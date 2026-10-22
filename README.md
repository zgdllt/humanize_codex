# Humanize for Codex

[Humanfia Humanize](https://humanfia.ai/projects/humanize) 的 Codex 插件与公开 marketplace。
动态规划、执行、独立审查、修复和重新规划由真实 Humanize Python 引擎运行。
支持 Codex 与 DeepSeek Harness（DSH），并保留经过审查的可复用 flow。
社区适配，非 Humanfia 或 OpenAI 官方插件。Apache-2.0。

## 安装

需要 macOS/Linux、`uv` 和可用的 Codex CLI 登录。首次启动会下载 Python 3.14 与锁定依赖。

```sh
codex plugin marketplace add zgdllt/humanize_codex
codex plugin add humanfia-humanize@humanize-codex
```

重新连接插件或打开新聊天，然后调用 `humanize_doctor`。
插件使用 `hmz[dsh]==0.2.1`、MCP Python SDK 和 `uv.lock`，运行环境位于插件数据目录。
提供 Agent Plugins 1.0 的 `plugin.json` / `mcp.json` 以及兼容入口。

本地开发可将第一条安装命令改为 `codex plugin marketplace add .`。

## 使用

> 用 Humanize 动态工作流完成这个功能，保留已有改动。按实际情况调整方案，
> 实现后独立审查并修复。最多六轮、30 分钟。由 flow 内的状态 agent 维护看板。

也可显式调用 `humanize-workflow`、`humanize-author-flow` 或 `humanize-setup` 技能。

```text
规划 → 执行 → 独立审查 ─ complete → 返回证据
                    ├ fix      → 原执行会话修复 → 再审查
                    ├ replan   → 重新规划 → 执行 → 再审查
                    └ blocked  → 请求必要输入

独立 observer agent ── 消费运行时阶段事件 ── 维护实时看板摘要
```

执行者保留会话；每轮审查开启新会话，检查实际文件与结果。
`review` 模式省略首次规划，仍可触发重新规划。分析任务使用 `read_only=true`。
默认六轮、1800 秒、50,000 输出 token；`cost_usd` 可选。预算覆盖全部角色。

### Codex 与 DSH 分工

默认跟随本机 Codex 配置；显式选择的模型失败时不会静默替换。
`agent` 设置通用模型，`agents` 可分别覆盖四个角色，例如：

```json
{
  "agent": "codex/gpt-6.1-sol:high",
  "agents": {
    "actor": "dsh/deepseek-v4-pro:high",
    "reviewer": "codex/gpt-6.1-sol:high",
    "observer": "codex/gpt-6.1-sol:low"
  }
}
```

DSH SDK 随插件安装；凭据沿用 Humanize/DSH 的配置与 `DEEPSEEK_API_KEY`，
也可指定上游支持的 `dsh@<provider>/<model>:<effort>`。插件不代填或上传密钥。
`humanize_doctor(workspace=...)` 返回 SDK 版本和本地认证是否就绪，不返回密钥。
全 DSH 的任务无需安装 Codex CLI；宿主仍是 Codex 插件。

有多个 Codex 安装时会检查 PATH 和 `~/.local/bin/codex`，选择版本最新的 CLI。
`HUMANIZE_CODEX_BINARY` 可指定绝对路径，优先于自动选择。

## 进度由 flow 内的 agent 负责

`observer` 是 flow 声明的第四个角色，拥有单独的只读会话，禁用在线搜索。
它异步消费结构化阶段事实，生成 `report.json` 中的简短状态与下一步。
不读取完整任务，不指挥执行者，不参与验收决策。消息队列只保留最新事件。
每轮播报有 30 秒与 800 输出 token 的边界，每次运行最多 24 次；全部计入总预算。

看板 HTTP 服务持续读取运行时事实与 observer 摘要，每秒刷新。
主执行 agent 无需轮询、整理日志或维护网页；observer 超时或失败不会拖住任务结束。
针对 hmz 0.2.1 / Codex 0.163 的 SQLite 初始化竞争，flow 串行启动握手，模型回合仍并发；
此兼容适配也包含在保留和导出的单文件 flow 内，不改写用户数据库或已安装 SDK 文件。
阶段、轮数、心跳、模型、最近活动、消耗与剩余时间由程序记录。
播报文字与这些事实分别显示，完成状态由独立审查决定。

调用 `humanize_dashboard` 获取本地只读地址，在 Codex 浏览器或普通浏览器打开。
服务只监听 `127.0.0.1`，地址带随机访问令牌，拒绝外站 Origin/Host 和写请求。
看板不展示任务原文或会话记录；不要把私有看板地址公开转发。
没有访问且无活动任务一小时后，服务退出；再次调用工具可重启。

MCP `humanize_wait` 提供协议进度通知，部分宿主可能不展示。
聊天只需报告启动、需要决策的阻塞和最终结果。终端也可持续查看：

```sh
python3 scripts/launch.py watch JOB_ID
```

## 积累、复用与 Flowverse

通过独立审查并带有证据的 `complete` 运行默认自动保留：

- 实际运行的 Python 代码快照及 SHA-256；运行开始后源文件变化不会影响它。
- 模式、只读权限、角色模型分工与轮数。
- 本地观察的成功次数和用量，重复保存同一运行不会重复计数。

不保存任务原文或审查转录到 flow 配方。观察次数不是跨任务质量排名。
可用 `retain_flow=false` 关闭自动积累。

| 操作 | MCP 工具 |
| --- | --- |
| 列出本地配方 | `humanize_library` |
| 给已通过审查的运行命名 | `humanize_save_flow(job_id, name, description)` |
| 用新任务与预算复用 | `humanize_reuse_flow(name, workspace, task, ...)` |
| 导出不可覆盖的版本源码包 | `humanize_export_flow(name, destination, version)` |
| 生成固定 Git 提交的索引 | `humanize_index_flow(name, version, destination, repo, commit, subdir, ...)` |

Flowverse 采用[当前 Humanize 的索引格式](https://docs.humanfia.ai/humanize/weaver/flowverses)：
源码仓库与索引分开。源码导出到 `bundles/<name>/<version>/<name>/`；
索引生成 `flows/<name>/<version>/flow.yaml`，固定完整 40 位 Git commit。
可将自己的 Flowverse fork（例如 [zgdllt/flowverse](https://github.com/zgdllt/flowverse)）
作为索引。源码可放在独立的公开或私有仓库，按权限分享。

导出不含本地运行 ID、任务文本和审查转录；自定义源码、描述和模型账号别名仍应在发布前检查。
索引生成只验证清单格式，不声称远端源码已经测试。提交源码后，用 Humanize 安装并验证
固定版本，再发布索引。保存、导出、生成清单均不会自动提交或推送。

## 自定义 flow

`humanize-author-flow` 使用上游公开 Python API 编写和测试条件分支、角色及持久状态。
管理器的 `flow_file` 参数接受可信的单文件 Python flow，需保留以下契约：

- 导出 `dynamic_workflow` 和 `read_only_workflow` 两个 async `@flow` 入口。
- 角色为 `planner`、`actor`、`reviewer`、`observer`，环境为 `workspace`。
- 参数为 `mode`、`max_rounds`、`artifacts`、`guidance`，journal 可恢复。
- 只读入口声明只读权限；结果区分 `complete`、`blocked`、`round_limit`，完成附审查证据。

从内置 `src/humanize_codex/flow.py` 复制并调整是最直接的起点。
单文件在运行开始时快照，成功后可积累和导出。Python flow 是可执行代码，
不自动下载或执行来自网页、日志或未知 Flowverse 的建议。
更通用的任意角色/多文件 flow 使用上游 `hmz exec`，沿用其生命周期。

## 生命周期与控制

工具包括 `humanize_run/status/list/wait/events/steer/cancel/resume`，以及上文的库和看板工具。
每个工作目录同时只允许一个管理器任务，实际文件锁持续到 worker 退出。
关闭聊天或 MCP 连接不会丢弃任务。

| 状态 | 含义 |
| --- | --- |
| `starting` / `running` | 尚未完成 |
| `complete` | 独立审查报告验收完成，附证据 |
| `blocked` | 缺少必要输入或授权 |
| `round_limit` / `budget_exceeded` | 达到边界，任务未完成 |
| `cancelled` | 已观察到取消并结束 |
| `failed` / `lost` | 失败或心跳丢失，任务未完成 |

纠偏与取消先返回 `queued`，通过 `control_receipt` 查看实际处理结果。
纠偏只尝试提交给执行者，不会送给 observer；后续回合也会读入指导。
DSH 不支持中途插入时在下一回合生效。取消后验证终态。
恢复建立新预算的运行，沿用原代码快照、目标与 journal；不自动恢复被用户取消的任务。

## 存储与权限

使用 `HUMANIZE_CODEX_DATA`，否则宿主的 `PLUGIN_DATA` / `CLAUDE_PLUGIN_DATA`，
再否则 `~/.local/share/humanfia-humanize-codex`。
`runs/` 存私有任务、状态、事件与审查；`library/` 存可复用代码；Humanize 原生 epic 路径由状态返回。
分发包不包含这些目录、凭据、虚拟环境或本地日志。

规划者和审查者声明只读权限，执行者为工作目录写权限，observer 为只读且禁用在线搜索。
实际隔离沿用 Humanize 与所选后端，语义约束不等于额外操作系统沙箱。
任务提示保留发布、发送、付费、物理硬件和范围变更的授权要求。
建议先在独立或临时工作目录验证。子工作流不能递归启动本插件。

## 开发与验证

```sh
uv sync --frozen --python 3.14
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv build
python3 scripts/package.py
```

常规测试不调用在线模型。覆盖真实 Humanize fake engine、MCP 协议、Codex/DSH 分工、
observer 隔离、状态与控制、flow 保留及真实 Git Flowverse 安装。
[验证记录](VALIDATION.md) 区分模拟控制流测试与真实模型烟雾测试。

上游：[humanfia/humanize](https://github.com/humanfia/humanize)，Apache-2.0。
运行固定 PyPI `hmz==0.2.1`；API 调研参考上游提交
`ac732f1e9fc3ea11dc2eb660f934ec7da73ca5f0`，不将两者混同。
插件格式参考 [Codex 文档](https://developers.openai.com/plugins/build/plugins)。
