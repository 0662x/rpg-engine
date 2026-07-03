# Intent Coordinator Team Review

Status: **PROPOSED：六角色架构评审结论，尚未实施代码**

Date: 2026-07-03

This document records the six-role architecture review for consolidating the AI
intent orchestration path. It complements
`docs/architecture/intent-coordinator-refactor-plan.md`: this file records the
review discussion and final design amendments; the refactor plan remains the
step-by-step implementation checklist.

## Review Method

Six read-only specialist reviews were performed:

| Role | Focus |
| --- | --- |
| Engine Architect | Kernel layering, Runtime/SaveManager/IntentRouter ownership, minimal refactor path. |
| AI Intent Safety Lead | Trust boundary, external/internal/rules/preflight semantics, binder and arbiter safety. |
| Gameplay / GM Flow Designer | Player turn experience, clarification, query/action/confirm behavior, gameplay fact safety. |
| Platform / MCP Integration Lead | MCP/CLI/platform entry points, profile gates, sidecar and prewarm integration. |
| QA / Regression Lead | Test coverage, characterization tests, staged verification commands. |
| Repo Maintainer / Release Manager | Commit slicing, docs policy, rollback, release gates. |

The first round mapped the real call chain and role-specific risks. The second
round reviewed the shared proposal and asked each role to challenge it. No
runtime code was changed during the review.

## Decision

Adopt the **medium, preparation-first refactor**:

1. Do not move files or create a large new `rpg_engine/intent/` package first.
2. Do not rewrite `AIIntentRouter`, arbiter, binder, risk policy, preflight
   cache, resolver, validation, commit, MCP profile gates, or platform gates.
3. First extract a pure candidate preparation helper near `rpg_engine.intent_router`.
4. Make live routing and preflight production reuse the same candidate
   preparation.
5. Only after that, bundle repeated internal parameters in smaller call-site
   phases.

The review explicitly rejected an aggressive rewrite. The current behavior is
too security-sensitive to move router, preflight, platform, and commit code at
the same time.

## Actual Call Chains

### Standard Player Turn

```text
MCP / CLI / Platform
  -> SaveManager.player_turn()
  -> GMRuntime.act()
  -> GMRuntime.preview_from_text()
  -> route_intent()
  -> AIIntentRouter.route_candidates()
  -> arbiter / binder
  -> GMRuntime.preview_intent()
  -> query result or action resolver preview
  -> SaveManager writes pending action or clarification only
  -> player_confirm(session_id)
  -> GMRuntime.commit_turn()
  -> validation pipeline
  -> commit service
  -> save delta / projections
```

Important current owners:

| Step | Owner |
| --- | --- |
| Player-safe entry and pending session | `rpg_engine/save_manager.py::SaveManager.player_turn` |
| Natural-language preview facade | `rpg_engine/runtime.py::GMRuntime.preview_from_text` |
| Live route contract | `rpg_engine/intent_router.py::route_intent` |
| AI review, preflight consumption, arbitration | `rpg_engine/ai_intent/router.py::AIIntentRouter.route_candidates` |
| Action preview | `rpg_engine/runtime.py::GMRuntime.preview_action` |
| Confirmation and commit | `SaveManager.player_confirm` -> `GMRuntime.commit_turn` |

### Advisory Preflight

```text
intent_preflight / platform prewarm
  -> GMRuntime.preflight_intent()
  -> normalize text and passive identity
  -> build rules candidate
  -> create pending intent_preflight_cache row
  -> collect internal intent review
  -> mark ready or failed
  -> later live player_turn consumes cache through AIIntentRouter
  -> arbiter / binder / preview / validation / confirmation still run
```

Preflight is not an authority. A cache hit only replaces a live internal review
call. It must not skip arbitration, binding, resolver preview, validation,
pending action, or confirmation.

## Role Findings

### Engine Architect

The current authority boundary is mostly correct. `SaveManager` owns player
session state, `Runtime` owns preview/commit facade behavior, `route_intent()`
owns the route contract, and `AIIntentRouter` owns AI candidate arbitration.

The clear duplication is candidate preparation: live route and preflight
production both normalize external input, build a legacy rule route, and build a
rules candidate. This is the first safe extraction target.

The first extraction must be pure: no AI call, no preflight consumption, no
commit, and no side effects beyond reading the DB for existing rule inference.

### AI Intent Safety Lead

The central safety rule is: do not flatten trust boundaries.

External AI remains low trust. Internal review is schema-validated but still
cannot preview or commit. Rules candidates are deterministic fallback/risk
inputs. Preflight is an advisory cache. Binder and arbiter remain separate
security checkpoints.

The review added a blocker requirement: `message_only` preflight must continue
to strip external candidate identity and pass `None` external candidate into
the internal helper, while live route may later receive a fresh external
candidate for arbitration.

### Gameplay / GM Flow Designer

The coordinator must not become a gameplay router or resolver. It should not
know gathering output, travel duration, combat hit logic, relationship changes,
hidden discovery, dice/random outcome, or delta construction.

Player-visible state-machine behavior must remain unchanged:

- `player_turn` can ask clarification, return read-only query text, or create a
  pending action.
- `player_turn` must not commit facts.
- `player_confirm(session_id)` is still required for writes.
- query remains read-only and creates no pending action.
- maintenance, forced save, hidden-info attempts, bad JSON/delta instructions,
  and composite plan shortcuts must stay blocked or clarified.

### Platform / MCP Integration Lead

MCP, CLI, and platform entry points must stay thin and permission-aware.

Do not expose an `IntentCoordinator` as a new MCP/CLI/platform tool. External
surfaces continue to call `SaveManager`, `GMRuntime`, or `PlatformSidecar`
facades.

Passive identity must remain passive:

- `preflight_id`
- `message_id`
- `platform`
- `session_key`
- `source_user_text_hash`
- `preflight_pending_wait_ms`

These fields are cache lookup identity, not permission or model config. They
must not be interpreted by adapters as authority.

### QA / Regression Lead

The main gap in the original plan was test order. Characterization tests should
be added before or with each refactor phase, so the old behavior is locked
before the code is reorganized.

The key tests must compare more than final output:

- normalized text
- explicit mode/submode trace
- legacy route trace
- rules candidate dict
- normalized external candidate
- `ActionIntent` player-visible fields
- preflight identity behavior
- proposal provenance behavior

### Repo Maintainer / Release Manager

Each phase should be separately reviewable and revertible. Phase 3 must be
split into smaller call-site phases. Docs should not churn specs when behavior
does not change.

Recommended branch/commit shape:

1. `p1-candidate-prep`
2. `p2-preflight-reuse`
3. `p3a-runtime-bundle`
4. `p3b-context-bundle`
5. `p3c-mcp-cli-callsite-bundle`
6. optional later `p5-intent-package`

The README `unittest` versus `pytest` inconsistency should be fixed separately,
not inside the intent refactor.

## Final Architecture Target

### Layers

```text
Adapters
  MCP / CLI / PlatformSidecar
  - profile gates
  - root/path/session gates
  - passive identity forwarding
  - no intent authority

SaveManager
  - active save registry
  - pending action / pending clarification
  - player_turn response shaping
  - player_confirm session gate

Runtime
  - preview/query/validate/commit facade
  - action resolver preview
  - validation pipeline and commit service calls

Intent preparation
  - normalize player text
  - normalize external candidate
  - build legacy rule route
  - build rules candidate
  - no AI call, no preflight consume, no preview, no commit

AIIntentRouter
  - optional preflight consumption
  - internal review collection
  - arbiter
  - binder
  - selected route outcome and trace

Domain / Commit
  - action contracts
  - resolver plans and delta drafts
  - validation pipeline
  - commit service
  - projection dirty marking
```

### Phase 1 Naming

The first helper should not be framed as an authority. Prefer concrete names:

- `prepare_intent_candidates()`
- `PreparedIntentCandidates`
- `IntentAIConfig`
- `IntentRequestMeta`

Avoid naming Phase 1 as an all-powerful `IntentCoordinator`. The code may later
grow into a coordinator package, but Phase 1 is candidate preparation only.

### Typed Inputs

`IntentAIConfig` is model/helper configuration only:

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
```

`IntentRequestMeta` is passive request identity only:

```python
@dataclass(frozen=True)
class IntentRequestMeta:
    preflight_id: str
    message_id: str
    platform: str
    session_key: str
    source_user_text_hash: str
    preflight_pending_wait_ms: int
```

External candidate input should stay visibly low-trust. The implementation can
keep it adjacent to request meta, but it must not be confused with passive
identity or authority.

`PreparedIntentCandidates` must not hide the `message_only` distinction behind
one ambiguous nullable external field. It should either expose separate helpers
or explicit fields:

```python
@dataclass(frozen=True)
class PreparedIntentCandidates:
    text: str
    explicit_mode: str | None
    explicit_submode: str | None
    legacy_route: LegacyRuleRoute
    rules_candidate: IntentCandidate
    external_for_live_route: IntentCandidate | None
```

For preflight production, the caller must explicitly derive:

```python
external_for_internal_review = (
    None
    if preflight_identity_profile == "message_only"
    else prepared.external_for_live_route
)
```

That line should be easy to audit.

### Later Safety Types

Do not force all of these into Phase 1. They are good later hardening targets:

- `ExternalCandidateInput`
- `RulesCandidate`
- `InternalReviewCandidate`
- `PreflightReceipt`
- `CandidateBoundIdentity`
- `MessageOnlyIdentity`
- `ArbitrationInputBundle`
- `FallbackEligibility`
- `IntentContextProvenance`

## Amended Implementation Roadmap

### Phase 0: Documentation And Baseline

Status: current phase.

Tasks:

- Keep this team review and the refactor plan in `docs/architecture`.
- Keep runtime code unchanged.
- Treat the latest `main` as the behavior baseline.

### Phase 1a: Characterize Candidate Preparation

Add tests before or in the same commit as the extraction.

Assertions:

- same normalized text
- same explicit mode/submode trace
- same `legacy_rule_route.trace()`
- same `legacy_rule_route.outcome.final_trace()`
- same `rules_candidate.to_dict()`
- same normalized external candidate
- same `ActionIntent` player-visible fields:
  `mode`, `submode`, `action`, `kind`, `status`, `player_message`,
  `missing_required`, `needs_confirmation`, `repair_options`,
  `clarification`

Minimum command:

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py \
  -k "intent_ai or intent_router or external_intent_candidate or semantic_suggestion or gold_set"
```

### Phase 1b: Extract Pure Candidate Preparation

Scope:

- `rpg_engine/intent_router.py`
- focused tests only

Rules:

- `prepare_intent_candidates()` must not call AI.
- It must not consume preflight.
- It must not call arbiter or binder.
- It must not decide fast path.
- It must not preview, validate, create pending action, or commit.
- `route_intent(...)` public signature stays unchanged.

### Phase 2a: Characterize Preflight Reuse

Add tests that lock old preflight behavior:

- live route and preflight use equivalent rules candidate
- `candidate_bound` keeps external/rule identity behavior
- `message_only` stores empty external identity and helper receives
  `external_candidate is None`
- a later live route can still receive a fresh external candidate and consume a
  message-only preflight hit
- non-hit or invalid cached review does not create preflight proposal provenance

Minimum command:

```bash
python3 -m pytest -q tests/test_preflight_cache.py tests/test_runtime.py tests/test_mcp_adapter.py -k "preflight"
```

### Phase 2b: Reuse Preparation In `GMRuntime.preflight_intent`

Scope:

- `rpg_engine/runtime.py::GMRuntime.preflight_intent`
- focused tests only

Rules:

- Keep cache state machine in `rpg_engine/preflight_cache.py`.
- Keep `GMRuntime.preflight_intent()` explicit mode/submode behavior unchanged.
- Keep pending/ready/failed transitions unchanged.
- Keep commits in the same places.
- Keep helper audit unchanged.
- Keep `message_only` external isolation as a blocker requirement.

### Phase 3a: Runtime Internal Bundling

Scope:

- `rpg_engine/runtime.py`
- focused runtime tests

Goal:

- internally pass `IntentAIConfig` and passive request metadata without changing
  public Runtime signatures or returned dicts.

Minimum command:

```bash
python3 -m pytest -q tests/test_runtime.py -k "start_turn or preview_from_text or preflight or intent_ai"
```

### Phase 3b: ContextBuilder Bundling

Scope:

- `rpg_engine/context_builder.py`
- focused runtime/context tests

Rules:

- `start_turn()` behavior must remain stable.
- `semantic_suggestion` remains trace-only unless existing code already uses it
  otherwise.
- `start_turn()` and `preview_from_text()` preflight consumption timing must be
  explicit. Do not accidentally consume a single-use preflight in a diagnostic
  path when the normal player route is expected to use it.

### Phase 3c: MCP / CLI / SaveManager Call-Site Bundling

Scope:

- internal call-site cleanup only
- public tool names and argument names unchanged
- profile gates unchanged
- error priority unchanged

Minimum commands:

```bash
python3 -m pytest -q tests/test_mcp_adapter.py \
  -k "player_profile or player_turn or player_act or intent_preflight or external_candidate"

python3 -m pytest -q tests/test_save_manager.py \
  -k "player_turn or player_act or standard_entry or external_candidate"
```

### Phase 4: Platform Verification Gate

Scope:

- verification first
- no platform behavior change unless a preceding phase exposes a bug

Minimum command:

```bash
python3 -m pytest -q tests/test_platform_prewarm.py tests/test_platform_ai_simulation.py
```

Blockers:

- platform act still uses binding active save
- platform still forwards `message_id`, `platform`, `session_key`, and
  `hash_text(message.text)`
- prewarm miss/timeout still degrades to normal player turn
- platform does not accept external candidate, delta, or proposal on player act

### Phase 5: Optional Package Split

Only after Phases 1 to 4 are passing and reviewed.

Possible layout:

```text
rpg_engine/intent/
  __init__.py
  preparation.py
  config.py
  coordinator.py
```

Do not start here.

## Additional Regression Requirements

### Trust Boundary Tests

Keep or add tests for:

- external schema error still rejects at the route boundary
- external candidate never directly overrides final route
- internal unavailable: `rest`/`travel` may fallback when currently allowed
- internal unavailable: `social`, `craft`, `gather`, `random_table`, `combat`,
  and composite remain denied/clarified where currently required
- hidden info, forced save, maintenance request remain blocked or clarified
- binder still rejects hallucinated, hidden, ambiguous, or unsupported slots

### Player State-Machine Tests

Keep or add tests for:

- clarification then repeated original text is still rejected
- fresh clarification answer clears or replaces pending clarification according
  to existing behavior
- query does not create pending action
- ready action replaces old pending action
- old `session_id` cannot confirm after a new pending action is created
- wrong save/platform/session confirmation is rejected
- composite plan does not create a `TurnProposal`

### Platform / MCP Tests

Keep or add tests for:

- player profile cannot use hidden view, low-level tools, maintenance mode, or
  per-call AI override
- message-only preflight can be consumed later without binding external
  candidate into cache identity
- platform prewarm miss, queue full, timeout, failed, and expired cases degrade
  to normal live processing or existing fallback behavior

## Documentation Policy

Behavior-preserving refactors should update only architecture/status docs and
test evidence.

Update specs only when public behavior changes:

- MCP or CLI public contract
- profile gate semantics
- preflight identity semantics
- player confirmation semantics
- AI trust boundary

Do not mix unrelated documentation cleanup, such as README testing-command
alignment, into an intent refactor commit.

## Release Gates

Before any implementation phase is merged:

1. The phase has characterization tests or focused regression tests.
2. The phase has a clear file boundary.
3. The phase can be reverted independently.
4. The commit or PR records the exact test command output.

Before final merge of the full refactor:

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py tests/test_save_manager.py

python3 -m pytest -q tests/test_current_native_*.py

python3 -m pytest -q
```

## Final Consensus

The six-role review supports the refactor only under these conditions:

1. Start with candidate preparation, not a broad coordinator rewrite.
2. Keep preparation pure and visibly non-authoritative.
3. Protect `message_only` external isolation as a blocker.
4. Add characterization tests before relying on the refactor.
5. Split Phase 3 into Runtime, ContextBuilder, and adapter call-site work.
6. Keep all player, platform, MCP, preflight, binder, resolver, validation, and
   commit authority boundaries unchanged.

This gives the project a maintainable path to reduce scattered AI intent code
without making the engine less safe or less predictable.
