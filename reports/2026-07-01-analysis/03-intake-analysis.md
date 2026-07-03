# Intake Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-intake-probe-2026-07-01.md`

统计：PASS=121 ISSUE=21 TOTAL=142

## 结论

明确结构化入库是可靠的：55/55 confirmed inventory intake 通过，20/20 confirmed world/event intake 通过。也就是说数据库写入、显式 `upsert_entities`、事件和立即查询链路基本正常。

真正的问题在两端：自然语言入库/发现没有稳定路由，坏 delta 的提交前 guardrail 不够强。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `natural_intake_misread_as_query` | 9 | 引擎 | `收集/记录/观察/发现/问到传闻` 等输入被当只读 query，没有进入 gather/explore/social fact intake。 | 给 intake/discovery 建立自然语言规则，至少路由到 gather/explore/social `needs_confirmation`。 |
| `natural_intake_route_gap` | 5 | 引擎 | 资源搜索、取水、发现新商队/新物种等被 route 到 combat/travel/explore blocked，未形成明确入库计划。 | 引入 `intake_plan` 或 composite：travel/search/gather/discovery，保存前要求结构化输出。 |
| `intake_guardrail_missing` | 6 | 引擎校验 | 零数量、输出 id mismatch、缺 location/owner、高风险 fuzzy、新文明事件缺实体、location 缺 payload 仍可提交。 | 这些规则前移到 delta validator/state audit blocker，必须 pre-commit 拦截。 |
| `intake_guardrail_reported_after_write` | 1 | 引擎校验 | 负数采集能写入，之后才被检测。 | unit of work 中先跑 validation，再写入；失败必须回滚。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `collect hemp fiber` 类 | `query:entity` | gather confirmation | 引擎把已有实体命中当查询，忽略“收集”动作。 |
| `record new tribe` | `query:entity` | discovery intake | 新事实记录没有专门 action/slot。 |
| `fill water bottle` | `action:combat` | gather/intake clarify | 关键词误判，且缺“容器+资源”模式。 |
| negative gathered quantity | committed=True, no_persist=False | pre-commit block | guardrail 在写后发现，事务边界不正确。 |
| civilization event without entity | committed=True | block | 事件声称发现文明，但没有结构化 entity/reference。 |

## 是否是剧情包或存档问题

confirmed intake 全过，说明存档结构能承载显式入库。自然语言失败主要是引擎。

少量内容/存档相关：

- 新文明、新物种、新地点需要明确 `save_as` 模式和 discovery candidate 类型。
- 高风险物品需要在存档里带 `inventory_reliability/source/confidence/location`，否则 fuzzy/approx intake 不应自动入库。

## 修复建议

1. 增加 `discovery/intake` 语义层：`kind=item_intake|world_fact|location|faction|species|event|reference`。
2. gather 预览默认不保存空产出；必须要求 `id/name/category/quantity/unit/location/source`。
3. 对 discovery 保存要求 `event + entity/reference/fact` 成对出现。
4. pre-commit blocker 覆盖：负数、零数量、output id mismatch、缺 owner/location、location entity 缺 location payload、高风险 fuzzy。
5. 对写入失败统一 rollback，禁止“写了再报错”。

## 回归验收

- 自然语言 `记录一个新部族传闻` 不应是 query，应是 discovery/social fact intake confirmation。
- `收集麻纤维` 不应是 query，应是 gather/intake confirmation。
- 坏 delta 不得留下任何 entity/event/turn。
- 高风险库存没有 exact quantity/source/confidence/location 时不能自动入库或消费。
