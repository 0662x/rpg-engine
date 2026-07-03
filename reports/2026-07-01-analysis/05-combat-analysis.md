# Combat Probe 分析

原始报告：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01/current-save-combat-probe-2026-07-01.md`

统计：PASS=47 ISSUE=30 TOTAL=77

## 结论

结构化战斗链路基本可靠：5 种弹药、多个距离、连续射击和混合弹药都能正确扣减。问题集中在自然语言槽位抽取和高风险 guardrail。

主责任是引擎。存档/内容也有少量参与：retired 弹药、非武器/非弹药的分类和可靠性元数据没有被 combat resolver 当成硬约束。

## Bug 分类

| bug 族 | 数量 | 归属 | 产生原因 | 修复办法 |
|---|---:|---|---|---|
| `natural_combat_misread_as_query` | 10 | 引擎 | 装填、戒备、压制、架弩、地雷守门等战斗准备语义被实体 query 吞掉。 | 扩展 combat/watch/overwatch 词表；武器/弹药/警戒词优先 combat clarify。 |
| `natural_combat_options_not_extracted` | 6 | 引擎 | 已完整写出目标、武器、弹药、距离、ready state，但 options 为空或不完整。 | 增加 combat slot parser：target、weapon、ammo、distance、ready_state、mode。 |
| `natural_combat_target_not_extracted` | 5 | 引擎 + 内容别名 | `南瓜/T2母猫/大型猫科/I室母猫` 没有保留为 target。 | target resolver 支持角色别名、地点限定目标和威胁别名；缺其他字段时保留已解析 target。 |
| retired/non-weapon/non-ammo/self/item guardrail | 6 | 引擎 + 存档 | resolver 只给 warnings，仍 ready/committed；没有硬性阻止 retired ammo、非 weapon、非 ammunition、自我目标。 | 把这些 warnings 升级为 blockers；要求高风险 ammo metadata 完整。 |
| `natural_query_misrouted_to_combat` | 1 | 测试口径 + 引擎 | 报告名说 misrouted to combat，但 observed 是 routine；本质是武器/弹药库存查询不应成可保存行动。 | 对 inventory/count query 先锁定 read-only query；同步修正 probe issue 名。 |

## 代表案例

| 案例 | observed | expected | 归因 |
|---|---|---|---|
| `用终极复合弩发射琥珀麻箭射南瓜，标准距离，已上弦并装填` | combat clarify，但 target/weapon/ammo/distance 都未抽出 | 直接可提交并扣 1 支 | 引擎槽位抽取缺失。 |
| `装填霜白冻箭准备压制` | query | combat clarify | 战斗准备词被 query 抢走。 |
| `拿弩守夜` | rest ready | combat/watch clarify | rest 关键词优先级过高。 |
| retired poison ammo | committed=True, ammo 9->8 | block | retired/可靠性不足没有作为硬性 blocker。 |
| non-weapon tool as weapon | committed=True | block | item category warning 没有阻断。 |
| self target | committed=True | block | 自我目标缺硬性防护。 |

## 是否是剧情包或存档问题

有一部分是存档/内容问题：

- `item:poison-bolts`、`item:plain-bolts` 这类 retired/unreliable 弹药仍被普通解析命中。
- 武器/弹药兼容关系、status、inventory reliability、ammo profile 需要完整。
- `大型猫科`、`I室母猫` 等目标别名如果没有明确 entity 或 threat alias，会影响 target extraction。

但 resolver 不应把这些内容缺口当 warning 后继续提交，硬性安全属于引擎责任。

## 修复建议

1. 新增 combat parser：
   - `mode=shoot|reload|aim|overwatch|suppress|trap|retreat|guard`
   - `target`, `weapon`, `ammo`, `distance`, `ready_state`
   - `conditional=true` 时只生成 clarify/overwatch plan，不直接扣弹药。
2. combat resolver blocker：
   - target 不能是 self，普通 item target 需要 `object_attack_confirmed`。
   - weapon 必须 category/profile 为 weapon。
   - ammo 必须 category/profile 为 ammunition，且兼容 weapon。
   - retired/depleted/fuzzy/unreliable ammo 必须阻断。
3. 对高风险弹药要求 exact quantity、unit、source、confidence、location。
4. 修改 inventory query 优先级，`数量/还剩/所有箭矢` 不生成可保存行动。

## 回归验收

- 完整自然语言射击能直接形成 combat delta 并扣弹药。
- 模糊警戒、压制、架弩进入 combat clarify，不是 query/rest/travel。
- retired ammo、非武器、非弹药、自我目标、普通物品目标全部 pre-commit 阻断。
- 结构化 combat 现有 25 个 pass 不回退。
