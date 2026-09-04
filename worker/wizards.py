r"""
/task and /event guided flows, with state in DynamoDB instead of process memory.

WHY THIS EXISTS
---------------
In polling mode these were python-telegram-bot ConversationHandlers holding
state in context.chat_data - a dict inside the bot process. Webhook mode has no
bot process: every message is a fresh Lambda invocation and a fresh worker
iteration, so that dict cannot exist.

This is the part of the migration that is actually hard. Everything else was
plumbing; a multi-turn flow genuinely needs somewhere to remember which step
the user is on, which is why the DynamoDB table was in the design from the
start.

PARSERS ARE IMPORTED, NOT REWRITTEN
-----------------------------------
Date, time, duration, reminder and colour parsing all come from
telegram_bot.py. That module imports cleanly with no side effects, and its
parsers already handle "tomorrow 14:00 for 90 min", "Friday 14:00-15:30",
day-first dates and Russian keywords. Reimplementing them here would guarantee
the two paths drift apart.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

ASSISTANT = Path(r"C:\Users\User\Documents\llm-agent-test\assistant")
if str(ASSISTANT) not in sys.path:
    sys.path.insert(0, str(ASSISTANT))

# telegram_bot reads these at import time. The real token lives in SSM and is
# not needed for the parsing helpers, only for the Application it never builds
# here, so a placeholder is enough.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "unused-import-only")
os.environ.setdefault("TELEGRAM_USER_ID", "0")

import telegram_bot as tb  # noqa: E402
from tools import (  # noqa: E402
    create_task,
    create_calendar_event,
    color_options_text,
)

WIZARD_TTL_SECONDS = 30 * 60  # abandoned flows expire; nobody resumes after that


# ── step tables ───────────────────────────────────────────────────────────────

TASK_STEPS = ["name", "due_date", "due_datetime", "list", "confirm"]
EVENT_STEPS = ["name", "datetime", "reminder", "color", "confirm"]

CANCELLED = "❌ Cancelled."


def _fmt_date(d: date) -> str:
    return tb._fmt_date(d)


def _fmt_dt(dt: datetime) -> str:
    return tb._fmt_dt(dt)


def _is_cancel(text: str) -> bool:
    return tb._is_cancel(text)


def _is_skip(text: str) -> bool:
    return tb._is_skip(text)


# ── entry ─────────────────────────────────────────────────────────────────────

def start(kind: str) -> tuple[str, dict]:
    """Begin a wizard. Returns (reply, state)."""
    if kind == "task":
        try:
            lists = tb._get_task_lists()
        except Exception:  # noqa: BLE001
            lists = []
        state = {"kind": "task", "step": "name",
                 "data": {"lists": [{"id": l["id"], "title": l["title"]} for l in lists]}}
        return ("📝 <b>New Task — Step 1/5</b>\n\nTask name?", state)

    state = {"kind": "event", "step": "name", "data": {}}
    return ("📅 <b>New Event — Step 1/5</b>\n\nEvent name?", state)


# ── task flow ─────────────────────────────────────────────────────────────────

def _task_step(state: dict, text: str) -> tuple[str, dict | None]:
    step = state["step"]
    data = state["data"]

    if step == "name":
        if not text:
            return "Please enter a name for the task.", state
        data["name"] = text
        state["step"] = "due_date"
        return (
            "📅 <b>Step 2/5 — Due date</b> (date only)\n\n"
            "Examples: <code>tomorrow</code>  <code>Friday</code>  <code>8.6</code>  "
            "<code>2026-06-12</code>\n"
            "Reply <code>-</code> to skip.", state)

    if step == "due_date":
        if _is_skip(text):
            data["due_date"] = None
        else:
            d = tb._parse_date(text)
            if d is None:
                return ("⚠️ Couldn't understand that date.\n"
                        "Try: <code>tomorrow</code>, <code>Friday</code>, "
                        "<code>8.6</code>, or <code>-</code> to skip.", state)
            data["due_date"] = d.isoformat()
        state["step"] = "due_datetime"
        return (
            "🕐 <b>Step 3/5 — Date and time</b> (for Calendar visibility)\n\n"
            "Examples: <code>tomorrow 15:00</code>  <code>Friday 9am</code>\n"
            "⚠️ The Tasks API cannot store a time — setting one also creates a "
            "Calendar event at that moment.\n"
            "Reply <code>-</code> to skip.", state)

    if step == "due_datetime":
        if _is_skip(text):
            data["due_datetime"] = None
        else:
            dt = tb._parse_datetime_str(text)
            if dt is None:
                return ("⚠️ Couldn't understand that date/time.\n"
                        "Try: <code>tomorrow 15:00</code>, <code>Friday 9am</code>, "
                        "or <code>-</code> to skip.", state)
            data["due_datetime"] = dt.strftime("%Y-%m-%dT%H:%M:%S")
        state["step"] = "list"
        lists = data.get("lists", [])
        lines = ("\n".join(f"  {i+1}. {l['title']}{' ← default' if i == 0 else ''}"
                           for i, l in enumerate(lists))
                 if lists else "  (could not fetch lists)")
        return (f"📋 <b>Step 4/5 — List</b>\n\n{lines}\n\n"
                f"Reply with a number, a list name, or <code>-</code> for the default.", state)

    if step == "list":
        lists = data.get("lists", [])
        if _is_skip(text):
            data["list_title"] = lists[0]["title"] if lists else "primary"
        elif text.isdigit():
            idx = int(text) - 1
            if not (0 <= idx < len(lists)):
                return (f"⚠️ Invalid number. Choose 1–{len(lists)} or a list name.", state)
            data["list_title"] = lists[idx]["title"]
        else:
            try:
                _, title = tb._resolve_list_name(text)
                data["list_title"] = title
            except ValueError as exc:
                return f"⚠️ {exc}", state

        state["step"] = "confirm"
        due = data.get("due_date")
        dtv = data.get("due_datetime")
        due_line = (f"  Due date:    {_fmt_date(date.fromisoformat(due))}"
                    if due else "  Due date:    — (none)")
        dt_line = (f"  Date/time:   {_fmt_dt(datetime.fromisoformat(dtv))}  (+ Calendar event)"
                   if dtv else "  Date/time:   — (no Calendar event)")
        return (
            f"📋 <b>Step 5/5 — Confirm</b>\n\n"
            f"<b>Task to create:</b>\n"
            f"  Name:        {data['name']}\n"
            f"{due_line}\n{dt_line}\n"
            f"  List:        {data['list_title']}\n\n"
            f"Create this task? Reply <b>yes</b> or <b>no</b>.", state)

    # confirm
    low = text.strip().lower()
    if low in tb._NO_WORDS:
        return CANCELLED, None
    if low not in tb._YES_WORDS:
        return "Please reply <b>yes</b> or <b>no</b>.", state

    try:
        res = create_task(
            data["name"],
            due_date=data.get("due_date"),
            due_datetime=data.get("due_datetime"),
            list_name=data.get("list_title"),
        )
    except Exception as exc:  # noqa: BLE001
        return f"⚠️ Failed to create task: {type(exc).__name__}: {exc}", None

    if isinstance(res, dict) and res.get("error"):
        return f"⚠️ {res['error']}", None
    return (f"✅ Task created\n   {data['name']}\n"
            f"   List: {data.get('list_title', 'default')}"), None


# ── event flow ────────────────────────────────────────────────────────────────

def _event_step(state: dict, text: str) -> tuple[str, dict | None]:
    step = state["step"]
    data = state["data"]

    if step == "name":
        if not text:
            return "Please enter a name for the event.", state
        data["name"] = text
        state["step"] = "datetime"
        return (
            "🕐 <b>Step 2/5 — Date and time</b>\n\n"
            "Examples:\n"
            "  <code>tomorrow 14:00</code>  → 1-hour event\n"
            "  <code>Friday 14:00-15:30</code>  → explicit end\n"
            "  <code>tomorrow 14:00 for 2 hours</code>\n"
            "  <code>tomorrow 14:00 for 90 min</code>", state)

    if step == "datetime":
        try:
            start_dt, end_dt = tb._parse_event_times(text)
        except Exception:  # noqa: BLE001
            start_dt = None
        if not start_dt:
            return ("⚠️ Couldn't parse that.\n"
                    "Try: <code>tomorrow 14:00</code>, <code>Friday 14:00-15:00</code>, "
                    "or <code>tomorrow 14:00 for 2 hours</code>.", state)
        data["start"] = start_dt.strftime("%Y-%m-%dT%H:%M:%S")
        data["end"] = end_dt.strftime("%Y-%m-%dT%H:%M:%S")
        state["step"] = "reminder"
        return (
            "🔔 <b>Step 3/5 — Reminder</b>\n\n"
            "How long before the event?\n"
            "Examples: <code>30 min</code>  <code>1 hour</code>  <code>1 day</code>  "
            "<code>10</code> (minutes)\n"
            "Reply <code>-</code> to use your calendar's default.", state)

    if step == "reminder":
        if _is_skip(text):
            data["reminder_minutes"] = None
        else:
            minutes, valid = tb._parse_reminder_minutes(text)
            if not valid:
                return ("⚠️ Couldn't understand that.\n"
                        "Try: <code>30 min</code>, <code>1 hour</code>, "
                        "<code>1 day</code>, or <code>-</code> to skip.", state)
            data["reminder_minutes"] = minutes
        state["step"] = "color"
        return (f"🎨 <b>Step 4/5 — Colour</b>\n\n"
                f"Choose a colour, or send <code>-</code> to skip.\n"
                f"{color_options_text()}", state)

    if step == "color":
        data["color_name"] = None if _is_skip(text) else text.strip()
        state["step"] = "confirm"
        start_dt = datetime.fromisoformat(data["start"])
        end_dt = datetime.fromisoformat(data["end"])
        rm = data.get("reminder_minutes")
        return (
            f"📅 <b>Step 5/5 — Confirm</b>\n\n"
            f"<b>Event to create:</b>\n"
            f"  Name:      {data['name']}\n"
            f"  Starts:    {_fmt_dt(start_dt)}\n"
            f"  Ends:      {end_dt.strftime('%H:%M')}\n"
            f"  Reminder:  {str(rm) + ' min before' if rm else '— (calendar default)'}\n"
            f"  Colour:    {data.get('color_name') or '— (default)'}\n\n"
            f"Create this event? Reply <b>yes</b> or <b>no</b>.", state)

    low = text.strip().lower()
    if low in tb._NO_WORDS:
        return CANCELLED, None
    if low not in tb._YES_WORDS:
        return "Please reply <b>yes</b> or <b>no</b>.", state

    # end is a REQUIRED positional on create_calendar_event, so it is always
    # passed; _parse_event_times guarantees one (defaulting to +1 hour).
    try:
        res = create_calendar_event(
            data["name"],
            data["start"],
            data["end"],
            reminder_minutes=data.get("reminder_minutes"),
            color=data.get("color_name"),
        )
    except Exception as exc:  # noqa: BLE001
        return f"⚠️ Failed to create event: {type(exc).__name__}: {exc}", None

    if isinstance(res, dict) and res.get("error"):
        return f"⚠️ {res['error']}", None
    start_dt = datetime.fromisoformat(data["start"])
    return f"✅ Event created\n   {data['name']}\n   {_fmt_dt(start_dt)}", None


# ── dispatch ──────────────────────────────────────────────────────────────────

def advance(state: dict, text: str) -> tuple[str, dict | None]:
    """
    Feed one user message into an in-progress wizard.

    Returns (reply, new_state). new_state is None when the flow has ended -
    completed, cancelled, or failed - and the caller should clear it.
    """
    text = (text or "").strip()

    # /cancel works at every step, and so does any bare command: starting to
    # type a different command should not be swallowed as a task name.
    if _is_cancel(text) or text.lower() in ("/cancel", "cancel"):
        return CANCELLED, None
    if text.startswith("/") and state["step"] != "name":
        return ("❌ Cancelled the guided flow because you sent a command.\n"
                f"Send /{state['kind']} to start again."), None

    if state["kind"] == "task":
        return _task_step(state, text)
    return _event_step(state, text)
