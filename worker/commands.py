r"""
Slash-command handling for the AWS-mode worker.

WHY THIS FILE EXISTS
--------------------
In polling mode, telegram_bot.py registered ~17 CommandHandlers with
python-telegram-bot. In webhook mode that file no longer runs, so every slash
command reached the model as literal text: "/task" was answered with a calendar
listing, because the agent did the best it could with a string it did not
understand.

Most of those commands are one-shot calls into modules that still exist. Those
are routed here. Two of them - /task and /event - are multi-step
ConversationHandler wizards whose state lived in process memory, and they are
NOT reimplemented yet. They report that plainly rather than falling through to
the agent and producing something that looks like an answer.

Saying "not available yet" is the honest behaviour. Silently doing something
else is how "/task" became a calendar listing.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ASSISTANT = Path(r"C:\Users\User\Documents\llm-agent-test\assistant")
if str(ASSISTANT) not in sys.path:
    sys.path.insert(0, str(ASSISTANT))

# Commands that need multi-turn state. Not yet migrated - see module docstring.
WIZARDS = {"task", "event", "template", "done", "cancel"}

HELP = """*Assistant — AWS mode*

*Working now*
/weather `[city]` — current conditions and forecast
/briefing — weather plus today's agenda
/digest — evening summary
/inbox `[n]` — summarise unread email (default 10)
/reminders — pending reminders
/log `[date]` — calorie and habit log
/memory — stored facts
/study — study dashboard
/clear — clear conversation history
/help — this message

*Not available in AWS mode yet*
/task, /event, /template, /done — these are multi-step wizards whose
state has not been migrated to DynamoDB yet.

You can still do all of it in plain language — "add a task to call the
dentist tomorrow", "put gym at 8pm on Thursday" — which goes through the
agent and works today."""

NOT_MIGRATED = (
    "⚠️ /{cmd} is a multi-step wizard and is not available in AWS mode yet.\n\n"
    "Its state used to live in the bot's memory, which no longer exists now that "
    "the ingest path is stateless.\n\n"
    "Ask in plain language instead — for example:\n"
    "  • \"add a task to call the dentist tomorrow\"\n"
    "  • \"put gym in my calendar at 8pm Thursday\""
)


def _fmt_inbox(msgs: list[dict]) -> str:
    if not msgs:
        return "📧 No unread email."
    out = [f"📧 {len(msgs)} unread:\n"]
    for m in msgs:
        flag = "🔴 " if m.get("is_urgent") else ""
        out.append(f"{flag}*{m.get('sender', '?')}*\n{m.get('subject', '(no subject)')}\n")
    return "\n".join(out)


def _fmt_reminders(rows: list[dict]) -> str:
    if not rows:
        return "⏰ No pending reminders."
    out = ["⏰ Pending reminders:\n"]
    for r in rows:
        out.append(f"  • {r.get('message')} — {str(r.get('fire_at'))[:16].replace('T', ' ')}")
    return "\n".join(out)


def _fmt_memory(rows: list[dict]) -> str:
    if not rows:
        return "🧠 Nothing stored yet."
    out = ["🧠 Stored facts:\n"]
    for r in rows:
        out.append(f"  • {r.get('fact')}")
    return "\n".join(out)


def _fmt_log(d: dict) -> str:
    cals = d.get("calories") or []
    habits = d.get("habits") or []
    if not cals and not habits:
        return "📋 Nothing logged."
    out = []
    if cals:
        out.append("🥗 Food:")
        out += [f"  • {c.get('item')}"
                + (f" — {c['calories']} kcal" if c.get("calories") else "")
                for c in cals]
    if habits:
        out.append("\n✅ Habits:")
        out += [f"  • {h.get('habit')}" for h in habits]
    return "\n".join(out)


def handle(text: str, chat_id: int, clear_history) -> str | None:
    """
    Handle a slash command.

    Returns the reply text, or None if `text` is not a command — in which case
    the caller passes it to the agent as normal.
    """
    if not text.startswith("/"):
        return None

    parts = text[1:].split()
    if not parts:
        return None
    # "/weather@MyBot" -> "weather"
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    if cmd in ("help", "start", "menu"):
        return HELP

    if cmd in WIZARDS:
        return NOT_MIGRATED.format(cmd=cmd)

    if cmd == "clear":
        clear_history(chat_id)
        return "🧹 Conversation history cleared."

    try:
        if cmd == "weather":
            from weather import get_weather
            return get_weather(include_tomorrow=True,
                               city=" ".join(args) if args else None)

        if cmd == "briefing":
            from agent import build_briefing
            return build_briefing("today")

        if cmd == "digest":
            from agent import build_digest
            return build_digest()

        if cmd == "study":
            from agent import build_study_dashboard
            return build_study_dashboard()

        if cmd == "inbox":
            from gmail_tools import summarize_unread
            n = int(args[0]) if args and args[0].isdigit() else 10
            return _fmt_inbox(summarize_unread(max_messages=min(n, 25)))

        if cmd == "reminders":
            import reminders as _r
            return _fmt_reminders(_r.get_pending_for_chat(chat_id))

        if cmd == "memory":
            import memory as _m
            return _fmt_memory(_m.get_all())

        if cmd == "log":
            import log_store as _l
            when = args[0] if args else date.today().isoformat()
            return _fmt_log(_l.get_log(when))

    except Exception as exc:  # noqa: BLE001
        # Report the real failure rather than a generic apology - a command
        # that silently half-works is worse than one that says what broke.
        return f"⚠️ /{cmd} failed: {type(exc).__name__}: {exc}"

    return (f"❓ Unknown command /{cmd}.\n\nSend /help for what is available.")
