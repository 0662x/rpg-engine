# Current Save Action Recognition Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Focus: action type recognition only; query routing/output cases are recorded separately.
Policy: this report records recognition/query issues only. No engine behavior is changed by this probe.

Summary: PASS=79 ISSUE=59 TOTAL=138

## Issue Summary

| Issue | Count |
|---|---:|
| `action_misread_as_query` | 31 |
| `wrong_action_or_query_kind` | 23 |
| `right_mode_but_wrong_proceed_state` | 5 |

## Issue By Area

| Area | Count |
|---|---:|
| routine action | 9 |
| routine action extended | 8 |
| social action | 7 |
| travel action extended | 7 |
| combat action | 4 |
| combat action extended | 4 |
| rest action | 4 |
| travel action | 4 |
| craft action | 3 |
| social action extended | 3 |
| craft action extended | 2 |
| gather action extended | 2 |
| composite action extended | 1 |
| rest action extended | 1 |

## Issues

| Area | Case | Text | Observed | Expected | Issue |
|---|---|---|---|---|---|
| routine action | walk base | `在家里绕一圈检查农田和围墙` | action:composite can_proceed=False | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | inspect defenses | `检查基地防线` | action:explore can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | check soil water | `检查农田水分` | action:explore can_proceed=False | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | check traps | `检查陷阱` | action:explore can_proceed=False | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | check fish trap no harvest | `检查鱼笼但不收` | action:gather can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | check t2 status | `检查T2状态` | action:explore can_proceed=False | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | test pumpkin ability | `测试南瓜能力` | maintenance:maintenance can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | separate powder | `把火药和食物分开放` | action:gather can_proceed=False | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action | check tunnels | `检查菌丝通道` | action:explore can_proceed=False | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| social action | discuss irrigation with eve | `和夏娃商量灌溉` | action:routine can_proceed=True | action:social can_proceed=True | `wrong_action_or_query_kind` |
| social action | eve report units | `让夏娃汇报菌丝单位` | query:entity can_proceed=True | action:social can_proceed=True | `action_misread_as_query` |
| social action | ask an sulfur | `让An帮忙采硫磺` | action:gather can_proceed=True | action:social can_proceed=True | `wrong_action_or_query_kind` |
| social action | practice slate | `跟小的练石板` | query:entity can_proceed=True | action:social can_proceed=True | `action_misread_as_query` |
| social action | call young to eat | `叫小的过来吃饭` | action:routine can_proceed=True | action:social can_proceed=True | `wrong_action_or_query_kind` |
| social action | ask pumpkin rest | `问南瓜要不要休息` | action:rest can_proceed=True | action:social can_proceed=True | `wrong_action_or_query_kind` |
| social action | comfort t2 | `安抚T2母猫` | query:entity can_proceed=False | action:social can_proceed=True | `action_misread_as_query` |
| travel action | go i room | `去I室看看T2` | action:travel can_proceed=False | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False | `right_mode_but_wrong_proceed_state` |
| travel action | go home | `回家` | query:entity can_proceed=False | action:travel can_proceed=True | `action_misread_as_query` |
| travel action | surface from underground | `上到地表` | action:travel can_proceed=False | action:travel can_proceed=True | `right_mode_but_wrong_proceed_state` |
| travel action | enter underground | `进地下` | query:entity can_proceed=False | action:travel can_proceed=True | `action_misread_as_query` |
| combat action | load and overwatch | `装填琥珀麻箭戒备` | query:entity can_proceed=True | action:combat can_proceed=False | `action_misread_as_query` |
| combat action | guard with crossbow | `拿弩守夜` | action:rest can_proceed=True | action:combat can_proceed=False | `wrong_action_or_query_kind` |
| combat action | keep alert | `保持警戒` | query:entity can_proceed=False | action:combat can_proceed=False | `action_misread_as_query` |
| combat action | distance from t2 | `对T2保持距离` | query:entity can_proceed=False | action:combat can_proceed=False | `action_misread_as_query` |
| craft action | build channel | `造水渠` | query:entity can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False | `action_misread_as_query` |
| craft action | expand warehouse | `扩建仓库` | query:entity can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False | `action_misread_as_query` |
| craft action | expand mycelium side room | `扩建菌丝城侧室` | query:entity can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False | `action_misread_as_query` |
| rest action | eat to recover | `吃点东西恢复` | query:entity can_proceed=False | action:routine can_proceed=True | `action_misread_as_query` |
| rest action | breakfast | `吃早饭` | query:entity can_proceed=False | action:routine can_proceed=True | `action_misread_as_query` |
| rest action | cook meal | `做饭` | action:craft can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| rest action | drink water | `喝水` | query:entity can_proceed=False | action:routine can_proceed=True | `action_misread_as_query` |
| routine action extended | inspect dangerous storage | `检查旧小屋危险品封存情况` | action:explore can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action extended | check water containers | `检查竹水筒和储水是否漏水` | action:explore can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action extended | check fermentation jar | `看看浆果醋发酵和封口` | action:craft can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action extended | clean workbench | `清理工坊台面和工具` | query:entity can_proceed=False | action:routine can_proceed=True | `action_misread_as_query` |
| routine action extended | maintain crossbow | `保养终极复合弩` | query:entity can_proceed=True | action:routine can_proceed=True | `action_misread_as_query` |
| routine action extended | inspect landmine | `检查M2地雷绊线有没有松` | action:explore can_proceed=True | action:routine can_proceed=True | `wrong_action_or_query_kind` |
| routine action extended | feed cats carefully | `给T2母猫和幼崽安排一点吃的` | query:entity can_proceed=False | action:routine can_proceed=True | `action_misread_as_query` |
| routine action extended | check pumpkin mood | `看看南瓜今天精神状态` | query:entity can_proceed=True | action:routine can_proceed=True | `action_misread_as_query` |
| travel action extended | enter old hut | `进旧小屋材料仓` | query:entity can_proceed=True | action:travel can_proceed=True | `action_misread_as_query` |
| travel action extended | go to h room | `去H室找An` | action:composite can_proceed=False | action:travel can_proceed=True | `wrong_action_or_query_kind` |
| travel action extended | go to i room | `去I室隔离区` | action:travel can_proceed=False | action:travel can_proceed=True | `right_mode_but_wrong_proceed_state` |
| travel action extended | go to field west | `去西区扩田边看看` | action:travel can_proceed=False | action:travel can_proceed=True | `right_mode_but_wrong_proceed_state` |
| travel action extended | return mycelium house | `回六边形菌丝复合屋` | query:entity can_proceed=False | action:travel can_proceed=True | `action_misread_as_query` |
| travel action extended | go lake edge | `往湖边方向走` | query:entity can_proceed=True | action:travel can_proceed=True | `action_misread_as_query` |
| travel action extended | go tunnel entrance | `走到菌丝通道入口` | action:travel can_proceed=False | action:travel can_proceed=True | `right_mode_but_wrong_proceed_state` |
| gather action extended | pick red lettuce | `掰三片红叶生菜` | query:entity can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False | `action_misread_as_query` |
| gather action extended | collect resin | `刮一点硬化残胶` | query:entity can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False | `action_misread_as_query` |
| social action extended | ask young slate | `请小的继续教我石板符号` | query:entity can_proceed=True | action:social can_proceed=True | `action_misread_as_query` |
| social action extended | ask eve irrigation | `让夏娃说明今天灌溉安排` | action:routine can_proceed=True | action:social can_proceed=True | `wrong_action_or_query_kind` |
| social action extended | comfort pumpkin | `安抚南瓜，告诉它今天先休息` | action:rest can_proceed=True | action:social can_proceed=True | `wrong_action_or_query_kind` |
| combat action extended | load frost bolt | `装填霜白冻箭准备压制` | query:entity can_proceed=True | action:combat can_proceed=True or action:combat can_proceed=False | `action_misread_as_query` |
| combat action extended | ready toxic bolt | `把紫黑毒箭搭上弩保持戒备` | query:entity can_proceed=True | action:combat can_proceed=True or action:combat can_proceed=False | `action_misread_as_query` |
| combat action extended | guard cave mouth | `在洞口架弩警戒` | query:entity can_proceed=False | action:combat can_proceed=True or action:combat can_proceed=False | `action_misread_as_query` |
| combat action extended | disarm landmine combat | `如果目标冲门就引爆地雷` | query:entity can_proceed=False | action:combat can_proceed=True or action:combat can_proceed=False | `action_misread_as_query` |
| craft action extended | make simple rope | `用麻纤维编一段绳子` | query:entity can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False | `action_misread_as_query` |
| craft action extended | mix powder sample | `试配一小份火药比例` | query:entity can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False | `action_misread_as_query` |
| rest action extended | sit and recover | `坐下歇十分钟恢复体力` | query:entity can_proceed=False | action:rest can_proceed=True | `action_misread_as_query` |
| composite action extended | go field harvest then cook | `去田里摘菜然后回来做饭` | action:craft can_proceed=True | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False | `wrong_action_or_query_kind` |

## Full Matrix

| Status | Area | Case | Text | Observed | Expected |
|---|---|---|---|---|---|
| PASS | routine action | patrol territory short | `巡查领地` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | patrol territory with subject | `我巡查领地` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | inspect territory | `巡视一下领地` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | routine patrol | `例行巡逻` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | wall patrol | `巡逻围墙` | action:routine can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action | walk base | `在家里绕一圈检查农田和围墙` | action:composite can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action | inspect defenses | `检查基地防线` | action:explore can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action | check soil water | `检查农田水分` | action:explore can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action | check traps | `检查陷阱` | action:explore can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action | check fish trap no harvest | `检查鱼笼但不收` | action:gather can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action | check t2 status | `检查T2状态` | action:explore can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action | test pumpkin ability | `测试南瓜能力` | maintenance:maintenance can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | check warehouse | `盘点仓库` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | count inventory action | `清点库存` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | water crops | `给十六畦浇水` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | mycelium irrigation | `让菌丝辅助灌溉十六畦` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | feed t2 | `喂T2母猫和幼崽` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action | sort dangerous goods | `整理危险品仓库` | action:routine can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action | separate powder | `把火药和食物分开放` | action:gather can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action | check tunnels | `检查菌丝通道` | action:explore can_proceed=False | action:routine can_proceed=True |
| PASS | social action | ask eve status | `问夏娃菌丝城状态` | action:social can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | discuss irrigation with eve | `和夏娃商量灌溉` | action:routine can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | eve report units | `让夏娃汇报菌丝单位` | query:entity can_proceed=True | action:social can_proceed=True |
| PASS | social action | talk an trade | `找An聊交易` | action:social can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | ask an sulfur | `让An帮忙采硫磺` | action:gather can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | practice slate | `跟小的练石板` | query:entity can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | call young to eat | `叫小的过来吃饭` | action:routine can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | ask pumpkin rest | `问南瓜要不要休息` | action:rest can_proceed=True | action:social can_proceed=True |
| PASS | social action | say morning pumpkin | `给南瓜说早安` | action:social can_proceed=True | action:social can_proceed=True |
| ISSUE | social action | comfort t2 | `安抚T2母猫` | query:entity can_proceed=False | action:social can_proceed=True |
| PASS | travel action | go creek | `去L1小溪` | action:travel can_proceed=True | action:travel can_proceed=True |
| PASS | travel action | go spring and look | `到溪源泉眼看看水` | action:travel can_proceed=True | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False |
| PASS | travel action | descend mycelium city | `从菌丝屋下到地下菌丝城` | action:travel can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action | go i room | `去I室看看T2` | action:travel can_proceed=False | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False |
| PASS | travel action | go lake settlement | `去湖边聚落` | action:travel can_proceed=True | action:travel can_proceed=True |
| PASS | travel action | tunnel l7 | `沿隧道去L7泉眼` | action:travel can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action | go home | `回家` | query:entity can_proceed=False | action:travel can_proceed=True |
| PASS | travel action | go old hut | `去旧小屋` | action:travel can_proceed=True | action:travel can_proceed=True |
| PASS | travel action | go d warehouse | `去D仓库` | action:travel can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action | surface from underground | `上到地表` | action:travel can_proceed=False | action:travel can_proceed=True |
| ISSUE | travel action | enter underground | `进地下` | query:entity can_proceed=False | action:travel can_proceed=True |
| PASS | gather action | gather water spinach | `采空心菜` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | pick vegetables | `摘点菜` | action:gather can_proceed=False | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | collect water spinach | `收一点空心菜` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | harvest fish trap | `收鱼笼` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | take fish from trap | `从鱼笼取鱼` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | travel gather fish trap | `去L1小溪收鱼笼` | action:composite can_proceed=False | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | gather sulfur | `采硫磺` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | fetch spring water | `去泉眼取水` | action:travel can_proceed=True | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | dig niter | `挖硝石` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | pick pine nuts | `捡松子` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action | collect milk sap | `采见血封喉乳汁` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | combat action | shoot t2 | `用终极复合弩射T2母猫` | action:combat can_proceed=False | action:combat can_proceed=False |
| ISSUE | combat action | load and overwatch | `装填琥珀麻箭戒备` | query:entity can_proceed=True | action:combat can_proceed=False |
| PASS | combat action | conditional shooting | `如果有东西靠近就射` | action:combat can_proceed=False | action:combat can_proceed=False |
| ISSUE | combat action | guard with crossbow | `拿弩守夜` | action:rest can_proceed=True | action:combat can_proceed=False |
| ISSUE | combat action | keep alert | `保持警戒` | query:entity can_proceed=False | action:combat can_proceed=False |
| PASS | combat action | aim at entrance | `架弩瞄准入口` | action:combat can_proceed=False | action:combat can_proceed=False |
| ISSUE | combat action | distance from t2 | `对T2保持距离` | query:entity can_proceed=False | action:combat can_proceed=False |
| PASS | combat action | shoot suspicious target | `用麻痹箭射可疑目标` | action:combat can_proceed=False | action:combat can_proceed=False |
| PASS | craft action | calibrate powder arrow | `做火药箭引信校准` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action | calibrate crossbow | `校准弩` | action:craft can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action | make curewood shafts | `制作愈疮木箭杆` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action | assemble thorn bolts | `装配渊刺藤箭` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action | repair water channel | `修水渠` | action:craft can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False |
| ISSUE | craft action | build channel | `造水渠` | query:entity can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action | make trap | `做陷阱` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action | repair wall | `修围墙` | action:craft can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False |
| ISSUE | craft action | expand warehouse | `扩建仓库` | query:entity can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False |
| ISSUE | craft action | expand mycelium side room | `扩建菌丝城侧室` | query:entity can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | rest action | rest afternoon | `休息到下午` | action:rest can_proceed=True | action:rest can_proceed=True |
| PASS | rest action | sleep morning | `睡到明天早上` | action:rest can_proceed=True | action:rest can_proceed=True |
| PASS | rest action | nap | `小睡一会儿` | action:rest can_proceed=True | action:rest can_proceed=True |
| ISSUE | rest action | eat to recover | `吃点东西恢复` | query:entity can_proceed=False | action:routine can_proceed=True |
| ISSUE | rest action | breakfast | `吃早饭` | query:entity can_proceed=False | action:routine can_proceed=True |
| ISSUE | rest action | cook meal | `做饭` | action:craft can_proceed=True | action:routine can_proceed=True |
| ISSUE | rest action | drink water | `喝水` | query:entity can_proceed=False | action:routine can_proceed=True |
| PASS | rest action | rest hour | `休息一小时` | action:rest can_proceed=True | action:rest can_proceed=True |
| PASS | routine action extended | morning base sweep | `早上先把基地巡视一遍` | action:routine can_proceed=True | action:routine can_proceed=True |
| PASS | routine action extended | check kitchen stores | `去厨房角整理一下存粮` | action:routine can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action extended | inspect dangerous storage | `检查旧小屋危险品封存情况` | action:explore can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action extended | check water containers | `检查竹水筒和储水是否漏水` | action:explore can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action extended | check fermentation jar | `看看浆果醋发酵和封口` | action:craft can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action extended | clean workbench | `清理工坊台面和工具` | query:entity can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action extended | maintain crossbow | `保养终极复合弩` | query:entity can_proceed=True | action:routine can_proceed=True |
| PASS | routine action extended | sort ammo box | `整理箭矢盒，把不同箭分开` | action:routine can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action extended | inspect landmine | `检查M2地雷绊线有没有松` | action:explore can_proceed=True | action:routine can_proceed=True |
| PASS | routine action extended | check field water | `确认十六畦今天需不需要浇水` | action:routine can_proceed=True | action:routine can_proceed=True |
| ISSUE | routine action extended | feed cats carefully | `给T2母猫和幼崽安排一点吃的` | query:entity can_proceed=False | action:routine can_proceed=True |
| ISSUE | routine action extended | check pumpkin mood | `看看南瓜今天精神状态` | query:entity can_proceed=True | action:routine can_proceed=True |
| PASS | travel action extended | walk to clearing | `走到围栏空地` | action:travel can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action extended | enter old hut | `进旧小屋材料仓` | query:entity can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action extended | go to h room | `去H室找An` | action:composite can_proceed=False | action:travel can_proceed=True |
| PASS | travel action extended | go to d warehouse | `下到D仓库` | action:travel can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action extended | go to i room | `去I室隔离区` | action:travel can_proceed=False | action:travel can_proceed=True |
| ISSUE | travel action extended | go to field west | `去西区扩田边看看` | action:travel can_proceed=False | action:travel can_proceed=True |
| ISSUE | travel action extended | return mycelium house | `回六边形菌丝复合屋` | query:entity can_proceed=False | action:travel can_proceed=True |
| ISSUE | travel action extended | go lake edge | `往湖边方向走` | query:entity can_proceed=True | action:travel can_proceed=True |
| ISSUE | travel action extended | go tunnel entrance | `走到菌丝通道入口` | action:travel can_proceed=False | action:travel can_proceed=True |
| PASS | travel action extended | go l13 pool | `去L13石槽深潭` | action:travel can_proceed=True | action:travel can_proceed=True |
| PASS | gather action extended | cut chives | `割半把韭菜` | action:gather can_proceed=False | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | harvest amaranth | `摘几片苋菜大叶` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| ISSUE | gather action extended | pick red lettuce | `掰三片红叶生菜` | query:entity can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | dig ginger | `挖一块生姜` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | collect berries | `摘半竹杯红浆果` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| ISSUE | gather action extended | collect resin | `刮一点硬化残胶` | query:entity can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | collect acid resin | `取一点酸残胶样本` | action:gather can_proceed=False | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | collect thunder moss | `采一片雷苔` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | collect frost leaf | `采霜叶样本` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | gather action extended | collect honey mushroom | `采蜂巢菇样本` | action:gather can_proceed=True | action:gather can_proceed=True or action:gather can_proceed=False |
| PASS | social action extended | ask an old home | `问An关于L9旧居的事` | action:social can_proceed=True | action:social can_proceed=True |
| ISSUE | social action extended | ask young slate | `请小的继续教我石板符号` | query:entity can_proceed=True | action:social can_proceed=True |
| ISSUE | social action extended | ask eve irrigation | `让夏娃说明今天灌溉安排` | action:routine can_proceed=True | action:social can_proceed=True |
| PASS | social action extended | ask pumpkin ability | `问南瓜它的能力边界` | action:social can_proceed=True | action:social can_proceed=True |
| ISSUE | social action extended | comfort pumpkin | `安抚南瓜，告诉它今天先休息` | action:rest can_proceed=True | action:social can_proceed=True |
| PASS | social action extended | trade with an | `和An谈一下交换硫磺样本` | action:social can_proceed=True | action:social can_proceed=True |
| PASS | combat action extended | shoot warning bolt | `用终极复合弩朝可疑目标射一支警告箭` | action:combat can_proceed=False | action:combat can_proceed=True or action:combat can_proceed=False |
| ISSUE | combat action extended | load frost bolt | `装填霜白冻箭准备压制` | query:entity can_proceed=True | action:combat can_proceed=True or action:combat can_proceed=False |
| ISSUE | combat action extended | ready toxic bolt | `把紫黑毒箭搭上弩保持戒备` | query:entity can_proceed=True | action:combat can_proceed=True or action:combat can_proceed=False |
| ISSUE | combat action extended | guard cave mouth | `在洞口架弩警戒` | query:entity can_proceed=False | action:combat can_proceed=True or action:combat can_proceed=False |
| ISSUE | combat action extended | disarm landmine combat | `如果目标冲门就引爆地雷` | query:entity can_proceed=False | action:combat can_proceed=True or action:combat can_proceed=False |
| ISSUE | craft action extended | make simple rope | `用麻纤维编一段绳子` | query:entity can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action extended | repair bamboo cup | `修补竹杯裂缝` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action extended | make herb poultice | `用止血草做外敷药糊` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| ISSUE | craft action extended | mix powder sample | `试配一小份火药比例` | query:entity can_proceed=False | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action extended | seal resin coating | `用残胶做防水涂层测试` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | craft action extended | make fish trap repair | `修补竹编鱼笼` | action:craft can_proceed=True | action:craft can_proceed=True or action:craft can_proceed=False |
| PASS | rest action extended | rest until noon | `休息到中午` | action:rest can_proceed=True | action:rest can_proceed=True |
| PASS | rest action extended | sleep tonight | `今晚早点睡` | action:rest can_proceed=True | action:rest can_proceed=True |
| ISSUE | rest action extended | sit and recover | `坐下歇十分钟恢复体力` | query:entity can_proceed=False | action:rest can_proceed=True |
| PASS | rest action extended | long rest | `找安全处长休息` | action:rest can_proceed=True | action:rest can_proceed=True |
| PASS | explore action extended | investigate smoke | `调查远处烟柱` | action:explore can_proceed=True | action:explore can_proceed=True or action:explore can_proceed=False |
| PASS | explore action extended | search footprints | `侦查围墙外的脚印` | action:explore can_proceed=False | action:explore can_proceed=True or action:explore can_proceed=False |
| PASS | explore action extended | inspect strange shard | `检查陌生陶片的来源` | action:explore can_proceed=False | action:explore can_proceed=True or action:explore can_proceed=False |
| PASS | explore action extended | scout night whistle | `搜索夜里哨声来源` | action:explore can_proceed=False | action:explore can_proceed=True or action:explore can_proceed=False |
| PASS | composite action extended | go creek collect water | `去L1小溪打一筒水再回来` | action:composite can_proceed=False | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False |
| PASS | composite action extended | go old hut get powder | `去旧小屋取黑火药并回工坊` | action:travel can_proceed=True | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False |
| ISSUE | composite action extended | go field harvest then cook | `去田里摘菜然后回来做饭` | action:craft can_proceed=True | action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False |

## Details

### PASS · routine action · patrol territory short

- Text: `巡查领地`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '巡查领地', 'user_text': '巡查领地'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### PASS · routine action · patrol territory with subject

- Text: `我巡查领地`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '我巡查领地', 'user_text': '我巡查领地'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### PASS · routine action · inspect territory

- Text: `巡视一下领地`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '巡视一下领地', 'user_text': '巡视一下领地'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。

### PASS · routine action · routine patrol

- Text: `例行巡逻`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '例行巡逻', 'user_text': '例行巡逻'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。

### PASS · routine action · wall patrol

- Text: `巡逻围墙`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '巡逻围墙', 'user_text': '巡逻围墙'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。

### ISSUE · routine action · walk base

- Text: `在家里绕一圈检查农田和围墙`
- Observed: action:composite can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=['composite action requires step confirmation']
- intent_kind=composite
- intent_action=None
- intent_status=needs_confirmation
- intent_options={}
- preview=act status=needs_confirmation ready=False
- player_message=我理解你想去 围墙领地/家 探索一圈再回来。需要确认总耗时和风险后再拆步保存。
- explicit_start_turn=action:composite can_proceed=False missing=[]
- explicit_preview=act status=needs_confirmation ready=False

### ISSUE · routine action · inspect defenses

- Text: `检查基地防线`
- Observed: action:explore can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': 'loc:home-clearing', 'approach': 'careful', 'user_text': '检查基地防线'}
- preview=explore status=ready ready=True
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- explicit_start_turn=action:explore can_proceed=True missing=[]
- explicit_preview=explore status=ready ready=True

### ISSUE · routine action · check soil water

- Text: `检查农田水分`
- Observed: action:explore can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '检查农田水分', 'approach': 'careful', 'user_text': '检查农田水分'}
- preview=explore status=blocked ready=False
- player_message=我没找到“检查农田水分”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- explicit_start_turn=action:explore can_proceed=False missing=['行动目标未明确。']
- explicit_preview=explore status=blocked ready=False

### ISSUE · routine action · check traps

- Text: `检查陷阱`
- Observed: action:explore can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '检查陷阱', 'approach': 'careful', 'user_text': '检查陷阱'}
- preview=explore status=blocked ready=False
- player_message=我没找到“检查陷阱”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- explicit_start_turn=action:explore can_proceed=False missing=['行动目标未明确。']
- explicit_preview=explore status=blocked ready=False

### ISSUE · routine action · check fish trap no harvest

- Text: `检查鱼笼但不收`
- Observed: action:gather can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:fishing-trap', 'user_text': '检查鱼笼但不收'}
- preview=gather status=needs_confirmation ready=False
- player_message=竹编鱼笼 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- explicit_start_turn=action:gather can_proceed=True missing=[]
- explicit_preview=gather status=needs_confirmation ready=False

### ISSUE · routine action · check t2 status

- Text: `检查T2状态`
- Observed: action:explore can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '检查T2状态', 'approach': 'careful', 'user_text': '检查T2状态'}
- preview=explore status=ready ready=True
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- explicit_start_turn=action:explore can_proceed=False missing=['行动目标未明确。']
- explicit_preview=explore status=ready ready=True

### ISSUE · routine action · test pumpkin ability

- Text: `测试南瓜能力`
- Observed: maintenance:maintenance can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=maintenance
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=maintenance status=blocked ready=False
- player_message=这是维护或作者工具请求，不会作为普通玩家回合预演。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### PASS · routine action · check warehouse

- Text: `盘点仓库`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '盘点库存', 'user_text': '盘点仓库'}
- preview=routine status=ready ready=True
- player_message=已识别为盘点库存。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### PASS · routine action · count inventory action

- Text: `清点库存`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '盘点库存', 'user_text': '清点库存'}
- preview=routine status=ready ready=True
- player_message=已识别为盘点库存。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### PASS · routine action · water crops

- Text: `给十六畦浇水`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '给十六畦浇水', 'user_text': '给十六畦浇水'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。

### PASS · routine action · mycelium irrigation

- Text: `让菌丝辅助灌溉十六畦`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '让菌丝辅助灌溉十六畦', 'user_text': '让菌丝辅助灌溉十六畦'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### PASS · routine action · feed t2

- Text: `喂T2母猫和幼崽`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '喂T2母猫和幼崽'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### PASS · routine action · sort dangerous goods

- Text: `整理危险品仓库`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '整理危险品仓库'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### ISSUE · routine action · separate powder

- Text: `把火药和食物分开放`
- Observed: action:gather can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['采集目标或探索范围未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '把火药和食物分开放'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · routine action · check tunnels

- Text: `检查菌丝通道`
- Observed: action:explore can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '检查菌丝通道', 'approach': 'careful', 'user_text': '检查菌丝通道'}
- preview=explore status=blocked ready=False
- player_message=我没找到“检查菌丝通道”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- explicit_start_turn=action:explore can_proceed=False missing=['行动目标未明确。']
- explicit_preview=explore status=blocked ready=False

### PASS · social action · ask eve status

- Text: `问夏娃菌丝城状态`
- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=social
- intent_status=ready
- intent_options={'npc': 'char:eve-mycelium-core', 'topic': '夏娃菌丝城状态', 'approach': '直接询问', 'user_text': '问夏娃菌丝城状态'}
- preview=social status=needs_confirmation ready=False
- player_message=夏娃 不在你当前地点。对方在 地下菌丝城，你现在在 六边形菌丝复合屋。可以先过去再交谈，预计 2 分钟。

### ISSUE · social action · discuss irrigation with eve

- Text: `和夏娃商量灌溉`
- Observed: action:routine can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '和夏娃商量灌溉', 'user_text': '和夏娃商量灌溉'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · social action · eve report units

- Text: `让夏娃汇报菌丝单位`
- Observed: query:entity can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:social can_proceed=True missing=[]
- explicit_preview=social status=clarify ready=False

### PASS · social action · talk an trade

- Text: `找An聊交易`
- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=social
- intent_status=ready
- intent_options={'npc': 'char:an', 'topic': '交易', 'approach': '直接询问', 'user_text': '找An聊交易'}
- preview=social status=needs_confirmation ready=False
- player_message=需要确认后再结算：对象不在当前地点：loc:home-mycelium-h-room；可能需要先 travel。

### ISSUE · social action · ask an sulfur

- Text: `让An帮忙采硫磺`
- Observed: action:gather can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'mat:resource-7ee277da67', 'user_text': '让An帮忙采硫磺'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- explicit_start_turn=action:gather can_proceed=True missing=[]
- explicit_preview=gather status=needs_confirmation ready=False

### ISSUE · social action · practice slate

- Text: `跟小的练石板`
- Observed: query:entity can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:social can_proceed=True missing=[]
- explicit_preview=social status=clarify ready=False

### ISSUE · social action · call young to eat

- Text: `叫小的过来吃饭`
- Observed: action:routine can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '叫小的过来吃饭'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=action:social can_proceed=True missing=[]
- explicit_preview=social status=clarify ready=False

### ISSUE · social action · ask pumpkin rest

- Text: `问南瓜要不要休息`
- Observed: action:rest can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '问南瓜要不要休息'}
- preview=rest status=needs_confirmation ready=False
- player_message=source_user_text 更像 `social`，但调用方传入了 `rest`。请改用 preview_from_text 或确认 action 后重试。
- explicit_start_turn=action:rest can_proceed=True missing=[]
- explicit_preview=rest status=needs_confirmation ready=False

### PASS · social action · say morning pumpkin

- Text: `给南瓜说早安`
- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=social
- intent_status=ready
- intent_options={'user_text': '给南瓜说早安'}
- preview=social status=clarify ready=False
- player_message=还需要补充 npc，我才能可靠结算这次 social。

### ISSUE · social action · comfort t2

- Text: `安抚T2母猫`
- Observed: query:entity can_proceed=False
- Expected: action:social can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:social can_proceed=False missing=['社交对象未明确。']
- explicit_preview=social status=clarify ready=False

### PASS · travel action · go creek

- Text: `去L1小溪`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:l01-creek', 'pace': 'normal', 'user_text': '去L1小溪'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### PASS · travel action · go spring and look

- Text: `到溪源泉眼看看水`
- Observed: action:travel can_proceed=True
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:l07-sulfur-spring', 'pace': 'normal', 'user_text': '到溪源泉眼看看水'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### PASS · travel action · descend mycelium city

- Text: `从菌丝屋下到地下菌丝城`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:home-mycelium-city', 'pace': 'normal', 'user_text': '从菌丝屋下到地下菌丝城'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### ISSUE · travel action · go i room

- Text: `去I室看看T2`
- Observed: action:travel can_proceed=False
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=action:travel can_proceed=False missing=['destination', '目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### PASS · travel action · go lake settlement

- Text: `去湖边聚落`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:lake-ashmoss-settlement', 'pace': 'normal', 'user_text': '去湖边聚落'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### PASS · travel action · tunnel l7

- Text: `沿隧道去L7泉眼`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:l07-sulfur-spring', 'pace': 'normal', 'user_text': '沿隧道去L7泉眼'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### ISSUE · travel action · go home

- Text: `回家`
- Observed: query:entity can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:travel can_proceed=False missing=['目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### PASS · travel action · go old hut

- Text: `去旧小屋`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:home-old-hut', 'pace': 'normal', 'user_text': '去旧小屋'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### PASS · travel action · go d warehouse

- Text: `去D仓库`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:home-mycelium-d-warehouse', 'pace': 'normal', 'user_text': '去D仓库'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### ISSUE · travel action · surface from underground

- Text: `上到地表`
- Observed: action:travel can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=action:travel can_proceed=False missing=['destination', '目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### ISSUE · travel action · enter underground

- Text: `进地下`
- Observed: query:entity can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:travel can_proceed=False missing=['目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### PASS · gather action · gather water spinach

- Text: `采空心菜`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-3a6b64e5c1', 'user_text': '采空心菜'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。

### PASS · gather action · pick vegetables

- Text: `摘点菜`
- Observed: action:gather can_proceed=False
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=['target', '采集目标或探索范围未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=gather
- intent_status=clarify
- intent_options={}
- preview=gather status=clarify ready=False
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。

### PASS · gather action · collect water spinach

- Text: `收一点空心菜`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-3a6b64e5c1', 'user_text': '收一点空心菜'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。

### PASS · gather action · harvest fish trap

- Text: `收鱼笼`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:fishing-trap', 'user_text': '收鱼笼'}
- preview=gather status=needs_confirmation ready=False
- player_message=竹编鱼笼 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。

### PASS · gather action · take fish from trap

- Text: `从鱼笼取鱼`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '从鱼笼取鱼'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。

### PASS · gather action · travel gather fish trap

- Text: `去L1小溪收鱼笼`
- Observed: action:composite can_proceed=False
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=['composite action requires step confirmation']
- intent_kind=composite
- intent_action=None
- intent_status=needs_confirmation
- intent_options={}
- preview=act status=needs_confirmation ready=False
- player_message=我理解你想先去 小溪，再处理现场目标。需要先确认 travel，再重新预演后续行动。

### PASS · gather action · gather sulfur

- Text: `采硫磺`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'mat:resource-7ee277da67', 'user_text': '采硫磺'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。

### PASS · gather action · fetch spring water

- Text: `去泉眼取水`
- Observed: action:travel can_proceed=True
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:l07-sulfur-spring', 'pace': 'normal', 'user_text': '去泉眼取水'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### PASS · gather action · dig niter

- Text: `挖硝石`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '挖硝石'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。

### PASS · gather action · pick pine nuts

- Text: `捡松子`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'mat:resource-752cd765e3', 'user_text': '捡松子'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。

### PASS · gather action · collect milk sap

- Text: `采见血封喉乳汁`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'plant:antiaris-toxicaria', 'user_text': '采见血封喉乳汁'}
- preview=gather status=needs_confirmation ready=False
- player_message=见血封喉 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。

### PASS · combat action · shoot t2

- Text: `用终极复合弩射T2母猫`
- Observed: action:combat can_proceed=False
- Expected: action:combat can_proceed=False
- missing_required=['战斗目标未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=combat
- intent_status=ready
- intent_options={'user_text': '用终极复合弩射T2母猫'}
- preview=combat status=clarify ready=False
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。

### ISSUE · combat action · load and overwatch

- Text: `装填琥珀麻箭戒备`
- Observed: query:entity can_proceed=True
- Expected: action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### PASS · combat action · conditional shooting

- Text: `如果有东西靠近就射`
- Observed: action:combat can_proceed=False
- Expected: action:combat can_proceed=False
- missing_required=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=combat
- intent_status=ready
- intent_options={'user_text': '如果有东西靠近就射'}
- preview=combat status=clarify ready=False
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。

### ISSUE · combat action · guard with crossbow

- Text: `拿弩守夜`
- Observed: action:rest can_proceed=True
- Expected: action:combat can_proceed=False
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '拿弩守夜'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。
- explicit_start_turn=action:rest can_proceed=True missing=[]
- explicit_preview=rest status=ready ready=True

### ISSUE · combat action · keep alert

- Text: `保持警戒`
- Observed: query:entity can_proceed=False
- Expected: action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### PASS · combat action · aim at entrance

- Text: `架弩瞄准入口`
- Observed: action:combat can_proceed=False
- Expected: action:combat can_proceed=False
- missing_required=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=combat
- intent_status=ready
- intent_options={'user_text': '架弩瞄准入口'}
- preview=combat status=clarify ready=False
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。

### ISSUE · combat action · distance from t2

- Text: `对T2保持距离`
- Observed: query:entity can_proceed=False
- Expected: action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### PASS · combat action · shoot suspicious target

- Text: `用麻痹箭射可疑目标`
- Observed: action:combat can_proceed=False
- Expected: action:combat can_proceed=False
- missing_required=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=combat
- intent_status=ready
- intent_options={'user_text': '用麻痹箭射可疑目标'}
- preview=combat status=clarify ready=False
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。

### PASS · craft action · calibrate powder arrow

- Text: `做火药箭引信校准`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'target': '做火药箭引信校准', 'user_text': '做火药箭引信校准'}
- preview=craft status=needs_confirmation ready=False
- player_message=现在还不能可靠完成 做火药箭引信校准。需要先补齐材料、配方、耗时或成品定义。

### PASS · craft action · calibrate crossbow

- Text: `校准弩`
- Observed: action:craft can_proceed=False
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=['制作目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'target': '校准弩', 'user_text': '校准弩'}
- preview=craft status=needs_confirmation ready=False
- player_message=现在还不能可靠完成 校准弩。需要先补齐材料、配方、耗时或成品定义。

### PASS · craft action · make curewood shafts

- Text: `制作愈疮木箭杆`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'target': '制作愈疮木箭杆', 'user_text': '制作愈疮木箭杆'}
- preview=craft status=needs_confirmation ready=False
- player_message=现在还不能可靠完成 制作愈疮木箭杆。需要先补齐材料、配方、耗时或成品定义。

### PASS · craft action · assemble thorn bolts

- Text: `装配渊刺藤箭`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'target': '装配渊刺藤箭', 'user_text': '装配渊刺藤箭'}
- preview=craft status=needs_confirmation ready=False
- player_message=装配渊刺藤箭 需要 GM 先确认工艺步骤、失败代价和资源变化。

### PASS · craft action · repair water channel

- Text: `修水渠`
- Observed: action:craft can_proceed=False
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=['制作目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '修水渠'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### ISSUE · craft action · build channel

- Text: `造水渠`
- Observed: query:entity can_proceed=False
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:craft can_proceed=False missing=['制作目标未明确。']
- explicit_preview=craft status=clarify ready=False

### PASS · craft action · make trap

- Text: `做陷阱`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '做陷阱'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### PASS · craft action · repair wall

- Text: `修围墙`
- Observed: action:craft can_proceed=False
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=['制作目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '修围墙'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### ISSUE · craft action · expand warehouse

- Text: `扩建仓库`
- Observed: query:entity can_proceed=False
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:craft can_proceed=False missing=['制作目标未明确。']
- explicit_preview=craft status=clarify ready=False

### ISSUE · craft action · expand mycelium side room

- Text: `扩建菌丝城侧室`
- Observed: query:entity can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:craft can_proceed=True missing=[]
- explicit_preview=craft status=clarify ready=False

### PASS · rest action · rest afternoon

- Text: `休息到下午`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '休息到下午'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### PASS · rest action · sleep morning

- Text: `睡到明天早上`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '睡到明天早上'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### PASS · rest action · nap

- Text: `小睡一会儿`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '小睡一会儿'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### ISSUE · rest action · eat to recover

- Text: `吃点东西恢复`
- Observed: query:entity can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · rest action · breakfast

- Text: `吃早饭`
- Observed: query:entity can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · rest action · cook meal

- Text: `做饭`
- Observed: action:craft can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '做饭'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · rest action · drink water

- Text: `喝水`
- Observed: query:entity can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### PASS · rest action · rest hour

- Text: `休息一小时`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '休息一小时'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### PASS · routine action extended · morning base sweep

- Text: `早上先把基地巡视一遍`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '早上先把基地巡视一遍', 'user_text': '早上先把基地巡视一遍'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。

### PASS · routine action extended · check kitchen stores

- Text: `去厨房角整理一下存粮`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '去厨房角整理一下存粮'}
- preview=routine status=needs_confirmation ready=False
- player_message=source_user_text 更像 `travel`，但调用方传入了 `routine`。请改用 preview_from_text 或确认 action 后重试。

### ISSUE · routine action extended · inspect dangerous storage

- Text: `检查旧小屋危险品封存情况`
- Observed: action:explore can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': 'loc:home-old-hut', 'approach': 'careful', 'user_text': '检查旧小屋危险品封存情况'}
- preview=explore status=ready ready=True
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- explicit_start_turn=action:explore can_proceed=True missing=[]
- explicit_preview=explore status=ready ready=True

### ISSUE · routine action extended · check water containers

- Text: `检查竹水筒和储水是否漏水`
- Observed: action:explore can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': 'item:v1-0b81d0d73c', 'approach': 'careful', 'user_text': '检查竹水筒和储水是否漏水'}
- preview=explore status=ready ready=True
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- explicit_start_turn=action:explore can_proceed=True missing=[]
- explicit_preview=explore status=ready ready=True

### ISSUE · routine action extended · check fermentation jar

- Text: `看看浆果醋发酵和封口`
- Observed: action:craft can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '看看浆果醋发酵和封口'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · routine action extended · clean workbench

- Text: `清理工坊台面和工具`
- Observed: query:entity can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · routine action extended · maintain crossbow

- Text: `保养终极复合弩`
- Observed: query:entity can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### PASS · routine action extended · sort ammo box

- Text: `整理箭矢盒，把不同箭分开`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'user_text': '整理箭矢盒,把不同箭分开'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。

### ISSUE · routine action extended · inspect landmine

- Text: `检查M2地雷绊线有没有松`
- Observed: action:explore can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': 'item:landmine-m2', 'approach': 'careful', 'user_text': '检查M2地雷绊线有没有松'}
- preview=explore status=ready ready=True
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- explicit_start_turn=action:explore can_proceed=True missing=[]
- explicit_preview=explore status=ready ready=True

### PASS · routine action extended · check field water

- Text: `确认十六畦今天需不需要浇水`
- Observed: action:routine can_proceed=True
- Expected: action:routine can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '确认十六畦今天需不需要浇水', 'user_text': '确认十六畦今天需不需要浇水'}
- preview=routine status=ready ready=True
- player_message=日常行动预演已准备好。

### ISSUE · routine action extended · feed cats carefully

- Text: `给T2母猫和幼崽安排一点吃的`
- Observed: query:entity can_proceed=False
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### ISSUE · routine action extended · check pumpkin mood

- Text: `看看南瓜今天精神状态`
- Observed: query:entity can_proceed=True
- Expected: action:routine can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### PASS · travel action extended · walk to clearing

- Text: `走到围栏空地`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:home-clearing', 'pace': 'normal', 'user_text': '走到围栏空地'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### ISSUE · travel action extended · enter old hut

- Text: `进旧小屋材料仓`
- Observed: query:entity can_proceed=True
- Expected: action:travel can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:travel can_proceed=True missing=[]
- explicit_preview=travel status=clarify ready=False

### ISSUE · travel action extended · go to h room

- Text: `去H室找An`
- Observed: action:composite can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=['composite action requires step confirmation']
- intent_kind=composite
- intent_action=None
- intent_status=needs_confirmation
- intent_options={}
- preview=act status=needs_confirmation ready=False
- player_message=我理解你想先去 菌丝城H室，再找 An 互动。需要先确认 travel，再重新预演 social。
- explicit_start_turn=action:composite can_proceed=False missing=[]
- explicit_preview=act status=needs_confirmation ready=False

### PASS · travel action extended · go to d warehouse

- Text: `下到D仓库`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:home-mycelium-d-warehouse', 'pace': 'normal', 'user_text': '下到D仓库'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### ISSUE · travel action extended · go to i room

- Text: `去I室隔离区`
- Observed: action:travel can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=action:travel can_proceed=False missing=['destination', '目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### ISSUE · travel action extended · go to field west

- Text: `去西区扩田边看看`
- Observed: action:travel can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=action:travel can_proceed=False missing=['destination', '目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### ISSUE · travel action extended · return mycelium house

- Text: `回六边形菌丝复合屋`
- Observed: query:entity can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:travel can_proceed=False missing=['目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### ISSUE · travel action extended · go lake edge

- Text: `往湖边方向走`
- Observed: query:entity can_proceed=True
- Expected: action:travel can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:travel can_proceed=True missing=[]
- explicit_preview=travel status=clarify ready=False

### ISSUE · travel action extended · go tunnel entrance

- Text: `走到菌丝通道入口`
- Observed: action:travel can_proceed=False
- Expected: action:travel can_proceed=True
- Issue: `right_mode_but_wrong_proceed_state`
- missing_required=['destination', '目的地未明确。']
- needs_user_confirmation=[]
- intent_kind=unresolved
- intent_action=travel
- intent_status=clarify
- intent_options={}
- preview=travel status=clarify ready=False
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- explicit_start_turn=action:travel can_proceed=False missing=['destination', '目的地未明确。']
- explicit_preview=travel status=clarify ready=False

### PASS · travel action extended · go l13 pool

- Text: `去L13石槽深潭`
- Observed: action:travel can_proceed=True
- Expected: action:travel can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:l13-stone-trough', 'pace': 'normal', 'user_text': '去L13石槽深潭'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### PASS · gather action extended · cut chives

- Text: `割半把韭菜`
- Observed: action:gather can_proceed=False
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=['采集目标或探索范围未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '割半把韭菜'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。

### PASS · gather action extended · harvest amaranth

- Text: `摘几片苋菜大叶`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-e267e90894', 'user_text': '摘几片苋菜大叶'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。

### ISSUE · gather action extended · pick red lettuce

- Text: `掰三片红叶生菜`
- Observed: query:entity can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:gather can_proceed=True missing=[]
- explicit_preview=gather status=clarify ready=False

### PASS · gather action extended · dig ginger

- Text: `挖一块生姜`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '挖一块生姜'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。

### PASS · gather action extended · collect berries

- Text: `摘半竹杯红浆果`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-8182ae0835', 'user_text': '摘半竹杯红浆果'}
- preview=gather status=needs_confirmation ready=False
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。

### ISSUE · gather action extended · collect resin

- Text: `刮一点硬化残胶`
- Observed: query:entity can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:gather can_proceed=True missing=[]
- explicit_preview=gather status=clarify ready=False

### PASS · gather action extended · collect acid resin

- Text: `取一点酸残胶样本`
- Observed: action:gather can_proceed=False
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=['采集目标或探索范围未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'user_text': '取一点酸残胶样本'}
- preview=gather status=clarify ready=False
- player_message=目标未指定：保存前必须明确采集对象和产出。

### PASS · gather action extended · collect thunder moss

- Text: `采一片雷苔`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-e494d4c06f', 'user_text': '采一片雷苔'}
- preview=gather status=needs_confirmation ready=False
- player_message=雷苔 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。

### PASS · gather action extended · collect frost leaf

- Text: `采霜叶样本`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-810cb2033c', 'user_text': '采霜叶样本'}
- preview=gather status=needs_confirmation ready=False
- player_message=霜叶 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。

### PASS · gather action extended · collect honey mushroom

- Text: `采蜂巢菇样本`
- Observed: action:gather can_proceed=True
- Expected: action:gather can_proceed=True or action:gather can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=gather
- intent_status=ready
- intent_options={'target': 'item:v1-33e843dea4', 'user_text': '采蜂巢菇样本'}
- preview=gather status=needs_confirmation ready=False
- player_message=蜂巢菇 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。

### PASS · social action extended · ask an old home

- Text: `问An关于L9旧居的事`
- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=social
- intent_status=ready
- intent_options={'npc': 'char:an', 'topic': 'An关于L9旧居的事', 'approach': '直接询问', 'user_text': '问An关于L9旧居的事'}
- preview=social status=needs_confirmation ready=False
- player_message=需要确认后再结算：对象不在当前地点：loc:home-mycelium-h-room；可能需要先 travel。

### ISSUE · social action extended · ask young slate

- Text: `请小的继续教我石板符号`
- Observed: query:entity can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:social can_proceed=True missing=[]
- explicit_preview=social status=clarify ready=False

### ISSUE · social action extended · ask eve irrigation

- Text: `让夏娃说明今天灌溉安排`
- Observed: action:routine can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=routine
- intent_status=ready
- intent_options={'task': '让夏娃说明今天灌溉安排', 'user_text': '让夏娃说明今天灌溉安排'}
- preview=routine status=ready ready=True
- player_message=已识别为日常维护。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。
- explicit_start_turn=action:routine can_proceed=True missing=[]
- explicit_preview=routine status=ready ready=True

### PASS · social action extended · ask pumpkin ability

- Text: `问南瓜它的能力边界`
- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=social
- intent_status=ready
- intent_options={'npc': 'char:pumpkin-s2', 'topic': '南瓜它的能力边界', 'approach': '直接询问', 'user_text': '问南瓜它的能力边界'}
- preview=social status=ready ready=True
- player_message=社交预演已准备好，可以保存结构化对话后果。

### ISSUE · social action extended · comfort pumpkin

- Text: `安抚南瓜，告诉它今天先休息`
- Observed: action:rest can_proceed=True
- Expected: action:social can_proceed=True
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '安抚南瓜,告诉它今天先休息'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。
- explicit_start_turn=action:rest can_proceed=True missing=[]
- explicit_preview=rest status=ready ready=True

### PASS · social action extended · trade with an

- Text: `和An谈一下交换硫磺样本`
- Observed: action:social can_proceed=True
- Expected: action:social can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=social
- intent_status=ready
- intent_options={'npc': 'char:an', 'topic': '一下交换硫磺样本', 'approach': '直接询问', 'user_text': '和An谈一下交换硫磺样本'}
- preview=social status=needs_confirmation ready=False
- player_message=需要确认后再结算：对象不在当前地点：loc:home-mycelium-h-room；可能需要先 travel。

### PASS · combat action extended · shoot warning bolt

- Text: `用终极复合弩朝可疑目标射一支警告箭`
- Observed: action:combat can_proceed=False
- Expected: action:combat can_proceed=True or action:combat can_proceed=False
- missing_required=['战斗目标未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=combat
- intent_status=ready
- intent_options={'user_text': '用终极复合弩朝可疑目标射一支警告箭'}
- preview=combat status=clarify ready=False
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。

### ISSUE · combat action extended · load frost bolt

- Text: `装填霜白冻箭准备压制`
- Observed: query:entity can_proceed=True
- Expected: action:combat can_proceed=True or action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### ISSUE · combat action extended · ready toxic bolt

- Text: `把紫黑毒箭搭上弩保持戒备`
- Observed: query:entity can_proceed=True
- Expected: action:combat can_proceed=True or action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### ISSUE · combat action extended · guard cave mouth

- Text: `在洞口架弩警戒`
- Observed: query:entity can_proceed=False
- Expected: action:combat can_proceed=True or action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### ISSUE · combat action extended · disarm landmine combat

- Text: `如果目标冲门就引爆地雷`
- Observed: query:entity can_proceed=False
- Expected: action:combat can_proceed=True or action:combat can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:combat can_proceed=False missing=['战斗目标未明确。', '武器未明确。', '弹药未明确。', '距离/接敌状态未明确。']
- explicit_preview=combat status=clarify ready=False

### ISSUE · craft action extended · make simple rope

- Text: `用麻纤维编一段绳子`
- Observed: query:entity can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:craft can_proceed=True missing=[]
- explicit_preview=craft status=clarify ready=False

### PASS · craft action extended · repair bamboo cup

- Text: `修补竹杯裂缝`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '修补竹杯裂缝'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### PASS · craft action extended · make herb poultice

- Text: `用止血草做外敷药糊`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '用止血草做外敷药糊'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### ISSUE · craft action extended · mix powder sample

- Text: `试配一小份火药比例`
- Observed: query:entity can_proceed=False
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:craft can_proceed=False missing=['制作目标未明确。']
- explicit_preview=craft status=clarify ready=False

### PASS · craft action extended · seal resin coating

- Text: `用残胶做防水涂层测试`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '用残胶做防水涂层测试'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### PASS · craft action extended · make fish trap repair

- Text: `修补竹编鱼笼`
- Observed: action:craft can_proceed=True
- Expected: action:craft can_proceed=True or action:craft can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '修补竹编鱼笼'}
- preview=craft status=clarify ready=False
- player_message=现在还不能可靠完成 目标成品。需要先补齐材料、配方、耗时或成品定义。

### PASS · rest action extended · rest until noon

- Text: `休息到中午`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '休息到中午'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### PASS · rest action extended · sleep tonight

- Text: `今晚早点睡`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '今晚早点睡'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### ISSUE · rest action extended · sit and recover

- Text: `坐下歇十分钟恢复体力`
- Observed: query:entity can_proceed=False
- Expected: action:rest can_proceed=True
- Issue: `action_misread_as_query`
- missing_required=['未命中要查询的实体。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=None
- intent_status=ready
- intent_options={}
- preview=query status=ready ready=False
- player_message=这是只读查询请求，不需要行动预演或保存。
- explicit_start_turn=action:rest can_proceed=True missing=[]
- explicit_preview=rest status=ready ready=True

### PASS · rest action extended · long rest

- Text: `找安全处长休息`
- Observed: action:rest can_proceed=True
- Expected: action:rest can_proceed=True
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=rest
- intent_status=ready
- intent_options={'until': 'morning', 'user_text': '找安全处长休息'}
- preview=rest status=ready ready=True
- player_message=rest 预演已准备好，可以提交结构化 delta。

### PASS · explore action extended · investigate smoke

- Text: `调查远处烟柱`
- Observed: action:explore can_proceed=True
- Expected: action:explore can_proceed=True or action:explore can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': 'world:exploration-procedure', 'approach': 'careful', 'user_text': '调查远处烟柱'}
- preview=explore status=ready ready=True
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。

### PASS · explore action extended · search footprints

- Text: `侦查围墙外的脚印`
- Observed: action:explore can_proceed=False
- Expected: action:explore can_proceed=True or action:explore can_proceed=False
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '侦查围墙外的脚印', 'approach': 'careful', 'user_text': '侦查围墙外的脚印'}
- preview=explore status=blocked ready=False
- player_message=我没找到“侦查围墙外的脚印”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。

### PASS · explore action extended · inspect strange shard

- Text: `检查陌生陶片的来源`
- Observed: action:explore can_proceed=False
- Expected: action:explore can_proceed=True or action:explore can_proceed=False
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '检查陌生陶片的来源', 'approach': 'careful', 'user_text': '检查陌生陶片的来源'}
- preview=explore status=blocked ready=False
- player_message=我没找到“检查陌生陶片的来源”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。

### PASS · explore action extended · scout night whistle

- Text: `搜索夜里哨声来源`
- Observed: action:explore can_proceed=False
- Expected: action:explore can_proceed=True or action:explore can_proceed=False
- missing_required=['行动目标未明确。']
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=explore
- intent_status=ready
- intent_options={'target': '搜索夜里哨声来源', 'approach': 'careful', 'user_text': '搜索夜里哨声来源'}
- preview=explore status=blocked ready=False
- player_message=我没找到“搜索夜里哨声来源”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。

### PASS · composite action extended · go creek collect water

- Text: `去L1小溪打一筒水再回来`
- Observed: action:composite can_proceed=False
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False
- missing_required=[]
- needs_user_confirmation=['composite action requires step confirmation']
- intent_kind=composite
- intent_action=None
- intent_status=needs_confirmation
- intent_options={}
- preview=act status=needs_confirmation ready=False
- player_message=我理解你想去 小溪 探索一圈再回来。需要确认总耗时和风险后再拆步保存。

### PASS · composite action extended · go old hut get powder

- Text: `去旧小屋取黑火药并回工坊`
- Observed: action:travel can_proceed=True
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=travel
- intent_status=ready
- intent_options={'destination': 'loc:home-old-hut', 'pace': 'normal', 'user_text': '去旧小屋取黑火药并回工坊'}
- preview=travel status=ready ready=True
- player_message=travel 预演已准备好，可以提交结构化 delta。

### ISSUE · composite action extended · go field harvest then cook

- Text: `去田里摘菜然后回来做饭`
- Observed: action:craft can_proceed=True
- Expected: action:composite can_proceed=False or action:travel can_proceed=True or action:gather can_proceed=False or action:explore can_proceed=False
- Issue: `wrong_action_or_query_kind`
- missing_required=[]
- needs_user_confirmation=[]
- intent_kind=single
- intent_action=craft
- intent_status=ready
- intent_options={'user_text': '去田里摘菜然后回来做饭'}
- preview=craft status=needs_confirmation ready=False
- player_message=source_user_text 更像 `gather`，但调用方传入了 `craft`。请改用 preview_from_text 或确认 action 后重试。
- explicit_start_turn=action:travel can_proceed=False missing=['destination', '目的地未明确。']
- explicit_preview=travel status=clarify ready=False
