# Current Save Intake Probe

Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.
Focus: gather/acquisition intake, newly discovered civilization/event facts, quantity correctness, and immediate queryability after commit.

Summary: PASS=121 ISSUE=21 TOTAL=142

## Key Findings

- Confirmed inventory intake: 55/55 passed; explicit `upsert_entities` stored the right item, quantity, event payload, and immediate query result.
- Confirmed world/event intake: 20/20 passed; new locations, factions, species, references, threats, relationships, and characters were immediately queryable.
- Natural player-language intake recognition: 40/54 passed; failures are mostly query/route misclassification before structured confirmation.
- Intake guardrails: 6/13 passed; several bad deltas still commit or write before post-check.

## Test Design

- Natural player inputs are routed through `start_turn` and `preview_from_text`; they must not mutate the save during preview.
- Confirmed inventory intake uses human-confirmed gather deltas with explicit `upsert_entities` and checks SQLite plus immediate `query()` results.
- Confirmed world/event intake uses human-confirmed explore deltas and checks event rows, entity rows, and immediate `query()` results.
- Guardrail cases intentionally submit bad intake deltas and expect pre-commit blocking with no persisted bad entity.

## Issue Summary

| Issue | Count |
|---|---:|
| `natural_intake_misread_as_query` | 9 |
| `intake_guardrail_missing` | 6 |
| `natural_intake_route_gap` | 5 |
| `intake_guardrail_reported_after_write` | 1 |

## Issue By Area

| Area | Count |
|---|---:|
| natural discovery recognition | 8 |
| intake guardrail | 7 |
| natural gather recognition | 6 |

## Issues

| Area | Case | Observed | Expected | Issue |
|---|---|---|---|---|
| natural gather recognition | fill water bottle | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify | recognize gather and ask for confirmed output before saving | `natural_intake_route_gap` |
| natural gather recognition | collect hemp fiber | start=query:entity can_proceed=True preview=action:query ready=False status=ready | recognize gather and ask for confirmed output before saving | `natural_intake_misread_as_query` |
| natural gather recognition | search food | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked | resource search should become gather | `natural_intake_route_gap` |
| natural gather recognition | search creek materials | start=action:explore can_proceed=False preview=action:explore ready=False status=needs_confirmation | travel/search/gather plan should be explicit | `natural_intake_route_gap` |
| natural discovery recognition | record new tribe | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize discovery that must save structured event/entity | `natural_intake_misread_as_query` |
| natural discovery recognition | observe civilization trace | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize discovery that must save structured event/entity | `natural_intake_misread_as_query` |
| natural discovery recognition | ask an civilization rumor | start=query:entity can_proceed=True preview=action:query ready=False status=ready | recognize social confirmation of new fact | `natural_intake_misread_as_query` |
| natural discovery recognition | record earthquake | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize event intake, not only routine narration | `natural_intake_misread_as_query` |
| natural discovery recognition | new spring | start=query:entity can_proceed=True preview=action:query ready=False status=ready | recognize location discovery intake | `natural_intake_misread_as_query` |
| natural discovery recognition | new cave | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize location discovery intake | `natural_intake_misread_as_query` |
| natural discovery recognition | new caravan | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify | recognize encounter/faction discovery | `natural_intake_route_gap` |
| natural discovery recognition | new species | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify | recognize species/civilization discovery | `natural_intake_route_gap` |
| natural gather recognition | rubbing slab | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize item intake and require structured output | `natural_intake_misread_as_query` |
| natural gather recognition | footprint sample | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize evidence/sample intake | `natural_intake_misread_as_query` |
| intake guardrail | negative gathered quantity | committed=True ok=False blocked=True no_persist=False | should block negative gathered quantity before writing | `intake_guardrail_reported_after_write` |
| intake guardrail | zero gathered quantity | committed=True ok=True blocked=False no_persist=False | should block zero-quantity intake when event claims new stock | `intake_guardrail_missing` |
| intake guardrail | output id mismatch | committed=True ok=True blocked=False no_persist=False | should block mismatch between event output_item_id and upsert entity id | `intake_guardrail_missing` |
| intake guardrail | missing location on item | committed=True ok=True blocked=False no_persist=False | should block newly gathered inventory without location_id or owner_id | `intake_guardrail_missing` |
| intake guardrail | fuzzy high risk quantity | committed=True ok=True blocked=False no_persist=False | should block high-risk inventory intake without exact quantity | `intake_guardrail_missing` |
| intake guardrail | civilization event without entity | committed=True ok=True blocked=False no_persist=True | should block confirmed new civilization event without structured entity/reference | `intake_guardrail_missing` |
| intake guardrail | location entity without location payload | committed=True ok=True blocked=False no_persist=False | should block location entity without location payload | `intake_guardrail_missing` |

## Full Matrix

| Status | Area | Case | Observed | Expected |
|---|---|---|---|---|
| PASS | natural gather recognition | gather water spinach | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | collect water spinach | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | cut two water spinach | start=action:gather can_proceed=True preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick shiso | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick hemostatic herb | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick anti-inflammatory herb | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | dig fever root | start=action:gather can_proceed=True preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick moon dew | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | collect moon moss | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | collect thunder moss | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | harvest fish trap | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather or require travel before saving |
| PASS | natural gather recognition | take fish from trap | start=action:gather can_proceed=True preview=action:gather ready=False status=clarify | recognize gather or require travel before saving |
| PASS | natural gather recognition | go creek harvest trap | start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation | recognize travel+gather plan instead of inventory query |
| PASS | natural gather recognition | fetch spring water | start=action:travel can_proceed=True preview=action:travel ready=True status=ready | recognize travel+gather plan instead of inventory query |
| ISSUE | natural gather recognition | fill water bottle | start=action:combat can_proceed=False preview=action:combat ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick pine nuts | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick pine cone | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | collect milky sap | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | collect sulfur shards | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | dig niter | start=action:gather can_proceed=True preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick flint | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| ISSUE | natural gather recognition | collect hemp fiber | start=query:entity can_proceed=True preview=action:query ready=False status=ready | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | collect lake fiber | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | take root mycelium sample | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick berries | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick chili | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | pick wild onion | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | cut chives | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | harvest potatoes | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | harvest sweet potato | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | look for herbs | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | resource search should become gather |
| PASS | natural gather recognition | look for materials | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | resource search should become gather |
| ISSUE | natural gather recognition | search food | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked | resource search should become gather |
| ISSUE | natural gather recognition | search creek materials | start=action:explore can_proceed=False preview=action:explore ready=False status=needs_confirmation | travel/search/gather plan should be explicit |
| PASS | natural discovery recognition | inspect smoke column | start=action:explore can_proceed=True preview=action:explore ready=True status=ready | recognize exploration/discovery, not query |
| PASS | natural discovery recognition | scout strange footprints | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked | recognize exploration/discovery, not query |
| PASS | natural discovery recognition | search pottery shard | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked | recognize exploration/discovery, not query |
| ISSUE | natural discovery recognition | record new tribe | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize discovery that must save structured event/entity |
| ISSUE | natural discovery recognition | observe civilization trace | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize discovery that must save structured event/entity |
| ISSUE | natural discovery recognition | ask an civilization rumor | start=query:entity can_proceed=True preview=action:query ready=False status=ready | recognize social confirmation of new fact |
| PASS | natural discovery recognition | ask eve new event | start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation | recognize social fact intake |
| ISSUE | natural discovery recognition | record earthquake | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize event intake, not only routine narration |
| ISSUE | natural discovery recognition | new spring | start=query:entity can_proceed=True preview=action:query ready=False status=ready | recognize location discovery intake |
| ISSUE | natural discovery recognition | new cave | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize location discovery intake |
| ISSUE | natural discovery recognition | new caravan | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify | recognize encounter/faction discovery |
| ISSUE | natural discovery recognition | new species | start=action:travel can_proceed=False preview=action:travel ready=False status=clarify | recognize species/civilization discovery |
| PASS | natural discovery recognition | night whistle source | start=action:explore can_proceed=False preview=action:explore ready=False status=blocked | recognize event/threat discovery |
| PASS | natural gather recognition | unknown feather | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | blue mineral sand | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | recognize gather and ask for confirmed output before saving |
| ISSUE | natural gather recognition | rubbing slab | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize item intake and require structured output |
| PASS | natural gather recognition | honeycomb mushroom | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | crystal mushroom | start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation | recognize gather and ask for confirmed output before saving |
| PASS | natural gather recognition | powder residue | start=action:gather can_proceed=False preview=action:gather ready=False status=clarify | recognize high-risk gather and require exact output |
| ISSUE | natural gather recognition | footprint sample | start=query:entity can_proceed=False preview=action:query ready=False status=ready | recognize evidence/sample intake |
| PASS | confirmed inventory intake | water spinach leaves | committed=True ok=True row=2.0株 event_ok=True query_ok=True | immediately store 测试入库001 空心菜嫩叶 as 2株 |
| PASS | confirmed inventory intake | shiso leaves | committed=True ok=True row=5.0片 event_ok=True query_ok=True | immediately store 测试入库002 紫苏叶 as 5片 |
| PASS | confirmed inventory intake | lettuce leaves | committed=True ok=True row=3.0片 event_ok=True query_ok=True | immediately store 测试入库003 红叶生菜叶 as 3片 |
| PASS | confirmed inventory intake | garlic leaves | committed=True ok=True row=4.0束 event_ok=True query_ok=True | immediately store 测试入库004 蒜叶束 as 4束 |
| PASS | confirmed inventory intake | wild onion | committed=True ok=True row=2.0把 event_ok=True query_ok=True | immediately store 测试入库005 野葱把 as 2把 |
| PASS | confirmed inventory intake | pine nuts | committed=True ok=True row=0.5竹杯 event_ok=True query_ok=True | immediately store 测试入库006 松子仁补充 as 0.5竹杯 |
| PASS | confirmed inventory intake | pine nut oil | committed=True ok=True row=0.25竹杯 event_ok=True query_ok=True | immediately store 测试入库007 松子油补装 as 0.25竹杯 |
| PASS | confirmed inventory intake | berries | committed=True ok=True row=6.0枚 event_ok=True query_ok=True | immediately store 测试入库008 红浆果补充 as 6枚 |
| PASS | confirmed inventory intake | fresh chili | committed=True ok=True row=2.0个 event_ok=True query_ok=True | immediately store 测试入库009 新鲜辣椒补充 as 2个 |
| PASS | confirmed inventory intake | ginger | committed=True ok=True row=1.0块 event_ok=True query_ok=True | immediately store 测试入库010 生姜块 as 1块 |
| PASS | confirmed inventory intake | clear water | committed=True ok=True row=1.0L event_ok=True query_ok=True | immediately store 测试入库011 清水补给 as 1L |
| PASS | confirmed inventory intake | filtered water | committed=True ok=True row=0.5L event_ok=True query_ok=True | immediately store 测试入库012 过滤水 as 0.5L |
| PASS | confirmed inventory intake | hemostatic herb | committed=True ok=True row=3.0株 event_ok=True query_ok=True | immediately store 测试入库013 止血草样本 as 3株 |
| PASS | confirmed inventory intake | anti inflammatory herb | committed=True ok=True row=2.0株 event_ok=True query_ok=True | immediately store 测试入库014 消炎草样本 as 2株 |
| PASS | confirmed inventory intake | fever root slices | committed=True ok=True row=4.0片 event_ok=True query_ok=True | immediately store 测试入库015 退热根切片 as 4片 |
| PASS | confirmed inventory intake | insect repellent herb | committed=True ok=True row=2.0株 event_ok=True query_ok=True | immediately store 测试入库016 驱虫草样本 as 2株 |
| PASS | confirmed inventory intake | moon dew herb | committed=True ok=True row=1.0株 event_ok=True query_ok=True | immediately store 测试入库017 月露草样本 as 1株 |
| PASS | confirmed inventory intake | moon moss | committed=True ok=True row=0.5捧 event_ok=True query_ok=True | immediately store 测试入库018 月光苔样本 as 0.5捧 |
| PASS | confirmed inventory intake | thunder moss | committed=True ok=True row=1.0片 event_ok=True query_ok=True | immediately store 测试入库019 雷苔样本 as 1片 |
| PASS | confirmed inventory intake | frost leaf | committed=True ok=True row=2.0片 event_ok=True query_ok=True | immediately store 测试入库020 霜叶样本 as 2片 |
| PASS | confirmed inventory intake | hemp fiber | committed=True ok=True row=0.75kg event_ok=True query_ok=True | immediately store 测试入库021 麻纤维补充 as 0.75kg |
| PASS | confirmed inventory intake | common resin | committed=True ok=True row=0.2竹杯 event_ok=True query_ok=True | immediately store 测试入库022 普通残胶样本 as 0.2竹杯 |
| PASS | confirmed inventory intake | hardened resin | committed=True ok=True row=0.1竹杯 event_ok=True query_ok=True | immediately store 测试入库023 硬化残胶碎片 as 0.1竹杯 |
| PASS | confirmed inventory intake | milky residue | committed=True ok=True row=0.1竹杯 event_ok=True query_ok=True | immediately store 测试入库024 乳白残液样本 as 0.1竹杯 |
| PASS | confirmed inventory intake | bamboo cup | committed=True ok=True row=1.0个 event_ok=True query_ok=True | immediately store 测试入库025 竹杯补充 as 1个 |
| PASS | confirmed inventory intake | salt crystals | committed=True ok=True row=0.1勺 event_ok=True query_ok=True | immediately store 测试入库026 盐晶样本 as 0.1勺 |
| PASS | confirmed inventory intake | sulfur shards | committed=True ok=True row=0.2竹杯 event_ok=True query_ok=True | immediately store 测试入库027 硫磺碎晶样本 as 0.2竹杯 |
| PASS | confirmed inventory intake | niter needles | committed=True ok=True row=0.15竹杯 event_ok=True query_ok=True | immediately store 测试入库028 硝石针晶样本 as 0.15竹杯 |
| PASS | confirmed inventory intake | flint | committed=True ok=True row=1.0块 event_ok=True query_ok=True | immediately store 测试入库029 优质燧石样本 as 1块 |
| PASS | confirmed inventory intake | serpentine | committed=True ok=True row=2.0块 event_ok=True query_ok=True | immediately store 测试入库030 蛇纹石碎片 as 2块 |
| PASS | confirmed inventory intake | river mud | committed=True ok=True row=3.0团 event_ok=True query_ok=True | immediately store 测试入库031 河泥样本 as 3团 |
| PASS | confirmed inventory intake | reed fiber | committed=True ok=True row=1.0捆 event_ok=True query_ok=True | immediately store 测试入库032 芦苇纤维 as 1捆 |
| PASS | confirmed inventory intake | lake fiber | committed=True ok=True row=0.3kg event_ok=True query_ok=True | immediately store 测试入库033 湖边细纤维样本 as 0.3kg |
| PASS | confirmed inventory intake | honeycomb mushroom | committed=True ok=True row=2.0朵 event_ok=True query_ok=True | immediately store 测试入库034 蜂巢菇样本 as 2朵 |
| PASS | confirmed inventory intake | crystal mushroom | committed=True ok=True row=1.0片 event_ok=True query_ok=True | immediately store 测试入库035 晶化菇碎片 as 1片 |
| PASS | confirmed inventory intake | echo pollen | committed=True ok=True row=0.05竹杯 event_ok=True query_ok=True | immediately store 测试入库036 回声花花粉 as 0.05竹杯 |
| PASS | confirmed inventory intake | star seed pod | committed=True ok=True row=3.0枚 event_ok=True query_ok=True | immediately store 测试入库037 星辰草种荚 as 3枚 |
| PASS | confirmed inventory intake | thorn vine | committed=True ok=True row=2.0段 event_ok=True query_ok=True | immediately store 测试入库038 荆棘藤段 as 2段 |
| PASS | confirmed inventory intake | root mycelium | committed=True ok=True row=1.0面 event_ok=True query_ok=True | immediately store 测试入库039 根源菌丝样本 as 1面 |
| PASS | confirmed inventory intake | mother spore | committed=True ok=True row=0.1捧 event_ok=True query_ok=True | immediately store 测试入库040 母孢子树孢子 as 0.1捧 |
| PASS | confirmed inventory intake | sample bag note | committed=True ok=True row=1.0件 event_ok=True query_ok=True | immediately store 测试入库041 样品袋记录 as 1件 |
| PASS | confirmed inventory intake | footprint cast | committed=True ok=True row=1.0件 event_ok=True query_ok=True | immediately store 测试入库042 新脚印石膏模 as 1件 |
| PASS | confirmed inventory intake | pottery shard | committed=True ok=True row=2.0片 event_ok=True query_ok=True | immediately store 测试入库043 陌生陶片 as 2片 |
| PASS | confirmed inventory intake | weave rubbing | committed=True ok=True row=1.0张 event_ok=True query_ok=True | immediately store 测试入库044 编织纹样拓片 as 1张 |
| PASS | confirmed inventory intake | charcoal sample | committed=True ok=True row=5.0块 event_ok=True query_ok=True | immediately store 测试入库045 焦黑木炭样本 as 5块 |
| PASS | confirmed inventory intake | metal filings | committed=True ok=True row=0.05竹杯 event_ok=True query_ok=True | immediately store 测试入库046 金属碎屑 as 0.05竹杯 |
| PASS | confirmed inventory intake | blue mineral sand | committed=True ok=True row=0.2竹杯 event_ok=True query_ok=True | immediately store 测试入库047 蓝色矿砂 as 0.2竹杯 |
| PASS | confirmed inventory intake | resin drops | committed=True ok=True row=7.0滴 event_ok=True query_ok=True | immediately store 测试入库048 透明树脂滴 as 7滴 |
| PASS | confirmed inventory intake | animal hair | committed=True ok=True row=1.0撮 event_ok=True query_ok=True | immediately store 测试入库049 动物毛束 as 1撮 |
| PASS | confirmed inventory intake | fish scales | committed=True ok=True row=6.0片 event_ok=True query_ok=True | immediately store 测试入库050 鱼鳞样本 as 6片 |
| PASS | confirmed inventory intake | toxin strip | committed=True ok=True row=1.0张 event_ok=True query_ok=True | immediately store 测试入库051 毒液试纸 as 1张 |
| PASS | confirmed inventory intake | powder residue | committed=True ok=True row=0.02竹杯 event_ok=True query_ok=True | immediately store 测试入库052 火药残渣样本 as 0.02竹杯 |
| PASS | confirmed inventory intake | paralysis spore | committed=True ok=True row=0.1捧 event_ok=True query_ok=True | immediately store 测试入库053 麻痹孢子样本 as 0.1捧 |
| PASS | confirmed inventory intake | black eggshell | committed=True ok=True row=1.0片 event_ok=True query_ok=True | immediately store 测试入库054 不明黑色卵壳 as 1片 |
| PASS | confirmed inventory intake | watch bell | committed=True ok=True row=1.0个 event_ok=True query_ok=True | immediately store 测试入库055 警戒哨采样铃 as 1个 |
| PASS | confirmed world/event intake | new smoke ridge | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new spring | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new cave mouth | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new faction | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new species | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new envoy | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new threat | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new project | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new reference | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new world setting | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new relationship | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new faction rumor | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new event reference | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new species track | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new encounter note | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new marker | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new cultural artifact | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new fungal incident | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new trade item | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | confirmed world/event intake | new hazard note | committed=True ok=True event_ok=True entities_ok=True query_ok=True | event and new fact entities are immediately persisted and queryable |
| PASS | intake guardrail | output event without upsert | committed=False ok=False blocked=True no_persist=True | should block claimed inventory output without matching upsert_entities |
| PASS | intake guardrail | non numeric quantity | committed=False ok=False blocked=True no_persist=True | should block non-numeric item.quantity in exact inventory upsert |
| PASS | intake guardrail | item without item payload | committed=False ok=False blocked=True no_persist=True | should block item entity without item payload |
| ISSUE | intake guardrail | negative gathered quantity | committed=True ok=False blocked=True no_persist=False | should block negative gathered quantity before writing |
| ISSUE | intake guardrail | zero gathered quantity | committed=True ok=True blocked=False no_persist=False | should block zero-quantity intake when event claims new stock |
| ISSUE | intake guardrail | output id mismatch | committed=True ok=True blocked=False no_persist=False | should block mismatch between event output_item_id and upsert entity id |
| ISSUE | intake guardrail | missing location on item | committed=True ok=True blocked=False no_persist=False | should block newly gathered inventory without location_id or owner_id |
| PASS | intake guardrail | both owner and location | committed=False ok=False blocked=True no_persist=True | should block active entity with both owner_id and location_id |
| PASS | intake guardrail | unknown location ref | committed=False ok=False blocked=True no_persist=True | should block newly gathered inventory with missing location ref |
| PASS | intake guardrail | duplicate upsert ids | committed=False ok=False blocked=True no_persist=True | should block duplicate upsert entity ids |
| ISSUE | intake guardrail | fuzzy high risk quantity | committed=True ok=True blocked=False no_persist=False | should block high-risk inventory intake without exact quantity |
| ISSUE | intake guardrail | civilization event without entity | committed=True ok=True blocked=False no_persist=True | should block confirmed new civilization event without structured entity/reference |
| ISSUE | intake guardrail | location entity without location payload | committed=True ok=True blocked=False no_persist=False | should block location entity without location payload |

## Details

### PASS · natural gather recognition · gather water spinach

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采空心菜
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · collect water spinach

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=收一点空心菜
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · cut two water spinach

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=割2株空心菜入库
- player_message=目标未指定：保存前必须明确采集对象和产出。
- errors=['目标未指定：保存前必须明确采集对象和产出。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick shiso

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=摘紫苏叶
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick hemostatic herb

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采止血草
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick anti-inflammatory herb

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采消炎草
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · dig fever root

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=挖退热根
- player_message=目标未指定：保存前必须明确采集对象和产出。
- errors=['目标未指定：保存前必须明确采集对象和产出。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick moon dew

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采月露草
- player_message=月露草 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-clearing；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · collect moon moss

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采月光苔
- player_message=月光苔 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-clearing；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · collect thunder moss

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采雷苔
- player_message=雷苔 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-clearing；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · harvest fish trap

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather or require travel before saving
- text=收鱼笼
- player_message=竹编鱼笼 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:l01-creek；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · take fish from trap

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=clarify
- Expected: recognize gather or require travel before saving
- text=从鱼笼取鱼
- player_message=目标未指定：保存前必须明确采集对象和产出。
- errors=['目标未指定：保存前必须明确采集对象和产出。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · go creek harvest trap

- Observed: start=action:composite can_proceed=False preview=action:act ready=False status=needs_confirmation
- Expected: recognize travel+gather plan instead of inventory query
- text=去L1小溪收鱼笼
- player_message=我理解你想先去 小溪，再处理现场目标。需要先确认 travel，再重新预演后续行动。
- errors=[]
- warnings=['composite action requires step confirmation']

### PASS · natural gather recognition · fetch spring water

- Observed: start=action:travel can_proceed=True preview=action:travel ready=True status=ready
- Expected: recognize travel+gather plan instead of inventory query
- text=去泉眼取水
- player_message=travel 预演已准备好，可以提交结构化 delta。
- errors=[]
- warnings=['目的地安全等级为 moderate：到达后必须先输出风险和迹象。']

### ISSUE · natural gather recognition · fill water bottle

- Observed: start=action:combat can_proceed=False preview=action:combat ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- Issue: `natural_intake_route_gap`
- text=打一筒水
- player_message=还需要补充 target, weapon, ammo, distance，我才能可靠结算这次 combat。
- errors=['目标未明确：需要目标实体或清楚的场景目标。', '距离未明确：需要至少给出贴身/近距/标准/远距或步数。', '弹药未明确：射击前必须选择弹药。', '武器未明确：保存前必须指定武器，不能由引擎默认选择。']
- warnings=[]

### PASS · natural gather recognition · pick pine nuts

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=捡松子
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick pine cone

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=捡松塔
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。
- errors=[]
- warnings=[]

### PASS · natural gather recognition · collect milky sap

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采见血封喉乳汁
- player_message=见血封喉 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-clearing；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · collect sulfur shards

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采硫磺碎晶
- player_message=硫磺碎晶 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-old-hut；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · dig niter

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=挖硝石
- player_message=目标未指定：保存前必须明确采集对象和产出。
- errors=['目标未指定：保存前必须明确采集对象和产出。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick flint

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=捡燧石
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### ISSUE · natural gather recognition · collect hemp fiber

- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready
- Expected: recognize gather and ask for confirmed output before saving
- Issue: `natural_intake_misread_as_query`
- text=搜集麻纤维
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### PASS · natural gather recognition · collect lake fiber

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=收集湖边细纤维
- player_message=湖边细纤维 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:l01-creek；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · take root mycelium sample

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采根源菌丝样本
- player_message=根源菌丝 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-mycelium-city；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick berries

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=摘红浆果
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick chili

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采红辣椒
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · pick wild onion

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采野葱
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · cut chives

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=割韭菜
- player_message=目标未指定：保存前必须明确采集对象和产出。
- errors=['目标未指定：保存前必须明确采集对象和产出。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · harvest potatoes

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=收土豆
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · harvest sweet potato

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=收红薯
- player_message=采集目标已识别，但保存前必须补明确产出数量和资源状态。
- errors=['需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · look for herbs

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: resource search should become gather
- text=找草药
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。
- errors=[]
- warnings=[]

### PASS · natural gather recognition · look for materials

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: resource search should become gather
- text=找材料
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。
- errors=[]
- warnings=[]

### ISSUE · natural gather recognition · search food

- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked
- Expected: resource search should become gather
- Issue: `natural_intake_route_gap`
- text=搜索可用食材
- player_message=我没找到“搜索可用食材”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- errors=['target not found: 搜索可用食材']
- warnings=[]

### ISSUE · natural gather recognition · search creek materials

- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=needs_confirmation
- Expected: travel/search/gather plan should be explicit
- Issue: `natural_intake_route_gap`
- text=搜索河边可采集材料
- player_message=source_user_text 更像 `gather`，但调用方传入了 `explore`。请改用 preview_from_text 或确认 action 后重试。
- errors=[]
- warnings=['source_user_text 更像 `gather`，但调用方传入了 `explore`。请改用 preview_from_text 或确认 action 后重试。']

### PASS · natural discovery recognition · inspect smoke column

- Observed: start=action:explore can_proceed=True preview=action:explore ready=True status=ready
- Expected: recognize exploration/discovery, not query
- text=调查远处烟柱看看有没有文明
- player_message=探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。
- errors=[]
- warnings=[]

### PASS · natural discovery recognition · scout strange footprints

- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked
- Expected: recognize exploration/discovery, not query
- text=侦查陌生脚印并记录
- player_message=我没找到“侦查陌生脚印并记录”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- errors=['target not found: 侦查陌生脚印并记录']
- warnings=[]

### PASS · natural discovery recognition · search pottery shard

- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked
- Expected: recognize exploration/discovery, not query
- text=搜索陌生陶片来源
- player_message=我没找到“搜索陌生陶片来源”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- errors=['target not found: 搜索陌生陶片来源']
- warnings=[]

### ISSUE · natural discovery recognition · record new tribe

- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready
- Expected: recognize discovery that must save structured event/entity
- Issue: `natural_intake_misread_as_query`
- text=发现新部落，先记录下来
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### ISSUE · natural discovery recognition · observe civilization trace

- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready
- Expected: recognize discovery that must save structured event/entity
- Issue: `natural_intake_misread_as_query`
- text=观察陌生文明留下的编织纹样
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### ISSUE · natural discovery recognition · ask an civilization rumor

- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready
- Expected: recognize social confirmation of new fact
- Issue: `natural_intake_misread_as_query`
- text=和An确认新文明传闻
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### PASS · natural discovery recognition · ask eve new event

- Observed: start=action:social can_proceed=True preview=action:social ready=False status=needs_confirmation
- Expected: recognize social fact intake
- text=问夏娃有没有发现新的菌丝事件
- player_message=夏娃 不在你当前地点。对方在 地下菌丝城，你现在在 六边形菌丝复合屋。可以先过去再交谈，预计 2 分钟。
- errors=['对象不在当前地点：loc:home-mycelium-city；可能需要先 travel。']
- warnings=['关系变化必须记录 trust/attitude/承诺，不只写对话散文。', '未发现额外结构化警告；仍需按对方反应确认关系变化。']

### ISSUE · natural discovery recognition · record earthquake

- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready
- Expected: recognize event intake, not only routine narration
- Issue: `natural_intake_misread_as_query`
- text=记录一次刚发生的地震事件
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### ISSUE · natural discovery recognition · new spring

- Observed: start=query:entity can_proceed=True preview=action:query ready=False status=ready
- Expected: recognize location discovery intake
- Issue: `natural_intake_misread_as_query`
- text=发现新的泉眼并标记位置
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### ISSUE · natural discovery recognition · new cave

- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready
- Expected: recognize location discovery intake
- Issue: `natural_intake_misread_as_query`
- text=发现新洞穴入口并记录
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### ISSUE · natural discovery recognition · new caravan

- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify
- Expected: recognize encounter/faction discovery
- Issue: `natural_intake_route_gap`
- text=遇到一队陌生商旅，先观察记录
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- errors=[]
- warnings=[]

### ISSUE · natural discovery recognition · new species

- Observed: start=action:travel can_proceed=False preview=action:travel ready=False status=clarify
- Expected: recognize species/civilization discovery
- Issue: `natural_intake_route_gap`
- text=遇到陌生种族先观察
- player_message=我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。
- errors=[]
- warnings=[]

### PASS · natural discovery recognition · night whistle source

- Observed: start=action:explore can_proceed=False preview=action:explore ready=False status=blocked
- Expected: recognize event/threat discovery
- text=搜索夜里哨声来源
- player_message=我没找到“搜索夜里哨声来源”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。
- errors=['target not found: 搜索夜里哨声来源']
- warnings=[]

### PASS · natural gather recognition · unknown feather

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=捡起地上的未知羽毛入库
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。
- errors=[]
- warnings=[]

### PASS · natural gather recognition · blue mineral sand

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: recognize gather and ask for confirmed output before saving
- text=收集蓝色矿砂
- player_message=我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。
- errors=[]
- warnings=[]

### ISSUE · natural gather recognition · rubbing slab

- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready
- Expected: recognize item intake and require structured output
- Issue: `natural_intake_misread_as_query`
- text=把新发现的石碑拓片入库
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### PASS · natural gather recognition · honeycomb mushroom

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采集蜂巢菇
- player_message=蜂巢菇 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-clearing；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · crystal mushroom

- Observed: start=action:gather can_proceed=True preview=action:gather ready=False status=needs_confirmation
- Expected: recognize gather and ask for confirmed output before saving
- text=采晶化菇
- player_message=晶化菇 不在 六边形菌丝复合屋。需要改地点、改目标，或先移动到对象所在地点。
- errors=['目标不在指定地点：loc:home-clearing；可能需要改地点或先 travel。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### PASS · natural gather recognition · powder residue

- Observed: start=action:gather can_proceed=False preview=action:gather ready=False status=clarify
- Expected: recognize high-risk gather and require exact output
- text=取火药残渣样本
- player_message=目标未指定：保存前必须明确采集对象和产出。
- errors=['目标未指定：保存前必须明确采集对象和产出。']
- warnings=['保存前必须明确新增库存的 id/name/category/quantity/unit/location。']

### ISSUE · natural gather recognition · footprint sample

- Observed: start=query:entity can_proceed=False preview=action:query ready=False status=ready
- Expected: recognize evidence/sample intake
- Issue: `natural_intake_misread_as_query`
- text=搜集围墙附近的脚印样本
- player_message=这是只读查询请求，不需要行动预演或保存。
- errors=[]
- warnings=[]

### PASS · confirmed inventory intake · water spinach leaves

- Observed: committed=True ok=True row=2.0株 event_ok=True query_ok=True
- Expected: immediately store 测试入库001 空心菜嫩叶 as 2株
- text=确认采到2株空心菜嫩叶并入库
- turn_id=turn:000045
- query=## 装备/物品：测试入库001 空心菜嫩叶 | 字段 | 值 | |------|----| | ID | `item:probe-intake-001` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2株 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到2株空心菜嫩叶并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · shiso leaves

- Observed: committed=True ok=True row=5.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库002 紫苏叶 as 5片
- text=确认摘到5片紫苏叶并入库
- turn_id=turn:000046
- query=## 装备/物品：测试入库002 紫苏叶 | 字段 | 值 | |------|----| | ID | `item:probe-intake-002` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 5片 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认摘到5片紫苏叶并入库；测试临时存档入库。 ###...

### PASS · confirmed inventory intake · lettuce leaves

- Observed: committed=True ok=True row=3.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库003 红叶生菜叶 as 3片
- text=确认收获3片红叶生菜并入库
- turn_id=turn:000047
- query=## 装备/物品：测试入库003 红叶生菜叶 | 字段 | 值 | |------|----| | ID | `item:probe-intake-003` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3片 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认收获3片红叶生菜并入库；测试临时存档入库。 ...

### PASS · confirmed inventory intake · garlic leaves

- Observed: committed=True ok=True row=4.0束 event_ok=True query_ok=True
- Expected: immediately store 测试入库004 蒜叶束 as 4束
- text=确认割到4束蒜叶并入库
- turn_id=turn:000048
- query=## 装备/物品：测试入库004 蒜叶束 | 字段 | 值 | |------|----| | ID | `item:probe-intake-004` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 4束 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认割到4束蒜叶并入库；测试临时存档入库。 ### ...

### PASS · confirmed inventory intake · wild onion

- Observed: committed=True ok=True row=2.0把 event_ok=True query_ok=True
- Expected: immediately store 测试入库005 野葱把 as 2把
- text=确认采到2把野葱并入库
- turn_id=turn:000049
- query=## 装备/物品：测试入库005 野葱把 | 字段 | 值 | |------|----| | ID | `item:probe-intake-005` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2把 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到2把野葱并入库；测试临时存档入库。 ### ...

### PASS · confirmed inventory intake · pine nuts

- Observed: committed=True ok=True row=0.5竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库006 松子仁补充 as 0.5竹杯
- text=确认捡到0.5竹杯松子仁并入库
- turn_id=turn:000050
- query=## 装备/物品：测试入库006 松子仁补充 | 字段 | 值 | |------|----| | ID | `item:probe-intake-006` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.5竹杯 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认捡到0.5竹杯松子仁并入库；测试临时...

### PASS · confirmed inventory intake · pine nut oil

- Observed: committed=True ok=True row=0.25竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库007 松子油补装 as 0.25竹杯
- text=确认滤出0.25竹杯松子油并入库
- turn_id=turn:000051
- query=## 装备/物品：测试入库007 松子油补装 | 字段 | 值 | |------|----| | ID | `item:probe-intake-007` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.25竹杯 | | 品质 | filtered | | 装备槽 | 无 | ### 摘要 确认滤出0.25竹杯松子油并...

### PASS · confirmed inventory intake · berries

- Observed: committed=True ok=True row=6.0枚 event_ok=True query_ok=True
- Expected: immediately store 测试入库008 红浆果补充 as 6枚
- text=确认摘到6枚红浆果并入库
- turn_id=turn:000052
- query=## 装备/物品：测试入库008 红浆果补充 | 字段 | 值 | |------|----| | ID | `item:probe-intake-008` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 6枚 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认摘到6枚红浆果并入库；测试临时存档入库。 #...

### PASS · confirmed inventory intake · fresh chili

- Observed: committed=True ok=True row=2.0个 event_ok=True query_ok=True
- Expected: immediately store 测试入库009 新鲜辣椒补充 as 2个
- text=确认摘到2个新鲜辣椒并入库
- turn_id=turn:000053
- query=## 装备/物品：测试入库009 新鲜辣椒补充 | 字段 | 值 | |------|----| | ID | `item:probe-intake-009` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2个 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认摘到2个新鲜辣椒并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · ginger

- Observed: committed=True ok=True row=1.0块 event_ok=True query_ok=True
- Expected: immediately store 测试入库010 生姜块 as 1块
- text=确认挖到1块生姜并入库
- turn_id=turn:000054
- query=## 装备/物品：测试入库010 生姜块 | 字段 | 值 | |------|----| | ID | `item:probe-intake-010` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1块 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认挖到1块生姜并入库；测试临时存档入库。 ### ...

### PASS · confirmed inventory intake · clear water

- Observed: committed=True ok=True row=1.0L event_ok=True query_ok=True
- Expected: immediately store 测试入库011 清水补给 as 1L
- text=确认灌到1L清水并入库
- turn_id=turn:000055
- query=## 装备/物品：测试入库011 清水补给 | 字段 | 值 | |------|----| | ID | `item:probe-intake-011` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1L | | 品质 | clean | | 装备槽 | 无 | ### 摘要 确认灌到1L清水并入库；测试临时存档入库。 ...

### PASS · confirmed inventory intake · filtered water

- Observed: committed=True ok=True row=0.5L event_ok=True query_ok=True
- Expected: immediately store 测试入库012 过滤水 as 0.5L
- text=确认过滤出0.5L水并入库
- turn_id=turn:000056
- query=## 装备/物品：测试入库012 过滤水 | 字段 | 值 | |------|----| | ID | `item:probe-intake-012` | | 类型 | 物品 | | 分类 | 食物 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.5L | | 品质 | filtered | | 装备槽 | 无 | ### 摘要 确认过滤出0.5L水并入库；测试临时...

### PASS · confirmed inventory intake · hemostatic herb

- Observed: committed=True ok=True row=3.0株 event_ok=True query_ok=True
- Expected: immediately store 测试入库013 止血草样本 as 3株
- text=确认采到3株止血草样本并入库
- turn_id=turn:000057
- query=## 装备/物品：测试入库013 止血草样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-013` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3株 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到3株止血草样本并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · anti inflammatory herb

- Observed: committed=True ok=True row=2.0株 event_ok=True query_ok=True
- Expected: immediately store 测试入库014 消炎草样本 as 2株
- text=确认采到2株消炎草样本并入库
- turn_id=turn:000058
- query=## 装备/物品：测试入库014 消炎草样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-014` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2株 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到2株消炎草样本并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · fever root slices

- Observed: committed=True ok=True row=4.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库015 退热根切片 as 4片
- text=确认切下4片退热根并入库
- turn_id=turn:000059
- query=## 装备/物品：测试入库015 退热根切片 | 字段 | 值 | |------|----| | ID | `item:probe-intake-015` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 4片 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认切下4片退热根并入库；测试临时存档入库。 #...

### PASS · confirmed inventory intake · insect repellent herb

- Observed: committed=True ok=True row=2.0株 event_ok=True query_ok=True
- Expected: immediately store 测试入库016 驱虫草样本 as 2株
- text=确认采到2株驱虫草并入库
- turn_id=turn:000060
- query=## 装备/物品：测试入库016 驱虫草样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-016` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2株 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到2株驱虫草并入库；测试临时存档入库。 #...

### PASS · confirmed inventory intake · moon dew herb

- Observed: committed=True ok=True row=1.0株 event_ok=True query_ok=True
- Expected: immediately store 测试入库017 月露草样本 as 1株
- text=确认采到1株月露草样本并入库
- turn_id=turn:000061
- query=## 装备/物品：测试入库017 月露草样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-017` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1株 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到1株月露草样本并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · moon moss

- Observed: committed=True ok=True row=0.5捧 event_ok=True query_ok=True
- Expected: immediately store 测试入库018 月光苔样本 as 0.5捧
- text=确认刮下0.5捧月光苔并入库
- turn_id=turn:000062
- query=## 装备/物品：测试入库018 月光苔样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-018` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.5捧 | | 品质 | damp | | 装备槽 | 无 | ### 摘要 确认刮下0.5捧月光苔并入库；测试临时存...

### PASS · confirmed inventory intake · thunder moss

- Observed: committed=True ok=True row=1.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库019 雷苔样本 as 1片
- text=确认收下1片雷苔并入库
- turn_id=turn:000063
- query=## 装备/物品：测试入库019 雷苔样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-019` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1片 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认收下1片雷苔并入库；测试临时存档入库。 ###...

### PASS · confirmed inventory intake · frost leaf

- Observed: committed=True ok=True row=2.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库020 霜叶样本 as 2片
- text=确认采到2片霜叶并入库
- turn_id=turn:000064
- query=## 装备/物品：测试入库020 霜叶样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-020` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2片 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到2片霜叶并入库；测试临时存档入库。 ###...

### PASS · confirmed inventory intake · hemp fiber

- Observed: committed=True ok=True row=0.75kg event_ok=True query_ok=True
- Expected: immediately store 测试入库021 麻纤维补充 as 0.75kg
- text=确认整理出0.75kg麻纤维并入库
- turn_id=turn:000065
- query=## 装备/物品：测试入库021 麻纤维补充 | 字段 | 值 | |------|----| | ID | `item:probe-intake-021` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.75kg | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认整理出0.75kg麻纤维并入库；测...

### PASS · confirmed inventory intake · common resin

- Observed: committed=True ok=True row=0.2竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库022 普通残胶样本 as 0.2竹杯
- text=确认收集0.2竹杯普通残胶并入库
- turn_id=turn:000066
- query=## 装备/物品：测试入库022 普通残胶样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-022` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.2竹杯 | | 品质 | sticky | | 装备槽 | 无 | ### 摘要 确认收集0.2竹杯普通残胶并入库...

### PASS · confirmed inventory intake · hardened resin

- Observed: committed=True ok=True row=0.1竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库023 硬化残胶碎片 as 0.1竹杯
- text=确认敲下0.1竹杯硬化残胶并入库
- turn_id=turn:000067
- query=## 装备/物品：测试入库023 硬化残胶碎片 | 字段 | 值 | |------|----| | ID | `item:probe-intake-023` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.1竹杯 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认敲下0.1竹杯硬化残胶并入库；测试...

### PASS · confirmed inventory intake · milky residue

- Observed: committed=True ok=True row=0.1竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库024 乳白残液样本 as 0.1竹杯
- text=确认收集0.1竹杯乳白残液样本并入库
- turn_id=turn:000068
- query=## 装备/物品：测试入库024 乳白残液样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-024` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.1竹杯 | | 品质 | wet | | 装备槽 | 无 | ### 摘要 确认收集0.1竹杯乳白残液样本并入库；...

### PASS · confirmed inventory intake · bamboo cup

- Observed: committed=True ok=True row=1.0个 event_ok=True query_ok=True
- Expected: immediately store 测试入库025 竹杯补充 as 1个
- text=确认新增1个竹杯并入库
- turn_id=turn:000069
- query=## 装备/物品：测试入库025 竹杯补充 | 字段 | 值 | |------|----| | ID | `item:probe-intake-025` | | 类型 | 物品 | | 分类 | 容器 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1个 | | 品质 | usable | | 装备槽 | 无 | ### 摘要 确认新增1个竹杯并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · salt crystals

- Observed: committed=True ok=True row=0.1勺 event_ok=True query_ok=True
- Expected: immediately store 测试入库026 盐晶样本 as 0.1勺
- text=确认刮下0.1勺盐晶并入库
- turn_id=turn:000070
- query=## 装备/物品：测试入库026 盐晶样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-026` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.1勺 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认刮下0.1勺盐晶并入库；测试临时存档入库...

### PASS · confirmed inventory intake · sulfur shards

- Observed: committed=True ok=True row=0.2竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库027 硫磺碎晶样本 as 0.2竹杯
- text=确认采到0.2竹杯硫磺碎晶并入库
- turn_id=turn:000071
- query=## 装备/物品：测试入库027 硫磺碎晶样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-027` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.2竹杯 | | 品质 | raw | | 装备槽 | 无 | ### 摘要 确认采到0.2竹杯硫磺碎晶并入库；测试...

### PASS · confirmed inventory intake · niter needles

- Observed: committed=True ok=True row=0.15竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库028 硝石针晶样本 as 0.15竹杯
- text=确认采到0.15竹杯硝石针晶并入库
- turn_id=turn:000072
- query=## 装备/物品：测试入库028 硝石针晶样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-028` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.15竹杯 | | 品质 | raw | | 装备槽 | 无 | ### 摘要 确认采到0.15竹杯硝石针晶并入库；...

### PASS · confirmed inventory intake · flint

- Observed: committed=True ok=True row=1.0块 event_ok=True query_ok=True
- Expected: immediately store 测试入库029 优质燧石样本 as 1块
- text=确认捡到1块优质燧石并入库
- turn_id=turn:000073
- query=## 装备/物品：测试入库029 优质燧石样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-029` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1块 | | 品质 | sharp | | 装备槽 | 无 | ### 摘要 确认捡到1块优质燧石并入库；测试临时存档...

### PASS · confirmed inventory intake · serpentine

- Observed: committed=True ok=True row=2.0块 event_ok=True query_ok=True
- Expected: immediately store 测试入库030 蛇纹石碎片 as 2块
- text=确认捡到2块蛇纹石碎片并入库
- turn_id=turn:000074
- query=## 装备/物品：测试入库030 蛇纹石碎片 | 字段 | 值 | |------|----| | ID | `item:probe-intake-030` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2块 | | 品质 | raw | | 装备槽 | 无 | ### 摘要 确认捡到2块蛇纹石碎片并入库；测试临时存档入库...

### PASS · confirmed inventory intake · river mud

- Observed: committed=True ok=True row=3.0团 event_ok=True query_ok=True
- Expected: immediately store 测试入库031 河泥样本 as 3团
- text=确认采到3团河泥样本并入库
- turn_id=turn:000075
- query=## 装备/物品：测试入库031 河泥样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-031` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3团 | | 品质 | wet | | 装备槽 | 无 | ### 摘要 确认采到3团河泥样本并入库；测试临时存档入库。 ...

### PASS · confirmed inventory intake · reed fiber

- Observed: committed=True ok=True row=1.0捆 event_ok=True query_ok=True
- Expected: immediately store 测试入库032 芦苇纤维 as 1捆
- text=确认整理出1捆芦苇纤维并入库
- turn_id=turn:000076
- query=## 装备/物品：测试入库032 芦苇纤维 | 字段 | 值 | |------|----| | ID | `item:probe-intake-032` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1捆 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认整理出1捆芦苇纤维并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · lake fiber

- Observed: committed=True ok=True row=0.3kg event_ok=True query_ok=True
- Expected: immediately store 测试入库033 湖边细纤维样本 as 0.3kg
- text=确认收集0.3kg湖边细纤维并入库
- turn_id=turn:000077
- query=## 装备/物品：测试入库033 湖边细纤维样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-033` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.3kg | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认收集0.3kg湖边细纤维并入库；...

### PASS · confirmed inventory intake · honeycomb mushroom

- Observed: committed=True ok=True row=2.0朵 event_ok=True query_ok=True
- Expected: immediately store 测试入库034 蜂巢菇样本 as 2朵
- text=确认采到2朵蜂巢菇样本并入库
- turn_id=turn:000078
- query=## 装备/物品：测试入库034 蜂巢菇样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-034` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2朵 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认采到2朵蜂巢菇样本并入库；测试临时存档入库。...

### PASS · confirmed inventory intake · crystal mushroom

- Observed: committed=True ok=True row=1.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库035 晶化菇碎片 as 1片
- text=确认取下1片晶化菇碎片并入库
- turn_id=turn:000079
- query=## 装备/物品：测试入库035 晶化菇碎片 | 字段 | 值 | |------|----| | ID | `item:probe-intake-035` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1片 | | 品质 | brittle | | 装备槽 | 无 | ### 摘要 确认取下1片晶化菇碎片并入库；测试临时...

### PASS · confirmed inventory intake · echo pollen

- Observed: committed=True ok=True row=0.05竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库036 回声花花粉 as 0.05竹杯
- text=确认收集0.05竹杯回声花花粉并入库
- turn_id=turn:000080
- query=## 装备/物品：测试入库036 回声花花粉 | 字段 | 值 | |------|----| | ID | `item:probe-intake-036` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.05竹杯 | | 品质 | fine | | 装备槽 | 无 | ### 摘要 确认收集0.05竹杯回声花花粉并入库...

### PASS · confirmed inventory intake · star seed pod

- Observed: committed=True ok=True row=3.0枚 event_ok=True query_ok=True
- Expected: immediately store 测试入库037 星辰草种荚 as 3枚
- text=确认收下3枚星辰草种荚并入库
- turn_id=turn:000081
- query=## 装备/物品：测试入库037 星辰草种荚 | 字段 | 值 | |------|----| | ID | `item:probe-intake-037` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 3枚 | | 品质 | seed | | 装备槽 | 无 | ### 摘要 确认收下3枚星辰草种荚并入库；测试临时存档入...

### PASS · confirmed inventory intake · thorn vine

- Observed: committed=True ok=True row=2.0段 event_ok=True query_ok=True
- Expected: immediately store 测试入库038 荆棘藤段 as 2段
- text=确认截下2段荆棘藤并入库
- turn_id=turn:000082
- query=## 装备/物品：测试入库038 荆棘藤段 | 字段 | 值 | |------|----| | ID | `item:probe-intake-038` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2段 | | 品质 | 新鲜 | | 装备槽 | 无 | ### 摘要 确认截下2段荆棘藤并入库；测试临时存档入库。 ##...

### PASS · confirmed inventory intake · root mycelium

- Observed: committed=True ok=True row=1.0面 event_ok=True query_ok=True
- Expected: immediately store 测试入库039 根源菌丝样本 as 1面
- text=确认取下1面根源菌丝样本并入库
- turn_id=turn:000083
- query=## 装备/物品：测试入库039 根源菌丝样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-039` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1面 | | 品质 | live | | 装备槽 | 无 | ### 摘要 确认取下1面根源菌丝样本并入库；测试临时存...

### PASS · confirmed inventory intake · mother spore

- Observed: committed=True ok=True row=0.1捧 event_ok=True query_ok=True
- Expected: immediately store 测试入库040 母孢子树孢子 as 0.1捧
- text=确认收集0.1捧母孢子树孢子并入库
- turn_id=turn:000084
- query=## 装备/物品：测试入库040 母孢子树孢子 | 字段 | 值 | |------|----| | ID | `item:probe-intake-040` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.1捧 | | 品质 | live | | 装备槽 | 无 | ### 摘要 确认收集0.1捧母孢子树孢子并入库；测...

### PASS · confirmed inventory intake · sample bag note

- Observed: committed=True ok=True row=1.0件 event_ok=True query_ok=True
- Expected: immediately store 测试入库041 样品袋记录 as 1件
- text=确认新增1件样品袋记录并入库
- turn_id=turn:000085
- query=## 装备/物品：测试入库041 样品袋记录 | 字段 | 值 | |------|----| | ID | `item:probe-intake-041` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1件 | | 品质 | noted | | 装备槽 | 无 | ### 摘要 确认新增1件样品袋记录并入库；...

### PASS · confirmed inventory intake · footprint cast

- Observed: committed=True ok=True row=1.0件 event_ok=True query_ok=True
- Expected: immediately store 测试入库042 新脚印石膏模 as 1件
- text=确认保存1件新脚印石膏模并入库
- turn_id=turn:000086
- query=## 装备/物品：测试入库042 新脚印石膏模 | 字段 | 值 | |------|----| | ID | `item:probe-intake-042` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1件 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认保存1件新脚印石膏模并入库；...

### PASS · confirmed inventory intake · pottery shard

- Observed: committed=True ok=True row=2.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库043 陌生陶片 as 2片
- text=确认收集2片陌生陶片并入库
- turn_id=turn:000087
- query=## 装备/物品：测试入库043 陌生陶片 | 字段 | 值 | |------|----| | ID | `item:probe-intake-043` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 2片 | | 品质 | old | | 装备槽 | 无 | ### 摘要 确认收集2片陌生陶片并入库；测试临时...

### PASS · confirmed inventory intake · weave rubbing

- Observed: committed=True ok=True row=1.0张 event_ok=True query_ok=True
- Expected: immediately store 测试入库044 编织纹样拓片 as 1张
- text=确认保存1张编织纹样拓片并入库
- turn_id=turn:000088
- query=## 装备/物品：测试入库044 编织纹样拓片 | 字段 | 值 | |------|----| | ID | `item:probe-intake-044` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1张 | | 品质 | clear | | 装备槽 | 无 | ### 摘要 确认保存1张编织纹样拓片并入...

### PASS · confirmed inventory intake · charcoal sample

- Observed: committed=True ok=True row=5.0块 event_ok=True query_ok=True
- Expected: immediately store 测试入库045 焦黑木炭样本 as 5块
- text=确认收集5块焦黑木炭样本并入库
- turn_id=turn:000089
- query=## 装备/物品：测试入库045 焦黑木炭样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-045` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 5块 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认收集5块焦黑木炭样本并入库；测试临时存档...

### PASS · confirmed inventory intake · metal filings

- Observed: committed=True ok=True row=0.05竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库046 金属碎屑 as 0.05竹杯
- text=确认收集0.05竹杯金属碎屑并入库
- turn_id=turn:000090
- query=## 装备/物品：测试入库046 金属碎屑 | 字段 | 值 | |------|----| | ID | `item:probe-intake-046` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.05竹杯 | | 品质 | raw | | 装备槽 | 无 | ### 摘要 确认收集0.05竹杯金属碎屑并入库；测试...

### PASS · confirmed inventory intake · blue mineral sand

- Observed: committed=True ok=True row=0.2竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库047 蓝色矿砂 as 0.2竹杯
- text=确认收集0.2竹杯蓝色矿砂并入库
- turn_id=turn:000091
- query=## 装备/物品：测试入库047 蓝色矿砂 | 字段 | 值 | |------|----| | ID | `item:probe-intake-047` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.2竹杯 | | 品质 | raw | | 装备槽 | 无 | ### 摘要 确认收集0.2竹杯蓝色矿砂并入库；测试临时...

### PASS · confirmed inventory intake · resin drops

- Observed: committed=True ok=True row=7.0滴 event_ok=True query_ok=True
- Expected: immediately store 测试入库048 透明树脂滴 as 7滴
- text=确认收集7滴透明树脂滴并入库
- turn_id=turn:000092
- query=## 装备/物品：测试入库048 透明树脂滴 | 字段 | 值 | |------|----| | ID | `item:probe-intake-048` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 7滴 | | 品质 | sticky | | 装备槽 | 无 | ### 摘要 确认收集7滴透明树脂滴并入库；测试临时存...

### PASS · confirmed inventory intake · animal hair

- Observed: committed=True ok=True row=1.0撮 event_ok=True query_ok=True
- Expected: immediately store 测试入库049 动物毛束 as 1撮
- text=确认保存1撮动物毛束并入库
- turn_id=turn:000093
- query=## 装备/物品：测试入库049 动物毛束 | 字段 | 值 | |------|----| | ID | `item:probe-intake-049` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1撮 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认保存1撮动物毛束并入库；测试临时...

### PASS · confirmed inventory intake · fish scales

- Observed: committed=True ok=True row=6.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库050 鱼鳞样本 as 6片
- text=确认保存6片鱼鳞样本并入库
- turn_id=turn:000094
- query=## 装备/物品：测试入库050 鱼鳞样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-050` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 6片 | | 品质 | dry | | 装备槽 | 无 | ### 摘要 确认保存6片鱼鳞样本并入库；测试临时...

### PASS · confirmed inventory intake · toxin strip

- Observed: committed=True ok=True row=1.0张 event_ok=True query_ok=True
- Expected: immediately store 测试入库051 毒液试纸 as 1张
- text=确认保存1张毒液试纸并入库
- turn_id=turn:000095
- query=## 装备/物品：测试入库051 毒液试纸 | 字段 | 值 | |------|----| | ID | `item:probe-intake-051` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1张 | | 品质 | sealed | | 装备槽 | 无 | ### 摘要 确认保存1张毒液试纸并入库；测...

### PASS · confirmed inventory intake · powder residue

- Observed: committed=True ok=True row=0.02竹杯 event_ok=True query_ok=True
- Expected: immediately store 测试入库052 火药残渣样本 as 0.02竹杯
- text=确认保存0.02竹杯火药残渣样本并入库
- turn_id=turn:000096
- query=## 装备/物品：测试入库052 火药残渣样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-052` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.02竹杯 | | 品质 | sealed | | 装备槽 | 无 | ### 摘要 确认保存0.02竹杯火药残渣样...

### PASS · confirmed inventory intake · paralysis spore

- Observed: committed=True ok=True row=0.1捧 event_ok=True query_ok=True
- Expected: immediately store 测试入库053 麻痹孢子样本 as 0.1捧
- text=确认保存0.1捧麻痹孢子样本并入库
- turn_id=turn:000097
- query=## 装备/物品：测试入库053 麻痹孢子样本 | 字段 | 值 | |------|----| | ID | `item:probe-intake-053` | | 类型 | 物品 | | 分类 | 材料 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 0.1捧 | | 品质 | sealed | | 装备槽 | 无 | ### 摘要 确认保存0.1捧麻痹孢子样本并入库...

### PASS · confirmed inventory intake · black eggshell

- Observed: committed=True ok=True row=1.0片 event_ok=True query_ok=True
- Expected: immediately store 测试入库054 不明黑色卵壳 as 1片
- text=确认保存1片不明黑色卵壳并入库
- turn_id=turn:000098
- query=## 装备/物品：测试入库054 不明黑色卵壳 | 字段 | 值 | |------|----| | ID | `item:probe-intake-054` | | 类型 | 物品 | | 分类 | evidence | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1片 | | 品质 | 未知 | | 装备槽 | 无 | ### 摘要 确认保存1片不明黑色卵壳并入库；测...

### PASS · confirmed inventory intake · watch bell

- Observed: committed=True ok=True row=1.0个 event_ok=True query_ok=True
- Expected: immediately store 测试入库055 警戒哨采样铃 as 1个
- text=确认新增1个警戒哨采样铃并入库
- turn_id=turn:000099
- query=## 装备/物品：测试入库055 警戒哨采样铃 | 字段 | 值 | |------|----| | ID | `item:probe-intake-055` | | 类型 | 物品 | | 分类 | 工具 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 数量 | 1个 | | 品质 | usable | | 装备槽 | 无 | ### 摘要 确认新增1个警戒哨采样铃并入库；测试临...

### PASS · confirmed world/event intake · new smoke ridge

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认发现烟柱高地并记录为新地点
- turn_id=turn:000045
- loc:probe-smoke-ridge=## 地点：测试烟柱高地 | 字段 | 值 | |------|----| | ID | `loc:probe-smoke-ridge` | | 状态 | 活跃 | | 生态 | probe | | 安全等级 | 未知 | | 距家耗时 | 15 分钟 | ### 摘要 测试记录地点：测试烟柱高地 ### 已知资源 - 无 ### 出口/路线 - 无 ### 备注 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new spring

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认发现新的侧泉眼并记录为新地点
- turn_id=turn:000046
- loc:probe-side-spring=## 地点：测试侧泉眼 | 字段 | 值 | |------|----| | ID | `loc:probe-side-spring` | | 状态 | 活跃 | | 生态 | probe | | 安全等级 | 未知 | | 距家耗时 | 15 分钟 | ### 摘要 测试记录地点：测试侧泉眼 ### 已知资源 - 无 ### 出口/路线 - 无 ### 备注 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new cave mouth

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认发现新洞穴入口并记录为新地点
- turn_id=turn:000047
- loc:probe-cave-mouth=## 地点：测试洞穴入口 | 字段 | 值 | |------|----| | ID | `loc:probe-cave-mouth` | | 状态 | 活跃 | | 生态 | probe | | 安全等级 | 未知 | | 距家耗时 | 15 分钟 | ### 摘要 测试记录地点：测试洞穴入口 ### 已知资源 - 无 ### 出口/路线 - 无 ### 备注 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new faction

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认遇见芦苇编织者聚落并登记派系
- turn_id=turn:000048
- faction:probe-reed-weavers=## 测试芦苇编织者 | 字段 | 值 | |------|----| | ID | `faction:probe-reed-weavers` | | 类型 | 阵营 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试芦苇编织者。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new species

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认首次观察到灰鳞人并登记物种
- turn_id=turn:000049
- species:probe-ashscale=## 物种：测试灰鳞人 | 字段 | 值 | |------|----| | ID | `species:probe-ashscale` | | 类型 | 物种 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试灰鳞人。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new envoy

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认遇见芦苇编织者使者并登记人物
- turn_id=turn:000050
- species:probe-reed-person=## 物种：测试芦苇人 | 字段 | 值 | |------|----| | ID | `species:probe-reed-person` | | 类型 | 物种 | | 位置 | 未知 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增物种。 ### 来源 intake_probe
- char:probe-reed-envoy=## 人物/生物：测试芦苇使者 | 字段 | 值 | |------|----| | ID | `char:probe-reed-envoy` | | 类型 | 角色 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 种族 | species:probe-reed-person | | 角色 | envoy | | 态度 | cautious | | 信任 | 0 | | 健康 | ...

### PASS · confirmed world/event intake · new threat

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认夜间哨声来源是一种潜在威胁
- turn_id=turn:000051
- threat:probe-night-whistle=## 测试夜哨威胁 | 字段 | 值 | |------|----| | ID | `threat:probe-night-whistle` | | 类型 | 威胁 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试夜哨威胁。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new project

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认开启陌生文明接触记录项目
- turn_id=turn:000052
- project:probe-civilization-contact=## 测试文明接触记录 | 字段 | 值 | |------|----| | ID | `project:probe-civilization-contact` | | 类型 | 项目 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试文明接触记录。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new reference

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认保存陌生陶片纹样参考
- turn_id=turn:000053
- ref:probe-pottery-pattern=## 资料：测试陶片纹样参考 | 字段 | 值 | |------|----| | ID | `ref:probe-pottery-pattern` | | 类型 | 参考资料 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试陶片纹样参考。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new world setting

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认记录湖边有定期贸易迹象
- turn_id=turn:000054
- setting:probe-lake-trade-sign=## 测试湖边贸易迹象 | 字段 | 值 | |------|----| | ID | `setting:probe-lake-trade-sign` | | 类型 | 大世界设定 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试湖边贸易迹象。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new relationship

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认记录与芦苇编织者的初始关系
- turn_id=turn:000055
- rel:probe-reed-weavers-contact=## 测试芦苇编织者初始关系 | 字段 | 值 | |------|----| | ID | `rel:probe-reed-weavers-contact` | | 类型 | 关系 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试芦苇编织者初始关系。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new faction rumor

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认An提供一个远方盐路文明传闻
- turn_id=turn:000056
- faction:probe-salt-road-rumor=## 测试盐路文明传闻 | 字段 | 值 | |------|----| | ID | `faction:probe-salt-road-rumor` | | 类型 | 阵营 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试盐路文明传闻。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new event reference

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认地震事件需要后续追踪
- turn_id=turn:000057
- ref:probe-quake-event=## 资料：测试地震事件记录 | 字段 | 值 | |------|----| | ID | `ref:probe-quake-event` | | 类型 | 参考资料 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试地震事件记录。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new species track

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认陌生三趾脚印来自未知物种
- turn_id=turn:000058
- species:probe-three-toed=## 物种：测试三趾未知种 | 字段 | 值 | |------|----| | ID | `species:probe-three-toed` | | 类型 | 物种 | | 位置 | loc:home-mycelium-house | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试三趾未知种。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new encounter note

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认陌生商旅经过领地边缘
- turn_id=turn:000059
- ref:probe-caravan-encounter=## 资料：测试商旅遭遇记录 | 字段 | 值 | |------|----| | ID | `ref:probe-caravan-encounter` | | 类型 | 参考资料 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试商旅遭遇记录。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new marker

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认地图上增加蓝砂采样点
- turn_id=turn:000060
- ref:probe-blue-sand-marker=## 资料：测试蓝砂采样点 | 字段 | 值 | |------|----| | ID | `ref:probe-blue-sand-marker` | | 类型 | 参考资料 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试蓝砂采样点。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new cultural artifact

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认编织纹样指向一种新文化
- turn_id=turn:000061
- faction:probe-weave-culture=## 测试编织纹样文化 | 字段 | 值 | |------|----| | ID | `faction:probe-weave-culture` | | 类型 | 阵营 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试编织纹样文化。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · confirmed world/event intake · new fungal incident

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认夏娃报告新的菌丝异常事件
- turn_id=turn:000062
- ref:probe-mycelium-anomaly=## 资料：测试菌丝异常事件 | 字段 | 值 | |------|----| | ID | `ref:probe-mycelium-anomaly` | | 类型 | 参考资料 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试菌丝异常事件。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new trade item

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认商旅展示一种陌生陶币
- turn_id=turn:000063
- ref:probe-clay-coin=## 资料：测试陌生陶币记录 | 字段 | 值 | |------|----| | ID | `ref:probe-clay-coin` | | 类型 | 参考资料 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试陌生陶币记录。 ### 来源 intake_probe

### PASS · confirmed world/event intake · new hazard note

- Observed: committed=True ok=True event_ok=True entities_ok=True query_ok=True
- Expected: event and new fact entities are immediately persisted and queryable
- text=确认新洞穴入口有塌方风险
- turn_id=turn:000064
- threat:probe-cave-collapse=## 测试洞穴塌方风险 | 字段 | 值 | |------|----| | ID | `threat:probe-cave-collapse` | | 类型 | 威胁 | | 状态 | 活跃 | | 可见性 | 已知 | ### 摘要 入库测试新增事实：测试洞穴塌方风险。 ### 细节 - 置信度: 已确认 - 来源: intake_probe

### PASS · intake guardrail · output event without upsert

- Observed: committed=False ok=False blocked=True no_persist=True
- Expected: should block claimed inventory output without matching upsert_entities
- error=ValueError: State audit blocked turn delta:
- delta text/event mentions gained or stored output, but no inventory/entity upsert is present.

### PASS · intake guardrail · non numeric quantity

- Observed: committed=False ok=False blocked=True no_persist=True
- Expected: should block non-numeric item.quantity in exact inventory upsert
- error=ValueError: Invalid turn delta:
- delta: $.upsert_entities[0].item.quantity: must be number
- $.upsert_entities[0].item.quantity: must be number

### PASS · intake guardrail · item without item payload

- Observed: committed=False ok=False blocked=True no_persist=True
- Expected: should block item entity without item payload
- error=ValueError: Invalid turn delta:
- delta: $.upsert_entities[0].item: recommended and required by engine for item/equipment details
- $.upsert_entities[0].item: recommended and required by engine for item/equipment details

### ISSUE · intake guardrail · negative gathered quantity

- Observed: committed=True ok=False blocked=True no_persist=False
- Expected: should block negative gathered quantity before writing
- Issue: `intake_guardrail_reported_after_write`
- check_errors=item:probe-bad-negative 负数采集物品 has negative quantity -1.0

### ISSUE · intake guardrail · zero gathered quantity

- Observed: committed=True ok=True blocked=False no_persist=False
- Expected: should block zero-quantity intake when event claims new stock
- Issue: `intake_guardrail_missing`

### ISSUE · intake guardrail · output id mismatch

- Observed: committed=True ok=True blocked=False no_persist=False
- Expected: should block mismatch between event output_item_id and upsert entity id
- Issue: `intake_guardrail_missing`

### ISSUE · intake guardrail · missing location on item

- Observed: committed=True ok=True blocked=False no_persist=False
- Expected: should block newly gathered inventory without location_id or owner_id
- Issue: `intake_guardrail_missing`

### PASS · intake guardrail · both owner and location

- Observed: committed=False ok=False blocked=True no_persist=True
- Expected: should block active entity with both owner_id and location_id
- error=ValueError: Invalid turn delta:
- delta: $.upsert_entities[0]: active entity cannot set both owner_id and location_id
- $.upsert_entities[0]: active entity cannot set both owner_id and location_id

### PASS · intake guardrail · unknown location ref

- Observed: committed=False ok=False blocked=True no_persist=True
- Expected: should block newly gathered inventory with missing location ref
- error=ValueError: Invalid turn delta:
- delta: $.upsert_entities[0].location_id: missing entity loc:does-not-exist
- $.upsert_entities[0].location_id: missing entity loc:does-not-exist

### PASS · intake guardrail · duplicate upsert ids

- Observed: committed=False ok=False blocked=True no_persist=True
- Expected: should block duplicate upsert entity ids
- error=ValueError: Invalid turn delta:
- delta: $.upsert_entities[1].id: duplicate entity id item:probe-bad-duplicate
- $.upsert_entities[1].id: duplicate entity id item:probe-bad-duplicate

### ISSUE · intake guardrail · fuzzy high risk quantity

- Observed: committed=True ok=True blocked=False no_persist=False
- Expected: should block high-risk inventory intake without exact quantity
- Issue: `intake_guardrail_missing`
- state_audit=HIGH_RISK_ITEM_METADATA_INCOMPLETE

### ISSUE · intake guardrail · civilization event without entity

- Observed: committed=True ok=True blocked=False no_persist=True
- Expected: should block confirmed new civilization event without structured entity/reference
- Issue: `intake_guardrail_missing`

### ISSUE · intake guardrail · location entity without location payload

- Observed: committed=True ok=True blocked=False no_persist=False
- Expected: should block location entity without location payload
- Issue: `intake_guardrail_missing`
