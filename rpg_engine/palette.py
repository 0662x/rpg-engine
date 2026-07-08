from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from .campaign import Campaign, load_yaml_file
from .db import get_meta, resolve_entity
from .redaction import redact_hidden_entity_refs
from .visibility import clock_visibility_sql, ensure_visibility_sql_functions, entity_not_archived_sql, entity_visibility_sql


KIND_KEYS = {
    "biome": "biomes",
    "material": "materials",
    "species": "species",
    "faction": "factions",
    "encounter": "encounters",
    "location": "locations",
}

PALETTE_DISCOVERY_MODES = {"direct", "confirm_required", "clue_only"}
PALETTE_INTENTS = {"gather", "explore", "craft", "social", "travel", "combat", "rest", "routine", "random_table"}

RARITY_RANK = {
    "common": 0,
    "known": 0,
    "uncommon": 1,
    "rare": 2,
    "very_rare": 3,
    "legendary": 4,
    "hidden": 5,
}

STATUS_LABELS = {
    "available": "可投放",
    "confirm_required": "需确认",
    "clue_only": "仅线索",
    "locked": "锁定",
    "out_of_context": "不适用",
}


def load_palette_entries(campaign: Campaign, kind: str | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    files = palette_files(campaign)
    requested = None if kind in {None, "all"} else kind
    for path in files:
        data = load_yaml_file(path)
        for entry_kind, key in KIND_KEYS.items():
            if requested and entry_kind != requested:
                continue
            for raw_entry in data.get(key, []) or []:
                entry = dict(raw_entry)
                entry["_kind"] = entry_kind
                entry["_source"] = campaign.display_path(path)
                entries.append(entry)
    return entries


def palette_files(campaign: Campaign) -> list[Path]:
    configured = campaign.content_files("palettes")
    if configured:
        return configured
    palette_dir = campaign.root / "content" / "palettes"
    if not palette_dir.exists():
        return []
    try:
        palette_dir.resolve().relative_to(campaign.root.resolve())
    except ValueError:
        raise ValueError("campaign palette directory escapes campaign root: content/palettes")
    files: list[Path] = []
    for path in sorted(palette_dir.glob("*.yaml")):
        try:
            path.resolve().relative_to(campaign.root.resolve())
        except ValueError as exc:
            raise ValueError(f"campaign palette file escapes campaign root: {campaign.display_path(path)}") from exc
        files.append(path)
    return files


def suggest_palette_entries(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    kind: str = "all",
    location_query: str | None = None,
    intent: str | None = None,
    include_locked: bool = False,
    limit: int = 12,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context = palette_context(conn, location_query, intent)
    candidates: list[dict[str, Any]] = []
    for entry in load_palette_entries(campaign, kind):
        candidate = evaluate_palette_entry(conn, entry, context)
        if candidate["status"] == "out_of_context":
            continue
        if candidate["status"] == "locked" and not include_locked:
            continue
        candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            status_rank(item["status"]),
            -int(item["score"]),
            RARITY_RANK.get(str(item["entry"].get("rarity", "common")), 9),
            str(item["entry"].get("id", "")),
        )
    )
    return context, candidates[: max(0, limit)]


def find_palette_candidate(
    campaign: Campaign,
    conn: sqlite3.Connection,
    palette_id: str | None,
    *,
    location_query: str | None = None,
    intent: str | None = None,
) -> dict[str, Any] | None:
    target = str(palette_id or "").strip()
    if not target:
        return None
    context = palette_context(conn, location_query, intent)
    for entry in load_palette_entries(campaign):
        if str(entry.get("id", "")).strip() == target:
            return evaluate_palette_entry(conn, entry, context)
    return None


def palette_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    entry = candidate["entry"]
    discovery = entry.get("discovery") if isinstance(entry.get("discovery"), dict) else {}
    return {
        "palette_id": str(entry.get("id", "")),
        "palette_kind": str(entry.get("_kind", "")),
        "palette_status": str(candidate.get("status", "")),
        "palette_name": str(entry.get("name", "")),
        "palette_discovery_mode": str(discovery.get("mode", "confirm_required")),
        "source": "palette",
        "needs_gm_resolution": True,
    }


def palette_entity_id(entry: dict[str, Any]) -> str:
    save_as = entry.get("save_as") if isinstance(entry.get("save_as"), dict) else {}
    explicit = save_as.get("entity_id") or save_as.get("id")
    if explicit:
        return str(explicit)
    kind = str(save_as.get("type") or entry.get("_kind") or "entity")
    prefix = {
        "material": "mat",
        "materials": "mat",
        "item": "item",
        "location": "loc",
        "locations": "loc",
        "species": "species",
        "faction": "faction",
        "factions": "faction",
        "npc": "npc",
        "character": "npc",
        "encounter": "ref",
    }.get(kind, kind)
    raw = str(entry.get("id") or entry.get("name") or "palette-candidate").split(":", maxsplit=2)[-1]
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-._").lower()
    return f"{prefix}:{slug or 'palette-candidate'}"


def palette_entity_type(entry: dict[str, Any]) -> str:
    save_as = entry.get("save_as") if isinstance(entry.get("save_as"), dict) else {}
    value = str(save_as.get("type") or entry.get("_kind") or "reference")
    return {
        "materials": "material",
        "material": "material",
        "locations": "location",
        "location": "location",
        "factions": "faction",
        "faction": "faction",
        "species": "species",
        "encounters": "reference",
        "encounter": "reference",
    }.get(value, value)


def palette_entry_to_entity(
    entry: dict[str, Any],
    *,
    visibility: str = "hinted",
    location_id: str | None = None,
) -> dict[str, Any]:
    save_as = entry.get("save_as") if isinstance(entry.get("save_as"), dict) else {}
    discovery = entry.get("discovery") if isinstance(entry.get("discovery"), dict) else {}
    entity_type = palette_entity_type(entry)
    entity: dict[str, Any] = {
        "id": palette_entity_id(entry),
        "type": entity_type,
        "name": str(entry.get("name") or palette_entity_id(entry)),
        "status": "active",
        "visibility": visibility,
        "summary": str(entry.get("summary") or discovery.get("clue_text") or entry.get("name") or ""),
        "aliases": [str(entry.get("name"))] if entry.get("name") else [],
        "details": {
            "source_palette_id": str(entry.get("id", "")),
            "source_palette_kind": str(entry.get("_kind", "")),
            "rarity": str(entry.get("rarity", "common")),
            "risks": as_list(entry.get("risks")),
            "uses": as_list(entry.get("uses")),
            "discovery": discovery,
            "save_as": save_as,
        },
    }
    if location_id:
        entity["location_id"] = location_id
    if entity_type == "location":
        entity.pop("location_id", None)
        entity["location"] = {
            "parent_id": location_id,
            "biome": str(first_value(entry.get("biomes")) or "unknown"),
            "safety_level": str(save_as.get("safety_level") or "unknown"),
            "travel_minutes_from_home": save_as.get("travel_minutes_from_home"),
            "description_short": str(discovery.get("clue_text") or entry.get("summary") or ""),
            "exits": as_list(save_as.get("exits")),
            "resources": as_list(save_as.get("resources")),
        }
    if entity_type in {"item", "equipment"}:
        entity.pop("location_id", None)
        item = {
            "category": str(save_as.get("category") or entity_type),
            "quantity": save_as.get("default_quantity", 1),
            "unit": save_as.get("unit"),
            "quality": str(save_as.get("quality") or "standard"),
            "stackable": bool(save_as.get("stackable", True)),
        }
        entity["item"] = item
    return entity


def palette_context(conn: sqlite3.Connection, location_query: str | None, intent: str | None) -> dict[str, Any]:
    meta = get_meta(conn)
    location = resolve_location_detail(conn, location_query or meta.get("current_location_id"))
    return {
        "meta": meta,
        "day": parse_day(meta.get("current_game_day")),
        "intent": intent,
        "location": location,
        "location_id": location["id"] if location else None,
        "biome": location["biome"] if location and "biome" in location.keys() else None,
    }


def resolve_location_detail(conn: sqlite3.Connection, text: str | None) -> sqlite3.Row | None:
    if not text:
        return None
    entity = resolve_entity(conn, text)
    if not entity or entity["type"] != "location":
        return None
    return conn.execute(
        """
        select e.id, e.name, e.summary, e.status, e.visibility,
               l.parent_id, l.biome, l.safety_level, l.travel_minutes_from_home,
               l.description_short, l.exits_json, l.resources_json
        from entities e
        left join locations l on l.entity_id = e.id
        where e.id = ?
        """,
        (entity["id"],),
    ).fetchone()


def evaluate_palette_entry(
    conn: sqlite3.Connection,
    entry: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    unmet: list[str] = []
    score = 0
    location_id = context.get("location_id")
    biome = context.get("biome")
    intent = context.get("intent")

    entry_locations = set(str(item) for item in as_list(entry.get("locations")))
    entry_biomes = set(str(item) for item in as_list(entry.get("biomes")))
    entry_intents = set(str(item) for item in as_list(entry.get("intents")))

    if intent and entry_intents:
        if str(intent) not in entry_intents:
            return candidate(entry, "out_of_context", score, reasons, [f"行动不匹配：{intent}"])
        score += 2
        reasons.append(f"行动匹配 {intent}")

    if entry_locations:
        if location_id in entry_locations:
            score += 5
            reasons.append(f"地点匹配 {location_id}")
        elif entry_biomes and biome in entry_biomes:
            score += 3
            reasons.append(f"生态匹配 {biome}")
        elif context.get("location") is not None:
            return candidate(entry, "out_of_context", score, reasons, [f"地点不匹配：{location_id}"])
    elif entry_biomes:
        if biome in entry_biomes:
            score += 4
            reasons.append(f"生态匹配 {biome}")
        elif context.get("location") is not None:
            return candidate(entry, "out_of_context", score, reasons, [f"生态不匹配：{biome}"])

    unlock = entry.get("unlock") or {}
    if not isinstance(unlock, dict):
        unlock = {}
    day = context.get("day")
    min_day = unlock.get("min_day")
    if min_day is not None and (day is None or int(day) < int(min_day)):
        unmet.append(f"需要第{min_day}天后")
    required_locations = set(str(item) for item in as_list(unlock.get("required_locations")))
    if required_locations and location_id not in required_locations:
        unmet.append(f"需要地点 {join_values(sorted(required_locations))}")
    required_biomes = set(str(item) for item in as_list(unlock.get("required_biomes")))
    if required_biomes and biome not in required_biomes:
        unmet.append(f"需要生态 {join_values(sorted(required_biomes))}")
    required_clocks = unlock.get("required_clocks") or {}
    if isinstance(required_clocks, dict):
        for clock_id, required in required_clocks.items():
            filled = visible_clock_segments_filled(conn, str(clock_id))
            if filled is None or int(filled) < int(required):
                current = "未知" if filled is None else str(filled)
                unmet.append(f"[hidden] 需要 {required}+，当前 {current}")

    if unmet:
        status = "clue_only" if bool(unlock.get("allow_clue_when_locked", False)) else "locked"
        return candidate(entry, status, score, reasons, unmet)

    mode = str((entry.get("discovery") or {}).get("mode", "confirm_required"))
    if mode == "direct":
        status = "available"
    elif mode == "clue_only":
        status = "clue_only"
    else:
        status = "confirm_required"
    return candidate(entry, status, score, reasons, unmet)


def candidate(
    entry: dict[str, Any],
    status: str,
    score: int,
    reasons: list[str],
    unmet: list[str],
) -> dict[str, Any]:
    return {
        "entry": entry,
        "status": status,
        "score": score,
        "reasons": reasons,
        "unmet": unmet,
    }


def clock_segments_filled(conn: sqlite3.Connection, clock_id: str) -> int | None:
    row = conn.execute("select segments_filled from clocks where entity_id = ?", (clock_id,)).fetchone()
    return int(row["segments_filled"]) if row else None


def visible_clock_segments_filled(conn: sqlite3.Connection, clock_id: str) -> int | None:
    ensure_visibility_sql_functions(conn)
    row = conn.execute(
        f"""
        select c.segments_filled
        from clocks c
        join entities e on e.id = c.entity_id
        where c.entity_id = ?
          and {entity_not_archived_sql("e")}
          {entity_visibility_sql("player", "e")}
          {clock_visibility_sql("player", "c")}
        """,
        (clock_id,),
    ).fetchone()
    return int(row["segments_filled"]) if row else None


def parse_day(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def first_value(value: Any) -> Any:
    items = as_list(value)
    return items[0] if items else None


def status_rank(status: str) -> int:
    return {
        "available": 0,
        "confirm_required": 1,
        "clue_only": 2,
        "locked": 3,
        "out_of_context": 9,
    }.get(status, 8)


def join_values(values: list[Any]) -> str:
    return "；".join(str(item) for item in values) if values else "无"


def short_text(text: Any, limit: int = 48) -> str:
    raw = str(text or "")
    return raw if len(raw) <= limit else raw[: limit - 1] + "…"


def render_palette_suggestions(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    kind: str = "all",
    location_query: str | None = None,
    intent: str | None = None,
    include_locked: bool = False,
    limit: int = 12,
) -> str:
    context, candidates = suggest_palette_entries(
        campaign,
        conn,
        kind=kind,
        location_query=location_query,
        intent=intent,
        include_locked=include_locked,
        limit=limit,
    )
    location = context.get("location")
    lines = [
        "## 素材库候选",
        "",
        "### 查询条件",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 类型 | {kind} |",
        f"| 地点 | {location['id'] + ' ' + location['name'] if location else location_query or '当前地点未解析'} |",
        f"| 生态 | {context.get('biome') or '未知'} |",
        f"| 行动 | {intent or '未指定'} |",
        f"| 游戏日 | {context.get('day') or '未知'} |",
        f"| 包含锁定 | {'是' if include_locked else '否'} |",
        "",
    ]
    lines.extend(render_palette_table(candidates, empty_text="没有符合条件的素材库候选。"))
    lines.extend(
        [
            "",
            "### 使用规则",
            "- `可投放` 可以作为本回合合法发现或低风险资源候选。",
            "- `需确认` 只能先给线索；采样、研究或询问后才能保存为事实。",
            "- `仅线索` 只能作为伏笔，不给资源收益。",
            "- `锁定` 默认不出现，除非玩家明确改设定或条件满足。",
        ]
    )
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def render_palette_table(candidates: list[dict[str, Any]], *, empty_text: str) -> list[str]:
    if not candidates:
        return [f"- {empty_text}"]
    lines = [
        "| 状态 | 类型 | 素材 | 稀有度 | 投放线索 | 限制/原因 |",
        "|------|------|------|--------|----------|-----------|",
    ]
    for item in candidates:
        entry = item["entry"]
        discovery = entry.get("discovery") or {}
        limits = item["unmet"] or item["reasons"] or as_list(entry.get("risks"))
        lines.append(
            f"| {STATUS_LABELS.get(item['status'], item['status'])} | "
            f"{entry.get('_kind', '')} | `{entry.get('id', '')}` {entry.get('name', '')} | "
            f"{entry.get('rarity', 'common')} | {short_text(discovery.get('clue_text') or entry.get('summary'))} | "
            f"{short_text(join_values([str(value) for value in limits]), 64)} |"
        )
    return lines


def render_compact_palette_table(
    candidates: list[dict[str, Any]],
    *,
    empty_text: str,
    conn: sqlite3.Connection | None = None,
) -> list[str]:
    if not candidates:
        return [f"- {empty_text}"]
    lines = [
        "| 状态 | 素材 | 稀有度 | 线索/确认 |",
        "|------|------|--------|-----------|",
    ]
    for item in candidates:
        entry = redact_hidden_entity_refs(conn, item["entry"]) if conn else item["entry"]
        discovery = entry.get("discovery") or {}
        confirm = join_values([str(value) for value in as_list(discovery.get("confirm_methods"))[:3]])
        if item["unmet"]:
            unmet = redact_hidden_entity_refs(conn, item["unmet"][:2]) if conn else item["unmet"][:2]
            confirm = join_values([str(value) for value in unmet])
        lines.append(
            f"| {STATUS_LABELS.get(item['status'], item['status'])} | "
            f"`{entry.get('id', '')}` {entry.get('name', '')} | "
            f"{entry.get('rarity', 'common')} | {short_text(confirm or discovery.get('mode') or entry.get('summary'), 52)} |"
        )
    return lines
