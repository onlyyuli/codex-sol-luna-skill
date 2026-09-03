"""Evidence-backed parent/child token and credit accounting for benchmark runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RATE_CARD = ROOT / "benchmarks/credit_rates.json"
TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
TOOL_ITEM_TYPES = {"function_call", "custom_tool_call"}
PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'=])((?:\.?\.?/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+|"
    r"[A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|jsx|json|toml|ya?ml|md|sh|ps1|rs|go|java|sql))"
)


def load_rate_card(path: Path = DEFAULT_RATE_CARD) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("unit") != "credits_per_1m_tokens":
        raise ValueError(f"invalid credit rate card: {path}")
    models = value.get("models")
    if not isinstance(models, dict) or not models:
        raise ValueError(f"credit rate card has no models: {path}")
    return value


def normalize_usage(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        key: child
        for key in TOKEN_KEYS
        if type((child := source.get(key))) is int and child >= 0
    }


def estimate_credits(
    model: str,
    usage: dict[str, int],
    rate_card: dict[str, Any],
) -> Optional[float]:
    rates = rate_card.get("models", {}).get(model)
    if not isinstance(rates, dict):
        return None
    total_input = usage.get("input_tokens", 0)
    cached_input = min(usage.get("cached_input_tokens", 0), total_input)
    cache_write = min(
        usage.get("cache_write_input_tokens", 0),
        max(0, total_input - cached_input),
    )
    uncached_input = max(0, total_input - cached_input - cache_write)
    output = usage.get("output_tokens", 0)
    multiplier = rate_card.get("cache_write_multiplier", 1.0)
    if not isinstance(multiplier, (int, float)) or multiplier < 0:
        raise ValueError("cache_write_multiplier must be a non-negative number")
    credits = (
        uncached_input * float(rates["input"])
        + cached_input * float(rates["cached_input"])
        + cache_write * float(rates["input"]) * float(multiplier)
        + output * float(rates["output"])
    ) / 1_000_000
    return round(credits, 6)


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def read_rollout(path: Path) -> list[dict[str, Any]]:
    try:
        return parse_jsonl(path.read_text(encoding="utf-8"))
    except OSError:
        return []


def rollout_metadata(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    for event in events:
        if event.get("type") == "session_meta" and isinstance(event.get("payload"), dict):
            return event["payload"]
    return {}


def rollout_model_and_effort(events: Iterable[dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    model: Optional[str] = None
    effort: Optional[str] = None
    for event in events:
        if event.get("type") != "turn_context" or not isinstance(event.get("payload"), dict):
            continue
        payload = event["payload"]
        if isinstance(payload.get("model"), str):
            model = payload["model"]
        if isinstance(payload.get("effort"), str):
            effort = payload["effort"]
        collaboration = payload.get("collaboration_mode")
        if isinstance(collaboration, dict) and isinstance(collaboration.get("settings"), dict):
            settings = collaboration["settings"]
            if isinstance(settings.get("reasoning_effort"), str):
                effort = settings["reasoning_effort"]
    return model, effort


def rollout_usage(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    latest: dict[str, int] = {}
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        usage = normalize_usage(info.get("total_token_usage"))
        if usage:
            latest = usage
    return latest


def _normalized_tool_arguments(payload: dict[str, Any]) -> Any:
    raw = payload.get("arguments", payload.get("input", {}))
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return " ".join(raw.split())
    return raw


def _path_hints(value: Any) -> set[str]:
    hints: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            hints.update(_path_hints(child))
    elif isinstance(value, list):
        for child in value:
            hints.update(_path_hints(child))
    elif isinstance(value, str):
        for match in PATH_PATTERN.finditer(value):
            path = match.group(1).strip("'\".,:;()[]{}")
            if path and not path.startswith(("http://", "https://")):
                hints.add(path)
    return hints


def rollout_tool_activity(events: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    signatures: set[str] = set()
    paths: set[str] = set()
    for event in events:
        payload = event.get("payload")
        if event.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        if payload.get("type") not in TOOL_ITEM_TYPES:
            continue
        name = payload.get("name")
        namespace = payload.get("namespace")
        if not isinstance(name, str):
            continue
        tool = f"{namespace}.{name}" if isinstance(namespace, str) and namespace else name
        arguments = _normalized_tool_arguments(payload)
        canonical = json.dumps(
            {"tool": tool, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        signatures.add(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        paths.update(_path_hints(arguments))
    return {"signatures": sorted(signatures), "path_hints": sorted(paths)}


def rollout_snapshot(codex_home: Path) -> set[Path]:
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return set()
    paths: set[Path] = set()
    try:
        for path in sessions.rglob("*.jsonl"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                paths.add(path.resolve())
            except OSError:
                continue
    except OSError:
        pass
    return paths


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".codex").resolve()


def stdout_parent_thread_id(stdout: str) -> Optional[str]:
    for event in parse_jsonl(stdout):
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return event["thread_id"]
    return None


def discover_rollouts(
    codex_home: Path,
    before: set[Path],
    parent_thread_id: Optional[str],
) -> tuple[Optional[Path], list[Path]]:
    if not parent_thread_id:
        return None, []
    parent: Optional[Path] = None
    children: list[Path] = []
    for path in sorted(rollout_snapshot(codex_home) - before):
        events = read_rollout(path)
        metadata = rollout_metadata(events)
        thread_id = metadata.get("id") or metadata.get("session_id")
        if thread_id == parent_thread_id:
            parent = path
        elif metadata.get("parent_thread_id") == parent_thread_id:
            children.append(path)
    return parent, children


def summarize_rollout(path: Path, rate_card: dict[str, Any]) -> dict[str, Any]:
    events = read_rollout(path)
    metadata = rollout_metadata(events)
    model, effort = rollout_model_and_effort(events)
    usage = rollout_usage(events)
    activity = rollout_tool_activity(events)
    thread_id = metadata.get("id") or metadata.get("session_id")
    return {
        "thread_id": thread_id,
        "model": model,
        "reasoning_effort": effort,
        "usage": usage,
        "credits": estimate_credits(model, usage, rate_card) if model and usage else None,
        "tool_signatures": activity["signatures"],
        "path_hints": activity["path_hints"],
    }


def account_rollouts(
    parent_path: Optional[Path],
    child_paths: list[Path],
    *,
    expected_children: int,
    rate_card: dict[str, Any],
) -> dict[str, Any]:
    parent = summarize_rollout(parent_path, rate_card) if parent_path else None
    children = [summarize_rollout(path, rate_card) for path in child_paths]
    parent_signatures = set(parent["tool_signatures"]) if parent else set()
    child_signatures = {
        signature for child in children for signature in child["tool_signatures"]
    }
    parent_paths = set(parent["path_hints"]) if parent else set()
    child_paths_seen = {path for child in children for path in child["path_hints"]}
    duplicate_signatures = parent_signatures.intersection(child_signatures)
    overlapping_paths = parent_paths.intersection(child_paths_seen)
    complete = bool(
        parent
        and parent.get("credits") is not None
        and len(children) == expected_children
        and all(child.get("credits") is not None for child in children)
    )
    parent_credits = parent.get("credits") if parent else None
    child_credits = (
        round(sum(float(child["credits"]) for child in children), 6)
        if all(child.get("credits") is not None for child in children)
        else None
    )
    total_credits = (
        round(float(parent_credits) + float(child_credits), 6)
        if complete and parent_credits is not None and child_credits is not None
        else None
    )
    return {
        "complete": complete,
        "evidence_source": "persisted_rollouts",
        "rate_card_effective_date": rate_card.get("effective_date"),
        "rate_card_source": rate_card.get("source_url"),
        "parent": parent,
        "children": children,
        "parent_credits": parent_credits,
        "child_credits": child_credits,
        "total_credits": total_credits,
        "duplicate_tool_call_count": len(duplicate_signatures),
        "overlapping_path_count": len(overlapping_paths),
        "economy_failure": bool(duplicate_signatures),
    }


def account_cli_parent_only(
    stdout_usage: dict[str, int],
    *,
    main_model: str,
    expected_children: int,
    rate_card: dict[str, Any],
) -> dict[str, Any]:
    usage = normalize_usage(stdout_usage)
    parent_credits = estimate_credits(main_model, usage, rate_card) if usage else None
    complete = expected_children == 0 and parent_credits is not None
    return {
        "complete": complete,
        "evidence_source": "cli_parent_only",
        "rate_card_effective_date": rate_card.get("effective_date"),
        "rate_card_source": rate_card.get("source_url"),
        "parent": {
            "thread_id": stdout_parent_thread_id(""),
            "model": main_model,
            "reasoning_effort": None,
            "usage": usage,
            "credits": parent_credits,
            "tool_signatures": [],
            "path_hints": [],
        },
        "children": [],
        "parent_credits": parent_credits,
        "child_credits": 0.0 if expected_children == 0 else None,
        "total_credits": parent_credits if complete else None,
        "duplicate_tool_call_count": 0,
        "overlapping_path_count": 0,
        "economy_failure": False,
    }
