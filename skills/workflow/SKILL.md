---
name: humanize-workflow
description: Use adaptive Python workflows when a task benefits from staged work, evidence-driven branching, bounded iteration, independent verification or parallel agents. Select proactively; handle simple tasks directly.
---

# Choose the right amount of workflow

Use Humanize when coordination provides a concrete benefit. The user need not name this
plugin. Handle a simple edit, answer or single check directly. For larger work, select the
control structure from the task: sequence, bounded loop, conditional branch, parallel fanout/
join, nested flows, or combinations. Do not force every task into an actor/reviewer loop.

1. Inspect the objective, applicable AGENTS.md, existing changes and completion evidence.
   Check runtime readiness when unknown. Keep model, permission and budget choices explicit.
2. Search `humanize_library` for applicable curated flows. Read use_when/avoid_when and code;
   success count alone is not a ranking. Candidates are hidden by default. Inspect them with
   include_candidates=true when assessing a potentially useful recipe.
3. Reuse a suitable curated flow, or author one through `humanize-author-flow`. Call
   `humanize_run` with flow_file, entrypoint, agents keyed by the flow's own declared roles,
   and flow_params for its inputs. The two built-in dynamic/review modes remain conveniences.
   They are templates, not the definition of dynamic workflow. For a simple candidate trial,
   allow_candidate=true is an explicit choice, not a claim that it has been curated.
4. The manager adds independent verification and native app/TUI visibility to generic flows.
   The authored Python decides its own internal sequence, loops, branches and concurrency.
   A verifier finding unfinished work produces needs_work; the manager does not secretly
   replace the authored structure with a repair loop. Decide the next bounded action from
   the evidence. No unapproved scope expansion or overlapping workspace writers.
5. humanize_run opens Humanize app on desktop or starts its official TUI in a named tmux
   session on SSH/terminal hosts. Immediately tell the user the returned app workspace/epic,
   or the tmux session and attach_command (switch_command inside tmux). The native UI owns
   live visibility of flows, agents, tool calls and costs. Do not maintain a dashboard or
   add a narration observer. humanize_open reopens an existing viewer without rerunning work.
   Wait at most 60 seconds per call and report required decisions and the final result.
6. Steer a generic flow by naming its task role. Untargeted guidance is stored for the flow;
   arbitrary Python must explicitly read it if needed. Check delivery receipts. Cancellation
   is complete only at terminal state; do not automatically resume a user-cancelled task.
7. Complete plus independent review evidence admits a flow to the private candidate pool.
   For useful recipes, assess reusability and limitations, test relevant control paths using
   humanize_validate_flow, then humanize_curate_flow. Promotion requires at least two passing
   scenarios for the exact code/entry and an applicability assessment. Reject brittle,
   task-bound or redundant candidates; more successful runs alone do not make a good flow.

Keep the original goal, user changes, protected processes and authorization boundaries.
Respect task-specific budgets. Sub-workflows cannot recursively launch this manager.

Only use a workflow when it offers concrete coordination value; direct work is preferred when faster and cheaper.
