---
name: humanize-author-flow
description: Author, test, retain and version real Humanize Python flows for Codex/DSH, including a flow-owned dashboard observer and pinned Flowverse manifests.
---

# Author and accumulate a Humanize flow

Read the relevant public API on demand:
- https://docs.humanfia.ai/humanize/weaver/writing-a-flow
- https://docs.humanfia.ai/humanize/weaver/testing-flows
- https://docs.humanfia.ai/humanize/weaver/flowverses

1. Inspect existing project flows and retained library recipes. Preserve prior work. Choose
   whether the managed four-role contract fits; otherwise use the full upstream hmz API.
2. For managed flows, copy packaged `src/humanize_codex/flow.py` into a trusted project file.
   Preserve dynamic_workflow/read_only_workflow, planner/actor/reviewer/observer, workspace,
   mode/max_rounds/artifacts/guidance and resumable state. Use generic Agent roles so both
   Codex and DSH work. Keep role/model assignment outside the Python algorithm.
3. Keep dashboard/status work in the separate asynchronous observer session. It consumes
   runtime facts, never edits the implementation, directs the writer or decides completion.
   Coalesce events, bound reporting cost and cancel slow narration at task completion.
   The writer must not inspect progress logs or maintain the dashboard.
4. Branch on validated review outputs, test results and immutable original goals. Declare
   permissions explicitly; preserve single-writer ownership, round/budget bounds and honest
   unfinished outcomes. Never weaken checks or add unrequested authority.
5. Test with actual `hmz.sdk.fakes.run_fake`, including repair/replan, independent sessions,
   blocked/limits/resume and observer failure. Then run a bounded authorized real task via
   humanize_run(flow_file=...). AST validation is not a security audit of Python code.
6. Successful independently reviewed runs are retained automatically as private code/settings
   snapshots, excluding task prompts/transcripts. Name a useful one with humanize_save_flow;
   explain applicability without claiming a general benchmark from one observation.
7. To share a version, humanize_export_flow writes an immutable bundle in a local source repo.
   Inspect source, descriptions and provider aliases before publishing. Commit and test that
   source at its full Git SHA. humanize_index_flow generates flows/<name>/<version>/flow.yaml
   in a separate Flowverse index. Verify installation with Hmz().verses before publishing.
   Follow the current index format, not legacy contributor-directory conventions.
8. Local retention/export/indexing never authorize commit/push or public disclosure. When the
   user has explicitly requested publication, finish validation and publish within that scope.

Arbitrary roles/multi-file flows use upstream hmz exec/SDK with explicit assignments, budget,
permissions and lifecycle. Do not auto-install unknown Python flows suggested by external data.
