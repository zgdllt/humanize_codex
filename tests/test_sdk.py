"""Validate the actual SDK boundary used by workers, including disabled backups."""

from hmz.sdk import Hmz, fakes

from humanize_codex.jobs import FLOW


def test_real_sdk_run_construction_accepts_worker_options(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "hmz-home"))
    run = Hmz(tmp_path).run(
        f"{FLOW}:read_only_workflow",
        "Read the fixture",
        agents={
            role: fakes.FakeAgentDriver("codex")
            for role in ("planner", "actor", "reviewer", "observer")
        },
        params={"mode": "review", "max_rounds": 1, "artifacts": str(tmp_path / "artifacts")},
        budget={"duration": 5, "output_tokens": 1000},
        resume=False,
        backup=[],
    )
    assert run.backup == ()
    assert not run.running
