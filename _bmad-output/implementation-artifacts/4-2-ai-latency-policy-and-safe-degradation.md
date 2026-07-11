---
baseline_commit: e2b1760f544d74aac4ddbfe560cdaa18bf7d9f39
---

# Story 4.2：AI 延迟策略与安全降级

Status: done

## Story

作为玩家，
我希望 AI-assisted turn 不会无界等待，
从而让慢速或不可用 AI 安全降级，而不是产生不安全提交或隐式改变意图权威。

## Acceptance Criteria

1. **Player-facing soft wait 有界且可观测**

   **Given** player-facing AI assistance 已启用
   **When** intent/helper call 超过配置的 soft wait target（默认约 8 秒）
   **Then** player-facing path 可以继续等待到 hard deadline、显示 fallback/clarification/pending wait，或走 non-AI safe processing，但必须记录结构化 `soft_wait_exceeded` / latency evidence
   **And** route、fact、hidden access、玩家确认与 commit authority 均不得改变。

2. **Hard timeout 覆盖一次 helper operation 的总预算**

   **Given** player-facing AI helper 配置 hard timeout（默认候选约 15 秒）
   **When** primary backend、可选 fallback backend、解析与 normalization 消耗该预算
   **Then** 整个 helper operation 共享同一 monotonic deadline，不能让 primary 和 fallback 各自重新获得完整 timeout
   **And** 超过 hard deadline 的结果必须被标记为 timeout/error 并丢弃，不得随后进入 arbitration、pending 或 commit。

3. **Enabled timeout/unavailable 不得被偷换为 off**

   **Given** internal intent AI 明确配置为 enabled/`consensus`
   **When** internal review soft-wait exceeded、hard timeout、provider error、fallback failure 或 unavailable
   **Then** trace 继续记录 `mode=consensus`，并通过现有 risk-aware safe fallback、clarification、blocked 或 no-AI policy 收敛
   **And** 该失败不得被解释为显式 `off`，不得让 external candidate 自动取得 `external_primary` route proposal authority。

4. **迟到结果没有追认权**

   **Given** player-facing call 已因 hard timeout 或安全降级完成
   **When** backend、worker、future 或 cache record 之后才返回 ready/result
   **Then** 迟到结果只能成为 timeout/late-discard evidence，不能替换本次 selected outcome、创建 pending、确认玩家或提交 facts
   **And** 下一次请求仍必须重新经过 identity、schema、arbiter、binder、resolver、preview、validation 与 confirmation gates。

5. **Background/preflight advisory 不阻塞事实提交**

   **Given** resident/background 或 platform prewarm advisory task 已调度
   **When** 它在 30-60 秒目标窗口内完成、超时、queue full、失败或 late-ready
   **Then** 它只产生 advisory result、drop reason、timeout/late evidence 或可重试状态
   **And** gameplay fact commit 不等待它，也不从它获得 confirmation、validation、proposal approval 或 commit authority。

6. **公开入口与事实边界保持不变**

   **Given** CLI、MCP、platform、Runtime 与 SaveManager 使用 AI latency policy
   **When** timeout 或降级发生
   **Then** adapters 继续调用既有 Kernel service，默认 MCP player profile 与 public parameter authority 不扩张，player-visible output 不泄露 raw prompt、hidden facts、delta/proposal 或 private AI reasoning
   **And** `data/game.sqlite` 仍是事实权威；`player_turn()` 最多产生 query/clarification/blocked/pending，只有匹配 `player_confirm(session_id)` 后才可能提交。

## Tasks / Subtasks

- [x] Task 1：先建立 latency contract characterization tests（AC: 1-5）
  - [x] 为 `InternalAIService` 覆盖 primary success、soft wait exceeded、primary timeout、fallback success、primary+fallback 总 deadline、late success discard、invalid timeout 与 audit evidence。
  - [x] 使用 fake backend/clock 或 monkeypatch 实现毫秒级 deterministic tests；不得用真实 8/15/30-60 秒 sleep，不得让 required suite 变 flaky。
  - [x] 证明 timeout detection 不依赖英文 error substring 作为唯一 authority；结构化 status/reason 必须可供 router、prewarm 与 audit 使用，同时保留现有错误文本兼容。

- [x] Task 2：在既有 AI helper 边界实现统一 latency policy（AC: 1, 2, 4）
  - [x] 在 `rpg_engine/ai/policy.py` / `defaults.py` 扩展现有 `AIHelperPolicy`，表达 player-facing soft target、hard deadline 与 background target window；不要创建第二套 timeout policy。
  - [x] 在 `rpg_engine/ai/provider.py` 使用 `time.monotonic()`/`perf_counter()` 计算单次 operation 的剩余 hard budget；direct 与 `hermes_z` fallback 必须共享预算。
  - [x] `AIHelperResult` / audit 增加最小结构化 latency evidence（例如 deadline class、soft exceeded、hard timeout、late discarded、configured targets），保持 `advisory=True`、`no_direct_writes=True`。
  - [x] 现有 `--intent-timeout` / `intent_timeout` 继续表示 caller 可配置的 hard budget，不新增 player per-call authority；默认值与文档统一为 hard timeout candidate，soft target 由 policy 独立表达。

- [x] Task 3：收紧 enabled intent timeout 的安全降级（AC: 2-4）
  - [x] 在 `rpg_engine/ai_intent/router.py` / `internal_review.py` 消费结构化 timeout/unavailable evidence；不得通过调用 `off` branch、伪造 external-only decision 或清空 mode 来降级。
  - [x] 复用 `apply_unavailable_internal_policy()` 与 `assess_rules_fallback()`；低风险 rules 可 fallback，高风险或 consensus-only action 必须 clarify/block。
  - [x] External candidate 存在时，enabled timeout 仍不得无条件采用 external；trace 明确 configured mode、helper outcome、fallback risk、route authority 与 selected outcome。
  - [x] 超过 hard deadline 后即使 backend 返回 schema-valid candidate，也不得进入 `normalize_intent_candidate()`、arbitration 或 adopted outcome。

- [x] Task 4：证明 preflight/background 与 player-safe boundary（AC: 4-6）
  - [x] 回归 `intent_preflight_cache` pending timeout、late-ready、single-use、identity/hash/provider/model mismatch；late cache 不能成为 proposal/permission cache。
  - [x] 回归 `PlatformPrewarmService` / queue 的 timeout、queue full、worker failure、late-ready drop reason；sidecar 正常 player turn/confirm 不被 prewarm latency 阻塞。
  - [x] 使用 temporary Save 证明 timeout/clarify/block/query 不修改 SQLite facts、events、pending 或正式 registry；ready action 仍只写 temp pending，匹配 confirm 后才 commit。
  - [x] 保持 `message_only` preflight 不携带 external candidate，platform sidecar 不新增 external candidate 或 commit 参数。

- [x] Task 5：同步 canonical docs 与 Prompt contract（AC: 1-6）
  - [x] 更新 `docs/project-context.md`、`docs/ai-intent-chain.md`、`docs/architecture.md`、`docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md` 与 `docs/prompts/ai-client-prompt.md`。
  - [x] 文档统一说明 soft wait、hard total deadline、background target、late discard，以及 `enabled timeout != off`；不得暗示 timeout 可授予 external、preflight 或 resident AI 权威。
  - [x] 只有 public/default contract 实际改变时才更新 CLI/MCP 示例；不新增依赖、schema、migration 或外部 GM Skill scope，除非实现证明现有 Skill 出现直接错误。

- [x] Task 6：从最终 clean diff 运行并记录全部 required gates（AC: 1-6）
  - [x] Story focused：AI provider/config/policy、intent/router/runtime/save/MCP/CLI/preflight/platform suites。
  - [x] Adjacent regression：platform simulation、current-native context/player-turn、context quality、surface inventory；所有写测试使用 temporary Save。
  - [x] Campaign：两个 canonical example 的 validate/test。
  - [x] Docs/static：Markdown links、changed Python `py_compile`、full Ruff、`git diff --check`。
  - [x] Repository full `pytest`；任何后续 patch 都使受影响旧绿灯失效，必须重跑。

### Review Findings

- [x] [Review][Patch] 用可及时返回的 execution boundary 强制整个 helper operation hard deadline，并在 transport/parse/normalization 阶段使用同一 absolute deadline [`rpg_engine/ai/provider.py`:127]
- [x] [Review][Patch] 区分 backend-attempt timeout 与 operation hard deadline；early timeout 有剩余预算时仍允许 fallback [`rpg_engine/ai/provider.py`:137]
- [x] [Review][Patch] 将 `URLError` wrapped timeout 与 HTTP 408/504 映射为结构化 timeout reason [`rpg_engine/ai/provider.py`:250]
- [x] [Review][Patch] 统一 hard/late result、failure reason 与 audit 顶层 status/error/output evidence [`rpg_engine/ai/provider.py`:562]
- [x] [Review][Patch] 使用 absolute deadline 实时计算 fallback 剩余预算，禁止从截断的 `elapsed_ms` 反推 [`rpg_engine/ai/provider.py`:616]
- [x] [Review][Patch] 保持 `ai_helper_result_to_dict()` 对旧 helper-like duck type 的兼容默认值 [`rpg_engine/runtime.py`:343]
- [x] [Review][Patch] 校验 latency policy 的非负数值与 background target 顺序 [`rpg_engine/ai/policy.py`:7]
- [x] [Review][Patch] temporary Save timeout 回归改用完整 authoritative snapshot 与 registry fingerprint [`tests/test_save_manager.py`:1219]
- [x] [Review][Patch] 补齐 soft-wait、exact enabled degradation、structured hard/late prewarm 与真实 deadline stage 测试 [`tests/test_ai_helper.py`:251]

#### Round 2

- [x] [Review][Patch] 用 bounded worker slots 防止 hard-timeout 后 daemon worker 无界累积，并在 worker 真正启动前重算 deadline [`rpg_engine/ai/provider.py`:723]
- [x] [Review][Patch] 传播 `contextvars` 并把 worker start/capacity failure 转为结构化降级 [`rpg_engine/ai/provider.py`:735]
- [x] [Review][Patch] hard/late discard 清空 raw payload，统一 audit elapsed/status/error，并保留显式 hard flag [`rpg_engine/ai/provider.py`:622]
- [x] [Review][Patch] 使用 effective soft target 并完整校验 timeout bounds、output limit 与 background window [`rpg_engine/ai/policy.py`:7]
- [x] [Review][Patch] 递归识别 nested `URLError` timeout reason [`rpg_engine/ai/provider.py`:802]
- [x] [Review][Patch] `summarize_ai_helper_result()` 保持 legacy helper-like duck-type 兼容 [`rpg_engine/ai_intent/router.py`:475]
- [x] [Review][Patch] prewarm 只把真实 boolean hard/late flags 当作 timeout authority [`rpg_engine/platform_prewarm.py`:463]
- [x] [Review][Patch] 用 Event 控制真实 late worker，避免固定 80ms wall-clock flaky assertion并验证 bounded cleanup [`tests/test_ai_helper.py`:400]
- [x] [Review][Patch] registry authority snapshot 只忽略允许更新的 play/inspect timestamps，不吞掉其他写入 [`tests/test_save_manager.py`:102]
- [x] [Review][Patch] 补齐 worker saturation、start failure、context propagation、explicit hard flag 与 strict prewarm coercion tests [`tests/test_ai_helper.py`:251]
- [x] [Review][Defer] 新 `player_turn` 清理已有 pending action 的生命周期策略 [`rpg_engine/save_manager.py`:449] — deferred, pre-existing；与 Story 4.1 已记录项重复确认

#### Round 3

- [x] [Review][Patch] 线程启动后重新计算 caller wait budget，并在 deadline 边界优先返回安全 timeout [`rpg_engine/ai/provider.py`:743]
- [x] [Review][Patch] 将普通 worker/provider exception 转为结构化 failure 并保留有剩余预算的 fallback [`rpg_engine/ai/provider.py`:788]
- [x] [Review][Patch] 脱敏 fallback primary audit 与 player-visible unavailable guard，禁止 transport body/private output 泄漏 [`rpg_engine/ai/provider.py`:960]
- [x] [Review][Patch] 分离 foreground/background bounded worker capacity，platform prewarm 默认使用 60 秒 background deadline且 player 保持 15 秒 [`rpg_engine/ai/provider.py`:59]
- [x] [Review][Patch] 强制 `max_output_chars` 为正整数并递归识别 timeout cause/context [`rpg_engine/ai/policy.py`:25]
- [x] [Review][Patch] primary annotation/deadline race 必须提升为 operation hard timeout [`rpg_engine/ai/provider.py`:152]
- [x] [Review][Patch] AI task parser 明确为 side-effect-free normalization contract并传播 background execution class [`rpg_engine/ai/tasks.py`:7]
- [x] [Review][Patch] worker saturation/start delay/exception/background isolation 测试使用受控 Event 清理，避免污染全局 slots [`tests/test_ai_helper.py`:522]
- [x] [Review][Patch] temporary Save no-mutation snapshot 纳入 events/save/snapshot/card projection files [`tests/test_save_manager.py`:83]

#### Round 4

- [x] [Review][Patch] 平台 CLI 显式 `--intent-timeout` 同时传播到 player hard budget 与 prewarm config，未显式配置时仍隔离 15/60 秒默认值 [`rpg_engine/cli_v1.py`:1204]
- [x] [Review][Patch] fallback failure 清空 raw/audit output，并让 route/runtime public helper evidence 仅暴露稳定 failure class [`rpg_engine/ai/provider.py`:1003]
- [x] [Review][Patch] prewarm worker result 脱敏 Runtime/provider error，保留结构化 timeout/failed/worker reason [`rpg_engine/platform_prewarm.py`:445]
- [x] [Review][Patch] 将 `copy_context()`、Thread 构造与 start 纳入同一安全释放边界，任何普通 setup exception 都结构化降级 [`rpg_engine/ai/provider.py`:773]
- [x] [Review][Patch] worker 中的 process-control `BaseException` 在 caller thread 重新抛出，不得伪装成 backend unavailable [`rpg_engine/ai/provider.py`:761]
- [x] [Review][Patch] background latency 使用独立 target status/classification，不误报 player 8 秒 soft wait，并明确 within/beyond window evidence [`rpg_engine/ai/provider.py`:633]
- [x] [Review][Patch] policy 拒绝超过 global max 的 background window，避免不可达配置 [`rpg_engine/ai/policy.py`:53]
- [x] [Review][Patch] policy 强制 advisory/fail-closed/no-direct-writes 三个安全不变量为 true [`rpg_engine/ai/policy.py`:24]
- [x] [Review][Patch] hard deadline parser 测试改为 Event 等待并放宽调度预算，避免慢 CI 的 20ms start race [`tests/test_ai_helper.py`:454]
- [x] [Review][Patch] worker start-delay 测试移除 wall-clock 上限，改验 fresh remaining budget 与 worker/slot 清理 [`tests/test_ai_helper.py`:660]

#### Round 5

- [x] [Review][Patch] 平台 CLI 的显式 `intent_timeout=0` 使用 None 判断传播，避免 truthiness 静默回退 environment timeout [`rpg_engine/cli_v1.py`:1197]
- [x] [Review][Patch] worker setup/start 控制异常使用锁保护的 slot lease exactly-once 释放，覆盖 Thread 已启动后中断竞态 [`rpg_engine/ai/provider.py`:773]
- [x] [Review][Patch] `normalize_timeout()` fail-closed 拒绝 non-finite、boolean 与非数值输入，避免 `OverflowError` 越过结构化降级 [`rpg_engine/ai/policy.py`:57]

#### Round 6

- [x] [Review][Patch] Event/Lock lease setup 移到 semaphore acquire 之前并结构化 setup failure，关闭 acquire 后保护边界前的 permit 泄漏窗口 [`rpg_engine/ai/provider.py`:778]
- [x] [Review][Patch] 用锁保护的 `worker_entered/start_cancelled` 状态机处理 Thread 已创建但 ident 未发布的 start interruption，取消 worker 不得执行 operation [`rpg_engine/ai/provider.py`:802]
- [x] [Review][Patch] public latency audit 使用字段、枚举与类型 allowlist，legacy helper 扩展字段不得携带 raw prompt/private reasoning [`rpg_engine/ai/provider.py`:1144]
- [x] [Review][Patch] 并发竞态测试使用无超时 Event gate 与 Thread join 建立 cleanup happens-before，避免慢 CI 自动放行 [`tests/test_ai_helper.py`:847]

#### Round 7

- [x] [Review][Patch] public helper 顶层 `failure_reason` 限定稳定枚举、`timeout_seconds` 限定 finite non-bool number，关闭 legacy duck-type payload 泄漏 [`rpg_engine/ai/provider.py`:1091]
- [x] [Review][Patch] malformed dict/list `failure_reason` 先做字符串类型核验，禁止 unhashable membership 打崩 public serialization [`rpg_engine/ai/provider.py`:1097]
- [x] [Review][Patch] Runtime preflight failure 的公开/缓存 error 使用脱敏 helper summary，不再写入 provider body/private error [`rpg_engine/runtime.py`:829]
- [x] [Review][Patch] fresh wait budget 测试用受控 remaining sequence 与 fake clock 取代真实 30/50ms timing window [`tests/test_ai_helper.py`:684]
- [x] [Review][Patch] `deadline_timeout_result()` 显式设置 hard timeout，精确浮点边界不得误分类为 backend timeout [`rpg_engine/ai/provider.py`:881]

#### Round 8

- [x] [Review][Patch] public helper 顶层与 audit metadata 仅接受稳定 scalar 类型，latency enum 先验字符串，禁止容器 payload 泄漏或 membership 崩溃 [`rpg_engine/ai/provider.py`:1093]
- [x] [Review][Patch] completed worker 的 `KeyboardInterrupt/SystemExit` 在 deadline 分类前重新抛出，不得误吞为 timeout [`rpg_engine/ai/provider.py`:859]
- [x] [Review][Patch] public latency 数值与 target window 强制 finite，禁止 NaN/Infinity 生成非标准 JSON 或序列化失败 [`rpg_engine/ai/provider.py`:1201]

#### Round 9

- [x] [Review][Patch] timeout/policy 对任意精度整数不经 float 转换并安全 clamp，public evidence 拒绝超过 JSON safe integer 的数值 [`rpg_engine/ai/policy.py`:10]
- [x] [Review][Patch] public nested `primary_audit` 使用 visited/depth guard，cyclic 或超深 legacy audit 不得触发递归崩溃 [`rpg_engine/ai/provider.py`:1162]
- [x] [Review][Patch] prewarm Runtime result 的 `ok` 仅接受真实 boolean `True`，字符串 `"false"` 不得伪装成功 [`rpg_engine/platform_prewarm.py`:476]
- [x] [Review][Patch] 修复新增 policy numeric helper 的定义顺序，default policy 初始化与 CLI import 必须稳定 [`rpg_engine/ai/policy.py`:10]
- [x] [Review][Patch] Story File List 同步实际 CLI/runtime test diff，BMAD 实现记录保持完整 [`4-2-ai-latency-policy-and-safe-degradation.md`:333]

#### Round 10

- [x] [Review][Patch] `hermes_z` 的 `TimeoutError` 通过 timeout cause 分类为结构化 backend timeout，不得退化为普通 unavailable [`rpg_engine/ai/provider.py`:423]
- [x] [Review][Patch] custom policy 的 global hard timeout 上限保持 120 秒，禁止任意大 deadline 在 float 加法时溢出 [`rpg_engine/ai/policy.py`:45]
- [x] [Review][Patch] public finite float 同样不得超过 JSON safe-number 上限，numeric evidence 规则保持一致 [`rpg_engine/ai/provider.py`:1252]
- [x] [Review][Patch] prewarm 先严格判定 boolean `ok` 再推导缺省 status，truthy 字符串不得得到 `ready` [`rpg_engine/platform_prewarm.py`:466]
- [x] [Review][Patch] worker saturation/background isolation 测试使用受控 remaining budget 与 start condition，移除真实 10ms 调度窗口 [`tests/test_ai_helper.py`:652]

#### Round 11

- [x] [Review][Patch] preflight failed transition 在 TTL expired/raced 时返回最终状态并保留 structured helper timeout，不得被 platform 重分类为 worker error [`rpg_engine/preflight_cache.py`:261]
- [x] [Review][Patch] preflight late-ready success 在 TTL expired/raced 时返回最终状态、不写 internal review authority，并生成 advisory late evidence [`rpg_engine/preflight_cache.py`:208]

#### Round 12

- [x] [Review][Patch] expired transition 的 CAS 丢失竞态必须重读 SQLite 最终状态，不得返回与事实行不一致的伪造 `expired` [`rpg_engine/preflight_cache.py`:244]
- [x] [Review][Patch] prewarm public `status/preflight_id` 只接受稳定字符串，复合 malformed metadata 不得被字符串化泄漏 [`rpg_engine/platform_prewarm.py`:468]
- [x] [Review][Patch] hard parser deadline 测试使用无超时 Event gate 与 finally cleanup，移除 1 秒自动放行竞态 [`tests/test_ai_helper.py`:514]
- [x] [Review][Patch] prewarm 成功必须同时满足 boolean `ok=True` 与 `status=ready`，矛盾 failed/expired/rejected 组合 fail closed [`rpg_engine/platform_prewarm.py`:476]

#### Round 13

- [x] [Review][Patch] failure transition 丢失到 authoritative `ready` 时从 SQLite 重建一致 ready result；无有效 review 则 fail closed，禁止 `ready+ok=False` [`rpg_engine/runtime.py`:830]
- [x] [Review][Patch] public helper task 使用已知任务 allowlist，任意敏感 scalar task metadata 归一为 `ai helper` [`rpg_engine/ai/provider.py`:1095]
- [x] [Review][Patch] prewarm `preflight_id` 使用格式 allowlist且 false-ready 归一为 failed，敏感任意字符串不得进入 public result [`rpg_engine/platform_prewarm.py`:480]

#### Round 14

- [x] [Review][Patch] failure→ready authoritative rebuild 同时校验 SQLite status、expires_at 与 review，并返回权威 expiry；过期 ready fail closed [`rpg_engine/runtime.py`:836]
- [x] [Review][Patch] 非成功 prewarm 结果无论 ID 格式是否合法都清空 `preflight_id`，失败 advisory 不暴露 cache handle [`rpg_engine/platform_prewarm.py`:512]
- [x] [Review][Patch] public backend/provider/model 仅接受短 identifier 字符集，敏感任意字符串 metadata 不得进入 player output [`rpg_engine/ai/provider.py`:1243]
- [x] [Review][Patch] public preflight ID 只接受 canonical `preflight:` + 32 位小写 hex [`rpg_engine/platform_prewarm.py`:781]
- [x] [Review][Patch] policy min/max hard timeout 强制整数，禁止 float bound 经 `int()` 截断后低于配置下界 [`rpg_engine/ai/policy.py`:45]

#### Round 15

- [x] [Review][Patch] nested/primary public audit 的 task 复用顶层语义 allowlist，格式合法的敏感未知 task 不得绕过 [`rpg_engine/ai/provider.py`:1159]
- [x] [Review][Patch] semantic helper 只向 player context 保存 public-sanitized error/audit，HTTP body/private reasoning 不得进入 JSON/Markdown [`rpg_engine/context/semantic.py`:25]
- [x] [Review][Patch] router trace 与 ContextBuildState 使用统一 bounded `normalize_timeout()`，超大 caller integer 不得造成证据不一致或 JSON 崩溃 [`rpg_engine/ai_intent/router.py`:99]

#### Round 16

- [x] [Review][Patch] success ready CAS loser 重读并校验 SQLite authoritative status/expiry/review，返回 winner review而非 losing late result [`rpg_engine/runtime.py`:798]
- [x] [Review][Patch] prewarm 只有 `ok=True + status=ready + canonical preflight_id` 才成功；缺 handle 的 ready fail closed [`rpg_engine/platform_prewarm.py`:476]

#### Round 17

- [x] [Review][Patch] authoritative ready result 不附带当前 helper audit，即使 winner/loser review payload 相同也不得把 losing evidence 追认为权威 [`rpg_engine/runtime.py`:858]
- [x] [Review][Patch] prewarm 缺失/未知 status 不得由 truthy `ok` 推断 ready，必须显式 `status=ready` [`rpg_engine/platform_prewarm.py`:469]
- [x] [Review][Patch] ready result 携带 structured timeout/hard/late evidence 时 fail closed 为 `ai_timeout` 并清空 handle [`rpg_engine/platform_prewarm.py`:493]
- [x] [Review][Patch] Story File List 补齐 semantic/context builder 与 low-level coverage 实际 diff [`4-2-ai-latency-policy-and-safe-degradation.md`:400]

#### Round 18

- [x] [Review][Patch] authoritative ready 重读发现 used/rejected/pending 时返回 SQLite 最终状态，不得固定伪造 failed [`rpg_engine/runtime.py`:819]
- [x] [Review][Patch] public backend 使用稳定 enum，provider/model 不在 player helper evidence 回显，格式合法的敏感 identifier 也不得泄漏 [`rpg_engine/ai/provider.py`:1128]
- [x] [Review][Patch] public helper/audit 的 advisory 与 no-direct-writes flags 固定为 true，malformed legacy false 不得暗示写权限 [`rpg_engine/ai/provider.py`:1134]
- [x] [Review][Patch] 撤销被后续 patch 失效的 Task 6 门禁勾选，等待最终 clean diff 全量重跑后再完成 [`4-2-ai-latency-policy-and-safe-degradation.md`:89]

#### Round 19

- [x] [Review][Patch] HTTP transport/subprocess 启动前重新计算 absolute deadline remaining 并 clamp timeout，过期请求不得继续占用外部资源或 worker slot [`rpg_engine/ai/provider.py`:304]

#### Round 20

- [x] [Review][Patch] Runtime preflight failure error 只从 public helper summary 生成；空 public error 不得回退读取 raw helper status并写入响应/cache [`rpg_engine/runtime.py`:863]

#### Round 21

- [x] 三路 fresh review 收敛：Acceptance Auditor 与 Edge Case Hunter clean；Blind Hunter 仅重复 `Thread.start()` 人工阻塞 finding。
- [x] [Review][Dismiss] 把 Python thread runtime setup 改成预启动 executor 超出 AC2 明列的 backend/fallback/parse/normalization 与 P0 无新 async architecture 边界；真实 transport/process start 已在 Round 19 做 deadline freshness guard。

## Dev Notes

### 当前实现与预期改动

- `rpg_engine/ai/defaults.py` / `ai/config.py` / `ai/policy.py`
  - 当前：`DEFAULT_INTENT_TIMEOUT_SECONDS=8`，`AIHelperSettings.intent_timeout` 只有一个 timeout 值；`AIHelperPolicy` 只做 3-120 秒 clamp，没有 soft/hard/background 语义。
  - 改动：在同一 policy family 中表达 8 秒 soft target、15 秒 hard candidate 和 30-60 秒 background target；避免把软目标错误实现成第二个 permission/route mode。
  - 保留：CLI/MCP profile gate、backend/provider/model 配置和最小 timeout clamp。

- `rpg_engine/ai/provider.py`
  - 当前：direct primary 失败后，fallback 再使用完整 `effective_timeout`，一次 helper operation 最坏可等待两倍预算；result audit 有 elapsed/error，但没有结构化 deadline classification。
  - 改动：primary/fallback 共用总 deadline，任何 deadline 后的 valid payload 都 fail closed；输出可区分 soft exceeded、hard timeout、late discard。
  - 保留：schema validation、normalizer、output size、API key、provider-specific payload 与 no-write/advisory contract。

- `rpg_engine/ai_intent/router.py`
  - 当前：enabled helper 失败会追加 unavailable guard，并用 `apply_unavailable_internal_policy()` 进行 risk-aware fallback；Story 4.1 已使 `off + external` 走 `external_primary`。
  - 改动：结构化识别 timeout/late-discard，并证明 `mode=consensus` 与 route authority 不被改写。
  - 保留：Story 4.1 的三分支 mode matrix、shared candidate validation、binder/resolver/preview/confirm/commit gates。

- `rpg_engine/preflight_cache.py` / `platform_prewarm.py` / `platform_sidecar.py`
  - 当前：已有 pending wait timeout、late-ready、queue/drop reason 和 background worker；prewarm 是 advisory optimization。
  - 改动：优先复用并补强结构化 timeout evidence/tests，不把测试编排塞进 production API。
  - 保留：TTL、identity/hash/provider/model binding、single-use、`message_only` 隔离与 sidecar thin forwarding。

### 架构与范围护栏

- P0 不变量：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- Internal AI enabled 时 timeout/unavailable 仍是 enabled mode 的 helper failure，不是显式 `off`。
- Timeout 是 execution control，不是 route/fact/permission/confirmation/commit authority。
- 不新增依赖，不引入 async framework、distributed jobs、`IntentCoordinator`、Resident Advisory Envelope 或新 queue；Story 4.3-4.7 保持后续范围。
- 不改 Campaign/Save schema、SQLite migration、TurnProposal、validation profile、CommitService 或 projection authority。
- 不直接修改 source Campaign、formal current Save、正式 registry；write tests 全部使用 `tmp_path`/temporary Save copy。
- Hidden/GM-only 内容不得进入 player-visible timeout/fallback message、audit summary、trace 或 Prompt。

### 测试要求

Focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ai_helper.py \
  tests/test_ai_intent.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_mcp_adapter.py \
  tests/test_v1_cli.py \
  tests/test_preflight_cache.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_sidecar.py \
  -p no:cacheprovider
```

Adjacent regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_platform_ai_simulation.py \
  tests/test_current_native_player_turn.py \
  tests/test_current_native_context.py \
  tests/test_context_quality.py \
  tests/test_current_native_visibility.py \
  tests/test_surface_inventory.py \
  -p no:cacheprovider
```

Campaign / docs / static / final：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m py_compile <all changed Python and test files>
python3 -m ruff check .
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

### Previous Story Intelligence

- Story 4.1 已落地并通过 17 轮收敛：`enabled + external` 保持 arbitration；`off + valid external` 使用 `external_primary`；`off + no external` 保持 deterministic fallback。
- 本 Story 最关键的回归护栏是：enabled helper timeout/unavailable 不得落入 `off + external` 分支；route authority 应保持 risk-aware Kernel policy，而不是 external-primary。
- Story 4.1 的 review 曾发现 route authority ordering、single-source candidate validation、query/action/composite shape 与 stale gate evidence 等问题；本 Story 不得绕过这些 shared validation，也不得复用被 patch 失效的旧绿灯。
- 最近提交 `e2b1760` 修改了 intent arbiter/router/Runtime 与相关 tests/docs；延迟改动必须建立在这些最终形状上，不回滚或复制旧路由逻辑。

### Project Structure Notes

- 优先修改现有 `rpg_engine/ai/` policy/provider 与 `ai_intent/router.py`；只有证据证明必要时才触碰 Runtime/SaveManager/adapters。
- 新测试优先加入现有 `tests/test_ai_helper.py` 与 intent/preflight/platform suites；不要新增仅用于编排 production 行为的测试 API。
- Story artifact 与 validation report 位于 `_bmad-output/implementation-artifacts/`；canonical docs 留在 `docs/`。
- 无 UX artifact；本项目是 CLI/MCP/kernel-first，本 Story 不新增 UI。
- 无需 latest-tech Web research：不新增或升级 library/framework/external API；实现只依赖 Python 3.11+ 标准库既有 `time`、`subprocess` 与 `urllib` timeout 语义。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 4.2: AI Latency Policy and Safe Degradation`]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md#FR-6: 降低 AI 参与时的玩家等待`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md#AD-8 - 延迟策略只能安全降级，不能转移权威 [ADOPTED]`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-10.md#3. 影响分析`]
- [Source: `_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.md#Previous Story Intelligence`]
- [Source: `docs/project-context.md#不可破坏边界`]
- [Source: `docs/ai-intent-chain.md#Cache hit 规则`]
- [Source: `docs/testing-and-quality-gates.md#AI intent / platform / SaveManager 高风险 cluster`]

## BMAD Provenance

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`；从 sprint status 选择下一个 backlog story。
- Catalog 路由：`[CS] Create Story`，`bmad-create-story:create`，BMM implementation phase，required。
- Skill：`.agents/skills/bmad-create-story/SKILL.md` 已完整读取。
- Customization resolver：成功；prepend/append 为空；persistent fact 为 `file:{project-root}/**/project-context.md`；`on_complete` 为空。
- Config：`_bmad/bmm/config.yaml`；`communication_language=Chinese`，`document_output_language=Chinese`，artifact roots 已解析。
- 执行文件：`discover-inputs.md`、`template.md`、`checklist.md` 已完整读取；create workflow steps 1-6 按顺序执行。
- 输入：完整 sprint status、epics、PRD、architecture spines、获批 Sprint Change Proposal、previous Story 4.1、canonical docs、现有 AI provider/policy/router/preflight/platform 代码与最近 5 个 commit。
- 完成说明：Ultimate context engine analysis completed - comprehensive developer guide created。
- Code Review 路由：`[CR] Code Review`，`bmad-code-review`；skill 已完整读取，customization resolver 成功，prepend/append/on_complete 为空，persistent fact 为 `docs/project-context.md`，steps 1-4 按顺序执行。

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- RED：新增 latency policy/result/deadline tests 首次 collection 因缺少新 constants 失败；新增 enabled timeout 与 structured prewarm tests 首次得到 2 个预期失败。
- GREEN：实现 8 秒 soft evidence、15 秒默认 hard total budget、30-60 秒 background target、late discard 与 structured timeout reason；定点测试转绿。
- Focused：`297 passed, 164 subtests passed`。
- Adjacent/current-native：`100 passed, 9180 subtests passed`。
- Campaign：两个 canonical example 的 validate/test 均 exit 0。
- Docs/static：175 个 Markdown 文件链接通过；changed Python `py_compile`、full Ruff、`git diff --check` 均通过。
- Repository full suite：`812 passed, 9707 subtests passed`。
- Review Round 1：三路 reviewer 全部返回；去重/复现后自动应用 9 个 Patch，dismiss 3 个噪声/合并细节，Decision/Defer 0；patch-focused `189 passed, 164 subtests passed`，Ruff 与 diff check 通过。
- Review Round 2：三路 reviewer 全部返回，Acceptance Auditor clean；去重/复现后自动应用 10 个 Patch、重申 1 个 pre-existing Defer、dismiss 6 个噪声，Decision 0；patch-focused `193 passed, 168 subtests passed`，Ruff 与 diff check 通过。
- Review Round 3：三路 reviewer 全部返回；去重/复现后自动应用 9 个 Patch、dismiss 5 个噪声，Decision/Defer 0；完整 focused `308 passed, 176 subtests passed`，Markdown links、full Ruff 与 diff check 通过。
- Review Round 4-20：持续使用每轮三路 fresh Blind/Edge/Acceptance reviewer；去重、复现与 AC/范围核验后累计自动应用 64 个后续 Patch（全 Story 共 92 个），无 Decision，重申 1 个 pre-existing Defer；每轮 patch 后重跑受影响 gates。
- Review Round 21：三路收敛为 clean / correctly dismissed；Acceptance 与 Edge clean，Blind 仅重复已核验越界的 thread-runtime setup finding。
- Final focused：`319 passed, 190 subtests passed in 48.57s`。
- Final adjacent/current-native：`100 passed, 9180 subtests passed in 346.20s`。
- Final Campaign：两个 canonical example 的 validate/test 均 OK。
- Final docs/static：175 个 Markdown 文件链接通过；changed Python `py_compile`、full Ruff、`git diff --check` 均通过。
- Final repository full suite：`834 passed, 9733 subtests passed in 514.84s`。

### Implementation Plan

- 复用现有 `AIHelperPolicy` / `InternalAIService`，用 monotonic total budget 约束 primary 与 fallback。
- 通过 `AIHelperResult` 和 audit 传播结构化 timeout evidence；router/prewarm 消费 reason，不新增第二套业务路径。
- 保持 Story 4.1 mode matrix、player-safe pending/confirm、preflight identity/single-use 与事实权威边界。

### Completion Notes List

- 实现统一 latency policy：8 秒 soft wait evidence、15 秒默认 hard total deadline、30-60 秒 background advisory target。
- Direct primary 与 fallback 共用总 budget；hard deadline 后的 schema-valid payload 也会 `late_discarded`，不能进入 routing/pending/commit。
- Enabled internal review timeout 保持 `mode=consensus` 并走 risk-aware fallback/clarify/block，不会变成 `off` 或 `external_primary`。
- Platform prewarm 优先消费结构化 timeout reason；保留现有错误文本兼容、message-only、single-use 与 thin-forwarding 边界。
- 使用 temporary Save 证明 non-fast consensus timeout 不修改 facts/events/entities/clocks，也不创建 pending。
- Canonical docs 与 AI Client Prompt 已同步；无新依赖、schema、migration 或外部 GM Skill 变更。
- ✅ Resolved Review Round 1：hard execution boundary、absolute fallback budget、early/wrapped/HTTP timeout、audit 一致性、duck-type compatibility、policy validation、完整 Save/registry evidence 与精确 latency tests 共 9 项。
- ✅ Resolved Review Round 2：bounded worker、deadline-before-start、context propagation、worker failure、raw/audit cleanup、effective soft/policy bounds、nested timeout、legacy summary、strict boolean、event-driven tests 共 10 项；pending lifecycle 继续 defer。
- ✅ Resolved Review Round 3：fresh wait budget、deadline race、structured exception/fallback、audit/guard redaction、foreground/background isolation、60 秒 prewarm、policy/cause validation、parser contract、projection evidence 与 deterministic cleanup 共 9 项。
- ✅ Resolved Review Round 4-20：继续自动收敛 latency boundary、worker lease/CAS、public/semantic redaction、prewarm fail-closed、TTL/late-ready、numeric/metadata validation 与 deterministic tests；全 Story 共应用 92 个 Patch。
- ✅ Review Round 21 clean / correctly dismissed；最终 clean diff 的全部 required gates 通过。

### File List

- `_bmad-output/implementation-artifacts/4-2-ai-latency-policy-and-safe-degradation.md`
- `_bmad-output/implementation-artifacts/4-2-ai-latency-policy-and-safe-degradation.validation-report.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/project-context.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `rpg_engine/context/semantic.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/ai/__init__.py`
- `rpg_engine/ai/defaults.py`
- `rpg_engine/ai/policy.py`
- `rpg_engine/ai/provider.py`
- `rpg_engine/ai/tasks.py`
- `rpg_engine/ai_intent/internal_review.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/cli_v1.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/preflight_cache.py`
- `rpg_engine/runtime.py`
- `tests/test_ai_helper.py`
- `tests/test_ai_intent.py`
- `tests/test_low_level_condition_coverage.py`
- `tests/test_platform_prewarm.py`
- `tests/test_preflight_cache.py`
- `tests/test_runtime.py`
- `tests/test_save_manager.py`
- `tests/test_v1_cli.py`

### Change Log

- 2026-07-11：Create Story 生成完整实现上下文，状态设为 ready-for-dev。
- 2026-07-11：完成 AI latency policy、total deadline、late discard、enabled-mode safe degradation、prewarm evidence、temporary Save 回归与 canonical docs 同步；全部 Dev Story 门禁通过，状态转为 review。
- 2026-07-11：Code Review Round 1 自动应用 9 个明确 patch；patch-focused、Ruff 与 diff check 通过，等待 fresh Round 2 review。
- 2026-07-11：Code Review Round 2 自动应用 10 个明确 patch并重申 1 个 pre-existing defer；patch-focused、Ruff 与 diff check 通过，等待 fresh Round 3 review。
- 2026-07-11：Code Review Round 3 自动应用 9 个明确 patch；完整 focused、Markdown links、Ruff 与 diff check 通过，等待 fresh Round 4 review。
- 2026-07-11：Code Review Round 4-20 持续三路 fresh review、自动应用全部有效 patch并重跑受影响 gates；累计 92 个 Patch，无 Decision。
- 2026-07-11：Code Review Round 21 收敛 clean / correctly dismissed；最终 focused、adjacent、Campaign、docs/static 与 full suite 全绿，Story 状态设为 done。
