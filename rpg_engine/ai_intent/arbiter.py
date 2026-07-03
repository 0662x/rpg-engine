from __future__ import annotations

import sqlite3
from typing import Any

from ..actions import ActionResolverRegistry
from .binder import bind_intent_candidate
from .normalization import normalize_intent_candidate
from .risk import ACTION_BASE_RISK, YELLOW_FAST
from .types import BoundIntent, ConsensusDecision, IntentCandidate


BLOCKER_SAFETY_FLAGS = {
    "prompt_injection",
    "out_of_world",
    "forced_save",
    "hidden_info",
    "maintenance_request",
    "unsafe_command",
}


def arbitrate_intent_candidates(
    conn: sqlite3.Connection,
    *,
    external_candidate: IntentCandidate | dict[str, Any] | None = None,
    internal_candidate: IntentCandidate | dict[str, Any] | None = None,
    rule_candidate: IntentCandidate | dict[str, Any] | None = None,
    internal_review_metadata: dict[str, Any] | None = None,
    registry: ActionResolverRegistry | None = None,
) -> ConsensusDecision:
    external = coerce_candidate(external_candidate, source="external_ai")
    internal = coerce_candidate(internal_candidate, source="internal_ai")
    rules = coerce_candidate(rule_candidate, source="rules")
    trace: dict[str, Any] = {
        "external_candidate": external.to_dict() if external else None,
        "internal_candidate": internal.to_dict() if internal else None,
        "rules_candidate": rules.to_dict() if rules else None,
    }
    safety_review = safety_flag_review(external, internal)
    if safety_review:
        trace["safety_flag_review"] = safety_review
    if internal_review_metadata:
        trace["internal_review"] = compact_internal_review_metadata(internal_review_metadata)

    safety_flags = sorted(BLOCKER_SAFETY_FLAGS.intersection(internal.safety_flags if internal else ()))
    if safety_flags and internal:
        trace["consensus"] = {"status": "blocked", "reason": "internal safety blocker", "safety_flags": safety_flags}
        return ConsensusDecision(
            status="blocked",
            source="internal_safety",
            candidate=internal,
            bound=None,
            disagreements=tuple(f"internal safety flag: {flag}" for flag in safety_flags),
            decision_trace=trace,
        )

    if external and internal:
        return arbitrate_external_internal(
            conn,
            external,
            internal,
            registry=registry,
            trace=trace,
            internal_review_metadata=internal_review_metadata,
        )

    if internal:
        bound = bind_intent_candidate(conn, internal, registry=registry)
        single_source = single_source_internal_fast_path(
            conn,
            internal,
            bound,
            rules,
            registry=registry,
        )
        if single_source is not None:
            trace["rules_binding"] = single_source.to_dict() if isinstance(single_source, BoundIntent) else None
            trace["consensus"] = {
                "status": "accepted",
                "source": "ai_single_source_internal_fast",
                "reason": "internal AI and deterministic rules agree on a low-risk single intent",
                "binding_status": bound.binding_status,
            }
            return ConsensusDecision(
                status="accepted",
                source="ai_single_source_internal_fast",
                candidate=internal,
                bound=bound if internal.mode == "action" else None,
                disagreements=(),
                decision_trace=trace,
            )
        source = "ai_single_source_internal"
        trace["consensus"] = {
            "status": "clarify",
            "source": source,
            "reason": "internal AI is available but external AI candidate is missing",
            "binding_status": bound.binding_status,
        }
        return ConsensusDecision(
            status="clarify",
            source=source,
            candidate=internal,
            bound=bound,
            disagreements=("external candidate missing",),
            decision_trace=trace,
        )

    if rules:
        bound = bind_intent_candidate(conn, rules, registry=registry)
        trace["consensus"] = {
            "status": "fallback",
            "source": "rules_fallback",
            "binding_status": bound.binding_status,
        }
        return ConsensusDecision(
            status="fallback",
            source="rules_fallback",
            candidate=rules,
            bound=bound,
            disagreements=("AI candidates unavailable",),
            decision_trace=trace,
        )

    trace["consensus"] = {"status": "clarify", "reason": "no candidate available"}
    return ConsensusDecision(
        status="clarify",
        source="no_candidate",
        candidate=None,
        bound=None,
        disagreements=("no intent candidate available",),
        decision_trace=trace,
    )


def arbitrate_external_internal(
    conn: sqlite3.Connection,
    external: IntentCandidate,
    internal: IntentCandidate,
    *,
    registry: ActionResolverRegistry | None,
    trace: dict[str, Any],
    internal_review_metadata: dict[str, Any] | None = None,
) -> ConsensusDecision:
    disagreements: list[str] = []
    disagreements.extend(internal_review_disagreements(internal_review_metadata))
    if external.mode != internal.mode:
        disagreements.append(f"mode mismatch: external={external.mode}, internal={internal.mode}")
    if external.action != internal.action:
        disagreements.append(f"action mismatch: external={external.action}, internal={internal.action}")
    if external.kind != internal.kind and "composite" in {external.kind, internal.kind}:
        disagreements.append(f"kind mismatch: external={external.kind}, internal={internal.kind}")

    if disagreements:
        trace["consensus"] = {"status": "clarify", "reason": "candidate mismatch", "disagreements": disagreements}
        return ConsensusDecision(
            status="clarify",
            source="ai_disagreement",
            candidate=internal,
            bound=None,
            disagreements=tuple(disagreements),
            decision_trace=trace,
        )

    if external.kind == "composite" and internal.kind == "composite":
        bound = bind_intent_candidate(conn, internal, registry=registry) if internal.mode == "action" else None
        trace["consensus"] = {
            "status": "clarify",
            "source": "ai_consensus_unbound",
            "reason": "composite plan requires step confirmation",
            "binding_status": bound.binding_status if bound else "not_applicable",
        }
        if bound is not None:
            trace["internal_binding"] = bound.to_dict()
        return ConsensusDecision(
            status="clarify",
            source="ai_consensus_unbound",
            candidate=internal,
            bound=bound,
            disagreements=("composite plan requires step confirmation",),
            decision_trace=trace,
        )

    if internal.mode != "action":
        trace["consensus"] = {"status": "accepted", "source": "ai_consensus", "reason": "non-action modes agree"}
        return ConsensusDecision(
            status="accepted",
            source="ai_consensus",
            candidate=internal,
            bound=None,
            disagreements=(),
            decision_trace=trace,
        )

    external_bound = bind_intent_candidate(conn, external, registry=registry)
    internal_bound = bind_intent_candidate(conn, internal, registry=registry)
    trace["external_binding"] = external_bound.to_dict()
    trace["internal_binding"] = internal_bound.to_dict()

    external_absent_required = [
        slot
        for slot in external_bound.missing_required
        if not candidate_slot_has_value(external, slot)
        and candidate_slot_has_value(internal, slot)
    ]
    if external_absent_required:
        trace["consensus"] = {
            "status": "clarify",
            "reason": "external candidate is incomplete",
            "binding_status": external_bound.binding_status,
        }
        return ConsensusDecision(
            status="clarify",
            source="ai_disagreement",
            candidate=internal,
            bound=internal_bound,
            disagreements=tuple(
                f"external candidate incomplete: {item}"
                for item in external_absent_required
            )
            or ("external candidate incomplete",),
            decision_trace=trace,
        )

    disagreements.extend(binding_disagreements(external_bound, internal_bound))
    if disagreements:
        trace["consensus"] = {"status": "clarify", "reason": "binding mismatch", "disagreements": disagreements}
        return ConsensusDecision(
            status="clarify",
            source="ai_disagreement",
            candidate=internal,
            bound=internal_bound,
            disagreements=tuple(disagreements),
            decision_trace=trace,
        )

    if internal_bound.binding_status != "bound":
        trace["consensus"] = {
            "status": "clarify",
            "source": "ai_consensus_unbound",
            "binding_status": internal_bound.binding_status,
        }
        return ConsensusDecision(
            status="clarify",
            source="ai_consensus_unbound",
            candidate=internal,
            bound=internal_bound,
            disagreements=tuple(internal_bound.needs_confirmation or internal_bound.missing_required or internal_bound.errors),
            decision_trace=trace,
        )

    trace["consensus"] = {
        "status": "accepted",
        "source": "ai_consensus",
        "binding_status": internal_bound.binding_status,
    }
    return ConsensusDecision(
        status="accepted",
        source="ai_consensus",
        candidate=internal,
        bound=internal_bound,
        disagreements=(),
        decision_trace=trace,
    )


def safety_flag_review(
    external: IntentCandidate | None,
    internal: IntentCandidate | None,
) -> dict[str, Any] | None:
    external_flags = set(BLOCKER_SAFETY_FLAGS.intersection(external.safety_flags if external else ()))
    internal_flags = set(BLOCKER_SAFETY_FLAGS.intersection(internal.safety_flags if internal else ()))
    if not external_flags and not internal_flags:
        return None
    return {
        "external_blocking_flags": sorted(external_flags),
        "internal_blocking_flags": sorted(internal_flags),
        "confirmed_by_internal": sorted(external_flags & internal_flags),
        "cleared_by_internal": sorted(external_flags - internal_flags) if internal is not None else [],
        "internal_only": sorted(internal_flags - external_flags),
        "policy": "external flags are low-trust signals; internal review is authoritative on healthy consensus",
    }


def binding_disagreements(external: BoundIntent, internal: BoundIntent) -> list[str]:
    disagreements: list[str] = []
    if external.action != internal.action:
        disagreements.append(f"bound action mismatch: external={external.action}, internal={internal.action}")
        return disagreements
    common_slots = (set(external.options) & set(internal.options)) - {"user_text"}
    for slot in sorted(common_slots):
        if str(external.options.get(slot)) != str(internal.options.get(slot)):
            disagreements.append(
                f"slot mismatch for {slot}: external={external.options.get(slot)}, internal={internal.options.get(slot)}"
            )
    for slot in sorted((set(external.candidate.slots) & set(internal.candidate.slots)) - common_slots):
        external_status = slot_status(external, slot)
        internal_status = slot_status(internal, slot)
        if external_status in {"missing", "ambiguous", "invalid"} or internal_status in {"missing", "ambiguous", "invalid"}:
            same_unbound_slot = (
                external_status == internal_status
                and str(external.candidate.slots.get(slot)) == str(internal.candidate.slots.get(slot))
            )
            if same_unbound_slot:
                continue
            disagreements.append(f"slot binding mismatch for {slot}: external={external_status}, internal={internal_status}")
    return disagreements


def internal_review_disagreements(metadata: dict[str, Any] | None) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    agreement = str(metadata.get("agreement_with_external") or "").strip().lower()
    quality = str(metadata.get("external_candidate_quality") or "").strip().lower()
    details = normalize_review_disagreements(metadata.get("disagreements"))
    disagreements: list[str] = []
    if quality == "wrong_action":
        disagreements.append("action mismatch: internal review marked external candidate as wrong_action")
    elif quality == "wrong_mode":
        disagreements.append("mode mismatch: internal review marked external candidate as wrong_mode")
    elif quality == "unsafe":
        disagreements.append("internal review marked external candidate as unsafe")
    if agreement == "partial":
        disagreements.append("internal review partial agreement with external candidate")
    elif agreement == "disagree":
        disagreements.append("internal review disagreement with external candidate")
    if disagreements and details:
        disagreements.extend(f"internal review detail: {item}" for item in details)
    return disagreements


def compact_internal_review_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "agreement_with_external": metadata.get("agreement_with_external"),
        "external_candidate_quality": metadata.get("external_candidate_quality"),
        "disagreements": normalize_review_disagreements(metadata.get("disagreements")),
    }


def normalize_review_disagreements(value: Any) -> list[str]:
    raw_items = value if isinstance(value, list) else ([value] if value else [])
    return [str(item).strip() for item in raw_items if str(item).strip()]


def slot_status(bound: BoundIntent, slot: str) -> str:
    trace = bound.decision_trace.get("binder", {}).get("slot_trace", {})
    if not isinstance(trace, dict):
        return "unknown"
    item = trace.get(slot)
    if not isinstance(item, dict):
        return "unknown"
    return str(item.get("status") or "unknown")


def candidate_slot_has_value(candidate: IntentCandidate, slot: str) -> bool:
    value = candidate.slots.get(slot)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def single_source_internal_fast_path(
    conn: sqlite3.Connection,
    internal: IntentCandidate,
    internal_bound: BoundIntent,
    rules: IntentCandidate | None,
    *,
    registry: ActionResolverRegistry | None,
) -> BoundIntent | bool | None:
    if rules is None:
        return None
    if internal.kind != "single" or rules.kind == "composite":
        return None
    if internal.safety_flags or internal.missing_slots or internal.needs_confirmation:
        return None
    if rules.mode != internal.mode:
        return None
    if internal.mode == "query":
        return True
    if internal.mode != "action":
        return None
    if rules.action != internal.action:
        return None
    if ACTION_BASE_RISK.get(internal.action or "") != YELLOW_FAST:
        return None
    if internal_bound.binding_status != "bound":
        return None
    rules_bound = bind_intent_candidate(conn, rules, registry=registry)
    if rules_bound.binding_status != "bound":
        return None
    if binding_disagreements(rules_bound, internal_bound):
        return None
    return rules_bound


def coerce_candidate(value: IntentCandidate | dict[str, Any] | None, *, source: str) -> IntentCandidate | None:
    if value is None:
        return None
    if isinstance(value, IntentCandidate):
        return value
    return normalize_intent_candidate(value, source=source)
