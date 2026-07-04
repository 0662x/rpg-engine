---
title: "AIGM Kernel Foundation Story Remediation Sprint Change Proposal"
status: approved
created: "2026-07-04"
updated: "2026-07-04"
workflow: bmad-correct-course
mode: incremental
changeScope: moderate
sourceReadinessReport: "_bmad-output/planning-artifacts/implementation-readiness-report-2026-07-04.md"
affectedArtifacts:
  - "_bmad-output/planning-artifacts/epics.md"
approvedEditProposals:
  - story-2-6-cross-campaign-forward-dependency
  - story-1-6-cli-mcp-platform-split
  - story-3-2-hidden-safe-split
  - story-4-4-resident-ai-advisory-split
  - story-4-5-and-5-5-proposal-boundary
  - story-5-1-campaign-diagnostics-split
  - story-5-7-residual-risk-gates
---

# Sprint Change Proposal：AIGM Kernel Foundation Stories 修正

## 1. 问题摘要

本次 Correct Course 的触发来源是 `[IR] Check Implementation Readiness` 评估报告。报告结论为 `NEEDS WORK`：PRD、Architecture 和 Epics 的方向一致，PRD 的 17 个 FR 均已有 Epic/Story 覆盖，但当前 `epics.md` 的部分 story 还不够适合直接进入实现。

核心问题不是产品目标错误，也不是架构方向错误，而是 story 级规划需要修正：

- 部分 story 粒度过大，容易形成横跨多模块的大 PR。
- `Story 2.6` 在 Epic 2 阶段要求完整 `context assembly` 和 player-safe play loop，存在依赖 Epic 3 的前向依赖风险。
- `Story 4.5` 与 `Story 5.5` 都触及 proposal/review/application 语义，需要明确职责边界。
- 部分验收条件缺少具名 fixture、focused gate 或可执行的 evidence gate。

支持证据：

- `implementation-readiness-report-2026-07-04.md` 记录 `Critical: 0`，`Major: 5`，`Minor: 5`，`Warning: 1`。
- 主要 Major issues 指向 `Story 2.6`、`Story 1.6`、`Story 3.2`、`Story 4.4`、`Story 5.1`。
- 该报告建议先做 story remediation pass，再重新跑 `[IR]` readiness。

## 2. 影响分析

### Epic 影响

Epic 结构不需要重建。保留当前 5 个 Epic 和顺序：

1. Epic 1：可信本地游玩闭环与入口权限
2. Epic 2：通用 Campaign/Save 世界模型
3. Epic 3：Visibility-Safe Context 与长期记忆
4. Epic 4：AI Intent 与 Resident Advisory Loop
5. Epic 5：作者/主持诊断与内容治理

需要调整的是部分 story 的粒度、位置、编号和验收条件。

### Story 影响

| 原 Story | 影响 | 处理方式 |
| --- | --- | --- |
| Story 1.6 | 过宽，混合 MCP、CLI、platform、audit | 拆成 MCP profile、CLI thin adapter、platform forwarding/audit 三个 stories |
| Story 2.6 | 可能提前依赖 Epic 3 context 能力 | 收窄为 Epic 2 model smoke，完整 context/play-loop smoke 移到 Epic 3 后 |
| Story 3.2 | hidden-safe 范围过宽 | 拆成核心 context/query/prompt 与 derived artifacts/search/cards 两个 stories |
| Story 4.4 | 可能演变为全 helper 大迁移 | 拆成 advisory envelope contract 与代表性 adapter |
| Story 4.5 | 与 proposal queue lifecycle 混淆 | 明确只负责 AI suggestion -> review artifact |
| Story 5.1 | Campaign diagnostics 覆盖面过宽 | 拆成结构诊断、引用/进度诊断、context usability/capability 诊断 |
| Story 5.5 | 与 Story 4.5 语义重叠 | 明确负责 proposal queue state machine、apply、revert、report |
| Story 5.7 | evidence gate 太抽象 | 具体列出可接受 gate 类型 |

### Artifact 冲突

- PRD：不需要修改。FR、MVP scope、NFR 和非目标仍有效。
- Architecture：不需要修改。当前 architecture 已经定义需要的 contract families 和 invariants。
- UX：无独立 UX artifact；当前 v1 是 CLI/MCP/kernel-first，UX 缺口仍为非阻塞 warning。
- Canonical docs：本次 proposal 不直接修改 canonical docs。后续 implementation stories 如果改变公开合同，再按 story gate 同步相关 docs。

### 技术影响

本次 Correct Course 不直接改代码，不引入 migration，不改 schema。技术影响体现在后续实现计划更小、更可验收：

- 降低 cross-module story 同时触碰 MCP/CLI/platform/context/AI/proposal 的风险。
- 提前明确 focused gates，减少实现阶段临时挑测试的随意性。
- 保持 `AI proposes. Kernel verifies. Player confirms. Engine commits.` 不变量。

## 3. 推荐方案

推荐路径：`Direct Adjustment`。

调整范围：只修改 `_bmad-output/planning-artifacts/epics.md`，并在完成后重新运行 `[IR] Check Implementation Readiness`。

不推荐路径：

- Rollback：不适用。当前尚未进入 sprint implementation，没有已完成 story 需要撤回。
- PRD MVP Review：不需要。MVP 目标和 FR 仍然成立，问题在 story 分解层。
- Architecture redo：不需要。Architecture 已经支持所需边界，问题在 story 落地粒度。

工作量估计：Medium。

风险等级：Low-to-Medium。风险主要来自 Story 编号重排和 FR coverage map 同步，不来自产品或架构不确定性。

## 4. 详细修改提案

### 4.1 修正 Story 2.6 前向依赖

Story：`Story 2.6: Cross-Campaign Foundation Smoke`

旧问题：

```markdown
**When** each package runs init, save inspect, campaign validate, campaign test, context assembly, basic query, preview, validation, and a safe play loop on temp saves
```

这个验收条件在 Epic 2 阶段要求完整 `context assembly`、ordinary query、preview、validation 和 safe play loop，容易依赖 Epic 3 才建立的 Context Slice / hidden-safe context 能力。

新方案：

- 将 Story 2.6 改为 `跨 Campaign 的模型边界冒烟测试`。
- Story 2.6 只验证 Campaign/Save ownership、Content Type / Merge、Entity、Relationship 和 Progress access contracts。
- 将完整 context/play-loop 冒烟测试新增为 Epic 3 后的 story。

拟改后 Story 2.6：

```markdown
### Story 2.6: 跨 Campaign 的模型边界冒烟测试

作为引擎作者，
我希望至少两个不同 Campaign Package 能复用同一套 Campaign/Save 模型边界，
从而证明 Kernel 的 package、entity、relationship 和 progress 基础不是某一个战役的专用实现。
```

新增 Story：

```markdown
### Story 3.7: 跨 Campaign 的 Context 与玩家安全回路集成冒烟测试

作为引擎作者，
我希望在 Context Slice 基础完成后，再用跨 Campaign 冒烟测试覆盖 context assembly 和基础 player-safe loop，
从而证明通用 Kernel 行为成立，同时避免 Epic 2 依赖 Epic 3。
```

理由：保留 FR-13 / FR-17 的跨 Campaign 证明，同时去掉 Epic 2 对 Epic 3 的前向依赖。

### 4.2 拆分 Story 1.6

Story：`Story 1.6: Thin CLI, MCP, and Platform Adapters`

旧问题：一个 story 同时覆盖 MCP `player` profile、CLI command groups、platform forwarding 和 audit logging。

新方案：

- `Story 1.6: MCP Player Profile 权限门`
- `Story 1.7: CLI 命令薄适配边界`
- `Story 1.8: Platform Forwarding 与审计边界`

旧文案：

```markdown
### Story 1.6: Thin CLI, MCP, and Platform Adapters

As an integrator,
I want CLI, MCP, and platform entry points to be thin wrappers over kernel services,
So that there is one gameplay business logic path instead of duplicated authority at the edges.
```

新 Story 1.6 聚焦 MCP：

```markdown
### Story 1.6: MCP Player Profile 权限门

作为 AI client 集成者，
我希望默认 MCP `player` profile 只暴露 player-safe tools，
从而保证 MCP 不能绕过普通玩家的 preview、pending、confirm 和 commit 边界。
```

新增 Story 1.7 聚焦 CLI：

```markdown
### Story 1.7: CLI 命令薄适配边界

作为本地 host，
我希望 CLI player/platform/mcp 入口只调用 Kernel services，
从而避免 CLI 复制 intent、preview、validation 或 commit 业务逻辑。
```

新增 Story 1.8 聚焦 platform/audit：

```markdown
### Story 1.8: Platform Forwarding 与审计边界

作为 platform 集成者，
我希望 platform sidecar 只做 session/actor gate、preflight identity 转发和 SaveManager forwarding，
从而保证平台消息不会获得额外 gameplay fact authority。
```

理由：每个 story 只触碰一个主要 surface，便于 focused tests 和 code review。

### 4.3 拆分 Story 3.2 hidden-safe 范围

Story：`Story 3.2: Hidden-Safe Context Collection`

旧问题：

```markdown
**When** player-safe context, ordinary query, scene output, onboarding, snapshots, cards, FTS, or player-safe AI prompts are built
```

该条件横跨核心 context/query/prompt 和 derived artifacts/search/cards/snapshots，范围过宽。

新方案：

- `Story 3.2: Player-Safe Context、Query 与 Prompt 隐藏信息边界`
- `Story 3.3: 派生玩家视图与检索产物的隐藏信息边界`

新 Story 3.2：

```markdown
### Story 3.2: Player-Safe Context、Query 与 Prompt 隐藏信息边界

作为玩家，
我希望 hidden 和 GM-only 信息不会进入 player-safe context、ordinary query、scene output 或 player-safe AI prompts，
从而让游戏可以保留秘密，同时仍能让 AI 主持可见内容。
```

新增 Story 3.3：

```markdown
### Story 3.3: 派生玩家视图与检索产物的隐藏信息边界

作为玩家，
我希望 cards、snapshots、FTS、onboarding 和其他派生玩家视图也不包含 hidden / GM-only 信息，
从而避免隐藏内容通过 read model 或搜索产物泄漏。
```

编号影响：

- 原 Story 3.3 改为 Story 3.4。
- 原 Story 3.4 改为 Story 3.5。
- 原 Story 3.5 改为 Story 3.6。
- 新增 cross-campaign context/play-loop smoke 为 Story 3.7。

理由：把 hidden 核心路径和派生 read models 分开，降低高风险 visibility story 的实现面。

### 4.4 拆分 Story 4.4 Resident AI Advisory

Story：`Story 4.4: Resident AI Advisory Envelope`

旧问题：

```markdown
**Then** implementation reuses existing `ai/`, `ai_intent/`, semantic, archivist, reflection, memory, state audit, delta draft, response acceptance, turn assistant, and proposal queue foundations where practical
```

该条件范围太大，且 `where practical` 不够可测。

新方案：

- `Story 4.4: Resident AI Advisory Envelope Contract`
- `Story 4.5: Resident AI Advisory 代表性适配`

新 Story 4.4：

```markdown
### Story 4.4: Resident AI Advisory Envelope Contract

作为引擎作者，
我希望 resident AI 输出共享一个 advisory envelope contract，
从而让意图识别、上下文总结、实体维护、进度管理和剧情推进建议都可追踪、非权威、可调试。
```

新增 Story 4.5：

```markdown
### Story 4.5: Resident AI Advisory 代表性适配

作为引擎作者，
我希望先把少量代表性 AI/helper 输出接入 Resident AI Advisory Envelope，
从而验证 envelope 可以复用现有实现，而不需要一次性重写所有 helper 模块。
```

编号影响：

- 原 Story 4.5 改为 Story 4.6。
- 原 Story 4.6 改为 Story 4.7。

理由：先定义 contract，再接入代表性 adapters，避免一次性迁移所有 helper modules。

### 4.5 澄清 Story 4.6 与 Story 5.7 的 proposal 分工

原 Stories：

- `Story 4.5: Entity, Relationship, and Progress Advisory Review`
- `Story 5.5: Proposal Queue Apply and Revert Rules`

编号调整后：

- 原 Story 4.5 变为 `Story 4.6`
- 原 Story 5.5 变为 `Story 5.7`

旧问题：两个 story 都触及 proposal/review/application，容易混淆职责。

新方案：

- Story 4.6 只负责 AI suggestion 进入显式 review artifact。
- Story 5.7 负责 proposal queue 状态机、apply、revert、report。

Story 4.6 新边界：

```markdown
**And** 本 story 不负责 proposal queue state transitions、apply、revert 或 batch review。
```

Story 5.7 新边界：

```markdown
**Then** 状态转换必须符合明确 allowed transitions
**And** application 必须使用对应 write、maintenance 或 commit path，而不是 queue state 本身。
```

理由：Epic 4 保持 advisory/review artifact 边界，Epic 5 承担治理和 lifecycle。

### 4.6 拆分 Story 5.1 Campaign diagnostics

Story：`Story 5.1: Campaign Foundation Diagnostics`

旧问题：

```markdown
**Then** they cover YAML/manifest/schema parse, required roots, content paths, entity references, relationship endpoints, progress/clock completeness, capability declarations, smoke test matching, visibility risks, missing summaries, and missing aliases
```

该条件把结构、引用、进度、visibility、capability、context usability 全放进一个 story。

新方案：

- `Story 5.1: Campaign Package 结构诊断`
- `Story 5.2: Campaign 引用、Relationship 与 Progress 诊断`
- `Story 5.3: Campaign Context Usability 与 Capability 诊断`

新 Story 5.1：

```markdown
### Story 5.1: Campaign Package 结构诊断

作为 Campaign 作者，
我希望 v1 diagnostics 先捕获 package 结构、manifest、schema 和路径问题，
从而在内容进入运行态前发现会导致导入或验证失败的基础错误。
```

新增 Story 5.2：

```markdown
### Story 5.2: Campaign 引用、Relationship 与 Progress 诊断

作为 Campaign 作者，
我希望 diagnostics 能发现 entity reference、relationship endpoint 和 progress/clock completeness 问题，
从而避免 AI 主持时遇到断裂事实、坏引用或无法解释的进度状态。
```

新增 Story 5.3：

```markdown
### Story 5.3: Campaign Context Usability 与 Capability 诊断

作为 Campaign 作者，
我希望 diagnostics 能发现 capability declarations、smoke tests、summary 和 aliases 的可用性问题，
从而提升 AI context 质量，而不评价文笔或剧情品味。
```

编号影响：

- 原 Story 5.2 改为 Story 5.4。
- 原 Story 5.3 改为 Story 5.5。
- 原 Story 5.4 改为 Story 5.6。
- 原 Story 5.5 改为 Story 5.7。
- 原 Story 5.6 改为 Story 5.8。
- 原 Story 5.7 改为 Story 5.9。

理由：按 diagnostics 类型拆分，便于 fixture 和 focused gate 管理。

### 4.7 具体化 Story 5.9 Residual Risk Evidence Gates

Story：原 `Story 5.7: Residual Risk Evidence Gates`，编号调整后为 `Story 5.9`。

旧问题：

```markdown
**And** it selects the smallest meaningful evidence gate.
```

该条件太抽象，难以验收。

新方案：

```markdown
**And** 它必须选择至少一个具体 evidence gate：focused unit test、SQLite/package integration test、CLI/MCP system test、current native regression、markdown/docs gate、manual inspection checklist，或明确说明为什么该 gate 不适用。
```

同时为 hidden/export/AI egress、backup/restore/archive/import、future coordinator/orchestration 分别补充更具体的 gate 说明。

理由：让 residual risk gate 可执行、可检查、可写入 story validation。

### 4.8 编号与覆盖表一致性更新

实施上述修改时，必须同步更新：

- `FR Coverage Map`
- `Epic List`
- Epic 3 / Epic 4 / Epic 5 的 story 编号
- 所有引用旧 Story 编号的文本

FR 覆盖不变：

- FR-1、FR-2、FR-3、FR-14、FR-16 仍由 Epic 1 覆盖。
- FR-7、FR-8、FR-13、FR-17 仍由 Epic 2 覆盖。
- FR-10、FR-11、FR-12 仍由 Epic 3 覆盖。
- FR-4、FR-5、FR-6、FR-9 仍由 Epic 4 覆盖。
- FR-15 仍由 Epic 5 覆盖，并继续强化 FR-9、FR-13、FR-17。

## 5. 实施交接

Change scope：Moderate。

建议交接：

- Planning / Product agent：按本 proposal 修改 `epics.md`。
- Readiness reviewer：修改后重新运行 `[IR] Check Implementation Readiness`。
- Developer agent：只有在 IR 状态变为 `READY` 或用户明确接受剩余风险后，才进入 `[SP] Sprint Planning`。

成功标准：

- `epics.md` 中所有新增/拆分 stories 均保持 FR traceability。
- 不新增 PRD scope，不改变 Architecture invariants。
- Story 2.6 不再依赖 Epic 3。
- Story 1.6、3.2、4.4、5.1 不再是过宽 story。
- Story 4.6 与 Story 5.7 的 proposal/review/apply/revert 分工清楚。
- Story 5.9 的 evidence gate 可执行。
- 重新运行 `[IR]` 后 readiness 目标为 `READY`。

## 6. 用户审核状态

Incremental review 已批准的修改提案：

- Approved：Story 2.6 前向依赖修正。
- Approved：Story 1.6 拆分。
- Approved：Story 3.2 hidden-safe 拆分。
- Approved：Story 4.4 Resident AI Advisory 拆分。
- Approved：Story 4.5 / Story 5.5 proposal 分工澄清。
- Approved：Story 5.1 Campaign diagnostics 拆分。
- Approved：Story 5.7 residual risk evidence gates 具体化。

完整 Proposal 审核：

- Approved：用户于 Correct Course Step 5 回复 `y`，按 `yes` 处理，批准本 Sprint Change Proposal 进入实施。

## 7. 实施路由与工作流完成记录

Scope classification：Moderate。

实施路由：

- Routed to：Product Owner / Developer agents。
- Planning / Product agent 责任：按本 proposal 修改 `_bmad-output/planning-artifacts/epics.md`，同步 story 编号、`FR Coverage Map` 和 `Epic List`。
- Readiness reviewer 责任：修改后重新运行 `[IR] Check Implementation Readiness`。
- Developer agent 责任：在 readiness 变为 `READY`，或用户明确接受剩余风险后，进入 `[SP] Sprint Planning` 和后续 story implementation。

本 Correct Course addressed issue：

- IR 报告发现 AIGM Kernel Foundation 的 `epics.md` directionally aligned 但 story 粒度、前向依赖和验收 gate 不足，状态为 `NEEDS WORK`。

Artifacts modified：

- 新增并批准：`_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md`。
- 未直接修改：`_bmad-output/planning-artifacts/epics.md`。
- 未修改：PRD、Architecture、canonical docs、代码。

Sprint status note：

- 未找到现有 `sprint-status.yaml` / `sprint-status.yml`，因此未执行 sprint status 更新。当前项目仍处于 `[CC]` story remediation handoff，尚未进入 `[SP] Sprint Planning`。

下一步成功标准：

- 按本 proposal 更新 `epics.md`。
- 重新运行 `[IR]`，目标状态为 `READY`。
- 之后再进入 `[SP] Sprint Planning`。
