# Humanize for Codex

[Humanfia Humanize](https://humanfia.ai/projects/humanize) 的 Codex 插件与公开 marketplace。
由真实 Humanize Python 引擎执行按任务编写的顺序、循环、分支、并行与嵌套工作流，
支持 Codex / DeepSeek Harness（DSH）、独立验收、flow 内状态 observer，以及筛选后的流程库。
社区适配，非 Humanfia 或 OpenAI 官方插件。Apache-2.0。

## 安装与自动选择

需要 macOS/Linux、`uv` 和可用的后端登录。首次启动下载 Python 3.14 与锁定依赖。

```sh
codex plugin marketplace add zgdllt/humanize_codex
codex plugin add humanfia-humanize@humanize-codex
```

重新连接插件或打开新聊天，调用 `humanize_doctor` 检查运行环境。
提供 Agent Plugins 1.0 的 `plugin.json` / `mcp.json` 和兼容入口。
本地开发可将第一条命令改为 `codex plugin marketplace add .`。

**用户无需在每次任务中指定 Humanize。** workflow/author-flow 技能允许隐式调用，
MCP 的启动指令要求 agent 在多阶段协调、证据驱动分支、迭代验证或并行确有价值时主动使用；
简单问答、单步修改直接完成。这是模型按任务判断的使用策略，不是拦截每条消息的强制路由器。
全局 AGENTS.md 也可加入这段规则：

> 对需要多阶段协调、证据驱动分支、迭代验证或并行代理的任务，主动选择 Humanize 工作流
> 或编写适合任务的新 flow，无需等待用户指名；简单任务直接完成。先查精选 flow，
> 根据任务选择顺序、循环、分支、并行或组合。由独立 observer 负责进度与看板，
> 执行代理专注任务。沿用已有授权、预算和工作目录边界。

## 自由编写控制结构

flow 是 async Python 程序，不是固定的提示词链或固定的执行—审查循环。
`examples/control_structures.py` 提供四个可实际运行的独立入口：

| 入口 | 结构 | 行为 |
| --- | --- | --- |
| `sequence_flow` | 顺序 | 先分析，再交给另一角色检查 |
| `loop_flow` | 有界循环 | 按输入的次数执行，返回每次结果 |
| `branch_flow` | 条件分支 | 根据参数选择不同角色 |
| `parallel_flow` | 并行汇合 | 两个独立会话同时分析，再汇总 |

可以组合这些结构、调用其他 flow、按结构化输出或真实检查结果决定下一步。
模型可主动 draft 适合当前任务的新 flow。模型/后端分配放在 flow 外，算法不绑定模型名。

1. `humanize_library` 搜索精选流程并阅读适用范围；不适合时使用 `humanize-author-flow`。
2. 在可信的单文件 `.py` 中声明自己的 `AgentCollection`、本地 `EnvCollection`、
   `FlowParams` 与一个选定的 async `@flow` 入口，无需四个固定角色或两个固定入口。
3. `humanize_inspect_flow` 返回角色、权限、参数 schema、是否可恢复和静态结构提示。
4. `humanize_validate_flow` 使用真实 fake engine 执行带预期结果的脚本场景。
5. `humanize_run` 传入 `flow_file`、`entrypoint`、`flow_params` 和按实际角色命名的 `agents`。

例如运行并行入口：

```json
{
  "workspace": "/absolute/task-workspace",
  "task": "分别检查两种方案，返回可验证的结论",
  "flow_file": "/absolute/control_structures.py",
  "entrypoint": "parallel_flow",
  "flow_params": {},
  "read_only": true,
  "duration_seconds": 300,
  "output_tokens": 6000,
  "agents": {
    "first": "codex/gpt-6.1-sol:low",
    "second": "dsh/deepseek-v4-pro:high",
    "humanize_verifier": "codex/gpt-6.1-sol:low",
    "humanize_observer": "codex/gpt-6.1-sol:low"
  }
}
```

管理器为自定义 flow 另加独立验收者 `humanize_verifier` 和状态角色 `humanize_observer`；
其环境名 `humanize_workspace` 也保留。自定义流程内部结构由作者决定。
验收通过才返回 `complete`；需改进时返回 `needs_work`，由 agent 根据证据决定后续工作。
管理器不会把自定义程序改写成修复循环。并发回合必须使用不同会话；并发写入应使用隔离
工作目录并明确集成责任，同目录并行分析应为只读。

目前管理器接受不超过 1 MiB 的自包含单文件、最多 30 个任务角色和自动本地环境。
多文件依赖、远程环境配置可使用上游 `hmz` 的完整生命周期。
结构标签来自语法分析，不等同于精确的执行图；Python flow 的声明、检查和测试都会执行
可信代码，不是安全沙箱。不下载并执行网页、日志或未知流程库中的代码建议。

## 内置模板仍可使用

省略 `entrypoint` 时，`dynamic` 模式采用规划 → 执行 → 独立审查，按证据修复或重新规划；
`review` 模式省略初始规划。它们是便捷模板，不代表插件只支持这一种结构。
默认六轮、1800 秒、50,000 输出 token；自定义循环由自身参数决定，`max_rounds` 仅约束
管理器 observer 的播报次数。分析任务设置 `read_only=true`，声明写权限的自定义角色会被拒绝。

默认跟随本机 Codex 配置；显式模型失败不会静默替换。`agent` 为默认分配，`agents` 覆盖实际角色。
DSH SDK 随插件安装，认证沿用 Humanize/DSH 配置或 `DEEPSEEK_API_KEY`；
也支持 `dsh@<provider>/<model>:<effort>`。doctor 只报告认证是否就绪，不输出密钥。
全 DSH 的运行无需 Codex CLI。多个 Codex 安装会选择 PATH / `~/.local/bin/codex` 中最新版，
或使用 `HUMANIZE_CODEX_BINARY` 指定的绝对路径。

## 候选池与精选库

**运行成功不等于流程值得复用。** 默认仅将 `complete`、独立验收 action 为 complete 且有证据
的运行保留为私有候选，按代码与设置去重。`retain_flow=false` 可关闭自动保留。
失败、阻塞或预算耗尽不会自动进入库；升级前的条目也按未筛选候选处理。

| 层级 | 门槛 | 默认使用 |
| --- | --- | --- |
| candidate | 真实任务通过独立验收、有证据 | 搜索隐藏；仅明确 trial 时复用/导出 |
| curated | 评估适用范围与限制；同代码哈希和入口至少两个不同脚本场景通过 | 默认搜索、复用、导出和索引 |
| rejected | 不适合复用、脆弱或重复等，有拒绝理由 | 拒绝复用和导出，需重新评估 |

流程筛选由 agent 评估用途、参数化程度、边界、现有替代方案和测试覆盖。
程序核对测试收据与源码哈希，不接受模型凭空声称测试通过。两个不同场景只是最低门槛，
不自动证明全部分支覆盖、泛化成功率或模型质量；作者仍需测试有意义的控制路径。

工具：`humanize_save_flow` 命名候选；`humanize_library(include_candidates=true)` 查看候选；
`humanize_validate_flow` 生成测试收据；`humanize_curate_flow` 用 promote/reject/needs_evidence
记录理由、use_when、avoid_when 和 validation_id；`humanize_reuse_flow` 复用。
候选试用/导出必须明确 `allow_candidate=true`，被拒绝的流程不能借此绕过筛选。
任务输入 `flow_params` 不复制进配方，复用时重新提供；运行日志与任务文本不进入源码包。

## 进度由 flow 内的 agent 负责

独立 observer 使用单独的只读会话、禁用在线搜索，异步消费结构化阶段/角色活动事实，
生成简短摘要与下一步。它不指挥执行者，不参与验收，也不占用执行代理上下文。
队列只保留最新事件，每次播报最多 30 秒、800 输出 token，每次运行最多 24 次；
全部消耗计入总预算。失败或超时不会拖住任务结束。

`humanize_dashboard(job_id=...)` 返回本地实时看板。看板显示实际 flow 名称、静态结构标签、
各角色模型、同时活动的会话、最近活动、消耗与剩余时间。通用 flow 使用通用布局，
不再把所有任务显示成固定的 planner/actor/reviewer 图。
看板每秒读取程序事实和 observer 摘要，主执行代理不维护网页或轮询日志。
可在后台播报延迟时仍看到实际活动。看板与只读 API 绑定 loopback 和随机访问令牌。

hmz 0.2.1 / Codex 0.163 的多角色 SQLite 初始化竞争通过串行启动握手规避，模型回合仍并发。
内置单文件导出携带此窄适配；自定义原始 flow 导出不携带管理器的额外验收/observer，
在插件中运行时由包装器添加。

## 生命周期、取消与恢复

工具包括 `humanize_run/status/list/wait/events/steer/cancel/resume`。
每个工作目录只允许一个受管任务；独立监督进程持续持有文件锁，关闭聊天不丢弃任务。
预算覆盖导入和执行。预算/取消先给协作式清理机会，再清理已跟踪的后代进程，
包括另建 session 的 Codex 服务，确认不再运行后释放锁。
这是一种生命周期约束，不是针对恶意代码的 OS 沙箱。

| 状态 | 含义 |
| --- | --- |
| starting / running | 尚未完成 |
| complete | 独立验收完成并附证据 |
| blocked | 缺少必要输入或授权 |
| needs_work | 自定义 flow 已返回，独立验收发现未完成项 |
| round_limit / budget_exceeded | 达到边界，任务未完成 |
| cancelled | 取消已处理，任务结束 |
| failed / lost | 失败或心跳丢失，任务未完成 |

纠偏与取消先返回 queued，查 `control_receipt` 或终态确认处理结果。
通用 flow 纠偏可传目标 role；未指定角色的指导只保存供 flow 读取，不声称已送达下一回合。
内置模板会在后续回合读取指导。DSH 不支持中途插入时沿用后续回合机制。
恢复沿用原代码快照、目标与 journal，使用新预算；只允许声明 `resumable=True` 的自定义 flow，
防止无恢复能力的程序重复副作用。不自动恢复用户取消的任务。

## Flowverse 导出与存储

`humanize_export_flow` 导出版本化源码，`humanize_index_flow` 生成固定完整 Git SHA 的索引。
采用[上游索引格式](https://docs.humanfia.ai/humanize/weaver/flowverses)：源码与索引分开。
源码为 `bundles/<name>/<version>/<name>/`，索引为 `flows/<name>/<version>/flow.yaml`。
可使用自己的 [Flowverse fork](https://github.com/zgdllt/flowverse) 承载索引，无需沿用现有目录设计。
导出/索引不自动提交或推送；发布前检查源码与描述，并实际安装固定提交进行验证。

数据目录优先 `HUMANIZE_CODEX_DATA`、`PLUGIN_DATA` / `CLAUDE_PLUGIN_DATA`，否则
`~/.local/share/humanfia-humanize-codex`。runs/ 为私有任务与事件，library/ 为流程配方，
validations/ 为私有脚本案例和收据。分发包不包含运行数据、凭据或虚拟环境。
权限隔离沿用 Humanize 与后端；已有发布、发送、付费、硬件和范围边界继续有效。

## 开发与验证

```sh
uv sync --frozen --python 3.14
uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv build
python3 scripts/package.py
```

常规测试不调用在线模型，覆盖真实 fake engine、并行重叠、MCP、筛选/精确哈希收据、
独立验收/observer、阻塞代码取消、脱离进程组的后代清理，以及真实 Git Flowverse 安装。
[验证记录](VALIDATION.md) 区分模拟控制路径与真实模型烟雾测试。

上游：[humanfia/humanize](https://github.com/humanfia/humanize)，Apache-2.0。
运行固定 PyPI `hmz==0.2.1`；API 调研参考上游提交
`ac732f1e9fc3ea11dc2eb660f934ec7da73ca5f0`，不将两者混同。
插件格式参考 [Codex 文档](https://developers.openai.com/plugins/build/plugins)。
