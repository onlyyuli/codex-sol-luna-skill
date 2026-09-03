# Codex Sol + Luna Skill

[![CI](https://github.com/onlyyuli/codex-sol-luna-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/onlyyuli/codex-sol-luna-skill/actions/workflows/ci.yml)

[English](README.en.md) · [安装](docs/installation.md) · [架构](docs/architecture.md) · [运行证据](docs/evidence.md) · [评测](docs/benchmark.md)

一枚**由用户显式启用、以真实额度节省为目标、证据优先**的 Codex Skill。

主线程始终使用你在 Codex 前端选择的模型；非简单且边界清晰的执行工作会优先交给一个 `gpt-5.6-luna`、`max` 叶子 Agent，只有实质独立的重任务才会并行。主线程保留路由、架构、安全、整合与最终验收权，但不会重复 Luna 已完成的工作。

> [!IMPORTANT]
> 当前代码树以 `v0.1.0` 为目标，尚未发布正式 GitHub Release。现在请使用下方“从源码安装”；Release 下载命令仅在对应标签发布后可用。

> [!NOTE]
> 这是社区项目，不是 OpenAI 官方预设。Sol 只是推荐的主线程模型，不是强制配置；模型权限、有效推理档位和并发能力取决于 Codex 版本及账户。

## 它到底是什么

本仓库交付一个用于分发和安装的 Codex Plugin，其中面向用户的核心能力是一枚名为 `$sol-luna` 的 Skill。托管安装还可以安装两个 namespaced Agent 模板、独立 settings 和可选 CLI Profile。

它解决四个具体问题：

- **开关明确**：只有从 Codex 前端 Skill 选择器选择并附加 `$sol-luna` 才会启用。
- **职责明确**：主线程决策与验收，Luna Reader/Worker 只完成边界明确的任务包。
- **证据明确**：配置只能证明“请求了 Luna Max”；实际模型必须由 Agent 活动或工具元数据证明。
- **节省可测**：父线程和每个子线程分别核算 Credit；缺少子线程用量时不声称节省。

它不会修改 Codex Desktop 的模型按钮，不会把普通对话自动变成多 Agent，也不会用其他模型静默冒充 Luna。

## 工作方式

```text
Codex 前端选择的主模型（Sol 仅为建议）
        │
        ├─ 未附加 Skill ─────────────────────> 当前主线程独立完成
        │
        └─ 前端选择并附加 $sol-luna
                    │
                    ├─ MAIN_ONLY ─────────────> 当前主线程
                    ├─ LUNA_SINGLE_READ ──────> 1 个 Luna Max Reader
                    ├─ LUNA_SINGLE_WRITE ─────> 1 个 Luna Max Worker
                    ├─ LUNA_READ_PARALLEL ────> 独立的 Luna Max Readers
                    └─ LUNA_WRITE_PARALLEL ───> 互斥范围的 Luna Max Workers
                                                   │
                                                   └─ 主线程定向检查并验收
```

| 路由 | 适用条件 | 子 Agent 行为 |
|---|---|---|
| `MAIN_ONLY` | 简单、高风险、架构决策或委派后仍需主线程重复执行 | 创建 0 个子线程 |
| `LUNA_SINGLE_READ` | 一个有界的非简单探索、审查或诊断 | 一个 Reader 替代主线程的主要调查 |
| `LUNA_SINGLE_WRITE` | 一个有界实现、测试或文档任务 | 一个 Worker 完成实现和局部验证 |
| `LUNA_READ_PARALLEL` | 独立重范围拆开后可减少无关上下文 | Reader 分别返回可验证证据 |
| `LUNA_WRITE_PARALLEL` | 独立输入、验证和互斥写入范围 | 每个文件只有一个活跃负责人 |

自适应并发为 1–2，默认优先单 Luna。显式数量仍允许 1–8；3–8 会提示可能比单 Agent 消耗更多 Credit，请求超过 8 会被拒绝。子 Agent 是叶子节点，不能继续创建孙 Agent。

## 从源码安装（当前可用）

要求：

- Codex CLI 支持 `codex plugin` 与 Subagents。
- Python 3.9 或更高版本。
- 真实 Luna 执行需要账户可访问 `gpt-5.6-luna`。

macOS / Linux：

```sh
git clone https://github.com/onlyyuli/codex-sol-luna-skill.git
cd codex-sol-luna-skill
./installer/install.sh install \
  --repo-root . \
  --repository onlyyuli/codex-sol-luna-skill \
  --local-marketplace
```

Windows PowerShell：

```powershell
git clone https://github.com/onlyyuli/codex-sol-luna-skill.git
Set-Location codex-sol-luna-skill
.\installer\install.ps1 install --repo-root . --repository onlyyuli/codex-sol-luna-skill --local-marketplace
```

安装完成后，新建一个 Codex 任务，再从前端 Skill 选择器中选择 `$sol-luna`。

## 正确使用方式

先在前端选择 `$sol-luna`，确认输入框中出现 Skill 标签，然后输入普通任务文本。不要再手工输入 `$sol-luna` 字符串。

| 目标 | 选择 Skill 后输入 |
|---|---|
| 最省额度的自适应路由 | `完成这个任务；优先让一个 Luna 替代主要执行，只在更省上下文时并行。` |
| 四个只读 Reader | `使用 4 个 Luna，只读并行分析这个仓库。` |
| 三个互斥 Worker | `使用 3 个 Luna，并行实现 UI、API 和测试；写入范围不能重叠。` |
| 强制主线程 | `不要使用子 Agent，只在主线程完成。` |

以下情况都**不会激活** Skill：

- 只在提示词中键入 `$sol-luna`。
- 通过任务 API 发送同名字符串。
- 仅用自然语言要求 Luna 或并行 Agent。

这是刻意设计的显式开关；`allow_implicit_invocation` 固定为 `false`。“不要使用子 Agent”的优先级最高。

## 当前额度验证状态

2026-09-03 使用稳定版 Codex CLI 0.153.0 做了一个低成本 canary：同一耦合改造任务的
Sol-only 基线为 9.303 Credits，两次 Sol + 单 Luna Max 分别为 5.550 和 6.001 Credits，
功能验证均通过，观察到 35.50%–40.35% 的方向性降幅；但耗时约为基线的两倍。

这**不是发布级节省承诺**。样本只有一个任务和一个基线，完整门禁仍要求 18 个任务各至少
3 次。去除本地路径和对话内容的结构化数据见
[`benchmarks/canary-2026-09-03.json`](benchmarks/canary-2026-09-03.json)，方法和限制见
[评测说明](docs/benchmark.md)。

## Main、Reader、Worker 的职责

| 角色 | 负责 | 不负责 |
|---|---|---|
| 当前主线程 | 需求解释、路由、架构、安全、文件所有权、定向整合验收和最终回复 | 重复 Luna 的搜索、阅读、实现或完整验证 |
| `sol_luna_reader` | 代码探索、审查、资料整理和测试分析 | 编辑文件、架构裁决、最终验收、继续派发 |
| `sol_luna_worker` | 任务包授权范围内的实现、测试和文档修改 | 越过 `write_scope`、修改共享所有权、最终验收、继续派发 |

## “请求 Luna Max”与“证明 Luna Max”

每次派发都会显式请求：

```text
model = gpt-5.6-luna
reasoning_effort = max
```

但 Agent 模板、配置文件、主线程文字或运行速度都不是实际模型证明。只有 Agent 活动或工具元数据明确关联到本次新建且完成的子线程时，项目才报告实际使用了 Luna/Max。

```sh
./installer/install.sh doctor
./installer/install.sh doctor --smoke-models
```

默认 `doctor` 不调用模型。`--smoke-models` 会发起一次真实、可能计费的最小子 Agent 请求，并把 JSONL、父/子线程关联、模型与推理档位、Codex 版本、时间戳和 SHA-256 保存到 `${CODEX_HOME}/sol-luna/evidence/`。分享证据包前请先检查，其中可能包含本地路径或账户相关错误信息。详见[运行证据](docs/evidence.md)。

## 发布 v0.1.0 后的固定版本安装

以下命令会在 `v0.1.0` Release 发布后可用。

macOS / Linux：

```sh
curl -fsSL https://github.com/onlyyuli/codex-sol-luna-skill/releases/download/v0.1.0/install.sh | sh -s -- install
```

Windows PowerShell：

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing "https://github.com/onlyyuli/codex-sol-luna-skill/releases/download/v0.1.0/install.ps1").Content)) install
```

只安装 Plugin/Skill，不安装全局 Agent 模板、settings 或 CLI Profile：

```sh
codex plugin marketplace add onlyyuli/codex-sol-luna-skill --ref v0.1.0
codex plugin add sol-luna@codex-sol-luna
```

可选 CLI Profile 只对显式 CLI 启动生效，不影响 Desktop 前端选择：

```sh
./installer/install.sh install --with-cli-profile
codex --profile sol-luna
```

## 配置与安全边界

托管安装创建 `${CODEX_HOME}/sol-luna/settings.toml`：

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

- settings 不能修改主线程模型、Luna 子模型或 `max` 推理档位。
- 运行时无法保证 Luna 派发时，严格模式会停止；不会继承其他模型后改名为 Luna。
- 自适应模式下 Luna 不可用会披露并回到主线程；明确要求 Luna 时则停止派发。
- 安装器只管理登记且校验和未变化的文件；用户修改过的文件会保留。
- 基础 `config.toml` 中已有的模型、权限和无关字段不会被安装器重写。
- v0.1.0 不包含 MCP、App、Hook、遥测或外部账号认证。
- benchmark 只有在父/子用量证据完整时才计算总 Credit；尚未通过真实 A/B 门禁前不声称节省比例。

详见[配置说明](docs/configuration.md)、[架构](docs/architecture.md)和[故障排查](docs/troubleshooting.md)。

## 升级与卸载

从源码 clone 中运行：

```sh
./installer/install.sh upgrade --repo-root . --repository onlyyuli/codex-sol-luna-skill --local-marketplace
./installer/install.sh uninstall
```

Release 安装后，应重新执行同一固定 Release 的包装器并把子命令改为 `upgrade`、`doctor` 或 `uninstall`；一行安装脚本本身不会永久复制到当前目录。

## 开发与验证

```sh
python3 tools/sync_repository_metadata.py --repository onlyyuli/codex-sol-luna-skill --check
python3 tools/validate_repository.py
python3 -m unittest discover -s tests -p "test_*.py"
python3 -m unittest discover -s benchmarks/fixture/tests -t benchmarks/fixture
python3 tests/integration_local_install.py
python3 benchmarks/run_matrix.py
```

最后一个测试使用临时 `CODEX_HOME`，不会接触现有 Codex 配置。真实 smoke 和 A/B benchmark 可能产生费用，默认不会自动执行。

## 设计依据与来源

实现以 OpenAI 的 [Plugin 打包文档](https://developers.openai.com/plugins/build/plugins)、[Codex Subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents) 和 [Codex Profiles 文档](https://learn.chatgpt.com/docs/config-file/config-advanced) 为准。

[BruceLanLan/sol-luna-engineering-workflow](https://github.com/BruceLanLan/sol-luna-engineering-workflow) 仅作为早期设计调研资料。本仓库不是其 Fork，不修改、不发布也不安装对方项目，当前实现独立完成。

## License

[MIT](LICENSE)
