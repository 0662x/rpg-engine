---
baseline_commit: 204be0195d9166e0593947129579ca43e49b4832
---

# Story 2.2: Content Type and Merge Contract

Status: done

Completion note: Content Type / Merge Contract implemented with registry-derived validation, package merge policy gates, docs/schema sync, and review patch closure.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 engine maintainer，
我希望 content types 明确声明 Campaign YAML、delta keys、runtime tables 和 merge policies 如何对齐，
从而新增 package content 时不会产生 ad hoc schema drift。

## 验收标准

1. 给定默认 `ContentRegistry`，当 content type metadata 被检查时，每个已注册类型必须声明 campaign key、YAML key、适用时的 delta key、entity type、runtime table、sync safety、validation rule 和 merge policy；delta schema 允许但未注册为 package content root 的 entity types 不得被误判为已注册 package content roots。
2. 给定 Campaign Package 声明 content paths，当 load、validate、import、merge 或 upgrade workflow 运行时，content records 必须通过 content type contract 检查；绝对路径或 campaign-root escape 必须被拒绝。
3. 给定 content type contract 发生变化，当 focused tests 运行时，package validation、merge 或 sync 行为、schema resources 和 docs 必须一起更新；既有 Campaign/Save compatibility 必须被保留或明确迁移。

## 任务 / 子任务

- [x] 固化默认 Content Type contract metadata。 (AC: 1)
  - [x] 在 `rpg_engine/content_types/base.py`、`rpg_engine/content_types/registry.py` 或就近 helper 中补齐可检查 metadata，至少覆盖：`name`、`campaign_key`、`yaml_key`、`delta_key`、`entity_type`、`table`、`sync_safe`、record validation、database validation、seed/upsert capability、`merge_policy` ownership buckets。
  - [x] 更新 `render_content_type_list()` / `render_content_type_detail()` 或等价 CLI 输出，使 `python3 -m rpg_engine content inspect-type <name>` 能显示 validation 和 merge policy contract，而不需要调用者读 Python callbacks。
  - [x] 增强 `tests/test_content_registry.py`，断言默认 registry 的每个已注册类型都有稳定 contract metadata 和 `merge_policy`；`clock`、`relationship` 可以没有 delta key，但必须明确为无 delta upsert。
  - [x] 增加断言：`delta_schema.ALLOWED_ENTITY_TYPES` 中允许但未注册为 first-class package content root 的类型，例如 `location`、`item`、`character`，不会通过 `ContentRegistry.by_entity_type()` 或 campaign content key 被当成独立 package content type。

- [x] 统一 package content key 和 content path validation 到 registry contract。 (AC: 2)
  - [x] 在 Campaign validation 与 package source validation 中复用默认 registry 的 seed specs 判断允许的 `campaign.yaml.content.*` keys；未知 content key 必须报稳定错误，而不是被 package load / diff / upgrade 静默忽略。
  - [x] 保留 Story 2.1 已加固的 path boundary：content paths 必须是 campaign/package root 内相对路径，拒绝 absolute path、`..`、symlink/root escape；不要削弱 `rpg_engine/campaign_validation.py` 和 `rpg_engine/packages/service.py::content_paths()` 的双层保护。
  - [x] 增强 `tests/test_campaign_validation.py` 和/或 `tests/test_package_cli.py`，覆盖未知 content key、绝对路径、root escape 路径在 campaign validate、package validate、package diff/upgrade dry-run 中被拒绝。
  - [x] 不把 `content_schema_version`、capabilities 或普通 author docs 当成 content type；它们是 package/manifest metadata，不是 registry content roots。

- [x] 固化 merge policy 行为与 drift evidence。 (AC: 1, 3)
  - [x] 增强 `tests/test_package_merge.py`，覆盖默认 registry 中至少一个实际 spec 的 merge policy，而不是只用手写测试 spec；确认 author-owned 字段可由 package 更新、runtime-owned 字段保留 Save 状态、mergeable 字段合并、conflict-only 字段要求 migration 或显式处理。
  - [x] 确认 `dry_run_package_upgrade()`、`render_package_dry_run()`、`diff_package_against_campaign()` 和 `apply_package_upgrade()` 使用同一 `ContentTypeSpec.merge_policy`；不要新增第二套 merge decision table。
  - [x] 若补充 schema/resource 输出，保证它来自 registry/spec metadata；不要手写与 registry 分叉的 content type 表。

- [x] 同步 canonical docs 与 schema wording。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 的 Content Type Registry 段，加入 validation rule、database check、merge policy / ownership buckets，以及“允许 entity type 不等于 registered package content root”的明确说明。
  - [x] 如 package validation 输出或 authoring contract 改变，更新 `docs/save-and-campaign-packages.md` 或 `docs/authoring-guide.md`，说明未知 content key 和 root escape 的拒绝语义。
  - [x] 不新增旧 `docs/specs/`、`docs/architecture/` 正文；旧路径只保留 compatibility stubs。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN focused tests：`python3 -m pytest -q tests/test_content_registry.py tests/test_package_merge.py tests/test_package_cli.py tests/test_campaign_validation.py`
  - [x] Campaign/Package smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`、`python3 -m rpg_engine package validate ./tests/fixtures/minimal_campaign`
  - [x] 如果触碰 package upgrade/apply runtime path，运行 `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py`
  - [x] Docs gate：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
  - [x] 收尾运行 `git diff --check`；若 content type code 改动较集中，运行 `python3 -m py_compile rpg_engine/content_types/base.py rpg_engine/content_types/registry.py rpg_engine/content_types/core.py rpg_engine/content_types/world_setting.py rpg_engine/packages/service.py rpg_engine/packages/merge.py`

### Review Findings

- [x] [Review][Patch] Campaign schema resources allowed unknown `content.*` roots; fixed both schema files and added schema-level rejection tests.
- [x] [Review][Patch] Package workflow tests missed upgrade dry-run and invalid registered path cases; added package validate/diff/upgrade dry-run coverage for unknown, absolute, and root-escape content keys.
- [x] [Review][Patch] Auxiliary `random_tables` / `palettes` content was allowed by validation but omitted from package build/lock artifacts; added auxiliary file tracking and archive/manifest coverage.
- [x] [Review][Patch] Package content contract did not enforce file existence/type consistently; `validate_package_content_contract()` now rejects missing or non-file content paths before load/build/diff/apply.
- [x] [Review][Patch] `content inspect-type` did not expose default ownership for unlisted fields; metadata, CLI output, docs, and tests now state unlisted fields are `conflict-only`.
- [x] [Review][Patch] `load_package_source()` still treated non-object `manifest.content` as empty; package validate/diff/upgrade now fail with `manifest.content must be object`.
- [x] [Review][Patch] Auto-discovered `content/palettes/*.yaml` files were still omitted when `palettes` was not declared in the manifest; package build/lock now include those runtime-discovered palette files.
- [x] [Review][Patch] Campaign schema and validator content-root allow-lists could drift from registry metadata; validator auxiliary keys are now limited to true auxiliary content and schema tests compare both resources against registry seed keys plus auxiliary keys.
- [x] [Review][Patch] BMAD story and validation artifacts were untracked during review; both are now included in git intent-to-add and will be committed with the story.
- [x] [Review][Patch] Package content paths using `~` relied on `expanduser()` before rejection; validation now rejects tilde-prefixed paths as non-relative package paths.
- [x] [Review][Patch] Registered content YAML files could silently drop non-array collections or non-object records; package load now rejects invalid document/record shape and package validate/diff/upgrade tests cover it.
- [x] [Review][Patch] `relationship` had a merge policy but no current-record loader for package diff/upgrade; relationship records now load from runtime entity details and preserve runtime-owned `trust` / `status`.
- [x] [Review][Patch] `content.palettes: []` diverged from runtime auto-discovery; package source now treats an empty palettes list like runtime and includes discovered `content/palettes/*.yaml`.
- [x] [Review][Patch] In-root symlink content paths were validated by declared path but archived/locked under resolved target path; package lock/archive now preserve the manifest-declared relative path.
- [x] [Review][Patch] Registered content files missing the expected YAML root could still be treated as empty; package load now requires the declared `yaml_key` to exist.
- [x] [Review][Patch] `campaign validate` did not validate auto-discovered palettes when `content.palettes: []`; palette validation now follows runtime auto-discovery for an empty list.
- [x] [Review][Patch] Content paths containing non-escaping `..` segments could pollute package lock/build manifests; campaign and package validation now reject any parent path segment.
- [x] [Review][Patch] `relationship.details` conflict migrations could make dry-run pass but apply fail; migration validation and authorization now allow only conflict-field updates supported by apply.
- [x] [Review][Patch] Package migration manifest paths still allowed `~` or non-escaping `..` segments; migration path loading now uses the same stable manifest path guard as content paths.
- [x] [Review][Patch] Already-applied migrations could repeatedly authorize conflict-only field overwrites; diff/apply authorization now considers only pending migrations not already recorded in the effective package lock.
- [x] [Review][Patch] Pending rename/delete migration side effects were not represented in dry-run merge state; dry-run now projects pending renames into current records, emits pending migration warnings, preflights pending migrations, and preserves runtime-owned fields through rename upgrades.
- [x] [Review][Patch] Pending rename did not project JSON/list references or reject rename chains; rename migration now updates relationship/world-setting JSON refs, projects list refs during dry-run, rejects chained renames, and lets database-ref validation run against the pending-migration snapshot.
- [x] [Review][Patch] Package relationship source/target database references were not validated against the pending-migration database snapshot; relationship refs now preflight after pending migrations and accept only source-created or existing entity ids.
- [x] [Review][Patch] Pending rename dry-run projection for relationship details did not match the real recursive apply rewrite; projection now rewrites JSON/list refs through the same multi-ref helper before merge decisions.
- [x] [Review][Patch] `content sync` / import paths could still treat registered content files with missing YAML roots as empty; shared content source validation now rejects missing roots and malformed records before sync.
- [x] [Review][Patch] Package relationship refs treated every same-package record id as an entity endpoint; same-package relationship endpoints now count only `entity` content records plus existing DB entities.
- [x] [Review][Patch] Pending rename/delete migrations could be undone by same-package content upserts for the old source id; migration validation now rejects delete collisions and rename source ids that still appear in package content.
- [x] [Review][Patch] `update_conflict_field` accepted invalid explicit values; migration validation and apply now enforce allowed `entity.type` values and object/null `entity.details` values while preserving authorization-only operations.
- [x] [Review][Patch] `campaign validate` could traceback on missing or directory `random_tables` paths; random table validation now skips non-files after content path validation records the structured error.
- [x] [Review][Patch] Dry-run pending migration preflight could alter a caller's `defer_foreign_keys` PRAGMA state; preflight and package diff now restore the incoming deferral state.
- [x] [Review][Patch] Package relationship `details.source_id` / `details.target_id` endpoints were not checked against the database-ref contract; relationship details endpoints now must match top-level endpoints and resolve to same-package entity content or DB entities.
- [x] [Review][Patch] `delete_record content_type: entity` collision checks missed same-package `clock` / `relationship` / other entity-backed roots; delete collision validation now follows the actual entities-table deletion footprint.
- [x] [Review][Decision-needed] Explicit `update_conflict_field.value` semantics needed human choice; resolved as explicit value constrains incoming package content, while omitted `value` remains pure conflict-field authorization.
- [x] [Review][Patch] Relationship-only packages skipped endpoint database-ref validation when no delta-backed records were present; relationship refs now validate even when pseudo delta is empty.
- [x] [Review][Patch] Resolved decision records used a non-standard `[Review][Decision]` tag; story review records now use the allowed `[Review][Decision-needed]` classification.
- [x] [Review][Patch] Explicit `update_conflict_field.value` constraints were only checked when a merge conflict existed and could still act as standalone DB mutation; source validation now requires matching incoming package content, and migration apply no longer writes explicit values directly.
- [x] [Review][Patch] Package DB-ref validation omitted same-package created ids from registered roots without delta keys, such as `clock` and `relationship`; package and campaign content preflight now pass extra created refs for entity-backed roots and same-source clocks.
- [x] [Review][Patch] Duplicate `rename_entity.from` / `rename_entity.to` operations could make dry-run and apply diverge; package migration validation now rejects duplicate rename sources and targets.
- [x] [Review][Patch] Content sync/import validation for no-delta `relationship` records did not check endpoint refs; campaign content preflight now validates top-level and details relationship endpoints before sync.
- [x] [Review][Patch] Campaign validation did not count same-source entity-backed roots as valid `world_setting.linked_entities`; campaign validation now aligns linked entity refs with package/content preflight.
- [x] [Review][Patch] Story completion note still referenced unrelated context-engine work; completion note now describes Story 2.2 Content Type / Merge Contract closure.

## 开发说明

### 来源上下文

- Epic 2 要求 Campaign Package 能定义可替换世界、实体、关系和进度，Save Package 承载运行事实；Story 2.2 是后续 Entity/Relationship/Progress access contract 前的 content type / merge 基础。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-13 要求 Campaign Package 表达实体、关系、目标/进度、campaign facts、capabilities、rules 和 gameplay scaffolding；FR-17 要求不同 Campaign Package 复用同一 foundation flow。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-3 要求 contract family 可被 story 引用；AD-4 要求 `ContentRegistry` / `ContentTypeSpec` 对齐 Campaign YAML、delta key、runtime table、merge policy 和 presentation registry。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- AR-19 明确：Content Type / Merge Contract 必须对齐 Campaign YAML key、delta key、runtime table、entity type、validation 和 merge policy；不要把每个允许 entity type 都误当成已注册 package content type。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 2.1 已完成 Campaign/Save ownership 和 root escape 边界：不要回退 runtime artifact warning、source Campaign no-mutation、save target placement guard、content path root boundary 或 campaign test temp-copy ignore 行为。来源：`_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`。

### 当前实现状态

- `ContentTypeSpec` 当前已有 `campaign_key`、`yaml_key`、`delta_key`、`entity_type`、`table`、`sync_safe`、`validate_record`、`validate_database`、`record_id` 和 `merge_policy`。来源：`rpg_engine/content_types/base.py`。
- 默认 registry 当前注册：`entity`、`rule`、`clock`、`route`、`relationship`、`world_setting`。`entity` 与 `route` 没有 `entity_type`；`clock` 和 `relationship` 没有 delta key；`world_setting` 当前是唯一 `sync_safe=True` 类型。来源：`rpg_engine/content_types/core.py`、`rpg_engine/content_types/world_setting.py`。
- `render_content_type_list()` 当前显示基础 lifecycle 字段；`render_content_type_detail()` 已显示 seed/upsert/record preflight/database check/presentation，但没有把 merge policy ownership buckets 渲染出来。来源：`rpg_engine/content_types/registry.py`。
- `validate_v1_structure()` 已用 `get_default_registry().seed_specs()` 判断 Campaign manifest 的允许 content keys；`validate_content_paths()` 已拒绝 absolute path、root escape 和非文件。来源：`rpg_engine/campaign_validation.py`。
- `load_package_source()`、`validate_package_source()`、`diff_package_against_campaign()` 和 `apply_package_upgrade()` 已以 `registry.seed_specs()` 为核心读取 records、执行 `validate_record()`、计算 merge diff 和应用 upsert。需要检查未知 manifest content keys 是否被稳定拒绝，而不是被忽略。来源：`rpg_engine/packages/service.py`。
- `content_paths()` 在 package service 层已拒绝 absolute path 和 root escape；这是 Story 2.1 的关键安全边界之一。来源：`rpg_engine/packages/service.py`。
- `MergePolicy` 与 `merge_package_record()` 已表达 author-owned、runtime-owned、mergeable、conflict-only 字段归属；测试目前主要用手写 spec，还需要覆盖默认 registry 的真实 policy。来源：`rpg_engine/packages/merge.py`、`tests/test_package_merge.py`。

### 前序故事情报

- Story 2.1 的 review patch 大量集中在 path/root/symlink 边界、runtime artifact warning 和 source no-mutation digest。Story 2.2 触碰 package load/validate/merge 时，任何 path 处理都必须保留这些 guard。
- Story 2.1 已把 `campaign validate` 对运行态 artifacts 定义为 warning-only ownership evidence。Story 2.2 不应把 content type validation 与 runtime artifact ownership 混成同一错误类别。
- 近期提交 `204be01 feat: enforce campaign save ownership contract` 修改了 `campaign_validation.py`、`packages/service.py`、`save_service.py`、`save_manager.py` 和 docs；实现时先看当前 diff 基线，不要假设旧路径仍安全。

### 架构合规要求

- `ContentRegistry` 是 Content Type / Merge Contract 的权威来源；CLI output、docs 和 tests 应从 registry/spec 行为派生或验证，不维护第二张手写 truth table。
- Merge policy 是 package/campaign evolution 的 contract，不是 ordinary gameplay commit authority。runtime-owned 字段不能被 package upgrade 静默覆盖 Save 当前事实。
- Delta schema 允许 `character`、`item`、`location` 等 entity types，并不代表它们都是独立 Campaign Package content roots；它们通常作为 `entity` content type 的记录形态或 typed side table 进入 runtime。
- 本 story 不要求新增 Relationship access API、Progress access API、专用 relationship SQL 表或 progress ontology；这些属于 Story 2.3-2.5。
- 不要新增第二个 package source loader、第二个 registry、第二套 merge policy 或手写 schema drift checker。

### 相关文件

- `rpg_engine/content_types/base.py`：`ContentTypeSpec`、`MergePolicy`、contract metadata 的主要落点。
- `rpg_engine/content_types/registry.py`：default registry、lookup、seed/delta/sync specs、CLI/list/detail rendering。
- `rpg_engine/content_types/core.py`：entity/rule/clock/route/relationship specs、record validators、merge policies。
- `rpg_engine/content_types/world_setting.py`：world setting spec、database validation、sync-safe contract。
- `rpg_engine/packages/service.py`：package source load/validate/diff/apply、path boundary、registry-driven records。
- `rpg_engine/packages/merge.py`：field ownership merge policy 与 dry-run rendering。
- `rpg_engine/campaign_validation.py`：Campaign manifest content keys/path validation。
- `rpg_engine/delta_schema.py`：allowed entity types；用于证明 allowed type 不等于 registered content root。
- `docs/data-models.md`：Content Type Registry canonical table。
- `docs/save-and-campaign-packages.md`、`docs/authoring-guide.md`：如 package authoring/validation semantics 改变则同步。
- `tests/test_content_registry.py`、`tests/test_package_merge.py`、`tests/test_package_cli.py`、`tests/test_campaign_validation.py`：本 story 的 focused tests。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_content_registry.py tests/test_package_merge.py tests/test_package_cli.py tests/test_campaign_validation.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine package validate ./tests/fixtures/minimal_campaign
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md
git diff --check
```

如果实现触碰 package upgrade/apply runtime path：

```bash
python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py
```

如果只改变 registry rendering/docs，也仍需跑 `tests/test_content_registry.py` 和 `tests/test_package_merge.py`，证明 contract 输出没有与 merge behavior 分叉。

### 残余风险与边界

- 本 story 不要求新增新的 content type；它固化已注册 content types 的 contract 和 drift evidence。
- 本 story 不要求把所有 allowed entity type 提升为独立 content root；明确避免这个误判。
- 本 story 不要求支持自动迁移所有 conflict-only 字段；冲突仍应通过 migration、lock 或显式 maintenance path 处理。
- 本 story 不要求改变 player-safe turn/confirm chain、Save fact authority 或 projection/outbox 语义。
- 本 story 不要求跨 Campaign smoke；那是 Story 2.6。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python stdlib、dataclasses、PyYAML、SQLite、pytest、ContentRegistry、PackageSource、MergePolicy 和 package CLI；不要新增运行时依赖。

## Project Structure Notes

Story 2.2 应优先小步增强 content type metadata、package validation 和 focused tests。保持 `content_types/` 作为 contract source，`packages/service.py` 作为 package workflow consumer，`packages/merge.py` 作为 merge policy engine；不要把 package content validation 复制进 CLI handler。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `docs/project-context.md`
- `docs/save-and-campaign-packages.md`
- `docs/authoring-guide.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/content_types/base.py`
- `rpg_engine/content_types/registry.py`
- `rpg_engine/content_types/core.py`
- `rpg_engine/content_types/world_setting.py`
- `rpg_engine/packages/service.py`
- `rpg_engine/packages/merge.py`
- `rpg_engine/campaign_validation.py`
- `rpg_engine/delta_schema.py`
- `tests/test_content_registry.py`
- `tests/test_package_merge.py`
- `tests/test_package_cli.py`
- `tests/test_campaign_validation.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Implementation Plan

- 先写 registry/package validation RED tests，锁住 contract metadata、unknown content key、allowed entity type 不等于 content root、merge policy behavior。
- 再补最小实现：registry rendering/metadata、package source validation 的未知 content key/path 报错、必要 docs。
- 跑 focused gates 和 package/campaign smoke，再进入三路 code review。

### Debug Log References

- CREATE STORY: baseline commit `204be0195d9166e0593947129579ca43e49b4832`。
- DEV start: sprint status moved to `in-progress` at 2026-07-08T05:41:15+1000.
- RED: `python3 -m pytest -q tests/test_content_registry.py tests/test_package_merge.py tests/test_package_cli.py tests/test_campaign_validation.py` failed as expected because `ContentTypeSpec.contract_metadata()` did not exist, `content inspect-type` did not render merge policy, and package validate/diff ignored unknown `manifest.content.characters`.
- GREEN: `python3 -m pytest -q tests/test_content_registry.py tests/test_package_merge.py tests/test_package_cli.py tests/test_campaign_validation.py` passed with 40 tests and 32 subtests.
- Campaign validate gate: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` returned OK.
- Campaign smoke gate: `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` returned OK.
- Package validate gate: `python3 -m rpg_engine package validate ./tests/fixtures/minimal_campaign` returned OK.
- Syntax gate: `python3 -m py_compile rpg_engine/content_types/base.py rpg_engine/content_types/registry.py rpg_engine/content_types/core.py rpg_engine/content_types/world_setting.py rpg_engine/packages/service.py rpg_engine/packages/merge.py` passed.
- Docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- Whitespace gate: `git diff --check` passed.
- Package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 28 tests and 28 subtests.
- Full regression: `python3 -m pytest -q` passed with 548 tests and 670 subtests.
- CODE REVIEW: three review subagents completed. Blind Hunter reported 1 patch and 1 decision-needed candidate; Edge Case Hunter reported 3 patch findings; Acceptance Auditor reported 2 patch findings and 1 decision-needed candidate. Triage merged them into 5 patch findings and 0 true decision-needed/defer items.
- REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_content_registry.py tests/test_package_merge.py tests/test_package_cli.py tests/test_campaign_validation.py` passed with 42 tests and 37 subtests.
- REVIEW PATCH campaign validate/test and package validate gates returned OK.
- REVIEW PATCH syntax gate passed for content type and package service modules.
- REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 28 tests and 28 subtests.
- REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- REVIEW PATCH whitespace gate: `git diff --check` passed.
- REVIEW PATCH full regression: `python3 -m pytest -q` passed with 550 tests and 675 subtests.
- SECOND CODE REVIEW: three review subagents completed. Blind Hunter, Edge Case Hunter, and Acceptance Auditor reported 4 patch findings and 0 true decision-needed items after triage.
- SECOND REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_merge.py` passed with 45 tests and 40 subtests.
- SECOND REVIEW PATCH campaign validate/test and package validate gates returned OK.
- SECOND REVIEW PATCH syntax gate passed for content type, package service, package merge, and campaign validation modules.
- SECOND REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- SECOND REVIEW PATCH whitespace gate: `git diff --check` passed.
- SECOND REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- SECOND REVIEW PATCH full regression: `python3 -m pytest -q` passed with 554 tests and 678 subtests.
- THIRD CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Blind Hunter reported 1 patch finding; Edge Case Hunter reported 3 patch findings; triage found 4 patch findings and 0 decision-needed/defer items.
- THIRD REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_save_condition_coverage.py` passed with 63 tests and 53 subtests.
- THIRD REVIEW PATCH campaign validate/test and package validate gates returned OK.
- THIRD REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, and campaign validation modules.
- THIRD REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- THIRD REVIEW PATCH whitespace gate: `git diff --check` passed.
- THIRD REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- THIRD REVIEW PATCH full regression: `python3 -m pytest -q` passed with 558 tests and 680 subtests.
- FOURTH CODE REVIEW: three review subagents completed. Blind Hunter reported 1 patch finding; Edge Case Hunter reported 3 patch findings; Acceptance Auditor reported 2 patch findings. Triage merged them into 4 patch findings and 0 decision-needed/defer items.
- FOURTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 65 tests and 55 subtests.
- FOURTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- FOURTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, and campaign validation modules.
- FOURTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- FOURTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- FOURTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- FOURTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 560 tests and 682 subtests.
- FIFTH CODE REVIEW: three review subagents completed. Blind Hunter and Acceptance Auditor reported clean; Edge Case Hunter reported 2 patch findings; triage found 2 patch findings and 0 decision-needed/defer items.
- FIFTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_campaign_validation.py tests/test_content_registry.py` passed with 66 tests and 57 subtests.
- FIFTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- FIFTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, and campaign validation modules.
- FIFTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- FIFTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- FIFTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- FIFTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 561 tests and 684 subtests.
- SIXTH CODE REVIEW: three review subagents completed. Blind Hunter and Acceptance Auditor reported clean; Edge Case Hunter reported 1 patch finding; triage found 1 patch finding and 0 decision-needed/defer items.
- SIXTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_campaign_validation.py tests/test_content_registry.py` passed with 67 tests and 57 subtests.
- SIXTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- SIXTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, and campaign validation modules.
- SIXTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- SIXTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- SIXTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- SIXTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 562 tests and 684 subtests.
- SEVENTH CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Blind Hunter reported 1 patch finding; Edge Case Hunter reported 3 patch findings. Triage merged them into 4 patch findings and 0 decision-needed/defer items.
- SEVENTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_campaign_validation.py tests/test_content_registry.py` passed with 68 tests and 57 subtests.
- SEVENTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- SEVENTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, and campaign validation modules.
- SEVENTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- SEVENTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- SEVENTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- SEVENTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 563 tests and 684 subtests.
- EIGHTH CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Edge Case Hunter reported 2 patch findings; Blind Hunter reported 1 patch finding. Triage merged them into 3 patch findings and 0 decision-needed/defer items.
- EIGHTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 70 tests and 57 subtests.
- EIGHTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- EIGHTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, campaign validation, content validation, and content sync modules.
- EIGHTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- EIGHTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- EIGHTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- EIGHTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 565 tests and 684 subtests.
- NINTH CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Blind Hunter reported 1 patch finding; Edge Case Hunter reported 4 patch findings. Triage kept 5 patch findings and 0 decision-needed/defer items.
- NINTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 75 tests and 61 subtests.
- NINTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- NINTH REVIEW PATCH syntax gate passed for package service, campaign validation, and updated tests.
- NINTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- NINTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 570 tests and 688 subtests.
- TENTH CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Blind Hunter reported 2 patch findings and 1 decision-needed finding; Edge Case Hunter confirmed the entity-backed delete collision patch. Triage kept 2 patch findings, 1 decision-needed finding, and 0 defer items.
- TENTH DECISION RESOLUTION: user selected option 1 for `update_conflict_field.value`; explicit values are constraints on incoming package content, omitted values remain pure authorization.
- TENTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 78 tests and 63 subtests.
- TENTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- TENTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, campaign validation, content validation, and content sync modules.
- TENTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- TENTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- TENTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- TENTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 573 tests and 690 subtests.
- ELEVENTH CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Edge Case Hunter reported 2 patch findings; Blind Hunter reported 1 patch finding. Triage kept 3 patch findings and 0 decision-needed/defer items.
- ELEVENTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 79 tests and 63 subtests.
- ELEVENTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- ELEVENTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, campaign validation, content validation, and content sync modules.
- ELEVENTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- ELEVENTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- ELEVENTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- ELEVENTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 574 tests and 690 subtests.
- TWELFTH CODE REVIEW: three review subagents completed. Blind Hunter and Acceptance Auditor reported clean; Edge Case Hunter reported 1 patch finding. Triage kept 1 patch finding and 0 decision-needed/defer items.
- TWELFTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 81 tests and 63 subtests.
- TWELFTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- TWELFTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, campaign validation, content validation, and content sync modules.
- TWELFTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- TWELFTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- TWELFTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- TWELFTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 576 tests and 690 subtests.
- THIRTEENTH CODE REVIEW: three review subagents completed. Acceptance Auditor reported clean; Blind Hunter reported 1 patch finding; Edge Case Hunter reported 3 patch findings. Triage kept 4 patch findings and 0 decision-needed/defer items.
- THIRTEENTH REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_cli.py tests/test_campaign_validation.py tests/test_package_save_condition_coverage.py tests/test_package_merge.py tests/test_content_registry.py` passed with 84 tests and 63 subtests.
- THIRTEENTH REVIEW PATCH campaign validate/test and package validate gates returned OK.
- THIRTEENTH REVIEW PATCH syntax gate passed for content type, package service, package merge, package lock/archive, campaign validation, content validation, and content sync modules.
- THIRTEENTH REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md` passed, checking 87 markdown files.
- THIRTEENTH REVIEW PATCH package/save boundary gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 29 tests and 28 subtests.
- THIRTEENTH REVIEW PATCH whitespace gate: `git diff --check` passed.
- THIRTEENTH REVIEW PATCH full regression: `python3 -m pytest -q` passed with 579 tests and 690 subtests.

### Completion Notes List

- Added machine-readable content type contract metadata on `ContentTypeSpec`, including lifecycle fields, validation flags, seed/delta capability, sync safety, and merge policy ownership buckets.
- Extended `content inspect-type` output to render record/database validation and merge policy directly from registered specs.
- Added package source validation for unknown `manifest.content.*` keys while preserving legal auxiliary author content keys `random_tables` and `palettes`.
- Locked the allowed entity type vs registered package content root distinction with tests, so `character`, `item`, and `location` remain entity records rather than independent content roots.
- Updated package merge tests to exercise a real default registry merge policy and updated canonical docs for content registry, package key, and authoring semantics.
- Resolved first-round review patches by syncing campaign schemas, strengthening package content path/file checks, making loader/build/lock include auxiliary content files, expanding workflow tests, and documenting default `conflict-only` ownership for unlisted fields.
- Resolved second-round review patches by hard-failing non-object `manifest.content`, including auto-discovered palette files in build/lock artifacts, aligning schema tests with registry-derived content roots, and rejecting tilde-prefixed package content paths before expansion.
- Resolved third-round review patches by validating registered YAML record shapes at load time, adding relationship current-record merge support, aligning empty palette-list auto-discovery with runtime behavior, and preserving manifest-declared symlink paths in package lock/archive artifacts.
- Resolved fourth-round review patches by requiring declared YAML roots, validating campaign auto-discovered palettes for empty palette lists, rejecting parent path segments, and keeping conflict-field migration dry-runs aligned with apply support.
- Resolved fifth-round review patches by applying content-path-grade guards to migration manifest paths and limiting conflict-field authorization to pending migrations.
- Resolved sixth-round review patch by making package dry-run migration-aware for pending renames/deletes and adding migration preflight so dry-run/apply stay aligned.
- Resolved seventh-round review patches by projecting/rewriting JSON and list references during entity renames, rejecting chained rename migrations, and validating database references against pending-migration state.
- Resolved eighth-round review patches by validating relationship refs after pending migrations, aligning recursive rename dry-run/apply projections, and sharing registered content source shape validation with content sync/import.
- Resolved ninth-round review patches by tightening relationship endpoint refs, rejecting migration/content source-id collisions, validating explicit conflict-field values, stabilizing random table path errors, and preserving `defer_foreign_keys` across dry-run preflight.
- Resolved tenth-round review patches and decision by validating relationship details endpoints, expanding delete collision checks to all entity-backed package roots, and enforcing explicit conflict-field migration values as incoming-content constraints.
- Resolved eleventh-round review patches by validating relationship-only package refs, normalizing resolved decision labels, and enforcing explicit conflict-field values at source validation without direct migration DB mutation.
- Resolved twelfth-round review patch by including same-package and same-source created ids from no-delta registered roots in database-reference preflight.
- Resolved thirteenth-round review patches by rejecting duplicate rename endpoints, sharing relationship endpoint preflight with content sync/import, aligning campaign same-source entity-backed refs, and correcting the story completion note.

### File List

- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/authoring-guide.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `rpg_engine/resources/schemas/campaign.schema.json`
- `rpg_engine/content_sync.py`
- `rpg_engine/content_types/base.py`
- `rpg_engine/content_types/registry.py`
- `rpg_engine/content_validation.py`
- `rpg_engine/packages/lock.py`
- `rpg_engine/packages/service.py`
- `schemas/campaign.schema.json`
- `tests/test_campaign_validation.py`
- `tests/test_content_registry.py`
- `tests/test_package_cli.py`
- `tests/test_package_merge.py`
- `tests/test_package_save_condition_coverage.py`

### Change Log

- 2026-07-08: Implemented Content Type / Merge Contract metadata, registry rendering, package content-key validation, focused tests, docs sync, and verification gates.
