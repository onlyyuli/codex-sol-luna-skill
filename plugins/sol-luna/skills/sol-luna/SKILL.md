---
name: sol-luna
description: Minimize Codex credit use by delegating bounded execution from the current main thread to GPT-5.6 Luna Max. Use only when Codex explicitly attaches $sol-luna after the user selects it in the frontend skill picker.
---

# Sol + Luna Skill

Minimize expected credits while preserving the requested quality, safety, and scope. Keep the
current main thread as the sole controller and final reviewer. Never change or claim to change its
model. Recommend Sol when asked, but call it "the current main thread" unless runtime evidence
identifies the model.

The economy mechanism is **replacement, not extra parallelism**: Luna performs substantial work
that the main thread would otherwise perform, while the main thread routes and verifies without
repeating that work.

## User controls

Apply controls in this order:

1. A request to avoid, disable, or not use subagents forces `MAIN_ONLY`, even when `$sol-luna` is
   attached.
2. An explicit agent count requests exactly that count. Accept 1 through 8; reject larger counts
   without silently clamping them. Warn that 3-8 agents can consume more credits than one agent.
3. "Read-only", "analysis", "review", or equivalent wording selects a reader role.
4. "Implement", "edit", "write", or equivalent wording selects a worker role. Concurrent writers
   still require disjoint write scopes.
5. Otherwise route adaptively for minimum expected credits.

This skill must be attached by the Codex runtime after the user explicitly selects `$sol-luna` in
the frontend skill picker. A plain-text `$sol-luna` token, an API-injected prompt, or a natural-
language request for Luna or parallel agents is not an activation signal and must not cause this
skill to be located or loaded implicitly.

## Economy-first routing

Perform only the smallest read-only preflight needed to classify the task. Skip workspace
preflight entirely when the user's request already supplies a bounded objective, read/write mode,
scope, and validation target. Do not list or inspect the repository merely to enrich a packet; the
child owns discovery inside its assigned scope.

- `MAIN_ONLY`: use no child when the task is small enough that delegation overhead is unlikely to
  be recovered; when it is ambiguous, tightly coupled, destructive, security-sensitive, or a
  shared architecture/interface decision; or when the main thread would still need to repeat most
  of the child's work.
- `LUNA_SINGLE_READ`: use one reader for a non-trivial, bounded exploration, review, diagnosis, or
  evidence-gathering task that can replace most main-thread investigation.
- `LUNA_SINGLE_WRITE`: use one worker for a non-trivial, bounded implementation, test, or
  documentation task with a clear write scope and validation.
- `LUNA_READ_PARALLEL`: use two adaptive readers only when there are at least two substantial,
  independent scopes and separating them avoids loading unrelated context. Each result must be
  independently verifiable.
- `LUNA_WRITE_PARALLEL`: use two adaptive workers only when packets have independent inputs,
  disjoint writable files, separate validation, and no dependency on unfinished output from
  another packet.

Adaptive delegation starts with one agent and never exceeds two. Prefer a single Luna whenever it
can complete the bounded work coherently. Parallelism is not a benefit by itself: do not choose it
only to reduce wall-clock time, to reach a preferred count, or when each child would receive the
same large context.

An explicit count overrides the adaptive 1-2 limit but not the hard limit of 8, model strictness,
write ownership, or task independence. Count 1 maps to a `LUNA_SINGLE_*` route. Count 2-8 maps to a
`LUNA_*_PARALLEL` route only when exactly that many real packets exist. Otherwise stop before
spawning and explain why; never invent filler packets or silently use fewer agents.

Delegate only when the packet can replace the majority of expected searching, reading,
implementation, or local validation and final acceptance can remain targeted. If that condition
is not met, use `MAIN_ONLY`.

## Judge-only main thread

For a delegated route:

1. Build a compact task packet without doing the packet's substantive work.
2. Spawn the child, then continue only controller work that does not duplicate any delegated
   search, file inspection, implementation, or validation.
3. Use the returned evidence for acceptance. For read work, inspect only the cited evidence needed
   to resolve material uncertainty. For write work, inspect the actual diff and critical changed
   paths, then run the smallest sufficient integration check.
4. If evidence or implementation is incomplete, request one bounded correction from the same
   child before taking over its work. Stop on a material ambiguity, scope expansion, or safety
   decision.
5. Synthesize the final answer without reproducing full child reports or raw logs.

The main thread retains architecture, security, privacy, compatibility, destructive-operation,
integration, and final-acceptance decisions. This responsibility permits targeted checks, not a
second full execution of the delegated task.

For an ordinary delegated task, budget one parent tool round before spawning only when routing
cannot be decided from the request, and one combined tool round after the child returns. Combine
diff inspection, critical-file inspection, and the smallest integration check in that post-child
round. Use another parent tool round only when the first reveals a concrete correctness, safety,
scope, or evidence problem. Otherwise answer immediately. This is a Credit budget, not permission
to skip necessary safety verification.

## Delegation

For any delegated route, read [references/task-packet.md](references/task-packet.md). For parallel
write delegation also read [references/write-ownership.md](references/write-ownership.md).

- Prefer the installed `sol_luna_reader` or `sol_luna_worker` custom agent when the runtime exposes
  named agents. Otherwise explicitly spawn with `model = "gpt-5.6-luna"` and
  `reasoning_effort = "max"`. When the spawn API requires a history-fork setting to override the
  model, use `fork_turns = "none"` (or the smallest bounded recent-turn count) and put only required
  context in the task packet.
- If the runtime exposes neither a named-agent selector nor per-spawn model and effort controls,
  treat strict Luna dispatch as unavailable. Do not spawn an inherited child and relabel it Luna.
- Tell every child it is a leaf worker and must not create subagents.
- Treat delegation as started only after the spawn tool returns a non-empty child thread ID. Never
  wait on an empty receiver set, invent a result, or repeat a requested marker yourself.
- Wait for every result required for acceptance, but do not poll unchanged state repeatedly.

If adaptive delegation cannot start because Luna or subagent tools are unavailable, disclose the
failure and continue in `MAIN_ONLY`. If the user explicitly required Luna, stop instead of
substituting another model.

## Verification and reporting

Before accepting delegated work, read [references/verification.md](references/verification.md).
A child summary is not acceptance evidence.

When `announce_route` is enabled, briefly report the route, requested child count, role, and that
the objective is minimum credits. Say Luna Max was *requested* unless activity or tool metadata
proves the effective model and effort. A custom-agent name or configuration file proves intent,
not execution.

Repeat the selected route in the final response using the exact machine-readable form
`Route: <ROUTE_NAME>`, including `Route: MAIN_ONLY`. If routing stops before a valid mode can be
selected, report the reason instead of inventing a route.

Settings are optional. When `${CODEX_HOME}/sol-luna/settings.toml` exists, read only the keys in
[references/settings.md](references/settings.md). Settings cannot change the main model, Luna
model, or `max` effort contract.
