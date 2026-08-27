# Troubleshooting

## Run doctor

```sh
./installer/install.sh doctor
```

It checks CLI capabilities, Marketplace and Plugin state, Agent schemas, settings, managed-file checksums, a global Luna main-model pin, disabled subagents, and a current-project model override. It does not call a model.

Use `doctor --smoke-models` only when one real, potentially billable test is acceptable. A successful textual response is not enough. The doctor requires exactly one newly created non-empty child thread ID, a marker linked to that child, child completion, Luna model metadata, and Max-effort metadata; missing evidence makes the command fail.

Every attempt writes `${CODEX_HOME}/sol-luna/evidence/smoke-*/events.jsonl`, `manifest.json`, and `SHA256SUMS`, including failures and timeouts. The human-readable output prints the bundle path, while `--json` exposes `checks[].evidence_path`. See [Luna Max smoke evidence](evidence.md) for the verification levels, integrity check, privacy warning, and retention behavior.

The smoke test uses the login associated with the selected `CODEX_HOME`. A disposable home normally has no login, so run the non-billable installation tests there and run the model smoke from an installed, authenticated home. If it times out, check `codex doctor --json` for provider and WebSocket reachability before changing the workflow configuration.

The smoke command disables unrelated plugins and keeps the parent/child sessions inspectable. For
that process only, it selects a temporary `sol_luna_smoke_http` provider that uses the normal Codex
ChatGPT endpoint and login with WebSockets disabled. It never overrides the reserved
`model_providers.openai` entry and does not modify the user's `config.toml`. The run may add
inspectable parent/child entries to local Codex history.

If `doctor` reports a pre-release executable (for example, a CLI bundled inside a desktop app),
install the current stable CLI and select it explicitly:

```sh
npm install -g @openai/codex@latest
./installer/install.sh doctor --codex-bin "$(command -v codex)" --smoke-models
```

You can also set `SOL_LUNA_CODEX_BIN` to an absolute executable path. Explicit selection prevents
an older bundled CLI earlier on `PATH` from silently handling the release-gate smoke. Always use
the current version shown in the official Codex changelog rather than copying the example version
forever.

Codex multi-agent tool surfaces are capability-dependent. Some releases may hide per-child
`model`/`reasoning_effort` fields or a custom-agent selector even when `multi_agent` itself is
enabled. With `strict_model = true`, this workflow treats that runtime as incompatible rather than
spawning an inherited child and calling it Luna. The optional CLI Profile supplies requested
defaults, but activity metadata is still required before reporting effective Luna Max use.

## Marketplace name collision

If `codex-sol-luna` already points to another source, the installer stops. Inspect `codex plugin marketplace list --json`; remove or rename the conflicting source deliberately rather than forcing an overwrite.

## Luna is unavailable

Account and workspace model access can differ. Adaptive `$sol-luna` work falls back to the main thread with disclosure. A request that explicitly requires Luna stops instead of substituting another model.

## `$sol-luna` was not attached

Start a new Codex task, open the frontend Skill picker, and select `$sol-luna` so it appears as an
attached Skill for that turn. A raw `$sol-luna` string sent through the composer or task API is not
equivalent to selecting the Skill. This is intentional: `allow_implicit_invocation` is disabled, so
natural-language requests for Luna or parallel agents do not discover or load the workflow.

## A project still starts with Luna

Check the current project for `.codex/config.toml` and the user `config.toml` for `model = "gpt-5.6-luna"`. This plugin never changes those values. Use the Desktop model picker or remove the separate pin yourself if it is no longer wanted.

## Uninstall preserved a file

The file changed after installation or is a symlink/non-regular path. The residual state lists preserved paths. Review and remove them manually if appropriate, then run uninstall again.
