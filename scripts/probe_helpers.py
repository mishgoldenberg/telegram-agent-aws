r"""Probe whether telegram_bot.py is safely importable for its parsing helpers."""

import os
import pathlib
import sys

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "probe")
os.environ.setdefault("TELEGRAM_USER_ID", "1")

NEEDED = [
    "_parse_date", "_parse_datetime_str", "_parse_event_times",
    "_parse_reminder_minutes", "_is_cancel", "_is_skip",
    "_fmt_date", "_fmt_dt", "_get_task_lists", "_resolve_list_name",
    "_YES_WORDS", "_NO_WORDS",
]

try:
    import telegram_bot as tb
except Exception as exc:  # noqa: BLE001
    print(f"  import FAILED: {type(exc).__name__}: {exc}")
    sys.exit(1)

print("  import OK - no blocking side effects")
missing = []
for name in NEEDED:
    ok = hasattr(tb, name)
    if not ok:
        missing.append(name)
    print(f"    {name:26} {'yes' if ok else 'MISSING'}")

print(f"\n  {'all helpers available' if not missing else 'missing: ' + ', '.join(missing)}")
