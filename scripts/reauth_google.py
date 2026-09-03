r"""
Re-run the Google OAuth consent flow and write a fresh token.json.

Needed whenever the refresh token dies. While the OAuth app's publishing
status is "Testing", Google expires refresh tokens after 7 days, so this is
a recurring chore rather than a one-off — see the README for the permanent fix.

Run with the assistant's venv, from the assistant directory:

    cd C:\Users\User\Documents\llm-agent-test\assistant
    .\venv\Scripts\python.exe ..\..\telegram-agent-aws\scripts\reauth_google.py

Opens a browser for consent. The app is unverified, so Google shows a
"Google hasn't verified this app" screen: choose Advanced, then
"Go to personal-assistant (unsafe)". That warning is expected for a personal
app that has not been through Google's verification process.
"""

import sys
import pathlib

ASSISTANT = pathlib.Path(
    sys.argv[1] if len(sys.argv) > 1
    else r"C:\Users\User\Documents\llm-agent-test\assistant"
).resolve()

sys.path.insert(0, str(ASSISTANT))
import os

os.chdir(ASSISTANT)

from auth import get_credentials  # noqa: E402

print("opening browser for consent…", flush=True)
creds = get_credentials()
print(f"OK valid={creds.valid} expired={creds.expired} has_refresh={bool(creds.refresh_token)}")
print(f"token written to {ASSISTANT / 'token.json'}")
