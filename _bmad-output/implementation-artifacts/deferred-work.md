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

- `SaveManager.player_turn()` 在解析新的玩家请求前会清理已有 pending action；malformed external candidate 也会取消旧 pending。这是既有“新 turn 取代旧 pending”的生命周期策略，不由 Story 4.1 引入；改变它需要独立确认 pending replacement / retry 语义。

## Deferred from: code review of 4-2-ai-latency-policy-and-safe-degradation (2026-07-11)

- Reaffirmed：`SaveManager.player_turn()` 在解析新请求前清理已有 pending action 的行为是 Story 4.1 已记录的 pre-existing lifecycle policy；本 Story 的 timeout policy 不改变 pending replacement / retry 语义。

## Deferred from: code review of 6-2-canonical-action-taxonomy-registry-projection (2026-07-13)

- CLOSED 2026-07-13：第二轮 Blind Hunter 对 baseline `keyword_expected_action()` 做逐词复现后确认，旧 guard 不包含 context-only“找/检查”；第一轮 Defer 的基线判断错误。Story 6.2 已增加 canonical `preview.mismatch` role，恢复 low-level guard 既有边界并保持 fail-closed。
