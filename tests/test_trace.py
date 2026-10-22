"""Timing must survive transcript noise, partial writes, reused sessions and stopped runs."""

import json
import os

from humanize_codex.trace import read_trace


def append(path, *events):
    with (path / "events.jsonl").open("a", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")


def event(kind, at, session="one", role="actor"):
    return {"kind": kind, "at": at, "session": session, "role": role}


def test_concurrent_sessions_and_repeated_turns_have_independent_spans(tmp_path):
    state = {"created": 1, "status": "running"}
    append(tmp_path, event("begins", 2), event("begins", 3, "two"))
    first = read_trace(tmp_path, state)
    assert len(first["spans"]) == 2
    append(
        tmp_path,
        event("ends", 4, "two"),
        event("ends", 5),
        event("begins", 6),
        event("ends", 7),
    )
    result = read_trace(tmp_path, state)
    assert [(s["start"], s["end"]) for s in result["spans"]] == [(2, 5), (3, 4), (6, 7)]
    assert first["spans"][0]["end"] is None  # Snapshots cannot mutate after a refresh.


def test_noisy_transcript_cannot_evict_a_turn_start(tmp_path):
    append(tmp_path, event("begins", 2))
    append(tmp_path, *({"at": 3, "kind": "text", "text": "PRIVATE"} for _ in range(400)))
    append(tmp_path, event("ends", 5))
    result = read_trace(tmp_path, {"status": "complete", "created": 1, "finished": 6})
    assert [(s["start"], s["end"]) for s in result["spans"]] == [(2, 5)]
    assert "PRIVATE" not in json.dumps(result)


def test_partial_event_retried_and_replaced_log_resets_projection(tmp_path):
    file = tmp_path / "events.jsonl"
    append(tmp_path, event("begins", 2))
    pending = json.dumps(event("ends", 4))
    with file.open("a") as stream:
        stream.write(pending[:15])
    assert read_trace(tmp_path, {"status": "running"})["spans"][0]["end"] is None
    with file.open("a") as stream:
        stream.write(pending[15:] + "\n")
    assert read_trace(tmp_path, {"status": "running"})["spans"][0]["end"] == 4
    replacement = tmp_path / "replacement"
    replacement.write_text(json.dumps(event("begins", 8)) + "\n")
    replacement.replace(file)
    result = read_trace(tmp_path, {"status": "running"})
    assert len(result["spans"]) == 1
    assert result["spans"][0]["start"] == 8


def test_stopped_and_lost_runs_freeze_incomplete_spans(tmp_path):
    append(tmp_path, event("begins", 2))
    cancelled = read_trace(
        tmp_path, {"status": "cancelled", "created": 1, "finished": 8, "heartbeat": 7}
    )
    assert cancelled["spans"][0]["end"] == 8
    assert cancelled["spans"][0]["interrupted"]
    lost = read_trace(tmp_path, {"status": "lost", "created": 1, "heartbeat": 6})
    assert lost["finished"] == lost["spans"][0]["end"] == 6


def test_equal_length_inplace_rewrite_invalidates_cached_projection(tmp_path):
    append(tmp_path, event("begins", 2))
    assert read_trace(tmp_path, {"status": "running"})["spans"][0]["start"] == 2
    file = tmp_path / "events.jsonl"
    stat = file.stat()
    file.write_text(json.dumps(event("begins", 8)) + "\n")
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
    assert file.stat().st_size == stat.st_size
    assert read_trace(tmp_path, {"status": "running"})["spans"][0]["start"] == 8


def test_old_records_are_labeled_and_malformed_lines_ignored(tmp_path):
    append(
        tmp_path,
        [],
        {"kind": "begins", "at": "invalid"},
        {"kind": "begins", "at": float("nan")},
        {"kind": "begins", "at": 2, "role": "actor"},
        {"kind": "ends", "at": 4, "role": "actor"},
    )
    result = read_trace(tmp_path, {"status": "running"})
    assert len(result["spans"]) == 1
    assert result["spans"][0]["approximate"]
    assert result["spans"][0]["end"] == 4
