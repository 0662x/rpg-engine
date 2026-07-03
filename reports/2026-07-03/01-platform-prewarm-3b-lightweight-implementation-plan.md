# 阶段三 3B：轻量平台监听与预热实施计划

Date: 2026-07-03

Implementation status: 2026-07-03 已完成 rpg-engine 侧 3B 闭环与平台入口安全收口：平台无关 binding store、queue/worker/metrics、feature flag/drop reason、标准 `player_turn` 与兼容 `player_act` 的被动 preflight 标识消费、MCP/CLI player-safe 透传、`PlatformSidecar` 薄接入层、自动激活/失效、正式 act/confirm gate、绑定 save 执行、防重复正式消息和 canary 指标。Hermes/QQ 原生 adapter 仍未修改；真实平台插件只需把 MessageEvent 喂给 `PlatformSidecar`。

## 目标

在不修改 Hermes core / QQ adapter core 的前提下，让平台消息到达后尽早启动 `rpg-engine` 内部 AI 预热。预热只能提高速度，不能改变权限、确认、保存或提交边界。

一句话原则：**平台监听只是可丢弃的加速旁路，不是新运行时。**

## 非目标

- 不改 Hermes core、hermes-agent、Hermes gateway 或 QQ adapter core。
- 不做独立 QQ ingress。
- 不接管 Hermes 的普通聊天流程。
- 不读 hidden context。
- 不缓存 delta 或 TurnProposal。
- 不自动 commit。
- 不把平台 adapter 变成规则引擎或游戏状态机。
- 不做 guild DM、语音、图片、引用消息、多人/群共享存档。

## 已有基础

3A 已在 `rpg-engine` 内核完成：

- `message_only` preflight identity。
- 无 `preflight_id` 的 message lookup。
- pending wait，硬上限 1000ms。
- late ready -> `rejected/late_ready_unused`。
- bypassed/expired 状态机。
- `GameSessionGate` 纯函数契约。
- MCP/CLI 的 `intent_preflight`、`preflight_identity_profile`、`preflight_pending_wait_ms`。

3B 要做的是平台侧和 workspace 侧的轻量连接层。当前已先实现 rpg-engine 内部平台无关基座；真实 Hermes/QQ adapter 只需要把消息归一化为 `PlatformMessage` 后调用该基座。

## 当前已实现

- 新增 `rpg_engine.platform_prewarm`：
  - `GameSessionBindingStore`：workspace `.aigm/game-session-bindings.json`，只存 `session_key_hash/user_id_hash`，不存 raw session/user id。
  - `PlatformPrewarmService`：feature flag 默认关闭，入口只返回 `allow_platform`，不阻塞平台主链路。
  - `PrewarmQueue`：bounded queue、message-level dedupe、queue full drop。
  - `PrewarmWorker`：调用 `GMRuntime.preflight_intent(..., preflight_identity_profile="message_only")`，失败不外抛。
  - `PrewarmMetrics`：enqueue/drop/finish、drop reason、queue depth、worker 平均/P95。
- `GameSessionBinding` 增加 `updated_at`、`last_action_message_id`、`last_confirm_message_id`。
- `SaveManager.player_turn` 增加 host/adapter 内部 AI 配置、被动 preflight 标识透传和内部 `save_path` 绑定执行路径；兼容 `SaveManager.player_act` 复用同一路径。
- `SaveManager.player_turn/player_confirm` 会在 pending action 中保存平台/session hash，并在平台 confirm 时校验同一平台会话。
- MCP `player_turn` 增加 `preflight_id/message_id/platform/session_key/source_user_text_hash/preflight_pending_wait_ms` 参数，并复用 MCP server 的内部 AI 配置；兼容 `player_act` 也可透传同一组被动标识。
- CLI `player turn` 增加 host 级内部 AI 配置、`--external-intent-candidate` 和被动 preflight 标识参数；兼容 `player act` 仍不接收 `external_intent_candidate`。
- 新增 `rpg_engine.platform_sidecar`：
  - `platform_message_from_event()`：把 QQ/Hermes 风格 MessageEvent 归一化为 `PlatformMessage`。
  - `PlatformSidecar.handle_message_event()`：平台消息到达即调用 `PlatformPrewarmService`，立即返回，不等待内部 AI。
  - `PlatformSidecar.start_or_continue_from_message()`、`player_act_from_message()`、`player_confirm_from_message()`：正式玩家链路自动维护 binding，并把同一条消息身份传入 `player_turn`。其中 `player_act_from_message()` 是保留的兼容命名，语义是平台 action facade。
  - `player_act_from_message()` / `player_confirm_from_message()` 已把 binding gate 变成正式入口硬边界：inactive、expired、bot/self、unsupported、command、重复正式消息等不会进入 `SaveManager`。
  - 正式 `act/confirm` 使用 binding 的 `active_save`，不依赖 workspace 全局 active save，避免平台会话串档。
  - `expire_stale_bindings()` / `deactivate_from_message()`：自动失效和手动失效。
  - `metrics_snapshot()`：输出 sidecar latency、clarification、prewarm drop/finish、queue depth、message-only cache used/hit-rate estimate。
- CLI 新增 `aigm platform message/start/act/confirm/metrics/expire/deactivate`，用于 sidecar 调试和轻量接入。
- MCP audit 中 `session_key` 已改为 hash 脱敏。
- 新增/更新测试：`tests/test_platform_sidecar.py`、`tests/test_platform_prewarm.py`、`tests/test_mcp_adapter.py`、`tests/test_game_session.py`、`tests/test_v1_cli.py`。

当前意图策略：

- `player_turn` 能消费 message-only preflight，并且是允许外部 AI 传低信任 `external_intent_candidate` 的标准入口；兼容 `player_act` 也能消费 message-only preflight，但不允许外部 AI 传 `external_intent_candidate`。
- 若 message-only preflight 命中且没有外部结构化候选，只有低风险、单步、内部 AI 与规则候选一致、binder 双方成功、无 safety/missing/confirmation 的情况可进入 `ai_single_source_internal_fast` 预览确认。
- 其他单源内部 AI 仍会澄清；`gather/craft/social/random_table`、`combat`、`maintenance`、`composite` 和 safety flags 不走低风险快通道。

## 总体链路

```text
Platform MessageEvent
  -> thin adapter/plugin/sidecar
  -> normalize PlatformMessage
  -> read GameSessionBinding
  -> GameSessionGate
  -> enqueue message_only intent_preflight
  -> return allow immediately

Hermes normal flow continues
  -> external AI / Agent decides whether to call rpg-engine
  -> rpg-engine player_turn, or trusted start_turn / preview_from_text / act
  -> IntentJoiner consumes ready preflight if available
  -> arbiter / binder / resolver / validation / confirm
```

失败降级：

```text
prewarm hit     -> 少等一次内部 AI
prewarm miss    -> 正常现场内部 AI
prewarm timeout -> 正常现场内部 AI
adapter failure -> 正常 Hermes 链路
queue full      -> drop prewarm only
```

## 轻量设计原则

1. 平台 adapter 只做“消息到 preflight 请求”的转换。
2. adapter 不拥有 action 判断权；意图识别仍由外部 AI + rpg-engine 内部 AI + 内核 arbiter 完成。
3. adapter 不阻塞 Hermes；`allow` 必须立即返回。
4. worker 有界：默认 1 个 worker，小队列，满了就丢。
5. 所有 3B 功能 feature flag 默认关闭。
6. 预热结果必须短 TTL；迟到结果只能 telemetry。
7. 只保存 hash 后的 session/user id；不要把 raw session id、hidden context、长期 raw text 写进 binding。
8. ACK/typing 是体验层，V1 默认不做；如果做，只能延迟发送，避免快速回复时制造噪音。

## 关键决策

### 3B 消费入口

要先确认当前 Hermes 玩家链路主要调用哪个入口：

| 入口 | 现状 | 3B 建议 |
| --- | --- | --- |
| `start_turn` / `preview_from_text` | 已能接收 preflight 标识和 pending wait。 | 可直接消费 3B 预热结果。 |
| `player_turn` | 已是标准 player-safe 自然语言入口；2026-07-03 已接收被动 preflight 标识。 | 可接收低信任 `external_intent_candidate`，也可只透传 cache lookup 所需的 `preflight_id/message_id/platform/session_key/source_user_text_hash/preflight_pending_wait_ms`。 |
| `player_act` | 兼容 wrapper；内部复用 `player_turn` 语义。 | 只允许 cache lookup 所需的被动标识；不允许 external candidate 或 per-call AI override。 |

推荐：真实 Hermes 调用链路优先走 `player_turn`；如果接入 `PlatformSidecar.player_act_from_message()` 或旧 `player_act` 兼容层，可以透传同一组被动标识。这不会改变确认边界。

### message_only 三元组

3A 当前允许创建缺少 `platform/session_key/message_id` 的 `message_only` 记录，但 by-message lookup 会 miss。

3B 当前实现：

- 平台 adapter 必须提供 `platform/session_key/message_id`。
- 3B worker 创建 `message_only` preflight 时，把三元组缺失视为 drop，并记录 telemetry。
- rpg-engine 低层 `intent_preflight` API 仍保持兼容，不把三元组改成硬校验；3B worker/service 负责在平台预热路径上 drop。

### session_key 隐私

3A preflight cache 仍存 raw `session_key` 以做身份校验。

3B 当前实现：

- workspace binding store 只存 hash。
- MCP audit 中 `session_key` 已 hash 脱敏。
- adapter audit 应只存 hash、reason、message_id、platform、drop cause。
- preflight cache 中 `session_key` 仍按 3A 兼容方式保存 raw 值，用于现有身份校验；后续 hardening 再评估 hash/redaction 迁移。

## 实施阶段

### 3B-0：开工前硬化（已完成）

目的：先把 3B 不该变重、不该越权的边界固化。

任务：

1. 明确术语：3A 是内核 join，3B 是平台消息到达即 enqueue。
2. 确认 Hermes 当前使用标准 `player_turn`、兼容 `player_act` 还是低层 `preview_from_text`。
3. 决定标准 `player_turn` 与兼容 `player_act` 如何接收被动 preflight 标识。
4. 定义 3B metrics 字段。
5. 定义 workspace binding store schema。
6. 定义 adapter feature flag，默认关闭。
7. 定义三元组缺失、重复 message、queue full、AI timeout 的 drop reason。

验收：

- 文档和测试计划更新。
- 不改 Hermes core。
- 不新增平台 worker 之前，现有全量测试保持通过。

### 3B-1：平台无关基座（已完成）

目的：先在 `rpg-engine` 或 workspace 层实现平台无关能力，不接 QQ。

组件：

- `GameSessionBindingStore`
- `PrewarmQueue`
- `PrewarmWorker`
- `PrewarmMetrics`
- `PlatformMessage` adapter contract

Binding store 最小字段：

```text
platform
session_key_hash
user_id_hash
active_save
state: inactive | active_game | pending_clarification | pending_approval | cooldown
active_until
last_message_id
clarification_id
updated_at
```

Queue 最小行为：

- bounded queue。
- 默认 1 worker。
- message-level dedupe。
- drop on full。
- worker exception 不外抛。
- 每条任务记录 start/finish/drop reason。

验收：

- inactive 不 enqueue。
- active_game enqueue。
- expired binding 不 enqueue。
- duplicate message 不重复 enqueue。
- queue full drop。
- worker failure 不影响主流程。

### 3B-2：MCP / player-safe 消费衔接（已完成）

目的：确保预热结果能被真实玩家路径消费，而不是只被低层测试工具消费。

任务：

1. 若真实链路走 `preview_from_text`：确认已能透传 `message_id/platform/session_key/source_user_text_hash/preflight_pending_wait_ms`。
2. 若真实链路走标准 `player_turn`：新增被动标识参数，并允许低信任 `external_intent_candidate` 继续走标准复核链路。
3. 若真实链路走兼容 `player_act`：新增被动标识参数，并只允许 cache lookup，不允许 external candidate、intent backend/model override。
4. 补 prompt/spec：默认 player profile 不调用 `intent_preflight`，但 host/adapter 可以透传被动标识。

验收：

- `player_turn` / 兼容 `player_act` 的新增参数不能暴露 delta/proposal。
- `player_confirm` 仍必须传 session_id。
- preflight hit 不等于玩家确认。
- preflight miss/fail 不影响原玩家路径。

### 3B-3：Hermes/QQ 薄 adapter / sidecar（rpg-engine 侧已完成）

目的：接入真实平台事件，但仍保持轻量。当前未改 Hermes/QQ 原生代码；rpg-engine 已提供 `PlatformSidecar`，真实 Hermes/QQ 插件只需调用该 sidecar 或等价 Python API。

adapter 只做：

1. 读取 MessageEvent 的原文、message_id、platform、session_key、actor、message_type。
2. 归一化为 `PlatformMessage`。
3. 读取 binding。
4. 调 `GameSessionGate`。
5. allow 时 enqueue prewarm。
6. 立刻返回 `allow`。

adapter 不做：

- 不调用 commit。
- 不生成 external candidate。
- 不读取 hidden context。
- 不等待 internal AI。
- 不发默认 ACK。
- 不持久化 raw text 到 workspace binding。

首批平台范围：

- QQ C2C 私聊。
- QQ 普通群 @。

继续 No-Go：

- guild DM。
- guild channel。
- 图片、语音、引用消息。
- 多人共享存档。

验收：

- 已满足：普通聊天 inactive 不 prewarm。
- 已满足：游戏 active_game 才 prewarm。
- 已满足：slash command / bot / self / approval / media 不 prewarm。
- 已满足：adapter/worker 报错不影响平台主流程。
- 已满足：不改 Hermes core。
- 已满足：正式 `player_act_from_message()` 自动透传 `message_id/platform/session_key/source_user_text_hash/preflight_pending_wait_ms`，并在内部调用标准 `player_turn` 语义。
- 已满足：正式 `player_act_from_message()` / `player_confirm_from_message()` 先过 binding gate；未绑定、过期、bot/self、命令、unsupported、重复正式消息直接拒绝，不进入 `SaveManager`。
- 已满足：正式 `act/confirm` 使用 binding 的 `active_save`，不使用全局 active save 推断平台会话目标存档。
- 已满足：pending action 存储平台/session hash，平台 confirm 必须来自同一平台会话。

### 3B-4：Canary 与体验调参（rpg-engine 侧已完成）

目的：小范围验证“更快但不乱”。

指标：

```text
prewarm_enqueue_count
prewarm_drop_count by reason
preflight_hit_rate
preflight_miss_rate
preflight_pending_wait_p50/p95/max
late_ready_unused_count
fallback_internal_ai_count
clarification_rate
adapter_error_count
queue_depth
average user-visible latency
```

体验策略：

- V1 默认静默预热。
- 如果需要 ACK，只在 800ms 后仍未完成时发送轻量提示。
- typing/ACK 不能成为成功条件。

验收：

- 已实现指标入口：`PlatformSidecar.metrics_snapshot()` 和 CLI `aigm platform metrics`。
- 已覆盖：drop reason、queue depth、worker average/P95、user-visible latency average/P50/P95、clarification count、message-only cache status、used count、hit-rate estimate。
- 仍需真实平台 canary 验证：命中时平均等待时间是否下降，以及真实 QQ/Hermes 输入链路上的 hit-rate。
- 已满足：miss/failure 时降级，不影响原玩家路径。
- 已满足：零自动 commit。
- 已满足：零 hidden context 泄漏。
- 已满足：零 Hermes core patch。

## 测试矩阵

| 类别 | 必测 |
| --- | --- |
| Gate | inactive、expired、pending_clarification、pending_approval、no active save、empty text、command、media、bot/self、missing message_id、duplicate message |
| Queue | enqueue、drop on full、dedupe、worker exception、timeout、shutdown |
| Binding | active TTL、last_message_id 更新、last_action/confirm_message_id、session hash、save switch、manual inactive |
| Preflight | message_only with full identity、later external candidate、pending wait、late_ready_unused、expired、bypassed |
| Player path | preflight hit/miss 都不绕过 preview/validation/player_confirm；正式入口按 binding save 执行；重复正式 message_id 不重放 |
| Adapter | allow immediately、no hidden read、no commit、failure isolation |
| Canary | hit rate、latency、drop reasons、clarification rate |

## 完成标准

3B 最小可交付必须满足：

1. 已满足：不改 Hermes core。
2. 已满足：feature flag 默认关闭。
3. 已满足：active_game 才会 enqueue prewarm。
4. 已满足：queue/worker 有界，失败可丢弃。
5. 已满足：message_only preflight 能被 `player_turn`、兼容 `player_act`、`start_turn`、`preview_from_text` 和低层 `act` 消费。
6. 已满足：preflight hit 不绕过 arbiter、binder、resolver、validation、confirm。
7. 已满足 rpg-engine 侧指标：已有 enqueue/drop/finish、drop reason、queue depth、worker average/P95、玩家可见 latency、clarification、message-only used/hit-rate estimate；真实平台数值需要在线 canary 采样。
8. 已满足入口安全收口：`PlatformSidecar` 正式 act/confirm 先校验 binding gate，按 binding save 执行，并拒绝重复正式消息。

## 下一轮建议

前四步和入口安全收口已在 rpg-engine 内完成，下一轮不需要改 Hermes core。建议进入真实平台 canary，但必须使用长驻 sidecar 或等价插件进程；一次性 CLI 只适合诊断：

1. 在 Hermes/QQ 插件或 sidecar 进程里实例化 `PlatformSidecar`，启动 dispatcher；退出时调用 `stop()`。
2. QQ MessageEvent 到达时调用 `handle_message_event()`。
3. Hermes 正式玩家行动调用 rpg-engine 时优先使用 `player_turn`；平台 sidecar 可使用 `player_act_from_message()` 这个兼容命名 facade，或透传同一组被动标识。
4. 小范围打开 `AIGM_PLATFORM_PREWARM=1`，观察 `aigm platform metrics` / `metrics_snapshot()`。
5. 采 20-50 条真实消息，记录 hit-rate、latency、drop reason、clarification rate 和重复消息拒绝情况。
6. 已完成低风险 `single_source_internal` 快通道；真实 canary 需要观察 `ai_single_source_internal_fast` 的命中率、澄清率下降幅度和是否出现误接受。
