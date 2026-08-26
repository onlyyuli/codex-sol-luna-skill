# Troubleshooting

## Run doctor

```sh
./installer/install.sh doctor
```

It checks CLI capabilities, Marketplace and Plugin state, Agent schemas, settings, managed-file checksums, a global Luna main-model pin, disabled subagents, and a current-project model override. It does not call a model.

Use `doctor --smoke-models` only when one real, potentially billable test is acceptable. A successful textual response is not enough. The doctor requires exactly one non-empty child thread ID, the child marker, Luna model metadata, and Max-effort metadata; missing evidence makes the command fail.

The smoke test uses the login associated with the selected `CODEX_HOME`. A disposable home normally has no login, so run the non-billable installation tests there and run the model smoke from an installed, authenticated home. If it times out, check `codex doctor --json` for provider and WebSocket reachability before changing the workflow configuration.

Codex multi-agent tool surfaces are capability-dependent. Some releases may hide per-child
`model`/`reasoning_effort` fields or a custom-agent selector even when `multi_agent` itself is
enabled. With `strict_model = true`, this workflow treats that runtime as incompatible rather than
spawning an inherited child and calling it Luna. The optional CLI Profile supplies requested
defaults, but activity metadata is still required before reporting effective Luna Max use.

## Marketplace name collision

If `codex-sol-luna` already points to another source, the installer stops. Inspect `codex plugin marketplace list --json`; remove or rename the conflicting source deliberately rather than forcing an overwrite.

## Luna is unavailable

Account and workspace model access can differ. Adaptive `$sol-luna` work falls back to the main thread with disclosure. A request that explicitly requires Luna stops instead of substituting another model.

## A project still starts with Luna

Check the current project for `.codex/config.toml` and the user `config.toml` for `model = "gpt-5.6-luna"`. This plugin never changes those values. Use the Desktop model picker or remove the separate pin yourself if it is no longer wanted.

## Uninstall preserved a file

The file changed after installation or is a symlink/non-regular path. The residual state lists preserved paths. Review and remove them manually if appropriate, then run uninstall again.
