#!/usr/bin/env python3
"""Managed installer and doctor for the codex-sol-luna workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
SMOKE_MAIN_MODEL = "gpt-5.6-sol"
SMOKE_CHILD_MODEL = "gpt-5.6-luna"
SMOKE_CHILD_REASONING_EFFORT = "max"
SMOKE_HTTP_PROVIDER = "sol_luna_smoke_http"
SMOKE_EVIDENCE_SCHEMA_VERSION = 1

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
    evidence_path: Optional[str] = None


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


def check_payload(check: Check) -> dict[str, Any]:
    payload = asdict(check)
    if payload.get("evidence_path") is None:
        payload.pop("evidence_path", None)
    return payload


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


def codex_path(explicit: Optional[str] = None) -> str:
    requested = explicit or "codex"
    expanded = str(Path(requested).expanduser())
    executable = shutil.which(expanded)
    if not executable:
        if explicit:
            raise InstallerError(f"Codex CLI was not found or is not executable: {explicit}")
        raise InstallerError("Codex CLI was not found on PATH.")
    return str(Path(executable).resolve())


def codex_release_channel(version_text: str) -> tuple[str, str]:
    match = re.search(r"\b(\d+\.\d+\.\d+)(?:-([0-9A-Za-z.-]+))?\b", version_text)
    if not match:
        return "warning", "could not determine the CLI release channel"
    prerelease = match.group(2)
    if prerelease:
        return "warning", f"pre-release CLI detected ({match.group(1)}-{prerelease})"
    return "ok", f"stable CLI detected ({match.group(1)})"


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


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def make_smoke_marker() -> str:
    return "LUNA_SMOKE_OK"


def normalize_process_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def parse_jsonl_events(stdout: str) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    invalid_lines = 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            invalid_lines += 1
    return events, invalid_lines


def smoke_rollout_snapshot(codex_home: Path) -> set[Path]:
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return set()
    paths: set[Path] = set()
    try:
        candidates = sessions.rglob("*.jsonl")
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            try:
                paths.add(path.resolve())
            except OSError:
                continue
    except OSError:
        return paths
    return paths


def rollout_session_metadata(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
        event = json.loads(first_line)
    except (OSError, json.JSONDecodeError):
        return {}
    if event.get("type") != "session_meta" or not isinstance(event.get("payload"), dict):
        return {}
    return event["payload"]


def smoke_parent_thread_id(stdout: str) -> Optional[str]:
    events, _ = parse_jsonl_events(stdout)
    for event in events:
        if event.get("type") != "thread.started":
            continue
        value = event.get("thread_id")
        if isinstance(value, str) and value:
            return value
    return None


def discover_smoke_rollouts(
    codex_home: Path,
    before: set[Path],
    parent_thread_id: Optional[str],
) -> tuple[Optional[Path], list[Path]]:
    if not parent_thread_id:
        return None, []
    new_paths = smoke_rollout_snapshot(codex_home) - before
    parent: Optional[Path] = None
    children: list[Path] = []
    for path in sorted(new_paths):
        metadata = rollout_session_metadata(path)
        thread_id = metadata.get("id") or metadata.get("session_id")
        if thread_id == parent_thread_id:
            parent = path
        elif metadata.get("parent_thread_id") == parent_thread_id:
            children.append(path)
    return parent, children


def read_smoke_rollout_artifacts(
    parent_path: Optional[Path], child_paths: list[Path]
) -> dict[str, bytes]:
    artifacts: dict[str, bytes] = {}
    candidates: list[tuple[str, Path]] = []
    if parent_path is not None:
        candidates.append(("parent-rollout.jsonl", parent_path))
    for index, path in enumerate(child_paths, start=1):
        metadata = rollout_session_metadata(path)
        child_id = metadata.get("id") or metadata.get("session_id")
        safe_id = re.sub(r"[^A-Za-z0-9-]", "-", str(child_id or index))
        candidates.append((f"child-rollout-{safe_id}.jsonl", path))
    for name, path in candidates:
        try:
            artifacts[name] = path.read_bytes()
        except OSError:
            continue
    return artifacts


def _rollout_texts(events: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if (
            event.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
        ):
            content = payload.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(item["text"])
    return texts


def assess_smoke_rollouts(
    parent_path: Optional[Path],
    child_paths: list[Path],
    marker: str,
) -> dict[str, Any]:
    empty = {
        "child_thread_ids": [],
        "child_count": 0,
        "collaboration_event_count": 0,
        "observed_models": [],
        "observed_reasoning_efforts": [],
        "marker_observed_anywhere": False,
        "marker_proven_for_child": False,
        "child_completion_proven": False,
        "child_states": [],
        "activity_errors": [],
        "parsed_event_count": 0,
        "invalid_jsonl_line_count": 0,
    }
    if parent_path is None or not parent_path.is_file():
        return empty
    try:
        parent_stdout = parent_path.read_text(encoding="utf-8")
    except OSError:
        return empty
    parent_events, invalid_lines = parse_jsonl_events(parent_stdout)
    started: set[str] = set()
    completed: set[str] = set()
    errors: list[str] = []
    collaboration_events = 0
    for event in parent_events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "item_completed" and isinstance(payload.get("item"), dict):
            item = payload["item"]
            if item.get("type") == "SubAgentActivity":
                child_id = item.get("agent_thread_id")
                kind = item.get("kind")
                if isinstance(child_id, str) and child_id:
                    collaboration_events += 1
                    if kind == "started":
                        started.add(child_id)
                    elif kind == "completed":
                        completed.add(child_id)
        if payload.get("type") == "error" and isinstance(payload.get("message"), str):
            errors.append(payload["message"])

    child_records: dict[str, dict[str, Any]] = {}
    event_count = len(parent_events)
    for path in child_paths:
        metadata = rollout_session_metadata(path)
        child_id = metadata.get("id") or metadata.get("session_id")
        if not isinstance(child_id, str) or not child_id:
            continue
        try:
            child_stdout = path.read_text(encoding="utf-8")
        except OSError:
            continue
        child_events, child_invalid = parse_jsonl_events(child_stdout)
        invalid_lines += child_invalid
        event_count += len(child_events)
        model_values: set[str] = set()
        effort_values: set[str] = set()
        task_complete = False
        for event in child_events:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if event.get("type") == "turn_context":
                model = payload.get("model")
                if isinstance(model, str):
                    model_values.add(model)
                collaboration = payload.get("collaboration_mode")
                if isinstance(collaboration, dict):
                    settings = collaboration.get("settings")
                    if isinstance(settings, dict):
                        effort = settings.get("reasoning_effort")
                        if isinstance(effort, str):
                            effort_values.add(effort)
            if event.get("type") == "event_msg" and payload.get("type") == "task_complete":
                task_complete = True
            if payload.get("type") == "error" and isinstance(payload.get("message"), str):
                errors.append(payload["message"])
        child_records[child_id] = {
            "models": model_values,
            "efforts": effort_values,
            "texts": _rollout_texts(child_events),
            "task_complete": task_complete,
        }

    linked_ids = set(child_records).intersection(started)
    models: set[str] = set()
    efforts: set[str] = set()
    marker_ids: set[str] = set()
    completed_ids: set[str] = set()
    for child_id in linked_ids:
        record = child_records[child_id]
        models.update(record["models"])
        efforts.update(record["efforts"])
        if any(marker in text for text in record["texts"]):
            marker_ids.add(child_id)
        if child_id in completed or record["task_complete"]:
            completed_ids.add(child_id)
    marker_proven = len(linked_ids) == 1 and marker_ids == linked_ids
    completion_proven = marker_proven and completed_ids == linked_ids
    return {
        "child_thread_ids": sorted(linked_ids),
        "child_count": len(linked_ids),
        "collaboration_event_count": collaboration_events,
        "observed_models": sorted(models),
        "observed_reasoning_efforts": sorted(efforts),
        "marker_observed_anywhere": bool(marker_ids),
        "marker_proven_for_child": marker_proven,
        "child_completion_proven": completion_proven,
        "child_states": ["completed"] if completion_proven else [],
        "activity_errors": errors[-5:],
        "parsed_event_count": event_count,
        "invalid_jsonl_line_count": invalid_lines,
    }


def merge_smoke_assessments(
    activity: dict[str, Any], rollout: dict[str, Any]
) -> dict[str, Any]:
    child_ids = set(activity["child_thread_ids"]) | set(rollout["child_thread_ids"])
    models = set(activity["observed_models"]) | set(rollout["observed_models"])
    efforts = set(activity["observed_reasoning_efforts"]) | set(
        rollout["observed_reasoning_efforts"]
    )
    marker_proven = bool(
        activity["marker_proven_for_child"] or rollout["marker_proven_for_child"]
    )
    completion_proven = marker_proven and bool(
        activity["child_completion_proven"] or rollout["child_completion_proven"]
    )
    luna_model_proven = len(child_ids) == 1 and models == {SMOKE_CHILD_MODEL}
    max_effort_proven = len(child_ids) == 1 and efforts == {
        SMOKE_CHILD_REASONING_EFFORT
    }
    verification_level = "requested_only"
    if len(child_ids) == 1 and marker_proven and completion_proven and luna_model_proven:
        verification_level = "luna_verified"
        if max_effort_proven:
            verification_level = "luna_max_verified"
    sources = []
    if activity["child_thread_ids"]:
        sources.append("cli_jsonl")
    if rollout["child_thread_ids"]:
        sources.append("persisted_rollouts")
    return {
        "verification_level": verification_level,
        "verification_sources": sources,
        "passed": verification_level == "luna_max_verified",
        "child_thread_ids": sorted(child_ids),
        "child_count": len(child_ids),
        "collaboration_event_count": (
            activity["collaboration_event_count"]
            + rollout["collaboration_event_count"]
        ),
        "observed_models": sorted(models),
        "observed_reasoning_efforts": sorted(efforts),
        "luna_model_proven": luna_model_proven,
        "max_effort_proven": max_effort_proven,
        "marker_observed_anywhere": bool(
            activity["marker_observed_anywhere"]
            or rollout["marker_observed_anywhere"]
        ),
        "marker_proven_for_child": marker_proven,
        "child_completion_proven": completion_proven,
        "child_states": sorted(
            set(activity["child_states"]) | set(rollout["child_states"])
        ),
        "activity_errors": (
            list(activity["activity_errors"]) + list(rollout["activity_errors"])
        )[-5:],
        "parsed_event_count": (
            activity["parsed_event_count"] + rollout["parsed_event_count"]
        ),
        "invalid_jsonl_line_count": (
            activity["invalid_jsonl_line_count"]
            + rollout["invalid_jsonl_line_count"]
        ),
    }


def nested_text_values(value: Any, accepted_keys: set[str], inside_result: bool = False) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            values.extend(
                nested_text_values(
                    child,
                    accepted_keys,
                    inside_result or key.lower() in accepted_keys,
                )
            )
    elif isinstance(value, list):
        for child in value:
            values.extend(nested_text_values(child, accepted_keys, inside_result))
    elif inside_result and isinstance(value, str):
        values.append(value)
    return values


def child_state_values(item: dict[str, Any], child_thread_ids: set[str]) -> set[str]:
    values: set[str] = set()
    states = item.get("agents_states")
    if isinstance(states, dict):
        for child_id in child_thread_ids:
            state = states.get(child_id)
            if isinstance(state, str):
                values.add(state.lower())
            elif isinstance(state, dict):
                values.update(
                    value.lower()
                    for value in metadata_values(state, {"status", "state", "phase"})
                )
    return values


def assess_smoke_activity(stdout: str, marker: str) -> dict[str, Any]:
    events, invalid_lines = parse_jsonl_events(stdout)
    child_thread_ids: set[str] = set()
    collaboration_events = 0
    activity_errors: list[str] = []
    for event in events:
        item = event.get("item")
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
        if (
            item.get("type") == "error"
            and isinstance(item.get("message"), str)
            and item["message"].strip()
        ):
            activity_errors.append(item["message"].strip())

    linked_items: list[dict[str, Any]] = []
    linked_events: list[dict[str, Any]] = []
    explicit_child_id_keys = {
        "agent_id",
        "child_thread_id",
        "receiver_thread_id",
        "sender_thread_id",
        "thread_id",
    }
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        receiver_ids = item.get("receiver_thread_ids")
        receiver_set = {
            value for value in receiver_ids if isinstance(value, str) and value
        } if isinstance(receiver_ids, list) else set()
        explicit_ids = metadata_values(event, explicit_child_id_keys)
        if child_thread_ids.intersection(receiver_set | explicit_ids):
            linked_events.append(event)
            linked_items.append(item)

    models = metadata_values(
        linked_items, {"model", "model_name", "model_slug", "selected_model"}
    )
    efforts = metadata_values(
        linked_items, {"model_reasoning_effort", "reasoning_effort"}
    )
    marker_anywhere = any(marker in text for text in nested_text_values(events, {"text"}))
    linked_result_texts = nested_text_values(
        linked_items,
        {"final_output", "last_message", "output", "response", "result"},
    )
    for event in linked_events:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        explicit_ids = metadata_values(event, explicit_child_id_keys)
        if child_thread_ids.intersection(explicit_ids) and isinstance(item.get("text"), str):
            linked_result_texts.append(item["text"])
    marker_proven_for_child = any(marker in text for text in linked_result_texts)

    completed_states: set[str] = set()
    for item in linked_items:
        completed_states.update(child_state_values(item, child_thread_ids))
    linked_item_completed = any(event.get("type") == "item.completed" for event in linked_events)
    completion_proven = marker_proven_for_child and (
        linked_item_completed or bool(completed_states.intersection({"complete", "completed", "done"}))
    )

    luna_model_proven = models == {SMOKE_CHILD_MODEL}
    max_effort_proven = efforts == {SMOKE_CHILD_REASONING_EFFORT}
    verification_level = "requested_only"
    if (
        len(child_thread_ids) == 1
        and marker_proven_for_child
        and completion_proven
        and luna_model_proven
    ):
        verification_level = "luna_verified"
        if max_effort_proven:
            verification_level = "luna_max_verified"

    return {
        "verification_level": verification_level,
        "passed": verification_level == "luna_max_verified",
        "child_thread_ids": sorted(child_thread_ids),
        "child_count": len(child_thread_ids),
        "collaboration_event_count": collaboration_events,
        "observed_models": sorted(models),
        "observed_reasoning_efforts": sorted(efforts),
        "luna_model_proven": luna_model_proven,
        "max_effort_proven": max_effort_proven,
        "marker_observed_anywhere": marker_anywhere,
        "marker_proven_for_child": marker_proven_for_child,
        "child_completion_proven": completion_proven,
        "child_states": sorted(completed_states),
        "activity_errors": activity_errors[-5:],
        "parsed_event_count": len(events),
        "invalid_jsonl_line_count": invalid_lines,
    }


def ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise InstallerError(f"Refusing evidence directory symlink: {path}")
    if path.exists() and not path.is_dir():
        raise InstallerError(f"Evidence path is not a directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def write_smoke_evidence_bundle(
    codex_home: Path,
    *,
    stdout: str,
    marker: str,
    assessment: dict[str, Any],
    codex_version: str,
    started_at: str,
    completed_at: str,
    execution_status: str,
    return_code: Optional[int],
    timed_out: bool,
    error_summary: str,
    rollout_artifacts: Optional[dict[str, bytes]] = None,
) -> Path:
    evidence_root = codex_home / "sol-luna" / "evidence"
    require_managed_path(evidence_root, codex_home)
    ensure_private_directory(evidence_root)
    run_id = (
        "smoke-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + "-"
        + secrets.token_hex(4)
    )
    bundle = evidence_root / run_id
    require_managed_path(bundle, codex_home)
    bundle.mkdir(mode=0o700)

    rollout_artifacts = rollout_artifacts or {}
    events_path = bundle / "events.jsonl"
    events_data = stdout.encode("utf-8")
    atomic_write(events_path, events_data)
    artifact_payloads = {"events.jsonl": events_data, **rollout_artifacts}
    for name, data in rollout_artifacts.items():
        if Path(name).name != name or not name.endswith(".jsonl"):
            raise InstallerError(f"Invalid smoke rollout artifact name: {name}")
        atomic_write(bundle / name, data)
    manifest = {
        "schema_version": SMOKE_EVIDENCE_SCHEMA_VERSION,
        "kind": "codex-sol-luna-model-smoke",
        "workflow_version": VERSION,
        "smoke_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "codex_version": codex_version,
        "request": {
            "main_model": SMOKE_MAIN_MODEL,
            "child_model": SMOKE_CHILD_MODEL,
            "child_reasoning_effort": SMOKE_CHILD_REASONING_EFFORT,
            "child_count": 1,
            "sandbox": "read-only",
            "marker": marker,
        },
        "execution": {
            "status": execution_status,
            "return_code": return_code,
            "timed_out": timed_out,
            "error_summary": " ".join(error_summary.split())[:500],
        },
        "verification": assessment,
        "artifacts": {
            name: {"bytes": len(data), "sha256": sha256_bytes(data)}
            for name, data in sorted(artifact_payloads.items())
        },
        "sharing_warning": (
            "Review events.jsonl before sharing; runtime output can contain local paths or "
            "account-specific diagnostic text."
        ),
    }
    manifest_path = bundle / "manifest.json"
    manifest_data = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write(manifest_path, manifest_data)
    checksum_lines = [
        f"{sha256_bytes(data)}  {name}\n"
        for name, data in sorted(artifact_payloads.items())
    ]
    checksum_lines.append(f"{sha256_bytes(manifest_data)}  manifest.json\n")
    checksums = "".join(checksum_lines).encode("utf-8")
    atomic_write(bundle / "SHA256SUMS", checksums)
    for path in (
        *(bundle / name for name in artifact_payloads),
        manifest_path,
        bundle / "SHA256SUMS",
    ):
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return bundle


def smoke_check_with_evidence(
    codex_home: Path,
    *,
    status: str,
    detail: str,
    stdout: str,
    marker: str,
    assessment: dict[str, Any],
    codex_version: str,
    started_at: str,
    execution_status: str,
    return_code: Optional[int],
    timed_out: bool,
    error_summary: str = "",
    rollout_artifacts: Optional[dict[str, bytes]] = None,
) -> Check:
    try:
        bundle = write_smoke_evidence_bundle(
            codex_home,
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            completed_at=utc_now_iso(),
            execution_status=execution_status,
            return_code=return_code,
            timed_out=timed_out,
            error_summary=error_summary,
            rollout_artifacts=rollout_artifacts,
        )
    except (InstallerError, OSError) as exc:
        return Check(
            "model smoke",
            "error",
            f"{detail} Evidence bundle could not be saved: {exc}",
        )
    return Check(
        "model smoke",
        status,
        f"{detail} Evidence: {bundle}",
        evidence_path=str(bundle),
    )


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
    started_at = utc_now_iso()
    marker = make_smoke_marker()
    task_name = f"luna_smoke_{secrets.token_hex(4)}"
    try:
        version_result = run_command(
            [codex, "--version"],
            codex_home=codex_home,
            cwd=cwd,
            timeout=15,
            check=False,
        )
        codex_version = (
            version_result.stdout.strip()
            or version_result.stderr.strip()
            or "unknown"
        ).splitlines()[0]
    except subprocess.TimeoutExpired:
        codex_version = "unknown (version check timed out)"
    try:
        login = run_command(
            [codex, "login", "status"],
            codex_home=codex_home,
            cwd=cwd,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = ""
        detail = "Codex login status timed out after 15 seconds."
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail=detail,
            stdout=stdout,
            marker=marker,
            assessment=assess_smoke_activity(stdout, marker),
            codex_version=codex_version,
            started_at=started_at,
            execution_status="preflight_timed_out",
            return_code=None,
            timed_out=True,
            error_summary=normalize_process_output(exc.stderr),
        )
    if login.returncode != 0:
        detail = login.stderr.strip() or login.stdout.strip() or "not logged in"
        stdout = ""
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail=f"Codex is not logged in for {codex_home}: {detail}",
            stdout=stdout,
            marker=marker,
            assessment=assess_smoke_activity(stdout, marker),
            codex_version=codex_version,
            started_at=started_at,
            execution_status="preflight_failed",
            return_code=None,
            timed_out=False,
            error_summary=detail,
        )
    prompt = (
        "Your first action must be one direct call to functions.collaboration.spawn_agent. "
        f"Use task_name {task_name}, fork_turns none, "
        f"model {SMOKE_CHILD_MODEL}, reasoning_effort {SMOKE_CHILD_REASONING_EFFORT}, and a "
        "message argument containing exactly this instruction: "
        f"Return exactly and only the full token {marker}, preserving every suffix character; "
        "do not read or write files, call tools, or delegate. "
        "Do not call wait_agent unless spawn_agent returns a non-empty child thread ID. If the "
        "tool is unavailable, the call fails, or no child ID is returned, return only "
        "SUBAGENT_SMOKE_FAILED. If the child starts, wait for that exact child and then return "
        "only SUBAGENT_SMOKE_COMPLETED. Never produce, echo, or quote the requested child marker "
        "in the parent thread."
    )
    command = [
        codex,
        "exec",
        "--enable",
        "multi_agent",
        "--disable",
        "plugins",
        "--strict-config",
        "--json",
        "--sandbox",
        "read-only",
        "--model",
        SMOKE_MAIN_MODEL,
        "--config",
        f'model_provider="{SMOKE_HTTP_PROVIDER}"',
        "--config",
        (
            "model_providers={sol_luna_smoke_http={"
            'name="Sol Luna smoke HTTP",'
            'base_url="https://chatgpt.com/backend-api/codex",'
            'wire_api="responses",requires_openai_auth=true,'
            "supports_websockets=false}}"
        ),
        "--config",
        "agents.enabled=true",
        "--config",
        f'agents.default_subagent_model="{SMOKE_CHILD_MODEL}"',
        "--config",
        f'agents.default_subagent_reasoning_effort="{SMOKE_CHILD_REASONING_EFFORT}"',
        prompt,
    ]
    rollout_before = smoke_rollout_snapshot(codex_home)
    try:
        result = run_command(command, codex_home=codex_home, cwd=cwd, timeout=300, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = normalize_process_output(exc.stdout)
        parent_rollout, child_rollouts = discover_smoke_rollouts(
            codex_home, rollout_before, smoke_parent_thread_id(stdout)
        )
        assessment = merge_smoke_assessments(
            assess_smoke_activity(stdout, marker),
            assess_smoke_rollouts(parent_rollout, child_rollouts, marker),
        )
        rollout_artifacts = read_smoke_rollout_artifacts(parent_rollout, child_rollouts)
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail="Codex model smoke timed out after 300 seconds.",
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="timed_out",
            return_code=None,
            timed_out=True,
            error_summary=normalize_process_output(exc.stderr),
            rollout_artifacts=rollout_artifacts,
        )
    stdout = result.stdout
    parent_rollout, child_rollouts = discover_smoke_rollouts(
        codex_home, rollout_before, smoke_parent_thread_id(stdout)
    )
    assessment = merge_smoke_assessments(
        assess_smoke_activity(stdout, marker),
        assess_smoke_rollouts(parent_rollout, child_rollouts, marker),
    )
    rollout_artifacts = read_smoke_rollout_artifacts(parent_rollout, child_rollouts)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown failure"
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail=f"Codex smoke run failed: {detail}",
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="failed",
            return_code=result.returncode,
            timed_out=False,
            error_summary=detail,
            rollout_artifacts=rollout_artifacts,
        )
    if assessment["child_count"] != 1:
        context = []
        if assessment["collaboration_event_count"]:
            context.append(
                f"collaboration events: {assessment['collaboration_event_count']}"
            )
        if assessment["activity_errors"]:
            context.append("activity error: " + assessment["activity_errors"][-1][:240])
        suffix = "; " + "; ".join(context) if context else ""
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail=(
                "Activity did not prove exactly one spawned subagent; "
                f"observed {assessment['child_count']} child thread IDs{suffix}."
            ),
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="completed",
            return_code=result.returncode,
            timed_out=False,
            rollout_artifacts=rollout_artifacts,
        )
    if not assessment["marker_proven_for_child"]:
        marker_context = (
            " The marker appeared only outside child-linked activity."
            if assessment["marker_observed_anywhere"]
            else ""
        )
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail=(
                "A child thread was observed, but its child-linked activity did not return the "
                f"smoke marker.{marker_context}"
            ),
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="completed",
            return_code=result.returncode,
            timed_out=False,
            rollout_artifacts=rollout_artifacts,
        )
    if not assessment["child_completion_proven"]:
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail="The marker was observed, but completion was not linked to the child thread.",
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="completed",
            return_code=result.returncode,
            timed_out=False,
            rollout_artifacts=rollout_artifacts,
        )
    if not assessment["luna_model_proven"]:
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail=(
                "One child thread completed, but JSONL activity did not prove its effective "
                "model; GPT-5.6 Luna Max was requested."
            ),
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="completed",
            return_code=result.returncode,
            timed_out=False,
            rollout_artifacts=rollout_artifacts,
        )
    if not assessment["max_effort_proven"]:
        return smoke_check_with_evidence(
            codex_home,
            status="error",
            detail="Activity proved GPT-5.6 Luna, but max effort was requested and not proven.",
            stdout=stdout,
            marker=marker,
            assessment=assessment,
            codex_version=codex_version,
            started_at=started_at,
            execution_status="completed",
            return_code=result.returncode,
            timed_out=False,
            rollout_artifacts=rollout_artifacts,
        )
    return smoke_check_with_evidence(
        codex_home,
        status="ok",
        detail="Activity proved GPT-5.6 Luna and max effort for one completed child thread.",
        stdout=stdout,
        marker=marker,
        assessment=assessment,
        codex_version=codex_version,
        started_at=started_at,
        execution_status="completed",
        return_code=result.returncode,
        timed_out=False,
        rollout_artifacts=rollout_artifacts,
    )


def run_doctor(
    codex_home: Path,
    *,
    cwd: Path,
    smoke: bool,
    repository: Optional[str],
    marketplace_source: Optional[str] = None,
    codex_executable: Optional[str] = None,
) -> list[Check]:
    checks: list[Check] = []
    codex = codex_executable or shutil.which("codex")
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
            f"{version.stdout.strip() or version.stderr.strip()} ({Path(codex).resolve()})",
        )
    )
    channel_status, channel_detail = codex_release_channel(
        version.stdout.strip() or version.stderr.strip()
    )
    checks.append(Check("Codex CLI release channel", channel_status, channel_detail))
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
    codex = codex_path(getattr(args, "codex_bin", None))
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
        codex_executable=codex,
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
    explicit_codex = getattr(args, "codex_bin", None)
    codex = codex_path(explicit_codex) if explicit_codex else shutil.which("codex")
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
    explicit_codex = getattr(args, "codex_bin", None)
    codex = codex_path(explicit_codex) if explicit_codex else None
    checks = run_doctor(
        codex_home,
        cwd=Path.cwd(),
        smoke=args.smoke_models,
        repository=repository,
        marketplace_source=str(repo_root) if repo_root else repository,
        codex_executable=codex,
    )
    for check in checks:
        reporter.emit(check.status, f"{check.name}: {check.detail}")
    status = "error" if any(check.status == "error" for check in checks) else "ok"
    return {"status": status, "action": "doctor", "checks": [check_payload(check) for check in checks]}


def default_codex_home() -> str:
    return os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "upgrade", "uninstall", "doctor"))
    parser.add_argument("--codex-home", default=default_codex_home(), help="Codex state directory")
    parser.add_argument(
        "--codex-bin",
        default=os.environ.get("SOL_LUNA_CODEX_BIN"),
        help=(
            "Codex CLI executable to use instead of the first codex on PATH "
            "(or set SOL_LUNA_CODEX_BIN)"
        ),
    )
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
        help=(
            "For doctor only: run one real, billable subagent smoke test and save an evidence "
            "bundle under CODEX_HOME/sol-luna/evidence"
        ),
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
