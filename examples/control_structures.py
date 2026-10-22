"""Four real Humanize Python flow shapes; local, read-only agent roles throughout."""

import asyncio

from hmz.flows import (
    Agent,
    AgentCollection,
    EnvCollection,
    FlowParams,
    LocalEnv,
    Permission,
    PermissionKind,
    flow,
)
from pydantic import Field


class Analyst(Agent):
    _permission = Permission(local=PermissionKind.READ, online=PermissionKind.NONE)


class Team(AgentCollection):
    first: Analyst
    second: Analyst


class Envs(EnvCollection):
    workspace: LocalEnv


class Inputs(FlowParams):
    iterations: int = Field(default=2, ge=1, le=5)
    alternate: bool = False


async def ask(agent, text, workspace):
    return await agent.run(text, session=await agent.spawn(), env=workspace)


@flow(agents=Team, envs=Envs, params=Inputs)
async def sequence_flow(task, *, agents, envs, params, ctx):
    first = await ask(agents["first"], task, envs["workspace"])
    second = await ask(
        agents["second"], f"Independently check this claim: {first}", envs["workspace"]
    )
    return {"shape": "sequence", "answers": [first, second]}


@flow(agents=Team, envs=Envs, params=Inputs)
async def loop_flow(task, *, agents, envs, params, ctx):
    answers = []
    for number in range(params.iterations):
        answers.append(await ask(agents["first"], f"{task}; pass {number + 1}", envs["workspace"]))
    return {"shape": "loop", "iterations": len(answers), "answers": answers}


@flow(agents=Team, envs=Envs, params=Inputs)
async def branch_flow(task, *, agents, envs, params, ctx):
    chosen = "second" if params.alternate else "first"
    answer = await ask(agents[chosen], task, envs["workspace"])
    return {"shape": "branch", "selected": chosen, "answer": answer}


@flow(agents=Team, envs=Envs, params=Inputs)
async def parallel_flow(task, *, agents, envs, params, ctx):
    answers = await asyncio.gather(
        ask(agents["first"], task + " — inspect one approach", envs["workspace"]),
        ask(agents["second"], task + " — inspect another approach", envs["workspace"]),
    )
    return {"shape": "parallel", "answers": answers}
