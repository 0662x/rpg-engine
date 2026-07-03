# Round 3 领域文档合并同步记录

文档状态：DRAFT / Round 3 Domain Docs In Progress
语言：zh-CN
迁移阶段：BMAD canonical domain docs 合并中
日期：2026-07-03

## 本轮目标

按 [`planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)
执行 Round 3：把旧 `docs/` 中仍是当前权威的领域内容合并到少数 canonical 文档。

## 当前已完成切片

### AI intent chain

已新增：

- [`docs/ai-intent-chain.md`](../docs/ai-intent-chain.md)

已更新：

- [`docs/index.md`](../docs/index.md)
- [`_bmad-output/planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)

主要来源：

- [`docs/specs/standard-intent-chain.md`](../docs/specs/standard-intent-chain.md)
- [`docs/specs/ai-intent-prewarm.md`](../docs/specs/ai-intent-prewarm.md)
- [`docs/specs/mcp-adapter.md`](../docs/specs/mcp-adapter.md)
- [`docs/specs/cli.md`](../docs/specs/cli.md)
- [`docs/architecture/intent-coordinator-refactor-plan.md`](../docs/architecture/intent-coordinator-refactor-plan.md)
- [`docs/architecture/intent-refactor-implementation-log.md`](../docs/architecture/intent-refactor-implementation-log.md)
- [`docs/architecture/intent-design-alignment-review.md`](../docs/architecture/intent-design-alignment-review.md)
- [`docs/architecture/future-turn-coordinator-design.md`](../docs/architecture/future-turn-coordinator-design.md)
- [`docs/architecture/turn-flow-architecture.md`](../docs/architecture/turn-flow-architecture.md)

代码事实校验：

- `rpg_engine/save_manager.py`
- `rpg_engine/runtime.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/preflight_cache.py`
- `rpg_engine/intent_manifest.py`

## 不改范围

- 不移动或归档旧文档。
- 不改 Python 代码、测试、schema、CLI/MCP 行为或 runtime 行为。
- 不弱化 AI trust boundary。
- 不把 future coordinator 描述成当前已实现主路径。

## 已保留的关键边界

- External AI 仍只是 low-trust candidate。
- Internal AI 仍只是 visible-external independent review，不能 preview / validate / confirm / commit。
- Preflight cache 仍是 advisory、single-use、identity-bound。
- `message_only` preflight 创建时不绑定 external candidate。
- `player_turn` 仍只产生 query result、clarification、blocked 或 pending action，不提交事实。
- `player_confirm` 仍是普通玩家路径提交门。
- MCP player profile 仍不能调用低层工具。
- Platform sidecar 仍只 gate、prewarm、forward passive identity 和转发 act/confirm。

## 待完成 Round 3 文档

- `docs/save-and-campaign-packages.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/data-models.md`

## Review Gate

| 视角 | 结论 |
| --- | --- |
| BMAD / Docs Maintainer | 通过。`docs/ai-intent-chain.md` 成为 AI intent 领域 canonical 入口，旧文档保留为来源。 |
| Engine Architect | 通过。没有把 future coordinator 写成当前 authority，也没有移动 resolver / validation / commit 边界。 |
| AI Intent Safety | 通过。external/internal/preflight/message-only 边界保持明确。 |
| Gameplay Flow | 通过。`player_turn -> pending/no save` 与 `player_confirm -> commit` 明确记录。 |
| Platform / MCP | 通过。player profile 和 platform sidecar 的低权限 surface 未被弱化。 |
| QA / Test Architect | 通过。文档收敛到既有 AI intent 高风险测试门禁。 |

## 验证记录

已执行：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

结果：

- `git diff --check`：通过。
- Markdown 链接检查：`checked 64 markdown files; local links ok`。

未执行：

- `python3 -m pytest`。原因：本切片仅改 Markdown 文档和 BMAD 计划产物，不改 Python 行为。

如后续领域文档引入新的 CLI/MCP 命令示例，再补对应 focused tests。
