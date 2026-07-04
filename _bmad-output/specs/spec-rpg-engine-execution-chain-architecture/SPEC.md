---
id: SPEC-rpg-engine-execution-chain-architecture
companions:
  - brownfield.md
  - surface-taxonomy.md
  - verification-gates.md
  - ../../../docs/project-context.md
  - ../../../docs/architecture.md
  - ../../../docs/ai-intent-chain.md
  - ../../../docs/cli-contracts.md
  - ../../../docs/mcp-contracts.md
sources:
  - ../../implementation-artifacts/investigations/architecture-execution-chain-investigation.md
  - ../../architecture.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only.

# RPG Engine Execution-Chain Architecture

## Why

RPG Engine needs a brownfield architecture spine because the current code now has tests and docs around the ordinary player path, but high-risk responsibility is still spread across AI intent/preflight, low-level/maintenance entry surfaces, and post-commit projection/outbox behavior. Downstream architecture and stories need a small, testable WHAT contract before any refactor or implementation work changes these boundaries.

## Capabilities

- **CAP-1**
  - **intent:** Architecture consumers can preserve the ordinary player-safe `player_turn -> pending action -> player_confirm -> validated commit` chain as the only normal gameplay fact-write path.
  - **success:** A downstream architecture or story can point to one canonical player-safe flow and prove `player_turn` cannot commit facts while `player_confirm` remains the commit gate.

- **CAP-2**
  - **intent:** Architecture consumers can classify every public or semi-public entry surface into player-safe, trusted low-level, maintenance/admin, platform sidecar, or platform prewarm categories.
  - **success:** A surface taxonomy exists that makes it impossible to mistake maintenance/admin or low-level runtime commands for ordinary player play.

- **CAP-3**
  - **intent:** Architecture consumers can define an `IntentCoordinator` or equivalent boundary for candidate preparation, preflight identity, AI consensus, and proposal provenance.
  - **success:** The coordinator boundary is documented as orchestration and trace only, with no preview, validation, confirmation, commit, or gameplay fact authority.

- **CAP-4**
  - **intent:** Architecture consumers can treat projection/outbox outputs as post-commit repairable read-model and evidence surfaces.
  - **success:** SQLite remains the fact authority, and projection/outbox failure behavior is specified as visible, reportable, and repairable without becoming a rollback or fact-source policy by accident.

- **CAP-5**
  - **intent:** Downstream stories can derive verification gates for player profile access, pending confirmation, preflight identity/single-use behavior, and projection/outbox repairability.
  - **success:** Each downstream implementation story names tests that protect the relevant boundary before changing Runtime, SaveManager, MCP, CLI, platform, preflight, validation, commit, or projection code.

## Constraints

- The invariant is: AI proposes; Kernel verifies; Player confirms; Engine commits.
- External AI remains low-trust input, not fact, final intent, hidden access, approval, or save authorization.
- Internal AI review can help classify and review but cannot preview, validate, confirm, or commit.
- `SaveManager.player_turn()` may create pending action or clarification but cannot commit gameplay facts.
- `SaveManager.player_confirm()` remains the ordinary player-path commit gate.
- Platform prewarm may only create advisory `message_only` preflight and cannot drive a turn.
- MCP/CLI/platform adapters must stay thin and call kernel services instead of duplicating business logic.
- Hidden/GM-only content must not leak into player views, FTS, scene output, or ordinary query.
- Projection/outbox artifacts are not authoritative facts and cannot bypass validation.
- Changes in this area must follow BMAD plan/story/review evidence before implementation.

## Non-goals

- Do not implement code, migrations, or refactors in this spec.
- Do not turn preflight into a proposal cache, permission cache, or gameplay fact source.
- Do not remove trusted low-level or maintenance/admin surfaces merely because they bypass `SaveManager.player_confirm` by design.
- Do not replace canonical project docs with this SPEC; this SPEC narrows the next architecture task.

## Success signal

A downstream architecture document can use this SPEC to produce a concise execution-chain spine that covers player-safe flow, surface taxonomy, `IntentCoordinator` boundaries, and projection/outbox consistency without weakening any existing player confirmation, AI trust, or write-validation guard.

## Assumptions

- `bmad-architecture` is the next best downstream workflow because `gds-game-architecture` requires a GDD and RPG Engine is a software kernel rather than a traditional game-client project.

## Open Questions

- Should legacy/admin CLI taxonomy be exhaustive before architecture, or should architecture define the taxonomy first and leave exhaustive command inventory to a follow-up story?
