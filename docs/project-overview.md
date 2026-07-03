# 项目概览

文档状态：**CURRENT：BMAD canonical overview**

## 摘要

RPG Engine 是一个 local-first AI GM 游戏引擎内核，包名为 `aigm-kernel`。它围绕
Campaign Package、Save Package、`GMRuntime`、CLI、MCP adapter 和平台 sidecar
组织，用本地可审计状态机运行文字 RPG / AI GM 回合流程。

当前仓库是 Python backend / CLI / library 型项目，不是 Unity、Godot 或图形客户端
项目。它的核心目标是让 AI 负责叙事、建议和候选意图，让引擎负责事实校验、状态提交、
隐藏信息保护、上下文构建和入口权限。

## 项目定位

- 领域：AI GM、文字 RPG、本地优先游戏引擎内核。
- 类型：Python backend + CLI + library + MCP integration。
- 主要入口：命令行、Python API、MCP 工具、平台 sidecar。
- 状态权威：Save Package 内 SQLite 数据库、事件流和投影材料。
- 内容权威：Campaign Package、打包 schema、内容注册与验证。
- AI 边界：AI 可以生成候选和叙事；最终 preview、validation、confirm、commit 必须在引擎内。

## V1 范围与非目标

V1 是收敛式本地内核，不是平台化扩张。必须交付的主线能力是：

- AIGM Kernel 核心库。
- Campaign Package 规范、校验器和作者 smoke tests。
- Save Package 规范、初始化、查看、校验、归档和安全维护入口。
- CLI 参考实现。
- MCP adapter 薄适配层。
- 通用 AI 客户端 prompt。
- 小型官方示例剧本。
- 对旧纯文档系统整理后继续游玩的承载能力；允许人工或 AI 辅助迁移，不承诺无监督一键完美迁移。

V1 明确不做：

- Web 后端、HTTP API、多人在线、账号、云同步、市场。
- 强制依赖 LLM 的核心运行路径。
- 独立聊天 UI 或内置 AI 剧本生成器。
- 动态插件系统、插件市场、作者自定义代码执行、脚本化规则引擎或插件 SDK。
- 模型网关、agent 平台、长期任务系统。
- 10k / 100k 规模目标。
- 完整电子游戏式战斗、制作、经营、恋爱、政治或国家模拟数值系统。

产品边界：

- 核心默认不依赖 LLM；AI helpers 只能是 advisory，不能成为事实源或写库入口。
- CLI 和 MCP 必须是薄入口，不能形成第二套业务编排。
- MCP 是通用 adapter，不是单一客户端私有插件。
- Campaign 作者只编辑 Markdown、YAML、JSON、prompt 和 template；不需要理解 Python、SQLite、MCP、delta 或 projection。
- 题材差异通过 Campaign Package 内容、capability、规则摘要、随机表和结构化状态表达。

## 技术栈

- Python `>=3.11`
- 包名：`aigm-kernel`
- 命令入口：`aigm`、`rpg_engine`
- 核心依赖：`PyYAML`、`jsonschema`
- 可选 MCP 依赖：`mcp`
- 开发工具：`pytest`、`coverage`、`ruff`、`build`、`twine`
- CI：GitHub Actions，Python 3.11 / 3.12 测试矩阵

参考：

- [`../pyproject.toml`](../pyproject.toml)
- [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml)
- [`../README.md`](../README.md)

## 主要能力

- Campaign Package 载入、校验、复制示例和 smoke test。
- Save Package 创建、校验、归档、修补、投影和安全维护。
- `GMRuntime` 回合门面：开始回合、查询、动作预览、delta 校验、提交回合、健康检查。
- 玩家安全回合链：`SaveManager.player_turn()` 创建 pending `TurnProposal`；
  `SaveManager.player_confirm()` 才进入正式提交。
- 行动系统：探索、旅行、战斗、休息、采集、制作、社交、随机表。核心预览合约是
  `ActionResolverSpec` 和 `GMRuntime.preview_action()`。
- AI 意图链：外层 `intent_router.py` 管规则/兼容候选，`ai_intent/router.py` 编排
  AI 候选、内部复核、仲裁、绑定和 trace。
- 平台链：入口门禁、消息冲突处理、异步预热、workspace 级平台会话绑定、
  advisory intent preflight cache。
- 上下文链：可见事实收集、预算、语义建议、上下文渲染和泄漏审计。
- 写入链：preview/proposal、validation pipeline、unit of work、write guard、commit service。
- MCP adapter：按 profile gate 暴露工具面。默认 player-safe，低层 runtime 工具只给
  developer、trusted、maintenance 或 admin profile。

## 不可破坏边界

- AI 输出永远是低信任候选，不是事实、最终意图或写入授权。
- internal AI review 可以帮助分类和复核，但不能 preview、validate、confirm 或 commit。
- `SaveManager.player_turn()` 不能提交游戏事实。
- `SaveManager.player_confirm()` 是普通玩家路径的提交门。
- platform prewarm 只能产生 advisory / `message_only` preflight，不能驱动回合。
- hidden / GM-only 内容不能泄露到玩家视图、FTS、scene output 或普通 query。
- CLI、MCP、platform sidecar 必须调用 kernel service，不能复制业务逻辑。
- Campaign Package 与 Save Package 职责分离，不能把剧情源数据和存档事实混在一起。

## 仓库公开边界

可以提交源码、测试、schema、示例 campaign、BMAD 文档和当前剧情包本体。不要提交真实
玩家存档、平台会话、运行缓存、密钥、私有配置、preflight cache 或玩家 SQLite。

运行数据默认排除：

- `.aigm/`
- `saves/`
- Save Package
- 玩家 SQLite
- platform session 绑定
- preflight cache 内容
- 当前工作区中的 save-like 运行目录，例如 `run1/`

## 当前文档状态

BMAD / Game Dev Studio 已作为强流程层安装在 [`../_bmad/`](../_bmad/)。Round 1 Deep
Scan 产物位于 [`../_bmad-output/`](../_bmad-output/)。本文件是 Round 2 迁入
`docs/` 的 canonical 概览，后续领域文档会继续从旧 `docs/` 中审查和合并。
