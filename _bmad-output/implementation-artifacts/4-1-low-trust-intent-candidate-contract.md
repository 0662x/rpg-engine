---
baseline_commit: 1d9f2c19ff773b023e3cd32a95f1603d15a0f980
---

# Story 4.1：低信任意图候选合同

Status: done

## Story

作为 external AI 集成者，
我希望合法 external candidate 仅在 internal intent AI 明确关闭时拥有路由提案权，
从而避免 deterministic rules 覆盖外部已经理解好的玩家意图，同时仍由 Kernel 完成结构校验、绑定、预演、确认与安全提交。

## Acceptance Criteria

1. **候选规范化与禁止字段**

   **Given** external candidate 或现有 internal review candidate 进入共享 intent candidate contract
   **When** candidate 被规范化
   **Then** 它可以包含 `kind`、`mode`、`action`、`slots`、`plan`、`confidence`、`missing_slots`、`needs_confirmation`、`safety_flags` 和 `reason`
   **And** 它不得表达玩家确认、hidden access、delta/proposal 注入、save authorization、profile escalation，或 default player profile 的 per-call override
   **And** 本 Story 不新增 resident candidate ingress 或 Resident AI Advisory Envelope。

2. **off + 合法 external candidate 的路由提案权**

   **Given** internal intent AI 为 `off` 且存在合法 external candidate
   **When** schema、action registry、safety 和 binding 检查通过并执行 routing
   **Then** external candidate 成为 selected route proposal
   **And** deterministic rules 只保留为 trace / diagnostic evidence，不得 override、veto，或仅因 mismatch 强制 clarification。

3. **enabled + external candidate 保持既有仲裁**

   **Given** internal intent AI 已启用且存在 external candidate
   **When** routing 执行
   **Then** external/internal candidates 继续走既有 arbitration path
   **And** external candidate 不得仅因存在就自动取得路由提案权。

4. **off + 无 external candidate 保持兼容 fallback**

   **Given** internal intent AI 为 `off` 且不存在 external candidate
   **When** routing 执行
   **Then** 本次首个修复保持当前 deterministic rules fallback
   **And** no-external fallback hardening 留作独立 P0 决策，不得夹带进本 Story。

5. **非法、不安全或无法绑定的 external candidate 不得静默替换意图**

   **Given** external candidate malformed、unsafe、引用未知 action，或 binding 无效/缺失
   **When** schema validation、risk checks、action registry 或 binder 执行
   **Then** 在既有层级合同中返回明确拒绝、clarification 或 blocked：schema normalization 的 direct Python caller 保持带字段路径的 `ValueError`，CLI/MCP adapter 保持结构化 error result，进入 router 后的绑定/安全失败保持结构化 outcome
   **And** deterministic rules 不得静默替换成另一玩家意图，也不得从无效 candidate 创建 pending action。

6. **已路由 AI intent 不受 keyword mismatch hard veto**

   **Given** external-primary 或 accepted consensus route 与 keyword expected action 冲突
   **When** Runtime preview mismatch guard 执行
   **Then** mismatch 只保留为 diagnostic evidence，不得 hard-veto 已路由 intent
   **And** 对未经过 routed AI intent 选择的直接低层 `preview_action`，现有 mismatch guard 必须保留。

7. **标准 player-safe 后续链保持不变**

   **Given** selected route 是 query 或 executable action
   **When** 标准 player-safe path 继续
   **Then** query 返回 player-visible read-only state 且不保存；action 经过 resolver、preview 和 validation 后只创建 pending action
   **And** 只有玩家明确确认后，匹配 `session_id` 的 `player_confirm()` 才能提交 gameplay facts。

## Tasks / Subtasks

- [x] Task 1：先建立 mode matrix characterization 与失败路径测试（AC: 1-6）
  - [x] 在 `tests/test_ai_intent.py` 覆盖 `off + valid external`、`off + no external`、`enabled + external` 三分支；断言 external-primary decision/source、rules trace 和既有 consensus 行为。
  - [x] 覆盖 external query、未知 action、missing/ambiguous binding、blocker safety flag、malformed schema；`mode=maintenance` 作为非法 schema 拒绝，合法 candidate 携带 `maintenance_request` safety flag 时必须 blocked；失败不得回落到另一 rules intent。
  - [x] 覆盖禁止字段/权限语义：confirmation/save/hidden/delta/proposal/profile/per-call override 不得取得效力；binder 必须继续忽略 AI supplied player-confirmation slots 并要求玩家确认。
  - [x] 覆盖 external candidate 伪造 `source` / `source_user_text` 时由 Kernel 覆写 effective provenance；不要删除兼容 normalized/cached payload 字段。
  - [x] 覆盖 invalid external query：非法 `query_kind`、entity/context 缺少 `query_text`、hidden target 均不得 fallback、save 或创建 pending。
  - [x] 覆盖 external composite `plan`：必须 structured clarification / step confirmation，不得直接 ready 或 pending。
  - [x] 更新现有 `off` 模式“external trace-only” characterization，不删除 `off + no external` 的兼容断言。

- [x] Task 2：实现 mode-gated external-primary arbitration 与 adoption（AC: 2-5）
  - [x] 在 `rpg_engine/ai_intent/arbiter.py` 增加只适用于 `off + external` 的 external-only 决策路径；保留 schema、registry、safety、binding，且不以 rules agreement 作为通过条件。
  - [x] 在 `rpg_engine/ai_intent/router.py` 显式区分 internal intent AI mode；`off + external` 允许 accepted external decision 生成 selected outcome，`off + no external` 保持现行 rules outcome。
  - [x] 在 `rpg_engine/ai_intent/adapters.py` 将 consensus-only decision conversion 泛化为 accepted external-primary / consensus decision conversion，同时保持 query/action/clarify/block 结构。
  - [x] Trace 必须同时记录 `mode`、`route_authority`、external candidate、rules candidate、rules outcome、decision 和 selected outcome；external-primary 使用稳定 source `external_primary`。为兼容保留现有 `consensus_outcome` 字段，并新增/使用通用 adopted outcome 字段，不得删除 rules diagnostics。

- [x] Task 3：让 Runtime mismatch guard 感知 routed provenance（AC: 2, 6）
  - [x] 在 `rpg_engine/runtime.py` 让 `preview_intent(ActionIntent)` 的内部 routed path 与直接低层 `preview_action` 区分开；推荐由 `preview_intent` 调用 `preview_action` 时不触发 direct-source hard guard，再单独追加 bounded mismatch diagnostic，避免信任 caller-supplied context/source 字段。
  - [x] Routed AI intent 的 keyword mismatch 只形成有界 diagnostic/warning，不改变 resolver 选择和 `ready_to_save`；direct low-level `preview_action(..., source_user_text=...)` 的现有 `needs_confirmation` guard 保持，即使 caller 伪造类似 routed context 也不得 bypass。
  - [x] 仅在 trace/provenance wiring 必须时修改 `rpg_engine/intent_router.py`；不得重新引入 keyword-based external override，也不得创建新的 coordinator。

- [x] Task 4：证明 player-safe、CLI/MCP、platform/preflight 边界未改变（AC: 3, 4, 7）
  - [x] 在 `tests/test_runtime.py` 覆盖 external=`rest` / rules=`gather` 的 off-mode conflict、external query read-only、routed mismatch 不 veto、direct low-level mismatch guard 保留。
  - [x] 在 `tests/test_save_manager.py` 使用 temporary workspace/Save 证明 `player_turn` 只创建 pending，错误 session 不提交，正确 `player_confirm(session_id)` 才提交；返回仍隐藏 delta/proposal。
  - [x] 在 `tests/test_mcp_adapter.py` 和 `tests/test_v1_cli.py` 证明 public signatures、default player profile、`player_act` 限制和输出形状不变。
  - [x] 回归 enabled agree/disagree/unsafe/internal-unavailable、preflight single-use/advisory、platform 不接收 external candidate；不得把 enabled timeout/unavailable 偷换为显式 `off`。

- [x] Task 5：实现验证通过后同步 canonical docs、Prompt 与 GM Skill（AC: 1-7）
  - [x] 在 focused behavior tests 通过后，同步 `docs/project-context.md`、`docs/ai-intent-chain.md`、`docs/architecture.md`、`docs/mcp-contracts.md`、`docs/cli-contracts.md`、`docs/prompt-contracts.md`。
  - [x] 更新 `docs/prompts/ai-client-prompt.md` 的三分支 mode matrix，删除“external 永远不是最终 intent authority”的歧义，但继续禁止 confirmation、preview approval、hidden permission、save approval 和 commit authority；Prompt version 升为 `2026-07-11.internal-ai-off-external-primary`。
  - [x] 同步 repo 外 `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/SKILL.md` 及 `references/mcp-interface.md`、`references/ai-intent-playtest.md`，将 Skill 版本从 `1.10.3` 升为 `1.11.0`；该外部 artifact 不进入本仓库 commit，最终单独报告验证状态。

- [x] Task 6：从最终 clean diff 运行并记录全部 required gates（AC: 1-7）
  - [x] Story focused：intent/runtime/save/MCP/CLI/preflight/platform suites。
  - [x] Adjacent regression：current-native context、context quality、platform AI simulation；所有写测试必须使用 temporary Save。
  - [x] Campaign：两个 canonical example 的 validate/test。
  - [x] Docs/static：Markdown links、`py_compile`、full Ruff、`git diff --check`。
  - [x] Repository full `pytest`；任何后续 patch 都会使受影响旧绿灯失效，必须重跑。
  - [x] 在 current-native package 的 temporary copy 上跑 external rest-vs-gather、external query、pending -> wrong confirm -> right confirm playtest；验证 source Campaign、formal current Save 和正式 registry fingerprint 不变。不得直接写 formal current Save。
  - [x] 验证外部 GM Skill：version 为 `1.11.0`，三文件都包含一致 mode matrix，且不存在 external 在 off 模式仍是 trace-only / 永远无 route authority 的旧表述。

### Review Findings

- [x] [Review][Patch] external-primary 必须保留独立 Kernel safety block [`rpg_engine/ai_intent/router.py`:175]
- [x] [Review][Patch] resolver 合同外 external slot 必须 block 而非 warning 后 accepted [`rpg_engine/ai_intent/arbiter.py`:241]
- [x] [Review][Patch] 补齐 ambiguous binding、maintenance flag 与 context missing query_text 矩阵 [`tests/test_ai_intent.py`:772]
- [x] [Review][Patch] 泛化 adapter 必须保持既有 consensus submode 与 player message 兼容 [`rpg_engine/ai_intent/adapters.py`:75]
- [x] [Review][Patch] 撤回不必要的 package-level generalized adapter export [`rpg_engine/ai_intent/__init__.py`:3]
- [x] [Review][Patch] MCP malformed candidate 测试补充 no-mutation 证据 [`tests/test_mcp_adapter.py`:234]
- [x] [Review][Patch] external-primary query 测试补充完整 SQLite 文件 no-mutation 证据 [`tests/test_runtime.py`:2438]
- [x] [Review][Patch] current-native playtest 补充正式 workspace registry fingerprint [`tests/test_current_native_player_turn.py`:51]
- [x] [Review][Patch] Prompt metadata 使用无 trailing whitespace 的独立渲染行 [`docs/prompts/ai-client-prompt.md`:5]
- [x] [Review][Defer] 新 `player_turn` 清理已有 pending action 的生命周期行为 [`rpg_engine/save_manager.py`:449] — deferred, pre-existing

#### Round 2

- [x] [Review][Patch] 缺失或 blocked-without-errors 的 rules safety evidence 必须 fail closed [`rpg_engine/ai_intent/router.py`:182]
- [x] [Review][Patch] resolver 合同外 slot 检测改用结构化 binder trace [`rpg_engine/ai_intent/arbiter.py`:241]
- [x] [Review][Patch] external entity query 多匹配必须 clarification [`rpg_engine/ai_intent/arbiter.py`:280]
- [x] [Review][Patch] external query 必须拒绝 query_kind/query_text 外的 slot [`rpg_engine/ai_intent/arbiter.py`:276]
- [x] [Review][Patch] external-primary 非安全 block 返回候选校验消息 [`rpg_engine/ai_intent/adapters.py`:90]
- [x] [Review][Patch] composite candidate 保留 structured step-confirmation plan [`rpg_engine/ai_intent/adapters.py`:92]
- [x] [Review][Patch] blocked/clarify adopted alternative 不得保留 0.92 高分 [`rpg_engine/intent_router.py`:326]
- [x] [Review][Patch] rejected external branch 的 route_authority 必须标记 Kernel validation [`rpg_engine/ai_intent/router.py`:222]
- [x] [Review][Patch] malformed/unknown external plan step 必须在 ingress 明确拒绝 [`rpg_engine/ai_intent/external.py`:9]
- [x] [Review][Patch] clarified external query submode 不得继承 rules fallback kind [`rpg_engine/ai_intent/adapters.py`:77]
- [x] [Review][Patch] external-primary 必须拒绝不一致的 mode/kind [`rpg_engine/ai_intent/arbiter.py`:179]
- [x] [Review][Patch] alias/canonical 重复 action slot 必须 block [`rpg_engine/ai_intent/arbiter.py`:241]

#### Round 3

- [x] [Review][Patch] external action 的 `kind=unresolved` 不得被绑定并提升为 ready [`rpg_engine/ai_intent/arbiter.py`:179]
- [x] [Review][Patch] composite kind 与非空 plan 必须双向一致，避免空确认或步骤丢失 [`rpg_engine/ai_intent/arbiter.py`:188]
- [x] [Review][Patch] external plan 超过八步必须在 schema ingress 明确拒绝而非静默截断 [`rpg_engine/resources/schemas/intent_candidate.schema.json`:24]
- [x] [Review][Patch] 自报 missing/confirmation 只能在 kind、plan、query、slot 结构校验后生效 [`rpg_engine/ai_intent/arbiter.py`:202]
- [x] [Review][Patch] Story File List 必须匹配最终实际 diff，移除未改文件并补齐新增模块 [`_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.md`:312]

#### Round 4

- [x] [Review][Patch] composite 顶层 action 必须通过 action registry 校验 [`rpg_engine/ai_intent/arbiter.py`:224]
- [x] [Review][Patch] composite plan steps 必须经过 resolver slot contract、binder 与 player visibility 校验并只暴露安全绑定值 [`rpg_engine/ai_intent/arbiter.py`:224]
- [x] [Review][Patch] composite clarification 必须保持 composite kind 并推荐 `confirm_plan` [`rpg_engine/ai_intent/adapters.py`:103]
- [x] [Review][Patch] generic plan step id 不得错误声明 external provenance [`rpg_engine/ai_intent/adapters.py`:145]
- [x] [Review][Patch] consensus 无 external candidate 时 route authority 不得声称 external/internal arbitration [`rpg_engine/ai_intent/router.py`:225]
- [x] [Review][Patch] Round 3 后失效的最终门禁必须先恢复为未完成，待 final clean diff 重跑 [`_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.md`:100]

#### Round 5

- [x] [Review][Patch] enabled consensus composite 必须复用逐步 registry/binder/player-visibility 安全化 [`rpg_engine/ai_intent/arbiter.py`:530]
- [x] [Review][Patch] blocked composite 的安全 candidate 必须保持合法 kind/plan 形状 [`rpg_engine/ai_intent/arbiter.py`:251]
- [x] [Review][Patch] binding 未完成的 plan 必须 ask clarification，只有可确认 plan 才推荐 `confirm_plan` [`rpg_engine/ai_intent/adapters.py`:96]
- [x] [Review][Patch] Kernel safety 覆盖必须保留 arbiter 已安全化的 candidate [`rpg_engine/ai_intent/router.py`:203]
- [x] [Review][Patch] consensus 无 external 且 internal unavailable 时 route authority 必须回到 deterministic rules/kernel validation [`rpg_engine/ai_intent/router.py`:229]
- [x] [Review][Patch] external query 的 `query_kind`/`query_text` 必须是字符串 [`rpg_engine/ai_intent/arbiter.py`:470]
- [x] [Review][Patch] composite 必须保留候选自报 missing/confirmation 并阻止未完整 plan 被确认 [`rpg_engine/ai_intent/arbiter.py`:280]
- [x] [Review][Patch] external safety player message 必须使用结构化 decision reason 而非英文 substring [`rpg_engine/ai_intent/adapters.py`:99]
- [x] [Review][Patch] Project Structure Notes 不得声称本 Story 未修改 schema [`_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.md`:270]

#### Round 6

- [x] [Review][Patch] enabled composite mismatch 分支不得输出未标记为已验证的 raw plan [`rpg_engine/ai_intent/adapters.py`:97]
- [x] [Review][Patch] shared composite validator 必须拒绝空 plan 并保持合法安全 candidate [`rpg_engine/ai_intent/arbiter.py`:359]
- [x] [Review][Patch] composite binding trace 必须引用 sanitized candidate 而非原始低信任 slots [`rpg_engine/ai_intent/arbiter.py`:565]
- [x] [Review][Patch] external/internal composite plan 不一致不得标记为 confirmation-ready [`rpg_engine/ai_intent/arbiter.py`:584]
- [x] [Review][Patch] internal helper unavailable 的 route authority 判定必须优先于 external-present 模式标签 [`rpg_engine/ai_intent/router.py`:229]
- [x] [Review][Patch] enabled consensus query 必须复用 query contract、visibility 与 declared clarification 校验 [`rpg_engine/ai_intent/arbiter.py`:603]
- [x] [Review][Patch] enabled single action 必须拒绝 duplicate/contract-outside slots 并保留 declared missing/confirmation [`rpg_engine/ai_intent/arbiter.py`:615]
- [x] [Review][Patch] shared composite 顶层必须检测 alias/canonical 重复 slots [`rpg_engine/ai_intent/arbiter.py`:359]

#### Round 7

- [x] [Review][Patch] enabled arbitration 必须在任何采用前拒绝 mode/kind/plan 自相矛盾的 shared candidate shape [`rpg_engine/ai_intent/arbiter.py`:572]
- [x] [Review][Patch] enabled query 比较必须使用 canonical string values，避免大小写/空白制造假 mismatch [`rpg_engine/ai_intent/arbiter.py`:690]
- [x] [Review][Patch] 创建期 validation report 必须标明 schema/no-change 结论是实现前快照 [`_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.validation-report.md`:5]

#### Round 8

- [x] [Review][Patch] enabled ordinary mismatch 必须先分别完成 query/action contract validation 与安全化 [`rpg_engine/ai_intent/arbiter.py`:673]
- [x] [Review][Patch] shared shape 的 `mode=unknown` 不得在 enabled arbitration 中变成 ready accepted route [`rpg_engine/ai_intent/arbiter.py`:567]

#### Round 9

- [x] [Review][Patch] single-source internal fast path 必须先经过 shared shape/query/action contract validation [`rpg_engine/ai_intent/arbiter.py`:84]
- [x] [Review][Patch] binding consensus 必须比较 effective bound option 并集，one-sided optional slot 必须 clarification [`rpg_engine/ai_intent/arbiter.py`:976]

#### Round 10

- [x] [Review][Patch] effective option union 必须 materialize resolver defaults 后再比较 [`rpg_engine/ai_intent/arbiter.py`:1027]
- [x] [Review][Patch] single-source query fast path 必须比较 canonical `query_kind/query_text` [`rpg_engine/ai_intent/arbiter.py`:1123]
- [x] [Review][Patch] single-source rules evidence 必须通过最小 shared shape/safety/query/action contract validation [`rpg_engine/ai_intent/arbiter.py`:1105]

#### Round 11

- [x] [Review][Patch] production rules query candidate 必须保留 canonical `query_kind/query_text` evidence [`rpg_engine/intent_router.py`:656]

#### Round 12

- [x] [Review][Patch] production entity query evidence 必须提取实体 target 而非使用整句 user text [`rpg_engine/intent_router.py`:661]
- [x] [Review][Patch] query rules builder 必须优先保留已存在的 canonical inferred/route options [`rpg_engine/intent_router.py`:650]
- [x] [Review][Patch] unknown deterministic query subtype 必须 fail closed，不得静默降为 scene [`rpg_engine/intent_router.py`:660]

#### Round 13

- [x] [Review][Patch] scene query canonical equality 必须忽略不参与执行的 `query_text` [`rpg_engine/ai_intent/arbiter.py`:593]
- [x] [Review][Patch] entity target parser 必须窄修复“查理是谁/夏娃在哪里/查一下夏娃”等确定性误切 [`rpg_engine/intent_router.py`:708]

#### Round 14

- [x] [Review][Patch] 无命令前缀的“实体名的资料/信息/属性”必须剥离明确 possessive 后缀 [`rpg_engine/intent_router.py`:716]

#### Round 15

- [x] [Review][Patch] typed query candidate 携带非空 action 必须在 shared shape 层 fail closed [`rpg_engine/ai_intent/arbiter.py`:612]

## Dev Notes

### 产品与权限语义

- 本 Story 只改变 **route proposal authority**，不改变 fact / permission / player confirmation / proposal approval / commit authority。
- 三分支 mode matrix 是实现真源：
  1. internal enabled + external：保持 external/internal arbitration；
  2. internal off + valid external：external-primary，rules trace-only；
  3. internal off + no external：保持当前 deterministic fallback。
- External candidate 结构合法但语义可能错误是批准方案已接受的剩余风险；显式 off mode、resolver/validation 和玩家确认负责控制。不要因此重新授予 rules mismatch 否决权。
- 错误合同由既有层级边界决定，不扩大 touched surface：direct Runtime/Python schema normalization 继续抛带 JSON path 的 `ValueError`；MCP/CLI 继续通过现有 adapter/handler 转为结构化错误；已进入 router 的 unknown action、binding、safety 和 query failures 使用 structured route/preview result。不要为了统一外观修改 `SaveManager`、CLI/MCP signature 或新增第二套异常包装。

### 当前实现与预期改动

- `rpg_engine/ai_intent/arbiter.py`
  - 当前：无 internal candidate 时直接进入 rules fallback，即使 external 存在。
  - 改动：提供 mode-gated external-only decision，先进行 external safety/binding 判定。
  - 保留：enabled external/internal disagreement、internal safety blocker、single-source internal fast path、no-candidate 结构。
- `rpg_engine/ai_intent/router.py`
  - 当前：只有 `intent_ai_mode == "consensus"` 才将 decision 转为 route outcome；off 最终选择 rules outcome。
  - 改动：off + external 也可转换受认可 external-primary decision；trace 明确 selected source。
  - 保留：off + no external、enabled helper/preflight/unavailable policy、preflight provenance gate。
- `rpg_engine/ai_intent/adapters.py`
  - 当前：`route_outcome_from_consensus_decision()` 已能把 accepted bound action、query、clarify/block 转为 `RouteOutcome`。
  - 改动：泛化命名/调用语义或新增窄 adapter；复用现有转换，不另造 outcome 类型。
  - 保留：maintenance block、query slot、clarification id/choices、structured errors。
- `rpg_engine/runtime.py`
  - 当前：`preview_intent()` 调用 `preview_action(..., source_user_text=intent.user_text)`，`preview_action()` 对 keyword mismatch 作 hard veto。
  - 改动：仅对 routed external-primary / accepted consensus 降为诊断；route provenance 应从现有 `ActionIntent.decision_trace` 进入 preview context。
  - 保留：direct low-level mismatch guard、resolver request/resolve contracts、redaction、TurnProposal、validation/commit。
- `rpg_engine/intent_router.py`
  - 当前：负责 candidate preparation、legacy rules trace、最终 `ActionIntent` 和 trace 组装。
  - 限制：只允许必要 provenance wiring；不要修改 keyword inference、无 external fallback、public method signature 或 semantic trace policy。

### 架构与范围护栏

- P0 不变量：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- `data/game.sqlite` 仍是 current fact authority；不改 schema、migration、Campaign/Save ownership、projection/outbox authority。
- 不修改 `ActionResolverSpec` 实现、`TurnProposal` schema、validation pipeline、`SaveManager` pending/confirm、`CommitService`。
- 不修改 public CLI/MCP signatures、default profile、server config shape、`player_act` external-candidate 边界或 platform sidecar/prewarm 参数。
- 不实现 Story 4.2 latency policy、Story 4.3 preflight contract、Story 4.4-4.5 advisory envelope/adapters、Story 4.6 maintenance proposal review 或 Story 4.7 plot progression。
- 不新增依赖，不创建 `IntentCoordinator`，不大规模重构 intent tree。
- Hidden/GM-only 内容不得进入 player surface、trace 的 player-visible fields、Prompt 或外部 GM Skill 示例。
- 所有 write tests 必须初始化或复制 temporary Save；不得修改 source Campaign、formal current Save 或正式 registry。

### 测试要求

必须覆盖以下行为矩阵：

| Scenario | Required result |
| --- | --- |
| off + valid bound external action + conflicting rules | external selected；rules 只留 trace |
| off + valid external query | player-view read-only；`saved=false`；无 pending/commit |
| off + malformed schema | route 前结构化拒绝，不 fallback |
| off + invalid query kind / missing query text / hidden target | 明确 reject/clarify/block；不 fallback、不保存 |
| off + unknown action / invalid slot | blocked 或 clarification；不进入 resolver/commit |
| off + missing/ambiguous binding | clarification；不形成 ready proposal |
| off + blocker safety / `maintenance_request` | blocked；非法 `mode=maintenance` 由 schema 拒绝 |
| off + external composite plan | structured step confirmation；不形成 ready proposal |
| routed external/accepted consensus 与 keyword 冲突 | 只记诊断，不 hard veto |
| direct low-level preview 与 source text 冲突 | 保留现有 mismatch guard |
| off + no external | 现行结果与 characterization 保持 |
| enabled agree/disagree/unsafe/unavailable | 既有 accepted/clarify/blocked/degrade 行为保持 |
| player action ready | `player_turn` 只 pending；匹配 confirm 后才 commit |
| platform/preflight | 不新增 candidate 权限；preflight 仍 advisory/single-use |

Focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ai_intent.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_mcp_adapter.py \
  tests/test_v1_cli.py \
  tests/test_preflight_cache.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_sidecar.py \
  -p no:cacheprovider
```

Adjacent regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_platform_ai_simulation.py \
  tests/test_current_native_context.py \
  tests/test_context_quality.py \
  tests/test_current_native_visibility.py \
  tests/test_surface_inventory.py \
  tests/test_cross_campaign_context_smoke.py \
  -p no:cacheprovider
```

Campaign / docs / static / final：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m py_compile <all changed Python and test files>
python3 -m ruff check .
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

### Project Structure Notes

- 在现有 `ai_intent/`、`intent_router.py` 和 `runtime.py` 边界内小步修改；不新增目录或第二套路由链。
- Story artifact 与 validation report 位于 `_bmad-output/implementation-artifacts/`。
- Canonical runtime docs 留在 `docs/`；Prompt 留在 `docs/prompts/`。
- GM Skill 是批准的 repo 外同步 artifact，不是本仓库 Git 文件；不得把其副本复制进 repo。
- 本 Story 是 Epic 4 第一项，无同 Epic previous-story file；最近 commit `1d9f2c1` 已批准并入库本 Story 的 P0 Correct Course、三分支 mode matrix 和 post-implementation docs/Skill sync。
- 无 UX artifact；本项目为 CLI/MCP/kernel-first，本 Story 不改变 UI 或 public surface shape。
- 无需 latest-tech web research：没有新增/升级 library、framework 或 external API；仅收紧仓库内既有 `intent_candidate.schema.json` 的 plan-step 合同与长度上限。
- 批准提案要求的真实 player-safe 验证默认在 current-native temporary copy 上完成；只有要写 formal save 时才需要另行授权，本 Story 不需要该授权。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 4.1: Low-Trust Intent Candidate Contract`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-10.md#2. 决策矩阵`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-10.md#5. 实施边界`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-10.md#6. 验收矩阵`]
- [Source: `_bmad-output/implementation-artifacts/investigations/external-intent-authority-investigation.md#Minimal Change Boundary`]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md#5.2 AI-First 意图与 Resident AI 边界`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md#AD-2 - AI route proposal 按 mode 选择，但 AI 不能成为事实、确认或提交权威 [ADOPTED]`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md#AD-2 - Intent coordination may select a route proposal but owns no gameplay fact or write authority [ADOPTED]`]
- [Source: `docs/project-context.md#不可破坏边界`]
- [Source: `docs/ai-intent-chain.md#当前标准链路`]
- [Source: `docs/testing-and-quality-gates.md#AI intent / platform / SaveManager 高风险 cluster`]

## BMAD Provenance

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`；从 sprint status 选择下一个 backlog story。
- Catalog 路由：`[CS] Create Story`，`bmad-create-story:create`，BMM implementation phase，required。
- Skill：`.agents/skills/bmad-create-story/SKILL.md` 已完整读取。
- Customization resolver：成功；prepend/append 为空；persistent fact 为 `file:{project-root}/**/project-context.md`；`on_complete` 为空。
- Config：`_bmad/bmm/config.yaml`；`communication_language=Chinese`，`document_output_language=Chinese`，artifact roots 已解析。
- 执行文件：`discover-inputs.md`、`template.md`、`checklist.md` 已完整读取；create workflow steps 1-6 按顺序执行。
- 输入：完整 sprint status、epics、PRD shards、architecture shards、批准的 Sprint Change Proposal、调查 case、canonical docs、计划内 production/test UPDATE 文件及外部 GM Skill 相关文件。
- 完成说明：Ultimate context engine analysis completed - comprehensive developer guide created。

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- RED：新增 external-primary tests 初次运行得到 11 个预期失败（缺少 `intent_ai_mode`、`route_authority`、adopted outcome，Runtime 仍选择 rules）。
- GREEN：实现 mode-gated external-primary arbitration/adoption、严格 query/binding/safety 失败路径与 routed mismatch diagnostic；focused 新增场景转为全绿。
- Dev baseline：focused `257 passed, 110 subtests passed`；adjacent/current-native `101 passed, 9182 subtests passed`；repository full suite `782 passed, 9653 subtests passed`。
- Campaign：`examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 的 validate/test 均 exit 0。
- Docs/static：173 个 Markdown 文件链接通过；changed Python `py_compile`、full Ruff、`git diff --check` 均通过。
- 外部 GM Skill：Codex 通用 validator 因 Hermes 扩展 frontmatter 不兼容而拒绝；改用 Hermes 原生 `_validate_frontmatter` / `_validate_content_size` 通过，8 个 Markdown 文件链接通过，三文件 mode matrix/旧表述扫描通过。
- Review Round 1：Blind 16 findings、Acceptance 3 findings；Edge timeout 记 failed layer。去重/复现后自动应用 9 个 Patch、记录 1 个 pre-existing Defer、dismiss 8 个噪声；patch-focused `222 passed, 114 subtests passed`，current-native targeted 通过。
- Review Round 2：三路 reviewer 全部返回；22 个原始 findings 去重后自动应用 12 个 Patch、dismiss 3 组噪声、Decision/Defer 0；patch-focused `264 passed, 123 subtests passed`，current-native targeted 与 docs/static gates 通过。
- Review Round 3：Blind 与 Edge 返回，Acceptance 两次在最终报告阶段超时并记 failed layer；其已复现 finding 与另两路重合。去重后自动应用 5 个 Patch、dismiss 9 组噪声、Decision/Defer 0；定点复现 `4 passed, 15 subtests passed`。
- Review Round 4：三路 reviewer 全部返回；去重后自动应用 6 个 Patch、dismiss 5 组噪声、Decision/Defer 0；patch-focused `118 passed, 88 subtests passed`，current-native `3 passed, 12 subtests passed`，docs/static gates 通过。
- Review Round 5：三路 reviewer 全部返回；去重后自动应用 9 个 Patch、dismiss 9 组噪声、Decision/Defer 0；patch-focused `119 passed, 90 subtests passed`，docs/static gates 通过。
- Review Round 6：三路 reviewer 全部返回；去重后自动应用 8 个 Patch、dismiss 10 组噪声、Decision/Defer 0；patch-focused `122 passed, 96 subtests passed`，docs/static gates 通过。
- Review Round 7：fresh Blind/Edge 返回；因 thread limit 复用独立 Acceptance agent 做 fresh-pass，Acceptance clean。去重后自动应用 3 个 Patch、dismiss 12 组噪声、Decision/Defer 0；patch-focused `123 passed, 99 subtests passed`，docs/static gates 通过。
- Review Round 8：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；去重后自动应用 2 个 Patch、dismiss 13 组噪声、Decision/Defer 0；patch-focused `124 passed, 103 subtests passed`，docs/static gates 通过。
- Review Round 9：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；三路一致确认并自动应用 2 个 Patch、dismiss 13 组噪声、Decision/Defer 0；patch-focused `126 passed, 107 subtests passed`，docs/static gates 通过。
- Review Round 10：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；去重后自动应用 3 个 Patch、dismiss 13 组噪声、Decision/Defer 0；patch-focused `128 passed, 109 subtests passed`，docs/static gates 通过。
- Review Round 11：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；三路一致确认并自动应用 1 个 Patch、dismiss 14 组噪声、Decision/Defer 0；patch-focused `129 passed, 109 subtests passed`，docs/static gates 通过。
- Review Round 12：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；三路一致确认并自动应用 3 个 Patch、dismiss 14 组噪声、Decision/Defer 0；patch-focused `129 passed, 109 subtests passed`，docs/static gates 通过。
- Review Round 13：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；三路一致确认并自动应用 2 个 Patch、dismiss 15 组噪声、Decision/Defer 0；patch-focused `130 passed, 115 subtests passed`，docs/static gates 通过。
- Review Round 14：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；Blind clean，Edge/Acceptance 确认并自动应用 1 个 Patch、dismiss 0、Decision/Defer 0；patch-focused `130 passed, 119 subtests passed`，docs/static gates 通过。
- Review Round 15：因 thread limit 复用三路独立 reviewer 线程 fresh-pass；Edge clean，Blind/Acceptance 确认并自动应用 1 个 Patch、dismiss 0、Decision/Defer 0；patch-focused `131 passed, 122 subtests passed`，docs/static gates 通过。
- Review Round 16：因 thread limit 复用三路独立 reviewer 线程 clean-pass；Blind clean、Edge `[]`、Acceptance clean，Patch/Decision/Defer 0。累计自动应用 67 个 review patches。
- Final full-suite 首跑：`802 passed, 9707 subtests passed, 4 failed`；4 个失败同源于两份旧 eval fixtures 缺少 required `query_kind`。补齐合法 entity query 后 `tests/test_eval_suite.py` 为 `12 passed`，等待 Round 17 re-review 与 full-suite 重跑。
- Review Round 17：因 thread limit 复用三路独立 reviewer 线程 clean-pass；Blind clean、Edge `[]`、Acceptance clean，Patch/Decision/Defer 0。
- Final clean-diff gates：focused `281 passed, 164 subtests passed`；adjacent `101 passed, 9182 subtests passed`；两个 canonical Campaign validate/test 均通过；Markdown links、changed Python `py_compile`、full Ruff、diff check 通过；repository full suite `806 passed, 9707 subtests passed`。
- 外部 GM Skill 最终验证：Hermes 原生 frontmatter/content-size 验证通过，8 个 Markdown 文件链接通过，version `1.11.0`、三文件 mode matrix 与旧表述扫描通过。

### Completion Notes List

- 实现三分支 mode matrix：enabled + external 保持 arbitration；off + valid external 采用 `external_primary`；off + no external 保持 rules fallback。
- 对 external-primary 保留 schema、registry、safety、query/binding 检查；非法候选结构化 block/clarify，不静默换成 rules 意图。
- 引入通用 `adopted_outcome` 并保留 `consensus_outcome` 兼容 trace；Kernel 覆写 external/rules effective provenance。
- Routed `preview_intent` mismatch 降为 bounded diagnostic，direct `preview_action` hard guard 继续生效且不能靠伪造 context 绕过。
- player-safe query、pending/confirm、CLI/MCP profile、preflight/platform、hidden visibility 与 formal current package 边界全部通过回归。
- 同步 canonical docs、AI Client Prompt 与 repo 外 GM Skill 1.11.0；外部 Skill 不进入本仓库 commit。
- ✅ Resolved review findings：独立 safety guard、非法 slot block、矩阵测试、consensus adapter 兼容、API export 收窄、no-mutation/registry evidence 与 Prompt header 共 9 项。
- ✅ Resolved Round 2 findings：safety fail-closed、query/slot/kind/plan 边界、structured composite confirmation、trace/alternative/message 语义共 12 项。
- ✅ Resolved Round 3 findings：action-kind、plan-kind/长度、结构校验顺序与 Story File List 共 5 项。
- ✅ Resolved Round 4 findings：composite registry/binder/visibility、confirm-plan/provenance、route authority 与 stale gate evidence 共 6 项。
- ✅ Resolved Round 5 findings：enabled composite 安全化、plan readiness、sanitized safety override、query/missing/type/trace 与 artifact 一致性共 9 项。
- ✅ Resolved Round 6 findings：validated-plan gate、empty/duplicate/mismatch composite、sanitized binding、enabled query/action shared contract 与 authority priority 共 8 项。
- ✅ Resolved Round 7 findings：enabled shared candidate shape、canonical query comparison 与 validation provenance 共 3 项。
- ✅ Resolved Round 8 findings：ordinary mismatch prevalidation/sanitization 与 unknown-mode fail-closed 共 2 项。
- ✅ Resolved Round 9 findings：single-source internal shared validation 与 effective bound option union consensus 共 2 项。
- ✅ Resolved Round 10 findings：resolver-default effective comparison、single-source canonical query 与 validated rules evidence 共 3 项。
- ✅ Resolved Round 11 findings：production rules query canonical evidence 与真实 single-source fast-path 回归共 1 项。
- ✅ Resolved Round 12 findings：entity target extraction、precise query evidence preservation 与 unknown subtype fail-closed 共 3 项。
- ✅ Resolved Round 13 findings：scene canonical equality 与 narrow Chinese entity query parser 共 2 项。
- ✅ Resolved Round 14 findings：possessive entity query suffix extraction 共 1 项。
- ✅ Resolved Round 15 findings：typed non-action candidate action-field fail-closed 共 1 项。
- ✅ Review Round 16 clean：三路均无新的范围内有效 finding。
- ✅ Review Round 17 clean：fixture 修复后三路均无新的范围内有效 finding。
- ✅ Final verification：最终 clean diff 的 focused、adjacent、Campaign、docs/static、full suite 与外部 GM Skill gates 全部通过；Story 转为 done。

### File List

- `_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.md`
- `_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/project-context.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `rpg_engine/ai_intent/adapters.py`
- `rpg_engine/ai_intent/arbiter.py`
- `rpg_engine/ai_intent/external.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/resources/evals/intent_clarification_loops.yaml`
- `rpg_engine/resources/evals/intent_consensus_gold_set.yaml`
- `rpg_engine/resources/schemas/intent_candidate.schema.json`
- `rpg_engine/runtime.py`
- `tests/test_ai_intent.py`
- `tests/test_current_native_player_turn.py`
- `tests/test_mcp_adapter.py`
- `tests/test_runtime.py`
- `tests/test_save_manager.py`
- `tests/test_v1_cli.py`

### Change Log

- 2026-07-11：实现 low-trust external-primary route proposal contract、严格失败路径、routed mismatch diagnostics、player-safe 回归与 canonical docs/Prompt/GM Skill 同步；Dev Story 门禁全绿，状态转为 review。
- 2026-07-11：Code Review Round 1 自动应用 9 个明确 patch，记录 1 个 pre-existing defer；受影响 focused/current-native/docs/static gates 重跑通过，等待 fresh re-review。
- 2026-07-11：Code Review Round 2 自动应用 12 个明确 patch；受影响 focused/current-native/docs/static gates 重跑通过，等待 Round 3 fresh re-review。
- 2026-07-11：Code Review Round 3 自动应用 5 个明确 patch；Acceptance layer 最终回传失败但其复现 finding 已由另两路覆盖，等待 patch gates 与 Round 4 fresh re-review。
- 2026-07-11：Code Review Round 4 自动应用 6 个明确 patch；受影响 focused/current-native/docs/static gates 重跑通过，等待 Round 5 fresh re-review。
- 2026-07-11：Code Review Round 5 自动应用 9 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 6 fresh re-review。
- 2026-07-11：Code Review Round 6 自动应用 8 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 7 fresh re-review。
- 2026-07-11：Code Review Round 7 自动应用 3 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 8 fresh re-review。
- 2026-07-11：Code Review Round 8 自动应用 2 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 9 fresh re-review。
- 2026-07-11：Code Review Round 9 自动应用 2 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 10 fresh re-review。
- 2026-07-11：Code Review Round 10 自动应用 3 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 11 fresh re-review。
- 2026-07-11：Code Review Round 11 自动应用 1 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 12 fresh re-review。
- 2026-07-11：Code Review Round 12 自动应用 3 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 13 fresh re-review。
- 2026-07-11：Code Review Round 13 自动应用 2 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 14 fresh re-review。
- 2026-07-11：Code Review Round 14 自动应用 1 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 15 fresh re-review。
- 2026-07-11：Code Review Round 15 自动应用 1 个明确 patch；受影响 focused/docs/static gates 重跑通过，等待 Round 16 fresh re-review。
- 2026-07-11：Code Review Round 16 三路 clean；review 自动收敛完成，进入 final clean-diff required gates。
- 2026-07-11：Final full suite 暴露并修复 2 个 stale eval fixture contracts；eval focused 通过，等待 Round 17 clean-pass。
- 2026-07-11：Code Review Round 17 三路 clean；重新运行 final clean-diff full suite。
- 2026-07-11：Final clean-diff required gates 全绿；Story 4.1 完成并同步为 done，Epic 4 因后续 stories 仍为 backlog 保持 in-progress。
