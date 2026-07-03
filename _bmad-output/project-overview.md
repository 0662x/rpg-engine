# 项目概览

文档状态：DRAFT / Round 1 Deep Scan
语言：zh-CN
迁移阶段：BMAD 扫描素材，未进入 canonical docs

## 摘要

`aigm-kernel` 是一个 local-first AI GM 游戏引擎内核。它围绕 Campaign Package、Save Package、GMRuntime、CLI 和 MCP adapter 组织，目标是在本地可审计状态机中运行文字 RPG/AI GM 回合流程。

当前仓库包含约 149 个 Python 源文件、50 个 pytest 测试文件、8 个 SQLite 迁移和 13 个打包 JSON Schema。旧文档约 45 篇，需要迁移和裁剪。

## 项目定位

- 领域：AI GM / 文字 RPG / 本地优先游戏引擎内核。
- 类型：Python backend + CLI + library + MCP integration。
- 主要运行方式：命令行、Python API、MCP 工具入口。
- 状态权威来源：Save Package 内 SQLite 数据库与事件流。
- 内容权威来源：Campaign Package、资源 schema、内容注册与验证。
- AI 边界：AI 可以识别意图、生成候选、给出叙事或提案；引擎负责校验、预览、提交和隐藏信息边界。

## 技术栈

- Python：`>=3.11`
- 包名：`aigm-kernel`
- 入口命令：`aigm`、`rpg_engine`
- 核心依赖：`PyYAML`、`jsonschema`
- 可选 MCP：`mcp`
- 开发工具：`pytest`、`coverage`、`ruff`、`build`、`twine`
- CI：GitHub Actions，Python 3.11/3.12 测试矩阵

参考：

- [pyproject.toml](../pyproject.toml)
- [CI workflow](../.github/workflows/ci.yml)
- [README](../README.md)

## 主要能力

- Campaign Package 载入、校验与示例包。
- Save Package 创建、校验、归档、修补；平台链维护 workspace 级会话绑定。
- GMRuntime 回合门面：开始回合、查询、预览动作、校验 delta、提交回合、健康检查。
- 玩家安全回合链：`SaveManager.player_turn` 创建 pending `TurnProposal`，`SaveManager.player_confirm` 才进入正式提交。
- 行动系统：探索、旅行、战斗、休息、采集、制作、社交、随机表，核心合约是 `ActionResolverSpec` 和 `GMRuntime.preview_action`。
- AI 意图链：外层 `intent_router.py` 管规则/兼容候选，`ai_intent/router.py` 编排 AI 候选、内部复核、仲裁、绑定和 trace。
- 平台链：入口门禁、消息冲突处理、异步预热、workspace 级平台会话绑定、advisory intent preflight cache。
- 上下文链：可见事实收集、预算、语义建议、上下文渲染和审计。
- 写入链：preview/proposal、validation pipeline、unit of work、write guard、commit service。
- MCP adapter：按 profile gate 暴露工具面，默认 player-safe，低层 runtime 工具只给 developer/trusted/maintenance/admin profile。

## 关键约束

- 不允许 AI 直接绕过引擎写入状态。
- 隐藏内容必须通过 visibility/context 规则保护。
- 所有状态变更应可预览、可校验、可审计、可回滚或可重建。
- 平台侧预热只能加速意图准备，不能替代最终门禁和提交校验。
- 平台绑定位于 workspace/runtime 级 `.aigm/game-session-bindings.json`，不属于单个 Save Package。
- `.aigm/`、`saves/`、Save Package、玩家 SQLite、平台 session 和 preflight cache 内容都属于运行数据，公开仓库默认不提交。
- 文档迁移必须以当前代码事实为准，旧 docs 只能作为素材源。

## 当前文档状态

已安装 BMAD / Game Dev Studio 相关护栏，并新增 BMAD 文档迁移计划。本轮 Deep Scan 的产物位于 `_bmad-output/`，后续会将成熟内容迁入 `docs/` 作为新的 canonical 文档。
