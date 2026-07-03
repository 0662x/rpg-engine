# AI 子系统专家 Code Review

Date: 2026-07-03

Scope: `ai/provider.py`、`ai_intent/*`、`preflight_cache.py`、`platform_prewarm.py`、`platform_sidecar.py`、`save_manager.py` 的 AI intent / preflight / platform sidecar 相关路径，以及 MCP/CLI/prompt/spec 文档。

## 总结

专家组结论：当前 AI 子系统没有变成不可维护的屎山，核心边界是清楚的；但几个 orchestration 文件已经偏大，后续应避免继续往 `runtime.py`、`platform_sidecar.py`、`preflight_cache.py` 里塞新策略。

本轮已做一个小而关键的策略放宽：当没有外部 AI 候选时，内部 AI 与确定性规则在低风险单步行动上完全一致，可以进入预览确认，source=`ai_single_source_internal_fast`。这解决了 message-only 预热命中后仍频繁澄清的问题，同时不绕过 `player_confirm` 或 commit guard。

## 角色交叉评审

### AI 架构负责人

结论：模块划分基本成立。

- `ai_intent` 已经承载 normalization、arbiter、binder、risk、route adoption，适合作为意图策略中心。
- `platform_sidecar` 是平台入口 facade，不应继续长出自然语言规则。
- `runtime.py` 已经 1600+ 行，后续 AI 策略不要继续写进 runtime。

建议：长期保留 `docs/specs/ai-intent-prewarm.md` 作为权威边界文档，报告只记录阶段实施。

### Gameplay / Save Safety

结论：当前放宽是可接受的，因为它只到 preview/pending confirmation。

- 快通道仅限 `routine/rest/travel/explore` 和只读 query。
- `gather/craft/social/random_table` 仍需外部+内部一致或更谨慎策略。
- `combat/maintenance/composite/safety_flags` 仍严格处理。
- 标准 `player_turn` 可接收低信任 `external_intent_candidate`；兼容 `player_act` 仍不接收 `external_intent_candidate`、delta、proposal 或 per-call AI override。

本轮已补测试，锁定低风险接受、中风险澄清、query submode 保持。

### 平台 / 性能

结论：轻量目标基本达成，前提是生产路径使用长驻 sidecar 和小 worker。

- `PlatformSidecar` 可做到消息到达即 enqueue，worker 后台调用 internal preflight。
- queue bounded，feature flag 默认关闭，失败可丢弃。
- `player_act_from_message()` 是保留的兼容命名平台 facade，可自动透传 message identity，内部调用 `player_turn` 语义并消费 message-only preflight。
- 重复正式 action message 现在优先返回 `duplicate_action_message`，pending action 期间的新消息仍会被 `pending_approval` 拦住。

需观察：`metrics_snapshot()` 不应在高频真实生产热路径里无节制调用；真实 canary 再看 hit-rate 和平均等待时间。

### 文档 / 开发体验

结论：原文档信息完整，但短期实施记录和长期设计混在一起，容易误读。

本轮整理方向：

- 新增长期权威文档：`docs/specs/ai-intent-prewarm.md`。
- `reports/2026-07-03/01...` 继续作为 3B 平台预热实施计划。
- MCP/CLI/prompt spec 只保留对外契约，不承载长篇讨论。

## 本轮已修复

1. 放宽低风险 message-only 预热策略：
   - `ai_single_source_internal_fast`
   - 内部 AI + 规则候选一致
   - binder 双方成功
   - 无 safety/missing/confirmation
   - 仅进入 preview/pending confirm，不 commit

2. 修复 query route adoption：
   - accepted query 不再强行落成 `entity`
   - 保留 `scene/entity/context` fallback submode

3. 修复平台重复消息 gate 优先级：
   - 同一 action message 重进时优先 `duplicate_action_message`
   - 不同消息在 pending approval 期间仍被 `pending_approval` 拦住

4. 更新 deterministic eval 金标：
   - 低风险 internal+rules agreement 现在期望 `ai_single_source_internal_fast`
   - 旧的 `single_source_internal` 澄清用例改为 fast preview 用例

## 仍需关注的问题

| 问题 | 严重度 | 建议 |
| --- | --- | --- |
| `runtime.py`、`platform_sidecar.py`、`platform_prewarm.py`、`preflight_cache.py` 偏大 | 中 | 后续新增行为时拆 service/facade，不做无关大重构。 |
| `player_act_from_message()` 诊断路径可能在正式 act 时再 enqueue | 低-中 | 真实平台接入时确保 adapter 先调用 `handle_message_event()`；canary 观察双调用率。 |
| `metrics_snapshot()` 可能扫描 cache 指标 | 低-中 | 高流量部署改为采样或周期缓存。 |
| duration metrics 目前是内存 list | 低 | 长驻进程改 rolling window。 |
| binding store 是 JSON | 低-中 | 单进程轻量可接受；多进程再加锁或迁 SQLite。 |
| preflight cache 仍保存 raw `session_key/user_text` | 中 | 后续做 retention/redaction 迁移。 |
| pending action 是 workspace 单槽 | 中 | 当前单人游戏可接受；多平台并发再做 scoped pending。 |

## 测试结果

本轮验证：

- `python3 -m py_compile rpg_engine/ai_intent/arbiter.py rpg_engine/ai_intent/adapters.py rpg_engine/platform_sidecar.py`
- `python3 -m pytest tests/test_ai_intent.py tests/test_mcp_adapter.py tests/test_platform_sidecar.py -q`
  - `59 passed`
- `python3 -m pytest tests/test_runtime.py tests/test_eval_suite.py -q`
  - `64 passed, 47 subtests passed`

下一步建议先跑全量测试，再做真实平台 canary。不要急着拆大文件；先用真实数据确认 prewarm hit-rate、平均等待时间、drop reason 和澄清率。
