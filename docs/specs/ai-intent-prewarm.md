# AI Intent And Prewarm Authority

Date: 2026-07-03

This document is the long-term authority for rpg-engine AI intent recognition, internal AI review, advisory preflight, and lightweight platform prewarm. Historical discussion lives in `reports/2026-07-02`; platform 3B implementation notes live in `reports/2026-07-03`.

## Purpose

The engine should feel fast while keeping save authority inside the kernel.

The design goal is not "AI directly plays the game". The design goal is:

1. External AI can understand the player's natural language and suggest an intent.
2. Internal AI reviews with the external candidate visible but non-authoritative.
3. Deterministic kernel code binds, validates, previews, and commits only through existing save guards.
4. Platform prewarm may compute internal review earlier, but cannot change permission or confirmation rules.

## Execution Chain

```text
player text
  -> optional external AI candidate
  -> deterministic rule candidate
  -> internal AI review, live or from advisory preflight cache
  -> arbiter
  -> binder
  -> action resolver / preview
  -> validation
  -> player_confirm or low-level approved commit
```

No AI candidate is allowed to skip binder, resolver, validation, pending action, or commit guard.

## Single Management Rule

The AI intent layer is an engine-owned subsystem, not a platform-owned or
external-AI-owned subsystem. External clients, MCP tools, CLI commands, and
platform sidecars may supply inputs, configuration, passive identifiers, or
advisory cache requests. They must not become alternate intent authorities.

New code should keep this split:

- Player-facing natural language enters `player_turn` or the low-level
  `preview_from_text` path.
- Final `mode/submode/action/options` decisions flow through
  `rpg_engine.intent_router.route_intent()` and `rpg_engine.ai_intent`.
- Advisory preflight may only cache internal review output. It must still be
  consumed through arbitration, binding, preview, validation, and confirmation.
- Platform code may enqueue prewarm and forward message identity. It must not
  decide final game intent or write game facts.
- If a future refactor adds an intent coordinator object, CLI, MCP,
  `SaveManager`, `GMRuntime`, and platform sidecar should call that coordinator
  instead of duplicating rule-candidate, internal-review, or preflight lifecycle
  code.

## Internal Review Model

The intended model is visible-external independent review, not blind review.

The internal AI may receive the player's original text, player-visible engine context, the external candidate, and the deterministic rule candidate in the same prompt. The external candidate is low-trust input, not the answer. "Independent" means the internal AI must re-derive its own candidate from the player text and visible context, then explicitly report agreement, disagreements, and external candidate quality. The arbiter compares external/internal/rules after that review; it must not treat the external candidate as player confirmation, preview approval, or save approval.

## Trust Boundaries

| Component | Authority |
| --- | --- |
| External AI | May provide `external_intent_candidate` on the standard `player_turn` route or trusted low-level routes. It is never final authority. |
| Internal AI | Reviews the player's text and any external candidate. It is the engine-side semantic judge, but still cannot commit. |
| Deterministic rules | Provide fallback candidates, risk gates, binding, validation, and safety checks. Rules are no longer the natural-language master router. |
| Arbiter | Decides whether candidates agree enough to preview, clarify, fallback, or block. |
| Binder/resolver/validation | Convert candidate slots into engine objects and decide whether preview/save is possible. |
| Platform sidecar | Only normalizes platform messages, gates sessions, enqueues prewarm, and forwards passive identifiers. |

`player_turn` is the standard player-safe natural-language route and may receive a low-trust `external_intent_candidate` from the AI/GM layer. `player_act` remains a compatibility wrapper: it may consume passive preflight identifiers, but it must not accept per-call `external_intent_candidate`, internal candidate injection, delta injection, proposal injection, or AI backend/model override from a player-facing client.

## Current Strategy

### External + Internal Consensus

If external AI and internal AI agree on mode/action/kind, and binding has no meaningful disagreement, the arbiter accepts the internal candidate as `ai_consensus`.

If they disagree, the engine returns structured clarification.

### Internal + Rules Fast Path

When there is no external AI candidate, the engine may still accept a low-risk internal candidate if deterministic rules agree.

Current accepted source: `ai_single_source_internal_fast`.

Required conditions:

- Internal candidate exists.
- Rule candidate exists.
- Both are `kind=single`.
- Modes match.
- For actions, actions match.
- Internal candidate has no safety flags, missing slots, or explicit confirmation needs.
- Binder succeeds for the internal candidate.
- Binder succeeds for the rule candidate.
- Bound slots do not disagree.
- Action risk is `yellow_fast`, or mode is read-only `query`.

This path only reaches preview/pending confirmation. It still does not commit state.

Current `yellow_fast` actions:

| Action | Reason |
| --- | --- |
| `routine` | Low-risk daily maintenance, inventory checks, non-creative housekeeping. |
| `rest` | Existing resolver constrains time/rest effects. |
| `travel` | Destination must bind to a known location. |
| `explore` | Target/approach still go through preview and validation. |

Current consensus-only actions:

| Action | Reason |
| --- | --- |
| `gather` | Can create/consume resources or reveal facts. |
| `craft` | Can create items/projects and consume materials. |
| `social` | Can change relationships, rumors, trades, or faction facts. |
| `random_table` | Must remain auditable and table-bound. |

Strict actions and modes:

| Type | Policy |
| --- | --- |
| `combat` | High risk; requires stricter review and missing-slot handling. |
| `maintenance` | Not a normal player action; requires trusted tooling. |
| `composite` | Requires step confirmation; no fast path. |
| safety flags | `prompt_injection`, `out_of_world`, `forced_save`, `hidden_info`, `maintenance_request`, `unsafe_command` block or clarify. |

### Internal Single Source Without Rules

If only internal AI is available and there is no external candidate and no agreeing rule candidate, the arbiter keeps the old safe behavior:

```text
status=clarify
source=ai_single_source_internal
```

### Rules Fallback

When internal AI is off or unavailable, deterministic rules may fallback only through `assess_rules_fallback`. This is intended for low-risk, bound, complete candidates and read-only queries. It is not a general replacement for AI intent recognition.

## Preflight Identity Profiles

`candidate_bound`:

- Used when a trusted/developer caller has an external candidate at preflight time.
- Later consumption is tied to `preflight_id` and identity hashes.

`message_only`:

- Used by platform prewarm when the raw platform message arrives before external AI has decided anything.
- Must include `platform`, `session_key`, `message_id`, and `source_user_text_hash` for reliable lookup.
- Does not bind an external candidate.
- May be consumed by player-safe `player_turn`, compatibility `player_act`, `start_turn`, `preview_from_text`, or low-level `act`.

Both profiles are advisory. A cache hit only replaces a live internal AI call; it does not replace arbitration or confirmation.

## Platform Prewarm

The platform path must stay lightweight:

```text
MessageEvent
  -> thin adapter / PlatformSidecar
  -> PlatformMessage
  -> GameSessionBinding gate
  -> bounded queue
  -> PrewarmWorker
  -> GMRuntime.preflight_intent(..., preflight_identity_profile="message_only")
```

Failure policy:

- Feature disabled: drop prewarm.
- Missing identity tuple: drop prewarm.
- Queue full: drop prewarm.
- AI timeout/error: drop prewarm.
- Late result after caller already bypassed: mark `late_ready_unused`.

All of these degrade to normal live processing.

## Direct Internal AI Provider

DeepSeek direct calls follow the official OpenAI-compatible chat format:

- Provider/model defaults: `deepseek` + `deepseek-v4-flash`.
- Config may pass either the official SDK-style base URL `https://api.deepseek.com` or the full HTTP endpoint `https://api.deepseek.com/chat/completions`.
- The provider normalizes configured base URLs into `/chat/completions` endpoints before sending HTTP.
- Request format is `POST` JSON with `Authorization: Bearer <key>`, `model`, `messages`, `temperature=0`, and `response_format={"type":"json_object"}`.
- The system prompt explicitly asks for exactly one JSON object, because DeepSeek JSON Output still requires an instruction to output JSON.
- For `deepseek-v4-flash`, internal helper calls set `thinking={"type":"disabled"}` to keep intent recognition lightweight and reduce latency.
- API keys must come from environment variables or the local env file; do not hard-code keys in source.

## Module Boundaries

| Module | Responsibility |
| --- | --- |
| `rpg_engine.ai.provider` | Lightweight helper provider abstraction and direct model calls. |
| `rpg_engine.ai_intent` | Normalization, internal review prompt, arbiter, binder, route adoption, risk policy. |
| `rpg_engine.preflight_cache` | Advisory cache state machine and identity lookup. |
| `rpg_engine.platform_prewarm` | Binding store, prewarm queue, worker, metrics, drop reasons. |
| `rpg_engine.platform_sidecar` | Thin platform entry facade and formal act/confirm gate. |
| `rpg_engine.save_manager` | Player-safe pending action and confirmation path. |
| `rpg_engine.runtime` | Runtime orchestration; should not absorb new AI policy if it can live in a smaller module. |

## Maintainability Guardrails

The AI subsystem is modular enough to maintain, but several orchestration files are already large:

| File | Risk |
| --- | --- |
| `rpg_engine/runtime.py` | Runtime orchestration is broad; avoid adding new AI policy here. |
| `rpg_engine/preflight_cache.py` | Cache state machine is important and should stay well-tested. |
| `rpg_engine/platform_prewarm.py` | Queue/worker/binding concerns may eventually split. |
| `rpg_engine/platform_sidecar.py` | Entry facade should stay thin; do not turn it into a rule engine. |
| `rpg_engine/ai/provider.py` | Provider abstraction is shared by intent and audit helpers. |
| `rpg_engine/ai/state_audit.py` | Commit safety helper; do not couple it to platform prewarm. |

Before adding new AI behavior, prefer these locations:

- Arbiter policy -> `rpg_engine/ai_intent/arbiter.py` and tests.
- Risk class -> `rpg_engine/ai_intent/risk.py` and eval gold sets.
- Platform prewarm drop/metrics -> `rpg_engine/platform_prewarm.py`.
- Platform player entry -> `rpg_engine/platform_sidecar.py`.
- Player-safe API shape -> `rpg_engine/save_manager.py`, MCP/CLI specs, and tests.

## Known Debts

- `PlatformSidecar.player_act_from_message()` is a compatibility-named platform action facade that internally uses `player_turn` semantics. It can enqueue prewarm during act if the adapter did not already call `handle_message_event`; this is useful for diagnostics but should be watched in real canary to avoid double AI calls.
- `metrics_snapshot()` includes cache metrics and should not be called on the hottest user-visible path in a high-volume deployment without sampling or caching.
- Metrics duration arrays are in-memory and unbounded; long-running sidecar should eventually use rolling windows.
- `GameSessionBindingStore` is JSON-based and lightweight; if multiple sidecar processes write the same workspace, add a process lock or move to SQLite.
- `preflight_cache` stores raw `session_key` and `user_text` for compatibility. Binding store already hashes session/user ids; cache retention/redaction should be hardened later.
- Pending player action is still a single workspace slot. This is acceptable for current single-player design, but multi-session support would need scoped pending stores.

## Current Verification

The current implementation is covered by focused AI intent tests, MCP player-safe tests, platform sidecar tests, runtime tests, and deterministic eval suites. The eval gold set now treats low-risk internal+rules agreement as `ai_single_source_internal_fast` rather than a required clarification.
