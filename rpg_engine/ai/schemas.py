from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..context.rendering import trim_inline


@dataclass(frozen=True)
class SemanticSuggestion:
    mode: str = "unknown"
    submode: str = "unknown"
    targets: list[str] = field(default_factory=list)
    entities_mentioned: list[str] = field(default_factory=list)
    missing_confirmations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: str = "low"


@dataclass(frozen=True)
class ReflectionAIOutput:
    title: str
    summary: str
    key_points: list[str]
    source_event_ids: list[str]


@dataclass(frozen=True)
class ArchivistSuggestion:
    turn_summary: str = ""
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    entity_alias_suggestions: list[dict[str, Any]] = field(default_factory=list)
    unresolved_leads: list[dict[str, Any]] = field(default_factory=list)
    possible_contradictions: list[dict[str, Any]] = field(default_factory=list)
    next_context_hints: list[str] = field(default_factory=list)
    review_required: list[dict[str, Any]] = field(default_factory=list)
    advisory: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_summary": self.turn_summary,
            "memory_candidates": self.memory_candidates,
            "entity_alias_suggestions": self.entity_alias_suggestions,
            "unresolved_leads": self.unresolved_leads,
            "possible_contradictions": self.possible_contradictions,
            "next_context_hints": self.next_context_hints,
            "review_required": self.review_required,
            "advisory": self.advisory,
        }


@dataclass(frozen=True)
class StateAuditResult:
    ok: bool = True
    risk: str = "low"
    findings: list[dict[str, Any]] = field(default_factory=list)
    missing_structured_changes: list[dict[str, Any]] = field(default_factory=list)
    requires_human_review: bool = False
    ai_status: str = "off"
    warnings: list[str] = field(default_factory=list)
    advisory: bool = True
    no_direct_writes: bool = True
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "risk": self.risk,
            "findings": self.findings,
            "missing_structured_changes": self.missing_structured_changes,
            "requires_human_review": self.requires_human_review,
            "ai_status": self.ai_status,
            "warnings": self.warnings,
            "advisory": self.advisory,
            "no_direct_writes": self.no_direct_writes,
            "audit": self.audit,
        }


def normalize_string_list(value: Any, *, limit: int, item_limit: int = 80) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = trim_inline(str(item).strip(), item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_object_list(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append({str(key): scalar_or_short_json(value) for key, value in item.items()})
        if len(result) >= limit:
            break
    return result


def scalar_or_short_json(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return trim_inline(value, 240) if isinstance(value, str) else value
    return trim_inline(str(value), 240)


def normalize_archivist_suggestion(value: dict[str, Any]) -> ArchivistSuggestion:
    return ArchivistSuggestion(
        turn_summary=trim_inline(str(value.get("turn_summary") or ""), 320),
        memory_candidates=normalize_object_list(value.get("memory_candidates"), limit=8),
        entity_alias_suggestions=normalize_object_list(value.get("entity_alias_suggestions"), limit=8),
        unresolved_leads=normalize_object_list(value.get("unresolved_leads"), limit=8),
        possible_contradictions=normalize_object_list(value.get("possible_contradictions"), limit=6),
        next_context_hints=normalize_string_list(value.get("next_context_hints"), limit=8, item_limit=160),
        review_required=normalize_object_list(value.get("review_required"), limit=8),
        advisory=True,
    )


def normalize_risk(value: Any) -> str:
    text = str(value or "low").strip().lower()
    return text if text in {"low", "medium", "high"} else "low"


def normalize_state_audit_result(value: dict[str, Any]) -> StateAuditResult:
    risk = normalize_risk(value.get("risk"))
    findings = normalize_object_list(value.get("findings"), limit=12)
    missing = normalize_object_list(value.get("missing_structured_changes"), limit=12)
    requires_review = bool(value.get("requires_human_review", risk == "high"))
    ok_value = value.get("ok")
    ok = bool(ok_value) if isinstance(ok_value, bool) else not (risk == "high" or requires_review)
    return StateAuditResult(
        ok=ok,
        risk=risk,
        findings=findings,
        missing_structured_changes=missing,
        requires_human_review=requires_review,
        ai_status=trim_inline(str(value.get("ai_status") or "off"), 40),
        warnings=normalize_string_list(value.get("warnings"), limit=8, item_limit=180),
        advisory=True,
        no_direct_writes=True,
        audit=value.get("audit") if isinstance(value.get("audit"), dict) else {},
    )
