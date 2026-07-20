---
baseline_commit: 2cd0228b8199e4304f55492f2d555b455651fdfb
---

# Story 6.5：显式 Pending Supersede 与 Clarification 生命周期

Status: done

## Story

作为玩家主持者，
我希望 pending action 与 clarification session 具备显式替代、过期、取消和修正语义，
从而新输入不会静默抹掉另一位 caller 的工作，也不会把玩家困在不可解释的恢复循环中。

## Acceptance Criteria

1. **单一 pending 的 compare-and-supersede**
   - Given 一个 active Save 已有 pending action 或 clarification，when 新 `player_turn()` 到达，then V1 仍只允许 workspace 中一个普通玩家 pending session；action 与 clarification 是同一不变量的两种 variant，不能各自并存为两份业务真源。
   - 同一 identity 只有提供与当前 session 精确匹配的 `expected_pending_id` 才可替代；只传 `supersede=true` 之类盲布尔值不构成 compare token。action 使用其 `session_id`，clarification 使用其 `clarification_id`。
   - 不同 save、platform、session 或 actor，以及 identity 字段 presence 不一致时，必须返回结构化 `pending_conflict`，不得泄露另一 caller 的 pending id、原文、candidate、delta、proposal 或身份值，也不得清除或修改旧 session。
   - 无 platform/session/actor 的 direct local caller 是合法的同一 local identity；只要任一方提供部分或额外 identity，就继续按 Story 6.4 presence-parity fail closed。
   - Query、blocked 或其他不发布新 pending 的结果可以执行并保留旧 session；任何要发布 action 或 clarification 的结果都必须在 owner lock 下再次 CAS，若旧状态在 Runtime/AI 处理期间变化则返回 conflict，不能覆盖后来 session。

2. **结构化 save switch、expiry、cancel、migration 与 orphan 结果**
   - `switch_save()` 不得静默删除或转绑旧 pending；它返回旧 session 仍精确绑定原 Save 的 `preserved` lifecycle 摘要，且继续保留 Story 1.3/6.4 已锁定的显式原 `save_path` confirmation 行为。
   - Action 与 clarification 默认 TTL 均为 1800 秒；过期清理返回 `expired`。已存在 confirmation claim 或 SQLite durable command evidence 的 action 必须先走 Story 6.4 replay/reconcile，不能作为普通过期 session 删除。
   - 新增统一 player-safe `player_cancel(expected_pending_id)` owner 操作，可取消 action 或 clarification；必须匹配 exact save 与 identity，并返回 `canceled | expired | not_found | conflict | invalid_state` 等稳定结构化分类。Cancel 不运行 preview/validation/confirm/commit，不写 gameplay facts，也不刷新无关 session TTL。
   - Legacy schema 1 clarification 缺少 TTL/origin 时，在同一 owner lock 下以 `created_at + 1800s` 和保守 `player_input_ambiguity` 原位兼容迁移，并返回 `migrated` evidence；坏 JSON、重复 key、超大文件、越界 symlink、双 active 文件、缺失/冲突 save binding 等不可无歧义迁移状态必须 fail closed 并保留 evidence，不能静默择一或删除。
   - 取消或过期后不存在可继续授权的 session；旧 `expected_pending_id` / `clarification_id` 只能得到 terminal/not-found 分类，不能授权 preview、pending creation、confirmation 或 commit。本 Story不增加 tombstone 事实表或数据库 migration。

3. **Clarification TTL、origin 与 corrected candidate**
   - 新 clarification envelope 必须记录 `schema_version`、`clarification_id`、exact `save_id/save_path`、`created_at`、`expires_at`、`ttl_seconds=1800`、`clarification_origin`、`original_user_text`、bounded clarification payload，以及可选 platform/session/actor hash；不得保存 raw session key 或 raw actor id。
   - `candidate_contract_mismatch` 仅指已经通过 Story 6.1 wire/version/safety 边界后，external candidate 与 Kernel rules/internal/binding 的语义 action/mode/kind/slot 不一致；`contract_version_mismatch`、unknown safety、malformed candidate 等 typed external contract error 仍按 Story 6.1 fail closed，不能转换为 clarification。
   - 只有 origin 为 `candidate_contract_mismatch`，且同一 identity 同时提交匹配的 `expected_pending_id`、`clarification_id`、与持久化 `original_user_text` 精确相等的原始文本（不得自行 trim、case-fold 或 Unicode normalize），以及确实变化的 corrected external candidate 时，才可重新进入完整 strict validation → live taxonomy/slot projection → active SQLite binding → resolver/preview 链。
   - Clarification 文件大小、字符串、容器深度/数量和 strict duplicate-key JSON 解码必须复用 pending state 现有安全上限，不为 clarification 创建另一套宽松边界。
   - Candidate correction 只重新核验候选，最多生成新的未确认 pending；它不是玩家 confirmation，不得设置 `human_confirmed=true` 或直接 commit。真实玩家输入歧义必须提供 fresh player answer，并用匹配 clarification id 显式结束旧 clarification；只换 candidate 不可绕过。

4. **SaveManager 唯一 persisted truth 与薄 adapter**
   - SaveManager 在共享 crash-release OS lock 内拥有 inspect/compare/publish/cancel/expire/migrate/orphan classification；MCP、CLI 与 platform 只 mirror、gate、forward，不能复制 lifecycle 决策。
   - MCP 现有 `pending_clarifications` 进程内字典必须移除 owner 语义；所有 low-level clarification gates 每次从 canonical persisted SaveManager session 读取。Adapter restart 后必须观察同一 clarification id、origin、expiry 与终止结果。
   - MCP player profile 增加 player-safe cancel surface，并把 `expected_pending_id` / `clarification_id` 薄转发给 `player_turn`；低层工具仍不得获得 confirmation、proposal approval、hidden access 或 commit authority。
   - Platform binding 中 `state/clarification_id/pending confirmation hash` 只是 mirror/CAS evidence；sidecar restart、stale binding 或不同 caller 不得复活、替代或覆盖 SaveManager canonical state。

5. **有界历史 replay 与既有权威边界**
   - 新 pending 发布不得让较早已确认 session 的合法延迟 retry 退化为通用 no-pending；Story 6.4 单条 receipt 迁入有界历史集合，按 confirmation session/save/identity/payload digest 查找并每次与目标 Save SQLite anchor/turn/event evidence 对账。
   - 历史 receipt 只保留 bounded、canonical、必要的 hashed identity/digest/result；固定保留上限并确定性淘汰最旧条目。它不是事实、玩家确认或 commit token，tamper/mismatch/重复 key/超限仍 fail closed。
   - `data/game.sqlite` 继续是事实权威；`player_turn`、inspect、cancel、switch、query、clarification correction 和 adapters 均不得提交 gameplay facts。只有匹配 `player_confirm()` 经 validation/CommitService/UnitOfWork 才能 commit。
   - External/internal AI 仍无事实、玩家确认、proposal approval 或 commit authority；hidden/GM-only 内容不得进入 player surface、error、lifecycle projection 或 audit。
   - 不新增依赖、数据库 migration、测试专用 production API、Coordinator、多 pending、多人/云/distributed 服务；不实现 Story 6.6/6.7、Story 4.7、Epic 5/7，不修改 `hermes-agent/**` 或 RPG Engine 自用 Skill。
   - 所有写测试只使用 synthetic Campaign fixture 与独立 temporary Save/workspace；source Campaign、formal current Saves、正式 registry 与用户 `data/game.sqlite` 必须保持不变。

## Tasks / Subtasks

- [x] Task 1：冻结 lifecycle wire、schema 与 fail-closed 分类（AC: 1, 2, 3, 5）
  - [x] 定义 canonical kind `action | clarification`、CAS token `expected_pending_id`、clarification correction token 与 `active | preserved | superseded | canceled | expired | migrated | orphaned | not_found | conflict | invalid_state` 的稳定 owner outcome。
  - [x] 对 clarification，canonical `expected_pending_id` 的值就是 `clarification_id`；API 可同时接收 `clarification_id` 用于 correction 语义核验，但两者不一致必须 `conflict`。
  - [x] Public lifecycle projection 只输出安全状态、kind、save binding 状态、TTL/expiry 与可操作提示；cross-identity 结果不返回 pending id，所有 audit 对 session/caller id 只保留批准 hash。
  - [x] 将 action/clarification 两文件纳入同一 single-session invariant；dual/malformed/oversize/duplicate-key/symlink 状态 fail closed，不创建自动选择权威。

- [x] Task 2：在 SaveManager 实现两阶段 CAS supersede（AC: 1, 2, 5）
  - [x] 第一次 owner lock 读取并规范化当前 session/receipt，校验 save/identity/expected id，记录 bounded generation digest；不得在 Runtime 前清除任何状态。
  - [x] 锁外运行 Runtime/AI；query/blocked/error 必须保留旧 session 与 receipt，不得改变 pending lifecycle state；其余既有合法 bookkeeping 语义保持不变。
  - [x] 发布新 action/clarification 前重新取得 owner lock并比较 generation；仅 matching explicit CAS 可替代，状态变化返回 conflict。发布失败必须恢复旧 session/receipt/history。
  - [x] 覆盖 two-thread/two-process first publication 与 supersede-vs-confirm 竞态；不能让新 session 被 in-flight confirmation 删除，也不能确认已 superseded 的旧 session。

- [x] Task 3：实现 clarification lifecycle 与 safe correction（AC: 2, 3, 4）
  - [x] clarification 添加 1800 秒 TTL、expiry、origin、exact save/identity 和 bounded/canonical read/write protections；legacy clarification 只做保守兼容迁移。
  - [x] 从实际 Runtime result 的 allowlisted route/binding disagreement 分类 `candidate_contract_mismatch`，其余为 genuine player ambiguity；不得捕获或降级 Story 6.1 typed contract errors。
  - [x] Matching correction 必须重跑 live manifest/taxonomy/slot/binder/preview；same candidate、wrong id/text/save/identity、expired/canceled/stale generation 均拒绝且 no-write。
  - [x] Fresh player answer 用 matching clarification token 显式替代；候选修正生成的 pending 保持未确认，仍需独立 `player_confirm()`。

- [x] Task 4：实现 inspect/cancel/switch/orphan 与历史 receipt retention（AC: 2, 5）
  - [x] 新增 SaveManager player-safe inspect/cancel owner 方法；cancel 在 shared lock内按 exact id/save/identity删除唯一匹配 session，绝不运行 gameplay pipeline。
  - [x] `switch_save()` 只返回 pending preserved/bound-to-previous-save 摘要，不删除、不转绑；create/duplicate activation 也不得静默覆盖 pending 生命周期。
  - [x] Orphan cleanup 仅清理可证明未 claim、未 durable、且 save record/path 已不可恢复的 exact session；任何 claim/receipt/SQLite evidence 不确定性返回 `invalid_state` 并保留 evidence。
  - [x] 增加 bounded historical receipt artifact/reader；兼容现有 latest receipt，固定容量、大小、duplicate-key/tamper/SQLite anchor 校验与 deterministic eviction。

- [x] Task 5：MCP/CLI/platform 只 mirror、gate、forward（AC: 1, 2, 4, 5）
  - [x] 移除 MCP in-memory clarification owner；low-level gates 读取 SaveManager canonical session，restart 后行为一致。
  - [x] MCP player profile 增加 `player_cancel`，`player_turn` 增加 `expected_pending_id` / `clarification_id` / actor identity 薄转发；同步 tool registration、surface inventory 与安全 audit。
  - [x] V1 CLI 暴露等价 player-safe cancel/参数时只调用 SaveManager；不得在 parser/adapter重建 lifecycle逻辑。
  - [x] Platform same/cross identity、cancel、expiry、restart、stale binding 与 confirmation generation 继续使用 binding revision/CAS，但以 SaveManager result 为业务 truth；saved metric 只计 fresh commit。

- [x] Task 6：建立 focused 与 adjacent regression gates（AC: 1–5）
  - [x] 新增 `tests/test_pending_lifecycle.py`，覆盖 action↔clarification 四向替代、missing/wrong CAS、cross identity、query preservation、TTL/cancel/migration/orphan、correction、restart、history、privacy/no-mutation 与 concurrency。
  - [x] 反转旧“非 ready 或 clarification 自动清除 pending”的 characterization tests；保留 Story 6.4 atomic claim/replay、bound-save switch confirm、publication rollback、registry/platform CAS 全部回归。
  - [x] 所有写测试使用 synthetic fixture + temporary Save；对 SQLite全表/schema、turn/event、events.jsonl、pending/clarification/receipt/history、registry、projection与 Save tree 做前后 oracle。
  - [x] Focused gate 在测试名固定后写成可直接执行的完整 pytest 命令与确定性 `-k` 表达式；至少包含 `tests/test_pending_lifecycle.py tests/test_pending_confirmation_replay.py tests/test_save_manager.py tests/test_mcp_adapter.py tests/test_mcp_transcript.py tests/test_platform_sidecar.py`，不得依赖人工挑选“lifecycle 子集”。
  - [x] Adjacent gate：intent/runtime/package condition/platform simulation/V1 CLI/surface inventory/Hermes provider fixture/cross-campaign context 与 current-native player-safe/write-safety相关回归。

- [x] Task 7：同步 canonical docs 与最终质量门（AC: 1–5）
  - [x] 更新 `docs/architecture.md`、`docs/component-inventory.md`、`docs/ai-intent-chain.md`、`docs/save-and-campaign-packages.md`、`docs/data-models.md`、`docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md` 与 `docs/testing-and-quality-gates.md`；若 public prompt tool/order 实际变化则同步 prompt version/artifact。
  - [x] 从最终 clean diff 重新运行 focused、adjacent、两套 Campaign validate/test、Markdown links、全仓 `py_compile`、full Ruff、`git diff --check` 与 repository full pytest；后续 patch 失效的旧绿灯不得复用。

### Review Findings

- [x] [Review][Patch] Cancel conflict 顶层 wire 必须返回稳定 `status=conflict` [`rpg_engine/save_manager.py`:2495]
- [x] [Review][Patch] 省略 `save_path` 时 cancel 仍须匹配当前 exact Save [`rpg_engine/save_manager.py`:1169]
- [x] [Review][Patch] `switch_save()` 的无身份摘要不得泄露 pending token [`rpg_engine/save_manager.py`:265]
- [x] [Review][Patch] Clarification save binding 冲突或归档状态须 fail closed 并保留 evidence [`rpg_engine/save_manager.py`:1345]
- [x] [Review][Patch] 缺任一迁移字段的 legacy clarification 须可保守原位迁移 [`rpg_engine/save_manager.py`:2578]
- [x] [Review][Patch] Receipt JSON 淘汰必须同步有界清理 SQLite historical anchors [`rpg_engine/save_manager.py`:1592]
- [x] [Review][Patch] MCP low-level clarification publication failure/conflict 不得返回 dangling clarification [`rpg_engine/mcp_adapter.py`:1183]
- [x] [Review][Patch] Pending action 缺失 save binding 须保持精确 fail-closed 错误 [`rpg_engine/save_manager.py`:2578]
- [x] [Review][Patch] Platform 必须在 `ok=false` 的 canonical clarification outcome 上同步 binding lifecycle [`rpg_engine/platform_sidecar.py`:728]
- [x] [Review][Patch] Platform cancel 只能在原 binding generation 未变化时清理 mirror [`rpg_engine/platform_sidecar.py`:505]
- [x] [Review][Patch] Clarification answer/supersede 必须同时匹配 `expected_pending_id` 与 `clarification_id` [`rpg_engine/save_manager.py`:576]
- [x] [Review][Patch] 纯空白等规范化等价文本不得伪装为 fresh clarification answer [`rpg_engine/save_manager.py`:576]
- [x] [Review][Patch] `candidate_contract_mismatch` origin 只能来自已通过 strict 边界的明确语义候选不一致 [`rpg_engine/save_manager.py`:2531]
- [x] [Review][Patch] Cross-identity inspect 只返回完全脱敏的 conflict lifecycle [`rpg_engine/save_manager.py`:1087]
- [x] [Review][Patch] Pending TTL 必须严格等于 1800 秒且与 created/expires 时间一致 [`rpg_engine/save_manager.py`:2578]
- [x] [Review][Patch] 深层 JSON parser recursion 必须转换为结构化 fail-closed 错误 [`rpg_engine/save_manager.py`:2901]
- [x] [Review][Patch] `player_confirm()` 必须先拒绝 dual-active canonical state，不能绕过单一 pending invariant [`rpg_engine/save_manager.py`:820]
- [x] [Review][Patch] 每次 clarification publication 必须生成新的 owner CAS id，不能重用 Runtime 语义 id [`rpg_engine/save_manager.py`:699]
- [x] [Review][Patch] Platform identity gate 拒绝结果不得回显另一 caller 的 clarification/message ids [`rpg_engine/platform_sidecar.py`:505]

### Review Findings（Round 2）

- [x] [Review][Patch] Platform act reservation 必须同步 pending confirmation generation [`rpg_engine/platform_sidecar.py`:660]
- [x] [Review][Patch] Clarification waiting result 不得把 binding 回退到另一 active Save [`rpg_engine/platform_sidecar.py`:728]
- [x] [Review][Patch] Private platform gate rejection 不得通过 metrics 泄露 Save 路径或底层错误 [`rpg_engine/platform_sidecar.py`:364]
- [x] [Review][Patch] Legacy clarification 必须完整内存校验后才可原位写回 [`rpg_engine/save_manager.py`:1319]
- [x] [Review][Patch] 可恢复目录或同 ID 异 path 的 Save binding 必须保留 pending evidence [`rpg_engine/save_manager.py`:1355]
- [x] [Review][Patch] TTL wire 必须要求原始值为 exact integer 1800 [`rpg_engine/save_manager.py`:2640]
- [x] [Review][Patch] Malformed/dual pending 下 cancel 必须返回稳定脱敏 `invalid_state` [`rpg_engine/save_manager.py`:1177]
- [x] [Review][Patch] 补齐 two-process first publication、supersede-vs-confirm 与 deterministic focused gate [`tests/test_pending_lifecycle.py`:637]
- [x] [Review][Patch] `switch_save()` 必须在提交 registry 前完成 canonical pending fail-closed 检查 [`rpg_engine/save_manager.py`:265]
- [x] [Review][Patch] 极端 ISO 时间的 TTL 计算必须转换 `OverflowError` 为 owner 错误 [`rpg_engine/save_manager.py`:2640]
- [x] [Review][Patch] 深层 corrected candidate digest recursion 必须形成 typed fail-closed [`rpg_engine/save_manager.py`:2558]

### Review Findings（Round 3）

- [x] [Review][Patch] CAS generation 冲突必须按当前 pending 重算 identity，不能泄露后来 session token [`rpg_engine/save_manager.py`:1456]
- [x] [Review][Patch] 过期 platform binding 必须先完成 actor identity gate，cross-identity 拒绝不得回显私密 mirror/metrics [`rpg_engine/platform_sidecar.py`:1305]
- [x] [Review][Patch] 历史 receipt 淘汰遇已不存在的旧 Save 时不得永久阻断健康 Save 的 pending publication [`rpg_engine/save_manager.py`:1619]
- [x] [Review][Patch] Confirmation history read/write 边界必须拒绝重复 confirmation session hash [`rpg_engine/save_manager.py`:1560]
- [x] [Review][Patch] `actor_not_allowed` 的 cross-identity platform 拒绝必须使用私密脱敏结果 [`rpg_engine/platform_sidecar.py`:1307]
- [x] [Review][Patch] CLI 与 Save/MCP canonical surface 清单必须同步 `player cancel` / `player_cancel` [`docs/cli-contracts.md`:140]

### Review Findings（Round 4）

- [x] [Review][Patch] Player-facing owner 方法必须先校验 exact save/identity，再执行 legacy migration 或 expiry mutation [`rpg_engine/save_manager.py`:537]
- [x] [Review][Patch] Save 目录仍可恢复时 action orphan classification 必须保留 evidence 并返回 `invalid_state` [`rpg_engine/save_manager.py`:1377]
- [x] [Review][Patch] Legacy/canonical pending envelope 必须拒绝 raw session/actor identity 与未知顶层字段 [`rpg_engine/save_manager.py`:2661]
- [x] [Review][Patch] Pending save binding 必须拒绝重复 ID/path registry records，不能依赖首项匹配 [`rpg_engine/save_manager.py`:1377]
- [x] [Review][Patch] GM/maintenance view 的 low-level clarification 不得持久化到 player canonical lifecycle [`rpg_engine/mcp_adapter.py`:1183]
- [x] [Review][Patch] Matching fresh clarification answer 产生 query/blocked 时必须以第二阶段 CAS 终结旧 clarification [`rpg_engine/save_manager.py`:749]
- [x] [Review][Patch] History/SQLite anchor 淘汰在 abrupt termination 后必须可重试收敛且保持有界 [`rpg_engine/save_manager.py`:1605]
- [x] [Review][Patch] Canonical prompt artifact 表必须同步当前 AI client prompt version [`docs/prompt-contracts.md`:14]

### Review Findings（Round 5）

- [x] [Review][Patch] MCP `player_confirm` / `player_cancel` 省略 Save 时必须交由 SaveManager 选择当前 active Save，不能强制解析不存在或陈旧的 adapter default [`rpg_engine/mcp_adapter.py`]
- [x] [Review][Patch] 同一 platform session 的并发 act completion 必须重新 inspect canonical pending，并把 binding mirror 收敛到 owner truth [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Patch] Player turn、current Save 与 cancel 在任何 refresh/mutation 前必须全局拒绝重复 registry ID/path evidence [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Save record/path 均消失且无 confirmation claim 的 action 必须按可证明 orphan 清理；有 claim 的 action 继续 fail closed [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Confirmation history 必须保存有序 digest、以 latest retained Save SQLite meta 锚定，并拒绝重排既有 receipt [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] 已认证 owner 对过期 pending platform binding 的 cancel 必须到达 SaveManager，以取得 exact terminal cleanup [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Patch] CAS conflict 的 current identity 只有同时匹配原 exact Save 才可返回 pending id，不能跨 Save 泄露 token [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Fresh clarification answer 产生 terminal superseded query/blocked 时，platform mirror 必须回到 `active_game` 而非保留旧 clarification [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Patch] Latest receipt 在归档前必须重新对账目标 Save SQLite anchor、turn、command 与 event count，不能归档重算 digest 的伪造 evidence [`rpg_engine/save_manager.py`]
- [x] [Review][Dismiss] 跨 action/clarification 两文件的 crash-atomic single-envelope 建议与 AC 明确的 dual-active fail-closed、无 migration 边界冲突；与 Round 1 已核验 finding 重复，不在本 Story 扩展。

### Review Findings（Round 6）

- [x] [Review][Patch] `inspect_pending()` 省略 Save 时仍必须核对当前 active Save；合法跨 Save pending 返回脱敏 conflict，损坏 binding 先返回 `invalid_state` [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Low-level clarification publication 的已有 pending conflict 必须同时匹配 exact Save 与 identity 后才可公开 token [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] `switch_save()` 写 registry 前必须验证 canonical pending save binding/orphan evidence，损坏证据 fail closed [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] `create_save(activate=True)` / `duplicate_save(activate=True)` 必须经 canonical `switch_save()` owner gate，并回传 preserved lifecycle [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Corrected candidate 的 typed/blocked error 必须保留旧 clarification，不能误标 terminal superseded [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Confirmation history order authority 必须使用 bounded prepared→committed head，成功后清理旧 Save/legacy anchors，拒绝旧 snapshot rollback，publication restore 同步恢复 SQLite evidence [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] Platform cancel completion 清空 mirror 前必须重新 inspect canonical owner，不能覆盖并发发布的新 pending [`rpg_engine/platform_sidecar.py`]
- [x] [Review][Patch] Canonical 中文文档不得继续把 Story 6.5 supersede/cancel/clarification 描述为未定义 Backlog [`docs/save-and-campaign-packages.md`, `docs/testing-and-quality-gates.md`]

### Review Findings（Round 7）

- [x] [Review][Patch] Registry 无 active Save 时默认 `inspect_pending()` 无法证明 exact selected Save，必须返回脱敏 `invalid_state` 而非完整 active token [`rpg_engine/save_manager.py`]
- [x] [Review][Patch] 跨 Save receipt 淘汰必须同时删除该 receipt 的 exact historical 与 generic latest SQLite anchors，确保超出 8 条窗口后不再具有 replay authority [`rpg_engine/save_manager.py`]
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 8）

- [x] [Review][Patch] 当前 committed history 验证成功时必须清除不兼容的 stale prepared order anchor，不能让未发布 history 在稍后被提升 [`rpg_engine/save_manager.py`]
- [x] [Review][Decision] 省略 `save_path` 且 registry 无 active Save 时的默认 inspect 语义：用户于 2026-07-20 选择 fail-closed 推荐方案，保持脱敏 `invalid_state`；显式 Save 才能读取对应 pending。
- [x] Edge Case Hunter：CLEAN。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 9）

- [x] [Review][Patch] committed history 命中时须跨 registry Saves 清理 stale prepared/order anchors，仅保留当前 history head 的 committed authority [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] 用户冻结的 no-active omitted inspect 契约必须先于 `not_found`、identity conflict 与 orphan 分类，统一返回脱敏 `invalid_state` [`rpg_engine/save_manager.py`]。
- [x] Edge Case Hunter：CLEAN。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 10）

- [x] [Review][Patch] 已持有 `confirmation_claim` 或已有 durable turn evidence 的 action 必须先完成 Story 6.4 recovery/reconcile，任何 TTL 状态都不得被新 turn supersede [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] history JSON 缺失但任一已登记 Save 仍保留 SQLite order authority 时必须 fail closed，不能静默返回空 replay window [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] MCP low-level clarification gate 必须把实际显式/默认 Save path 薄转发给 canonical inspect，并在不可验证状态 fail closed；Acceptance Auditor 的同项 finding 已去重 [`rpg_engine/mcp_adapter.py`]。

### Review Findings（Round 11）

- [x] [Review][Patch] 缺失 history 的 authority 扫描必须先验证事实库存在并使用 SQLite read-only URI，禁止因默认 connect 创建缺失 `data/game.sqlite` [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] SQLite claim anchor 已写但 pending claim 尚未发布的 crash 窗口必须按当前 pending 重建 expected claim digest 并进入 recovery-required，不能被 matching supersede 覆盖 [`rpg_engine/save_manager.py`]。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 12）

- [x] [Review][Patch] committed history 跨 Save cleanup 必须只以 SQLite `mode=rw` 打开既有事实库，缺失数据库 fail closed 且禁止创建；Acceptance Auditor 的同项 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending recovery/claim 探针及其余 Story 6.5 evidence 读取必须统一使用 SQLite `mode=ro` 打开既有事实库，异常不得产生空数据库副作用 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] clarification payload 若携带 `clarification_id`，必须与 envelope owner id 精确一致；冲突 evidence fail closed 并原样保留 [`rpg_engine/save_manager.py`]。

### Review Findings（Round 13）

- [x] [Review][Patch] clarification payload id 必须以原始字符串值与 envelope id 精确相等，禁止 `clean()`、类型转换或 whitespace 绕过 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] registry 仍精确记录 Save 但目录暂缺时属于可恢复 binding evidence，inspect 必须 `invalid_state` 并保留 pending，不能当作 orphan 删除 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] `platform` 与 `session_key` 必须成对出现；半对 identity 在 Runtime/publication 前结构化拒绝，不能创建无法由同 identity confirm 的 pending [`rpg_engine/save_manager.py`]。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 14）

- [x] [Review][Patch] canonical pending envelope 必须拒绝 `platform` / `session_key_hash` 半绑定、非 canonical identity 字符串与非法 hash evidence；Edge Case Hunter 同项已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] action/clarification owner token 必须是原始、非空、无首尾空白的字符串，禁止 `clean()` 隐式转换或裁剪后成为有效 CAS token [`rpg_engine/save_manager.py`]。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 15）

- [x] [Review][Patch] 外部 `expected_pending_id` / `clarification_id` / cancel token 必须按原始字符串精确比较，首尾空白或非字符串不得经 `clean()` 获得 supersede/cancel authority；三路同类 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending `save_id` / `save_path` 必须是原始 canonical 字符串且 path 规范化结果不变，禁止 whitespace/隐式类型转换后匹配 Save [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] clarification external candidate digest 必须为空或 64 位小写十六进制，`candidate_contract_mismatch` 必须持有非空 digest，非法 evidence fail closed [`rpg_engine/save_manager.py`]。

### Review Findings（Round 16）

- [x] [Review][Patch] `player_confirm` active commit 与 historical replay 均必须先要求原始、非空、canonical string `session_id`，禁止 trim/类型转换后获得确认 authority [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] partial legacy clarification 必须逐项验证任何已存在的 TTL/origin/digest evidence，migration 仅补缺失字段；已存在非法或冲突值 fail closed 并原样保留 [`rpg_engine/save_manager.py`]。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 17）

- [x] [Review][Patch] confirmation receipt 的 `receipt_digest` 必须是原始 64 位小写十六进制并与重算值精确一致，禁止 whitespace 经 `clean()` 绕过 latest/history tamper gate [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] `switch_save()` 对 claimed/durable recovery action 仍只保留原 binding，wire 必须按 AC2 返回 `preserved`；recovery 限制由 supersede/cancel/confirm 路径执行 [`rpg_engine/save_manager.py`]。
- [x] Edge Case Hunter：CLEAN。

### Review Findings（Round 18）

- [x] [Review][Patch] history JSON `order_digest` 与 SQLite committed/prepared anchor 必须是原始 64 位小写十六进制并精确比较，禁止 whitespace 经 `clean()` 绕过顺序 tamper gate [`rpg_engine/save_manager.py`]。
- [x] Edge Case Hunter：CLEAN。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 19）

- [x] [Review][Patch] 过期但已有 file/SQLite confirmation claim 的 action 必须保留完整 recovery evidence 并返回 recovery-required，不能删除 pending 后遗留孤立 anchor [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] persisted `claim_digest` 与 SQLite claim anchor 必须是原始 64 位小写十六进制并精确匹配，禁止 whitespace 获得 confirm authority；Blind/Edge 同项已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] generic/historical SQLite receipt anchors 必须以原始 canonical digest 与 receipt 精确比较，双 anchor whitespace tamper 不得授权 replay [`rpg_engine/save_manager.py`]。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 20）

- [x] [Review][Patch] 显式 inspect 的 supplied Save binding 必须先于 orphan 分类与清理精确匹配 pending Save；错误 Save 不得删除另一 Save 的 orphan pending [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending `created_at` / `expires_at` 必须是原始 canonical 字符串，禁止 whitespace 经 `clean()` 后获得有效 TTL evidence [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] latest receipt replay 也必须先验证 history JSON 与 SQLite order authority；缺失 history 时不得通过 latest 快路径绕过 fail-closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] receipt `confirmation_session_hash` 必须是原始 64 位小写十六进制，并在 identity、history key 与去重路径精确使用原值 [`rpg_engine/save_manager.py`]。

### Review Findings（Round 21）

- [x] [Review][Patch] receipt 的 Save binding、command/turn、payload digest、identity hash 与 result 标量必须在 envelope 入口完整 canonical 校验，下游 authority 对账精确使用原值；Blind、Edge 与 Acceptance 同类 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending `created_at` / `expires_at` 必须是 timezone-aware、UTC `+00:00` 且与解析后 `.isoformat()` 精确一致；naive、`Z` 与非 UTC offset evidence 均 fail closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] inflight clarification answer 遇同 identity 精确 cancel 后，platform 必须采用 canonical `not_found` terminal truth 将陈旧 mirror 收敛到 `active_game` [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] 省略显式 Save 的 `player_turn()` 必须在第一阶段与发布/终结阶段把 active Save exact id/path 纳入 owner CAS；锁外 Runtime 期间切换 active Save 时拒绝发布旧 Save pending [`rpg_engine/save_manager.py`]。

### Review Findings（Round 22）

- [x] [Review][Patch] platform act completion 发现较新 `INACTIVE` binding 时必须保留该 revision；即使 canonical inspect 返回 terminal `not_found` 也不得重新激活 [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] developer low-level `start_turn` / `preview_from_text` 必须冻结 Runtime 前 pending generation，并由 SaveManager 在 clarification publication 前执行 owner CAS；inflight cancel/change 时脱敏 conflict [`rpg_engine/save_manager.py`, `rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] registry-active low-level 调用必须只解析一次实际 Runtime Save，并在 publication 阶段重检 active selection；inflight switch 不得把 Save A 的 clarification 错绑到 Save B [`rpg_engine/save_manager.py`, `rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] 二阶段 action/clarification supersede 与 terminal resolution 必须在 owner lock 内重检当前 session expiry；普通 expiry 清理并返回 terminal，recovery evidence 则保留并 fail closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] canonical CLI 文档的 Platform 子命令清单与合同必须同步已公开的 `platform cancel` [`docs/cli-contracts.md`]。
- [x] Verification 收敛：low-level CAS snapshot 对 standalone trusted runtime Save 只冻结路径/generation；未发生 clarification publication 时不得要求 registry record，focused 回归恢复绿色。

### Review Findings（Round 23）

- [x] [Review][Patch] standalone trusted low-level Save 的 Runtime clarification 必须保持 preview-only 原结果且不创建 canonical pending；snapshot 显式标记 `canonical_publication=false`，registry-invalid 状态仍 fail closed [`rpg_engine/save_manager.py`, `rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] low-level begin 必须是只读 owner snapshot：在任何 migration/expiry mutation 前核验 exact Save/identity；cross-owner 或 cross-Save 调用脱敏拒绝并原样保留 evidence [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] 二阶段 publication 必须先以 `migrate=False` 比较 raw kind/generation/identity；后来 session 导致 CAS 失败时不得先迁移或改写对方 legacy evidence [`rpg_engine/save_manager.py`]。
- [x] Edge Case Hunter：CLEAN。

### Review Findings（Round 24）

- [x] [Review][Patch] standalone preview-only snapshot 不具 canonical publication authority，必须跳过 workspace canonical pending owner gate；其他 Save 的 action/clarification 原样保留且 Runtime preview 仍可返回 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] registered low-level publication snapshot 必须是必填、绑定 canonical platform/session-key-hash/actor-id-hash 的不可转移 owner evidence；cross-identity 或 missing snapshot 在任何写入前拒绝 [`rpg_engine/save_manager.py`, `rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] action 与 low-level clarification publication 必须在 owner lock 内持有 registry lock，原子重检 frozen Save 仍唯一、registered、unarchived、healthy，active 模式还须保持 exact selection；变化时脱敏拒绝且不写 pending [`rpg_engine/save_manager.py`]。
- [x] Blind Hunter：CLEAN。

### Review Findings（Round 25）

- [x] [Review][Patch] owner lock 内的 frozen registry gate 必须实时只读校验 exact Save 目录、package 与 `data/game.sqlite`；仅依赖 registry 缓存 health 会在 Save 被删除或损坏后错误发布 pending；三路同类 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] low-level publication snapshot 必须使用不可篡改的完整性凭据，任何对 `require_active_save_match`、Save/identity 或 generation 字段的修改都必须在写入前拒绝 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending owner 必须维护单调 lifecycle revision，并纳入 player-turn 与 low-level 两阶段 CAS；`empty → pending → cancel → empty` 的 ABA 不能让旧 Runtime 结果复活 [`rpg_engine/save_manager.py`]。
- [x] Verification：focused `247 passed, 125 subtests passed`；扩展确定性并发/ABA 集 `13 passed`。

### Review Findings（Round 26）

- [x] [Review][Patch] MCP adapter 不得在 HMAC 验证前读取 mutable `canonical_publication=false` 并跳过 owner；registered snapshot 的任何字段篡改必须先由 SaveManager 拒绝 [`rpg_engine/mcp_adapter.py`, `rpg_engine/save_manager.py`]。
- [x] [Review][Patch] lifecycle revision 必须在 canonical 第一阶段 owner lock 内初始化为非零值，二阶段缺失/损坏不得回退为 0；revision 文件丢失后的 ABA 必须 fail closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] standalone trusted preview-only 不具 canonical publication authority，不得读取或初始化 workspace lifecycle revision；无关 malformed revision 必须原样保留且不阻断 preview [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] matching fresh clarification answer 遇 `invalid_request` 或 Story 6.1 typed external contract error 时必须保留旧 clarification；正常 query/blocked 的 terminal supersede 语义不变 [`rpg_engine/save_manager.py`]。
- [x] Verification：focused `252 passed, 125 subtests passed`；新增 tamper、revision-loss、standalone isolation 与 typed-error 场景全部通过。

### Review Findings（Round 27）

- [x] [Review][Patch] Story 6.1 typed external contract error 即使夹带 clarification payload，也不得创建或替代 canonical clarification；player turn 与 low-level owner 共用同一 error-preservation gate [`rpg_engine/save_manager.py`, `rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] lifecycle evidence 必须同时比较随机 incarnation 与单调 revision；revision 文件丢失后由只读 query 重建也不能恢复旧 Runtime 的发布 authority [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] bounded JSON reader 必须把 Python 超长整数解析 `ValueError` 收敛为稳定 `SaveManagerError`，不能泄漏底层异常 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] low-level HMAC snapshot 必须绑定 workspace root 与 exact registry owner scope；同构 Save id/path/revision 的另一 workspace 不能重放 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] canonical inspect/cancel 必须验证 lifecycle revision evidence；malformed revision 返回 player-safe `invalid_state` 并保留 pending，standalone preview-only 仍忽略该 evidence [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] platform cancel completion 仅在 canonical terminal 且原 binding generation 未变化时清 mirror；invalid/unknown inspection 保留，较新 `INACTIVE` binding 永远优先 [`rpg_engine/platform_sidecar.py`]。
- [x] Acceptance Auditor：CLEAN。

### Review Findings（Round 28）

- [x] [Review][Patch] active Save 实际 selection 变化必须推进 publication CAS revision；默认 player turn 与 registry-active low-level snapshot 均须拒绝 `Save A → B → A` ABA [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] low-level snapshot 验签后必须只读取 validated immutable copy；caller 并发修改原始 dict 不能在 HMAC check 后改变 active-selection gate [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] platform cancel 只有在 canonical inspect 的 `ok/status/lifecycle.state` 精确一致且属于 terminal allowlist 时才可清 mirror；unknown/inconsistent response 一律保留 [`rpg_engine/platform_sidecar.py`]。
- [x] Acceptance Auditor：CLEAN。
- [x] Verification：focused `264 passed, 125 subtests passed`；active-selection ABA、snapshot TOCTOU 与 inconsistent terminal 定向场景通过。

### Review Findings（Round 29）

- [x] [Review][Patch] platform audit 顶层 `session_id` / pending token 必须与嵌套 payload 使用同一 SHA-256 规则；不得因 summary 拆值而把原始 owner token 写入 audit [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] platform act completion 与 cancel 必须复用同一 exact canonical inspect classifier；`ok=true`、顶层 status 与 lifecycle state 精确一致且命中 active/terminal allowlist 才可更新 mirror，其余保留 [`rpg_engine/platform_sidecar.py`]。
- [x] Edge Case Hunter：CLEAN。
- [x] Verification：focused `266 passed, 125 subtests passed`；audit token、act/cancel inconsistent inspect 场景通过。

### Review Findings（Round 30）

- [x] [Review][Patch] platform canonical inspect classifier 必须拒绝非 dict、`errors` 非空、active/migrated 缺失 canonical `pending_id`、非法 status/kind 组合及 terminal 携带 token；act/cancel 均 fail closed 保留 mirror [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] low-level MCP `start_turn` / `preview_from_text` 必须实际暴露并薄转发可选 `actor_id`，使 SaveManager snapshot/clarification 的 actor hash presence-parity 可由同 actor 延续 [`rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] platform audit 自由文本中的 generated `player_action:<hex>` / `clarification:<hex>` 也必须替换为批准 SHA-256，不能只依赖字段名哈希 [`rpg_engine/platform_sidecar.py`]。
- [x] Acceptance Auditor：CLEAN。
- [x] Verification：focused `268 passed, 133 subtests passed`；strict inspect wire、actor-bound low-level 与 audit free-text token 场景通过。

### Review Findings（Round 31）

- [x] [Review][Patch] platform canonical inspect classifier 必须拒绝顶层或 lifecycle 内伪装成 owner token 的 alias 字段；terminal token alias 不能取得 terminal authority [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] MCP audit 自由文本中的 generated `player_action:<hex>` / `clarification:<hex>` 必须使用同一 SHA-256 脱敏规则，不能把 owner token 写入审计 [`rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] matching fresh clarification answer 在终结旧 clarification 前必须重新冻结 registry、Save package 与 SQLite 健康状态；inflight archive/delete/corruption 时保留原 evidence 并 fail closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] canonical Story 6.5 focused/race gate 文档必须纳入 platform AI simulation 与已扩展的 active-selection、revision、low-level CAS 场景 [`docs/testing-and-quality-gates.md`]。
- [x] [Review][Patch] Story artifact 的 CLI source 路径修正为实际 `rpg_engine/cli_v1.py`。
- [x] Verification：定向 compile、Ruff 与回归 `7 passed, 9 subtests passed`。

### Review Findings（Round 32）

- [x] [Review][Patch] platform canonical inspect 必须以 exact 顶层/lifecycle key allowlist 验证 wire；任何未知 token alias 或额外字段均不得取得 terminal/active authority；Blind 与 Acceptance 同项已去重 [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] publication 与 clarification terminal resolution 的 live registry/package/SQLite freeze 必须先于 expiry 清理；到期与 archive/delete/corruption 并发时保留原 evidence 并返回 conflict [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] clarification payload 必须递归拒绝 raw session/actor identity 字段，并在 player-turn、low-level publication 时拒绝 raw identity value；tampered persisted payload fail closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] `switch_save()` 对 missing/archived/invalid target 的失败路径不得先迁移 legacy clarification 或推进 lifecycle revision；switch 只读并保留原 evidence [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] frozen Save gate 必须将 registry lock/read/schema/path/health 异常统一收敛为 `SavePublicationConflict`，让 owner 返回稳定脱敏 lifecycle conflict 而非裸异常 [`rpg_engine/save_manager.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `6 passed, 10 subtests passed`。

### Review Findings（Round 33）

- [x] [Review][Decision] raw identity 隐私策略采用用户批准的“精确结构化检测”：递归拒绝 reserved identity field，字符串 key/scalar 仅以 exact raw 值或持久化 identity hash 对账拒绝；不改变合法短 platform/session/actor ID 合同。
- [x] [Review][Patch] clarification privacy traversal 必须先复用 bounded JSON shape gate 并使用迭代遍历；循环、超深或超大 payload 收敛为 `SaveManagerError`，不得泄漏 `RecursionError` [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] player-turn 与 low-level publication 必须拒绝 nested key/scalar 中的 exact raw identity；persisted read 必须以 envelope identity hash 检出 exact raw scalar/key tamper，同时不误杀普通短 ID 文本；Blind、Acceptance 与 Edge 同类 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] player-turn 第一阶段在任何 legacy migration、recovery/expiry mutation 前必须验证 pending Save binding；默认 active Save 已 archived/invalid 时保留 action/clarification evidence 并返回 `invalid_state` [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] platform canonical inspect classifier 必须按 lifecycle state/kind 使用 exact required/allowed shape，并校验 token prefix、TTL/timestamp 与 clarification origin；合法字段名的非法组合不得获得 mirror authority [`rpg_engine/platform_sidecar.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `8 passed, 13 subtests passed`。

### Review Findings（Round 34）

- [x] [Review][Patch] pending live binding classification 必须复用 exact registry/package/SQLite read-only gate；默认 active Save 在 owner classification 前或第一阶段内损坏时返回结构化 `invalid_state`，inspect/migration/expiry 均保留 evidence；三路同根 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] platform token classifier 必须与 SaveManager canonical owner 合同一致，接受 bounded、非空、无首尾空白的 legacy clarification token（如 `clarify:*`），不能由 adapter 发明更窄格式 [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] action/clarification pending writer 必须把超长整数等 `json.dumps` 的 `TypeError`/`ValueError`/`RecursionError` 收敛为稳定 `SaveManagerError`，且不创建 pending [`rpg_engine/save_manager.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `7 passed, 15 subtests passed`。

### Review Findings（Round 35）

- [x] [Review][Patch] platform action token 继续要求 `player_action:<32 hex>`；legacy clarification token 虽允许旧格式，仍必须服从 owner `MAX_PENDING_STRING_LENGTH`；Blind、Acceptance 与 Edge 同项已去重 [`rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] 默认 Save 不可证明时的结构化兜底必须完全脱敏为 `kind=unknown/invalid_state`，不能仅凭 identity 相同回显另一 Save 或 no-active pending token/save id [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] 第一阶段已持 frozen registry lock 的 legacy migration 必须显式复用 live verification，禁止 `pending_orphan_classification()` 对同一 registry lock 自重入并等待超时 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] orphan proof 与 clear 之间必须在 owner+registry 临界区重新核验 record/path 仍缺失；并发恢复 Save 时保留 pending 并返回 `invalid_state` [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending JSON shape、writer、stable digest 与 low-level HMAC 必须把 invalid Unicode/UTF-8 编码异常收敛为稳定 `SaveManagerError` [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] 默认 `inspect_pending()` 遇 malformed registry/read/schema 异常必须返回脱敏 `invalid_state`，保留 pending/revision，不泄漏底层解析错误 [`rpg_engine/save_manager.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `7 passed, 17 subtests passed`。

### Review Findings（Round 36）

- [x] [Review][Patch] `inspect_pending()` migration/expiry 与 `player_cancel()` migration/expiry/cancel 必须在同一 owner+frozen registry/package/SQLite 临界区完成；archive/corruption 先发生时保留 evidence 并返回 `invalid_state`；Edge 与 Acceptance 同项已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] 默认 `player_turn()` 遇 malformed registry/schema 且存在 pending 时必须走完全脱敏 `kind=unknown/invalid_state` 兜底，不泄漏 JSON 行列或 owner evidence [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] owner compare token 与 platform `pending_id/save_id/timestamp` wire 必须同时满足 bounded、canonical UTF-8；lone surrogate 不得进入 hash、mirror 或 binding persistence；Blind 与 Edge 同项已去重 [`rpg_engine/save_manager.py`, `rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] orphan classification 与最终 clear 必须检查 matching latest/history confirmation receipt；receipt match、损坏或无法核验时返回 `invalid_state` 并保留 pending [`rpg_engine/save_manager.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `6 passed, 19 subtests passed`。

### Review Findings（Round 37）

- [x] [Review][Patch] 默认 `player_turn()` 遇任意 registry resolution failure 且 canonical pending 存在时必须统一返回完全脱敏的 `kind=unknown/invalid_state`；不得靠错误消息 allowlist 判断隐私边界，显式 Save 与无 pending 路径仍保留原错误合同 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] 外部 `platform` / `session_key` / `actor_id` 必须在任何 clean/hash/compare/snapshot 前验证为 bounded valid UTF-8 string；非法代理字符、超长或非字符串输入稳定 fail closed，pending 与事实均不变；registry 非对象、记录非数组及非法 UTF-8 同步纳入安全兜底 [`rpg_engine/save_manager.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `4 passed, 6 subtests passed`。

### Review Findings（Round 38）

- [x] [Review][Patch] MCP audit 与 platform sidecar 必须在 binding lookup、gate、audit hash/snapshot 前拒绝非字符串、超长或非法 UTF-8 的 platform/session/actor identity；invalid identity 走私密结构化 rejection，best-effort audit 构造失败不得改变 owner 结果；三路同根 finding 已去重 [`rpg_engine/mcp_adapter.py`, `rpg_engine/platform_sidecar.py`]。
- [x] [Review][Patch] registry reader 必须 bounded、拒绝任意层 duplicate JSON key、非有限数和 escaped invalid Unicode；malformed evidence 不得 last-wins 获得 active/pending authority或在 refresh 中被规范化重写 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] orphan 判定遇 confirmation session hash 相同但 Save binding 冲突的 canonical receipt 时必须按 evidence uncertainty 返回 `invalid_state` 并保留 pending，不能将矛盾证据视为不存在 [`rpg_engine/save_manager.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `6 passed, 23 subtests passed`。

### Review Findings（Round 39）

- [x] [Review][Patch] raw platform event identity alias 不得经 `clean()/str()` 把非字符串洗成 authority；start/act/confirm/cancel、enabled prewarm 与 deactivate 必须在任何 expiry housekeeping、binding lookup/write、hash 或 audit 前执行同一原始 bounded UTF-8 gate；非法输入不得改变既有过期 binding；Blind、Edge 与 Acceptance 同根 finding 已去重 [`rpg_engine/platform_sidecar.py`, `rpg_engine/platform_prewarm.py`]。
- [x] [Review][Patch] MCP `intent_preflight`、`start_turn`、`preview_from_text` 必须在 publication snapshot、Runtime/SQLite 前验证原始 platform/session/actor identity，禁止 helper 以 `str()` 生成 owner evidence [`rpg_engine/mcp_adapter.py`]。
- [x] [Review][Patch] registry writer 必须在 atomic replace 前应用与 strict reader 对称的 bounded canonical JSON shape/UTF-8/size 验证；create/duplicate Save 在 registry publication 失败时移除本次新建临时目标，不能遗留未注册 Save 或写出自拒绝 registry [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] cached registry path 每次 read/write 都必须重新拒绝 symlink、越界 parent 与非 regular file；manager 初始化后的 symlink 替换不能取得 workspace registry authority [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] start 的私密 `invalid_identity` rejection 与 act/confirm/cancel 一致不得返回全局 binding metrics，避免跨身份存在性 oracle [`rpg_engine/platform_sidecar.py`]。
- [x] Verification：定向 compile、Ruff 与回归 `10 passed, 33 subtests passed`；扩展 pending/platform/MCP focused `241 passed, 138 subtests passed`。

### Review Findings（Round 40）

- [x] [Review][Patch] registry read/write 必须以 root-relative `dir_fd`、`O_NOFOLLOW`、regular-file `fstat` 与目录/文件 inode recheck 绑定同一 authority；check→open/replace 窗口内 parent rename/symlink 替换必须中止，不能读写外部 registry [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] registry campaigns/saves 的每项必须是 object，active Save id 与 record id/path authority 必须是 bounded canonical UTF-8 string/null；numeric/boolean evidence 不得被 `clean()/str()` 授权，refresh 不得静默过滤 malformed entries [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] create/duplicate Save 的 publication rollback 只能删除 inode/dev 仍与本次创建目录精确一致的目标；并发 rename+replacement 时不得 blind `rmtree` 删除他方目录 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] pending action/clarification、lifecycle revision、receipt 与 history 的 canonical reader/writer/removal 必须复用 anchored no-follow regular-file IO；leaf symlink、check→open race、FIFO/device 与底层 `OSError` 稳定 fail closed，不能采用外部 evidence、阻塞或泄漏裸异常 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] platform `message_id` 在 expiry、prewarm、reservation/binding write 与 audit 前必须是 bounded、非空、canonical valid UTF-8；raw event 仅允许受控 numeric scalar normalization，list/dict/surrogate/oversize 私密拒绝且不改 binding [`rpg_engine/platform_prewarm.py`, `rpg_engine/platform_sidecar.py`]。
- [x] [Review][Dismiss] “拒绝 clarification 字符串中包含 raw identity 子串”违反 Round 33 用户批准的精确结构化检测边界；仅 exact structured key/scalar/raw hash 对账属于当前 AC，substring heuristic 会误杀合法文本，故不实施。
- [x] Verification：anchored registry/pending、strict writer、rollback 与 message-id 定向 compile/Ruff 回归 `15 passed, 29 subtests passed`。

### Review Findings（Round 41）

- [x] [Review][Patch] canonical registry、pending/clarification、receipt/history、revision 与 shared lock 路径必须保留 root-relative lexical leaf，再由 `dir_fd`/`O_NOFOLLOW` anchored walk 校验；预先 `Path.resolve()` 不得把 workspace 内 symlink 洗成 authority；Blind 与 Acceptance 同根 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] canonical removal 必须将已观察 entry 原子移入随机 quarantine、复核 inode/dev 后仅删除该 exact entry；check→unlink 期间出现的 replacement 必须保留并 fail closed [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] atomic writer 必须将 published destination 与 temporary inode/dev 对账，并区分 replace 前失败与 replace 后 durability uncertain；post-replace directory fsync 失败不得触发 create/duplicate 删除已登记 Save；Blind 与 Edge 同根 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] create/duplicate 从目标目录首次创建起即进入 rollback 保护；rollback 以 anchored parent + atomic quarantine + inode/dev 复核隔离 exact target，不能在 `lstat→rmtree` 竞态中删除 replacement；Blind 与 Acceptance 同根 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] registry `schema_version` reader/writer 必须要求原始 exact string `"1"`；numeric/boolean schema 不得获得 authority 或被 refresh 静默规范化；Blind 与 Edge 同根 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] invalid platform `message_id` 的 enabled/disabled/direct/queue prewarm rejection 不得原样或经 `clean()` 字符串化回显；所有 result 统一只输出 valid bounded canonical message id [`rpg_engine/platform_prewarm.py`, `rpg_engine/platform_sidecar.py`]。
- [x] Verification：三路 finding 定向回归、compile 与 Ruff 通过；七文件 focused `312 passed, 191 subtests passed`。

### Review Findings（Round 42）

- [x] [Review][Patch] quarantine removal 必须在最终 `unlink/rmtree` 紧邻前重新核验 anchored parent 与 exact entry inode/type；在 recheck 前 parent 已移出 workspace 或 quarantine 已被替换时保留 evidence 并 fail closed，不能先删除 root 外或他方 entry 再报错；Edge 与 Acceptance 同根 finding 已去重 [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] conditional unlink 的 quarantine mismatch 必须以 raw no-follow stat 识别 symlink/FIFO/device，并以不覆盖 canonical name 的 hard-link restore 保留 replacement；regular-file validator 不得在恢复分支前抛错；Blind finding [`rpg_engine/save_manager.py`]。
- [x] [Review][Patch] shared lock 必须持有独立 companion authority inode；holder 期间单独替换 primary leaf 不能形成 split-lock，同时不能用 workspace-global lock 阻塞合法的不同 lock domain 并发 [`rpg_engine/save_manager.py`]。
- [x] Verification：quarantine parent/replacement、special-file restore、split-lock 与跨 lock-domain 并发定向回归通过；七文件 focused `316 passed, 191 subtests passed`。

### Review Findings（Round 43）

- [x] Edge Case Hunter：CLEAN；定向验证 parent-moved quarantine、symlink/FIFO replacement、single-leaf split-lock 与不同 lock-domain 并发 `6 passed`。
- [x] [Review][Dismiss] “最后一次 recheck 返回后由 hostile same-UID controller 精确替换随机 quarantine，再要求 inode-conditional unlink/rmtree”不属于 Story 6.5 的 cooperative engine/process concurrency：POSIX 不提供按 inode 条件删除目录项，继续增加 check 只会递归产生相同窗口；当前实现已用随机 quarantine、raw no-follow identity、删除前紧邻 re-anchor 与删除后验证覆盖范围内 race，扩大到 hostile syscall/filesystem controller 需要新的 OS authority/threat model。
- [x] [Review][Dismiss] “holder 期间同时替换 primary、companion 及任意后续命名 authority”属于同一递归 hostile-filesystem-controller 模型；当前 companion 已关闭 in-scope single-leaf replacement 且保持不同 lock domain 并发。要求不可替换的 per-domain kernel namespace 需要新增跨平台锁设计/依赖并扩大 P0 边界，缺少本 Story 规划证据；Blind 与 Acceptance 同项已去重。
- [x] Verification：R43 无 scope-valid patch；七文件 focused 绿灯保持 `316 passed, 191 subtests passed`。

### Review Findings（Round 44）

- [x] [Review][Patch] confirmation 与 companion authority 的 thread-local reentrant state 必须绑定当前 PID 并维护 depth；fork child 不得继承 parent held-set 后跳过 kernel lock，父持锁期间 child 同 domain 必须 timeout/fail closed [`rpg_engine/save_manager.py`]。
- [x] Edge Case Hunter：CLEAN；Acceptance Auditor：CLEAN（其快照在 fork patch 前，故不作为最终 clean round）。
- [x] Verification：fork inheritance、single-leaf split-lock、不同 lock-domain 并发、confirmation/registry concurrency 定向回归通过；七文件 focused `317 passed, 191 subtests passed`。

### Review Findings（Round 45）

- [x] Blind Hunter：CLEAN；Edge Case Hunter：CLEAN。
- [x] [Review][Patch] kernel lock release 必须绑定实际 acquisition PID；fork child 正常 unwind 继承 context 时只能关闭自己的 fd 引用，不得对共享 open-file description 执行 `LOCK_UN` 释放 parent 仍持有的 primary/companion lock [`rpg_engine/save_manager.py`]。
- [x] Verification：child normal-unwind、PID-bound reentrant、single-leaf split-lock 定向回归通过；七文件 focused `318 passed, 191 subtests passed`。

### Review Findings（Round 46）

- [x] Blind Hunter：CLEAN。
- [x] Edge Case Hunter：CLEAN；定向回归 `8 passed`。
- [x] Acceptance Auditor：CLEAN；定向回归 `3 passed, 158 deselected`，`py_compile` 与 Ruff 通过。
- [x] Verification：三路 fresh review 无 `[Review][Patch]`、`[Review][Decision]` 或 `[Review][Defer]`；本轮当时 clean，累计自动应用 `183` 个有效 patch；后续 adjacent gate 修正使该绿灯失效并继续收敛。

### Review Findings（Round 47）

- [x] Blind Hunter：CLEAN；确认 adjacent 测试同步现行契约且未掩盖 production 缺陷。
- [x] Edge Case Hunter：CLEAN；定向边界 `14 passed, 17 subtests passed`，SaveManager `35 passed, 37 subtests passed`，confirmation replay `23 passed, 6 subtests passed`。
- [x] [Review][Patch] Story File List 必须列入本轮 Story-owned adjacent 修正 `tests/test_cross_campaign_context_smoke.py`；Acceptance Auditor 定向回归 `4 passed, 14 subtests passed`，`py_compile` 与 `git diff --check` 通过。
- [x] [Review][Dismiss] `sprint-status.yaml` 的 `last_updated=2026-07-20` 与 Epic 7 additions 均为 Story 启动前用户既存规划 hunk；按仓库归属边界只暂存 6.5 状态，不以日期一致性为由覆盖或混入。
- [x] Verification：完整 adjacent `286 passed, 516 subtests passed`；本轮应用 1 个有效 artifact patch，累计自动应用 `184` 个 review patch。

### Review Findings（Round 48）

- [x] [Review][Patch] Debug Log、Completion Notes 与 Change Log 的 review provenance 必须同步 Round 47 后的实际轮次/patch 数，且不得在 post-patch 全套 required gates 完成前宣称最终验证已完成；三路同根 finding 已去重。
- [x] Verification：Blind、Edge 与 Acceptance 对 code/tests/File List/ownership 均无新 finding；Edge 定向 `6 passed, 2 subtests passed`，Markdown links、相邻文件 `py_compile` 与 `git diff --check` 通过。
- [x] 本轮应用 1 个有效 artifact patch，累计自动应用 `185` 个 review patch；下一轮 fresh review 与最终 required gates 待完成。

### Review Findings（Round 49）

- [x] Edge Case Hunter：CLEAN；定向验证 `6 passed, 4 subtests passed`。
- [x] [Review][Patch] 最终 fresh review 与 post-patch required gates 尚未完成时，Story、Sprint 6.5、Task 7 与最终 gate 子项不得提前标为完成；Blind 与 Acceptance 同根 finding 已去重。
- [x] Verification：三路对 AC1–AC5 code/docs、File List、ownership 与 adjacent contract 均无新偏差；本轮应用 1 个有效 artifact/status patch，累计自动应用 `186` 个 review patch。

### Review Findings（Round 50）

- [x] Blind Hunter：CLEAN。
- [x] Edge Case Hunter：CLEAN；定向验证 `6 passed, 2 subtests passed`。
- [x] Acceptance Auditor：CLEAN；`git diff --check` 与相邻文件 `py_compile` 通过。
- [x] Verification：三路 fresh review 为 0 `[Review][Patch]`、0 `[Review][Decision]`、0 `[Review][Defer]`；最终 clean review round，累计自动应用 `186` 个 review patch。

### Review Findings（Round 51）

- [x] Blind Hunter：CLEAN；确认 full-suite 测试修正恢复 canonical 前置条件且未削弱 Story 1.10 no-mutation oracle。
- [x] Edge Case Hunter：CLEAN；含 dual-active fail-closed 正向控制的定向验证 `10 passed, 7776 subtests passed`。
- [x] Acceptance Auditor：CLEAN；定向验证 `9 passed, 7776 subtests passed`，相邻文件 `py_compile` 与 `git diff --check` 通过。
- [x] Verification：首次 post-R50 full suite 为 `1809 passed, 2678 subtests passed, 9 failed`；9 项均复现为失效测试前置——temporary registry 缺 strict schema 及 Intake 测试非法 dual-active。修正后不改 production，三路 fresh review 0 Patch/Decision/Defer；累计 review patch 仍为 `186`。

### Final Verification（post-Round 51 clean diff）

- [x] Focused：`318 passed, 191 subtests passed`（96.38 秒）。
- [x] Adjacent：`286 passed, 516 subtests passed`（249.51 秒）。
- [x] Campaign：`v1_minimal_adventure` 与 `small_cn_campaign` 的 validate/test 全部 OK。
- [x] Docs/static：216 个 Markdown 文件链接通过；全仓 `py_compile`、full Ruff、`git diff --check` 全部通过。
- [x] Repository full suite：`1818 passed, 10454 subtests passed`（855.94 秒）。

## Dev Notes

### 实施前可复现缺口

- `SaveManager.player_turn()` 当前在 route/validation 前无条件清除 action pending，并在 ready/clarification/blocked 分支静默互相清除；这既破坏 compare-and-supersede，也让 malformed candidate 或 query 抹去旧确认上下文。[Source: `rpg_engine/save_manager.py` — `SaveManager.player_turn`]
- Action pending 已有 1800 秒 TTL 与 save/platform/session/actor 绑定；clarification 只有 created time，没有 expiry/origin，read/clear 也缺少与 action 同等级的 bounded/duplicate-key/path保护。[Source: `rpg_engine/save_manager.py` — pending action/clarification helpers]
- MCP developer low-level clarification guard 当前由 `AIGMMCPAdapter.pending_clarifications` 进程内字典拥有，adapter restart 即丢失。[Source: `rpg_engine/mcp_adapter.py` — clarification guard helpers]
- Platform 已能镜像 binding state/clarification id 并阻止明显 cross-identity overwrite，但业务 conflict helper 复制了 SaveManager判定且 same identity 仍进入隐式清除路径。[Source: `rpg_engine/platform_sidecar.py` — `player_act_from_message`, `platform_pending_conflict`]
- Story 6.4 已将跨后续 action 的历史 replay receipt retention 明确 Defer 到本 Story；不能静默忽略。[Source: `_bmad-output/implementation-artifacts/deferred-work.md`]

### Architecture Compliance

- 权威链保持：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- `data/game.sqlite` 是事实权威；pending/clarification/receipt/history、registry、binding 与 audit 只是 entry/evidence/mirror。
- Shared OS lock 只保护短暂 read/compare/publish transition；Runtime/AI 不得在锁内长时间执行。使用两阶段 generation CAS 避免 10 秒 lock timeout 与 15 秒 helper deadline互相放大。
- `contract_version_mismatch` 与 unknown safety 是 Story 6.1 typed boundary，不属于 candidate semantic mismatch clarification。
- Story 6.9 active-only binder、Story 6.3 live slot projection、Story 6.2 taxonomy与 Story 6.4 atomic confirmation/replay均必须保持。

### Project Structure Notes

- 核心 owner：`rpg_engine/save_manager.py`。
- Thin surfaces：`rpg_engine/mcp_adapter.py`、`rpg_engine/cli_v1.py`、`rpg_engine/platform_sidecar.py`、`rpg_engine/game_session.py`、`rpg_engine/surface_inventory.py`。
- Focused owner tests：新增 `tests/test_pending_lifecycle.py`；相邻测试集中在现有 pending confirmation、SaveManager、MCP、platform、CLI 与 surface inventory 文件。
- 不修改 `/Users/oliver/.hermes/hermes-agent/**`、`/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/**`、正式 Campaign/Save/registry 或任何用户 SQLite。
- 当前 worktree 含未提交 Correct Course、rebaseline、test/trace/report 工作；均为用户既有工作。Story 6.5 只精确暂存本 artifact、实现/测试/同步文档以及 `sprint-status.yaml` 的 6.5 状态 hunk。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Story 6.5]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md` — D3, D5, Story 6.5]
- [Source: `_bmad-output/implementation-artifacts/6-4-atomic-pending-confirmation-claim-and-replay-classification.md` — AC, Review Round 3 Defer]
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md` — pending supersede / historical receipt]
- [Source: `docs/project-context.md` — P0 authority, repository and temporary Save boundaries]
- [Source: `docs/architecture.md` — player-safe write and fact authority]
- [Source: `docs/save-and-campaign-packages.md` — pending files and bound-save lifecycle]
- [Source: `docs/mcp-contracts.md` — player profile and clarification guard]

## Dev Agent Record

### Agent Model Used

GPT-5.4

### Debug Log References

- Story validation：`_bmad-output/implementation-artifacts/6-5-explicit-pending-supersede-and-clarification-lifecycle.validation-report.md`（PASS）。
- Fresh code review：Round 1–51；Round 51 三路 CLEAN，累计应用 186 个经去重、复现与 AC/范围核验的 review patch。
- Verification：post-Round 51 clean diff 的 focused、adjacent、Campaign、docs/static 与 repository full suite 全部通过；未复用被后续 patch 失效的旧绿灯。

### Implementation Plan

- 先以 synthetic temporary workspace 新增 lifecycle owner tests，锁定 CAS、cancel、TTL、correction、restart、history 与 no-mutation。
- 在 `SaveManager` 内实现 bounded canonical session read、两阶段 generation CAS、统一 cancel/inspect 与 historical receipt；复用 Story 6.4 crash-release lock/SQLite anchors。
- 让 MCP、CLI、platform 只转发 owner 参数与结果，删除进程内 clarification owner；同步 surface inventory 与 canonical docs。
- 每个 patch 后运行受影响 focused tests，Dev 完成后运行 full regression 并将 Story 置为 review。

### Completion Notes List

- 完成 action/clarification 单一 persisted session、两阶段 generation CAS、显式 supersede/cancel/expiry/migration/orphan 与 bounded historical receipt lifecycle。
- SaveManager 保持唯一业务权威；CLI、MCP 与 platform 只 mirror、gate、forward，restart/stale binding/cross-identity 均按 canonical owner 结果收敛。
- Candidate correction 仅在 exact identity/save/token/original text 与确实变化的 strict candidate 下重入完整验证链，并最多产生新的未确认 pending；仅 `player_confirm()` 可提交事实。
- 完成 privacy、bounded strict JSON、registry/path/lock/crash rollback 与 fork/concurrency 防护；未修改 Hermes 源码、RPG Engine 自用 Skill、正式 Campaign/Save/registry 或用户 SQLite。
- Round 43 的 hostile same-UID recursive final-syscall/filesystem replacement 两项超出本 Story cooperative engine/POSIX 权威边界，已按 workflow 去重并记录为 Dismiss；无 Defer 或待决 Decision。
- Round 51 三路 fresh review 全部 clean；累计自动应用 186 个有效 review patch，最终 required gates 全部通过。

### File List

- `_bmad-output/implementation-artifacts/6-5-explicit-pending-supersede-and-clarification-lifecycle.md`
- `_bmad-output/implementation-artifacts/6-5-explicit-pending-supersede-and-clarification-lifecycle.validation-report.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`（仅 Story 6.5 状态 hunk）
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/mcp-contracts.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/cli_v1.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/surface_inventory.py`
- `tests/compatibility/hermes_stdio_provider.py`
- `tests/fixtures/hermes_stdio_compatibility.yaml`
- `tests/test_current_native_player_turn.py`
- `tests/test_current_native_visibility.py`
- `tests/test_cross_campaign_context_smoke.py`
- `tests/test_gather_intake_commit.py`
- `tests/test_hermes_stdio_compatibility.py`
- `tests/test_mcp_adapter.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_pending_confirmation_replay.py`
- `tests/test_pending_lifecycle.py`
- `tests/test_platform_ai_simulation.py`
- `tests/test_platform_sidecar.py`
- `tests/test_save_manager.py`
- `tests/test_v1_cli.py`

## Change Log

- 2026-07-20：完成 Create Story 与 fresh Validate Story，进入 Dev Story 实施。
- 2026-07-21：完成 Dev Story、51 轮三路 fresh code review与最终 required gates；Round 51 CLEAN，累计应用 186 个有效 review patch，Story 置为 done。
