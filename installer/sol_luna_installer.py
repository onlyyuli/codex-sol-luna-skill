#!/usr/bin/env python3
"""Managed installer and doctor for the codex-sol-luna workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # Python 3.9 and 3.10
    _tomllib = None


VERSION = "0.1.0"
PLUGIN_NAME = "sol-luna"
MARKETPLACE_NAME = "codex-sol-luna"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
REPOSITORY_PLACEHOLDER = "__GITHUB_REPOSITORY__"
REF_PLACEHOLDER = "__SOL_LUNA_REF__"
DEFAULT_REF = f"v{VERSION}"
MAX_AGENTS = 8

RESOURCE_TARGETS = (
    ("config/agents/sol-luna-reader.toml", "agents/sol-luna-reader.toml", "agent"),
    ("config/agents/sol-luna-worker.toml", "agents/sol-luna-worker.toml", "agent"),
    ("config/settings.toml", "sol-luna/settings.toml", "settings"),
)
PROFILE_RESOURCE = (
    "config/profiles/sol-luna.config.toml",
    "sol-luna.config.toml",
    "profile",
)
SETTINGS_KEYS = {
    "auto_min_agents",
    "auto_max_agents",
    "hard_max_agents",
    "write_parallelism",
    "strict_model",
    "announce_route",
}


class InstallerError(RuntimeError):
    """A safe, user-actionable installer failure."""


@dataclass
class Check:
    name: str
    status: str
    detail: str


class Reporter:
    def __init__(self, json_output: bool = False) -> None:
        self.json_output = json_output
        self.events: list[dict[str, str]] = []

    def emit(self, level: str, message: str) -> None:
        self.events.append({"level": level, "message": message})
        if not self.json_output:
            print(f"[{level.upper()}] {message}")

    def finish(self, payload: dict[str, Any]) -> None:
        if self.json_output:
            print(json.dumps({"events": self.events, **payload}, ensure_ascii=False, indent=2))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise InstallerError(f"Refusing to replace symlink: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, ValueError):
        return False
    return True


def require_managed_path(path: Path, codex_home: Path) -> None:
    if not path.is_absolute() or not path_is_within(path, codex_home):
        raise InstallerError(f"Managed path escapes CODEX_HOME: {path}")


def command_env(codex_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    return env


def run_command(
    command: list[str],
    *,
    codex_home: Optional[Path] = None,
    cwd: Optional[Path] = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = command_env(codex_home) if codex_home else None
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown command failure"
        raise InstallerError(f"Command failed ({' '.join(command)}): {detail}")
    return result


def command_json(command: list[str], codex_home: Path) -> dict[str, Any]:
    result = run_command(command, codex_home=codex_home)
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise InstallerError(f"Command returned invalid JSON ({' '.join(command)}): {exc}") from exc
    if not isinstance(value, dict):
        raise InstallerError(f"Command returned a non-object JSON value: {' '.join(command)}")
    return value


def codex_path() -> str:
    executable = shutil.which("codex")
    if not executable:
        raise InstallerError("Codex CLI was not found on PATH.")
    return executable


def state_path(codex_home: Path) -> Path:
    return codex_home / "sol-luna" / "install-state.json"


def read_state(codex_home: Path) -> dict[str, Any]:
    path = state_path(codex_home)
    require_managed_path(path, codex_home)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerError(f"Cannot read installer state at {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise InstallerError(f"Unsupported installer state at {path}")
    return value


def write_state(codex_home: Path, state: dict[str, Any]) -> None:
    require_managed_path(state_path(codex_home), codex_home)
    data = (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    atomic_write(state_path(codex_home), data)


def parse_repository_from_remote(remote: str) -> Optional[str]:
    remote = remote.strip()
    patterns = (
        r"^https://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, remote)
        if match:
            return match.group(1)
    return None


def validate_repository(value: str) -> str:
    value = value.strip().removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise InstallerError(f"Repository must be an owner/name GitHub identifier, got: {value!r}")
    return value


def discover_repo_root(script_path: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / ".agents/plugins/marketplace.json").is_file():
            raise InstallerError(f"Not a codex-sol-luna repository root: {root}")
        return root
    candidate = script_path.resolve().parents[1]
    if (candidate / ".agents/plugins/marketplace.json").is_file():
        return candidate
    return None


def resolve_repository(explicit: Optional[str], repo_root: Optional[Path]) -> str:
    if explicit:
        return validate_repository(explicit)
    env_value = os.environ.get("SOL_LUNA_REPOSITORY", "").strip()
    if env_value and env_value != REPOSITORY_PLACEHOLDER:
        return validate_repository(env_value)
    embedded = REPOSITORY_PLACEHOLDER
    if embedded != "__" + "GITHUB_REPOSITORY__":
        return validate_repository(embedded)
    if repo_root and (repo_root / ".git").exists():
        result = run_command(
            ["git", "remote", "get-url", "origin"], cwd=repo_root, check=False
        )
        if result.returncode == 0:
            parsed = parse_repository_from_remote(result.stdout)
            if parsed:
                return validate_repository(parsed)
    raise InstallerError(
        "Cannot determine the GitHub repository. Pass --repository owner/name or set "
        "SOL_LUNA_REPOSITORY."
    )


def resolve_ref(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env_value = os.environ.get("SOL_LUNA_REF", "").strip()
    if env_value and env_value != REF_PLACEHOLDER:
        return env_value
    embedded = REF_PLACEHOLDER
    if embedded != "__" + "SOL_LUNA_REF__":
        return embedded
    return DEFAULT_REF


def read_resource(
    relative_path: str,
    *,
    repo_root: Optional[Path],
    repository: str,
    ref: str,
) -> bytes:
    if repo_root:
        path = (repo_root / relative_path).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise InstallerError(f"Resource escapes repository root: {relative_path}") from exc
        if path.is_file():
            return path.read_bytes()
    url = f"https://raw.githubusercontent.com/{repository}/{ref}/{relative_path}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise InstallerError(f"Cannot download {relative_path} from {repository}@{ref}: {exc}") from exc


def normalize_marketplace_source(value: str) -> str:
    normalized = value.strip().removesuffix(".git").removesuffix("/")
    normalized = re.sub(r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)", "", normalized)
    return normalized


def marketplace_source_matches(actual: str, expected: str, source_type: str) -> bool:
    if source_type == "local":
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected):
            return False
        try:
            return Path(actual).expanduser().resolve() == Path(expected).expanduser().resolve()
        except OSError:
            return False
    return normalize_marketplace_source(actual) == normalize_marketplace_source(expected)


def marketplace_map(codex: str, codex_home: Path) -> dict[str, dict[str, Any]]:
    payload = command_json([codex, "plugin", "marketplace", "list", "--json"], codex_home)
    entries = payload.get("marketplaces", [])
    return {
        item["name"]: item
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


def installed_plugins(codex: str, codex_home: Path) -> list[dict[str, Any]]:
    payload = command_json([codex, "plugin", "list", "--json"], codex_home)
    entries = payload.get("installed", [])
    return [item for item in entries if isinstance(item, dict)]


def ensure_marketplace(
    codex: str,
    codex_home: Path,
    repository: str,
    ref: str,
    repo_root: Optional[Path],
    reporter: Reporter,
    upgrade: bool,
) -> bool:
    existing = marketplace_map(codex, codex_home).get(MARKETPLACE_NAME)
    requested_source = str(repo_root) if repo_root else repository
    if existing:
        source_data = existing.get("marketplaceSource") or {}
        actual_source = str(source_data.get("source") or existing.get("root") or "")
        actual_normalized = normalize_marketplace_source(actual_source)
        requested_normalized = normalize_marketplace_source(requested_source)
        same_local_path = False
        if repo_root:
            try:
                same_local_path = Path(actual_source).resolve() == repo_root.resolve()
            except OSError:
                same_local_path = False
        if actual_normalized != requested_normalized and not same_local_path:
            raise InstallerError(
                f"Marketplace name {MARKETPLACE_NAME!r} already points to {actual_source!r}, "
                f"not {requested_source!r}."
            )
        reporter.emit("ok", f"Marketplace {MARKETPLACE_NAME} already uses the requested source.")
        if upgrade and source_data.get("sourceType") != "local":
            run_command(
                [codex, "plugin", "marketplace", "upgrade", MARKETPLACE_NAME],
                codex_home=codex_home,
            )
            reporter.emit("ok", f"Marketplace {MARKETPLACE_NAME} refreshed.")
        return False

    command = [codex, "plugin", "marketplace", "add"]
    if repo_root:
        command.extend([str(repo_root), "--json"])
    else:
        command.extend([repository, "--ref", ref, "--json"])
    result = command_json(command, codex_home)
    if result.get("marketplaceName") != MARKETPLACE_NAME:
        raise InstallerError(
            f"Marketplace source reported {result.get('marketplaceName')!r}; expected {MARKETPLACE_NAME!r}."
        )
    reporter.emit("ok", f"Marketplace {MARKETPLACE_NAME} added.")
    return True


def ensure_plugin(codex: str, codex_home: Path, reporter: Reporter) -> None:
    result = command_json([codex, "plugin", "add", PLUGIN_ID, "--json"], codex_home)
    if result.get("pluginId") != PLUGIN_ID:
        raise InstallerError(f"Codex installed an unexpected plugin: {result!r}")
    reporter.emit("ok", f"Plugin {PLUGIN_ID} installed at version {result.get('version', 'unknown')}.")


def rotate_owned_marketplace_ref(
    codex: str,
    codex_home: Path,
    *,
    state: dict[str, Any],
    repository: str,
    ref: str,
    reporter: Reporter,
) -> bool:
    """Replace an installer-owned Git marketplace when its pinned ref changes.

    Codex refreshes a marketplace at its configured ref, so moving from one fixed
    release tag to another requires replacing that source. The operation is only
    allowed when the installer owns the marketplace and no unrelated plugin uses it.
    """
    old_ref = state.get("ref")
    if not isinstance(old_ref, str) or not old_ref or old_ref == ref:
        return False
    if state.get("repository") != repository:
        raise InstallerError(
            "Refusing to rotate a marketplace recorded for a different repository."
        )
    if not state.get("marketplace_added"):
        raise InstallerError(
            "Cannot change the pinned release because the marketplace was not created "
            "by this installer. Remove it manually or reinstall with a distinct CODEX_HOME."
        )

    existing = marketplace_map(codex, codex_home).get(MARKETPLACE_NAME)
    if not existing:
        return False
    source_data = existing.get("marketplaceSource") or {}
    source_type = str(source_data.get("sourceType") or "")
    actual_source = str(source_data.get("source") or existing.get("root") or "")
    if source_type == "local" or not marketplace_source_matches(
        actual_source, repository, source_type
    ):
        raise InstallerError(
            f"Refusing to replace marketplace {MARKETPLACE_NAME!r} from unexpected source "
            f"{actual_source!r}."
        )

    plugins = installed_plugins(codex, codex_home)
    marketplace_plugins = [
        item for item in plugins if item.get("marketplaceName") == MARKETPLACE_NAME
    ]
    unrelated = [item for item in marketplace_plugins if item.get("pluginId") != PLUGIN_ID]
    if unrelated:
        names = ", ".join(str(item.get("pluginId", "unknown")) for item in unrelated)
        raise InstallerError(
            "Cannot rotate the pinned marketplace while unrelated plugins use it: " + names
        )
    plugin_was_installed = any(item.get("pluginId") == PLUGIN_ID for item in marketplace_plugins)

    if plugin_was_installed:
        command_json([codex, "plugin", "remove", PLUGIN_ID, "--json"], codex_home)
    command_json(
        [codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"],
        codex_home,
    )
    try:
        added = command_json(
            [codex, "plugin", "marketplace", "add", repository, "--ref", ref, "--json"],
            codex_home,
        )
        if added.get("marketplaceName") != MARKETPLACE_NAME:
            raise InstallerError(
                f"Replacement source reported {added.get('marketplaceName')!r}; expected "
                f"{MARKETPLACE_NAME!r}."
            )
        ensure_plugin(codex, codex_home, reporter)
    except (InstallerError, subprocess.TimeoutExpired) as exc:
        reporter.emit(
            "warning",
            f"Upgrade to {ref} failed; attempting to restore marketplace ref {old_ref}.",
        )
        rollback_errors = []
        try:
            if MARKETPLACE_NAME in marketplace_map(codex, codex_home):
                command_json(
                    [codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"],
                    codex_home,
                )
            restored = command_json(
                [
                    codex,
                    "plugin",
                    "marketplace",
                    "add",
                    repository,
                    "--ref",
                    old_ref,
                    "--json",
                ],
                codex_home,
            )
            if restored.get("marketplaceName") != MARKETPLACE_NAME:
                rollback_errors.append("restored marketplace reported an unexpected name")
            elif plugin_was_installed:
                ensure_plugin(codex, codex_home, reporter)
        except (InstallerError, subprocess.TimeoutExpired) as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            raise InstallerError(
                f"Upgrade failed ({exc}); rollback also failed: {'; '.join(rollback_errors)}"
            ) from exc
        raise InstallerError(f"Upgrade failed and the previous ref was restored: {exc}") from exc

    reporter.emit("ok", f"Marketplace moved from {old_ref} to {ref}.")
    return True


def install_managed_file(
    destination: Path,
    data: bytes,
    source: str,
    kind: str,
    previous: Optional[dict[str, Any]],
    reporter: Reporter,
) -> dict[str, str]:
    desired_hash = sha256_bytes(data)
    previous_hash = str((previous or {}).get("sha256", ""))
    previously_managed = bool(previous) and (previous or {}).get("status", "managed") == "managed"
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink():
            raise InstallerError(f"Refusing to manage symlink: {destination}")
        if not destination.is_file():
            raise InstallerError(f"Refusing to replace non-regular path: {destination}")
        current_hash = sha256_file(destination)
        if previously_managed and current_hash == desired_hash:
            reporter.emit("ok", f"Managed file already current: {destination}")
        elif previously_managed and previous_hash and current_hash == previous_hash:
            atomic_write(destination, data)
            reporter.emit("ok", f"Updated managed file: {destination}")
        else:
            reporter.emit("warning", f"Preserved user-modified or unmanaged file: {destination}")
            return {
                "sha256": current_hash,
                "source": source,
                "kind": kind,
                "status": "preserved",
            }
    else:
        atomic_write(destination, data)
        reporter.emit("ok", f"Installed managed file: {destination}")
    return {"sha256": desired_hash, "source": source, "kind": kind, "status": "managed"}


def install_resources(
    codex_home: Path,
    state: dict[str, Any],
    *,
    repo_root: Optional[Path],
    repository: str,
    ref: str,
    with_profile: bool,
    reporter: Reporter,
) -> dict[str, dict[str, str]]:
    previous_files = state.get("managed_files", {}) if isinstance(state, dict) else {}
    if not isinstance(previous_files, dict):
        previous_files = {}
    resources = list(RESOURCE_TARGETS)
    if with_profile:
        resources.append(PROFILE_RESOURCE)
    managed: dict[str, dict[str, str]] = {}
    for source, relative_destination, kind in resources:
        destination = codex_home / relative_destination
        require_managed_path(destination, codex_home)
        data = read_resource(source, repo_root=repo_root, repository=repository, ref=ref)
        managed[str(destination)] = install_managed_file(
            destination,
            data,
            source,
            kind,
            previous_files.get(str(destination)),
            reporter,
        )
    for path, record in previous_files.items():
        if path not in managed and isinstance(record, dict):
            require_managed_path(Path(path), codex_home)
            managed[path] = record
    return managed


def validate_settings_data(value: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["settings root must be a TOML table"]
    unknown = set(value) - SETTINGS_KEYS
    if unknown:
        errors.append(f"unknown settings keys: {', '.join(sorted(unknown))}")
    limit_types_valid = True
    for key in ("auto_min_agents", "auto_max_agents", "hard_max_agents"):
        if type(value.get(key)) is not int:
            errors.append(f"{key} must be an integer")
            limit_types_valid = False
    if limit_types_valid:
        minimum = value["auto_min_agents"]
        automatic_max = value["auto_max_agents"]
        hard_max = value["hard_max_agents"]
        if not (1 <= minimum <= automatic_max <= hard_max <= MAX_AGENTS):
            errors.append("agent limits must satisfy 1 <= min <= auto max <= hard max <= 8")
    if value.get("write_parallelism") not in {"off", "disjoint-only"}:
        errors.append('write_parallelism must be "off" or "disjoint-only"')
    for key in ("strict_model", "announce_route"):
        if type(value.get(key)) is not bool:
            errors.append(f"{key} must be a boolean")
    return errors


def _strip_toml_comment(line: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {'"', "'"}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
            continue
        if char == "#" and quote is None:
            return line[:index]
    return line


def _simple_toml_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    if raw == "true":
        return True
    if raw == "false":
        return False
    if re.fullmatch(r"[-+]?[0-9]+", raw):
        return int(raw)
    return raw


def _simple_toml_load(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current = root
    multiline_key: Optional[str] = None
    multiline_delimiter = ""
    multiline_parts: list[str] = []
    for line_number, original in enumerate(text.splitlines(), start=1):
        stripped = original.strip()
        if multiline_key is not None:
            if multiline_delimiter in stripped:
                before = stripped.split(multiline_delimiter, 1)[0]
                multiline_parts.append(before)
                current[multiline_key] = "\n".join(multiline_parts)
                multiline_key = None
                multiline_parts = []
            else:
                multiline_parts.append(original)
            continue
        line = _strip_toml_comment(original).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section:
                raise ValueError(f"empty TOML section at line {line_number}")
            current = root
            for raw_part in section.split("."):
                part = raw_part.strip().strip('"').strip("'")
                child = current.setdefault(part, {})
                if not isinstance(child, dict):
                    raise ValueError(f"invalid TOML section at line {line_number}")
                current = child
            continue
        if "=" not in line:
            raise ValueError(f"unsupported TOML syntax at line {line_number}")
        key, raw_value = line.split("=", 1)
        key = key.strip().strip('"').strip("'")
        raw_value = raw_value.strip()
        if raw_value.startswith(('"""', "'''")):
            delimiter = raw_value[:3]
            remainder = raw_value[3:]
            if delimiter in remainder:
                current[key] = remainder.split(delimiter, 1)[0]
            else:
                multiline_key = key
                multiline_delimiter = delimiter
                multiline_parts = [remainder] if remainder else []
            continue
        current[key] = _simple_toml_scalar(raw_value)
    if multiline_key is not None:
        raise ValueError(f"unterminated multiline TOML value for {multiline_key}")
    return root


def parse_toml_file(path: Path) -> dict[str, Any]:
    if _tomllib is not None:
        with path.open("rb") as handle:
            value = _tomllib.load(handle)
    else:
        value = _simple_toml_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise InstallerError(f"TOML root must be a table: {path}")
    return value


def inspect_agent(path: Path, expected_name: str, expected_sandbox: str) -> list[str]:
    try:
        value = parse_toml_file(path)
    except (OSError, ValueError, InstallerError) as exc:
        return [str(exc)]
    errors = []
    expected = {
        "name": expected_name,
        "model": "gpt-5.6-luna",
        "model_reasoning_effort": "max",
        "sandbox_mode": expected_sandbox,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            errors.append(f"{key} must be {expected_value!r}")
    for required in ("description", "developer_instructions"):
        if not isinstance(value.get(required), str) or not value[required].strip():
            errors.append(f"{required} must be a non-empty string")
    return errors


def find_project_config(start: Path) -> Optional[Path]:
    current = start.resolve()
    while True:
        candidate = current / ".codex" / "config.toml"
        if candidate.is_file():
            return candidate
        if (current / ".git").exists() or current.parent == current:
            return None
        current = current.parent


def metadata_values(value: Any, accepted_keys: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in accepted_keys and isinstance(child, str):
                found.add(child)
            found.update(metadata_values(child, accepted_keys))
    elif isinstance(value, list):
        for child in value:
            found.update(metadata_values(child, accepted_keys))
    return found


def inspect_cached_luna_model(codex_home: Path) -> Check:
    cache = codex_home / "models_cache.json"
    if not cache.is_file():
        return Check(
            "Luna model catalog",
            "warning",
            "models_cache.json is unavailable; use --smoke-models for an account-level check",
        )
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return Check("Luna model catalog", "warning", f"cannot read model cache: {exc}")
    models = payload.get("models", []) if isinstance(payload, dict) else []
    luna = next(
        (
            item
            for item in models
            if isinstance(item, dict) and item.get("slug") == "gpt-5.6-luna"
        ),
        None,
    )
    if not luna:
        return Check(
            "Luna model catalog",
            "warning",
            "gpt-5.6-luna is absent from the local model cache; access is not proven",
        )
    efforts = {
        item.get("effort")
        for item in luna.get("supported_reasoning_levels", [])
        if isinstance(item, dict)
    }
    if "max" not in efforts:
        return Check(
            "Luna model catalog",
            "warning",
            "gpt-5.6-luna is cached but max reasoning is not advertised",
        )
    return Check(
        "Luna model catalog",
        "ok",
        "local catalog advertises gpt-5.6-luna with max; runtime use still requires smoke evidence",
    )


def smoke_models(codex: str, codex_home: Path, cwd: Path) -> Check:
    login = run_command(
        [codex, "login", "status"],
        codex_home=codex_home,
        cwd=cwd,
        timeout=15,
        check=False,
    )
    if login.returncode != 0:
        detail = login.stderr.strip() or login.stdout.strip() or "not logged in"
        return Check(
            "model smoke",
            "error",
            f"Codex is not logged in for {codex_home}: {detail}",
        )
    prompt = (
        "Your first action must be to call the spawn_agent collaboration tool exactly once for "
        "one leaf subagent using model gpt-5.6-luna and reasoning_effort max. Ask the child to "
        "return only LUNA_SMOKE_OK without reading or writing files. Do not call wait_agent unless "
        "spawning returns a non-empty child thread ID. Never produce LUNA_SMOKE_OK yourself: "
        "return SUBAGENT_SMOKE_FAILED if no child starts. Wait for the real child, then report "
        "its marker."
    )
    command = [
        codex,
        "exec",
        "--enable",
        "multi_agent",
        "--json",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--model",
        "gpt-5.6-sol",
        "--config",
        "agents.enabled=true",
        "--config",
        'agents.default_subagent_model="gpt-5.6-luna"',
        "--config",
        'agents.default_subagent_reasoning_effort="max"',
        prompt,
    ]
    try:
        result = run_command(command, codex_home=codex_home, cwd=cwd, timeout=300, check=False)
    except subprocess.TimeoutExpired:
        return Check("model smoke", "error", "Codex model smoke timed out after 300 seconds.")
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown failure"
        return Check("model smoke", "error", f"Codex smoke run failed: {detail}")
    events = []
    for line in result.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    child_thread_ids: set[str] = set()
    messages: list[str] = []
    collaboration_events = 0
    activity_errors: list[str] = []
    for event in events:
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict):
            continue
        receiver_ids = item.get("receiver_thread_ids")
        if isinstance(receiver_ids, list):
            collaboration_events += 1
            child_thread_ids.update(
                value for value in receiver_ids if isinstance(value, str) and value
            )
        for key in ("error", "failure", "detail"):
            if isinstance(item.get(key), str) and item[key].strip():
                activity_errors.append(item[key].strip())
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            messages.append(item["text"])
    if len(child_thread_ids) != 1:
        context = []
        if collaboration_events:
            context.append(f"collaboration events: {collaboration_events}")
        if activity_errors:
            context.append("activity error: " + activity_errors[-1][:240])
        if messages:
            context.append("last agent message: " + " ".join(messages[-1].split())[:240])
        suffix = "; " + "; ".join(context) if context else ""
        return Check(
            "model smoke",
            "error",
            "Activity did not prove exactly one spawned subagent; "
            f"observed {len(child_thread_ids)} child thread IDs{suffix}.",
        )
    if not any("LUNA_SMOKE_OK" in message for message in messages):
        return Check(
            "model smoke",
            "error",
            "A child thread was observed, but the expected smoke marker was not returned.",
        )
    child_activity: list[Any] = []
    for event in events:
        item = event.get("item") if isinstance(event, dict) else None
        if not isinstance(item, dict):
            continue
        receivers = item.get("receiver_thread_ids")
        if isinstance(receivers, list) and child_thread_ids.intersection(receivers):
            child_activity.append(item)
    models = metadata_values(
        child_activity, {"model", "model_name", "model_slug", "selected_model"}
    )
    efforts = metadata_values(
        child_activity, {"model_reasoning_effort", "reasoning_effort"}
    )
    if "gpt-5.6-luna" not in models:
        return Check(
            "model smoke",
            "error",
            "One child thread completed, but JSONL activity did not prove its effective model; "
            "GPT-5.6 Luna Max was requested.",
        )
    if "max" not in efforts:
        return Check(
            "model smoke",
            "error",
            "Activity proved GPT-5.6 Luna, but max effort was requested and not proven.",
        )
    return Check("model smoke", "ok", "Activity proved GPT-5.6 Luna and max effort.")


def run_doctor(
    codex_home: Path,
    *,
    cwd: Path,
    smoke: bool,
    repository: Optional[str],
    marketplace_source: Optional[str] = None,
) -> list[Check]:
    checks: list[Check] = []
    codex = shutil.which("codex")
    if not codex:
        return [Check("Codex CLI", "error", "codex is not available on PATH")]
    try:
        state = read_state(codex_home)
    except InstallerError as exc:
        checks.append(Check("installer state", "error", str(exc)))
        state = {}
    if marketplace_source is None and state:
        candidate = state.get("marketplace_source") or state.get("repository")
        if isinstance(candidate, str) and candidate:
            marketplace_source = candidate
    version = run_command([codex, "--version"], codex_home=codex_home, check=False)
    checks.append(
        Check(
            "Codex CLI",
            "ok" if version.returncode == 0 else "error",
            version.stdout.strip() or version.stderr.strip(),
        )
    )
    plugin_help = run_command([codex, "plugin", "--help"], codex_home=codex_home, check=False)
    checks.append(
        Check(
            "plugin capability",
            "ok" if plugin_help.returncode == 0 else "error",
            "codex plugin is available" if plugin_help.returncode == 0 else "codex plugin is unavailable",
        )
    )
    features = run_command([codex, "features", "list"], codex_home=codex_home, check=False)
    multi_agent_enabled = bool(
        features.returncode == 0
        and re.search(r"^multi_agent\s+\S+\s+true\s*$", features.stdout, re.MULTILINE)
    )
    checks.append(
        Check(
            "subagent capability",
            "ok" if multi_agent_enabled else "error",
            "multi_agent capability is enabled"
            if multi_agent_enabled
            else "Codex did not report an enabled multi_agent capability",
        )
    )
    checks.append(inspect_cached_luna_model(codex_home))
    if plugin_help.returncode == 0:
        try:
            market = marketplace_map(codex, codex_home).get(MARKETPLACE_NAME)
            if not market:
                checks.append(Check("marketplace", "error", f"{MARKETPLACE_NAME} is not configured"))
            else:
                source_data = market.get("marketplaceSource") or {}
                actual = str(source_data.get("source") or market.get("root") or "unknown")
                status = "ok"
                detail = f"configured from {actual}"
                expected_source = marketplace_source or repository
                if expected_source and not marketplace_source_matches(
                    actual, expected_source, str(source_data.get("sourceType") or "")
                ):
                    status = "error"
                    detail = f"configured from unexpected source {actual}"
                checks.append(Check("marketplace", status, detail))
            plugin = next(
                (entry for entry in installed_plugins(codex, codex_home) if entry.get("pluginId") == PLUGIN_ID),
                None,
            )
            if plugin:
                status = "ok" if plugin.get("version") == VERSION else "error"
                checks.append(Check("plugin", status, f"installed version {plugin.get('version', 'unknown')}"))
            else:
                checks.append(Check("plugin", "error", f"{PLUGIN_ID} is not installed"))
        except InstallerError as exc:
            checks.append(Check("plugin state", "error", str(exc)))

    agents = (
        (codex_home / "agents/sol-luna-reader.toml", "sol_luna_reader", "read-only"),
        (codex_home / "agents/sol-luna-worker.toml", "sol_luna_worker", "workspace-write"),
    )
    for path, expected_name, sandbox in agents:
        if not path.exists():
            checks.append(Check(expected_name, "error", f"not installed at {path}"))
            continue
        errors = inspect_agent(path, expected_name, sandbox)
        checks.append(Check(expected_name, "error" if errors else "ok", "; ".join(errors) or "valid"))

    settings = codex_home / "sol-luna/settings.toml"
    if not settings.exists():
        checks.append(Check("settings", "error", f"not installed at {settings}"))
    else:
        try:
            errors = validate_settings_data(parse_toml_file(settings))
        except (OSError, ValueError, InstallerError) as exc:
            errors = [str(exc)]
        checks.append(Check("settings", "error" if errors else "ok", "; ".join(errors) or "valid"))

    base_config = codex_home / "config.toml"
    if base_config.exists():
        try:
            config = parse_toml_file(base_config)
            if config.get("model") == "gpt-5.6-luna":
                checks.append(
                    Check(
                        "main model",
                        "warning",
                        "base config pins the main thread to gpt-5.6-luna; the plugin does not change it",
                    )
                )
            else:
                checks.append(Check("main model", "ok", "no base Luna main-model pin detected"))
            agents_config = config.get("agents") or {}
            if isinstance(agents_config, dict) and agents_config.get("enabled") is False:
                checks.append(Check("subagents enabled", "warning", "base config disables subagent tools"))
            if isinstance(agents_config, dict):
                concurrency = agents_config.get("max_concurrent_threads_per_session")
                if concurrency is None:
                    concurrency = agents_config.get("max_threads")
                if type(concurrency) is int and concurrency > MAX_AGENTS:
                    checks.append(
                        Check(
                            "subagent concurrency",
                            "warning",
                            f"base config allows {concurrency} concurrent child threads; workflow cap is 8",
                        )
                    )
        except (OSError, ValueError, InstallerError) as exc:
            checks.append(Check("base config", "error", str(exc)))

    project_config = find_project_config(cwd)
    if project_config:
        try:
            value = parse_toml_file(project_config)
            if "model" in value:
                checks.append(
                    Check(
                        "project model override",
                        "warning",
                        f"{project_config} selects model {value.get('model')!r}",
                    )
                )
        except (OSError, ValueError, InstallerError) as exc:
            checks.append(Check("project config", "error", str(exc)))

    if state:
        modified = []
        preserved = []
        unsafe = []
        for raw_path, record in (state.get("managed_files") or {}).items():
            path = Path(raw_path)
            if not path.is_absolute() or not path_is_within(path, codex_home):
                unsafe.append(str(path))
                continue
            expected = str(record.get("sha256", "")) if isinstance(record, dict) else ""
            if isinstance(record, dict) and record.get("status") == "preserved":
                preserved.append(str(path))
                continue
            if path.exists() and (
                not path.is_file() or not expected or sha256_file(path) != expected
            ):
                modified.append(str(path))
        details = []
        if unsafe:
            details.append("unsafe state paths: " + ", ".join(unsafe))
        if preserved:
            details.append("preserved/unmanaged: " + ", ".join(preserved))
        if modified:
            details.append("modified: " + ", ".join(modified))
        checks.append(
            Check(
                "managed files",
                "error" if unsafe else ("warning" if details else "ok"),
                "; ".join(details) if details else "all installed files match state",
            )
        )
    if smoke:
        checks.append(smoke_models(codex, codex_home, cwd))
    return checks


def install_or_upgrade(args: argparse.Namespace, reporter: Reporter, upgrade: bool) -> dict[str, Any]:
    codex_home = Path(args.codex_home).expanduser().resolve()
    codex_home.mkdir(parents=True, exist_ok=True)
    repo_root = discover_repo_root(Path(__file__), args.repo_root)
    repository = resolve_repository(args.repository, repo_root)
    ref = resolve_ref(args.ref)
    codex = codex_path()
    state = read_state(codex_home)
    previously_added = bool(state.get("marketplace_added", False))

    base_config = codex_home / "config.toml"
    base_before = base_config.read_bytes() if base_config.exists() else b""
    rotated = bool(
        upgrade
        and not args.local_marketplace
        and rotate_owned_marketplace_ref(
            codex,
            codex_home,
            state=state,
            repository=repository,
            ref=ref,
            reporter=reporter,
        )
    )
    added_now = ensure_marketplace(
        codex,
        codex_home,
        repository,
        ref,
        repo_root if args.local_marketplace else None,
        reporter,
        upgrade and not rotated,
    )
    if not rotated:
        ensure_plugin(codex, codex_home, reporter)
    managed = install_resources(
        codex_home,
        state,
        repo_root=repo_root,
        repository=repository,
        ref=ref,
        with_profile=args.with_cli_profile or bool(state.get("with_cli_profile", False)),
        reporter=reporter,
    )
    new_state = {
        "schema_version": 1,
        "installer_version": VERSION,
        "repository": repository,
        "ref": ref,
        "marketplace_source": str(repo_root) if args.local_marketplace and repo_root else repository,
        "marketplace_name": MARKETPLACE_NAME,
        "marketplace_added": previously_added or added_now,
        "plugin_id": PLUGIN_ID,
        "with_cli_profile": args.with_cli_profile or bool(state.get("with_cli_profile", False)),
        "managed_files": managed,
    }
    write_state(codex_home, new_state)

    base_after = base_config.read_bytes() if base_config.exists() else b""
    if base_before != base_after:
        reporter.emit(
            "info",
            "Codex CLI updated only its marketplace/plugin namespace in config.toml; existing "
            "main-model and permission settings were not edited by this installer.",
        )
    checks = run_doctor(
        codex_home,
        cwd=Path.cwd(),
        smoke=False,
        repository=repository,
        marketplace_source=str(repo_root) if args.local_marketplace and repo_root else repository,
    )
    failures = [check for check in checks if check.status == "error"]
    for check in checks:
        reporter.emit(check.status, f"doctor/{check.name}: {check.detail}")
    if failures:
        raise InstallerError("Post-install doctor reported errors.")
    reporter.emit("ok", "Installation complete. Start a new Codex task before invoking $sol-luna.")
    return {"status": "ok", "action": "upgrade" if upgrade else "install", "state": new_state}


def uninstall(args: argparse.Namespace, reporter: Reporter) -> dict[str, Any]:
    codex_home = Path(args.codex_home).expanduser().resolve()
    state = read_state(codex_home)
    codex = shutil.which("codex")
    plugin_pending = False
    marketplace_pending = False
    if codex:
        try:
            plugins = installed_plugins(codex, codex_home)
            if any(entry.get("pluginId") == PLUGIN_ID for entry in plugins):
                command_json([codex, "plugin", "remove", PLUGIN_ID, "--json"], codex_home)
                reporter.emit("ok", f"Removed plugin {PLUGIN_ID}.")
            else:
                reporter.emit("ok", f"Plugin {PLUGIN_ID} was already absent.")
        except InstallerError as exc:
            plugin_pending = True
            reporter.emit("warning", f"Could not remove plugin through Codex CLI: {exc}")
    else:
        plugin_pending = True
        reporter.emit("warning", "Codex CLI is unavailable; plugin cache/config removal was skipped.")

    preserved: dict[str, Any] = {}
    for raw_path, record in (state.get("managed_files") or {}).items():
        if not isinstance(record, dict):
            continue
        path = Path(raw_path)
        expected = str(record.get("sha256", ""))
        if not path.is_absolute() or not path_is_within(path, codex_home):
            preserved[raw_path] = record
            reporter.emit("warning", f"Preserved unsafe out-of-scope state path: {path}")
            continue
        if not path.exists():
            continue
        if (
            record.get("status") == "preserved"
            or path.is_symlink()
            or not path.is_file()
            or not expected
            or sha256_file(path) != expected
        ):
            preserved[raw_path] = record
            reporter.emit("warning", f"Preserved modified or non-regular managed path: {path}")
            continue
        path.unlink()
        reporter.emit("ok", f"Removed managed file: {path}")

    if codex and state.get("marketplace_added"):
        try:
            remaining = [
                item
                for item in installed_plugins(codex, codex_home)
                if item.get("marketplaceName") == MARKETPLACE_NAME
            ]
            if remaining:
                marketplace_pending = True
                reporter.emit("warning", f"Marketplace retained because {len(remaining)} plugin(s) still use it.")
            elif MARKETPLACE_NAME in marketplace_map(codex, codex_home):
                command_json(
                    [codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"],
                    codex_home,
                )
                reporter.emit("ok", f"Removed marketplace {MARKETPLACE_NAME}.")
        except InstallerError as exc:
            marketplace_pending = True
            reporter.emit("warning", f"Could not remove marketplace: {exc}")

    path = state_path(codex_home)
    if state and (preserved or plugin_pending or marketplace_pending):
        residual = dict(state)
        residual["managed_files"] = preserved
        residual["plugin_removed"] = not plugin_pending
        residual["marketplace_pending"] = marketplace_pending
        write_state(codex_home, residual)
        reporter.emit("warning", f"Residual state retained at {path} for pending cleanup.")
    elif path.exists():
        path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
    reporter.emit("ok", "Uninstall complete.")
    return {"status": "ok", "action": "uninstall", "preserved": sorted(preserved)}


def doctor_action(args: argparse.Namespace, reporter: Reporter) -> dict[str, Any]:
    codex_home = Path(args.codex_home).expanduser().resolve()
    repository = args.repository or os.environ.get("SOL_LUNA_REPOSITORY")
    if repository in {REPOSITORY_PLACEHOLDER, ""}:
        repository = None
    repo_root = discover_repo_root(Path(__file__), args.repo_root) if args.local_marketplace else None
    checks = run_doctor(
        codex_home,
        cwd=Path.cwd(),
        smoke=args.smoke_models,
        repository=repository,
        marketplace_source=str(repo_root) if repo_root else repository,
    )
    for check in checks:
        reporter.emit(check.status, f"{check.name}: {check.detail}")
    status = "error" if any(check.status == "error" for check in checks) else "ok"
    return {"status": status, "action": "doctor", "checks": [asdict(check) for check in checks]}


def default_codex_home() -> str:
    return os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "upgrade", "uninstall", "doctor"))
    parser.add_argument("--codex-home", default=default_codex_home(), help="Codex state directory")
    parser.add_argument("--repo-root", help="Local source repository root for templates")
    parser.add_argument("--repository", help="GitHub repository as owner/name")
    parser.add_argument("--ref", help=f"Git ref (default: {DEFAULT_REF})")
    parser.add_argument(
        "--local-marketplace",
        action="store_true",
        help="Install the marketplace directly from --repo-root for local development",
    )
    parser.add_argument(
        "--with-cli-profile",
        action="store_true",
        help="Install the optional sol-luna CLI profile",
    )
    parser.add_argument(
        "--smoke-models",
        action="store_true",
        help="For doctor only: run one real, billable subagent smoke test",
    )
    parser.add_argument("--json", action="store_true", help="Emit one JSON result")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    reporter = Reporter(args.json)
    try:
        if args.action == "install":
            payload = install_or_upgrade(args, reporter, False)
        elif args.action == "upgrade":
            payload = install_or_upgrade(args, reporter, True)
        elif args.action == "uninstall":
            payload = uninstall(args, reporter)
        else:
            payload = doctor_action(args, reporter)
        reporter.finish(payload)
        return 1 if payload.get("status") == "error" else 0
    except (InstallerError, subprocess.TimeoutExpired) as exc:
        reporter.emit("error", str(exc))
        reporter.finish({"status": "error", "action": args.action})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
