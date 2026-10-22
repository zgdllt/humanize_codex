"""Status narration belongs to an isolated agent and cannot hold up the writer."""

import asyncio
import json
import time

from hmz.sdk import fakes
from test_flow import REPORT, run, verdict

from humanize_codex.flow import Params, StatusObserver


def test_dsh_observer_owns_narration_in_separate_session(tmp_path):
    observer = fakes.FakeAgentDriver("dsh", reply=REPORT)
    actor = fakes.FakeAgentDriver("codex", reply="Implemented and checked")
    result = run(tmp_path, actor, verdict("complete"), observer=observer)
    assert result["status"] == "complete"
    assert observer.prompts
    assert all("You own the live dashboard" in prompt for prompt in observer.prompts)
    assert all("Implement the requested feature" not in prompt for prompt in observer.prompts)
    assert all("You own the live dashboard" not in prompt for prompt in actor.prompts)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["role"] == "observer" and report["summary"] == REPORT["summary"]
    assert json.loads((tmp_path / "progress.json").read_text())["stage"] == "complete"


def test_broken_status_agent_does_not_fail_implementation(tmp_path):
    result = run(tmp_path, "Done", verdict("complete"), observer="invalid structured report")
    assert result["status"] == "complete"
    assert json.loads((tmp_path / "report.json").read_text())["status"] == "unavailable"


def test_slow_observer_is_cancelled_without_holding_up_completion(tmp_path):
    class SlowAgent:
        async def spawn(self):
            return object()

        async def run(self, *_args, **_kwargs):
            await asyncio.sleep(3600)

    async def exercise():
        observer = StatusObserver(SlowAgent(), Params(artifacts=str(tmp_path)))
        observer.publish({"revision": 1, "stage": "acting"})
        await asyncio.sleep(0)
        start = time.monotonic()
        await observer.close()
        assert time.monotonic() - start < 2
        assert observer.task.done()

    asyncio.run(exercise())
