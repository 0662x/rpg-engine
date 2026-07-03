# Module Map

This map is for orientation before editing code. It is descriptive, not a
replacement for the specs.

## Public Surfaces

| Module | Role |
|---|---|
| `rpg_engine/cli.py` | Public CLI command routing. Keep business logic thin. |
| `rpg_engine/mcp_adapter.py` | MCP tool surface and profile-gated AI client access. |
| `rpg_engine/runtime.py` | GMRuntime stable facade for query, preview, validate, commit, and health. |
| `rpg_engine/__main__.py` | `python3 -m rpg_engine` entry point. |

## Runtime and Write Path

| Module | Role |
|---|---|
| `rpg_engine/game_session.py` | Session-level orchestration helpers. |
| `rpg_engine/preview.py` | Turn proposal construction and preview contracts. |
| `rpg_engine/commit_service.py` | Commit boundary for accepted proposals/deltas. |
| `rpg_engine/unit_of_work.py` | Transaction lifecycle and coordinated side effects. |
| `rpg_engine/write_guard.py` | Write safety checks and mutation boundaries. |
| `rpg_engine/validation_pipeline.py` | Validation orchestration. |
| `rpg_engine/delta_schema.py` | Delta contract/schema handling. |

## Actions and Intent

| Module | Role |
|---|---|
| `rpg_engine/actions/` | Domain action contracts and built-in action resolvers. |
| `rpg_engine/intent_router.py` | Legacy/current intent routing boundary. |
| `rpg_engine/intent_manifest.py` | Player-visible intent/action capability manifest. |
| `rpg_engine/ai_intent/` | External/internal AI intent candidate, review, binding, and arbitration. |
| `rpg_engine/ai/` | AI provider/config/task support and state audits. |
| `rpg_engine/preflight_cache.py` | Advisory internal-intent review cache state machine. |

Primary authority for this area: `docs/specs/standard-intent-chain.md` and
`docs/specs/ai-intent-prewarm.md`. New natural-language player entry behavior
should flow through the standard intent chain instead of adding routing policy
to CLI, MCP, platform, or save-manager surfaces. Refactor sequencing for this
area is recorded in `docs/architecture/intent-coordinator-refactor-plan.md`;
the six-role architecture review and amendments are recorded in
`docs/architecture/intent-coordinator-team-review.md`. Historical AI intent
design-goal alignment is recorded in
`docs/architecture/intent-design-alignment-review.md`.

## Context and Visibility

| Module | Role |
|---|---|
| `rpg_engine/context/` | Context pipeline, collectors, budgets, rendering, semantic routing. |
| `rpg_engine/context_builder.py` | Compatibility/context construction entry point. |
| `rpg_engine/visibility.py` | Hidden/GM/player visibility rules. |
| `rpg_engine/context_audit.py` | Context audit storage and inspection. |
| `rpg_engine/render.py` | Text rendering helpers. |

## Packages, Saves, and Projection

| Module | Role |
|---|---|
| `rpg_engine/campaign.py` | Campaign package loading and core campaign objects. |
| `rpg_engine/campaign_validation.py` | Campaign validation. |
| `rpg_engine/save.py` | Save package loading and save objects. |
| `rpg_engine/save_service.py` | Save lifecycle operations. |
| `rpg_engine/save_manager.py` | Player-facing save management. |
| `rpg_engine/save_validation.py` | Save validation. |
| `rpg_engine/packages/` | Current package service/archive/lock/merge implementation. |
| `rpg_engine/package_*` | Compatibility wrappers or older package surfaces. |
| `rpg_engine/projection_service.py` | Projection orchestration and repair/status behavior. |
| `rpg_engine/projections.py` | Projection helpers. |

## Content and Authoring

| Module | Role |
|---|---|
| `rpg_engine/content_types/` | Content type registry and built-in content contracts. |
| `rpg_engine/content_delta.py` | Content delta contract. |
| `rpg_engine/content_validation.py` | Content validation. |
| `rpg_engine/content_factory.py` | Content construction helpers. |
| `rpg_engine/authoring/` | Author-facing campaign doctor, outline, split, explain, templates. |
| `rpg_engine/palette.py` | Candidate content palette before facts are committed. |
| `rpg_engine/proposal_queue.py` | Proposal queue and review boundary. |

## Infrastructure

| Module | Role |
|---|---|
| `rpg_engine/db.py` | SQLite connection/schema helpers. |
| `rpg_engine/migrations.py` | Migration application and checks. |
| `rpg_engine/atomic_io.py` | Atomic filesystem writes. |
| `rpg_engine/backup.py` | Backup helpers. |
| `rpg_engine/package_lock.py` | Package lock compatibility surface. |
| `rpg_engine/resource_paths.py` | Packaged resource lookup. |

## Platform Entry and Prewarm

| Module | Role |
|---|---|
| `rpg_engine/platform_sidecar.py` | Thin platform message facade, game-session gate, and act/confirm forwarding. |
| `rpg_engine/platform_prewarm.py` | Lightweight platform advisory prewarm queue, worker, binding store, and metrics. |

Platform modules should pass passive identifiers and player text into kernel
services. They should not own final intent policy, hidden context visibility,
preview approval, validation, or save commits.

## Compatibility and Legacy

| Module | Role |
|---|---|
| `rpg_engine/legacy/` | Explicit compatibility only. Avoid new behavior here. |
| `rpg_engine/importers/` | Import pipelines, including campaign-specific adapters. |
| `rpg_engine/compat/` | Compatibility namespace. |
| `rpg_engine/cli_v1.py` | Older CLI surface; prefer current CLI unless maintaining legacy. |

## Edit Heuristics

- If a change writes game state, look for the service/transaction owner first.
- If a change changes player-visible context, inspect visibility and context
  audit paths.
- If a change changes MCP/CLI behavior, make sure runtime/kernel behavior is not
  duplicated in the surface layer.
- If a module name has both a package form and top-level wrapper, prefer the
  package form for new implementation and leave wrappers thin.
