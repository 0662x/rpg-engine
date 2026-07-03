# Round 4 旧文档归档映射表

文档状态：DRAFT / Round 4 Archive Mapping
语言：zh-CN
日期：2026-07-04

## 目标

本文件是 BMAD Round 4 的第一步产物：扫描旧 `docs/architecture/`、`docs/specs/`、
`docs/guides/`、`docs/prompts/`，判断每个旧文件在归档前应如何处理。

本步骤只做映射，不移动、不删除、不改 Python 行为。

## 扫描范围

旧目录当前共有 28 个 Markdown 文件：

| 目录 | 文件数 |
| --- | ---: |
| `docs/architecture/` | 15 |
| `docs/specs/` | 8 |
| `docs/guides/` | 3 |
| `docs/prompts/` | 2 |

Round 3 已建立当前 canonical 领域文档：

- [`docs/ai-intent-chain.md`](../docs/ai-intent-chain.md)
- [`docs/save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md)
- [`docs/data-models.md`](../docs/data-models.md)
- [`docs/cli-contracts.md`](../docs/cli-contracts.md)
- [`docs/mcp-contracts.md`](../docs/mcp-contracts.md)
- [`docs/architecture.md`](../docs/architecture.md)
- [`docs/component-inventory.md`](../docs/component-inventory.md)
- [`docs/source-tree-analysis.md`](../docs/source-tree-analysis.md)
- [`docs/development-guide.md`](../docs/development-guide.md)
- [`docs/testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md)
- [`docs/project-overview.md`](../docs/project-overview.md)

## 处理分类

| 分类 | 含义 |
| --- | --- |
| `stub+archive` | 当前权威内容已迁入 canonical docs；后续可移动原文到 archive，并在旧路径保留短 stub。 |
| `archive-evidence` | 历史报告、实施记录或本机基线；不再作为当前规范，后续可归档为证据。 |
| `extract-before-archive` | 仍有未完全迁入 canonical docs 的可用内容；先摘取或建立新 canonical 入口，再归档。 |
| `decision-needed` | 文件不是纯历史文档，可能是可复用 prompt/guide artifact；需要决定长期位置。 |

## 高层结论

可以高置信进入下一步 `stub+archive` 的主线规范：

- `docs/specs/standard-intent-chain.md`
- `docs/specs/ai-intent-prewarm.md`
- `docs/specs/campaign-package.md`
- `docs/specs/save-package.md`
- `docs/specs/cli.md`
- `docs/specs/mcp-adapter.md`
- `docs/specs/player-entry-save-manager.md`
- `docs/architecture/game-engine.md`
- `docs/architecture/module-map.md`
- `docs/architecture/review.md`
- `docs/architecture/phase-0-surface-inventory.md`

需要先摘取或决策，不建议第一批直接归档的文件：

- `docs/specs/kernel-requirements.md`：V1 产品边界锚点，已有大量内容迁入 canonical docs，但仍应核对是否需要在
  [`docs/project-overview.md`](../docs/project-overview.md) 或 [`docs/architecture.md`](../docs/architecture.md)
  保留更明确的 “V1 不做什么” 摘要。
- `docs/guides/author-guide.md`、`docs/guides/author-examples.md`、`docs/guides/author-maintenance.md`：
  作者可操作指南尚未形成 canonical authoring guide。
- `docs/prompts/ai-client-prompt.md`、`docs/prompts/author-ai-prompt.md`：这是可复用 prompt artifact，
  不是普通历史说明。需要决定是保留为 active prompt、迁入新模板位置，还是转成 canonical prompt contract。
- `docs/architecture/current-code-multi-expert-review.md`：大部分当前边界已迁入 canonical docs，但其中仍有
  发布成熟度、可靠性、安全和评估残余风险，可考虑摘到 BMAD backlog / quality gate 后再归档。

## 逐文件映射

| 旧文件 | 行数 | 引用数 | 建议 | Canonical 目标 | 备注 |
| --- | ---: | ---: | --- | --- | --- |
| [`docs/architecture/composite-plan-turn-adr.md`](../docs/architecture/composite-plan-turn-adr.md) | 79 | 1 | `stub+archive` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md) | Composite / multi-step 行动边界已在 intent 链中保留为需确认、不可直接 saveable action。 |
| [`docs/architecture/current-code-multi-expert-review.md`](../docs/architecture/current-code-multi-expert-review.md) | 1676 | 1 | `extract-before-archive` | [`testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md), BMAD backlog | 历史评审很长，已部分过时；仍可摘取未关闭的发布质量、安全、可靠性和评估风险。 |
| [`docs/architecture/external-projects-review.md`](../docs/architecture/external-projects-review.md) | 469 | 1 | `archive-evidence` | [`architecture.md`](../docs/architecture.md) | 外部项目经验是架构校准证据，不应继续当当前规范入口。 |
| [`docs/architecture/future-turn-coordinator-design.md`](../docs/architecture/future-turn-coordinator-design.md) | 504 | 9 | `stub+archive` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md), [`architecture.md`](../docs/architecture.md) | 明确是 future/proposed；canonical docs 已避免把 future coordinator 写成当前主路径。 |
| [`docs/architecture/game-engine.md`](../docs/architecture/game-engine.md) | 82 | 10 | `stub+archive` | [`project-overview.md`](../docs/project-overview.md), [`architecture.md`](../docs/architecture.md), [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md) | 当前实现契约已拆入 overview、architecture、package/data/CLI/MCP 文档。 |
| [`docs/architecture/intent-coordinator-refactor-plan.md`](../docs/architecture/intent-coordinator-refactor-plan.md) | 464 | 7 | `archive-evidence` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md) | Phases 1-4 已完成；作为实现计划证据归档。Phase 5 可选后续不应成为当前规范。 |
| [`docs/architecture/intent-coordinator-team-review.md`](../docs/architecture/intent-coordinator-team-review.md) | 608 | 3 | `archive-evidence` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md) | 六角色评审结论已沉淀到 intent canonical 边界。 |
| [`docs/architecture/intent-design-alignment-review.md`](../docs/architecture/intent-design-alignment-review.md) | 259 | 7 | `archive-evidence` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md) | 历史设计目标对照，当前权威应读 canonical intent 文档。 |
| [`docs/architecture/intent-refactor-implementation-log.md`](../docs/architecture/intent-refactor-implementation-log.md) | 1021 | 5 | `archive-evidence` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md), [`testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md) | 分轮实施日志作为证据归档；不再作为日常开发入口。 |
| [`docs/architecture/module-map.md`](../docs/architecture/module-map.md) | 128 | 3 | `stub+archive` | [`component-inventory.md`](../docs/component-inventory.md), [`source-tree-analysis.md`](../docs/source-tree-analysis.md) | 模块职责已迁入 component inventory / source tree。 |
| [`docs/architecture/p0-stop-loss-acceptance-2026-07-02.md`](../docs/architecture/p0-stop-loss-acceptance-2026-07-02.md) | 50 | 0 | `archive-evidence` | [`testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md) | 一次性 P0 验收记录；后续可直接归档，无需旧路径 stub。 |
| [`docs/architecture/phase-0-performance-baseline.md`](../docs/architecture/phase-0-performance-baseline.md) | 37 | 3 | `archive-evidence` | [`testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md) | 本机性能基线是历史证据，不应作为长期通用阈值。 |
| [`docs/architecture/phase-0-surface-inventory.md`](../docs/architecture/phase-0-surface-inventory.md) | 171 | 2 | `stub+archive` | [`cli-contracts.md`](../docs/cli-contracts.md), [`mcp-contracts.md`](../docs/mcp-contracts.md), [`ai-intent-chain.md`](../docs/ai-intent-chain.md) | 默认 player surface / low-level profile 边界已迁入 CLI/MCP/intent 文档。 |
| [`docs/architecture/review.md`](../docs/architecture/review.md) | 165 | 11 | `stub+archive` | [`architecture.md`](../docs/architecture.md), [`component-inventory.md`](../docs/component-inventory.md) | 架构评估入口已由 canonical architecture 替代。 |
| [`docs/architecture/turn-flow-architecture.md`](../docs/architecture/turn-flow-architecture.md) | 2087 | 7 | `archive-evidence` | [`architecture.md`](../docs/architecture.md), [`ai-intent-chain.md`](../docs/ai-intent-chain.md), [`data-models.md`](../docs/data-models.md) | 超长设计和阶段记录；当前主路径已收敛，剩余作为历史设计证据。 |
| [`docs/guides/author-examples.md`](../docs/guides/author-examples.md) | 71 | 0 | `extract-before-archive` | Future authoring guide / [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md) | 题材示例对作者仍有用，尚未迁入 canonical authoring 入口。 |
| [`docs/guides/author-guide.md`](../docs/guides/author-guide.md) | 171 | 0 | `extract-before-archive` | Future authoring guide / [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md) | 作者操作步骤、目录说明和 AI 辅助流程仍有用，需先整理。 |
| [`docs/guides/author-maintenance.md`](../docs/guides/author-maintenance.md) | 44 | 0 | `extract-before-archive` | Future authoring guide / [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md) | 作者维护 checklist 可并入 authoring canonical 文档。 |
| [`docs/prompts/ai-client-prompt.md`](../docs/prompts/ai-client-prompt.md) | 150 | 8 | `decision-needed` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md), [`mcp-contracts.md`](../docs/mcp-contracts.md), possible prompt artifact location | 可复用外部 AI prompt，不是普通历史文档；需要决定长期位置与版本策略。 |
| [`docs/prompts/author-ai-prompt.md`](../docs/prompts/author-ai-prompt.md) | 71 | 3 | `decision-needed` | Future authoring guide / possible prompt artifact location | 作者 AI prompt 仍可用；需要决定是否作为 active template 保留。 |
| [`docs/specs/ai-intent-prewarm.md`](../docs/specs/ai-intent-prewarm.md) | 240 | 6 | `stub+archive` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md), [`mcp-contracts.md`](../docs/mcp-contracts.md) | Preflight、message_only、platform prewarm 权限已迁入 canonical docs。 |
| [`docs/specs/campaign-package.md`](../docs/specs/campaign-package.md) | 381 | 9 | `stub+archive` | [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md), [`data-models.md`](../docs/data-models.md) | Campaign Package 当前合同已迁入 package/data docs。 |
| [`docs/specs/cli.md`](../docs/specs/cli.md) | 198 | 10 | `stub+archive` | [`cli-contracts.md`](../docs/cli-contracts.md) | CLI public / low-level / platform / MCP launch 合同已迁入 CLI canonical 文档。 |
| [`docs/specs/kernel-requirements.md`](../docs/specs/kernel-requirements.md) | 609 | 8 | `extract-before-archive` | [`project-overview.md`](../docs/project-overview.md), [`architecture.md`](../docs/architecture.md), [`development-guide.md`](../docs/development-guide.md) | V1 产品边界锚点，需核对 “不做什么 / 产品范围” 是否已完整保留。 |
| [`docs/specs/mcp-adapter.md`](../docs/specs/mcp-adapter.md) | 616 | 12 | `stub+archive` | [`mcp-contracts.md`](../docs/mcp-contracts.md), [`cli-contracts.md`](../docs/cli-contracts.md) | MCP profile、tool、path、preflight、commit、audit 合同已迁入 MCP canonical 文档。 |
| [`docs/specs/player-entry-save-manager.md`](../docs/specs/player-entry-save-manager.md) | 915 | 5 | `stub+archive` | [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md), [`ai-intent-chain.md`](../docs/ai-intent-chain.md), [`cli-contracts.md`](../docs/cli-contracts.md), [`mcp-contracts.md`](../docs/mcp-contracts.md) | 旧稿标记为 V1.1 draft；当前实现以 SaveManager、CLI、MCP 代码和 canonical docs 为准。 |
| [`docs/specs/save-package.md`](../docs/specs/save-package.md) | 173 | 8 | `stub+archive` | [`save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md), [`data-models.md`](../docs/data-models.md) | Save Package 当前合同已迁入 package/data docs。 |
| [`docs/specs/standard-intent-chain.md`](../docs/specs/standard-intent-chain.md) | 491 | 7 | `stub+archive` | [`ai-intent-chain.md`](../docs/ai-intent-chain.md) | 标准玩家意图链已迁入 canonical AI intent 文档。 |

## 推荐执行批次

### Round 4A：本映射表

状态：当前步骤。

产物：

- 本文件。
- 更新 BMAD migration plan，标记 Round 4 已开始 archive mapping。

### Round 4B：先摘取仍有用内容

建议先处理：

1. 从 [`docs/specs/kernel-requirements.md`](../docs/specs/kernel-requirements.md) 摘取仍未显式进入
   canonical docs 的 V1 产品边界和 “不做什么”。
2. 把 `docs/guides/author-*` 合并为 canonical authoring guidance，或决定仍保留为 active guide。
3. 决定 `docs/prompts/*` 的长期位置：active prompt artifact、模板目录，或 prompt contract 文档。
4. 从 [`docs/architecture/current-code-multi-expert-review.md`](../docs/architecture/current-code-multi-expert-review.md)
   摘出仍未关闭的质量/发布/安全/可靠性风险，放入 BMAD backlog 或 testing gate。

### Round 4C：归档高置信已迁移旧文档

移动原文到：

```text
docs/archive/pre-bmad-docs-2026-07-03/
```

对引用数大于 0 或外部入口可能引用的旧路径保留短 stub。Stub 只应说明：

- 文档已归档。
- 当前权威入口是谁。
- 旧文档只作为历史证据。

### Round 4D：链接和回归

归档/Stub 后至少执行：

```bash
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

如果只移动 Markdown 且不改示例命令，不需要代码 focused tests。若改动 prompt/guide 中的命令示例，再补对应 CLI/MCP focused tests。
