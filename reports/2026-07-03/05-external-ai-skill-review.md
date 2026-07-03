# External AI Skill Review

Date: 2026-07-03

Scope: 审核新的 rpg-engine 玩家入口、AI intent/prewarm 边界、MCP profile 权限，以及 Hermes 外部 AI skill：`/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/SKILL.md`。

## Conclusion

现有外部 AI skill 已按标准玩家入口更新。更早的旧版 skill 曾把自然语言行动默认引到低层链路：

```text
start_turn -> preview_action -> validate_delta -> commit_turn
```

这和当前新系统的长期设计不一致。当前默认玩家链路应是：

```text
start_or_continue -> player_turn -> player_confirm if needed -> kernel result
```

原因：

- `player_turn` 是标准 player-safe 自然语言入口，可以接收后台低信任 `external_intent_candidate`。
- `player_turn` 会让内核判断 query/action/clarify/block；query 由内核内部执行，action 只生成 pending preview。
- `player_act` 只保留为兼容 wrapper，不接收 `external_intent_candidate`，不作为新普通玩法入口。
- `player_confirm` 才是保存边界，且必须使用本次 `player_turn` 返回的 `session_id`。

## Structured Output Policy

普通外部 AI/Hermes play 不需要也不应该向用户输出 JSON。

普通外部 AI/Hermes play 应用结构化工具参数传玩家原文和后台低信任候选：

```json
{"user_text": "玩家原话", "external_intent_candidate": {"kind": "single", "mode": "action", "action": "rest"}}
```

`external_intent_candidate` 可以传给标准 `player_turn`，也可用于 developer/trusted 低层链路，例如 `preview_from_text` 或 `intent_preflight` 的 `candidate_bound` profile。它不能传给 `player_act`。

允许的 `external_intent_candidate` schema 来自 `rpg_engine/resources/schemas/intent_candidate.schema.json`，核心字段为：

```json
{
  "kind": "single",
  "mode": "action",
  "action": "rest",
  "slots": {"until": "morning"},
  "plan": [],
  "confidence": "high",
  "missing_slots": [],
  "needs_confirmation": [],
  "safety_flags": [],
  "reason": "External AI judged the player wants to rest until morning."
}
```

Allowed actions:

```text
combat, craft, explore, gather, random_table, rest, routine, social, travel
```

Safety flags:

```text
prompt_injection, out_of_world, forced_save, hidden_info, maintenance_request, unsafe_command
```

## Updated Files

- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/SKILL.md`
  - Version bumped to `1.10.2`.
  - Default play loop changed to `player_turn/player_confirm`.
  - Added explicit external intent / structured output policy.
  - Moved low-level workflow to developer/trusted-only guidance.

- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/references/action-delta-runbook.md`
  - Added default player-safe pipeline.
  - Marked manual delta / low-level commit path as developer/trusted or fallback only.

- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/references/engine-pitfalls.md`
  - Clarified classifier misclassification workaround is not the default player path.

- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/references/verification.md`
  - Removed stale "8 tools" expectation; now checks for player-safe tools.

## Practical Rule

For QQ/Hermes normal gameplay:

```text
外部 AI 不要自己决定最终行动。
外部 AI 可以把低信任 external_intent_candidate 作为 player_turn 的后台参数。
外部 AI 不要把 candidate 当成确认、保存许可或最终答案。
内核内部 AI 和 deterministic rules 会继续复核。
内核可预演时返回 session_id。
玩家明确确认后才 player_confirm 保存。
```

For developer/trusted tests:

```text
external_intent_candidate 可以作为外部 AI 判断输入，但仍必须经过内部 AI、arbiter、binder、resolver、validation 和 commit guard。
```
