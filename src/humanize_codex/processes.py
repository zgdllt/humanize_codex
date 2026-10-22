"""Track owned descendants across setsid and reparenting, with PID reuse protection."""

from __future__ import annotations

import subprocess
import time

import psutil


class ProcessTree:
    def __init__(self, pid: int):
        try:
            self.owned = {pid: psutil.Process(pid)}
        except psutil.NoSuchProcess:
            self.owned = {}

    def capture(self) -> None:
        for process in list(self.owned.values()):
            try:
                # psutil Process identities include creation time; signals check PID reuse.
                if process.is_running():
                    for child in process.children(recursive=True):
                        previous = self.owned.get(child.pid)
                        if previous is None or not previous.is_running():
                            self.owned[child.pid] = child
            except psutil.NoSuchProcess:
                pass

    def close(self) -> None:
        # Stop spawning first, then discover descendants that appeared during the scan.
        suspended = set()
        while True:
            self.capture()
            pending = [p for p in self.owned.values() if p.pid not in suspended]
            if not pending:
                break
            for process in pending:
                try:
                    process.suspend()
                except psutil.NoSuchProcess:
                    pass
                suspended.add(process.pid)
        for process in reversed(list(self.owned.values())):
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        # Zombies cannot write; a still-running process must retain workspace ownership.
        while True:
            alive = []
            for process in self.owned.values():
                try:
                    if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                        alive.append(process)
                except psutil.NoSuchProcess:
                    pass
            if not alive:
                return
            time.sleep(0.05)


def bounded_python(args: list[str], *, cwd, env, timeout: float) -> None:
    """Bound trusted inspection/fake validation and clean up their detached descendants."""
    with subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        tree = ProcessTree(process.pid)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                tree.capture()
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(args, timeout)
                time.sleep(0.05)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, args)
        finally:
            tree.close()
