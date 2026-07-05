# Story 1.3: Player Confirm Validation Commit Gate

Status: ready-for-dev

## Story

As a player host,
I want `SaveManager.player_confirm()` to be the ordinary player commit gate,
So that only explicitly confirmed and validated proposals become durable facts.

## Acceptance Criteria

1. Given a valid pending player action from `player_turn`, when `SaveManager.player_confirm(session_id)` is called with the matching active save, confirmation session, and optional platform/session/actor identity, then the stored `TurnProposal` passed to commit is marked `human_confirmed=true`, records `confirmed_via=player_confirm`, the confirmation `session_id`, and a confirmation timestamp, and `GMRuntime.commit_turn()` is called through the `player_turn_commit` validation profile.
2. Given the pending action has a missing or mismatched confirmation session id, belongs to a different active save, has a mismatched platform/session/actor identity, has incomplete `delta` or `turn_proposal` payload, or has expired, when `player_confirm()` is called, then the commit is rejected, no gameplay facts are written, and only expired pending state is cleaned up with a message requiring a fresh `player_turn`.
3. Given `GMRuntime.commit_turn()` or the validation/commit services reject the delta or `TurnProposal` because approval, profile compatibility, validation evidence, write-guard expectations, delta digest, proposal id, or duplicate command id checks fail, when the caller attempts to commit, then no partial gameplay fact write is committed and the still-valid pending action is not cleared by `player_confirm()`.
4. Given a player-safe public surface uses confirmation, when CLI, MCP, or platform confirm flows execute, then they remain thin adapters around `SaveManager.player_confirm()` and do not duplicate preview, validation, low-level commit, platform identity, or proposal approval logic.
5. Given a player-safe response is returned from `player_confirm()`, when the response is inspected through SaveManager, MCP, CLI, or platform paths, then it reports structured status/message/warnings/errors without exposing raw `delta`, full `TurnProposal`, raw platform session key, raw actor id, hidden facts, or AI private reasoning.
6. Given the implementation touches `SaveManager`, Runtime, validation, commit, MCP, CLI, or platform boundaries, when focused gates run, then they prove the player-safe chain still follows `player_turn -> pending action -> player_confirm -> validation -> commit` and low-level `commit_turn` remains trusted-only for ordinary player profiles.

## Tasks / Subtasks

- [ ] Harden and document `SaveManager.player_confirm()` as the ordinary commit gate. (AC: 1, 2, 3)
  - [ ] Keep the order of operations explicit: load active save, load pending action, reject expired state, verify save id, verify platform/session/actor identity, verify confirmation `session_id`, verify payload shape, mark proposal confirmation provenance, then call `GMRuntime.commit_turn()`.
  - [ ] Ensure `player_confirm()` clears pending action only after a successful validated commit; validation or commit exceptions must leave a still-valid pending action available for retry or inspection.
  - [ ] Preserve existing expired-pending cleanup behavior and require a fresh `player_turn` after expiry.
  - [ ] Do not add auto-confirm, auto-save, or any direct SQLite write path outside `GMRuntime.commit_turn()`.
- [ ] Add focused no-mutation and pending-state tests for confirm failures. (AC: 2, 3)
  - [ ] Cover wrong/missing `session_id`, wrong save, wrong platform, wrong session key, wrong/missing actor, incomplete payload, and expired pending action; assert SQLite gameplay state is unchanged.
  - [ ] Cover a real `player_turn()` pending payload where `GMRuntime.commit_turn()` rejects due to unconfirmed proposal, mismatched delta/proposal, invalid validation, missing `expected_turn_id` or `command_id`, duplicate command id, or equivalent current guard; assert no gameplay facts are written.
  - [ ] Assert non-expired rejected confirmations do not clear pending action, while expired confirmations do clear it.
- [ ] Strengthen successful confirmation evidence. (AC: 1, 5)
  - [ ] Assert the proposal handed to `GMRuntime.commit_turn()` has `human_confirmed=true`, `confirmed_via=player_confirm`, the expected confirmation `session_id`, and `confirmed_at`.
  - [ ] Assert public SaveManager/MCP/platform confirm responses keep `saved`, `ok`, `message`, `write_status`, `projection_status`, `warnings`, and `errors` semantics without exposing raw delta/proposal internals or raw platform identity.
- [ ] Keep public surfaces as thin adapters. (AC: 4, 6)
  - [ ] If CLI player confirm changes, verify it only calls `SaveManager.player_confirm(session_id=...)`.
  - [ ] If MCP player confirm changes, verify the default player profile cannot call low-level `commit_turn`, `validate_delta`, or `preview_action` as a bypass.
  - [ ] If platform confirm changes, verify `PlatformSidecar.player_confirm_from_message()` forwards `save_path`, `platform`, `session_key`, and `actor_id` into SaveManager and does not commit directly.
- [ ] Update docs only if public CLI/MCP/platform wording or result shape changes. (AC: 4, 5)
  - [ ] Keep canonical docs unchanged when behavior is only test hardening or internal guard cleanup.
  - [ ] If wording changes, update the relevant CLI/MCP/platform docs and markdown links.

## Dev Notes

### Source Context

- Epic 1 protects the trusted local play loop and entry authority boundary. Story 1.3 owns the `player_confirm -> validation -> commit` half of the ordinary player chain after Story 1.2 established the pending-action half. [Source: `_bmad-output/planning-artifacts/epics.md`]
- Story 1.3 acceptance criteria require `SaveManager.player_confirm()` to mark `TurnProposal.human_confirmed=true`, call `GMRuntime.commit_turn()` through the player commit validation profile, reject session/save/platform/actor/expiry mismatches, and reject low-level commit attempts missing approval, profile compatibility, validation evidence, or write-guard expectations. [Source: `_bmad-output/planning-artifacts/epics.md`]
- PRD FR-1 requires ordinary gameplay writes to pass through player turn, pending action, player confirmation, validation, and commit. FR-14 requires Save Package fact integrity and separated current facts, events, pending actions, projections, and metadata. [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`]
- The execution-chain architecture requires ordinary player-safe writes to flow through `SaveManager.player_turn()` to pending action, then `SaveManager.player_confirm(session_id)` with matching save/session/platform identity, then `GMRuntime.commit_turn()` with validation and an approved `TurnProposal`. [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`]
- The foundation architecture inherits that invariant and frames pending state, preflight cache, proposal queue, projections, cards, snapshots, memory, and audit artifacts as runtime/advisory/derived state rather than gameplay fact authority. [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`]
- Project context states the core boundary as: "AI proposes. Kernel verifies. Player confirms. Engine commits." `SaveManager.player_turn()` may create pending action, but `SaveManager.player_confirm()` is the ordinary player commit gate. [Source: `docs/project-context.md`]

### Current Implementation State

- `rpg_engine/save_manager.py` currently implements `SaveManager.player_confirm()` at lines 557-610. It reads the active save, reads pending action, rejects missing/expired/wrong-save/wrong-session/wrong-platform/wrong-actor/incomplete pending data, adds confirmation provenance, sets `human_confirmed=True`, calls `GMRuntime.commit_turn(delta, turn_proposal=proposal)`, then clears pending action and refreshes registry metadata.
- `validate_pending_platform_session()` currently hashes and compares platform session and actor identity at `rpg_engine/save_manager.py` lines 1007-1025. Reuse it; do not add a second hashing or comparison path.
- `player_confirm_message()` currently renders committed vs not-completed save text and projection refresh text at `rpg_engine/save_manager.py` lines 1177-1188. Preserve player-visible clarity if result handling changes.
- `GMRuntime.commit_turn()` currently normalizes `TurnProposal`, rejects delta/proposal mismatch, runs `run_validation_pipeline(..., profile="player_turn_commit")`, raises on validation failure, requires a proposal, and then calls `commit_turn_proposal()`. [Source: `rpg_engine/runtime.py` lines 1399-1465]
- `commit_turn_delta()` rejects non-ok validation, disallowed validation profiles, missing proposal validation for `player_turn_commit`, missing `expected_turn_id` / `command_id`, and validation delta digest mismatches. [Source: `rpg_engine/commit_service.py` lines 74-102]
- `commit_turn_proposal()` rejects proposal-id mismatch, missing proposal delta, and duplicate committed command id before delegating to `commit_turn_delta()`. [Source: `rpg_engine/commit_service.py` lines 172-220]
- `validate_turn_proposal()` marks AI-generated, response-draft, and human-edited delta sources as needing human confirmation until `human_confirmed=True`; this is the proposal-level reason Story 1.3 must prove confirmation is explicit. [Source: `rpg_engine/proposal.py` lines 241-322]
- `AIGMMCPAdapter.player_confirm()` currently forwards to `self.save_manager().player_confirm(session_id=session_id)` and the MCP server tool exposes only that wrapper for player confirmation. [Source: `rpg_engine/mcp_adapter.py` lines 438-443 and 1204-1207]
- `PlatformSidecar.player_confirm_from_message()` currently gates the platform event and forwards `session_id`, active save path, platform, session key, and actor id to SaveManager. [Source: `rpg_engine/platform_sidecar.py` lines 312-333]
- CLI v1 `player confirm` currently calls `manager.player_confirm(session_id=args.session_id)`; platform confirm routes through the sidecar. [Source: `rpg_engine/cli_v1.py`]

### Previous Story Intelligence

- Story 1.2 completed the pending-action half of the player-safe chain and is committed at baseline `97aa92d39e4a6a6e375ef124b5fd3075c7e9f409`.
- Story 1.2 added evidence that `player_turn()` ready previews do not mutate authoritative SQLite gameplay state before confirmation, pending action binds save id/path/text/action/delta/proposal/session/TTL/platform/session/actor hashes, and non-ready outcomes clear stale committable pending action without writing facts.
- Story 1.2 review patches also sanitized platform preflight trace identity in pending proposals so raw `session_key` / `actor_id` are not persisted or exposed. Preserve this behavior in confirm-path responses and tests.
- Existing focused branch tests already cover many SaveManager confirm errors in `tests/test_package_save_condition_coverage.py` lines 807-884, but they use mocked/simple pending payloads and should be complemented with real `player_turn()` pending payload and SQLite no-mutation assertions.
- Existing runtime tests prove raw `runtime.commit_turn(delta)` without a `TurnProposal` is rejected, and proposal validation requires human confirmation for AI-generated deltas. [Source: `tests/test_runtime.py` lines 168-190 and 2308-2325]
- Existing MCP and platform tests prove player workflows hide `delta_draft` / `turn_proposal`, confirm pending actions, default player profile rejects low-level commit, and platform confirm uses message identity. Extend them only if touched. [Source: `tests/test_mcp_adapter.py`; `tests/test_platform_sidecar.py`]

### Architecture Compliance

- Do not weaken the player-safe chain: ordinary gameplay facts must still move through `player_turn -> pending action -> player_confirm -> validation -> commit`.
- Do not treat pending action as an accepted fact. Pending files are runtime entry state until confirmation submits them to the validated commit path.
- Do not expose raw `delta`, full `TurnProposal`, hidden facts, raw `session_key`, raw `actor_id`, or AI private reasoning in player-safe responses.
- Do not add new gameplay write authority to CLI, MCP, platform, prewarm, preflight, query, preview, or resident/advisory AI paths.
- Do not move pending action into Save SQLite as a gameplay fact for this story.
- Do not rename public product/API concepts just to match PRD wording. Keep implementation names such as `Campaign Package`, `SaveManager`, `GMRuntime`, `TurnProposal`, and `player_turn_commit`.

### Relevant Files

- `rpg_engine/save_manager.py`: primary implementation surface for `player_confirm()`, pending action read/write/clear behavior, platform/session/actor identity checks, and public confirmation result shape.
- `rpg_engine/runtime.py`: `GMRuntime.commit_turn()` validation profile and proposal gate.
- `rpg_engine/commit_service.py`: validation profile, digest, expected-turn, command-id, proposal-id, and duplicate-commit guards.
- `rpg_engine/proposal.py`: `TurnProposal` parsing and approval/confirmation semantics.
- `rpg_engine/platform_sidecar.py`: platform confirm forwarding and session/actor gate.
- `rpg_engine/mcp_adapter.py`: MCP player confirm wrapper and low-level profile restrictions.
- `rpg_engine/cli_v1.py`: CLI player/platform confirm adapters.
- `tests/test_save_manager.py`: primary focused integration tests for real pending action, authoritative SQLite no-mutation, and confirm success/failure semantics.
- `tests/test_package_save_condition_coverage.py`: helper and branch coverage for SaveManager confirm edge cases.
- `tests/test_runtime.py`: low-level runtime validation/commit guard tests.
- `tests/test_mcp_adapter.py`, `tests/test_platform_sidecar.py`, and `tests/test_v1_cli.py`: surface tests to extend only if public confirm wrappers or result shape change.
- `tests/test_surface_inventory.py` and `tests/test_namespace_boundaries.py`: authority/taxonomy guardrails to run if surface metadata or category semantics change.

### Testing Requirements

Run the smallest meaningful gate for the implemented diff:

```bash
python3 -m pytest -q tests/test_save_manager.py tests/test_runtime.py
git diff --check
```

If helper-only confirm branches change, also run:

```bash
python3 -m pytest -q tests/test_package_save_condition_coverage.py
```

If MCP, CLI, or platform confirm wrappers or public result shapes change, also run:

```bash
python3 -m pytest -q tests/test_mcp_adapter.py tests/test_v1_cli.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py
```

If surface taxonomy or low-level permission boundaries change, also run:

```bash
python3 -m pytest -q tests/test_surface_inventory.py tests/test_namespace_boundaries.py
```

Run markdown/link and full regression gates when the diff is no longer small:

```bash
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m pytest -q
```

### Residual Risk Notes

- Round 7 already hardened pending action TTL, platform/session identity, and actor identity. Preserve the single-actor platform binding model; multi-actor party/session modeling remains out of scope until a separate contract story exists. [Source: `_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`]
- UI/Agent copy for clarification vs pending proposal vs expired action remains a residual risk. This story should keep player-facing expired-action messaging clear but should not design a full UI transcript system.
- Commit failure and projection failure are different. Validation/commit rejection must not write gameplay facts; projection dirtiness after a successful commit should remain visible in `projection_status` rather than being treated as a failed confirmation unless current commit contracts already do so.

### Latest Technical Information

No external web research is required for this story. Use existing Python stdlib, SQLite, dataclass/dict payload patterns, current validation pipeline, and pytest fixtures. Do not add runtime dependencies.

## Project Structure Notes

Story 1.3 should stay inside the existing kernel boundary. The expected implementation center is `rpg_engine/save_manager.py` plus focused tests. Changes to `runtime.py`, `commit_service.py`, `proposal.py`, MCP, CLI, or platform code should be made only if the focused tests expose an actual boundary bug or public result contract gap.

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`
- `_bmad-output/implementation-artifacts/1-2-player-turn-pending-contract.md`
- `docs/project-context.md`
- `rpg_engine/save_manager.py`
- `rpg_engine/runtime.py`
- `rpg_engine/commit_service.py`
- `rpg_engine/proposal.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/cli_v1.py`
- `tests/test_save_manager.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_runtime.py`
- `tests/test_mcp_adapter.py`
- `tests/test_platform_sidecar.py`

## Dev Agent Record

### Agent Model Used

TBD

### Debug Log References

- TBD

### Completion Notes List

- TBD

### File List

- TBD

## Change Log

- 2026-07-05: Created Story 1.3 from Epic 1 backlog, incorporating Story 1.2 learnings, current code inspection, and implementation boundary guidance; status set to ready-for-dev.
