"""A real blocking Python import must not defeat duration or cancel boundaries."""

import time
from pathlib import Path

import pytest

from humanize_codex.jobs import Jobs, prepare

EXAMPLE = Path(__file__).resolve().parent.parent / "examples/control_structures.py"


@pytest.mark.parametrize("cancel", [False, True])
def test_supervisor_kills_blocked_import_and_releases_workspace(tmp_path, monkeypatch, cancel):
    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    source = tmp_path / "blocking.py"
    source.write_text("import time\ntime.sleep(60)\n" + EXAMPLE.read_text())
    jobs = Jobs(data)
    request = prepare(
        str(tmp_path),
        "No agent turn",
        flow_file=str(source),
        entrypoint="sequence_flow",
        agent="dsh/fake:low",
        duration_seconds=20 if cancel else 0.5,
        retain_flow=False,
    )
    state = jobs.start(request)
    if cancel:
        jobs.control(state["job_id"], "cancel")
        # Simulate worker consumption before the supervisor's next poll.
        for file in (data / "runs" / state["job_id"] / "inbox").glob("*.json"):
            file.unlink()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        state = jobs.wait(state["job_id"], 0.2)
        if state["status"] in {"cancelled", "budget_exceeded", "failed"}:
            break
    assert state["status"] == ("cancelled" if cancel else "budget_exceeded"), state
    # Wait only for the supervisor to reap descendants and release the ownership lock.
    from humanize_codex.store import workspace_locked

    while True:
        try:
            with workspace_locked(data, str(tmp_path)):
                break
        except ValueError:
            assert time.monotonic() < deadline
            time.sleep(0.05)


def test_budget_cleanup_stops_detached_descendant_before_terminal(tmp_path, monkeypatch):
    import json

    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    marker = tmp_path / "late-write"
    script = f"import time; from pathlib import Path; time.sleep(4); Path({str(marker)!r}).touch()"
    source = tmp_path / "detached.py"
    source.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {script!r}], start_new_session=True)\n"
        "time.sleep(60)\n" + EXAMPLE.read_text()
    )
    jobs = Jobs(data)
    state = jobs.start(
        prepare(
            str(tmp_path),
            "No model",
            agent="dsh/fake:low",
            duration_seconds=1,
            flow_file=str(source),
            entrypoint="sequence_flow",
            retain_flow=False,
        )
    )
    state = jobs.wait(state["job_id"], 8)
    assert state["status"] == "budget_exceeded", json.dumps(state)
    # The detached process would have written after the old group-only cleanup.
    time.sleep(1.5)
    assert not marker.exists()


def test_budget_reason_preserved_when_runner_exits_cooperatively(tmp_path, monkeypatch):
    import sys
    from unittest.mock import patch

    from humanize_codex.store import read_json
    from humanize_codex.supervisor import supervise

    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    jobs = Jobs(data)
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(prepare(str(tmp_path), "No model", duration_seconds=0.3))
    path = data / "runs" / state["job_id"] / "state.json"
    script = (
        "import signal, time, pathlib, json\n"
        "def stop(*args):\n"
        f" p=pathlib.Path({str(path)!r}); s=json.loads(p.read_text()); "
        "s['status']='cancelled'; p.write_text(json.dumps(s)); raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "time.sleep(30)\n"
    )
    import subprocess

    real_popen = subprocess.Popen

    def child(*args, **kwargs):
        return real_popen([sys.executable, "-c", script], **kwargs)

    with patch("humanize_codex.supervisor.subprocess.Popen", child):
        supervise(state["job_id"])
    assert read_json(path)["status"] == "budget_exceeded"
