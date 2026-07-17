from __future__ import annotations

import re
import sqlite3
import unicodedata
from types import SimpleNamespace
from typing import Any

from ..actions import ActionResolverRegistry, get_default_action_registry
from ..actions.base import ActionResolverSpec
from ..actions.slot_contract import ActionSlotSpec
from ..db import (
    _is_default_ignorable_query_character,
    entity_subtype_visibility_sql,
    player_candidate_matches_redacted_text,
    player_query_contains_hidden_ref,
    query_tokens,
    resolve_entity_exact_token,
    sanitize_fts_query,
    should_search_body,
    world_setting_entity_join_and_clause,
)
from ..visibility import (
    EDGE_WHITESPACE_CHARS,
    PLAYER_VIEW,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_status_sql,
    entity_visibility_sql,
    normalize_visibility_label,
    normalize_visibility_view,
)
from .normalization import normalize_intent_candidate
from .types import BoundIntent, IntentCandidate


DICE_EXPR_RE = re.compile(r"^(?:[1-9][0-9]*)?d[1-9][0-9]*(?:[+-][0-9]+)?$", re.I)


def bind_intent_candidate(
    conn: sqlite3.Connection,
    candidate: IntentCandidate | dict[str, Any],
    *,
    registry: ActionResolverRegistry | None = None,
    view: str = PLAYER_VIEW,
) -> BoundIntent:
    normalized = (
        candidate
        if isinstance(candidate, IntentCandidate)
        else normalize_intent_candidate(candidate, registry=registry)
    )
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

    action_registry = registry if registry is not None else get_default_action_registry()
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

    contract = spec.slot_contract
    allowed_options = option_names(spec)
    options: dict[str, Any] = {"user_text": normalized.source_user_text}
    entity_bindings: dict[str, str] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    confirmations: list[str] = list(normalized.needs_confirmation)
    errors: list[str] = []
    warnings: list[str] = []
    slot_trace: dict[str, Any] = {}
    seen_raw_slots: dict[str, str] = {}

    for raw_name, raw_value in normalized.slots.items():
        slot = contract.normalize_name(raw_name)
        if slot not in allowed_options:
            warnings.append(f"ignored slot outside resolver contract: {raw_name}")
            slot_trace[raw_name] = {"status": "ignored", "reason": "outside resolver contract"}
            continue
        if slot == "user_text":
            continue
        previous_raw_name = seen_raw_slots.get(slot)
        if previous_raw_name is not None:
            errors.append(f"duplicate normalized slot: {slot}")
            trace_key = raw_name if raw_name not in slot_trace else f"{raw_name}#duplicate"
            slot_trace[trace_key] = {
                "status": "invalid",
                "reason": "duplicate_normalized_slot",
                "canonical_slot": slot,
                "first_raw_slot": previous_raw_name,
            }
            continue
        seen_raw_slots[slot] = raw_name
        slot_spec = contract.slot(slot)
        if not slot_spec.ai_fillable:
            if slot_spec.player_confirmation_required:
                warnings.append(f"ignored AI-supplied safety confirmation slot: {slot}")
                confirmations.append(f"{slot} requires direct player confirmation")
                reason = "safety_critical_confirmation"
            else:
                warnings.append(f"ignored AI-supplied non-fillable slot: {slot}")
                reason = "not_ai_fillable"
            slot_trace[slot] = {"status": "ignored", "reason": reason}
            continue
        bound = bind_slot_value(conn, slot_spec, raw_value, view=view)
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
            if bound["trace"].get("reason") == "invalid_unicode":
                errors.append(f"{slot} contains invalid Unicode")
            else:
                errors.append(f"{slot} is invalid: {raw_value}")

    requirement_evaluation = contract.evaluate_requirements(options)
    confirmation_only_missing = {
        slot.name
        for slot in contract.slots
        if slot.required
        and slot.player_confirmation_required
        and not options.get(slot.name)
    }
    confirmation_only_groups = {
        " or ".join(group.members): group
        for group in contract.requirement_groups
        if group.required
        and all(
            contract.slot(member).player_confirmation_required
            for member in group.members
        )
    }
    confirmations.extend(
        f"{name} requires direct player confirmation"
        for name in sorted(confirmation_only_missing)
    )
    confirmations.extend(
        f"{group.name} requires direct player confirmation: one of {', '.join(group.members)}"
        for label, group in sorted(confirmation_only_groups.items())
        if label in requirement_evaluation.missing
        or not any(options.get(member) for member in group.members)
    )
    missing.extend(
        item
        for item in requirement_evaluation.missing
        if item not in confirmation_only_missing
        and item not in confirmation_only_groups
    )
    errors.extend(requirement_evaluation.errors)
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
    slot: ActionSlotSpec,
    value: Any,
    *,
    view: str,
) -> dict[str, Any]:
    if value is None or value == "":
        return {"status": "missing", "trace": {"status": "missing"}}
    slot_type = slot.binding_type
    if slot_type == "text_list":
        text = text_list_value(value)
        return {"status": "text", "value": text, "trace": {"status": "text", "value": text}}
    if slot_type == "dice_expr":
        text = text_value(value)
        status = "text" if DICE_EXPR_RE.match(text) else "invalid"
        return {"status": status, "value": text, "trace": {"status": status, "value": text}}
    if slot_type in {"text", "random_table_id"}:
        text = text_value(value)
        return {"status": "text", "value": text, "trace": {"status": "text", "value": text}}

    allowed_types = allowed_entity_types(slot)
    if allowed_types is None:
        text = text_value(value)
        return {"status": "text", "value": text, "trace": {"status": "text", "value": text}}

    text = text_value(value)
    if _contains_unicode_surrogate(text):
        return {
            "status": "invalid",
            "trace": {"status": "invalid", "reason": "invalid_unicode"},
        }
    if not _normalize_candidate_match_text(text):
        return {
            "status": "missing",
            "trace": {"status": "missing", "input": text, "reason": "normalized_empty"},
        }
    candidates, matched_non_active = find_bindable_entity_candidates(
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
    if matched_non_active:
        return {
            "status": "missing",
            "trace": {"status": "missing", "input": text, "allowed_types": sorted(allowed_types)},
        }
    if slot_type in {"entity_or_text", "text_or_entity"}:
        return {"status": "text", "value": text, "trace": {"status": "text", "input": text, "reason": "no entity match"}}
    return {"status": "missing", "trace": {"status": "missing", "input": text, "allowed_types": sorted(allowed_types)}}


def option_names(spec: ActionResolverSpec) -> set[str]:
    return {slot.name for slot in spec.slot_contract.slots}


def normalize_slot_name(
    action: str,
    name: str,
    *,
    registry: ActionResolverRegistry | None = None,
) -> str:
    action_registry = registry if registry is not None else get_default_action_registry()
    spec = action_registry.get(action)
    if spec is None:
        return str(name or "").strip()
    return spec.slot_contract.normalize_name(name)


def allowed_entity_types(slot: ActionSlotSpec) -> set[str] | None:
    if slot.binding_type in {"entity", "entity_or_text", "text_or_entity"}:
        return set(slot.allowed_entity_types)
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
    exact = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="exact",
        status_predicate=entity_not_archived_sql("e"),
        limit=limit,
    )
    if exact:
        return list(exact)
    if exact_only:
        return []
    partial = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="partial",
        status_predicate=entity_not_archived_sql("e"),
        limit=limit,
    )
    return list(partial)


def find_bindable_entity_candidates(
    conn: sqlite3.Connection,
    text: str,
    *,
    allowed_types: set[str] | None,
    view: str = PLAYER_VIEW,
    exact_only: bool = False,
    limit: int = 5,
) -> tuple[list[sqlite3.Row], bool]:
    text = str(text or "").strip()
    if not text or not _normalize_candidate_match_text(text) or not has_table(conn, "entities"):
        return [], False
    ensure_visibility_sql_functions(conn)
    view = normalize_visibility_view(view)
    active_predicate = f"{entity_status_sql('e')} = 'active'"
    non_active_predicate = f"{entity_status_sql('e')} != 'active'"

    exact_active = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="exact",
        status_predicate=active_predicate,
        limit=limit,
        normalize_match=True,
    )
    if exact_active:
        return list(exact_active), False
    exact_non_active = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="exact",
        status_predicate=non_active_predicate,
        limit=1,
        normalize_match=True,
    )
    if exact_non_active:
        return [], True

    # A longer hybrid phrase can contain a canonical non-active reference even
    # when another active row happens to match the whole phrase partially.
    # Active exact remains authoritative, but non-active canonical references
    # must shadow every lower-priority partial/literal path.
    contained_non_active = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="contained",
        status_predicate=non_active_predicate,
        limit=1,
        normalize_match=True,
    )
    if contained_non_active:
        return [], True

    partial_non_active = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="partial",
        status_predicate=non_active_predicate,
        limit=1,
        normalize_match=True,
    )
    if partial_non_active:
        return [], True
    if not exact_only:
        contained_active_ids = _query_entity_candidates(
            conn,
            text,
            allowed_types=allowed_types,
            view=view,
            match="contained_id",
            status_predicate=active_predicate,
            limit=limit,
            normalize_match=True,
        )
        if contained_active_ids:
            return list(contained_active_ids), False
    partial_active = _query_entity_candidates(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        match="partial",
        status_predicate=active_predicate,
        limit=limit,
        normalize_match=True,
    )
    if partial_active and not exact_only:
        return list(partial_active), False

    # Resolver owners may also use token, body, or FTS lookup after a hybrid
    # literal leaves the binder.  Mirror that final read only to reject a
    # caller-visible non-active result; active resolution keeps its established
    # downstream behavior and hidden rows remain indistinguishable from absent.
    if _has_non_active_resolver_shadow(
        conn,
        text,
        allowed_types=allowed_types,
        view=view,
        status_predicate=non_active_predicate,
    ):
        return [], True
    return [], False


def _has_non_active_resolver_shadow(
    conn: sqlite3.Connection,
    text: str,
    *,
    allowed_types: set[str] | None,
    view: str,
    status_predicate: str,
) -> bool:
    resolver_text = _normalize_candidate_resolver_text(text)
    if not resolver_text or player_query_contains_hidden_ref(conn, resolver_text, view=view):
        return False
    tokens = query_tokens(resolver_text)
    # Mirror the shared resolver's ordered exact-token stage.  Its first exact
    # winner returns immediately, so a later active token cannot hide an
    # earlier non-active ID-suffix/name/alias winner.
    for token in tokens:
        exact_winner = resolve_entity_exact_token(conn, token, view=view)
        if exact_winner is not None:
            return normalize_visibility_label(str(exact_winner["status"] or "")) != "active"
    for token in tokens:
        if _query_entity_candidates(
            conn,
            token,
            allowed_types=allowed_types,
            view=view,
            match="partial",
            status_predicate=status_predicate,
            limit=1,
            normalize_match=True,
        ):
            return True
    for term in (resolver_text, *tokens):
        if not should_search_body(term):
            continue
        rows = _query_entity_candidates(
            conn,
            term,
            allowed_types=allowed_types,
            view=view,
            match="body",
            status_predicate=status_predicate,
            limit=12,
        )
        if any(player_candidate_matches_redacted_text(conn, row, term, view=view) for row in rows):
            return True
    return bool(
        _query_non_active_fts_candidates(
            conn,
            resolver_text,
            allowed_types=allowed_types,
            view=view,
            status_predicate=status_predicate,
            limit=1,
        )
    )


def _query_entity_candidates(
    conn: sqlite3.Connection,
    text: str,
    *,
    allowed_types: set[str] | None,
    view: str,
    match: str,
    status_predicate: str,
    limit: int,
    normalize_match: bool = False,
) -> list[sqlite3.Row]:
    type_clause, type_params = type_filter_sql(allowed_types)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    match_text = _normalize_candidate_match_text(text) if normalize_match else text
    if normalize_match and not match_text:
        return []
    if normalize_match:
        conn.create_function(
            "nfkc_casefold_text",
            1,
            _normalize_candidate_match_text,
            deterministic=True,
        )
    if match == "exact":
        match_values = (match_text, match_text, match_text)
        match_sql = (
            "nfkc_casefold_text(e.id) = ? "
            "or nfkc_casefold_text(e.name) = ? "
            "or nfkc_casefold_text(a.alias) = ?"
            if normalize_match
            else "lower(e.id) = lower(?) or e.name = ? or a.alias = ?"
        )
        order_sql = "e.id"
    elif match == "partial":
        like = f"%{_escape_like_literal(match_text)}%"
        match_values = (like, like, like)
        match_sql = (
            "nfkc_casefold_text(e.id) like ? escape '!' "
            "or nfkc_casefold_text(e.name) like ? escape '!' "
            "or nfkc_casefold_text(a.alias) like ? escape '!'"
            if normalize_match
            else "lower(e.id) like lower(?) escape '!' "
            "or e.name like ? escape '!' "
            "or a.alias like ? escape '!'"
        )
        order_sql = "length(e.name), e.id"
    elif match == "contained":
        match_values = (match_text, match_text, match_text)
        match_sql = (
            "instr(?, nfkc_casefold_text(e.id)) > 0 "
            "or (e.name != '' and instr(?, nfkc_casefold_text(e.name)) > 0) "
            "or (a.alias != '' and instr(?, nfkc_casefold_text(a.alias)) > 0)"
            if normalize_match
            else "instr(lower(?), lower(e.id)) > 0 "
            "or (e.name != '' and instr(lower(?), lower(e.name)) > 0) "
            "or (a.alias != '' and instr(lower(?), lower(a.alias)) > 0)"
        )
        order_sql = "length(e.name) desc, e.id"
    elif match == "contained_id":
        match_values = (match_text,)
        match_sql = (
            "instr(?, nfkc_casefold_text(e.id)) > 0"
            if normalize_match
            else "instr(lower(?), lower(e.id)) > 0"
        )
        order_sql = "length(e.id) desc, e.id"
    elif match == "body":
        like = f"%{_escape_like_literal(match_text)}%"
        match_values = (like, like)
        match_sql = "e.summary like ? escape '!' or e.details_json like ? escape '!'"
        order_sql = "length(e.summary), e.id"
    else:
        raise ValueError("unsupported entity candidate match mode")
    rows = list(
        conn.execute(
            f"""
            select distinct e.*
            from entities e
            left join aliases a on a.entity_id = e.id
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where {status_predicate}
              {visibility_clause}
              {subtype_visibility_clause}
              {world_setting_visibility_clause}
              {type_clause}
              and ({match_sql})
            order by {order_sql}
            {'' if match in {'contained', 'contained_id'} else 'limit ?'}
            """,
            (
                *type_params,
                *match_values,
                *((limit,) if match not in {"contained", "contained_id"} else ()),
            ),
        ).fetchall()
    )
    if match == "contained_id":
        return [
            row
            for row in rows
            if _contains_canonical_reference(text, str(row["id"] or ""), qualified_id=True)
        ][:limit]
    if match == "contained":
        return [
            row
            for row in rows
            if _row_has_contained_canonical_reference(conn, row, text)
        ][:limit]
    return rows


def _query_non_active_fts_candidates(
    conn: sqlite3.Connection,
    text: str,
    *,
    allowed_types: set[str] | None,
    view: str,
    status_predicate: str,
    limit: int,
) -> list[sqlite3.Row]:
    safe_query = sanitize_fts_query(text)
    if not safe_query or not has_table(conn, "fts_index"):
        return []
    type_clause, type_params = type_filter_sql(allowed_types)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    return list(
        conn.execute(
            f"""
            select distinct e.*
            from fts_index f
            join entities e on e.id = f.entity_id
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where fts_index match ?
              and {status_predicate}
              {visibility_clause}
              {subtype_visibility_clause}
              {world_setting_visibility_clause}
              {type_clause}
            order by e.id
            limit ?
            """,
            (safe_query, *type_params, limit),
        ).fetchall()
    )


def _row_has_contained_canonical_reference(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    text: str,
) -> bool:
    if _contains_canonical_reference(text, str(row["id"] or ""), qualified_id=True):
        return True
    references = [str(row["name"] or "")]
    references.extend(
        str(alias_row["alias"] or "")
        for alias_row in conn.execute(
            "select alias from aliases where entity_id=? order by alias",
            (str(row["id"]),),
        )
    )
    return any(_contains_canonical_reference(text, reference) for reference in references)


def _contains_canonical_reference(
    text: str,
    reference: str,
    *,
    qualified_id: bool = False,
) -> bool:
    normalized_text = _normalize_candidate_match_text(text)
    normalized_reference = _normalize_candidate_match_text(reference)
    if not normalized_reference:
        return False
    if not qualified_id and _contains_non_latin_letter(normalized_reference):
        if _canonical_reference_codepoint_count(reference) < 2:
            return normalized_text == normalized_reference
        return normalized_reference in normalized_text
    for match in re.finditer(re.escape(normalized_reference), normalized_text):
        if _is_reference_continuation(
            normalized_text,
            match.start() - 1,
            direction=-1,
            qualified_id=qualified_id,
            reference=normalized_reference,
        ):
            continue
        if _is_reference_continuation(
            normalized_text,
            match.end(),
            direction=1,
            qualified_id=qualified_id,
            reference=normalized_reference,
        ):
            continue
        return True
    return False


def _is_reference_continuation(
    text: str,
    index: int,
    *,
    direction: int,
    qualified_id: bool,
    reference: str,
) -> bool:
    saw_format = False
    while 0 <= index < len(text):
        value = text[index]
        category = unicodedata.category(value)
        if category.startswith("M"):
            return True
        if category == "Cf":
            saw_format = True
            index += direction
            continue
        if _contains_non_latin_letter(value):
            return False
        continuation = r"[\w:.-]" if qualified_id else r"[\w:-]"
        if re.fullmatch(continuation, value) is None:
            return False
        adjacent_script = _unicode_script_group(value)
        reference_script = _reference_edge_script(reference, direction=direction)
        return not adjacent_script or not reference_script or adjacent_script == reference_script
    return saw_format


def _reference_edge_script(reference: str, *, direction: int) -> str:
    values = reference if direction < 0 else reversed(reference)
    for value in values:
        script = _unicode_script_group(value)
        if script:
            return script
    return ""


def _unicode_script_group(value: str) -> str:
    if not value or not unicodedata.category(value).startswith("L"):
        return ""
    return unicodedata.name(value, "").partition(" ")[0]


def _contains_non_latin_letter(value: str) -> bool:
    return any(
        unicodedata.category(char).startswith("L") and _unicode_script_group(char) != "LATIN"
        for char in value
    )


def _canonical_reference_codepoint_count(value: str) -> int:
    normalized = unicodedata.normalize("NFKD", str(value or "")).strip(EDGE_WHITESPACE_CHARS).casefold()
    return sum(1 for char in normalized if not _is_default_ignorable_match_character(char))


def _contains_unicode_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _normalize_candidate_match_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).strip(EDGE_WHITESPACE_CHARS).casefold()
    return "".join(
        char
        for char in normalized
        if not unicodedata.category(char).startswith("M") and not _is_default_ignorable_match_character(char)
    )


def _normalize_candidate_resolver_text(value: Any) -> str:
    return _normalize_candidate_match_text(value)


def _is_default_ignorable_match_character(value: str) -> bool:
    return _is_default_ignorable_query_character(value)


def _escape_like_literal(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def type_filter_sql(allowed_types: set[str] | None) -> tuple[str, tuple[str, ...]]:
    if not allowed_types:
        return "", ()
    values = tuple(sorted(allowed_types))
    placeholders = ", ".join("?" for _ in values)
    return f"and e.type in ({placeholders})", values


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute("select 1 from sqlite_master where type = 'table' and name = ?", (name,)).fetchone())


def required_missing(spec: ActionResolverSpec, options: dict[str, Any]) -> list[str]:
    return list(spec.slot_contract.evaluate_requirements(options).missing)


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
