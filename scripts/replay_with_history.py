r"""
Replay a prompt using the REAL conversation history stored in DynamoDB.

trace_one.py runs with history=[], which is not what the worker does. If a
prompt works in isolation but fails in Telegram, the difference is the history
being fed alongside it - and that is worth seeing rather than guessing.

Prints only control-flow lines and a redacted history summary, never the full
stored conversation.

    cd C:\Users\User\Documents\telegram-agent-aws\worker
    ..\..\llm-agent-test\assistant\venv\Scripts\python.exe ..\scripts\replay_with_history.py "prompt"
"""

import contextlib
import io
import os
import pathlib
import re
import sys

WORKER = pathlib.Path(r"C:\Users\User\Documents\telegram-agent-aws\worker").resolve()
sys.path.insert(0, str(WORKER))
os.chdir(WORKER)

import worker as w  # noqa: E402
import agent  # noqa: E402

CHAT = 700196974
KEEP = re.compile(r"CALL :|GUARD|BACKSTOP|SHORT-CIRCUIT|DIRECT|CONFIRM|round 0|RETRY")

prompt = sys.argv[1] if len(sys.argv) > 1 else "What's are the tasks I have right now?"

history = w.load_history(CHAT)
print(f"  stored history: {len(history)} messages")
for m in history[-8:]:
    role = m.get("role", "?")
    body = str(m.get("content", "")).replace("\n", " ")[:64]
    print(f"    {role:9} {body}")

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        reply = agent.run_agent(prompt, history=list(history), chat_id=CHAT)
    except Exception as exc:  # noqa: BLE001
        reply = f"<{type(exc).__name__}: {exc}>"
out = buf.getvalue()

print(f"\n  prompt: {prompt}")
for line in out.splitlines():
    if KEEP.search(line):
        print("   ", line.strip()[:150])
print(f"    reply: {reply[:180]!r}")
