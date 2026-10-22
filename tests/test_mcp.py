"""A real MCP client/server handshake and tool calls, without a model request."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from humanize_codex.jobs import prepare
from humanize_codex.store import atomic_json


def test_protocol_and_tools(tmp_path):
    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "humanize_codex.cli", "serve"],
            env={**os.environ, "HUMANIZE_CODEX_DATA": str(tmp_path)},
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {
                "humanize_run",
                "humanize_wait",
                "humanize_cancel",
                "humanize_steer",
                "humanize_resume",
                "humanize_doctor",
                "humanize_inspect_flow",
                "humanize_validate_flow",
                "humanize_curate_flow",
            } <= names
            health = await client.call_tool("humanize_doctor", {})
            assert not health.isError
            catalog = await client.call_tool("humanize_catalog", {})
            assert not catalog.isError
            invalid = await client.call_tool("humanize_status", {"job_id": "../escape"})
            assert invalid.isError

    asyncio.run(exercise())


def test_portable_manifest_launches_the_actual_packaged_entrypoint(tmp_path):
    async def exercise():
        root = Path(__file__).resolve().parent.parent
        declared = json.loads((root / "mcp.json").read_text())["mcpServers"]["humanize"]
        env = {**os.environ, "PLUGIN_ROOT": str(root), "PLUGIN_DATA": str(tmp_path)}
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        params = StdioServerParameters(
            command=declared["command"],
            args=declared["args"],
            cwd=str((root / declared["cwd"]).resolve()),
            env=env,
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()
            assert "humanize_run" in {tool.name for tool in (await client.list_tools()).tools}
            assert not (await client.call_tool("humanize_doctor", {})).isError

    asyncio.run(exercise())


def test_wait_sends_protocol_progress_without_exposing_task(tmp_path):
    job_id = "b" * 32
    root = tmp_path / "runs" / job_id
    atomic_json(root / "request.json", prepare(str(tmp_path), "PRIVATE_TASK"))
    atomic_json(
        root / "state.json",
        {
            "job_id": job_id,
            "status": "running",
            "created": time.time(),
            "heartbeat": time.time(),
        },
    )
    atomic_json(root / "progress.json", {"stage": "acting", "round": 1, "revision": 2})

    async def exercise():
        messages = []

        async def progress(value, total, message):
            messages.append((value, total, message))

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "humanize_codex.cli", "serve"],
            env={**os.environ, "HUMANIZE_CODEX_DATA": str(tmp_path)},
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as client:
            await client.initialize()
            response = await client.call_tool(
                "humanize_wait",
                {
                    "job_id": job_id,
                    "seconds": 0.25,
                },
                progress_callback=progress,
            )
            assert not response.isError
            assert messages and messages[0] == (2, None, "acting · round 1")
            assert "PRIVATE_TASK" not in str(messages)

    asyncio.run(exercise())
