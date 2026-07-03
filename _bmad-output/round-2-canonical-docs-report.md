# Round 2 Canonical Docs 同步记录

文档状态：DRAFT / Round 2 Canonical Docs Close-out
语言：zh-CN
迁移阶段：BMAD canonical docs 骨架已进入 `docs/`
日期：2026-07-03

## 本轮目标

按 [`planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)
执行 Round 2：把 Round 1 已审过的 BMAD Deep Scan 材料整理为 `docs/` 下的 canonical
文档骨架，同时保留旧文档目录作为后续迁移来源。

## 已生成或更新产物

- [`docs/index.md`](../docs/index.md)
- [`docs/project-overview.md`](../docs/project-overview.md)
- [`docs/source-tree-analysis.md`](../docs/source-tree-analysis.md)
- [`docs/architecture.md`](../docs/architecture.md)
- [`docs/component-inventory.md`](../docs/component-inventory.md)
- [`docs/development-guide.md`](../docs/development-guide.md)
- [`docs/testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md)
- [`docs/README.md`](../docs/README.md)
- [`_bmad-output/planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)

## 不改范围

- 不移动、删除或归档旧 `docs/architecture`、`docs/specs`、`docs/guides`、`docs/prompts`。
- 不改 runtime、SaveManager、MCP、CLI、platform、schema、migration 或测试行为。
- 不把旧文档直接升格为权威；旧文档仍需 Round 3 逐篇判断。
- 不提交或引用运行数据内容，例如 `.aigm/`、`saves/`、Save Package、玩家 SQLite、
  platform session 或 preflight cache。

## 关键同步内容

- `docs/index.md` 成为 canonical 文档入口。
- `docs/README.md` 收敛为兼容入口，指向 `docs/index.md`。
- Round 1 扫描中的项目定位、源码树、架构边界、组件职责和开发门禁已整理进 `docs/`。
- AI trust boundary 保持为：external AI 低信任候选，internal AI 只做 review，正式
  preview / validation / confirm / commit 仍在引擎内。
- 玩家路径保持为：`player_turn` 产生 pending proposal，`player_confirm` 才能提交。
- platform prewarm 仍只是 advisory / `message_only` 候选来源，正式入口必须重新校验身份。

## Review Gate

| 视角 | 结论 |
| --- | --- |
| BMAD / Docs Maintainer | 通过。`docs/index.md` 成为单一入口，旧长索引收敛为兼容入口。 |
| Engine Architect | 通过。玩家安全链、低层 runtime 链、platform sidecar 链、prewarm 链边界未被弱化。 |
| AI Intent Safety | 通过。external/internal AI、preflight cache、`message_only`、confirm gate 均保持原约束。 |
| Gameplay Flow | 通过。`player_turn -> pending/no save` 与 `player_confirm -> commit` 被明确记录。 |
| QA / Test Architect | 通过。新增 `testing-and-quality-gates.md` 收敛已有 `TESTING.md`、CI 和 BMAD 门禁。 |
| Repo Maintainer | 通过。未移动旧文档；新增链接通过本地 Markdown 检查。 |

## 验证记录

已执行：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m json.tool _bmad-output/project-scan-report.json >/dev/null
```

结果：

- `git diff --check`：通过。
- Markdown 链接检查：`checked 62 markdown files; local links ok`。
- `project-scan-report.json` JSON 语法检查：通过。

未执行：

- `python3 -m pytest`。原因：本轮仅改 Markdown 文档和 BMAD 计划产物，不改 Python 行为。

## 后续建议

下一轮进入 Round 3：把旧文档中仍是当前权威的内容合并到少数领域文档，例如
`docs/ai-intent-chain.md`、`docs/save-and-campaign-packages.md`、`docs/cli-contracts.md`、
`docs/mcp-contracts.md` 和 `docs/data-models.md`。
