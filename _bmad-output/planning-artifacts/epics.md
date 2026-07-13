---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
workflowStatus: complete
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md
  - docs/architecture.md
  - docs/component-inventory.md
  - docs/data-models.md
  - docs/ai-intent-chain.md
  - docs/save-and-campaign-packages.md
  - docs/authoring-guide.md
  - docs/testing-and-quality-gates.md
  - docs/governance/content-generation.md
  - docs/cli-contracts.md
  - docs/mcp-contracts.md
  - docs/prompt-contracts.md
  - _bmad-output/planning-artifacts/bmad-residual-risk-backlog.md
  - _bmad-output/specs/spec-rpg-engine-execution-chain-architecture/SPEC.md
  - _bmad-output/specs/spec-rpg-engine-execution-chain-architecture/surface-taxonomy.md
  - _bmad-output/specs/spec-rpg-engine-execution-chain-architecture/verification-gates.md
  - _bmad-output/planning-artifacts/implementation-readiness-report-2026-07-04.md
  - _bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md
---

# AIGM Kernel Foundation - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for AIGM Kernel Foundation, decomposing the requirements from the PRD, Architecture requirements, and canonical implementation contracts into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: 引擎必须保留 player-safe flow：普通 gameplay 写入必须经过 player turn、pending action、player confirmation、validation 和 commit。

FR-2: 引擎必须按权限分类 public 和 semi-public entry surfaces：player-safe、trusted low-level、maintenance/admin、platform sidecar、platform prewarm、projection/outbox。

FR-3: Projection 和 outbox 输出必须保持为 post-commit read model 和 evidence，不能成为 gameplay fact authority。

FR-4: 引擎必须能接收外部或 resident AI intent candidates，但不能把它们当成最终权威。

FR-5: 引擎 v1 必须包含最小 resident/background AI 能力，形态为 Resident AI Coordinator 加多个 Resident AI Assistant。Coordinator 负责调度和 provenance；窄助手分别覆盖意图识别、上下文总结、实体维护辅助、进度管理辅助和剧情推进辅助。

FR-6: 引擎必须把 AI 延迟视为 intent 和后台辅助的产品约束。

FR-7: 引擎必须支持存储和查询由 Campaign Package 或 Save Package 提供的重要实体关系，例如谁认识谁、谁在哪、谁拥有什么、实体之间的态度是什么。

FR-8: 引擎必须支持由 Campaign Package 定义、并在 Save Package 中随游玩变化的 progress tracks，用于任务、探索、关系、资源、时间、剧情阶段或 campaign goals。

FR-9: Resident AI 可以帮助提出实体创建、实体更新、关系变化和进度变化，但这些建议必须作用于剧本包/存档中的内容模型，最终写入边界仍属于引擎。

FR-10: 引擎必须组装能给 AI 足够相关事实的 context，减少遗忘事实或编造关键状态。

FR-11: 引擎必须防止 hidden/GM-only 信息泄露到 player-visible views、ordinary query、scene output 或不合适的 AI prompts。

FR-12: Resident AI 或相关机制必须能总结相关游戏历史，使长期会话可继续使用，而不会把 prompt 塞爆。

FR-13: Campaign packages 必须能表达 AI-hosted play 所需的基础结构：实体、关系、目标/进度、campaign facts、capability declarations、规则和 gameplay scaffolding。更换 Campaign Package 应是切换游戏题材和大部分玩法结构的主要方式。

FR-14: Save packages 必须保持为长期本地 play 的 authoritative runtime state。

FR-15: 引擎必须提供足够的 CLI/MCP/maintenance workflow 支持，使 engine author / host 能 inspect、validate 和 operate Campaign/Save foundations。

FR-16: 引擎必须把核心能力以清晰接口暴露给内部模块和外部 caller，避免功能依赖隐式调用、重复业务逻辑或难以维护的跨层耦合。

FR-17: Kernel 必须把跨游戏通用能力和具体剧本内容分开，使不同类型的 AIGM 游戏可以共享同一套基础执行链、事实边界、上下文机制和存档机制。

### NonFunctional Requirements

NFR-1 Safety: AI 输出在未经 kernel 接受前，永远不是事实、最终意图、hidden access、approval 或 save authorization。

NFR-2 Maintainability: 核心边界必须足够模块化，使 execution chain、AI intent、entity/relationship/progress、context assembly 和 Campaign/Save foundations 能演进，而不反复大重构。

NFR-3 Interface clarity: 内部模块接口和外部调用接口必须清晰、稳定、可测试，减少跨层耦合和业务逻辑复制。

NFR-4 Debuggability: Intent decision、context assembly、progress state、entity change 和 commit outcome 应留下足够证据，能解释发生了什么。

NFR-5 Local-first operation: v1 面向本地、单人、单 campaign、长期 play。

NFR-6 Degraded operation: 没有 resident/internal AI 时，引擎仍必须可用，虽然质量可以较低。

NFR-7 Latency awareness: AI-assisted paths 应考虑玩家等待时间；当 AI 慢或不可用时必须安全降级。

NFR-8 Visibility correctness: Hidden/GM-only data 不能泄露到 player context、ordinary query、scene output 或 player-safe AI prompts。

### Additional Requirements

AR-1: 架构和 story 必须保持核心不变量：AI proposes; Kernel verifies; Player confirms; Engine commits。

AR-2: 普通玩家事实写入必须保持 `SaveManager.player_turn()` 创建 pending action 或 clarification、`SaveManager.player_confirm()` 作为 commit gate、`GMRuntime.commit_turn()` 进入 validation/commit 的执行链；`player_turn`、query、start/continue、platform message 和 preflight 不得提交 gameplay facts。

AR-3: `GMRuntime.start_turn()`、`query()`、`preview_action()`、`validate_delta()`、`commit_turn()` 等低层能力必须只在 developer/trusted/maintenance/admin 或等价 trusted path 中暴露，不能成为普通玩家默认入口。

AR-4: 每个 CLI command、MCP tool、platform endpoint、runtime helper 和未来 public surface 必须声明 surface taxonomy category 与 write authority；跨分类 surface 必须拆分或有明确 gate。

AR-5: CLI/MCP/platform adapters 必须保持 thin adapter，调用 `SaveManager`、`GMRuntime`、validators 和 kernel services，不复制 intent、preview、validation、commit 业务逻辑。

AR-6: 默认 MCP `player` profile 只能注册 player-safe tools；不得注册 `intent_preflight`、`start_turn`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn` 或 maintenance/admin tools。

AR-7: `external_intent_candidate`、internal AI review、preflight cache 和 resident AI advisory 都必须保持 low-trust/advisory/candidate 语义；这里的 low-trust 限定 gameplay facts、permission、player confirmation 和 commit authority，不排除 external candidate 在显式 off-mode policy 下成为 selected route proposal。任何 candidate 或 advisory 都不得表达 confirmation、hidden permission、proposal approval、delta injection、save authorization 或 profile escalation。

AR-8: Preflight cache 必须保持 advisory、identity-bound、TTL-bound、single-use；`message_only` preflight 创建时不得携带 external candidate，正式入口消费时仍必须经过 arbiter、binder、resolver、validation 和 commit guard。

AR-9: AI latency policy 必须支持安全降级：player-facing AI assistance 以约 8 秒为 soft wait、约 15 秒为 hard timeout 候选；resident/background advisory 可异步 30-60 秒产出，不阻塞 fact commit。

AR-10: Resident AI v1 的目标形态是 coordinator + narrow assistants，但实现故事应优先复用当前 `ai/`、`ai_intent/`、`context/semantic.py`、`archivist.py`、`reflection.py`、`memory.py`、`ai/state_audit.py`、`delta_draft.py`、`response_acceptance.py`、`turn_assistant.py` 和 `proposal_queue.py`。

AR-11: Resident AI Coordinator 只能负责任务调度、visibility-safe 输入、provenance/freshness 记录和 advisory 输出规范化；不得拥有 confirmation、validation、hidden permission、proposal approval 或 commit authority。

AR-12: `data/game.sqlite` 是 Save Package 当前事实权威；`events` 是权威审计记录；`data/events.jsonl`、snapshots、cards、memory、projection_state、outbox、registry、archive、preflight cache 和 audit logs 都不能成为 gameplay fact authority。

AR-13: Projection/outbox failure 必须可见、可报告、可修复；required projections 应与 `current_turn_id` 对齐并保持 clean，projection artifacts 不得绕过 pre-commit validation。

AR-14: Campaign Package 与 Save Package 必须分层：Campaign Package 包含作者内容、capabilities、rules、prompts、templates 和 smoke tests；Save Package 包含运行事实、events、projections、memory 和 save metadata。普通 play 不能把运行事实写回 Campaign Package。

AR-15: Campaign Package 普通作者包不得依赖 Python 插件、脚本化规则、绝对路径、任意本地文件引用或运行态 Save 文件；content paths 必须保持 campaign root 内相对路径。

AR-16: SaveManager workspace registry 必须保持 workspace-root-relative path boundary，拒绝 absolute path、`..` 和 root escape；registry 只选择 active save，不保存游戏事实。

AR-17: Pending player action 必须绑定 active save、save path、player text、action、delta、TurnProposal、confirmation `session_id`、expiry 和可选 platform/session/actor identity；过期或身份不匹配必须拒绝提交并要求重新 preview。

AR-18: Turn delta 必须遵守 `TurnProposal`、`TurnContract`、`ValidationReport` 和 validation profile 边界；player commit 必须使用 `human_confirmed=true` 且匹配 player commit profile。

AR-19: Content Type / Merge Contract 必须对齐 Campaign YAML key、delta key、runtime table、entity type、validation 和 merge policy；不要把每个允许 entity type 都误当成已注册 package content type。

AR-20: Entity 必须继续作为统一身份锚点；typed side tables 可增强结构化字段但不能替代 `entities.id`，也不能引入并行身份系统。

AR-21: Relationship 必须作为 first-class access contract，可先沿用 `relationship` content type、`type: relationship` entity 和规范化 details，但调用方不得依赖临时 `details_json` 约定或直接表结构细节。

AR-22: Progress Track / Clock 必须作为 first-class access contract；当前实现优先沿用 `clock` content type、`clocks` 表和 `tick_clocks` delta，不先构建复杂 quest ontology。

AR-23: Entity/Relationship/Progress access contract 必须提供 stable reads、validated mutation requests、reference checks、visibility filters 和 storage abstraction。

AR-24: Context assembly 必须先产出 inspectable `ContextBuildResult` / Context Slice，再渲染 prompt 或玩家可见文本；它应包含 scoped metadata、entities、relationships、progress/clocks、world settings、rules、routes、palettes、recent events、memory summaries、discovery_states、semantic hints、plot progression signals、visibility、provenance、inclusion reason、budget evidence 和 omitted/missing signals。

AR-25: Player-safe context、query、scene output、FTS、cards、snapshots、onboarding 和 AI prompt 必须在 collection/query 阶段排除 hidden/GM-only facts，而不是渲染后遮盖。

AR-26: Context path 改动必须覆盖 hidden-content leakage、context audit rows、recall budget、relationship/progress inclusion 和 omitted/missing evidence。

AR-27: Campaign diagnostics v1 必须至少覆盖 YAML/manifest/schema parse、required roots、entity reference integrity、relationship endpoint integrity、progress/clock completeness、visibility/hidden leakage risk、capability declarations 与 smoke tests 匹配、缺失 summary/aliases 的 context usability warning。

AR-28: Authoring diagnostics 不评价文笔、剧情好坏、美术风格或成熟 no-code authoring；v1 重点是捕获会导致 AI 乱主持、事实断裂或 hidden 泄露的问题。

AR-29: Author AI 只能编辑 Campaign author files，例如 `campaign.yaml`、`AUTHOR_NOTES.md`、`AUTHOR_AI_PROMPT.md`、`content/**`、`prompts/**`、`templates/**`、`tests/**`、`docs/**`；不得编辑 Save/runtime files 或写 Python、插件、migration、save patch、package upgrade。

AR-30: Prompt artifacts 是操作指导，不是权限授予；Prompt 变化必须与 CLI/MCP/AI intent/authoring contracts 同步，且不能让 AI 跳过 preview、validation、confirm 或 commit。

AR-31: 新内容治理必须遵守事实阶梯：叙事颜色、候选素材、未知线索、待确认实体、已确认运行事实、剧本权威内容；AI 可以即兴描述和起草 delta，但不能让重大新事实直接成立。

AR-32: Palette/random table/content delta 只能作为候选、线索、事件或受审核内容来源；`available`、`confirm_required`、`clue_only`、`locked`、`out_of_context` 的语义必须被 resolver、context 和 validation 尊重。

AR-33: 高影响内容，包括 world_setting、rule、location、route、faction、faction_state、rare/hidden/legendary species 或 hidden/hinted 到 known 的可见性升级，必须产生 warning 或 review requirement，不能静默进入事实。

AR-34: `discovery_states` 已有基础，应在后续故事中补齐多源确认、归档、维护报告和过期线索清理；不能把 discovery_state 召回误当成已确认事实。

AR-35: `proposal_queue` 已有基础，应在后续故事中补齐 `memory_update`、`alias_suggestion` 和 `turn_delta` proposal 的 apply/revert 规则；proposal approval 仍不等于普通 gameplay commit。

AR-36: Composite plan 当前主要返回 plan/repair options；未来多步计划不得绕过 capability、visibility、resolver、validation 或 per-step commit 边界。

AR-37: Content promotion/runtime-to-campaign 回写只能作为受控 maintenance 草案流程，默认不直接改 Campaign Package；必须保留 source event/proposal evidence 并跑 campaign validate/doctor/test。

AR-38: Story implementation 必须优先通过 Campaign Package 内容、capability declarations、rules、ActionResolverSpec、context collectors、ContentTypeSpec、package diagnostics 和 smoke tests 支撑玩法差异，不把每种题材的专用规则塞进 Kernel core。

AR-39: 至少两个题材或 capability profile 不同的 Campaign Package 应能复用同一套 init/save/context/validation/basic play loop，以证明 Kernel 是通用基座而不是单剧本实现。

AR-40: Foundation stories 必须带最小有意义的 boundary tests；触碰 SaveManager、Runtime、intent/preflight、CLI、MCP、platform、validation、commit、projection、visibility、Campaign/Save 或 context 的 story 必须声明 touched boundary 和 focused gate。

AR-41: 高风险 intent/platform/SaveManager 改动至少考虑 `tests/test_ai_intent.py`、`tests/test_runtime.py`、`tests/test_mcp_adapter.py`、`tests/test_preflight_cache.py`、`tests/test_platform_prewarm.py`、`tests/test_platform_ai_simulation.py`、`tests/test_platform_sidecar.py`、`tests/test_save_manager.py`、`tests/test_v1_cli.py`、`tests/test_current_native_context.py` 和 `tests/test_context_quality.py` 的相关子集。

AR-42: Campaign/Save/data model 改动必须考虑 package validation、current native package、write safety、visibility、projection、save patch、package merge 和 migration gates；测试不得直接写正式 current save package，写入测试必须复制到临时目录。

AR-43: 文档-only 变更至少运行 `git add -N docs _bmad-output`、`git diff --check` 和 `python3 scripts/check_markdown_links.py docs _bmad-output`；最终说明必须记录已跑命令和未跑原因。

AR-44: 残余风险 backlog 应作为故事风险检查表：hidden/export/AI egress、backup/restore/archive fault injection、skipped test policy、coverage growth、eval trends、declarative action spec、pending action/concurrency、TurnCoordinator guardrail 均不得被 foundation refactor 意外倒退。

### UX Design Requirements

No UX design contract was included. This project is currently CLI/MCP/kernel-first rather than UI-first. Player/author/operator experience requirements from CLI, MCP, Prompt, Campaign/Save, Authoring, and Content Governance contracts are captured under Additional Requirements.

### FR Coverage Map

FR-1: Epic 1 - 普通玩家写入链保持 `player_turn -> pending action -> player_confirm -> validation -> commit`。

FR-2: Epic 1 - 所有 public / semi-public surface 有分类、权限和写入权威。

FR-3: Epic 1 - Projection/outbox 保持 post-commit read model 和 repairable evidence。

FR-4: Epic 4 - 外部 AI 或 resident AI intent candidate 可进入引擎，但只作为低信任候选。

FR-5: Epic 4 - Resident AI Coordinator 与窄助手覆盖意图识别、上下文总结、实体维护、进度管理和剧情推进建议。

FR-6: Epic 4 - AI-assisted path 有延迟目标、timeout、preflight/background/caching 和安全降级策略。

FR-7: Epic 2 - Entity relationship 成为 Campaign/Save/context/gameplay 可依赖的 first-class access contract。

FR-8: Epic 2 - Progress Track / Clock 成为任务、探索、关系、资源、时间和剧情阶段的量化进度基础。

FR-9: Epic 4 - Resident AI 可以建议实体、关系和进度维护，但最终写入仍归 kernel boundary。

FR-10: Epic 3 - Context assembly 能为 AI/host 组装准确、相关、可检查的 Context Slice。

FR-11: Epic 3 - Context/query/scene/prompt/card/search 等 player-safe path 执行 hidden/GM-only 边界。

FR-12: Epic 3 - 长期游戏历史可被总结和召回，summary 基于 evidence 且不覆盖权威事实。

FR-13: Epic 2 - Campaign Package 能表达 AIGM play 的实体、关系、进度、规则、capabilities 和 gameplay scaffolding。

FR-14: Epic 1 - Save Package 保持 runtime fact integrity，SQLite 是当前事实权威。

FR-15: Epic 5 - 作者/主持者能 inspect、validate 和 operate Campaign/Save foundations，并获得可操作 diagnostics。

FR-16: Epic 1 - 核心内部模块和外部 caller 有清晰接口契约，尤其是 Surface Authority 与 Validation/Commit 边界。

FR-17: Epic 2 - Kernel 通用能力与具体 Campaign 内容分离，支持不同 Campaign Package 复用同一基础流程。

## Epic List

### Epic 1: 可信本地游玩闭环与入口权限

Oliver 可以通过 player-safe path 长期游玩、确认行动、保存事实，并且 CLI/MCP/platform/low-level 入口不会混淆权限。完成后，引擎拥有可验证的普通玩家写入闭环、surface taxonomy、Save fact authority、projection/outbox 证据边界和核心接口契约基础。

**FRs covered:** FR-1, FR-2, FR-3, FR-14, FR-16

### Epic 2: 通用 Campaign/Save 世界模型

作者可以用 Campaign Package 定义可替换的游戏世界、实体、关系和进度；Save Package 承载运行事实，同一 Kernel 可服务不同题材。完成后，Campaign/Save 分层、Entity/Relationship/Progress access contract、Content Type / Merge Contract 和通用 extension hooks 能支撑至少两个不同 capability profile 的 Campaign Package。

**FRs covered:** FR-7, FR-8, FR-13, FR-17

### Epic 3: Visibility-Safe Context 与长期记忆

AI/主持者可以拿到准确、相关、可审计、不会泄露 hidden 的 Context Slice，并支持长期游玩的摘要召回。完成后，`ContextBuildResult` 成为 prompt/render/query/advisory 的 inspectable context contract，hidden/GM-only 内容在 collection/query 阶段被排除出 player-safe path。

**FRs covered:** FR-10, FR-11, FR-12

### Epic 4: AI Intent 与 Resident Advisory Loop

外部 AI 和 resident AI 可以帮助理解意图、总结上下文、建议实体/关系/进度/剧情推进，并在延迟或 AI 不可用时安全降级，但事实权威仍在 Kernel。Intent route proposal 按显式 internal intent AI mode 选择；成为 selected route 不会授予事实、玩家确认或 commit authority。完成后，AI candidate、preflight cache、Resident AI advisory、proposal/review queue 和 latency policy 都保持 low-trust/advisory 语义。

**FRs covered:** FR-4, FR-5, FR-6, FR-9

### Epic 5: 作者/主持诊断与内容治理

作者和主持者可以检查 Campaign/Save 基础质量，治理 palette、random table、discovery、proposal、content delta 等新内容来源，让世界可扩展但不乱写事实。完成后，Campaign diagnostics v1 能捕获会导致 AI 乱主持、事实断裂或 hidden 泄露的问题，并把内容扩展控制在候选、确认、delta、review、commit 的治理链路内。

**FRs covered:** FR-15; reinforces FR-9, FR-13, FR-17

### Epic 6: Intent Contract 与 Player Session Reliability

Oliver 可以依赖 versioned intent contract、明确的 pending/clarification 生命周期、exactly-once confirmation 响应和可解释 audit；RPG Engine 负责 provider、session 与安全边界，Hermes consumer、reconnect 与 self-improvement 保持在独立仓库。完成后，taxonomy、safety、slot、manifest、preflight、session 和 audit 都有单一 owner 或 executable parity gate，且不会改变 AI、玩家确认或 commit authority。

**FRs reinforced:** FR-1, FR-4, FR-6, FR-16; NFR-1, NFR-3, NFR-4, NFR-6, NFR-7

## Epic 1: 可信本地游玩闭环与入口权限

Oliver 可以通过 player-safe path 长期游玩、确认行动、保存事实，并且 CLI/MCP/platform/low-level 入口不会混淆权限。完成后，引擎拥有可验证的普通玩家写入闭环、surface taxonomy、Save fact authority、projection/outbox 证据边界和核心接口契约基础。

### Story 1.1: Surface Authority Inventory and Contract

As an engine author,
I want every public and semi-public entry surface to declare its authority category,
So that player-safe, trusted low-level, maintenance, platform, prewarm, and projection paths cannot be confused.

**Acceptance Criteria:**

**Given** the current CLI, MCP, platform, runtime, projection, and maintenance entry points
**When** the surface inventory is generated or checked
**Then** every surface is classified as exactly one of player-safe, trusted low-level, maintenance/admin, platform sidecar, platform prewarm, or projection/outbox
**And** every surface records its write authority and forbidden bypasses.

**Given** a new surface is added without taxonomy metadata
**When** the focused surface contract test runs
**Then** the test fails with a clear missing-category or missing-authority error
**And** the developer can identify the surface to update.

**Given** a surface spans multiple categories
**When** the inventory is validated
**Then** it must either be split or document the explicit gate that changes authority
**And** the player-safe category must not expose low-level write powers.

### Story 1.2: Player Turn Pending Contract

As a player host,
I want `SaveManager.player_turn()` to create only query, clarification, blocked, or pending-action outcomes,
So that ordinary player input never commits gameplay facts before confirmation.

**Acceptance Criteria:**

**Given** an active Save Package and a player action that can change state
**When** `SaveManager.player_turn()` is called
**Then** it returns a player-visible preview with `ready_to_confirm=true` and a `session_id`
**And** no new gameplay facts, turns, events, clock ticks, or entity changes are committed.

**Given** the player input is a query, clarification case, or blocked action
**When** `SaveManager.player_turn()` completes
**Then** it returns `ready_to_confirm=false`
**And** it does not create a committable pending action.

**Given** a pending action is created
**When** the pending state is inspected
**Then** it binds save id, save path, player text, action, delta, `TurnProposal`, confirmation session id, created time, expiry, and optional platform/session/actor identity
**And** the pending state is not treated as an accepted fact.

### Story 1.3: Player Confirm Validation Commit Gate

As a player host,
I want `SaveManager.player_confirm()` to be the ordinary player commit gate,
So that only explicitly confirmed and validated proposals become durable facts.

**Acceptance Criteria:**

**Given** a valid pending player action from `player_turn`
**When** `SaveManager.player_confirm(session_id)` is called with the matching save and identity
**Then** the `TurnProposal` is marked `human_confirmed=true`
**And** `GMRuntime.commit_turn()` is called through the player commit validation profile.

**Given** the session id, active save, platform identity, actor identity, or pending expiry does not match
**When** `player_confirm()` is called
**Then** the commit is rejected
**And** expired pending state is cleaned up with a message requiring a fresh `player_turn`.

**Given** a low-level caller invokes `commit_turn`
**When** the delta or `TurnProposal` is missing approval, profile compatibility, validation evidence, or write guard expectations
**Then** the commit is rejected
**And** no gameplay facts are written.

### Story 1.4: Save Fact Authority and Runtime State Boundary

As an engine maintainer,
I want Save Package facts, registry state, pending state, archives, caches, and audit artifacts to have separate contracts,
So that no derived artifact or workspace index becomes a hidden fact source.

**Acceptance Criteria:**

**Given** a Save Package exists
**When** fact authority is inspected
**Then** `data/game.sqlite` is documented and tested as current fact authority
**And** events rows are the authoritative audit records.

**Given** registry, pending files, projection state, outbox, archive manifests, preflight cache, MCP audit logs, snapshots, cards, or memory artifacts exist
**When** they are read by player or maintenance paths
**Then** they are treated as entry state, derived state, advisory state, or evidence
**And** they cannot override SQLite facts.

**Given** workspace registry paths or MCP/CLI path parameters contain absolute paths, `..`, or root escape attempts
**When** validation runs
**Then** the path is rejected
**And** no registry, save, campaign, or pending state is modified.

### Story 1.5: Projection and Outbox Health Evidence

As a host maintaining a long-running save,
I want projection and outbox failures to be visible and repairable,
So that read models can fail without corrupting authoritative gameplay facts.

**Acceptance Criteria:**

**Given** a validated commit succeeds
**When** projection refresh runs
**Then** projection state records required projection status, version, last turn id, and any failure details
**And** projection artifacts remain post-commit read models.

**Given** events JSONL, search, snapshots, cards, or other required projections are dirty, stale, refreshing, failed, or behind current turn
**When** `save validate` or equivalent inspection runs
**Then** the health report exposes the mismatch
**And** the report does not reinterpret committed facts.

**Given** projection repair is invoked through a maintenance/admin surface
**When** repair completes or fails
**Then** the result is recorded as repair evidence
**And** pre-commit validation, player confirmation, and SQLite fact authority are not bypassed.

### Story 1.6: MCP Player Profile 权限门

作为 AI client 集成者，
我希望默认 MCP `player` profile 只暴露 player-safe tools，
从而保证 MCP 不能绕过普通玩家的 preview、pending、confirm 和 commit 边界。

**Acceptance Criteria:**

**Given** 默认 MCP `player` profile 已启用
**When** tool registration 或 tool list 被检查
**Then** 只注册 player-safe tools
**And** low-level preview、validate、commit、preflight、hidden view、maintenance 和 per-call AI override tools 不可用。

**Given** MCP `player` profile 调用禁止工具
**When** 请求到达权限门
**Then** 请求被拒绝并返回清晰的 surface/category mismatch
**And** 不写入 Save facts、pending state 或 audit 以外的 gameplay state。

### Story 1.7: CLI 命令薄适配边界

作为本地 host，
我希望 CLI `player` / `platform` / `mcp` 入口只调用 Kernel services，
从而避免 CLI 复制 intent、preview、validation 或 commit 业务逻辑。

**Acceptance Criteria:**

**Given** CLI `player` 命令处理普通玩家输入
**When** preview 或 confirm 流程执行
**Then** 命令只调用 `SaveManager.player_turn()` 和 `SaveManager.player_confirm()`
**And** 不直接写 SQLite facts、events、entity state 或 progress state。

**Given** CLI `play` low-level 命令仍作为 developer/trusted 工具存在
**When** CLI command contract test 运行
**Then** player-safe 命令和 trusted low-level 命令有明确分组与帮助文本边界
**And** 普通 player path 不能获得 low-level commit 权限。

### Story 1.8: Platform Forwarding 与审计边界

作为 platform 集成者，
我希望 platform sidecar 只做 session/actor gate、preflight identity 转发和 SaveManager forwarding，
从而保证平台消息不会获得额外 gameplay fact authority。

**Acceptance Criteria:**

**Given** platform sidecar 收到带 session / actor identity 的玩家请求
**When** 请求被转发到 Kernel
**Then** platform 层先执行 identity gate
**And** 成功后只调用对应 SaveManager player-safe API。

**Given** platform 或 MCP audit logging 已启用
**When** 一次调用完成、失败或被权限门拒绝
**Then** audit records 包含 sanitized request/result summaries、surface category、identity 摘要和 status
**And** audit 写入失败不会中断已成功的 Kernel operation，也不会提升 gameplay fact authority。

## Epic 2: 通用 Campaign/Save 世界模型

作者可以用 Campaign Package 定义可替换的游戏世界、实体、关系和进度；Save Package 承载运行事实，同一 Kernel 可服务不同题材。完成后，Campaign/Save 分层、Entity/Relationship/Progress access contract、Content Type / Merge Contract 和通用 extension hooks 能支撑至少两个不同 capability profile 的 Campaign Package。

### Story 2.1: Campaign and Save Ownership Contract

As a campaign author,
I want Campaign Package authored content and Save Package runtime facts to have explicit ownership contracts,
So that changing a game world and playing a save do not mutate the wrong source of truth.

**Acceptance Criteria:**

**Given** a Campaign Package
**When** campaign validation inspects package contents
**Then** author content, capabilities, rules, prompts, templates, smoke tests, and content files are allowed
**And** runtime files such as SQLite, save manifests, projections, memory, backups, reports, and pending state are rejected or warned as inappropriate.

**Given** a Save Package initialized from a Campaign Package
**When** save init or starter copy completes
**Then** `save.yaml`, runtime `campaign.yaml`, SQLite, events projection, snapshots, and cards are created or normalized
**And** authored Campaign Package files are not treated as mutable runtime progress.

**Given** ordinary play creates runtime changes
**When** facts, relationships, progress, or events are committed
**Then** those changes are stored in the Save Package fact boundary
**And** the source Campaign Package is not modified.

### Story 2.2: Content Type and Merge Contract

As an engine maintainer,
I want content types to declare how Campaign YAML, delta keys, runtime tables, and merge policies align,
So that new package content can evolve without ad hoc schema drift.

**Acceptance Criteria:**

**Given** the default `ContentRegistry`
**When** content type metadata is inspected
**Then** each registered type declares campaign key, YAML key, delta key when applicable, entity type, runtime table, sync safety, validation rule, and merge policy
**And** unregistered allowed entity types are not mistaken for package content roots.

**Given** a Campaign Package declares content paths
**When** load, validate, import, merge, or upgrade workflows run
**Then** content records are checked through the content type contract
**And** absolute paths or campaign-root escapes are rejected.

**Given** a content type contract changes
**When** focused tests run
**Then** package validation, merge or sync behavior, schema resources, and docs are updated together
**And** existing Campaign/Save compatibility is either preserved or explicitly migrated.

### Story 2.3: Entity Identity Access Contract

As an AI host or runtime caller,
I want a stable entity access contract,
So that characters, locations, items, clues, projects, rules, clocks, and other game objects can be referenced consistently.

**Acceptance Criteria:**

**Given** an entity is created from Campaign import or validated runtime delta
**When** it is stored
**Then** it has a stable `entities.id`, type, name, status, visibility, optional location/owner, summary, details, and update evidence
**And** typed side tables reference the entity rather than replacing its identity.

**Given** a caller reads entities for gameplay, diagnostics, context, or authoring
**When** it uses the entity access contract
**Then** reads apply status and visibility filters appropriate to the caller mode
**And** callers do not need direct table-specific knowledge for common identity fields.

**Given** a runtime mutation references entities
**When** validation runs
**Then** references must exist or be created in the same validated delta
**And** active entities cannot violate location/owner invariants.

### Story 2.4: Relationship Access Contract

As a game host,
I want relationships to be first-class readable and validatable concepts,
So that AI and gameplay systems can understand who knows whom, who owns what, who is where, and who has what attitude.

**Acceptance Criteria:**

**Given** Campaign or Save data contains relationship records
**When** the relationship access contract reads them
**Then** it returns stable relationship id, source id, target id, kind/state, attitude or stance fields when present, visibility, summary, and update evidence
**And** it can be used without relying on arbitrary `details_json` conventions.

**Given** a relationship endpoint is missing, hidden, archived, or outside caller visibility
**When** validation or context assembly requests the relationship
**Then** the issue is reported or filtered according to the caller mode
**And** player-safe output does not leak hidden endpoints.

**Given** an AI or maintenance workflow suggests a relationship change
**When** the change is submitted
**Then** it must enter a validated mutation, proposal, or maintenance path
**And** the suggestion alone does not become fact.

### Story 2.5: Progress Track and Clock Access Contract

As a game host,
I want progress tracks and clocks to be first-class readable and validatable concepts,
So that tasks, threats, exploration, relationships, resources, time, and plot phases can be tracked without a heavyweight quest system.

**Acceptance Criteria:**

**Given** Campaign or Save data defines clocks or progress tracks
**When** the progress access contract reads them
**Then** it returns id, kind/type, scope, total segments, filled segments, visibility, status, trigger or tick rules, and update evidence
**And** the current `clock` content type, `clocks` table, and `tick_clocks` delta remain the v1 implementation basis.

**Given** gameplay or maintenance attempts to tick or update progress
**When** validation runs
**Then** referenced clocks must exist, visibility rules must hold, and the delta must explain why progress changed
**And** progress updates cannot be smuggled through unstructured narrative text.

**Given** a host asks "where is the game now?"
**When** progress state is queried
**Then** active visible tracks help answer current goals, pressures, phases, and open threats
**And** hidden tracks remain excluded from player-safe views.

### Story 2.6: 跨 Campaign 的模型边界冒烟测试

作为引擎作者，
我希望至少两个不同 Campaign Package 能复用同一套 Campaign/Save 模型边界，
从而证明 Kernel 的 package、entity、relationship 和 progress 基础不是某一个战役的专用实现。

**Acceptance Criteria:**

**Given** 两个具有不同 capability profile 或 genre assumption 的 Campaign Packages
**When** 每个 package 在临时 Save 上运行 init、save inspect、campaign validate、campaign test 和模型访问 smoke
**Then** 两者都复用同一套 Campaign/Save ownership、Content Type / Merge、Entity、Relationship 和 Progress access contracts
**And** 不需要 fork fact store、custom commit chain 或 campaign-specific runtime schema。

**Given** 新 gameplay variation 可以通过 capabilities、content types、rules、relationship kinds、progress tracks 和 smoke tests 表达
**When** variation 被加入其中一个 Campaign Package
**Then** 不需要改变核心 fact authority、player confirmation flow 或 Context Slice contract
**And** 任何新增 extension point 都带有 contract 文档和边界测试。

**Given** smoke test 需要写入 Save Package state
**When** 测试运行
**Then** 它使用 temporary save copy
**And** 正式 current save packages 不会被修改。

## Epic 3: Visibility-Safe Context 与长期记忆

AI/主持者可以拿到准确、相关、可审计、不会泄露 hidden 的 Context Slice，并支持长期游玩的摘要召回。完成后，`ContextBuildResult` 成为 prompt/render/query/advisory 的 inspectable context contract，hidden/GM-only 内容在 collection/query 阶段被排除出 player-safe path。

### Story 3.1: ContextBuildResult Contract and Audit

As an AI host,
I want context assembly to produce an inspectable `ContextBuildResult`,
So that prompts, query output, render output, and advisory inputs share one auditable context contract.

**Acceptance Criteria:**

**Given** a player action, query, or host context request
**When** `build_context()` or equivalent context assembly runs
**Then** it returns structured scoped metadata, included items, omitted items, visibility mode, provenance, inclusion reason, budget evidence, and missing-signal evidence
**And** rendering or prompt construction consumes this result rather than rebuilding facts independently.

**Given** context audit is enabled
**When** a context run completes
**Then** `context_runs` and `context_items` or equivalent audit records describe what was included and omitted
**And** the audit can explain why a relevant fact was present or absent.

**Given** a new context source is added
**When** focused context tests run
**Then** the source must declare visibility, provenance, and budget behavior
**And** it cannot bypass the `ContextBuildResult` contract.

### Story 3.2: Player-Safe Context、Query 与 Prompt 隐藏信息边界

作为玩家，
我希望 hidden 和 GM-only 信息不会进入 player-safe context、ordinary query、scene output 或 player-safe AI prompts，
从而让游戏可以保留秘密，同时仍能让 AI 主持可见内容。

**Acceptance Criteria:**

**Given** hidden 或 GM-only entities、relationships、world settings、discovery states、memory summaries 或 events 存在
**When** player-safe context、ordinary query、scene output 或 player-safe AI prompts 被构建
**Then** hidden material 在 collection 或 query 阶段被排除
**And** 不能只依赖最终 render 阶段隐藏。

**Given** trusted GM 或 maintenance context 被请求
**When** caller profile 允许 hidden reads
**Then** hidden material 可以带 explicit visibility mode 和 provenance 被纳入
**And** 同一份结果不能通过 cache reuse 泄漏到 player-safe mode。

### Story 3.3: 派生玩家视图与检索产物的隐藏信息边界

作为玩家，
我希望 cards、snapshots、FTS、onboarding 和其他派生玩家视图也不包含 hidden / GM-only 信息，
从而避免隐藏内容通过 read model 或搜索产物泄漏。

**Acceptance Criteria:**

**Given** hidden 或 GM-only material 存在于 Save facts、events、memory、cards source 或 projection input
**When** onboarding、snapshots、cards、FTS 或 player-facing search artifacts 被生成或刷新
**Then** player-visible artifacts 不包含 hidden material
**And** projection/search 的派生缓存不能成为 hidden 泄漏路径。

**Given** visibility 相关实现发生变化
**When** focused visibility tests 运行
**Then** tests 分别覆盖 player view、ordinary query、FTS、scene output、cards、snapshots 和 AI prompt boundaries
**And** failures 能指出泄漏的 item type 与 artifact type。

### Story 3.4: Relationship, Progress, and Plot Signal Context

As an AI host,
I want context slices to include relevant relationships, progress tracks, and plot progression signals,
So that narration and intent handling can reason from current game state instead of guessing.

**Acceptance Criteria:**

**Given** a player action references an entity, place, goal, resource, threat, or social target
**When** context assembly scopes relevant facts
**Then** related entities, relationships, active progress tracks/clocks, recent events, world settings, rules, routes, palettes, discovery states, and plot progression signals are considered
**And** included items carry source and visibility evidence.

**Given** a relationship or progress item is relevant but omitted because of budget, visibility, missing reference, or conflict resolution
**When** the context result is inspected
**Then** omission evidence explains why it was excluded
**And** debugging can distinguish absent facts from hidden or over-budget facts.

**Given** a Campaign Package supplies light hooks, goals, clues, project summaries, or other plot hints
**When** those hints are player-visible and relevant
**Then** they can appear as plot progression signals
**And** they do not become mandatory storylets or automatic director commands.

### Story 3.5: Long-Term Memory Summary Provenance

As a long-running game host,
I want memory summaries to be evidence-based and freshness-aware,
So that the AI can continue a campaign without replacing authoritative facts.

**Acceptance Criteria:**

**Given** a memory summary is created or refreshed
**When** it is stored
**Then** it records source turns, source events, freshness or staleness metadata, visibility mode, and summary type
**And** it is marked as derived context rather than authoritative fact.

**Given** a summary conflicts with current SQLite facts
**When** context assembly or diagnostics evaluates it
**Then** authoritative facts win
**And** the summary is flagged stale, omitted, or sent through an advisory review workflow.

**Given** resident AI is unavailable
**When** long-term play continues
**Then** existing deterministic summaries, snapshots, recent events, or lower-quality fallback context remain usable
**And** gameplay fact submission is not blocked by missing summary refresh.

### Story 3.6: Context Budget and Quality Diagnostics

As an engine author,
I want context quality diagnostics for missing, oversized, stale, or low-value context,
So that I can improve AI hosting without weakening visibility boundaries.

**Acceptance Criteria:**

**Given** a context request exceeds budget
**When** budgeting runs
**Then** the result records budget decisions, included and omitted items, and high-value missing signals
**And** player-safe hidden filtering still happens before any prompt or render output.

**Given** an entity, relationship, progress track, memory summary, alias, or world setting lacks fields needed for useful context
**When** diagnostics run
**Then** warnings identify missing summary, aliases, endpoint references, progress metadata, or stale summary evidence
**And** diagnostics do not evaluate prose quality or story taste.

**Given** context behavior changes
**When** focused tests run
**Then** they cover context audit rows, recall budget, relationship/progress inclusion, hidden leakage, and current native context regression
**And** the final story evidence names the selected test gate.

### Story 3.7: 跨 Campaign 的 Context 与玩家安全回路集成冒烟测试

作为引擎作者，
我希望在 Context Slice 基础完成后，再用跨 Campaign 冒烟测试覆盖 context assembly 和基础 player-safe loop，
从而证明通用 Kernel 行为成立，同时避免 Epic 2 依赖 Epic 3。

**Acceptance Criteria:**

**Given** 至少两个不同 capability profile 或 genre assumption 的 Campaign Packages
**When** 每个 package 在 temporary save copy 上运行 context assembly、basic query、preview、validation 和 safe player loop smoke
**Then** 两者都复用同一套 ContextBuildResult、visibility filtering、player_turn、pending action、player_confirm 和 commit validation 边界
**And** 不需要 campaign-specific context fork 或 custom player-safe commit chain。

**Given** cross-campaign smoke 发现 context 缺失、hidden 泄漏或 player-safe loop 失败
**When** 测试报告生成
**Then** 报告指出对应 Campaign、Save、context source、visibility mode 或 player-safe stage
**And** 正式 current save packages 不会被测试修改。

## Epic 4: AI Intent 与 Resident Advisory Loop

外部 AI 和 resident AI 可以帮助理解意图、总结上下文、建议实体/关系/进度/剧情推进，并在延迟或 AI 不可用时安全降级，但事实权威仍在 Kernel。完成后，AI candidate、preflight cache、Resident AI advisory、proposal/review queue 和 latency policy 都保持 low-trust/advisory 语义。

### Story 4.1: Low-Trust Intent Candidate Contract

As an external AI integrator,
I want a valid external candidate to become proposal authority only when internal intent AI is off,
So that deterministic rules cannot override externally understood intent while the Kernel still verifies, binds, previews, confirms, and commits safely.

**Acceptance Criteria:**

**Given** an external or resident AI submits an intent candidate
**When** the candidate is normalized
**Then** it may contain kind, mode, action, slots, plan, confidence, missing slots, safety flags, and reason
**And** it cannot contain player confirmation, hidden access, delta/proposal injection, save authorization, profile escalation, or per-call override for player profile.

**Given** internal intent AI is off and a valid external candidate is present
**When** schema, action registry, safety, and binding checks pass and routing runs
**Then** the external candidate becomes the selected route proposal
**And** deterministic rules are retained only as trace or diagnostic evidence and cannot override, veto, or force clarification solely because of mismatch.

**Given** internal intent AI is enabled and an external candidate is present
**When** routing runs
**Then** external and internal candidates follow the existing arbitration path
**And** the external candidate does not become proposal authority merely because it is present.

**Given** internal intent AI is off and no external candidate is present
**When** routing runs
**Then** the first fix preserves the current deterministic rules fallback
**And** no-external fallback hardening remains a separate P0 decision.

**Given** an external candidate is malformed, unsafe, names an unknown action, or has invalid or missing binding
**When** schema validation, risk checks, action registry, or binder run
**Then** the result is a structured rejection, clarification, or blocked response as appropriate
**And** deterministic rules do not silently substitute a different player intent or create a pending action from the invalid candidate.

**Given** an external-primary or accepted consensus route conflicts with the keyword expected action
**When** the runtime preview mismatch guard runs
**Then** the mismatch is retained as diagnostic evidence and does not hard-veto the routed intent
**And** the existing mismatch guard remains for direct low-level `preview_action` calls whose action was not selected by a routed AI intent.

**Given** a selected route is a query or executable action
**When** the standard player-safe path continues
**Then** a query returns player-visible read-only state without saving, while an action passes resolver, preview, and validation and creates only a pending action
**And** only a matching `player_confirm(session_id)` after explicit player confirmation may commit gameplay facts.

### Story 4.2: AI Latency Policy and Safe Degradation

As a player,
I want AI-assisted turns to avoid unbounded waiting,
So that slow or unavailable AI results in safe fallback rather than unsafe commits.

**Acceptance Criteria:**

**Given** player-facing AI assistance is enabled
**When** an intent or helper call exceeds the configured soft wait target near 8 seconds
**Then** the player-facing path may show fallback, clarification, pending wait, or non-AI safe processing
**And** authority boundaries remain unchanged.

**Given** an AI call reaches the configured hard timeout candidate near 15 seconds
**When** the turn proceeds
**Then** the system safely degrades to deterministic low-risk fallback, clarification, blocked, or no-AI path
**And** no timed-out AI result can later authorize commit.

**Given** internal intent AI is configured as enabled
**When** internal review times out or becomes unavailable
**Then** degradation does not silently reinterpret the configured mode as explicit off or grant the external candidate unconditional proposal authority
**And** the existing safe fallback, clarification, blocked, or no-AI policy remains in force.

**Given** resident/background advisory tasks are scheduled
**When** they complete within or beyond the 30-60 second target window
**Then** they produce advisory records or timeout evidence
**And** gameplay fact commit is not blocked by their latency.

### Story 4.3: Advisory Preflight Cache Boundary

As a platform integrator,
I want background preflight to speed up intent review without changing authority,
So that platform messages can be prepared while formal entry still revalidates everything.

**Acceptance Criteria:**

**Given** candidate-bound preflight is created
**When** it is stored
**Then** it binds preflight id, text hash, external candidate hash, rule candidate hash, save/base turn, context identity, provider/model/backend, schema, and task
**And** it is advisory, TTL-bound, identity-bound, and single-use.

**Given** message-only preflight is created by platform prewarm
**When** it is stored
**Then** it includes platform, session key, message id, and source user text hash
**And** it does not store an external candidate at creation.

**Given** formal player entry consumes a preflight hit
**When** routing continues
**Then** the hit can replace only live internal review
**And** arbiter, binder, resolver, preview, pending action, player confirm, validation, and commit guard still run.

### Story 4.4: Resident AI Advisory Envelope Contract

作为引擎作者，
我希望 resident AI 输出共享一个 advisory envelope contract，
从而让意图识别、上下文总结、实体维护、进度管理和剧情推进建议都可追踪、非权威、可调试。

**Acceptance Criteria:**

**Given** resident AI assistant 产生输出
**When** 输出被存储或返回
**Then** 它记录 advisory type、target ids、evidence、confidence、freshness、visibility mode、source assistant、schema version 和 proposed next workflow
**And** 它不能直接写 Save facts、approve proposals、confirm players 或 grant hidden access。

**Given** advisory record 会暴露给 player-visible surface
**When** 它被 render 或通过 CLI/MCP 暴露
**Then** private reasoning、hidden facts、raw delta drafts 和 unsafe proposal internals 被排除
**And** provenance 仍足够 maintenance/debug 使用。

### Story 4.5: Resident AI Advisory 代表性适配

作为引擎作者，
我希望先把少量代表性 AI/helper 输出接入 Resident AI Advisory Envelope，
从而验证 envelope 可以复用现有实现，而不需要一次性重写所有 helper 模块。

**Acceptance Criteria:**

**Given** 已存在的 AI/helper 输出路径，例如 intent review、context summary、memory/state audit 或 delta draft
**When** 选择代表性 adapter 接入 advisory envelope
**Then** 至少覆盖两个不同 advisory type
**And** 每个 adapter 有 focused test 验证 envelope 字段、visibility mode、provenance 和 non-authoritative boundary。

**Given** 尚未接入的 helper modules 仍存在
**When** 本 story 完成
**Then** 它们不会被强制大迁移
**And** 后续迁移点以明确 backlog 或 follow-up story 记录。

### Story 4.6: Entity, Relationship, and Progress Advisory Review

As a host,
I want AI-suggested entity, relationship, and progress changes to enter reviewable workflows,
So that useful maintenance help can become facts only after validation or approval.

**Acceptance Criteria:**

**Given** resident AI suggests creating or updating an entity, relationship, alias, memory summary, progress track, or clock tick
**When** the suggestion is accepted for review
**Then** it becomes a proposal, content delta draft, maintenance delta, or other explicit review artifact
**And** the original AI suggestion remains non-authoritative.
**And** this story does not own proposal queue state transitions, apply, revert, or batch review.

**Given** a reviewed suggestion targets gameplay facts
**When** application is requested
**Then** it must pass the appropriate validation profile, reference checks, visibility checks, and commit or maintenance gate
**And** proposal approval alone is not equivalent to ordinary gameplay commit.

**Given** a suggestion is rejected, stale, superseded, or conflicts with current facts
**When** reports or context recall inspect it
**Then** it is not treated as current fact
**And** rollback or supersession evidence is visible to maintenance users.

### Story 4.7: Plot Progression Advisory Without Storylet Requirement

As a game host,
I want AI to receive plot progression advice from Campaign/Save signals,
So that stories can move naturally without requiring a formal storylet scheduler in v1.

**Acceptance Criteria:**

**Given** world settings, recent events, relationships, active progress tracks, discovery states, memory summaries, rules, and authored hooks are available
**When** resident or external AI asks for plot progression context
**Then** the Kernel provides visibility-safe signals and optional advisory guidance
**And** it does not require `storylets.yaml` or a mandatory automatic director.

**Given** AI proposes a plot beat, escalation, clue reveal, new entity, route, faction, resource, or rule implication
**When** the proposal would affect future gameplay
**Then** it must enter candidate, discovery, proposal, content delta, or validated turn delta workflow
**And** the narrative text alone does not create durable facts.

**Given** resident AI is disabled
**When** plot progression continues
**Then** external AI and deterministic context signals can still support lower-quality play
**And** the Kernel keeps the same fact and hidden boundaries.

## Epic 5: 作者/主持诊断与内容治理

作者和主持者可以检查 Campaign/Save 基础质量，治理 palette、random table、discovery、proposal、content delta 等新内容来源，让世界可扩展但不乱写事实。完成后，Campaign diagnostics v1 能捕获会导致 AI 乱主持、事实断裂或 hidden 泄露的问题，并把内容扩展控制在候选、确认、delta、review、commit 的治理链路内。

### Story 5.1: Campaign Package 结构诊断

作为 Campaign 作者，
我希望 v1 diagnostics 先捕获 package 结构、manifest、schema 和路径问题，
从而在内容进入运行态前发现会导致导入或验证失败的基础错误。

**Acceptance Criteria:**

**Given** Campaign Package 被 validate、doctor、outline 或等价 diagnostics 检查
**When** package structure diagnostics 运行
**Then** 它覆盖 YAML/manifest/schema parse、required roots、content paths、content type declarations 和 package-relative path rules
**And** absolute path、`..`、campaign-root escape、runtime/save 文件误放会产生可操作 error 或 warning。

**Given** diagnostics 发现 prose、taste、genre quality 或 art-style concerns
**When** v1 package structure diagnostics 报告结果
**Then** 它不评价或阻塞这些主观质量
**And** 它只关注 package 可加载性、schema validity、路径安全和基础结构完整性。

**Given** diagnostics 针对 formal current Campaign/Save setup 运行
**When** 测试需要 write behavior
**Then** 它使用 temp copies
**And** formal current save packages 不会被修改。

### Story 5.2: Campaign 引用、Relationship 与 Progress 诊断

作为 Campaign 作者，
我希望 diagnostics 能发现 entity references、relationship endpoints 和 progress/clock completeness 问题，
从而避免 AI hosting 时出现断裂事实、无效关系或不可追踪进度。

**Acceptance Criteria:**

**Given** Campaign Package 包含 entities、relationships、progress tracks 或 clocks
**When** reference diagnostics 运行
**Then** missing entity refs、invalid relationship endpoints、hidden/archived endpoint misuse、unknown relationship kind/state 和 invalid owner/location references 被报告
**And** 每条 error 或 warning 指向可修复的 source file、id 或 field。

**Given** Campaign Package 定义 progress tracks、clocks、goals 或 campaign phases
**When** progress diagnostics 运行
**Then** total segments、filled segments、tick rules、scope、status、visibility、trigger references 和 lifecycle completeness 被检查
**And** progress updates 不能只依赖 unstructured narrative text。

**Given** diagnostics 发现引用或进度问题
**When** 报告被作者查看
**Then** 报告区分 blocking errors、warnings 和 advisory cleanup
**And** 它说明问题会影响 import、context、validation、player-safe output 还是 maintenance workflow。

### Story 5.3: Campaign Context Usability 与 Capability 诊断

作为 Campaign 作者，
我希望 diagnostics 能发现 capability declarations、smoke tests、summary 和 aliases 的可用性问题，
从而提升 AI context 质量，而不评价文笔或剧情品味。

**Acceptance Criteria:**

**Given** Campaign Package 声明 capabilities、rules、prompts、templates 或 smoke tests
**When** capability diagnostics 运行
**Then** capability declarations 与 smoke test coverage、content type usage、rules hooks 和 expected player-safe flows 对齐
**And** 缺失或不匹配项以可操作 warning 或 error 报告。

**Given** entities、relationships、world settings、locations 或 progress tracks 缺少 AI-hosted play 所需 context hints
**When** context usability diagnostics 运行
**Then** missing summaries、aliases、relationship summaries、progress metadata、visibility risks 和 stale hints 被报告
**And** diagnostics 不评价 prose taste、plot quality 或 genre preference。

**Given** diagnostics 发现 hidden/GM-only visibility risk
**When** 报告输出
**Then** 它指出可能影响 player-safe context、ordinary query、cards、snapshots、FTS 或 prompt boundary 的位置
**And** 它不把 hidden truth 暴露进 player-safe 报告。

### Story 5.4: Author AI and Prompt Contract Diagnostics

As a campaign author using AI assistance,
I want author prompts and AI-client prompts to enforce tool and file boundaries,
So that AI helpers improve content without claiming false save authority.

**Acceptance Criteria:**

**Given** author AI instructions or campaign-local author prompts are checked
**When** diagnostics evaluate allowed and forbidden files
**Then** allowed author files include `campaign.yaml`, notes, author prompts, `content/**`, `prompts/**`, `templates/**`, `tests/**`, and `docs/**`
**And** Save/runtime files, Python code, plugins, migrations, save patch, and package upgrade instructions are flagged as out of scope.

**Given** AI-client prompt artifacts are checked
**When** prompt contract diagnostics run
**Then** they preserve `player_turn -> player_confirm`, low-trust external candidate semantics, intent manifest read-only semantics, preflight advisory semantics, and low-level tool restrictions
**And** examples remain aligned with CLI and MCP contracts.

**Given** prompt contract semantics change
**When** the update is merged
**Then** prompt versioning, markdown links, diff whitespace, and relevant CLI/MCP/SaveManager focused tests are considered
**And** the final evidence states which checks were run.

### Story 5.5: Palette and Random Table Governance

As a campaign author,
I want palette and random table diagnostics to distinguish candidates, clues, and facts,
So that AI can make the world feel open without inventing durable truths.

**Acceptance Criteria:**

**Given** palette files are declared or auto-discovered
**When** validation runs
**Then** ids, kind, locations or biomes, intents, discovery mode, clue text, confirm methods, unlock conditions, risks, save-as mapping, hidden/direct conflicts, and references are checked
**And** bad candidates produce errors or warnings before play.

**Given** random tables are used for rumors, risks, discoveries, encounters, costs, social reactions, or gather yields
**When** diagnostics inspect table entries
**Then** entries that imply high-impact facts, inventory gain, hidden revelation, or confirmed factions without delta/review path are warned
**And** random table rolls remain events or candidates until validated commit.

**Given** an action resolver consumes a palette id
**When** preview and validation run
**Then** `available`, `confirm_required`, `clue_only`, `locked`, and `out_of_context` statuses are respected
**And** clue-only or confirm-required material cannot be silently saved as known inventory or confirmed world facts.

### Story 5.6: Discovery State Lifecycle Reports

As a host,
I want discovery states to record and report how uncertain content becomes confirmed or rejected,
So that the same clue is not repeatedly invented and hidden truths are not leaked early.

**Acceptance Criteria:**

**Given** rumors, palette candidates, unknown leads, exploration clues, samples, social confirmations, or false leads are produced
**When** discovery state is updated
**Then** stage, visibility, confidence, source events, location, required next steps, and updated turn evidence are recorded
**And** player-visible recall distinguishes rumored, hinted, observed, sampled, confirmed, and rejected states.

**Given** multiple sources confirm or contradict a discovery
**When** maintenance reports run
**Then** they show supporting events, conflicting evidence, stale or orphaned discoveries, and suggested cleanup
**And** hidden truth remains unavailable to player-safe contexts until confirmed through allowed steps.

**Given** a discovery is archived, rejected, or expired
**When** context assembly and palette suggestion run
**Then** it is not repeatedly presented as brand-new
**And** audit evidence explains why it was omitted or downgraded.

### Story 5.7: Proposal Queue Apply and Revert Rules

As a maintenance host,
I want proposal queue entries to have clear apply and revert semantics,
So that AI suggestions and maintenance drafts can be reviewed without polluting current facts.

**Acceptance Criteria:**

**Given** a proposal for `memory_update`, `alias_suggestion`, `turn_delta`, content delta, or related advisory work is created
**When** it enters the queue
**Then** it records kind, risk, target ids, proposed payload, facts used, narrative claims where relevant, validation status, review status, provenance, rollback hint, and source evidence
**And** it is not current gameplay fact.

**Given** a reviewer approves, rejects, supersedes, or applies a proposal
**When** the proposal state changes
**Then** the state transition is validated against allowed transitions
**And** application uses the appropriate write, maintenance, or commit path rather than queue state alone.

**Given** an applied proposal must be reverted or reported
**When** rollback-plan, report, or batch-review tools run
**Then** they identify applied evidence, affected ids, safe rollback hints, and blocked rollback cases
**And** hidden or private AI reasoning is not exposed to player-safe outputs.

### Story 5.8: High-Impact Content Delta Review and Promotion

As a campaign maintainer,
I want high-impact content changes and runtime-to-campaign promotion to be reviewed as drafts,
So that long-running worlds can grow without silently rewriting the campaign.

**Acceptance Criteria:**

**Given** a content delta creates or changes world settings, rules, locations, routes, factions, faction state, rare/hidden/legendary species, or hidden/hinted-to-known visibility
**When** `content validate-delta` or apply workflows run
**Then** high-impact warnings or review requirements are produced
**And** strict review blocks unreviewed high-impact application.

**Given** a palette candidate is converted to content delta
**When** `content from-palette` or equivalent factory runs
**Then** the draft records source palette id, review requirement, visibility default, risks, and description that it is a draft
**And** high-impact candidates do not default to known player facts.

**Given** runtime facts are candidates for campaign promotion
**When** content diff, export, or promote workflows run
**Then** they create reviewed draft artifacts with source event/proposal evidence
**And** they do not directly rewrite Campaign Package source unless an explicit maintenance flow approves it and campaign validate/doctor/test gates are considered.

### Story 5.9: Residual Risk Evidence Gates

As an engine maintainer,
I want residual risk checks to be attached to foundation stories,
So that hidden/export, backup/restore, eval, coverage, action spec, concurrency, and coordinator risks do not regress quietly.

**Acceptance Criteria:**

**Given** a story touches hidden content, export, AI egress, archive, backup, restore, skipped tests, coverage, eval reports, declarative action specs, pending actions, platform concurrency, or future coordinator boundaries
**When** the story is prepared for implementation
**Then** it names the relevant residual risk category
**And** it selects at least one concrete evidence gate: focused unit test, SQLite/package integration test, CLI/MCP system test, current native regression, markdown/docs gate, manual inspection checklist, or an explicit reason that the gate does not apply.

**Given** hidden content, export, AI egress, player-safe output, or visibility-sensitive read models change
**When** the selected evidence gate runs
**Then** it covers the relevant hidden/GM-only exclusion or sanitization path
**And** the final story evidence names the fixture, command, checklist, or report used.

**Given** backup, restore, archive, or import behavior changes
**When** focused reliability tests run
**Then** they cover interruption, half-write, staging, checksum, failed restore, and current-save preservation where applicable
**And** failures do not delete a currently usable save.

**Given** a future coordinator or orchestration layer is introduced
**When** boundary tests run
**Then** player workflow, profile gate, hidden/visibility gate, atomic write, archive staging, skipped-test reporting, coverage/eval metrics, declarative action spec behavior, pending action identity, and platform concurrency do not regress where applicable
**And** the coordinator remains orchestration and trace rather than authority.

## Epic 6: Intent Contract 与 Player Session Reliability

Oliver 可以依赖 versioned intent contract、明确的 pending/clarification 生命周期、exactly-once confirmation 响应和可解释 audit；RPG Engine 负责 provider、session 与安全边界，Hermes consumer、reconnect 与 self-improvement 保持在独立仓库。完成后，taxonomy、safety、slot、manifest、preflight、session 和 audit 都有单一 owner 或 executable parity gate，且不会改变 AI、玩家确认或 commit authority。

### Story 6.1: Strict External Safety Vocabulary and Version Negotiation

As an external AI integrator,
I want external safety vocabulary validation and version negotiation to fail closed,
So that unknown flags or rolling upgrades cannot silently weaken the Kernel trust boundary.

**Acceptance Criteria:**

**Given** an external intent candidate contains a safety flag outside the active versioned vocabulary
**When** the external candidate boundary validates and normalizes it
**Then** the candidate is rejected or blocked with a structured unknown-safety error
**And** the unknown flag is not silently removed, adopted, routed, previewed, or converted into pending state.

**Given** a caller and provider use different manifest or safety-vocabulary versions or digests
**When** the candidate reaches the provider contract boundary
**Then** the provider returns a retriable `contract_version_mismatch` requiring manifest refresh and candidate regeneration
**And** a compatibility-window caller that omits provenance may continue only when every supplied flag belongs to the active allowlist.

**Given** schema, external normalization, arbiter blockers, and manifest projection expose safety vocabulary
**When** parity and threat/consequence gates run across off, consensus, known-danger, old-caller/new-provider, and new-caller/old-provider cases
**Then** all owners agree on the active vocabulary and unknown values fail closed
**And** external AI remains low-trust while Kernel safety, pending, player confirmation, validation, and commit authority remain unchanged.

### Story 6.2: Canonical Action Taxonomy Registry Projection

As an intent contract maintainer,
I want simple lexical action taxonomy to have one versioned registry owner,
So that deterministic routing, live manifest, internal prompts, and external consumers cannot drift.

**Acceptance Criteria:**

**Given** builtin action resolvers are registered
**When** the resolved intent taxonomy is generated
**Then** `ActionResolverSpec` / `ActionResolverRegistry` owns the versioned simple-term `ActionTaxonomySpec`
**And** deterministic router, live manifest, and internal prompt consume projections from that same source rather than parallel synonym tables.

**Given** `intent_router` evaluates composite, negation, maintenance, entity-aware, or context-aware grammar
**When** lexical taxonomy is centralized
**Then** those grammar responsibilities remain in the router while simple action synonyms move to the registry projection
**And** current P0 routes, entity/hidden binding, and off-mode external-primary behavior do not regress.

**Given** builtin, custom/campaign, or multilingual locale terms are projected
**When** taxonomy parity and stale-contract tests run
**Then** “巡视/巡逻” remains `routine`, custom and locale terms follow the same resolved contract, and manifest version/digest changes with the projection
**And** a candidate bound to a stale taxonomy version or digest is rejected with the refresh behavior fixed by Story 6.1.

### Story 6.3: Resolved Slot Contract Projection and Parity

As an action contract maintainer,
I want slot metadata to have a single resolved projection or executable parity gate,
So that resolver, binder, manifest, and internal prompt do not maintain incompatible requirements.

**Acceptance Criteria:**

**Given** an action declares required slots, any-of groups, aliases, types, AI-fillable fields, binding rules, or confirmation requirements
**When** its resolved slot contract is built
**Then** the resolver contract produces one normalized metadata projection consumed by binder, manifest, and internal prompt
**And** requirement groups such as `random_table` table-or-dice remain expressible without consumer-specific exceptions.

**Given** a legacy runtime table cannot yet be removed safely
**When** focused parity tests compare it with the resolved projection
**Then** any missing, extra, or semantically different slot metadata fails with the owning action and field identified
**And** unguarded parallel hand-maintenance is not accepted as a finished state.

**Given** slot projection cleanup is implemented
**When** binding and visibility regression gates run
**Then** current required/any-of behavior, aliases, confirmation, player-visible entity binding, and hidden-content exclusion remain unchanged
**And** this story does not compress route representations, introduce a Coordinator, or claim a runtime defect that was not reproduced.

### Story 6.4: Atomic Pending Confirmation Claim and Replay Classification

As a player host,
I want pending confirmation to have an atomic claim and stable replay result,
So that concurrent or retried confirmation cannot report multiple fresh commits or duplicate facts.

**Acceptance Criteria:**

**Given** two callers concurrently confirm the same valid pending session
**When** SaveManager claims and commits the proposal
**Then** exactly one caller receives fresh `committed` and the other receives `already_confirmed` with `idempotent_replay=true`
**And** SQLite records only one turn/event/fact transition.

**Given** commit succeeds but the process fails before pending state is cleared
**When** the same identity and session retry confirmation
**Then** SaveManager and CommitService classify the existing command/event as `already_confirmed`, safely reconcile pending state, and do not report a fresh commit
**And** recovery is proven with subprocess or equivalent crash-window evidence.

**Given** a replay uses a different identity, active save, session, command, or proposal payload
**When** confirmation is attempted
**Then** it returns conflict or the existing identity/session mismatch result rather than idempotent success
**And** player confirmation, validation, write guard, and commit authority are not weakened.

### Story 6.5: Explicit Pending Supersede and Clarification Lifecycle

As a player host,
I want pending and clarification sessions to have explicit supersede, expiry, cancel, and correction semantics,
So that new input cannot silently erase another caller's work or trap a player in an opaque recovery loop.

**Acceptance Criteria:**

**Given** one active Save already has a pending action or clarification
**When** a new player turn arrives
**Then** the V1 single-pending contract uses compare-and-supersede: the same identity may replace it only through explicit supersede, while a different actor/session receives conflict
**And** save switch, expiry, cancel, migration, and orphan cleanup have structured, testable outcomes rather than unconditional deletion.

**Given** a pending clarification is created
**When** its lifecycle is inspected or a player-safe cancel is requested
**Then** it uses the same default 1800-second TTL as pending actions, records expiry and origin, and can be canceled without writing gameplay facts
**And** stale or canceled clarification cannot authorize preview, pending action, confirmation, or commit.

**Given** the clarification origin is `candidate_contract_mismatch`
**When** the same identity submits the matching `clarification_id`, original text, and corrected external candidate
**Then** the request may be revalidated without treating candidate correction as player confirmation
**And** a genuine player-input ambiguity still requires a fresh player answer.

**Given** MCP or platform surfaces track clarification state
**When** SaveManager persisted state changes
**Then** adapters mirror, gate, and forward the canonical session instead of owning a second business-state truth
**And** adapter restart does not create a different clarification lifecycle.

### Story 6.6: Explicit Preflight Consumer Purpose

As a runtime integrator,
I want every preflight consumer to declare its purpose,
So that diagnostics cannot accidentally consume authoritative single-use review evidence intended for formal routing.

**Acceptance Criteria:**

**Given** `GMRuntime.start_turn()` is used for context or diagnostics
**When** matching ready preflight evidence exists
**Then** `start_turn` declares diagnostic purpose and does not claim or mark the evidence `used`
**And** it has no opt-in switch that converts the diagnostic entry into an authoritative consumer.

**Given** a formal player route or trusted preview is allowed to consume preflight evidence
**When** `IntentRequestMeta.consumer_purpose` is evaluated
**Then** only the named formal route/preview purpose can perform the single-use claim
**And** missing, unknown, or mismatched purpose fails safely or falls back without borrowing another entry's authority.

**Given** consumer-purpose behavior changes
**When** preflight regression gates run
**Then** CAS, identity, TTL, `message_only` isolation, late/used/replay handling, and enabled-mode degradation remain correct
**And** preflight remains advisory rather than proposal, permission, confirmation, validation, or commit authority.

### Story 6.7: Safe Intent Audit Reconstruction Summary

As an engine maintainer,
I want provider audit to reconstruct the normalized route class without exposing sensitive payloads,
So that incidents can be explained without turning audit into a hidden-data or authority surface.

**Acceptance Criteria:**

**Given** an intent request completes, clarifies, blocks, or fails
**When** MCP/provider audit writes its result summary
**Then** allowlisted normalized metadata can distinguish external mode/action class, rules mode/action class, selected source/outcome, clarification/failure class, manifest version/digest, and preflight consumer purpose
**And** an incident such as external=query versus rules=routine can be reconstructed without the raw candidate object.

**Given** candidate slots, reason, player text, session identity, provider output, private reasoning, or hidden context exists
**When** the audit summary is serialized
**Then** raw values are omitted or reduced to approved hashes/enums/counts
**And** privacy/hidden-content tests prove the summary does not expose those values or act as an existence oracle.

**Given** audit writing fails or an audit record is replayed
**When** the gameplay/tool operation completes
**Then** audit remains non-authoritative evidence and cannot change profile gate, routing, pending state, player confirmation, validation, or facts
**And** failure is reported only through the existing safe warning/evidence boundary.

### Story 6.8: RPG Engine Compatibility Fixture for Hermes Stdio E2E

As a cross-repository integration maintainer,
I want a stable RPG Engine provider fixture for the Hermes compatibility suite,
So that real stdio behavior can be tested without making RPG Engine own Hermes client lifecycle.

**Acceptance Criteria:**

**Given** the compatibility fixture starts an RPG Engine MCP provider
**When** a scripted client runs deterministic transcripts
**Then** it uses real stdio FastMCP, a scripted model contract, temporary Save data, and hooks for manifest version/digest, candidate refresh, `player_turn`, `player_confirm`, and safe audit
**And** it requires no network or API key.

**Given** the fixture or its tests can write runtime state
**When** verification runs
**Then** all writes stay inside temporary Campaign/Save/workspace copies
**And** source Campaigns, formal Saves, workspace registry, `data/game.sqlite`, and player data fingerprints remain unchanged.

**Given** provider fixture CI and full compatibility CI are assigned
**When** ownership is checked
**Then** RPG Engine CI validates only the provider fixture and contract outputs, while Hermes CI owns the real client, tool registration, next-model-turn barrier, reconnect lifecycle, and combined release gate
**And** Hermes H1-H4 status is not tracked as RPG Engine sprint state.
