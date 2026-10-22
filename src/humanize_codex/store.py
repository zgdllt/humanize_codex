"""Local durable job records and per-workspace single-writer coordination."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

TERMINAL = {"complete", "blocked", "round_limit", "budget_exceeded", "cancelled", "failed", "lost"}


def data_root() -> Path:
    """Use plugin-owned writable storage, also outside a plugin host."""
    root = (
        Path(
            os.environ.get("HUMANIZE_CODEX_DATA")
            or os.environ.get("PLUGIN_DATA")
            or os.environ.get("CLAUDE_PLUGIN_DATA")
            or Path.home() / ".local/share/humanfia-humanize-codex"
        )
        .expanduser()
        .resolve()
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Replace a JSON record atomically so readers never see half a heartbeat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, default=str)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path: Path) -> dict[str, Any]:
    """Read a plugin record, refusing a malformed or non-object record."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Invalid job record: {path.name}")
    return value


def job_path(root: Path, job_id: str) -> Path:
    """Resolve only plugin-generated IDs, never user-supplied filesystem paths."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("job_id must be the 32-character ID returned by humanize_run")
    path = root / "runs" / job_id
    if not (path / "request.json").is_file():
        raise ValueError(f"Unknown Humanize job: {job_id}")
    return path


@contextlib.contextmanager
def locked(root: Path) -> Iterator[None]:
    """Serialize starts and control-message writes across MCP server processes."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".jobs.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


@contextlib.contextmanager
def workspace_locked(root: Path, workspace: str, *, wait: bool = False) -> Iterator[None]:
    """Hold actual workspace ownership even if a worker's heartbeat has stalled."""
    directory = root / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(workspace.encode()).hexdigest()
    with (directory / f"{digest}.lock").open("a") as stream:
        flags = fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
        try:
            fcntl.flock(stream, flags)
        except BlockingIOError as error:
            raise ValueError("This workspace already has an active job") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
