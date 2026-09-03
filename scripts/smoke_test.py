r"""
End-to-end smoke test.

Posts a synthetic Telegram update to the real API Gateway endpoint with the
real secret header, exercising every hop of the ingest path:

    HTTPS -> API Gateway -> ingest Lambda -> dedupe (DynamoDB) -> SQS
          -> local worker -> agent -> Ollama -> Telegram reply

A reply arriving in Telegram is the pass condition. It also re-posts the same
update_id to prove the idempotency check drops the duplicate.

Usage, from envs/dev:
    $env:WEBHOOK_URL    = terraform output -raw webhook_url
    $env:WEBHOOK_SECRET = terraform output -raw webhook_secret
    python ..\..\scripts\smoke_test.py
"""

import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ENV_FILE = pathlib.Path(
    os.environ.get("ASSISTANT_ENV", r"C:\Users\User\Documents\llm-agent-test\assistant\.env")
)

TEXT = os.environ.get("SMOKE_TEXT", "Reply with exactly: pipeline works")


def user_id() -> int:
    pairs = dict(re.findall(r"^\s*([A-Z_]+)\s*=\s*(.+?)\s*$",
                            ENV_FILE.read_text(encoding="utf-8", errors="replace"), re.M))
    return int(pairs["TELEGRAM_USER_ID"].strip().strip('"').strip("'"))


def post(url: str, payload: dict, secret: str | None) -> tuple[int, str]:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def update(uid: int, update_id: int) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {"id": uid, "is_bot": False, "first_name": "Mish"},
            "chat": {"id": uid, "type": "private"},
            "date": int(time.time()),
            "text": TEXT,
        },
    }


def main() -> None:
    url = os.environ.get("WEBHOOK_URL")
    secret = os.environ.get("WEBHOOK_SECRET")
    if not url or not secret:
        sys.exit("set WEBHOOK_URL and WEBHOOK_SECRET from terraform output first")

    uid = user_id()
    uid_n = int(time.time())

    print("1. wrong secret token -> expect 403")
    code, body = post(url, update(uid, uid_n), "obviously-wrong")
    print(f"   {code} {body!r}  {'PASS' if code == 403 else 'FAIL'}")

    print("2. no secret token at all -> expect 403")
    code, body = post(url, update(uid, uid_n), None)
    print(f"   {code} {body!r}  {'PASS' if code == 403 else 'FAIL'}")

    print("3. wrong user id -> expect 200, silently ignored")
    code, body = post(url, update(999_999_999, uid_n + 1), secret)
    print(f"   {code} {body!r}  {'PASS' if code == 200 else 'FAIL'}")

    print("4. genuine update -> expect 200, then a Telegram reply")
    code, body = post(url, update(uid, uid_n + 2), secret)
    print(f"   {code} {body!r}  {'PASS' if code == 200 else 'FAIL'}")

    print("5. SAME update_id again -> expect 200 and dropped as duplicate")
    code, body = post(url, update(uid, uid_n + 2), secret)
    print(f"   {code} {body!r}  {'PASS' if code == 200 else 'FAIL'}")
    print("   (check the ingest log for duplicate_dropped)")

    print("\nWatch Telegram — one reply should arrive, not two.")


if __name__ == "__main__":
    main()
