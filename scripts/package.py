"""Build a clean local marketplace and distributable archive without user/runtime data."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

INCLUDE = [
    "plugin.json",
    "mcp.json",
    ".mcp.json",
    ".codex-plugin",
    ".agents",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "LICENSE",
    "NOTICE",
    "VALIDATION.md",
    "skills",
    "scripts",
    "src",
    "tests",
    ".gitignore",
]


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    output = root / "output"
    marketplace = output / "marketplace"
    plugin = marketplace / "plugins/humanfia-humanize"
    if plugin.exists():
        shutil.rmtree(plugin)
    plugin.mkdir(parents=True)
    for name in INCLUDE:
        source = root / name
        target = plugin / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target)
    catalog = marketplace / ".agents/plugins/marketplace.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads((root / ".agents/plugins/marketplace.json").read_text())
    data["plugins"][0]["source"]["path"] = "./plugins/humanfia-humanize"
    catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    version = json.loads((root / "plugin.json").read_text())["version"]
    archive = output / f"humanfia-humanize-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for file in sorted(marketplace.rglob("*")):
            if file.is_file():
                zipped.write(file, file.relative_to(marketplace))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    print(
        json.dumps(
            {
                "marketplace": str(marketplace),
                "archive": str(archive),
                "bytes": archive.stat().st_size,
                "sha256": digest,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
