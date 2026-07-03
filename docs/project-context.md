# Project Context

This is the BMAD/AI-agent project context for RPG Engine / AIGM Kernel. It
captures the rules future agents should load before planning or editing code.

## Product Thesis

The engine is a local-first kernel for long-running text RPG campaigns. It
stores durable facts, enforces rules, validates state transitions, builds
queryable context, and exposes safe CLI/MCP surfaces. The AI client narrates and
proposes; the kernel verifies and commits.

## Trust Model

- External AI suggestions are low-trust candidates.
- Internal AI review may help classify or bind intent, but cannot bypass kernel
  validation.
- Durable facts require preview, validation, and commit.
- Hidden content must stay hidden unless an explicit GM/maintenance profile is
  selected.
- Admin and maintenance paths must be visibly separated from ordinary player
  paths.

## Architecture Priorities

1. Preserve factual integrity.
2. Preserve save-package portability and inspectability.
3. Keep CLI/MCP thin over kernel services.
4. Make validation and write safety explicit.
5. Keep campaign authoring friendly without weakening runtime boundaries.
6. Prefer clear contracts over clever inference.

## Current Development Focus

The current implementation has landed major Phase 0-7.1 hardening around
intent, preview contracts, validation, commit, projection, targeted repair, and
current native package regressions. New work should usually move toward:

- complete turn coordination
- stronger target/tool protocols
- semantic AI parity
- import/migration/reporting hardening
- reducing legacy/admin ambiguity

## Required Documents

Start from `docs/README.md`. For implementation planning, also read:

- `docs/architecture/module-map.md`
- `docs/architecture/game-engine.md`
- `docs/architecture/turn-flow-architecture.md`
- `docs/specs/standard-intent-chain.md`
- `docs/specs/mcp-adapter.md`
- `TESTING.md`

## Coding Rules

- Keep state changes inside services that own the relevant transaction or
  validation boundary.
- Do not let CLI commands write state without going through the same guards as
  runtime/MCP flows.
- Do not add hidden-content exceptions without tests proving player views stay
  clean.
- Do not mutate formal current saves in tests; copy them first.
- Use schema validation for package and delta contracts.
- Treat reports as evidence, not as current authority unless linked from
  `docs/README.md`.

## Test Expectations

For any behavior change, pick at least one:

- focused unit test for pure logic
- integration test against temp SQLite/package state
- CLI/system test for public workflows
- current native regression when the formal package behavior is involved

For high-risk write paths, include rollback or no-mutation assertions.

