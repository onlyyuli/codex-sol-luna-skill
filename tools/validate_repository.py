#!/usr/bin/env python3
"""Validate cross-file invariants for the codex-sol-luna repository."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from installer import sol_luna_installer as installer  # noqa: E402


def main() -> int:
    errors: list[str] = []

    manifest_path = ROOT / "plugins/sol-luna/.codex-plugin/plugin.json"
    marketplace_path = ROOT / ".agents/plugins/marketplace.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

    expected_manifest = {
        "name": installer.PLUGIN_NAME,
        "version": installer.VERSION,
        "skills": "./skills/",
        "license": "MIT",
    }
    for key, expected in expected_manifest.items():
        if manifest.get(key) != expected:
            errors.append(f"plugin.json {key} must be {expected!r}")
    forbidden_manifest = {"hooks", "apps", "mcpServers"} & set(manifest)
    if forbidden_manifest:
        errors.append(f"plugin.json contains unsupported v0.1 fields: {sorted(forbidden_manifest)}")

    if marketplace.get("name") != installer.MARKETPLACE_NAME:
        errors.append("marketplace name is inconsistent")
    entries = marketplace.get("plugins") or []
    entry = next((item for item in entries if item.get("name") == installer.PLUGIN_NAME), None)
    if not entry:
        errors.append("marketplace does not contain the sol-luna plugin")
    else:
        if entry.get("source") != {"source": "local", "path": "./plugins/sol-luna"}:
            errors.append("marketplace source must be ./plugins/sol-luna")
        if entry.get("policy") != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
            errors.append("marketplace policy is inconsistent")
        if entry.get("category") != "Developer Tools":
            errors.append("marketplace category must be Developer Tools")

    skill_root = ROOT / "plugins/sol-luna/skills/sol-luna"
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    yaml_text = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
    if "[TODO" in skill_text or "TODO:" in skill_text:
        errors.append("skill contains an unfinished TODO")
    if "allow_implicit_invocation: false" not in yaml_text:
        errors.append("skill must disable implicit invocation")
    for reference in ("task-packet.md", "write-ownership.md", "verification.md", "settings.md"):
        if not (skill_root / "references" / reference).is_file():
            errors.append(f"missing skill reference: {reference}")

    settings = installer.parse_toml_file(ROOT / "config/settings.toml")
    errors.extend(f"settings: {error}" for error in installer.validate_settings_data(settings))
    for filename, name, sandbox in (
        ("sol-luna-reader.toml", "sol_luna_reader", "read-only"),
        ("sol-luna-worker.toml", "sol_luna_worker", "workspace-write"),
    ):
        errors.extend(
            f"{filename}: {error}"
            for error in installer.inspect_agent(ROOT / "config/agents" / filename, name, sandbox)
        )

    profile = installer.parse_toml_file(ROOT / "config/profiles/sol-luna.config.toml")
    if profile.get("model") != "gpt-5.6-sol":
        errors.append("optional profile must select gpt-5.6-sol")
    agents = profile.get("agents") or {}
    if agents.get("default_subagent_model") != "gpt-5.6-luna":
        errors.append("optional profile must default subagents to gpt-5.6-luna")
    if agents.get("default_subagent_reasoning_effort") != "max":
        errors.append("optional profile must default subagents to max effort")
    if agents.get("max_concurrent_threads_per_session") != installer.MAX_AGENTS:
        errors.append("optional profile concurrency must match the hard limit")

    if (ROOT / ".codex/config.toml").exists():
        errors.append("root .codex/config.toml must not exist")

    benchmark_path = ROOT / "benchmarks/tasks.jsonl"
    if benchmark_path.exists():
        tasks = [json.loads(line) for line in benchmark_path.read_text(encoding="utf-8").splitlines() if line]
        if len(tasks) != 18:
            errors.append(f"benchmark dataset must contain 18 tasks, got {len(tasks)}")
        if len({task.get("id") for task in tasks}) != len(tasks):
            errors.append("benchmark task IDs must be unique")
        categories: dict[str, int] = {}
        for task in tasks:
            category = str(task.get("category", ""))
            categories[category] = categories.get(category, 0) + 1
        if sorted(categories.values()) != [3, 3, 3, 3, 3, 3]:
            errors.append(f"benchmark categories must contain six groups of three: {categories}")

    routing_path = ROOT / "benchmarks/routing_cases.jsonl"
    if routing_path.exists():
        routing_cases = [
            json.loads(line)
            for line in routing_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if len(routing_cases) != 12:
            errors.append(f"routing contract must contain 12 cases, got {len(routing_cases)}")
        if len({case.get("id") for case in routing_cases}) != len(routing_cases):
            errors.append("routing case IDs must be unique")
        required_routing_fields = {
            "id",
            "main_model",
            "prompt",
            "expected_route",
            "min_children",
            "max_children",
            "required_final_text",
            "allowed_changed_paths",
            "validation",
        }
        for case in routing_cases:
            missing = required_routing_fields - set(case)
            if missing:
                errors.append(f"routing case {case.get('id')} misses {sorted(missing)}")
                continue
            minimum = case["min_children"]
            maximum = case["max_children"]
            if type(minimum) is not int or type(maximum) is not int:
                errors.append(f"routing case {case['id']} child bounds must be integers")
            elif not 0 <= minimum <= maximum <= installer.MAX_AGENTS:
                errors.append(f"routing case {case['id']} has invalid child bounds")

    forbidden_patterns = {
        "absolute macOS/Linux developer path": re.compile("/" + r"Users/[^/\s]+/"),
        "absolute Windows developer path": re.compile(r"[A-Za-z]:" + r"\\Users\\"),
        "GitHub token": re.compile(r"(?:gh" + r"p_|github_pat_)[A-Za-z0-9_]+"),
        "OpenAI-style secret": re.compile("s" + r"k-[A-Za-z0-9]{16,}"),
    }
    ignored_parts = {".git", "dist", "build", "__pycache__", ".pytest_cache"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ignored_parts.intersection(path.relative_to(ROOT).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in forbidden_patterns.items():
            if pattern.search(text):
                errors.append(f"{path.relative_to(ROOT)} contains {label}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
