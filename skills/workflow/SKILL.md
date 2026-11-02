---
name: humanize-workflow
description: Use official or authored Humanize workflows when staged work, branching, iteration or parallel agents help. Select proactively; handle simple tasks directly.
---

# Choose a flow for the task

Use Humanize when coordination helps the task. The user need not name this plugin.
Direct execution is preferred when faster and cheaper.

1. Read the objective, applicable AGENTS.md, existing changes and completion evidence.
   Check runtime readiness when unknown. Follow the user's model and permission choices.
2. Inspect `humanize_catalog` for upstream flows and `humanize_library` for curated custom
   sources. Choose by behavior and applicability. The default `flow="rlar"` is the official
   actor/reviewer flow; `ralph_loop` and `stateful_ralph` deliberately continue until stopped.
   Do not force every task into a review loop. Adapt official source or author a new flow
   when a different sequence, branch, loop, parallel join or nested structure fits better.
3. Call `humanize_run(flow=..., agents=..., flow_params=...)`, or provide flow_file and
   entrypoint for a trusted local Python flow. Assign models by the selected flow's roles.
   There is no plugin planner, extra verifier or max_rounds parameter.
4. Omit duration_seconds, output_tokens and cost_usd for an unlimited run. Set a limit only
   when the user requests it or a task-specific budget already applies. Do not invent caps
   or simulate "unlimited" with a large finite number. A deliberately endless upstream loop
   keeps running without limits until cancelled. read_only restricts local agent permissions.
5. The official app/TUI opens automatically. Immediately share the returned app workspace/
   epic or tmux session and attach_command (switch_command inside tmux). Use the native UI
   for flow, session, tool and usage visibility; do not add a dashboard or narration agent.
   Wait at most 60 seconds per tool call; this is polling, not a workflow runtime limit.
   Report stage outcomes, meaningful changes, required decisions and final evidence in chat.
6. Steering can target an active task role; check receipts. Untargeted guidance is stored
   and submitted to actor/agent when a session is available. Cancellation is complete at
   terminal state. Do not automatically resume a user-cancelled run. Resume requires the
   selected flow to support journals and accepts new optional limits; omitted limits are
   unlimited. Old saved requests keep their original flow/envelope structure on recovery.
7. `complete` means the selected flow returned normally. Read the result and verify the
   user's requested outcome; a Python return alone is not independent task acceptance.
   Custom results can explicitly report complete, blocked or needs_work. No extra model
   verification is imposed by the plugin.
8. Custom flows with actual independent review evidence can enter the private candidate
   pool. Official flows remain available by reference. Curate only useful recipes: assess
   scope/limitations and test relevant paths before promotion. More successful runs alone
   do not establish reuse value. Do not turn retention into extra work on every task.

Preserve the original goal, user changes and existing authorization boundaries. Native
sub-flows are supported; recursively starting another plugin-managed job is not.
