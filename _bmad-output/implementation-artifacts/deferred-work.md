# Deferred Work

## Deferred from: code review of 1-3-player-confirm-validation-commit-gate (2026-07-05)

- CLOSED 2026-07-06: CLI/platform confirm response filtering evidence remains thinner than SaveManager/MCP coverage. The code review re-run patch added explicit CLI JSON and platform confirm response non-leakage assertions.

## Deferred from: code review of 1-3-player-confirm-validation-commit-gate (2026-07-06)

- Idempotent `player_confirm` retry after commit succeeds but pending clear fails is not currently supported. This is a pre-existing crash/retry resilience gap: if SQLite commit succeeds but pending cleanup does not, retry may hit validation or duplicate-command guards before clearing the pending action.
- CLOSED 2026-07-06: CLI/platform confirm response filtering evidence remains internally deferred despite broad completed task wording. The code review re-run patch added explicit CLI JSON and platform confirm response non-leakage assertions.

## Deferred from: code review of 1-3-player-confirm-validation-commit-gate (2026-07-06 re-run)

- Idempotent `player_confirm` retry after commit succeeds but pending clear fails remains unsupported. This is still treated as a pre-existing crash/retry resilience gap rather than a blocker for the current confirm/backup cleanup patch set.
