from __future__ import annotations

import hashlib
import json
from typing import Any

from ..intent_manifest import QUERY_KINDS
from ..ux import PlanStep
from .types import ClarificationChoice, ClarificationQuestion, ConsensusDecision, ConsensusRouteAdoption, RouteOutcome


QUERY_KIND_SET = set(QUERY_KINDS)


def route_outcome_from_intent_decision(
    decision: ConsensusDecision,
    *,
    fallback_submode: str,
) -> ConsensusRouteAdoption | None:
    if decision.status == "fallback":
        return None
    if decision.status == "accepted" and decision.bound:
        bound = decision.bound
        candidate = bound.candidate
        return ConsensusRouteAdoption(
            outcome=RouteOutcome(
                mode="action",
                submode=bound.action or fallback_submode,
                action=bound.action,
                options=dict(bound.options),
                kind=candidate.kind,
                status="ready" if bound.binding_status == "bound" else "needs_confirmation",
                missing_required=bound.missing_required,
                needs_confirmation=bound.needs_confirmation,
                errors=bound.errors,
                source=decision.source,
                confidence=candidate.confidence,
            )
        )
    if decision.status == "accepted" and decision.candidate:
        candidate = decision.candidate
        if candidate.mode == "maintenance":
            return ConsensusRouteAdoption(
                outcome=RouteOutcome(
                    mode="unknown",
                    submode="unknown",
                    action=None,
                    options={},
                    kind="unresolved",
                    status="blocked",
                    errors=("maintenance request is outside the normal player intent mode",),
                    player_message="这是维护或作者工具请求，不会作为普通玩家回合处理。",
                    source=decision.source,
                    confidence=candidate.confidence,
                )
            )
        if candidate.mode == "query":
            submode = query_submode_from_candidate(candidate, fallback_submode)
            options = query_options_from_candidate(candidate)
        else:
            submode = fallback_submode
            options = {}
        return ConsensusRouteAdoption(
            outcome=RouteOutcome(
                mode=candidate.mode,
                submode=submode,
                action=None,
                options=options,
                kind=candidate.kind,
                status="ready",
                source=decision.source,
                confidence=candidate.confidence,
            )
        )

    candidate = decision.candidate
    external_primary = decision.source == "external_primary"
    mode = candidate.mode if candidate and candidate.mode in {"action", "query", "maintenance", "unknown"} else "unknown"
    query_kind = str(candidate.slots.get("query_kind") or "").strip().lower() if candidate else ""
    if external_primary and mode == "query":
        submode = query_kind if query_kind in QUERY_KIND_SET else "unknown"
    elif candidate and candidate.action:
        submode = candidate.action
    elif external_primary and mode in {"action", "maintenance", "unknown"}:
        submode = "unknown"
    else:
        submode = "unknown" if mode in {"maintenance", "unknown"} else fallback_submode
    if mode == "maintenance":
        mode = "unknown"
    if mode == "query" and submode not in {"entity", "scene", "context"}:
        submode = "unknown" if external_primary and query_kind not in QUERY_KIND_SET else query_submode_from_candidate(candidate, fallback_submode)
    options = query_options_from_candidate(candidate) if mode == "query" else {}
    default_confirmation = "intent route decision requires clarification" if external_primary else "intent consensus requires clarification"
    confirmations = decision.disagreements or (default_confirmation,)
    errors = confirmations if decision.status == "blocked" else ()
    clarification = None if decision.status == "blocked" else clarification_from_consensus_decision(decision)
    plan = (
        candidate_plan_steps(candidate)
        if candidate
        and candidate.kind == "composite"
        and decision.status != "blocked"
        and decision_plan_validated(decision)
        else ()
    )
    plan_confirmation_ready = decision_plan_confirmation_ready(decision)
    consensus_trace = decision.decision_trace.get("consensus", {}) if isinstance(decision.decision_trace, dict) else {}
    consensus_reason = str(consensus_trace.get("reason") or "") if isinstance(consensus_trace, dict) else ""
    external_safety_block = external_primary and consensus_reason in {
        "external safety blocker",
        "kernel safety guard",
    }
    return ConsensusRouteAdoption(
        outcome=RouteOutcome(
            mode=mode,
            submode=submode,
            action=None,
            options=options,
            kind="composite" if plan and plan_confirmation_ready else "unresolved",
            status="blocked" if decision.status == "blocked" else "needs_confirmation",
            missing_required=clarification.missing_slots if clarification else (),
            needs_confirmation=() if decision.status == "blocked" else confirmations,
            errors=errors,
            player_message=(
                "意图路由未通过，需要玩家确认。"
                if external_primary and decision.status != "blocked"
                else "意图安全检查阻止了这个请求。"
                if external_safety_block
                else "外部意图候选未通过内核校验，请修正候选字段或重新描述。"
                if external_primary
                else "AI 意图共识未通过，需要玩家确认。"
                if decision.status != "blocked"
                else "AI 意图安全检查阻止了这个请求。"
            ),
            source=decision.source,
            confidence="low",
            plan=plan,
            clarification=clarification,
        )
    )


def route_outcome_from_consensus_decision(
    decision: ConsensusDecision,
    *,
    fallback_submode: str,
) -> ConsensusRouteAdoption | None:
    """Compatibility alias for callers using the former consensus-only name."""
    return route_outcome_from_intent_decision(decision, fallback_submode=fallback_submode)


def candidate_plan_steps(candidate: Any) -> tuple[PlanStep, ...]:
    plan = candidate.plan if candidate and isinstance(candidate.plan, tuple) else ()
    return tuple(
        PlanStep(
            step_id=f"intent-step:{index}",
            action=step.action,
            label=step.action,
            status="needs_confirmation",
            options=dict(step.slots),
        )
        for index, step in enumerate(plan, start=1)
    )


def query_submode_from_candidate(candidate: Any, fallback_submode: str) -> str:
    slots = candidate.slots if candidate and isinstance(candidate.slots, dict) else {}
    for key in ("query_kind", "kind", "submode"):
        text = str(slots.get(key) or "").strip().lower()
        if text in QUERY_KIND_SET:
            return text
    fallback = str(fallback_submode or "").strip().lower()
    if fallback in QUERY_KIND_SET:
        return fallback
    return "entity"


def query_options_from_candidate(candidate: Any) -> dict[str, Any]:
    slots = candidate.slots if candidate and isinstance(candidate.slots, dict) else {}
    text = str(slots.get("query_text") or slots.get("query") or slots.get("target") or "").strip()
    return {"query_text": text} if text else {}


def clarification_from_consensus_decision(decision: ConsensusDecision) -> ClarificationQuestion | None:
    if decision.status == "blocked":
        return None
    disagreements = tuple(str(item) for item in decision.disagreements if str(item).strip())
    trace = decision.decision_trace if isinstance(decision.decision_trace, dict) else {}
    missing_slots = bound_missing_slots(decision)
    reason = clarification_reason(decision, disagreements, missing_slots)
    choices = clarification_choices(trace)
    question = clarification_question_text(reason, missing_slots, choices)
    return ClarificationQuestion(
        clarification_id=clarification_id_from_consensus_decision(decision, reason, missing_slots, choices),
        reason=reason,
        question=question,
        choices=choices,
        disagreements=disagreements,
        missing_slots=missing_slots,
        suggested_next_tool="confirm_plan" if decision_plan_confirmation_ready(decision) else "ask_clarification",
    )


def decision_plan_confirmation_ready(decision: ConsensusDecision) -> bool:
    trace = decision.decision_trace if isinstance(decision.decision_trace, dict) else {}
    consensus = trace.get("consensus") if isinstance(trace, dict) else None
    return bool(
        isinstance(consensus, dict)
        and consensus.get("plan_validated") is True
        and consensus.get("plan_confirmation_ready") is True
    )


def decision_plan_validated(decision: ConsensusDecision) -> bool:
    trace = decision.decision_trace if isinstance(decision.decision_trace, dict) else {}
    consensus = trace.get("consensus") if isinstance(trace, dict) else None
    return bool(isinstance(consensus, dict) and consensus.get("plan_validated") is True)


def clarification_reason(
    decision: ConsensusDecision,
    disagreements: tuple[str, ...],
    missing_slots: tuple[str, ...],
) -> str:
    joined = " | ".join(disagreements)
    if "mode mismatch" in joined:
        return "external_internal_mode_mismatch"
    if "action mismatch" in joined or "bound action mismatch" in joined:
        return "external_internal_action_mismatch"
    if "kind mismatch" in joined:
        return "external_internal_kind_mismatch"
    if missing_slots:
        return "missing_slots"
    if "slot mismatch" in joined or "slot binding mismatch" in joined:
        return "external_internal_slot_mismatch"
    if decision.source == "ai_consensus_unbound":
        return "binding_unresolved"
    if decision.source == "ai_single_source_internal":
        return "single_source_internal"
    return "intent_consensus_clarify"


def clarification_question_text(
    reason: str,
    missing_slots: tuple[str, ...],
    choices: tuple[ClarificationChoice, ...],
) -> str:
    if reason == "external_internal_mode_mismatch":
        return "我需要确认这句话是要执行游戏行动，还是只读取/维护信息？"
    if reason == "external_internal_action_mismatch":
        return "我需要确认你想按哪类行动结算。"
    if reason in {"external_internal_slot_mismatch", "binding_unresolved"}:
        return "我需要确认这次行动的目标对象或关键参数。"
    if reason == "external_internal_kind_mismatch":
        return "我需要确认这是单步行动，还是需要先拆成多个步骤。"
    if reason == "missing_slots":
        missing = "、".join(missing_slots) if missing_slots else "关键行动信息"
        return f"我还需要补充 {missing}，才能可靠结算这次行动。"
    if reason == "single_source_internal":
        return "内部 AI 给出了一个意图，但缺少外部 AI 候选，请确认是否按这个意图继续。"
    if choices:
        return "AI 意图判断需要玩家确认，请选择更符合你原意的一项。"
    return "AI 意图判断需要玩家确认，请补充你的真实意图。"


def clarification_id_from_consensus_decision(
    decision: ConsensusDecision,
    reason: str,
    missing_slots: tuple[str, ...],
    choices: tuple[ClarificationChoice, ...],
) -> str:
    candidate = decision.candidate.to_dict() if decision.candidate else None
    payload = {
        "source": decision.source,
        "status": decision.status,
        "reason": reason,
        "candidate": candidate,
        "disagreements": list(decision.disagreements),
        "missing_slots": list(missing_slots),
        "choices": [choice.to_dict() for choice in choices],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"clarification:{digest}"


def bound_missing_slots(decision: ConsensusDecision) -> tuple[str, ...]:
    values: list[str] = []
    if decision.bound is not None:
        values.extend(decision.bound.missing_required)
    if decision.candidate is not None:
        values.extend(decision.candidate.missing_slots)
    for key in ("internal_binding", "external_binding"):
        binding = decision.decision_trace.get(key) if isinstance(decision.decision_trace, dict) else None
        if isinstance(binding, dict):
            values.extend(str(item) for item in binding.get("missing_required", []) if str(item).strip())
    return tuple(dict.fromkeys(str(item) for item in values if str(item).strip()))


def clarification_choices(trace: dict[str, Any]) -> tuple[ClarificationChoice, ...]:
    choices: list[ClarificationChoice] = []
    for key, label_prefix in (("external_candidate", "外部判断"), ("internal_candidate", "内部复核")):
        candidate = trace.get(key)
        if not isinstance(candidate, dict):
            continue
        choice = choice_from_candidate(key, label_prefix, candidate)
        if choice is not None:
            choices.append(choice)
    return tuple(choices)


def choice_from_candidate(
    key: str,
    label_prefix: str,
    candidate: dict[str, Any],
) -> ClarificationChoice | None:
    mode = str(candidate.get("mode") or "").strip()
    action = str(candidate.get("action") or "").strip() or None
    slots = candidate.get("slots") if isinstance(candidate.get("slots"), dict) else {}
    confidence = str(candidate.get("confidence") or "unknown")
    reason = str(candidate.get("reason") or "")
    if not mode and not action and not slots:
        return None
    target = action or mode or "unknown"
    slot_text = format_slots(slots)
    label = f"{label_prefix}: {target}" + (f" ({slot_text})" if slot_text else "")
    return ClarificationChoice(
        id=key,
        label=label,
        source=str(candidate.get("source") or key),
        mode=mode,
        action=action,
        slots=dict(slots),
        confidence=confidence,
        reason=reason,
    )


def format_slots(slots: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(slots):
        value = slots[key]
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
        if len(parts) >= 3:
            break
    return "，".join(parts)
