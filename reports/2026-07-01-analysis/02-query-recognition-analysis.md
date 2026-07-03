# Query Recognition Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-query-recognition-probe-2026-07-01.md`

统计：PASS=100 ISSUE=59 TOTAL=159

## 结论

这份报告不是单纯“查不到数据”。它分成三类：

- 查询路由错误：场景/状态查询被当成 entity query 或 action。
- 查询解析/输出不足：路由到 query 后，实体/聚合事实没有查出来。
- 内容/存档建模缺口：菌丝单位、箭矢总量、紧急事项、基地压力这类聚合事实没有稳定的 queryable 表示。

主责任仍是引擎查询层，但剧情包/存档需要补 aliases、aggregate cards 和项目/clock 索引。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `right_mode_but_wrong_proceed_state` | 22 | 引擎 + 内容 | 路由到了 query:entity 但实体/聚合对象未找到，或应走 scene query 却进 entity query。 | 给 scene/status query 单独入口；增强 entity resolver 的别名、聚合和模糊匹配。 |
| `query_misread_as_action` | 12 | 引擎 | `检查/哪些/多久/压力` 同时像动作和查询，动作关键词抢先。 | 只读查询检测先于动作：数量、状态、进度、风险、可用列表、多久没做等应锁定 query。 |
| `query_entity_not_found` | 10 | 引擎 + 存档/内容 | 路由可行但 query 输出找不到物品/角色/菌丝聚合事实。 | 建立 aggregate query index；补 `aliases`、cards、facts；让 query 能按 category/tag 汇总。 |
| `wrong_action_or_query_kind` | 10 | 引擎 | `我现在在哪/当前局面/身边有什么` 被当 entity query，而不是 scene query。 | 扩展 scene/status query 词表：位置、局面、身边、时间天气、出口、当前风险。 |
| `query_route_gap` | 5 | 引擎 | 查询语义明确，但没有统一输出路径，记录为 route gap。 | 增加 scene summary、urgent issues、base upkeep、home location 等 query renderer。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `我现在在哪` | `query:entity can_proceed=False` | `query:scene` | 引擎 scene query 词表太窄，只识别 `我在哪`，没有泛化 `我现在在哪`。 |
| `所有箭矢数量` | `query:entity can_proceed=False` | `query:entity` | 存档有多种弹药，但 query 层缺 category 聚合和别名。 |
| `春末干旱进度到几格了` | `action:travel` | `query:entity` | clock/progress query 被 action 词抢走。 |
| `菌丝人总数是多少` | `query:entity can_proceed=False` | `query:entity` | 菌丝单位数量更像聚合事实，不是单一 entity。 |
| `现在最紧急的事情是什么` | query/route gap | useful output | 缺 scene priority/urgent issue renderer。 |

## 是否是剧情包或存档问题

部分是。

内容/存档需要补：

- 菌丝人/腐工蕈/锐孢蕈/思菌蕈的聚合数量和别名。
- 所有箭矢、特殊箭矢、可用弹药、厨房存粮、能吃的等分类查询索引。
- clock/project alias：`春末干旱`、`基地维护压力`、`十六畦浇水`。
- `当前最紧急事项`、`当前局面`、`今天优先事项` 这类 scene summary card。

但“查询被动作抢走”是引擎问题。

## 修复建议

1. 新增 `query_kind=scene|entity|aggregate|clock|project|inventory_category`。
2. 只读 query 检测优先处理 `多少/数量/还剩/进度/状态/情况/有哪些/多久/能不能/会不会`。
3. entity query 不只查名称，还要支持 category/tag/properties，如 ammo、food、mycelium_unit。
4. 为剧情包补 aggregate cards：`菌丝单位总览`、`弹药库存总览`、`食物库存总览`、`当前项目与压力`。
5. query output 要在未找到单一 entity 时降级为聚合查询，而不是直接 `can_proceed=False`。

## 回归验收

- `我现在在哪`、`现在是什么情况`、`附近能去哪些地方` 返回 scene query。
- `所有箭矢数量`、`特殊箭矢分别还剩几支` 返回弹药聚合列表。
- `菌丝人总数是多少` 返回总数和分项。
- `春末干旱进度到几格了` 返回 clock 状态，不生成 travel/routine action。
