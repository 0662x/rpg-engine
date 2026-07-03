# Current Save Travel/Movement Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records movement/travel behavior only. No engine behavior is changed by this probe.

Summary: PASS=75 ISSUE=15 TOTAL=90

## Coverage

- Structured travel: direct `preview_action('travel', destination=...)` over active known locations.
- Natural travel: player-like Chinese movement commands through `start_turn` + `preview_from_text`.
- Multi-leg chain: committed route sequence that moves across surface, water, settlement, underground, and home nodes.
- Guardrails: missing/unknown/same-location/retired-location movement attempts.

## Area Summary

| Area | Pass | Issue | Total |
| --- | ---: | ---: | ---: |
| multi-leg travel chain | 20 | 0 | 20 |
| natural travel | 30 | 11 | 41 |
| structured travel | 23 | 1 | 24 |
| travel guardrails | 2 | 3 | 5 |

## Issue Summary

| Issue | Count |
| --- | ---: |
| natural_travel_misread_as_query | 6 |
| travel_unrouted_zero_time | 3 |
| travel_retired_location_committed | 2 |
| natural_travel_destination_unresolved | 1 |
| natural_travel_wrong_action | 1 |
| travel_meta_location_not_updated | 1 |
| travel_same_location_committed | 1 |

## Issue Details

### 1. structured travel / structured to old hut/material warehouse

- Issue: `travel_unrouted_zero_time`
- Observed: ok=True turns=73->74 meta=loc:home-old-hut pc=loc:home-old-hut event=travel health=True
- Expected: preview ready, commit ok, current location and player entity move to destination
- Detail: before_location=loc:home-mycelium-house
- Detail: delta_destination=loc:home-old-hut
- Detail: estimated_minutes=0
- Detail: route_ids=[]
- Detail: event_payload_to=loc:home-old-hut
- Detail: warnings=['未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=estimated_minutes=0 for different locations; no structured route warning

### 2. natural travel / natural walk toward L3

- Issue: `natural_travel_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=走向L3
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 3. natural travel / natural go to quartz quarry

- Issue: `natural_travel_wrong_action`
- Observed: start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=去石英采掘场
- Detail: player_message=我理解你想先去 石英采掘场，再处理现场目标。需要先确认 travel，再重新预演后续行动。
- Detail: warnings=['composite action requires step confirmation']
- Detail: errors=[]
- Detail: confirmations=None

### 4. natural travel / natural return to surface clearing

- Issue: `natural_travel_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=回围墙领地
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 5. natural travel / natural return home

- Issue: `natural_travel_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=回家
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 6. natural travel / natural return to mycelium house

- Issue: `natural_travel_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=回六边形菌丝复合屋
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 7. natural travel / natural enter underground

- Issue: `natural_travel_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=进地下
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 8. natural travel / natural go to material warehouse

- Issue: `travel_unrouted_zero_time`
- Observed: ok=True turns=73->74 meta=loc:home-old-hut pc=loc:home-old-hut event=travel health=True
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=去材料仓库
- Detail: start=action:travel
- Detail: before_location=loc:home-mycelium-house
- Detail: delta_destination=loc:home-old-hut
- Detail: estimated_minutes=0
- Detail: route_ids=[]
- Detail: event_payload_to=loc:home-old-hut
- Detail: warnings=['未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=estimated_minutes=0 for different locations; no structured route warning

### 9. natural travel / natural go to old hut

- Issue: `travel_unrouted_zero_time`
- Observed: ok=True turns=73->74 meta=loc:home-old-hut pc=loc:home-old-hut event=travel health=True
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=去旧小屋
- Detail: start=action:travel
- Detail: before_location=loc:home-mycelium-house
- Detail: delta_destination=loc:home-old-hut
- Detail: estimated_minutes=0
- Detail: route_ids=[]
- Detail: event_payload_to=loc:home-old-hut
- Detail: warnings=['未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=estimated_minutes=0 for different locations; no structured route warning

### 10. natural travel / natural go up to surface

- Issue: `natural_travel_destination_unresolved`
- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=上到地表
- Detail: player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 11. natural travel / natural leave mycelium house to territory

- Issue: `travel_meta_location_not_updated`
- Observed: ok=True turns=73->74 meta=loc:home-mycelium-house pc=loc:home-mycelium-house event=travel health=True
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=从菌丝屋出门到领地
- Detail: start=action:travel
- Detail: before_location=loc:home-mycelium-house
- Detail: delta_destination=loc:home-mycelium-house
- Detail: estimated_minutes=0
- Detail: route_ids=[]
- Detail: event_payload_to=loc:home-mycelium-house
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=meta.current_location_id=loc:home-mycelium-house; player.location_id=loc:home-mycelium-house; turn location loc:home-mycelium-house->loc:home-mycelium-house; delta.location_after=loc:home-mycelium-house; estimated_minutes=0 for different locations

### 12. natural travel / natural return to clearing

- Issue: `natural_travel_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready delta_destination=None
- Expected: natural language should resolve to travel, commit, and move to the intended destination
- Detail: text=回空地
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 13. travel guardrails / guard same current location

- Issue: `travel_same_location_committed`
- Observed: ready=True status=ready committed=True turns=73->74 location=loc:home-mycelium-house->loc:home-mycelium-house
- Expected: same-location travel should be clarified/no-op instead of writing a changed movement turn
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 14. travel guardrails / guard retired treehouse location

- Issue: `travel_retired_location_committed`
- Observed: ready=True status=ready committed=True turns=73->74 location=loc:home-mycelium-house->loc:home-treehouse
- Expected: retired historical locations should not be accepted as normal travel destinations
- Detail: warnings=['未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。']
- Detail: errors=[]
- Detail: confirmations=None

### 15. travel guardrails / guard retired original clearing

- Issue: `travel_retired_location_committed`
- Observed: ready=True status=ready committed=True turns=73->74 location=loc:home-mycelium-house->loc:home-original-clearing
- Expected: retired historical locations should not be accepted as normal travel destinations
- Detail: warnings=['未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。']
- Detail: errors=[]
- Detail: confirmations=None

## Full Matrix

| Area | Case | Status | Observed | Expected | Issue |
| --- | --- | --- | --- | --- | --- |
| structured travel | structured to surface home clearing | PASS | ok=True turns=73->74 meta=loc:home-clearing pc=loc:home-clearing event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to mycelium city | PASS | ok=True turns=73->74 meta=loc:home-mycelium-city pc=loc:home-mycelium-city event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to D warehouse | PASS | ok=True turns=73->74 meta=loc:home-mycelium-d-warehouse pc=loc:home-mycelium-d-warehouse event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to H room | PASS | ok=True turns=73->74 meta=loc:home-mycelium-h-room pc=loc:home-mycelium-h-room event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to old hut/material warehouse | ISSUE | ok=True turns=73->74 meta=loc:home-old-hut pc=loc:home-old-hut event=travel health=True | preview ready, commit ok, current location and player entity move to destination | travel_unrouted_zero_time |
| structured travel | structured to creek | PASS | ok=True turns=73->74 meta=loc:l01-creek pc=loc:l01-creek event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to pool | PASS | ok=True turns=73->74 meta=loc:l02-pool pc=loc:l02-pool event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to pinewood | PASS | ok=True turns=73->74 meta=loc:l03-pinewood pc=loc:l03-pinewood event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to bramble ring | PASS | ok=True turns=73->74 meta=loc:l04-bramble-ring pc=loc:l04-bramble-ring event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to oldwood | PASS | ok=True turns=73->74 meta=loc:l05-oldwood pc=loc:l05-oldwood event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to waterfall | PASS | ok=True turns=73->74 meta=loc:l06-waterfall pc=loc:l06-waterfall event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to T5 overlook | PASS | ok=True turns=73->74 meta=loc:l06-t5-overlook-trough pc=loc:l06-t5-overlook-trough event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to sulfur spring | PASS | ok=True turns=73->74 meta=loc:l07-sulfur-spring pc=loc:l07-sulfur-spring event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to stone terrace | PASS | ok=True turns=73->74 meta=loc:l08-stone-terrace pc=loc:l08-stone-terrace event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to An underground home | PASS | ok=True turns=73->74 meta=loc:l09-underground-home pc=loc:l09-underground-home event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to river | PASS | ok=True turns=73->74 meta=loc:l10-river pc=loc:l10-river event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to river delta | PASS | ok=True turns=73->74 meta=loc:l11-delta pc=loc:l11-delta event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to niter crust | PASS | ok=True turns=73->74 meta=loc:l12-niter-crust pc=loc:l12-niter-crust event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to stone trough | PASS | ok=True turns=73->74 meta=loc:l13-stone-trough pc=loc:l13-stone-trough event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to humus wetland | PASS | ok=True turns=73->74 meta=loc:l14-humus-wetland pc=loc:l14-humus-wetland event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to grassland cliff | PASS | ok=True turns=73->74 meta=loc:l15-grassland-cliff pc=loc:l15-grassland-cliff event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to ashmoss hearth | PASS | ok=True turns=73->74 meta=loc:l15-east-ashmoss-hearth pc=loc:l15-east-ashmoss-hearth event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to quartz quarry | PASS | ok=True turns=73->74 meta=loc:l15-west-quartz-quarry pc=loc:l15-west-quartz-quarry event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| structured travel | structured to ashmoss settlement | PASS | ok=True turns=73->74 meta=loc:lake-ashmoss-settlement pc=loc:lake-ashmoss-settlement event=travel health=True | preview ready, commit ok, current location and player entity move to destination |  |
| natural travel | natural go to creek | PASS | ok=True turns=73->74 meta=loc:l01-creek pc=loc:l01-creek event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural walk to L1 | PASS | ok=True turns=73->74 meta=loc:l01-creek pc=loc:l01-creek event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural reach creek side | PASS | ok=True turns=73->74 meta=loc:l01-creek pc=loc:l01-creek event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to pool | PASS | ok=True turns=73->74 meta=loc:l02-pool pc=loc:l02-pool event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to L2 pool | PASS | ok=True turns=73->74 meta=loc:l02-pool pc=loc:l02-pool event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural follow creek to waterfall | PASS | ok=True turns=73->74 meta=loc:l06-waterfall pc=loc:l06-waterfall event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to L6 | PASS | ok=True turns=73->74 meta=loc:l06-waterfall pc=loc:l06-waterfall event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural climb to T5 overlook | PASS | ok=True turns=73->74 meta=loc:l06-t5-overlook-trough pc=loc:l06-t5-overlook-trough event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to pinewood | PASS | ok=True turns=73->74 meta=loc:l03-pinewood pc=loc:l03-pinewood event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural walk toward L3 | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_misread_as_query |
| natural travel | natural go to bramble ring | PASS | ok=True turns=73->74 meta=loc:l04-bramble-ring pc=loc:l04-bramble-ring event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to black bramble ring | PASS | ok=True turns=73->74 meta=loc:l04-bramble-ring pc=loc:l04-bramble-ring event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to oldwood | PASS | ok=True turns=73->74 meta=loc:l05-oldwood pc=loc:l05-oldwood event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to spring | PASS | ok=True turns=73->74 meta=loc:l07-sulfur-spring pc=loc:l07-sulfur-spring event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to sulfur spring | PASS | ok=True turns=73->74 meta=loc:l07-sulfur-spring pc=loc:l07-sulfur-spring event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to stone terrace | PASS | ok=True turns=73->74 meta=loc:l08-stone-terrace pc=loc:l08-stone-terrace event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to An home | PASS | ok=True turns=73->74 meta=loc:l09-underground-home pc=loc:l09-underground-home event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to underground tree home | PASS | ok=True turns=73->74 meta=loc:l09-underground-home pc=loc:l09-underground-home event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to river | PASS | ok=True turns=73->74 meta=loc:l10-river pc=loc:l10-river event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to delta | PASS | ok=True turns=73->74 meta=loc:l11-delta pc=loc:l11-delta event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to lakeside settlement | PASS | ok=True turns=73->74 meta=loc:lake-ashmoss-settlement pc=loc:lake-ashmoss-settlement event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to ashmoss settlement | PASS | ok=True turns=73->74 meta=loc:lake-ashmoss-settlement pc=loc:lake-ashmoss-settlement event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to niter point | PASS | ok=True turns=73->74 meta=loc:l12-niter-crust pc=loc:l12-niter-crust event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to stone trough | PASS | ok=True turns=73->74 meta=loc:l13-stone-trough pc=loc:l13-stone-trough event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to wetland | PASS | ok=True turns=73->74 meta=loc:l14-humus-wetland pc=loc:l14-humus-wetland event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to grassland cliff | PASS | ok=True turns=73->74 meta=loc:l15-grassland-cliff pc=loc:l15-grassland-cliff event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to old hearth | PASS | ok=True turns=73->74 meta=loc:l15-east-ashmoss-hearth pc=loc:l15-east-ashmoss-hearth event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to quartz quarry | ISSUE | start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_wrong_action |
| natural travel | natural return to surface clearing | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_misread_as_query |
| natural travel | natural return home | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_misread_as_query |
| natural travel | natural return to mycelium house | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_misread_as_query |
| natural travel | natural enter underground | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_misread_as_query |
| natural travel | natural go down to mycelium city | PASS | ok=True turns=73->74 meta=loc:home-mycelium-city pc=loc:home-mycelium-city event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to D warehouse | PASS | ok=True turns=73->74 meta=loc:home-mycelium-d-warehouse pc=loc:home-mycelium-d-warehouse event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to H room | PASS | ok=True turns=73->74 meta=loc:home-mycelium-h-room pc=loc:home-mycelium-h-room event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural go to material warehouse | ISSUE | ok=True turns=73->74 meta=loc:home-old-hut pc=loc:home-old-hut event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination | travel_unrouted_zero_time |
| natural travel | natural go to old hut | ISSUE | ok=True turns=73->74 meta=loc:home-old-hut pc=loc:home-old-hut event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination | travel_unrouted_zero_time |
| natural travel | natural go up to surface | ISSUE | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_destination_unresolved |
| natural travel | natural leave mycelium house to territory | ISSUE | ok=True turns=73->74 meta=loc:home-mycelium-house pc=loc:home-mycelium-house event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination | travel_meta_location_not_updated |
| natural travel | natural go to base | PASS | ok=True turns=73->74 meta=loc:home-clearing pc=loc:home-clearing event=travel health=True | natural language should resolve to travel, commit, and move to the intended destination |  |
| natural travel | natural return to clearing | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready delta_destination=None | natural language should resolve to travel, commit, and move to the intended destination | natural_travel_misread_as_query |
| multi-leg travel chain | chain house to clearing | PASS | ok=True turns=73->74 meta=loc:home-clearing pc=loc:home-clearing event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain clearing to creek | PASS | ok=True turns=74->75 meta=loc:l01-creek pc=loc:l01-creek event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain creek to pool | PASS | ok=True turns=75->76 meta=loc:l02-pool pc=loc:l02-pool event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain pool to waterfall | PASS | ok=True turns=76->77 meta=loc:l06-waterfall pc=loc:l06-waterfall event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain waterfall to river | PASS | ok=True turns=77->78 meta=loc:l10-river pc=loc:l10-river event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain river to delta | PASS | ok=True turns=78->79 meta=loc:l11-delta pc=loc:l11-delta event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain delta to settlement | PASS | ok=True turns=79->80 meta=loc:lake-ashmoss-settlement pc=loc:lake-ashmoss-settlement event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain settlement back to delta | PASS | ok=True turns=80->81 meta=loc:l11-delta pc=loc:l11-delta event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain delta back to river | PASS | ok=True turns=81->82 meta=loc:l10-river pc=loc:l10-river event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain river back to waterfall | PASS | ok=True turns=82->83 meta=loc:l06-waterfall pc=loc:l06-waterfall event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain waterfall to An home | PASS | ok=True turns=83->84 meta=loc:l09-underground-home pc=loc:l09-underground-home event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain An home to mycelium city | PASS | ok=True turns=84->85 meta=loc:home-mycelium-city pc=loc:home-mycelium-city event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain city to H room | PASS | ok=True turns=85->86 meta=loc:home-mycelium-h-room pc=loc:home-mycelium-h-room event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain H room back to city | PASS | ok=True turns=86->87 meta=loc:home-mycelium-city pc=loc:home-mycelium-city event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain city to D warehouse | PASS | ok=True turns=87->88 meta=loc:home-mycelium-d-warehouse pc=loc:home-mycelium-d-warehouse event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain D warehouse back to city | PASS | ok=True turns=88->89 meta=loc:home-mycelium-city pc=loc:home-mycelium-city event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain city to humus wetland | PASS | ok=True turns=89->90 meta=loc:l14-humus-wetland pc=loc:l14-humus-wetland event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain wetland to pinewood | PASS | ok=True turns=90->91 meta=loc:l03-pinewood pc=loc:l03-pinewood event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain pinewood back to clearing | PASS | ok=True turns=91->92 meta=loc:home-clearing pc=loc:home-clearing event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| multi-leg travel chain | chain clearing back to house | PASS | ok=True turns=92->93 meta=loc:home-mycelium-house pc=loc:home-mycelium-house event=travel health=True | each leg should preview, commit, and update location from the previous leg |  |
| travel guardrails | guard missing destination | PASS | ready=False status=clarify committed=False turns=73->73 location=loc:home-mycelium-house->loc:home-mycelium-house | missing destination should not be ready or write a turn |  |
| travel guardrails | guard nonexistent destination | PASS | ready=False status=blocked committed=False turns=73->73 location=loc:home-mycelium-house->loc:home-mycelium-house | unknown destination should not be ready or write a turn |  |
| travel guardrails | guard same current location | ISSUE | ready=True status=ready committed=True turns=73->74 location=loc:home-mycelium-house->loc:home-mycelium-house | same-location travel should be clarified/no-op instead of writing a changed movement turn | travel_same_location_committed |
| travel guardrails | guard retired treehouse location | ISSUE | ready=True status=ready committed=True turns=73->74 location=loc:home-mycelium-house->loc:home-treehouse | retired historical locations should not be accepted as normal travel destinations | travel_retired_location_committed |
| travel guardrails | guard retired original clearing | ISSUE | ready=True status=ready committed=True turns=73->74 location=loc:home-mycelium-house->loc:home-original-clearing | retired historical locations should not be accepted as normal travel destinations | travel_retired_location_committed |
