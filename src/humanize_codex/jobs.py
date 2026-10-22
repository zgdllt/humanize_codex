"""Validate, launch and control isolated Humanize worker processes."""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .binary import select_codex, version
from .library import Library, snapshot
from .store import (
    TERMINAL,
    atomic_json,
    data_root,
    job_path,
    locked,
    read_json,
    workspace_locked,
)

DEFAULT_AGENT = ""
FLOW = Path(__file__).with_name("flow.py")
ROLES = ("planner", "actor", "reviewer", "observer")


def validate_agent(spec: str) -> str:
    """Use Humanize's own parser, restricted to the two supported harnesses."""
    from hmz.coganchor.backends import read

    if not isinstance(spec, str) or any(c.isspace() for c in spec) or "=" in spec:
        raise ValueError("agent must be codex[/@provider]/model:effort or dsh/model:effort")
    if not spec:
        return spec
    _, backend, _, effort, _ = read(spec)
    if backend.name not in {"codex", "dsh"}:
        raise ValueError("Supported harnesses are codex and dsh")
    if effort and effort not in backend.efforts:
        raise ValueError(f"Unsupported {backend.name} effort: {effort}")
    return spec


def doctor(workspace: str | None = None) -> dict[str, Any]:
    """Report prerequisites without exposing credentials or starting a model turn."""
    try:
        selected = select_codex()
        cli = {"path": str(selected), "version": list(version(selected))[:3]}
    except ValueError as error:
        cli = {"path": None, "error": str(error)}
    try:
        from hmz.coganchor.agents.dsh import native_ready

        dsh = {"sdk_version": importlib.metadata.version("deepseek-harness-sdk")}
        dsh["native_auth_ready"] = native_ready(workspace or Path.cwd())
    except importlib.metadata.PackageNotFoundError:
        dsh = {"sdk_version": None, "error": "Install the pinned hmz[dsh] dependencies"}
    return {
        "plugin_version": importlib.metadata.version("humanfia-humanize-codex"),
        "hmz_version": importlib.metadata.version("hmz"),
        "mcp_version": importlib.metadata.version("mcp"),
        "python": sys.version.split()[0],
        "codex": cli,
        "dsh": dsh,
        "default_agent": "Automatic: local Codex config or its advertised default model",
        "data_directory": str(data_root()),
        "nested_run": os.environ.get("HUMANIZE_CODEX_CHILD") == "1",
        "platform": sys.platform,
    }


def _bounded_number(value: float | int, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number")
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} must be greater than zero and at most {maximum}")
    return float(value)


def prepare(
    workspace: str,
    task: str,
    mode: str = "dynamic",
    agent: str = DEFAULT_AGENT,
    max_rounds: int = 6,
    duration_seconds: float = 1800,
    cost_usd: float | None = None,
    output_tokens: int = 50000,
    read_only: bool = False,
    agents: dict[str, str] | None = None,
    flow_file: str = "",
    retain_flow: bool = True,
    entrypoint: str = "",
    flow_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate all execution settings before creating any job or starting any agent."""
    if os.environ.get("HUMANIZE_CODEX_CHILD") == "1":
        raise ValueError("Nested Humanize runs are disabled; complete the assigned flow turn")
    path = Path(workspace).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("workspace must be an existing absolute directory")
    if not isinstance(task, str) or not task.strip() or len(task) > 100000:
        raise ValueError("task must contain 1–100000 characters")
    if mode not in {"dynamic", "review"}:
        raise ValueError("mode must be dynamic or review")
    validate_agent(agent)
    if agents is not None and (
        not isinstance(agents, dict)
        or len(agents) > 32
        or any(
            not isinstance(role, str)
            or not role.isidentifier()
            or (not entrypoint and role not in ROLES)
            for role in agents
        )
    ):
        raise ValueError("Use declared role names (up to 32); builtin flows use their four roles")
    for spec in (agents or {}).values():
        validate_agent(spec)
    if flow_file:
        source = Path(flow_file).expanduser()
        if not source.is_absolute() or not source.is_file() or source.suffix != ".py":
            raise ValueError("flow_file must be an existing absolute trusted Python file")
        flow_file = str(source.resolve())
    if not isinstance(retain_flow, bool):
        raise ValueError("retain_flow must be a boolean")
    if entrypoint and (not flow_file or not re.fullmatch(r"[A-Za-z_]\w*", entrypoint)):
        raise ValueError("A custom entrypoint requires a trusted flow_file and Python identifier")
    if flow_params is not None and not isinstance(flow_params, dict):
        raise ValueError("flow_params must be an object")
    if (
        isinstance(max_rounds, bool)
        or not isinstance(max_rounds, int)
        or not 1 <= max_rounds <= 100
    ):
        raise ValueError("max_rounds must be an integer between 1 and 100")
    duration = _bounded_number(duration_seconds, "duration_seconds", 86400)
    _bounded_number(output_tokens, "output_tokens", 10000000)
    if not isinstance(output_tokens, int):
        raise ValueError("output_tokens must be an integer")
    if not isinstance(read_only, bool):
        raise ValueError("read_only must be a boolean")
    budget: dict[str, Any] = {"duration": duration, "output_tokens": output_tokens}
    if cost_usd is not None:
        budget["cost"] = _bounded_number(cost_usd, "cost_usd", 100000)
    return {
        "workspace": str(path.resolve()),
        "task": task,
        "mode": mode,
        "agent": agent,
        "max_rounds": max_rounds,
        "budget": budget,
        "read_only": read_only,
        "agents": agents or {},
        "flow_file": flow_file,
        "retain_flow": retain_flow,
        "entrypoint": entrypoint,
        "flow_params": flow_params or {},
    }


class Jobs:
    """Durable worker handles shared by every Codex chat using this installation."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or data_root()).resolve()

    def status(self, job_id: str) -> dict[str, Any]:
        path = job_path(self.root, job_id)
        state = read_json(path / "state.json")
        if state["status"] not in TERMINAL and time.time() - state["heartbeat"] > 60:
            state = {**state, "status": "lost", "error": "Worker heartbeat expired"}
        request = read_json(path / "request.json")
        progress = read_json(path / "progress.json") if (path / "progress.json").is_file() else {}
        report = read_json(path / "report.json") if (path / "report.json").is_file() else {}
        retention = state.get("retention_class")
        if state.get("retained_flow"):
            try:
                retention = Library(self.root).get(state["retained_flow"])["curation"]["status"]
            except (OSError, ValueError):
                pass
        elapsed = max(0, state.get("finished", time.time()) - state["created"])
        return {
            **state,
            "progress": progress,
            "report": report,
            "retention_class": retention,
            "elapsed_seconds": round(elapsed, 1),
            "remaining_seconds": round(max(0, request["budget"]["duration"] - elapsed), 1),
            "revision": f"{state['status']}:{progress.get('revision', 0)}",
            "artifacts": str(path),
            "request": request,
        }

    def list(self, workspace: str | None = None) -> list[dict[str, Any]]:
        selected = str(Path(workspace).expanduser().resolve()) if workspace else None
        states = []
        for file in sorted((self.root / "runs").glob("*/request.json"), reverse=True):
            state = self.status(file.parent.name)
            if selected is None or state["request"]["workspace"] == selected:
                states.append(state)
        return sorted(states, key=lambda s: s["created"], reverse=True)

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        if os.environ.get("HUMANIZE_CODEX_CHILD") == "1":
            raise ValueError("A Humanize worker cannot launch another Humanize workflow")
        # Resolve actual declared roles/backends in the worker, before any model turn.
        # The parent cannot infer omitted/automatic roles of arbitrary Python collections.
        source = Path(request.get("flow_file") or FLOW)
        source_bytes = snapshot(source, request.get("entrypoint", ""))
        with locked(self.root), workspace_locked(self.root, request["workspace"]):
            for current in self.list(request["workspace"]):
                if current["status"] not in TERMINAL:
                    raise ValueError(
                        f"This workspace already has an active job: {current['job_id']}"
                    )
            job_id = uuid.uuid4().hex
            path = self.root / "runs" / job_id
            path.mkdir(parents=True, mode=0o700)
            now = time.time()
            (path / "workflow.py").write_bytes(source_bytes)
            atomic_json(path / "request.json", request)
            atomic_json(
                path / "state.json",
                {
                    "job_id": job_id,
                    "status": "starting",
                    "created": now,
                    "heartbeat": now,
                },
            )
            env = {**os.environ, "HUMANIZE_CODEX_DATA": str(self.root)}
            try:
                with (path / "worker.log").open("ab") as log:
                    subprocess.Popen(
                        [sys.executable, "-m", "humanize_codex.cli", "worker", job_id],
                        cwd=request["workspace"],
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
            except OSError as error:
                state = read_json(path / "state.json")
                atomic_json(
                    path / "state.json",
                    {
                        **state,
                        "status": "failed",
                        "error": str(error),
                        "heartbeat": time.time(),
                    },
                )
                raise
        return self.status(job_id)

    def control(self, job_id: str, kind: str, text: str = "", role: str = "") -> dict[str, Any]:
        if kind not in {"cancel", "steer"}:
            raise ValueError("Unknown control action")
        path = job_path(self.root, job_id)
        state = self.status(job_id)
        if state["status"] in TERMINAL:
            raise ValueError(f"Job is already {state['status']}")
        if kind == "steer" and (not text.strip() or len(text) > 50000):
            raise ValueError("Steering text must contain 1–50000 characters")
        if role and (
            role not in state.get("agents", {})
            or role in {"observer", "humanize_observer", "humanize_verifier"}
        ):
            raise ValueError("Select an active custom task role, not a manager/observer role")
        ticket = uuid.uuid4().hex
        with locked(self.root):
            atomic_json(
                path / "inbox" / f"{time.time_ns()}-{ticket}.json",
                {
                    "kind": kind,
                    "text": text,
                    "ticket": ticket,
                    "role": role,
                },
            )
            if kind == "cancel":
                atomic_json(path / "cancel.json", {"ticket": ticket})
        return {"job_id": job_id, "ticket": ticket, "status": "queued"}

    def wait(
        self, job_id: str, seconds: float = 30, after_revision: str | None = None
    ) -> dict[str, Any]:
        if not math.isfinite(seconds) or not 0 <= seconds <= 60:
            raise ValueError("seconds must be between 0 and 60")
        deadline = time.monotonic() + seconds
        while True:
            state = self.status(job_id)
            if (
                state["status"] in TERMINAL
                or time.monotonic() >= deadline
                or after_revision is not None
                and state["revision"] != after_revision
            ):
                return state
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def resume(self, job_id: str, guidance: str = "") -> dict[str, Any]:
        state = self.status(job_id)
        if state["status"] not in TERMINAL or state["status"] == "complete":
            raise ValueError("Only an unfinished, stopped job can be resumed")
        if not state.get("epic"):
            raise ValueError("This job has no Humanize journal to resume")
        if state["request"].get("entrypoint") and not state.get("flow", {}).get("resumable"):
            raise ValueError(
                "This authored flow does not support resume; reassess before a new run"
            )
        if len(guidance) > 50000:
            raise ValueError("guidance is too long")
        request = dict(state["request"])
        request["flow_file"] = str(job_path(self.root, job_id) / "workflow.py")
        request.update(resume_epic=state["epic"], resume_of=job_id, guidance=guidance)
        return self.start(request)

    def reuse(
        self,
        name: str,
        workspace: str,
        task: str,
        duration_seconds: float = 1800,
        output_tokens: int = 50000,
        agents: dict[str, str] | None = None,
        flow_params: dict[str, Any] | None = None,
        allow_candidate: bool = False,
    ) -> dict[str, Any]:
        profile = Library(self.root).get(name)
        if profile["curation"]["status"] == "rejected":
            raise ValueError("This flow was rejected; reassess it before reuse")
        if profile["curation"]["status"] != "curated" and not allow_candidate:
            raise ValueError("This is an uncurated candidate; assess it or explicitly trial it")
        settings = profile["settings"]
        request = prepare(
            workspace,
            task,
            mode=settings["mode"],
            max_rounds=settings["max_rounds"],
            read_only=settings["read_only"],
            agents={
                k: v
                for k, v in {**settings["agents"], **(agents or {})}.items()
                if settings.get("entrypoint") or k not in {"humanize_verifier", "humanize_observer"}
            },
            duration_seconds=duration_seconds,
            output_tokens=output_tokens,
            flow_file=str(Library(self.root).source(name)),
            entrypoint=settings.get("entrypoint", ""),
            flow_params=flow_params,
        )
        request["reused_flow"] = name
        return self.start(request)

    def events(self, job_id: str, limit: int = 15) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        path = job_path(self.root, job_id) / "events.jsonl"
        if not path.exists():
            return []
        from collections import deque

        with path.open(encoding="utf-8") as stream:
            return [json.loads(line) for line in deque(stream, maxlen=limit) if line.endswith("\n")]
