r"""
Prove wizard state survives a round trip through DynamoDB.

wizard_check.py passes state hand to hand in memory. That is not the real test:
in production each user message is a separate SQS job, and the worker may even
be restarted between turns. This drives the same flow but persists and reloads
from the real table between EVERY step, which is what actually happens.

Answers "no" at confirm, so nothing is created in Google.

    cd C:\Users\User\Documents\telegram-agent-aws\worker
    ..\..\llm-agent-test\assistant\venv\Scripts\python.exe ..\scripts\wizard_persistence_check.py
"""

import os
import pathlib
import re
import sys

WORKER = pathlib.Path(r"C:\Users\User\Documents\telegram-agent-aws\worker").resolve()
sys.path.insert(0, str(WORKER))
os.chdir(WORKER)

import worker as w  # noqa: E402  (loads .env, boto3 clients, agent)
import commands  # noqa: E402
import wizards  # noqa: E402

CHAT = 999_000_001  # not a real chat; nothing is sent to Telegram
failures = 0


def strip(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").replace("\n", " ⏎ ")[:78]


def main() -> None:
    global failures
    w.clear_wizard(CHAT)

    reply = commands.handle("/task", CHAT, lambda c: None)
    state = commands.take_pending_wizard()
    w.save_wizard(CHAT, state)
    print(f"  start   -> {strip(reply)}")

    for msg, expect in [("Persisted task", "Step 2/5"),
                        ("tomorrow", "Step 3/5"),
                        ("-", "Step 4/5"),
                        ("-", "Step 5/5"),
                        ("no", "Cancelled")]:
        # THE POINT: reload from DynamoDB, exactly as a fresh job would.
        loaded = w.load_wizard(CHAT)
        if loaded is None:
            print(f"  [FAIL] {msg:16} -> no state in DynamoDB")
            failures += 1
            break
        reply, new_state = wizards.advance(loaded, msg)
        if new_state is None:
            w.clear_wizard(CHAT)
        else:
            w.save_wizard(CHAT, new_state)
        ok = expect.lower() in (reply or "").lower()
        failures += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg:16} -> {strip(reply)}")

    left = w.load_wizard(CHAT)
    ok = left is None
    failures += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] state cleared from DynamoDB after finish")

    print(f"\n  {'all passed' if not failures else str(failures) + ' FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
