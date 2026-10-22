"""Launch the pinned plugin environment without modifying the user's Python environment."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if not Path(uv).is_file():
        raise SystemExit("Humanfia Humanize requires uv: https://docs.astral.sh/uv/")
    data = Path(
        os.environ.get("PLUGIN_DATA")
        or os.environ.get("CLAUDE_PLUGIN_DATA")
        or Path.home() / ".local/share/humanfia-humanize-codex"
    )
    data.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HUMANIZE_CODEX_DATA", str(data.resolve()))
    os.environ["UV_PROJECT_ENVIRONMENT"] = str(data / "runtime")
    args = [
        uv,
        "run",
        "--project",
        str(root),
        "--python",
        "3.14",
        "--frozen",
        "--no-dev",
        "humanize-codex",
        *sys.argv[1:],
    ]
    os.execv(uv, args)


if __name__ == "__main__":
    main()
