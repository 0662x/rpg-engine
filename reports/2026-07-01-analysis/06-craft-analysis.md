# Craft Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-craft-probe-2026-07-01.md`

统计：PASS=35 ISSUE=42 TOTAL=77

## 结论

craft 的问题比 combat 更靠近“事务契约”：自然语言制作经常识别不到 target/material/time/recipe；更危险的是部分结构化 craft 已经 `ready` 并能 commit，但没有扣材料、没有产物、没有项目更新。

主归因是引擎 resolver/delta builder 和自然语言槽位抽取；剧情包需要补 recipe alias 和 recipe target 设计。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `natural_craft_misread_as_query` | 12 | 引擎 | `造/扩建/编/腌/配/磨/封/搭` 等 craft 动词没稳定进入 craft。 | 扩展 craft 词表；制作动词优先 action:craft clarify。 |
| `natural_craft_options_not_extracted` | 5 | 引擎 | 句子里有 `材料...耗时...`，但 options 仍缺 target/materials/time_cost。 | craft slot parser 解析 output/materials/time/project/recipe。 |
| `natural_craft_known_recipe_not_matched` | 4 | 引擎 + 剧情包 | 已知配方的自然语言别名无法匹配，如火药箭校准、四系箭、愈疮木箭杆。 | recipe alias 表 + target/output 规范化。 |
| `natural_craft_query_misrouted` | 4 | 引擎 | 进度/材料问题被当 craft action，而应是 read-only query。 | `需要什么材料/进度/有哪些项目` 先进入 query。 |
| `craft_ready_without_material_delta` | 3 | 引擎契约 | `material_consumption_required=true` 但 `upsert_entities=[]` 仍 ready/commit。 | ready 前强制 material/output/project delta；否则 needs_confirmation。 |
| `craft_recipe_missing` / `craft_recipe_target_blocked` / `craft_wrong_recipe_match` | 7 | 引擎 + 剧情包 | recipe 和成品实体边界混乱，别名可错配到无关 recipe。 | 分离 recipe、project、output item；recipe match 要按 target+materials+project 打分。 |
| `natural_craft_wrong_action` / `natural_craft_misread_as_routine` | 5 | 引擎 | 打磨、检查维护、喂食等被 combat/routine 吃掉。 | craft/routine/combat 边界规则和 test gold set。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| powder arrow calibration full inputs | committed=True, upsert_count=0, quantities unchanged | ready craft 必须扣材料或拒绝保存 | 引擎 delta builder 没生成材料/产物状态变化。 |
| toxic bolt assembly target existing ammo | recipe 错配到 `recipe:curewood-heavy-shafts` | `recipe:thorn-bolt-assembly` | 配方匹配排序和别名不可靠。 |
| `用麻纤维做绳子，材料麻纤维，耗时20分钟` | target/material/time 都未抽出 | 接近 ready 或明确缺 recipe | 自然语言槽位抽取缺失。 |
| `造水渠` / `扩建仓库` | query | craft/project action | craft 动词表和 project action 边界不足。 |
| `火药箭校准需要什么材料` | craft needs_confirmation | read-only query | 查询语义没有优先于制作动作。 |

## 是否是剧情包或存档问题

部分是。

剧情包/内容需要补：

- recipe aliases：火药箭校准、渊刺藤箭、四系箭、愈疮木箭杆、鱼笼复位、竹杯修补、药糊等。
- recipe output 必须是明确 item/equipment/project update，不能只指向 recipe 本身。
- 配方材料的所在地、可用性和消耗规则应结构化。

引擎必须保证：缺材料扣减/产物/project update 时不能 `ready_to_save=True`。

## 修复建议

1. craft parser 输出：
   - `output`, `project`, `recipe`, `materials[{id/query, quantity, consume}]`, `tools`, `time_cost`, `location`, `expected_output`, `failure_cost`。
2. `build_craft_delta` 如果 `material_consumption_required`：
   - 必须生成材料数量变化或 `no_material_consumption=true`。
   - 如果需要产物，必须生成 output upsert 或 project update。
3. `validate_craft_delta` 把“没有 upsert/project/material delta”从 warning 升级为 error。
4. 配方匹配按 target/output 优先，材料次之；recipe entity 不能直接作为成品 target。
5. 查询优先：`进度/需要什么材料/有哪些制作项目` 走 query。

## 回归验收

- ready craft 不允许空材料/空产物提交。
- 火药箭校准、渊刺藤箭装配、愈疮木箭杆自然语言能匹配正确 recipe 或给出具体缺项。
- `用麻纤维做绳子，材料麻纤维，耗时20分钟` 至少抽出 target/material/time。
- craft 查询不生成可保存 craft action。
