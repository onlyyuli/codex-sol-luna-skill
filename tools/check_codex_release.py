#!/usr/bin/env python3
"""Fail when the selected Codex CLI is missing or is a pre-release build."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from installer.sol_luna_installer import codex_release_channel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", help="Codex executable to inspect; defaults to PATH")
    args = parser.parse_args()
    candidate = args.codex_bin or shutil.which("codex")
    if not candidate:
        parser.error("Codex CLI is not installed or is not on PATH")
    executable = str(Path(candidate).expanduser().resolve())
    result = subprocess.run(
        [executable, "--version"], text=True, capture_output=True, check=False
    )
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        print(f"Codex version check failed ({result.returncode}): {output}")
        return 1
    status, detail = codex_release_channel(output)
    print(f"{executable}: {output}")
    print(detail)
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
