"""Exercise evidence-gated retention and real upstream Flowverse installation."""

import asyncio
import json
import shutil
import subprocess
import time

import pytest
from hmz.sdk import Hmz, fakes

from humanize_codex.jobs import FLOW, Jobs, prepare
from humanize_codex.library import Library
from humanize_codex.store import atomic_json


def promote(library, name):
    from humanize_codex.custom import validate_flow

    agents = {
        "planner": {"steps": ["Read"], "acceptance": ["Verified"], "rationale": "Small"},
        "actor": "Read fixture",
        "observer": {"summary": "Reading", "next_step": "Review"},
    }
    cases = [
        {
            "agents": {
                **agents,
                "reviewer": {"action": verdict, "notes": "checked", "evidence": ["actual fixture"]},
            },
            "params": {"mode": "review", "max_rounds": 1},
            "expected": {"status": verdict},
        }
        for verdict in ("complete", "blocked")
    ]
    receipt = validate_flow(library.root, str(library.source(name)), "read_only_workflow", cases)
    assert receipt["status"] == "passed", receipt
    return library.curate(
        name,
        "promote",
        "Inspected applicability and stopping behavior",
        ["Read-only fact checks"],
        ["Do not use for workspace edits"],
        receipt["validation_id"],
    )


@pytest.fixture
def completed(tmp_path):
    root = tmp_path / "data"
    job_id = "a" * 32
    path = root / "runs" / job_id
    path.mkdir(parents=True)
    request = prepare(
        str(tmp_path),
        "PRIVATE_TASK_SENTINEL",
        mode="review",
        agent="codex/fake:low",
        read_only=True,
        max_rounds=1,
    )
    atomic_json(path / "request.json", request)
    atomic_json(
        path / "state.json",
        {
            "job_id": job_id,
            "status": "complete",
            "heartbeat": time.time(),
            "created": time.time(),
            "result": {"action": "complete", "round": 1, "evidence": ["PRIVATE_REVIEW_SENTINEL"]},
            "usage": {"output_tokens": 100},
        },
    )
    shutil.copy2(FLOW, path / "workflow.py")
    return root, job_id, path


def test_retain_is_idempotent_and_never_copies_task_or_review(completed):
    root, job_id, path = completed
    library = Library(root)
    first = library.retain(job_id)
    second = library.retain(job_id)
    assert first["name"] == second["name"]
    assert second["successes"] == 1
    for file in (root / "library").rglob("*"):
        if file.is_file():
            assert "PRIVATE_TASK_SENTINEL" not in file.read_text()
            assert "PRIVATE_REVIEW_SENTINEL" not in file.read_text()
    assert library.source(first["name"]).read_bytes() == (path / "workflow.py").read_bytes()


@pytest.mark.parametrize(
    "status,evidence", [("running", ["x"]), ("blocked", ["x"]), ("complete", [])]
)
def test_unreviewed_or_unfinished_runs_are_not_retained(completed, status, evidence):
    root, job_id, path = completed
    atomic_json(
        path / "state.json",
        {"status": status, "result": {"action": "complete", "evidence": evidence}},
    )
    with pytest.raises(ValueError, match="independent review"):
        Library(root).retain(job_id)


def test_named_flow_is_immutable_and_tampering_is_detected(completed):
    root, job_id, path = completed
    library = Library(root)
    library.retain(job_id, "my_flow")
    with (path / "workflow.py").open("a") as stream:
        stream.write("\n# changed implementation\n")
    with pytest.raises(ValueError, match="another flow"):
        library.retain(job_id, "my_flow")
    with library.source("my_flow").open("a") as stream:
        stream.write("# modified retained code\n")
    with pytest.raises(ValueError, match="changed"):
        library.source("my_flow")


def test_reuse_gets_saved_roles_permissions_and_original_code(completed, monkeypatch, tmp_path):
    root, job_id, path = completed
    library = Library(root)
    library.retain(job_id, "my_flow")
    promote(library, "my_flow")
    captured = {}

    def capture(self, request):
        captured.update(request)
        return request

    monkeypatch.setattr(Jobs, "start", capture)
    Jobs(root).reuse("my_flow", str(tmp_path), "NEW_TASK", duration_seconds=10)
    assert captured["read_only"]
    assert captured["mode"] == "review"
    assert captured["agents"]["actor"] == "codex/fake:low"
    assert captured["budget"]["duration"] == 10
    assert captured["task"] == "NEW_TASK"
    assert open(captured["flow_file"], "rb").read() == (path / "workflow.py").read_bytes()


def test_export_and_real_upstream_index_install(completed, tmp_path, monkeypatch):
    root, job_id, _ = completed
    library = Library(root)
    library.retain(job_id, "my_flow")
    promote(library, "my_flow")
    source, index = tmp_path / "source", tmp_path / "index"
    source.mkdir()
    index.mkdir()
    exported = library.export("my_flow", str(source), "1.0.0")
    for file in source.rglob("*"):
        if file.is_file():
            text = file.read_text()
            assert "PRIVATE_TASK_SENTINEL" not in text
            assert "PRIVATE_REVIEW_SENTINEL" not in text
            assert job_id not in text
    assert json.loads((source / exported["subdir"] / "flow.json").read_text())["successes"] == 1
    with pytest.raises(ValueError, match="exists"):
        library.export("my_flow", str(source), "1.0.0")

    def git(where, *args):
        return subprocess.check_output(["git", "-C", str(where), *args], text=True).strip()

    git(source, "init", "-q", "-b", "main")
    git(source, "add", ".")
    git(
        source,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "test flow",
    )
    commit = git(source, "rev-parse", "HEAD")
    release = library.index(
        "my_flow", "1.0.0", str(index), source.as_uri(), commit, exported["subdir"], "main"
    )
    assert release["manifest"]["commit"] == commit
    git(index, "init", "-q", "-b", "main")
    git(index, "add", ".")
    git(
        index,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "test index",
    )
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "hmz-home"))
    verses = Hmz(tmp_path).verses
    verses.add(index.as_uri(), "testing")
    installed = list(verses.install("@testing/my_flow"))
    assert installed[0].version == "1.0.0"
    # Exercise the installed named entry, not merely a YAML/schema round trip.
    result = asyncio.run(
        fakes.run_fake(
            str(installed[0].at),
            "Read a fixture",
            agents={
                "planner": fakes.FakeAgentDriver("codex"),
                "actor": fakes.FakeAgentDriver("codex", reply="Read fixture"),
                "observer": fakes.FakeAgentDriver(
                    "codex", reply={"summary": "Checking", "next_step": "Review"}
                ),
                "reviewer": fakes.FakeAgentDriver(
                    "codex",
                    reply={
                        "action": "complete",
                        "notes": "checked",
                        "evidence": ["fixture checked"],
                    },
                ),
            },
            params={"mode": "review", "max_rounds": 1},
        )
    )
    assert result["status"] == "complete"


def test_index_rejects_unpinned_commit_and_secret_urls(completed, tmp_path):
    root, job_id, _ = completed
    library = Library(root)
    library.retain(job_id, "my_flow")
    promote(library, "my_flow")
    for repo, commit in [
        ("owner/repo", "main"),
        ("https://secret-token@github.com/owner/repo", "a" * 40),
    ]:
        with pytest.raises(ValueError):
            library.index("my_flow", "1.0.0", str(tmp_path), repo, commit, "my_flow")


def test_success_is_candidate_and_default_reuse_export_require_curation(completed, tmp_path):
    root, job_id, _ = completed
    library = Library(root)
    profile = library.retain(job_id, "candidate")
    assert profile["curation"]["status"] == "candidate"
    with pytest.raises(ValueError, match="candidate"):
        Jobs(root).reuse("candidate", str(tmp_path), "New task")
    with pytest.raises(ValueError, match="curated"):
        library.export("candidate", str(tmp_path))
    with pytest.raises(ValueError, match="receipt"):
        library.curate("candidate", "promote", "Looks useful", ["read"], ["write"])


def test_rejected_flow_is_not_reused_even_with_trial_flag(completed, tmp_path):
    root, job_id, _ = completed
    library = Library(root)
    library.retain(job_id, "bad_flow")
    library.curate("bad_flow", "reject", "Task-bound and not reusable", [], [])
    with pytest.raises(ValueError, match="rejected"):
        Jobs(root).reuse("bad_flow", str(tmp_path), "Task", allow_candidate=True)


def test_runtime_inputs_are_not_saved_in_custom_recipe(completed):
    root, job_id, path = completed
    from humanize_codex.store import read_json

    request = read_json(path / "request.json")
    request.update(entrypoint="read_only_workflow", flow_params={"guidance": "PRIVATE_INPUT"})
    atomic_json(path / "request.json", request)
    profile = Library(root).retain(job_id)
    assert "PRIVATE_INPUT" not in json.dumps(profile)


@pytest.mark.parametrize("mismatch", ["duplicate", "source", "entry"])
def test_promotion_requires_distinct_cases_for_exact_code_and_entry(completed, tmp_path, mismatch):
    from humanize_codex.custom import validate_flow

    root, job_id, _ = completed
    library = Library(root)
    library.retain(job_id, "checks")
    source = library.source("checks")
    if mismatch == "source":
        other = tmp_path / "changed.py"
        other.write_bytes(source.read_bytes() + b"\n# Different tested source\n")
        source = other
    entry = "dynamic_workflow" if mismatch == "entry" else "read_only_workflow"
    cases = [
        {
            "agents": {
                "planner": {"steps": ["read"], "acceptance": ["verified"], "rationale": "check"},
                "actor": "Checked",
                "observer": {"summary": "Checking", "next_step": "Review"},
                "reviewer": {"action": action, "notes": "Checked", "evidence": ["fixture"]},
            },
            "params": {"mode": "review", "max_rounds": 1},
            "expected": {"status": action},
        }
        for action in ("complete", "complete" if mismatch == "duplicate" else "blocked")
    ]
    receipt = validate_flow(root, str(source), entry, cases)
    assert receipt["status"] == "passed", receipt
    with pytest.raises(ValueError, match="exact code and entry"):
        library.curate(
            "checks", "promote", "Assessed", ["read"], ["write"], receipt["validation_id"]
        )


def test_legacy_flow_defaults_to_candidate_and_preserves_fingerprint(completed):
    from humanize_codex.store import read_json

    root, job_id, _ = completed
    library = Library(root)
    original = library.retain(job_id, "legacy")
    file = root / "library/legacy/flow.json"
    old = read_json(file)
    old.pop("curation")
    atomic_json(file, old)
    assert library.get("legacy")["curation"]["status"] == "candidate"
    assert library.retain(job_id, "legacy")["fingerprint"] == original["fingerprint"]


def test_custom_reuse_preserves_manager_backend_overrides(completed, tmp_path, monkeypatch):
    from humanize_codex.store import read_json

    root, job_id, path = completed
    request = read_json(path / "request.json")
    request["entrypoint"] = "read_only_workflow"
    state = read_json(path / "state.json")
    state["agents"] = {
        role: "dsh/fake:low"
        for role in (
            "planner",
            "actor",
            "reviewer",
            "observer",
            "humanize_verifier",
            "humanize_observer",
        )
    }
    atomic_json(path / "request.json", request)
    atomic_json(path / "state.json", state)
    Library(root).retain(job_id, "custom")
    monkeypatch.setattr(Jobs, "start", lambda self, request: request)
    reused = Jobs(root).reuse("custom", str(tmp_path), "New task", allow_candidate=True)
    assert reused["agents"]["humanize_observer"] == "dsh/fake:low"
    assert reused["agents"]["humanize_verifier"] == "dsh/fake:low"
