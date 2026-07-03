# Development Workflow

This is the practical workflow for changing RPG Engine without blurring engine
facts, AI suggestions, and maintenance operations.

## 1. Classify the Change

Choose one primary category before editing:

- Runtime play path: turn, query, preview, validation, commit, projection.
- Authoring path: campaign package creation, validation, outline, doctor.
- Save/package maintenance: import, export, migration, repair, archive.
- AI intent path: external candidate, internal review, arbiter, binding.
- Surface path: CLI, MCP, prompt, docs.
- Test/report only.

If a change touches more than two categories, write a short plan first.

## 2. Read the Owning Docs and Tests

Use this map:

| Change area | Read first | Test cluster |
|---|---|---|
| Turn flow | `docs/ai-intent-chain.md`, `docs/save-and-campaign-packages.md` | `tests/test_current_native_player_turn.py`, `tests/test_cross_layer_regression.py` |
| AI intent | `docs/ai-intent-chain.md`, `docs/prompt-contracts.md` | `tests/test_ai_intent.py`, `tests/test_platform_prewarm.py` |
| Projection/write safety | `docs/architecture.md`, `docs/data-models.md` | `tests/test_projection_service.py`, `tests/test_current_native_write_safety.py` |
| Campaign package | `docs/save-and-campaign-packages.md`, `docs/authoring-guide.md` | `tests/test_campaign_validation.py`, `tests/test_official_example.py` |
| Save package | `docs/save-and-campaign-packages.md`, `docs/data-models.md` | `tests/test_save_manager.py`, `tests/test_save_patch.py` |
| MCP | `docs/mcp-contracts.md`, `docs/prompt-contracts.md` | `tests/test_mcp_adapter.py`, `tests/test_mcp_transcript.py` |
| CLI | `docs/cli-contracts.md` | `tests/test_v1_cli.py`, `tests/test_package_cli.py` |

## 3. Keep the Diff Shaped

- One behavioral goal per change.
- Avoid mixing refactors with behavior changes unless the refactor is required
  to make the behavior safe.
- Leave legacy files alone unless the task is a compatibility or migration
  change.
- Put new long-lived docs under `docs/`; put dated probes under `reports/`.

## 4. Verify

Use `python3`.

Fast checks:

```bash
python3 -m py_compile rpg_engine/path.py
python3 -m pytest tests/test_target.py -q
```

Regression clusters:

```bash
python3 -m pytest tests/test_current_native_*.py tests/test_cross_layer_regression.py
python3 -m pytest tests/test_validation_pipeline.py tests/test_projection_service.py tests/test_save_manager.py
python3 -m pytest
```

Campaign smoke:

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
```

## 5. Finish With Evidence

Record:

- files changed
- boundary changed
- tests run
- known risks or skipped tests

If the change affects player-visible output, include a short before/after or CLI
example.
