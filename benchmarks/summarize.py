#!/usr/bin/env python3
"""Summarize quality, runtime, and evidence-backed credit savings."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional


EXPECTED_TASK_COUNT = 18
MIN_TRIALS_PER_TASK = 3


def median_or_none(values: Iterable[float]) -> Optional[float]:
    items = list(values)
    return round(statistics.median(items), 6) if items else None


def credit_total(record: dict[str, Any]) -> Optional[float]:
    evidence = record.get("credit_evidence")
    if not isinstance(evidence, dict) or not evidence.get("complete"):
        return None
    value = evidence.get("total_credits")
    return float(value) if isinstance(value, (int, float)) else None


def paired_savings(
    values: list[dict[str, Any]],
    baseline_by_run: dict[tuple[Any, Any], dict[str, Any]],
    *,
    eligible_only: bool,
) -> list[float]:
    savings: list[float] = []
    for value in values:
        if eligible_only and not value.get("economy_eligible"):
            continue
        baseline = baseline_by_run.get((value.get("task_id"), value.get("trial")))
        current_total = credit_total(value)
        baseline_total = credit_total(baseline) if baseline else None
        if current_total is None or baseline_total is None or baseline_total <= 0:
            continue
        savings.append((baseline_total - current_total) / baseline_total)
    return savings


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_arm[str(record["arm"])].append(record)

    summary: dict[str, Any] = {}
    for arm, values in sorted(by_arm.items()):
        task_counts = Counter(value.get("task_id") for value in values)
        passed = [
            value
            for value in values
            if value["codex_exit_code"] == 0 and value["validation_exit_code"] == 0
        ]
        parallel = [value for value in values if value["parallelizable"]]
        delegated = [value for value in values if value.get("child_count", 0)]
        token_totals: list[int] = []
        complete_credits: list[float] = []
        parent_credits: list[float] = []
        child_credits: list[float] = []
        delegated_parent_shares: list[float] = []
        eligible_credits: list[float] = []
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
            evidence = value.get("credit_evidence")
            if not isinstance(evidence, dict) or not evidence.get("complete"):
                continue
            total = evidence.get("total_credits")
            parent = evidence.get("parent_credits")
            children = evidence.get("child_credits")
            if isinstance(total, (int, float)):
                complete_credits.append(float(total))
                if value.get("economy_eligible"):
                    eligible_credits.append(float(total))
            if isinstance(parent, (int, float)):
                parent_credits.append(float(parent))
            if isinstance(children, (int, float)):
                child_credits.append(float(children))
            if value.get("child_count", 0) and isinstance(total, (int, float)) and total > 0:
                if isinstance(parent, (int, float)):
                    delegated_parent_shares.append(float(parent) / float(total))

        summary[arm] = {
            "run_count": len(values),
            "distinct_task_count": len(task_counts),
            "minimum_trials_per_task": min(task_counts.values(), default=0),
            "economy_eligible_run_count": sum(
                bool(value.get("economy_eligible")) for value in values
            ),
            "pass_rate": round(len(passed) / len(values), 6) if values else None,
            "median_elapsed_seconds": median_or_none(
                float(value["elapsed_seconds"]) for value in values
            ),
            "parallel_median_elapsed_seconds": median_or_none(
                float(value["elapsed_seconds"]) for value in parallel
            ),
            "median_input_plus_output_tokens": median_or_none(
                float(value) for value in token_totals
            ),
            "delegated_run_count": len(delegated),
            "luna_proven_run_count": sum(
                bool(value.get("luna_model_proven")) for value in delegated
            ),
            "max_effort_proven_run_count": sum(
                bool(value.get("max_effort_proven")) for value in delegated
            ),
            "credit_complete_run_count": len(complete_credits),
            "median_total_credits": median_or_none(complete_credits),
            "eligible_median_total_credits": median_or_none(eligible_credits),
            "median_parent_credits": median_or_none(parent_credits),
            "median_child_credits": median_or_none(child_credits),
            "delegated_median_parent_credit_share": median_or_none(
                delegated_parent_shares
            ),
            "duplicate_execution_run_count": sum(
                bool((value.get("credit_evidence") or {}).get("economy_failure"))
                for value in values
            ),
            "route_match_run_count": sum(
                value.get("reported_route") == value.get("preferred_route")
                for value in values
            ),
        }

    baseline_values = by_arm.get("A", [])
    baseline_by_run = {
        (value.get("task_id"), value.get("trial")): value
        for value in baseline_values
    }
    baseline_metrics = summary.get("A")
    for arm, values in by_arm.items():
        metrics = summary[arm]
        all_savings = paired_savings(
            values, baseline_by_run, eligible_only=False
        )
        eligible_savings = paired_savings(
            values, baseline_by_run, eligible_only=True
        )
        metrics["paired_credit_run_count"] = len(all_savings)
        metrics["median_credit_savings_vs_A"] = median_or_none(all_savings)
        metrics["eligible_paired_credit_run_count"] = len(eligible_savings)
        metrics["eligible_median_credit_savings_vs_A"] = median_or_none(
            eligible_savings
        )
        if baseline_metrics and isinstance(baseline_metrics.get("pass_rate"), float):
            metrics["pass_rate_delta_vs_A"] = round(
                float(metrics["pass_rate"]) - float(baseline_metrics["pass_rate"]),
                6,
            )
        else:
            metrics["pass_rate_delta_vs_A"] = None
        baseline_parallel = (
            baseline_metrics.get("parallel_median_elapsed_seconds")
            if baseline_metrics
            else None
        )
        current_parallel = metrics["parallel_median_elapsed_seconds"]
        metrics["parallel_speed_improvement_vs_A"] = (
            round(
                (float(baseline_parallel) - float(current_parallel))
                / float(baseline_parallel),
                6,
            )
            if isinstance(baseline_parallel, (int, float))
            and baseline_parallel > 0
            and isinstance(current_parallel, (int, float))
            else None
        )

    economy = summary.get("B")
    if economy:
        checks = {
            "full_task_and_trial_coverage": (
                economy["distinct_task_count"] >= EXPECTED_TASK_COUNT
                and economy["minimum_trials_per_task"] >= MIN_TRIALS_PER_TASK
            ),
            "complete_credit_evidence": (
                economy["credit_complete_run_count"] == economy["run_count"]
            ),
            "complete_paired_baselines": (
                economy["paired_credit_run_count"] == economy["run_count"]
                and economy["eligible_paired_credit_run_count"]
                == economy["economy_eligible_run_count"]
            ),
            "pass_rate_loss_at_most_5pp": (
                economy.get("pass_rate_delta_vs_A") is not None
                and economy["pass_rate_delta_vs_A"] >= -0.05
            ),
            "overall_median_credit_savings_at_least_15pct": (
                economy.get("median_credit_savings_vs_A") is not None
                and economy["median_credit_savings_vs_A"] >= 0.15
            ),
            "eligible_median_credit_savings_at_least_30pct": (
                economy.get("eligible_median_credit_savings_vs_A") is not None
                and economy["eligible_median_credit_savings_vs_A"] >= 0.30
            ),
            "no_duplicate_execution": economy["duplicate_execution_run_count"] == 0,
            "all_routes_match_task_contract": (
                economy["route_match_run_count"] == economy["run_count"]
            ),
            "all_delegated_runs_prove_luna": (
                economy["luna_proven_run_count"] == economy["delegated_run_count"]
            ),
            "all_delegated_runs_prove_max": (
                economy["max_effort_proven_run_count"]
                == economy["delegated_run_count"]
            ),
        }
        summary["economy_release_gate"] = {
            "passed": all(checks.values()),
            "checks": checks,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results")
    args = parser.parse_args()
    records = [
        json.loads(line)
        for line in Path(args.results).read_text(encoding="utf-8").splitlines()
        if line
    ]
    print(json.dumps(summarize_records(records), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
