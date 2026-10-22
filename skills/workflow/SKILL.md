---
name: humanize-workflow
description: Run an explicitly requested Humanize adaptive workflow in Codex, with Codex/DSH role assignments, an independent status observer and reusable successful flows.
---

# Humanize workflow

Use the real Humanize runtime through `humanize_*` MCP tools. Python branches decide the
next stage; the flow-owned observer handles dashboard narration in its separate session.

1. Inspect the objective, applicable AGENTS.md, worktree changes and verifiable acceptance
   criteria. Preserve the user's authorized scope and protected processes.
2. Check `humanize_doctor(workspace=...)` if readiness is unknown. Resolve prerequisites with
   the setup skill. Never expose credential values. DSH uses its own account/environment.
3. Inspect `humanize_library` for a relevant retained flow. Choose based on code, applicability
   and observed evidence, not success counts alone. Reuse with `humanize_reuse_flow`, or start
   `humanize_run` with the absolute workspace and complete task, constraints and validation.
   This explicitly requested workflow delegates to planner, actor, reviewer and observer.
   Use `read_only=true` for analysis/review-only tasks. Set agents per role when useful and
   authorized; otherwise follow local Codex. Explicit models never silently fall back.
4. Call `humanize_dashboard` once and share/open the returned read-only URL. The flow's
   observer owns progress summaries; runtime records supply exact phases, budgets and
   heartbeat. Do not ask the main execution agent to inspect logs, poll status or maintain
   the dashboard. Do not duplicate every stage update in the parent conversation.
5. The worker owns the workspace. Do not edit the same files or start overlapping workflows.
   Wait with `humanize_wait` up to 60 seconds per call until terminal; omit after_revision
   during normal operation so stage changes do not repeatedly consume parent attention.
   Use status/events for an actual user question, troubleshooting or control receipts.
   Tell the user about required decisions, material failure and final results; the dashboard
   covers ordinary progress. Launching is not completion evidence.
6. Forward corrections with `humanize_steer`. Check receipts; queued is not delivered.
   The observer never receives implementation steering. DSH may accept guidance only next
   turn. On an explicit stop, cancel and verify terminal; never automatically resume it.
7. `complete` requires independent review evidence. blocked/round_limit/budget_exceeded/
   failed/lost/cancelled mean unfinished. Verify important claims and report actual results,
   checks, limits and useful artifacts. Resume only within continued authorization/budget.
8. Reviewed complete flows are automatically retained privately. Name particularly reusable
   ones with `humanize_save_flow` and an honest description of applicability. Never include
   task secrets in descriptions/source. Export/version/index through the author skill when
   useful; saving locally does not authorize publishing a flow or its traces.

Defaults: six rounds, 30 minutes, 50,000 output tokens shared by all roles. Honor user limits.
Do not publish, send messages, spend beyond authorization or operate hardware without the
user's permission. Preserve dirty worktree changes. Do not recursively launch Humanize.
