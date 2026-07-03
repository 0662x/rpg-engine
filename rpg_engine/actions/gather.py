from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..palette import (
    find_palette_candidate,
    palette_candidate_payload,
    palette_entry_to_entity,
)
from ..preview import (
    build_gather_delta,
    crop_plot_for_entity,
    gather_confirmations,
    location_detail_row,
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


def preview_gather(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    del context
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return render_palette_gather_preview(campaign, conn, options, str(palette_id))
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
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return resolve_palette_gather(campaign, conn, options, str(palette_id))
    meta = get_meta(conn)
    target_query = option_value(options, "target")
    location_query = option_value(options, "location") or option_value(options, "destination")
    location = resolve_location(conn, str(location_query)) if location_query else location_detail_row(conn, meta.get("current_location_id"))
    if location and "description_short" not in location.keys():
        location = location_detail_row(conn, location["id"])
    target = resolve_entity(conn, str(target_query)) if target_query else None
    crop = crop_plot_for_entity(conn, target["id"]) if target else None
    blocking = gather_blockers(target_query, target, location, crop, meta)
    confirmations = gather_confirmations(target_query, target, location, crop, meta)
    if blocking:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(gather_facts(target, location, crop)),
            confirmations=tuple(blocking),
            warnings=tuple(item for item in confirmations if item not in blocking),
            player_message=gather_player_message(target_query, target, location, meta, blocking),
            repair_options=gather_repair_options(target_query, target, location, meta, blocking),
            narrative_constraints=("Ask for a concrete gather target at the current location before saving.",),
        )

    proposed_delta = build_gather_delta(
        meta=meta,
        target=target,
        location=location,
        crop=crop,
        user_text=option_value(options, "user_text"),
    )
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")

    if any(item.startswith("保存前必须明确新增库存") for item in confirmations) and not option_value(
        options,
        "output_confirmed",
    ):
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(gather_facts(target, location, crop)),
            rules_applied=tuple(rules),
            confirmations=("需要先确认实际产出数量、单位、位置和资源状态，不能直接保存空产出采集草案。",),
            warnings=tuple(confirmations),
            player_message="采集目标已识别，但保存前必须补明确产出数量和资源状态。",
            proposed_delta=proposed_delta,
            narrative_constraints=(
                "Ask the GM/player to provide output item id, quantity, unit, location and resource state before commit.",
            ),
        )

    return ResolutionResult(
        status="ready",
        facts_used=tuple(gather_facts(target, location, crop)),
        rules_applied=tuple(rules),
        warnings=tuple(confirmations),
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
    target_query = option_value(options, "target")
    if not target_query:
        return ActionValidationResult(missing_required=("target",))
    target = resolve_entity(conn, str(target_query))
    if not target:
        return ActionValidationResult(errors=(f"target not found: {target_query}",))
    location_query = option_value(options, "location") or option_value(options, "destination")
    location = resolve_location(conn, str(location_query)) if location_query else location_detail_row(conn, meta.get("current_location_id"))
    if location and "description_short" not in location.keys():
        location = location_detail_row(conn, location["id"])
    crop = crop_plot_for_entity(conn, target["id"])
    blockers = gather_blockers(target_query, target, location, crop, meta)
    errors = list(blockers)
    warnings: list[str] = []
    if delta.get("intent") != "gather":
        warnings.append("delta intent is not gather")
    expected_location_id = location["id"] if location else meta.get("current_location_id")
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
        if payload.get("travel_required") is True and expected_location_id == meta.get("current_location_id"):
            errors.append(f"events[{index}].payload.travel_required must be false at current location")
    if "upsert_entities" not in delta:
        warnings.append("delta has no upsert_entities field for gathered output")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def render_palette_gather_preview(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
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
        f"| 地点 | {location_query or meta.get('current_location_id', '当前地点未解析')} |",
        f"| 原始行动 | {option_value(options, 'user_text') or option_value(options, 'target') or '采集候选素材'} |",
        "",
    ]
    if candidate is None:
        lines.extend(["### 错误", f"- palette not found: {palette_id}"])
        return "\n".join(lines)

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
        return "\n".join(lines)

    delta = build_palette_gather_delta(conn, candidate, options)
    lines.extend(
        [
            "保存前必须由 GM 按实际采样、数量和资源状态改写。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return "\n".join(lines)


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
        return ResolutionResult(
            status="blocked",
            warnings=validation.errors,
            player_message=validation.errors[0],
            narrative_constraints=("Do not invent gathered output from an invalid palette candidate.",),
        )
    if candidate is None:
        return ResolutionResult(status="blocked", warnings=(f"palette not found: {palette_id}",))
    entry = candidate["entry"]
    if candidate["status"] != "available":
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=(palette_id,),
            confirmations=(f"候选素材 `{palette_id}` 仍是 {candidate['status']}，需要观察、采样或询问后才能保存采集产出。",),
            warnings=validation.warnings,
            player_message="这还是候选线索，不能直接加入库存或确认新材料。",
            narrative_constraints=("Describe clue text only; ask for sampling or verification before saving gathered output.",),
        )
    return ResolutionResult(
        status="ready",
        facts_used=(palette_id,),
        warnings=validation.warnings,
        proposed_delta=build_palette_gather_delta(conn, candidate, options),
        player_message=f"候选素材 {entry.get('name', palette_id)} 可作为本回合采集候选；保存前仍需确认数量和资源状态。",
        narrative_constraints=(
            "Use gather_turn.md for the response.",
            "Do not invent output quantity, quality or depletion state outside the approved delta.",
            "Mention that this result came from a palette candidate.",
        ),
    )


def build_palette_gather_delta(conn: sqlite3.Connection, candidate: dict[str, Any], options: Any) -> dict[str, Any]:
    meta = get_meta(conn)
    location_id = meta.get("current_location_id")
    entry = candidate["entry"]
    entity = palette_entry_to_entity(entry, visibility="known", location_id=location_id)
    payload = {
        **palette_candidate_payload(candidate),
        "target_id": entity["id"],
        "target_type": entity["type"],
        "location_id": location_id,
        "output_quantity_required": True,
        "resource_state_update_required": True,
    }
    summary = f"采集候选素材：{entry.get('name', entry.get('id'))}；数量和资源状态待 GM 确认。"
    return {
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
    target_query: str | None,
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    crop: sqlite3.Row | None,
    meta: dict[str, str],
) -> list[str]:
    blockers: list[str] = []
    current_location_id = meta.get("current_location_id")
    if not target_query:
        blockers.append("目标未指定：保存前必须明确采集对象和产出。")
    elif not target:
        blockers.append(f"采集目标未找到：{target_query}")
    if not location:
        blockers.append("采集地点未解析：需要确认当前位置或目的地。")
    elif current_location_id and location["id"] != current_location_id:
        blockers.append(f"目标地点不是当前位置：当前在 {current_location_id}，需要先结算 travel 或同回合明确旅行耗时/风险。")
    if target and location and target["location_id"] and target["location_id"] != location["id"]:
        blockers.append(f"目标不在指定地点：{target['location_id']}；可能需要改地点或先 travel。")
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
        facts.append(str(crop["crop_entity_id"]))
    return list(dict.fromkeys(item for item in facts if item))


def gather_player_message(
    target_query: str | None,
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    meta: dict[str, str],
    blocking: list[str],
) -> str:
    if location and meta.get("current_location_id") and location["id"] != meta.get("current_location_id"):
        return f"你现在不在 {location['name']}。可以先前往该地点，再采集 {target_query or '目标资源'}。"
    if target and location and target["location_id"] and target["location_id"] != location["id"]:
        return f"{target['name']} 不在 {location['name']}。需要改地点、改目标，或先移动到对象所在地点。"
    return blocking[0] if blocking else "采集行动需要更多信息。"


def gather_repair_options(
    target_query: str | None,
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    meta: dict[str, str],
    blocking: list[str],
) -> tuple[RepairOption, ...]:
    options: list[RepairOption] = []
    current_location_id = meta.get("current_location_id")
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
    if target and target["location_id"] and target["location_id"] != current_location_id:
        options.append(
            RepairOption(
                id="travel_to_target_location",
                label="前往目标所在地点",
                action="travel",
                options={"destination": target["location_id"], "pace": "normal"},
                effect=f"移动到 {target['location_id']} 后重新采集",
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
        ActionOptionSpec("target", "target crop/resource/item id/name/alias"),
        ActionOptionSpec("location", "location id/name/alias; defaults to current location"),
        ActionOptionSpec("palette_id", "palette candidate id to consume under gather rules", dest="palette-id"),
        ActionOptionSpec("output_confirmed", "GM/human-edited delta includes explicit output quantity", dest="output-confirmed"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    keywords=("收", "采", "采集", "挖", "割", "取", "捡", "收获", "能吃", "食物"),
    semantic_labels=("gather", "harvest", "collect", "forage"),
    inference_priority=50,
    validate_request=validate_gather_request,
    resolve=resolve_gather,
    validate_delta=validate_gather_delta,
)
