# 2026-07-01 专项测试 Bug 分析总览

来源目录：`/Users/oliver/.hermes/rpg-engine/reports/2026-07-01`

分析范围：10 份 `current-save-*-probe-2026-07-01.md` 测试报告。`inventory-quantity-strategy-gap.md` 是设计缺口文档，作为库存数量策略的参考，不计入“每份测试报告”。

## 文件清单

| 分析文件 | 原始报告 | 原始统计 | 主归因 |
|---|---|---:|---|
| `01-action-recognition-analysis.md` | `current-save-action-recognition-probe-2026-07-01.md` | PASS=79 ISSUE=59 | 引擎意图路由 |
| `02-query-recognition-analysis.md` | `current-save-query-recognition-probe-2026-07-01.md` | PASS=100 ISSUE=59 | 引擎查询路由 + 查询索引/内容别名 |
| `03-intake-analysis.md` | `current-save-intake-probe-2026-07-01.md` | PASS=121 ISSUE=21 | 自然语言入库路由 + 提交前 guardrail |
| `04-consumption-analysis.md` | `current-save-consumption-probe-2026-07-01.md` | PASS=43 ISSUE=60 | 消耗动作缺失 + 库存数量策略 |
| `05-combat-analysis.md` | `current-save-combat-probe-2026-07-01.md` | PASS=47 ISSUE=30 | 战斗槽位抽取 + 高风险 guardrail |
| `06-craft-analysis.md` | `current-save-craft-probe-2026-07-01.md` | PASS=35 ISSUE=42 | 制作槽位/配方解析 + delta 契约 |
| `07-explore-analysis.md` | `current-save-explore-probe-2026-07-01.md` | PASS=62 ISSUE=24 | 探索目标解析 + 内容别名 |
| `08-rest-analysis.md` | `current-save-rest-probe-2026-07-01.md` | PASS=23 ISSUE=28 | 休息时间解析 + 边界意图 |
| `09-social-analysis.md` | `current-save-social-probe-2026-07-01.md` | PASS=49 ISSUE=44 | 社交槽位/后果 delta 契约 |
| `10-travel-analysis.md` | `current-save-travel-probe-2026-07-01.md` | PASS=75 ISSUE=15 | 路线内容 + travel guardrail |
| `11-ai-consensus-intent-design.md` | 当前讨论设计备忘 | - | 外部/内部 AI 共识意图识别 + 内核槽位绑定 |
| `12-ai-intent-refactor-plan.md` | 长期 AI 改造计划 | - | AI 共识主路由 + IntentCandidate/Binder/Arbiter 一次性落地路线 |

## 总体判断

这些 bug 不是单一层的问题。大多数失败来自引擎层的自然语言路由和槽位抽取，少数来自剧情包/存档内容的别名、路线、配方、retired 状态和库存元数据不完整。

最高优先级是把“自然语言识别”和“可保存 delta”之间的契约补齐：只要 resolver 返回 `ready_to_save=True`，提交就不应该再因为缺关系、缺交易、缺材料扣减、缺库存 upsert 而失败。反过来，如果缺这些结构化状态变化，preview 就应该停在 `needs_confirmation` 或 `clarify`。

## 根因分类

| 根因编号 | 归属 | 影响报告 | 说明 | 修复方向 |
|---|---|---|---|---|
| E1 | 引擎 | action/query/intake/consumption/combat/craft/explore/rest/social/travel | 关键词路由顺序和优先级不稳定，`检查/查看/让/给/用/回/等到/守夜` 这类词在查询、动作、社交、休息、战斗之间反复误判。 | 在 `intent_router` 前置只读查询、否定/假设、消耗、社交、旅行、战斗、制作等显式判定；建立 gold set 回归。 |
| E2 | 引擎 | combat/craft/social/rest/intake | 自然语言只选中了 action 类型，没有抽出目标、材料、弹药、距离、耗时、NPC、topic、approach 等槽位。 | 增加结构化 intent parser，输出 `action + slots + confidence + missing_required`，resolver 只做验证和结算。 |
| E3 | 引擎 | craft/social/consumption/travel/combat | resolver/validator 允许危险或不完整 delta 进入 ready/commit，或者 preview ready 但 commit 被 state audit 拦截。 | ready 前强制验证 state ops；将 state audit 的关键规则前移为 resolver/validator blocker。 |
| E4 | 引擎 + 存档 | consumption/intake/combat/query | 库存只有 numeric `quantity`/`unit` 一等字段，fuzzy 数量和高风险元数据没有统一策略。 | 实现 `quantity_strategy=exact|fuzzy|needs_audit`，高风险物品必须 exact，低风险 fuzzy 也必须结构化。 |
| C1 | 剧情包/内容 | query/explore/travel/craft/social | 别名、路线、配方、聚合实体和 target ranking 不够；如 `文明传闻` 可解析到 rule 而非 clock，旧小屋缺结构化路线，部分配方别名不匹配。 | 补 content aliases、route records、recipe aliases、aggregate query cards；把 retired/historical 内容从普通候选中过滤。 |
| S1 | 当前存档 | combat/travel/consumption/query | 当前存档存在 retired 弹药/历史地点仍可被 resolver 当作可用对象、部分物品缺 source/confidence/location、部分聚合数量只在文本里。 | 存档迁移/清理：标记 retired 不可交互，补高风险库存元数据，给聚合事实建立 queryable entity/card。 |
| T1 | 测试口径 | combat/craft/action/query | 个别 issue label 与 observed 不完全一致，或 expected 允许多个路线但 issue 名称过窄。 | 清理 probe 的 issue 命名，区分“真正失败”和“可接受但需偏好调整”。 |

## 建议修复顺序

1. 修 E3/E4：提交前 guardrail 和库存策略，先避免写坏存档。
2. 修 E1/E2：统一自然语言 intent/slot parser，降低误路由。
3. 修 C1/S1：补路线、别名、配方、聚合实体和 retired 状态。
4. 修 T1：调整 probe 命名和验收口径。

## 关键验收线

- 所有 `preview ready_to_save=True` 的 action 都能 commit，且 commit 后 state audit 不应再拦截同一个 delta。
- 所有需要结构化状态变化的行动，如果缺 upsert/project/relationship/clock/material delta，preview 必须 `needs_confirmation`。
- 高风险库存不允许 fuzzy-only、不允许缺 source/confidence/location、不允许 minimal upsert 丢 metadata。
- retired location/ammo/历史实体不能作为普通 travel/combat/social 候选。
- 查询、动作、社交、休息、战斗、制作、消耗的自然语言 gold set 进入固定回归测试。
