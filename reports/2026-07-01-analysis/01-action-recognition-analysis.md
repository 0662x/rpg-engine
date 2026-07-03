# Action Recognition Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-action-recognition-probe-2026-07-01.md`

统计：PASS=79 ISSUE=59 TOTAL=138

## 结论

这份报告主要暴露的是引擎意图路由问题，不是存档坏了。失败集中在“玩家自然语言动作”被当成查询、维护、休息、采集、探索或错误动作。剧情包/存档只在少量 travel 目标无法解析时参与归因。

核心根因是 `intent_router` 里的关键词优先级和可玩动作推断还太粗：`检查` 偏向 explore/query，`问/让/请/叫` 没稳定进入 social，`守夜/休息` 容易压过 combat/social，`造/扩建/编/试配` 对 craft 覆盖不完整。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `action_misread_as_query` | 31 | 引擎 | 查询关键词和实体命中优先于动作语义；`查看/检查/让/请/用/打磨/编` 等没有进入明确动作槽位。 | 在路由前增加 action-first 规则：社交祈使句、制作动词、战斗准备、采集动词、旅行动词优先于实体 query。 |
| `wrong_action_or_query_kind` | 23 | 引擎 | 同一句话含多个动作暗示时没有稳定优先级，如 `问南瓜要不要休息` 被 rest，`让An帮忙采硫磺` 被 gather。 | 增加动作优先级矩阵：NPC 祈使句优先 social；武器/戒备优先 combat；维护/检查基地优先 routine；制作动词优先 craft。 |
| `right_mode_but_wrong_proceed_state` | 5 | 引擎 + 内容/存档 | 识别到 travel/combat 但目标或距离/地点未解析，导致 proceed 状态不符。 | 对 location alias、当前可达地点、combat target 保留已识别槽位；无法解析时返回 clarify，但不要丢已解析字段。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `检查基地防线` | `action:explore` | `action:routine` | 引擎把“检查”默认成 explore，没有识别基地维护/巡检语义。 |
| `让夏娃汇报菌丝单位` | `query:entity` | `action:social` | NPC 祈使句被当实体查询；社交 parser 没有把 `让/请/叫 + NPC + 动词` 作为 social。 |
| `拿弩守夜` | `action:rest` | `action:combat` clarify | `守夜` 被 rest keyword 抢走，武器/警戒语义没有提升到 combat/watch。 |
| `造水渠` / `扩建仓库` | `query:entity` | `action:craft` | craft 动词表缺 `造/扩建/搭/编/腌/试配` 等中文常用词。 |
| `回家` / `进地下` | `query:entity` | `action:travel` | 短旅行词和地点别名没有稳定映射到 travel。 |

## 是否是剧情包或存档问题

大部分不是。只要输入已经命中可见实体却被错误路由，就是引擎问题。

可能涉及内容/存档的点：

- `去I室隔离区`、`去西区扩田边看看`、`走到菌丝通道入口` 等 proceed state 错误，可能是地点别名、可见性或路线数据不全。
- NPC 群体名如 `菌丝人`、`An一家` 如果不能解析成可交互 character/group，需要剧情包补 alias 或 group entity。

## 修复建议

1. 在 `intent_router` 加一个自然语言 gold set，覆盖本报告 59 个 issue 文本。
2. 建立 `route_intent -> structured intent` 层，至少输出 `action`, `target/npc/destination`, `topic`, `materials`, `weapon/ammo`, `duration`, `confidence`。
3. 调整优先级：否定/假设和只读查询先行；NPC 祈使句优先 social；武器/戒备优先 combat；制作动词优先 craft；明确移动词优先 travel。
4. 对识别到 action 但槽位不全的情况，返回同 action 的 `clarify/needs_confirmation`，不要退回 query。
5. 内容侧补充短别名：`家/地表/地下/I室/旧小屋/材料仓库/菌丝通道入口/西区扩田边`。

## 回归验收

- `找南瓜聊聊`、`让夏娃汇报菌丝单位`、`请小的继续教我石板符号` 必须是 social。
- `拿弩守夜`、`装填琥珀麻箭戒备` 必须是 combat clarify。
- `造水渠`、`扩建仓库`、`用麻纤维编一段绳子` 必须是 craft clarify。
- `回家`、`进地下`、`上到地表` 必须是 travel 或 travel clarify，不能是 query。
