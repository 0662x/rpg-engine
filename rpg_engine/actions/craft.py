from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..palette import find_palette_candidate, palette_candidate_payload
from ..redaction import redact_hidden_entity_refs
from ..visibility import can_read_hidden, normalize_visibility_view
from ..render import parse_json
from ..preview import (
    build_craft_delta,
    craft_confirmations,
    craft_warnings,
    current_location_row,
    primary_energy_label,
    recipe_material_terms,
    render_craft_preview,
    resolve_materials,
    resolve_recipe,
    split_terms,
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


def redact_craft_value(conn: sqlite3.Connection, value: Any, *, should_redact: bool) -> Any:
    return redact_hidden_entity_refs(conn, value, drop_empty=False) if should_redact else value


def render_craft_text(conn: sqlite3.Connection, text: str, *, should_redact: bool) -> str:
    return str(redact_hidden_entity_refs(conn, text, drop_empty=False)) if should_redact else text


def preview_craft(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    should_redact = should_redact_action(context)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return render_palette_craft_preview(campaign, conn, options, str(palette_id), should_redact=should_redact)
    assistant_shape = hasattr(options, "output")
    return render_craft_preview(
        conn,
        project_query=option_value(options, "project") or (
            option_value(options, "target") if assistant_shape else None
        ),
        target=(
            option_value(options, "output") or option_value(options, "destination")
            if assistant_shape
            else option_value(options, "target")
        ),
        materials_text=option_value(options, "materials"),
        time_cost=option_value(options, "time_cost"),
        user_text=option_value(options, "user_text"),
    )


def craft_target_value(options: Any) -> Any:
    assistant_shape = hasattr(options, "output")
    if assistant_shape:
        return option_value(options, "output") or option_value(options, "destination") or option_value(options, "target")
    return option_value(options, "target")


def resolve_craft_inputs(conn: sqlite3.Connection, options: Any) -> dict[str, Any]:
    meta = get_meta(conn)
    if hasattr(options, "output"):
        project_query = option_value(options, "project") or option_value(options, "target")
    else:
        project_query = option_value(options, "project")
    target = craft_target_value(options)
    project = resolve_entity(conn, str(project_query)) if project_query else None
    target_entity = resolve_entity(conn, str(target)) if target else None
    recipe = resolve_recipe(conn, str(target) if target else None) or resolve_recipe(conn, str(project_query) if project_query else None)
    recipe_profile = parse_json(recipe["details_json"], {}).get("recipe_profile") if recipe else None
    material_terms = split_terms(option_value(options, "materials"))
    if not material_terms:
        material_terms = recipe_material_terms(recipe_profile)
    materials = resolve_materials(conn, material_terms, meta)
    location = current_location_row(conn, meta)
    pc = conn.execute("select * from entities where id = (select value from meta where key='player_entity_id')").fetchone()
    return {
        "meta": meta,
        "location": location,
        "pc_details": parse_json(pc["details_json"], {}) if pc else {},
        "project_query": project_query,
        "target": target,
        "project": project,
        "target_entity": target_entity,
        "recipe": recipe,
        "recipe_profile": recipe_profile,
        "materials": materials,
        "time_cost": option_value(options, "time_cost"),
    }


def validate_craft_request(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        candidate = find_palette_candidate(campaign, conn, str(palette_id), intent="craft")
        return validate_palette_craft_candidate(candidate, str(palette_id))
    if not craft_target_value(options):
        return ActionValidationResult(missing_required=("target",))
    return ActionValidationResult()


def resolve_craft(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    should_redact = should_redact_action(context_data)
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return resolve_palette_craft(campaign, conn, options, str(palette_id), should_redact=should_redact)
    data = resolve_craft_inputs(conn, options)
    confirmations = craft_confirmations(
        data["project_query"],
        data["project"],
        data["target"],
        data["target_entity"],
        data["materials"],
        data["time_cost"],
        data["recipe"],
        data["recipe_profile"],
    )
    warnings = craft_warnings(
        data["project"],
        data["target"] or (data["target_entity"]["name"] if data["target_entity"] else None),
        data["materials"],
        data["pc_details"],
        data["recipe_profile"],
        energy_label=primary_energy_label(data["meta"]),
    )
    blockers = [item for item in confirmations if not item.startswith("无硬性缺口")]
    if not data["location"]:
        blockers.append("当前地点未登记、不可见或不存在：不能保存制作结果。")
    facts = craft_facts(data)
    if blockers:
        safe_blockers = tuple(redact_hidden_entity_refs(conn, tuple(blockers), drop_empty=False))
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(redact_hidden_entity_refs(conn, tuple(facts), drop_empty=False)),
            confirmations=safe_blockers,
            warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
            player_message=str(redact_hidden_entity_refs(conn, craft_player_message(data, blockers), drop_empty=False)),
            repair_options=redact_repair_options(conn, craft_repair_options(data, blockers)),
            narrative_constraints=("Ask for target output, available materials/tools, recipe and time before saving craft.",),
        )
    proposed_delta = build_craft_delta(
        conn=conn,
        meta=data["meta"],
        location=data["location"],
        project=data["project"],
        recipe=data["recipe"],
        recipe_profile=data["recipe_profile"],
        target=data["target"],
        target_entity=data["target_entity"],
        materials=data["materials"],
        time_cost=data["time_cost"],
        user_text=option_value(options, "user_text"),
    )
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")
    proposed_delta = redact_hidden_entity_refs(conn, proposed_delta, drop_empty=False)
    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_hidden_entity_refs(conn, tuple(facts), drop_empty=False)),
        rules_applied=tuple(rules),
        warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
        proposed_delta=proposed_delta,
        player_message="制作预演已准备好，可以保存材料、耗时和产出变化。",
        narrative_constraints=(
            "Use craft_turn.md for the response.",
            "Do not consume materials or create output entities outside the approved delta.",
            "Confirm quality, quantity, failure cost and time before final save.",
        ),
    )


def validate_craft_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del context_data
    palette_id = option_value(options, "palette_id")
    if palette_id:
        return validate_palette_craft_delta(campaign, conn, options, delta, str(palette_id))
    data = resolve_craft_inputs(conn, options)
    confirmations = craft_confirmations(
        data["project_query"],
        data["project"],
        data["target"],
        data["target_entity"],
        data["materials"],
        data["time_cost"],
        data["recipe"],
        data["recipe_profile"],
    )
    errors = [item for item in confirmations if not item.startswith("无硬性缺口")]
    warnings: list[str] = []
    if delta.get("intent") != "craft":
        warnings.append("delta intent is not craft")
    expected_location_id = data["location"]["id"] if data["location"] else None
    if not expected_location_id:
        errors.append("当前地点未登记、不可见或不存在：不能校验制作位置。")
    elif delta.get("location_after") and str(delta["location_after"]) != str(expected_location_id):
        errors.append(f"location_after must remain {expected_location_id}")
    for index, event in enumerate(delta.get("events", []) if isinstance(delta.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("project_id") and data["project"] and str(payload["project_id"]) != str(data["project"]["id"]):
            errors.append(f"events[{index}].payload.project_id must be {data['project']['id']}")
        if payload.get("recipe_id") and data["recipe"] and str(payload["recipe_id"]) != str(data["recipe"]["id"]):
            errors.append(f"events[{index}].payload.recipe_id must be {data['recipe']['id']}")
        if payload.get("target_id") and data["target_entity"] and str(payload["target_id"]) != str(data["target_entity"]["id"]):
            errors.append(f"events[{index}].payload.target_id must be {data['target_entity']['id']}")
        if expected_location_id and payload.get("location_id") and str(payload["location_id"]) != str(expected_location_id):
            errors.append(f"events[{index}].payload.location_id must be {expected_location_id}")
    if not delta.get("upsert_entities"):
        warnings.append("craft delta does not define output or project updates")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def render_palette_craft_preview(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> str:
    candidate = find_palette_candidate(campaign, conn, palette_id, intent="craft")
    lines = [
        "## 制作候选预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 候选素材 | `{palette_id}` |",
        f"| 制作目标 | {craft_target_value(options) or '未明确'} |",
        f"| 材料 | {option_value(options, 'materials') or '未明确'} |",
        f"| 耗时 | {option_value(options, 'time_cost') or '未明确'} |",
        "",
    ]
    if candidate is None:
        lines.extend(["### 错误", f"- palette not found: {palette_id}"])
        return render_craft_text(conn, "\n".join(lines), should_redact=should_redact)
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
            "- palette 可以参与制作计划或配方/材料草案，但不是库存事实。",
            "- 材料消耗、产物、品质、失败代价和耗时必须由 delta 显式表达。",
            "- `confirm_required` / `clue_only` 不能直接当作已持有材料消耗。",
            "",
            "### Delta 草案",
        ]
    )
    validation = validate_palette_craft_candidate(candidate, palette_id)
    if validation.errors:
        lines.extend(f"- {item}" for item in validation.errors)
        return render_craft_text(conn, "\n".join(lines), should_redact=should_redact)
    if not current_location_row(conn, get_meta(conn)):
        lines.append("当前地点不可见，不能生成保存草案。")
        return render_craft_text(conn, "\n".join(lines), should_redact=should_redact)
    delta = build_palette_craft_delta(conn, candidate, options, should_redact=should_redact)
    lines.extend(
        [
            "保存后只记录制作候选计划；不会直接扣材料或创建成品。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return render_craft_text(conn, "\n".join(lines), should_redact=should_redact)


def validate_palette_craft_candidate(candidate: dict[str, Any] | None, palette_id: str) -> ActionValidationResult:
    if candidate is None:
        return ActionValidationResult(errors=(f"palette not found: {palette_id}",))
    entry = candidate["entry"]
    save_as = entry.get("save_as") if isinstance(entry.get("save_as"), dict) else {}
    if entry.get("_kind") not in {"material"} and str(save_as.get("type", "")) not in {"recipe", "project"}:
        return ActionValidationResult(errors=(f"palette candidate is not material/recipe: {palette_id}",))
    if candidate["status"] in {"locked", "out_of_context"}:
        return ActionValidationResult(errors=(f"palette candidate is {candidate['status']}: {palette_id}",))
    if candidate["status"] in {"confirm_required", "clue_only"}:
        return ActionValidationResult(warnings=(f"palette candidate requires confirmation before material consumption: {palette_id}",))
    return ActionValidationResult()


def resolve_palette_craft(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    palette_id: str,
    *,
    should_redact: bool = True,
) -> ResolutionResult:
    candidate = find_palette_candidate(campaign, conn, palette_id, intent="craft")
    validation = validate_palette_craft_candidate(candidate, palette_id)
    if validation.errors:
        safe_errors = tuple(redact_craft_value(conn, validation.errors, should_redact=should_redact))
        return ResolutionResult(
            status="blocked",
            warnings=safe_errors,
            player_message=safe_errors[0],
            narrative_constraints=("Do not invent craft inputs from an invalid palette candidate.",),
        )
    if candidate is None:
        safe_palette_id = str(redact_craft_value(conn, palette_id, should_redact=should_redact))
        return ResolutionResult(status="blocked", warnings=(f"palette not found: {safe_palette_id}",))
    if not current_location_row(conn, get_meta(conn)):
        return ResolutionResult(
            status="needs_confirmation",
            warnings=("当前地点未登记、不可见或不存在：不能保存制作候选计划。",),
            player_message="当前地点不可见，不能生成制作候选保存草案。",
            narrative_constraints=("Ask the player to resolve current location before saving craft output.",),
        )
    entry = redact_craft_value(conn, candidate["entry"], should_redact=should_redact) or {}
    display_name = str(entry.get("name") or palette_id)
    return ResolutionResult(
        status="ready",
        facts_used=(str(redact_craft_value(conn, palette_id, should_redact=should_redact)),),
        warnings=tuple(redact_craft_value(conn, tuple(validation.warnings), should_redact=should_redact)),
        proposed_delta=build_palette_craft_delta(conn, candidate, options, should_redact=should_redact),
        player_message=f"制作候选 {display_name} 已准备好；保存后只记录计划，不扣材料或创建成品。",
        narrative_constraints=(
            "Use craft_turn.md for the response.",
            "Do not consume materials or create output entities outside an approved craft delta.",
            "Do not treat unconfirmed palette materials as inventory.",
        ),
    )


def build_palette_craft_delta(
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
    entry = redact_craft_value(conn, candidate["entry"], should_redact=should_redact) or {}
    target = craft_target_value(options) or str(entry.get("name") or entry.get("id"))
    payload = {
        **redact_craft_value(conn, palette_candidate_payload(candidate), should_redact=should_redact),
        "target": target,
        "location_id": location_id,
        "materials_text": option_value(options, "materials"),
        "time_cost": option_value(options, "time_cost"),
        "material_consumption_required": True,
        "output_delta_required": True,
        "resource_state_update_required": True,
        "clue_stage": "hinted",
    }
    summary = f"制作候选计划：{entry.get('name', entry.get('id'))}；材料消耗和产物待 GM 确认。"
    delta = {
        "user_text": option_value(options, "user_text") or f"制作计划：{target}",
        "intent": "craft",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": meta.get("current_time_block"),
        "location_before": location_id,
        "location_after": location_id,
        "summary": summary,
        "events": [
            {
                "type": "craft_plan",
                "title": "制作候选计划",
                "summary": summary,
                "payload": payload,
                "source": "palette_craft_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }
    return redact_craft_value(conn, delta, should_redact=should_redact)


def validate_palette_craft_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: Any,
    delta: dict[str, Any],
    palette_id: str,
) -> ActionValidationResult:
    candidate = find_palette_candidate(campaign, conn, palette_id, intent="craft")
    validation = validate_palette_craft_candidate(candidate, palette_id)
    errors = list(validation.errors)
    warnings = list(validation.warnings)
    if delta.get("intent") != "craft":
        warnings.append("delta intent is not craft")
    current = current_location_row(conn, get_meta(conn))
    expected_location_id = current["id"] if current else None
    if not expected_location_id:
        errors.append("palette craft delta requires a visible current location")
    elif delta.get("location_after") and str(delta["location_after"]) != str(expected_location_id):
        errors.append(f"palette craft delta must keep location_after at current location {expected_location_id}")
    payloads = [event.get("payload", {}) for event in delta.get("events", []) if isinstance(event, dict)]
    if not any(isinstance(payload, dict) and payload.get("palette_id") == palette_id for payload in payloads):
        errors.append(f"craft delta must include events[].payload.palette_id {palette_id}")
    if candidate and candidate["status"] != "available" and delta.get("upsert_entities"):
        errors.append(f"palette candidate {palette_id} is {candidate['status']} and cannot create craft output directly")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def craft_facts(data: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    for key in ("location", "project", "target_entity", "recipe"):
        row = data.get(key)
        if row:
            facts.append(str(row["id"]))
    for item in data.get("materials", []):
        entity = item.get("entity")
        if entity:
            facts.append(str(entity["id"]))
    return list(dict.fromkeys(facts))


def craft_player_message(data: dict[str, Any], blockers: list[str]) -> str:
    target = data.get("target") or (data["target_entity"]["name"] if data.get("target_entity") else "目标成品")
    missing = [item for item in blockers if "未找到" in item or "未指定" in item or "未匹配" in item]
    if missing:
        return f"现在还不能可靠完成 {target}。需要先补齐材料、配方、耗时或成品定义。"
    return f"{target} 需要 GM 先确认工艺步骤、失败代价和资源变化。"


def craft_repair_options(data: dict[str, Any], blockers: list[str]) -> tuple[RepairOption, ...]:
    target = str(data.get("target") or (data["target_entity"]["name"] if data.get("target_entity") else "目标成品"))
    options: list[RepairOption] = []
    if any("材料" in item for item in blockers):
        options.append(
            RepairOption(
                id="list_materials",
                label="先列出材料和工具",
                action="routine",
                options={"task": f"整理{target}所需材料", "focus": "材料、工具、消耗量、剩余量"},
                effect="不制作成品，只整理缺口清单",
                risk_level="none",
                requires_confirmation=False,
            )
        )
    if any("配方" in item or "项目" in item for item in blockers):
        options.append(
            RepairOption(
                id="create_or_select_project",
                label="确认制作项目/配方",
                action="craft",
                options={"target": target},
                effect="明确是已有项目、已有配方，还是新制作计划",
            )
        )
    if any("耗时" in item for item in blockers):
        options.append(
            RepairOption(
                id="estimate_time",
                label="补充耗时",
                action="craft",
                options={"target": target, "time_cost": "30m"},
                effect="用明确耗时重新预演制作",
            )
        )
    options.append(
        RepairOption(
            id="cancel_craft",
            label="暂不制作",
            effect="不消耗材料，不推进时间",
            risk_level="none",
            requires_confirmation=False,
        )
    )
    return tuple(options)


CRAFT_RESOLVER = ActionResolverSpec(
    name="craft",
    preview=preview_craft,
    response_template="craft_turn.md",
    option_specs=option_specs_for(
        ActionOptionSpec("project", "project entity id/name/alias"),
        ActionOptionSpec("target", "target item/output name or entity"),
        ActionOptionSpec("materials", "comma-separated materials/tools to check"),
        ActionOptionSpec("time_cost", "estimated crafting time", dest="time"),
        ActionOptionSpec("palette_id", "material or recipe palette candidate id used in a craft plan", dest="palette-id"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    taxonomy=ActionTaxonomySpec(
        terms=(
            *taxonomy_terms("zh-Hans", ("做", "修")),
            *taxonomy_terms(
                "zh-Hans",
                ("制作", "修理", "装配", "校准", "做个", "做一个", "做成", "做出"),
                roles=("playable.craft", "preview.mismatch", "simple"),
            ),
            *taxonomy_terms(
                "zh-Hans",
                ("加工", "发酵", "升级", "改造"),
                roles=("playable.craft", "simple"),
            ),
            *taxonomy_terms(
                "en",
                ("craft", "make", "build", "repair", "fix"),
                roles=("playable.craft", "preview.mismatch", "simple"),
            ),
        ),
        semantic_labels=("craft", "repair", "build", "upgrade"),
        inference_priority=40,
    ),
    validate_request=validate_craft_request,
    resolve=resolve_craft,
    validate_delta=validate_craft_delta,
)
