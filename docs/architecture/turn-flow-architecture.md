# RPG Engine 全链路设计说明和优化方案

文档状态：**设计说明、优化方案、详细开发计划与阶段落地记录**  
基准日期：2026-07-01  
专家复审结论：**设计方向通过，可按阶段实施；必须同步补齐 profile、测试矩阵、权限门禁、性能指标、外部 surface 管理、迁移/回滚和 projection repair 能力**  
当前代码评审校准：[`current-code-multi-expert-review.md`](current-code-multi-expert-review.md) 对当前实现给出 67/100。本文中的 Phase 0-7.1 “已完成”应理解为内部合同、主路径骨架和 projection 状态语义的阶段性架构里程碑，不代表默认 MCP/player surface、权限隔离、文件级可靠性、发布质量门和长期评估体系已经达到产品成熟度。进入完整 `TurnCoordinator` / `plan_turn -> validate_proposal -> commit_proposal` 前，应先完成当前代码评审中 R1-R4 的硬门槛：安全/profile 止血、玩家/MCP 默认工作流收敛、写入/投影/备份可靠性、质量门和发布链。  
相关代码：
[`runtime.py`](../../rpg_engine/runtime.py)、
[`context_builder.py`](../../rpg_engine/context_builder.py)、
[`mcp_adapter.py`](../../rpg_engine/mcp_adapter.py)、
[`cli.py`](../../rpg_engine/cli.py)、
[`cli_v1.py`](../../rpg_engine/cli_v1.py)、
[`turn_assistant.py`](../../rpg_engine/turn_assistant.py)、
[`proposal.py`](../../rpg_engine/proposal.py)、
[`delta_draft.py`](../../rpg_engine/delta_draft.py)、
[`response_acceptance.py`](../../rpg_engine/response_acceptance.py)、
[`validation_pipeline.py`](../../rpg_engine/validation_pipeline.py)、
[`commit_service.py`](../../rpg_engine/commit_service.py)、
[`save.py`](../../rpg_engine/save.py)、
[`unit_of_work.py`](../../rpg_engine/unit_of_work.py)、
[`projection_service.py`](../../rpg_engine/projection_service.py)、
[`projections.py`](../../rpg_engine/projections.py)、
[`preview.py`](../../rpg_engine/preview.py)、
[`content_delta.py`](../../rpg_engine/content_delta.py)、
[`content_sync.py`](../../rpg_engine/content_sync.py)、
[`save_patch.py`](../../rpg_engine/save_patch.py)、
[`simulation.py`](../../rpg_engine/simulation.py)、
[`actions/base.py`](../../rpg_engine/actions/base.py)

## 0. 执行摘要和阅读地图

一句话结论：本方案不是单点重构，而是把 RPG Engine 的普通玩家回合、外部 MCP 接入、AI client prompt/skill、Campaign Package、Save Package、validation、commit 和 projection 统一到一条可追踪、可测试、可回滚的全链路上。

设计判断：

- 设计方向通过：核心架构符合第 5.1 的职责单一、边界清晰、可测试、故障隔离和不过度设计原则。
- 当前实现已完成 Phase 0-7.1 主路径与投影边界硬化：surface/baseline、统一 `IntentRouter`、Agent 安全入口、严格 `TurnContract`、统一 `TurnProposal`、`ValidationPipeline` profile/stage 报告、`TurnCommitService` proposal commit 边界、集中 `ProjectionService` / `ProjectionReport`，以及 projection 事务边界、targeted repair、stale/version repair 和 commit/projection 状态 API；完整 `plan_turn -> validate_proposal -> commit_proposal` 工具仍是后续目标。
- No-AI path 是最低标准；AI helper 只能增强意图理解、叙事、proposal 草案和审计补充，不能绕过 resolver、delta schema、state audit、profile 或 commit 门禁。
- 外部 AI 是低信任调用者；MCP 默认只暴露玩家 workflow、受控存档选择/创建和只读检查；package/admin/maintenance 能力必须分层、打 profile、可审计、可回滚。
- Phase 0-7.1 实现已经过测试基线验证。下一步进入完整 `TurnCoordinator`/工具协议、`intent_ai=consensus` parity、导入/迁移批量 profile 报告和发布/回滚说明；这些后续工作不能回退 Phase 7.1 已建立的 projection 事务、作用域和状态 API 边界。

阅读地图：

| 读者目标 | 优先阅读 |
|---|---|
| 快速理解结论 | 第 0 节、第 13 节、第 15 节 |
| 理解为什么需要优化 | 第 2-4 节 |
| 理解目标架构 | 第 5-7 节 |
| 理解 MCP、AI prompt/skill、包管理边界 | 第 8.6 节、第 9.15 节、第 10.3 节 |
| 对照外部项目经验校准 Phase 3 | [`external-projects-review.md`](external-projects-review.md) |
| 看开发计划 | 第 10.1-10.3 节，尤其是 Phase 7.1 落地记录 |
| 看验收和专家门槛 | 第 13 节 |
| 看当前已落地和未落地 | 第 11 节、第 14 节、[`phase-0-surface-inventory.md`](phase-0-surface-inventory.md)、[`phase-0-performance-baseline.md`](phase-0-performance-baseline.md) |
| 看最终审核意见 | 第 15 节 |

## 1. 文档目标和范围

本文聚焦 RPG Engine 从玩家输入到存档和投影输出的完整回合链路：

```text
用户输入
  -> 意图识别
  -> 上下文装载
  -> 行动预演
  -> AI/人类叙事和候选 delta
  -> 校验和审计
  -> 写入存档
  -> 投影产物
  -> 输出给玩家和下一轮
```

本文目标是给出一条可落地的全链路优化方案，而不只是修补某个行动模板误判。具体目标：

- 统一自然语言入口，避免 `start_turn()`、`act()`、外部 Agent、`preview_action()` 各自决定行动类型。
- 建立清晰的中间合同：`ActionIntent -> TurnContract -> TurnProposal -> ValidationReport -> CommitResult -> ProjectionReport`。
- 让 No-AI path 成为最低可用标准，规则、实体索引、resolver、schema、审计和投影在无 AI 时也能稳定运行；AI helper 只作为受控增强层。
- 收敛玩家保存路径，区分普通玩家回合、response acceptance、admin/legacy、maintenance/import 等 profile。
- 统一投影刷新语义，避免事实库、snapshot、cards、events、search、memory、reports 状态不一致。
- 把多角色评审意见转化为阶段门槛，而不是只停留在设计原则。

本文边界：

- 讨论架构设计、职责划分、迁移顺序和验收标准。
- 不要求一次性重写所有模块。
- 不取消低层工具、admin 工具或 maintenance 工具，但要求它们有明确 profile 和边界。
- 不允许 AI 绕过 resolver 合同、delta schema、state audit 或 commit 门禁。

当前引擎已经把查询、行动预演、delta 校验和保存拆成多个模块，这是正确方向。本文前半部分保留优化前基线和问题地图，用来解释为什么需要本方案；第 11 节记录截至 2026-07-01 已落地内容。阅读时应区分四类状态：

- 优化前基线：描述发现问题时的旧链路和风险。
- 已落地状态：本轮已经完成的 `IntentRouter`、`preview_from_text`、严格 `TurnContract` 消费、统一 `TurnProposal` 主路径、mismatch guard、profile 化 `ValidationPipeline` 和 `TurnCommitService`。
- 后续目标：完整 `TurnCoordinator`、目标期 `plan_turn -> validate_proposal -> commit_proposal` 工具、`intent_ai=consensus` parity，以及 maintenance/import 更完整 profile 报告。
- 专家补强项：本轮文档整理新增的多角色最终评审、量化验收门槛、外部 surface 详细开发计划、权限/profile 要求、性能和发布门槛。

基线中的核心问题是：若干阶段存在多个模块同时拥有“最终决策权”，导致链路可能互相打架。

最典型的优化前问题是自然语言行动类型判断：

- `start_turn()` 会构建上下文包，并通过 `classify_request()` 判断 `mode/submode`。
- `collect_semantic_suggestion()` 会调用可选 AI；当前 `apply_semantic_request_decision()` 只记录 trace/assumption，不再覆盖最终 `mode/submode`。
- 优化前 `act()` 会通过 `runtime.py` 内部旧 `infer_player_action()` 副本直接把自然语言转成 `action/options`，再调用 `preview_action()`。
- `preview_action()` 接收调用方传入的 `action`，只执行对应 resolver，不重新判断自然语言。
- 外部 AI 客户端在 MCP 链路中通常先调用 `start_turn()`，再自行选择是否调用 `preview_action(action, options)`。

这使得真局输入可能出现链路不一致。例如“巡视领地，查看各单位和角色的状态”在 `act()` 链路中可被理解为 `routine`，但在 `start_turn()` 规则初判中可能落到 `query:entity`，外部 AI 又可能错误调用 `preview_action(action="craft")`，最终进入制作预演。

同类问题还存在于 delta 来源、保存编排、投影刷新、回复验收等环节。下面按输入到输出链路展开。

## 2. 输入到输出链路：优化前基线与当前差异

### 2.1 MCP 玩家回合链路：优化前基线

```text
用户输入
  -> Hermes Agent / MCP client
  -> mcp_adapter.start_turn()
  -> GMRuntime.start_turn()
  -> build_context()
  -> classify_request()
  -> collect_entity_hits()
  -> collect_semantic_suggestion()
  -> apply_semantic_request_decision()
  -> expand_related_entities()
  -> run_context_collectors()
  -> validate_context()
  -> StartTurnResult
  -> 外部 AI 判断下一步
  -> mcp_adapter.preview_action(action, options)
  -> GMRuntime.preview_action()
  -> ActionResolver.request_contract()
  -> ActionResolver.resolve_contract()
  -> ActionResolver.preview()
  -> PreviewActionResult
  -> 外部 AI 生成叙事和 delta
  -> validate_delta()
  -> commit_turn()
```

优化前 `start_turn()` 的输出是上下文合同，不是行动预演结果。它会告诉调用方：

- `mode`: `query`、`action` 或 `maintenance`
- `submode`: `entity`、`scene`、`craft`、`routine` 等
- `requires_preview`: 是否需要预演
- `required_template`: 推荐回复模板
- `context`: 当前场景、相关实体、规则、历史、长期记忆等

`preview_action()` 的输入是已经确定的 `action/options`。优化前它不会验证调用方为什么选择这个 `action`，只会执行对应 resolver。

当前已落地差异：

```text
用户输入
  -> mcp_adapter.start_turn()
  -> GMRuntime.start_turn()
  -> build_context()
  -> route_intent()
  -> StartTurnResult(intent, turn_contract, decision_trace)
  -> mcp_adapter.preview_from_text(user_text)
  -> GMRuntime.preview_from_text()
  -> route_intent()
  -> preview_action(intent.action, intent.options, source_user_text=user_text)
```

也就是说，低层 Agent 面对自然语言时已有 `preview_from_text` primitive，不再需要手动猜 `preview_action(action, options)`。当前默认 player profile 则应走更高层的 `player_turn`。低层 `preview_action()` 仍保留，但当调用方传入 `source_user_text` 时会做轻量 action/text 冲突保护。

### 2.2 CLI 快捷行动链路：优化前基线

```text
  用户输入
    -> rpg_engine play act
    -> GMRuntime.act()
  -> runtime.py 旧 infer_player_action() 副本
  -> preview_action(inferred.action, inferred.options)
```

优化前这条链路不经过 `start_turn()` 的 `classify_request()`。它有自己的自然语言推断逻辑，因此可能和 MCP 真局链路产生不同判断。

当前已落地差异：

```text
用户输入
  -> rpg_engine play act
  -> GMRuntime.act()
  -> GMRuntime.preview_from_text(mode="action")
  -> route_intent()
  -> preview_action(intent.action, intent.options, source_user_text=user_text)
```

这样 CLI 与 MCP 的自然语言主路径已经共享同一个 `IntentRouter` 结果。

### 2.3 Runtime 玩家回合保存链路

```text
PreviewActionResult.delta_draft 或 AI 生成 delta
  -> GMRuntime.validate_delta(delta, action, action_options)
  -> validate_delta_schema()
  -> action resolver delta_contract()
  -> state_audit
  -> GMRuntime.commit_turn()
  -> backup
  -> save_turn_delta()
  -> UnitOfWork
  -> write turns/events/entities/clocks/meta
  -> mark standard projections dirty
  -> rebuild search
  -> event outbox / events.jsonl
  -> write snapshot/card
  -> mark snapshots/cards clean
```

这条链路是当前玩家回合的主路径，保存边界相对清晰：结构化 delta 通过校验和审计后才会写入当前事实。

但它并不是唯一会写入或刷新投影的路径。引擎内还有下列并行路径：

- `response_acceptance.accept_response()`：从 AI 回复文本反推 delta；当前只适合无真实状态变化或低风险验收，有状态变化草案会被 blocker 拦住。
- `turn_assistant.run_save_pipeline()`：报告型编排器里也可以校验、审计、备份和保存；Phase 5-7 后已经通过 validation/commit/projection service 表达 profile 和 projection report，但仍不是最终 `TurnCoordinator`。
- 顶层 `save-turn` CLI：保留为 admin/legacy 入口；Phase 5-7 后通过 `admin_or_legacy_save_turn` validation/commit service 和 projection service 执行，不伪装成普通玩家 commit。
- `content_delta.apply_content_delta()`：维护类内容 delta 写入实体、事件、meta，并标记投影。
- `content_sync.sync_campaign_content()`：从 campaign content 同步注册内容到当前数据库，也通过 `UnitOfWork` 写入 turn/event/meta 并标记投影。
- `save_patch.apply_save_patch()`：直接维护实体字段，属于 maintenance 入口；Phase 7 后通过 `ProjectionService` 刷新 search/snapshots/cards 并返回 projection report。
- `simulation.run_long_simulation()`：在临时复制的 campaign 上调用 `save_turn_delta()` 做长跑压力测试；它不是正式存档入口，但说明保存核心被多个上层流程复用。
- 多个 CLI 子命令过去会直接调用 `write_current_snapshot()`、`write_cards()`、`mark_projections_clean()`；Phase 7 后这些 artifact 命令保留为 legacy/admin/maintenance surface，但刷新语义由 `ProjectionService` 解释。

这些路径有合理用途；当前已共享 validation/commit/projection 的主要能力，但 maintenance/import 批量报告、stale version repair 和最终 `TurnCoordinator` 仍需继续硬化。

### 2.4 回复验收链路

```text
AI 回复文本
  -> lint_response()
  -> draft_delta_from_response()
  -> check_delta_response_consistency()
  -> state_audit
  -> decide_save()
  -> save_turn_delta()
  -> write snapshot/card
```

`response_acceptance.py` 当前会阻止有真实状态变化的反推草案直接保存，因为它只生成 `response_delta_draft` 事件，而不是权威玩法 delta。这个保护是对的。Phase 4 已把这类草案纳入 `TurnProposal(delta_source=response_draft)`；Phase 5/6 已把它接入 `ValidationPipeline(profile=response_acceptance)` 和 `commit_turn_proposal()`，未人工确认的 response draft 不再通过 `--save-if-safe` 自动保存。

## 3. 决策点地图：问题、目标和当前同步状态

| 阶段 | 优化前/现存决策点 | 风险 | 目标职责 | 当前同步状态 |
|---|---|---|---|---|
| 意图识别 | `classify_request()`、`apply_semantic_request_decision()`、旧 runtime `infer_player_action()` 副本、外部 AI 手动选 action | 同一输入在不同入口得到不同 `mode/submode/action` | 单一 `IntentRouter` 负责最终意图 | 已落地主路径：`start_turn()`、`act()`、`preview_from_text()` 共享 `route_intent()`；旧 runtime 副本已删除 |
| 上下文装载 | `build_context()`、实体命中、collector、预算策略 | 上下文预算和模板依赖本地分类结果，可能和后续 action 不一致 | 收集实体、语义和预算 hints；不拥有最终意图裁决 | 已落地主路径：context request 输出 `intent`、`turn_contract`、`decision_trace` |
| 场景建议 | `render_scene()` 的 `scene_affordances()` | 生成“可行动”建议，但不产生可校验 intent | 只作为 UI 候选，不作为执行决策 | 保持原定位，尚未改为可执行 plan |
| 行动预演 | `preview_action()`、Action Resolver、`preview.py` delta builder | 低层 API 会忠实执行错误 action；预演和 delta 草案构造散在 resolver 与 `preview.py` | Resolver 只负责领域合同和预演，delta builder 作为实现层被显式纳入合同 | 部分落地：新增 `preview_from_text()`；`preview_action(source_user_text=...)` 有 mismatch guard |
| delta 来源 | resolver `proposed_delta`、`preview.py`/resolver builder、外部 AI delta、旧 `proposal.proposed_delta`、`draft_delta_from_response()` | 多个 delta 来源权威性不同，但缺少统一承载 | 统一为 `TurnProposal`，记录来源、provenance 和确认状态 | 已落地 Phase 4：runtime preview、response acceptance、turn assistant proposal guard 和外部 proposal JSON 统一消费 `TurnProposal`；旧 `proposed_delta` proposal 字段会被拒绝 |
| 提案校验 | `validate_turn_proposal()` | 已有提案校验雏形，但和 runtime commit 没打通 | 成为 validation pipeline 的一个 stage | 已落地 Phase 5：`proposal_guard` stage 统一处理 delta_source、human confirmation 和 resolver 合同 |
| delta 校验 | `validate_delta()`、`save_turn_delta()` 内部 schema 复验、resolver `delta_contract()` | 校验分散，错误语义不统一 | 单一 `ValidationPipeline` 汇总 schema、合同、审计、回复一致性 | 已落地 Phase 5：`ValidationReport.stages` 汇总 schema、capability、resolver request/resolve/delta、response lint/consistency、state audit |
| 状态审计 | `run_state_audit()` deterministic + optional AI | 和 response acceptance、turn assistant、runtime 分别调用 | 作为 validation pipeline 的固定阶段 | 已落地 Phase 5：runtime、`save-turn`、turn assistant、response acceptance 通过 pipeline stage 调用 |
| 保存提交 | `commit_turn()`、顶层 `save-turn`、`turn_assistant.run_save_pipeline()`、`response_acceptance.accept_response()`、`content_delta`、`content_sync`、`save_patch` | backup、save、check、artifact refresh 重复；部分路径不走 action `delta_contract()` | `TurnCommitService` 负责玩家回合提交，维护写入走专门 maintenance commit | 已落地 Phase 6 主路径：runtime/player commit 走 `commit_turn_proposal()`，`save-turn`/turn assistant 走 admin/legacy profile，response acceptance 不再直接保存 |
| 投影刷新 | `UnitOfWork.mark_standard_projections()`、runtime/CLI/maintenance 旧入口、`refresh_projections()` | dirty/clean 状态和实际产物刷新分散 | `ProjectionService` 统一管理 dirty、refresh、clean、失败状态 | 已落地 Phase 7：post-transaction snapshots/cards/memory/reports/package_lock 由 `ProjectionService` 刷新并返回 `ProjectionReport`；`refresh_projections()` 保留为 legacy wrapper |
| 回复模板 | `required_template`、resolver `response_template`、`response_lint` 固定标题、外部 AI 实际输出 | 模板建议和最终 lint 之间不是同一合同 | 输出格式属于 `TurnContract`，从 intent 到 lint 贯穿 | 已落地 Phase 3：`response_lint` 必须消费 `TurnContract`，并校验 headings、required template、validation profile 和 must-save 语义 |

## 4. 主要问题和当前处置状态

### 4.1 意图路由不唯一：主路径已落地修复

优化前 `start_turn()` 与 `act()` 分别维护自然语言判断逻辑：

```text
start_turn -> classify_request
act        -> runtime.py 旧 infer_player_action 副本
```

两者都使用 action registry 的关键词和实体信息，但规则顺序、默认行为、组合行动处理并不一致。

当前状态：已新增 `IntentRouter`，并让 `start_turn()`、`act()`、`preview_from_text()` 共享 `route_intent()` 结果；`runtime.py` 中的旧自然语言推断副本已删除。后续仍需要把 `turn_assistant` 等报告入口完全切到同一 coordinator。

### 4.2 MCP 曾缺少“从文本预演”的安全入口：已新增主工具

优化前 MCP 只暴露：

```text
start_turn
query
preview_action
validate_delta
commit_turn
```

这要求外部 AI 在 `start_turn()` 之后自行决定 `preview_action` 的 `action`。如果外部 AI 选错，例如把 routine 文本传给 `craft`，内核会忠实执行错误 resolver。

当前状态：MCP 已新增 `preview_from_text`，普通 Agent 自然语言行动应优先调用该工具。`preview_action` 保留为低层确定性 API。

### 4.3 `preview_action()` 低层 API 容易被误用：已加轻量保护

`preview_action(action="craft", options={...})` 的设计是低层确定性 API。优化前它不校验 `user_text` 和 `action` 是否语义匹配，因此不适合作为外部 AI 直接面对自然语言的主入口。

当前状态：`preview_action()` 已支持 `source_user_text`。当文本和 action 明显冲突时返回 warning 或 `needs_confirmation`。它仍不承担完整自然语言路由职责，避免违反职责单一原则。

### 4.4 规则关键词不足以处理开放 RP 文本

同一个词在不同语境下可能含义不同：

- “查看”可能是查询，也可能是巡查行动。
- “找”可能是找 NPC，也可能是找材料。
- “推进”可能是项目推进、日常维护或制作。
- “下到某地找某人询问”可能是 travel + social 的组合行动。

因此，No-AI path 不能只靠零散关键词硬猜。最低标准应是“规则 + 实体索引 + action registry + resolver contract + 澄清/确认机制”的确定性基线；AI helper 只能在这个基线上提高开放文本理解能力，不能取代基线或绕过门禁。

### 4.5 模板选择和 resolver 执行没有单一合同

优化前 `start_turn()` 返回 `required_template`，但 `preview_action()` 不知道这个判断。两步之间由外部 AI 衔接，缺少机器可校验的“本轮意图合同”。

当前状态：Phase 3 已把 `TurnContract` 作为强制合同贯穿 context request、`preview_from_text()` interpretation、response lint 和 proposal validation。Phase 5/6 已把 commit profile 收敛到 `ValidationPipeline` 和 `TurnCommitService`；普通玩家 commit 不再接受无 proposal 的裸 delta。

### 4.6 delta 权威来源不唯一

当前至少有四类 delta 来源：

- Action Resolver 的 `ResolutionResult.proposed_delta`。
- `preview.py` 和各 action resolver 内部的 `build_*_delta()` 实现层。
- 外部 AI 根据上下文和预演手写的 delta。
- 旧 proposal payload 中的 `proposed_delta` 字段。
- `delta_draft.py` 从 AI 回复文本反推的低可信草案。

这些来源都能进入某些校验或保存路径，但权威性不同。优化前缺少统一字段说明：

- delta 是 resolver 生成、AI 生成、人类编辑，还是回复反推。
- 是否已经经过 action contract。
- 是否已经和最终回复一致性校验。
- 是否允许自动保存。

当前状态：Phase 4 已通过 `TurnProposal.delta_source`、`provenance`、`human_confirmed` 和 `turn_contract.allowed_delta_sources` 统一表达这些差异；Phase 5/6 已把保存策略集中到 profile 化 validation 和 proposal commit 服务中。`human_edited`、`ai_generated`、`response_draft` 仍必须按 proposal guard 的确认语义进入提交。

### 4.7 校验和审计没有统一报告面

当前校验分散在：

- `GMRuntime.validate_delta()`：schema + action resolver delta contract。
- `save_turn_delta()`：保存前再次 schema 校验。
- `run_state_audit()`：确定性审计 + 可选 AI 审计。
- `lint_response()`：检查回复结构。
- `check_delta_response_consistency()`：检查回复和 delta 的弱一致性。
- `validate_turn_proposal()`：校验 action proposal、resolver、delta。

这些检查都必要，但应该形成一个 `ValidationReport`，明确哪些是 blocker，哪些是 warning，哪些需要人工确认。

当前状态：Phase 5 已新增 `validation_pipeline.py`，集中定义 `preview_only`、`player_turn_commit`、`response_acceptance`、`maintenance_commit`、`admin_or_legacy_save_turn`、`import_or_migration` profile，并以 `ValidationStageResult`/`ValidationReport` 表达 schema、capability、resolver request/resolve/delta、proposal guard、response lint、response/delta consistency 和 state audit。
`ValidationReport` 还会记录规范化 `delta_digest`，供提交层确认“本次校验报告对应的就是本次提交 delta”。

### 4.8 保存提交逻辑重复

`GMRuntime.commit_turn()`、顶层 `save-turn`、`turn_assistant.run_save_pipeline()` 和 `response_acceptance.accept_response()` 都包含类似步骤：

```text
validate/audit
  -> create_backup()
  -> save_turn_delta()
  -> write_current_snapshot()
  -> write_current_snapshot_json()
  -> write_cards()
  -> mark_projections_clean()
  -> run_checks() 或返回结果
```

重复本身不是最大问题，真正问题是：不同路径一旦策略不一致，就会出现“某条路径保存了但没有完整投影”“某条路径审计强度不同”“某条路径标记 clean 但产物未刷新”等问题。

当前状态：Phase 6 已新增 `commit_service.py`，集中 backup、`save_turn_delta()`、post-check、可选 archivist 和 `CommitResult`。Phase 7 后，commit service 不再直接写 snapshot/cards/memory，而是在事实提交后调用 `ProjectionService`，并把 `ProjectionReport` 放入 `CommitResult`。玩家 `GMRuntime.commit_turn()` / MCP `commit_turn` / `play commit` 需要 preview 返回的 `TurnProposal`；顶层 `save-turn` 和 turn assistant save 以 `admin_or_legacy_save_turn` profile 调用统一提交服务。

### 4.9 投影所有权分散

`UnitOfWork.mark_standard_projections()` 会把标准投影标记为 dirty，并立即重建 search 后标 clean，同时通过 outbox 处理 events JSONL。Phase 7 前，runtime、CLI 和维护命令还会手动写 snapshot/cards 并 mark clean；`refresh_projections()` 也能重刷 events/search/snapshots/cards/memory/reports。

当前状态：Phase 7 已新增 `projection_service.py`。`ProjectionService.refresh()` 统一处理 snapshots、cards、memory、reports、package_lock 和 repair/rebuild 类刷新，写入 `refreshing/clean/failed` 持久状态，并返回 item 级 `ProjectionReport`。`UnitOfWork` 仍保留事务内 dirty/outbox/search 边界；旧 `refresh_projections()` 作为 legacy wrapper 调用 projection service。CLI `init`、`render-current`、`render-cards`、`memory rebuild`、`audit`、`projection repair`、content/proposal/import/save patch/campaign validation 等入口已迁移为 maintenance/admin/import projection profile，不再各自解释 projection clean/dirty。

目标不是禁止这些命令，而是让投影状态只有一个服务负责解释：

- 何时 dirty。
- 何时 refresh。
- 何时 clean。
- refresh 失败如何记录。
- 同步产物和异步产物如何区分。

### 4.10 回复验收是并行编排器

`response_acceptance.accept_response()` 的方向是有价值的：它能 lint 回复、反推 delta、生成 diff、决定是否保存。优化前它是一条和 runtime commit 并行的编排路径。

长期应把它改成：

```text
AI 回复文本
  -> ResponseAcceptanceStage
  -> TurnProposal / ValidationReport
  -> TurnCommitService
```

也就是说，回复验收只产出提案和校验报告，不直接拥有最终保存编排权。

当前状态：Phase 5/6 已完成这一迁移。`accept_response()` 产出 `TurnProposal(delta_source=response_draft)` 和 `ValidationReport(profile=response_acceptance)`；若最终允许保存，调用 `commit_turn_proposal()`，不再直接 `create_backup()` / `save_turn_delta()` / 写 snapshot/cards。

### 4.11 `turn_assistant` 是雏形但不是唯一编排层

`turn_assistant.py` 已经把 context、resolver contract、preview、proposal guard、response lint、delta validation、save pipeline 放在一个报告里。这说明代码已经自然长出了“回合编排器”的需求。

但它仍然是 CLI/报告工具性质，和 `GMRuntime`、MCP 主链路、response acceptance 没有统一为同一个服务。因此它更适合作为未来 `TurnCoordinator` 的观察窗口，而不是另一个保存入口。

### 4.12 顶层 CLI/Admin 保存路径会绕过 Runtime 合同

V1 `play commit` 会调用 `GMRuntime.commit_turn()`，这是当前玩家回合主保存路径。与此同时，顶层 CLI 仍保留若干 admin/legacy/维护命令：

- `save-turn`：直接执行 schema 校验、state audit、backup、`save_turn_delta()`、snapshot/cards 刷新，不经过 `GMRuntime.validate_delta()`，因此不会自动执行 action resolver 的 `delta_contract()`。
- `turn assistant --save`：先生成报告，再在 `run_save_pipeline()` 中执行 schema 校验、state audit 和保存；resolver contract/proposal guard 是报告项，不是统一保存门禁。
- `turn accept-response`：从回复反推 delta，低风险时可保存；当前对非空状态变化表会阻断，避免把低可信草案当作权威玩法 delta。
- `apply-content-delta`、`content_sync`、`save patch`：属于维护写入，各自有内容/patch 校验，但不应和玩家回合 commit 混为一条产品路径。

这些路径不一定是 bug；很多属于作者、维护、迁移或测试工具。但它们证明“保存提交”和“投影刷新”确实没有唯一 owner。最终架构应明确哪些是普通玩家路径，哪些是 admin/maintenance profile，并让它们共享统一的 validation/commit/projection 能力。

### 4.13 `preview.py` 是 Resolver 实现层，不是独立路由器

`preview.py` 当前承载了大量 `render_*_preview()` 与 `build_*_delta()` 逻辑，多个 action resolver 会调用它生成预演文本和 delta 草案。它不直接决定 action 类型，也不直接保存，因此不是另一个意图路由器。

但它是 delta 来源的一部分。Phase 4 已要求 ready preview 输出 `TurnProposal(delta_source=resolver_proposed)`，把 `preview.py` 或 resolver builder 生成的草案放进统一来源合同；后续还可以在 `provenance` 中继续细化具体 builder 名称。

## 5. 目标设计原则

### 5.1 核心架构原则

本优化方案必须始终坚守下列核心设计原则。它们优先于局部实现便利，也用于约束后续 `IntentRouter`、`TurnCoordinator`、`ValidationPipeline`、`TurnCommitService` 和 `ProjectionService` 的拆分边界。

- 职责单一原则：一个模块只负责一类事情，不要什么都往一个地方塞。
- 边界清晰原则：每一层、每个模块都要知道自己管什么、不管什么。
- 高内聚低耦合原则：相关逻辑放在一起，模块之间尽量少互相依赖。
- 面向变化原则：架构要方便未来扩展，而不是只满足眼前需求。
- 依赖抽象原则：业务逻辑尽量依赖接口、抽象、规则，而不是依赖具体实现。
- 数据流清晰原则：数据从哪里来、经过哪里、在哪里被修改、到哪里去，都要可追踪。
- 可测试原则：核心业务逻辑应该能被单独测试，不要强绑定数据库、网络、第三方服务。
- 故障隔离原则：一个局部模块出问题，不应该拖垮整个系统。
- 可观测原则：系统出问题时，要能通过日志、指标、链路追踪快速定位原因。
- 不过度设计原则：架构要刚好解决当前问题，并给未来留空间，不要为了“高级”而复杂。

最核心的一句话：

优秀架构的本质，是控制复杂度，让系统在变化、增长和出问题时依然可理解、可修改、可扩展、可恢复。

#### 5.1.1 设计符合性复核

按上述原则复核当前方案，结论是：方向符合 5.1，但后续实现必须把若干风险点写成硬边界，避免新服务演变成新的复杂度中心。

| 原则 | 当前设计符合点 | 必须守住的同步要求 |
|---|---|---|
| 职责单一 | Router、Coordinator、Validator、Committer、Projector 已拆成不同 owner | `TurnCoordinator` 只能编排，不写 resolver、validation、commit 或 projection 规则 |
| 边界清晰 | 第 5.3 和第 7 节已定义每阶段 owner | 每个模块必须写清“负责”和“不负责”，低层工具保留但标 profile |
| 高内聚低耦合 | 意图、上下文、预演、校验、提交、投影按链路拆分 | 共享数据必须通过 `ActionIntent`、`TurnContract`、`TurnProposal`、`ValidationReport` 等合同传递 |
| 面向变化 | 新 action resolver、validation profile、projection 类型都有扩展点 | 新玩法只扩 resolver/contract/profile，不新增第二套自然语言路由或保存路径 |
| 依赖抽象 | 目标设计依赖 resolver contract、profile、report 等抽象 | `IntentRouter` 的实体查询应逐步收敛到 `EntityLookup`/read model 抽象，避免核心规则强绑 SQLite |
| 数据流清晰 | 主链路已定义 `InboundRequest -> ... -> OutboundResponse` | 每次覆盖、确认、校验、提交、投影都必须写入 trace/report，不能只靠异常或日志表达 |
| 可测试 | 回归矩阵贯穿 Phase 0-7.1，每阶段都要求新增或更新测试 | 核心 router 和 validation stage 应可用 fake lookup/fake resolver 单测，不依赖真实 MCP 或 AI 服务 |
| 故障隔离 | commit 和 projection 分开表达，AI 只给建议不直接写库 | projection 失败不得伪装成 commit 失败或成功；AI/semantic 失败必须 fallback 到规则路径 |
| 可观测 | `decision_trace`、`ValidationReport`、`ProjectionReport` 是观测面 | MCP audit、validation stages、commit/projection state 需要统一字段，方便定位工具调用顺序问题 |
| 不过度设计 | 实施路径按 Phase 0-7.1 渐进迁移，并以持续测试矩阵约束每阶段完成条件 | 先包装旧函数、保留旧入口兼容；只有测试和 profile 覆盖后再迁移保存和投影核心 |

因此，本方案满足 5.1 的前提不是“新增更多中心化服务”，而是把复杂度按稳定边界拆开：路由只裁决意图，协调器只串流程，resolver 只管领域预演，validator 只给保存门禁，committer 只写事实，projector 只管派生产物状态。

### 5.2 确定性基线优先，AI 受控增强

开放自然语言意图识别不能依赖单一外部 AI。最低标准是 No-AI path 也能靠规则、resolver、schema、实体索引和确定性审计稳定推进；AI helper 用来增强开放文本理解、组合行动拆解、歧义提示、叙事质量和审计覆盖率。

- 确定性路径负责候选生成、硬边界、风险提示、越权拦截、低成本 fallback、实体解析、resolver 合同、delta schema 和状态审计门禁。
- 内部 AI helper 可以产出 `semantic_suggestion`、置信度、理由、候选 plan/proposal 和审计补充，但必须进入 `IntentRouter.finalize()`、`TurnProposal` 或 `ValidationPipeline`。
- 外部 AI 是低信任调用者，可以调用 workflow 工具、生成叙事和解释结果，但不能直接决定最终 action、写库、绕过 validation 或声明保存/投影状态。
- AI 失败、超时或低置信时必须退回确定性结果，并在 trace 中记录降级原因。

换句话说，AI 可以帮助系统理解“玩家可能想做什么”，但最终 intent、delta 和事实写入必须由确定性内核和可追踪合同裁决。

### 5.3 每个阶段只有一个最终决策者

建议的所有权：

| 决策 | 唯一 owner | 其他模块角色 |
|---|---|---|
| `mode/submode/action/options` | `IntentRouter` | 规则、external/internal intent candidate、实体解析 hint 都是候选输入；legacy semantic suggestion 仅作 trace |
| 上下文装载 | `ContextBuilder` | 可收集 semantic/entity hints，但必须回交 `IntentRouter` 形成最终 intent；不直接拥有最终裁决权 |
| resolver 选择 | `PreviewCoordinator` | 只使用 intent.action |
| delta 权威状态 | `TurnProposal` | 记录来源、修改、确认状态 |
| 是否可保存 | `ValidationPipeline` | 汇总 schema、resolver、审计、回复一致性 |
| 如何写入 | `TurnCommitService` | 调用 `save_turn_delta()` 和 `UnitOfWork` |
| 产物刷新 | `ProjectionService` | 管 dirty/clean/failed |
| 对玩家输出 | `ResponseRenderer` 或外部 AI | 受 `TurnContract` 和 lint 约束 |

### 5.4 决策必须可追踪

每个关键对象都应带 `decision_trace`：

```json
{
    "source": "intent_ai",
  "confidence": "high",
  "candidates": [
    {"mode": "action", "submode": "routine", "score": 0.86, "source": "ai"},
    {"mode": "query", "submode": "entity", "score": 0.42, "source": "rules"}
  ],
  "overrides": [
    "AI 语义判断仅记录，不覆盖最终路由：query:entity vs action:routine"
  ],
  "guards": [
    "explicit mode/submode not provided",
    "routine resolver exists"
  ]
}
```

这能解释为什么一轮被判断为 action，也能定位 AI 与规则冲突。

## 6. 目标全链路架构

建议收敛为一条主链：

```text
InboundRequest
  -> TurnCoordinator
  -> IntentRouter.pre_route()
       -> rule candidates
       -> cheap entity hints
       -> PreliminaryActionIntent
  -> ContextBuilder(preliminary_intent)
       -> entity hits
       -> AI semantic judgement
       -> context hints
  -> IntentRouter.finalize()
       -> ActionIntent
       -> decision_trace
  -> ContextBuilder.render(final_intent)
       -> TurnContextPacket
  -> PreviewCoordinator(intent, context)
       -> ActionPreview
  -> AI narrator / human edit
       -> TurnProposal
  -> ValidationPipeline(proposal)
       -> ValidationReport
  -> TurnCommitService(validation.approved_proposal)
       -> CommitResult
  -> ProjectionService
       -> ProjectionReport
  -> OutboundResponse
```

### 6.1 `ActionIntent`

```python
@dataclass(frozen=True)
class ActionIntent:
    user_text: str
    mode: str
    submode: str
    action: str | None
    options: dict[str, Any]
    confidence: str
    source: str
    alternatives: tuple[ActionAlternative, ...]
    missing_required: tuple[str, ...]
    needs_confirmation: tuple[str, ...]
    decision_trace: dict[str, Any]
```

含义：

- `mode/submode`: 给 `start_turn`、上下文预算和模板使用。
- `action/options`: 给 `preview_action` 或 `PreviewCoordinator` 使用。
- `confidence/source`: 告诉调用方这是显式参数、AI、规则还是 fallback。
- `alternatives`: 冲突时返回候选，例如 `routine` 与 `query:scene`。
- `missing_required`: 缺目的地、对象、目标等硬缺失项。
- `needs_confirmation`: 组合行动、高风险行动或低置信度时的确认项。

### 6.2 `TurnContract`

`TurnContract` 应贯穿上下文、预演、回复模板和 lint：

```python
@dataclass(frozen=True)
class TurnContract:
    intent: ActionIntent
    required_template: str
    response_headings: tuple[str, ...]
    requires_preview: bool
    must_save: bool
    allowed_delta_sources: tuple[str, ...]
    validation_profile: str
```

这样 `required_template` 不再只是 `start_turn()` 的建议，而是后续 lint、proposal validation 和 commit 的共同合同。

### 6.3 `TurnProposal`

`proposal.py` 已扩展为 Phase 4 的统一中间对象：

```python
@dataclass(frozen=True)
class TurnProposal:
    proposal_id: str
    intent: ActionIntent
    context_id: str | None
    preview: ActionPreview | None
    response_text: str | None
    delta: dict[str, Any] | None
    delta_source: str
    provenance: dict[str, Any]
    human_confirmed: bool
    facts_used: tuple[str, ...]
    narrative_claims: tuple[str, ...]
    turn_contract: TurnContract
```

`delta_source` 建议枚举：

- `resolver_proposed`
- `ai_generated`
- `human_edited`
- `response_draft`
- `maintenance_delta`

当前 proposal guard 已按 `delta_source`、`turn_contract.allowed_delta_sources` 和 `human_confirmed` 区分 resolver、AI、human edit 和 response draft；最终保存策略仍应在 Phase 5 的 `ValidationReport` 和 Phase 6 的提交服务中集中决定，而不是由各入口自行判断。

### 6.4 `ValidationReport`

```python
@dataclass(frozen=True)
class ValidationReport:
    profile: str
    stages: tuple[ValidationStageResult, ...]
    proposal_id: str | None = None
    delta_source: str | None = None
    delta_digest: str | None = None
```

必须汇总：

- delta schema。
- action resolver request/delta contract。
- state audit。
- response lint。
- response/delta consistency。
- proposal guard。
- capability checks。
- write guard readiness。
- CLI/admin profile 差异，例如 `save-turn`、`turn assistant --save`、maintenance delta 是否允许跳过玩家 action contract。

### 6.5 `CommitResult` 和 `ProjectionReport`

保存和投影应分开表达：

```python
@dataclass(frozen=True)
class CommitResult:
    turn_id: str
    backup_id: str | None
    write_status: str
    projection_report: ProjectionReport
    audit: dict[str, Any] | None

@dataclass(frozen=True)
class ProjectionReport:
    dirty: tuple[str, ...]
    refreshed: tuple[str, ...]
    clean: tuple[str, ...]
    failed: tuple[str, ...]
    artifacts: tuple[str, ...]
```

这样保存成功但某个投影失败时，可以明确返回 partial projection failure，而不是混在 commit 成功或异常里。

## 7. 推荐模块边界

### 7.1 `intent_router.py`

新增统一入口：

```python
def route_intent(
    campaign: Campaign,
    conn: sqlite3.Connection,
    user_text: str,
    *,
    mode: str = "auto",
    submode: str | None = None,
    semantic_suggestion: dict[str, Any] | None = None,
    semantic_ai: str = "off",
    semantic_provider: str = DEFAULT_AI_PROVIDER,
    semantic_model: str = DEFAULT_AI_MODEL,
    semantic_timeout: int = DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
) -> ActionIntent:
    ...
```

迁移内容：

- `classify_request()` 中的规则判断。
- `runtime.py` 旧 `infer_player_action()` 副本中的自然语言行动判断，合并到 `IntentRouter`。
- `apply_semantic_request_decision()` 中旧 AI 覆盖策略；当前只保留只读兼容包装并记录 trace。

不保留 `runtime.py` 旧副本；自然语言主入口统一通过 `route_intent()`，低层 `preview_action()` 只保留 resolver 预演职责。

目标接口允许两种调用形态：

- `pre_route_intent(...)`：只使用显式 mode/submode、规则、低成本实体 hint 和 action inference，产出 preliminary intent，供 context builder 决定预算、召回和 AI prompt。
- `finalize_intent(..., external_intent_candidate=..., internal_intent_candidate=..., entity_hints=...)`：把外部/内部 AI 候选、实体解析和规则候选统一交给 `IntentRouter` 做最终裁决，写入 `decision_trace`。

在过渡期可以继续保留单函数 `route_intent()`，但语义上必须满足同一要求：**ContextBuilder 可以收集 semantic/entity hints，但最终 `mode/submode/action/options` 只能由 IntentRouter 产出**。

边界要求：

- 负责：裁决 `mode/submode/action/options`，产出 `ActionIntent` 和 `decision_trace`。
- 不负责：装载长上下文、执行 resolver、生成 delta、校验保存、写库或刷新投影。
- 依赖边界：规则判断应依赖 action registry、semantic suggestion 和实体解析 hint；实体查询应逐步抽成 `EntityLookup`/read model，避免自然语言规则直接绑定 SQLite 细节。
- 可测试要求：核心分支必须能用 fake entity lookup、fake semantic suggestion 和 fake registry 单测；真实数据库测试只覆盖集成行为。

### 7.2 `turn_coordinator.py`

负责主流程编排，不直接写领域规则：

```python
class TurnCoordinator:
    def start_turn(...)
    def preview_from_text(...)
    def validate_proposal(...)
    def commit_proposal(...)
```

`GMRuntime` 和 MCP adapter 调用它，CLI 和 `turn_assistant` 也调用它。

边界要求：

- 负责：按固定顺序串联 router、context、preview、proposal、validation、commit、projection，并汇总阶段报告。
- 不负责：自己判断 action、自己校验 delta schema、自己写 SQLite、自己刷新 snapshot/cards、自己生成领域规则。
- 依赖边界：依赖 `IntentRouter`、`ContextBuilder`、`PreviewCoordinator`、`ValidationPipeline`、`TurnCommitService`、`ProjectionService` 的接口，不直接依赖底层表结构。
- 故障隔离：某阶段失败时返回阶段化 report 和 recommended next step，不吞异常后继续假装成功。
- 不过度设计：先做薄编排层包装现有 runtime 方法，只有当多个入口稳定复用后再迁移更多逻辑。

### 7.3 `validation_pipeline.py`

统一下列检查：

- `validate_delta_schema()`
- resolver `request_contract()`
- resolver `resolve_contract()`
- resolver `delta_contract()`
- `validate_turn_proposal()`
- `lint_response()`
- `check_delta_response_consistency()`
- `run_state_audit()`
- 顶层 `save-turn` 和 `turn_assistant --save` 当前各自执行的 schema/audit/check 逻辑

不同入口可以选择 profile：

- `preview_only`
- `player_turn_commit`
- `response_acceptance`
- `maintenance_commit`
- `admin_or_legacy_save_turn`
- `import_or_migration`

但 profile 选择必须在 pipeline 内集中定义。

建议 profile/stage 矩阵：

| Profile | 适用入口 | 必跑 stage | 可跳过/降级 stage | 自动保存策略 |
|---|---|---|---|---|
| `preview_only` | query、preview、plan dry-run | resolver request/resolve contract、capability check、basic safety guard | delta schema、state audit、commit readiness | 不允许保存 |
| `player_turn_commit` | 普通玩家回合 | delta schema、resolver delta contract、capability check、state audit、write guard、proposal source check | response lint 可在无回复文本时跳过 | 仅 approved `TurnProposal` 可保存；裸 delta 不能伪装成玩家提交 |
| `response_acceptance` | AI 回复验收 | response lint、response/delta consistency、draft provenance、proposal guard、state audit | resolver delta contract 只有在能确定 action 时执行 | 默认不保存真实状态变化；`response_draft` 必须人工确认后才可进入 commit service |
| `maintenance_commit` | content delta、save patch、author repair | maintenance schema/content validation、reference check、state audit 或 maintenance audit、write guard | 玩家 action resolver contract | 可保存，但必须标记 maintenance provenance |
| `admin_or_legacy_save_turn` | 顶层 `save-turn`、兼容脚本 | delta schema、state audit、write guard、explicit admin profile warning | action resolver contract 可降级为 warning，除非传入 action | 允许保存，但输出必须声明不是普通玩家路径 |
| `import_or_migration` | package import、campaign sync、migration | package/schema validation、migration checksum、reference check、backup/write guard | 玩家 action/response lint | 允许批量写入；必须生成 migration/import report |

stage 结果统一落入 `ValidationReport.stages`，每个 stage 至少包含：

- `name`
- `profile`
- `status`: `ok`、`warning`、`blocked`、`skipped`
- `issues`
- `skipped_reason`
- `artifacts` 或 `trace`（如有）

这样 profile 是可测试合同，而不是散落在 CLI、runtime、assistant 和 maintenance 命令里的隐式 if/else。

当前实现记录：`rpg_engine.validation_pipeline.run_validation_pipeline()` 已落地上述 profile 集中定义和 stage report。已覆盖的 stage 包括 `profile`、`write_guard`、`proposal_guard`、`delta_schema`、`capability_check`、`resolver_request_contract`、`resolver_resolve_contract`、`resolver_delta_contract`、`response_lint`、`response_delta_consistency` 和 `state_audit`。
报告会记录 `proposal_id`、`delta_source` 和 `delta_digest`；后续提交服务必须用这些字段确认 validation/proposal/delta 绑定关系。

边界要求：

- 负责：汇总 schema、resolver contract、proposal guard、response lint、response/delta consistency、state audit、capability 和 write guard readiness。
- 不负责：生成叙事、修改 delta、写库、刷新投影、选择玩家意图。
- 依赖边界：每个检查是 stage，输入 `TurnProposal`/profile，输出 `ValidationStageResult`，最终汇总为 `ValidationReport`。
- 可测试要求：每个 stage 可单测；pipeline 可用 fake resolver/fake audit 跑 profile 组合测试。
- 故障隔离：AI audit 或 response lint 失败必须作为独立 stage failure/warning 表达，不能掩盖 deterministic blocker。

### 7.4 `commit_service.py`

集中玩家回合提交：

```python
def commit_turn_proposal(
    campaign: Campaign,
    proposal: TurnProposal,
    validation: ValidationReport,
    *,
    backup: bool = True,
) -> CommitResult:
    ...
```

维护类写入可以有单独入口，但也应复用投影服务：

```python
def commit_maintenance_delta(...)
def apply_save_patch(...)
```

顶层 `save-turn` 若保留，应明确降级为 admin/legacy profile，或改为调用 `commit_turn_proposal()` 并显式传入 validation profile，避免成为隐形玩家保存路径。

当前实现记录：`rpg_engine.commit_service.commit_turn_proposal()` 是普通玩家 proposal 提交入口；`commit_turn_delta()` 保留给 admin/legacy、maintenance、migration/import 等显式 profile。`commit_turn_delta()` 会拒绝 `player_turn_commit` profile 下没有 `proposal_id` 的提交，并强制比对 `ValidationReport.delta_digest` 与实际提交 delta，因此裸 delta 或复用其他 delta 的 validation report 都不能伪装成普通玩家回合。

边界要求：

- 负责：在 `ValidationReport.ok` 且 profile 允许时执行 backup、`save_turn_delta()`、事务后检查和 commit result 汇总。
- 不负责：重新解释玩家意图、补写 delta、决定 validation profile、直接刷新所有投影细节。
- 依赖边界：只接受已批准 proposal 和 validation，不接受任意 AI 回复文本作为权威输入。
- 故障隔离：事实写入成功但投影失败时，返回 partial projection state；不得让玩家以为派生产物已经全部刷新。

### 7.5 `projection_service.py`

把 `UnitOfWork.mark_standard_projections()`、`refresh_projections()`、runtime 手动写 snapshot/cards 的职责收敛：

```python
def mark_after_commit(...)
def refresh_required(...)
def refresh_now(...)
def render_status(...)
```

`UnitOfWork` 继续负责事务内 dirty/outbox/search 这类强一致动作；snapshot/cards/memory/reports 等可由 projection service 在 commit 后统一处理。

需要一起收敛的调用点包括 runtime commit、`turn_assistant`、`response_acceptance`、顶层 `save-turn`、`content_delta`、`content_sync`、`save_patch`、save init、campaign validation/test 和 CLI artifact repair 命令。它们不一定使用同一个 commit profile，但不应各自解释 projection clean/dirty。

边界要求：

- 负责：统一解释 dirty、refresh、clean、failed、artifact path 和可恢复状态。
- 不负责：写 turns/events/entities/clocks 当前事实，不决定 delta 是否允许保存。
- 依赖边界：事务内强一致 dirty/outbox/search 仍归 `UnitOfWork`；事务后 snapshot/cards/memory/reports 刷新由 projection service 统一报告。
- 可观测要求：每个 projection item 必须有状态、失败原因和 artifact 路径；Agent 最终回复只能陈述已完成的 projection state。

投影状态必须可持久化，不能只存在于一次函数返回值里。建议 `ProjectionService` 维护下列语义：

| 状态 | 含义 | 后续处理 |
|---|---|---|
| `dirty` | 事实库已变化，派生产物需要刷新 | `refresh_required()` 必须返回该项 |
| `refreshing` | 当前进程正在刷新 | 崩溃恢复时可回退为 `dirty` |
| `clean` | 派生产物已与当前 projection version 对齐 | 普通查询可安全展示 |
| `failed` | 上次刷新失败，事实提交本身可能已经成功 | 保留错误原因和 artifact path；允许 repair/retry |
| `stale` | artifact 存在但版本落后 | 展示时必须提示，不得宣称已完成 |

事实提交和投影刷新语义必须分开：

- `TurnCommitService` 成功写入事实后，即使 snapshot/cards 刷新失败，也应返回 `write_status=committed` 与 `projection_report.failed`。
- projection failure 不应回滚已经提交的 turns/events/entities，除非失败发生在事务内强一致投影（如必须同步的 search/outbox）并明确被定义为 commit blocker。
- `refresh_projections()`、artifact repair 命令和下一次 commit 都应能读取持久化 dirty/failed 状态并重试。
- Agent 或 UI 只能把 `clean/refreshed` 的 artifact 描述为已完成；对 `dirty/failed/stale` 只能描述为待刷新或修复中。

实现状态：Phase 7 已新增 `ProjectionItemReport`、`ProjectionReport` 和 `ProjectionService`。每个刷新项会先持久化为 `refreshing`，成功后标 `clean`，失败后标 `failed` 并记录 `last_error`；报告包含 `requested`、`refreshed`、`dirty`、`failed`、`skipped`、artifact paths 和 item metadata。Phase 7.1 后，报告进一步区分 requested/global scope，新增 `started_at/finished_at/duration_ms` 和 item `duration_ms`，`ok/status` 默认按 requested scope 解释，`global_status/global_failed/global_dirty/global_stale` 用于诊断。`ProjectionService.refresh()` 增加 `service_managed` 与 `caller_committed_required` commit policy；新式 commit/maintenance 入口在 projection 前显式完成事实提交。`stale` 版本检测已落地：`projection_state.version < PROJECTION_VERSIONS[name]` 会被展示和修复为 stale/refreshable。

## 8. MCP 和 CLI 入口调整

### 8.1 新增 `preview_from_text`，并收敛到 `plan_turn`

MCP 应新增安全主入口：

```text
preview_from_text(user_text, save=None, mode="auto", submode=None, semantic_ai=None)
```

当前过渡链路：

```text
start_turn
  -> preview_from_text
  -> validate_delta
  -> commit_turn
```

这条链路的目标是立刻降低 Agent 手动猜 `preview_action(action, options)` 的风险。它仍以 `delta` 为提交对象，因此只属于过渡主路径。

目标链路应收敛为 `plan_turn`：

```text
plan_turn(user_text)
  -> IntentRouter.pre_route()
  -> ContextBuilder 收集 entity/semantic/context hints
  -> IntentRouter.finalize()
  -> build_context(final_intent)
  -> if action ready: preview_action(final_intent.action, final_intent.options)
  -> if composite: return plan + repair_options
  -> if unclear: return clarify
  -> return TurnContract + context_id + preview/candidate_delta + recommended_next_tool
```

目标提交链路：

```text
plan_turn -> validate_proposal -> commit_proposal
```

而不是直接猜：

```text
start_turn -> preview_action(action=AI guessed value)
```

因此，文档中出现的 `validate_proposal` 和 `commit_proposal` 是目标工具；在它们落地前，MCP/Agent prompt 应使用当前过渡链路 `preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)`。

### 8.2 `preview_action()` 保持低层 API

保留 `preview_action()`，但增加误用保护：

```python
source_user_text: str | None = None
expected_intent_id: str | None = None
```

当调用方提供 `source_user_text` 时，低成本检查文本和 action 是否明显冲突：

- “巡视、盘点、查看状态”传入 `craft`，返回 warning 或 `needs_confirmation`。
- “制作、装配、修理”传入 `routine`，返回候选 `craft`。
- “下到 X 找 Y 问 Z”传入单一 `social`，提示可能需要先 travel。

这不是让 `preview_action()` 成为路由器，而是防止低层 API 被外部 AI 误用。

### 8.3 `act()` 复用统一路由器

```text
act()
  -> route_intent()
  -> if intent.action: preview_action(intent.action, intent.options)
  -> else return clarify/composite plan
```

这样 CLI 与 MCP 的分类结果一致。

### 8.4 `turn_assistant` 改为观察窗口

`turn_assistant` 应复用 `TurnCoordinator` 的中间产物生成报告，而不是维护自己的 save pipeline。

```text
TurnCoordinator.run(...)
  -> report context / contract / preview / validation / commit result
```

### 8.5 `response_acceptance` 改为 validation stage

`response_acceptance` 不应直接保存。它应产出：

- response lint stage。
- response-derived draft delta stage。
- response/delta consistency stage。
- suggested `TurnProposal`。

最终保存仍交给 `TurnCommitService`。

### 8.6 对外 MCP、AI 客户端 skill/prompt 与包管理边界

全链路优化不能只覆盖回合工具，还必须覆盖外部 AI 实际能看到的 surface。当前对外能力分三类：MCP 工具、AI 客户端 prompt/skill、剧情包和存档包管理能力。

当前 V1 MCP 对外工具集包括：

```text
workspace_inspect
campaign_list
save_list
save_current
save_create
save_switch
start_or_continue
intent_manifest
campaign_validate
save_inspect
player_turn
player_confirm
health
```

developer/trusted low-level profile 额外注册：

```text
start_turn
query
preview_from_text
preview_action
validate_delta
commit_turn
```

这些工具必须分层解释：

| 工具类别 | 工具 | 对外语义 | 设计要求 |
|---|---|---|---|
| workspace/campaign/save 选择 | `workspace_inspect`、`campaign_list`、`save_list`、`save_current`、`save_switch` | 选择和查看运行目标 | 只访问配置 root 下的 campaign/save，不接受任意绝对路径 |
| save package 创建/检查 | `save_create`、`start_or_continue`、`save_inspect` | 创建或检查 Save Package | 可以创建存档包，但不能推进剧情或写入玩法事实 |
| campaign 检查 | `campaign_validate` | 检查 Campaign Package 是否可运行 | 只读 validation，不执行 package upgrade/reconcile/migration |
| 默认玩家回合 workflow | `player_turn`、`player_confirm` | 普通玩家主路径 | 自然语言统一进入 `player_turn`；query 由内核内部执行，action 只在玩家确认后通过 `player_confirm` 保存 |
| 低层玩家回合 workflow | `start_turn`、`query`、`preview_from_text`、`validate_delta`、`commit_turn` | developer/trusted 辅助路径 | 自然语言低层预演优先 `preview_from_text`；提交必须带 preview 返回的 `TurnProposal`，并经过 validation 和确认 |
| 低层预演 | `preview_action` | 已确定 action 的 resolver executor | advanced/internal；外部 AI 只有在 action 已由合同/UI/确定 intent 给出时才能直接调用 |
| 健康检查 | `health` | 只读状态检查 | 不 repair、不迁移、不写入 |

MCP 默认不应暴露：

- admin/repair。
- migration apply。
- package upgrade/reconcile/install/diff 等维护操作。
- plugin loading。
- 任意文件读写。
- 模型调用代理。
- 长期任务调度。

外部 AI 调用层应按 prompt/skill 处理，而不是按可信代码处理。当前项目应提供通用 AI 客户端 prompt，例如 `docs/prompts/ai-client-prompt.md`；Hermes 或其他客户端可以把它包装成 skill，但该 skill 只是一组调用指引，不是权限来源。设计约束是：

- 外部 AI skill/prompt 只能推荐 workflow 工具顺序，不能授予低层/admin/maintenance 权限。
- skill/prompt 必须推荐默认 player profile 的 `player_turn -> player_confirm` 链路；developer/trusted 附录才说明 `start_turn -> preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)`。
- skill/prompt 必须声明事实以 save 为准，未 commit 的叙事不能当作已发生。
- 工具协议变化时必须同步更新 MCP tool description、AI client prompt/skill 和 transcript 测试。

现有 Campaign Package 和 Save Package 管理能力也属于本方案边界，但不属于普通玩家回合主路径：

| 能力 | 代表命令/模块 | 默认 profile | MCP 默认暴露 |
|---|---|---|---|
| Campaign Package 检查 | `campaign validate`、`campaign test`、`campaign_validate` | `preview_only` / `import_or_migration` | 只暴露只读 `campaign_validate` |
| Campaign Package 构建/升级/安装/对账/差异 | package validate/build/test/reconcile/install/diff/upgrade | `import_or_migration` / `maintenance_commit` | 不默认暴露 |
| Save Package 初始化/选择/检查 | `save init`、`save inspect`、`save_list`、`save_create`、`save_switch`、`save_inspect` | `preview_only` 或受控 create | 暴露受控选择、创建和检查工具 |
| Save Package 导入/导出 | `save import`、`save export` | `import_or_migration` | 不默认暴露给普通 AI |
| Save Package patch/repair | `save patch`、artifact repair | `maintenance_commit` / admin | 不默认暴露 |
| 内容同步和内容 delta | `content_sync`、`content_delta` | `maintenance_commit` | 不默认暴露 |

因此，本方案对包管理能力的结论是：保留现有剧情包和存档包管理能力，但必须把它们定义为只读检查、受控创建、maintenance/import/admin profile 三类；它们不得混入普通玩家回合保存链路，也不得通过外部 AI skill/prompt 变成默认可调用捷径。

## 9. 多角色评审

本节基于前文和第 14 节代码复核结论，从完整研发团队视角评审目标方案。当前问题不再只是“行动模板由谁判断”，而是整条链路存在多个隐性 owner：

- 自然语言入口曾经有 `classify_request()`、旧 runtime `infer_player_action()` 副本、外部 Agent 手动选择 action。
- 行动预演由 resolver 执行，但 `preview.py` 又承载了重要的 preview/delta builder 实现。
- 保存路径除了 `GMRuntime.commit_turn()`，还有 `save-turn`、`turn_assistant --save`、`accept-response`、maintenance delta 等入口。
- 投影刷新由 `UnitOfWork`、runtime、CLI、maintenance 命令和 `refresh_projections()` 共同参与。

多角色评审的共同前提是：玩家路径必须有唯一产品主流程，底层工具和维护入口可以存在，但必须有明确 profile、可追踪合同和统一的 validation/commit/projection 能力。No-AI path 是最低可用标准；AI helper 只能增强质量和覆盖率，不能成为普通回合推进的隐性单点依赖。

### 9.1 角色覆盖矩阵

| 角色 | 核心关注 | 本方案必须回答的问题 |
|---|---|---|
| 产品经理 | 真局可信度、阶段收益、事故面 | 玩家是否能自然推进、是否知道保存状态、阶段交付是否有可衡量收益 |
| UX/交互设计师 | 玩家心智模型、修复路径、状态可见性 | 玩家是否知道系统理解了什么、是否需要确认、是否已保存或投影失败 |
| 游戏设计师/内容作者 | 玩法规则、剧本维护、叙事节奏 | resolver、规则、候选素材、隐藏设定和维护工具是否支持长期内容生产 |
| 软件架构师 | owner 边界、接口合同、演进路径 | Router/Coordinator/Validator/Committer/Projector 是否职责单一且可替换 |
| 后端/内核工程师 | 实现可落地性、数据模型、兼容迁移 | 新服务如何包装旧函数、如何处理旧入口、如何避免巨型 coordinator |
| AI Agent 工程师 | 工具协议、Agent 误用、workflow 编排 | 外部 Agent 是否只接触正确工具，是否能按 next step 走完整链路 |
| AI/ML 与提示词工程师 | 内部 AI helper、语义质量、降级 | semantic/audit/archivist helper 如何受控调用、如何评估提升和失败降级 |
| QA/测试工程师 | 回归矩阵、故障注入、golden outputs | No-AI/AI 双路径、profile、commit、projection、MCP transcript 是否可测 |
| SRE/可靠性工程师 | 性能、恢复、可观测性、长存档 | projection failed 如何恢复，日志/trace 如何定位，性能是否有预算 |
| 安全/权限/隐私工程师 | prompt injection、工具越权、隐藏信息泄露 | 外部 AI 是否能碰低层工具、hidden 信息和 admin/maintenance 能否隔离 |
| 数据/评估工程师 | 指标、实验、质量门槛 | intent accuracy、AI lift、latency、误用率、block rate 如何采集 |
| 发布/维护工程师 | 版本升级、兼容、回滚 | migration、package upgrade、旧 CLI 和 save package 如何安全过渡 |

这组角色覆盖了常见小型产品研发组的核心职责。若团队规模较小，可以由同一个人兼任多个角色，但文档评审必须覆盖这些关注点。

### 9.2 产品经理视角

产品上真正要解决的是“真局可信度”。用户不会因为内部有很多 resolver 而满意，只会因为系统稳定理解行动、少误判、能解释、能安全保存，并在下一轮继续基于正确事实运行而满意。

产品目标：

- 玩家能用自然语言顺畅推进。
- 复杂行动能被拆解，不丢失意图。
- 错误匹配率下降，特别是 routine/query/craft/gather/travel/social 之间的误判。
- 保存行为可靠可解释，减少“以为保存了但没有保存”或“保存了错误状态”。
- snapshot、cards、events、search、memory、reports 与事实库保持一致，避免玩家看到过期世界状态。
- 作者和维护工具继续保留效率，但不能污染普通玩家路径。

产品风险：

- 过度追求完整架构会拖慢改善真局体验的速度。
- AI-assisted 如果缺少回归测试，可能从“规则误判”变成“模型漂移误判”。
- 如果只修意图，不修保存和投影，短期误判会减少，但长期仍会出现“说了、预演了、没正确写入或没正确显示”的体验问题。
- 如果 admin/maintenance profile 过早收紧，可能影响内容制作和迁移效率，需要保留作者工具但清楚分层。

产品要求：

- 第一优先级：统一 `start_turn()`、`act()` 和 `preview_from_text()` 的意图结果。
- 第二优先级：建立 30-50 条真局高频输入回归集，持续度量误判率。
- 第三优先级：把玩家保存路径收敛到 `TurnCommitService`，并为 `save-turn`、`turn_assistant --save`、`accept-response`、maintenance delta 标 profile。
- 第四优先级：统一投影服务，降低“事实已写入但可见产物过期”的风险。

### 9.3 UX/交互设计师视角

玩家的心智模型不是“选择 action resolver”，而是“我描述角色要做什么，系统理解、预演、确认并可靠推进世界”。所以 UX 不能只优化 action 命中率，还要让玩家知道当前内容处于哪个状态：只是查询、已经预演、等待确认、校验失败、已经写入存档，还是只刷新了派生产物。

UX 目标：

- 自然语言输入后的第一反馈应说明系统理解：`routine 巡视`、`query 查看状态`、`travel + social 组合行动`、`需要补充目标`。
- 明确展示推进语义：是否推进时间、是否会改变资源/位置/关系、是否需要保存。
- 把 `preview_action(action=...)` 从普通真局体验中隐藏；普通玩家和默认 Agent 面对的是 `player_turn`。
- 低置信度、组合行动、状态风险高的行动进入确认或拆分流程，不静默落到错误 resolver。
- 回复中的保存状态必须可感知，避免玩家把未提交的叙事当作已写入事实库。

UX 要求：

- `ActionIntent` 应有面向玩家的解释，例如 `player_explanation` 和 `confirmation_prompt`。
- `PreviewActionResult` / `plan_turn` 应有统一的 `next_step_label`，例如 `直接回复`、`确认后保存`、`补充信息`、`拆分行动`。
- 保存和投影要有状态标签：`not_saved`、`preview_ready`、`validated`、`committed`、`projection_pending`、`projection_failed`。
- 普通真局 UI 只呈现玩家路径，admin/maintenance profile 只在作者工具或诊断工具中出现。

### 9.4 游戏设计师/内容作者视角

游戏设计和内容作者关心的是：系统是否支持长期剧本生产，是否保留叙事节奏，是否不会让 AI 把候选素材、隐藏设定或未确认线索写成事实。

内容目标：

- Action resolver 的合同要能表达玩法成本、风险、时间推进、资源消耗和叙事约束。
- `TurnContract` 要能约束回复结构，但不能把所有游戏都压成同一种模板。
- `TurnProposal` 要能区分“已确认事实”“候选线索”“GM/作者建议”“AI 草案”。
- maintenance/import profile 要服务内容生产，不能被普通玩家路径误用。
- hidden visibility、候选 palette、random tables 和 discovery state 要继续保持边界清晰。

内容风险：

- 如果 AI 生成的新地点、新 NPC、新资源直接进入事实库，会破坏作者控制权。
- 如果 response draft 和 resolver delta 混为一类，后续剧情会基于低可信内容继续扩散。
- 如果维护工具过度收紧，作者修补内容和升级包会变慢。

内容要求：

- 新内容必须走 proposal、palette 或 maintenance delta，而不是普通叙事直接落库。
- 所有 AI 生成内容必须带 provenance 和 visibility。
- 作者工具可以更强，但必须显式 profile、可预览、可回滚。

### 9.5 软件架构师视角

当前设计最大问题不是模块数量多，而是多个模块在不同阶段拥有最终判断权。架构上必须区分：

- Orchestrator：负责编排流程。
- Router：负责意图裁决。
- Resolver：负责领域规则。
- Preview/Delta Builder：负责从 resolver 结果生成预演和候选 delta。
- Validator：负责保存前门禁。
- Committer：负责持久化。
- Projector：负责派生产物。

架构目标：

- 每个阶段只有一个 owner。
- 阶段之间只通过类型化对象传递，不靠松散 dict 隐式约定。
- 所有 AI 输出都必须进入结构化对象和校验管线。
- 保存和投影分离，避免“写库成功但产物状态不一致”。
- 玩家提交和 maintenance/admin 写入都走显式 profile，不允许隐藏的第二条玩家保存路径。

架构要求：

- `IntentRouter` 是最终意图 owner；ContextBuilder 可以收集 hints，但必须回交 `IntentRouter.finalize()`。
- `TurnCoordinator` 只能编排，不直接写 resolver、validation、commit 或 projection 规则。
- `ValidationPipeline` 以 stage/profile 组合表达，不做隐式大 if/else。
- `ProjectionService` 管理 dirty/clean/failed/stale 的持久化语义。
- 所有低层工具保留，但必须明确 advanced/internal/admin 边界。

### 9.6 后端/内核工程师视角

后端/内核工程师关心的是方案是否能在现有代码上渐进落地，而不是产生一次高风险重写。

实现目标：

- 新服务先包装旧函数，再逐步迁移调用方。
- `GMRuntime`、MCP adapter、CLI、turn assistant 和 response acceptance 逐步改为复用同一 coordinator/pipeline/service。
- 现有 save package、campaign package 和 CLI 行为保持兼容，除非明确标 legacy/admin。
- 数据结构变化优先通过 dataclass/schema 和 report 扩展，不急于改存档格式。

实现风险：

- `TurnCoordinator` 过早变成巨型服务。
- `ValidationPipeline` stage 之间共享太多隐式上下文。
- `ProjectionService` 和 `UnitOfWork` 边界不清，导致事务失败语义混乱。
- 旧 CLI 入口未迁移但文档已假设统一路径，形成新的隐形风险。

实现要求：

- 每个新服务先有 thin wrapper 版本和回归测试。
- 每个入口迁移时记录 old path/new path/profile。
- `CommitResult` 与 `ProjectionReport` 分开返回，避免投影失败伪装成 commit 失败或成功。
- 所有 report 对象必须 JSON 可序列化，供 MCP、CLI 和测试复用。

### 9.7 AI Agent 工程师视角

AI Agent 游戏开发的核心问题是工具协议设计。Agent 擅长理解语义和生成叙事，但不应该被迫在多个低层工具之间猜测系统内部 action，也不应该直接拼装 delta、选择保存入口或声明投影状态。工具应该把正确路径编码进协议。

Agent 目标：

- Agent 接收玩家文本后，有一个主工具返回意图、上下文、预演、下一步建议。
- Agent 可以基于 `TurnContract` 生成叙事，但不能绕过 `ValidationPipeline` 保存。
- Agent 对组合行动应得到结构化 plan，而不是把多步行动强行塞进单个 resolver。
- Agent 需要明确知道当前处于 `context_ready`、`preview_ready`、`proposal_needs_delta`、`validation_failed`、`commit_done` 哪个阶段。
- Agent 不需要理解 `save-turn`、`content_sync`、`save_patch` 等维护入口，除非处于作者/维护工具上下文。

工具要求：

- 过渡期 `preview_from_text` 返回 `recommended_next_tool`，例如 `query`、`ask_clarification`、`validate_delta`。
- 目标 `plan_turn` 返回 `validate_proposal`、`commit_proposal` 等 proposal 工具建议。
- `preview_action` 标为 advanced/internal，并要求 `source_user_text` 或 `expected_intent_id`。
- `commit_turn` 长期应接受 `proposal_id` 或 approved proposal，减少 Agent 手动拼装 action/action_options/delta 的机会。
- 对 Agent 路径建立 transcript 测试，验证工具调用顺序，而不只验证单个函数输出。

### 9.8 AI/ML 与提示词工程师视角

AI/ML 与提示词工程师关心的是内部 AI helper 如何受控接入、如何证明提升、失败时如何退回 deterministic path。

AI 分层模型：

| 层级 | 代表 | 信任级别 | 可以做什么 | 不可以做什么 |
|---|---|---:|---|---|
| 外部 AI 客户端 | 通用聊天模型、Agent、MCP client | 低 | 调用 workflow 工具、生成叙事、解释结果、提出 proposal/delta 草案 | 直接决定最终 action、直接写库、绕过 validation、声明未发生的保存/投影状态 |
| 内部 AI helper | semantic suggestion、state audit AI、archivist、authoring helper | 中低 | 产出语义建议、审计补充、摘要、内容候选、作者维护建议 | 单独决定事实、覆盖 deterministic blocker、绕过 profile、直接提交 |
| 确定性内核 | IntentRouter、resolver、schema、deterministic audit、commit/projection | 高 | 最终裁决 intent、校验 delta、提交事实、维护投影状态 | 生成自由叙事、替玩家做无依据推断 |

AI 治理要求：

- 所有 AI 调用必须有 `ai_role`：`external_agent`、`semantic_helper`、`audit_helper`、`archivist_helper`、`authoring_helper`。
- 所有 AI 输出必须有 `provenance`：provider、model、prompt/schema、timeout、confidence、raw status、parsed result。
- 所有 AI 输出必须进入类型化对象：`ActionIntent`、`TurnProposal`、`ValidationStageResult`、`ArchivistSuggestion` 等。
- 内部 AI helper 失败必须降级为 deterministic fallback，除非当前 profile 明确要求 AI review。
- AI helper 的效果必须通过指标证明，不应因为“更智能”而自动扩大权限。

AI 质量指标：

- No-AI intent accuracy。
- AI-assisted intent lift。
- fallback rate。
- AI timeout/error rate。
- validation block rate for AI-generated proposals。
- response/delta consistency improvement。

### 9.9 QA/测试工程师视角

QA 关心的是：这套架构是否能被验证，特别是 AI、profile、projection failure 这类非确定性或跨阶段问题。

测试目标：

- No-AI path 和 AI-assisted path 都有回归测试。
- 高频自然语言输入覆盖 query/action/routine/craft/gather/travel/social/composite。
- MCP transcript 验证工具调用顺序。
- ValidationProfile 组合测试覆盖 preview/player/response/maintenance/admin/import。
- Projection failure、partial refresh、artifact missing、stale artifact 有故障注入测试。
- 旧 CLI/admin 工具迁移后仍有兼容测试。

测试要求：

- 每个 stage 可以单测，pipeline 可以用 fake resolver/fake audit/fake projection 跑组合测试。
- 对 semantic AI 使用 fixture/fake provider，不依赖真实网络模型跑 CI。
- 对关键文本输出保留 golden 或 fingerprint，防止上下文质量悄悄退化。
- 每次新增 action resolver 必须补 request contract、delta contract、preview、commit 回归。

### 9.10 SRE/可靠性工程师视角

SRE 关心的是性能、恢复、可观测性和长存档规模。一个本地优先的 RPG 引擎也需要明确运行预算和故障状态。

可靠性目标：

- No-AI path 在常规存档规模下保持快速响应。
- AI helper 有超时、重试、降级和明确错误状态。
- commit 成功和 projection 成功分开记录。
- projection dirty/failed/stale 状态可持久化、可重试、可诊断。
- crash recovery 不会把未完成 projection 标成 clean。

可靠性要求：

- 每个 turn 有 trace id / context id / proposal id / commit id。
- 每个 AI call 有 provider/model/timeout/status。
- 每个 validation stage 有 status 和耗时。
- 每个 projection item 有 dirty version、last_refresh_version、last_error、artifact path。
- 性能报告至少包含 context build、preview、validate、commit、projection refresh 的平均值、p95 和最大值。

### 9.11 安全/权限/隐私工程师视角

安全视角的核心是：外部 AI 和玩家文本都不能越权，hidden 信息不能泄露，admin/maintenance 工具不能被普通 Agent 当捷径。

安全风险：

- Prompt injection 要求跳过 preview/validate/commit gate。
- 外部 AI 调用低层 `preview_action`、`commit_turn` 或 maintenance 工具绕过主流程。
- hidden entity、GM note、未公开线索进入普通玩家上下文。
- AI 生成 delta 修改 visibility、资源、关系或世界状态。
- audit log 记录了敏感 hidden 内容并暴露给普通视角。

安全要求：

- MCP 工具按 namespace/profile 暴露：workflow 默认可见，low-level/admin/maintenance 需要显式上下文。
- `preview_action`、`commit_turn`、`save-turn`、`save_patch`、`content_sync` 等低层工具必须标 advanced/internal/admin。
- 所有写入工具必须检查 profile、capability 和 write guard。
- hidden visibility 在 context、response lint、projection/card render 中都要有测试。
- AI 输出不得直接修改 visibility 或 bypass risk/cost，相关 delta 必须被 validation blocker 拦截。

### 9.12 数据/评估工程师视角

数据/评估视角负责把“更好用、更准确、更快”变成可观察指标。没有指标，AI 和架构改造容易变成主观判断。

指标建议：

- intent accuracy：按 gold set 统计 mode/submode/action 准确率。
- composite detection rate：复合行动是否正确拆步。
- clarify rate：需要补充信息的比例，区分合理澄清和过度打断。
- AI-assisted lift：启用 semantic helper 相比 No-AI 的提升。
- latency：context、intent、preview、validate、commit、projection 各阶段耗时。
- token budget：上下文估算 token、超预算裁剪、关键 section 保留率。
- validation block rate：不同 profile 下 blocker/warning 分布。
- tool misuse rate：外部 Agent 调错低层工具的比例。
- projection failure rate：dirty/failed/stale 出现和修复耗时。

评估要求：

- 保留固定 gold set，覆盖中文自然语言和具体游戏内容。
- AI 评估必须固定 provider/model/prompt/schema，记录时间和版本。
- No-AI baseline 永远保留，AI 只能和 baseline 对比提升。
- 每次架构阶段完成都更新指标报告，而不是只跑单元测试。

### 9.13 发布/维护工程师视角

发布/维护关注版本升级、兼容、回滚和作者存档安全。全链路优化不能让已有 campaign/save 变成不可用。

发布目标：

- 旧 CLI 和 MCP 工具在迁移期保留兼容包装。
- 新 profile、proposal、projection 状态字段有迁移策略。
- package import、save export/import、backup、rollback 都能解释新增状态。
- 文档明确当前工具链和目标工具链，避免用户调用未实现工具。

发布要求：

- 每个阶段有 migration note 和 rollback note。
- 顶层 `save-turn` 等 legacy/admin 命令改语义前要先加 warning/profile 输出。
- `ProjectionService` 引入持久状态时要提供 repair/rebuild 命令。
- release checklist 必须包括：schema migration、fixture upgrade、docs/prompt update、MCP tool description update、gold set metrics update。

### 9.14 多视角共同结论

不同角色关注点不同，但结论一致：

| 角色 | 最关心的问题 | 对架构的要求 |
|---|---|---|
| 产品经理 | 真局体验是否稳定、投入是否有阶段收益、事故面是否可控 | 先解决高频误判和安全入口，再收敛保存、投影和测试指标 |
| UX/交互设计师 | 玩家是否理解系统判断、是否少打断、是否知道保存状态 | 自然语言主入口、清晰解释、修复项、保存和投影状态透明 |
| 游戏设计师/内容作者 | 规则和内容是否可长期维护 | AI 内容候选不直接落库，作者/维护工具 profile 清晰 |
| 软件架构师 | 决策权是否唯一、边界是否稳定、写入路径是否可控 | Router/Coordinator/Validator/Committer/Projector 分层，所有入口 profile 化 |
| 后端/内核工程师 | 是否能渐进落地且兼容旧入口 | 新服务先薄包装旧函数，再按入口迁移 |
| AI Agent 工程师 | Agent 是否容易按正确流程调用工具 | 工作流工具优先、低层工具降级、proposal、validation、commit state 驱动 |
| AI/ML 与提示词工程师 | AI helper 是否受控且可证明提升 | 内部 AI 可观测、可降级，输出进入结构化合同 |
| QA/测试工程师 | 方案是否可验证 | No-AI/AI、profile、projection failure、MCP transcript 全覆盖 |
| SRE/可靠性工程师 | 性能、恢复、可观测性是否充分 | trace、耗时、dirty/failed/stale 持久化和恢复 |
| 安全/权限/隐私工程师 | 外部 AI 是否越权、hidden 是否泄露 | 工具分层、profile/capability/write guard、visibility 测试 |
| 数据/评估工程师 | 改造是否真实提升 | gold set、No-AI baseline、AI lift、latency 和误用率指标 |
| 发布/维护工程师 | 迁移是否安全、可回滚 | migration/rollback/rebuild/release checklist |

因此本文档的优化方向应坚持下列产品化架构原则：

1. 玩家和 Agent 面对的是 `plan_turn/preview_from_text`，不是一组需要猜调用顺序的底层工具。
2. No-AI path 是最低可用标准；规则、resolver、schema、deterministic audit、commit 和 projection 必须在无 AI 时稳定、快速、可测试。
3. AI helper 辅助开放文本理解、叙事、proposal 草案和审计补充；保存必须经过确定性合同和审计。
4. 外部 AI 是低信任调用者，内部 AI helper 是可观测、可降级的增强模块，所有 AI 输出都必须进入结构化合同。
5. 每轮必须留下可追踪合同：`ActionIntent -> TurnContract -> TurnProposal -> ValidationReport -> CommitResult -> ProjectionReport`。
6. 所有写入入口必须带 profile：普通玩家路径、response acceptance、admin/legacy、maintenance/import 不能混成一条隐形保存通道。
7. 投影状态是产品结果的一部分，不能只作为后台 artifact 维护细节处理。
8. 每个阶段都必须同步测试、指标、工具协议和发布/回滚说明；没有对应验证的迁移不能视为完成。

### 9.15 外部 surface 专项复审

第 8.6 补齐了对外 MCP、AI 客户端 skill/prompt、Campaign Package 和 Save Package 管理边界。多角色专项复审结论如下：

| 角色 | MCP 对外接口 | 外部 AI skill/prompt | Campaign/Save Package 管理 |
|---|---|---|---|
| 产品经理 | 默认工具必须支持顺畅真局，不把玩家暴露给底层维护命令 | prompt/skill 应引导稳定玩法流程，而不是让 AI 自由选择工具 | 创建、选择、检查存档是玩家路径；升级、迁移、修复是维护路径 |
| UX/交互设计师 | 工具返回要表达当前状态：选择、预演、校验、提交、投影 | prompt/skill 必须要求 AI 说明未保存、需确认和投影失败状态 | 包管理操作需要明确“只读检查、创建、导入、修复”的用户语义 |
| 游戏设计师/内容作者 | MCP 不应让普通玩家直接执行内容同步或 package upgrade | 作者 AI prompt 可以辅助内容生产，但不能把候选内容直接写入事实库 | Campaign Package 维护能力保留，但应通过 author/maintenance profile 使用 |
| 软件架构师 | MCP adapter 只能是薄适配层，不形成第二套业务编排 | skill/prompt 是协议说明，不是架构 owner 或权限来源 | package/save 管理走 service/profile，不绕过 validation、commit、projection 边界 |
| 后端/内核工程师 | MCP 工具应转调 runtime/service，不直接拼接底层模块 | prompt/skill 变化必须伴随工具 schema 和 transcript 测试 | import/export/upgrade/repair 需要兼容包装、迁移记录和回滚策略 |
| AI Agent 工程师 | 默认 Agent 只用 workflow 工具，低层工具标 advanced/internal/admin | skill/prompt 必须固定推荐链路，避免 `preview_action` 和 maintenance 工具误用 | Agent 可选择存档和只读检查，但不默认执行 package 迁移或 repair |
| AI/ML 与提示词工程师 | MCP 不代理模型调用，AI 输出只能进入结构化合同 | prompt/skill 必须记录版本，并和 provider/model/schema 评估绑定 | 作者 AI 可产生候选素材和维护建议，但必须带 provenance |
| QA/测试工程师 | 需要 MCP transcript 测试覆盖默认工具顺序和禁止工具误用 | prompt/skill 更新必须有 transcript 或 fixture 覆盖 | package/save validate/create/import/export/repair 的 profile 行为要有矩阵测试 |
| SRE/可靠性工程师 | MCP audit 要记录工具名、状态、耗时和错误摘要 | prompt/skill 不能隐藏 AI timeout/fallback；Agent 回复只陈述真实状态 | package migration、save import/export、repair 需要失败恢复和耗时报告 |
| 安全/权限/隐私工程师 | 默认 MCP 不暴露 admin/repair/migration/package upgrade/任意文件读写 | prompt/skill 不能授予权限，不能把 prompt injection 当命令执行 | package/save 路径必须限制在配置 root，hidden 和维护数据不得泄露给普通视角 |
| 数据/评估工程师 | 需要统计 tool misuse rate、block rate、latency | AI prompt/skill 改动要能比较 No-AI baseline 和 AI-assisted lift | package/save 管理要统计迁移成功率、回滚率、repair 成功率 |
| 发布/维护工程师 | MCP tool description 变化必须有发布说明 | prompt/skill 版本必须随工具协议一起发布和回滚 | Campaign/Save Package schema、migration、repair/rebuild 必须有 migration note 和 rollback note |

专项结论：

1. 对外 MCP 工具属于全链路优化的一部分，但默认 surface 只能包含玩家 workflow、受控存档选择/创建和只读检查。
2. 外部 AI skill/prompt 属于低信任调用指导层，必须随 MCP tool description、transcript 测试和 release note 同步维护。
3. Campaign Package 和 Save Package 管理能力属于全链路边界，但应分为只读检查、受控创建、maintenance/import/admin，而不是混入普通玩家回合主路径。
4. package upgrade/reconcile/import/export/repair 等能力必须保留，但不默认暴露给普通 AI；只有显式作者、维护或 admin 上下文才能调用。
5. 这些 surface 的设计已通过专项复审；后续实现验收必须看第 10.2、第 10.3 和第 13 节对应门槛。

## 10. 实施路径、目标和边界

本节把目标方案落成实施路径。总体策略是从低风险观测和路由统一开始，再逐步收敛 proposal、validation、commit 和 projection；外部 MCP、AI prompt/skill、Campaign Package 和 Save Package 管理任务必须并入每个阶段，而不是作为独立尾项补做。回归测试矩阵必须从 Phase 0 开始贯穿每个阶段。

| 阶段组 | 主要目标 | 不做什么 | 可验收交付物 |
|---|---|---|---|
| Phase 0 | 补充 trace、标注 profile、保留现有行为 | 不改变玩家路径语义 | 现有入口输出 decision trace；保存/维护入口有 profile 标记；建立测试矩阵基线 |
| Phase 1-2 | 统一自然语言主入口，新增 Agent 安全过渡工具 | 不让 `preview_action()` 变成自然语言路由器；不假设 proposal 工具已落地 | `start_turn()`、`act()`、`preview_from_text()` 共享 `IntentRouter` 基线结果；当前链路使用 `validate_delta/commit_turn`；高频输入路由测试通过 |
| Phase 3-4 | 建立 `TurnContract` 和 `TurnProposal` | 不直接改变存档格式 | 模板、预演、delta 来源、确认状态都进入类型化对象；proposal/delta 来源测试通过 |
| Phase 5-6 | 收敛 validation 和玩家 commit | 不把 admin/maintenance 伪装成玩家路径 | `ValidationPipeline` 和 `TurnCommitService` 成为玩家回合保存主入口；profile 和 commit transcript 测试通过 |
| Phase 7 | 统一投影状态 | 不移除必要的 artifact 维护能力 | snapshot/cards/events/search/memory/reports 的 dirty/clean/failed 由 `ProjectionService` 解释；projection failure 测试通过 |
| Phase 7.1 | 硬化投影边界 | 不扩成 `TurnCoordinator`；不引入异步任务队列；不重写 `UnitOfWork` | projection 事务边界、targeted repair、commit/projection 状态 API、stale/version repair 和指标字段有测试 |
| 持续测试矩阵 | 每个阶段同步扩展回归测试 | 不把测试推迟到架构完成后 | 真局高频输入、MCP transcript、profile、commit/projection 行为持续覆盖 |

实施边界：

- 先集中“决策权”，再集中“实现代码”。早期可以让新服务包装旧函数，避免大规模搬迁。
- player path 优先，admin/maintenance path 先打标和接入统一 report，再逐步迁移。
- `preview.py` 可以继续存在，但必须被定义为 resolver preview/delta builder 实现层，不能承担 router 或 commit 职责。
- `UnitOfWork` 继续处理事务内一致性，`ProjectionService` 负责事务后投影语义和状态报告。
- 每个阶段都必须保持旧入口可用，除非该阶段明确把旧入口标为 legacy/admin 并更新 MCP/CLI 文档。
- 每个阶段都必须同步测试和工具协议文档；没有对应测试的迁移不能视为完成。

### 10.1 详细阶段

#### Phase 0：补充追踪和文档

- 保留现有行为。
- 在 `StartTurnResult`、`PreviewActionResult`、`CommitTurnResult` 中增加更完整的 decision trace。
- 对文档中发现的并行保存、投影路径打标。
- 给顶层 `save-turn`、`turn assistant --save`、`accept-response`、`content_sync`、`save_patch` 标注 profile，区分 player path 与 admin/maintenance path。
- 建立测试矩阵基线，至少覆盖当前自然语言路由、MCP 工具顺序、玩家 commit 主路径和 maintenance/admin profile 现状。

#### Phase 1：抽出 `IntentRouter`

- 新增 `rpg_engine/intent_router.py`。
- 迁移 `classify_request()`、旧 runtime `infer_player_action()` 副本、`apply_semantic_request_decision()` 的核心判断。
- `start_turn()`、`act()`、`preview_from_text()` 共用同一 router 基线；`turn_assistant` 可先通过 `build_context()` 间接复用分类结果，完整迁入 `TurnCoordinator` 放到后续阶段。
- No-AI 路径先给出稳定裁决；legacy semantic suggestion 只能记录为 trace，不能覆盖最终 intent。
- 同步测试：`route_intent()`、`start_turn()`、`act()`、`preview_from_text()` 对同一输入必须返回一致 intent；AI intent consensus 的采纳/澄清/回退必须通过 `IntentRouter` 记录 trace。

#### Phase 2：新增 MCP 安全入口

- 新增 `preview_from_text()` 或 `plan_turn()`。
- 外部 Agent 面对自然语言时默认使用该入口。
- `preview_action()` 文档标注为低层确定性 API。
- 同步测试：MCP `preview_from_text` 工具可用；`preview_action(source_user_text=...)` 对明显冲突返回 warning 或 `needs_confirmation`。
- 目标测试：`plan_turn` 或升级后的 `preview_from_text` 在开启 semantic AI 时与 `start_turn` 使用同一 final intent，不出现 semantic 只影响 context、不影响 preview 的分裂。

#### Phase 3：引入 `TurnContract`

- 把 `required_template`、`requires_preview`、`must_save`、response headings、validation profile 收敛到一个合同对象。
- `ContextBuilder`、resolver preview、response lint 使用同一合同。
- 同步测试：context、preview、response lint 使用同一 `TurnContract.required_template` 和 profile。

#### Phase 4：升级 `TurnProposal`

- 扩展 `proposal.py` 为统一中间对象。
- 记录 delta 来源、预演来源、AI 生成来源、人类确认状态。
- resolver `proposed_delta`、AI delta、response draft 都进入同一 proposal 表达。
- 同步测试：resolver delta、AI delta、response draft 必须带 `delta_source`，且保存策略能区分来源。

#### Phase 5：统一 `ValidationPipeline`（已完成主路径）

- 汇总 schema、resolver、state audit、response lint、response/delta consistency、proposal guard。
- 返回统一 `ValidationReport`。
- 各入口只选择 profile，不手写保存决策。
- `save-turn` 和 `turn_assistant --save` 不再各自拼接 schema/audit/check，而是调用 pipeline。
- 同步测试：每个 validation stage 可单测；player、response acceptance、maintenance、admin/legacy profile 都有组合测试。

实现状态：已新增 `rpg_engine.validation_pipeline`，并让 runtime validate/commit、顶层 `save-turn`、`turn_assistant --save`、`response_acceptance` 使用统一 profile/stage 报告。新增 `tests/test_validation_pipeline.py` 覆盖 profile/stage 组合和 commit gate。

#### Phase 6：集中 `TurnCommitService`（已完成主路径）

- `GMRuntime.commit_turn()` 调用 commit service。
- 顶层 `save-turn` 删除或标为 admin/legacy，并改为调用 commit service。
- `turn_assistant.run_save_pipeline()` 删除或改为调用 commit service。
- `response_acceptance.accept_response()` 不再直接保存。
- backup、save、post-check、commit result 统一。
- 同步测试：普通玩家 commit 只能接受 approved proposal；admin/maintenance 写入不能伪装成 player turn commit。

实现状态：已新增 `rpg_engine.commit_service` 和 `rpg_engine.projection_service`。`GMRuntime.commit_turn()`、MCP `commit_turn` 和 `play commit` 需要 preview 返回的 `TurnProposal`；顶层 `save-turn` 明确为 `admin_or_legacy_save_turn` profile；`turn_assistant.run_save_pipeline()` 和 `response_acceptance.accept_response()` 已改为调用 commit service；post-commit artifacts 由 projection service 返回 `ProjectionReport`。Phase 7.1 后 `CommitResult` 增加 `write_status` 和 `projection_status`，投影失败时可以明确表达“事实已提交，但 projection partial failure/failed”。当前测试基线：`python3 -m pytest -q` 为 `174 passed, 77 skipped`；`python3 -m unittest discover tests -q` 为 `251 tests OK (77 skipped)`。

#### Phase 7：集中 `ProjectionService`

- Runtime 不直接散落调用 `write_current_snapshot()`、`write_cards()`、`mark_projections_clean()`。
- Commit 后由 projection service 统一刷新或标记。
- `refresh_projections()` 成为 projection service 的实现之一。
- maintenance/admin 命令也通过 projection service 刷新 snapshots/cards/reports/memory，不再手动 mark clean。
- 同步测试：投影成功、投影失败、部分刷新、artifact 路径缺失都必须返回明确 `ProjectionReport`。

实现状态：已落地。`ProjectionService` 是 post-transaction artifact owner；`refresh_projections()` 已迁移为 legacy wrapper；commit、runtime/MCP 输出、turn assistant、save patch、save init、campaign validation、simulation/importer 和主 CLI maintenance/admin/import 入口均返回或使用 `ProjectionReport`。新增测试覆盖 projection success、partial failure/failed state、commit 后 projection report，以及旧 `refresh_projections()` 入口迁移。

#### Phase 7.1：Projection Boundary Hardening

Phase 7.1 是 Phase 7 的修补和硬化阶段，不是新功能扩张阶段。它的核心判断来自 2026-07-01 多专家联合代码评审：如果在 `ProjectionService` 事务边界、targeted repair 语义和 commit/projection 状态 API 还不够硬时直接进入 `TurnCoordinator`，新 coordinator 会把这些模糊点包进更大的主流程。本阶段现已落地。

目标边界：

- 明确事实写入状态和投影刷新状态的 API 边界。
- 明确 `ProjectionService` 何时可以提交事务，何时必须要求调用方已经完成事实提交。
- 让 targeted repair 的成功/失败只由 requested projection 决定，同时保留 global dirty/failed 诊断。
- 把 `stale`/version repair 的最小语义落地，避免 projection version 升级后仍被展示为 clean。
- 给 projection report 增加基础耗时/诊断字段，为后续 metrics report 铺路。

非目标：

- 不实现完整 `TurnCoordinator`。
- 不新增 `plan_turn -> validate_proposal -> commit_proposal` 目标工具。
- 不重写 `UnitOfWork` 或 `save_turn_delta()`。
- 不把 maintenance/import 入口伪装成普通 player commit。
- 不引入完整异步任务队列；当前仍硬化同步 refresh/repair。

多专家修补项：

| 视角 | 问题 | 修补计划 | 验收标准 |
|---|---|---|---|
| 后端/架构 | `ProjectionService.refresh()` 内部提交事务，部分 maintenance caller 在未显式提交事实 DML 后调用它 | 增加明确 commit policy，例如 `service_managed`、`caller_committed_required`；maintenance 入口在需要“事实已提交、projection 可失败”时先显式提交事实，再调用 projection service | strict policy 下如果 caller 仍在 transaction 中则拒绝；save patch/content/proposal apply 的事实提交点在代码中可见 |
| 产品/API | `CommitResult.ok` 只看 post-check，不能表达“事实已提交但投影失败” | `CommitResult` 增加 `write_status` 和 `projection_status`；runtime/MCP/CLI 同步输出；兼容字段 `snapshot_path/cards_count` 标注为 report 派生字段 | snapshot/cards 失败时仍返回 `write_status=committed`、`projection_status=partial_failure` 或 `failed`，不让 Agent 误以为投影全成功 |
| QA/SRE | `ProjectionReport.failed` 当前可能混入无关 global failed，targeted repair exit code 容易被污染 | 区分 `requested_failed/global_failed`、`requested_dirty/global_dirty`；`ok` 和 CLI exit code 对 repair 默认只看 requested 范围 | `projection repair --name snapshots` 成功时，即使 `cards` 仍 failed，也返回 0 并报告 `global_failed=[cards]` |
| SRE/数据 | projection refresh 缺少耗时和修复诊断字段 | `ProjectionItemReport` 增加 `duration_ms`；`ProjectionReport` 增加 `started_at/finished_at` 或 `duration_ms`；metrics 文档记录 dirty age、failure rate、repair duration | 测试能断言 report 有耗时字段；performance/ops report 后续可消费这些字段 |
| 发布/维护 | `stale` 只在文档中定义，代码尚未识别 version mismatch | 先做最小 version stale：`projection_state.version < PROJECTION_VERSIONS[name]` 视为 stale/refresh_required；repair stale 等价 dirty refresh | 人工降低 projection version 后，status/repair 能识别并刷新为当前 version |

实际执行顺序：

1. 先修 `ProjectionReport` 作用域字段和 `ok/status` 语义。
2. 再修 `ProjectionService` commit policy 和 maintenance caller 的显式事实提交边界。
3. 同步 `CommitResult`、runtime、MCP audit summary、CLI 输出中的 `write_status/projection_status`。
4. 补 targeted repair、projection failure、strict transaction policy 和 stale version repair 测试。
5. 同步 README、架构文档、release/rollback/repair 说明。

落地结果：

- `python3 -m pytest -q`：`174 passed, 77 skipped`。
- `python3 -m unittest discover tests -q`：`251 tests OK (77 skipped)`。
- 新增测试覆盖 targeted repair 不受无关 failed 污染、projection failure 后 commit 仍是 `write_status=committed`、strict post-transaction policy 拒绝未提交 caller transaction、stale version 可 repair。
- 文档明确写出 Phase 7.1 是 projection hardening，不是 TurnCoordinator 阶段。

#### 持续测试矩阵：贯穿 Phase 0-7.1

测试矩阵不是最后阶段，而是每个阶段的完成条件。新增和持续维护的测试数据包括：

```yaml
- text: 巡视领地，查看各单位和角色的状态
  mode: action
  action: routine

- text: 下到地下菌丝城找夏娃，询问岩铠蕈孢子的孵化进度
  kind: composite
  steps: [travel, social]

- text: 找草药
  action: gather

- text: 做个草药包
  action: craft

- text: 查看终极复合弩属性
  mode: query
  submode: entity

- text: 去小溪看看鱼笼
  kind: composite
  steps: [travel, gather]
```

每条用例至少验证：

- `route_intent()`
- `start_turn()`
- `act()`
- `preview_from_text()`
- `TurnContract.required_template`
- `ValidationPipeline` profile 选择
- MCP/Agent transcript 的工具调用顺序
- 顶层 `save-turn`、`turn_assistant --save`、`accept-response` 的 profile 行为

目标是所有入口共享同一个路由结果。

### 10.2 专家意见转化后的计划修正

多角色评审后的计划修正不是新增一套大重构，而是给 Phase 0-7.1 增加硬门槛。任何阶段如果没有同步完成对应门槛，不能视为完成。

| 专家角色 | 评审意见 | 计划修正 | 阶段门槛 |
|---|---|---|---|
| 产品经理 | 先改善真局可信度，避免只做架构拆分 | Phase 1-2 必须建立真局高频 gold set，并持续报告误判率 | 高频输入 gold set 通过；自然语言主路径误判有可追踪 report |
| UX/交互设计师 | 玩家必须知道系统理解、保存和投影状态 | `ActionIntent`、`PreviewActionResult`、`CommitResult`、`ProjectionReport` 增加用户可解释状态 | UI/Agent 输出不允许把 preview、validated、committed、projection clean 混为一谈 |
| 游戏设计师/内容作者 | AI 内容不能直接污染事实库 | `TurnProposal.delta_source`、`provenance`、`visibility` 成为保存前门禁字段 | AI 生成地点/NPC/资源默认只能作为 proposal/palette/maintenance 候选 |
| 软件架构师 | 防止 `TurnCoordinator` 成为新复杂度中心 | Coordinator 只串阶段，不实现 router/resolver/validation/commit/projection 规则 | 新 coordinator 方法只依赖接口和 report，不直接写数据库或规则判断 |
| 后端/内核工程师 | 必须渐进迁移旧入口 | 每个入口迁移时记录 old path、new path、profile、兼容策略 | 旧 CLI/MCP 行为保持可用，除非明确标 legacy/admin 并更新文档 |
| AI Agent 工程师 | 工具协议要把正确流程编码进去 | workflow 工具默认暴露；低层工具降级为 advanced/internal/admin | 外部 Agent 自然语言 transcript 不再直接调用 `preview_action(action=...)` |
| AI/ML 与提示词工程师 | AI 必须可观测、可降级、可比较 | 每个 AI helper 记录 role、provider、model、prompt/schema、timeout、confidence、fallback | CI 使用 fake provider；真实 AI 只进入评估报告，不作为 CI 必需条件 |
| QA/测试工程师 | 方案必须可验证 | 新增 intent gold set、profile matrix、MCP transcript、projection failure 注入 | 每个 phase 合并前必须补对应测试或记录明确豁免 |
| SRE/可靠性工程师 | 需要性能预算和恢复路径 | Phase 0 先记录基线；后续阶段不得无解释劣化关键路径 | No-AI path、validation、commit、projection 有耗时报告和失败恢复测试 |
| 安全/权限/隐私工程师 | 外部 AI 和玩家文本不能越权 | 所有写入工具检查 profile、capability、write guard；hidden visibility 有测试 | 默认 MCP namespace 不暴露 maintenance/admin 写入工具 |
| 数据/评估工程师 | “更好”必须可量化 | 每个阶段输出 metrics report：accuracy、latency、AI lift、block rate、tool misuse | 没有指标报告的 AI/路由改动不能视为完成 |
| 发布/维护工程师 | 迁移必须可回滚 | 每个阶段补 migration note、rollback note、repair/rebuild 命令说明；Campaign/Save Package 管理能力必须区分只读、受控创建、maintenance/import/admin | schema 或 projection 状态变化必须有备份、回滚和修复路径；package upgrade/reconcile/import/export 不进入默认 MCP workflow |

阶段出门槛：

| 阶段 | 新增硬门槛 |
|---|---|
| Phase 0 | 生成 baseline report：当前 intent accuracy、关键路径耗时、写入入口清单、projection 状态清单、MCP 工具暴露清单、AI client prompt/skill 清单、Campaign/Save Package 管理入口清单 |
| Phase 1 | `IntentRouter` 的 No-AI gold set 通过；legacy semantic suggestion 只能记录 trace；AI consensus 覆盖/澄清/回退全部写入 trace |
| Phase 2 | MCP/Agent transcript 覆盖默认 `player_turn -> player_confirm`，并覆盖 developer/trusted `start_turn -> preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)`；自然语言路径默认不使用低层 `preview_action`；AI client prompt/skill 与 MCP tool description 同步 |
| Phase 3 | `TurnContract` 被 context、preview、response lint 共享；玩家可见状态字段完整 |
| Phase 4 | `TurnProposal` 承载全部 delta 来源；AI/human/resolver/response draft 来源可区分，保存策略可测试 |
| Phase 5 | `ValidationPipeline` profile/stage matrix 可单测；player、response、maintenance、admin profile 已有组合测试，import/migration profile 已集中定义并待后续扩展批量写入报告 |
| Phase 6 | 普通玩家写入必须经 approved `TurnProposal`；legacy/admin 写入输出 warning/profile，不能伪装成 player commit |
| Phase 7 | `ProjectionService` 持久化 dirty/refreshing/clean/failed/stale；提供 retry/repair/rebuild；failure 注入测试通过 |

量化门槛采用“先基线、再收紧”的策略：

- Phase 0 必须记录现有准确率、耗时和失败率，作为后续比较基线。
- Phase 1-2 的 No-AI gold set 不得低于当前基线；新增高频用例不得出现 silent wrong resolver，低置信或组合行动必须 clarify/confirm。
- 引入 AI helper 后，AI-assisted 指标必须相对 No-AI baseline 有可解释提升，且不得扩大写入权限。
- 无真实模型的 CI 必须稳定通过；真实 AI 评估只作为离线 metrics report。
- 关键路径性能若较 Phase 0 基线劣化超过 20%，必须有明确原因、用户收益和回滚开关。

### 10.3 外部 surface 详细开发计划

本节把第 8.6 和第 9.15 的边界落成开发任务。外部 surface 的目标不是增加更多入口，而是让 MCP、AI client prompt/skill、Campaign Package 和 Save Package 管理能力都按同一套 profile、权限、测试和发布规则工作。

#### 10.3.1 MCP surface 优化计划

| 子任务 | 具体工作 | 交付物 | 测试/验收 |
|---|---|---|---|
| 工具清单固化 | 以 `docs/specs/mcp-adapter.md` 和 `mcp_adapter.py` 为准，生成默认暴露工具清单；标注 workflow、low-level、readonly、controlled-create | MCP tool inventory report | 清单包含工具名、profile、读写属性、是否默认暴露 |
| 工具描述分层 | 更新 `preview_from_text`、`preview_action`、`validate_delta`、`commit_turn`、`save_create`、`campaign_validate`、`health` 的 tool description | 更新后的 MCP spec 和 tool description | `preview_action` 明确 low-level；`health` 明确只读；`save_create` 明确不推进剧情 |
| 默认 namespace 收紧 | 默认 MCP 只暴露 workspace/save 选择、只读检查、玩家 workflow 和受控低层预演 | MCP 配置/文档更新 | admin/repair/migration/package upgrade/plugin/任意文件读写不在默认工具列表 |
| profile/capability 检查 | 给写入工具补 `profile`、capability、write guard 检查；过渡期至少输出 profile warning | 工具返回字段或 audit 字段 | 普通 Agent 调 maintenance/admin 工具时被拒绝或需要显式上下文 |
| MCP audit 增强 | audit 记录 tool、profile、status、duration、error summary、trace id | `aigm-mcp-audit.jsonl` 字段说明 | transcript 测试能断言工具调用顺序和误用拦截 |

阶段安排：

- Phase 0：生成 MCP 工具暴露清单和当前 audit baseline。
- Phase 2：同步默认 `player_turn` 主链路、低层 `preview_from_text` primitive、tool description 和 transcript 测试。
- Phase 5-6：`validate_delta/commit_turn` 已迁入 `ValidationPipeline/TurnCommitService` 主路径；工具语义已更新为 `commit_turn(delta, turn_proposal)`。
- Phase 7：MCP 返回 `ProjectionReport` 或等价 projection state，不让 Agent 宣称未完成的 artifact 已完成。

#### 10.3.2 AI client prompt/skill 优化计划

| 子任务 | 具体工作 | 交付物 | 测试/验收 |
|---|---|---|---|
| Prompt/skill 清单 | 列出现有 `docs/prompts/ai-client-prompt.md`、作者 AI prompt、Hermes skill 包装或等价外部调用说明 | AI surface inventory | 清单记录文件、用途、面向对象、对应 MCP 工具版本 |
| 默认流程更新 | 固定推荐 `player_turn -> player_confirm`；developer/trusted 附录保留 `start_turn -> preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)` | prompt/skill 更新 | transcript fixture 不再出现普通自然语言直接 `preview_action(action=...)` |
| 权限声明 | prompt/skill 明确不是权限来源，不能授权 admin/maintenance/package 操作 | prompt/skill 安全条款 | prompt injection 用例不能让 Agent 跳过 validation 或调用维护工具 |
| 状态表达规则 | 要求 AI 输出区分 preview、validated、committed、projection pending/failed | response guidance 更新 | golden transcript 中未 commit 内容不得描述为事实 |
| 版本和评估 | prompt/skill 记录版本；AI helper/provider/model/schema 变化进入 metrics report | prompt version note、metrics report | AI-assisted lift 与 No-AI baseline 可比较，CI 使用 fake provider |

阶段安排：

- Phase 0：冻结当前 prompt/skill 清单和推荐流程 baseline。
- Phase 2：更新外部 AI 默认流程，补 transcript 测试。
- Phase 4-6：随着 proposal/validation/commit 工具落地，同步 prompt/skill 和 tool description。
- 每次工具协议变化：必须同步更新 prompt/skill、MCP spec、release note 和 rollback note。

#### 10.3.3 Campaign Package 管理优化计划

| 子任务 | 具体工作 | 交付物 | 测试/验收 |
|---|---|---|---|
| 能力分层 | 把 validate/test、build、install、diff、upgrade、reconcile、migration 明确归入 readonly、maintenance 或 import/admin profile | Campaign package capability matrix | `campaign_validate` 可默认暴露；upgrade/reconcile/migration 不默认暴露 |
| 只读检查保留 | `campaign_validate` 继续作为 MCP 默认只读工具；不执行 repair、upgrade 或 migration | MCP spec 和 campaign spec 更新 | `campaign_validate` 无写入、无 migration side effect |
| 维护操作 profile 化 | package build/install/diff/upgrade/reconcile/migration 必须输出 profile、migration id、checksum、backup/rollback 信息 | maintenance report | migration apply 必须有 backup、checksum 和 rollback note |
| 作者 AI 边界 | 作者 AI prompt 可以生成候选内容、检查建议和维护草案，但不能直接写入运行事实库 | author prompt 更新 | AI 生成新地点/NPC/资源默认进入 proposal/palette/maintenance 候选 |
| 与投影服务衔接 | package 更新影响 projection 时，由 `ProjectionService` 标记 dirty/failed/stale | projection integration note | package 维护后 artifact 状态可 repair/rebuild |

阶段安排：

- Phase 0：列出当前 package 管理入口和 profile。
- Phase 5：维护写入接入 `ValidationPipeline` 的 maintenance/import profile。
- Phase 6：维护写入接入 commit/report 统一返回，保留兼容 CLI。
- Phase 7：package 变更后的 projection 状态交给 `ProjectionService`。

#### 10.3.4 Save Package 管理优化计划

| 子任务 | 具体工作 | 交付物 | 测试/验收 |
|---|---|---|---|
| 能力分层 | 把 save list/current/create/switch/inspect、init、validate、import/export、patch/repair 分层 | Save package capability matrix | 默认 MCP 只暴露选择、创建、检查；import/export/patch/repair 不默认暴露 |
| 受控创建 | `save_create` 和 `start_or_continue` 可以创建 Save Package，但不能推进剧情或写 gameplay fact | save create contract | 创建后无 turn consequence，必须先 `start_turn/preview_from_text` |
| 导入导出 profile | `save import/export` 归入 `import_or_migration`；必须有 schema validation、checksum、backup/restore 说明 | import/export report | 导入失败可回滚，导出不泄露 hidden 到普通视角 |
| patch/repair profile | `save patch`、artifact repair 归入 maintenance/admin；必须显式上下文、write guard 和 audit | patch/repair report | 普通 Agent 默认不能调用 patch/repair |
| 与 commit/projection 收敛 | 玩家回合保存走 `TurnCommitService`；save 管理类写入复用 validation/commit/projection report | service integration note | save patch 后 projection 状态不再手动伪装 clean |

阶段安排：

- Phase 0：列出当前 save 管理入口和 MCP 暴露状态。
- Phase 2：确保 `save_create/start_or_continue` 的工具说明声明“不推进剧情”。
- Phase 7+：import/export/patch/repair 接入更完整的 profile/stage/projection report。
- Phase 7：save 管理和 artifact repair 统一使用 projection dirty/failed/stale 语义。

#### 10.3.5 横向测试、发布和回滚计划

| 测试/发布项 | 覆盖内容 | 完成定义 |
|---|---|---|
| MCP transcript tests | 默认玩家流程、查询流程、行动流程、误用 `preview_action`、误用 maintenance/admin 工具 | transcript 可断言 recommended next tool、status、profile、blocked/warning |
| Prompt/skill fixture tests | prompt 推荐流程、状态表达、prompt injection 防绕过 | 外部 AI 不把未 commit 内容当事实，不调用默认禁用工具 |
| Package profile matrix | campaign validate/build/upgrade/reconcile/migration，save create/import/export/patch/repair | 每个能力都有 profile、读写属性、默认 MCP 暴露状态、rollback 要求 |
| Security tests | root 路径限制、hidden visibility、admin 工具默认不可见、write guard | 违反边界时 blocker，而不是 warning |
| Release checklist | MCP tool description、AI prompt/skill、campaign/save spec、migration note、rollback note、metrics report | 任一 surface 变化都必须进入 release note |
| Rollback checklist | prompt/skill 版本回滚、MCP 工具配置回滚、schema/projection repair 回滚 | 回滚后默认玩家 workflow 仍可用，admin/maintenance 不被误暴露 |

优先级建议：

1. 先完成 inventory：MCP 工具、AI prompt/skill、Campaign/Save Package 管理入口、profile、默认暴露状态。
2. 再完成安全默认值：默认 MCP 不暴露 admin/repair/migration/package upgrade/import/export/patch。
3. 然后补 transcript 和 profile matrix 测试。
4. 最后随 Phase 5-7 把这些外部 surface 接入统一 validation、commit 和 projection report。

## 11. 本次落地状态

截至 2026-07-01，本轮已完成 Phase 1-6 的主路径落地。Phase 3/4 已按本文档的升级重构目标执行：`TurnContract` 不再只是提示字段，`TurnProposal` 也不再兼容旧 `proposed_delta` 提案结构。Phase 5/6 已把校验和提交收敛到 profile 化 `ValidationPipeline` 与 `TurnCommitService`；普通玩家提交不再为了兼容旧代码接受无 proposal 的裸 delta。

- 新增 `rpg_engine/intent_router.py`，提供 `ActionIntent`、`TurnContract`、`route_intent()` 和 action/text mismatch guard。
- `context_builder.classify_request()` 与 `GMRuntime.act()` 已共享 `IntentRouter` 结果。
- `StartTurnResult` 和 context request 现在包含 `intent`、`turn_contract` 和 `decision_trace`。
- 新增 `GMRuntime.preview_from_text()` 和 MCP `preview_from_text` 工具，Agent 面对自然语言玩家行动时不再需要手动猜 `preview_action(action, options)`。
- `GMRuntime.preview_action()` 保持低层确定性 API，但新增 `source_user_text` 误用保护；明显冲突时返回 `needs_confirmation`。
- AI 语义建议已退权为 trace-only；高置信度也不能覆盖最终路由，AI intent consensus 另走 external/internal candidate 仲裁链路。
- 已按 5.1 核心架构原则完成设计复核，并在第 7 节补充各核心模块的负责/不负责/依赖/测试/故障隔离边界。
- `turn_contract_for_intent()` 统一产出 `required_template`、`response_headings`、`requires_preview`、`must_save`、`allowed_delta_sources` 和 `validation_profile`。
- context request、`StartTurnResult`、`preview_from_text()` interpretation 和 ready preview 的 proposal 共用同一个 `TurnContract`。
- `response_lint.lint_response()` 必须接收 `TurnContract`，不再保留 mode/submode 或固定标题 fallback；它会校验 headings、`required_template`、`validation_profile` 和 must-save 语义。
- `proposal.py` 现在提供严格 `TurnProposal` 读写合同；未知字段会被拒绝，旧 `proposed_delta` proposal 字段不再作为兼容入口。
- runtime ready preview 会输出 `TurnProposal(delta_source=resolver_proposed)`；AI/human edit proposal 通过同一严格 JSON 合同进入 guard；`response_acceptance.accept_response()` 会输出 `TurnProposal(delta_source=response_draft)`。
- `validate_turn_proposal()` 消费 `TurnProposal` 和 `turn_contract`，校验 intent/contract 一致性、允许的 delta source、AI/human/response draft 人工确认要求、schema 和 resolver delta contract。
- `turn_assistant` 和 CLI proposal validate 已改为 strict `TurnProposal` loader；CLI response lint 已要求 `--context-json` 并从中读取 `TurnContract`。
- 新增 `validation_pipeline.py`，统一 `ValidationReport` 和 `ValidationStageResult`，集中定义 `preview_only`、`player_turn_commit`、`response_acceptance`、`maintenance_commit`、`admin_or_legacy_save_turn`、`import_or_migration` profile，并在报告中记录 `delta_digest` 以绑定 validation 与提交 delta。
- `GMRuntime.validate_delta()`、`GMRuntime.commit_turn()`、顶层 `save-turn`、`turn_assistant --save` 和 `response_acceptance.accept_response()` 已接入 validation pipeline。
- 新增 `commit_service.py`，集中 backup、`save_turn_delta()`、post-check、可选 archivist 和 `CommitResult`；projection artifact 刷新在 Phase 7 后交由 `ProjectionService`。
- `GMRuntime.commit_turn()`、MCP `commit_turn` 和 `play commit` 现在要求 preview 返回的 `TurnProposal`；`commit_turn_delta()` 会拒绝没有 proposal 的 `player_turn_commit`，也会拒绝 validation report 与实际提交 delta digest 不一致的提交。
- 顶层 `save-turn` 保留为 admin/legacy profile；`turn_assistant --save` 使用同一 admin/legacy validation/commit 服务并在报告中声明 profile。
- `response_acceptance.accept_response()` 不再直接保存；它产出 `TurnProposal(delta_source=response_draft)` 和 validation report，只有通过 guard 后才调用 `commit_turn_proposal()`。

这里的“Phase 1-6 已落地”指自然语言入口、合同层、提案层、校验层和提交层主路径已经完成，不再为了兼容旧 proposal、旧 response lint 入口或裸 delta 玩家提交妥协。当前玩家过渡主路径仍是：

```text
start_turn -> preview_from_text -> TurnProposal -> validate_delta -> commit_turn(delta, turn_proposal)
```

目标主路径仍是：

```text
plan_turn -> validate_proposal -> commit_proposal
```

后续必须把 semantic AI、实体解析 hint 和上下文召回统一纳入 `IntentRouter.finalize()`，避免 `start_turn` 与 `preview_from_text` 在开启 semantic AI 时产生不同最终 intent。

仍未在本轮硬拆的部分：

- `ProjectionService` 已集中化 post-transaction artifact 刷新；snapshot/cards/memory/reports/package_lock 的 refresh/clean/failed 状态由 `ProjectionReport` 表达。
- `content_delta`、`content_sync`、`save_patch`、import/migration 写入已接入 maintenance/import projection report；批量写入的完整 commit/profile 报告和 migration checksum 仍待硬化。
- `maintenance_delta` 已作为 `TurnProposal` 来源枚举和 maintenance 合同来源存在；maintenance/import profile 已集中定义，但批量写入报告和 migration checksum 仍待硬化。
- `turn_assistant` 仍是报告/诊断编排器雏形，尚未完全复用目标 `TurnCoordinator`。
- `preview_from_text` 仍是过渡安全入口，尚未等价于完整 `plan_turn`。

## 12. 边界和非目标

本优化不应改变以下边界：

- AI 不直接写入 SQLite。
- AI 不绕过 delta schema。
- AI 不绕过 action resolver 的 request/delta 合同。
- AI 不绕过 state audit。
- hidden 实体可见性和维护视角边界不变。
- `preview_action()` 不变成自然语言路由器，它仍是低层确定性 resolver executor。
- 维护类写入可以保留专用入口，但应复用统一 validation、commit 或 projection 能力。

## 13. 验收标准

完整优化完成后应同时满足功能验收、专家门槛和当前状态核对。验收对象不是单个函数，而是从自然语言输入到存档、投影和下一轮上下文的全链路。

### 13.1 功能验收

| 编号 | 标准 | 完成定义 |
|---:|---|---|
| 1 | 所有自然语言入口共用一个 `IntentRouter` 结果 | `start_turn()`、`act()`、`preview_from_text()`、未来 `plan_turn()` 对同一输入返回一致 final intent 和 trace |
| 2 | 外部 AI 客户端有安全 workflow 入口 | 默认工具链是 `player_turn -> player_confirm`，不要求外部 AI 手动猜 `preview_action(action)` |
| 3 | 低层 `preview_action()` 有误用保护 | 明显 action/text 冲突返回 warning、`needs_confirmation` 或候选 intent |
| 4 | 组合行动有明确 plan | travel + social、travel + gather 等不被静默塞进单个错误 resolver |
| 5 | `TurnContract` 贯穿上下文、预演和回复 lint | `required_template`、`requires_preview`、`must_save`、validation profile 来源一致 |
| 6 | delta 来源明确 | resolver、AI、human edit、response draft、maintenance delta 都有 `delta_source` 和 provenance |
| 7 | 校验集中为 `ValidationReport` | schema、resolver contract、state audit、response lint、proposal guard、capability/write guard 汇总为 stage/report |
| 8 | 玩家回合保存通过统一提交服务 | 普通玩家路径只接受 approved `TurnProposal`；不再有隐形第二条玩家保存路径 |
| 9 | 投影状态统一 | snapshot、cards、events JSONL、search、memory、reports 的 dirty/refreshing/clean/failed/stale 由 `ProjectionService` 解释 |
| 10 | 高频真局输入有回归测试 | gold set 覆盖 query/action/routine/craft/gather/travel/social/composite 和中文自然语言 |
| 11 | 写入入口全部 profile 化 | `save-turn`、`turn assistant --save`、`accept-response`、maintenance/import 都有明确 profile 和报告 |
| 12 | 职责边界清晰 | 路由、上下文、resolver、validation、commit、projection、response rendering 不互相越权 |
| 13 | 对外 MCP surface 清晰分层 | 默认暴露工具只包含 workspace/save 选择、只读检查、玩家 workflow 和受控低层预演；admin/repair/migration/package upgrade 不进入默认 MCP |
| 14 | 外部 AI prompt/skill 同步 | prompt/skill 推荐 workflow 工具顺序，不授予权限；工具协议变化时同步更新 prompt、tool description 和 transcript 测试 |
| 15 | 剧情包和存档包管理能力 profile 化 | Campaign/Save Package 的 validate/create/inspect、import/export、upgrade/reconcile、patch/repair 分别归入只读、受控创建、maintenance/import/admin |

### 13.2 专家门槛

| 维度 | 必须满足 |
|---|---|
| 产品 | 真局高频输入误判率可度量；每个阶段都有用户可感知收益或明确风险降低 |
| UX | 输出明确区分 `preview_ready`、`validated`、`committed`、`projection_pending`、`projection_failed` |
| 内容 | AI 生成内容默认不直接落库；新增事实必须经过 proposal、palette、maintenance 或人工确认路径 |
| 架构 | `TurnCoordinator` 不直接实现 router/resolver/validation/commit/projection 规则 |
| 后端 | 新服务先作为 thin wrapper 包装旧函数；每个入口迁移有 old/new/profile 记录 |
| Agent | 外部 Agent 的默认 transcript 不调用低层写入或 maintenance 工具 |
| AI/ML | 每个 AI 输出有 role、provider、model、prompt/schema、timeout、confidence、fallback 和 provenance |
| QA | No-AI、AI-assisted、profile matrix、MCP transcript、projection failure 均有测试或明确豁免 |
| SRE | 关键路径耗时有 baseline 和 p95；劣化超过 20% 必须解释并可回滚 |
| 安全 | hidden visibility、profile、capability、write guard 有 blocker 级测试 |
| 数据 | 每阶段输出 metrics report，至少包含 accuracy、latency、AI lift、block rate、tool misuse、projection failure |
| 发布 | schema、projection state、工具协议、AI client prompt/skill、Campaign/Save Package 管理入口变化都有 migration note、rollback note、repair/rebuild 路径 |

### 13.3 当前状态核对

截至 2026-07-01：

- 已满足或基本满足：1、2、3、4、5、6、10 的自然语言主路径基线部分、12 的意图/预演边界部分；其中第 2 项当前满足的是过渡工具 `preview_from_text`，不是完整 `plan_turn`/proposal 工具链。
- 第 5 项当前满足的是 Phase 3 合同贯穿：context、preview、response lint 和 proposal validation 共享 `TurnContract`，并强制检查 template/profile/headings/source。
- 第 6 项当前满足的是 Phase 4 来源承载：resolver、AI、human edit、response draft 进入统一 `TurnProposal`；`maintenance_delta` 已进入来源枚举和 maintenance 合同。
- 已满足主路径：7、8、9、11 中关于 `ValidationPipeline` profile、玩家 commit proposal gate、`save-turn`/turn assistant/response acceptance profile、`ProjectionService` 集中化，以及 Phase 7.1 projection 边界硬化的部分。尚未满足：10 中关于 semantic parity、import/migration 批量写入和发布/回滚指标的完整矩阵，以及 13、14、15 中关于 metrics、rollback/release 的完整要求。
- 新增文档门槛已补齐：专家复审、阶段出门槛、外部 surface 详细开发计划、AI 信任边界、权限/profile 要求、性能和指标要求、迁移/回滚要求。

因此本文档不能被理解为“全链路优化已经全部完成”；它记录的是完整目标架构，以及当前已经完成的自然语言入口、Agent 安全预演、Phase 3 合同层、Phase 4 提案层、Phase 5 校验层、Phase 6 提交层、Phase 7 投影层和 Phase 7.1 投影边界硬化。测试矩阵已经有自然语言主路径、合同 lint、proposal 来源、validation profile、commit gate、projection report/failure、targeted repair、strict projection transaction policy 和 stale repair 基线；下一步进入完整 `TurnCoordinator` 和目标工具协议。

## 14. 代码复核记录

本节记录 2026-07-01 对当前代码的再次核对结论。总体判断：本文档的主分析正确，尤其是意图路由、MCP 安全入口、保存编排和投影所有权分散这四个判断都有直接代码依据；Phase 7 已将投影所有权收敛到 `ProjectionService`，Phase 7.1 已硬化 projection 事务边界、repair 作用域和 commit/projection 状态 API。需要继续补强的是完整 `TurnCoordinator`、目标工具协议、metrics/report 和 import/migration 批量 profile 报告。

### 14.1 已确认正确的判断

- 此前 MCP 工具列表只有 `start_turn`、`query`、`preview_action`、`validate_delta`、`commit_turn` 等工具，没有 `act`、`preview_from_text` 或 `plan_turn`。本轮已新增 `preview_from_text`，普通 Agent 自然语言行动应优先使用该入口。
- `GMRuntime.start_turn()` 只构建 context；真正分类发生在 `build_context()` 的 pipeline 中。当前 `classify_request` 已包装 `route_intent()`，随后进入 `collect_entity_hits -> collect_semantic_suggestion -> apply_semantic_request_decision -> expand_related_entities -> run_context_collectors -> validate_context`。
- `apply_semantic_request_decision()` 当前只记录 high-confidence semantic suggestion 与最终路由的差异，不再修改 `mode/submode`、`must_save`、`requires_preview`、`required_template` 或预算策略。
- 此前 `GMRuntime.act()` 不复用 `start_turn()` 的分类结果，而是调用 `runtime.py` 旧 `infer_player_action()` 副本，再进入 `preview_action()`。本轮已改为 `act()` 调用 `preview_from_text(..., mode="action")`，与 `start_turn()` 共用 `IntentRouter`。
- `GMRuntime.preview_action()` 仍只根据传入的 `action` 找 resolver，执行 request contract、resolve contract 和 preview；但当调用方提供 `source_user_text` 时，本轮新增轻量 action/text 冲突保护。
- `GMRuntime.commit_turn()` 是玩家回合主保存路径：先通过 `ValidationPipeline(profile=player_turn_commit)` 校验 `TurnProposal` 和 delta，再调用 `commit_turn_proposal()` 执行 backup、`save_turn_delta()`、archivist 可选流程和 post-commit projection refresh。没有 proposal 的裸 delta 会被 commit service 拒绝为 player commit。
- `save_turn_delta()` 内部会再次执行 delta schema 校验，并通过 `UnitOfWork` 写 turns/events/entities/clocks/meta，标记标准投影 dirty，重建 search，并通过 outbox/events JSONL 完成事件投影。
- `response_acceptance.accept_response()` 曾是一条并行验收路径；Phase 5/6 后它会 lint response、从回复反推 delta、做一致性检查、运行 validation pipeline，并在允许保存时调用 `commit_turn_proposal()`。未确认的 `response_draft` 不再通过 `--save-if-safe` 自动保存。
- `turn_assistant.run_turn_assistant()` 已经是编排器雏形：它串联 context、action contract、preview、proposal guard、response lint、delta validation 和可选 save pipeline；Phase 5/6 后 save pipeline 已改为调用 validation pipeline 和 commit service，但还没有成为 runtime/MCP 的统一主流程。
- 投影所有权在 Phase 7 后已收敛：`UnitOfWork` 负责事务内 dirty/outbox/search，`ProjectionService` 负责事务后 snapshots/cards/memory/reports/package_lock 刷新、`refreshing/clean/failed` 持久状态和 `ProjectionReport`。`refresh_projections()` 仍保留为 legacy wrapper，但不再拥有独立解释权。

### 14.2 本次补充修正

- `preview.py` 应被纳入文档。它不是路由器，也不是保存入口，但多个 action resolver 调用其中的 `render_*_preview()` 和 `build_*_delta()`，因此它是 resolver proposed delta 的重要实现层。
- 顶层 `save-turn` CLI 是额外保存路径。Phase 5/6 后它明确降级为 `admin_or_legacy_save_turn` profile，调用 validation pipeline 和 commit service；若未提供 action，resolver delta contract 会降级为 warning，并在输出中声明 profile。
- `turn_assistant --save` 的 save pipeline 也不是 `GMRuntime.commit_turn()` 的等价物。Phase 5/6 后它同样走 `admin_or_legacy_save_turn` profile 和 commit service，作为报告/诊断入口保留。
- `content_sync.sync_campaign_content()` 是额外维护写入路径，应和 `content_delta.apply_content_delta()`、`save_patch.apply_save_patch()` 一起归入 maintenance/admin profile。
- `simulation.run_long_simulation()` 会调用 `save_turn_delta()`，但只在临时复制的 campaign 上运行，不应被视为正式玩家存档入口。
- 此前 AI client prompt 推荐 `start_turn -> preview_action -> validate_delta -> commit_turn`，这进一步证明 `preview_from_text/plan_turn` 是工具协议层的缺口。本轮已将 prompt 更新为 `start_turn -> preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)`。

### 14.3 已同步修正的代码文案

`context_builder.render_semantic_suggestion()` 的旧说明曾与实现不一致；最新实现已统一为 trace-only：semantic suggestion 可记录差异，但不能改写最终路由。

当前文案为：

```text
用于补充意图识别和实体提示；仅记录为 trace，不覆盖最终路由，也不能绕过 resolver、delta schema、state audit 和 commit 门禁。
```

### 14.4 Phase 0-2 实现后复核

本轮已同步新增 `rpg_engine.surface_inventory`、`rpg_engine.mcp_transcript`、`rpg_engine.performance_baseline`、Phase 0 surface/performance baseline 文档、AI client/author prompt 版本和权限声明、MCP tool description 边界文案，以及 inventory/prompt/tool description/No-AI gold-set/MCP transcript/performance baseline 测试。

多角色复核结论：Phase 0-2 当前实现可以作为后续阶段基线继续推进。它满足第 5.1 的职责单一、边界清晰、可测试和不过度设计要求，因为新增 inventory 不接管 runtime 业务，MCP adapter 仍是薄适配层，外部 AI prompt 只作为低信任操作指南。

已处理问题：

- 文档和代码清单可能漂移：`tests/test_surface_inventory.py` 已要求 Phase 0 文档包含 inventory 中所有 MCP、AI prompt 和 package 管理入口。
- maintenance/admin/import/export/repair 类入口可能误标为默认暴露：`tests/test_surface_inventory.py` 已要求相关 profile/write mode 不能 `default_exposed=True`。

残余风险：

- `preview_action` 已移出默认 MCP player profile，只在 low-level profile 注册。仍需用 MCP transcript 测试证明普通 natural-language play 不会把低层工具作为首选入口。
- No-AI gold set 已扩充为 25 个 fixture 用例，覆盖多语言、多动作、复合、失败和越权输入；但还不能代表完整 intent accuracy。Phase 1 应继续扩充多 package fixture 并输出 accuracy、clarify rate、block rate。
- Phase 0 已新增独立 runtime latency report，记录 `start_turn`、`preview_from_text`、`validate_delta`、`commit_turn` 的本机 P50/P95。后续阶段应以该报告作为退化比较基线。

详细复审表和处理记录见 [`phase-0-surface-inventory.md`](phase-0-surface-inventory.md) 第 6 节。外部项目经验对照和 Phase 3 前专家清单见 [`external-projects-review.md`](external-projects-review.md)。

### 14.5 Phase 0-4 实现后多角色复审

复审对象：Phase 0 inventory/baseline、Phase 1 `IntentRouter`、Phase 2 `player_turn`/`preview_from_text` 和 MCP/prompt/transcript、Phase 3 `TurnContract`、Phase 4 `TurnProposal`。  
复审范围：代码、文档、prompt、MCP 默认 surface、gold set、transcript、response lint、proposal validation 和 response acceptance 主路径。  
复审结论：**Phase 0-4 主路径可以视为已完成；没有发现需要回滚 Phase 3/4 的阻塞问题。** 发现的问题属于后续阶段或硬化项，必须在 Phase 5/6 前继续跟踪。

本次复审直接阅读的关键代码入口：

- Phase 0：`rpg_engine.surface_inventory`、`rpg_engine.mcp_adapter.MCP_TOOL_NAMES`、`rpg_engine.mcp_transcript`、`rpg_engine.performance_baseline`。
- Phase 1：`rpg_engine.intent_router.route_intent()`、`context_builder.classify_request()`、`context_builder.apply_semantic_request_decision()`、`GMRuntime.act()`。
- Phase 2：`AIGMMCPAdapter.player_turn()`、`AIGMMCPAdapter.preview_from_text()`、`AIGMMCPAdapter.preview_action()`、`GMRuntime.preview_from_text()`、`GMRuntime.preview_action()`、AI client prompt 和 transcript fixtures。
- Phase 3：`turn_contract_for_intent()`、`turn_contract_to_dict()`、`turn_contract_from_dict()`、`response_lint.lint_response()`、CLI/turn assistant response lint 调用点。
- Phase 4：`TurnProposal`、`turn_proposal_from_dict()`、`validate_turn_proposal()`、`turn_proposal_from_preview_context()`、`response_acceptance.accept_response()`、CLI/turn assistant proposal validation 调用点。

| 角色 | 结论 | 代码/测试证据 | 发现的问题或后续要求 |
|---|---|---|---|
| 产品经理 | 通过 | 默认玩家 workflow 已覆盖选择/继续存档、上下文、自然语言预演、校验和提交；No-AI gold set 覆盖高频真局输入 | 阶段收益已有测试证明，但仍需要持续输出误判率、block rate 和 tool misuse rate |
| UX/交互设计师 | 通过 | `StartTurnResult`、`PreviewActionResult`、`TurnContract`、`TurnProposal` 都暴露状态和下一步信息；Phase 5-7 后新增 validation/commit/projection report | 仍需把 preview/validated/committed/projection pending/failed 做成更清晰的用户文案 |
| 游戏设计师/内容作者 | 通过 | AI/human/response draft 都必须进入 `TurnProposal` 并带 `delta_source`、`provenance`、`human_confirmed` | `maintenance_delta` 已建模，maintenance/import 已有 profile 和 projection report；批量报告仍需硬化 |
| 软件架构师 | 有条件通过 | Router、Contract、Proposal 没有接管 resolver/commit/projection 规则；`preview_action` 仍是低层确定性 API；Phase 5-7 已拆出 validation/commit/projection owner | `TurnCoordinator` 和目标工具 surface 仍未完成 |
| 后端/内核工程师 | 通过 | `response_lint` 强制消费 `TurnContract`；strict proposal loader 拒绝旧 `proposed_delta` proposal 字段；direct `preview_action` ready delta 也会生成 `TurnProposal` | 顶层 `save-turn` 和 `turn_assistant --save` 已迁移为 admin/legacy profile；仍需继续压实 import/migration profile |
| AI Agent 工程师 | 有条件通过 | MCP/prompt/transcript 已要求默认自然语言行动优先 `player_turn`，并阻止普通流程直接首选 `preview_action` | 低层工具只在 low-level profile 注册；必须继续用 transcript 测试防误用 |
| AI/ML 与提示词工程师 | 有条件通过 | 外部 AI prompt 已声明低信任；AI 产出的 delta/proposal 必须进入结构化对象和 provenance | `semantic_ai` 开启时的 `start_turn`/`preview_from_text` 语义一致性还不是完整矩阵；No-AI 主路径通过，但 AI-assisted parity 需单独补测 |
| QA/测试工程师 | 通过 | `pytest` 覆盖 surface inventory、MCP transcript、intent gold set、contract lint、proposal source、旧字段拒绝和 response draft confirmation | gold set 已可作为 Phase 0-4 基线，但仍需要多 package fixture 和 profile matrix |
| SRE/可靠性工程师 | 有条件通过 | Phase 0 performance baseline 已记录关键路径；Phase 3/4 新增合同层后全量测试通过 | 严格 Phase 3/4 后尚未生成新的性能对比报告；若后续关键路径劣化超过 20%，必须说明收益和回滚方式 |
| 安全/权限/隐私工程师 | 通过 | 默认 MCP 不暴露 admin/repair/migration/import/export/patch；hidden/maintenance 边界未放宽；prompt 不授予权限 | `player_confirm` 是默认写入入口；低层 `commit_turn` 只在 developer/trusted profile 注册，并继续要求 validate/preview 前置条件 |
| 数据/评估工程师 | 有条件通过 | 当前有 gold set、transcript 和测试基线，可统计 route/tool misuse | 还缺阶段性 metrics report；Phase 5 前建议固定 accuracy、latency、confirmation rate、block rate 字段 |
| 发布/维护工程师 | 通过 | README 测试基准、prompt、tool description、architecture doc 已同步；Phase 0 inventory 有文档哨兵测试 | 发布说明需要明确 Phase 0-4 已完成但 Phase 5-7 未完成，避免外部用户误以为全链路优化结束 |

复审中确认的已处理问题：

- 旧 proposal 结构问题：`TurnProposal` strict loader 已拒绝未知字段，旧 `proposed_delta` proposal 字段不能再绕过合同。
- response lint 旁路问题：CLI 和 turn assistant 已要求从 context 读取 `TurnContract`，`lint_response()` 不再接受无合同 mode/submode fallback。
- resolver delta 来源问题：`preview_from_text()` 和 direct `preview_action()` 的 ready delta 都会生成 `TurnProposal(delta_source=resolver_proposed)`。
- response draft 来源问题：`accept_response()` 已输出 `TurnProposal(delta_source=response_draft)`，且 proposal guard 要求人工确认。
- 外部 Agent 误用问题：AI client prompt 和 MCP transcript 测试已把自然语言玩家行动默认入口固定到 `player_turn`。

复审中保留的非阻塞问题：

- low-level surface 误用仍需跟踪；当前通过 profile 注册拆分、prompt 文案、transcript validator 和 mismatch guard 缓解。
- `semantic_ai` 打开时，context builder 能收集 semantic suggestion，但该结果只进入 trace；AI-assisted parity 的重点已经转向 `intent_ai=consensus` 下 external/internal candidate 的采纳、澄清和 fallback 对照。
- Phase 4 已统一 proposal 表达，但保存策略还没有集中到 `ValidationPipeline` 和 `TurnCommitService`；这是 Phase 5/6 范围，不是 Phase 4 回滚理由。
- 当时遗留问题：投影状态仍由多处手动刷新/mark clean；Phase 7 已完成集中化，Phase 7.1 已完成边界硬化。

专家综合判断：Phase 0-4 没有阻塞性问题，可以进入 Phase 5；后续应优先补齐 `intent_ai=consensus` parity 测试、metrics report 字段和低层 `preview_action` 误用监控。

### 14.6 Phase 5-6 实现后多角色代码复审

复审对象：Phase 5 `ValidationPipeline` 和 Phase 6 `TurnCommitService`。  
复审范围：`validation_pipeline.py`、`commit_service.py`、`runtime.commit_turn()`、MCP `commit_turn`、`play commit`、顶层 `save-turn`、`turn_assistant.run_save_pipeline()`、`response_acceptance.accept_response()`、MCP transcript validator、README 和测试基线。  
复审结论：**Phase 5/6 主路径可以视为已完成；没有发现需要为了旧裸 delta 玩家提交回滚的阻塞问题。**

本次复审直接阅读和测试的关键代码入口：

- Phase 5：`run_validation_pipeline()`、`ValidationReport`、`ValidationStageResult`、各 profile/stage helper。
- Phase 6：`commit_turn_proposal()`、`commit_turn_delta()`、`GMRuntime.commit_turn(turn_proposal=...)`、`AIGMMCPAdapter.commit_turn(turn_proposal=...)`、`cli_v1 play commit --proposal-json`。
- Phase 7：`ProjectionService.refresh()`、`ProjectionReport`、legacy `refresh_projections()` wrapper、commit result projection report、CLI maintenance/admin/import projection profiles。
- 迁移入口：顶层 `save-turn`、`turn_assistant.run_save_pipeline()`、`response_acceptance.accept_response()`、`save_patch`、content/proposal/import/campaign validation 入口。
- 外部 surface：`mcp_transcript.validate_commit_prerequisites()`、`surface_inventory`、MCP tool description 和 V1 CLI tests。

| 角色 | 结论 | 代码/测试证据 | 发现的问题或后续要求 |
|---|---|---|---|
| 产品经理 | 通过 | 普通玩家 workflow 现在从 preview proposal 到 commit result 可追踪；`save-turn` 明确降级为 admin/legacy | 仍需要把新状态做成用户可见的 metrics/report |
| UX/交互设计师 | 通过 | `ValidationReport.render()`、accept-response report、play commit JSON 都显示 profile/status/stage；commit result 现在包含 `projection_report` | 需要把 projection pending/failed 做成更清晰的最终用户文案 |
| 游戏设计师/内容作者 | 通过 | `response_draft` 未确认会被 proposal guard 阻断；`human_edited` proposal 可人工确认提交 | maintenance/import 批量写入报告还需继续硬化 |
| 软件架构师 | 通过 | validation stage 不写库；commit service 不重新解释玩家意图；runtime/MCP/CLI 只选择 profile 和 proposal | `TurnCoordinator` 仍未落地，当前是薄迁移而非最终工具形态 |
| 后端/内核工程师 | 通过 | `commit_turn_delta()` 拒绝无 `proposal_id` 的 `player_turn_commit`，并强制 validation report 与实际提交 delta 的 digest 一致；admin/legacy profile 可保存但输出 warning；post-commit artifacts 由 `ProjectionService` 处理 | `stale` 版本检测和 import/migration 批量 commit report 仍需硬化 |
| AI Agent 工程师 | 通过 | MCP `commit_turn` 接收 `turn_proposal`；transcript validator 新增 `commit_without_turn_proposal` | prompt/skill 文案需持续随目标 `commit_proposal` 工具更新 |
| QA/测试工程师 | 通过 | 新增 `tests/test_validation_pipeline.py` 和 `tests/test_projection_service.py`，覆盖 profile/stage、proposal gate、validation/delta digest、projection success/failure/legacy wrapper | import/migration profile 目前仍需要真实批量写入 fixture |
| SRE/可靠性工程师 | 有条件通过 | post-check、backup 和 projection report 分离；projection failure 会持久化为 `failed` 并可通过 repair/retry 处理 | 性能基线已更新为 proposal commit，但仍需阶段性 latency/block-rate/projection failure rate 报告 |
| 安全/权限/隐私工程师 | 通过 | 裸 delta player commit 被拒绝；legacy/admin 路径不会伪装成 player profile | 默认 player profile 通过 `player_confirm` 保存；低层 `commit_turn` 只在 developer/trusted profile 注册，仍需 transcript/prompt 持续证明不会被误用 |
| 发布/维护工程师 | 通过 | README 和架构文档同步 Phase 7 状态；legacy/admin projection 入口保留但由 service/profile 边界承载 | 发布说明仍需补充 stale projection 版本迁移和回滚说明 |

复审中确认的已处理问题：

- proposal guard 不再只是报告项；普通玩家 commit 必须带 approved `TurnProposal`。
- `response_acceptance.accept_response()` 不再直接保存，未确认 `response_draft` 不再自动保存。
- 顶层 `save-turn` 和 `turn_assistant --save` 已使用 `admin_or_legacy_save_turn` profile，不再伪装成玩家路径。
- MCP transcript 现在要求 `commit_turn` 请求包含 preview 返回的 `turn_proposal`。
- validation/delta 绑定问题已修复：`ValidationReport` 现在记录 `delta_digest`，`commit_turn_delta()` 会拒绝复用不匹配的 validation report 提交其他 delta。
- Phase 7 投影所有权已收敛：`ProjectionService` 统一刷新 snapshots/cards/memory/reports/package_lock，失败写入 `projection_state.status='failed'` 和 `last_error`，commit/runtime/CLI 返回 `ProjectionReport`。
- 旧 `refresh_projections()` 入口已迁移为 legacy wrapper；主 CLI 的 `init`、`render-current`、`render-cards`、`memory rebuild`、`audit`、`projection repair`、content/proposal/import/save patch/campaign validation 等入口不再直接 mark clean。

复审中保留的非阻塞问题：

- `stale` projection version 检测仍未单独落库；当前以 dirty/refreshing/clean/failed 为主。
- `content_delta`、`content_sync`、`save_patch`、import/migration 已接入 projection report，但仍需要更完整 maintenance/import commit report。
- `TurnCoordinator` 和目标工具 `plan_turn -> validate_proposal -> commit_proposal` 尚未落地；当前仍是过渡工具链。
- `intent_ai=consensus` parity、metrics report 和发布/回滚说明仍需继续补齐。

专家综合判断：Phase 0-7.1 主路径和 projection hardening 已完成，可进入完整 `TurnCoordinator` / `plan_turn -> validate_proposal -> commit_proposal` surface、`intent_ai=consensus` parity 和 import/migration 批量 profile 报告。后续实现不得回退 Phase 7.1 已建立的 commit/projection 状态边界。

### 14.7 Phase 7.1 多专家修补计划和落地记录

本节把 2026-07-01 Phase 7 后的多专家联合代码评审转化为可执行修补计划，并记录 Phase 7.1 的实际落地结果。它是第 10.1 Phase 7.1 的代码 review 依据。

总体判断：`ProjectionService` 的方向正确；进入 `TurnCoordinator` 前必须先打硬 projection 层的事务语义、repair 作用域和状态 API。Phase 7.1 已完成这些硬化项。

#### 14.7.1 目标边界

- `ProjectionService` 只负责 projection 状态、artifact 刷新、repair/retry 报告，不负责决定事实写入是否允许。
- `UnitOfWork` 继续负责事务内 dirty/outbox/search 这类强一致动作。
- `TurnCommitService` 负责事实写入和 commit result，不把 projection failure 伪装成事实 commit failure。
- legacy/admin/maintenance/import 入口可以保留，但必须显式使用 profile 和 report，不得伪装成 player commit。

#### 14.7.2 非目标

- 不做完整 `TurnCoordinator`。
- 不新增目标工具 `plan_turn -> validate_proposal -> commit_proposal`。
- 不重写 `save_turn_delta()`、`UnitOfWork` 或 migration 系统。
- 不引入完整异步任务队列。
- 不为了兼容旧命令牺牲 `TurnProposal`、`ValidationReport`、`CommitResult`、`ProjectionReport` 的合同边界。

#### 14.7.3 发现和修补项

| 优先级 | 专家视角 | 发现 | 落地处理 | 验收 |
|---|---|---|---|---|
| P2 | 后端/SRE | `ProjectionService.refresh()` 内部会提交事务，maintenance caller 若在未显式提交事实 DML 后调用，会让 projection service 隐式提交事实变更 | 增加 commit policy；strict post-transaction policy 在 `conn.in_transaction` 时拒绝；maintenance caller 在需要事实提交后 projection 可失败时显式提交事实再刷新 | strict policy 测试通过；save patch/content/proposal apply 的事实提交点可见；projection failure 不回滚已提交事实 |
| P2 | 产品/API | `CommitResult.ok` 只看 post-check，不能表达事实已提交但 projection failed | 增加 `write_status`、`projection_status`；同步 runtime/MCP/CLI 输出；保留兼容字段但标注为 projection report 派生 | snapshot/cards 注入失败时返回 `write_status=committed` 与 `projection_status=partial_failure/failed` |
| P2 | QA/SRE | `ProjectionReport.failed` 容易混入无关 global failed，targeted repair exit code 会被污染 | 区分 requested/global 状态字段；repair 的 `ok` 和 CLI exit code 默认只看 requested scope | 修复 snapshots 成功但 cards 仍 failed 时，`projection repair --name snapshots` 返回 0，并报告 `global_failed=[cards]` |
| P3 | SRE/数据 | projection report 缺少 duration/diagnostic 字段，后续无法统计 repair latency 和 failure rate | item 和 report 增加耗时字段；后续 ops/performance report 可消费 | 测试断言 report 包含 duration；文档记录 dirty age、failure rate、repair duration |
| P3 | 发布/维护 | `stale` 只在文档语义中存在，version mismatch 尚未可修复 | 最小实现：`projection_state.version < PROJECTION_VERSIONS[name]` 视作 stale/refresh_required，repair stale 等价 dirty refresh | 人工降低 version 后 status/repair 能识别并刷新 |

#### 14.7.4 实际执行顺序

1. 先修 `ProjectionReport` 作用域字段和 `ok/status` 语义。
2. 再修 `ProjectionService` commit policy 和 maintenance caller 显式事实提交边界。
3. 同步 `CommitResult`、runtime、MCP audit summary、CLI 输出中的 `write_status/projection_status`。
4. 补 targeted repair、projection failure、strict transaction policy 和 stale version repair 测试。
5. 同步 README、架构文档、release/rollback/repair 说明。

#### 14.7.5 落地结果

- `python3 -m pytest -q`：`174 passed, 77 skipped`。
- `python3 -m unittest discover tests -q`：`251 tests OK (77 skipped)`。
- 新增测试覆盖：
  - targeted repair 不受无关 failed projection 污染。
  - projection failure 后 commit 仍是 `write_status=committed`。
  - strict post-transaction policy 拒绝未提交 caller transaction。
  - stale version 可 repair。
- README 和本文档明确标注：Phase 7.1 是 projection hardening，不是 `TurnCoordinator` 阶段。

### 14.8 最终核对结论

本文档的主线判断成立，但应把“统一路由”理解为第一步，而不是全部问题。完整优化必须同时处理：

1. 自然语言入口的唯一 `IntentRouter`。
2. Agent 面向自然语言的 `preview_from_text/plan_turn` 主工具。
3. `TurnContract` 和 `TurnProposal` 作为 Phase 3/4 合同层，已经承接模板、profile、delta source、provenance 和确认状态。
4. `ValidationPipeline` 和 `TurnCommitService` 已完成 Phase 5/6 主路径，普通玩家 commit 必须带 approved `TurnProposal`。
5. `ProjectionService` 已完成集中化和 Phase 7.1 projection boundary hardening；下一步做完整 `TurnCoordinator`。

如果只完成 `IntentRouter` 和 Phase 3/4 合同层，可以解决行动模板误判和 delta 来源不可追踪；但如果不继续收敛保存、校验和投影，仍会留下“叙事、delta、保存、产物状态互相不一致”的长期风险。

## 15. 修订后多角色最终复审

本节记录根据专家意见补齐边界、详细开发计划、验收门槛和外部 surface 任务后的最终复审结论。复审对象是本文档的设计方案，不代表所有代码已经完成实现。

总体结论：**设计方案通过，可进入分阶段实现；没有阻塞性架构问题。**  
通过条件是严格执行第 10.2 的阶段门槛、第 10.3 的外部 surface 计划和第 13 节验收标准，不能把当前过渡链路误认为完整目标链路。

| 角色 | 复审结论 | 仍需盯住的条件 |
|---|---|---|
| 产品经理 | 通过 | 阶段收益必须用 gold set、误判率、保存可靠性和 projection 状态指标证明 |
| UX/交互设计师 | 通过 | 玩家/Agent 输出必须明确区分理解、预演、校验、提交和投影状态 |
| 游戏设计师/内容作者 | 通过 | AI 内容默认只作为候选或 proposal，不得无确认写成事实 |
| 软件架构师 | 有条件通过 | `TurnCoordinator` 必须保持编排层，不得吸收规则、保存和投影实现 |
| 后端/内核工程师 | 有条件通过 | 新服务必须 thin wrapper 起步，旧入口迁移要保留兼容和 profile 报告 |
| AI Agent 工程师 | 通过 | 外部 Agent 默认只接触 workflow 工具；低层/admin/maintenance 工具有显式边界；AI client prompt/skill 与 MCP 工具协议同步 |
| AI/ML 与提示词工程师 | 通过 | AI helper 必须可观测、可降级、可离线评估，不能扩大写入权限 |
| QA/测试工程师 | 有条件通过 | 每个 phase 合并前必须补对应测试矩阵，尤其是 profile、MCP transcript 和 projection failure |
| SRE/可靠性工程师 | 有条件通过 | Phase 0 必须先建立性能和失败率 baseline，后续劣化超过 20% 需解释和回滚 |
| 安全/权限/隐私工程师 | 有条件通过 | profile、capability、write guard、hidden visibility 必须进入 blocker 级测试 |
| 数据/评估工程师 | 有条件通过 | AI lift、No-AI baseline、tool misuse、latency 和 projection failure 必须持续出报告 |
| 发布/维护工程师 | 通过 | schema、projection state、工具协议、AI client prompt/skill、Campaign/Save Package 管理入口变化必须有 migration、rollback、repair/rebuild 说明 |

### 15.1 全部计划多专家审核矩阵

本轮复审覆盖第 10.1、10.2、10.3 的全部计划，包括核心引擎阶段、Phase 7.1 projection boundary hardening、对外 MCP surface、AI client prompt/skill、Campaign Package、Save Package、测试、发布和回滚。

| 角色 | 核心 Phase 0-7.1 | MCP surface | AI prompt/skill | Campaign/Save Package | 测试/发布/回滚 | 审核结论 |
|---|---|---|---|---|---|---|
| 产品经理 | 阶段顺序合理，先解决真局误判再收敛保存和投影 | 默认工具能覆盖普通玩家主流程 | prompt/skill 应减少工具误用 | 创建/选择/检查属于玩家路径，迁移/修复属于维护路径 | 指标必须证明阶段收益 | 通过 |
| UX/交互设计师 | 需要把每阶段状态反馈给玩家 | 工具输出要区分选择、预演、校验、提交、投影 | AI 回复必须说明未保存、需确认和失败状态 | 包管理操作要有清晰状态语义 | transcript/golden 输出要覆盖状态表达 | 通过 |
| 游戏设计师/内容作者 | resolver/contract/proposal 能保护玩法规则 | 普通 MCP 不应暴露内容同步和 package upgrade | 作者 AI 只能产出候选和建议 | Campaign Package 维护能力保留但走 author/maintenance profile | 内容变更需 provenance 和 visibility 测试 | 通过 |
| 软件架构师 | 分层正确，风险是 coordinator/pipeline 过大 | MCP adapter 必须保持薄适配 | prompt/skill 不是架构 owner | package/save 管理必须走 service/profile/report | release gate 应阻止无测试迁移 | 有条件通过 |
| 后端/内核工程师 | thin wrapper 起步，渐进迁移可落地 | MCP 工具应转调 runtime/service | prompt 变化要同步 schema 和工具描述 | import/export/repair 要兼容旧 CLI | 需要 old path/new path/profile 迁移表 | 有条件通过 |
| AI Agent 工程师 | workflow 逐步从 delta 链路过渡到 proposal 链路 | 默认 Agent 不直接碰 low-level/admin | prompt/skill 固定推荐链路 | Agent 可做只读检查和受控创建，不做迁移/修复 | transcript 测试是硬门槛 | 通过 |
| AI/ML 与提示词工程师 | No-AI baseline 保留，AI 只增强 | MCP 不代理模型调用 | prompt/skill 版本化并可评估 | 作者 AI 输出必须带 provenance | AI-assisted lift 要能和 baseline 对比 | 通过 |
| QA/测试工程师 | 每 phase 都有验收条件 | MCP transcript 覆盖默认流程和误用 | prompt injection fixture 必须覆盖 | package/save profile matrix 必须覆盖 | 测试矩阵完整但实现量较大 | 有条件通过 |
| SRE/可靠性工程师 | Phase 0 baseline 是必要前置 | MCP audit 要有耗时、状态、错误摘要 | prompt/skill 不能掩盖 timeout/fallback | import/export/repair 需失败恢复 | 性能劣化超过 20% 必须解释和回滚 | 有条件通过 |
| 安全/权限/隐私工程师 | profile/capability/write guard 必须贯穿写入 | 默认 MCP 不暴露 admin/repair/migration | prompt/skill 不能授予权限 | package/save 路径限制在 root，hidden 不泄露 | 安全违规必须 blocker | 有条件通过 |
| 数据/评估工程师 | accuracy、latency、block rate 可度量 | 统计 tool misuse rate | prompt 变更要能 A/B 或离线比较 | 统计迁移成功率、回滚率、repair 成功率 | metrics report 是完成条件 | 有条件通过 |
| 发布/维护工程师 | Phase 化适合发布和回滚 | tool description 变化要发版说明 | prompt/skill 随协议版本发布 | schema/migration/repair 要有 rollback note | release/rollback checklist 已覆盖关键项 | 通过 |

审核发现的剩余非阻塞风险：

1. `TurnCoordinator`、`ValidationPipeline` 和 `ProjectionService` 的实现边界必须在代码 review 中持续检查，防止新中心变成复杂度黑洞。
2. Phase 0 的 inventory 和 baseline 是后续一切指标的地基，不能跳过。
3. MCP 默认暴露面必须以实际配置和 tool description 为准，不能只靠文档承诺。
4. AI prompt/skill 更新必须进入发布流程；否则工具协议变了，外部 Agent 仍会按旧链路调用。
5. Campaign/Save Package 的 maintenance/import/admin profile 测试量较大，应优先做 profile matrix，再做深度迁移测试。

全计划审核结论：**全部计划可执行、覆盖面充分、没有新增阻塞项；Phase 0-7.1 已完成当前主路径与 projection hardening，后续应把第 10.3 的外部 surface 任务纳入每阶段验收。**

专家一致意见：

1. 当前方案符合第 5.1 的核心架构原则，尤其是职责单一、边界清晰、数据流可追踪、可测试、故障隔离和不过度设计。
2. AI 设计方向正确：No-AI path 是最低标准，内部 AI helper 是增强模块，外部 AI 是低信任调用者。
3. 最优先落地顺序应保持不变：先统一自然语言路由和 Agent 安全入口，再收敛 proposal/validation/commit/projection，Phase 7.1 projection 边界硬化完成后进入完整 coordinator。
4. 不应为了“统一”删除 admin/maintenance 能力；正确做法是 profile 化、可观测、可回滚。
5. 对外 MCP 工具、外部 AI prompt/skill、Campaign/Save Package 管理能力都已纳入边界；默认玩家 workflow 和 package/admin/maintenance 能力必须分层暴露。
6. 文档当前已经补齐专家要求的计划修正、Phase 7.1 修补计划和落地记录、外部 surface 详细开发计划、验收门槛和最终复审结论，可以作为后续实现和代码 review 的依据。

最终判断：**文档设计层面已通过多角色复审。后续风险主要在实现执行，而不是方案方向。**
