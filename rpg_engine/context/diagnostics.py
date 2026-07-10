from __future__ import annotations

from typing import Any, Callable, Iterable

from .sections import ContextSection
from ..visibility import can_read_hidden


HIGH_VALUE_PRIORITY = 70
HIGH_VALUE_SIGNAL_LIMIT = 8
QUALITY_DIAGNOSTIC_LIMIT = 32
MAX_DIAGNOSTIC_INTEGER = (1 << 53) - 1
MAX_UTILIZATION = 1_000_000.0
MAX_DIAGNOSTIC_SUBJECTS = 64


def build_budget_evidence(
    *,
    sections: Iterable[ContextSection],
    selected: Iterable[ContextSection],
    omitted: Iterable[ContextSection],
    limit: int,
    requested: int | None,
    campaign_default: int,
    policy_profile: str,
    policy_reason: str,
) -> dict[str, Any]:
    section_list = list(sections)
    selected_list = list(selected)
    omitted_list = list(omitted)
    selected_keys = {section.key for section in selected_list}
    raw_limit = _unbounded_nonnegative_int(limit)
    effective_limit = _bounded_nonnegative_int(raw_limit)
    raw_included_tokens = _unbounded_nonnegative_sum(
        section.estimated_tokens for section in selected_list
    )
    raw_required_tokens = _unbounded_nonnegative_sum(
        section.estimated_tokens for section in section_list if section.required
    )
    included_tokens = _bounded_nonnegative_int(raw_included_tokens)
    required_tokens = _bounded_nonnegative_int(raw_required_tokens)
    overflow_tokens = _bounded_nonnegative_int(
        max(0, raw_included_tokens - raw_limit)
    )
    required_overflow_tokens = _bounded_nonnegative_int(
        max(0, raw_required_tokens - raw_limit)
    )
    utilization = _bounded_utilization(raw_included_tokens, raw_limit)

    decisions = [
        {
            "section": section.key,
            "required": bool(section.required),
            "priority": _bounded_nonnegative_int(section.priority),
            "estimated_tokens": _bounded_nonnegative_int(section.estimated_tokens),
            "included": section.key in selected_keys,
            "reason": _section_decision_reason(section, section.key in selected_keys),
            "reason_code": _section_decision_reason_code(
                section,
                section.key in selected_keys,
            ),
        }
        for section in section_list
    ]

    return {
        "limit": effective_limit,
        "requested": _optional_bounded_signed_integer(requested),
        "campaign_default": _bounded_nonnegative_int(campaign_default),
        "policy_profile": str(policy_profile),
        "policy_reason": str(policy_reason),
        "estimated": included_tokens,
        "required_tokens": required_tokens,
        "sections": {
            section.key: _bounded_nonnegative_int(section.estimated_tokens)
            for section in selected_list
        },
        "included_sections": [section.key for section in selected_list],
        "omitted_sections": [section.key for section in omitted_list],
        "decisions": decisions,
        "trimmed": any(
            decision.get("reason_code") == "over_budget"
            for decision in decisions
        ),
        "over_limit": raw_included_tokens > raw_limit,
        "overflow_tokens": overflow_tokens,
        "required_over_limit": raw_required_tokens > raw_limit,
        "required_overflow_tokens": required_overflow_tokens,
        "utilization": utilization,
    }


def high_value_missing_signals(
    *,
    budget: dict[str, Any],
    omitted_items: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    required_signal: dict[str, Any] | None = None
    if budget.get("required_over_limit") is True:
        required_signal = {
            "code": "required_budget_overflow",
            "signal": "required_sections",
            "source": "context_budget",
            "severity": "advisory",
            "priority": 100,
            "reason_code": "required_budget_overflow",
            "reason": "required context exceeds the effective budget limit",
            "budget": {
                "limit": _bounded_nonnegative_int(budget.get("limit")),
                "required_tokens": _bounded_nonnegative_int(
                    budget.get("required_tokens")
                ),
                "overflow_tokens": _bounded_nonnegative_int(
                    budget.get("required_overflow_tokens")
                ),
            },
        }

    candidates: list[dict[str, Any]] = []
    for item in omitted_items:
        if not isinstance(item, dict):
            continue
        item_budget = item.get("budget")
        item_budget = item_budget if isinstance(item_budget, dict) else {}
        reason_code = _bounded_text(
            item_budget.get("reason_code"),
            80,
        ).lower()
        if item_budget.get("included") is not False or reason_code != "over_budget":
            continue
        priority_value = item_budget.get("priority")
        if priority_value is None:
            priority_value = item.get("priority", 0)
        priority = _bounded_nonnegative_int(priority_value)
        if priority < HIGH_VALUE_PRIORITY:
            continue
        signal = _bounded_text(item.get("id"), 160)
        source = _bounded_text(item.get("source"), 80)
        if not signal or not source:
            continue
        candidates.append(
            {
                "code": "high_value_budget_omission",
                "signal": signal,
                "source": source,
                "severity": "advisory",
                "priority": priority,
                "reason_code": reason_code,
                "reason": "high-value context evidence omitted by token budget",
                "budget": {
                    "included": False,
                    "priority": priority,
                    "estimated_tokens": _optional_bounded_integer(
                        item_budget.get(
                            "estimated_tokens",
                            item.get("estimated_tokens"),
                        )
                    ),
                    "reason": reason_code,
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            -_bounded_nonnegative_int(item.get("priority")),
            str(item.get("source", "")),
            str(item.get("signal", "")),
            str(item.get("code", "")),
        )
    )
    ordinary: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in candidates:
        key = (
            str(item["code"]),
            str(item["source"]),
            str(item["signal"]),
        )
        if key in seen:
            continue
        seen.add(key)
        ordinary.append(item)
        if len(ordinary) >= HIGH_VALUE_SIGNAL_LIMIT:
            break
    if required_signal is not None:
        ordinary = ordinary[: HIGH_VALUE_SIGNAL_LIMIT - 1]
        ordinary.append(required_signal)
        ordinary.sort(
            key=lambda item: (
                -_bounded_nonnegative_int(item.get("priority")),
                str(item.get("source", "")),
                str(item.get("signal", "")),
                str(item.get("code", "")),
            )
        )
    return ordinary[:HIGH_VALUE_SIGNAL_LIMIT]


def build_quality_diagnostics(
    *,
    state: Any,
    budget: dict[str, Any],
    loaded_items: Iterable[dict[str, Any]],
    omitted_items: Iterable[dict[str, Any]],
    context_view: str,
) -> list[dict[str, Any]]:
    loaded_list = [item for item in loaded_items if isinstance(item, dict)]
    omitted_list = [item for item in omitted_items if isinstance(item, dict)]
    warnings: list[dict[str, Any]] = []
    collectors: list[tuple[str, Callable[[], Iterable[dict[str, Any]]]]] = [
        ("entity_resolution", lambda: _entity_quality_warnings(state, context_view)),
        ("world_settings", lambda: _world_setting_quality_warnings(state, context_view)),
        ("relationships", lambda: _relationship_quality_warnings(state, context_view)),
        ("progress_context", lambda: _progress_quality_warnings(state, context_view)),
        (
            "memory_summaries",
            lambda: _memory_quality_warnings(
                [*loaded_list, *omitted_list], context_view
            ),
        ),
        ("context_budget", lambda: _budget_quality_warnings(budget, context_view)),
    ]
    for source, collector in collectors:
        try:
            warnings.extend(collector())
        except Exception:
            warnings.append(
                _quality_warning(
                    code="quality_diagnostics_unavailable",
                    source=source,
                    subject_kind="context",
                    subject_id=source,
                    missing_fields=["diagnostic_evidence"],
                    reason=f"{source} diagnostics are unavailable",
                    context_view=context_view,
                    severity="error",
                )
            )
    return _normalize_quality_warnings(warnings)


def _entity_quality_warnings(state: Any, context_view: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    hits_by_id: dict[str, Any] = {}
    for hit in getattr(state, "entity_hits", []) or []:
        entity_id = _bounded_text(getattr(hit, "id", None), 160)
        if entity_id and entity_id not in hits_by_id:
            hits_by_id[entity_id] = hit
        if len(hits_by_id) >= MAX_DIAGNOSTIC_SUBJECTS:
            break
    for entity_id, hit in hits_by_id.items():
        if not _has_text(getattr(hit, "summary", None)):
            warnings.append(
                _quality_warning(
                    code="missing_summary",
                    source="entity_resolution",
                    subject_kind=_bounded_text(getattr(hit, "type", None), 80) or "entity",
                    subject_id=entity_id,
                    missing_fields=["summary"],
                    reason="relevant entity is missing a structured summary",
                    context_view=context_view,
                )
            )
    alias_ids, aliases_available = _entity_ids_with_aliases(
        getattr(state, "conn", None),
        list(hits_by_id),
    )
    if not aliases_available and hits_by_id:
        warnings.append(
            _quality_warning(
                code="quality_diagnostics_unavailable",
                source="aliases",
                subject_kind="context",
                subject_id="aliases",
                missing_fields=["aliases"],
                reason="alias diagnostics are unavailable",
                context_view=context_view,
            )
        )
    elif aliases_available:
        for entity_id, hit in hits_by_id.items():
            if entity_id in alias_ids:
                continue
            warnings.append(
                _quality_warning(
                    code="missing_aliases",
                    source="aliases",
                    subject_kind=_bounded_text(getattr(hit, "type", None), 80) or "entity",
                    subject_id=entity_id,
                    missing_fields=["aliases"],
                    reason="relevant entity has no lookup aliases",
                    context_view=context_view,
                )
            )
    if getattr(state, "semantic_alias_gaps", None):
        warnings.append(
            _quality_warning(
                code="missing_aliases",
                source="semantic_resolution",
                subject_kind="context",
                subject_id="semantic_alias_gap",
                missing_fields=["aliases"],
                reason="a semantic entity label could not be resolved through available aliases",
                context_view=context_view,
            )
        )
    return warnings


def _world_setting_quality_warnings(state: Any, context_view: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in (getattr(state, "world_settings", []) or [])[:MAX_DIAGNOSTIC_SUBJECTS]:
        if not isinstance(item, dict):
            continue
        row = item.get("row")
        setting_id = _bounded_text(_row_value(row, "entity_id"), 160)
        if not setting_id:
            continue
        if not _has_text(_row_value(row, "entity_summary")):
            warnings.append(
                _quality_warning(
                    code="missing_summary",
                    source="world_settings",
                    subject_kind="world_setting",
                    subject_id=setting_id,
                    missing_fields=["summary"],
                    reason="relevant world setting is missing a structured summary",
                    context_view=context_view,
                )
            )
    return warnings


def _relationship_quality_warnings(state: Any, context_view: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in (getattr(state, "relationships", []) or [])[:MAX_DIAGNOSTIC_SUBJECTS]:
        record = item.get("record") if isinstance(item, dict) else None
        relationship_id = _bounded_text(getattr(record, "id", None), 160)
        if not relationship_id:
            continue
        if not _has_text(getattr(record, "summary", None)):
            warnings.append(
                _quality_warning(
                    code="missing_summary",
                    source="relationships",
                    subject_kind="relationship",
                    subject_id=relationship_id,
                    missing_fields=["summary"],
                    reason="relevant relationship is missing a structured summary",
                    context_view=context_view,
                )
            )
        endpoint_issues = tuple(getattr(record, "endpoint_issues", ()) or ())
        if endpoint_issues:
            fields = _relationship_issue_fields(endpoint_issues)
            warnings.append(
                _quality_warning(
                    code="missing_endpoint_reference",
                    source="relationships",
                    subject_kind="relationship",
                    subject_id=relationship_id,
                    missing_fields=fields,
                    reason="relationship endpoint reference is missing or unavailable",
                    context_view=context_view,
                )
            )
    for item in (getattr(state, "relationship_omissions", []) or [])[:MAX_DIAGNOSTIC_SUBJECTS]:
        if not isinstance(item, dict) or item.get("reason_code") != "missing_reference":
            continue
        relationship_id = _bounded_text(item.get("id"), 160)
        if relationship_id:
            warnings.append(
                _quality_warning(
                    code="missing_endpoint_reference",
                    source="relationships",
                    subject_kind="relationship",
                    subject_id=relationship_id,
                    missing_fields=["endpoint_reference"],
                    reason="relationship endpoint reference is missing or unavailable",
                    context_view=context_view,
                )
            )
    return warnings


def _progress_quality_warnings(state: Any, context_view: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in (getattr(state, "progress_context", []) or [])[:MAX_DIAGNOSTIC_SUBJECTS]:
        record = item.get("record") if isinstance(item, dict) else None
        progress_id = _bounded_text(getattr(record, "id", None), 160)
        if not progress_id:
            continue
        if not _has_text(getattr(record, "summary", None)):
            warnings.append(
                _quality_warning(
                    code="missing_summary",
                    source="progress_context",
                    subject_kind="progress",
                    subject_id=progress_id,
                    missing_fields=["summary"],
                    reason="relevant progress track is missing a structured summary",
                    context_view=context_view,
                )
            )
        missing_fields: list[str] = []
        if _is_empty(getattr(record, "scope", None)):
            missing_fields.append("scope")
        if not _has_text(getattr(record, "clock_type", None)) and not _has_text(
            getattr(record, "kind", None)
        ):
            missing_fields.append("clock_type")
        total = _plain_integer(getattr(record, "segments_total", None))
        filled = _plain_integer(getattr(record, "segments_filled", None))
        if total is None or total <= 0:
            missing_fields.append("segments_total")
        if filled is None or filled < 0 or (total is not None and total > 0 and filled > total):
            missing_fields.append("segments_filled")
        if not _has_tick_rule_metadata(getattr(record, "tick_rules", None)) and not _has_text(
            getattr(record, "trigger_when_full", None)
        ):
            missing_fields.append("tick_rules_or_trigger_when_full")
        if missing_fields:
            warnings.append(
                _quality_warning(
                    code="missing_progress_metadata",
                    source="progress_context",
                    subject_kind="progress",
                    subject_id=progress_id,
                    missing_fields=missing_fields,
                    reason="relevant progress track is missing structured progress metadata",
                    context_view=context_view,
                )
            )
    for item in (getattr(state, "progress_omissions", []) or [])[:MAX_DIAGNOSTIC_SUBJECTS]:
        if not isinstance(item, dict):
            continue
        reason_code = item.get("reason_code")
        if reason_code not in {"missing_reference", "conflict"}:
            continue
        progress_id = _bounded_text(item.get("id"), 160)
        if progress_id:
            missing_fields = (
                ["scope_reference"]
                if reason_code == "missing_reference"
                else ["segments_or_status"]
            )
            warnings.append(
                _quality_warning(
                    code="missing_progress_metadata",
                    source="progress_context",
                    subject_kind="progress",
                    subject_id=progress_id,
                    missing_fields=missing_fields,
                    reason=(
                        "progress metadata contains a missing reference"
                        if reason_code == "missing_reference"
                        else "progress segments or status are structurally inconsistent"
                    ),
                    context_view=context_view,
                )
            )
    return warnings


def _memory_quality_warnings(
    omitted_items: Iterable[dict[str, Any]],
    context_view: str,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for item in omitted_items:
        if (
            not isinstance(item, dict)
            or item.get("source") != "memory_summaries"
            or item.get("kind") != "memory"
        ):
            continue
        freshness = item.get("freshness")
        freshness = freshness if isinstance(freshness, dict) else {}
        status = _bounded_text(freshness.get("status"), 40).lower()
        if status == "fresh":
            continue
        memory_id = _bounded_text(item.get("id"), 160) or "memory_summaries"
        warnings.append(
            _quality_warning(
                code="stale_summary_evidence",
                source="memory_summaries",
                subject_kind="memory",
                subject_id=memory_id,
                missing_fields=["freshness_evidence"],
                reason="memory summary freshness evidence is stale, unavailable, or unverifiable",
                context_view=context_view,
            )
        )
        if len(warnings) >= MAX_DIAGNOSTIC_SUBJECTS:
            break
    return warnings


def _budget_quality_warnings(
    budget: dict[str, Any],
    context_view: str,
) -> list[dict[str, Any]]:
    decisions = budget.get("decisions")
    if not isinstance(decisions, list):
        return []
    warnings: list[dict[str, Any]] = []
    effective_limit = _bounded_nonnegative_int(budget.get("limit"))
    included_optional_priorities = [
        _bounded_nonnegative_int(item.get("priority"))
        for item in decisions
        if isinstance(item, dict) and item.get("included") is True and item.get("required") is not True
    ]
    lowest_included_priority = min(included_optional_priorities) if included_optional_priorities else None
    for item in decisions[:MAX_DIAGNOSTIC_SUBJECTS]:
        if not isinstance(item, dict):
            continue
        section = _bounded_text(item.get("section"), 160)
        if not section:
            continue
        estimated = _bounded_nonnegative_int(item.get("estimated_tokens"))
        priority = _bounded_nonnegative_int(item.get("priority"))
        if effective_limit > 0 and estimated > effective_limit:
            warnings.append(
                _quality_warning(
                    code="oversized_context_section",
                    source="context_budget",
                    subject_kind="section",
                    subject_id=section,
                    missing_fields=["budget_fit"],
                    reason="context section exceeds the effective token budget",
                    context_view=context_view,
                )
            )
        if (
            item.get("included") is False
            and item.get("required") is not True
            and item.get("reason_code") == "over_budget"
            and lowest_included_priority is not None
            and priority > lowest_included_priority
        ):
            warnings.append(
                _quality_warning(
                    code="low_value_budget_tradeoff",
                    source="context_budget",
                    subject_kind="section",
                    subject_id=section,
                    missing_fields=["priority_budget_tradeoff"],
                    reason="higher-priority context was omitted while lower-priority context was included",
                    context_view=context_view,
                )
            )
    return warnings


def _normalize_quality_warnings(warnings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, tuple[str, ...]]] = set()
    for item in sorted(
        warnings,
        key=lambda warning: (
            str(warning.get("severity", "")),
            str(warning.get("code", "")),
            str(warning.get("source", "")),
            str(warning.get("subject_id", "")),
            tuple(warning.get("missing_fields", [])),
        ),
    ):
        key = (
            str(item.get("code", "")),
            str(item.get("source", "")),
            str(item.get("subject_kind", "")),
            str(item.get("subject_id", "")),
            tuple(str(value) for value in item.get("missing_fields", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= QUALITY_DIAGNOSTIC_LIMIT:
            break
    return unique


def _quality_warning(
    *,
    code: str,
    source: str,
    subject_kind: str,
    subject_id: str,
    missing_fields: Iterable[str],
    reason: str,
    context_view: str,
    severity: str = "warning",
) -> dict[str, Any]:
    safe_source = _bounded_text(source, 80) or "context"
    return {
        "code": _bounded_text(code, 80),
        "severity": _bounded_text(severity, 40) or "warning",
        "source": safe_source,
        "subject_kind": _bounded_text(subject_kind, 80) or "context",
        "subject_id": _bounded_text(subject_id, 160) or safe_source,
        "missing_fields": sorted(
            {
                field
                for value in missing_fields
                if (field := _bounded_text(value, 80))
            }
        ),
        "reason": _bounded_text(reason, 240),
        "visibility": {
            "mode": _bounded_text(context_view, 40),
            "hidden_allowed": can_read_hidden(context_view),
        },
        "provenance": {
            "diagnostic": "context_quality",
            "source": safe_source,
        },
        "advisory_only": True,
    }


def _entity_ids_with_aliases(conn: Any, entity_ids: list[str]) -> tuple[set[str], bool]:
    if conn is None or not entity_ids:
        return set(), False
    try:
        table = conn.execute(
            "select 1 from main.sqlite_master where type='table' and name='aliases'"
        ).fetchone()
        if not table:
            return set(), False
        placeholders = ",".join("?" for _ in entity_ids)
        rows = conn.execute(
            f"select entity_id, alias from main.aliases where entity_id in ({placeholders})",
            entity_ids,
        ).fetchall()
    except Exception:
        return set(), False
    return {
        entity_id
        for row in rows
        if (entity_id := _bounded_text(_row_value(row, "entity_id", index=0), 160))
        and _has_text(_row_value(row, "alias", index=1))
    }, True


def _relationship_issue_fields(issues: Iterable[Any]) -> list[str]:
    fields: set[str] = set()
    for issue in issues:
        text = str(issue)
        if text.startswith("source_id"):
            fields.add("source_id")
        elif text.startswith("target_id"):
            fields.add("target_id")
        else:
            fields.add("endpoint_reference")
    return sorted(fields) or ["endpoint_reference"]


def _row_value(row: Any, key: str, *, index: int | None = None) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        if index is None:
            return None
        try:
            return row[index]
        except (IndexError, KeyError, TypeError):
            return None


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return not value
    return False


def _has_tick_rule_metadata(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(
        str(key).strip().lower() != "scope" and not _is_empty(item)
        for key, item in value.items()
    )


def _plain_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _section_decision_reason(section: ContextSection, included: bool) -> str:
    if included and section.required:
        return "required"
    if included:
        return "selected by priority within token budget"
    return str(section.omitted_reason or "token budget")


def _section_decision_reason_code(section: ContextSection, included: bool) -> str:
    if included and section.required:
        return "required"
    if included:
        return "selected"
    if section.omitted_reason in {None, "token budget", "source section omitted by token budget"}:
        return "over_budget"
    return "unavailable"


def _unbounded_nonnegative_sum(values: Iterable[Any]) -> int:
    total = 0
    for value in values:
        total += _unbounded_nonnegative_int(value)
    return total


def _unbounded_nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, result)


def _bounded_nonnegative_int(value: Any) -> int:
    return min(MAX_DIAGNOSTIC_INTEGER, _unbounded_nonnegative_int(value))


def _bounded_utilization(included_tokens: int, limit: int) -> float:
    if limit <= 0:
        return 0.0
    if included_tokens >= limit * int(MAX_UTILIZATION):
        return MAX_UTILIZATION
    return round(included_tokens / limit, 6)


def _optional_bounded_integer(value: Any) -> int | None:
    if value is None:
        return None
    return _bounded_nonnegative_int(value)


def _optional_bounded_signed_integer(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 0
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(-MAX_DIAGNOSTIC_INTEGER, min(MAX_DIAGNOSTIC_INTEGER, result))


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text[:limit]
