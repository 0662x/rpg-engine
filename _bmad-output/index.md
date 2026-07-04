# _bmad-output Directory Index

文档状态：CURRENT / BMAD output directory index
语言：zh-CN
更新工作流：`bmad-index-docs`
更新日期：2026-07-04

本目录保存 BMAD / GDS 的扫描、规划、审计和历史执行产物。长期项目知识入口仍是
[`../docs/index.md`](../docs/index.md)；本目录不是 canonical docs 的替代品。

## 使用规则

- **Strict GDS Rescan Outputs** 是本轮严格 `gds-document-project` 的扫描基线，可作为
  brownfield PRD、architecture 或 story 的输入。
- **Historical Round Reports** 是历史执行记录，保留上下文和验证证据，但不能单独作为当前规范权威。
- **Planning Artifacts** 是后续规划、风险和迁移材料。
- 隐藏目录如 `.archive/` 按 `bmad-index-docs` 规则不列入本索引。
- 若本目录内容与当前代码或 [`../docs/`](../docs/) canonical 文档冲突，以当前代码和 canonical docs 为准。

## Strict GDS Rescan Outputs

- **[api-contracts.md](./api-contracts.md)** - Public surface contract scan
- **[architecture.md](./architecture.md)** - Current architecture scan
- **[component-inventory.md](./component-inventory.md)** - Component responsibility inventory
- **[data-models.md](./data-models.md)** - Data model scan
- **[development-guide.md](./development-guide.md)** - Development operations scan
- **[document-project-completion-summary.md](./document-project-completion-summary.md)** - Workflow close-out summary
- **[documentation-provenance-audit.md](./documentation-provenance-audit.md)** - Document trust provenance audit
- **[project-overview.md](./project-overview.md)** - Project identity overview
- **[source-tree-analysis.md](./source-tree-analysis.md)** - Repository structure analysis

## Workflow State

- **[project-scan-report.json](./project-scan-report.json)** - Resumable workflow state

## Historical Round Reports

- **[round-1-sync-report.md](./round-1-sync-report.md)** - Initial deep scan close-out
- **[round-2-canonical-docs-report.md](./round-2-canonical-docs-report.md)** - Canonical docs skeleton report
- **[round-3-domain-docs-report.md](./round-3-domain-docs-report.md)** - Domain docs merge report
- **[round-4-archive-map.md](./round-4-archive-map.md)** - Legacy archive mapping
- **[round-5-docs-gate-report.md](./round-5-docs-gate-report.md)** - Documentation gate close-out
- **[round-6-doc-code-audit.md](./round-6-doc-code-audit.md)** - Docs-code audit report
- **[round-7-player-session-concurrency.md](./round-7-player-session-concurrency.md)** - Player session hardening report

## Subdirectories

### planning-artifacts/

- **[bmad-documentation-migration-plan.md](./planning-artifacts/bmad-documentation-migration-plan.md)** - Documentation migration plan
- **[bmad-residual-risk-backlog.md](./planning-artifacts/bmad-residual-risk-backlog.md)** - Extracted residual risk backlog

### implementation-artifacts/

- No visible files yet.

### test-artifacts/

- No visible files yet.

## Entry Points

- Start here for BMAD scan outputs: **[document-project-completion-summary.md](./document-project-completion-summary.md)**
- Use as brownfield input for future workflows: **[project-overview.md](./project-overview.md)** and
  **[architecture.md](./architecture.md)**
- Use to resolve old-document confusion: **[documentation-provenance-audit.md](./documentation-provenance-audit.md)**
