"""The live view is local, read-only and does not expose task transcripts."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from humanize_codex.dashboard import make_server, public_state


def test_dashboard_projection_omits_tasks_and_transcripts():
    shown = public_state(
        {
            "job_id": "a" * 32,
            "status": "running",
            "request": {
                "task": "PRIVATE",
                "workspace": "/tmp/work",
                "budget": {},
                "mode": "dynamic",
                "read_only": False,
            },
            "result": {"actor_summary": "PRIVATE", "evidence": ["tested"]},
        }
    )
    assert "PRIVATE" not in json.dumps(shown)
    assert shown["evidence"] == ["tested"]


def test_dashboard_is_live_and_rejects_wrong_token_host_origin_and_writes(tmp_path):
    server = make_server(tmp_path, "a" * 64)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    route = "/" + "a" * 64 + "/"
    try:
        with urllib.request.urlopen(base + route) as response:
            assert b"fetch('api'" in response.read()
            assert response.headers["Cache-Control"] == "no-store"
        with urllib.request.urlopen(base + route + "api") as response:
            assert json.load(response) == {"jobs": []}
        for path, headers, method, status in [
            ("/wrong/api", {}, "GET", 404),
            (route + "api", {"Host": "attacker.example"}, "GET", 403),
            (route + "api", {"Origin": "https://attacker.example"}, "GET", 403),
            (route + "api", {}, "POST", 501),
        ]:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(
                    urllib.request.Request(base + path, headers=headers, method=method)
                )
            assert error.value.code == status
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
