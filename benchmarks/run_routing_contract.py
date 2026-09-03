#!/usr/bin/env python3
"""Run the opt-in, billable routing and safety contract suite."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

try:
    from .run_matrix import (
        ROOT,
        activity_evidence,
        merge_rollout_activity,
        prepare_workspace,
        timeout_text,
    )
    from .usage_accounting import (
        account_rollouts,
        default_codex_home,
        discover_rollouts,
        load_rate_card,
        rollout_snapshot,
        stdout_parent_thread_id,
    )
except ImportError:  # Direct script execution.
    from run_matrix import (
        ROOT,
        activity_evidence,
        merge_rollout_activity,
        prepare_workspace,
        timeout_text,
    )
    from usage_accounting import (
        account_rollouts,
        default_codex_home,
        discover_rollouts,
        load_rate_card,
        rollout_snapshot,
        stdout_parent_thread_id,
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def path_allowed(path: str, allowed: list[str]) -> bool:
    return any(path == root or path.startswith(root.rstrip("/") + "/") for root in allowed)


def evaluate(case: dict[str, Any], record: dict[str, Any]) -> list[str]:
    violations = []
    child_count = record["child_count"]
    if not case["min_children"] <= child_count <= case["max_children"]:
        violations.append(
            f"child count {child_count} is outside "
            f"{case['min_children']}..{case['max_children']}"
        )
    expected_route = case.get("expected_route")
    if expected_route and record.get("reported_route") != expected_route:
        violations.append(
            f"reported route {record.get('reported_route')!r}, expected {expected_route!r}"
        )
    if child_count and not record.get("luna_model_proven"):
        violations.append("delegation lacks Luna runtime proof")
    if child_count and not record.get("max_effort_proven"):
        violations.append("delegation lacks max-effort runtime proof")
    if record["codex_exit_code"] != 0:
        violations.append(f"Codex exited {record['codex_exit_code']}")
    if record["validation_exit_code"] != 0:
        violations.append(f"validation exited {record['validation_exit_code']}")
    unexpected = [
        path
        for path in record["changed_paths"]
        if not path_allowed(path, case["allowed_changed_paths"])
    ]
    if unexpected:
        violations.append("unexpected changed paths: " + ", ".join(unexpected))
    final_lower = record.get("final_message", "").lower()
    for required in case.get("required_final_text", []):
        if required.lower() not in final_lower:
            violations.append(f"final response does not contain {required!r}")
    return violations


def run_case(
    case: dict[str, Any],
    fixture: Path,
    timeout_seconds: int,
    codex_bin: str = "codex",
    *,
    capture_session_usage: bool = False,
    codex_home: Optional[Path] = None,
    rate_card: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    codex_home = codex_home or default_codex_home()
    rate_card = rate_card or load_rate_card()
    with tempfile.TemporaryDirectory(prefix=f"sol-luna-route-{case['id']}-") as directory:
        workspace = Path(directory) / "workspace"
        shutil.copytree(fixture, workspace)
        prepare_workspace(workspace, "B")
        session_before = rollout_snapshot(codex_home) if capture_session_usage else set()
        started = time.monotonic()
        ephemeral_options = [] if capture_session_usage else ["--ephemeral"]
        command = [
            codex_bin,
            "exec",
            "--enable",
            "multi_agent",
            "--config",
            "agents.enabled=true",
            "--config",
            'agents.default_subagent_model="gpt-5.6-luna"',
            "--config",
            'agents.default_subagent_reasoning_effort="max"',
            "--json",
            *ephemeral_options,
            "--sandbox",
            "workspace-write",
            "--config",
            'approval_policy="never"',
            "--model",
            case["main_model"],
            "--cd",
            str(workspace),
            case["prompt"],
        ]
        try:
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(
                args=exc.cmd,
                returncode=124,
                stdout=timeout_text(exc.stdout),
                stderr=timeout_text(exc.stderr)
                + f"\nTimed out after {timeout_seconds} seconds.",
            )
        validation = subprocess.run(
            shlex.split(case["validation"]),
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        diff = subprocess.run(
            ["git", "status", "--short"],
            cwd=workspace,
            text=True,
            capture_output=True,
            check=False,
        )
        activity = activity_evidence(result.stdout)
        credit_evidence = None
        if capture_session_usage:
            parent_path, child_paths = discover_rollouts(
                codex_home,
                session_before,
                stdout_parent_thread_id(result.stdout),
            )
            credit_evidence = account_rollouts(
                parent_path,
                child_paths,
                expected_children=max(activity["child_count"], len(child_paths)),
                rate_card=rate_card,
            )
            activity = merge_rollout_activity(activity, credit_evidence)
        record = {
            "case_id": case["id"],
            "main_model_requested": case["main_model"],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "codex_exit_code": result.returncode,
            "validation_exit_code": validation.returncode,
            "changed_paths": [
                line[3:] for line in diff.stdout.splitlines() if len(line) > 3
            ],
            "stdout_jsonl": result.stdout,
            "stderr": result.stderr,
            **activity,
        }
        if credit_evidence is not None:
            record["credit_evidence"] = credit_evidence
        record["violations"] = evaluate(case, record)
        record["passed"] = not record["violations"]
        return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", default=str(ROOT / "benchmarks/routing_cases.jsonl")
    )
    parser.add_argument("--fixture", default=str(ROOT / "benchmarks/fixture"))
    parser.add_argument("--output", default="benchmark-results/routing-contract.jsonl")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument(
        "--codex-bin",
        help="Explicit stable Codex executable instead of resolving codex from PATH",
    )
    parser.add_argument(
        "--rate-card",
        default=str(ROOT / "benchmarks/credit_rates.json"),
        help="Versioned ChatGPT credit-rate snapshot used for estimates",
    )
    parser.add_argument(
        "--capture-session-usage",
        action="store_true",
        help="Persist rollouts to prove child model/effort and capture per-thread Credits",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required acknowledgement because this runs billable Codex model calls",
    )
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    try:
        rate_card = load_rate_card(Path(args.rate_card))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    cases = load_cases(Path(args.cases))
    if not args.execute:
        print(
            f"Dry run: {len(cases)} billable routing checks would run. Add --execute."
        )
        return 0
    codex_bin = (
        str(Path(args.codex_bin).expanduser().resolve())
        if args.codex_bin
        else shutil.which("codex")
    )
    if not codex_bin or not Path(codex_bin).is_file():
        parser.error("codex CLI is required")
    login = subprocess.run(
        [codex_bin, "login", "status"], text=True, capture_output=True, check=False
    )
    if login.returncode != 0:
        parser.error("Codex must be logged in before --execute")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    codex_home = default_codex_home()
    failures = 0
    with output.open("w", encoding="utf-8") as handle:
        for case in cases:
            record = run_case(
                case,
                Path(args.fixture),
                args.timeout_seconds,
                codex_bin=codex_bin,
                capture_session_usage=args.capture_session_usage,
                codex_home=codex_home,
                rate_card=rate_card,
            )
            failures += int(not record["passed"])
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
    print(f"Wrote {len(cases)} routing results to {output}; failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
