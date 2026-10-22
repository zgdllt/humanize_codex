"""Inspect and wrap arbitrary local Python flows using the public Humanize API."""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

from hmz.sdk import Hmz

from .library import snapshot

RESERVED = ("humanize_verifier", "humanize_observer")
RESERVED_ENV = "humanize_workspace"


def _declares_name(node: ast.AST, name: str) -> bool:
    """Match an `@flow(name=...)` decorator so a renamed entry still resolves."""
    return any(
        isinstance(decorator, ast.Call)
        and any(
            keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == name
            for keyword in decorator.keywords
        )
        for decorator in getattr(node, "decorator_list", [])
    )


def inspect_flow(source: str, entrypoint: str, workspace: str) -> dict:
    """Inspect a fresh frozen module in a bounded process, never in the MCP process."""
    import os
    import sys
    import tempfile

    from .processes import bounded_python
    from .store import atomic_json, read_json

    with tempfile.TemporaryDirectory(prefix="humanize-inspect-") as directory:
        path = Path(directory)
        (path / "workflow.py").write_bytes(
            snapshot(Path(source).expanduser().resolve(), entrypoint)
        )
        atomic_json(path / "input.json", {"entrypoint": entrypoint, "workspace": workspace})
        bounded_python(
            [sys.executable, "-m", "humanize_codex.cli", "inspect-worker", directory],
            cwd=directory,
            env={**os.environ, "HUMANIZE_CODEX_CHILD": "1"},
            timeout=10,
        )
        result = read_json(path / "declaration.json")
        if "error" in result:
            raise ValueError(result["error"])
        return result


def _inspect_flow(source: str, entrypoint: str, workspace: str) -> dict:
    """Imports trusted Python via Humanize; this is introspection, not a security sandbox."""
    path = Path(source).expanduser().resolve()
    content = snapshot(path, entrypoint)
    declaration = Hmz(workspace).flows.declared(f"{path}:{entrypoint}")
    if any(role.name in RESERVED for role in declaration.agents):
        raise ValueError(f"Reserved manager role names: {', '.join(RESERVED)}")
    if len(declaration.agents) > 30:
        raise ValueError("The local manager supports up to 30 declared task roles")
    if any(env.name == RESERVED_ENV for env in declaration.envs):
        raise ValueError(f"Reserved manager environment name: {RESERVED_ENV}")
    if any(not env.auto for env in declaration.envs):
        raise ValueError(
            "The local manager requires LocalEnv roles; use hmz for remote provisioning"
        )
    module = ast.parse(content)
    functions = {
        n.name: n for n in module.body if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    selected = functions.get(entrypoint)
    if selected is None:
        selected = next((n for n in functions.values() if _declares_name(n, entrypoint)), None)
    if selected is None:
        raise ValueError(f"No flow function declares the entrypoint {entrypoint!r}")
    reached, pending, seen = [], [selected], set()
    while pending:
        function = pending.pop()
        if function.name in seen:
            continue
        seen.add(function.name)
        reached.append(function)
        pending.extend(
            functions[n.func.id]
            for n in ast.walk(function)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in functions
            and n.func.id not in seen
        )
    tree = ast.Module(body=reached, type_ignores=[])
    forms = ["sequence"]
    if any(isinstance(node, ast.For | ast.AsyncFor | ast.While) for node in ast.walk(tree)):
        forms.append("loop")
    if any(isinstance(node, ast.If | ast.IfExp | ast.Match) for node in ast.walk(tree)):
        forms.append("branch")
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"gather", "create_task", "TaskGroup"}
        for node in ast.walk(tree)
    ):
        forms.append("parallel")
    return {
        "entrypoint": entrypoint,
        "description": declaration.description,
        "roles": [
            {
                "name": role.name,
                "auto": role.auto,
                "required": role.required,
                "permission": dataclasses.asdict(role.permission),
            }
            for role in declaration.agents
        ],
        "environments": [env.name for env in declaration.envs],
        "params_schema": declaration.params.model_json_schema(),
        "resumable": declaration.resumable,
        "structures": forms,
        "structure_note": "Static syntax hints; not an inferred execution graph",
    }


def make_envelope(path: Path, entrypoint: str, read_only: bool) -> tuple[Path, dict]:
    """Freeze the entry's signature and add separate verification and narration roles."""
    info = _inspect_flow(str(path / "workflow.py"), entrypoint, str(path))
    if read_only and any(role["permission"]["local"] == "all" for role in info["roles"]):
        raise ValueError(
            "read_only requires every custom agent role to declare read-only permission"
        )
    wrapper = path / "envelope.py"
    wrapper.write_text(
        "from hmz.flows import AgentCollection, EnvCollection, LocalEnv, flow, load\n"
        "from hmz.sdk import Hmz\n"
        "from humanize_codex.flow import Reader, Observer\n"
        "from humanize_codex.envelope import EnvelopeParams, execute\n"
        f"target = load({str(path / 'workflow.py') + ':' + entrypoint!r})\n"
        f"declared = Hmz().flows.declared({str(path / 'workflow.py') + ':' + entrypoint!r})\n"
        "roles = {role.name: role.declared for role in declared.agents if not role.auto}\n"
        "roles.update(humanize_verifier=Reader, humanize_observer=Observer)\n"
        "ManagedAgents = type('ManagedAgents', (AgentCollection,), "
        "{'__annotations__': roles, '__module__': __name__})\n"
        "environments = {env.name: env.declared for env in declared.envs}\n"
        "environments['humanize_workspace'] = LocalEnv\n"
        "ManagedEnvs = type('ManagedEnvs', (EnvCollection,), "
        "{'__annotations__': environments, '__module__': __name__})\n"
        "@flow(agents=ManagedAgents, envs=ManagedEnvs, params=EnvelopeParams, "
        f"resumable={info['resumable']!r})\n"
        "async def managed(task, *, agents, envs, params, ctx):\n"
        "    return await execute(target, declared, task, agents, envs, params, ctx)\n",
        encoding="utf-8",
    )
    return wrapper, info


def fake_cases(source: str, entrypoint: str, cases: list[dict]) -> dict:
    """Run caller-supplied structural scenarios using the real engine and scripted agents."""
    import asyncio
    import hashlib
    import tempfile

    from hmz.sdk import fakes

    content = snapshot(Path(source), entrypoint)

    async def exercise() -> list[dict]:
        results = []
        with tempfile.TemporaryDirectory(prefix="humanize-flow-check-") as directory:
            frozen = Path(directory) / "workflow.py"
            frozen.write_bytes(content)
            for index, case in enumerate(cases):
                try:
                    # No online model calls; no user-worktree environment is handed to a case.
                    output = await asyncio.wait_for(
                        fakes.run_fake(
                            f"{frozen}:{entrypoint}",
                            case.get("task", "Structural validation"),
                            agents=case.get("agents", {}),
                            params=case.get("params", {}),
                        ),
                        timeout=10,
                    )
                    expected = case.get("expected", {})
                    if not isinstance(output, dict) or any(
                        output.get(k) != v for k, v in expected.items()
                    ):
                        raise ValueError("The flow result did not match the expected fields")
                    scenario = hashlib.sha256(
                        json.dumps(
                            {k: case.get(k, {}) for k in ("agents", "params", "expected")},
                            sort_keys=True,
                        ).encode()
                    ).hexdigest()
                    results.append({"case": index, "status": "passed", "scenario": scenario})
                except Exception as error:
                    results.append(
                        {
                            "case": index,
                            "status": "failed",
                            "error": f"{type(error).__name__}: {error}"[:1000],
                        }
                    )
        return results

    results = asyncio.run(exercise())
    return {
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "entrypoint": entrypoint,
        "cases": results,
        "status": "passed" if all(x["status"] == "passed" for x in results) else "failed",
        "model_calls": False,
    }


def validate_flow(root: Path, source: str, entrypoint: str, cases: list[dict]) -> dict:
    """Bound a local validation subprocess, keeping its receipt separate from model claims."""
    import os
    import subprocess
    import sys
    import uuid

    from .processes import bounded_python
    from .store import atomic_json, read_json

    if not isinstance(cases, list) or not 1 <= len(cases) <= 8:
        raise ValueError("Supply 1–8 fake scenarios")
    for case in cases:
        if (
            not isinstance(case, dict)
            or not isinstance(case.get("expected"), dict)
            or not case["expected"]
        ):
            raise ValueError("Each case requires nonempty expected result fields")
    path = root / "validations" / uuid.uuid4().hex
    path.mkdir(parents=True, mode=0o700)
    (path / "workflow.py").write_bytes(snapshot(Path(source), entrypoint))
    atomic_json(path / "input.json", {"entrypoint": entrypoint, "cases": cases})
    try:
        bounded_python(
            [sys.executable, "-m", "humanize_codex.cli", "validate-worker", str(path)],
            env={**os.environ, "HUMANIZE_CODEX_CHILD": "1"},
            cwd=path,
            timeout=10 * len(cases) + 5,
        )
        receipt = read_json(path / "receipt.json")
    except (subprocess.SubprocessError, OSError) as error:
        receipt = {"status": "failed", "error": type(error).__name__}
        atomic_json(path / "receipt.json", receipt)
    return {"validation_id": path.name, **receipt}
