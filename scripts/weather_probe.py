r"""
Probe the weather tool directly: which city spellings resolve, and does the
tool RETURN its errors or RAISE them?

That distinction matters. agent.py short-circuits get_weather's return value
straight to the user, so a returned error string reaches them verbatim. A
raised exception is caught, turned into {"error": ...}, and handed to the model
to narrate - which is how "It seems there was an error with the weather tool"
happened instead of a clean message.
"""

import os
import pathlib
import sys

ASSISTANT = pathlib.Path(r"C:\Users\User\Documents\llm-agent-test\assistant").resolve()
sys.path.insert(0, str(ASSISTANT))
os.chdir(ASSISTANT)

import weather  # noqa: E402

SPELLINGS = [
    "Tirat Hacarmel",
    "Tirat HaCarmel",
    "Tirat Carmel",
    "Tirat Karmel",
    "Tirat Yehuda",
    "Haifa",
    "Qiryat Yam",
    "Kiryat Yam",
    "Tel Aviv",
    "טירת כרמל",
]

print("city lookups\n")
for name in SPELLINGS:
    try:
        out = weather.get_weather(include_tomorrow=False, city=name)
        kind = "RETURNED"
        first = out.splitlines()[0] if out else "(empty)"
    except Exception as exc:  # noqa: BLE001
        kind = f"RAISED {type(exc).__name__}"
        first = str(exc)[:60]
    print(f"  {name:18} {kind:22} {first[:56]}")

print("\nargument shapes the model might send\n")
CALLS = [
    {"city": "Haifa"},
    {"city": "Haifa", "include_tomorrow": True},
    {},
    {"city": None},
    {"city": ""},
    {"include_tomorrow": True},
]
for kw in CALLS:
    try:
        out = weather.get_weather(**kw)
        kind, first = "RETURNED", (out.splitlines()[0] if out else "(empty)")
    except Exception as exc:  # noqa: BLE001
        kind, first = f"RAISED {type(exc).__name__}", str(exc)[:60]
    print(f"  {str(kw):44} {kind:22} {first[:44]}")
