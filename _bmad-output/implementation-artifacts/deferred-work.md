# Deferred Work

## Deferred from: code review of 1-3-player-confirm-validation-commit-gate (2026-07-05)

- CLOSED 2026-07-06: CLI/platform confirm response filtering evidence remains thinner than SaveManager/MCP coverage. The code review re-run patch added explicit CLI JSON and platform confirm response non-leakage assertions.

## Deferred from: code review of 1-3-player-confirm-validation-commit-gate (2026-07-06)

- Idempotent `player_confirm` retry after commit succeeds but pending clear fails is not currently supported. This is a pre-existing crash/retry resilience gap: if SQLite commit succeeds but pending cleanup does not, retry may hit validation or duplicate-command guards before clearing the pending action.
- CLOSED 2026-07-06: CLI/platform confirm response filtering evidence remains internally deferred despite broad completed task wording. The code review re-run patch added explicit CLI JSON and platform confirm response non-leakage assertions.

## Deferred from: code review of 1-3-player-confirm-validation-commit-gate (2026-07-06 re-run)

- Idempotent `player_confirm` retry after commit succeeds but pending clear fails remains unsupported. This is still treated as a pre-existing crash/retry resilience gap rather than a blocker for the current confirm/backup cleanup patch set.

## Deferred from: code review of 1-6-mcp-player-profile-权限门 (2026-07-07)

- Windows-style forward-slash drive paths such as `C:/outside` are accepted as root-relative on POSIX. This is a pre-existing cross-platform path-normalization gap outside the Story 1.6 MCP player profile gate patch.

## Deferred from: code review of 1-7-cli-命令薄适配边界 (2026-07-07)

- `platform_event_from_args` can override `--event-json` identity/text with explicit CLI flags. This is a pre-existing platform event normalization ambiguity and should be handled with the platform forwarding/audit boundary work rather than the Story 1.7 help/inventory/test patch.

## Deferred from: code review of 3-3-派生玩家视图与检索产物的隐藏信息边界 (2026-07-09)

- `rpg_engine/audit.py` hidden clock audit still recognizes only exact `hidden`; this is a pre-existing audit/reporting gap outside Story 3.3 player-facing derived read-model scope.

## Deferred from: code review of 3-6-context-budget-and-quality-diagnostics (2026-07-10)

- `filter_plot_signals_for_selected_sections` 在初次 budget pass 后删除或缩小派生 plot section 时，不会重新选择先前 omitted 的较低优先级 source section；这是 Story 3.4 已存在的 dependency-aware budget selection/priority policy 缺口，修复会改变既有 selection 策略，故不作为 Story 3.6 diagnostics evidence patch 处理。

## Deferred from: second code review of 3-6-context-budget-and-quality-diagnostics (2026-07-10)

- Reaffirmed：plot post-filter 释放容量后不重新选择较低优先级 source section 仍是 Story 3.4 的 pre-existing dependency-aware budget policy 缺口；第二轮未发现新的 Story 3.6-specific 修复依据，继续 defer。

## Deferred from: code review of 4-1-low-trust-intent-candidate-contract (2026-07-11)

- CLOSED 2026-07-20（Story 6.5）：`SaveManager.player_turn()` 不再因新请求或 malformed external candidate 静默清理旧 pending；新 publication 使用 exact `expected_pending_id` 两阶段 CAS，query/blocked/error 保留旧 session。

## Deferred from: code review of 4-2-ai-latency-policy-and-safe-degradation (2026-07-11)

- CLOSED 2026-07-20（Story 6.5）：pending replacement / retry 已由 canonical owner、explicit supersede、TTL/cancel 与 generation CAS 统一实现；latency helper 仍不拥有 lifecycle authority。

## Deferred from: code review of 6-2-canonical-action-taxonomy-registry-projection (2026-07-13)

- CLOSED 2026-07-13：第二轮 Blind Hunter 对 baseline `keyword_expected_action()` 做逐词复现后确认，旧 guard 不包含 context-only“找/检查”；第一轮 Defer 的基线判断错误。Story 6.2 已增加 canonical `preview.mismatch` role，恢复 low-level guard 既有边界并保持 fail-closed。

## Deferred from: code review of 6-4-atomic-pending-confirmation-claim-and-replay-classification (2026-07-14)

- 可选 archivist 请求在通用 CommitService 的 SQLite commit 后崩溃窗口没有 durable phase/outbox。普通 `SaveManager.player_confirm()` 默认不启用 archivist；修复需要扩大持久化设计，作为独立规划项处理，不在 Story 6.4 内引入 migration 或新 authority。
- CLOSED 2026-07-20（Story 6.5）：latest receipt 现会迁入最多 8 条的 canonical bounded history；延迟 retry 按 confirmation session/save/identity/payload digest 查找，并重新核验 SQLite anchor、turn 与 event evidence。

## Deferred from: code review of 1-9-库存消耗语义提交门 (2026-07-15)

- 大型 routine consumption delta 的每个非目标 upsert 当前会执行一次 item-existence SQL 查询；批量化需要独立 cardinality/performance 规划，不扩大本次 P0 语义正确性范围。
- 权威 SQLite 中既有的损坏 `details_json` / `properties_json` 会在 consumption metadata 读取时抛出原生 JSON decode error；数据库损坏诊断与稳定 corruption error contract 属于既有健康检查/恢复范围。
- hostile `list` subclass 用作 `events` / `upsert_entities` 时，完整 pipeline 会在 routine resolver 之前的通用 `proposal -> delta_schema` 迭代中抛异常。局部 exact-list routine guard 不能修复真实路径；需要独立规划全 action 共用的 non-canonical Python container fail-closed 边界。

## Deferred from: code review of 6-9-retired-entity-binding-fail-closed (2026-07-17)

- Pending proposal 创建后、玩家确认前，若已绑定实体转为 retired/archived/unknown，现有 confirmation/commit 路径不重新执行 lifecycle binding。这是本 Story 修复之前已存在的 pending→commit freshness 策略缺口；批准的 Story 6.9 明确以 binder/public ingress 在 committable pending 前 fail-closed 为边界，且禁止将修复扩大到 SaveManager/confirmation owner，因此需要独立规划。

## Deferred from: third code review of 6-9-retired-entity-binding-fail-closed (2026-07-18)

- Binder 连接完成 active-only 绑定后，resolver/preview 重开 SQLite connection 前若有并发 lifecycle 变更，尚无跨阶段 snapshot/revalidation。该 TOCTOU 是既有 binder→preview→pending→confirm freshness 设计缺口；需要与已记录的 pending→confirm 重验统一规划，而不在本 Story 引入跨 owner 持久化或测试钩子。

## Deferred from: eleventh code review of 6-9-retired-entity-binding-fail-closed (2026-07-18)

- PARTIALLY CLOSED 2026-07-20（Story 6.5）：既有 pending 的保留、显式 compare-and-supersede、身份/session/save conflict 已完成；`last_played_at` 沿用既有合法 bookkeeping 语义，未在 Story 6.5 扩张或重新定义。

## Deferred from: code review of 6-8-rpg-engine-compatibility-fixture-for-hermes-stdio-e2e (2026-07-19)

- PID-bearing ready sentinel配合`os.kill(pid, 0)`可证明当前AI-off provider直接子进程已退出，但不能彻底排除极短窗口PID reuse，也不证明未来可能出现的派生进程组。Hermes CI独占client/reconnect lifecycle；在MCP SDK提供稳定public process identity前，本Story不回引private process handle或扩张为Hermes lifecycle gate。
