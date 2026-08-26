#!/usr/bin/env python3
"""Run opt-in Luna and Terra main-thread compatibility smoke checks."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

try:
    from .run_matrix import ROOT, activity_evidence, prepare_workspace, timeout_text
except ImportError:  # Direct script execution.
    from run_matrix import ROOT, activity_evidence, prepare_workspace, timeout_text


MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default=str(ROOT / "benchmarks/fixture"))
    parser.add_argument("--output", default="benchmark-results/compatibility.jsonl")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required acknowledgement because this runs two billable Codex model calls",
    )
    args = parser.parse_args()
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    if not args.execute:
        print("Dry run: 2 billable main-thread compatibility checks would run. Add --execute.")
        return 0
    if not shutil.which("codex"):
        parser.error("codex CLI is required")
    login = subprocess.run(
        ["codex", "login", "status"], text=True, capture_output=True, check=False
    )
    if login.returncode != 0:
        parser.error("Codex must be logged in before --execute")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for model in MODELS:
            with tempfile.TemporaryDirectory(prefix="sol-luna-compat-") as directory:
                workspace = Path(directory) / "workspace"
                shutil.copytree(args.fixture, workspace)
                prepare_workspace(workspace, "A")
                started = time.monotonic()
                try:
                    result = subprocess.run(
                        [
                            "codex",
                            "exec",
                            "--json",
                            "--ephemeral",
                            "--sandbox",
                            "read-only",
                            "--model",
                            model,
                            "--cd",
                            str(workspace),
                            "Do not use subagents. Inspect README.md only and return COMPATIBILITY_OK.",
                        ],
                        text=True,
                        capture_output=True,
                        timeout=args.timeout_seconds,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    result = subprocess.CompletedProcess(
                        args=exc.cmd,
                        returncode=124,
                        stdout=timeout_text(exc.stdout),
                        stderr=timeout_text(exc.stderr)
                        + f"\nTimed out after {args.timeout_seconds} seconds.",
                    )
                evidence = activity_evidence(result.stdout)
                diff = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=workspace,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                record = {
                    "arm": "D",
                    "model": model,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "codex_exit_code": result.returncode,
                    "marker_observed": "COMPATIBILITY_OK" in evidence["final_message"],
                    "changed_paths": [line[3:] for line in diff.stdout.splitlines() if len(line) > 3],
                    "stdout_jsonl": result.stdout,
                    "stderr": result.stderr,
                    **evidence,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Wrote compatibility results to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
