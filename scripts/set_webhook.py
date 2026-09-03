r"""
Register (or clear) the Telegram webhook.

Run from envs/dev with WEBHOOK_URL and WEBHOOK_SECRET exported from
terraform output, so no secret is ever typed or pasted:

    $env:WEBHOOK_URL    = terraform output -raw webhook_url
    $env:WEBHOOK_SECRET = terraform output -raw webhook_secret
    python ..\..\scripts\set_webhook.py

    python ..\..\scripts\set_webhook.py --delete   # revert to long polling

NOTE ON THE CUTOVER: Telegram allows a bot to use EITHER long polling or a
webhook, never both. Calling setWebhook stops getUpdates working, so the old
polling bot will start returning 409 Conflict. --delete reverses it in seconds.
"""

import json
import os
import pathlib
import re
import sys
import urllib.parse
import urllib.request

ENV_FILE = pathlib.Path(
    os.environ.get("ASSISTANT_ENV", r"C:\Users\User\Documents\llm-agent-test\assistant\.env")
)


def bot_token() -> str:
    text = ENV_FILE.read_text(encoding="utf-8", errors="replace")
    pairs = dict(re.findall(r"^\s*([A-Z_]+)\s*=\s*(.+?)\s*$", text, re.M))
    token = pairs.get("TELEGRAM_BOT_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        sys.exit(f"no TELEGRAM_BOT_TOKEN in {ENV_FILE}")
    return token


def call(method: str, **params):
    url = f"https://api.telegram.org/bot{bot_token()}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
        return json.loads(r.read())


def main() -> None:
    me = call("getMe")["result"]
    print(f"  bot: @{me['username']} ({me['first_name']})")

    if "--delete" in sys.argv:
        res = call("deleteWebhook", drop_pending_updates="false")
        print(f"  deleteWebhook: ok={res['ok']} — long polling is available again")
    else:
        url = os.environ.get("WEBHOOK_URL")
        secret = os.environ.get("WEBHOOK_SECRET")
        if not url or not secret:
            sys.exit("set WEBHOOK_URL and WEBHOOK_SECRET from terraform output first")

        res = call(
            "setWebhook",
            url=url,
            secret_token=secret,
            # Only ask for what the ingest Lambda handles. Telegram will not
            # send callback queries, polls, or channel posts, so they cannot
            # cost an invocation.
            allowed_updates=json.dumps(["message", "edited_message"]),
            # Discard anything queued while the bot was offline; replying to
            # hours-old messages on cutover is confusing.
            drop_pending_updates="true",
        )
        print(f"  setWebhook: ok={res['ok']} — {res.get('description')}")

    info = call("getWebhookInfo")["result"]
    registered = info.get("url", "")
    # Print only enough of the URL to confirm identity; it contains the secret path.
    shown = f"{registered[:44]}…{registered[-6:]}" if len(registered) > 52 else (registered or "(none)")
    print(f"  registered:      {shown}")
    print(f"  pending updates: {info.get('pending_update_count')}")
    print(f"  allowed updates: {info.get('allowed_updates')}")
    print(f"  last error:      {info.get('last_error_message', 'none')}")


if __name__ == "__main__":
    main()
