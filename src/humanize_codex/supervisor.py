"""Bound the whole worker process, including trusted Python imports and blocking code."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time

from .library import retain_completed
from .processes import ProcessTree
from .store import TERMINAL, atomic_json, data_root, job_path, locked, read_json, workspace_locked

GRACE_SECONDS = 2
CLEANUP_RETRY_SECONDS = 1


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


def _cleanup(tree, runner, path):
    """Retain workspace ownership until cleanup succeeds, reporting every failed attempt."""
    previous_state, cleanup_error = None, ""
    while True:
        try:
            tree.close()
            runner.wait()
            return previous_state, cleanup_error
        except Exception as error:
            cleanup_error = f"Supervisor cleanup: {type(error).__name__}: {error}"
            message = f"{cleanup_error}; workspace stays locked; retrying cleanup"
            with contextlib.suppress(OSError):
                print(message, file=sys.stderr, flush=True)
            try:
                state = read_json(path / "state.json")
                if previous_state is None:
                    previous_state = state
                pending = {
                    **state,
                    "status": "cleaning_up",
                    "error": message,
                    "heartbeat": time.time(),
                }
                pending.pop("finished", None)
                atomic_json(path / "state.json", pending)
            except Exception as report_error:
                # A failed status write must not release ownership of live descendants.
                with contextlib.suppress(OSError):
                    print(
                        f"Could not record cleanup status: {report_error}",
                        file=sys.stderr,
                        flush=True,
                    )
            time.sleep(CLEANUP_RETRY_SECONDS)


def supervise(job_id: str) -> None:
    root = data_root()
    path = job_path(root, job_id)
    request = read_json(path / "request.json")
    with workspace_locked(root, request["workspace"], wait=True):
        runner = subprocess.Popen(
            [sys.executable, "-m", "humanize_codex.cli", "execute-worker", job_id],
            start_new_session=True,
            env={**os.environ, "HUMANIZE_CODEX_SUPERVISED": job_id},
        )
        tree = ProcessTree(runner.pid)
        deadline = time.monotonic() + request["budget"]["duration"]
        reason, stop_at = "", 0.0
        forced, supervisor_error = False, ""
        try:
            while runner.poll() is None:
                tree.capture()
                cancelled = _cancel_requested(path)
                if not reason and (cancelled or time.monotonic() >= deadline):
                    reason = "cancelled" if cancelled else "budget_exceeded"
                    stop_at = time.monotonic()
                    runner.send_signal(signal.SIGTERM)
                if reason and time.monotonic() - stop_at >= GRACE_SECONDS:
                    forced = True
                    break
                time.sleep(0.1)
        except Exception as error:
            supervisor_error = f"Supervisor: {type(error).__name__}: {error}"
        finally:
            previous_state, cleanup_error = _cleanup(tree, runner, path)
        outcome = path / "outcome.json"
        state = (
            read_json(outcome)
            if outcome.is_file()
            else previous_state or read_json(path / "state.json")
        )
        # Serialize the final cancel check and terminal publication with control enqueue.
        with locked(root):
            if not reason and _cancel_requested(path):
                reason = "cancelled"
            if supervisor_error:
                state.update(status="failed", error=supervisor_error)
            elif reason or state["status"] not in TERMINAL:
                state.update(
                    status=reason or "failed",
                    error="Worker process tree stopped after the cleanup grace period"
                    if forced
                    else f"Worker exited with code {runner.returncode}",
                )
            if cleanup_error:
                state["cleanup_error"] = cleanup_error
            atomic_json(
                path / "state.json",
                {**state, "finished": time.time(), "heartbeat": time.time(), "active_agents": []},
            )
            for file in (path / "inbox").glob("*.json"):
                item = read_json(file)
                with (path / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "at": time.time(),
                                "kind": "control_receipt",
                                "ticket": item["ticket"],
                                "delivery": "stopped"
                                if item["kind"] == "cancel"
                                else "not_delivered",
                            }
                        )
                        + "\n"
                    )
                file.unlink()
        retain_completed(root, job_id)
