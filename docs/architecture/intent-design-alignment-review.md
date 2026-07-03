# AI Intent Design Alignment Review

Status: **PROPOSED：历史设计目标对照评审，尚未实施代码**

Date: 2026-07-03

This document answers one narrow question:

> Does the proposed intent orchestration refactor still follow the older AI
> intent design goals?

Short answer: **partial alignment, conditional pass**. The refactor is safe only
when it is treated as an **Intent Candidate Preparation Refactor**, not as the
full future `IntentCoordinator` or `plan_turn` implementation.

The future coordinator target is recorded separately in
`docs/architecture/future-turn-coordinator-design.md`.

## Sources Reviewed

The review searched current specs, architecture docs, prompts, and older
analysis reports related to AI intent design:

| Source | Why it matters |
| --- | --- |
| `docs/specs/standard-intent-chain.md` | Current standard player intent chain and trust boundary. |
| `docs/specs/ai-intent-prewarm.md` | Advisory preflight, platform prewarm, and authority rules. |
| `docs/architecture/turn-flow-architecture.md` | Long-term turn flow and player workflow goals. |
| `reports/2026-07-01-analysis/11-ai-consensus-intent-design.md` | Original AI consensus design: external/internal/rules/binder/resolver split. |
| `reports/2026-07-01-analysis/12-ai-intent-refactor-plan.md` | Earlier refactor plan and known gaps around `semantic_suggestion`. |
| `reports/2026-07-02/01-lightweight-internal-ai-and-parallel-consensus.md` | Implemented lightweight internal AI and preflight cache boundaries. |
| `reports/2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md` | Platform prewarm scope and non-authority rule. |
| `reports/2026-07-03/05-external-ai-skill-review.md` | External AI client workflow and tool-surface expectations. |
| `docs/prompts/ai-client-prompt.md` | What an external AI GM is told to do. |

## Original Design Goals

The older AI intent design was not just "put intent code in one place". Its
main goals were:

1. Natural-language player input should not be judged primarily by keyword
   rules. Legacy rules should become safety guard, fallback, debug signal, or
   candidate input.
2. External AI may provide a low-trust `ExternalIntentCandidate`, but it never
   acts, queries, advances time, previews delta, confirms, or saves.
3. Internal AI performs visible-external independent review: it may see the
   external candidate, but it must independently re-evaluate player text and
   player-visible context.
4. The final `ActionIntent`, entity ids, slot binding, legality, delta, and save
   authority remain kernel-owned.
5. AI consensus may advance a turn to preview or clarification. It must not
   commit facts.
6. The default player entry is `player_turn`; `player_confirm` is the save
   boundary. `preview_from_text` is a lower-level natural-language preview
   primitive and compatibility facade, not the default player-facing workflow.
7. Preflight/prewarm is advisory cache only. A hit may replace a live internal
   AI review call, but it must not skip arbiter, binder, resolver, validation,
   pending action, or confirmation.
8. The long-term target includes a higher-level flow like
   `plan_turn -> validate_proposal -> commit_proposal`, but that is future work.
9. `semantic_suggestion` is too weak to be a final intent. It should stay
   trace-only or eventually be retired/derived from proper `IntentCandidate`.
10. The intent/action/query/slot manifest should become the single source of
    truth for available player-visible capabilities.
11. Trace and eval records must make misroutes diagnosable across external,
    internal, rules, consensus, binder, final intent, preview, and commit.

## Expert Review Summary

The review was organized as an AI game development panel with six roles:

| Role | Verdict |
| --- | --- |
| AI Intent Design Historian | Mostly aligned, but the plan must not fossilize legacy rules as the real judge. |
| AI Safety / Trust Boundary Lead | Conditional pass. `IntentRequestMeta` must be passive identity only. |
| Gameplay / Player Experience Lead | Conditional pass. `player_turn` and `player_confirm` must remain the mental model. |
| Platform / Prewarm Architect | Conditional pass. Platform prewarm remains disposable acceleration, not runtime authority. |
| Refactor / QA Lead | Conditional pass. Start with side-effect-limited preparation and characterization tests. |
| Engine Architecture Lead | Conditional pass. Do not move resolver, binder, validation, commit, MCP, or platform gates in the first phase. |

Consensus:

The current refactor proposal is useful as **paving work**. It reduces repeated
candidate preparation between live routing and preflight production. It does not
complete the historical AI intent target by itself.

## Current Chain Being Protected

Standard player chain:

```text
player text / external candidate
  -> player_turn
  -> preview_from_text facade
  -> route_intent
  -> AIIntentRouter
  -> arbiter / binder
  -> preview / query result
  -> pending action or clarification
  -> player_confirm
  -> validation
  -> commit
```

Advisory preflight chain:

```text
platform or explicit preflight request
  -> preflight_intent
  -> internal review cache row
  -> later player_turn consumes review if identity matches
  -> arbiter / binder / preview / validation / confirmation still run
```

## Alignment Matrix

| Historical goal | Current refactor fit | Required adjustment |
| --- | --- | --- |
| External AI is low trust | Mostly aligned | Keep external candidate visibly separate from passive request metadata. |
| Internal AI independently reviews | Aligned if preparation stays side-effect-limited | `message_only` preflight must pass `external_for_internal_review = None`. |
| Kernel owns final intent and save | Aligned | Do not move binder, resolver, validation, pending action, or commit. |
| Rules stop being the main judge | Partial | `legacy_route` is a characterization baseline and rules candidate source, not the future authority model. |
| `player_turn` is the player entry | Aligned | Docs and prompts must keep `preview_from_text` marked low-level/transition. |
| `player_confirm` is save boundary | Aligned | No refactor phase may auto-confirm or commit. |
| Preflight is advisory only | Aligned if guarded | A hit only replaces live internal review, never downstream checks. |
| Future `plan_turn` exists | Not implemented | Do not describe this refactor as the final TurnCoordinator. |
| `semantic_suggestion` is weak | Needs follow-up | Keep trace-only; later retire or derive from `IntentCandidate`. |
| Manifest is source of truth | Needs follow-up | Do not add parallel action/query/slot contracts during this refactor. |
| Trace/eval explain misroutes | Needs stronger gate | Add eval/canary/trace acceptance before claiming quality improvement. |

## Required Amendments Before Code Work

These are blockers for implementation:

1. Rename the mental model to **Intent Candidate Preparation Refactor** for
   Phase 1. A full `IntentCoordinator` can be future work.
2. `IntentRequestMeta` must contain only passive request identity:
   `preflight_id`, `message_id`, `platform`, `session_key`,
   `source_user_text_hash`, and `preflight_pending_wait_ms`.
3. `IntentRequestMeta` must not contain external candidate, internal candidate,
   delta, proposal, permission, profile override, AI backend override, or save
   authority.
4. External candidate input must stay adjacent but separate, for example as
   `ExternalCandidateInput` or `external_candidate_input`.
5. Candidate preparation must be side-effect-limited: normalize text, normalize
   external candidate, build legacy route, build rules candidate, and read DB
   state only for existing rule inference. It must not call AI, consume
   preflight, arbitrate, bind, preview, validate, create pending action, or
   commit.
6. Preflight production must explicitly preserve the identity distinction:

```python
external_for_internal_review = (
    None
    if preflight_identity_profile == "message_only"
    else prepared.external_low_trust_candidate
)
```

7. A preflight hit may only replace the live internal AI review call. It must
   still flow through arbiter, binder, resolver preview, validation, pending
   action, and `player_confirm`.
8. `player_act` and platform act must not accept external candidate, delta,
   proposal, or per-call AI override.
9. `preview_from_text` must remain documented as a facade/low-level primitive.
   The standard external player workflow remains `player_turn -> player_confirm`.
10. Release gates must include characterization and trace/eval checks, not only
    "pytest still passes".

## What This Changes In The Refactor Plan

The original refactor plan had one unsafe shape:

```python
class IntentRequestMeta:
    external_intent_candidate: dict[str, Any] | None
    ...
```

That is wrong for the historical design. External candidate is low-trust input,
not passive identity. Putting it into `IntentRequestMeta` makes it too easy for
future code to treat it like cache identity or authority.

The corrected shape is:

```python
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
```

`PreparedIntentCandidates` may carry a normalized external candidate for the
live route, but the field should be named to preserve trust meaning:

```python
@dataclass(frozen=True)
class PreparedIntentCandidates:
    text: str
    explicit_mode: str | None
    explicit_submode: str | None
    legacy_route: LegacyRuleRoute
    rules_candidate: IntentCandidate
    external_low_trust_candidate: IntentCandidate | None
```

## Implementation Guidance

Before editing runtime code:

1. Add characterization tests around `route_intent` output and trace.
2. Add preflight identity tests for `candidate_bound` and `message_only`.
3. Verify default player profile still uses `player_turn` and `player_confirm`.
4. Verify low-level tools do not leak into player profile.

During Phase 1:

1. Extract only candidate preparation near `rpg_engine/intent_router.py`.
2. Keep `route_intent(...)` as the compatibility facade.
3. Keep `AIIntentRouter` behavior unchanged.
4. Keep `semantic_suggestion` trace-only.

During Phase 2:

1. Reuse the same candidate preparation in `GMRuntime.preflight_intent`.
2. Do not move the preflight cache state machine.
3. Preserve `message_only` external isolation.
4. Prove that cache hit still passes through arbiter, binder, preview,
   validation, pending action, and confirmation.

During later phases:

1. Bundle repeated parameters only inside call sites.
2. Keep public MCP, CLI, Runtime, SaveManager, and platform signatures stable
   unless a separate spec change explicitly approves otherwise.
3. Do not create a large `rpg_engine/intent/` package until the smaller
   preparation extraction is stable.

## Final Position

The proposed refactor should go forward only as a behavior-preserving cleanup
that makes future AI intent work easier to manage. It should not claim to solve
the full historical AI design target yet.

The historical target remains:

```text
AI helps understand player language.
The deterministic kernel owns facts, legality, preview, validation, and save.
```
