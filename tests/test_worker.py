"""Run the actual SDK worker against scripted drivers, including control delivery."""

from unittest.mock import patch

import pytest
from hmz.sdk import Hmz, fakes

from humanize_codex.jobs import Jobs, prepare
from humanize_codex.worker import work

DONE = {"action": "complete", "notes": "Independently checked", "evidence": ["fixture verified"]}


@pytest.fixture(autouse=True)
def no_real_cli_detection(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr("humanize_codex.jobs.select_codex", lambda: Path("/bin/true"))
    monkeypatch.setattr("humanize_codex.worker.select_codex", lambda: Path("/bin/true"))


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
    if control == "cancel":
        assert result["status"] == "cancelled"
        assert not actor.prompts
    else:
        assert result["status"] == "complete", result.get("error")
        assert result["epic"]
        if control == "steer":
            assert "Check the exact first line" in actor.prompts[0]
            assert any(event["kind"] == "control_receipt" for event in jobs.events(state["job_id"]))
