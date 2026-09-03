r"""
Unit check for _extract_date_intent — no model, no network, instant.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\date_intent_check.py
"""

import os
import pathlib
import sys
from datetime import date

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import agent  # noqa: E402

Y = date.today().year

CASES: list[tuple[str, object]] = [
    ("What's in the schedule for the next week?", ("next week", None)),
    ("06.09-12.09",                               (f"{Y}-09-06", f"{Y}-09-12")),
    ("6.9 - 12.9",                                (f"{Y}-09-06", f"{Y}-09-12")),
    ("What's on my calendar today?",              ("today", None)),
    ("what do I have planned this weekend",       ("2026-09-05", "2026-09-06")),
    ("am I free tomorrow",                        ("tomorrow", None)),
    ("что у меня на следующей неделе",            ("next week", None)),
    ("покажи календарь на сегодня",               ("today", None)),
    ("show me 6.9",                               (f"{Y}-09-06", None)),
    ("what about the day after tomorrow",         ("2026-09-06", None)),
    ("summarise my unread emails",                None),
    ("add milk to my shopping list",              None),
]


def main() -> None:
    print(f"today = {date.today().isoformat()}\n")
    passed = 0
    for text, expected in CASES:
        got = agent._extract_date_intent(text)
        ok = got == expected
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:40]:42} "
              f"want={str(expected):34} got={got}")
    print(f"\n  {passed}/{len(CASES)} correct")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
