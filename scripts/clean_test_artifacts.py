r"""
List (and optionally delete) the calendar events and tasks that testing wrote.

The corpus exercises real write tools against the real Google account, so a
full run leaves real rows behind - "Gym session", "Renew passport" and so on.
This finds them and shows them; it deletes nothing unless you pass --delete,
and it prints exactly what it would remove first either way.

    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\clean_test_artifacts.py
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\clean_test_artifacts.py --delete

Anything created from here on should use scripts/dry_writes.py instead, which
stubs the write tools and leaves the account untouched.
"""

import os
import pathlib
import sys
from datetime import date, timedelta

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
if str(ASSISTANT) not in sys.path:
    sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import tools  # noqa: E402

# Titles the corpus is known to produce. Deliberately exact - a substring match
# would sweep up real entries that happen to mention the gym.
TEST_TITLES = {
    "gym session", "study session", "call mom", "dentist",
    "renew passport", "buy milk", "купить хлеб", "call the dentist",
    "study", "тренировка",
}


def main() -> None:
    delete = "--delete" in sys.argv
    today = date.today()
    window = (today.isoformat(), (today + timedelta(days=14)).isoformat())

    events = [e for e in tools.list_calendar_events(*window)
              if (e.get("title") or "").strip().lower() in TEST_TITLES]
    tasks = [t for t in tools.list_tasks()
             if (t.get("title") or "").strip().lower() in TEST_TITLES]

    print(f"Calendar events matching test titles ({window[0]}..{window[1]}):")
    for e in events:
        print(f"  {e['day']} {e['time']}  {e['title']}")
    print(f"\nTasks matching test titles:")
    for t in tasks:
        print(f"  {t.get('title')}")

    if not delete:
        print(f"\n{len(events)} event(s), {len(tasks)} task(s). "
              f"Re-run with --delete to remove them.")
        return

    for e in events:
        try:
            tools.delete_calendar_event(title=e["title"], date_str=e["day"], confirm=True)
            print(f"  deleted event: {e['title']} ({e['day']})")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED event {e['title']}: {exc}")
    for t in tasks:
        try:
            tools.complete_task(task_title=t["title"])
            print(f"  completed task: {t['title']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED task {t['title']}: {exc}")


if __name__ == "__main__":
    main()
