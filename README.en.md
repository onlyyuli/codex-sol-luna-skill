# Codex Sol + Luna Skill

[![CI](https://github.com/onlyyuli/codex-sol-luna-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyyuli/codex-sol-luna-skill/actions/workflows/ci.yml)

[简体中文](README.md) · [Installation](docs/installation.md) · [Architecture](docs/architecture.md) · [Runtime evidence](docs/evidence.md) · [Benchmark](docs/benchmark.md)

An **explicitly enabled, evidence-first, bounded** Codex Skill.

The main thread always keeps the model selected in the Codex frontend. Only independently verifiable work with a clear boundary is requested from leaf subagents using `gpt-5.6-luna` and `max`. Routing, architecture, safety, integration, and final acceptance stay in the main thread.

> [!IMPORTANT]
> The current tree targets `v0.1.0`, but no GitHub Release has been published yet. Use the source installation below today; pinned Release commands become valid only after the matching tag is published.

> [!NOTE]
> This is a community project, not an official OpenAI preset. Sol is a recommendation for the main thread, not a forced configuration. Model access, effective reasoning effort, and concurrency depend on the Codex version and account.

## What this repository contains

The repository distributes a Codex Plugin whose user-facing capability is the explicit `$sol-luna` Skill. A managed installation can also add two namespaced Agent templates, isolated settings, and an optional CLI Profile.

The design makes three contracts visible:

- **Explicit activation:** the Skill runs only after `$sol-luna` is selected and attached in the Codex frontend Skill picker.
- **Clear ownership:** the main thread decides and accepts; Luna Readers and Workers complete bounded task packets.
- **Verifiable identity:** configuration proves only that Luna Max was requested. Agent activity or tool metadata must prove the effective model.

The Skill does not change the Desktop model picker, turn ordinary chats into multi-agent runs, or silently relabel another model as Luna.

## How it works

```text
Model selected in the Codex frontend (Sol is only recommended)
        |
        |-- Skill not attached ----------------> Current main thread only
        |
        `-- Select and attach $sol-luna
                    |
                    |-- MAIN_ONLY --------------> Current main thread
                    |-- LUNA_READ_PARALLEL -----> Luna Max Readers
                    `-- LUNA_WRITE_PARALLEL ----> Luna Max Workers
                                                     |
                                                     `-- Main thread checks diffs,
                                                         tests, and acceptance
```

| Route | When it applies | Child behavior |
|---|---|---|
| `MAIN_ONLY` | Small, tightly coupled, sequential, high-risk, or explicitly no subagents | Creates zero child threads |
| `LUNA_READ_PARALLEL` | At least two independent exploration, review, analysis, or test packets | Returns read-only evidence in parallel |
| `LUNA_WRITE_PARALLEL` | At least two independently verifiable packets with disjoint write scopes | Gives every writable file one active owner |

Adaptive concurrency is 2–4. Explicit counts may be 1–8; requests above 8 are rejected rather than silently clamped. Every subagent is a leaf and may not create another generation of agents.

## Install from source (available now)

Requirements:

- A Codex CLI with `codex plugin` and Subagent support.
- Python 3.9 or later.
- Account access to `gpt-5.6-luna` for real Luna execution.

macOS / Linux:

```sh
git clone https://github.com/onlyyuli/codex-sol-luna-skill.git
cd codex-sol-luna-skill
./installer/install.sh install \
  --repo-root . \
  --repository onlyyuli/codex-sol-luna-skill \
  --local-marketplace
```

Windows PowerShell:

```powershell
git clone https://github.com/onlyyuli/codex-sol-luna-skill.git
Set-Location codex-sol-luna-skill
.\installer\install.ps1 install --repo-root . --repository onlyyuli/codex-sol-luna-skill --local-marketplace
```

Start a new Codex task after installation, then select `$sol-luna` from the frontend Skill picker.

## Invoke it correctly

Select `$sol-luna` in the frontend and confirm that a Skill chip is attached. Then enter the task as ordinary text—do not type another raw `$sol-luna` token.

| Goal | Prompt after attaching the Skill |
|---|---|
| Adaptive routing | `Complete this task and split independent packets when useful.` |
| Four read-only Readers | `Use four Luna agents for read-only parallel analysis of this repository.` |
| Three disjoint Workers | `Use three Luna agents to implement UI, API, and tests in non-overlapping write scopes.` |
| Force the main thread | `Do not use subagents; complete this only in the main thread.` |

None of these activate the Skill:

- Typing a raw `$sol-luna` string in a prompt.
- Sending the same string through a task API.
- Merely asking for Luna or parallel agents in natural language.

That explicit gate is intentional: `allow_implicit_invocation` is fixed to `false`. A request not to use subagents has the highest priority.

## Main, Reader, and Worker responsibilities

| Role | Owns | Does not own |
|---|---|---|
| Current main thread | Requirements, routing, architecture, safety, file ownership, integration, tests, and the final answer | Treating an unverified child summary as completion evidence |
| `sol_luna_reader` | Code exploration, review, research organization, and test analysis | File edits, architecture decisions, final acceptance, or further delegation |
| `sol_luna_worker` | Implementation, tests, and docs inside an authorized task packet | Expanding `write_scope`, taking shared ownership, final acceptance, or further delegation |

## Requesting Luna Max vs proving Luna Max

Every delegated packet explicitly requests:

```text
model = gpt-5.6-luna
reasoning_effort = max
```

An Agent template, config file, main-thread claim, or observed speed is not proof of the effective model. The project reports actual Luna/Max use only when Agent activity or tool metadata links it to the same newly created, completed child thread.

```sh
./installer/install.sh doctor
./installer/install.sh doctor --smoke-models
```

The default doctor makes no model call. `--smoke-models` makes one real, potentially billable child request and stores JSONL, parent/child linkage, model and effort metadata, Codex version, timestamps, and SHA-256 values under `${CODEX_HOME}/sol-luna/evidence/`. Review a bundle before sharing it because it may contain local paths or account-specific errors. See [runtime evidence](docs/evidence.md).

## Pinned installation after v0.1.0 is released

These commands become valid after the `v0.1.0` Release is published.

macOS / Linux:

```sh
curl -fsSL https://github.com/onlyyuli/codex-sol-luna-skill/releases/download/v0.1.0/install.sh | sh -s -- install
```

Windows PowerShell:

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing "https://github.com/onlyyuli/codex-sol-luna-skill/releases/download/v0.1.0/install.ps1").Content)) install
```

Plugin/Skill only, without global Agent templates, settings, or a CLI Profile:

```sh
codex plugin marketplace add onlyyuli/codex-sol-luna-skill --ref v0.1.0
codex plugin add sol-luna@codex-sol-luna
```

The optional CLI Profile affects only an explicit CLI launch, never the Desktop picker:

```sh
./installer/install.sh install --with-cli-profile
codex --profile sol-luna
```

## Configuration and safety boundaries

A managed install creates `${CODEX_HOME}/sol-luna/settings.toml`:

```toml
auto_min_agents = 2
auto_max_agents = 4
hard_max_agents = 8
write_parallelism = "disjoint-only"
strict_model = true
announce_route = true
```

- Settings cannot change the main model, the Luna child model, or the `max` effort contract.
- Strict mode stops when the runtime cannot guarantee Luna dispatch; it never inherits another model and calls it Luna.
- An adaptive route discloses an unavailable Luna and returns to the main thread. An explicit Luna requirement stops delegation.
- The installer removes or updates only recorded, checksum-matching files and preserves user modifications.
- Existing model, permission, and unrelated fields in the base `config.toml` are not rewritten by the installer.
- v0.1.0 contains no MCP server, App, Hook, telemetry, or external account authentication.
- The project makes no performance-multiplier claim before real A/B results pass the release gates.

See [configuration](docs/configuration.md), [architecture](docs/architecture.md), and [troubleshooting](docs/troubleshooting.md).

## Upgrade and uninstall

From a source clone:

```sh
./installer/install.sh upgrade --repo-root . --repository onlyyuli/codex-sol-luna-skill --local-marketplace
./installer/install.sh uninstall
```

After a Release installation, rerun the same pinned Release wrapper with `upgrade`, `doctor`, or `uninstall`. The one-line installer is fetched into a temporary location and is not permanently copied into the current directory.

## Develop and validate

```sh
python3 tools/sync_repository_metadata.py --repository onlyyuli/codex-sol-luna-skill --check
python3 tools/validate_repository.py
python3 -m unittest discover -s tests -p "test_*.py"
python3 -m unittest discover -s benchmarks/fixture/tests -t benchmarks/fixture
python3 tests/integration_local_install.py
```

The isolated integration test uses a temporary `CODEX_HOME` and does not touch an existing Codex configuration. Real model smoke and A/B benchmark runs may consume quota and never run by default.

## Design references and provenance

The implementation follows OpenAI documentation for [Plugin packaging](https://developers.openai.com/plugins/build/plugins), [Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), and [Codex Profiles](https://learn.chatgpt.com/docs/config-file/config-advanced).

[BruceLanLan/sol-luna-engineering-workflow](https://github.com/BruceLanLan/sol-luna-engineering-workflow) was early design research only. This repository is not a fork, does not modify, publish, or install that project, and contains an independent implementation.

## License

[MIT](LICENSE)
