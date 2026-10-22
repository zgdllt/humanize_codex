---
name: humanize-author-flow
description: Draft and test task-specific Humanize Python flows with arbitrary roles and sequential, looping, branching, parallel or nested control structures when existing workflows do not fit.
---

# Author a flow for the task

Draft an ordinary async Python program using hmz.flows. Do not copy a four-role review loop
unless it fits the task. The local manager accepts a self-contained .py file and one chosen
@flow entrypoint, its declared role names and its own FlowParams schema.

1. Inspect existing curated flows and project conventions. Choose the smallest useful
   structure; combinations and nested flow calls are allowed. No fixed role names or pair
   of entrypoints is required. Inspect examples/control_structures.py only when examples
   of sequence/loop/branch/parallel execution would help.
2. Declare AgentCollection, local EnvCollection, FlowParams and @flow. Prefer generic Agent
   role types for Codex/DSH compatibility. Keep agent/model assignments outside the algorithm.
   Every concurrent turn needs a separate session. Bound loops and concurrency. Parallel
   writers must use isolated worktrees/environments with defined integration ownership;
   same-tree parallel analysis should be read-only. Do not provision remote resources unless
   authorized; this manager binds local environments, while hmz supports broader provisioning.
3. humanize_inspect_flow imports trusted authored code and returns roles, permissions, input
   schema and static structure hints. This is not a security sandbox or an inferred graph.
   humanize_validate_flow executes 1–8 scripted cases through the real fake engine. Cases
   specify task, agents, params and nonempty expected output fields. Exercise meaningful
   alternate branches, loop termination and fanout/join, not just repeated happy paths.
4. Start with humanize_run(flow_file=..., entrypoint=..., flow_params=..., agents=...). The
   manager adds reserved humanize_verifier and humanize_observer roles; their assignments may
   be overridden. It does not constrain the target flow's other roles or Python control flow.
   Do not use reserved names in the authored collection. Results may have any Python shape;
   the independent verifier checks actual outcomes before the outer run can claim complete.
5. The observer consumes runtime activity outside the execution agents' contexts. Do not
   delegate dashboard maintenance or log polling to the task's main agent. The program records
   concurrent active sessions even while narration is delayed or unavailable.
6. A reviewed success creates a candidate. To promote a reusable recipe, inspect its code,
   parameterization, applicability, failure modes and existing alternatives. Run at least two
   meaningful validation cases for its exact retained source/entry. Curate with rationale,
   use_when and avoid_when. This is an agent assessment backed by evidence, not a benchmark.
7. Runtime input values are not copied into saved recipes; supply flow_params on reuse as
   needed. Export curated code as a versioned source bundle and index it with a full Git SHA.
   Candidates require explicit trial export; the index accepts curated flows only. Never
   publish task secrets or treat local retention as authorization to push a repository.

Read upstream detail only when needed:
- https://docs.humanfia.ai/humanize/weaver/writing-a-flow
- https://docs.humanfia.ai/humanize/weaver/async-flows
- https://docs.humanfia.ai/humanize/weaver/calling-flows
- https://docs.humanfia.ai/humanize/weaver/testing-flows
- https://docs.humanfia.ai/humanize/weaver/flowverses
