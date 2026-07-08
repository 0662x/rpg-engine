from __future__ import annotations

import heapq
import json
import re
import sqlite3
from typing import Any

from .campaign import Campaign
from .actions.policy import clock_query_terms, first_matching_clock, matching_clock_rows
from .db import (
    entity_subtype_visibility_sql,
    entity_type_priority_sql,
    get_meta,
    get_player_entity_id,
    query_tokens,
    resolve_entity,
    sanitize_fts_query,
)
from .entity_access import read_entity
from .palette import render_compact_palette_table, suggest_palette_entries
from .player_resources import (
    primary_energy_detail_key,
    primary_energy_full_value,
    primary_energy_label,
    primary_energy_value,
)
from .render import format_quantity, format_value, parse_json
from .redaction import redact_hidden_entity_refs
from .time_weather import enrich_time_weather_meta, format_time_brief, format_weather_brief
from .visibility import (
    clock_visibility_sql,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalized_text_sql,
)
from .write_guard import add_generated_write_guards


def default_combat_weapon_query(meta: dict[str, str]) -> str | None:
    return meta.get("default_combat_weapon_id") or meta.get("default_weapon_id") or None


def render_combat_preview(
    conn: sqlite3.Connection,
    *,
    target_query: str | None = None,
    weapon_query: str | None = None,
    ammo_query: str | None = None,
    distance: str | None = None,
    ready_state: str | None = None,
    user_text: str | None = None,
) -> str:
    meta = get_meta(conn)
    effective_weapon_query = weapon_query or default_combat_weapon_query(meta)
    weapon = resolve_entity(conn, effective_weapon_query) if effective_weapon_query else None
    target = resolve_entity(conn, target_query) if target_query else None
    ammo = resolve_entity(conn, ammo_query) if ammo_query else None
    weapon_item = item_row(conn, weapon["id"]) if weapon else None
    ammo_item = item_row(conn, ammo["id"]) if ammo else None
    weapon_properties = parse_json(weapon_item["properties_json"], {}) if weapon_item else {}
    ammo_properties = parse_json(ammo_item["properties_json"], {}) if ammo_item else {}
    combat = weapon_properties.get("combat_profile") if isinstance(weapon_properties, dict) else {}
    ammo_profile = ammo_properties.get("ammo_profile") if isinstance(ammo_properties, dict) else {}
    compatible_ammo = combat.get("compatible_ammo", []) if isinstance(combat, dict) else []
    confirmations = required_confirmations(target, ammo, distance, combat, ammo_item)
    if ready_state:
        confirmations = [item for item in confirmations if not item.startswith("必须确认武器是否已上弦")]
    if not weapon:
        confirmations.append("武器未明确：需要指定武器或配置默认战斗武器。")
    warnings = preview_warnings(
        weapon,
        weapon_item,
        ammo,
        ammo_item,
        combat,
        ammo_profile,
        get_player_entity_id(conn),
        conn=conn,
    )
    suggested_ticks = suggested_clock_ticks(conn, ammo, ammo_profile)
    delta = build_combat_delta(
        conn,
        target=target,
        weapon=weapon,
        ammo=ammo,
        ammo_item=ammo_item,
        suggested_ticks=suggested_ticks,
        user_text=user_text,
        distance=distance,
        ready_state=ready_state,
    )
    add_generated_write_guards(conn, delta, prefix="preview-combat")

    lines = [
        "## 战斗行动预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text or '未提供'} |",
        f"| 目标 | {entity_label(target) if target else target_query or '未指定'} |",
        f"| 武器 | {entity_label(weapon) if weapon else effective_weapon_query or '未指定'} |",
        f"| 弹药 | {entity_label(ammo) if ammo else ammo_query or '未指定'} |",
        f"| 距离 | {distance or '未指定'} |",
        f"| 武器状态确认 | {ready_state or '未提供'} |",
        "",
        "### 当前局势",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 位置 | {current_location_label(conn, meta)} |",
        f"| 目标位置 | {entity_ref_label(conn, target['location_id']) if target and target['location_id'] else '未知/未登记'} |",
        f"| 目标摘要 | {redact_hidden_entity_refs(conn, target['summary']) if target else '未指定，无法判断'} |",
    ]

    lines.extend(["", "### 武器检查"])
    if weapon and weapon_item:
        lines.extend(
            [
                "| 项目 | 当前 |",
                "|------|------|",
                f"| ID | `{weapon['id']}` |",
                f"| 分类 | {weapon_item['category']} |",
                f"| 位置/所有者 | {entity_ref_label(conn, weapon['location_id'] or weapon['owner_id'])} |",
                f"| 数量 | {format_quantity(weapon_item)} |",
                f"| 装备槽 | {weapon_item['equipped_slot'] or '无'} |",
                f"| 待机状态 | {combat.get('ready_state', '未登记') if isinstance(combat, dict) else '未登记'} |",
                f"| 装填 | {format_value(combat.get('loading', {})) if isinstance(combat, dict) else '未登记'} |",
            ]
        )
    else:
        lines.append("- 未找到可用武器。")

    lines.extend(["", "### 弹药检查"])
    if ammo and ammo_item:
        after_quantity = decremented_quantity(ammo_item)
        lines.extend(
            [
                "| 项目 | 当前 |",
                "|------|------|",
                f"| ID | `{ammo['id']}` |",
                f"| 分类 | {ammo_item['category']} |",
                f"| 数量 | {format_quantity(ammo_item)} |",
                f"| 击发后 | {format_quantity_text(after_quantity, ammo_item['unit'])} |",
                f"| 效果类型 | {ammo_profile.get('effect_type', '未登记') if isinstance(ammo_profile, dict) else '未登记'} |",
                f"| 主要效果 | {ammo_profile.get('primary_effect', '未登记') if isinstance(ammo_profile, dict) else '未登记'} |",
                f"| 可靠性 | {ammo_profile.get('reliability', '未登记') if isinstance(ammo_profile, dict) else '未登记'} |",
            ]
        )
    elif compatible_ammo:
        lines.extend(["| 弹药 | 用途 | 备注 |", "|------|------|------|"])
        for item in compatible_ammo:
            if isinstance(item, dict):
                lines.append(
                    f"| `{item.get('id', '')}` {item.get('name', '')} | "
                    f"{item.get('role', '')} | {item.get('notes', '')} |"
                )
            else:
                lines.append(f"| {format_value(item)} |  |  |")
    else:
        lines.append("- 未指定弹药，也没有可读的兼容弹药表。")

    lines.extend(["", "### 必须确认"])
    if confirmations:
        lines.extend(f"- {item}" for item in confirmations)
    else:
        lines.append("- 无硬性缺口；仍需由 GM 根据场景描述确认目标动作。")

    lines.extend(["", "### 风险/进度钟"])
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- 未发现额外结构化警告。")
    if suggested_ticks:
        lines.extend(["", "建议进度钟："])
        for item in suggested_ticks:
            lines.append(f"- `{item['id']}` +{item['delta']}：{item['reason']}")

    lines.extend(
        [
            "",
            "### 推荐结算步骤",
            "1. 确认目标、距离、遮蔽、退路和友方位置。",
            "2. 确认武器是否已上弦、弹药是否已装填。",
            "3. 若击发，先记录弹药消耗，再结算命中和目标状态。",
            "4. 若产生爆炸、巨响、烟味、冰霜或血迹，记录可追踪痕迹和进度钟。",
            "5. 输出行动结果后，用 delta 保存正式变化。",
            "",
            "### Delta 草案",
            "保存前必须由 GM 按实际叙事改写摘要、目标状态和进度钟。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def render_rest_preview(
    conn: sqlite3.Connection,
    *,
    until: str | None = None,
    user_text: str | None = None,
) -> str:
    meta = get_meta(conn)
    rest_target = normalize_rest_until(until)
    current_day = parse_game_day(meta.get("current_game_day"))
    target_day = current_day + 1 if rest_target["overnight"] and current_day else current_day
    target_time = rest_target["time_block"]
    location = current_location_row(conn, meta)
    player_entity_id = get_player_entity_id(conn)
    pc = conn.execute("select * from entities where id = ?", (player_entity_id,)).fetchone()
    character = conn.execute("select * from characters where entity_id = ?", (player_entity_id,)).fetchone()
    pc_details = parse_json(pc["details_json"], {}) if pc else {}
    energy_label = primary_energy_label(meta)
    energy_full = primary_energy_full_value(meta)
    clocks = active_clock_rows(conn, include_hidden=False)
    crop_summary = summarize_crop_plots(conn)
    suggested_ticks = suggested_rest_clock_ticks(conn, meta, rest_target)
    delta = None
    if location:
        delta = build_rest_delta(
            conn,
            meta=meta,
            pc=pc,
            character=character,
            target_day=target_day,
            target_time=target_time,
            location=location,
            suggested_ticks=suggested_ticks,
            user_text=user_text,
        )
        add_generated_write_guards(conn, delta, prefix="preview-rest")

    lines = [
        "## 休息/过夜预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text or '未提供'} |",
        f"| 目标时间 | {until or 'morning'} -> 第{target_day or '?'}天 · {target_time} |",
        f"| 是否跨夜 | {'是' if rest_target['overnight'] else '否'} |",
        "",
        "### 睡前状态",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 位置 | {location_label(location) if location else current_location_label(conn, meta)} |",
        f"| 安全等级 | {location['safety_level'] if location and location['safety_level'] else '未登记'} |",
        f"| 健康 | {pc_details.get('health', character['health_state'] if character else '未登记')} |",
        f"| 体力 | {pc_details.get('stamina', '未登记')} |",
        f"| 饥饿 | {pc_details.get('hunger', '未登记')} |",
        f"| 口渴 | {pc_details.get('thirst', '未登记')} |",
        f"| {energy_label} | {primary_energy_value(pc_details, meta)} |",
    ]

    lines.extend(
        [
            "",
            "### 夜间安全检查",
            f"- 休息点：{redact_hidden_entity_refs(conn, location['description_short']) if location and location['description_short'] else '未登记详细描述'}",
            f"- 出入口/资源：{format_value(redact_hidden_entity_refs(conn, parse_json(location['exits_json'], []))) if location else '未登记'}；{format_value(redact_hidden_entity_refs(conn, parse_json(location['resources_json'], []))) if location else '未登记'}",
            f"- 预演不自动触发遭遇；若 GM 判定夜间有声响、入侵、梦境或{energy_label}异常，必须先改写 delta。",
            f"- 清晨{energy_label}恢复到满值后更容易成为感知源；外出前应再次判断遮蔽、武器位置和农田痕迹。",
        ]
    )

    lines.extend(
        [
            "",
            "### 恢复/消耗预测",
            "| 属性 | 睡前 | 睡后草案 | 依据 |",
            "|------|------|----------|------|",
            f"| 健康 | {pc_details.get('health', '未登记')} | {pc_details.get('health', '维持当前')} | 普通休息不自动治疗重大伤势 |",
            f"| 体力 | {pc_details.get('stamina', '未登记')} | █████████░  基本恢复 | 充足睡眠恢复行动能力 |",
            f"| 饥饿 | {pc_details.get('hunger', '未登记')} | ██████░░░░  清晨偏饿 | 夜间消耗，建议早饭 |",
            f"| 口渴 | {pc_details.get('thirst', '未登记')} | ███████░░░  清晨需补水 | 睡醒后补水检查 |",
            f"| {energy_label} | {primary_energy_value(pc_details, meta)} | {energy_full} | 一夜充足睡眠后恢复，不累积 |",
        ]
    )

    lines.extend(["", "### 农田/项目/进度钟预测"])
    lines.extend(
        [
            "| 类型 | 当前 | 过夜草案 |",
            "|------|------|----------|",
            f"| 农田 | {crop_summary['total']}畦；{crop_summary['needs_water_check']}畦需晨间查水；{crop_summary['partial_harvest']}畦可持续采收 | 不自动改生长阶段；清晨先巡田、查水、查虫害 |",
            f"| 天气 | {format_weather_brief(meta)} | 若继续晴天，干旱压力建议 +1；若夜雨则取消 |",
        ]
    )
    for clock in clocks:
        suggestion = rest_tick_reason(clock["entity_id"], suggested_ticks)
        lines.append(
            f"| `{clock['entity_id']}` {clock['name']} | {clock['segments_filled']}/{clock['segments_total']} {clock['visibility']} | {suggestion} |"
        )

    if crop_summary["sample_rows"]:
        lines.extend(["", "重点田地抽样："])
        for row in crop_summary["sample_rows"]:
            lines.append(
                f"- 畦{row['plot_no']} {row['crop_name']}：{row['harvest_status']} / 水分 {row['water_status']} / {row['notes']}"
            )

    lines.extend(["", "### 必须确认"])
    for item in rest_confirmations(rest_target, location, crop_summary, suggested_ticks, energy_label=energy_label):
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "### 推荐结算步骤",
            "1. 确认睡眠是否完整到清晨，是否被夜间事件打断。",
            f"2. 先结算主角健康、体力、饥饿、口渴、{energy_label}。",
            "3. 再结算天气、干旱/森林注意等进度钟。",
            "4. 最后输出清晨场景：全景、主角状态、近处对象、可行动选项。",
            "5. 如果玩家确认推进，用 delta 保存正式变化。",
            "",
            "### Delta 草案",
        ]
    )
    if delta is None:
        lines.append("当前地点不可见，不能生成保存草案。")
    else:
        lines.extend(
            [
                "保存前必须由 GM 按实际夜间事件、天气和清晨场景改写。",
                "",
                "```json",
                json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def render_craft_preview(
    conn: sqlite3.Connection,
    *,
    project_query: str | None = None,
    target: str | None = None,
    materials_text: str | None = None,
    time_cost: str | None = None,
    user_text: str | None = None,
) -> str:
    meta = get_meta(conn)
    location = current_location_row(conn, meta)
    pc = conn.execute("select * from entities where id = ?", (get_player_entity_id(conn),)).fetchone()
    pc_details = parse_json(pc["details_json"], {}) if pc else {}
    energy_label = primary_energy_label(meta)
    project = resolve_entity(conn, project_query) if project_query else None
    target_entity = resolve_entity(conn, target) if target else None
    recipe = resolve_recipe(conn, target) or resolve_recipe(conn, project_query)
    recipe_profile = parse_json(recipe["details_json"], {}).get("recipe_profile") if recipe else None
    material_terms = split_terms(materials_text) or recipe_material_terms(recipe_profile)
    materials = resolve_materials(conn, material_terms, meta)
    candidates = nearby_crafting_candidates(conn, meta)
    confirmations = craft_confirmations(
        project_query,
        project,
        target,
        target_entity,
        materials,
        time_cost,
        recipe,
        recipe_profile,
    )
    warnings = craft_warnings(
        project,
        target or (target_entity["name"] if target_entity else None),
        materials,
        pc_details,
        recipe_profile,
        energy_label=energy_label,
    )
    delta = None
    if location:
        delta = build_craft_delta(
            conn=conn,
            meta=meta,
            location=location,
            project=project,
            recipe=recipe,
            recipe_profile=recipe_profile,
            target=target,
            target_entity=target_entity,
            materials=materials,
            time_cost=time_cost,
            user_text=user_text,
        )
        add_generated_write_guards(conn, delta, prefix="preview-craft")

    lines = [
        "## 制作行动预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text or '未提供'} |",
        f"| 制作项目 | {entity_label(project) if project else project_query or '未指定'} |",
        f"| 配方 | {entity_label(recipe) if recipe else '未匹配'} |",
        f"| 目标成品 | {entity_label(target_entity) if target_entity else target or '未指定'} |",
        f"| 材料输入 | {materials_text or '未指定'} |",
        f"| 预计耗时 | {time_cost or recipe_time_cost(recipe_profile) or '未指定'} |",
        "",
        "### 当前状态",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 地点 | {location_label(location) if location else current_location_label(conn, meta)} |",
        f"| 体力 | {pc_details.get('stamina', '未登记')} |",
        f"| 饥渴 | 饥饿：{pc_details.get('hunger', '未登记')}；口渴：{pc_details.get('thirst', '未登记')} |",
        f"| {energy_label} | {primary_energy_value(pc_details, meta)} |",
    ]

    lines.extend(["", "### 项目/成品检查"])
    lines.extend(["| 字段 | 当前 |", "|------|------|"])
    if project:
        lines.append(f"| 项目摘要 | {project['summary']} |")
        details = parse_json(project["details_json"], {})
        lines.append(f"| 项目细节 | {format_value(details) if details else '未登记'} |")
    else:
        lines.append("| 项目摘要 | 未解析到项目实体；需要 GM 明确这是新项目还是已有项目推进。 |")
    if target_entity:
        if target_entity["type"] in {"item", "equipment"}:
            lines.append(f"| 既有成品实体 | `{target_entity['id']}` {target_entity['name']}：{target_entity['summary']} |")
        else:
            lines.append(
                f"| 关联实体 | `{target_entity['id']}` {target_entity['name']}（{target_entity['type']}）："
                "不是 item/equipment 成品，保存前仍需明确成品实体。 |"
            )
    else:
        lines.append("| 既有实体 | 未找到；若是新成品，保存前必须补实体 id、分类、数量、位置和摘要。 |")

    lines.extend(["", "### 配方检查"])
    if recipe and isinstance(recipe_profile, dict):
        lines.extend(["| 字段 | 值 |", "|------|----|"])
        lines.append(f"| 配方 ID | `{recipe['id']}` |")
        lines.append(f"| 耗时 | {recipe_time_cost(recipe_profile) or '未登记'} |")
        lines.append(f"| 输出 | {format_value(recipe_profile.get('output', {}))} |")
        lines.append(f"| 输入 | {format_value(recipe_profile.get('inputs', []))} |")
        lines.append(f"| 工具 | {format_value(recipe_profile.get('tools', []))} |")
    else:
        lines.append("- 未匹配结构化配方；预演只能检查玩家显式给出的材料。")

    lines.extend(["", "### 材料/工具检查"])
    if materials:
        lines.extend(["| 输入 | 解析实体 | 类别 | 数量 | 可用性 | 摘要 |", "|------|----------|------|------|--------|------|"])
        for item in materials:
            row = item.get("entity")
            item_row_value = item.get("item")
            lines.append(
                f"| {item['query']} | {entity_label(row) if row else '未找到'} | "
                f"{item_row_value['category'] if item_row_value else '未登记'} | "
                f"{format_quantity(item_row_value) if item_row_value else '未登记'} | "
                f"{item['availability']} | {row['summary'] if row else '需要确认'} |"
            )
    else:
        lines.append("- 未指定材料；以下是当前位置/基地附近的候选材料和工具。")
        lines.extend(["| 实体 | 类别 | 数量 | 位置 | 摘要 |", "|------|------|------|------|------|"])
        for row in candidates[:12]:
            lines.append(
                f"| `{row['id']}` {row['name']} | {row['category']} | {format_quantity(row)} | "
                f"{row['owner_id'] or row['location_id'] or '未知'} | {row['summary']} |"
            )

    lines.extend(["", "### 必须确认"])
    for item in confirmations:
        lines.append(f"- {item}")

    lines.extend(["", "### 风险/进度钟"])
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- 未发现额外结构化警告；仍需按实际工艺确认耗时和失败代价。")

    lines.extend(
        [
            "",
            "### 推荐结算步骤",
            "1. 确认成品规格、数量、品质和用途，不用含糊名称保存。",
            "2. 确认每种材料和工具的位置、数量、是否可替代。",
            "3. 先扣材料，再新增或更新成品、项目进度和主角状态。",
            f"4. 若使用{energy_label}、火药、毒物、发酵、陷阱或防御设施，检查对应风险和进度钟。",
            "5. 输出制作结果后，用 delta 保存正式变化。",
            "",
            "### Delta 草案",
        ]
    )
    if delta is None:
        lines.append("当前地点不可见，不能生成保存草案。")
    else:
        lines.extend(
            [
                "保存前必须由 GM 填入明确材料扣减、成品实体和项目进度；当前草案不自动扣材料。",
                "",
                "```json",
                json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def render_travel_preview(
    conn: sqlite3.Connection,
    *,
    destination_query: str | None = None,
    pace: str | None = None,
    user_text: str | None = None,
) -> str:
    meta = get_meta(conn)
    current = location_detail_row(conn, meta.get("current_location_id"))
    destination_entity = resolve_location(conn, destination_query) if destination_query else None
    destination = location_detail_row(conn, destination_entity["id"]) if destination_entity else None
    player_entity_id = get_player_entity_id(conn)
    pc = conn.execute("select * from entities where id = ?", (player_entity_id,)).fetchone()
    character = conn.execute("select * from characters where entity_id = ?", (player_entity_id,)).fetchone()
    pc_details = parse_json(pc["details_json"], {}) if pc else {}
    route = find_route(conn, current, destination)
    travel_minutes = route["travel_minutes"] if route else estimate_travel_minutes(current, destination)
    threats = destination_threats(conn, destination["id"] if destination else None)
    occupants = destination_occupants(conn, destination["id"] if destination else None)
    suggested_ticks = suggested_travel_clock_ticks(conn, destination)
    confirmations = travel_confirmations(destination_query, destination_entity, destination, current, travel_minutes, pc_details)
    can_generate_delta = bool(destination_entity and destination and current and travel_minutes is not None)
    delta = None
    if can_generate_delta:
        delta = build_travel_delta(
            conn,
            meta=meta,
            pc=pc,
            character=character,
            current=current,
            destination=destination,
            travel_minutes=travel_minutes,
            pace=pace,
            threats=threats,
            route=route,
            suggested_ticks=suggested_ticks,
            user_text=user_text,
        )
        add_generated_write_guards(conn, delta, prefix="preview-travel")

    lines = [
        "## 旅行行动预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text or '未提供'} |",
        f"| 出发地 | {location_label(current) if current else current_location_label(conn, meta)} |",
        f"| 目的地 | {location_label(destination) if destination else destination_query or '未指定'} |",
        f"| 步速 | {pace or 'normal'} |",
        "",
        "### 路线估算",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 预计耗时 | {format_minutes(travel_minutes)} |",
        f"| 路线 | {route['id'] if route else '未登记，使用粗估'} |",
        f"| 难度 | {route['difficulty'] if route else '未知'} |",
        f"| 当前体力 | {pc_details.get('stamina', '未登记')} |",
        f"| 当前位置安全 | {current['safety_level'] if current and current['safety_level'] else '未登记'} |",
        f"| 目的地安全 | {destination['safety_level'] if destination and destination['safety_level'] else '未登记'} |",
    ]

    lines.extend(["", "### 目的地资料"])
    if destination:
        lines.extend(
            [
                "| 字段 | 值 |",
                "|------|----|",
                f"| ID | `{destination['id']}` |",
                f"| 摘要 | {redact_hidden_entity_refs(conn, destination['summary'])} |",
                f"| 描述 | {redact_hidden_entity_refs(conn, destination['description_short']) if destination['description_short'] else '未登记'} |",
                f"| 出口 | {format_value(redact_hidden_entity_refs(conn, parse_json(destination['exits_json'], [])))} |",
                f"| 资源 | {format_value(redact_hidden_entity_refs(conn, parse_json(destination['resources_json'], [])))} |",
            ]
        )
    else:
        lines.append("- 未找到目的地实体。")

    lines.extend(["", "### 路线细节"])
    if route:
        lines.extend(
            [
                "| 项目 | 值 |",
                "|------|----|",
                f"| 路线 ID | `{route['id']}` |",
                f"| 起点 | `{route['from_location_id']}` |",
                f"| 终点 | `{route['to_location_id']}` |",
                f"| 耗时 | {format_minutes(route['travel_minutes'])} |",
                f"| 难度 | {route['difficulty']} |",
                f"| 危险 | {format_value(parse_json(route['hazards_json'], []))} |",
                f"| 需求 | {format_value(parse_json(route['requirements_json'], []))} |",
            ]
        )
        segments = route.get("segments", [])
        if segments:
            lines.extend(["", "| 路段 | 起点 | 终点 | 耗时 | 难度 |", "|------|------|------|------|------|"])
            for segment in segments:
                lines.append(
                    f"| `{segment['id']}` | `{segment['from_location_id']}` | `{segment['to_location_id']}` | "
                    f"{format_minutes(segment['travel_minutes'])} | {segment['difficulty']} |"
                )
    else:
        lines.append("- 未找到结构化路线；保存前需要 GM 手动确认路线、耗时、危险和需求。")

    lines.extend(["", "### 现场对象/威胁"])
    if occupants or threats:
        lines.extend(["| 类型 | 实体 | 摘要 |", "|------|------|------|"])
        for row in occupants[:6]:
            lines.append(f"| {row['type']} | `{row['id']}` {row['name']} | {row['summary']} |")
        for row in threats[:6]:
            lines.append(f"| threat | `{row['id']}` {row['name']} | {row['summary']} |")
    else:
        lines.append("- 目的地当前未登记 active NPC/威胁；不代表绝对安全。")

    lines.extend(["", "### 必须确认"])
    for item in confirmations:
        lines.append(f"- {item}")

    lines.extend(["", "### 风险/进度钟"])
    risks = travel_risks(destination, threats, pc_details, pace)
    if risks:
        lines.extend(f"- {item}" for item in risks)
    else:
        lines.append("- 未发现额外结构化警告；仍需按实际天气、光线和装备确认。")
    if suggested_ticks:
        lines.extend(["", "建议进度钟："])
        for item in suggested_ticks:
            lines.append(f"- `{item['id']}` +{item['delta']}：{item['reason']}")

    lines.extend(
        [
            "",
            "### 推荐结算步骤",
            "1. 确认是否立刻出发、是否带南瓜/背包/武器、是否绕路潜行。",
            "2. 结算耗时、体力、饥渴、天气光线和途中迹象。",
            "3. 到达后使用场景入场模板，先给全景，再给近处对象和风险。",
            "4. 若目的地有聚落、异常点、威胁或隐藏观察者，检查相关进度钟。",
            "5. 玩家确认行动后，用 delta 保存位置变化。",
            "",
            "### Delta 草案",
        ]
    )
    if delta is None:
        lines.append("目的地、当前位置或耗时未解析完整，不能生成保存草案。")
    else:
        lines.extend(
            [
                "保存前必须由 GM 按实际路线、遭遇、耗时和体力改写。",
                "",
                "```json",
                json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def render_gather_preview(
    conn: sqlite3.Connection,
    *,
    campaign: Campaign | None = None,
    target_query: str | None = None,
    location_query: str | None = None,
    user_text: str | None = None,
) -> str:
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    location = resolve_location(conn, location_query) if location_query else current
    if location and "description_short" not in location.keys():
        location = location_detail_row(conn, location["id"])
    target = resolve_entity(conn, target_query) if target_query else None
    crop = crop_plot_for_entity(conn, target["id"]) if target else None
    local_items = gatherable_items(conn, location["id"] if location else None)
    crop_candidates = harvestable_crop_rows(conn, parse_game_day(meta.get("current_game_day"))) if is_home_location(location, meta) else []
    palette_candidates: list[dict[str, Any]] = []
    if campaign and location:
        for palette_kind, palette_limit in [("material", 6), ("species", 4), ("encounter", 4)]:
            _, rows = suggest_palette_entries(
                campaign,
                conn,
                kind=palette_kind,
                location_query=location["id"],
                intent="gather",
                limit=palette_limit,
            )
            palette_candidates.extend(rows)
    confirmations = gather_confirmations(conn, target_query, target, location, current, crop, meta)
    delta = None
    if current and location:
        delta = build_gather_delta(
            meta=meta,
            current_location_id=current["id"],
            target=target,
            location=location,
            crop=crop,
            user_text=user_text,
        )
        add_generated_write_guards(conn, delta, prefix="preview-gather")

    lines = [
        "## 采集/收获预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text or '未提供'} |",
        f"| 地点 | {location_label(location) if location else location_query or '当前地点未解析'} |",
        f"| 目标 | {entity_label(target) if target else target_query or '未指定'} |",
        "",
        "### 当前状态",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 地点安全 | {location['safety_level'] if location and location['safety_level'] else '未登记'} |",
        f"| 地点资源 | {format_value(redact_hidden_entity_refs(conn, parse_json(location['resources_json'], []))) if location else '未登记'} |",
    ]

    lines.extend(["", "### 目标检查"])
    if target:
        lines.extend(["| 字段 | 值 |", "|------|----|"])
        lines.append(f"| ID | `{target['id']}` |")
        lines.append(f"| 类型 | {target['type']} |")
        lines.append(f"| 摘要 | {redact_hidden_entity_refs(conn, target['summary'])} |")
        lines.append(f"| 位置 | {entity_ref_label(conn, target['location_id'] or target['owner_id'])} |")
        if crop:
            lines.append(f"| 畦号 | {crop['plot_no']} |")
            lines.append(f"| 作物 | {crop['crop_entity_id']} |")
            lines.append(f"| 收获状态 | {crop['harvest_status']} |")
            lines.append(f"| 水分/土壤 | {crop['water_status']} / {crop['soil_status']} |")
            lines.append(f"| 预计产出 | {crop['expected_yield'] or '未登记'} |")
    else:
        lines.append("- 未指定目标；以下列出当前可考虑的采集/收获对象。")

    lines.extend(["", "### 候选对象"])
    if crop_candidates or local_items:
        lines.extend(["| 类型 | 对象 | 状态/数量 | 摘要 |", "|------|------|-----------|------|"])
        for row in crop_candidates[:10]:
            lines.append(
                f"| crop | `plot:field-{int(row['plot_no']):03d}` 畦{row['plot_no']} {row['crop_name']} | "
                f"{row['harvest_status']} / 水分 {row['water_status']} | {row['notes']} |"
            )
        for row in local_items[:10]:
            lines.append(
                f"| item | `{row['id']}` {row['name']} | {format_quantity(row)} | {row['summary']} |"
            )
    else:
        lines.append("- 当前没有结构化候选对象；GM 需要根据地点资源手动判断。")

    lines.extend(["", "### 素材库候选"])
    lines.extend(
        render_compact_palette_table(
            palette_candidates[:10],
            empty_text="没有符合当前地点和采集意图的素材库候选。",
            conn=conn,
        )
    )

    lines.extend(["", "### 必须确认"])
    for item in confirmations:
        lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "### 推荐结算步骤",
            "1. 确认采集目标、工具、耗时和是否会离开当前位置。",
            "2. 对作物先确认可采部位、留根/留种、再生周期和水分状态。",
            "3. 对鱼笼/野外资源先确认是否有危险迹象和实际产出。",
            "4. 保存时明确新增物品、数量、单位、位置，以及目标资源是否被消耗或进入冷却。",
            "5. 若采集制造明显痕迹、靠近聚落或处理魔力植物，检查进度钟。",
            "",
            "### Delta 草案",
            "保存前必须由 GM 填入实际产出和资源状态变化；当前草案不自动新增库存。",
            "",
        ]
    )
    if delta is None:
        lines.append("当前地点或目标地点不可见，不能生成保存草案。")
    else:
        lines.extend(["```json", json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def render_social_preview(
    conn: sqlite3.Connection,
    *,
    npc_query: str | None = None,
    topic: str | None = None,
    approach: str | None = None,
    user_text: str | None = None,
) -> str:
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    npc = resolve_entity(conn, npc_query) if npc_query else None
    character = conn.execute("select * from characters where entity_id = ?", (npc["id"],)).fetchone() if npc else None
    relevant_clocks = social_relevant_clocks(conn, npc, topic, approach)
    suggested_ticks = suggested_social_clock_ticks(conn, npc, topic, approach)
    confirmations = social_confirmations(conn, npc_query, npc, character, topic, approach, meta)
    delta = None
    if current:
        delta = build_social_delta(
            meta=meta,
            current_location_id=current["id"],
            npc=npc,
            character=character,
            topic=topic,
            approach=approach,
            suggested_ticks=suggested_ticks,
            user_text=user_text,
        )
        add_generated_write_guards(conn, delta, prefix="preview-social")

    lines = [
        "## 社交/交易预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 原始行动 | {user_text or '未提供'} |",
        f"| 对象 | {entity_label(npc) if npc else npc_query or '未指定'} |",
        f"| 主题 | {topic or '未指定'} |",
        f"| 方式 | {approach or '未指定'} |",
        "",
        "### 对象状态",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 玩家位置 | {current_location_label(conn, meta)} |",
        f"| 对象位置 | {location_id_label(conn, npc['location_id']) if npc and npc['location_id'] else '未登记'} |",
        f"| 对象摘要 | {npc['summary'] if npc else '未找到'} |",
        f"| 信任 | {character['trust'] if character else '未登记'} |",
        f"| 态度 | {character['attitude'] if character else '未登记'} |",
    ]

    lines.extend(["", "### 相关进度钟"])
    if relevant_clocks:
        lines.extend(["| 进度钟 | 当前 | 满格后果 |", "|--------|------|----------|"])
        for row in relevant_clocks:
            lines.append(
                f"| `{row['entity_id']}` {row['name']} | {row['segments_filled']}/{row['segments_total']} {row['visibility']} | {row['trigger_when_full']} |"
            )
    else:
        lines.append("- 未找到直接相关进度钟；仍需按承诺、礼物和威胁姿态判断。")

    lines.extend(["", "### 必须确认"])
    for item in confirmations:
        lines.append(f"- {item}")

    lines.extend(["", "### 风险/进度钟"])
    for item in social_risks(npc, topic, approach):
        lines.append(f"- {item}")
    if suggested_ticks:
        lines.extend(["", "建议进度钟："])
        for item in suggested_ticks:
            lines.append(f"- `{item['id']}` +{item['delta']}：{item['reason']}")

    lines.extend(
        [
            "",
            "### 推荐结算步骤",
            "1. 确认是否在同一地点、是否需要先 travel、是否放下武器或带交换物。",
            "2. 明确玩家表达、礼物、承诺和对方可见反应。",
            "3. 记录关系变化、承诺、获得情报、交换物和后续约定。",
            "4. 若接近警惕聚落、违背承诺或展示高风险武器，检查进度钟。",
            "5. 保存时用结构化 delta 更新 NPC、项目、物品和进度钟。",
            "",
            "### Delta 草案",
            "保存前必须由 GM 填入实际对话结果、交易物品和关系变化。",
            "",
        ]
    )
    if delta is None:
        lines.append("当前地点不可见，不能生成保存草案。")
    else:
        lines.extend(["```json", json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def item_row(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from items where entity_id = ?", (entity_id,)).fetchone()


def entity_label(entity: sqlite3.Row | None) -> str:
    if not entity:
        return "未找到"
    return f"`{entity['id']}` {entity['name']}（{entity['type']}）"


def entity_ref_label(conn: sqlite3.Connection, entity_id: Any) -> str:
    if not entity_id:
        return "未登记"
    record = read_entity(conn, str(entity_id))
    if not record:
        return "[hidden]"
    return f"`{record.id}` {record.name}"


def required_confirmations(
    target: sqlite3.Row | None,
    ammo: sqlite3.Row | None,
    distance: str | None,
    combat: Any,
    ammo_item: sqlite3.Row | None,
) -> list[str]:
    items: list[str] = []
    if not target:
        items.append("目标未明确：需要目标实体或清楚的场景目标。")
    if not distance:
        items.append("距离未明确：需要至少给出贴身/近距/标准/远距或步数。")
    if isinstance(combat, dict) and combat.get("ready_state"):
        items.append("必须确认武器是否已上弦、是否已装箭。")
    if not ammo:
        items.append("弹药未明确：射击前必须选择弹药。")
    if ammo_item and (ammo_item["quantity"] is None or float(ammo_item["quantity"]) <= 0):
        items.append("弹药不足：当前弹药数量不可用于击发。")
    return items


def preview_warnings(
    weapon: sqlite3.Row | None,
    weapon_item: sqlite3.Row | None,
    ammo: sqlite3.Row | None,
    ammo_item: sqlite3.Row | None,
    combat: Any,
    ammo_profile: Any,
    player_entity_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    warnings: list[str] = []
    if weapon and weapon["owner_id"] not in {player_entity_id, None}:
        owner = entity_ref_label(conn, weapon["owner_id"]) if conn else weapon["owner_id"]
        warnings.append(f"武器所有者不是主角：{owner}")
    if weapon_item and weapon_item["category"] != "weapon":
        warnings.append(f"所选武器分类不是 weapon：{weapon_item['category']}")
    if ammo_item and ammo_item["category"] != "ammunition":
        warnings.append(f"所选弹药分类不是 ammunition：{ammo_item['category']}")
    if ammo and ammo["owner_id"] not in {player_entity_id, None}:
        owner = entity_ref_label(conn, ammo["owner_id"]) if conn else ammo["owner_id"]
        warnings.append(f"弹药所有者不是主角：{owner}")
    if isinstance(combat, dict) and combat.get("risks"):
        for item in combat["risks"][:2]:
            warnings.append(str(redact_hidden_entity_refs(conn, item) if conn else item))
    if isinstance(ammo_profile, dict):
        for item in ammo_profile.get("risks", [])[:3]:
            warnings.append(str(redact_hidden_entity_refs(conn, item) if conn else item))
        compatible_weapon = ammo_profile.get("compatible_weapon_id")
        if weapon and compatible_weapon and compatible_weapon != weapon["id"]:
            label = entity_ref_label(conn, compatible_weapon) if conn else compatible_weapon
            warnings.append(f"弹药兼容武器为 {label}，不是 {weapon['id']}。")
    return warnings


def suggested_clock_ticks(
    conn: sqlite3.Connection,
    ammo: sqlite3.Row | None,
    ammo_profile: Any,
) -> list[dict[str, Any]]:
    if not ammo or not isinstance(ammo_profile, dict):
        return []
    effect_type = str(ammo_profile.get("effect_type", ""))
    risk_text = " ".join(str(item) for item in ammo_profile.get("risks", []))
    noisy = effect_type in {"explosive", "impact_burst"} or any(
        word in risk_text for word in ["噪音", "爆炸", "暴露", "烟味"]
    )
    if not noisy:
        return []
    clock = first_matching_clock(conn, ["爆炸", "火药", "噪音", "暴露", "声响", "attention", "noise"])
    if not clock:
        return []
    return [{"id": clock["entity_id"], "delta": 1, "reason": "爆炸/巨大声响/暴露痕迹"}]


def build_combat_delta(
    conn: sqlite3.Connection,
    *,
    target: sqlite3.Row | None,
    weapon: sqlite3.Row | None,
    ammo: sqlite3.Row | None,
    ammo_item: sqlite3.Row | None,
    suggested_ticks: list[dict[str, Any]],
    user_text: str | None,
    distance: str | None,
    ready_state: str | None = None,
) -> dict[str, Any]:
    upserts = []
    if ammo and ammo_item and ammo_item["quantity"] is not None and float(ammo_item["quantity"]) > 0:
        upserts.append(item_delta_entity(conn, ammo, ammo_item, decremented_quantity(ammo_item)))
    return {
        "user_text": user_text or "战斗行动预演生成的草案",
        "intent": "combat",
        "changed": True,
        "summary": draft_summary(target, weapon, ammo, distance),
        "events": [
            {
                "type": "combat",
                "title": "战斗行动结算",
                "summary": draft_summary(target, weapon, ammo, distance),
                "payload": {
                    "target_id": target["id"] if target else None,
                    "weapon_id": weapon["id"] if weapon else None,
                    "ammo_id": ammo["id"] if ammo else None,
                    "distance": distance,
                    "ready_state": ready_state,
                    "needs_gm_resolution": True,
                },
                "source": "combat_preview",
            }
        ],
        "upsert_entities": upserts,
        "tick_clocks": [{"id": item["id"], "delta": item["delta"]} for item in suggested_ticks],
    }


def normalize_rest_until(until: str | None) -> dict[str, Any]:
    raw = (until or "morning").strip()
    lowered = raw.lower()
    overnight_values = {"morning", "dawn", "sunrise", "清晨", "天亮", "明早", "早上"}
    if lowered in overnight_values or raw in overnight_values:
        return {"raw": raw, "time_block": "清晨", "overnight": True}
    if "明" in raw or "天亮" in raw:
        return {"raw": raw, "time_block": raw, "overnight": True}
    return {"raw": raw, "time_block": raw, "overnight": False}


def parse_game_day(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def current_location_row(conn: sqlite3.Connection, meta: dict[str, str]) -> sqlite3.Row | None:
    location_id = meta.get("current_location_id")
    if not location_id:
        return None
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    subtype_visibility_clause = entity_subtype_visibility_sql("player", "e", "c")
    return conn.execute(
        f"""
        select e.id, e.name, e.type, e.status, e.visibility, e.location_id, e.owner_id,
               e.summary, e.details_json,
               l.parent_id, l.biome, l.safety_level, l.description_short,
               l.exits_json, l.resources_json
        from entities e
        left join locations l on l.entity_id = e.id
        where e.id = ?
          and e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        """,
        (location_id,),
    ).fetchone()


def location_label(location: sqlite3.Row | None) -> str:
    if not location:
        return "未找到"
    return f"`{location['id']}` {location['name']}"


def current_location_label(conn: sqlite3.Connection, meta: dict[str, str]) -> str:
    location = current_location_row(conn, meta)
    return location_label(location) if location else "当前地点不可见"


def location_id_label(conn: sqlite3.Connection, location_id: str | None) -> str:
    if not location_id:
        return "未登记"
    location = location_detail_row(conn, location_id)
    return location_label(location) if location else "未知地点"


def active_clock_rows(conn: sqlite3.Connection, *, include_hidden: bool) -> list[sqlite3.Row]:
    ensure_visibility_sql_functions(conn)
    clock_visibility_clause = "" if include_hidden else clock_visibility_sql("player", "c")
    entity_visibility_clause = "" if include_hidden else entity_visibility_sql("player", "e")
    subtype_visibility_clause = "" if include_hidden else entity_subtype_visibility_sql("player", "e", "c")
    return conn.execute(
        f"""
        select c.entity_id, e.name, e.summary, c.clock_type, c.segments_filled,
               c.segments_total, c.visibility, c.trigger_when_full, c.tick_rules_json,
               c.last_ticked_turn_id
        from clocks c
        join entities e on e.id = c.entity_id
        where {normalized_text_sql("e.status")} = 'active'
          {entity_visibility_clause}
          {clock_visibility_clause}
          {subtype_visibility_clause}
        order by
          case c.visibility when 'visible' then 0 when 'hinted' then 1 else 2 end,
          c.entity_id
        """
    ).fetchall()


def summarize_crop_plots(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_visibility_sql_functions(conn)
    plot_visibility_clause = entity_visibility_sql("player", "e")
    crop_visibility_clause = entity_visibility_sql("player", "ce")
    plot_subtype_clause = entity_subtype_visibility_sql("player", "e", "plot_clock")
    crop_subtype_clause = entity_subtype_visibility_sql("player", "ce", "crop_clock")
    rows = conn.execute(
        f"""
        select p.entity_id, e.name, p.plot_no, p.crop_entity_id, ce.name as crop_name,
               p.planted_day, p.growth_stage, p.growth_stage_max, p.harvest_day_min,
               p.harvest_day_max, p.harvest_status, p.water_status, p.soil_status,
               p.expected_yield, p.notes
        from crop_plots p
        join entities e on e.id = p.entity_id
        join entities ce on ce.id = p.crop_entity_id
        left join clocks plot_clock on plot_clock.entity_id = e.id
        left join clocks crop_clock on crop_clock.entity_id = ce.id
        where {entity_not_archived_sql("e")}
          and {entity_not_archived_sql("ce")}
          {plot_visibility_clause}
          {crop_visibility_clause}
          {plot_subtype_clause}
          {crop_subtype_clause}
        order by p.plot_no
        """
    ).fetchall()
    needs_water_check = [
        row for row in rows if str(row["water_status"] or "").lower() in {"needs_check", "dry", "low"}
    ]
    partial_harvest = [row for row in rows if row["harvest_status"] == "partial_harvest"]
    high_priority = partial_harvest[:4] + [
        row for row in needs_water_check if row["entity_id"] not in {item["entity_id"] for item in partial_harvest[:4]}
    ][:4]
    return {
        "total": len(rows),
        "needs_water_check": len(needs_water_check),
        "partial_harvest": len(partial_harvest),
        "sample_rows": high_priority[:8],
    }


def suggested_rest_clock_ticks(
    conn: sqlite3.Connection,
    meta: dict[str, str],
    rest_target: dict[str, Any],
) -> list[dict[str, Any]]:
    if not rest_target.get("overnight"):
        return []
    ticks: list[dict[str, Any]] = []
    weather = meta.get("weather_label", "")
    condition = meta.get("weather_condition", "")
    precipitation = meta.get("weather_precipitation", "")
    drought = first_matching_clock(conn, ["干旱", "晴天", "浇水", "drought", "dry"])
    dry_weather = (
        condition == "clear"
        or precipitation == "none"
        or "晴" in weather
        or "clear" in weather.lower()
        or not weather
    )
    wet_weather = precipitation in {"light", "moderate", "heavy", "present"} or "雨" in weather
    if drought and dry_weather and not wet_weather:
        ticks.append({"id": drought["entity_id"], "delta": 1, "reason": "跨夜到新一天且天气为晴/未记录降雨"})
    return ticks


def rest_tick_reason(clock_id: str, suggested_ticks: list[dict[str, Any]]) -> str:
    for item in suggested_ticks:
        if item["id"] == clock_id:
            return f"+{item['delta']}（{item['reason']}）"
    return "无自动变化；按夜间事件修正"


def rest_confirmations(
    rest_target: dict[str, Any],
    location: sqlite3.Row | None,
    crop_summary: dict[str, Any],
    suggested_ticks: list[dict[str, Any]],
    *,
    energy_label: str = "能量",
) -> list[str]:
    items = []
    if not rest_target.get("overnight"):
        items.append("目标时间不是默认跨夜清晨：GM 需要确认是否推进日期。")
    items.append("是否完整睡到目标时间，还是被梦境、声响、敌意接近或同伴动作打断。")
    if not location:
        items.append("当前地点未解析：不能可靠判断夜间安全。")
    elif location["safety_level"] not in {"defended", "safe"}:
        items.append(f"当前地点安全等级为 {location['safety_level']}：需要夜间风险判定。")
    if crop_summary["needs_water_check"]:
        items.append(f"清晨必须检查农田水分：当前 {crop_summary['needs_water_check']} 畦标记为 needs_check。")
    if suggested_ticks:
        items.append("干旱进度钟为建议推进；若夜间下雨或露水充足，需要取消或改写。")
    items.append(f"{energy_label}恢复到 100% 后不累积；当天使用前必须从满值重新扣减。")
    return items


def build_rest_delta(
    conn: sqlite3.Connection,
    *,
    meta: dict[str, str],
    pc: sqlite3.Row | None,
    character: sqlite3.Row | None,
    target_day: int | None,
    target_time: str,
    location: sqlite3.Row | None,
    suggested_ticks: list[dict[str, Any]],
    user_text: str | None,
) -> dict[str, Any]:
    location_id = meta.get("current_location_id")
    energy_label = primary_energy_label(meta)
    summary = rest_summary(target_day, target_time, location, energy_label=energy_label)
    delta: dict[str, Any] = {
        "user_text": user_text or "睡到天亮（休息预演生成的草案）",
        "intent": "rest",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": f"第{target_day or '?'}天 · {target_time}",
        "location_before": location_id,
        "location_after": location_id,
        "summary": summary,
        "events": [
            {
                "type": "rest",
                "title": "过夜休息结算",
                "summary": summary,
                "payload": {
                    "before": {
                        "day": meta.get("current_game_day"),
                        "time_block": meta.get("current_time_block"),
                        "location_id": location_id,
                    },
                    "after": {
                        "day": str(target_day) if target_day else None,
                        "time_block": target_time,
                        "location_id": location_id,
                    },
                    "safety_level": location["safety_level"] if location else None,
                    "needs_gm_resolution": True,
                    "crop_checks_required": True,
                    "clock_ticks_are_suggestions": True,
                },
                "source": "rest_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [{"id": item["id"], "delta": item["delta"]} for item in suggested_ticks],
        "meta": enrich_time_weather_meta({
            "current_game_day": str(target_day) if target_day else str(meta.get("current_game_day", "")),
            "current_time_block": morning_time_block(target_day, target_time, energy_label=energy_label),
            "current_location_id": location_id,
        }),
    }
    if pc:
        delta["upsert_entities"].append(pc_rest_delta_entity(conn, pc, character, target_day, target_time, location, meta))
    return delta


def rest_summary(target_day: int | None, target_time: str, location: sqlite3.Row | None, *, energy_label: str = "能量") -> str:
    place = location["name"] if location else "当前地点"
    return f"在{place}休息至第{target_day or '?'}天{target_time}；体力基本恢复，{energy_label}恢复到 100%，清晨需要检查水分、早饭和周边动静。"


def morning_time_block(target_day: int | None, target_time: str, *, energy_label: str = "能量") -> str:
    if target_time == "清晨":
        return f"清晨（第{target_day or '?'}天/睡醒/{energy_label}恢复/需检查田地）"
    return target_time


def pc_rest_delta_entity(
    conn: sqlite3.Connection,
    pc: sqlite3.Row,
    character: sqlite3.Row | None,
    target_day: int | None,
    target_time: str,
    location: sqlite3.Row | None,
    meta: dict[str, str],
) -> dict[str, Any]:
    details = parse_json(pc["details_json"], {})
    health = details.get("health") or (character["health_state"] if character else "██████████  良好")
    energy_label = primary_energy_label(meta)
    energy_key = primary_energy_detail_key(meta)
    energy_full = primary_energy_full_value(meta)
    place = location["name"] if location else "当前地点"
    location_text = f"{place}（第{target_day or '?'}天{target_time}/睡醒）"
    details.update(
        {
            "health": health,
            "stamina": "█████████░  基本恢复（睡眠后行动能力恢复，仍需早饭补足）",
            "hunger": "██████░░░░  清晨偏饿（建议先吃早饭）",
            "thirst": "███████░░░  清晨需补水（睡醒后检查竹水筒）",
            energy_key: f"{energy_full}（一夜充足睡眠后恢复，不累积）",
            "location_text": location_text,
            "sleep": f"第{(target_day - 1) if target_day else '?'}夜在{place}休息到第{target_day or '?'}天{target_time}；夜间异常需由 GM 另行结算。",
        }
    )
    entity: dict[str, Any] = {
        "id": pc["id"],
        "type": pc["type"],
        "name": pc["name"],
        "status": pc["status"],
        "visibility": pc["visibility"],
        "location_id": pc["location_id"],
        "owner_id": pc["owner_id"],
        "summary": (
            f"健康{health}；体力█████████░  基本恢复；饥饿██████░░░░  清晨偏饿；"
            f"口渴███████░░░  清晨需补水；{energy_label}{energy_full}；位置{location_text}"
        ),
        "details": details,
        "aliases": entity_aliases(conn, pc["id"]),
    }
    if character:
        entity["character"] = {
            "species_id": character["species_id"],
            "role": character["role"],
            "attitude": character["attitude"],
            "trust": character["trust"],
            "health_state": health,
            "stress": parse_json(character["stress_json"], {}),
            "consequences": parse_json(character["consequences_json"], []),
            "goals": parse_json(character["goals_json"], []),
            "knowledge": parse_json(character["knowledge_json"], {}),
        }
    return entity


def split_terms(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,，、;；\n]+", text) if part.strip()]


def resolve_recipe(conn: sqlite3.Connection, text: str | None) -> sqlite3.Row | None:
    if not text:
        return None
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    exact_id = conn.execute(
        f"""
        select *
        from entities e
        where e.id = ?
          and e.type = 'recipe'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        """,
        (text,),
    ).fetchone()
    if exact_id:
        return exact_id
    exact_name = conn.execute(
        f"""
        select *
        from entities e
        where type = 'recipe'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          and name = ?
        limit 1
        """,
        (text,),
    ).fetchone()
    if exact_name:
        return exact_name
    alias = conn.execute(
        f"""
        select e.*
        from aliases a
        join entities e on e.id = a.entity_id
        where e.type = 'recipe'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          and a.alias = ?
        limit 1
        """,
        (text,),
    ).fetchone()
    if alias:
        return alias
    like = f"%{text}%"
    fuzzy = conn.execute(
        f"""
        select *
        from entities e
        where type = 'recipe'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          and (name like ? or summary like ? or details_json like ?)
        order by name
        limit 1
        """,
        (like, like, like),
    ).fetchone()
    return fuzzy


def recipe_material_terms(recipe_profile: Any) -> list[str]:
    if not isinstance(recipe_profile, dict):
        return []
    terms: list[str] = []
    for key in ("inputs", "tools"):
        values = recipe_profile.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict):
                terms.append(str(item.get("id") or item.get("name") or ""))
            else:
                terms.append(str(item))
    return [item for item in terms if item]


def recipe_time_cost(recipe_profile: Any) -> str | None:
    if isinstance(recipe_profile, dict):
        value = recipe_profile.get("time_cost")
        if value:
            return str(value)
    return None


def recipe_tick_clocks(recipe_profile: Any) -> list[dict[str, Any]]:
    if not isinstance(recipe_profile, dict):
        return []
    ticks = []
    for item in recipe_profile.get("suggested_clock_ticks", []):
        if isinstance(item, dict) and item.get("id"):
            ticks.append({"id": str(item["id"]), "delta": int(item.get("delta", 0))})
    return ticks


def resolve_materials(
    conn: sqlite3.Connection,
    queries: list[str],
    meta: dict[str, str],
) -> list[dict[str, Any]]:
    materials = []
    for query in queries:
        entity = resolve_entity(conn, query)
        item = item_row(conn, entity["id"]) if entity else None
        materials.append(
            {
                "query": query,
                "entity": entity,
                "item": item,
                "availability": material_availability(conn, entity, meta, get_player_entity_id(conn)),
            }
        )
    return materials


def material_availability(conn: sqlite3.Connection, entity: sqlite3.Row | None, meta: dict[str, str], player_entity_id: str) -> str:
    if not entity:
        return "未找到"
    current = current_location_row(conn, meta)
    current_location = current["id"] if current else None
    home_locations = visible_home_location_ids(conn, meta)
    if entity["owner_id"] == player_entity_id:
        return "随身"
    if entity["location_id"] == current_location:
        return "当前地点"
    if current_location and current_location in home_locations and entity["location_id"] in home_locations:
        return "基地邻近"
    if entity["location_id"]:
        return f"不在手边：{entity_ref_label(conn, entity['location_id'])}"
    return "位置未登记"


def nearby_crafting_candidates(conn: sqlite3.Connection, meta: dict[str, str]) -> list[sqlite3.Row]:
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    subtype_visibility_clause = entity_subtype_visibility_sql("player", "e", "c")
    current = current_location_row(conn, meta)
    current_location = current["id"] if current else None
    home_locations = visible_home_location_ids(conn, meta)
    allowed_locations = {current_location} if current_location else set()
    if current_location and current_location in home_locations:
        allowed_locations.update(home_locations)
    location_placeholders = ",".join("?" for _ in allowed_locations)
    location_filter = f"e.location_id in ({location_placeholders})" if allowed_locations else "0"
    return conn.execute(
        f"""
        select e.id, e.name, e.summary, e.location_id, e.owner_id,
               i.category, i.quantity, i.unit, i.quality, i.durability_current,
               i.durability_max, i.stackable, i.equipped_slot
        from entities e
        join items i on i.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        where {normalized_text_sql("e.status")} = 'active'
          {visibility_clause}
          {subtype_visibility_clause}
          and i.category in ('material', 'tool', 'container', 'weapon', 'armor', 'ammunition')
          and (e.owner_id = ? or {location_filter})
        order by
          case i.category
            when 'material' then 0
            when 'tool' then 1
            when 'container' then 2
            else 3
          end,
          e.name
        limit 40
        """,
        (get_player_entity_id(conn), *tuple(allowed_locations)),
    ).fetchall()


def visible_home_location_ids(conn: sqlite3.Connection, meta: dict[str, str]) -> set[str]:
    return {
        location_id
        for location_id in configured_home_location_ids(meta)
        if location_detail_row(conn, location_id)
    }


def configured_home_location_ids(meta: dict[str, str]) -> set[str]:
    raw = meta.get("home_location_ids") or meta.get("base_location_ids")
    if not raw:
        return set()
    value = parse_json(raw, None)
    if isinstance(value, list):
        return {str(item) for item in value if str(item).strip()}
    return {item.strip() for item in re.split(r"[,，、;；\n]+", raw) if item.strip()}


def craft_confirmations(
    project_query: str | None,
    project: sqlite3.Row | None,
    target: str | None,
    target_entity: sqlite3.Row | None,
    materials: list[dict[str, Any]],
    time_cost: str | None,
    recipe: sqlite3.Row | None,
    recipe_profile: Any,
) -> list[str]:
    items: list[str] = []
    if project_query and not project:
        items.append("制作项目未解析：需要确认是新项目还是已有项目别名缺失。")
    if not target:
        items.append("目标成品未指定：必须明确成品名称、数量、品质和用途。")
    elif target_entity and target_entity["type"] not in {"item", "equipment"}:
        items.append(f"目标解析到 {target_entity['type']}，不是成品实体：保存前需要明确 item/equipment 成品。")
    if not materials:
        items.append("材料未指定：保存前必须列出材料、工具、消耗量和剩余量。")
    if not recipe:
        items.append("未匹配结构化配方：保存前必须手动确认输入、输出和失败代价。")
    for material in materials:
        if material["entity"] is None:
            items.append(f"材料未找到：{material['query']}")
        elif material["item"] is None:
            items.append(f"材料不是 item 表实体：{material['entity']['id']}")
        elif material["availability"].startswith("不在手边"):
            items.append(f"材料不在当前可用范围：{material['entity']['name']}（{material['availability']}）")
    if not (time_cost or recipe_time_cost(recipe_profile)):
        items.append("耗时未指定：需要估算制作占用的时段和体力。")
    return items or ["无硬性缺口；仍需由 GM 确认工艺步骤、失败代价和保存 delta。"]


def craft_warnings(
    project: sqlite3.Row | None,
    target: str | None,
    materials: list[dict[str, Any]],
    pc_details: dict[str, Any],
    recipe_profile: Any,
    *,
    energy_label: str = "能量",
) -> list[str]:
    warnings: list[str] = []
    haystack = " ".join(
        [
            project["name"] if project else "",
            project["summary"] if project else "",
            target or "",
            " ".join(str(item["query"]) for item in materials),
            " ".join(item["entity"]["name"] for item in materials if item["entity"]),
            format_value(recipe_profile) if isinstance(recipe_profile, dict) else "",
        ]
    )
    if any(word in haystack for word in ["火药", "硝石", "硫磺", "爆", "引信"]):
        warnings.append("涉及火药/硝石/硫磺/引信：必须确认远离火源、防潮、失败后果和森林注意。")
    if any(word in haystack for word in ["毒", "麻痹", "麻箭", "毒刺", "渊刺", "见血封喉"]):
        warnings.append("涉及毒物或麻痹材料：必须记录污染、误伤和处理工具清洁。")
    if any(word in haystack for word in [energy_label, "催熟", "种"]):
        warnings.append(f"涉及{energy_label}或催熟：必须扣减{energy_label}，并考虑土壤肥力/环境注意。")
    stamina = str(pc_details.get("stamina", ""))
    if "███" in stamina or "疲" in stamina:
        warnings.append("主角当前疲劳明显：精细制作、火药和武器校准应提高失误风险或延长耗时。")
    return warnings


def build_craft_delta(
    *,
    conn: sqlite3.Connection | None = None,
    meta: dict[str, str],
    location: sqlite3.Row | None,
    project: sqlite3.Row | None,
    recipe: sqlite3.Row | None,
    recipe_profile: Any,
    target: str | None,
    target_entity: sqlite3.Row | None,
    materials: list[dict[str, Any]],
    time_cost: str | None,
    user_text: str | None,
) -> dict[str, Any]:
    target_name = target or (target_entity["name"] if target_entity else "未指定成品")
    project_name = project["name"] if project else "未指定项目"
    effective_time = time_cost or recipe_time_cost(recipe_profile)
    summary = f"预演制作：{project_name} -> {target_name}；材料扣减和成品实体待 GM 确认。"
    delta = {
        "user_text": user_text or "制作行动预演生成的草案",
        "intent": "craft",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": f"{meta.get('current_time_block', '当前时段')} + {effective_time or '未定耗时'}（草案）",
        "location_before": location["id"] if location else None,
        "location_after": location["id"] if location else None,
        "summary": summary,
        "events": [
            {
                "type": "craft",
                "title": "制作行动结算",
                "summary": summary,
                "payload": {
                    "project_id": project["id"] if project else None,
                    "recipe_id": recipe["id"] if recipe else None,
                    "target_id": target_entity["id"] if target_entity else None,
                    "target_name": target_name,
                    "recipe_output": recipe_profile.get("output") if isinstance(recipe_profile, dict) else None,
                    "recipe_inputs": recipe_profile.get("inputs", []) if isinstance(recipe_profile, dict) else [],
                    "location_id": location["id"] if location else meta.get("current_location_id"),
                    "time_cost": effective_time,
                    "materials": [
                        {
                            "query": item["query"],
                            "entity_id": item["entity"]["id"] if item["entity"] else None,
                            "availability": item["availability"],
                        }
                        for item in materials
                    ],
                    "needs_gm_resolution": True,
                    "material_consumption_required": True,
                    "output_entity_required": target_entity is None or target_entity["type"] not in {"item", "equipment"},
                },
                "source": "craft_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": recipe_tick_clocks(recipe_profile),
    }
    return redact_hidden_entity_refs(conn, delta, drop_empty=False) if conn else delta


def location_detail_row(conn: sqlite3.Connection, entity_id: str | None) -> sqlite3.Row | None:
    if not entity_id:
        return None
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    subtype_visibility_clause = entity_subtype_visibility_sql("player", "e", "c")
    return conn.execute(
        f"""
        select e.id, e.name, e.type, e.status, e.visibility, e.location_id, e.owner_id,
               e.summary, e.details_json,
               l.parent_id, l.coord_x, l.coord_y, l.coord_z, l.biome, l.safety_level,
               l.travel_minutes_from_home, l.description_short, l.exits_json, l.resources_json
        from entities e
        left join locations l on l.entity_id = e.id
        where e.id = ?
          and e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        """,
        (entity_id,),
    ).fetchone()


def resolve_location(conn: sqlite3.Connection, text: str | None) -> sqlite3.Row | None:
    if not text:
        return None
    ensure_visibility_sql_functions(conn)
    text = str(text).strip()
    visibility_clause = entity_visibility_sql("player", "e")
    exact_id = conn.execute(
        f"""
        select e.*
        from entities e
        where e.id = ?
          and e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        """,
        (text,),
    ).fetchone()
    if exact_id:
        return exact_id
    exact_id_ci = conn.execute(
        f"""
        select e.*
        from entities e
        where lower(e.id) = lower(?)
          and e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        limit 1
        """,
        (text,),
    ).fetchone()
    if exact_id_ci:
        return exact_id_ci
    exact_name = conn.execute(
        f"""
        select e.*
        from entities e
        where e.name = ?
          and e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        order by e.status, e.id
        limit 1
        """,
        (text,),
    ).fetchone()
    if exact_name:
        return exact_name
    alias = conn.execute(
        f"""
        select e.*
        from aliases a
        join entities e on e.id = a.entity_id
        where a.alias = ?
          and e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
        order by e.status, e.id
        limit 1
        """,
        (text,),
    ).fetchone()
    if alias:
        return alias

    terms = [text, *query_tokens(text)]
    for term in terms:
        like = f"%{term}%"
        suffix_like = f"%:{term}"
        fuzzy = conn.execute(
            f"""
            select e.*
            from entities e
            left join aliases a on a.entity_id = e.id
            where e.type = 'location'
              and {entity_not_archived_sql("e")}
              {visibility_clause}
              and (
                lower(e.id) like lower(?)
                or lower(e.id) like lower(?)
                or e.name like ?
                or a.alias like ?
              )
            order by
              case
                when lower(e.id) like lower(?) then 0
                when e.name like ? then 1
                when a.alias like ? then 2
                when lower(e.id) like lower(?) then 3
                else 9
              end,
              length(e.name),
              e.id
            limit 1
            """,
            (suffix_like, like, like, like, suffix_like, like, like, like),
        ).fetchone()
        if fuzzy:
            return fuzzy

    like = f"%{text}%"
    summary_match = conn.execute(
        f"""
        select e.*
        from entities e
        where e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          and (e.name like ? or e.summary like ?)
        order by {entity_type_priority_sql("e")}, e.name
        limit 1
        """,
        (like, like),
    ).fetchone()
    if summary_match:
        return summary_match
    safe_query = sanitize_fts_query(text)
    if not safe_query:
        return None
    fts = conn.execute(
        f"""
        select e.*
        from fts_index f
        join entities e on e.id = f.entity_id
        where e.type = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          and fts_index match ?
        order by bm25(fts_index), e.id
        limit 1
        """,
        (safe_query,),
    ).fetchone()
    return fts


def estimate_travel_minutes(
    current: sqlite3.Row | None,
    destination: sqlite3.Row | None,
) -> int | None:
    if not current or not destination:
        return None
    current_minutes = current["travel_minutes_from_home"]
    destination_minutes = destination["travel_minutes_from_home"]
    if current["id"] == destination["id"]:
        return 0
    if destination_minutes is None:
        return None
    if current_minutes in {None, 0}:
        return int(destination_minutes)
    return max(5, abs(int(destination_minutes) - int(current_minutes)))


def find_route(
    conn: sqlite3.Connection,
    current: sqlite3.Row | None,
    destination: sqlite3.Row | None,
) -> dict[str, Any] | None:
    if not current or not destination:
        return None
    if current["id"] == destination["id"]:
        return None
    return shortest_route_plan(conn, current["id"], destination["id"])


def shortest_route_plan(conn: sqlite3.Connection, start_id: str, destination_id: str) -> dict[str, Any] | None:
    ensure_visibility_sql_functions(conn)
    from_visibility_clause = entity_visibility_sql("player", "from_e")
    to_visibility_clause = entity_visibility_sql("player", "to_e")
    rows = conn.execute(
        f"""
        select r.*
        from routes r
        join entities from_e on from_e.id = r.from_location_id
        join entities to_e on to_e.id = r.to_location_id
        where from_e.type = 'location'
          and to_e.type = 'location'
          and {entity_not_archived_sql("from_e")}
          and {entity_not_archived_sql("to_e")}
          {from_visibility_clause}
          {to_visibility_clause}
        order by r.id
        """
    ).fetchall()
    if not rows:
        return None
    graph: dict[str, list[tuple[str, sqlite3.Row, int]]] = {}
    for row in rows:
        minutes = int(row["travel_minutes"] or 0)
        if minutes <= 0:
            continue
        graph.setdefault(row["from_location_id"], []).append((row["to_location_id"], row, minutes))
        graph.setdefault(row["to_location_id"], []).append((row["from_location_id"], row, minutes))
    if start_id not in graph or destination_id not in graph:
        return None

    counter = 0
    queue: list[tuple[int, int, str, list[dict[str, Any]]]] = [(0, counter, start_id, [])]
    best: dict[str, int] = {start_id: 0}
    while queue:
        total_minutes, _, location_id, path = heapq.heappop(queue)
        if location_id == destination_id:
            return route_plan_from_segments(start_id, destination_id, path)
        if total_minutes > best.get(location_id, 10**9):
            continue
        for next_id, row, minutes in graph.get(location_id, []):
            candidate = total_minutes + minutes
            if candidate >= best.get(next_id, 10**9):
                continue
            best[next_id] = candidate
            segment = {
                "id": row["id"],
                "from_location_id": location_id,
                "to_location_id": next_id,
                "travel_minutes": minutes,
                "difficulty": row["difficulty"],
                "hazards_json": row["hazards_json"],
                "requirements_json": row["requirements_json"],
            }
            counter += 1
            heapq.heappush(queue, (candidate, counter, next_id, [*path, segment]))
    return None


def route_plan_from_segments(
    start_id: str,
    destination_id: str,
    segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not segments:
        return None
    route_ids = [str(segment["id"]) for segment in segments]
    return {
        "id": " -> ".join(route_ids),
        "route_ids": route_ids,
        "from_location_id": start_id,
        "to_location_id": destination_id,
        "travel_minutes": sum(int(segment["travel_minutes"] or 0) for segment in segments),
        "difficulty": aggregate_route_difficulty(segments),
        "hazards_json": json.dumps(aggregate_route_values(segments, "hazards_json"), ensure_ascii=False),
        "requirements_json": json.dumps(aggregate_route_values(segments, "requirements_json"), ensure_ascii=False),
        "segments": segments,
    }


def aggregate_route_difficulty(segments: list[dict[str, Any]]) -> str:
    ranks = {
        "easy": 0,
        "friendly": 0,
        "normal": 1,
        "risky": 2,
        "wary": 3,
        "dangerous": 4,
        "hostile": 4,
        "unknown": 5,
    }
    worst = max(segments, key=lambda item: ranks.get(str(item.get("difficulty") or "unknown"), 5))
    return str(worst.get("difficulty") or "unknown")


def aggregate_route_values(segments: list[dict[str, Any]], key: str) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for segment in segments:
        for value in parse_json(str(segment.get(key) or "[]"), []):
            marker = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
            if marker in seen:
                continue
            seen.add(marker)
            values.append(value)
    return values


def route_between(conn: sqlite3.Connection, from_location_id: str, to_location_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select *
        from routes
        where from_location_id = ?
          and to_location_id = ?
        order by travel_minutes, id
        limit 1
        """,
        (from_location_id, to_location_id),
    ).fetchone()


def format_minutes(minutes: int | None) -> str:
    if minutes is None:
        return "未知"
    if minutes == 0:
        return "0分钟"
    return f"约{minutes}分钟"


def destination_threats(conn: sqlite3.Connection, location_id: str | None) -> list[sqlite3.Row]:
    if not location_id:
        return []
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    return conn.execute(
        f"""
        select e.id, e.name, e.type, e.summary, e.location_id, e.owner_id, e.status, e.visibility
        from entities e
        where {normalized_text_sql("e.status")} = 'active'
          and e.type = 'threat'
          and e.location_id = ?
          {visibility_clause}
        order by e.visibility, e.name
        """,
        (location_id,),
    ).fetchall()


def destination_occupants(conn: sqlite3.Connection, location_id: str | None) -> list[sqlite3.Row]:
    if not location_id:
        return []
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    return conn.execute(
        f"""
        select e.id, e.name, e.type, e.summary, e.location_id, e.owner_id, e.status, e.visibility
        from entities e
        where {normalized_text_sql("e.status")} = 'active'
          and e.type in ('character', 'item', 'project')
          and e.location_id = ?
          and e.id != ?
          {visibility_clause}
        order by
          case e.type when 'character' then 0 when 'project' then 1 else 2 end,
          e.name
        limit 12
        """,
        (location_id, get_player_entity_id(conn)),
    ).fetchall()


def crop_plot_for_entity(conn: sqlite3.Connection, entity_id: str) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    plot_visibility_clause = entity_visibility_sql("player", "e")
    crop_visibility_clause = entity_visibility_sql("player", "ce")
    plot_subtype_clause = entity_subtype_visibility_sql("player", "e", "plot_clock")
    crop_subtype_clause = entity_subtype_visibility_sql("player", "ce", "crop_clock")
    return conn.execute(
        f"""
        select p.*, ce.name as crop_name
        from crop_plots p
        join entities e on e.id = p.entity_id
        join entities ce on ce.id = p.crop_entity_id
        left join clocks plot_clock on plot_clock.entity_id = e.id
        left join clocks crop_clock on crop_clock.entity_id = ce.id
        where p.entity_id = ?
          and {entity_not_archived_sql("e")}
          and {entity_not_archived_sql("ce")}
          {plot_visibility_clause}
          {crop_visibility_clause}
          {plot_subtype_clause}
          {crop_subtype_clause}
        """,
        (entity_id,),
    ).fetchone()


def harvestable_crop_rows(conn: sqlite3.Connection, current_day: int | None) -> list[sqlite3.Row]:
    day = current_day or 0
    ensure_visibility_sql_functions(conn)
    plot_visibility_clause = entity_visibility_sql("player", "e")
    crop_visibility_clause = entity_visibility_sql("player", "ce")
    plot_subtype_clause = entity_subtype_visibility_sql("player", "e", "plot_clock")
    crop_subtype_clause = entity_subtype_visibility_sql("player", "ce", "crop_clock")
    return conn.execute(
        f"""
        select p.*, ce.name as crop_name
        from crop_plots p
        join entities e on e.id = p.entity_id
        join entities ce on ce.id = p.crop_entity_id
        left join clocks plot_clock on plot_clock.entity_id = e.id
        left join clocks crop_clock on crop_clock.entity_id = ce.id
        where {entity_not_archived_sql("e")}
          and {entity_not_archived_sql("ce")}
          {plot_visibility_clause}
          {crop_visibility_clause}
          {plot_subtype_clause}
          {crop_subtype_clause}
          and (
            p.harvest_status in ('partial_harvest', 'repeat_harvest', 'regrowing')
            or (p.harvest_day_min is not null and p.harvest_day_min <= ?)
            or (p.growth_stage_max is not null and p.growth_stage >= p.growth_stage_max)
          )
        order by
          case p.harvest_status
            when 'partial_harvest' then 0
            when 'repeat_harvest' then 1
            when 'regrowing' then 2
            else 3
          end,
          p.plot_no
        """,
        (day,),
    ).fetchall()


def gatherable_items(conn: sqlite3.Connection, location_id: str | None) -> list[sqlite3.Row]:
    if not location_id:
        return []
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    subtype_visibility_clause = entity_subtype_visibility_sql("player", "e", "c")
    return conn.execute(
        f"""
        select e.id, e.name, e.summary, e.location_id, e.owner_id,
               i.category, i.quantity, i.unit, i.quality, i.durability_current,
               i.durability_max, i.stackable, i.equipped_slot
        from entities e
        join items i on i.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        where {normalized_text_sql("e.status")} = 'active'
          {visibility_clause}
          {subtype_visibility_clause}
          and e.location_id = ?
          and i.category in ('food', 'material', 'tool', 'container')
        order by i.category, e.name
        limit 20
        """,
        (location_id,),
    ).fetchall()


def gather_confirmations(
    conn: sqlite3.Connection,
    target_query: str | None,
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    current: sqlite3.Row | None,
    crop: sqlite3.Row | None,
    meta: dict[str, str],
) -> list[str]:
    items: list[str] = []
    current_location_id = current["id"] if current else None
    if meta.get("current_location_id") and not current:
        items.append("当前地点不可见或不存在：不能保存采集结果。")
    if target_query and not target:
        items.append(f"采集目标未找到：{target_query}")
    if not location:
        items.append("采集地点未解析：需要确认当前位置或目的地。")
    elif current_location_id and location["id"] != current_location_id:
        items.append(f"目标地点不是当前位置：当前在 {location_label(current)}，需要先结算 travel 或同回合明确旅行耗时/风险。")
    if target and location and target["location_id"] and target["location_id"] != location["id"]:
        items.append(f"目标不在指定地点：{entity_ref_label(conn, target['location_id'])}；可能需要改地点或先 travel。")
    if not target:
        items.append("目标未指定：保存前必须明确采集对象和产出。")
    if target and target["type"] == "crop_plot" and not crop:
        items.append("目标是农田但缺少 crop_plot 行：不能可靠结算收获。")
    if crop:
        items.append("作物收获必须确认采收部位、留根/留种、再生周期和产出数量。")
    items.append("保存前必须明确新增库存的 id/name/category/quantity/unit/location。")
    return items


def is_home_location(location: sqlite3.Row | None, meta: dict[str, str]) -> bool:
    return bool(location and location["id"] in configured_home_location_ids(meta))


def build_gather_delta(
    *,
    meta: dict[str, str],
    current_location_id: str,
    target: sqlite3.Row | None,
    location: sqlite3.Row | None,
    crop: sqlite3.Row | None,
    user_text: str | None,
) -> dict[str, Any]:
    target_name = target["name"] if target else "未指定目标"
    location_id = location["id"] if location else meta.get("current_location_id")
    travel_required = bool(current_location_id and location_id and current_location_id != location_id)
    summary = f"预演采集/收获：{target_name}；实际产出和资源状态待 GM 确认。"
    return {
        "user_text": user_text or "采集/收获预演生成的草案",
        "intent": "gather",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": f"{meta.get('current_time_block', '当前时段')} + 采集耗时（草案）",
        "location_before": current_location_id,
        "location_after": location_id,
        "summary": summary,
        "events": [
            {
                "type": "gather",
                "title": "采集/收获结算",
                "summary": summary,
                "payload": {
                    "target_id": target["id"] if target else None,
                    "target_type": target["type"] if target else None,
                    "from_location_id": current_location_id,
                    "location_id": location_id,
                    "travel_required": travel_required,
                    "crop_plot": {
                        "plot_no": crop["plot_no"],
                        "crop_entity_id": crop["crop_entity_id"],
                        "harvest_status": crop["harvest_status"],
                    }
                    if crop
                    else None,
                    "needs_gm_resolution": True,
                    "output_quantity_required": True,
                    "resource_state_update_required": True,
                },
                "source": "gather_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }


def social_relevant_clocks(
    conn: sqlite3.Connection,
    npc: sqlite3.Row | None,
    topic: str | None,
    approach: str | None,
) -> list[sqlite3.Row]:
    text = " ".join([npc["name"] if npc else "", topic or "", approach or ""])
    rows = matching_clock_rows(conn, clock_query_terms(text), limit=3)
    if rows:
        return rows
    ensure_visibility_sql_functions(conn)
    entity_visibility_clause = entity_visibility_sql("player", "e")
    clock_visibility_clause = clock_visibility_sql("player", "c")
    subtype_visibility_clause = entity_subtype_visibility_sql("player", "e", "c")
    return conn.execute(
        f"""
        select c.entity_id, e.name, c.segments_filled, c.segments_total,
               c.visibility, c.trigger_when_full
        from clocks c
        join entities e on e.id = c.entity_id
        where c.clock_type in ('relationship', 'faction')
          and {entity_not_archived_sql("e")}
          {entity_visibility_clause}
          {clock_visibility_clause}
          {subtype_visibility_clause}
        order by c.visibility desc, c.entity_id
        limit 2
        """,
    ).fetchall()


def suggested_social_clock_ticks(
    conn: sqlite3.Connection,
    npc: sqlite3.Row | None,
    topic: str | None,
    approach: str | None,
) -> list[dict[str, Any]]:
    text = " ".join([npc["name"] if npc else "", topic or "", approach or ""])
    ticks: list[dict[str, Any]] = []
    if any(word in text for word in ["履行", "交换", "交易", "送", "食物", "盐", "调料"]):
        clock = first_matching_clock(conn, ["履行", "交换", "交易", "承诺", "食物", "盐", "调料", *clock_query_terms(text)])
        if clock:
            ticks.append({"id": clock["entity_id"], "delta": 1, "reason": "履行交换/食物/盐/调料承诺"})
    if any(word in text for word in ["湖边", "聚落", "武装接近"]):
        clock = first_matching_clock(conn, ["聚落", "警惕", "武装", "接近", "suspicion", *clock_query_terms(text)])
        if clock:
            ticks.append({"id": clock["entity_id"], "delta": 1, "reason": "接近警惕聚落或暴露武装姿态"})
    return ticks


def social_confirmations(
    conn: sqlite3.Connection,
    npc_query: str | None,
    npc: sqlite3.Row | None,
    character: sqlite3.Row | None,
    topic: str | None,
    approach: str | None,
    meta: dict[str, str],
) -> list[str]:
    items: list[str] = []
    if not current_location_row(conn, meta):
        items.append("当前地点未登记、不可见或不存在：不能保存社交结果。")
    if npc_query and not npc:
        items.append(f"社交对象未找到：{npc_query}")
    if npc and npc["type"] != "character":
        items.append(f"社交对象不是 character：{npc['id']}（{npc['type']}）")
    if not npc:
        items.append("对象未指定：保存前必须明确 NPC/群体。")
    if npc and npc["location_id"] and npc["location_id"] != meta.get("current_location_id"):
        items.append(f"对象不在当前地点：{location_id_label(conn, npc['location_id'])}；可能需要先 travel。")
    if not topic:
        items.append("主题未指定：需要明确交易、询问、承诺、道歉、接触或威慑。")
    if not approach:
        items.append("方式未指定：需要明确礼物、姿态、语言/石板、距离和武器处理。")
    if character:
        items.append("关系变化必须记录 trust/attitude/承诺，不只写对话散文。")
    return items


def social_risks(
    npc: sqlite3.Row | None,
    topic: str | None,
    approach: str | None,
) -> list[str]:
    text = " ".join([npc["name"] if npc else "", topic or "", approach or ""])
    risks = []
    if any(word in text for word in ["武装", "弩", "威慑", "逼近"]):
        risks.append("武器可见或威慑姿态会降低信任，并可能推动警惕进度钟。")
    if any(word in text for word in ["承诺", "交易", "交换"]):
        risks.append("新承诺必须保存为项目/人物细节，否则后续容易遗忘。")
    if any(word in text for word in ["湖边", "聚落"]):
        risks.append("湖边聚落尚未正式接触；直接接近比通过 An 中介风险更高。")
    return risks or ["未发现额外结构化警告；仍需按对方反应确认关系变化。"]


def build_social_delta(
    *,
    meta: dict[str, str],
    current_location_id: str | None,
    npc: sqlite3.Row | None,
    character: sqlite3.Row | None,
    topic: str | None,
    approach: str | None,
    suggested_ticks: list[dict[str, Any]],
    user_text: str | None,
) -> dict[str, Any]:
    npc_name = npc["name"] if npc else "未指定对象"
    summary = f"预演社交：与{npc_name}围绕{topic or '未指定主题'}互动；实际关系和交易结果待 GM 确认。"
    return {
        "user_text": user_text or "社交/交易预演生成的草案",
        "intent": "social",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": f"{meta.get('current_time_block', '当前时段')} + 社交耗时（草案）",
        "location_before": current_location_id,
        "location_after": current_location_id,
        "summary": summary,
        "events": [
            {
                "type": "social",
                "title": "社交/交易结算",
                "summary": summary,
                "payload": {
                    "npc_id": npc["id"] if npc else None,
                    "topic": topic,
                    "approach": approach,
                    "trust_before": character["trust"] if character else None,
                    "needs_gm_resolution": True,
                    "relationship_update_required": True,
                    "trade_items_required": True,
                },
                "source": "social_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [{"id": item["id"], "delta": item["delta"]} for item in suggested_ticks],
    }


def travel_confirmations(
    destination_query: str | None,
    destination_entity: sqlite3.Row | None,
    destination: sqlite3.Row | None,
    current: sqlite3.Row | None,
    travel_minutes: int | None,
    pc_details: dict[str, Any],
) -> list[str]:
    items: list[str] = []
    if not destination_query:
        items.append("目的地未指定：旅行前必须明确到达地点。")
    elif not destination_entity:
        items.append(f"目的地未找到：{destination_query}")
    elif destination_entity["type"] != "location":
        items.append(f"目的地不是 location 类型：{destination_entity['id']}（{destination_entity['type']}）")
    if not current:
        items.append("当前地点未解析：不能可靠估算路线。")
    if not destination:
        items.append("目的地缺少 location 详情：不能可靠估算安全等级和资源。")
    if travel_minutes is None:
        items.append("路线耗时未知：GM 必须手动估算耗时。")
    if "疲" in str(pc_details.get("stamina", "")):
        items.append("主角疲劳状态旅行：必须确认是否降低速度、增加遭遇风险或消耗体力。")
    items.append("出发前确认携带物：背包、武器、弹药、竹水筒、南瓜是否同行。")
    return items


def travel_risks(
    destination: sqlite3.Row | None,
    threats: list[sqlite3.Row],
    pc_details: dict[str, Any],
    pace: str | None,
) -> list[str]:
    risks: list[str] = []
    if destination:
        safety = destination["safety_level"]
        if safety in {None, "", "unknown", "risky", "wary", "moderate"}:
            risks.append(f"目的地安全等级为 {safety or '未登记'}：到达后必须先输出风险和迹象。")
    if threats:
        risks.append(f"目的地登记有 {len(threats)} 个 active 威胁。")
    if "疲" in str(pc_details.get("stamina", "")):
        risks.append("疲劳会影响观察、潜行、奔跑和战斗反应。")
    if pace and pace not in {"normal", "正常", "普通"}:
        risks.append(f"非普通步速：{pace}；需要调整耗时、噪音和体力消耗。")
    return risks


def suggested_travel_clock_ticks(
    conn: sqlite3.Connection,
    destination: sqlite3.Row | None,
) -> list[dict[str, Any]]:
    if not destination:
        return []
    ticks: list[dict[str, Any]] = []
    text = " ".join([destination["id"], destination["name"], destination["summary"] or ""])
    clock = first_matching_clock(conn, ["聚落", "警惕", "武装", "接近", "suspicion", *clock_query_terms(text)])
    if clock:
        ticks.append({"id": clock["entity_id"], "delta": 1, "reason": "武装或直接靠近高警惕区域"})
    return ticks


def build_travel_delta(
    conn: sqlite3.Connection,
    *,
    meta: dict[str, str],
    pc: sqlite3.Row | None,
    character: sqlite3.Row | None,
    current: sqlite3.Row | None,
    destination: sqlite3.Row | None,
    travel_minutes: int | None,
    pace: str | None,
    threats: list[sqlite3.Row],
    route: dict[str, Any] | None,
    suggested_ticks: list[dict[str, Any]],
    user_text: str | None,
) -> dict[str, Any]:
    destination_id = destination["id"] if destination else None
    current_id = current["id"] if current else meta.get("current_location_id")
    summary = travel_summary(current, destination, travel_minutes)
    delta: dict[str, Any] = {
        "user_text": user_text or "旅行行动预演生成的草案",
        "intent": "travel",
        "changed": True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": f"{meta.get('current_time_block', '当前时段')} + {format_minutes(travel_minutes)}（草案）",
        "location_before": current_id,
        "location_after": destination_id,
        "summary": summary,
        "events": [
            {
                "type": "travel",
                "title": "旅行行动结算",
                "summary": summary,
                "payload": {
                    "from_location_id": current_id,
                    "to_location_id": destination_id,
                    "route_id": route["id"] if route else None,
                    "route_ids": route.get("route_ids", []) if route else [],
                    "route_segments": redact_hidden_entity_refs(conn, route.get("segments", [])) if route else [],
                    "estimated_minutes": travel_minutes,
                    "pace": pace or "normal",
                    "route_difficulty": route["difficulty"] if route else None,
                    "route_hazards": redact_hidden_entity_refs(conn, parse_json(route["hazards_json"], [])) if route else [],
                    "route_requirements": redact_hidden_entity_refs(conn, parse_json(route["requirements_json"], [])) if route else [],
                    "destination_safety": destination["safety_level"] if destination else None,
                    "known_threat_ids": [row["id"] for row in threats],
                    "needs_gm_resolution": True,
                    "arrival_scene_required": True,
                },
                "source": "travel_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [{"id": item["id"], "delta": item["delta"]} for item in suggested_ticks],
        "meta": {
            "current_location_id": destination_id or current_id,
            "current_time_block": f"{meta.get('current_time_block', '当前时段')} + {format_minutes(travel_minutes)}（到达{destination['name'] if destination else '未知地点'}，草案）",
        },
    }
    if pc and destination:
        delta["upsert_entities"].append(pc_travel_delta_entity(conn, pc, character, destination, travel_minutes))
    return delta


def travel_summary(
    current: sqlite3.Row | None,
    destination: sqlite3.Row | None,
    travel_minutes: int | None,
) -> str:
    return (
        f"从{current['name'] if current else '当前地点'}前往"
        f"{destination['name'] if destination else '未指定目的地'}，预计{format_minutes(travel_minutes)}；"
        "到达后需要输出场景入场包。"
    )


def pc_travel_delta_entity(
    conn: sqlite3.Connection,
    pc: sqlite3.Row,
    character: sqlite3.Row | None,
    destination: sqlite3.Row,
    travel_minutes: int | None,
) -> dict[str, Any]:
    details = parse_json(pc["details_json"], {})
    health = details.get("health") or (character["health_state"] if character else "██████████  良好")
    stamina = details.get("stamina", "未登记")
    hunger = details.get("hunger", "未登记")
    thirst = details.get("thirst", "未登记")
    meta = get_meta(conn)
    energy_label = primary_energy_label(meta)
    energy_value = primary_energy_value(details, meta)
    location_text = f"{destination['name']}（旅行到达/耗时{format_minutes(travel_minutes)}，草案）"
    details["location_text"] = location_text
    entity: dict[str, Any] = {
        "id": pc["id"],
        "type": pc["type"],
        "name": pc["name"],
        "status": pc["status"],
        "visibility": pc["visibility"],
        "location_id": destination["id"],
        "owner_id": pc["owner_id"],
        "summary": (
            f"健康{health}；体力{stamina}；饥饿{hunger}；口渴{thirst}；"
            f"{energy_label}{energy_value}；位置{location_text}"
        ),
        "details": details,
        "aliases": entity_aliases(conn, pc["id"]),
    }
    if character:
        entity["character"] = {
            "species_id": character["species_id"],
            "role": character["role"],
            "attitude": character["attitude"],
            "trust": character["trust"],
            "health_state": health,
            "stress": parse_json(character["stress_json"], {}),
            "consequences": parse_json(character["consequences_json"], []),
            "goals": parse_json(character["goals_json"], []),
            "knowledge": parse_json(character["knowledge_json"], {}),
        }
    return entity


def item_delta_entity(
    conn: sqlite3.Connection,
    entity: sqlite3.Row,
    item: sqlite3.Row,
    quantity: float,
) -> dict[str, Any]:
    return {
        "id": entity["id"],
        "type": entity["type"],
        "name": entity["name"],
        "status": entity["status"],
        "visibility": entity["visibility"],
        "location_id": entity["location_id"],
        "owner_id": entity["owner_id"],
        "summary": entity["summary"],
        "details": parse_json(entity["details_json"], {}),
        "aliases": entity_aliases(conn, entity["id"]),
        "item": {
            "category": item["category"],
            "quantity": quantity,
            "unit": item["unit"],
            "quality": item["quality"],
            "durability_current": item["durability_current"],
            "durability_max": item["durability_max"],
            "stackable": bool(item["stackable"]),
            "equipped_slot": item["equipped_slot"],
            "properties": parse_json(item["properties_json"], {}),
        },
    }


def entity_aliases(conn: sqlite3.Connection, entity_id: str) -> list[str]:
    return [
        row["alias"]
        for row in conn.execute(
            "select alias from aliases where entity_id = ? and kind = 'name' order by alias",
            (entity_id,),
        ).fetchall()
    ]


def decremented_quantity(item: sqlite3.Row) -> float:
    quantity = float(item["quantity"] or 0)
    return max(0, quantity - 1)


def format_quantity_text(quantity: float, unit: str | None) -> str:
    if float(quantity).is_integer():
        quantity = int(quantity)
    return f"{quantity}{unit or ''}"


def draft_summary(
    target: sqlite3.Row | None,
    weapon: sqlite3.Row | None,
    ammo: sqlite3.Row | None,
    distance: str | None,
) -> str:
    target_name = target["name"] if target else "未指定目标"
    weapon_name = weapon["name"] if weapon else "未指定武器"
    ammo_name = ammo["name"] if ammo else "未指定弹药"
    distance_text = distance or "未指定距离"
    return f"使用{weapon_name}装填{ammo_name}，对{target_name}进行{distance_text}战斗行动。"
