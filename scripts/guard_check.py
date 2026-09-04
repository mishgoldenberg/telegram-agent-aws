r"""
Unit checks for the agent's Python-side guards. No model, no network.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\guard_check.py
"""

import os
import pathlib
import sys
from datetime import date, timedelta

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import agent  # noqa: E402

TODAY = date.today()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()
NEXT_MON = (TODAY - timedelta(days=TODAY.weekday()) + timedelta(weeks=1)).isoformat()

ACK_CASES: list[tuple[str, bool]] = [
    # Replies that are ABOUT language, not answers — must be discarded.
    ("Sure, I will reply only in English and avoid using any other languages!", True),
    ("I will adhere to the instructions and only reply in English.", True),
    ("Going forward, I will avoid using any other language.", True),
    ("Буду отвечать только на русском.", True),
    # Real answers — must be kept.
    ("Your haircut appointment is on Sunday at 16:00.", False),
    ("Here is your calendar:\n\nTuesday 20:30 Gym", False),
    ("The task was added for tomorrow.", False),
    ("", False),
]

ISO_CASES: list[tuple[str, str]] = [
    ("today", TODAY.isoformat()),
    ("tomorrow", TOMORROW),
    ("next week", NEXT_MON),
    ("2026-09-06", "2026-09-06"),
    ("2023-10-19T09:00", "2023-10-19"),  # already ISO: passed through, trimmed
]


def main() -> None:
    failed = 0

    print("acknowledgement detector")
    for text, expected in ACK_CASES:
        got = agent._is_language_acknowledgement(text)
        ok = got == expected
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] want={str(expected):5} got={str(got):5} "
              f"{text[:52]!r}")

    print("\nkeyword -> ISO")
    for value, expected in ISO_CASES:
        got = agent._keyword_to_iso(value)
        ok = got == expected
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {value:18} want={expected:12} got={got}")

    print(f"\n  {'all passed' if not failed else str(failed) + ' FAILED'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
