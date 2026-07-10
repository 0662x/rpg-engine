# Investigation: External Intent Authority

## Hand-off Brief

`intent_ai=off` 时，合法的 external candidate 会被记录却不被采纳，并可能在 preview 阶段再次被关键词规则否决。
调查已确认三个控制点：arbiter 缺 external-only branch、router 只允许 consensus adoption、`preview_action_mismatch_guard` 对已路由 AI intent 仍作 hard veto。
修复应采用 external-primary + engine-verified，限制在 intent arbitration/adoption、route adapter 和 route-aware preview guard；保留现有 resolver、validation、confirm/commit、platform 以及 no-external 行为，并通过 P0 `bmad-correct-course` 进入实施。

## Case Info

| Field            | Value |
| ---------------- | ----- |
| Ticket           | N/A |
| Date opened      | 2026-07-10 |
| Status           | Concluded |
| System           | macOS local checkout；repo `/Users/oliver/.hermes/rpg-engine`；workspace `/Users/oliver/.hermes` |
| Evidence sources | 用户描述；canonical docs；core route/source entrypoints；临时 repro；focused tests；git/history archive；targeted Ruff |

## Problem Statement

用户报告当前自然语言意图链路存在设计问题：规则/关键词路由准确率低；无 internal AI 时，如果外部 AI 已经传入 `external_intent_candidate`，engine 不应继续用内部规则覆盖外部候选。用户期望重新调查这一文件，并评估是否应改为：外部 AI 负责理解意图，engine 负责稳定、安全地验证和执行。

本次调查从零重做。旧文件中的结论不作为当前结论，除非在本轮重新验证。

## Evidence Inventory

| Source | Status | Notes |
| ------ | ------ | ----- |
| 用户描述 | Partial | 设计诉求明确，但没有可复现的真实失败输入、external candidate、期望 route 和当前 route。 |
| Canonical docs | Available | 权威边界一致：external 是低信任候选，internal 是独立复核，rules 是 fallback/risk/binding 候选；off-mode precedence 未定义。 |
| Core route source | Available | 已核对 candidate preparation、arbiter、route selection、binder、rules risk、SaveManager 和 MCP `player_turn` 传递链。 |
| CLI/MCP/platform entrypoints | Available | CLI/MCP/player_turn、legacy player_act、Runtime/start_turn、platform sidecar/prewarm 的参数与默认值已逐入口核对。 |
| Tests | Available | Outcome 2 的 6 个 focused tests、Outcome 3 的 4 个 safety tests、Outcome 4 的 6 个入口/validation tests 与 12 个 subtests 均通过；另运行临时实验矩阵。 |
| Version control | Available | 关键选择可追溯到 baseline；归档实现日志确认 rule-first/trace-only 是当时行为保持型重构的显式兼容策略，但不是现行 canonical precedence。 |
| Static analysis | Available | 相关 8 个 route/entrypoint 文件运行 Ruff，结果 `All checks passed!`。 |
| Diagnostic archives / issue tracker | Missing | Repo 内未发现独立 diagnostic、incident、ticket 或 issue artifact。 |
| 失败样例 / playtest transcripts | Missing | 尚未收集真实失败输入、外部 candidate、期望 action/query/slots。 |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --------------- | -------- | ------ | ----- |
| 1 | 重新盘点 canonical docs：external/internal/rules 权威边界 | High | Done | 未发现 external-primary proposal 必然违反写入边界；off-mode precedence 是规范缺口。 |
| 2 | 重新盘点 route source：candidate preparation、route selection、rules fallback、binder/resolver | High | Done | 已追到 Runtime query/action、resolver contracts、TurnProposal、validation、confirm/commit。 |
| 3 | 重新盘点 tests：当前 rules-first 假设和可改验收矩阵 | High | Done | 当前行为被 characterization tests 明确锁定；缺 external-primary 验收矩阵。 |
| 4 | 收集真实失败样例 | High | Open | 至少需要 user_text、external candidate、期望结果、当前结果。 |
| 5 | 比较候选策略：external-primary、mismatch-clarify、rules-only-when-no-external | High | Done | 推荐 external-primary + engine-verified；rules 仅在 external 缺失时 fallback；blanket mismatch-clarify 被反证。 |
| 6 | 检查 CLI/MCP/platform entrypoints | Medium | Done | CLI/MCP `player_turn` 可传且默认 off；legacy `player act` 不传；platform 不传且默认 consensus。 |
| 7 | 查找设计来源 / issue / ADR | Medium | Done | 归档实现日志找到当时 rationale：行为保持、external advisory/future consensus；未找到外部 ticket。 |

## Timeline of Events

| Time | Event | Source | Confidence |
| ---- | ----- | ------ | ---------- |
| 2026-07-10 | 用户要求按建议覆盖原 investigation 文件并重新调查。 | Conversation | Confirmed |
| 2026-07-10 | 重新读取当前代码 stronghold，确认 `intent_ai_mode != "consensus"` 时 adoption 为 `None`，`selected_outcome` fallback 到 `rules_outcome`。 | `rpg_engine/ai_intent/router.py:188` | Confirmed |
| 2026-07-10 | 重新读取项目边界，确认 external AI 输出不是事实、最终意图或写入授权。 | `docs/project-context.md:35` | Confirmed |
| 2026-07-10 | 重新读取 AI intent 文档，确认 deterministic rules 不是开放自然语言唯一裁判。 | `docs/ai-intent-chain.md:66` | Confirmed |
| 2026-07-10 | 完成 Outcome 2 evidence perimeter；6 个 focused tests 全部通过。 | Focused pytest | Confirmed |
| 2026-07-10 | Git blame 确认 off-mode selection 表达式来自 baseline commit。 | `3df5748`; `rpg_engine/ai_intent/router.py:188` | Confirmed |
| 2026-07-10 | 临时实验确认“今天先收工，明早再继续”被 rules 判为 `gather/clarify`，同一 external rest candidate 经 consensus 成为 `rest/ready`。 | Outcome 3 experiment | Confirmed |
| 2026-07-10 | 反向实验确认错误 external social candidate 可通过 schema 与 binder，并绑定 `npc:scout-ren`；结构门不能判断语义正确性。 | Outcome 3 binder experiment | Confirmed |
| 2026-07-10 | 4 个 safety focused tests 通过：mismatch clarify、hidden-info blocked、risk fallback 限制、高风险 action 拒绝 fallback。 | Focused pytest | Confirmed |
| 2026-07-03 16:30 +10:00 | Baseline commit 已包含 consensus-only adoption 与 rules fallback selection。 | `3df5748` | Confirmed |
| 2026-07-03 17:57 +10:00 | Characterization snapshots 记录多类 `rules_fallback` 行为。 | `338423f` | Confirmed |
| 2026-07-03 18:12 +10:00 | Candidate preparation refactor 增加 external conflict 在 off 模式 trace-only 的明确测试。 | `dc2906b` | Confirmed |
| 2026-07-03 22:30 +10:00 | Canonical AI intent 文档建立，但未定义 off-mode external precedence。 | `d00f358` | Confirmed |
| 2026-07-10 | Outcome 4 复现：external/internal 均判 `rest`，仍被 preview 关键词 guard 以 `gather` hard veto。 | Outcome 4 experiment | Confirmed |
| 2026-07-10 | 入口/validation focused suite 通过。 | `4 passed in 0.17s`; `2 passed, 12 subtests passed in 80.60s` | Confirmed |
| 2026-07-10 | Outcome 5 完成；root cause、change boundary、acceptance matrix 和 BMAD hand-off 最终化，case 状态改为 Concluded。 | Investigation case file | Confirmed |

## Confirmed Findings

### Finding 1: 当前 route selection 在 AI off 时回落到 rules outcome

**Evidence:** `rpg_engine/ai_intent/router.py:188`

**Detail:** 当前代码只在 `intent_ai_mode == "consensus"` 时调用 `route_outcome_from_consensus_decision(...)`。否则 `adoption=None`、`consensus_outcome=None`，随后 `selected_outcome = consensus_outcome or rules_outcome`。

### Finding 2: external AI 不能成为事实或写入授权

**Evidence:** `docs/project-context.md:35`

**Detail:** 项目宪法明确：外部 AI 输出永远是低信任候选，不是事实、不是最终意图、不是写入授权；`SaveManager.player_confirm()` 是普通玩家路径的提交门。

### Finding 3: canonical docs 不把 deterministic rules 定义为唯一自然语言裁判

**Evidence:** `docs/ai-intent-chain.md:64`; `docs/ai-intent-chain.md:66`

**Detail:** AI intent 文档同时声明 external candidate 不是最终裁决，并声明 deterministic rules 提供 fallback、risk、binding 线索和可审计规则候选，不是开放自然语言的唯一裁判。

### Finding 4: 该改动属于 P0 风险面

**Evidence:** `docs/governance/bmad-workflow.md:42`

**Detail:** 改 AI intent、arbiter、binder、MCP/CLI/platform 公开行为、确认/事实提交时机都属于 P0，必须先规划，不能直接改代码。

### Finding 5: external candidate 和 rules candidate 会被并行准备，但 off 模式不采纳 external route

**Evidence:** `rpg_engine/intent_router.py:259`; `rpg_engine/intent_router.py:427`; `rpg_engine/ai_intent/router.py:103`; `rpg_engine/ai_intent/router.py:188`

**Detail:** `prepare_intent_candidates()` 会分别规范化 external candidate 并构建 legacy rules candidate。`AIIntentRouter.route_candidates()` 也会把 external candidate 送入 arbiter；但 route outcome adoption 只在 `intent_ai_mode == "consensus"` 时执行，off 模式最终选择 `rules_outcome`。

### Finding 6: 当前 tests 明确把 off-mode rules-first 当作预期行为

**Evidence:** `tests/test_ai_intent.py:1113`; `tests/test_runtime.py:742`; `tests/test_runtime.py:1292`

**Detail:** 测试分别断言 AI off 时 `selected_outcome` 是 rules outcome、冲突 external candidate 只留在 trace、`start_turn` context 中 decision source 为 `rules_fallback`。这不是偶然分支，而是被测试锁定的现行契约。

### Finding 7: external candidate 已受 schema gate，写入仍受独立确认门保护

**Evidence:** `tests/test_runtime.py:1349`; `rpg_engine/save_manager.py:515`; `rpg_engine/save_manager.py:613`; `tests/test_save_manager.py:995`

**Detail:** 非法 external candidate 会在 route/preview 前被拒绝。可执行结果只生成 pending action 和 `session_id`，`player_turn` 返回 `saved=False` 且不暴露 delta；只有匹配 session 的 `player_confirm()` 才调用 `commit_turn()`。

### Finding 8: 规范没有定义 off 模式下 external-vs-rules 的优先级

**Evidence:** `docs/ai-intent-chain.md:64`; `docs/ai-intent-chain.md:67`; `docs/ai-intent-chain.md:194`

**Detail:** 文档定义了 external、internal、rules 的角色以及 internal AI 不可用时的受限 rules fallback，却没有规定 `intent_ai=off` 且 external candidate 存在时应 external-primary、rules-primary 还是 mismatch-clarify。

### Finding 9: 公共入口对 external candidate 的支持不一致

**Evidence:** `docs/cli-contracts.md:164`; `docs/mcp-contracts.md:199`; `rpg_engine/mcp_adapter.py:396`; `rpg_engine/mcp_adapter.py:1286`; `docs/ai-intent-chain.md:333`

**Detail:** CLI `player turn` 与 MCP `player_turn` 支持 external candidate；legacy `player act` 不支持；platform sidecar 不接收 candidate。因此“完全删除 rules route”会涉及入口兼容决策，不能只改一行 selection。

### Finding 10: route selection 有两个独立锁点

**Evidence:** `rpg_engine/ai_intent/arbiter.py:60`; `rpg_engine/ai_intent/arbiter.py:113`; `rpg_engine/ai_intent/router.py:188`

**Detail:** internal candidate 缺失时，arbiter 没有 external-only adoption 分支，而是进入 rules fallback。随后 router 又只在 `intent_ai_mode == "consensus"` 时把 arbiter decision 转成 route outcome。只修改其中一处仍不足以让 off 模式采纳 external candidate。

### Finding 11: 已复现 external 正确而 rules 错误的可执行案例

**Evidence:** Outcome 3 experiment；`rpg_engine/intent_router.py:474`

**Detail:** 文本“今天先收工，明早再继续”在 off 模式被规则判成 `gather/clarify`；external=`rest(until=morning)` 与 internal review 一致时，现有 consensus 路径可绑定并生成 `rest/ready` preview。这证明 external candidate 在该案例中不是不可执行，只是被 off-mode authority policy 排除。

### Finding 12: schema 与 binder 不验证 candidate 对玩家原文的语义正确性

**Evidence:** `rpg_engine/ai_intent/external.py:10`; `rpg_engine/ai_intent/binder.py:61`; Outcome 3 binder experiment

**Detail:** 一个对“休息到早上”错误给出 `social(Scout Ren, 闲聊)` 的 external candidate 能通过 schema、action registry、slot/entity binding，并达到 `binding_status=bound`。这些门能保证结构和世界引用有效，不能证明 external AI 理解正确。

### Finding 13: 当前 rules fallback risk policy 不能直接作为 external-primary policy

**Evidence:** `rpg_engine/ai_intent/risk.py:54`; `rpg_engine/ai_intent/risk.py:86`; `rpg_engine/ai_intent/risk.py:100`

**Detail:** `assess_rules_fallback()` 把 external/rules mismatch、rules outcome mismatch 和非 `yellow_fast` action 当作拒绝 fallback 的理由。若 external-primary 继续让 rules mismatch 控制 adoption，就会重新引入用户要求移除的规则裁决权。需要独立的 external adoption risk policy，保留 schema、registry、binding、安全 flag、preview/validation/confirm/commit，但不把 rules agreement 当成通过条件。

### Finding 14: preview 阶段还存在第三个关键词 hard veto

**Evidence:** `rpg_engine/runtime.py:1051`; `rpg_engine/intent_router.py:1747`; Outcome 4 experiment

**Detail:** `preview_intent()` 把已经路由完成的 action 交给 `preview_action()`，后者再次调用 `detect_preview_action_mismatch()`。实验中 external/internal 都接受 `rest`，但“不要采集，休息到明早”仍被关键词优先级判为 `gather` 并返回 `needs_confirmation`。因此只修 arbiter/router 仍会让规则在 preview 阶段否决 AI route。

### Finding 15: route 后的 query/action/commit 安全链可以复用

**Evidence:** `rpg_engine/runtime.py:1270`; `rpg_engine/runtime.py:1298`; `rpg_engine/runtime.py:1370`; `rpg_engine/runtime.py:1486`; `rpg_engine/runtime.py:1524`; `rpg_engine/save_manager.py:515`; `rpg_engine/save_manager.py:613`

**Detail:** `ActionIntent` 生成后，query 固定走 player-view query 并保持 `ready_to_save=False`；single action 走 action registry、request/resolve contracts、preview 和 TurnProposal；SaveManager 只写 pending action；`player_confirm()` 后再次运行 `player_turn_commit` validation 才 commit。这些路径不依赖 route 来源，可直接服务 external-primary。

### Finding 16: off 模式的 no-external rules fallback 实际没有经过 risk helper

**Evidence:** `rpg_engine/ai_intent/router.py:179`; `rpg_engine/ai_intent/router.py:188`; Outcome 4 no-external experiment

**Detail:** `assess_rules_fallback()` 只在 consensus 模式 internal helper 不可用时调用；普通 off 模式直接选择 rules outcome。实测无 external 的 `social` 可生成 ready preview。canonical docs 描述的“受限 rules fallback”与当前 off 实现不完全一致。

### Finding 17: 入口变更影响可以限制在已有 external-capable surface

**Evidence:** `rpg_engine/cli_v1.py:536`; `rpg_engine/mcp_adapter.py:396`; `rpg_engine/mcp_adapter.py:1286`; `rpg_engine/platform_sidecar.py:392`; `rpg_engine/platform_prewarm.py:445`

**Detail:** CLI/MCP `player_turn` 已能传 external candidate 且默认 internal AI off，是主要受益入口。Runtime `start_turn/preview_from_text` 也会自动继承新 route。Platform sidecar/prewarm 明确不传 external，且 sidecar 默认 consensus，因此首个修复无需改变 platform signature 或行为。

### Finding 18: rule-first/trace-only 是历史兼容策略，不是漏接参数

**Evidence:** `docs/archive/pre-bmad-docs-2026-07-03/architecture/intent-refactor-implementation-log.md:48`; `docs/archive/pre-bmad-docs-2026-07-03/architecture/intent-refactor-implementation-log.md:64`; `docs/archive/pre-bmad-docs-2026-07-03/architecture/intent-design-alignment-review.md:225`

**Detail:** 当时的 behavior-preserving refactor 明确锁定 no-internal-AI rule-first，并声明 external 在 off 模式只用于 trace/future consensus。该归档记录解释了实现来源，但 canonical docs 仍未把它规定为永久产品 precedence。

## Deduced Conclusions

### Deduction 1: 用户指出的 authority 问题已被源码和实验确认

**Based on:** Finding 1, Finding 10, Finding 11

**Reasoning:** off 模式同时缺少 external-only arbiter 分支和 adoption 分支；可执行的 external rest candidate 因此被错误的 rules gather route 覆盖。

**Conclusion:** 根因不是普通关键词表不完整，而是 authority policy 明确把 external candidate 降为 trace-only。继续扩充关键词无法解决开放自然语言的权威冲突。

### Deduction 2: 可接受方案必须区分 route proposal 和 write authority

**Based on:** Finding 2, Finding 3

**Reasoning:** 文档允许 external AI 提供候选，也不把 deterministic rules 当唯一裁判；但 external AI 仍不能成为事实、确认或写入授权。

**Conclusion:** 任何候选方案都必须保留 engine 的 schema validation、action registry、binding、resolver/preview、validation、player confirmation 和 commit gate。

### Deduction 3: 推荐策略是 external-primary，而不是 external-unchecked

**Based on:** Finding 7, Finding 11, Finding 12, Finding 13

**Reasoning:** external candidate 可以修正规则误判，但也可能语义错误且结构完全有效。引擎无法在 internal AI 关闭时重新判断语义，但仍能并且必须验证候选是否合法、可绑定、风险允许、可预演和可确认。

**Conclusion:** `intent_ai=off` 且 external candidate 存在时，应由 external 决定 route proposal；engine 对它执行独立 external adoption policy。规则结果可保留为 trace/telemetry，但不能作为 veto 或 override。

## Strategy Decision Matrix

| Input state | Recommended authority | Engine result |
| --- | --- | --- |
| internal AI on；external 存在 | 现有 external/internal arbiter | agree 可采用；disagree clarification；unsafe blocked |
| internal AI off；external 存在 | external-primary | schema/registry/binding/risk 通过后 preview；失败则 clarification/blocked |
| internal AI off；external 缺失 | 首个修复保持现行 rules fallback | 是否收紧为 canonical 所述 restricted fallback，另立 P0 决策，避免夹带兼容变化 |
| internal AI off + external/rules 冲突 | external 是 proposal authority | rules 仅记录 trace，不 override、veto 或仅因 mismatch 触发 clarification |

## Hypothesized Paths

### Hypothesis 1: external-primary, engine-verified 可以改善自然语言准确率且不违反写入边界

**Status:** Open

**Theory:** 当 `external_intent_candidate` 存在时，把它作为 primary route proposal；engine 只负责验证、绑定、预演、校验、确认和提交。

**Supporting indicators:** 当前代码和文档显示 external candidate 已是正式输入面；rules 不是唯一自然语言裁判。

**Would confirm:** 真实失败样例中 external candidate 正确且可通过 binding/resolver/validation，而 rules route 错误。

**Would refute:** external candidate 在真实样例中频繁错误、缺 slot、越权或不可绑定，导致体验或安全性更差。

**Resolution:** 机械可行性和写入边界已得到实验支持；“真实玩家准确率整体改善”仍缺 playtest/transcript 数据，因此保持 Open。

### Hypothesis 2: rules-only fallback 仍需要保留给无 external candidate 的入口

**Status:** Confirmed

**Theory:** 完全删除 rules route 会破坏没有 external candidate 的 CLI/MCP/debug/query 兼容路径。

**Supporting indicators:** 当前 rules outcome 是默认 selected outcome；CLI/platform/legacy 入口中存在不传 external candidate 的路径。

**Would confirm:** 测试或入口盘点显示无 external candidate 时仍有合法 query/action flow。

**Would refute:** 产品决策要求所有普通自然语言入口必须提供 external candidate；无 candidate 时一律 clarification。

**Resolution:** CLI/platform/兼容路径存在不提供 external candidate 的入口；临时实验也确认无 external 时合法 action 依赖 rules fallback。首个修复必须保留该路径；是否按 canonical docs 收紧 risk 应拆成独立变更。

### Hypothesis 3: external/rules mismatch 直接 clarification 是更安全但可能更保守的替代方案

**Status:** Refuted

**Theory:** 当 external candidate 和 rules outcome 冲突时，不听规则也不听外部，直接要求玩家澄清。

**Supporting indicators:** 这可以避免 external 错误候选直接影响 preview。

**Would confirm:** 用户接受额外澄清，且冲突样例大多确实 ambiguous 或高风险。

**Would refute:** 冲突样例大多是 external 明确正确、rules 明确错误；clarification 只增加摩擦。

**Resolution:** 作为 blanket default 已被反证：external 正确/rules 错误的 `rest` 案例也会因 mismatch 被迫 clarification，继续让不可靠 rules 拥有否决权。Mismatch 可保留为 trace；clarification 应由 binding、risk、缺 slot 或独立安全门触发。

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | ------ | ------------- |
| 真实失败输入样例 | 无法证明 external-primary 的收益 | 收集用户历史 playtest、audit log 或人工列举样例 |
| External-primary 实施级验收测试 | 新 policy 尚未实现 | 后续 story 按 Acceptance Matrix 实现测试 |
| No-external fallback 最终产品策略 | canonical “restricted” 与当前 off-mode unrestricted 行为不一致 | 单独 P0 decision/story，不与 external-primary 修复捆绑 |
| 外部真实 playtest 数据 | 无法量化 external-primary 的整体准确率收益 | 收集 trace/transcript 后跑 canary/eval |

## Source Code Trace

| Element | Detail |
| ------- | ------ |
| Error origin | `rpg_engine/ai_intent/arbiter.py:60` 缺 external-only branch；`rpg_engine/ai_intent/arbiter.py:113` internal 缺失时进入 rules fallback；`rpg_engine/ai_intent/router.py:188` adoption 只在 consensus mode；`rpg_engine/runtime.py:1051` preview keyword hard veto |
| Trigger | `player_turn(... intent_ai="off", external_intent_candidate=...)` |
| Condition | external candidate 存在且 internal AI 关闭；或 AI route 与 `keyword_expected_action()` 冲突 |
| Related files | `rpg_engine/intent_router.py`, `rpg_engine/ai_intent/router.py`, `rpg_engine/ai_intent/risk.py`, `rpg_engine/ai_intent/binder.py`, `rpg_engine/save_manager.py`, `rpg_engine/runtime.py`, `rpg_engine/mcp_adapter.py`, `rpg_engine/cli_v1.py`, `rpg_engine/platform_sidecar.py` |

### Caller chain

1. CLI/MCP `player_turn` -> `SaveManager.player_turn()` -> `GMRuntime.act()` -> `preview_from_text()`。
2. `preview_from_text()` -> `route_intent()` -> candidate preparation -> `AIIntentRouter.route_candidates()`。
3. Current off path: arbiter rules fallback -> router rules outcome -> `ActionIntent(source=rules/action_inference)`。
4. Query intent -> `GMRuntime.query(view=player)` -> redacted read-only response，永不保存。
5. Action intent -> `preview_action()` -> action registry -> request/resolve contracts -> delta draft -> TurnProposal。
6. `SaveManager.player_turn()` 只保存 pending action 和 session id；`saved=False`。
7. `player_confirm()` 设置 human confirmation -> `commit_turn()` -> validation pipeline -> commit service。

## Minimal Change Boundary

### Must change

| File | Required responsibility |
| --- | --- |
| `rpg_engine/ai_intent/arbiter.py` | 增加 mode-gated external-only decision：schema 后按 mode/safety/binding 产生 accepted/clarify/blocked，不比较 rules agreement。 |
| `rpg_engine/ai_intent/router.py` | `intent_ai=off` 且 external 存在时启用 external-primary decision，并允许该 decision 生成 selected outcome；无 external 路径保持现状。 |
| `rpg_engine/ai_intent/adapters.py` | 将 consensus-only route adapter 泛化为可转换受认可的 external-primary decision，保留 query/action/clarify/block 结果。 |
| `rpg_engine/runtime.py` | 让 `preview_action_mismatch_guard` 感知 route authority；对 external-primary/AI-consensus routed intent 只记录诊断，不作 hard veto；直接低层 `preview_action` 仍保留 guard。 |

### Must not change in the first fix

- Public CLI/MCP signatures and defaults。
- Platform sidecar/prewarm external candidate boundary。
- Action resolver implementations、TurnProposal schema、validation pipeline、SaveManager pending/confirm、commit service。
- `intent_ai=off` 且 external 缺失时的现行行为；其 risk 收紧另立变更。

## Acceptance Matrix

| Scenario | Required result |
| --- | --- |
| off + valid bound external action + conflicting rules | external action becomes selected route；rules 仅 trace |
| off + valid external query | player-view query directly returned；`saved=False` |
| off + malformed external schema | 继续在 route 前拒绝 |
| off + unknown action / invalid slot | blocked 或 clarification，不进入 resolver commit |
| off + missing/ambiguous required binding | clarification，不能形成 ready proposal |
| off + blocker safety flag / maintenance mode | blocked |
| routed external/consensus action conflicts with keyword guard | keyword mismatch 不得 hard veto；可记录 warning/trace |
| direct low-level `preview_action` conflicts with source text | 现有 mismatch confirmation guard 保留 |
| off + no external | 首个修复保持现行 route 和测试 |
| consensus external/internal agree/disagree/unsafe | 现有 accepted/clarify/blocked 行为不变 |
| player action ready | `player_turn` 仅 pending；只有匹配 `player_confirm(session_id)` 可 commit |
| platform message path | 仍不传 external candidate，默认 consensus 行为不变 |

## Final Conclusion

**Confidence:** High

根因已确认且可确定复现：off + external 在 arbiter 被降级为 rules fallback，在 router 被 consensus-only adoption 阻止；即使 AI route 已被接受，Runtime 仍可能用关键词 mismatch guard 作第二次语义否决。历史记录表明这曾是行为保持型重构的显式兼容策略，但当前 canonical docs 没有要求它永久存在，且 rules 并非开放自然语言唯一裁判。

最终修正方向是 external-primary + engine-verified：internal AI 关闭且 external candidate 存在时，由 external 决定 route proposal；engine 继续掌握 schema、action registry、slot/entity binding、query visibility、resolver、preview、TurnProposal、validation、player confirmation 和 commit。Rules 可以留在 trace/telemetry 中，也可在 external 缺失时保持现行 fallback，但不能 override、veto 或仅因 mismatch 强制 clarification。

High confidence 适用于根因、调用链和最小改动边界。真实 playtest 数据仍缺失，所以尚不能量化准确率收益；这不影响诊断结论，只影响上线后的质量评估。

## Recommended Next Steps

### Fix direction

1. **Authority mechanism:** 在 `AIIntentRouter`/arbiter 中增加 mode-gated external-only decision，并允许 off + external adoption。
2. **Preview mechanism:** routed external/AI intent 不再受关键词 mismatch hard veto；直接低层 `preview_action` 保留现有 guard。
3. **Boundary preservation:** 不修改 resolver、SaveManager pending/confirm、validation、commit、public CLI/MCP signatures 或 platform forwarding。
4. **Non-goal:** 首个修复不收紧 off + no-external fallback；canonical restricted fallback 差异另立 P0 决策。

### Remaining diagnostics

1. 收集真实 `user_text / external candidate / current route / expected route` transcript，量化修复收益。
2. 单独决定 no-external fallback 是否应从当前 unrestricted 行为收紧到 canonical restricted policy。

## Reproduction Plan

已完成四类 route baseline，并新增 preview veto repro：“不要采集，休息到明早”在 external/internal 都选择 rest 时仍被关键词 guard 判为 gather。实施后重新运行这些 repro、Acceptance Matrix、intent eval/canary、current-native player-turn、MCP/CLI/platform 和 validation suites。

## Next Workflow

1. **Recommended:** `bmad-correct-course`，为该 P0 authority 变更更新 canonical contract、范围和验收标准。
2. **Then:** `bmad-create-story`，把 Minimal Change Boundary 与 Acceptance Matrix 转成 tracked implementation story。
3. **After implementation:** `bmad-code-review`，重点审查规则是否仍在任何 routed AI path 拥有 override/veto 权，以及保存边界是否保持不变。

## BMAD Provenance

- Trigger: 用户调用 `bmad-investigate`，随后要求覆盖旧 case file 并逐 Outcome 继续。
- Skill: `.agents/skills/bmad-investigate/SKILL.md`。
- Customization: workflow prepend/append 均为空；persistent fact 为 project context；case path 位于 implementation artifacts；`on_complete` 为空。
- Config: communication/document output 使用中文；artifact root 为 `_bmad-output/implementation-artifacts`。
- Verification: focused pytest、临时 Runtime/binder repro、Git history/blame、targeted Ruff；正式 current-native save 由 read-only test contract 保护。

## Side Findings

- Confirmed: 本文件已按用户要求覆盖重建；旧调查内容不再作为当前结论。
- Confirmed: repo 内未发现独立 diagnostic archive、issue/ticket artifact 或 playtest transcript。
- Workflow note: docs 盘点代理正常返回；source/tests 代理超时后被终止，相关证据改由 scoped local reads 和 focused tests 核验。
- Workflow note: Outcome 3 safety-chain 代理同样超时并被终止；结论由四文件 scoped read、临时实验和 4 个 focused tests 独立核验。
- Workflow note: Outcome 4 两路 source/caller 代理超时并被终止；改用分段本地 source trace 与入口/validation focused suite 核验。

## Follow-up: 2026-07-10

### New Evidence

- Canonical docs 盘点完成；发现 off-mode precedence 未定义。
- Core source 显示 external/rules 会并行准备，但 adoption 只在 consensus mode 发生。
- `6 passed in 1.69s`：现行规则优先、安全 schema gate、consensus adoption、CLI/MCP 边界均与代码一致。
- Targeted Ruff：`All checks passed!`。
- Git blame：关键 selection 表达式来自 baseline commit `3df5748`，无独立 rationale。

### Additional Findings

- Finding 5-9 已加入。

### Updated Hypotheses

- Hypothesis 1-3 均保持 Open；Outcome 2 只确认调查边界，不把方案假设升级为结论。

### Backlog Changes

- #1 canonical docs、#3 tests 标为 Done。
- #2 core source、#6 entrypoints 标为 In Progress。
- 新增 #7 设计 rationale / ADR / ticket 查找。

### Updated Conclusion

Evidence perimeter 已完成。当前实现与测试一致地采用 off-mode rules-first；规范未决定该优先级。进入 Outcome 3 前仍保留真实失败样例和完整安全矩阵两个关键缺口。

## Follow-up: 2026-07-10 #2

### New Evidence

- Arbiter 在 external 存在、internal 缺失时没有 external-only adoption branch，直接进入 rules fallback。
- Router 只在 consensus mode 将 arbiter decision 转成 route outcome，形成第二个独立锁点。
- 四类临时实验完成；正向规则误判和反向 external 误判均可重复。
- 错误 external social candidate 通过 schema/action registry/entity binding，证明结构验证不等于语义验证。
- `4 passed in 1.17s`：mismatch、hidden-info、rules risk 与高风险 fallback 安全行为保持有效。

### Additional Findings

- Finding 10-13 已加入；root cause 从单一 router fallback 更新为 arbiter + router 双重 authority gate。

### Updated Hypotheses

- Hypothesis 1 保持 Open：机械可行性已支持，真实准确率收益仍缺数据。
- Hypothesis 2 更新为 Confirmed：无 external 的合法入口仍依赖 restricted rules fallback。
- Hypothesis 3 更新为 Refuted：blanket mismatch-clarify 会让错误 rules 继续拥有否决权。

### Backlog Changes

- #5 strategy comparison 标为 Done。
- #2 保持 In Progress，剩余 resolver/validation 精确 trace。
- #6 保持 In Progress，剩余 CLI/platform 源码逐入口复核。

### Updated Conclusion

推荐策略已收敛为 external-primary + engine-verified，而不是删除所有 rules 或无条件信任 external。Outcome 4 需要把该策略落到精确 source boundary 和测试矩阵后，才能完成调查。

## Follow-up: 2026-07-10 #3

### New Evidence

- Route 后仍存在 `preview_action_mismatch_guard` 关键词 hard veto，形成第三个规则控制点。
- Query 与 action 在 `ActionIntent` 后进入通用 Runtime 路径，不需要为 external-primary 新建 resolver 或 commit 流程。
- CLI/MCP `player_turn` 已支持 external candidate 且默认 intent AI off；platform 不传 external 且默认 consensus。
- Archived implementation log 确认 trace-only 是历史兼容策略，而不是参数漏传。
- Focused verification：入口/validation `4 passed in 0.17s`；current-native `2 passed, 12 subtests passed in 80.60s`。

### Additional Findings

- Finding 14-18 已加入。
- Root cause 更新为三处：arbiter、router、preview mismatch guard。
- 发现 canonical restricted rules fallback 与当前 off-mode 实现存在独立差异。

### Updated Hypotheses

- Hypothesis 1 保持 Open，仅保留真实准确率收益缺口。
- Hypothesis 2 保持 Confirmed，但首个修复只保留现行 no-external fallback，不夹带 risk 收紧。
- Hypothesis 3 保持 Refuted。

### Backlog Changes

- #2 source trace、#6 entrypoints、#7 historical rationale 标为 Done。
- 仅剩真实失败样例与后续实施验证；它们不再阻塞 root-cause conclusion。

### Updated Conclusion

Source trace 已达到 hand-off 标准。首个修复范围可限制在 intent arbitration/adoption、route adapter 和 route-aware preview mismatch guard；保存、验证、提交和 platform 边界不需要修改。

## Follow-up: 2026-07-10 #4

### Finalization

- Hand-off Brief 已重写为最终三句版本。
- Case status 更新为 Concluded。
- Final Conclusion 置信度为 High；真实准确率收益作为独立数据缺口保留。
- Fix direction、Remaining diagnostics、Reproduction Plan、Next Workflow 和 BMAD Provenance 已最终化。
- `workflow.on_complete` 为空，无额外自动动作。
