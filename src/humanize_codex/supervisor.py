"""Bound the whole worker process, including trusted Python imports and blocking code."""

from __future__ import annotations

import signal
import subprocess
import sys
import time

from .processes import ProcessTree
from .store import TERMINAL, atomic_json, data_root, job_path, read_json, workspace_locked

GRACE_SECONDS = 2


def _cancel_requested(path) -> bool:
    if (path / "cancel.json").is_file():
        return True
    for file in (path / "inbox").glob("*.json"):
        try:
            if read_json(file).get("kind") == "cancel":
                return True
        except FileNotFoundError:
            pass  # The cooperative runner may have consumed this receipt concurrently.
    return False


def supervise(job_id: str) -> None:
    root = data_root()
    path = job_path(root, job_id)
    request = read_json(path / "request.json")
    with workspace_locked(root, request["workspace"], wait=True):
        runner = subprocess.Popen(
            [sys.executable, "-m", "humanize_codex.cli", "execute-worker", job_id],
            start_new_session=True,
        )
        tree = ProcessTree(runner.pid)
        deadline = time.monotonic() + request["budget"]["duration"]
        reason, stop_at = "", 0.0
        try:
            while runner.poll() is None:
                tree.capture()
                cancelled = _cancel_requested(path)
                if not reason and (cancelled or time.monotonic() >= deadline):
                    reason = "cancelled" if cancelled else "budget_exceeded"
                    stop_at = time.monotonic()
                    runner.send_signal(signal.SIGTERM)
                if reason and time.monotonic() - stop_at >= GRACE_SECONDS:
                    tree.close()
                    runner.wait()
                    state = read_json(path / "state.json")
                    atomic_json(
                        path / "state.json",
                        {
                            **state,
                            "status": reason,
                            "error": "Worker process group stopped after the cleanup grace period",
                            "heartbeat": time.time(),
                            "finished": time.time(),
                            "active_agents": [],
                        },
                    )
                    return
                time.sleep(0.1)
            tree.close()
            state = read_json(path / "state.json")
            if reason or state["status"] not in TERMINAL:
                atomic_json(
                    path / "state.json",
                    {
                        **state,
                        "status": reason or "failed",
                        "error": f"Worker exited with code {runner.returncode}",
                        "heartbeat": time.time(),
                        "finished": time.time(),
                    },
                )
        except Exception as error:
            tree.close()
            runner.wait()
            state = read_json(path / "state.json")
            atomic_json(
                path / "state.json",
                {
                    **state,
                    "status": "failed",
                    "error": f"Supervisor: {type(error).__name__}: {error}",
                    "finished": time.time(),
                    "heartbeat": time.time(),
                },
            )
        finally:
            tree.close()
            runner.wait()
