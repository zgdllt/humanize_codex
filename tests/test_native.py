"""Verify native host sharing, root journals and real tmux startup without model calls."""

import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import psutil
import pytest
from hmz import daemon
from hmz.sdk import fakes

from humanize_codex.native import NativeRun, entry_file, prepare_host
from humanize_codex.store import atomic_json, workspace_locked

SOURCE = """import asyncio
from pathlib import Path
from hmz.flows import flow, AgentCollection, EnvCollection, FlowParams
class Team(AgentCollection): pass
class Envs(EnvCollection): pass
class Params(FlowParams):
    artifacts: str = ""
    guidance: str = ""
    mode: str = "review"
    max_rounds: int = 1
    delay: float = 0.1
@flow(agents=Team, envs=Envs, params=Params, resumable=True)
async def dynamic_workflow(task, *, agents, envs, params, ctx):
    ctx.state["count"] = ctx.state.get("count", 0) + 1
    await asyncio.sleep(params.delay)
    return {"status": "complete", "action": "complete",
            "evidence": ["Python calculation checked"], "count": ctx.state["count"]}
@flow(agents=Team, envs=Envs, params=Params, resumable=True)
async def read_only_workflow(task, *, agents, envs, params, ctx):
    return await dynamic_workflow.fn(task, agents=agents, envs=envs, params=params, ctx=ctx)
"""


@pytest.mark.native
def test_native_root_resume_keeps_state_with_new_artifacts_and_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", __import__("os").environ["PATH"])
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "0")
    journal = tmp_path / "journal.jsonl"
    outputs = []
    for number in (1, 2):
        path = tmp_path / f"job{number}"
        path.mkdir()
        source = path / "workflow.py"
        source.write_text(SOURCE)
        entry = entry_file(path, f"{source}:read_only_workflow")
        outputs.append(
            asyncio.run(
                fakes.run_fake(
                    f"{entry}:read_only_workflow",
                    "Keep the same goal",
                    journal=journal,
                    resume=number == 2,
                    params={"artifacts": str(path), "guidance": str(number)},
                )
            )
        )
    assert [output["count"] for output in outputs] == [1, 2]


@pytest.mark.native
@pytest.mark.parametrize("cancel", [False, True])
def test_native_run_is_readable_by_another_frontend(tmp_path, monkeypatch, cancel):
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "home"))
    path = tmp_path / "job"
    path.mkdir()
    source = path / "workflow.py"
    source.write_text(SOURCE)
    native = prepare_host(str(tmp_path), uuid.uuid4().hex)
    atomic_json(path / "request.json", {"native": native})
    host = daemon.running(tmp_path, slot=native["slot"])
    observer = host.link(kind="tui", name="Test user")
    seen = []
    observer.heard(seen.append)
    run = NativeRun(
        str(tmp_path),
        path,
        f"{source}:read_only_workflow",
        "Native visibility",
        params={"delay": 30 if cancel else 0},
        agents={},
        backup=[],
        budget={"duration": 10, "output_tokens": 100},
    )
    try:
        run.start()
        if cancel:
            run.stop()
            run.stop()  # Match the worker's repeated cancellation checks.
        assert run.wait(5)
        assert run.native_finished
        assert run.epic and (run.epic / "epic.jsonl").is_file()
        if cancel:
            assert isinstance(run.raised, asyncio.CancelledError)
        else:
            assert run.raised is None
            assert run.result["count"] == 1
        assert observer.asked({"do": "status"})["run"] == run.number
        deadline = time.monotonic() + 2
        while not any(message.get("type") == "ended" for message in seen):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert any(message.get("type") == "started" for message in seen)
    finally:
        run.detach()
        observer.close()
        host.stop()


@pytest.mark.native
@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux is not installed on this test host")
def test_real_tmux_tui_and_flow_share_host_and_reopen_does_not_rerun(tmp_path, monkeypatch):
    from humanize_codex import viewer
    from humanize_codex.jobs import Jobs, prepare

    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "hmz-home"))
    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(tmp_path / "plugin data"))
    monkeypatch.setenv("HUMANIZE_NATIVE_TEST", "inherited-by-flow-window")
    monkeypatch.setattr(viewer, "mode", lambda: "tmux")
    source = tmp_path / "no_model.py"
    source.write_text(
        SOURCE.replace(
            'ctx.state["count"] =',
            'assert __import__("os").environ.get("HUMANIZE_NATIVE_TEST") '
            '== "inherited-by-flow-window"\n    ctx.state["count"] =',
        )
    )
    sentinel = daemon.host(tmp_path)
    sentinel_link = sentinel.link(kind="sdk", name="Existing user host")
    jobs = Jobs()
    state = jobs.start(
        prepare(
            str(tmp_path),
            "Run in tmux",
            flow_file=str(source),
            read_only=True,
            retain_flow=False,
            duration_seconds=15,
        )
    )
    view = state["viewer"]
    try:
        assert view["kind"] == "tmux"
        assert view["session"] in view["attach_command"]
        assert state["native"]["pid"] != sentinel.pid
        state = jobs.wait(state["job_id"], 15)
        assert state["status"] == "complete", state.get("error")
        assert state["result"]["count"] == 1
        assert psutil.pid_exists(sentinel.pid)
        assert psutil.pid_exists(state["native"]["pid"])
        pane = subprocess.check_output(
            [view["tmux"], "display-message", "-p", "-t", f"{view['session']}:tui", "#{pane_dead}"],
            text=True,
        )
        assert pane.strip() == "0"
        path = Path(state["artifacts"])
        before = (path / "flow-result.json").read_bytes()
        assert (path / "launch-env.json").stat().st_mode & 0o077 == 0
        viewer.reopen(path, state["request"])
        assert (path / "flow-result.json").read_bytes() == before
    finally:
        subprocess.run([view["tmux"], "kill-session", "-t", view["session"]], check=False)
        own = daemon.running(tmp_path, slot=state["native"]["slot"])
        if own:
            own.stop()
        sentinel_link.close()
        sentinel.stop()


@pytest.mark.native
def test_hard_budget_cleans_only_job_host_not_the_shared_router(tmp_path, monkeypatch):
    import sys

    from humanize_codex import viewer
    from humanize_codex.jobs import Jobs, prepare

    monkeypatch.setenv("HUMANIZE_CODEX_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HUMANIZE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(viewer, "describe", lambda workspace, job_id: {"kind": "test"})

    def launch(path, request, env):
        with (path / "worker.log").open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "humanize_codex.cli", "worker", path.name],
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        return {"kind": "test", "pid": process.pid}

    monkeypatch.setattr(viewer, "launch", launch)
    sentinel = daemon.host(tmp_path)
    sentinel_link = sentinel.link(kind="sdk", name="Unrelated existing host")
    source = tmp_path / "blocking.py"
    source.write_text(
        SOURCE.replace("    await asyncio.sleep(params.delay)", "    while True: pass")
    )
    jobs = Jobs()
    state = jobs.start(
        prepare(
            str(tmp_path),
            "Blocking Python",
            flow_file=str(source),
            duration_seconds=1,
            retain_flow=False,
        )
    )
    try:
        state = jobs.wait(state["job_id"], 10)
        assert state["status"] == "budget_exceeded", state
        assert not psutil.pid_exists(state["native"]["pid"])
        assert psutil.pid_exists(sentinel.pid)
        assert sentinel_link.asked({"do": "status"})["ok"]
        with workspace_locked(jobs.root, str(tmp_path)):
            pass
    finally:
        own = daemon.running(tmp_path, slot=state["native"]["slot"])
        if own:
            own.kill(seconds=1)
        sentinel_link.close()
        sentinel.stop()


@pytest.mark.native
def test_ssh_uses_tmux_even_with_a_desktop_app(monkeypatch):
    from humanize_codex import viewer

    monkeypatch.setenv("SSH_CONNECTION", "test-ssh-connection")
    monkeypatch.setattr(viewer, "app_path", lambda: Path("/Applications/humanize.app"))
    assert viewer.mode() == "tmux"


@pytest.mark.native
@pytest.mark.parametrize("gui", [False, True])
def test_piped_mcp_detects_gui_not_the_bundled_cli_path(monkeypatch, gui):
    from types import SimpleNamespace

    from humanize_codex import viewer

    for key in ("SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT", "TMUX", "TERM_PROGRAM"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(viewer.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(viewer.sys.stdout, "isatty", lambda: False)
    paths = [
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
    ]
    paths += ["/Applications/ChatGPT.app/Contents/MacOS/ChatGPT"] if gui else ["/bin/zsh"]
    monkeypatch.setattr(
        viewer.psutil,
        "Process",
        lambda: SimpleNamespace(
            parents=lambda: [SimpleNamespace(exe=lambda p=path: p) for path in paths]
        ),
    )
    monkeypatch.setattr(viewer, "app_path", lambda: Path("/Applications/humanize.app"))
    assert viewer.mode() == ("app" if gui else "tmux")
