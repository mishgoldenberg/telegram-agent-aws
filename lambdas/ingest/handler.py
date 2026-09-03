"""
Telegram webhook ingest.

Runs behind API Gateway HTTP API. Its job is to accept an update, prove it is
genuinely from Telegram, make sure it is handled exactly once, and hand it to
the work queue — then return 200 as fast as possible.

It deliberately does NOT talk to Ollama, run the agent, or reply to the user.
All of that happens on the local worker. This function is a doorman.

WHY IT ALWAYS RETURNS 200
-------------------------
Telegram retries any webhook that does not return 2xx, with backoff. A 500 on a
message we cannot process means that message comes back forever. So genuine
failures are logged and swallowed: the update is dropped deliberately rather
than retried indefinitely. The only non-200 is 403 for a failed secret check,
which is not Telegram and should not be encouraged.
"""

import json
import os
import time
import urllib.parse
import urllib.request
import uuid

import boto3
from botocore.exceptions import ClientError

# Clients are created at module scope so they survive across invocations on a
# warm container. Creating a boto3 client costs ~100ms; doing it per invoke
# would roughly double the duration of this function.
_ssm = boto3.client("ssm")
_ddb = boto3.client("dynamodb")
_sqs = boto3.client("sqs")
_s3 = boto3.client("s3")

TABLE = os.environ["TABLE_NAME"]
QUEUE_URL = os.environ["QUEUE_URL"]
BUCKET = os.environ["AUDIO_BUCKET"]
PREFIX = os.environ.get("AUDIO_PREFIX", "voice/")
SSM_PREFIX = os.environ["SSM_PREFIX"]
ALLOWED_USER = int(os.environ["ALLOWED_USER_ID"])

DEDUPE_TTL_SECONDS = 86_400  # 24h; Telegram gives up retrying long before this

# Populated on first use and reused while the container lives.
_secrets: dict[str, str] = {}


def log(event: str, **fields) -> None:
    """One JSON object per line, so CloudWatch Logs Insights can query fields."""
    print(json.dumps({"event": event, **fields}))


def _secret(name: str) -> str:
    """
    Fetch a SecureString from Parameter Store, caching for the container's life.

    Parameter Store rather than Secrets Manager: Secrets Manager is $0.40 per
    secret per month, which for three secrets is 24% of this project's entire
    $5 budget. Parameter Store Standard is free and equally encrypted. What it
    gives up is native rotation, which nothing here uses.
    """
    if name not in _secrets:
        resp = _ssm.get_parameter(Name=f"{SSM_PREFIX}/{name}", WithDecryption=True)
        _secrets[name] = resp["Parameter"]["Value"]
    return _secrets[name]


def _telegram(method: str, **params):
    """Call the Telegram Bot API. urllib, so the package needs no dependencies."""
    url = f"https://api.telegram.org/bot{_secret('bot_token')}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=8) as r:
        return json.loads(r.read())


def _already_seen(update_id: int) -> bool:
    """
    Idempotency, via a conditional write.

    Telegram redelivers an update if it does not get a timely 2xx — and it will
    happen, on a cold start or a slow moment. Without this, one voice note can
    be transcribed and answered two or three times.

    The condition is what makes this safe: PutItem with
    attribute_not_exists(pk) is atomic at the item level, so two concurrent
    invocations racing on the same update cannot both win. Checking with GetItem
    and then writing would leave exactly that race open.
    """
    try:
        _ddb.put_item(
            TableName=TABLE,
            Item={
                "pk": {"S": f"update#{update_id}"},
                "sk": {"S": "dedupe"},
                "expires_at": {"N": str(int(time.time()) + DEDUPE_TTL_SECONDS)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return False
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True
        raise


def _store_voice(file_id: str, chat_id: int, update_id: int) -> str:
    """
    Download the audio from Telegram and put it in S3.

    A webhook update contains a file_id, never the audio itself. Retrieving it
    is two calls: getFile for a path, then a download from a different host.

    The S3 PUT is deliberately the commit point for the voice path. The
    transcription job is enqueued by the bucket's ObjectCreated event, not by
    this function, so a job can never reference audio that was not stored.
    """
    info = _telegram("getFile", file_id=file_id)
    path = info["result"]["file_path"]

    url = f"https://api.telegram.org/file/bot{_secret('bot_token')}/{path}"
    with urllib.request.urlopen(url, timeout=10) as r:
        audio = r.read()

    key = f"{PREFIX}{chat_id}/{update_id}-{uuid.uuid4().hex[:8]}.ogg"

    # chat_id and update_id ride along as object metadata so the S3 event
    # handler can build the job without re-reading anything else. The event
    # notification itself carries only the bucket and key.
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=audio,
        ContentType="audio/ogg",
        Metadata={"chat-id": str(chat_id), "update-id": str(update_id)},
    )
    log("voice_stored", key=key, bytes=len(audio))
    return key


def _enqueue(job: dict) -> None:
    _sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(job))


def handler(event, context):
    # API Gateway HTTP API v2 lowercases header names. Telegram sends this
    # header on every request when a secret_token was supplied to setWebhook.
    #
    # This is the actual authentication. The unguessable URL path is a second
    # layer, not a substitute: without this check, anyone who learned the URL
    # could inject arbitrary updates and drive the assistant.
    headers = event.get("headers") or {}
    if headers.get("x-telegram-bot-api-secret-token") != _secret("webhook_secret"):
        log("rejected_bad_secret", ip=event.get("requestContext", {}).get("http", {}).get("sourceIp"))
        return {"statusCode": 403, "body": "forbidden"}

    try:
        update = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        log("bad_json")
        return {"statusCode": 200, "body": "ok"}

    update_id = update.get("update_id")
    message = update.get("message") or update.get("edited_message")

    if update_id is None or not message:
        # Channel posts, poll answers, callback queries and so on. Nothing to
        # do, but still a 200 so Telegram does not retry.
        log("ignored_non_message", keys=list(update.keys()))
        return {"statusCode": 200, "body": "ok"}

    user_id = (message.get("from") or {}).get("id")
    chat_id = (message.get("chat") or {}).get("id")

    # Single-user bot. The webhook URL is public, so this is the check that
    # stops a stranger who found it from using your assistant and your GPU.
    if user_id != ALLOWED_USER:
        log("rejected_unknown_user", user_id=user_id)
        return {"statusCode": 200, "body": "ok"}

    if _already_seen(update_id):
        log("duplicate_dropped", update_id=update_id)
        return {"statusCode": 200, "body": "ok"}

    try:
        if "voice" in message:
            _store_voice(message["voice"]["file_id"], chat_id, update_id)
            # No enqueue here. The S3 ObjectCreated event does it, which
            # guarantees the audio exists before any worker is told about it.
        elif "text" in message:
            _enqueue({
                "type": "text",
                "chat_id": chat_id,
                "update_id": update_id,
                "text": message["text"],
                "received_at": int(time.time()),
            })
            log("text_enqueued", update_id=update_id, chars=len(message["text"]))
        else:
            log("unsupported_message_type", update_id=update_id, keys=list(message.keys()))
    except Exception as exc:
        # Swallow deliberately: see the module docstring. A 500 here would make
        # Telegram redeliver this update indefinitely.
        log("processing_failed", update_id=update_id, error=f"{type(exc).__name__}: {exc}")

    return {"statusCode": 200, "body": "ok"}
