# Credit benchmark

The benchmark answers one release question: does economy routing reduce total Credits without
breaking task quality or safety?

## Arms

- A: Sol main thread with no subagents.
- B: Sol main thread with adaptive, minimum-Credit `$sol-luna` routing.
- C: Sol main thread with four Luna agents forced only for parallelizable tasks.
- D: separate Luna/Terra main-thread compatibility smoke checks; excluded from savings aggregates.

Every run starts from a fresh copy of `benchmarks/fixture`. The 18 tasks cover read exploration,
tests, documentation, disjoint implementation, coupled refactoring, and high-risk decisions.

## Run

Planning is free:

```sh
python3 benchmarks/run_matrix.py
python3 benchmarks/run_routing_contract.py
```

Run a two-call canary before the full matrix:

```sh
python3 benchmarks/run_matrix.py --execute --trials 1 --arms A B \
  --task-ids coupled-01 --capture-session-usage
```

The sanitized result of the first local canary is retained in
[`benchmarks/canary-2026-09-03.json`](../benchmarks/canary-2026-09-03.json). Both delegated runs
proved Luna Max and passed validation, with 35.50%-40.35% fewer estimated Credits than the single
stored A baseline. They took roughly twice as long. This is directional evidence only: one task,
one A run, and two B runs do not satisfy the release gate below.

Model execution is opt-in and billable:

```sh
python3 benchmarks/run_matrix.py --execute --trials 3 --capture-session-usage
python3 benchmarks/run_routing_contract.py --execute --capture-session-usage
python3 benchmarks/run_compatibility_smoke.py --execute
python3 benchmarks/summarize.py benchmark-results/results.jsonl
```

`--capture-session-usage` intentionally disables ephemeral mode so the runner can associate new
parent and child rollout files. It extracts only usage, model, effort, hashed tool signatures, and
path hints into the result; it does not copy rollout text. The normal Codex session files remain in
the configured Codex home.

Pass `--codex-bin /path/to/codex` to every runner when validating with a standalone stable CLI
instead of a Desktop-bundled pre-release.

Without that flag, the runner estimates complete Credits only for zero-child runs. Delegated totals
are marked incomplete instead of silently omitting Luna usage.

## Credit calculation

`benchmarks/credit_rates.json` is a dated snapshot of the official Codex Credit table. For each
thread:

```text
uncached input × input rate
+ cached input × cached rate
+ cache-write input × input rate × cache-write multiplier
+ output × output rate
```

The sum is divided by one million. `output_tokens` already includes billable reasoning output for
this calculation; `reasoning_output_tokens` is retained as evidence and not added twice.

Results include parent Credits, combined child Credits, total Credits, evidence completeness,
effective child model/effort, exact duplicate tool-call count, and overlapping path count.

## Release gate

Arm B must satisfy all gates:

- All 18 tasks have at least three trials; a canary can never pass the release gate.
- Complete parent/child Credit evidence for every run.
- A complete same-task, same-trial Sol-only baseline for every economy run.
- Pass-rate loss versus A no greater than five percentage points.
- Median Credit reduction across the full task set of at least 15%.
- Median Credit reduction across economy-eligible tasks of at least 30%.
- Zero exact duplicate parent/child tool executions.
- Every reported route matches the task contract.
- Every delegated run proves GPT-5.6 Luna and `max`.
- Write-ownership conflicts and silent model fallback remain zero.

Multiple Luna agents are not an adaptive default unless matched measurements show lower total
Credits than one Luna at the same quality. Wall-clock improvement is reported but cannot override
the Credit gate.

Do not publish a savings or performance claim without the raw result file, task set, rate-card
snapshot, account/config context, and scoring method.
