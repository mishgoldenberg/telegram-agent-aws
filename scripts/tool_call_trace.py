r"""
Trace the ARGUMENTS the model passes to each tool, and any error the tool
raises. Prints call signatures and errors only - never tool results, so
calendar entries and email content never reach the console or a log.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\tool_call_trace.py "next week query"
"""

import contextlib
import io
import os
import pathlib
import re
import sys

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import agent  # noqa: E402
import tools  # noqa: E402

if os.environ.get("MODEL_OVERRIDE"):
    agent.MODEL = os.environ["MODEL_OVERRIDE"]

PROMPTS = sys.argv[1:] or [
    "What's in the schedule for the next week?",
    "06.09-12.09",
]

CALL_RE = re.compile(r"\[tool round \d+\] CALL : ([a-z_]+)\((.*?)\)\s*$", re.M)
ERR_RE = re.compile(r"(?i)^.*(error|exception|traceback|failed|invalid).*$", re.M)


def main() -> None:
    print(f"model: {agent.MODEL}\n")

    # Wrap the real function so we see exactly what it receives and raises.
    real = tools.list_calendar_events

    def traced(date_str=None, end_date=None, *a, **kw):
        print(f"    -> list_calendar_events(date_str={date_str!r}, end_date={end_date!r})")
        try:
            out = real(date_str, end_date, *a, **kw)
            print(f"    <- returned {len(out) if hasattr(out,'__len__') else '?'} item(s)")
            return out
        except Exception as exc:  # noqa: BLE001
            print(f"    <- RAISED {type(exc).__name__}: {exc}")
            raise

    tools.list_calendar_events = traced
    agent.TOOL_FUNCTIONS["list_calendar_events"] = traced

    for p in PROMPTS:
        print(f'  prompt: "{p}"')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                reply = agent.run_agent(p, history=[], chat_id=None)
            except Exception as exc:  # noqa: BLE001
                reply = f"<{type(exc).__name__}: {exc}>"
        out = buf.getvalue()
        # replay only the traced lines and the model's call signatures
        for line in out.splitlines():
            if "-> list_calendar_events(" in line or "<- " in line:
                print(line)
        for m in CALL_RE.finditer(out):
            print(f"    model called: {m.group(1)}({m.group(2)[:120]})")
        for line in out.splitlines():
            if re.search(r"BACKSTOP|no tool calls|refusing", line):
                print(f"    {line.strip()[:130]}")
        print(f"    reply[:110]: {reply[:110]!r}\n")


if __name__ == "__main__":
    main()
