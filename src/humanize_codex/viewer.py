"""Choose the upstream app or a named tmux session, and start the actual workflow there."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import psutil

from .store import atomic_json, read_json


def app_path() -> Path | None:
    if sys.platform == "darwin":
        for directory in (Path("/Applications"), Path.home() / "Applications"):
            for name in ("humanize.app", "Humanize.app"):
                path = directory / name
                if path.is_dir():
                    return path
    return None


def mode() -> str:
    if any(os.environ.get(key) for key in ("SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "TMUX")):
        return "tmux"
    if sys.stdin.isatty() or sys.stdout.isatty():
        return "tmux"
    if os.environ.get("TERM_PROGRAM"):
        return "tmux"
    # MCP stdio is piped in both CLI and desktop. A bundled codex executable can also
    # be run from a terminal; only the actual GUI ancestor identifies desktop mode.
    for parent in psutil.Process().parents():
        try:
            if parent.exe().endswith(("/Contents/MacOS/Codex", "/Contents/MacOS/ChatGPT")):
                return "app" if app_path() else "tmux"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return "tmux"


def describe(workspace: str, job_id: str) -> dict:
    selected = mode()
    view = {"kind": selected, "workspace": workspace, "slot": f"chat:{job_id}", "job_id": job_id}
    if selected == "app":
        view.update(
            app=str(app_path()),
            live_route="#/@local/live?" + urlencode({"workspace": workspace, "slot": view["slot"]}),
            instruction="In Humanize app, open this workspace's running epic "
            "to see its graph, sessions and tools.",
        )
    else:
        binary = shutil.which("tmux")
        if not binary:
            raise ValueError("Terminal/SSH runs require tmux. Install tmux on this host and retry.")
        session = f"humanize-{job_id[:12]}"
        view.update(
            tmux=binary,
            session=session,
            window="tui",
            attach_command=f"tmux attach-session -t {session}",
            switch_command=f"tmux switch-client -t {session}",
        )
    return view


def _session_command(path: Path, env: dict, command: str) -> str:
    # tmux servers keep an older environment. Forward this invocation privately, never
    # putting provider credentials into tmux process arguments or shell command strings.
    atomic_json(path / "launch-env.json", env)
    script = path / "start-session.py"
    script.write_text(
        "import json, os, sys\n"
        f"env = json.load(open({str(path / 'launch-env.json')!r}, encoding='utf-8'))\n"
        "env.update({k: os.environ[k] for k in ('TERM', 'TMUX', 'TMUX_PANE') if k in os.environ})\n"
        f"args = [sys.executable, '-m', 'humanize_codex.cli', sys.argv[1], {path.name!r}]\n"
        "os.execve(sys.executable, args, env)\n",
        encoding="utf-8",
    )
    return shlex.join([sys.executable, str(script), command])


def _tui_session(path: Path, request: dict, env: dict, *, run_flow: bool) -> dict:
    view = request["viewer"]
    binary, session = view["tmux"], view["session"]
    tui_command = _session_command(path, env, "tui")
    subprocess.run(
        [
            binary,
            "new-session",
            "-d",
            "-s",
            session,
            "-n",
            "tui",
            "-c",
            request["workspace"],
            tui_command,
        ],
        check=True,
        timeout=10,
        env=env,
    )
    subprocess.run(
        [binary, "set-option", "-t", session, "remain-on-exit", "on"], check=True, timeout=10
    )
    if run_flow:
        # A fast flow can finish before Textual imports. Hold its native TUI link first,
        # so the actual run and its replay remain available in this session.
        deadline = time.monotonic() + 10
        while not (path / "tui-ready.json").is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("Humanize TUI did not attach; inspect the tmux tui window")
            time.sleep(0.05)
        flow_command = (
            _session_command(path, env, "worker")
            + " >> "
            + shlex.quote(str(path / "worker.log"))
            + " 2>&1"
        )
        subprocess.run(
            [
                binary,
                "new-window",
                "-t",
                session,
                "-n",
                "flow",
                "-c",
                request["workspace"],
                flow_command,
            ],
            check=True,
            timeout=10,
            env=env,
        )
    subprocess.run([binary, "select-window", "-t", f"{session}:tui"], check=True, timeout=10)
    return view


def launch(path: Path, request: dict, env: dict) -> dict:
    """Start the workflow with its native viewer available from the beginning."""
    view = request["viewer"]
    if view["kind"] == "tmux":
        return _tui_session(path, request, env, run_flow=True)
    subprocess.run(["open", "-a", view["app"]], check=True, timeout=10)
    with (path / "worker.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "humanize_codex.cli", "worker", path.name],
            cwd=request["workspace"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    return {**view, "pid": process.pid}


def reopen(path: Path, request: dict) -> dict:
    """Open the existing run's viewer; never start its flow a second time."""
    view = request["viewer"]
    if view["kind"] == "app":
        subprocess.run(["open", "-a", view["app"]], check=True, timeout=10)
        return view
    found = subprocess.run(
        [view["tmux"], "has-session", "-t", view["session"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    if found.returncode == 0:
        pane = subprocess.run(
            [view["tmux"], "display-message", "-p", "-t", f"{view['session']}:tui", "#{pane_dead}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if pane.returncode == 0 and pane.stdout.strip() == "0":
            return view
        command = _session_command(
            path, {**os.environ, "HUMANIZE_CODEX_DATA": str(path.parent.parent)}, "tui"
        )
        if pane.returncode == 0:
            subprocess.run(
                [view["tmux"], "respawn-pane", "-t", f"{view['session']}:tui", command],
                check=True,
                timeout=10,
            )
        else:
            subprocess.run(
                [
                    view["tmux"],
                    "new-window",
                    "-t",
                    view["session"],
                    "-n",
                    "tui",
                    "-c",
                    request["workspace"],
                    command,
                ],
                check=True,
                timeout=10,
            )
        state = read_json(path / "state.json")
        return {
            **view,
            "epic": state.get("epic"),
            "instruction": "If the live host has ended, /epics opens the saved run.",
        }
    return _tui_session(
        path,
        request,
        {**os.environ, "HUMANIZE_CODEX_DATA": str(path.parent.parent)},
        run_flow=False,
    )
