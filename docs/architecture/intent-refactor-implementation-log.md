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
