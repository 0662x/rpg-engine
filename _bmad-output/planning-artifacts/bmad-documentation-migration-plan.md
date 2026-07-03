# BMAD 文档体系迁移计划

文档状态：**PROPOSED：迁移计划，尚未执行文档搬迁**

日期：2026-07-03

## 目标

把 RPG Engine 当前分散、混杂、历史包袱较重的 `docs/` 体系迁移到 BMAD
brownfield / established project 风格的文档结构。

这次迁移不是“继续往旧分类里补文档”，而是：

1. 冻结旧文档体系。
2. 用 BMAD/GDS document-project 的结构重建 canonical documentation。
3. 把长期项目上下文、架构、开发指南、测试门禁和功能说明重新整理成少数清晰入口。
4. 让未来开发默认更新 BMAD 风格文档，而不是继续维护旧的杂乱分类。

## 当前问题

当前 `docs/` 有以下问题：

- 分类过细且边界重叠：`architecture/`、`specs/`、`guides/`、`governance/`
  之间有重复说明。
- 历史设计、当前实现、实施日志和未来规划混在相邻目录里，读者不容易判断权威性。
- AI intent、SaveManager、MCP、CLI、platform 的链路文档分散，虽然内容已较完整，
  但入口成本高。
- `docs/README.md` 变成了长索引，而不是 BMAD 风格的 project documentation index。
- 后续如果继续在旧分类里补文档，会继续扩大维护面。

## BMAD 目标结构

采用 BMAD/GDS `document-project` 的 canonical structure，并按 RPG Engine 的
领域补少量专属文档。

目标长期结构：

```text
docs/
  index.md
  project-overview.md
  source-tree-analysis.md
  architecture.md
  development-guide.md
  component-inventory.md
  data-models.md
  cli-contracts.md
  mcp-contracts.md
  ai-intent-chain.md
  save-and-campaign-packages.md
  testing-and-quality-gates.md
  project-context.md
  governance/
    bmad-workflow.md
  archive/
    pre-bmad-docs-2026-07-03/
      ...
```

说明：

- `docs/index.md` 成为唯一长期文档入口。
- `docs/README.md` 可以保留为兼容入口，但只指向 `docs/index.md`，不再维护长索引。
- 旧 `docs/architecture`、`docs/specs`、`docs/guides`、`docs/prompts` 中仍有价值的内容
  迁入 canonical docs。
- 旧文件整体归档到 `docs/archive/pre-bmad-docs-2026-07-03/`，避免丢历史。
- `docs/project-context.md` 和 `docs/governance/bmad-workflow.md` 继续保留为 BMAD
  agent 约束入口。

## 不做什么

这次迁移不应该：

- 不改 runtime、MCP、CLI、platform、SaveManager 或测试行为。
- 不借文档迁移重写架构。
- 不把历史实施日志当成当前规范继续扩写。
- 不删除旧文档内容；先归档，再从 canonical docs 引用或摘取。
- 不一次性移动后不验证链接。

## 分轮实施

### Round 1：BMAD 深度扫描产物

目标：

- 使用 `gds-document-project` 的 deep scan 语义扫描当前项目。
- 产物先放在 `_bmad-output/`，不直接覆盖 `docs/`。
- 生成或手工整理以下草稿：
  - project overview
  - source tree analysis
  - architecture summary
  - development guide
  - component inventory

验收：

- 不移动旧文档。
- 不改代码行为。
- 记录扫描范围、遗漏和不确定点。

### Round 2：建立 canonical docs 骨架

目标：

- 在 `docs/` 下建立 BMAD 风格 canonical docs。
- `docs/index.md` 成为主入口。
- `docs/README.md` 改成兼容跳转入口。

首批文件：

- `docs/index.md`
- `docs/project-overview.md`
- `docs/source-tree-analysis.md`
- `docs/architecture.md`
- `docs/development-guide.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`

验收：

- 入口清楚。
- 每个文档只表达一种职责。
- 不删除旧文档。
- `git add -N docs _bmad-output && git diff --check` 通过。
- `python3 scripts/check_markdown_links.py docs _bmad-output` 通过。

### Round 3：领域文档合并

目标：

把旧文档中仍是当前权威的内容合并到少数领域文档：

- `docs/ai-intent-chain.md`
- `docs/save-and-campaign-packages.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/data-models.md`

迁移来源：

- `docs/specs/standard-intent-chain.md`
- `docs/specs/ai-intent-prewarm.md`
- `docs/specs/player-entry-save-manager.md`
- `docs/specs/campaign-package.md`
- `docs/specs/save-package.md`
- `docs/specs/cli.md`
- `docs/specs/mcp-adapter.md`
- `docs/architecture/intent-*.md`
- `docs/architecture/future-turn-coordinator-design.md`
- `docs/architecture/turn-flow-architecture.md`

验收：

- AI trust boundary 不弱化。
- `player_turn -> pending/no save` 和 `player_confirm -> commit` 边界不改写。
- 旧文档重要结论能在新文档找到位置。

### Round 4：归档旧分类

目标：

- 把旧 `docs/architecture`、`docs/specs`、`docs/guides`、`docs/prompts` 中已迁移内容
  归档到 `docs/archive/pre-bmad-docs-2026-07-03/`。
- 只保留必要的 compatibility stub 或入口说明。

验收：

- 不丢历史。
- 旧链接要么更新，要么通过 stub 指向新位置。
- `rg` 检查不再有主要入口指向旧权威文档。

### Round 5：链接和回归门禁

目标：

- 检查 Markdown 链接。
- 检查 BMAD project context 和 AGENTS 入口。
- 跑轻量代码回归，确认文档迁移没有夹带行为改动。

建议门禁：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m pytest -q tests/test_ai_intent.py tests/test_save_manager.py
```

如涉及 CLI/MCP 文档的命令示例，也应跑对应 focused tests。

## Review Gate

每轮至少需要以下视角复核：

- BMAD / Docs Maintainer：文档结构是否符合 BMAD 入口和输出习惯。
- Engine Architect：架构边界是否被错误简化。
- AI Intent Safety：external/internal AI trust boundary 是否准确。
- Gameplay Flow：turn / preview / confirm / commit 是否准确。
- QA / Test Architect：测试门禁是否匹配风险。
- Repo Maintainer：链接、归档、Git hygiene 是否干净。

## 风险

- 文档迁移本身不改代码，但可能让读者误解当前系统行为。
- 大规模移动 Markdown 文件会打断旧链接。
- BMAD 自动生成文档可能偏通用，需要人工校准 RPG Engine 的特殊边界。
- 如果直接删除旧文档，历史决策会丢失；必须先归档。
- 如果只保留 `_bmad-output/` 产物而不整理到 `docs/`，长期项目知识会变成临时产物。

## 建议结论

采用“BMAD generated draft -> curated canonical docs -> old docs archive”的路线。

不要直接把旧 `docs/` 原地改成另一个复杂分类；应该用 BMAD 的少数核心文档作为
长期入口，把旧文档变成归档证据。
