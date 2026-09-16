r"""
Run the phrasing corpus through the real agent and report what a user would see.

Two checks per case, and the second matters more:

  ROUTING   did it call the expected tool (or correctly call none)?
  USABLE    would a human have got a real answer, or an apology?

A case can route correctly and still fail: calling get_weather and then
replying "It seems there was an error with the weather tool" is a failure, and
that is precisely the class of bug this is hunting.

Tool RESULTS are never printed - only tool names, guard lines and a short reply
prefix - so a full run never dumps calendar entries or email into a log.

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\run_corpus.py
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\run_corpus.py --only weather
"""

import contextlib
import io
import json
import os
import pathlib
import re
import sys
import time

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
SCRIPTS = pathlib.Path(__file__).resolve().parent
WORKER = SCRIPTS.parent / "worker"
for p in (str(ASSISTANT), str(SCRIPTS), str(WORKER)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.chdir(ASSISTANT)

import agent  # noqa: E402
import corpus  # noqa: E402
import dry_writes  # noqa: E402

CALL_RE = re.compile(r"\[tool round \d+\] CALL : ([a-z_]+)\(")
GUARD_RE = re.compile(
    r"\[([A-Z-]+GUARD|[A-Z-]*RESCUE|BACKSTOP|BARE-DATE|META|DIRECT|CONFIRM"
    r"|SHORT-CIRCUIT|DEDUPE-GUARD)[^\]]*\]")

# Replies that mean the user got nothing useful.
BAD_REPLY = re.compile(
    r"couldn't fetch your data|couldn't generate a response|couldn't process that"
    r"|не удалось получить|error with the .* tool|bad arguments for"
    r"|unexpected keyword argument|there was an error|\{'error'|\"error\":"
    r"|please try again|try rephrasing",
    re.IGNORECASE,
)

OUT = SCRIPTS.parent / "corpus_results.json"


def run_one(prompt: str) -> dict:
    buf = io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(buf):
        try:
            reply = agent.run_agent(prompt, history=[], chat_id=700196974)
        except Exception as exc:  # noqa: BLE001
            reply = f"<EXCEPTION {type(exc).__name__}: {exc}>"
    log = buf.getvalue()
    return {
        "prompt": prompt,
        "tools": CALL_RE.findall(log),
        "rescued": [tool for rx, tool in RESCUE_CALLS if rx.search(log)],
        "guards": sorted(set(GUARD_RE.findall(log))),
        "reply_head": (reply or "")[:100],
        "reply_len": len(reply or ""),
        "secs": round(time.time() - t0, 1),
        "exception": reply.startswith("<EXCEPTION"),
    }


# A rescue answers the question in Python when the model produced no tool call.
# The user gets the right answer from live API data, so counting that as a
# routing failure measures the wrong thing - it marks the recovery as the bug.
#
# Each pattern matches the rescue's OWN log line, so the credit is for the call
# it actually made: LIST-RESCUE covers three different tools and must not be
# allowed to satisfy an expectation it did not meet.
RESCUE_CALLS = [
    (re.compile(r"\[LIST-RESCUE\] inbox query"),        "summarize_unread"),
    (re.compile(r"\[LIST-RESCUE\].*listing tasks"),     "list_tasks"),
    (re.compile(r"\[LIST-RESCUE\].*listing '"),         "list_calendar_events"),
    (re.compile(r"\[MAIL-RESCUE\]"),                    "summarize_unread"),
    (re.compile(r"\[BARE-DATE\].*listing calendar"),    "list_calendar_events"),
    (re.compile(r"\[WRITE-RESCUE\].*creating task"),    "create_task"),
    (re.compile(r"\[WRITE-RESCUE\].*creating event"),   "create_calendar_event"),
    (re.compile(r"\[KNOWLEDGE-RESCUE\]"),               "web_search"),
    (re.compile(r"\[EVENT-GUARD\].*create_calendar_event"), "create_calendar_event"),
]


def judge(expected, got: dict) -> tuple[bool, str]:
    tools, reply = got["tools"] + got["rescued"], got["reply_head"]

    if got["exception"]:
        return False, "raised"
    if not reply.strip():
        return False, "empty reply"
    if BAD_REPLY.search(reply):
        return False, "error reply"

    if expected is corpus.ANY:
        return True, ""
    if expected is None:
        return (not tools, "called a tool when none was wanted" if tools else "")
    wanted = {expected} if isinstance(expected, str) else set(expected)
    if not tools:
        return False, f"no tool call; wanted {'/'.join(sorted(wanted))}"
    if wanted & set(tools):
        return True, ""
    return False, f"wanted {'/'.join(sorted(wanted))}, got {tools[0]}"


def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].lower()

    # The corpus contains 15 write cases, and they were writing to the real
    # Google account - one debugging pass left four identical gym sessions on
    # a real calendar. Reads stay live; writes are recorded instead of sent.
    if "--live-writes" not in sys.argv:
        dry_writes.install()
        print("  writes are STUBBED (pass --live-writes to write for real)\n")

    # Slash commands first: instant, no model.
    print("=== slash commands (no model) ===")
    import commands as cmds
    cmd_fail = 0
    for text, expect in corpus.COMMAND_CASES:
        try:
            r = cmds.handle(text, 700196974, lambda c: None) or ""
        except Exception as exc:  # noqa: BLE001
            r = f"<EXCEPTION {type(exc).__name__}: {exc}>"
        ok = expect.lower() in r.lower() and not r.startswith("<EXCEPTION")
        cmd_fail += not ok
        if not ok:
            print(f"  [FAIL] {text:12} -> {r[:72]!r}")
    print(f"  {len(corpus.COMMAND_CASES) - cmd_fail}/{len(corpus.COMMAND_CASES)} ok\n")

    cases = corpus.CASES
    if only:
        cases = [c for c in cases if only in c[0].lower()]

    print(f"=== {len(cases)} prompts through {agent.MODEL} ===", flush=True)
    results, failures = [], []
    t0 = time.time()

    for i, (prompt, expected) in enumerate(cases, 1):
        got = run_one(prompt)
        ok, why = judge(expected, got)
        got["ok"], got["why"] = ok, why
        got["expected"] = list(expected) if isinstance(expected, set) else expected
        results.append(got)
        if not ok:
            failures.append(got)
            print(f"  [{i:>2}/{len(cases)}] FAIL  {prompt[:46]:48} {why}", flush=True)
            print(f"            tools={got['tools']} guards={got['guards']}", flush=True)
            print(f"            reply={got['reply_head'][:80]!r}", flush=True)
        else:
            print(f"  [{i:>2}/{len(cases)}] ok    {prompt[:46]:48} "
                  f"{(got['tools'] or ['-'])[0]:22} {got['secs']:5.1f}s", flush=True)

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    mins = (time.time() - t0) / 60
    print(f"\n  {len(cases) - len(failures)}/{len(cases)} passed in {mins:.1f} min")
    print(f"  full results: {OUT}")
    if failures:
        print("\n  failures:")
        for f in failures:
            print(f"    {f['prompt'][:56]:58} {f['why']}")


if __name__ == "__main__":
    main()
