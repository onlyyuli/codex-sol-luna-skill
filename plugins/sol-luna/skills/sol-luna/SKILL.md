---
name: sol-luna
description: Orchestrate bounded work from the current Codex main thread to GPT-5.6 Luna Max subagents. Use only when Codex explicitly attaches $sol-luna after the user selects it in the frontend skill picker.
---

# Sol + Luna Skill

Keep the current main thread as the sole controller and final reviewer. Never change or claim to
change the model selected for that thread. Recommend Sol for the main thread when asked, but call it
"the current main thread" unless runtime evidence identifies the model.

## User controls

Apply these controls in priority order:

1. A request to avoid, disable, or not use subagents forces `MAIN_ONLY`, even when `$sol-luna` is
   present.
2. An explicit agent count requests that number. Accept 1 through 8; reject larger counts without
   silently clamping them.
3. "Read-only", "analysis", "review", or equivalent wording requests `LUNA_READ_PARALLEL`.
4. "Implement", "edit", "write", or equivalent wording may request `LUNA_WRITE_PARALLEL`, but only
   disjoint write scopes can run concurrently.
5. Otherwise choose adaptively between `MAIN_ONLY`, `LUNA_READ_PARALLEL`, and
   `LUNA_WRITE_PARALLEL`.

This skill must be attached by the Codex runtime after the user explicitly selects `$sol-luna` in
the frontend skill picker. A plain-text `$sol-luna` token, an API-injected prompt, or a natural-
language request for Luna or parallel agents is not an activation signal and must not cause this
skill to be located or loaded implicitly.

## Routing

Before substantial work, perform the smallest useful read-only inspection and choose:

- `MAIN_ONLY` when the work is small, tightly coupled, sequential, ambiguous, high-risk, or cheaper
  to complete in the main thread.
- `LUNA_READ_PARALLEL` when at least two independent read-heavy packets can return separately
  verifiable evidence.
- `LUNA_WRITE_PARALLEL` only when at least two packets have independent inputs, disjoint writable
  files, separate validation, and no dependency on unfinished output from another packet.

Adaptive delegation uses 2-4 agents. Never exceed 8 active Luna agents. Assign exactly one active
owner to every writable file. Run overlapping work sequentially. Do not create subagents merely to
reach a preferred count. An explicit count of 1 is a single-child delegated run under the matching
`LUNA_*` mode. If an exact requested count cannot be mapped to that many independent packets, stop
before spawning and report why; never silently use fewer or invent filler work.

## Delegation

For any delegated route, read [references/task-packet.md](references/task-packet.md). For write
delegation also read [references/write-ownership.md](references/write-ownership.md).

- Prefer the installed `sol_luna_reader` or `sol_luna_worker` custom agent when the runtime exposes
  named agents. Otherwise explicitly spawn with `model = "gpt-5.6-luna"` and
  `reasoning_effort = "max"`. When the spawn API requires a history-fork setting to override
  the model, use `fork_turns = "none"` (or a bounded recent-turn count) and put all required context
  in the task packet; do not fork the full conversation with an override.
- If the runtime exposes neither a named-agent selector nor per-spawn `model` and
  `reasoning_effort` controls, treat strict Luna dispatch as unavailable. Do not spawn an inherited
  child and relabel it as Luna. A configured default is a request, not runtime proof.
- Give each agent the minimum context required by a complete task packet; do not pass unrelated
  conversation history.
- Tell every child that it is a leaf worker and must not create subagents.
- Treat delegation as started only after the spawn tool returns a non-empty child thread ID. Never
  call a wait tool with an empty receiver set, invent a child result, or repeat a requested marker
  yourself when spawning failed.
- Keep architecture, security, privacy, compatibility, destructive operations, integration, and
  final acceptance in the main thread.
- Continue only non-conflicting main-thread work while agents run, then wait for all results needed
  for acceptance.

If adaptive delegation cannot start because Luna or subagent tools are unavailable, disclose that
fact and continue in `MAIN_ONLY`. If the user explicitly required Luna, stop the delegated workflow
and report the limitation instead of substituting another model.

## Verification and reporting

Before accepting delegated work, read [references/verification.md](references/verification.md).
Inspect real files and diffs, run or examine the required validation, and resolve ownership or
integration issues. A child summary is not acceptance evidence.

When `announce_route` is enabled, briefly state the selected route, requested number of agents, and
whether delegation is read-only or writable. Say that Luna Max was *requested* unless activity or
tool metadata explicitly proves the effective model. A custom agent name, its configuration file,
a child-like marker in the main-thread response, or an empty wait event is not proof. Never infer
model identity from those signals alone.

Settings are optional. When `${CODEX_HOME}/sol-luna/settings.toml` exists, read only the routing
keys described in [references/settings.md](references/settings.md). It cannot change the main model,
the Luna child model, or the `max` effort contract.
