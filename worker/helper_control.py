r"""
Helper Control — a small tkinter panel for the AWS-mode assistant.

Since the ingest path moved to AWS, running the assistant needs TWO local
processes, and neither starts on its own:

    Ollama          serves the language model on :11434
    worker.py       long-polls SQS, transcribes, runs the agent, replies

AWS is always up; these two are not. This panel shows both and starts/stops
them.

DETACHED, DELIBERATELY
----------------------
The worker is launched with DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP so it
survives this window closing. Without that it dies with its parent, which is
exactly how both processes ended up down after being "started" earlier.

Launched via helper_control.vbs -> pythonw.exe, so no console window appears.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
ASSISTANT = Path(r"C:\Users\User\Documents\llm-agent-test\assistant")
VENV_PY = ASSISTANT / "venv" / "Scripts" / "python.exe"
WORKER = HERE / "worker.py"
PIDFILE = HERE / ".worker.pid"
LOG = HERE / "worker.log"
ERRLOG = HERE / "worker.err"

OLLAMA_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
    Path(r"C:\Program Files\Ollama\ollama.exe"),
]

# Windows process-creation flags for a genuinely detached child.
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

BG = "#12161a"
CARD = "#1b2229"
FG = "#e6eaed"
DIM = "#8b979f"
OK = "#3fb950"
BAD = "#f85149"
WARN = "#d29922"
ACCENT = "#2f81f7"


# ── state checks ──────────────────────────────────────────────────────────────

def ollama_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1.5):
            return True
    except OSError:
        return False


def ollama_model_loaded() -> str | None:
    """Return the model name Ollama currently has resident, if any."""
    try:
        with urlopen("http://127.0.0.1:11434/api/ps", timeout=2) as r:
            models = json.loads(r.read()).get("models") or []
            return models[0].get("name") if models else None
    except Exception:  # noqa: BLE001
        return None


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid exists. tasklist avoids a psutil dep."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=6,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        return str(pid) in out
    except Exception:  # noqa: BLE001
        return False


def worker_pid() -> int | None:
    if not PIDFILE.exists():
        return None
    try:
        pid = int(PIDFILE.read_text().strip())
    except (ValueError, OSError):
        return None
    if _pid_alive(pid):
        return pid
    PIDFILE.unlink(missing_ok=True)  # stale
    return None


# ── actions ───────────────────────────────────────────────────────────────────

def start_ollama() -> str:
    if ollama_up():
        return "already running"
    exe = next((p for p in OLLAMA_CANDIDATES if p.exists()), None)
    if exe is None:
        return "ollama.exe not found"
    subprocess.Popen([str(exe)], creationflags=DETACHED, close_fds=True)
    for _ in range(20):
        time.sleep(1)
        if ollama_up():
            return "started"
    return "did not come up in 20s"


def start_worker() -> str:
    if worker_pid():
        return "already running"
    if not VENV_PY.exists():
        return "venv python not found"
    out = open(LOG, "ab", buffering=0)
    err = open(ERRLOG, "ab", buffering=0)
    proc = subprocess.Popen(
        [str(VENV_PY), str(WORKER)],
        cwd=str(HERE),
        stdout=out, stderr=err, stdin=subprocess.DEVNULL,
        creationflags=DETACHED,
        close_fds=True,
    )
    PIDFILE.write_text(str(proc.pid))
    time.sleep(2.5)
    return "started" if worker_pid() else "exited immediately - check the log"


def stop_worker() -> str:
    pid = worker_pid()
    if not pid:
        return "not running"
    try:
        # CTRL_BREAK lets worker.py's signal handler finish the in-flight job.
        os.kill(pid, signal.CTRL_BREAK_EVENT)
        for _ in range(8):
            time.sleep(0.5)
            if not _pid_alive(pid):
                break
    except Exception:  # noqa: BLE001
        pass
    if _pid_alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    PIDFILE.unlink(missing_ok=True)
    return "stopped"


# ── UI ────────────────────────────────────────────────────────────────────────

class Panel:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Assistant Helper")
        root.configure(bg=BG)
        root.resizable(False, False)

        self.f_title = tkfont.Font(family="Segoe UI Semibold", size=13)
        self.f_body = tkfont.Font(family="Segoe UI", size=10)
        self.f_small = tkfont.Font(family="Segoe UI", size=9)
        self.f_mono = tkfont.Font(family="Consolas", size=9)

        tk.Label(root, text="Assistant Helper", font=self.f_title,
                 bg=BG, fg=FG).pack(anchor="w", padx=18, pady=(16, 0))
        self.sub = tk.Label(root, text="", font=self.f_small, bg=BG, fg=DIM)
        self.sub.pack(anchor="w", padx=18, pady=(2, 12))

        self.rows: dict[str, tuple[tk.Canvas, tk.Label]] = {}
        for name, hint in (
            ("Ollama", "language model, port 11434"),
            ("Worker", "polls AWS, runs the agent"),
        ):
            self.rows[name] = self._row(name, hint)

        btns = tk.Frame(root, bg=BG)
        btns.pack(fill="x", padx=18, pady=(14, 4))
        self.b_start = self._btn(btns, "Start", self.on_start, ACCENT)
        self.b_stop = self._btn(btns, "Stop", self.on_stop, "#30363d")
        self.b_restart = self._btn(btns, "Restart", self.on_restart, "#30363d")
        self.b_log = self._btn(btns, "Log", self.on_log, "#30363d")

        self.status = tk.Label(root, text="", font=self.f_mono, bg=BG, fg=DIM,
                               anchor="w", justify="left")
        self.status.pack(fill="x", padx=18, pady=(6, 16))

        self.refresh()

    def _row(self, name: str, hint: str):
        card = tk.Frame(self.root, bg=CARD)
        card.pack(fill="x", padx=18, pady=3, ipady=9)
        dot = tk.Canvas(card, width=12, height=12, bg=CARD, highlightthickness=0)
        dot.create_oval(2, 2, 11, 11, fill=BAD, outline="", tags="d")
        dot.pack(side="left", padx=(12, 10))
        tk.Label(card, text=name, font=self.f_body, bg=CARD, fg=FG,
                 width=8, anchor="w").pack(side="left")
        state = tk.Label(card, text="checking…", font=self.f_small, bg=CARD, fg=DIM)
        state.pack(side="left")
        tk.Label(card, text=hint, font=self.f_small, bg=CARD,
                 fg="#5c686f").pack(side="right", padx=12)
        return dot, state

    def _btn(self, parent, text, cmd, colour):
        b = tk.Button(parent, text=text, command=cmd, font=self.f_body,
                      bg=colour, fg="#ffffff", activebackground=colour,
                      activeforeground="#ffffff", relief="flat", bd=0,
                      padx=16, pady=6, cursor="hand2")
        b.pack(side="left", padx=(0, 8))
        return b

    def _set(self, name: str, up: bool, text: str, colour: str | None = None) -> None:
        dot, state = self.rows[name]
        dot.itemconfig("d", fill=colour or (OK if up else BAD))
        state.config(text=text, fg=FG if up else DIM)

    def refresh(self) -> None:
        o_up = ollama_up()
        model = ollama_model_loaded() if o_up else None
        self._set("Ollama", o_up,
                  f"running — {model}" if model else ("running — idle" if o_up else "not running"))

        pid = worker_pid()
        self._set("Worker", bool(pid),
                  f"running — pid {pid}" if pid else "not running")

        both = o_up and pid
        self.sub.config(
            text="Ready — message the bot on Telegram" if both
            else "Not running — press Start",
            fg=OK if both else WARN)

        self.b_start.config(state="disabled" if both else "normal")
        self.b_stop.config(state="normal" if pid else "disabled")
        self.b_restart.config(state="normal" if pid else "disabled")

        self.root.after(4000, self.refresh)

    # actions
    def _busy(self, msg: str) -> None:
        self.status.config(text=msg)
        self.root.update_idletasks()

    def on_start(self) -> None:
        self._busy("Starting Ollama…")
        o = start_ollama()
        self._busy(f"Ollama: {o}\nStarting worker…")
        w = start_worker()
        self.status.config(text=f"Ollama: {o}\nWorker: {w}")

    def on_stop(self) -> None:
        self._busy("Stopping worker…")
        self.status.config(text=f"Worker: {stop_worker()}\nOllama left running.")

    def on_restart(self) -> None:
        self._busy("Restarting worker…")
        stop_worker()
        self.status.config(text=f"Worker: {start_worker()}")

    def on_log(self) -> None:
        target = ERRLOG if ERRLOG.exists() else LOG
        if target.exists():
            os.startfile(target)  # noqa: S606
        else:
            self.status.config(text="No log yet — start the worker first.")


def main() -> None:
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except tk.TclError:
        pass
    Panel(root)
    root.eval("tk::PlaceWindow . center")
    root.mainloop()


if __name__ == "__main__":
    main()
