"""Resolve the local CLI default through its actual app-server configuration."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from typing import Any


def default_agent() -> str:
    """Read configuration and model availability without starting a model turn.

    Honor an explicitly configured model. Never silently substitute for an explicitly
    requested model; this resolver is used only for the plugin's empty/automatic setting.
    """
    child = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    assert child.stdin is not None and child.stdout is not None
    messages: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def read() -> None:
        try:
            for line in child.stdout:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            messages.put(None)

    def send(value: dict[str, Any]) -> None:
        child.stdin.write(json.dumps(value) + "\n")
        child.stdin.flush()

    threading.Thread(target=read, daemon=True).start()
    config = None
    models = None
    deadline = time.monotonic() + 15
    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "humanize-model-resolution", "version": "0.1.0"},
                },
            }
        )
        while time.monotonic() < deadline:
            try:
                message = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if message is None:
                break
            if message.get("id") == 1:
                if "error" in message:
                    raise ValueError("Codex app-server initialization failed")
                send({"method": "initialized"})
                send({"id": 2, "method": "config/read", "params": {"includeLayers": False}})
                send({"id": 3, "method": "model/list", "params": {"includeHidden": False}})
            elif message.get("id") == 2:
                config = message.get("result", {}).get("config", {})
            elif message.get("id") == 3:
                models = message.get("result", {}).get("data", [])
            if config is not None and models is not None:
                configured = config.get("model")
                model = configured or next(
                    (item.get("model") for item in models if item.get("isDefault")),
                    None,
                )
                if not model:
                    raise ValueError("Codex offered no default model; explicitly supply agent")
                effort = config.get("model_reasoning_effort") or "high"
                return f"codex/{model}:{effort}"
        raise ValueError("Could not resolve the local Codex default; explicitly supply agent")
    finally:
        child.terminate()
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        child.stdin.close()
        child.stdout.close()
