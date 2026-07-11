from __future__ import annotations

import hashlib
import json
from typing import Any

from .advisory import (
    ADVISORY_SCHEMA_VERSION,
    MAX_CONTAINER_ITEMS,
    AdvisoryAuthority,
    ResidentAIAdvisory,
    normalize_resident_ai_advisory,
)
from .provider import AIHelperResult
from .schemas import StateAuditResult


_CONFIDENCE_MAP = {"high": 0.9, "medium": 0.6, "low": 0.3}
_VISIBILITY_MODES = frozenset({"player", "gm", "maintenance"})
_MAX_TARGETS = 32
_MAX_INPUT_REFERENCES = MAX_CONTAINER_ITEMS
_MAX_REFERENCE_LENGTH = 160
_UNAVAILABLE_INTENT_STATUSES = frozenset({"off", "error", "timeout", "failed", "unavailable"})


def adapt_internal_intent_review_advisory(
    result: AIHelperResult,
    *,
    bound_target_ids: tuple[str, ...],
    visibility_mode: str,
) -> ResidentAIAdvisory | None:
    _validate_common_input(result, bound_target_ids, visibility_mode=visibility_mode)
    if type(result.task) is not str or result.task != "internal_intent_review":
        raise ValueError("$: invalid intent advisory source")
    if type(result.status) is not str:
        raise ValueError("$: invalid intent advisory source status")
    if result.status in _UNAVAILABLE_INTENT_STATUSES:
        return None
    if result.status != "ok":
        raise ValueError("$: invalid intent advisory source status")
    if result.parsed is None:
        return None
    if type(result.parsed) is not dict:
        raise ValueError("$: invalid intent advisory payload")
    confidence_label = _intent_confidence(result.parsed)
    if type(confidence_label) is not str or confidence_label not in _CONFIDENCE_MAP:
        raise ValueError("$: invalid intent advisory confidence")
    targets = _dedupe_references(bound_target_ids)
    if not targets:
        return None
    digest = _digest(
        {
            "adapter": "internal_intent_review",
            "confidence": confidence_label,
            "targets": targets,
            "visibility_mode": visibility_mode,
        }
    )
    return _normalize_adapter_value(
        advisory_type="intent_recognition",
        targets=targets,
        evidence=[
            {"kind": _evidence_kind(target_id), "ref_id": target_id, "as_of_turn_id": None}
            for target_id in targets
        ],
        confidence=_CONFIDENCE_MAP[confidence_label],
        visibility_mode=visibility_mode,
        source_assistant="internal_intent_review",
        trace_id=f"trace:intent-review:{digest}",
        source_id=f"candidate:intent-review:{digest}",
    )


def adapt_state_audit_progress_advisory(
    result: StateAuditResult,
    *,
    clock_ids: tuple[str, ...],
) -> ResidentAIAdvisory | None:
    if type(result) is not StateAuditResult:
        raise ValueError("$: invalid state audit advisory source")
    _validate_advisory_flags(result.advisory, result.no_direct_writes)
    clocks = _dedupe_references(clock_ids)
    if not clocks:
        return None
    if any(not clock_id.startswith("clock:") for clock_id in clocks):
        raise ValueError("$: invalid state audit progress reference")
    digest = _digest(
        {
            "adapter": "state_audit_progress",
            "targets": clocks,
            "visibility_mode": "maintenance",
        }
    )
    return _normalize_adapter_value(
        advisory_type="progress_management",
        targets=clocks,
        evidence=[{"kind": "progress", "ref_id": clock_id, "as_of_turn_id": None} for clock_id in clocks],
        confidence=0.5,
        visibility_mode="maintenance",
        source_assistant="state_audit",
        trace_id=f"trace:state-audit:{digest}",
        source_id=f"candidate:state-audit:{digest}",
    )


def matches_internal_intent_review_projection(
    advisory: Any,
    result: AIHelperResult,
    *,
    bound_target_ids: tuple[str, ...],
    visibility_mode: str,
) -> bool:
    if type(advisory) is not ResidentAIAdvisory:
        return False
    try:
        expected = adapt_internal_intent_review_advisory(
            result,
            bound_target_ids=bound_target_ids,
            visibility_mode=visibility_mode,
        )
        return type(expected) is ResidentAIAdvisory and advisory == expected
    except Exception:
        return False


def matches_state_audit_progress_projection(
    advisory: Any,
    result: StateAuditResult,
    *,
    clock_ids: tuple[str, ...],
) -> bool:
    if type(advisory) is not ResidentAIAdvisory:
        return False
    try:
        expected = adapt_state_audit_progress_advisory(result, clock_ids=clock_ids)
        return type(expected) is ResidentAIAdvisory and advisory == expected
    except Exception:
        return False


def _validate_common_input(
    result: Any,
    targets: Any,
    *,
    visibility_mode: Any,
) -> None:
    if type(result) is not AIHelperResult:
        raise ValueError("$: invalid intent advisory source")
    _validate_advisory_flags(result.advisory, result.no_direct_writes)
    if type(targets) is not tuple:
        raise ValueError("$: advisory targets must be an exact tuple")
    if type(visibility_mode) is not str or visibility_mode not in _VISIBILITY_MODES:
        raise ValueError("$: invalid advisory visibility mode")


def _validate_advisory_flags(advisory: Any, no_direct_writes: Any) -> None:
    if type(advisory) is not bool or advisory is not True:
        raise ValueError("$: invalid advisory source authority")
    if type(no_direct_writes) is not bool or no_direct_writes is not True:
        raise ValueError("$: invalid advisory source authority")


def _intent_confidence(parsed: dict[Any, Any]) -> Any:
    if len(parsed) > MAX_CONTAINER_ITEMS:
        raise ValueError("$: invalid intent advisory payload")
    found = False
    confidence: Any = None
    for key, value in parsed.items():
        if type(key) is not str:
            raise ValueError("$: invalid intent advisory payload")
        if key == "confidence":
            found = True
            confidence = value
    if not found:
        raise ValueError("$: invalid intent advisory confidence")
    return confidence


def _dedupe_references(values: Any) -> list[str]:
    if type(values) is not tuple:
        raise ValueError("$: advisory targets must be an exact tuple")
    if len(values) > _MAX_INPUT_REFERENCES:
        raise ValueError("$: advisory input exceeds traversal budget")
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if type(item) is not str or not item or len(item) > _MAX_REFERENCE_LENGTH:
            raise ValueError("$: invalid advisory target reference")
        try:
            item.encode("utf-8")
        except UnicodeError:
            raise ValueError("$: invalid advisory target reference") from None
        if item not in seen:
            if len(result) >= _MAX_TARGETS:
                raise ValueError("$: advisory targets exceed item budget")
            seen.add(item)
            result.append(item)
    return result


def _evidence_kind(ref_id: str) -> str:
    if ref_id.startswith("rel:"):
        return "relationship"
    if ref_id.startswith("clock:"):
        return "progress"
    if ref_id.startswith("rule:"):
        return "rule"
    if ref_id.startswith(("world:", "setting:")):
        return "world_setting"
    return "entity"


def _digest(payload: dict[str, Any]) -> str:
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def _normalize_adapter_value(
    *,
    advisory_type: str,
    targets: list[str],
    evidence: list[dict[str, Any]],
    confidence: float,
    visibility_mode: str,
    source_assistant: str,
    trace_id: str,
    source_id: str,
) -> ResidentAIAdvisory:
    return normalize_resident_ai_advisory(
        {
            "advisory_type": advisory_type,
            "target_ids": list(targets),
            "evidence": evidence,
            "confidence": confidence,
            "freshness": {"status": "unknown", "as_of_turn_id": None, "source_event_ids": []},
            "visibility_mode": visibility_mode,
            "source_assistant": source_assistant,
            "schema_version": ADVISORY_SCHEMA_VERSION,
            "proposed_next_workflow": "none",
            "provenance": {"trace_id": trace_id, "source_ids": [source_id]},
            "authority": AdvisoryAuthority().to_dict(),
        }
    )
