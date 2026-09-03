"""
S3 ObjectCreated -> transcription job.

Triggered when the ingest Lambda finishes writing a voice note. Reads the
object's metadata and enqueues a job for the local worker.

WHY THIS FUNCTION EXISTS AT ALL
-------------------------------
The ingest Lambda has everything it needs to enqueue the voice job directly,
which would make this hop look like ceremony. It is not, for one reason: it
makes the S3 PUT the commit point.

If ingest enqueued the job itself, the ordering would be: PUT, then send. A
crash between those two leaves audio in the bucket that nobody will ever
transcribe. Worse, sending first and putting second leaves a job pointing at an
object that does not exist, and the worker fails three times and dead-letters.

Driving the enqueue from the bucket's own event removes the window entirely: a
job exists if and only if the audio is durably stored.

It also means anything else that writes audio into this bucket gets
transcription for free, without knowing the queue exists.
"""

import json
import os
import time
import urllib.parse

import boto3

_s3 = boto3.client("s3")
_sqs = boto3.client("sqs")

QUEUE_URL = os.environ["QUEUE_URL"]


def log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}))


def handler(event, context):
    # One notification can carry several records; S3 batches under load.
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]

        # Object keys arrive URL-encoded in S3 event notifications. Skipping
        # the unquote is a classic bug: it works in testing and breaks the
        # moment a key contains a space or a non-ASCII character.
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        size = record["s3"]["object"].get("size", 0)

        # Metadata was set by the ingest Lambda at PUT time. S3 lowercases and
        # strips the "x-amz-meta-" prefix on the way back out.
        head = _s3.head_object(Bucket=bucket, Key=key)
        meta = head.get("Metadata", {})

        chat_id = meta.get("chat-id")
        update_id = meta.get("update-id")

        if not chat_id:
            # Something wrote here that was not our ingest path. Refuse to
            # guess: a job with no chat_id has nowhere to send its reply.
            log("skipped_no_chat_id", key=key)
            continue

        _sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "type": "voice",
                "chat_id": int(chat_id),
                "update_id": int(update_id) if update_id else None,
                "bucket": bucket,
                "key": key,
                "bytes": size,
                "received_at": int(time.time()),
            }),
        )
        log("voice_enqueued", key=key, chat_id=chat_id, bytes=size)

    return {"ok": True}
