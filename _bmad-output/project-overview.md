# 项目概览

文档状态：DRAFT / GDS full_rescan exhaustive overview
语言：zh-CN
工作流：`gds-document-project`
生成时间：2026-07-04
迁移阶段：BMAD 扫描输出，供 brownfield PRD / 后续 story 使用；长期规范入口仍是 [`docs/project-overview.md`](../docs/project-overview.md)。

## BMAD Provenance

- 用户触发：`gds-document-project`
- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Customization resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Config：`_bmad/gds/config.yaml`
- Workflow instructions：
  `.agents/skills/gds-document-project/instructions.md`,
  `.agents/skills/gds-document-project/workflows/full-scan-instructions.md`
- 支撑文件：
  `.agents/skills/gds-document-project/checklist.md`,
  `.agents/skills/gds-document-project/documentation-requirements.csv`
- 模式：`full_rescan`
- 扫描深度：`exhaustive`
- 用户额外关注：`none`

## 摘要

RPG Engine 是 local-first AI GM 游戏引擎内核，Python 包名为 `aigm-kernel`。它围绕
Campaign Package、Save Package、`GMRuntime`、CLI、MCP adapter、platform sidecar、
AI intent chain、SQLite 状态和验证/提交链组织，用本地可审计状态机运行文字 RPG / AI GM
回合流程。

本仓库当前更接近 Python backend / CLI / library 型内核，而不是 Unity、Godot、Unreal
或图形客户端项目。架构重心不是渲染，而是事实权威、玩家确认、隐藏信息、上下文构建、
包格式、入口权限和可审计状态提交。

核心边界：

```text
AI proposes. Kernel verifies. Player confirms. Engine commits.
```

## 项目分类

| 项 | 结论 |
| --- | --- |
| Repository type | Monolith |
| Parts count | 1 |
| Primary language | Python |
| Project type | Backend/kernel with CLI, library, game, and data traits |
| Package | `aigm-kernel` |
| Runtime authority | Save Package SQLite + events + projections |
| Content authority | Campaign Package + packaged schemas + content validation |
| Public surfaces | CLI, Python runtime API, MCP tools, platform sidecar |
| Deployment surface | GitHub Actions CI; no Docker/Kubernetes/cloud deployment config found |

用户已确认这个 single-part classification 可用，因此 workflow 跳过 multi-part integration
architecture。

## V1 产品边界

V1 是收敛式本地内核。必须维护的主线能力是：

- AIGM Kernel 核心库。
- Campaign Package 规范、校验器、作者工具和 smoke tests。
- Save Package 初始化、查看、校验、导入导出、归档、补丁和安全维护入口。
- CLI 参考实现。
- MCP adapter 薄适配层。
- 通用 AI 客户端 prompt artifacts。
- 小型官方示例 campaign。
- 对旧纯文档系统整理后继续游玩的承载能力；允许人工或 AI 辅助迁移，不承诺无监督一键完美迁移。

V1 非目标：

- Web 后端、HTTP API、多人在线、账号、云同步、市场。
- 强制依赖 LLM 的核心运行路径。
- 独立聊天 UI 或内置 AI 剧本生成器。
- 动态插件系统、插件市场、作者自定义代码执行、脚本化规则引擎或插件 SDK。
- 模型网关、agent 平台、长期任务系统。
- 完整电子游戏式战斗、制作、经营、恋爱、政治或国家模拟数值系统。

## 技术栈

| 类别 | 技术 | 当前证据 |
| --- | --- | --- |
| Language | Python `>=3.11` | `pyproject.toml`, CI matrix |
| Package | setuptools package `aigm-kernel` `0.2.0` | `pyproject.toml` |
| Console scripts | `aigm`, `rpg_engine` | `pyproject.toml` |
| Runtime deps | `PyYAML>=6.0`, `jsonschema>=4.20` | `pyproject.toml` |
| Optional integration | `mcp>=1.28,<2` | `pyproject.toml`, `rpg_engine/mcp_adapter.py` |
| Persistence | SQLite + SQL migrations | `rpg_engine/db.py`, `rpg_engine/resources/migrations/` |
| Dev tools | pytest, coverage, ruff, build, twine | `pyproject.toml`, `.github/workflows/ci.yml` |
| CI | GitHub Actions Python 3.11 / 3.12 | `.github/workflows/ci.yml` |

## 主要能力

- Campaign Package 载入、校验、复制示例、outline、author doctor、split 和 smoke test。
- Save Package 创建、检查、校验、导入导出、归档、补丁、投影和安全维护。
- `GMRuntime` 回合门面：start turn、query、act、preview、validate delta、commit、health。
- 玩家安全回合链：`SaveManager.player_turn()` 创建 pending `TurnProposal`；
  `SaveManager.player_confirm()` 才进入正式提交。
- 行动系统：探索、旅行、战斗、休息、采集、制作、社交、随机表。
- AI 意图链：规则候选、外部候选、AI 候选、internal review、arbiter、binder、trace。
- Platform chain：sidecar 门禁、异步 prewarm、platform session identity、advisory cache。
- 上下文链：可见事实收集、预算、语义建议、渲染和泄漏审计。
- 写入链：preview/proposal、validation pipeline、unit of work、write guard、commit service。
- MCP adapter：profile-gated 工具面，默认 player-safe，受信 profile 才暴露低层 runtime 工具。

## 不可破坏边界

- AI 输出永远是低信任候选，不是事实、最终 intent 或写入授权。
- Internal AI review 不能 preview、validate、confirm 或 commit。
- `SaveManager.player_turn()` 不能提交游戏事实。
- `SaveManager.player_confirm()` 是普通玩家路径的提交门。
- Platform prewarm 只能产生 advisory / `message_only` preflight。
- Hidden / GM-only 内容不能泄露到玩家视图、FTS、scene output 或普通 query。
- CLI、MCP、platform sidecar 必须调用 kernel service，不能复制业务逻辑。
- Campaign Package 与 Save Package 职责分离，不能把剧情源数据和存档事实混在一起。

## 文档状态

当前长期入口是 [`docs/index.md`](../docs/index.md)。Round 4C 后，旧 `docs/architecture/`、
`docs/specs/` 和 `docs/guides/` 正文已归档到
[`docs/archive/pre-bmad-docs-2026-07-03/`](../docs/archive/pre-bmad-docs-2026-07-03/)，旧路径
只保留 compatibility stubs。

本轮复核结论：

- Canonical docs 已经存在并覆盖主要当前边界。
- 旧 `_bmad-output` 中 Round 1 素材仍有参考价值，但状态头和 provenance 不足以证明本轮严格执行。
- 本轮新/刷新输出已加入 `gds-document-project` provenance，作为后续 brownfield PRD 和 story 的扫描基线。
