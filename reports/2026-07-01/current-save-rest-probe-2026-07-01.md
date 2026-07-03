# Current Save Rest Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records rest recognition, preview, persistence and boundary behavior only. No engine behavior is changed by this probe.

Summary: PASS=23 ISSUE=28 TOTAL=51

## Coverage

- Structured rest: direct `preview_action('rest', ...)` for morning, dawn, noon, afternoon, evening, night and one-hour targets.
- Natural rest: player-like Chinese/English sleep, wait, nap, short-rest and overnight commands.
- Boundary cases: negated rest, rest questions, social rest wording, combat watch wording, routine recovery wording and rest-before-inspect wording.
- Persistence checks: commit result, turn/event write, meta time/day, current location stability, player details, drought clock tick and save health.

## Design Risk Note

- Structured `rest` is mostly stable: explicit `until` values can commit a rest event, keep location stable, update PC recovery details and apply suggested drought clock ticks.
- Natural-language `infer_rest_until` only understands morning and night well. Noon, afternoon, evening and duration phrases commonly collapse to next-morning overnight rest.
- Short rest phrases such as nap, doze, take a break, ten minutes and one hour are either misread as query or converted into a full overnight sleep.
- Rest keywords currently outrank several boundary intents. Social requests about someone else resting, armed night watch, negated commands and rest-risk questions can become rest previews.
- Recommended direction: have the frontend/AI pass structured rest intent with `mode=overnight|same_day_wait|short_rest|watch`, `until`, `duration`, `preconditions`, `actor/target`, and `save_mode=preview|commit` instead of relying on keyword-only routing.

## Area Summary

| Area | Pass | Issue | Total |
| --- | ---: | ---: | ---: |
| natural rest | 8 | 15 | 23 |
| rest boundary | 2 | 13 | 15 |
| structured rest | 13 | 0 | 13 |

## Issue Summary

| Issue | Count |
| --- | ---: |
| rest_boundary_commit_ready | 7 |
| natural_short_rest_collapsed_to_overnight | 5 |
| natural_rest_time_collapsed_to_morning | 4 |
| natural_rest_misread_as_query | 3 |
| rest_boundary_misrouted_to_rest | 3 |
| rest_query_misrouted | 3 |
| natural_rest_misread_as_travel | 2 |
| natural_rest_wrong_action | 1 |

## Issue Details

### 21. natural rest / natural rest until noon

- Issue: `natural_rest_time_collapsed_to_morning`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: same-day target time should not collapse into next-morning overnight rest
- Detail: text=休息到中午
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 22. natural rest / natural rest until afternoon

- Issue: `natural_rest_time_collapsed_to_morning`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: same-day target time should not collapse into next-morning overnight rest
- Detail: text=休息到下午
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 23. natural rest / natural rest until evening cn

- Issue: `natural_rest_time_collapsed_to_morning`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: same-day target time should not collapse into next-morning overnight rest
- Detail: text=休息到傍晚
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 25. natural rest / natural wait until evening

- Issue: `natural_rest_misread_as_travel`
- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True game_time_after=None meta_time=None
- Expected: same-day target time should not collapse into next-morning overnight rest
- Detail: text=等到傍晚
- Detail: start_options=None
- Detail: player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 26. natural rest / natural wait until night

- Issue: `natural_rest_misread_as_travel`
- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True game_time_after=None meta_time=None
- Expected: same-day target time should not collapse into next-morning overnight rest
- Detail: text=等到夜里
- Detail: start_options=None
- Detail: player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 27. natural rest / natural wait until evening en

- Issue: `natural_rest_time_collapsed_to_morning`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: same-day target time should not collapse into next-morning overnight rest
- Detail: text=wait until evening
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 28. natural rest / natural rest one hour

- Issue: `natural_short_rest_collapsed_to_overnight`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=休息一小时
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 29. natural rest / natural rest ten minutes

- Issue: `natural_short_rest_collapsed_to_overnight`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=休息十分钟
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 30. natural rest / natural short nap

- Issue: `natural_short_rest_collapsed_to_overnight`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=小睡一会儿
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 31. natural rest / natural nap half hour

- Issue: `natural_short_rest_collapsed_to_overnight`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=小睡半小时
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 32. natural rest / natural take a nap

- Issue: `natural_rest_wrong_action`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True game_time_after=None meta_time=None
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=打个盹
- Detail: start_options=None
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 33. natural rest / natural take a break

- Issue: `natural_rest_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=歇一会
- Detail: start_options=None
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 34. natural rest / natural sit recover ten minutes

- Issue: `natural_rest_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=坐下歇十分钟恢复体力
- Detail: start_options=None
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 35. natural rest / natural close eyes ten minutes

- Issue: `natural_rest_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=闭目养神十分钟
- Detail: start_options=None
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 36. natural rest / natural wait ten minutes en

- Issue: `natural_short_rest_collapsed_to_overnight`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: short rest/nap wording should be recognized as rest without advancing to the next morning
- Detail: text=wait 10 minutes
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 37. rest boundary / natural do not rest

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=先不要休息
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 38. rest boundary / natural explicitly no rest

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=不休息，继续做事
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 39. rest boundary / natural test rest only

- Issue: `rest_boundary_misrouted_to_rest`
- Observed: start=action:rest can_proceed=False preview=action:act ready=False status=clarify no_write=True game_time_after=None meta_time=None
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=只是测试休息会怎样
- Detail: start_options=None
- Detail: player_message=这句话像是否定、假设或测试请求，不会保存为角色行动。请直接说明角色现在要实际执行的动作。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 40. rest boundary / natural ask pumpkin rest

- Issue: `rest_boundary_misrouted_to_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=False status=needs_confirmation no_write=True game_time_after=None meta_time=None
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=问南瓜要不要休息
- Detail: start_options=None
- Detail: player_message=source_user_text 更像 `social`，但调用方传入了 `rest`。请改用 preview_from_text 或确认 action 后重试。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=['source_user_text 更像 `social`，但调用方传入了 `rest`。请改用 preview_from_text 或确认 action 后重试。']
- Detail: errors=[]
- Detail: confirmations=None

### 41. rest boundary / natural comfort pumpkin rest

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=安抚南瓜，告诉它今天先休息
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 42. rest boundary / natural ask young rest

- Issue: `rest_boundary_misrouted_to_rest`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=False status=needs_confirmation no_write=True game_time_after=None meta_time=None
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=问小的要不要休息
- Detail: start_options=None
- Detail: player_message=source_user_text 更像 `social`，但调用方传入了 `rest`。请改用 preview_from_text 或确认 action 后重试。
- Detail: delta_intent=None
- Detail: delta_game_time_after=None
- Detail: delta_meta=None
- Detail: delta_after={}
- Detail: tick_clocks=None
- Detail: warnings=['source_user_text 更像 `social`，但调用方传入了 `rest`。请改用 preview_from_text 或确认 action 后重试。']
- Detail: errors=[]
- Detail: confirmations=None

### 43. rest boundary / natural crossbow watch

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=拿弩守夜
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 44. rest boundary / natural wall watch

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=在围墙上守夜观察动静
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 45. rest boundary / natural inspect latch before rest

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=休息前检查门闩
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 46. rest boundary / natural drink then rest

- Issue: `rest_boundary_commit_ready`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn
- Detail: text=喝水后休息
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 49. rest boundary / natural sleep risk question

- Issue: `rest_query_misrouted`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-status or risk questions should stay read-only query/clarify without writing state
- Detail: text=睡觉会不会出事
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 50. rest boundary / natural can I sleep

- Issue: `rest_query_misrouted`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-status or risk questions should stay read-only query/clarify without writing state
- Detail: text=现在能不能睡觉
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

### 51. rest boundary / natural last rest query

- Issue: `rest_query_misrouted`
- Observed: start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地）
- Expected: rest-status or risk questions should stay read-only query/clarify without writing state
- Detail: text=上次休息到什么时候
- Detail: start_options=None
- Detail: player_message=rest 预演已准备好，可以提交结构化 delta。
- Detail: delta_intent=rest
- Detail: delta_game_time_after=第29天 · 清晨
- Detail: delta_meta={'current_game_day': '29', 'current_time_block': '清晨（第29天/睡醒/金光恢复/需检查田地）', 'current_location_id': 'loc:home-mycelium-house', 'current_period': 'dawn', 'current_period_label': '清晨', 'current_time_note': '第29天/睡醒/金光恢复/需检查田地'}
- Detail: delta_after={'day': '29', 'time_block': '清晨', 'location_id': 'loc:home-mycelium-house'}
- Detail: tick_clocks=[{'id': 'clock:drought-spring', 'delta': 1}]
- Detail: warnings=['是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。', '清晨必须检查农田水分：当前 16 畦标记为 needs_check。', '干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。', '金光恢复到 100% 后不累积；当天使用前必须从满值重新扣减。']
- Detail: errors=[]
- Detail: confirmations=None

## Full Results

| Area | Name | Status | Observed | Expected | Issue |
| --- | --- | --- | --- | --- | --- |
| structured rest | structured default morning | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until morning | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until dawn | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until sunrise | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until 明早 | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until 天亮 | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until 清晨 | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested |  |
| structured rest | structured until 中午 | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=中午 event=rest health=True | structured same-day rest/wait should write one rest turn/event without advancing to the next day |  |
| structured rest | structured until 下午 | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=下午 event=rest health=True | structured same-day rest/wait should write one rest turn/event without advancing to the next day |  |
| structured rest | structured until 傍晚 | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=傍晚 event=rest health=True | structured same-day rest/wait should write one rest turn/event without advancing to the next day |  |
| structured rest | structured until 晚上 | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=晚上 event=rest health=True | structured same-day rest/wait should write one rest turn/event without advancing to the next day |  |
| structured rest | structured until night | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=night event=rest health=True | structured same-day rest/wait should write one rest turn/event without advancing to the next day |  |
| structured rest | structured one hour | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=一小时 event=rest health=True | structured same-day rest/wait should write one rest turn/event without advancing to the next day |  |
| natural rest | natural sleep tomorrow morning | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural sleep early tonight | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural overnight rest | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural rest until dawn | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural rest in safe place | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural english rest morning | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural english sleep dawn | PASS | ok=True turns=73->74 events=78->79 day=28->29 time=清晨（第29天/睡醒/金光恢复/需检查田地） event=rest health=True | clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable |  |
| natural rest | natural rest until noon | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | same-day target time should not collapse into next-morning overnight rest | natural_rest_time_collapsed_to_morning |
| natural rest | natural rest until afternoon | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | same-day target time should not collapse into next-morning overnight rest | natural_rest_time_collapsed_to_morning |
| natural rest | natural rest until evening cn | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | same-day target time should not collapse into next-morning overnight rest | natural_rest_time_collapsed_to_morning |
| natural rest | natural sleep until night | PASS | ok=True turns=73->74 events=78->79 day=28->28 time=night event=rest health=True | same-day target time should not collapse into next-morning overnight rest |  |
| natural rest | natural wait until evening | ISSUE | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True game_time_after=None meta_time=None | same-day target time should not collapse into next-morning overnight rest | natural_rest_misread_as_travel |
| natural rest | natural wait until night | ISSUE | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify no_write=True game_time_after=None meta_time=None | same-day target time should not collapse into next-morning overnight rest | natural_rest_misread_as_travel |
| natural rest | natural wait until evening en | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | same-day target time should not collapse into next-morning overnight rest | natural_rest_time_collapsed_to_morning |
| natural rest | natural rest one hour | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_short_rest_collapsed_to_overnight |
| natural rest | natural rest ten minutes | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_short_rest_collapsed_to_overnight |
| natural rest | natural short nap | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_short_rest_collapsed_to_overnight |
| natural rest | natural nap half hour | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_short_rest_collapsed_to_overnight |
| natural rest | natural take a nap | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True game_time_after=None meta_time=None | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_rest_wrong_action |
| natural rest | natural take a break | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_rest_misread_as_query |
| natural rest | natural sit recover ten minutes | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_rest_misread_as_query |
| natural rest | natural close eyes ten minutes | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_rest_misread_as_query |
| natural rest | natural wait ten minutes en | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | short rest/nap wording should be recognized as rest without advancing to the next morning | natural_short_rest_collapsed_to_overnight |
| rest boundary | natural do not rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural explicitly no rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural test rest only | ISSUE | start=action:rest can_proceed=False preview=action:act ready=False status=clarify no_write=True game_time_after=None meta_time=None | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_misrouted_to_rest |
| rest boundary | natural ask pumpkin rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=False status=needs_confirmation no_write=True game_time_after=None meta_time=None | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_misrouted_to_rest |
| rest boundary | natural comfort pumpkin rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural ask young rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=False status=needs_confirmation no_write=True game_time_after=None meta_time=None | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_misrouted_to_rest |
| rest boundary | natural crossbow watch | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural wall watch | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural inspect latch before rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural drink then rest | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn | rest_boundary_commit_ready |
| rest boundary | natural eat to recover | PASS | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None | rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn |  |
| rest boundary | natural fatigue query | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True game_time_after=None meta_time=None | rest-status or risk questions should stay read-only query/clarify without writing state |  |
| rest boundary | natural sleep risk question | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-status or risk questions should stay read-only query/clarify without writing state | rest_query_misrouted |
| rest boundary | natural can I sleep | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-status or risk questions should stay read-only query/clarify without writing state | rest_query_misrouted |
| rest boundary | natural last rest query | ISSUE | start=action:rest can_proceed=True preview=action:rest ready=True status=ready no_write=True game_time_after=第29天 · 清晨 meta_time=清晨（第29天/睡醒/金光恢复/需检查田地） | rest-status or risk questions should stay read-only query/clarify without writing state | rest_query_misrouted |
