---
title: "库存消耗语义提交门 Sprint Change Proposal"
status: approved
created: "2026-07-15"
updated: "2026-07-15"
workflow: bmad-correct-course
mode: incremental
priority: P0
changeScope: minor
implementationStatus: backlog-updated
triggerTarget: "current-save-rebaseline-2026-07-15"
triggerEvidence:
  - "_bmad-output/test-artifacts/automation-validation-iteration-2.json"
  - "_bmad-output/test-artifacts/test-review.md"
  - "_bmad-output/test-artifacts/traceability-matrix.md"
  - "_bmad-output/test-artifacts/e2e-trace-summary.json"
  - "_bmad-output/test-artifacts/gate-decision.json"
affectedArtifacts:
  - "_bmad-output/planning-artifacts/epics.md"
  - "_bmad-output/implementation-artifacts/sprint-status.yaml"
---

# Sprint Change Proposal：库存消耗语义提交门

## 1. 问题摘要

2026-07-15 的 current-save 模拟用户测试重基线通过 `CON-03` 复现了一个 P0 Kernel 缺陷：
声明单物品库存消耗的结构化 delta 可以在实时数量不匹配、库存不足、payload/upsert 物品不一致或
`consumed_quantity` 为负数时通过 `player_turn_commit` validation 并正常提交。

本问题不是意图识别准确率问题，也不是 external/internal AI provider 问题。触发测试直接构造
human-confirmed `TurnProposal`，通过真实 `GMRuntime.commit_turn()`、ValidationPipeline 和 CommitService
攻击提交边界。当前 `routine` resolver validation 只检查位置与 audit event，没有核验该单物品消耗声明的
实时库存、算术和 state upsert 一致性。

本次变更采用 Direct Adjustment：在 Epic 1 增加一个独立 P0 Story，复用既有 validation/commit 架构，
不重开已完成的 Story 1.3，不把缺陷塞入 Epic 6.5，也不扩展为完整 consumption action 或库存数量战略。

## 2. 触发证据

| 证据 | 结果 | 含义 |
| --- | --- | --- |
| CON-01 | PASS | 合法结构化消耗可以精确扣减数量。 |
| CON-02 | PASS | 合法扣减可以保留物品 metadata。 |
| CRF-01 | PASS | 现有 craft 材料扣减与产出 upsert 可正常提交。 |
| CON-03 insufficient | FAIL | 库存不足仍正常 commit；pytest 为 `DID NOT RAISE ValueError`。 |
| CON-03 stale-before | FAIL | payload 的 `before_quantity` 与 SQLite 实时数量不一致仍正常 commit。 |
| CON-03 item-mismatch | FAIL | payload 的消耗物品与 upsert 物品不一致仍正常 commit。 |
| CON-03 malformed-quantity | FAIL | 负数 `consumed_quantity` 仍正常 commit。 |

执行证据：

- focused：3 passed / 4 failed，失败仅为 CON-03 四个参数案例；
- repository full pytest：1151 passed / 4 failed，另有 10331 subtests passed，失败仅为 CON-03；
- Test Review：92/100，A，Approve with Comments；测试质量本身没有 P0 blocker；
- Trace gate：FAIL；P0 FULL 25/46（54.3%），P1 FULL 2/9（22.2%）；
- source Campaign、formal Save、正式 registry 均未变化；所有写测试只使用独立 temporary Save；
- external AI 与 internal intent AI 均未参与本缺陷复现。

2026-07-01 原始消费报告和分析继续作为冻结历史证据，不覆盖、不改写。

## 3. Correct Course 检查清单结果

### 3.1 Trigger 与上下文

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 1.1 Triggering story | [x] | 触发源不是既有开发 Story，而是 `current-save-rebaseline-2026-07-15` 的 CON-03 集成测试。 |
| 1.2 Core problem | [x] | 类型为测试执行中发现的技术契约缺口；单物品消耗语义未被 pre-commit validation 强制执行。 |
| 1.3 Evidence | [x] | 四种互相独立的 P0 失败签名均通过真实 commit boundary 复现，且正式数据保护与测试隔离证据完整。 |

### 3.2 Epic / Story 影响

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 2.1 当前 Epic | [N/A] | 没有触发 Story；按 FR owner 判断，受影响的是 Epic 1 的 Validation/Commit 与 Save fact integrity。 |
| 2.2 Epic-level change | [x] | 在 Epic 1 新增 Story 1.9；不修改已 done 的 Story 1.3，不新增 Epic。 |
| 2.3 后续 Epic | [x] | Epic 4、5、6 的范围仍有效；Story 6.5 的 pending lifecycle 与本缺陷正交。 |
| 2.4 Epic 有效性 | [x] | 没有 Epic 因本问题失效，也不需要删除、重定义或新增 Epic。 |
| 2.5 顺序/优先级 | [x] | Epic 编号不变；Story 1.9 作为 P0 应先于 4.7、5.x 与 6.5–6.8 backlog 实施。 |

### 3.3 Artifact 冲突

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 3.1 PRD | [x] | FR-1、FR-14、FR-16、SM-1 已要求 validated commit 与 Save fact integrity；MVP 不变，无需修改 PRD。 |
| 3.2 Architecture | [x] | 现有 execution chain、AD-1、AD-4、AD-5 已覆盖实现位置和权威边界；无需新增架构决策。 |
| 3.3 UI/UX | [N/A] | 本项目为 CLI/MCP/kernel-first，本缺陷没有 UI/UX artifact 影响。 |
| 3.4 其他 artifacts | [x] | 更新 `epics.md` 与 `sprint-status.yaml`；实现后刷新测试执行与 Trace/gate 证据。仅在新增公共错误分类时同步 canonical docs。 |

### 3.4 Path Forward

| 选项 | 可行性 | 工作量 | 风险 | 结论 |
| --- | --- | --- | --- | --- |
| Direct Adjustment | Viable | Medium | Medium | 推荐。在现有 validation pipeline 增加窄范围语义门并运行跨 action 回归。 |
| Potential Rollback | Not viable | High | High | 没有一个近期已完成 Story 或提交可以安全回滚来解决缺失校验；回滚会损害既有闭环。 |
| PRD/MVP Review | Not needed | Medium | Medium | 缺陷违反现有 MVP 合同，不要求缩减或重新定义 MVP。 |

推荐路径为 **Option 1：Direct Adjustment**。change scope 为 **Minor**：规划上只新增一个 Story，
实现复用现有架构；由于触及 commit 前语义校验并需要跨 action 回归，实施工作量与风险均为 Medium。

## 4. Artifact 变更

### 4.1 Epic 1

**OLD：** Epic 1 结束于 Story 1.8；已完成 Story 1.3 只覆盖 proposal approval、profile compatibility、
validation evidence 与 write guard，没有明确覆盖单物品消耗的实时数量和 payload/upsert 语义一致性。

**NEW：** 在 Epic 1 增加：

### Story 1.9: 库存消耗语义提交门

作为长期存档的玩家主机，
我希望声明单物品库存消耗的结构化 delta 在提交前核验实时库存、数量算术和 payload/upsert 对齐，
从而使库存不足、过期或畸形的消耗不能成为 SQLite 事实。

**验收标准：**

**Given** 一个结构化事件通过 `consumed_item_id`、`before_quantity`、`consumed_quantity` 和 `after_quantity` 声明单物品库存消耗
**When** `player_turn_commit` validation 运行
**Then** 当前 SQLite 数量必须等于 `before_quantity`
**And** `consumed_quantity` 必须为有限正数，`after_quantity = before_quantity - consumed_quantity` 且结果不得小于零
**And** payload 的物品、单位和数量必须与唯一匹配的 `upsert_entities` 物品更新一致。

**Given** 消耗声明存在库存不足、过期 `before_quantity`、payload/upsert 物品不一致、缺失或重复更新、非法数量、单位不一致或算术不一致
**When** validation 或 commit 被调用
**Then** 提交在任何持久化之前被拒绝，并返回稳定、可断言的消耗校验错误
**And** SQLite、库存、turn、event 与 `events.jsonl` 均保持不变。

**Given** 一个合法的单物品消耗 delta
**When** 它通过已批准的 `TurnProposal` 提交
**Then** 只扣减声明的数量并保留物品的 unit、quality、properties、durability、owner、location、status、visibility 等 metadata
**And** 只产生预期的 turn 与 event，不修改其他库存。

**Given** 现有 craft、combat 或其他 action 使用不同的领域 payload contract
**When** 本 Story 的校验加入既有 validation pipeline
**Then** 其既有领域 validator 和合法提交行为不得退化
**And** 本 Story 不新增自然语言意图识别、外部或内部 AI 权威、一等 consumption action、fuzzy quantity strategy、第三方依赖或测试专用 production API。

**Given** focused 与回归测试运行
**When** 测试需要执行写入
**Then** 所有写入只针对独立 temporary Save
**And** source Campaign、formal Save、正式 registry 与 `data/game.sqlite` 事实源保持不变。

该编辑已在 Incremental 审阅中由 Oliver 明确批准并写入 `epics.md`。

### 4.2 Sprint Status

**OLD：** Epic 1 没有 Story 1.9，`last_updated` 为 `2026-07-14`。

**NEW：**

```yaml
last_updated: 2026-07-15

development_status:
  epic-1: in-progress
  1-9-库存消耗语义提交门: backlog
```

该编辑已在 Incremental 审阅中由 Oliver 明确批准并写入 `sprint-status.yaml`；其他 Story 状态不变。

## 5. PRD、Architecture 与范围边界

### 5.1 不修改的规划合同

- PRD：FR-1、FR-14、FR-16、NFR-4、SM-1 已提供充分规划依据；
- Architecture：继续使用 `ActionResolverSpec`、ValidationPipeline、CommitService、SQLite fact authority；
- Story 1.3：保持 done，不追溯改写其历史 AC；
- Story 6.5：继续只负责 pending supersede/clarification lifecycle；
- 2026-07-01 报告：保持冻结历史证据。

### 5.2 明确不在本 Story 范围

- 不恢复大规模自然语言关键词路由测试；
- 不新增一等 `consumption` action；
- 不设计或实现 fuzzy/exact/needs-audit 完整库存数量战略；
- 不改变 external/internal AI、玩家确认、proposal approval 或 commit authority；
- 不增加第三方依赖、数据库迁移或测试专用 production API；
- 不顺手修复 Trace 中其余 21 个 P0 覆盖充分性缺口或 3 个 P1 NONE；
- 不修改 source Campaign、formal current Saves 或正式 registry。

## 6. 高层行动计划与交接

| 顺序 | Owner / Workflow | 责任 |
| ---: | --- | --- |
| 1 | Product Owner / Correct Course | 将 Story 1.9 写入 Epic 1 与 Sprint backlog；本步骤已完成。 |
| 2 | Scrum Master / `bmad-create-story` | 从 Epic 1 创建 Story 1.9 artifact，引用 CON-03、Trace 和本提案，并明确范围保护。 |
| 3 | Story Validator | 完整验证 Story AC、实现可行性、测试归属与 repository boundary。 |
| 4 | Developer / `bmad-dev-story` | 在既有 validation owner 中实现单物品消耗语义门；先让 focused acceptance tests 转绿，不修改无关生产 API。 |
| 5 | Code Review | 使用 fresh Blind Hunter、Edge Case Hunter、Acceptance Auditor；去重、复现、核验范围后应用所有有效明确 patch，持续复审至 clean。 |
| 6 | Verification | 从最终 clean diff 重跑 focused、adjacent、Campaign validate/test、Markdown links、py_compile、full Ruff、diff check 与 repository full pytest。 |
| 7 | Test Architect / Trace | 更新 CON-03、STA-02 执行结果并重新生成 Trace/gate；如整体 gate 仍因覆盖缺口 FAIL，必须如实保留。 |

Correct Course 不实现生产修复，也不取得 commit/push 权威。当前 worktree 中既有未提交测试重基线资产继续保留；
后续 Story 只暂存明确归属于 Story 1.9 的生产、Story 与 acceptance-test 文件，不混入其他测试迁移工作。

## 7. Story 1.9 成功标准

Story 只有在以下条件全部满足后才能标记 done：

1. CON-03 的 insufficient、stale-before、item-mismatch、malformed-quantity 四例全部 PASS；
2. CON-01、CON-02、CRF-01 继续 PASS；
3. 非法消耗在任何持久化前拒绝，temporary Save 的 SQLite、events JSONL、库存、turn/event 计数零变化；
4. 合法扣减保持 metadata，并且不破坏 craft、combat 与其他相邻 action 的领域 validator；
5. source Campaign、formal Save、正式 registry 的前后指纹一致；
6. 所有 required gates 从最终 diff 重跑并通过，包括 repository full pytest；
7. 三路 fresh code review clean，或只剩正确记录的 dismiss/defer；
8. Story 与 Sprint 状态同步，提交只包含 Story 1.9 归属文件。

Story 1.9 完成并不自动表示整个测试重基线完成。当前 Trace 仍有 21 个 P0 覆盖充分性缺口和 3 个 P1 NONE；
修复后必须重新计算 gate，不能沿用旧 FAIL 或预先宣告 PASS。

## 8. Checklist Proposal Components

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 5.1 Issue summary | [x] | 已记录触发上下文、四类失败与实际影响。 |
| 5.2 Epic / artifact impact | [x] | 只新增 Epic 1 Story 1.9 并同步 Sprint；PRD、Architecture、其他 Epic 不变。 |
| 5.3 Recommended path | [x] | Direct Adjustment；已记录 rollback 与 PRD/MVP review 不适用的理由。 |
| 5.4 MVP / action plan | [x] | MVP 不变；已定义 BMAD 实施、review、verification 与 Trace 顺序。 |
| 5.5 Agent handoff | [x] | Product Owner、Scrum Master、Developer、reviewers 与 Test Architect 责任明确。 |

## 9. Final Review 状态

| Checklist | 状态 | 结论 |
| --- | --- | --- |
| 6.1 Checklist completion | [x] | 所有适用影响分析已完成；N/A 项有明确原因。 |
| 6.2 Proposal accuracy | [x] | 提案与 PRD、Epics、Architecture、Sprint、测试和 Trace 证据一致。 |
| 6.3 Explicit final approval | [x] | Oliver 已于 2026-07-15 明确批准完整 Sprint Change Proposal。 |
| 6.4 Sprint status update | [x] | Story 1.9 backlog 已经 Incremental 单项批准并写入 Sprint。 |
| 6.5 Next steps / handoff | [x] | 正式交给 `bmad-create-story` 创建 Story 1.9；Correct Course 不进入生产修复。 |

## 10. 最终批准记录

- 决策：**APPROVED**
- 批准人：Oliver
- 批准日期：2026-07-15
- 条件：按本提案的 P0 范围保护、完整 BMAD Story 流程和最终验证门执行。
