# Current Save Explore Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records explore recognition, preview, persistence and target resolution behavior only. No engine behavior is changed by this probe.

Summary: PASS=62 ISSUE=24 TOTAL=86

## Coverage

- Structured explore: known locations, clocks, project, item/trap, crop plot, reference and explicit unknown leads.
- Natural explore: current base, field/defense checks, L1-L15 locations, water sources, settlement traces, clocks, projects, items and English commands.
- Boundary cases: read-only query, gather/resource search, social requests, armed scouting/combat-like wording, routine maintenance and composite travel+explore plans.
- Persistence checks: commit result, turn/event write, payload target/kind, location stability, entity count, clock stability, state audit and save health.

## Design Risk Note

- Structured `explore` is conservative and useful for known targets: it writes an explore event and does not directly create facts, entities or clock ticks.
- Natural-language target extraction is brittle. Some broad wording resolves to unrelated world rules or reference entities instead of the object the player named.
- Explicit unknown-lead wording is not extracted from natural text; only structured `unknown_lead=True` makes unresolved clues saveable.
- `检查/搜索/侦查` overlap heavily with query, gather, routine, combat and social. Without structured intent, maintenance and resource-search commands are often routed through explore or blocked as target-not-found.
- Recommended direction: have the frontend/AI pass structured explore intent with `target_id|target_query`, `target_kind=known|unknown_lead|palette_candidate`, `location_id`, `approach`, `risk_posture`, `touch/collect=false`, and `save_mode=preview|commit`.

## Area Summary

| Area | Pass | Issue | Total |
| --- | ---: | ---: | ---: |
| explore boundary | 6 | 8 | 14 |
| explore guardrails | 6 | 0 | 6 |
| natural composite explore | 3 | 1 | 4 |
| natural explore | 26 | 11 | 37 |
| natural unknown lead | 3 | 3 | 6 |
| palette explore | 1 | 0 | 1 |
| structured explore | 17 | 1 | 18 |

## Issue Summary

| Issue | Count |
| --- | ---: |
| explore_boundary_wrong_action | 6 |
| natural_explore_wrong_target | 5 |
| natural_explore_target_unresolved | 3 |
| natural_unknown_lead_not_extracted | 3 |
| explore_query_misrouted | 2 |
| explore_wrong_target | 1 |
| natural_explore_composite_plan_wrong | 1 |
| natural_explore_misread_as_gather | 1 |
| natural_explore_misread_as_query | 1 |
| natural_explore_misread_as_routine | 1 |

## Issue Details

### 13. structured explore / civilization rumor clock

- Issue: `explore_wrong_target`
- Observed: ok=True turns=73->74 events=78->79 target=rule:external-trace-classification kind=None event=explore health=True
- Expected: known-target explore should commit one explore event without moving, creating entities or ticking clocks
- Detail: payload={'target_query': '文明传闻', 'target_id': 'rule:external-trace-classification', 'approach': '检查外溢风险', 'needs_gm_resolution': True}
- Detail: turn={'id': 'turn:000045', 'session_id': None, 'user_text': '探索探测：civilization rumor clock', 'intent': 'explore', 'game_time_before': '第28天 · 上午', 'game_time_after': '第28天 · 上午', 'location_before': 'loc:home-mycelium-house', 'location_after': 'loc:home-mycelium-house', 'summary': '探索文明传闻，需要 GM 根据可见事实结算线索与风险。', 'changed': 1, 'created_at': '2026-07-01T17:42:14.914991+00:00', 'command_id': 'preview-explore:turn-000044-1090704a33840961', 'command_hash': '9c240560a08720b6937fee808908560e7790e51dc80edeaee4f80bac17e10ba7', 'expected_turn_id': 'turn:000044'}
- Detail: event_payload={'approach': '检查外溢风险', 'needs_gm_resolution': True, 'target_id': 'rule:external-trace-classification', 'target_query': '文明传闻'}
- Detail: entities=288->288
- Detail: clocks={'clock:drought-spring': 4, 'clock:forest-attention': 3, 'clock:lake-settlement-suspicion': 2, 'clock:civilization-rumor': 0}->{'clock:drought-spring': 4, 'clock:forest-attention': 3, 'clock:lake-settlement-suspicion': 2, 'clock:civilization-rumor': 0}
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=payload.target_id=rule:external-trace-classification expected=clock:civilization-rumor

### 27. natural explore / natural inspect house

- Issue: `natural_explore_target_unresolved`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=检查菌丝复合屋屋内有没有异常
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“检查菌丝复合屋屋内有没有异常”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 检查菌丝复合屋屋内有没有异常']
- Detail: confirmations=None

### 29. natural explore / natural home defenses

- Issue: `natural_explore_target_unresolved`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=侦查围墙外侧
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“侦查围墙外侧”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 侦查围墙外侧']
- Detail: confirmations=None

### 49. natural explore / natural quartz quarry

- Issue: `natural_explore_misread_as_gather`
- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation no_write=True target=None kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=检查石英采掘场工具痕
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']
- Detail: errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- Detail: confirmations=None

### 50. natural explore / natural lake settlement

- Issue: `natural_explore_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True target=None kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=远距观察湖边聚落
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 52. natural explore / natural forest attention

- Issue: `natural_explore_wrong_target`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=调查森林注意来源
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索world:exploration-procedure，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'world:exploration-procedure', 'target_id': 'world:exploration-procedure', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 53. natural explore / natural civilization rumor

- Issue: `natural_explore_target_unresolved`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=检查文明传闻风险
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“clock:civilization-rumor”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: clock:civilization-rumor']
- Detail: confirmations=None

### 54. natural explore / natural lake suspicion

- Issue: `natural_explore_wrong_target`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=loc:lake-ashmoss-settlement kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=调查湖边聚落警惕
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索loc:lake-ashmoss-settlement，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'loc:lake-ashmoss-settlement', 'target_id': 'loc:lake-ashmoss-settlement', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 55. natural explore / natural water crops project

- Issue: `natural_explore_misread_as_routine`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=False status=needs_confirmation no_write=True target=None kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=调查十六畦浇水压力
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=source_user_text 更像 `explore`，但调用方传入了 `routine`。请改用 preview_from_text 或确认 action 后重试。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=['source_user_text 更像 `explore`，但调用方传入了 `routine`。请改用 preview_from_text 或确认 action 后重试。']
- Detail: errors=[]
- Detail: confirmations=None

### 59. natural explore / natural pumpkin status

- Issue: `natural_explore_wrong_target`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=调查南瓜状态
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索world:exploration-procedure，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'world:exploration-procedure', 'target_id': 'world:exploration-procedure', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 60. natural explore / natural current room english

- Issue: `natural_explore_wrong_target`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=True status=ready no_write=True target=ref:day-028-current-priorities kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=inspect current room
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索inspect current room，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'inspect current room', 'target_id': 'ref:day-028-current-priorities', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 62. natural explore / natural wall english

- Issue: `natural_explore_wrong_target`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=True status=ready no_write=True target=rule:gather-yield-pressure kind=None plan=[]
- Expected: natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state
- Detail: text=scout around the wall
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索scout around the wall，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'scout around the wall', 'target_id': 'rule:gather-yield-pressure', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 66. natural unknown lead / natural unknown hum explicit

- Issue: `natural_unknown_lead_not_extracted`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue
- Detail: text=把奇怪的嗡鸣当未知线索探索
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“把奇怪的嗡鸣当未知线索探索”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 把奇怪的嗡鸣当未知线索探索']
- Detail: confirmations=None

### 67. natural unknown lead / natural unknown footprint explicit

- Issue: `natural_unknown_lead_not_extracted`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue
- Detail: text=把围墙外陌生脚印作为未知线索侦查
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“把围墙外陌生脚印作为未知线索侦查”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 把围墙外陌生脚印作为未知线索侦查']
- Detail: confirmations=None

### 68. natural unknown lead / natural unknown smoke explicit

- Issue: `natural_unknown_lead_not_extracted`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[]
- Expected: explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue
- Detail: text=远处烟柱作为未知线索调查
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索world:exploration-procedure，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'world:exploration-procedure', 'target_id': 'world:exploration-procedure', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 72. natural composite explore / natural travel social not pure explore

- Issue: `natural_explore_composite_plan_wrong`
- Observed: start=action:travel can_proceed=True preview=action:travel ready=True status=ready no_write=True target=None kind=None plan=[]
- Expected: travel plus explore wording should return a composite plan without writing state
- Detail: text=去湖边聚落问有没有烟柱线索
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=travel 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=travel
- Detail: delta_summary=从六边形菌丝复合屋前往灰藓族湖边聚落，预计约39分钟；到达后需要输出场景入场包。
- Detail: payload={'from_location_id': 'loc:home-mycelium-house', 'to_location_id': 'loc:lake-ashmoss-settlement', 'route_id': 'route:home-mycelium-house--home-mycelium-city -> route:home-mycelium-city--l09-underground-home -> route:l06-waterfall--l09-underground-home -> route:l06-waterfall--l10-river -> route:l10-river--l11-delta -> route:l11-delta--lake-ashmoss-settlement', 'route_ids': ['route:home-mycelium-house--home-mycelium-city', 'route:home-mycelium-city--l09-underground-home', 'route:l06-waterfall--l09-underground-home', 'route:l06-waterfall--l10-river', 'route:l10-river--l11-delta', 'route:l11-delta--lake-ashmoss-settlement'], 'route_segments': [{'id': 'route:home-mycelium-house--home-mycelium-city', 'from_location_id': 'loc:home-mycelium-house', 'to_location_id': 'loc:home-mycelium-city', 'travel_minutes': 1, 'difficulty': 'easy', 'hazards_json': '["竖井上下需确认脚下菌丝阶梯是否张开"]', 'requirements_json': '["通过新屋地板竖井"]'}, {'id': 'route:home-mycelium-city--l09-underground-home', 'from_location_id': 'loc:home-mycelium-city', 'to_location_id': 'loc:l09-underground-home', 'travel_minutes': 5, 'difficulty': 'friendly', 'hazards_json': '["西隧仍需确认菌丝维护状态", "大件物资通过时需放慢"]', 'requirements_json': '["走菌丝城西隧"]'}, {'id': 'route:l06-waterfall--l09-underground-home', 'from_location_id': 'loc:l09-underground-home', 'to_location_id': 'loc:l06-waterfall', 'travel_minutes': 5, 'difficulty': 'friendly', 'hazards_json': '["地下入口狭窄", "未经招呼进入可能失礼"]', 'requirements_json': '["通过 An/小的的居所边界", "进入前表明非敌意"]'}, {'id': 'route:l06-waterfall--l10-river', 'from_location_id': 'loc:l06-waterfall', 'to_location_id': 'loc:l10-river', 'travel_minutes': 10, 'difficulty': 'normal', 'hazards_json': '["河岸湿滑", "水声掩盖动静"]', 'requirements_json': '["沿水系下行"]'}, {'id': 'route:l10-river--l11-delta', 'from_location_id': 'loc:l10-river', 'to_location_id': 'loc:l11-delta', 'travel_minutes': 10, 'difficulty': 'risky', 'hazards_json': '["芦苇遮挡视线", "人工渔网可能暴露他者活动"]', 'requirements_json': '["接近前先观察火烟和脚印"]'}, {'id': 'route:l11-delta--lake-ashmoss-settlement', 'from_location_id': 'loc:l11-delta', 'to_location_id': 'loc:lake-ashmoss-settlement', 'travel_minutes': 8, 'difficulty': 'wary', 'hazards_json': '["聚落警惕", "武装接近可能被误判", "棚屋视线交叉"]', 'requirements_json': '["交换物", "非敌意姿态", "优先通过 An 中介"]'}], 'estimated_minutes': 39, 'pace': 'normal', 'route_difficulty': 'wary', 'route_hazards': ['竖井上下需确认脚下菌丝阶梯是否张开', '西隧仍需确认菌丝维护状态', '大件物资通过时需放慢', '地下入口狭窄', '未经招呼进入可能失礼', '河岸湿滑', '水声掩盖动静', '芦苇遮挡视线', '人工渔网可能暴露他者活动', '聚落警惕', '武装接近可能被误判', '棚屋视线交叉'], 'route_requirements': ['通过新屋地板竖井', '走菌丝城西隧', '通过 An/小的的居所边界', '进入前表明非敌意', '沿水系下行', '接近前先观察火烟和脚印', '交换物', '非敌意姿态', '优先通过 An 中介'], 'destination_safety': 'wary', 'known_threat_ids': ['threat:c3-92847a'], 'needs_gm_resolution': True, 'arrival_scene_required': True}
- Detail: upsert_entities=[{'id': 'pc:shenyan', 'type': 'character', 'name': '亚', 'status': 'active', 'visibility': 'known', 'location_id': 'loc:lake-ashmoss-settlement', 'owner_id': None, 'summary': '健康██████████  极佳；体力未登记；饥饿未登记；口渴未登记；金光未登记；位置灰藓族湖边聚落（旅行到达/耗时约39分钟，草案）', 'details': {'location_text': '灰藓族湖边聚落（旅行到达/耗时约39分钟，草案）'}, 'aliases': [], 'character': {'species_id': 'species:human', 'role': 'player_character', 'attitude': 'self', 'trust': 100, 'health_state': '██████████  极佳', 'stress': {}, 'consequences': [], 'goals': [], 'knowledge': {}}}]
- Detail: tick_clocks=[{'id': 'clock:lake-settlement-suspicion', 'delta': 1}]
- Detail: warnings=['目的地安全等级为 wary：到达后必须先输出风险和迹象。', '目的地登记有 1 个 active 威胁。']
- Detail: errors=[]
- Detail: confirmations=None

### 75. explore boundary / natural ammo count

- Issue: `explore_query_misrouted`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True target=None kind=None plan=[]
- Expected: read-only status/count/progress questions should remain query/routine without writing explore events
- Detail: text=检查火药箭数量
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- Detail: delta_intent=routine
- Detail: delta_summary=日常行动：检查火药箭数量。
- Detail: payload={'template_id': 'routine:upkeep', 'task': '检查火药箭数量', 'target_id': None, 'focus': None, 'time_cost': '10m', 'needs_gm_resolution': True, 'state_changes_must_be_structured': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 77. explore boundary / natural current options

- Issue: `explore_query_misrouted`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[]
- Expected: read-only status/count/progress questions should remain query/routine without writing explore events
- Detail: text=现在附近有什么可以调查
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: delta_intent=explore
- Detail: delta_summary=探索world:exploration-procedure，需要 GM 根据可见事实结算线索与风险。
- Detail: payload={'target_query': 'world:exploration-procedure', 'target_id': 'world:exploration-procedure', 'approach': 'careful', 'needs_gm_resolution': True}
- Detail: upsert_entities=[]
- Detail: tick_clocks=[]
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 79. explore boundary / natural search herbs

- Issue: `explore_boundary_wrong_action`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: non-explore intent should not be stolen by broad explore keywords
- Detail: text=搜索草药
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“搜索草药”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 搜索草药']
- Detail: confirmations=None

### 80. explore boundary / natural collect fiber

- Issue: `explore_boundary_wrong_action`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: non-explore intent should not be stolen by broad explore keywords
- Detail: text=搜索附近可用材料
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“搜索附近可用材料”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 搜索附近可用材料']
- Detail: confirmations=None

### 83. explore boundary / natural armed scout wall

- Issue: `explore_boundary_wrong_action`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: non-explore intent should not be stolen by broad explore keywords
- Detail: text=拿弩侦查围墙外
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“拿弩侦查围墙外”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 拿弩侦查围墙外']
- Detail: confirmations=None

### 84. explore boundary / natural inspect before rest

- Issue: `explore_boundary_wrong_action`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True target=None kind=None plan=[]
- Expected: non-explore intent should not be stolen by broad explore keywords
- Detail: text=休息前检查门闩
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_summary=在六边形菌丝复合屋休息至第29天清晨；体力基本恢复，金光恢复到 100%，清晨需要检查水分、早饭和周边动静。
- Detail: payload={'before': {'day': '28', 'time_block': '第28天 · 上午', 'location_id': 'loc:home-mycelium-house'}, 'after': {'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}, 'safety_level': 'defended', 'needs_gm_resolution': True, 'crop_checks_required': True, 'clock_ticks_are_suggestions': True}
- Detail: upsert_entities=[{'id': 'pc:shenyan', 'type': 'character', 'name': '亚', 'status': 'active', 'visibility': 'known', 'location_id': 'loc:home-mycelium-house', 'owner_id': None, 'summary': '健康██████████  极佳；体力█████████░  基本恢复；饥饿██████░░░░  清晨偏饿；口渴███████░░░  清晨需补水；金光██████████  100%；位置六边形菌丝复合屋（第29天清晨/睡醒）', 'details': {'health': '██████████  极佳', 'stamina': '█████████░  基本恢复（睡眠后行动能力恢复，仍需早饭补足）', 'hunger': '██████░░░░  清晨偏饿（建议先吃早饭）', 'thirst': '███████░░░  清晨需补水（睡醒后检查竹水筒）', 'golden_light': '██████████  100%（一夜充足睡眠后恢复，不累积）', 'location_text': '六边形菌丝复合屋（第29天清晨/睡醒）', 'sleep': '第28夜在六边形菌丝复合屋休息到第29天清晨；夜间异常需由 GM 另行结算。'}, 'aliases': [], 'character': {'species_id': 'species:human', 'role': 'player_character', 'attitude': 'self', 'trust': 100, 'health_state': '██████████  极佳', 'stress': {}, 'consequences': [], 'goals': [], 'knowledge': {}}}]
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 85. explore boundary / natural check traps maintenance

- Issue: `explore_boundary_wrong_action`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: non-explore intent should not be stolen by broad explore keywords
- Detail: text=检查陷阱
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“检查陷阱”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 检查陷阱']
- Detail: confirmations=None

### 86. explore boundary / natural check tunnels maintenance

- Issue: `explore_boundary_wrong_action`
- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[]
- Expected: non-explore intent should not be stolen by broad explore keywords
- Detail: text=检查菌丝通道
- Detail: start_plan=[]
- Detail: preview_plan=[]
- Detail: player_message=我没找到“检查菌丝通道”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- Detail: delta_intent=None
- Detail: delta_summary=
- Detail: payload={}
- Detail: upsert_entities=None
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['target not found: 检查菌丝通道']
- Detail: confirmations=None

## Full Results

| Area | Name | Status | Observed | Expected | Issue |
| --- | --- | --- | --- | --- | --- |
| structured explore | current room by id | PASS | ok=True turns=73->74 events=78->79 target=loc:home-mycelium-house kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | current room by name | PASS | ok=True turns=73->74 events=78->79 target=loc:home-mycelium-house kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | home clearing | PASS | ok=True turns=73->74 events=78->79 target=loc:home-clearing kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | mycelium city | PASS | ok=True turns=73->74 events=78->79 target=loc:home-mycelium-city kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | old hut | PASS | ok=True turns=73->74 events=78->79 target=loc:home-old-hut kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | creek | PASS | ok=True turns=73->74 events=78->79 target=loc:l01-creek kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | waterfall | PASS | ok=True turns=73->74 events=78->79 target=loc:l06-waterfall kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | sulfur spring | PASS | ok=True turns=73->74 events=78->79 target=loc:l07-sulfur-spring kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | stone trough | PASS | ok=True turns=73->74 events=78->79 target=loc:l13-stone-trough kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | lake settlement | PASS | ok=True turns=73->74 events=78->79 target=loc:lake-ashmoss-settlement kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | drought clock | PASS | ok=True turns=73->74 events=78->79 target=clock:drought-spring kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | forest attention clock | PASS | ok=True turns=73->74 events=78->79 target=clock:forest-attention kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | civilization rumor clock | ISSUE | ok=True turns=73->74 events=78->79 target=rule:external-trace-classification kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks | explore_wrong_target |
| structured explore | water crops project | PASS | ok=True turns=73->74 events=78->79 target=project:water-crops kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | M2 landmine | PASS | ok=True turns=73->74 events=78->79 target=item:landmine-m2 kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | field plot | PASS | ok=True turns=73->74 events=78->79 target=plot:field-001 kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | stone tablet | PASS | ok=True turns=73->74 events=78->79 target=item:v1-5a357b56c5 kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| structured explore | current priorities reference | PASS | ok=True turns=73->74 events=78->79 target=ref:day-028-current-priorities kind=None event=explore health=True | known-target explore should commit one explore event without moving, creating entities or ticking clocks |  |
| explore guardrails | missing target | PASS | ready=False status=clarify turns=73->73 events=78->78 | missing explore target should not be ready or write state |  |
| explore guardrails | unknown target blocked | PASS | ready=False status=blocked turns=73->73 events=78->78 | unknown target without explicit unknown_lead should not save |  |
| explore guardrails | unknown target allowed bool | PASS | ok=True turns=73->74 events=78->79 target=None kind=unknown_lead event=explore health=True | explicit unknown_lead should commit as unresolved clue without target_id |  |
| explore guardrails | unknown target allowed text | PASS | ok=True turns=73->74 events=78->79 target=None kind=unknown_lead event=explore health=True | text unknown_lead flag should commit as unresolved clue without target_id |  |
| palette explore | available palette candidate | PASS | ok=True turns=73->74 events=78->79 target=None kind=palette_candidate event=explore health=True | available palette explore should commit as palette_candidate and not create known entity |  |
| explore guardrails | out of context palette | PASS | ready=False status=blocked turns=73->73 events=78->78 | out-of-context palette should be blocked |  |
| explore guardrails | missing palette | PASS | ready=False status=blocked turns=73->73 events=78->78 | missing palette should be blocked |  |
| natural explore | natural current room | PASS | ok=True turns=73->74 events=78->79 target=loc:home-mycelium-house kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural inspect house | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_target_unresolved |
| natural explore | natural home clearing | PASS | ok=True turns=73->74 events=78->79 target=loc:home-clearing kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural home defenses | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_target_unresolved |
| natural explore | natural old hut | PASS | ok=True turns=73->74 events=78->79 target=loc:home-old-hut kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural old hut dangerous goods | PASS | ok=True turns=73->74 events=78->79 target=loc:home-old-hut kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural creek trace | PASS | ok=True turns=73->74 events=78->79 target=loc:l01-creek kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural creek alias | PASS | ok=True turns=73->74 events=78->79 target=loc:l01-creek kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural pool | PASS | ok=True turns=73->74 events=78->79 target=loc:l02-pool kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural pinewood | PASS | ok=True turns=73->74 events=78->79 target=loc:l03-pinewood kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural bramble ring | PASS | ok=True turns=73->74 events=78->79 target=loc:l04-bramble-ring kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural oldwood | PASS | ok=True turns=73->74 events=78->79 target=loc:l05-oldwood kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural waterfall | PASS | ok=True turns=73->74 events=78->79 target=loc:l06-waterfall kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural t5 overlook | PASS | ok=True turns=73->74 events=78->79 target=loc:l06-t5-overlook-trough kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural sulfur spring | PASS | ok=True turns=73->74 events=78->79 target=loc:l07-sulfur-spring kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural stone terrace | PASS | ok=True turns=73->74 events=78->79 target=loc:l08-stone-terrace kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural An old home | PASS | ok=True turns=73->74 events=78->79 target=loc:l09-underground-home kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural river | PASS | ok=True turns=73->74 events=78->79 target=loc:l10-river kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural delta | PASS | ok=True turns=73->74 events=78->79 target=loc:l11-delta kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural niter point | PASS | ok=True turns=73->74 events=78->79 target=loc:l12-niter-crust kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural stone trough | PASS | ok=True turns=73->74 events=78->79 target=loc:l13-stone-trough kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural wetland | PASS | ok=True turns=73->74 events=78->79 target=loc:l14-humus-wetland kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural grassland cliff | PASS | ok=True turns=73->74 events=78->79 target=loc:l15-grassland-cliff kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural quartz quarry | ISSUE | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation no_write=True target=None kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_misread_as_gather |
| natural explore | natural lake settlement | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True target=None kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_misread_as_query |
| natural explore | natural drought clock | PASS | ok=True turns=73->74 events=78->79 target=clock:drought-spring kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural forest attention | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_wrong_target |
| natural explore | natural civilization rumor | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_target_unresolved |
| natural explore | natural lake suspicion | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=loc:lake-ashmoss-settlement kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_wrong_target |
| natural explore | natural water crops project | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=False status=needs_confirmation no_write=True target=None kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_misread_as_routine |
| natural explore | natural landmine | PASS | ok=True turns=73->74 events=78->79 target=item:landmine-m2 kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural field water | PASS | ok=True turns=73->74 events=78->79 target=plot:field-001 kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural stone tablet | PASS | ok=True turns=73->74 events=78->79 target=item:v1-5a357b56c5 kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural pumpkin status | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_wrong_target |
| natural explore | natural current room english | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=True status=ready no_write=True target=ref:day-028-current-priorities kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_wrong_target |
| natural explore | natural drought english | PASS | ok=True turns=73->74 events=78->79 target=clock:drought-spring kind=None event=explore health=True | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state |  |
| natural explore | natural wall english | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=True status=ready no_write=True target=rule:gather-yield-pressure kind=None plan=[] | natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state | natural_explore_wrong_target |
| natural unknown lead | natural strange hum plain | PASS | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | unknown natural clue should at least stay as explore clarification without writing state |  |
| natural unknown lead | natural strange shard plain | PASS | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | unknown natural clue should at least stay as explore clarification without writing state |  |
| natural unknown lead | natural night whistle plain | PASS | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | unknown natural clue should at least stay as explore clarification without writing state |  |
| natural unknown lead | natural unknown hum explicit | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue | natural_unknown_lead_not_extracted |
| natural unknown lead | natural unknown footprint explicit | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue | natural_unknown_lead_not_extracted |
| natural unknown lead | natural unknown smoke explicit | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[] | explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue | natural_unknown_lead_not_extracted |
| natural composite explore | natural round trip creek | PASS | start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation no_write=True target=None kind=None plan=['travel', 'explore', 'travel'] | travel plus explore wording should return a composite plan without writing state |  |
| natural composite explore | natural travel then spring explore | PASS | start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation no_write=True target=None kind=None plan=['travel', 'explore'] | travel plus explore wording should return a composite plan without writing state |  |
| natural composite explore | natural travel delta traces | PASS | start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation no_write=True target=None kind=None plan=['travel', 'explore'] | travel plus explore wording should return a composite plan without writing state |  |
| natural composite explore | natural travel social not pure explore | ISSUE | start=action:travel can_proceed=True preview=action:travel ready=True status=ready no_write=True target=None kind=None plan=[] | travel plus explore wording should return a composite plan without writing state | natural_explore_composite_plan_wrong |
| explore boundary | natural view around | PASS | start=query:scene can_proceed=True preview=action:query ready=False status=ready no_write=True target=None kind=None plan=[] | read-only status/count/progress questions should remain query/routine without writing explore events |  |
| explore boundary | natural forest attention progress | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True target=None kind=None plan=[] | read-only status/count/progress questions should remain query/routine without writing explore events |  |
| explore boundary | natural ammo count | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True target=None kind=None plan=[] | read-only status/count/progress questions should remain query/routine without writing explore events | explore_query_misrouted |
| explore boundary | natural material status | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True target=None kind=None plan=[] | read-only status/count/progress questions should remain query/routine without writing explore events |  |
| explore boundary | natural current options | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True target=world:exploration-procedure kind=None plan=[] | read-only status/count/progress questions should remain query/routine without writing explore events | explore_query_misrouted |
| explore boundary | natural gather herbs | PASS | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords |  |
| explore boundary | natural search herbs | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords | explore_boundary_wrong_action |
| explore boundary | natural collect fiber | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords | explore_boundary_wrong_action |
| explore boundary | natural ask pumpkin anomaly | PASS | start=action:social can_proceed=True preview=action:social ready=True status=ready no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords |  |
| explore boundary | natural tell An inspect | PASS | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords |  |
| explore boundary | natural armed scout wall | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords | explore_boundary_wrong_action |
| explore boundary | natural inspect before rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords | explore_boundary_wrong_action |
| explore boundary | natural check traps maintenance | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords | explore_boundary_wrong_action |
| explore boundary | natural check tunnels maintenance | ISSUE | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked no_write=True target=None kind=None plan=[] | non-explore intent should not be stolen by broad explore keywords | explore_boundary_wrong_action |
