from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .actions import get_default_action_registry
from .actions.base import ActionResolverRegistry, ActionValidationResult, ResolutionResult
from .campaign import Campaign
from .delta_schema import validate_delta_schema
from .intent_router import (
    ActionIntent,
    TurnContract,
    action_intent_from_dict,
    action_intent_to_dict,
    turn_contract_from_dict,
    turn_contract_to_dict,
)


ALLOWED_TURN_PROPOSAL_KEYS = {
    "proposal_id",
    "intent",
    "context_id",
    "preview",
    "response_text",
    "facts_used",
    "narrative_claims",
    "delta",
    "delta_source",
    "provenance",
    "human_confirmed",
    "turn_contract",
}

DELTA_SOURCES = {
    "resolver_proposed",
    "ai_generated",
    "human_edited",
    "response_draft",
    "maintenance_delta",
}


@dataclass(frozen=True)
class TurnProposal:
    proposal_id: str
    intent: ActionIntent
    context_id: str | None = None
    preview: dict[str, Any] | None = None
    response_text: str | None = None
    delta: dict[str, Any] | None = None
    delta_source: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    human_confirmed: bool = False
    facts_used: tuple[str, ...] = field(default_factory=tuple)
    narrative_claims: tuple[str, ...] = field(default_factory=tuple)
    turn_contract: TurnContract | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "intent": action_intent_to_dict(self.intent),
            "context_id": self.context_id,
            "preview": self.preview,
            "response_text": self.response_text,
            "delta": self.delta,
            "delta_source": self.delta_source,
            "provenance": self.provenance,
            "human_confirmed": self.human_confirmed,
            "facts_used": list(self.facts_used),
            "narrative_claims": list(self.narrative_claims),
            "turn_contract": turn_contract_to_dict(self.turn_contract),
        }


@dataclass(frozen=True)
class ApprovedOutcome:
    status: str
    proposal: TurnProposal
    facts_used: tuple[str, ...] = field(default_factory=tuple)
    rules_applied: tuple[str, ...] = field(default_factory=tuple)
    delta: dict[str, Any] | None = None
    confirmations: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    narrative_constraints: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "approved"

    def render(self) -> str:
        lines = [
            "# Proposal Validation",
            "",
            f"- status: `{self.status}`",
            f"- action: `{self.proposal.intent.action or ''}`",
        ]
        lines.append(f"- proposal_id: `{self.proposal.proposal_id}`")
        lines.append(f"- delta_source: `{self.proposal.delta_source}`")
        lines.append(f"- human_confirmed: `{'yes' if self.proposal.human_confirmed else 'no'}`")
        if self.facts_used:
            lines.append("- facts_used: `" + "`, `".join(self.facts_used) + "`")
        if self.rules_applied:
            lines.append("- rules_applied: `" + "`, `".join(self.rules_applied) + "`")
        for item in self.confirmations:
            lines.append(f"- confirmation: {item}")
        for item in self.warnings:
            lines.append(f"- warning: {item}")
        for item in self.errors:
            lines.append(f"- error: {item}")
        for item in self.narrative_constraints:
            lines.append(f"- narrative_constraint: {item}")
        if self.delta is not None:
            lines.extend(
                [
                    "",
                    "## Approved Delta",
                    "",
                    "```json",
                    json.dumps(self.delta, ensure_ascii=False, indent=2, sort_keys=True),
                    "```",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"


def load_json_payload(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def load_turn_proposal(path: str | Path) -> TurnProposal:
    return turn_proposal_from_dict(load_json_payload(path))


def turn_proposal_from_dict(data: dict[str, Any]) -> TurnProposal:
    errors: list[str] = []
    unknown = sorted(set(data) - ALLOWED_TURN_PROPOSAL_KEYS)
    errors.extend(f"$.{key}: unknown TurnProposal field" for key in unknown)

    proposal_id = data.get("proposal_id")
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        errors.append("$.proposal_id: required non-empty string")

    intent_data = data.get("intent")
    intent: ActionIntent | None = None
    if not isinstance(intent_data, dict):
        errors.append("$.intent: required object")
    else:
        try:
            intent = action_intent_from_dict(intent_data)
        except Exception as exc:
            errors.append(f"$.intent: {exc}")

    context_id = data.get("context_id")
    if context_id is not None and not isinstance(context_id, str):
        errors.append("$.context_id: must be string")
        context_id = None

    preview = data.get("preview")
    if preview is not None and not isinstance(preview, dict):
        errors.append("$.preview: must be object")
        preview = None

    response_text = data.get("response_text")
    if response_text is not None and not isinstance(response_text, str):
        errors.append("$.response_text: must be string")
        response_text = None

    delta = data.get("delta")
    if not isinstance(delta, dict):
        errors.append("$.delta: required object")
        delta = None

    delta_source = data.get("delta_source")
    if not isinstance(delta_source, str) or not delta_source.strip():
        errors.append("$.delta_source: required string")
        delta_source = ""

    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("$.provenance: required object")
        provenance = {}

    human_confirmed_raw = data.get("human_confirmed")
    if not isinstance(human_confirmed_raw, bool):
        errors.append("$.human_confirmed: required boolean")
        human_confirmed = False
    else:
        human_confirmed = human_confirmed_raw

    facts_used = validate_string_list(data.get("facts_used", []), "$.facts_used", errors)
    narrative_claims = validate_string_list(data.get("narrative_claims", []), "$.narrative_claims", errors)

    contract_data = data.get("turn_contract")
    turn_contract: TurnContract | None = None
    if not isinstance(contract_data, dict):
        errors.append("$.turn_contract: required object")
    else:
        try:
            turn_contract = turn_contract_from_dict(contract_data)
        except Exception as exc:
            errors.append(f"$.turn_contract: {exc}")

    if errors:
        raise ValueError("Invalid TurnProposal:\n" + "\n".join(f"- {error}" for error in errors))

    assert intent is not None
    assert delta is not None
    assert turn_contract is not None
    return TurnProposal(
        proposal_id=proposal_id.strip(),
        intent=intent,
        context_id=context_id,
        preview=preview,
        response_text=response_text,
        delta=delta,
        delta_source=delta_source.strip(),
        provenance=dict(provenance),
        human_confirmed=human_confirmed,
        facts_used=facts_used,
        narrative_claims=narrative_claims,
        turn_contract=turn_contract,
    )


def load_proposal(path: str | Path) -> dict[str, Any]:
    return load_json_payload(path)


def validate_turn_proposal(
    campaign: Campaign,
    conn: sqlite3.Connection,
    proposal: TurnProposal,
    *,
    response_text: str | None = None,
    registry: ActionResolverRegistry | None = None,
) -> ApprovedOutcome:
    registry = registry or get_default_action_registry()
    errors: list[str] = []
    warnings: list[str] = []
    confirmations: list[str] = []

    if not isinstance(proposal, TurnProposal):
        raise TypeError("validate_turn_proposal requires a TurnProposal")

    validate_delta_source(proposal, errors, confirmations)
    validate_contract_matches_intent(proposal, errors)
    validate_context_id_matches_intent(conn, proposal, errors)

    action = proposal.intent.action or ""
    if not action:
        errors.append("$.action: required")
        return rejected(proposal, errors=errors, warnings=warnings)
    spec = registry.get(action)
    if spec is None:
        errors.append(f"$.action: unknown action resolver {action}")
        return rejected(proposal, errors=errors, warnings=warnings)

    confidence = parse_intent_confidence(proposal.intent.confidence, warnings)
    if confidence is not None and confidence < 0.5:
        confirmations.append("proposal confidence is below approval threshold")

    options = SimpleNamespace(**proposal.intent.options)

    request = spec.request_contract(campaign, conn, {}, options)
    resolution = spec.resolve_contract(campaign, conn, {}, options)
    collect_request_result(request, errors, warnings, confirmations)
    collect_resolution_result(resolution, warnings, confirmations)

    effective_response_text = response_text if response_text is not None else proposal.response_text
    warnings.extend(validate_claims_against_response(proposal.narrative_claims, effective_response_text))

    approved_delta = proposal.delta

    delta_errors = validate_delta_schema(approved_delta, conn)
    errors.extend(f"delta: {item}" for item in delta_errors)
    delta_contract = spec.delta_contract(campaign, conn, {}, options, approved_delta)
    collect_delta_result(delta_contract, errors, warnings, confirmations)

    if resolution.status == "blocked":
        errors.append("resolver status is blocked")
    elif resolution.status != "ready":
        confirmations.append(f"resolver status is {resolution.status}")

    status = outcome_status(errors, confirmations)
    facts = tuple(dict.fromkeys([*proposal.facts_used, *resolution.facts_used]))
    return ApprovedOutcome(
        status=status,
        proposal=proposal,
        facts_used=facts,
        rules_applied=tuple(dict.fromkeys(resolution.rules_applied)),
        delta=approved_delta,
        confirmations=tuple(dict.fromkeys(confirmations)),
        warnings=tuple(dict.fromkeys(warnings)),
        errors=tuple(dict.fromkeys(errors)),
        narrative_constraints=tuple(dict.fromkeys(resolution.narrative_constraints)),
    )


def validate_delta_source(proposal: TurnProposal, errors: list[str], confirmations: list[str]) -> None:
    if proposal.delta_source not in DELTA_SOURCES:
        errors.append(f"$.delta_source: unsupported delta source {proposal.delta_source}")
        return
    allowed_sources = proposal.turn_contract.allowed_delta_sources if proposal.turn_contract else ()
    if allowed_sources and proposal.delta_source not in allowed_sources:
        errors.append(
            "$.delta_source: "
            f"{proposal.delta_source} is not allowed by turn contract ({', '.join(allowed_sources)})"
        )
    if proposal.delta_source in {"ai_generated", "response_draft", "human_edited"} and not proposal.human_confirmed:
        confirmations.append(f"{proposal.delta_source} requires human confirmation before approval")


def validate_contract_matches_intent(proposal: TurnProposal, errors: list[str]) -> None:
    if proposal.turn_contract is None:
        errors.append("$.turn_contract: required")
        return
    contract_intent = proposal.turn_contract.intent
    if contract_intent.mode != proposal.intent.mode:
        errors.append("$.turn_contract.intent.mode: does not match proposal intent")
    if contract_intent.submode != proposal.intent.submode:
        errors.append("$.turn_contract.intent.submode: does not match proposal intent")
    if contract_intent.action != proposal.intent.action:
        errors.append("$.turn_contract.intent.action: does not match proposal intent")
    if proposal.turn_contract.validation_profile != "player_turn_commit" and proposal.delta_source != "maintenance_delta":
        errors.append("$.turn_contract.validation_profile: player turn proposal requires player_turn_commit")


def validate_context_id_matches_intent(
    conn: sqlite3.Connection,
    proposal: TurnProposal,
    errors: list[str],
) -> None:
    trace_preflight_status = preflight_status_from_intent(proposal.intent)
    trace_preflight_id = preflight_id_from_intent(proposal.intent)
    provenance_preflight_id = provenance_string(proposal, "preflight_id")
    if trace_preflight_id and provenance_preflight_id and trace_preflight_id != provenance_preflight_id:
        errors.append("$.provenance.preflight_id: does not match intent preflight id")
    if provenance_preflight_id and trace_preflight_status != "hit":
        errors.append("$.intent.decision_trace.intent_ai.preflight.status: must be hit when provenance.preflight_id is present")
    preflight_id = trace_preflight_id or provenance_preflight_id
    expected_from_trace = intent_context_id_from_intent(proposal.intent)
    provenance_context = provenance_string(proposal, "intent_context_id")
    if preflight_id:
        row = conn.execute(
            "select status, intent_context_id from intent_preflight_cache where id=?",
            (preflight_id,),
        ).fetchone()
        if row is None:
            errors.append("$.provenance.preflight_id: unknown preflight id")
            return
        if str(row["status"]) != "used":
            errors.append("$.provenance.preflight_id: cached preflight must be used after a hit")
        expected = str(row["intent_context_id"])
        if not expected_from_trace:
            errors.append("$.intent.decision_trace.intent_ai.preflight.record.identity.intent_context_id: required")
        elif expected_from_trace != expected:
            errors.append(
                "$.intent.decision_trace.intent_ai.preflight.record.identity.intent_context_id: "
                "does not match cached preflight context"
            )
        if not provenance_context:
            errors.append("$.provenance.intent_context_id: required when preflight_id is present")
        elif provenance_context != expected:
            errors.append("$.provenance.intent_context_id: does not match cached preflight context")
        if not proposal.context_id:
            errors.append("$.context_id: required when preflight_id is present")
        elif proposal.context_id != expected:
            errors.append("$.context_id: does not match cached preflight context")
        return
    if proposal.context_id or provenance_context:
        errors.append("$.context_id: preflight context requires provenance.preflight_id")
        return
    expected = expected_from_trace
    if not expected:
        return
    if not proposal.context_id:
        errors.append("$.context_id: required when intent was built from preflight context")
    elif proposal.context_id != expected:
        errors.append("$.context_id: does not match intent preflight context")
    if not provenance_context:
        errors.append("$.provenance.intent_context_id: required when intent was built from preflight context")
    elif provenance_context != expected:
        errors.append("$.provenance.intent_context_id: does not match intent preflight context")


def intent_context_id_from_intent(intent: ActionIntent | None) -> str | None:
    if intent is None or not isinstance(intent.decision_trace, dict):
        return None
    preflight = {}
    intent_ai = intent.decision_trace.get("intent_ai")
    if isinstance(intent_ai, dict):
        preflight = intent_ai.get("preflight") if isinstance(intent_ai.get("preflight"), dict) else {}
    if preflight and preflight.get("status") != "hit":
        return None
    record = preflight.get("record") if isinstance(preflight, dict) else None
    identity = record.get("identity") if isinstance(record, dict) else None
    value = identity.get("intent_context_id") if isinstance(identity, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    value = intent.decision_trace.get("intent_context_id")
    return value.strip() if isinstance(value, str) and value.strip() else None


def preflight_id_from_intent(intent: ActionIntent | None) -> str | None:
    if intent is None or not isinstance(intent.decision_trace, dict):
        return None
    intent_ai = intent.decision_trace.get("intent_ai")
    preflight = intent_ai.get("preflight") if isinstance(intent_ai, dict) else None
    if not isinstance(preflight, dict) or preflight.get("status") != "hit":
        return None
    record = preflight.get("record") if isinstance(preflight, dict) else None
    value = record.get("id") if isinstance(record, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def preflight_status_from_intent(intent: ActionIntent | None) -> str | None:
    if intent is None or not isinstance(intent.decision_trace, dict):
        return None
    intent_ai = intent.decision_trace.get("intent_ai")
    preflight = intent_ai.get("preflight") if isinstance(intent_ai, dict) else None
    status = preflight.get("status") if isinstance(preflight, dict) else None
    return status.strip() if isinstance(status, str) and status.strip() else None


def provenance_string(proposal: TurnProposal, key: str) -> str | None:
    value = proposal.provenance.get(key) if isinstance(proposal.provenance, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_intent_confidence(value: str, warnings: list[str]) -> float | None:
    if not value:
        return None
    if value in {"high", "explicit"}:
        return 1.0
    if value == "medium":
        return 0.7
    if value == "low":
        return 0.4
    try:
        confidence = float(value)
    except ValueError:
        warnings.append(f"intent confidence is non-numeric: {value}")
        return None
    if confidence < 0 or confidence > 1:
        warnings.append(f"intent confidence is outside 0..1: {value}")
        return None
    return confidence


def collect_request_result(
    result: ActionValidationResult,
    errors: list[str],
    warnings: list[str],
    confirmations: list[str],
) -> None:
    errors.extend(f"request: {item}" for item in result.errors)
    warnings.extend(f"request: {item}" for item in result.warnings)
    confirmations.extend(f"missing option: {item}" for item in result.missing_required)


def collect_resolution_result(
    result: ResolutionResult,
    warnings: list[str],
    confirmations: list[str],
) -> None:
    warnings.extend(f"resolution: {item}" for item in result.warnings)
    confirmations.extend(result.confirmations)


def collect_delta_result(
    result: ActionValidationResult,
    errors: list[str],
    warnings: list[str],
    confirmations: list[str],
) -> None:
    errors.extend(f"delta_contract: {item}" for item in result.errors)
    warnings.extend(f"delta_contract: {item}" for item in result.warnings)
    confirmations.extend(f"delta_contract missing: {item}" for item in result.missing_required)


def validate_string_list(value: Any, path: str, errors: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        errors.append(f"{path}: must be array")
        return ()
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{path}[{index}]: must be non-empty string")
            continue
        result.append(item.strip())
    return tuple(result)


def validate_claims_against_response(claims: tuple[str, ...], response_text: str | None) -> list[str]:
    if not claims:
        return []
    if response_text is None:
        return ["narrative claims were not checked because no response text was provided"]
    warnings: list[str] = []
    for claim in claims:
        if claim not in response_text:
            warnings.append(f"narrative claim not found in response text: {claim}")
    return warnings


def outcome_status(errors: list[str], confirmations: list[str]) -> str:
    if errors:
        return "rejected"
    if confirmations:
        return "needs_confirmation"
    return "approved"


def rejected(
    proposal: TurnProposal,
    *,
    errors: list[str],
    warnings: list[str],
) -> ApprovedOutcome:
    return ApprovedOutcome(
        status="rejected",
        proposal=proposal,
        errors=tuple(dict.fromkeys(errors)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
