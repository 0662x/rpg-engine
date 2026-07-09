from __future__ import annotations

import json
import sqlite3
from typing import Any

from .base import ContentRuntime, ContentTypeSpec, MergePolicy
from .registry import ContentRegistry
from ..visibility import ENTITY_VISIBILITY_LABELS, PLAYER_VIEW, can_read_hidden, is_player_hidden_visibility


WORLD_SETTING_CATEGORIES = {
    "calendar",
    "weather",
    "power",
    "species_culture",
    "faction",
    "ecology",
    "economy",
    "technology",
    "truth",
}
WORLD_SETTING_VISIBILITIES = set(ENTITY_VISIBILITY_LABELS)


def validate_world_setting_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "name", "summary", "category"):
        if not isinstance(record.get(key), str) or not str(record.get(key, "")).strip():
            errors.append(f"{key}: required non-empty string")
    if record.get("id") and not str(record["id"]).startswith("world:"):
        errors.append("id: world setting id must start with world:")
    if record.get("category") and record["category"] not in WORLD_SETTING_CATEGORIES:
        errors.append(f"category: unsupported value {record['category']}")
    visibility = record.get("visibility", "known")
    if visibility not in WORLD_SETTING_VISIBILITIES:
        errors.append(f"visibility: unsupported value {visibility}")
    if not isinstance(record.get("content", {}), dict):
        errors.append("content: must be object")
    if not isinstance(record.get("applies_when", {}), dict):
        errors.append("applies_when: must be object")
    for key in ("linked_rules", "linked_clocks", "linked_entities", "aliases"):
        value = record.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"{key}: must be an array of non-empty strings")
    priority = record.get("priority", 50)
    if not isinstance(priority, int) or isinstance(priority, bool):
        errors.append("priority: must be integer")
    return errors


def upsert_world_setting(runtime: ContentRuntime, record: dict[str, Any]) -> None:
    from ..db import json_text, upsert_entity

    setting_id = str(record["id"])
    visibility = str(record.get("visibility", "known"))
    content = record.get("content", {})
    linked_rules = record.get("linked_rules", [])
    linked_clocks = record.get("linked_clocks", [])
    linked_entities = record.get("linked_entities", [])
    applies_when = record.get("applies_when", {})
    details = {
        "category": record.get("category", "general"),
        "scope": record.get("scope", "world"),
        "priority": int(record.get("priority", 50)),
        "linked_rules": linked_rules,
        "linked_clocks": linked_clocks,
        "linked_entities": linked_entities,
        "applies_when": applies_when,
        "source": record.get("source", "content"),
    }
    if not is_player_hidden_visibility(visibility):
        details["content"] = content
    entity = {
        "id": setting_id,
        "type": "world_setting",
        "name": record.get("name", setting_id),
        "status": record.get("status", "active"),
        "visibility": visibility,
        "summary": record.get("summary", ""),
        "details": details,
        "aliases": record.get("aliases", []),
        "updated_turn_id": record.get("updated_turn_id", runtime.turn_id),
    }
    upsert_entity(runtime.conn, entity)
    runtime.conn.execute(
        """
        insert into world_settings
        (entity_id, category, scope, visibility, priority, summary, content_json,
         linked_rules_json, linked_clocks_json, linked_entities_json, applies_when_json, source)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(entity_id) do update set
          category=excluded.category,
          scope=excluded.scope,
          visibility=excluded.visibility,
          priority=excluded.priority,
          summary=excluded.summary,
          content_json=excluded.content_json,
          linked_rules_json=excluded.linked_rules_json,
          linked_clocks_json=excluded.linked_clocks_json,
          linked_entities_json=excluded.linked_entities_json,
          applies_when_json=excluded.applies_when_json,
          source=excluded.source
        """,
        (
            setting_id,
            str(record.get("category", "general")),
            str(record.get("scope", "world")),
            visibility,
            int(record.get("priority", 50)),
            str(record.get("summary", "")),
            json_text(content, "{}"),
            json_text(linked_rules, "[]"),
            json_text(linked_clocks, "[]"),
            json_text(linked_entities, "[]"),
            json_text(applies_when, "{}"),
            str(record.get("source", "content")),
        ),
    )


def render_world_setting_entity(conn: sqlite3.Connection, entity: sqlite3.Row, *, view: str = PLAYER_VIEW) -> str:
    from ..render import bullet_list, display_key, display_label, format_value, parse_json, render_generic_entity

    if str(entity["type"]) != "world_setting":
        return render_generic_entity(entity)
    if not table_exists(conn, "world_settings"):
        return _player_hidden_world_setting_placeholder() if not can_read_hidden(view) else render_generic_entity(entity)
    row = conn.execute("select * from world_settings where entity_id = ?", (entity["id"],)).fetchone()
    if not row:
        return _player_hidden_world_setting_placeholder() if not can_read_hidden(view) else render_generic_entity(entity)
    if (
        not can_read_hidden(view)
        and is_player_hidden_visibility(str(row["visibility"]))
        and not is_player_hidden_visibility(str(entity["visibility"]))
    ):
        return _player_hidden_world_setting_placeholder()
    content = parse_json(row["content_json"], {})
    linked_rules = parse_json(row["linked_rules_json"], [])
    linked_clocks = parse_json(row["linked_clocks_json"], [])
    linked_entities = parse_json(row["linked_entities_json"], [])
    applies_when = parse_json(row["applies_when_json"], {})
    lines = [
        f"## 大世界设定：{entity['name']}",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| ID | `{entity['id']}` |",
        f"| 分类 | {display_label('rule_category', row['category'])} |",
        f"| 范围 | {display_label('scope', row['scope'])} |",
        f"| 可见性 | {display_label('visibility', row['visibility'])} |",
        f"| 优先级 | {row['priority']} |",
        f"| 来源 | {row['source']} |",
        "",
        "### 摘要",
        row["summary"] or entity["summary"] or "无",
    ]
    if linked_rules:
        lines.extend(["", "### 关联规则", bullet_list([f"`{item}`" for item in linked_rules])])
    if linked_clocks:
        lines.extend(["", "### 关联进度钟", bullet_list([f"`{item}`" for item in linked_clocks])])
    if linked_entities:
        lines.extend(["", "### 关联实体", bullet_list([f"`{item}`" for item in linked_entities])])
    if applies_when:
        lines.extend(["", "### 适用条件"])
        for key, value in applies_when.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    if content:
        lines.extend(["", "### 内容"])
        for key, value in content.items():
            lines.append(f"- {display_key(key)}: {format_value(value)}")
    return "\n".join(lines)


def _player_hidden_world_setting_placeholder() -> str:
    return "\n".join(
        [
            "## 大世界设定",
            "",
            "### 摘要",
            "此设定摘要对玩家不可见。",
            "",
            "### 内容",
            "此设定内容对玩家不可见。",
        ]
    )


def append_world_setting_card_sections(conn: sqlite3.Connection, lines: list[str], entity: sqlite3.Row) -> None:
    from ..cards import append_mapping, append_sequence
    from ..render import display_label, parse_json

    row = conn.execute("select * from world_settings where entity_id = ?", (entity["id"],)).fetchone()
    if not row:
        return
    if is_player_hidden_visibility(str(row["visibility"])) and not is_player_hidden_visibility(str(entity["visibility"])):
        return
    lines.extend(
        [
            "",
            "## 大世界设定",
            "| 字段 | 值 |",
            "|------|----|",
            f"| 分类 | {display_label('rule_category', row['category'])} |",
            f"| 范围 | {display_label('scope', row['scope'])} |",
            f"| 可见性 | {display_label('visibility', row['visibility'])} |",
            f"| 优先级 | {row['priority']} |",
            f"| 来源 | {row['source']} |",
        ]
    )
    append_sequence(lines, "## 关联规则", parse_json(row["linked_rules_json"], []))
    append_sequence(lines, "## 关联进度钟", parse_json(row["linked_clocks_json"], []))
    append_sequence(lines, "## 关联实体", parse_json(row["linked_entities_json"], []))
    append_mapping(lines, "## 适用条件", parse_json(row["applies_when_json"], {}), exclude=set())
    append_mapping(lines, "## 内容", parse_json(row["content_json"], {}), exclude=set())


def validate_world_settings_database(conn: sqlite3.Connection) -> list[str]:
    if not table_exists(conn, "world_settings"):
        return []
    errors: list[str] = []
    rows = conn.execute(
        """
        select ws.*, e.name
        from world_settings ws
        left join entities e on e.id = ws.entity_id
        """
    ).fetchall()
    for row in rows:
        if row["name"] is None:
            errors.append(f"world setting {row['entity_id']} has no matching entity")
        if row["category"] not in WORLD_SETTING_CATEGORIES:
            errors.append(f"world setting {row['entity_id']} has unsupported category {row['category']}")
        if row["visibility"] not in WORLD_SETTING_VISIBILITIES:
            errors.append(f"world setting {row['entity_id']} has unsupported visibility {row['visibility']}")
        for field, target_table in [
            ("linked_rules_json", "rules"),
            ("linked_clocks_json", "clocks"),
            ("linked_entities_json", "entities"),
        ]:
            for target_id in parse_json_list(row[field]):
                if not content_ref_exists(conn, target_table, str(target_id)):
                    errors.append(f"world setting {row['entity_id']} links missing {target_table} row {target_id}")
        if not isinstance(parse_json_value(row["content_json"], {}), dict):
            errors.append(f"world setting {row['entity_id']} content_json must be object")
        if not isinstance(parse_json_value(row["applies_when_json"], {}), dict):
            errors.append(f"world setting {row['entity_id']} applies_when_json must be object")
    return errors


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
    return bool(row)


def content_ref_exists(conn: sqlite3.Connection, table: str, entity_id: str) -> bool:
    query = "select 1 from entities where id = ?"
    if table != "entities":
        query = f"select 1 from {table} where entity_id = ?"
    row = conn.execute(query, (entity_id,)).fetchone()
    return bool(row)


def parse_json_value(text: str, default: object) -> object:
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


def parse_json_list(text: str) -> list[object]:
    value = parse_json_value(text, [])
    return value if isinstance(value, list) else []


def register_world_setting(registry: ContentRegistry) -> None:
    registry.register(
        ContentTypeSpec(
            name="world_setting",
            campaign_key="world_settings",
            yaml_key="world_settings",
            delta_key="upsert_world_settings",
            entity_type="world_setting",
            table="world_settings",
            count_key="world_settings",
            payload_key="world_settings",
            sync_safe=True,
            upsert=upsert_world_setting,
            validate_record=validate_world_setting_record,
            validate_database=validate_world_settings_database,
            merge_policy=MergePolicy(
                author_owned={"name", "summary", "category", "scope", "visibility", "priority", "content", "applies_when", "source"},
                mergeable={"aliases", "linked_rules", "linked_clocks", "linked_entities"},
                conflict_only={"id", "status"},
            ),
        )
    )
