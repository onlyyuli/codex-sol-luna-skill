#!/usr/bin/env python3
"""Build release-ready installer assets with repository metadata embedded."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


PLACEHOLDERS = {
    "__GITHUB_REPOSITORY__": "repository",
    "__SOL_LUNA_REF__": "ref",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--output", default="dist")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("--repository must be owner/name")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", args.ref):
        parser.error("--ref must be a semantic release tag")

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "plugins/sol-luna/.codex-plugin/plugin.json").read_text(encoding="utf-8")
    )
    expected_tag_prefix = f"v{manifest.get('version', '')}"
    if args.ref != expected_tag_prefix and not args.ref.startswith(expected_tag_prefix + "-"):
        parser.error(
            f"--ref {args.ref!r} does not match plugin version {manifest.get('version')!r}"
        )
    output = (root / args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = (
        root / "installer/install.sh",
        root / "installer/install.ps1",
        root / "installer/sol_luna_installer.py",
    )
    values = {"repository": args.repository, "ref": args.ref}
    built = []
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for placeholder, key in PLACEHOLDERS.items():
            text = text.replace(placeholder, values[key])
        destination = output / source.name
        destination.write_text(text, encoding="utf-8")
        shutil.copymode(source, destination)
        built.append(destination)
    checksum_file = output / "SHA256SUMS"
    checksum_file.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(built)),
        encoding="utf-8",
    )
    print(f"Built {len(built)} installer assets in {output}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
