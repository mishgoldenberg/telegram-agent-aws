r"""
Tool-routing check: does the model pick the right tool for each intent?

Prints ONLY the tool names chosen, never the tool results — so a routing test
never dumps calendar entries or email content into a terminal or a log.

Usage:
    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\tool_routing_check.py
"""

import contextlib
import io
import re
import sys
import time
import pathlib

ASSISTANT = pathlib.Path(
    sys.argv[1] if len(sys.argv) > 1
    else r"C:\Users\User\Documents\llm-agent-test\assistant"
).resolve()

sys.path.insert(0, str(ASSISTANT))
import os

os.chdir(ASSISTANT)

import agent  # noqa: E402

# Compare models without editing agent.py:  $env:MODEL_OVERRIDE = "qwen2.5:7b"
if os.environ.get("MODEL_OVERRIDE"):
    agent.MODEL = os.environ["MODEL_OVERRIDE"]

# (prompt, tool name that should be called)
#
# NOTE: there is deliberately no weather case. weather.py is wired to the
# /weather bot command, not exposed as an agent tool, so "what's the weather"
# correctly falls through to web_search. An earlier version of this file
# asserted get_weather and produced a false failure.
CASES = [
    ("What is in my schedule for the next week?", "list_calendar_events"),
    ("What's on my calendar today?", "list_calendar_events"),
    ("Am I free on Friday?", "list_calendar_events"),
    ("What do I have planned this weekend?", "list_calendar_events"),
    ("Show me my tasks", "list_tasks"),
    ("Summarise my unread emails", "summarize_unread"),
    ("Any new mail?", "summarize_unread"),
]

CALL_RE = re.compile(r"\[tool round \d+\] CALL : ([a-z_]+)\(")


def tools_called(prompt: str) -> tuple[list[str], float]:
    """Run the agent, capturing stdout so tool RESULTS never reach the console."""
    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        try:
            agent.run_agent(prompt, history=[], chat_id=None)
        except Exception as exc:  # noqa: BLE001
            return [f"<error: {type(exc).__name__}>"], time.time() - t0
    return CALL_RE.findall(buf.getvalue()), time.time() - t0


def main() -> None:
    print(f"model: {agent.MODEL}\n")
    passed = 0
    for prompt, expected in CASES:
        called, secs = tools_called(prompt)
        first = called[0] if called else "<no tool call>"
        ok = expected in called
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {prompt[:44]:46} "
              f"want={expected:22} got={first:22} {secs:5.1f}s")
    print(f"\n  {passed}/{len(CASES)} routed correctly")


if __name__ == "__main__":
    main()
