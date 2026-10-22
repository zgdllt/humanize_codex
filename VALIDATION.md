# 验证记录

日期：2026-10-22。版本：0.2.0。

## 常规验证

测试使用真实 Humanize fake engine 和真实 MCP 客户端/服务端，常规运行不调用在线模型。
覆盖动态分支、独立审查与保留执行会话、阻塞/轮数边界、journal 恢复、工作区文件锁、
取消/纠偏收据、Codex 二进制选择、Codex/DSH 通用角色及独立状态 observer。

保留测试核对证据门槛、代码快照、去重、不可覆盖的名字/版本、私有任务不进入配方。
Flowverse 测试创建本地 Git 源码与索引仓库，通过真实 Hmz().verses 安装固定提交，
再从安装位置执行具名 flow。看板测试拒绝错误访问令牌、Host、Origin 和写请求。

运行命令见 README；GitHub Actions 在 Linux/macOS 执行 lint、测试与构建。
Agent Plugins 1.0 的 plugin.json/mcp.json 依官方 JSON Schema 校验。

## 已观察的真实模型链路

初版插件用 Codex CLI 0.163.0 和 codex/gpt-6.1-sol:low，在临时工作区读取 fixture，
由独立审查者核对文件，返回 complete，约 41 秒，fixture 内容未改变。
旧 Homebrew CLI 的模型拒绝不能推广为账号或新版 TUI 不支持该模型。

0.2.0 用同一 Codex 版本及 gpt-6.1-sol:low 实测：执行、独立审查、并行 observer
均运行，任务返回 complete，约 41 秒、413 输出 token；fixture SHA-256 未改变。
observer 的独立中文阶段摘要在实际浏览器看板显示；通过审查的 flow 自动进入本地库。
测试暴露了 hmz 0.2.1 多角色同时初始化 Codex SQLite 的竞争；修复只串行初始化握手，
模型回合仍并发。该窄适配包含在导出的单文件 flow 中。
DSH SDK 0.1.5rc1 已纳入锁定环境；真实 DSH 认证/模型运行需配置使用者自己的账号。

## 证据边界

Fake engine 验证流程控制，不证明具体模型能正确完成真实开发任务。
烟雾测试只验证被测链路，不证明复杂任务成功率、成本优势或长期可靠性。
尚未验证 Windows；支持范围为 macOS/Linux。
运行日志、任务文本、凭据和机器路径不进入公开仓库或分发包。
