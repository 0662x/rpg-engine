# Rest Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-rest-probe-2026-07-01.md`

统计：PASS=23 ISSUE=28 TOTAL=51

## 结论

结构化 rest 全部通过，说明 `preview_action('rest', until=...)` 和 commit 机制没坏。问题在自然语言 `infer_rest_until` 和 rest 边界意图：同日休息/短休被塌缩成次日清晨，否定、问题、社交、战斗守夜被 rest 抢走。

这是引擎问题，基本不是剧情包/存档问题。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `rest_boundary_commit_ready` | 7 | 引擎 | 否定、复合、守夜观察、喝水后休息等边界句被生成 commit-ready rest。 | 否定/问题/复合动作/武器守夜优先 clarify 或其他 action。 |
| `natural_short_rest_collapsed_to_overnight` | 5 | 引擎 | `一小时/十分钟/一会儿/半小时/10 minutes` 被 normalize 成 overnight morning。 | 支持 duration parser，生成 same-day short_rest。 |
| `natural_rest_time_collapsed_to_morning` | 4 | 引擎 | `中午/下午/傍晚/evening` 从自然语言进入 `until=morning` 或 overnight。 | `infer_rest_until` 映射同日 time block。 |
| `natural_rest_misread_as_query` | 3 | 引擎 | `歇一会/闭目养神十分钟` 没被休息词表覆盖。 | 扩展短休词表。 |
| `rest_boundary_misrouted_to_rest` | 3 | 引擎 | 社交问别人休息、测试句等仍 route 到 rest。 | 社交/否定/假设检测先于 rest。 |
| `rest_query_misrouted` | 3 | 引擎 | `睡觉会不会出事/现在能不能睡觉/上次休息到什么时候` 是 query，却成 rest ready。 | 问题句只读 query 或 risk check，不生成 rest delta。 |
| `natural_rest_misread_as_travel` | 2 | 引擎 | `等到傍晚/等到夜里` 的 `到` 被 travel 抢走。 | `等到 + 时间` 优先 wait/rest，而不是 travel。 |
| `natural_rest_wrong_action` | 1 | 引擎 | `打个盹` 被 combat 误判，可能因为 `打` 被战斗词命中。 | 对固定短语 `打盹` 特判为 rest。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `休息到中午` | 第29天清晨 | 同日中午 | 自然语言时间映射错误。 |
| `休息十分钟` | 第29天清晨 | 同日短休 | duration 未解析。 |
| `等到傍晚` | travel clarify | rest/wait same-day | `到` 触发 travel。 |
| `先不要休息` | rest ready | clarify/no-op | 否定检测没有先于 rest keyword。 |
| `拿弩守夜` | rest ready | combat/watch clarify | 守夜既可 rest 也可警戒，武器上下文应改变 action。 |
| `睡觉会不会出事` | rest ready | query/risk check | 问题句未锁只读。 |

## 是否是剧情包或存档问题

基本不是。当前地点、时间、clock tick 都在结构化 rest 中可用，失败不来自存档。

唯一需要内容配合的是时间块枚举/标签要统一：`中午/下午/傍晚/晚上/night/一小时` 应和存档 meta 的 period/time_block 有稳定映射。

## 修复建议

1. `infer_rest_until` 拆分为：
   - `mode=overnight|same_day_wait|short_rest|watch|query`
   - `until`, `duration_minutes`, `actor/target`
2. 解析顺序：
   - 否定/假设/测试句 -> clarify/no-op
   - 问题句 -> query
   - NPC + rest -> social
   - 武器/观察/守夜 -> combat/watch
   - `等到 + 时间` -> same_day_wait
   - duration phrase -> short_rest
3. validator 不允许 short_rest 变成 next morning。
4. 添加短语白名单：`打盹/小睡/歇一会/闭目养神/休息十分钟/wait 10 minutes`。

## 回归验收

- `休息到中午/下午/傍晚` 保持同日。
- `休息十分钟/小睡半小时/wait 10 minutes` 不推进到次日清晨。
- `先不要休息`、`睡觉会不会出事` 不生成 commit-ready rest。
- `拿弩守夜` 不走 rest ready。
