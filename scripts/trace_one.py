r"""
Trace a single prompt through the agent, printing only control-flow lines -
tool calls, guards, backstops - never tool results.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\trace_one.py "your prompt"
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

KEEP = re.compile(
    r"CALL :|GUARD|BACKSTOP|SHORT-CIRCUIT|DIRECT|CONFIRM|round 0|RETRY|"
    r"CLARIFICATION|Unknown tool|Bad arguments|error"
)

prompts = sys.argv[1:] or ["What's are the tasks I have right now?"]

for p in prompts:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            reply = agent.run_agent(p, history=[], chat_id=700196974)
        except Exception as exc:  # noqa: BLE001
            reply = f"<{type(exc).__name__}: {exc}>"
    out = buf.getvalue()
    print(f"\n  prompt: {p}")
    for line in out.splitlines():
        if KEEP.search(line):
            print("   ", line.strip()[:150])
    print(f"    reply: {reply[:200]!r}")
