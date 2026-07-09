from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .atomic_io import write_text_atomic
from .campaign import Campaign
from .card_registry import CardRegistry, get_default_card_registry
from .db import (
    entity_subtype_visibility_sql,
    get_meta,
    get_player_entity_id,
    resolve_entity,
    world_setting_entity_join_and_clause,
)
from .player_resources import player_detail_items
from .redaction import redact_hidden_entity_refs, redact_player_hidden_material
from .time_weather import format_time_brief, format_weather_brief
from .visibility import (
    PLAYER_VIEW,
    can_read_hidden,
    clock_visibility_sql,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalize_visibility_view,
    normalized_text_sql,
)


def parse_json(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


ID_PREFIXES = {
    "char",
    "clock",
    "creature",
    "fstate",
    "item",
    "loc",
    "mat",
    "pc",
    "plant",
    "plot",
    "project",
    "recipe",
    "ref",
    "rel",
    "rule",
    "species",
    "threat",
    "world",
}

VALUE_LABELS = {
    "active": "活跃",
    "archived": "已归档",
    "completed": "已完成",
    "retired": "已退役",
    "planned": "规划中",
    "known": "已知",
    "visible": "可见",
    "hinted": "有线索",
    "hidden": "隐藏",
    "gm": "GM可见",
    "player": "玩家",
    "maintenance": "维护",
    "character": "角色",
    "location": "地点",
    "equipment": "装备",
    "item": "物品",
    "plant": "植物",
    "material": "材料",
    "species": "物种",
    "clock": "进度钟",
    "rule": "规则",
    "world_setting": "大世界设定",
    "crop_plot": "农田",
    "faction_state": "阵营状态",
    "relationship": "关系",
    "project": "项目",
    "recipe": "配方",
    "reference": "参考资料",
    "threat": "威胁",
    "weapon": "武器",
    "armor": "防具",
    "container": "容器",
    "ammunition": "弹药",
    "food": "食物",
    "tool": "工具",
    "trap": "陷阱",
    "living_civilization_core": "活体文明核心",
    "living_material": "活体材料",
    "medicinal_herb": "药草",
    "plant_material": "植物材料",
    "plant_sample": "植物样本",
    "social_token": "社交信物",
    "legendary": "传奇",
    "unique": "唯一",
    "normal": "普通",
    "fresh": "新鲜",
    "full": "满",
    "merged": "已合并",
    "opened_mature": "已开封成熟",
    "disassembled_recovered": "拆解回收",
    "base": "基地",
    "condition": "状态",
    "ecology": "生态",
    "faction": "阵营",
    "mystery": "谜团",
    "season": "季节",
    "truth": "世界真相",
    "calendar": "历法",
    "weather": "天气",
    "power": "力量体系",
    "technology": "技术",
    "species_culture": "物种文化",
    "artifact": "神器",
    "clue": "线索",
    "craft": "制作",
    "divinity": "神性",
    "economy": "经济",
    "exploration": "探索",
    "gather": "采集",
    "gm": "GM",
    "inventory": "库存",
    "resource": "资源",
    "risk": "风险",
    "survival": "生存",
    "travel": "旅行",
    "play": "游玩",
    "world": "世界",
    "common": "常见",
    "uncommon": "少见",
    "uncommon_local": "局部少见",
    "rare": "稀有",
    "save_fact": "存档事实",
    "confirmed": "已确认",
    "unknown": "未知",
    "existing_save_reasonable_inference": "基于既有存档的合理推断",
    "conservative_structured_metadata": "保守结构化补强",
    "0013_high_frequency_content_enrichment": "0013 高频内容补强",
    "confirmed facts stay confirmed; uncertain world details are stored under unknowns/uncertain_questions.": (
        "已确认事实保持已确认；不确定设定写入未知/待确认问题"
    ),
    "fertile": "肥沃",
    "stable": "稳定",
    "tired": "疲弱",
    "depleted": "枯竭",
    "surplus": "充裕",
    "tight": "紧张",
    "critical": "危急",
    "severe": "严重",
    "growing": "生长中",
    "partial_harvest": "部分收获",
    "planned_not_active": "规划中未启用",
    "needs_check": "需要检查",
    "not_required_planned": "规划中暂不需要",
    "planned_not_rooted": "规划中未定根",
    "forest_clearing": "森林空地",
    "treehouse": "树屋",
    "creek": "小溪",
    "pool": "水潭",
    "pine_forest": "松林",
    "anomaly": "异常点",
    "old_forest": "老林",
    "waterfall": "瀑布",
    "spring": "泉眼",
    "rocky_terrace": "岩石台地",
    "underground_dwelling": "地下居所",
    "river": "河流",
    "delta": "河口三角洲",
    "dry_rock": "干燥岩地",
    "lakeside_settlement": "湖边聚落",
    "mycelium_house": "菌丝屋",
    "mycelium_underground": "地下菌丝城",
    "mycelium_underground_room": "地下菌丝房间",
    "cliff_grassland_edge": "草原崖缘",
    "abandoned_hearth": "废弃火塘",
    "quartz_outcrop": "石英露头",
    "forest_clearing_historical_core": "森林空地旧核心",
    "storage_hut": "储物棚",
    "mycelium_storage": "菌丝仓储",
    "guarded": "有守卫",
    "moderate": "中等",
    "risky": "有风险",
    "friendly": "友好",
    "wary": "警惕",
    "defended": "设防",
    "query": "查询",
    "preview": "预演",
    "explore": "探索",
    "social": "社交",
    "rest": "休息",
    "routine": "日常",
    "combat": "战斗",
}

VISIBILITY_LABELS = {
    **VALUE_LABELS,
    "gm": "GM可见",
}

RULE_CATEGORY_LABELS = {
    **VALUE_LABELS,
    "gm": "主持人",
}

KEY_LABELS = {
    "abundance": "丰度",
    "active": "活跃",
    "after": "之后",
    "applies_when": "适用条件",
    "batch": "批次",
    "category": "分类",
    "clock": "进度钟",
    "clue_text": "线索文本",
    "collection_methods": "采集方法",
    "confidence": "置信度",
    "confidence_rule": "置信规则",
    "confirm_methods": "确认方式",
    "content": "内容",
    "content_enrichment": "内容补强",
    "craft_stages": "制作阶段",
    "current_reliable_location": "当前可靠位置",
    "description": "描述",
    "discovery": "发现线索",
    "distribution": "分布",
    "forage": "采集",
    "keywords": "关键词",
    "location": "位置",
    "magic_plant_regrowth": "魔力植物再生",
    "method": "方法",
    "next_steps": "下一步",
    "note": "备注",
    "old_record": "旧记录",
    "old_record_reliability": "旧记录可靠性",
    "principles": "原则",
    "rarity": "稀有度",
    "resource_profile": "资源档案",
    "risks": "风险",
    "rule": "规则",
    "save_as": "存档归类",
    "scope": "范围",
    "soil": "土壤",
    "source": "来源",
    "state_source": "状态来源",
    "states": "状态档位",
    "storage": "存储",
    "submodes": "子模式",
    "type": "类型",
    "unknowns": "未知项",
    "use": "用途",
    "uses": "用途",
    "v1_quality_enrichment": "v1质量补强",
    "water": "水资源",
}

LABEL_GROUPS = {
    "entity_type": VALUE_LABELS,
    "status": VALUE_LABELS,
    "visibility": VISIBILITY_LABELS,
    "item_category": VALUE_LABELS,
    "quality": VALUE_LABELS,
    "clock_type": VALUE_LABELS,
    "rule_category": RULE_CATEGORY_LABELS,
    "scope": VALUE_LABELS,
    "rarity": VALUE_LABELS,
    "biome": VALUE_LABELS,
    "safety_level": VALUE_LABELS,
    "crop_status": VALUE_LABELS,
    "water_status": VALUE_LABELS,
    "soil_status": VALUE_LABELS,
    "view": VALUE_LABELS,
}


def display_key(key: Any) -> str:
    text = str(key)
    return KEY_LABELS.get(text, text)


def display_label(kind: str, value: Any, *, default: str | None = None) -> str:
    if value in (None, ""):
        return default if default is not None else "未知"
    text = str(value)
    return LABEL_GROUPS.get(kind, {}).get(text, VALUE_LABELS.get(text, text))


def is_reference_id(text: str) -> bool:
    if ":" not in text:
        return False
    prefix, rest = text.split(":", 1)
    return prefix in ID_PREFIXES and bool(rest)


def display_scalar(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value)
    if is_reference_id(text):
        return text
    return VALUE_LABELS.get(text, text)


def bullet_list(items: list[Any]) -> str:
    if not items:
        return "- 无"
    return "\n".join(f"- {format_value(item)}" for item in items)


def format_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "无"
        return "；".join(format_value(item) for item in value)
    if isinstance(value, dict):
        if not value:
            return "无"
        return "；".join(f"{display_key(key)}：{format_value(item)}" for key, item in value.items())
    return display_scalar(value)


def append_item_profile_sections(lines: list[str], properties: dict[str, Any], *, heading_level: int = 3) -> None:
    prefix = "#" * heading_level
    combat = properties.get("combat_profile")
    ammo = properties.get("ammo_profile")
    melee = properties.get("melee_profile")
    defense = properties.get("defense_profile")
    carry = properties.get("carry_profile")
    if isinstance(combat, dict):
        lines.extend(["", f"{prefix} 战斗档案"])
        append_profile_table(
            lines,
            combat,
            [
                ("role", "定位"),
                ("ready_state", "待机状态"),
                ("noise", "声音/暴露"),
                ("wet_weather", "潮湿/雨天"),
            ],
        )
        append_range_bands(lines, combat.get("range_bands"), prefix)
        append_mapping_section(lines, f"{prefix} 装填/操作", combat.get("loading"))
        append_sequence_section(lines, f"{prefix} 操作步骤", combat.get("operation_steps"))
        append_ammo_table(lines, combat.get("compatible_ammo"), prefix)
        append_sequence_section(lines, f"{prefix} 使用限制", combat.get("constraints"))
        append_sequence_section(lines, f"{prefix} 风险", combat.get("risks"))
        append_sequence_section(lines, f"{prefix} 维护", combat.get("maintenance"))
        append_sequence_section(lines, f"{prefix} 结算规则", combat.get("adjudication_rules"))
    if isinstance(melee, dict):
        lines.extend(["", f"{prefix} 近战档案"])
        append_profile_table(
            lines,
            melee,
            [
                ("role", "定位"),
                ("reach", "攻击距离"),
                ("grip", "握持"),
                ("damage_mode", "伤害方式"),
                ("best_use", "适用场景"),
                ("poor_use", "不适合"),
            ],
        )
        append_sequence_section(lines, f"{prefix} 技法/动作", melee.get("techniques"))
        append_sequence_section(lines, f"{prefix} 使用限制", melee.get("constraints"))
        append_sequence_section(lines, f"{prefix} 风险", melee.get("risks"))
        append_sequence_section(lines, f"{prefix} 维护", melee.get("maintenance"))
        append_sequence_section(lines, f"{prefix} 结算规则", melee.get("adjudication_rules"))
    if isinstance(defense, dict):
        lines.extend(["", f"{prefix} 防护档案"])
        append_profile_table(
            lines,
            defense,
            [
                ("role", "定位"),
                ("coverage", "覆盖"),
                ("protection", "防护"),
                ("mobility", "机动影响"),
                ("weak_points", "弱点"),
            ],
        )
        append_sequence_section(lines, f"{prefix} 擅长抵御", defense.get("best_against"))
        append_sequence_section(lines, f"{prefix} 不擅长抵御", defense.get("poor_against"))
        append_sequence_section(lines, f"{prefix} 使用规则", defense.get("use_rules"))
        append_sequence_section(lines, f"{prefix} 风险", defense.get("risks"))
        append_sequence_section(lines, f"{prefix} 维护", defense.get("maintenance"))
        append_sequence_section(lines, f"{prefix} 结算规则", defense.get("adjudication_rules"))
    if isinstance(carry, dict):
        lines.extend(["", f"{prefix} 携行档案"])
        append_profile_table(
            lines,
            carry,
            [
                ("role", "定位"),
                ("capacity", "容量"),
                ("carried_state", "携行状态"),
                ("access", "取用速度"),
                ("long_item_slots", "长物固定"),
                ("mobility", "机动影响"),
            ],
        )
        append_sequence_section(lines, f"{prefix} 装载规则", carry.get("load_rules"))
        append_sequence_section(lines, f"{prefix} 快速取用", carry.get("quick_access"))
        append_sequence_section(lines, f"{prefix} 风险", carry.get("risks"))
        append_sequence_section(lines, f"{prefix} 结算规则", carry.get("adjudication_rules"))
    if isinstance(ammo, dict):
        lines.extend(["", f"{prefix} 弹药档案"])
        append_profile_table(
            lines,
            ammo,
            [
                ("compatible_weapon_id", "兼容武器"),
                ("effect_type", "效果类型"),
                ("primary_effect", "主要效果"),
                ("best_use", "适用场景"),
                ("range_notes", "射程影响"),
                ("reliability", "可靠性"),
            ],
        )
        append_sequence_section(lines, f"{prefix} 限制", ammo.get("limitations"))
        append_sequence_section(lines, f"{prefix} 风险", ammo.get("risks"))
        append_sequence_section(lines, f"{prefix} 结算规则", ammo.get("adjudication_rules"))


def append_profile_table(lines: list[str], values: dict[str, Any], keys: list[tuple[str, str]]) -> None:
    rows = [(label, values.get(key)) for key, label in keys if values.get(key) not in (None, "", [], {})]
    if not rows:
        return
    lines.extend(["| 字段 | 值 |", "|------|----|"])
    for label, value in rows:
        lines.append(f"| {label} | {format_value(value)} |")


def append_range_bands(lines: list[str], value: Any, prefix: str) -> None:
    if not isinstance(value, list) or not value:
        return
    lines.extend(["", f"{prefix} 射程分段", "| 分段 | 距离 | 用法 | 风险 |", "|------|------|------|------|"])
    for item in value:
        if isinstance(item, dict):
            lines.append(
                f"| {format_value(item.get('band', ''))} | {format_value(item.get('distance', ''))} | "
                f"{format_value(item.get('use', ''))} | {format_value(item.get('risk', ''))} |"
            )
        else:
            lines.append(f"|  |  | {format_value(item)} |  |")


def append_ammo_table(lines: list[str], value: Any, prefix: str) -> None:
    if not isinstance(value, list) or not value:
        return
    lines.extend(["", f"{prefix} 兼容弹药", "| 弹药 | 用途 | 备注 |", "|------|------|------|"])
    for item in value:
        if isinstance(item, dict):
            name = item.get("name") or item.get("id") or ""
            entity_id = item.get("id")
            label = f"`{entity_id}` {name}" if entity_id and name != entity_id else format_value(name)
            lines.append(
                f"| {label} | {format_value(item.get('role', ''))} | {format_value(item.get('notes', ''))} |"
            )
        else:
            lines.append(f"| {format_value(item)} |  |  |")


def append_mapping_section(lines: list[str], title: str, value: Any) -> None:
    if not isinstance(value, dict) or not value:
        return
    lines.extend(["", title])
    for key, item in value.items():
        if item not in (None, "", [], {}):
            lines.append(f"- {display_key(key)}: {format_value(item)}")


def append_sequence_section(lines: list[str], title: str, value: Any) -> None:
    if not value:
        return
    if not isinstance(value, list):
        value = [value]
    lines.extend(["", title])
    for item in value:
        lines.append(f"- {format_value(item)}")


def render_entity(conn: sqlite3.Connection, query: str, *, view: str = PLAYER_VIEW) -> str:
    view = normalize_visibility_view(view)
    entity = resolve_entity(conn, query, view=view)
    if entity is None:
        display_query = str(redact_player_hidden_material(conn, query, drop_empty=False)) if view == PLAYER_VIEW else query
        return "\n".join(
            [
                f"未找到实体：`{display_query}`",
                "",
                "可尝试：",
                "- 使用完整实体 ID，例如 `item:powder-arrows`。",
                "- 缩短为更明确的名称、别名或编号，例如 `火药箭`、`T2`、`L05`。",
                "- 如果是在描述一段行动，用 `query context` 或 `start-turn` 让内核加载相关上下文。",
            ]
        )

    spec = get_default_card_registry().by_entity_type(str(entity["type"]))
    if str(entity["type"]) == "world_setting":
        from .content_types.world_setting import render_world_setting_entity

        text = render_world_setting_entity(conn, entity, view=view)
    elif spec and spec.render_query:
        text = spec.render_query(conn, entity)
    else:
        text = render_generic_entity(entity)
    if view == PLAYER_VIEW:
        return str(redact_player_hidden_material(conn, text, drop_empty=False))
    return text


def render_generic_entity(entity: sqlite3.Row) -> str:
    details = parse_json(entity["details_json"], {})
    lines = [
        f"## {entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 类型 | {display_label('entity_type', entity['type'])} |",
        f"| 状态 | {display_label('status', entity['status'])} |",
        f"| 可见性 | {display_label('visibility', entity['visibility'])} |",
        "",
        "### 摘要",
        entity["summary"] or "无",
    ]
    if details:
        lines.extend(["", "### 细节"])
        for key, value in details.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    return "\n".join(lines)


def render_knowledge_entity(entity: sqlite3.Row) -> str:
    details = parse_json(entity["details_json"], {})
    lines = [
        f"## 资料：{entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 类型 | {display_label('entity_type', entity['type'])} |",
        f"| 状态 | {display_label('status', entity['status'])} |",
        f"| 可见性 | {display_label('visibility', entity['visibility'])} |",
        "",
        "### 摘要",
        entity["summary"] or "无",
    ]
    profile = details.get("encyclopedia") or details.get("profile")
    if isinstance(profile, dict) and profile:
        lines.extend(["", "### 结构化信息"])
        for key, value in profile.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    excerpt = details.get("encyclopedia_excerpt") or details.get("profile_excerpt") or details.get("excerpt")
    if excerpt:
        lines.extend(["", "### 资料摘录", format_value(excerpt)])
    if details.get("source"):
        lines.extend(["", "### 来源", str(details["source"])])
    return "\n".join(lines)


def render_item(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
    item = conn.execute("select * from items where entity_id = ?", (entity["id"],)).fetchone()
    details = parse_json(entity["details_json"], {})
    properties = parse_json(item["properties_json"], {}) if item else {}
    location_label = entity["location_id"] or entity["owner_id"] or "未知"
    summary = entity["summary"] or "无"
    lines = [
        f"## 装备/物品：{entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 类型 | {display_label('entity_type', entity['type'])} |",
        f"| 分类 | {display_label('item_category', item['category'], default='未知') if item else '未知'} |",
        f"| 位置 | {location_label} |",
        f"| 状态 | {display_label('status', entity['status'])} |",
        f"| 数量 | {format_quantity(item) if item else '未知'} |",
        f"| 品质 | {display_label('quality', item['quality'], default='未知') if item else '未知'} |",
        f"| 装备槽 | {item['equipped_slot'] if item and item['equipped_slot'] else '无'} |",
        "",
        "### 摘要",
        summary,
    ]
    append_item_profile_sections(lines, properties, heading_level=3)
    hidden_property_keys = {"combat_profile", "ammo_profile", "melee_profile", "defense_profile", "carry_profile"}
    visible_properties = {key: value for key, value in properties.items() if key not in hidden_property_keys}
    if visible_properties:
        lines.extend(["", "### 属性"])
        for key, value in visible_properties.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    if details:
        lines.extend(["", "### 备注"])
        for key, value in details.items():
            if key != "properties":
                lines.append(f"- {display_key(key)}: {format_value(value)}")
    return "\n".join(lines)


def format_quantity(item: sqlite3.Row | None) -> str:
    if not item:
        return "未知"
    quantity = item["quantity"]
    unit = item["unit"] or ""
    if quantity is None:
        return "不适用"
    if float(quantity).is_integer():
        quantity = int(quantity)
    return f"{quantity}{unit}"


def render_character(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
    char = conn.execute("select * from characters where entity_id = ?", (entity["id"],)).fetchone()
    details = parse_json(entity["details_json"], {})
    lines = [
        f"## 人物/生物：{entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 类型 | {display_label('entity_type', entity['type'])} |",
        f"| 位置 | {entity['location_id'] or '未知'} |",
        f"| 状态 | {display_label('status', entity['status'])} |",
        f"| 种族 | {char['species_id'] if char and char['species_id'] else '未知'} |",
        f"| 角色 | {format_value(char['role']) if char and char['role'] else '未知'} |",
        f"| 态度 | {format_value(char['attitude']) if char and char['attitude'] else '未知'} |",
        f"| 信任 | {char['trust'] if char else '未知'} |",
        f"| 健康 | {format_value(char['health_state']) if char and char['health_state'] else '未知'} |",
        "",
        "### 摘要",
        entity["summary"] or "无",
    ]
    if details.get("known_abilities"):
        lines.extend(["", "### 已知能力", bullet_list(details["known_abilities"])])
    if details.get("commitments"):
        lines.extend(["", "### 当前承诺", bullet_list(details["commitments"])])
    if details.get("unknowns"):
        lines.extend(["", "### 未确认信息", bullet_list(details["unknowns"])])
    return "\n".join(lines)


def render_species(entity: sqlite3.Row) -> str:
    details = parse_json(entity["details_json"], {})
    lines = [
        f"## 物种：{entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 类型 | {display_label('entity_type', entity['type'])} |",
        f"| 位置 | {entity['location_id'] or '未知'} |",
        f"| 状态 | {display_label('status', entity['status'])} |",
        f"| 可见性 | {display_label('visibility', entity['visibility'])} |",
        "",
        "### 摘要",
        entity["summary"] or "无",
    ]
    profile = details.get("profile") or details.get("encyclopedia")
    if isinstance(profile, dict) and profile:
        lines.extend(["", "### 结构化信息"])
        for key, value in profile.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    if details.get("known_abilities"):
        lines.extend(["", "### 已知能力", bullet_list(details["known_abilities"])])
    if details.get("unknowns"):
        lines.extend(["", "### 未确认信息", bullet_list(details["unknowns"])])
    if details.get("source"):
        lines.extend(["", "### 来源", str(details["source"])])
    return "\n".join(lines)


def render_location(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
    location = conn.execute("select * from locations where entity_id = ?", (entity["id"],)).fetchone()
    resources = parse_json(location["resources_json"], []) if location else []
    exits = parse_json(location["exits_json"], []) if location else []
    details = parse_json(entity["details_json"], {})
    lines = [
        f"## 地点：{entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 状态 | {display_label('status', entity['status'])} |",
        f"| 生态 | {display_label('biome', location['biome'], default='未知') if location else '未知'} |",
        f"| 安全等级 | {display_label('safety_level', location['safety_level'], default='未知') if location else '未知'} |",
        f"| 距家耗时 | {location['travel_minutes_from_home'] if location and location['travel_minutes_from_home'] is not None else '未知'} 分钟 |",
        "",
        "### 摘要",
        location["description_short"] if location and location["description_short"] else entity["summary"],
        "",
        "### 已知资源",
        bullet_list(resources),
        "",
        "### 出口/路线",
        bullet_list(exits),
    ]
    if details:
        lines.extend(["", "### 备注"])
        for key, value in details.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    return "\n".join(lines)


def render_clock(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
    clock = conn.execute("select * from clocks where entity_id = ?", (entity["id"],)).fetchone()
    if not clock:
        return render_generic_entity(entity)
    filled = int(clock["segments_filled"])
    total = int(clock["segments_total"])
    bar = "■" * filled + "□" * max(total - filled, 0)
    return "\n".join(
        [
            f"## 进度钟：{entity['name']}",
            "",
            "| 字段 | 值 |",
            "|------|----|",
            f"| ID | `{entity['id']}` |",
            f"| 类型 | {display_label('clock_type', clock['clock_type'])} |",
            f"| 进度 | {bar} {filled}/{total} |",
            f"| 可见性 | {display_label('visibility', clock['visibility'])} |",
            f"| 满格触发 | {clock['trigger_when_full']} |",
            "",
            "### 摘要",
            entity["summary"] or "无",
        ]
    )


def render_rule(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
    rule = conn.execute("select * from rules where entity_id = ?", (entity["id"],)).fetchone()
    if not rule:
        return render_generic_entity(entity)
    examples = parse_json(rule["examples_json"], [])
    exceptions = parse_json(rule["exceptions_json"], [])
    return "\n".join(
        [
            f"## 规则：{entity['name']}",
            "",
            "| 字段 | 值 |",
            "|------|----|",
            f"| ID | `{entity['id']}` |",
            f"| 分类 | {display_label('rule_category', rule['category'])} |",
            f"| 范围 | {display_label('scope', rule['scope'])} |",
            f"| 锁定 | {'是' if rule['locked'] else '否'} |",
            f"| 来源 | {rule['source']} |",
            "",
            "### 规则文本",
            rule["statement"],
            "",
            "### 例子",
            bullet_list(examples),
            "",
            "### 例外",
            bullet_list(exceptions),
        ]
    )


def render_scene(conn: sqlite3.Connection, *, view: str = PLAYER_VIEW) -> str:
    ensure_visibility_sql_functions(conn)
    view = normalize_visibility_view(view)
    should_redact = not can_read_hidden(view)

    def safe_value(value: Any) -> Any:
        return redact_player_hidden_material(conn, value, drop_empty=False) if should_redact else value

    registry = get_default_card_registry()
    meta = get_meta(conn)
    location_id = meta.get("current_location_id", "")
    entity_visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    location = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {entity_visibility_clause}
          {subtype_visibility_clause}
        """,
        (location_id,),
    ).fetchone()
    if not location:
        if view == PLAYER_VIEW:
            return "当前地点不可见或不存在"
        return f"当前地点不可见或不存在：`{location_id}`"

    location_details = conn.execute("select * from locations where entity_id = ?", (location_id,)).fetchone()
    present = conn.execute(
        f"""
        select e.id, e.type, e.name, e.summary
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.location_id = ? and {normalized_text_sql("e.status")} = 'active'
          {entity_visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        order by e.name
        """,
        (location_id,),
    ).fetchall()
    present = sorted(present, key=lambda row: entity_sort_key(row, registry))
    player_entity_id = get_player_entity_id(conn)
    carried = conn.execute(
        f"""
        select e.id, e.type, e.name, i.category, i.quantity, i.unit
        from entities e
        join items i on i.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.owner_id = ? and {normalized_text_sql("e.status")} = 'active'
          {entity_visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        order by i.equipped_slot is null, i.equipped_slot, e.name
        limit 20
        """,
        (player_entity_id,),
    ).fetchall()
    clock_visibility_clause = clock_visibility_sql(view, "c")
    clocks = conn.execute(
        f"""
        select e.name, c.segments_filled, c.segments_total, c.visibility
        from clocks c
        join entities e on e.id = c.entity_id
        where {entity_not_archived_sql("e")}
          {clock_visibility_clause}
          {entity_visibility_clause}
        order by c.visibility, e.name
        limit 8
        """
    ).fetchall()

    lines = [
        f"## 当前场景：{location['name']}",
        "",
        "### 全景",
        safe_value(
            location_details["description_short"] if location_details and location_details["description_short"] else location["summary"],
        ),
        "",
        "### 当前状态",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 天气 | {format_weather_brief(meta)} |",
        f"| 季节 | {meta.get('year_label', '未登记')} / {meta.get('season_label', '未登记')} / {meta.get('month_label', '未登记')} |",
        f"| 位置 | `{location_id}` |",
        "",
        "### 近处对象",
    ]
    if present:
        visible_present = present[:12]
        for row in visible_present:
            name = safe_value(row["name"]) or row["name"]
            summary = safe_value(row["summary"]) or "无"
            lines.append(f"- `{row['id']}` {name}（{display_label('entity_type', row['type'])}）：{summary}")
        if len(present) > len(visible_present):
            hidden_count = len(present) - len(visible_present)
            lines.append(f"- 另有 {hidden_count} 项库存/对象已折叠；查询具体物品可用实体查询。")
    else:
        lines.append("- 无已登记对象")

    lines.extend(["", "### 随身重点装备"])
    if carried:
        for row in carried:
            if row["quantity"] is None:
                quantity = ""
            else:
                number = row["quantity"]
                if float(number).is_integer():
                    number = int(number)
                quantity = f" ×{number}{row['unit'] or ''}"
            name = safe_value(row["name"]) or row["name"]
            lines.append(f"- `{row['id']}` {name}（{display_label('item_category', row['category'])}）{quantity}")
    else:
        lines.append("- 无")

    lines.extend(["", "### 活跃进度钟"])
    if clocks:
        for row in clocks:
            filled = int(row["segments_filled"])
            total = int(row["segments_total"])
            bar = "■" * filled + "□" * max(total - filled, 0)
            name = safe_value(row["name"]) or row["name"]
            lines.append(f"- {name}：{bar} {filled}/{total}（{display_label('visibility', row['visibility'])}）")
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "### 可行动",
            "| # | 行动 | 说明 |",
            "|---|------|------|",
        ]
    )
    for index, item in enumerate(scene_affordances(conn, location_id, present, view=view), start=1):
        lines.append(f"| {index} | {item[0]} | {item[1]} |")
    text = "\n".join(str(line) for line in lines)
    return str(redact_player_hidden_material(conn, text, drop_empty=False)) if should_redact else text


def current_location_display(conn: sqlite3.Connection, meta: dict[str, str], view: str) -> str:
    location_id = meta.get("current_location_id", "")
    if not location_id:
        return "未知"
    entity_visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    location = conn.execute(
        f"""
        select e.id, e.name
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {entity_visibility_clause}
          {subtype_visibility_clause}
        """,
        (location_id,),
    ).fetchone()
    if location:
        return f"`{location['id']}` {location['name']}"
    if view == PLAYER_VIEW:
        return "当前地点不可见或不存在"
    return f"当前地点不可见或不存在：`{location_id}`"


def scene_affordances(
    conn: sqlite3.Connection,
    location_id: str,
    present: list[sqlite3.Row],
    *,
    view: str = PLAYER_VIEW,
) -> list[tuple[str, str]]:
    ensure_visibility_sql_functions(conn)
    entity_visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    actions: list[tuple[str, str]] = [
        ("查看周围细节", "查询当前地点资源和风险"),
        ("盘点库存", "低风险日常行动，不制造新资源"),
    ]
    player_entity_id = get_player_entity_id(conn)
    for row in present:
        if row["type"] == "character" and row["id"] != player_entity_id:
            actions.append((f"找 {row['name']} 谈谈", "社交预演；重要承诺或交易需保存 delta"))
            break
    routes = conn.execute(
        f"""
        select r.to_location_id as destination_id, e.name
        from routes r
        join entities e on e.id = r.to_location_id
        left join clocks c on c.entity_id = e.id
        where r.from_location_id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {entity_visibility_clause}
          {subtype_visibility_clause}
        union
        select r.from_location_id as destination_id, e.name
        from routes r
        join entities e on e.id = r.from_location_id
        left join clocks c on c.entity_id = e.id
        where r.to_location_id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {entity_visibility_clause}
          {subtype_visibility_clause}
        order by name
        limit 3
        """,
        (location_id, location_id),
    ).fetchall()
    for row in routes:
        actions.append((f"去 {row['name']}", f"旅行预演到 `{row['destination_id']}`"))
    projects = conn.execute(
        f"""
        select e.id, e.name
        from entities e
        where e.type = 'project' and {normalized_text_sql("e.status")} = 'active'
          {entity_visibility_clause}
        order by e.name
        limit 2
        """
    ).fetchall()
    for row in projects:
        actions.append((f"推进 {row['name']}", f"制作/日常预演 `{row['id']}`"))
    actions.append(("安排行动", "输入自然语言行动，先预演再确认保存"))
    return actions[:8]


def render_current_snapshot(campaign: Campaign, conn: sqlite3.Connection, *, view: str = PLAYER_VIEW) -> str:
    view = normalize_visibility_view(view)
    meta = get_meta(conn)
    scene = render_scene(conn, view=view)
    pc = conn.execute("select * from entities where id = ?", (get_player_entity_id(conn),)).fetchone()
    pc_details = parse_json(pc["details_json"], {}) if pc else {}
    pc_summary = pc["summary"] if pc else "未知"
    if view == PLAYER_VIEW:
        pc_summary = redact_player_hidden_material(conn, pc_summary, drop_empty=False) or "未知"
        pc_details = redact_player_hidden_material(conn, pc_details, drop_empty=False)
    lines = [
        "# 当前局面",
        "",
        f"Campaign：{campaign.name}",
        f"存档版本：{meta.get('schema_version', 'unknown')}",
        f"当前回合：{meta.get('current_turn_id', 'unknown')}",
        f"游戏时间：{format_time_brief(meta)}",
        f"天气：{format_weather_brief(meta)}",
        f"季节：{meta.get('year_label', '未登记')} / {meta.get('season_label', '未登记')} / {meta.get('month_label', '未登记')}",
        f"当前位置：{current_location_display(conn, meta, view)}",
        "",
        "## 玩家状态",
        f"- 摘要：{pc_summary}",
    ]
    for label, value in player_detail_items(pc_details, meta):
        lines.append(f"- {label}: {value}")
    lines.extend(["", scene])
    text = "\n".join(lines)
    return str(redact_player_hidden_material(conn, text, drop_empty=False)) if view == PLAYER_VIEW else text


def render_current_snapshot_json(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    view: str = PLAYER_VIEW,
) -> dict[str, Any]:
    ensure_visibility_sql_functions(conn)
    view = normalize_visibility_view(view)
    registry = get_default_card_registry()
    meta = get_meta(conn)
    current_location_id = meta.get("current_location_id", "")
    player_entity_id = get_player_entity_id(conn)
    pc = conn.execute("select * from entities where id = ?", (player_entity_id,)).fetchone()
    entity_visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    location = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {entity_visibility_clause}
          {subtype_visibility_clause}
        """,
        (current_location_id,),
    ).fetchone()
    location_row = None
    present = []
    if location:
        location_row = conn.execute("select * from locations where entity_id = ?", (current_location_id,)).fetchone()
        present = conn.execute(
            f"""
            select e.id, e.type, e.name, e.summary
            from entities e
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where e.location_id = ? and {normalized_text_sql("e.status")} = 'active'
              {entity_visibility_clause}
              {subtype_visibility_clause}
              {world_setting_visibility_clause}
            order by e.name
            limit 40
            """,
            (current_location_id,),
        ).fetchall()
        present = sorted(present, key=lambda row: entity_sort_key(row, registry))[:40]
    carried = conn.execute(
        f"""
        select e.id, e.type, e.name, e.summary, i.category, i.quantity, i.unit, i.equipped_slot
        from entities e
        join items i on i.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.owner_id = ? and {normalized_text_sql("e.status")} = 'active'
          {entity_visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        order by i.equipped_slot is null, i.equipped_slot, e.name
        limit 40
        """,
        (player_entity_id,),
    ).fetchall()
    clock_visibility_clause = clock_visibility_sql(view, "c")
    clocks = conn.execute(
        f"""
        select e.id, e.name, e.summary, c.clock_type, c.segments_filled, c.segments_total,
               c.visibility, c.trigger_when_full
        from clocks c
        join entities e on e.id = c.entity_id
        where {entity_not_archived_sql("e")}
          {clock_visibility_clause}
          {entity_visibility_clause}
        order by c.visibility, e.name
        """
    ).fetchall()
    snapshot_meta = dict(meta)
    should_redact = not can_read_hidden(view)
    if should_redact and not location:
        snapshot_meta["current_location_id"] = "当前地点不可见或不存在"
    if should_redact:
        snapshot_meta = redact_player_hidden_material(conn, snapshot_meta, drop_empty=False)
    def safe_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        value = dict(row)
        return redact_player_hidden_material(conn, value, drop_empty=False) if should_redact else value

    return {
        "campaign": {
            "id": campaign.campaign_id,
            "name": campaign.name,
            "engine_version": campaign.engine_version,
        },
        "visibility_view": view,
        "meta": snapshot_meta,
        "player": safe_row(pc),
        "location": {
            "entity": safe_row(location),
            "details": safe_row(location_row),
        },
        "present": [safe_row(row) for row in present],
        "carried": [safe_row(row) for row in carried],
        "active_clocks": [safe_row(row) for row in clocks],
    }


def entity_sort_key(entity: sqlite3.Row, registry: CardRegistry | None = None) -> tuple[int, str, str]:
    registry = registry or get_default_card_registry()
    return registry.sort_key(str(entity["type"]), str(entity["name"] or ""))


def write_current_snapshot(campaign: Campaign, conn: sqlite3.Connection, *, view: str = PLAYER_VIEW) -> Path:
    text = render_current_snapshot(campaign, conn, view=view)
    campaign.current_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(campaign.current_snapshot_path, text + "\n")
    return campaign.current_snapshot_path


def write_current_snapshot_json(campaign: Campaign, conn: sqlite3.Connection, *, view: str = PLAYER_VIEW) -> Path:
    data = render_current_snapshot_json(campaign, conn, view=view)
    campaign.current_snapshot_json_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(
        campaign.current_snapshot_json_path,
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return campaign.current_snapshot_json_path
