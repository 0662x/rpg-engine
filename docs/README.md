# RPG Engine Documentation

文档状态：**CURRENT：当前文档入口与维护规则**

这个目录是 RPG Engine / AIGM Kernel 的唯一长期文档入口。根目录只保留简短 `README.md`；规范、指南、prompt、治理说明和架构说明都放在这里。

## Start Here

| 目标 | 文档 |
|---|---|
| 理解产品边界 | [`specs/kernel-requirements.md`](specs/kernel-requirements.md) |
| 开始开发或让 AI 改代码 | [`../AGENTS.md`](../AGENTS.md)、[`project-context.md`](project-context.md)、[`development-workflow.md`](development-workflow.md)、[`architecture/module-map.md`](architecture/module-map.md) |
| 编写 Campaign Package | [`specs/campaign-package.md`](specs/campaign-package.md)、[`guides/author-guide.md`](guides/author-guide.md) |
| 管理 Save Package | [`specs/save-package.md`](specs/save-package.md) |
| 设计玩家入口和多存档体验 | [`specs/player-entry-save-manager.md`](specs/player-entry-save-manager.md) |
| 理解正常游戏意图识别链路 | [`specs/standard-intent-chain.md`](specs/standard-intent-chain.md)、[`specs/ai-intent-prewarm.md`](specs/ai-intent-prewarm.md) |
| 使用 CLI | [`specs/cli.md`](specs/cli.md) |
| 接入 MCP / AI 客户端 | [`specs/mcp-adapter.md`](specs/mcp-adapter.md)、[`prompts/ai-client-prompt.md`](prompts/ai-client-prompt.md) |
| 让外部 AI 辅助写剧本 | [`prompts/author-ai-prompt.md`](prompts/author-ai-prompt.md) |
| 维护候选素材、内容生成和 proposal 边界 | [`governance/content-generation.md`](governance/content-generation.md) |
| 理解当前架构 | [`architecture/game-engine.md`](architecture/game-engine.md)、[`architecture/review.md`](architecture/review.md)、[`architecture/turn-flow-architecture.md`](architecture/turn-flow-architecture.md)、[`architecture/external-projects-review.md`](architecture/external-projects-review.md) |

## Current Docs

### Development

- [`../AGENTS.md`](../AGENTS.md)：AI/human 开发入口、不可破坏边界和验证规则。
- [`project-context.md`](project-context.md)：BMAD/AI agent 项目上下文，给未来开发规划加载。
- [`development-workflow.md`](development-workflow.md)：变更分类、阅读路径、测试选择和收尾证据。
- [`architecture/module-map.md`](architecture/module-map.md)：源码模块边界和编辑启发。

### Specs

- [`specs/kernel-requirements.md`](specs/kernel-requirements.md)：V1 产品边界和交付范围锚点。
- [`specs/campaign-package.md`](specs/campaign-package.md)：Campaign Package 目录、字段、content、palette、random table 和 smoke tests。
- [`specs/save-package.md`](specs/save-package.md)：Save Package、`.aigmsave`、inspect/validate、safe patch。
- [`specs/player-entry-save-manager.md`](specs/player-entry-save-manager.md)：首次开始游戏、继续游戏、多存档切换、Save Manager、onboarding 和玩家入口 MCP/CLI 设计。
- [`specs/standard-intent-chain.md`](specs/standard-intent-chain.md)：正常游戏唯一标准意图识别链路，external AI 低信任候选、internal AI 可见外部候选独立复核、arbiter/preview/validation/confirm/commit 边界。
- [`specs/ai-intent-prewarm.md`](specs/ai-intent-prewarm.md)：AI intent、internal review、advisory preflight、platform prewarm 的长期 authority、模块责任和维护护栏。
- [`specs/cli.md`](specs/cli.md)：普通 CLI 主路径和 legacy/admin 边界。
- [`specs/mcp-adapter.md`](specs/mcp-adapter.md)：MCP 工具白名单、参数、路径边界和推荐 AI 流程。

### Guides

- [`guides/author-guide.md`](guides/author-guide.md)：普通作者如何创建和维护剧本。
- [`guides/author-maintenance.md`](guides/author-maintenance.md)：已发布剧本的安全维护原则。
- [`guides/author-examples.md`](guides/author-examples.md)：几类剧本结构示例。

### Prompts

- [`prompts/ai-client-prompt.md`](prompts/ai-client-prompt.md)：给 AI GM 客户端使用的通用 prompt。
- [`prompts/author-ai-prompt.md`](prompts/author-ai-prompt.md)：给外部 AI 用于辅助创作 Campaign Package 的 prompt。

### Governance

- [`governance/content-generation.md`](governance/content-generation.md)：palette、random table、content delta、proposal queue 和高影响内容审稿边界。

### Architecture

- [`architecture/game-engine.md`](architecture/game-engine.md)：当前实现分层和运行原则。
- [`architecture/module-map.md`](architecture/module-map.md)：源码模块责任图和编辑入口。
- [`architecture/review.md`](architecture/review.md)：当前架构风险、legacy/admin 边界和后续整理顺序。
- [`architecture/turn-flow-architecture.md`](architecture/turn-flow-architecture.md)：从玩家输入到意图、预演、delta、校验、保存、投影和输出的全链路设计说明、阶段落地记录和 Phase 7.1 hardening 落地记录。
- [`architecture/external-projects-review.md`](architecture/external-projects-review.md)：对照 Ink、Ren'Py、Foundry VTT、MCP、LangGraph、Temporal 等外部项目经验的 Phase 3 前专家评审清单。

## Archive

- [`archive/`](archive/)：唯一归档入口。
- [`archive/2026-06-30/`](archive/2026-06-30/)：2026-06-30 的建议报告、UX 设计稿、Author Kit 设计/计划、bug report、UX simulation report、历史设计和生成输出。它们是历史记录，不是当前入口。

## Maintenance Rules

1. 新增长期文档必须放入 `docs/specs`、`docs/guides`、`docs/prompts`、`docs/governance` 或 `docs/architecture`。
2. 一次性报告、审计、设计草稿和测试记录放入 `docs/archive/<date>/`，不要放在根目录。
3. 修改代码能力时，同步更新相关 spec/guide/prompt；不要只更新历史报告。
4. `docs/README.md` 是文档目录索引；新增长期文档时必须在这里登记。
5. 历史报告中的旧链接可以保持原样，避免改写历史语境；当前文档必须使用新的相对路径。
6. 面向 AI/开发流程的长期规范优先更新 `AGENTS.md`、`project-context.md`、`development-workflow.md` 或 `architecture/module-map.md`，不要散落在临时报告里。
