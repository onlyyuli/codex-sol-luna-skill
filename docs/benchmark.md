# Benchmark

The repository includes 18 tasks across read-heavy exploration, tests, documentation, disjoint implementation, coupled refactoring, and high-risk decisions. Each run starts from a fresh copy of `benchmarks/fixture`.

Arms:

- A: Sol main thread, no subagents.
- B: Sol main thread with adaptive `$sol-luna`.
- C: Sol main thread with forced four-Luna delegation only for eligible tasks.
- D: separate Luna/Terra main-thread compatibility smoke checks; not part of the performance aggregate.

The runner is intentionally opt-in because a full three-trial matrix makes many billable model calls:

```sh
python3 benchmarks/run_matrix.py
python3 benchmarks/run_matrix.py --execute --trials 3
python3 benchmarks/run_routing_contract.py
python3 benchmarks/run_routing_contract.py --execute
python3 benchmarks/run_compatibility_smoke.py --execute
python3 benchmarks/summarize.py benchmark-results/results.jsonl
```

For B and C, each disposable fixture contains a copy of the packaged Skill and the prompt explicitly
loads that file. This avoids treating a raw `$sol-luna` string in non-interactive CLI input as proof
that the client's interactive skill selector hydrated the Skill. Plugin discovery is tested
separately by the isolated installer test. The release checklist also requires a real frontend
picker probe; the non-interactive benchmark cannot replace that UI gate.

Record deterministic test pass rate, elapsed time, Token metadata when exposed, tool failures, write conflicts, and model evidence. Non-code outputs still require blind manual review; deterministic tests alone are not a complete quality score.

Release gate:

- Routing and safety invariants: 100%.
- Overall pass-rate loss versus A: no more than five percentage points.
- Median elapsed improvement on eligible parallel work: at least 20%.
- Write-ownership conflicts, silent model fallback, and unsupported model claims: zero.

`run_routing_contract.py` contains 12 machine-checked cases for zero-child default behavior,
MAIN_ONLY routing, exact reader/worker counts, overlap refusal, the hard limit, disable precedence,
non-Sol main-thread compatibility, scope expansion, and main-thread verification. Its default mode
only validates and counts the plan; `--execute` is required for billable runtime checks.

Do not publish multiplier claims without the raw result file, task set, account/config context, and scoring method.
