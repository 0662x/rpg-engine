from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, get_player_entity_id
from ..palette import find_palette_candidate, palette_candidate_payload
from ..redaction import redact_hidden_entity_refs
from ..visibility import can_read_hidden, normalize_visibility_view
from ..preview import (
    build_travel_delta,
    current_location_label,
    current_location_row,
    destination_threats,
    estimate_travel_minutes,
    find_route,
    location_detail_row,
    render_travel_preview,
    resolve_location,
    suggested_travel_clock_ticks,
    travel_risks,
)
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)


def action_request_view(context_data: dict[str, Any] | None) -> str:
    return normalize_visibility_view(str((context_data or {}).get("view") or "player"))


def should_redact_action(context_data: dict[str, Any] | None) -> bool:
    return not can_read_hidden(action_request_view(context_data))


def redact_travel_value(conn: sqlite3.Connection, value: Any, *, should_redact: bool) -> Any:
    return redact_hidden_entity_refs(conn, value, drop_empty=False) if should_redact else value


def render_travel_text(conn: sqlite3.Connection, text: str, *, should_redact: bool) -> str:
    return str(redact_hidden_entity_refs(conn, text, drop_empty=False)) if should_redact else text


def preview_travel(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> str:
    should_redact = should_redact_action(context_data)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return render_palette_travel_preview(campaign, conn, options, str(palette_id), should_redact=should_redact)
    destination = option_value(options, "destination")
    if not destination:
        return ""
    return render_travel_preview(
        conn,
        destination_query=destination,
        pace=option_value(options, "pace", "normal"),
        user_text=option_value(options, "user_text"),
    )


def validate_travel_request(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        candidate = find_palette_candidate(
            campaign,
            conn,
            str(palette_id),
            location_query=option_value(options, "location") or option_value(options, "destination"),
            intent="travel",
        )
        return validate_palette_travel_candidate(candidate, str(palette_id))
    destination_query = option_value(options, "destination")
    if not destination_query:
        return ActionValidationResult(missing_required=("destination",))
    destination_entity = resolve_location(conn, str(destination_query))
    if not destination_entity:
        return ActionValidationResult(errors=(f"destination not found: {destination_query}",))
    if destination_entity["type"] != "location":
        return ActionValidationResult(errors=(f"destination is not a location: {destination_entity['id']}",))
    destination = location_detail_row(conn, destination_entity["id"])
    if not destination:
        return ActionValidationResult(errors=(f"destination lacks location details: {destination_entity['id']}",))
    return ActionValidationResult()


def resolve_travel(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    should_redact = should_redact_action(context_data)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return resolve_palette_travel(campaign, conn, options, str(palette_id), should_redact=should_redact)
    destination_query = option_value(options, "destination")
    if not destination_query:
        return ResolutionResult(
            status="needs_confirmation",
            confirmations=("目的地未明确。",),
            narrative_constraints=("Ask which visible location the player wants to reach.",),
        )

    meta = get_meta(conn)
    current = location_detail_row(conn, meta.get("current_location_id"))
    destination_entity = resolve_location(conn, str(destination_query))
    if not destination_entity:
        safe_destination_query = redact_hidden_entity_refs(conn, str(destination_query), drop_empty=False)
        return ResolutionResult(
            status="needs_confirmation",
            confirmations=(f"目的地未找到：{safe_destination_query}",),
            narrative_constraints=("Ask the player to clarify the destination before saving travel.",),
        )
    destination = location_detail_row(conn, destination_entity["id"])
    if not current:
        return ResolutionResult(
            status="blocked",
            warnings=("当前地点未解析，不能可靠结算旅行。",),
            narrative_constraints=("Repair current_location_id before resolving travel.",),
        )
    if not destination:
        return ResolutionResult(
            status="blocked",
            warnings=(f"目的地缺少 location 详情：{destination_entity['id']}",),
            narrative_constraints=("Repair destination location details before resolving travel.",),
        )

    route = find_route(conn, current, destination)
    travel_minutes = route["travel_minutes"] if route else estimate_travel_minutes(current, destination)
    if travel_minutes is None:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=(current["id"], destination["id"]),
            confirmations=("路线耗时未知。",),
            narrative_constraints=("GM must estimate route time and risk before saving.",),
        )

    threats = destination_threats(conn, destination["id"])
    suggested_ticks = suggested_travel_clock_ticks(conn, destination)
    warnings = list(travel_risks(destination, threats, {}, option_value(options, "pace", "normal")))
    if route is None and current["id"] != destination["id"]:
        warnings.append("未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。")

    player_id = get_player_entity_id(conn)
    pc = conn.execute("select * from entities where id = ?", (player_id,)).fetchone()
    character = conn.execute("select * from characters where entity_id = ?", (player_id,)).fetchone()
    proposed_delta = build_travel_delta(
        conn,
        meta=meta,
        pc=pc,
        character=character,
        current=current,
        destination=destination,
        travel_minutes=travel_minutes,
        pace=option_value(options, "pace", "normal"),
        threats=threats,
        route=route,
        suggested_ticks=suggested_ticks,
        user_text=option_value(options, "user_text"),
    )

    facts = [current["id"], destination["id"]]
    if route:
        facts.extend(str(route_id) for route_id in route.get("route_ids", []) or [route["id"]])
    facts.extend(row["id"] for row in threats[:6])
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")

    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_hidden_entity_refs(conn, tuple(dict.fromkeys(str(item) for item in facts if item)), drop_empty=False)),
        rules_applied=tuple(rules),
        warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
        proposed_delta=redact_hidden_entity_refs(conn, proposed_delta, drop_empty=False),
        narrative_constraints=(
            "Use scene_entry.md after arrival.",
            "Do not reveal hidden destination threats unless they are visible or surfaced by an approved event.",
            "Confirm carried gear and pace in narration before final save.",
        ),
    )


def validate_travel_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return validate_palette_travel_delta(campaign, conn, options, delta, str(palette_id))
    destination_query = option_value(options, "destination")
    if not destination_query:
        return ActionValidationResult(missing_required=("destination",))
    destination_entity = resolve_location(conn, str(destination_query))
    if not destination_entity:
        return ActionValidationResult(errors=(f"destination not found: {destination_query}",))
    destination_id = str(destination_entity["id"])
    errors: list[str] = []
    warnings: list[str] = []
    if delta.get("intent") != "travel":
        warnings.append("delta intent is not travel")
    if not delta.get("location_after"):
        errors.append("location_after is required for travel")
    elif str(delta["location_after"]) != destination_id:
        errors.append(f"location_after must be {destination_id}")
    meta = delta.get("meta", {})
    if isinstance(meta, dict) and meta.get("current_location_id") and str(meta["current_location_id"]) != destination_id:
        errors.append(f"meta.current_location_id must be {destination_id}")
    for index, event in enumerate(delta.get("events", []) if isinstance(delta.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if isinstance(payload, dict) and payload.get("to_location_id") and str(payload["to_location_id"]) != destination_id:
            errors.append(f"events[{index}].payload.to_location_id must be {destination_id}")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def render_palette_travel_preview(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> str:
    candidate = find_palette_candidate(
        campaign,
        conn,
        palette_id,
        location_query=option_value(options, "location") or option_value(options, "destination"),
        intent="travel",
    )
    lines = [
        "## 旅行候选预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 候选素材 | `{palette_id}` |",
            f"| 当前地点 | {current_location_label(conn, get_meta(conn))} |",
        f"| 旅行节奏 | {option_value(options, 'pace', 'normal')} |",
        "",
    ]
    if candidate is None:
        lines.extend(["### 错误", f"- palette not found: {palette_id}"])
        return render_travel_text(conn, "\n".join(lines), should_redact=should_redact)
    entry = candidate["entry"]
    discovery = entry.get("discovery") if isinstance(entry.get("discovery"), dict) else {}
    lines.extend(
        [
            "### 候选地点",
            "| 字段 | 值 |",
            "|------|----|",
            f"| 状态 | `{candidate['status']}` |",
            f"| 类型 | `{entry.get('_kind', '')}` |",
            f"| 名称 | {entry.get('name', '')} |",
            f"| 摘要 | {entry.get('summary', '')} |",
            f"| 线索 | {discovery.get('clue_text', '')} |",
            "",
            "### 结算边界",
            "- 旅行候选只能生成找路、确认路线或观察线索。",
            "- 不能直接新增 route，不能把候选地点直接设为当前位置。",
            "- 若要把地点或路线变成事实，必须走 content delta / proposal review。",
            "",
            "### Delta 草案",
        ]
    )
    validation = validate_palette_travel_candidate(candidate, palette_id)
    if validation.errors:
        lines.extend(f"- {item}" for item in validation.errors)
        return render_travel_text(conn, "\n".join(lines), should_redact=should_redact)
    if not current_location_row(conn, get_meta(conn)):
        lines.append("当前地点不可见，不能生成保存草案。")
        return render_travel_text(conn, "\n".join(lines), should_redact=should_redact)
    delta = build_palette_travel_delta(conn, candidate, options, should_redact=should_redact)
    lines.extend(
        [
            "保存后只记录找路线索；不会移动角色，也不会新增路线。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return render_travel_text(conn, "\n".join(lines), should_redact=should_redact)


def validate_palette_travel_candidate(candidate: dict[str, Any] | None, palette_id: str) -> ActionValidationResult:
    if candidate is None:
        return ActionValidationResult(errors=(f"palette not found: {palette_id}",))
    entry = candidate["entry"]
    if entry.get("_kind") != "location":
        return ActionValidationResult(errors=(f"palette candidate is not location: {palette_id}",))
    if candidate["status"] in {"locked", "out_of_context"}:
        return ActionValidationResult(errors=(f"palette candidate is {candidate['status']}: {palette_id}",))
    return ActionValidationResult()


def resolve_palette_travel(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> ResolutionResult:
    candidate = find_palette_candidate(
        campaign,
        conn,
        palette_id,
        location_query=option_value(options, "location") or option_value(options, "destination"),
        intent="travel",
    )
    validation = validate_palette_travel_candidate(candidate, palette_id)
    if validation.errors:
        safe_errors = tuple(redact_travel_value(conn, validation.errors, should_redact=should_redact))
        return ResolutionResult(
            status="blocked",
            warnings=safe_errors,
            player_message=safe_errors[0],
            narrative_constraints=("Do not invent travel facts from an invalid palette candidate.",),
        )
    if candidate is None:
        safe_palette_id = str(redact_travel_value(conn, palette_id, should_redact=should_redact))
        return ResolutionResult(status="blocked", warnings=(f"palette not found: {safe_palette_id}",))
    if not current_location_row(conn, get_meta(conn)):
        return ResolutionResult(
            status="needs_confirmation",
            warnings=("当前地点未登记、不可见或不存在：不能保存旅行候选线索。",),
            player_message="当前地点不可见，不能生成旅行候选保存草案。",
            narrative_constraints=("Ask the player to resolve current location before saving travel leads.",),
        )
    entry = redact_travel_value(conn, candidate["entry"], should_redact=should_redact) or {}
    display_name = str(entry.get("name") or palette_id)
    return ResolutionResult(
        status="ready",
        facts_used=(str(redact_travel_value(conn, palette_id, should_redact=should_redact)),),
        warnings=tuple(redact_travel_value(conn, (f"候选状态为 {candidate['status']}；本回合只记录找路线索，不确认新地点或路线。",), should_redact=should_redact)),
        proposed_delta=build_palette_travel_delta(conn, candidate, options, should_redact=should_redact),
        player_message=f"旅行候选 {display_name} 已准备好；保存后只记录找路线索。",
        narrative_constraints=(
            "Use scene_entry.md for travel lead response.",
            "Do not move the player to a palette location candidate in this step.",
            "Do not create routes outside content delta review.",
        ),
    )


def build_palette_travel_delta(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    options: Any,
    *,
    should_redact: bool = True,
) -> dict[str, Any]:
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    if not current:
        raise ValueError("current location is not player-visible")
    current_location_id = current["id"]
    entry = redact_travel_value(conn, candidate["entry"], should_redact=should_redact) or {}
    payload = {
        **redact_travel_value(conn, palette_candidate_payload(candidate), should_redact=should_redact),
        "from_location_id": current_location_id,
        "to_location_id": None,
        "target_kind": "palette_candidate",
        "travel_plan_required": True,
        "route_creation_requires_review": True,
        "clue_stage": "hinted",
        "pace": option_value(options, "pace", "normal"),
    }
    summary = f"发现旅行候选线索：{entry.get('name', entry.get('id'))}；需要确认路线后才能移动。"
    delta = {
        "user_text": option_value(options, "user_text") or option_value(options, "destination") or f"寻找 {entry.get('name', entry.get('id'))}",
        "intent": "travel",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": meta.get("current_time_block"),
        "location_before": current_location_id,
        "location_after": current_location_id,
        "summary": summary,
        "events": [
            {
                "type": "travel_lead",
                "title": "旅行候选线索",
                "summary": summary,
                "payload": payload,
                "source": "palette_travel_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }
    return redact_travel_value(conn, delta, should_redact=should_redact)


def validate_palette_travel_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    delta: dict[str, Any],
    palette_id: str,
) -> ActionValidationResult:
    candidate = find_palette_candidate(
        campaign,
        conn,
        palette_id,
        location_query=option_value(options, "location") or option_value(options, "destination"),
        intent="travel",
    )
    validation = validate_palette_travel_candidate(candidate, palette_id)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    if delta.get("intent") != "travel":
        warnings.append("delta intent is not travel")
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    current_location_id = current["id"] if current else None
    if not current_location_id:
        errors.append("palette travel delta requires a visible current location")
    elif delta.get("location_after") and str(delta["location_after"]) != str(current_location_id):
        errors.append(f"palette travel delta must keep location_after at current location {current_location_id}")
    payloads = [event.get("payload", {}) for event in delta.get("events", []) if isinstance(event, dict)]
    if not any(isinstance(payload, dict) and payload.get("palette_id") == palette_id for payload in payloads):
        errors.append(f"travel delta must include events[].payload.palette_id {palette_id}")
    if delta.get("upsert_entities"):
        warnings.append("palette travel delta should not create location or route facts before content review")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


TRAVEL_RESOLVER = ActionResolverSpec(
    name="travel",
    preview=preview_travel,
    response_template="scene_entry.md",
    required_options=("destination",),
    option_specs=option_specs_for(
        ActionOptionSpec("destination", "destination location id/name/alias"),
        ActionOptionSpec("location", "optional current/search location for palette candidates"),
        ActionOptionSpec("palette_id", "location palette candidate id used as a travel lead", dest="palette-id"),
        ActionOptionSpec("pace", "travel pace", default="normal"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    keywords=("去", "前往", "抵达", "出发", "撤退"),
    semantic_labels=("travel", "move", "retreat", "approach", "scout-route"),
    inference_priority=60,
    validate_request=validate_travel_request,
    resolve=resolve_travel,
    validate_delta=validate_travel_delta,
)
