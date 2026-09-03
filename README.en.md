# Codex Sol + Luna Skill

[![CI](https://github.com/onlyyuli/codex-sol-luna-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyyuli/codex-sol-luna-skill/actions/workflows/ci.yml)

[简体中文](README.md) · [Installation](docs/installation.md) · [Architecture](docs/architecture.md) · [Runtime evidence](docs/evidence.md) · [Benchmark](docs/benchmark.md)

An **explicitly enabled, evidence-backed Codex Skill designed to reduce Credit use**.

The main thread always keeps the model selected in the Codex frontend. Non-trivial bounded execution is delegated first to one `gpt-5.6-luna`, `max` leaf agent; parallel agents are reserved for substantial independent work. Routing, architecture, safety, integration, and final acceptance stay in the main thread without repeating Luna's execution.

> [!IMPORTANT]
> The current tree targets `v0.1.0`, but no GitHub Release has been published yet. Use the source installation below today; pinned Release commands become valid only after the matching tag is published.

> [!NOTE]
> This is a community project, not an official OpenAI preset. Sol is a recommendation for the main thread, not a forced configuration. Model access, effective reasoning effort, and concurrency depend on the Codex version and account.

## What this repository contains

The repository distributes a Codex Plugin whose user-facing capability is the explicit `$sol-luna` Skill. A managed installation can also add two namespaced Agent templates, isolated settings, and an optional CLI Profile.

The design makes four contracts visible:

- **Explicit activation:** the Skill runs only after `$sol-luna` is selected and attached in the Codex frontend Skill picker.
- **Clear ownership:** the main thread decides and accepts; Luna Readers and Workers complete bounded task packets.
- **Verifiable identity:** configuration proves only that Luna Max was requested. Agent activity or tool metadata must prove the effective model.
- **Measurable savings:** parent and child Credits are accounted separately; missing child usage never becomes a savings claim.

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
                    |-- LUNA_SINGLE_READ -------> One Luna Max Reader
                    |-- LUNA_SINGLE_WRITE ------> One Luna Max Worker
                    |-- LUNA_READ_PARALLEL -----> Independent Luna Max Readers
                    `-- LUNA_WRITE_PARALLEL ----> Disjoint Luna Max Workers
                                                     |
                                                     `-- Main thread performs targeted acceptance
```

| Route | When it applies | Child behavior |
|---|---|---|
| `MAIN_ONLY` | Small, high-risk, architectural, or still requires duplicated main-thread execution | Creates zero child threads |
| `LUNA_SINGLE_READ` | One bounded, non-trivial exploration, review, or diagnosis | Replaces most main-thread investigation |
| `LUNA_SINGLE_WRITE` | One bounded implementation, test, or documentation task | Completes implementation and local validation |
| `LUNA_READ_PARALLEL` | Isolated heavy scopes reduce unrelated context | Returns independently verifiable evidence |
| `LUNA_WRITE_PARALLEL` | Independent inputs, validation, and disjoint write scopes | Gives every writable file one active owner |

Adaptive concurrency is 1–2 and prefers one Luna. Explicit counts may still be 1–8; counts 3–8 warn that they may cost more than one agent, and requests above 8 are rejected. Every subagent is a leaf.

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
| Minimum-Credit adaptive routing | `Complete this task; prefer one Luna to replace execution and parallelize only when it reduces unrelated context.` |
| Four read-only Readers | `Use four Luna agents for read-only parallel analysis of this repository.` |
| Three disjoint Workers | `Use three Luna agents to implement UI, API, and tests in non-overlapping write scopes.` |
| Force the main thread | `Do not use subagents; complete this only in the main thread.` |

None of these activate the Skill:

- Typing a raw `$sol-luna` string in a prompt.
- Sending the same string through a task API.
- Merely asking for Luna or parallel agents in natural language.

That explicit gate is intentional: `allow_implicit_invocation` is fixed to `false`. A request not to use subagents has the highest priority.

## Current Credit evidence

On 2026-09-03, a low-cost canary used stable Codex CLI 0.153.0. The Sol-only run for one coupled
refactor cost an estimated 9.303 Credits; two Sol + single Luna Max runs cost 5.550 and 6.001
Credits. All validation passed, for a directional 35.50%-40.35% reduction, while elapsed time was
roughly twice the baseline.

This is **not a release-grade savings claim**. It covers one task and one stored baseline; the full
gate still requires all 18 tasks with at least three trials each. See the sanitized, path-free
[`benchmarks/canary-2026-09-03.json`](benchmarks/canary-2026-09-03.json) and the
[benchmark methodology](docs/benchmark.md).

## Main, Reader, and Worker responsibilities

| Role | Owns | Does not own |
|---|---|---|
| Current main thread | Requirements, routing, architecture, safety, ownership, targeted acceptance, and the final answer | Repeating Luna's search, reading, implementation, or full validation |
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
routing_objective = "minimize-credits"
auto_min_agents = 1
auto_max_agents = 2
hard_max_agents = 8
write_parallelism = "disjoint-only"
parent_review = "targeted"
strict_model = true
announce_route = true
```

- Settings cannot change the main model, the Luna child model, or the `max` effort contract.
- Strict mode stops when the runtime cannot guarantee Luna dispatch; it never inherits another model and calls it Luna.
- An adaptive route discloses an unavailable Luna and returns to the main thread. An explicit Luna requirement stops delegation.
- The installer removes or updates only recorded, checksum-matching files and preserves user modifications.
- Existing model, permission, and unrelated fields in the base `config.toml` are not rewritten by the installer.
- v0.1.0 contains no MCP server, App, Hook, telemetry, or external account authentication.
- The benchmark computes total Credits only with complete parent/child evidence; no savings claim is made before the real A/B gates pass.

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
python3 benchmarks/run_matrix.py
```

The isolated integration test uses a temporary `CODEX_HOME` and does not touch an existing Codex configuration. Real model smoke and A/B benchmark runs may consume quota and never run by default.

## Design references and provenance

The implementation follows OpenAI documentation for [Plugin packaging](https://developers.openai.com/plugins/build/plugins), [Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), and [Codex Profiles](https://learn.chatgpt.com/docs/config-file/config-advanced).

[BruceLanLan/sol-luna-engineering-workflow](https://github.com/BruceLanLan/sol-luna-engineering-workflow) was early design research only. This repository is not a fork, does not modify, publish, or install that project, and contains an independent implementation.

## License

[MIT](LICENSE)
