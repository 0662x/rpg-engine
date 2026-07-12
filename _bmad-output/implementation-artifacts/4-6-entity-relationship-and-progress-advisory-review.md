---
baseline_commit: d1c5784bd29811af7d5edf3d2827383b578b9abd
---

# Story 4.6：Entity、Relationship 与 Progress Advisory Review

Status: done

## Story

作为主持者，
我希望 AI 建议的实体、关系和进度变更进入可审查 workflow，
从而让有用的维护辅助只有在验证或批准之后才可能成为事实。

## 验收标准

1. **AI suggestion 进入显式、非权威 review artifact**

   **Given** resident AI 建议创建或更新 entity、relationship、alias、memory summary、progress track 或 clock tick
   **When** 该建议被接受进入 review
   **Then** 它成为 proposal、content delta draft、maintenance delta 或其他显式 review artifact
   **And** 原始 AI suggestion 继续保持 non-authoritative
   **And** 本 Story 不拥有 proposal queue state transitions、apply、revert 或 batch review。

2. **Gameplay fact application 仍由既有 validation/write gate 控制**

   **Given** reviewed suggestion 指向 gameplay facts
   **When** 请求 application
   **Then** 它必须通过适当 validation profile、reference checks、visibility checks 以及 commit 或 maintenance gate
   **And** proposal approval 本身不等同于普通 gameplay commit
   **And** intake 只生成 preflight evidence，不执行 application：entity/relationship content candidate 必须记录并通过 `validate_content_delta()` 的当前 preflight，后续 `apply_content_delta()` 仍须重新验证；clock tick 必须通过 `validate_delta_progress_references()`，后续只能由 caller 已获授权的 confirmed `TurnProposal -> run_validation_pipeline() -> commit` 路径，或既有 maintenance validation/write path 重新验证
   **And** artifact 不得选择或提升 validation profile；alias、memory summary 与 progress definition 在没有已命名且可验证的现有 application owner 时固定 `application_eligible=false`，不得以 generic proposal approval、`save_patch` 或 memory rebuild 猜测 application 权威。

3. **非 current suggestion 不得作为事实召回**

   **Given** suggestion 被 rejected、stale、superseded 或与 current facts 冲突
   **When** reports 或 context recall 检查它
   **Then** 不得把它当成 current fact
   **And** rollback 或 supersession evidence 对 maintenance user 可见。

## 任务 / 子任务

- [x] Task 1：先用 RED tests 冻结 suggestion → review artifact contract（AC: 1-3）
  - [x] 新增 `tests/test_resident_ai_advisory_review.py`，冻结 keyword-only、纯 intake API；输入必须由 canonical `ResidentAIAdvisory` 与独立、bounded、明确 kind 的 candidate draft 组成，输出为 immutable / JSON-safe `AdvisoryReviewArtifact` 或脱敏 fail-closed rejection。Artifact 内部只保存 exact frozen nested records 与 tuples，不保存 caller dict/list；所有输入先 bounded deep snapshot，serializer 每次返回全新的 exact JSON built-ins。修改 source candidate、serializer 返回值或 caller collection 均不得改变 artifact、digest 或后续 serialization。
  - [x] 覆盖六个 suggestion family，并对 entity/relationship 的 create 与 update 分支分别测试：entity、relationship、alias、memory summary、progress track review 与 clock tick；逐类断言 artifact kind、target bindings、`required_gate`、`next_owner`、`application_eligible`、reference/visibility requirements、source/freshness/supersession/rollback evidence与固定 no-authority state，以及错误/过期输入的确定性结果。
  - [x] 证明 advisory envelope 不是 mutation payload：只含 targets/evidence 的 envelope 不能凭空生成 delta；raw helper/provider output、private reasoning、prompt、audit、session/preflight、hidden token、caller-controlled error text 与未经 allowlist 的 proposal internals不得进入 artifact。
  - [x] 覆盖 exact built-in types、有界 deep snapshot、cycle/oversize、scalar/container subclass、mixed valid/invalid、并发 mutation/TOCTOU 与 source collection alias；非法输入必须脱敏 fail closed，且不得修改 source advisory、candidate 或 caller connection transaction ownership。

- [x] Task 2：实现严格、只读的 Advisory Review intake contract（AC: 1-3）
  - [x] 新增 `rpg_engine/ai/advisory_review.py`；定义 frozen `AdvisoryReviewArtifact`、固定 artifact/schema/authority vocabulary、maintenance-safe serializer 与单一 intake API，最终必须重新调用 `normalize_resident_ai_advisory()`，不得把公开 dataclass constructor 当 validation token。Artifact 内部只允许 exact frozen nested records/tuples，serializer 必须重建全新 exact JSON built-ins。
  - [x] 将 suggestion kind 限制在明确 allowlist，并分别绑定安全 draft shape：entity/relationship 使用 structured content/maintenance candidate；alias 与 memory summary 使用对应 maintenance review candidate；clock tick 只接受 structured `tick_clocks`（含 canonical id、非零整数 delta 与安全 reason）；progress definition 若现有 content contract 不支持直接 mutation，只能保持 explicit review artifact，不能虚构 `upsert_clocks` 或 narrative write path。
  - [x] 复用 `entity_access.py`、`relationship_access.py`、`progress_access.py` 进行 current target、endpoint、archived/status 与 visibility 检查；复用既有 delta/content validation evidence，不直接解析 relationship `details_json` 或 clock storage internals。
  - [x] Artifact 必须明确记录 `current_fact_authority=false`、`application_authorized=false`、`proposal_approval_is_commit=false`、required profile/gates 与下一步 owner；intake 不接收 approval/confirmation/hidden permission/trusted delta/save/profile escalation/validation bypass/commit capability。
  - [x] `rejected`、`stale`、`superseded`、`conflict` 只作为 intake 时绑定的 disposition/evidence snapshot，不实现状态转换。对 update、alias、memory summary 与 clock tick，primary target 必须存在、未 archived、visibility 合法，且自 artifact 绑定的 base turn 后未变化；missing 或 changed-after-base target 使 artifact `application_eligible=false`。对 entity create，新 entity id 必须尚不存在；对 relationship create，新 relationship id 必须尚不存在，但 source/target endpoints 必须存在、未 archived且 visibility 合法；已存在的新建 id 构成 conflict。Progress definition create 在现有 content contract 没有 mutation owner 时固定 `application_eligible=false`。所有分支均 all-or-none。
  - [x] 更新 `rpg_engine/ai/__init__.py` 只导出稳定 review contract API；保持 Story 4.4 envelope、Story 4.5 adapters 与 owner paths 的既有 shape 不变。

- [x] Task 3：证明 review artifact 不会成为事实或 application 旁路（AC: 1-3）
  - [x] 用 temporary Save 在 intake 前后比较 `entities`、`aliases`、`clocks`、`memory_summaries`、`turns`、`events`、`meta`、projection/outbox 与 pending state；创建/序列化 artifact 不得写事实、Campaign、registry、pending、preflight 或 proposal queue。
  - [x] 用明确 no-call matrix 证明 intake 不取得 authority：queue lifecycle、content/save apply、validation/commit 与 provider 各至少设置一个 sentinel 并断言零调用；不得为测试绑定不必要实现细节，也不得在 production API 中加入测试编排 hook。
  - [x] Approval-shaped 或 reviewed payload 不能直接改变 entity/relationship/alias/memory/clock state；artifact 只能声明必须交给既有 content validation、maintenance validation 或 `TurnProposal -> validation -> commit` owner path，不能自行执行 application。
  - [x] 对 entity/relationship/content draft 执行适用的 schema/reference/visibility preflight；对 clock tick 执行 `validate_delta_progress_references()` 等现有检查。Preflight evidence 不是 application authorization，真正 apply 时仍须重新验证 current facts。
  - [x] 本 Story 的 intake 与 serializer 不创建、查询或修改 proposal queue；`proposal_queue.py` 的 create/review/apply/revert/batch/report/status/allowed-transition 均保持不变。若验收必须依赖持久化、queue status 或 queue report，立即停止并升级到 Story 5.7，不在本 Story 内补实现。

- [x] Task 4：覆盖 visibility、staleness、report/context recall 边界（AC: 2-3）
  - [x] Player projection 对 hidden/GM-only entity、hidden relationship endpoint、hidden clock、missing/archived target 使用统一 unavailable/omission 语义；不得泄漏 id、alias、kind、数量、正文、raw candidate 或逐项失败原因。
  - [x] Maintenance serializer 可输出 bounded canonical target/source、safe validation summary、disposition、supersedes references 与 rollback hint，但不得输出 private reasoning、provider body、prompt、raw hidden fact 或任意 mutation/approval token。
  - [x] `rejected`、`stale`、`superseded` 与 `conflict` artifact 的 report/recall representation 必须固定 `current_fact_authority=false` 且 `application_eligible=false`；现有 SQLite/access-contract current facts始终优先。
  - [x] 证明 artifact/report/context helper 是只读 evidence；这里只验证 caller 显式传入 artifact 的 maintenance/player-safe pure projection，不把 artifact 接入 `proposal_report()`、`render_proposal_report()`、proposal list/batch、持久 context recall collector、storage owner 或任何 queue lifecycle。不存在 artifact 时不查询或创建 advisory state，gameplay/context 仍安全降级且不阻塞 ordinary fact commit。

- [x] Task 5：同步 canonical docs 与后续 ownership（AC: 1-3）
  - [x] 更新 `docs/architecture.md` 与 `docs/data-models.md`：记录 advisory + separate candidate → explicit review artifact、required gate metadata、非事实/非 approval/非 commit、stale/supersession evidence，以及不选择新的 storage owner。
  - [x] 更新 `docs/component-inventory.md` 登记 `rpg_engine/ai/advisory_review.py`；更新 `docs/testing-and-quality-gates.md` 登记 focused、no-mutation、hidden/non-oracle、stale/conflict 与 application-bypass gates。
  - [x] 明确后续边界：Story 4.7 拥有 plot progression；Story 5.7 拥有 proposal queue allowed transitions、apply、revert、batch review 与 report lifecycle。本 Story 不新增 coordinator/scheduler、SQLite table/migration、Campaign/Save schema、依赖或 public CLI/MCP/platform surface。

- [x] Task 6：从最终 clean diff 运行全部 required gates（AC: 1-3）
  - [x] Story focused：new review contract、Resident advisory contract/adapters、Entity/Relationship/Progress access、相关 validation/content checks。
  - [x] Adjacent regression：validation/maintenance、current-native visibility/write safety、Runtime/SaveManager/MCP/platform/surface、proposal/content既有行为；所有写测试使用 temporary Save。
  - [x] Campaign：两个 canonical examples 的 validate/test。
    - [x] `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`
    - [x] `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`
    - [x] `python3 -m rpg_engine campaign validate ./examples/small_cn_campaign`
    - [x] `python3 -m rpg_engine campaign test ./examples/small_cn_campaign`
  - [x] Docs/static：Markdown links、changed Python `py_compile`、full Ruff、`git diff --check`。
  - [x] Repository full `pytest`；任何后续 review patch 都使受影响旧绿灯失效并必须重跑。

### Review Findings

- [x] [Review][Patch] Create 必须以 maintenance authority 排除 hidden/archived ID collision [rpg_engine/ai/advisory_review.py:247]
- [x] [Review][Patch] rollback hint 必须使用 bounded exact allowlist，禁止 authority/private smuggling [rpg_engine/ai/advisory_review.py:139]
- [x] [Review][Patch] Serializer 必须重验 family/operation、source/target、candidate 与 validation invariants，不能信任可重算 digest [rpg_engine/ai/advisory_review.py:388]
- [x] [Review][Patch] Current-target operations 必须绑定 canonical、存在的 base turn [rpg_engine/ai/advisory_review.py:229]
- [x] [Review][Patch] Relationship endpoint 必须同时满足 base-turn freshness [rpg_engine/ai/advisory_review.py:359]
- [x] [Review][Patch] Memory source events 必须验证存在性、visibility binding 与 freshness [rpg_engine/ai/advisory_review.py:293]
- [x] [Review][Patch] Progress definition review/create 必须执行 authoritative existence、live/current 与 visibility checks [rpg_engine/ai/advisory_review.py:303]
- [x] [Review][Patch] Delegated validator messages 必须映射为固定安全代码，禁止 caller/raw canary 进入 artifact [rpg_engine/ai/advisory_review.py:239]
- [x] [Review][Patch] Mutation targets 必须 exact binding，player projection 不得回显 mixed hidden targets [rpg_engine/ai/advisory_review.py:214]
- [x] [Review][Patch] Authority denylist 只匹配 exact control keys，不能误拒合法 gameplay 字段 [rpg_engine/ai/advisory_review.py:474]
- [x] [Review][Patch] No-mutation gate 必须比较完整数据库状态与 transaction ownership，而非仅 row counts [tests/test_resident_ai_advisory_review.py:425]
- [x] [Review][Patch] 补齐 Story 声明的 bounded snapshot、aliasing、TOCTOU 与 recomputed-forgery tests [tests/test_resident_ai_advisory_review.py:315]
- [x] [Review][Patch] Stale source advisory freshness 必须强制 stale/ineligible [rpg_engine/ai/advisory_review.py:136]
- [x] [Review][Patch] TEMP shadow 防护必须覆盖 delegated validator 读取的 items [rpg_engine/ai/advisory_review.py:548]
- [x] [Review][Patch] Temporary current-native fixture helper 必须拒绝 formal Save 且检查每项 normalization rowcount [tests/helpers.py:189]
- [x] [Review][Patch] Entity candidate 的 nested entity references 必须执行 caller-view visibility preflight [rpg_engine/ai/advisory_review.py:317]
- [x] [Review][Patch] Relationship/progress create 必须按共享 entities identity 排除跨类型 collision [rpg_engine/ai/advisory_review.py:322]
- [x] [Review][Patch] Memory source event 必须复用 player-safe hidden provenance resolver [rpg_engine/ai/advisory_review.py:375]
- [x] [Review][Patch] Serializer 必须重验完整 content record schema 与 memory source cross-binding [rpg_engine/ai/advisory_review.py:584]
- [x] [Review][Patch] Builder 必须在返回前执行与 serializer 一致的 static candidate contract [rpg_engine/ai/advisory_review.py:178]
- [x] [Review][Patch] Bounded snapshot 必须检测 exact built-in container 的并发撕裂 [rpg_engine/ai/advisory_review.py:659]
- [x] [Review][Patch] Player serializer 必须检测跨连接 visibility/currentness TOCTOU [rpg_engine/ai/advisory_review.py:260]
- [x] [Review][Patch] Entity family 不得接受 clock type，并须防止 update 改变 current entity type [rpg_engine/ai/advisory_review.py:434]
- [x] [Review][Patch] Exact control denylist 必须覆盖 commit/confirmation/profile/prompt/audit/session/hidden token [rpg_engine/ai/advisory_review.py:52]
- [x] [Review][Patch] 所有 family 的 source freshness event evidence 必须验证存在、visibility 与 base freshness [rpg_engine/ai/advisory_review.py:310]
- [x] [Review][Patch] Base turn 必须使用 repository canonical turn ID contract [rpg_engine/ai/advisory_review.py:873]
- [x] [Review][Patch] Turn freshness 必须按 timezone-aware instant 比较而非 ISO 字符串字典序 [rpg_engine/ai/advisory_review.py:653]
- [x] [Review][Patch] Supersedes/rollback references 必须使用 canonical safe ID pattern [rpg_engine/ai/advisory_review.py:845]
- [x] [Review][Patch] Base turn 与 evidence as-of 必须严格绑定 source advisory freshness [rpg_engine/ai/advisory_review.py:204]
- [x] [Review][Patch] Player serializer 必须同时检测同连接 mutation/transaction TOCTOU [rpg_engine/ai/advisory_review.py:287]
- [x] [Review][Patch] Intake 必须检测其他连接在多次 preflight read 间提交的事实变化 [rpg_engine/ai/advisory_review.py:181]
- [x] [Review][Patch] Player serializer 必须检测检查期间新增 TEMP shadow/schema 变化 [rpg_engine/ai/advisory_review.py:287]
- [x] [Review][Patch] Player source projection 必须 exact 证明全部 artifact targets 可见 [rpg_engine/ai/advisory_review.py:293]
- [x] [Review][Patch] Entity content candidate 必须拒绝 validator 忽略的未知 record 字段 [rpg_engine/ai/advisory_review.py:512]
- [x] [Review][Patch] Progress definition target 必须使用 canonical clock ID namespace [rpg_engine/ai/advisory_review.py:555]
- [x] [Review][Patch] Rollback references 必须限定为安全 gameplay/evidence namespaces [rpg_engine/ai/advisory_review.py:984]
- [x] [Review][Patch] Non-current artifact 必须始终携带 bounded rollback 或 supersession evidence [rpg_engine/ai/advisory_review.py:157]
- [x] [Review][Patch] 最终 required gates 必须在 review patches 收敛后的 clean diff 上重跑并记录 [4-6-entity-relationship-and-progress-advisory-review.md:75]
- [x] [Review][Patch] Authority/private denylist 必须覆盖 canonical contract 与 raw-output 同义字段 [rpg_engine/ai/advisory_review.py:52]
- [x] [Review][Patch] Temporary Save helper 必须拒绝指向 formal game.sqlite 的 symlink/hardlink [tests/helpers.py:189]
- [x] [Review][Patch] Advisory type/workflow 必须与 suggestion family 严格绑定 [rpg_engine/ai/advisory_review.py:215]
- [x] [Review][Patch] Freshness 必须按 canonical turn sequence 而非 caller-controlled wall-clock 排序 [rpg_engine/ai/advisory_review.py:833]
- [x] [Review][Patch] Candidate denylist 必须覆盖完整 canonical authority/private vocabulary [rpg_engine/ai/advisory_review.py:63]
- [x] [Review][Patch] Serializer 必须要求 runtime-issued artifact proof，不能接受伪造 dynamic preflight [rpg_engine/ai/advisory_review.py:760]
- [x] [Review][Patch] Temporary helper 必须在 SQLite open 后复核实际 database file [tests/helpers.py:189]
- [x] [Review][Patch] Entity/relationship candidate 不得经 aliases 字段绕过 no-owner boundary [rpg_engine/ai/advisory_review.py:134]
- [x] [Review][Patch] Create 必须以 source freshness bound 检查 source events 时序 [rpg_engine/ai/advisory_review.py:436]
- [x] [Review][Patch] Relationship create endpoint 也必须执行 source/base freshness [rpg_engine/ai/advisory_review.py:475]
- [x] [Review][Patch] Evidence as-of 必须与 freshness as-of exact 对账，不能以 null 绕过 [rpg_engine/ai/advisory_review.py:1186]
- [x] [Review][Patch] Runtime-issued registry 必须按对象 identity 而非 dataclass value equality 校验 [rpg_engine/ai/advisory_review.py:225]
- [x] [Review][Patch] Bounded snapshot 与 progress numbers 必须限制整数幅度 [rpg_engine/ai/advisory_review.py:687]
- [x] [Review][Patch] Event-only create freshness 缺少 canonical base 时必须 fail closed [rpg_engine/ai/advisory_review.py:281]
- [x] [Review][Patch] Authority denylist 必须覆盖 fact_authority/application_eligible/current_fact 同义字段 [rpg_engine/ai/advisory_review.py:65]
- [x] [Review][Patch] Entity/relationship candidate 必须拒绝未知 visibility label [rpg_engine/ai/advisory_review.py:627]
- [x] [Review][Patch] Relationship candidate 必须使用专属 exact record fields，禁止跨 subtype blocks [rpg_engine/ai/advisory_review.py:647]
- [x] [Review][Patch] Entity subtype numeric fields 必须使用 exact types 与业务范围 [rpg_engine/ai/advisory_review.py:675]
- [x] [Review][Patch] Maintenance-visible candidate 文本必须拒绝 control/ANSI/bidi injection [rpg_engine/ai/advisory_review.py:683]
- [x] [Review][Patch] Relationship details 必须 exact keys 并完整校验 text/numeric safety [rpg_engine/ai/advisory_review.py:690]
- [x] [Review][Patch] Entity update 必须允许 exact preserve current aliases，不能因 alias 既存而误拒 [rpg_engine/ai/advisory_review.py:532]
- [x] [Review][Patch] Relationship update outer allowlist 必须允许 exact preserve current aliases [rpg_engine/ai/advisory_review.py:168]
- [x] [Review][Patch] Base turn 必须不晚于 authoritative current turn，拒绝 future-base 绕过 [rpg_engine/ai/advisory_review.py:1332]
- [x] [Review][Patch] Relationship update 必须保留 current details key shape，避免静默擦除 notes [rpg_engine/ai/advisory_review.py:691]
- [x] [Review][Patch] Item durability_current 不得超过 durability_max [rpg_engine/ai/advisory_review.py:1193]
- [x] [Review][Patch] Crop growth/harvest lower bound 不得超过 upper bound [rpg_engine/ai/advisory_review.py:1212]
- [x] [Review][Patch] Entity update 必须显式提供完整 replacement base/subtype shape，禁止 omission 默认值擦除 [rpg_engine/ai/advisory_review.py:536]
- [x] [Review][Patch] Relationship update 不得修改 stable source/target/kind identity fields [rpg_engine/ai/advisory_review.py:543]
- [x] [Review][Patch] Entity candidate references 必须按 artifact base turn 执行 freshness [rpg_engine/ai/advisory_review.py:515]
- [x] [Review][Patch] Entity update subtype section 集合必须与 authoritative current subtype rows 完全一致 [rpg_engine/ai/advisory_review.py:992]
- [x] [Review][Patch] Location discovered_turn_id 必须 canonical、存在且不晚于 artifact base [rpg_engine/ai/advisory_review.py:940]
- [x] [Review][Patch] Relationship target ID 必须使用 canonical rel: namespace [rpg_engine/ai/advisory_review.py:739]
- [x] [Review][Patch] Entity create subtype blocks 必须与 declared entity type compatible [rpg_engine/ai/advisory_review.py:761]
- [x] [Review][Patch] Relationship update 必须显式提供完整 replacement base fields [rpg_engine/ai/advisory_review.py:616]
- [x] [Review][Patch] Issuance registry 必须保存独立 canonical fingerprint，检测 issued object 原地篡改 [rpg_engine/ai/advisory_review.py:306]
- [x] [Review][Patch] Entity family 必须拒绝占用 rel:/clock: owner-specific namespaces [rpg_engine/ai/advisory_review.py:761]
- [x] [Review][Patch] Entity family reserved namespace 防护必须覆盖 rule:/world:/setting: [rpg_engine/ai/advisory_review.py:799]
- [x] [Review][Patch] Location discovered_turn_id 在 base=None 时仍必须验证 authoritative existence [rpg_engine/ai/advisory_review.py:1024]
- [x] [Review][Patch] Entity family reserved namespace 防护必须覆盖 route: 与其他明确非 entity-owner IDs [rpg_engine/ai/advisory_review.py:796]
- [x] [Review][Patch] Entity family 必须拒绝 rule/world_setting dedicated-owner type smuggling [rpg_engine/ai/advisory_review.py:810]
- [x] [Review][Patch] Entity reserved namespaces 必须覆盖 table:/pal: auxiliary author-content owners [rpg_engine/ai/advisory_review.py:278]
- [x] [Review][Patch] Generic entity namespace 防护必须改为 type→canonical prefix allowlist，封闭 denylist 漏项 [rpg_engine/ai/advisory_review.py:278]
- [x] [Review][Patch] Type→namespace/subtype contract 必须对齐 char:/creature:/plot: canonical current facts [rpg_engine/ai/advisory_review.py:278]
- [x] [Review][Patch] Equipment namespace 必须与 CardRegistry exact 对齐，禁止 item: type divergence [rpg_engine/ai/advisory_review.py:282]
- [x] [Review][Patch] Entity subtype direct SQLite scalar fields 必须 exact str|None [rpg_engine/ai/advisory_review.py:1466]
- [x] [Review][Patch] Rollback safe namespaces 必须从 canonical entity namespace mapping 派生 [rpg_engine/ai/advisory_review.py:259]
- [x] [Review][Patch] Equipment namespace 必须对齐 formal current facts 的 canonical item: shared prefix [rpg_engine/ai/advisory_review.py:282]
- [x] [Review][Patch] Clock tick static candidate 必须强制 canonical clock: ID [rpg_engine/ai/advisory_review.py:945]
- [x] [Review][Patch] Authority denylist 不得误拒 canonical gameplay details.profile [rpg_engine/ai/advisory_review.py:106]
- [x] [Review][Patch] Entity subtype JSON fields 必须校验 exact dict/list shapes [rpg_engine/ai/advisory_review.py:1440]
- [x] [Review][Patch] 公开事实读取入口必须 fail closed 拒绝调用前已存在的 SQLite snapshot transaction，且不改变 caller transaction ownership [rpg_engine/ai/advisory_review.py:408]
- [x] [Review][Patch] Nested gameplay JSON 必须拒绝 prompt/session/error/proposal/raw response control-field 同义键 [rpg_engine/ai/advisory_review.py:76]
- [x] [Review][Patch] Player-scoped advisory 不得生成 hidden/GM-only 且 application-eligible 的 content candidate [rpg_engine/ai/advisory_review.py:650]
- [x] [Review][Patch] Rollback gameplay reference 必须接受仓库 canonical mixed-case entity/clock ID 后缀 [rpg_engine/ai/advisory_review.py:1620]
- [x] [Review][Patch] Entity create 的 nested subtype block 必须拒绝 schema allowlist 外字段，保持 artifact 与 apply shape 一致 [rpg_engine/ai/advisory_review.py:880]
- [x] [Review][Patch] Nested gameplay JSON 的所有 dict key 必须拒绝 bidi/ANSI/control 文本注入 [rpg_engine/ai/advisory_review.py:1276]
- [x] [Review][Patch] Singleton entity candidate 必须拒绝 primary target 的自引用事实 [rpg_engine/ai/advisory_review.py:1072]
- [x] [Review][Patch] Entity/relationship create candidate 必须显式携带 visibility，禁止 omission 继承公开默认值 [rpg_engine/ai/advisory_review.py:895]
- [x] [Review][Patch] Relationship create/update 必须要求 non-empty exact details.kind [rpg_engine/ai/advisory_review.py:920]
- [x] [Review][Patch] Artifact issuance 必须绑定 authoritative fact fingerprint，拒绝同一 base turn 内后续事实替换 [rpg_engine/ai/advisory_review.py:1251]

## 开发说明

### 范围与 P0 边界

- 本 Story 是 P0，因为它触碰 AI advisory、visibility、validation/maintenance gate 的边界；已有 PRD、两份 Architecture Spine、Epic 4 和获批 Correct Course 为规划证据。
- 本 Story 只负责 `AI suggestion -> explicit review artifact`。`proposal_queue.py` 现有 lifecycle 较宽松，但 review/apply/revert/batch/report 状态机的修正严格属于 Story 5.7，不得顺手修改。
- `ResidentAIAdvisory` 只有 metadata/target/evidence，不含可信 mutation body；必须用独立、严格、bounded candidate draft 输入，二者绑定后才形成 review artifact。Artifact 不是 delta、proposal approval、confirmation、validation proof 或 commit token。
- `data/game.sqlite` 继续是事实权威。AI、review artifact、proposal queue、content delta draft、maintenance draft、rollback hint 与 report 都不能覆盖 current facts。
- `AI proposes. Kernel verifies. Player confirms. Engine commits.` 不变；external/internal/resident AI 都不能取得 fact、hidden、approval、confirmation、validation 或 commit authority。
- 不新增依赖、表、migration、public CLI/MCP/platform surface、resident coordinator/scheduler；不修改 source Campaign、formal current Saves 或正式 registry。所有写测试必须使用 temporary Save。

### 固定 vocabulary

- `schema_version` 固定为 `resident_ai_advisory_review:v1`。
- `suggestion_operation` 只接受 `create | update | review | tick`。
- `disposition` 只接受 `reviewable | rejected | stale | superseded | conflict`。
- Authority 固定为 `current_fact_authority=false`、`application_authorized=false`、`proposal_approval_is_commit=false`；caller 不得覆盖。
- 每个 suggestion family 的 `required_gate` 与 `next_owner` 必须使用下表固定 token；未知或近似 token 脱敏 fail closed，不静默归一化。

### Artifact kind 与既有 owner 映射

| Suggestion | Review artifact / draft | Required checks | Application owner（本 Story 不调用） |
| --- | --- | --- | --- |
| Entity create | structured content candidate | id absent、content schema、same-delta refs、visibility | `validate_content_delta` preflight；existing content maintenance owner |
| Entity update | structured content/maintenance candidate | id live/current、content schema、entity refs、visibility | `validate_content_delta` preflight；existing content maintenance owner |
| Relationship create | entity-backed relationship candidate | relationship id absent、live endpoints、endpoint visibility、content schema | `validate_content_delta` preflight；existing content maintenance owner |
| Relationship update | entity-backed relationship candidate | relationship + endpoints live/current、visibility、content schema | `validate_content_delta` preflight；existing content maintenance owner |
| Alias | alias maintenance candidate | target existence/status/visibility、bounded alias shape | existing maintenance path |
| Memory summary | memory update candidate | source/freshness/visibility、derived authority | existing memory maintenance/rebuild path |
| Progress definition | explicit review artifact | entity/clock identity、schema、visibility | no named application owner；`application_eligible=false` |
| Clock tick | structured `tick_clocks` candidate | canonical live/current clock、non-zero delta、reason、visibility | `validate_delta_progress_references` preflight；confirmed TurnProposal 或 existing maintenance validation owner |

### 文件结构要求

- **NEW**：`rpg_engine/ai/advisory_review.py`、`tests/test_resident_ai_advisory_review.py`。
- **UPDATE**：`rpg_engine/ai/__init__.py`、`docs/architecture.md`、`docs/data-models.md`、`docs/component-inventory.md`、`docs/testing-and-quality-gates.md`。
- **CONDITIONAL UPDATE（必须有 RED 证据）**：`content_validation.py`、`validation_pipeline.py`、三 access-contract modules 仅限现有 contract 无法提供 required evidence 的最小缺口。
- **EXPECTED NO CHANGE**：proposal review/apply/batch/report lifecycle、`content_delta.py` apply、`save_patch.py` apply、Runtime、SaveManager、CommitService、preflight、CLI/MCP/platform、migrations/schema、Campaign/Save/formal registry、Story 4.5 adapters/owner paths。

### 测试要求

建议 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_resident_ai_advisory_review.py \
  tests/test_resident_ai_advisory_adapters.py \
  tests/test_resident_ai_advisory.py \
  tests/test_entity_access.py \
  tests/test_relationship_access.py \
  tests/test_progress_access.py \
  tests/test_validation_pipeline.py \
  tests/test_palette_governance.py \
  -p no:cacheprovider
```

建议 adjacent regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_low_level_condition_coverage.py \
  tests/test_maintenance_tooling_coverage.py \
  tests/test_current_native_visibility.py \
  tests/test_current_native_write_safety.py \
  tests/test_cross_layer_regression.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_mcp_adapter.py \
  tests/test_platform_sidecar.py \
  tests/test_surface_inventory.py \
  -p no:cacheprovider
```

### Previous Story 4.5 intelligence

- Story 4.5 在 commit `d1c5784` 建立 Internal Intent Review 与 State Audit Progress 两个 strict companion adapters；它们只输出 metadata envelope，不是 review artifact 或 mutation payload。
- 4.5 经 16 轮三路 fresh review、36 项 patch 收敛。重点教训是 exact types、bounded deep snapshot、source mutation/TOCTOU、TEMP shadow、canonical digest、owner-private validation proof 与脱敏异常必须 defense-in-depth。
- 4.5 最终 gate 为 focused 236/222 subtests、adjacent 265/9261 subtests、full 907/9890 subtests；这些只是基线，不能复用为 4.6 完成绿灯。
- 当前 formal Save 可能由外部游戏会话推进；current-native gates 必须复制冻结 temporary Campaign/Save roots，绝不能回滚或写 formal source。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 4 / Story 4.6]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md` — §4.5 Story 4.6 与 5.7 proposal 分工]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md` — FR-5、FR-7、FR-8、FR-9、§6.0-6.3]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md` — AD-3、AD-4、AD-6、AD-10]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md` — AD-1、AD-2、AD-4、AD-5]
- [Source: `_bmad-output/implementation-artifacts/4-5-resident-ai-advisory-代表性适配.md` — AC3、范围、Review Findings 与 Previous Story intelligence]
- [Source: `docs/project-context.md`、`docs/architecture.md`、`docs/data-models.md`、`docs/component-inventory.md`、`docs/testing-and-quality-gates.md`]
- [Source: `rpg_engine/ai/advisory.py`、`rpg_engine/ai/advisory_adapters.py`、`rpg_engine/proposal_queue.py`、`rpg_engine/content_delta.py`]
- [Source: `rpg_engine/entity_access.py`、`rpg_engine/relationship_access.py`、`rpg_engine/progress_access.py`]

## 开发代理记录

### 使用的代理模型

GPT-5 Codex

### 调试日志引用

- Create Story research：两路只读 subagents 分别覆盖 planning/previous story/git 与 code/access/validation/proposal boundaries；共同确认“strict advisory + separate candidate -> explicit review artifact、无 lifecycle 越界”。
- BMAD Create Story：完整读取 `.agents/skills/bmad-create-story/SKILL.md`、discover/template/checklist；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空。
- Input discovery：完整 Sprint status、Epic 4/Story 4.6、主 PRD、两份 Architecture Spine、Correct Course §4.5、previous Story 4.5、canonical docs 与现有 advisory/access/proposal/content code；无 UX artifact。
- Web research：未执行。本 Story 不新增/升级 library、framework、external API 或依赖，只复用仓库锁定 Python/stdlib/jsonschema/pytest/Ruff。
- Validate Story：fresh validator 提出 3 Critical、4 Enhancement、2 Optimization；9 项无歧义改进全部应用，Decision-needed=0。
- RED：`tests/test_resident_ai_advisory_review.py` 首次 collection 因 `rpg_engine.ai.advisory_review` 不存在而失败。
- GREEN/refactor：new review contract 13 passed / 11 subtests；focused contract gate 120 passed / 188 subtests。
- Adjacent 首轮暴露 formal current Save 已从旧测试基线推进至 turn 45 / 地下菌丝城，以及 dirty memory projection 引起的 temporary fixture 漂移；未修改 formal Save，改为在 temporary copies 显式固定旧故事语言前置，并动态对账正式 inspect/no-write baseline。
- Dev Story adjacent：310 passed / 9260 subtests；两个 canonical Campaign validate/test 四命令均 OK。
- Dev Story docs/static：Markdown links 183 files、changed Python `py_compile`、full Ruff 与 `git diff --check` 全部通过。
- Dev Story repository full：920 passed / 9901 subtests。
- BMAD Dev Story：完整读取 `.agents/skills/bmad-dev-story/SKILL.md`；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空；按 fresh start→in-progress→RED/GREEN/refactor 顺序执行。
- BMAD Code Review：完整读取 `.agents/skills/bmad-code-review/SKILL.md` 与 step-01 至 step-04；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空。
- Review 自动收敛：共 27 轮三路 fresh review；自动应用 98 个去重、复现、范围内且无歧义的 `[Review][Patch]`；dismiss 1 个与 singleton P0 边界冲突的 multi-record finding；`[Review][Decision]=0`、`[Review][Defer]=0`。第 27 轮 Blind Hunter、Edge Case Hunter、Acceptance Auditor 全部 CLEAN。
- 最终 clean diff gates：focused 154 passed / 282 subtests；adjacent 310 passed / 9260 subtests；两个 canonical Campaign validate/test 四命令均 OK；Markdown links 183 files、changed Python `py_compile`、full Ruff、`git diff --check` 全部通过；repository full 954 passed / 9995 subtests。

### 实施计划

- 先用 RED tests 冻结 artifact shape、kind mapping、input bounds、no-authority 与 no-mutation。
- 实现纯、只读 review intake contract，复用 advisory normalizer 与三类 access contract；不实现 apply/lifecycle。
- 同步 canonical docs，从最终 clean diff 完成三路 review 自动收敛与全部 required gates。

### 完成说明列表

- 已完成终极上下文引擎分析并生成实现指南。
- 已实现 `resident_ai_advisory_review:v1` 深度不可变 review artifact、strict intake、maintenance/player-safe serializers 与固定 no-authority contract。
- Entity/relationship candidate 只执行 content/access preflight，clock tick 只执行 progress reference preflight；alias/memory/progress definition 没有具名 owner 时固定不可 application。
- Intake 不创建/查询 proposal queue，不调用 provider/apply/validation/commit owner，不写 Save/Campaign/registry/pending/preflight；实际 application 必须由既有 owner 从 current facts 重新验证。
- 已同步 architecture、data model、component inventory 与 testing docs；Story 5.7 的 queue lifecycle ownership保持不变。
- 已修复 current-native tests 对可演进正式 Save 的硬编码 fixture 假设；所有变更只在 temporary copies 建立测试前置，正式 Save 未被修改。
- 全部 tasks、AC、Dev Story DoD、27 轮 review 收敛与最终 required gates 已满足，Story 状态转为 done。

### 文件列表

- `_bmad-output/implementation-artifacts/4-6-entity-relationship-and-progress-advisory-review.md`
- `_bmad-output/implementation-artifacts/4-6-entity-relationship-and-progress-advisory-review.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/ai/__init__.py`
- `rpg_engine/ai/advisory_review.py`
- `tests/helpers.py`
- `tests/test_cross_layer_regression.py`
- `tests/test_current_native_actions.py`
- `tests/test_current_native_context.py`
- `tests/test_current_native_package.py`
- `tests/test_current_native_player_turn.py`
- `tests/test_current_native_visibility.py`
- `tests/test_current_native_write_safety.py`
- `tests/test_resident_ai_advisory_review.py`

## 变更日志

- 2026-07-12：Create Story 生成完整实现上下文，状态设为 ready-for-dev。
- 2026-07-12：Validate Story 自动应用 9 项改进，Decision-needed 为 0。
- 2026-07-12：实现 strict advisory review intake/artifact、安全 projection、focused tests 与 canonical docs；修复 temporary current-native fixture 漂移。
- 2026-07-12：Dev Story required gates 全绿，Story 转为 review。
- 2026-07-12：经 27 轮三路 fresh review 自动收敛，应用 98 个 patch；最终 clean-diff required gates 全绿，Story 转为 done。

## BMAD 来源记录

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`，从 sprint status 自动选择下一个 backlog story。
- Catalog 路由：`[CS] Create Story`（`bmad-create-story:create`）后接 `[VS] Validate Story`（`bmad-create-story:validate`）。
- Skill：`.agents/skills/bmad-help/SKILL.md` 与 `.agents/skills/bmad-create-story/SKILL.md` 已完整读取。
- 后续 Skill：`.agents/skills/bmad-dev-story/SKILL.md` 与 `.agents/skills/bmad-code-review/SKILL.md` 已完整读取并按 step files 顺序执行。
- Customization：`bmad-help` 无 customization surface；`bmad-create-story` resolver 成功，`activation_steps_prepend=[]`、`activation_steps_append=[]`、`persistent_facts=[file:{project-root}/**/project-context.md]`、`on_complete=""`。
- 已加载 config/facts：`_bmad/bmm/config.yaml`、`_bmad/core/config.yaml`、`docs/project-context.md`、`docs/governance/bmad-workflow.md`；通信与 artifact 均为中文。
