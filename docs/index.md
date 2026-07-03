# RPG Engine 文档索引

文档状态：**CURRENT：BMAD canonical documentation entry**

本目录是 RPG Engine / AIGM Kernel 的长期文档入口。旧 `architecture/`、`specs/`
和 `guides/` 正文已在 BMAD Round 4C 归档，当前只保留 compatibility stubs。
长期入口是本索引列出的少数 canonical 文档。

## 快速入口

| 目标 | 文档 |
| --- | --- |
| 了解项目定位 | [项目概览](project-overview.md) |
| 查看源码和目录边界 | [源码树分析](source-tree-analysis.md) |
| 理解当前架构 | [架构](architecture.md) |
| 查找模块职责 | [组件清单](component-inventory.md) |
| 理解 AI 意图链 | [AI 意图链](ai-intent-chain.md) |
| 理解 Save / Campaign 包边界 | [Save 与 Campaign Package](save-and-campaign-packages.md) |
| 创作或维护 Campaign Package | [作者指南](authoring-guide.md) |
| 理解数据模型 | [数据模型](data-models.md) |
| 理解 CLI 合同 | [CLI 合同](cli-contracts.md) |
| 理解 MCP 合同 | [MCP 合同](mcp-contracts.md) |
| 管理 prompt artifacts | [Prompt 合同](prompt-contracts.md) |
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
CLI 和 MCP 领域内容合并到 canonical 文档。Round 4B 已处理作者指南、prompt 长期位置、
V1 产品边界和残余风险摘取。Round 4C 已把旧 `architecture/`、`specs/`、`guides/`
原文归档到 [`archive/pre-bmad-docs-2026-07-03/`](archive/pre-bmad-docs-2026-07-03/)，
并在旧路径留下短 stub。执行记录见
[`../_bmad-output/round-4-archive-map.md`](../_bmad-output/round-4-archive-map.md)。

当前 canonical 文档：

- [项目概览](project-overview.md)
- [源码树分析](source-tree-analysis.md)
- [架构](architecture.md)
- [组件清单](component-inventory.md)
- [AI 意图链](ai-intent-chain.md)
- [Save 与 Campaign Package](save-and-campaign-packages.md)
- [作者指南](authoring-guide.md)
- [数据模型](data-models.md)
- [CLI 合同](cli-contracts.md)
- [MCP 合同](mcp-contracts.md)
- [Prompt 合同](prompt-contracts.md)
- [开发指南](development-guide.md)
- [测试与质量门禁](testing-and-quality-gates.md)
- [项目上下文](project-context.md)
- [BMAD 强约束开发流程](governance/bmad-workflow.md)
- [内容生成治理](governance/content-generation.md)

## 旧文档兼容入口

以下目录现在只保留 compatibility stubs，不再作为规范入口：

- [`architecture/`](architecture/)
- [`specs/`](specs/)
- [`guides/`](guides/)

归档原文位于 [`archive/pre-bmad-docs-2026-07-03/`](archive/pre-bmad-docs-2026-07-03/)。

[`prompts/`](prompts/) 不是普通历史目录。Round 4B 已决定它继续作为 active prompt artifact
目录保留，由 [Prompt 合同](prompt-contracts.md) 管理长期位置、版本和权限语义。

归档原文只作历史证据。若归档原文与 canonical docs、代码事实或 BMAD 治理文档冲突，
以当前代码事实和 canonical docs 为准。

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
11. [Prompt 合同](prompt-contracts.md)
12. [作者指南](authoring-guide.md)（涉及 Campaign authoring 时）
13. touched surface 对应的 canonical 文档；必要时再读 archive 原文作为历史证据
14. [测试与质量门禁](testing-and-quality-gates.md)

AI intent、SaveManager、CLI、MCP、platform、schema、migration 或 hidden-content 相关改动
必须按 BMAD P0/P1 流程留下 plan、story、test/review 和 docs sync 证据。
