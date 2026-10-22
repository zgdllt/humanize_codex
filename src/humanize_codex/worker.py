"""One independent, bounded Humanize SDK run with durable progress and control receipts."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import threading
import time
import traceback
from typing import Any

from .binary import select_codex
from .compat import guard_codex_startup
from .jobs import ROLES
from .library import Library
from .models import default_agent
from .store import atomic_json, data_root, job_path, read_json, workspace_locked


def work(job_id: str) -> None:
    """Run the real Humanize engine; a closed MCP connection does not abandon the run."""
    root = data_root()
    request = read_json(job_path(root, job_id) / "request.json")
    with workspace_locked(root, request["workspace"], wait=True):
        _work(job_id)


def _work(job_id: str) -> None:
    """Own one workspace lock for the entire lifetime of the Humanize SDK run."""
    from hmz.flows import BudgetExceeded
    from hmz.sdk import Hmz

    path = job_path(data_root(), job_id)
    request = read_json(path / "request.json")
    state = read_json(path / "state.json")
    state.update(status="starting", pid=os.getpid(), active_agents=[])
    os.environ["HUMANIZE_CODEX_CHILD"] = "1"
    guard = threading.RLock()
    cancel = threading.Event()
    finished = threading.Event()
    sessions: list[Any] = []
    session_roles: dict[str, str] = {}
    active: dict[str, dict] = {}
    guidance: list[str] = []

    def update(**values: Any) -> None:
        with guard:
            state.update(values, heartbeat=time.time())
            atomic_json(path / "state.json", state)

    def event(kind: str, **values: Any) -> None:
        with guard, (path / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps({"at": time.time(), "kind": kind, **values}, default=str) + "\n"
            )
        update(last_activity={"at": time.time(), "kind": kind, "role": values.get("role", "")})

    def heartbeat() -> None:
        while not finished.wait(2):
            update()

    def watch(agent, session, item) -> None:
        text = getattr(item, "text", "")
        key, kind = str(session), str(item.kind)
        role = session_roles.get(key, getattr(agent, "role", ""))
        with guard:
            if kind == "begins":
                active[key] = {"role": role, "started": time.time()}
            elif kind == "ends":
                active.pop(key, None)
            update(active_agents=list(active.values()))
            if (
                request.get("entrypoint")
                and kind in {"begins", "ends"}
                and role not in {"humanize_observer", "humanize_verifier"}
            ):
                running = [
                    x["role"]
                    for x in active.values()
                    if x["role"] not in {"humanize_observer", "humanize_verifier"}
                ]
                atomic_json(
                    path / "progress.json",
                    {
                        "revision": time.time_ns(),
                        "stage": "custom",
                        "role": role,
                        "message": "Active roles: " + (", ".join(running) or "Python control flow"),
                        "active_roles": running,
                        "updated": time.time(),
                        "custom": True,
                    },
                )
        event(kind, role=role, text=str(text)[:4000])

    def opened(role, agent, session, where) -> None:
        with guard:
            sessions.append(session)
            del sessions[:-20]
            session_roles[str(session)] = str(role)
        event("session_opened", role=role)

    def control(run) -> None:
        for message in sorted((path / "inbox").glob("*.json")):
            item = read_json(message)
            if item["kind"] == "cancel":
                cancel.set()
                run.stop()
                event("control_receipt", ticket=item["ticket"], delivery="cancelling")
            else:
                guidance.append(item["text"])
                atomic_json(path / "guidance.json", guidance)
                delivery = "available_to_flow" if request.get("entrypoint") else "next_turn"
                desired = item.get("role") or ("" if request.get("entrypoint") else "actor")
                with guard:
                    candidates = [
                        session
                        for session in reversed(sessions)
                        if session_roles.get(str(session)) == desired and desired
                    ]
                for session in candidates:
                    try:
                        session.interject(item["text"])
                        delivery = "submitted_to_session"
                        break
                    except (RuntimeError, NotImplementedError, ValueError, AttributeError):
                        continue
                event("control_receipt", ticket=item["ticket"], delivery=delivery)
            message.unlink()

    signal.signal(signal.SIGTERM, lambda *_: cancel.set())
    signal.signal(signal.SIGINT, lambda *_: cancel.set())
    threading.Thread(target=heartbeat, daemon=True).start()
    run = None
    try:
        chosen = "read_only_workflow" if request["read_only"] else "dynamic_workflow"
        source = path / "workflow.py"
        roles = list(ROLES)
        params = {
            "mode": request["mode"],
            "max_rounds": request["max_rounds"],
            "artifacts": str(path),
            "guidance": request.get("guidance", ""),
        }
        if request.get("entrypoint"):
            from .custom import RESERVED, make_envelope

            source, info = make_envelope(path, request["entrypoint"], request["read_only"])
            declared = Hmz(request["workspace"]).flows.declared(
                f"{path / 'workflow.py'}:{request['entrypoint']}"
            )
            declared.params.model_validate(request.get("flow_params", {}))
            roles = [r["name"] for r in info["roles"] if not r["auto"]] + list(RESERVED)
            if set(request.get("agents", {})) - set(roles):
                raise ValueError("Agent assignments contain roles not declared by this flow")
            chosen = "managed"
            params = {
                "inputs": request.get("flow_params", {}),
                "artifacts": str(path),
                "guidance": request.get("guidance", ""),
                "max_rounds": request["max_rounds"],
            }
            update(flow=info)
        assignments = {
            role: request.get("agents", {}).get(role) or request["agent"] for role in roles
        }
        if any(
            not spec or spec.partition("/")[0].partition("@")[0] == "codex"
            for spec in assignments.values()
        ):
            binary = select_codex()
            tool_bin = path / "tool-bin"
            tool_bin.mkdir(exist_ok=True)
            (tool_bin / "codex").symlink_to(binary)
            os.environ["PATH"] = str(tool_bin) + os.pathsep + os.environ.get("PATH", "")
            update(codex_binary=str(binary))
            guard_codex_startup()
        automatic = default_agent() if any(not spec for spec in assignments.values()) else ""
        assignments = {role: spec or automatic for role, spec in assignments.items()}
        update(agents=assignments)
        run = Hmz(request["workspace"]).run(
            f"{source}:{chosen}",
            request["task"],
            agents=assignments,
            params=params,
            budget=request["budget"],
            resume=request.get("resume_epic", False),
            backup=[],
        )
        run.watch(watch)
        run.opened(opened)
        run.noticed(lambda text: event("notice", text=text))
        control(run)
        run.start()
        update(status="running")
        began = time.monotonic()
        forced_budget = False
        while not run.wait(0.2):
            control(run)
            if cancel.is_set():
                run.stop()
            if time.monotonic() - began > request["budget"]["duration"] + 5:
                forced_budget = True
                run.close()
            usage = run.usage
            update(
                epic=str(run.epic) if run.epic else None,
                usage={
                    "duration_seconds": usage.duration.total_seconds(),
                    "cost_usd": usage.cost,
                    "output_tokens": usage.output_tokens,
                },
            )
        error = run.raised
        if cancel.is_set():
            update(status="cancelled")
        elif forced_budget or isinstance(error, BudgetExceeded):
            update(status="budget_exceeded", error=str(error or "Wall-clock limit reached"))
        elif error is not None:
            update(status="failed", error=f"{type(error).__name__}: {error}")
        elif isinstance(run.result, dict) and run.result.get("status") in {
            "complete",
            "blocked",
            "round_limit",
            "needs_work",
        }:
            update(status=run.result["status"], result=run.result)
        else:
            update(status="failed", error="The flow returned no recognized completion result")
        usage = run.usage
        update(
            epic=str(run.epic) if run.epic else None,
            usage={
                "duration_seconds": usage.duration.total_seconds(),
                "cost_usd": usage.cost,
                "output_tokens": usage.output_tokens,
            },
        )
    except (Exception, asyncio.CancelledError) as error:
        traceback.print_exc()
        update(
            status="cancelled" if cancel.is_set() else "failed",
            error=f"{type(error).__name__}: {error}",
        )
    finally:
        if run is not None and run.running:
            run.close()
            run.wait(10)
        finished.set()
        update(finished=time.time(), active_agents=[])
        if state["status"] == "complete" and request.get("retain_flow", True):
            try:
                profile = Library(data_root()).retain(job_id)
                update(retained_flow=profile["name"], retention_class="candidate")
                event("flow_retained", name=profile["name"], successes=profile["successes"])
            except Exception as error:
                # A library failure must not change an already reviewed task outcome.
                update(retention_error=f"{type(error).__name__}: {error}")
