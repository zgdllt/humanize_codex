# 验证记录

日期：2026-11-03。当前版本：0.5.0。

## v0.5.0 官方 flow 与可选预算

已移除插件提供的 dynamic/review 算法、mode/max_rounds 入口和强制有限总预算。
新运行默认引用官方 rlar，接受其他 SDK flow ref 或本地自定义入口，不自动添加 planner/verifier。
预算省略/null 使用 SDK 的无限预算，显式限额没有插件自定上限；复用、恢复同样接受新可选预算。
complete 表示所选 flow 正常返回，任务验收需要结合实际结果；不再要求返回插件专用结果结构。

新增/调整验证使用真实 SDK 和 fake agents，无在线模型调用：

- 官方 rlar 在 102 轮后由上游审查条件结束，跨过原插件 100 轮边界，actor 会话复用、reviewer 刷新。
- 原生薄桥保留官方 review-notes 技能，普通与只读两种权限路径均可执行。
- 无限预算 JSON 往返、超过旧时长/token/费用上限的显式值，以及 SDK 的零限额语义。
- 无限预算任务可取消；显式时间预算仍能终止阻塞任务，两者只清理本任务 Host，保留其他 Host。
- 运行/复用不再自动附加 verifier；旧请求和已保留源码仍沿原调用结构恢复、复用与导出。

旧模板源码仅在 tests/fixtures 中用于兼容回归，不提供给新运行。
本机 macOS / hmz 0.2.2 的完整测试 118 项通过，ruff/格式检查、wheel/sdist 和 marketplace 打包通过。
只读复审另验证了旧 envelope 的跨目录 journal 状态延续和本地 Git VCS 包的技能桥接。
只读权限收窄保留原 NONE 权限，SDK 自动角色保持原声明；对应回归已通过。
该计数包含替换后的官方 flow 测试与旧数据兼容测试；不代表在线模型任务已完成。
下方版本记录为历史行为，其中内置模板/强制预算/自动 verifier 的描述已被本节替代。

## v0.4.1 依赖更新（历史记录）

开发基线从 hmz[dsh] 0.2.1 升级到 PyPI 最新稳定版 0.2.2。
实际分发启动器通过隔离的 uv tool 环境加载 hmz 0.2.2、DSH SDK 0.1.5rc1，
doctor 返回插件 0.4.1 和 Humanize 0.2.2。最新版本约束独立于项目 uv.lock，
不改动全局 hmz 或正在执行的 flow 的环境。

本机 macOS 在 hmz 0.2.2 上完整测试 120 项通过，包含实际分发入口的 MCP 握手、
原生 Host、恢复/取消和真实 tmux TUI；ruff 检查、格式检查、wheel/sdist 和 marketplace 打包通过。
MCP 首次检查遇到一次 PyPI TLS EOF，单项重跑及随后完整测试均通过。

latest CI 在 Linux/macOS 强制安装 PyPI 当时发布的精确版本，记录并核对实际版本，
执行完整测试，并安装 tmux 运行原生 TUI 集成路径。
另保留使用 uv.lock 的常规 CI，便于区分上游变化与本仓库回归。
本次没有新增在线模型调用；下方 v0.4.0 在线烟雾测试的限制仍保留。

## v0.4.0 原生界面与运行链路（历史记录）

依赖固定 hmz[dsh]==0.2.1。本机 macOS 已安装 Humanize app 0.2.1 和 tmux。
插件移除独立浏览器看板、humanize_dashboard 工具和用于播报的 observer。

真实、无在线模型的原生集成测试覆盖：

- 用官方 daemon Host / Link 启动 flow，另一个 TUI 类前端收到相同 started/ended。
- 极快 flow 仍保存 Python 返回结果、epic 和结束用量；原生 done 不冒充验收 complete。
- native entry 在同一根 journal 恢复，换 artifacts 和 guidance 后状态计数从 1 延续到 2。
- 重复取消保持幂等，原生停止映射为插件 cancelled。
- 真正创建 tmux 的 tui / flow 窗口，官方 TUI 连接任务的独占 Host。
- tmux 既有 server 场景下也继承本次运行环境，环境私有文件权限为 0600。
- 重开界面不重新执行任务；同步阻塞超出预算后仅清理本任务 Host，其他默认 Host 仍可响应。

上述 6 个集成测试已通过独立只读复审者复跑；另有 2 项环境识别回归，
区分真正桌面 app 与终端中运行的 bundled Codex CLI。原生集成/环境测试共 8 项通过。
没有 tmux 的 CI 主机只跳过 tmux 实测，
仍运行共享 Host、journal、取消与预算归属测试。
上游 hmz 0.2.1 通过 fork 创建 Host，Python 3.14 在多线程测试进程中会输出相应弃用警告；
本次未改写上游 daemon 实现。

## 现有行为回归

本机完整测试 118 项通过。继续检查顺序/循环/分支/并行 flow、独立验收、候选/精选门槛、源码哈希与去重、旧快照声明角色、
工作目录锁、预算和清理终态、控制收据、真实 Git Flowverse 安装，以及 MCP 协议/打包启动。
新模板只有 planner、actor、reviewer；通用管理器只添加 humanize_verifier。
旧源码保持原样，显式声明的旧 observer 属于旧流程本身。

## 桌面模型烟雾测试

Humanize app 0.2.1 已实际启动。通过独占原生 Host 启动 branch_flow，
Codex CLI 0.166.0 / gpt-6.1-sol:low 的首个只读回合建立了真实会话，原生事件与转录可读取。
该回合在 120 秒内没有返回输出，终态为 budget_exceeded，输出 token 为 0。
未观察到明确错误消息；无法据此确认在线模型任务能完整结束，也不将其报告为成功。
预算和清理路径正常执行，临时 fixture SHA-256 未改变；未修改用户项目。

## 可见性与证据边界

桌面启动器会打开实际 Humanize app。该版本没有通用 workspace 深链启动参数，
用户从原生侧栏选择返回的 workspace/epic；不声称已自动聚焦指定运行。
SSH/终端模式返回实际 tmux session、attach_command 和 switch_command。
原生 Host 已结束时，重开 TUI 打开官方 /epics 历史菜单，不新建空 job slot 或重跑任务。

原生界面展示 SDK 发出的实际流程、会话和工具事件。模型输出不被当成授权。
测试验证被测链路，不代表复杂任务成功率、全部控制路径覆盖或性能优势。
DSH 配置/分配有回归测试；在线 DSH 仍需使用者自己的认证。
运行日志、环境值、凭据、任务文本和本机实际路径不进入公开仓库或分发包。
