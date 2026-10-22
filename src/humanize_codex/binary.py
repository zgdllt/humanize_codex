"""Choose the current installed CLI rather than a stale executable shadowing it on PATH."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def version(path: Path) -> tuple[int, int, int, int]:
    """Read a bounded --version response, ordering stable builds before prereleases."""
    result = subprocess.run(
        [str(path), "--version"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    match = re.search(r"codex-cli (\d+)\.(\d+)\.(\d+)([^\s]*)", result.stdout)
    if not match:
        raise ValueError(f"Not a recognized Codex executable: {path}")
    return (*map(int, match.group(1, 2, 3)), int(not match.group(4)))


def select_codex() -> Path:
    """Honor an explicit binary, otherwise choose the newest local/PATH Codex installation."""
    override = os.environ.get("HUMANIZE_CODEX_BINARY")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("HUMANIZE_CODEX_BINARY must name an executable absolute path")
        version(path)
        return path
    candidates = [Path.home() / ".local/bin/codex"]
    candidates.extend(Path(part) / "codex" for part in os.get_exec_path() if part)
    found = []
    seen = set()
    for path in candidates:
        if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
            continue
        real = path.resolve()
        if real in seen:
            continue
        seen.add(real)
        try:
            found.append((version(path), path))
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    if not found:
        raise ValueError("No working Codex CLI found; install Codex or set HUMANIZE_CODEX_BINARY")
    return max(found, key=lambda entry: entry[0])[1]
