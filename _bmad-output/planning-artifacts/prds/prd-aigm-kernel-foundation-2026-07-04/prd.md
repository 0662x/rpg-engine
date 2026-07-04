---
title: "AIGM Kernel 基础 PRD"
status: final
created: "2026-07-04"
updated: "2026-07-04"
---

# AIGM Kernel 基础 PRD

## 0. 文档目的

这份 PRD 定义 RPG Engine / AIGM Kernel 的 v1 基础方向。它面向引擎作者、后续 BMAD architecture/story 工作流，以及未来负责实现的 agent。目标是在继续重构或扩展引擎前，先形成清晰的产品契约。

这份 PRD 建立在已有 execution-chain SPEC 和 Architecture Spine 之上，不替代它们：

- `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/SPEC.md`
- `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/surface-taxonomy.md`
- `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/verification-gates.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`

本 PRD 有意聚焦 foundation 工作：先说清楚这个引擎到底要成为什么，再谈优化、玩法扩展、作者工具打磨或更复杂的产品形态。

## 1. 愿景

RPG Engine / AIGM Kernel 应该成为一个 AI-first、本地优先、面向长期文本 RPG 的通用 AIGM 游戏基座：作者能写剧本包，AI 能自然主持，玩家能长期玩，事实不会乱，并且引擎有足够结构支撑“好玩”，而不只是“能跑”。

这个引擎不是传统规则驱动 RPG 引擎。它应该让 AI 做现代模型擅长的事：理解自然语言、辅助上下文、总结、维护实体、推动剧情。Kernel 则负责它更适合强约束的事：事实、存档、隐藏信息、校验、实体状态、进度状态和安全提交边界。

长期目标是：更换不同 Campaign Package，就能承载不同类型的 AIGM 游戏，而不是每换一种题材或玩法就重写 Kernel。不同游戏的世界设定、实体、关系、目标、规则、进度结构和主持材料应主要由剧本包表达；Kernel 提供稳定通用的承载、校验、查询、上下文和提交能力。

v1 foundation 首先服务引擎作者本人作为 builder 和 game host 的使用场景，不需要先满足广泛外部用户。但它必须建立一套稳定基础，让后续优化和扩展不需要反复推倒核心边界。

## 2. 目标用户

### 2.1 Jobs To Be Done

- 作为引擎作者，我需要理解并控制引擎基础，避免质量依赖偶然写出来的代码形状。
- 作为游戏主持者，我需要引擎保存事实、隐藏信息、状态变化和进度，同时让 AI 围绕这些事实自然主持和叙事。
- 作为剧本作者，我需要剧本包能表达实体、关系、目标、进度和游戏结构，使 AI 能主持这类游戏。
- 作为外部 AI 集成者，我需要引擎能接收 AI 理解好的意图候选，但不能把 AI 输出当成最终权威。
- 作为未来实现者，我需要稳定的 PRD 级需求，使后续 architecture、epics、stories 和 tests 能从同一个产品契约派生。

### 2.2 v1 非目标用户

- 公开多人游戏 host。
- 商业 live-service 运营者。
- 需要复杂 UI 的游戏客户端用户。
- 期待成熟 no-code 剧本编辑器的作者。
- 需要 cloud-first 部署或分布式运行时协调的系统。

### 2.3 关键用户旅程

- **UJ-1. Oliver 运行一个长期本地 AIGM 战役而事实不漂移。** Oliver 启动或恢复本地 campaign，通过普通 player-safe path 输入玩家行动，用 AI 做自然理解和主持，对重要行动进行确认，并期望引擎在多次会话中持续保持事实、存档、隐藏信息和进度一致。

- **UJ-2. Oliver 开发一个 AI 能主持好的剧本包。** Oliver 定义包含实体、关系、进度结构和上下文相关事实的剧本材料。引擎可以加载和查询这些结构，让 AI 获得足够准确的信息，不必猜关键状态。

- **UJ-3. Oliver 让外部 AI 或后台 AI 帮忙，但不交出事实权威。** 外部 AI 或 resident/background AI 可以帮助分类意图、总结上下文、维护实体、追踪进度或建议剧情推进。引擎只把这些输出当作候选或 advisory material，直到 kernel 的校验和提交边界接受它。

## 3. 术语表

- **AIGM Kernel**：本地优先的通用 AIGM 游戏基座，负责承载、校验、存储、查询、上下文拼装和安全提交边界；不负责替作者创作具体世界设定、关系或进度内容。
- **Campaign Package**：作者提供的游戏内容和结构，包括世界事实、实体、关系、目标、进度定义、规则和剧本材料；它负责 authored content 的来源。它是当前代码和 canonical docs 的实现名，对应早期讨论里的“剧情包/剧本包”和 PRD 草稿中的 Scenario Package 概念。
- **Save Package**：运行时玩家/campaign 状态，包括 SQLite 事实、事件、投影、pending action 和存档元数据。
- **Player-Safe Path**：普通 gameplay 路径；当前实现名主要是 `SaveManager.player_turn()` / `SaveManager.player_confirm()`。它可以创建 pending action，但提交 gameplay facts 前必须获得玩家确认。
- **AI Intent Candidate**：由外部 AI、内部 AI、后台 AI 或 fallback logic 提供的低信任玩家意图解释。当前实现中相关名字包括 `external_intent_candidate`、`IntentCandidate`、`AIIntentRouter`、`ActionIntent` 和 `intent_preflight_cache`。
- **Resident AI**：v1 的后台/内部 AI 能力，用于意图识别、上下文总结、实体维护、进度管理和剧情推进，但不拥有 commit authority。当前代码已有 `ai/`、`ai_intent/`、`context/semantic.py`、`archivist.py`、`reflection.py`、`memory.py`、`ai/state_audit.py`、`delta_draft.py`、`response_acceptance.py`、`turn_assistant.py`、`proposal_queue.py` 等分散基础；`Resident AI Coordinator` 是后续要收敛的协调层，不是当前已完成类。
- **Resident AI Coordinator**：v1 resident AI 的调度和 provenance 层，负责组织多个窄助手的输入/输出、记录来源和结果，但不直接写事实。实现时应优先复用当前 AI/context 模块，不要求先新建独立目录。
- **Resident AI Assistant**：resident AI 下的窄能力助手，例如意图识别、上下文总结、实体维护建议、进度管理建议或剧情推进建议。
- **Entity**：游戏对象，例如人物、地点、物品、阵营、线索、任务对象、场景对象或抽象追踪对象。当前实现锚点是 SQLite `entities` 表和 typed side tables。
- **Relationship**：实体之间的存储连接，例如认识、位于、拥有、属于、态度、依赖、冲突或叙事关系。当前实现是 `relationship` content type，导入后作为 `type: relationship` 的 entity，关键字段进入规范化 `details`。
- **Progress Track / Clock**：目标、任务、探索、关系、资源、时间、剧情阶段或 campaign progress 的可量化/可检查状态。当前实现主干是 `clocks` 表、`clock` content type 和 delta 中的 `tick_clocks`。
- **Plot Progression Signal**：帮助 AI 推断剧情推进的结构化信号，例如世界设定、相关实体、关系、进度、近期事件、长期记忆和隐藏边界。
- **Plot Beat / Storylet**：可选的未来剧情推进单元，通常包含可播放内容、前置条件和执行后对世界状态的影响。当前 v1 不要求作者先写正式 storylet package。
- **Context Slice**：每轮给 AI 或 host 使用的结构化上下文切片，包含当前行动相关的实体、关系、进度、近期事件、长期记忆和 visibility 约束。当前实现名是 `ContextBuildResult`，入口是 `build_context()`，审计落在 `context_runs` / `context_items`。
- **Context Assembly**：为 AI 和玩家可见输出选择准确、相关、符合 visibility 边界的信息的过程。
- **Hidden Information**：GM-only 或玩家不可见事实，不能泄露到玩家视图、普通 query、scene output 或不合适的 AI prompt。

## 4. 产品原则

- **AI-first interpretation, kernel-enforced facts。** 自然语言理解应主要由 AI 完成。规则可以保留为 fallback、guard 或 deterministic aid，但不应作为开放式玩家意图的主判断策略。
- **分层约束。** 事实、存档、隐藏信息、校验和 commit 边界强约束；叙事、意图理解和剧情推进弱约束，让 AI 和引擎各自做擅长的事情。
- **无内部 AI 也能跑，有 resident AI 更好用。** v1 即使没有内部 AI 也必须能兜底运行，效果可以只是凑合；resident AI 仍是 v1 需求，但质量允许逐步迭代。
- **剧本和存档支持是产品能力。** Campaign Package、Save Package 和作者/host 工作流不是边角工具，而是 AIGM Kernel 好不好用的一部分。
- **接口是产品质量的一部分。** 引擎内部模块之间、以及对 CLI/MCP/platform/外部 AI caller 暴露的能力，都必须有清晰、稳定、可理解的接口。PRD 规定这个质量要求；具体模块/API contract 由后续 architecture 和 stories 落实。
- **内容归剧本包，机制归 Kernel。** 世界设定、初始实体、初始关系、目标、进度定义和剧本材料由 Campaign Package 提供；Kernel 负责让这些内容有稳定 schema、校验、存储、运行态更新和上下文召回。
- **通用基座，不是单一剧本引擎。** Kernel 应提供跨类型复用的通用原语和边界，例如 entity、relationship、progress、visibility、context、intent、validation、commit、Campaign/Save package。具体题材和玩法差异应优先由 Campaign Package、capability declaration、规则和可扩展 action/context hooks 承载。
- **好玩需要剧本结构和引擎承载。** v1 不需要支持所有游戏类型，但必须让剧本包能表达清楚的实体关系、可量化进度和足够准确的上下文，Kernel 再可靠地承载和召回这些内容。
- **先 foundation，再优化。** v1 先建立稳定边界和数据概念。延迟、打磨和更广泛扩展可以之后改善，但不能靠反复重写核心来换。

## 5. 功能

### 5.1 稳定的 Player-Safe 执行链

**描述：** 普通 gameplay action 必须有清楚路径：输入、意图候选、preview、pending action、玩家确认、validation、commit、projection refresh。这个 feature 继承已有 execution-chain Architecture Spine，并作为更大 foundation 的一部分。

#### FR-1: 保留普通 player-safe commit flow

引擎必须保留 player-safe flow：普通 gameplay 写入必须经过 player turn、pending action、player confirmation、validation 和 commit。

**可测试后果：**
- `player_turn` 或等价入口可以创建 pending action 或 clarification，但不能提交 gameplay facts。
- `player_confirm` 或等价入口是普通玩家路径的 commit gate。
- Commit 必须需要 validation 和 approved proposal/delta contract。

#### FR-2: 分类 public / semi-public surfaces

引擎必须按权限分类 public 和 semi-public entry surfaces：player-safe、trusted low-level、maintenance/admin、platform sidecar、platform prewarm、projection/outbox。

**可测试后果：**
- 新命令、MCP tool、platform entry point 和 runtime helper 必须声明分类。
- 跨分类 surface 必须拆分，或用明确 gate/profile/session check 表达权限切换。
- maintenance/admin 和 low-level tools 不能被描述成普通玩家玩法入口。

#### FR-3: 保持 projection/outbox 非事实权威

Projection 和 outbox 输出必须保持为 post-commit read model 和 evidence，不能成为 gameplay fact authority。

**可测试后果：**
- SQLite facts 保持事实权威。
- Projection/outbox 失败必须可见、可报告、可修复。
- Projection artifacts 不能绕过 pre-commit validation 或 player confirmation。

### 5.2 AI-First 意图与 Resident AI 边界

**描述：** 引擎应从“规则匹配作为开放式自然语言意图主策略”转向 AI-first。外部 AI 或 resident/internal AI 可以提供意图理解和后台辅助，但 kernel 保留 validation、hidden access 和 commit authority。

#### FR-4: 接收低信任 AI intent candidates

引擎必须能接收外部或 resident AI intent candidates，但不能把它们当成最终权威。

**可测试后果：**
- AI candidates 可以表达 action、mode、slots、confidence、missing information 和 reasoning。
- AI candidates 不能表达 player confirmation、hidden-access permission、proposal approval 或 save authorization。
- 当 AI 不可用时，引擎可以 fallback 到 deterministic rules，但 rule matching 不是产品的主 NLU 策略。

#### FR-5: 提供 v1 Resident AI Coordinator 和窄助手

引擎 v1 必须包含最小 resident/background AI 能力，形态为 Resident AI Coordinator 加多个 Resident AI Assistant。Coordinator 负责调度和 provenance；窄助手分别覆盖意图识别、上下文总结、实体维护辅助、进度管理辅助和剧情推进辅助。

**可测试后果：**
- Resident AI Coordinator 和 Assistant 输出默认为 advisory 或 candidate material，除非经过 kernel boundary 接受。
- Resident AI Coordinator 不能直接写 gameplay facts、确认玩家行动、绕过 hidden boundary 或绕过 commit validation。
- 每个 Resident AI Assistant 必须有窄职责和可解释输出，避免形成不可调试的大黑盒。
- Resident AI 质量可以在 v1 之后继续迭代，但 foundation 必须从一开始定义它的角色。
- 没有 resident AI 时，引擎仍能以较低质量运行。

#### FR-6: 降低 AI 参与时的玩家等待

引擎必须把 AI 延迟视为 intent 和后台辅助的产品约束。

**可测试后果：**
- 设计允许在安全前提下使用 preflight、background preparation、cache 或 asynchronous assistance。
- 延迟优化不能把 preflight/background AI 变成 commit authority。
- 慢 AI 路径必须安全降级为 fallback 或 clarification，而不是 unsafe commit。
- v1 player-facing AI assistance 以约 8 秒作为软等待上限；超过软上限应显示 fallback/clarification 或继续不用 AI 的安全路径。
- v1 player-facing AI assistance 不应无限等待；约 15 秒应作为 hard timeout 候选，具体数值由 architecture/implementation 校准。
- Resident/background AI 的总结、实体维护和剧情推进建议可以异步执行，目标是 30-60 秒内产出 advisory result，且不能阻塞事实提交。

### 5.3 Entity、Relationship 和 Progress 承载基础

**描述：** 具体实体、关系和进度内容由 Campaign Package 和运行时 Save Package 提供。引擎需要提供足够清晰的承载模型、校验、查询和运行态更新边界，使 AI-hosted 游戏能在长期会话中保持连贯。

#### FR-7: 表达清楚的实体关系

引擎必须支持存储和查询由 Campaign Package 或 Save Package 提供的重要实体关系，例如谁认识谁、谁在哪、谁拥有什么、实体之间的态度是什么。

**可测试后果：**
- Relationship 必须足够 first-class，可以被 context assembly 和 Campaign logic 使用。
- Relationship reads 对 host / AI workflows 足够方便。
- Relationship updates 仍受 validation 和 commit rules 管理。

#### FR-8: 追踪可量化进度

引擎必须支持由 Campaign Package 定义、并在 Save Package 中随游玩变化的 progress tracks，用于任务、探索、关系、资源、时间、剧情阶段或 campaign goals。

**可测试后果：**
- Progress 可被 AI 和 engine logic 读取。
- Progress 可以通过 validated gameplay 或 maintenance workflows 改变。
- Progress state 能帮助回答“游戏现在推进到哪里了”。

#### FR-9: 支持实体维护辅助

Resident AI 可以帮助提出实体创建、实体更新、关系变化和进度变化，但这些建议必须作用于剧本包/存档中的内容模型，最终写入边界仍属于引擎。

**可测试后果：**
- AI 可以根据 play context 建议缺失实体或关系更新。
- 建议变更需要 review、validation 或明确 trusted path 才能成为事实。
- AI-assisted entity work 仍必须遵守 hidden information rules。

### 5.4 Context Assembly 和 Visibility 基础

**描述：** AI 要主持得好，必须拿到足够准确、相关、符合 visibility 的上下文。Context assembly 必须成为 first-class foundation capability，而不是一堆 prompt fragments。

#### FR-10: 组装准确的 player-safe context

引擎必须组装能给 AI 足够相关事实的 context，减少遗忘事实或编造关键状态。

**可测试后果：**
- Context 在适用时包含相关实体、关系、地点、inventory/state、progress 和 recent events。
- Context 根据当前 action/query/play situation 做 scope。
- Context assembly 必须足够 deterministic / inspectable，便于调试。

#### FR-11: 在 context 中执行 hidden information 边界

引擎必须防止 hidden/GM-only 信息泄露到 player-visible views、ordinary query、scene output 或不合适的 AI prompts。

**可测试后果：**
- Context items 必须携带或遵守 visibility。
- Player-safe AI prompts 不包含 hidden facts。
- 触碰 context path 的改动必须覆盖 hidden-content leakage 测试。

#### FR-12: 支持长期游玩的总结

Resident AI 或相关机制必须能总结相关游戏历史，使长期会话可继续使用，而不会把 prompt 塞爆。

**可测试后果：**
- Summaries 应尽量基于 evidence，并能追溯到 stored facts/events。
- Summaries 不能覆盖 authoritative facts。
- Summary 的 freshness/staleness 必须足够可见，便于调试。

### 5.5 Campaign 和 Save 基础

**描述：** Campaign Package 和 Save Package 是核心产品 surface。v1 应使它们可靠到足以让引擎作者构建并运行本地长期 AIGM 游戏。

#### FR-13: 支持面向 AIGM play 的 Campaign packages

Campaign packages 必须能表达 AI-hosted play 所需的基础结构：实体、关系、目标/进度、campaign facts、capability declarations、规则和 gameplay scaffolding。更换 Campaign Package 应是切换游戏题材和大部分玩法结构的主要方式。

**可测试后果：**
- Campaign material 可以进入 context assembly。
- Campaign structure 可以支持 progress 和 entity relationship queries。
- Campaign package validation 能捕获缺失或 malformed foundation data。
- 新增普通题材或常见玩法变体时，应优先通过 Campaign Package 内容、声明和规则表达，而不是要求修改 Kernel 核心。

#### FR-14: 保持 save package fact integrity

Save packages 必须保持为长期本地 play 的 authoritative runtime state。

**可测试后果：**
- Current facts、events、pending actions、projections 和 metadata 按职责分离。
- 测试不能直接修改 formal current save packages。
- Save import/export 或 maintenance flows 不能意外绕过 gameplay validation。

#### FR-15: 提供 foundation-level author/host operations

引擎必须提供足够的 CLI/MCP/maintenance workflow 支持，使 engine author / host 能 inspect、validate 和 operate Campaign/Save foundations。

**可测试后果：**
- v1 不要求复杂 UI 或成熟 no-code authoring tool。
- CLI/MCP/platform adapters 保持 thin wrapper，并调用 kernel services。
- Author/host operations 应提供有用 diagnostics，但不能成为普通 gameplay bypass。
- Campaign package diagnostics v1 必须优先捕获会导致 AI 乱主持、事实断裂或 hidden 泄露的问题。
- V1 diagnostics 至少覆盖：YAML/manifest/schema parse、required roots、entity reference integrity、relationship endpoint integrity、progress/clock completeness、visibility/hidden leakage risk、capability declarations 与 smoke tests 的匹配、缺失 summary/aliases 的 context usability warning。
- V1 diagnostics 不要求评价文笔、剧情好坏、美术风格或完整 no-code authoring 体验。

#### FR-16: 建立清晰的内部与外部接口契约

引擎必须把核心能力以清晰接口暴露给内部模块和外部 caller，避免功能依赖隐式调用、重复业务逻辑或难以维护的跨层耦合。

**可测试后果：**
- 核心能力应能通过命名清晰的 internal service/runtime boundary 调用，而不是散落在 CLI/MCP/platform handler 中。
- 外部 surfaces 应有明确输入、输出、错误形状、权限边界和写入权威说明。
- 后续 architecture/stories 必须把具体接口 contract 落到模块/API 层，而 PRD 不规定具体类名或函数签名。
- 后续 architecture 至少必须定义这些契约族：Campaign Package Contract、Save Fact Contract、Content Type / Merge Contract、Intent Candidate Contract、Context Slice Contract、Resident AI Advisory Contract、Response / Delta Assistant Contract、Entity/Relationship/Progress Access Contract、Proposal/Review Queue Contract、Validation/Commit Contract、Surface Authority Contract。
- 每个契约族都必须说明输入、输出、错误、权限、visibility 规则、事实写入权威和可测试边界。

#### FR-17: 支持通用基座与剧本替换

Kernel 必须把跨游戏通用能力和具体剧本内容分开，使不同类型的 AIGM 游戏可以共享同一套基础执行链、事实边界、上下文机制和存档机制。

**可测试后果：**
- Campaign init / save init / context assembly / validation / commit 对不同 Campaign Package 使用同一套基础边界。
- Campaign Package 可以声明本剧本使用的 capabilities、内容类型、规则、初始状态和 author tests。
- 当一个新游戏只需要已有通用原语时，不应要求改动 Kernel 核心事实/提交链。
- 当确实需要新增基础能力时，应通过清晰 extension point 或 architecture decision 引入，而不是在某个剧本里临时分叉核心逻辑。

## 6. V1 游戏状态最小模型

本节是 PRD 级产品决策：v1 不追求完整传统 RPG engine ontology，也不立即重写成完整 ECS、复杂 quest system 或正式 storylet package。v1 的目标是建立 AIGM 最需要的最小稳定模型，让 AI 能主持、作者能写、存档事实不乱、长期游戏有可追踪进展。

当前实现已经有可用骨架：`entities` 作为统一身份锚点，typed side tables 增加结构化字段，`facts/events` 保存事实和审计，`clocks` 保存量化进度，`memory/context` 支撑长期上下文。v1 应沿着这个方向补强，而不是推倒重来。

### 6.0 内容所有权边界

世界设定、初始实体、初始关系、目标、进度定义、规则和剧本材料由 Campaign Package 负责。玩家游玩后的当前事实、关系变化、进度变化和事件历史由 Save Package 保存。AIGM Kernel 负责 schema、校验、导入、存储、查询、上下文拼装、可见性约束和提交边界。

**产品决策：**
- Kernel 不替作者创作世界设定、关系或目标进度。
- Kernel 必须让 Campaign Package 能表达这些内容，并在初始化或同步时安全进入 Save Package。
- Runtime 中的关系/进度变化属于 Save Package 当前事实，必须经过 validation/commit。
- AI 可以建议内容变化或剧情推进，但不能越过 Campaign/Save/Kernel 的所有权边界。

### 6.1 Entity 保持统一身份锚点

v1 应继续把 Entity 作为所有持久游戏对象的统一身份锚点。人物、地点、物品、线索、项目、阵营状态、关系、进度钟和世界设定由 Campaign/Save 提供内容，Kernel 负责让它们能被稳定引用、查询、进入上下文，并被事实/事件追踪。

**产品决策：**
- 不引入并行身份系统。
- 不把所有类型都做成独立根对象。
- typed side table 或 typed subrecord 可以继续存在，但必须引用 Entity。
- `details` 可以保留为扩展区，但 v1 关键 gameplay 字段不能只靠随手约定藏在 `details` 里。

### 6.2 Relationship 成为 first-class 产品概念

Relationship 在 v1 必须是作者、AI、context assembly 和 gameplay update 都能依赖的 first-class 概念。关系内容由 Campaign Package 定义初始状态，并由 Save Package 记录运行态变化；Kernel 负责统一承载、校验、查询和上下文召回。它不一定在 v1 立刻需要独立 SQL 表；可以先以 relationship entity + 规范 details/subrecord 实现。但对外和对内接口必须把它当作明确概念，而不是普通文本字段。

**最小字段方向：**
- `id`
- `source_id`
- `target_id`
- `kind` 或 `state`
- `stance` / `attitude` / `trust` / `tension` 中的最小可用组合
- `visibility`
- `summary`
- `updated_turn_id` 或等价 evidence 指针

**产品决策：**
- “谁认识谁、谁对谁什么态度、谁依赖谁、谁与谁冲突”应能直接查询和进入上下文。
- 关系变化可以由 AI 建议，但必须通过 validation/commit 才能成为事实。
- v1 不要求完整社交模拟系统，但要避免关系只散落在角色 `details.relationship_to_pc` 这种不可统一检索的字段中。

### 6.3 Progress Track / Clock 是 v1 量化进度核心

v1 的任务、威胁、探索、关系推进、资源压力、时间压力和剧情阶段，优先用 Progress Track / Clock 表达。具体进度目标和初始轨道由 Campaign Package 负责，运行态数值和推进历史由 Save Package 保存，Kernel 负责统一机制和边界。Progress Track 是产品概念；当前 `clocks` 可以作为主要实现基础。

**最小字段方向：**
- `id`
- `kind` / `clock_type`
- `scope` 或关联实体列表
- `segments_total`
- `segments_filled`
- `visibility`
- `trigger_when_full`
- `tick_rules`
- `status`
- `updated_turn_id` 或等价 evidence 指针

**产品决策：**
- v1 不先构建复杂 quest ontology。
- project、quest、threat、relationship arc 和 plot phase 都可以先映射到 progress track。
- progress 应反映游戏局势，不应替代叙事本身。
- progress 变化必须可解释：为什么 tick、谁触发、影响什么。

### 6.4 Plot Progression Signal 是 v1 剧情推进基础

为了支持“好玩”和 AI 主持，v1 需要先把 AI 推断剧情推进所需的信号准备好，而不是立即要求作者维护正式 Plot Beat / Storylet 系统。这些信号的内容主要来自 Campaign Package 和 Save Package；Kernel 负责把它们按 visibility 和相关性拼装给 AI。当前剧情推进可以主要由外部 AI 或 resident AI 根据世界设定、上下文、记忆、实体关系和进度状态合理推断。

**最小信号方向：**
- 相关 world settings / rules。
- 当前和近期事件。
- 关键实体及其位置、状态和目标。
- 关键 relationships。
- 活跃 progress tracks / clocks。
- 长期 memory summaries。
- 可见性和 hidden information 边界。
- 作者在 Campaign package 中提供的 hooks、goals、clues、project summaries 或其他轻量剧情提示。

**产品决策：**
- v1 不要求先新增 `storylets.yaml` 或完整剧情包推荐系统。
- v1 应优先保证 AI 能拿到来自 Campaign/Save 的准确、相关、visibility-safe 的剧情推进信号。
- 外部 AI 或 resident AI 可以建议剧情推进，但建议只能是 advisory/candidate material。
- 若后续引入 Plot Beat / Storylet，它应先作为可选作者结构或 context hint，而不是强制线性脚本或自动导演。
- 剧情推进产生的事实变化仍必须走 kernel validation/commit。

### 6.5 Context Slice 是 AI 主持的核心输出

AI 主持质量取决于它拿到的信息是否准确、相关、足够短且不泄露 hidden facts。v1 应把 Context Slice 当作核心产品输出，而不是拼 prompt 的副产物。

**最小内容方向：**
- 当前玩家状态和当前位置。
- 当前 intent/action 的相关实体。
- 与相关实体相连的 relationship。
- 活跃 progress tracks / clocks。
- 相关近期事件。
- 相关长期记忆总结。
- 必要 world settings / rules。
- visibility 和 hidden information 边界说明。

**产品决策：**
- Context Slice 必须 inspectable/debuggable。
- Context Slice 应服务 AI-first intent、resident AI、外部 AI host 和普通 query/action。
- Hidden facts 只能出现在明确 GM/trusted context 中，不能进入 player-safe context。

### 6.6 设计依据

- 现有代码已经具备 Entity anchor、typed side tables、facts/events、clocks、memory 和 context audit 的基础，应优先收敛为明确产品模型。
- Blades in the Dark 的 progress clocks 证明 progress clock 适合表示复杂障碍、逼近威胁和多层进展。
- Emily Short 的 storylet 模型证明“内容 + 前置条件 + 世界状态后果”适合比传统分支更灵活的互动叙事，但本 PRD 不把正式 storylet package 设为 v1 必做项。
- Fate Core 的 intent-first 原则支持本 PRD 的方向：先理解玩家想达成什么，再决定用什么机制处理。
- Component-style entity design 支持当前“统一 entity + typed structure”的方向，但 v1 不需要完整 ECS 重写。

## 7. Cross-Cutting NFRs

- **NFR-1 Safety:** AI 输出在未经 kernel 接受前，永远不是事实、最终意图、hidden access、approval 或 save authorization。
- **NFR-2 Maintainability:** 核心边界必须足够模块化，使 execution chain、AI intent、entity/relationship/progress、context assembly 和 Campaign/Save foundations 能演进，而不反复大重构。
- **NFR-3 Interface clarity:** 内部模块接口和外部调用接口必须清晰、稳定、可测试，减少跨层耦合和业务逻辑复制。
- **NFR-4 Debuggability:** Intent decision、context assembly、progress state、entity change 和 commit outcome 应留下足够证据，能解释发生了什么。
- **NFR-5 Local-first operation:** v1 面向本地、单人、单 campaign、长期 play。
- **NFR-6 Degraded operation:** 没有 resident/internal AI 时，引擎仍必须可用，虽然质量可以较低。
- **NFR-7 Latency awareness:** AI-assisted paths 应考虑玩家等待时间；当 AI 慢或不可用时必须安全降级。
- **NFR-8 Visibility correctness:** Hidden/GM-only data 不能泄露到 player context、ordinary query、scene output 或 player-safe AI prompts。

## 8. 明确非目标

- v1 不追求让 rule-only natural-language matching 对开放式玩家意图变准确。
- v1 不构建复杂图形 UI。
- v1 不把所有 gameplay genre 或 campaign type 的专用规则都内置进 Kernel。
- v1 不要求 resident AI 第一版就完美。
- v1 不增加 cloud-first、distributed、public-server 或 commercial launch infrastructure。
- v1 不通过削弱事实、hidden information、validation 或 commit boundaries 来优化延迟。
- v1 不替代 execution-chain Architecture Spine，而是把它作为 foundation constraint 纳入。
- v1 不重写成完整 ECS，也不先构建复杂 quest system、正式 storylet package 或通用剧情调度器。

## 9. MVP 范围

### 9.1 In Scope

- 稳定 player-safe execution chain 和 authority taxonomy。
- AI-first intent candidate flow，支持 external AI candidate 和 resident AI。
- 最小 resident AI loop：意图识别、上下文总结、实体维护、进度管理、剧情推进辅助。
- 清晰的内部模块接口和外部调用接口 foundation。
- Entity、relationship、progress track、plot progression signals 和 context slice foundations。
- 带 visibility-safe hidden information boundary 的 context assembly。
- 面向本地长期 play 的 Campaign package 和 save package foundation support。
- 通用 AIGM 基座原则：同一 Kernel 应能承载不同 Campaign Package，并通过通用原语、capability declarations 和 extension points 支撑题材/玩法差异。
- 通过现有 thin CLI/MCP/kernel surfaces 提供 foundation diagnostics 和 validation。

### 9.2 Out of Scope for MVP

- 多人、协作或 public server runtime。
- 商业发布 readiness。
- 复杂 UI 或 no-code Campaign editor。
- 一次性内置所有 RPG/gameplay structures 的专用结算器。
- 完整 latency optimization 或 background AI quality tuning。
- 大规模 infrastructure 或 deployment redesign。
- 完整 ECS rewrite、复杂 quest ontology、正式 storylet package、自动剧情导演或成熟 storylet scheduler。

## 10. 成功指标

**Primary**

- **SM-1:** 一个本地长期 campaign 可以经过多轮玩家行动推进，同时 facts、save state 和 hidden information 保持一致。验证 FR-1、FR-3、FR-10、FR-11、FR-14。
- **SM-2:** AI-assisted intent 可以由 external 或 resident AI candidates 驱动，同时 commit authority 仍在 kernel 内。验证 FR-4、FR-5、FR-6。
- **SM-3:** 一个 Campaign/Save 可以暴露 entities、relationships、progress tracks 和 plot progression signals，并被 context assembly 使用。验证 FR-7、FR-8、FR-10、FR-13、FR-17。
- **SM-4:** 核心内部模块和外部 surfaces 有清晰接口契约，能被 architecture/stories 引用并验证。验证 FR-2、FR-16、FR-17。

**Secondary**

- **SM-5:** 引擎作者可以 inspect/debug 一个 action、AI candidate、context payload、entity/progress update 或 commit 为什么被接受或拒绝。验证 FR-2、FR-9、FR-12、FR-15。
- **SM-6:** Resident AI Coordinator 能调度窄助手，并至少以最小方式辅助五类 v1 能力：意图识别、上下文总结、实体维护、进度管理、剧情推进。验证 FR-5。
- **SM-7:** 至少两个题材或 capability profile 不同的 Campaign Package 可以复用同一套 Kernel foundation flow 完成 init、save、context assembly、validation 和 basic play loop。验证 FR-13、FR-17。
- **SM-8:** Campaign package diagnostics 能捕获 broken references、缺失 required roots、malformed relationship/progress structures 和 hidden leakage risks，并给出可操作的作者/host 修复信息。验证 FR-13、FR-15。

**Counter-metrics**

- **SM-C1:** 不为了最快 AI 响应而削弱 hidden information、validation 或 commit boundaries。
- **SM-C2:** 不为了广泛玩法覆盖而牺牲 v1 foundation 稳定性，或把每种题材的专用规则都塞进 Kernel。
- **SM-C3:** 不把 rule-matching completeness 当成 AI-first intent 的替代目标。

## 11. 最终决策与转后续事项

### 11.1 已关闭的 PRD 决策

- **Campaign package diagnostics v1:** v1 diagnostics 重点检查会导致 AI 乱主持、事实断裂或 hidden 泄露的问题；美学、文笔和成熟 no-code authoring 留到 author tooling v2。
- **AI latency target:** v1 player-facing AI assistance 以约 8 秒作为软等待上限，约 15 秒作为 hard timeout 候选；resident/background AI 可以异步 30-60 秒产出 advisory result，不阻塞 commit。
- **Priority after PRD:** 后续优先顺序是接口契约与状态模型边界、context assembly、resident AI advisory loop、Campaign diagnostics、plot progression enhancements。
- **Required contract families:** 后续 architecture 至少定义 Campaign Package、Save Fact、Content Type / Merge、Intent Candidate、Context Slice、Resident AI Advisory、Response / Delta Assistant、Entity/Relationship/Progress Access、Proposal/Review Queue、Validation/Commit、Surface Authority 这些契约族。
- **Plot progression:** v1 不要求正式 Storylet package；剧情推进先依赖 Campaign/Save 提供的 plot progression signals，由外部 AI 或 resident AI advisory 合理推断。

### 11.2 转后续 Architecture

- **Relationship / Progress storage:** PRD 只要求 Relationship 和 Progress Track 是 first-class 产品/接口概念；是否新增 dedicated SQL tables，还是先用 entity + normalized details/service API，由下一轮 `bmad-architecture` 决定。
- **Storylet future placement:** 如果未来引入 Plot Beat / Storylet，优先作为可选 Campaign package schema 或 context hint；是否进入 resident AI advisory output 或 scheduler，由后续 architecture/game design 再判断。

## 12. Assumptions Index

- 当前草稿没有未解决的 inline `[ASSUMPTION]` 标签。现有 scope choices 已在 PRD discovery 中由用户确认。
