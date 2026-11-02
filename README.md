# Humanize for Codex

[Humanfia Humanize](https://humanfia.ai/projects/humanize) 的 Codex 插件与公开 marketplace。
直接运行官方 flow，或按需编写顺序、循环、分支、并行与嵌套 Python flow，支持 Codex / DSH。
社区适配，非 Humanfia 或 OpenAI 官方插件。Apache-2.0。

## v0.5.0：官方 flow，默认不限预算

插件不再提供 dynamic/review 模板，也不再为新任务添加 planner、verifier 或轮次上限。
`humanize_run` 的 `flow` 默认是官方 `rlar`；通过 `humanize_catalog` 查看当前上游与已安装流程。
控制结构、结束条件和角色由所选 flow 决定。

| flow | 上游行为 | 结束方式 |
| --- | --- | --- |
| `rlar`（默认） | actor 保持会话，reviewer 每轮重新审查 | reviewer 确认完成，或取消/显式预算耗尽/失败 |
| `ralph_loop` | 每轮使用新会话，重复执行任务 | 取消、显式预算耗尽或失败 |
| `stateful_ralph` | 在同一会话中重复任务，支持 journal 恢复 | 取消、显式预算耗尽或失败 |
| 自定义 Python / SDK ref | 作者自行决定顺序、分支、循环、并行及嵌套 | 作者的返回条件，或取消/显式预算耗尽/失败 |

**默认没有总时长、总输出 token 或费用上限。** 省略 `duration_seconds`、`output_tokens`、
`cost_usd` 时，插件使用 SDK 的 `Budget(cost=math.inf)`。这些字段也接受 null；
显式限额遵循 SDK 契约，没有插件自定的 24 小时、1000 万 token 或费用上限。
无限预算的持续循环会一直运行，直到取消或发生失败；插件不替官方算法添加完成条件。

```json
{
  "workspace": "/absolute/task-workspace",
  "task": "实现并验证这个功能",
  "flow": "rlar",
  "agents": {
    "actor": "codex/gpt-6.1-sol:high",
    "reviewer": "dsh/deepseek-v4-pro:high"
  }
}
```

只有任务本身需要限额时才添加，例如 `duration_seconds: 7200`。
复用、恢复也默认不限预算，可以传入新限额。`humanize_wait` 的每次最长 60 秒是轮询时长，
不是工作流运行上限。

## 安装与更新

需要 macOS/Linux、`uv` 和可用的后端登录。桌面模式需要 Humanize app，终端/SSH 需要 `tmux`。

```sh
codex plugin marketplace add zgdllt/humanize_codex
codex plugin add humanfia-humanize@humanize-codex
```

升级后重新连接插件或打开新聊天，调用 `humanize_doctor` 检查版本、Codex、DSH、app 和 tmux。
0.4.x 调用方应把 mode/max_rounds 换成 flow/flow_params，按所选 flow 的角色名分配模型。
旧请求和旧配方的源码不被重写；恢复仍沿用原模板/envelope 的 journal 结构。
兼容助手只服务旧数据，不供新任务选择。

## 按需主动使用与自定义 flow

agent 在多阶段协调、分支、迭代或并行有实际价值时主动选择 flow；用户无需每次指定插件。
直接完成更快更省时，直接执行。先考虑官方流程和精选配方；不适合时读取 author-flow 技能，
以上游源码/API 为模板编写所需算法，不固定套用执行—审查循环。

- `flow` 接受上游 SDK 的 flow ref，包括官方、已安装和 VCS 包引用，保留其技能资源。
- `flow_file` 与 `entrypoint` 选择可信、自包含的本地 Python 文件；插件冻结源码供恢复和复用。
- `flow_params` 传递所选 flow 自己的参数，`agents` 使用它声明的角色名。
- 新自定义 flow 直接执行，不自动附加独立验收者；需要审查时，由 flow 自己安排。
- `read_only=true` 缩减本地 agent 权限，沿用原角色的技能和能力声明，不改写控制结构。

`examples/control_structures.py` 展示顺序、循环、分支、并行。并行回合使用不同会话；
并发写入应使用独立工作目录并明确集成责任。检查、验证和运行会执行可信 Python，不是代码沙箱。
本地文件的保留/导出支持自包含源码；带相邻模块、技能的包使用 SDK ref。

## 原生 app / tmux TUI

插件没有浏览器看板，也不添加摘要播报 observer。每次运行都连接独占的 Humanize 原生 Host。

| 环境 | 展示方式 |
| --- | --- |
| macOS 桌面，已安装 Humanize app | 打开 app，返回 workspace/epic/slot；用户从侧栏选择对应运行 |
| SSH、终端或 Linux | 命名的 tmux 会话，`tui` 窗口显示官方界面，`flow` 窗口执行任务 |

```text
session: humanize-8a6b31b6f321
attach_command: tmux attach-session -t humanize-8a6b31b6f321
switch_command: tmux switch-client -t humanize-8a6b31b6f321
```

已有 tmux 中使用 switch_command，另一个终端使用 attach_command；Ctrl-b、d 分离。
SSH 命令在运行 flow 的那台主机执行。上游用裸命令 `hmz` 打开 TUI，没有 `hmz tui` 子命令；
插件通过上游 `Humanize(link=...)` 连接本任务。app 尚无通用 workspace 深链，插件不声称自动聚焦。
agent 应立即告知用户界面位置，并在聊天中说明阶段成果、关键发现、下一步和所需决定。

`humanize_open(job_id)` 重开界面，不重跑任务。已结束的 Host 使用官方 /epics 历史菜单。
SDK Host 不直接在消息中返回 Python 结果，插件使用薄入口保存返回值，并传递同一个根 ctx；
入口沿用原 flow 的技能目录和已安装技能记录，不替换算法。

## 状态、取消与恢复

工具：humanize_run/status/list/wait/events/steer/cancel/resume/open。
`starting/running` 表示仍在执行，`cleaning_up` 表示进程清理尚未结束。
`complete` 表示所选 flow 正常返回；应结合结果判断用户任务是否完成。
官方 rlar 在审查通过后返回；任意 Python 的正常返回本身不等于独立验收。
自定义结果可显式报告 complete、blocked、needs_work；旧记录仍保留 round_limit 状态。
`budget_exceeded/cancelled/failed/lost` 都不是完成任务。

纠偏可指定实际角色；控制收据用于确认是否已提交会话。没有可用会话时指导保存在私有文件，
自定义 flow 可按需读取。取消先返回 queued，终态代表本任务已完成清理；不自动恢复用户取消。
恢复要求 flow 声明 resumable=True，沿用目标与根 journal，可指定新的可选预算。
监督器只管理本任务的 worker/Host，清理不影响共享 daemon 和其他任务。

## 模型、配方与数据

默认沿用本机 Codex 配置，显式模型失败不静默替换。DSH SDK 随插件安装，认证沿用现有
Humanize/DSH 配置或 DEEPSEEK_API_KEY；doctor 不输出密钥。全 DSH 任务不要求 Codex CLI。

自定义 flow 正常返回不自动进入精选池。带实际独立审查 action/evidence 的完成结果可进入私有候选池，
再经用途评估、适用范围/限制说明和至少两个匹配源码与入口的不同测试场景，才提升为精选。
官方 flow 直接按引用使用，不重复复制进候选池。只在有复用价值时筛选，不把入库变成每次任务的作业。
Flowverse 导出将源码与索引分开，索引固定完整 Git SHA，不复制任务参数或自动推送。

数据目录优先 HUMANIZE_CODEX_DATA、PLUGIN_DATA / CLAUDE_PLUGIN_DATA，否则
~/.local/share/humanfia-humanize-codex。运行、收据与 tmux 环境位于私有数据目录；
环境文件权限为 0600，凭据不进入 tmux 参数、公开仓库或分发包。已有授权与工作目录边界继续有效。

## Humanize latest 与持续检查

每次新启动 MCP 时从 PyPI 读取当前发布版本，精确安装最新 `hmz[dsh]`，不因兼容性问题退回旧版。
`uv.lock` 仅记录可复现的开发基线。隔离的 uv tool 环境保留运行中流程与全局 hmz 安装；
已经连接的进程在重连后使用新版。启动需要访问 PyPI，首次可能下载 Python 3.14 和依赖。

[latest compatibility CI](https://github.com/zgdllt/humanize_codex/actions/workflows/humanize-latest.yml)
每 6 小时在 Linux/macOS 强制解析最新版本，核对实际版本，测试 MCP、官方 flow、无限预算、
取消/恢复和真实 tmux TUI，保存版本报告、JUnit 与锁文件。也支持相关 push/PR、手动运行与
`repository_dispatch` 的 `humanize-release` 事件。常规 Checks 测试锁定基线；CI 不调用在线模型。

```sh
uv sync --frozen --python 3.14
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv build
python3 scripts/package.py
```

[验证记录](VALIDATION.md) 区分已实现、实测与历史在线运行限制。
上游：[humanfia/humanize](https://github.com/humanfia/humanize)、
[Flow API](https://docs.humanfia.ai/humanize/reference/flows)、
[SDK](https://docs.humanfia.ai/humanize/reference/sdk)。
