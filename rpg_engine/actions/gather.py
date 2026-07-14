from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..palette import (
    find_palette_candidate,
    palette_candidate_payload,
    palette_entry_to_entity,
)
from ..redaction import redact_hidden_entity_refs
from ..visibility import can_read_hidden, normalize_visibility_view
from ..preview import (
    build_gather_delta,
    crop_plot_for_entity,
    current_location_label,
    current_location_row,
    entity_ref_label,
    gather_confirmations,
    location_detail_row,
    location_label,
    render_gather_preview,
    resolve_location,
)
from ..ux import RepairOption
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .taxonomy import ActionTaxonomySpec, taxonomy_terms


def redact_repair_options(conn: sqlite3.Connection, options: tuple[RepairOption, ...]) -> tuple[RepairOption, ...]:
    return tuple(
        replace(
            option,
            label=str(redact_hidden_entity_refs(conn, option.label, drop_empty=False)),
            description=str(redact_hidden_entity_refs(conn, option.description, drop_empty=False)),
            options=redact_hidden_entity_refs(conn, option.options, drop_empty=False),
            effect=str(redact_hidden_entity_refs(conn, option.effect, drop_empty=False)),
        )
        for option in options
    )


def action_request_view(context_data: dict[str, Any] | None) -> str:
    return normalize_visibility_view(str((context_data or {}).get("view") or "player"))


def should_redact_action(context_data: dict[str, Any] | None) -> bool:
    return not can_read_hidden(action_request_view(context_data))


def redact_gather_value(conn: sqlite3.Connection, value: Any, *, should_redact: bool) -> Any:
    return redact_hidden_entity_refs(conn, value, drop_empty=False) if should_redact else value


def render_gather_text(conn: sqlite3.Connection, text: str, *, should_redact: bool) -> str:
    return str(redact_hidden_entity_refs(conn, text, drop_empty=False)) if should_redact else text


def preview_gather(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    should_redact = should_redact_action(context)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return render_palette_gather_preview(campaign, conn, options, str(palette_id), should_redact=should_redact)
    return render_gather_preview(
        conn,
        campaign=campaign,
        target_query=option_value(options, "target"),
        location_query=option_value(options, "location") or option_value(options, "destination"),
        user_text=option_value(options, "user_text"),
    )


def validate_gather_request(
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
            intent="gather",
        )
        return validate_palette_gather_candidate(candidate, str(palette_id))
    if not option_value(options, "target"):
        return ActionValidationResult(missing_required=("target",))
    return ActionValidationResult()


def resolve_gather(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    should_redact = should_redact_action(context_data)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return resolve_palette_gather(campaign, conn, options, str(palette_id), should_redact=should_redact)
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    target_query = option_value(options, "target")
    location_query = option_value(options, "location") or option_value(options, "destination")
    location = resolve_location(conn, str(location_query)) if location_query else current
    if location and "description_short" not in location.keys():
        location = location_detail_row(conn, location["id"])
    target = resolve_entity(conn, str(target_query)) if target_query else None
    crop = crop_plot_for_entity(conn, target["id"]) if target else None
    blocking = gather_blockers(conn, target_query, target, location, current, crop, meta)
    confirmations = gather_confirmations(conn, target_query, target, location, current, crop, meta)
    if blocking:
        safe_blocking = tuple(redact_hidden_entity_refs(conn, tuple(blocking), drop_empty=False))
        safe_warnings = tuple(redact_hidden_entity_refs(conn, tuple(item for item in confirmations if item not in blocking), drop_empty=False))
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(redact_hidden_entity_refs(conn, tuple(gather_facts(target, location, crop)), drop_empty=False)),
            confirmations=safe_blocking,
            warnings=safe_warnings,
            player_message=str(redact_hidden_entity_refs(conn, gather_player_message(target_query, target, location, current, meta, blocking), drop_empty=False)),
            repair_options=redact_repair_options(conn, gather_repair_options(conn, target_query, target, location, current, meta, blocking)),
            narrative_constraints=("Ask for a concrete gather target at the current location before saving.",),
        )

    proposed_delta = build_gather_delta(
        meta=meta,
        current_location_id=current["id"] if current else "",
        target=target,
        location=location,
        crop=crop,
        user_text=option_value(options, "user_text"),
    )
    proposed_delta = redact_hidden_entity_refs(conn, proposed_delta, drop_empty=False)
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")

    if any(item.startswith("保存前必须明确新增库存") for item in confirmations) and not option_value(
        options,
        "output_confirmed",
    ):
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(redact_hidden_entity_refs(conn, tuple(gather_facts(target, location, crop)), drop_empty=False)),
            rules_applied=tuple(rules),
            confirmations=("需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。",),
            warnings=tuple(redact_hidden_entity_refs(conn, tuple(confirmations), drop_empty=False)),
            player_message="采集目标已识别，但保存前必须补明确产出数量和资源状态。",
            proposed_delta=proposed_delta,
            narrative_constraints=(
                "Ask the GM/player to provide output item id, quantity, unit, location and resource state before commit.",
            ),
        )

    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_hidden_entity_refs(conn, tuple(gather_facts(target, location, crop)), drop_empty=False)),
        rules_applied=tuple(rules),
        warnings=tuple(redact_hidden_entity_refs(conn, tuple(confirmations), drop_empty=False)),
        player_message="采集预演已准备好，可以保存结构化产出和资源变化。",
        proposed_delta=proposed_delta,
        narrative_constraints=(
            "Use gather_turn.md for the response.",
            "Do not invent output quantity, quality or depletion state outside the approved delta.",
            "If travel is required, resolve travel before saving gather.",
        ),
    )


def validate_gather_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return validate_palette_gather_delta(campaign, conn, options, delta, str(palette_id))
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    target_query = option_value(options, "target")
    if not target_query:
        return ActionValidationResult(missing_required=("target",))
    target = resolve_entity(conn, str(target_query))
    if not target:
        return ActionValidationResult(errors=(f"target not found: {target_query}",))
    location_query = option_value(options, "location") or option_value(options, "destination")
    location = resolve_location(conn, str(location_query)) if location_query else current
    if location and "description_short" not in location.keys():
        location = location_detail_row(conn, location["id"])
    crop = crop_plot_for_entity(conn, target["id"])
    blockers = gather_blockers(conn, target_query, target, location, current, crop, meta)
    errors = list(blockers)
    warnings: list[str] = []
    if delta.get("intent") != "gather":
        warnings.append("delta intent is not gather")
    expected_location_id = location["id"] if location else (current["id"] if current else None)
    if delta.get("location_after") and str(delta["location_after"]) != str(expected_location_id):
        errors.append(f"location_after must be {expected_location_id}")
    for index, event in enumerate(delta.get("events", []) if isinstance(delta.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("target_id") and str(payload["target_id"]) != str(target["id"]):
            errors.append(f"events[{index}].payload.target_id must be {target['id']}")
        if payload.get("location_id") and str(payload["location_id"]) != str(expected_location_id):
            errors.append(f"events[{index}].payload.location_id must be {expected_location_id}")
        if payload.get("travel_required") is True and current and expected_location_id == current["id"]:
            errors.append(f"events[{index}].payload.travel_required must be false at current location")
    if "upsert_entities" not in delta:
        warnings.append("delta has no upsert_entities field for gathered output")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def render_palette_gather_preview(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> str:
    meta = get_meta(conn)
    location_query = option_value(options, "location") or option_value(options, "destination")
    candidate = find_palette_candidate(campaign, conn, palette_id, location_query=location_query, intent="gather")
    lines = [
        "## 采集候选预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 候选素材 | `{palette_id}` |",
        f"| 地点 | {location_query or current_location_label(conn, meta)} |",
        f"| 原始行动 | {option_value(options, 'user_text') or option_value(options, 'target') or '采集候选素材'} |",
        "",
    ]
    if candidate is None:
        lines.extend(["### 错误", f"- palette not found: {palette_id}"])
        return render_gather_text(conn, "\n".join(lines), should_redact=should_redact)

    entry = candidate["entry"]
    discovery = entry.get("discovery") if isinstance(entry.get("discovery"), dict) else {}
    lines.extend(
        [
            "### 候选素材",
            "| 字段 | 值 |",
            "|------|----|",
            f"| 状态 | `{candidate['status']}` |",
            f"| 类型 | `{entry.get('_kind', '')}` |",
            f"| 名称 | {entry.get('name', '')} |",
            f"| 摘要 | {entry.get('summary', '')} |",
            f"| 线索 | {discovery.get('clue_text', '')} |",
            "",
            "### 结算边界",
            "- palette 是候选，不是当前事实。",
            "- `confirm_required` 和 `clue_only` 不能直接加入库存或确认新材料。",
            "- 若要保存正式发现，delta 必须包含 palette 来源和结构化事件。",
            "",
            "### Delta 草案",
        ]
    )
    if candidate["status"] != "available":
        lines.append("该候选需要确认或仅能作为线索，不能生成采集产出保存草案。")
        return render_gather_text(conn, "\n".join(lines), should_redact=should_redact)
    if not current_location_row(conn, get_meta(conn)):
        lines.append("当前地点不可见，不能生成保存草案。")
        return render_gather_text(conn, "\n".join(lines), should_redact=should_redact)

    delta = build_palette_gather_delta(conn, candidate, options, should_redact=should_redact)
    lines.extend(
        [
            "保存前必须由 GM 按实际采样、数量和资源状态改写。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return render_gather_text(conn, "\n".join(lines), should_redact=should_redact)


def validate_palette_gather_candidate(candidate: dict[str, Any] | None, palette_id: str) -> ActionValidationResult:
    if candidate is None:
        return ActionValidationResult(errors=(f"palette not found: {palette_id}",))
    entry = candidate["entry"]
    if entry.get("_kind") != "material":
        return ActionValidationResult(errors=(f"palette candidate is not material: {palette_id}",))
    if candidate["status"] in {"locked", "out_of_context"}:
        return ActionValidationResult(errors=(f"palette candidate is {candidate['status']}: {palette_id}",))
    if candidate["status"] in {"confirm_required", "clue_only"}:
        return ActionValidationResult(warnings=(f"palette candidate requires confirmation before gather output: {palette_id}",))
    return ActionValidationResult()


def resolve_palette_gather(
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
        intent="gather",
    )
    validation = validate_palette_gather_candidate(candidate, palette_id)
    if validation.errors:
        safe_errors = tuple(redact_gather_value(conn, validation.errors, should_redact=should_redact))
        return ResolutionResult(
            status="blocked",
            warnings=safe_errors,
            player_message=safe_errors[0],
            narrative_constraints=("Do not invent gathered output from an invalid palette candidate.",),
        )
    if candidate is None:
        safe_palette_id = str(redact_gather_value(conn, palette_id, should_redact=should_redact))
        return ResolutionResult(status="blocked", warnings=(f"palette not found: {safe_palette_id}",))
    entry = candidate["entry"]
    if candidate["status"] != "available":
        safe_palette_id = str(redact_gather_value(conn, palette_id, should_redact=should_redact))
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=(safe_palette_id,),
            confirmations=(f"候选素材 `{safe_palette_id}` 仍是 {candidate['status']}，需要观察、采样或询问后才能保存采集产出。",),
            warnings=tuple(redact_gather_value(conn, tuple(validation.warnings), should_redact=should_redact)),
            player_message="这还是候选线索，不能直接加入库存或确认新材料。",
            narrative_constraints=("Describe clue text only; ask for sampling or verification before saving gathered output.",),
        )
    if not current_location_row(conn, get_meta(conn)):
        return ResolutionResult(
            status="needs_confirmation",
            warnings=("当前地点未登记、不可见或不存在：不能保存采集候选结果。",),
            player_message="当前地点不可见，不能生成采集候选保存草案。",
            narrative_constraints=("Ask the player to resolve current location before saving gather output.",),
        )
    return ResolutionResult(
        status="ready",
        facts_used=(str(redact_gather_value(conn, palette_id, should_redact=should_redact)),),
        warnings=tuple(redact_gather_value(conn, tuple(validation.warnings), should_redact=should_redact)),
        proposed_delta=build_palette_gather_delta(conn, candidate, options, should_redact=should_redact),
        player_message=f"候选素材 {redact_gather_value(conn, entry.get('name', palette_id), should_redact=should_redact)} 可作为本回合采集候选；保存前仍需确认数量和资源状态。",
        narrative_constraints=(
            "Use gather_turn.md for the response.",
            "Do not invent output quantity, quality or depletion state outside the approved delta.",
            "Mention that this result came from a palette candidate.",
        ),
    )


def build_palette_gather_delta(
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
    location_id = current["id"]
    entry = redact_gather_value(conn, candidate["entry"], should_redact=should_redact) or {}
    entity = palette_entry_to_entity(entry, visibility="known", location_id=location_id)
    payload = {
        **redact_gather_value(conn, palette_candidate_payload(candidate), should_redact=should_redact),
        "target_id": entity["id"],
        "target_type": entity["type"],
        "location_id": location_id,
        "output_quantity_required": True,
        "resource_state_update_required": True,
    }
    summary = f"采集候选素材：{entry.get('name', entry.get('id'))}；数量和资源状态待 GM 确认。"
    delta = {
        "user_text": option_value(options, "user_text") or option_value(options, "target") or f"采集 {entry.get('name', entry.get('id'))}",
        "intent": "gather",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": f"{meta.get('current_time_block', '当前时段')} + 采集耗时（草案）",
        "location_before": location_id,
        "location_after": location_id,
        "summary": summary,
        "events": [
            {
                "type": "gather",
                "title": "采集候选素材",
                "summary": summary,
                "payload": payload,
                "source": "palette_gather_preview",
            }
        ],
        "upsert_entities": [entity],
        "tick_clocks": [],
    }
    return redact_gather_value(conn, delta, should_redact=should_redact)


def validate_palette_gather_delta(
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
        intent="gather",
    )
    validation = validate_palette_gather_candidate(candidate, palette_id)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    if delta.get("intent") != "gather":
        warnings.append("delta intent is not gather")
    payloads = [
        event.get("payload", {})
        for event in delta.get("events", []) if isinstance(event, dict)
    ]
    if not any(isinstance(payload, dict) and payload.get("palette_id") == palette_id for payload in payloads):
        errors.append(f"gather delta must include events[].payload.palette_id {palette_id}")
    if candidate and candidate["status"] != "available" and delta.get("upsert_entities"):
        errors.append(f"palette candidate {palette_id} is {candidate['status']} and cannot create gathered output")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def gather_blockers(
    conn_or_target_query: sqlite3.Connection | str | None,
    target_query: str | sqlite3.Row | None = None,
    target: sqlite3.Row | None = None,
    location: sqlite3.Row | None = None,
    current: sqlite3.Row | dict[str, str] | None = None,
    crop: sqlite3.Row | dict[str, str] | None = None,
    meta: dict[str, str] | None = None,
) -> list[str]:
    conn: sqlite3.Connection | None
    if isinstance(conn_or_target_query, sqlite3.Connection):
        conn = conn_or_target_query
    else:
        conn = None
        meta = current if isinstance(current, dict) else (crop if isinstance(crop, dict) else meta)
        crop = current if isinstance(current, sqlite3.Row) else None
        current = None
        location = target if isinstance(target, sqlite3.Row) else None
        target = target_query if isinstance(target_query, sqlite3.Row) else None
        target_query = conn_or_target_query if isinstance(conn_or_target_query, str) else None
    meta = meta or {}
    blockers: list[str] = []
    current_location_id = current["id"] if isinstance(current, sqlite3.Row) else meta.get("current_location_id")
    if meta.get("current_location_id") and not current:
        blockers.append("当前地点不可见或不存在：不能保存采集结果。")
    if not target_query:
        blockers.append("目标未指定：保存前必须明确采集对象和产出。")
    elif not target:
        blockers.append(f"采集目标未找到：{target_query}")
    if not location:
        blockers.append("采集地点未解析：需要确认当前位置或目的地。")
    elif current_location_id and location["id"] != current_location_id:
        current_label = location_label(current) if isinstance(current, sqlite3.Row) else current_location_id
        blockers.append(f"目标地点不是当前位置：当前在 {current_label}，需要先结算 travel 或同回合明确旅行耗时/风险。")
    if target and location and target["location_id"] and target["location_id"] != location["id"]:
        target_location = entity_ref_label(conn, target["location_id"]) if conn else target["location_id"]
        blockers.append(f"目标不在指定地点：{target_location}；可能需要改地点或先 travel。")
    if target and target["type"] == "crop_plot" and not crop:
        blockers.append("目标是农田但缺少 crop_plot 行：不能可靠结算收获。")
    return blockers


def gather_facts(
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    crop: sqlite3.Row | None,
) -> list[str]:
    facts: list[str] = []
    if location:
        facts.append(str(location["id"]))
    if target:
        facts.append(str(target["id"]))
    if crop:
        facts.append(str(crop["entity_id"]))
    return list(dict.fromkeys(item for item in facts if item))


def gather_player_message(
    target_query: str | None,
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    current: sqlite3.Row | dict[str, str] | None,
    meta: dict[str, str] | list[str] | None = None,
    blocking: list[str] | None = None,
) -> str:
    if blocking is None and isinstance(meta, list):
        blocking = meta
        meta = current if isinstance(current, dict) else {}
        current = None
    blocking = blocking or []
    meta = meta if isinstance(meta, dict) else {}
    current_location_id = current["id"] if isinstance(current, sqlite3.Row) else meta.get("current_location_id")
    if location and current_location_id and location["id"] != current_location_id:
        return f"你现在不在 {location['name']}。可以先前往该地点，再采集 {target_query or '目标资源'}。"
    if target and location and target["location_id"] and target["location_id"] != location["id"]:
        return f"{target['name']} 不在 {location['name']}。需要改地点、改目标，或先移动到对象所在地点。"
    return blocking[0] if blocking else "采集行动需要更多信息。"


def gather_repair_options(
    conn_or_target_query: sqlite3.Connection | str | None,
    target_query: str | sqlite3.Row | None = None,
    target: sqlite3.Row | None = None,
    location: sqlite3.Row | dict[str, str] | None = None,
    current: sqlite3.Row | list[str] | None = None,
    meta: dict[str, str] | None = None,
    blocking: list[str] | None = None,
) -> tuple[RepairOption, ...]:
    conn: sqlite3.Connection | None
    if isinstance(conn_or_target_query, sqlite3.Connection):
        conn = conn_or_target_query
    else:
        conn = None
        blocking = current if isinstance(current, list) else blocking
        meta = location if isinstance(location, dict) else meta
        current = None
        location = target if isinstance(target, sqlite3.Row) else None
        target = target_query if isinstance(target_query, sqlite3.Row) else None
        target_query = conn_or_target_query if isinstance(conn_or_target_query, str) else None
    meta = meta or {}
    blocking = blocking or []
    options: list[RepairOption] = []
    current_location_id = current["id"] if isinstance(current, sqlite3.Row) else meta.get("current_location_id")
    if location and current_location_id and location["id"] != current_location_id:
        options.append(
            RepairOption(
                id="travel_then_gather",
                label=f"先去{location['name']}再采集",
                action="travel",
                options={"destination": location["id"], "pace": "normal"},
                effect="先结算 travel，再重新预演 gather",
            )
        )
    target_location = location_detail_row(conn, target["location_id"]) if conn and target and target["location_id"] else None
    target_location_id = target_location["id"] if target_location else None
    if target_location_id and target_location_id != current_location_id:
        target_location_name = target_location["name"] if target_location else target_location_id
        options.append(
            RepairOption(
                id="travel_to_target_location",
                label="前往目标所在地点",
                action="travel",
                options={"destination": target_location_id, "pace": "normal"},
                effect=f"移动到 {target_location_name} 后重新采集",
            )
        )
    if target_query and any("盘点" in item or "库存" in str(target_query) for item in blocking):
        options.append(
            RepairOption(
                id="use_routine_inventory_audit",
                label="改为盘点库存",
                action="routine",
                options={"task": "盘点库存", "user_text": str(target_query)},
                effect="不产生采集产出，只做低风险库存检查",
                risk_level="none",
                requires_confirmation=False,
            )
        )
    if not options:
        options.append(
            RepairOption(
                id="clarify_gather",
                label="改目标或地点",
                action="gather",
                options={"target": target_query},
                effect="用更明确的采集对象和当前位置重新预演",
                risk_level="none",
                requires_confirmation=False,
            )
        )
    return tuple(options)


GATHER_RESOLVER = ActionResolverSpec(
    name="gather",
    preview=preview_gather,
    response_template="gather_turn.md",
    option_specs=option_specs_for(
        ActionOptionSpec(
            "target",
            "target crop/resource/item id/name/alias",
            required=True,
            binding_type="entity",
            allowed_entity_types=("plant", "item", "material", "crop_plot"),
            aliases=("resource",),
        ),
        ActionOptionSpec(
            "location",
            "location id/name/alias; defaults to current location",
            binding_type="entity",
            allowed_entity_types=("location",),
            aliases=("destination", "place"),
        ),
        ActionOptionSpec("palette_id", "palette candidate id to consume under gather rules", dest="palette-id"),
        ActionOptionSpec("output_confirmed", "GM/human-edited delta includes explicit output quantity", dest="output-confirmed"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text", ai_fillable=False),
    ),
    taxonomy=ActionTaxonomySpec(
        terms=(
            *taxonomy_terms(
                "zh-Hans",
                ("采", "采集", "捡", "采药", "摘", "拾取", "收集"),
                roles=("preview.mismatch", "simple"),
            ),
            *taxonomy_terms("zh-Hans", ("收", "挖", "割", "取", "收获", "能吃", "食物", "弄点")),
            *taxonomy_terms(
                "en",
                ("gather", "collect", "harvest"),
                roles=("preview.mismatch", "simple"),
            ),
            *taxonomy_terms("en", ("pick", "forage")),
        ),
        semantic_labels=("gather", "harvest", "collect", "forage"),
        inference_priority=50,
    ),
    validate_request=validate_gather_request,
    resolve=resolve_gather,
    validate_delta=validate_gather_delta,
)
