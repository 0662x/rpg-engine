from __future__ import annotations

import sqlite3
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, get_player_entity_id, resolve_entity
from ..render import parse_json
from ..preview import (
    build_combat_delta,
    current_location_row,
    decremented_quantity,
    entity_ref_label,
    item_row,
    preview_warnings,
    render_combat_preview,
    required_confirmations,
    suggested_clock_ticks,
)
from ..redaction import redact_hidden_entity_refs
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .taxonomy import ActionTaxonomySpec, taxonomy_terms


def preview_combat(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    del campaign, context
    return render_combat_preview(
        conn,
        target_query=option_value(options, "target"),
        weapon_query=option_value(options, "weapon"),
        ammo_query=option_value(options, "ammo"),
        distance=option_value(options, "distance"),
        ready_state=option_value(options, "ready_state"),
        user_text=option_value(options, "user_text"),
    )


def resolve_combat_inputs(conn: sqlite3.Connection, options: Any) -> dict[str, Any]:
    meta = get_meta(conn)
    target_query = option_value(options, "target")
    weapon_query = option_value(options, "weapon")
    ammo_query = option_value(options, "ammo")
    target = resolve_entity(conn, str(target_query)) if target_query else None
    weapon = resolve_entity(conn, str(weapon_query)) if weapon_query else None
    ammo = resolve_entity(conn, str(ammo_query)) if ammo_query else None
    weapon_item = item_row(conn, weapon["id"]) if weapon else None
    ammo_item = item_row(conn, ammo["id"]) if ammo else None
    weapon_properties = parse_json(weapon_item["properties_json"], {}) if weapon_item else {}
    ammo_properties = parse_json(ammo_item["properties_json"], {}) if ammo_item else {}
    combat = weapon_properties.get("combat_profile") if isinstance(weapon_properties, dict) else {}
    ammo_profile = ammo_properties.get("ammo_profile") if isinstance(ammo_properties, dict) else {}
    current = current_location_row(conn, meta)
    return {
        "target_query": target_query,
        "weapon_query": weapon_query,
        "ammo_query": ammo_query,
        "target": target,
        "weapon": weapon,
        "ammo": ammo,
        "weapon_item": weapon_item,
        "ammo_item": ammo_item,
        "combat": combat,
        "ammo_profile": ammo_profile,
        "distance": option_value(options, "distance"),
        "ready_state": option_value(options, "ready_state"),
        "current_location_id": current["id"] if current else None,
        "current_location_unreadable": bool(meta.get("current_location_id") and not current),
    }


def validate_combat_request(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    del campaign, conn, context_data
    missing = tuple(
        name
        for name in ("target", "weapon", "ammo", "distance")
        if not option_value(options, name)
    )
    return ActionValidationResult(missing_required=missing)


def combat_blockers(data: dict[str, Any], conn: sqlite3.Connection | None = None) -> list[str]:
    blockers = required_confirmations(
        data["target"],
        data["ammo"],
        data["distance"],
        data["combat"],
        data["ammo_item"],
    )
    if not data["weapon_query"]:
        blockers.append("武器未明确：保存前必须指定武器，不能由引擎默认选择。")
    elif not data["weapon"]:
        blockers.append(f"武器未找到：{data['weapon_query']}")
    if data["target_query"] and not data["target"]:
        blockers.append(f"目标未找到：{data['target_query']}")
    if data.get("current_location_unreadable"):
        blockers.append("当前地点未登记、不可见或不存在：不能保存战斗结果。")
    if (
        data["target"]
        and data["target"]["location_id"]
        and data["current_location_id"]
        and data["target"]["location_id"] != data["current_location_id"]
    ):
        location = entity_ref_label(conn, data["target"]["location_id"]) if conn else data["target"]["location_id"]
        blockers.append(f"目标不在当前地点：{location}；需要先 travel 或重新确认距离/视线。")
    if data["ammo_query"] and not data["ammo"]:
        blockers.append(f"弹药未找到：{data['ammo_query']}")
    if data["ready_state"]:
        blockers = [item for item in blockers if not item.startswith("必须确认武器是否已上弦")]
    return blockers


def resolve_combat(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    del campaign, context_data
    data = resolve_combat_inputs(conn, options)
    blockers = combat_blockers(data, conn)
    warnings = preview_warnings(
        data["weapon"],
        data["weapon_item"],
        data["ammo"],
        data["ammo_item"],
        data["combat"],
        data["ammo_profile"],
        get_player_entity_id(conn),
        conn=conn,
    )
    if data["ready_state"]:
        warnings.append(f"武器状态已由请求确认：{data['ready_state']}")
    facts = combat_facts(data)
    if blockers:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(redact_hidden_entity_refs(conn, tuple(facts), drop_empty=False)),
            confirmations=tuple(redact_hidden_entity_refs(conn, tuple(blockers), drop_empty=False)),
            warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
            narrative_constraints=("Ask for target, explicit weapon, ammo, distance and weapon ready state before saving combat.",),
        )

    suggested_ticks = suggested_clock_ticks(conn, data["ammo"], data["ammo_profile"])
    proposed_delta = build_combat_delta(
        conn,
        target=data["target"],
        weapon=data["weapon"],
        ammo=data["ammo"],
        ammo_item=data["ammo_item"],
        suggested_ticks=suggested_ticks,
        user_text=option_value(options, "user_text"),
        distance=data["distance"],
        ready_state=data["ready_state"],
    )
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")
    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_hidden_entity_refs(conn, tuple(facts), drop_empty=False)),
        rules_applied=tuple(rules),
        warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
        proposed_delta=redact_hidden_entity_refs(conn, proposed_delta, drop_empty=False),
        narrative_constraints=(
            "Use combat_turn.md for the response.",
            "Do not resolve hit, damage, target state or collateral effects outside the approved delta.",
            "Every fired ammunition item must be decremented exactly once.",
        ),
    )


def validate_combat_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del campaign, context_data
    data = resolve_combat_inputs(conn, options)
    errors = combat_blockers(data, conn)
    warnings: list[str] = []
    if delta.get("intent") != "combat":
        warnings.append("delta intent is not combat")
    for index, event in enumerate(delta.get("events", []) if isinstance(delta.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("target_id") and data["target"] and str(payload["target_id"]) != str(data["target"]["id"]):
            errors.append(f"events[{index}].payload.target_id must be {data['target']['id']}")
        if payload.get("weapon_id") and data["weapon"] and str(payload["weapon_id"]) != str(data["weapon"]["id"]):
            errors.append(f"events[{index}].payload.weapon_id must be {data['weapon']['id']}")
        if payload.get("ammo_id") and data["ammo"] and str(payload["ammo_id"]) != str(data["ammo"]["id"]):
            errors.append(f"events[{index}].payload.ammo_id must be {data['ammo']['id']}")
        if payload.get("distance") and data["distance"] and str(payload["distance"]) != str(data["distance"]):
            errors.append(f"events[{index}].payload.distance must be {data['distance']}")
    if data["ammo"] and data["ammo_item"] and data["ammo_item"]["quantity"] is not None and float(data["ammo_item"]["quantity"]) > 0:
        validate_ammo_decrement(data, delta, errors)
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def validate_ammo_decrement(data: dict[str, Any], delta: dict[str, Any], errors: list[str]) -> None:
    expected_quantity = decremented_quantity(data["ammo_item"])
    matches = [
        item
        for item in delta.get("upsert_entities", []) if isinstance(delta.get("upsert_entities", []), list)
        if isinstance(item, dict) and str(item.get("id")) == str(data["ammo"]["id"])
    ]
    if not matches:
        errors.append(f"upsert_entities must decrement fired ammo {data['ammo']['id']} to {expected_quantity:g}")
        return
    item_payload = matches[0].get("item", {})
    if not isinstance(item_payload, dict):
        errors.append(f"upsert_entities entry for {data['ammo']['id']} must include item payload")
        return
    quantity = item_payload.get("quantity")
    if quantity is None or float(quantity) != float(expected_quantity):
        errors.append(f"upsert_entities entry for {data['ammo']['id']} quantity must be {expected_quantity:g}")


def combat_facts(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    for key in ("target", "weapon", "ammo"):
        row = data.get(key)
        if row:
            facts.append(str(row["id"]))
    return list(dict.fromkeys(facts))


COMBAT_RESOLVER = ActionResolverSpec(
    name="combat",
    preview=preview_combat,
    response_template="combat_turn.md",
    option_specs=option_specs_for(
        ActionOptionSpec("target", "target entity id/name/alias"),
        ActionOptionSpec("weapon", "weapon entity id/name/alias"),
        ActionOptionSpec("ammo", "ammunition entity id/name/alias"),
        ActionOptionSpec("distance", "distance band or exact distance"),
        ActionOptionSpec("ready_state", "explicit weapon ready/loading confirmation"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    taxonomy=ActionTaxonomySpec(
        terms=(
            *taxonomy_terms("zh-Hans", ("射", "打", "攻击", "瞄准", "伏击", "开火", "逃跑", "迎击")),
            *taxonomy_terms("en", ("attack", "shoot", "ambush", "defend")),
        ),
        semantic_labels=("attack", "shoot", "ambush", "defend"),
        inference_priority=10,
    ),
    validate_request=validate_combat_request,
    resolve=resolve_combat,
    validate_delta=validate_combat_delta,
)
