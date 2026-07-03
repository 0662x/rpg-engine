# Testing

The full project test suite is run with:

```bash
python3 -m pytest
```

Use `python3`, not `python`, because the local environment does not provide a `python` command.

## Useful Targets

Run the current native campaign/save regression suite:

```bash
python3 -m pytest tests/test_current_native_*.py tests/test_cross_layer_regression.py
```

Run the write-safety and validation cluster:

```bash
python3 -m pytest \
  tests/test_cross_layer_regression.py \
  tests/test_validation_pipeline.py \
  tests/test_projection_service.py \
  tests/test_save_manager.py
```

Show the slowest tests:

```bash
python3 -m pytest --durations=20 -q
```

Run branch coverage, including CLI subprocess tests:

```bash
python3 -m coverage erase
python3 -m coverage run -m pytest -q
python3 -m coverage combine
python3 -m coverage report --sort=cover
```

## Test Layers

- Unit/white-box tests cover small contracts and branchy logic, such as intent classification, response acceptance decisions, content type registration, validation profiles, and schema helpers.
- Integration/gray-box tests inspect database side effects, write guards, projection state, context audit rows, package import/export, and rollback behavior.
- System/black-box tests exercise CLI or `GMRuntime` flows against a real package or packaged example, including current native save read-only queries, preview/commit flows on temp copies, export/import round trips, and projection repair.

## Current Native Packages

Current package tests use these defaults:

- Campaign package: `/Users/oliver/.hermes/rp/isekai-farm-campaign-native-v1`
- Save package: `/Users/oliver/.hermes/rp/isekai-farm-save-native-v1`

Override them with:

```bash
RPG_ENGINE_CURRENT_CAMPAIGN_ROOT=/path/to/campaign \
RPG_ENGINE_CURRENT_SAVE_ROOT=/path/to/save \
python3 -m pytest tests/test_current_native_*.py
```

Tests must not mutate the formal current save package. Mutating tests should copy the campaign/save into a temporary directory first, usually through helpers in `tests/helpers.py`.

The current native regression suite is split by topic:

- `tests/test_current_native_package.py`: package manifests, validation, migration health, and author/save boundaries.
- `tests/test_current_native_context.py`: read-only scene/entity queries, context routing, recall budgets, and audit rows.
- `tests/test_current_native_actions.py`: preview contracts, delta guards, and blocked action behavior.
- `tests/test_current_native_write_safety.py`: commit guards, rollback, export/import, and projection repair on temp copies.
- `tests/test_current_native_visibility.py`: hidden/GM-only content leakage checks.

## Helper Conventions

Shared test scaffolding lives in `tests/helpers.py`.

Prefer these helpers for new tests:

- `run_cli(...)`
- `load_stdout_json(...)`
- `query_scalar(...)` / `query_int(...)`
- `current_turn(...)` / `current_location(...)`
- `copy_initialized_minimal(...)`
- `copy_current_packages(...)`

Keep assertions in test files. Helpers should stay boring: paths, temp fixture setup, CLI subprocess calls, and simple SQLite reads.

## Coverage Note

Coverage is configured with branch measurement and subprocess tracking. Because subprocess runs write parallel data files, use `coverage combine` before `coverage report`.
