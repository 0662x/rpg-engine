---
baseline_commit: 740eeab032bdbfd32ae73001ef1664d9488f545f
---

# Story 2.5: Progress Track and Clock Access Contract

Status: done

Completion note: Progress / Clock Access Contract implemented and reviewed.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 game host，
我希望 progress tracks 和 clocks 成为 first-class readable and validatable concepts，
从而任务、威胁、探索、关系、资源、时间和剧情阶段可以被追踪，而不需要 heavyweight quest system。

## 验收标准

1. 给定 Campaign 或 Save data 定义 clocks 或 progress tracks，当 progress access contract 读取它们时，必须返回 id、kind/type、scope、total segments、filled segments、visibility、status、trigger 或 tick rules、summary 和 update evidence；当前 `clock` content type、`clocks` table 和 `tick_clocks` delta 仍是 v1 实现基础。
2. 给定 gameplay 或 maintenance 尝试 tick 或 update progress，当 validation 运行时，引用的 clocks 必须存在，visibility / archived rules 必须按 caller mode 成立，并且 delta 必须用 event 或 `tick_clocks[*].reason` 解释为什么 progress 改变；progress updates 不能通过 unstructured narrative text 偷渡成事实。
3. 给定 host 询问“where is the game now?”，当 progress state 被查询时，active visible tracks 必须能帮助回答当前 goals、pressures、phases 和 open threats；hidden tracks 必须从 player-safe views 中排除。

## 任务 / 子任务

- [x] 建立命名 Progress Access Contract。 (AC: 1, 3)
  - [x] 新增 `rpg_engine/progress_access.py` 或等价就近模块，定义 `ProgressRecord`，暴露稳定字段：`id`、`kind` / `clock_type`、`scope`、`segments_total`、`segments_filled`、`visibility`、`status`、`summary`、`trigger_when_full`、parsed `tick_rules`、parsed `details`、`last_ticked_turn_id`、`updated_turn_id`、`updated_at`。
  - [x] 提供 `read_progress()` / `list_progress()` 或等价 API，默认排除 archived clock entity；对 `view="player"` 同时排除 `entities.visibility='hidden'` 和 `clocks.visibility='hidden'` 的 tracks。
  - [x] 复用 `rpg_engine.entity_access.read_entity()` / `list_entities()`、`visibility.py` normalization 和现有 clock subtype visibility behavior；不要复制新的 hidden/archive literal SQL 分支。
  - [x] 保持当前 v1 storage：progress 仍以 `entities.type='clock'` + `clocks` side table 表达；不得新增 `progress_tracks` SQL table、并行 progress identity system 或 mandatory quest ontology。

- [x] 将 progress / clock tick validation 接入现有 validation path。 (AC: 1, 2)
  - [x] 增加 helper 校验 `tick_clocks` references，例如 `validate_delta_progress_references()`；每个 tick 必须引用存在且未 archived 的 clock entity，且 caller view 为 player 时不得引用 hidden clock entity 或 hidden clock side table row。
  - [x] 保持 `tick_clocks` 是 runtime progress mutation 的唯一 v1 delta path；不要新增 `upsert_clocks` turn delta key，也不要允许 narrative-only event 声称 progress 已改变但没有结构化 `tick_clocks`。
  - [x] 对 malformed tick item、空 id、leading/trailing whitespace、非字符串 id、非法 clock id、missing clock、archived clock、player-unavailable hidden clock、非整数或 0 delta、空 `reason` 字段返回稳定 validation error。
  - [x] 保持现有 state-changing delta 规则：有 `tick_clocks` 时必须有 event；如果实现使用 `reason`，它只能是 tick evidence，不得替代 event audit row。

- [x] 增加 focused progress access tests。 (AC: 1, 2, 3)
  - [x] 新增 `tests/test_progress_access.py` 或扩展相邻测试，覆盖 `read_progress()` / `list_progress()` 返回 stable fields、parsed `tick_rules`、scope、summary、visibility/status 和 update evidence。
  - [x] 覆盖 player view 读不到 hidden clock row、hidden entity row 和 archived clock；GM / maintenance view 可以读取 hidden clock 并带清晰字段。
  - [x] 覆盖 runtime delta clock tick validation：既有 clock 通过，missing/empty/non-string/whitespace/invalid/archived/player-hidden clock 失败，并通过 `validate_delta_schema(..., conn)` 或新 helper 集成断言。
  - [x] 覆盖 `tick_clocks[*].reason` shape（必须是安全可见的非空字符串）和 “tick without event” 仍被拒绝。
  - [x] 使用临时 Save Package 或 fixture copy，不直接修改正式 current save package。

- [x] 同步 canonical docs 与 component inventory。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 的 Progress / Clock Access Contract 段，说明 stable read fields、clock subtype visibility、runtime tick validation、event/reason evidence 和 no direct AI fact authority。
  - [x] 更新 `docs/component-inventory.md`，登记 Progress Access 模块或等价职责。
  - [x] 如实现只改变 internal contract，不新增 CLI/MCP/public output，则不要扩大 `docs/cli-contracts.md` / `docs/mcp-contracts.md` scope。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN focused tests：`python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_validation_pipeline.py`
  - [x] Package/content regression：`python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py`
  - [x] Current native visibility/write safety gate：`python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_current_native_context.py tests/test_current_native_actions.py`
  - [x] Campaign smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`
  - [x] Docs gate：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-5-progress-track-and-clock-access-contract.md`
  - [x] 收尾运行 `python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py`、`python3 -m ruff check .` 和 `git diff --check`。

### Review Findings

- [x] [Review][Patch] player caller mode 未接入 progress tick validation [rpg_engine/validation_pipeline.py:298]
- [x] [Review][Patch] clock id 判定比现有 `clock:` content contract 更窄 [rpg_engine/progress_access.py:14]
- [x] [Review][Patch] narrative-only progress update event 未强制结构化 `tick_clocks` [rpg_engine/delta_schema.py:278]
- [x] [Review][Patch] `tick_clocks[*].reason` 可由零宽/格式字符伪装为空证据 [rpg_engine/delta_schema.py:251]
- [x] [Review][Patch] 二次 review：generic / mismatched progress event 仍可绕过结构化 `tick_clocks` [rpg_engine/delta_schema.py:294]
- [x] [Review][Patch] 二次 review：hidden entity clock 的 `ProgressRecord.visibility` 未反映有效 player visibility [rpg_engine/progress_access.py:147]
- [x] [Review][Patch] 二次 review：Campaign clock content id validation 与 runtime clock id contract 不一致 [rpg_engine/content_types/core.py:70]
- [x] [Review][Patch] 二次 review：standalone proposal validation 未按 `player_turn_commit` 使用 player progress visibility [rpg_engine/proposal.py:283]
- [x] [Review][Patch] 二次 review：`turn_delta.schema.json` 未同步 `tick_clocks[*].id` / `reason` shape [schemas/turn_delta.schema.json:142]
- [x] [Review][Patch] 最终 review：plain narrative / top-level progress claims 仍可绕过结构化 `tick_clocks` [rpg_engine/delta_schema.py:294]
- [x] [Review][Patch] 最终 review：`progress:` claim 可被无关 `tick_clocks` 掩护 [rpg_engine/delta_schema.py:316]
- [x] [Review][Patch] 最终 review：控制字符 reason 可伪装成有效 tick evidence [rpg_engine/progress_access.py:229]
- [x] [Review][Patch] 最终 review：event audit fields 可由零宽文本满足形式要求 [rpg_engine/delta_schema.py:134]
- [x] [Review][Patch] 最终 review：JSON schema 与 runtime `tick_clocks` shape 仍不完全一致 [schemas/turn_delta.schema.json:142]
- [x] [Review][Patch] clean review：clock id narrative parser / runtime / schema 合同仍不一致 [rpg_engine/progress_access.py:14]
- [x] [Review][Patch] clean review：plain clock-name narrative claim 仍可绕过结构化 `tick_clocks` [rpg_engine/delta_schema.py:353]
- [x] [Review][Patch] clean review：`response_acceptance` 无 proposal 时未按 player view 校验 hidden clocks [rpg_engine/validation_pipeline.py:305]
- [x] [Review][Patch] clean review：nested payload progress claim 可绕过 narrative-only guard [rpg_engine/delta_schema.py:368]
- [x] [Review][Patch] clean review：无 reason 的 tick 可由无关普通 event 满足 audit 形式要求 [rpg_engine/delta_schema.py:256]
- [x] [Review][Patch] clean review：event field / reason safe-visible schema 与 runtime 仍需统一 [schemas/turn_delta.schema.json:66]
- [x] [Review][Patch] clean review follow-up：preview delta builders 丢弃 suggested clock tick reason [rpg_engine/preview.py:1019]
- [x] [Review][Patch] final clean review：array payload progress claim 可绕过 narrative-only guard [rpg_engine/delta_schema.py:393]
- [x] [Review][Patch] final clean review：C1 control chars 未纳入 safe-visible runtime/schema 范围 [rpg_engine/progress_access.py:17]
- [x] [Review][Patch] final clean review：中文 / completed / increased / fraction progress 文本未被识别 [rpg_engine/delta_schema.py:454]
- [x] [Review][Patch] final clean review：nested payload clock-name claim 未传入 known clock names [rpg_engine/delta_schema.py:407]
- [x] [Review][Patch] final clean review：空泛 `clock_tick` event 仍可替代 tick reason [rpg_engine/delta_schema.py:421]
- [x] [Review][Patch] terminal clean review：无 reason tick 可由 id-only event evidence 放行，最终收紧为 `reason` 必填 [rpg_engine/delta_schema.py:248]
- [x] [Review][Decision] terminal review：generic `clock|progress` + update verb 保守阻断会误杀普通叙事；用户选择 option 2，收窄为明确 clock id、known clock name、payload progress key 或 explicit progress event type 才触发 [rpg_engine/delta_schema.py:382]
- [x] [Review][Patch] terminal review：variation selectors / tag characters / NFKC 兼容重音可伪装 safe-visible evidence [rpg_engine/progress_access.py:17]
- [x] [Review][Patch] terminal review：格式字符可拆开 progress update verb 绕过 narrative detector [rpg_engine/delta_schema.py:382]
- [x] [Review][Patch] terminal review：嵌套结构化 payload `clock_id/id + delta` 可绕过 progress claim guard [rpg_engine/delta_schema.py:400]
- [x] [Review][Patch] terminal review：turn delta 可通过 `upsert_entities[type=clock]` 修改 progress-facing clock entity 字段 [rpg_engine/delta_schema.py:178]
- [x] [Review][Patch] terminal review：recipe preview 将 bool delta 强转为整数 tick [rpg_engine/preview.py:1437]
- [x] [Review][Patch] terminal review：narrative guard 漏掉 escalates/resolved/上升 等常见进度动词，known clock name substring 也会误杀短名称 [rpg_engine/delta_schema.py:458]
- [x] [Review][Patch] post-patch review：`upsert_entities` 可用 `id=clock:*` + 非 clock type 伪装修改 clock entity [rpg_engine/delta_schema.py:197]
- [x] [Review][Patch] post-patch review：payload key、兄弟节点分散的 `clock_id` / update signal、`segments_filled` / `status=completed` 可绕过 structured tick guard [rpg_engine/delta_schema.py:425]
- [x] [Review][Patch] post-patch review：safe-visible runtime/schema 仍漏掉 U+0600 format chars 与 U+2017/U+203E/U+FFE3 NFKC 兼容字符 [rpg_engine/progress_access.py:17]
- [x] [Review][Patch] post-fix review：payload progress key 本身（`progress`、`segments_filled`、`status=completed`）仍可在无 `tick_clocks` 时通过 [rpg_engine/delta_schema.py:422]
- [x] [Review][Patch] final candidate review：safe-visible schema 仍漏掉 runtime NFKC 会拒绝的 `U+FE49..FE4C` / `U+2ADC` 等兼容字符 [schemas/turn_delta.schema.json:179]
- [x] [Review][Patch] final candidate review：narrative clock id regex 会吞掉句末标点，导致有结构化 tick 也被误杀 [rpg_engine/delta_schema.py:386]
- [x] [Review][Patch] final review 2：Story 顶部 `Completion note` 与 Story 2.5 不符 [2-5-progress-track-and-clock-access-contract.md:9]

## 开发说明

### 来源上下文

- Epic 2 要求 Campaign/Save 分层、Entity/Relationship/Progress access contract、Content Type / Merge Contract 和通用 extension hooks 能支撑不同 Campaign Package。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 2.5 明确 progress reads 必须返回 id、kind/type、scope、segments、visibility、status、trigger/tick rules 和 update evidence，并且继续基于 `clock` content type、`clocks` table 和 `tick_clocks` delta。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-8 要求 Campaign Package 定义、Save Package 随游玩变化的 progress tracks，用于任务、探索、关系、资源、时间、剧情阶段或 campaign goals。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-4 要求 Progress Track / Clock 是 first-class access contract；v1 优先沿用 `clock` content type、`clocks` 表和 `tick_clocks` delta，不先构建复杂 quest ontology。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Save/Campaign canonical docs 要求普通 play 后的 progress changes 只落在 Save Package fact boundary，safe patch 不允许 tick clock。来源：`docs/save-and-campaign-packages.md`。

### 当前实现状态

- `rpg_engine/content_types/core.py::validate_clock_record()` 已校验 Campaign clock 的 `id` 前缀、`name`、`trigger_when_full`、`segments_total` 和 `segments_filled` bounds。
- `rpg_engine/content_types/core.py::_upsert_clock()` 与 `rpg_engine/db.py::upsert_clock()` 当前把 clock 同时写入 `entities.type='clock'` 和 `clocks` side table；`clocks.visibility` 可能比 entity visibility 更严格。
- `rpg_engine/entity_access.py` 已在 `read_entity()` / `list_entities()` 中对 clock subtype visibility 做特殊处理：player view 会排除 `clocks.visibility='hidden'` 的 clock，即使 entity row 本身不是 hidden。Progress access 必须复用这个行为。
- `rpg_engine/delta_schema.py::validate_tick_clocks()` 当前检查 `tick_clocks` array、item object、`id`、非零整数 `delta` 和存在的 `clocks` row；它尚未形成命名 Progress Access Contract，也没有稳定处理 archived/player-hidden clock reference。
- `rpg_engine/save.py::save_turn_delta()` 是 clock tick 的事实写入点：它按 `tick_clocks[*].delta` clamp `segments_filled` 到 `0..segments_total`，并写 `last_ticked_turn_id` 与 entity update evidence。
- `rpg_engine/packages/service.py::current_clock_records()` 已为 package diff/merge 读取 clock rows；实现 Progress Access Contract 时不要破坏 package merge ownership：author-owned clock definition，runtime-owned `segments_filled` / `last_ticked_turn_id`。
- `tests/test_entity_access.py` 已覆盖 hidden clock subtype 在 entity access、FTS、cards、context 和 palette 等 player-facing surfaces 中不泄露；Progress access tests 应复用同一隐私期待。

### 前序故事情报

- Story 2.1 固化 Campaign/Save ownership：普通 play 后产生的 relationship/progress changes 只能落在 Save Package fact boundary，不能写回 source Campaign Package。
- Story 2.2 固化 Content Type / Merge Contract：`clock` 是 registered content type，但没有 delta upsert key；package merge policy author-owned clock definition，runtime-owned filled segments / last tick。
- Story 2.3 新增 `entity_access.py` 后的关键经验是所有 player-facing reads 必须复用 shared visibility/status helpers，避免 literal SQL、Unicode/format whitespace bypass、hidden clock subtype leak 和 derived artifact regression。
- Story 2.4 新增 `relationship_access.py` 的模式可复用：小型 dataclass record + read/list helpers + validation helper + focused tests + docs sync，不引入专用 SQL 表或第二套身份系统。

### 架构合规要求

- Progress Access Contract 是 read/validation support，不拥有写入权威。事实写入仍必须经过 Campaign import/package maintenance 或 runtime validation/commit。
- v1 不新增 progress 专用 SQL 表；如将来需要专表、quest ontology 或 storylet scheduler，必须另开 architecture/story。
- Progress / clock identity 必须继续使用 `entities.id`，通常为 `clock:` 前缀；不要引入新的 progress id system。
- Player-safe progress reads 必须过滤 hidden/archived/off-view clock；GM/maintenance 必须显式选择 hidden-read view。
- Runtime progress mutation 应通过现有 `tick_clocks` 进入 delta validation；不要新增未经授权的 shortcut 或 content delta path。

### 相关文件

- `rpg_engine/progress_access.py`：建议新增的 Progress / Clock Access Contract 模块。
- `rpg_engine/entity_access.py`：必须复用的 entity identity、visibility/status 和 clock subtype visibility helper。
- `rpg_engine/delta_schema.py`：runtime delta schema、`tick_clocks` shape 和 database reference validation 接入口。
- `rpg_engine/content_types/core.py`：clock content type record validation / import shape。
- `rpg_engine/db.py`、`rpg_engine/save.py`：clock storage 和 tick commit behavior。
- `rpg_engine/content_validation.py`：maintenance/content validation，不应引入 `upsert_clocks` bypass。
- `rpg_engine/packages/service.py`：current clock records、merge/dry-run behavior。
- `docs/data-models.md`、`docs/component-inventory.md`：canonical docs sync。
- `tests/test_progress_access.py`、`tests/test_entity_access.py`、`tests/test_validation_pipeline.py`、`tests/test_campaign_validation.py`、`tests/test_package_cli.py`、`tests/test_package_save_condition_coverage.py`：focused tests。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_validation_pipeline.py
python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-5-progress-track-and-clock-access-contract.md
python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py
git diff --check
```

如 implementation touches context/render/cards/player-facing progress output，另跑：

```bash
python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_current_native_context.py tests/test_current_native_actions.py
```

### 残余风险与边界

- 本 story 不要求 Relationship / Progress context inclusion；relationship/progress 进入 Context Slice 是 Story 3.4 的主要范围。
- 本 story 不要求 cross-campaign model smoke；那是 Story 2.6。
- 本 story 不要求 Campaign diagnostics 的 progress completeness 报告；那是 Story 5.2。
- 本 story 不要求 proposal queue apply/revert；AI/maintenance progress suggestions 只需保持 suggestion != fact，并进入 existing validated/proposal/maintenance path。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python stdlib、dataclasses、SQLite、pytest、`entity_access`、`visibility`、`ContentRegistry`、`PackageSource` 和 validation pipeline；不要新增运行时依赖。

## Project Structure Notes

Progress access 应与 `entity_access.py`、`relationship_access.py` 同层，保持 helper 小而明确。优先通过 `ProgressRecord` + read/list/validate helper 形成 contract；不要把 clock storage parsing 分散到 CLI、MCP、context、package caller 或 action resolver 中。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
- `_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`
- `_bmad-output/implementation-artifacts/2-4-relationship-access-contract.md`
- `docs/project-context.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/authoring-guide.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/entity_access.py`
- `rpg_engine/relationship_access.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/content_types/core.py`
- `rpg_engine/db.py`
- `rpg_engine/save.py`
- `rpg_engine/content_validation.py`
- `rpg_engine/packages/service.py`
- `tests/test_entity_access.py`
- `tests/test_relationship_access.py`
- `tests/test_validation_pipeline.py`
- `tests/test_campaign_validation.py`
- `tests/test_package_cli.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED test: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` failed as expected with missing `rpg_engine.progress_access`.
- GREEN focused test: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` passed with 2 tests.
- Focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_validation_pipeline.py -p no:cacheprovider` passed with 33 tests and 11 subtests.
- Condition combination compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_condition_combinations.py tests/test_progress_access.py tests/test_validation_pipeline.py -p no:cacheprovider` passed with 28 tests and 89 subtests.
- Package/content regression: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py -p no:cacheprovider` passed with 84 tests and 63 subtests.
- Current native gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_current_native_context.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 22 tests and 24 subtests.
- Campaign gates: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` returned OK; `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` returned OK for 12 smoke tests.
- Docs/syntax/quality gates: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-5-progress-track-and-clock-access-contract.md` checked 87 Markdown files; `python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py` passed; `python3 -m ruff check .` passed; `git diff --check` passed.
- Full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 610 tests and 705 subtests.
- Review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_validation_pipeline.py -p no:cacheprovider` passed with 12 tests.
- Review patch compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_condition_combinations.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_progress_access.py tests/test_validation_pipeline.py -p no:cacheprovider` passed with 53 tests and 100 subtests.
- Second review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_validation_pipeline.py tests/test_core_rule_condition_coverage.py -p no:cacheprovider` passed with 24 tests.
- Second review patch syntax/schema sync gate: `python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/validation_pipeline.py rpg_engine/proposal.py rpg_engine/content_types/core.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0.
- Final review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_validation_pipeline.py tests/test_core_rule_condition_coverage.py -p no:cacheprovider` passed with 24 tests.
- Final review patch syntax/schema sync gate: `python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/validation_pipeline.py rpg_engine/proposal.py rpg_engine/content_types/core.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0.
- Clean review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_validation_pipeline.py tests/test_core_rule_condition_coverage.py tests/test_condition_combinations.py -p no:cacheprovider` passed with 41 tests and 89 subtests.
- Clean review patch syntax/schema sync gate: `python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/validation_pipeline.py rpg_engine/proposal.py rpg_engine/content_types/core.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0.
- Clean review follow-up current-native gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_current_native_context.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 22 tests and 24 subtests.
- Clean review follow-up focused compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_validation_pipeline.py tests/test_condition_combinations.py tests/test_core_rule_condition_coverage.py -p no:cacheprovider` passed with 65 tests and 100 subtests.
- Final clean review focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_validation_pipeline.py tests/test_core_rule_condition_coverage.py tests/test_condition_combinations.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 47 tests and 97 subtests.
- Final clean review runtime C1 gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` passed with 3 tests.
- Terminal clean review focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_validation_pipeline.py tests/test_core_rule_condition_coverage.py tests/test_condition_combinations.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 47 tests and 97 subtests.
- Terminal clean review syntax/schema sync gate: `python3 -m py_compile rpg_engine/preview.py rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/validation_pipeline.py rpg_engine/proposal.py rpg_engine/content_types/core.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0.
- Terminal review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` passed with 4 tests and 2 subtests.
- Terminal review patch adjacent gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_validation_pipeline.py tests/test_core_rule_condition_coverage.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 27 tests and 8 subtests.
- Terminal review patch compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_validation_pipeline.py tests/test_condition_combinations.py tests/test_core_rule_condition_coverage.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 72 tests and 110 subtests.
- Terminal review patch syntax/schema/lint gate: `python3 -m py_compile rpg_engine/preview.py rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/validation_pipeline.py rpg_engine/proposal.py rpg_engine/content_types/core.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0; `python3 -m ruff check rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/preview.py tests/test_progress_access.py` passed.
- Post-patch review focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` passed with 4 tests and 10 subtests.
- Post-patch review compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_validation_pipeline.py tests/test_condition_combinations.py tests/test_core_rule_condition_coverage.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 72 tests and 118 subtests.
- Post-patch review package/content gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py -p no:cacheprovider` passed with 84 tests and 63 subtests.
- Post-patch review syntax/schema/lint gate: `python3 -m py_compile rpg_engine/progress_access.py rpg_engine/delta_schema.py rpg_engine/preview.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0; `python3 -m ruff check rpg_engine/progress_access.py rpg_engine/delta_schema.py tests/test_progress_access.py` passed.
- Post-fix review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` passed with 4 tests and 13 subtests.
- Post-fix review patch compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_validation_pipeline.py tests/test_condition_combinations.py tests/test_core_rule_condition_coverage.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 72 tests and 121 subtests.
- Post-fix review patch syntax/lint gate: `python3 -m py_compile rpg_engine/delta_schema.py` passed; `python3 -m ruff check rpg_engine/delta_schema.py tests/test_progress_access.py` passed.
- Final candidate review patch focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py -p no:cacheprovider` passed with 4 tests and 19 subtests.
- Final candidate review patch compatibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_progress_access.py tests/test_entity_access.py tests/test_relationship_access.py tests/test_validation_pipeline.py tests/test_condition_combinations.py tests/test_core_rule_condition_coverage.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 72 tests and 127 subtests.
- Final candidate review patch syntax/schema/lint gate: `python3 -m py_compile rpg_engine/delta_schema.py rpg_engine/progress_access.py` passed; `cmp -s schemas/turn_delta.schema.json rpg_engine/resources/schemas/turn_delta.schema.json` returned 0; `python3 -m ruff check rpg_engine/delta_schema.py tests/test_progress_access.py` passed.
- Final review 2 artifact patch gate: `git diff --check` passed after correcting the story completion note.
- Final review 2 result: Blind Hunter clean, Edge Case Hunter clean, Acceptance Auditor artifact recheck clean; no remaining `[Review][Patch]` or `[Review][Decision]`.
- Final verification gates: package/content `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py -p no:cacheprovider` passed with 84 tests and 63 subtests; current native `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_current_native_context.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 22 tests and 24 subtests; campaign validate/test returned OK; docs links, `python3 -m ruff check .`, `python3 -m py_compile ...`, schema `cmp`, and `git diff --check` passed.
- Final full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 613 tests and 724 subtests.

### Completion Notes List

- Added `rpg_engine.progress_access.ProgressRecord` plus `read_progress()` and `list_progress()` as the stable progress/clock read contract over current clock-backed storage.
- Added player-safe filtering through existing `entity_access` clock subtype visibility behavior, so hidden clock rows, hidden entity rows, and archived clocks are excluded from player view.
- Added `validate_delta_progress_references()` and routed `delta_schema.validate_database_refs()` through it so runtime `tick_clocks` references can report missing, archived, unavailable, malformed, and invalid reason cases.
- Hardened `tick_clocks` shape validation for leading/trailing whitespace, invalid clock ids, boolean deltas, and mandatory safe-visible `reason` fields while preserving event audit requirements for state-changing deltas.
- Applied first review patches: `player_turn_commit` now validates progress references with player visibility, existing broad `clock:` IDs remain tickable unless they contain unsafe whitespace/control characters, narrative-only progress update events require structured `tick_clocks`, and zero-width/format-only reasons are rejected.
- Applied second review patches: generic or mismatched progress event claims now require matching structured ticks, ProgressRecord effective visibility reflects entity-layer hidden state, content/proposal/schema entry points share the runtime clock id and player visibility contract.
- Applied final review patches: plain narrative/top-level progress claims now require structured ticks, `progress:` claims cannot be covered by unrelated clock ticks, visible-text validation rejects control/format-only evidence and event audit fields, and both turn-delta schemas were tightened to match runtime tick id/reason constraints.
- Applied clean review patches: clock ids now use one ASCII-safe runtime/content/schema/parser contract, response acceptance validates progress refs with player visibility, nested payload and known-clock-name progress claims require structured ticks, and ticks now require explicit safe-visible reason evidence.
- Updated preview delta builders so suggested clock ticks preserve their generated reason evidence.
- Applied final clean review patches: payload arrays are scanned for progress claims, C1 control chars are unsafe in runtime/schema evidence, Chinese/completed/increased/fraction progress text is detected, nested payload clock-name claims use known clocks, and generic clock events no longer explain reasonless ticks.
- Applied terminal clean review patch: no-reason ticks are rejected at shape/schema validation instead of relying on event inference.
- Applied terminal review decision and patches: generic `clock|progress` text no longer triggers progress mutation guard without a concrete progress binding; safe-visible runtime/schema now reject variation selectors, tag characters, and NFKC compatibility accent-only text; narrative matching strips unsafe formatting characters before verb detection; nested structured payload progress updates are recursive; turn delta rejects `upsert_entities[type=clock]`; recipe suggested ticks no longer coerce bool deltas.
- Applied post-patch review patches: turn delta rejects `upsert_entities` for any `clock:*` id even when the type is disguised, payload progress claims merge ids and update signals across keys, sibling dict/list nodes, segments/status fields, and safe-visible runtime/schema reject additional format / NFKC-compatible invisible evidence characters.
- Applied post-fix review patch: payload progress keys now count as progress update claims even without a concrete id, so they require structured `tick_clocks` unless a tick is already present.
- Applied final candidate review patches: schema safe-visible now uses the runtime NFKC unsafe closure for compatible punctuation/mark characters, and narrative id extraction strips ordinary sentence-ending punctuation before comparing to structured ticks.
- Corrected the story completion note to describe Progress / Clock Access Contract completion.
- Added focused progress access tests and verified compatibility with existing condition-combination, package/content, current native, campaign smoke, docs, syntax, lint, whitespace, and full regression gates.
- Final review 2 completed clean and story/sprint status were synchronized to done.
- Synced `docs/data-models.md` and `docs/component-inventory.md` with the new Progress / Clock Access Contract.

### File List

- `_bmad-output/implementation-artifacts/2-5-progress-track-and-clock-access-contract.md`
- `_bmad-output/implementation-artifacts/2-5-progress-track-and-clock-access-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `rpg_engine/content_types/core.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/progress_access.py`
- `rpg_engine/preview.py`
- `rpg_engine/proposal.py`
- `rpg_engine/resources/schemas/turn_delta.schema.json`
- `rpg_engine/validation_pipeline.py`
- `schemas/turn_delta.schema.json`
- `tests/test_core_rule_condition_coverage.py`
- `tests/test_current_native_actions.py`
- `tests/test_progress_access.py`
- `tests/test_validation_pipeline.py`

## Change Log

- 2026-07-09: Created story context for Progress Track and Clock Access Contract.
- 2026-07-09: Started implementation for Progress Track and Clock Access Contract.
- 2026-07-09: Implemented Progress / Clock Access Contract, runtime tick validation, focused tests, docs sync, and verification gates.
