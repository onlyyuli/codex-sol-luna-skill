# Codex Sol + Luna Workflow

[English](README.en.md) · [安装指南](docs/installation.md) · [架构](docs/architecture.md) · [运行证据](docs/evidence.md) · [评测](docs/benchmark.md)

一个显式调用、全局可安装的 Codex 编排插件：保留用户在前端选择的主线程模型，只把边界明确、可独立验证的工作派给 GPT-5.6 Luna Max 子 Agent。

> 这是社区项目，不是 OpenAI 官方预设。模型权限、有效推理档位、并发和实际路由取决于 Codex 版本及账户；只有 Agent 活动或工具元数据能证明实际运行的模型。

> 严格模式还要求当前 Codex 运行时暴露命名 Agent 选择或逐次派发的模型/推理参数；若能力缺失，插件会拒绝 Luna 派发，而不会把继承主模型的子线程冒充 Luna。

## 核心行为

```text
Codex 前端所选主模型（推荐 Sol）
        │
        ├─ 普通对话 / 明确禁用 → MAIN_ONLY
        │
        └─ $sol-luna
               ├─ MAIN_ONLY
               ├─ LUNA_READ_PARALLEL
               └─ LUNA_WRITE_PARALLEL → GPT-5.6 Luna Max
```

- 普通对话不会自动激活该技能或创建子 Agent。
- Codex Desktop 的模型按钮始终控制主线程；插件不设置主线程模型。
- 子 Agent 固定请求 `gpt-5.6-luna` 与 `max`。
- 自适应并发为 2–4，显式上限为 8。
- 并行写入要求文件范围互斥，并遵守“一份文件一个活跃负责人”。
- 主线程负责架构、安全、整合、真实 diff 检查、最终测试和验收。

## 使用

自适应路由：

```text
$sol-luna 完成这个任务
```

强制只读分析：

```text
$sol-luna 使用 4 个 Luna，只读并行分析这个仓库
```

边界互斥时并行实现：

```text
$sol-luna 使用 3 个 Luna，并行实现 UI、API 和测试
```

关闭子 Agent：

```text
不要使用子 Agent，只在主线程完成这个任务
```

没有额外的前端开关；调用 `$sol-luna` 是开启入口，“不要使用子 Agent”是强制关闭入口。

## 五分钟安装

macOS / Linux：

```sh
curl -fsSL https://github.com/onlyyuli/codex-sol-luna-workflow/releases/download/v0.1.0/install.sh | sh -s -- install
```

Windows PowerShell：

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing "https://github.com/onlyyuli/codex-sol-luna-workflow/releases/download/v0.1.0/install.ps1").Content)) install
```

可选安装 Sol CLI Profile：

```sh
./installer/install.sh install --with-cli-profile
codex --profile sol-luna
```

安装完成后新建一个 Codex 任务，再调用 `$sol-luna`。

### 纯 Plugin 安装

不安装全局 Agent 模板、settings 或 CLI Profile：

```sh
codex plugin marketplace add onlyyuli/codex-sol-luna-workflow --ref v0.1.0
codex plugin add sol-luna@codex-sol-luna
```

Codex CLI 会在自己的 `config.toml` 中维护该 Marketplace 和 Plugin 的命名空间；本项目安装器不会修改已有的 `model`、`[agents]` 默认值、权限或其他用户字段。

## 诊断与卸载

```sh
./installer/install.sh doctor
./installer/install.sh doctor --smoke-models
./installer/install.sh uninstall
```

`doctor` 默认不调用模型。`--smoke-models` 会执行一次真实、可能计费的最小子 Agent 测试，并把 CLI JSONL、关联的父/子 rollout、子线程 ID、模型与推理档位、Codex 版本、UTC 时间戳及 SHA-256 校验值自动保存到 `${CODEX_HOME}/sol-luna/evidence/`。只有本次新建且完成的同一个子线程同时证明 Luna、Max 和子线程校验标记时才通过；详见 [运行证据](docs/evidence.md)。

发布验证应使用官方当前稳定 CLI。若 `codex` 实际指向 Desktop 内置的预发布版本，可用
`--codex-bin /absolute/path/to/codex` 或 `SOL_LUNA_CODEX_BIN` 显式选择稳定 CLI；smoke
会在单次进程内直接使用 HTTPS，并且不会修改基础 `config.toml`。

卸载只删除安装状态中登记且校验和未变化的文件；用户修改过的 settings、Agent 或 Profile 会被保留并明确报告。

## 配置

托管安装创建 `${CODEX_HOME}/sol-luna/settings.toml`：

```toml
auto_min_agents = 2
auto_max_agents = 4
hard_max_agents = 8
write_parallelism = "disjoint-only"
strict_model = true
announce_route = true
```

该文件不能修改主线程模型、Luna 子模型或 `max` 推理档位。详见 [配置说明](docs/configuration.md)。

## 本地开发验证

```sh
python3 tools/validate_repository.py
python3 -m unittest discover -s tests
python3 tests/integration_local_install.py
```

真实隔离安装测试使用临时 `CODEX_HOME`，不会接触现有 Codex 配置。

## 设计依据

实现以 [OpenAI Plugin 打包文档](https://developers.openai.com/plugins/build/plugins)、[Codex Subagents 文档](https://learn.chatgpt.com/docs/agent-configuration/subagents) 和 [Codex Profiles 文档](https://learn.chatgpt.com/docs/config-file/config-advanced) 为准。

[BruceLanLan/sol-luna-engineering-workflow](https://github.com/BruceLanLan/sol-luna-engineering-workflow) 仅作为早期设计调研资料。本仓库不是其 Fork，不修改、不发布也不安装对方项目，v0.1.0 为独立实现。

## License

[MIT](LICENSE)
