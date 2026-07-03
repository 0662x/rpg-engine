# AI 平台本地模拟压测报告

Date: 2026-07-03

Scope: 本轮只模拟 `rpg-engine` 内部 AI intent、message-only prewarm、PlatformSidecar、标准 `player_turn` 语义的兼容平台 action facade、player_confirm 和平台 gate。未修改 Hermes/QQ 原生代码，也未连接真实 QQ。

## 结论

本地模拟结论：rpg-engine 侧闭环可用，轻量设计成立，低风险快通道没有绕过保存确认。本轮已把扩展模拟固化为自动化测试：`tests/test_platform_ai_simulation.py`。

- 本地扩展模拟测试：7 passed, 21 subtests passed，合计 28 个自动化子场景。
- 扩展模拟 + 相关单元/eval 测试：134 passed, 68 subtests passed。
- DeepSeek 官方 API 格式已核对：内部 provider 现在接受官方 `https://api.deepseek.com` base URL，也接受完整 `/chat/completions` endpoint。
- 全量测试：354 passed, 289 subtests passed。
- 当前环境没有 `DEEPSEEK_API_KEY`，所以没有跑真实 DeepSeek 延迟；真实模型耗时需要接 key 后单独 canary。

## 模拟覆盖

| 场景 | 结果 | 关键观察 |
| --- | --- | --- |
| QQ-like raw event normalization | PASS | `msg_id/content/type/group_id/user_id/at_bot` 可归一化为 `PlatformMessage`，群 at 变 `group_at`；private/c2c 事件可派生 session key。 |
| 正常 rest：prewarm -> act -> confirm | PASS | message-only cache 被正式 act 消费；`ready_to_confirm=true`；confirm 后 `saved=true`。 |
| 低风险快通道 | PASS | `rest/travel/routine` 可进入 ready preview；未自动保存。 |
| 中高风险不快通 | PASS | `social/gather/craft/random_table/combat` 不走低风险快通道。 |
| 缺槽/幻觉目标/safety flags | PASS | 缺 destination、虚构地点、`forced_save/hidden_info/prompt_injection/unsafe_command` 均不 ready；安全 flag blocked。 |
| pending approval + duplicate + confirm guard | PASS | 同 message_id 重放返回 `duplicate_action_message`；新消息在待确认期间返回 `pending_approval`；错误 session_id/错误平台会话不能保存；正确 confirm 保存。 |
| 异常平台消息 | PASS | bot/self/media/group-not-at/command/empty/approval-as-act 分别被 gate 拒绝。 |
| inactive / expired session | PASS | 未绑定会话 `inactive`；过期会话 `expired`，进入 SaveManager 前被拒绝。 |
| feature disabled / missing identity / queue pressure | PASS | disabled drop、missing platform/session/message id drop、queue size=3 时 8 条消息中 3 enqueued/5 queue_full。 |
| AI timeout | PASS | worker 记录 `ai_timeout`，只丢弃预热，不让玩家主链路崩掉。 |

## 关键数值

假模型环境下的局部数值只用于验证链路，不代表真实模型性能。扩展测试已进入自动化：

```text
python3 -m pytest tests/test_platform_ai_simulation.py -q
# 7 passed, 21 subtests passed

python3 -m pytest tests/test_platform_ai_simulation.py tests/test_ai_intent.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py tests/test_runtime.py tests/test_eval_suite.py -q
# 134 passed, 68 subtests passed

python3 -m pytest -q
# 354 passed, 289 subtests passed
```

局部模拟数值：

- 正常 rest prewarm worker：约 42ms。
- 正式 act 消费 cache 后玩家可见链路：约 36ms。
- queue pressure：`max_queue_size=3` 时，多余消息按 `queue_full` 丢弃。
- AI timeout：worker result `ok=false/status=failed/reason=ai_timeout`，不会写入 pending action。

## 真实 DeepSeek Canary 待测

当前本机环境：

```text
DEEPSEEK_API_KEY=missing
```

已新增两个本地辅助脚本：

```text
scripts/setup_platform_prewarm_env.sh
scripts/check_platform_prewarm.sh
```

`setup_platform_prewarm_env.sh` 会把 key 和平台预热开关写入 `~/.hermes/.aigm-platform-prewarm.env`，权限为 `600`。`check_platform_prewarm.sh` 会读取这个 env 文件，创建临时测试 workspace，真实调用 `deepseek-v4-flash` 跑一次 message-only prewarm，再验证正式 act 是否消费 cache。

调用格式说明：

- `AIGM_PLATFORM_PREWARM_INTENT_BASE_URL=https://api.deepseek.com` 使用官方 OpenAI-compatible base URL。
- `rpg_engine.ai.provider` 会自动补成 `https://api.deepseek.com/chat/completions` 发起裸 HTTP 请求。
- 请求使用 bearer auth、JSON body、`response_format={"type":"json_object"}`。
- `deepseek-v4-flash` 会显式设置 `thinking={"type":"disabled"}`，优先保证内部意图识别轻量和低延迟。

接入真实 key 后，建议用 20-50 条真实 QQ/Hermes 小流量消息采样：

| 指标 | 目标 |
| --- | --- |
| prewarm hit-rate | 越高越好；先看是否能稳定 > 50%。 |
| prewarm worker average / p95 | 判断 deepseek-v4-flash 实际耗时。 |
| user-visible latency average / p95 | 判断玩家实际等待是否下降。 |
| drop reason 分布 | 重点看 `queue_full`、`ai_timeout`、`duplicate_message` 是否异常偏高。 |
| clarification rate | 低风险输入应下降；中高风险不应被错误放行。 |
| `ai_single_source_internal_fast` 命中率 | 观察低风险快通道是否真的减少无谓澄清。 |
| confirm save success rate | ready 后确认是否稳定保存，是否有 pending 冲突。 |

## Canary 操作建议

第一轮真实 canary 不要改 Hermes core。只让薄 adapter/sidecar 做三件事：

1. 首次成功游戏调用后激活 platform binding。
2. QQ MessageEvent 到达时调用 `PlatformSidecar.handle_message_event()`。
3. 正式玩家行动优先调用 `player_turn`；平台 sidecar 可调用 `player_act_from_message()` 这个兼容命名 facade，或透传同一组被动 preflight 标识。

先不要做 ACK/typing，不要多人共享存档，不要扩大到所有群。等 hit-rate、latency、drop reason 稳定后，再决定是否接体验层提示。

## 仍需观察

- `player_act_from_message()` 在一次性 CLI 诊断模式下可能再次尝试 enqueue 同一消息，当前会按 `duplicate_message` drop；真实长驻 adapter 应尽量先 `handle_message_event()`，正式 action facade 只消费被动标识并按 `player_turn` 语义执行。
- `metrics_snapshot()` 现在适合 canary 观察；高频生产路径后续可改为周期采样。
- 当前 pending action 是单 workspace 槽。单人游戏可接受；如果未来多平台/多会话并发，需要 scoped pending store。
