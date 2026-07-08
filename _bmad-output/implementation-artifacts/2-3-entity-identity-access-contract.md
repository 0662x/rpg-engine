---
baseline_commit: ef1aa2d123aa0c8781c06770f046f8828620bfec
---

# Story 2.3: Entity Identity Access Contract

Status: done

Completion note: Entity Identity Access Contract implemented with stable read helpers, delta reference validation reuse, docs sync, and verification gates.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 AI host 或 runtime caller，
我希望拥有稳定的 entity access contract，
从而 characters、locations、items、clues、projects、rules、clocks 和其他 game objects 能被一致引用。

## 验收标准

1. 给定 entity 由 Campaign import 或 validated runtime delta 创建，当它被存储时，必须拥有稳定的 `entities.id`、`type`、`name`、`status`、`visibility`、可选 `location_id` / `owner_id`、`summary`、`details` 和 update evidence；typed side tables 必须引用 entity，而不是替代 identity。
2. 给定 caller 为 gameplay、diagnostics、context 或 authoring 读取 entities，当它使用 entity access contract 时，读取必须按 caller mode 应用 status 与 visibility filters；调用方不需要知道常用 identity 字段来自哪个表。
3. 给定 runtime mutation 引用 entities，当 validation 运行时，引用的 entity 必须已存在或在同一 validated delta 中创建；active entities 不得违反 `location_id` / `owner_id` invariant。

## 任务 / 子任务

- [x] 建立命名 Entity Identity access contract。 (AC: 1, 2)
  - [x] 新增 `rpg_engine/entity_access.py` 或就近同等模块，定义 `EntityRecord` / contract helper，暴露稳定字段：`id`、`type`、`name`、`status`、`visibility`、`location_id`、`owner_id`、`summary`、parsed `details`、`updated_turn_id`、`updated_at`。
  - [x] 提供 `read_entity()` / `list_entities()` 或等价 API，默认排除 `status='archived'` 并在 player view 排除 hidden；GM / maintenance view 可读取 hidden。
  - [x] 对 `clock` entity 同时尊重 `clocks.visibility`，不要让 hidden clock 通过普通 entity read 泄露。
  - [x] 不新增并行 identity table，不改变 `entities.id` 作为共享锚点；typed side tables 仍通过 `entity_id` foreign key 扩展结构化字段。

- [x] 将 runtime mutation 引用校验收敛到 entity access contract。 (AC: 3)
  - [x] 将 `delta_schema.validate_database_refs()` 中的 entity existence / same-delta upsert reference 逻辑抽到或复用 entity access helper，保持现有错误 wording 尽量稳定。
  - [x] 校验 `location_before`、`location_after`、`meta.current_location_id`、`upsert_entities[*].location_id`、`owner_id`、`character.species_id`、`location.parent_id`、`crop_plot.crop_entity_id`：引用必须已在 DB 存在，或属于同一 delta 的 `upsert_entities[*].id`。
  - [x] 保留 active entity 不能同时设置 `owner_id` 和 `location_id` 的规则；若实现扩展 status 判断，只能让 `status != archived` 的 active-like entity 受该 invariant 约束，不要放松当前默认行为。
  - [x] 不把 AI candidate、proposal approval、package merge 或 content sync 变成绕过 validation 的新写入路径。

- [x] 增加 focused entity access tests。 (AC: 1, 2, 3)
  - [x] 新增或扩展 `tests/test_entity_access.py` / `tests/test_entity_resolution.py`，覆盖 player view 读不到 hidden entity、GM / maintenance 能读到、archived 默认被排除、common identity fields 与 parsed details 可用。
  - [x] 覆盖 hidden `clock` subtype：即使 `entities.visibility` 非 hidden，`clocks.visibility='hidden'` 也不能通过 player view access contract 读取。
  - [x] 覆盖 runtime delta reference：引用既有 entity 通过、引用同一 delta 新建 entity 通过、缺失引用失败、`owner_id` + `location_id` 同时存在失败。
  - [x] 使用临时 Save Package 或 fixture copy，不直接修改正式 current save package。

- [x] 同步 canonical docs 与 component inventory。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 的 Entity Model 段，说明 entity access contract、status/visibility filter、hidden clock subtype filter、同一 delta 引用规则和 `location_id` / `owner_id` invariant。
  - [x] 如新增模块，更新 `docs/component-inventory.md` 的运行时/数据模型或内容模块列表。
  - [x] 仅当 CLI/MCP/public contract 输出改变时更新 `docs/cli-contracts.md` 或 `docs/mcp-contracts.md`；本 story 不应为了暴露新 CLI 而扩大 scope。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN focused tests：`python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py`
  - [x] Campaign/Package regression：`python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py`
  - [x] Current native visibility/write safety gate：`python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py`
  - [x] Campaign smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`。
  - [x] Docs gate：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`
  - [x] 收尾运行 `git diff --check`；如新增 Python 模块，运行 `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py`。

### Review Findings

- [x] [Review][Patch] `list_entities()` 默认 archived 过滤可被 `statuses` 绕过 [`rpg_engine/entity_access.py:94`]
- [x] [Review][Patch] `list_entities()` 对单个字符串 `statuses` / `types` 会按字符拆分 [`rpg_engine/entity_access.py:94`]
- [x] [Review][Patch] `list_entities()` 对非法 `limit` 通过 `int()` 触发运行时异常 [`rpg_engine/entity_access.py:118`]
- [x] [Review][Patch] `validate_delta_entity_references()` 直接收到非 dict delta 时会 AttributeError [`rpg_engine/entity_access.py:137`]
- [x] [Review][Patch] entity access tests 未覆盖 `validate_delta_schema(..., conn)` schema 集成和有效 owner/location 的 invariant 失败路径 [`tests/test_entity_access.py:116`]
- [x] [Review][Patch] validation report 的历史 smoke 命令仍断言 ready-for-dev，当前 review 状态下会产生误导验证证据 [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.validation-report.md:71`]
- [x] [Review][Patch] validation report summary / next step 仍像当前状态一样提示 ready-for-development / dev-story [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.validation-report.md:11`]
- [x] [Review][Patch] entity access status/visibility filters 未处理大小写或空白变体 [`rpg_engine/entity_access.py:67`]
- [x] [Review][Patch] runtime delta reference checks 会跳过空串或 `0` 引用值 [`rpg_engine/entity_access.py:140`]
- [x] [Review][Patch] `crop_plot.crop_entity_id` 未纳入 runtime entity reference validation [`rpg_engine/entity_access.py:177`]
- [x] [Review][Patch] `include_archived` 非布尔真值可绕过默认 archived 过滤 [`rpg_engine/entity_access.py:62`]
- [x] [Review][Patch] entity reference 值带首尾空白时校验通过但提交外键可能失败 [`rpg_engine/entity_access.py:214`]
- [x] [Review][Patch] 空 `location_before` / `location_after` 会在 schema 与 DB reference validation 中重复报错 [`rpg_engine/delta_schema.py:266`]
- [x] [Review][Patch] `docs/data-models.md` Entity Access Contract 引用字段清单漏掉 `crop_plot.crop_entity_id` [`docs/data-models.md:242`]
- [x] [Review][Patch] SQLite `trim()` 默认不去除 tab/newline，status/visibility 过滤仍可被边缘空白绕过 [`rpg_engine/entity_access.py:68`]
- [x] [Review][Patch] `crop_plot.crop_entity_id` 缺失或为 null 时 reference helper 会放过后续写入失败 [`rpg_engine/entity_access.py:188`]
- [x] [Review][Patch] same-delta upsert id 非字符串或非法格式时可被 reference helper 误当作有效新建目标 [`rpg_engine/entity_access.py:214`]
- [x] [Review][Patch] status/visibility 被 Unicode 边缘空白包裹时仍可能绕过过滤 [`rpg_engine/entity_access.py:11`]
- [x] [Review][Patch] status/visibility Unicode whitespace 集合不完整，部分 hidden/archived 变体仍可绕过过滤 [`rpg_engine/visibility.py:11`]
- [x] [Review][Patch] access contract 的 hidden/archived 归一化未同步到 FTS rebuild 和普通 query resolution [`rpg_engine/db.py:471`]
- [x] [Review][Patch] `crop_plot.plot_no` 缺失时 schema validation 会通过但 writer 会崩溃 [`rpg_engine/delta_schema.py:217`]
- [x] [Review][Patch] Python 与 SQL label normalization 对 NFKC 兼容字符语义不一致 [`rpg_engine/visibility.py:61`]
- [x] [Review][Patch] hidden clock subtype 仍会被写入 FTS [`rpg_engine/db.py:471`]
- [x] [Review][Patch] Campaign import 的 crop_plot 必填字段校验缺失 [`rpg_engine/content_types/core.py:46`]
- [x] [Review][Patch] runtime `crop_plot` type 可省略 `crop_plot` subrecord [`rpg_engine/delta_schema.py:217`]
- [x] [Review][Patch] Dev Agent Record File List 漏掉 visibility/FTS/crop_plot validation files [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md:246`]
- [x] [Review][Patch] 未注册 `nfkc_label` 的连接使用 visibility SQL 会运行时失败 [`rpg_engine/visibility.py:71`]
- [x] [Review][Patch] hidden/archived 被 U+2060 等不可见格式字符包裹时可能绕过归一化 [`rpg_engine/visibility.py:12`]
- [x] [Review][Patch] `list_entities()` status/type filters 对全角或边缘空白标签未使用 shared normalizer [`rpg_engine/entity_access.py:270`]
- [x] [Review][Patch] 非字符串 entity reference 被转成字符串查询，错误语义不稳定 [`rpg_engine/entity_access.py:243`]
- [x] [Review][Patch] Player context 仍绕过 subtype/status access contract，hidden clock / archived 变体可泄露 [`rpg_engine/context/resolution.py:243`]
- [x] [Review][Patch] U+200C 等不可见 format 字符包裹 hidden/archived 标签时仍可能绕过归一化 [`rpg_engine/visibility.py:12`]
- [x] [Review][Patch] 直接调用 `validate_entity_reference()` 时非法 same-delta id 可被误判有效 [`rpg_engine/entity_access.py:216`]
- [x] [Review][Patch] Player cards 仍会生成 hidden clock / 非规范 archived entity [`rpg_engine/cards.py:45`]
- [x] [Review][Patch] Context active clocks section 仍绕过 entity visibility/status contract [`rpg_engine/context/collectors.py:475`]
- [x] [Review][Patch] `nfkc_label()` SQL 注册未覆盖 render/cards/context/preview/binder visibility SQL 调用点 [`rpg_engine/visibility.py:75`]
- [x] [Review][Patch] Gameplay / AI read paths still used literal `status != 'archived'` filters [`rpg_engine/preview.py:1529`]
- [x] [Review][Patch] `render_scene()` current location read lacked status filter [`rpg_engine/render.py:749`]
- [x] [Review][Patch] Player card redaction only recognized literal `visibility='hidden'` [`rpg_engine/cards.py:587`]
- [x] [Review][Patch] `render_card_index()` direct calls could pass unfiltered entities [`rpg_engine/cards.py:438`]
- [x] [Review][Patch] Card index owned item query regressed from active-only to non-archived [`rpg_engine/cards.py:453`]
- [x] [Review][Patch] Save validation FTS/card expectations still used old visibility/status filters [`rpg_engine/save_validation.py:597`]
- [x] [Review][Patch] `render_scene()` / current snapshot nearby/current entity reads missed hidden clock subtype filtering [`rpg_engine/render.py:760`]
- [x] [Review][Patch] `collect_world_settings()` missed hidden clock subtype filtering for entity-linked settings [`rpg_engine/context/collectors.py:139`]
- [x] [Review][Patch] `resolve_recipe()` alias query had literal helper text and recipe queries missed player visibility filters [`rpg_engine/preview.py:1260`]
- [x] [Review][Patch] Craft/gather preview item candidates missed player visibility filters [`rpg_engine/preview.py:1374`]
- [x] [Review][Patch] `matching_clock_rows()` leaked hidden/archived clocks into action policy suggestions [`rpg_engine/actions/policy.py:12`]
- [x] [Review][Patch] Location route cards leaked hidden/archived route endpoints [`rpg_engine/cards.py:267`]
- [x] [Review][Patch] Unicode mark categories `Mc` / `Me` could still bypass status/visibility normalization [`rpg_engine/visibility.py:69`]
- [x] [Review][Patch] World memory clock rows missed normalized entity/clock visibility filters [`rpg_engine/memory.py:152`]
- [x] [Review][Patch] Memory generation/retrieval still used literal status/visibility filters [`rpg_engine/memory.py:185`]
- [x] [Review][Patch] Authoring content audit still used literal archived filter [`rpg_engine/content_factory.py:182`]
- [x] [Review][Patch] Ops report counts/type grouping still used literal archived filters [`rpg_engine/ops_report.py:43`]
- [x] [Review][Patch] Tests missed `Mc` / `Me` marks and memory visibility regression coverage [`tests/test_entity_access.py:75`]
- [x] [Review][Patch] `first_visible_entity_in_text()` missed hidden clock subtype filtering [`rpg_engine/intent_router.py:1620`]
- [x] [Review][Patch] `current_location_row()` could return non-location or hidden clock subtype current entity [`rpg_engine/preview.py:984`]
- [x] [Review][Patch] `social_relevant_clocks()` fallback missed normalized entity/clock visibility filters [`rpg_engine/preview.py:2031`]
- [x] [Review][Patch] `location_detail_row()` read player-facing current locations without status/visibility filters [`rpg_engine/preview.py:1543`]
- [x] [Review][Patch] `shortest_route_plan()` built routes through hidden/archived route endpoints [`rpg_engine/preview.py:1726`]
- [x] [Review][Patch] Crop plot preview helpers leaked hidden/archived plots or crops [`rpg_engine/preview.py:1022`]
- [x] [Review][Patch] `normalize_visibility_view()` did not reuse NFKC/edge/format/mark normalization for GM/maintenance view labels [`rpg_engine/visibility.py:49`]
- [x] [Review][Patch] `list_entities()` `statuses` / `types` invalid inputs raised unstable errors or byte iteration behavior [`rpg_engine/entity_access.py:283`]
- [x] [Review][Patch] Card summary redaction did not hide archived entity id references [`rpg_engine/cards.py:598`]
- [x] [Review][Patch] Social action scope could leak hidden/archived location names or route ids through raw scope/name lookup [`rpg_engine/actions/social.py:344`]
- [x] [Review][Patch] Crop preview helpers missed hidden clock subtype filtering for `crop_entity_id` [`rpg_engine/preview.py:1032`]
- [x] [Review][Patch] Crop plot cards leaked hidden/archived crop ids [`rpg_engine/cards.py:368`]
- [x] [Review][Patch] Card index view label displayed unnormalized raw Unicode view labels [`rpg_engine/cards.py:519`]
- [x] [Review][Patch] `crop_plot.crop_entity_id` missing/null errors duplicated schema required validation with unstable wording [`rpg_engine/entity_access.py:205`]
- [x] [Review][Patch] `render_scene()` / current snapshot accepted visible non-location current entities [`rpg_engine/render.py:759`]
- [x] [Review][Patch] Route affordance/card/context queries did not require player-visible location endpoints or hidden clock subtype filters [`rpg_engine/render.py:898`]
- [x] [Review][Patch] Context route collection and social scope could use hidden parent locations [`rpg_engine/context/collectors.py:75`]
- [x] [Review][Patch] Social `location_name()` fallback leaked hidden/archived raw location ids [`rpg_engine/actions/social.py:358`]
- [x] [Review][Patch] Craft/gather item candidates missed hidden clock subtype filtering [`rpg_engine/preview.py:1411`]
- [x] [Review][Patch] Route/location regression tests missed hidden parent, hidden clock endpoint, visible non-location current entity, and hidden clock item-side-table cases [`tests/test_entity_access.py:663`]
- [x] [Review][Patch] Social preview/confirmations leaked hidden/archived NPC location ids through raw `npc.location_id` fallback [`rpg_engine/preview.py:791`]
- [x] [Review][Patch] Rest/craft/travel preview fallbacks leaked hidden current location ids when player-visible current location lookup failed [`rpg_engine/preview.py:525`]
- [x] [Review][Patch] Card index current location link accepted a visible non-location entity as a location [`rpg_engine/cards.py:482`]
- [x] [Review][Patch] Runtime delta `$.meta.current_location_id` accepted non-location entity ids [`rpg_engine/entity_access.py:166`]
- [x] [Review][Patch] Save validation accepted persisted non-location `current_location_id` values [`rpg_engine/validators.py:24`]
- [x] [Review][Patch] Player context and current snapshots leaked raw hidden/non-location current location ids [`rpg_engine/context/rendering.py:62`, `rpg_engine/render.py:959`]
- [x] [Review][Patch] Current snapshot JSON returned raw meta and queried hidden current-location details/occupants [`rpg_engine/render.py:998`]
- [x] [Review][Patch] Social preview/resolver wrote raw current or NPC location ids to delta/facts [`rpg_engine/preview.py:2246`, `rpg_engine/actions/social.py:337`]
- [x] [Review][Patch] Gather preview/resolver wrote raw hidden current or target location ids to delta/confirmations [`rpg_engine/preview.py:683`, `rpg_engine/preview.py:710`]
- [x] [Review][Patch] Craft material availability/candidate queries trusted raw current/home location ids [`rpg_engine/preview.py:1433`]
- [x] [Review][Patch] Player cards and compact context leaked hidden refs through `location_id`/`owner_id`/`species_id`/`parent_id` fields [`rpg_engine/cards.py:141`, `rpg_engine/context/rendering.py:92`]
- [x] [Review][Patch] Card/context/FTS text redaction missed hidden/archived entity names and aliases [`rpg_engine/cards.py:638`, `rpg_engine/db.py:491`, `rpg_engine/context/rendering.py:97`]
- [x] [Review][Patch] World memory persisted raw current location id and could leak it through long-term memory context [`rpg_engine/memory.py:176`]
- [x] [Regression][Patch] Full regression exposed stale search projection count after the entity-safe FTS contract changed; `migrate apply` did not refresh search projection and pending migrations surfaced projection drift too early [`rpg_engine/cli.py:1166`, `rpg_engine/save_validation.py:176`]
- [x] [Review][Patch] Combat preview and resolver surfaced raw current/target location ids in blockers and summary text [`rpg_engine/preview.py:104`, `rpg_engine/actions/combat.py:107`]
- [x] [Review][Patch] Gather/craft/travel palette paths trusted hidden or missing current locations and could build unsafe deltas [`rpg_engine/actions/gather.py:321`, `rpg_engine/actions/craft.py:338`, `rpg_engine/actions/travel.py:334`]
- [x] [Review][Patch] Save validation snapshot checks rejected the intentional hidden-current placeholder after player-safe redaction [`rpg_engine/save_validation.py:614`]
- [x] [Review][Patch] Scene, snapshot JSON, render item, and context player-state output still contained unredacted hidden/archived entity ids or names [`rpg_engine/render.py:568`, `rpg_engine/render.py:824`, `rpg_engine/render.py:1082`, `rpg_engine/context/rendering.py:69`]
- [x] [Review][Patch] Memory event and history context could preserve hidden/archived entity references in player-facing recall [`rpg_engine/memory.py:457`]
- [x] [Review][Patch] Incremental FTS rebuild left stale hidden/archived search rows after redaction-sensitive entity updates [`rpg_engine/db.py:507`]
- [x] [Review][Patch] Persisted current location validation accepted hidden/archived locations as valid current locations [`rpg_engine/validators.py:24`]
- [x] [Review][Patch] Location card and preview side-table text leaked hidden/archived references through descriptions, exits, and resources [`rpg_engine/cards.py:266`, `rpg_engine/preview.py:392`]
- [x] [Review][Patch] Render query and current snapshot text paths did not uniformly redact visible entity text containing hidden/archived refs [`rpg_engine/render.py:487`, `rpg_engine/render.py:1000`]
- [x] [Review][Patch] Craft/travel/gather/social/combat previews and warnings leaked hidden refs through side-table text, route metadata, NPC summaries, clock triggers, owner ids, and profile risk text [`rpg_engine/preview.py:412`, `rpg_engine/preview.py:584`, `rpg_engine/preview.py:742`, `rpg_engine/preview.py:827`, `rpg_engine/preview.py:927`]
- [x] [Review][Patch] Combat/routine/explore/rest/craft/travel/social action validation still used or displayed raw current location ids when the current location was hidden/unreadable [`rpg_engine/actions/combat.py:69`, `rpg_engine/actions/routine.py:180`, `rpg_engine/actions/explore.py:56`, `rpg_engine/actions/rest.py:117`, `rpg_engine/actions/craft.py:210`, `rpg_engine/actions/travel.py:405`, `rpg_engine/actions/social.py:247`]
- [x] [Review][Patch] Player cards, active facts, clock cards, crop plot cards, context active clocks, world settings, and event history could preserve hidden/archived refs in generated read models [`rpg_engine/cards.py:341`, `rpg_engine/cards.py:396`, `rpg_engine/cards.py:462`, `rpg_engine/context/collectors.py:537`, `rpg_engine/context/collectors.py:594`, `rpg_engine/context/collectors.py:637`]
- [x] [Review][Patch] Long-term memory generation/rendering could store or replay hidden refs from clock, character, project, faction, or old memory rows [`rpg_engine/memory.py:180`, `rpg_engine/memory.py:241`, `rpg_engine/memory.py:411`]
- [x] [Review][Patch] Save validation did not scan player snapshot JSON, generated cards, stale hidden/archived cards, or FTS rows for hidden/archived refs [`rpg_engine/save_validation.py:596`, `rpg_engine/save_validation.py:625`, `rpg_engine/save_validation.py:659`]
- [x] [Review][Patch] Snapshot JSON hidden-current placeholder was accepted even when the real current location was player-visible [`rpg_engine/save_validation.py:614`]
- [x] [Review][Patch] `render_entity()` regression test passed a `sqlite3.Row` as query and did not cover the actual query renderer path [`tests/test_entity_access.py:1133`]
- [x] [Regression][Patch] Hidden-ref token scanning falsely flagged archived/current visible name collisions and pending-migration current-save projections; redaction now excludes public name/alias collisions and pending migrations defer deep derived-projection leak scans [`rpg_engine/redaction.py:14`, `rpg_engine/save_validation.py:176`]
- [x] [Regression][Patch] `migrate apply` refreshed only search projection, leaving copied saves with stale cards/snapshots after stricter player-view projection validation [`rpg_engine/cli.py:1166`]
- [x] [Review][Patch] Current snapshot Markdown and scene output did not receive final player-view hidden-ref redaction [`rpg_engine/render.py:1014`]
- [x] [Review][Patch] Save validation did not scan `snapshots/current.md` for hidden/archived refs [`rpg_engine/save_validation.py:176`]
- [x] [Review][Patch] Card index rendering and validation skipped hidden refs in `cards/INDEX.md` [`rpg_engine/cards.py:584`, `rpg_engine/save_validation.py:717`]
- [x] [Review][Patch] Explore and palette action previews/deltas could surface raw palette or target text containing hidden refs [`rpg_engine/actions/explore.py:127`, `rpg_engine/actions/craft.py:295`, `rpg_engine/actions/gather.py:260`, `rpg_engine/actions/travel.py:285`]
- [x] [Review][Patch] Palette gather/craft/travel builders persisted raw candidate payload or entry text before player-facing redaction [`rpg_engine/actions/gather.py:337`, `rpg_engine/actions/craft.py:361`, `rpg_engine/actions/travel.py:353`]
- [x] [Review][Patch] Social palette section and compact context palette table appended raw candidate text after earlier redaction [`rpg_engine/actions/social.py:42`, `rpg_engine/context/collectors.py:151`]
- [x] [Review][Patch] Hidden-ref token matching treated `loc:hidden` inside longer ids as a leak and did not protect public visible id/name/alias collisions [`rpg_engine/redaction.py:105`]
- [x] [Review][Patch] Current snapshot JSON raw meta fields could expose hidden ids, and structured delta redaction removed required empty arrays from preview contracts [`rpg_engine/render.py:1090`, `rpg_engine/redaction.py:71`]
- [x] [Review][Patch] Combat delta validation called blockers without a connection, allowing raw hidden location fallbacks [`rpg_engine/actions/combat.py:191`]
- [x] [Review][Patch] Gather repair options fell back to raw target location ids when target location details were unreadable [`rpg_engine/actions/gather.py:514`]
- [x] [Review][Patch] Palette required-clock gating could read hidden clocks and expose hidden clock ids in unmet reasons [`rpg_engine/palette.py:322`]
- [x] [Review][Patch] Story review record needed current full-gate evidence semantics, an auditable full `py_compile` command, and pending-migration save validation wording that is not treated as a passing done gate [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md:281`]
- [x] [Review][Patch] Palette action resolver JSON `player_message` used raw candidate entry names outside Markdown final redaction [`rpg_engine/actions/explore.py:354`, `rpg_engine/actions/gather.py:322`, `rpg_engine/actions/craft.py:343`, `rpg_engine/actions/travel.py:336`]
- [x] [Review][Patch] Palette craft/travel structured deltas redacted payloads but left raw entry names in `summary`, `user_text`, and event summaries [`rpg_engine/actions/craft.py:358`, `rpg_engine/actions/travel.py:351`]
- [x] [Review][Patch] Social palette resolver merged raw `palette_candidate_payload()` into structured proposed deltas [`rpg_engine/actions/social.py:331`]
- [x] [Review][Patch] Reference token boundary mishandled dotted longer ids and sentence punctuation around entity ids [`rpg_engine/redaction.py:156`]
- [x] [Review][Patch] Structured redaction detected hidden refs in dict keys but did not redact keys, and exact hidden scalars became `None` even when preserving structure [`rpg_engine/redaction.py:103`]
- [x] [Review][Patch] Rest/travel/combat non-palette resolvers returned structured deltas containing raw copied PC, character, item, or ammo fields before final redaction [`rpg_engine/actions/rest.py:95`, `rpg_engine/actions/travel.py:174`, `rpg_engine/actions/combat.py:173`]
- [x] [Review][Patch] Routine preview/resolver returned raw unresolved target options in Markdown and structured delta payloads [`rpg_engine/actions/routine.py:84`, `rpg_engine/actions/routine.py:116`, `rpg_engine/actions/routine.py:207`]
- [x] [Review][Patch] Explore unresolved target responses echoed raw hidden ids/names/aliases in JSON confirmations, player_message, and repair options [`rpg_engine/actions/explore.py:185`]
- [x] [Review][Patch] Palette resolver facts and palette validation errors exposed raw palette ids when they collided with hidden/archived refs [`rpg_engine/actions/explore.py:352`, `rpg_engine/actions/gather.py:304`, `rpg_engine/actions/craft.py:341`, `rpg_engine/actions/travel.py:334`, `rpg_engine/actions/social.py:204`]
- [x] [Review][Patch] CLI `palette suggest` rendered raw location query and palette entry name/summary/clue text without final redaction [`rpg_engine/cli.py:1703`, `rpg_engine/palette.py:447`]
- [x] [Review][Patch] `find_entity_ref_tokens()` scanned tuple/set values but `redact_entity_refs()` did not redact tuple/set containers [`rpg_engine/redaction.py:111`]
- [x] [Review][Patch] Story still needed current post-patch full regression and full auditable syntax gate evidence before done sync [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md:373`]
- [x] [Review][Patch] Runtime `preview_action()` returned raw request validation errors/warnings, default player messages, default repair options, and ready turn proposal intent options outside resolver redaction [`rpg_engine/runtime.py:1010`, `rpg_engine/runtime.py:423`]
- [x] [Review][Patch] Runtime `validate_delta()` returned validation pipeline errors/warnings with raw hidden refs from action delta validators [`rpg_engine/runtime.py:1394`, `rpg_engine/validation_pipeline.py:351`]
- [x] [Review][Patch] Non-palette gather/craft/social blocked or ready resolver paths returned raw query text, repair options, confirmations, warnings, or structured deltas [`rpg_engine/actions/gather.py:96`, `rpg_engine/actions/craft.py:146`, `rpg_engine/actions/social.py:172`]
- [x] [Review][Patch] `render_entity()` not-found early return echoed raw hidden/archived query text [`rpg_engine/render.py:491`]
- [x] [Review][Patch] Context semantic AI request/markdown fields could include raw semantic targets, notes, alias gaps, or audit data containing hidden refs [`rpg_engine/context_builder.py:424`, `rpg_engine/context_builder.py:613`]
- [x] [Review][Patch] Story still needed current post-patch full regression and full auditable syntax gate evidence before done sync [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md:383`]
- [x] [Review][Patch] Runtime query JSON and preview-intent query interpretation retained raw `data.query` / context query text outside Markdown redaction [`rpg_engine/runtime.py:937`, `rpg_engine/runtime.py:1271`]
- [x] [Review][Patch] Preview-intent unresolved, maintenance, compound, and mismatch exits returned raw `intent_data`, `source_user_text`, `plan`, or repair options before terminal redaction [`rpg_engine/runtime.py:1006`, `rpg_engine/runtime.py:1219`, `rpg_engine/runtime.py:1358`]
- [x] [Review][Patch] Context request JSON and markdown still exposed raw `user_text`, `intent`, `decision_trace`, intent-AI external candidate/decision, loaded item reasons, and semantic trace data [`rpg_engine/context_builder.py:413`, `rpg_engine/context_builder.py:657`, `rpg_engine/intent_router.py:1721`]
- [x] [Review][Patch] Reference token boundary still matched inside legal dotted continuations such as `loc:hidden..route` [`rpg_engine/redaction.py:184`]
- [x] [Review][Patch] `redact_hidden_entity_refs()` did not traverse dataclass objects used by runtime UX/result structures [`rpg_engine/redaction.py:103`]
- [x] [Review][Patch] `validate_snapshot_json()` skipped `snapshots/current.md` hidden-ref scan when `snapshots/current.json` was missing [`rpg_engine/save_validation.py:615`]
- [x] [Review][Patch] Runtime trusted `query()` / `preview_intent()` paths over-redacted GM/maintenance output and context query ignored trusted view [`rpg_engine/runtime.py:937`, `rpg_engine/runtime.py:1258`]
- [x] [Review][Patch] `preview_action()` early exits and invalid option paths could leak hidden action/option refs, and trusted preview context view was ignored [`rpg_engine/runtime.py:991`]
- [x] [Review][Patch] `commit_turn()` validation failures and `ux_metrics()` could surface raw hidden current-location refs [`rpg_engine/runtime.py:1501`, `rpg_engine/runtime.py:1616`]
- [x] [Review][Patch] `SaveManager.refresh_save_record()` copied raw hidden `current_location_id`, errors, warnings, and summary fallback into registry output [`rpg_engine/save_manager.py:785`]
- [x] [Review][Patch] MCP `require_view_allowed()` used raw lowercasing instead of shared visibility-view normalization [`rpg_engine/mcp_adapter.py:1040`]
- [x] [Review][Patch] Structured redaction scanner missed dataclass and `frozenset` payloads [`rpg_engine/redaction.py:104`, `rpg_engine/redaction.py:150`]
- [x] [Review][Patch] Trusted scene/entity/snapshot renderers were over-redacted before outer runtime view-aware redaction could preserve GM/maintenance refs [`rpg_engine/render.py:563`, `rpg_engine/render.py:760`, `rpg_engine/render.py:1019`]
- [x] [Review][Patch] Maintenance context semantic fields, player-state section, and relevant entity section were over-redacted inside context renderers [`rpg_engine/context_builder.py:405`, `rpg_engine/context_builder.py:535`, `rpg_engine/context/rendering.py:53`]
- [x] [Review][Patch] Player-facing MCP `save_inspect` and `health` returned raw hidden refs from inspect/check errors [`rpg_engine/mcp_adapter.py:532`, `rpg_engine/mcp_adapter.py:1096`]
- [x] [Review][Patch] Registry-active runtime save resolution used stale active save cache and could continue on an unhealthy active save [`rpg_engine/save_manager.py:394`]
- [x] [Review][Patch] Context collectors still over-redacted hidden refs in maintenance active clocks, world settings, and history events [`rpg_engine/context/collectors.py:513`, `rpg_engine/context/collectors.py:584`, `rpg_engine/context/collectors.py:632`]
- [x] [Review][Patch] Context route collection and parent lookup hard-coded player visibility in maintenance context [`rpg_engine/context/collectors.py:64`, `rpg_engine/context/collectors.py:762`]
- [x] [Review][Patch] Explore resolver internals ignored trusted preview view and over-redacted GM markdown/delta output [`rpg_engine/actions/explore.py:36`, `rpg_engine/actions/explore.py:157`]
- [x] [Review][Patch] MCP `preview_from_text` / `preview_action` did not expose or pass trusted `view` to runtime preview [`rpg_engine/mcp_adapter.py:781`, `rpg_engine/mcp_adapter.py:915`]
- [x] [Review][Patch] SaveManager `list_saves(refresh=False)` and `current_save(refresh=False)` returned stale raw hidden refs from registry cache [`rpg_engine/save_manager.py:121`, `rpg_engine/save_manager.py:167`]
- [x] [Review][Patch] `collect_palettes()` unconditionally redacted maintenance palette context and compact palette rows [`rpg_engine/context/collectors.py:154`]
- [x] [Review][Patch] Explore palette preview/resolve paths ignored trusted view and over-redacted GM palette output [`rpg_engine/actions/explore.py:55`]
- [x] [Review][Patch] MCP `start_turn(mode="maintenance")` let developer profile request hidden-read maintenance context [`rpg_engine/mcp_adapter.py:708`]
- [x] [Review][Patch] SaveManager refresh/scrub failures kept stale raw hidden fields for missing or corrupt registry saves [`rpg_engine/save_manager.py:832`]
- [x] [Review][Patch] Memory lookup/rendering hard-coded player filters/redaction and maintenance context could not recall hidden memory subjects [`rpg_engine/memory.py:376`]
- [x] [Review][Patch] `list_saves(refresh=True)` path-error early return bypassed cached-save hidden-ref scrubbing [`rpg_engine/save_manager.py:139`]
- [x] [Review][Patch] MCP `start_turn` accepted `view` but did not pass it to runtime/context, and server wrapper did not expose `view` [`rpg_engine/mcp_adapter.py:739`]
- [x] [Review][Patch] Gather palette preview/resolve/delta paths ignored trusted view and over-redacted GM output [`rpg_engine/actions/gather.py:52`]
- [x] [Review][Patch] Craft palette preview/resolve/delta paths ignored trusted view and over-redacted GM output [`rpg_engine/actions/craft.py:49`]
- [x] [Review][Patch] Travel palette preview/resolve/delta paths ignored trusted view and over-redacted GM output [`rpg_engine/actions/travel.py:34`]
- [x] [Review][Patch] Social palette preview/resolve/delta paths ignored trusted view and over-redacted GM output [`rpg_engine/actions/social.py:30`]
- [x] [Review][Patch] `redact_entity_refs()` rebuilt set/frozenset with unhashable redacted dataclass dicts and could raise `TypeError` [`rpg_engine/redaction.py:123`]
- [x] [Review][Patch] Context entity resolution ignored explicit trusted `visibility_view`, so GM context query could not resolve non-current hidden targets [`rpg_engine/context/resolution.py:63`]
- [x] [Review][Patch] Set/frozenset dataclass redaction fallback preserved crash-safety but changed the outer container shape to list [`rpg_engine/redaction.py:146`]
- [x] [Review][Patch] `runtime.query("context", view="gm")` used maintenance mode instead of query/context plus explicit view, mixing caller mode with hidden-read view [`rpg_engine/runtime.py:980`]
- [x] [Review][Patch] Final full-regression gate showed `query:context` no longer performed fallback candidate entity recall after preserving query/context mode [`rpg_engine/context/resolution.py:81`]
- [x] [Review][Patch] Trusted GM natural-language `query:context` could not recall hidden entities because fallback still depended on public FTS [`rpg_engine/context/resolution.py:404`]
- [x] [Review][Patch] Blank `query:context` fallback candidate recall used `LIKE '%%'` and loaded arbitrary visible entities [`rpg_engine/context/resolution.py:85`]
- [x] [Review][Patch] Trusted token fallback could be starved when public FTS noise filled the result limit before hidden direct DB matches [`rpg_engine/context/resolution.py:446`]
- [x] [Review][Patch] Stopword-only `query:context` still entered LIKE/FTS fallback and recalled arbitrary visible entities [`rpg_engine/context/resolution.py:400`]
- [x] [Review][Patch] Trusted multi-token fallback used OR matching and could recall hidden entities that matched only one significant token [`rpg_engine/context/resolution.py:479`]
- [x] [Review][Patch] Trusted fallback helper could still let public direct DB matches fill its internal limit before hidden rows [`rpg_engine/context/resolution.py:482`]
- [x] [Review][Patch] Chinese stopword-only queries such as `查看 查询` still recalled visible noise entities [`rpg_engine/context/resolution.py:43`]
- [x] [Review][Patch] Trusted all-token fallback treated request verbs like `Tell` / `Please` / `show` as required entity tokens [`rpg_engine/context/resolution.py:497`]
- [x] [Review][Patch] Public LIKE/FTS fallback did not share the significant-token guard for stopword-only inputs such as `to in of` / `a an to` [`rpg_engine/context/resolution.py:492`]
- [x] [Review][Patch] Trusted token helper lacked its own `can_read_hidden(view)` guard for direct calls [`rpg_engine/context/resolution.py:479`]
- [x] [Review][Patch] Request stopword filtering missed `can` / `you`, blocking common GM hidden natural-language queries [`rpg_engine/context/resolution.py:44`]
- [x] [Review][Patch] Request stopword filtering missed common no-entity queries such as `what is`, `where is`, `look at`, and `show around` [`rpg_engine/context/resolution.py:44`]
- [x] [Review][Patch] Public FTS fallback still used raw request-word tokens and could let request-word noise displace legitimate visible targets [`rpg_engine/context/resolution.py:772`]
- [x] [Review][Patch] Context FTS sanitizer did not quote FTS keywords and missed CJK request verb `看` [`rpg_engine/context/resolution.py:770`]
- [x] [Review][Patch] Context FTS sanitizer missed CJK request verbs `查` / `问` / `找`, allowing request-word noise to displace single-character visible targets [`rpg_engine/context/resolution.py:45`]
- [x] [Review][Patch] Context FTS tokenizer missed no-space CJK request prefixes such as `查弩` / `问弩` / `找弩` [`rpg_engine/context/resolution.py:546`]
- [x] [Review][Patch] Public candidate `LIKE` fallback treated `%` / `_` as wildcards and could recall arbitrary visible or trusted-view hidden entities [`rpg_engine/context/resolution.py:442`]
- [x] [Review][Patch] Trusted hidden token fallback treated `_` as a `LIKE` wildcard and could recall unrelated hidden rows [`rpg_engine/context/resolution.py:504`]
- [x] [Review][Patch] Dev Agent Record File List missed `tests/test_context_quality.py` after sanitizer-focused review patches [`_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md:542`]
- [x] [Review][Patch] Public raw `LIKE` fallback could let no-space CJK request-prefix noise such as `查弩 Noise` displace target `弩` before sanitized FTS recall [`rpg_engine/context/resolution.py:445`]
- [x] [Review][Patch] Trusted hidden fallback could let stripped CJK token matches outrank raw hidden exact entities such as `找弩` / `查询器` [`rpg_engine/context/resolution.py:486`]
- [x] [Review][Patch] Trusted hidden token extraction dropped literal `%` in queries such as `A%B`, preventing alias/details recall for hidden literal percent codes [`rpg_engine/context/resolution.py:557`]
- [x] [Review][Patch] Trusted literal candidate helper lacked its own hidden-read guard for direct player-view calls [`rpg_engine/context/resolution.py:591`]
- [x] [Review][Patch] Trusted token helper ran hidden literal lookup before rejecting stopword-only request text [`rpg_engine/context/resolution.py:547`]
- [x] [Review][Patch] GM candidate ordering let broad hidden fallback outrank visible raw exact matches such as `Official Notice` [`rpg_engine/context/resolution.py:477`]
- [x] [Review][Patch] GM significant/raw broad candidate search still used GM visibility, allowing hidden broad rows to outrank visible exact official recall [`rpg_engine/context/resolution.py:450`]

## 开发说明

### 来源上下文

- Epic 2 要求 Campaign/Save 世界模型支持 entity、relationship 和 progress access contracts；Story 2.3 是 Entity Identity 边界，为 Story 2.4 Relationship 与 Story 2.5 Progress 提供身份锚点。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-7 要求 Relationship 能依赖实体关系；FR-13 要求 Campaign Package 表达 entities、relationships、goals/progress；FR-17 要求不同 Campaign Package 复用同一 Kernel foundation flow。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-4 规定 Entity 是统一身份锚点；typed side tables 可以增强结构化字段，但不能替代 `entities.id`。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- AR-20 明确：Entity 必须继续作为统一身份锚点；typed side tables 可增强结构化字段但不能替代 `entities.id`，也不能引入并行身份系统。来源：`_bmad-output/planning-artifacts/epics.md`。
- Canonical data model 已定义 `entities` 核心字段、typed side tables、player view FTS 排除 hidden / archived，以及 active entity 不能同时设置 `location_id` 和 `owner_id`。来源：`docs/data-models.md`。

### 当前实现状态

- `rpg_engine/db.py::upsert_entity()` 写入 `entities` common fields，并按 `character`、`item`、`location`、`crop_plot` subrecord 写 typed side tables。当前没有独立 entity access contract 模块。
- `rpg_engine/db.py::resolve_entity()` 已在 query/preview/context 解析时应用 `entity_visibility_sql()`、`entity_subtype_visibility_sql()` 和 `status != 'archived'`，并对 hidden clocks 有 subtype visibility filter。该函数偏解析/搜索，不应成为全部 entity access contract 的唯一 API。
- `rpg_engine/visibility.py` 已提供 `PLAYER_VIEW`、`GM_VIEW`、`MAINTENANCE_VIEW`、`normalize_visibility_view()`、`can_read_hidden()` 和 `entity_visibility_sql()`；新 contract 应复用这些 helper。
- `rpg_engine/delta_schema.py::validate_entities()` 已校验 `id`、`type`、`name`、`summary`、`ALLOWED_ENTITY_TYPES`、aliases、details/subrecords，以及 `owner_id` + `location_id` 同时存在错误。
- `rpg_engine/delta_schema.py::validate_database_refs()` 已校验 runtime delta 中的 `location_before`、`location_after`、`meta.current_location_id`、entity `location_id` / `owner_id`、`character.species_id`、`location.parent_id`、`crop_plot.crop_entity_id`，并允许同一 delta 内新建引用目标（same delta upsert refs）。该逻辑应被抽成 entity access contract 的 validation helper 或由 contract 复用，避免后续 Relationship/Progress story 复制 SQL。
- `tests/test_entity_resolution.py` 已覆盖 entity resolution 的 query token、hidden clock player/GM visibility 和 location resolution；新增 tests 可以复用同一 fixture pattern。
- `tests/test_low_level_condition_coverage.py` 已有 low-level invariant coverage，包括 missing entity references 和 owner/location 同时存在；本 story 应新增更聚焦的 contract tests，而不是只依赖大文件。

### 前序故事情报

- Story 2.1 已固化 Campaign/Save ownership 与 source Campaign no-mutation；本 story 的 tests 涉及 Save 写入时必须使用 temp copy。
- Story 2.2 已固化 Content Type / Merge Contract，并明确 `character`、`item`、`location` 是 `entity` content type 中的 records，不是独立 package content roots。Entity access contract 不应回退到按 entity type 发明 package roots。
- Story 2.2 的 review patch 多次暴露同一规则分散在 package validation、campaign validation、schema 和 loader 中会 drift。本 story 应把 entity common read/reference/invariant 规则集中在一个命名 contract，至少让 runtime delta validation 复用它。

### 架构合规要求

- `entities.id` 是唯一持久身份锚点。不要新增第二套 ID table、identity registry 或 campaign-specific runtime schema。
- Entity access contract 是 read/validation helper，不是 write authority。写入仍必须走 Campaign import、content sync/package maintenance 或 runtime validation/commit。
- Player-safe reads 必须默认排除 hidden 和 archived。GM / maintenance 读取 hidden 必须显式选择对应 view。
- Hidden clock 必须同时检查 `entities.visibility` 和 `clocks.visibility`；不能只看 entity row。
- Runtime mutation 可以引用同一 delta 中即将创建的 entities，但不能引用不存在且未创建的 ids。
- 普通 play 的事实写入仍受 `player_turn -> pending action -> player_confirm -> validation -> commit` 约束；本 story 不改 SaveManager authority。

### 相关文件

- `rpg_engine/entity_access.py`：建议新增的 contract 模块。
- `rpg_engine/db.py`：现有 entity upsert、resolve、FTS 和 helper；避免大范围迁移解析逻辑。
- `rpg_engine/delta_schema.py`：runtime delta schema 与 database reference validation 主要落点。
- `rpg_engine/visibility.py`：view normalization 和 hidden-read helper。
- `rpg_engine/content_types/core.py`：`validate_entity_record()` 与 `entity` content type seed/upsert 行为。
- `rpg_engine/context/resolution.py`、`rpg_engine/context/rendering.py`、`rpg_engine/render.py`：现有 entity read/render callers；本 story 不要求全量迁移所有 SQL caller。
- `docs/data-models.md`、`docs/component-inventory.md`：canonical docs 同步落点。
- `tests/test_entity_access.py`、`tests/test_entity_resolution.py`、`tests/test_validation_pipeline.py`：focused tests 落点。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py
python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md
git diff --check
```

如果 implementation 改动触及 content type / package source validation：

```bash
python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py
```

如果 implementation 改动 broader runtime、context 或 query rendering：

```bash
python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py
```

### 残余风险与边界

- 本 story 不实现 Relationship Access Contract；那是 Story 2.4。
- 本 story 不实现 Progress Track / Clock Access Contract；那是 Story 2.5。这里只覆盖 clock subtype visibility，避免 hidden clock 经 entity access 泄露。
- 本 story 不要求全仓库所有 direct `select * from entities` 一次性迁移；只要求建立稳定 contract，并让 runtime delta reference validation 复用或对齐它。
- 本 story 不新增 CLI/MCP tool；如调试需要，优先用 tests 和 docs 证明 contract。
- 本 story 不改变 Campaign Package content root 规则，不把 `characters`、`items`、`locations` 变成独立 package roots。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python stdlib、SQLite、pytest、visibility helper、ContentRegistry 和 delta validation。不要新增运行时依赖。

## Project Structure Notes

实现应保持小而可测：新增命名 entity access contract，收敛 validation 引用规则，补 focused tests 和 canonical docs。避免对 `db.py::resolve_entity()`、preview、context、render 进行大范围重写，除非某个 test 证明必须调整。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `_bmad-output/implementation-artifacts/2-2-content-type-and-merge-contract.md`
- `docs/project-context.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/db.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/visibility.py`
- `rpg_engine/content_types/core.py`
- `tests/test_entity_resolution.py`
- `tests/test_validation_pipeline.py`
- `tests/test_low_level_condition_coverage.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED: `python3 -m pytest -q tests/test_entity_access.py` failed as expected with missing `rpg_engine.entity_access`.
- GREEN focused: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 13 tests.
- Package/content regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests.
- Current native gate: `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Campaign smoke: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` and `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` returned OK.
- Docs/syntax/whitespace: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py`, and `git diff --check` passed.
- Full regression: `python3 -m pytest -q` passed with 582 tests and 690 subtests.
- Review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 14 tests.
- Review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py` and `git diff --check` passed.
- Second review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 14 tests.
- Second review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py` and `git diff --check` passed.
- Third review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 14 tests.
- Third review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py` and `git diff --check` passed.
- Fourth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 14 tests.
- Fourth review patch docs/syntax/whitespace: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py`, and `git diff --check` passed.
- Fifth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 14 tests.
- Fifth review patch docs/syntax/whitespace: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py`, and `git diff --check` passed.
- Sixth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 14 tests.
- Sixth review patch docs/syntax/whitespace: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py`, and `git diff --check` passed.
- Seventh review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 15 tests.
- Seventh review patch docs/syntax/whitespace: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py`, and `git diff --check` passed.
- Eighth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 16 tests.
- Eighth review patch docs/syntax/whitespace: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py`, and `git diff --check` passed.
- Eighth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Eighth review package/current-native regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Ninth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 16 tests.
- Ninth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/ai_intent/binder.py` and `git diff --check` passed.
- Ninth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Ninth review package/current-native regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Tenth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 16 tests.
- Tenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/ai_intent/binder.py rpg_engine/save_validation.py` and `git diff --check` passed.
- Tenth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Tenth review package/current-native regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Eleventh review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 17 tests.
- Eleventh review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/ai_intent/binder.py rpg_engine/save_validation.py rpg_engine/memory.py rpg_engine/actions/policy.py rpg_engine/content_factory.py rpg_engine/ops_report.py rpg_engine/audit.py rpg_engine/validators.py rpg_engine/intent_router.py` and `git diff --check` passed.
- Eleventh review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Eleventh review package/current-native regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Twelfth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 17 tests.
- Twelfth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/intent_router.py rpg_engine/ai_intent/binder.py rpg_engine/save_validation.py rpg_engine/memory.py rpg_engine/actions/policy.py rpg_engine/content_factory.py rpg_engine/ops_report.py rpg_engine/audit.py rpg_engine/validators.py` and `git diff --check` passed.
- Twelfth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Twelfth review package/current-native regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Thirteenth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 17 tests.
- Thirteenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/intent_router.py rpg_engine/ai_intent/binder.py rpg_engine/save_validation.py rpg_engine/memory.py rpg_engine/actions/policy.py rpg_engine/content_factory.py rpg_engine/ops_report.py rpg_engine/audit.py rpg_engine/validators.py` and `git diff --check` passed.
- Thirteenth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Thirteenth review package/current-native regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 8 tests.
- Fourteenth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 17 tests.
- Fourteenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/intent_router.py rpg_engine/ai_intent/binder.py rpg_engine/save_validation.py rpg_engine/memory.py rpg_engine/actions/policy.py rpg_engine/actions/scope.py rpg_engine/actions/social.py rpg_engine/content_factory.py rpg_engine/ops_report.py rpg_engine/audit.py rpg_engine/validators.py` and `git diff --check` passed.
- Fourteenth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Fourteenth review package/current/maintenance regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_maintenance_tooling_coverage.py` passed with 30 tests and 5 subtests.
- Fifteenth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 17 tests.
- Fifteenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/entity_access.py rpg_engine/delta_schema.py rpg_engine/db.py rpg_engine/visibility.py rpg_engine/content_types/core.py rpg_engine/context/resolution.py rpg_engine/context/collectors.py rpg_engine/cards.py rpg_engine/render.py rpg_engine/preview.py rpg_engine/intent_router.py rpg_engine/ai_intent/binder.py rpg_engine/save_validation.py rpg_engine/memory.py rpg_engine/actions/policy.py rpg_engine/actions/scope.py rpg_engine/actions/social.py rpg_engine/content_factory.py rpg_engine/ops_report.py rpg_engine/audit.py rpg_engine/validators.py` and `git diff --check` passed.
- Fifteenth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Fifteenth review package/current/maintenance regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests; `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_maintenance_tooling_coverage.py` passed with 30 tests and 5 subtests.
- Sixteenth review patch focused gate: `python3 -m pytest -q tests/test_entity_access.py` passed with 7 tests.
- Sixteenth review patch gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 17 tests.
- Sixteenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/actions/policy.py rpg_engine/actions/scope.py rpg_engine/actions/social.py rpg_engine/ai_intent/binder.py rpg_engine/audit.py rpg_engine/cards.py rpg_engine/content_factory.py rpg_engine/content_types/core.py rpg_engine/context/collectors.py rpg_engine/context/resolution.py rpg_engine/db.py rpg_engine/delta_schema.py rpg_engine/entity_access.py rpg_engine/intent_router.py rpg_engine/memory.py rpg_engine/ops_report.py rpg_engine/preview.py rpg_engine/render.py rpg_engine/save_validation.py rpg_engine/validators.py rpg_engine/visibility.py tests/test_entity_access.py` and `git diff --check` passed.
- Seventeenth review full regression pre-patch: `python3 -m pytest -q` failed with FTS projection drift around hidden clock subtype search indexing, then was fixed through migration/search projection synchronization.
- Seventeenth review patch focused gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 18 tests.
- Seventeenth review action/current gate: `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py` passed with 16 tests and 36 subtests.
- Seventeenth review context regression: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Seventeenth review package regression: `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests.
- Seventeenth review current/maintenance regression: `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_package.py tests/test_current_native_visibility.py tests/test_current_native_write_safety.py tests/test_maintenance_tooling_coverage.py` passed with 46 tests and 42 subtests.
- Seventeenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/actions/gather.py rpg_engine/actions/policy.py rpg_engine/actions/scope.py rpg_engine/actions/social.py rpg_engine/ai_intent/binder.py rpg_engine/audit.py rpg_engine/cards.py rpg_engine/cli.py rpg_engine/content_factory.py rpg_engine/content_types/core.py rpg_engine/context/collectors.py rpg_engine/context/rendering.py rpg_engine/context/resolution.py rpg_engine/db.py rpg_engine/delta_schema.py rpg_engine/entity_access.py rpg_engine/intent_router.py rpg_engine/memory.py rpg_engine/ops_report.py rpg_engine/preview.py rpg_engine/redaction.py rpg_engine/render.py rpg_engine/save_validation.py rpg_engine/validators.py rpg_engine/visibility.py tests/test_entity_access.py` and `git diff --check` passed.
- Eighteenth review patch focused gate: `python3 -m pytest -q tests/test_entity_access.py` passed with 8 tests.
- Eighteenth review patch syntax/whitespace: `python3 -m py_compile rpg_engine/preview.py tests/test_entity_access.py` and `git diff --check` passed.
- Nineteenth review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py` passed with 18 tests; `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 27 tests.
- Nineteenth review current-native gates: `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests; `python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 16 tests and 17 subtests.
- Nineteenth review context/package gates: `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests; `python3 -m pytest -q tests/test_campaign_validation.py tests/test_content_registry.py tests/test_package_cli.py tests/test_package_merge.py` passed with 70 tests and 52 subtests.
- Nineteenth review validation regression gates: `python3 -m pytest -q tests/test_core_rule_condition_coverage.py tests/test_current_native_package.py tests/test_current_native_visibility.py tests/test_current_native_write_safety.py` passed with 27 tests and 17 subtests. Pending-migration diagnostic evidence only: `python3 -m rpg_engine save validate /Users/oliver/.hermes/rp/isekai-farm-save-native-v1 --format json` reported only `SCHEMA_INCONSISTENT` while pending migrations remain; this is not a final done-pass gate.
- Nineteenth review campaign/docs/syntax gates: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`, `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`, `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`, `python3 -m py_compile rpg_engine/actions/combat.py rpg_engine/actions/craft.py rpg_engine/actions/explore.py rpg_engine/actions/gather.py rpg_engine/actions/policy.py rpg_engine/actions/rest.py rpg_engine/actions/routine.py rpg_engine/actions/scope.py rpg_engine/actions/social.py rpg_engine/actions/travel.py rpg_engine/ai_intent/binder.py rpg_engine/audit.py rpg_engine/cards.py rpg_engine/cli.py rpg_engine/content_factory.py rpg_engine/content_types/core.py rpg_engine/context/collectors.py rpg_engine/context/rendering.py rpg_engine/context/resolution.py rpg_engine/db.py rpg_engine/delta_schema.py rpg_engine/entity_access.py rpg_engine/intent_router.py rpg_engine/memory.py rpg_engine/ops_report.py rpg_engine/palette.py rpg_engine/preview.py rpg_engine/redaction.py rpg_engine/render.py rpg_engine/save_validation.py rpg_engine/validators.py rpg_engine/visibility.py tests/test_core_rule_condition_coverage.py tests/test_entity_access.py tests/test_low_level_condition_coverage.py`, and `git diff --check` passed.
- Twentieth review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py` passed with 9 tests; `python3 -m pytest -q tests/test_core_rule_condition_coverage.py` passed with 11 tests.
- Twentieth review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 28 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests; `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Twentieth review syntax/whitespace: `python3 -m py_compile rpg_engine/redaction.py rpg_engine/render.py rpg_engine/actions/explore.py rpg_engine/actions/gather.py rpg_engine/actions/craft.py rpg_engine/actions/travel.py rpg_engine/preview.py` and `git diff --check` passed.
- Twenty-first review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py` passed with 10 tests; `python3 -m pytest -q tests/test_palette_governance.py tests/test_current_native_actions.py` passed with 15 tests and 8 subtests.
- Twenty-first review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 29 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests; `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Twenty-first review syntax/whitespace: `python3 -m py_compile rpg_engine/redaction.py rpg_engine/actions/explore.py rpg_engine/actions/gather.py rpg_engine/actions/craft.py rpg_engine/actions/travel.py rpg_engine/actions/social.py tests/test_entity_access.py tests/test_maintenance_tooling_coverage.py` and `git diff --check` passed.
- Twenty-second review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py` passed with 10 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_palette_governance.py` passed with 15 tests and 8 subtests; `python3 -m pytest -q tests/test_maintenance_tooling_coverage.py` passed with 22 tests and 5 subtests.
- Twenty-second review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 29 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests; `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Twenty-second review syntax/whitespace: `python3 -m py_compile rpg_engine/redaction.py rpg_engine/actions/rest.py rpg_engine/actions/travel.py rpg_engine/actions/combat.py rpg_engine/actions/routine.py rpg_engine/actions/explore.py rpg_engine/actions/gather.py rpg_engine/actions/craft.py rpg_engine/actions/social.py rpg_engine/palette.py tests/test_entity_access.py` and `git diff --check` passed.
- Twenty-third review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py` passed with 10 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_palette_governance.py tests/test_maintenance_tooling_coverage.py` passed with 37 tests and 13 subtests.
- Twenty-third review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 29 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests; `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Twenty-third review syntax/whitespace: `python3 -m py_compile rpg_engine/runtime.py rpg_engine/render.py rpg_engine/context_builder.py rpg_engine/actions/gather.py rpg_engine/actions/craft.py rpg_engine/actions/social.py tests/test_entity_access.py` and `git diff --check` passed.
- Twenty-fourth review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py` passed with 10 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_context_quality.py tests/test_v1_cli.py` passed with 65 tests and 24 subtests.
- Twenty-fourth review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 29 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests; `python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_v1_cli.py` passed with 67 tests and 32 subtests.
- Twenty-fourth review syntax/whitespace: `python3 -m py_compile rpg_engine/redaction.py rpg_engine/runtime.py rpg_engine/context_builder.py rpg_engine/save_validation.py tests/test_entity_access.py` and `git diff --check` passed.
- Twenty-fifth review patch focused gates: `python3 -m pytest -q tests/test_current_native_visibility.py tests/test_entity_access.py` passed with 14 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_context_quality.py tests/test_v1_cli.py` passed with 65 tests and 24 subtests.
- Twenty-fifth review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 32 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests.
- Twenty-sixth review patch focused gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_save_manager.py` passed with 75 tests and 35 subtests.
- Twenty-sixth review regression gates: `python3 -m pytest -q tests/test_current_native_actions.py tests/test_context_quality.py tests/test_v1_cli.py` passed with 65 tests and 24 subtests; `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 34 tests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests.
- Twenty-sixth review syntax/whitespace: `python3 -m py_compile rpg_engine/runtime.py rpg_engine/render.py rpg_engine/context_builder.py rpg_engine/context/rendering.py rpg_engine/mcp_adapter.py rpg_engine/save_manager.py tests/test_entity_access.py tests/test_mcp_adapter.py` and `git diff --check` passed.
- Twenty-seventh review patch focused gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_save_manager.py tests/test_current_native_actions.py tests/test_context_quality.py tests/test_v1_cli.py` passed with 141 tests and 59 subtests.
- Twenty-seventh review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 34 tests; `python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py tests/test_current_native_write_safety.py` passed with 68 tests and 35 subtests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests.
- Twenty-eighth review patch focused gate: `python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_save_manager.py tests/test_palette_governance.py` passed with 86 tests and 35 subtests.
- Twenty-eighth review regression gates: `python3 -m pytest -q tests/test_entity_access.py tests/test_entity_resolution.py tests/test_validation_pipeline.py tests/test_palette_governance.py` passed with 35 tests; `python3 -m pytest -q tests/test_current_native_write_safety.py tests/test_context_quality.py tests/test_v1_cli.py` passed with 66 tests and 16 subtests; `python3 -m pytest -q tests/test_current_native_actions.py tests/test_current_native_player_turn.py tests/test_current_native_context.py tests/test_maintenance_tooling_coverage.py` passed with 38 tests and 41 subtests.
- Twenty-eighth review syntax/whitespace: `python3 -m py_compile rpg_engine/memory.py rpg_engine/actions/explore.py rpg_engine/context/collectors.py rpg_engine/mcp_adapter.py rpg_engine/save_manager.py`, `python3 -m py_compile rpg_engine/redaction.py rpg_engine/actions/explore.py`, and `git diff --check` passed.
- Twenty-ninth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_save_manager.py -p no:cacheprovider` passed with 76 tests and 35 subtests; `python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_save_manager.py tests/test_palette_governance.py` passed with 87 tests and 39 subtests.
- Twenty-ninth review regression gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_actions.py tests/test_context_quality.py tests/test_v1_cli.py -p no:cacheprovider` passed with 65 tests and 24 subtests; `python3 -m pytest -q tests/test_palette_governance.py tests/test_current_native_actions.py` passed with 17 tests and 12 subtests.
- Twenty-ninth review syntax/whitespace: `python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/runtime.py rpg_engine/mcp_adapter.py rpg_engine/actions/gather.py rpg_engine/actions/craft.py rpg_engine/actions/travel.py rpg_engine/actions/social.py rpg_engine/redaction.py tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_palette_governance.py tests/test_save_manager.py` and `git diff --check` passed.
- Thirtieth review patch focused gates: `python3 -m pytest -q tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs -q` passed; `python3 -m pytest -q tests/test_mcp_adapter.py tests/test_entity_access.py tests/test_context_quality.py` passed with 58 tests and 9 subtests.
- Thirtieth review regression gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_save_manager.py -p no:cacheprovider` passed with 76 tests and 35 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_actions.py tests/test_context_quality.py tests/test_v1_cli.py -p no:cacheprovider` passed with 65 tests and 24 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_palette_governance.py tests/test_current_native_actions.py -p no:cacheprovider` passed with 17 tests and 12 subtests.
- Thirtieth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py rpg_engine/context_builder.py rpg_engine/redaction.py tests/test_mcp_adapter.py tests/test_entity_access.py` and `git diff --check` passed.
- Thirty-first review patch focused gates: `python3 -m pytest -q tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs -q` passed; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests.
- Thirty-first review syntax/whitespace: `python3 -m py_compile rpg_engine/runtime.py tests/test_mcp_adapter.py` and `git diff --check` passed.
- Thirty-second final-gate regression patch: `python3 -m pytest -q tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop -q` passed; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests.
- Thirty-second review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py` and `git diff --check` passed.
- Thirty-third review patch focused gates: `python3 -m pytest -q tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop -q` passed; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests.
- Thirty-third review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_mcp_adapter.py tests/test_entity_access.py` and `git diff --check` passed.
- Thirty-fourth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_mcp_adapter.py tests/test_entity_access.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs -p no:cacheprovider` passed with 2 tests.
- Thirty-fourth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_mcp_adapter.py tests/test_entity_access.py` and `git diff --check` passed.
- Thirty-fifth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_mcp_adapter.py tests/test_entity_access.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs -p no:cacheprovider` passed with 2 tests.
- Thirty-fifth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_mcp_adapter.py tests/test_entity_access.py` and `git diff --check` passed.
- Thirty-sixth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_mcp_adapter.py tests/test_entity_access.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs -p no:cacheprovider` passed with 2 tests.
- Thirty-sixth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_mcp_adapter.py tests/test_entity_access.py` and `git diff --check` passed.
- Thirty-seventh review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 58 tests and 9 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop -p no:cacheprovider` passed.
- Thirty-seventh review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_entity_access.py` and `git diff --check` passed.
- Thirty-eighth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 59 tests and 9 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py::ContextBuilderUnitTests::test_fts_sanitizer_and_entity_id_extraction tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop -p no:cacheprovider` passed with 2 tests.
- Thirty-eighth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_entity_access.py tests/test_context_quality.py tests/test_core_rule_condition_coverage.py` and `git diff --check` passed.
- Thirty-ninth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 59 tests and 9 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py::ContextBuilderUnitTests::test_fts_sanitizer_and_entity_id_extraction tests/test_official_example.py::OfficialExampleTests::test_official_example_validates_tests_and_runs_minimal_gameplay_loop -p no:cacheprovider` passed with 2 tests.
- Thirty-ninth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_context_quality.py` and `git diff --check` passed.
- Fortieth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 60 tests and 12 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py::ContextBuilderUnitTests::test_fts_sanitizer_and_entity_id_extraction tests/test_entity_access.py::EntityAccessContractTests::test_context_candidate_search_filters_cjk_request_words_for_fts -p no:cacheprovider` passed with 2 tests and 3 subtests.
- Fortieth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_context_quality.py tests/test_entity_access.py` and `git diff --check` passed.
- Forty-first review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 61 tests and 20 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py::ContextBuilderUnitTests::test_fts_sanitizer_and_entity_id_extraction tests/test_entity_access.py::EntityAccessContractTests::test_context_candidate_search_filters_cjk_request_words_for_fts tests/test_entity_access.py::EntityAccessContractTests::test_context_candidate_search_escapes_like_wildcards -p no:cacheprovider` passed with 3 tests and 11 subtests.
- Forty-first review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_context_quality.py tests/test_entity_access.py` and `git diff --check` passed.
- Forty-second review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 63 tests and 20 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py::EntityAccessContractTests::test_context_candidate_search_filters_cjk_request_words_for_fts tests/test_entity_access.py::EntityAccessContractTests::test_context_candidate_search_escapes_like_wildcards tests/test_entity_access.py::EntityAccessContractTests::test_trusted_candidate_search_prefers_raw_hidden_literals_before_stripped_tokens tests/test_entity_access.py::EntityAccessContractTests::test_trusted_candidate_search_uses_literal_percent_tokens_for_aliases_and_details -p no:cacheprovider` passed with 4 tests and 11 subtests.
- Forty-second review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_context_quality.py tests/test_entity_access.py` and `git diff --check` passed.
- Forty-third review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 65 tests and 20 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py::EntityAccessContractTests::test_trusted_literal_candidate_helper_guards_player_and_stopword_only_calls tests/test_entity_access.py::EntityAccessContractTests::test_gm_candidate_search_prefers_visible_exact_before_hidden_contains tests/test_entity_access.py::EntityAccessContractTests::test_trusted_candidate_search_prefers_raw_hidden_literals_before_stripped_tokens tests/test_entity_access.py::EntityAccessContractTests::test_trusted_candidate_search_uses_literal_percent_tokens_for_aliases_and_details -p no:cacheprovider` passed with 4 tests.
- Forty-third review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_context_quality.py tests/test_entity_access.py` and `git diff --check` passed.
- Forty-fourth review patch focused gates: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py tests/test_mcp_adapter.py tests/test_context_quality.py -p no:cacheprovider` passed with 65 tests and 20 subtests; `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_entity_access.py::EntityAccessContractTests::test_gm_candidate_search_prefers_visible_exact_before_hidden_contains tests/test_entity_access.py::EntityAccessContractTests::test_trusted_candidate_search_prefers_raw_hidden_literals_before_stripped_tokens tests/test_mcp_adapter.py::MCPAdapterTests::test_player_save_inspect_and_health_redact_hidden_current_location_refs -p no:cacheprovider` passed with 3 tests.
- Forty-fourth review syntax/whitespace: `python3 -m py_compile rpg_engine/context/resolution.py tests/test_context_quality.py tests/test_entity_access.py` and `git diff --check` passed.
- Final full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q` passed with 606 tests and 705 subtests.
- Final campaign gates: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` returned OK; `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` returned OK for 12 smoke tests.
- Final docs/syntax/whitespace gates: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md` checked 87 Markdown files; `PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile $(git diff --name-only -- '*.py')` passed; `git diff --check` passed.
- Final review status: Blind Hunter, Edge Case Hunter, and Acceptance Auditor all returned no `[Review][Patch]` and no `[Review][DecisionNeeded]` after the forty-fourth review patch.

### Implementation Plan

- 新增 `rpg_engine/entity_access.py`，以 `EntityRecord` 和 read/list/reference helper 固化 common entity identity contract。
- 用 entity access helper 收敛 `delta_schema.validate_database_refs()` 的 entity reference checks，保持现有错误 wording。
- 新增 `tests/test_entity_access.py` 覆盖 visibility/status/filter、hidden clock subtype 和 runtime delta references。
- 同步 `docs/data-models.md` 与 `docs/component-inventory.md`，然后运行 story 指定 focused gates。

### Completion Notes List

- Added `rpg_engine.entity_access.EntityRecord` plus `read_entity()` and `list_entities()` as the stable common-field entity identity read contract.
- Added player-safe visibility filtering and hidden clock subtype filtering to the access contract without changing `entities.id` or typed side-table ownership.
- Added `validate_delta_entity_references()` and routed `delta_schema.validate_database_refs()` through it, preserving same-delta upsert reference semantics and existing error wording.
- Added focused entity access tests for common identity fields, parsed details, hidden/archived filters, hidden clock subtype filtering, and runtime delta references.
- Synced `docs/data-models.md` and `docs/component-inventory.md` with the new Entity Identity Access Contract.
- Fixed review findings for archived status filtering, string filter normalization, limit validation, non-object reference helper input, schema integration coverage, and historical validation report wording.
- Fixed second-review findings for historical validation report summary/next-step wording, case/whitespace-normalized access filters, and explicit empty/non-string reference validation.
- Fixed third-review findings for crop plot crop entity references, strict include_archived booleans, whitespace-padded reference values, and duplicate reference/schema errors.
- Fixed fourth-review findings for `crop_plot.crop_entity_id` docs/story sync and SQLite edge whitespace normalization in status/visibility filters.
- Fixed fifth-review findings for required crop plot crop references, legal same-delta upsert ids, and Unicode edge whitespace normalization.
- Fixed sixth-review findings by sharing Unicode whitespace normalization through visibility helpers, aligning FTS/query entity resolution with the access contract, and validating required `crop_plot.plot_no`.
- Fixed seventh-review findings by registering shared `nfkc_label()` SQL normalization, excluding hidden clock subtypes from FTS, and requiring crop plot write fields in runtime and Campaign content validation.
- Fixed eighth-review findings by extending context entity resolution to use the same status/subtype visibility contract, normalizing status/type filter labels through the shared helper, tightening non-string reference errors, and updating the File List.
- Fixed ninth-review findings by stripping format characters from label normalization, validating direct entity references before same-delta acceptance, filtering cards and active clock sections through the same subtype/status contract, and registering `nfkc_label()` at remaining visibility SQL call sites.
- Fixed tenth-review findings by replacing remaining gameplay/AI/card/save-validation literal status filters with shared normalized helpers, filtering direct card-index calls through `read_entity()`, restoring active-only owned item semantics, and redacting noncanonical hidden references in card summaries/indexes.
- Fixed eleventh-review findings by applying shared normalized visibility/status filters to render, context world settings, preview recipe/craft/gather, action clock policy, route cards, memory, content audit, ops reporting, audit, validation, and intent-router read paths; tests now cover `Mc` / `Me` marks, memory, route, recipe, gather, policy, world-setting, and diagnostics regressions.
- Fixed twelfth-review findings by applying subtype filters to intent-router player entity candidates, limiting preview current/location detail helpers to visible locations, filtering route graph endpoints, filtering crop plot and crop entities, and filtering social preview clock fallback.
- Fixed thirteenth-review findings by normalizing GM/maintenance view labels with the shared label normalizer, validating `list_entities()` status/type filter input types, and redacting archived entity references from player card text.
- Fixed fourteenth-review findings by filtering social scope route/name helpers through player-visible location reads, applying subtype filters to crop preview helpers, redacting unsafe crop ids in crop plot cards, normalizing card index view display labels, and leaving missing crop refs to schema required validation.
- Fixed fifteenth-review findings by requiring player-visible location endpoints for scene affordances, route cards, context routes, route scope, and current scene/snapshot location reads; hidden parent locations no longer create same-parent social scope; craft/gather item candidates now apply hidden clock subtype filters.
- Fixed sixteenth-review findings by redacting hidden current/NPC location fallbacks in social/rest/craft/travel previews and requiring card-index current location links to point at player-visible `location` entities.
- Fixed seventeenth-review findings by requiring current location references to resolve to locations, redacting hidden/archived ids/names/aliases across cards/context/FTS/memory/snapshots/previews, gating gather/social deltas on player-visible current locations, and refreshing search projection after migrations.
- Fixed eighteenth-review findings by redacting combat/render/context/memory/preview text surfaces, validating visible current locations across validators and palette action builders, accepting player-safe hidden-current placeholders in save validation, and rebuilding FTS globally for redaction-sensitive updates.
- Fixed nineteenth-review findings by applying player-view redaction to query renderers, previews, generated cards, context sections, memory summaries, save validation scans, and action current-location validation; projection repair now refreshes search/snapshots/cards during migration apply, while pending migrations defer deep derived-projection leak scans.
- Fixed twentieth-review findings by adding final player-view redaction for current snapshots, card indexes, palette previews, palette context tables, and structured palette deltas; hidden-ref scans now cover current Markdown/card indexes, token matching is boundary-aware, hidden clock palette gates are player-safe, and structured redaction can preserve empty delta fields.
- Fixed twenty-first-review findings by redacting palette resolver JSON messages and structured deltas, redacting social palette payloads, handling dict-key hidden refs, preserving exact hidden scalar shape as `[hidden]`, and tightening reference-id dotted boundary matching without treating sentence punctuation as id suffix.
- Fixed twenty-second-review findings by redacting non-palette action structured deltas, routine/explore unresolved target JSON fields, palette facts/errors, CLI palette suggestions, and tuple/set redaction containers.
- Fixed twenty-third-review findings by adding runtime-level redaction for preview/validate JSON exits, redacting gather/craft/social non-palette resolver outputs, redacting entity-query not-found text, and redacting semantic AI context request/markdown fields.
- Fixed twenty-fourth-review findings by redacting runtime query and preview-intent non-action exits, redacting full context request/markdown payloads, supporting dataclass redaction, tightening dotted token boundaries, and scanning current Markdown even when current JSON is missing.
- Fixed twenty-fifth-review findings by making runtime query/preview redaction view-aware, redacting commit validation failure and UX metrics output, normalizing MCP view guards through shared visibility helpers, redacting SaveManager registry refresh output, and extending structured redaction to dataclass/frozenset payloads.
- Fixed twenty-sixth-review findings by preserving trusted GM/maintenance render/context output, redacting player-facing MCP inspect/health payloads, and refreshing registry-active runtime save resolution before using active saves.
- Fixed twenty-seventh-review findings by preserving trusted maintenance collector sections, passing trusted view through explore/MCP preview paths, and scrubbing stale SaveManager registry cache records before player-facing list/current output.
- Fixed twenty-eighth-review findings by making palette context and explore palette previews view-aware, gating MCP maintenance turns to hidden-read profiles, clearing stale hidden registry fields on SaveManager failures, and making memory projection/query/render support player-safe and maintenance-trusted views.
- Fixed twenty-ninth-review findings by scrubbing `list_saves(refresh=True)` path-error returns, propagating MCP/runtime/context trusted start-turn views, making gather/craft/travel/social palette paths view-aware, and handling unhashable dataclass redaction results inside set/frozenset containers.
- Fixed thirtieth-review findings by applying explicit trusted context view to entity resolution and preserving set/frozenset outer container shape when redacted dataclass payloads need a stable hashable representation.
- Fixed thirty-first-review finding by keeping runtime context queries in `query:context` mode while passing explicit trusted visibility view to `build_context()`.
- Fixed thirty-second final-gate regression by letting `query:context` perform fallback candidate entity recall without reverting to maintenance mode.
- Fixed thirty-third-review findings by guarding blank candidate queries and adding trusted-only direct DB token fallback for hidden-read context recall without writing hidden entities into public FTS.
- Fixed thirty-fourth-review findings by prioritizing trusted direct DB token matches, rejecting stopword-only candidate fallback, and requiring all significant tokens for trusted multi-token hidden recall.
- Fixed thirty-fifth-review findings by restricting trusted direct fallback to hidden/unindexed rows and expanding shared query stopword filtering for English and Chinese request-only inputs.
- Fixed thirty-sixth-review findings by guarding the trusted token helper itself and filtering `can` / `you` request terms from hidden-read natural-language recall.
- Fixed thirty-seventh-review finding by filtering additional request-only English stopwords before candidate fallback.
- Fixed thirty-eighth-review finding by making context FTS sanitization use significant search tokens while preserving CJK single-character entity terms and short digit terms such as `T3`.
- Fixed thirty-ninth-review finding by quoting significant FTS tokens and filtering the CJK request verb `看` while preserving non-stopword CJK single-character entity terms.
- Fixed fortieth-review finding by filtering additional CJK request verbs `查` / `问` / `找` before candidate FTS recall and covering single-character CJK target recall against request-word noise.
- Fixed forty-first-review findings by stripping no-space CJK request prefixes before candidate FTS recall, escaping `%` / `_` in public and trusted candidate `LIKE` fallbacks, rejecting wildcard-only candidate queries, and completing the sanitizer test file list entry.
- Fixed forty-second-review findings by ranking raw exact literal hits before stripped-token fallback, using stripped significant phrase recall before raw CJK-prefix contains noise, and preserving literal `%` trusted hidden alias/details recall.
- Fixed forty-third-review findings by guarding trusted literal helper direct calls, rejecting stopword-only trusted helper text before hidden lookup, and ordering GM candidate recall as hidden/visible exact before broad trusted fallback.
- Fixed forty-fourth-review finding by making GM broad public candidate recall use player-safe visibility while still checking trusted hidden exact/raw significant matches through dedicated hidden-read helpers.

### File List

- `_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.md`
- `_bmad-output/implementation-artifacts/2-3-entity-identity-access-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `rpg_engine/actions/combat.py`
- `rpg_engine/actions/craft.py`
- `rpg_engine/actions/explore.py`
- `rpg_engine/actions/rest.py`
- `rpg_engine/actions/routine.py`
- `rpg_engine/actions/travel.py`
- `rpg_engine/actions/policy.py`
- `rpg_engine/actions/gather.py`
- `rpg_engine/actions/scope.py`
- `rpg_engine/actions/social.py`
- `rpg_engine/ai_intent/binder.py`
- `rpg_engine/audit.py`
- `rpg_engine/cards.py`
- `rpg_engine/cli.py`
- `rpg_engine/content_factory.py`
- `rpg_engine/content_types/core.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context/rendering.py`
- `rpg_engine/context/resolution.py`
- `rpg_engine/db.py`
- `rpg_engine/delta_schema.py`
- `rpg_engine/entity_access.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/memory.py`
- `rpg_engine/ops_report.py`
- `rpg_engine/palette.py`
- `rpg_engine/preview.py`
- `rpg_engine/redaction.py`
- `rpg_engine/render.py`
- `rpg_engine/runtime.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/save_validation.py`
- `rpg_engine/validators.py`
- `rpg_engine/visibility.py`
- `tests/test_core_rule_condition_coverage.py`
- `tests/test_context_quality.py`
- `tests/test_entity_access.py`
- `tests/test_low_level_condition_coverage.py`
- `tests/test_maintenance_tooling_coverage.py`
- `tests/test_mcp_adapter.py`
- `tests/test_palette_governance.py`
- `tests/test_save_manager.py`

## Change Log

- 2026-07-08: Started implementation for Entity Identity Access Contract.
- 2026-07-08: Implemented Entity Identity Access Contract, delta reference validation reuse, focused tests, docs sync, and verification gates.
- 2026-07-08: Applied code review patches and reran focused gates.
- 2026-07-08: Applied second code review patches.
- 2026-07-08: Applied third code review patches.
- 2026-07-08: Applied fourth code review patches.
- 2026-07-08: Applied fifth code review patches.
- 2026-07-08: Applied sixth code review patches.
- 2026-07-08: Applied seventh code review patches.
- 2026-07-08: Applied eighth code review patches.
- 2026-07-08: Applied ninth code review patches.
- 2026-07-08: Applied tenth code review patches.
- 2026-07-08: Applied eleventh code review patches.
- 2026-07-08: Applied twelfth code review patches.
- 2026-07-08: Applied thirteenth code review patches.
- 2026-07-08: Applied fourteenth code review patches.
- 2026-07-08: Applied fifteenth code review patches.
- 2026-07-08: Applied sixteenth code review patches.
- 2026-07-08: Applied seventeenth code review and full-regression patches.
- 2026-07-08: Applied eighteenth code review patches.
- 2026-07-08: Applied nineteenth code review and projection-validation patches.
- 2026-07-08: Applied twentieth code review and structured-redaction patches.
- 2026-07-08: Applied twenty-first code review and palette JSON redaction patches.
- 2026-07-08: Applied twenty-second code review and action structured-delta redaction patches.
- 2026-07-08: Applied twenty-third code review and runtime JSON redaction patches.
- 2026-07-08: Applied twenty-fourth code review and context/query JSON redaction patches.
- 2026-07-08: Applied twenty-fifth code review and runtime/MCP/SaveManager redaction patches.
- 2026-07-08: Applied twenty-sixth code review and trusted-view/MCP active-save patches.
- 2026-07-08: Applied twenty-seventh code review and context collector/MCP preview/cache scrub patches.
- 2026-07-08: Applied twenty-eighth code review and palette/MCP/cache/memory trusted-view patches.
- 2026-07-08: Applied twenty-ninth code review and MCP start-turn/palette action/redaction patches.
- 2026-07-08: Applied thirtieth code review and context-resolution/set-shape patches.
- 2026-07-08: Applied thirty-first code review and runtime context-query view patch.
- 2026-07-08: Applied thirty-second final-gate regression patch for query-context candidate recall.
- 2026-07-08: Applied thirty-third code review and trusted context candidate fallback patches.
- 2026-07-08: Applied thirty-fourth code review and trusted context fallback precision patches.
- 2026-07-08: Applied thirty-fifth code review and trusted fallback stopword/hidden-only patches.
- 2026-07-08: Applied thirty-sixth code review and trusted helper guard/request-term patches.
- 2026-07-08: Applied thirty-seventh code review and request-only stopword patches.
- 2026-07-08: Applied thirty-eighth code review and significant-token FTS sanitizer patch.
- 2026-07-08: Applied thirty-ninth code review and quoted FTS/CJK request-token patches.
- 2026-07-08: Applied fortieth code review and CJK request-token recall patch.
- 2026-07-08: Applied forty-first code review and CJK prefix/wildcard LIKE patches.
- 2026-07-08: Applied forty-second code review and trusted/public literal-priority patches.
- 2026-07-08: Applied forty-third code review and trusted helper guard/exact-priority patches.
- 2026-07-08: Applied forty-fourth code review and GM public-broad ordering patch.
- 2026-07-08: Final verification gates passed; story and sprint status synced to done.
