---
title: "Intent Contract、Session Reliability 与 Hermes 集成拆分 Sprint Change Proposal"
status: approved
created: "2026-07-13"
updated: "2026-07-13"
workflow: bmad-correct-course
mode: batch
priority: P0
changeScope: moderate
implementationStatus: backlog-updated
triggerInvestigations:
  - "_bmad-output/implementation-artifacts/investigations/intent-mode-mismatch-mcp-call-investigation.md"
  - "_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md"
affectedArtifacts:
  - "_bmad-output/planning-artifacts/epics.md"
  - "_bmad-output/implementation-artifacts/sprint-status.yaml"
externalHandoffRepository: "/Users/oliver/.hermes/hermes-agent"
protectedStory:
  id: "4.7"
  sectionSha256: "27c2a9538c8b83d63d66a275631a222053fc4f94237c9fd1f3ce2dc0286e3f58"
---

# Sprint Change Proposal：Intent Contract、Session Reliability 与 Hermes 集成拆分

## 1. 问题摘要

两份调查确认的是两个独立故障域与一组跨层设计债务：

1. RPG Engine 的安全核心仍然成立。external/internal AI 不拥有事实、确认或 commit 权威；
   binder、resolver、preview、validation、pending、player confirmation 和 SQLite commit 边界无需推倒重写。
2. RPG Engine 已复现 taxonomy drift、unknown safety flag 静默删除后可接受、并发 confirm 双成功响应，
   以及 provider audit 无法独立重建 route。
3. workspace pending supersede、clarification lifecycle、`start_turn` 消费 single-use preflight 是已确认行为，
   但需要产品语义；slot 多真源属于未复现 runtime failure 的设计债务。
4. “巡视”事件中的 caller candidate 与当前 canonical route contract 不一致，同时 live manifest 未暴露
   deterministic router 独有词项；Kernel 的 consensus fail-closed 正常工作。
5. MCP 工具注销是 Hermes keepalive/reconnect lifecycle 故障，请求没有到达 RPG Engine；它不能进入
   RPG Engine 的 intent 或 MCP adapter 修复 story。

本次改动属于 P0 规划：将八项产品/架构选择固定为可执行合同；在 RPG Engine 新增独立 Epic；
Hermes consumer、reconnect、自改进和跨仓 E2E 由 Hermes backlog/CI 持有；不修改 Story 4.7 的既有验收边界。

## 2. 八项产品/架构决策

| ID | 决策 | 锁定结果 | 主要 owner |
| --- | --- | --- | --- |
| D1 | Canonical taxonomy owner | 由 `ActionResolverSpec` / `ActionResolverRegistry` 持有 versioned `ActionTaxonomySpec`；`intent_router` 只保留 composite、否定、maintenance、entity/context grammar，不再维护简单同义词平行表。builtin、custom/campaign 与多语言词项均从 registry resolved projection 生成 manifest/internal prompt，并以 parity gate 约束。 | RPG Engine |
| D2 | Unknown safety 与 rolling upgrade | external boundary 对任意 unknown safety flag 结构化 fail-closed，不再静默删除。manifest 暴露 safety vocabulary version；版本/digest 不匹配返回可重试 `contract_version_mismatch`，要求刷新 manifest 后重建 candidate。旧 caller 在兼容窗口可省略 provenance，但其 flag 仍必须属于当前 allowlist。本项定级为 P1 trust-boundary hardening；在 consequence probe 证明可绕过 Kernel 已知危险语义前，不宣称已发生 security incident。 | RPG Engine |
| D3 | Pending partition | V1 保留“每个 active Save 只有一个普通玩家 pending session”，不引入 per-session 多 pending。新输入必须 compare-and-supersede：同一 identity 只有显式替代才能 supersede；不同 actor/session 返回 conflict，不得静默清除；cancel、expiry、save switch 与 orphan cleanup 明确化。 | RPG Engine |
| D4 | Concurrent confirm / replay | 只有一个 caller 返回 fresh `committed`。后续相同 command/session 返回稳定 `already_confirmed`，同时携带 machine-readable `idempotent_replay=true`；身份或 payload 不匹配返回 conflict。commit 成功但 pending 未清理即崩溃时，重试必须从 SQLite event/command evidence 识别已提交、返回 `already_confirmed` 并完成安全清理，不能再次报告 fresh commit。 | RPG Engine |
| D5 | Clarification lifecycle | clarification 使用与 pending action 相同的 1800 秒默认 TTL，支持显式 player-safe cancel。只有 `clarification_origin=candidate_contract_mismatch`、匹配 `clarification_id` 与同一 identity 时，允许同原文 + corrected candidate 重新核验；该修正不是玩家确认。真实玩家歧义仍要求 fresh player answer。MCP in-memory guard 降为 persisted SaveManager session 的镜像，不能成为第二真源。 | RPG Engine |
| D6 | `start_turn` purpose | `start_turn` 固定为纯 diagnostic/context entry，不消费 authoritative single-use preflight，也不提供 opt-in 消费开关。`IntentRequestMeta.consumer_purpose` 必须显式区分 diagnostic、formal player route 与受信 preview；只有正式 route/preview owner 可 claim evidence。 | RPG Engine |
| D7 | Manifest provenance | version/digest 是 RPG Engine MCP schema 和 external candidate envelope 的 provider contract，不只放在 Hermes host cache。stale/missing provenance 按 rollout policy 返回可重试错误；registry/taxonomy 变化后不得采用 stale candidate。Hermes 仍负责 next-model-turn barrier 和 cache refresh。 | RPG Engine + Hermes，schema 由 RPG Engine 持有 |
| D8 | Cross-repo E2E owner | Hermes CI 是真实 stdio compatibility E2E 的 primary owner，因为它控制 MCP client、tool registry、model-turn barrier 与 reconnect lifecycle；RPG Engine 提供无网络、scripted model、temporary Save 的稳定 provider fixture/entrypoint。两个仓库分别运行自身 unit/integration gates，Hermes CI 运行组合 gate。 | Hermes CI；RPG Engine 提供 fixture |

## 3. Checklist 影响分析

### 3.1 Trigger 与证据

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 1.1 Triggering story | [x] | 不是 Story 4.7 发现的问题。触发源是 2026-07-12 真实 intent mismatch/MCP outage，以及随后全链调查；既有 Story 4.1–4.3 解释了 mode/preflight 安全边界，但没有覆盖新确认的 taxonomy、version、session 与 consumer contract。 |
| 1.2 Core problem | [x] | 类型为实施中发现的 contract/ownership 缺口与跨仓责任混淆，不是 PRD 战略转向。 |
| 1.3 Evidence | [x] | exact text replay、temporary Save probes、并发 confirm barrier、preflight consumption、audit reconstruction、Hermes reconnect/parking/tool deregistration 日志均已记录。 |

### 3.2 Epic / Story 影响

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 2.1 当前 Epic 可否完成 | [x] | Epic 4 仍可按原目标完成；Story 4.7 与本次修复正交。 |
| 2.2 Epic-level change | [x] | 新增 Epic 6，避免把 session、audit、contract 与跨仓 fixture 塞入 Story 4.7 或已完成 Story 4.1–4.6。 |
| 2.3 后续 Epic 影响 | [x] | Epic 5 不需要改；其 proposal/content governance 与本次 intent/session contract 分开。 |
| 2.4 新 Epic 必要性 | [x] | 必要。问题横跨 intent contract、SaveManager、CommitService、preflight、MCP audit，且包含多项 P0 边界。 |
| 2.5 顺序/优先级 | [x] | 先完成 Epic 6 的 trust/taxonomy stories，再推进其 session/preflight/audit stories；Story 4.7 保留 backlog 和原验收边界，可独立排期。 |

### 3.3 Artifact 冲突

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 3.1 PRD | [x] | FR-1、FR-4、FR-6、FR-16 与 NFR-1/3/4 已覆盖目标；MVP 不变，不需本次改 PRD。 |
| 3.2 Architecture | [!] | 现有 AD-2、AD-3、AD-5、AD-8、AD-9 支持方向；各 implementation story 落地时需把八项决定同步到 canonical architecture/intent/MCP docs。Correct Course 本轮不提前改 runtime canonical docs。 |
| 3.3 UI/UX | [N/A] | 无独立 UX artifact；本项目为 CLI/MCP/kernel-first。 |
| 3.4 其他 artifacts | [!] | Hermes GM skill、background review、MCP reconnect tests 与 CI 只能在 Hermes 仓库更新；RPG Engine Sprint 只记录外部 dependency，不记录 Hermes story 状态。 |

### 3.4 Path Forward

| 选项 | 可行性 | 工作量 | 风险 | 结论 |
| --- | --- | --- | --- | --- |
| Direct Adjustment | Viable | High（拆成小 stories） | Medium/High | 推荐。保持安全核心，按 owner 定向收敛。 |
| Rollback | Not viable | High | High | 多数行为源自基线设计，不存在一个可安全回滚的近期提交；回滚还会损害已验证安全边界。 |
| PRD/MVP Review | Not needed | Medium | Medium | MVP、local-first、single-player 与 authority 原则仍成立。 |

推荐方案是 Direct Adjustment，change scope 为 **Moderate**：需要 backlog 重组和跨仓 handoff，
但不需要重做 PRD、Architecture Spine 或撤回已完成 stories。

## 4. Epic / Story 变更提案

### 4.1 Epic List

**OLD：** Epic List 仅含 Epic 1–5。

**NEW：** 在 Epic 5 之后新增：

```markdown
### Epic 6: Intent Contract 与 Player Session Reliability

Oliver 可以依赖 versioned intent contract、明确的 pending/clarification 生命周期、exactly-once confirmation
响应和可解释 audit；RPG Engine 负责 provider、session 与安全边界，Hermes consumer/reconnect/self-improvement
保持在独立仓库。完成后，taxonomy/safety/slot/manifest/preflight/session/audit 都有单一 owner 和可执行 gate，
且不会改变 AI、玩家确认或 commit authority。

**FRs reinforced:** FR-1, FR-4, FR-6, FR-16; NFR-1, NFR-3, NFR-4, NFR-6, NFR-7
```

### 4.2 RPG Engine Stories

新增八个 RPG Engine stories；每个 story 只实现其 owner 内的 contract，不修改 Story 4.7。

#### Story 6.1: Strict External Safety Vocabulary and Version Negotiation

- unknown external safety flag 在 external boundary 明确 rejected/blocked，不得被 normalizer 静默删除。
- schema、external normalizer、arbiter/known blocker 使用同一 versioned vocabulary 或 executable parity gate。
- manifest/candidate version skew 返回可重试 `contract_version_mismatch`；old-caller compatibility 不允许 unknown flag。
- threat/consequence matrix 覆盖 off、consensus、known-danger、new-caller/old-provider 与 old-caller/new-provider；
  保持 external low-trust、Kernel safety guard、pending/confirm/commit 边界。

#### Story 6.2: Canonical Action Taxonomy Registry Projection

- `ActionResolverSpec` / Registry 是 simple lexical taxonomy 的唯一 owner；builtin、custom/campaign、locale terms
  形成 resolved projection。
- deterministic router、live manifest 与 internal prompt 同源；`intent_router` 只保留 composite/entity/context grammar。
- “巡视/巡逻”继续路由 `routine`；现有 P0 route、hidden/entity binding 与 off-mode external-primary 规则不回退。
- manifest 生成 version/digest；registry/taxonomy 变化可被 stale contract 检出。

#### Story 6.3: Resolved Slot Contract Projection and Parity

- required、any-of、aliases、type、AI-fillable、binding、confirmation metadata 由 resolver contract 形成单一
  resolved projection；若个别 runtime table 暂不能移除，必须有 executable parity gate。
- binder、manifest、internal prompt 消费同一 projection，不改变现有 required/any-of、hidden-content 与 confirmation。
- 本 story 不压缩 route representations、不新建 Coordinator，也不声称修复未复现的 runtime defect。

#### Story 6.4: Atomic Pending Confirmation Claim and Replay Classification

- SaveManager 对 pending confirmation 执行 atomic claim；并发 caller 只有一个 fresh `committed`。
- second caller 返回 `already_confirmed` + `idempotent_replay=true`，identity/payload mismatch 返回 conflict。
- CommitService/UnitOfWork 区分 fresh commit 与 replay；事实、turn/event 仍只写一次。
- 覆盖 commit 后、pending clear 前崩溃恢复与 subprocess concurrency；玩家确认仍是普通写入门。

#### Story 6.5: Explicit Pending Supersede and Clarification Lifecycle

- 每个 active Save 保留单 pending session；same-identity explicit supersede、cross-identity conflict、save switch、
  cancel、expiry、migration/orphan cleanup 均有结构化结果。
- clarification 默认 TTL 1800 秒并支持 player-safe cancel。
- 只有 candidate contract mismatch + matching clarification id/identity 允许同原文 corrected candidate 重核；
  玩家歧义必须 fresh answer，candidate correction 不等于 confirmation。
- SaveManager 是唯一 persisted truth；MCP/Platform 只 mirror/gate/forward。

#### Story 6.6: Explicit Preflight Consumer Purpose

- `IntentRequestMeta.consumer_purpose` 明确 diagnostic、formal player route、trusted preview。
- `start_turn` 永不 claim authoritative single-use preflight；正式 route/preview 才能按 purpose claim。
- 保持 CAS、identity、TTL、message-only isolation、late/used/replay safety 与 enabled-mode degradation。
- 不把 cache 变成 proposal、permission、confirmation 或 commit authority。

#### Story 6.7: Safe Intent Audit Reconstruction Summary

- MCP/provider audit 记录 allowlisted normalized metadata，足以区分 external=query、rules=routine、selected source、
  clarification/failure class、manifest version/digest 与 preflight purpose。
- 不记录 raw slots、reason、player text、hidden context、private reasoning、provider body 或 raw session key。
- audit 仍是非权威 evidence；写入失败不改变 tool result、gate、pending 或事实提交。

#### Story 6.8: RPG Engine Compatibility Fixture for Hermes Stdio E2E

- 提供真实 stdio FastMCP provider fixture、scripted model contract、temporary Save 和 deterministic transcript hooks。
- fixture 覆盖 manifest version/digest、candidate rejection/refresh、next-turn ordering、player_turn/confirm 与安全 audit；
  不依赖网络/API key，不修改 source Campaign、formal Save、registry 或 `data/game.sqlite`。
- RPG Engine CI 只验证 provider fixture；完整 Hermes client/reconnect/tool-registration 组合 gate 由 Hermes CI 持有。

### 4.3 Story 4.7 保护边界

Story 4.7 的标题、用户价值与三组 Acceptance Criteria 全部保持原文。审批后编辑前后必须验证该 section 的
SHA-256 均为：

```text
27c2a9538c8b83d63d66a275631a222053fc4f94237c9fd1f3ce2dc0286e3f58
```

本次不向 Story 4.7 塞入 taxonomy、MCP reconnect、manifest barrier、pending、preflight purpose、audit 或 E2E AC。

## 5. Sprint Status 变更提案

**OLD：** `sprint-status.yaml` 只有 `epic-1` 至 `epic-5`；Story 4.7 为 `backlog`。

**NEW：** 保持所有既有 key/status（特别是 Story 4.7）不变，在 Epic 5 之后新增：

```yaml
  epic-6: backlog
  6-1-strict-external-safety-vocabulary-and-version-negotiation: backlog
  6-2-canonical-action-taxonomy-registry-projection: backlog
  6-3-resolved-slot-contract-projection-and-parity: backlog
  6-4-atomic-pending-confirmation-claim-and-replay-classification: backlog
  6-5-explicit-pending-supersede-and-clarification-lifecycle: backlog
  6-6-explicit-preflight-consumer-purpose: backlog
  6-7-safe-intent-audit-reconstruction-summary: backlog
  6-8-rpg-engine-compatibility-fixture-for-hermes-stdio-e2e: backlog
  epic-6-retrospective: optional
```

Hermes stories 不写入 RPG Engine `sprint-status.yaml`，避免一个仓库伪装成另一个仓库的 tracking authority。

## 6. Hermes 独立 Backlog / Handoff

以下工作只在 `/Users/oliver/.hermes/hermes-agent` 建 tracked stories；RPG Engine 的 Epic 6 只记录接口依赖：

| Hermes work package | Scope | 依赖 / 验收 |
| --- | --- | --- |
| H1 MCP reconnect lifecycle and nested exception observability | `tools/mcp_tool.py` keepalive failure、stdio teardown、initialize、tool re-register、parking/recovery；递归展开 `BaseExceptionGroup`，记录 child PID/PGID/watchdog/leaf exception。 | 自动恢复后 tools 重新注册且请求到达 provider audit；连续失败只在真实不可用期间注销。 |
| H2 Manifest next-model-turn barrier and GM skill correction | 获取 live manifest 后必须进入新模型轮再生成 candidate；消费完整 taxonomy/version/digest；移除“巡视→craft”静态错误项，static pitfall 不覆盖 current evidence。 | exact transcript 断言 manifest result 先可见、candidate JSON 与 `routine` contract 一致、stale digest 触发 refresh。 |
| H3 Background technical-claim evidence gate | classifier/API/kernel 行为的 durable skill claim 必须有 raw/tool evidence + deterministic reproduction/test；否则只能写 unverified session note。 | background fork 无证据时不能把推断升级为 confirmed durable claim；patch 保留 provenance。 |
| H4 Cross-repo stdio compatibility E2E | Hermes CI 启动 RPG Engine Story 6.8 fixture，驱动真实 client、tool registration、next-model-turn barrier、player_turn/confirm 与 reconnect。 | 无网络/API key；temporary Save；provider/consumer release compatibility 可定位；不修改正式数据。 |

H1 是第二份调查中的独立 MCP outage 修复；H2–H4 是 full-chain 调查的 consumer/self-improvement/E2E 工作。
这些 story 不得回写成 RPG Engine MCP adapter 或 Story 4.7 的验收责任。

## 7. Artifact Before / After 与理由

### `epics.md`

- **OLD：** Epic 4 承载 AI Intent/Resident Advisory，Epic 5 承载 author/content governance；没有已命名 owner
  承接 session/replay/preflight purpose/audit/compatibility fixture。
- **NEW：** 新增 Epic 6 与八个小 stories；Epic 4/5 既有内容保持原样。
- **理由：** 避免修改已完成 stories 或把十个工作包合并为大 Coordinator；让 P0 boundary tests 按 owner 收敛。

### `sprint-status.yaml`

- **OLD：** 无 Epic 6 key。
- **NEW：** 只新增 Epic 6 / 6.1–6.8 backlog 和 retrospective optional；既有状态不变。
- **理由：** Correct Course 只重组 backlog，不伪造 story file 或 in-progress 状态。

### PRD / Architecture / canonical docs

- **OLD/NEW：** 本轮不直接编辑。
- **理由：** PRD/MVP 不变；八项 implementation contract 在对应 story 实现并验证时同步到 architecture、
  `docs/ai-intent-chain.md`、MCP/CLI/prompt/testing 文档，避免计划先于运行事实成为 canonical 行为声明。

## 8. 排期、依赖与成功标准

推荐顺序：

1. RPG 6.1 → 6.2 → 6.3，先关闭 trust、taxonomy、version 与 slot projection。
2. Hermes H2 可在 6.2/D7 schema 固定后实施；旧静态错误项可先移除，但 barrier 验收必须绑定 provider digest。
3. RPG 6.4 → 6.5，先锁 atomic claim/replay，再调整 supersede/clarification lifecycle。
4. RPG 6.6 → 6.7，固定 consumer purpose 与 safe audit。
5. RPG 6.8 后由 Hermes H4 接入；H1 reconnect 可独立并行，但其完整 E2E 归 H4。
6. Hermes H3 独立实施，不阻塞 RPG Engine contract stories；它阻塞将本次根因作为 durable self-improvement 结论发布。

成功标准：

- 八项决定均进入对应 story AC，不留给 developer 临场选择。
- taxonomy、safety、slot、manifest、pending、clarification、preflight 与 audit 有单一 owner 或 executable parity gate。
- 并发 confirm 只有一个 fresh commit response，事实仍只写一次。
- `start_turn` 不消费 authoritative preflight。
- provider audit 可在不泄露 raw/hidden/private data 的前提下重建 route class。
- Hermes reconnect、manifest barrier、自改进 evidence gate 和真实 stdio E2E 均在 Hermes 仓库追踪。
- Story 4.7 section hash 不变。

## 9. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| Strict safety 造成版本错配 outage | version/digest negotiation、结构化 retriable mismatch、兼容窗口；unknown flag 始终 fail-closed。 |
| Taxonomy registry 演变成新的大一统 Coordinator | 只持有 lexical metadata/projection；arbiter、binder、resolver、preview、validation、commit owner 不动。 |
| 单 pending 对多入口/多 actor 不友好 | 明确 single-player V1；cross-identity conflict、explicit cancel/expiry；未来多人需求必须另开 PRD/architecture。 |
| `already_confirmed` 被客户端误当 fresh success | machine-readable `idempotent_replay`；Hermes transcript/E2E 必须区分叙事与外围副作用。 |
| Audit 增强泄露 raw data | 严格 allowlist、hash/digest、generic failure classes、hidden/privacy review。 |
| 跨仓 work 再次混入 RPG sprint | Sprint YAML 只追踪 RPG stories；Hermes story key 只出现在 handoff，不标注 RPG status。 |
| Story 4.7 被顺手扩边界 | section SHA-256 前后检查；proposal 明确禁止向 4.7 添加任何本次 AC。 |

## 10. 验证门与 Handoff

Correct Course 批准并更新两个规划文件后，至少运行：

```bash
git add -N _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

并执行结构验证：

- YAML parse `sprint-status.yaml`。
- `epics.md` 中 Epic/Story key 与 sprint status 新增 key 一一对应。
- Story 4.7 section SHA-256 保持不变。
- `git diff` 不包含 RPG Engine source、tests、Campaign、Save、registry、`data/game.sqlite` 或 Hermes 仓库修改。

批准后 handoff：

- **Product Owner / Developer：** 将 Epic 6 / 6.1–6.8 写入 RPG Engine backlog/sprint tracker；按顺序执行
  `[CS] Create Story` → `[VS] Validate Story` → `[DS] Dev Story` → `[CR] Code Review`。
- **Hermes Product Owner / Developer：** 在 Hermes 仓库创建 H1–H4 tracked stories；不得使用 RPG sprint status 代替。
- **Architect / AI Intent Safety：** 在各 story validation 中核对八项锁定决策、authority 不变量与 privacy boundary。
- **Test Architect：** 为 6.1/6.4/6.6/6.8 和 H1/H4 设计 version-skew、subprocess concurrency、purpose/CAS、real stdio gates。

## 11. 审批状态

当前状态：`approved`。

用户于 2026-07-13 明确批准本提案。Batch 模式的影响分析、八项决策、RPG Engine Epic 6 / Stories 6.1–6.8、
Sprint backlog 更新、Hermes H1–H4 独立 handoff 与 Story 4.7 保护措施均已完成。

本次只修改规划与 sprint tracking artifacts；未创建 implementation story 文件，未修改 RPG Engine source/tests、
Hermes 仓库、Campaign、Save、registry 或 `data/game.sqlite`。下一步按 `[CS] Create Story`
(`bmad-create-story:create`) 创建 Story 6.1，并在实现前运行 `[VS] Validate Story`。
