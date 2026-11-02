"""Record package versions for CI diagnosis, without credentials or machine configuration."""

import importlib.metadata
import json
import os
import platform
from pathlib import Path


def main() -> None:
    report = {
        "requested_hmz": os.environ.get("HMZ_LATEST_VERSION"),
        "python": platform.python_version(),
        "platform": platform.system(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("hmz", "humanfia-humanize-codex", "mcp", "psutil")
        },
    }
    text = json.dumps(report, indent=2) + "\n"
    Path("compatibility-report.json").write_text(text, encoding="utf-8")
    print(text, end="")
    if report["requested_hmz"] is not None and report["requested_hmz"] != report["packages"]["hmz"]:
        raise SystemExit("Resolved hmz does not match the current upstream release")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write("### Latest Humanize compatibility\n\n```json\n" + text + "```\n")


if __name__ == "__main__":
    main()
