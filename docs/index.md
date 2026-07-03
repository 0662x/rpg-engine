# RPG Engine 文档索引

文档状态：**CURRENT：BMAD canonical documentation entry**

本目录是 RPG Engine / AIGM Kernel 的长期文档入口。当前文档体系正在从旧的
`architecture/`、`specs/`、`guides/`、`prompts/` 长索引迁移到 BMAD/GDS 风格的
少数 canonical 文档。

## 快速入口

| 目标 | 文档 |
| --- | --- |
| 了解项目定位 | [项目概览](project-overview.md) |
| 查看源码和目录边界 | [源码树分析](source-tree-analysis.md) |
| 理解当前架构 | [架构](architecture.md) |
| 查找模块职责 | [组件清单](component-inventory.md) |
| 理解 AI 意图链 | [AI 意图链](ai-intent-chain.md) |
| 理解 Save / Campaign 包边界 | [Save 与 Campaign Package](save-and-campaign-packages.md) |
| 理解数据模型 | [数据模型](data-models.md) |
| 理解 CLI 合同 | [CLI 合同](cli-contracts.md) |
| 理解 MCP 合同 | [MCP 合同](mcp-contracts.md) |
| 开始开发 | [开发指南](development-guide.md) |
| 选择测试和门禁 | [测试与质量门禁](testing-and-quality-gates.md) |
| 读取 AI agent 项目宪法 | [项目上下文](project-context.md) |
| 遵循 BMAD 流程 | [BMAD 强约束开发流程](governance/bmad-workflow.md) |

## 核心边界

RPG Engine 是一个 local-first AI GM kernel，用于长期文本 RPG 战役。它负责事实、
规则、校验、状态提交、隐藏信息保护、上下文构建和平台入口约束。

```text
AI proposes. Kernel verifies. Player confirms. Engine commits.
```

外部 AI 可以叙事、解释、建议和提出候选意图。引擎必须保留 preview、validation、
confirm 和 commit 权威。`SaveManager.player_turn()` 可以产生 pending proposal，
`SaveManager.player_confirm()` 才是普通玩家路径的提交门。

## BMAD 文档迁移状态

Round 1 Deep Scan 已完成，扫描材料保留在 [`../_bmad-output/`](../_bmad-output/)。
Round 2 已建立 canonical docs 骨架。Round 3 已把 AI intent、Save/Campaign、数据模型、
CLI 和 MCP 领域内容合并到 canonical 文档。旧文档暂时不移动、不删除，后续 Round 4 会把
已迁移内容归档或改成兼容入口。

当前 canonical 文档：

- [项目概览](project-overview.md)
- [源码树分析](source-tree-analysis.md)
- [架构](architecture.md)
- [组件清单](component-inventory.md)
- [AI 意图链](ai-intent-chain.md)
- [Save 与 Campaign Package](save-and-campaign-packages.md)
- [数据模型](data-models.md)
- [CLI 合同](cli-contracts.md)
- [MCP 合同](mcp-contracts.md)
- [开发指南](development-guide.md)
- [测试与质量门禁](testing-and-quality-gates.md)
- [项目上下文](project-context.md)
- [BMAD 强约束开发流程](governance/bmad-workflow.md)
- [内容生成治理](governance/content-generation.md)

## 旧文档迁移来源

以下目录仍保留原始历史和领域资料。它们是迁移来源，不再作为首选入口：

- [`architecture/`](architecture/)
- [`specs/`](specs/)
- [`guides/`](guides/)
- [`prompts/`](prompts/)
- [`archive/`](archive/)

读取旧文档时要先判断其状态：当前有效、部分有效、已过期，或只适合归档。若旧文档
与 canonical docs、代码事实或 BMAD 治理文档冲突，以当前代码事实和 canonical docs
为准。

## AI 辅助开发路径

规划或大改前按顺序读取：

1. [项目上下文](project-context.md)
2. [BMAD 强约束开发流程](governance/bmad-workflow.md)
3. [开发指南](development-guide.md)
4. [架构](architecture.md)
5. [组件清单](component-inventory.md)
6. [AI 意图链](ai-intent-chain.md)
7. [Save 与 Campaign Package](save-and-campaign-packages.md)
8. [数据模型](data-models.md)
9. [CLI 合同](cli-contracts.md)
10. [MCP 合同](mcp-contracts.md)
11. touched surface 对应的旧 spec / architecture 文档
12. [测试与质量门禁](testing-and-quality-gates.md)

AI intent、SaveManager、CLI、MCP、platform、schema、migration 或 hidden-content 相关改动
必须按 BMAD P0/P1 流程留下 plan、story、test/review 和 docs sync 证据。
