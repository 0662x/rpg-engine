from __future__ import annotations

import sqlite3
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..palette import find_palette_candidate, palette_candidate_payload
from ..preview import (
    build_social_delta,
    current_location_row,
    location_detail_row,
    render_social_preview,
    social_confirmations,
    social_risks,
)
from ..redaction import redact_hidden_entity_refs
from ..visibility import can_read_hidden, normalize_visibility_view
from ..ux import PlanStep, RepairOption
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .scope import InteractionScope, location_scope


def action_request_view(context_data: dict[str, Any] | None) -> str:
    return normalize_visibility_view(str((context_data or {}).get("view") or "player"))


def should_redact_action(context_data: dict[str, Any] | None) -> bool:
    return not can_read_hidden(action_request_view(context_data))


def redact_social_value(conn: sqlite3.Connection, value: Any, *, should_redact: bool) -> Any:
    return redact_hidden_entity_refs(conn, value, drop_empty=False) if should_redact else value


def preview_social(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    should_redact = should_redact_action(context)
    text = render_social_preview(
        conn,
        npc_query=option_value(options, "npc") or option_value(options, "target"),
        topic=option_value(options, "topic"),
        approach=option_value(options, "approach"),
        user_text=option_value(options, "user_text"),
    )
    palette_id = option_value(options, "palette_id")
    if not palette_id:
        return text
    candidate = find_palette_candidate(campaign, conn, str(palette_id), intent="social")
    combined = text + "\n\n" + render_social_palette_section(candidate, str(palette_id))
    return str(redact_hidden_entity_refs(conn, combined, drop_empty=False)) if should_redact else combined


def resolve_social_inputs(conn: sqlite3.Connection, options: Any) -> dict[str, Any]:
    meta = get_meta(conn)
    npc_query = option_value(options, "npc") or option_value(options, "target")
    npc = resolve_entity(conn, str(npc_query)) if npc_query else None
    character = conn.execute("select * from characters where entity_id = ?", (npc["id"],)).fetchone() if npc else None
    current_location = current_location_row(conn, meta)
    npc_location = location_detail_row(conn, npc["location_id"]) if npc and npc["location_id"] else None
    return {
        "meta": meta,
        "npc_query": npc_query,
        "npc": npc,
        "character": character,
        "current_location": current_location,
        "npc_location": npc_location,
        "topic": option_value(options, "topic"),
        "approach": option_value(options, "approach"),
    }


def validate_social_request(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        candidate = find_palette_candidate(campaign, conn, str(palette_id), intent="social")
        palette_validation = validate_social_palette_candidate(candidate, str(palette_id))
        if palette_validation.errors:
            return palette_validation
    missing = tuple(name for name in ("npc",) if not (option_value(options, name) or option_value(options, "target")))
    return ActionValidationResult(missing_required=missing)


def resolve_social(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    should_redact = should_redact_action(context_data)
    data = resolve_social_inputs(conn, options)
    scope = social_scope(conn, data)
    confirmations = social_confirmations(
        conn,
        data["npc_query"],
        data["npc"],
        data["character"],
        data["topic"],
        data["approach"],
        data["meta"],
    )
    blockers = [item for item in confirmations if not item.startswith("关系变化必须记录")]
    warnings = [item for item in confirmations if item.startswith("关系变化必须记录")]
    warnings.extend(social_risks(data["npc"], data["topic"], data["approach"]))
    facts = social_facts(data)
    if location_blocked_only(blockers) and scope.kind in {"same_parent", "one_hop"}:
        npc_name = data["npc"]["name"] if data["npc"] else str(data["npc_query"])
        current_name = location_name(conn, scope.from_location_id)
        target_name = location_name(conn, scope.target_location_id)
        minutes = scope.estimated_minutes or 2
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(facts),
            confirmations=tuple(blockers),
            warnings=tuple(warnings),
            player_message=(
                f"{npc_name} 不在你当前地点。对方在 {target_name}，你现在在 {current_name}。"
                f"可以先过去再交谈，预计 {minutes} 分钟。"
            ),
            repair_options=(
                RepairOption(
                    id="go_and_talk",
                    label=f"去{target_name}找{npc_name}谈",
                    action="travel",
                    options={"destination": scope.target_location_id, "pace": "normal"},
                    effect="先移动到对方所在地点，再重新预演 social",
                ),
                RepairOption(
                    id="call_from_here",
                    label=f"在当前位置呼唤{npc_name}",
                    action="social",
                    options={
                        "npc": data["npc"]["id"] if data["npc"] else data["npc_query"],
                        "topic": data["topic"],
                        "approach": "远距离呼唤",
                    },
                    effect="不移动，但谈话私密性和细节会下降",
                ),
                RepairOption(
                    id="cancel_social",
                    label="取消交谈",
                    effect="不推进时间，不保存状态",
                    risk_level="none",
                    requires_confirmation=False,
                ),
            ),
            plan=(
                PlanStep(
                    step_id="step:1",
                    action="travel",
                    label=f"前往{target_name}",
                    options={"destination": scope.target_location_id, "pace": "normal"},
                    estimated_minutes=minutes,
                    risk_level="low" if scope.kind == "same_parent" else "medium",
                ),
                PlanStep(
                    step_id="step:2",
                    action="social",
                    label=f"与{npc_name}交谈",
                    options={
                        "npc": data["npc"]["id"] if data["npc"] else data["npc_query"],
                        "topic": data["topic"],
                        "approach": data["approach"],
                    },
                    risk_level="low",
                ),
            ),
            narrative_constraints=("Ask the player whether to move first, call from here, or cancel.",),
        )
    if blockers:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(redact_hidden_entity_refs(conn, tuple(facts), drop_empty=False)),
            confirmations=tuple(redact_hidden_entity_refs(conn, tuple(blockers), drop_empty=False)),
            warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
            narrative_constraints=("Ask for NPC, topic, approach and current-location access before saving social results.",),
        )

    proposed_delta = build_social_delta(
        meta=data["meta"],
        current_location_id=data["current_location"]["id"] if data["current_location"] else None,
        npc=data["npc"],
        character=data["character"],
        topic=data["topic"],
        approach=data["approach"],
        suggested_ticks=[],
        user_text=option_value(options, "user_text"),
    )
    mark_social_no_change_when_low_impact(proposed_delta, data["topic"], data["approach"])
    palette_id = option_value(options, "palette_id")
    palette_warnings: list[str] = []
    palette_facts: list[str] = []
    if palette_id:
        candidate = find_palette_candidate(campaign, conn, str(palette_id), intent="social")
        palette_validation = validate_social_palette_candidate(candidate, str(palette_id))
        if palette_validation.errors:
            safe_errors = tuple(redact_social_value(conn, palette_validation.errors, should_redact=should_redact))
            return ResolutionResult(
                status="blocked",
                facts_used=tuple(redact_social_value(conn, tuple(facts), should_redact=should_redact)),
                warnings=safe_errors,
                player_message=safe_errors[0],
                narrative_constraints=("Do not use invalid palette candidates as confirmed social facts.",),
            )
        if candidate:
            attach_palette_to_social_delta(conn, proposed_delta, candidate, should_redact=should_redact)
            safe_palette_id = str(redact_social_value(conn, str(palette_id), should_redact=should_redact))
            palette_facts.append(safe_palette_id)
            palette_warnings.append(
                f"社交主题关联候选 `{safe_palette_id}`；对话只能询问或记录传闻，不能直接确认派系/文明事实。"
            )
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")
    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_social_value(conn, tuple([*facts, *palette_facts]), should_redact=should_redact)),
        rules_applied=tuple(rules),
        warnings=tuple(redact_social_value(conn, tuple([*warnings, *palette_warnings]), should_redact=should_redact)),
        proposed_delta=redact_social_value(conn, proposed_delta, should_redact=should_redact),
        player_message="社交预演已准备好，可以保存结构化对话后果。",
        narrative_constraints=(
            "Use social_turn.md for the response.",
            "Do not invent trust, attitude, promises or traded items outside the approved delta.",
            "Record relationship and trade consequences explicitly when the interaction changes them.",
        ),
    )


def validate_social_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del context_data
    data = resolve_social_inputs(conn, options)
    confirmations = social_confirmations(
        conn,
        data["npc_query"],
        data["npc"],
        data["character"],
        data["topic"],
        data["approach"],
        data["meta"],
    )
    errors = [item for item in confirmations if not item.startswith("关系变化必须记录")]
    warnings = [item for item in confirmations if item.startswith("关系变化必须记录")]
    if delta.get("intent") != "social":
        warnings.append("delta intent is not social")
    expected_location_id = data["current_location"]["id"] if data.get("current_location") else None
    if not expected_location_id:
        errors.append("当前地点未登记、不可见或不存在：不能校验社交位置。")
    elif delta.get("location_after") and str(delta["location_after"]) != str(expected_location_id):
        errors.append(f"location_after must remain {expected_location_id}")
    for index, event in enumerate(delta.get("events", []) if isinstance(delta.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("npc_id") and data["npc"] and str(payload["npc_id"]) != str(data["npc"]["id"]):
            errors.append(f"events[{index}].payload.npc_id must be {data['npc']['id']}")
        if payload.get("topic") and data["topic"] and str(payload["topic"]) != str(data["topic"]):
            errors.append(f"events[{index}].payload.topic must be {data['topic']}")
        if payload.get("approach") and data["approach"] and str(payload["approach"]) != str(data["approach"]):
            errors.append(f"events[{index}].payload.approach must be {data['approach']}")
    if "upsert_entities" not in delta:
        warnings.append("social delta has no upsert_entities field for relationship/trade updates")
    palette_id = option_value(options, "palette_id")
    if palette_id:
        candidate = find_palette_candidate(campaign, conn, str(palette_id), intent="social")
        palette_validation = validate_social_palette_candidate(candidate, str(palette_id))
        errors.extend(palette_validation.errors)
        warnings.extend(palette_validation.warnings)
        payloads = [
            event.get("payload", {})
            for event in delta.get("events", []) if isinstance(event, dict)
        ]
        if not any(isinstance(payload, dict) and payload.get("palette_id") == str(palette_id) for payload in payloads):
            errors.append(f"social delta must include events[].payload.palette_id {palette_id}")
        if delta.get("upsert_entities"):
            warnings.append("palette social delta should not create or confirm faction/location entities without content review")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def mark_social_no_change_when_low_impact(delta: dict[str, Any], topic: str | None, approach: str | None) -> None:
    text = " ".join([topic or "", approach or ""])
    relationship_required = any(word in text for word in ["承诺", "道歉", "请求", "说服", "威慑", "命名", "邀请", "加入"])
    trade_required = any(word in text for word in ["交易", "交换", "赠送", "送", "给", "食物", "盐", "调料"])
    for event in delta.get("events", []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        payload["relationship_update_required"] = relationship_required
        payload["trade_items_required"] = trade_required
        if not relationship_required:
            payload["no_relationship_change"] = True
        if not trade_required:
            payload["no_trade"] = True


def render_social_palette_section(candidate: dict[str, Any] | None, palette_id: str) -> str:
    lines = [
        "### 社交候选边界",
        "",
        f"- 候选素材：`{palette_id}`",
    ]
    if candidate is None:
        lines.append(f"- 错误：palette not found: {palette_id}")
        return "\n".join(lines)
    entry = candidate["entry"]
    lines.extend(
        [
            f"- 状态：`{candidate['status']}`",
            f"- 类型：`{entry.get('_kind', '')}`",
            f"- 名称：{entry.get('name', '')}",
            "- 该候选只能作为询问主题、传闻或接触线索；不能通过一次社交预演直接确认新势力、新文明或隐藏地点。",
        ]
    )
    return "\n".join(lines)


def validate_social_palette_candidate(candidate: dict[str, Any] | None, palette_id: str) -> ActionValidationResult:
    if candidate is None:
        return ActionValidationResult(errors=(f"palette not found: {palette_id}",))
    if candidate["status"] in {"locked", "out_of_context"}:
        return ActionValidationResult(errors=(f"palette candidate is {candidate['status']}: {palette_id}",))
    return ActionValidationResult()


def attach_palette_to_social_delta(
    conn: sqlite3.Connection,
    delta: dict[str, Any],
    candidate: dict[str, Any],
    *,
    should_redact: bool = True,
) -> None:
    payload = redact_social_value(conn, palette_candidate_payload(candidate), should_redact=should_redact)
    for event in delta.get("events", []):
        if not isinstance(event, dict):
            continue
        event_payload = event.setdefault("payload", {})
        if not isinstance(event_payload, dict):
            continue
        event_payload.update(payload)
        event_payload["topic_kind"] = "palette_candidate"
        break


def social_facts(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    current = data.get("current_location")
    npc = data.get("npc")
    if current:
        facts.append(str(current["id"]))
    if npc:
        facts.append(str(npc["id"]))
    npc_location = data.get("npc_location")
    if npc_location:
        facts.append(str(npc_location["id"]))
    return list(dict.fromkeys(facts))


def social_scope(conn: sqlite3.Connection, data: dict[str, Any]) -> InteractionScope:
    meta = data.get("meta", {})
    npc = data.get("npc")
    return location_scope(
        conn,
        str(meta.get("current_location_id")) if meta.get("current_location_id") else None,
        str(npc["location_id"]) if npc and npc["location_id"] else None,
    )


def location_blocked_only(blockers: list[str]) -> bool:
    return bool(blockers) and all("对象不在当前地点" in item for item in blockers)


def location_name(conn: sqlite3.Connection, location_id: str | None) -> str:
    if not location_id:
        return "未知地点"
    row = location_detail_row(conn, location_id)
    return str(row["name"]) if row else "未知地点"


SOCIAL_RESOLVER = ActionResolverSpec(
    name="social",
    preview=preview_social,
    response_template="social_turn.md",
    option_specs=option_specs_for(
        ActionOptionSpec("npc", "NPC or faction entity id/name/alias"),
        ActionOptionSpec("topic", "topic, promise, trade or question"),
        ActionOptionSpec("approach", "approach, gift, posture or communication method"),
        ActionOptionSpec("palette_id", "palette candidate id used as a rumor/contact topic", dest="palette-id"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    keywords=("说", "问", "交易", "谈", "展示", "拜访", "找", "询问"),
    semantic_labels=("talk", "trade", "ask", "negotiate"),
    inference_priority=30,
    validate_request=validate_social_request,
    resolve=resolve_social,
    validate_delta=validate_social_delta,
)
