---
baseline_commit: 0ef34f34e6413e7913f25181168af736864d9cd6
---

# Story 6.9：Retired Entity Binding Fail-Closed

Status: done

## Story

作为玩家主机，
我希望外部 candidate 引用 retired 或 archived 实体时在绑定阶段安全失败，
从而使已经退出当前世界状态的目标不能重新成为可确认行动。

## Acceptance Criteria

1. **retired / archived 引用在 committable pending 前 fail closed**
   - Given 一个结构化 external candidate 的 entity slot 通过 canonical ID、alias 或旧名称引用当前 caller view 可见的 Save `retired` 或 `archived` 实体/地点，when public ingress、candidate validation 或 canonical binder 处理该引用，then 结果必须被拒绝或进入明确 clarification，`ready_to_confirm=false`，且不得创建 pending action。
   - Binder 的可绑定集合必须来自本次请求绑定的 active Save SQLite connection；candidate payload、manifest、alias row、缓存或其他 Campaign 的同名/同 ID 实体都不能改变 lifecycle 判定或复活目标。
   - 非 `active` lifecycle 值采用 fail-closed 绑定语义；不得因大小写、Unicode/边缘空白或 alias/name 匹配分支绕过同一 canonical status gate。

2. **现有 negative-path 行为与不泄露边界不退化**
   - Given external candidate 引用 foreign Campaign、stale manifest、hidden/GM-only、ambiguous 或 missing 目标，when 绑定链运行，then 保留既有 contract mismatch、missing、ambiguous、clarification 或 blocked 行为，不得静默改绑为另一目标。
   - Player surface 不得暴露 hidden/GM-only 的名称、alias、ID、summary 或存在性；retired/archived 与 missing 在公开结果中不能靠数据库候选列表形成额外 existence oracle。
   - 决策次序（2026-07-18）：PLAYER_VIEW 的 hidden/GM-only row 不参与lifecycle shadow。Entity-only slot 中 hidden 与 absent 同样 missing；hybrid slot 中两者同样只作 literal text，不产生 entity binding、facts used 或 hidden projection。Visible non-active 仍严格阻断 fallback，GM/maintenance view 仍对其可见 non-active row fail closed。
   - 失败路径不得创建新的 committable pending action、confirmation claim/receipt、turn、event、fact、projection 或 events.jsonl；允许返回既有明确 clarification，但不得把它升级为可确认 proposal。测试必须从 authoritative SQLite 与 workspace 文件同时验证该边界。
   - 范围决策（2026-07-18）：本 Story 的no-mutation合同从初始无pending/receipt的temporary workspace验证“拒绝不创建新确认状态或游戏事实”。新turn到来时如何保留、替换或冲突处理既有pending，以及workspace registry `last_played_at`元数据语义，归Story 6.5显式pending supersede处理，不在本 Story修改SaveManager。

3. **active player-visible positive control 保持可用**
   - Given candidate 通过 canonical ID、alias 或名称引用当前 Save 中唯一、`active` 且 player-visible 的合法实体，when 同一 binder / preview / `player_turn` 流程运行，then 继续产生预期 bound option、preview 或可确认 pending。
   - 该 positive control 不削弱 external contract version/safety、action registry、slot contract、visibility、confirmation、validation 或 commit gate；`player_turn()` 仍不提交事实，只有明确 `player_confirm()` 才可能提交。

4. **权威与范围边界保持不变**
   - `data/game.sqlite` 仍是事实权威；external/internal AI 只提供低信任候选，不获得事实、hidden、玩家确认、proposal approval、validation 或 commit authority。
   - 修复位于共享 canonical binder / SQLite lookup owner，不在 MCP、CLI、platform、SaveManager 或测试句式上复制 business rule，也不新增自然语言短句特例。
   - 所有写测试使用独立 temporary Campaign/Save/workspace；不得修改 source Campaign、formal current Saves、正式 registry 或用户 `data/game.sqlite`。
   - 不新增依赖、数据库 migration、测试专用 production API、Coordinator 或跨仓协议；不实现 Story 3.8、Stories 6.5–6.8、Hermes E2E 或其他无关工作。

## Tasks / Subtasks

- [x] Task 1：锁定 authoritative binder lifecycle 合同与 RED 基线（AC: 1, 2, 3, 4）
  - [x] 新增 Story 自包含的 focused test file，不依赖当前未提交的 Iteration 3 rebaseline fixtures；在 temporary Save 中构造 active、retired、archived、hidden、ambiguous 与 foreign/missing 对照。
  - [x] 先复现 BND-03：retired location 的版本化 external travel candidate 当前返回 `ok=true` / `ready_to_confirm=true`；记录 RED 结果后再实现。
  - [x] 对 direct binder 与 public `SaveManager.player_turn()` 同时建立 exact oracle，覆盖 canonical ID、alias 与 name 三种查找路径。

- [x] Task 2：在 canonical binder 的 SQLite candidate lookup 中实施 fail-closed lifecycle gate（AC: 1, 2, 3, 4）
  - [x] Action binding 的 exact 与 partial/alias/name 分支使用同一 normalized lifecycle predicate，只允许当前 SQLite 中 `status='active'` 的实体进入 bindable 候选集合；若复用 `find_entity_candidates()`，必须用显式 binder-only 参数或内部 helper，不能意外改变 query arbitration 的既有 read语义。
  - [x] lifecycle gate 与既有 player visibility、clock subtype visibility、allowed entity type、exact-only、ambiguity 和 deterministic ordering 组合，不能在某个分支先解析 alias 后绕过 status。
  - [x] `entity_or_text` / `text_or_entity` 的 fallback 不能把已由当前 caller view 可见 SQLite exact/partial ID/name/alias 识别为 non-active 的 row 降级成自由文本后继续形成 ready proposal；对真正不存在或 PLAYER_VIEW hidden 且合同允许自由文本的值保留既有 literal 语义，不得创建 entity binding 或回显 hidden/non-active row详情。
  - [x] 保留 GM/maintenance 的显式 hidden read能力，但 non-active entity 对 action binding 仍不可绑定；不要全局改变 query/context/render 对 retired history 的既有读取语义。
  - [x] 缺失/拒绝 trace 使用现有 bounded missing/ambiguous 合同，不将被排除的 non-active/hidden row 或候选 ID列表投影到 player surface。

- [x] Task 3：覆盖 public ingress no-mutation 与正向控制（AC: 1, 2, 3, 4）
  - [x] 对 retired 与 archived 的 ID/name/alias 输入断言 `ready_to_confirm=false`；在初始无pending/receipt的temporary workspace中保持无新pending action/claim/receipt，且SQLite tables、turn/event、events.jsonl与authoritative confirmation state不变。
  - [x] 覆盖 active visible ID/name/alias 唯一绑定并能产生预期 preview/pending；`player_turn()` 后 SQLite turn/event/facts仍不变。
  - [x] 保留 foreign ID、stale external manifest、hidden/GM-only、missing 与 ambiguous 回归；hidden 断言必须检查 player result/trace/message 中没有数据库 hidden token。
  - [x] 运行现有 binder/action-slot tests，确保 social、travel、gather、explore、craft、routine、combat 与 random-table 合法绑定不退化。

- [x] Task 4：同步 canonical 文档与最终 gates（AC: 1, 2, 3, 4）
  - [x] 更新 `docs/ai-intent-chain.md`、`docs/architecture.md`、`docs/data-models.md` 与 `docs/testing-and-quality-gates.md` 中的 binder lifecycle / authority / focused gate；仅更新真正受影响的 canonical 内容。
  - [x] 从最终 clean Story diff 重跑 focused、adjacent、两套 Campaign validate/test、Markdown links、全仓 `py_compile`、full Ruff、`git diff --check` 与 repository full pytest。
  - [x] 后续任何 review patch 使旧 gate失效时，重跑所有受影响 verification；三路 fresh review 持续收敛到 clean 或只剩正确记录的 dismiss/defer。

### Review Findings

- [x] [Review][Patch] 不可见 exact/non-active shadow 必须在无法绑定时阻断 visible partial 或 free-text 回退 [`rpg_engine/ai_intent/binder.py`:327]
- [x] [Review][Patch] partial lookup 必须把 `%` / `_` 视为字面输入而非 SQL `LIKE` 通配符 [`rpg_engine/ai_intent/binder.py`:388]
- [x] [Review][Patch] 增加真实双 temporary Campaign 的同 ID authority 回归 [`tests/test_retired_entity_binding.py`:302]
- [x] [Review][Patch] 修复 `text_or_entity` exact miss 跳过 non-active partial 检测，并从 public ingress 锁定两种 free-text 回退 [`rpg_engine/ai_intent/binder.py`:347]
- [x] [Review][Patch] negative public ingress 必须验证 workspace confirmation/pending state 未变 [`tests/test_retired_entity_binding.py`:86]
- [x] [Review][Patch] active positive 必须断言 canonical destination 与 pending payload 精确一致 [`tests/test_retired_entity_binding.py`:115]
- [x] [Review][Patch] shared query/read 回归需要覆盖 name/alias/partial/archived/hidden 语义 [`tests/test_retired_entity_binding.py`:230]
- [x] [Review][Patch] public ingress 增加 unknown/empty/NFKC lifecycle 代表矩阵 [`tests/test_retired_entity_binding.py`:196]
- [x] [Review][Defer] pending 创建后、确认前 lifecycle 变化未重验 [`rpg_engine/save_manager.py`:710] — deferred, pre-existing；Story 6.9 与批准规划将修复 owner 限定在 binding stage，该问题需要独立 pending→commit freshness 规划

### Review Findings — Round 2

- [x] [Review][Decision] PLAYER_VIEW hybrid slot 优先保持 hidden non-oracle；用户选择方案 1，hidden row 不参与lifecycle shadow，hybrid 仅作literal、不形成entity binding [`rpg_engine/ai_intent/binder.py`:341]
- [x] [Review][Patch] visible non-active partial 与 active partial 同时命中时不得过早绑定 active 候选 [`rpg_engine/ai_intent/binder.py`:354]
- [x] [Review][Defer] pending→confirm lifecycle freshness 缺口仍属 SaveManager/confirmation owner 的预存问题 [`rpg_engine/save_manager.py`:710] — Round 2 reaffirmed，不扩入 Story 6.9

### Review Findings — Round 3

- [x] [Review][Patch] hybrid composite literal 不得被 resolver 二次解析为 visible non-active 实体 [`rpg_engine/ai_intent/binder.py`:243]
- [x] [Review][Patch] canonical docs 必须明确 active exact 优先与non-active exact/partial 阻断次序 [`docs/ai-intent-chain.md`:319]
- [x] [Review][Patch] 增加无 visible partial 候选时 entity-only hidden-present/absent 均 missing 的 paired oracle [`tests/test_retired_entity_binding.py`:488]
- [x] [Review][Patch] public hidden/absent paired oracle 使用独立 workspace，并分别核验 pending entity bindings/facts [`tests/test_retired_entity_binding.py`:560]
- [x] [Review][Patch] 增加 active exact 胜过 non-active partial 的优先级回归 [`tests/test_retired_entity_binding.py`:456]
- [x] [Review][Patch] `LIKE` 字面语义必须同时覆盖含 `%`/`_`/`!` 的真实 entity 与 shared query consumer [`tests/test_retired_entity_binding.py`:300]
- [x] [Review][Patch] GM/maintenance 的 hidden active/non-active direct binder 控制需与 visibility-first 决策一致 [`tests/test_retired_entity_binding.py`:488]
- [x] [Review][Defer] binding connection 与resolver/preview connection 之间的 lifecycle TOCTOU [`rpg_engine/runtime.py`:1473] — deferred, pre-existing cross-owner freshness design，需与 pending→confirm revalidation 统一规划

### Review Findings — Round 4

- [x] [Review][Patch] secondary resolver 的case/token/body/FTS路径不得复活visible non-active实体 [`rpg_engine/ai_intent/binder.py`:389]
- [x] [Review][Patch] composite canonical shadow必须使用token/phrase边界，短alias不得命中无关单词内部 [`rpg_engine/ai_intent/binder.py`:474]
- [x] [Review][Patch] non-active composite reference必须先于active partial候选阻断，避免静默改绑 [`rpg_engine/ai_intent/binder.py`:347]
- [x] [Review][Patch] PLAYER binder lookup必须组合`world_settings.visibility` subtype gate，并以独立hidden/absent workspace锁定public oracle [`rpg_engine/ai_intent/binder.py`:422]

### Review Findings — Round 5

- [x] [Review][Patch] NFKC/casefold canonical shadow不得被SQLite raw `lower/instr`预筛漏掉 [`rpg_engine/ai_intent/binder.py`:442]
- [x] [Review][Patch] qualified ID的token边界必须把`-`/`:`视为continuation，避免non-active短ID前缀误伤active长ID [`rpg_engine/ai_intent/binder.py`:496]
- [x] [Review][Decision] 用户选择方案1：`world_settings.visibility` subtype过滤同时修正shared `find_entity_candidates()`；PLAYER hidden边界优先，retired/non-archived read合同保持不变 [`rpg_engine/ai_intent/binder.py`:291]

### Review Findings — Round 6

- [x] [Review][Patch] Completion Notes与Change Log必须补齐Round 5 patch、用户Decision及最新focused/adjacent证据 [`_bmad-output/implementation-artifacts/6-9-retired-entity-binding-fail-closed.md`:240]

### Review Findings — Round 7

- [x] [Review][Patch] CJK name/alias嵌入无空格自然短语时必须参与visible non-active composite shadow [`rpg_engine/ai_intent/binder.py`:524]
- [x] [Review][Patch] binder NFKC/casefold必须使用项目`EDGE_WHITESPACE_CHARS`剥离U+200B/U+2060，保留active ID正向绑定 [`rpg_engine/ai_intent/binder.py`:535]

### Review Findings — Round 8

- [x] [Review][Patch] edge-whitespace-only输入归一化为空后必须在SQL前返回missing，不能命中空alias或退化成`LIKE '%%'` [`rpg_engine/ai_intent/binder.py`:326]
- [x] [Review][Patch] CJK composite检测必须覆盖Extension B等supplementary Unicode ideograph ranges [`rpg_engine/ai_intent/binder.py`:537]
- [x] [Review][Patch] qualified ID continuation必须包含实际Entity ID grammar允许的`.`，并避免retired短前缀误伤active dotted ID [`rpg_engine/ai_intent/binder.py`:540]

### Review Findings — Round 9

- [x] [Review][Patch] normalized-empty hybrid entity slot必须返回missing，不得降级为free-text literal [`rpg_engine/ai_intent/binder.py`:227]
- [x] [Review][Patch] `text_or_entity` exact-only不得被active contained-ID分支绕过；active composite ID保留literal [`rpg_engine/ai_intent/binder.py`:388]
- [x] [Review][Patch] Completion Notes与Change Log必须补齐Round 7/8 patch与verification证据 [`_bmad-output/implementation-artifacts/6-9-retired-entity-binding-fail-closed.md`:257]

### Review Findings — Round 10

- [x] [Review][Patch] CJK无空格composite识别必须覆盖Hangul、Hiragana、Katakana与Bopomofo，不能仅识别Han ideograph [`rpg_engine/ai_intent/binder.py`:584]

### Review Findings — Round 11

- [x] [Review][Decision] 用户选择方案1：保留Story 6.9 binder边界；被拒绝的新`player_turn()`删除既有pending并更新workspace registry `last_played_at`的预存行为转为Story 6.5 Defer，不在本Story修改SaveManager [`rpg_engine/save_manager.py`:474]
- [x] [Review][Defer] 新turn对既有pending的compare-and-supersede及`last_played_at`元数据语义由Story 6.5统一处理；Story 6.9只保证拒绝不创建新的committable pending或游戏事实 [`_bmad-output/planning-artifacts/epics.md`:1316]

### Review Findings — Round 12

- [x] [Review][Patch] 无空格Unicode脚本的composite lifecycle shadow必须覆盖Thai、Lao、Khmer与Myanmar，不能仅覆盖CJK脚本 [`rpg_engine/ai_intent/binder.py`:584]

### Review Findings — Round 13

- [x] [Review][Patch] Latin canonical name/alias与无空格Unicode脚本相邻时必须按cross-script boundary识别，不能被active partial抢占 [`rpg_engine/ai_intent/binder.py`:575]
- [x] [Review][Patch] 无可靠空格分词边界的Unicode script检测必须覆盖Devanagari及Indic/Brahmic代表脚本 [`rpg_engine/ai_intent/binder.py`:598]

### Review Findings — Round 14

- [x] [Review][Patch] Unicode combining mark与内部format control必须保持分词脚本token continuation，避免retired短alias误伤普通literal [`rpg_engine/ai_intent/binder.py`:599]
- [x] [Review][Patch] Cf/CGJ/variation selector等default-ignorable插入canonical引用时不得绕过NFKC/casefold lifecycle匹配 [`rpg_engine/ai_intent/binder.py`:657]
- [x] [Review][Patch] Cross-script boundary必须按任意不同Unicode letter script识别，覆盖Arabic/Cyrillic包围Latin canonical引用 [`rpg_engine/ai_intent/binder.py`:627]

### Review Findings — Round 15

- [x] [Review][Patch] Canonical identity必须在active partial前统一折叠Mn/Mc/Me与Hangul filler等Default_Ignorable，阻断视觉等同retired引用 [`rpg_engine/ai_intent/binder.py`:679]
- [x] [Review][Patch] Shared resolver partial/body LIKE必须把`%`/`_`/`!`作为字面输入，不能误拒绝普通hybrid literal [`rpg_engine/db.py`:838]
- [x] [Review][Patch] 单codepoint无空格脚本name/alias只参与exact，不得在较长普通词中触发non-active composite shadow [`rpg_engine/ai_intent/binder.py`:576]

### Review Findings — Round 16

- [x] [Review][Patch] Canonical normalization必须覆盖完整Default_Ignorable区段，包括U+2065、U+FFF0区段与Plane 14 [`rpg_engine/ai_intent/binder.py`:701]

### Review Findings — Round 17

- [x] [Review][Patch] 无空格composite policy必须覆盖所有多codepoint非Latin letter script，不能依赖有限script名单 [`rpg_engine/ai_intent/binder.py`:575]

### Review Findings — Round 18

- [x] [Review][Patch] 非Latin single/composite判定必须使用mark折叠前identity，base+mark不得退化为single-codepoint exact-only [`rpg_engine/ai_intent/binder.py`:576]
- [x] [Review][Patch] Shared resolver exact-token ID suffix LIKE必须字面转义`%`/`_`/`!`，不能误拒绝missing hybrid literal [`rpg_engine/db.py`:805]

### Review Findings — Round 19

- [x] [Review][Patch] Canonical mark folding必须先NFKD分解预组合字符，再移除Mn/Mc/Me与Default_Ignorable [`rpg_engine/ai_intent/binder.py`:710]
- [x] [Review][Patch] Resolver在active exact token未命中后，token partial/body/FTS阶段必须检查任一visible non-active命中，不能被同阶段active排序winner遮蔽 [`rpg_engine/ai_intent/binder.py`:423]

### Verification Correction — Round 19

- [x] [Verification][Patch] Resolver shadow必须保留任一active exact token先胜出的阶段优先级，历史partial/body不得误拒绝当前canonical alias [`rpg_engine/ai_intent/binder.py`:455]

### Review Findings — Round 20

- [x] [Review][Patch] Resolver shadow必须按token顺序使用首个exact winner，后续active token不得掩盖更早的non-active exact ID-suffix/name/alias [`rpg_engine/ai_intent/binder.py`:455]
- [x] [Review][Patch] 含未配对UTF-16 surrogate的外部entity slot必须在SQLite前invalid/blocked，不能抛UnicodeEncodeError或进入clarification/pending [`rpg_engine/ai_intent/binder.py`:228]

### Review Findings — Round 21

- [x] [Review][Patch] Shared resolver token/FTS normalization必须与binder共用完整Default_Ignorable folding，Hangul filler等不得复活retired事实 [`rpg_engine/db.py`:738]
- [x] [Review][Patch] Shared partial resolver的WHERE与排序CASE必须一致使用`ESCAPE '!'`，literal `%`/`_`/`!`不得改变候选优先级 [`rpg_engine/db.py`:868]

### Focused Gate

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q \
  tests/test_retired_entity_binding.py \
  tests/test_ai_intent.py \
  tests/test_action_slot_contract.py \
  tests/test_current_native_player_turn.py \
  -p no:cacheprovider
```

### Adjacent Gate

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_mcp_adapter.py \
  tests/test_v1_cli.py \
  tests/test_platform_ai_simulation.py \
  tests/test_cross_campaign_context_smoke.py \
  tests/test_current_native_visibility.py \
  tests/test_current_native_write_safety.py \
  tests/test_surface_inventory.py \
  -p no:cacheprovider
```

## Dev Notes

### 当前可复现基线

- Story 基线 `HEAD` / `origin/main`：`0ef34f34e6413e7913f25181168af736864d9cd6`（Story 1.10）。工作树包含用户既有、未提交的 Correct Course、Iteration 3 rebaseline、test review/trace/gate 与测试支持文件；这些文件必须保留并从 Story 6.9 commit 排除。
- Iteration 3 `BND-03` 参数测试当前结果为 `1 passed, 1 failed`：foreign Campaign ID 已 fail closed；retired location 返回 `ok=true`，在 `assert result["ok"] is False` 处失败。[Source: `_bmad-output/test-artifacts/automation-validation-iteration-3.json`; `tests/test_iteration3_boundary_contract.py`]
- `rpg_engine.ai_intent.binder.find_entity_candidates()` 的 exact 与 partial SQL 当前只使用 `entity_not_archived_sql()`；该 predicate 排除 archived，但允许 retired，因而 ID、name 与 alias 都能把 retired row 带回 binder。[Source: `rpg_engine/ai_intent/binder.py`; `rpg_engine/visibility.py`]
- 现有 `test_binder_visibility_and_archived_binding_are_read_only` 已证明 archived 在 player/GM view 均 missing、hidden 在 player view missing 而 GM view可读；本 Story扩展 lifecycle 绑定合同，不改变显式 hidden read权限。[Source: `tests/test_ai_intent.py`]

### Architecture Compliance

- 权威链保持：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- External contract validator只验证候选 shape/version/safety；实体 currentness 必须由 binder 使用 caller 提供的 active Save SQLite connection重新判断，不能相信 manifest或 candidate。
- Binder lifecycle predicate仅收紧 action entity binding；`find_entity_candidates()` 也被 external entity query arbitration调用，因此普通 query/context/render若有意展示 retired历史记录，继续沿用各自 access contract。本 Story不得把全局 `entity_not_archived_sql()` 或共享 query lookup无条件改成 active-only。
- `player_turn()` 可以发布 pending，但不写事实；non-active binding失败必须发生在 resolver/preview形成 committable pending 之前。
- 所有 surfaces继续薄转发 Kernel结果，不在 MCP/CLI/platform重复 lifecycle判定。

### Existing Code: Current / Change / Preserve

- `rpg_engine/ai_intent/binder.py`
  - Current：exact/partial 的 ID、name、alias lookup排除 archived、应用 player visibility与 subtype visibility，但 retired仍进入候选。
  - Change：增加 binder-only normalized active-only lifecycle lookup，覆盖 exact与partial所有匹配路径，并阻止 known non-active row 经 `entity_or_text` / `text_or_entity` 回退为自由文本。
  - Preserve：slot contract、allowed types、exact-only、ambiguity、confirmation、trace shape、read-only connection ownership。
- `rpg_engine/visibility.py`
  - Current：`entity_not_archived_sql()` 是全局 read语义，很多 query/context/render consumer有意包含 retired。
  - Change：通常不改；如确需共享 helper，只新增含义明确的 bindable/active predicate，不能重定义既有 helper。
  - Preserve：player hidden labels、GM/maintenance显式 hidden view、Unicode label normalization。
- Public ingress / surfaces
  - Current：SaveManager把 external candidate交给 Runtime/router/binder，ready时才发布 pending。
  - Change：消费 binder现有 missing/ambiguous/invalid outcome即可，不增加 surface-specific规则。
  - Preserve：version/safety validation、confirmation/commit、pending claim/replay、平台 identity gates。

### Previous Story / Git Intelligence

- Story 6.4 已把 confirmation原子 claim/replay收回 `SaveManager` owner，并通过十二轮 review证明 adapter不应复制 Kernel语义；Story 6.9同样只修改 binder owner。
- Story 6.3 已确立 `ActionResolverRegistry.slot_contract` 是 slot/allowed entity type的 canonical projection；本 Story不增加 action-specific special case。
- 最近提交 `0ef34f3`、`ce4efd6`、`dff6e4d`、`ee021b4`、`6af8597` 均采用 owner code + self-contained tests + canonical docs + Story/sprint artifact 的 bounded commit结构。
- 不需要新依赖、migration、provider research或跨仓协议；Python stdlib/SQLite现有能力足以完成。

### Expected File Scope

- NEW：`tests/test_retired_entity_binding.py`。
- UPDATE：`rpg_engine/ai_intent/binder.py`。
- UPDATE：`rpg_engine/db.py`（仅同步resolver token/FTS的Unicode mark/format normalization，防止preview二次复活）。
- UPDATE（canonical docs）：`docs/ai-intent-chain.md`、`docs/architecture.md`、`docs/data-models.md`、`docs/testing-and-quality-gates.md`。
- UPDATE（BMAD）：本 Story、validation report、`sprint-status.yaml`；`epics.md` 中 Story 6.9 已属于用户批准的 Correct Course规划，不在 create阶段覆盖或重写。
- 通常不改：`visibility.py` 的既有 `entity_not_archived_sql()`、SaveManager/Runtime/MCP/CLI/platform、schema/migrations、dependencies、Iteration 3 rebaseline tests/helpers/reports、Story 3.8或 Stories 6.5–6.8。

### Testing Requirements

- Focused：direct binder全查找分支、public external candidate入口、active positive、retired/archived/hidden/ambiguous/missing/foreign no-mutation。
- Adjacent：Runtime、SaveManager、MCP/CLI/platform、cross-Campaign、current-native visibility/write safety与surface inventory。
- Package safety：测试创建独立 temporary workspace并复制 Campaign；对 source Campaign/formal current Save/正式 registry只做前后 fingerprint检查，绝不写入。
- Final clean-diff gates：focused、adjacent、两套 Campaign validate/test、Markdown links、全仓 py_compile、full Ruff、`git diff --check`、repository full pytest。

## Project Structure Notes

- Lifecycle binding ownership在 `rpg_engine/ai_intent/binder.py` 的共享 SQLite lookup，不新建 coordinator/service，也不在 action resolver按 action硬编码。
- 新测试必须自包含；未提交的 `tests/conftest.py`、`tests/automation_support/iteration3_fixtures.py` 与 `tests/test_iteration3_boundary_contract.py` 仅作外部 RED evidence，不能成为 Story commit依赖。
- 如果实现发现必须改变全局 retired query语义、增加 migration/dependency、改变 hidden GM view或扩大到 Story 3.8/6.5–6.8，按用户 HALT条件停止并提交证据。

## References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Story 6.9]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-17.md` — §4.2, §8.2, §8.4]
- [Source: `_bmad-output/test-artifacts/automation-validation-iteration-3.json` — BND-03]
- [Source: `_bmad-output/test-artifacts/test-review.md` — Iteration 3 product failures]
- [Source: `_bmad-output/test-artifacts/traceability-matrix.md` — BND-03 FULL/FAIL evidence]
- [Source: `_bmad-output/implementation-artifacts/6-4-atomic-pending-confirmation-claim-and-replay-classification.md` — owner/thin-surface/review intelligence]
- [Source: `docs/project-context.md` — fact/AI/confirmation/package boundaries]
- [Source: `docs/architecture.md` — player-safe intent/preview/pending chain]
- [Source: `docs/ai-intent-chain.md` — binder/external candidate/public surface authority]
- [Source: `docs/data-models.md` — Entity Access Contract / Pending Player State]
- [Source: `docs/testing-and-quality-gates.md` — AI intent and package safety gates]
- [Source: `rpg_engine/ai_intent/binder.py` — `bind_intent_candidate`, `find_entity_candidates`]
- [Source: `rpg_engine/visibility.py` — status/visibility SQL normalization]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Create Story RED：Iteration 3 BND-03参数测试 `1 passed, 1 failed`；retired分支返回 `ok=true`。
- Create Story code trace：`SaveManager.player_turn` → Runtime/router → `bind_intent_candidate` → `bind_slot_value` → `find_entity_candidates`。
- Dev Story RED：新增自包含 focused test初始 `13 failed, 11 passed`；失败覆盖retired public ingress、ID/name/alias、free-text fallback、partial/exact优先级、active alias替换与unknown lifecycle。

### Implementation Plan

- RED：新增不依赖 rebaseline worktree的 temp-Save tests，锁定 direct binder与public ingress的 ID/name/alias retired/archived失败及 active positive。
- GREEN：在 binder exact/partial查询使用同一 normalized active-only lifecycle predicate。
- REFACTOR：保持 trace/missing/ambiguity与surface shape不变，同步 canonical docs。
- VERIFY：focused/adjacent/package/docs/static/full suite，之后三路 fresh review持续自动收敛。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created。
- Task 1完成：tracked test不依赖Iteration 3未提交fixtures，在temporary Save上锁定direct binder与public ingress RED，并保留source Campaign fingerprint。
- Task 2完成：binder-only lookup按NFKC normalized `active`过滤，exact优先于partial；known non-active exact/partial不进入free-text fallback，默认query lookup保持原read语义。Focused binder/action-slot `121 passed, 185 subtests`，Ruff/py_compile/diff-check通过。
- Task 3完成：Story tests `24 passed`；current-native + Iteration 3 BND `6 passed, 12 subtests`。Retired/archived ID/name/alias均无committable pending/receipt/Save mutation，active positive仍产出pending；hidden DB-only canary、foreign/missing/ambiguous/stale contract保持fail closed。
- Task 4完成：同步四份canonical docs；focused `124 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`，两套Campaign validate/test、209 Markdown links、全仓py_compile、full Ruff与diff-check通过。
- Repository full：当前用户worktree `1482 passed, 10331 subtests, 1 failed`，唯一失败为已批准给Story 3.8的未提交QRY-02 test；`HEAD + Story 6.9`独立clean tree完整通过 `1382 passed, 10331 subtests`。
- Dev Story DoD通过：全部Tasks/AC完成，无新增依赖、migration、production test API或surface逻辑；Story与sprint状态设为review，进入三路fresh code review。
- Code Review Round 1：Blind / Edge / Acceptance 三路 fresh review 原始候选去重为 11 项；8 项明确 patch 已全部应用，1 项 pending→commit freshness 预存缺口已 defer，2 项与 AC/实际 fixture 冲突的 finding 已 dismiss。Patch 后 Story test `53 passed`，focused `153 passed, 197 subtests`，Ruff/py_compile/diff-check 通过。
- Code Review Round 2：三路 fresh review 共同复现 PLAYER_VIEW hybrid hidden-vs-absent 的结果类别 oracle，归类为 1 个真实 Decision；另有 1 个 partial-vs-partial 明确 patch 等待 Decision 先解决后应用。Pending→confirm freshness defer 被 Acceptance Auditor 再次确认边界正确。
- Decision Resolution（2026-07-18）：用户选择方案 1（hidden non-oracle 优先）。Binder 恢复 PLAYER_VIEW visibility-first，hidden-present/absent 成对 direct/public 结果同形；visible non-active partial 先于 active partial fail closed。Story test `54 passed`。
- Code Review Round 3：三路 fresh review 去重、复现后应用 7 个范围内 patch；composite canonical reference 在resolver二次解析前阻断visible non-active，paired hidden/absent分别使用独立workspace核验binding/facts，补齐active-exact优先、LIKE字面字符和GM/maintenance控制。另记录1项跨connection lifecycle TOCTOU defer，其余噪声/越界finding dismiss。Story test `75 passed`。
- Code Review Round 4：Blind / Edge / Acceptance 三路fresh review分别报告3/3/1项，去重为4个明确patch、0 Decision、0新增Defer。Canonical shadow改为casefold token/phrase边界并镜像resolver non-active结果，前移到active partial之前；shared lookup组合world-setting subtype visibility。新增public body/FTS、短alias、active-partial冲突与独立world-setting hidden/absent回归；Story test `82 passed`。
- Code Review Round 5：Blind与Edge在Decision HALT前去重为2个明确patch与1个Decision；按workflow未把未启动的Acceptance冒充第三路。用户选择方案1，确认world-setting subtype hidden过滤同时适用于binder与shared PLAYER query；binder-only match在SQL前统一NFKC/casefold，qualified ID边界把`-`/`:`作为continuation。Story test `86 passed`，focused `186 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。
- Code Review Round 6：Blind与Edge均clean；Acceptance确认AC1–4与package/no-mutation边界通过，仅发现本Story Completion Notes/Change Log漏记Round 5的P2 artifact patch，已补齐。代码无新finding。
- Code Review Round 7：三路fresh review去重为2个patch；CJK name/alias支持无空格自然短语，binder使用项目edge-whitespace集合处理U+200B/U+2060。Story test `90 passed`，focused `190 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。
- Code Review Round 8：三路fresh review去重为3个patch；normalized-empty在SQL前fail closed，supplementary CJK ranges通过Unicode character name识别，qualified ID continuation补齐`.`并为active composite ID建立canonical binding。Story test `95 passed`，focused `195 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。
- Code Review Round 9：Blind与Acceptance共同复现normalized-empty hybrid与`text_or_entity` exact-only回归，Edge clean；另补齐Round 7/8 BMAD审计记录。应用3个patch后Story test `96 passed`，focused `196 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。
- Code Review Round 10：Edge与Acceptance clean；Blind复现Hangul/Kana无空格composite未进入lifecycle shadow，去重为1个明确patch。Unicode script检测扩展到Han/Hangul/Hiragana/Katakana/Bopomofo，新增韩文与片假名direct/public回归；Story test `98 passed`，focused `198 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。
- Code Review Round 11：Blind fresh review复现1个Decision候选：被拒绝的请求会触发SaveManager既有pending清除与registry `last_played_at`更新；主代理在独立temporary Save复现同一结果。因修复归属与Story 6.5显式pending supersede AC冲突，按workflow HALT；Edge已中止，Acceptance未启动，不将本轮冒充三路完成。
- Decision Resolution（2026-07-18）：用户选择方案1，保持Story 6.9 binder-only范围；明确no-mutation为拒绝不创建新committable pending/游戏事实，既有pending supersede与`last_played_at`归Story 6.5并记录Defer。Round 11保持中止记录，后续从全新三路review重新开始。
- Code Review Round 12：Edge clean；Blind复现Thai无空格composite可把visible retired name降级成literal并创建pending，去重为1个明确patch；Acceptance在补丁后clean。通用script检测扩展到Thai/Lao/Khmer/Myanmar并新增direct/public回归；Story test `102 passed`，focused `202 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。因本轮产生代码patch，后续仍重新执行三路fresh review。
- Code Review Round 13：Blind与Edge分别复现cross-script Latin canonical boundary与Devanagari连写绕过，去重为2个明确patch。Canonical reference matcher按无可靠空格分词script转换识别Latin name/alias，并扩展Indic/Brahmic代表脚本；Story test `108 passed`，focused `208 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。本轮产生代码patch，继续执行下一轮三路fresh review。
- Code Review Round 14：Blind与Edge去重为3个明确patch：combining mark伪造短alias token、CGJ/variation-selector视觉等同canonical绕过，以及Arabic/Cyrillic包围Latin的cross-script漏拦截。Binder统一default-ignorable/script boundary，shared resolver tokenizer在NFKC后折叠mark/format，避免preview二次读取retired facts。Story test `115 passed`，focused `215 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`；继续下一轮三路fresh review。
- Code Review Round 15：Blind与Edge去重为3个明确patch：canonical内部Mn/Mc/Me/Hangul filler绕过、shared resolver LIKE元字符误命中、单codepoint无空格alias误伤普通词。Canonical两侧统一折叠mark/default-ignorable，单codepoint仅exact，resolver partial/body字面转义。Story test `123 passed`，focused `223 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`；继续下一轮三路fresh review。
- Code Review Round 16：Blind与Edge共同复现Default_Ignorable表遗漏，去重为1个明确patch。Canonical normalization补齐U+2065、U+FFF0区段、shorthand/Cf相关区段与Plane 14；public control-character safety保持独立。Story test `126 passed`，focused `226 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`；继续下一轮三路fresh review。
- Code Review Round 17：Blind与Edge分别以Arabic、Georgian复现有限script名单漏拦截，去重为1个明确patch。Composite policy收敛为所有多codepoint非Latin letter script按substring fail closed，单codepoint仍只exact、纯Latin仍保留词内边界。Story test `130 passed`，focused `230 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`；继续下一轮三路fresh review。
- Code Review Round 18：Edge clean；Blind复现base+mark被folding后误判single-codepoint，以及exact-token ID suffix LIKE未转义，去重为2个明确patch；Acceptance在补丁后clean。Single/composite使用folding前identity，shared resolver suffix LIKE字面化。Story test `132 passed`，focused `232 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`；因本轮有代码patch继续下一轮三路fresh review。
- Code Review Round 19：三路finding去重为2个明确review patch：NFKD预组合mark folding与任一non-active resolver-stage winner检查。补丁后focused捕获active exact token阶段优先级回归，自动应用1个verification patch并新增自包含控制；最终Story test `135 passed`，focused `235 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。本轮仍有代码patch，继续下一轮三路fresh review。
- Code Review Round 20：Acceptance clean；Blind与Edge各复现1个明确patch，分别关闭“后续active exact token掩盖更早non-active exact winner”与未配对UTF-16 surrogate异常退出。主流程在独立temporary Save复现、应用2个patch；Story test `137 passed`，focused `237 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。本轮有代码patch，继续下一轮三路fresh review。
- Code Review Round 21：Blind与Edge的Default_Ignorable secondary-resolver finding去重为1项，Acceptance另复现partial LIKE排序CASE的ESCAPE退化；主流程复现并应用2个patch。Binder/shared resolver共用完整folding规则，partial过滤/排序统一literal语义；Story test `139 passed`，focused `239 passed, 197 subtests`，adjacent `248 passed, 9293 subtests`。本轮有代码patch，继续下一轮三路fresh review。
- Code Review Round 22：Blind、Edge、Acceptance三路fresh review同轮CLEAN；无新增Patch、Decision或Defer。Blind定向9项、Acceptance完整Story gate与各路temporary Save审计均通过，review收敛完成。
- Final clean-diff verification：focused `239 passed, 197 subtests`；adjacent `248 passed, 9293 subtests`；两套Campaign validate/test均OK；89个Markdown文件local links通过；全仓py_compile、full Ruff与`git diff --check`通过；显式formal roots的独立clean Story tree repository full suite `1497 passed, 10331 subtests`（2个既有`p0` marker warning，退出码0）。Story与Sprint设为done；Epic 6因6.5–6.8仍未完成保持in-progress。

### File List

- `_bmad-output/implementation-artifacts/6-9-retired-entity-binding-fail-closed.md`
- `_bmad-output/implementation-artifacts/6-9-retired-entity-binding-fail-closed.validation-report.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `rpg_engine/ai_intent/binder.py`
- `rpg_engine/db.py`
- `tests/test_retired_entity_binding.py`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`

## Change Log

- 2026-07-17：Create Story 完成规划、BND-03 RED、架构/源码/测试/前序 Story/Git情报分析；状态设为 ready-for-dev。
- 2026-07-17：Validate Story完成fresh-context复核；2项Critical与2项Enhancement均自动吸收，无Decision，保持ready-for-dev。
- 2026-07-17：Dev Story完成binder active-only lifecycle gate、self-contained tests、canonical docs与required gates；状态设为review。
- 2026-07-17：Code Review Round 1 完成三路 fresh review；应用 8 个有效 patch，记录 1 个 defer，dismiss 2 个噪声/冲突 finding，受影响 focused gate 重跑通过。
- 2026-07-17：Code Review Round 2 发现 1 个 PLAYER_VIEW hybrid hidden non-oracle 真实 Decision 与 1 个 partial shadow patch；按 workflow 暂停并将 Story 设为 in-progress。
- 2026-07-18：用户决定采用 hidden non-oracle 优先方案；实施 visibility-first hybrid literal 语义、paired oracle tests 与 visible partial 冲突 fail-closed patch。
- 2026-07-18：Code Review Round 3应用7个有效patch、记录1个freshness defer并dismiss越界/冲突finding；Story自包含测试75项通过，进入受影响verification与下一轮fresh review。
- 2026-07-18：Code Review Round 4三路报告去重为4个有效patch，无Decision/新Defer；修复resolver语义对齐、短alias边界、composite优先级与world-setting subtype visibility，Story自包含测试82项通过。
- 2026-07-18：Code Review Round 5在Decision HALT前发现2个patch；用户选择方案1保留shared world-setting hidden过滤，随后完成binder-only NFKC/casefold与qualified-ID continuation修复，Story测试86项、focused 186项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 6代码审查clean，Acceptance仅要求补齐Round 5 BMAD审计记录；artifact patch完成后进入下一轮fresh review。
- 2026-07-18：Code Review Round 7应用2个patch，关闭CJK无空格composite与U+200B/U+2060 active正向绑定边界。
- 2026-07-18：Code Review Round 8应用3个patch，关闭normalized-empty SQL、supplementary CJK与dotted qualified-ID边界。
- 2026-07-18：Code Review Round 9应用2个代码patch与1个BMAD artifact patch；最新Story/focused/adjacent gates通过。
- 2026-07-18：Code Review Round 10应用1个代码patch，关闭Hangul/Kana等CJK无分词脚本的无空格composite lifecycle绕过；Story 98项、focused 198项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 11在Blind阶段发现并复现1个SaveManager pending/workspace no-mutation Decision；按BMAD Decision HALT，等待用户裁决后继续三路fresh review。
- 2026-07-18：用户选择方案1，将既有pending supersede与`last_played_at`归入Story 6.5 Defer；Story 6.9保持binder-only边界并重新启动完整三路fresh review。
- 2026-07-18：Code Review Round 12应用1个patch，将无空格Unicode script lifecycle shadow扩展至Thai/Lao/Khmer/Myanmar；Story 102项、focused 202项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 13应用2个patch，关闭Latin canonical cross-script边界与Devanagari/Indic/Brahmic连写绕过；Story 108项、focused 208项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 14应用3个patch，关闭combining/default-ignorable与任意cross-script边界，并同步shared resolver tokenizer；Story 115项、focused 215项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 15应用3个patch，关闭mark/filler canonical绕过、resolver LIKE通配与单codepoint alias误伤；Story 123项、focused 223项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 16应用1个patch，补齐完整Default_Ignorable canonical folding且保留public safety gate；Story 126项、focused 226项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 17应用1个patch，将有限script名单收敛为统一多codepoint非Latin policy；Story 130项、focused 230项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 18应用2个patch，修复base+mark identity与resolver exact-token suffix LIKE字面语义；Story 132项、focused 232项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 19应用2个review patch，并在verification应用1个阶段优先级修正；Story 135项、focused 235项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 20应用2个review patch，修复resolver ordered exact winner与surrogate fail-closed；Story 137项、focused 237项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 21应用2个review patch，对齐binder/shared resolver完整Default_Ignorable folding并修复partial LIKE排序ESCAPE；Story 139项、focused 239项/197 subtests、adjacent 248项/9293 subtests通过。
- 2026-07-18：Code Review Round 22三路fresh review同轮CLEAN；进入最终clean-diff required gates。
- 2026-07-18：最终clean-diff required gates全部通过；Story 6.9与Sprint条目设为done，Epic 6保持in-progress。

## BMAD Provenance

- 用户触发：直接启动 Story 6.9完整 Story Cycle，并继承先前授权的自动 validation、dev、三路 fresh review、patch收敛、verification、commit、push与 HEAD对账。
- Catalog route：`bmad-help/catalog` 确认 `[CS] bmad-create-story:create` → `[VS] bmad-create-story:validate` → `[DS] bmad-dev-story` → `[CR] bmad-code-review`。
- `[CS]` skill：完整读取 `.agents/skills/bmad-create-story/SKILL.md`；customization resolver得到空 prepend/append/on_complete与 `file:{project-root}/**/project-context.md` persistent fact；加载 `_bmad/bmm/config.yaml`、`docs/project-context.md`，并按 Steps 1→6执行。
- Create Story sources：sprint status、Epic 6/Story 6.9、Correct Course proposal、Iteration 3 automation/test-review/trace/gate evidence、Story 6.4、canonical architecture/intent/data/testing docs、binder/visibility/entity access源码、现有binder/public-ingress测试与 recent Git history。
- 本 Story不改变外部依赖、数据库 schema或API版本，因此不需要网络研究。
