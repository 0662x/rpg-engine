---
baseline_commit: ee021b4c8d6c38206940335e6b9ecf5a7a726cab
---

# Story 6.4：原子 Pending Confirmation Claim 与 Replay 分类

Status: done

## Story

作为玩家主持者，
我希望 pending confirmation 具备原子 claim 和稳定的 replay 结果，
从而并发或重试确认不会报告多个 fresh commit，也不会重复写入事实。

## Acceptance Criteria

1. **并发确认只有一个 fresh commit**
   - Given 两个 caller 并发确认同一个有效 pending session，when `SaveManager` claim 并提交 proposal，then 恰好一个 caller 收到 `write_status=committed`，另一个收到 `write_status=already_confirmed` 且 `idempotent_replay=true`。
   - Atomic claim 必须覆盖 direct Python、MCP、CLI 与 platform forwarding 的共享 `SaveManager` owner，并在本地多线程、多进程下成立；不得只在某个 adapter 或单个进程内加锁。
   - SQLite 只能出现一次逻辑 turn/event/fact transition；backup、archivist、projection/outbox、registry refresh、platform saved metrics 等 fresh-only 外围副作用也不得因 replay 重复执行或重复计数。

2. **Commit 后、pending clear 前崩溃可恢复**
   - Given SQLite commit 已成功但进程在 pending state 清除前失败，when 同一 save、identity、confirmation session、command 与 proposal payload 重试，then `SaveManager` 与 CommitService 从现有 SQLite command/event evidence 分类为 `already_confirmed`，返回 `idempotent_replay=true`，安全 reconcile pending/claim state，且不再次报告 fresh commit。
   - 正常成功并已清除 pending 后，同一确认重试仍必须得到同一个稳定 replay 分类；不能退化为通用 `no pending player action`。
   - Recovery 必须用真实 subprocess 或等价 crash-window evidence 证明；测试不得在 production API 中加入 failpoint、barrier 或专用编排入口。

3. **Replay identity 与 payload 不匹配 fail closed**
   - Given replay 的 active/bound save、confirmation session、platform/session/actor identity、command id/hash、delta 或 proposal digest 任一不匹配，when confirmation 被尝试，then 返回结构化 conflict，或保留现有明确 save/session/platform/actor mismatch 错误；绝不能返回 idempotent success。
   - Replay receipt/entry evidence 必须 bounded、可校验、只保存必要 identity/digest/turn result，不保存 raw player text、raw delta、raw proposal、raw session key、raw actor id、hidden/GM-only 内容或 private AI material。
   - Malformed、tampered、stale 或无法与 SQLite `turns.command_id` / `command_hash` 和 authoritative event/turn evidence 对账的 receipt 必须 fail closed，不能覆盖 SQLite 事实或授予确认/commit authority。

4. **既有权威、兼容与范围边界不变**
   - `player_turn()` 仍只产生 query/clarification/blocked/pending，不提交事实；`player_confirm()` 仍是普通玩家 commit gate，validation、approved `TurnProposal`、write guard 与 `data/game.sqlite` 事实权威不变。
   - Same command + same payload 才可分类 replay；same command + different payload 继续 conflict，stale `expected_turn_id` 的 fresh write 继续拒绝，失败写入继续保留 pending（expiry 除外）并清理 pre-commit backup。
   - 保留 Story 1.3 已锁定的 bound-save 行为：显式 `save_path` 可在 active save 切换后确认原 pending；不匹配 replay 不能借此改写另一个 Save。
   - External/internal AI 仍没有事实、玩家确认、proposal approval 或 commit authority；CLI/MCP/platform 只薄转发或展示 Kernel classification，不复制 claim/replay 业务逻辑。
   - 本 Story 不实现 Story 6.5 的 compare-and-supersede、cancel、clarification TTL/correction、save-switch/orphan lifecycle，不实现 6.6 preflight purpose、6.7 audit reconstruction、6.8 Hermes fixture，不新增 Coordinator、多人/云/distributed 服务、依赖或测试专用 production API。
   - 所有写测试使用 temporary Campaign/Save/workspace；source Campaign、formal current Saves、正式 workspace registry 与用户 `data/game.sqlite` 不得被修改。

## Tasks / Subtasks

- [x] Task 1：定义 fresh/replay/conflict 结果合同并锁定当前缺陷（AC: 1, 2, 3, 4）
  - [x] 增加 characterization test，重现两个并发 caller 都报告 `committed`、但 SQLite 只有一个 turn/event 的当前行为；测试先红后实现。
  - [x] 为 CommitService/Runtime/SaveManager 结果定义 machine-readable `write_status=committed|already_confirmed` 与 `idempotent_replay: bool`；合法 replay 的 `ok` 必须为 true，但不得被描述为 fresh save。
  - [x] 明确 `saved`、player message、projection status 与 warnings/errors 的 replay 语义，使 CLI/MCP/platform client 能避免重复叙事或外围副作用；不在 adapter 重新分类。
  - [x] 保留 low-level 未确认/伪造 `TurnProposal` 的拒绝边界；idempotent classification 不得成为绕过 `human_confirmed`、validation 或 profile gate 的入口。

- [x] Task 2：在 SaveManager owner 内实现跨进程 atomic confirmation claim（AC: 1, 2, 3, 4）
  - [x] 对 workspace 单一 pending confirmation 使用 process-safe、crash-release 的有界锁；锁范围覆盖 read → validate identity/payload → commit/replay classify → receipt/reconcile → clear，避免读取与提交间 TOCTOU。
  - [x] 不直接复用会在进程退出后遗留 stale `O_EXCL` 文件的 registry lock；不得把 claim authority放到 MCP、CLI 或 platform adapter。
  - [x] 锁等待/失败返回受控、脱敏结果，不能清除合法 pending、不能写 facts，也不能让第二个 caller抢先报告 fresh success。
  - [x] 保留现有 expiry、wrong save/session/platform/session key/actor、incomplete pending、stale write 与 commit failure 语义；除 expiry 与成功 reconcile 外，失败不得清除 pending。

- [x] Task 3：建立 bounded replay receipt 并用 SQLite 事实复核（AC: 1, 2, 3, 4）
  - [x] 在正常 fresh commit 后、pending clear 前原子发布非权威 replay receipt；至少绑定 confirmation session、save id/path、command id/hash、delta/proposal digest、可选 platform/session/actor hash、turn id 与稳定 result classification。
  - [x] Receipt 只作为 entry/replay evidence；每次 replay 必须重新对账目标 Save SQLite 中的 command/hash/turn/event evidence，不能从 receipt 推导或覆盖 gameplay facts。
  - [x] Commit 已成功但 receipt 尚未发布时，重试必须从仍存在的 pending + SQLite command evidence恢复；receipt 已发布而 pending 尚未清除时也必须收敛为同一 replay结果。
  - [x] Receipt 写入或 pending clear 失败不得把已提交事实报告成 fresh retry；下一次同 identity retry必须可修复。不得顺手引入 Story 6.5 的长期 orphan/多 pending lifecycle。
  - [x] 优先复用现有 `turns.session_id` / `command_id` / `command_hash`、canonical delta digest、atomic IO 与 SQLite evidence，不新增 dependency 或 migration；若确实需要 schema migration 才能满足 AC，按 P0 范围扩张规则停止并提交证据，不自行扩大。

- [x] Task 4：让 CommitService / UnitOfWork 保留 fresh-vs-replay outcome（AC: 1, 2, 3, 4）
  - [x] 将 `UnitOfWork.begin()` 的 existing-turn outcome 传播到 CommitService，而不是丢弃分类后无条件包装为 `committed`；保留 `save_turn_delta()->str` 的既有兼容调用，必要时新增内部 outcome helper。
  - [x] 删除或重构 transaction 外的非原子 `assert_turn_proposal_not_committed()`：same command/hash 返回 replay；same command/different hash 仍抛 conflict；并发检查与 `BEGIN IMMEDIATE` 间竞态仍必须由 UnitOfWork最终分类。
  - [x] Replay 路径不得创建 backup、再次运行 archivist、重写事实、重复 projection/outbox append 或 fresh-only post-commit操作；必要 projection health 只能作为只读/repair evidence，不得伪装为新提交。
  - [x] Runtime 在 fresh validation 前后都必须安全处理 race/crash replay：已经 durable 的相同命令不能因 stale expected turn 在分类前被误拒，但 replay recognition 也不能绕过 payload/hash、proposal confirmation 或 save identity核验。

- [x] Task 5：保持所有 surfaces 薄适配并覆盖外围副作用（AC: 1, 3, 4）
  - [x] MCP 与 V1 CLI 继续直接调用 `SaveManager.player_confirm()` 并透传 machine-readable fields；human text 明确区分“本次已写入”与“此前已确认，本次为幂等重放”。
  - [x] Platform sidecar 的 saved/success metrics、message reservation 与 binding activation 不得把 `already_confirmed` 计作新的 fresh save；不同 message id 对同一 confirmation session 的合法 retry仍能获得 replay。
  - [x] Public result/audit summary不得包含 raw pending/receipt/delta/proposal/identity；完整 route audit reconstruction继续留给 Story 6.7。
  - [x] `surface_inventory` 的 `player_confirm` validated commit authority 不变；默认 player profile不获得任何 low-level工具。

- [x] Task 6：建立 concurrency、crash、conflict 与 package safety gates（AC: 1, 2, 3, 4）
  - [x] 新增 focused owner test file（优先 `tests/test_pending_confirmation_replay.py`），覆盖真实 two-thread 与 two-subprocess barrier：精确一条 `committed`、一条 `already_confirmed/idempotent_replay=true`，turn/event/fact与外围计数只增加一次。
  - [x] Subprocess crash test 在 SQLite commit 可见、receipt/pending clear 前终止 child；parent retry必须 replay、清理 pending且不增加任何 authoritative row。使用测试内 monkeypatch/subclass/process orchestration，不增加 production failpoint。
  - [x] 覆盖 normal-clear 后 replay、lock release-on-crash/timeout、receipt write/clear failure、malformed/tampered receipt、same command different delta/proposal、wrong session/save/platform/session/actor，以及 raw/hidden token non-leakage。
  - [x] 更新既有 replay 预期：`test_cross_campaign_context_smoke.py` 等旧测试中“第二次 confirm 抛 no pending”应改为稳定 replay；同时保留 expired/incomplete/stale/write-failure pending 保护与 source/formal package fingerprint。
  - [x] Focused union 至少包含：
    ```bash
    PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q \
      tests/test_pending_confirmation_replay.py \
      tests/test_save_manager.py \
      tests/test_validation_pipeline.py \
      tests/test_projection_service.py \
      tests/test_runtime.py \
      -p no:cacheprovider
    ```
  - [x] Adjacent union 至少包含：
    ```bash
    PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q \
      tests/test_mcp_adapter.py \
      tests/test_v1_cli.py \
      tests/test_platform_sidecar.py \
      tests/test_platform_ai_simulation.py \
      tests/test_p0_stop_loss_acceptance.py \
      tests/test_current_native_player_turn.py \
      tests/test_current_native_write_safety.py \
      tests/test_cross_campaign_context_smoke.py \
      tests/test_cross_layer_regression.py \
      tests/test_surface_inventory.py \
      -p no:cacheprovider
    ```

- [x] Task 7：同步 canonical docs 与最终质量门（AC: 1, 2, 3, 4）
  - [x] 更新实际受影响的 `docs/architecture.md`、`docs/component-inventory.md`、`docs/ai-intent-chain.md`、`docs/save-and-campaign-packages.md`、`docs/data-models.md`、`docs/cli-contracts.md`、`docs/mcp-contracts.md` 与 `docs/testing-and-quality-gates.md`；仅在实际 public prompt语义变化时更新 prompt artifact/version。
  - [x] 明确 receipt/claim 是 entry/replay evidence，不是事实、玩家确认、proposal approval 或 commit token；SQLite turns/events仍是权威证据。
  - [x] 从最终 clean diff 重跑 story focused、adjacent regression、两套 Campaign validate/test、Markdown links、全仓 `py_compile`、full Ruff、`git diff --check` 与 repository full pytest；任何后续 patch 使旧 gate失效时必须重跑。

### Review Findings — Round 1

- [x] [Review][Patch] 用同一 confirmation lock 保护 `player_turn` 的 pending/receipt 发布，并在发布失败时恢复旧 receipt [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] 已 durable 的过期 pending 必须进入 replay recovery，不能先清除 pending [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] SQLite commit 后、projection/outbox finalize 前崩溃必须以 dirty-only repair 收敛 [`rpg_engine/runtime.py`]
- [x] [Review][Patch] pending 已清除但 registry 尚未刷新时，replay 必须按 cached turn mismatch 做幂等 repair [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] replay proposal 必须具备 SaveManager confirmation provenance，不能仅信任 `human_confirmed=true` [`rpg_engine/commit_service.py`]
- [x] [Review][Patch] `commit_turn_delta()` 的 replay permission 必须默认 deny，仅由可信 proposal 路径显式开启 [`rpg_engine/commit_service.py`]
- [x] [Review][Patch] public `saved/write_status/idempotent_replay` 非法组合必须 fail closed [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] receipt bounded read 必须在读取整个文件前执行上限 [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] confirmation lock 必须验证 workspace 边界并提供 stdlib 跨平台锁实现 [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] unbound pending 不得接受额外 platform/session/actor identity 后产生不可 replay 的 receipt [`rpg_engine/save_manager.py`]
- [x] [Review][Defer] 可选 archivist 请求在通用 CommitService 的 SQLite commit 后崩溃窗口缺少 durable phase/outbox [`rpg_engine/commit_service.py`] — deferred, pre-existing；普通 `player_confirm` 默认不启用 archivist，修复需要扩大持久化设计，留待独立规划。

### Review Findings — Round 2

- [x] [Review][Patch] 移除 low-level Runtime 的自报 provenance early replay；durable replay 与 dirty repair 只由已核验 claim/identity/payload 的 SaveManager owner 执行，owner 外 UOW replay fail closed [`rpg_engine/runtime.py`, `rpg_engine/commit_service.py`, `rpg_engine/save_manager.py`]
- [x] [Review][Patch] 将 bounded receipt 完整 digest 锚定到目标 Save SQLite meta，重算 workspace digest 的 identity/payload/turn 篡改仍须拒绝 [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] 部分绑定 platform/session/actor identity 也必须执行 presence parity，不能接受 pending 未绑定的额外 actor [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] receipt `event_count` 必须为 exact non-negative integer，拒绝 bool、float 与 numeric string [`rpg_engine/save_manager.py`]

### Review Findings — Round 3

- [x] [Review][Patch] CommitService 提供仅由已核验 SaveManager owner 调用的 durable replay propagation/dirty repair 合同，返回 `already_confirmed` 而普通 Runtime/UOW replay 继续 fail closed [`rpg_engine/commit_service.py`, `rpg_engine/save_manager.py`]
- [x] [Review][Patch] pending 的 `save_path` 必须与当前选定/bound save record 精确一致，不能只比较可被 registry 替换的 `save_id` [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] pending action 的 read/clear 必须执行 workspace boundary 校验并拒绝外部 symlink [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] confirmation result 的 `ok` 与 `idempotent_replay` 必须为 exact bool，不接受 truthy string/int [`rpg_engine/save_manager.py`]
- [x] [Review][Defer] 新行动发布后仍支持更早 confirmation 的延迟 replay 需要 bounded historical receipt set 与 supersede/orphan/retention 策略，属于 Story 6.5 lifecycle 范围；已记录到 `deferred-work.md`。

### Review Findings — Round 4

- [x] [Review][Patch] fresh confirm 必须冻结首次核验的 bound save id/path，并按 exact path refresh；确认中 active save 切换不能把 A 的 pending 写入 B [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] platform `already_confirmed` replay 只能保留 reservation/current binding，不得重复 activation 或延长 active TTL [`rpg_engine/platform_sidecar.py`]

### Review Findings — Round 5

- [x] [Review][Patch] pending 必须包含并匹配 exact normalized `save_path`；缺失路径不能退回只信任 registry `save_id` [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] bounded receipt JSON 必须拒绝 duplicate keys，即使重复值解析后与 SQLite anchor 一致 [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] confirmation lock open/acquire OS failure必须转为稳定脱敏 SaveManagerError [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] unlock 异常不得跳过 fd close 或把已完成 confirmation 变成未处理的 OS error [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] confirm 后 registry save refresh 必须在同一 registry lock 内 read-merge-write，保留并发 active-save switch [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] platform confirm completion 必须在 entry lock 内与最新 reservation 合并，较旧 fresh completion 不得覆盖较新 message id [`rpg_engine/platform_sidecar.py`]

### Review Findings — Round 6

- [x] [Review][Patch] duplicate receipt key 的错误必须使用固定脱敏文本，不能回显 attacker-controlled key [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] `switch_save` 自身必须在 registry lock 内 read-modify-write，不能用锁外 stale snapshot覆盖 confirm refresh [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] platform 旧 confirm completion 必须保留更新的 act/deactivate/save/clarification context，而不仅是最新 message id [`rpg_engine/platform_sidecar.py`]

### Review Findings — Round 7

- [x] [Review][Patch] bound-save `require_save(refresh=True)` 必须用 registry 锁内 merge，不能以锁外快照撤销并发 `switch_save` [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] platform `deactivate_from_message` 必须与 confirm completion 使用同一 entry/file lock，旧 completion 不得复活 inactive binding [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Patch] pending claim 必须绑定 save 与 hashed platform identity并以目标 Save SQLite anchor 复核；receipt 缺失的 durable claim 不能重绑另一 Save [`rpg_engine/save_manager.py`]

### Review Findings — Round 8

- [x] [Review][Patch] `GMRuntime.commit_turn()` 抛出可捕获异常后，只有重新查询 SQLite 证明 command 未 durable 才能回滚新 claim；post-commit 异常与 evidence-query failure 必须保留 claim/anchor 供 replay recovery [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] platform start/act completion 必须与 confirm/deactivate/expiry 共用 entry/file lock 并合并最新 reservation context，旧 completion 不得复活 inactive binding或覆盖更新 Save [`rpg_engine/platform_sidecar.py`]

### Review Findings — Round 9

- [x] [Review][Patch] registry RMW 必须使用进程退出自动释放的 OS lock；fresh confirm 在 pending clear 后死于 registry merge 时，durable replay 不能被 stale `O_EXCL` 文件永久阻断 [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] advisory prewarm binding RMW 必须与 sidecar completion 共用跨平台 owner lock，但只更新 last message、不推进 authoritative revision；act completion 应保留较新 prewarm message并完成 `pending_approval` transition [`rpg_engine/platform_prewarm.py`, `rpg_engine/platform_sidecar.py`, `rpg_engine/game_session.py`]
- [x] [Review][Patch] start placeholder 的显式 deactivate 必须推进可比较 revision；旧 start completion 即使 state/save/message表面未变，也不得重新激活 binding [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Decision] fresh confirm 已 durable 但进程死于 platform merge 前，replay 是永不 activation 还是精确补做缺失 completion？用户选择方案 1：持久化 hashed confirmation correlation/revision；仅在 session/save/state 全匹配且没有更新 authoritative context 时补 `active_game` transition，保持原 TTL，不复制 Kernel authority。

### Review Findings — Round 10

- [x] [Review][Patch] `current_save/list_saves/list_campaigns` refresh 与其余 production registry RMW 的 read → refresh/mutate → write 必须处于同一 crash-release owner transaction，锁外旧快照不得覆盖 concurrent confirmation registry merge [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] fresh/replay confirm completion 必须以 reservation 捕获的 state revision 做 CAS；同一 confirmation retry reservation 可保留 revision，但更新 start/act/deactivate/save context 必须阻断旧 completion [`rpg_engine/platform_sidecar.py`]

### Review Findings — Round 11

- [x] [Review][Patch] registry merge/`require_save(refresh=True)` 必须在 owner lock 内重新取得并 refresh 最新 exact path/id record，不能让 caller 的旧 whole-record 覆盖 concurrent metadata [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] start reservation 必须推进 confirmation operation generation；较旧 confirm 不能继承新 revision，start 失败或无 activation result 时须以 CAS 恢复原 authoritative binding [`rpg_engine/game_session.py`, `rpg_engine/platform_prewarm.py`, `rpg_engine/platform_sidecar.py`]
- [x] [Review][Patch] confirm 的 message-only reservation 不得阻断仍然有效的 act/start completion；authoritative revision/state/action/save context 仍须执行 CAS [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Decision] schema 1 `pending_approval` 缺少 confirmation correlation 时是否允许 completion backfill？用户选择方案 1：仅 owner-validated hash、revision=0、pending revision=0、correlation 为空且 Save/state 精确匹配时兼容回填；任何新 authoritative operation 均阻断。

### Review Findings — Round 12

- [x] Blind Hunter、Edge Case Hunter 与 Acceptance Auditor 三路 fresh review 均 CLEAN；0 Patch、0 Decision、0 新 Defer。累计自动应用 42 个明确 Patch，既有 2 个 Defer 已正确记录。

## Dev Notes

### 当前可复现基线

- Create Story 基线 `HEAD` / `origin/main`：`ee021b4c8d6c38206940335e6b9ecf5a7a726cab`（Story 6.3），工作树干净。
- 已批准调查在 temporary Save 上复现：两个并发 `player_confirm()` 都报告 `committed`，但数据库只写一个 turn/event；因此缺陷是 exactly-once response 语义与 crash recovery，不是事实双写。[Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md` — Outcome 3 Dynamic Evidence / Refutation Record]
- `SaveManager.player_confirm()` 当前是 pending JSON read → identity/session validation → `GMRuntime.commit_turn()` → unlink pending，无跨进程 claim/lock/receipt。[Source: `rpg_engine/save_manager.py` — `SaveManager.player_confirm`]
- `UnitOfWork.begin()` 已使用 `BEGIN IMMEDIATE`，并通过 `find_idempotent_turn()` 以 `command_id` / canonical command hash识别 existing turn；但 `save_turn_delta()` 只返回 turn id，CommitService无条件发布 `write_status=committed`。[Source: `rpg_engine/unit_of_work.py` — `begin`; `rpg_engine/write_guard.py` — `find_idempotent_turn`; `rpg_engine/save.py` — `save_turn_delta`; `rpg_engine/commit_service.py` — `commit_turn_delta`]
- `commit_turn_proposal()` 当前的 `assert_turn_proposal_not_committed()` 在 write transaction 外执行；并发可同时通过，crash retry又会被通用 `already committed`异常阻断。[Source: `rpg_engine/commit_service.py` — `commit_turn_proposal`, `assert_turn_proposal_not_committed`]

### Architecture Compliance

- 权威链不变：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- 普通玩家写入必须保持 `player_turn -> pending -> player_confirm -> validation -> CommitService/UnitOfWork -> SQLite`；claim/replay classification只能加强这一门，不能建立第二写入路径。
- `data/game.sqlite` 的 turns/events/facts 是事实与权威审计；workspace pending/claim/receipt、registry、projection/outbox都不是 fact authority。
- 本地 V1 仍是每个 active Save 一个普通玩家 pending session；本 Story只解决 confirmation atomicity/replay，不决定 supersede/cancel/clarification产品语义。
- 对并发 caller，SQLite `BEGIN IMMEDIATE` 保证单 writer；[SQLite transaction 文档](https://www.sqlite.org/lang_transaction.html)说明同时只允许一个 write transaction，`BEGIN IMMEDIATE` 会立即尝试取得 write transaction。Unique `command_id` 继续作为数据库最终去重护栏。[SQLite CREATE INDEX 文档](https://www.sqlite.org/lang_createindex.html)
- 若使用文件 rename 发布 receipt，[Python `os.replace()` 文档](https://docs.python.org/3.11/library/os.html#os.replace)规定成功的同文件系统 rename 在 POSIX 上是 atomic；它只能用于发布文件，不能代替跨进程 claim锁或 SQLite事实复核。

### Existing Code: Current / Change / Preserve

- `rpg_engine/save_manager.py`
  - Current：workspace pending JSON atomic write，但 confirm read/commit/clear无互斥；成功后删除唯一 replay上下文。
  - Change：confirmation lock、bounded replay receipt、fresh/replay/conflict result、crash reconcile、player message。
  - Preserve：single-pending、TTL、bound save、platform/session/actor hash、pending failure preservation、thin surfaces与不暴露 delta/proposal。
- `rpg_engine/unit_of_work.py` / `rpg_engine/save.py`
  - Current：`BEGIN IMMEDIATE` + existing command detection已防事实重复，但分类被压成 turn id。
  - Change：向 CommitService保留 fresh vs existing outcome，同时保持旧 `save_turn_delta` caller compatibility。
  - Preserve：expected-turn、transaction rollback、event/entity/clock/meta原子写、projection dirtiness与 outbox finalize。
- `rpg_engine/commit_service.py`
  - Current：transaction 外 duplicate proposal检查；无 replay result，post-commit工作默认按 fresh执行。
  - Change：same command/hash replay classification、different payload conflict、fresh-only backup/archivist/projection/check边界。
  - Preserve：validation profile、approved TurnProposal、stable delta digest、SQLite事实和 projection非权威边界。
- `rpg_engine/runtime.py`
  - Current：validation先于 commit，`CommitTurnResult.ok` 只认 `committed`。
  - Change：在不绕过 confirmation/payload核验的前提下处理 durable replay与 race，传播 `idempotent_replay`。
  - Preserve：low-level profile/TurnProposal gate、state audit、registry injection、错误脱敏。
- `rpg_engine/platform_sidecar.py`
  - Current：调用 SaveManager薄转发，但部分 metrics/activation以 `saved`判断。
  - Change：只消费 Kernel 的 replay字段，避免重复 fresh副作用。
  - Preserve：message reservation/session actor gate、passive identity与无直接事实写入。

### Previous Story Intelligence

- Story 6.3 的成功依赖方向是 canonical owner → resolved evidence → all consumers；Story 6.4同样必须让 `SaveManager` / CommitService拥有 claim/replay语义，不让 adapter各自拼状态。
- Story 6.3 review反复捕获 validation-before-hash/sort、falsey fallback、mutable/equal-but-not-canonical输入、duplicate last-write-wins、preflight identity缺段和 File List漂移。Pending/receipt实现应从首版就先验证 exact/bounded identity与 digest，再做 lock、lookup、write/clear。
- Story 6.2 的大范围 review表明无规划的 locale/grammar扩展会触发 decision；本 Story必须严守 6.4，不提前实现 6.5 supersede/clarification或6.7 audit。
- Story 1.3 已把“commit succeeds but pending clear fails后的幂等 retry”明确 defer给后续；同时锁定 bound-save confirmation、write failure保留 pending、precommit backup cleanup和公开结果脱敏。本 Story应关闭该 defer而不回退这些行为。

### Git Intelligence

- 最近提交：`ee021b4 feat(intent): complete Story 6.3 slot contract`、`6af8597 feat(intent): complete Story 6.2 action taxonomy`、`dbced86 feat(intent): negotiate external safety contracts`。
- Epic 6 前三项均采用：Story + validation artifact + sprint sync + canonical docs + owner code + focused/adjacent/full gates的单个 concise commit；6.4应保持同一提交边界。
- 当前不需要新依赖、网络服务或云锁；只使用 Python 3.11+ stdlib、SQLite 与既有 pytest/Ruff。

### Expected File Scope

- NEW（优先）：`tests/test_pending_confirmation_replay.py`。
- UPDATE（核心）：`rpg_engine/save_manager.py`、`rpg_engine/commit_service.py`、`rpg_engine/save.py`、`rpg_engine/unit_of_work.py`、`rpg_engine/runtime.py`；仅在共享 hash/replay helper确有必要时更新 `rpg_engine/write_guard.py`。
- UPDATE（相邻）：`rpg_engine/platform_sidecar.py` 及相关 SaveManager/runtime/MCP/CLI/platform/cross-campaign/current-native tests。
- UPDATE（docs）：architecture/component/intent/save/data-model/CLI/MCP/testing canonical docs；public prompt合同未改变时不改 prompt版本。
- 通常不改：DB schema/migrations、Campaign/Save schema、intent taxonomy/slot/safety/preflight、MCP/CLI business logic、Hermes仓库、Story 4.7或 Stories 6.5–6.8。

### Testing Requirements

- Focused：pending claim/replay、SaveManager、CommitService/UoW/write guard、Runtime、validation/projection。
- Adjacent：MCP/CLI/platform、P0 stop-loss、current-native player/write safety、cross-campaign context、cross-layer/surface inventory。
- Package safety：所有并发/crash/commit测试只写 temporary Save；source Campaign、formal current Save、正式 registry与正式 `data/game.sqlite` fingerprint不变。
- Required final clean-diff gates：story focused、adjacent regression、两套 Campaign validate/test、Markdown links、全仓 `py_compile`、full Ruff、`git diff --check`、repository full pytest。

## Project Structure Notes

- Claim/replay ownership留在 `SaveManager` + CommitService/UnitOfWork；不新建 coordinator或把事务语义塞进 adapters。
- Replay receipt若存在，放在 workspace `.aigm/` entry/evidence边界，使用 bounded schema与原子写；不得放入 source Campaign、正式 registry或 player-visible projection。
- 不把测试 barrier/failpoint放进 production模块；subprocess测试使用 test-local orchestration。
- 如实现发现必须新增 migration、依赖、跨仓协议或扩大 Story 6.5/6.7边界，按用户 HALT条件停止并报告证据。

## References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Story 6.4]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md` — D4, §4.2 Story 6.4, §8–10]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md` — FR-1, FR-14, FR-16, NFR-1/3/4]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md` — AD-1, AD-4, AD-5]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md` — AD-1, AD-3, AD-9, AD-10]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md` — pending/confirm reproduction and handoff]
- [Source: `_bmad-output/implementation-artifacts/6-3-resolved-slot-contract-projection-and-parity.md` — previous story intelligence]
- [Source: `docs/project-context.md` — fact/AI/confirmation/package boundaries]
- [Source: `docs/architecture.md` — player-safe chain, write chain, data boundary]
- [Source: `docs/save-and-campaign-packages.md` — Player Workspace Registry / Player Entry Flow / test boundary]
- [Source: `docs/data-models.md` — Turn/Event, Turn Delta, TurnProposal, Pending Player State]
- [Source: `docs/testing-and-quality-gates.md` — write safety / SaveManager / cross-campaign / current-native gates]
- [Python 3.11 `os.replace()`](https://docs.python.org/3.11/library/os.html#os.replace)
- [SQLite Transactions](https://www.sqlite.org/lang_transaction.html)
- [SQLite Unique Indexes](https://www.sqlite.org/lang_createindex.html#unique_indexes)

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Create Story read-only reproduction evidence：existing investigation confirms duplicate fresh response with one SQLite write。
- Create Story code trace：`SaveManager.player_confirm` → `GMRuntime.commit_turn` → CommitService → `save_turn_delta` → UnitOfWork/write guard。

### Implementation Plan

- RED：新增 owner-focused 并发与 normal-clear replay tests，确认现状两个 caller 都报告 `committed` 且 clear 后重试抛 `no pending`。
- GREEN：以 SaveManager OS file lock 串行化确认，在 pending 内冻结 payload claim，commit 后原子发布 bounded receipt；由 SQLite command/turn/event evidence 复核 replay。
- REFACTOR：让 `save_turn_delta()` 保持字符串兼容，同时由 outcome helper 向 CommitService/Runtime 传播 fresh/replay；surfaces 只透传 Kernel classification。
- VERIFY：真实 thread/subprocess/crash、conflict/privacy/package safety、focused/adjacent/full suite 与 canonical docs/static gates。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created。
- Validate Story checklist 通过：0 critical、0 decision-needed；5 项明确增强与 2 项优化已纳入正文和独立 validation report。
- `[DS]` 完成 atomic claim、pending payload claim、bounded replay receipt、SQLite replay复核、fresh-only副作用与 thin-surface结果传播；未新增依赖、migration或测试专用 production API。
- RED 证据：`tests/test_pending_confirmation_replay.py` 初始 `2 failed`，精确复现 dual-`committed` 与 normal-clear `no pending`。
- GREEN/回归：focused `171 passed, 140 subtests`；adjacent `152 passed, 288 subtests`；repository full `1048 passed, 10329 subtests`。
- 静态/package：full Ruff、全仓 py_compile、193 Markdown files links、两套 Campaign validate/test、`git diff --check` 全部通过。
- Code Review Round 1：Blind Hunter 与 Edge Case Hunter 共产生去重候选；Acceptance Auditor 被平台误报中止。经复现、范围与 AC 核验后应用 10 个明确 Patch，dismiss 4 个噪声/重复/越界 finding，记录 1 个 Defer；补丁后 focused `177 passed, 140 subtests`、adjacent `152 passed, 288 subtests`，Ruff、py_compile、Markdown links 与 diff-check 通过。
- Code Review Round 2：Blind Hunter 与 Edge Case Hunter 均完成 fresh review；Acceptance Auditor 在先行报告两个实证缺口后被平台误报中止。去重后应用 4 个明确 Patch，无 Decision/Defer；补丁后 focused `178 passed, 142 subtests`、扩展 adjacent `159 passed, 278 subtests`，Ruff、py_compile、Markdown links 与 diff-check 通过。
- Code Review Round 3：三路 fresh reviewer 全部完成。经复现、AC 与范围核验后应用 4 个明确 Patch，将 1 个跨新行动的 historical receipt finding 按 Story 6.5 边界 Defer；Acceptance Auditor 提出的 latest-diff final gates 属于 clean review 后的既定收尾步骤。补丁后 focused `179 passed, 142 subtests`、扩展 adjacent `159 passed, 278 subtests`，Ruff、py_compile、Markdown links 与 diff-check 通过。
- Code Review Round 4：三路 fresh reviewer 全部完成；Acceptance Auditor clean，Blind/Edge 去重后确认 2 个 Patch。补丁后 focused `180 passed, 142 subtests`、扩展 adjacent `159 passed, 278 subtests`，Ruff、py_compile、Markdown links 与 diff-check 通过；无 Decision/新 Defer。
- Code Review Round 5：Acceptance Auditor fresh turn clean，Edge Case Hunter fresh turn确认 6 个 Patch，Blind Hunter 被平台误报中止，因此本轮不计 clean。全部 Patch 已应用；补丁后 focused `181 passed, 142 subtests`、扩展 adjacent `159 passed, 278 subtests`，无 Decision/新 Defer。
- Code Review Round 6：Acceptance Auditor fresh turn clean，Edge Case Hunter fresh turn确认 3 个 Patch，Blind Hunter 再次被平台误报中止，因此本轮不计 clean。全部 Patch 已应用；补丁后 focused `181 passed, 142 subtests`、扩展 adjacent `159 passed, 278 subtests`，无 Decision/新 Defer。
- Code Review Round 7：三路全新独立 turn 均完成有效结果；去重后确认 3 个 Patch。实现过程中 focused 捕获普通失败遗留 claim meta，已自动恢复原 pending/anchor语义。补丁后 focused `182 passed, 142 subtests`、扩展 adjacent `159 passed, 278 subtests`，无 Decision/新 Defer。
- Code Review Round 8：三路 fresh 独立 review 均完成；Acceptance Auditor clean，Blind Hunter 与 Edge Case Hunter 独立复现同两项问题，去重后应用 2 个 Patch。新增 post-commit 可捕获异常与 platform stale start/act completion 回归；补丁后 focused `183 passed, 142 subtests`、扩展 adjacent `161 passed, 278 subtests`，Ruff、py_compile、193 Markdown links 与 diff-check 通过，无 Decision/新 Defer。
- Code Review Round 9：三路 fresh 独立 review 均完成；去重后确认 3 个 Patch 与 1 个真实 Decision。用户明确选择持久化 completion correlation/revision 方案；已实现 crash-release registry/platform lock、prewarm merge、placeholder deactivate generation与无 TTL 刷新的精确 replay completion repair。新增 4 个直接复现测试；补丁后 focused `184 passed, 142 subtests`、扩展 adjacent `164 passed, 278 subtests`，Ruff、py_compile、193 Markdown links 与 diff-check 通过，进入第十轮 fresh re-review。
- Code Review Round 10：三路 fresh review 均完成；Edge clean，Blind 与 Acceptance 各确认 1 个 Patch。已把全部 production registry RMW 收进同一 owner transaction，并为 fresh/replay confirm completion 增加 state revision CAS；补丁后 focused `185 passed, 142 subtests`、扩展 adjacent `165 passed, 278 subtests`，Ruff、py_compile、193 Markdown links 与 diff-check 通过，无 Decision/Defer。
- Code Review Round 11：三路 fresh review 均完成；Acceptance clean，Blind/Edge 去重后确认 3 个 Patch 与 1 个真实 Decision。用户选择 owner-validated revision=0 兼容回填；已实现 registry latest-record refresh、pending confirmation generation、start CAS rollback 与 message-only confirm completion merge。定向/受影响回归 `308 passed, 178 subtests`，进入第十二轮 fresh re-review。
- Code Review Round 12：Blind Hunter、Edge Case Hunter 与 Acceptance Auditor 三路 fresh review 全部 CLEAN；0 Patch、0 Decision、0 新 Defer。独立复核覆盖 atomic claim/receipt、registry RMW、platform generation/CAS、start rollback、legacy revision=0 backfill、AC/边界与 temporary Save 隔离；进入最终 clean diff required gates。
- 最终 clean diff required gates：focused `185 passed, 142 subtests`；adjacent `161 passed, 288 subtests`；两套 Campaign validate/test 均 `OK`；193 个 Markdown files links、全仓 py_compile、full Ruff、`git diff --check` 全部通过；repository full `1071 passed, 10331 subtests`。
- BMAD 状态同步：Story 6.4 与 sprint 条目设为 `done`；Epic 6 因 6.5–6.8 仍为 backlog，保持 `in-progress`。

### File List

- `_bmad-output/implementation-artifacts/6-4-atomic-pending-confirmation-claim-and-replay-classification.md`
- `_bmad-output/implementation-artifacts/6-4-atomic-pending-confirmation-claim-and-replay-classification.validation-report.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/mcp-contracts.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/commit_service.py`
- `rpg_engine/game_session.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/runtime.py`
- `rpg_engine/save.py`
- `rpg_engine/save_manager.py`
- `tests/test_cross_campaign_context_smoke.py`
- `tests/test_mcp_adapter.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_pending_confirmation_replay.py`
- `tests/test_platform_sidecar.py`
- `tests/test_v1_cli.py`

## Change Log

- 2026-07-14：Create Story 完成规划、架构、现有代码、前序 Story、Git 与官方 Python/SQLite文档分析；状态设为 ready-for-dev。
- 2026-07-14：Validate Story 完成独立 checklist 复核；0 critical、0 decision-needed，已应用全部明确增强，保持 ready-for-dev。
- 2026-07-14：Dev Story 完成 atomic confirmation claim、durable replay classification、bounded receipt、thin-surface传播、canonical docs 与 required regression；状态设为 review。
- 2026-07-14：Code Review Round 1 应用 10 个有效 Patch、dismiss 4 项并按 workflow 记录 1 项 Defer；受影响 verification gates 通过，进入 fresh re-review。
- 2026-07-14：Code Review Round 2 应用 4 个有效 Patch，将 replay authority 收回 SaveManager owner并加入 SQLite receipt anchor；受影响 verification gates 通过，进入第三轮 fresh re-review。
- 2026-07-14：Code Review Round 3 应用 4 个有效 Patch、记录 1 个 Story 6.5 lifecycle Defer；受影响 verification gates 通过，进入第四轮 fresh re-review。
- 2026-07-14：Code Review Round 4 应用 2 个有效 Patch，冻结 confirm bound save并去除 platform replay activation；受影响 verification gates 通过，进入第五轮 fresh re-review。
- 2026-07-14：Code Review Round 5 应用 6 个有效 Patch，收紧 pending/receipt/lock并原子合并 registry/platform completion；受影响 verification gates 通过，进入第六轮 fresh re-review。
- 2026-07-14：Code Review Round 6 应用 3 个有效 Patch，完成错误脱敏与 registry/platform stale-completion merge；受影响 verification gates 通过，进入第七轮 fresh re-review。
- 2026-07-14：Code Review Round 7 应用 3 个有效 Patch，锚定完整 pending claim并关闭 bound refresh/deactivate TOCTOU；受影响 verification gates 通过，进入第八轮 fresh re-review。
- 2026-07-14：Code Review Round 8 应用 2 个有效 Patch，以 durable evidence约束异常回滚并关闭 platform start/act stale-completion窗口；进入第九轮 fresh re-review。
- 2026-07-14：Code Review Round 9 应用 3 个有效 Patch；用户解析 1 个 Decision为持久化 platform completion correlation/revision，完成 registry/platform crash-release owner 与无 TTL replay repair；进入第十轮 fresh re-review。
- 2026-07-14：Code Review Round 10 应用 2 个有效 Patch，线性化全部 registry RMW并为 confirm completion加入 state revision CAS；进入第十一轮 fresh re-review。
- 2026-07-14：Code Review Round 11 应用 3 个有效 Patch；用户解析 1 个 Decision为 owner-validated schema 1 revision=0兼容回填，补齐 registry latest merge、confirmation generation与 start rollback；进入第十二轮 fresh re-review。
- 2026-07-14：Code Review Round 12 三路 fresh reviewer 全部 CLEAN；review 持续收敛完成，进入最终 clean diff required gates。
- 2026-07-14：最终 clean diff 全部 required gates 通过；Story 6.4 与 sprint 条目同步为 done，Epic 6 因后续 stories 尚未完成保持 in-progress。

## BMAD Provenance

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`；指定从 `sprint-status.yaml` 选择 Epic 6下一个 backlog story，并授权持续 review/patch/verification收敛、commit与push。
- Catalog route：完整读取 `.agents/skills/bmad-help/SKILL.md`，使用 `_bmad/_config/bmad-help.csv`、`skill-manifest.csv`、Core/BMM config、project context、governance与 sprint artifact；路由为 `[CS] bmad-create-story:create` → `[VS] bmad-create-story:validate` → `[DS] bmad-dev-story` → `[CR] bmad-code-review`。
- `[CS]` skill：完整读取 `.agents/skills/bmad-create-story/SKILL.md`；resolver成功，prepend/append/on_complete为空，persistent fact为 `file:{project-root}/**/project-context.md`；加载 `_bmad/bmm/config.yaml`、`docs/project-context.md` 后按 embedded Steps 1→6执行，并完整读取 `discover-inputs.md`、`template.md`、`checklist.md`。
- Create Story sources：完整读取 sprint status、epics、PRD、两份 architecture spine、Correct Course proposal、Story 6.3、canonical project/governance/development/architecture/component/save/testing docs、相关源码/测试与 recent git history；并用三路只读 subagents分别核对 planning、code/tests、previous story/Git情报。
- Latest technical research：官方 Python 3.11 `os.replace`、SQLite transaction 与 unique index文档；未引入新依赖。
- `[VS]` validation：复用已完整读取的 `bmad-create-story` skill/checklist，重新运行 resolver并加载同一 config/persistent facts；生成 `6-4-atomic-pending-confirmation-claim-and-replay-classification.validation-report.md`，0 decision-needed，所有明确改进已自动应用。
