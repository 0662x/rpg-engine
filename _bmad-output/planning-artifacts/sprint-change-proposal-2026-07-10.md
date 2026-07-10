---
title: "Internal-AI-Off External Intent Proposal Authority Sprint Change Proposal"
status: approved
created: "2026-07-10"
updated: "2026-07-10"
workflow: bmad-correct-course
mode: incremental
priority: P0
changeScope: moderate
triggerInvestigation: "_bmad-output/implementation-artifacts/investigations/external-intent-authority-investigation.md"
implementationStatus: not-started
runtimeDocsStatus: deferred-until-implementation-verified
affectedArtifacts:
  - "_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md"
  - "_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md"
  - "_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md"
  - "_bmad-output/planning-artifacts/epics.md"
  - "docs/project-context.md"
  - "docs/ai-intent-chain.md"
  - "docs/architecture.md"
  - "docs/mcp-contracts.md"
  - "docs/cli-contracts.md"
  - "docs/prompt-contracts.md"
  - "docs/prompts/ai-client-prompt.md"
  - "/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/SKILL.md"
approvedEditProposals:
  - investigation-mode-qualification
  - prd-mode-gated-route-authority
  - architecture-mode-gated-route-authority
  - epic-4-story-4-1-acceptance-matrix
  - post-implementation-docs-prompt-skill-sync
---

# Sprint Change Proposal：Internal AI Off 时由 External Candidate 提供路由提案

## 1. 触发与问题摘要

本次 Correct Course 由 `external-intent-authority-investigation.md` 触发。调查确认当前实现中，
`intent_ai=off` 且调用方已经提供合法 `external_intent_candidate` 时，external candidate 会进入 trace，
但最终 route 仍由 deterministic rules 选择。即使 AI route 已被接受，Runtime 的关键词 mismatch guard
仍可能再次作 hard veto。

已确认三个控制点：

1. `rpg_engine/ai_intent/arbiter.py` 缺少 mode-gated external-only adoption branch。
2. `rpg_engine/ai_intent/router.py` 只在 consensus mode 把 arbiter decision 转成 selected route。
3. `rpg_engine/runtime.py` 的 preview mismatch guard 仍可用关键词结果否决 routed AI intent。

根本设计问题不是关键词数量不足，而是 internal AI 关闭时，Engine 仍使用 deterministic NLU 结果覆盖外部
已经理解好的意图。开放式自然语言继续依赖规则扩充无法稳定解决该冲突。

本提案严格区分两类 authority：

- **Route proposal authority**：决定本次请求按哪个 query/action/mode/slots 进入 Engine 校验和执行链。
- **Fact / permission / confirmation / commit authority**：决定事实、hidden access、玩家确认、proposal approval
  和保存；这些权限始终不授予 external 或 internal AI。

## 2. 决策矩阵

| 输入状态 | Route proposal authority | Rules 角色 | 后续边界 |
| --- | --- | --- | --- |
| internal intent AI enabled；external 存在 | 保持 external/internal arbitration | 保留现有 provenance、risk 和 fallback 角色 | agree/clarify/block 后仍进入 binder、preview、validation、confirm/commit |
| internal intent AI off；合法 external 存在 | external candidate | 仅记录 trace / diagnostic evidence；不得 override、veto 或仅因 mismatch 强制 clarification | Engine 执行 schema、registry、safety、binding、resolver、preview 和 validation |
| internal intent AI off；external 缺失 | 首个修复保持当前 deterministic rules fallback | 当前兼容行为不变 | no-external fallback 是否收紧另立 P0 决策 |

关键限定：只有 `internal intent AI off + 合法 external candidate` 这一分支由 external 拥有 proposal authority。
Internal AI 开启时，external 不无条件优先。

## 3. 影响分析

### PRD 与 Architecture

PRD 的产品方向不变，仍是 AI-first interpretation、kernel-enforced facts。本次只消除“low-trust 等于规则永远
拥有路由否决权”的歧义，并在 FR-4、NFR-1 和术语中加入 mode matrix。

Foundation 与 execution-chain architecture 不重做。`AD-2` 现在允许 coordinator 按显式 mode 选择 route
proposal，同时继续禁止其 preview、validate、confirm、commit、绕过 hidden gate 或构造 trusted delta。

### Epic 与 Story

Epic 结构和顺序不变。Story 4.1 仍是 `Low-Trust Intent Candidate Contract`，但验收标准已加入：

- off + external 的 proposal authority。
- enabled + external 的现有仲裁行为。
- off + no external 的现有 fallback。
- invalid candidate、keyword mismatch guard、query/pending/confirm 边界。

Story 4.2 增加 enabled-timeout 限制：internal review 超时或不可用不能被偷偷解释为显式 off，也不能因此
给 external 无条件 proposal authority。

Story 4.1 当前仍为 backlog，因此无需回滚已完成 story，也无需重排 sprint。`sprint-status.yaml` 的 story key
和状态不需要在本次 Correct Course 中修改。

### Public Interfaces

CLI/MCP 方法名、参数和默认 profile 不变：

```text
player_turn(user_text, optional external_intent_candidate)
  -> query / clarification / blocked / pending action
  -> player_confirm(session_id)
  -> validated commit
```

本次改变的是 Engine 内部 route selection 语义，不是 surface shape。`player_act` 继续不接收 external candidate；
platform sidecar/prewarm 继续不新增 external candidate 参数。

### UX、Schema 与 Migration

- 无独立 UX artifact；本项目当前为 CLI/MCP/kernel-first，本次无 UI 变更。
- 不改 Save schema、Campaign schema、TurnProposal schema 或 migration。
- 不改 active save facts，不需要数据迁移或 rollback migration。

## 4. 方案比较

### Option 1：Direct Adjustment（推荐）

在现有 arbiter/router/runtime 边界内增加 mode-gated external-primary branch，保留所有 Engine 安全和写入门。

- **工作量：** Medium。
- **风险：** P0 / High behavioral risk，但 blast radius 可由 mode gate 和 focused tests 限定。
- **优点：** 修复根因，不扩充关键词，不改变公共接口或存档边界。

### Option 2：Rollback

不适用。当前 rule-first/trace-only 是历史兼容策略，不是近期可回滚的一次独立功能提交；回滚也会破坏之后的
intent refactor 和公开入口契约。

### Option 3：MVP / PRD 重审

不需要。AI-first、local-first、player confirmation 和 kernel fact authority 的 MVP 方向仍成立；问题是既有
low-trust 表述没有区分 route proposal 与 write authority。

## 5. 实施边界

### Must Change

| 文件 | 责任 |
| --- | --- |
| `rpg_engine/ai_intent/arbiter.py` | 增加显式 off + external decision；不把 rules agreement 当 external adoption 条件。 |
| `rpg_engine/ai_intent/router.py` | 允许 off + external 的 accepted decision 生成 selected route；off + no external 保持现状。 |
| `rpg_engine/ai_intent/adapters.py` | 将 consensus-only route conversion 泛化为 accepted external-primary/consensus decision conversion，并保留 query/action/clarify/block 结构。 |
| `rpg_engine/runtime.py` | 让 preview keyword mismatch guard 感知 route provenance；routed external/accepted consensus 只记录诊断，不 hard veto。 |
| `tests/test_ai_intent.py` | 覆盖 mode matrix、trace provenance、invalid external、enabled consensus regression。 |
| `tests/test_runtime.py` | 覆盖 external query/action、keyword mismatch、direct low-level preview guard。 |
| `tests/test_save_manager.py` | 证明 player turn 仍只 pending，只有匹配 confirm session 才 commit。 |
| `tests/test_mcp_adapter.py`、`tests/test_v1_cli.py` | 证明公开签名/profile/输出边界不变。 |

`rpg_engine/intent_router.py` 只允许为 provenance/trace wiring 做必要调整，不得重新引入基于关键词的 external
route override。

### Must Not Change in First Fix

- Public CLI/MCP signatures、默认 profile 和 server config shape。
- Platform sidecar/prewarm 的 external candidate 边界和默认 consensus 行为。
- Action resolver implementations、TurnProposal、validation pipeline、SaveManager pending/confirm、CommitService。
- `intent_ai=off` 且 external 缺失时的现行 fallback。
- Campaign/Save package schema、SQLite facts、migration、projection/outbox authority。

## 6. 验收矩阵

| Scenario | Required result |
| --- | --- |
| off + valid bound external action + conflicting rules | external action 成为 selected route；rules 仅 trace |
| off + valid external query | 返回 player-view query；`saved=false`；不创建 action commit |
| off + malformed external schema | route 前结构化拒绝，不偷偷 fallback 到另一规则意图 |
| off + unknown action / invalid slot | blocked 或 clarification，不进入 resolver/commit |
| off + missing or ambiguous required binding | clarification，不形成 ready proposal |
| off + blocker safety flag / maintenance mode | blocked |
| routed external/accepted consensus 与 keyword guard 冲突 | mismatch 只记录诊断，不 hard veto |
| direct low-level `preview_action` 与 source text 冲突 | 现有 mismatch guard 保留 |
| off + no external | 首个修复保持当前 route 和 characterization tests |
| enabled + external/internal agree/disagree/unsafe | 现有 accepted/clarify/blocked 行为不变 |
| enabled + internal timeout/unavailable | 不自动改写为显式 off，不授予 external 无条件 authority |
| ready player action | `player_turn` 只写 pending；匹配 `player_confirm(session_id)` 才 commit |
| platform message path | 不新增 external candidate；默认 consensus 行为不变 |

## 7. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| External candidate 语义错误但 schema/binding 合法 | 仅在显式 off 生效；保留 manifest、registry、safety、binding、resolver、validation 和玩家确认；增加真实 transcript eval。 |
| 把 rules trace-only 误写成删除所有 safety guard | 测试区分 deterministic NLU mismatch 与 schema/safety/hidden/maintenance/validation guard。 |
| Internal AI enabled 路径回归 | 保留并重跑 agree/disagree/unsafe、preflight 和 timeout tests。 |
| Keyword guard 仍从其他入口否决 routed AI | trace provenance 必须贯穿 router 到 runtime；direct low-level guard 单独回归。 |
| Active docs/skill 先于代码更新而失真 | Canonical runtime docs、Prompt 和 Skill 只在实现验收通过后同步。 |
| No-external fallback 仍与 canonical restricted fallback 有差异 | 明确留作独立 P0 decision，不夹带进首个修复。 |

## 8. 文档、Prompt 与 Skill 同步

实现和 focused tests 通过后，同批更新：

- `docs/project-context.md`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/mcp-contracts.md`
- `docs/cli-contracts.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/SKILL.md`
- Skill references：`mcp-interface.md`、`ai-intent-playtest.md`

文档必须统一使用本提案的三分支 mode matrix。Prompt 删除“external candidate 永远不是最终意图 authority”
的歧义，只保留其不能成为 confirmation、preview approval、hidden permission、save approval 或 commit authority。
Prompt version 按合同变更升级。

GM Skill 从 `1.10.3` 升到 `1.11.0`，新增 `Intent Mode Matrix`，并同步默认 player-safe 流程、query/action
流程、consensus playtest、external candidate 说明和硬规则。Skill 仍以 `intent_manifest` 为 action/query/slot
参数真源。

## 9. 验证与交付门

至少运行：

```bash
python3 -m pytest -q \
  tests/test_ai_intent.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_mcp_adapter.py \
  tests/test_v1_cli.py \
  tests/test_preflight_cache.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_sidecar.py

python3 -m pytest -q \
  tests/test_current_native_context.py \
  tests/test_context_quality.py

git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

还必须用临时 save 或只读 current-native contract 复现：

- external=`rest`、rules=`gather` 的 off-mode route conflict。
- external query 的无保存路径。
- 错误 external candidate 的 schema/action/binding/safety 失败路径。
- `player_turn -> player_confirm` 的 pending/commit 边界。
- enabled consensus 与 platform/preflight regression。

真实存档游玩验证必须在代码和 focused tests 通过后进行；测试前先确认 active save 和 backup/只读策略，不以
手写 SQLite 或绕过 player-safe gate 的方式验证。

## 10. Handoff

1. 本提案最终批准后，使用 `bmad-create-story` 从 Story 4.1 和本提案生成 implementation story。
2. 实现仅触碰 Must Change 边界，并先写/更新 mode-matrix characterization tests。
3. 使用 `bmad-code-review` 检查任何 rules/keyword 路径是否仍能 override routed external/accepted consensus。
4. 实现验收通过后再同步 canonical runtime docs、Prompt 和 GM Skill。
5. 最后运行真实 save player-safe playtest，验证可查询、可预演、可确认、可提交且状态连续。

## 11. 最终批准状态

当前状态：`approved`。

已完成：

- 调查矩阵措辞收紧为 `internal AI off + external/rules conflict`。
- PRD mode matrix 更新。
- 两份 Architecture Spine 更新。
- Epic 4 / Story 4.1 与 Story 4.2 验收更新。
- Post-implementation canonical docs、Prompt 和 Skill 同步方案获增量批准。

尚未开始：

- Engine 代码和测试修改。
- Active runtime docs、Prompt 和 Skill 修改。
- 真实存档游玩验证。

本完整 Sprint Change Proposal 已获用户最终批准，可以进入 implementation story handoff。Story 4.1 的编号、
status key 和 backlog 状态均未改变，因此本次 Correct Course 不修改 `sprint-status.yaml`。
