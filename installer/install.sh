#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
  set -- install
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
local_installer="$script_dir/sol_luna_installer.py"

if command -v python3 >/dev/null 2>&1; then
  python_cmd=python3
elif command -v python >/dev/null 2>&1; then
  python_cmd=python
else
  echo "Python 3 is required." >&2
  exit 1
fi

if [ -f "$local_installer" ]; then
  exec "$python_cmd" "$local_installer" "$@"
fi

repository=${SOL_LUNA_REPOSITORY:-__GITHUB_REPOSITORY__}
release_ref=${SOL_LUNA_REF:-__SOL_LUNA_REF__}
repository_placeholder="__GITHUB_"'REPOSITORY__'
ref_placeholder="__SOL_LUNA_"'REF__'
if [ "$repository" = "$repository_placeholder" ]; then
  echo "This source wrapper is not a release asset. Set SOL_LUNA_REPOSITORY=owner/repo." >&2
  exit 1
fi
if [ "$release_ref" = "$ref_placeholder" ]; then
  release_ref="v0.1.0"
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for release installation." >&2
  exit 1
fi

temp_dir=$(mktemp -d "${TMPDIR:-/tmp}/sol-luna-installer.XXXXXX")
trap 'rm -rf "$temp_dir"' EXIT HUP INT TERM
installer_url="https://raw.githubusercontent.com/$repository/$release_ref/installer/sol_luna_installer.py"
curl -fsSL "$installer_url" -o "$temp_dir/sol_luna_installer.py"
SOL_LUNA_REPOSITORY="$repository" SOL_LUNA_REF="$release_ref" \
  "$python_cmd" "$temp_dir/sol_luna_installer.py" "$@"
