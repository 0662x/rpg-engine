# Verification Gates

## Boundary Tests

- Player profile cannot register or call low-level preview, validate, commit, or preflight tools.
- `player_turn` creates pending action or clarification but does not commit gameplay facts.
- `player_confirm` requires the pending `session_id` and matching platform/session/actor identity where applicable.
- Runtime commit requires approved proposal validation, matching delta digest, and write guard expectations.
- Preflight cache is advisory, identity-bound, TTL-bound, and single-use.
- `message_only` preflight does not store external candidate at creation and must be revalidated on formal entry.
- Projection/outbox failures surface through projection report/state and remain repairable.
- Hidden/GM-only content does not leak into player view, FTS, scene output, or ordinary query.

## Suggested Focused Suites

- `tests/test_mcp_adapter.py`
- `tests/test_save_manager.py`
- `tests/test_runtime.py`
- `tests/test_preflight_cache.py`
- `tests/test_platform_sidecar.py`
- `tests/test_platform_prewarm.py`
- `tests/test_projection_service.py`
- `tests/test_v1_cli.py`

## Acceptance Rule

Any implementation derived from this SPEC must name which boundary it touches and run the smallest meaningful subset of the gates above. Cross-module changes must also update canonical docs.
