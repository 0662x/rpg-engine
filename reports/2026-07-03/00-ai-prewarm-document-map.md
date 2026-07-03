# AI Prewarm 文档地图

Date: 2026-07-03

## 权威入口

当前 AI intent / preflight / platform prewarm 文档分三层：

| 层级 | 文档 | 用途 |
| --- | --- | --- |
| 长期权威设计 | [`docs/specs/ai-intent-prewarm.md`](../../docs/specs/ai-intent-prewarm.md) | AI intent、internal review、preflight、平台预热、风险分级和低风险快通道的长期边界。后续策略判断优先看这份。 |
| 已实现记录 | [`2026-07-02/01-lightweight-internal-ai-and-parallel-consensus.md`](../2026-07-02/01-lightweight-internal-ai-and-parallel-consensus.md) | 记录阶段一、阶段二和阶段三 3A 的设计、实现、专家复核和测试结果。保留历史讨论，不作为 3B 施工清单。 |
| 当前实施计划 | [`01-platform-prewarm-3b-lightweight-implementation-plan.md`](01-platform-prewarm-3b-lightweight-implementation-plan.md) | 3B 平台监听/预热的工程计划和 2026-07-03 rpg-engine 侧实现记录。后续真实 QQ/Hermes 插件 canary 和验收优先对齐这份文档。 |
| 专家复核记录 | [`02-ai-subsystem-code-review.md`](02-ai-subsystem-code-review.md) | 记录本轮 AI 子系统 code review、已修复点、剩余技术债和测试结果。 |
| 对外工具契约 | [`docs/specs/mcp-adapter.md`](../../docs/specs/mcp-adapter.md)、[`docs/specs/cli.md`](../../docs/specs/cli.md)、[`docs/prompts/ai-client-prompt.md`](../../docs/prompts/ai-client-prompt.md) | 说明 MCP/CLI/AI client 如何使用已实现的 preflight / sidecar 能力，以及真实 Hermes/QQ 原生代码仍未修改。 |

## 术语

- 阶段一：`rpg-engine` 内部 AI 从 `hermes -z` 子进程模式转向轻量 direct provider 主路径。
- 阶段二：`rpg-engine` 支持 advisory preflight cache，正式链路只消费内核自己的 internal review。
- 阶段三 3A：`rpg-engine` 内核已能用 `message_only`、message lookup、pending wait、late ready telemetry 汇合预热结果。
- 阶段三 3B：平台消息刚到时，由薄 adapter 触发预热。rpg-engine 侧 binding store、queue/worker、metrics、`PlatformSidecar`、标准 `player_turn` 与兼容 `player_act` 的消费衔接、自动激活/失效、正式入口 gate、绑定 save 执行、防重复正式消息和 canary 指标已实现；Hermes/QQ 原生代码未改。
- IntentJoiner：本文档中的 IntentJoiner 指 3A 已实现的 preflight lookup / join 行为，不是独立平台服务。

## 当前状态

- 3A 已完成：`message_only` identity、无 `preflight_id` message lookup、pending 短等待、`late_ready_unused`、`GameSessionGate` 纯函数契约、MCP/CLI 透传。
- 3B rpg-engine 侧已完成：平台无关 binding store、bounded queue/worker、drop reason、metrics、feature flag、`PlatformSidecar`、标准 `player_turn` 与兼容 `player_act` 的被动 preflight 标识消费、自动激活/失效、正式 act/confirm gate、绑定 save 执行、防重复正式消息。
- AI 策略已完成低风险快通道：内部 AI + 规则候选一致时，`routine/rest/travel/explore` 和只读 query 可进入 `ai_single_source_internal_fast` 预览确认；不会自动保存。
- 3B 仍需真实环境验证：Hermes/QQ 插件调用 `PlatformSidecar`、ACK/typing、真实平台 latency/hit-rate metrics。
- Hermes/QQ 原生代码未改，也不建议作为 3B 默认方案修改。

## 轻量原则

平台监听必须在保证功能的前提下尽量轻：

- 只监听平台消息并触发 advisory preflight。
- 只做 `GameSessionGate`、幂等去重、enqueue、fire-and-forget。
- 默认 feature flag 关闭。
- 队列满、AI 超时、adapter 报错都只降级为“没有预热”。
- 不阻塞 Hermes 正常链路。
- 不读 hidden context。
- 不生成 delta / TurnProposal。
- 不自动 commit。

## 文档维护规则

- 阶段一/二/3A 的历史和测试结果继续留在 2026-07-02 报告。
- 3B 新需求、任务拆分、验收标准和变更记录写入 2026-07-03 计划。
- AI intent 长期边界、风险策略和 preflight 权限边界写入 `docs/specs/ai-intent-prewarm.md`。
- MCP/CLI/prompt 文档只写对外契约，不承载长篇设计讨论。
- 如果后续发现旧架构文档里的 “Phase 3” 指 TurnContract，不应和本组文档的“阶段三 AI 预热”混用。
