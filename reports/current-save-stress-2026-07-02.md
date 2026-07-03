# Current Save Stress Report

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.

Summary: PASS=18 WARN=1 FAIL=9

| Status | Area | Case | Observed | Expected |
|---|---|---|---|---|
| PASS | start_turn | scene query | query:scene can_proceed=True | query:scene can_proceed=True |
| PASS | start_turn | direct ammo count query | query:entity can_proceed=True | query:entity can_proceed=True |
| FAIL | start_turn | broad weapon and ammo inventory query | action:explore can_proceed=True | query:entity can_proceed=True or action:routine can_proceed=True |
| PASS | start_turn | pumpkin status query | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | start_turn | ask pumpkin status socially | action:social can_proceed=True | action:social can_proceed=True |
| FAIL | start_turn | talk to pumpkin in natural language | action:social can_proceed=False | action:social can_proceed=True |
| PASS | start_turn | patrol territory | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | start_turn | short travel | action:travel can_proceed=True | action:travel can_proceed=True |
| FAIL | start_turn | water crops command | query:entity can_proceed=True | action:routine can_proceed=True or action:craft can_proceed=True |
| FAIL | start_turn | drought and water pressure check | action:explore can_proceed=True | query:entity can_proceed=True or action:routine can_proceed=True |
| FAIL | start_turn | pending projects query | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| PASS | start_turn | compound fish-trap action | action:composite can_proceed=False | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False |
| PASS | start_turn | vague combat should ask clarification | action:combat can_proceed=False | action:combat can_proceed=False |
| PASS | start_turn | gather inventory-like target | action:gather can_proceed=True | action:gather can_proceed=True |
| PASS | start_turn | rest | action:rest can_proceed=True | action:rest can_proceed=True |
| PASS | preview_from_text | read-only ammo count stays unsaved | query status=ready ready=False | query ready=False |
| PASS | preview_from_text | patrol can be previewed | routine status=ready ready=True | routine ready=True |
| FAIL | preview_from_text | crop watering should not become read-only query | query status=ready ready=False | routine ready=True |
| PASS | preview_from_text | social preview is generated | social status=ready ready=True | social ready=True |
| PASS | preview_from_text | gather preview is generated | gather status=ready ready=True | gather ready=True |
| PASS | commit | travel commit updates location | ok=True turns=73->74 location=loc:home-clearing health=True | commit ok, turns +1, current_location_id=loc:home-clearing, health ok |
| PASS | commit | routine text preview commits | ok=True turns=73->74 latest_event=routine | commit ok, turns +1, event type routine |
| PASS | commit | combat commit decrements ammo | ok=True stun_bolts=12.0->11.0 | stun bolts 12 -> 11 |
| FAIL | preview_action | combat blocks off-location target | ready=True current=loc:home-mycelium-house target_location=loc:home-mycelium-i-room errors=() | not ready when target is in another location |
| FAIL | preview_commit_consistency | unedited gather preview should not fail at confirm | preview_ready=True commit_error=ValueError: State audit blocked turn delta:<br>- event requires output quantity but delta has no upsert_entities output.<br>- delta text/event mentions gained or stored output, but no inventory/entity upsert is present. | if preview is ready_to_save, confirm should commit; otherwise preview should ask for quantity first |
| FAIL | preview_commit_consistency | unedited social preview should not fail at confirm | preview_ready=True commit_error=ValueError: State audit blocked turn delta:<br>- event requires relationship update but delta has no relationship/project/clock update.<br>- event requires trade items but delta has no structured item or project update.<br>- delta text/event mentions social, promise or trade consequences without structured state operations. | if preview is ready_to_save, confirm should commit; otherwise preview should ask for relationship/trade result first |
| WARN | commit | human-edited gather delta stores inventory quantity | ok=True item_quantity=2.0株 audit_findings=1 | commit ok and query returns 2株 |
| PASS | player_entry | player act/confirm travel | act_ready=True confirm_ok=True location=loc:home-clearing health=ok | player act returns pending action, confirm commits, active save remains healthy |

## Details

### PASS · start_turn · scene query

- Observed: query:scene can_proceed=True
- Expected: query:scene can_proceed=True
- text=查看当前场景
- missing_required=[]
- intent_options={}

### PASS · start_turn · direct ammo count query

- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- text=查询琥珀麻箭还剩多少支
- missing_required=[]
- intent_options={}

### FAIL · start_turn · broad weapon and ammo inventory query

- Observed: action:explore can_proceed=True
- Expected: query:entity can_proceed=True or action:routine can_proceed=True
- text=检查终极复合弩和所有箭矢数量
- missing_required=[]
- intent_options={'target': 'item:ultimate-compound-crossbow', 'approach': 'careful', 'user_text': '检查终极复合弩和所有箭矢数量'}

### PASS · start_turn · pumpkin status query

- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- text=查看南瓜状态
- missing_required=[]
- intent_options={}

### PASS · start_turn · ask pumpkin status socially

- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- text=问南瓜状态
- missing_required=[]
- intent_options={'npc': 'char:pumpkin-s2', 'topic': '南瓜状态', 'approach': '直接询问', 'user_text': '问南瓜状态'}

### FAIL · start_turn · talk to pumpkin in natural language

- Observed: action:social can_proceed=False
- Expected: action:social can_proceed=True
- text=找南瓜聊聊，问问它今天状态怎么样
- missing_required=[]
- intent_options={'npc': 'char:pumpkin-s2', 'topic': '问它今天状态怎么样', 'approach': '直接询问', 'user_text': '找南瓜聊聊,问问它今天状态怎么样'}

### PASS · start_turn · patrol territory

- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- text=巡视领地，看看大家都在做什么
- missing_required=[]
- intent_options={'task': '巡视领地,看看大家都在做什么', 'user_text': '巡视领地,看看大家都在做什么'}

### PASS · start_turn · short travel

- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- text=去围墙领地/家巡查
- missing_required=[]
- intent_options={'destination': 'loc:home-clearing', 'pace': 'normal', 'user_text': '去围墙领地/家巡查'}

### FAIL · start_turn · water crops command

- Observed: query:entity can_proceed=True
- Expected: action:routine can_proceed=True or action:craft can_proceed=True
- text=给十六畦浇水
- missing_required=[]
- intent_options={}

### FAIL · start_turn · drought and water pressure check

- Observed: action:explore can_proceed=True
- Expected: query:entity can_proceed=True or action:routine can_proceed=True
- text=检查春末干旱和十六畦浇水压力
- missing_required=[]
- intent_options={'target': 'project:water-crops', 'approach': 'careful', 'user_text': '检查春末干旱和十六畦浇水压力'}

### FAIL · start_turn · pending projects query

- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- text=当前有哪些待处理项目
- missing_required=['未命中要查询的实体。']
- intent_options={}

### PASS · start_turn · compound fish-trap action

- Observed: action:composite can_proceed=False
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False
- text=去L1小溪收鱼笼
- missing_required=[]
- intent_options={}

### PASS · start_turn · vague combat should ask clarification

- Observed: action:combat can_proceed=False
- Expected: action:combat can_proceed=False
- text=用终极复合弩装填琥珀麻箭戒备射击可疑目标
- missing_required=['战斗目标未明确。', '距离/接敌状态未明确。']
- intent_options={'user_text': '用终极复合弩装填琥珀麻箭戒备射击可疑目标'}

### PASS · start_turn · gather inventory-like target

- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True
- text=采集空心菜
- missing_required=[]
- intent_options={'target': 'item:v1-3a6b64e5c1', 'user_text': '采集空心菜'}

### PASS · start_turn · rest

- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- text=休息到下午
- missing_required=[]
- intent_options={'until': 'morning', 'user_text': '休息到下午'}

### PASS · preview_from_text · read-only ammo count stays unsaved

- Observed: query status=ready ready=False
- Expected: query ready=False
- text=查询琥珀麻箭还剩多少支
- errors=[]
- warnings=[]

### PASS · preview_from_text · patrol can be previewed

- Observed: routine status=ready ready=True
- Expected: routine ready=True
- text=巡视领地，看看大家都在做什么
- errors=[]
- warnings=[]

### FAIL · preview_from_text · crop watering should not become read-only query

- Observed: query status=ready ready=False
- Expected: routine ready=True
- text=给十六畦浇水
- errors=[]
- warnings=[]

### PASS · preview_from_text · social preview is generated

- Observed: social status=ready ready=True
- Expected: social ready=True
- text=找南瓜聊聊，问问它今天状态怎么样
- errors=[]
- warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']

### PASS · preview_from_text · gather preview is generated

- Observed: gather status=ready ready=True
- Expected: gather ready=True
- text=采集空心菜
- errors=[]
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · commit · combat commit decrements ammo

- Observed: ok=True stun_bolts=12.0->11.0
- Expected: stun bolts 12 -> 11
- 火药/爆炸弹药会暴露基地附近活动痕迹。
- 疲劳状态下长时间瞄准和重装会放大失误风险。
- 活捉目标仍需后续束缚或隔离。
- 若命中非关键部位，目标可能在倒地前继续移动。
- 武器状态已由请求确认：已上弦并装填

### FAIL · preview_action · combat blocks off-location target

- Observed: ready=True current=loc:home-mycelium-house target_location=loc:home-mycelium-i-room errors=()
- Expected: not ready when target is in another location
- 火药/爆炸弹药会暴露基地附近活动痕迹。
- 疲劳状态下长时间瞄准和重装会放大失误风险。
- 活捉目标仍需后续束缚或隔离。
- 若命中非关键部位，目标可能在倒地前继续移动。
- 武器状态已由请求确认：已上弦并装填

### FAIL · preview_commit_consistency · unedited gather preview should not fail at confirm

- Observed: preview_ready=True commit_error=ValueError: State audit blocked turn delta:
- event requires output quantity but delta has no upsert_entities output.
- delta text/event mentions gained or stored output, but no inventory/entity upsert is present.
- Expected: if preview is ready_to_save, confirm should commit; otherwise preview should ask for quantity first

### FAIL · preview_commit_consistency · unedited social preview should not fail at confirm

- Observed: preview_ready=True commit_error=ValueError: State audit blocked turn delta:
- event requires relationship update but delta has no relationship/project/clock update.
- event requires trade items but delta has no structured item or project update.
- delta text/event mentions social, promise or trade consequences without structured state operations.
- Expected: if preview is ready_to_save, confirm should commit; otherwise preview should ask for relationship/trade result first

### WARN · commit · human-edited gather delta stores inventory quantity

- Observed: ok=True item_quantity=2.0株 audit_findings=1
- Expected: commit ok and query returns 2株
- [{"code": "HIGH_RISK_ITEM_METADATA_INCOMPLETE", "severity": "medium", "message": "high-risk item/entity update is missing: source, confidence.", "path": "$.upsert_entities[0]", "suggested_fix": "Record quantity, unit, location, source and confidence for high-risk inventory.", "missing_fields": ["source", "confidence"], "entity_id": "item:stress-water-spinach-harvest"}]
