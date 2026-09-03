"""
Local SQS worker — the half of the pipeline that runs on your own hardware.

Long-polls the job queue, runs the existing agent against a local Ollama, and
replies to Telegram directly. AWS is never called inbound: this process makes
only outbound HTTPS connections, so nothing at home is exposed and it works
behind CGNAT or any consumer router.

    AWS  --(job)-->  SQS  <--long poll--  worker  --(reply)-->  Telegram

WHY THE REPLY DOES NOT GO BACK THROUGH AWS
------------------------------------------
The obvious design sends the answer back to a Lambda which forwards it to
Telegram. That needs a second API Gateway or a response queue, and buys
nothing: this process already has the bot token and can call the Bot API
directly. Once a job is dequeued, AWS is out of the loop.

Run:  python worker/worker.py
Stop: Ctrl+C (finishes the in-flight job first)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import boto3

# ── configuration ────────────────────────────────────────────────────────────

HERE = Path(__file__).resolve().parent


def _load_env() -> None:
    """Minimal .env reader so the worker has no dependency on python-dotenv."""
    envfile = HERE / ".env"
    if not envfile.exists():
        sys.exit(f"missing {envfile} — run scripts/bootstrap_worker.ps1 first")
    for line in envfile.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

QUEUE_URL = os.environ["QUEUE_URL"]
TABLE = os.environ["TABLE_NAME"]
SSM_PREFIX = os.environ["SSM_PREFIX"]
ASSISTANT_DIR = Path(os.environ["ASSISTANT_DIR"]).resolve()

# History is trimmed rather than unbounded. Every turn is re-sent to the model,
# so an ever-growing history means every reply gets slower and the context
# window eventually overflows. 20 turns is roughly a full conversation.
MAX_HISTORY_TURNS = 20
SESSION_TTL_SECONDS = 7 * 24 * 3600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("worker")

# ── the existing assistant ───────────────────────────────────────────────────
#
# agent.py and whisper_stt.py read relative paths (memory.db, token.json), so
# the process must run FROM the assistant directory, not merely import from it.
sys.path.insert(0, str(ASSISTANT_DIR))
os.chdir(ASSISTANT_DIR)

from agent import run_agent          # noqa: E402
from whisper_stt import transcribe   # noqa: E402

# ── AWS clients ──────────────────────────────────────────────────────────────

_sqs = boto3.client("sqs")
_ddb = boto3.client("dynamodb")
_s3 = boto3.client("s3")
_ssm = boto3.client("ssm")

_BOT_TOKEN: str | None = None


def bot_token() -> str:
    """Read the token from Parameter Store once, so it lives in exactly one place."""
    global _BOT_TOKEN
    if _BOT_TOKEN is None:
        _BOT_TOKEN = _ssm.get_parameter(
            Name=f"{SSM_PREFIX}/bot_token", WithDecryption=True
        )["Parameter"]["Value"]
    return _BOT_TOKEN


# ── Telegram ─────────────────────────────────────────────────────────────────

TELEGRAM_MAX = 4096


def tg(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{bot_token()}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
        return json.loads(r.read())


def send(chat_id: int, text: str, **kw) -> None:
    """Send a reply, splitting on Telegram's 4096-character limit."""
    if not text:
        return
    for i in range(0, len(text), TELEGRAM_MAX):
        chunk = text[i:i + TELEGRAM_MAX]
        try:
            tg("sendMessage", chat_id=chat_id, text=chunk, **kw)
        except Exception:
            # Retry once without parse_mode: the usual cause is model output
            # containing markup Telegram rejects as malformed HTML.
            if kw:
                tg("sendMessage", chat_id=chat_id, text=chunk)
            else:
                raise


# ── conversation state ───────────────────────────────────────────────────────
#
# This is what the DynamoDB table is for. In the polling bot, history lived in
# a process-local dict, so a restart wiped every conversation. Moving it out is
# what makes the ingest path stateless — and it is the actual hard part of the
# migration, not the API Gateway wiring.


def load_history(chat_id: int) -> list:
    resp = _ddb.get_item(
        TableName=TABLE,
        Key={"pk": {"S": f"chat#{chat_id}"}, "sk": {"S": "session"}},
    )
    item = resp.get("Item")
    if not item:
        return []

    # TTL deletion is asynchronous — DynamoDB sweeps expired items within about
    # 48 hours, so an expired item is still READABLE until then. Enforce it
    # here rather than trusting the sweeper.
    if int(item.get("expires_at", {}).get("N", "0")) < int(time.time()):
        return []

    try:
        return json.loads(item["history"]["S"])
    except (KeyError, json.JSONDecodeError):
        log.warning("corrupt history for chat %s, starting fresh", chat_id)
        return []


def save_history(chat_id: int, history: list) -> None:
    trimmed = history[-(MAX_HISTORY_TURNS * 2):]
    _ddb.put_item(
        TableName=TABLE,
        Item={
            "pk": {"S": f"chat#{chat_id}"},
            "sk": {"S": "session"},
            "history": {"S": json.dumps(trimmed, ensure_ascii=False)},
            "expires_at": {"N": str(int(time.time()) + SESSION_TTL_SECONDS)},
            "updated_at": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        },
    )


# ── job handling ─────────────────────────────────────────────────────────────


def fetch_voice_text(bucket: str, key: str) -> str:
    """Download the voice note and transcribe it locally with Whisper."""
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        path = tmp.name
    try:
        _s3.download_file(bucket, key, path)
        t0 = time.time()
        text = transcribe(path)
        log.info("transcribed in %.1fs: %s", time.time() - t0, text[:70])
        return text
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def handle(job: dict) -> None:
    chat_id = job["chat_id"]

    if job["type"] == "voice":
        tg("sendChatAction", chat_id=chat_id, action="typing")
        text = fetch_voice_text(job["bucket"], job["key"])
        if not text:
            send(chat_id, "⚠️ Couldn't hear anything — try again.")
            return
        # Echo the transcription so a misheard word is visible rather than
        # silently changing what the agent was asked.
        send(chat_id, f"🎤 {text}")
    else:
        text = job["text"]

    tg("sendChatAction", chat_id=chat_id, action="typing")

    history = load_history(chat_id)
    t0 = time.time()
    reply = run_agent(text, history=list(history), chat_id=chat_id)
    log.info("agent replied in %.1fs (%d chars)", time.time() - t0, len(reply or ""))

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    save_history(chat_id, history)

    send(chat_id, reply)


# ── main loop ────────────────────────────────────────────────────────────────

_running = True


def _stop(signum, frame):
    global _running
    log.info("shutdown requested — finishing the in-flight job")
    _running = False


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)


def main() -> None:
    log.info("worker up — polling %s", QUEUE_URL.rsplit("/", 1)[-1])
    log.info("assistant: %s", ASSISTANT_DIR)

    while _running:
        # WaitTimeSeconds=20 is long polling, and it is a COST control as much
        # as a latency one. At 20s this makes ~130k ReceiveMessage calls a
        # month, inside the 1M always-free tier. At 1s it would be 2.6M and
        # start costing money for identical behaviour.
        resp = _sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=300,
        )

        for msg in resp.get("Messages", []):
            body = msg["Body"]
            try:
                job = json.loads(body)
                log.info("job: %s chat=%s", job.get("type"), job.get("chat_id"))
                handle(job)
            except Exception:
                # Do NOT delete the message. Letting the visibility timeout
                # expire returns it to the queue; after maxReceiveCount
                # attempts SQS moves it to the DLQ, which fires an alarm.
                # Deleting here would silently lose the job.
                log.exception("job failed, leaving it for redelivery: %s", body[:200])
                continue

            _sqs.delete_message(
                QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"]
            )

    log.info("worker stopped")


if __name__ == "__main__":
    main()
