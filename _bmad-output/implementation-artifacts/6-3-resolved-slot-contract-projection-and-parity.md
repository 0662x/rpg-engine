---
baseline_commit: 6af8597202393edd92e45033e297133078e67d9f
---

# Story 6.3：解析后槽位合同投影与一致性

Status: done

## Story

作为 action contract maintainer，
我希望 slot metadata 只有一个解析后投影或可执行一致性门，
从而避免 resolver、binder、manifest 与 internal prompt 维护互不兼容的要求。

## Acceptance Criteria

1. **Resolver-owned resolved slot contract**
   - Given 一个 action 声明 required slots、any-of groups、aliases、types、AI-fillable fields、binding rules 或 confirmation requirements，when 解析其 slot contract，then `ActionResolverSpec` / `ActionResolverRegistry` 产生一个 normalized、不可变、确定性的 metadata projection。
   - Binder、live intent manifest 与 internal intent prompt 必须消费同一 resolved projection；不得继续分别维护 required/alias/type/confirmation 或 any-of 特例。
   - Requirement group 必须能表达 `random_table` 的 `table` / `dice` exactly-one cardinality（缺一不可接受、两者同时存在也不可接受），并显式表达 `routine` 当前 source-user-text binding fallback；不得靠 consumer 内 hardcode action 名形成例外。
   - Builtin、合法 custom/injected registry 与 compatibility constructor 都必须经过同一 normalization/validation；falsey injected registry 不得回退到 default registry。

2. **Legacy metadata parity 与 fail-closed 迁移**
   - Given 某张 legacy runtime table 暂时不能安全删除，when focused parity gate 将其与 resolved projection 比较，then missing、extra 或语义不同的 metadata 必须以 owning action 与 field/path 报错。
   - Unguarded parallel hand-maintenance 不得作为完成状态；legacy compatibility 只能由 canonical projection 派生，或作为有明确删除条件的只读 adapter，并有 executable parity test。
   - 现有无法被 resolver option 接收的 legacy alias/binding 项只有在 characterization 证明其一直被忽略后才可移除；不得通过新增 option 将原本 ignored 的 slot 悄悄变成可执行输入。
   - `required_options` 若为 compatibility input，必须在构造时单向归一化为 canonical slot metadata；对现有 `required_options=("target",)` 且无 `option_specs` 的 custom resolver，合成项必须锁定当前 binder 默认语义：required text、无 aliases/allowed entity types/default/confirmation、AI-fillable。Canonical 与 legacy declarations 冲突时 fail closed，不能让两个值并存。

3. **Binding、visibility 与 confirmation 行为不回退**
   - Given slot projection cleanup 已完成，when binding 与 visibility regression gates 运行，then current required/any-of、aliases、text/list/dice/entity binding、ambiguity/missing classification、confirmation 与 player-visible entity binding 行为保持不变。
   - Hidden/GM-only、archived、missing 或 ambiguous entity 不得因 projection 迁移进入 player binding、manifest、prompt、trace 或 public output；binder 继续通过现有 visibility/access SQL 读取事实。
   - AI-supplied `combat.ready_state` 仍必须被忽略并要求 direct player confirmation；AI/internal prompt 不得把 confirmation-only slot 标成 fillable。
   - `random_table` 缺少 table/dice、combat 缺少 required slots、travel/social/gather/explore/craft/routine 的现有成功与失败分类必须由同一 contract 产生，并通过 characterization tests 锁定。

4. **范围与权威保持不变**
   - 本 Story 不压缩 route representations、不引入 `IntentCoordinator` / `TurnCoordinator`、不修改 pending/clarification/confirm/commit 生命周期，也不把 slot ownership design debt 描述为已复现 runtime defect。
   - External/internal AI 继续只提供低信任 candidate/review；resolver、binder、preview、validation、玩家确认与 commit authority 仍在 Kernel。
   - 不新增 Campaign/Save schema、数据库 migration、依赖、动态 plugin/locale loader、CLI/MCP execution surface 或测试专用 production API。
   - 所有写测试使用 temporary Campaign/Save/workspace；source Campaign、formal current Saves、workspace registry 与 `data/game.sqlite` 不得被修改。

## Tasks / Subtasks

- [x] Task 1：建立 resolver-owned canonical slot contract（AC: 1, 2）
  - [x] 定义 frozen、JSON-safe 的 slot、requirement-group 与 resolved action-slot contract 类型；字段至少覆盖 name/dest/description、binding type、allowed entity types、aliases、required、default、AI-fillable、player-confirmation-required、group cardinality 与 binding rule。
  - [x] 为 exact built-in types、duplicate slot/alias/group、alias collision、unknown group member、invalid type/entity combination、confirmation+AI-fillable conflict及非确定性输入增加 fail-closed validation；没有规划证据时不新增任意 numeric/string collection caps。
  - [x] `ActionResolverSpec` 在构造时生成 canonical slot contract；`ActionResolverRegistry` 注册前验证 prospective contract，失败后 registry names/taxonomy/slot projection 必须不变。
  - [x] 保持 `ActionOptionSpec`、`required_options`、`.option_specs` 的必要只读 compatibility surface；legacy input 只能单向归一化，canonical/legacy 冲突必须明确报错。
  - [x] Projection 必须有稳定 action/slot/group/alias 排序、defensive copies 与跨 `PYTHONHASHSEED` wire stability；复用现有 canonical JSON helper，不复制 digest 算法。

- [x] Task 2：迁移 builtin slot metadata 并消除平行真源（AC: 1, 2, 3）
  - [x] 将九个 builtin resolvers 的 required、aliases、types、allowed entity types、AI fillable 与 confirmation metadata 移入其 resolver-owned contract。
  - [x] 将 `random_table` 的 `random_source(table|dice)` exactly-one 与 `routine_scope(task|target)` 迁入 canonical requirement groups；routine 的现有 `source_user_text` binder fallback 必须作为 group binding rule 显式建模。
  - [x] Characterize 并处理 stale metadata：`social.target` 当前经 binder 判为 outside resolver contract；`gather.destination` 当前先 alias 到可执行的 `location`，因此必须继续有效，但其同名 binding-table 项在 alias 后不可达。不得把 cleanup 变成新增 accepted slot 或改变既有 alias 语义。
  - [x] Characterize `travel.palette_id` 当前默认 text binding，并在 canonical contract 中显式记录，不依赖 binder fallback default。
  - [x] 删除 `intent_manifest.py` 中按 action 名硬编码的 requirement groups，以及 binder 对 required/alias/type/confirmation 的平行表读取。

- [x] Task 3：让 binder 只消费 active registry 的 resolved contract（AC: 1, 3, 4）
  - [x] `bind_intent_candidate()`、slot-name normalization、allowed options、binding type、required/group evaluation 与 confirmation-only rejection 全部使用 resolved contract。
  - [x] 保留现有 exact/partial entity matching、`entity_or_text` / `text_or_entity` 区别、dice validation、text-list normalization、missing/ambiguous/invalid classification 与 trace shape。
  - [x] 保留 player-view visibility SQL、hidden/archived exclusion 与 generic binding outcome；不得让 manifest/prompt metadata触发额外 SQLite read 或泄露 hidden existence。
  - [x] Custom/falsey injected registry 的 custom slots、aliases、types、requirements 与 confirmation rules必须贯通 normalize → binder → manifest → internal prompt，不得回退 default contract。
  - [x] 若保留 `rpg_engine.ai_intent.slot_contract` import path，仅可 re-export canonical types/helpers或由 projection 派生只读 compatibility，不得保留独立可编辑 tables。

- [x] Task 4：让 manifest、prompt 与 introspection 发布同源投影（AC: 1, 2, 3）
  - [x] `build_intent_manifest(registry=...)` 从 active registry resolved slot contract 构建既有 action `slots` / `requirement_groups` wire shape；builtin wire 语义保持兼容。
  - [x] 仅在确实新增/改变 public manifest wire shape 时提升 `MANIFEST_SCHEMA_VERSION`；若 wire shape 不变，则保持 v3，并证明 canonical slot metadata 变化仍旋转整体 `manifest_digest`。
  - [x] Internal intent prompt 继续从 live manifest 摘录 slots/groups，不重新硬编码 action 或 slot policy；confirmation-only 与 AI-fillable 必须精确一致。
  - [x] MCP `intent_manifest` 保持 thin wrapper；CLI resolver list/detail 若展示 slot contract，应调用 registry render/projection helper，不在 adapter/CLI 复制 metadata。
  - [x] Prompt 语义或 manifest schema 若变化，同步 `docs/prompts/ai-client-prompt.md` 的 Prompt version；仅内部 owner 迁移且 wire 兼容时不得无理由改 public版本。

- [x] Task 5：建立 slot contract、parity 与安全回归门（AC: 1, 2, 3, 4）
  - [x] 新增 focused slot-contract tests：frozen/defensive copy、exact-type validation、alias/group collision、registration atomicity/order、hash-seed stability、legacy normalization/conflict 与 custom/falsey registry。
  - [x] 逐 action 比较 resolver projection、binder、manifest 与 internal prompt；错误必须包含 action + field/path，禁止只做 loose set equality。
  - [x] Characterize required/group cardinality：travel、social、gather、explore、craft、combat、routine、random_table（none/only-table/only-dice/both 四分支），以及 rest optional/default。
  - [x] 对 routine 明确断言：`slots={}` + 非空 source user text 仍满足 binder completeness；manifest/internal prompt 仍向 AI 发布 `task|target`，且 `user_text` 不得成为 AI-fillable slot；resolver request behavior 保持不变。
  - [x] Characterize aliases/types：entity exact/partial/text fallback、text/text-list/dice/random-table id、unknown/extra slot、stale table-only aliases 与 custom slot。
  - [x] Characterize confirmation/visibility：`combat.ready_state`、hidden/archived/missing/ambiguous entity、player vs trusted view，并证明 no fact/pending/turn/event mutation。
  - [x] 回归 Story 6.1/6.2 contract identity、taxonomy/prompt/custom-registry/preflight digest、off-mode external-primary、consensus、low-level mismatch、current-native player/context/visibility 与 MCP player profile。
  - [x] Focused union 至少包含：
    ```bash
    PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q \
      tests/test_action_slot_contract.py \
      tests/test_intent_manifest.py \
      tests/test_ai_intent.py \
      tests/test_action_taxonomy.py \
      tests/test_runtime.py \
      tests/test_mcp_adapter.py \
      tests/test_v1_cli.py \
      -p no:cacheprovider
    ```
  - [x] Adjacent union 至少包含：
    ```bash
    PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q \
      tests/test_preflight_cache.py \
      tests/test_platform_prewarm.py \
      tests/test_platform_ai_simulation.py \
      tests/test_platform_sidecar.py \
      tests/test_save_manager.py \
      tests/test_p0_stop_loss_acceptance.py \
      tests/test_surface_inventory.py \
      tests/test_eval_suite.py \
      tests/test_mcp_transcript.py \
      tests/test_current_native_player_turn.py \
      tests/test_current_native_context.py \
      tests/test_current_native_visibility.py \
      tests/test_current_native_write_safety.py \
      tests/test_cross_layer_regression.py \
      -p no:cacheprovider
    ```

- [x] Task 6：同步 canonical docs 与最终质量门（AC: 1, 2, 3, 4）
  - [x] 更新实际受影响的 `docs/architecture.md`、`docs/component-inventory.md`、`docs/ai-intent-chain.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`、AI client prompt 与 `docs/testing-and-quality-gates.md`；若 CLI introspection 输出变化，同步 `docs/cli-contracts.md`。无行为变化的 surface 不做无关重写。
  - [x] 明确 Story 6.3 关闭 slot ownership/parity design debt，但未证明旧 runtime 已错误，也未提前实现 Stories 6.4–6.8。
  - [x] 从最终 clean diff 重跑 focused、adjacent regression、两套 Campaign validate/test、Markdown links、全仓 `py_compile`、full Ruff、`git diff --check` 与 repository full pytest；任何后续 patch 使旧 gate 失效时必须重跑。

## Dev Notes

### 当前可复现基线

- 当前 `HEAD` / `origin/main`：`6af8597202393edd92e45033e297133078e67d9f`（Story 6.2）。工作树在 Create Story 开始时干净。
- Baseline：`PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q tests/test_intent_manifest.py tests/test_ai_intent.py -p no:cacheprovider` → `88 passed, 135 subtests passed`。
- 当前没有复现 slot runtime failure；已确认的是 ownership split：
  - `ActionResolverSpec.required_options` / `ActionOptionSpec` 持有 resolver options；
  - `rpg_engine/ai_intent/slot_contract.py` 分别持有 binding type、aliases、required 与 AI confirmation；
  - `rpg_engine/intent_manifest.py` 单独硬编码 `random_table` / `routine` requirement groups；
  - `binder.required_missing()` 再合并并按 action 名处理 group/fallback。
- 只读 introspection 发现：`social.target` 在 AI binder 会因不属于 resolver options 被 ignored，但 low-level social resolver compatibility 仍可直接读取 `target`；`gather.destination` 会先由 alias 归一化为可执行 `location`，仅其同名 binding-table 项在 alias 后不可达；`travel.palette_id` 没有显式 binding metadata并回退为 text。迁移必须按 surface 锁定这些行为，不能把 stale metadata cleanup 变成新能力。
- `routine` binder 当前允许 `source_user_text` 满足 binding completeness，而 manifest 对 AI candidate 发布 `task|target` requirement group。新 contract 必须显式表达两层语义，不得在 binder/manifest继续各写一个 action-name 特例，也不得把这个 design debt夸大为已发生玩家故障。

### Legacy Migration Matrix

| Action / slot | 当前入口与结果 | Canonical target |
| --- | --- | --- |
| `social.target` | AI binder ignored；low-level resolver compatibility 可读取 | 不扩展 AI accepted slots；保留 low-level compatibility 的既有边界 |
| `gather.destination` | AI binder alias 为 `location` 后可执行；同名 binding-table entry 不可达 | 保留 alias；删除或派生不可达平行 binding metadata |
| `travel.palette_id` | Resolver option 可接收，binder 依赖默认 text | 显式 canonical text binding |
| `routine.source_user_text` | 只作为 binder completeness fallback | Group binding rule；不得发布为 AI-fillable candidate slot |
| `combat.ready_state` | AI supplied value ignored并要求玩家确认 | Canonical confirmation-only、`ai_fillable=false` |
| Custom legacy `required_options` | Binder可接收/要求；manifest当前不发布 | 构造时合成 required text slot，同源进入 binder/manifest/prompt |

### Architecture Compliance

- 权威链不变：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- Slot contract 属于 registered resolver 的 player-safe static metadata；不得从 `data/game.sqlite`、Campaign hidden content、AI output 或 runtime trace 生成。
- Binder 仍负责将低信任字符串绑定到 player-visible entities；resolved metadata 不进行事实读取、不拥有 preview/validation/confirmation/commit authority。
- `data/game.sqlite` 仍是事实权威；manifest、prompt、trace 与 slot projection 都只是 contract/evidence。
- 不新增 Coordinator、不压缩 route types、不接管 SaveManager/pending/confirm，不改 external candidate contract四字段 identity。

### Existing Code: Current / Change / Preserve

- `rpg_engine/actions/base.py`
  - Current：`ActionOptionSpec` 只有 name/help/required/default/dest；`ActionResolverSpec.required_options` 与 taxonomy同属 resolver spec。
  - Change：承接或组合 canonical frozen slot contract，并在构造/registry registration 时 normalize/validate。
  - Preserve：preview/request/resolve/delta hooks、taxonomy contract、subclass registration compatibility 与 resolver执行顺序。
- `rpg_engine/ai_intent/slot_contract.py`
  - Current：四张按 action 名维护的 mutable dict/set table。
  - Change：删除平行 owner；必要时只保留 canonical re-export/derived compatibility。
  - Preserve：builtin semantic values，除已证明 unreachable 的 stale entries 外不改 accepted behavior。
- `rpg_engine/ai_intent/binder.py`
  - Current：从 tables 与 spec options 合并 required/type/alias/confirmation，并自行硬编码 routine/random-table rules。
  - Change：只读取 active spec resolved contract，并用共享 group evaluator。
  - Preserve：entity SQL、visibility、exact/partial matching、trace、classification 与 no-write behavior。
- `rpg_engine/intent_manifest.py`
  - Current：从 resolver option + slot tables + action-name special cases 拼装 wire contract。
  - Change：直接投影 active registry 的 resolved slot contract。
  - Preserve：versioned manifest/safety v1/taxonomy v1 identity、canonical full-payload digest、query contract 与 thin surfaces；若 review 证明现有 group wire 无法表达权威语义，则按 Task 4 规则提升 manifest schema。
- `rpg_engine/ai_intent/prompts.py`
  - Current：已经从 manifest 摘录 slot/group contract。
  - Change：只需验证/最小适配 canonical projection，不添加 parallel metadata。
  - Preserve：player-safe redaction、visible entities与 low-trust prompt authority。

### Previous Story Intelligence

- Story 6.2 已建立成功模式：canonical frozen leaf contract → resolver owner → registry projection → router/manifest/prompt consumer；Story 6.3 应复用这个依赖方向和 `canonical_json_sha256()`，不要复制 hash/排序逻辑。
- 6.2 review 反复捕获 falsey injected registry fallback、legacy/canonical constructor conflict、generator bounds、registration atomicity、custom registry chain 与 preflight identity遗漏。Slot contract应在首轮设计中直接覆盖这些相同 seam。
- 6.2 明确没有提前迁移 `ACTION_REQUIRED_SLOTS` 或 AI confirmation slots；本 Story 正是该后续 owner，不应回头修改 taxonomy grammar。
- 6.2 最终 required gates 为 `1016 passed, 10245 subtests passed`；当前 Story 必须在最终 clean diff 上建立新基线，不能复用该旧结果。

### Git Intelligence

- 最近提交：`6af8597 feat(intent): complete Story 6.2 action taxonomy`、`dbced86 feat(intent): negotiate external safety contracts`；两者分别提供 registry projection和 versioned manifest/typed stale-refresh 模式。
- Story 6.2 涉及 `actions/base.py`、`intent_manifest.py`、`ai_intent/binder.py`、`ai_intent/prompts.py`、runtime/injected registry 与 docs/tests；Story 6.3 应保持同样的 registry injection seam，但避免重开 taxonomy/safety 范围。
- 没有新增依赖或框架需求；本 Story 只使用 Python 3.11+ dataclass/typing、stdlib JSON/SQLite 与既有 pytest/Ruff，因此 Create Story Step 4 无需外部版本研究。

### Expected File Scope

- NEW（优先）：`rpg_engine/actions/slot_contract.py`、`tests/test_action_slot_contract.py`。
- UPDATE（核心）：`rpg_engine/actions/base.py`、`actions/__init__.py`、九个 builtin resolver、`rpg_engine/ai_intent/slot_contract.py`、`ai_intent/binder.py`、`intent_manifest.py`、`ai_intent/prompts.py`、`actions/registry.py` 与相关 tests。
- UPDATE（仅实际合同受影响）：canonical intent/architecture/component/MCP/CLI/prompt/testing docs；若 public prompt wire 语义不变，保持 prompt version。
- 通常不改：DB/migrations、Campaign/Save schema、SaveManager、CommitService、preflight lifecycle、MCP adapter business logic、CLI command handlers、platform sidecar/prewarm、Hermes仓库。

### Testing Requirements

- Focused：new slot contract、manifest、binder/arbiter/internal prompt、custom registry、runtime、MCP/CLI contract。
- Adjacent：Story 6.1/6.2 identity/taxonomy/preflight、current-native player/context/visibility、surface inventory、eval/transcript、SaveManager no-mutation。
- Campaign：`examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 均跑 validate/test；测试写入仅在 temp Save。
- Docs/static：Markdown links、全仓 Python `py_compile`、full Ruff、`git diff --check`。
- Final：repository full pytest，且必须是最后一批 patch 后的新鲜结果。

### Project Structure Notes

- Canonical slot contract 放在 `rpg_engine/actions/` leaf layer；依赖方向保持 actions → binder/manifest/prompt/surfaces，不能让 actions contract反向依赖 `ai_intent`。
- `ai_intent/slot_contract.py` 只能作为迁移 adapter/re-export，不能继续成为可编辑 owner。
- Public wire projection必须是 deterministic、JSON-safe、bounded plain data；tuple 在 JSON wire 中按 array。
- 不把 parity检查做成 production endpoint，也不把测试 orchestration 塞进 runtime/MCP/CLI API。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Story 6.3]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md` — §4.2 Story 6.3、§8 排期与成功标准]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md` — slot ownership split、未复现 runtime defect、minimal boundary]
- [Source: `_bmad-output/implementation-artifacts/6-2-canonical-action-taxonomy-registry-projection.md` — resolver registry projection、injected registry 与 review learnings]
- [Source: `docs/project-context.md` — fact/AI/hidden/temporary Save 边界]
- [Source: `docs/governance/bmad-workflow.md` — P0 workflow 与 verification]
- [Source: `docs/architecture.md` — AI intent、resolver、preview/commit边界]
- [Source: `docs/component-inventory.md` — Slot Contract、Binder、ActionResolver ownership]
- [Source: `docs/ai-intent-chain.md` — manifest slot contract、binder与 authority]
- [Source: `docs/mcp-contracts.md` — thin intent manifest 与 player profile]
- [Source: `docs/prompt-contracts.md` — prompt/version触发条件]
- [Source: `docs/testing-and-quality-gates.md` — intent/campaign/current-native/final gates]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Create Story baseline：`88 passed, 135 subtests passed`。
- Task 1 RED：新增测试因 `rpg_engine.actions.slot_contract` 尚不存在而 collection fail。
- Task 1 GREEN：`50 passed, 142 subtests passed`；全仓 `1022 passed, 10254 subtests passed`；相关 Ruff 通过。
- Task 2 RED：builtin canonical metadata 测试出现预期的 20 个失败分支。
- Task 2 GREEN：`98 passed, 173 subtests passed`；全仓 `1026 passed, 10283 subtests passed`；相关 Ruff 通过。
- Task 3 RED：random-table 双来源与 falsey custom alias/confirmation 测试出现预期失败。
- Task 3 GREEN：focused union `204 passed, 388 subtests passed`；全仓 `1029 passed, 10287 subtests passed`；相关 Ruff 通过。
- Task 4 RED：manifest digest 与 falsey custom prompt alias 两项按预期失败。
- Task 4 GREEN：focused union `301 passed, 441 subtests passed`；全仓 `1032 passed, 10296 subtests passed`；相关 Ruff 通过。
- Task 5 GREEN：Story focused `305 passed, 459 subtests passed`；adjacent `191 passed, 9232 subtests passed`；全仓 `1036 passed, 10314 subtests passed`。
- Task 6 docs/static：两套 Campaign validate/test 均 `OK`；Markdown links `88 files`；全仓 `py_compile`、full Ruff、`git diff --check` 均通过。首次 Markdown 命令误扫模板占位链接、首次 py_compile 使用 zsh 只读变量名，纠正编排后均通过。
- Task 6 post-doc：focused `305 passed, 459 subtests passed`；adjacent `191 passed, 9232 subtests passed`；全仓 `1036 passed, 10314 subtests passed`。

### Implementation Plan

- 以 `actions/slot_contract.py` 作为 frozen canonical leaf contract，`ActionResolverSpec` 构造时单向归一化 legacy input，registry 只发布稳定投影与 canonical digest。
- 逐 builtin 迁移 metadata 后，让 binder、manifest、prompt 仅消费 active registry 的 resolved contract；旧 import path 只保留派生只读 adapter。
- 使用 characterization/focused/adjacent/full gates 锁定 binding、visibility、confirmation 与 authority 边界，再进入 fresh 三路 review 收敛。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created。
- Task 1：完成 frozen/JSON-safe slot contract、requirement group、legacy normalization、严格冲突验证、registry atomic projection 与 defensive copy；保留连字符 custom action 兼容。
- Task 2：九个 builtin resolver 已拥有完整 slot metadata；random/routine group 进入 canonical contract；旧 AI slot module 仅保留派生只读 adapter，stale metadata 未扩大 accepted surface。
- Task 3：binder 与 arbiter slot normalization 已切换为 active registry resolved contract；保留 visibility SQL/trace/classification，新增 exactly-one invalid 与 custom falsey registry 全链测试。
- Task 4：manifest/action slot/group 由 active registry 精确投影，custom metadata 贯通 internal prompt 并旋转 digest；review 证明旧 group wire 丢失 cardinality/binding rule 后，按既定条件提升至 manifest v4 并同步 prompt version。
- Task 5：补齐 slot projection hash-seed、registration atomicity、required/group matrix、精确 parity path、custom/falsey registry、stale alias、confirmation/visibility 与 no-mutation 回归门。
- Task 6：canonical docs 已同步；明确关闭 ownership/parity design debt 而非证明旧 runtime defect，未修改 CLI/MCP execution surface、schema、依赖、pending/confirm/commit 生命周期或 P0 权威边界。
- Final verification：最终 clean diff 上 focused `308 passed, 470 subtests passed`；adjacent `192 passed, 9232 subtests passed`；两套 Campaign validate/test 均 `OK`；Markdown links `191 files`、全仓 `py_compile`、full Ruff、`git diff --check` 均通过；repository full suite `1040 passed, 10325 subtests passed`。

### File List

- `_bmad-output/implementation-artifacts/6-3-resolved-slot-contract-projection-and-parity.md`
- `_bmad-output/implementation-artifacts/6-3-resolved-slot-contract-projection-and-parity.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/component-inventory.md`
- `docs/mcp-contracts.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/actions/base.py`
- `rpg_engine/actions/combat.py`
- `rpg_engine/actions/craft.py`
- `rpg_engine/actions/explore.py`
- `rpg_engine/actions/gather.py`
- `rpg_engine/actions/__init__.py`
- `rpg_engine/actions/random_table.py`
- `rpg_engine/actions/rest.py`
- `rpg_engine/actions/routine.py`
- `rpg_engine/actions/social.py`
- `rpg_engine/actions/slot_contract.py`
- `rpg_engine/actions/travel.py`
- `rpg_engine/ai_intent/slot_contract.py`
- `rpg_engine/ai_intent/arbiter.py`
- `rpg_engine/ai_intent/binder.py`
- `rpg_engine/ai_intent/normalization.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/cli.py`
- `rpg_engine/intent_manifest.py`
- `rpg_engine/preflight_cache.py`
- `rpg_engine/runtime.py`
- `tests/test_intent_manifest.py`
- `tests/test_action_slot_contract.py`
- `tests/test_ai_intent.py`
- `tests/test_preflight_cache.py`
- `tests/test_runtime.py`

### Review Findings

#### Round 1

- [x] [Review][Patch] Manifest 与 internal prompt 必须发布 requirement-group 的 `cardinality` / `binding_rule`，相关语义变化必须旋转 digest 并按 public wire 变化提升 schema/prompt version [`rpg_engine/intent_manifest.py:136`]
- [x] [Review][Patch] Binder 必须统一拒绝所有 `ai_fillable=false` 的 AI supplied slot，而非只处理 confirmation-only slot [`rpg_engine/ai_intent/binder.py:91`]
- [x] [Review][Patch] Registry registration 必须重新验证 resolved contract 的所有 leaf invariant，并保持失败原子性 [`rpg_engine/actions/slot_contract.py:251`]
- [x] [Review][Patch] 默认 resolver request validation 必须消费 canonical requirement groups，不能只检查 individual required slots [`rpg_engine/actions/base.py:237`]
- [x] [Review][Patch] Legacy binding compatibility adapter 不得额外发布旧表从未包含的 `user_text` [`rpg_engine/ai_intent/slot_contract.py:31`]
- [x] [Review][Patch] `ENTITY_SLOT_TYPES` compatibility constant 必须保留旧 binding-value 语义 [`rpg_engine/ai_intent/slot_contract.py:19`]
- [x] [Review][Patch] Required/group presence 判定必须保持原有 falsey 值视为缺失的行为 [`rpg_engine/actions/slot_contract.py:422`]
- [x] [Review][Patch] Parity gate 必须精确检查 missing/extra/duplicate slots、全部 slot fields、requirement groups 与 internal prompt 投影 [`tests/test_action_slot_contract.py:54`]
- [x] [Review][Patch] 补齐 archived、player/GM visibility 与 facts/turns/events/no-write characterization，避免空库 smoke test 冒充安全回归门 [`tests/test_ai_intent.py:842`]

#### Round 2

- [x] [Review][Patch] Normalized `.option_specs` 的 JSON container default 必须保持只读，不能与 digest/manifest 分叉 [`rpg_engine/actions/slot_contract.py:84`]
- [x] [Review][Patch] Registry registration 必须验证 `.option_specs` / `.required_options` / `.requirement_groups` compatibility mirrors 与 canonical contract 一致 [`rpg_engine/actions/base.py:344`]
- [x] [Review][Patch] `user_text` 必须 fail-closed 为 source-only、非 AI-fillable、非 confirmation slot [`rpg_engine/actions/slot_contract.py:324`]
- [x] [Review][Patch] Default resolution 遇到 canonical group error 必须返回 blocked 并保留错误证据 [`rpg_engine/actions/base.py:210`]
- [x] [Review][Patch] Confirmation-required slot 不得声明 non-null default 来静默满足直接玩家确认 [`rpg_engine/actions/slot_contract.py:331`]
- [x] [Review][Patch] Legacy required adapter 必须忽略 `required=false` 的 optional requirement group [`rpg_engine/ai_intent/slot_contract.py:47`]
- [x] [Review][Patch] Manifest digest gate 必须同时覆盖 `binding_rule` 与 `cardinality` 变化 [`tests/test_intent_manifest.py:370`]
- [x] [Review][Patch] External contract rolling-skew gate 必须直接覆盖上一版 manifest v3 [`tests/test_ai_intent.py:437`]
- [x] [Review][Patch] Canonical component inventory 必须同步当前 Manifest v4 [`docs/component-inventory.md:33`]

#### Round 3

- [x] [Review][Patch] Low-level preview CLI 不得把 canonical required metadata 提前变成 argparse gate，必须保留 palette/custom resolver 分类 [`rpg_engine/cli.py:102`]
- [x] [Review][Patch] Registry deep validation 必须拒绝 value-equal 但 mutable 的 canonical default 伪造 [`rpg_engine/actions/slot_contract.py:285`]
- [x] [Review][Patch] Registry compatibility mirror 必须拒绝 value-equal 但非 canonical identity 的 option default [`rpg_engine/actions/base.py:354`]
- [x] [Review][Patch] `user_text` 必须是保留 source-only 名称，其他 slot 不得把它声明为 alias [`rpg_engine/actions/slot_contract.py:217`]
- [x] [Review][Patch] Preflight identity 必须纳入 active slot projection digest，slot metadata 变化不得复用 stale internal review [`rpg_engine/preflight_cache.py:689`]
- [x] [Review][Patch] Required confirmation-only slot 缺失时 Binder 必须请求直接玩家确认而非报告普通 AI missing input [`rpg_engine/ai_intent/binder.py:115`]
- [x] [Review][Patch] Manifest v4 AI Client Prompt 必须明确定义 cardinality 与 binding_rule 的可执行语义 [`docs/prompts/ai-client-prompt.md:20`]

#### Round 4

- [x] [Review][Patch] Registry compatibility mirror 必须逐字段 exact-type 比较，不能让 `True == 1` 绕过 fail-closed [`rpg_engine/actions/base.py:365`]
- [x] [Review][Patch] Frozen JSON object default 必须拥有独立不可变存储，不能接受包装外部 mutable dict 的 mapping proxy [`rpg_engine/actions/slot_contract.py:481`]
- [x] [Review][Patch] Required group 全由 confirmation-only slots 组成时 Binder 必须请求直接玩家确认 [`rpg_engine/ai_intent/binder.py:118`]
- [x] [Review][Patch] Preflight low-level create/consume identity 必须强制非空 action slot digest，遗漏时 fail closed [`rpg_engine/preflight_cache.py:700`]
- [x] [Review][Patch] Canonical architecture/intent/testing docs 必须同步 preflight taxonomy + slot projection digest identity [`docs/ai-intent-chain.md:351`]

#### Round 5

- [x] [Review][Patch] Owned frozen JSON object 不得继承 mutable `dict`，避免调用 base mutator 后让 canonical projection/digest 漂移 [`rpg_engine/actions/slot_contract.py:31`]
- [x] [Review][Patch] 全由 confirmation-only slots 组成的 required group 不得被 `source_user_text_fallback` 静默满足，仍须请求 direct player confirmation [`rpg_engine/ai_intent/binder.py:135`]
- [x] [Review][Patch] Slot description/default 中的未配对 Unicode surrogate 必须在 contract 构造时 fail closed，不能延迟到 UTF-8 digest 阶段崩溃 [`rpg_engine/actions/slot_contract.py:462`]

#### Round 6

- [x] [Review][Patch] Slot registry projection `version` 必须执行 UTF-8 fail-closed validation，不能在 digest 阶段抛裸 `UnicodeEncodeError` [`rpg_engine/actions/slot_contract.py:278`]
- [x] [Review][Patch] Requirement group 不得把保留 source-only `user_text` 声明为 member；source fallback 只能由显式 `binding_rule` 表达 [`rpg_engine/actions/slot_contract.py:423`]
- [x] [Review][Patch] 已规范化的 immutable object default 必须能通过公开只读 `.option_specs` 安全复用到另一个合法 constructor，并产生独立 owned copy [`rpg_engine/actions/slot_contract.py:479`]

#### Round 7

- [x] [Review][Patch] Registry deep validation 必须拒绝内部 items 被伪造成乱序键或重复键的 frozen JSON object，保持 canonical object 与 wire/digest 一致 [`rpg_engine/actions/slot_contract.py:525`]
- [x] [Review][Patch] 超深 JSON default 的 `RecursionError` 必须转换为带 slot path 的受控 deterministic JSON-safe `ValueError` [`rpg_engine/actions/slot_contract.py:486`]

#### Round 8

- [x] [Review][Patch] Frozen/default validation 必须对合法深层 round-trip 与 malformed cycle 都采用 depth/cycle-safe 路径，不能在 `_is_frozen_json()` / thaw 阶段抛裸递归异常 [`rpg_engine/actions/slot_contract.py:505`]
- [x] [Review][Patch] Registry deep validation 必须对 `slot_contract.action` 执行 exact-type/action-name 重验，拒绝 value-equal 的 `str` subclass [`rpg_engine/actions/slot_contract.py:306`]
- [x] [Review][Patch] Binder 直接入口必须拒绝 canonical slot 与 alias 同时出现，不能保留顺序相关 last-write-wins [`rpg_engine/ai_intent/binder.py:89`]
- [x] [Review][Patch] Canonical slot/alias identifier 必须与既有 candidate ingress 的 60 字符边界一致，避免发布永远无法绑定的名称 [`rpg_engine/actions/slot_contract.py:485`]
- [x] [Review][Patch] Canonical contract 的 AI-fillable slot 数必须与既有 bounded candidate 的 24 项边界一致，避免合法 manifest 无法由 ingress 表达 [`rpg_engine/actions/slot_contract.py:251`]

#### Round 9

- [x] [Review][Patch] Frozen JSON thaw/projection 必须使用迭代路径；超出当前运行时 nesting limit 的 registry rebuild 必须以带 action/slot path 的合同错误原子拒绝 [`rpg_engine/actions/slot_contract.py:548`]
- [x] [Review][Patch] JSON object default 必须在序列化前验证所有 key 为 exact `str`，不得让 JSON round-trip 静默字符串化或碰撞非字符串键 [`rpg_engine/actions/slot_contract.py:587`]
- [x] [Review][Patch] Candidate slot key 清理后发生重名时 normalization 必须保留冲突证据，让 Binder fail closed，不能在前置 dict 写入中 last-write-wins [`rpg_engine/ai_intent/normalization.py:140`]

#### Round 10

- [x] [Review][Patch] Slot registry projection 必须先逐 entry 验证 exact pair 与 action name，再按已验证字符串排序，避免 mixed invalid key 提前抛裸 `TypeError` [`rpg_engine/actions/slot_contract.py:296`]

#### Round 11

- [x] [Review][Patch] Registry `register()` 必须在哈希 `spec.name`、membership 与 prospective dict 构造前，以未哈希 entry pair 完成 canonical exact validation [`rpg_engine/actions/base.py:366`]

#### Round 12

- [x] [Review][Patch] Prospective registry validation 必须逐项重验已注册 `item.name` 为 exact `str` 且等于 registry key，拒绝 shallow-tampered name 污染新增注册 [`rpg_engine/actions/base.py:373`]

#### Round 13

- [x] [Review][Patch] Story File List 必须补列 Round 9 实际修改的 candidate slot normalization 文件，保持 BMAD artifact 与 clean diff 一致 [`rpg_engine/ai_intent/normalization.py:136`]

#### Round 14

- 三路 fresh review（Blind Hunter、Edge Case Hunter、Acceptance Auditor）均 clean；无 `[Review][Patch]`、`[Review][Decision]` 或 `[Review][Defer]`，File List 与 37 个实际 diff 文件双向一致。

## Change Log

- 2026-07-14：实现 Story 6.3 resolver-owned resolved slot contract、九个 builtin metadata 迁移、binder/manifest/prompt 同源投影、legacy 只读 adapter、parity/安全回归门与 canonical docs；状态转为 review。
- 2026-07-14：首轮三路 code review 去重后自动应用 9 项 patch；manifest/prompt 升至 v4、补齐 group 语义投影、registry/binder/request-contract fail-closed 行为与精确 parity/visibility/no-write gates；Story focused 为 `307 passed, 459 subtests passed`，继续 fresh review 收敛。
- 2026-07-14：第二轮三路 code review 去重、复现并按 AC 驳回 custom-hook 强制合并等噪声后，自动应用 9 项 patch；补齐 read-only default、compatibility mirror、source-only/confirmation/default-resolution fail-closed 与 v4 rolling-skew/docs gates；Story focused 为 `307 passed, 461 subtests passed`。
- 2026-07-14：第三轮三路 code review 自动应用 7 项 patch；恢复 low-level CLI 由 Kernel 分类 required/palette、强化 mutable-default/user_text/required-confirmation 边界，并把 slot digest 纳入 preflight identity；更新测试夹具后 Story focused 为 `308 passed, 462 subtests passed`。
- 2026-07-14：第四轮三路 code review 自动应用 5 项 patch；compatibility mirror 改为 exact-type、JSON object default 改为 owned immutable storage、confirmation-only group 与 preflight slot digest fail-closed/documentation gates 完成；Story focused 为 `308 passed, 462 subtests passed`。
- 2026-07-14：第五轮三路 code review 去重、复现并驳回既有兼容语义/无规划证据候选后，自动应用 3 项 patch；消除 `dict` base mutator 绕过、confirmation source fallback 绕过与 surrogate 延迟崩溃；Story focused 为 `308 passed, 464 subtests passed`，累计自动应用 33 项有效 patch。
- 2026-07-14：第六轮三路 code review 自动应用 3 项 patch；补齐 projection version UTF-8 validation、禁止 `user_text` group member 绕过显式 fallback，并恢复 canonical immutable default 的 constructor round-trip；Story focused 为 `308 passed, 464 subtests passed`，累计自动应用 36 项有效 patch。
- 2026-07-14：第七轮三路 code review 自动应用 2 项 patch；registry 现会重验 frozen object 的 exact canonical items，超深 JSON default 以带 path 的合同错误 fail closed；Story focused 为 `308 passed, 465 subtests passed`，累计自动应用 38 项有效 patch。
- 2026-07-14：第八轮三路 code review 自动应用 5 项 patch；统一 deep/cycle-safe canonical JSON 路径、补齐 action exact-type、Binder duplicate fail-close，并让 slot name/count 与既有 60/24 candidate ingress 边界同源；Story focused 为 `308 passed, 469 subtests passed`，累计自动应用 43 项有效 patch。
- 2026-07-14：第九轮三路 code review 自动应用 3 项 patch；deep thaw 改为迭代、原始 JSON object key 先做 exact-type validation，并保留 candidate key 清理碰撞供 Binder 拒绝；Story focused 为 `308 passed, 470 subtests passed`，累计自动应用 46 项有效 patch。
- 2026-07-14：第十轮三路 code review 自动应用 1 项 patch；registry projection 改为 entry exact validation-before-sort，mixed malformed action name 以带 path 的合同错误原子拒绝；Story focused 为 `308 passed, 470 subtests passed`，累计自动应用 47 项有效 patch。
- 2026-07-14：第十一轮三路 code review 自动应用 1 项 patch；registry 在任何 name hash/dict 操作前先执行单 entry canonical projection validation，unhashable/non-exact name 受控且失败原子；Story focused 为 `308 passed, 470 subtests passed`，累计自动应用 48 项有效 patch。
- 2026-07-14：第十二轮三路 code review 自动应用 1 项 patch；prospective validation 逐项校验已注册 resolver name/key mirror，shallow name tamper 不再污染新增注册；Story focused 为 `308 passed, 470 subtests passed`，累计自动应用 49 项有效 patch。
- 2026-07-14：第十三轮三路 code review 的行为/AC 审计 clean；自动应用 1 项 artifact patch，补齐实际修改的 normalization File List，累计自动应用 50 项有效 patch。
- 2026-07-14：第十四轮三路 fresh code review 全部 clean；AC 1–4、Tasks 1–6、artifact/diff、权威与范围边界均无剩余 finding，进入最终 required gates。
- 2026-07-14：最终 required gates 全部通过；Story 与 sprint 状态同步为 done，Epic 6 因 6.4–6.8 仍为 backlog 而保持 in-progress。

## BMAD Provenance

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`；指定从 `sprint-status.yaml` 选择 Epic 6 下一个 backlog story，并授权持续 review/patch/verification 收敛、commit 与 push。
- Catalog route：完整读取 `.agents/skills/bmad-help/SKILL.md`；其 resolver 无 `customize.toml`，按 fallback 加载 `_bmad/_config/bmad-help.csv`、`skill-manifest.csv`、Core/BMM config、project context、governance与 sprint artifact；路由为 `[CS] bmad-create-story:create` → `[VS] bmad-create-story:validate` → `[DS] bmad-dev-story` → `[CR] bmad-code-review`。
- `[CS]` skill：完整读取 `.agents/skills/bmad-create-story/SKILL.md`；resolver 成功，prepend/append/on_complete 为空，persistent fact 为 `file:{project-root}/**/project-context.md`；加载 `_bmad/bmm/config.yaml`、`docs/project-context.md` 后按 embedded Steps 1→6 执行，并完整读取 `discover-inputs.md`、`template.md`、`checklist.md`。
- Create Story source context：完整读取 sprint status、epics、PRD、两份 architecture spine、Correct Course proposal、Story 6.2、intent-chain investigation、canonical project/architecture/component/intent/MCP/prompt/testing docs、相关源码/测试与 recent git history；无 UX artifact，无需外部技术版本研究。
- `[DS]` skill：完整读取 `.agents/skills/bmad-dev-story/SKILL.md`；resolver 成功，prepend/append/on_complete 为空，加载 persistent project context 与 BMM config 后按 embedded Steps 1→10 执行 red-green-refactor、逐任务 full-suite、DoD 与 review handoff。
