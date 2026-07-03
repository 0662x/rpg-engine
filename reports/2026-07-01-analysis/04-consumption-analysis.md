# Consumption Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-consumption-probe-2026-07-01.md`

统计：PASS=43 ISSUE=60 TOTAL=103

## 结论

这是最重要的一份安全报告。结构化 combat 自动扣弹药能通过，但自然语言消耗、普通物品扣减、metadata 保留、stale write 和 fuzzy quantity 都有缺口。

主归因是引擎缺一等 `consumption/spend` 动作和一等库存数量策略。剧情包/存档也有责任：部分库存用文本/fuzzy 数量表达，缺少统一可扣减结构。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `natural_consumption_misread_as_query` | 20 | 引擎 | `吃/喝/用/消耗/季节调味/拆解` 等被已有实体查询吞掉。 | 新增 consumption route，消耗动词优先于 query；输出 item_id、amount、unit、mode。 |
| `natural_consumption_not_ready` | 12 | 引擎 | 部分命中 craft/combat，但 resolver 只要求确认，没有形成扣减 delta。 | craft/combat/routine 中携带 material/ammo consumption slot；不完整则 `needs_confirmation`。 |
| `natural_consumption_committed_without_decrement` | 2 | 引擎 guardrail | routine 事件可提交，但没有扣减对应库存。 | 只要 narrative/event 提到消耗或喂食，必须有 material/item delta 或显式 `no_inventory_change`。 |
| guardrail 变体 | 24+ | 引擎校验 | 单位错、负数、null、payload 前后数量不一致、item mismatch、metadata 丢失、状态/可见性/品质/名称突变都能提交。 | 把 consumption validator 做成强约束，禁止 pure decrement 修改非数量字段。 |
| stale write | 1 | 引擎 + 调用契约 | 第二次消耗没有 `expected_turn_id` 仍覆盖较新数量。 | 所有库存写入要求 expected turn/revision guard。 |
| fuzzy quantity gap | 跨多项 | 引擎 + 存档 | `quantity` 只能数值，fuzzy 存在 details 文本，不能可靠扣减或查询。 | 实现 `quantity_strategy=exact|fuzzy|needs_audit`。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `吃空心菜` | `query:entity`, before=13 after=13 | 13->12 或清晰阻断 | 引擎把消耗动作当库存查询。 |
| `喂T2母猫鱼` | routine committed, no decrement | 扣鱼或阻断 | routine 缺 consumption guardrail。 |
| `use black powder in fuse test` | maintenance blocked | 扣黑火药或阻断 | “测试”进入 maintenance，未保留游戏内消耗语义。 |
| unit mismatch | committed, unit 变 `支` | block | pure decrement 不应改单位。 |
| minimal upsert | owner/location/properties 丢失 | preserve metadata | upsert merge 语义错误，数量更新覆盖了完整 item payload。 |
| stale consumption | stale_committed=True | block | 缺 expected turn/revision guard。 |

## 是否是剧情包或存档问题

部分是，但不是主要原因。

存档/内容问题：

- 普通食物、水、材料可能使用 fuzzy 文本，当前引擎无法统一消费。
- 高风险资源如火药、毒箭、特殊弹药需要 exact quantity 和 provenance。
- 部分物品缺完整 source/confidence/location，导致高风险消费无法安全自动化。

引擎问题：

- 没有 `consume/spend/use` action。
- 没有区分 low-risk fuzzy 与 high-risk exact。
- 没有强制 metadata-preserving decrement。

## 修复建议

1. 增加 `consumption` action，支持 `eat|drink|use_material|feed|fire_ammo|disassemble|season|cook_use`。
2. 实现一等数量策略：
   - `exact`: numeric + unit + source + confidence + location，适用于弹药、毒物、火药、稀有材料。
   - `fuzzy`: band + optional range，适用于低风险普通库存。
   - `needs_audit`: 存在但不可自动花费。
3. 对 pure decrement 强制 preserve：name/category/unit/quality/status/visibility/owner/location/properties/durability/equipped_slot 不可被 minimal upsert 清空。
4. consumption event payload 必须与 upsert 对齐：before/current、after、consumed_item_id、consumed_quantity、unit。
5. 所有库存写入必须带 `expected_turn_id` 或 item revision。

## 回归验收

- `吃一株空心菜` 会扣减或要求确认，不会变 query。
- `喂T2母猫鱼` 若鱼为 0，应阻断，不能提交 no-op routine。
- `用黑火药试引信` 必须按高风险 exact 扣减或阻断。
- 单位/负数/null/payload mismatch/stale write 全部 pre-commit 阻断。
- minimal quantity upsert 不丢 owner/location/properties。
