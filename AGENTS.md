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

### Strict BMAD Skill Activation

When the user mentions `bmad`, `BMAD`, a BMAD menu code, a BMAD skill name, or
asks what the next BMAD step should be, treat it as a real BMAD invocation, not
as a generic planning prompt.

Required sequence:

1. Route through the installed BMAD catalog. If the user did not name a concrete
   skill, start with `bmad-help`: read `.agents/skills/bmad-help/SKILL.md`
   completely, then use `_bmad/_config/bmad-help.csv`,
   `_bmad/_config/skill-manifest.csv`, relevant `_bmad/**/config.yaml` files,
   existing artifacts, and `docs/project-context.md` to decide the next skill.
2. Prefer Game Dev Studio (`gds-*`) skills for RPG Engine game/engine work,
   BMM (`bmad-*`) skills for general software/product work, Core skills for
   repo-wide BMAD utilities, and TEA skills for test architecture.
3. Before doing task work, read the selected
   `.agents/skills/<skill>/SKILL.md` completely. Do not claim BMAD was used
   from memory or from a hand-written approximation.
4. If the selected skill has activation/customization instructions, run
   `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/<skill> --key workflow`
   or follow the skill's stated fallback merge rules. Execute
   `activation_steps_prepend`, load `persistent_facts`, load the module config,
   greet in the configured `communication_language`, and execute
   `activation_steps_append` before the workflow body.
5. If the skill points to `instructions.md`, a checklist, CSV requirements, or a
   step file, read the required file fully before acting on it.
6. For step-file workflows such as `bmad-quick-dev`, `gds-quick-dev`,
   `bmad-dev-story`, or `gds-dev-story`, load only the current step file,
   complete steps in order, never skip or optimize the sequence, and halt at any
   checkpoint that requires human input.
7. When recommending next BMAD work, report the menu code, display name, skill
   name, action context/args when present, whether the step is optional or
   required, and recommend a fresh context window unless the user asks to run it
   immediately.
8. When producing BMAD-governed artifacts or final summaries, include BMAD
   provenance: the user trigger, catalog row or menu code, skill path read,
   customization resolver result or fallback, config loaded, instruction/step
   files followed, and verification gates run.
9. If a named skill is missing, unreadable, or exposes no customization surface
   for the requested behavior, say so plainly and stop or choose the closest
   valid BMAD path with that limitation stated. Do not invent unsupported BMAD
   behavior.
10. Repo-level agent rules belong in this `AGENTS.md`. Formal BMAD per-skill
    behavior customization belongs under `_bmad/custom/<skill>.toml` or
    `_bmad/custom/<skill>.user.toml` when the target skill's `customize.toml`
    exposes the requested field.

Existing BMAD-style documents without recorded skill provenance are useful
working artifacts, but future BMAD claims require the evidence above.

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
