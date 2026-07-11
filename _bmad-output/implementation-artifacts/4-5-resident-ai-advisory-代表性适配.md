---
baseline_commit: 4ea796bd9bb5612d44a80ea89fc849b58ee88357
---

# Story 4.5：Resident AI Advisory 代表性适配

Status: done

## Story

作为引擎作者，
我希望先把少量代表性 AI/helper 输出接入 Resident AI Advisory Envelope，
从而验证 envelope 可以复用现有实现，而不需要一次性重写所有 helper 模块。

## 验收标准

1. **Internal Intent Review 产生独立、非权威的 `intent_recognition` companion advisory**

   **Given** `AIIntentRouter` 已取得成功且 exact advisory/no-write 的 `internal_intent_review` helper result，并由 Kernel binder/arbiter 产生带 canonical `entity_bindings` 的 decision
   **When** route result 被组装
   **Then** 新 adapter 仅从 helper 的稳定枚举、Kernel-bound target ids 与安全 canonical metadata 构造 `ResidentAIAdvisory`
   **And** advisory 固定为 `advisory_type=intent_recognition`、`source_assistant=internal_intent_review`、`proposed_next_workflow=none`，confidence 按 `high/medium/low -> 0.9/0.6/0.3` 显式映射，freshness 为 `unknown/null/[]`，visibility mode 与 binder view 一致
   **And** `target_ids` 只来自 `decision.bound.entity_bindings.values()` 的 canonical access-contract references，并按首次出现顺序去重；prefix mapping 固定为 `rel -> relationship`、`clock -> progress`、`rule -> rule`、`world/setting -> world_setting`，其余允许的 gameplay prefix -> entity；不能从 player text、target labels、slots、reason、disagreements、provider/model/session/preflight 或 raw audit 推断事实引用
   **And** 该 envelope 是 internal helper 生成的 route-level companion：`source_assistant` 表示 producer，targets 表示最终 Kernel-selected decision binding，不表示 helper 独立确认这些实体；只有 successful exact helper 与最终 `decision.bound` 同时存在时才生成
   **And** advisory 只作为 `AIIntentRouteResult` 的 optional companion field；它不得进入 arbiter、binder、resolver 或 route selection 输入，不得改变 mode matrix、fallback、guards、decision、selected outcome、preview、pending、confirm、validation 或 commit。

2. **State Audit 对合法 clock targets 产生 maintenance-only `progress_management` companion advisory**

   **Given** validation pipeline 已执行 state audit，delta schema stage 未 blocked，且 delta 的 `tick_clocks[*].id` 提供至少一个 canonical clock id
   **When** maintenance-oriented profile（`maintenance_commit`、`admin_or_legacy_save_turn` 或 `import_or_migration`）组装 state-audit stage artifacts
   **Then** 新 adapter 可产生 `advisory_type=progress_management`、`source_assistant=state_audit`、`visibility_mode=maintenance`、`confidence=0.5`、freshness `unknown/null/[]`、`proposed_next_workflow=none` 的 canonical envelope
   **And** target/evidence 只包含稳定去重 clock ids 与 `kind=progress` references；不得复制 findings、warnings、missing changes、raw delta、provider audit、prompt、proposal internals 或 validation messages
   **And** companion maintenance dict 只能在成功适配时加入 state-audit artifacts；除 `maintenance_commit`、`admin_or_legacy_save_turn`、`import_or_migration` 外，`preview_only`、`player_turn_commit`、`response_acceptance`、未知 profile、invalid/empty clock targets、未执行 audit 或 blocked delta schema 均不得包含 maintenance advisory
   **And** `tick_clocks` 提取采用 all-or-none：任一 item/id 不是 exact built-in dict/string、不是 canonical `clock:` id 或超限时，整个 companion 省略，不得过滤坏项后为剩余项生成部分 advisory
   **And** advisory 的生成与存在不得改变 state-audit risk、block/warning/ok status、issues、validation result、proposal state 或 commit eligibility。

3. **两个 adapter 复用 Story 4.4 contract，并保持其余 helper 不迁移**

   **Given** representative adapter 被直接调用或由 owner path 调用
   **When** 输入可适配
   **Then** adapter 必须统一调用 `normalize_resident_ai_advisory()` 返回 `ResidentAIAdvisory`，不得新建 schema、validator、authority vocabulary 或把公开 dataclass constructor 当 validation token
   **And** exact source type、`advisory is True` 与 `no_direct_writes is True` 必须 fail closed；schema version、advisory type、source assistant、workflow 与 authority 不接受 caller override
   **And** provenance digest 只基于 bounded canonical targets 与安全枚举，不包含 user text、helper body、provider/model、session/message/preflight key、delta body、hidden token 或 caller-controlled error text；authority 继续固定为 advisory-only/no-direct-writes，所有 write/approve/confirm/hidden/trusted-delta/save/profile/validation/commit capabilities 为 false
   **And** adapters 为纯转换，不接收 SQLite connection、不写 Save/Campaign/registry/pending/preflight/proposal queue、不调用 provider、不执行 workflow；source helper objects 与 caller collections 不被修改或保留可变 alias；owner path 必须隔离 adapter 的 `TypeError`、`ValueError` 与意外异常，只省略 companion，且不得把异常文本/类型/输入写入 trace、issues、warnings 或 artifacts
   **And** semantic/context helper、Archivist、reflection、memory、entity maintenance、delta draft、response acceptance、turn assistant 与 plot progression 不被强制迁移；后续边界明确记录，Story 4.6 继续拥有 suggestion -> review artifact，Story 4.7 拥有 plot progression，Story 5.7 拥有 proposal queue lifecycle/apply/revert/report。

## 任务 / 子任务

- [x] Task 1：先补 RED adapter contract tests（AC: 1-3）
  - [x] 新增 `tests/test_resident_ai_advisory_adapters.py`，冻结两个 keyword-only 稳定 API：`adapt_internal_intent_review_advisory(result: AIHelperResult, *, bound_target_ids: tuple[str, ...], visibility_mode: str) -> ResidentAIAdvisory | None` 与 `adapt_state_audit_progress_advisory(result: StateAuditResult, *, clock_ids: tuple[str, ...]) -> ResidentAIAdvisory | None`。
  - [x] 精确断言两种 advisory type、全部 envelope fields、confidence/freshness/visibility/provenance 映射、schema version、workflow 与 11 个 authority flags。
  - [x] 冻结返回/拒绝矩阵：normal unavailable/off/timeout/failed、`parsed is None`、empty exact target tuple 返回 `None`；非 exact source type、wrong task、伪造 advisory/no-write flags、非 exact tuple/string/bool、非法 confidence/visibility/ref/oversize 输入抛脱敏 `ValueError`。Intent `parsed` 必须为 exact dict 且只读取 exact `confidence=high|medium|low`，不得遍历或规范化其余 helper body。
  - [x] 用 canary 证明 source user text、slots、reason、disagreements、findings、warnings、raw delta、provider/model/audit/raw prompt/private reasoning 不进入 maintenance/player serialization、exception 或 provenance digest。
  - [x] 证明 adapter 对 source objects 与 caller tuples 无 mutation/alias；不调用 `run_ai_helper_json`、SQLite、proposal/validation/commit API。
  - [x] 精确断言 canonical digest 稳定性：同一 canonical input 同 digest；first-seen target 顺序或允许枚举变化按 contract 改变 digest；敏感 canary 的变化不影响 digest。

- [x] Task 2：实现共享 representative adapters（AC: 1-3）
  - [x] 新增 `rpg_engine/ai/advisory_adapters.py`；只依赖 `ai.advisory`、`AIHelperResult` 与 `StateAuditResult`，不得从 `ai` 反向 import `ai_intent`，避免循环依赖。
  - [x] Intent adapter 只接受 exact successful `AIHelperResult(task=internal_intent_review)` 与 exact tuple `bound_target_ids`；按首次出现顺序稳定去重，prefix mapping 固定为 `rel:/clock:/rule:/world:/setting:` 对应 relationship/progress/rule/world_setting，其余允许 gameplay prefix 为 entity。
  - [x] State adapter 只接受 exact `StateAuditResult` 与 exact tuple `clock_ids`；只保留 `clock:` canonical ids，invalid input 不静默洗白，empty 合法输入返回 `None`。
  - [x] 冻结 provenance wire：Intent digest payload 精确为 `{"adapter":"internal_intent_review","confidence":<high|medium|low>,"targets":[...],"visibility_mode":<player|gm|maintenance>}`；State digest payload 精确为 `{"adapter":"state_audit_progress","targets":[...],"visibility_mode":"maintenance"}`。两者只含 exact built-in JSON scalars 与 first-seen targets，使用 `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`、UTF-8、SHA-256 lowercase hex；完整 IDs 分别为 `trace:intent-review:<hex>` / `candidate:intent-review:<hex>` 与 `trace:state-audit:<hex>` / `candidate:state-audit:<hex>`。
  - [x] 两个 adapter 最终都把全量 dict 交给 `normalize_resident_ai_advisory()`；caller 不得覆盖 authority/schema/type/source/workflow。
  - [x] 更新 `rpg_engine/ai/__init__.py` 只导出两个稳定 adapter API；保持 `AIHelperResult`、`InternalIntentReview`、`StateAuditResult`、Archivist/semantic/reflection 既有 shape 不变。

- [x] Task 3：接入 Internal Intent Review owner path（AC: 1, 3）
  - [x] 更新 `rpg_engine/ai_intent/router.py`：在 decide/bind/arbitrate 与 selected outcome 已完成后，使用 successful internal helper、最终 bound entity ids 与 exact view 生成 optional companion；adapter failure 必须只产生 `None`，不能 crash 或改变 route。
  - [x] `AIIntentRouteResult` 增加 default-`None` 的 typed `internal_advisory` 字段；不得把 maintenance dict、private helper payload 或 advisory 内容塞入公开 trace/decision trace。
  - [x] 新增/更新 focused tests，证明有 canonical bound ids 时生成 `intent_recognition`；无 bindings、helper unavailable、intent AI off 或 adapter rejection 时为 `None`，同时既有 decision/outcome/guards/mode/fallback 完全不变。
  - [x] preflight cache hit 仍只替代 live internal review；companion advisory 不改变 4.3 identity/TTL/single-use/CAS，也不把 cached provider/session/message metadata写入 provenance。
  - [x] 覆盖 external/internal agree、disagree、rule fallback、blocked 与 clarify：targets 始终只表达最终 Kernel-selected binding，source assistant 只表达 producer，不得把 helper attribution 解释为独立事实确认。
  - [x] monkeypatch adapter 分别抛带敏感 canary 的 `TypeError`、`ValueError`、unexpected exception；断言 route decision/selected outcome/guards/trace 与未启用 adapter 基线完全相同，且 canary 不出现。

- [x] Task 4：接入 State Audit maintenance owner path（AC: 2-3）
  - [x] 更新 `rpg_engine/validation_pipeline.py`：定义单一 `MAINTENANCE_ADVISORY_PROFILES`；只在 state audit 已执行、已存在且未 blocked 的 delta schema stage、profile 属于 allowlist 且 `tick_clocks` 提供全量合法 ids 时调用 adapter。
  - [x] 先把 clock ids 复制为独立 exact tuple并按首次出现顺序去重；任一 mixed invalid/oversize item 使整个 companion 省略。使用新建 artifacts dict 与 `resident_ai_advisory_to_maintenance_dict()` 加入 `advisory`，不得原地修改 audit `to_dict()`、`StateAuditResult` 或 caller artifacts。
  - [x] `preview_only`、`player_turn_commit`、`response_acceptance` 与未知 profile 的 stage artifacts / `ValidationReport.to_dict()` 永不包含 maintenance advisory，不新增 public renderer 或 CLI/MCP field。
  - [x] adapter 返回 `None` 或抛出 contract rejection 时，state audit 原 status/issues/audit artifact 保持原样；不得把 advisory failure 升级为 validation blocker、warning 或 commit authority。
  - [x] focused tests 覆盖 maintenance positive、player/response omission、blocked delta schema、empty/invalid clock ids、audit warning/blocking 与 deterministic/AI merge 路径；companion 不改变现有 `ValidationReport.state_audit` 或 `to_dict()` 旧字段语义。
  - [x] 覆盖 mixed valid/invalid、duplicate、all-or-none 与 adapter 三类异常；逐字段证明原 audit/status/issues/report ok/commit eligibility 与无 adapter 基线相同，异常 canary 不进入 issues/warnings/artifacts。

- [x] Task 5：同步 canonical docs 与明确未迁移 backlog（AC: 3）
  - [x] 更新 `docs/architecture.md`：记录 representative companion adapters、依赖方向、纯转换、owner-path 单向输出以及“不反哺 authority”。
  - [x] 更新 `docs/data-models.md`：记录 helper payload 与 envelope metadata 分离、两类 mapping、unknown freshness 与无新表/owner。
  - [x] 更新 `docs/component-inventory.md` 登记 `rpg_engine/ai/advisory_adapters.py`；更新 `docs/testing-and-quality-gates.md` 登记 adapter focused/adjacent/no-mutation/redaction gates。
  - [x] 明确后续清单：semantic/context summary、Archivist、reflection、memory、entity-maintenance/delta-draft/response/turn-assistant 保持未迁移；4.6/4.7/5.7 既有 owner 不变，不新建虚构 sprint story。
  - [x] `docs/ai-intent-chain.md`、CLI/MCP contracts 只有真实公开 contract 改变时才更新；本 Story 默认不改变 public trace/tool/schema。

- [x] Task 6：从最终 clean diff 运行全部 required gates（AC: 1-3）
  - [x] Story focused：new adapters、Resident advisory contract、AI intent route、validation/state audit owner path。
  - [x] Adjacent regression：AI helper、preflight、runtime、SaveManager、MCP/platform/surface、current-native visibility/write safety 与 validation pipeline；所有写测试使用 temporary Save。
  - [x] Campaign：两个 canonical examples 的 validate/test。
  - [x] Docs/static：Markdown links、changed Python `py_compile`、full Ruff、`git diff --check`。
  - [x] Repository full `pytest`；任何后续 review patch 都使受影响旧绿灯失效并必须重跑。

### Review Findings

- [x] [Review][Patch] Intent adapter 在比较前必须校验 exact built-in `task/status`，并使 malformed source 以脱敏 `ValueError` fail closed [`rpg_engine/ai/advisory_adapters.py:29`]
- [x] [Review][Patch] Maintenance profile allowlist 必须不可变，且 owner helper 必须拒绝 `str` 子类伪装的未知 profile [`rpg_engine/validation_pipeline.py:40`]
- [x] [Review][Patch] State owner 必须在隔离边界内快照 `tick_clocks`，每个 `id` 只读一次，避免并发变更导致 validation crash [`rpg_engine/validation_pipeline.py:526`]
- [x] [Review][Patch] Target item budget 必须对 first-seen 去重后的唯一 references 计数，重复项不得先耗尽 budget [`rpg_engine/ai/advisory_adapters.py:119`]
- [x] [Review][Patch] 补齐 Internal Intent owner 的 no-binding/unavailable/off/preflight/agree-disagree/fallback/blocked/clarify 不变性验收矩阵 [`tests/test_resident_ai_advisory_adapters.py:334`]
- [x] [Review][Patch] 补齐 State Audit owner 的 profile/empty-oversize/warning-blocking/merge/report/commit-eligibility 不变性验收矩阵 [`tests/test_resident_ai_advisory_adapters.py:427`]
- [x] [Review][Patch] State owner 只能信任唯一、exact、与当前 profile 一致且 status=ok 的 `delta_schema` stage [`rpg_engine/validation_pipeline.py:523`]
- [x] [Review][Patch] 在 unique-target budget 之外复用 Story 4.4 container budget 限制原始 reference 遍历和 owner 快照 [`rpg_engine/ai/advisory_adapters.py:125`]
- [x] [Review][Patch] Exact `ValidationStageResult` 仍必须对 `name/profile/status` 执行 exact built-in string 校验，阻断可重载相等伪装 [`rpg_engine/validation_pipeline.py:526`]
- [x] [Review][Patch] Intent parsed payload 必须在读取 confidence 前验证有界 exact string keys，并将 hostile lookup 收敛为脱敏 `ValueError` [`rpg_engine/ai/advisory_adapters.py:45`]
- [x] [Review][Patch] State owner 必须从 exact outer delta 和 exact-string-key clock items 提取 targets，阻断 mapping/key 伪装 [`rpg_engine/validation_pipeline.py:541`]
- [x] [Review][Patch] Intent owner 必须将 adapter 的非异常错误返回类型 fail closed 为 `None` [`rpg_engine/ai_intent/router.py:292`]
- [x] [Review][Patch] Exact mapping 提取也必须执行 Story 4.4 64-item container budget [`rpg_engine/validation_pipeline.py:560`]
- [x] [Review][Patch] Intent/State owners 必须重新 normalise 并校验各自固定 semantic envelope，阻断错误 surface/type/source/visibility [`rpg_engine/ai_intent/router.py:292`; `rpg_engine/validation_pipeline.py:552`]
- [x] [Review][Patch] Owner 必须用共享 projection matcher 验证 envelope 与本次 canonical targets/helper confidence/digest 完整一致 [`rpg_engine/ai_intent/router.py:297`; `rpg_engine/validation_pipeline.py:558`]
- [x] [Review][Patch] State owner 必须在 `run_state_audit()` 之前冻结已验证 clock-id tuple，消除 mutable delta TOCTOU [`rpg_engine/validation_pipeline.py:485`]
- [x] [Review][Patch] Delta-schema success 必须私有绑定 validated digest/clock tuple，state owner 前后校验 digest 并在 mutation 时省略 companion [`rpg_engine/validation_pipeline.py:318`; `rpg_engine/validation_pipeline.py:492`]
- [x] [Review][Patch] Validated-stage proof 必须由 owner-private token 铸造，并将 live exact clock tuple 与 stage tuple/digest 严格绑定 [`rpg_engine/validation_pipeline.py:56`; `rpg_engine/validation_pipeline.py:596`]
- [x] [Review][Patch] Delta digest 对不可序列化输入必须 fail closed，不得使 validation 抛异常 [`rpg_engine/validation_pipeline.py:251`; `rpg_engine/validation_pipeline.py:325`]
- [x] [Review][Patch] State adapter 必须只接收隔离 audit 副本，status/issues/artifact 从未被 adapter 接触的 snapshot 生成 [`rpg_engine/validation_pipeline.py:523`]
- [x] [Review][Patch] Delta digest+clock tuple 必须封装为单一 owner-minted frozen proof，阻断 `dataclasses.replace()` 独立伪造字段 [`rpg_engine/validation_pipeline.py:54`; `rpg_engine/validation_pipeline.py:607`]
- [x] [Review][Patch] State owner 在发出 companion 前必须用同一 `conn` all-or-none 确认所有 clock targets 仍 live [`rpg_engine/validation_pipeline.py:545`]
- [x] [Review][Patch] Commit digest 任一侧为 `None` 必须拒绝，不得以 `None == None` 通过绑定检查 [`rpg_engine/commit_service.py:102`]
- [x] [Review][Patch] Canonical delta digest 必须递归只接受 exact JSON built-ins，拒绝 key coercion、subclass 与重复编码 key [`rpg_engine/validation_pipeline.py:269`]
- [x] [Review][Patch] Schema proof 必须保存验证过的 canonical wire，并确认 deep snapshot 与原 delta 一致；audit 只消费该 wire 重建输入 [`rpg_engine/validation_pipeline.py:346`; `rpg_engine/validation_pipeline.py:648`]
- [x] [Review][Patch] Validated proof 必须绑定当前 connection 且单次消费，移除可直接调用的 module mint helper [`rpg_engine/validation_pipeline.py:57`; `rpg_engine/validation_pipeline.py:627`]
- [x] [Review][Patch] Live clock 复核必须 join canonical entity status 并 all-or-none 排除 archived targets [`rpg_engine/validation_pipeline.py:696`]
- [x] [Review][Patch] Validated proof 必须强绑定原始 connection 对象，不能使用释放后可复用的 `id(conn)` [`rpg_engine/validation_pipeline.py:63`]
- [x] [Review][Patch] Live clock 最终复核必须显式查询事实权威 `main.clocks/main.entities`，阻断 TEMP shadow table 绕过 [`rpg_engine/validation_pipeline.py:737`]
- [x] [Review][Patch] Archived lifecycle 必须复用项目 canonical label normalizer，不能使用 `lower(trim(...))` 的弱等价判断 [`rpg_engine/validation_pipeline.py:741`]
- [x] [Review][Patch] Canonical delta wire 必须把 UTF-8 可编码性纳入 fail-closed 边界，拒绝未配对 surrogate [`rpg_engine/validation_pipeline.py:263`]
- [x] [Review][Patch] State audit 对所有 delta 形状都必须使用 canonical 隔离副本，不能让 audit 在既有验证后修改 caller delta 与 report digest [`rpg_engine/validation_pipeline.py:564`]
- [x] [Review][Patch] Adapter 返回后、发布 artifact 前必须再次复核 authoritative clock liveness 与 snapshot 绑定 [`rpg_engine/validation_pipeline.py:595`]
- [x] [Review][Patch] 两个公开 adapter 必须把 target 中未配对 surrogate 的编码失败收敛为脱敏 `ValueError` [`rpg_engine/ai/advisory_adapters.py:170`]
- [x] [Review][Patch] Story 文件清单与开发记录必须包含 CommitService 条件改动及其 RED provenance [`rpg_engine/commit_service.py:102`; `tests/test_validation_pipeline.py:1827`]
- [x] [Review][Patch] 非 canonical delta 仍须以隔离深拷贝保留既有 State Audit risk/status/issues 语义，不能替换为 `{}` [`rpg_engine/validation_pipeline.py:570`]

## 开发说明

### 范围与 P0 边界

- 本 Story 只建立两个 bounded companion adapters 与两个窄 owner integration points；不得新增 resident coordinator、scheduler、worker、repository、storage lifecycle、SQLite table/migration、Campaign/Save schema、依赖或 public CLI/MCP/platform surface。
- Adapter/envelope 不是 fact、proposal、delta 或 authorization token。`AI proposes. Kernel verifies. Player confirms. Engine commits.` 不变；external/internal/resident AI 都不能取得 fact、hidden、approval、confirmation、validation 或 commit authority。
- Intent companion 必须在 routing decision 完成后单向生成；绝不能进入 candidate arbitration、binding、resolver 或 selection。State-audit companion 只能附着 maintenance artifacts；绝不能影响 audit risk/status/issues 或 validation/commit gate。
- 不接入/修改 `archivist.py`、`memory.py`、`reflection.py`、`delta_draft.py`、`proposal_queue.py`、`response_acceptance.py`、`turn_assistant.py`、Runtime/SaveManager/CommitService、CLI/MCP。Story 4.6/4.7/5.7 ownership 不得提前实现。
- `data/game.sqlite` 继续是事实权威；所有 player rendering 必须通过 Story 4.4 的 SQLite-aware player serializer。Adapter 的 `visibility_mode=player` 不是 hidden permission。

### 精确 mapping contract

| Adapter | advisory type | targets/evidence | confidence | freshness | visibility | source/workflow |
| --- | --- | --- | --- | --- | --- | --- |
| Internal Intent Review | `intent_recognition` | Kernel-bound canonical entity ids；prefix -> typed evidence | high/medium/low -> 0.9/0.6/0.3 | `unknown/null/[]` | exact binder view | `internal_intent_review` / `none` |
| State Audit Progress | `progress_management` | canonical `clock:` ids；`kind=progress` | fixed 0.5（risk 不是 confidence） | `unknown/null/[]` | maintenance | `state_audit` / `none` |

- Intent helper 不提供 canonical numeric as-of/event evidence；state audit 处理的是尚未 commit 的 delta，因此二者不得伪称 `current`。
- Digest 只证明 adapter metadata 的稳定关联，不证明事实、provider 身份或可信调用者；不得包含原始输出、prompt、正文、provider/model、session/message/preflight key 或 delta body。
- Adapter source flags 使用 exact bool，source class 使用 exact type；不可适配的正常状态返回 `None`，伪造/非法 contract input 以脱敏 `ValueError` fail closed。
- Intent player serialization 使用 temporary Save 的 Story 4.4 player serializer：hidden/archived/missing refs 被 omission，且 confidence/freshness/source/workflow/provenance 不公开；State advisory 只测试 maintenance serializer，并证明没有 player serializer/public renderer 调用路径。Canary 必须同时检查 envelope、maintenance dict、player dict、exceptions、route trace 与 validation issues。

### 文件结构要求

- **NEW**：`rpg_engine/ai/advisory_adapters.py`、`tests/test_resident_ai_advisory_adapters.py`。
- **UPDATE**：`rpg_engine/ai/__init__.py`、`rpg_engine/ai_intent/router.py`、`rpg_engine/validation_pipeline.py`、`tests/test_ai_intent.py`、`tests/test_validation_pipeline.py`、`docs/architecture.md`、`docs/data-models.md`、`docs/component-inventory.md`、`docs/testing-and-quality-gates.md`。
- **EXPECTED NO CHANGE**：`rpg_engine/ai/advisory.py` 与 schema（除非 RED 证明 4.4 contract defect）、helper/provider schemas、arbiter/binder/resolver policy、preflight cache、Archivist/memory/reflection/delta/proposal/response/turn modules、Runtime/SaveManager/commit、CLI/MCP/platform、migrations、Campaign/Save/formal registry。
- 条件文件只有在 RED 证据证明当前 contract 无法落地时才能最小修改；编辑前完整重读并在开发记录注明触发。不得把测试编排塞入 production API。

### 测试要求

建议 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_resident_ai_advisory_adapters.py \
  tests/test_resident_ai_advisory.py \
  tests/test_ai_intent.py \
  tests/test_validation_pipeline.py \
  tests/test_maintenance_tooling_coverage.py \
  -p no:cacheprovider
```

建议 adjacent regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ai_helper.py \
  tests/test_preflight_cache.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_mcp_adapter.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py \
  tests/test_platform_sidecar.py \
  tests/test_surface_inventory.py \
  tests/test_current_native_visibility.py \
  tests/test_current_native_write_safety.py \
  -p no:cacheprovider
```

### Previous Story 4.4 intelligence

- Story 4.4 在 commit `4ea796b` 建立 strict envelope、schema、maintenance/player serializers、bounded structural snapshot、authority-smuggling rejection、typed access-contract visibility 与 generic unavailable；本 Story 必须复用这些 API，不得建立平行 contract。
- 4.4 经 14 轮三路 fresh review、61 项 patch 收敛；主要教训是 hostile mutable inputs、traceback locals、SQLite TEMP/attached schema、hidden token collisions 与 public allowlist 都必须 defense-in-depth。
- 4.4 最终基线为 focused 70/8989、adjacent 368/458、full 879/9822；这些只是基线，不能复用为 4.5 完成绿灯。
- 当前 formal Save 已由外部游戏会话推进；current-native gates 必须复制冻结 temporary Campaign/Save roots，绝不能回滚或让测试写 formal source。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 4 / Story 4.5]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md` — Story 4.4 split 与 4.6/5.7 proposal boundary]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md` — FR-5、FR-6、FR-9、FR-12]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md` — advisory/authority contract families]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md` — execution/commit invariants]
- [Source: `docs/project-context.md` — facts/access/temporary Save/BMAD governance]
- [Source: `_bmad-output/implementation-artifacts/4-4-resident-ai-advisory-envelope-contract.md` — contract/review learnings]
- [Source: `rpg_engine/ai/advisory.py`、`rpg_engine/ai/provider.py`、`rpg_engine/ai/state_audit.py`]
- [Source: `rpg_engine/ai_intent/router.py`、`rpg_engine/validation_pipeline.py`]

## 开发代理记录

### 使用的代理模型

GPT-5 Codex

### 调试日志引用

- Create Story research：三路只读 subagents 覆盖 helper/call-chain、architecture/boundaries、tests/previous Story；共同确认“两个 bounded companion adapters + 窄 owner integration、无迁移大爆炸”。
- BMAD Create Story：完整读取 `.agents/skills/bmad-create-story/SKILL.md`、discover/template/checklist；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空。
- Validate Story：fresh subagent 按完整 checklist 提出 3 Critical、4 Enhancement、2 Optimization；9 项无歧义改进全部应用，Decision-needed=0。
- RED：`tests/test_resident_ai_advisory_adapters.py` 首次 collection 因 `rpg_engine.ai.advisory_adapters` 不存在而失败。
- GREEN：adapter unit/owner integration 11 passed / 21 subtests；adapter + 4.4 contract + AI intent + validation 120 passed / 164 subtests。
- Dev Story focused：219 passed / 175 subtests；Markdown links 181 files、full Ruff、changed py_compile 与 `git diff --check` 通过。
- Dev Story adjacent：329 passed / 9304 subtests（冻结 temporary current-native roots）。
- Dev Story Campaign：两个 canonical examples 的 validate/test 四命令全部 OK。
- Dev Story repository full：890 passed / 9843 subtests。
- Review RED（条件文件）：canonical digest 对非法值 fail closed 为 `None` 后，CommitService 原 `None == None` 比较可错误接受未绑定 delta；据此最小修改 `commit_service.py` 并在 `tests/test_validation_pipeline.py` 固定拒绝行为，未改变合法 commit eligibility。
- Code Review：16 轮三路 fresh Blind Hunter / Edge Case Hunter / Acceptance Auditor 持续收敛；累计自动应用 36 项范围内无歧义 patch，Decision=0、Defer=0、dismiss=5；被平台过滤的 reviewer 输出均由 fresh retry 补齐，最终第 16 轮三路 clean。
- Final focused：236 passed / 222 subtests；Final adjacent：265 passed / 9261 subtests（冻结 temporary current-native roots）。
- Final Campaign：`v1_minimal_adventure` 与 `small_cn_campaign` 的 validate/test 四命令全部 OK。
- Final docs/static：Markdown links 181 files、changed Python `py_compile`、full Ruff、`git diff --check` 全部通过。
- Final repository full：907 passed / 9890 subtests。
- BMAD Dev Story：完整读取 `.agents/skills/bmad-dev-story/SKILL.md`；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空；按 fresh start→in-progress→RED/GREEN/refactor 顺序执行。
- BMAD Code Review：完整读取 `.agents/skills/bmad-code-review/SKILL.md` 与每轮 step files；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，`workflow.on_complete` 为空。

### 实施计划

- 先用 adapter RED tests 冻结字段映射、payload exclusion、no-authority 与 no-mutation。
- 实现纯 adapter module，再分别接到已完成 routing decision 与 maintenance state-audit artifacts 的单向输出点。
- 同步 canonical docs，记录未迁移 helper backlog，从最终 clean diff 运行全部 required gates。

### 完成说明列表

- 已完成终极上下文引擎分析并生成实现指南。
- 已实现 Internal Intent Review 与 State Audit Progress 两个 strict companion adapters，统一复用 Story 4.4 normalizer、固定 authority 与 canonical provenance digest。
- 已把 intent companion 单向接到最终 route result，把 progress companion 限制在 maintenance state-audit artifacts；adapter 失败不改变主 route/validation 结果。
- 已同步 architecture、data model、component inventory 与 testing docs，并记录未迁移 helper/后续 Story ownership。
- 全部 tasks、AC、DoD、三路 clean review 与最终 required gates 均满足；Story 状态转为 done。

### 文件列表

- `_bmad-output/implementation-artifacts/4-5-resident-ai-advisory-代表性适配.md`
- `_bmad-output/implementation-artifacts/4-5-resident-ai-advisory-代表性适配.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/ai/__init__.py`
- `rpg_engine/ai/advisory_adapters.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/commit_service.py`
- `rpg_engine/validation_pipeline.py`
- `tests/test_resident_ai_advisory_adapters.py`
- `tests/test_validation_pipeline.py`

## 变更日志

- 2026-07-12：Create Story 生成完整实现上下文，状态设为 ready-for-dev。
- 2026-07-12：Validate Story 自动应用 9 项改进，Decision-needed 为 0。
- 2026-07-12：实现两个 representative companion adapters、owner integrations、focused tests 与 canonical docs。
- 2026-07-12：Dev Story required gates 全绿，Story 转为 review。
- 2026-07-12：16 轮三路 review 自动收敛 36 项 patch；最终三路 clean、全部 required gates 全绿，Story 转为 done。

## BMAD 来源记录

- 用户触发：完成并推送 Story 4-4 后继续 Story 4-5；父流程为 `bmad-story-cycle-auto with review subagents and apply every patch`。
- Catalog 路由：`[CS] Create Story`（`bmad-create-story:create`）后接 `[VS] Validate Story`（`bmad-create-story:validate`）。
- Review 路由：`[CR] Code Review`（`bmad-code-review`），每轮使用 fresh Blind Hunter、Edge Case Hunter、Acceptance Auditor；最终三路 clean。
- Customization：resolver 成功，`activation_steps_prepend=[]`、`activation_steps_append=[]`、`persistent_facts=[file:{project-root}/**/project-context.md]`、`on_complete=""`。
- 已加载 config/facts：`_bmad/bmm/config.yaml`、`_bmad/core/config.yaml`、`docs/project-context.md`、`docs/governance/bmad-workflow.md`；通信与 artifact 均为中文。
- Input discovery：Epic 4/Story 4.5、主 PRD、两份 Architecture Spine、Correct Course、previous Story 4.4、canonical docs 与现有 helper/intent/validation code；无 UX artifact。
- Web research：未执行。本 Story 不新增/升级 library、framework、external API 或依赖，只复用仓库锁定 Python/stdlib/jsonschema/pytest/Ruff。
