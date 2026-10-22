"""Incrementally project runtime events without exposing model or tool output."""

from __future__ import annotations

import json
import math
import os
import threading
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

from .store import TERMINAL


class _Reader:
    def __init__(self, path: Path):
        self.path = path
        self.guard = threading.Lock()
        self.identity = None
        self.stamp = None
        self.offset = 0
        self.spans = deque(maxlen=320)
        self.facts = deque(maxlen=60)
        self.open = defaultdict(deque)
        self.count = 0
        self.latest = 0

    def _consume(self, item: object, offset: int) -> None:
        if not isinstance(item, dict):
            return
        at, role, kind = item.get("at"), item.get("role", ""), item.get("kind")
        if (
            isinstance(at, bool)
            or not isinstance(at, int | float)
            or not math.isfinite(at)
            or not isinstance(role, str)
            or not isinstance(kind, str)
        ):
            return
        self.latest = max(self.latest, at)
        session = str(item.get("session") or "")
        key = (session, role)
        if kind == "begins":
            span = {"id": offset, "role": role, "start": at, "end": None}
            if not session:
                span["approximate"] = True  # Old workers did not record session IDs.
            self.open[key].append(span)
            self.spans.append(span)
            self.count += 1
        elif kind == "ends":
            pending = self.open.get(key)
            if pending:
                span = pending.popleft()
                span["end"] = max(span["start"], at)
                if not pending:
                    del self.open[key]
        elif kind in {"control_receipt", "flow_retained", "session_opened"}:
            self.facts.append({"at": at, "kind": kind, "role": role})

    def read(self, state: dict) -> dict:
        with self.guard:
            try:
                with self.path.open("rb") as stream:
                    stat = os.fstat(stream.fileno())
                    identity = (stat.st_dev, stat.st_ino)
                    if (
                        self.identity != identity
                        or stat.st_size < self.offset
                        or (stat.st_size == self.offset and stat.st_mtime_ns != self.stamp)
                    ):
                        self.identity, self.offset = identity, 0
                        self.spans.clear()
                        self.facts.clear()
                        self.open.clear()
                        self.count, self.latest = 0, 0
                    stream.seek(self.offset)
                    while raw := stream.readline():
                        if not raw.endswith(b"\n"):
                            break  # Retry a partially written event on the next refresh.
                        offset, self.offset = self.offset, stream.tell()
                        try:
                            self._consume(json.loads(raw), offset)
                        except (ValueError, UnicodeDecodeError):
                            continue
                    self.stamp = stat.st_mtime_ns
            except FileNotFoundError:
                pass
            finished = state.get("finished")
            if state.get("status") in TERMINAL and not finished:
                finished = max(state.get("heartbeat", 0), self.latest, state.get("created", 0))
            # Keep long-running spans even when newer completed turns leave the window.
            spans = {s["id"]: s for s in self.spans}
            spans.update((s["id"], s) for queue in self.open.values() for s in queue)
            shown = []
            for span in sorted(spans.values(), key=lambda s: (s["start"], s["id"])):
                row = dict(span)
                if row["end"] is None and finished is not None:
                    row.update(end=max(row["start"], finished), interrupted=True)
                shown.append(row)
            return {
                "spans": shown,
                "facts": list(self.facts),
                "created": state.get("created"),
                "finished": finished,
                "truncated": self.count > len(shown),
            }


@lru_cache(maxsize=128)
def _reader(path: Path) -> _Reader:
    return _Reader(path)


def read_trace(path: Path, state: dict) -> dict:
    """Read only appended bytes after the first visit; cache at most 128 run projections."""
    return _reader(path / "events.jsonl").read(state)
