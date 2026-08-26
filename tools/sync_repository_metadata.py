#!/usr/bin/env python3
"""Synchronize GitHub-owner metadata from an owner/repository identity."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CANONICAL_URL_PATTERN = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/codex-sol-luna-workflow"
)


def repository_from_remote() -> Optional[str]:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    match = re.match(
        r"^(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?$",
        result.stdout.strip(),
    )
    return match.group(1) if match else None


def resolve_repository(explicit: Optional[str]) -> str:
    repository = explicit or os.environ.get("GITHUB_REPOSITORY") or repository_from_remote()
    if not repository or not REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("Provide --repository owner/name or configure a GitHub origin remote.")
    return repository


def expected_files(repository: str) -> dict[Path, str]:
    owner, name = repository.split("/", 1)
    if name != "codex-sol-luna-workflow":
        raise ValueError("Repository name must be codex-sol-luna-workflow.")
    canonical_url = f"https://github.com/{repository}"
    manifest_path = ROOT / "plugins/sol-luna/.codex-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["author"] = {"name": owner, "url": f"https://github.com/{owner}"}
    manifest["homepage"] = canonical_url
    manifest["repository"] = canonical_url
    manifest["interface"]["developerName"] = owner
    manifest["interface"]["websiteURL"] = canonical_url
    expected = {
        manifest_path: json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        ROOT / ".github/CODEOWNERS": f"* @{owner}\n",
    }
    for relative in ("README.md", "README.en.md"):
        path = ROOT / relative
        expected[path] = CANONICAL_URL_PATTERN.sub(canonical_url, path.read_text(encoding="utf-8"))
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", help="GitHub repository as owner/name")
    parser.add_argument("--check", action="store_true", help="Fail instead of updating stale files")
    args = parser.parse_args()
    try:
        repository = resolve_repository(args.repository)
        expected = expected_files(repository)
    except ValueError as exc:
        parser.error(str(exc))
    manifest_path = ROOT / "plugins/sol-luna/.codex-plugin/plugin.json"
    stale = []
    for path, content in expected.items():
        current = path.read_text(encoding="utf-8")
        matches = (
            json.loads(current) == json.loads(content)
            if path == manifest_path
            else current == content
        )
        if not matches:
            stale.append(path)
    if args.check:
        if stale:
            for path in stale:
                print(f"STALE: {path.relative_to(ROOT)}")
            return 1
        print(f"Repository metadata matches {repository}.")
        return 0
    for path in stale:
        path.write_text(expected[path], encoding="utf-8")
        print(f"Updated {path.relative_to(ROOT)}")
    if not stale:
        print(f"Repository metadata already matches {repository}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
