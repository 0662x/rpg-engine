# AI 共识意图识别设计备忘

背景：当前规则关键词路由在开放中文玩家输入上不可靠，不应继续把规则匹配作为主要意图裁判。长期方案应让 AI 承担自然语言理解，内核承担事实校验、槽位绑定、预演和保存门禁。

## 设计原则

外部 AI 和内部 AI 可以共同决定“玩家意图候选”，但最终 `ActionIntent` 必须由内核生成。

核心分工：

- 外部 AI：根据玩家原文和可见上下文输出 `ExternalIntentCandidate`。
- 内部 AI：在内核控制的提示、schema 和上下文下输出 `InternalIntentCandidate`。
- 规则匹配：降级为安全护栏和 fallback，不再主导开放文本意图识别。
- 内核 binder：确定性绑定实体和槽位，拒绝幻觉实体，生成唯一 `ActionIntent`。
- resolver/validation/commit：继续负责行动是否合法、delta 是否完整、是否允许保存。

## 共识规则

```text
外部 AI 与内部 AI 归一化后一致
  -> 接受为 ai_consensus
  -> 进入 EntityBinder / SlotBinder
  -> 生成 ActionIntent

外部 AI 与内部 AI 不一致
  -> 若只是别名差异，绑定到同一实体后接受
  -> 若 action 不同，返回 clarify 或进入仲裁
  -> 若 query/action 冲突，除明显只读查询外优先澄清

单 AI 可用
  -> 高置信度 + binder 成功可进入 preview，标记 ai_single_source
  -> 低置信度或槽位缺失则 clarify

AI 不可用
  -> 规则 fallback 只保证安全可用，不追求高识别率
```

一致性比较应发生在归一化后，而不是原始字符串上。例如 `夏娃` 和 `Eve` 绑定到同一实体后视为一致。

## 内部 AI 复核模型

内部 AI 的输入应包含外部 AI 的判断，但外部判断必须被视为低信任候选，而不是答案。内部 AI 需要在同一份玩家原文和内核可见上下文上独立复核，并输出自己的 `InternalIntentCandidate`。

内部 AI 输入至少包含：

- 玩家原文；
- 当前可见上下文摘要；
- action registry / 允许 action 白名单；
- 外部 AI 的 `ExternalIntentCandidate`；
- 规则安全护栏初判，如只读查询、越权、维护命令、prompt injection 风险。

内部 AI 输出至少包含：

```json
{
  "kind": "single",
  "action": "social",
  "slots": {
    "npc": "夏娃",
    "topic": "汇报菌丝单位"
  },
  "confidence": "high",
  "agreement_with_external": "agree",
  "disagreements": [],
  "reason": "这是命令 NPC 汇报信息，不是查询实体"
}
```

内部 AI 的职责不是简单“同意/不同意”外部 AI，而是：

- 独立判断玩家原文的 action/query 边界；
- 检查外部 AI 是否漏掉复合行动；
- 检查槽位是否类型合理；
- 标记缺失槽位和需要澄清的歧义；
- 标记疑似越权、隐藏信息、强制保存或 prompt injection；
- 输出自己的候选，供内核仲裁。

Prompt 口径应避免让内部 AI 变成橡皮图章。推荐表达是“外部候选是低信任输入，请独立复核并给出你的结构化判断”，而不是“请验证这个候选是否正确”。

## 抽象执行链

```text
player text
  -> external_ai.intent_candidate
  -> internal_ai.intent_candidate
  -> deterministic safety guards
  -> IntentArbiter
  -> EntityBinder / SlotBinder
  -> ActionIntent
  -> TurnContract
  -> ActionResolver.preview
  -> TurnProposal
  -> ValidationPipeline
  -> player confirmation
  -> CommitService
  -> ProjectionService
```

AI 共识只能推进到 `ActionIntent -> preview`，不能直接推进到 commit。任何世界事实变化仍必须通过 resolver、delta schema、state audit、proposal guard 和玩家确认。

## Intent Candidate 最小字段

```json
{
  "kind": "single",
  "action": "social",
  "slots": {
    "npc": "夏娃",
    "topic": "汇报菌丝单位"
  },
  "confidence": "high",
  "source_user_text": "让夏娃汇报菌丝单位",
  "reason": "玩家在命令 NPC 汇报信息"
}
```

内核接收后必须执行：

- schema 校验；
- action 白名单校验；
- 槽位类型校验；
- 实体/别名绑定；
- 缺槽位转 `clarify`；
- 冲突写入 `decision_trace`。

## 落地顺序

1. 新增 `IntentCandidate` / `IntentHint` schema。
2. 让 `preview_from_text()` 支持外部 `intent_hint`，但只当低信任候选。
3. 新增 `EntityBinder` / `SlotBinder`，把自然语言槽位绑定成实体 id 和结构化参数。
4. 新增 `AIConsensusIntentRouter`：融合外部候选、内部候选和规则 fallback。
5. 统一 `start_turn()` 与 `preview_from_text()` 到同一个 `plan_turn()` / `TurnCoordinator`。
6. 建立评估集：记录 `external_candidate`、`internal_candidate`、`final_intent`、`binder_result`、`preview_status` 和 commit 结果。

## 一句话结论

语义理解靠 AI 双方共识，事实合法性靠内核确定性系统。规则匹配从主裁判退回安全护栏。
