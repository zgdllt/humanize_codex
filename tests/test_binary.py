"""A stale Homebrew CLI must not override the newer CLI the user's TUI runs."""

from pathlib import Path
from unittest.mock import patch

import pytest

from humanize_codex.binary import select_codex


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_newer_local_install_wins_over_stale_path_binary(tmp_path, monkeypatch):
    old = executable(tmp_path / "homebrew/bin/codex")
    new = executable(tmp_path / "home/.local/bin/codex")
    monkeypatch.setenv("PATH", str(old.parent))
    monkeypatch.delenv("HUMANIZE_CODEX_BINARY", raising=False)
    with patch.object(Path, "home", return_value=tmp_path / "home"):
        with patch(
            "humanize_codex.binary.version",
            side_effect=lambda p: (0, 163, 0, 1) if p == new else (0, 154, 0, 1),
        ):
            assert select_codex() == new


def test_explicit_binary_is_honored_even_if_older(tmp_path, monkeypatch):
    chosen = executable(tmp_path / "chosen/codex")
    monkeypatch.setenv("HUMANIZE_CODEX_BINARY", str(chosen))
    with patch("humanize_codex.binary.version", return_value=(0, 154, 0, 1)):
        assert select_codex() == chosen


def test_bad_explicit_binary_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMANIZE_CODEX_BINARY", "relative/codex")
    with pytest.raises(ValueError, match="absolute"):
        select_codex()
