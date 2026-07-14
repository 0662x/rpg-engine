from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..palette import find_palette_candidate, palette_candidate_payload
from ..preview import current_location_label
from ..redaction import redact_hidden_entity_refs
from ..render import parse_json
from ..ux import RepairOption
from ..visibility import can_read_hidden, normalize_visibility_view
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .taxonomy import ActionTaxonomySpec, taxonomy_terms


def explore_target_query(options: Any) -> str | None:
    target = option_value(options, "target") or option_value(options, "location")
    return str(target) if target else None


def allows_unknown_lead(options: Any) -> bool:
    value = option_value(options, "unknown_lead")
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "未知线索", "unknown"}


def action_request_view(context_data: dict[str, Any] | None) -> str:
    return normalize_visibility_view(str((context_data or {}).get("view") or "player"))


def redact_explore_value(conn: sqlite3.Connection, value: Any, *, should_redact: bool) -> Any:
    return redact_hidden_entity_refs(conn, value, drop_empty=False) if should_redact else value


def preview_explore(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> str:
    request_view = action_request_view(context_data)
    should_redact = not can_read_hidden(request_view)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return render_palette_explore_preview(campaign, conn, options, str(palette_id), should_redact=should_redact)
    target_query = explore_target_query(options)
    approach = option_value(options, "approach")
    user_text = option_value(options, "user_text") or target_query or "探索"
    meta = get_meta(conn)
    current_location = current_location_label(conn, meta)
    lines = [
        "## 探索行动预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text} |",
        f"| 当前地点 | {current_location} |",
        f"| 探索目标 | {target_query or '未明确'} |",
        f"| 方法 | {approach or '未明确'} |",
    ]
    if not target_query:
        lines.extend(
            [
                "",
                "### 必须确认",
                "- 探索目标未明确。",
                "",
                "### Delta 草案",
                "缺少探索目标，不能生成保存草案。",
            ]
        )
        text = "\n".join(lines)
        return str(redact_hidden_entity_refs(conn, text)) if should_redact else text

    entity = resolve_entity(conn, str(target_query), view=request_view)
    lines.extend(["", "### 已知目标"])
    if entity:
        details = parse_json(entity["details_json"], {})
        lines.extend(
            [
                "| 字段 | 值 |",
                "|------|----|",
                f"| ID | `{entity['id']}` |",
                f"| 类型 | {entity['type']} |",
                f"| 名称 | {entity['name']} |",
                f"| 摘要 | {entity['summary'] or '无'} |",
            ]
        )
        if details.get("safety"):
            lines.append(f"| 安全等级 | {details['safety']} |")
    else:
        lines.extend(
            [
                "- 未命中现有可见实体；探索只能产生线索候选，不能直接确认新事实。",
            ]
        )

    lines.extend(
        [
            "",
            "### 结算边界",
            "- 先描述可观察迹象，再等待玩家选择是否深入、靠近、触碰或撤退。",
            "- 发现新事实前必须用 delta 显式保存事件、线索或实体。",
            "- hidden 信息不能因探索预演直接泄露给玩家。",
            "",
            "### Delta 草案",
        ]
    )
    if entity is None and not allows_unknown_lead(options):
        lines.append("目标未解析为现有可见实体，不能生成保存草案。")
    else:
        delta = build_explore_delta(
            target_query=str(target_query),
            entity=entity,
            approach=approach,
            user_text=str(user_text),
            unknown_lead=entity is None,
        )
        lines.extend(
            [
                "保存前必须由 GM 按实际线索、风险和耗时改写。",
                "",
                "```json",
                json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    text = "\n".join(lines)
    return str(redact_hidden_entity_refs(conn, text)) if should_redact else text


def validate_explore_request(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    request_view = action_request_view(context_data)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        candidate = find_palette_candidate(
            campaign,
            conn,
            str(palette_id),
            location_query=option_value(options, "location"),
            intent="explore",
        )
        return validate_palette_explore_candidate(candidate, str(palette_id))
    target_query = explore_target_query(options)
    if not target_query:
        return ActionValidationResult(missing_required=("target",))
    target = resolve_entity(conn, target_query, view=request_view)
    if not target and not allows_unknown_lead(options):
        return ActionValidationResult(errors=(f"target not found: {target_query}",))
    return ActionValidationResult()


def resolve_explore(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    request_view = action_request_view(context_data)
    should_redact = not can_read_hidden(request_view)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return resolve_palette_explore(campaign, conn, options, str(palette_id), should_redact=should_redact)
    target_query = explore_target_query(options)
    if not target_query:
        return ResolutionResult(
            status="needs_confirmation",
            confirmations=("探索目标未明确。",),
            player_message="需要先说明你要探索什么。",
            repair_options=(
                RepairOption(
                    id="clarify_explore_target",
                    label="补充探索目标",
                    action="explore",
                    effect="说明地点、对象、痕迹或未知线索",
                    risk_level="none",
                    requires_confirmation=False,
                ),
            ),
        )
    entity = resolve_entity(conn, target_query, view=request_view)
    if not entity and not allows_unknown_lead(options):
        safe_target_query = (
            str(redact_hidden_entity_refs(conn, str(target_query), drop_empty=False))
            if should_redact
            else str(target_query)
        )
        approach = option_value(options, "approach")
        safe_approach = redact_hidden_entity_refs(conn, approach, drop_empty=False) if should_redact else approach
        return ResolutionResult(
            status="blocked",
            confirmations=(f"target not found: {safe_target_query}",),
            player_message=f"我没找到“{safe_target_query}”对应的已知可见对象。可以改成已知对象，或明确把它当作未知线索探索。",
            repair_options=(
                RepairOption(
                    id="mark_unknown_lead",
                    label="作为未知线索探索",
                    action="explore",
                    options={
                        "target": safe_target_query,
                        "approach": safe_approach,
                        "unknown_lead": True,
                    },
                    effect="保存为 unknown_lead，不直接确认新事实",
                ),
            ),
        )
    return ResolutionResult(
        status="ready",
        facts_used=(str(entity["id"]),) if entity else (),
        proposed_delta=redact_explore_value(
            conn,
            build_explore_delta(
                target_query=str(target_query),
                entity=entity,
                approach=option_value(options, "approach"),
                user_text=option_value(options, "user_text") or str(target_query),
                unknown_lead=entity is None,
            ),
            should_redact=should_redact,
        ),
        player_message="探索预演已准备好；保存后只确认可观察线索，不泄漏 hidden 信息。",
        narrative_constraints=("Use scene_entry.md for exploration response.", "Do not reveal hidden facts unless delta records discovery."),
    )


def validate_explore_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    request_view = action_request_view(context_data)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return validate_palette_explore_delta(campaign, conn, options, delta, str(palette_id))
    target_query = explore_target_query(options)
    if not target_query:
        return ActionValidationResult(missing_required=("target",))
    target = resolve_entity(conn, target_query, view=request_view)
    unknown_lead = allows_unknown_lead(options)
    if not target and not unknown_lead:
        return ActionValidationResult(errors=(f"target not found: {target_query}",))
    errors: list[str] = []
    warnings: list[str] = []
    if delta.get("intent") != "explore":
        warnings.append("delta intent is not explore")
    target_id = str(target["id"]) if target else None
    events = delta.get("events", []) if isinstance(delta.get("events", []), list) else []
    found_target_payload = False
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if unknown_lead and payload.get("target_kind") == "unknown_lead" and payload.get("needs_gm_resolution") is True:
            found_target_payload = True
            continue
        if payload.get("target_id") is not None:
            found_target_payload = True
            if target_id and str(payload["target_id"]) != target_id:
                errors.append(f"events[{index}].payload.target_id must be {target_id}")
    if not found_target_payload:
        errors.append("explore delta must include events[].payload.target_id or explicit unknown_lead payload")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def render_palette_explore_preview(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> str:
    candidate = find_palette_candidate(campaign, conn, palette_id, location_query=option_value(options, "location"), intent="explore")
    target_query = explore_target_query(options)
    approach = option_value(options, "approach")
    lines = [
        "## 探索候选预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 候选素材 | `{palette_id}` |",
        f"| 探索目标 | {target_query or '按候选素材线索'} |",
        f"| 方法 | {approach or '未明确'} |",
        "",
    ]
    if candidate is None:
        lines.extend(["### 错误", f"- palette not found: {palette_id}"])
        text = "\n".join(lines)
        return str(redact_hidden_entity_refs(conn, text)) if should_redact else text
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
            "- 探索候选只能确认可观察迹象。",
            "- 新地点、物种、势力和遭遇不能在探索预演中直接变成 known 事实。",
            "- 若要保存，delta 必须保留 palette 来源并标记 `needs_gm_resolution`。",
            "",
            "### Delta 草案",
        ]
    )
    validation = validate_palette_explore_candidate(candidate, palette_id)
    if validation.errors:
        lines.extend(f"- {item}" for item in validation.errors)
        text = "\n".join(lines)
        return str(redact_hidden_entity_refs(conn, text)) if should_redact else text
    delta = redact_explore_value(conn, build_palette_explore_delta(candidate, options), should_redact=should_redact)
    lines.extend(
        [
            "保存前必须由 GM 按实际线索、风险和耗时改写。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    text = "\n".join(lines)
    return str(redact_hidden_entity_refs(conn, text)) if should_redact else text


def validate_palette_explore_candidate(candidate: dict[str, Any] | None, palette_id: str) -> ActionValidationResult:
    if candidate is None:
        return ActionValidationResult(errors=(f"palette not found: {palette_id}",))
    if candidate["status"] in {"locked", "out_of_context"}:
        return ActionValidationResult(errors=(f"palette candidate is {candidate['status']}: {palette_id}",))
    return ActionValidationResult()


def resolve_palette_explore(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> ResolutionResult:
    candidate = find_palette_candidate(campaign, conn, palette_id, location_query=option_value(options, "location"), intent="explore")
    validation = validate_palette_explore_candidate(candidate, palette_id)
    if validation.errors:
        safe_errors = (
            tuple(redact_hidden_entity_refs(conn, validation.errors, drop_empty=False))
            if should_redact
            else tuple(validation.errors)
        )
        return ResolutionResult(
            status="blocked",
            warnings=safe_errors,
            player_message=safe_errors[0],
            narrative_constraints=("Do not invent facts from a locked or missing palette candidate.",),
        )
    if candidate is None:
        safe_palette_id = str(redact_hidden_entity_refs(conn, palette_id, drop_empty=False)) if should_redact else palette_id
        return ResolutionResult(status="blocked", warnings=(f"palette not found: {safe_palette_id}",))
    entry = redact_explore_value(conn, candidate["entry"], should_redact=should_redact) or {}
    display_name = str(entry.get("name") or palette_id)
    return ResolutionResult(
        status="ready",
        facts_used=(str(redact_hidden_entity_refs(conn, palette_id, drop_empty=False)) if should_redact else palette_id,),
        warnings=(f"候选状态为 {candidate['status']}；保存后仍只确认线索，不确认 hidden 真相。",),
        proposed_delta=redact_explore_value(conn, build_palette_explore_delta(candidate, options), should_redact=should_redact),
        player_message=f"探索候选 {display_name} 已准备好；保存后只记录可观察线索。",
        narrative_constraints=(
            "Use scene_entry.md for exploration response.",
            "Do not reveal hidden facts unless delta records discovery.",
            "Do not convert palette candidate to known entity in this explore step.",
        ),
    )


def build_palette_explore_delta(candidate: dict[str, Any], options: Any) -> dict[str, Any]:
    entry = candidate["entry"]
    target_query = explore_target_query(options) or str(entry.get("name") or entry.get("id"))
    payload = {
        **palette_candidate_payload(candidate),
        "target_query": target_query,
        "target_id": None,
        "target_kind": "palette_candidate",
        "approach": option_value(options, "approach"),
    }
    summary = f"探索候选线索：{entry.get('name', entry.get('id'))}；仅确认可观察迹象。"
    return {
        "changed": True,
        "intent": "explore",
        "user_text": option_value(options, "user_text") or target_query,
        "summary": summary,
        "events": [
            {
                "type": "explore",
                "title": "探索候选线索",
                "summary": summary,
                "payload": payload,
                "source": "palette_explore_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }


def validate_palette_explore_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    delta: dict[str, Any],
    palette_id: str,
) -> ActionValidationResult:
    candidate = find_palette_candidate(campaign, conn, palette_id, location_query=option_value(options, "location"), intent="explore")
    validation = validate_palette_explore_candidate(candidate, palette_id)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    if delta.get("intent") != "explore":
        warnings.append("delta intent is not explore")
    payloads = [
        event.get("payload", {})
        for event in delta.get("events", []) if isinstance(event, dict)
    ]
    if not any(isinstance(payload, dict) and payload.get("palette_id") == palette_id for payload in payloads):
        errors.append(f"explore delta must include events[].payload.palette_id {palette_id}")
    if delta.get("upsert_entities"):
        warnings.append("palette explore delta should not create known entities before confirmation")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def build_explore_delta(
    *,
    target_query: str,
    entity: sqlite3.Row | None,
    approach: Any,
    user_text: str,
    unknown_lead: bool = False,
) -> dict[str, Any]:
    payload = {
        "target_query": target_query,
        "target_id": entity["id"] if entity else None,
        "approach": approach,
        "needs_gm_resolution": True,
    }
    if unknown_lead:
        payload["target_kind"] = "unknown_lead"
    return {
        "changed": True,
        "intent": "explore",
        "user_text": user_text,
        "summary": f"探索{target_query}，需要 GM 根据可见事实结算线索与风险。",
        "events": [
            {
                "type": "explore",
                "title": "探索行动结算",
                "summary": f"探索{target_query}；预演不自动确认隐藏事实。",
                "payload": payload,
                "source": "explore_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }


EXPLORE_RESOLVER = ActionResolverSpec(
    name="explore",
    preview=preview_explore,
    response_template="scene_entry.md",
    option_specs=option_specs_for(
        ActionOptionSpec(
            "target",
            "place, object, clue or area to inspect",
            required=True,
            binding_type="entity_or_text",
            aliases=("object", "clue"),
        ),
        ActionOptionSpec(
            "location",
            "optional location id/name/alias",
            binding_type="entity",
            allowed_entity_types=("location",),
            aliases=("place",),
        ),
        ActionOptionSpec("approach", "how the player explores or handles risk"),
        ActionOptionSpec("unknown_lead", "allow unresolved target as an explicit unknown lead", dest="unknown-lead"),
        ActionOptionSpec("palette_id", "palette candidate id to inspect as a controlled clue", dest="palette-id"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text", ai_fillable=False),
    ),
    taxonomy=ActionTaxonomySpec(
        terms=(
            *taxonomy_terms(
                "zh-Hans",
                ("探索", "调查", "侦查"),
                roles=("preview.mismatch", "simple"),
            ),
            *taxonomy_terms("zh-Hans", ("检查线索",)),
            *taxonomy_terms(
                "zh-Hans",
                ("搜索",),
                roles=("preview.mismatch", "search", "simple"),
            ),
            *taxonomy_terms("zh-Hans", ("搜查", "搜寻"), roles=("search", "simple")),
            *taxonomy_terms(
                "en",
                ("explore", "investigate", "inspect", "scout"),
                roles=("preview.mismatch", "simple"),
            ),
            *taxonomy_terms("en", ("search",), roles=("search", "simple")),
        ),
        semantic_labels=("explore", "inspect", "search", "investigate", "scout"),
        inference_priority=55,
    ),
    validate_request=validate_explore_request,
    resolve=resolve_explore,
    validate_delta=validate_explore_delta,
)
