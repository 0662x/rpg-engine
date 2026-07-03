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

## Round 3: Phase 2 Reuse Candidate Preparation In Preflight

Status: **COMPLETE**

Goal:

Make `GMRuntime.preflight_intent()` reuse the same side-effect-limited
candidate preparation helper as live routing.

Code scope:

- `rpg_engine/runtime.py`
- `tests/test_runtime.py`

Runtime behavior impact:

- `GMRuntime.preflight_intent()` no longer hand-builds external/rules
  candidates.
- Candidate-bound preflight passes `ExternalCandidateInput` to
  `prepare_intent_candidates()` and uses the resulting
  `external_low_trust_candidate` plus `rules_candidate`.
- `message_only` preflight still routes supplied external input through
  preparation so schema errors surface as before, but drops the prepared
  external candidate before cache creation and internal review. The cache
  identity stays passive.
- Preflight cache creation, identity profile normalization, pending/ready/failed
  transitions, helper audit, and commits remain in `GMRuntime.preflight_intent()`.
- No MCP, CLI, platform, `AIIntentRouter`, `preflight_cache`, resolver,
  validation, or commit code changed.

Added regression coverage:

- `test_preflight_reuses_prepared_candidate_inputs`
  - Captures the `rule_candidate` and `external_candidate` passed to internal
    intent review during candidate-bound preflight.
  - Compares them to `prepare_intent_candidates()` output.
  - Verifies `message_only` preflight still passes no external candidate to
    internal review while using the same prepared rules candidate.
- `test_message_only_preflight_still_validates_supplied_external_candidate`
  - Preserves the existing schema rejection behavior for malformed supplied
    external candidates even under `message_only`.

Verification so far:

```bash
python3 -m pytest -q tests/test_runtime.py \
  -k "preflight_reuses_prepared_candidate_inputs or message_only_preflight or preflight_cache_reuses"

python3 -m pytest -q tests/test_preflight_cache.py tests/test_runtime.py tests/test_mcp_adapter.py \
  -k "preflight"

git diff --check
```

Result:

```text
5 passed, 53 deselected
29 passed, 68 deselected
git diff --check passed
```

Expert code review:

- Engine boundary: pass after preserving `message_only` supplied external
  schema validation while still dropping the prepared external before cache
  creation/internal review.
- AI intent safety: pass. Optional tighter error-message assertion was applied.
- Gameplay turn flow: pass. Confirmed preflight state ordering and player-facing
  flow boundaries are unchanged.
- Platform/MCP integration: pass. Confirmed no MCP, CLI, platform, SaveManager,
  or preflight-cache entry files changed.
- QA/regression: pass after the `message_only` malformed external behavior was
  restored and covered.
- Repo/docs: pass. Confirmed log wording matches the final compatibility
  behavior and verification results.

Review fixes applied:

- Changed the first draft from "skip external preparation for `message_only`"
  to "prepare all supplied external input, then drop the prepared external for
  `message_only` before cache/internal review".
- Added malformed external candidate regression coverage for `message_only`.
- Tightened the regression to assert the schema-validation error message.

Documentation sync:

- This implementation log records the Phase 2 change and its current
  verification gate.
- Final Round 3 expert review is complete with no blockers.

## Round 4: Phase 3a Runtime Text Preview Intent Bundling

Status: **COMPLETE**

Goal:

Start Phase 3a by bundling Runtime's text-preview intent parameters into the
existing `IntentAIConfig` and `IntentRequestMeta` value objects before calling
`route_intent()`.

Code scope:

- `rpg_engine/runtime.py`
- `tests/test_runtime.py`

Runtime behavior impact:

- `GMRuntime.preview_from_text()` now builds `IntentAIConfig` and
  `IntentRequestMeta` after the empty-text guard and before opening the DB
  connection.
- The public `GMRuntime.preview_from_text()` and `GMRuntime.act()` signatures
  are unchanged.
- `GMRuntime.act()` still delegates to `preview_from_text()` with the same
  public arguments.
- `GMRuntime.start_turn()` and `ContextBuilder` are intentionally unchanged;
  ContextBuilder bundling remains Phase 3b.
- External candidate input remains a separate low-trust argument and is not
  placed inside passive `IntentRequestMeta`.
- No MCP, CLI, SaveManager, platform, preflight-cache, resolver, validation, or
  commit code changed.

Added internal helpers:

- `intent_ai_config_kwargs()`
- `intent_request_meta_kwargs()`

Added regression coverage:

- `test_preview_from_text_bundles_runtime_intent_config_after_empty_text_guard`
  - Confirms empty text still returns a clarification before invalid intent
    backend validation.
  - Confirms Runtime text preview still passes normalized backend/provider/
    model/timeout/base-url/api-key/fallback settings into intent trace.

Verification so far:

```bash
python3 -m compileall -q rpg_engine/runtime.py tests/test_runtime.py

python3 -m pytest -q tests/test_runtime.py \
  -k "preview_from_text_bundles_runtime_intent_config or external_intent_candidate_schema_error or start_turn_records_external_intent_candidate"

python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or player_workflow or standard_entry or external_candidate"

python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_save_manager.py \
  -k "intent_ai or intent_router or external_intent_candidate or semantic_suggestion or gold_set or candidate_preparation_characterization or route_preparation_cases_unsaved or prepare_intent_candidates or conflicting_external_candidate or preview_from_text_bundles_runtime_intent_config"

git diff --check
```

Result:

```text
compileall passed
3 passed, 56 deselected
13 passed, 18 deselected, 17 subtests passed
21 passed, 87 deselected, 40 subtests passed
git diff --check passed
```

Expert code review:

- Engine boundary: pass. Confirmed empty-text guard still precedes intent
  config validation and public signatures are unchanged.
- AI intent safety: pass. Confirmed `IntentRequestMeta` remains passive-only and
  external candidate input stays separate.
- Gameplay turn flow: pass. Confirmed player-facing text preview behavior stays
  unchanged.
- Platform/MCP integration: pass. Confirmed no MCP, CLI, SaveManager, platform,
  or ContextBuilder files changed.
- QA/regression: pass. Confirmed staged diff preserves existing public surfaces
  and focused gates passed.
- Repo/docs: pass. Confirmed the implementation log matches the staged diff and
  verification results.

Documentation sync:

- This implementation log records the Phase 3a Runtime-only bundling scope and
  intentionally defers ContextBuilder/MCP/SaveManager bundling to Phases 3b/3c.
- Final Round 4 expert review is complete with no blockers.
