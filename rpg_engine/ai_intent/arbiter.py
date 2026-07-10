from __future__ import annotations

import sqlite3
from dataclasses import replace
from typing import Any

from ..actions import ActionResolverRegistry, get_default_action_registry
from ..intent_manifest import QUERY_KINDS
from ..visibility import PLAYER_VIEW
from .binder import bind_intent_candidate, find_entity_candidates, normalize_slot_name
from .normalization import normalize_intent_candidate
from .risk import ACTION_BASE_RISK, YELLOW_FAST
from .types import BoundIntent, CandidateStep, ConsensusDecision, IntentCandidate


BLOCKER_SAFETY_FLAGS = {
    "prompt_injection",
    "out_of_world",
    "forced_save",
    "hidden_info",
    "maintenance_request",
    "unsafe_command",
}
QUERY_KIND_SET = set(QUERY_KINDS)


def arbitrate_intent_candidates(
    conn: sqlite3.Connection,
    *,
    external_candidate: IntentCandidate | dict[str, Any] | None = None,
    internal_candidate: IntentCandidate | dict[str, Any] | None = None,
    rule_candidate: IntentCandidate | dict[str, Any] | None = None,
    internal_review_metadata: dict[str, Any] | None = None,
    intent_ai_mode: str = "consensus",
    registry: ActionResolverRegistry | None = None,
    view: str = PLAYER_VIEW,
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

    if intent_ai_mode == "off" and external is not None:
        return arbitrate_external_primary(
            conn,
            external,
            registry=registry,
            view=view,
            trace=trace,
        )

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
            view=view,
            trace=trace,
            internal_review_metadata=internal_review_metadata,
        )

    if internal:
        shape_errors = candidate_shape_errors(internal, source_label="internal")
        if shape_errors:
            internal = safe_shape_failure_candidate(internal)
            trace["internal_candidate"] = internal.to_dict()
            trace["consensus"] = {
                "status": "blocked",
                "source": "ai_single_source_internal",
                "reason": shape_errors[0],
            }
            return ConsensusDecision(
                status="blocked",
                source="ai_single_source_internal",
                candidate=internal,
                bound=None,
                disagreements=shape_errors,
                decision_trace=trace,
            )
        validation_status, validation_issues, internal, validated_bound = validate_candidate_before_disagreement(
            conn,
            internal,
            registry=registry,
            view=view,
            source_label="internal",
        )
        trace["internal_candidate"] = internal.to_dict()
        if validated_bound is not None:
            trace["internal_binding"] = validated_bound.to_dict()
        if validation_status != "accepted":
            source = "ai_single_source_internal"
            trace["consensus"] = {
                "status": validation_status,
                "source": source,
                "reason": validation_issues[0] if validation_issues else "internal candidate requires clarification",
                "plan_validated": internal.kind == "composite",
                "plan_confirmation_ready": False,
            }
            return ConsensusDecision(
                status=validation_status,
                source=source,
                candidate=internal,
                bound=validated_bound,
                disagreements=validation_issues or ("external candidate missing",),
                decision_trace=trace,
            )
        bound = validated_bound or bind_intent_candidate(conn, internal, registry=registry, view=view)
        single_source = single_source_internal_fast_path(
            conn,
            internal,
            bound,
            rules,
            registry=registry,
            view=view,
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
            "plan_validated": internal.kind == "composite",
            "plan_confirmation_ready": False,
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
        bound = bind_intent_candidate(conn, rules, registry=registry, view=view)
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


def arbitrate_external_primary(
    conn: sqlite3.Connection,
    external: IntentCandidate,
    *,
    registry: ActionResolverRegistry | None,
    view: str,
    trace: dict[str, Any],
) -> ConsensusDecision:
    """Validate an external route proposal when internal intent AI is explicitly off."""
    blocking_flags = sorted(BLOCKER_SAFETY_FLAGS.intersection(external.safety_flags))
    if blocking_flags:
        disagreements = tuple(f"external safety flag: {flag}" for flag in blocking_flags)
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": "external safety blocker",
            "safety_flags": blocking_flags,
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=disagreements,
            decision_trace=trace,
        )

    shape_errors = candidate_shape_errors(external, source_label="external")
    if shape_errors:
        safe_external = safe_shape_failure_candidate(external)
        trace["external_candidate"] = safe_external.to_dict()
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": shape_errors[0],
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=safe_external,
            bound=None,
            disagreements=shape_errors,
            decision_trace=trace,
        )

    if (external.mode == "query") != (external.kind == "query"):
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": "external candidate mode and kind are inconsistent",
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=("external candidate mode and kind are inconsistent",),
            decision_trace=trace,
        )

    if external.mode == "action" and external.kind not in {"single", "composite"}:
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": "external action candidate kind is not routable",
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=("external action candidate kind is not routable",),
            decision_trace=trace,
        )

    if bool(external.plan) != (external.kind == "composite"):
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": "external composite kind and plan are inconsistent",
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=("external composite kind and plan are inconsistent",),
            decision_trace=trace,
        )

    duplicate_slots = duplicate_normalized_slots(external)
    if duplicate_slots:
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": "external candidate repeats a normalized action slot",
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=tuple(f"duplicate normalized action slot: {slot}" for slot in duplicate_slots),
            decision_trace=trace,
        )

    if external.kind == "composite":
        validation_status, disagreements, external, top_bound = validate_composite_candidate(
            conn,
            external,
            registry=registry,
            view=view,
            source_label="external",
        )
        trace["external_candidate"] = external.to_dict()
        trace["consensus"] = {
            "status": "blocked" if validation_status == "blocked" else "clarify",
            "source": "external_primary",
            "reason": (
                disagreements[0]
                if disagreements
                else "composite plan requires step confirmation"
            ),
            "plan_validated": True,
            "plan_confirmation_ready": validation_status == "accepted",
        }
        return ConsensusDecision(
            status="blocked" if validation_status == "blocked" else "clarify",
            source="external_primary",
            candidate=external,
            bound=top_bound,
            disagreements=disagreements or ("composite plan requires step confirmation",),
            decision_trace=trace,
        )

    if external.mode == "query":
        status, disagreements = validate_candidate_query(conn, external, view=view, source_label="external")
        if status == "accepted" and (external.missing_slots or external.needs_confirmation):
            status = "clarify"
            disagreements = external_clarification_signals(external)
        trace["consensus"] = {
            "status": status,
            "source": "external_primary",
            "reason": "external query contract validated" if status == "accepted" else disagreements[0],
        }
        return ConsensusDecision(
            status=status,
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=() if status == "accepted" else disagreements,
            decision_trace=trace,
        )

    if external.mode != "action":
        trace["consensus"] = {
            "status": "blocked",
            "source": "external_primary",
            "reason": "external candidate mode is not routable",
        }
        return ConsensusDecision(
            status="blocked",
            source="external_primary",
            candidate=external,
            bound=None,
            disagreements=("external candidate mode is not routable",),
            decision_trace=trace,
        )

    bound = bind_intent_candidate(conn, external, registry=registry, view=view)
    trace["external_binding"] = bound.to_dict()
    ignored_slots = outside_contract_slots(bound)
    contract_errors = tuple(f"ignored slot outside resolver contract: {slot}" for slot in ignored_slots)
    if contract_errors:
        status = "blocked"
        disagreements = contract_errors
    elif bound.binding_status == "bound" and (external.missing_slots or external.needs_confirmation):
        status = "clarify"
        disagreements = external_clarification_signals(external)
    elif bound.binding_status == "bound":
        status = "accepted"
        disagreements: tuple[str, ...] = ()
    elif bound.binding_status in {"missing", "ambiguous"}:
        status = "clarify"
        disagreements = tuple(bound.needs_confirmation or bound.missing_required or ("external binding requires clarification",))
    else:
        status = "blocked"
        disagreements = tuple(bound.errors or bound.missing_required or ("external binding is invalid",))
    trace["consensus"] = {
        "status": status,
        "source": "external_primary",
        "reason": "external action binding validated" if status == "accepted" else disagreements[0],
        "binding_status": bound.binding_status,
    }
    return ConsensusDecision(
        status=status,
        source="external_primary",
        candidate=external,
        bound=bound,
        disagreements=disagreements,
        decision_trace=trace,
    )


def external_clarification_signals(candidate: IntentCandidate) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*candidate.missing_slots, *candidate.needs_confirmation))) or (
        "external candidate requires clarification",
    )


def outside_contract_slots(bound: BoundIntent) -> list[str]:
    slot_trace = bound.decision_trace.get("binder", {}).get("slot_trace", {})
    return (
        sorted(
            str(slot)
            for slot, item in slot_trace.items()
            if isinstance(item, dict)
            and item.get("status") == "ignored"
            and item.get("reason") == "outside resolver contract"
        )
        if isinstance(slot_trace, dict)
        else []
    )


def validate_composite_candidate(
    conn: sqlite3.Connection,
    candidate: IntentCandidate,
    *,
    registry: ActionResolverRegistry | None,
    view: str,
    source_label: str,
) -> tuple[str, tuple[str, ...], IntentCandidate, BoundIntent]:
    top_bound = bind_intent_candidate(
        conn,
        replace(candidate, kind="single", plan=()),
        registry=registry,
        view=view,
    )
    safe_top_slots = {key: value for key, value in top_bound.options.items() if key != "user_text"}
    safe_candidate = replace(candidate, slots=safe_top_slots)
    safe_bound = replace(
        top_bound,
        candidate=replace(safe_candidate, kind="single", plan=()),
    )
    duplicate_slots = duplicate_normalized_slots(candidate)
    if duplicate_slots:
        disagreements = tuple(
            f"{source_label} composite repeats normalized action slot: {slot}"
            for slot in duplicate_slots
        )
        return (
            "blocked",
            disagreements,
            replace(safe_candidate, kind="unresolved", action=None, plan=()),
            safe_bound,
        )
    if not candidate.plan:
        return (
            "blocked",
            (f"{source_label} composite plan requires at least one step",),
            replace(safe_candidate, kind="unresolved", action=None, plan=()),
            safe_bound,
        )
    top_contract_errors = tuple(
        f"{source_label} composite ignored slot outside resolver contract: {slot}"
        for slot in outside_contract_slots(top_bound)
    )
    if top_contract_errors or top_bound.binding_status not in {"bound", "missing", "ambiguous"}:
        disagreements = top_contract_errors or tuple(
            f"{source_label} composite: {item}"
            for item in (
                top_bound.errors
                or top_bound.missing_required
                or ("action is missing or not in the action registry",)
            )
        )
        return (
            "blocked",
            disagreements,
            replace(safe_candidate, kind="unresolved", action=None, plan=()),
            safe_bound,
        )

    top_clarifications = tuple(
        dict.fromkeys(
            (
                *top_bound.needs_confirmation,
                *top_bound.missing_required,
                *candidate.missing_slots,
                *candidate.needs_confirmation,
            )
        )
    )
    plan_status, plan_disagreements, safe_plan = validate_candidate_plan(
        conn,
        candidate,
        registry=registry,
        view=view,
        source_label=source_label,
    )
    safe_candidate = replace(safe_candidate, plan=safe_plan)
    disagreements = tuple(dict.fromkeys((*top_clarifications, *plan_disagreements)))
    if plan_status == "blocked":
        return (
            "blocked",
            disagreements,
            replace(safe_candidate, kind="unresolved", action=None, plan=()),
            safe_bound,
        )
    if disagreements:
        return "clarify", disagreements, safe_candidate, safe_bound
    return "accepted", (), safe_candidate, safe_bound


def validate_candidate_plan(
    conn: sqlite3.Connection,
    candidate: IntentCandidate,
    *,
    registry: ActionResolverRegistry | None,
    view: str,
    source_label: str,
) -> tuple[str, tuple[str, ...], tuple[CandidateStep, ...]]:
    safe_steps: list[CandidateStep] = []
    clarifications: list[str] = []
    for index, step in enumerate(candidate.plan, start=1):
        step_candidate = IntentCandidate(
            source=candidate.source,
            source_user_text=candidate.source_user_text,
            kind="single",
            mode="action",
            action=step.action,
            slots=dict(step.slots),
            confidence=candidate.confidence,
        )
        duplicate_slots = duplicate_normalized_slots(step_candidate)
        if duplicate_slots:
            errors = tuple(
                f"{source_label} plan step {index} repeats normalized action slot: {slot}"
                for slot in duplicate_slots
            )
            return "blocked", errors, tuple(safe_steps)

        bound = bind_intent_candidate(conn, step_candidate, registry=registry, view=view)
        ignored_slots = outside_contract_slots(bound)
        if ignored_slots:
            errors = tuple(
                f"{source_label} plan step {index} ignored slot outside resolver contract: {slot}"
                for slot in ignored_slots
            )
            return "blocked", errors, tuple(safe_steps)
        if bound.binding_status not in {"bound", "missing", "ambiguous"}:
            errors = tuple(
                f"{source_label} plan step {index}: {item}"
                for item in (bound.errors or bound.missing_required or ("binding is invalid",))
            )
            return "blocked", errors, tuple(safe_steps)

        safe_steps.append(
            CandidateStep(
                action=bound.action or step.action,
                slots={key: value for key, value in bound.options.items() if key != "user_text"},
            )
        )
        if bound.binding_status in {"missing", "ambiguous"}:
            clarifications.extend(
                f"{source_label} plan step {index}: {item}"
                for item in (
                    bound.needs_confirmation
                    or bound.missing_required
                    or ("binding requires clarification",)
                )
            )

    return (
        "clarify" if clarifications else "accepted",
        tuple(dict.fromkeys(clarifications)),
        tuple(safe_steps),
    )


def validate_candidate_query(
    conn: sqlite3.Connection,
    candidate: IntentCandidate,
    *,
    view: str,
    source_label: str,
) -> tuple[str, tuple[str, ...]]:
    unsupported_slots = sorted(set(candidate.slots) - {"query_kind", "query_text"})
    if unsupported_slots:
        return "blocked", tuple(f"unsupported {source_label} query slot: {slot}" for slot in unsupported_slots)
    raw_query_kind = candidate.slots.get("query_kind")
    raw_query_text = candidate.slots.get("query_text")
    if raw_query_kind is not None and not isinstance(raw_query_kind, str):
        return "blocked", (f"{source_label} query_kind must be a string",)
    if raw_query_text is not None and not isinstance(raw_query_text, str):
        return "blocked", (f"{source_label} query_text must be a string",)
    query_kind = str(raw_query_kind or "").strip().lower()
    query_text = str(raw_query_text or "").strip()
    if query_kind not in QUERY_KIND_SET:
        return "blocked", (f"{source_label} query_kind is missing or unsupported",)
    if query_kind in {"entity", "context"} and not query_text:
        return "clarify", (f"{query_kind} query requires query_text",)
    if query_kind == "entity":
        matches = find_entity_candidates(conn, query_text, allowed_types=None, view=view)
        if not matches:
            return "blocked", (f"{source_label} entity query target is not available in the player view",)
        if len(matches) > 1:
            return "clarify", (f"{source_label} entity query target is ambiguous",)
    return "accepted", ()


def canonical_query_slots(candidate: IntentCandidate) -> tuple[str, str]:
    query_kind = str(candidate.slots.get("query_kind") or "").strip().lower()
    query_text = str(candidate.slots.get("query_text") or "").strip()
    return query_kind, "" if query_kind == "scene" else query_text


def duplicate_normalized_slots(candidate: IntentCandidate) -> tuple[str, ...]:
    if not candidate.action:
        return ()
    seen: set[str] = set()
    duplicates: list[str] = []
    for raw_slot in candidate.slots:
        normalized = normalize_slot_name(candidate.action, raw_slot)
        if normalized in seen and normalized not in duplicates:
            duplicates.append(normalized)
        seen.add(normalized)
    return tuple(sorted(duplicates))


def candidate_shape_errors(candidate: IntentCandidate, *, source_label: str) -> tuple[str, ...]:
    errors: list[str] = []
    if candidate.mode not in {"action", "query"}:
        errors.append(f"{source_label} candidate mode is not routable")
    if candidate.mode != "action" and candidate.action is not None:
        errors.append(f"{source_label} non-action candidate must not carry an action")
    if (candidate.mode == "query") != (candidate.kind == "query"):
        errors.append(f"{source_label} candidate mode and kind are inconsistent")
    if candidate.mode == "action" and candidate.kind not in {"single", "composite"}:
        errors.append(f"{source_label} action candidate kind is not routable")
    if bool(candidate.plan) != (candidate.kind == "composite"):
        errors.append(f"{source_label} composite kind and plan are inconsistent")
    return tuple(errors)


def safe_shape_failure_candidate(candidate: IntentCandidate) -> IntentCandidate:
    return replace(
        candidate,
        kind="unresolved",
        mode="unknown",
        action=None,
        slots={},
        plan=(),
    )


def validate_candidate_before_disagreement(
    conn: sqlite3.Connection,
    candidate: IntentCandidate,
    *,
    registry: ActionResolverRegistry | None,
    view: str,
    source_label: str,
) -> tuple[str, tuple[str, ...], IntentCandidate, BoundIntent | None]:
    if candidate.kind == "composite":
        return validate_composite_candidate(
            conn,
            candidate,
            registry=registry,
            view=view,
            source_label=source_label,
        )
    if candidate.mode == "query":
        status, issues = validate_candidate_query(
            conn,
            candidate,
            view=view,
            source_label=source_label,
        )
        if status == "accepted" and (candidate.missing_slots or candidate.needs_confirmation):
            status = "clarify"
            issues = external_clarification_signals(candidate)
        if status == "blocked":
            return status, issues, safe_shape_failure_candidate(candidate), None
        query_kind, query_text = canonical_query_slots(candidate)
        safe_slots = {"query_kind": query_kind}
        if query_text:
            safe_slots["query_text"] = query_text
        return status, issues, replace(candidate, slots=safe_slots), None

    duplicate_slots = duplicate_normalized_slots(candidate)
    if duplicate_slots:
        issues = tuple(
            f"{source_label} duplicate normalized action slot: {slot}"
            for slot in duplicate_slots
        )
        return "blocked", issues, safe_shape_failure_candidate(candidate), None
    bound = bind_intent_candidate(conn, candidate, registry=registry, view=view)
    safe_slots = {key: value for key, value in bound.options.items() if key != "user_text"}
    safe_candidate = replace(candidate, slots=safe_slots)
    safe_bound = replace(bound, candidate=safe_candidate)
    ignored_slots = outside_contract_slots(bound)
    if ignored_slots:
        issues = tuple(
            f"{source_label} ignored slot outside resolver contract: {slot}"
            for slot in ignored_slots
        )
        return "blocked", issues, safe_shape_failure_candidate(candidate), safe_bound
    if bound.binding_status not in {"bound", "missing", "ambiguous"}:
        issues = tuple(
            f"{source_label}: {item}"
            for item in (bound.errors or bound.missing_required or ("binding is invalid",))
        )
        return "blocked", issues, safe_shape_failure_candidate(candidate), safe_bound
    issues = tuple(
        dict.fromkeys(
            (
                *bound.needs_confirmation,
                *bound.missing_required,
                *candidate.missing_slots,
                *candidate.needs_confirmation,
            )
        )
    )
    return ("clarify" if issues else "accepted"), issues, safe_candidate, safe_bound


def arbitrate_external_internal(
    conn: sqlite3.Connection,
    external: IntentCandidate,
    internal: IntentCandidate,
    *,
    registry: ActionResolverRegistry | None,
    view: str,
    trace: dict[str, Any],
    internal_review_metadata: dict[str, Any] | None = None,
) -> ConsensusDecision:
    external_shape_errors = candidate_shape_errors(external, source_label="external")
    internal_shape_errors = candidate_shape_errors(internal, source_label="internal")
    shape_errors = (*external_shape_errors, *internal_shape_errors)
    if shape_errors:
        safe_external = safe_shape_failure_candidate(external) if external_shape_errors else external
        safe_internal = safe_shape_failure_candidate(internal) if internal_shape_errors else internal
        trace["external_candidate"] = safe_external.to_dict()
        trace["internal_candidate"] = safe_internal.to_dict()
        trace["consensus"] = {
            "status": "blocked",
            "source": "ai_consensus_unbound",
            "reason": shape_errors[0],
        }
        return ConsensusDecision(
            status="blocked",
            source="ai_consensus_unbound",
            candidate=safe_internal,
            bound=None,
            disagreements=tuple(shape_errors),
            decision_trace=trace,
        )

    disagreements: list[str] = []
    disagreements.extend(internal_review_disagreements(internal_review_metadata))
    if external.mode != internal.mode:
        disagreements.append(f"mode mismatch: external={external.mode}, internal={internal.mode}")
    if external.action != internal.action:
        disagreements.append(f"action mismatch: external={external.action}, internal={internal.action}")
    if external.kind != internal.kind and "composite" in {external.kind, internal.kind}:
        disagreements.append(f"kind mismatch: external={external.kind}, internal={internal.kind}")

    if disagreements:
        external_status, external_issues, external, external_bound = validate_candidate_before_disagreement(
            conn,
            external,
            registry=registry,
            view=view,
            source_label="external",
        )
        internal_status, internal_issues, internal, internal_bound = validate_candidate_before_disagreement(
            conn,
            internal,
            registry=registry,
            view=view,
            source_label="internal",
        )
        trace["external_candidate"] = external.to_dict()
        trace["internal_candidate"] = internal.to_dict()
        if external_bound is not None:
            trace["external_binding"] = external_bound.to_dict()
        if internal_bound is not None:
            trace["internal_binding"] = internal_bound.to_dict()
        disagreements.extend((*external_issues, *internal_issues))
        validation_blocked = "blocked" in {external_status, internal_status}
        disagreements = list(dict.fromkeys(disagreements))
        trace["consensus"] = {
            "status": "blocked" if validation_blocked else "clarify",
            "reason": "candidate mismatch",
            "disagreements": disagreements,
            "plan_validated": internal.kind == "composite",
            "plan_confirmation_ready": False,
        }
        return ConsensusDecision(
            status="blocked" if validation_blocked else "clarify",
            source="ai_disagreement",
            candidate=internal,
            bound=internal_bound,
            disagreements=tuple(disagreements),
            decision_trace=trace,
        )

    if external.kind == "composite" and internal.kind == "composite":
        external_status, external_disagreements, external, external_bound = validate_composite_candidate(
            conn,
            external,
            registry=registry,
            view=view,
            source_label="external",
        )
        internal_status, internal_disagreements, internal, internal_bound = validate_composite_candidate(
            conn,
            internal,
            registry=registry,
            view=view,
            source_label="internal",
        )
        trace["external_candidate"] = external.to_dict()
        trace["internal_candidate"] = internal.to_dict()
        trace["external_binding"] = external_bound.to_dict()
        trace["internal_binding"] = internal_bound.to_dict()
        disagreements = list(dict.fromkeys((*external_disagreements, *internal_disagreements)))
        if external.plan != internal.plan:
            disagreements.append("composite plan mismatch after safe binding")
        validation_blocked = "blocked" in {external_status, internal_status}
        plan_confirmation_ready = (
            {external_status, internal_status} == {"accepted"}
            and external.plan == internal.plan
        )
        trace["consensus"] = {
            "status": "blocked" if validation_blocked else "clarify",
            "source": "ai_consensus_unbound",
            "reason": disagreements[0] if disagreements else "composite plan requires step confirmation",
            "binding_status": internal_bound.binding_status,
            "plan_validated": True,
            "plan_confirmation_ready": plan_confirmation_ready,
        }
        return ConsensusDecision(
            status="blocked" if validation_blocked else "clarify",
            source="ai_consensus_unbound",
            candidate=internal,
            bound=internal_bound,
            disagreements=tuple(disagreements) or ("composite plan requires step confirmation",),
            decision_trace=trace,
        )

    if internal.mode == "query":
        external_status, external_query_issues = validate_candidate_query(
            conn,
            external,
            view=view,
            source_label="external",
        )
        internal_status, internal_query_issues = validate_candidate_query(
            conn,
            internal,
            view=view,
            source_label="internal",
        )
        query_issues = list(dict.fromkeys((*external_query_issues, *internal_query_issues)))
        if canonical_query_slots(external) != canonical_query_slots(internal):
            query_issues.append("query slot mismatch between external and internal candidates")
        if external_status == "accepted" and (external.missing_slots or external.needs_confirmation):
            query_issues.extend(external_clarification_signals(external))
            external_status = "clarify"
        if internal_status == "accepted" and (internal.missing_slots or internal.needs_confirmation):
            query_issues.extend(external_clarification_signals(internal))
            internal_status = "clarify"
        query_issues = list(dict.fromkeys(query_issues))
        if "blocked" in {external_status, internal_status}:
            status = "blocked"
        elif query_issues or "clarify" in {external_status, internal_status}:
            status = "clarify"
        else:
            status = "accepted"
        trace["consensus"] = {
            "status": status,
            "source": "ai_consensus" if status == "accepted" else "ai_consensus_unbound",
            "reason": query_issues[0] if query_issues else "query contracts agree",
        }
        return ConsensusDecision(
            status=status,
            source="ai_consensus" if status == "accepted" else "ai_consensus_unbound",
            candidate=internal,
            bound=None,
            disagreements=tuple(query_issues),
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

    external_bound = bind_intent_candidate(conn, external, registry=registry, view=view)
    internal_bound = bind_intent_candidate(conn, internal, registry=registry, view=view)
    trace["external_binding"] = external_bound.to_dict()
    trace["internal_binding"] = internal_bound.to_dict()
    structural_issues = [
        *(f"external duplicate normalized action slot: {slot}" for slot in duplicate_normalized_slots(external)),
        *(f"internal duplicate normalized action slot: {slot}" for slot in duplicate_normalized_slots(internal)),
        *(f"external ignored slot outside resolver contract: {slot}" for slot in outside_contract_slots(external_bound)),
        *(f"internal ignored slot outside resolver contract: {slot}" for slot in outside_contract_slots(internal_bound)),
    ]
    if structural_issues:
        trace["consensus"] = {
            "status": "blocked",
            "source": "ai_consensus_unbound",
            "reason": structural_issues[0],
        }
        return ConsensusDecision(
            status="blocked",
            source="ai_consensus_unbound",
            candidate=internal,
            bound=internal_bound,
            disagreements=tuple(structural_issues),
            decision_trace=trace,
        )

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

    disagreements.extend(binding_disagreements(external_bound, internal_bound, registry=registry))
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

    declared_clarifications = tuple(
        dict.fromkeys(
            (
                *external.missing_slots,
                *external.needs_confirmation,
                *internal.missing_slots,
                *internal.needs_confirmation,
            )
        )
    )
    if declared_clarifications:
        trace["consensus"] = {
            "status": "clarify",
            "source": "ai_consensus_unbound",
            "reason": "candidate requires declared clarification",
        }
        return ConsensusDecision(
            status="clarify",
            source="ai_consensus_unbound",
            candidate=internal,
            bound=internal_bound,
            disagreements=declared_clarifications,
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


def binding_disagreements(
    external: BoundIntent,
    internal: BoundIntent,
    *,
    registry: ActionResolverRegistry | None = None,
) -> list[str]:
    disagreements: list[str] = []
    if external.action != internal.action:
        disagreements.append(f"bound action mismatch: external={external.action}, internal={internal.action}")
        return disagreements
    action_registry = registry or get_default_action_registry()
    spec = action_registry.get(external.action or "")
    defaults = {
        option.name: option.default
        for option in (spec.option_specs if spec is not None else ())
        if option.default is not None
    }
    missing = object()
    effective_slots = (set(external.options) | set(internal.options)) - {"user_text"}
    for slot in sorted(effective_slots):
        external_value = external.options.get(slot, defaults.get(slot, missing))
        internal_value = internal.options.get(slot, defaults.get(slot, missing))
        if external_value is missing or internal_value is missing:
            disagreements.append(
                f"one-sided bound option for {slot}: "
                f"external={external.options.get(slot)}, internal={internal.options.get(slot)}"
            )
        elif external_value != internal_value:
            disagreements.append(
                f"slot mismatch for {slot}: external={external_value}, internal={internal_value}"
            )
    for slot in sorted((set(external.candidate.slots) & set(internal.candidate.slots)) - effective_slots):
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
    view: str,
) -> BoundIntent | bool | None:
    if rules is None:
        return None
    if rules.safety_flags or rules.missing_slots or rules.needs_confirmation:
        return None
    if candidate_shape_errors(rules, source_label="rules"):
        return None
    rules_status, _, rules, validated_rules_bound = validate_candidate_before_disagreement(
        conn,
        rules,
        registry=registry,
        view=view,
        source_label="rules",
    )
    if rules_status != "accepted":
        return None
    if internal.safety_flags or internal.missing_slots or internal.needs_confirmation:
        return None
    if rules.mode != internal.mode:
        return None
    if internal.mode == "query":
        return (
            True
            if internal.kind == "query"
            and rules.kind == "query"
            and canonical_query_slots(internal) == canonical_query_slots(rules)
            else None
        )
    if internal.mode != "action" or internal.kind != "single" or rules.kind == "composite":
        return None
    if rules.action != internal.action:
        return None
    if ACTION_BASE_RISK.get(internal.action or "") != YELLOW_FAST:
        return None
    if internal_bound.binding_status != "bound":
        return None
    rules_bound = validated_rules_bound or bind_intent_candidate(conn, rules, registry=registry, view=view)
    if rules_bound.binding_status != "bound":
        return None
    if binding_disagreements(rules_bound, internal_bound, registry=registry):
        return None
    return rules_bound


def coerce_candidate(value: IntentCandidate | dict[str, Any] | None, *, source: str) -> IntentCandidate | None:
    if value is None:
        return None
    if isinstance(value, IntentCandidate):
        return value
    return normalize_intent_candidate(value, source=source)
