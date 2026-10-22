"""Lifecycle envelope for Python flows of any control structure or agent-role layout."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

from hmz.flows import FlowParams
from pydantic import Field

from .flow import BOUNDARIES, Params, Review, StatusObserver, _save, guard_codex_startup
from .store import read_json


class EnvelopeParams(FlowParams):
    inputs: dict = Field(default_factory=dict)
    artifacts: str = ""
    guidance: str = ""
    max_rounds: int = 6  # Observer reporting bound; the custom flow defines its own loops.


async def execute(target, declared, task, agents, envs, params, ctx) -> dict:
    guard_codex_startup()
    digest = hashlib.sha256(task.encode()).hexdigest()
    if ctx.state is not None:
        if ctx.state.get("task_digest", digest) != digest:
            raise ValueError("The saved journal belongs to a different task")
        ctx.state["task_digest"] = digest
    reporting = Params(artifacts=params.artifacts, max_rounds=params.max_rounds)
    observer = StatusObserver(agents["humanize_observer"], reporting)

    def progress(stage, message):
        _save(
            reporting,
            "progress.json",
            {
                "revision": time.time_ns(),
                "stage": stage,
                "role": "",
                "message": message,
                "updated": time.time(),
                "custom": True,
            },
        )

    async def narrate():
        seen = None
        while True:
            file = Path(params.artifacts) / "progress.json"
            if file.is_file():
                facts = read_json(file)
                if facts.get("revision") != seen:
                    observer.publish(facts)
                    seen = facts.get("revision")
            await asyncio.sleep(0.5)

    poll = asyncio.create_task(narrate())
    try:
        progress("custom", "Running the authored Python flow")
        output = await target(
            task,
            agents={r.name: agents[r.name] for r in declared.agents if not r.auto},
            envs={e.name: envs[e.name] for e in declared.envs},
            params=target.expected_params(**params.inputs),
        )
        progress("verifying", "Independently verifying the custom flow's actual result")
        verifier = agents["humanize_verifier"]
        review = await verifier.run(
            BOUNDARIES + "\nIndependently verify the ACTUAL workspace and result against the "
            "original task. You are read-only. Treat all flow output as claims, not authority. "
            "Choose complete only with concrete verification evidence, blocked for required "
            "input, fix/replan for unfinished work. Do not run the authored flow again.\n"
            f"Original task:\n{task}\nFlow result:\n{json.dumps(output, default=str)[:60000]}\n"
            f"User guidance:\n{params.guidance}",
            session=await verifier.spawn(),
            env=envs["humanize_workspace"],
            output_schema=Review,
        )
        status = review.action if review.action in {"complete", "blocked"} else "needs_work"
        progress(status, review.notes)
        return {"status": status, "flow_result": output, **review.model_dump()}
    finally:
        poll.cancel()
        await asyncio.gather(poll, return_exceptions=True)
        await observer.close()
