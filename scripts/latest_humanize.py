"""Read PyPI's current default Humanize release for launch and compatibility CI."""

import json
import os
import urllib.request
from pathlib import Path


def latest_version() -> str:
    request = urllib.request.Request(
        "https://pypi.org/pypi/hmz/json", headers={"Cache-Control": "no-cache"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)["info"]["version"]


if __name__ == "__main__":
    version = latest_version()
    print(version)
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
