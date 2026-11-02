"""Validate upstream flow construction with an unlimited budget and disabled backups."""

import math

from hmz.sdk import Hmz, fakes

from humanize_codex.jobs import execution_budget


def test_real_sdk_run_construction_accepts_unlimited_worker_options(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "hmz-home"))
    run = Hmz(tmp_path).run(
        "rlar",
        "Read the fixture",
        agents={role: fakes.FakeAgentDriver("codex") for role in ("actor", "reviewer")},
        params={},
        budget=execution_budget(),
        resume=False,
        backup=[],
    )
    assert run.backup == ()
    assert run.budget.duration is None
    assert run.budget.output_tokens is None
    assert math.isinf(run.budget.cost)
    assert not run.running
