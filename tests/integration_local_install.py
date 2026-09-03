#!/usr/bin/env python3
"""Exercise the real Codex plugin CLI in an isolated CODEX_HOME."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer/sol_luna_installer.py"
SHELL_INSTALLER = ROOT / "installer/install.sh"
POWERSHELL_INSTALLER = ROOT / "installer/install.ps1"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{result.stdout}\n{result.stderr}")
    return result


def installer_command(entrypoint: str, action: str, options: list[str]) -> list[str]:
    if entrypoint == "shell":
        prefix = [str(SHELL_INSTALLER)]
    elif entrypoint == "powershell":
        executable = shutil.which("pwsh")
        if not executable:
            raise RuntimeError("pwsh is required for the PowerShell integration")
        prefix = [executable, "-NoProfile", "-File", str(POWERSHELL_INSTALLER)]
    else:
        prefix = [sys.executable, str(INSTALLER)]
    return [*prefix, action, *options]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entrypoint", choices=("core", "shell", "powershell"), default="core"
    )
    parser.add_argument(
        "--codex-bin",
        help="Explicit Codex executable to test instead of resolving codex from PATH",
    )
    args = parser.parse_args()
    codex_bin = str(Path(args.codex_bin).expanduser().resolve()) if args.codex_bin else None
    if codex_bin and not Path(codex_bin).is_file():
        parser.error(f"Codex executable does not exist: {codex_bin}")
    if not codex_bin and not shutil.which("codex"):
        print("SKIP: codex CLI is not installed")
        return 0
    with tempfile.TemporaryDirectory(prefix="sol-luna-integration-") as directory:
        temp_root = Path(directory)
        codex_home = temp_root / "codex-home"
        codex_home.mkdir()
        old_repo = temp_root / "old-repository"
        new_repo = temp_root / "new-repository"
        shutil.copytree(
            ROOT,
            old_repo,
            ignore=shutil.ignore_patterns(
                ".git", "dist", "benchmark-results", "__pycache__", ".pytest_cache"
            ),
        )
        config = codex_home / "config.toml"
        original = 'model = "gpt-5.6-sol"\ncustom_marker = "keep-me"\n'
        config.write_text(original, encoding="utf-8")
        options = [
            "--codex-home",
            str(codex_home),
            "--repo-root",
            str(old_repo),
            "--repository",
            "onlyyuli/codex-sol-luna-skill",
            "--local-marketplace",
            "--json",
        ]
        if codex_bin:
            options.extend(["--codex-bin", codex_bin])
        install = run(
            installer_command(args.entrypoint, "install", [*options, "--with-cli-profile"])
        )
        install_payload = json.loads(install.stdout)
        if install_payload["status"] != "ok":
            raise RuntimeError("installer did not report success")
        repeated_install = run(
            installer_command(args.entrypoint, "install", [*options, "--with-cli-profile"])
        )
        if json.loads(repeated_install.stdout)["status"] != "ok":
            raise RuntimeError("repeated installation was not idempotent")
        old_repo.rename(new_repo)
        options[options.index(str(old_repo))] = str(new_repo)
        upgraded = run(
            installer_command(args.entrypoint, "upgrade", [*options, "--with-cli-profile"])
        )
        if json.loads(upgraded.stdout)["status"] != "ok":
            raise RuntimeError("same-source upgrade was not idempotent")
        installed_config = config.read_text(encoding="utf-8")
        if 'model = "gpt-5.6-sol"' not in installed_config or 'custom_marker = "keep-me"' not in installed_config:
            raise RuntimeError("Codex changed pre-existing main-model configuration")
        run(installer_command(args.entrypoint, "doctor", options))

        settings = codex_home / "sol-luna/settings.toml"
        settings.write_text(settings.read_text(encoding="utf-8") + "# user change\n", encoding="utf-8")
        uninstall = run(installer_command(args.entrypoint, "uninstall", options))
        uninstall_payload = json.loads(uninstall.stdout)
        if str(settings.resolve()) not in uninstall_payload["preserved"]:
            raise RuntimeError(
                "uninstall did not preserve user-modified settings: "
                f"{uninstall_payload!r}"
            )
        if not settings.exists():
            raise RuntimeError("modified settings were removed")
        if (codex_home / "agents/sol-luna-reader.toml").exists():
            raise RuntimeError("unchanged reader agent was not removed")
        final_config = config.read_text(encoding="utf-8")
        if final_config != original:
            raise RuntimeError("full install/uninstall did not byte-restore pre-existing config")
        repeated_uninstall = run(installer_command(args.entrypoint, "uninstall", options))
        if json.loads(repeated_uninstall.stdout)["status"] != "ok":
            raise RuntimeError("repeated uninstall was not idempotent")
    print(f"Real Codex isolated {args.entrypoint} install integration passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
