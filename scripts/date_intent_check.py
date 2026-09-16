r"""
Unit check for _extract_date_intent — no model, no network, instant.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\date_intent_check.py
"""

import os
import pathlib
import sys
from datetime import date, timedelta

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import agent  # noqa: E402

Y = date.today().year

# Computed, never hardcoded. Two cases here were written as literal dates and
# started failing the moment the calendar moved past them - a test that reports
# a bug where there is none costs more than no test at all.
_TODAY = date.today()
_SAT = _TODAY + timedelta(days=(5 - _TODAY.weekday()) % 7)
_WEEKEND = (_SAT.isoformat(), (_SAT + timedelta(days=1)).isoformat())
_DAY_AFTER = ((_TODAY + timedelta(days=2)).isoformat(), None)

CASES: list[tuple[str, object]] = [
    ("What's in the schedule for the next week?", ("next week", None)),
    ("06.09-12.09",                               (f"{Y}-09-06", f"{Y}-09-12")),
    ("6.9 - 12.9",                                (f"{Y}-09-06", f"{Y}-09-12")),
    ("What's on my calendar today?",              ("today", None)),
    ("what do I have planned this weekend",       _WEEKEND),
    ("am I free tomorrow",                        ("tomorrow", None)),
    ("что у меня на следующей неделе",            ("next week", None)),
    ("покажи календарь на сегодня",               ("today", None)),
    ("show me 6.9",                               (f"{Y}-09-06", None)),
    ("what about the day after tomorrow",         _DAY_AFTER),
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
    return len(CASES) - passed


# ── Weekday names ─────────────────────────────────────────────────────────────
# Added after "put dentist on friday 14:00" reached the model with no date at
# all and came back as an October task.
def _next_weekday(target: int) -> str:
    today = date.today()
    return (today + timedelta(days=(target - today.weekday()) % 7)).isoformat()


WEEKDAY_CASES = [
    ("am I free on Friday?",            _next_weekday(4)),
    ("put dentist on friday 14:00",     _next_weekday(4)),
    ("schedule a call with mom sunday", _next_weekday(6)),
    ("что в среду",                     _next_weekday(2)),
]

CLOCK_CASES = [
    ("put dentist on friday 14:00",                "14:00"),
    ("add gym to my calendar tomorrow at 8pm",     "20:00"),
    ("book me 2 hours of study tomorrow at 9",     "09:00"),
    ("создай событие завтра в 10 утра тренировка", "10:00"),
    ("в 7 вечера",                                 "19:00"),
    ("what do i have today",                       None),
]

EVENT_CASES = [
    ("put dentist on friday 14:00",            True),
    ("schedule a call with mom sunday 19:00",   True),
    ("add task to call the dentist tomorrow",   False),
    ("remind me tomorrow at 9 to call the bank", False),   # reminder, not diary
    ("mark buy milk as done",                   False),
]


def _extra_checks() -> int:
    bad = 0
    print("\nweekday names")
    for text, want in WEEKDAY_CASES:
        got = agent._extract_date_intent(text)
        ok = got is not None and got[0] == want
        bad += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:38]:40} want={want} got={got}")

    print("\nclock time")
    for text, want in CLOCK_CASES:
        got = agent._extract_clock_time(text)
        ok = got == want
        bad += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:38]:40} want={want!s:6} got={got}")

    print("\nevent vs task")
    for text, want in EVENT_CASES:
        got = agent._looks_like_an_event(text)
        ok = got is want
        bad += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {text[:38]:40} want={want!s:6} got={got}")

    print(f"\n  {'all passed' if not bad else str(bad) + ' failed'}")
    return bad


if __name__ == "__main__":
    failed = main() + _extra_checks()
    sys.exit(1 if failed else 0)
