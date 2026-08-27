# Installation

## Requirements

- Codex CLI with `codex plugin` and subagent support.
- Python 3.9 or later.
- `curl` on macOS/Linux or PowerShell on Windows for one-line installation.
- Access to `gpt-5.6-luna` for real Luna execution.

Release-gate model smoke tests should use the current stable standalone Codex CLI. The installer
accepts `--codex-bin /absolute/path/to/codex`, or the equivalent `SOL_LUNA_CODEX_BIN` environment
variable, when a desktop-bundled pre-release appears first on `PATH`.

## Managed installation after v0.1.0 is released

The release installer adds the pinned GitHub repository as `codex-sol-luna`, installs `sol-luna`, installs namespaced reader/worker Agent files, creates routing settings, and records checksums for safe upgrades and removal.

macOS/Linux:

```sh
curl -fsSL https://github.com/onlyyuli/codex-sol-luna-skill/releases/download/v0.1.0/install.sh | sh -s -- install
```

Windows:

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing "https://github.com/onlyyuli/codex-sol-luna-skill/releases/download/v0.1.0/install.ps1").Content)) install
```

For security-sensitive environments, download `install.sh` or `install.ps1` and `SHA256SUMS`, verify the checksum, inspect the script, and then execute it locally.

## Optional CLI profile

```sh
./installer/install.sh install --with-cli-profile
codex --profile sol-luna
```

The profile selects Sol High for that CLI launch and sets Luna Max subagent defaults. Desktop model selection remains independent.

## Local development installation

From a clone:

```sh
python3 installer/sol_luna_installer.py install \
  --repo-root . \
  --repository onlyyuli/codex-sol-luna-skill \
  --local-marketplace
```

After installation, start a new Codex task and select `$sol-luna` from the frontend Skill picker.
The Skill does not activate from a plain-text mention or natural-language request alone.

Use a disposable home while developing:

```sh
CODEX_HOME=/tmp/sol-luna-dev python3 installer/sol_luna_installer.py install \
  --repo-root . \
  --repository onlyyuli/codex-sol-luna-skill \
  --local-marketplace
```

## Configuration effects

`codex plugin marketplace add` and `codex plugin add` necessarily add their own `[marketplaces.codex-sol-luna]` and `[plugins."sol-luna@codex-sol-luna"]` entries to Codex `config.toml`. The installer does not edit existing main-model, agents, permissions, provider, or unrelated settings. Removing the plugin and installer-owned Marketplace removes those namespaced entries through Codex CLI.

Managed files are recorded in `${CODEX_HOME}/sol-luna/install-state.json`. Pre-existing files are recorded as preserved even when their bytes match a template. A preserved file, or a managed file whose checksum changes, is never overwritten or removed automatically.

## Upgrade and uninstall

```sh
./installer/install.sh upgrade
./installer/install.sh uninstall
```

Release installers stay pinned to their own tag. When that tag changes, the installer
replaces only a Marketplace it previously created, refuses the operation if unrelated
plugins depend on it, and attempts to restore the previous tag if replacement fails.

The Marketplace is removed only if the installer originally added it and no installed plugin still uses it. Start a new Codex task after install or upgrade.

Model-smoke bundles under `${CODEX_HOME}/sol-luna/evidence/` are user audit data and are not listed as managed files. Upgrade and uninstall leave them in place for manual review or removal.
