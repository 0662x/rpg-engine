from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .campaign import Campaign
from .palette import find_palette_candidate, palette_entry_to_entity
from .render import parse_json
from .visibility import ensure_visibility_sql_functions, entity_not_archived_sql


@dataclass(frozen=True)
class ContentAuditFinding:
    severity: str
    entity_id: str
    title: str


def make_content_delta(
    *,
    kind: str,
    entity_id: str,
    name: str,
    summary: str,
    location_id: str | None = None,
    rarity: str | None = None,
    uses: list[str] | None = None,
    risks: list[str] | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    aliases = aliases or [name]
    uses = uses or []
    risks = risks or ["待确认风险"]
    entity: dict[str, Any] = {
        "id": entity_id,
        "type": kind_to_entity_type(kind),
        "name": name,
        "status": "active",
        "visibility": "known",
        "summary": summary,
        "aliases": aliases,
        "details": base_details(kind, location_id=location_id, rarity=rarity, uses=uses, risks=risks),
    }
    if location_id:
        entity["location_id"] = location_id
    if kind == "location":
        entity["location"] = {
            "parent_id": location_id,
            "biome": "unknown",
            "safety_level": "unknown",
            "travel_minutes_from_home": None,
            "description_short": summary,
            "exits": [],
            "resources": [],
        }
        entity.pop("location_id", None)
    return {
        "title": f"新增{kind}：{name}",
        "description": f"内容生产流水线生成 {kind} 草案：{name}。应用前需人工复核。",
        "intent": "content_maintenance",
        "event_type": "content_delta",
        "source": "content_factory",
        "upsert_entities": [entity],
    }


def make_content_delta_from_palette(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    palette_id: str,
    visibility: str = "hinted",
    location_id: str | None = None,
) -> dict[str, Any]:
    candidate = find_palette_candidate(campaign, conn, palette_id, location_query=location_id, intent=None)
    if candidate is None:
        raise ValueError(f"palette not found: {palette_id}")
    entry = candidate["entry"]
    entity = palette_entry_to_entity(entry, visibility=visibility, location_id=location_id)
    high_impact = entity["type"] in {"location", "faction", "faction_state", "species", "world_setting"}
    return {
        "title": f"候选素材转内容：{entry.get('name') or palette_id}",
        "description": (
            f"从 palette 候选 `{palette_id}` 生成内容维护草案。"
            "应用前需人工复核；这不是自动确认的世界事实。"
        ),
        "intent": "content_maintenance",
        "event_type": "content_delta",
        "source": "content_factory_from_palette",
        "meta": {
            "palette_id": palette_id,
            "palette_status": str(candidate["status"]),
            "review_required": True,
            "high_impact": high_impact,
        },
        "upsert_entities": [entity],
    }


def kind_to_entity_type(kind: str) -> str:
    return {
        "material": "material",
        "location": "location",
        "species": "species",
        "faction": "faction",
        "recipe": "recipe",
        "project": "project",
        "npc": "character",
    }.get(kind, kind)


def base_details(
    kind: str,
    *,
    location_id: str | None,
    rarity: str | None,
    uses: list[str],
    risks: list[str],
) -> dict[str, Any]:
    if kind == "material":
        return {
            "resource_profile": {
                "location": location_id or "待定",
                "rarity": rarity or "common",
                "uses": uses,
                "risks": risks,
                "discovery": {
                    "clue_text": "待补线索。",
                    "confirm_methods": ["观察", "采样", "小量测试"],
                },
                "save_as": {"type": "material", "category": "unknown"},
            }
        }
    if kind == "species":
        return {
            "profile": {
                "rarity": rarity or "common",
                "habitat": location_id or "待定",
                "behavior": ["待补行为"],
                "yields": uses,
                "risks": risks,
                "discovery": {"clue_text": "待补线索。", "confirm_methods": ["观察", "接触痕迹", "询问"]},
            }
        }
    if kind == "faction":
        return {
            "profile": {
                "stance": "待定",
                "goals": uses,
                "risks": risks,
                "contact_protocol": {"safe_openers": ["低压接触"], "unsafe_openers": ["武力威胁"]},
            }
        }
    if kind == "location":
        return {
            "known_features": uses,
            "risks": risks,
            "discovery": {"clue_text": "待补入口线索。", "confirm_methods": ["侦查", "路线确认"]},
        }
    return {"uses": uses, "risks": risks, "discovery": {"clue_text": "待补线索。", "confirm_methods": ["确认"]}}


def write_content_delta(delta: dict[str, Any], output: str | Path | None) -> str:
    text = json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        return str(path)
    return text


def audit_content_quality(conn: sqlite3.Connection) -> list[ContentAuditFinding]:
    findings: list[ContentAuditFinding] = []
    ensure_visibility_sql_functions(conn)
    rows = conn.execute(
        f"""
        select id, type, name, summary, details_json
        from entities
        where {entity_not_archived_sql("entities")}
          and type in ('material', 'species', 'faction', 'location', 'recipe', 'project')
        order by type, id
        """
    ).fetchall()
    for row in rows:
        details = parse_json(row["details_json"], {})
        aliases = conn.execute("select count(*) from aliases where entity_id = ?", (row["id"],)).fetchone()[0]
        if aliases == 0:
            findings.append(ContentAuditFinding("warn", row["id"], f"{row['name']} 缺少别名"))
        if not row["summary"] or len(row["summary"]) < 8:
            findings.append(ContentAuditFinding("warn", row["id"], f"{row['name']} 摘要过短"))
        if row["type"] in {"material", "species", "faction", "location"}:
            if not has_any_key(details, ["risks", "risk", "contact_protocol", "resource_profile", "profile"]):
                findings.append(ContentAuditFinding("info", row["id"], f"{row['name']} 缺少风险/档案字段"))
            if not contains_key_recursive(details, "discovery") and row["type"] in {"material", "species", "location"}:
                findings.append(ContentAuditFinding("info", row["id"], f"{row['name']} 缺少发现/确认方式"))
            if not has_uses(details) and row["type"] in {"material", "species", "project", "recipe"}:
                findings.append(ContentAuditFinding("info", row["id"], f"{row['name']} 缺少用途/产出/下一步"))
    return findings


def render_content_quality(findings: list[ContentAuditFinding]) -> str:
    lines = ["# Content Quality Audit", "", f"- findings: {len(findings)}", ""]
    lines.extend(["| Severity | Entity | Finding |", "|----------|--------|---------|"])
    for finding in findings:
        lines.append(f"| {finding.severity} | `{finding.entity_id}` | {finding.title} |")
    if not findings:
        lines.append("| OK |  | 无 |")
    return "\n".join(lines) + "\n"


def has_any_key(value: dict[str, Any], keys: list[str]) -> bool:
    return any(key in value for key in keys)


def contains_key_recursive(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key_recursive(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key_recursive(item, key) for item in value)
    return False


def has_uses(value: Any) -> bool:
    text = json.dumps(value, ensure_ascii=False)
    return bool(re.search(r"(uses|用途|yields|output|next_steps|产出|下一步)", text))


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，;；]", value) if item.strip()]
