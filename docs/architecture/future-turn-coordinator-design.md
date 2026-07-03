# Future Turn Coordinator Design

Status: **PROPOSED：未来协调层设计，尚未实施代码**

Date: 2026-07-03

This document records the future `IntentCoordinator` / `TurnCoordinator`
design. It follows the historical AI intent goals in
`docs/architecture/intent-design-alignment-review.md` and the near-term
preparation-first refactor in
`docs/architecture/intent-coordinator-refactor-plan.md`.

Short answer:

```text
Coordinator = orchestration and trace.
Coordinator != new authority.
```

The next code work should still start with **Intent Candidate Preparation
Refactor**. This document describes what that work is paving toward.

## Review Method

Six read-only specialist reviews informed this design:

| Role | Main question |
| --- | --- |
| Engine Kernel Coordinator Architect | How should SaveManager, Runtime, intent routing, AI routing, validation, commit, and projection remain separated? |
| AI Intent Safety / Trust Boundary Lead | Which authority boundaries must a coordinator never flatten? |
| Gameplay / Player Experience Turn Flow Designer | What state machine should players and player-facing AI clients see? |
| Platform / MCP Integration Architect | How should MCP, CLI, platform sidecar, prewarm, and external AI candidates connect? |
| QA / Evaluation / Release Lead | Which tests, trace schema, eval metrics, and rollback gates are required? |
| Incremental Refactor / Repo Maintainer | How should this evolve without import churn, broad rewrites, or upstream-update pain? |

The consensus is conditional: a coordinator is useful only if it remains a thin
internal orchestrator and does not absorb router, binder, resolver, validation,
commit, projection, MCP profile, or platform gate authority.

## Current Ownership

| Owner | Current responsibility |
| --- | --- |
| `SaveManager` | Active save, registry, `player_turn` response shaping, pending action, pending clarification, `player_confirm` session/platform checks. |
| `GMRuntime` | Transitional facade for preflight production, context/start turn, natural-language preview, query, resolver preview, validation, commit, and health. |
| `intent_router.route_intent` | Current compatibility route facade: normalize text/external input, build legacy route, build rules candidate, call `AIIntentRouter`, assemble `ActionIntent`. |
| `AIIntentRouter` | Preflight consumption, live internal review, arbiter call, internal-unavailable fallback policy, selected outcome trace. |
| Arbiter | Compare external/internal/rules candidates and decide accept, clarify, block, or fallback. |
| Binder | Bind slots to player-visible entities and resolver options. |
| Action resolvers | Domain preview, request/resolve/delta contracts, proposed delta. |
| `ValidationPipeline` | Proposal/delta/write/profile/state-audit gate; produces report and digest; does not write. |
| `CommitService` | Validated fact write, backup, turn delta persistence, post-commit projection refresh. |
| `ProjectionService` | Snapshot/cards/events/search/memory/report refresh status and repair. |
| MCP/CLI/platform adapters | Thin public surfaces, profile gates, path/session/platform gates, passive identity forwarding. |

The problem is scattered orchestration and repeated parameter/candidate
assembly. The problem is not that any one of these owners should take over the
others.

## Future Layering

Target layering:

```text
MCP / CLI / Platform / Host UI
  -> SaveManager
     -> TurnCoordinator
        -> IntentCoordinator
           -> IntentPreparation
           -> AIIntentRouter
              -> arbiter
              -> binder
        -> Runtime query / preview facade
        -> ValidationPipeline
        -> CommitService
        -> ProjectionService
```

Important:

- `SaveManager` still owns player pending state and `player_confirm`.
- `TurnCoordinator` orchestrates a turn, but it does not own save authority.
- `IntentCoordinator` orchestrates intent understanding, but it does not own
  resolver or commit authority.
- Public surfaces keep stable names. Do not expose a raw
  `coordinate_intent`/`turn_coordinator` player tool.

## IntentCoordinator

`IntentCoordinator` is the future internal owner for the intent understanding
sequence.

It may own:

- constructing `IntentAIConfig`
- constructing passive `IntentRequestMeta`
- receiving separate low-trust `ExternalCandidateInput`
- calling pure `prepare_intent_candidates()`
- calling `AIIntentRouter.route_candidates()`
- returning `ActionIntent`
- returning versioned trace/provenance
- distinguishing live route, `candidate_bound` preflight, and `message_only`
  preflight

It must not own:

- save registry, pending action, pending clarification, or `player_confirm`
- MCP/player profile gates or platform session gates
- external AI authority
- internal candidate injection from outside the kernel
- arbiter policy reimplementation
- binder slot rules reimplementation
- resolver/domain/action rules
- delta construction outside resolvers
- validation stages
- commit, backup, projection, or repair

Phase 1 code should not create this full class yet. It should first extract
the pure preparation pieces inside `intent_router.py`.

## TurnCoordinator

`TurnCoordinator` is the future internal owner for player-turn orchestration.

It may own:

- `player text -> intent -> query/action/clarify/block/plan` orchestration
- one stage report for the turn
- one recommended next step
- a consistent trace across intent, preview, validation, and commit
- avoiding duplicate route calls between `start_turn`, `preview_from_text`, and
  future `plan_turn`
- optional shadow-mode comparison between old and new paths

It must not own:

- low-level MCP/profile permission decisions
- platform binding, platform prewarm queue, or bot/self/duplicate gates
- action resolver business logic
- validation rule internals
- SQLite write details
- projection refresh details
- automatic player confirmation

`TurnCoordinator` should begin as a wrapper around existing owners, not a new
center that rewrites them.

## Player State Machine

The player-facing model should stay simple:

```text
I say what I want.
The engine answers, asks, previews, plans, or blocks.
I explicitly confirm.
Only then does the world change.
```

Future `TurnCoordinator` player-visible states:

| State | Meaning | Save effect |
| --- | --- | --- |
| `query_result` | Player-visible read-only result. | No save. |
| `clarification_required` | Engine needs a fresh player answer. | No save. |
| `blocked` | Unsafe, hidden, maintenance, impossible, or unsupported request. | No save. |
| `action_preview_ready` | One concrete action has a proposal and `session_id`. | Waits for `player_confirm`. |
| `plan_pending` | Composite action has been decomposed or needs plan confirmation. | No save. |
| `committed` | Confirmed proposal was written. | Saved. |
| `committed_projection_degraded` | Facts were saved, but projection refresh failed or was partial. | Saved, with degraded projection warning. |
| `failed` | Validation or commit failed. | Not saved unless report says otherwise. |

`preview_from_text` should remain a low-level facade/compatibility tool. The
default player workflow remains:

```text
start_or_continue -> player_turn -> player_confirm if needed
```

## Composite Plans

Composite action handling follows
`docs/architecture/composite-plan-turn-adr.md`.

Rules:

- `composite` is not directly saveable.
- `IntentCandidate.plan` is advisory and must not be executed directly.
- Future `plan_turn` may produce a `CompositeTurnPlan`.
- Plan confirmation is not confirmation for all later action outcomes.
- A plan uses `plan_id`; a saveable step uses `session_id`.
- Only the current executable step may produce a `TurnProposal`.
- Each step must be re-previewed against current state after earlier steps
  commit.
- Old plan/proposal/session ids must be rejected after stale turn/context/digest
  changes.

Target composite path:

```text
player_turn("go to X, ask Y, return")
  -> plan_pending(plan_id, steps)
  -> player chooses current step
  -> action_preview_ready(session_id)
  -> player_confirm(session_id)
  -> committed
  -> replan or preview next step from new state
```

## Trust Boundary Types

Future types should keep trust boundaries visible:

```python
@dataclass(frozen=True)
class IntentAIConfig:
    mode: str
    backend: str
    provider: str
    model: str
    timeout: int
    base_url: str
    api_key_env: str
    fallback_backend: str


@dataclass(frozen=True)
class IntentRequestMeta:
    preflight_id: str = ""
    message_id: str = ""
    platform: str = ""
    session_key: str = ""
    source_user_text_hash: str = ""
    preflight_pending_wait_ms: int = 0


@dataclass(frozen=True)
class ExternalCandidateInput:
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreparedIntentCandidates:
    text: str
    explicit_mode: str | None
    explicit_submode: str | None
    legacy_route: LegacyRuleRoute
    rules_candidate: IntentCandidate
    external_for_live_route: IntentCandidate | None
```

Additional future boundary types:

| Type | Boundary |
| --- | --- |
| `PlayerTextRoot` | Player source text as audit root. |
| `RulesCandidate` | Deterministic candidate/fallback/risk signal, not long-term main judge. |
| `InternalReview` | Engine-side semantic review, advisory only. |
| `PreflightIdentity` | Explicit `candidate_bound` or `message_only`, not ambiguous nullable fields. |
| `ArbitrationDecision` | Accept/clarify/block/fallback without delta/save authority. |
| `BoundIntent` | Slot binding result, still not a saved fact. |
| `TurnProposalPreview` | Resolver preview with `human_confirmed=false`. |
| `PendingActionConfirmation` | SaveManager-owned pending action with save/platform/session/session_id. |
| `CommitApproval` | Produced only by `player_confirm(session_id)` or trusted approved commit path. |

Hard rule:

`IntentRequestMeta` must never contain external candidate, internal candidate,
delta, proposal, permission, profile/model override, or save authority.

## Preflight And Prewarm

Preflight is an advisory internal-review cache.

`message_only`:

- Used when platform message arrives before external AI candidate.
- Must use `platform/session_key/message_id/source_user_text_hash`.
- Must pass `external_for_internal_review = None`.
- Must not bind external/rule candidate hashes.

`candidate_bound`:

- Used only for trusted/developer flows that already have an external candidate
  at preflight time.
- Must bind `preflight_id`, text hash, external candidate hash, rule candidate
  hash, model/schema/task/context identity.

Preflight hit:

- May replace only the live internal AI review call.
- Must still pass through arbiter, binder, resolver preview, validation,
  pending action, and `player_confirm`.
- Must never cache or replay delta, `TurnProposal`, or commit approval.
- Must fail back to normal live processing on miss, timeout, queue full, failed,
  expired, rejected, ambiguous, or late-ready cases.

## Public Surface Policy

Do not expose raw coordinator internals as player tools.

Player profile:

- keep `start_or_continue`
- keep safe save/campaign read/check/select tools
- keep read-only `intent_manifest`
- keep `player_turn`
- keep `player_confirm`
- do not expose `preview_from_text`, `preview_action`, `validate_delta`,
  `commit_turn`, `intent_preflight`, maintenance/admin tools, or per-call AI
  overrides

Developer/trusted profiles may keep low-level tools for diagnostics and
controlled operation. They should call the same internal coordination path
rather than duplicating route/preview/commit logic.

Platform sidecar:

- normalizes message events
- enforces platform/session gates
- enqueues advisory `message_only` prewarm
- forwards passive identity to `player_turn`
- never accepts external candidate, internal candidate, delta, proposal, or
  commit approval on platform act

## Trace And Eval

Future trace should be additive and versioned, for example `intent_trace_v1`.

Minimum sections:

```json
{
  "trace_version": "intent_trace_v1",
  "request": {},
  "preparation": {},
  "preflight": {},
  "internal_review": {},
  "arbitration": {},
  "binding": {},
  "selection": {},
  "preview": {},
  "validation": {},
  "save_boundary": {}
}
```

Eval should promote these to first-class metrics:

- `route_correct`
- `save_boundary_ok`
- `silent_wrong_route`
- `silent_wrong_save`
- `trace_complete`
- `preflight_provenance_ok`
- `unexpected_commit_rate`
- `query_pending_action_rate`
- `player_surface_delta_leak_rate`
- `latency_p95_ms`
- `ai_lift`
- `tool_misuse_rate`

Release blocker rates:

```text
silent_wrong_route_rate = 0
silent_wrong_save_rate = 0
unexpected_commit_rate = 0
query_pending_action_rate = 0
preflight_bad_provenance_rate = 0
player_surface_delta_leak_rate = 0
```

## Implementation Roadmap

### Phase A: Candidate Preparation

This is the current near-term work.

1. Add characterization tests.
2. Extract pure `prepare_intent_candidates()` inside `intent_router.py`.
3. Keep `route_intent(...)` public signature unchanged.
4. Do not call AI, consume preflight, arbitrate, bind, preview, validate,
   create pending action, or commit from preparation.

### Phase B: Preflight Reuse

1. Make `GMRuntime.preflight_intent()` reuse preparation.
2. Keep preflight cache state machine in `preflight_cache.py`.
3. Keep `message_only` external isolation.
4. Prove live route and preflight use equivalent rules candidates.

### Phase C: Internal Bundling

Split into reviewable pieces:

1. Runtime internal bundling.
2. ContextBuilder bundling.
3. MCP/CLI/SaveManager call-site bundling.

Public method signatures and profile gates stay stable.

### Phase D: Shadow Coordinator

Only after Phases A-C pass:

1. Introduce internal `TurnCoordinator` in shadow mode.
2. Run old and new orchestration side by side in tests/eval.
3. Require old/new selected outcome and save intent equivalence.
4. Do not enable as main path until silent wrong route/save metrics are zero.

### Phase E: Optional Package Split

Only after preparation and preflight reuse are stable:

```text
rpg_engine/intent/
  __init__.py
  config.py
  preparation.py
```

Do not add `coordinator.py` until the shadow `TurnCoordinator` boundary is
proven. The first package split should move stable boundaries only.

### Phase F: Target Tool Protocol

Future target:

```text
plan_turn -> validate_proposal -> commit_proposal
```

This is not a replacement for player confirmation. It is the cleaned-up internal
and trusted-tool protocol that can eventually reduce transitional
`preview_from_text -> validate_delta -> commit_turn` usage.

## Tests And Gates

Minimum staged commands:

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py \
  -k "intent_ai or intent_router or external_intent_candidate or semantic_suggestion or gold_set"

python3 -m pytest -q tests/test_preflight_cache.py tests/test_runtime.py tests/test_mcp_adapter.py \
  -k "preflight"

python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or external_candidate"

python3 -m pytest -q tests/test_platform_prewarm.py tests/test_platform_ai_simulation.py
```

Before a true coordinator is enabled:

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py tests/test_platform_prewarm.py tests/test_save_manager.py

python3 -m pytest -q tests/test_eval_suite.py

python3 -m rpg_engine eval run --format json
```

Real-model canary should remain observational until the local deterministic
suite proves old/new route and save equivalence.

## Rollback

- Keep old `route_intent` facade until the new path is proven.
- Keep old preflight consume behavior until reuse tests pass.
- New trace fields must be additive; breaking trace changes require version
  bump.
- Coordinator must be flaggable or shadow-only during first rollout.
- On silent wrong route/save, preflight provenance mismatch, player surface
  delta leak, canary helper failure spike, or p95 latency regression over 20%,
  disable the coordinator path and revert only the current phase.

## Non-Goals

- Do not make coordinator a public player tool.
- Do not move resolver, validation, commit, or projection rules into
  coordinator.
- Do not make AI consensus a save authority.
- Do not make preflight a permission or proposal cache.
- Do not make `composite` directly saveable.
- Do not use this design as a reason to move files before behavior is protected.

## Final Position

The coordinator should make the engine easier to reason about by making the
turn stages explicit. It should not make the engine more powerful by giving a
new object more authority.

The safe direction is:

```text
prepare candidates first
reuse preparation in preflight
bundle parameters internally
shadow a thin coordinator
only then consider target coordinator APIs
```
