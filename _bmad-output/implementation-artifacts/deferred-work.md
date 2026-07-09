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
