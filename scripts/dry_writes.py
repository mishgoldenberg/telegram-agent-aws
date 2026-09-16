r"""
Run agent prompts with every WRITE replaced by a recorder.

Testing the routing of "add gym to my calendar tomorrow at 8pm" should not put
a gym session on the real calendar - and during one debugging pass it put four
there. The reads stay live, because the whole point is to exercise the real
Google APIs; only the writes are intercepted, and each one is printed with the
arguments it would have been given, which is exactly what a routing test wants
to see anyway.

    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\dry_writes.py "put dentist on friday 14:00"
"""

import contextlib
import io
import os
import pathlib
import re
import sys
import time
from datetime import date

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
if str(ASSISTANT) not in sys.path:
    sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import agent  # noqa: E402

WRITES = [
    "create_calendar_event", "create_task", "update_task", "complete_task",
    "set_reminder", "save_memory", "log_calories", "log_habit",
    "delete_calendar_event", "set_event_reminder",
]

recorded: list[tuple[str, dict]] = []


def _fake_result(name: str, kwargs: dict) -> dict:
    """
    Mimic each tool's REAL success shape.

    A generic dict is not good enough. The first version returned the same
    {id, title, summary, start, end} for everything, and the model - which sees
    these results - read the wrong-looking response from log_calories and
    save_memory as a failure, then narrated "there was an error or unexpected
    response from the tools". Four cases failed in the stubbed run that had
    passed against the live APIs: the harness was manufacturing bugs.
    """
    title = kwargs.get("title") or kwargs.get("task_title") or "(dry run)"
    if name == "create_calendar_event":
        return {"id": "dry-run", "summary": title,
                "start": kwargs.get("start"), "end": kwargs.get("end"),
                "reminder_minutes": kwargs.get("reminder_minutes")}
    if name in ("create_task", "update_task"):
        return {"id": "dry-run", "title": title,
                "due_date": kwargs.get("due_date"), "list": kwargs.get("list_name")}
    if name == "complete_task":
        return {"completed": True, "id": "dry-run", "title": title}
    if name == "delete_calendar_event":
        return {"deleted": True, "id": "dry-run", "title": title}
    if name == "save_memory":
        return {"id": 1, "fact": kwargs.get("fact", "(dry run)"),
                "category": kwargs.get("category", "general"),
                "created": date.today().isoformat()}
    if name == "log_calories":
        return {"logged": True, "id": 1, "date": kwargs.get("date_str"),
                "item": kwargs.get("item"), "calories": kwargs.get("calories")}
    if name == "log_habit":
        return {"logged": True, "id": 1, "date": kwargs.get("date_str"),
                "habit": kwargs.get("habit")}
    if name in ("set_reminder", "reminders.add"):
        return {"status": "reminder_set", "id": "dry-run",
                "message": kwargs.get("message"), "fire_at": kwargs.get("fire_at")}
    return {"ok": True, "id": "dry-run"}


def _stub(name: str):
    def fake(**kwargs):
        recorded.append((name, kwargs))
        return _fake_result(name, kwargs)
    return fake


def install() -> None:
    """Point the dispatch table at recorders. Reads are untouched."""
    for name in WRITES:
        if name in agent.TOOL_FUNCTIONS:
            agent.TOOL_FUNCTIONS[name] = _stub(name)
    # The rescues call module-level names directly, not the dispatch table.
    for name in ("create_task", "set_reminder"):
        if hasattr(agent, name):
            setattr(agent, name, _stub(name))

    # run_agent REBUILDS set_reminder on every call, to close over chat_id, and
    # overwrites the dispatch entry - so stubbing the table is not enough and
    # test runs were queueing real reminders that would later message Telegram.
    # Cut it off at the store instead.
    _record = _stub("reminders.add")

    def fake_add(chat_id, message, fire_at):
        _record(chat_id=chat_id, message=message, fire_at=fire_at)
        return "dry-run"

    agent._reminders.add = fake_add


CALL_RE = re.compile(r"\[tool round \d+\] CALL : ([a-z_]+)\(")
GUARD_RE = re.compile(r"\[([A-Z-]+(?:GUARD|RESCUE)|BACKSTOP|BARE-DATE|CONFIRM[^\]]*)\]")


def run(prompt: str) -> None:
    recorded.clear()
    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        reply = agent.run_agent(prompt, history=[], chat_id=700196974)
    log = buf.getvalue()
    print(f"\n### {prompt}   ({time.time() - t0:.1f}s)")
    print(f"    tools  : {CALL_RE.findall(log)}")
    print(f"    guards : {sorted(set(GUARD_RE.findall(log)))}")
    for name, kwargs in recorded:
        print(f"    WOULD WRITE {name}({kwargs})")
    print("    reply  : " + (reply or "").replace("\n", "\n             ")[:400])


if __name__ == "__main__":
    install()
    for p in sys.argv[1:]:
        run(p)
