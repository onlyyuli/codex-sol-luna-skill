#!/usr/bin/env python3
"""Summarize deterministic benchmark metrics from a JSONL result file."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    args = parser.parse_args()
    records = [json.loads(line) for line in Path(args.results).read_text(encoding="utf-8").splitlines() if line]
    by_arm = defaultdict(list)
    for record in records:
        by_arm[record["arm"]].append(record)
    summary = {}
    for arm, values in sorted(by_arm.items()):
        passed = [value for value in values if value["codex_exit_code"] == 0 and value["validation_exit_code"] == 0]
        parallel = [value for value in values if value["parallelizable"]]
        delegated = [value for value in values if value.get("child_count", 0) > 0]
        token_totals = []
        for value in values:
            usage = value.get("usage") or {}
            if isinstance(usage, dict):
                token_total = sum(
                    count
                    for key, count in usage.items()
                    if key in {"input_tokens", "output_tokens"} and type(count) is int
                )
                if token_total:
                    token_totals.append(token_total)
        summary[arm] = {
            "runs": len(values),
            "deterministic_pass_rate": round(len(passed) / len(values), 4) if values else 0,
            "median_elapsed_seconds": round(statistics.median(v["elapsed_seconds"] for v in values), 3),
            "parallel_median_elapsed_seconds": (
                round(statistics.median(v["elapsed_seconds"] for v in parallel), 3) if parallel else None
            ),
            "runs_with_child_activity": len(delegated),
            "runs_with_luna_model_proof": sum(bool(value.get("luna_model_proven")) for value in values),
            "runs_with_max_effort_proof": sum(bool(value.get("max_effort_proven")) for value in values),
            "median_input_plus_output_tokens": (
                round(statistics.median(token_totals), 1) if token_totals else None
            ),
        }
    baseline = summary.get("A")
    if baseline:
        for arm, metrics in summary.items():
            metrics["pass_rate_delta_vs_A_percentage_points"] = round(
                (metrics["deterministic_pass_rate"] - baseline["deterministic_pass_rate"]) * 100,
                2,
            )
            baseline_parallel = baseline.get("parallel_median_elapsed_seconds")
            arm_parallel = metrics.get("parallel_median_elapsed_seconds")
            metrics["parallel_speed_improvement_vs_A"] = (
                round((baseline_parallel - arm_parallel) / baseline_parallel, 4)
                if baseline_parallel and arm_parallel is not None
                else None
            )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
