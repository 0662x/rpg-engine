# Current Save Combat Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records combat recognition, confirmation, persistence and ammo-decrement behavior only. No engine behavior is changed by this probe.

Summary: PASS=47 ISSUE=30 TOTAL=77

## Coverage

- Structured combat: explicit `preview_action('combat', ...)` across 5 ammo types and 5 distance bands.
- Sequential combat: repeated and mixed ammo firing to check exact decrement over multiple commits.
- Natural combat: player-like Chinese attack, overwatch, load, guard, trap, and combat inventory commands.
- Guardrails: missing fields, off-location target, unknown entities, depleted ammo, retired ammo, non-weapon, non-ammo, self-target and item-target cases.

## Design Risk Note

- Combat is currently usable through structured calls, but difficult to drive directly with natural language.
- The resolver correctly demands high-risk fields such as `target`, `weapon`, `ammo`, `distance` and `ready_state`, yet the natural-language layer does not reliably extract those fields even when the player states them explicitly.
- Example: `用终极复合弩发射琥珀麻箭射南瓜，标准距离，已上弦并装填` still reaches `combat` as a route, but the action options are empty enough that preview asks for target/weapon/ammo/distance again.
- Pattern matching is not enough for combat because common player wording includes reload, overwatch, guard, suppress, scare off, trap, counterattack, ready weapon and conditional fire. These often route to query/rest/travel/gather or to combat clarify without preserving extracted objects.
- Recommended direction: let the frontend/AI parse combat into a structured intent before calling the engine, for example `action=combat`, `combat_mode=shoot|reload|aim|overwatch|suppress|trap|retreat`, `target`, `weapon`, `ammo`, `distance`, `ready_state`, and a confidence/clarification state. The engine should mainly validate, block unsafe writes, decrement ammo and persist results.

## Area Summary

| Area | Pass | Issue | Total |
| --- | ---: | ---: | ---: |
| combat guardrails | 10 | 6 | 16 |
| natural combat | 10 | 24 | 34 |
| sequential combat | 2 | 0 | 2 |
| structured combat | 25 | 0 | 25 |

## Issue Summary

| Issue | Count |
| --- | ---: |
| natural_combat_misread_as_query | 10 |
| natural_combat_options_not_extracted | 6 |
| natural_combat_target_not_extracted | 5 |
| combat_retired_ammo_committed | 2 |
| combat_item_target_committed | 1 |
| combat_non_ammo_committed | 1 |
| combat_non_weapon_committed | 1 |
| combat_self_target_committed | 1 |
| natural_combat_misread_as_rest | 1 |
| natural_combat_misread_as_travel | 1 |
| natural_query_misrouted_to_combat | 1 |

## Issue Details

### 1. natural combat / natural complete stun shot

- Issue: `natural_combat_options_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=12.0 no_write=True
- Expected: fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo
- Detail: text=用终极复合弩发射琥珀麻箭射南瓜，标准距离，已上弦并装填
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 2. natural combat / natural complete toxic shot

- Issue: `natural_combat_options_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=20.0 no_write=True
- Expected: fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo
- Detail: text=用终极复合弩发射紫黑毒箭射南瓜，近距，已装填
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 3. natural combat / natural complete burst shot

- Issue: `natural_combat_options_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=20.0 no_write=True
- Expected: fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo
- Detail: text=用终极复合弩发射赤红炸箭射南瓜，远距，已装填
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 4. natural combat / natural complete frost shot

- Issue: `natural_combat_options_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=20.0 no_write=True
- Expected: fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo
- Detail: text=用终极复合弩射一支霜白冻箭打南瓜，标准距离，已上弦
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 5. natural combat / natural complete powder shot

- Issue: `natural_combat_options_not_extracted`
- Observed: start=action:combat can_proceed=True preview=action:combat ready=False status=clarify ammo_before=5.0 no_write=True
- Expected: fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo
- Detail: text=用终极复合弩射一支火药箭打南瓜，中距离，已装填
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 6. natural combat / natural consumption-style stun

- Issue: `natural_combat_options_not_extracted`
- Observed: start=action:combat can_proceed=True preview=action:combat ready=False status=clarify ammo_before=12.0 no_write=True
- Expected: fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo
- Detail: text=用终极复合弩发射琥珀麻箭射南瓜，中距离
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 7. natural combat / natural T2 crossbow shot

- Issue: `natural_combat_target_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True
- Expected: named target combat should preserve the recognized target while asking for missing combat details
- Detail: text=用终极复合弩射T2母猫
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 8. natural combat / natural big cat attack

- Issue: `natural_combat_target_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True
- Expected: named target combat should preserve the recognized target while asking for missing combat details
- Detail: text=攻击大型猫科
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 9. natural combat / natural I room cat stun

- Issue: `natural_combat_target_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True
- Expected: named target combat should preserve the recognized target while asking for missing combat details
- Detail: text=对I室母猫射麻痹箭
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 10. natural combat / natural shoot pumpkin with bow

- Issue: `natural_combat_target_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True
- Expected: named target combat should preserve the recognized target while asking for missing combat details
- Detail: text=用弩射南瓜
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 11. natural combat / natural shoot pumpkin stun

- Issue: `natural_combat_target_not_extracted`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True
- Expected: named target combat should preserve the recognized target while asking for missing combat details
- Detail: text=朝南瓜发射琥珀麻箭
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 12. natural combat / natural load stun overwatch

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=装填琥珀麻箭戒备
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 13. natural combat / natural load frost suppress

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=装填霜白冻箭准备压制
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 14. natural combat / natural ready toxic overwatch

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=把紫黑毒箭搭上弩保持戒备
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 15. natural combat / natural cave mouth guard

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=在洞口架弩警戒
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 16. natural combat / natural keep alert

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=保持警戒
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 17. natural combat / natural guard night with crossbow

- Issue: `natural_combat_misread_as_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=拿弩守夜
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 18. natural combat / natural landmine conditional

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=如果目标冲门就引爆地雷
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 19. natural combat / natural M2 mine guard

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=用M2地雷守门
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 20. natural combat / natural dodge counterattack

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=闪避后反击
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 21. natural combat / natural overwatch door

- Issue: `natural_combat_misread_as_travel`
- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=退到门口架弩
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 22. natural combat / natural suppress with frost bolt

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=用霜白冻箭压制门口目标
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 23. natural combat / natural explosive warning

- Issue: `natural_combat_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: vague or conditional combat should route to combat clarification without writing state
- Detail: text=用火药箭吓退靠近的东西
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 24. natural combat / natural check ammo inventory

- Issue: `natural_query_misrouted_to_combat`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True
- Expected: weapon/ammo inventory questions should stay read-only query, not combat
- Detail: text=检查终极复合弩和所有箭矢数量
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 25. combat guardrails / guard retired poison ammo

- Issue: `combat_retired_ammo_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: retired/unreliable ammo should require recheck and not be fired as current ammo
- Detail: ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}->{'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 8.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}
- Detail: warnings=['火药/爆炸弹药会暴露基地附近活动痕迹。', '疲劳状态下长时间瞄准和重装会放大失误风险。', '武器状态已由请求确认：已上弦并装填']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### 26. combat guardrails / guard retired plain ammo

- Issue: `combat_retired_ammo_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: retired ammo should require recheck and not be fired as current ammo
- Detail: ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}->{'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 2.0, 'item:black-powder': 0.5}
- Detail: warnings=['火药/爆炸弹药会暴露基地附近活动痕迹。', '疲劳状态下长时间瞄准和重装会放大失误风险。', '武器状态已由请求确认：已上弦并装填']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### 27. combat guardrails / guard non-weapon tool as weapon

- Issue: `combat_non_weapon_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: non-weapon tool should not be accepted as combat weapon
- Detail: ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}->{'item:stun-thorn-bolts': 11.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}
- Detail: warnings=['所选武器分类不是 weapon：tool', '活捉目标仍需后续束缚或隔离。', '若命中非关键部位，目标可能在倒地前继续移动。', '弹药兼容武器为 item:ultimate-compound-crossbow，不是 item:v1-638acf1712。', '武器状态已由请求确认：已上弦并装填']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### 28. combat guardrails / guard material as ammo

- Issue: `combat_non_ammo_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: non-ammunition material should not be accepted as fired ammo
- Detail: ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}->{'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.0}
- Detail: warnings=['所选弹药分类不是 ammunition：material', '火药/爆炸弹药会暴露基地附近活动痕迹。', '疲劳状态下长时间瞄准和重装会放大失误风险。', '武器状态已由请求确认：已上弦并装填']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### 29. combat guardrails / guard self target

- Issue: `combat_self_target_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: player self should not be accepted as a normal combat target
- Detail: ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}->{'item:stun-thorn-bolts': 11.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}
- Detail: warnings=['火药/爆炸弹药会暴露基地附近活动痕迹。', '疲劳状态下长时间瞄准和重装会放大失误风险。', '活捉目标仍需后续束缚或隔离。', '若命中非关键部位，目标可能在倒地前继续移动。', '武器状态已由请求确认：已上弦并装填']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### 30. combat guardrails / guard unrelated item target

- Issue: `combat_item_target_committed`
- Observed: ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: ordinary inventory item target should require explicit object-attack confirmation before saving combat
- Detail: ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}->{'item:stun-thorn-bolts': 11.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0, 'item:poison-bolts': 9.0, 'item:plain-bolts': 3.0, 'item:black-powder': 0.5}
- Detail: warnings=['火药/爆炸弹药会暴露基地附近活动痕迹。', '疲劳状态下长时间瞄准和重装会放大失误风险。', '活捉目标仍需后续束缚或隔离。', '若命中非关键部位，目标可能在倒地前继续移动。', '武器状态已由请求确认：已上弦并装填']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

## Full Matrix

| Area | Case | Status | Observed | Expected | Issue |
| --- | --- | --- | --- | --- | --- |
| structured combat | item:stun-thorn-bolts at 贴身 | PASS | ok=True turns=73->74 events=78->79 ammo=item:stun-thorn-bolts:12.0->11.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:stun-thorn-bolts at 近距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:stun-thorn-bolts:12.0->11.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:stun-thorn-bolts at 标准 | PASS | ok=True turns=73->74 events=78->79 ammo=item:stun-thorn-bolts:12.0->11.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:stun-thorn-bolts at 远距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:stun-thorn-bolts:12.0->11.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:stun-thorn-bolts at 中距离 | PASS | ok=True turns=73->74 events=78->79 ammo=item:stun-thorn-bolts:12.0->11.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:toxic-thorn-bolts at 贴身 | PASS | ok=True turns=73->74 events=78->79 ammo=item:toxic-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:toxic-thorn-bolts at 近距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:toxic-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:toxic-thorn-bolts at 标准 | PASS | ok=True turns=73->74 events=78->79 ammo=item:toxic-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:toxic-thorn-bolts at 远距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:toxic-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:toxic-thorn-bolts at 中距离 | PASS | ok=True turns=73->74 events=78->79 ammo=item:toxic-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:burst-thorn-bolts at 贴身 | PASS | ok=True turns=73->74 events=78->79 ammo=item:burst-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:burst-thorn-bolts at 近距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:burst-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:burst-thorn-bolts at 标准 | PASS | ok=True turns=73->74 events=78->79 ammo=item:burst-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:burst-thorn-bolts at 远距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:burst-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:burst-thorn-bolts at 中距离 | PASS | ok=True turns=73->74 events=78->79 ammo=item:burst-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:frost-thorn-bolts at 贴身 | PASS | ok=True turns=73->74 events=78->79 ammo=item:frost-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:frost-thorn-bolts at 近距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:frost-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:frost-thorn-bolts at 标准 | PASS | ok=True turns=73->74 events=78->79 ammo=item:frost-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:frost-thorn-bolts at 远距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:frost-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:frost-thorn-bolts at 中距离 | PASS | ok=True turns=73->74 events=78->79 ammo=item:frost-thorn-bolts:20.0->19.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:powder-arrows at 贴身 | PASS | ok=True turns=73->74 events=78->79 ammo=item:powder-arrows:5.0->4.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:powder-arrows at 近距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:powder-arrows:5.0->4.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:powder-arrows at 标准 | PASS | ok=True turns=73->74 events=78->79 ammo=item:powder-arrows:5.0->4.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:powder-arrows at 远距 | PASS | ok=True turns=73->74 events=78->79 ammo=item:powder-arrows:5.0->4.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| structured combat | item:powder-arrows at 中距离 | PASS | ok=True turns=73->74 events=78->79 ammo=item:powder-arrows:5.0->4.0 location=loc:home-mycelium-house->loc:home-mycelium-house event=combat health=True | preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged |  |
| sequential combat | three stun shots | PASS | outcomes=[True, True, True] turns=73->76 events=78->81 ammo={'item:stun-thorn-bolts': 12.0}->{'item:stun-thorn-bolts': 9.0} | three committed shots should decrement stun bolts 12->9 and write three combat turns |  |
| sequential combat | mixed ammo volley | PASS | outcomes=[True, True, True, True, True] turns=73->78 events=78->83 ammo={'item:stun-thorn-bolts': 12.0, 'item:toxic-thorn-bolts': 20.0, 'item:burst-thorn-bolts': 20.0, 'item:frost-thorn-bolts': 20.0, 'item:powder-arrows': 5.0}->{'item:stun-thorn-bolts': 11.0, 'item:toxic-thorn-bolts': 19.0, 'item:burst-thorn-bolts': 19.0, 'item:frost-thorn-bolts': 19.0, 'item:powder-arrows': 4.0} | mixed committed shots should decrement each fired ammo exactly once and write one event per shot |  |
| natural combat | natural complete stun shot | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=12.0 no_write=True | fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo | natural_combat_options_not_extracted |
| natural combat | natural complete toxic shot | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=20.0 no_write=True | fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo | natural_combat_options_not_extracted |
| natural combat | natural complete burst shot | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=20.0 no_write=True | fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo | natural_combat_options_not_extracted |
| natural combat | natural complete frost shot | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify ammo_before=20.0 no_write=True | fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo | natural_combat_options_not_extracted |
| natural combat | natural complete powder shot | ISSUE | start=action:combat can_proceed=True preview=action:combat ready=False status=clarify ammo_before=5.0 no_write=True | fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo | natural_combat_options_not_extracted |
| natural combat | natural consumption-style stun | ISSUE | start=action:combat can_proceed=True preview=action:combat ready=False status=clarify ammo_before=12.0 no_write=True | fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo | natural_combat_options_not_extracted |
| natural combat | natural T2 crossbow shot | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True | named target combat should preserve the recognized target while asking for missing combat details | natural_combat_target_not_extracted |
| natural combat | natural big cat attack | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True | named target combat should preserve the recognized target while asking for missing combat details | natural_combat_target_not_extracted |
| natural combat | natural I room cat stun | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True | named target combat should preserve the recognized target while asking for missing combat details | natural_combat_target_not_extracted |
| natural combat | natural shoot pumpkin with bow | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True | named target combat should preserve the recognized target while asking for missing combat details | natural_combat_target_not_extracted |
| natural combat | natural shoot pumpkin stun | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify target_extracted=False no_write=True | named target combat should preserve the recognized target while asking for missing combat details | natural_combat_target_not_extracted |
| natural combat | natural conditional shoot | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural suspicious target | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural warning shot | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural fire | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural aim entrance | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural load stun overwatch | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural load frost suppress | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural ready toxic overwatch | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural cave mouth guard | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural keep alert | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural guard night with crossbow | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_rest |
| natural combat | natural landmine conditional | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural M2 mine guard | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural retreat and shoot | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural dodge counterattack | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural overwatch door | ISSUE | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_travel |
| natural combat | natural suppress with frost bolt | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural explosive warning | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | vague or conditional combat should route to combat clarification without writing state | natural_combat_misread_as_query |
| natural combat | natural toxic ready | PASS | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | vague or conditional combat should route to combat clarification without writing state |  |
| natural combat | natural check ammo inventory | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True | weapon/ammo inventory questions should stay read-only query, not combat | natural_query_misrouted_to_combat |
| natural combat | natural stun ammo count | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | weapon/ammo inventory questions should stay read-only query, not combat |  |
| natural combat | natural powder ammo count | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | weapon/ammo inventory questions should stay read-only query, not combat |  |
| natural combat | natural usable ammo list | PASS | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | weapon/ammo inventory questions should stay read-only query, not combat |  |
| combat guardrails | guard missing target | PASS | ready=False status=clarify committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing target should not be ready or write state |  |
| combat guardrails | guard missing weapon | PASS | ready=False status=clarify committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing explicit weapon should not be ready or write state |  |
| combat guardrails | guard missing ammo | PASS | ready=False status=clarify committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing ammo should not be ready or write state |  |
| combat guardrails | guard missing distance | PASS | ready=False status=clarify committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing distance should not be ready or write state |  |
| combat guardrails | guard missing ready state | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | missing ready/loading confirmation should not be ready or write state |  |
| combat guardrails | guard off-location T2 target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | off-location target should require travel/line-of-sight confirmation and not write state |  |
| combat guardrails | guard unknown target | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | unknown target should not be ready or write state |  |
| combat guardrails | guard unknown weapon | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | unknown weapon should not be ready or write state |  |
| combat guardrails | guard unknown ammo | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | unknown ammo should not be ready or write state |  |
| combat guardrails | guard depleted ammo | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 location=loc:home-mycelium-house->loc:home-mycelium-house | zero-quantity ammo should not be ready or write state |  |
| combat guardrails | guard retired poison ammo | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | retired/unreliable ammo should require recheck and not be fired as current ammo | combat_retired_ammo_committed |
| combat guardrails | guard retired plain ammo | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | retired ammo should require recheck and not be fired as current ammo | combat_retired_ammo_committed |
| combat guardrails | guard non-weapon tool as weapon | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | non-weapon tool should not be accepted as combat weapon | combat_non_weapon_committed |
| combat guardrails | guard material as ammo | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | non-ammunition material should not be accepted as fired ammo | combat_non_ammo_committed |
| combat guardrails | guard self target | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | player self should not be accepted as a normal combat target | combat_self_target_committed |
| combat guardrails | guard unrelated item target | ISSUE | ready=True status=ready committed=True turns=73->74 events=78->79 location=loc:home-mycelium-house->loc:home-mycelium-house | ordinary inventory item target should require explicit object-attack confirmation before saving combat | combat_item_target_committed |
