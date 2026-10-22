"""Exercise real Humanize control flow without model calls or user filesystem changes."""

import asyncio
import json

import pytest
from hmz.flows import OutputSchemaError
from hmz.sdk import fakes

from humanize_codex.jobs import FLOW

PLAN = {
    "steps": ["Implement then verify"],
    "acceptance": ["The real check passes"],
    "rationale": "Minimal implementation",
}
REPORT = {"summary": "正在执行已授权的工作", "next_step": "等待独立审查"}


def verdict(action, notes="Concrete feedback"):
    return {"action": action, "notes": notes, "evidence": ["test_feature.py:12; check exit 0"]}


def run(tmp_path, actor, reviewer, planner=None, **params):
    observer = params.pop("observer", REPORT)
    return asyncio.run(
        fakes.run_fake(
            f"{FLOW}:dynamic_workflow",
            "Implement the requested feature",
            agents={
                "actor": actor,
                "reviewer": reviewer,
                "planner": planner or PLAN,
                "observer": observer,
            },
            params={"artifacts": str(tmp_path), **params},
        )
    )


def test_adapts_plan_keeps_actor_and_refreshes_reviews(tmp_path):
    actor = fakes.FakeAgentDriver("codex", reply="Implemented and checked")
    reviewer = fakes.FakeAgentDriver(
        "codex",
        reply=[
            verdict("replan", "Change the approach"),
            verdict("fix", "Fix the boundary"),
            verdict("complete", "Verified the real implementation"),
        ],
    )
    planner = fakes.FakeAgentDriver("codex", reply=PLAN)
    result = run(tmp_path, actor, reviewer, planner)
    assert result["status"] == "complete"
    assert result["round"] == 3
    assert len(actor.sessions) == 1
    assert len(reviewer.sessions) == 3
    assert len(planner.sessions) == 2
    assert "Fix the boundary" in actor.prompts[-1]
    assert json.loads((tmp_path / "review-3.json").read_text())["action"] == "complete"


def test_required_human_input_is_blocked_not_completed(tmp_path):
    result = run(tmp_path, "Need an unprovided decision", verdict("blocked", "Need user input"))
    assert result["status"] == "blocked"
    assert result["round"] == 1


def test_round_limit_does_not_claim_completion(tmp_path):
    result = run(tmp_path, "Not complete", verdict("fix"), max_rounds=2)
    assert result["status"] == "round_limit"
    assert result["round"] == 2
    assert result["action"] == "fix"


def test_empty_review_evidence_is_rejected(tmp_path):
    with pytest.raises(OutputSchemaError):
        run(tmp_path, "Done", {"action": "complete", "notes": "Trust me", "evidence": []})


def test_review_mode_skips_unnecessary_initial_planning(tmp_path):
    planner = fakes.FakeAgentDriver("codex", reply=PLAN)
    result = run(tmp_path, "Done", verdict("complete"), planner, mode="review")
    assert result["status"] == "complete"
    assert not planner.sessions


def test_read_only_variant_runs_on_real_engine(tmp_path):
    result = asyncio.run(
        fakes.run_fake(
            f"{FLOW}:read_only_workflow",
            "Explain this repository",
            agents={
                "planner": PLAN,
                "actor": "Explanation",
                "reviewer": verdict("complete"),
                "observer": REPORT,
            },
            params={"artifacts": str(tmp_path)},
        )
    )
    assert result["status"] == "complete"


def test_journal_resume_preserves_progress_and_original_goal(tmp_path):
    journal = tmp_path / "journal.jsonl"
    args = {
        "flow": f"{FLOW}:dynamic_workflow",
        "task": "Original goal",
        "journal": journal,
        "params": {"max_rounds": 1},
    }
    first = asyncio.run(
        fakes.run_fake(
            **args,
            agents={
                "planner": PLAN,
                "actor": "Attempt",
                "reviewer": verdict("fix"),
                "observer": REPORT,
            },
        )
    )
    actor = fakes.FakeAgentDriver("codex", reply="Now verified")
    planner = fakes.FakeAgentDriver("codex", reply=PLAN)
    second = asyncio.run(
        fakes.run_fake(
            **args,
            resume=True,
            agents={
                "planner": planner,
                "actor": actor,
                "reviewer": verdict("complete"),
                "observer": REPORT,
            },
        )
    )
    assert first["status"] == "round_limit"
    assert second["status"] == "complete" and second["round"] == 2
    assert not planner.sessions
    assert "Concrete feedback" in actor.prompts[0]
    with pytest.raises(ValueError, match="different task"):
        asyncio.run(
            fakes.run_fake(
                **{**args, "task": "Changed goal"},
                resume=True,
                agents={
                    "planner": PLAN,
                    "actor": "x",
                    "reviewer": verdict("complete"),
                    "observer": REPORT,
                },
            )
        )
