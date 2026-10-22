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
    for repo, commit in [
        ("owner/repo", "main"),
        ("https://secret-token@github.com/owner/repo", "a" * 40),
    ]:
        with pytest.raises(ValueError):
            library.index("my_flow", "1.0.0", str(tmp_path), repo, commit, "my_flow")
