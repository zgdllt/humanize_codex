"""Frozen pre-0.5 source for compatibility regression tests only."""

from pathlib import Path

from humanize_codex.jobs import prepare as current_prepare

FLOW = Path(__file__).with_name("fixtures") / "legacy_workflow.py"


def prepare(workspace, task, *, mode="dynamic", max_rounds=6, **kwargs):
    kwargs.setdefault("flow_file", str(FLOW))
    request = current_prepare(workspace, task, **kwargs)
    request.pop("flow")
    request.update(mode=mode, max_rounds=max_rounds)
    return request
