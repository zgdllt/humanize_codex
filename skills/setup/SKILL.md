---
name: humanize-setup
description: Set up or diagnose the Humanfia Humanize Codex plugin, its Python runtime and local workflow tools.
---

# Set up Humanfia Humanize

1. Call the plugin's `humanize_doctor` tool. Check the hmz version, MCP version, Python and
   `codex` path, Humanize app/tmux availability, and DSH SDK/auth readiness. Pure DSH jobs do not require a Codex CLI. Do not print, copy or rewrite credential values. DSH readiness is reported as a boolean.
2. The plugin launcher reads PyPI's current default `hmz` release and requires that exact
   version with the DSH extra in an isolated, cached `uv tool` environment. `uv.lock` records
   the development baseline; it does not pin plugin launches. Existing processes and the
   user's global hmz installation keep their environments. Python 3.14 is selected for the
   tested dependency set. Launch requires access to PyPI; the first launch or an upstream
   update may download dependencies. If `uv` is missing, inspect the official
   installation instructions at https://docs.astral.sh/uv/getting-started/installation/ and
   install it within the user's authorized local setup scope.
3. If MCP is not yet connected, run `python3 <plugin-root>/scripts/launch.py doctor` using the
   actual plugin root supplied by the host. If Codex is missing or signed out, report the
   required local install/login step. OAuth may require the user to complete sign-in.
4. Reconnect the plugin or open a new chat after installation so its tools and skills load.
5. Verify tool discovery and call `humanize_catalog`. Do not start a real, paid/model-backed
   coding workflow solely to check setup unless such a smoke test was authorized.

Use the workflow skill for execution and the author-flow skill for custom Python workflows.
This is the Humanfia project at https://humanfia.ai/projects/humanize, not the legacy RLCR
skill bundle. Source: https://github.com/humanfia/humanize. License: Apache-2.0.

Desktop runs open the installed Humanize app. SSH or terminal runs require tmux and use the upstream Humanize TUI bound to the job host. If tmux is missing, report it before starting a flow.
