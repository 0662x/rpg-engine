from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..db import get_meta, get_player_entity_id
from ..player_resources import player_detail_items
from ..render import parse_json
from ..time_weather import format_time_brief, format_weather_brief
from .resolution import EntityHit, as_list, is_direct_hit


TYPE_LABELS = {
    "character": "人物",
    "equipment": "装备",
    "item": "物品",
    "location": "地点",
    "material": "材料",
    "plant": "植物",
    "species": "物种",
    "faction": "势力",
    "threat": "威胁",
    "rule": "规则",
    "clock": "进度钟",
    "project": "项目",
    "recipe": "配方",
    "reference": "资料",
    "world_setting": "大世界设定",
    "crop_plot": "田畦",
}


DETAIL_LABELS = {
    "action_guidance": "行动要点",
    "risk_profile": "风险",
    "safety_protocol": "安全协议",
    "adjudication_rules": "结算规则",
    "cooldown_profile": "冷却/收获",
    "trap_profile": "陷阱档案",
    "recipe_profile": "配方档案",
    "resource_profile": "资源档案",
    "evidence_profile": "证据档案",
    "world_expansion_role": "世界外扩作用",
    "unknowns": "未确认",
    "linked_entities": "相关实体",
    "source": "来源",
}


def render_player_state(conn: sqlite3.Connection) -> str:
    meta = get_meta(conn)
    pc = conn.execute("select * from entities where id = ?", (get_player_entity_id(conn),)).fetchone()
    details = parse_json(pc["details_json"], {}) if pc else {}
    lines = [
        "### 玩家状态",
        "",
        "| 项目 | 当前 |",
        "|------|------|",
        f"| 时间 | {format_time_brief(meta)} |",
        f"| 天气 | {format_weather_brief(meta)} |",
        f"| 位置 | `{meta.get('current_location_id', 'unknown')}` |",
    ]
    if pc:
        lines.append(f"| 主角 | `{pc['id']}` {pc['name']} |")
        lines.append(f"| 摘要 | {pc['summary'] or '无'} |")
    for label, value in player_detail_items(details, meta):
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def render_relevant_entities(state: Any) -> str:
    lines = ["### 相关实体", ""]
    for hit in state.entity_hits[:12]:
        detail = entity_context_level(state, hit)
        lines.extend(render_entity_hit(state.conn, hit, detail=detail))
        lines.append("")
    return "\n".join(lines).rstrip()


def entity_context_level(state: Any, hit: EntityHit) -> str:
    if not (is_direct_hit(hit) and hit.depth == 0 and hit.priority >= 80):
        return "compact"
    if state.mode == "query" and state.submode == "entity":
        return "full"
    return "standard"


def render_entity_hit(conn: sqlite3.Connection, hit: EntityHit, *, detail: str) -> list[str]:
    if detail in {"standard", "full"}:
        return render_context_entity(conn, hit, level=detail)
    location = f"；位置：{hit.location_id}" if hit.location_id else ""
    owner = f"；所有者：{hit.owner_id}" if hit.owner_id else ""
    return [
        f"- `{hit.id}` {hit.name}（{TYPE_LABELS.get(hit.type, hit.type)}；状态：{hit.status}{location}{owner}）",
        f"  - 原因：{hit.reason}",
        f"  - 摘要：{trim_inline(hit.summary or '无', 120)}",
    ]


def render_context_entity(conn: sqlite3.Connection, hit: EntityHit, *, level: str) -> list[str]:
    row = conn.execute("select * from entities where id = ?", (hit.id,)).fetchone()
    if not row:
        return [
            f"#### `{hit.id}` {hit.name}",
            "",
            f"- 加载原因：{hit.reason}",
            "- 上下文视图：missing",
            "- 实体已不在当前数据库中。",
        ]

    details = parse_json(row["details_json"], {})
    lines = [
        f"#### `{row['id']}` {row['name']}",
        "",
        f"- 加载原因：{hit.reason}",
        f"- 上下文视图：{level}",
        "",
    ]
    if row["type"] in {"item", "equipment"}:
        append_context_item(conn, lines, row, details, level)
    elif row["type"] == "location":
        append_context_location(conn, lines, row, details, level)
    elif row["type"] == "character":
        append_context_character(conn, lines, row, details, level)
    elif row["type"] == "clock":
        append_context_clock(conn, lines, row)
    elif row["type"] == "rule":
        append_context_rule(conn, lines, row)
    else:
        append_context_generic(lines, row, details, level)
    return lines


def append_context_item(
    conn: sqlite3.Connection,
    lines: list[str],
    row: sqlite3.Row,
    details: dict[str, Any],
    level: str,
) -> None:
    item = conn.execute("select * from items where entity_id = ?", (row["id"],)).fetchone()
    properties = parse_json(item["properties_json"], {}) if item else {}
    append_context_table(
        lines,
        [
            ("ID", f"`{row['id']}`"),
            ("类型", TYPE_LABELS.get(row["type"], row["type"])),
            ("分类", item["category"] if item else "未知"),
            ("状态", row["status"]),
            ("位置", row["location_id"] or row["owner_id"] or "未知"),
            ("数量", format_context_quantity(item)),
            ("品质", item["quality"] if item and item["quality"] else "未知"),
            ("装备槽", item["equipped_slot"] if item and item["equipped_slot"] else "无"),
        ],
    )
    append_summary(lines, row["summary"])
    append_context_item_profiles(lines, properties, level=level)
    append_context_details(lines, details, level=level, entity_type=row["type"])


def append_context_location(
    conn: sqlite3.Connection,
    lines: list[str],
    row: sqlite3.Row,
    details: dict[str, Any],
    level: str,
) -> None:
    location = conn.execute("select * from locations where entity_id = ?", (row["id"],)).fetchone()
    resources = parse_json(location["resources_json"], []) if location else []
    exits = parse_json(location["exits_json"], []) if location else []
    append_context_table(
        lines,
        [
            ("ID", f"`{row['id']}`"),
            ("类型", TYPE_LABELS.get(row["type"], row["type"])),
            ("状态", row["status"]),
            ("生态", location["biome"] if location and location["biome"] else "未知"),
            ("安全等级", location["safety_level"] if location and location["safety_level"] else "未知"),
            (
                "距家耗时",
                f"{location['travel_minutes_from_home']}分钟"
                if location and location["travel_minutes_from_home"] is not None
                else "未知",
            ),
        ],
    )
    summary = location["description_short"] if location and location["description_short"] else row["summary"]
    append_summary(lines, summary)
    append_sequence_section(lines, "### 已知资源", resources, limit=6 if level == "full" else 4)
    append_sequence_section(lines, "### 出口/路线", exits, limit=5 if level == "full" else 3)
    append_context_details(lines, details, level=level, entity_type=row["type"])


def append_context_character(
    conn: sqlite3.Connection,
    lines: list[str],
    row: sqlite3.Row,
    details: dict[str, Any],
    level: str,
) -> None:
    character = conn.execute("select * from characters where entity_id = ?", (row["id"],)).fetchone()
    append_context_table(
        lines,
        [
            ("ID", f"`{row['id']}`"),
            ("类型", TYPE_LABELS.get(row["type"], row["type"])),
            ("状态", row["status"]),
            ("位置", row["location_id"] or "未知"),
            ("种族", character["species_id"] if character and character["species_id"] else "未知"),
            ("角色", character["role"] if character and character["role"] else "未知"),
            ("态度", character["attitude"] if character and character["attitude"] else "未知"),
            ("信任", str(character["trust"]) if character else "未知"),
            ("健康", character["health_state"] if character and character["health_state"] else "未知"),
        ],
    )
    append_summary(lines, row["summary"])
    for key, title in [
        ("known_abilities", "### 已知能力"),
        ("commitments", "### 当前承诺"),
        ("unknowns", "### 未确认信息"),
    ]:
        append_sequence_section(lines, title, details.get(key), limit=5 if level == "full" else 3)
    append_context_details(lines, details, level=level, entity_type=row["type"])


def append_context_clock(conn: sqlite3.Connection, lines: list[str], row: sqlite3.Row) -> None:
    clock = conn.execute("select * from clocks where entity_id = ?", (row["id"],)).fetchone()
    if not clock:
        append_context_generic(lines, row, parse_json(row["details_json"], {}), "standard")
        return
    filled = int(clock["segments_filled"])
    total = int(clock["segments_total"])
    bar = "■" * filled + "□" * max(total - filled, 0)
    append_context_table(
        lines,
        [
            ("ID", f"`{row['id']}`"),
            ("类型", clock["clock_type"]),
            ("状态", row["status"]),
            ("进度", f"{bar} {filled}/{total}"),
            ("可见性", clock["visibility"]),
            ("满格触发", clock["trigger_when_full"]),
        ],
    )
    append_summary(lines, row["summary"])


def append_context_rule(conn: sqlite3.Connection, lines: list[str], row: sqlite3.Row) -> None:
    rule = conn.execute("select * from rules where entity_id = ?", (row["id"],)).fetchone()
    if not rule:
        append_context_generic(lines, row, parse_json(row["details_json"], {}), "standard")
        return
    append_context_table(
        lines,
        [
            ("ID", f"`{row['id']}`"),
            ("分类", rule["category"]),
            ("范围", rule["scope"]),
            ("锁定", "是" if rule["locked"] else "否"),
        ],
    )
    append_summary(lines, rule["statement"])


def append_context_generic(
    lines: list[str],
    row: sqlite3.Row,
    details: dict[str, Any],
    level: str,
) -> None:
    append_context_table(
        lines,
        [
            ("ID", f"`{row['id']}`"),
            ("类型", TYPE_LABELS.get(row["type"], row["type"])),
            ("状态", row["status"]),
            ("位置", row["location_id"] or row["owner_id"] or "未知"),
        ],
    )
    append_summary(lines, row["summary"])
    append_context_details(lines, details, level=level, entity_type=row["type"])


def append_context_item_profiles(lines: list[str], properties: dict[str, Any], *, level: str) -> None:
    combat = properties.get("combat_profile")
    if isinstance(combat, dict):
        lines.extend(["", "### 战斗档案"])
        append_context_table(
            lines,
            [
                ("定位", combat.get("role")),
                ("待机状态", combat.get("ready_state")),
                ("声音/暴露", combat.get("noise")),
                ("潮湿/雨天", combat.get("wet_weather")),
            ],
        )
        append_range_bands_context(lines, combat.get("range_bands"), limit=5 if level == "full" else 3)
        append_ammo_table_context(lines, combat.get("compatible_ammo"), limit=8 if level == "full" else 5)
        append_sequence_section(lines, "### 使用限制", combat.get("constraints"), limit=5 if level == "full" else 3)
        append_sequence_section(lines, "### 风险", combat.get("risks"), limit=5 if level == "full" else 3)
        append_sequence_section(lines, "### 结算规则", combat.get("adjudication_rules"), limit=5 if level == "full" else 3)

    for profile_key, title, fields in [
        (
            "ammo_profile",
            "### 弹药档案",
            [
                ("兼容武器", "compatible_weapon_id"),
                ("效果类型", "effect_type"),
                ("主要效果", "primary_effect"),
                ("适用场景", "best_use"),
                ("可靠性", "reliability"),
            ],
        ),
        (
            "melee_profile",
            "### 近战档案",
            [
                ("定位", "role"),
                ("攻击距离", "reach"),
                ("握持", "grip"),
                ("伤害方式", "damage_mode"),
                ("适用场景", "best_use"),
            ],
        ),
        (
            "defense_profile",
            "### 防护档案",
            [
                ("定位", "role"),
                ("覆盖", "coverage"),
                ("防护", "protection"),
                ("机动影响", "mobility"),
                ("弱点", "weak_points"),
            ],
        ),
        (
            "carry_profile",
            "### 携行档案",
            [
                ("定位", "role"),
                ("容量", "capacity"),
                ("携行状态", "carried_state"),
                ("取用速度", "access"),
                ("机动影响", "mobility"),
            ],
        ),
    ]:
        profile = properties.get(profile_key)
        if not isinstance(profile, dict):
            continue
        lines.extend(["", title])
        append_context_table(lines, [(label, profile.get(key)) for label, key in fields])
        append_sequence_section(lines, "### 限制/规则", profile.get("limitations") or profile.get("constraints") or profile.get("adjudication_rules"), limit=4)
        append_sequence_section(lines, "### 风险", profile.get("risks"), limit=4)


def append_context_details(lines: list[str], details: dict[str, Any], *, level: str, entity_type: str) -> None:
    if not details:
        return
    hidden_keys = {"known_abilities", "commitments", "unknowns"}
    preferred_keys = [
        "action_guidance",
        "risk_profile",
        "safety_protocol",
        "adjudication_rules",
        "cooldown_profile",
        "trap_profile",
        "recipe_profile",
        "resource_profile",
        "evidence_profile",
        "world_expansion_role",
        "unknowns",
        "linked_entities",
        "source",
    ]
    keys = [key for key in preferred_keys if key in details and key not in hidden_keys]
    if level == "full":
        keys.extend(key for key in details.keys() if key not in keys and key not in hidden_keys)
    keys = keys[:8 if level == "full" else 5]
    if not keys:
        return
    lines.extend(["", "### 结构化要点"])
    for key in keys:
        append_detail_entry(lines, key, details[key], level=level, entity_type=entity_type)


def append_detail_entry(lines: list[str], key: str, value: Any, *, level: str, entity_type: str) -> None:
    title = DETAIL_LABELS.get(key, key)
    if isinstance(value, dict):
        lines.append(f"- {title}:")
        limit = 6 if level == "full" else 4
        for subkey, subvalue in list(value.items())[:limit]:
            lines.append(f"  - {subkey}: {format_context_value(subvalue, max_chars=150, list_limit=3)}")
        if len(value) > limit:
            lines.append(f"  - ...: 另有 {len(value) - limit} 项")
        return
    if isinstance(value, list):
        lines.append(f"- {title}:")
        limit = 5 if level == "full" else 3
        for item in value[:limit]:
            lines.append(f"  - {format_context_value(item, max_chars=150, list_limit=3)}")
        if len(value) > limit:
            lines.append(f"  - ... 另有 {len(value) - limit} 项")
        return
    lines.append(f"- {title}: {format_context_value(value, max_chars=180 if level == 'full' else 130)}")


def render_ambiguous_candidates(state: Any) -> str:
    lines = [
        "### 歧义候选",
        "",
        "玩家输入包含指代词；下列候选会导致不同结算，默认不硬猜。",
        "",
        "| # | ID | 类型 | 名称 | 摘要 |",
        "|---|----|------|------|------|",
    ]
    for index, hit in enumerate(state.ambiguous_hits, start=1):
        lines.append(
            f"| {index} | `{hit.id}` | {TYPE_LABELS.get(hit.type, hit.type)} | {hit.name} | {trim_inline(hit.summary, 60)} |"
        )
    return "\n".join(lines)


def append_summary(lines: list[str], summary: str | None) -> None:
    if summary:
        lines.extend(["", "### 摘要", trim_inline(summary, 220)])


def append_context_table(lines: list[str], rows: list[tuple[str, Any]]) -> None:
    visible = [(label, value) for label, value in rows if value not in (None, "", [], {})]
    if not visible:
        return
    lines.extend(["| 字段 | 值 |", "|------|----|"])
    for label, value in visible:
        lines.append(f"| {escape_table_cell(label)} | {escape_table_cell(format_context_value(value, max_chars=180))} |")


def append_sequence_section(lines: list[str], title: str, value: Any, *, limit: int) -> None:
    items = as_list(value)
    if not items:
        return
    lines.extend(["", title])
    for item in items[:limit]:
        lines.append(f"- {format_context_value(item, max_chars=160, list_limit=3)}")
    if len(items) > limit:
        lines.append(f"- ... 另有 {len(items) - limit} 项")


def append_range_bands_context(lines: list[str], value: Any, *, limit: int) -> None:
    if not isinstance(value, list) or not value:
        return
    lines.extend(["", "### 射程分段", "| 分段 | 距离 | 用法 | 风险 |", "|------|------|------|------|"])
    for item in value[:limit]:
        if isinstance(item, dict):
            lines.append(
                f"| {escape_table_cell(item.get('band', ''))} | {escape_table_cell(item.get('distance', ''))} | "
                f"{escape_table_cell(trim_inline(str(item.get('use', '')), 80))} | "
                f"{escape_table_cell(trim_inline(str(item.get('risk', '')), 80))} |"
            )
    if len(value) > limit:
        lines.append(f"| ... | ... | 另有 {len(value) - limit} 段 | ... |")


def append_ammo_table_context(lines: list[str], value: Any, *, limit: int) -> None:
    if not isinstance(value, list) or not value:
        return
    lines.extend(["", "### 兼容弹药", "| 弹药 | 用途 | 备注 |", "|------|------|------|"])
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        entity_id = item.get("id")
        name = item.get("name") or entity_id or ""
        label = f"`{entity_id}` {name}" if entity_id and name != entity_id else str(name)
        lines.append(
            f"| {escape_table_cell(label)} | {escape_table_cell(item.get('role', ''))} | "
            f"{escape_table_cell(trim_inline(str(item.get('notes', '')), 90))} |"
        )
    if len(value) > limit:
        lines.append(f"| ... | ... | 另有 {len(value) - limit} 项 |")


def format_context_quantity(item: sqlite3.Row | None) -> str:
    if not item or item["quantity"] is None:
        return "不适用"
    quantity = item["quantity"]
    if float(quantity).is_integer():
        quantity = int(quantity)
    return f"{quantity}{item['unit'] or ''}"


def format_context_value(value: Any, *, max_chars: int = 140, list_limit: int = 4) -> str:
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        if not value:
            return "无"
        parts = [format_context_value(item, max_chars=max_chars, list_limit=2) for item in value[:list_limit]]
        if len(value) > list_limit:
            parts.append(f"另有 {len(value) - list_limit} 项")
        return trim_inline("；".join(parts), max_chars)
    if isinstance(value, dict):
        if not value:
            return "无"
        parts: list[str] = []
        for key, item in list(value.items())[:list_limit]:
            parts.append(f"{key}={format_context_value(item, max_chars=80, list_limit=2)}")
        if len(value) > list_limit:
            parts.append(f"另有 {len(value) - list_limit} 项")
        return trim_inline("；".join(parts), max_chars)
    return trim_inline(str(value), max_chars)


def escape_table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def trim_inline(text: str | None, limit_chars: int) -> str:
    raw = str(text or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw if len(raw) <= limit_chars else raw[: max(0, limit_chars - 1)] + "…"
