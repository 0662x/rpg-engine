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

### Save and campaign packages

已新增：

- [`docs/save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md)

已更新：

- [`docs/index.md`](../docs/index.md)
- [`_bmad-output/planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)

主要来源：

- [`docs/specs/campaign-package.md`](../docs/specs/campaign-package.md)
- [`docs/specs/save-package.md`](../docs/specs/save-package.md)
- [`docs/specs/player-entry-save-manager.md`](../docs/specs/player-entry-save-manager.md)
- [`docs/architecture/game-engine.md`](../docs/architecture/game-engine.md)
- [`docs/architecture/turn-flow-architecture.md`](../docs/architecture/turn-flow-architecture.md)
- [`docs/project-context.md`](../docs/project-context.md)

代码事实校验：

- `rpg_engine/campaign.py`
- `rpg_engine/save_service.py`
- `rpg_engine/save_archive.py`
- `rpg_engine/save_validation.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/packages/service.py`
- `rpg_engine/cli_v1.py`
- `rpg_engine/mcp_adapter.py`

### Data models

已新增：

- [`docs/data-models.md`](../docs/data-models.md)

已更新：

- [`docs/index.md`](../docs/index.md)
- [`_bmad-output/planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)

主要来源：

- [`docs/architecture.md`](../docs/architecture.md)
- [`docs/component-inventory.md`](../docs/component-inventory.md)
- [`docs/save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md)
- [`docs/testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md)
- [`docs/architecture/game-engine.md`](../docs/architecture/game-engine.md)
- [`docs/architecture/turn-flow-architecture.md`](../docs/architecture/turn-flow-architecture.md)

代码事实校验：

- `rpg_engine/db.py`
- `rpg_engine/resources/migrations/*.sql`
- `rpg_engine/delta_schema.py`
- `rpg_engine/proposal.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/validation_pipeline.py`
- `rpg_engine/unit_of_work.py`
- `rpg_engine/projections.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/content_types/*`
- `rpg_engine/save_manager.py`
- `schemas/*.json`
- `rpg_engine/resources/schemas/*.json`

### CLI contracts

已新增：

- [`docs/cli-contracts.md`](../docs/cli-contracts.md)

已更新：

- [`docs/index.md`](../docs/index.md)
- [`_bmad-output/planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)

主要来源：

- [`docs/specs/cli.md`](../docs/specs/cli.md)
- [`docs/ai-intent-chain.md`](../docs/ai-intent-chain.md)
- [`docs/save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md)
- [`docs/data-models.md`](../docs/data-models.md)
- [`docs/testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md)

代码事实校验：

- `rpg_engine/cli_v1.py`
- `rpg_engine/cli.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/runtime.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/platform_prewarm.py`
- `pyproject.toml`

## 不改范围

- 不移动或归档旧文档。
- 不改 Python 代码、测试、schema、CLI/MCP 行为或 runtime 行为。
- 不弱化 AI trust boundary。
- 不把 future coordinator 描述成当前已实现主路径。
- 不把旧 `player-entry-save-manager.md` 的过期设计草稿当成当前事实；以当前
  `SaveManager`、CLI 和 MCP 代码为准。
- 不把 reports、projection artifacts、registry、pending action 或 AI preflight cache 写成事实源。

## 已保留的关键边界

- External AI 仍只是 low-trust candidate。
- Internal AI 仍只是 visible-external independent review，不能 preview / validate / confirm / commit。
- Preflight cache 仍是 advisory、single-use、identity-bound。
- `message_only` preflight 创建时不绑定 external candidate。
- `player_turn` 仍只产生 query result、clarification、blocked 或 pending action，不提交事实。
- `player_confirm` 仍是普通玩家路径提交门。
- MCP player profile 仍不能调用低层工具。
- Platform sidecar 仍只 gate、prewarm、forward passive identity 和转发 act/confirm。
- Campaign Package 仍只定义作者内容、初始世界、规则、模板和 smoke tests。
- Save Package 仍保存一次游玩的当前事实，且 `data/game.sqlite` 是事实权威。
- Registry 仍只是 workspace 索引，不是事实源。
- `.aigmsave` 仍是完整归档形态，默认可能包含 GM hidden 信息。
- 投影产物仍由 `projection_state` 和 `ProjectionService` 管理，不是绕过 SQLite 的写入通道。
- `TurnProposal`、turn delta、`ValidationReport` 和 `ProjectionReport` 仍是运行合同或证据，
  不是已提交事实本身。
- Content registry 的 registered content type 与 delta schema 允许的 entity type 保持区分。
- CLI 仍只是 kernel 参考入口；`campaign/save/player/play/platform/mcp/eval` public groups
  与 legacy/admin surface 的权限边界分开记录。
- `play *` 仍是低层 runtime / developer / trusted-gm 工具，不写成普通玩家默认入口。
- `platform message` / prewarm 仍是 advisory，不写成事实提交入口。
- `mcp serve` / `mcp print-config` 仍只启动和配置 MCP；具体 MCP 工具权限仍由 profile gate 决定。

## 待完成 Round 3 文档

- `docs/mcp-contracts.md`

## Review Gate

| 视角 | 结论 |
| --- | --- |
| BMAD / Docs Maintainer | 通过。`docs/ai-intent-chain.md` 成为 AI intent 领域 canonical 入口，旧文档保留为来源。 |
| Engine Architect | 通过。没有把 future coordinator 写成当前 authority，也没有移动 resolver / validation / commit 边界。 |
| AI Intent Safety | 通过。external/internal/preflight/message-only 边界保持明确。 |
| Gameplay Flow | 通过。`player_turn -> pending/no save` 与 `player_confirm -> commit` 明确记录。 |
| Platform / MCP | 通过。player profile 和 platform sidecar 的低权限 surface 未被弱化。 |
| QA / Test Architect | 通过。文档收敛到既有 AI intent、SaveManager、package 和 projection 高风险测试门禁。 |
| Package / Save Boundary | 通过。Campaign Package、Save Package、workspace registry、projection 和 `.aigmsave` 的事实权威边界分开记录。 |
| Data Model Boundary | 通过。SQLite facts、turn delta、TurnProposal、validation/projection reports、registry、archive 和 preflight cache 的权威关系分开记录。 |
| CLI Contract Boundary | 通过。V1 public groups、low-level `play`、platform sidecar、MCP launch 和 legacy/admin surface 的职责分开记录。 |

## 验证记录

已执行：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m pytest -q tests/test_save_manager.py tests/test_campaign_validation.py tests/test_package_cli.py tests/test_package_save_condition_coverage.py tests/test_projection_service.py tests/test_current_native_visibility.py tests/test_save_patch.py
python3 -m pytest -q tests/test_validation_pipeline.py tests/test_projection_service.py tests/test_current_native_package.py tests/test_current_native_write_safety.py tests/test_current_native_visibility.py tests/test_save_manager.py tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_ai_intent.py tests/test_preflight_cache.py
python3 -m pytest -q tests/test_v1_cli.py tests/test_save_manager.py tests/test_mcp_adapter.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py
```

结果：

- `git diff --check`：通过。
- Markdown 链接检查：`checked 67 markdown files; local links ok`。
- Focused package/save tests：`55 passed, 28 subtests passed`。
- Focused data-model tests：`130 passed, 45 subtests passed`。
- Focused CLI contract tests：`58 passed, 17 subtests passed`。

未执行：

- 全量 `python3 -m pytest`。原因：本切片仅改 Markdown 文档和 BMAD 计划产物；已补跑
  SaveManager、Campaign validation、package CLI、projection、visibility、safe patch、
  validation pipeline、current native package/write safety、package merge、AI intent 和 preflight cache
  相关 focused tests。

如后续领域文档引入新的 CLI/MCP 命令示例，再补对应 focused tests。
