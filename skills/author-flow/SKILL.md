---
name: humanize-author-flow
description: Adapt official Humanize flows or author Python flows with task-specific roles and sequential, looping, branching, parallel or nested control structures.
---

# Start with upstream flows

Use the installed SDK and official source as the template. Inspect `humanize_catalog` and
`Hmz(workspace).flows.find(ref)` before drafting. Read the relevant upstream API as needed:

- https://docs.humanfia.ai/humanize/weaver/writing-a-flow
- https://docs.humanfia.ai/humanize/reference/flows
- https://docs.humanfia.ai/humanize/weaver/testing-flows

1. Choose the smallest useful control structure. Official rlar is suitable when an actor
   should work until review passes; ralph_loop and stateful_ralph are continuous loops.
   Reuse an official reference directly when it fits; do not copy its code unnecessarily.
2. When authoring, use AgentCollection, EnvCollection, FlowParams and @flow. Keep model
   assignment outside the algorithm. Independent concurrent turns need separate sessions;
   concurrent writers need separate worktrees and integration ownership. Add loop bounds or
   per-turn budgets only when the task calls for them. No plugin role names or schemas are
   imposed. The examples/control_structures.py file illustrates basic Python structures.
3. `humanize_run(flow_file=..., entrypoint=..., flow_params=..., agents=...)` runs the chosen
   function directly. Results may have any Python shape. No plugin planner, verifier or
   execution/review loop is added. Omitted total budgets are unlimited.
4. The local file interface freezes a self-contained source file. Use an SDK `flow` reference
   for installed packages or VCS packages with sibling modules and skills. SDK reference
   resolution and the native bridge preserve the package's skill resources. Flow-declared
   permissions apply; read_only can restrict local agent roles to reads.
5. Inspect declarations with humanize_inspect_flow. Use humanize_validate_flow for meaningful
   alternate branches, loop termination and parallel joins when validating reusable code.
   These helpers execute trusted Python, not a security sandbox. Match verification to risk;
   do not invent new gates or tests for simple reversible edits.
6. The native app/TUI displays real events. Share its returned location and keep chat updates
   focused on progress, findings and decisions. Custom journal recovery requires
   resumable=True; preserve the task and its root state across resume.
7. A normal return is flow completion, not proof of task acceptance. If a custom flow has an
   actual independent review, it may return status="complete", action="complete" and concrete
   evidence to qualify for the private candidate pool. Do not fabricate evidence for storage.
   Promotion additionally assesses applicability and uses at least two passing scenarios
   for the exact code/entry. Leave task prompts and credentials out of exported source.
