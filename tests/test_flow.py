"""Official algorithms run unchanged; the native bridge preserves skills and permissions."""

import asyncio
import json

import pytest
from hmz.flows import PermissionKind
from hmz.sdk import Hmz, fakes

from humanize_codex.jobs import execution_budget
from humanize_codex.native import entry_file


def test_official_rlar_has_no_plugin_round_cap():
    actor = fakes.FakeAgentDriver("codex", reply="Implemented")
    reviewer = fakes.FakeAgentDriver(
        "codex",
        reply=[{"done": False, "notes": "Continue"}] * 101
        + [{"done": True, "notes": "Verified the implementation"}],
    )
    result = asyncio.run(
        fakes.run_fake(
            "rlar",
            "Implement the task",
            agents={"actor": actor, "reviewer": reviewer},
        )
    )
    assert result == "Verified the implementation"
    assert len(actor.sessions) == 1
    assert len(reviewer.sessions) == 102


@pytest.mark.parametrize("read_only", [False, True])
def test_native_bridge_runs_real_official_rlar_with_its_skills(tmp_path, read_only, monkeypatch):
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "0")
    bridge = entry_file(tmp_path, "rlar", read_only=read_only)
    ref = f"{bridge}:rlar"
    declared = Hmz(tmp_path).flows.declared(ref)
    assert {r.name for r in declared.agents} == {"actor", "reviewer"}
    assert (bridge / "skills/review-notes/SKILL.md").is_file()
    if read_only:
        assert all(r.permission.local == PermissionKind.READ for r in declared.agents)
    run = Hmz(tmp_path).run(
        ref,
        "Implement the task",
        agents={
            "actor": fakes.FakeAgentDriver("codex", reply="Done"),
            "reviewer": fakes.FakeAgentDriver("codex", reply={"done": True, "notes": "Verified"}),
        },
        budget=execution_budget(),
        backup=[],
    )
    assert run.run() == "Verified"
    assert json.loads((tmp_path / "flow-result.json").read_text()) == {"value": "Verified"}


def test_readonly_bridge_keeps_denied_permissions_and_automatic_roles(tmp_path, monkeypatch):
    monkeypatch.setenv("HUMANIZE_CODEX_CHILD", "0")
    source = tmp_path / "sealed.py"
    source.write_text("""from hmz.flows import *
class Sealed(Agent):
    _permission = Permission(local=PermissionKind.NONE, user=PermissionKind.NONE,
                             system=PermissionKind.NONE, online=PermissionKind.NONE)
class Agents(AgentCollection):
    worker: Sealed
@flow(agents=Agents, envs=EnvCollection, params=FlowParams)
async def sealed(task, *, agents, envs, params, ctx):
    return "done"
""")
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    bridge = entry_file(restricted, f"{source}:sealed", read_only=True)
    role = Hmz(tmp_path).flows.declared(f"{bridge}:sealed").agents[0]
    for scope in ("local", "user", "system", "online"):
        assert getattr(role.permission, scope) == PermissionKind.NONE
    chat = tmp_path / "chat"
    chat.mkdir()
    bridge = entry_file(chat, "chat", read_only=True)
    original = Hmz(tmp_path).flows.declared("chat")
    adapted = Hmz(tmp_path).flows.declared(f"{bridge}:chat")
    assert [(r.name, r.auto) for r in adapted.agents] == [(r.name, r.auto) for r in original.agents]
