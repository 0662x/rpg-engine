# RPG Engine BMAD 扫描索引

文档状态：DRAFT / Round 1 Deep Scan
语言：zh-CN
迁移阶段：BMAD 扫描素材，未进入 canonical docs
生成时间：2026-07-03
工作流：`gds-document-project` Deep Scan

状态说明：本目录是后续 BMAD 正式文档迁移的扫描事实基线和待人工校准素材，不是最终 canonical 文档。

## 项目判断

这个仓库当前更接近 **Python backend/CLI/library 型 local-first AI GM 游戏引擎内核**，不是 Unity/Godot 这类图形客户端项目。

核心目标是：让 AI 负责叙事、提议和候选意图，让引擎负责校验、状态提交、隐藏信息保护、上下文构建和平台入口约束。

## 本轮产物

- [项目概览](./project-overview.md)
- [源码树分析](./source-tree-analysis.md)
- [架构扫描](./architecture.md)
- [组件清单](./component-inventory.md)
- [数据模型](./data-models.md)
- [开发指南](./development-guide.md)
- [Round 1 同步记录](./round-1-sync-report.md)
- [扫描状态 JSON](./project-scan-report.json)

## 迁移边界

- Round 4C 后，旧 `architecture/`、`specs/`、`guides/` 正文已归档到
  [`docs/archive/pre-bmad-docs-2026-07-03/`](../docs/archive/pre-bmad-docs-2026-07-03/)，
  旧路径保留 compatibility stubs。
- 本轮不移动旧文档，不改代码行为，不替换正式 README。
- 后续迁移以本目录为临时 BMAD 扫描输出，再整理为 `docs/` 下的 canonical 文档。
- 已有迁移计划见 [BMAD 文档迁移计划](./planning-artifacts/bmad-documentation-migration-plan.md)。

## 下一步建议

1. 先人工校准本扫描结果，再生成 `docs/index.md`、`docs/architecture.md`、`docs/development-guide.md` 等新主文档。
2. 逐篇审查旧 `docs/`，只迁移仍符合当前代码事实的内容。
3. 为 AI 意图链、平台预热链、写入提交链建立单独受控章节。
4. Round 4C 已把旧文档完成吸收后的原文归档到 `docs/archive/pre-bmad-docs-2026-07-03/`。
