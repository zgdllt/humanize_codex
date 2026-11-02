"""Keep existing lifecycle unit tests independent of a user's desktop and tmux server."""

import subprocess
import sys

import pytest


@pytest.fixture(autouse=True)
def native_viewer_boundary(monkeypatch, request):
    if request.node.get_closest_marker("native"):
        return
    monkeypatch.setattr("humanize_codex.native.prepare_host", lambda *args: {})
    monkeypatch.setattr(
        "humanize_codex.viewer.describe",
        lambda workspace, job_id: {"kind": "test", "workspace": workspace},
    )

    def launch(path, spec, env):
        with (path / "worker.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "humanize_codex.cli", "worker", path.name],
                cwd=spec["workspace"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        return {"kind": "test", "pid": process.pid}

    monkeypatch.setattr("humanize_codex.viewer.launch", launch)
