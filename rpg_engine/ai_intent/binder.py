from __future__ import annotations

import re
import sqlite3
from types import SimpleNamespace
from typing import Any

from ..actions import ActionResolverRegistry, get_default_action_registry
from ..actions.base import ActionResolverSpec
from ..db import entity_subtype_visibility_sql
from ..visibility import (
    PLAYER_VIEW,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalize_visibility_view,
)
from .normalization import normalize_intent_candidate
from .slot_contract import (
    ACTION_REQUIRED_SLOTS,
    ACTION_SLOT_BINDINGS,
    AI_SUPPLIED_CONFIRMATION_SLOTS,
    ENTITY_SLOT_TYPES,
    SLOT_ALIASES,
    TEXT_SLOT_TYPES,
)
from .types import BoundIntent, IntentCandidate


DICE_EXPR_RE = re.compile(r"^(?:[1-9][0-9]*)?d[1-9][0-9]*(?:[+-][0-9]+)?$", re.I)


def bind_intent_candidate(
    conn: sqlite3.Connection,
    candidate: IntentCandidate | dict[str, Any],
    *,
    registry: ActionResolverRegistry | None = None,
    view: str = PLAYER_VIEW,
) -> BoundIntent:
    normalized = candidate if isinstance(candidate, IntentCandidate) else normalize_intent_candidate(candidate)
    if normalized.mode != "action":
        return BoundIntent(
            candidate=normalized,
            action=None,
            options={},
            binding_status="not_applicable",
            errors=(f"candidate mode {normalized.mode} is not actionable",),
            decision_trace={"binder": {"status": "not_applicable"}},
        )
    if not normalized.action:
        return BoundIntent(
            candidate=normalized,
            action=None,
            options={},
            binding_status="invalid",
            missing_required=("action",),
            errors=("action candidate is missing or not in the action registry",),
            decision_trace={"binder": {"status": "invalid"}},
        )

    action_registry = registry or get_default_action_registry()
    spec = action_registry.get(normalized.action)
    if not spec:
        return BoundIntent(
            candidate=normalized,
            action=normalized.action,
            options={},
            binding_status="invalid",
            missing_required=("action",),
            errors=(f"unknown action: {normalized.action}",),
            decision_trace={"binder": {"status": "invalid"}},
        )

    allowed_options = option_names(spec)
    slot_types = ACTION_SLOT_BINDINGS.get(spec.name, {})
    options: dict[str, Any] = {"user_text": normalized.source_user_text}
    entity_bindings: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    confirmations: list[str] = list(normalized.needs_confirmation)
    errors: list[str] = []
    warnings: list[str] = []
    slot_trace: dict[str, Any] = {}

    for raw_name, raw_value in normalized.slots.items():
        slot = normalize_slot_name(spec.name, raw_name)
        if slot not in allowed_options:
            warnings.append(f"ignored slot outside resolver contract: {raw_name}")
            slot_trace[raw_name] = {"status": "ignored", "reason": "outside resolver contract"}
            continue
        if slot == "user_text":
            continue
        if slot in AI_SUPPLIED_CONFIRMATION_SLOTS.get(spec.name, set()):
            warnings.append(f"ignored AI-supplied safety confirmation slot: {slot}")
            confirmations.append(f"{slot} requires direct player confirmation")
            slot_trace[slot] = {"status": "ignored", "reason": "safety_critical_confirmation"}
            continue
        slot_type = slot_types.get(slot, "text")
        bound = bind_slot_value(conn, slot, raw_value, slot_type, view=view)
        slot_trace[slot] = bound["trace"]
        if bound["status"] == "bound":
            options[slot] = bound["value"]
            if bound.get("entity_id"):
                entity_bindings[slot] = str(bound["entity_id"])
        elif bound["status"] == "text":
            options[slot] = bound["value"]
        elif bound["status"] == "ambiguous":
            ambiguous.append(slot)
            confirmations.append(f"{slot} is ambiguous: {raw_value}")
        elif bound["status"] == "missing":
            missing.append(slot)
            confirmations.append(f"{slot} could not be bound: {raw_value}")
        elif bound["status"] == "invalid":
            errors.append(f"{slot} is invalid: {raw_value}")

    missing.extend(required_missing(spec, options))
    missing = dedupe(missing)
    confirmations = dedupe(confirmations)
    errors = dedupe(errors)
    warnings = dedupe(warnings)
    status = binding_status(missing, ambiguous, confirmations, errors)

    return BoundIntent(
        candidate=normalized,
        action=spec.name,
        options=options,
        binding_status=status,
        entity_bindings=entity_bindings,
        missing_required=tuple(missing),
        needs_confirmation=tuple(confirmations),
        errors=tuple(errors),
        warnings=tuple(warnings),
        decision_trace={
            "binder": {
                "status": status,
                "action": spec.name,
                "slot_trace": slot_trace,
                "allowed_options": sorted(allowed_options),
            }
        },
    )


def bind_slot_value(
    conn: sqlite3.Connection,
    slot: str,
    value: Any,
    slot_type: Any,
    *,
    view: str,
) -> dict[str, Any]:
    if value is None or value == "":
        return {"status": "missing", "trace": {"status": "missing"}}
    if slot_type == "text_list":
        text = text_list_value(value)
        return {"status": "text", "value": text, "trace": {"status": "text", "value": text}}
    if slot_type == "dice_expr":
        text = text_value(value)
        status = "text" if DICE_EXPR_RE.match(text) else "invalid"
        return {"status": status, "value": text, "trace": {"status": status, "value": text}}
    if slot_type in TEXT_SLOT_TYPES:
        text = text_value(value)
        return {"status": "text", "value": text, "trace": {"status": "text", "value": text}}

    allowed_types = allowed_entity_types(slot_type)
    if allowed_types is None:
        text = text_value(value)
        return {"status": "text", "value": text, "trace": {"status": "text", "value": text}}

    text = text_value(value)
    candidates = find_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        exact_only=slot_type == "text_or_entity",
    )
    candidate_ids = tuple(str(row["id"]) for row in candidates)
    if len(candidates) == 1:
        row = candidates[0]
        return {
            "status": "bound",
            "value": str(row["id"]),
            "entity_id": str(row["id"]),
            "trace": {"status": "bound", "input": text, "entity_id": str(row["id"]), "entity_type": str(row["type"])},
        }
    if len(candidates) > 1:
        return {"status": "ambiguous", "trace": {"status": "ambiguous", "input": text, "candidates": list(candidate_ids)}}
    if slot_type in {"entity_or_text", "text_or_entity"}:
        return {"status": "text", "value": text, "trace": {"status": "text", "input": text, "reason": "no entity match"}}
    return {"status": "missing", "trace": {"status": "missing", "input": text, "allowed_types": sorted(allowed_types)}}


def option_names(spec: ActionResolverSpec) -> set[str]:
    names = {option.name for option in spec.option_specs}
    names.update(spec.required_options)
    names.add("user_text")
    return names


def normalize_slot_name(action: str, name: str) -> str:
    text = str(name or "").strip()
    return SLOT_ALIASES.get(action, {}).get(text, text)


def allowed_entity_types(slot_type: Any) -> set[str] | None:
    if isinstance(slot_type, tuple):
        return {str(item) for item in slot_type if str(item)}
    if slot_type in ENTITY_SLOT_TYPES:
        return set() if slot_type in {"entity_or_text", "text_or_entity"} else {str(slot_type)}
    if isinstance(slot_type, str) and slot_type not in TEXT_SLOT_TYPES:
        return {slot_type}
    return None


def find_entity_candidates(
    conn: sqlite3.Connection,
    text: str,
    *,
    allowed_types: set[str] | None,
    view: str = PLAYER_VIEW,
    exact_only: bool = False,
    limit: int = 5,
) -> list[sqlite3.Row]:
    text = str(text or "").strip()
    if not text or not has_table(conn, "entities"):
        return []
    ensure_visibility_sql_functions(conn)
    view = normalize_visibility_view(view)
    type_clause, type_params = type_filter_sql(allowed_types)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    exact = conn.execute(
        f"""
        select distinct e.*
        from entities e
        left join aliases a on a.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {type_clause}
          and (
            lower(e.id) = lower(?)
            or e.name = ?
            or a.alias = ?
          )
        order by e.id
        limit ?
        """,
        (*type_params, text, text, text, limit),
    ).fetchall()
    if exact:
        return list(exact)
    if exact_only:
        return []

    like = f"%{text}%"
    partial = conn.execute(
        f"""
        select distinct e.*
        from entities e
        left join aliases a on a.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {type_clause}
          and (
            lower(e.id) like lower(?)
            or e.name like ?
            or a.alias like ?
          )
        order by length(e.name), e.id
        limit ?
        """,
        (*type_params, like, like, like, limit),
    ).fetchall()
    return list(partial)


def type_filter_sql(allowed_types: set[str] | None) -> tuple[str, tuple[str, ...]]:
    if not allowed_types:
        return "", ()
    values = tuple(sorted(allowed_types))
    placeholders = ", ".join("?" for _ in values)
    return f"and e.type in ({placeholders})", values


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("select 1 from sqlite_master where type = 'table' and name = ?", (name,)).fetchone())


def required_missing(spec: ActionResolverSpec, options: dict[str, Any]) -> list[str]:
    required = list(spec.required_options)
    required.extend(ACTION_REQUIRED_SLOTS.get(spec.name, ()))
    if spec.name == "random_table":
        return [] if options.get("table") or options.get("dice") else ["table or dice"]
    if spec.name == "routine" and (options.get("task") or options.get("target") or options.get("user_text")):
        return []
    return [name for name in dedupe(required) if not options.get(name)]


def binding_status(
    missing: list[str],
    ambiguous: list[str],
    confirmations: list[str],
    errors: list[str],
) -> str:
    if errors:
        return "invalid"
    if ambiguous:
        return "ambiguous"
    if missing:
        return "missing"
    if confirmations:
        return "ambiguous"
    return "bound"


def text_value(value: Any) -> str:
    if isinstance(value, list):
        return text_list_value(value)
    return str(value or "").strip()


def text_list_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def options_namespace(bound: BoundIntent) -> SimpleNamespace:
    return SimpleNamespace(**bound.options)


def dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
