---
baseline_commit: bd410099b0378365cebfb113504de991b5b6a612
---

# Story 1.1: Surface Authority Inventory and Contract

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

## Story

As an engine author,
I want every public and semi-public entry surface to declare its authority category,
so that player-safe, trusted low-level, maintenance, platform, prewarm, and projection paths cannot be confused.

## Acceptance Criteria

1. Given the current CLI, MCP, platform, runtime, projection, and maintenance entry points, when the surface inventory is generated or checked, then every surface is classified as exactly one of `player-safe`, `trusted low-level`, `maintenance/admin`, `platform sidecar`, `platform prewarm`, or `projection/outbox`, and every surface records its write authority and forbidden bypasses.
2. Given a new surface is added without taxonomy metadata, when the focused surface contract test runs, then the test fails with a clear missing-category or missing-authority error, and the developer can identify the surface to update.
3. Given a surface spans multiple categories, when the inventory is validated, then it must either be split or document the explicit gate that changes authority, and the player-safe category must not expose low-level write powers.

## Tasks / Subtasks

- [x] Audit and extend the existing surface inventory contract. (AC: 1, 2)
  - [x] Reuse `rpg_engine/surface_inventory.py`; do not create a parallel registry.
  - [x] Ensure each `SurfaceEntry` exposes the canonical taxonomy category, write authority, intended profile/caller, default exposure, normal-play status, and forbidden bypasses.
  - [x] If keeping the current domain-style `category` values such as `save_package` or `turn_low_level`, add a separate explicit taxonomy field; do not rely on domain category as the authority taxonomy.
  - [x] Add an inventory validation helper that returns actionable errors for missing/invalid taxonomy category, missing write authority, missing forbidden bypasses, duplicate names within a surface, and player-safe entries exposing low-level write powers.
- [x] Expand inventory coverage across all public and semi-public surfaces. (AC: 1, 3)
  - [x] MCP: cover all `MCP_TOOL_NAMES` from `rpg_engine/mcp_adapter.py`, preserving player profile vs low-level profile gates.
  - [x] CLI V1: cover `campaign`, `save`, `player`, `play`, `platform`, `mcp`, and `eval` command surfaces declared in `rpg_engine/cli_v1.py`.
  - [x] Legacy/admin CLI: keep the current sentinel maintenance/package/projection entries and add only enough coverage to prevent undocumented bypasses for migration, projection repair, package upgrade/install/reconcile, save patch/import/export, content/proposal apply, plugin validation, and legacy save-turn paths.
  - [x] Runtime API: classify `GMRuntime.preflight_intent`, `start_turn`, `query`, `preview_from_text`, `preview_action`, `act`, `validate_delta`, and `commit_turn`.
  - [x] Platform: classify `PlatformSidecar.handle_message_event`, `start_or_continue_from_message`, `player_act_from_message`, `player_confirm_from_message`, metrics/expire/deactivate surfaces, and `PlatformPrewarmService.handle_message`.
  - [x] Projection/outbox: classify `ProjectionService.refresh`, `refresh_projections`, `process_outbox`, `render_projection_status`, and CLI projection repair/status surfaces.
- [x] Make cross-category gates explicit. (AC: 3)
  - [x] Split entries that cannot be honestly represented by one taxonomy category.
  - [x] Where a command intentionally changes authority by profile, mode, or session gate, record the gate in metadata and test it.
  - [x] Preserve the rule that ordinary player-safe flow can create pending action and confirm existing pending action only through `SaveManager.player_turn()` / `SaveManager.player_confirm()`.
- [x] Update focused tests. (AC: 1, 2, 3)
  - [x] Extend `tests/test_surface_inventory.py` so the full inventory validates without errors.
  - [x] Add a negative test with a deliberately incomplete entry and assert the failure names the missing category or write authority and the affected surface name.
  - [x] Add coverage tests comparing inventory entries to source constants or parser-derived command names where stable: `MCP_TOOL_NAMES`, V1 command groups/subcommands, selected runtime methods, platform entry methods, and projection entry helpers.
  - [x] Keep the existing tests proving default MCP profile excludes low-level tools and maintenance/admin tokens.
- [x] Synchronize canonical docs. (AC: 1)
  - [x] Update `docs/architecture.md`, `docs/cli-contracts.md`, `docs/mcp-contracts.md`, and `docs/testing-and-quality-gates.md` only where the implemented inventory contract changes public wording.
  - [x] Do not resurrect `docs/architecture/phase-0-surface-inventory.md` as a current authority; it is an archived stub.

### Review Findings

- [x] [Review][Patch] Required legacy/admin bypass sentinels are missing for package install/reconcile, proposal/content apply, and legacy save-turn paths [rpg_engine/surface_inventory.py:587]
- [x] [Review][Patch] `aigm projection repair` is registered twice as the same public CLI surface under different surface labels [rpg_engine/surface_inventory.py:760]
- [x] [Review][Patch] V1 command coverage checks only top-level command groups, so existing/new subcommands can lack taxonomy metadata [tests/test_surface_inventory.py:187]
- [x] [Review][Patch] Runtime/platform/projection coverage uses hard-coded expected sets instead of source-backed entrypoint discovery [tests/test_surface_inventory.py:197]
- [x] [Review][Patch] `validate_surface_inventory()` does not require `authority_gate` for dispatch or multi-authority entries [rpg_engine/surface_inventory.py:1145]
- [x] [Review][Patch] `validate_surface_inventory()` accepts placeholder bypasses and misses low-level authority hidden in write modes or raw TurnProposal wording [rpg_engine/surface_inventory.py:1163]
- [x] [Review][Patch] Rerun: authority-gated non-dispatch write modes can still omit `authority_gate` [rpg_engine/surface_inventory.py:1705]
- [x] [Review][Patch] Rerun: non-surface public API allowlists live only in tests, so source coverage can be bypassed without production rationale [tests/test_surface_inventory.py:36]
- [x] [Review][Patch] Rerun: `forbidden_bypasses` passed as a raw string can satisfy validation character-by-character [rpg_engine/surface_inventory.py:1700]
- [x] [Review][Patch] Rerun: default-exposed MCP entries are not explicitly required to be `player-safe` [rpg_engine/surface_inventory.py:1688]
- [x] [Review][Patch] Rerun: test requires domain category and taxonomy category to differ, which is stricter than the contract [tests/test_surface_inventory.py:96]

## Dev Notes

### Source Context

- Epic 1 establishes the player-safe local play loop and surface authority boundary. Story 1.1 is the first foundation story and should create the reusable contract that later Story 1.2 through Story 1.8 can cite. [Source: `_bmad-output/planning-artifacts/epics.md`]
- The required taxonomy categories are exactly: `player-safe`, `trusted low-level`, `maintenance/admin`, `platform sidecar`, `platform prewarm`, and `projection/outbox`. [Source: `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/surface-taxonomy.md`]
- The architectural invariant is `AI proposes. Kernel verifies. Player confirms. Engine commits.` Inventory work must not weaken pending confirmation, AI trust, hidden visibility, profile gates, preflight identity, or projection repair behavior. [Source: `docs/architecture.md`; `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/SPEC.md`]
- PRD FR-2 requires public and semi-public entry surfaces to be classified by authority; FR-16 requires named contracts with input/output/error/permission/write-authority semantics. [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`]

### Current Implementation State

- `rpg_engine/surface_inventory.py` already defines `SurfaceEntry`, `MCP_SURFACE_INVENTORY`, `AI_PROMPT_SURFACE_INVENTORY`, `PACKAGE_SURFACE_INVENTORY`, and `render_surface_inventory_markdown()`. This is the correct extension point.
- Existing `SurfaceEntry.category` values are mostly domain labels such as `save_package`, `turn_workflow`, `turn_low_level`, `projection`, and `plugin`. They do not yet directly encode the canonical taxonomy required by this story.
- Existing entries record `profile`, `write_mode`, `default_exposed`, `normal_play`, notes, and related tools. They do not consistently record forbidden bypasses.
- `tests/test_surface_inventory.py` already checks MCP inventory parity with `MCP_TOOL_NAMES`, default MCP exposure, write modes, prompt surfaces, selected package/maintenance sentinels, generated markdown, and canonical docs mentions.
- `docs/architecture/phase-0-surface-inventory.md` is an archived stub; current authority lives in canonical docs and code inventory.

### Relevant Files

- `rpg_engine/surface_inventory.py`: extend the inventory schema, validation helper, coverage lists, and markdown rendering.
- `tests/test_surface_inventory.py`: extend positive and negative contract tests.
- `rpg_engine/mcp_adapter.py`: source of `PLAYER_MCP_TOOL_NAMES`, `LOW_LEVEL_MCP_TOOL_NAMES`, `MCP_TOOL_NAMES`, and profile gates. Read but avoid changing unless the inventory uncovers an actual behavior bug.
- `rpg_engine/cli_v1.py`: source of V1 public command groups and subcommands, including player, play, platform, mcp, campaign, save, and eval surfaces.
- `rpg_engine/cli.py`: source of legacy/admin maintenance surfaces; avoid exhaustive churn unless a missing high-risk write surface is found.
- `rpg_engine/runtime.py`: source of `GMRuntime` low-level and player-adjacent runtime methods.
- `rpg_engine/platform_sidecar.py` and `rpg_engine/platform_prewarm.py`: source of platform sidecar and prewarm authority gates.
- `rpg_engine/projection_service.py` and `rpg_engine/projections.py`: source of projection/outbox refresh, repair, and status behavior.
- Canonical docs to synchronize if behavior or wording changes: `docs/architecture.md`, `docs/cli-contracts.md`, `docs/mcp-contracts.md`, `docs/testing-and-quality-gates.md`.

### Architecture Compliance

- Do not add a second business-logic path in CLI or MCP. Inventory and tests may inspect or describe surfaces, but adapters must continue calling kernel services. [Source: `AGENTS.md`; `docs/project-context.md`]
- Do not remove trusted low-level or maintenance/admin surfaces just because they bypass ordinary player confirm by design. The story is about classification, gates, and failure evidence. [Source: `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/SPEC.md`]
- Platform sidecar entries must remain gate-and-forward surfaces. They must not gain direct gameplay fact write authority. [Source: `docs/cli-contracts.md`; `rpg_engine/platform_sidecar.py`]
- Platform prewarm must remain advisory and `message_only`-capable; it cannot drive turns or cache permissions/proposals. [Source: `docs/ai-intent-chain.md`; `rpg_engine/platform_prewarm.py`]
- Projection/outbox entries are post-commit read models and repair evidence, not fact authority or rollback policy. [Source: `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/verification-gates.md`; `rpg_engine/projection_service.py`]

### Testing Requirements

Run the smallest meaningful gate for the implemented diff:

```bash
python3 -m pytest -q tests/test_surface_inventory.py
git diff --check
```

If the implementation changes MCP/profile behavior, also run:

```bash
python3 -m pytest -q tests/test_mcp_adapter.py
```

If it changes CLI parser shape or command docs, also run:

```bash
python3 -m pytest -q tests/test_v1_cli.py
```

If it changes platform or projection metadata derived from behavior, also run the relevant subset:

```bash
python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_projection_service.py
```

For docs changes, run:

```bash
git add -N docs _bmad-output
python3 scripts/check_markdown_links.py docs _bmad-output
```

### Latest Technical Information

No external web research is required for this story. The implementation should use existing Python stdlib/dataclass patterns, current repo tests, and the installed dependency set documented in the architecture spine. Do not add runtime dependencies.

### Previous Story Intelligence

This is the first story in Epic 1, so there is no previous story file to reuse.

### Recent Git Intelligence

Recent commits show the current work is documentation/BMAD-boundary heavy:

- `83c84c3 docs: complete GDS document project rescan`
- `130c968 docs: require strict BMAD skill activation`
- `c34706b feat: harden player pending session confirmation`
- `bfd8315 docs: align BMAD docs with current code audit`
- `c5964c2 docs: close BMAD documentation migration`

Relevant implementation signal: preserve strict BMAD provenance and pending confirmation boundaries while adding inventory metadata and tests.

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- 2026-07-05T04:44:24+1000: Captured `baseline_commit` and moved sprint status for Story 1.1 to `in-progress`.
- RED: Added failing `tests/test_surface_inventory.py` coverage for canonical taxonomy metadata, actionable validation errors, duplicate detection, player-safe low-level bypass detection, CLI V1 command groups, runtime APIs, platform sidecar/prewarm methods, and projection/outbox helpers.
- GREEN: Extended `rpg_engine.surface_inventory` with explicit canonical taxonomy metadata, write authority, intended caller, authority gates, forbidden bypasses, validation helper, runtime/platform/projection/CLI inventories, and expanded markdown rendering.
- REFACTOR/DOCS: Synchronized canonical architecture, CLI, MCP, and testing docs with the implemented inventory contract.
- Verification: `python3 -m pytest -q tests/test_surface_inventory.py`; `git diff --check`; `python3 scripts/check_markdown_links.py docs _bmad-output`; `python3 -m pytest -q`.
- REVIEW PATCHES: Resolved BMAD code review findings by adding parser-derived V1 subcommand coverage, missing legacy/admin sentinels, duplicate public CLI detection, stronger authority-gate/bypass validation, and source-backed runtime/platform/projection coverage.
- Review verification: `python3 -m pytest -q tests/test_surface_inventory.py`; `python3 -m pytest -q tests/test_v1_cli.py tests/test_mcp_adapter.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_projection_service.py`; `git diff --check`; `python3 scripts/check_markdown_links.py docs _bmad-output`; `python3 -m pytest -q`.
- RERUN REVIEW PATCHES: Resolved rerun findings by adding production non-surface API rationale, rejecting raw-string bypass metadata, requiring gates for gated write modes, enforcing default-exposed MCP taxonomy, and removing the accidental category/taxonomy inequality test.
- Rerun verification: `python3 -m pytest -q tests/test_surface_inventory.py`; `python3 -m pytest -q tests/test_v1_cli.py tests/test_mcp_adapter.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_projection_service.py`; `git diff --check`; `python3 scripts/check_markdown_links.py docs _bmad-output`; `python3 -m pytest -q`.

### Completion Notes List

- Implemented a single reusable surface authority contract in `rpg_engine/surface_inventory.py`; no parallel registry was added.
- Preserved domain-style `category` values while adding a separate `taxonomy_category` field with the exact canonical taxonomy required by the story.
- Added `validate_surface_inventory()` to catch missing taxonomy, invalid taxonomy, missing write authority, missing intended caller, missing forbidden bypasses, duplicate names within a surface, and player-safe entries that expose low-level authority.
- Expanded inventory coverage across MCP, V1 CLI command groups, package/maintenance sentinels, runtime API methods, platform sidecar/prewarm entrypoints, and projection/outbox helpers.
- Documented explicit authority gates where surface authority changes by profile, subcommand, session, actor identity, preflight identity, or pending confirmation.
- Updated focused tests and canonical docs; no gameplay business logic path was changed.

### File List

- `rpg_engine/surface_inventory.py`
- `tests/test_surface_inventory.py`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/testing-and-quality-gates.md`
- `_bmad-output/implementation-artifacts/1-1-surface-authority-inventory-and-contract.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

### Change Log

- 2026-07-05: Implemented Story 1.1 surface authority inventory and contract; added canonical taxonomy metadata, validation gates, expanded coverage tests, docs sync, and full regression evidence.
