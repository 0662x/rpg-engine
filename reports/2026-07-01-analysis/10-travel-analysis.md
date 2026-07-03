# Travel Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-travel-probe-2026-07-01.md`

统计：PASS=75 ISSUE=15 TOTAL=90

## 结论

travel 整体比其他 action 稳：结构化地点和多段路线大多通过。问题集中在三类：

- 自然语言短目的地被当查询。
- 缺结构化 route 的地点仍能以 0 分钟提交。
- retired/same-location 等不该写 movement turn 的情况仍能 commit。

这是“剧情包路线数据”和“引擎 travel guardrail”共同问题。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `natural_travel_misread_as_query` | 6 | 引擎 + 内容别名 | `走向L3/回家/回空地/进地下/回六边形菌丝复合屋` 被 query 词或实体命中抢走。 | 明确移动词优先 travel；补地点短别名。 |
| `travel_unrouted_zero_time` | 3 | 剧情包 + 引擎 | `loc:home-old-hut` 可解析但没有 route，engine 用估算 0 分钟仍 ready/commit。 | 剧情包补 route；engine 对不同地点 0 分钟/无 route 设为 needs_confirmation。 |
| `travel_retired_location_committed` | 2 | 存档/内容 + 引擎 | retired historical location 仍被普通目的地接受。 | resolver 过滤 retired/archived/historical location；存档清理 status/visibility。 |
| `natural_travel_destination_unresolved` | 1 | 内容别名 + 引擎 | `上到地表` 没映射到当前可达地表地点。 | 增加 context-aware alias：地表、地下、家、空地。 |
| `natural_travel_wrong_action` | 1 | 引擎/测试口径 | `去石英采掘场` 被 composite plan，因为目的地兼现场目标。 | 单纯 `去X` 默认 travel；带 `看看/采/调查` 才 composite。 |
| `travel_meta_location_not_updated` | 1 | 引擎 + 内容别名 | `从菌丝屋出门到领地` 解析成当前地点，写了无移动 turn。 | destination resolver 不应把“出门到领地”解析为 current；同地点 no-op 不写 turn。 |
| `travel_same_location_committed` | 1 | 引擎 guardrail | same-location travel 仍写 changed turn。 | same-location 返回 clarify/no-op，不 commit。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| structured to old hut/material warehouse | estimated_minutes=0, route_ids=[] committed | route/time confirmed or block | 旧小屋缺 route + 引擎允许无 route 0 分钟提交。 |
| `回家` / `回空地` | query | travel | 短移动词被 query/entity 抢走，别名不足。 |
| `上到地表` | travel clarify destination unresolved | travel to surface/clearing | context-aware 地表 alias 缺失。 |
| `从菌丝屋出门到领地` | destination=current, location 不变 | loc:home-clearing | 目的地解析错误 + same-location 写入。 |
| retired treehouse/original clearing | committed | block | retired historical location 没被过滤。 |

## 是否是剧情包或存档问题

明确有。

剧情包/存档需要：

- 补 `loc:home-mycelium-house <-> loc:home-old-hut` 路线和耗时，或声明不可直达。
- 给 `家/空地/领地/地表/地下/旧小屋/材料仓库/六边形菌丝复合屋/L3` 补别名。
- retired/historical location 设置为不可普通 travel，或从可见候选中移除。

引擎仍必须防御内容缺口：无 route/0 分钟/同地点/retired 都不能直接 commit。

## 修复建议

1. `resolve_travel` 中：
   - current != destination 且 route is None 且 estimated_minutes <= 0 -> `needs_confirmation`。
   - same-location -> no-op/clarify，不写 turn。
   - retired/archived/historical location -> blocked。
2. location resolver 增加 context-aware aliases 和可达地点优先级。
3. 单纯 `去X/回X/进X/上到X/走向X` 默认 travel；只有带后续动作才 composite。
4. content route audit 增加缺边检查：当前常用地点之间必须有 route 或明确 unreachable。

## 回归验收

- `回家`、`回空地`、`进地下`、`上到地表` 不能是 query。
- 无 route 不再 0 分钟 commit。
- retired 地点不能 travel。
- 同地点 travel 不写 changed turn。
- 多段 travel chain 现有 pass 不回退。
