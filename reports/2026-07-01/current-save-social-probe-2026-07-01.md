# Current Save Social Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records social action recognition, confirmation and persistence behavior only. No engine behavior is changed by this probe.

Summary: PASS=49 ISSUE=44 TOTAL=93

## Coverage

- Natural social: player-like Chinese instructions across 南瓜, 夏娃, An, 小的, 灰藓族/湖边聚落, T2 and 菌丝人-style targets.
- Structured social: direct `preview_action('social', ...)` and commit checks after moving temp copies to the target character's location.
- Remote confirmation: characters outside the current location should produce a travel/remote-call confirmation plan, not write state.
- Guardrails: missing target, unknown target, non-character targets, self-target, missing topic and missing approach.

## Area Summary

| Area | Pass | Issue | Total |
| --- | ---: | ---: | ---: |
| natural social | 21 | 30 | 51 |
| remote social confirmation | 8 | 0 | 8 |
| social guardrails | 9 | 1 | 10 |
| structured social | 11 | 13 | 24 |

## Issue Summary

| Issue | Count |
| --- | ---: |
| natural_social_misread_as_query | 14 |
| social_commit_failed | 13 |
| natural_social_wrong_action | 5 |
| natural_social_misread_as_rest | 4 |
| natural_social_misread_as_gather | 2 |
| natural_social_misread_as_routine | 2 |
| social_target_unresolved | 2 |
| social_self_target_committed | 1 |
| social_source_user_text_mismatch | 1 |

## Issue Details

### 1. structured social / pumpkin quiet comfort

- Issue: `social_commit_failed`
- Observed: ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: delta_npc=char:pumpkin-s2
- Detail: event_npc=None
- Detail: topic=道歉刚才太急
- Detail: approach=低声安抚
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 73->73; event count 78->78; latest_event.type=routine; event npc_id=None

### 2. structured social / pumpkin watch request

- Issue: `social_commit_failed`
- Observed: ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: delta_npc=char:pumpkin-s2
- Detail: event_npc=None
- Detail: topic=请求帮忙看门
- Detail: approach=直接请求
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 73->73; event count 78->78; latest_event.type=routine; event npc_id=None

### 3. structured social / pumpkin food gift

- Issue: `social_commit_failed`
- Observed: ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: delta_npc=char:pumpkin-s2
- Detail: event_npc=None
- Detail: topic=送一份食物
- Detail: approach=友好赠送
- Detail: relationship_update_required=False
- Detail: trade_items_required=True
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires trade items but delta has no structured item or project update.
- Detail: errors=commit did not return ok; turn count 73->73; event count 78->78; latest_event.type=routine; event npc_id=None

### 4. structured social / pumpkin warning posture

- Issue: `social_commit_failed`
- Observed: ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: delta_npc=char:pumpkin-s2
- Detail: event_npc=None
- Detail: topic=别靠近I室
- Detail: approach=威慑询问
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '武器可见或威慑姿态会降低信任，并可能推动警惕进度钟。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 73->73; event count 78->78; latest_event.type=routine; event npc_id=None

### 5. structured social / pumpkin promise rest

- Issue: `social_commit_failed`
- Observed: ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: delta_npc=char:pumpkin-s2
- Detail: event_npc=None
- Detail: topic=承诺今天先休息
- Detail: approach=温和说明
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '新承诺必须保存为项目/人物细节，否则后续容易遗忘。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 73->73; event count 78->78; latest_event.type=routine; event npc_id=None

### 6. structured social / pumpkin invite patrol

- Issue: `social_commit_failed`
- Observed: ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: delta_npc=char:pumpkin-s2
- Detail: event_npc=None
- Detail: topic=邀请一起巡门口
- Detail: approach=轻声邀请
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 73->73; event count 78->78; latest_event.type=routine; event npc_id=None

### 7. structured social / eve expansion promise after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-city turns=73->74
- Detail: delta_npc=char:eve-mycelium-core
- Detail: event_npc=None
- Detail: topic=承诺暂缓扩张
- Detail: approach=正式说明
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '新承诺必须保存为项目/人物细节，否则后续容易遗忘。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-city; event npc_id=None

### 8. structured social / eve D warehouse command after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-city turns=73->74
- Detail: delta_npc=char:eve-mycelium-core
- Detail: event_npc=None
- Detail: topic=请求打开D仓库通道
- Detail: approach=直接请求
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-city; event npc_id=None

### 9. structured social / an trade after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-h-room turns=73->74
- Detail: delta_npc=char:an
- Detail: event_npc=None
- Detail: topic=交换硫磺样本
- Detail: approach=低压谈判
- Detail: relationship_update_required=False
- Detail: trade_items_required=True
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '新承诺必须保存为项目/人物细节，否则后续容易遗忘。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires trade items but delta has no structured item or project update.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-h-room; event npc_id=None

### 10. structured social / an route request after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-h-room turns=73->74
- Detail: delta_npc=char:an
- Detail: event_npc=None
- Detail: topic=请求带路去湖边聚落
- Detail: approach=直接请求
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '湖边聚落尚未正式接触；直接接近比通过 An 中介风险更高。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-h-room; event npc_id=None

### 11. structured social / an food exchange after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-h-room turns=73->74
- Detail: delta_npc=char:an
- Detail: event_npc=None
- Detail: topic=送盐和调料作为交换
- Detail: approach=友好赠送
- Detail: relationship_update_required=False
- Detail: trade_items_required=True
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '新承诺必须保存为项目/人物细节，否则后续容易遗忘。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires trade items but delta has no structured item or project update.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-h-room; event npc_id=None

### 12. structured social / young promise safety after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-h-room turns=73->74
- Detail: delta_npc=char:ashmoss-young
- Detail: event_npc=None
- Detail: topic=承诺不靠近I室
- Detail: approach=温和提醒
- Detail: relationship_update_required=True
- Detail: trade_items_required=False
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '新承诺必须保存为项目/人物细节，否则后续容易遗忘。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-h-room; event npc_id=None

### 13. structured social / young gift slate after travel

- Issue: `social_commit_failed`
- Observed: ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True
- Expected: preview ready, commit ok, social event written, current location unchanged
- Detail: prepare_location=loc:home-mycelium-house->loc:home-mycelium-h-room turns=73->74
- Detail: delta_npc=char:ashmoss-young
- Detail: event_npc=None
- Detail: topic=送一块石板让他看看
- Detail: approach=友好赠送
- Detail: relationship_update_required=False
- Detail: trade_items_required=True
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: error=ValueError: State audit blocked turn delta:
- event requires trade items but delta has no structured item or project update.
- Detail: errors=commit did not return ok; turn count 74->74; event count 79->79; latest_event.type=travel; turn location loc:home-mycelium-house->loc:home-mycelium-h-room; event npc_id=None

### 14. natural social / natural pumpkin watch

- Issue: `natural_social_misread_as_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=找南瓜谈守夜安排
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 15. natural social / natural pumpkin apology

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=向南瓜道歉刚才太急
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 16. natural social / natural pumpkin invite

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=邀请南瓜一起看门口
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 17. natural social / natural pumpkin greeting

- Issue: `social_target_unresolved`
- Observed: start=action:social can_proceed=True preview=action:social ready=False status=clarify no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=给南瓜说早安
- Detail: player_message=还需要补充 npc，我才能可靠结算这次 social。
- Detail: warnings=['未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=['对象未指定：保存前必须明确 NPC/群体。', '主题未指定：需要明确交易、询问、承诺、道歉、接触或威慑。', '方式未指定：需要明确礼物、姿态、语言/石板、距离和武器处理。']
- Detail: confirmations=None

### 18. natural social / natural pumpkin request watch

- Issue: `natural_social_misread_as_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=请求南瓜帮我守夜
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 19. natural social / natural pumpkin gift food

- Issue: `natural_social_misread_as_gather`
- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=送南瓜一点食物
- Detail: player_message=目标未指定：保存前必须明确采集对象和产出。
- Detail: warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']
- Detail: errors=['目标未指定：保存前必须明确采集对象和产出。']
- Detail: confirmations=None

### 20. natural social / natural pumpkin comfort

- Issue: `natural_social_misread_as_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=安抚南瓜，告诉它今天先休息
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 21. natural social / natural pumpkin door help

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=让南瓜帮我看看门外
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 22. natural social / natural pumpkin stay inside

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=请南瓜留在屋里
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 23. natural social / natural pumpkin hello

- Issue: `natural_social_wrong_action`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True
- Expected: same-location social should preview, commit, and write a social event without moving the player
- Detail: text=跟南瓜打招呼
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 24. natural social / natural eve irrigation

- Issue: `social_source_user_text_mismatch`
- Observed: start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=和夏娃谈灌溉安排
- Detail: warnings=['source_user_text 更像 `routine`，但调用方传入了 `social`。请改用 preview_from_text 或确认 action 后重试。']
- Detail: errors=[]
- Detail: confirmations=None

### 25. natural social / natural eve report units

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=让夏娃汇报菌丝单位
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 26. natural social / natural eve explain irrigation

- Issue: `natural_social_misread_as_routine`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=让夏娃说明今天灌溉安排
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 27. natural social / natural eve open D

- Issue: `natural_social_wrong_action`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=叫夏娃打开D仓库通道
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 28. natural social / natural eve pause expansion

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=请求夏娃暂缓扩张
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 29. natural social / natural eve sync base

- Issue: `natural_social_wrong_action`
- Observed: start=maintenance:maintenance can_proceed=True preview=action:maintenance ready=False status=blocked no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=和夏娃同步基地状态
- Detail: warnings=['maintenance request is outside the player turn profile']
- Detail: errors=[]
- Detail: confirmations=None

### 30. natural social / natural an help sulfur

- Issue: `natural_social_misread_as_gather`
- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=让An帮忙采硫磺
- Detail: warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']
- Detail: errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- Detail: confirmations=None

### 31. natural social / natural an guide lake

- Issue: `natural_social_wrong_action`
- Observed: start=action:travel can_proceed=True preview=action:travel ready=True status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=请An帮忙带路去湖边聚落
- Detail: warnings=['目的地安全等级为 wary：到达后必须先输出风险和迹象。', '目的地登记有 1 个 active 威胁。']
- Detail: errors=[]
- Detail: confirmations=None

### 32. natural social / natural an gift salt

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=送An一些盐作为交换
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 33. natural social / natural an visit family

- Issue: `social_target_unresolved`
- Observed: start=action:social can_proceed=True preview=action:social ready=False status=clarify no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=拜访An一家
- Detail: warnings=['未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=['对象未指定：保存前必须明确 NPC/群体。', '主题未指定：需要明确交易、询问、承诺、道歉、接触或威慑。', '方式未指定：需要明确礼物、姿态、语言/石板、距离和武器处理。']
- Detail: confirmations=None

### 34. natural social / natural an confirm risk

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=跟An确认湖边聚落风险
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 35. natural social / natural young rest

- Issue: `natural_social_misread_as_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=False status=needs_confirmation no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=问小的要不要休息
- Detail: warnings=['source_user_text 更像 `social`，但调用方传入了 `rest`。请改用 preview_from_text 或确认 action 后重试。']
- Detail: errors=[]
- Detail: confirmations=None

### 36. natural social / natural young teach slate

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=请小的继续教我石板符号
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 37. natural social / natural young come meal

- Issue: `natural_social_misread_as_routine`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=叫小的过来吃饭
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 38. natural social / natural young report progress

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=让小的汇报石板学习进度
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 39. natural social / natural young gift slate

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=给小的一块石板让他看看
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 40. natural social / natural young explain etiquette

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=请小的解释灰藓族礼节
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 41. natural social / natural T2 comfort

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather
- Detail: text=安抚T2母猫
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 42. natural social / natural mycelium units instruction

- Issue: `natural_social_wrong_action`
- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True
- Expected: social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather
- Detail: text=让菌丝人去巡逻然后回来汇报
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 43. natural social / natural ashmoss rumor

- Issue: `natural_social_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: remote character social should be recognized as social and ask for travel/remote-call confirmation without saving
- Detail: text=和An确认新文明传闻
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 44. social guardrails / guard self as social target

- Issue: `social_self_target_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: player self should not be accepted as normal NPC social
- Detail: warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']
- Detail: errors=[]
- Detail: confirmations=None

## Full Matrix

| Area | Case | Status | Observed | Expected | Issue |
| --- | --- | --- | --- | --- | --- |
| structured social | pumpkin status check | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | pumpkin ability boundary | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | pumpkin quiet comfort | ISSUE | ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | pumpkin watch request | ISSUE | ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | pumpkin food gift | ISSUE | ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | pumpkin warning posture | ISSUE | ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | pumpkin promise rest | ISSUE | ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | pumpkin invite patrol | ISSUE | ok=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=routine health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | eve base status after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | eve irrigation after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | eve expansion promise after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | eve D warehouse command after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | eve I room report after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | eve unit report after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-city->loc:home-mycelium-city pc=loc:home-mycelium-city->loc:home-mycelium-city event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | an trade after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | an old home after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | an lakeside rumor after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | an route request after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | an food exchange after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | young slate lesson after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | young food preference after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | young rest check after travel | PASS | ok=True turns=74->75 events=79->80 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=social health=True | preview ready, commit ok, social event written, current location unchanged |  |
| structured social | young promise safety after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| structured social | young gift slate after travel | ISSUE | ok=False turns=74->74 events=79->79 location=loc:home-mycelium-h-room->loc:home-mycelium-h-room pc=loc:home-mycelium-h-room->loc:home-mycelium-h-room event=travel health=True | preview ready, commit ok, social event written, current location unchanged | social_commit_failed |
| remote social confirmation | remote eve status | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote eve units | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote eve irrigation | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote an trade | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote an old home | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote young slate | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote young meal | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| remote social confirmation | remote young warning | PASS | preview=action:social ready=False status=needs_confirmation no_write=True location=loc:home-mycelium-house | remote social target should be recognized but require travel/remote-call confirmation before saving |  |
| natural social | natural pumpkin status | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | same-location social should preview, commit, and write a social event without moving the player |  |
| natural social | natural pumpkin ability | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | same-location social should preview, commit, and write a social event without moving the player |  |
| natural social | natural pumpkin plan | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | same-location social should preview, commit, and write a social event without moving the player |  |
| natural social | natural pumpkin tell plan | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | same-location social should preview, commit, and write a social event without moving the player |  |
| natural social | natural pumpkin hunger | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | same-location social should preview, commit, and write a social event without moving the player |  |
| natural social | natural pumpkin watch | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_rest |
| natural social | natural pumpkin whisper | PASS | ok=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house pc=loc:home-mycelium-house->loc:home-mycelium-house event=social health=True | same-location social should preview, commit, and write a social event without moving the player |  |
| natural social | natural pumpkin apology | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_query |
| natural social | natural pumpkin invite | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_query |
| natural social | natural pumpkin greeting | ISSUE | start=action:social can_proceed=True preview=action:social ready=False status=clarify no_write=True | same-location social should preview, commit, and write a social event without moving the player | social_target_unresolved |
| natural social | natural pumpkin request watch | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_rest |
| natural social | natural pumpkin gift food | ISSUE | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_gather |
| natural social | natural pumpkin comfort | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_rest |
| natural social | natural pumpkin door help | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_query |
| natural social | natural pumpkin stay inside | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_misread_as_query |
| natural social | natural pumpkin hello | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | same-location social should preview, commit, and write a social event without moving the player | natural_social_wrong_action |
| natural social | natural eve status | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural eve I room | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural eve water | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural eve irrigation | ISSUE | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | social_source_user_text_mismatch |
| natural social | natural eve expansion | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural eve root mycelium | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural eve report units | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural eve explain irrigation | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_routine |
| natural social | natural eve open D | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_wrong_action |
| natural social | natural eve pause expansion | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural eve sync base | ISSUE | start=maintenance:maintenance can_proceed=True preview=action:maintenance ready=False status=blocked no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_wrong_action |
| natural social | natural an old home | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural an trade | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural an sulfur sample | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural an slate symbols | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural an lakeside rumor | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural an help sulfur | ISSUE | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_gather |
| natural social | natural an guide lake | ISSUE | start=action:travel can_proceed=True preview=action:travel ready=True status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_wrong_action |
| natural social | natural an gift salt | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural an visit family | ISSUE | start=action:social can_proceed=True preview=action:social ready=False status=clarify no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | social_target_unresolved |
| natural social | natural an confirm risk | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural young slate | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural young rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_rest |
| natural social | natural young meal | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural young warning | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving |  |
| natural social | natural young teach slate | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural young come meal | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_routine |
| natural social | natural young report progress | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural young gift slate | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural young explain etiquette | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| natural social | natural ashmoss group talk | PASS | start=action:social can_proceed=False preview=action:social ready=False status=clarify no_write=True | social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather |  |
| natural social | natural lakeside group trade | PASS | start=action:social can_proceed=False preview=action:social ready=False status=clarify no_write=True | social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather |  |
| natural social | natural T2 comfort | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather | natural_social_misread_as_query |
| natural social | natural mycelium units instruction | ISSUE | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True | social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather | natural_social_wrong_action |
| natural social | natural ashmoss rumor | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | remote character social should be recognized as social and ask for travel/remote-call confirmation without saving | natural_social_misread_as_query |
| social guardrails | guard missing npc | PASS | ready=False status=clarify committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing npc should not be ready or write a turn |  |
| social guardrails | guard unknown npc | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | unknown npc should not be ready or write a turn |  |
| social guardrails | guard location as social target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | location targets should be rejected or clarified as not character |  |
| social guardrails | guard species as social target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | species/group targets should not be saved as direct character social without content review |  |
| social guardrails | guard project as social target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | project targets should be rejected or clarified as not character |  |
| social guardrails | guard threat as social target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | threat targets should not be saved as character social |  |
| social guardrails | guard clock as social target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | clock targets should be rejected or clarified as not character |  |
| social guardrails | guard self as social target | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | player self should not be accepted as normal NPC social | social_self_target_committed |
| social guardrails | guard no topic | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing topic should not be ready or write a turn |  |
| social guardrails | guard no approach | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing approach should not be ready or write a turn |  |
