# Explore Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-explore-probe-2026-07-01.md`

统计：PASS=62 ISSUE=24 TOTAL=86

## 结论

结构化 explore 基本保守可用：已知目标可写 explore event，不直接创建事实、实体或 clock tick。失败集中在自然语言 target resolution、未知线索提取和边界动作误判。

这是引擎和剧情包共同问题：引擎 target ranking 不够，剧情包别名/候选实体也不足。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `explore_boundary_wrong_action` | 6 | 引擎 | `检查/搜索/侦查` 与 query/gather/routine/combat/social 交叠，边界规则不稳定。 | 根据动词对象和是否 collect/talk/fight 细分 explore vs gather/query/routine。 |
| `natural_explore_wrong_target` | 5 | 引擎 + 剧情包 | 目标解析到无关 rule/world_setting/reference，如森林注意来源解析成探索流程规则。 | target resolver 增加类型偏好、alias、上下文权重和 exact phrase ranking。 |
| `natural_explore_target_unresolved` | 3 | 引擎 + 内容 | `菌丝复合屋屋内异常`、`围墙外侧` 等场景部位没有实体/别名。 | 支持 location subarea/unknown lead；内容补常见部位 alias。 |
| `natural_unknown_lead_not_extracted` | 3 | 引擎 | 自然语言没有把未知线索保存为 `unknown_lead=True`。 | 加未知线索模式：异常、痕迹、来源、不明、远距观察。 |
| `explore_query_misrouted` | 2 | 引擎 | 只读观察/情况被 action/query 错路由。 | read-only observe query 和 exploratory observe action 分开。 |
| 其他单例 | 5 | 引擎 + 内容 | 错 target、composite plan 错、explore/gather/query/routine 误判。 | 用 structured explore intent + gold set。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `文明传闻` clock | target=`rule:external-trace-classification` | `clock:civilization-rumor` | 内容别名/target ranking 错，把规则匹配排在 clock 前。 |
| `检查菌丝复合屋屋内有没有异常` | target not found | known target 或 unknown lead | 场景部位不是 queryable/explorable target。 |
| `远距观察湖边聚落` | query | explore | 观察动作被 read-only query 吞掉。 |
| `调查森林注意来源` | target=`world:exploration-procedure` | forest attention clock/threat/source | 目标 ranking 偏向世界规则。 |
| `检查石英采掘场工具痕` | gather | explore | `采掘场` 命中资源/采集语义，忽略“工具痕”观察。 |

## 是否是剧情包或存档问题

有明显内容问题：

- `文明传闻` 应 alias 到 `clock:civilization-rumor` 或对应 project/reference，而不是 rule。
- 家/围墙/菌丝屋/门外/洞口/采掘场工具痕等 subarea 需要 location part 或 reference。
- 湖边聚落、森林注意、基地防线这类调查目标需要可见 clue/reference。

但自然语言无法生成 `unknown_lead=True` 是引擎问题。

## 修复建议

1. explore intent 支持：
   - `target_id|target_query`
   - `target_kind=known|unknown_lead|subarea|palette_candidate`
   - `location_id`, `approach`, `risk_posture`, `touch=false`, `collect=false`
2. target resolver ranking：clock/project/reference/threat/location 的权重按 query text 和 expected target kind 调整。
3. 未知线索自然语言触发：`异常/痕迹/来源/不明/可疑/远距观察/有没有`。
4. 内容侧补 aliases/subareas：菌丝复合屋屋内、围墙外侧、门外、文明传闻、森林注意来源。
5. 对 `检查鱼笼但不收`、`寻找材料` 这类边界，明确 `collect=false` 才 explore/routine，`collect=true` 才 gather。

## 回归验收

- `文明传闻` 不再解析到 rule。
- `检查屋内异常` 能作为 unknown lead 或 house subarea explore。
- `远距观察湖边聚落` 是 explore，不是 query。
- explore 不直接新增事实或 clock tick，除非 delta 明确保存 discovery。
