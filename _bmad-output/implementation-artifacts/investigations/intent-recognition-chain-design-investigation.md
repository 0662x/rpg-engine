# 调查：Intent Recognition 全链路设计合理性

## Hand-off Brief

完整审查表明 trust、binding、preview、validation、player confirmation、commit 与 preflight identity/CAS 的安全核心合理且测试充分，不需要推倒重写。已复现缺陷是 route taxonomy drift、unknown safety flag 静默删除并被接受、concurrent confirm duplicate-success API 语义及 provider audit 无法独立重建 route；slot 多真源、pending supersede、preflight consumer purpose、prompt-only sequencing 与 self-improvement evidence gate 分别属于设计债务、产品选择或推断风险，不能混称为同等级 confirmed defect。修复必须按 Kernel contract、SaveManager session、AIIntentRouter、RPG Engine audit、Hermes consumer 和跨仓 integration 分 owner 推进，未来 coordinator 只能收拢编排与 trace。

## Case Info

| Field | Value |
| --- | --- |
| Ticket | N/A |
| Date opened | 2026-07-12 |
| Status | Concluded |
| System | RPG Engine main；Python/SQLite；CLI/MCP/platform/Hermes caller intent pipeline |
| Evidence sources | canonical intent 文档、源码、测试、版本历史、现有 incident case 与 runtime trace |

## Problem Statement

用户希望仔细审查整个意图识别链条，包括传入、处理、核验和最终状态边界，判断当前设计是否合理，并识别设计不良、逻辑不清、重复权威、故障降级或可维护性问题。

本调查是 area exploration，不预设“当前设计一定有问题”。审查范围包括：

- external caller / GM skill 如何读取 `intent_manifest` 并生成 low-trust candidate；
- MCP、CLI、platform ingress 如何转发 text、candidate、identity 和 preflight metadata；
- candidate schema/normalization、deterministic rules 与 candidate preparation；
- internal AI live/preflight review、timeout/unavailable/off mode；
- arbiter、risk、binding、route adoption 和 fallback；
- resolver/preview/validation、pending clarification/action、player confirmation 与 commit；
- trace/audit/player-visible output 是否足以解释结果；
- 跨层 contract、测试与文档是否存在重复或漂移。

不在本调查范围：直接实施修复、改变 Campaign 内容、叙事质量评价、模型供应商性能比较。

## Evidence Inventory

| Source | Status | Notes |
| --- | --- | --- |
| `docs/ai-intent-chain.md` | Available | canonical authority、mode matrix、preflight 与 target coordinator |
| `rpg_engine/ai_intent/`、`rpg_engine/intent_router.py` | Available | normalization、rules、internal review、arbiter、risk/binding |
| `rpg_engine/save_manager.py`、Runtime/ContextBuilder | Available | player turn、pending、confirm、preview/validation 边界 |
| `rpg_engine/mcp_adapter.py`、CLI/platform surfaces | Available | ingress/profile/identity forwarding |
| intent/preflight/player/MCP tests | Available | contract 与 regression evidence；focused runs 有重叠，不把各组数量相加当作唯一测试总数 |
| external GM skill 与 prompt | Available | sequencing、field consumption、static drift 与 self-improvement 已追踪 |
| 真实运行 trace | Available | mismatch、timeout、off、preflight、pending/confirm 并发代表路径已重放 |
| 版本历史 | Available | 2026-07-03 至 07-12 intent 相关路径至少约 +12,190/-441 行；近期变更密集 |
| 动态重放与并发实证 | Available | temporary Save 与 focused tests 已完成 |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --- | --- | --- | --- |
| 1 | 绘制 end-to-end authority、I/O 与状态转换图 | High | Done | authority/state map 与 replay 已完成 |
| 2 | 核对 external consumer 与 manifest 的真实 contract | High | Done | taxonomy drift、sequencing boundary 与 provenance gap 已定位 |
| 3 | 审查 candidate preparation / rules / internal / arbiter 重复与优先级 | High | Done | actual drift/unknown safety confirmed；trace inconsistency refuted |
| 4 | 审查 off/unavailable/timeout/preflight 的状态机 | High | Done | safety成立；purpose/liveness ownership 已定位 |
| 5 | 审查 binding → preview → pending → confirm → commit | High | Done | fact idempotency成立；pending claim/supersede缺口已定位 |
| 6 | 审查 MCP/CLI/platform 参数与 profile parity | Medium | Done | profile差异与重复 clarification ownership 已区分 |
| 7 | 建立测试覆盖矩阵与缺口 | High | Done | provider strong；consumer/concurrency/real transport gaps confirmed |
| 8 | 核对历史架构意图与当前实现偏差 | Medium | Done | baseline debt、后续暴露路径和未落实 warning 已追踪 |
| 9 | 形成设计优点、缺陷、严重度与重构边界 | High | Done | owner/minimal boundary/do-not-change 已记录 |

## Timeline of Events

| Time | Event | Source | Confidence |
| --- | --- | --- | --- |
| 2026-07-12 | mode mismatch incident 证明 external query candidate 可与 canonical routine rules 冲突 | `intent-mode-mismatch-mcp-call-investigation.md` | Confirmed |
| 2026-07-12 | 用户要求从单点事故升级为全 intent chain 设计审查 | 当前请求 | Confirmed |

## Confirmed Findings

### Finding 1: 权威边界在 canonical contract 中是明确的

**Evidence:** `docs/ai-intent-chain.md:12` 声明 “AI proposes. Kernel verifies. Player confirms. Engine commits.”；`docs/ai-intent-chain.md:64`–`70` 分离 external、internal、rules、arbiter、binding/preview 与 validation/commit 权限。

**Detail:** 设计审查应验证实现是否忠实保持该边界，而不是重新讨论 external/internal AI 是否应拥有 commit authority。

### Finding 2: 主链入口与提交门可定位

**Evidence:** canonical flow 从 `player_turn` 经 candidate preparation、rules/internal router、binding、preview/pending 到 `player_confirm`（`docs/ai-intent-chain.md:19`–`25`）；代码入口为 `SaveManager.player_turn()`（`rpg_engine/save_manager.py:431`）与 `SaveManager.player_confirm()`（`rpg_engine/save_manager.py:613`）。

**Detail:** 这为 Outcome 2–4 的反向 caller trace 与状态机核验提供稳定 stronghold。

### Finding 3: Machine manifest 与 deterministic router 的 action taxonomy 已发生实际漂移

**Evidence:** routine resolver keywords 不含“巡视/巡逻”（`rpg_engine/actions/routine.py:257`），但 `ROUTINE_INTENT_TERMS` 包含两者（`rpg_engine/intent_router.py:67`）；manifest 从 resolver keywords 导出（`rpg_engine/intent_manifest.py:54`），P0 acceptance 又要求巡视文本路由为 routine（`tests/test_p0_stop_loss_acceptance.py:68`）。runtime introspection 还显示 routine router-only 20 项、resolver-only 8 项。

**Detail:** 外部 consumer 严格读取 live manifest 也无法得到当前 deterministic route 的完整 exact-term contract。required slots 还由 resolver spec、`ACTION_REQUIRED_SLOTS` 和 binder 合并维护，但当前只证明 ownership split，未复现错误 binding 或 manifest 行为；blocking safety allowlist 虽有两份，但当前集合一致，尚未漂移。

### Finding 4: 未知 safety flag 被 schema 接受、normalizer 静默删除，并可在 off mode 被采用

**Evidence:** wire schema 仅要求 safety flag 为 string（`rpg_engine/resources/schemas/intent_candidate.schema.json:38`）；normalizer 过滤非 allowlist 项（`rpg_engine/ai_intent/normalization.py:149`）。focused probe 中 `safety_flags=["new_danger"]` schema 零错误，normalize 后为空，最终 `status=accepted, source=external_primary`。

**Detail:** 这是明确的 strict-validation/future-compatibility fail-open contract gap。作为反证，unknown action 虽同样通过 schema 并被归一化为 `None/unresolved`，但后续 arbiter 会 block；该路径安全，只是错误信息失真。由于 external flags 是可省略的低信任自述，目前尚未证明 unknown flag 能绕过 Kernel 自己识别的危险行为并到达 unsafe commit；其 security/P1 严重度需由 threat model 和 consequence probe 决定。

### Finding 5: Route 多表示尚未造成可复现的 authority/trace 不一致

**Evidence:** 9 个 focused route tests 与 8 个 subtests 覆盖 external-primary、kernel safety block、consensus unavailable/timeout、ordinary mismatch 与 characterization snapshots，均通过。

**Detail:** 多表示仍是维护债务候选，但当前 adapter/selected outcome/trace tests 能维持一致，不能仅凭类型数量判为已发生缺陷。

### Finding 6: Workspace pending 行为已确认；duplicate-success API 缺口已复现

**Evidence:** `player_turn()` 在处理任何新输入前清除 pending action（`rpg_engine/save_manager.py:453`）。temporary Save probe 中 ready rest pending 被后续只读 query 撤销，旧 session 无法确认。并发 barrier probe 强制两路 confirm 读取同一 pending 后，两路均返回 `committed`，但 SQLite 只增加一个 turn/event。

**Detail:** 底层 command id/expected turn 保住事实幂等，没有双写；但 API confirmation claim 不是 exactly-once。两位 caller 都可能据成功响应继续叙事或执行外围副作用属于由返回语义推导出的风险，尚未做外围系统实证。单 pending 的 supersede 行为本身可能是产品选择；已确认的缺口是当前没有按 save/session/caller 分区，也未在公开调用 contract 中充分突出。

### Finding 7: Clarification 与 unavailable mismatch 有恢复边，但把 caller 错误成本转嫁给玩家

**Evidence:** 古老 `created_at` 的 pending clarification 不会按时间过期；重复原文继续被阻断。但 temporary Save 中 fresh text“执行一次基地巡视”加 routine candidate，即使 internal unavailable 也能进入 `routine/ready`。

**Detail:** “永久死循环”被反证。准确语义是 indefinite-until-fresh-answer：只修正 candidate 而保持同一玩家原文仍被 guard 拒绝，玩家必须改写文本。对真实玩家歧义这是安全设计；对 caller 自己构造错 candidate，则恢复 UX 不合理。

### Finding 8: Preflight 的 single-use 安全正确，但 entry purpose contract 不清

**Evidence:** ready preflight 被 `start_turn` 消费后 DB 变为 `used`；同一 preflight 再用于正式 preview 时只能 live review。下游 routing 抛错后 used 状态也不回滚（`rpg_engine/preflight_cache.py:617`）。

**Detail:** 没有安全绕过，但 diagnostic/preview/player flow 会竞争同一份 single-use evidence，造成可观察的额外延迟与 liveness 成本。canonical 文档把 `start_turn` 定位为诊断入口，但未明确禁止调用方显式让它消费 authoritative preflight；因此当前属于用途 contract mismatch，最终行为仍需产品/架构决定。

### Finding 9: Consumer sequencing 是弱 contract，但不是本次“巡视”误判的直接原因

**Evidence:** Hermes message 9383 确实把 manifest 和另一个 query 的 player_turn 预序列化在同一 batch；但“巡视一下我的基地”位于后续独立 message 9390，上一轮 manifest result 已在上下文中。incident candidate reason 是模型主动解释为只读 query。

**Detail:** 协议无法强制 next-model-turn sequencing 是 confirmed design weakness；将本次 incident 直接归因于同 batch 则被反证。更直接的结构问题是 live manifest 自身没有“巡视”taxonomy。

### Finding 10: Audit explainability gap 已确认；self-improvement 增加 Deduced poisoning risk

**Evidence:** provider audit 将 candidate 摘要为 object/key_count，无法独立恢复 external query、rules routine 或 caller reason（`rpg_engine/mcp_adapter.py:1841`）。旧 `engine-pitfalls` 在 incident 后被加载并诱发 craft 误诊；background review fork 无 terminal/reproduction 工具，写门也不要求 domain evidence（`../hermes-agent/agent/background_review.py:784`）。这证明机制允许无证据技术结论被固化，但不能在缺少 old/new payload 时证明某一句已经被实际写入。

**Detail:** stale skill 没有导致初次 query candidate，但其 04:29 load 与后续 craft 误诊的顺序关系已确认。background review 是否把同一具体句子写成 durable skill claim，因缺少完整 old/new patch payload，只能列为 Deduced risk，不能与前述 trace 同等级 Confirmed。

## Deduced Conclusions

### Deduction 1: “原则合理”与“实现链条合理”必须分开评价

**Based on:** Finding 1–2 与既有 mismatch incident。

**Reasoning:** authority 原则清晰并不能自动保证 consumer sequencing、候选分类、mode degradation、preflight identity、binding 或 pending 状态在实现中保持单一权威和可解释性。

**Conclusion:** 后续报告将分别给出原则层、contract 层、状态机层、实现耦合层和可观测性层评价，避免用安全口号掩盖逻辑复杂度。

### Deduction 2: 当前设计是“安全核心合理，编排与合同所有权不够合理”

**Based on:** Finding 3–10。

**Reasoning:** no-mutation、confirmation、binding、validation、preflight identity/CAS 经 focused tests 和 probes 保持成立；失败集中在分类语义多真源、边界外 consumer、恢复/并发语义和诊断证据，而不是事实 authority。

**Conclusion:** 不应重写安全核心或降低 fail-closed；应收敛 taxonomy/contract ownership、明确 pending/preflight state ownership，并把 consumer 与 audit 纳入可执行协议。

## Hypothesized Paths

### Hypothesis 1: 总体 trust/commit 架构合理，但 route proposal 链存在重复分类与 contract 漂移

**Status:** Confirmed

**Theory:** external AI、deterministic rules 与 internal AI 三路候选能提升安全性和可审计性，但 manifest、static skill、rules keywords、internal prompt 和测试都表达部分语义，可能形成多份 route contract。

**Supporting indicators:** 已发生 external caller 在 manifest 已可见时生成与当前项目 route contract 不一致的 query candidate 事件；现有 telemetry 不能证明它忽略了哪个具体字段，也不能单独确定玩家主观意图。

**Would confirm:** 发现相同 intent semantics 在多个文件独立维护，且没有生成/一致性测试。

**Would refute:** 所有 consumer 语义均由 manifest/registry 生成，静态文档只引用且有 parity gate。

**Resolution:** routine/craft taxonomy、required slot ownership 与 prompt projection 已确认不一致；safety allowlist 当前仅重复、未漂移。

### Hypothesis 2: `off`、`unavailable`、timeout、preflight hit/miss 的组合状态过多，安全但 liveness 与可解释性不足

**Status:** Confirmed（局部）

**Theory:** fail-closed 防止错误动作，但 internal unavailable 与 external/rules disagreement 可能形成无法由同一玩家回答打破的 clarification loop。

**Supporting indicators:** 既有 incident 在 internal unavailable 下稳定进入 mode mismatch clarification。

**Would confirm:** 状态转换表存在重复 clarification、无 recovery token/明确重试条件，或 caller 无法知道怎样生成可收敛的新输入。

**Would refute:** 每个失败状态都有唯一、可执行且测试覆盖的恢复边。

**Resolution:** fail-closed authority 正确，但 preflight purpose competition、clarification fresh-answer requirement 与 pending supersede 形成可观察 liveness/UX 成本；“完全无恢复边”被反证。

### Hypothesis 3: Intent orchestration 分散在 SaveManager、Runtime、ContextBuilder、preflight 和 adapters 中，可能产生参数 bundling 与生命周期重复

**Status:** Open

**Theory:** coordinator 尚未落地，paving work 可能留下跨模块参数透传、cache identity 与 route selection 分散的问题。

**Supporting indicators:** project context 明确说明真正的 `IntentCoordinator` 尚未实现；canonical 文档列出多个 paving components。

**Would confirm:** 同一 mode/config/identity/candidate 在多层重复构造、默认或核验，并存在 parity 测试负担。

**Would refute:** 各层均为纯薄转发，单一 service 完整拥有状态机和默认值。

**Resolution:** Outcome 3 已确认分散状态的具体症状；是否由 coordinator 收敛、如何拆分仍待 Outcome 4 source ownership trace。

### Hypothesis 4: 安全边界测试较强，但 consumer contract、可观测性和恢复性测试不足

**Status:** Confirmed

**Theory:** provider-side no-mutation/confirmation tests 充足，但 external tool ordering、manifest field consumption、trace explanation 与 unavailable recovery 未形成端到端 contract gate。

**Supporting indicators:** exact incident 通过现有 kernel tests，却仍在真实 caller 发生。

**Would confirm:** 测试矩阵显示 kernel unit/integration 密集，而 consumer transcript/order 与跨进程恢复缺失。

**Would refute:** 已有 exact end-to-end tests 覆盖 consumer → manifest → candidate → player_turn → confirmation。

**Resolution:** provider/platform tests 充足，但真实 Hermes→FastMCP sequencing、manifest consumption、pending concurrent claim 与可独立重建 route 的 audit tests 缺失。

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | --- | --- |
| 2026-07-01 旧版本是否曾把巡视判为 craft | 只影响历史 bug claim 真伪，不影响当前设计结论 | 对历史 checkout 做 isolated replay |
| Background review 每次 skill patch 的完整 old/new payload | 无法确认哪条具体 durable claim 被强化；当前只能确认 skill load 与后续误诊顺序 | 为未来 skill patch 保存安全 diff provenance |
| 多进程而非多线程 concurrent confirm | 可能补充 crash/lock 细节，不改变已确认的 duplicate-success API 语义 | 新 story 中增加 subprocess barrier test |
| Cross-repo E2E 的 CI owner | 影响落地位置，不影响确认存在组合测试断层 | Correct Course / planning decision |
| Unknown safety 的 threat model 与 consequence probe | 决定它是 P1 security defect，还是 strict-validation/future-compatibility defect | 构造 Kernel 已知危险语义、unknown/new flag、off/consensus 与 preview/commit 边界矩阵 |
| Canonical taxonomy 的最终 owner | drift 已确认，但不能仅凭调查决定由 resolver registry 还是独立 versioned taxonomy contract 持有 | Correct Course / architecture decision |

## Source Code Trace

| Issue | Error origin | Trigger / condition | Source owner | Depth |
| --- | --- | --- | --- | --- |
| Taxonomy drift | `rpg_engine/intent_router.py:67`、`rpg_engine/actions/routine.py:257`、`rpg_engine/intent_manifest.py:54` | 词项仅存在 router hardcoded terms；manifest/internal/external consumer 看见不同 hints | Owner 待规划：resolver registry 或独立 versioned taxonomy contract | Cross-module |
| Slot ownership split | `rpg_engine/ai_intent/slot_contract.py:9`、`rpg_engine/ai_intent/binder.py:294`、`rpg_engine/intent_manifest.py:114` | resolver、parallel tables、manifest any-of 特例分别维护 required/alias/type/confirmation；尚未复现错误行为 | Owner/metadata shape 待架构决定 | Cross-module design debt |
| Unknown safety fail-open | `intent_candidate.schema.json:38` → `external.py:11` → `normalization.py:149` → `arbiter.py:199` | unknown string 通过 schema、被静默删除，off+external 可 accepted | External candidate trust-boundary validation | Cross-module |
| Pending supersede | `rpg_engine/save_manager.py:453` | 新 `player_turn` 在替代状态形成前无条件清除 workspace pending | `SaveManager` pending session owner | Local behavior / cross-entry impact |
| Duplicate confirm success | `save_manager.py:623` → `commit_service.py:213` → `unit_of_work.py:34` | 并发 caller 同读 pending；底层事实幂等但两路均报告 committed | SaveManager atomic claim + CommitService replay classification | Cross-module |
| Clarification split | `save_manager.py:454` 与 `mcp_adapter.py:1095` | persisted player clarification 和 MCP in-memory guard 的 freshness/expiry 不同 | SaveManager canonical clarification session | Cross-module |
| Preflight purpose | `ai_intent/router.py:127`、`runtime.py:934`、`context_builder.py:334` | 任意 entry 只要带 identity 即消费 single-use review；无 consumer purpose | AIIntentRouter/cache claim + Runtime entry semantics | Cross-module |
| Consumer sequencing | AI prompt/GM skill → Hermes tool batch executor | manifest/player_turn data dependency只由 prompt表达，executor只管并发顺序 | Hermes consumer orchestration | Cross-repo |
| Audit explainability | `rpg_engine/mcp_adapter.py:1782`–`1908` | candidate整体摘要，route failure无法仅凭 provider audit重建 | RPG Engine MCP audit contract | Local |
| Self-improvement poisoning | `hermes-agent/agent/background_review.py:171`、`skill_manager_tool.py:382` | active patch bias + 无 domain evidence/reproduction gate | Hermes background review / skill manager | Cross-module |
| Real E2E gap | FakeFastMCP/mock serve/fixture transcript tests | 无真实 Hermes client→stdio FastMCP→next model turn→player_turn gate | Shared integration harness | Cross-repo |

### Ownership Boundary

未来 `IntentCoordinator` 只能收拢 config、request meta、candidate preparation、router invocation 和 versioned trace（`docs/ai-intent-chain.md:392`）。它不得接管 `player_confirm`、MCP/platform gate、arbiter、binder、resolver、validation 或 commit；因此 pending/confirm 与 taxonomy/trust validation 必须在各自 canonical owner 内修复。

## Final Conclusion

**Confidence:** High for confirmed behavior、current module boundaries 与 dynamic reproduction；Medium for final ownership、severity 与 remaining product choices

当前设计不是整体不合理：trust、事实、确认、validation 和 preflight identity/CAS 边界合理且测试强。已复现的实现/contract 缺陷是 route taxonomy drift、unknown safety 静默删除并接受、concurrent confirm duplicate-success 与 provider audit route reconstruction gap。slot ownership、pending supersede、preflight purpose、prompt-only sequencing 和 self-improvement evidence gate 是需要规划的设计债务、产品选择或 Deduced risk。多 route 表示暂未造成实际 authority inconsistency，不应仅为简化而大改。

## Recommended Next Steps

### Fix direction

调查阶段不修改代码。最小合理方向：

1. **High-priority trust-boundary：** external boundary 对 unknown safety flag strict fail-closed；schema、normalizer、arbiter 使用同一 versioned vocabulary parity gate。是否定为 security P1，需先完成 threat model/consequence probe，并设计 rolling-upgrade 兼容策略。
2. **High-priority taxonomy：** 由 planning 选定唯一、版本化的 lexical taxonomy owner；router 只保留 composite/entity/context grammar；manifest 与 internal prompt 从同一 source 投影。
3. **P1/P2 session semantics：** SaveManager 增加显式 compare-and-supersede 与 atomic confirmation claim；CommitService 区分 fresh commit 和 idempotent replay。
4. **P2 preflight：** IntentRequestMeta 增加 internal consumer purpose；由 planning 决定 diagnostic `start_turn` 是完全不消费，还是只在显式 opt-in 时消费 authoritative single-use evidence。
5. **P2 consumer/audit：** Hermes 使用 next-model-turn manifest barrier；audit 只增加 allowlisted normalized route metadata，不记录 raw slots/reason/hidden context。
6. **P2 self-improvement/E2E：** technical bug claim 需要 evidence level；用 scripted model + temporary Save 建立真实 stdio 跨仓 contract test。

### Diagnostic

不需要无边界扩大诊断范围。实施前保留四项 focused diagnostics：unknown safety threat/consequence 与 version-skew matrix、subprocess concurrent confirm（包含 commit 后 clear 前崩溃窗口）、真实 stdio consumer ordering/audit reconstruction、manifest version/digest stale check。产品选择应进入 AC，不应以“缺证据”为由由开发者自行决定。

## Reproduction Plan

已完成 temporary Save / read-only verification：query、routine、consensus mismatch、internal timeout/unavailable、explicit off、preflight hit/used/late、pending supersede、clarification recovery、concurrent confirm。后续每个 story 必须重跑其受影响路径，并保持 source Campaign、formal Saves、正式 registry 不变。

## Side Findings

- 既有 incident case 可作为一条 failure trace，但不能代表整体架构质量。

> 以下 Follow-up 保留调查演进和 refutation 记录。凡其中的 `Open`、`Missing`、`Partial`、待 Outcome 3/4 等阶段状态，均为历史快照；当前权威状态以文首 Confirmed Findings、Missing Evidence、Final Conclusion 与 Final Handoff 为准。

## Follow-up: 2026-07-12

### New Evidence

- 核心链实际维护 `LegacyRuleRoute → IntentCandidate → BoundIntent → ConsensusDecision → ConsensusRouteAdoption → RouteOutcome → ActionIntent` 多个相邻表示，并跨 adapter/trace 复制字段（`rpg_engine/intent_router.py:121`；`rpg_engine/ai_intent/types.py:19`；`rpg_engine/ai_intent/adapters.py:15`）。
- action semantics 同时存在 resolver registry keywords、`intent_router.py` 顶层词表和逐 action inference；slot required、blocking safety flags 也存在多个维护点（`rpg_engine/intent_router.py:67`；`rpg_engine/ai_intent/slot_contract.py:78`；`rpg_engine/ai_intent/risk.py:26`；`rpg_engine/ai_intent/arbiter.py:16`）。
- provider safety gates 很完整：preflight single-use CAS、identity/TTL/late-result、binding visibility、proposal/validation、pending identity 与 player confirm 均有明确实现和测试（`rpg_engine/preflight_cache.py:519`；`rpg_engine/save_manager.py:613`；`rpg_engine/validation_pipeline.py:174`）。
- current pending action/clarification 是 workspace 级单文件；任意新 `player_turn` 在 caller identity/route 核验前清除旧 pending action（`rpg_engine/save_manager.py:453`；`rpg_engine/save_manager.py:708`）。
- pending action 有 TTL，但 pending clarification inventory 未发现 TTL/expiry；`player_confirm` 的 pending JSON read→validate→commit→clear 未发现跨进程 CAS/lock 测试。
- MCP `intent_manifest` 与 `player_turn` 是两个独立工具，`player_turn` 不接 manifest version/digest/provenance（`rpg_engine/mcp_adapter.py:1275`；`rpg_engine/mcp_adapter.py:1287`）。Hermes 关闭并发只保证 batch 顺序执行，无法让已序列化的第二个 tool call 使用第一个结果重新生成参数。
- Manifest 提供 `keywords`、`semantic_labels`、`inference_priority`，但 Hermes GM skill 明示摘取字段不包含它们；internal prompt inventory 也只消费部分分类提示（`rpg_engine/intent_manifest.py:65`；`rpg_engine/ai_intent/prompts.py:177`；`../skills/gaming/aigm-kernel-v1-gm/SKILL.md:140`）。
- MCP audit 对 external candidate 仅保留 object/key_count 摘要，结果摘要不保留完整 status、route authority、clarification reason 或 manifest provenance（`rpg_engine/mcp_adapter.py:1790`；`rpg_engine/mcp_adapter.py:1841`）。
- Hermes background self-improvement 对写 skill 有积极偏置，但 fork 无 terminal/reproduction 工具；guard 只覆盖 ownership、read-before-write 与安全扫描，没有 domain evidence gate（`../hermes-agent/agent/background_review.py:171`；`../hermes-agent/agent/background_review.py:784`；`../hermes-agent/tools/skill_manager_tool.py:382`）。
- 静态统计显示主要相关实现与六个核心测试文件约 20,429 行、约 192 个测试入口；2026-07-03 起相关路径历史 churn 约 +12,190/-441 行。该数字只说明规模/变更密度，不直接证明设计质量。

### Evidence Classification

| Category | Status | Outcome 2 说明 |
| --- | --- | --- |
| Canonical authority/docs | Available | 权威原则、mode matrix、preflight/commit contract 可引用 |
| Core source | Available | preparation/rules/internal/arbiter/risk/binder/adoption 已盘点 |
| State machine | Available | preflight、pending、confirm、commit 状态边已列出 |
| Surface parity | Available | MCP/CLI/platform/Hermes consumer 差异已盘点 |
| Tests/evals | Available | provider、platform、preflight、commit 覆盖密集 |
| Real consumer ordering test | Missing | 未发现 live manifest→下一模型轮 candidate→player_turn 测试 |
| Real FastMCP+Hermes E2E | Missing | repository 测试使用 fake/mock surface；未见真实 stdio consumer 组合测试 |
| Concurrent pending/confirm proof | Missing | 未发现跨进程 CAS/lock 设计说明或直接测试 |
| Runtime trace sample set | Partial | 有单一 incident；其余路径待 Outcome 3 重放 |

### Inventory-only Design Questions

以下仍是待验证问题，不是最终 findings：

1. 多份 action/slot/safety contract 是否真的会漂移，还是现有 parity tests 足以约束？
2. 多个 route 表示与兼容 trace 是否必要，还是 coordinator 未落地留下的过渡复杂度？
3. fail-closed unavailable policy 是否在安全与 liveness 之间失衡？
4. workspace 单 pending 是否与产品“一次只允许一个待确认动作”的意图一致，且能否承受多入口并发？
5. message-only preflight 与 candidate-bound review 的不同语义是否对 caller 足够清楚？
6. prompt-only manifest sequencing 是否应升级为 protocol/host state，而非继续依赖 LLM 遵循说明？
7. audit 的脱敏是否过度削弱事故可解释性？

### Backlog Changes

- Outcome 2 inventory 完成；所有设计线程进入 Outcome 3 的 causality/refutation 阶段。
- 新增 focused replay：consumer sequencing、unavailable clarification recovery、start_turn 先消费 preflight、workspace pending concurrency、confirm concurrency、audit reconstruction。

### Updated Conclusion

Evidence perimeter 显示该设计的安全/事实边界不是薄弱点；真正需要审查的是安全机制之上的 orchestration、contract ownership、状态/表示复杂度、并发模型和可解释性。当前不把任何 inventory-only gap 升级为 confirmed defect。

## Follow-up: 2026-07-12 #2

### Outcome 3 Dynamic Evidence

- 主线程 focused gate：20 passed、38 subtests passed，覆盖 manifest、巡视 P0、timeout authority、external-primary trace、pending/no-mutation、preflight late/used、platform AI simulation。
- Core review run：额外 9 个 route tests、8 个 subtests 通过；未发现 route authority/trace 不一致。该组可能与主线程 focused gate 重叠，不计作唯一测试总数。
- State review run：8 个 pending/preflight focused tests、5 个 subtests 及 5 个 authority tests 通过；所有写 probe 均使用 temporary Save。该组同样按执行批次记录，不与其他批次相加推断唯一用例数。
- taxonomy introspection：routine manifest keywords 不含“巡视/巡逻”，router-only 20 项、resolver-only 8 项；internal prompt 又丢弃 manifest keywords/inference priority。
- schema probe：unknown safety flag 被静默清空且 off-mode external-primary accepted；unknown action 被后续 block。
- pending probe：后续 query 撤销前一个 ready pending；concurrent confirm 两路均报告 committed，但数据库只写一次。
- preflight probe：`start_turn` 消费 ready evidence，随后正式 preview 触发一次 live helper；安全结果仍 ready。
- clarification probe：同原文+修正 candidate 不可重试，fresh clarified text 可在 internal unavailable 下收敛为 routine ready。

### Refutation Record

| Hypothesis | Result | Refutation outcome |
| --- | --- | --- |
| 多真源只是表面重复，没有真实 drift | Refuted（taxonomy）/未证实（slot runtime defect） | routine/craft keyword 与 prompt projection 已有实际 drift；required slot 只确认 split ownership，未复现错误行为 |
| 多 route 表示已经造成 authority trace 错误 | Refuted | focused snapshots/authority tests 全绿；保留为低优先设计债务 |
| clarification mismatch 完全无恢复边 | Refuted | fresh player answer 可收敛；同原文 corrected candidate 不可收敛 |
| incident 由 manifest/player_turn 同 batch 直接触发 | Refuted | incident 是后续独立 player_turn，manifest 已在上下文 |
| 完整消费 manifest keywords 即可修复巡视误判 | Refuted | live manifest 本身没有“巡视/巡逻” |
| concurrent confirm 会双写事实 | Refuted | 两路成功响应但只写一个 turn/event；问题是 API exactly-once 语义 |
| unknown normalization 均安全 fail-closed | Refuted | unknown action 安全 block，但 unknown safety flag 被删后可 accepted |

### Causality Update

本次“巡视”incident 的精确因果应更新为：external LLM 在前一轮 manifest 已可见时仍把动作解释为 query；live manifest 又没有暴露 deterministic router 中的“巡视→routine”exact-term evidence；internal unavailable 后 kernel 正常 fail closed。prompt-only sequencing 是独立弱点，但不是该 incident 的直接触发原因。旧 skill 随后导致 craft 错误归因，background review 再把该诊断固化。

### Backlog Changes

- #1 authority/state map：Outcome 3 完成，Outcome 4 只补 source ownership。
- #2 consumer/manifest contract：taxonomy drift Confirmed；sequencing direct-cause Refuted、design weakness Confirmed。
- #3 candidate/rules/internal/arbiter：unknown safety fail-open 与 taxonomy drift Confirmed；route representation inconsistency Refuted。
- #4 mode/preflight：安全 policy 成立；consumer purpose/liveness debt Confirmed。
- #5 pending/confirm：事实幂等成立；duplicate-success API semantics Confirmed；supersede 是 confirmed behavior，是否为 defect 待产品语义决定。
- #6 surface parity：差异大多符合 profile 设计；真实 consumer E2E 缺口 Confirmed。
- #7 tests：provider coverage strong；consumer/concurrency/audit gaps Confirmed。
- #8 historical architecture：留到 Outcome 4 判断 coordinator boundary。
- #9 design severity：进入 Outcome 4 source trace 后定级。

### Updated Conclusion

用户“可能存在设计不合理”的前提部分成立，但问题不是 AI 权限过大或 commit 不安全。更准确的评价是：安全核心设计成熟，route contract 与 orchestration 没有同等成熟；需要定向收敛，而不是推倒重写。

## Follow-up: 2026-07-12 #3

### Outcome 4 Source Ownership

- Taxonomy：应选定单一、版本化 owner；`ActionResolverSpec/Registry` 是候选方案而非调查已决定的唯一答案，也可采用独立 taxonomy contract。`intent_router` 应保留组合语义、否定、maintenance、entity-aware grammar，不再维护简单同义词平行表。
- Slot：是否由 resolver contract 拥有 required/any-of/aliases/binding/confirmation 的 resolved metadata，属于 architecture decision。现有证据只要求消除无 parity gate 的平行手工维护，未证明当前 slot 行为已经错误。
- External safety：strict validation owner 位于 external candidate boundary；tolerant internal/legacy normalizer 不能替代 external fail-closed。
- Pending/clarification：`SaveManager` 是 canonical session owner；PlatformSidecar/MCP adapter 不应各自发展不同 business state truth。
- Commit replay：UnitOfWork 已保护事实幂等，缺口在 SaveManager claim 与 CommitService replay result classification。
- Preflight：AIIntentRouter/cache 拥有 single-use claim；Runtime entry 必须声明 consumer purpose，ContextBuilder 不应隐式决定消费。
- Consumer/self-improvement：属于 Hermes；RPG Engine 只提供机器 contract、safe audit 与跨边界 fixtures。

### Historical Alignment

- 基线 commit `3df5748` 同时引入 taxonomy/slot 多真源、宽容 safety normalization、单 pending、无 confirm claim 与 preflight consuming route；这不是单一近期回归。
- `e2b1760` 让 external-primary 路径可到达，从而使基线 unknown safety flag 静默删除产生 accepted outcome；但 external-primary 的低信任/diagnostic-only rules边界必须保留。
- 历史 coordinator review 已明确警告 diagnostic `start_turn` 不应意外消费正常 player route 的 single-use preflight（archived team review line 460）；当前缺少 executable purpose contract。
- Canonical coordinator boundary 明确禁止接管 player confirm、arbiter、binder、resolver、validation 或 commit（`docs/ai-intent-chain.md:392`）。

### Minimal Boundaries

| Work package | Minimum files/owners | Must preserve |
| --- | --- | --- |
| Strict safety vocabulary | schema、`external.py`、normalization/arbiter parity tests | external 低信任、known blocker、kernel safety guard |
| Canonical action taxonomy | owner 待规划：actions registry/spec 或独立 taxonomy contract；intent router、manifest、internal prompt、parity/P0 tests | current P0 routes、entity/hidden binding、rules non-veto for validated external-primary |
| Slot ownership cleanup | resolver/binder/slot contract/manifest；metadata shape 待设计 | current binding、required/any-of、confirmation 与 hidden-content boundary |
| Pending exactly-once | SaveManager pending store、CommitService replay result、concurrency tests | no gameplay write before confirm、idempotent command、stale/write guards |
| Clarification lifecycle | SaveManager canonical session、MCP mirror/guard、platform tests | fresh player answer、no candidate-as-confirmation、reroute old preview |
| Preflight purpose | IntentRequestMeta、AIIntentRouter/cache、Runtime entries | CAS、identity、TTL、message-only isolation、no authority escalation |
| Consumer/audit | repository prompt/transcript validator、Hermes skill/executor、MCP audit | privacy、hidden-content redaction、audit non-authority |
| Cross-repo E2E | scripted model、real stdio FastMCP、temporary Save | no network/API key、no formal Save/Campaign/registry mutation |

### Product Decisions Still Open

以下不是调查能替用户决定的实现细节，必须进入 planning/story AC：

1. Canonical taxonomy 由 `ActionResolverRegistry` 承担，还是建立独立 versioned taxonomy contract；custom/campaign registry 和多语言词项如何投影。
2. Unknown safety strict rejection 的版本协商/rolling-upgrade 策略，以及 threat model 是否支持 security P1。
3. Workspace 是否保证永远单普通玩家会话；若是，保留单 pending 但显式 supersede；若否，需 per-session pending。
4. 第二次并发 confirm 返回 `already_confirmed`、`idempotent_replay` 还是 conflict，并定义 commit 后 clear 前崩溃恢复。
5. Clarification 是否有 TTL/cancel；caller-candidate defect 是否允许 matching clarification_id 在同原文上重新核验。
6. `start_turn` 定位为纯 diagnostic 不消费，还是显式 opt-in authoritative consumer。
7. Manifest provenance 是 MCP schema 字段，还是只由 Hermes host 维护 barrier/cache identity；registry 变化时如何处理 stale manifest。
8. Cross-repo E2E 落在 RPG Engine、Hermes CI 或独立 compatibility harness。

### Updated Conclusion

Outcome 4 已把所有 confirmed 问题追到当前责任边界、候选 owner 和最小修改面；taxonomy/slot 的最终 architecture owner 仍待 planning 决定。没有发现需要推倒 arbiter/binder/validation/commit 的证据；相反，历史和当前 canonical contract 都要求保留这些层。下一步应先做 Outcome 5 最终定级和 story decomposition，而不是直接编码一个大 Coordinator。

## Final Handoff: 2026-07-13

### Work Package Decomposition

| Order | Package | Priority | Repository / owner | Decision needed | Primary acceptance boundary |
| --- | --- | --- | --- | --- | --- |
| 1 | Strict external safety vocabulary | High；security/P1 待定 | RPG Engine / external candidate trust boundary | Yes: threat model、version skew policy | 任意 unknown safety flag 明确 rejected/blocked；known flags 与 schema/normalizer/arbiter parity；rolling upgrade 行为稳定 |
| 2 | Canonical action taxonomy | High | RPG Engine / owner 待 architecture decision | Yes: registry-owned 或独立 contract；迁移形状 | deterministic simple terms、manifest、internal projection 同源；巡视 P0 保持 routine；custom/multilingual projection 有 contract |
| 3 | Slot ownership cleanup | P2 design debt | RPG Engine / resolver+binder | Yes: owner/metadata shape | required/any-of/alias/binding/confirmation 有单一 resolved projection 或 executable parity gate |
| 4 | Pending claim and supersede semantics | P1/P2 | RPG Engine / SaveManager+CommitService | Yes: single workspace vs per-session；replay/crash result | 并发 confirm 只有一个 fresh commit；第二路稳定返回 replay/conflict；commit 后 clear 前崩溃可恢复；事实仍只写一次 |
| 5 | Clarification lifecycle | P2 | RPG Engine / SaveManager | Yes: TTL/cancel/corrected candidate | 单一 persisted session truth；不得把 candidate correction 当玩家确认 |
| 6 | Preflight consumer purpose | P2 | RPG Engine / AIIntentRouter+Runtime | Yes: `start_turn` 定位 | diagnostic 不意外消费 authoritative evidence；CAS/identity/TTL 保持 |
| 7 | Safe intent audit summary | P2 | RPG Engine / MCP adapter | Yes: provider audit 与受控 raw trace 的职责边界；privacy review | 可区分 external=query、rules=routine、selected source/clarification；不记录 raw slots/reason/hidden data |
| 8 | Manifest barrier and skill correction | P1/P2 | Hermes GM integration | No | next-model-turn barrier；static pitfall 不覆盖 live/current evidence |
| 9 | Background technical-claim evidence gate | P2 | Hermes self-improvement | Yes: reject vs unverified notes | 无 raw/tool evidence的技术根因不能升级为 confirmed durable skill claim |
| 10 | Real cross-repo stdio contract E2E | P2 | Shared integration | Yes: CI owner | scripted model、real FastMCP、temporary Save、无网络/正式数据写入 |

### Recommended BMAD Route

最高价值下一步是 `[CC] Correct Course` (`bmad-correct-course`)：先锁定上述八个产品/ownership 选择并拆分两个仓库的 stories。完成 change proposal 后，按 `[CS] Create Story` → `[VS] Validate Story` → `[DS] Dev Story` → `[CR] Code Review` 推进；不要把十个 package 合并成单一 story 或大 Coordinator。

### Outcome 5 Finalization

- Case 状态：`Concluded`。
- Root/design findings：Confirmed 或已明确 refute；剩余项均为规划选择或边界已知的历史证据缺口。
- `workflow.on_complete`：空，无 completion hook。
- 本调查未实施生产修复，未修改 source Campaign、formal Saves、正式 registry 或 `data/game.sqlite`。

## Review Correction: 2026-07-13

### Classification Corrections

- Confirmed runtime/contract defects：taxonomy drift、unknown safety 静默删除并接受、concurrent confirm duplicate-success、provider audit 无法独立重建 route。
- Confirmed behavior with product decision：workspace pending supersede、clarification lifecycle、`start_turn` preflight consumption。
- Confirmed design debt without reproduced runtime failure：slot ownership split、route representation complexity。
- Deduced risk：duplicate-success 引发外围副作用、background self-improvement 强化具体 durable claim。
- Open architecture/product choices：taxonomy owner、unknown-safety versioning/severity、pending partition/replay/crash semantics、clarification correction、preflight purpose、manifest provenance、E2E owner。

### Edge Cases Added to Planning Boundary

1. 新 caller/旧 provider 的 unknown safety vocabulary version skew，不能让 strict rejection 变成无计划 outage。
2. manifest 获取后 registry/taxonomy 变化时，next-model-turn barrier 仍可能使用 stale contract；需要 digest/version binding 或明确重试策略。
3. commit 已成功但 pending 尚未 clear 时的进程崩溃与重试分类。
4. direct MCP、platform 与多个 actor 共用同一 Save 时的 pending collision、cancel、migration 和 orphan cleanup。
5. canonical taxonomy 对 custom/campaign registry 与多语言词项的投影和 parity。
