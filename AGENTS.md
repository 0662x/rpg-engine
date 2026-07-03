# RPG Engine Development Guide

This file is the first stop for AI coding agents and human contributors working
on RPG Engine / AIGM Kernel.

## What This Project Is

RPG Engine is a local-first AIGM Kernel. It owns factual state, rules,
validation, random resolution, save packages, projections, and queryable context.
It does not write prose as the game master. External AI clients may narrate, but
the kernel decides what becomes durable fact.

Current documentation starts at `docs/README.md`.

## BMAD Workflow

BMAD is installed for this repository as the strong AI-assisted development
process layer.

- BMAD modules live under `_bmad/`.
- Codex and Hermes skills live under `.agents/skills/`.
- Long-lived BMAD / AI-agent project context is `docs/project-context.md`.
- The required workflow rules are in `docs/governance/bmad-workflow.md`.

For high-risk changes, do not jump straight to implementation. Classify the
change first and follow the BMAD workflow:

- AI intent, preflight, Runtime, SaveManager, MCP, CLI, platform, schema,
  migration, hidden-content, or cross-module refactors require planning and
  review evidence.
- Small bug fixes may be implemented directly, but still need focused
  verification and a clear risk summary.

## Non-Negotiable Boundaries

- `data/game.sqlite` is the authoritative current fact store.
- Events and JSONL are audit/projection surfaces, not a license to bypass write
  validation.
- AI output is always untrusted until routed through preview, validation, and
  commit.
- AI intent recognition authority is documented in `docs/ai-intent-chain.md`.
  External AI may propose candidates, but final routing, binding, preview,
  validation, and commit authority stay inside the engine.
- Hidden/GM-only content must not leak into player views, FTS, scene output, or
  normal query paths.
- Ordinary play uses Campaign Package + Save Package + GMRuntime + CLI/MCP.
  Low-level migration, repair, import, projection, and package surgery are
  admin/maintenance paths.
- Formal current save packages must not be mutated by tests. Copy them to temp
  dirs before write tests.
- Do not add a second business-logic path in CLI or MCP. They should call kernel
  services, not reimplement engine behavior.

## Read Before Editing

For broad changes, read these in order:

1. `docs/README.md`
2. `docs/project-context.md`
3. `docs/governance/bmad-workflow.md`
4. `docs/development-guide.md`
5. `docs/architecture.md`
6. `docs/component-inventory.md`
7. The canonical doc for the touched surface, such as `docs/ai-intent-chain.md`,
   `docs/save-and-campaign-packages.md`, `docs/cli-contracts.md`,
   `docs/mcp-contracts.md`, `docs/data-models.md`, or `docs/authoring-guide.md`.
8. `docs/testing-and-quality-gates.md`

For narrow bug fixes, at minimum read the touched module, its closest tests, and
the relevant section of `docs/component-inventory.md` or
`docs/source-tree-analysis.md`.

## Module Ownership Rules

- `rpg_engine/actions/`: action contracts and domain action resolution.
- `rpg_engine/ai/` and `rpg_engine/ai_intent/`: AI candidate handling,
  arbitration, schema validation, and trust boundaries.
- `rpg_engine/preflight_cache.py`, `rpg_engine/platform_prewarm.py`, and
  `rpg_engine/platform_sidecar.py`: advisory preflight and platform entry only.
  Do not put final intent policy or write authority here.
- `rpg_engine/context/`: context collection, budgeting, rendering, semantic
  routing, and validation.
- `rpg_engine/content_types/`: content registry and content type contracts.
- `rpg_engine/packages/`: package archive, lock, merge, and service utilities.
- Top-level legacy modules remain valid only where current docs say so. Prefer
  current service modules for new work.
- `rpg_engine/legacy/` is not a place for new behavior unless the task is
  explicitly legacy compatibility.

## Development Workflow

- Keep changes scoped to one behavior, boundary, or phase.
- Update docs when changing user-visible CLI, MCP contracts, package schemas,
  save semantics, validation rules, projection behavior, or AI trust boundaries.
- Add or update tests at the same layer as the risk: unit for pure helpers,
  integration for SQLite/write/projection behavior, CLI/system tests for user
  flows.
- Prefer explicit profiles and capability gates over implicit defaults.
- Keep helpers boring. Assertions belong in tests unless shared behavior needs a
  named contract.
- Use structured parsers and schema validation for package data; avoid ad-hoc
  string parsing for YAML/JSON/SQLite records.

## Verification

Use `python3`, not `python`.

Common commands:

```bash
python3 -m pytest
python3 -m pytest tests/test_current_native_*.py tests/test_cross_layer_regression.py
python3 -m pytest tests/test_validation_pipeline.py tests/test_projection_service.py tests/test_save_manager.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
```

For Python syntax-only checks:

```bash
python3 -m py_compile path/to/file.py
```

## Report and Scratch File Policy

- Durable docs go under canonical docs in `docs/`, `docs/governance`, or active
  artifact directories such as `docs/prompts`.
- Time-boxed research and probe reports go under `reports/YYYY-MM-DD/` with an
  `INDEX.md`.
- Historical or superseded design material goes under `docs/archive/YYYY-MM-DD/`.
- Temporary saves, caches, and probe outputs must not become source of truth.

## Before You Finish

- Re-run the smallest meaningful verification.
- Check that docs and tests match the changed behavior.
- Confirm no formal current save package was mutated.
- Summarize the changed boundary, not just the changed files.
