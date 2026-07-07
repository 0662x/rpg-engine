---
baseline_commit: a3187b5d4870fa6e5e0671331193e679d2c87c44
---

# Story 1.5: Projection and Outbox Health Evidence

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为长期存档的主持者，
我希望 projection 和 outbox failure 可见、可报告、可修复，
从而让 read model 可以失败，但不会污染权威 gameplay facts。

## 验收标准

1. 给定一次 validated commit 成功，当 post-commit projection refresh 运行时，`projection_state` 必须记录 required projection 的 status、version、`last_turn_id` 和失败细节；projection artifacts 仍然只是 post-commit read models。
2. 给定 `events_jsonl`、search、snapshots、cards 或其他 required projections 处于 dirty、stale、refreshing、failed，或落后于 `current_turn_id`，当 `save validate`、`save inspect` 或等价 inspection 运行时，health report 必须暴露 mismatch，并且不能把 committed facts 从 projection artifacts 中重新解释或回填。
3. 给定 projection repair 通过 maintenance/admin surface 被调用，当 repair 成功或失败时，结果必须被记录为 repair evidence；repair 不得绕过 pre-commit validation、player confirmation 或 SQLite fact authority。

## 任务 / 子任务

- [x] 补齐 projection/outbox health evidence 的机器可读形状。 (AC: 1, 2)
  - [x] 复用现有 `ProjectionService`、`ProjectionReport`、`ProjectionItemReport`、`projection_state` 和 `outbox`；不要新增第二套 projection health 服务或事实表。
  - [x] 确保 required projections 至少覆盖 `events_jsonl`、`search`、`snapshots`、`cards`，并在 report 中暴露 status、version、`last_turn_id`、effective stale status、failure detail、artifact path 和 outbox summary。
  - [x] 如果现有 `inspect_save_package()` 只有字符串 errors，不足以作为 health report，补一个小型稳定字段，例如 `projection_health` 或等价结构；字段必须声明这些数据是 health/evidence，不是 fact authority。
  - [x] 保持 `authority_contract` 中 `data/game.sqlite`、SQLite `events`、projection artifacts、`projection_state` 和 `outbox` 的职责不变。

- [x] 强化 dirty/stale/failed/behind/outbox mismatch 的 inspect/validate 暴露。 (AC: 2)
  - [x] 覆盖 `projection_state` missing、dirty、refreshing、failed、version 落后、`last_turn_id != current_turn_id` 的 required projection cases。
  - [x] 覆盖 outbox `pending` 和 `failed` rows，确保 `save validate`/inspect 输出包含 row id、status、last error 或足够定位的信息。
  - [x] 覆盖 derived artifact drift：`data/events.jsonl` 缺失或多出 SQLite event、`snapshots/current.json` meta 落后、cards/search 与 SQLite 不一致时，只报告 drift，不改变 SQLite facts。
  - [x] 保持 `current_turn_id`、entity counts、turn/event/clock counts 和 meta 读取自 SQLite；不得从 JSONL、snapshot、cards、registry 或 pending state 回填。

- [x] 让 projection repair 产生明确 repair evidence。 (AC: 3)
  - [x] `aigm projection repair` 继续作为 maintenance/admin 或 `projection/outbox` surface；不得成为普通玩家入口。
  - [x] Repair 输出应包含 profile、requested names、refreshed names、skipped names、requested/global dirty/failed/stale、artifacts、errors、started/finished time 或 duration 等足够证据。
  - [x] Repair 成功必须清理对应 `projection_state` failure/stale/dirty 状态并让 artifact 与 SQLite 对齐；失败必须保留 `projection_state.last_error`、outbox `last_error` 或 report errors。
  - [x] Targeted repair 不能隐藏 unrelated failed projections；全局 health 仍应报告其他 projection/outbox failure。
  - [x] Repair 不得写 turns、events、entities、clocks 或 `current_turn_id`，也不得生成 pending action、player confirmation 或 low-level commit approval。

- [x] 同步 public contract、surface taxonomy 和文档，仅限实际变更。 (AC: 1, 2, 3)
  - [x] 如果 `save inspect`/`save validate` JSON 形状改变，更新 `docs/save-and-campaign-packages.md`、`docs/data-models.md` 和 `docs/cli-contracts.md`。
  - [x] 如果 projection repair 增加 JSON/format 输出或字段，更新 CLI contract 和 tests；MCP 当前不暴露 projection repair，不要无需求新增 MCP repair tool。
  - [x] 如果新增或重命名 public/semi-public surface，更新 `rpg_engine/surface_inventory.py` 并补 `tests/test_surface_inventory.py`。

- [x] 添加 focused boundary gates。 (AC: 1, 2, 3)
  - [x] 增强 `tests/test_projection_service.py`：commit/refresh report 包含 required projection health evidence，失败不回滚 SQLite facts，targeted repair 保留 unrelated failure 可见。
  - [x] 增强 `tests/test_v1_cli.py` 或相关 CLI tests：`save validate`/inspect 暴露 dirty、stale、failed、behind、outbox pending/failed，`projection repair` 输出 repair evidence。
  - [x] 增强 current-native 写入安全测试时只在 temp copy 上操作，不直接写 formal current save package。
  - [x] 运行最小相关 gates，并在 Dev Agent Record 记录命令和结果。

### Review Findings

- [x] [Review][Patch] Missing current_turn_id can pass validation while projection health says clean [rpg_engine/save_validation.py:248]
- [x] [Review][Patch] projection_health.outbox reports clean when outbox table is missing [rpg_engine/save_validation.py:289]
- [x] [Review][Patch] Targeted projection repair hides unrelated outbox failures [rpg_engine/projection_service.py:209]
- [x] [Review][Patch] Malformed or partial outbox schema can abort later validation and omit non-done work [rpg_engine/save_validation.py:307]
- [x] [Review][Patch] Outbox failures mentioning events.jsonl get event-log error code [rpg_engine/validation_issues.py:54]
- [x] [Review][Patch] Malformed projection_state schema can abort health reporting [rpg_engine/save_validation.py:222]
- [x] [Review][Patch] Unknown projection_state status can leave projection_health.status clean while item is unhealthy [rpg_engine/save_validation.py:300]
- [x] [Review][Patch] Unknown outbox status is reported as pending even repair will not retry it [rpg_engine/projections.py:127]
- [x] [Review][Patch] Repair text and Markdown output omit outbox last_error and timestamps [rpg_engine/cli.py:1250]
- [x] [Review][Patch] Projection repair can report clean when projection_state table is missing [rpg_engine/projection_service.py:452]
- [x] [Review][Patch] Projection repair can crash before emitting evidence on malformed projection_state or outbox schema [rpg_engine/projection_service.py:236]
- [x] [Review][Patch] Stored stale projection_state status is treated as invalid [rpg_engine/save_validation.py:273]
- [x] [Review][Patch] Projection repair global_status can ignore invalid projection_state statuses [rpg_engine/projection_service.py:452]
- [x] [Review][Patch] Projection health can hide duplicate projection_state names in malformed schemas [rpg_engine/save_validation.py:243]
- [x] [Review][Patch] Projection/outbox health helpers can treat views as healthy tables [rpg_engine/save_validation.py:235]
- [x] [Review][Patch] Outbox rows with missing ids are not classified as malformed evidence [rpg_engine/projections.py:106]
- [x] [Review][Patch] Event-log validation messages containing outbox text get projection error codes [rpg_engine/validation_issues.py:54]
- [x] [Review][Patch] Repair text output can be line-forged by newline characters in outbox evidence [rpg_engine/projection_service.py:29]
- [x] [Review][Patch] Repair text output emits duplicate `global_failed` evidence keys [rpg_engine/cli.py:1247]
- [x] [Review][Patch] Unavailable `projection_health` omits the stable top-level errors shape [rpg_engine/save_validation.py:208]
- [x] [Review][Patch] Blank `meta.current_turn_id` can make projection health report clean when projection rows also use blank turn ids [rpg_engine/save_validation.py:231]

## 开发说明

### 来源上下文

- Epic 1 要求可信本地玩家写入闭环、surface authority、Save fact authority 和 projection/outbox 证据边界；Story 1.5 专门处理 projection/outbox failure 的可见、可报告、可修复。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 1.5 的原始 AC 要求 validated commit 后 projection refresh 记录 required projection status/version/last turn/failure details；save validate 或等价 inspection 暴露 dirty/stale/refreshing/failed/behind；maintenance repair 记录 repair evidence 且不绕过 validation、player confirmation 或 SQLite fact authority。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-3 明确 projection/outbox 是 post-commit read model 和 evidence，不能成为 gameplay fact authority；projection/outbox failure 必须可见、可报告、可修复。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- PRD FR-14 要求 Save Package current facts、events、pending actions、projections 和 metadata 职责分离；FR-15 要求 author/host operations 提供可操作 diagnostics 但不能成为普通 gameplay bypass。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Execution-chain AD-4 规定 SQLite commits 是 facts，`ProjectionService`、projection tables、search、snapshots、cards、memory 和 event outbox 都是 post-commit、visible、reportable、repairable evidence；AD-5 要求本 story 带最小有意义 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。
- Foundation AD-1 规定 Save Package 包含 SQLite facts/events、projections、snapshots、cards、memory 和 metadata；`.aigm/save-registry.json`、pending、preflight、proposal/advisory state 都不是 gameplay facts。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Canonical docs 已声明 `projection_state` 和 `outbox` 在 SQLite 内，但职责只是 projection health 和 work-queue evidence，不能改变 turns、events、entities、clocks 或 meta 的事实含义。来源：`docs/save-and-campaign-packages.md`、`docs/data-models.md`。

### 当前实现状态

- `rpg_engine/projections.py` 当前定义 `PROJECTION_VERSIONS`：`events_jsonl`、`search`、`snapshots`、`cards`、`memory`、`reports`、`package_lock`；`projection_state` 支持 `clean`、`dirty`、`refreshing`、`failed`，并通过版本落后计算 effective `stale`。来源：`rpg_engine/projections.py`。
- `ensure_projection_rows()` 会初始化 projection rows；`mark_projections_dirty()` 记录 version、`last_turn_id`、status 和 updated time；`mark_projection_failed()` 当前记录 status=`failed` 和截断后的 `last_error`。来源：`rpg_engine/projections.py`。
- `process_outbox()` 处理 `events.jsonl.append` durable outbox，成功后标记 row `done` 并清理 error；失败时标记 outbox `failed`，并把 `events_jsonl` projection 标成 failed。来源：`rpg_engine/projections.py`。
- `ProjectionService.refresh()` 已返回 `ProjectionReport`，包含 requested/refreshed/skipped、requested/global dirty/failed/stale、artifacts、errors、items、started/finished/duration；`_refresh_one()` 会先标记 `refreshing`，成功标 `clean`，失败标 `failed`。来源：`rpg_engine/projection_service.py`。
- `ProjectionReport.status` 当前基于 requested projections；`global_status` 基于所有 projection rows。Targeted repair 后 unrelated failure 应继续出现在 `global_failed` 或 `global_status`。来源：`rpg_engine/projection_service.py`。
- `UnitOfWork.mark_standard_projections()` 在 commit 期间将 standard projections 标 dirty、enqueue event export、重建 search 并把 search 标 clean；`finalize_artifacts()` 在提交后处理 outbox。来源：`rpg_engine/unit_of_work.py`。
- `commit_turn_delta()` post-commit 当前通过 `ProjectionService` 刷新 `snapshots`、`cards`，可选 `memory`，并把 `projection_report` 放进 `CommitResult`；不要把 projection failure 当成事实回滚策略。来源：`rpg_engine/commit_service.py`。
- `inspect_save_package()` 当前验证 required files、schema/migrations/meta、projection_state/outbox、events JSONL、snapshot JSON、cards 和 search projection；它已经返回 `authority_contract`，但 projection health 主要通过 errors/error_details 暴露。来源：`rpg_engine/save_validation.py`。
- `validate_projection_state()` 当前 required projections 是 `events_jsonl`、`search`、`snapshots`、`cards`；它会报告 missing、非 clean status、version 落后、`last_turn_id` 不等于 `current_turn_id`，并报告 outbox 非 `done` row。来源：`rpg_engine/save_validation.py`。
- `aigm projection status` 当前用 `render_projection_status()` 输出 projection table 和 outbox counts；`aigm projection repair` 调用 `ProjectionService.refresh(profile="projection_repair:maintenance_projection", commit_policy="caller_committed_required")`，并打印 OK/FAILED、status、global_status、refreshed、failed、global_failed、artifact、error。来源：`rpg_engine/cli.py`。
- MCP contract 当前明确不暴露 `repair`、package install/upgrade/reconcile、migration apply 或 projection repair；本 story 不应顺手新增 MCP repair。来源：`docs/mcp-contracts.md`。

### 前序故事情报

- Story 1.4 已完成 Save fact authority 和 runtime state boundary，新增/强化了 `authority_contract`，确认 `data/game.sqlite` 是 current fact authority，SQLite `events` 是权威审计记录，JSONL/snapshots/cards/memory/projection reports/registry metadata 不得覆盖 SQLite facts。
- Story 1.4 已覆盖派生产物 drift 不提升为事实：篡改 JSONL、snapshot、cards/search/projection_state/outbox 时，`save inspect` 仍从 SQLite 读 current turn 和 counts，并报告 drift/dirty/failed/stale。
- Story 1.4 review 修复过 registry path、archive import core files 和 cached summary authority；Story 1.5 不应回退这些边界，也不要把 registry refresh、archive manifest、pending state 或 audit log 变成事实源。
- 最近完整回归在 Story 1.4 后通过：`python3 -m pytest -q` 为 `488 passed, 627 subtests passed`。本 story 可先跑 focused gates，若改动共享 Save/validation/CLI 边界，再扩大到全量。

### 架构合规要求

- Surface category：`ProjectionService.refresh`、`render_projection_status`、`aigm projection status/repair` 属于 `projection/outbox` 或 maintenance/admin；默认玩家路径不得调用 repair 来完成 gameplay commit。
- `projection_state`、outbox、events JSONL、snapshots、cards、memory、reports 和 package lock 都是 derived/evidence；它们不能替代 pre-commit validation、proposal approval、player confirmation 或 SQLite fact authority。
- `save inspect` 和 `save validate` 可以报告 mismatch、health、repair options 或 evidence，但不能自动修正 SQLite facts，也不能从 artifacts 推导新 facts。
- Projection repair 可以重建 read models、retry outbox、更新 projection health evidence；不能写 turns、events、entities、clocks、facts、`current_turn_id` 或 player pending state。
- 所有写入测试必须使用临时复制的 campaign/save；不得直接写正式 current save package。
- 如果 public result shape 变化，保持字段结构稳定、机器可读、可测试，并同步 docs/tests。

### 相关文件

- `rpg_engine/projections.py`：projection versions、projection_state helpers、outbox processing、events JSONL rewrite、status rendering。
- `rpg_engine/projection_service.py`：ProjectionService refresh/repair 核心、ProjectionReport shape、item-level artifacts/errors/timing。
- `rpg_engine/save_validation.py`：`inspect_save_package()`、required projection validation、outbox mismatch、artifact drift checks、`authority_contract`。
- `rpg_engine/cli.py`：legacy/admin `projection status` 和 `projection repair` CLI surface；不要误改 `cli_v1.py` 作为 projection repair 主入口。
- `rpg_engine/commit_service.py`、`rpg_engine/unit_of_work.py`、`rpg_engine/save.py`：commit 后 projection/outbox 刷新链和不回滚事实的边界。
- `rpg_engine/surface_inventory.py`：projection/outbox surface taxonomy；新增/重命名 surface 时必须更新。
- `docs/save-and-campaign-packages.md`、`docs/data-models.md`、`docs/cli-contracts.md`、`docs/mcp-contracts.md`：canonical public contracts。
- `tests/test_projection_service.py`：ProjectionService report/repair/failure/stale gates。
- `tests/test_v1_cli.py`：save init/inspect/validate/export/import、projection drift 和 CLI repair gates。
- `tests/test_current_native_write_safety.py`：current native temp-copy projection repair safety。
- `tests/test_surface_inventory.py`：surface taxonomy sentinel if surface metadata changes。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py
python3 -m pytest -q tests/test_current_native_write_safety.py
git diff --check
```

如果只改 docs/story artifact：

```bash
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md
```

如果 public/semi-public surface taxonomy 变化：

```bash
python3 -m pytest -q tests/test_surface_inventory.py tests/test_namespace_boundaries.py
```

如果 Save Package schema、migration、commit service 或 shared validation contract 变化：

```bash
python3 -m pytest -q
```

### 残余风险与边界

- Story 1.4 已建立 fact authority contract；Story 1.5 只补 projection/outbox health/repair evidence，不应把范围扩成通用 ops dashboard。
- Optional projections `memory`、`reports`、`package_lock` 存在于 `PROJECTION_VERSIONS`，但当前 required projections 是 `events_jsonl`、`search`、`snapshots`、`cards`。如果扩大 required set，必须同步 docs、tests 和 migration/compat 预期。
- `ProjectionReport.status` 与 `global_status` 的语义不同。Targeted repair 的 requested status 可以 clean，但 global status 仍可能 failed；不要在 UI 或 tests 中把两者混用。
- `events_jsonl` 同时涉及 outbox 和 full rewrite repair。实现时要保持 idempotent append/rewrite，不要产生重复 event rows 或把 JSONL 内容写回 SQLite events。
- Projection repair UX、dashboard 和长期 repair history 可以后续扩展；本 story 只要求当前 repair invocation 的证据足够可见、可测试、可诊断。

### 最新技术信息

无需外部 Web research。本 story 使用现有 Python stdlib、SQLite、pytest、atomic write helpers、`ProjectionService`、`inspect_save_package()` 和 CLI patterns。不要新增运行时依赖。

## Project Structure Notes

Story 1.5 应优先增强现有 projection/save validation/CLI 合同与测试，不应引入新包层级、新数据库事实源或并行 health registry。若需要机器可读 health 字段，优先放在 `save_validation.py` 的 inspect 输出和 ProjectionReport helpers 中，并同步 canonical docs/tests。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/save-and-campaign-packages.md`
- `docs/data-models.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/projections.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/save_validation.py`
- `rpg_engine/cli.py`
- `rpg_engine/commit_service.py`
- `rpg_engine/unit_of_work.py`
- `rpg_engine/surface_inventory.py`
- `tests/test_projection_service.py`
- `tests/test_v1_cli.py`
- `tests/test_current_native_write_safety.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import tests/test_v1_cli.py::V1CliTests::test_save_validate_rejects_dirty_projection_and_event_log_drift tests/test_v1_cli.py::V1CliTests::test_save_validate_projection_health_covers_required_state_mismatches tests/test_v1_cli.py::V1CliTests::test_save_inspect_reports_derived_drift_without_promoting_artifacts` failed on missing `projection_health`, incomplete repair evidence output, and outbox last-error reporting.
- GREEN: same targeted V1 CLI tests passed after adding `projection_health`, outbox row details, and repair report evidence.
- RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_inspect_reports_derived_drift_without_promoting_artifacts` failed because outbox mismatch was classified as generic save validation error.
- GREEN: same drift test passed after classifying outbox mismatch as `PROJECTION_INCONSISTENT`.
- Focused gate: `python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py` passed with 28 tests and 5 subtests.
- Focused gate: `python3 -m pytest -q tests/test_current_native_write_safety.py` passed with 7 tests.
- Additional related gate: `python3 -m pytest -q tests/test_mcp_adapter.py` passed with 24 tests.
- Docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md` passed.
- Diff gate: `git diff --check` passed.
- Full regression: `python3 -m pytest -q` passed with 489 tests and 627 subtests.
- Review RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_validate_rejects_missing_current_turn_id_in_projection_health tests/test_v1_cli.py::V1CliTests::test_save_validate_projection_health_reports_missing_outbox_table tests/test_v1_cli.py::V1CliTests::test_save_validate_tolerates_partial_outbox_schema_and_reports_health_error tests/test_v1_cli.py::V1CliTests::test_save_validate_outbox_error_code_precedes_event_log_path_in_last_error tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_unrelated_failed_outbox tests/test_projection_service.py::ProjectionServiceTests::test_targeted_repair_reports_unrelated_failed_outbox` failed with 6 expected review-finding failures.
- Review GREEN: same review-focused command passed with 6 tests.
- Review focused gate: `python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py` passed with 34 tests and 5 subtests.
- Review surface gate: `python3 -m pytest -q tests/test_surface_inventory.py::SurfaceInventoryTests::test_runtime_platform_and_projection_inventory_cover_source_entrypoints tests/test_projection_service.py tests/test_v1_cli.py` passed with 35 tests and 8 subtests after keeping shared outbox helpers private.
- Review full regression: `python3 -m pytest -q` passed with 495 tests and 627 subtests.
- Review syntax gate: `python3 -m py_compile rpg_engine/projections.py rpg_engine/save_validation.py rpg_engine/projection_service.py rpg_engine/cli.py rpg_engine/validation_issues.py` passed.
- Review diff gate: `git diff --check` passed.
- Review docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md` passed.
- Re-review RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_validate_tolerates_partial_projection_state_schema tests/test_v1_cli.py::V1CliTests::test_save_validate_reports_unknown_projection_state_status_as_invalid tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_invalid_outbox_status_with_details tests/test_projection_service.py::ProjectionServiceTests::test_targeted_repair_reports_unrelated_failed_outbox` failed with 4 expected re-review findings.
- Re-review GREEN: same re-review-focused command passed with 4 tests.
- Re-review focused gate: `python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py tests/test_surface_inventory.py::SurfaceInventoryTests::test_runtime_platform_and_projection_inventory_cover_source_entrypoints` passed with 38 tests and 8 subtests.
- Re-review full regression: `python3 -m pytest -q` passed with 498 tests and 627 subtests.
- Re-review syntax gate: `python3 -m py_compile rpg_engine/projections.py rpg_engine/save_validation.py rpg_engine/projection_service.py rpg_engine/cli.py rpg_engine/validation_issues.py` passed.
- Re-review diff gate: `git diff --check` passed.
- Re-review docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md` passed.
- Third-rerun RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_validate_accepts_stored_stale_projection_state_status tests/test_v1_cli.py::V1CliTests::test_save_validate_rejects_duplicate_projection_state_names tests/test_v1_cli.py::V1CliTests::test_save_validate_rejects_projection_state_and_outbox_views_as_missing_tables tests/test_v1_cli.py::V1CliTests::test_save_validate_rejects_outbox_row_with_missing_id tests/test_v1_cli.py::V1CliTests::test_save_validate_event_log_error_code_precedes_outbox_text_in_event_id tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_invalid_outbox_status_with_details tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_missing_projection_state_table tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_malformed_projection_state_without_traceback tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_invalid_projection_state_status_globally` failed with 9 expected third-rerun findings.
- Third-rerun GREEN: same third-rerun-focused command passed with 9 tests.
- Third-rerun focused gate: `python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py tests/test_surface_inventory.py::SurfaceInventoryTests::test_runtime_platform_and_projection_inventory_cover_source_entrypoints` passed with 46 tests and 8 subtests.
- Third-rerun syntax gate: `python3 -m py_compile rpg_engine/projection_service.py rpg_engine/projections.py rpg_engine/save_validation.py rpg_engine/validation_issues.py rpg_engine/cli.py` passed.
- Third-rerun full regression: `python3 -m pytest -q` passed with 506 tests and 627 subtests.
- Third-rerun diff gate: `git diff --check` passed.
- Third-rerun docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md` passed.
- Close-time RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_projection_repair_reports_invalid_projection_state_status_globally tests/test_v1_cli.py::V1CliTests::test_save_inspect_projection_health_unavailable_keeps_errors_shape` failed with 2 expected late review findings.
- Close-time GREEN: same close-time-focused command passed with 2 tests.
- Close-time focused gate: `python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py tests/test_surface_inventory.py::SurfaceInventoryTests::test_runtime_platform_and_projection_inventory_cover_source_entrypoints` passed with 47 tests and 8 subtests.
- Close-time full regression: `python3 -m pytest -q` passed with 507 tests and 627 subtests.
- Close-time syntax gate: `python3 -m py_compile rpg_engine/projection_service.py rpg_engine/projections.py rpg_engine/save_validation.py rpg_engine/validation_issues.py rpg_engine/cli.py` passed.
- Close-time diff gate: `git diff --check` passed.
- Close-time docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md` passed.
- Final-close RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_validate_rejects_blank_current_turn_id_in_projection_health` failed with 1 expected blank-current-turn finding.
- Final-close GREEN: same blank-current-turn test passed.
- Final-close focused gate: `python3 -m pytest -q tests/test_projection_service.py tests/test_v1_cli.py tests/test_surface_inventory.py::SurfaceInventoryTests::test_runtime_platform_and_projection_inventory_cover_source_entrypoints` passed with 48 tests and 8 subtests.
- Final-close full regression: `python3 -m pytest -q` passed with 508 tests and 627 subtests.
- Final-close syntax gate: `python3 -m py_compile rpg_engine/projection_service.py rpg_engine/projections.py rpg_engine/save_validation.py rpg_engine/validation_issues.py rpg_engine/cli.py` passed.
- Final-close diff gate: `git diff --check` passed.
- Final-close docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md` passed.

### Completion Notes List

- Added stable `projection_health` evidence to `inspect_save_package()` with required projection status/effective status/version/current-turn alignment/artifact paths and outbox counts/non-done row details.
- Kept `authority_contract` roles unchanged: SQLite remains fact/audit authority, while projection artifacts, `projection_state`, and `outbox` remain derived/evidence.
- Strengthened validation reporting for missing, dirty, refreshing, failed, stale, behind, pending outbox, failed outbox, JSONL drift, snapshot drift, cards drift, and FTS drift without reading facts back from derived artifacts.
- Expanded `projection repair` CLI output to include `ProjectionReport` evidence: profile, requested/skipped names, requested/global dirty/failed/stale, timestamps, duration, artifacts, and errors.
- Updated canonical Save/Campaign, data model, CLI, and MCP docs for `projection_health` and repair evidence output; no MCP repair surface was added.
- Fixed review findings by requiring `meta.current_turn_id`, reporting missing/malformed outbox as unhealthy evidence, making targeted repair expose unrelated failed outbox work, and preserving projection error codes when outbox last errors mention `events.jsonl`.
- Fixed re-review findings by making `projection_state` health schema-tolerant, classifying unknown projection statuses as invalid, classifying unknown outbox statuses as malformed, and rendering outbox `last_error`/timestamp evidence in CLI and Markdown reports.
- Fixed third-rerun findings by returning failed repair evidence when `projection_state` is missing, malformed, invalid, or duplicated; preserving stored stale status; rejecting views as required tables; classifying missing outbox ids; keeping event-log errors ahead of embedded outbox text; and sanitizing repair text output.
- Fixed close-time review findings by keeping repair text `global_failed` evidence to one aggregate key and preserving the stable `projection_health.errors` shape when health is unavailable.
- Fixed final close-time current-turn handling by treating blank `meta.current_turn_id` as missing inside projection health and projection validation.

### File List

- `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/cli-contracts.md`
- `docs/data-models.md`
- `docs/mcp-contracts.md`
- `docs/save-and-campaign-packages.md`
- `rpg_engine/cli.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/projections.py`
- `rpg_engine/save_validation.py`
- `rpg_engine/validation_issues.py`
- `tests/test_projection_service.py`
- `tests/test_v1_cli.py`

## Change Log

- 2026-07-07: Implemented projection/outbox health evidence, repair evidence output, validation classification, focused regression tests, and canonical documentation updates; status set to review.
- 2026-07-07: Applied all code-review patch findings for current-turn health, outbox missing/malformed evidence, targeted repair outbox reporting, and outbox error-code classification; status set to done.
- 2026-07-07: Applied re-review patch findings for malformed projection_state schemas, invalid statuses, unknown outbox statuses, and complete outbox detail rendering; status remains done.
- 2026-07-07: Applied third-rerun review patch findings for repair evidence, projection_state/outbox schema edge cases, event-log classification, and repair output sanitization; status remains done.
- 2026-07-07: Applied close-time review patch findings for duplicate repair evidence keys and unavailable projection_health error shape; status remains done.
- 2026-07-07: Applied final close-time patch for blank current-turn projection health handling; status remains done.
