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

## Round 5: Phase 3b ContextBuilder Intent Bundling

Status: **COMPLETE**

Goal:

Bundle ContextBuilder's internal intent configuration and passive request
identity into `IntentAIConfig` and `IntentRequestMeta` while preserving the
existing `build_context()` public signature and rendered request shape.

Code scope:

- `rpg_engine/context_builder.py`
- `tests/test_runtime.py`

Runtime behavior impact:

- `BuildState` now carries internal `intent_config` and `request_meta` value
  objects.
- `build_context()` still accepts the same public parameters.
- `classify_request()` now passes normalized internal config/meta values from
  those objects into `route_intent()`.
- Existing rendered `request["intent_ai"]` fields continue to use the
  pre-existing BuildState display fields, so this round does not change the
  context packet surface.
- External candidate input remains separate from passive request metadata.
- Runtime, MCP, CLI, SaveManager, platform, preflight-cache, resolver,
  validation, and commit code are unchanged.

Added regression coverage:

- `test_start_turn_bundles_context_builder_intent_config_without_changing_request_surface`
  - Confirms `start_turn()` / ContextBuilder sends normalized intent config into
    the intent route trace.
  - Confirms the existing `context.request["intent_ai"]` display surface stays
    compatible for raw backend/provider/model fields and clamped pending wait.

Verification so far:

```bash
python3 -m compileall -q rpg_engine/context_builder.py tests/test_runtime.py

python3 -m pytest -q tests/test_runtime.py \
  -k "start_turn_bundles_context_builder_intent_config or start_turn_records_external_intent_candidate or preview_from_text_bundles_runtime_intent_config"

python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or player_workflow or standard_entry or external_candidate"

python3 -m pytest -q tests/test_current_native_context.py tests/test_context_quality.py tests/test_runtime.py \
  -k "context or start_turn or start_turn_bundles_context_builder_intent_config"

python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_save_manager.py \
  -k "intent_ai or intent_router or external_intent_candidate or semantic_suggestion or gold_set or candidate_preparation_characterization or route_preparation_cases_unsaved or prepare_intent_candidates or conflicting_external_candidate or start_turn_bundles_context_builder_intent_config"

git diff --check
```

Result:

```text
compileall passed
3 passed, 57 deselected
13 passed, 18 deselected, 17 subtests passed
24 passed, 56 deselected, 25 subtests passed
21 passed, 88 deselected, 40 subtests passed
git diff --check passed
```

Expert code review:

- Engine boundary: pass. Confirmed normalized config/meta are internal only and
  public/deferred boundaries remain untouched.
- AI intent safety: pass. Confirmed `IntentRequestMeta` remains passive-only
  and external candidate input stays separate.
- Gameplay turn flow: pass. Confirmed `start_turn()` and context packet behavior
  remain compatible.
- Platform/MCP integration: pass. Confirmed no MCP, CLI, SaveManager, platform,
  Runtime, preflight-cache, or intent-router files changed.
- QA/regression: pass. Confirmed route trace normalization and existing context
  request display behavior are covered.
- Repo/docs: pass. Confirmed the implementation log matches the staged diff and
  verification results.

Documentation sync:

- This implementation log records the Phase 3b ContextBuilder-only bundling
  scope and intentionally defers MCP/CLI/SaveManager call-site bundling to
  Phase 3c.
- Final Round 5 expert review is complete with no blockers.

## Round 6: Phase 3c1 MCP Low-Level Intent Input Bundling

Status: **COMPLETE**

Goal:

Start Phase 3c by bundling the low-level MCP adapter's Runtime intent inputs
without changing MCP tool signatures, audit request shape, profile gates, or
SaveManager/CLI/platform entry points.

Code scope:

- `rpg_engine/mcp_adapter.py`
- `tests/test_mcp_adapter.py`

Runtime behavior impact:

- `AIGMMCPAdapter.start_turn()` now validates effective intent settings with
  `IntentAIConfig` and creates `IntentRequestMeta` inside the audited callback
  after MCP profile/freshness gates and after resolving the Runtime save.
- `start_turn()` still passes the effective display values through to
  Runtime/ContextBuilder so `context.request["intent_ai"]` remains compatible
  while `decision_trace["intent_ai"]` carries normalized routing values.
- `AIGMMCPAdapter.preview_from_text()` now creates `IntentRequestMeta` inside
  the audited callback and uses `IntentAIConfig` for non-empty text.
- Empty `preview_from_text()` input intentionally keeps intent config
  validation inside `GMRuntime.preview_from_text()` so the existing "describe
  your action" clarification still wins over invalid backend settings.
- MCP public arguments, request/audit fields, low-level tool availability,
  player-profile override checks, and pending clarification handling are
  unchanged.
- External candidate input remains separate from passive `IntentRequestMeta`.
- CLI, SaveManager, platform, ContextBuilder, Runtime, preflight-cache,
  resolver, validation, and commit code are unchanged.

Added regression coverage:

- `test_mcp_preview_empty_text_keeps_clarification_before_intent_config_validation`
  - Confirms MCP text preview still returns the empty-user-text clarification
    even when a bad intent backend override is supplied.
  - Guards against moving intent config validation ahead of the Runtime
    empty-text boundary.
- `test_mcp_start_turn_bundling_preserves_request_surface_aliases`
  - Confirms MCP `start_turn()` preserves request-surface alias/case values for
    display while the decision trace keeps normalized internal routing values.
  - Guards against adapter-level bundling changing the public response surface.

Verification so far:

```bash
python3 -m py_compile rpg_engine/mcp_adapter.py tests/test_mcp_adapter.py

python3 -m pytest -q tests/test_mcp_adapter.py \
  -k "start_turn_bundling_preserves_request_surface_aliases or empty_text_keeps_clarification or direct_options or player_profile_start"

python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or player_workflow or standard_entry or external_candidate"

python3 -m pytest -q tests/test_mcp_adapter.py

git diff --check
```

Result:

```text
py_compile passed
4 passed, 19 deselected
13 passed, 20 deselected, 17 subtests passed
23 passed
git diff --check passed
```

Expert code review:

- Initial QA review found a blocking response-surface regression in MCP
  `start_turn()` when normalized intent config kwargs were passed into Runtime.
  The fix keeps Runtime/ContextBuilder display kwargs as effective call values
  while retaining adapter-side config validation and bundled request metadata.
- Engine boundary: pass. Confirmed the response-surface regression is fixed and
  `start_turn()` no longer passes normalized config kwargs into Runtime.
- AI intent safety: pass. Confirmed `external_intent_candidate` remains separate
  from passive `IntentRequestMeta`, empty preview still clarifies first, and
  non-empty preview normalization does not expose a context request surface.
- Gameplay turn flow: pass. Confirmed player profile gates and pending
  clarification freshness still run before adapter-side validation/bundling.
- Platform/MCP integration: pass. Confirmed MCP signatures, profile tool
  registration, audit capture, SaveManager, and platform entry paths remain
  unchanged.
- QA/regression: pass. Confirmed the new start-turn alias/case regression test
  covers the fixed blocker and current coverage is sufficient for this diff.
- Repo/docs: pass. Confirmed the implementation log matches the final diff,
  verification results, scope, and deferrals.

Residual risks:

- `start_turn()` now validates intent settings in the MCP adapter and again in
  ContextBuilder; future field additions must keep those helper mappings in
  sync.
- Non-empty `preview_from_text()` still passes normalized intent kwargs into
  Runtime. That is acceptable because it does not expose the same
  `context.request` surface as `start_turn()`, but future preview API changes
  should add alias-preservation coverage if such a surface appears.

Documentation sync:

- This implementation log records the Phase 3c1 MCP low-level adapter-only
  bundling scope and intentionally defers CLI/SaveManager call-site bundling to
  later Phase 3c rounds.
- Final Round 6 expert review is complete with no blockers.

## Round 7: Phase 3c2 SaveManager Intent Input Bundling

Status: **COMPLETE**

Goal:

Continue Phase 3c by bundling `SaveManager.player_turn()` intent settings and
passive request metadata before the Runtime player preview call, while keeping
the player-safe entry surface unchanged.

Code scope:

- `rpg_engine/save_manager.py`
- `tests/test_save_manager.py`

Runtime behavior impact:

- `SaveManager.player_turn()` now builds `IntentRequestMeta` before calling
  `GMRuntime.act()`.
- For non-empty player text, `player_turn()` builds `IntentAIConfig` and passes
  normalized intent settings into Runtime.
- Empty player text intentionally keeps intent config validation inside
  `GMRuntime.preview_from_text()` so the existing clarify-first behavior still
  wins over invalid backend settings.
- `player_turn()` still clears stale pending actions before preview, still
  writes pending player actions only when Runtime returns a ready proposal, and
  still hides `delta_draft` / `turn_proposal` from the player response.
- `player_act()` remains a compatibility wrapper over `player_turn()`.
- CLI, MCP, platform sidecar, Runtime, ContextBuilder, preflight-cache,
  resolver, validation, and commit code are unchanged.

Added regression coverage:

- `test_player_turn_empty_text_keeps_clarification_before_intent_config_validation`
  - Confirms SaveManager player turns still return the empty-user-text clarify
    response even when a bad intent backend is supplied.
  - Confirms no pending player action is created for that path.
- `test_player_turn_bundles_intent_inputs_without_exposing_internal_delta`
  - Confirms `player_turn()` can route through bundled intent config/meta while
    the public player response still hides internal delta/proposal fields.
  - Confirms the internal pending action trace carries normalized intent config
    values.

Verification so far:

```bash
python3 -m py_compile rpg_engine/save_manager.py tests/test_save_manager.py

python3 -m pytest -q tests/test_save_manager.py \
  -k "bundles_intent_inputs or empty_text_keeps_clarification or player_turn_standard_entry or player_turn_cli_accepts_external_candidate"

python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or player_workflow or standard_entry or external_candidate"

python3 -m pytest -q tests/test_save_manager.py

git diff --check
```

Result:

```text
py_compile passed
5 passed, 7 deselected, 12 subtests passed
15 passed, 20 deselected, 17 subtests passed
12 passed, 17 subtests passed
git diff --check passed
```

Expert code review:

- Engine boundary: pass. Confirmed SaveManager-only bundling preserves the
  public boundary and reran the focused SaveManager/MCP gates.
- AI intent safety: pass. Confirmed `external_intent_candidate` remains
  separate from passive `IntentRequestMeta`, empty text still clarifies before
  intent config validation, and pending action trace remains internal.
- Gameplay turn flow: pass. Confirmed pending clarification repeat blocking,
  pending action creation, hidden delta/proposal response, and `player_confirm`
  session requirements remain intact.
- Platform/MCP integration: pass. Confirmed MCP player entry, CLI arguments,
  and platform sidecar call paths are unchanged.
- QA/regression: pass. Confirmed the current targeted coverage is sufficient
  for this diff; direct SaveManager preflight-hit coverage can be added later
  if the path changes again.
- Repo/docs: pass. Confirmed implementation log scope and verification results
  match the diff.

Residual risks:

- Request metadata forwarding through SaveManager is covered indirectly by the
  MCP `player_act` message-only preflight path rather than by a new direct
  SaveManager-only preflight-hit test.
- If `make_intent_request_meta()` later gains stricter validation, re-check the
  empty-text path because SaveManager now builds passive request metadata before
  calling Runtime.

Documentation sync:

- This implementation log records the Phase 3c2 SaveManager-only bundling
  scope and intentionally defers CLI call-site bundling to the next Phase 3c
  round.
- Final Round 7 expert review is complete with no blockers.

## Round 8: Phase 3c3 CLI Intent Call-Site Bundling

Status: **COMPLETE**

Goal:

Finish Phase 3c call-site bundling by collecting repeated CLI intent,
external-candidate, passive preflight-consume, and preflight-production
arguments into helper kwargs before dispatching to Runtime or SaveManager.

Code scope:

- `rpg_engine/cli_v1.py`
- `tests/test_v1_cli.py`

Runtime behavior impact:

- Added CLI-only helpers for intent option kwargs, internal-review kwargs,
  passive preflight-consume kwargs, preflight-production identity kwargs,
  external intent candidate loading, combined preview kwargs, and preflight
  production kwargs.
- `play start-turn` and `play act` now pass bundled preview kwargs to Runtime.
- `play preflight` now passes bundled preflight-production kwargs to Runtime.
- `player turn` now passes bundled preview kwargs to SaveManager.
- `player act` now passes intent option kwargs plus passive preflight kwargs to
  SaveManager, intentionally keeping external candidate unsupported for that
  compatibility command.
- No CLI command names, flags, defaults, parser choices, Runtime signatures,
  SaveManager signatures, MCP surfaces, platform behavior, or intent-routing
  behavior changed.
- CLI helpers do not create `IntentAIConfig` or `IntentRequestMeta`; validation
  remains in Runtime/ContextBuilder/SaveManager as established in earlier
  rounds.

Added regression coverage:

- `test_cli_intent_helpers_preserve_option_and_preflight_surfaces`
  - Confirms intent option kwargs do not include external candidate payloads.
  - Confirms preview kwargs load external candidate JSON and preserve passive
    preflight metadata.
  - Confirms preflight-production kwargs exclude player-turn-only fields such
    as `intent_ai`, `preflight_id`, and pending-wait metadata while preserving
    identity profile and TTL.

Verification so far:

```bash
python3 -m py_compile rpg_engine/cli_v1.py tests/test_v1_cli.py

python3 -m pytest -q tests/test_v1_cli.py \
  -k "cli_intent_helpers or play_start_query_preview_and_commit_commands"

python3 -m pytest -q tests/test_save_manager.py \
  -k "player_turn_cli_accepts_external_candidate or player_act_confirm_hides_internal_delta"

python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or player_workflow or standard_entry or external_candidate"

python3 -m pytest -q tests/test_v1_cli.py

python3 -m pytest -q tests/test_save_manager.py

git diff --check
```

Result:

```text
py_compile passed
2 passed, 12 deselected
2 passed, 10 deselected
15 passed, 20 deselected, 17 subtests passed
14 passed
12 passed, 17 subtests passed
git diff --check passed
```

Expert code review:

- Initial repo/docs review found the Round 8 log under-reported the final
  `play preflight` helper bundling scope. The log was updated to include
  internal-review kwargs, preflight-production identity kwargs,
  `intent_preflight_kwargs_from_args()`, and `play preflight` dispatch.
- Engine boundary: pass. Confirmed CLI helpers preserve Runtime/SaveManager
  kwarg surfaces and do not introduce `IntentAIConfig` / `IntentRequestMeta`
  validation at the CLI layer.
- AI intent safety: pass. Confirmed external candidates remain limited to
  preview/preflight-capable helpers, passive metadata remains separate, and
  empty-text/error priority stays owned by Runtime/SaveManager.
- Gameplay turn flow: pass. Confirmed `player turn` still produces pending
  work without committing, `player act` still rejects external candidate flags,
  and `player confirm` remains the commit path.
- Platform/MCP integration: pass. Confirmed no MCP adapter, MCP profile/tool
  surface, `mcp serve` config, platform sidecar, platform CLI, or player CLI
  argument regression.
- QA/regression: pass. Confirmed helper-level coverage and existing CLI /
  SaveManager gates are sufficient for this diff.
- Repo/docs: pass. Confirmed Round 8 documentation now matches the final diff,
  verification results, scope, and Phase 4 deferral.

Residual risks:

- `play preflight` helper dispatch is covered by helper-shape assertions and
  existing Runtime/preflight tests, not by a new subprocess CLI end-to-end test
  with non-default preflight flags.
- CLI helper functions assume the parser namespace contains the expected
  attributes, so future reuse on unrelated subcommands should add targeted
  tests or keep helpers scoped to matching parser surfaces.
- Existing behavior remains that `play preflight` registers `--intent-ai`
  through shared parser setup but does not pass it to `GMRuntime.preflight_intent`;
  Round 8 preserves that behavior rather than changing it.

Documentation sync:

- This implementation log records the Phase 3c3 CLI-only call-site bundling
  scope. Phase 4 platform verification remains separate and should not be
  combined into this round.
- Final Round 8 expert review is complete with no blockers.

## Round 9: Phase 4 Platform Verification

Status: **COMPLETE**

Goal:

Verify the platform sidecar and prewarm paths after Phases 1-3, without
changing platform behavior.

Code scope:

- `docs/architecture/intent-refactor-implementation-log.md`

Runtime behavior impact:

- No runtime, platform, MCP, CLI, SaveManager, preflight-cache, intent-router,
  resolver, validation, or commit behavior changed.
- Platform prewarm remains advisory and creates only message-only preflight
  records.
- Platform act remains a passive-identity forwarding path into
  `SaveManager.player_turn()`.
- Platform confirm remains a forwarding path into `SaveManager.player_confirm()`.

Verification so far:

```bash
python3 -m pytest -q tests/test_platform_prewarm.py tests/test_platform_ai_simulation.py

python3 -m pytest -q tests/test_platform_sidecar.py
```

Result:

```text
11 passed, 21 subtests passed
5 passed
```

Expert code review:

- Engine boundary: pass. Confirmed Round 9 is documentation-only and no
  Runtime/MCP/CLI/SaveManager/platform behavior code changed.
- AI intent safety: pass. Confirmed platform prewarm remains advisory
  message-only preflight, platform act/confirm do not decide final intent, and
  passive identity/external candidate boundaries are unchanged.
- Gameplay turn flow: pass. Confirmed platform act still routes to
  `SaveManager.player_turn()` and platform confirm still routes to
  `SaveManager.player_confirm()`.
- Platform/MCP integration: pass. Confirmed platform prewarm, AI simulation,
  and sidecar coverage are aligned with the Phase 4 boundary and MCP/CLI/player
  surfaces are unchanged.
- QA/regression: pass. Confirmed Phase 4 minimum verification plus sidecar
  tests are sufficient for this verification-only round.
- Repo/docs: pass. Confirmed documentation scope and verification results match
  the diff and git hygiene is clean.

Residual risks:

- Platform tests use fake AI, temporary workspaces, and in-process sidecar /
  worker paths; real platform connector, real MCP client, and real model canary
  coverage remain outside Round 9.
- Platform act is "not committed" in the gameplay-fact sense: it may still write
  pending action and last-played metadata, but it does not commit a turn or
  gameplay facts until `player_confirm()`.
- Pending action storage remains a workspace-level single slot; multi-platform
  or multi-session scoped pending stores remain future hardening work.
- Preflight cache privacy hardening for raw `session_key` / `user_text` remains
  existing technical debt, not a Round 9 regression.

Documentation sync:

- This implementation log records the Phase 4 platform verification-only scope.
  No behavior change was required.
- Final Round 9 expert review is complete with no blockers.
