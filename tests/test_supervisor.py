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
        "import signal, time, pathlib\n"
        "from humanize_codex.store import atomic_json, read_json\n"
        "def stop(*args):\n"
        f" p=pathlib.Path({str(path)!r}); s=read_json(p)\n"
        " atomic_json(p.with_name('outcome.json'), "
        "{**s, 'status': 'cancelled', 'finished': time.time()})\n"
        " atomic_json(p, {**s, 'status': 'cleaning_up'})\n"
        " raise SystemExit(0)\n"
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


@pytest.mark.parametrize("outcome", ["complete", "cancelled", "budget_exceeded", "failed"])
@pytest.mark.parametrize("cleanup_failures", [0, 4])
def test_cleanup_retains_ownership_until_all_descendants_exit(
    tmp_path, monkeypatch, capsys, outcome, cleanup_failures
):
    from unittest.mock import Mock

    from humanize_codex import supervisor
    from humanize_codex.store import TERMINAL, atomic_json, read_json, workspace_locked

    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    job_id = "a" * 32
    path = data / "runs" / job_id
    atomic_json(
        path / "request.json",
        {
            "workspace": str(tmp_path),
            "budget": {"duration": 0 if outcome == "budget_exceeded" else 60},
            "retain_flow": False,
        },
    )
    now = time.time()
    initial = {
        "job_id": job_id,
        "status": "cleaning_up" if outcome == "complete" else "running",
        "created": now,
        "heartbeat": now,
        "active_agents": [{"role": "actor"}],
    }
    if outcome == "complete":
        atomic_json(
            path / "outcome.json",
            {**initial, "status": "complete", "finished": now, "error": "Worker result retained"},
        )
    atomic_json(path / "state.json", initial)
    if outcome == "cancelled":
        atomic_json(path / "cancel.json", {})

    descendant_alive = True
    observations, waits, launches = [], [], []
    runner = Mock(pid=12345, returncode=0 if outcome == "complete" else None)
    runner.poll.return_value = runner.returncode

    def reap():
        waits.append(descendant_alive)
        runner.returncode = 0 if outcome == "complete" else -9

    runner.wait.side_effect = reap

    class Tree:
        def __init__(self, pid):
            self.attempts = 0

        def capture(self):
            if outcome == "failed":
                raise RuntimeError("injected monitor failure")

        def close(self):
            nonlocal descendant_alive
            self.attempts += 1
            try:
                with workspace_locked(data, str(tmp_path)):
                    held = False
            except ValueError:
                held = True
            observations.append((held, descendant_alive, read_json(path / "state.json")))
            if self.attempts <= cleanup_failures:
                raise TimeoutError("injected surviving descendant 54321")
            descendant_alive = False

    def launch(*args, **kwargs):
        launches.append(kwargs)
        return runner

    monkeypatch.setattr(supervisor.subprocess, "Popen", launch)
    monkeypatch.setattr(supervisor, "ProcessTree", Tree)
    monkeypatch.setattr(supervisor, "GRACE_SECONDS", 0)
    monkeypatch.setattr(supervisor, "CLEANUP_RETRY_SECONDS", 0)
    supervisor.supervise(job_id)

    assert len(observations) == cleanup_failures + 1
    assert launches[0]["env"]["HUMANIZE_CODEX_SUPERVISED"] == job_id
    assert launches[0]["env"]["HUMANIZE_CODEX_DATA"] == str(data)
    assert all(held and alive for held, alive, _ in observations)
    assert all(state["status"] not in TERMINAL for _, _, state in observations)
    assert all("finished" not in state for _, _, state in observations)
    assert waits == [False]
    for _, _, pending in observations[1:]:
        assert pending["status"] == "cleaning_up"
        assert pending["status"] not in TERMINAL
        assert "TimeoutError" in pending["error"]
        assert "workspace stays locked" in pending["error"]
        assert pending["heartbeat"] > now
        assert "finished" not in pending
    actual = read_json(path / "state.json")
    assert actual["status"] == outcome
    assert actual["active_agents"] == []
    assert "finished" in actual
    if outcome == "complete":
        assert actual["error"] == "Worker result retained"
    if outcome == "failed":
        assert "injected monitor failure" in actual["error"]
    if cleanup_failures:
        assert "surviving descendant 54321" in actual["cleanup_error"]
        assert capsys.readouterr().err.count("workspace stays locked") == cleanup_failures
    else:
        assert "cleanup_error" not in actual
    with workspace_locked(data, str(tmp_path)):
        assert not descendant_alive


def test_cleanup_timeout_holds_lock_for_real_detached_descendant(tmp_path, monkeypatch, capsys):
    import subprocess
    import sys

    import psutil

    from humanize_codex import supervisor
    from humanize_codex.processes import ProcessTree
    from humanize_codex.store import atomic_json, read_json, workspace_locked

    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    job_id = "b" * 32
    path = data / "runs" / job_id
    atomic_json(
        path / "request.json",
        {"workspace": str(tmp_path), "budget": {"duration": 60}, "retain_flow": False},
    )
    now = time.time()
    initial = {"status": "cleaning_up", "created": now, "heartbeat": now}
    atomic_json(path / "state.json", initial)
    atomic_json(path / "outcome.json", {**initial, "status": "complete", "finished": now})
    jobs = Jobs(data)
    pid_file = tmp_path / "descendant.pid"
    script = (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "start_new_session=True)\n"
        f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    runner = subprocess.Popen([sys.executable, "-c", script], start_new_session=True)
    tree = ProcessTree(runner.pid)
    descendant = None
    kill = psutil.Process.kill
    close = tree.close
    observations = []
    attempts = 0
    try:
        deadline = time.monotonic() + 5
        while not pid_file.exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        descendant = psutil.Process(int(pid_file.read_text()))
        tree.capture()
        assert descendant.pid in tree.owned
        # The runner has completed, but its tracked detached writer is still alive.
        runner.terminate()
        runner.wait(timeout=5)

        def delayed_kill(process):
            if process.pid != descendant.pid or attempts > 4:
                kill(process)

        def close_with_timeout():
            nonlocal attempts
            attempts += 1
            if attempts <= 4:
                try:
                    with workspace_locked(data, str(tmp_path)):
                        held = False
                except ValueError:
                    held = True
                observations.append((held, descendant.is_running(), jobs.wait(job_id, 0.02)))
            close(timeout=0.02)

        monkeypatch.setattr(psutil.Process, "kill", delayed_kill)
        monkeypatch.setattr(tree, "close", close_with_timeout)
        monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: runner)
        monkeypatch.setattr(supervisor, "ProcessTree", lambda pid: tree)
        monkeypatch.setattr(supervisor, "CLEANUP_RETRY_SECONDS", 0)
        supervisor.supervise(job_id)

        assert attempts >= 5
        assert all(held and alive for held, alive, _ in observations)
        assert all(state["status"] == "cleaning_up" for _, _, state in observations)
        assert all("finished" not in state for _, _, state in observations)
        actual = read_json(path / "state.json")
        assert actual["status"] == "complete"
        assert str(descendant.pid) in actual["cleanup_error"]
        assert "workspace stays locked" in capsys.readouterr().err
        with workspace_locked(data, str(tmp_path)):
            assert not descendant.is_running() or descendant.status() == psutil.STATUS_ZOMBIE
    finally:
        if descendant is not None:
            try:
                kill(descendant)
            except psutil.NoSuchProcess:
                pass
        if runner.poll() is None:
            runner.kill()
        runner.wait(timeout=5)


@pytest.mark.parametrize("cancel_phase", [None, "during-cleanup", "after-timeout"])
def test_cleanup_defers_wait_terminal_and_merges_cancel_before_retention(
    tmp_path, monkeypatch, cancel_phase
):
    from copy import deepcopy
    from unittest.mock import Mock, patch

    from humanize_codex import supervisor
    from humanize_codex.store import TERMINAL, atomic_json, read_json, workspace_locked

    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    jobs = Jobs(data)
    with patch("humanize_codex.jobs.subprocess.Popen"):
        initial = jobs.start(
            prepare(str(tmp_path), "No model", agent="dsh/fake:low", retain_flow=True)
        )
    job_id = initial["job_id"]
    path = data / "runs" / job_id
    # Steering accepted before cleanup must receive an explicit undelivered receipt.
    queued_steer = jobs.control(job_id, "steer", "Queued before worker exit")
    public = {**read_json(path / "state.json"), "status": "cleaning_up"}
    result = {
        "status": "complete",
        "action": "complete",
        "evidence": ["fixture verified"],
        "payload": {"answer": 42},
    }
    atomic_json(path / "state.json", public)
    atomic_json(
        path / "outcome.json",
        {**public, "status": "complete", "finished": time.time(), "result": result},
    )
    alive = True
    cleanup_finished = None
    observations, public_writes, retention, cancellations, steer_errors = [], [], [], [], []
    cancel_errors = []
    attempts = 0
    runner = Mock(pid=12345, returncode=0)
    runner.poll.return_value = 0
    runner.wait.return_value = 0

    def record_write(file, value):
        if file == path / "state.json":
            public_writes.append((alive, deepcopy(value)))
        atomic_json(file, value)

    def retain(job):
        retention.append((alive, read_json(path / "state.json")))
        return {"name": "fixture_candidate", "successes": 1}

    retain_mock = Mock(side_effect=retain)

    class Tree:
        def __init__(self, pid):
            pass

        def close(self):
            nonlocal alive, attempts, cleanup_finished
            attempts += 1
            began = time.monotonic()
            waiting = jobs.wait(job_id, 0.03)
            try:
                with workspace_locked(data, str(tmp_path)):
                    held = False
            except ValueError:
                held = True
            observations.append((waiting, time.monotonic() - began, held, retain_mock.call_count))
            if cancel_phase == "after-timeout" and attempts == 1:
                raise TimeoutError("injected cleanup timeout before late cancellation")
            try:
                jobs.control(job_id, "steer", "Cannot reach an exited worker")
            except ValueError as error:
                steer_errors.append(str(error))
            if cancel_phase is not None:
                try:
                    cancellations.append(jobs.control(job_id, "cancel"))
                except ValueError as error:
                    cancel_errors.append(str(error))
                observations.append((jobs.wait(job_id, 0.03), None, held, retain_mock.call_count))
            alive = False
            cleanup_finished = time.time()

    monkeypatch.setattr(supervisor, "ProcessTree", Tree)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: runner)
    monkeypatch.setattr(supervisor, "atomic_json", record_write)
    monkeypatch.setattr(supervisor, "CLEANUP_RETRY_SECONDS", 0)
    monkeypatch.setattr("humanize_codex.library.Library.retain", retain_mock)
    supervisor.supervise(job_id)

    assert observations
    for waiting, elapsed, held, retained in observations:
        assert waiting["status"] == "cleaning_up"
        assert waiting["status"] not in TERMINAL
        assert "finished" not in waiting
        assert held
        assert retained == 0
        if elapsed is not None:
            assert elapsed >= 0.02
    assert len(steer_errors) == 1
    assert "cleaning up" in steer_errors[0].lower()
    assert public_writes
    assert all(
        not was_alive
        for was_alive, state in public_writes
        if state["status"] in TERMINAL or "finished" in state
    )
    actual = jobs.wait(job_id, 0)
    assert actual["finished"] >= cleanup_finished
    receipts = {
        event["ticket"]: event["delivery"]
        for event in jobs.events(job_id)
        if event["kind"] == "control_receipt"
    }
    assert receipts[queued_steer["ticket"]] == "not_delivered"
    assert not list((path / "inbox").glob("*.json"))
    if cancel_phase is None:
        assert actual["status"] == "complete"
        assert actual["result"] == result
        retain_mock.assert_called_once_with(job_id)
        assert retention[0][0] is False
        assert retention[0][1]["status"] == "complete"
        assert "finished" in retention[0][1]
        assert actual["retained_flow"] == "fixture_candidate"
    else:
        assert not cancel_errors
        assert len(cancellations) == 1
        assert cancellations[0]["status"] == "queued"
        assert actual["status"] == "cancelled"
        assert receipts[cancellations[0]["ticket"]] == "stopped"
        retain_mock.assert_not_called()
        assert "retained_flow" not in actual
        assert not any(event["kind"] == "flow_retained" for event in jobs.events(job_id))
    with workspace_locked(data, str(tmp_path)):
        assert not alive


@pytest.mark.parametrize("failed_report", ["state", "stderr", "both"])
def test_cleanup_keeps_ownership_when_reporting_fails(tmp_path, monkeypatch, capsys, failed_report):
    from unittest.mock import Mock

    from humanize_codex import supervisor
    from humanize_codex.store import atomic_json, workspace_locked

    data = tmp_path / "data"
    path = data / "runs" / ("c" * 32)
    atomic_json(path / "state.json", {"status": "running", "heartbeat": time.time()})
    held = []

    def close():
        try:
            with workspace_locked(data, str(tmp_path)):
                held.append(False)
        except ValueError:
            held.append(True)
        if len(held) <= 4:
            raise TimeoutError("injected cleanup timeout")

    def broken_write(*args):
        raise OSError("injected status write failure")

    def broken_print(*args, **kwargs):
        raise OSError("injected log write failure")

    tree, runner = Mock(), Mock()
    tree.close.side_effect = close
    if failed_report in {"state", "both"}:
        monkeypatch.setattr(supervisor, "atomic_json", broken_write)
    if failed_report in {"stderr", "both"}:
        monkeypatch.setattr(supervisor, "print", broken_print, raising=False)
    monkeypatch.setattr(supervisor, "CLEANUP_RETRY_SECONDS", 0)
    with workspace_locked(data, str(tmp_path)):
        supervisor._cleanup(tree, runner, path)
    assert held == [True] * 5
    runner.wait.assert_called_once()
    if failed_report == "state":
        assert capsys.readouterr().err.count("injected status write failure") == 4
