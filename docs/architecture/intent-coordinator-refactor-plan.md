# Intent Coordinator Refactor Plan

Status: **PROPOSED：仅为重构计划，尚未实施**

Date: 2026-07-03

This document records the safe refactor plan for consolidating AI intent
orchestration without changing player-facing behavior.

Historical AI intent design alignment is recorded in
`docs/architecture/intent-design-alignment-review.md`. That review clarifies
that Phase 1 is an **Intent Candidate Preparation Refactor**, not the full
future `IntentCoordinator` or `plan_turn` implementation.

The future internal coordinator target is recorded in
`docs/architecture/future-turn-coordinator-design.md`.

Six-role architecture review amendments are recorded in
`docs/architecture/intent-coordinator-team-review.md`. That review tightens this
plan with characterization tests, `message_only` preflight blockers, Phase 3
sub-phases, and release gates. When implementing, read the team review first.

## Purpose

The current AI intent chain mostly has the right authority boundary: external
AI can propose an intent, internal AI can review it, and the engine still owns
binding, preview, validation, confirmation, and commit.

The maintainability problem is not that AI intent is outside the engine. The
problem is that several orchestration details are repeated across runtime,
preflight, MCP, CLI, and platform entry surfaces. This makes future changes easy
to apply in one path but forget in another.

The goal of this refactor is therefore narrow:

1. Keep existing behavior.
2. Keep public CLI, MCP, Runtime, and SaveManager signatures stable at first.
3. Consolidate repeated candidate preparation and intent configuration handling.
4. Make preflight production reuse the same candidate preparation as live
   routing.
5. Preserve every trust boundary around external AI, preflight cache, platform
   sidecar, preview, validation, and commit.

This refactor is not allowed to turn legacy keyword/rule routing back into the
primary long-term natural-language judge. The legacy route is preserved as a
characterization baseline, deterministic rules candidate, fallback signal, and
debug trace while the AI consensus path remains the intended direction for open
player language.

## Current Chain

Standard player turn:

`GMRuntime.preview_from_text()` is a facade for natural-language preview. It
calls intent routing before any actual query/action preview is produced.

```text
MCP / CLI / Platform
  -> SaveManager.player_turn()
  -> GMRuntime.act()
  -> GMRuntime.preview_from_text()  # facade
  -> route_intent()
  -> AIIntentRouter.route_candidates()
  -> arbiter / binder
  -> preview_intent()
  -> action resolver / validation
  -> player_confirm()
  -> commit
```

Advisory preflight:

```text
intent_preflight / platform prewarm
  -> GMRuntime.preflight_intent()
  -> create pending intent_preflight_cache row
  -> collect internal intent review
  -> mark ready or failed
  -> later player_turn consumes cache through AIIntentRouter
  -> arbiter / binder / preview / validation / confirmation still run
```

Key source locations:

| Area | Current owner |
| --- | --- |
| Player-safe entry | `rpg_engine/save_manager.py::SaveManager.player_turn` |
| Natural-language preview facade; routes intent before previewing | `rpg_engine/runtime.py::GMRuntime.preview_from_text` |
| Live intent routing | `rpg_engine/intent_router.py::route_intent` |
| AI review, preflight consumption, arbitration | `rpg_engine/ai_intent/router.py::AIIntentRouter.route_candidates` |
| Preflight production | `rpg_engine/runtime.py::GMRuntime.preflight_intent` |
| Preflight state machine | `rpg_engine/preflight_cache.py` |
| Platform prewarm | `rpg_engine/platform_prewarm.py` |
| Platform act/confirm facade | `rpg_engine/platform_sidecar.py` |

## Problems To Fix

### Repeated Candidate Preparation

`route_intent()` and `GMRuntime.preflight_intent()` both prepare equivalent
inputs:

- normalize player text
- normalize optional external intent candidate
- build the deterministic legacy rule route
- convert that route into a rules intent candidate

This duplication is the first thing to remove.

### Parameter Flooding

The following values are passed through many layers as separate parameters:

- `intent_ai`
- `intent_backend`
- `intent_provider`
- `intent_model`
- `intent_timeout`
- `intent_base_url`
- `intent_api_key_env`
- `intent_fallback_backend`
- `external_intent_candidate`
- `preflight_id`
- `message_id`
- `platform`
- `session_key`
- `source_user_text_hash`
- `preflight_pending_wait_ms`

The public signatures should stay stable initially, but internal calls can use
typed bundles so the code has fewer places to forget a parameter.

### Split Preflight Lifecycle

Preflight production lives in `GMRuntime.preflight_intent()`, while preflight
consumption lives in `AIIntentRouter.route_candidates()`. This is acceptable for
now, but production should reuse the same candidate preparation as live routing.
Later, a small preflight orchestration wrapper can make production and
consumption easier to audit without moving the cache state machine.

## Non-Goals

Do not do these as part of the first refactor:

- Do not change AI arbitration policy.
- Do not rewrite `AIIntentRouter`.
- Do not move binder, resolver, validation, or commit authority.
- Do not let preflight cache become an intent authority.
- Do not change public MCP/CLI tool availability.
- Do not weaken MCP profile gates.
- Do not move platform session gating into intent code.
- Do not change save confirmation semantics.
- Do not fold `response_acceptance.py` into the normal player-turn path.
- Do not create a large new `rpg_engine/intent/` package until the thin
  coordinator has proven stable.

## Target Shape

The first target is a thin internal preparation layer near
`rpg_engine.intent_router`. It should be boring and mostly mechanical. It may
later support a real coordinator package, but Phase 1 is not that package.

Suggested additions:

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
    preflight_id: str
    message_id: str
    platform: str
    session_key: str
    source_user_text_hash: str
    preflight_pending_wait_ms: int


@dataclass(frozen=True)
class ExternalCandidateInput:
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class PreparedIntentCandidates:
    text: str
    explicit_mode: str | None
    explicit_submode: str | None
    legacy_route: LegacyRuleRoute
    rules_candidate: IntentCandidate
    external_for_live_route: IntentCandidate | None
```

`IntentRequestMeta` is passive identity only. It must not contain external
candidate, internal candidate, delta, proposal, permission, profile override, AI
backend override, or save authority. External candidate input should remain
adjacent but visibly low-trust and separate from passive request metadata.

Suggested helper functions:

```python
def make_intent_ai_config(...) -> IntentAIConfig:
    """Normalize and validate intent AI config once."""


def make_intent_request_meta(...) -> IntentRequestMeta:
    """Normalize passive preflight/request identity once."""


def prepare_intent_candidates(
    conn: sqlite3.Connection,
    user_text: str,
    *,
    mode: str = "auto",
    submode: str | None = None,
    meta: IntentRequestMeta,
    external_candidate_input: ExternalCandidateInput | None = None,
) -> PreparedIntentCandidates:
    """Normalize text, external candidate, legacy route, and rules candidate."""


def route_prepared_intent(
    campaign: Campaign,
    conn: sqlite3.Connection,
    prepared: PreparedIntentCandidates,
    *,
    ai_config: IntentAIConfig,
    semantic_suggestion: dict[str, Any] | None = None,
) -> ActionIntent:
    """Call AIIntentRouter and assemble the final ActionIntent."""
```

The existing `route_intent(...)` should remain as the compatibility facade. It
should convert old parameters into `IntentAIConfig` and `IntentRequestMeta`,
then call `prepare_intent_candidates()` and `route_prepared_intent()`.

## Step-By-Step Plan

### Phase 0: Baseline And Documentation

Status: completed for documentation, not for code.

Tasks:

1. Keep this plan in `docs/architecture`.
2. Confirm the worktree is clean.
3. Capture the current targeted test commands.

No runtime code changes in this phase.

### Phase 1: Extract Candidate Preparation

Scope:

- Edit only `rpg_engine/intent_router.py` and focused tests if needed.
- Add `IntentAIConfig`, `IntentRequestMeta`, and `PreparedIntentCandidates`.
- Add `prepare_intent_candidates()`.
- Make `route_intent(...)` use the new helper internally.
- Do not change the `route_intent(...)` public signature.
- Do not change `AIIntentRouter` behavior.

Acceptance criteria:

- Existing route results stay identical for normal runtime tests.
- Existing external candidate schema errors still surface the same way.
- Semantic suggestion remains trace-only and does not override final route.

Minimum verification:

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py \
  -k "intent_ai or intent_router or external_intent_candidate"
```

### Phase 2: Reuse Candidate Preparation In Preflight Production

Scope:

- Edit `rpg_engine/runtime.py` only where `GMRuntime.preflight_intent()` builds
  live rule/external candidates.
- Replace duplicated candidate preparation with `prepare_intent_candidates()`.
- Keep preflight cache creation, identity profile handling, pending/ready/failed
  transitions, helper audit, and commits exactly where they are.
- Keep `message_only` behavior: no external candidate is passed to the helper
  when the identity profile is `message_only`.

Acceptance criteria:

- Candidate-bound preflight still binds external/rule identity.
- Message-only preflight still strips external candidate identity.
- Hash mismatch still rejects.
- Cache hit still only replaces the live internal AI call.
- Cache hit still flows through arbitration, binding, preview, validation, and
  confirmation.

Minimum verification:

```bash
python3 -m pytest -q tests/test_preflight_cache.py tests/test_runtime.py tests/test_mcp_adapter.py -k "preflight"
```

### Phase 3: Bundle Internal Intent Parameters

Phase 3 must be split into smaller reviewable pieces:

- 3a: Runtime internal bundling.
- 3b: ContextBuilder bundling.
- 3c: MCP/CLI/SaveManager call-site bundling.

Do not combine these into one broad cross-surface refactor.

Scope:

- Keep public method signatures stable.
- Inside Runtime, ContextBuilder, and MCP adapter, convert intent settings into
  `IntentAIConfig` and `IntentRequestMeta` as early as possible.
- Reduce repeated normalization and request dict assembly where it can be done
  without changing public output.
- Keep external candidate input separate from passive `IntentRequestMeta`.
- Do not change MCP profile behavior.
- Do not change CLI argument names.

Acceptance criteria:

- `player_turn` still hides `delta_draft` and `turn_proposal`.
- `player_confirm` remains required for state commits.
- MCP player profile still cannot call low-level tools.
- Low-level developer surfaces still work.

Minimum verification:

```bash
python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py \
  -k "player_profile or player_turn or player_act or player_workflow or standard_entry or external_candidate"
```

### Phase 4: Platform Verification Only

Scope:

- Do not change platform behavior until Phases 1 to 3 are stable.
- Verify platform sidecar and prewarm still pass passive identifiers into
  `SaveManager.player_turn()`.
- Verify platform prewarm still produces only advisory `message_only` preflight.

Acceptance criteria:

- Platform prewarm does not drive a turn by itself.
- Platform act still calls `SaveManager.player_turn()`.
- Platform confirm still calls `SaveManager.player_confirm()`.
- Binding, gate, TTL, duplicate, bot/self, command, and chat checks remain
  outside intent routing.

Minimum verification:

```bash
python3 -m pytest -q tests/test_platform_prewarm.py tests/test_platform_ai_simulation.py
```

### Phase 5: Optional Package Split

Only consider this after Phases 1 to 4 pass and the code is stable.

Possible later layout:

```text
rpg_engine/intent/
  __init__.py
  coordinator.py
  config.py
  prepared.py
```

Do not start here. Moving files first creates import churn before the behavior
is protected by a smaller internal boundary.

## Safety Boundaries

These behaviors must remain unchanged:

| Boundary | Rule |
| --- | --- |
| External AI | May propose `external_intent_candidate`; never final authority. |
| Internal AI | Reviews intent; cannot preview, validate, confirm, or commit. |
| Preflight cache | Advisory internal review cache only; single-use and identity-bound. |
| `AIIntentRouter` | Owns candidate arbitration and preflight consumption. |
| Binder | Must still reject hidden, hallucinated, ambiguous, and unsafe slots. |
| Resolver | Must still build previews through action contracts. |
| Validation | Must still run before commit. |
| `SaveManager.player_turn` | May create pending action, must not save facts. |
| `player_confirm` | Still required to commit pending player action. |
| MCP profile gates | Player profile must not gain low-level tools. |
| Platform sidecar | May gate and forward passive identity, not decide final intent. |

## Regression Tests To Protect

Run this targeted suite before any merge:

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py tests/test_save_manager.py
```

Important behavior checks already covered by tests:

- external candidate schema rejection
- external candidate trace without route override
- AI consensus adoption
- external/internal mismatch clarification
- hidden info block
- rules fallback denial for consensus-only actions
- preflight cache single-use
- preflight context/hash/model/candidate mismatch rejection
- message-only preflight consumption without `preflight_id`
- pending preflight timeout and late-ready handling
- MCP `player_turn` hides delta/proposal
- `player_confirm` commits only pending approved action
- platform prewarm remains advisory

## Rollback Plan

Each phase should be a separate commit.

If a phase fails:

1. Revert only that phase commit.
2. Keep earlier passing phases.
3. Do not patch over a failing behavior by weakening tests.
4. Add one focused regression test before retrying if the failure exposed an
   uncovered boundary.

## Commit Plan

Recommended commit sequence:

1. `docs: record intent coordinator refactor plan`
2. `refactor: extract intent candidate preparation`
3. `refactor: reuse intent preparation for preflight`
4. `refactor: bundle internal intent request config`
5. Optional later: `refactor: move intent coordinator package`

The first implementation commit should be small enough to review by reading
only `rpg_engine/intent_router.py` and the focused test diff.
