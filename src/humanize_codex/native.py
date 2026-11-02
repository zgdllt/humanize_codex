"""Run through Humanize's native host so its app and TUI see the actual workflow."""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import psutil
from hmz import daemon
from hmz.flows import BudgetExceeded, Usage
from hmz.runtime import Refused
from hmz.sdk import Hmz

from .store import read_json


def prepare_host(workspace: str, job_id: str) -> dict:
    # Start the shared router before the supervised worker exists. It belongs to the user.
    slot = f"chat:{job_id}"
    host = daemon.host(workspace, slot=slot)
    return {"slot": slot, "pid": host.pid, "created": psutil.Process(host.pid).create_time()}


def owned_host(workspace: str, native: dict):
    host = daemon.running(workspace, slot=native["slot"])
    try:
        if host is not None and host.pid == native["pid"]:
            if psutil.Process(host.pid).create_time() == native["created"]:
                return host
    except psutil.NoSuchProcess:
        pass
    return None


def prepare_process(artifacts: str) -> None:
    from .compat import guard_codex_startup

    os.environ["HUMANIZE_CODEX_CHILD"] = "1"
    directory = Path(artifacts) / "tool-bin"
    if (directory / "codex").exists():
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    guard_codex_startup()


def entry_file(path: Path, source: str) -> Path:
    """The native Host omits return values from its wire protocol; persist one privately."""
    target = path / "native-entry.py"
    target.write_text(
        "from pathlib import Path\n"
        "from hmz.flows import flow, load\n"
        "from hmz.sdk import Hmz\n"
        "from humanize_codex.native import prepare_process\n"
        "from humanize_codex.store import atomic_json\n"
        f"prepare_process({str(path)!r})\n"
        f"target = load({source!r})\n"
        f"declared = Hmz().flows.declared({source!r})\n"
        f"@flow(name={source.rsplit(':', 1)[-1]!r}, "
        "agents=target.expected_agents, envs=target.expected_envs, "
        "params=target.expected_params, resumable=declared.resumable)\n"
        "async def codex_workflow(task, *, agents, envs, params, ctx):\n"
        # FlowImpl.fn forwards the validated root context unchanged. A nested
        # target(...) call would reset its journal when a resumed job's artifacts move.
        "    value = await target.fn(task, agents=agents, envs=envs, params=params, ctx=ctx)\n"
        f"    atomic_json(Path({str(path / 'flow-result.json')!r}), {{'value': value}})\n"
        "    return value\n",
        encoding="utf-8",
    )
    return target


class NativeSession(str):
    def __new__(cls, name, link):
        session = super().__new__(cls, name)
        session.link = link
        return session

    def interject(self, text):
        self.link.say(text, to=str(self))


class NativeRun:
    """Small adapter preserving the worker's callbacks, outcome and control contracts."""

    def __init__(self, workspace, path: Path, source, task, **options):
        self.path, self.task, self.options = path, task, options
        self.source = f"{entry_file(path, source)}:{source.rsplit(':', 1)[-1]}"
        native = read_json(path / "request.json")["native"]
        host = owned_host(workspace, native)
        if host is None:
            raise RuntimeError("This job's native host has exited; start a new run")
        self.link = host.link(kind="sdk", name="Codex")
        self.epic_root = Hmz(workspace).epics.under()
        self.epic = None
        self.usage = Usage()
        self.result, self.raised, self.how = None, None, ""
        self.number = None
        self.running, self.native_finished = False, False
        self.pending, self.roles = [], {}
        self._watch = self._opened = self._noticed = lambda *args: None
        self._done, self._lock = threading.Event(), threading.RLock()
        self._cancelled = False
        self.link.heard(self._heard)

    def watch(self, callback):
        self._watch = callback

    def opened(self, callback):
        self._opened = callback

    def noticed(self, callback):
        self._noticed = callback

    def start(self):
        if self._cancelled:
            self._done.set()
            return
        answer = self.link.start(self.source, self.task, **self.options)
        with self._lock:
            self.number = answer["run"]
            self.running = True
            for message in self.pending:
                self._accept(message)
            self.pending.clear()

    def _heard(self, message):
        with self._lock:
            if self.number is None:
                self.pending.append(message)
            else:
                self._accept(message)

    def _accept(self, message):
        kind = message.get("type")
        if kind == "gone":
            if not self.native_finished:
                self.raised = RuntimeError(message.get("why", "Native host disconnected"))
                self.running = False
                self._done.set()
            return
        if message.get("run") != self.number:
            return
        if message.get("epic"):
            self.epic = self.epic_root / message["epic"]
        if kind == "opened":
            role, key = message["role"], message["key"]
            self.roles[key] = role
            self._opened(role, SimpleNamespace(role=role), NativeSession(key, self.link), None)
        elif kind == "event":
            key = message.get("session") or message.get("key", "")
            self._watch(
                SimpleNamespace(role=self.roles.get(key, "")),
                NativeSession(key, self.link),
                SimpleNamespace(kind=message["kind"], text=message.get("text", "")),
            )
        elif kind == "notice":
            self._noticed(message.get("text", ""))
        elif kind == "usage":
            if message.get("usage"):
                self.usage = Usage.model_validate(message["usage"])
            if self.native_finished:
                self._done.set()
        elif kind == "ended":
            self.how = message["how"]
            if self.how == "done":
                try:
                    self.result = read_json(self.path / "flow-result.json")["value"]
                except (OSError, ValueError, KeyError) as error:
                    self.raised = RuntimeError(f"Native flow returned no recorded result: {error}")
            elif self.how == "budget":
                self.raised = BudgetExceeded(message.get("why", "Native budget exhausted"))
            elif self.how == "stopped":
                self.raised = asyncio.CancelledError()
            else:
                self.raised = RuntimeError(message.get("why") or self.how)
            self.running, self.native_finished = False, True

    def wait(self, seconds):
        ready = self._done.wait(seconds)
        if not ready and self.native_finished:
            status = self.link.asked({"do": "status"}, seconds=2)
            if status.get("epic"):
                self.epic = self.epic_root / status["epic"]
            self._done.set()
            return True
        return ready

    def stop(self):
        already = self._cancelled
        self._cancelled = True
        if self.running and not already:
            try:
                self.link.stop()
            except Refused:
                # The UI may already have stopped it; the ordered end event still arrives.
                pass

    def close(self):
        if self.running:
            self.stop()
            self.link.force()

    def detach(self):
        self.link.close()


def tui(job_id: str) -> None:
    from .store import atomic_json, data_root, job_path

    path = job_path(data_root(), job_id)
    request = read_json(path / "request.json")
    os.chdir(request["workspace"])
    native = request["native"]
    host = owned_host(request["workspace"], native)
    if host is not None:
        with host.link(kind="tui", name="Codex user") as link:
            atomic_json(path / "tui-ready.json", {"pid": os.getpid(), "slot": native["slot"]})
            from hmz.tui import Humanize

            Humanize(link=link).run()
    else:
        # Open the native history menu, without recreating an empty job host or rerunning it.
        with daemon.attach("tui", "Codex history", workspace=request["workspace"]) as link:
            from hmz.tui import Humanize

            app = Humanize(link=link)
            app.call_after_refresh(app.action_epics)
            app.run()
