---
baseline_commit: c835d34803f99b8b2c4c4024022ba435640d0b43
---

# Story 2.6: 跨 Campaign 的模型边界冒烟测试

Status: done

Completion note: Implementation, review patches, final verification gates and sprint sync completed.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为引擎作者，
我希望至少两个不同 Campaign Package 能复用同一套 Campaign/Save 模型边界，
从而证明 Kernel 的 package、entity、relationship 和 progress 基础不是某一个战役的专用实现。

## 验收标准

1. 给定两个具有不同 capability profile 或 genre assumption 的 Campaign Packages，当每个 package 在临时 Save 上运行 init、save inspect、campaign validate、campaign test 和模型访问 smoke 时，两者都必须复用同一套 Campaign/Save ownership、Content Type / Merge、Entity、Relationship 和 Progress access contracts，并且不需要 fork fact store、custom commit chain 或 campaign-specific runtime schema。
2. 给定新的 gameplay variation 可以通过 capabilities、content types、rules、relationship kinds、progress tracks 和 smoke tests 表达，当 variation 被加入其中一个 Campaign Package 时，不得改变核心 fact authority、player confirmation flow 或 Context Slice contract；任何新增 extension point 都必须带 contract 文档和边界测试。
3. 给定 smoke test 需要写入 Save Package state，当测试运行时，必须使用 temporary save copy，并且正式 current save packages 和 source Campaign Package 不会被修改。

## 任务 / 子任务

- [x] 建立跨 Campaign 模型边界 smoke 测试。 (AC: 1, 3)
  - [x] 新增 `tests/test_cross_campaign_model_smoke.py` 或等价 focused regression，覆盖 `examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 两个不同 profile 的 package。
  - [x] 对每个 package 调用 `validate_campaign_package()`、`run_campaign_smoke_tests()`、`init_v1_save()` 和 `inspect_v1_save()` / `inspect_save_package()`，并断言结果均为 OK。
  - [x] 所有 save 初始化和写入类 smoke 必须在 `tempfile.TemporaryDirectory()` 下进行；不得直接写 source package，也不得写正式 current save。
  - [x] 记录 source Campaign Package 关键文件 fingerprint 或 runtime artifact absence，证明 smoke 运行后 source package 未被写入运行态文件或修改作者内容。

- [x] 验证两个 Campaign 复用同一套模型 access contracts。 (AC: 1)
  - [x] 从每个临时 Save 的 SQLite 中通过 `read_entity()` / `list_entities()` 读取 player entity、当前 location 和至少一个题材特定 entity，断言 stable entity fields 存在且 player view 不需要表级知识。
  - [x] 通过 `list_relationships()` / `read_relationship()` 读取至少一个 visible relationship，断言 `source_id`、`target_id`、`state` / `trust` / `summary` 等 stable fields 可用。
  - [x] 通过 `list_progress()` / `read_progress()` 读取至少一个 clock-backed progress，断言 `segments_total`、`segments_filled`、`visibility`、`trigger_when_full` 和 update evidence shape 可用。
  - [x] 对每个 package 构造一个合法 `tick_clocks` delta，使用 `validate_delta_schema(..., conn)` 或 `validate_delta_progress_references()` 证明 progress tick validation 复用同一路径。

- [x] 验证 Content Type / Merge 和 schema 不被 campaign-specific fork。 (AC: 1, 2)
  - [x] 使用 `get_default_registry()` 或 `content inspect-type` 等价 API，断言两个 campaign 使用同一个 registry：`entity`、`relationship`、`clock`、`rule`、`route`、`world_setting` 的 contract metadata 一致。
  - [x] 断言 `relationship` 与 `clock` 仍没有 runtime delta upsert key；runtime relationship/progress changes 仍走 validated mutation / `tick_clocks` / existing proposal or maintenance path，不新增 `upsert_relationships` 或 `upsert_clocks`。
  - [x] 比较两个临时 Save 的 SQLite table set，确认没有 campaign-specific runtime table，例如 `progress_tracks_*`、`relationships_*` 或 genre-named fact tables。
  - [x] 覆盖 capability / content variation：英文 minimal adventure 与中文 small campaign 可有不同 capabilities、relationship kinds/states、progress tracks、palettes 或 rules，但核心 fact authority 和 schema 不变。

- [x] 同步 canonical docs 与测试门禁说明。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 或 `docs/save-and-campaign-packages.md`，记录 Story 2.6 的跨 Campaign model-boundary smoke：两个不同 package 复用同一 Campaign/Save ownership、content registry、entity/relationship/progress access contracts。
  - [x] 更新 `docs/testing-and-quality-gates.md`，把跨 campaign model smoke 作为触碰 package/content/entity/relationship/progress foundation 时的 focused gate。
  - [x] 如实现只新增 regression tests 和 docs，不改变 CLI/MCP/public output，则不要扩大 `docs/cli-contracts.md` / `docs/mcp-contracts.md` scope。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN focused test：`python3 -m pytest -q tests/test_cross_campaign_model_smoke.py`
  - [x] Adjacent contract regression：`python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py`
  - [x] Package/save regression：`python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py`
  - [x] Campaign smoke CLI gate：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign validate ./examples/small_cn_campaign`、`python3 -m rpg_engine campaign test ./examples/small_cn_campaign`
  - [x] Docs gate：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md`
  - [x] 收尾运行 `python3 -m py_compile` 覆盖 touched Python files、`python3 -m ruff check .` 和 `git diff --check`。

### Review Findings

- [x] [Review][Patch] SQLite schema fork guard only compared exact table names; it could miss same-name column/index/trigger/view drift or prefixed/genre runtime tables. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Source/current save no-mutation evidence did not prove initial source runtime artifact absence or formal current save package immutability. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Player-view access checks only covered positive visible/hinted records and could miss hidden entity, relationship or progress leakage. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Story and validation-report wording still described the create-time ready-for-dev state after the story had moved to review. [_bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md]
- [x] [Review][Patch] Second review found schema snapshots were taken before test writes and forbidden schema names only checked table names; fixed by sampling schema after writes and checking all schema object names/table names. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Second review found hidden relationship negative coverage could pass for the wrong reason; fixed by making the relationship entity explicitly player-readable while its target endpoint remains hidden. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Second review found no-mutation evidence ignored empty directories/current registry and alternate current save roots; fixed by tree fingerprints plus default/env current save and registry fingerprints. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Second review found relationship `state` and forbidden `upsert_clocks` / `upsert_relationships` delta keys were not asserted; fixed by adding stable field and unknown top-level key checks. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Second review found docs overclaimed Context Slice coverage; fixed by limiting this smoke to model-boundary contracts and leaving full Context Slice/basic query/player loop coverage to the context gate. [docs/data-models.md]
- [x] [Review][Patch] Patch-verification review found hidden negative coverage only checked read APIs; fixed by asserting hidden IDs are absent from player list APIs while the visible relationship entity itself remains listable as an entity. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Patch-verification review found current-save fingerprints did not parse registry active save paths; fixed by fingerprinting default/env current save roots plus active save paths from `.aigm/save-registry.json`. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Patch-verification review found system tempfile root could be under a current save before save-dir checks ran; fixed by checking `tempfile.gettempdir()` before creating any temporary directory. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Patch-verification review found schema forbidden-name guard missed case variants, singular relationship prefixes and SQL-level schema drift; fixed by case-normalized name and SQL-fragment checks. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Patch-verification review found progress evidence only checked generic entity update evidence; fixed by asserting `last_ticked_turn_id` on clock-backed progress. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final patch-verification review found current-save evidence skipped missing configured roots and pending/lock workspace state; fixed by fingerprinting missing/existing default/env/registry active save roots and `.aigm` state files. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final patch-verification review found schema SQL guard could reject legal `relationship_id` fields; fixed by narrowing SQL fragments while retaining schema object name checks. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final patch-verification review found validation warnings were treated as hard failures despite the OK gate; fixed by relying on `validation.ok` plus explicit source runtime artifact absence. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final patch-verification review found hidden clock player tick validation was not covered; fixed by asserting hidden `tick_clocks` are unavailable under `caller_view="player"`. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Convergence review found ContentRegistry checks were global self-comparisons; fixed by loading each actual campaign package through the default registry and asserting manifest content keys/types match registered seed specs. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Convergence review found final gate records could look stale after later patches; fixed by deferring final gate status update until the final gates complete. [_bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md]
- [x] [Review][Patch] Final convergence review found Epic 2 remained in-progress after all Epic 2 stories were done; fixed by syncing `epic-2` to `done` in sprint-status. [_bmad-output/implementation-artifacts/sprint-status.yaml]
- [x] [Review][Patch] Final convergence review found tempfile root checks only protected current saves; fixed by also rejecting system temp roots inside source campaign packages. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final convergence review found source runtime artifact detection did not reuse production validator suffix/file rules; fixed by reusing `campaign_validation` runtime artifact constants. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final convergence review found env current save workspace root inference missed nested SaveManager layouts; fixed by discovering ancestor `.aigm/save-registry.json` roots. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final confirmation review found post-write inspect drift could hide FTS hidden-ref leaks; fixed by allowing only missing-card and expected-count FTS drift. [tests/test_cross_campaign_model_smoke.py]
- [x] [Review][Patch] Final confirmation review found no-mutation evidence only fingerprinted active registered save; fixed by fingerprinting every registered save path in discovered workspace registries. [tests/test_cross_campaign_model_smoke.py]

## 开发说明

### 来源上下文

- Epic 2 的完成目标是 Campaign/Save 分层、Entity/Relationship/Progress access contract、Content Type / Merge Contract 和通用 extension hooks 能支撑至少两个不同 capability profile 的 Campaign Package。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 2.6 已在 sprint change proposal 中收窄为 model-boundary smoke；完整 context assembly、ordinary query、preview、validation 和 player-safe loop smoke 已移到 Story 3.7。来源：`_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md`。
- PRD SM-7 要求至少两个题材或 capability profile 不同的 Campaign Package 复用同一 Kernel foundation flow。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-7 要求玩法差异放在 Campaign capabilities、content types、rules、initial state、prompts、author smoke tests 和轻量 hooks 中，而不是 fork Kernel core。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Save/Campaign canonical docs 要求 Campaign Package 是作者内容，Save Package 是运行事实，`data/game.sqlite` 是当前事实权威，正式 current save packages 不能被测试直接写。来源：`docs/save-and-campaign-packages.md`。

### 当前实现状态

- `examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 都是当前仓库里的可运行 example package。它们语言、初始地点、capability/content shape、relationship names 和 progress clocks 不同，适合作为跨 campaign smoke 对照样本。
- `rpg_engine.campaign_validation.validate_campaign_package()` 与 `run_campaign_smoke_tests()` 已覆盖 Campaign validate/test；`run_campaign_smoke_tests()` 已在内部复制 package 到 temp dir 并初始化临时运行态。
- `rpg_engine.save_service.init_v1_save()` 会拒绝把 Save 目录放进 source Campaign Package，并把运行态 `campaign.yaml`、`save.yaml`、SQLite、events、snapshot 和 cards 写入目标 Save Package。
- `rpg_engine.save_validation.inspect_save_package()` 暴露 `authority_contract`、`projection_health`、counts 和 schema/migration/projection evidence，可作为 save inspect 的 API 层 gate。
- `rpg_engine.entity_access.py`、`relationship_access.py`、`progress_access.py` 是 Story 2.3-2.5 已建立的命名 access contracts；Story 2.6 应复用这些接口，而不是新增平行读取路径。
- `rpg_engine.content_types.get_default_registry()` / `ContentTypeSpec.contract_metadata()` 是 Content Type / Merge Contract 的真值来源；不要维护第二份手写 content type truth table。

### 前序故事情报

- Story 2.1 固化 Campaign/Save ownership：普通 play 和 smoke 产生的 runtime facts 必须落在 Save Package，不得写回 source Campaign Package。
- Story 2.2 固化 Content Type / Merge Contract：registered content roots、delta key、runtime table、validation rule 和 merge policy 必须通过 `ContentRegistry` 对齐；`clock` 和 `relationship` 没有 runtime delta upsert key。
- Story 2.3 固化 Entity Identity Access Contract：跨 surface 读取实体必须复用 stable identity/visibility/status helper，避免 literal SQL 和 player-hidden 泄漏。
- Story 2.4 固化 Relationship Access Contract：relationship 仍是 entity-backed first-class access contract，AI/maintenance suggestions 不是事实。
- Story 2.5 固化 Progress / Clock Access Contract：progress 仍基于 `entities.type='clock'` + `clocks` side table + `tick_clocks` delta；runtime tick 需要 safe-visible reason 和 event audit。

### 架构合规要求

- 本 story 是 P1/P0-adjacent foundation regression，主要应新增 tests/docs；除非测试暴露真实缺口，不应改写核心 schema、commit chain、Context Slice contract、CLI/MCP authority 或 SaveManager player confirmation flow。
- 所有写入类测试必须使用临时 Save Package 或临时 package copy，不得写 `data/game.sqlite`、正式 current save、source examples 或用户 workspace registry。
- 不新增 campaign-specific runtime schema，不新增 `progress_tracks` 表，不新增 `relationship_*` 表，不新增 `upsert_clocks` 或 `upsert_relationships` turn delta key。
- Variation 应通过 package data 表达：capabilities、registered content roots、rules、relationship details/kinds、clock/progress records、palettes、random tables 和 smoke tests。
- 如果实现需要新增 extension point，必须同步 contract docs 和 boundary tests；若不新增 extension point，最终说明应明确“未新增 extension point”。

### 相关文件

- `tests/test_cross_campaign_model_smoke.py`：建议新增的 focused regression。
- `examples/v1_minimal_adventure/`、`examples/small_cn_campaign/`：跨 campaign source packages。
- `rpg_engine/campaign_validation.py`：Campaign validate/test API。
- `rpg_engine/save_service.py`、`rpg_engine/save_validation.py`：Save init / inspect API。
- `rpg_engine/content_types/registry.py`、`rpg_engine/content_types/core.py`：Content Type / Merge Contract。
- `rpg_engine/entity_access.py`、`rpg_engine/relationship_access.py`、`rpg_engine/progress_access.py`：model access contracts。
- `rpg_engine/delta_schema.py`：turn delta validation 和 `tick_clocks` contract。
- `docs/data-models.md`、`docs/save-and-campaign-packages.md`、`docs/testing-and-quality-gates.md`：canonical docs sync。
- `tests/test_campaign_validation.py`、`tests/test_content_registry.py`、`tests/test_entity_access.py`、`tests/test_relationship_access.py`、`tests/test_progress_access.py`、`tests/test_package_cli.py`、`tests/test_v1_cli.py`：adjacent regression patterns。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_cross_campaign_model_smoke.py
python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py
python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md
python3 -m ruff check .
git diff --check
```

如实现触碰 SaveManager、Runtime、Context Slice、CLI/MCP/platform surface、validation/commit authority 或 public JSON schemas，另跑对应高风险 gate，并更新相关 canonical docs。

### 残余风险与边界

- 本 story 不要求 context assembly、ContextBuildResult、prompt rendering、basic query 或 player-safe loop cross-campaign smoke；这是 Story 3.7。
- 本 story 不要求 resident AI advisory、intent candidate、preflight cache 或 proposal queue lifecycle。
- 本 story 不要求 Campaign diagnostics 完整性、missing relationship/progress completeness 报告或 author repair suggestions；这些在 Epic 5。
- 本 story 不要求新增 CLI output；如只新增 regression tests/docs，不应改变 public CLI/MCP contracts。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python stdlib、SQLite、pytest、Campaign validation、Save service、ContentRegistry、Entity/Relationship/Progress access contracts 和 validation pipeline；不要新增运行时依赖。

## Project Structure Notes

优先把跨 campaign smoke 放在 `tests/test_cross_campaign_model_smoke.py`，保持它是 focused regression，而不是 production runtime feature。若需要 helper，应放在测试文件内部或现有测试 fixture 模式附近；不要把测试编排逻辑加入 CLI、MCP、SaveManager 或 Runtime。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
- `_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`
- `_bmad-output/implementation-artifacts/2-4-relationship-access-contract.md`
- `_bmad-output/implementation-artifacts/2-5-progress-track-and-clock-access-contract.md`
- `docs/project-context.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/campaign_validation.py`
- `rpg_engine/save_service.py`
- `rpg_engine/save_validation.py`
- `rpg_engine/content_types/registry.py`
- `rpg_engine/entity_access.py`
- `rpg_engine/relationship_access.py`
- `rpg_engine/progress_access.py`
- `rpg_engine/delta_schema.py`
- `tests/test_campaign_validation.py`
- `tests/test_content_registry.py`
- `tests/test_entity_access.py`
- `tests/test_relationship_access.py`
- `tests/test_progress_access.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` failed as expected because the file did not exist.
- GREEN focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Focused + adjacent contract gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py tests/test_campaign_validation.py tests/test_content_registry.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider` passed with 57 tests and 72 subtests.
- Package/save regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py -p no:cacheprovider` passed with 104 tests and 32 subtests.
- Campaign CLI smoke gate: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign validate ./examples/small_cn_campaign && python3 -m rpg_engine campaign test ./examples/small_cn_campaign` passed.
- Docs/syntax/quality gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md && python3 -m py_compile tests/test_cross_campaign_model_smoke.py && python3 -m ruff check . && git diff --check` passed.
- Full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 615 tests and 728 subtests.
- First code-review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Second code-review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Patch-verification focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Final patch-verification focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Convergence patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Final focused + adjacent contract gate after convergence patch: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py tests/test_campaign_validation.py tests/test_content_registry.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider` passed with 57 tests and 72 subtests.
- Final docs/syntax/quality gate after convergence patch: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md && python3 -m py_compile tests/test_cross_campaign_model_smoke.py && python3 -m ruff check . && git diff --check` passed.
- Final package/save regression gate after convergence patch: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py -p no:cacheprovider` passed with 104 tests and 32 subtests.
- Final campaign CLI smoke gate after convergence patch: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign validate ./examples/small_cn_campaign && python3 -m rpg_engine campaign test ./examples/small_cn_campaign` passed.
- Final full regression gate after convergence patch: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 615 tests and 728 subtests in 135.19s.
- Final convergence patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py -p no:cacheprovider` passed with 2 tests and 4 subtests.
- Final convergence patch focused + adjacent contract gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py tests/test_campaign_validation.py tests/test_content_registry.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider` passed with 57 tests and 72 subtests.
- Final convergence patch docs/syntax/quality gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md && python3 -m py_compile tests/test_cross_campaign_model_smoke.py && python3 -m ruff check . && git diff --check` passed.
- Final convergence patch package/save regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py -p no:cacheprovider` passed with 104 tests and 32 subtests.
- Final convergence patch campaign CLI smoke gate: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign validate ./examples/small_cn_campaign && python3 -m rpg_engine campaign test ./examples/small_cn_campaign` passed.
- Final convergence patch full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 615 tests and 728 subtests in 136.36s.
- Final confirmation patch focused + adjacent contract gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_model_smoke.py tests/test_campaign_validation.py tests/test_content_registry.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider` passed with 57 tests and 72 subtests.
- Final confirmation patch docs/syntax/quality gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md && python3 -m py_compile tests/test_cross_campaign_model_smoke.py && python3 -m ruff check . && git diff --check` passed.
- Final confirmation patch package/save regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py -p no:cacheprovider` passed with 104 tests and 32 subtests.
- Final confirmation patch campaign CLI smoke gate: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign validate ./examples/small_cn_campaign && python3 -m rpg_engine campaign test ./examples/small_cn_campaign` passed.
- Final confirmation patch full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 615 tests and 728 subtests in 135.78s.

### Completion Notes List

- 新增跨 Campaign model-boundary focused regression，使用 `examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 验证 validate/test/init/inspect、ContentRegistry、entity/relationship/progress access、`tick_clocks` validation、SQLite schema sameness 和 source no-mutation。
- 第一轮 code review 的明确 patch 已应用：schema fork guard 升级为 SQLite schema signature + forbidden prefix 检查，source/current save no-mutation 证据补强，player-hidden 负例覆盖 entity/relationship/progress，create-time validation report wording 已消除 stale status 矛盾。
- 第二轮 code review 的明确 patch 已应用：schema 采样移到写入后，tree/current registry fingerprint 补齐，relationship hidden endpoint、`state` 和 forbidden delta keys 覆盖补齐，Context Slice 文档边界收窄。
- Patch-verification review 的明确 patch 已应用：player list API hidden guard、registry active save fingerprint、tempfile root 隔离、case-normalized schema SQL guard 和 `last_ticked_turn_id` evidence 补齐。
- Final patch-verification review 的明确 patch 已应用：missing current-save root / pending workspace state fingerprint、SQL blacklist 收窄、validation warning hard-fail 移除，以及 hidden clock player tick validation 负例补齐。
- Convergence review 的明确 patch 已应用：ContentRegistry 断言改为读取实际 campaign package content roots，并保留最终 gate 记录到最终验证后更新。
- Final verification gates passed after all review patches, and Story 2.6 / sprint-status are synced to `done`.
- Final convergence review 的明确 patch 已应用：Epic 2 同步为 done、tempfile source-root 隔离、production runtime artifact detection 规则复用，以及 nested current-save workspace registry discovery。
- Final confirmation review 的明确 patch 已应用：post-write inspect drift whitelist 收窄，所有 registered save packages 纳入 current-save no-mutation fingerprint。
- 同步 canonical docs，将 `tests/test_cross_campaign_model_smoke.py` 记录为 package/content/entity/relationship/progress foundation 变更的 focused gate。
- 未新增 production runtime code、public CLI/MCP output、extension point、fact store、commit chain 或 campaign-specific schema。

### File List

- `_bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md`
- `_bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `tests/test_cross_campaign_model_smoke.py`

## Change Log

- 2026-07-09: BMAD create-story generated and validated Story 2.6 context.
- 2026-07-09: Implemented cross-campaign model-boundary smoke regression and docs sync; story ready for code review.
- 2026-07-09: Applied first code-review patch pass and prepared story for re-review.
- 2026-07-09: Applied second code-review patch pass and prepared final verification gates.
- 2026-07-09: Applied patch-verification review pass and prepared final verification gates.
- 2026-07-09: Applied final patch-verification review pass and prepared final verification gates.
- 2026-07-09: Applied convergence review patch pass and prepared final verification gates.
- 2026-07-09: Ran final verification gates after convergence patch and synced Story 2.6 to done.
- 2026-07-09: Applied final convergence review patch pass, including Epic 2 done sync and source/current-save isolation hardening.
- 2026-07-09: Applied final confirmation review patch pass for FTS drift and registered save no-mutation coverage.
