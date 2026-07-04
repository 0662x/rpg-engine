# Brownfield Context

## Input Basis

- Primary source: `../../implementation-artifacts/investigations/architecture-execution-chain-investigation.md`.
- Supporting scan: `../../architecture.md`.
- Canonical adopted companions: project context, architecture, AI intent chain, CLI contracts, MCP contracts.

## Current Evidence

- The ordinary player path is supported by source, canonical docs, and focused tests.
- The confirmed player-safe chain is `player_turn -> pending action -> player_confirm -> runtime commit`.
- Low-level `play` and MCP developer/trusted tools are intentional architecture surfaces.
- Legacy/admin CLI write commands are maintenance surfaces, not ordinary player flows.
- Commit validates before writing SQLite, then projection/outbox refresh and report artifact status after commit.
- Preflight cache has identity, hash, status, TTL, and single-use protections.
- AI intent/preflight ownership is distributed across Runtime, intent router, AIIntentRouter, preflight cache, context builder, MCP, and platform prewarm.

## Architecture Debt

- `IntentCoordinator` or equivalent package boundary is not implemented.
- Surface taxonomy exists implicitly in docs/source but is not yet an architecture spine artifact.
- Projection/outbox consistency semantics are present in code but need clearer architecture language.
- Historical reports and old BMAD-style artifacts remain contextual only; canonical docs and current code win on conflict.

## Downstream Caution

Do not infer an active ordinary-player bypass from the existence of low-level or maintenance write paths. The risk is exposure, documentation, and misuse, not existence.
