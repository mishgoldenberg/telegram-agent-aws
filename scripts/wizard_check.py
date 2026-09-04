r"""
Drive the /task and /event wizards end to end without Telegram, AWS, or a model.

State is passed hand to hand exactly as the worker does it via DynamoDB, so
this exercises the real step machine. The final confirm step is answered "no"
so the suite creates nothing in Google.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\wizard_check.py
"""

import os
import pathlib
import re
import sys

WORKER = pathlib.Path(r"C:\Users\User\Documents\telegram-agent-aws\worker").resolve()
ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(WORKER))
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import commands  # noqa: E402
import wizards  # noqa: E402

failures = 0


def strip(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).replace("\n", " ⏎ ")[:96]


def run(label: str, opening: str, turns: list[tuple[str, str]]) -> None:
    """turns = [(user_message, substring expected in the reply), ...]"""
    global failures
    print(f"\n{label}")

    reply = commands.handle(opening, 700196974, lambda c: None)
    state = commands.take_pending_wizard()
    ok = state is not None
    failures += not ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {opening:22} -> {strip(reply or '')}")

    for msg, expect in turns:
        if state is None:
            print(f"  [FAIL] {msg:22} -> flow already ended, expected {expect!r}")
            failures += 1
            break
        reply, state = wizards.advance(state, msg)
        ok = expect.lower() in (reply or "").lower()
        failures += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg:22} -> {strip(reply or '')}")

    ended = state is None
    print(f"  [{'PASS' if ended else 'FAIL'}] flow cleared at end: {ended}")
    failures += not ended


run("/task — happy path, declined at confirm",
    "/task",
    [("Buy milk",        "Step 2/5"),
     ("tomorrow",        "Step 3/5"),
     ("-",               "Step 4/5"),
     ("-",               "Step 5/5"),
     ("no",              "cancelled")])

run("/task — invalid date is re-prompted, not accepted",
    "/task",
    [("Call dentist",    "Step 2/5"),
     ("not a date",      "couldn't understand"),
     ("tomorrow",        "Step 3/5"),
     ("-",               "Step 4/5"),
     ("-",               "Step 5/5"),
     ("no",              "cancelled")])

run("/event — happy path, declined at confirm",
    "/event",
    [("Dentist",              "Step 2/5"),
     ("tomorrow 14:00",       "Step 3/5"),
     ("30 min",               "Step 4/5"),
     ("-",                    "Step 5/5"),
     ("no",                   "cancelled")])

run("/event — unparseable time is re-prompted",
    "/event",
    [("Standup",        "Step 2/5"),
     ("sometime soon",  "couldn't parse"),
     ("tomorrow 09:00", "Step 3/5"),
     ("-",              "Step 4/5"),
     ("-",              "Step 5/5"),
     ("no",             "cancelled")])

run("/task — /cancel mid-flow",
    "/task",
    [("Something",  "Step 2/5"),
     ("/cancel",    "cancelled")])

print(f"\n  {'all passed' if not failures else str(failures) + ' FAILED'}")
sys.exit(1 if failures else 0)
