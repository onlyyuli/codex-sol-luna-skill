# Architecture

## Objective

The frontend-selected model remains the sole controller. The Skill optimizes one thing: expected
Credit use while preserving required quality, safety, and scope. It never changes or infers the
main model. Sol is recommended, not required.

Savings come from replacing expensive main-thread execution with bounded Luna work. Creating more
agents without reducing main-thread work is an economy failure.

## Routes

| Route | Execution |
|---|---|
| `MAIN_ONLY` | Current main thread; zero children |
| `LUNA_SINGLE_READ` | One Luna Max reader replaces a bounded investigation |
| `LUNA_SINGLE_WRITE` | One Luna Max worker replaces a bounded implementation |
| `LUNA_READ_PARALLEL` | Two adaptive readers, or an explicitly requested valid count |
| `LUNA_WRITE_PARALLEL` | Two adaptive workers with disjoint ownership, or an explicitly requested valid count |

Adaptive routing starts with one Luna and can use two only when scopes are substantial,
independent, and cheaper to isolate than to combine. Explicit counts from 1 through 8 remain
available; counts 3-8 are never selected adaptively.

The Skill remains explicit-only. It activates only when Codex attaches it after the user selects
`$sol-luna` in the frontend Skill picker.

## Judge-only control plane

The main thread owns requirements, route selection, architecture and safety decisions, ownership,
integration, and final acceptance. For delegated work it performs only a shallow preflight, sends a
compact packet, and avoids delegated reads, searches, edits, and local validation.

After the child returns, the main thread:

1. checks cited evidence for material uncertainty;
2. inspects actual diffs and critical changed paths for write work;
3. runs the smallest sufficient integration check;
4. asks the same child for one bounded correction when needed; and
5. synthesizes the answer without copying the full child report.

This prevents the previous failure mode where Sol completed most of the task and Luna merely added
work.

For a normal delegated task, the controller uses at most one preflight tool round when the request
does not already define the boundary, followed by one combined diff/evidence/integration round
after the child completes. A further round requires a concrete correctness, safety, scope, or
evidence problem. The final answer repeats the selected route as `Route: <ROUTE_NAME>` so routing
tests do not depend on prose interpretation.

## Execution plane

Every child is a leaf agent explicitly requested as `gpt-5.6-luna` with `max` reasoning. Readers
are read-only. Workers receive an exact write scope and local validation. Parallel writers require
one active owner per file and cannot depend on another packet's unfinished output.

## Evidence and accounting

Configuration proves requested model settings, not actual execution. Runtime activity or persisted
rollouts must link every child thread to Luna Max.

The benchmark records parent and child input, cached input, cache-write input, and output tokens.
It estimates Credits using a dated rate-card snapshot and marks the total incomplete when any child
usage is missing. Exact repeated parent/child tool calls are recorded as duplicate execution.

The rate card is benchmark evidence, not runtime routing configuration. Model rates can change, so
every result retains the snapshot date and official source.

The first sanitized local canary is stored in
[`benchmarks/canary-2026-09-03.json`](../benchmarks/canary-2026-09-03.json). It is directional
evidence only and intentionally does not satisfy the full release gate.

## Failure behavior

- Adaptive route and unavailable Luna: disclose the failure and continue in `MAIN_ONLY`.
- Explicitly required Luna and unavailable Luna: stop without substitution.
- Incomplete result: request one bounded correction from the same child before main-thread takeover.
- Scope expansion, safety decision, destructive work, or unexpected write overlap: stop and return
  control to the main thread.
