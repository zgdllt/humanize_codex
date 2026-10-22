"""Read-only live dashboard on loopback, protected by an unguessable local URL."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .store import TERMINAL, atomic_json, data_root, locked, read_json


def _url(record: dict) -> str:
    port, token = record.get("port"), record.get("token", "")
    if (
        not isinstance(port, int)
        or not 0 < port < 65536
        or not isinstance(token, str)
        or not re.fullmatch(r"[a-f0-9]{64}", token)
    ):
        raise ValueError("Invalid local dashboard descriptor")
    return f"http://127.0.0.1:{port}/{token}/"


def _healthy(record: dict) -> bool:
    try:
        with urllib.request.urlopen(_url(record) + "health", timeout=0.5) as response:
            return json.load(response) == {"ok": True, "version": __version__}
    except (OSError, ValueError, urllib.error.URLError):
        return False


def ensure_dashboard(root: Path | None = None) -> dict[str, Any]:
    root = root or data_root()
    directory = root / "dashboard"
    with locked(directory):
        descriptor = directory / "server.json"
        try:
            record = read_json(descriptor) if descriptor.is_file() else {}
        except (ValueError, OSError):
            record = {}
        if not _healthy(record):
            record = {"token": secrets.token_hex(32), "port": 0}
            atomic_json(descriptor, record)
            env = {**os.environ, "HUMANIZE_CODEX_DATA": str(root)}
            with (directory / "server.log").open("ab") as log:
                subprocess.Popen(
                    [sys.executable, "-m", "humanize_codex.cli", "dashboard-worker"],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                record = read_json(descriptor)
                if _healthy(record):
                    break
                time.sleep(0.1)
            else:
                raise ValueError("Local dashboard did not start; inspect dashboard/server.log")
    return {"url": _url(record), "read_only": True, "refresh_seconds": 1}


def public_state(state: dict) -> dict:
    """Show useful progress; omit task prompts, transcripts and credential configuration."""
    request = state["request"]
    return {
        key: state.get(key)
        for key in (
            "job_id",
            "status",
            "created",
            "finished",
            "progress",
            "elapsed_seconds",
            "remaining_seconds",
            "usage",
            "last_activity",
            "agents",
            "retained_flow",
            "report",
            "active_agents",
            "retention_class",
        )
    } | {
        "flow": {
            k: state.get("flow", {}).get(k)
            for k in ("entrypoint", "structures", "description", "structure_note")
        },
        "workspace": request["workspace"],
        "budget": request["budget"],
        "mode": request["mode"],
        "read_only": request["read_only"],
        "evidence": state.get("result", {}).get("evidence", []),
    }


def make_server(root: Path, token: str) -> ThreadingHTTPServer:
    from .jobs import Jobs

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (
                self.headers.get("Host") != origin.removeprefix("http://")
                or self.headers.get("Origin", origin) != origin
            ):
                self.send_error(403)
                return
            route = self.path.partition("?")[0]
            base = f"/{token}/"
            if route == base:
                content = Path(__file__).with_name("dashboard.html").read_bytes()
                kind = "text/html; charset=utf-8"
            elif route == base + "health":
                content = json.dumps({"ok": True, "version": __version__}).encode()
                kind = "application/json"
            elif route == base + "api":
                try:
                    selected = parse_qs(urlsplit(self.path).query).get("job", [None])[0]
                    states = [Jobs(root).status(selected)] if selected else Jobs(root).list()[:100]
                    content = json.dumps({"jobs": [public_state(s) for s in states]}).encode()
                except (ValueError, OSError):
                    self.send_error(503, "Progress records temporarily unavailable")
                    return
                kind = "application/json"
            else:
                self.send_error(404)
                return
            self.server.last_request = time.monotonic()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.last_request = time.monotonic()
    return server


def serve_dashboard() -> None:
    root = data_root()
    descriptor = root / "dashboard/server.json"
    record = read_json(descriptor)
    with make_server(root, record["token"]) as server:
        atomic_json(descriptor, {**record, "port": server.server_port})
        server.timeout = 2
        while True:
            server.handle_request()
            if time.monotonic() - server.last_request > 3600:
                from .jobs import Jobs

                if all(s["status"] in TERMINAL for s in Jobs(root).list()):
                    break
