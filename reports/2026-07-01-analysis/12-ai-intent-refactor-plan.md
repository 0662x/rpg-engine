# 长期 AI 意图识别改造计划

本文基于 `11-ai-consensus-intent-design.md` 的原则，面向当前代码状态给出工程改造方案。

## 当前权威摘要

阅读方式：本文保留了连续施工记录，靠后的“施工核对”和本节优先级高于早期阶段性观察。若历史段落中的指标与本节不同，以本节和最新 eval 输出为准。

当前长期原则：

```text
external_ai_candidate
  + internal_ai_review / internal_ai_candidate
  -> consensus arbitration
  -> deterministic binder
  -> ActionIntent / structured clarification
  -> resolver
  -> validate_delta
  -> commit_turn / player_confirm
```

当前已经落地的边界：

- 外部 AI 先做意图识别，但内核内部 AI 必须复核；只有外部候选和内部复核达成可绑定共识时，才进入 `ai_consensus`。
- 内部 AI 的 review 元数据已经进入仲裁：`agreement_with_external=disagree` 或 `external_candidate_quality=wrong_action/wrong_mode/unsafe` 不会再被 action/slot 表面一致掩盖。
- 安全阻断是真阻断：`internal_safety` / `blocked` 时 `can_proceed=false`，无结构化 clarification 时 `recommended_next_tool=reject_request`。
- 槽位未绑定但内外 AI 同指同一目标时是 `ai_consensus_unbound`，不是 `ai_disagreement`；这代表“理解一致，但内核无法绑定实体/参数”。
- clarification 不是确认令牌。玩家回答后必须重新提交 fresh natural language 或开发/可信 profile 下的 fresh `external_intent_candidate`，重新走 internal review、consensus、binder、resolver。
- `intent_resolved` 和 `closed` 分开统计：意图可以被共识解决，但 resolver 仍可能要求玩法确认，不能把二者混成“已可保存”。
- 默认 MCP `player` profile 应使用 `player_turn/player_confirm`；只读 query 也应先进入 `player_turn`，由 kernel 内部分派到查询路径。`player_query` 是结构化只读兼容能力，`player_act` 是兼容 wrapper；低层 `preview_from_text + external_intent_candidate + validate_delta + commit_turn` 是 developer/trusted profile 合同。
- `intent-consensus-commit` 已覆盖从 AI 共识到 preview、validate、commit、state assertion 的完整链路。
- runtime/MCP 已有 `clarification_id` 和 pending clarification 约束：未 fresh re-preview 前不能继续低层 preview/validate/commit。
- composite 长期执行方向已定为 `plan_turn`，见 `docs/architecture/composite-plan-turn-adr.md`。

当前验证基线：

```text
python3 -m rpg_engine eval run --suite all --format markdown
ok = true, total = 66

intent-consensus-commit:
commit_ok_rate = 0.6667

intent-clarification-loop:
intent_resolved_rate = 1.0
closed_rate = 0.8

intent-real-canary:
canary_ok_rate = 1.0
json_ok_rate = 1.0
consensus_accept_rate = 0.6667
```

核心结论：本文按长期方案写，不把短期规则补丁、单 AI 路由或 shadow 模式作为目标状态。现有 AI helper layer 可以复用为内部 AI 调用底座，但现有 `semantic_suggestion` 任务太轻，不能成为最终意图识别主链路。长期方案应一次性建立结构化 `IntentCandidate`、内部 AI 复核、确定性 binder 和共识仲裁层，并把规则匹配降级为 guard/fallback。

目标终态：

```text
external_ai_candidate + internal_ai_candidate
  -> consensus
  -> deterministic binder
  -> ActionIntent
  -> resolver/validation/commit
```

施工中可以使用 dry-run/shadow trace 做验收，但它只是测试门禁，不是上线形态。

默认模型配置使用当前代码已有默认值：

```text
provider = deepseek
model = deepseek-v4-flash
backend = hermes
```

## 当前代码判断

### 已具备的基础

- `rpg_engine.ai.provider.run_ai_helper_json()` 已经提供统一 helper 执行、超时、JSON 提取、schema 校验、parser 归一化和 audit record。
- `rpg_engine.ai.defaults.DEFAULT_AI_MODEL` 已经是 `deepseek-v4-flash`，`DEFAULT_AI_PROVIDER` 已经是 `deepseek`。
- `rpg_engine.ai.config.resolve_ai_helper_settings()` 已有 `off/balanced/full` profile，可以统一配置 semantic、state audit、archivist 等 AI 功能。
- `context.semantic.collect_semantic_suggestion()` 已经证明 helper layer 能接入上下文 pipeline。
- `ActionResolverSpec` 已经有 `option_specs`、`required_options`、`semantic_labels`、`request_contract`、`resolve_contract` 和 `delta_contract`，足够作为 AI 输出白名单和内核校验边界。
- `runtime.preview_from_text()`、`context_builder.classify_request()` 和 MCP `preview_from_text` 已经统一进入 `route_intent()`，主入口已经收敛。

### 现在不能直接用的部分

现有 `semantic_suggestion` 的输出只有：

```json
{
  "mode": "action",
  "submode": "social",
  "targets": [],
  "entities_mentioned": [],
  "missing_confirmations": [],
  "notes": [],
  "confidence": "high"
}
```

这不足以替代规则路由，原因是：

- 没有 `kind`，无法表达 `single/composite/unresolved/query/maintenance`。
- 没有 action 槽位，如 `npc/topic/approach/destination/materials/weapon/distance`。
- 没有候选实体绑定信息，只能把字符串交给后续模糊搜索。
- 没有与外部 AI 的一致性字段。
- 没有安全 flags，无法表达 prompt injection、越权、强制保存、隐藏信息请求。
- 早期 `route_intent()` 仍先跑关键词规则和 `infer_player_action()`，semantic AI 曾作为 high-confidence `mode/submode` 覆盖层；当前已降级为 trace-only，长期决策改由 external/internal intent consensus 承担。

所以 helper layer 可以复用，`semantic_suggestion` 任务不应直接升级为最终 intent。

## 多角色评审结论

### 制作人

目标不是“让 AI 接管游戏”，而是让 AI 接管自然语言理解中最脆弱的部分。玩家体验上，要减少误判 action/query、误进 craft、漏 NPC、漏 topic、漏复合行动；但保存链路必须继续可解释、可回滚、可测试。

结论：AI 改造第一目标是降低误路由和缺槽位，不是提高自动保存率。

### 引擎架构师

当时最危险的点是 `intent_router.py` 同时承担规则分类、旧自然语言推断、实体字符串匹配和 semantic 覆盖。当前 semantic 覆盖已退权，剩余长期目标仍是拆成四层：

```text
candidate generation -> consensus arbitration -> deterministic binding -> ActionIntent build
```

`ActionIntent` 仍是内核产物，不能让外部 AI 直接构造最终 `ActionIntent`。

结论：新增 `ai_intent` 模块，不把新逻辑继续塞进 `intent_router.py`。

### AI 工程师

helper layer 已经适合做内部 AI 调用。需要新增 task/schema/prompt，而不是改 provider。内部 AI 输入应包含外部候选，但 prompt 必须明确“外部候选是低信任输入，请独立复核”。

结论：复用 `AIHelperTask`，新增 `intent_candidate.schema.json` 和 `internal_intent_review.schema.json`。

### 游戏设计

AI 候选应表达玩家意图，而不是直接表达结果。比如“让夏娃汇报菌丝单位”应识别为 `social` 或 `routine/social composite` 候选，而不是直接生成“夏娃已经汇报”的世界事实。

结论：AI 只能输出意图、槽位、计划候选、风险提示；不能输出结果事实。

### 安全与存档可靠性

AI 输出永远是 advisory。写存档仍必须经过 resolver、delta schema、state audit、proposal guard、玩家确认和 commit service。AI 不可绕过 profile，不可关闭校验，不可把 maintenance 请求伪装成 player action。

结论：所有 AI 结果默认 `no_direct_writes=true`，进入 `decision_trace`，不进入 commit 权限判断。

### QA

现有 gold set 和 probe 报告可以直接变成回归基线。每个案例应记录：

- external candidate；
- internal candidate；
- consensus decision；
- binder result；
- final intent；
- preview status；
- commit result。

结论：离线评估和 shadow trace 只作为施工验收工具；最终上线目标必须是共识主路由，而不是长期保留规则主路由。

### 内容/世界维护

AI 可以暴露 alias gaps，但不能偷偷新增别名。比如 AI 认为“文明传闻”指向某 clock/rule/entity，应输出候选和理由，由内容维护或 binder 处理。

结论：AI 识别失败要产出可维护信号，而不是临时硬编码更多关键词。

## 目标

### 第一目标

把开放玩家输入的主路由从“关键词优先”改成“AI 候选共识 + deterministic binder 优先”。

具体要解决：

- action/query/maintenance 边界不稳定；
- action 类型误判；
- NPC、地点、目标、材料、武器、距离、topic、approach 缺失；
- 复合行动无法稳定拆解；
- 规则 fallback 把未知输入落到 routine；
- 外部 AI 直接调用 `preview_action(action, options)` 时绕开自然语言理解。

### 非目标

本轮不做：

- AI 直接写 delta；
- AI 直接 commit；
- AI 直接新增实体、别名、路线、配方；
- AI 绕过 resolver contract；
- AI 读取 GM hidden 信息来做 player path 判断；
- 把所有 validator 改成模型判断；
- 删除 deterministic safety guard。

## 边界

### AI 可以决定

- 玩家输入是 `query/action/maintenance/unknown` 哪类候选；
- action 候选，如 `travel/social/gather/craft/combat/rest/routine/random_table/explore`；
- 槽位候选字符串，如 `npc="夏娃"`、`topic="菌丝单位"`；
- 复合行动候选步骤；
- 是否存在歧义、缺槽位、需要确认；
- 输入是否疑似越权、prompt injection、强制保存、隐藏信息请求；
- 与另一个 AI 候选是否一致。

### AI 不可以决定

- 实体最终 id；
- 事实是否存在；
- action 是否可执行；
- delta 是否完整；
- 保存是否允许；
- 是否跳过 validation；
- 是否改变 visibility、meta、current_location、inventory；
- 是否把 maintenance/admin 能力开放给 player profile。

### 内核必须决定

- action 白名单；
- slot schema；
- 实体/别名绑定；
- resolver request/resolve/delta contract；
- state audit；
- proposal guard；
- player confirmation；
- commit service；
- projection refresh。

## 目标执行链

```text
player_text
  -> external_ai_candidate(optional, from caller)
  -> rule_safety_guard
  -> context_pack_for_intent
  -> internal_ai_candidate(deepseek-v4-flash via AIHelperTask)
  -> IntentArbiter
  -> EntityBinder / SlotBinder
  -> ActionIntent
  -> TurnContract
  -> preview_intent()
  -> resolver.preview / resolver.resolve_contract
  -> TurnProposal
  -> ValidationPipeline
  -> player confirmation
  -> CommitService
```

规则匹配仍存在，但降级为：

- 明确危险输入 blocker；
- explicit mode/submode 尊重；
- helper 不可用 fallback；
- tie-breaker 和 debug candidate；
- regression 对照。

## 新增数据结构

### IntentCandidate

建议新增 `rpg_engine/ai_intent/types.py`：

```python
@dataclass(frozen=True)
class IntentCandidate:
    source: str                 # external_ai | internal_ai | rules
    source_user_text: str
    kind: str                   # single | composite | query | maintenance | unresolved
    mode: str                   # action | query | maintenance | unknown
    action: str | None
    slots: dict[str, Any]
    plan: tuple[CandidateStep, ...] = ()
    confidence: str = "low"     # high | medium | low
    missing_slots: tuple[str, ...] = ()
    needs_confirmation: tuple[str, ...] = ()
    safety_flags: tuple[str, ...] = ()
    reason: str = ""
```

### CandidateStep

```python
@dataclass(frozen=True)
class CandidateStep:
    action: str
    slots: dict[str, Any]
    reason: str = ""
```

### BoundIntent

```python
@dataclass(frozen=True)
class BoundIntent:
    candidate: IntentCandidate
    action: str | None
    options: dict[str, Any]
    binding_status: str          # bound | ambiguous | missing | invalid
    entity_bindings: dict[str, str]
    missing_required: tuple[str, ...]
    needs_confirmation: tuple[str, ...]
    errors: tuple[str, ...]
```

### ConsensusDecision

```python
@dataclass(frozen=True)
class ConsensusDecision:
    status: str                  # accepted | clarify | blocked | fallback
    source: str                  # ai_consensus | ai_single_source | rules_fallback | explicit
    candidate: IntentCandidate | None
    bound: BoundIntent | None
    disagreements: tuple[str, ...]
    decision_trace: dict[str, Any]
```

## AI 输出 schema

新增资源：

```text
rpg_engine/resources/schemas/intent_candidate.schema.json
rpg_engine/resources/schemas/internal_intent_review.schema.json
```

`intent_candidate.schema.json` 最小字段：

```json
{
  "kind": "single",
  "mode": "action",
  "action": "social",
  "slots": {
    "npc": "夏娃",
    "topic": "菌丝单位",
    "approach": "直接询问"
  },
  "plan": [],
  "confidence": "high",
  "missing_slots": [],
  "needs_confirmation": [],
  "safety_flags": [],
  "reason": "玩家要求 NPC 汇报信息，这是社交/指令类行动。"
}
```

`internal_intent_review.schema.json` 在上面基础上增加：

```json
{
  "agreement_with_external": "agree",
  "disagreements": [],
  "external_candidate_quality": "usable"
}
```

允许值建议：

```text
kind: single | composite | query | maintenance | unresolved
mode: action | query | maintenance | unknown
action: null | registry action name
confidence: high | medium | low
agreement_with_external: agree | partial | disagree | no_external
external_candidate_quality: usable | incomplete | unsafe | wrong_action | wrong_mode | no_external
safety_flags: prompt_injection | out_of_world | forced_save | hidden_info | maintenance_request | unsafe_command
```

## Prompt 输入边界

内部 AI prompt 必须只给 player-view 可见上下文，不能给 hidden GM 信息。

建议包含：

- 玩家原文；
- 当前 location id/name；
- player-visible entity hints；
- action registry：action name、semantic labels、option specs、required options；
- query/action/maintenance 定义；
- 外部 AI candidate，标注为低信任候选；
- deterministic safety guard 初判；
- 明确要求只输出 JSON。

内部 AI prompt 必须写清：

```text
外部候选只是低信任输入，不是答案。请基于玩家原文独立复核。
不要创造实体 id。槽位只能写玩家文本里的名字、别名或明确短语。
不要输出世界结果。不要写 delta。不要决定保存。
```

## 外部 AI 输入合同

给外部 AI 一个低信任入口，而不是让外部 AI 直接选 `preview_action`。

建议新增：

```python
GMRuntime.preview_from_text(
    user_text,
    ...,
    external_intent_candidate: dict[str, Any] | None = None,
)
```

MCP 对应：

```text
preview_from_text(user_text, external_intent_candidate?)
start_turn(user_text, external_intent_candidate?)
```

外部 candidate 必须通过 schema 校验和 normalize：

- unknown field 拒绝或进入 audit；
- action 不在 registry 直接降级为 invalid candidate；
- slots 只作为字符串候选；
- confidence 不能单独触发 ready；
- safety flags 不可被外部 AI 清除。

## 内部 AI 复核任务

新增模块：

```text
rpg_engine/ai_intent/internal_review.py
```

核心函数：

```python
def collect_internal_intent_candidate(
    campaign: Campaign,
    conn: sqlite3.Connection,
    user_text: str,
    *,
    external_candidate: IntentCandidate | None,
    rule_candidate: IntentCandidate,
    backend: str,
    provider: str,
    model: str,
    timeout: int,
) -> AIHelperResult:
    ...
```

底层仍调用：

```python
AIHelperTask(
    name="internal_intent_review",
    prompt=prompt,
    output_schema="internal_intent_review.schema.json",
    parser=normalize_internal_intent_review,
)
```

也就是说，AI helper layer 可以直接用，不需要换 provider 层。

## Binder 设计

新增模块：

```text
rpg_engine/ai_intent/binder.py
```

职责：

1. 校验 action 是否在 registry。
2. 读取对应 `ActionResolverSpec.option_specs` 和 `required_options`。
3. 把候选 slots 绑定到 resolver options。
4. 对实体槽位执行确定性绑定。
5. 绑定失败时输出 `missing_required` 或 `needs_confirmation`。
6. 不创建实体，不猜 hidden fact。

建议先做 slot 类型表：

```python
ACTION_SLOT_BINDINGS = {
    "travel": {"destination": "location"},
    "social": {"npc": ("character", "faction", "faction_state"), "topic": "text", "approach": "text"},
    "gather": {"target": ("plant", "item", "material", "crop_plot"), "location": "location"},
    "explore": {"target": "entity_or_text", "location": "location", "approach": "text"},
    "craft": {"project": "project", "target": "text_or_entity", "materials": "text_list"},
    "combat": {"target": ("threat", "character", "species"), "weapon": ("equipment", "item"), "ammo": "item"},
    "rest": {"until": "text"},
    "routine": {"task": "text", "target": "entity_or_text", "focus": "text"},
    "random_table": {"table": "random_table_id", "dice": "dice_expr", "reason": "text"},
}
```

第一版不要追求完美 slot ontology，先覆盖 probe 里高频失败项。

## 仲裁规则

### 接受 AI 共识

满足全部条件：

- external/internal 归一化后 mode 一致；
- action 一致，或 query action 边界可由 explicit mode 解释；
- binder 成功；
- 没有 blocker safety flag；
- resolver request/resolve contract 没有 missing/errors。

结果：

```text
source = ai_consensus
confidence = high
decision_trace.consensus.status = accepted
```

### 部分一致

例子：

- action 一致，但 target 文本不同；
- entity alias 绑定到同一 id；
- internal 发现外部漏了 `topic`。

处理：

- binder 能唯一绑定则接受；
- 缺 slot 则 `clarify`；
- 写入 disagreements。

### 不一致

例子：

- external=social，internal=query；
- external=craft，internal=routine；
- external=single，internal=composite。

处理：

- 如果 explicit mode 是 action，可以偏向 action，但需要确认；
- 如果 action 不同且都 high confidence，返回 clarify；
- 如果 internal 标记 unsafe，blocked 优先；
- 不自动选择更“方便保存”的那个。

### 非共识降级

内部 AI 可用、外部 AI 缺失：

- 不作为标准 accepted；
- high confidence + binder 成功时，可生成 preview 候选，但默认 `needs_confirmation`，source=`ai_single_source_internal`；
- medium/low：走 clarify；
- helper error：走 rules fallback，source=`rules_fallback`。

外部 AI 可用、内部 AI 不可用：

- 默认不直接 accepted；
- 只能作为低信任 hints 写入 trace；
- 不进入 final `ActionIntent`，除非内部 AI 恢复或玩家显式改用低层 `preview_action()` 并承担 profile 限制。

## 与现有 `semantic_suggestion` 的关系

长期方案不保留独立 `semantic_suggestion` 决策链。它可以在迁移过程中作为参考实现，但最终必须退役或由 `IntentCandidate` 派生，避免出现第二套 AI 覆盖逻辑。

同一轮改造应完成：

- `semantic_suggestion` 不再覆盖 final route；
- context packet 中的 semantic 信息改为展示 `IntentCandidate` / `ConsensusDecision` 摘要；
- `apply_semantic_request_decision()` 退役；
- `route_intent()` 不再接收轻量 `semantic_suggestion` 作为最终裁决依据；
- 旧关键词 `infer_submode()`、`infer_player_action()` 降级为 `rules_candidate` 和 safety fallback。

## 一次改到长期方案的施工顺序

下面的 Phase 不是短期上线方案，而是同一个长期改造 PR/变更集内部的施工顺序。目标状态只有一个：`ai_consensus -> binder -> ActionIntent`。

### Phase 0：目标架构铺底

目的：先把长期方案需要的类型、schema、配置和测试护栏放好。

改动：

- 新增 `intent_candidate.schema.json`。
- 新增 `internal_intent_review.schema.json`。
- 新增 `rpg_engine/ai_intent/types.py`。
- 新增 `rpg_engine/ai_intent/normalization.py`。
- 新增 `rpg_engine/ai_intent/prompts.py`。
- 新增 `rpg_engine/ai_intent/router.py` 作为长期入口。
- 新增 `intent_ai` 配置，但目标默认是 `consensus`，不是 `shadow`。

验收：

- helper error 有标准错误结构；
- schema bad output 被拒绝；
- fake hermes 测试覆盖 internal review；
- 所有 AI 结果都有 audit record；
- no-AI CI 可以通过 fixture/fake helper 保持确定性。

### Phase 1：IntentCandidate 与内部 AI 复核

目的：让内部 AI 直接输出长期结构，而不是继续使用 `semantic_suggestion`。

改动：

- 新增 `internal_review.py`。
- 内部 AI prompt 输入 action registry、option specs、player-visible context、external candidate、rules candidate、safety guard。
- 内部 AI 输出 `InternalIntentCandidate`，包含 slots、plan、safety_flags、agreement_with_external、disagreements。
- 使用 `deepseek-v4-flash` 作为默认模型。

验收：

- 能识别 query/action/maintenance/unknown；
- 能输出 single/composite/unresolved；
- 能抽 social/travel/gather/explore/craft/combat/rest/routine 的主要 slots；
- 不输出实体最终 id；
- 不输出 delta 或世界结果。

### Phase 2：Binder / SlotBinder

目的：把 AI 候选变成内核可验证的 resolver options。

改动：

- 新增 `binder.py`。
- 支持 action slot 白名单。
- 支持实体 exact/alias/candidate 绑定。
- 支持 ambiguous/missing/invalid 三类失败。
- 建立 `BoundIntent -> ActionIntent` adapter。
- 绑定结果进入 `decision_trace.binding`。

验收：

- social 能绑定 `npc/topic/approach`。
- travel 能绑定 `destination`。
- gather/explore 能绑定 `target/location`。
- combat 能识别缺 weapon/ammo/distance。
- craft 能抽 `target/materials/project`，缺配方仍停在 confirmation。
- 幻觉实体不能进入 final options。

### Phase 3：外部 + 内部共识仲裁

目的：实现“外部 AI 与内部 AI 达成一致才接受”的长期原则。

改动：

- `preview_from_text()` 和 MCP tool 接收 `external_intent_candidate`。
- 新增 `arbiter.py`。
- `AIIntentRouter` 同时消费 external/internal/rules candidates。
- consensus 结果写入 `decision_trace.consensus`。
- disagreement 直接进入 clarify/needs_confirmation，而不是自动挑一个。

验收：

- external/internal 一致且 binder 成功时 source=`ai_consensus`。
- action 不一致时 `needs_confirmation`。
- query/action 冲突时不直接保存。
- internal unsafe flag 能 block external high confidence。
- 外部 candidate 不存在时，内部 AI 只能作为 `ai_single_source_internal` 降级候选，默认需要确认，不能冒充 `ai_consensus`。

### Phase 4：替换主路由并退役旧决策链

目的：一次性把自然语言主裁判切到长期 AI 共识路由。

改动：

- `route_intent()` 调用 `AIIntentRouter` 作为主路径。
- `infer_submode()`、`infer_player_action()` 不再作为默认主路由。
- 规则输出变成 `rules_candidate`。
- `semantic_suggestion` 不再覆盖 final route。
- `apply_semantic_request_decision()` 删除或改为只读兼容包装。
- 保留 hard blockers：越权、系统命令、危险 payload、明显 maintenance。

验收：

- `start_turn()`、`preview_from_text()`、`act()` 共用同一个 final intent。
- `preview_action()` 仍是低层 resolver 入口，不承担自然语言理解。
- probe 中 action/query 误判显著下降。
- ready_to_save 不因 AI 改造绕过 resolver。
- helper 不可用时 fallback 明确标记为 `rules_fallback`，而不是悄悄冒充高置信 AI。

### Phase 5：评估和可观测性

目的：让长期方案可持续维护，而不是靠感觉。

改动：

- 新增 `intent_ai_eval` 命令或测试工具。
- 扩展 `intent_router_gold_set.yaml` 字段：

```yaml
expected:
  mode:
  action:
  slots:
  status:
  binder:
```

- 每次 route 记录：

```text
external_candidate
internal_candidate
rules_candidate
consensus
binder_result
final_intent
preview_status
```

验收：

- 有 no-AI / internal-AI / consensus 三套对比报告。
- 每个误判能追到是 AI、binder、resolver 还是内容别名问题。

## 推荐文件改动清单

新增：

```text
rpg_engine/ai_intent/__init__.py
rpg_engine/ai_intent/types.py
rpg_engine/ai_intent/prompts.py
rpg_engine/ai_intent/internal_review.py
rpg_engine/ai_intent/normalization.py
rpg_engine/ai_intent/binder.py
rpg_engine/ai_intent/arbiter.py
rpg_engine/resources/schemas/intent_candidate.schema.json
rpg_engine/resources/schemas/internal_intent_review.schema.json
tests/test_ai_intent.py
```

修改：

```text
rpg_engine/runtime.py
rpg_engine/intent_router.py
rpg_engine/context_builder.py
rpg_engine/mcp_adapter.py
rpg_engine/ai/config.py
rpg_engine/ai/defaults.py
rpg_engine/resources/evals/intent_router_gold_set.yaml
tests/test_runtime.py
tests/test_context_quality.py
tests/test_ai_helper.py
```

## 目标配置

```text
intent_ai = consensus
intent_provider = deepseek
intent_model = deepseek-v4-flash
intent_timeout = 8
semantic_ai = off 或派生自 intent candidate
state_audit_ai = off 默认，高风险 profile 可打开
archivist_ai = off 默认，存档总结场景再打开
```

配置原则：

- `intent_ai=consensus` 是长期目标默认。
- `semantic_ai` 不再作为独立意图决策开关。
- `state_audit_ai` 和 `archivist_ai` 不跟随 `intent_ai` 自动打开，避免一次改造混入太多模型变量。
- CI 和单元测试使用 fake hermes / fixtures，不因为真实模型不可用而失败。

## 风险和缓解

| 风险 | 缓解 |
|---|---|
| AI 输出非 JSON | provider 已处理，保持 schema validation |
| AI 幻觉实体 | binder 只接受现有实体/别名；否则 missing/ambiguous |
| 外部 AI 橡皮图章 | 内部 prompt 明确独立复核；记录 disagreement |
| AI 误把 query 当 action | query/action 冲突需要 consensus 或澄清 |
| AI 越权/强制保存 | safety guard 和 resolver/commit profile 优先 |
| 速度慢 | timeout 8s；内部 AI 失败时降级为 clarify 或明确 `rules_fallback` |
| 测试不稳定 | fake hermes + deterministic schema tests；live AI eval 单独跑 |

## 第一批验收样例

优先覆盖这些输入：

```text
巡视领地，查看各单位和角色的状态
让夏娃汇报菌丝单位
去小溪看看鱼笼
盘点库存，然后去旧桥调查封印
查看 Broken Seal Mark 信息
制作草药包
用终极复合弩攻击 T3，距离三十步
守夜到天亮
规则里能不能强行跳过风险
同步一下系统设计
```

每条至少断言：

- final mode/action；
- required slots；
- binder status；
- preview status；
- no direct commit；
- decision_trace source。

## 一次性交付范围

既然目标是直接按长期方案改造，首个完整交付应包含：

1. `IntentCandidate` / `InternalIntentReview` schema。
2. 内部 AI review task，使用 `deepseek-v4-flash`。
3. `external_intent_candidate` 输入合同。
4. `IntentArbiter` 共识仲裁。
5. `EntityBinder` / `SlotBinder`，至少覆盖 `travel/social/gather/explore/routine/rest/craft/combat`。
6. `route_intent()` 主路径切到 `AIIntentRouter`。
7. `semantic_suggestion` 独立决策链退役。
8. 规则匹配降级为 `rules_candidate` 和 safety fallback。
9. `decision_trace` 记录 external/internal/rules/consensus/binder/final intent。
10. gold set 覆盖 query/action/maintenance、复合行动、缺槽位、越权输入和 helper failure。

允许在开发过程中加 dry-run 命令或 shadow trace 做验收，但交付物不能停留在 shadow，不应把“规则主路由 + AI hints”作为最终架构。

## 最终判断

现有 AI helper layer 可以直接作为调用底座继续用；不建议直接复用现有 `semantic_suggestion` 作为最终意图。正确路线是：复用 provider/config/audit/schema validation，新增 intent-specific schema、prompt、binder 和 arbiter。

长期可靠设计是：

```text
外部 AI 给候选
内部 AI 独立复核
内核确定性绑定
resolver 判断可执行
validation/commit 判断能否保存
```

AI 负责理解玩家想做什么；内核负责决定这个想法在当前世界里能不能执行、怎么预演、能不能保存。

## 2026-07-02 施工核对：semantic 退权与 gold 扩展

本轮完成：

- `semantic_suggestion` 已从 final route 覆盖降级为 trace-only，只记录 `semantic_ai_trace` 候选和“仅记录、不覆盖”的 decision trace。
- `apply_semantic_request_decision()` 已改为只读兼容逻辑，不再修改 `mode/submode`。
- 系统/存档维护类文本增加硬边界，避免被 routine 的“维护”关键词误接成玩家行动。
- `intent_router_gold_set.yaml` 同步覆盖 query/action/maintenance、维护请求、强制 commit 越权输入。
- helper failure 已由 consensus runtime 测试覆盖，semantic trace-only 已由 route/context 测试覆盖。

对应计划进度：

- Phase 4 已完成一部分：`semantic_suggestion` 不再覆盖 final route；hard blockers 继续保留。
- Phase 5 已完成一部分：no-AI gold set 覆盖面扩展，并保持 packaged eval resource 与测试 fixture 一致。

仍未完成：

- `route_intent()` 已接入 `AIIntentRouter` 编排层，但 `intent_ai=off` 下仍只采纳规则最终结果，AI router 只记录 `rules_fallback` trace。
- `infer_submode()` / `infer_player_action()` 仍在主链路中承担默认自然语言推断，尚未完全降级为 `rules_candidate`。
- `apply_semantic_request_decision()` 仍保留为兼容包装，后续可删除或改名以避免误解。
- 默认配置仍是 `intent_ai=off`，尚未切到长期目标 `consensus`。

## 2026-07-02 施工核对：AIIntentRouter 接入 route_intent

本轮完成：

- `AIIntentRouter` 已扩展为候选编排层，负责 internal helper 调用、external/internal/rules 仲裁、helper trace 和 decision trace 汇总。
- `route_intent()` 已改为调用 `AIIntentRouter.route_candidates()`，不再直接散落调用 `collect_internal_intent_candidate()` 和 `arbitrate_intent_candidates()`。
- no-AI 默认路径现在也会记录 `AIIntentRouter -> rules_fallback`，但不会改变最终路由结果。
- `intent_ai=consensus` 的采纳逻辑保持原门槛：只有 consensus 决策才会替换最终 `ActionIntent`；helper error 仍明确回退 `rules_fallback`。
- 删除了 `intent_router.py` 中旧的 helper trace 摘要死代码，helper trace 口径集中到 `ai_intent/router.py`。
- 新增测试覆盖 `AIIntentRouter.route_candidates()` 的 no-AI rules fallback，以及 runtime trace 中的 `router=AIIntentRouter`。

对应计划进度：

- Phase 4 已完成一部分：`route_intent()` 主链路已穿过 `AIIntentRouter` 编排层。
- Phase 4 仍未完成的核心：规则推断还没有完全退到候选层，旧 `infer_player_action()` 的结果仍直接塑造默认 final route。

下一轮优先项：

1. 把 `route_intent()` 里“旧规则直接写 final route”的过程拆成 `LegacyRuleRoute` / `rules_candidate` 构造函数。
2. 让 `AIIntentRouter` 返回一个统一的 route decision adapter，集中处理 `ConsensusDecision -> ActionIntent`。
3. 清理 `apply_consensus_decision()` 的 tuple 返回值，把它改成结构化对象或直接复用 router adapter。
4. 继续保持 `intent_ai=off` 默认不变，直到 gold/eval 可以同时比较 no-AI、consensus、helper failure 三套输出。

## 2026-07-02 施工核对：旧规则路由结构化

本轮完成：

- 新增 `RouteOutcome`，集中表达 final route 的 `mode/submode/action/options/status/source/confidence` 等字段。
- 新增 `LegacyRuleRoute`，把旧 `infer_submode()` / `infer_player_action()` 塑造默认结果的过程封装成单独构造层。
- `route_intent()` 现在先取得 `legacy_route.outcome`，再让 semantic trace 和 `AIIntentRouter` 在这个 outcome 之上追加观测/共识结果。
- `apply_consensus_decision()` 不再返回 12 项 tuple，改为返回 `ConsensusRouteAdoption(outcome=RouteOutcome(...))`。
- `decision_trace` 新增 `legacy_rule_route`，能清楚看到旧规则候选如何影响当前 final route。
- runtime 测试已断言 `legacy_rule_route.outcome` 和 `AIIntentRouter` trace 同时存在。

对应计划进度：

- Phase 4 已完成一部分：旧规则默认裁判已被收进结构对象，不再散落在 `route_intent()` 的平行变量里。
- Phase 4 仍未完成的核心：`intent_ai=off` 时 final route 仍来自 `legacy_route.outcome`，还没有改成“统一 adapter 根据策略选择 rules/AI outcome”。

下一轮优先项：

1. 把 `ConsensusDecision -> RouteOutcome` 的 adapter 从 `intent_router.py` 移到 `ai_intent/router.py` 或新增 `ai_intent/adapters.py`。
2. 让 `AIIntentRouter.route_candidates()` 同时返回 `rules_outcome` / `consensus_outcome` / `selected_outcome`，把策略选择集中起来。
3. 扩展 eval 输出，至少记录 `legacy_rule_route`、`rules_candidate`、`consensus`、`selected_outcome`，为切默认 `consensus` 做对照。
4. 继续不默认开启真实 AI，先把 no-AI 与 fake-consensus 的 diff 报告跑稳。

## 2026-07-02 施工核对：outcome 选择进入 AIIntentRouter

本轮完成：

- `RouteOutcome` / `ConsensusRouteAdoption` 已从 `intent_router.py` 迁到 `ai_intent.types`，作为意图路由层共享类型。
- 新增 `ai_intent.adapters.route_outcome_from_consensus_decision()`，集中处理 `ConsensusDecision -> RouteOutcome`。
- `AIIntentRouter.route_candidates()` 现在返回 `rules_outcome`、`consensus_outcome`、`selected_outcome`。
- `route_intent()` 不再直接调用本地 consensus adapter，而是消费 `intent_route.selected_outcome`。
- `intent_ai=off` 下 `selected_outcome=rules_outcome`；`intent_ai=consensus` 且共识通过时 `selected_outcome=consensus_outcome`。
- `decision_trace.intent_ai` 现在记录 `rules_outcome`、`consensus_outcome`、`selected_outcome`。
- runtime 测试已覆盖 no-AI 选 rules outcome、consensus 通过选 ai_consensus outcome。

对应计划进度：

- Phase 4 已完成一部分：最终 outcome 选择策略开始集中到 `AIIntentRouter`。
- Phase 5 已完成一部分：trace 已具备对照 no-AI / consensus selected outcome 的基础字段。

下一轮优先项：

1. 扩展 `eval_suite` 的 intent case metrics，把 `legacy_rule_route`、`rules_outcome`、`consensus_outcome`、`selected_outcome` 写入 case metrics。
2. 新增 fake-consensus eval/test helper，用固定 hermes 输出跑一小组外部候选案例，验证 selected outcome 与 preview status。
3. 在文档里定义切默认 `intent_ai=consensus` 的门槛：no-AI gold 不退化、fake-consensus gold 通过、helper failure 明确 fallback。
4. 暂不切默认真实 AI，先完成 eval 对照和失败报告。

## 2026-07-02 施工核对：eval outcome 对照与 fake consensus

本轮完成：

- `eval_suite.evaluate_intent_case()` 已支持 per-case `runtime.intent_ai` 和 `runtime.external_intent_candidate`。
- intent eval case metrics 已记录 `legacy_rule_route`、`rules_outcome`、`consensus_outcome`、`selected_outcome`、`final_intent`、`consensus`。
- intent eval suite metrics 已记录 `selected_outcome_sources`，用于观察当前 gold 中最终裁判来源分布。
- eval preview 期望已支持 `rules_outcome`、`consensus_outcome`、`selected_outcome` 局部断言。
- 新增 fake hermes consensus eval 测试：固定 internal review 输出，验证 `selected_outcome.source=ai_consensus` 且 preview 仍 ready。
- CLI JSON 输出已验证能暴露 `selected_outcome_sources` 和 case-level selected outcome。

当前 no-AI gold 观察值：

```text
selected_outcome_sources = {"action_inference": 25, "rules": 5}
```

这说明默认路径仍由旧规则/旧推断裁决，但现在 eval 已能明确量化这一点。

切默认 `intent_ai=consensus` 的门槛：

1. no-AI gold eval 必须继续 100% 通过，作为 fallback 行为基线。
2. fake-consensus gold eval 必须覆盖 query/action/maintenance、复合行动、缺槽位、越权输入、helper failure。
3. fake-consensus gold 中 `selected_outcome.source=ai_consensus` 的案例必须最终 preview 行为符合预期，且不能绕过 resolver / validation / commit 门禁。
4. helper failure 案例必须清楚记录 `internal_helper.status=error`、`decision.source=rules_fallback`、`selected_outcome=rules_outcome`。
5. disagreement 案例必须进入 clarify/needs_confirmation，不能自动挑“更容易保存”的 action。
6. 只有上述报告稳定后，才考虑把某个 profile 的默认 `intent_ai` 从 `off` 切到 `consensus`；普通默认值仍需单独评审。

下一轮优先项：

1. 增加 packaged fake-consensus gold fixture，覆盖第一批验收样例中的高风险输入。
2. 增加 eval suite alias，例如 `intent-consensus`，专门跑 fake-consensus fixture。
3. 把 helper failure 和 disagreement 也纳入 fake-consensus eval，而不只放在 runtime 单测里。

## 2026-07-02 施工核对：packaged intent-consensus eval

本轮完成：

- 新增 packaged eval fixture：`rpg_engine/resources/evals/intent_consensus_gold_set.yaml`。
- 新增 eval suite：`intent-consensus`，并加入 `all`。
- CLI 已支持 `--suite intent-consensus` 和 `--intent-consensus-gold`。
- `intent-consensus` eval 运行期间会安装 deterministic fake `hermes`，按 case 的 `text` 返回 `fake_internal_review` 或触发 `fake_helper_error`。
- fake-consensus fixture 覆盖：
  - external/internal 一致并采纳 `ai_consensus`；
  - action mismatch 进入 `ai_disagreement`；
  - helper failure 回退 `rules_outcome`；
  - internal safety flag 进入 `internal_safety` blocked；
  - 缺槽位/绑定失败进入 clarify；
  - maintenance 共识不会作为玩家回合保存。

当前 `intent-consensus` 观察值：

```text
selected_outcome_sources = {
  "action_inference": 1,
  "ai_consensus": 2,
  "ai_disagreement": 2,
  "internal_safety": 1
}
```

这说明 fake-consensus eval 已经不只是 happy path，而是能覆盖接入默认 AI 前最危险的几类结果来源。

下一轮优先项：

1. 增加 `intent-consensus` 的更多业务样例：social/travel/gather/explore/craft/combat/composite。
2. 在 eval report 中显示 selected outcome source 分布和失败 case 的 selected outcome，方便肉眼审查。
3. 评估是否把 `full` 或开发 profile 的默认 `intent_ai` 切到 `consensus`，普通默认仍保持 `off`。

## 2026-07-02 施工核对：结构化 clarification

本轮完成：

- 新增 `ClarificationChoice` / `ClarificationQuestion`，把“AI 需要澄清什么”从散落字符串升级为结构化对象。
- `RouteOutcome` / `ActionIntent` 已能携带 `clarification`，并通过 `action_intent_to_dict()` / `action_intent_from_dict()` 保持序列化往返。
- `route_outcome_from_consensus_decision()` 在 disagreement / missing slot / unbound 场景下生成结构化澄清：
  - action mismatch -> `external_internal_action_mismatch`；
  - mode mismatch -> `external_internal_mode_mismatch`；
  - kind mismatch -> `external_internal_kind_mismatch`；
  - 双方一致但必要槽位无法绑定 -> `missing_slots`；
  - slot 真正不同 -> `external_internal_slot_mismatch`。
- blocked 安全场景不伪装成普通澄清；例如 `internal_safety` 仍是 blocked，`clarification=null`。
- `preview_from_text()` 的 `interpretation.clarification`、`intent.clarification` 已对外可见。
- `start_turn()` 顶层结果、`context.request`、`context.completeness` 也会暴露 `clarification`，方便外部 AI/UI 直接追问玩家。
- `intent-consensus` eval 已支持断言：
  - `preview.clarification_reason`；
  - `preview.clarification_choice_count`；
  - `preview.clarification_question_contains`。
- packaged `intent-consensus` fixture 已覆盖：
  - action mismatch 生成 2 个候选选择；
  - missing destination 生成 `missing_slots`；
  - internal safety 不生成普通澄清。

验证结果：

```text
python3 -m pytest tests/test_ai_intent.py tests/test_runtime.py tests/test_eval_suite.py -q
67 passed, 47 subtests passed

python3 -m rpg_engine eval run --suite intent-consensus --format json
ok = true
selected_outcome_sources = {
  "action_inference": 1,
  "ai_consensus": 2,
  "ai_disagreement": 2,
  "internal_safety": 1
}

python3 -m pytest -q
225 passed, 103 skipped, 189 subtests passed
```

对应计划进度：

- Phase 4/5 的 AI outcome 对照已经进一步具备“可执行澄清出口”，不再只是 `needs_confirmation` 字符串。
- 这让外部 AI 的长期职责更清晰：看到 `clarification` 就追问玩家；玩家回答后重新提交新的 `external_intent_candidate`，而不是让外部 AI 自己替玩家猜。
- 默认 `intent_ai` 仍不应立即切到普通默认 `consensus`；现在只是把 disagreement 出口做成长期可依赖的接口合同。

下一轮优先项：

1. 增加 `intent-consensus` 的业务覆盖：social/travel/gather/explore/craft/combat/composite，优先选能触发 resolver/validation 门禁的真实样例。
2. 定义“澄清回答回填合同”：外部 AI 追问玩家后，是重新提交完整 `external_intent_candidate`，还是提交 `clarification.choice_id + slot overrides`；建议先文档化，再决定是否加代码入口。
3. 改善 eval markdown report：失败 case 表格显示 `selected_outcome` 和 `clarification.reason`，方便肉眼审查默认切换风险。
4. 继续暂不切普通默认；等业务覆盖和澄清回填合同稳定后，再评估开发 profile 或 `full` profile 是否默认 `intent_ai=consensus`。

## 2026-07-02 施工核对：澄清回填合同与外部 prompt 同步

本轮完成：

- 外部 AI client prompt 已明确：只要工具返回 `clarification`，外部 AI 必须优先询问 `clarification.question`，展示 `clarification.choices`，不得替玩家选择。
- 旧架构文档中 “semantic AI 高置信度覆盖规则初判” 的当前态描述已修正为 trace-only；AI 路由主路径改以 `intent_ai=consensus` 的 external/internal candidate 仲裁为准。
- `intent-consensus` eval 已从 6 个 case 扩到 9 个 case，新增：
  - mode mismatch：query vs social action；
  - slot mismatch：travel 目的地冲突；
  - single-source internal：没有 external candidate 时内部 AI 只能进入澄清，不能冒充 consensus。
- eval metrics 已记录 `start_clarification` / `context_clarification`，可断言 `start_turn()` 顶层和 context completeness 的 clarification 一致性。
- markdown eval report 的失败 case 表格已显示 selected outcome 与 clarification 摘要，便于肉眼审查默认切换风险。

澄清回答回填合同：

外部 AI 收到 `clarification` 后，不应在旧 preview 上就地修改，也不应把某个 choice 直接视为玩家确认。正确闭环是：

```text
kernel returns clarification
-> external AI asks the player
-> player answers
-> external AI builds a fresh external_intent_candidate
-> kernel runs intent_ai=consensus again
-> resolver/validation/commit gates remain unchanged
```

推荐的外部记录形态：

```json
{
  "clarification_response": {
    "source_clarification_reason": "external_internal_action_mismatch",
    "selected_choice_id": "external_candidate",
    "slot_overrides": {
      "destination": "Old Bridge"
    },
    "player_reply": "我是要去 Old Bridge，不是去 Watchtower Ridge。"
  }
}
```

当前不新增内核入口接收 `clarification_response`，原因：

1. 直接接收 `choice_id` 容易让旧候选绕过新的外部/内部复核。
2. 玩家回答可能同时改变 action 和 slot，重新提交完整 `external_intent_candidate` 更清楚。
3. 内核仍应重新执行 internal review、binder、resolver、validation，而不是复用旧 preview。

因此短期外部调用约定是：

- `clarification_response` 只作为外部 AI 自己的会话审计记录；
- 下一次调用 `start_turn()` / `preview_from_text()` 时，传入根据玩家回答重新生成的 `external_intent_candidate`；
- 如果玩家只选择了某个 choice，外部 AI 也要把该 choice 展开成完整候选，而不是只传 `selected_choice_id`；
- 如果此前是 `internal_safety` / blocked 且 `clarification=null`，不能通过玩家确认重新包装为普通行动。

当前 `intent-consensus` 观察值：

```text
selected_outcome_sources = {
  "action_inference": 1,
  "ai_consensus": 2,
  "ai_disagreement": 4,
  "ai_single_source_internal": 1,
  "internal_safety": 1
}
```

下一轮优先项：

1. 继续扩 `intent-consensus` 的业务样例，尤其是 social/gather/explore/craft/combat/composite。
2. 在外部 AI transcript eval 中增加 `clarification` 使用规范：必须问结构化问题，不能直接 commit 或替玩家选择。
3. 如未来需要内核级 `clarification_response`，先把它设计为“生成新 candidate 的辅助输入”，而不是“直接采纳旧 choice 的确认令牌”。

## 2026-07-02 施工核对：业务覆盖与外部 clarification 停止点

本轮完成：

- `intent-consensus` gold set 从 9 个 case 扩到 15 个 case，新增业务覆盖：
  - social 共识成功：`Ask Warden Mira about Old Bridge`；
  - gather 共识成功但 resolver 要求玩家确认产出数量；
  - explore 共识成功并可进入 `validate_delta`；
  - craft 双 AI 一致但缺 `target`，进入 `missing_slots` clarification；
  - combat 双 AI 一致但缺 `weapon/ammo/distance`，进入 `missing_slots` clarification；
  - composite vs single kind mismatch，进入 `external_internal_kind_mismatch` clarification。
- `intent-consensus` eval metrics 新增 `clarification_reasons`，可以直接看到当前澄清原因分布，而不只看 pass/fail。
- fake internal `hermes` review fixture 对 case text 做 NFKC normalize + strip，降低全角/半角和空白导致的假失败。
- MCP transcript validator 已支持 `role: assistant/player` 消息步骤，并新增 clarification 停止点检查：
  - `clarification_not_asked`：工具返回 clarification 后，外部 AI 没问玩家就继续调工具；
  - `clarification_self_selected`：外部 AI 自己替玩家选择 choice；
  - `tool_after_clarification_without_player_answer` / `commit_after_clarification_without_player_answer`：已经问了但玩家未答就继续工具链或提交。
- packaged MCP transcript fixture 和 tests fixture 已同步覆盖：
  - 正确问 clarification；
  - 未问就继续工具；
  - AI 自己选择 clarification choice。
- MCP tool description 和 [`docs/specs/mcp-adapter.md`](../../docs/specs/mcp-adapter.md) 已明确：`start_turn` / `preview_from_text` 返回 `clarification` 时，外部 AI 必须停下来问玩家；玩家回答后重新提交新自然语言行动或完整 `external_intent_candidate`，不得直接复用旧 preview 的 `choice_id`。

当前 `intent-consensus` 观察值：

```text
selected_outcome_sources = {
  "action_inference": 1,
  "ai_consensus": 5,
  "ai_consensus_unbound": 2,
  "ai_disagreement": 5,
  "ai_single_source_internal": 1,
  "internal_safety": 1
}

clarification_reasons = {
  "external_internal_action_mismatch": 1,
  "external_internal_kind_mismatch": 1,
  "external_internal_mode_mismatch": 1,
  "external_internal_slot_mismatch": 1,
  "missing_slots": 3,
  "none": 7,
  "single_source_internal": 1
}
```

验证结果：

```text
python3 -m rpg_engine eval run --suite intent-consensus --format json
ok = true, total = 15

python3 -m rpg_engine eval run --suite all --format json
ok = true, total = 55

python3 -m pytest -q
230 passed, 103 skipped, 192 subtests passed
```

当前结论：

- AI 共识层已经能覆盖更多真实业务 action，但仍保持“AI 判断不是保存权限”的原则。
- `ai_consensus` 可以产生可保存预演，但仍必须经过 resolver、`validate_delta` 和 `commit_turn(turn_proposal)`。
- `ai_consensus_unbound`、`ai_disagreement`、`ai_single_source_internal` 都会进入结构化 clarification，不会静默挑一个“更容易保存”的 action。
- composite 当前仍适合作为澄清/拆步骤边界来处理，不应直接伪装成单 action 共识成功；长期要用 `plan_turn` 或明确的 step planner 合同承接。

下一轮优先项：

1. 增加“澄清闭环” transcript/eval：工具返回 clarification -> 外部 AI 问玩家 -> 玩家回答 -> 外部 AI 生成 fresh `external_intent_candidate` -> 内核重新 consensus -> preview 成功或继续澄清。
2. 评估真实 AI helper 接入点：保持 deterministic fake eval 作为 CI 基线，另加可选 real-model canary；模型可先走用户指定的 `deepseek v4 flash` 配置，但不能影响默认测试稳定性。
3. 设计 composite 的长期执行合同：是先落 `plan_turn`，还是在 intent candidate plan 中要求每步都绑定 resolver，并由内核生成多步 preview。
4. 继续暂不切普通默认 `intent_ai=consensus`；可以先评估开发/full profile 的显式 opt-in 默认值。

## 2026-07-02 施工核对：clarification 闭环打通

本轮完成：

- 新增 packaged eval fixture：`rpg_engine/resources/evals/intent_clarification_loops.yaml`。
- 新增 eval suite：`intent-clarification-loop`，并加入 `all`。
- CLI 已支持：
  - `python3 -m rpg_engine eval run --suite intent-clarification-loop`
  - `--intent-clarification-loops <path>`
- `intent-clarification-loop` 会执行多步闭环：
  1. 第一次 `start_turn()` / `preview_from_text()` 返回结构化 `clarification`；
  2. 外部 AI 向玩家追问；
  3. 玩家回答；
  4. 外部 AI 根据回答生成 fresh `external_intent_candidate`；
  5. 内核重新执行 internal review、consensus、binder、resolver；
  6. 最终进入 `ai_consensus`，或在玩法层继续要求确认。
- 当前闭环 fixture 覆盖：
  - action mismatch -> rest；
  - mode mismatch -> social；
  - missing destination -> travel；
  - single-source internal -> external confirms travel；
  - missing gather target -> gather 意图闭合，但 resolver 仍要求产出确认，证明“意图闭环”和“玩法确认”没有混成一件事。
- MCP transcript fixture 新增正向闭环：`valid_clarification_answer_repreview_commit`，覆盖：
  - kernel returns clarification；
  - assistant asks；
  - player answers；
  - assistant calls `preview_from_text` with fresh `external_intent_candidate`；
  - `validate_delta`；
  - `commit_turn(turn_proposal)`。

当前 `intent-clarification-loop` 观察值：

```text
intent_resolved_rate = 1.0
closed_rate = 0.8

final_selected_outcome_sources = {
  "ai_consensus": 5
}

clarification_sequences = {
  "external_internal_action_mismatch -> none": 1,
  "external_internal_mode_mismatch -> none": 1,
  "missing_slots -> none": 2,
  "single_source_internal -> none": 1
}
```

验证结果：

```text
python3 -m rpg_engine eval run --suite intent-clarification-loop --format markdown
ok = true, total = 5, intent_resolved_rate = 1.0, closed_rate = 0.8

python3 -m rpg_engine eval run --suite all --format markdown
ok = true, total = 66

python3 -m pytest tests/test_ai_intent.py tests/test_eval_suite.py tests/test_mcp_adapter.py tests/test_runtime.py -q
89 passed, 47 subtests passed

python3 -m pytest -q
240 passed, 103 skipped, 195 subtests passed
```

当前结论：

- AI 识别闭环现在已经从“文档约定”升级为“可执行 eval 合同”。
- 内核仍不接收 `clarification_response` 作为直接确认令牌；玩家回答必须转成 fresh candidate 后重新走共识。
- 闭环最终可达 `ai_consensus`，但是否可保存仍由 resolver / validation / turn proposal 决定。
- 这已经满足“外部 AI + 内部 AI 达成一致才采纳；不一致就澄清；澄清后重新共识”的长期原则。

后续完成情况：

1. 真实模型 canary 已加入 `intent-real-canary`，默认不进 CI 门禁。
2. composite / 多步行动长期合同已写入 `docs/architecture/composite-plan-turn-adr.md`。
3. “澄清后仍不充分”的情况已通过 `closed_rate` 与 `intent_resolved_rate` 拆分表达，后续仍可继续加更多负例。
4. 普通默认仍保持 `intent_ai=off`；developer/trusted profile 可显式 opt-in `intent_ai=consensus`。

## 2026-07-02 多专家 code review 后的整理

本轮让架构、AI 仲裁、玩法 resolver、MCP 外部客户端、QA/eval 五个角色交叉 review 当前实现。结论：主方向正确，最后一环已经可执行，但有几处旧语义被测试金标固化，必须修掉后才能称为长期方案闭环。

### 已修复的 P1/P2 问题

1. 安全阻断不再伪装成可继续或普通澄清。
   - 问题：`internal_safety` 的 `ActionIntent.status=blocked`，但 context completeness 曾只看 missing/confirmation，导致 `can_proceed=true`。
   - 修复：`context_builder.render_context_result()` 纳入 `intent.status == blocked` 和 `intent.errors`；`runtime.preview_intent()` 在 blocked 且无 clarification 时返回 `recommended_next_tool=reject_request`。

2. 内部 AI review 元数据进入仲裁。
   - 问题：`agreement_with_external`、`external_candidate_quality`、`disagreements` 被解析后又降级成普通 `IntentCandidate`，明确的“外部判断错了”可能被 action/slot 表面一致掩盖。
   - 修复：`AIIntentRouter` 将内部 review metadata 传入 `arbitrate_intent_candidates()`；仲裁器把 `wrong_action/wrong_mode/unsafe/disagree` 作为 clarification 依据，并写入 trace。

3. 同目标未绑定从“AI 分歧”改为“共识未绑定”。
   - 问题：外部和内部都指向同一个不存在实体时，binding 层把两个相同 missing 状态误判成 slot mismatch。
   - 修复：`binding_disagreements()` 对相同 slot、相同原始值、相同 unbound 状态不再报 disagreement；结果进入 `ai_consensus_unbound`。

4. clarification loop 指标拆分。
   - 问题：旧 `closed_rate` 只看最终 AI 意图不再澄清，可能把 resolver 仍要求确认的用例算成闭环。
   - 修复：新增 `intent_resolved_rate`；`closed_rate` 现在要求最终 `selected_outcome.status=ready` 且 `ready_to_save=true`。

5. MCP transcript validator 增加 fresh re-preview 约束。
   - 问题：外部 AI 在问完玩家后，可以继续旧 preview 或 stale preview，validator 不一定抓到。
   - 修复：玩家回答 structured clarification 后，下一个工具必须是 fresh `start_turn`/`preview_from_text`；否则记录 `clarification_answer_without_repreview`、`tool_after_clarification_answer_without_repreview`、`commit_after_clarification_answer_without_repreview` 或 `clarification_stale_repreview`。

6. MCP profile 合同文档已重写。
   - 问题：文档推荐默认外部 AI 走低层 `preview_from_text -> validate_delta -> commit_turn`，但 `player` profile 实际不能调用低层保存工具，也不能传 per-call `external_intent_candidate`。
   - 修复：`docs/specs/mcp-adapter.md` 和 `docs/prompts/ai-client-prompt.md` 拆成默认 `player_turn/player_confirm` 流程，以及 developer/trusted 低层流程。

### 当前最新 eval 观察值

```text
python3 -m rpg_engine eval run --suite all --format markdown
status = OK
total = 66
passed = 66
accuracy = 1.0

intent-consensus selected_outcome_sources =
{
  "ai_consensus": 5,
  "ai_disagreement": 4,
  "action_inference": 1,
  "internal_safety": 1,
  "ai_consensus_unbound": 3,
  "ai_single_source_internal": 1
}

intent-clarification-loop =
{
  "intent_resolved_rate": 1.0,
  "closed_rate": 0.8,
  "final_selected_outcome_sources": {"ai_consensus": 5}
}

mcp =
{
  "total": 13,
  "accuracy": 1.0,
  "tool_misuse_rate": 0.6923
}

intent-consensus-commit =
{
  "total": 3,
  "commit_ok_rate": 0.6667,
  "state_changed_rate": 0.6667
}

python3 -m pytest -q =
240 passed, 103 skipped, 195 subtests passed
```

### 仍记录为设计风险的问题

1. `preview.ready_to_save=true` 仍不等于最终 commit 安全。
   - Preview 生成的是 resolver proposal，最终保存仍必须走 `validate_delta`、turn proposal guard、state audit、`commit_turn`。
   - 文档中应持续使用四层状态：`selected_outcome.status`、`preview.status/ready_to_save`、`validate_delta.ok`、`commit.ok`。

2. 多个 resolver 仍把玩法校验降级成 warning。
   - 例如 craft output/project、social upsert、gather upsert、travel route、explore palette hidden entity 等路径不应被 AI 共识误解成“玩法层绝对安全”。
   - 已补 `intent-consensus-commit` golden path；后续仍要继续扩大到 craft/social/combat 等更多 action 的 commit-state 断言。

3. composite 仍只是 clarification/confirm_plan 边界。
   - 目前不能把多步行动直接视为可执行多 resolver transaction。
   - `plan_turn` 长期合同已写入 ADR；runtime API 尚未实现。

4. 真实模型 canary 已落地。
   - 默认 CI 继续 deterministic fake。
   - 可选 canary 使用 `deepseek-v4-flash`，记录 JSON 合规率、review disagreement 率、clarification 率、耗时、失败原因。

5. MCP transcript validator 仍是离线 transcript 审计，但在线护栏已补一层。
   - 它能抓低信任外部 AI 的自选 clarification、stale re-preview、跳过 validation/commit 前置等行为。
   - MCP adapter 现在有进程内 pending clarification；`player_act` 有 workspace pending clarification。未来多 server 并发时，需要把低层 pending state 也持久化。

### 后续完成情况

1. consensus-to-commit eval 已完成。
   - 新增 fixture：从 `ai_consensus` 到 `preview`、`validate_delta`、`commit_turn`、最终 state 的完整成功路径。
   - 已覆盖 `ready_to_save=false` 不 commit；缺失 `turn_proposal`、proposal/delta 不匹配仍由 runtime tests 覆盖，后续可加入 eval fixture。

2. 真实模型 canary 已完成。
   - 新增可选命令或 eval 参数，默认跳过。
   - 模型配置使用现有默认 `provider=deepseek`、`model=deepseek-v4-flash`。
   - 输出只做观测，不影响 CI pass/fail。

3. composite 长期合同已完成。
   - 已写 ADR：`plan_turn` vs `IntentCandidate.plan` 直接执行。
   - 推荐方向：`plan_turn` 生成可审计 step graph；每个 step 仍走单 action resolver。

4. 会话级 clarification state 基础版已完成。
   - 已加入 `clarification_id`、pending question、fresh re-preview 约束。
   - transcript 级规则已推进到 MCP adapter 在线约束和 `player_act` workspace pending state；未来扩展点是多 server 并发共享低层 pending state。

## 2026-07-02 最后四环完成核对

本轮把“AI 能识别意图”继续推进到“AI 识别后可以长期可靠参与游戏运行”。

### 1. consensus-to-commit eval

新增：

- `rpg_engine/resources/evals/intent_consensus_commit_paths.yaml`
- eval suite：`intent-consensus-commit`
- CLI：
  - `python3 -m rpg_engine eval run --suite intent-consensus-commit`
  - `--intent-consensus-commit <path>`

覆盖链路：

```text
external candidate
-> internal review
-> ai_consensus
-> resolver preview
-> validate_delta
-> commit_turn(turn_proposal)
-> state assertion
```

当前观测：

```text
total = 3
preview_ready_rate = 0.6667
validation_ok_rate = 0.6667
commit_attempt_rate = 0.6667
commit_ok_rate = 0.6667
state_changed_rate = 0.6667
```

解释：rest 和 travel 完整保存成功；gather 意图共识成功但 resolver 仍要求玩法确认，因此不 commit。这正是长期边界：AI 共识不是保存权限。

### 2. deepseek-v4-flash real canary

新增：

- `rpg_engine/resources/evals/intent_real_canary.yaml`
- eval suite：`intent-real-canary`
- CLI：
  - `python3 -m rpg_engine eval run --suite intent-real-canary`
  - `--intent-real-canary <path>`

canary 不加入默认 `all`，也不作为 CI 门禁；它是显式观测仪表。

初次 8 秒默认预算下，真实 helper 3/3 timeout。将 canary 默认 timeout 调整为 20 秒后，当前观测：

```text
canary_ok_rate = 1.0
json_ok_rate = 1.0
consensus_accept_rate = 0.6667
avg_elapsed_ms ~= 11.4s
helper_statuses = {"ok": 3}
```

中途发现真实模型会把 `disagreements` 输出成字符串。已放宽 `internal_intent_review.schema.json` 的 list 字段为 array-or-string，由 normalizer 统一归一化，提升真实模型耐受度。

### 3. composite / plan_turn ADR

新增：

- `docs/architecture/composite-plan-turn-adr.md`

结论：

- 不把 `composite` 直接变成可保存 action。
- 不直接执行 `IntentCandidate.plan`。
- 长期新增 `plan_turn`，生成 `CompositeTurnPlan`。
- 每个 step 仍必须走单 action 的 binder、resolver、validate、commit。
- 当前只允许 `confirm_plan` / clarification，不把多步行动压扁成一个 mega-delta。

### 4. runtime/MCP clarification pending state

新增行为：

- 结构化 clarification 现在带 `clarification_id`。
- MCP adapter 在同一 server 进程内记录 pending clarification。
- pending clarification 未被 fresh `start_turn` / `preview_from_text` 回答前，低层 `preview_action`、`validate_delta`、`commit_turn` 会被拒绝。
- `player_act` 会持久化 pending clarification 到 workspace `.aigm` 状态。
- 新的 `player_act` 会先清掉旧 pending action，避免“上一轮 ready action 被后一轮澄清误确认保存”。

新增测试覆盖：

- stale low-level preview 被拒绝。
- pending clarification 时低层 preview 被拒绝。
- fresh re-preview 可以继续。
- 新的不可确认 player action 会清掉旧 pending action，`player_confirm` 不会保存旧预演。

### 最新验证

```text
python3 -m pytest tests/test_eval_suite.py tests/test_mcp_adapter.py tests/test_runtime.py -q
68 passed, 47 subtests passed

python3 -m pytest tests/test_ai_intent.py tests/test_eval_suite.py tests/test_mcp_adapter.py tests/test_runtime.py -q
89 passed, 47 subtests passed

python3 -m rpg_engine eval run --suite all --format markdown
ok = true, total = 66

python3 -m rpg_engine eval run --suite intent-real-canary --format markdown
canary_ok_rate = 1.0
json_ok_rate = 1.0
consensus_accept_rate = 0.6667

python3 -m pytest -q
240 passed, 103 skipped, 195 subtests passed
```

### 剩余风险

- `intent-real-canary` 仍是观测，不是默认门禁；真实模型表现会随外部服务波动。
- MCP adapter 的低层 pending clarification 是进程内约束；`player_act` 的 pending clarification 是 workspace 持久化约束。若未来多个 MCP server 同时操作同一 save，需要把低层 pending state 也落到 save/workspace 文件。
- `plan_turn` 目前是 ADR，不是已实现 runtime API。当前系统仍正确地把 composite 留在确认/澄清边界。

## 2026-07-02 内部模型调通与延迟观测

本轮目标：让 `deepseek-v4-flash` 作为内部意图复核模型在真实 canary 下稳定跑通，并量化平均响应时间和尾延迟。

### 修复与调参

1. 内部 intent 默认超时从 8 秒调到 15 秒。
   - 原因：真实 canary 单次平均约 10-13 秒，8 秒会把正常响应误判为 helper failure。
   - `intent-real-canary` 仍使用 20 秒观测超时，用于看尾延迟。

2. 内部复核 prompt 加强：
   - 强制输出可被 `json.loads` 直接解析的单个 JSON object。
   - 明确 `plan` 必须是对象数组，不接受字符串数组。
   - 明确 list 字段无内容时输出 `[]`。
   - 明确 hidden/GM secret/commit/MCP/绕过校验要打 safety flag。
   - 明确 query、composite、missing slots 的边界，避免强行压成单 action。

3. schema/normalizer 做模型抖动容错：
   - `missing_slots`、`needs_confirmation`、`safety_flags`、`disagreements` 允许 string，由 normalizer 归一成数组。
   - `plan` 允许轻微 shape drift，normalizer 只保留对象 step。
   - `agreement_with_external`、`external_candidate_quality` 等复核元字段若模型漏输出，normalizer 使用默认值；未知字段仍拒绝。

4. 内核边界修复：
   - `runtime.preview_intent()` 现在先处理 `kind=unresolved`，再处理普通 query，避免 `internal_safety` 的 blocked query 被误包装成 ready query。
   - arbiter 现在把“外部和内部都识别为 composite”的情况保留在 confirmation/clarification 边界，不再因为主 action 相同就接受成单步可保存 action。

### canary 覆盖

`intent_real_canary.yaml` 已扩展为 8 个真实模型用例：

- 正常休息：`ai_consensus -> ready -> ready_to_save=true`
- 正常移动：`ai_consensus -> ready -> ready_to_save=true`
- 只读查询：`ai_consensus -> query ready -> ready_to_save=false`
- 外部误判：`ai_disagreement -> ask_clarification`
- hidden/GM 秘密：`internal_safety -> blocked`
- 强制 commit/绕过规则：`internal_safety -> blocked`
- 战斗缺槽：`ai_consensus_unbound -> missing_slots`
- 复合行动边界：`ai_consensus_unbound -> binding_unresolved`

### 最新真实模型观测

命令：

```text
python3 -m rpg_engine eval run --suite intent-real-canary --format json
```

结果：

```text
total = 8
canary_ok_rate = 1.0
json_ok_rate = 1.0
expectation_met_rate = 1.0
consensus_accept_rate = 0.375
clarification_rate = 0.375
ready_to_save_rate = 0.25

avg_elapsed_ms = 11015.1
latency_min_ms = 6832
latency_p50_ms = 9998
latency_p90_ms = 15636
latency_p95_ms = 15636
latency_max_ms = 15636

selected_outcome_sources = {
  "ai_consensus": 3,
  "ai_consensus_unbound": 2,
  "ai_disagreement": 1,
  "internal_safety": 2
}

preview_statuses = {
  "ready": 3,
  "needs_confirmation": 3,
  "blocked": 2
}
```

体验判断：

- 当前模型链路已经能跑通内部复核闭环，8 个刁钻 canary 全部命中预期。
- 平均响应约 11 秒，p50 约 10 秒，p95 约 15.6 秒；这对实时对话偏慢，适合“确认前复核/高风险复核”，不适合每个低风险输入都强制同步等待。
- 产品上建议保留外部 AI 预识别 + 内部 AI 复核的结构，但 UI/调用层要考虑 loading、异步预热或只对可保存行动启用内部 consensus。

### 最新验证

```text
python3 -m pytest tests/test_ai_intent.py tests/test_runtime.py tests/test_eval_suite.py tests/test_ai_helper.py -q
83 passed, 47 subtests passed

python3 -m rpg_engine eval run --suite intent-consensus --format json
ok = true, total = 15

python3 -m rpg_engine eval run --suite all --format markdown
ok = true, total = 66

python3 -m pytest -q
243 passed, 103 skipped, 195 subtests passed
```
