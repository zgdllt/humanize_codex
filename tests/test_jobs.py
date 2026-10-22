"""Validate job boundaries, single-writer ownership and honest lifecycle reporting."""

import json
import time
from unittest.mock import patch

import pytest

from humanize_codex.jobs import Jobs, prepare
from humanize_codex.store import atomic_json, job_path, read_json, workspace_locked


@pytest.fixture(autouse=True)
def no_real_cli_detection(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("humanize_codex.jobs.select_codex", lambda: Path("/bin/true"))


@pytest.mark.parametrize(
    "extra",
    [
        {"duration_seconds": float("nan")},
        {"duration_seconds": float("inf")},
        {"duration_seconds": 0},
        {"cost_usd": -1},
        {"max_rounds": True},
        {"output_tokens": 1.2},
        {"mode": "unknown"},
        {"agent": "codex/"},
        {"agent": "codex/m,other=value"},
        {"agent": "claude/model"},
        {"agents": {"unknown": "codex/model"}},
        {"agents": {"actor": "dsh/"}},
        {"agents": {"observer": "dsh/model:medium"}},
        {"flow_file": "relative.py"},
    ],
)
def test_invalid_execution_settings_are_rejected(tmp_path, extra):
    with pytest.raises(ValueError):
        prepare(str(tmp_path), "Task", **extra)


def test_nested_workflow_is_not_launched(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "1")
    with pytest.raises(ValueError, match="Nested"):
        prepare(str(tmp_path), "Task")


def test_accepts_mixed_and_provider_role_specs(tmp_path):
    request = prepare(
        str(tmp_path),
        "Task",
        agent="codex/gpt-6.1-sol:high",
        agents={
            "actor": "dsh/deepseek-v4-pro:high",
            "observer": "dsh@personal/deepseek-v4-flash:low",
        },
    )
    assert request["agents"]["actor"].startswith("dsh/")


def test_pure_dsh_does_not_require_codex_and_freezes_source(tmp_path, monkeypatch):
    def no_codex():
        raise AssertionError("A pure DSH job must not inspect Codex")

    monkeypatch.setattr("humanize_codex.jobs.select_codex", no_codex)
    from humanize_codex.jobs import FLOW

    source = tmp_path / "custom.py"
    source.write_bytes(FLOW.read_bytes())
    request = prepare(str(tmp_path), "Task", agent="dsh/deepseek-v4-pro:low", flow_file=str(source))
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(request)
    source.write_text("raise RuntimeError('Changed after launch')")
    assert (
        tmp_path / "data/runs" / state["job_id"] / "workflow.py"
    ).read_bytes() == FLOW.read_bytes()


def test_path_traversal_cannot_address_other_files(tmp_path):
    with pytest.raises(ValueError, match="job_id"):
        job_path(tmp_path, "../../config")


def test_only_one_active_job_per_workspace_and_cancellation_is_scoped(tmp_path):
    jobs = Jobs(tmp_path / "data")
    request = prepare(str(tmp_path), "Task")
    with patch("humanize_codex.jobs.subprocess.Popen") as popen:
        state = jobs.start(request)
        with pytest.raises(ValueError, match="already has an active"):
            jobs.start(request)
        assert popen.call_count == 1
    receipt = jobs.control(state["job_id"], "cancel")
    assert receipt["status"] == "queued"
    assert jobs.status(state["job_id"])["status"] == "starting"
    messages = list((tmp_path / "data/runs" / state["job_id"] / "inbox").glob("*.json"))
    assert len(messages) == 1
    assert read_json(messages[0])["kind"] == "cancel"


def test_expired_worker_is_lost_and_never_complete(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(prepare(str(tmp_path), "Task"))
    path = tmp_path / "data/runs" / state["job_id"] / "state.json"
    atomic_json(path, {**read_json(path), "heartbeat": time.time() - 61})
    assert jobs.status(state["job_id"])["status"] == "lost"
    with pytest.raises(ValueError, match="already lost"):
        jobs.control(state["job_id"], "cancel")


def test_launch_error_is_terminal_and_observable(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen", side_effect=OSError("launch failed")):
        with pytest.raises(OSError):
            jobs.start(prepare(str(tmp_path), "Task"))
    assert jobs.list()[0]["status"] == "failed"


def test_worker_lock_prevents_a_second_writer_even_without_a_heartbeat(tmp_path):
    jobs = Jobs(tmp_path / "data")
    request = prepare(str(tmp_path), "Task")
    with workspace_locked(jobs.root, request["workspace"]):
        with pytest.raises(ValueError, match="active job"):
            jobs.start(request)


def test_event_reader_ignores_a_partially_written_final_line(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(prepare(str(tmp_path), "Task"))
    path = tmp_path / "data/runs" / state["job_id"] / "events.jsonl"
    path.write_text('{"kind":"complete-line"}\n{"kind":"half')
    assert jobs.events(state["job_id"]) == [{"kind": "complete-line"}]


def test_completed_job_cannot_be_resumed(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(prepare(str(tmp_path), "Task"))
    path = tmp_path / "data/runs" / state["job_id"] / "state.json"
    atomic_json(path, {**read_json(path), "status": "complete"})
    with pytest.raises(ValueError, match="unfinished"):
        jobs.resume(state["job_id"])


def test_trace_projection_drops_model_text_and_pairs_session_spans(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(prepare(str(tmp_path), "Task"))
    path = tmp_path / "data/runs" / state["job_id"]
    lines = [
        {"at": 1.0, "kind": "session_opened", "role": "actor", "session": "s1"},
        {"at": 2.0, "kind": "begins", "role": "actor", "session": "s1", "text": "PRIVATE_OUTPUT"},
        {"at": 3.0, "kind": "notice", "text": "PRIVATE_NOTICE"},
        {"at": 4.5, "kind": "ends", "role": "actor", "session": "s1", "text": "PRIVATE_OUTPUT"},
        {"at": 5.0, "kind": "begins", "role": "reviewer", "session": "s2"},
    ]
    (path / "events.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in lines), encoding="utf-8"
    )
    trace = jobs.status(state["job_id"], include_trace=True)["trace"]
    spans = {s["role"]: s for s in trace["spans"]}
    assert spans["actor"]["start"] == 2.0
    assert spans["actor"]["end"] == 4.5
    assert spans["reviewer"]["end"] is None
    assert [f["kind"] for f in trace["facts"]] == ["session_opened"]
    assert "PRIVATE" not in json.dumps(trace)
    assert "s1" not in json.dumps(trace)


def test_normal_status_does_not_scan_transcripts_for_dashboard_trace(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(prepare(str(tmp_path), "Task"))
    with patch.object(Jobs, "trace", side_effect=AssertionError("unrequested trace scan")):
        assert "trace" not in jobs.status(state["job_id"])
        assert len(jobs.list(limit=1)) == 1
