"""The same tools are available from a terminal for setup and reproducible diagnostics."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .jobs import DEFAULT_AGENT, Jobs, doctor, prepare
from .library import Library
from .store import TERMINAL, data_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Humanfia Humanize Codex plugin")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "doctor", "list", "library", "dashboard", "dashboard-worker"):
        sub.add_parser(name)
    for name in (
        "worker",
        "status",
        "cancel",
        "events",
        "wait",
        "resume",
        "steer",
        "watch",
        "save",
    ):
        item = sub.add_parser(name)
        item.add_argument("job_id")
        if name in {"steer", "resume"}:
            item.add_argument("text", nargs="?", default="")
        if name == "wait":
            item.add_argument("--seconds", type=float, default=30)
        if name == "save":
            item.add_argument("--name", default="")
            item.add_argument("--description", default="")
    item = sub.add_parser("export")
    item.add_argument("name")
    item.add_argument("destination")
    item.add_argument("--version", default="0.1.0")
    item = sub.add_parser("reuse")
    item.add_argument("name")
    item.add_argument("--workspace", required=True)
    item.add_argument("--task-file", required=True)
    item.add_argument("--duration", type=float, default=1800)
    item = sub.add_parser("run")
    item.add_argument("--workspace", required=True)
    item.add_argument("--task-file", required=True)
    item.add_argument("--mode", choices=["dynamic", "review"], default="dynamic")
    item.add_argument("--agent", default=DEFAULT_AGENT)
    item.add_argument("--max-rounds", type=int, default=6)
    item.add_argument("--duration", type=float, default=1800)
    item.add_argument("--read-only", action="store_true")
    item.add_argument("--role", action="append", default=[], metavar="ROLE=SPEC")
    item.add_argument("--flow-file", default="")
    item.add_argument("--no-retain", action="store_true")
    args = parser.parse_args()
    if args.command == "serve":
        from .server import mcp

        mcp.run(transport="stdio")
        return
    if args.command == "worker":
        from .worker import work

        work(args.job_id)
        return
    if args.command == "dashboard-worker":
        from .dashboard import serve_dashboard

        serve_dashboard()
        return
    jobs = Jobs()
    if args.command == "doctor":
        result = doctor()
    elif args.command == "run":
        result = jobs.start(
            prepare(
                args.workspace,
                Path(args.task_file).read_text(encoding="utf-8"),
                args.mode,
                args.agent,
                args.max_rounds,
                args.duration,
                read_only=args.read_only,
                agents=dict(spec.split("=", 1) for spec in args.role),
                flow_file=args.flow_file,
                retain_flow=not args.no_retain,
            )
        )
    elif args.command == "list":
        result = jobs.list()
    elif args.command == "library":
        result = Library(data_root()).list()
    elif args.command == "save":
        result = Library(data_root()).retain(args.job_id, args.name, args.description)
    elif args.command == "export":
        result = Library(data_root()).export(args.name, args.destination, args.version)
    elif args.command == "reuse":
        result = jobs.reuse(
            args.name, args.workspace, Path(args.task_file).read_text(), args.duration
        )
    elif args.command == "dashboard":
        from .dashboard import ensure_dashboard

        result = ensure_dashboard()
    elif args.command == "watch":
        previous, notified = "", 0.0
        while True:
            state = jobs.status(args.job_id)
            if state["revision"] != previous or time.monotonic() - notified >= 10:
                print(
                    json.dumps(
                        {
                            key: state.get(key)
                            for key in (
                                "job_id",
                                "status",
                                "progress",
                                "elapsed_seconds",
                                "remaining_seconds",
                                "agents",
                                "usage",
                                "last_activity",
                            )
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                previous, notified = state["revision"], time.monotonic()
            if state["status"] in TERMINAL:
                break
            time.sleep(0.5)
        result = state
    elif args.command in {"cancel", "steer"}:
        result = jobs.control(args.job_id, args.command, getattr(args, "text", ""))
    elif args.command == "wait":
        result = jobs.wait(args.job_id, args.seconds)
    elif args.command == "resume":
        result = jobs.resume(args.job_id, args.text)
    elif args.command == "events":
        result = jobs.events(args.job_id)
    else:
        result = jobs.status(args.job_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
