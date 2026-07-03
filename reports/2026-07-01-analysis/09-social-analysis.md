# Social Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-social-probe-2026-07-01.md`

统计：PASS=49 ISSUE=44 TOTAL=93

## 结论

社交有两条不同问题线：

1. 自然语言社交经常被 query/rest/gather/routine/combat/travel 抢走。
2. 结构化 social preview 看似 ready，但 commit 被 state audit 拦下，因为关系、承诺、交易后果没有结构化 state operation。

第二条比第一条更危险：ready 以后不能提交，说明 preview/resolver 与 state audit 的契约不一致。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `natural_social_misread_as_query` | 14 | 引擎 | `向/邀请/请/让/请求/送/确认/汇报` 等社交动词被实体查询吞掉。 | NPC 祈使句、送礼、道歉、请求、汇报优先 social。 |
| `social_commit_failed` | 13 | 引擎契约 | delta 标记 `relationship_update_required` 或 `trade_items_required`，但没有 relationship/project/clock/item update，state audit 阻断。 | preview 不应 ready；或生成明确 relationship/trade/project delta；低影响需显式 no-change。 |
| `natural_social_wrong_action` | 5 | 引擎 | 打招呼/打开通道/带路/菌丝人指令等被 combat/travel/maintenance。 | social slot parser + group/NPC command 规则。 |
| `natural_social_misread_as_rest` | 4 | 引擎 | `守夜/休息` 词抢过 NPC 请求语义。 | NPC + rest/watch phrasing 优先 social 或 combat-watch，不能 rest ready。 |
| `natural_social_misread_as_gather` | 2 | 引擎 | 送食物、让 An 采硫磺被当 gather。 | `给/送/让NPC帮忙` 是 social/trade/request，不是玩家采集。 |
| `natural_social_misread_as_routine` | 2 | 引擎 | 让夏娃说明安排、叫小的吃饭被当 routine。 | NPC 指令优先 social。 |
| `social_target_unresolved` | 2 | 引擎 + 内容 | `给南瓜说早安`、`拜访An一家` 没解析到 NPC/group。 | 补 social alias/group entity；保留已识别名字。 |
| `social_self_target_committed` | 1 | 引擎 guardrail | self 作为 NPC 仍可 commit。 | social target 不能是 player self，除非专门 self-reflection action。 |
| `social_source_user_text_mismatch` | 1 | 引擎/测试调用 | explicit social 与 source text routine 冲突，preview_from_text/explicit action 契约不清。 | explicit action 调用保留 warning；自然入口应由 router 决策。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| structured `请求帮忙看门` | commit failed: needs relationship update | commit ok 或 preview needs_confirmation | social delta 没有关系/项目/clock 更新。 |
| structured `送一份食物` | commit failed: trade items required | commit ok 或 preview needs_confirmation | trade 没有 item decrement/transfer。 |
| `向南瓜道歉刚才太急` | query | social | 道歉动词没进 social。 |
| `请求南瓜帮我守夜` | rest ready | social | NPC 请求被 rest 抢走。 |
| `让An帮忙采硫磺` | gather | social request | `让NPC帮忙` 不等于玩家采集。 |
| `请An帮忙带路去湖边聚落` | travel ready | social/remote confirmation | 带路请求被普通旅行抢走。 |

## 是否是剧情包或存档问题

部分是：

- `An一家`、`菌丝人`、T2 这类 group/social target 需要 entity 或 aliases。
- 关系轴、承诺、交易物品、项目/clock 应有可写结构，否则 social 后果无处保存。

但 commit failed 的直接原因是引擎 contract：既然 delta 自己标记需要关系/交易，就不能不提供 state op 还返回 ready。

## 修复建议

1. social parser 输出：
   - `npc/group`, `topic`, `approach`, `speech_act=request|apology|gift|promise|warning|report|invite|ask`
   - `trade_items`, `relationship_effect`, `project_effect`, `remote_mode`
2. `build_social_delta`：
   - 低影响问候：显式 `no_relationship_change=true`, `no_trade=true`。
   - 请求/承诺/威慑：生成 relationship/project/clock pending update 或 `needs_confirmation`。
   - 赠送/交易：要求 item transfer/decrement delta。
3. `validate_social_delta` 把缺 relationship/trade state op 升为 preview blocker。
4. remote social confirmation 保持现有通过路径：不在同地时给 travel/remote-call plan，不直接写。
5. block self target。

## 回归验收

- structured social 不再出现 preview ready 但 commit 被 state audit 拦。
- `向南瓜道歉`、`请求夏娃暂缓扩张`、`请小的继续教我石板符号` 都是 social。
- `送An一些盐作为交换` 要求 trade item delta。
- `请An带路去湖边聚落` 不直接 travel，应先 social/remote confirmation。
