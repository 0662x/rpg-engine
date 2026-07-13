from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .safety_contract import SAFETY_FLAG_VALUES
from .types import BoundIntent, IntentCandidate, RouteOutcome


GREEN = "green"
YELLOW_FAST = "yellow_fast"
YELLOW_CONSENSUS = "yellow_consensus"
RED = "red"

ACTION_BASE_RISK = {
    "routine": YELLOW_FAST,
    "rest": YELLOW_FAST,
    "travel": YELLOW_FAST,
    "explore": YELLOW_FAST,
    "gather": YELLOW_CONSENSUS,
    "craft": YELLOW_CONSENSUS,
    "social": YELLOW_CONSENSUS,
    "random_table": YELLOW_CONSENSUS,
    "combat": RED,
}

BLOCKING_SAFETY_FLAGS = SAFETY_FLAG_VALUES


@dataclass(frozen=True)
class IntentRiskDecision:
    risk: str
    allow_rules_fallback: bool
    reason: str
    action: str | None = None
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk": self.risk,
            "allow_rules_fallback": self.allow_rules_fallback,
            "reason": self.reason,
            "action": self.action,
            "flags": list(self.flags),
        }


def assess_rules_fallback(
    candidate: IntentCandidate | None,
    *,
    external_candidate: IntentCandidate | None = None,
    bound: BoundIntent | None = None,
    rules_outcome: RouteOutcome | None = None,
) -> IntentRiskDecision:
    if candidate is None:
        return IntentRiskDecision(RED, False, "missing rules candidate")

    flags = tuple(sorted(BLOCKING_SAFETY_FLAGS.intersection(candidate.safety_flags)))
    if external_candidate is not None:
        flags = tuple(sorted(set(flags).union(BLOCKING_SAFETY_FLAGS.intersection(external_candidate.safety_flags))))
    if flags:
        return IntentRiskDecision(RED, False, "safety flag requires internal review", candidate.action, flags)

    if candidate.mode == "query":
        return IntentRiskDecision(GREEN, True, "read-only query can use deterministic fallback", candidate.action)
    if candidate.mode == "maintenance":
        return IntentRiskDecision(RED, False, "maintenance requires trusted internal review", candidate.action)
    if candidate.mode != "action":
        return IntentRiskDecision(YELLOW_CONSENSUS, False, "unknown mode requires clarification", candidate.action)
    if candidate.kind == "composite":
        return IntentRiskDecision(YELLOW_CONSENSUS, False, "composite plan requires confirmation", candidate.action)

    action = candidate.action
    base = ACTION_BASE_RISK.get(action or "", YELLOW_CONSENSUS)
    if base == RED:
        return IntentRiskDecision(RED, False, f"{action} is high risk", action)
    if base != YELLOW_FAST:
        return IntentRiskDecision(base, False, f"{action} requires external/internal consensus", action)

    if external_candidate is not None:
        if external_candidate.mode != candidate.mode:
            return IntentRiskDecision(YELLOW_CONSENSUS, False, "external/rules mode mismatch", action)
        if external_candidate.mode == "action" and external_candidate.action != candidate.action:
            return IntentRiskDecision(YELLOW_CONSENSUS, False, "external/rules action mismatch", action)
        if external_candidate.kind == "composite":
            return IntentRiskDecision(YELLOW_CONSENSUS, False, "external candidate is composite", action)

    if bound is not None and bound.binding_status != "bound":
        return IntentRiskDecision(YELLOW_CONSENSUS, False, f"binding is {bound.binding_status}", action)

    if candidate.missing_slots or candidate.needs_confirmation:
        return IntentRiskDecision(YELLOW_CONSENSUS, False, "candidate needs clarification", action)

    if rules_outcome is not None:
        if rules_outcome.mode != candidate.mode:
            return IntentRiskDecision(YELLOW_CONSENSUS, False, "rules outcome/candidate mode mismatch", action)
        if candidate.mode == "action" and rules_outcome.action != candidate.action:
            return IntentRiskDecision(YELLOW_CONSENSUS, False, "rules outcome/candidate action mismatch", action)
        if rules_outcome.status != "ready":
            return IntentRiskDecision(YELLOW_CONSENSUS, False, f"rules outcome is {rules_outcome.status}", action)
        if rules_outcome.missing_required or rules_outcome.needs_confirmation or rules_outcome.errors:
            return IntentRiskDecision(YELLOW_CONSENSUS, False, "rules outcome is incomplete", action)

    return IntentRiskDecision(YELLOW_FAST, True, f"{action} is eligible for fast fallback", action)
