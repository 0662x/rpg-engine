# Current Save Craft Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Policy: this report records craft recognition, confirmation, persistence, material and output behavior only. No engine behavior is changed by this probe.

Summary: PASS=35 ISSUE=42 TOTAL=77

## Coverage

- Natural craft: player-like Chinese craft/repair/build/cook/ferment/calibrate commands, including fully specified target/material/time strings.
- Structured craft: direct `preview_action('craft', ...)` at home, old hut, creek and mycelium-city temp-copy locations.
- Guardrails: missing target/material/time, remote materials, recipe/project targets, consumed/archived/non-item/living materials and no-recipe cases.
- Persistence checks: commit, turn/event write, location stability, tracked material quantities, output/project delta presence and state-audit findings.

## Design Risk Note

- Craft currently behaves more like a plan preview than a full material/output transaction.
- A `ready` craft delta can still have `material_consumption_required=true` with `upsert_entities=[]`, so saving may write a craft event without decrementing materials, creating output, or updating a project.
- Natural-language craft uses the entire player sentence as `target`; it does not reliably extract `target`, `materials`, `time_cost`, `project`, or recipe references.
- Common player wording such as build, expand, weave, mix, preserve, ferment and calibrate often routes to query or craft clarify without preserving structured inputs.
- Recommended direction: have the frontend/AI parse craft into a structured intent before calling the engine: `target/output`, `project`, `recipe`, `materials[{id, quantity, consume}]`, `tools`, `time_cost`, `location`, `expected_output`, `failure_cost`, and `save_mode=plan|commit_materials|commit_output`.

## Area Summary

| Area | Pass | Issue | Total |
| --- | ---: | ---: | ---: |
| craft guardrails | 16 | 0 | 16 |
| natural craft | 19 | 32 | 51 |
| structured craft | 0 | 10 | 10 |

## Issue Summary

| Issue | Count |
| --- | ---: |
| natural_craft_misread_as_query | 12 |
| natural_craft_options_not_extracted | 5 |
| natural_craft_known_recipe_not_matched | 4 |
| natural_craft_query_misrouted | 4 |
| craft_ready_without_material_delta | 3 |
| craft_recipe_missing | 3 |
| natural_craft_wrong_action | 3 |
| craft_recipe_target_blocked | 2 |
| craft_wrong_recipe_match | 2 |
| natural_craft_misread_as_routine | 2 |
| natural_craft_recipe_as_target_blocked | 2 |

## Issue Details

### 1. structured craft / powder arrow calibration full inputs at old hut

- Issue: `craft_ready_without_material_delta`
- Observed: ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: payload={'project_id': 'project:arrow-upgrade', 'recipe_id': 'recipe:powder-arrow-fuse-calibration', 'target_id': 'item:powder-arrows', 'target_name': '火药箭', 'recipe_output': {'category': 'ammunition', 'id': 'item:powder-arrows', 'name': '火药箭', 'quantity': '保持现有数量，更新可靠性', 'type': 'item', 'unit': '支'}, 'recipe_inputs': [{'consume': False, 'id': 'item:powder-arrows', 'name': '火药箭', 'quantity': '现有5支'}, {'consume': True, 'id': 'item:black-powder', 'name': '黑火药（造粒）', 'quantity': '少量补封'}], 'location_id': 'loc:home-old-hut', 'time_cost': '30分钟', 'materials': [{'query': '火药箭', 'entity_id': 'item:powder-arrows', 'availability': '随身'}, {'query': '黑火药', 'entity_id': 'item:black-powder', 'availability': '当前地点'}, {'query': '优质燧石', 'entity_id': 'item:v1-c1101bc083', 'availability': '当前地点'}, {'query': '石英磨石', 'entity_id': 'item:v1-d1e0bf81d4', 'availability': '当前地点'}], 'needs_gm_resolution': True, 'material_consumption_required': True, 'output_entity_required': False}
- Detail: upsert_count=0
- Detail: quantities={'item:black-powder': 0.5, 'item:powder-arrows': 5.0}->{'item:black-powder': 0.5, 'item:powder-arrows': 5.0}
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。', '涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。', '涉及金光或催熟：必须扣减金光，并考虑土壤肥力/环境注意。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=material_consumption_required but no upsert/material quantity change

### 2. structured craft / powder arrow calibration minimal recipe inputs

- Issue: `craft_ready_without_material_delta`
- Observed: ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: payload={'project_id': None, 'recipe_id': 'recipe:powder-arrow-fuse-calibration', 'target_id': 'item:powder-arrows', 'target_name': '火药箭', 'recipe_output': {'category': 'ammunition', 'id': 'item:powder-arrows', 'name': '火药箭', 'quantity': '保持现有数量，更新可靠性', 'type': 'item', 'unit': '支'}, 'recipe_inputs': [{'consume': False, 'id': 'item:powder-arrows', 'name': '火药箭', 'quantity': '现有5支'}, {'consume': True, 'id': 'item:black-powder', 'name': '黑火药（造粒）', 'quantity': '少量补封'}], 'location_id': 'loc:home-old-hut', 'time_cost': '45分钟', 'materials': [{'query': '火药箭', 'entity_id': 'item:powder-arrows', 'availability': '随身'}, {'query': '黑火药', 'entity_id': 'item:black-powder', 'availability': '当前地点'}], 'needs_gm_resolution': True, 'material_consumption_required': True, 'output_entity_required': False}
- Detail: upsert_count=0
- Detail: quantities={'item:black-powder': 0.5, 'item:powder-arrows': 5.0}->{'item:black-powder': 0.5, 'item:powder-arrows': 5.0}
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=material_consumption_required but no upsert/material quantity change

### 3. structured craft / powder arrow calibration alias target

- Issue: `craft_recipe_missing`
- Observed: ready=False status=needs_confirmation location=loc:home-old-hut
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。']
- Detail: confirmations=None

### 4. structured craft / thorn bolt assembly with rope at old hut

- Issue: `craft_recipe_target_blocked`
- Observed: ready=False status=needs_confirmation location=loc:home-old-hut
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。', '涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。', '涉及金光或催熟：必须扣减金光，并考虑土壤肥力/环境注意。']
- Detail: errors=['目标解析到 recipe，不是成品实体：保存前需要明确 item/equipment 成品。']
- Detail: confirmations=None

### 5. structured craft / toxic bolt assembly target existing ammo

- Issue: `craft_wrong_recipe_match`
- Observed: ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: payload={'project_id': 'project:arrow-upgrade', 'recipe_id': 'recipe:curewood-heavy-shafts', 'target_id': 'item:toxic-thorn-bolts', 'target_name': '紫黑毒箭', 'recipe_output': {'category': 'material', 'name': '愈疮木重箭杆', 'quantity': 80, 'requires_entity': True, 'type': 'item', 'unit': '支'}, 'recipe_inputs': [{'consume': True, 'id': 'plant:curewood', 'name': '愈疮木', 'quantity': '足够削80支箭杆'}, {'consume': True, 'id': 'item:v1-9852b22696', 'name': '麻纤维', 'quantity': '少量'}], 'location_id': 'loc:home-old-hut', 'time_cost': '1小时', 'materials': [{'query': '备用纤维绳', 'entity_id': 'item:v1-515c3e4a2f', 'availability': '当前地点'}], 'needs_gm_resolution': True, 'material_consumption_required': True, 'output_entity_required': False}
- Detail: upsert_count=0
- Detail: quantities={'item:v1-515c3e4a2f': 3.0, 'item:toxic-thorn-bolts': 20.0}->{'item:v1-515c3e4a2f': 3.0, 'item:toxic-thorn-bolts': 20.0}
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。', '涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。', '涉及金光或催熟：必须扣减金光，并考虑土壤肥力/环境注意。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=recipe_id=recipe:curewood-heavy-shafts expected=recipe:thorn-bolt-assembly; material_consumption_required but no upsert/material quantity change

### 6. structured craft / stun bolt assembly target existing ammo

- Issue: `craft_wrong_recipe_match`
- Observed: ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: payload={'project_id': 'project:arrow-upgrade', 'recipe_id': 'recipe:curewood-heavy-shafts', 'target_id': 'item:stun-thorn-bolts', 'target_name': '琥珀麻箭', 'recipe_output': {'category': 'material', 'name': '愈疮木重箭杆', 'quantity': 80, 'requires_entity': True, 'type': 'item', 'unit': '支'}, 'recipe_inputs': [{'consume': True, 'id': 'plant:curewood', 'name': '愈疮木', 'quantity': '足够削80支箭杆'}, {'consume': True, 'id': 'item:v1-9852b22696', 'name': '麻纤维', 'quantity': '少量'}], 'location_id': 'loc:home-old-hut', 'time_cost': '1小时', 'materials': [{'query': '备用纤维绳', 'entity_id': 'item:v1-515c3e4a2f', 'availability': '当前地点'}], 'needs_gm_resolution': True, 'material_consumption_required': True, 'output_entity_required': False}
- Detail: upsert_count=0
- Detail: quantities={'item:v1-515c3e4a2f': 3.0, 'item:stun-thorn-bolts': 12.0}->{'item:v1-515c3e4a2f': 3.0, 'item:stun-thorn-bolts': 12.0}
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。', '涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。', '涉及金光或催熟：必须扣减金光，并考虑土壤肥力/环境注意。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: errors=recipe_id=recipe:curewood-heavy-shafts expected=recipe:thorn-bolt-assembly; material_consumption_required but no upsert/material quantity change

### 7. structured craft / freestyle rope should not match thorn bolt recipe

- Issue: `craft_ready_without_material_delta`
- Observed: ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True
- Expected: freestyle rope craft should not be saved using an unrelated ammunition recipe
- Detail: prepare_location=loc:home-mycelium-house->loc:home-old-hut
- Detail: payload={'project_id': None, 'recipe_id': 'recipe:thorn-bolt-assembly', 'target_id': 'item:v1-515c3e4a2f', 'target_name': '纤维绳', 'recipe_output': {'category': 'ammunition', 'existing_outputs': ['item:stun-thorn-bolts', 'item:toxic-thorn-bolts', 'item:burst-thorn-bolts', 'item:frost-thorn-bolts'], 'name': '渊刺藤四系箭', 'quantity': '按刺数量分配', 'type': 'item', 'unit': '支'}, 'recipe_inputs': [{'consume': '消耗可用刺，不消耗根', 'id': 'plant:abyss-thorn-vine', 'name': '活体渊刺藤', 'quantity': '四类刺'}, {'consume': True, 'name': '愈疮木重箭杆', 'quantity': '按装配数量'}, {'consume': True, 'id': 'item:v1-515c3e4a2f', 'name': '备用纤维绳', 'quantity': '少量'}], 'location_id': 'loc:home-old-hut', 'time_cost': '20分钟', 'materials': [{'query': '麻纤维', 'entity_id': 'item:v1-9852b22696', 'availability': '当前地点'}], 'needs_gm_resolution': True, 'material_consumption_required': True, 'output_entity_required': False}
- Detail: upsert_count=0
- Detail: quantities={'item:v1-9852b22696': 3.0}->{'item:v1-9852b22696': 3.0}
- Detail: warnings=['涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。', '涉及金光或催熟：必须扣减金光，并考虑土壤肥力/环境注意。']
- Detail: errors=[]
- Detail: confirmations=None
- Detail: state_audit=MATERIAL_CONSUMPTION_NOT_STRUCTURED; NARRATED_CONSUMPTION_WITHOUT_STATE_OP
- Detail: errors=material_consumption_required but no upsert/material quantity change; state audit reported missing structured material/project update

### 8. structured craft / freestyle glue patch at home

- Issue: `craft_recipe_missing`
- Observed: ready=False status=needs_confirmation location=loc:home-mycelium-house
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: warnings=[]
- Detail: errors=['未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。']
- Detail: confirmations=None

### 9. structured craft / freestyle herb poultice at home

- Issue: `craft_recipe_missing`
- Observed: ready=False status=needs_confirmation location=loc:home-mycelium-house
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: warnings=[]
- Detail: errors=['未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。']
- Detail: confirmations=None

### 10. structured craft / fish trap reset at creek

- Issue: `craft_recipe_target_blocked`
- Observed: ready=False status=needs_confirmation location=loc:l01-creek
- Expected: ready craft should either persist structured material/output changes or refuse to save
- Detail: prepare_location=loc:home-mycelium-house->loc:l01-creek
- Detail: warnings=[]
- Detail: errors=['目标解析到 recipe，不是成品实体：保存前需要明确 item/equipment 成品。']
- Detail: confirmations=None

### 11. natural craft / natural powder calibration

- Issue: `natural_craft_known_recipe_not_matched`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=做火药箭引信校准
- Detail: player_message=现在还不能可靠完成 做火药箭引信校准。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 12. natural craft / natural calibrate powder arrow

- Issue: `natural_craft_recipe_as_target_blocked`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=校准火药箭
- Detail: player_message=校准火药箭 需要 GM 先确认工艺步骤、失败代价和资源变化。
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['目标解析到 recipe，不是成品实体：保存前需要明确 item/equipment 成品。', '材料不在当前可用范围：黑火药（造粒）（不在手边：loc:home-old-hut）', '材料不在当前可用范围：优质燧石（不在手边：loc:home-old-hut）', '材料不在当前可用范围：石英磨石（不在手边：loc:home-old-hut）']
- Detail: confirmations=None

### 13. natural craft / natural recalibrate powder arrow

- Issue: `natural_craft_known_recipe_not_matched`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=把火药箭重新校准一下
- Detail: player_message=现在还不能可靠完成 把火药箭重新校准一下。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 14. natural craft / natural thorn bolt assembly

- Issue: `natural_craft_recipe_as_target_blocked`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=装配渊刺藤箭
- Detail: player_message=装配渊刺藤箭 需要 GM 先确认工艺步骤、失败代价和资源变化。
- Detail: warnings=['涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。', '涉及金光或催熟：必须扣减金光，并考虑土壤肥力/环境注意。']
- Detail: errors=['目标解析到 recipe，不是成品实体：保存前需要明确 item/equipment 成品。', '材料不是 item 表实体：plant:curewood', '材料不在当前可用范围：麻纤维（不在手边：loc:home-old-hut）', '材料不在当前可用范围：石英磨石（不在手边：loc:home-old-hut）']
- Detail: confirmations=None

### 15. natural craft / natural four bolt assembly

- Issue: `natural_craft_known_recipe_not_matched`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=做四系箭装配
- Detail: player_message=现在还不能可靠完成 做四系箭装配。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=[]
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 16. natural craft / natural curewood shafts

- Issue: `natural_craft_known_recipe_not_matched`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=制作愈疮木箭杆
- Detail: player_message=现在还不能可靠完成 制作愈疮木箭杆。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=[]
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 17. natural craft / natural fish trap reset

- Issue: `natural_craft_wrong_action`
- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True
- Expected: known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed
- Detail: text=检查鱼笼并复位
- Detail: player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 18. natural craft / natural build channel

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=造水渠
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 19. natural craft / natural expand warehouse

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=扩建仓库
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 20. natural craft / natural expand mycelium side room

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=扩建菌丝城侧室
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 21. natural craft / natural rope

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=用麻纤维编一段绳子
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 22. natural craft / natural powder mix

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=试配一小份火药比例
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 23. natural craft / natural preserve fish

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=腌鱼
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 24. natural craft / natural salt vegetables

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=用盐腌一点空心菜
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 25. natural craft / natural make medicine

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=配一份消炎草药
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 26. natural craft / natural grind niter

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=把硝石针晶磨细
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 27. natural craft / natural sharpen flint

- Issue: `natural_craft_wrong_action`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=把优质燧石打磨成刀片
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

### 28. natural craft / natural glue waterproof

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=用硬化残胶封一下竹水筒
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 29. natural craft / natural repair landmine

- Issue: `natural_craft_misread_as_routine`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=检查并维护M2地雷
- Detail: player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 30. natural craft / natural make basket

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=用藤条编个小篮子
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 31. natural craft / natural make rope explicit

- Issue: `natural_craft_options_not_extracted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True
- Expected: fully specified natural craft should extract target/materials/time and become ready or close to ready
- Detail: text=用麻纤维做绳子，材料麻纤维，耗时20分钟
- Detail: player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=[]
- Detail: errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 32. natural craft / natural powder explicit

- Issue: `natural_craft_options_not_extracted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: fully specified natural craft should extract target/materials/time and become ready or close to ready
- Detail: text=把火药箭重新校准一下，材料用火药箭和黑火药，耗时30分钟
- Detail: player_message=现在还不能可靠完成 把火药箭重新校准一下,材料用火药箭和黑火药,耗时30分钟。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['目标解析到 project，不是成品实体：保存前需要明确 item/equipment 成品。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 33. natural craft / natural cup explicit

- Issue: `natural_craft_options_not_extracted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True
- Expected: fully specified natural craft should extract target/materials/time and become ready or close to ready
- Detail: text=修补竹杯裂缝，材料硬化残胶和竹杯，耗时10分钟
- Detail: player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=[]
- Detail: errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 34. natural craft / natural herb explicit

- Issue: `natural_craft_options_not_extracted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True
- Expected: fully specified natural craft should extract target/materials/time and become ready or close to ready
- Detail: text=用止血草和竹杯做外敷药糊，耗时15分钟
- Detail: player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=[]
- Detail: errors=['目标成品未指定：必须明确成品名称、数量、品质和用途。', '材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 35. natural craft / natural fish explicit

- Issue: `natural_craft_options_not_extracted`
- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True
- Expected: fully specified natural craft should extract target/materials/time and become ready or close to ready
- Detail: text=用盐腌鱼，材料小杂鱼和盐，耗时20分钟
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 36. natural craft / natural check powder project

- Issue: `natural_craft_query_misrouted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: craft progress or inventory questions should remain read-only query
- Detail: text=火药箭校准进度
- Detail: player_message=现在还不能可靠完成 火药箭校准进度。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 37. natural craft / natural recipe question

- Issue: `natural_craft_query_misrouted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: craft progress or inventory questions should remain read-only query
- Detail: text=火药箭校准需要什么材料
- Detail: player_message=现在还不能可靠完成 火药箭校准需要什么材料。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=['涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。']
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 38. natural craft / natural craft todo

- Issue: `natural_craft_query_misrouted`
- Observed: start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True
- Expected: craft progress or inventory questions should remain read-only query
- Detail: text=现在有哪些制作项目没完成
- Detail: player_message=现在还不能可靠完成 现在有哪些制作项目没完成。需要先补齐材料、配方、耗时或成品定义。
- Detail: warnings=[]
- Detail: errors=['材料未指定：保存前必须列出材料、工具、消耗量和剩余量。', '未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。', '耗时未指定：需要估算制作占用的时段和体力。']
- Detail: confirmations=None

### 39. natural craft / natural water crops not craft

- Issue: `natural_craft_query_misrouted`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True
- Expected: non-craft shorthand should not be forced into craft without action context
- Detail: text=浇水
- Detail: player_message=日常行动预演已准备好。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 40. natural craft / natural feed T2 not craft

- Issue: `natural_craft_misread_as_routine`
- Observed: start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=喂T2母猫鱼
- Detail: player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 41. natural craft / natural make shelter

- Issue: `natural_craft_misread_as_query`
- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=搭一个临时棚
- Detail: player_message=这是只读查询请求，不需要行动预演或保存。
- Detail: warnings=[]
- Detail: errors=[]
- Detail: confirmations=None

### 42. natural craft / natural sharpen arrows

- Issue: `natural_craft_wrong_action`
- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True
- Expected: craft-like wording should route to craft clarification, not query/routine/travel
- Detail: text=给箭头重新打磨
- Detail: player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- Detail: warnings=[]
- Detail: errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- Detail: confirmations=None

## Full Matrix

| Area | Case | Status | Observed | Expected | Issue |
| --- | --- | --- | --- | --- | --- |
| structured craft | powder arrow calibration full inputs at old hut | ISSUE | ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True | ready craft should either persist structured material/output changes or refuse to save | craft_ready_without_material_delta |
| structured craft | powder arrow calibration minimal recipe inputs | ISSUE | ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True | ready craft should either persist structured material/output changes or refuse to save | craft_ready_without_material_delta |
| structured craft | powder arrow calibration alias target | ISSUE | ready=False status=needs_confirmation location=loc:home-old-hut | ready craft should either persist structured material/output changes or refuse to save | craft_recipe_missing |
| structured craft | thorn bolt assembly with rope at old hut | ISSUE | ready=False status=needs_confirmation location=loc:home-old-hut | ready craft should either persist structured material/output changes or refuse to save | craft_recipe_target_blocked |
| structured craft | toxic bolt assembly target existing ammo | ISSUE | ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True | ready craft should either persist structured material/output changes or refuse to save | craft_wrong_recipe_match |
| structured craft | stun bolt assembly target existing ammo | ISSUE | ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True | ready craft should either persist structured material/output changes or refuse to save | craft_wrong_recipe_match |
| structured craft | freestyle rope should not match thorn bolt recipe | ISSUE | ok=True turns=74->75 events=79->80 location=loc:home-old-hut->loc:home-old-hut event=craft health=True | freestyle rope craft should not be saved using an unrelated ammunition recipe | craft_ready_without_material_delta |
| structured craft | freestyle glue patch at home | ISSUE | ready=False status=needs_confirmation location=loc:home-mycelium-house | ready craft should either persist structured material/output changes or refuse to save | craft_recipe_missing |
| structured craft | freestyle herb poultice at home | ISSUE | ready=False status=needs_confirmation location=loc:home-mycelium-house | ready craft should either persist structured material/output changes or refuse to save | craft_recipe_missing |
| structured craft | fish trap reset at creek | ISSUE | ready=False status=needs_confirmation location=loc:l01-creek | ready craft should either persist structured material/output changes or refuse to save | craft_recipe_target_blocked |
| craft guardrails | missing target | PASS | ready=False status=clarify committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | missing materials | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | missing time no recipe | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | unknown material | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | remote old hut material from home | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | remote creek trap from home | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | recipe target as output | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | project target as output | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | completed project target | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | consumed fish as material | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | archived backpack as material | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | missing time with unknown recipe | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | non-item material resource | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | living core as material | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | current item but no recipe | PASS | ready=False status=needs_confirmation committed=False turns=73->73 events=78->78 | unsafe or incomplete craft request should not be ready or write state |  |
| craft guardrails | dangerous powder no explicit safety project | PASS | ready=False status=needs_confirmation committed=False turns=74->74 events=79->79 | unsafe or incomplete craft request should not be ready or write state |  |
| natural craft | natural powder calibration | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_known_recipe_not_matched |
| natural craft | natural calibrate powder arrow | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_recipe_as_target_blocked |
| natural craft | natural recalibrate powder arrow | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_known_recipe_not_matched |
| natural craft | natural thorn bolt assembly | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_recipe_as_target_blocked |
| natural craft | natural four bolt assembly | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_known_recipe_not_matched |
| natural craft | natural curewood shafts | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_known_recipe_not_matched |
| natural craft | natural fish trap reset | ISSUE | start=action:explore can_proceed=True preview=action:explore ready=True status=ready no_write=True | known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed | natural_craft_wrong_action |
| natural craft | natural fish trap repair | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural repair crossbow | PASS | start=action:craft can_proceed=False preview=action:craft ready=False status=needs_confirmation no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural repair channel | PASS | start=action:craft can_proceed=False preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural build channel | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural make trap | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural repair wall | PASS | start=action:craft can_proceed=False preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural expand warehouse | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural expand mycelium side room | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural rope | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural repair cup | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural herb poultice | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural powder mix | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural resin waterproofing | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural cook meal | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural preserve fish | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural salt vegetables | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural make medicine | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural grind niter | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural sharpen flint | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_wrong_action |
| natural craft | natural glue waterproof | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural repair landmine | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_routine |
| natural craft | natural make fuse | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural make basket | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural make rope explicit | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | fully specified natural craft should extract target/materials/time and become ready or close to ready | natural_craft_options_not_extracted |
| natural craft | natural powder explicit | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | fully specified natural craft should extract target/materials/time and become ready or close to ready | natural_craft_options_not_extracted |
| natural craft | natural cup explicit | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | fully specified natural craft should extract target/materials/time and become ready or close to ready | natural_craft_options_not_extracted |
| natural craft | natural herb explicit | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | fully specified natural craft should extract target/materials/time and become ready or close to ready | natural_craft_options_not_extracted |
| natural craft | natural fish explicit | ISSUE | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | fully specified natural craft should extract target/materials/time and become ready or close to ready | natural_craft_options_not_extracted |
| natural craft | natural check powder project | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | craft progress or inventory questions should remain read-only query | natural_craft_query_misrouted |
| natural craft | natural recipe question | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | craft progress or inventory questions should remain read-only query | natural_craft_query_misrouted |
| natural craft | natural ammo count | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft progress or inventory questions should remain read-only query |  |
| natural craft | natural material count | PASS | start=query:entity can_proceed=True preview=action:query ready=False status=ready no_write=True | craft progress or inventory questions should remain read-only query |  |
| natural craft | natural craft todo | ISSUE | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | craft progress or inventory questions should remain read-only query | natural_craft_query_misrouted |
| natural craft | natural water crops not craft | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True | non-craft shorthand should not be forced into craft without action context | natural_craft_query_misrouted |
| natural craft | natural feed T2 not craft | ISSUE | start=action:routine can_proceed=True preview=action:routine ready=True status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_routine |
| natural craft | natural make shelter | ISSUE | start=query:entity can_proceed=False preview=action:query ready=False status=ready no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_misread_as_query |
| natural craft | natural make sign | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural patch backpack | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural ferment vinegar | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural oil coating | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural sharpen arrows | ISSUE | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel | natural_craft_wrong_action |
| natural craft | natural make bait | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural repair warehouse shelf | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=clarify no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
| natural craft | natural mycelium room door | PASS | start=action:craft can_proceed=True preview=action:craft ready=False status=needs_confirmation no_write=True | craft-like wording should route to craft clarification, not query/routine/travel |  |
