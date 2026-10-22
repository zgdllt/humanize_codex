"""Exercise SDK workers and supervised publication without real model calls."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from hmz.sdk import Hmz, fakes

from humanize_codex.jobs import Jobs, prepare
from humanize_codex.store import TERMINAL, read_json
from humanize_codex.worker import work

DONE = {"action": "complete", "notes": "Independently checked", "evidence": ["fixture verified"]}


@pytest.fixture(autouse=True)
def no_real_cli_detection(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("humanize_codex.jobs.select_codex", lambda: Path("/bin/true"))
    monkeypatch.setattr("humanize_codex.worker.select_codex", lambda: Path("/bin/true"))
    monkeypatch.delenv("HUMANIZE_CODEX_SUPERVISED", raising=False)


@pytest.mark.parametrize("control", [None, "steer", "cancel"])
def test_worker_lifecycle_with_real_sdk_and_fake_agents(tmp_path, monkeypatch, control):
    data = tmp_path / "plugin-data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "hmz-home"))
    actor = fakes.FakeAgentDriver("codex", reply="Observed fixture")
    reviewer = fakes.FakeAgentDriver("codex", reply=DONE)

    class ScriptedRuntime:
        def __init__(self, workspace):
            self.runtime = Hmz(workspace)

        def run(self, *args, **kwargs):
            kwargs["agents"] = {
                "planner": fakes.FakeAgentDriver("codex"),
                "actor": actor,
                "reviewer": reviewer,
                "observer": fakes.FakeAgentDriver(
                    "codex", reply={"summary": "Checking fixture", "next_step": "Review"}
                ),
            }
            return self.runtime.run(*args, **kwargs)

    jobs = Jobs(data)
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(
            prepare(
                str(tmp_path),
                "Read fixture",
                mode="review",
                agent="codex/fake:low",
                max_rounds=1,
                duration_seconds=10,
                read_only=True,
            )
        )
    if control:
        jobs.control(state["job_id"], control, "Check the exact first line")
    # This is an in-process test of a worker that normally owns its process environment.
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "0")
    monkeypatch.setenv("PATH", __import__("os").environ["PATH"])
    with patch("hmz.sdk.Hmz", ScriptedRuntime), patch("humanize_codex.worker.signal.signal"):
        work(state["job_id"])
    result = jobs.status(state["job_id"])
    path = data / "runs" / state["job_id"]
    assert "finished" in read_json(path / "state.json")
    assert not (path / "outcome.json").exists()
    if control == "cancel":
        assert result["status"] == "cancelled"
        assert not actor.prompts
    else:
        assert result["status"] == "complete", result.get("error")
        assert result["epic"]
        if control == "steer":
            assert "Check the exact first line" in actor.prompts[0]
            assert any(event["kind"] == "control_receipt" for event in jobs.events(state["job_id"]))


def _scripted_worker(tmp_path, monkeypatch, terminal):
    from hmz.flows import BudgetExceeded

    from humanize_codex import worker

    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "0")
    monkeypatch.setenv("PATH", __import__("os").environ["PATH"])
    monkeypatch.setattr(worker, "guard_codex_startup", lambda: None)
    jobs = Jobs(data)
    with patch("humanize_codex.jobs.subprocess.Popen"):
        initial = jobs.start(
            prepare(str(tmp_path), "Scripted result", agent="codex/fake:low", retain_flow=True)
        )
    result = {
        **DONE,
        "status": terminal,
        "artifact": {"path": "fixture.txt", "checks": ["contents", "format"]},
    }
    raised = None
    if terminal == "failed":
        raised = RuntimeError("injected worker failure")
    elif terminal == "budget_exceeded":
        raised = BudgetExceeded("injected budget exhaustion")
    run = Mock(
        result=result,
        raised=raised,
        running=False,
        epic="fixture-epic",
        usage=SimpleNamespace(duration=timedelta(seconds=0.1), cost=0, output_tokens=0),
    )
    run.wait.return_value = True

    def runtime(workspace):
        if terminal == "startup_failure":
            raise RuntimeError("injected worker startup failure")
        return SimpleNamespace(run=lambda *a, **k: run)

    monkeypatch.setattr("hmz.sdk.Hmz", runtime)
    if terminal == "cancelled":
        jobs.control(initial["job_id"], "cancel")
    return jobs, initial["job_id"], result


@pytest.mark.parametrize(
    "terminal",
    [
        "complete",
        "blocked",
        "round_limit",
        "needs_work",
        "cancelled",
        "budget_exceeded",
        "failed",
        "startup_failure",
    ],
)
def test_supervised_worker_defers_every_terminal_and_finished_to_private_outcome(
    tmp_path, monkeypatch, terminal
):
    from humanize_codex import worker

    jobs, job_id, result = _scripted_worker(tmp_path, monkeypatch, terminal)
    path = jobs.root / "runs" / job_id
    monkeypatch.setenv("HUMANIZE_CODEX_SUPERVISED", job_id)
    public_writes = []
    atomic_json = worker.atomic_json

    def record_write(file, value):
        if file == path / "state.json":
            public_writes.append(deepcopy(value))
        atomic_json(file, value)

    retain = Mock(return_value={"name": "fixture_candidate", "successes": 1})
    monkeypatch.setattr(worker, "atomic_json", record_write)
    monkeypatch.setattr("humanize_codex.library.Library.retain", retain)
    with patch("humanize_codex.worker.signal.signal"):
        work(job_id)

    assert public_writes
    assert all(state["status"] not in TERMINAL for state in public_writes)
    assert all("finished" not in state for state in public_writes)
    state = read_json(path / "state.json")
    assert state["status"] == "cleaning_up"
    assert "finished" not in state
    assert jobs.wait(job_id, 0.02)["status"] == "cleaning_up"
    outcome = read_json(path / "outcome.json")
    assert outcome["status"] == ("failed" if terminal == "startup_failure" else terminal)
    assert outcome["job_id"] == job_id
    assert isinstance(outcome["finished"], (int, float))
    assert outcome["finished"] >= outcome["created"]
    assert outcome["active_agents"] == []
    if terminal != "startup_failure":
        assert outcome["epic"] == "fixture-epic"
        assert outcome["usage"] == {"duration_seconds": 0.1, "cost_usd": 0, "output_tokens": 0}
    if terminal in {"complete", "blocked", "round_limit", "needs_work"}:
        assert outcome["result"] == result
    elif terminal == "failed":
        assert "injected worker failure" in outcome["error"]
    elif terminal == "budget_exceeded":
        assert "injected budget exhaustion" in outcome["error"]
    elif terminal == "startup_failure":
        assert "injected worker startup failure" in outcome["error"]
    retain.assert_not_called()
    assert "retained_flow" not in state
    assert not any(event["kind"] == "flow_retained" for event in jobs.events(job_id))


@pytest.mark.parametrize("supervised_id", [None, "f" * 32], ids=["direct", "different-job"])
def test_worker_retains_direct_publication_unless_supervised_env_matches_job(
    tmp_path, monkeypatch, supervised_id
):
    jobs, job_id, result = _scripted_worker(tmp_path, monkeypatch, "complete")
    if supervised_id is not None:
        monkeypatch.setenv("HUMANIZE_CODEX_SUPERVISED", supervised_id)
    with patch("humanize_codex.worker.signal.signal"):
        work(job_id)

    path = jobs.root / "runs" / job_id
    actual = read_json(path / "state.json")
    assert actual["status"] == "complete"
    assert isinstance(actual["finished"], (int, float))
    assert actual["result"] == result
    assert actual["retained_flow"]
    assert any(event["kind"] == "flow_retained" for event in jobs.events(job_id))
    assert not (path / "outcome.json").exists()
