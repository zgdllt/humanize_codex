# Humanize for Codex

[Humanfia Humanize](https://humanfia.ai/projects/humanize) 的 Codex 插件与公开 marketplace。
按需编写和运行顺序、循环、分支、并行及嵌套 Python flow，支持 Codex / DeepSeek Harness（DSH）。
社区适配，非 Humanfia 或 OpenAI 官方插件。Apache-2.0。

## v0.4.0：直接使用 Humanize app / TUI

插件不再提供浏览器看板，也不再添加用于摘要播报的 observer 模型回合。
每次启动 flow 都连接 Humanize 的原生运行会话：

| 环境 | 启动方式 | 用户从哪里观察 |
| --- | --- | --- |
| macOS 桌面，已安装 Humanize app | 打开 Humanize app 并启动 flow | 在 app 侧栏选择返回的工作目录及运行，查看原生流程图、会话、工具调用和用量 |
| SSH、tmux 或终端环境；Linux | 在命名的 tmux 会话中启动官方 Humanize TUI 和 flow | 返回的 session / attach_command；TUI 自动连接本任务 |

终端返回示例：

```text
session: humanize-8a6b31b6f321
attach_command: tmux attach-session -t humanize-8a6b31b6f321
switch_command: tmux switch-client -t humanize-8a6b31b6f321
```

`flow` 窗口运行任务，`tui` 窗口显示官方界面。在已有 tmux 中用 switch_command，
从另一个终端用 attach_command；按 Ctrl-b、d 分离，任务继续。
SSH 的命令需在运行 flow 的那台主机执行。

固定的 hmz 0.2.1 用裸命令 `hmz` 打开 TUI，没有 `hmz tui` 子命令。
插件通过上游 `Humanize(link=...)` 将同一个官方 TUI 连接到本任务的独占会话，
避免裸命令连接到另一个默认会话。无需复制或维护一套界面。

桌面 app 当前没有通用的工作目录深链启动参数；插件会打开 app 并返回 workspace、slot 和
原生 live_route，用户从侧栏选择对应运行。不会声称已经自动聚焦到指定运行。

## 安装

需要 macOS/Linux、`uv` 和可用的后端登录；桌面模式需要安装 Humanize app，
终端/SSH 模式需要 `tmux`。首次启动下载 Python 3.14 与锁定依赖。

```sh
codex plugin marketplace add zgdllt/humanize_codex
codex plugin add humanfia-humanize@humanize-codex
```

重新连接插件或打开新聊天，调用 `humanize_doctor` 检查版本、Codex 路径、DSH 认证就绪状态、
Humanize app 和 tmux。缺少 tmux 时明确报告，不会把任务悄悄改成不可见的后台运行。
提供 Agent Plugins 1.0 的 plugin.json / mcp.json 和兼容入口。
本地开发可将第一条安装命令改为 `codex plugin marketplace add .`。

## 按需主动调用

workflow / author-flow 技能允许隐式调用。agent 在协调、分支或并行有实际价值时选择或编写
flow，用户无需每次指定 Humanize；自己直接完成更快更省时，直接执行。
这是模型按任务作出的选择，不是每条消息都强制运行工作流。

调用 `humanize_run` 后，agent 应立即告知用户 viewer 中的 app 工作目录或 tmux 会话与连接命令。
原生界面持续显示实际事件；执行代理不维护页面、不生成进度摘要。
启动任务不是完成任务，调用方仍应等到终态后报告结果。

## 自定义结构

flow 是普通 async Python 程序。`examples/control_structures.py` 提供：

| 入口 | 结构 |
| --- | --- |
| sequence_flow | 两角色顺序执行 |
| loop_flow | 根据参数执行有界循环 |
| branch_flow | 根据参数选择角色 |
| parallel_flow | 不同会话并行执行，再汇合 |

可以组合这些结构并调用子 flow，不固定套用执行—审查循环。
模型分配放在算法外，flow 声明自己的角色、权限与 FlowParams。
先查 `humanize_library` 中的精选流程；不适合时使用 author-flow 技能编写新的单文件入口。
`humanize_inspect_flow` 检查声明，`humanize_validate_flow` 使用真实 fake engine 测试控制路径。

```json
{
  "workspace": "/absolute/task-workspace",
  "task": "分别检查两种方案并返回可验证结论",
  "flow_file": "/absolute/control_structures.py",
  "entrypoint": "parallel_flow",
  "flow_params": {},
  "read_only": true,
  "duration_seconds": 300,
  "output_tokens": 6000,
  "agents": {
    "first": "codex/gpt-6.1-sol:low",
    "second": "dsh/deepseek-v4-pro:high",
    "humanize_verifier": "codex/gpt-6.1-sol:low"
  }
}
```

通用入口添加独立验收者 humanize_verifier；验收通过返回 complete，需改进返回 needs_work，
由 agent 根据证据选择后续行动。它不将作者的控制结构改写成修复循环。
保留的管理器环境名为 humanize_workspace。

当前支持自包含单文件（不超过 1 MiB）、最多 30 个任务角色和自动本地环境。
并行回合使用不同会话；并发写入使用隔离工作目录并明确集成责任。
只读任务设置 read_only=true。Python 声明、检查与测试会执行可信代码，不是恶意代码沙箱。
多文件与远程环境可使用上游 hmz 完整生命周期。

省略 entrypoint 时使用内置模板：dynamic 为规划 → 执行 → 独立审查，按证据修复或重新规划；
review 省略初始规划。新模板只有 planner / actor / reviewer 三个角色。
max_rounds 只控制内置循环；自定义循环由作者的参数决定。

## 原生运行、取消和恢复

每个 job 使用独占的原生 Host slot，官方 app、TUI 和插件连接同一个 Host。
任务启动前创建 Host，监督器只跟踪本任务 worker 与该 Host，保留用户共享 daemon 和其他运行。
预算覆盖初始化与执行，取消先请求原生停止；同步阻塞超出清理宽限时清理本任务的进程树，
确认退出后发布终态、释放工作目录锁。正常结束保留原生前端用于查看记录。

SDK 的原生 Host 不在消息里返回 Python 结果。插件以一层很薄的入口保存结果，同时沿用
原 flow 的根 journal 上下文，避免恢复时因新的日志目录改变而丢失状态。
这使用固定 hmz 0.2.1 的 FlowImpl.fn；Codex SQLite 初始化竞争仍通过启动握手的窄适配处理。

工具：humanize_run/status/list/wait/events/steer/cancel/resume/open。
`humanize_open(job_id)` 重开界面，不重新执行 flow。TUI host 已结束时打开官方 /epics 历史菜单；
可以根据返回的 epic 名称选择记录。保留的死 tmux pane 会在重开时恢复。

| 状态 | 含义 |
| --- | --- |
| starting / running | 尚未完成 |
| cleaning_up | 正在清理，工作目录仍被占用 |
| complete | 独立验收完成并附证据 |
| blocked / needs_work | 需要输入，或仍有未完成项 |
| round_limit / budget_exceeded | 达到边界，任务未完成 |
| cancelled / failed / lost | 取消、失败或心跳丢失，任务未完成 |

取消/纠偏先返回 queued，查看控制收据及终态确认实际处理。
通用 flow 纠偏可指定 role，对应原生 session key；未指定角色的指导留给 flow 读取。
恢复沿用原源码、目标与 journal，使用新预算；自定义 flow 必须声明 resumable=True。
不会自动恢复用户取消的任务。旧版本保存的源码保持原样，其中显式声明的旧 observer
可能仍会运行；v0.4.0 新模板和新管理器不添加它。

## 模型与流程积累

默认跟随本机 Codex 配置；显式模型失败不静默替换。agents 可覆盖实际角色。
DSH SDK 随插件安装，认证沿用 Humanize/DSH 配置或 DEEPSEEK_API_KEY；doctor 不输出密钥。
支持 dsh@<provider>/<model>:<effort>。全 DSH 任务不要求 Codex CLI。

成功且有独立验收证据的 flow 默认进入私有候选池，按源码和设置去重。
精选需适用范围和限制评估，以及匹配源码哈希/入口的至少两个不同测试场景。
默认搜索、复用、导出和索引使用精选；候选 trial 需 allow_candidate=true，被拒绝项不能绕过。
这是基于证据的 agent 判断，不等于全路径覆盖或跨任务性能保证。
只在有复用价值时进行精选，不把入库评估变成每次任务的附加作业。

Flowverse 源码与索引分开，源码导出到 bundles/<name>/<version>/<name>/，
索引为 flows/<name>/<version>/flow.yaml，固定完整 Git SHA；导出与索引不会自动推送。
任务参数不复制进配方。发布源码前检查其中的私有内容。

数据目录优先 HUMANIZE_CODEX_DATA、PLUGIN_DATA / CLAUDE_PLUGIN_DATA，否则
~/.local/share/humanfia-humanize-codex。运行、收据和 tmux 启动环境位于私有数据目录；
环境文件权限为 0600，不把凭据放在 tmux 命令参数中，也不进入分发包。
原有发布、发送、付费、硬件及范围边界继续有效。

## 开发与验证

```sh
uv sync --frozen --python 3.14
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv build
python3 scripts/package.py
```

常规测试不调用在线模型，包含真实原生 Host、TUI/tmux 启动、取消、恢复与进程归属测试。
没有 tmux 的测试主机跳过 tmux 实测，仍运行 Host 协议测试。
[验证记录](VALIDATION.md) 区分这些测试与实际在线模型运行。

上游：[humanfia/humanize](https://github.com/humanfia/humanize)，Apache-2.0。
固定 PyPI hmz[dsh]==0.2.1，桌面/TUI 行为以该版本为准。
[原生 CLI 参考](https://docs.humanfia.ai/humanize/reference/cli)、
[共享 Host 参考](https://docs.humanfia.ai/humanize/reference/daemon)。
