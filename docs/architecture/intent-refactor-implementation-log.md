# Intent Refactor Implementation Log

Status: **CURRENT：分轮实施记录**

Date: 2026-07-03

This log records implementation rounds for the intent preparation and future
coordinator work. It complements:

- `docs/architecture/intent-coordinator-refactor-plan.md`
- `docs/architecture/intent-coordinator-team-review.md`
- `docs/architecture/intent-design-alignment-review.md`
- `docs/architecture/future-turn-coordinator-design.md`

Each round must record:

1. Scope.
2. Runtime behavior impact.
3. Verification.
4. Expert code review result.
5. Documentation sync.

## Round 1: Phase 1a Candidate Preparation Characterization

Status: **COMPLETE**

Goal:

Lock the current route-preparation behavior before extracting
`prepare_intent_candidates()`.

Code scope:

- `tests/test_runtime.py`
- `tests/test_save_manager.py`

Runtime behavior impact:

- None intended.
- No `rpg_engine/` runtime code changed.
- No public MCP, CLI, Runtime, SaveManager, or platform signature changed.

Added coverage:

- `test_intent_candidate_preparation_characterization_snapshots`
- `test_player_turn_surface_keeps_route_preparation_cases_unsaved`

The route-level test locks representative no-internal-AI, rule-first,
low-level candidate-preparation snapshots for:

- read-only query
- single action with a low-trust external candidate
- maintenance/system request blocked out of player intent mode
- composite plan boundary
- explicit mode/submode routing

This is a low-level `route_intent` characterization. It is not a new public
surface and does not change the standard player workflow:

```text
player_turn -> player_confirm
```

`preview_from_text` remains a low-level primitive. The external candidate in
this round is advisory/low-trust route input; it is recorded for trace and
future consensus, but it does not override final route authority in
`intent_ai=off`.

Protected fields:

- `trace["explicit"]`
- `legacy_rule_route.rule`
- `legacy_rule_route.inferred`
- `legacy_rule_route.outcome`
- `legacy_rule_route.guards`
- full `rules_candidate` candidate snapshot
- `intent_ai.rules_candidate`
- full normalized external candidate snapshot, including provenance
- `intent_ai.decision.status`
- `intent_ai.decision.source`
- selected outcome
- final intent
- internal final `ActionIntent` fields used before player-facing rendering:
  `user_text`, `mode`, `submode`, `action`, `kind`, `status`, `source`,
  `player_message`, `missing_required`, `needs_confirmation`, `errors`,
  `summary`, `plan`, `repair_options`, and `clarification`

The player-surface sentinel locks the corresponding standard entry behavior:

- query stays read-only with no pending action
- a single action creates a pending confirmation session but does not save
- maintenance/system requests stay blocked with no pending action
- composite action stays non-saveable and does not create a confirmation
  session
- entity query stays read-only with no pending action

The current maintenance/system snapshot intentionally records the legacy rules
candidate shape. The safety boundary is the blocked final outcome plus legacy
guards, not the absence of a candidate safety flag.

Verification:

```bash
python3 -m pytest -q tests/test_runtime.py -k "candidate_preparation_characterization"

python3 -m pytest -q tests/test_save_manager.py -k "route_preparation_cases_unsaved"

python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_save_manager.py \
  -k "intent_ai or intent_router or external_intent_candidate or semantic_suggestion or gold_set or candidate_preparation_characterization or route_preparation_cases_unsaved"
```

Result:

```text
1 passed, 53 deselected, 5 subtests passed
1 passed, 9 deselected, 5 subtests passed
18 passed, 85 deselected, 40 subtests passed
```

Expert code review:

Six read-only expert reviews were completed:

- Engine Boundary Code Reviewer
- AI Intent Safety Code Reviewer
- Gameplay Turn Flow Code Reviewer
- Platform/MCP Integration Code Reviewer
- QA / Regression Code Reviewer
- Repo Maintainer / Docs Sync Reviewer

Accepted findings and fixes:

- Added full candidate snapshots, including `source`, `plan`, and `reason`.
- Added `intent_ai.decision.status/source` assertions to preserve external AI
  low-trust behavior.
- Added internal final `ActionIntent` fields required by Phase 1a review.
- Added direct `intent.user_text` coverage for normalized text.
- Added `SaveManager.player_turn()` surface sentinel for query/action/block/
  composite save-boundary behavior.
- Clarified that this is low-level route characterization, not a new public
  surface or public player contract.
- Clarified that the composite legacy `rules_candidate.action` is only legacy
  trace shape; final intent/pending/proposal must not use it as a saveable
  single action.

Follow-up signoff:

- AI Intent Safety, QA / Regression, and Repo Maintainer / Docs Sync reviewers
  re-reviewed the final diff after fixes.
- No blockers remained.
- Final staged diff remained docs/tests only, with no runtime code changes.

Documentation sync:

- This log was created and indexed from `docs/README.md`.
- `docs/architecture/module-map.md` links this log as implementation evidence.

## Round 2: Phase 1b Extract Side-Effect-Limited Candidate Preparation

Status: **COMPLETE**

Goal:

Extract a side-effect-limited `prepare_intent_candidates()` helper inside
`intent_router.py` while keeping `route_intent(...)` as the compatibility
facade. "Side-effect-limited" means no AI, preflight consumption, arbitration,
binding, preview, pending-action creation, save validation, or commit. The
helper still reads current campaign state through legacy rule routing and action
inference to prepare deterministic candidates.

Code scope:

- `rpg_engine/intent_router.py`
- `tests/test_runtime.py`

Runtime behavior impact:

- Behavior-preserving refactor intended.
- `route_intent(...)` public signature unchanged.
- No `AIIntentRouter`, preflight cache, resolver, validation, commit,
  SaveManager, MCP, CLI, or platform code changed.

Added internal types:

- `IntentAIConfig`
- `IntentRequestMeta`
- `ExternalCandidateInput`
- `PreparedIntentCandidates`

Added helpers:

- `make_intent_ai_config()`
- `make_intent_request_meta()`
- `prepare_intent_candidates()`

Preparation helper boundary:

- Normalizes player text.
- Normalizes optional low-trust external candidate.
- Builds legacy rule route.
- Builds deterministic rules candidate.
- Returns the external input as `external_low_trust_candidate`; this is trace
  and AI-router input, not an authority to apply directly.
- May read the campaign DB through legacy route/action inference.
- Does not call AI.
- Does not consume preflight.
- Does not arbitrate.
- Does not bind slots.
- Does not preview, validate, create pending action, or commit.

Verification so far:

```bash
python3 -m pytest -q tests/test_runtime.py \
  -k "prepare_intent_candidates or candidate_preparation_characterization or conflicting_external_candidate"

python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_save_manager.py \
  -k "intent_ai or intent_router or external_intent_candidate or semantic_suggestion or gold_set or candidate_preparation_characterization or route_preparation_cases_unsaved or prepare_intent_candidates or conflicting_external_candidate"
```

Result:

```text
3 passed, 53 deselected, 5 subtests passed
20 passed, 85 deselected, 40 subtests passed
```

Expert code review:

- Engine boundary: pass. Noted non-blocking risk that helper tests should make
  side-effect boundaries explicit.
- AI intent safety: requested a conflicting low-trust external-candidate
  negative case before safety signoff.
- Gameplay turn flow: pass. Confirmed ordinary player flow remains
  `player_turn -> player_confirm`; `route_intent`, `prepare_intent_candidates`,
  and `preview_from_text` are not normal player entry points.
- Platform/MCP integration: pass. Confirmed MCP/CLI/platform and SaveManager
  surfaces did not gain external candidate intake or new entry points.
- QA/regression: pass with non-blocking suggestions to assert all
  `IntentRequestMeta` and `IntentAIConfig` normalization fields.
- Repo/docs: pass with request to avoid calling the helper strictly "pure".

Review fixes applied:

- Added `test_route_intent_keeps_conflicting_external_candidate_trace_only_when_ai_off`.
- Expanded helper tests to assert `IntentRequestMeta` full field values,
  empty-string normalization, and `IntentAIConfig` backend/fallback/provider/
  model/base-url/api-key normalization.
- Renamed prepared external field from `external_for_live_route` to
  `external_low_trust_candidate`.

Documentation sync:

- Updated Round 2 terminology from "pure" to "side-effect-limited".
- Synced architecture docs that referenced the prepared external-candidate
  field name.
- Final expert follow-up review complete. Engine boundary, AI intent safety,
  gameplay turn flow, Platform/MCP integration, QA/regression, and repo/docs
  reviewers all signed off with no blockers.
