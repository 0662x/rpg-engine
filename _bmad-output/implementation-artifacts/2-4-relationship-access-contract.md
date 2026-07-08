---
baseline_commit: cec10ff045d9d68c3fec9eae9b2c39bcb0ca4d65
---

# Story 2.4: Relationship Access Contract

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 game host，
我希望 relationships 成为 first-class readable and validatable concepts，
从而 AI 和 gameplay systems 能理解谁认识谁、谁拥有什么、谁在哪里、以及双方态度如何。

## 验收标准

1. 给定 Campaign 或 Save data 包含 relationship records，当 relationship access contract 读取它们时，必须返回稳定的 relationship id、source id、target id、kind/state、存在时的 attitude 或 stance 字段、visibility、summary 和 update evidence；调用方不得依赖任意 `details_json` 约定。
2. 给定 relationship endpoint 缺失、hidden、archived 或超出 caller visibility，当 validation 或 context assembly 请求该 relationship 时，必须按 caller mode 报告或过滤问题；player-safe output 不得泄露 hidden endpoints。
3. 给定 AI 或 maintenance workflow 建议 relationship change，当该 change 被提交时，必须进入 validated mutation、proposal 或 maintenance path；suggestion alone 不得成为事实。

## 任务 / 子任务

- [x] 建立命名 Relationship Access Contract。 (AC: 1, 2)
  - [x] 新增 `rpg_engine/relationship_access.py` 或等价就近模块，定义 `RelationshipRecord`，暴露稳定字段：`id`、`source_id`、`target_id`、`kind` / `state`、`attitude` / `stance`、`trust`、`visibility`、`summary`、parsed `details`、`updated_turn_id`、`updated_at`。
  - [x] 提供 `read_relationship()` / `list_relationships()` 或等价 API，默认排除 archived relationship，并对 `view="player"` 排除 hidden relationship 及 hidden/archived/off-view endpoints。
  - [x] 复用 `rpg_engine.entity_access.read_entity()` / `list_entities()` 和 `visibility.py` normalization；不要复制 literal `status != 'archived'` / `visibility != 'hidden'` SQL。
  - [x] 保持当前 v1 storage：relationship 仍是 `entities.type='relationship'`，规范字段从 normalized details 解析；不得新增并行 relationship identity table 或要求专用 SQL 表。

- [x] 将 relationship endpoint validation 接入现有 validation path。 (AC: 1, 2, 3)
  - [x] 增加 helper 校验 relationship records / runtime relationship upserts：`source_id` 与 `target_id` 必须是非空合法 entity id，且已存在或在同一 validated delta 的 `upsert_entities[*].id` 中创建。
  - [x] 对 `upsert_entities[*].type == "relationship"` 的 runtime delta，要求 `details.source_id` 与 `details.target_id` 存在并通过 endpoint reference validation；保留 `details.state`、`details.stance`、`details.trust` 等字段为 relationship payload，不把它们当作写入授权。
  - [x] 对 malformed relationship details、空 endpoint、leading/trailing whitespace、非字符串 endpoint、非法 id、缺失 endpoint、同一 delta 非法 id 等情况返回稳定 validation error。
  - [x] 不新增 `upsert_relationships` delta key，不让 AI candidate、proposal approval、package merge 或 content sync 绕过 `validate_delta_schema()` / `validate_content_sources()` / maintenance validation。

- [x] 增加 focused relationship access tests。 (AC: 1, 2, 3)
  - [x] 新增 `tests/test_relationship_access.py` 或扩展相邻测试，覆盖 `read_relationship()` / `list_relationships()` 返回 stable fields、parsed details、trust/state/stance、update evidence。
  - [x] 覆盖 player view 读不到 hidden relationship、hidden endpoint relationship、archived endpoint relationship；GM / maintenance view 能读取 hidden relationship 并带 endpoint evidence。
  - [x] 覆盖 runtime delta relationship upsert：既有 endpoints 通过、同一 delta 新建 endpoints 通过、缺失/空/非字符串/空白/非法 endpoint 失败，并通过 `validate_delta_schema(..., conn)` 集成断言。
  - [x] 覆盖 Campaign/package relationship source validation 不回退：top-level endpoints 与 `details.source_id` / `details.target_id` mismatch 仍报错，relationship-only package 仍会校验 endpoints。
  - [x] 使用临时 Save Package 或 fixture copy，不直接修改正式 current save package。

- [x] 同步 canonical docs 与 component inventory。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 的 Relationship Access Contract 段，说明 relationship storage、stable read fields、endpoint visibility/status filters、runtime delta endpoint validation 和 no direct AI fact authority。
  - [x] 更新 `docs/component-inventory.md`，登记 Relationship Access 模块或等价职责。
  - [x] 如实现只改变 internal contract，不新增 CLI/MCP/public output，则不要扩大 `docs/cli-contracts.md` / `docs/mcp-contracts.md` scope。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN focused tests：`python3 -m pytest -q tests/test_relationship_access.py tests/test_entity_access.py tests/test_validation_pipeline.py`
  - [x] Package/content regression：`python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py`
  - [x] Current native visibility/write safety gate：`python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py`
  - [x] Campaign smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`
  - [x] Docs gate：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-4-relationship-access-contract.md`
  - [x] 收尾运行 `git diff --check`；如新增 Python 模块，运行 `python3 -m py_compile rpg_engine/relationship_access.py rpg_engine/delta_schema.py`。

### Review Findings

- [x] [Review][Patch] Non-object relationship `details` skipped endpoint validation [`rpg_engine/relationship_access.py`] — fixed by reporting `details: must be object` plus required `source_id` / `target_id` errors.
- [x] [Review][Patch] `list_relationships(limit=0)` returned one record and non-integer limits were not validated up front [`rpg_engine/relationship_access.py`] — fixed by normalizing limit before scanning.
- [x] [Review][Decision] Archived endpoint object exposure for GM/maintenance views [`rpg_engine/relationship_access.py`] — user chose issue-only behavior; fixed so archived endpoints are reported in `endpoint_issues` but not returned as endpoint records.
- [x] [Review][Patch] Maintenance/content pseudo-delta relationship upserts could miss endpoint validation [`rpg_engine/content_validation.py`] — fixed by routing `upsert_entities[*].type == "relationship"` through `validate_delta_relationship_references()`.
- [x] [Review][Patch] Stable field focused tests did not assert all AC1 fields [`tests/test_relationship_access.py`] — fixed by asserting `visibility`, `summary`, parsed `details`, `updated_turn_id`, and `updated_at`.

## 开发说明

### 来源上下文

- Epic 2 要求 Campaign/Save 分层、Entity/Relationship/Progress access contract、Content Type / Merge Contract 和通用 extension hooks 能支撑不同 Campaign Package。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 2.4 明确 relationship 读取必须返回 stable relationship id、source/target、kind/state、attitude/stance、visibility、summary、update evidence，并且不能依赖任意 `details_json` 约定。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-7 要求支持由 Campaign Package 或 Save Package 提供的重要实体关系；FR-13/FR-17 要求 Campaign Package 表达基础结构且 Kernel 保持通用基座。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-4 要求 Relationship 是 first-class access contract，但 v1 可继续使用 `relationship` content type、`type: relationship` entity 和规范化 details；调用方不得直接依赖 storage internals。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Architecture AD-2 / PRD NFR-1 要求 AI 输出只能是 advisory/candidate，不能直接写 facts、approve proposal 或 grant hidden access。来源：`docs/project-context.md`、`docs/architecture.md`。

### 当前实现状态

- `rpg_engine/content_types/core.py::validate_relationship_record()` 已校验 Campaign relationship 的 `id`、`name`、`summary`、`source_id`、`target_id`、`visibility` 和 `details` shape。
- `rpg_engine/content_types/core.py::_upsert_relationship()` 当前把 relationship 写成 `entities.type='relationship'`，并把 `source_id`、`target_id`、`state`、`trust`、`stance`、`notes` 合入 normalized `details`。
- `rpg_engine/entity_access.py` 已提供 shared `EntityRecord`、`read_entity()`、`list_entities()`、`validate_delta_entity_references()`、status/visibility normalization、hidden clock subtype filtering 和 same-delta reference validation。Relationship access 必须复用它。
- `rpg_engine/content_validation.py::validate_relationship_refs()` 与 `rpg_engine/packages/service.py::validate_package_relationship_refs()` 已校验 Campaign/package relationship endpoints 和 details endpoint mismatch；本 story 不应放松这些错误。
- `rpg_engine/delta_schema.py` 允许 `upsert_entities[*].type == "relationship"`，但当前 runtime entity reference validation 没有 relationship-specific `details.source_id` / `details.target_id` endpoint contract。
- `examples/v1_minimal_adventure/content/relationships.yaml` 和 `examples/small_cn_campaign/content/relationships.yaml` 提供现有 relationship fixtures，可用于 campaign smoke 和 focused tests。

### 前序故事情报

- Story 2.1 固化 Campaign/Save ownership：普通 play 后产生的 relationship/progress changes 只能落在 Save Package fact boundary，不能写回 source Campaign Package。
- Story 2.2 固化 Content Type / Merge Contract：relationship 是 registered content type，但没有 delta key；package merge policy author-owned endpoints/summary/state/stance，runtime-owned trust/status。
- Story 2.3 新增 `entity_access.py` 后经过多轮 review，关键经验是所有 player-facing reads 必须复用 shared visibility/status helpers，避免 literal SQL、Unicode/format whitespace bypass、hidden clock subtype leak、stale FTS/card/context redaction regression。
- 最近提交 `cec10ff Implement entity identity access contract` 触碰了 entity access、visibility、redaction、context、render、cards、preview、MCP 和 memory；实现前必须以当前 HEAD 为准，不假设旧查询路径仍安全。

### 架构合规要求

- Relationship Access Contract 是 read/validation support，不拥有写入权威。事实写入仍必须经过 Campaign import/package maintenance 或 runtime validation/commit。
- v1 不新增 relationship 专用 SQL 表；如将来需要专表，必须另开 architecture/story。
- Relationship endpoints 必须使用 `entities.id`，不得引入新的 relationship identity system。
- Player-safe relationship reads 必须过滤 relationship 本身和 endpoints 的 hidden/archived/off-view 状态；GM/maintenance 必须显式选择 hidden-read view。
- Runtime relationship mutation 应通过 `upsert_entities` 的 `type='relationship'` 进入现有 delta validation；不要新增未经授权的 shortcut。

### 相关文件

- `rpg_engine/entity_access.py`：必须复用的 entity identity、visibility/status 和 reference validation helper。
- `rpg_engine/relationship_access.py`：建议新增的 Relationship Access Contract 模块。
- `rpg_engine/delta_schema.py`：runtime delta schema 和 database reference validation 接入口。
- `rpg_engine/content_types/core.py`：relationship content type record validation / import shape。
- `rpg_engine/content_validation.py`：Campaign content source relationship endpoint validation。
- `rpg_engine/packages/service.py`：package relationship endpoint validation、relationship current record loader、merge/dry-run behavior。
- `docs/data-models.md`、`docs/component-inventory.md`：canonical docs sync。
- `tests/test_relationship_access.py`、`tests/test_entity_access.py`、`tests/test_validation_pipeline.py`、`tests/test_campaign_validation.py`、`tests/test_package_cli.py`：focused tests。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_relationship_access.py tests/test_entity_access.py tests/test_validation_pipeline.py
python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-4-relationship-access-contract.md
python3 -m py_compile rpg_engine/relationship_access.py rpg_engine/delta_schema.py
git diff --check
```

如 implementation touches context/render/cards/player-facing relationship output，另跑：

```bash
python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_context_quality.py
```

### 残余风险与边界

- 本 story 不要求 Relationship context inclusion；那是 Story 3.4 的主要范围。本 story 只提供 context assembly 可复用的 first-class access contract。
- 本 story 不要求 Progress Track / Clock access contract；那是 Story 2.5。
- 本 story 不要求 cross-campaign smoke；那是 Story 2.6。
- 本 story 不要求 proposal queue apply/revert；AI/maintenance relationship suggestions 只需保持 suggestion != fact，并进入 existing validated/proposal/maintenance path。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python stdlib、dataclasses、SQLite、pytest、`entity_access`、`visibility`、`ContentRegistry`、`PackageSource` 和 validation pipeline；不要新增运行时依赖。

## Project Structure Notes

Relationship access 应与 `entity_access.py` 同层，保持 helper 小而明确。优先通过 `RelationshipRecord` + read/list/validate helper 形成 contract；不要把 relationship storage parsing 分散到 CLI、MCP、context 或 package caller 中。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
- `_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`
- `docs/project-context.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/entity_access.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/content_types/core.py`
- `rpg_engine/content_validation.py`
- `rpg_engine/packages/service.py`
- `tests/test_entity_access.py`
- `tests/test_campaign_validation.py`
- `tests/test_package_cli.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Implementation Plan

- 先写 relationship access RED tests，锁住 stable read fields、player/GM visibility、hidden/archived endpoint filtering 和 delta endpoint validation。
- 新增最小 `relationship_access.py`，复用 `entity_access` 与 `visibility` helper。
- 将 relationship-specific endpoint validation 接入 `delta_schema.validate_database_refs()`。
- 同步 docs/component inventory，运行 focused gates。

### Debug Log References

- RED test: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_relationship_access.py -p no:cacheprovider` failed as expected with missing `rpg_engine.relationship_access`.
- GREEN focused test: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_relationship_access.py -p no:cacheprovider` passed with 2 tests.
- Focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_relationship_access.py tests/test_entity_access.py tests/test_validation_pipeline.py -p no:cacheprovider` passed with 33 tests and 11 subtests.
- Package/content regression: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py -p no:cacheprovider` passed with 70 tests and 52 subtests.
- Current native gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py -p no:cacheprovider` passed with 8 tests.
- Campaign gates: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` returned OK; `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` returned OK for 12 smoke tests.
- Docs/syntax/quality gates: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-4-relationship-access-contract.md` checked 87 Markdown files; `python3 -m py_compile rpg_engine/relationship_access.py rpg_engine/delta_schema.py` passed; `python3 -m ruff check .` passed; `git diff --check` passed.
- Full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 608 tests and 705 subtests.
- Review patch focused test: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_relationship_access.py -p no:cacheprovider` passed with 2 tests.
- Review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_relationship_access.py tests/test_entity_access.py tests/test_validation_pipeline.py -p no:cacheprovider` passed with 33 tests and 11 subtests.
- Review patch content validation gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_core_rule_condition_coverage.py tests/test_upgrade_v2.py -p no:cacheprovider` passed with 18 tests and 4 subtests.
- Review patch package/content regression: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py -p no:cacheprovider` passed with 70 tests and 52 subtests.
- Review patch current native gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py -p no:cacheprovider` passed with 8 tests.
- Review patch campaign/docs/syntax gates: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` OK; `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` OK for 12 smoke tests; `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-4-relationship-access-contract.md` checked 87 Markdown files; `python3 -m py_compile rpg_engine/relationship_access.py rpg_engine/delta_schema.py rpg_engine/content_validation.py` passed; `python3 -m ruff check .` passed; `git diff --check` passed.
- Review patch full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 608 tests and 705 subtests.
- Second code review: Blind Hunter raised 3 dismissed non-blocking/scope findings; Edge Case Hunter returned `[]`; Acceptance Auditor returned clean review.

### Completion Notes List

- Added `rpg_engine.relationship_access.RelationshipRecord` plus `read_relationship()` and `list_relationships()` as the stable relationship read contract over current entity-backed storage.
- Added endpoint-aware player-safe filtering: player view filters hidden relationships, hidden endpoints, archived endpoints, and missing endpoints; GM/maintenance views can inspect hidden endpoints and receive `endpoint_issues` for missing or archived endpoints.
- Added `validate_delta_relationship_references()` and routed `delta_schema.validate_database_refs()` through it so runtime `type='relationship'` upserts require valid `details.source_id` / `details.target_id` references.
- Routed content maintenance `upsert_entities[*].type == "relationship"` through the same endpoint reference validation.
- Hardened malformed relationship details, archived endpoint serialization, and `list_relationships()` limit semantics after code review.
- Added focused relationship access tests for stable fields, endpoint visibility/status filtering, same-delta endpoint creation, malformed endpoint errors, and `validate_delta_schema(..., conn)` integration.
- Synced `docs/data-models.md` and `docs/component-inventory.md` with the new Relationship Access Contract.

### File List

- `_bmad-output/implementation-artifacts/2-4-relationship-access-contract.md`
- `_bmad-output/implementation-artifacts/2-4-relationship-access-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `rpg_engine/content_validation.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/relationship_access.py`
- `tests/test_relationship_access.py`

## Change Log

- 2026-07-09: Created story context for Relationship Access Contract.
- 2026-07-09: Started implementation for Relationship Access Contract.
- 2026-07-09: Implemented Relationship Access Contract, runtime delta endpoint validation, focused tests, docs sync, and verification gates.
- 2026-07-09: Applied first-round review patches for malformed details validation, content maintenance validation, archived endpoint reporting, limit handling, and stable field coverage.
- 2026-07-09: Completed second code review, final verification gates, and moved story to done.
