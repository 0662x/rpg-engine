# Current Save Query Recognition Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Focus: query routing and query output usefulness only; action recognition cases are recorded separately.
Policy: this report records recognition/query issues only. No engine behavior is changed by this probe.

Summary: PASS=100 ISSUE=59 TOTAL=159

## Issue Summary

| Issue | Count |
|---|---:|
| `right_mode_but_wrong_proceed_state` | 22 |
| `query_misread_as_action` | 12 |
| `query_entity_not_found` | 10 |
| `wrong_action_or_query_kind` | 10 |
| `query_route_gap` | 5 |

## Issue By Area

| Area | Count |
|---|---:|
| scene/status query | 9 |
| scene/status query extended | 9 |
| mycelium query | 8 |
| query output extended | 8 |
| query output | 7 |
| inventory query | 5 |
| clock/project query | 3 |
| field query extended | 3 |
| inventory query extended | 2 |
| ammo query extended | 1 |
| character query extended | 1 |
| location query extended | 1 |
| mycelium query extended | 1 |
| project query extended | 1 |

## Issues

| Area | Case | Text | Observed | Expected | Issue |
|---|---|---|---|---|---|
| scene/status query | where am I | `我现在在哪` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query | current situation | `现在是什么情况` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query | today status | `今天上午当前状态` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query | current board | `看一下当前局面` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query | nearby objects | `我身边有什么` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query | turn info | `当前回合信息` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query | urgent issues | `现在最紧急的事情是什么` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| scene/status query | pending projects | `现在有哪些项目没处理` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| scene/status query | what should do | `我现在该干嘛` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| inventory query | all arrows | `所有箭矢数量` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| inventory query | usable ammo | `我能用的弹药有哪些` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| inventory query | crossbow and ammo | `检查终极复合弩和所有箭矢数量` | action:routine can_proceed=True | query:entity can_proceed=True or query:scene can_proceed=True | `query_misread_as_action` |
| inventory query | food stock | `还有多少能吃的` | action:gather can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `query_misread_as_action` |
| inventory query | kitchen food | `厨房存粮情况` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | mycelium people total | `菌丝人总数是多少` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | unit list | `菌丝单位名单` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | how many mycelium people | `现在有多少菌丝人` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | mushroom count | `目前菌丝蘑菇有几个` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | unit split counts | `腐工蕈锐孢蕈思菌蕈各有几个` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | worker count | `腐工蕈数量` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | sharp spore count | `锐孢蕈数量` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query | thinking fungus count | `思菌蕈数量` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| clock/project query | drought clock | `春末干旱进度到几格了` | action:travel can_proceed=False | query:entity can_proceed=True | `query_misread_as_action` |
| clock/project query | base upkeep clock | `基地维护压力多少` | action:routine can_proceed=True | query:entity can_proceed=True | `query_misread_as_action` |
| clock/project query | water project | `十六畦浇水多久没做了` | action:routine can_proceed=True | query:entity can_proceed=True | `query_misread_as_action` |
| scene/status query extended | where exact location | `我现在具体在什么地点` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query extended | time and weather | `现在时间和天气怎么样` | query:entity can_proceed=True | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query extended | visible exits | `附近能去哪些地方` | action:travel can_proceed=False | query:scene can_proceed=True | `query_misread_as_action` |
| scene/status query extended | current companions | `我身边现在有谁` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| scene/status query extended | current risks | `当前有哪些风险` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| scene/status query extended | today priorities | `今天优先事项是什么` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| scene/status query extended | pending confirmations | `现在有哪些需要确认的事` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True | `right_mode_but_wrong_proceed_state` |
| scene/status query extended | last saved turn | `最近一次保存到哪个回合` | action:travel can_proceed=False | query:scene can_proceed=True | `query_misread_as_action` |
| scene/status query extended | current resources nearby | `当前地点附近有什么资源` | query:entity can_proceed=False | query:scene can_proceed=True | `wrong_action_or_query_kind` |
| inventory query extended | acid resin amount | `酸残胶还剩多少ml` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| inventory query extended | landmine stock | `地雷现在有几枚` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| ammo query extended | all special bolts | `特殊箭矢分别还剩几支` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| character query extended | t2 status | `T2母猫情况` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| mycelium query extended | mycelium irrigation capacity | `菌丝能帮忙灌溉到什么程度` | action:routine can_proceed=True | query:entity can_proceed=True | `query_misread_as_action` |
| field query extended | field water pressure | `十六畦浇水压力` | action:routine can_proceed=True | query:entity can_proceed=True | `query_misread_as_action` |
| field query extended | new fields status | `新增畦17到27状态` | action:travel can_proceed=False | query:entity can_proceed=True | `query_misread_as_action` |
| field query extended | harvestable crops | `哪些作物现在能收` | action:gather can_proceed=False | query:entity can_proceed=True | `query_misread_as_action` |
| location query extended | i room status | `I室隔离区情况` | query:entity can_proceed=False | query:entity can_proceed=True | `right_mode_but_wrong_proceed_state` |
| project query extended | base maintenance | `基地维护压力详情` | action:routine can_proceed=True | query:entity can_proceed=True | `query_misread_as_action` |
| query output | mycelium people total | `菌丝人总数是多少` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output | mycelium units count | `地下菌丝城现在有多少单位` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output | fungus worker split | `腐工蕈锐孢蕈思菌蕈各有几个` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output | stun bolts count | `琥珀麻箭还剩几支` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output | all arrows count | `所有箭矢数量` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output | water spinach count | `空心菜还有多少株` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output | urgent issues | `现在最紧急的事情是什么` | query/route gap | route query:entity can_proceed=True or query:scene can_proceed=True; useful query output | `query_route_gap` |
| query output extended | current situation scene | `现在是什么情况` | query/route gap | route query:scene can_proceed=True; useful query output | `query_route_gap` |
| query output extended | urgent things scene | `当前最紧急的事情` | query/route gap | route query:entity can_proceed=True or query:scene can_proceed=True; useful query output | `query_route_gap` |
| query output extended | water spinach stock | `空心菜库存` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output extended | stun bolts direct extra | `琥珀麻箭数量` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output extended | powder arrows direct extra | `火药箭数量` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output extended | eve direct extra | `夏娃现在状态` | query/route gap | route query:entity can_proceed=True; useful query output | `query_entity_not_found` |
| query output extended | base upkeep direct | `基地维护压力` | query/route gap | route query:entity can_proceed=True; useful query output | `query_route_gap` |
| query output extended | home house location | `六边形菌丝复合屋` | query/route gap | route query:entity can_proceed=True; useful query output | `query_route_gap` |

## Full Matrix

| Status | Area | Case | Text | Observed | Expected |
|---|---|---|---|---|---|
| PASS | scene/status query | look around | `看一下周围` | query:scene can_proceed=True | query:scene can_proceed=True |
| ISSUE | scene/status query | where am I | `我现在在哪` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query | current situation | `现在是什么情况` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query | today status | `今天上午当前状态` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query | current board | `看一下当前局面` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query | nearby objects | `我身边有什么` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query | turn info | `当前回合信息` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query | urgent issues | `现在最紧急的事情是什么` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| PASS | scene/status query | pending todo | `当前有哪些待办` | query:scene can_proceed=True | query:entity can_proceed=True or query:scene can_proceed=True |
| ISSUE | scene/status query | pending projects | `现在有哪些项目没处理` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| ISSUE | scene/status query | what should do | `我现在该干嘛` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| PASS | inventory query | stun bolt count | `琥珀麻箭还剩几支` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query | stun bolt direct | `查一下琥珀麻箭` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | inventory query | all arrows | `所有箭矢数量` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | inventory query | usable ammo | `我能用的弹药有哪些` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | inventory query | crossbow and ammo | `检查终极复合弩和所有箭矢数量` | action:routine can_proceed=True | query:entity can_proceed=True or query:scene can_proceed=True |
| PASS | inventory query | powder arrows | `我还有多少火药箭` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query | toxic old bolts | `旧毒弩箭还有几支能用` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query | water spinach count | `空心菜还有多少株` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | inventory query | food stock | `还有多少能吃的` | action:gather can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| ISSUE | inventory query | kitchen food | `厨房存粮情况` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| PASS | inventory query | root mycelium count | `根源菌丝有几面` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query | salt count | `盐还剩多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query | fish trap count | `竹编鱼笼有几个` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | mycelium query | mycelium people total | `菌丝人总数是多少` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | mycelium query | mycelium population | `菌丝城人口` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | mycelium query | unit list | `菌丝单位名单` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | mycelium query | how many mycelium people | `现在有多少菌丝人` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | mycelium query | mushroom count | `目前菌丝蘑菇有几个` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | mycelium query | mycelium city units | `地下菌丝城现在有多少单位` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | mycelium query | unit split counts | `腐工蕈锐孢蕈思菌蕈各有几个` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | mycelium query | worker count | `腐工蕈数量` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | mycelium query | sharp spore count | `锐孢蕈数量` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | mycelium query | thinking fungus count | `思菌蕈数量` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | mycelium query | eve dispatch capacity | `夏娃现在能调度多少菌丝单位` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | mycelium query | capacity limit | `夏娃和菌丝城容量上限` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | clock/project query | drought clock | `春末干旱进度到几格了` | action:travel can_proceed=False | query:entity can_proceed=True |
| ISSUE | clock/project query | base upkeep clock | `基地维护压力多少` | action:routine can_proceed=True | query:entity can_proceed=True |
| ISSUE | clock/project query | water project | `十六畦浇水多久没做了` | action:routine can_proceed=True | query:entity can_proceed=True |
| PASS | clock/project query | ashmoss trust | `灰藓族互信现在几格` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | scene/status query extended | where exact location | `我现在具体在什么地点` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query extended | time and weather | `现在时间和天气怎么样` | query:entity can_proceed=True | query:scene can_proceed=True |
| PASS | scene/status query extended | current safety | `当前周围安全吗` | query:scene can_proceed=True | query:scene can_proceed=True |
| ISSUE | scene/status query extended | visible exits | `附近能去哪些地方` | action:travel can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query extended | current companions | `我身边现在有谁` | query:entity can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query extended | current risks | `当前有哪些风险` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| ISSUE | scene/status query extended | today priorities | `今天优先事项是什么` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| ISSUE | scene/status query extended | pending confirmations | `现在有哪些需要确认的事` | query:entity can_proceed=False | query:entity can_proceed=True or query:scene can_proceed=True |
| ISSUE | scene/status query extended | last saved turn | `最近一次保存到哪个回合` | action:travel can_proceed=False | query:scene can_proceed=True |
| ISSUE | scene/status query extended | current resources nearby | `当前地点附近有什么资源` | query:entity can_proceed=False | query:scene can_proceed=True |
| PASS | inventory query extended | water amount | `竹水筒里还有多少水` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query extended | salt amount | `盐现在还够不够` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query extended | berries amount | `红浆果还剩多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query extended | vinegar amount | `浆果醋还有多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query extended | oil amount | `松子油库存` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query extended | resin amount | `普通残胶和硬化残胶各有多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | inventory query extended | acid resin amount | `酸残胶还剩多少ml` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | inventory query extended | niter sulfur stock | `硝石和硫磺库存` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | inventory query extended | black powder stock | `黑火药还有多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | inventory query extended | landmine stock | `地雷现在有几枚` | query:entity can_proceed=False | query:entity can_proceed=True |
| ISSUE | ammo query extended | all special bolts | `特殊箭矢分别还剩几支` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | ammo query extended | toxic bolt count | `紫黑毒箭数量` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | ammo query extended | frost bolt count | `霜白冻箭数量` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | ammo query extended | burst bolt count | `赤红炸箭数量` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | ammo query extended | plain bolt count | `旧普通箭数量` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | equipment query extended | crossbow detail | `终极复合弩参数` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | equipment query extended | armor detail | `我身上的护甲有哪些` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | equipment query extended | backpack detail | `竹藤背包情况` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | character query extended | pumpkin status | `南瓜现在状态` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | character query extended | an status | `An现在在哪里` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | character query extended | young status | `小的现在情况` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | character query extended | eve status | `夏娃现在状态` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | character query extended | t2 status | `T2母猫情况` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | mycelium query extended | mycelium core | `母孢子树现在怎么样` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | mycelium query extended | mycelium city rooms | `菌丝城有哪些房间` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | mycelium query extended | mycelium irrigation capacity | `菌丝能帮忙灌溉到什么程度` | action:routine can_proceed=True | query:entity can_proceed=True |
| PASS | field query extended | field six status | `畦6空心菜状态` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | field query extended | field water pressure | `十六畦浇水压力` | action:routine can_proceed=True | query:entity can_proceed=True |
| ISSUE | field query extended | new fields status | `新增畦17到27状态` | action:travel can_proceed=False | query:entity can_proceed=True |
| ISSUE | field query extended | harvestable crops | `哪些作物现在能收` | action:gather can_proceed=False | query:entity can_proceed=True |
| PASS | clock query extended | forest attention clock | `森林注意进度` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | clock query extended | civilization rumor clock | `文明传闻钟多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | clock query extended | lake suspicion clock | `湖边聚落警惕几格` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | clock query extended | fatigue clock | `疲劳压力现在多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | clock query extended | soil clock | `土壤肥力消耗多少` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | location query extended | old hut status | `旧小屋现在有什么` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | location query extended | l1 creek status | `L1小溪情况` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | location query extended | d warehouse status | `D仓库里有什么` | query:entity can_proceed=True | query:entity can_proceed=True |
| PASS | location query extended | h room status | `H室情况` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | location query extended | i room status | `I室隔离区情况` | query:entity can_proceed=False | query:entity can_proceed=True |
| PASS | project query extended | crafting breakthrough | `工艺突破进度` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | project query extended | base maintenance | `基地维护压力详情` | action:routine can_proceed=True | query:entity can_proceed=True |
| PASS | project query extended | ashmoss trust detail | `灰藓族互信详情` | query:entity can_proceed=True | query:entity can_proceed=True |
| ISSUE | query output | mycelium people total | `菌丝人总数是多少` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output | mycelium species direct | `幽壤菌裔` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output | eve direct | `夏娃` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output | mycelium city direct | `地下菌丝城` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output | mycelium units count | `地下菌丝城现在有多少单位` | query/route gap | route query:entity can_proceed=True; useful query output |
| ISSUE | query output | fungus worker split | `腐工蕈锐孢蕈思菌蕈各有几个` | query/route gap | route query:entity can_proceed=True; useful query output |
| ISSUE | query output | stun bolts count | `琥珀麻箭还剩几支` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output | stun bolts direct | `琥珀麻箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output | all arrows count | `所有箭矢数量` | query/route gap | route query:entity can_proceed=True; useful query output |
| ISSUE | query output | water spinach count | `空心菜还有多少株` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output | water spinach direct | `空心菜` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output | pending projects | `当前有哪些待办` | route ok; query useful | route query:scene can_proceed=True; useful query output |
| ISSUE | query output | urgent issues | `现在最紧急的事情是什么` | query/route gap | route query:entity can_proceed=True or query:scene can_proceed=True; useful query output |
| PASS | query output extended | current location scene | `看一下周围` | route ok; query useful | route query:scene can_proceed=True; useful query output |
| ISSUE | query output extended | current situation scene | `现在是什么情况` | query/route gap | route query:scene can_proceed=True; useful query output |
| ISSUE | query output extended | urgent things scene | `当前最紧急的事情` | query/route gap | route query:entity can_proceed=True or query:scene can_proceed=True; useful query output |
| PASS | query output extended | water bottle direct | `竹水筒` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | salt direct | `盐` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | red berries direct | `红浆果` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | berry vinegar direct | `浆果醋` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | pine nut oil direct | `松子油` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | ordinary resin direct | `普通残胶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | hardened resin direct | `硬化残胶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | acid resin direct | `酸残胶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | niter direct | `硝石针晶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | sulfur shards direct | `硫磺碎晶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | black powder direct | `黑火药` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output extended | water spinach stock | `空心菜库存` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | amaranth direct | `苋菜大叶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | lettuce direct | `红叶生菜` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | wild onion direct | `野葱` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | garlic leaf direct | `蒜叶` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | ginger direct | `生姜` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output extended | stun bolts direct extra | `琥珀麻箭数量` | query/route gap | route query:entity can_proceed=True; useful query output |
| ISSUE | query output extended | powder arrows direct extra | `火药箭数量` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | toxic bolts direct | `紫黑毒箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | frost bolts direct | `霜白冻箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | burst bolts direct | `赤红炸箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | plain bolts direct | `旧普通箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | poison bolts direct | `旧毒弩箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | bamboo arrows direct | `竹箭` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | ultimate crossbow direct | `终极复合弩` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | backpack direct | `竹藤背包` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | landmine direct | `M2地雷` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | fish trap direct | `竹编鱼笼` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | pumpkin direct | `南瓜` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | an direct extra | `An现在在哪里` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | young direct | `小的` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output extended | eve direct extra | `夏娃现在状态` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | ashmoss trust direct | `灰藓族互信` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | drought clock direct | `春末干旱` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output extended | base upkeep direct | `基地维护压力` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | forest attention direct | `森林注意` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | civilization rumor direct | `文明传闻` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | soil depletion direct | `土壤肥力消耗` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | field six direct | `畦6 空心菜` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | field ten direct | `畦10 盐角草` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | field sixteen direct | `畦16 储存南瓜` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| ISSUE | query output extended | home house location | `六边形菌丝复合屋` | query/route gap | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | old hut location | `旧小屋` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | l1 creek location | `L1小溪` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | d warehouse location | `D仓库` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | h room location | `H室` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | i room location | `I室` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | root mycelium direct | `根源菌丝` | route ok; query useful | route query:entity can_proceed=True; useful query output |
| PASS | query output extended | mother spore tree direct | `母孢子树` | route ok; query useful | route query:entity can_proceed=True; useful query output |

## Details

### PASS · scene/status query · look around

- Text: `看一下周围`
- Observed: query:scene can_proceed=True
- Expected: query:scene can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · scene/status query · where am I

- Text: `我现在在哪`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · current situation

- Text: `现在是什么情况`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · today status

- Text: `今天上午当前状态`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · current board

- Text: `看一下当前局面`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · nearby objects

- Text: `我身边有什么`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · turn info

- Text: `当前回合信息`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · urgent issues

- Text: `现在最紧急的事情是什么`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · scene/status query · pending todo

- Text: `当前有哪些待办`
- Observed: query:scene can_proceed=True
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · scene/status query · pending projects

- Text: `现在有哪些项目没处理`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query · what should do

- Text: `我现在该干嘛`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · inventory query · stun bolt count

- Text: `琥珀麻箭还剩几支`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query · stun bolt direct

- Text: `查一下琥珀麻箭`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · inventory query · all arrows

- Text: `所有箭矢数量`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · inventory query · usable ammo

- Text: `我能用的弹药有哪些`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · inventory query · crossbow and ammo

- Text: `检查终极复合弩和所有箭矢数量`
- Observed: action:routine can_proceed=True
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '检查终极复合弩和所有箭矢数量'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · inventory query · powder arrows

- Text: `我还有多少火药箭`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query · toxic old bolts

- Text: `旧毒弩箭还有几支能用`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query · water spinach count

- Text: `空心菜还有多少株`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · inventory query · food stock

- Text: `还有多少能吃的`
- Observed: action:gather can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=['采集目标或探索范围未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '还有多少能吃的'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · inventory query · kitchen food

- Text: `厨房存粮情况`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · inventory query · root mycelium count

- Text: `根源菌丝有几面`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query · salt count

- Text: `盐还剩多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query · fish trap count

- Text: `竹编鱼笼有几个`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · mycelium query · mycelium people total

- Text: `菌丝人总数是多少`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · mycelium query · mycelium population

- Text: `菌丝城人口`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · mycelium query · unit list

- Text: `菌丝单位名单`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · mycelium query · how many mycelium people

- Text: `现在有多少菌丝人`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · mycelium query · mushroom count

- Text: `目前菌丝蘑菇有几个`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · mycelium query · mycelium city units

- Text: `地下菌丝城现在有多少单位`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · mycelium query · unit split counts

- Text: `腐工蕈锐孢蕈思菌蕈各有几个`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · mycelium query · worker count

- Text: `腐工蕈数量`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · mycelium query · sharp spore count

- Text: `锐孢蕈数量`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · mycelium query · thinking fungus count

- Text: `思菌蕈数量`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · mycelium query · eve dispatch capacity

- Text: `夏娃现在能调度多少菌丝单位`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · mycelium query · capacity limit

- Text: `夏娃和菌丝城容量上限`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · clock/project query · drought clock

- Text: `春末干旱进度到几格了`
- Observed: action:travel can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · clock/project query · base upkeep clock

- Text: `基地维护压力多少`
- Observed: action:routine can_proceed=True
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '基地维护压力多少'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · clock/project query · water project

- Text: `十六畦浇水多久没做了`
- Observed: action:routine can_proceed=True
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '十六畦浇水多久没做了', 'user_text': '十六畦浇水多久没做了'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · clock/project query · ashmoss trust

- Text: `灰藓族互信现在几格`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · scene/status query extended · where exact location

- Text: `我现在具体在什么地点`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · time and weather

- Text: `现在时间和天气怎么样`
- Observed: query:entity can_proceed=True
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · scene/status query extended · current safety

- Text: `当前周围安全吗`
- Observed: query:scene can_proceed=True
- Expected: query:scene can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · scene/status query extended · visible exits

- Text: `附近能去哪些地方`
- Observed: action:travel can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · current companions

- Text: `我身边现在有谁`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · current risks

- Text: `当前有哪些风险`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · today priorities

- Text: `今天优先事项是什么`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · pending confirmations

- Text: `现在有哪些需要确认的事`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True or query:scene can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · last saved turn

- Text: `最近一次保存到哪个回合`
- Observed: action:travel can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · scene/status query extended · current resources nearby

- Text: `当前地点附近有什么资源`
- Observed: query:entity can_proceed=False
- Expected: query:scene can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · inventory query extended · water amount

- Text: `竹水筒里还有多少水`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query extended · salt amount

- Text: `盐现在还够不够`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query extended · berries amount

- Text: `红浆果还剩多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query extended · vinegar amount

- Text: `浆果醋还有多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query extended · oil amount

- Text: `松子油库存`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query extended · resin amount

- Text: `普通残胶和硬化残胶各有多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · inventory query extended · acid resin amount

- Text: `酸残胶还剩多少ml`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · inventory query extended · niter sulfur stock

- Text: `硝石和硫磺库存`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · inventory query extended · black powder stock

- Text: `黑火药还有多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · inventory query extended · landmine stock

- Text: `地雷现在有几枚`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · ammo query extended · all special bolts

- Text: `特殊箭矢分别还剩几支`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · ammo query extended · toxic bolt count

- Text: `紫黑毒箭数量`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · ammo query extended · frost bolt count

- Text: `霜白冻箭数量`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · ammo query extended · burst bolt count

- Text: `赤红炸箭数量`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · ammo query extended · plain bolt count

- Text: `旧普通箭数量`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · equipment query extended · crossbow detail

- Text: `终极复合弩参数`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · equipment query extended · armor detail

- Text: `我身上的护甲有哪些`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · equipment query extended · backpack detail

- Text: `竹藤背包情况`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · character query extended · pumpkin status

- Text: `南瓜现在状态`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · character query extended · an status

- Text: `An现在在哪里`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · character query extended · young status

- Text: `小的现在情况`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · character query extended · eve status

- Text: `夏娃现在状态`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · character query extended · t2 status

- Text: `T2母猫情况`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · mycelium query extended · mycelium core

- Text: `母孢子树现在怎么样`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · mycelium query extended · mycelium city rooms

- Text: `菌丝城有哪些房间`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · mycelium query extended · mycelium irrigation capacity

- Text: `菌丝能帮忙灌溉到什么程度`
- Observed: action:routine can_proceed=True
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '菌丝能帮忙灌溉到什么程度'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · field query extended · field six status

- Text: `畦6空心菜状态`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · field query extended · field water pressure

- Text: `十六畦浇水压力`
- Observed: action:routine can_proceed=True
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '十六畦浇水压力', 'user_text': '十六畦浇水压力'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · field query extended · new fields status

- Text: `新增畦17到27状态`
- Observed: action:travel can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · field query extended · harvestable crops

- Text: `哪些作物现在能收`
- Observed: action:gather can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=['target', '采集目标或探索范围未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=gather
- intent_status=clarify
- intent_options={}
- preview=gather status=clarify ready=False
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · clock query extended · forest attention clock

- Text: `森林注意进度`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · clock query extended · civilization rumor clock

- Text: `文明传闻钟多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · clock query extended · lake suspicion clock

- Text: `湖边聚落警惕几格`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · clock query extended · fatigue clock

- Text: `疲劳压力现在多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · clock query extended · soil clock

- Text: `土壤肥力消耗多少`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · location query extended · old hut status

- Text: `旧小屋现在有什么`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · location query extended · l1 creek status

- Text: `L1小溪情况`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · location query extended · d warehouse status

- Text: `D仓库里有什么`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### PASS · location query extended · h room status

- Text: `H室情况`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · location query extended · i room status

- Text: `I室隔离区情况`
- Observed: query:entity can_proceed=False
- Expected: query:entity can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · project query extended · crafting breakthrough

- Text: `工艺突破进度`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · project query extended · base maintenance

- Text: `基地维护压力详情`
- Observed: action:routine can_proceed=True
- Expected: query:entity can_proceed=True
- Issue: `query_misread_as_action`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '基地维护压力详情', 'user_text': '基地维护压力详情'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · project query extended · ashmoss trust detail

- Text: `灰藓族互信详情`
- Observed: query:entity can_proceed=True
- Expected: query:entity can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。

### ISSUE · query output · mycelium people total

- Text: `菌丝人总数是多少`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=False
- query_kind=entity
- query_excerpt=未找到实体：`菌丝人总数是多少` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- note=用户点名失败场景：应该能命中菌丝族群/单位统计，而不是未找到实体。
- missing required ['数量']; query returned 未找到实体
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · query output · mycelium species direct

- Text: `幽壤菌裔`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 物种：幽壤菌裔 | 字段 | 值 | |------|----| | ID | `species:youhrang-mycelium` | | 类型 | 物种 | | 位置 | 未知 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 由母孢子树/主母菌核统合的菌丝蘑菇文明体系，可生产腐工蕈、锐孢蕈、思菌蕈等分工单位。 ### 结构化信息 - behavior: 服从夏娃/主母菌核调度；按单位类型执行腐解、战斗、思考、仓储、厨房和农耕任务；通过菌丝网络感知基地状态 - 发现线索: 线索文本：由母孢子树/主母菌核演化并在第25天命名夏娃。；确认方式：夏娃汇报；菌丝城房间和单位清点；观察地表菌毯范围 - habitat: 空地/家地下；地下菌丝城；地表菌毯和外派中继点 - outputs: 腐工蕈劳动力；锐孢蕈防卫/侦察；思菌蕈信息处理；岩铠蕈防护单位；地下房间和隧道扩展 - 风险: 扩张消耗水和养分；外派规模过大会暴露基地；未知智慧种可能将其视为威胁或奇迹 - 未知项: 长期自我意识边界；与灰藓族/外部文明的文化兼容性 - 用途: 基地自动化；灌溉和农耕；仓储

### PASS · query output · eve direct

- Text: `夏娃`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 人物/生物：夏娃 | 字段 | 值 | |------|----| | ID | `char:eve-mycelium-core` | | 类型 | 角色 | | 位置 | loc:home-mycelium-city | | 状态 | 活跃 | | 种族 | species:youhrang-mycelium | | 角色 | 基地调度中枢/共生伙伴/菌丝文明种子 | | 态度 | bonded | | 信任 | 6 | | 健康 | active; 24层沟回; 金光累计1186%; 律动约16次/分 | ### 摘要 夏娃位于地下菌丝城，是菌丝城调度核心；可询问水路、隧道、仓储、I室隔离和菌群运行状态。

### PASS · query output · mycelium city direct

- Text: `地下菌丝城`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 地点：地下菌丝城 | 字段 | 值 | |------|----| | ID | `loc:home-mycelium-city` | | 状态 | 活跃 | | 生态 | 地下菌丝城 | | 安全等级 | 设防 | | 距家耗时 | 1 分钟 | ### 摘要 领地下方的菌丝城市和生产中枢。 ### 已知资源 - 腐工蕈 - 锐孢蕈 - 思菌蕈 - 地下仓库 - 菌丝厨房 ### 出口/路线 - 六边形菌丝复合屋竖井 - 西隧至L9 - 各功能侧室 ### 备注 - author_polish: current_day_role：地下调度中枢；D仓库存发酵/调料，H室住An和小的，I室隔离T2母猫与幼崽。；route_note：通L7、L13、L14的隧道已结构化，但行动前仍检查通风、塌方、水压和外部痕迹。；来源：rp/docs/isekai-farm-save-content-polish-plan.md D-02 - 内容补强: 批次：0013 高频内容补强；置信规则：已确认事实保持已确认；不确定设定写入未知/待确认问题；方法：基于既有存档的合理推断 - 发现线索

### ISSUE · query output · mycelium units count

- Text: `地下菌丝城现在有多少单位`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`地下菌丝城现在有多少单位` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['数量']; query returned 未找到实体

### ISSUE · query output · fungus worker split

- Text: `腐工蕈锐孢蕈思菌蕈各有几个`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=False
- query_kind=entity
- query_excerpt=未找到实体：`腐工蕈锐孢蕈思菌蕈各有几个` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['数量']; query returned 未找到实体
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · query output · stun bolts count

- Text: `琥珀麻箭还剩几支`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`琥珀麻箭还剩几支` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['12支']; query returned 未找到实体

### PASS · query output · stun bolts direct

- Text: `琥珀麻箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：琥珀麻箭 | 字段 | 值 | |------|----| | ID | `item:stun-thorn-bolts` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | pc:shenyan | | 状态 | 活跃 | | 数量 | 12支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 控制型麻痹箭；第25天围猎T2消耗8支后当前剩余12支，适合活捉和打断。 ### 弹药档案 | 字段 | 值 | |------|----| | 兼容武器 | item:ultimate-compound-crossbow | | 效果类型 | stun | | 主要效果 | 命中后麻痹、倒地或动作迟滞 | | 适用场景 | 活捉、打断冲锋、控制中小型活体目标 | | 射程影响 | 标准射程内最稳定；远距命中非要害也可产生迟滞 | | 可靠性 | 对有神经/肌肉反应的目标可靠；对史莱姆、植物、无机物不确定 | ### 限制 - 不是立即停止一切动作，通常需要数息生效。 - 大型或高抗性目标可能只减速不倒地。 ### 风险 - 活捉目标仍需

### ISSUE · query output · all arrows count

- Text: `所有箭矢数量`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=False
- query_kind=entity
- query_excerpt=未找到实体：`所有箭矢数量` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- query returned 未找到实体
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### ISSUE · query output · water spinach count

- Text: `空心菜还有多少株`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`空心菜还有多少株` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['13株']; query returned 未找到实体

### PASS · query output · water spinach direct

- Text: `空心菜`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：空心菜 | 字段 | 值 | |------|----| | ID | `item:v1-3a6b64e5c1` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 13株 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 蔬菜 ### 备注 - location_adjudication: applied_at：2026-06-30T16:39:29.958801+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 13株（鲜/8+5傍晚割） - 存储: 鲜用 - v1_location: 树屋（畦6）

### PASS · query output · pending projects

- Text: `当前有哪些待办`
- Observed: route ok; query useful
- Expected: route query:scene can_proceed=True; useful query output
- start_turn=query:scene can_proceed=True
- query_kind=scene
- query_excerpt=## 当前场景：六边形菌丝复合屋 ### 全景 领地中央的六边形菌丝复合屋，当前主居所。 ### 当前状态 | 项目 | 当前 | |------|------| | 时间 | 第28天 · 上午 | | 天气 | 晴，干旱持续（地表水全断/地下菌丝从L7泉眼抽水自给） | | 季节 | 创世历元年 / 晚春 / 春之月 3 | | 位置 | `loc:home-mycelium-house` | ### 近处对象 - `pc:shenyan` 亚（角色）：第28天清晨；轻微疲劳；金光100% - `char:pumpkin-s2` 南瓜（角色）：南瓜在六边形菌丝复合屋内，是当前最近的伴侣型活体伙伴；可进行日常沟通、状态观察和能力边界确认。 - `item:v1-1767a0dfd3` 乳白残液（矿物釉）（物品）：乳白残液（矿物釉），约40ml；矿物转化/灰白薄釉材料，存于新屋储物墙。 - `item:v1-9bb88c5944` 普通残胶（S4）（物品）：普通残胶（S4），约半竹杯；防水/透明涂层材料。 - `item:v1-b4fc16271b` 松子仁（物品）：松子仁，约一

### ISSUE · query output · urgent issues

- Text: `现在最紧急的事情是什么`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True or query:scene can_proceed=True; useful query output
- Issue: `query_route_gap`
- start_turn=query:entity can_proceed=False
- query_kind=scene
- query_excerpt=## 当前场景：六边形菌丝复合屋 ### 全景 领地中央的六边形菌丝复合屋，当前主居所。 ### 当前状态 | 项目 | 当前 | |------|------| | 时间 | 第28天 · 上午 | | 天气 | 晴，干旱持续（地表水全断/地下菌丝从L7泉眼抽水自给） | | 季节 | 创世历元年 / 晚春 / 春之月 3 | | 位置 | `loc:home-mycelium-house` | ### 近处对象 - `pc:shenyan` 亚（角色）：第28天清晨；轻微疲劳；金光100% - `char:pumpkin-s2` 南瓜（角色）：南瓜在六边形菌丝复合屋内，是当前最近的伴侣型活体伙伴；可进行日常沟通、状态观察和能力边界确认。 - `item:v1-1767a0dfd3` 乳白残液（矿物釉）（物品）：乳白残液（矿物釉），约40ml；矿物转化/灰白薄釉材料，存于新屋储物墙。 - `item:v1-9bb88c5944` 普通残胶（S4）（物品）：普通残胶（S4），约半竹杯；防水/透明涂层材料。 - `item:v1-b4fc16271b` 松子仁（物品）：松子仁，约一
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · query output extended · current location scene

- Text: `看一下周围`
- Observed: route ok; query useful
- Expected: route query:scene can_proceed=True; useful query output
- start_turn=query:scene can_proceed=True
- query_kind=scene
- query_excerpt=## 当前场景：六边形菌丝复合屋 ### 全景 领地中央的六边形菌丝复合屋，当前主居所。 ### 当前状态 | 项目 | 当前 | |------|------| | 时间 | 第28天 · 上午 | | 天气 | 晴，干旱持续（地表水全断/地下菌丝从L7泉眼抽水自给） | | 季节 | 创世历元年 / 晚春 / 春之月 3 | | 位置 | `loc:home-mycelium-house` | ### 近处对象 - `pc:shenyan` 亚（角色）：第28天清晨；轻微疲劳；金光100% - `char:pumpkin-s2` 南瓜（角色）：南瓜在六边形菌丝复合屋内，是当前最近的伴侣型活体伙伴；可进行日常沟通、状态观察和能力边界确认。 - `item:v1-1767a0dfd3` 乳白残液（矿物釉）（物品）：乳白残液（矿物釉），约40ml；矿物转化/灰白薄釉材料，存于新屋储物墙。 - `item:v1-9bb88c5944` 普通残胶（S4）（物品）：普通残胶（S4），约半竹杯；防水/透明涂层材料。 - `item:v1-b4fc16271b` 松子仁（物品）：松子仁，约一

### ISSUE · query output extended · current situation scene

- Text: `现在是什么情况`
- Observed: query/route gap
- Expected: route query:scene can_proceed=True; useful query output
- Issue: `query_route_gap`
- start_turn=query:entity can_proceed=False
- query_kind=scene
- query_excerpt=## 当前场景：六边形菌丝复合屋 ### 全景 领地中央的六边形菌丝复合屋，当前主居所。 ### 当前状态 | 项目 | 当前 | |------|------| | 时间 | 第28天 · 上午 | | 天气 | 晴，干旱持续（地表水全断/地下菌丝从L7泉眼抽水自给） | | 季节 | 创世历元年 / 晚春 / 春之月 3 | | 位置 | `loc:home-mycelium-house` | ### 近处对象 - `pc:shenyan` 亚（角色）：第28天清晨；轻微疲劳；金光100% - `char:pumpkin-s2` 南瓜（角色）：南瓜在六边形菌丝复合屋内，是当前最近的伴侣型活体伙伴；可进行日常沟通、状态观察和能力边界确认。 - `item:v1-1767a0dfd3` 乳白残液（矿物釉）（物品）：乳白残液（矿物釉），约40ml；矿物转化/灰白薄釉材料，存于新屋储物墙。 - `item:v1-9bb88c5944` 普通残胶（S4）（物品）：普通残胶（S4），约半竹杯；防水/透明涂层材料。 - `item:v1-b4fc16271b` 松子仁（物品）：松子仁，约一
- explicit_start_turn=query:scene can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### ISSUE · query output extended · urgent things scene

- Text: `当前最紧急的事情`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True or query:scene can_proceed=True; useful query output
- Issue: `query_route_gap`
- start_turn=query:entity can_proceed=False
- query_kind=scene
- query_excerpt=## 当前场景：六边形菌丝复合屋 ### 全景 领地中央的六边形菌丝复合屋，当前主居所。 ### 当前状态 | 项目 | 当前 | |------|------| | 时间 | 第28天 · 上午 | | 天气 | 晴，干旱持续（地表水全断/地下菌丝从L7泉眼抽水自给） | | 季节 | 创世历元年 / 晚春 / 春之月 3 | | 位置 | `loc:home-mycelium-house` | ### 近处对象 - `pc:shenyan` 亚（角色）：第28天清晨；轻微疲劳；金光100% - `char:pumpkin-s2` 南瓜（角色）：南瓜在六边形菌丝复合屋内，是当前最近的伴侣型活体伙伴；可进行日常沟通、状态观察和能力边界确认。 - `item:v1-1767a0dfd3` 乳白残液（矿物釉）（物品）：乳白残液（矿物釉），约40ml；矿物转化/灰白薄釉材料，存于新屋储物墙。 - `item:v1-9bb88c5944` 普通残胶（S4）（物品）：普通残胶（S4），约半竹杯；防水/透明涂层材料。 - `item:v1-b4fc16271b` 松子仁（物品）：松子仁，约一
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · query output extended · water bottle direct

- Text: `竹水筒`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：竹水筒 | 字段 | 值 | |------|----| | ID | `item:v1-0b81d0d73c` | | 类型 | 物品 | | 分类 | 工具 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 4L | | 品质 | 满 | | 装备槽 | 无 | ### 摘要 约4L竹水筒；第28天上午在L1小溪装满溪水后带回六边形菌丝复合屋。 ### 属性 - capacity_liters: 4 - 内容: 溪水 - fill_state: 满 - last_filled: event_id：event:000043:001；location_id：loc:l01-creek；turn_id：turn:000043 ### 备注 - 内容: 溪水 - fill_state: 满 - last_filled_event_id: event:000043:001 - last_filled_location_id: loc:l01-creek - quantity_text: ~4L（满） - st

### PASS · query output extended · salt direct

- Text: `盐`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：盐 | 字段 | 值 | |------|----| | ID | `item:salt` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.5勺 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 盐，约半勺结构化余量；当前放在六边形菌丝复合屋厨房角，可用于调味、腌制和基础保存。 ### 备注 - author_polish: 清理旧迁移勾选符号，不改变数量。 - location_adjudication: applied_at：2026-06-30T16:39:29.958722+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 约一勺半（晚餐又用了半勺） - 存储: 六边形菌丝复合屋厨房角调料区 - v1_location:

### PASS · query output extended · red berries direct

- Text: `红浆果`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：红浆果 | 字段 | 值 | |------|----| | ID | `item:v1-8182ae0835` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.5竹杯 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 红浆果，约半竹杯；可食用或继续用于调味/发酵，存于新屋厨房角。 ### 属性 - state_standardization: 置信度：reasonable inference from old save/current cards/session snapshots；方法：current save standardization；standardized_at：2026-06-30T15:57:35.666735+00:00 ### 备注 - quantity_text: 约一竹杯半（半杯已做醋） - state_standardization: 置信度：reasonable inference from old s

### PASS · query output extended · berry vinegar direct

- Text: `浆果醋`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：浆果醋 | 字段 | 值 | |------|----| | ID | `item:berry-vinegar` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-d-warehouse | | 状态 | 活跃 | | 数量 | 1竹杯 | | 品质 | 已开封成熟 | | 装备槽 | 无 | ### 摘要 第9天启动、第23天成熟、第25天已开封验证的成熟浆果醋；暗石榴红澄清、酸度适中回甘，当前存D仓库。 ### 属性 - fermentation_state: 已开封成熟 - is_condiment: 是 - source_days: mature：23；opened：25；started：9 ### 备注 - adjudication: HC-03 同意推荐 - mature_day: 23 - merged_from: item:berry-vinegar-ferment；item:v1-7de3677e06 - opened_day: 25 - opened_result: 暗石榴红澄清/酸度适中

### PASS · query output extended · pine nut oil direct

- Text: `松子油`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：松子油 | 字段 | 值 | |------|----| | ID | `item:pine-nut-oil` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3竹杯 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 食用油 ### 备注 - location_adjudication: applied_at：2026-06-30T16:39:29.958700+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 约小半竹杯（①碗松仁→3勺+②碗→3勺） - 存储: ~数周 - v1_location: 树屋

### PASS · query output extended · ordinary resin direct

- Text: `普通残胶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：普通残胶（S4） | 字段 | 值 | |------|----| | ID | `item:v1-9bb88c5944` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.5竹杯 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 普通残胶（S4），约半竹杯；防水/透明涂层材料。 ### 属性 - state_standardization: 置信度：reasonable inference from old save/current cards/session snapshots；方法：current save standardization；standardized_at：2026-06-30T15:57:35.666735+00:00 ### 备注 - quantity_text: ~半竹杯 - state_standardization: 置信度：reasonable inference from old save/curren

### PASS · query output extended · hardened resin direct

- Text: `硬化残胶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：硬化残胶 | 字段 | 值 | |------|----| | ID | `item:v1-0322977645` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 80ml | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 硬化残胶，约80ml；可作为浓胶、硬化涂料或防水修补材料，存于新屋储物墙。 ### 属性 - original_migrated_unit: m - state_standardization: 置信度：reasonable inference from old save/current cards/session snapshots；方法：current save standardization；standardized_at：2026-06-30T15:57:35.666735+00:00 - unit_correction: m->ml ### 备注 - quantity_text: ~80ml - state_

### PASS · query output extended · acid resin direct

- Text: `酸残胶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：酸残胶（S1） | 字段 | 值 | |------|----| | ID | `item:v1-18a38459f1` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 30ml | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 酸残胶（S1），约30ml；已按低风险材料封入竹杯，当前存新屋储物墙，可用于防水涂层试验。 ### 属性 - original_migrated_unit: m - state_standardization: 置信度：reasonable inference from old save/current cards/session snapshots；方法：current save standardization；standardized_at：2026-06-30T15:57:35.666735+00:00 - unit_correction: m->ml ### 备注 - author_polish: 清理旧

### PASS · query output extended · niter direct

- Text: `硝石针晶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：硝石针晶 | 字段 | 值 | |------|----| | ID | `item:v1-26667819cb` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-old-hut | | 状态 | 活跃 | | 数量 | 0.5杯 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 约小半杯火药原料，大部分已碾粉；来自L12砂岩岩壳采集，当前随火药材料存旧小屋材料仓库。 ### 备注 - current_location_confidence: high_inferred - linked_entities: loc:l12-niter-crust；item:black-powder - location_adjudication: applied_at：2026-06-30T16:39:29.958772+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：旧小屋/地面材料仓库；to：loc:home-old-hut - o

### PASS · query output extended · sulfur shards direct

- Text: `硫磺碎晶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：硫磺碎晶 | 字段 | 值 | |------|----| | ID | `item:v1-4681d8edfb` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-old-hut | | 状态 | 活跃 | | 数量 | 1把 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 约一把淡鹅黄色硫磺碎晶，部分已用；来自L7溪源泉眼采集，当前随火药材料存旧小屋材料仓库。 ### 备注 - current_location_confidence: high_inferred - linked_entities: loc:l07-sulfur-spring；item:black-powder - location_adjudication: applied_at：2026-06-30T16:39:29.958816+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：旧小屋/地面材料仓库；to：loc:home-old-hut - o

### PASS · query output extended · black powder direct

- Text: `黑火药`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：黑火药（造粒） | 字段 | 值 | |------|----| | ID | `item:black-powder` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-old-hut | | 状态 | 活跃 | | 数量 | 0.5竹杯 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 约小半竹杯湿混造粒黑火药，燃速翻倍，硝石已重结晶纯化；树屋拆除后转入旧小屋危险品隔离角，远离火源。 ### 备注 - ingredients_linked: item:v1-26667819cb；item:v1-4681d8edfb - linked_entities: item:landmine-m1；item:landmine-m2；item:powder-arrows；ref:trap-and-powder-safety - location_adjudication: applied_at：2026-06-30T16:39:29.958649+00:00；from：loc:home-treehouse；reason：树屋

### ISSUE · query output extended · water spinach stock

- Text: `空心菜库存`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`空心菜库存` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['13株']; query returned 未找到实体

### PASS · query output extended · amaranth direct

- Text: `苋菜大叶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：苋菜大叶 | 字段 | 值 | |------|----| | ID | `item:v1-e267e90894` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 8片 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 蔬菜 ### 备注 - location_adjudication: applied_at：2026-06-30T16:39:29.959050+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 8片（鲜/第9天傍晚摘） - 存储: 鲜用 - v1_location: 树屋（畦3）

### PASS · query output extended · lettuce direct

- Text: `红叶生菜`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：红叶生菜 | 字段 | 值 | |------|----| | ID | `item:v1-f07d297448` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3片 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 蔬菜 ### 备注 - location_adjudication: applied_at：2026-06-30T16:39:29.959063+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 3片（鲜/傍晚掰） - 存储: 鲜用 - v1_location: 树屋（畦9）

### PASS · query output extended · wild onion direct

- Text: `野葱`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：野葱 | 字段 | 值 | |------|----| | ID | `item:v1-0629e81966` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3根 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 调料 ### 备注 - location_adjudication: applied_at：2026-06-30T16:39:29.958739+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 3根（鲜） - 存储: 鲜用 - v1_location: 树屋（调料区）

### PASS · query output extended · garlic leaf direct

- Text: `蒜叶`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：蒜叶 | 字段 | 值 | |------|----| | ID | `item:v1-8aa915dbc4` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2片 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 调料 ### 备注 - location_adjudication: applied_at：2026-06-30T16:39:29.958876+00:00；from：loc:home-treehouse；reason：树屋已拆除，库存按用途迁到新屋或旧小屋。；来源：HC-13；存储：六边形菌丝复合屋厨房角或储物墙；to：loc:home-mycelium-house - quantity_text: 2片 - 存储: 鲜用 - v1_location: 树屋（调料区）

### PASS · query output extended · ginger direct

- Text: `生姜`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：生姜 | 字段 | 值 | |------|----| | ID | `item:v1-a5ed98dd5e` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-clearing | | 状态 | 活跃 | | 数量 | 3块 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 生姜，3块老姜；当前作为调料/种植材料登记，具体取用前可通过盘点确认可食用部分。 ### 属性 - inventory_audit: unit inferred during standardization; correct later if play reveals exact amount ### 备注 - author_polish: 正文清理旧迁移口吻，推断来源保留在审计字段。 - quantity_text: 3块老姜 - state_standardization: 置信度：reasonable inferred unit; correct in play if inventory audit differs；方法：curre

### ISSUE · query output extended · stun bolts direct extra

- Text: `琥珀麻箭数量`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`琥珀麻箭数量` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['12支']; query returned 未找到实体

### ISSUE · query output extended · powder arrows direct extra

- Text: `火药箭数量`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`火药箭数量` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- missing required ['5支']; query returned 未找到实体

### PASS · query output extended · toxic bolts direct

- Text: `紫黑毒箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：紫黑毒箭 | 字段 | 值 | |------|----| | ID | `item:toxic-thorn-bolts` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | pc:shenyan | | 状态 | 活跃 | | 数量 | 20支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 神经+血液双毒箭；强于见血封喉，适合快速削弱或击杀活体。 ### 弹药档案 | 字段 | 值 | |------|----| | 兼容武器 | item:ultimate-compound-crossbow | | 效果类型 | toxin | | 主要效果 | 中毒、虚弱、神经失调或持续伤害 | | 适用场景 | 对付有血液/神经系统的危险活体 | | 射程影响 | 只要破皮入体即可发挥；远距命中浅伤时效果降低 | | 可靠性 | 对普通动物和类人生物高；对胶质、植物、无血目标需保守 | ### 限制 - 不保证瞬杀。 - 可能污染肉、皮、血液等战利品。 ### 风险 - 误伤友方或猎物污染不可逆。 - 处理尸体时需要避免接触箭头和毒

### PASS · query output extended · frost bolts direct

- Text: `霜白冻箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：霜白冻箭 | 字段 | 值 | |------|----| | ID | `item:frost-thorn-bolts` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | pc:shenyan | | 状态 | 活跃 | | 数量 | 20支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 霜寒控场箭；拳大范围冻伤，适合减速、冻结湿表面和压制冷血目标。 ### 弹药档案 | 字段 | 值 | |------|----| | 兼容武器 | item:ultimate-compound-crossbow | | 效果类型 | frost_control | | 主要效果 | 局部冻结、冻伤、减速或制造湿滑/脆化表面 | | 适用场景 | 冷血目标、胶质目标、水边战斗、控场撤退 | | 射程影响 | 命中点附近生效；远距命中仍可控场但范围不扩大 | | 可靠性 | 潮湿、水面、胶质目标上效果更明显；高热目标会削弱 | ### 限制 - 不是大范围冰墙。 - 对厚甲或高热目标更偏减速而非冻结。 ### 风险 - 可能冻裂可采集材料

### PASS · query output extended · burst bolts direct

- Text: `赤红炸箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：赤红炸箭 | 字段 | 值 | |------|----| | ID | `item:burst-thorn-bolts` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | pc:shenyan | | 状态 | 活跃 | | 数量 | 20支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 撞击爆裂箭；拳大空腔爆裂，适合冲击、破甲和驱散。 ### 弹药档案 | 字段 | 值 | |------|----| | 兼容武器 | item:ultimate-compound-crossbow | | 效果类型 | impact_burst | | 主要效果 | 撞击爆裂、冲击、破甲或撕裂表层组织 | | 适用场景 | 硬壳、甲壳、群体驱散、打断冲锋 | | 射程影响 | 中距和远距都可用；需命中实体表面触发 | | 可靠性 | 撞击触发稳定；软泥/水面/厚毛皮会削弱爆裂形态 | ### 限制 - 不是火药爆炸，范围小于火药箭。 - 可能破坏皮毛、甲壳和可采集材料。 ### 风险 - 近距可能有碎片和冲击波风险。 - 对隐蔽行动不

### PASS · query output extended · plain bolts direct

- Text: `旧普通箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：旧普通箭 | 字段 | 值 | |------|----| | ID | `item:plain-bolts` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | loc:home-clearing | | 状态 | 已退役 | | 数量 | 3支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 无 ### 备注 - material: 竹杆+铁木尖 - special: 无 - v1_location: 旧小屋

### PASS · query output extended · poison bolts direct

- Text: `旧毒弩箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：旧毒弩箭 | 字段 | 值 | |------|----| | ID | `item:poison-bolts` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | loc:home-clearing | | 状态 | 已退役 | | 数量 | 9支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 旧毒弩箭，结构化库存记录为9支；毒剂来源已确认为见血封喉树，有效期不明确，当前可用性需使用前复核。 ### 属性 - current_usability: not_reliable_combat_ammo_until_checked - inventory_reliability: retired_requires_check ### 备注 - 内容补强: 批次：0014_user_confirmed_arrow_poison_facts；置信规则：confirmed user answers override prior uncertain_questions; unanswered quantities remain unknow

### PASS · query output extended · bamboo arrows direct

- Text: `竹箭`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：竹箭（弓用） | 字段 | 值 | |------|----| | ID | `item:v1-9a74235657` | | 类型 | 物品 | | 分类 | 弹药 | | 位置 | loc:home-clearing | | 状态 | 已退役 | | 数量 | 15支 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 退役 ### 备注 - material: 全竹/三棱尖 - special: 退役 - v1_location: 树屋墙角

### PASS · query output extended · ultimate crossbow direct

- Text: `终极复合弩`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：终极复合弩 | 字段 | 值 | |------|----| | ID | `item:ultimate-compound-crossbow` | | 类型 | 装备 | | 分类 | 武器 | | 位置 | pc:shenyan | | 状态 | 活跃 | | 数量 | 1把 | | 品质 | 传奇 | | 装备槽 | 主武器 | ### 摘要 反向弩臂/复合凸轮/推箭行程~48cm/拉力峰值~140kg(泄力后~15kg)/曲柄7圈上弦/退弦释放钮 ### 战斗档案 | 字段 | 值 | |------|----| | 定位 | 远程高威力精确武器；适合先手、伏击、控场和单发高价值目标 | | 待机状态 | 默认未声明已上弦；战斗前必须确认是否已上弦/已装箭 | | 声音/暴露 | 普通弩箭弦响较低；火药箭和赤红炸箭会明显暴露位置并可能推动森林注意 | | 潮湿/雨天 | 弩本体可用；火药箭潮湿时可靠性下降，需防水封存或重新检查引信 | ### 射程分段 | 分段 | 距离 | 用法 | 风险 | |------|------|------|------|

### PASS · query output extended · backpack direct

- Text: `竹藤背包`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：竹藤背包 | 字段 | 值 | |------|----| | ID | `item:bamboo-vine-backpack` | | 类型 | 装备 | | 分类 | 容器 | | 位置 | pc:shenyan | | 状态 | 活跃 | | 数量 | 1个 | | 品质 | 未知 | | 装备槽 | 背部 | ### 摘要 外架式竹藤背包；双侧可插长物，当前作为随身携行系统。 ### 携行档案 | 字段 | 值 | |------|----| | 定位 | 随身携行、固定长物、分隔箭束和水筒 | | 容量 | 轻装适合日常巡逻；满载会明显影响奔跑、攀爬和翻滚 | | 携行状态 | 默认背在身上，除非明确放下 | | 取用速度 | 腰侧/外侧长物较快；包内小物需要停顿翻找 | | 长物固定 | 双侧可插水筒、箭束、矛或类似长物；长物过多会卡树枝 | | 机动影响 | 中等负重下可行走和慢跑；战斗翻滚、攀树、钻洞会受限 | ### 装载规则 - 行动前若涉及攀爬、潜行、冲刺、游水或贴身战斗，必须考虑是否卸包。 - 易碎、火药、毒物、食物和样本不应无说明混放

### PASS · query output extended · landmine direct

- Text: `M2地雷`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：M2 围栏竹门外地雷 | 字段 | 值 | |------|----| | ID | `item:landmine-m2` | | 类型 | 物品 | | 分类 | 陷阱 | | 位置 | loc:home-clearing | | 状态 | 活跃 | | 数量 | 1枚 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 埋在围栏竹门外侧，东西绊线，使用造粒火药和弹片，属于基地外围被动防御陷阱。 ### 属性 - warning: 出入竹门必须避开 ### 备注 - adjudication_rules: 若触发，结算爆炸、弹片、竹门/围栏损伤、声响和后续调查痕迹。；雨水、潮气或泥土可能影响火药可靠性，需要按天气/维护状态保守处理。；重新布设需要消耗时间、工具和安全距离。 - linked_entities: item:black-powder；loc:home-clearing；ref:trap-and-powder-safety；rule:player-agency - safety_protocol: 主角夜间出入竹门、搬运水桶或带NPC

### PASS · query output extended · fish trap direct

- Text: `竹编鱼笼`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：竹编鱼笼 | 字段 | 值 | |------|----| | ID | `item:fishing-trap` | | 类型 | 物品 | | 分类 | 陷阱 | | 位置 | loc:l01-creek | | 状态 | 活跃 | | 数量 | 2个 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 2个手工竹编鱼笼；T1在L1小溪，第28天上午已收并复位；T2按时间线已从早期L2挪到L13石槽深潭。 ### 属性 - count: 2 - last_harvest_event_id: event:000043:001 - last_harvest_location_id: loc:l01-creek - second_trap_status: loc:l13-stone-trough inferred from current location card; old L2 placement retained as history. ### 备注 - action_guidance: 玩家说收鱼笼时，必须先确认目标地点或逐个检查T1/T2。

### PASS · query output extended · pumpkin direct

- Text: `南瓜`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 人物/生物：南瓜 | 字段 | 值 | |------|----| | ID | `char:pumpkin-s2` | | 类型 | 角色 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 种族 | 未知 | | 角色 | companion | | 态度 | bonded | | 信任 | 85 | | 健康 | 活体稳定 | ### 摘要 南瓜在六边形菌丝复合屋内，是当前最近的伴侣型活体伙伴；可进行日常沟通、状态观察和能力边界确认。 ### 已知能力 - 双核魔力结构 - 球腔自蓄水体 - 柔肌仿生膜 - 多属性吸收记录 ### 未确认信息 - 长期进化方向 - C级后继续吸收属性的风险

### PASS · query output extended · an direct extra

- Text: `An现在在哪里`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 人物/生物：An | 字段 | 值 | |------|----| | ID | `char:an` | | 类型 | 角色 | | 位置 | loc:home-mycelium-h-room | | 状态 | 活跃 | | 种族 | species:ashmoss-folk | | 角色 | ally | | 态度 | 友好 | | 信任 | 75 | | 健康 | 未知 | ### 摘要 An住在菌丝城H室，是灰藓族互信关系核心；可围绕石板沟通、分工贸易、L9旧居和家园适应展开互动。

### PASS · query output extended · young direct

- Text: `小的`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 人物/生物：小的 | 字段 | 值 | |------|----| | ID | `char:ashmoss-young` | | 类型 | 角色 | | 位置 | loc:home-mycelium-h-room | | 状态 | 活跃 | | 种族 | species:ashmoss-folk | | 角色 | ally | | 态度 | 友好 | | 信任 | 65 | | 健康 | 未知 | ### 摘要 小的住在菌丝城H室，是灰藓族成熟个体；适合做低压社交、石板学习、生活适应和互信巩固。

### ISSUE · query output extended · eve direct extra

- Text: `夏娃现在状态`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_entity_not_found`
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=未找到实体：`夏娃现在状态` 可尝试： - 使用完整实体 ID，例如 `item:powder-arrows`。 - 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。 - 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。
- query returned 未找到实体

### PASS · query output extended · ashmoss trust direct

- Text: `灰藓族互信`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 进度钟：灰藓族互信 | 字段 | 值 | |------|----| | ID | `clock:ashmoss-trust` | | 类型 | 关系 | | 进度 | ■■■■□□ 4/6 | | 可见性 | 可见 | | 满格触发 | 灰藓族开放更深层路线、族群知识和稳定协作。 | ### 摘要 主角已与 An 和小的建立交换、命名、石板沟通和分工贸易。

### PASS · query output extended · drought clock direct

- Text: `春末干旱`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 进度钟：春末干旱 | 字段 | 值 | |------|----| | ID | `clock:drought-spring` | | 类型 | 季节 | | 进度 | ■■■■□□ 4/6 | | 可见性 | 可见 | | 满格触发 | 水源压力明显上升，作物浇水频率增加，水边生物活动改变。 | ### 摘要 水潭和瀑布水量已下降，十六畦需要持续浇水。

### ISSUE · query output extended · base upkeep direct

- Text: `基地维护压力`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_route_gap`
- start_turn=action:routine can_proceed=True
- query_kind=entity
- query_excerpt=## 进度钟：基地维护压力 | 字段 | 值 | |------|----| | ID | `clock:base-upkeep-pressure` | | 类型 | 基地 | | 进度 | ■□□□□□ 1/6 | | 可见性 | 可见 | | 满格触发 | 基地出现明确维护问题，例如仓储污染、危险品混放、灌溉瓶颈、菌丝通道效率下降或陷阱误判风险。 | ### 摘要 农田、储水、仓储、厨房、发酵、危险品、陷阱和菌丝通道需要周期性维护。
- explicit_start_turn=query:entity can_proceed=True missing=[]
- explicit_preview=query status=ready ready=False

### PASS · query output extended · forest attention direct

- Text: `森林注意`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 进度钟：森林注意 | 字段 | 值 | |------|----| | ID | `clock:forest-attention` | | 类型 | 谜团 | | 进度 | ■■■□□□□□ 3/8 | | 可见性 | 有线索 | | 满格触发 | 未知大型存在或森林机制主动接近空地。 | ### 摘要 农田、火药、魔力植物和夜间嗡鸣共同构成未知关注源。

### PASS · query output extended · civilization rumor direct

- Text: `文明传闻`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 规则：外部文明痕迹分级 | 字段 | 值 | |------|----| | ID | `rule:external-trace-classification` | | 分类 | 阵营 | | 范围 | 世界 | | 锁定 | 是 | | 来源 | system/world_rules | ### 规则文本 非灰藓族工具痕、叠石、布片、切削痕、远烟等外部文明相关信息必须按“旧痕迹、近期活动、持续观察、正式接触”分级。当前只有痕迹时，不能直接宣布外部人类势力登场、定位基地或建立外交；外部文明真正介入必须由文明传闻钟、连续线索、玩家追踪或明确事件共同支撑。 ### 例子 - L15的非灰藓族工具痕迹只能说明存在未确认制造者或旧活动，不能直接说人类侦查者已到家门口。 - 文明传闻钟未推进到阈值前，外部人类最多作为远期伏笔或不可用线索。 - 玩家连续追踪、发现新营火并确认工具来源后，才能保存为新势力/角色/路线事实。 ### 例外 - 灰藓族相关痕迹走灰藓族社交和聚落警惕规则，不自动归入外部人类文明。 - 玩家明确要求改设定或开启外部文明篇章时，可用内容 delta 或剧情事件重

### PASS · query output extended · soil depletion direct

- Text: `土壤肥力消耗`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 进度钟：土壤肥力消耗 | 字段 | 值 | |------|----| | ID | `clock:soil-depletion` | | 类型 | 生态 | | 进度 | ■□□□□□ 1/6 | | 可见性 | 可见 | | 满格触发 | 作物生长效率下降，必须堆肥、轮作或扩地。 | ### 摘要 金光催熟和十六畦密集耕作开始消耗空地肥力。

### PASS · query output extended · field six direct

- Text: `畦6 空心菜`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 畦6 空心菜 | 字段 | 值 | |------|----| | ID | `plot:field-006` | | 类型 | 农田 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 ✅ 已割多茬/断口干发新芽/未割株蹿至拇指粗/可持续割（第9+10天催熟） ### 细节 - 来源: state.md:耕地 - v1_attrs: 后续周期：每 1-2 天割一茬（留根发新芽/割后分枝更多）；当前状态：✅ 已割多茬/断口干发新芽/未割株蹿至拇指粗/可持续割（第9+10天催熟）；播种方式：金光种子直播（微洼地/排水差适合水生菜）；播种日：第 9 天傍晚；生长阶段：❷ 收割中（2/3）；阶段说明：0-出苗 → 1-抽茎 → 2-可割 → 3-留种；面积：~1.5 ㎡；预计首割：✅ 当天催熟/已割8株

### PASS · query output extended · field ten direct

- Text: `畦10 盐角草`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 畦10 盐角草 | 字段 | 值 | |------|----| | ID | `plot:field-010` | | 类型 | 农田 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 🔴 第一茬已割→烧盐完成/根系保留等再发（第10天下午） ### 细节 - 来源: state.md:耕地 - v1_attrs: 周期：每几天割一茬/烧灰→水滤→煮干→海盐；当前状态：🔴 第一茬已割→烧盐完成/根系保留等再发（第10天下午）；播种方式：金光种子直播（微洼地/挨着空心菜/排水差适合盐生植物）；播种日：第 10 天上午；生长阶段：❸ 已割等再发（3/3）；阶段说明：0-出苗 → 1-可割烧盐 → 2-再发 → 3-留种；面积：~1 ㎡；预计首割：明天（第11天）

### PASS · query output extended · field sixteen direct

- Text: `畦16 储存南瓜`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 畦16 储存南瓜 | 字段 | 值 | |------|----| | ID | `plot:field-016` | | 类型 | 农田 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 扁平白籽出土/子叶极厚顶种壳/藤蔓往围栏探 ### 细节 - 来源: state.md:耕地 - v1_attrs: 储存：南瓜皮硬/放地上存数月不坏/冬天储备；当前状态：扁平白籽出土/子叶极厚顶种壳/藤蔓往围栏探；播种方式：金光种子直播（微洼地最远/挨驱虫草围栏）；播种日：第 11 天上午；生长阶段：❶ 藤蔓出土（1/4）；阶段说明：0-出苗 → 1-爬藤 → 2-开花 → 3-坐果 → 4-老熟可存；面积：~2 ㎡；预计首收：约第 50-60 天

### ISSUE · query output extended · home house location

- Text: `六边形菌丝复合屋`
- Observed: query/route gap
- Expected: route query:entity can_proceed=True; useful query output
- Issue: `query_route_gap`
- start_turn=query:entity can_proceed=False
- query_kind=entity
- query_excerpt=## 地点：六边形菌丝复合屋 | 字段 | 值 | |------|----| | ID | `loc:home-mycelium-house` | | 状态 | 活跃 | | 生态 | 菌丝屋 | | 安全等级 | 设防 | | 距家耗时 | 0 分钟 | ### 摘要 领地中央的六边形菌丝复合屋，当前主居所。 ### 已知资源 - 菌丝床 - 厨房角 - 储物墙 - 竖井入口 - 竹水筒（满） - 小杂鱼3条 - 溪虾2只 ### 出口/路线 - 空地/家 - 地下菌丝城竖井 ### 备注 - area: 约28㎡ - author_polish: current_day_role：当前回合起点与生活中枢。；daily_flow：厨房角处理食物；储物墙取用轻量物资；竖井下到地下菌丝城；出门进入围墙领地和农田；do_not_assume：不自动推进时间；不自动处理鱼虾；不自动浇水；来源：rp/docs/isekai-farm-save-content-polish-plan.md D-02 - constructed_day: 23 - 内容补强: 批次：0013 高频内容
- explicit_start_turn=query:entity can_proceed=False missing=['未命中要查询的实体。']
- explicit_preview=query status=ready ready=False

### PASS · query output extended · old hut location

- Text: `旧小屋`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 地点：旧小屋/地面材料仓库 | 字段 | 值 | |------|----| | ID | `loc:home-old-hut` | | 状态 | 活跃 | | 生态 | 储物棚 | | 安全等级 | 有守卫 | | 距家耗时 | 0 分钟 | ### 摘要 围墙领地内的旧小屋，当前用作地面材料仓库和危险品隔离点。 ### 已知资源 - 旧装备 - 火药原料 - 工具材料 - 备用纤维 ### 出口/路线 - 围墙领地 - 六边形菌丝复合屋 - 地下菌丝城D仓库 ### 备注 - 来源: 旧state多次引用旧小屋；HC-13按用户裁决补为独立地点。 - storage_profile: fire_safety：远离火坑和厨房；处理火药前必须确认干燥、明火距离和容器封闭。；primary_uses：旧装备收纳；火药/硫磺/硝石等危险材料隔离；工具材料仓储

### PASS · query output extended · l1 creek location

- Text: `L1小溪`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 地点：小溪 | 字段 | 值 | |------|----| | ID | `loc:l01-creek` | | 状态 | 活跃 | | 生态 | 小溪 | | 安全等级 | 中等 | | 距家耗时 | 15 分钟 | ### 摘要 浅溪水源点，设有拦溪竹栅和鱼笼相关设施。 ### 已知资源 - 水 - 卵石 - 鱼笼 - 拦溪竹栅 - 湖边细纤维线索 - 新鲜偶蹄印线索 ### 出口/路线 - 回家 - 下游到 L2 水潭 - 沿溪上游到 L7 溪源泉眼 ### 备注 - action_guidance: 去小溪收鱼笼应先构建 travel/gather 上下文，包含 route:home--l01-creek、item:fishing-trap、天气、时段和水边风险。；夜间或雨后行动要描述湿石、视线、水声遮蔽和脚印痕迹，不应直接跳到收获结果。；采集新材料时优先从素材库候选生成线索，保存后再成为事实实体。 - 内容补强: 批次：0013 高频内容补强；置信规则：已确认事实保持已确认；不确定设定写入未知/待确认问题；方法：基于既有存档的合理推断 - 发现线索: 线索文

### PASS · query output extended · d warehouse location

- Text: `D仓库`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 地点：菌丝城D仓库 | 字段 | 值 | |------|----| | ID | `loc:home-mycelium-d-warehouse` | | 状态 | 活跃 | | 生态 | 菌丝仓储 | | 安全等级 | 设防 | | 距家耗时 | 0 分钟 | ### 摘要 地下菌丝城D侧室仓库，带菌丝通风架和稳定温湿环境。 ### 已知资源 - 菌丝通风架 - 调料/发酵品 - 分区仓储 ### 出口/路线 - 地下菌丝城主腔室 - 六边形菌丝复合屋竖井 ### 备注 - room_code: D - 来源: 旧state母孢子树侧室列表与浆果醋D仓库记录；HC-03/HC-13裁决落地。 - storage_profile: not_for：明火；未封存火药；强毒未标记样本；primary_uses：发酵品；调料；轻量食材；需要避光通风的存货

### PASS · query output extended · h room location

- Text: `H室`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 地点：菌丝城H室 | 字段 | 值 | |------|----| | ID | `loc:home-mycelium-h-room` | | 状态 | 活跃 | | 生态 | 地下菌丝房间 | | 安全等级 | 友好 | | 距家耗时 | 1 分钟 | ### 摘要 菌丝城内给 An 与小的居住的侧室。 ### 已知资源 - 火塘 - 草席 - 石板 - 灰藓族生活物资 ### 出口/路线 - 地下菌丝城主腔 - 西隧至L9 ### 备注 - 发现线索: 线索文本：菌丝城H室 已存在于当前存档事实库；进入或行动前应查询地点卡、路线和附近活跃风险。；置信度：存档事实；确认方式：query 地点卡；查看相邻路线；到达后观察 - 风险: 未复核前不把该地点视为完全安全；进入、采集、扎营、点火、爆破或留下明显痕迹前先通过 preview 确认风险。；地点内的资源、威胁、路线变化和可见度以当前存档与行动预览为准。 - 来源: state.md:智慧生物接触 - v1质量补强: 方法：保守结构化补强；备注：补齐 AI GM 检索所需的风险、确认方式和用途边界；不推进剧情事实。

### PASS · query output extended · i room location

- Text: `I室`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 地点：菌丝城I室 | 字段 | 值 | |------|----| | ID | `loc:home-mycelium-i-room` | | 状态 | 活跃 | | 生态 | 未知 | | 安全等级 | 未知 | | 距家耗时 | 未知 分钟 | ### 摘要 地下菌丝城第9号侧室，用作隔离/关押室，当前关押T2母猫+2幼崽 ### 已知资源 - 无 ### 出口/路线 - 无

### PASS · query output extended · root mycelium direct

- Text: `根源菌丝`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：根源菌丝 | 字段 | 值 | |------|----| | ID | `item:v1-22e37e913c` | | 类型 | 物品 | | 分类 | 活体材料 | | 位置 | loc:home-mycelium-city | | 状态 | 活跃 | | 数量 | 1面 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 根源菌丝，触觉感知网络的一面结构；归入菌丝城活体材料，不按食物处理。 ### 属性 - original_migrated_category: 食物 - state_standardization: 置信度：reasonable inference from old save/current cards/session snapshots；方法：current save standardization；standardized_at：2026-06-30T15:57:35.666735+00:00 ### 备注 - quantity_text: 1撮（S2表面） - state_standardization: 置信度：

### PASS · query output extended · mother spore tree direct

- Text: `母孢子树`
- Observed: route ok; query useful
- Expected: route query:entity can_proceed=True; useful query output
- start_turn=query:entity can_proceed=True
- query_kind=entity
- query_excerpt=## 装备/物品：母孢子树（夏娃菌核） | 字段 | 值 | |------|----| | ID | `item:v1-d9e3f1ce7b` | | 类型 | 物品 | | 分类 | 活体文明核心 | | 位置 | loc:home-mycelium-city | | 状态 | 活跃 | | 数量 | 1株 | | 品质 | 唯一 | | 装备槽 | 无 | ### 摘要 夏娃的实体菌核/母孢子树，累计金光1186%，是地下菌丝城和幽壤菌裔单位的物理中枢。 ### 属性 - character_entity_id: char:eve-mycelium-core - controls_location_id: loc:home-mycelium-city - living: 是 - unique: 是 ### 备注 - current_state: 菌核裂变至24层沟回，律动约16次/分；共生共享感知已建立。 - golden_light_total_percent: 1186 - linked_character_id: char:eve-mycelium-core - q
