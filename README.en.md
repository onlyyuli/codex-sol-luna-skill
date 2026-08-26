# Codex Sol + Luna Workflow

[简体中文](README.md) · [Installation](docs/installation.md) · [Architecture](docs/architecture.md) · [Benchmark](docs/benchmark.md)

An explicitly invoked, globally installable Codex orchestration plugin. It preserves the model selected for the main thread and delegates only bounded, independently verifiable work to GPT-5.6 Luna Max subagents.

> This is a community project, not an official OpenAI preset. Model access, effective reasoning effort, concurrency, and routing depend on the Codex version and account. Only agent activity or tool metadata can prove which model ran.

> Strict mode also requires the current Codex runtime to expose either named-agent selection or per-spawn model and effort controls. When those controls are absent, the plugin refuses Luna dispatch instead of relabeling an inherited child.

## Contract

- Ordinary chats do not activate the skill or spawn subagents.
- The Codex Desktop model picker remains authoritative for the main thread.
- Every child request explicitly selects `gpt-5.6-luna` with `max` reasoning.
- Adaptive concurrency is 2–4; the explicit hard limit is 8.
- Parallel writers require disjoint paths and one active owner per writable file.
- The main thread owns architecture, safety, integration, diff inspection, final tests, and acceptance.

## Invocation

```text
$sol-luna complete this task
$sol-luna use four Luna agents for read-only parallel analysis
$sol-luna use three Luna agents for parallel implementation
Do not use subagents; complete this in the main thread
```

There is no added Desktop toggle. Invoking `$sol-luna` enables the workflow; explicitly saying not to use subagents disables it.

## Install

macOS / Linux:

```sh
curl -fsSL https://github.com/onlyyuli/codex-sol-luna-workflow/releases/download/v0.1.0/install.sh | sh -s -- install
```

Windows PowerShell:

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing "https://github.com/onlyyuli/codex-sol-luna-workflow/releases/download/v0.1.0/install.ps1").Content)) install
```

Start a new Codex task after installation. For the optional CLI profile, install with `--with-cli-profile` and run `codex --profile sol-luna`.

The Codex CLI maintains the Marketplace and Plugin namespaces in its own `config.toml`. This installer never rewrites existing model, `[agents]` defaults, permission, or unrelated user settings.

## Verify and remove

```sh
./installer/install.sh doctor
./installer/install.sh doctor --smoke-models
./installer/install.sh uninstall
```

The default doctor is non-billable. `--smoke-models` makes one real, potentially billable subagent request. Uninstall removes only unchanged managed files and preserves user modifications.

See [installation](docs/installation.md), [configuration](docs/configuration.md), and [troubleshooting](docs/troubleshooting.md) for details.

## References

The implementation follows official OpenAI documentation for [plugin packaging](https://developers.openai.com/plugins/build/plugins), [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), and [Codex profiles](https://learn.chatgpt.com/docs/config-file/config-advanced).

[BruceLanLan/sol-luna-engineering-workflow](https://github.com/BruceLanLan/sol-luna-engineering-workflow) was research input only. This repository is not a fork and contains an independent v0.1.0 implementation.

## License

[MIT](LICENSE)
