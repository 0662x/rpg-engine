# 架构

文档状态：**CURRENT：BMAD canonical architecture**

## 总体架构

RPG Engine 是本地优先的 AI GM 引擎内核。外部入口按权限和用途分成玩家安全链、低层
runtime 链、平台 sidecar 链和平台预热链。所有链路都必须保持同一个核心原则：

```text
AI proposes. Kernel verifies. Player confirms. Engine commits.
```

```mermaid
flowchart TD
  Player["玩家输入"] --> PlayerEntry["CLI/MCP player-safe / PlatformSidecar"]
  PlayerEntry --> SaveManager["SaveManager.player_turn"]
  SaveManager --> Act["GMRuntime.act"]
  Act --> Intent["intent_router + AIIntentRouter"]
  Intent --> PreviewAction["GMRuntime.preview_action + ActionResolverSpec"]
  PreviewAction --> Proposal["pending TurnProposal"]
  Proposal --> Confirm["SaveManager.player_confirm"]
  Confirm --> Commit["GMRuntime.commit_turn"]
  Commit --> CommitService["Commit Service / UnitOfWork / WriteGuard"]
  CommitService --> DB["SQLite Save DB + Events"]

  Dev["Developer/trusted MCP 或 Python API"] --> Runtime["GMRuntime low-level methods"]
  Runtime --> Context["Context Builder / Query / Preview / Validate"]

  Platform["平台消息"] --> Sidecar["PlatformSidecar entry gate"]
  Sidecar --> PlayerEntry

  Platform --> Prewarm["PlatformPrewarm worker"]
  Prewarm --> Preflight["GMRuntime.preflight_intent"]
  Preflight --> Cache["intent_preflight_cache advisory review"]
  Cache -. "正式入口重新校验后才可消费" .-> Intent
```

`rpg_engine.surface_inventory` 是当前 public / semi-public entry surface 的可测试权限清单。
每个 entry 必须同时声明 domain category、canonical taxonomy、write authority、intended caller、
default exposure、normal-play status、authority gate 和 forbidden bypasses。Canonical taxonomy 只能是
`player-safe`、`trusted low-level`、`maintenance/admin`、`platform sidecar`、`platform prewarm`
或 `projection/outbox`；新增入口缺少这些元数据时，`tests/test_surface_inventory.py` 必须失败。

## 玩家安全链

普通玩家动作的主链是：

1. `SaveManager.player_turn()` 接收玩家输入，解析 campaign、save 和 session。
2. `GMRuntime.act()` 调用 `preview_from_text()`，进入 `route_intent()`。
3. `intent_router.py` 准备规则候选、外部候选、兼容候选和 AI 配置。
4. `ai_intent/router.py` 的 `AIIntentRouter` 按 mode 编排 candidate collection、可选内部复核、
   arbitration、槽位绑定、route adoption 和 trace：enabled + external 保持双候选仲裁；
   `off` + valid external 采用 `external_primary`；`off` + no external 保持 deterministic fallback。
5. Canonical binder用当前Save SQLite重新核验entity lifecycle与caller visibility；只有normalized
   `status='active'` 的可见row可进入action binding。Active exact先于同名/同alias历史row胜出；若没有active exact，
   visible non-active exact先于partial/literal阻断，non-active partial与active partial冲突也fail closed，hybrid composite
   的canonical phrase在active partial前按NFKC/casefold token边界阻断，qualified ID将`-`/`:`视为token continuation；
   任何多codepoint非Latin letter script的name/alias（含supplementary Han ranges）都在连写自然短语中按canonical substring识别；任意不同letter script之间的转换也是canonical boundary，纯Latin单词内部仍受token保护。Canonical identity先NFKD分解，再将Unicode marks与完整Default_Ignorable范围（含U+2065、U+FFF0区段、Plane 14）在两侧统一折叠；单codepoint判定使用folding前identity，因此base+mark仍作多codepoint，public control-character safety gate仍独立生效。U+200B/U+2060等项目
   edge whitespace先被剥离且归一化空输入不进入SQL；qualified ID continuation包含实际grammar允许的`.`；
   normalized-empty在entity与hybrid slot中都返回missing，`text_or_entity` exact-only不采用active contained-ID binding；
   resolver token/body/FTS也不能二次复活non-active引用；binder镜像resolver阶段次序，按token顺序的首个exact winner决定active放行或non-active阻断，之后的token partial/body/FTS阶段逐阶段检查任一visible non-active命中，同阶段active排序winner不能遮蔽它。未配对UTF-16 surrogate在SQLite前invalid/blocked。共享token/FTS tokenizer与binder共用NFKD后mark/完整Default_Ignorable折叠；exact-token ID suffix及partial/body LIKE转义`%`/`_`/`!`，partial排序CASE也使用相同ESCAPE语义，避免preview重新制造短alias、FTS历史命中或通配符排序退化。
   Shared partial lookup将 `%`、`_`、`!` 解释为字面字符，entity/clock/world-setting subtype visibility一并生效。
   PLAYER_VIEW 的hidden row不参与lifecycle shadow，因此hybrid literal fallback与真正absent保持同形，且不形成entity binding。
6. `GMRuntime.preview_intent()` / `GMRuntime.preview_action()` 基于动作解析器生成可确认预览。
7. ready 结果写成 pending `TurnProposal`，此时还没有提交状态变化。
8. `SaveManager.player_confirm()` 校验 pending proposal、平台 session hash、确认状态和来源。
9. `GMRuntime.commit_turn()` 接收 approved `TurnProposal`，再进入 validation / commit。
10. `commit_service.py`、`unit_of_work.py`、`write_guard.py` 写入 SQLite、事件和投影材料。

`player_confirm()` 在 SaveManager owner 内用可在进程退出时自动释放的 workspace file lock 串行化
pending 的 read → identity/payload validation → commit/replay classification → receipt → clear。SQLite
`turns.command_id` / `command_hash` 与 event rows 仍是权威证据；`.aigm` confirmation claim/receipt 只保存
bounded hash/digest 和 turn result evidence，不是事实、确认、proposal approval 或 commit token。首个 caller
返回 `write_status=committed`；同一身份与 payload 的并发/崩溃重试返回
`write_status=already_confirmed`、`idempotent_replay=true`，且不重复 backup、archivist、projection/outbox
或 registry fresh-only 工作。

`player_turn()` 清理旧 pending 与发布新 pending/receipt transition 时也取得同一 confirmation lock，避免
in-flight confirm 删除较新的 session；pending 发布失败会恢复上一条 replay receipt。Durable command 的
pending 即使在重试前过期，也先按 SQLite evidence 进入 recovery。若进程在 SQLite commit 后、outbox 或
projection finalize 前退出，完成 claim/identity/payload 核验的 SaveManager replay 只对 dirty
`events_jsonl` / snapshots / cards 执行幂等 repair；
registry 仅在 cached turn 落后于 durable turn 时修复，不把普通 replay 计作 fresh save。
Fresh confirm 会冻结首次核验的 bound save id/path，并按该 exact path refresh；active registry 在确认中的
并发切换不能把 pending 写入另一 Save。Platform replay 默认只保留 reservation/current binding，不重复
activation 或延长 active TTL；唯一例外是 binding 中持久化的 pending confirmation session hash 与同一
durable replay 精确匹配、状态仍为 `pending_approval` 且 Save 未变化时，sidecar 只补做缺失的
`active_game` completion transition，并保持原 TTL。
Pending 缺失 save path、receipt duplicate JSON key 与非规范 result type 均 fail closed；confirmation lock 的
OS 失败对公开入口使用稳定脱敏错误，fd close 不因 unlock 异常被跳过。确认后的 registry refresh 在同一
registry lock 内 read-merge-write，platform completion 也在 entry lock 内合并最新 reservation，避免较旧
completion 覆盖并发 switch/message。Start、act 与 confirm completion 以及 deactivate/expiry writer 共用
跨平台 crash-release entry/file lock；advisory prewarm 的 binding RMW 也使用该锁但不推进 authoritative
revision。Completion 在 activation 前比较 revision/context，保留较新的 prewarm message id，同时不能复活
较新的 inactive binding；fresh/replay confirm completion 都以其 reservation 捕获的 state revision 做 CAS，
较新的 start/act/deactivate/save context 必须获胜。Pending confirmation 另存其创建时的
`pending_confirmation_revision`：start/act 推进操作 generation，同一 confirm 的消息 reservation 不推进；
因此 start 先取得 reservation 后，较旧 confirm 即使随后取得 Kernel replay 结果也不能激活旧 generation。
Schema 1 旧 binding 只在 correlation 为空、binding/pending revision 都为 0、Save/state 精确匹配且
SaveManager 已返回同一 owner-validated confirmation hash 时允许一次兼容回填。Registry 所有 production RMW 的 read → refresh/mutate →
write 均处于同一 OS crash-release transaction lock；锁文件存在本身不表示仍有 owner。
Bound-save refresh 本身也只通过 registry 锁内 merge 更新 record；`switch_save` 与 platform deactivate 使用
同一各自 owner lock；merge 会在锁内按 path/id 重新取得最新 record，再从 SQLite refresh，不能用 caller 的
旧 record 覆盖并发 metadata，也不能在 merge read/write 之间插入 stale completion。Pending claim 绑定 save 与全部
hashed platform identity，并在首次 confirm 前写入目标 Save SQLite claim anchor；可捕获的 commit failure
只有在重新查询 SQLite 并证明 command 尚未 durable 时才恢复原 pending并删除本次 anchor。若已 durable，
或 evidence query 本身失败，则 fail closed 保留 claim/anchor 供 recovery；真实进程退出同样保留二者。

`GMRuntime.start_turn()` 主要用于构建当前回合上下文和可见信息，不是玩家动作提交主入口。

## 低层 Runtime 链

开发者或受信 MCP profile 可以直接调用 `GMRuntime.start_turn()`、`query()`、
`preview_action()`、`validate_delta()`、`commit_turn()` 等低层能力。MCP adapter 必须通过
profile gate 控制这些能力：默认 profile 只暴露 player-safe 工具，developer、trusted、
maintenance、admin 才能看到低层工具。

## 平台 Sidecar 链

`platform_sidecar.py` 负责平台入口门禁、冲突处理和指标。正式玩家动作最终仍应走
player-safe path，由 `SaveManager` 与 `GMRuntime` 处理 pending proposal 和确认。
sidecar 不应复制业务逻辑，也不应成为提交状态的旁路。

## 平台预热链

`platform_prewarm.py` 的 worker 可以提前调用 `GMRuntime.preflight_intent()`，把 advisory
internal intent review 写入 `intent_preflight_cache`。正式入口消费缓存时必须重新验证：

- `user_text`
- save / base turn
- context hash
- provider / model / backend
- schema / task / profile
- platform / session / message 身份
- active action taxonomy / slot projection digests

preflight cache 只能作为候选来源，不能替代最终 preview、validation、confirm 或 commit。
`candidate_bound` helper identity 使用 provider/model/backend/fallback 独立字段对账，不依赖可碰撞的拼接
字符串；`message_only` 在 Runtime 与 cache service 双层要求完整 platform/session/message identity，并在
写入前清除 external candidate。Ready row 通过 SQLite 条件更新原子消费一次，TTL、mismatch、并发 replay、
pending bypass 与 late-ready 都只能 miss/reject/fallback，不能恢复任何 authority。

## AI 延迟与降级边界

Player-facing intent helper 的默认 latency policy 是约 8 秒 soft wait target 与 15 秒 hard total
deadline。Soft target 用于结构化 `soft_wait_exceeded` evidence；调用可以继续等待到 hard deadline，
也可以走 clarification、blocked 或 non-AI safe processing。`intent_timeout` 是 caller 配置的 hard
budget，direct primary 与可选 fallback 必须共享该预算，不能各自重新计时。

Hard deadline 后返回的 payload 即使 schema-valid 也必须丢弃并记录 `late_discarded`，不得进入
arbitration、pending 或 commit。Internal intent AI 配置为 `consensus` 时，timeout/unavailable 仍是
enabled-mode helper failure；只能通过 risk-aware fallback/clarification/block 收敛，不能变成显式
`off`，也不能授予 external candidate `external_primary` route proposal authority。

Resident/background 与 platform prewarm 的 30-60 秒目标只描述 advisory scheduling。Timeout、queue
full、failed 或 late-ready 产生 evidence/drop reason，不阻塞 gameplay fact commit。当前 platform
prewarm 默认使用 60 秒 background deadline；player-facing intent 仍是 15 秒 hard deadline。Foreground
与 background helper 使用独立 bounded worker capacity，background 饱和不能占满 player-facing slots。
Background latency 按 `before_target` / `within_target` / `target_exceeded` 记录，不复用 player-facing
`soft_wait_exceeded`。Player/public trace 只暴露稳定 failure class 与脱敏 audit，不回传 provider body、
exception detail 或 output summary。

## Resident AI Advisory Envelope

`rpg_engine.ai.advisory.ResidentAIAdvisory` 是 resident AI 输出的共享 contract，不是 coordinator、
任务队列或存储服务。V1 envelope 使用 `resident_ai_advisory:v1` schema，严格记录五类
`advisory_type`、target ids、结构化 evidence、finite confidence、freshness、visibility mode、
source assistant、proposed next workflow、provenance 与固定 authority。Workflow 字段只是受限 hint；
authority 永远是 advisory-only / no-direct-writes，所有 fact write、proposal approval、player confirmation、
hidden permission、trusted delta、save authorization、profile escalation、validation bypass 和 commit
capability 都固定为 false。

Normalizer 先执行有界 JSON-safe structural preflight，再使用 Draft 2020-12 schema fail closed；它不
静默裁剪未知/越界输入，也不保留 caller 的可变 collection。Maintenance serializer 只输出 canonical、
有界的 debug representation，不保存 private reasoning。Player serializer 使用独立字段 allowlist，要求
精确 `visibility_mode=player` 和有效 SQLite connection，并通过 Entity/Relationship/Progress access
contracts 分别验证 targets/evidence；hidden、archived、missing、unsupported 或查询失败都采用同一个
generic unavailable 结果，最后才调用通用 hidden redactor 作为 defense-in-depth。以上操作只读且保留
caller transaction ownership；本 contract 不写 Save、Campaign、registry、pending、preflight 或 proposal
state，也不改变 30-60 秒 background scheduling target。

公开 dataclass 不是 validation token：maintenance/player serializer 会重新执行 strict normalization。Player
projection 只保留经权威 access contract 证明的 target/evidence、安全 schema version 与固定 authority；不会
回显可能受 hidden evidence 影响的 confidence、freshness（包括 evidence as-of turn）、source assistant 或
workflow metadata。任何最终
hidden redaction 造成的 allowlist shape 变化都会 fail closed 为同一 generic unavailable 结果。
Evidence、freshness event 与 provenance references 必须使用 canonical prefixed IDs；未知 structural keys 不得
进入异常 path。公开 `to_dict()` 与 serializers 都会拒绝伪造 authority state，不把静默重写当成验证。
Structural preflight 只接受 exact built-in `dict/list`，normalized dataclass collections 必须是 tuple；authority
const 与 as-of integer 使用精确 wire types。Defense-in-depth redaction 只扫描已通过 access contract 的动态
references，不让无关 hidden 文本碰撞固定协议 key。
Schema validation 前只接受精确 built-in scalar types；已知 runtime/derived namespace 不能成为 advisory target。
Defense redaction 只扫描 reference leaf values，validator exception 不保留敏感 cause，同一 reference/as-of 也
不能以多个 evidence kind 重复出现。
Mapping keys 与 values 一样只接受 exact built-in JSON scalars。单个 reference read 失败只 omission 该项；
合法的其他公开 reference 仍可投影。`to_dict()` 完成 strict revalidation 后，player serializer 不重复执行
第二轮完整 schema normalization。
Normalizer 在 structural preflight 后复制 bounded exact JSON snapshot，再对 snapshot 复核并完成 schema/semantic
validation。`rel:`/`clock:` prefix 即使遇到 malformed storage type 也必须走 typed access contract；Progress
references 兼容既有 nested-colon clock ids。Redactor 比较保存调用前 wire snapshot，不能被 in-place mutation 绕过。
Redactor 输出还必须保持 exact `list[str]` 形状，JSON 文本相同的 tuple 也会 fail closed。
对已经 access-contract 验证的结构化 reference 只查询 bounded candidate IDs，并以区分大小写的 canonical ID
精确匹配执行 redaction；不加载全库 hidden names/aliases/text，也不执行 hidden-ID 子串匹配，避免无关 hidden
内容改变公开 reference 的可用性并形成 existence oracle。
Player serializer 还拒绝存在 `entities`、`clocks` 或 `world_settings` TEMP shadow table/view 的连接，
并要求 `main` schema 自身包含权威 `entities`/`clocks` tables，防止 SQLite 名称解析 fallback 到 attached
database 绕过 `main` 事实权威。
Maintenance provenance source ids 只接受 `turn/event/context/memory/advisory/trace/candidate` 安全 namespace；
bare authority/approval/confirmation 只允许 canonical 顶层 authority object。Prefix dispatch 优先于冲突的
storage type，structural traversal 的并发 mutation 异常不会保留原始 cause/message。
Clock reference syntax 精确复用 Progress Access Contract 的 `[A-Za-z0-9_.:-]+` 后缀；candidate/prompt/hidden
等控制面 namespace 不能成为 target/entity evidence。Player projection 在 revalidation 后只读取 canonical dict
snapshot，并对 rule/world/setting prefix 执行 storage type 核验。

### Representative Advisory Adapters

`rpg_engine.ai.advisory_adapters` 提供两个 bounded、纯转换的 companion adapter。Internal Intent Review
在 Kernel arbitration/binding 与 route selection 完成后，把最终 `entity_bindings` 映射为
`intent_recognition` advisory；`source_assistant` 只表示 internal helper 是 producer，targets 表示最终
Kernel-selected binding，不表示 AI 独立确认事实。该 optional object 只存在于 `AIIntentRouteResult`，不进入
trace、arbiter、binder、resolver、fallback、preview、pending、confirm、validation 或 commit 输入。

State Audit adapter 只把 maintenance-oriented validation profile 中、已通过 delta-schema stage 的完整
`tick_clocks` id 集合映射为 `progress_management` advisory。提取采用 all-or-none；maintenance dict 只作为
state-audit stage 的 companion artifact，不能出现在 preview/player-turn/response-acceptance profile，也不能
改变 audit risk/status/issues、report ok 或 commit eligibility。

两个 adapter 都只读取 exact helper flags、安全枚举与 canonical access-contract references，最终复用
`normalize_resident_ai_advisory()`。Provenance SHA-256 只覆盖 adapter kind、first-seen targets、confidence/view
等 bounded metadata，不包含 player text、reason、slots、findings、warnings、delta body、provider/model、prompt、
session/message/preflight 或 raw audit。Freshness 固定 unknown，workflow 固定 none；adapter 不接收 connection、
不调用 provider、不写 Save/queue/registry。Semantic/Archivist/reflection/memory/delta/response/turn/plot helpers
保持未迁移，Story 4.6、4.7 与 5.7 的 review/plot/proposal ownership 不变。

### Advisory Review Intake

`rpg_engine.ai.advisory_review` 把一个已经严格 normalization 的 `ResidentAIAdvisory` 与独立、
bounded、明确 kind 的 candidate draft 绑定为 `AdvisoryReviewArtifact`。Envelope 只提供 target、evidence
和 provenance；它本身不是 mutation payload。Artifact 是深度不可变的显式 review evidence，不是 fact、
proposal approval、confirmation、validation proof 或 commit token，也不选择或提升 validation profile。

Intake 只执行只读 preflight：entity/relationship candidate 复用 `validate_content_delta()` 与 access-contract
检查；clock tick 复用 `validate_delta_progress_references()`；alias、memory summary 和 progress definition 在没有
已命名 application owner 时固定不可 application。所有 application owner 都必须在实际写入时从 current facts
重新验证；proposal approval 不能替代 confirmed `TurnProposal`、maintenance validation 或 commit gate。

Review artifact 没有 repository、SQLite table、queue 或 context collector owner。Maintenance/player serializer
只投影 caller 显式传入的 artifact；player projection 复用 Story 4.4 的 SQLite-aware access-contract projection，
对 hidden、missing、archived、TEMP-shadow 或伪造 artifact 统一 fail closed。`rejected`、`stale`、`superseded`
和 `conflict` 只记录 disposition、supersession 与 rollback evidence，永远不是 current facts。Proposal queue 的
create/status/allowed transitions/apply/revert/batch/report 仍完整属于 Story 5.7。

## AI 意图边界

关键模块：

- `intent_router.py`：外层兼容/规则候选/`ActionIntent` facade，负责候选准备、配置和请求元数据。
- `actions/taxonomy.py`：持有 frozen `ActionTaxonomyTerm` / `ActionTaxonomySpec`、规范化匹配规则与
  canonical taxonomy projection/digest；`ActionResolverRegistry` 是全局 version/projection owner。通用
  projection 可保存合法 BCP47-like locale 元数据，但 live executable registry 只接受已有否定、假设和问句
  safety grammar 覆盖的 `zh` / `en` / `ja` / `ko` language family（含兼容的 subtags）；显式 script subtag
  与 term 实际 script 也必须符合对应 grammar，其他 locale 或错标 script 注册 fail closed。
- `actions/slot_contract.py`：持有 frozen、JSON-safe 的 slot / requirement-group / resolved contract；
  `ActionResolverSpec` 在构造时把 legacy `required_options` 单向归一化，`ActionResolverRegistry` 在注册前验证
  确定性 slot projection/digest。九个 builtin resolver 是 required、alias、binding type、entity type、
  AI-fillable、confirmation 与 group rule 的 owner。
- Router 的否定、假设和问句 policy 按 winning canonical term 的 locale family 分派，并共享 Unicode sentence-terminal
  归一化；不得用较窄的平行 script regex 或 surface-specific 句尾字符表重新判断 locale。
- `intent_manifest.py`：发布 manifest v4、完整 contract digest、taxonomy v1 projection、versioned safety
  projection 与 resolver-owned slot/group projection；group wire 包含 `cardinality` / `binding_rule`，slot/group
  metadata 变化都会旋转 manifest digest。
- `ai_intent/safety_contract.py`：唯一持有 safety vocabulary v1、canonical digest、compatibility policy、
  typed contract error 与安全公开投影。
- `ai_intent/external.py`：共享 external ingress；先验证 contract identity，再严格验证 raw safety token，
  最后才进入 schema、registry 与 tolerant domain normalization。
- `ai_intent/router.py`：`AIIntentRouter`，实际 AI 意图链协调者。
- `ai_intent/adapters.py`：外部候选适配。
- `ai_intent/arbiter.py`：候选裁决。
- `ai_intent/binder.py`：只从 active registry 的 resolved slot contract 读取 accepted slots、alias、binding type、
  required/group cardinality 与 confirmation policy，再用当前Save SQLite的active-only lifecycle与player-view SQL
  完成action binding；普通query/read仍使用各自non-archived access contract。
- `ai_intent/slot_contract.py`：旧 import path 的派生只读 adapter/re-export，不再拥有按 action 手工维护的 table。
- `ai_intent/internal_review.py`：内部复核。
- `ai_intent/risk.py`：风险判断。
- `preflight_cache.py`：advisory internal intent review cache。

设计约束：

- AI 可以提供候选和解释，不能直接提交状态。
- External candidate 可整体省略 contract 进入显式 `legacy_unversioned` compatibility window；一旦提供
  contract，四个 identity 字段必须完整匹配当前 manifest v4 / safety v1。Taxonomy v1 整体进入 manifest
  digest，不扩展 candidate identity envelope；未知 safety token fail closed，
  compatibility 不能把它放行。
- Contract match 只产生 bounded `matched | legacy_unversioned` validation evidence，不提升 route、hidden、
  confirmation、proposal、validation 或 commit authority。
- Direct Python/Runtime/SaveManager 传播 `ExternalIntentContractError(ValueError)`；只有 MCP、V1 CLI 与
  legacy `context build` command boundary 将它投影为固定、脱敏的 public error detail。
- `external_primary` 只表示 internal intent AI 显式 `off` 时通过 Kernel 校验的 route proposal；它不授予
  fact、hidden、player confirmation、proposal approval、validation 或 commit authority。
- 规则候选、AI 候选和外部候选必须保留来源信息，便于审计与回放。
- Routed `ActionIntent` 的 keyword mismatch 只作诊断；direct low-level `preview_action` 的 mismatch guard
  仍是硬边界，不能由 caller-supplied context/source 绕过。
- `candidate_bound` profile 绑定候选身份。
- 平台预热常用 `message_only` profile，正式入口必须重新构建候选并验证身份。
- 澄清循环要防止无限循环和错误提交。
- timeout 是 execution control，不是 route、fact、permission、confirmation 或 commit authority。
- preflight cache 可能包含原始玩家输入、platform/session/message 标识、internal review 和 helper audit，不能作为公开诊断材料提交。
- RPG Engine 负责 provider-side manifest/taxonomy/safety contract 和 shared ingress。Runtime 注入 registry 时，
  deterministic route、binder、internal prompt、manifest 与 active contract validation 必须使用同一实例。
  Hermes 负责消费 manifest、在 mismatch 后 refresh 并重新生成候选；Hermes reconnect、
  next-model-turn barrier 与跨仓 E2E 不由 RPG Engine 6.1 实现。

## 预览、提案与写入链

预览边界不是单个 `preview.py` 文件。核心边界是：

- `actions/base.py` 的 `ActionResolverSpec` 合约；per-action taxonomy 是 frozen canonical metadata，旧
  `keywords` / `semantic_labels` / `inference_priority` 只保留只读兼容投影。
- `GMRuntime.preview_action()` 的编排。
- 各 `actions/*` 模块对具体动作的解析和 delta 构造。
- `preview.py` 的复用渲染 / delta helper。
- `proposal.py` 的 `TurnProposal`，承载 pending/approved 状态、确认、来源和 intent contract。

写入链由以下模块共同组成：

- `proposal.py`
- `delta_schema.py`
- `validation_pipeline.py`
- `commit_service.py`
- `unit_of_work.py`
- `write_guard.py`
- `db.py`
- `migrations.py`

架构原则：

- 玩家动作先生成 pending proposal，确认后才提交。
- 所有状态写入必须先通过预览、提案确认和校验。
- 事件流和当前事实表共同支持审计与查询。
- 写入错误应尽可能在提交前暴露。

## 上下文链路

上下文链路负责把 Save DB 中的事实转换为 AI/玩家可见材料：

- `context_builder.py`：主构建入口。
- `context/collectors.py`：事实收集，包括 entities、relationships、progress/clocks、routes、
  palettes、discovery states、world settings、recent events、memory summaries 和 advisory-only
  plot progression signals。
- `context/diagnostics.py`：从最终 visibility-safe collection、budget 和 access-contract evidence
  生成有界、确定性、advisory-only 的预算与结构质量诊断。
- `context/resolution.py`：引用和冲突解析。
- `context/budget.py`：上下文预算。
- `context/semantic.py`：语义建议。
- `context/rendering.py` 和 `render.py`：可读输出。
- `visibility.py` 和 `context_audit.py`：隐藏信息边界和审计。

任何新增上下文来源都必须标明 visibility，不能把 hidden / GM-only 内容泄露到玩家视图、
FTS/search、scene output、普通 query、snapshots、cards 或 onboarding。最终 render redaction
只能作为防御层；玩家派生 read model 应在 collection / projection 阶段排除 player-hidden facts。
Relationship / progress context 必须复用 `relationship_access.py` 和 `progress_access.py` 的 access
contract，不直接依赖表结构细节。Plot progression signal 只能作为可见 context evidence / advisory input，
不能要求 storylet、自动导演命令或状态写入。

Context quality diagnostics 只扩展既有 `ContextBuildResult.budget` 与 `completeness`：section 选择决策写入
`budget.decisions`，结构 warning 写入 `completeness.quality_diagnostics`，高价值预算遗漏只追加到
`completeness.missing_signal_evidence`。诊断必须消费当前 view 已过滤且完成 budget reconciliation 的 evidence，
复用 relationship/progress access contracts 与 memory freshness evidence；alias 检查仅对已过滤 entity ids 做一次
canonical `main.aliases` 批量读取。warnings 不评价文笔、剧情或题材品味，也不拥有事实、确认、proposal、clock tick、
save 或 commit authority；诊断失败只能降级为安全的 unavailable evidence，不能改变 `allow_proceed`、confidence、
missing-required 或 confirmation decision。Player hidden-only 与真正 absent 输入必须产生同样的通用有界信号，最终
redaction 仍只是 defense-in-depth。Context audit DDL/DML 必须显式绑定 `main.context_runs` / `main.context_items`，
TEMP 同名表不能劫持最终 result、item token evidence 或 audit upsert。

Memory summary context 只能作为 derived context evidence。`memory_summaries` 记录 source turns/events、
summary type、visibility mode、freshness/staleness metadata 和 derived authority；当它与当前 SQLite
facts 或 access contract 结果不一致时，权威事实优先，summary 只能被标记 stale、从 context 省略或进入
advisory review。memory rebuild、reports 和 projection health 不得阻塞 ordinary gameplay commit；缺失
summary refresh 时，context assembly 应继续使用 recent events、snapshots 或 lower-quality fallback。memory
projection 非 clean、早于 provenance migration、与 current turn 错位或无法验证时，旧 summaries 必须 fail
closed；direct rebuild 只可在同一 turn snapshot 内标 clean。Player lookup/report 只能输出已解析、当前 view
可读的 source ids、allowlisted freshness evidence 和固定 derived-context authority。事实维护入口（包括 save
patch）必须在同一事务中把 memory projection 标 dirty；缺失的 memory projection state 也必须从 dirty 开始，
不能由通用初始化伪装为 clean。Player memory row 必须从字段 allowlist 重建，source turn 的 location refs、
validity window、来源数量上限和返回前 projection snapshot 复核均采用 fail-closed 语义。Context render 必须
在最终返回前对 generation 做 revision-aware gate；若 collection、section、plot signal、budget 或 item evidence
期间 generation 改变，必须统一移除 memory-derived section/signal 并有界重建结果；重新生成的 omission evidence
必须直接绑定检测到的 generation snapshot，不能先查询旧 omission 再把它标成新 generation。Player omitted-item
边界必须把 maintenance/hidden rows 合并为单一 generic signal，不能泄露数量、类型、标题或原始 id。Projection `updated_at`
通常按单调 generation token 分配；refresh 只能以 `refreshing + generation` CAS 到 clean，期间出现的新 dirty
generation 不得覆盖。同一 campaign/projection 的 publication 必须跨线程/进程序列化，失去 ownership 的旧 refresher
不能在新 generation 之后覆盖数据库 rows 或文件 artifacts；最终 report 还必须按最终 effective health 重写 item / refreshed
结论。publication lock 必须有界等待并返回结构化失败；events outbox append 与完整 `events_jsonl` rewrite 使用同一把 target lock。
所有 projection-state/outbox SQL 必须显式绑定 `main`，TEMP 同名表不能劫持 refresh、status 或 queue。`projection_state`
metadata 与 `outbox` availability 独立：缺失 queue 仍必须允许 fact transaction 将 memory 标 dirty，queue health 另行报告 missing。
Generation token 在可解析 UTC timestamp 后携带 opaque nonce，避免时钟回拨或最大值
repair 复用历史 owner token。若损坏的最大 timestamp 已无法递增，allocator 必须产生不同 token、保持
projection non-clean，并且绝不能阻断 authoritative fact commit；事实事务内的 projection metadata 写入使用
savepoint 隔离并保留 caller transaction 语义；helper 自己开启事务时必须自行 commit，普通 Python/SQLite callback
失败统一清理并返回 false。schema/trigger/constraint 失败只能使 projection stale，不得回滚 turn 或 save patch。Direct
memory rebuild 必须先取得 `refreshing + generation` 所有权，table/report 失败或完成 CAS 丢失时不得报告成功。
Direct player report 必须在同一 projection snapshot 上组装并原子发布，snapshot 改变时只留下 generic unavailable report。GM/maintenance
只放宽 hidden-content 权限，
仍必须消费字段 allowlist 与 JSON-safe 动态类型。Subject summary 的 evidence subject 必须与 row subject 一致，
`subject_updated_turn_id` 必须对账 authoritative entity。Validity window 独立于 freshness provenance：未来
`valid_to` 可有效，未来 `valid_from` 表示尚未生效；evidence 中的 bounds 必须与 stored bounds（包括 absence）精确一致，
但 bounds 或与 bound 相同的 scalar turn 本身不能单独证明 freshness。Trusted rebuild authority 必须精确等于 canonical
derived-context object，额外键、非有限 JSON 常量或 numeric pseudo-booleans 均 fail closed。
Memory schema/migration 只操作 `main`，拒绝 TEMP shadow、大小写 trigger 绕过、数字伪 boolean authority defaults、
非 canonical FK action 和缺失的 `(kind, subject_id)` lookup index；`main.schema_migrations` 不能被 TEMP ledger
替代，SQL constraint 检查必须忽略 quoted/comment-only text 并拒绝 executable CHECK/COLLATE。helper backfill 必须先验证
全部现有列，再在同一 savepoint 内原子添加缺列和 canonical index。

## 数据与包边界

- Campaign Package：世界、规则、内容、capabilities、smoke tests 和作者材料。
- Save Package：当前存档、SQLite、事件、投影、snapshots、cards/memory 和存档元数据。
- Workspace/runtime state：`.aigm/game-session-bindings.json`、`.aigm/save-registry.json`、
  `.aigm/pending-*` 等平台绑定和运行索引。
- Packaged resources：迁移、schema、示例、evals。
- `rp/`：剧情包/剧本材料。公开仓库只应推当前剧情包本体，不推存档。

## 已知风险

- 旧文档中的设计版本较多，容易和当前代码事实混淆。
- AI 意图链、平台预热链、旧规则路由之间存在兼容逻辑，需要保持分层清晰。
- `.aigm/`、`saves/`、Save Package、玩家 SQLite、platform session 和 preflight cache 属于敏感运行数据。
- 后续增加真正协调层时，不能让 `GMRuntime` 继续膨胀为所有职责的集合。
