---
baseline_commit: bd410099b0378365cebfb113504de991b5b6a612
---

# Story 1.2: Player Turn Pending Contract

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

## Story

As a player host,
I want `SaveManager.player_turn()` to create only query, clarification, blocked, or pending-action outcomes,
so that ordinary player input never commits gameplay facts before confirmation.

## Acceptance Criteria

1. Given an active Save Package and a player action that can change state, when `SaveManager.player_turn()` is called, then it returns a player-visible preview with `ready_to_confirm=true` and a `session_id`, and no new gameplay facts, turns, events, clock ticks, or entity changes are committed.
2. Given the player input is a query, clarification case, or blocked action, when `SaveManager.player_turn()` completes, then it returns `ready_to_confirm=false`, and it does not create a committable pending action.
3. Given a pending action is created, when the pending state is inspected, then it binds save id, save path, player text, action, delta, `TurnProposal`, confirmation session id, created time, expiry, and optional platform/session/actor identity, and the pending state is not treated as an accepted fact.

## Tasks / Subtasks

- [x] Lock down the `player_turn()` outcome contract without inventing a new player flow. (AC: 1, 2)
  - [x] Keep `SaveManager.player_turn()` as the ordinary natural-language entry and `SaveManager.player_confirm()` as the only ordinary player commit gate.
  - [x] Preserve the allowed `player_turn()` result families: query, clarification, blocked, and pending action.
  - [x] For ready actions, return `ready_to_confirm=true`, a non-empty `session_id`, `saved=false`, and player-facing preview text only.
  - [x] For query, clarification, `needs_confirmation`, blocked, empty text, unsupported capability, or maintenance requests, return `ready_to_confirm=false`, `session_id=None`, and `saved=false`.
  - [x] Continue hiding `delta_draft` and full `turn_proposal` from public `player_turn()` / CLI / MCP / platform result payloads.
  - [x] Do not call `GMRuntime.commit_turn()` or any direct SQLite fact-write path from `player_turn()`.
- [x] Make pending action payload shape explicit and testable. (AC: 3)
  - [x] Ensure a pending action written by `player_turn()` includes `schema_version`, `session_id`, `save_id`, `save_path`, `created_at`, `expires_at`, `ttl_seconds`, `user_text`, `action`, `delta`, `turn_proposal`, and optional `platform`, `session_key_hash`, and `actor_id_hash`.
  - [x] Treat `session_id` as the confirmation session id returned to the player; do not add a parallel confirmation id unless the implementation needs backward-compatible aliasing.
  - [x] Assert the stored `turn_proposal` is still unaccepted before confirmation: `human_confirmed` must be false or absent-false, and provenance must not claim `confirmed_via=player_confirm`.
  - [x] Keep pending action and pending clarification files under `.aigm/` workspace runtime state; they are not Save Package facts.
  - [x] If adding a helper, keep it in `rpg_engine/save_manager.py` or a narrowly owned SaveManager helper module; do not create a second pending-action registry.
- [x] Add no-mutation evidence around ready player actions. (AC: 1)
  - [x] In `tests/test_save_manager.py`, create a focused test that snapshots authoritative SQLite state before and after a ready `player_turn()` on a temporary initialized save.
  - [x] Assert after `player_turn()` and before `player_confirm()` that `current_turn_id`, turn rows, event rows, entity rows, relevant clock values, and projection/outbox state have not advanced because of the preview.
  - [x] Assert the only expected writes are workspace/runtime metadata such as `.aigm/pending-player-action.json` and registry `last_played_at`; these must not be described as gameplay facts.
  - [x] Then call `player_confirm(session_id)` and assert the commit advances through the existing validated commit path.
- [x] Add negative outcome coverage for non-committable results. (AC: 2)
  - [x] Extend existing cases so query, clarification or `needs_confirmation`, blocked, maintenance, and empty-text outcomes leave no `.aigm/pending-player-action.json`.
  - [x] If a clarification state is persisted, assert it is `.aigm/pending-player-clarification.json` only and cannot be confirmed via `player_confirm()`.
  - [x] Assert a new non-ready `player_turn()` clears any stale committable pending action from a previous ready preview.
- [x] Preserve platform/session/actor pending boundaries. (AC: 3)
  - [x] Reuse `platform_session_metadata()` and `validate_pending_platform_session()`; do not hand-roll a second hashing or identity comparison path.
  - [x] Keep `PlatformSidecar.player_act_from_message()` forwarding platform, session key, actor id, message id, text hash, and passive preflight identity into `SaveManager.player_turn()`.
  - [x] If platform code changes, add or update `tests/test_platform_sidecar.py` to prove wrong actor/session cannot create or confirm another pending action.
- [x] Synchronize public docs only when behavior or wording changes. (AC: 1, 2, 3)
  - [x] Update `docs/save-and-campaign-packages.md`, `docs/ai-intent-chain.md`, `docs/cli-contracts.md`, `docs/mcp-contracts.md`, and `docs/testing-and-quality-gates.md` only if the implementation changes public contract wording.
  - [x] Do not update archived stubs as source of truth.

### Review Findings

- [x] [Review][Patch] Ready-preview no-mutation snapshot only covers six tables and can miss gameplay fact/entity writes [tests/test_save_manager.py:23]
- [x] [Review][Patch] Non-ready `player_turn()` outcomes do not assert authoritative SQLite state remains unchanged [tests/test_save_manager.py:286]
- [x] [Review][Patch] Unsupported-capability and real pending-clarification branches are not explicitly covered [tests/test_save_manager.py:266]
- [x] [Review][Patch] Pending payload expiry and raw platform identity leakage assertions are too weak [tests/test_save_manager.py:247]
- [x] [Review][Patch] Platform/session/actor confirm gate is not exercised using an actual `player_turn()` pending payload [tests/test_save_manager.py:252]
- [x] [Review][Patch] Platform preflight hit trace leaks raw `session_key` into pending `TurnProposal` audit payload [rpg_engine/preflight_cache.py:108]

## Dev Notes

### Source Context

- Epic 1 protects the trusted local play loop and entry authority boundary. Story 1.2 owns the `player_turn -> pending action` half of the ordinary player chain. [Source: `_bmad-output/planning-artifacts/epics.md`]
- PRD FR-1 requires ordinary gameplay writes to pass through player turn, pending action, player confirmation, validation, and commit. FR-14 requires Save Package fact integrity. [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`]
- The execution-chain architecture says `player_turn`, query, `start_or_continue`, platform message handling, and preflight may not commit gameplay facts. [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`]
- The invariant remains: `AI proposes. Kernel verifies. Player confirms. Engine commits.` [Source: `docs/project-context.md`; `docs/architecture.md`]

### Current Implementation State

- `rpg_engine/save_manager.py` already implements `SaveManager.player_turn()`, `player_act()` as a wrapper, `player_confirm()`, pending action/clarification read/write/clear helpers, TTL helpers, and platform/session/actor identity helpers.
- `player_turn()` currently resolves the active save, reads pending clarification, clears stale pending action, calls `GMRuntime.act(..., view="player")`, writes pending action only when `ready_to_save` plus `delta_draft` plus `turn_proposal` are present, writes pending clarification when applicable, and returns public fields without `delta_draft` or `turn_proposal`.
- `player_turn()` currently calls `mark_played()`, which updates workspace registry metadata. That is acceptable runtime entry metadata, but tests for this story must distinguish it from gameplay facts in `data/game.sqlite`.
- `player_confirm()` currently reads pending action, rejects missing/expired/wrong-save/wrong-session/wrong-platform/wrong-actor cases, sets proposal provenance with `confirmed_via=player_confirm`, sets `human_confirmed=True`, then calls `GMRuntime.commit_turn()`.
- `rpg_engine/runtime.py` keeps `GMRuntime.act()` as a preview wrapper over `preview_from_text()`. `GMRuntime.commit_turn()` runs the validation pipeline and requires an approved `TurnProposal`; a raw delta without a proposal is rejected.
- Round 7 already hardened pending action TTL and platform actor identity. Preserve that work; this story should add explicit contract and no-mutation evidence, not undo it. [Source: `_bmad-output/round-7-player-session-concurrency.md`]

### Relevant Files

- `rpg_engine/save_manager.py`: primary implementation surface for pending action shape, result contract, and player confirmation boundary.
- `tests/test_save_manager.py`: primary focused test target for ready action no-mutation, result shape, pending payload shape, and non-ready outcomes.
- `tests/test_package_save_condition_coverage.py`: existing helper/branch coverage for SaveManager conditions, TTL, platform identity, and message rendering. Extend only if a pure helper branch changes.
- `rpg_engine/runtime.py`: read for commit guard behavior; avoid changing unless a real `TurnProposal` or validation bug is found.
- `rpg_engine/platform_sidecar.py` and `tests/test_platform_sidecar.py`: only change if platform/session/actor pending propagation or conflict checks need adjustment.
- `rpg_engine/mcp_adapter.py`, `rpg_engine/cli_v1.py`, `tests/test_mcp_adapter.py`, and `tests/test_v1_cli.py`: verify public result exposure if CLI/MCP player payload shape changes.

### Architecture Compliance

- Do not introduce auto-confirm, auto-save, or low-risk direct commit in `player_turn()`. The existing `auto_confirm_low_risk` argument in `GMRuntime.act()` is deliberately ignored; keep that boundary.
- Do not treat ready preview text as fact. Any message must keep the "confirm before save" language and avoid implying the action happened.
- Do not expose raw delta, proposal internals, hidden facts, or AI private reasoning to player-safe results.
- Do not move pending action into Save Package SQLite as a gameplay fact for this story. Pending action is workspace runtime state until `player_confirm()` submits it through validation/commit.
- Do not weaken trusted low-level surfaces. `GMRuntime.preview_*`, `validate_delta()`, and `commit_turn()` may continue to exist behind developer/trusted/maintenance gates.

### Testing Requirements

Run the smallest meaningful gate for the implemented diff:

```bash
python3 -m pytest -q tests/test_save_manager.py
git diff --check
```

If pending helper branches in `tests/test_package_save_condition_coverage.py` change, also run:

```bash
python3 -m pytest -q tests/test_package_save_condition_coverage.py
```

If public CLI/MCP result shape or arguments change, also run:

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_mcp_adapter.py
```

If platform forwarding or actor/session gate code changes, also run:

```bash
python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py
```

For docs changes, run:

```bash
git add -N docs _bmad-output
python3 scripts/check_markdown_links.py docs _bmad-output
```

### Residual Risk Gate

- This story touches the `Player Session / Concurrency` residual risk area. The minimum evidence is a no-mutation test for ready `player_turn()` plus pending payload identity/expiry assertions. [Source: `_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`]
- Multi-actor party/session modeling is explicitly out of scope. Preserve the current single-actor platform binding until a separate party/session contract exists.

### Previous Story Intelligence

- Story 1.1 exists as `ready-for-dev` but has not been implemented in this worktree. Do not assume the Story 1.1 surface inventory changes are already available.
- If Story 1.1 is implemented before this story, classify `SaveManager.player_turn()` as `player-safe` with write authority limited to pending action/clarification runtime state, and forbidden bypasses including direct commit, raw delta/proposal exposure, hidden access, and profile escalation.

### Recent Git Intelligence

Recent commits are boundary and documentation heavy:

- `83c84c3 docs: complete GDS document project rescan`
- `130c968 docs: require strict BMAD skill activation`
- `c34706b feat: harden player pending session confirmation`
- `bfd8315 docs: align BMAD docs with current code audit`
- `c5964c2 docs: close BMAD documentation migration`

The relevant implementation signal is commit `c34706b`: pending session confirmation was recently hardened with TTL, actor identity, and platform gate tests. Build on it rather than replacing it.

### Latest Technical Information

No external web research is required for this story. Use existing Python stdlib, SQLite, dataclass/dict payload patterns, and current pytest fixtures. Do not add runtime dependencies.

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- `python3 -m pytest -q tests/test_save_manager.py -k "ready_preview_does_not_mutate or pending_action_payload_binds or non_ready_outcomes_clear"` -> `3 passed, 12 deselected, 5 subtests passed`
- `python3 -m pytest -q tests/test_save_manager.py` -> `15 passed, 22 subtests passed`
- `python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py` -> `10 passed`
- `python3 -m pytest -q tests/test_package_save_condition_coverage.py` -> `9 passed, 11 subtests passed`
- `git diff --check` -> passed
- `python3 -m pytest -q` -> `464 passed, 609 subtests passed`
- BMAD code review patches: expanded authoritative SQLite snapshots to all application tables, added no-mutation assertions for non-ready outcomes, covered unsupported-capability and persisted clarification branches, strengthened pending expiry/raw identity assertions, and exercised platform/session/actor confirm gates from a real `player_turn()` pending payload.
- Review patch verification: `python3 -m pytest -q tests/test_save_manager.py` -> `17 passed, 22 subtests passed`; `python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py` -> `19 passed, 11 subtests passed`; `python3 scripts/check_markdown_links.py docs _bmad-output` -> `checked 133 markdown files; local links ok`; `git diff --check` -> passed; `python3 -m pytest -q` -> `466 passed, 609 subtests passed`.
- Follow-up review patch verification: `python3 -m pytest -q tests/test_platform_sidecar.py::PlatformSidecarTests::test_message_prewarm_then_player_act_uses_same_message_identity` -> `1 passed`; `python3 -m pytest -q tests/test_preflight_cache.py` -> `18 passed`; `python3 -m py_compile rpg_engine/preflight_cache.py tests/test_platform_sidecar.py` -> passed; `python3 -m pytest -q tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_save_manager.py tests/test_runtime.py` -> `87 passed, 74 subtests passed`.
- Final verification: `python3 scripts/check_markdown_links.py docs _bmad-output` -> `checked 133 markdown files; local links ok`; `git diff --check` -> passed; `python3 -m pytest -q` -> `466 passed, 609 subtests passed`.
- Test hardening verification: `python3 -m pytest -q tests/test_save_manager.py` -> `17 passed, 22 subtests passed`; `git diff --check` -> passed; `python3 -m pytest -q` -> `466 passed, 609 subtests passed`.

### Completion Notes List

- Added focused guardrail tests that prove `player_turn()` ready previews do not mutate authoritative SQLite gameplay state before `player_confirm()`.
- Added pending-action payload assertions for confirmation `session_id`, save binding, TTL/expiry consistency, action/delta/proposal payload, platform/session/actor hashes, raw identity non-leakage, and unaccepted `TurnProposal` provenance.
- Added negative outcome coverage showing query, needs-confirmation/clarification, blocked maintenance, empty text, blocked out-of-world requests, unsupported capabilities, and persisted clarification results clear stale committable pending actions, do not mutate SQLite facts, and cannot be confirmed.
- Sanitized preflight trace serialization so pending `TurnProposal` audit payloads store `session_key_hash` instead of raw `session_key`, while preserving raw cache matching internally.
- Public docs did not need updates; the player-visible contract is unchanged.

### File List

- `tests/test_save_manager.py`
- `rpg_engine/preflight_cache.py`
- `tests/test_platform_sidecar.py`
- `_bmad-output/implementation-artifacts/1-2-player-turn-pending-contract.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Change Log

- 2026-07-05: Added `SaveManager.player_turn()` contract tests for no-mutation preview behavior, pending action payload shape, stale pending clearing, and non-committable outcomes; moved story to review.
- 2026-07-05: Resolved BMAD code review findings by strengthening SQLite no-mutation snapshots, non-ready branch coverage, pending payload expiry/identity assertions, and platform/session/actor confirmation tests; moved story to done.
- 2026-07-05: Resolved follow-up BMAD review finding by sanitizing platform preflight trace identity in pending proposals and adding a real sidecar prewarm-hit regression test.
