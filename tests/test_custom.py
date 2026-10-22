"""Exercise arbitrary flow shapes with the real SDK, without online models."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from hmz.sdk import Hmz, fakes

from humanize_codex.custom import inspect_flow, make_envelope, validate_flow
from humanize_codex.jobs import Jobs, prepare
from humanize_codex.store import atomic_json, read_json
from humanize_codex.worker import work

EXAMPLE = Path(__file__).resolve().parent.parent / "examples/control_structures.py"
DONE = {"action": "complete", "notes": "Checked actual output", "evidence": ["Two results checked"]}


def drivers(review=DONE):
    return {
        "first": fakes.FakeAgentDriver("codex", reply="one"),
        "second": fakes.FakeAgentDriver("codex", reply="two"),
        "humanize_verifier": fakes.FakeAgentDriver("codex", reply=review),
        "humanize_observer": fakes.FakeAgentDriver(
            "codex", reply={"summary": "Checking active roles", "next_step": "Verify"}
        ),
    }


@pytest.mark.parametrize(
    "entry,params,expected",
    [
        ("sequence_flow", {}, {"shape": "sequence", "answers": ["one", "two"]}),
        ("loop_flow", {"iterations": 3}, {"shape": "loop", "iterations": 3}),
        ("branch_flow", {}, {"shape": "branch", "selected": "first"}),
        ("branch_flow", {"alternate": True}, {"shape": "branch", "selected": "second"}),
        ("parallel_flow", {}, {"shape": "parallel", "answers": ["one", "two"]}),
    ],
)
def test_arbitrary_shapes_under_managed_verification(tmp_path, entry, params, expected):
    (tmp_path / "workflow.py").write_bytes(EXAMPLE.read_bytes())
    wrapper, info = make_envelope(tmp_path, entry, True)
    assert entry.split("_")[0] in info["structures"]
    assert {role["name"] for role in info["roles"]} == {"first", "second"}
    result = asyncio.run(
        fakes.run_fake(
            f"{wrapper}:managed",
            "Inspect fixture",
            agents=drivers(),
            params={"inputs": params, "artifacts": str(tmp_path)},
        )
    )
    assert result["status"] == "complete"
    assert all(result["flow_result"][key] == value for key, value in expected.items())
    assert read_json(tmp_path / "report.json")["status"] == "ready"


def test_parallel_roles_really_overlap_instead_of_serial_execution(tmp_path):
    async def exercise():
        started = set()
        both = asyncio.Event()

        def reply(role):
            async def answer(*args, **kwargs):
                started.add(role)
                if len(started) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), timeout=2)
                return role

            return answer

        agents = {
            role: fakes.FakeAgentDriver("codex", reply=reply(role)) for role in ("first", "second")
        }
        result = await fakes.run_fake(f"{EXAMPLE}:parallel_flow", "Check", agents=agents)
        assert result["answers"] == ["first", "second"]

    asyncio.run(exercise())


def test_managed_result_requires_independent_acceptance(tmp_path):
    (tmp_path / "workflow.py").write_bytes(EXAMPLE.read_bytes())
    wrapper, _ = make_envelope(tmp_path, "sequence_flow", True)
    result = asyncio.run(
        fakes.run_fake(
            f"{wrapper}:managed",
            "Inspect fixture",
            agents=drivers(
                {
                    "action": "fix",
                    "notes": "Missing evidence",
                    "evidence": ["Output omitted a required check"],
                }
            ),
            params={"artifacts": str(tmp_path)},
        )
    )
    assert result["status"] == "needs_work"


def test_reserved_environment_and_writer_role_are_rejected(tmp_path):
    source = tmp_path / "workflow.py"
    source.write_text(
        EXAMPLE.read_text().replace("workspace: LocalEnv", "humanize_workspace: LocalEnv")
    )
    with pytest.raises(ValueError, match="Reserved manager environment"):
        inspect_flow(str(source), "sequence_flow", str(tmp_path))
    other = tmp_path / "writer"
    other.mkdir()
    (other / "workflow.py").write_text(
        EXAMPLE.read_text().replace("PermissionKind.READ", "PermissionKind.ALL")
    )
    with pytest.raises(ValueError, match="read_only"):
        make_envelope(other, "sequence_flow", True)


def test_nonresumable_custom_job_cannot_repeat_side_effects(tmp_path):
    jobs = Jobs(tmp_path / "data")
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(
            prepare(str(tmp_path), "Check", flow_file=str(EXAMPLE), entrypoint="sequence_flow")
        )
    file = jobs.root / "runs" / state["job_id"] / "state.json"
    atomic_json(
        file,
        {**read_json(file), "status": "blocked", "epic": "journal", "flow": {"resumable": False}},
    )
    with pytest.raises(ValueError, match="does not support resume"):
        jobs.resume(state["job_id"])


def test_fake_validation_runs_both_branches_and_checks_expected_output(tmp_path):
    receipt = validate_flow(
        tmp_path,
        str(EXAMPLE),
        "branch_flow",
        [
            {"agents": {"first": "one", "second": "two"}, "expected": {"selected": "first"}},
            {
                "agents": {"first": "one", "second": "two"},
                "params": {"alternate": True},
                "expected": {"selected": "second"},
            },
        ],
    )
    assert receipt["status"] == "passed", receipt
    assert len({case["scenario"] for case in receipt["cases"]}) == 2
    bad = validate_flow(
        tmp_path,
        str(EXAMPLE),
        "branch_flow",
        [
            {"agents": {"first": "one"}, "expected": {"selected": "second"}},
        ],
    )
    assert bad["status"] == "failed"


def test_worker_resolves_custom_roles_and_retains_only_candidate(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(data))
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "hmz"))
    monkeypatch.setattr("humanize_codex.worker.select_codex", lambda: Path("/bin/true"))

    class Runtime:
        def __init__(self, workspace=None):
            self.runtime = Hmz(workspace)
            self.flows = self.runtime.flows

        def run(self, *args, **kwargs):
            assert set(kwargs["agents"]) == set(drivers())
            kwargs["agents"] = drivers()
            return self.runtime.run(*args, **kwargs)

    jobs = Jobs(data)
    with patch("humanize_codex.jobs.subprocess.Popen"):
        state = jobs.start(
            prepare(
                str(tmp_path),
                "Inspect fixture",
                agent="codex/fake:low",
                flow_file=str(EXAMPLE),
                entrypoint="parallel_flow",
                read_only=True,
            )
        )
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "0")
    monkeypatch.setenv("PATH", __import__("os").environ["PATH"])
    with patch("hmz.sdk.Hmz", Runtime), patch("humanize_codex.worker.signal.signal"):
        work(state["job_id"])
    actual = jobs.status(state["job_id"])
    assert actual["status"] == "complete", actual.get("error")
    assert actual["retention_class"] == "candidate"
    assert actual["flow"]["structures"] == ["sequence", "parallel"]
    assert not actual["active_agents"]
