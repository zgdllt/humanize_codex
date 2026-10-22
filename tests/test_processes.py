"""Cleanup deadlines must report survivors and reap ordinary timed-out children."""

import subprocess
import sys
import time
from unittest.mock import Mock

import psutil
import pytest

from humanize_codex import processes


def test_close_timeout_names_survivors_and_allows_retry(monkeypatch):
    process = Mock(pid=12345)
    process.is_running.return_value = True
    process.status.return_value = psutil.STATUS_STOPPED
    process.children.return_value = []
    monkeypatch.setattr(processes.psutil, "Process", lambda pid: process)
    tree = processes.ProcessTree(process.pid)

    with pytest.raises(TimeoutError, match="survived SIGKILL.*12345") as error:
        tree.close(timeout=0)
    assert "workspace" not in str(error.value)
    # A zombie cannot write, even before its parent has reaped it.
    process.status.return_value = psutil.STATUS_ZOMBIE
    tree.close(timeout=0)


@pytest.mark.parametrize("exit_code", [0, 7, None], ids=["normal", "failed", "timeout"])
def test_bounded_python_reaps_child_and_stops_detached_descendant(tmp_path, monkeypatch, exit_code):
    pid_file = tmp_path / "descendant.pid"
    script = (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "start_new_session=True)\n"
        f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        f"time.sleep({60 if exit_code is None else 0.4})\n"
        f"sys.exit({exit_code!r})\n"
    )
    popen = subprocess.Popen
    spawned = []

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(processes.subprocess, "Popen", start)
    started = time.monotonic()
    descendant = None
    try:
        args = [sys.executable, "-c", script]
        if exit_code is None:
            with pytest.raises(subprocess.TimeoutExpired):
                processes.bounded_python(args, cwd=tmp_path, env=None, timeout=0.8)
        elif exit_code:
            with pytest.raises(subprocess.CalledProcessError) as error:
                processes.bounded_python(args, cwd=tmp_path, env=None, timeout=3)
            assert error.value.returncode == exit_code
        else:
            processes.bounded_python(args, cwd=tmp_path, env=None, timeout=3)
        assert time.monotonic() - started < 5
        assert len(spawned) == 1
        assert spawned[0].returncode is not None
        assert not psutil.pid_exists(spawned[0].pid)
        try:
            descendant = psutil.Process(int(pid_file.read_text()))
        except psutil.NoSuchProcess:
            pass
        else:
            assert not descendant.is_running() or descendant.status() == psutil.STATUS_ZOMBIE
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        if descendant is None and pid_file.exists():
            try:
                descendant = psutil.Process(int(pid_file.read_text()))
            except psutil.NoSuchProcess:
                pass
        if descendant is not None:
            try:
                descendant.kill()
            except psutil.NoSuchProcess:
                pass


def test_bounded_python_limits_reap_wait_when_cleanup_fails(tmp_path, monkeypatch):
    args = [sys.executable, "-c", "import time; time.sleep(60)"]
    process = Mock(pid=12345)
    process.poll.return_value = None
    process.wait.side_effect = subprocess.TimeoutExpired(args, 5)
    tree = Mock()
    tree.close.side_effect = TimeoutError("injected unkillable process")
    monkeypatch.setattr(processes.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(processes, "ProcessTree", lambda pid: tree)

    with pytest.raises(subprocess.TimeoutExpired) as error:
        processes.bounded_python(args, cwd=tmp_path, env=None, timeout=0)
    assert error.value.timeout == 5
    process.wait.assert_called_once_with(timeout=5)
