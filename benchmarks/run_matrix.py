#!/usr/bin/env python3
"""Run the opt-in, billable Sol + Luna benchmark matrix."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Union


ROOT = Path(__file__).resolve().parents[1]
ARMS = {
    "A": {"model": "gpt-5.6-sol", "prefix": "Do not use subagents. "},
    "B": {
        "model": "gpt-5.6-sol",
        "prefix": (
            "$sol-luna This is an explicit invocation. Load and follow "
            ".agents/skills/sol-luna/SKILL.md before routing. "
        ),
    },
    "C": {
        "model": "gpt-5.6-sol",
        "prefix": (
            "$sol-luna This is an explicit invocation. Load and follow "
            ".agents/skills/sol-luna/SKILL.md. Use four GPT-5.6 Luna Max agents when the task "
            "is eligible. "
        ),
    },
}


def timeout_text(value: Optional[Union[str, bytes]]) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def load_tasks(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def nested_values(value: Any, keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in keys and isinstance(child, str):
                found.add(child)
            found.update(nested_values(child, keys))
    elif isinstance(value, list):
        for child in value:
            found.update(nested_values(child, keys))
    return found


def activity_evidence(stdout: str) -> dict[str, Any]:
    events = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    child_ids: set[str] = set()
    messages: list[str] = []
    usage: dict[str, int] = {}
    for event in events:
        item = event.get("item")
        if isinstance(item, dict):
            receivers = item.get("receiver_thread_ids")
            if isinstance(receivers, list):
                child_ids.update(value for value in receivers if isinstance(value, str) and value)
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
        event_usage = event.get("usage")
        if isinstance(event_usage, dict):
            for key, value in event_usage.items():
                if type(value) is int:
                    usage[key] = usage.get(key, 0) + value
    child_activity = []
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        receivers = item.get("receiver_thread_ids")
        if isinstance(receivers, list) and child_ids.intersection(receivers):
            child_activity.append(item)
    models = nested_values(
        child_activity, {"model", "model_name", "model_slug", "selected_model"}
    )
    efforts = nested_values(
        child_activity, {"model_reasoning_effort", "reasoning_effort"}
    )
    final_text = messages[-1] if messages else ""
    return {
        "child_thread_ids": sorted(child_ids),
        "child_count": len(child_ids),
        "observed_models": sorted(models),
        "observed_reasoning_efforts": sorted(efforts),
        "luna_model_proven": "gpt-5.6-luna" in models,
        "max_effort_proven": "max" in efforts,
        "reported_route": next(
            (route for route in ("MAIN_ONLY", "LUNA_READ_PARALLEL", "LUNA_WRITE_PARALLEL") if route in final_text),
            None,
        ),
        "usage": usage,
        "final_message": final_text,
    }


def prepare_workspace(workspace: Path, arm: str) -> None:
    if arm in {"B", "C"}:
        skill_source = ROOT / "plugins/sol-luna/skills/sol-luna"
        skill_target = workspace / ".agents/skills/sol-luna"
        skill_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_source, skill_target)
    commands = (
        ["git", "init", "-b", "main"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Sol Luna Benchmark",
            "-c",
            "user.email=benchmark@example.invalid",
            "commit",
            "-m",
            "fixture baseline",
        ],
    )
    for command in commands:
        result = subprocess.run(command, cwd=workspace, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def run_codex(
    workspace: Path,
    task: dict[str, Any],
    arm: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    definition = ARMS[arm]
    prompt = definition["prefix"] + task["prompt"]
    agent_options = []
    if arm in {"B", "C"}:
        agent_options = [
            "--enable",
            "multi_agent",
            "--config",
            "agents.enabled=true",
            "--config",
            'agents.default_subagent_model="gpt-5.6-luna"',
            "--config",
            'agents.default_subagent_reasoning_effort="max"',
        ]
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                "codex",
                "exec",
                *agent_options,
                "--json",
                "--ephemeral",
                "--sandbox",
                "workspace-write",
                "--ask-for-approval",
                "never",
                "--model",
                definition["model"],
                "--cd",
                str(workspace),
                prompt,
            ],
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
            stderr=timeout_text(exc.stderr) + f"\nTimed out after {timeout_seconds} seconds.",
        )
    validation = subprocess.run(
        shlex.split(task["validation"]),
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
    record = {
        "task_id": task["id"],
        "category": task["category"],
        "arm": arm,
        "model": definition["model"],
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "codex_exit_code": result.returncode,
        "validation_exit_code": validation.returncode,
        "parallelizable": task["parallelizable"],
        "stdout_jsonl": result.stdout,
        "stderr": result.stderr,
        "validation_stdout": validation.stdout,
        "validation_stderr": validation.stderr,
        "changed_paths": [line[3:] for line in diff.stdout.splitlines() if len(line) > 3],
    }
    record.update(activity_evidence(result.stdout))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default=str(ROOT / "benchmarks/tasks.jsonl"))
    parser.add_argument("--fixture", default=str(ROOT / "benchmarks/fixture"))
    parser.add_argument("--output", default="benchmark-results/results.jsonl")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--arms", nargs="+", choices=sorted(ARMS), default=sorted(ARMS))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required acknowledgement because this runs billable Codex model calls",
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if args.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    tasks = load_tasks(Path(args.tasks))
    planned = sum(1 for task in tasks for arm in args.arms if arm != "C" or task["parallelizable"])
    planned *= args.trials
    if not args.execute:
        print(f"Dry run: {planned} billable Codex executions would run. Add --execute to continue.")
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
        for trial in range(1, args.trials + 1):
            for task in tasks:
                for arm in args.arms:
                    if arm == "C" and not task["parallelizable"]:
                        continue
                    with tempfile.TemporaryDirectory(prefix=f"sol-luna-{task['id']}-") as directory:
                        workspace = Path(directory) / "workspace"
                        shutil.copytree(args.fixture, workspace)
                        prepare_workspace(workspace, arm)
                        record = run_codex(workspace, task, arm, args.timeout_seconds)
                        record["trial"] = trial
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        handle.flush()
    print(f"Wrote benchmark results to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
