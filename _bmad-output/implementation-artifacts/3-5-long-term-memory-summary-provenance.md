---
baseline_commit: 872e83dc2beec34094cdeb466941823f0447ecd1
---

# Story 3.5: Long-Term Memory Summary Provenance

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 long-running game host，
我希望 memory summaries 基于 evidence 并带 freshness 信息，
从而让 AI 可以继续长期 campaign，而不会用摘要替代权威事实。

## 验收标准

1. 给定 memory summary 被创建或刷新，当它被存储时，它记录 source turns、source events、freshness 或 staleness metadata、visibility mode 和 summary type，并且明确标记为 derived context，而不是 authoritative fact。
2. 给定 summary 与当前 SQLite facts 冲突，当 context assembly 或 diagnostics 评估它时，authoritative facts 胜出，并且 summary 被标记为 stale、omitted，或进入 advisory review workflow。
3. 给定 resident AI 不可用，当长期游玩继续时，既有 deterministic summaries、snapshots、recent events 或较低质量 fallback context 仍可用，并且缺少 summary refresh 不会阻塞 gameplay fact submission。

## 任务 / 子任务

- [x] 扩展 memory summary 存储合同与迁移。 (AC: 1)
  - [x] 新增向后兼容 schema migration（当前序列到 `0008_intent_joiner_message_only.sql`），为 `memory_summaries` 增加 summary provenance/freshness 字段；同时更新 `rpg_engine/memory.py::ensure_memory_tables()`，让旧测试库和未迁移库也能安全补齐缺失列。
  - [x] 字段必须覆盖 `summary_type`、`visibility_mode`、`freshness_status` 或等价状态、freshness/staleness evidence、derived authority 标记，以及 source turn/event evidence 的可检查形状；保留现有 `source_event_ids_json`、`source_turn_ids_json`、`valid_from_turn`、`valid_to_turn` 和 `updated_at` 兼容语义。
  - [x] 新增或更新 migration/status 测试，证明 fresh database、旧 database 和 in-memory helper path 都得到同一组 memory metadata columns。
  - [x] 不新增运行时依赖，不把 memory artifacts、reports、projection state 或 snapshots 提升为 gameplay fact authority。

- [x] 让 deterministic memory rebuild 写入 provenance、visibility 和 freshness metadata。 (AC: 1, 3)
  - [x] 更新 `build_day_memories()`、`build_world_memories()`、`build_character_memories()`、`build_project_memories()`、`build_faction_memories()` 或统一 record-normalization helper，使每条记录都有 summary type、visibility mode、source turns/events、freshness basis 和 derived-context authority evidence。
  - [x] `rebuild_memory_summaries()` 写入新增 metadata，并继续保持事务性：任一 bad record 失败时 rollback，不能留下半刷新 summary。
  - [x] `write_memory_report()` 渲染新增 metadata 的玩家安全版本，不能泄露 hidden subject、hidden id/name/summary 或 private AI reasoning。
  - [x] `memory rebuild` / projection refresh 仍是 derived projection 维护动作；缺少或失败的 memory refresh 不得阻塞 `player_turn`、`player_confirm` 或普通事实提交。

- [x] 在 context memory collector 中评估 freshness / conflict，并产生可审计 evidence。 (AC: 1, 2, 3)
  - [x] 更新 `find_relevant_memories()` / `find_player_safe_relevant_memories()` / `memory_loaded_items()`，让 loaded memory evidence 包含 source events/turns、summary type、visibility mode、freshness status、derived authority 和 omission/staleness reason。
  - [x] 当 summary 的 subject 已 archived、hidden-unavailable、缺失、`updated_turn_id` 晚于 summary evidence，或 source turn/event 已落后于当前事实时，player-safe context 不应把该 summary 当成当前事实；GM / maintenance 视图可看到脱敏 stale reason。
  - [x] 若 summary 与当前 SQLite facts 冲突，SQLite facts 和 access contracts 优先；summary 应被标记 stale 或 omitted，必要时通过 existing advisory/proposal/review path 记录后续处理，不允许 context collector 直接修正事实。
  - [x] 保留 Story 3.2 / 3.3 的 hidden boundary：memory/event 当前没有独立 hidden authority 时，player view 仍需跳过含 hidden entity refs 的 rows，并继续避免 SQL top-N hidden starvation。

- [x] 提供 deterministic fallback context 行为。 (AC: 3)
  - [x] 当 `memory_summaries` 表不存在、为空、schema 缺字段、projection memory stale/failed，或 resident AI / archivist suggestion 不可用时，context assembly 继续依赖 recent events、snapshots/current artifacts 或 lower-quality deterministic sections；缺失 memory summary 只能产生 missing/omitted evidence 或 diagnostics warning，不能阻塞 action/query/commit。
  - [x] `ContextBuildResult.completeness.missing_signal_evidence` 或 loaded/omitted item evidence 应能解释 memory summary 缺失、stale 或 lower-quality fallback 的原因。
  - [x] 不改变 `ContextBuildResult` 顶层字段名、`context_runs` / `context_items` 表结构或默认 audit opt-in 语义，除非本 story 同步测试和 canonical docs 证明必要。

- [x] 同步 canonical docs。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 的 `memory_summaries` 和 ContextBuildResult 说明，明确 summary 是 derived context evidence，带 source/freshness/visibility metadata，不覆盖 SQLite facts。
  - [x] 更新 `docs/architecture.md` 的上下文链路说明，声明 memory freshness/staleness 评估和 authoritative facts precedence。
  - [x] 更新 `docs/testing-and-quality-gates.md` 的 context / memory gate，列出 freshness、conflict、hidden boundary、fallback context 和 migration checks。
  - [x] 若 CLI `memory rebuild`、projection repair、MCP 或 prompt contract 的公开字段语义变化，同步 `docs/cli-contracts.md`、`docs/mcp-contracts.md` 或 `docs/prompt-contracts.md`；若无变化，在 Dev Agent Record 说明。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN memory provenance gate：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_rebuild_finds_subjects_filters_hidden_and_renders_reports tests/test_context_quality.py -p no:cacheprovider`
  - [x] Current-native visibility / context gate：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider`
  - [x] Runtime / projection fallback gate：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_projection_service.py tests/test_v1_cli.py -p no:cacheprovider`
  - [x] Campaign smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`
  - [x] Docs / syntax / quality：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md`、`python3 -m py_compile rpg_engine/memory.py rpg_engine/context/collectors.py rpg_engine/context_builder.py rpg_engine/migrations.py`、`python3 -m ruff check .`、`git diff --check`

### Review Findings

- [x] [Review][Decision] Pre-existing `uv.lock` ownership — resolved by user direction: keep `uv.lock` untracked and exclude it from this story commit/push.
- [x] [Review][Decision] Pre-existing investigation artifact ownership — resolved by user direction: keep `_bmad-output/implementation-artifacts/investigations/external-intent-authority-investigation.md` untracked and exclude it from this story commit/push.
- [x] [Review][Patch] Make `0009` additive migration idempotent when helper backfilled memory metadata first [`rpg_engine/migrations.py`]
- [x] [Review][Patch] Enforce `visibility_mode` for player memory lookup and player-safe memory report rows [`rpg_engine/memory.py`]
- [x] [Review][Patch] Treat migrated legacy summaries without reliable freshness evidence as stale instead of fresh [`rpg_engine/memory.py`]
- [x] [Review][Patch] Emit fallback evidence for empty memory tables and stale/dirty/failed memory projection state [`rpg_engine/memory.py`]
- [x] [Review][Patch] Include archived-subject stale omission evidence in maintenance/GM memory diagnostics [`rpg_engine/memory.py`]
- [x] [Review][Patch] Overfetch trusted memory lookup past stale rows so fresh rows are not starved [`rpg_engine/memory.py`]
- [x] [Review][Patch] Add top-level source to memory omitted item evidence [`rpg_engine/context/collectors.py`]
- [x] [Review][Patch] Correct focused gate test class name in story evidence [`_bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md`]
- [x] [Review][Patch] Redact projection `last_error` from player-visible memory fallback evidence [`rpg_engine/memory.py`]
- [x] [Review][Patch] Clamp derived-authority evidence to a consistent derived-context shape while preserving the applied `0009` migration checksum [`rpg_engine/memory.py`]
- [x] [Review][Patch] Omit subjectless legacy memory rows that lack reliable freshness/source evidence [`rpg_engine/memory.py`]
- [x] [Review][Patch] Scan memory source/freshness evidence for hidden references before player lookup [`rpg_engine/memory.py`]
- [x] [Review][Patch] Sanitize player omitted/missing memory evidence defensively when hidden refs are present [`rpg_engine/context/collectors.py`, `rpg_engine/context_builder.py`]
- [x] [Review][Patch] Include source/freshness evidence in storage-time `visibility_mode` calculation [`rpg_engine/memory.py`]
- [x] [Review][Patch] Clamp corrupt `derived_authority_json` rows back to derived-context invariants [`rpg_engine/memory.py`]
- [x] [Review][Patch] Cover native context hidden source/freshness evidence leakage in player view [`tests/test_current_native_context.py`]
- [x] [Review][Patch] Dereference opaque source event/turn rows during hidden evidence scans [`rpg_engine/memory.py`]
- [x] [Review][Patch] Restrict player-visible memory stale reasons to safe reason codes [`rpg_engine/context/collectors.py`, `rpg_engine/context_builder.py`]
- [x] [Review][Patch] Return only authority allowlist fields from corrupt/legacy `derived_authority_json` rows [`rpg_engine/memory.py`]
- [x] [Review][Patch] Treat `subject_hidden_unavailable` as non-player-safe oracle and map it to a generic memory omission reason [`rpg_engine/memory.py`]
- [x] [Review][Patch] Follow source event `turn_id` links and scan all source rows instead of truncating hidden evidence checks [`rpg_engine/memory.py`]
- [x] [Review][Patch] Clamp freshness evidence to an allowlist before loaded/omitted context evidence is emitted [`rpg_engine/context/collectors.py`, `rpg_engine/memory.py`]
- [x] [Review][Patch] Make current-native migration-state tests tolerate either pending or already-applied formal save migrations [`tests/test_current_native_package.py`]
- [x] [Review][Patch] Clamp allowlisted freshness evidence values to safe enum/id/list shapes [`rpg_engine/memory.py`]
- [x] [Review][Patch] Clamp provenance/freshness evidence values, source ids, loaded freshness turns, and rendered freshness status to player-safe shapes [`rpg_engine/memory.py`, `rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Add `tests/test_current_native_package.py` to the BMAD File List [`_bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md`]
- [x] [Review][Patch] Require the complete memory table schema and convert memory-only SQLite read failures into sanitized fallback evidence [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Fail closed when hidden source event/turn dereferencing cannot be verified [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat corrupt freshness status and unresolved freshness evidence as stale; strictly type boolean evidence [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Omit existing summaries when the memory projection is non-clean, outdated, misaligned, or unverifiable, while retaining sanitized fallback evidence [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Paginate stale-memory omission scans, honor `limit <= 0`, and prevent fallback evidence from exceeding the requested limit [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Validate existing additive migration columns for case-insensitive name and compatible type/null/default contracts before skipping [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Clamp summary types and expose only real, current-view-safe SQLite source/turn/subject references in player evidence and reports [`rpg_engine/memory.py`, `rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Chunk large source-turn lookups below SQLite bind limits and use deterministic turn ordering [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat missing or incomparable subject update turns as stale instead of silently fresh [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Detect legacy memory projections older than the provenance migration and include them in dirty-only repair without invalidating already rebuilt compatible saves [`rpg_engine/memory.py`, `rpg_engine/projection_service.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Capture one rebuild turn snapshot and leave ProjectionService lifecycle ownership intact; direct rebuild stays non-clean if the turn advances [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reuse complete freshness turn extraction during storage/read hidden-reference scans [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Make empty and hidden-only player memory sets emit the same generic fallback and avoid hidden existence oracles [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Sanitize provenance/freshness/authority metadata at the player row boundary, not only in downstream collectors [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Preserve missing legacy summary-type inference but map unknown non-empty values to canonical `unknown` [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Render player-safe source events/turns, freshness evidence, and derived authority in the memory report [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require compatible metadata/projection schema contracts, exactly one trustworthy projection row, and safe projection diagnostics [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Fail stale on future/incomparable turns, missing subject update turns, unresolved provenance, invalid/oversized ids, and deep/corrupt metadata JSON [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Parse turn ordering in UTC, ignore invalid timestamps, and short-circuit non-clean projection lookup with one health snapshot [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat absent and explicit `NULL` SQL defaults equivalently while rejecting authority-escalating or unknown default extensions [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Sanitize direct player omission reasons, projection turn evidence, and malformed summary ids at the row/collector boundary [`rpg_engine/memory.py`, `rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Surface memory-specific effective health in projection status and global reports [`rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Refuse to report a memory refresh item clean when effective memory health remains non-clean [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Update the canonical source tree migration range through `0009` [`docs/source-tree-analysis.md`]
- [x] [Review][Patch] Fail player hidden scans closed on corrupt, deep, BLOB, or structurally invalid provenance JSON [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require source event/turn rows and event-linked turns to have verifiable text/JSON shapes [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Validate every provenance/freshness turn against the authoritative current turn and derive freshness from the complete reference set [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject mixed-invalid evidence ids instead of silently retaining a valid subset [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Refresh legacy rows with source turns and fail stale on missing/corrupt `0009` timestamps unless every row proves a deterministic rebuild [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Enforce the complete base/metadata memory schema contract in helper and reader paths [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require `projection_state.name` to be the sole primary key under the complete projection schema contract [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat UTC normalization overflow as incomparable/stale instead of raising [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Bound memory query limits before SQLite binding and sanitize unrenderable omission ids [`rpg_engine/memory.py`, `rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Make projection lifecycle ownership explicit so direct rebuild reconciles orphaned `refreshing` state [`rpg_engine/memory.py`, `rpg_engine/projection_service.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Clarify that current-state tables own current fact authority while committed events provide provenance/audit evidence [`docs/data-models.md`]
- [x] [Review][Patch] Dirty memory in the same transaction when save patch mutates authoritative facts within the current turn [`rpg_engine/save_patch.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Initialize a missing memory projection row as dirty so status/repair cannot synthesize a clean provenance timestamp [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Rebuild player memory rows from an explicit field allowlist and canonicalize unknown/BLOB kinds [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Include source-turn location refs in hidden scans and fail closed on malformed location values [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject expired, not-yet-valid, and reversed summary validity windows independently of freshness evidence [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Allow non-conflicting additive projection-state columns while retaining strict known-column and sole-primary-key contracts [`rpg_engine/memory.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Require trusted deterministic rebuild markers to resolve every provenance reference and turn ordering [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Recheck the projection/current-turn snapshot before returning loaded or omitted memory rows [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Batch player source resolution and cap independent provenance references to prevent query amplification [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat non-integer/non-finite projection versions as stale without crashing diagnostics [`rpg_engine/projections.py`, `rpg_engine/memory.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Protect direct and service-managed memory refresh completion with a monotonic generation CAS so newer dirty state wins [`rpg_engine/memory.py`, `rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `tests/test_maintenance_tooling_coverage.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Include projection generation in lookup/context snapshots and discard rows across clean-dirty-clean ABA changes [`rpg_engine/memory.py`, `rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Validate and allowlist memory rows for every view so maintenance/GM BLOB rows cannot break context JSON [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require `memory_summaries.id` to be the sole BINARY primary key [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject additive memory/projection columns that block canonical insert/upsert while permitting safe nullable/defaulted extensions [`rpg_engine/memory.py`, `rpg_engine/projection_service.py`, `tests/test_maintenance_tooling_coverage.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Require exact BINARY canonical memory projection identity and mark NOCASE aliases stale [`rpg_engine/memory.py`, `rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Validate trusted rebuild row subjects, subject evidence, visibility, freshness, and validity before skipping migration repair [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Decouple validity bounds from freshness provenance so future end bounds remain valid and future start bounds are not-yet-valid [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`, `tests/test_current_native_visibility.py`]
- [x] [Review][Patch] Add a revision-aware final context snapshot gate that removes stale memory sections, loaded evidence, and memory-derived plot signals before bounded result rebuild [`rpg_engine/context/collectors.py`, `rpg_engine/context_builder.py`, `tests/test_current_native_context.py`]
- [x] [Review][Patch] Transfer refresh ownership to the clean CAS generation and reconcile post-refresh non-clean effective health without reporting the item refreshed [`rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Exclude validity bounds from freshness evidence and require subject evidence to bind the row subject and authoritative update turn [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject invalid dynamic row types before trusting deterministic rebuild provenance [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Match schema identifiers with SQLite ASCII semantics so Unicode pseudo-columns cannot hide write-blocking extensions [`rpg_engine/memory.py`, `rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject non-canonical UNIQUE, expression/partial indexes, generated columns, extra foreign keys, CHECK constraints, and triggers that can tighten canonical writes [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Make generation allocation total at the maximum timestamp and verify the real UnitOfWork save path cannot roll back authoritative facts [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Register generation/CAS helpers as internal non-surface APIs [`rpg_engine/surface_inventory.py`]
- [x] [Review][Patch] Isolate projection metadata writes with savepoints so malformed schema, constraints, or triggers cannot roll back UnitOfWork or save-patch facts [`rpg_engine/projections.py`, `tests/test_projection_service.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject executable defaults, every expression/partial/custom-collation index, commented CHECK constraints, and main/TEMP triggers in insert-compatible schema checks [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Add a parseable opaque nonce to projection generation tokens so maximum-timestamp repair cannot reuse a stale owner token [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Validate every context retry candidate and freeze repeated generation churn into one generic unstable-memory fallback [`rpg_engine/context/collectors.py`, `rpg_engine/context_builder.py`, `tests/test_current_native_context.py`]
- [x] [Review][Patch] Run budget filtering on copied render state so retries preserve non-memory plot signals and collector evidence [`rpg_engine/context_builder.py`, `tests/test_current_native_context.py`]
- [x] [Review][Patch] Emit fixed JSON-safe maintenance omission evidence for structurally invalid memory rows without creating a player existence oracle [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Acquire direct-rebuild refreshing ownership before table writes and reconcile table/report failures to failed without overwriting newer dirty state [`rpg_engine/memory.py`, `rpg_engine/projections.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Mark superseded failed refresh items stale and exclude errored clean items from refreshed reporting [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Render incompatible projection schema diagnostics without initialization writes and keep canonical memory aliases stale across text and machine-readable reports [`rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Bind additive migrations explicitly to `main`, reject TEMP shadowing, and reject existing columns with write-blocking constraints before recording `0009` [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Match canonical table and trigger identities with SQLite ASCII case-insensitive semantics and fail closed when canonical table SQL is unavailable [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require the complete canonical foreign-key/action contract and the canonical `(kind, subject_id)` memory lookup index [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Compare JSON authority defaults with strict boolean types rather than Python numeric/boolean equality [`rpg_engine/memory.py`, `rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Prevalidate every existing metadata column before additive DDL so a failed helper upgrade cannot leave a partially upgraded schema [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Decouple validity bounds from freshness provenance and require subjectless summaries to carry non-validity freshness evidence [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Enforce player visibility and hidden-ID safety at direct row/render/omitted-item boundaries, collapsing hidden omissions to one generic signal [`rpg_engine/memory.py`, `rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reconcile direct rebuilds without a trustworthy current turn to dirty instead of leaving projection ownership refreshing [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Register `mark_projection_dirty_if_unchanged` as an internal non-surface API and restore the surface inventory gate [`rpg_engine/surface_inventory.py`, `tests/test_surface_inventory.py`]
- [x] [Review][Patch] Treat every stored projection version unequal to the supported version as stale [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Qualify projection-state and outbox reads/writes to `main` so TEMP tables cannot hijack refresh, status, or queue processing [`rpg_engine/projection_service.py`, `rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Serialize projection publication so a superseded refresher cannot overwrite newer database rows or artifacts after losing generation ownership [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Move refresh-ownership acquisition inside structured failure handling and preserve a report instead of propagating acquisition errors [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Preserve caller transaction semantics, clean every savepoint on non-SQL exceptions, and return false when `mark_projection_failed` updates no row [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Reconcile final item/refreshed reporting against final effective projection health [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Bind context omission evidence to the same stable projection snapshot and keep player fallback diagnostics generic [`rpg_engine/context/collectors.py`, `tests/test_current_native_context.py`]
- [x] [Review][Patch] Make memory helper table/index creation atomic so an incompatible existing schema cannot retain a newly created canonical index [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Ignore quoted/commented SQL text when detecting executable CHECK constraints in additive migration compatibility checks [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject table-level custom collation that changes additive metadata-column identity or comparison semantics [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Validate write-blocking target-table constraints before adding a missing metadata column, not only when the column already exists [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Qualify the migration ledger to `main.schema_migrations` so a TEMP ledger cannot hide or forge pending `0009` state [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Detect hidden entity names/aliases embedded in otherwise legal memory IDs before player lookup, rendering, or report publication [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Refuse direct memory-report publication when any authoritative memory table is shadowed in TEMP [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat a lost direct-rebuild clean/dirty CAS as a failed superseded rebuild instead of reporting success [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require exact deterministic derived-authority JSON before trusting rows as a completed rebuild [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject non-finite JSON constants such as NaN and Infinity from memory metadata [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Bound total rows scanned while overfetching visible or omitted memory candidates [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Require freshness evidence validity bounds to exactly match the stored bounds, including explicit absence [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Bind direct memory-report rows and atomic publication to one stable projection snapshot [`rpg_engine/memory.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Reject TEMP shadowing for every migration statement target, not only additive ALTER TABLE targets [`rpg_engine/migrations.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Decouple projection-state metadata from outbox availability and preserve fail-closed memory invalidation when optional queue state is absent [`rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `rpg_engine/save_patch.py`, `tests/test_projection_service.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Make projection metadata writes commit self-owned transactions and convert every ordinary callback/setup/cleanup failure into a clean false result [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Return aggregate success from multi-projection clean transitions instead of silently discarding partial failures [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Validate player-safe omission overrides instead of trusting caller-supplied reason/signal strings [`rpg_engine/context_builder.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Collapse hidden memory omissions to one generic missing-signal advisory as well as one omitted item [`rpg_engine/context_builder.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Fail closed when collected memory summaries have no projection snapshot [`rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Re-evaluate row freshness immediately before rendering or recording loaded memory evidence [`rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Assign distinct opaque fallback IDs to multiple malformed non-hidden omissions [`rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Treat unknown projection names/statuses and every non-canonical case alias as stale [`rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Report projection version mismatches with `!=` semantics that match effective-status evaluation [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Add bounded acquisition timeouts to local and cross-process projection publication locks [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Process the events outbox under the same publication lock as full `events_jsonl` rewrites [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Reconcile dirty-only reports against the original requested set when a skipped projection becomes dirty after eligibility sampling [`rpg_engine/projection_service.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Make an empty projection-name invalidation request a true no-op [`rpg_engine/projections.py`, `tests/test_projection_service.py`]
- [x] [Review][Patch] Emit canonical `stale` status evidence for repeated unstable memory-generation fallback [`rpg_engine/context/collectors.py`, `tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Prove the fresh full migration chain and current-native package discovery include `0009` and the complete memory metadata contract [`tests/test_maintenance_tooling_coverage.py`, `tests/test_current_native_package.py`]
- [x] [Review][Patch] Prove a rebuild failure after a valid new row restores all prior summaries and leaves no partial refresh [`tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Prove a late `0009` failure rolls back every earlier additive column and the migration marker [`tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Exercise publication serialization across independent processes, not only threads [`tests/test_projection_service.py`]
- [x] [Review][Patch] Cover the clean-and-empty memory projection fallback path independently of non-clean projection short-circuiting [`tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Verify end-to-end context retains lower-quality authoritative sections when memory refresh is unavailable [`tests/test_maintenance_tooling_coverage.py`]
- [x] [Review][Patch] Exercise real outbox processing while a TEMP outbox attempts to shadow the canonical queue [`tests/test_projection_service.py`]
- [x] [Review][Patch] Exercise generation ownership loss with a real second SQLite connection [`tests/test_projection_service.py`]
- [x] [Review][Patch] Re-run all Story gates and final full-suite verification after the review patches, then synchronize Story/sprint to done [`_bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`]

## 开发说明

### 来源上下文

- Epic 3 要求 `ContextBuildResult` 成为 prompt/render/query/advisory 的 inspectable context contract，并支持长期游玩的 summary recall。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 3.5 的 AC 明确要求 memory summary 记录 source turns、source events、freshness/staleness metadata、visibility mode、summary type，并保持 derived context 语义。来源：`_bmad-output/planning-artifacts/epics.md#Story 3.5`。
- PRD FR-12 要求 summaries 基于 evidence、可追溯到 stored facts/events、不能覆盖 authoritative facts，并且 freshness/staleness 可见。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Architecture AD-5 要求 `ContextBuildResult` 包含 `memory_summaries`、visibility、provenance、budget evidence 和 omitted/missing signals；AD-2 / AD-6 限定 AI/context summary 只能是 advisory 或 derived，不拥有 fact authority。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- `docs/data-models.md` 当前声明 `memory_summaries` 是 long-term memory summaries，但没有独立 visibility/freshness schema；events / memory rows 目前没有独立 hidden authority，player view 必须通过 hidden entity refs 跳过或 redaction。来源：`docs/data-models.md`。

### 当前实现状态

- `rpg_engine/resources/migrations/0001_init.sql` 和 `rpg_engine/memory.py::ensure_memory_tables()` 当前 `memory_summaries` 字段包括 `id`、`kind`、`subject_id`、`title`、`summary`、`key_points_json`、`source_event_ids_json`、`source_turn_ids_json`、`valid_from_turn`、`valid_to_turn`、`updated_at`；缺少显式 `visibility_mode`、summary type、freshness/staleness 和 derived authority 字段。
- 当前 migration 序列到 `0008_intent_joiner_message_only.sql`；如果扩展 `memory_summaries` schema，应新增 `0009_*` migration，并让 `apply_pending_migrations()` / fresh init / helper table creation 路径一致。
- `rebuild_memory_summaries()` deterministic 地重建 day/world/character/project/faction summaries，并写 `reports/memory-current.md`；它已经在事务中 delete/insert，失败时 rollback。
- `find_relevant_memories()` 和 `find_player_safe_relevant_memories()` 按 subject、title、summary、key_points 和 visibility view 查询；player-safe path 当前会 overfetch 并跳过 hidden refs，避免 hidden rows 饿死 safe recall。
- `collect_memory_summaries()`、`memory_summaries_section()` 和 `memory_loaded_items()` 已把 memory rows 纳入 context，但 loaded item evidence 只包含 id/kind/title/reason/priority/depth；缺少 source/freshness/derived authority evidence。
- `ProjectionService` 将 `memory` 作为 derived projection 刷新；`rpg_engine/projections.py` 支持 `stale` projection status。这个 status 是 projection health，不等同 summary 与事实冲突的 staleness，需要在 story 中保持语义区分。

### 前序故事情报

- Story 3.1 固化了 `ContextBuildResult`、`context_runs` / `context_items` audit 和新增 context source 的 visibility/provenance/budget metadata 要求。
- Story 3.2 加固了 player-safe context、ordinary query、scene output 和 player-safe AI prompt 的 hidden 边界；events / memory summaries 当前没有独立 hidden visibility 字段时，player view 必须跳过含 hidden entity refs 的 rows。
- Story 3.3 加固了 FTS、snapshots、cards、onboarding 等派生玩家视图；memory report / projection output 不能重新引入 hidden 泄漏。
- Story 3.4 新增 relationship/progress/plot signal collectors，并明确 plot signals 可以从 visible memory summaries 派生，但仍是 `advisory_only` context evidence；本 story 不应破坏 3.4 的 collector 顺序和 item evidence 结构。
- 最近提交 `872e83d Complete story 3.4 context signals` 对 `context/collectors.py` 和 `context_builder.py` 改动较大；实现前先读这些文件的当前版本，不要从旧心智继续开发。

### 架构合规要求

- 本 story 触碰 context assembly、memory projection、SQLite schema/migration、visibility 和 derived fact authority，按 BMAD 视为高风险 context / data-model boundary 变更；必须先写 focused tests，再实现最小改动。
- `memory_summaries`、`reports/memory-current.md`、snapshots、cards 和 projection state 都是 derived/read-model evidence，不是 Save SQLite current facts；summary 不能覆盖 entity、relationship、progress、meta 或 event authority。
- Player-safe path 必须在 collection/query 阶段过滤 hidden / GM-only material；render redaction 只能作为 defense-in-depth。
- GM / maintenance 视图可以检查 stale reason 和 hidden/structural evidence，但 player-safe evidence 不得暴露 hidden summary、hidden subject、hidden id/name、private AI reasoning 或 hidden-count oracle。
- 不新增 resident AI coordinator、proposal queue apply/revert、AI latency policy、preflight cache、MCP profile gate 或 player confirmation flow 的行为；如实现发现必须触碰这些边界，应按 HALT / correct-course 处理。

### 相关文件

- `rpg_engine/memory.py`：memory summary table creation、deterministic rebuild、relevance lookup、rendering、report writing。
- `rpg_engine/resources/migrations/0001_init.sql` 和新增 `0009_*.sql`：SQLite schema contract。
- `rpg_engine/migrations.py`、`rpg_engine/resource_paths.py`：migration discovery/status/apply。
- `rpg_engine/context/collectors.py`：`memory_summaries` collector、loaded item evidence、plot signal memory source。
- `rpg_engine/context_builder.py`：ContextBuildResult evidence、missing-signal evidence、visibility invariants、budget omission。
- `rpg_engine/projection_service.py`、`rpg_engine/projections.py`：memory projection refresh and stale/dirty health semantics。
- `rpg_engine/visibility.py`、`rpg_engine/redaction.py`：hidden / GM-only filtering 与 defense-in-depth redaction。
- `tests/test_maintenance_tooling_coverage.py`：memory rebuild/report focused tests。
- `tests/test_current_native_context.py`：current-native context/audit regression。
- `tests/test_current_native_visibility.py`：hidden memory/event starvation 与 player-safe leakage regression。
- `tests/test_context_quality.py`：collector metadata / stable order / evidence quality tests。
- `tests/test_projection_service.py`、`tests/test_v1_cli.py`：projection / CLI memory repair behavior。

### 测试要求

最小 focused gates：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_rebuild_finds_subjects_filters_hidden_and_renders_reports tests/test_context_quality.py -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_projection_service.py tests/test_v1_cli.py -p no:cacheprovider
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md
python3 -m py_compile rpg_engine/memory.py rpg_engine/context/collectors.py rpg_engine/context_builder.py rpg_engine/migrations.py
python3 -m ruff check .
git diff --check
```

如实现触碰 SaveManager commit/pending、MCP profile exposure、platform sidecar/prewarm、AI intent/preflight、Campaign/Save schema beyond memory table、archive/export 或 prompt artifact 文件，再追加对应高风险 gates 并同步 canonical docs；否则记录未触碰原因。

### 残余风险与边界

- 本 story 不要求 Resident AI Advisory Envelope，这是 Story 4.4 / 4.5。
- 本 story 不要求 operator-facing context budget diagnostics UX，这是 Story 3.6。
- 本 story 不要求跨 Campaign context 与 player-safe loop smoke，这是 Story 3.7。
- 本 story 不要求 proposal queue apply/revert rules，这是 Story 5.7；若 stale memory 进入 review，只能使用现有 advisory/proposal path 并保留 non-authoritative 语义。
- 如果发现当前 memory summary schema 需要独立 free-text hidden visibility，不能静默添加 player-readable字段；必须先设计结构化 visibility / sensitivity 字段和 migration，并覆盖 hidden leakage tests。

### 最新技术信息

无需外部 Web research。本 story 使用仓库当前 Python 3.11+、stdlib `sqlite3` / `json` / `dataclasses`、pytest、ruff、现有 migration 系统、`ContextBuildResult`、visibility/redaction helpers 和 current-native fixtures；不要新增运行时依赖。

## Project Structure Notes

- 保持 memory summary 逻辑集中在 `rpg_engine/memory.py`，context 侧只消费稳定 helper / rows，不在 collector 中复制 rebuild 或 schema migration 逻辑。
- migration SQL 放在 `rpg_engine/resources/migrations/`，并由现有 `migration_resource_files()` 自动发现；不要维护第二套手写 migration 清单。
- 不在 CLI/MCP adapter 中实现第二套 memory freshness 判定；公开入口应消费 `memory.py`、`ProjectionService` 或 `ContextBuildResult` 的结果。
- 所有 current-native 写入测试必须使用 temporary save copy；正式 current save package 只读。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/3-1-contextbuildresult-contract-and-audit.md`
- `_bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`
- `_bmad-output/implementation-artifacts/3-3-派生玩家视图与检索产物的隐藏信息边界.md`
- `_bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/source-tree-analysis.md`
- `docs/testing-and-quality-gates.md`
- `pyproject.toml`
- `rpg_engine/memory.py`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/resources/migrations/0001_init.sql`
- `rpg_engine/migrations.py`
- `rpg_engine/projection_service.py`
- `tests/test_maintenance_tooling_coverage.py`
- `tests/test_current_native_context.py`
- `tests/test_current_native_package.py`
- `tests/test_current_native_visibility.py`
- `tests/test_context_quality.py`
- `tests/test_projection_service.py`
- `tests/test_v1_cli.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED memory schema/rebuild gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_table_schema_backfills_provenance_and_freshness_columns tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_rebuild_finds_subjects_filters_hidden_and_renders_reports -p no:cacheprovider` -> failed as expected: missing metadata columns / `summary_type`.
- GREEN memory schema/rebuild gate: same command -> 2 passed.
- RED stale memory context gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py::CurrentNativeContextTests::test_stale_memory_summary_is_omitted_when_subject_fact_is_newer -p no:cacheprovider` -> failed as expected before omission evidence existed; second RED failed until `missing_signal_evidence` included memory stale evidence.
- GREEN stale memory context gate: same command -> 1 passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_rebuild_finds_subjects_filters_hidden_and_renders_reports tests/test_context_quality.py -p no:cacheprovider` -> 20 passed, 20 subtests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py::CurrentNativeVisibilityTests::test_player_safe_context_excludes_hidden_probe_while_gm_context_can_read_it -p no:cacheprovider` -> 1 passed after updating the expected memory visibility invariant.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider` -> 27 passed, 8906 subtests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_projection_service.py tests/test_v1_cli.py -p no:cacheprovider` -> 116 passed, 59 subtests passed.
- `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` -> OK.
- `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` -> OK.
- `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md` -> checked 87 markdown files; local links ok.
- `python3 -m py_compile rpg_engine/memory.py rpg_engine/context/collectors.py rpg_engine/context_builder.py rpg_engine/migrations.py` -> passed.
- `python3 -m ruff check .` -> All checks passed.
- `git diff --check` -> passed.
- Review patch regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_metadata_migration_tolerates_helper_backfilled_columns tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_legacy_memory_rows_without_freshness_turn_are_omitted_when_subject_changed tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_visibility_mode_blocks_player_lookup_and_report_rows tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_fallback_evidence_for_empty_table_and_stale_projection tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_omissions_include_archived_subject_for_maintenance_view tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_trusted_memory_lookup_overfetches_past_stale_rows -p no:cacheprovider` -> 6 passed.
- Review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_table_schema_backfills_provenance_and_freshness_columns tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_rebuild_finds_subjects_filters_hidden_and_renders_reports tests/test_current_native_context.py::CurrentNativeContextTests::test_stale_memory_summary_is_omitted_when_subject_fact_is_newer tests/test_context_quality.py -p no:cacheprovider` -> 22 passed, 20 subtests passed.
- Second review patch regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_metadata_migration_tolerates_helper_backfilled_columns tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_legacy_memory_rows_without_freshness_turn_are_omitted_when_subject_changed tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_visibility_mode_blocks_player_lookup_and_report_rows tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_fallback_evidence_for_empty_table_and_stale_projection tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_omissions_include_archived_subject_for_maintenance_view tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_trusted_memory_lookup_overfetches_past_stale_rows tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_subjectless_legacy_memory_without_freshness_evidence_is_omitted tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_player_memory_lookup_skips_hidden_refs_in_source_evidence tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_player_memory_projection_fallback_redacts_last_error -p no:cacheprovider` -> 9 passed.
- Second review patch focused/static gates: focused memory/context gate -> 22 passed, 20 subtests passed; `py_compile` / `ruff` / `git diff --check` -> passed.
- Third review patch regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_metadata_migration_tolerates_helper_backfilled_columns tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_legacy_memory_rows_without_freshness_turn_are_omitted_when_subject_changed tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_visibility_mode_blocks_player_lookup_and_report_rows tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_fallback_evidence_for_empty_table_and_stale_projection tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_omissions_include_archived_subject_for_maintenance_view tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_trusted_memory_lookup_overfetches_past_stale_rows tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_subjectless_legacy_memory_without_freshness_evidence_is_omitted tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_player_memory_lookup_skips_hidden_refs_in_source_evidence tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_player_memory_projection_fallback_redacts_last_error tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_metadata_visibility_scans_source_evidence tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_row_authority_clamps_corrupt_rows_to_derived_context tests/test_current_native_context.py::CurrentNativeContextTests::test_player_context_memory_evidence_does_not_leak_hidden_source_refs -p no:cacheprovider` -> 12 passed.
- Fourth review patch regression/static gates: same regression gate -> 12 passed; `py_compile` / `ruff` / `git diff --check` -> passed.
- Fourth review patch current-native gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider` -> 28 passed, 8906 subtests passed.
- Final review patch regression/static gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_hidden_scan_checks_all_source_rows_and_event_turns tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_freshness_evidence_and_player_reasons_are_allowlisted tests/test_current_native_context.py::CurrentNativeContextTests::test_player_context_memory_evidence_does_not_leak_hidden_source_refs tests/test_current_native_package.py::CurrentNativePackageTests::test_current_save_validate_surfaces_pending_migrations_without_hiding_other_health tests/test_current_native_package.py::CurrentNativePackageTests::test_pending_migrations_apply_cleanly_on_temp_copy -p no:cacheprovider` -> 5 passed; `py_compile` / `ruff` / `git diff --check` -> passed.
- Final evidence value clamp gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py::MemoryBackupAndWorldSettingCoverageTests::test_memory_freshness_evidence_and_player_reasons_are_allowlisted tests/test_current_native_context.py::CurrentNativeContextTests::test_player_context_memory_evidence_does_not_leak_hidden_source_refs -p no:cacheprovider` -> 2 passed; `py_compile` / `ruff` / `git diff --check` -> passed.
- Final three-way review RED gate: ten focused review regressions -> 15 failures and 1 pass, reproducing incompatible additive columns, partial schema reads, projection-state bypass, corrupt freshness, unresolved provenance ids, summary-type leakage, hidden-source fail-open, omission starvation, and nondeterministic turn ordering.
- Final three-way review GREEN memory gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py -p no:cacheprovider` -> 47 passed, 11 subtests passed.
- Final three-way review cross-module gates: context/entity/P0 -> 47 passed, 33 subtests passed; runtime/projection/CLI -> 116 passed, 59 subtests passed; current-package/migration/official-example -> 21 passed, 40 subtests passed; `py_compile` / `ruff` / `git diff --check` -> passed.
- Second three-way review RED gate: eight grouped regressions -> 8 failures, reproducing migration-default escalation, projection/schema corruption, rebuild turn race, hidden freshness visibility, hidden-only oracle/raw player metadata, future/unresolved/deep evidence, and non-clean query amplification.
- Second three-way review GREEN memory gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py -p no:cacheprovider` -> 55 passed, 11 subtests passed.
- Second three-way review cross-module gates: context/entity/P0 -> 47 passed, 33 subtests passed; runtime/projection/CLI -> 116 passed, 59 subtests passed; current-native context/visibility/package/write-safety -> 43 passed, 8923 subtests passed; campaign/docs/static gates -> passed.
- Third three-way review RED gate: ten focused regressions -> 10 expected failures after fixture correction, reproducing legacy migration marker gaps, orphaned refresh ownership, incomplete turn validation, corrupt/BLOB provenance fail-open, raw player omission metadata, incomplete schema/PK contracts, UTC overflow, unbounded limits, and effective-health diagnostics drift.
- Third three-way review GREEN gate: the same ten focused regressions -> 10 passed.
- Third three-way review maintenance gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_maintenance_tooling_coverage.py -p no:cacheprovider` -> 64 passed, 11 subtests passed.
- Third three-way review cross-module gates: context/entity/P0 -> 47 passed, 33 subtests passed; runtime/projection/CLI -> 117 passed, 59 subtests passed; current-native context/visibility/package/write-safety -> 43 passed, 8923 subtests passed; campaign/docs/static gates -> passed.
- Fourth three-way review pre-patch full suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 686 passed, 9635 subtests passed; findings landed afterward, so this is preliminary evidence only.
- Fourth three-way review RED gate: ten focused regressions -> 10 failures, reproducing same-turn fact drift, missing-state clean synthesis, player extension/kind leakage, hidden source locations, invalid validity windows, additive-column repair failure, unresolved trusted markers, projection snapshot TOCTOU, provenance query amplification, and infinite projection versions.
- Fourth three-way review GREEN gate: the same ten focused regressions -> 10 passed.
- Fourth three-way review maintenance/projection gates: maintenance -> 71 passed, 11 subtests passed; projection/CLI -> 120 passed, 59 subtests passed.
- Fourth three-way review cross-module gates: context/entity/P0 -> 47 passed, 33 subtests passed; current-native context/visibility/package/write-safety -> 43 passed, 8923 subtests passed; campaign/docs/static gates -> passed.
- Fifth three-way review pre-patch full suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 696 passed, 9635 subtests passed; findings landed afterward, so this is preliminary evidence only.
- Fifth three-way review RED gate: nine focused generation/schema/all-view/validity regressions -> 9 failures after correcting one migration-time fixture, reproducing dirty overwrite, clean ABA, maintenance BLOB rows, composite PK, required extensions, NOCASE aliases, missing trusted subjects, and validity/freshness coupling.
- Fifth three-way review GREEN gate: the same nine focused regressions -> 9 passed.
- Fifth three-way review maintenance/projection gates: maintenance -> 77 passed, 11 subtests passed; runtime/projection/CLI -> 123 passed, 59 subtests passed.
- Fifth three-way review cross-module gates: context/entity/P0 -> 47 passed, 33 subtests passed; current-native context/visibility/package/write-safety -> 43 passed, 8923 subtests passed after upgrading two visibility fixtures to the current memory metadata contract; campaign/docs/static gates -> passed.
- Sixth three-way review RED gate: eight grouped regressions reproduced final context generation mixing, post-refresh stale-as-clean reporting, bound-only freshness, unrelated subject evidence, trusted maintenance BLOB rows, Unicode/write-blocking schema extensions, non-canonical UNIQUE state, and maximum-generation fact rollback.
- Sixth three-way review GREEN gate: focused projection -> 3 passed; focused memory/schema -> 4 passed; real dual-connection current-native context -> 1 passed.
- Sixth three-way review maintenance/projection gates: maintenance -> 80 passed, 11 subtests passed; runtime/projection/CLI -> 126 passed, 59 subtests passed; surface inventory -> 21 passed, 221 subtests passed.
- Sixth three-way review cross-module gates: context/entity/P0 -> 48 passed, 33 subtests passed; current-native context -> 16 passed, 16 subtests passed; current-native visibility/package/write-safety -> 28 passed, 8907 subtests passed.
- Seventh three-way review RED gate: eleven focused regressions reproduced fact rollback on malformed projection metadata, executable schema bypasses, maximum-token ABA, unvalidated context retry exhaustion, plot-state mutation, missing invalid-row diagnostics, direct-rebuild clean leakage, superseded refresh misreporting, crashing status diagnostics, and alias status drift.
- Seventh three-way review GREEN gate: projection regressions -> 7 passed; memory/schema regressions -> 5 passed; dual-connection context regressions -> 2 passed; surface inventory -> 21 passed, 221 subtests passed.
- Seventh three-way review module gates: maintenance -> 83 passed, 11 subtests passed; projection service -> 24 passed; context quality -> 19 passed, 20 subtests passed; current-native context -> 17 passed, 16 subtests passed.
- Eighth three-way review triage: 0 decision-needed, 16 patch, 0 defer, 18 dismissed after cross-layer deduplication; all explicit patch findings were applied under the user's standing authorization.
- Eighth three-way review focused GREEN gates: memory/schema -> 88 passed, 11 subtests passed; projection service -> 30 passed; real dual-connection context snapshot -> 1 passed; surface inventory -> passed.
- Eighth three-way review cross-module gates: runtime/projection/CLI -> 137 passed, 59 subtests passed; package/surface -> 29 passed, 238 subtests passed; context/current-native visibility -> 50 passed, 8926 subtests passed; `py_compile` / focused Ruff / `git diff --check` -> passed.
- Ninth three-way review triage: 0 decision-needed, 38 patch, 0 defer, 21 dismissed after cross-layer deduplication; all explicit patch findings were applied under the user's standing authorization.
- Ninth review focused GREEN gates: memory/projection -> 136 passed, 11 subtests passed; current-native package -> 8 passed, 17 subtests passed; surface inventory -> 21 passed, 221 subtests passed; two upgraded current-native validity fixtures -> 2 passed.
- Ninth review campaign/docs/static gates: both canonical example campaigns validated; 166 Markdown files passed local-link validation; repository Ruff and `git diff --check` passed.
- Final post-patch full suite: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 751 passed, 9635 subtests passed in 469.43s.

### Completion Notes List

- Added `0009_memory_summary_provenance.sql` and `ensure_memory_tables()` backfill for memory summary metadata columns: summary type, visibility mode, freshness status/turn/reason/evidence, and derived authority.
- Updated deterministic memory rebuild to write derived authority, source/freshness evidence, visibility mode, and summary type while preserving rollback behavior.
- Added stale memory filtering and omitted item evidence so outdated subject summaries do not enter player-safe context when SQLite facts are newer.
- Added memory omission entries to `ContextBuildResult.completeness.missing_signal_evidence` as advisory fallback evidence, without blocking action/query/commit.
- Applied review patches for idempotent helper/migration ordering, player visibility metadata enforcement, legacy freshness inference, empty/projection fallback evidence, archived-subject omissions, and trusted lookup overfetch.
- Applied second-review patches for player-safe projection error redaction, consistent derived-authority defaults, subjectless legacy freshness evidence, and hidden refs in source/freshness evidence.
- Applied third-review patches for player-safe omitted/missing evidence sanitization, storage-time source/freshness visibility scanning, corrupt authority clamping, and native context hidden evidence regression coverage.
- Applied fourth-review patches for opaque source event/turn hidden scans, player-safe stale reason codes, and authority evidence allowlisting.
- Applied final-review patches for hidden-subject reason de-oracling, full source event/turn scanning, freshness evidence allowlisting, and current-native migration-state test robustness.
- Applied final value-level provenance clamp patch so player-visible source ids, freshness evidence/status/turn metadata, and report output cannot carry arbitrary private text through allowlisted fields.
- Applied final three-way review patches for full-schema fallback, projection-health enforcement, fail-closed provenance/freshness verification, canonical summary types, stale-omission pagination, additive-column compatibility, chunked turn lookup, and deterministic/unverifiable turn ordering.
- Applied second three-way review patches for migration-aware projection repair, rebuild turn snapshots, strict schema/visibility/provenance contracts, hidden-oracle resistance, bounded metadata parsing, UTC turn ordering, player-row sanitization, and complete report provenance/authority.
- Applied third three-way review patches for complete provenance-turn validation, corrupt/BLOB fail-closed handling, explicit rebuild lifecycle ownership, full schema/PK contracts, bounded query inputs, effective projection diagnostics, player omission sanitization, and canonical documentation corrections.
- Applied fourth three-way review patches for same-turn fact invalidation, missing-state dirty initialization, player row allowlisting, source-turn location visibility, validity windows, additive projection schema compatibility, trusted-marker resolution, snapshot rechecks, provenance query bounds, and non-finite versions.
- Applied fifth three-way review patches for monotonic generation/CAS ownership, ABA-safe context snapshots, all-view JSON-safe rows, strict BINARY single-column identities, insert-compatible extensions, trusted subjects, and validity/freshness separation.
- Applied sixth three-way review patches for final context generation reconciliation, clean-generation ownership transfer, subject-bound freshness, dynamic trusted-row typing, SQLite ASCII identifiers, canonical-write constraint checks, and maximum-generation fail-safe commits.
- Applied seventh three-way review patches for projection-metadata savepoint isolation, opaque generation nonces, complete executable-schema rejection, owned direct rebuilds, coherent retry fallback/copy state, invalid-row maintenance evidence, and aligned refresh/status diagnostics.
- Applied eighth three-way review patches for main-schema migration binding, strict schema/FK/index/default contracts, validity/freshness separation, player boundary sanitization, serialized projection publication, TEMP-safe projection/outbox access, transaction cleanup, final report reconciliation, stable omission snapshots, and surface inventory sync.
- Applied ninth three-way review patches for canonical migration-ledger/target binding, atomic helper schema setup, exact metadata/validity contracts, bounded memory scans, stable atomic reports, independent projection-state/outbox health, total metadata transaction cleanup, strict player omission/context boundaries, bounded cross-process publication locks, and final AC regression evidence.
- Synchronized canonical docs for memory summary provenance, freshness/staleness, visibility metadata, fallback context, and SQLite fact precedence. CLI/MCP/prompt public command syntax did not change.

### File List

- `_bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md`
- `_bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/source-tree-analysis.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/memory.py`
- `rpg_engine/migrations.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/projections.py`
- `rpg_engine/save_patch.py`
- `rpg_engine/surface_inventory.py`
- `rpg_engine/unit_of_work.py`
- `rpg_engine/resources/migrations/0009_memory_summary_provenance.sql`
- `tests/test_current_native_context.py`
- `tests/test_current_native_package.py`
- `tests/test_current_native_visibility.py`
- `tests/test_maintenance_tooling_coverage.py`
- `tests/test_projection_service.py`
- `tests/test_v1_cli.py`

### Implementation Plan

- Add RED coverage for memory metadata schema/backfill and deterministic rebuild evidence.
- Add RED coverage for stale memory omission when subject facts are newer than summary freshness evidence.
- Implement a backwards-compatible memory metadata migration and helper backfill.
- Extend memory rebuild, context loaded/omitted evidence, and missing-signal advisory fallback evidence.
- Sync canonical docs and run focused, current-native, runtime/projection/CLI, campaign, docs/static gates.

### Change Log

- 2026-07-10: Implemented Story 3.5 memory summary provenance/freshness metadata, stale memory omission evidence, fallback advisory evidence, docs sync, and moved story to review.
- 2026-07-10: Applied code review patches for migration idempotency, visibility metadata enforcement, legacy freshness inference, fallback diagnostics, and trusted lookup overfetch.
- 2026-07-10: Applied second review patches for player-safe projection error redaction, consistent derived authority defaults, subjectless legacy evidence, and hidden source evidence scanning.
- 2026-07-10: Applied third review patches for omitted/missing evidence sanitization, storage-time hidden evidence scanning, authority clamping, and native hidden evidence regression coverage.
- 2026-07-10: Applied fourth review patches for opaque source event/turn hidden scans, player-safe stale reason codes, and authority allowlisting.
- 2026-07-10: Applied final review patches for hidden-subject reason de-oracling, full source event/turn scanning, freshness evidence allowlisting, and current-native migration-state test robustness.
- 2026-07-10: Applied final freshness evidence value clamp patch.
- 2026-07-10: Applied third three-way review patches for strict provenance/source verification, schema and projection diagnostics, lifecycle ownership, bounded inputs, omission sanitization, and canonical docs.
- 2026-07-10: Applied fourth three-way review patches for same-turn memory invalidation, missing-state repair, player allowlists, validity/location checks, bounded provenance resolution, snapshot consistency, and robust projection versions.
- 2026-07-10: Applied fifth three-way review patches for generation-safe refresh ownership, ABA detection, all-view sanitization, strict schema identity/extensions, trusted subjects, and decoupled validity bounds.
- 2026-07-10: Applied sixth three-way review patches for final context snapshot reconciliation, post-refresh health ownership, strict freshness subjects, SQLite extension constraints, and maximum-generation commit safety.
- 2026-07-10: Applied seventh three-way review patches for fact-safe projection metadata failure, opaque generation ownership, complete schema execution checks, coherent context retries, and aligned rebuild/report diagnostics.
- 2026-07-10: Applied eighth three-way review patches for schema/migration hardening, player-safe memory boundaries, serialized projection publication, TEMP-safe state/outbox access, stable context omission snapshots, and final report reconciliation.
- 2026-07-10: Applied ninth three-way review patches, completed final full-suite/campaign/docs/static gates, and synchronized Story 3.5 to done.
