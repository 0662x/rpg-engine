from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..ux import PlanStep, RepairOption, UxStatus


@dataclass(frozen=True)
class CandidateStep:
    action: str
    slots: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntentCandidate:
    source: str
    source_user_text: str
    kind: str
    mode: str
    action: str | None
    slots: dict[str, Any] = field(default_factory=dict)
    plan: tuple[CandidateStep, ...] = ()
    confidence: str = "low"
    missing_slots: tuple[str, ...] = ()
    needs_confirmation: tuple[str, ...] = ()
    safety_flags: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["plan"] = [step.to_dict() for step in self.plan]
        data["missing_slots"] = list(self.missing_slots)
        data["needs_confirmation"] = list(self.needs_confirmation)
        data["safety_flags"] = list(self.safety_flags)
        return data


@dataclass(frozen=True)
class InternalIntentReview(IntentCandidate):
    agreement_with_external: str = "no_external"
    disagreements: tuple[str, ...] = ()
    external_candidate_quality: str = "no_external"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["agreement_with_external"] = self.agreement_with_external
        data["disagreements"] = list(self.disagreements)
        data["external_candidate_quality"] = self.external_candidate_quality
        return data


@dataclass(frozen=True)
class BoundIntent:
    candidate: IntentCandidate
    action: str | None
    options: dict[str, Any]
    binding_status: str
    entity_bindings: dict[str, str] = field(default_factory=dict)
    missing_required: tuple[str, ...] = ()
    needs_confirmation: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    decision_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "action": self.action,
            "options": dict(self.options),
            "binding_status": self.binding_status,
            "entity_bindings": dict(self.entity_bindings),
            "missing_required": list(self.missing_required),
            "needs_confirmation": list(self.needs_confirmation),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "decision_trace": dict(self.decision_trace),
        }


@dataclass(frozen=True)
class ConsensusDecision:
    status: str
    source: str
    candidate: IntentCandidate | None
    bound: BoundIntent | None
    disagreements: tuple[str, ...] = ()
    decision_trace: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "bound": self.bound.to_dict() if self.bound else None,
            "disagreements": list(self.disagreements),
            "decision_trace": dict(self.decision_trace),
        }


@dataclass(frozen=True)
class ClarificationChoice:
    id: str
    label: str
    source: str = ""
    mode: str = ""
    action: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: str = "unknown"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "source": self.source,
            "mode": self.mode,
            "action": self.action,
            "slots": dict(self.slots),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ClarificationQuestion:
    reason: str
    question: str
    clarification_id: str = ""
    choices: tuple[ClarificationChoice, ...] = ()
    disagreements: tuple[str, ...] = ()
    missing_slots: tuple[str, ...] = ()
    suggested_next_tool: str = "ask_clarification"

    def to_dict(self) -> dict[str, Any]:
        return {
            "clarification_id": self.clarification_id,
            "reason": self.reason,
            "question": self.question,
            "choices": [choice.to_dict() for choice in self.choices],
            "disagreements": list(self.disagreements),
            "missing_slots": list(self.missing_slots),
            "suggested_next_tool": self.suggested_next_tool,
        }


@dataclass(frozen=True)
class RouteOutcome:
    mode: str
    submode: str
    action: str | None
    options: dict[str, Any] = field(default_factory=dict)
    kind: str = "single"
    status: UxStatus = "ready"
    missing_required: tuple[str, ...] = ()
    needs_confirmation: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    player_message: str = ""
    summary: str = ""
    source: str = "rules"
    confidence: str = "medium"
    plan: tuple[PlanStep, ...] = ()
    repair_options: tuple[RepairOption, ...] = ()
    clarification: ClarificationQuestion | None = None

    def final_trace(self) -> dict[str, Any]:
        trace = {
            "mode": self.mode,
            "submode": self.submode,
            "action": self.action,
            "source": self.source,
            "status": self.status,
        }
        if self.clarification is not None:
            trace["clarification"] = self.clarification.to_dict()
        return trace


@dataclass(frozen=True)
class ConsensusRouteAdoption:
    outcome: RouteOutcome
