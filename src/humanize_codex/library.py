"""Private, evidence-gated flow recipes; exports never include task histories."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import semver
import yaml

from .store import atomic_json, job_path, locked, read_json


def snapshot(source: Path, entrypoint: str = "") -> bytes:
    """Freeze a trusted self-contained flow without importing or executing it."""
    content = source.read_bytes()
    if len(content) > 1024 * 1024:
        raise ValueError("A managed flow must be a self-contained Python file under 1 MiB")
    tree = ast.parse(content, filename=source.name)
    entries = {node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)}
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call):
                    entries.update(
                        k.value.value
                        for k in decorator.keywords
                        if k.arg == "name"
                        and isinstance(k.value, ast.Constant)
                        and isinstance(k.value.value, str)
                    )
    if entrypoint and entrypoint not in entries:
        raise ValueError(f"No async flow entrypoint {entrypoint!r}")
    if not entrypoint and not {"dynamic_workflow", "read_only_workflow"} <= entries:
        raise ValueError("A managed flow must export dynamic_workflow and read_only_workflow")
    if any(isinstance(node, ast.ImportFrom) and node.level for node in ast.walk(tree)):
        raise ValueError(
            "Managed flows must be self-contained; relative imports cannot be retained"
        )
    return content


def _name(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
        raise ValueError("flow name must match [a-z][a-z0-9_]*, at most 64 characters")
    return name


class Library:
    """Keep code and reusable settings, with local observations separate from exports."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "library"

    def source(self, name: str) -> Path:
        profile = self.get(name)
        source = self.directory / _name(name) / "__init__.py"
        if hashlib.sha256(source.read_bytes()).hexdigest() != profile["source_sha256"]:
            raise ValueError("Saved flow changed; review and run it before retaining a new version")
        return source

    def get(self, name: str) -> dict[str, Any]:
        path = self.directory / _name(name) / "flow.json"
        if not path.is_file():
            raise ValueError(f"Unknown retained flow: {name}")
        profile = read_json(path)
        profile.setdefault("curation", {"status": "candidate", "reason": "Not yet assessed"})
        return profile

    def list(self) -> list[dict[str, Any]]:
        return [self.get(path.parent.name) for path in sorted(self.directory.glob("*/flow.json"))]

    def retain(self, job_id: str, name: str = "", description: str = "") -> dict[str, Any]:
        path = job_path(self.root, job_id)
        state, request = read_json(path / "state.json"), read_json(path / "request.json")
        result = state.get("result", {})
        if (
            state["status"] != "complete"
            or result.get("action") != "complete"
            or not result.get("evidence")
        ):
            raise ValueError(
                "Only a completed flow with independent review evidence can be retained"
            )
        if len(description) > 2000:
            raise ValueError("description must be at most 2000 characters")
        content = snapshot(path / "workflow.py", request.get("entrypoint", ""))
        source_hash = hashlib.sha256(content).hexdigest()
        settings = {
            "mode": request["mode"],
            "read_only": request["read_only"],
            "max_rounds": request["max_rounds"],
            "agents": state.get("agents")
            or {
                role: request.get("agents", {}).get(role) or request["agent"]
                for role in request.get("role_names", ("planner", "actor", "reviewer", "observer"))
            },
        }
        if request.get("entrypoint"):
            settings["entrypoint"] = request["entrypoint"]
        fingerprint = hashlib.sha256(
            (source_hash + json.dumps(settings, sort_keys=True)).encode()
        ).hexdigest()
        selected = _name(name or f"flow_{fingerprint[:12]}")
        with locked(self.directory):
            target = self.directory / selected
            if (target / "flow.json").is_file():
                profile = self.get(selected)
                if profile["fingerprint"] != fingerprint:
                    raise ValueError("This name already identifies another flow; choose a new name")
            else:
                target.mkdir(parents=True, mode=0o700)
                (target / "__init__.py").write_bytes(content)
                profile = {
                    "format": "humanize-codex-flow-v1",
                    "name": selected,
                    "description": description or "Locally reviewed reusable workflow",
                    "fingerprint": fingerprint,
                    "source_sha256": source_hash,
                    "settings": settings,
                    "created": time.time(),
                    "successes": 0,
                    "observations": {},
                    "curation": {
                        "status": "candidate",
                        "reason": "Reviewed task success; flow reuse value has not been assessed",
                    },
                }
            if job_id not in profile["observations"]:
                profile["observations"][job_id] = {
                    "at": time.time(),
                    "usage": state.get("usage", {}),
                    "rounds": result.get("round"),
                }
                profile["successes"] += 1
            if description:
                profile["description"] = description
            profile["updated"] = time.time()
            atomic_json(target / "flow.json", profile)
        return profile

    def curate(
        self,
        name: str,
        verdict: str,
        rationale: str,
        use_when: list[str],
        avoid_when: list[str],
        validation_id: str = "",
    ) -> dict[str, Any]:
        """Separate an agent's reuse assessment from deterministic test/run evidence."""
        if verdict not in {"promote", "reject", "needs_evidence"} or not rationale.strip():
            raise ValueError("Supply promote/reject/needs_evidence and a reason")
        with locked(self.directory):
            profile = self.get(name)
            if verdict == "promote":
                if (
                    not use_when
                    or not avoid_when
                    or not all(isinstance(x, str) and x.strip() for x in [*use_when, *avoid_when])
                ):
                    raise ValueError("Promotion requires applicability and limitations")
                if not re.fullmatch(r"[a-f0-9]{32}", validation_id):
                    raise ValueError("Promotion requires a flow validation receipt")
                receipt = read_json(self.root / "validations" / validation_id / "receipt.json")
                entry = profile["settings"].get("entrypoint") or (
                    "read_only_workflow" if profile["settings"]["read_only"] else "dynamic_workflow"
                )
                if (
                    receipt.get("status") != "passed"
                    or len(receipt.get("cases", [])) < 2
                    or any(c.get("status") != "passed" for c in receipt.get("cases", []))
                    or len({c.get("scenario") for c in receipt.get("cases", [])}) < 2
                    or receipt.get("source_sha256") != profile["source_sha256"]
                    or receipt.get("entrypoint") != entry
                ):
                    raise ValueError(
                        "Need at least two passing cases for this exact code and entry"
                    )
                self.source(name)  # Refuse code modified since the tested snapshot.
            profile["curation"] = {
                "status": {
                    "promote": "curated",
                    "reject": "rejected",
                    "needs_evidence": "candidate",
                }[verdict],
                "rationale": rationale,
                "use_when": use_when,
                "avoid_when": avoid_when,
                "validation_id": validation_id,
                "assessed": time.time(),
                "assessment": "Agent judgment, backed by observed runs and scripted cases; "
                "not a general performance guarantee",
            }
            atomic_json(self.directory / _name(name) / "flow.json", profile)
            return profile

    def export(
        self, name: str, destination: str, version: str = "0.1.0", allow_candidate: bool = False
    ) -> dict[str, Any]:
        """Write an immutable source release, separately from its Flowverse index."""
        semver.Version.parse(version)
        root = Path(destination).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("destination must be an existing absolute local checkout/directory")
        profile = self.get(name)
        if profile["curation"]["status"] == "rejected":
            raise ValueError("This flow was rejected; reassess it before exporting")
        if profile["curation"]["status"] != "curated" and not allow_candidate:
            raise ValueError(
                "Only curated flows export by default; explicitly allow a candidate trial"
            )
        source = self.source(name)
        subdir = Path("bundles") / _name(name) / version / name
        target = root.resolve() / subdir
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Export path resolves outside destination")
        if target.exists():
            raise ValueError("Export target exists; inspect it or choose a new flow name")
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".flow-export-", dir=parent))
        try:
            # Humanize resolves installed flows by their directory's name.
            entry = profile["settings"].get("entrypoint") or (
                "read_only_workflow" if profile["settings"]["read_only"] else "dynamic_workflow"
            )
            tree = ast.parse(source.read_bytes())
            named_entry = next(
                node
                for node in tree.body
                if isinstance(node, ast.AsyncFunctionDef)
                and (
                    node.name == entry
                    or any(
                        isinstance(d, ast.Call)
                        and any(
                            k.arg == "name"
                            and isinstance(k.value, ast.Constant)
                            and k.value.value == entry
                            for k in d.keywords
                        )
                        for d in node.decorator_list
                    )
                )
            )
            named_entry.name = name
            for decorator in named_entry.decorator_list:
                if isinstance(decorator, ast.Call):
                    for keyword in decorator.keywords:
                        if keyword.arg == "name":
                            keyword.value = ast.Constant(name)
            exported_source = (
                source.read_bytes()
                + (
                    "\n# Named entry for Flowverse installation.\n"
                    + ast.unparse(named_entry)
                    + "\n"
                ).encode()
            )
            (temporary / "__init__.py").write_bytes(exported_source)
            exported = {
                key: profile[key]
                for key in (
                    "format",
                    "name",
                    "description",
                    "source_sha256",
                    "settings",
                    "successes",
                    "curation",
                )
            }
            exported["retained_source_sha256"] = exported["source_sha256"]
            exported["source_sha256"] = hashlib.sha256(exported_source).hexdigest()
            # Local validation identifiers are not part of a public source release.
            exported["curation"].pop("validation_id", None)
            atomic_json(temporary / "flow.json", exported)
            (temporary / "README.md").write_text(
                f"# {name}\n\n{profile['description']}\n\n"
                "Self-contained Humanize source bundle (hmz 0.2.1).\n"
                f"Select `:{name}`; original entry: {entry}. Role settings are in flow.json.\n"
                "Local successes are observations, not a cross-task benchmark.\n"
                "No task prompts, review transcripts or credentials are exported.\n"
                "Generate a pinned flow.yaml in a separate Flowverse index after committing\n"
                "this source bundle. Keep private tasks and credentials out of both repos.\n",
                encoding="utf-8",
            )
            temporary.rename(target)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return {
            "name": name,
            "version": version,
            "path": str(target),
            "subdir": subdir.as_posix(),
            "published": False,
        }

    def index(
        self,
        name: str,
        version: str,
        destination: str,
        repo: str,
        commit: str,
        subdir: str,
        ref: str = "",
        license: str = "Apache-2.0",
    ) -> dict[str, Any]:
        """Generate the current Humanize index schema; no fetch, install, commit or push."""
        from hmz.runtime.flowing.index import Release

        profile = self.get(name)
        if profile["curation"]["status"] != "curated":
            raise ValueError("Only curated flows may be indexed for reuse")
        if "://" in repo:
            parsed = urlsplit(repo)
            if (
                parsed.password
                or parsed.query
                or parsed.fragment
                or (parsed.username and parsed.scheme != "ssh")
            ):
                raise ValueError(
                    "Repository URLs must not contain credentials or access parameters"
                )
        release = Release(
            name=_name(name),
            version=version,
            repo=repo,
            ref=ref,
            commit=commit,
            subdir=subdir,
            license=license,
            description=profile["description"].replace("\n", " "),
        )
        root = Path(destination).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("destination must be an existing absolute Flowverse index checkout")
        target = root.resolve() / "flows" / name / release.version / "flow.yaml"
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Index path resolves outside destination")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = release.model_dump(exclude={"owner", "dependencies"})
        with target.open("x", encoding="utf-8") as stream:
            yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
        return {
            "path": str(target),
            "manifest": data,
            "published": False,
            "source_verified": False,
            "next": "Verify/install the pinned source before publishing this index",
        }
