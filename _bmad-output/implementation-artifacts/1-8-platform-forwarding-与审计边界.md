---
baseline_commit: a3187b5d4870fa6e5e0671331193e679d2c87c44
---

# Story 1.8: Platform Forwarding 与审计边界

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 platform 集成者，
我希望 platform sidecar 只做 session/actor gate、preflight identity 转发和 SaveManager forwarding，
从而保证平台消息不会获得额外 gameplay fact authority。

## 验收标准

1. 给定 platform sidecar 收到带 session / actor identity 的玩家请求，当请求被转发到 Kernel 时，platform 层必须先执行 identity gate；gate 通过后只调用对应 SaveManager player-safe API，不直接调用 `GMRuntime` low-level preview/validate/commit、SQLite fact writes、action resolver 或 commit/projection internals。
2. 给定 platform `act` 从已绑定 platform message 进入玩家行动链，当它调用 SaveManager 时，必须使用绑定的 active save，并转发 passive preflight identity：`message_id`、`platform`、`session_key`、`actor_id`、`source_user_text_hash` 和 `preflight_pending_wait_ms`；message-only preflight 仍是 advisory，不能携带 external candidate、delta、proposal 或 commit approval。
3. 给定 platform gate 拒绝请求、SaveManager 返回成功/失败，或 sidecar 只处理 prewarm/message/metrics/maintenance 操作，当 platform audit logging 启用时，audit record 必须包含 sanitized request/result summaries、surface category、operation/status、identity 摘要和 duration，并且不得泄露 raw `session_key`、raw actor id、raw delta/proposal/validation internals、hidden/private key variants 或 AI private reasoning。
4. 给定 MCP audit logging 已启用，当 MCP 调用成功、失败或被权限门拒绝时，audit record 必须同样暴露 stable surface category、status、sanitized request/result summaries 和 identity 摘要；audit 写入失败不得中断已完成的 MCP operation，也不得提升 MCP profile、hidden read、preflight 或 commit authority。
5. 给定 platform 或 MCP audit 写入失败，当原本的 Kernel operation 已完成或 gate 已产生拒绝结果时，调用方必须收到原始 operation/gate 结果；audit failure 只能进入 stderr/log warning 或 result 外的非权威诊断，不能改变 gameplay facts、pending state、save facts、projection/outbox 或权限判断。

## 任务 / 子任务

- [x] 固化 platform sidecar gate-before-forwarding 合同。 (AC: 1)
  - [x] 复用现有 `PlatformSidecar.gate_player_entry()`、`platform_entry_gate()`、`platform_pending_conflict()`、`SaveManager.player_turn()` 和 `SaveManager.player_confirm()`；不要新增并行 platform 权限表、并行 pending 文件、并行 commit path 或 runtime shortcut。
  - [x] 增加/强化 `tests/test_platform_sidecar.py`，证明 inactive session、wrong actor、duplicate message、pending conflict 等 gate 拒绝发生在 SaveManager forwarding 之前。
  - [x] 增加 focused sentinel，证明 `player_act_from_message()` 和 `player_confirm_from_message()` 不直接调用 `GMRuntime.preview_action()`、`GMRuntime.validate_delta()`、`GMRuntime.commit_turn()`、`sqlite3.connect()` 写 gameplay state、action resolver 或 projection/outbox repair。
  - [x] 保持 `start_or_continue_from_message()` 只通过 SaveManager start/continue 边界激活 binding；不要把 platform start 变成 gameplay fact commit。

- [x] 固化 passive preflight identity forwarding。 (AC: 2)
  - [x] 保持 `PlatformPrewarmService.handle_message()` 和 `PrewarmWorker.process()` 的 `message_only` preflight 语义：`external_intent_candidate=None`，identity 包含 platform/session/message/source text hash。
  - [x] 为 `PlatformSidecar.player_act_from_message()` 添加或强化 monkeypatch/spy 测试，确认传给 `SaveManager.player_turn()` 的参数包括绑定 active save、`message_id`、`platform`、raw `session_key` 仅作为 service identity 输入、`actor_id`、`source_user_text_hash=hash_text(message.text)` 和 `preflight_pending_wait_ms`。
  - [x] 覆盖 bound-save 行为：即使 workspace active save 已切换，platform act/confirm 仍使用 binding 的 active save，不使用全局 active save 作为事实写入目标。
  - [x] 不允许 sidecar 接收 external/internal candidate、delta、proposal、human approval 或 hidden permission 参数；如果新增参数或 audit 字段，必须保持这些概念不可写入 SaveManager forwarding 输入。

- [x] 为 platform sidecar 增加结构化 audit evidence。 (AC: 3, 5)
  - [x] 在 `PlatformSidecarConfig` 或等价配置中加入可测试的 audit log path/disable 入口，默认位置应在 workspace runtime logs 下；若选择默认开启或仅在显式配置时开启，必须在 docs/tests 中写清楚。
  - [x] 让 platform sidecar public entry methods 通过统一 audit wrapper 或 helper 记录结果：`handle_message_event`、`start_or_continue_from_message`、`player_act_from_message`、`player_confirm_from_message`、`metrics_snapshot`、`expire_stale_bindings`、`deactivate_from_message`。如果某些方法不记录，必须在 Dev Agent Record 说明它们为什么不是本 story 的 audited operation。
  - [x] Audit record 至少包含：`created_at`、`surface_category` (`platform sidecar` 或 `platform prewarm`)、operation name、status (`ok` / `error` / `rejected` / `dropped` 等稳定值)、duration、identity summary、sanitized request summary、sanitized result summary。
  - [x] Sanitization 必须 hash raw session/user identity，保留 `message_id` 和 `platform` 这类低敏定位字段，summary raw text 时要截断；不得写 raw `session_key`、raw actor id、full pending delta、full `turn_proposal`、validation/projection internals、hidden/private key variants 或 AI private reasoning。
  - [x] Audit 写入失败必须被捕获并只产生 warning/stderr；不得改变 sidecar 返回结果、pending action、binding state、Save facts、projection/outbox 或 metrics authority。

- [x] 补齐 MCP audit surface/category 与 identity summary。 (AC: 4, 5)
  - [x] 复用现有 `AIGMMCPAdapter.call_with_audit()`、`write_audit_record()`、`sanitize_for_audit()` 和 `summarize_result_for_audit()`；不要新增第二套 MCP audit writer。
  - [x] 为 MCP audit record 增加 stable `surface_category` / profile authority evidence。分类应来自 `rpg_engine.surface_inventory.MCP_SURFACE_INVENTORY` 或等价 single source；不能靠散落字符串猜测工具权限。
  - [x] 增加 identity summary，至少覆盖 request 中出现的 `platform`、hashed `session_key`、`message_id`，以及 profile/tool/surface status；保持 current tests 对 raw session key、raw delta/proposal internals、private reasoning 和 hidden fields 的不泄露断言。
  - [x] 增加 audit writer failure test，证明 MCP tool 的成功/拒绝/错误结果不因 audit log path 不可写而改变。
  - [x] 不改变默认 `player` profile 权限门；`intent_preflight`、`preview_*`、`validate_delta`、`commit_turn` 仍不能被 player profile 调用。

- [x] 同步 surface inventory 与 canonical docs。 (AC: 1, 2, 3, 4, 5)
  - [x] 若新增/重命名 platform audit surface 或 helper 被视为 public/semi-public surface，更新 `rpg_engine/surface_inventory.py` 和 `tests/test_surface_inventory.py`；否则保持 helper 私有并在 tests 中避免误判。
  - [x] 更新 `docs/cli-contracts.md` 的 Platform 命令合同，说明 platform audit 只记录 sanitized evidence，不是事实源，且 audit failure 不阻断已完成 operation。
  - [x] 更新 `docs/mcp-contracts.md` 的 MCP audit 合同，说明 audit record 包含 surface category/status/identity summary，audit failure 不改变 tool result 或 profile gate。
  - [x] 更新 `docs/ai-intent-chain.md` 或 `docs/component-inventory.md`，仅在实现改变 platform prewarm/sidecar 或 audit contract 表述时同步；不要重复粘贴所有实现细节。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3, 4, 5)
  - [x] 先跑新增/修改的 RED 测试，确认缺口被测试抓住；如果当前行为已满足某项边界，只记录 “existing behavior locked by new test”，不要伪造失败。
  - [x] 最小 GREEN gate：`python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py tests/test_surface_inventory.py`。
  - [x] 未触碰 CLI platform rendering/config，因此无需追加 `tests/test_v1_cli.py`；platform coverage 已由 focused gate 覆盖。
  - [x] 未改变 SaveManager player workflow 或 pending identity contract，因此无需追加 `tests/test_save_manager.py` / `tests/test_platform_ai_simulation.py`；全量回归已覆盖相关现有套件。
  - [x] 未改变 AI intent/preflight consumption contract，因此无需追加 intent cluster 子集；全量回归已覆盖相关现有套件。
  - [x] 收尾运行 `git diff --check`；若 docs/story links 变化，运行 `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md`。

### Review Findings

- [x] [Review][Patch] 并发/重入 duplicate platform act/confirm 必须在 SaveManager forwarding 前预留 message id，且 reservation 需跨同 workspace 的 sidecar 实例可见，避免同一平台消息双推进。[rpg_engine/platform_sidecar.py:328]
- [x] [Review][Patch] platform start 入口必须先校验 actor identity、bot/self、message/chat type，再允许 SaveManager start/continue 激活 binding。[rpg_engine/platform_sidecar.py:265]
- [x] [Review][Patch] duplicate platform start message 必须在 SaveManager start/continue 前被预留/拒绝，避免重复 webhook 创建多个 save 或覆盖 binding。[rpg_engine/platform_sidecar.py:265]
- [x] [Review][Patch] platform/MCP audit sanitizer 必须摘要 external/internal intent candidate，并覆盖 camelCase/plural private/hidden key variants，避免外部 AI payload 或私密推理进入 audit。[rpg_engine/mcp_adapter.py:86]
- [x] [Review][Patch] platform/MCP audit 的 `errors`、`warnings`、文本 preview 等自由文本必须按 request/message raw identity 和 private/hidden marker 做 scrub，避免异常字符串泄露敏感内容。[rpg_engine/mcp_adapter.py:1124]
- [x] [Review][Patch] audited platform prewarm/start public operations 在下游抛异常时也必须写入 sanitized error audit record，并保持异常语义不被吞掉。[rpg_engine/platform_sidecar.py:235]
- [x] [Review][Patch] `player_act_from_message()` 内部 advisory prewarm 抛异常时不能阻断 SaveManager forwarding；必须降级为 dropped prewarm summary 并写入最终 act audit。[rpg_engine/platform_sidecar.py:362]

## 开发说明

### 来源上下文

- Epic 1 要求可信本地玩家写入闭环、surface authority、Save fact authority 和 platform/low-level 入口权限不混淆；Story 1.8 专门处理 platform sidecar forwarding 与 audit evidence 边界。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 1.8 原始 AC 要求 platform sidecar 收到带 session/actor identity 的玩家请求时先 gate，再只调用 SaveManager player-safe API；platform 或 MCP audit logging 必须记录 sanitized summaries、surface category、identity 摘要和 status，且 audit failure 不阻断成功的 Kernel operation。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-2 要求 public / semi-public surfaces 分类，包括 platform sidecar 和 platform prewarm；FR-16 要求 CLI/MCP/platform adapters 保持 thin wrapper 并调用 kernel services，不复制业务逻辑。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Execution-chain AD-1 要求 ordinary player writes 仍经 `SaveManager.player_turn()` -> pending action -> `SaveManager.player_confirm()` -> `GMRuntime.commit_turn()` validation/commit；AD-3 要求每个 public/semi-public surface 声明 category/write authority；AD-5 要求 platform/SaveManager/MCP 改动带 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。
- Foundation AD-8 固定 AI latency/prewarm 的降级边界：platform prewarm 可以异步产生 advisory preflight，但不能阻塞 fact commit 或削弱 inherited execution-chain gates。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Canonical AI intent docs 明确：Platform sidecar 只做消息归一化、session gate、prewarm enqueue 和被动身份转发；preflight cache 是 single-use、identity-bound、advisory；sidecar 不接收 external candidate、internal candidate、delta、proposal 或 commit approval。来源：`docs/ai-intent-chain.md`。
- Canonical CLI docs 明确：`platform message` 只处理平台消息和 advisory prewarm；`platform act` 转发到 player act/turn 语义；`platform confirm` 必须校验同一 platform/session/actor identity 后转发到 `player_confirm`。来源：`docs/cli-contracts.md`。
- Canonical MCP docs 明确：MCP audit 是证据和排障日志，不是事实源；`player` profile 不能注册或调用低层 preview/validate/commit/preflight 工具。来源：`docs/mcp-contracts.md`。

### 当前实现状态

- `PlatformSidecar.player_act_from_message()` 当前先调用 `gate_player_entry(message, kind="act")`；gate 拒绝时返回 `platform_gate_rejection()`，不会调用 SaveManager。gate 通过后才实例化 `SaveManager(self.root)`、检查 pending conflict、调用 `prewarm_service.handle_message()`，再调用 `manager.player_turn(...)`。来源：`rpg_engine/platform_sidecar.py`。
- `PlatformSidecar.player_confirm_from_message()` 当前先 gate，再调用 `manager.player_confirm(session_id=..., save_path=binding.active_save, platform=..., session_key=..., actor_id=...)`。来源：`rpg_engine/platform_sidecar.py`。
- `platform_entry_gate()` 当前检查 missing platform/session/message、inactive binding、platform/session mismatch、empty active save、expired、bot/self actor、missing/changed actor、unsupported message/chat、duplicate confirm/action、pending approval/clarification 和 command/empty text。来源：`rpg_engine/platform_sidecar.py`。
- `platform_pending_conflict()` 当前读取 SaveManager pending action/clarification，并拒绝跨 save/platform/session/actor 的 pending 冲突；这保护平台 session 不覆盖另一个 session 的 pending state。来源：`rpg_engine/platform_sidecar.py`。
- `PlatformSidecar.player_act_from_message()` 当前转发 `message_id`、`platform`、`session_key`、`actor_id`、`source_user_text_hash=hash_text(message.text)` 和 `preflight_pending_wait_ms` 到 `SaveManager.player_turn()`；还传入 sidecar config 中的 player intent AI settings。来源：`rpg_engine/platform_sidecar.py`。
- `PlatformPrewarmService.handle_message()` 当前按 binding、message identity、queue、feature flag、chat/message type、command/empty/pending state 等规则决定 enqueue/drop；`PrewarmWorker.process()` 以 `preflight_identity_profile="message_only"` 调用 runtime preflight，且 `external_intent_candidate` 为 `None`。来源：`rpg_engine/platform_prewarm.py` 与 `tests/test_platform_prewarm.py`。
- `GameSessionBindingStore` 当前把 session key 和 user id 存为 hash；`binding_to_public_dict()` 也只暴露 hashes 和 active save/path state。来源：`rpg_engine/platform_prewarm.py`、`rpg_engine/platform_sidecar.py`。
- `tests/test_platform_sidecar.py` 已覆盖 raw event normalization、inactive session gate、actor mismatch、message-only preflight hit、raw session/actor 不进入 pending/preflight/public result、duplicate message rejection，以及 bound save 不受全局 active save 切换影响。Story 1.8 应在此基础上补 audit 与 forwarding sentinel，而不是重写平台 flow。
- `AIGMMCPAdapter.call_with_audit()` 当前包住 callback，异常会转为 error dict；`write_audit_record()` 当前写 `created_at`、server、tool、duration、status、sanitized request、summarized result；写 audit 失败只 print stderr，不中断调用。来源：`rpg_engine/mcp_adapter.py`。
- `sanitize_for_audit()` 当前会 hash `session_key`，摘要 `delta`、`turn_proposal`、external/internal candidate、private reasoning、hidden facts 等敏感 payload，递归截断长文本；`summarize_result_for_audit()` 当前只摘取安全字段和 result previews。来源：`rpg_engine/mcp_adapter.py`。
- `tests/test_mcp_adapter.py` 已覆盖 MCP audit success/error、player profile 权限拒绝不写 gameplay state、permission audit 脱敏 raw session/delta/proposal/private/hidden 字段。Story 1.8 应增强 surface/category 和 audit failure 行为，不放松这些断言。
- `PLATFORM_SURFACE_INVENTORY` 当前覆盖 `PlatformSidecar.handle_message_event`、`start_or_continue_from_message`、`player_act_from_message`、`player_confirm_from_message`、`metrics_snapshot`、`expire_stale_bindings`、`deactivate_from_message` 和 `PlatformPrewarmService.handle_message`，并标记 platform sidecar/prewarm authority。来源：`rpg_engine/surface_inventory.py`。

### 前序故事情报

- Story 1.7 已完成 CLI `player` / `platform` / `mcp` thin adapter boundary：CLI platform 只构建 `PlatformSidecar` 并调用其方法；CLI mcp 只配置/启动 MCP adapter；`play` 保持 developer/trusted low-level。Story 1.8 不应把 platform/MCP 业务逻辑搬回 CLI handler。
- Story 1.6 已完成默认 MCP `player` profile 权限门：默认 profile 只暴露 player-safe tools；低层 `intent_preflight`、`preview_*`、`validate_delta`、`commit_turn` 等工具必须保持 developer/trusted/maintenance/admin profile gate。
- Story 1.5 已完成 projection/outbox evidence 边界：audit/projection/outbox artifacts 都不能成为 gameplay fact authority。Story 1.8 的 audit evidence 必须沿用这个原则。
- Story 1.4 已完成 Save fact authority 和 runtime state boundary：SQLite `data/game.sqlite` 是 current fact authority；registry/pending/projection/archive/preflight/MCP audit 不能覆盖 facts。
- Story 1.3/1.2 已完成 `SaveManager.player_confirm()` 和 `SaveManager.player_turn()` player-safe contracts；platform act/confirm 必须继续依赖这些 services。

### 架构合规要求

- Platform sidecar 是 edge adapter，不拥有 preview、validation、confirmation、commit、hidden access 或 save authorization。它可以 normalize message、gate session/actor、enqueue/drop prewarm、forward passive identity、render platform-safe result、记录脱敏 audit evidence。
- Platform prewarm 是 advisory/precompute path。`message_only` preflight 只能替代 live internal AI review call；命中后仍必须进入 arbiter/binder/resolver/preview/pending/confirm/commit guard。
- Audit record 是 evidence，不是事实源、权限源、rollback policy 或 approval source。Audit failure 不能改变 committed facts，也不能把 rejected operation 变成 allowed。
- MCP audit 与 platform audit 可以共享 sanitizer/pattern，但不要把 platform sidecar 变成 MCP adapter，或让 MCP 通过 platform audit 获得 profile bypass。
- Raw platform/session/actor identifiers 可以作为 service input 传给 SaveManager 做 identity binding，但不能以 raw 形态写入 public result、pending file、preflight record 或 audit logs。
- 新 helper 尽量保持私有函数；如果成为 public/semi-public surface，必须登记到 `surface_inventory.py`。

### 相关文件

- `rpg_engine/platform_sidecar.py`：Platform sidecar gate、SaveManager forwarding、binding activation、metrics、platform result rendering；主要实现落点。
- `rpg_engine/platform_prewarm.py`：message-only preflight、binding store、prewarm queue/worker、metrics；用于验证 advisory identity 和 raw identity hashing。
- `rpg_engine/game_session.py`：`PlatformMessage`、`GameSessionBinding`、hash/clean/text helpers、binding gate support types。
- `rpg_engine/save_manager.py`：player-safe `player_turn()` / `player_confirm()` / pending identity contract；不要复制逻辑到 sidecar。
- `rpg_engine/mcp_adapter.py`：MCP audit writer/sanitizer、profile gate、player_turn/player_confirm/low-level tools；MCP audit 增强落点。
- `rpg_engine/surface_inventory.py`：platform sidecar/prewarm 与 MCP surface taxonomy；新增 public surface 时同步。
- `docs/ai-intent-chain.md`：platform prewarm、message-only preflight、low-trust candidate 边界。
- `docs/cli-contracts.md`：Platform CLI sidecar contract。
- `docs/mcp-contracts.md`：MCP profile/audit contract。
- `docs/component-inventory.md`：platform sidecar/prewarm component summary；如实现职责文字变化则同步。
- `tests/test_platform_sidecar.py`：platform gate/forwarding/audit focused tests。
- `tests/test_platform_prewarm.py`：message-only preflight/advisory prewarm tests。
- `tests/test_mcp_adapter.py`：MCP audit/profile gate tests。
- `tests/test_surface_inventory.py`：platform/MCP surface taxonomy sentinel。
- `tests/test_v1_cli.py`：如果 CLI platform rendering/config 变化时追加。
- `tests/test_save_manager.py`、`tests/test_platform_ai_simulation.py`：如果 pending identity或 platform/AI flow 改动时追加。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py tests/test_surface_inventory.py
git diff --check
```

如果只改 docs/story artifacts：

```bash
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md
```

如果触碰 platform CLI config/rendering：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_platform_sidecar.py
```

如果触碰 SaveManager pending identity 或 player flow：

```bash
python3 -m pytest -q tests/test_save_manager.py tests/test_platform_sidecar.py tests/test_platform_ai_simulation.py
```

如果触碰 AI intent/preflight consumption：

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_preflight_cache.py tests/test_platform_prewarm.py tests/test_platform_sidecar.py
```

如果 implementation changes shared MCP/profile/intent/platform contracts broadly:

```bash
python3 -m pytest -q
```

### 残余风险与边界

- 本 story 不要求构建通用 audit subsystem、UI dashboard、remote telemetry、SIEM integration 或长期 audit retention policy；只要求 platform/MCP entry audit evidence 足够安全、稳定、可测。
- 不要让 audit result 成为 `SaveManager.player_confirm()` 的输入，也不要让 audit failure 触发 retry commit、projection repair 或 pending state mutation。
- 不要把 platform `act` 迁移到 `GMRuntime.act()` 或 `preview_from_text()` 低层入口；必须继续走 SaveManager player-safe path。
- 不要把 platform prewarm 改成默认 mandatory blocking path。AI 慢、队列满、drop 或 timeout 时必须安全降级到 normal processing 或安全拒绝。
- 不要为了方便 audit 而记录 raw session key、raw actor id、full prompt、full delta/proposal、hidden facts 或 private AI reasoning。
- MCP audit 已经存在；本 story 只补 category/status/identity evidence 和 failure tests，不重写 MCP adapter。

### 最新技术信息

无需外部 Web research。本 story 使用现有 Python stdlib、SQLite、pytest、platform sidecar/prewarm、MCP adapter audit helpers、surface inventory 和 docs contracts。不要新增运行时依赖。

## Project Structure Notes

Story 1.8 应优先增强 `platform_sidecar.py`、`mcp_adapter.py`、focused tests 和 canonical docs。保持 CLI 作为薄适配层、SaveManager 作为 player-safe gate、GMRuntime 作为内部 runtime/low-level kernel、MCP adapter 作为 profile-gated tool host。Audit helpers 应保持局部、可测试、可复用，但不要抽象成跨仓库框架。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-7-cli-命令薄适配边界.md`
- `_bmad-output/implementation-artifacts/1-6-mcp-player-profile-权限门.md`
- `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/ai-intent-chain.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/game_session.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/surface_inventory.py`
- `tests/test_platform_sidecar.py`
- `tests/test_platform_prewarm.py`
- `tests/test_mcp_adapter.py`
- `tests/test_surface_inventory.py`
- `tests/test_v1_cli.py`
- `tests/test_save_manager.py`
- `tests/test_platform_ai_simulation.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Implementation Plan

- 先写 platform/MCP audit 与 forwarding boundary tests，锁住 gate-before-forward、passive identity forwarding、sanitized audit 和 audit failure non-blocking。
- 最小实现 platform sidecar audit writer 与 MCP audit category/identity evidence；复用现有 sanitizer/patterns，不新增事实源或权限源。
- 同步 canonical docs 和 surface inventory（仅在 public/semi-public surface 变化时），运行 focused gates，再按实际触碰范围追加测试。

### Debug Log References

- DEV start: baseline commit `a3187b5d4870fa6e5e0671331193e679d2c87c44`; sprint status moved to `in-progress` at 2026-07-08T01:36:11+1000.
- RED: `python3 -m pytest -q tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_act_and_confirm_reject_inactive_session_before_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_act_forwards_bound_save_and_passive_identity_to_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_sidecar_writes_sanitized_audit_for_rejected_and_forwarded_calls tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_audit_write_failure_does_not_change_operation_result tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_adapter_writes_structured_audit_log_for_success_and_error tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_audit_write_failure_does_not_change_tool_result tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_player_profile_permission_audit_is_sanitized_and_summarized` failed with 4 expected failures: platform audit config missing and MCP audit missing `surface_category`/identity.
- GREEN: same focused test set passed after adding platform audit config/records and MCP audit metadata.
- Focused gate: `python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py tests/test_surface_inventory.py` passed with 62 tests and 221 subtests.
- Syntax gate: `python3 -m py_compile rpg_engine/platform_sidecar.py rpg_engine/mcp_adapter.py` passed.
- Docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md` passed, checking 87 markdown files.
- Whitespace gate: `git diff --check` passed.
- Full regression: `python3 -m pytest -q` passed with 524 tests and 638 subtests.
- CODE REVIEW: three review subagents completed. Acceptance Auditor reported no findings. Blind/Edge findings were deduplicated into 4 patch items; 2 false positives were dismissed because `player_query`/`player_act` are already low-level-only and current profile tests cover player rejection/registration.
- REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_start_rejects_actorless_event_before_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_duplicate_act_is_reserved_before_forwarding_to_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_duplicate_confirm_is_reserved_before_forwarding_to_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_prewarm_exception_is_audited_without_being_swallowed tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_start_exception_is_audited_without_being_swallowed tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_sidecar_writes_sanitized_audit_for_rejected_and_forwarded_calls tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_player_profile_permission_audit_is_sanitized_and_summarized` passed with 7 tests.
- REVIEW PATCH focused gate: `python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py tests/test_surface_inventory.py` passed with 67 tests and 221 subtests.
- REVIEW PATCH syntax gate: `python3 -m py_compile rpg_engine/platform_sidecar.py rpg_engine/mcp_adapter.py` passed.
- REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md` passed, checking 87 markdown files.
- REVIEW PATCH whitespace gate: `git diff --check` passed.
- REVIEW PATCH full regression: `python3 -m pytest -q` passed with 529 tests and 638 subtests.
- SECOND REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_duplicate_start_is_reserved_before_forwarding_to_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_duplicate_act_is_reserved_before_forwarding_to_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_duplicate_confirm_is_reserved_before_forwarding_to_save_manager tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_act_prewarm_exception_remains_advisory_and_audited tests/test_platform_sidecar.py::PlatformSidecarTests::test_platform_start_exception_is_audited_without_being_swallowed tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_audit_scrubs_sensitive_free_text_errors_and_warnings` passed with 6 tests.
- SECOND REVIEW PATCH focused gate: `python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py tests/test_surface_inventory.py` passed with 70 tests and 221 subtests.
- SECOND REVIEW PATCH syntax gate: `python3 -m py_compile rpg_engine/platform_sidecar.py rpg_engine/mcp_adapter.py` passed.
- SECOND REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md` passed, checking 87 markdown files.
- SECOND REVIEW PATCH whitespace gate: `git diff --check` passed.
- SECOND REVIEW PATCH full regression: `python3 -m pytest -q` passed with 532 tests and 638 subtests.
- FINAL CODE REVIEW: Blind Hunter returned `Clean`; Acceptance Auditor returned `Clean`; Edge Case Hunter returned `[]`.

### Completion Notes List

- Added opt-in `PlatformSidecarConfig.audit_log` support and private platform audit helpers that record surface category, operation status, duration, identity hashes, sanitized request summaries, and sanitized result summaries without changing platform gate or SaveManager forwarding behavior.
- Preserved platform sidecar authority: act/confirm still gate first, then forward only to `SaveManager.player_turn()` / `SaveManager.player_confirm()` with passive platform/message identity; prewarm remains advisory and message-only.
- Added MCP audit `surface_category` and identity summaries sourced from `MCP_SURFACE_INVENTORY`, while preserving existing audit sanitization and non-blocking audit failure behavior.
- Added focused tests for gate-before-SaveManager, passive identity forwarding, platform audit sanitization, audit write failure behavior, MCP audit category/identity, and MCP audit failure non-blocking.
- Applied review patches for cross-instance pre-forward duplicate reservation, actor-required/duplicate start gate, stronger audit sanitizer coverage, audit free-text scrub, exception-path audit evidence for platform prewarm/start, and advisory prewarm failure downgrade inside platform act.
- Synchronized `docs/cli-contracts.md`, `docs/mcp-contracts.md`, `docs/ai-intent-chain.md`, and `docs/component-inventory.md` with the audit evidence boundary.

### Change Log

- 2026-07-08: Implemented Story 1.8 platform forwarding and audit boundary; story moved to review.
- 2026-07-08: Applied code review patches and reran focused/full regression.
- 2026-07-08: Applied second-review patches and reran focused/full regression.
- 2026-07-08: Final review clean; story moved to done and sprint status synced.

### File List

- `_bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md`
- `_bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/ai-intent-chain.md`
- `docs/cli-contracts.md`
- `docs/component-inventory.md`
- `docs/mcp-contracts.md`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/platform_sidecar.py`
- `tests/test_mcp_adapter.py`
- `tests/test_platform_sidecar.py`
