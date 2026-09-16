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


def _stub(name: str):
    def fake(**kwargs):
        recorded.append((name, kwargs))
        # Shaped like the real responses so the confirmation formatters,
        # which are part of what is being tested, still have something to read.
        return {
            "id": "dry-run",
            "title": kwargs.get("title", "(dry run)"),
            "summary": kwargs.get("title", "(dry run)"),
            "start": kwargs.get("start") or kwargs.get("due_date"),
            "end": kwargs.get("end"),
            "due_date": kwargs.get("due_date"),
        }
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
