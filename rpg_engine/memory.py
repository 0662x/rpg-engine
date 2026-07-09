from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .campaign import Campaign
from .db import entity_subtype_visibility_sql, get_meta, get_player_entity_id, utc_now
from .redaction import find_hidden_entity_id_substrings, find_hidden_entity_ref_tokens, redact_hidden_entity_refs
from .render import parse_json
from .time_weather import format_time_brief, format_weather_brief
from .visibility import (
    MAINTENANCE_VIEW,
    can_read_hidden,
    clock_visibility_sql,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalized_text_sql,
)


DAY_PATTERN = re.compile(r"第\s*(\d+)\s*天")


@dataclass(frozen=True)
class MemoryBuildResult:
    total: int
    by_kind: dict[str, int]
    report_path: Path


def ensure_memory_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists memory_summaries (
          id text primary key,
          kind text not null,
          subject_id text,
          title text not null,
          summary text not null,
          key_points_json text not null default '[]',
          source_event_ids_json text not null default '[]',
          source_turn_ids_json text not null default '[]',
          valid_from_turn text,
          valid_to_turn text,
          updated_at text not null,
          foreign key(subject_id) references entities(id),
          foreign key(valid_from_turn) references turns(id),
          foreign key(valid_to_turn) references turns(id)
        );
        create index if not exists idx_memory_kind_subject on memory_summaries(kind, subject_id);
        """
    )


def memory_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'memory_summaries'"
    ).fetchone()
    return bool(row)


def rebuild_memory_summaries(campaign: Campaign, conn: sqlite3.Connection) -> MemoryBuildResult:
    ensure_memory_tables(conn)
    now = utc_now()
    memories = build_memory_records(conn)
    conn.execute("begin")
    try:
        conn.execute("delete from memory_summaries")
        for memory in memories:
            conn.execute(
                """
                insert into memory_summaries
                (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                 source_turn_ids_json, valid_from_turn, valid_to_turn, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory["id"],
                    memory["kind"],
                    memory.get("subject_id"),
                    memory["title"],
                    memory["summary"],
                    json.dumps(memory.get("key_points", []), ensure_ascii=False, sort_keys=True),
                    json.dumps(memory.get("source_event_ids", []), ensure_ascii=False, sort_keys=True),
                    json.dumps(memory.get("source_turn_ids", []), ensure_ascii=False, sort_keys=True),
                    memory.get("valid_from_turn"),
                    memory.get("valid_to_turn"),
                    now,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    report_path = write_memory_report(campaign, conn)
    by_kind: dict[str, int] = {}
    for memory in memories:
        by_kind[memory["kind"]] = by_kind.get(memory["kind"], 0) + 1
    return MemoryBuildResult(total=len(memories), by_kind=by_kind, report_path=report_path)


def build_memory_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    projection_view = MAINTENANCE_VIEW
    memories: list[dict[str, Any]] = []
    memories.extend(build_day_memories(conn, view=projection_view))
    memories.extend(build_world_memories(conn, view=projection_view))
    memories.extend(build_character_memories(conn, view=projection_view))
    memories.extend(build_project_memories(conn, view=projection_view))
    memories.extend(build_faction_memories(conn, view=projection_view))
    return memories


def build_day_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    meta = get_meta(conn)
    fallback_day = str(meta.get("current_game_day") or "unknown")
    rows = recent_memory_events(conn, limit=80)
    by_day: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        day = parse_day(row["game_time"]) or fallback_day
        by_day.setdefault(day, []).append(row)
    memories: list[dict[str, Any]] = []
    for day, events in sorted(by_day.items(), key=lambda item: item[0]):
        if not events:
            continue
        ordered = sorted(events, key=lambda row: row["id"])
        history_rows = [row for row in ordered if row["type"] == "history_reconstruction"]
        if history_rows:
            selected = history_rows[-2:]
            non_history = [row for row in ordered if row["type"] != "history_reconstruction"][-4:]
            points = history_points(conn, selected, view=view)
            points.extend(event_point(row, conn, view=view) for row in non_history)
            source_rows = [*selected, *non_history]
        else:
            source_rows = ordered[-12:]
            points = [event_point(row, conn, view=view) for row in ordered[-8:]]
        memories.append(
            {
                "id": f"summary:day-{safe_id(day).zfill(3) if day.isdigit() else safe_id(day)}",
                "kind": "day",
                "title": f"第{day}天摘要" if day.isdigit() else f"{day} 摘要",
                "summary": trim_join(points[:3], "；", 260),
                "key_points": points,
                "source_event_ids": [row["id"] for row in source_rows],
                "source_turn_ids": dedupe([row["turn_id"] for row in source_rows]),
                "valid_from_turn": ordered[0]["turn_id"],
            }
        )
    return memories


def build_world_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    meta = get_meta(conn)
    should_redact = not can_read_hidden(view)
    clock_public_clause = f"and {normalized_text_sql('c.visibility')} in ('visible', 'hinted')" if should_redact else ""
    entity_visibility_clause = entity_visibility_sql(view, "e")
    clock_visibility_clause = clock_visibility_sql(view, "c")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    clocks = conn.execute(
        f"""
        select e.id, e.name, e.summary, c.segments_filled, c.segments_total, c.visibility, c.trigger_when_full
        from clocks c
        join entities e on e.id = c.entity_id
        where {entity_not_archived_sql("e")}
          {clock_public_clause}
          {entity_visibility_clause}
          {clock_visibility_clause}
          {subtype_visibility_clause}
        order by c.visibility, e.name
        limit 8
        """
    ).fetchall()
    points = [
        f"当前时间：{format_time_brief(meta)}",
        f"当前天气：{format_weather_brief(meta)}",
        f"当前位置：{current_world_location_label(conn, meta, view=view)}",
    ]
    for row in clocks:
        clock_text = str(row["summary"] or row["trigger_when_full"] or "")
        if should_redact:
            clock_text = redact_hidden_entity_refs(conn, clock_text) or ""
        points.append(f"{row['name']} {row['segments_filled']}/{row['segments_total']}：{clock_text}")
    return [
        {
            "id": "summary:current-world",
            "kind": "world",
            "title": "当前世界压力摘要",
            "summary": trim_join(points[:4], "；", 260),
            "key_points": points,
            "source_event_ids": [],
            "source_turn_ids": [],
        }
    ]


def current_world_location_label(conn: sqlite3.Connection, meta: dict[str, str], *, view: str = "player") -> str:
    location_id = meta.get("current_location_id", "")
    if not location_id:
        return "未知"
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    row = conn.execute(
        f"""
        select e.id, e.name
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
        """,
        (location_id,),
    ).fetchone()
    return f"{row['id']} {row['name']}" if row else "当前地点不可见或不存在"


def build_character_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    player_entity_id = get_player_entity_id(conn)
    should_redact = not can_read_hidden(view)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*, c.role, c.attitude, c.trust, c.health_state, c.goals_json, c.knowledge_json
        from characters c
        join entities e on e.id = c.entity_id
        where {normalized_text_sql("e.status")} = 'active'
          {visibility_clause}
          and e.id != ?
        order by c.trust desc, e.name
        limit 20
        """,
        (player_entity_id,),
    ).fetchall()
    memories: list[dict[str, Any]] = []
    for row in rows:
        events = related_events_for_subject(conn, row["id"], row["name"], limit=5)
        goals = parse_json(row["goals_json"], [])
        row_summary = str(row["summary"] or "")
        if should_redact:
            goals = redact_hidden_entity_refs(conn, goals) or []
            row_summary = redact_hidden_entity_refs(conn, row_summary) or ""
        points = [
            f"角色：{row['role'] or '未知'}",
            f"态度/信任：{row['attitude'] or '未知'} / {row['trust']}",
            f"健康：{row['health_state'] or '未知'}",
            f"摘要：{row_summary}",
        ]
        points.extend(f"目标：{goal}" for goal in as_text_list(goals)[:3])
        points.extend(event_point(event, conn, view=view) for event in events[:3])
        memories.append(
            {
                "id": f"reflection:character:{row['id'].replace(':', '-')}",
                "kind": "character",
                "subject_id": row["id"],
                "title": f"{row['name']} 长期状态",
                "summary": trim_join(points[:4], "；", 260),
                "key_points": points,
                "source_event_ids": [event["id"] for event in events],
                "source_turn_ids": dedupe([event["turn_id"] for event in events]),
            }
        )
    return memories


def build_project_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    should_redact = not can_read_hidden(view)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        where {normalized_text_sql("e.status")} = 'active'
          and e.type = 'project'
          {visibility_clause}
        order by e.name
        limit 30
        """
    ).fetchall()
    memories: list[dict[str, Any]] = []
    for row in rows:
        events = related_events_for_subject(conn, row["id"], row["name"], limit=5)
        details = parse_json(row["details_json"], {})
        row_summary = str(row["summary"] or "")
        if should_redact:
            details = redact_hidden_entity_refs(conn, details) or {}
            row_summary = redact_hidden_entity_refs(conn, row_summary) or ""
        points = [f"摘要：{row_summary}"]
        for key in ["status", "next_steps", "risks", "linked_entities"]:
            if key in details:
                points.append(f"{key}: {format_memory_value(details[key])}")
        points.extend(event_point(event, conn, view=view) for event in events[:3])
        memories.append(
            {
                "id": f"reflection:project:{row['id'].replace(':', '-')}",
                "kind": "project",
                "subject_id": row["id"],
                "title": f"{row['name']} 项目摘要",
                "summary": trim_join(points[:3], "；", 260),
                "key_points": points,
                "source_event_ids": [event["id"] for event in events],
                "source_turn_ids": dedupe([event["turn_id"] for event in events]),
            }
        )
    return memories


def build_faction_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    should_redact = not can_read_hidden(view)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        where {normalized_text_sql("e.status")} = 'active'
          and e.type in ('faction', 'faction_state', 'species')
          {visibility_clause}
        order by e.type, e.name
        limit 20
        """
    ).fetchall()
    memories: list[dict[str, Any]] = []
    for row in rows:
        events = related_events_for_subject(conn, row["id"], row["name"], limit=5)
        details = parse_json(row["details_json"], {})
        if should_redact:
            details = redact_hidden_entity_refs(conn, details) or {}
        profile = details.get("profile") or details.get("encyclopedia") or details
        row_summary = str(row["summary"] or "")
        if should_redact:
            row_summary = redact_hidden_entity_refs(conn, row_summary) or ""
        points = [f"摘要：{row_summary}"]
        if isinstance(profile, dict):
            for key, value in list(profile.items())[:4]:
                points.append(f"{key}: {format_memory_value(value)}")
        points.extend(event_point(event, conn, view=view) for event in events[:3])
        memories.append(
            {
                "id": f"reflection:faction:{row['id'].replace(':', '-')}",
                "kind": "faction",
                "subject_id": row["id"],
                "title": f"{row['name']} 势力/族群反思",
                "summary": trim_join(points[:3], "；", 260),
                "key_points": points,
                "source_event_ids": [event["id"] for event in events],
                "source_turn_ids": dedupe([event["turn_id"] for event in events]),
            }
        )
    return memories


def recent_memory_events(conn: sqlite3.Connection, *, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from events
        where type not in ('import', 'campaign_seeded')
          and id != 'event:seed'
        order by created_at desc, id desc
        limit ?
        """,
        (limit,),
    ).fetchall()


def related_events_for_subject(conn: sqlite3.Connection, subject_id: str, name: str, *, limit: int) -> list[sqlite3.Row]:
    like_id = f"%{subject_id}%"
    like_name = f"%{name}%"
    return conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from events
        where payload_json like ?
           or summary like ?
           or title like ?
        order by created_at desc, id desc
        limit ?
        """,
        (like_id, like_name, like_name, limit),
    ).fetchall()


def find_relevant_memories(
    conn: sqlite3.Connection,
    *,
    targets: list[str],
    limit: int = 4,
    view: str = "player",
) -> list[sqlite3.Row]:
    if not memory_table_exists(conn):
        return []
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    clauses = ["m.kind in ('world', 'day')"]
    params: list[str] = []
    for target in targets[:16]:
        if not target:
            continue
        clauses.append("(m.subject_id = ? or m.title like ? or m.summary like ? or m.key_points_json like ?)")
        like = f"%{target}%"
        params.extend([target, like, like, like])
    if not can_read_hidden(view):
        return find_player_safe_relevant_memories(
            conn,
            clauses=clauses,
            params=params,
            limit=limit,
            view=view,
        )
    rows = conn.execute(
        f"""
        select m.*
        from memory_summaries m
        left join entities e on e.id = m.subject_id
        left join clocks c on c.entity_id = e.id
        where (e.id is null or ({entity_not_archived_sql("e")} {visibility_clause} {subtype_visibility_clause}))
          and ({' or '.join(clauses)})
        order by
          case m.kind
            when 'world' then 0
            when 'character' then 1
            when 'project' then 2
            when 'faction' then 3
            when 'day' then 4
            else 5
          end,
          m.updated_at desc,
          m.id
        limit ?
        """,
        [*params, limit],
    ).fetchall()
    return rows[:limit]


def find_player_safe_relevant_memories(
    conn: sqlite3.Connection,
    *,
    clauses: list[str],
    params: list[str],
    limit: int,
    view: str,
) -> list[sqlite3.Row]:
    page_size = max(limit * 4, limit + 12)
    offset = 0
    result: list[sqlite3.Row] = []
    while len(result) < limit:
        rows = conn.execute(
            f"""
            select m.*
            from memory_summaries m
            left join entities e on e.id = m.subject_id
            left join clocks c on c.entity_id = e.id
            where (e.id is null or ({entity_not_archived_sql("e")} {entity_visibility_sql(view, "e")} {entity_subtype_visibility_sql(view, "e", "c")}))
              and ({' or '.join(clauses)})
            order by
              case m.kind
                when 'world' then 0
                when 'character' then 1
                when 'project' then 2
                when 'faction' then 3
                when 'day' then 4
                else 5
              end,
              m.updated_at desc,
              m.id
            limit ? offset ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            if memory_row_has_hidden_refs(conn, row):
                continue
            result.append(redact_memory_row_for_view(conn, row, view=view))
            if len(result) >= limit:
                break
    return result[:limit]


def memory_row_has_hidden_refs(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    payload = {
        "title": row["title"],
        "summary": row["summary"],
        "key_points": row["key_points_json"],
    }
    identifiers = {
        "id": row["id"],
        "subject_id": row["subject_id"],
    }
    return (
        bool(find_hidden_entity_ref_tokens(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, identifiers))
    )


def render_memory_section(rows: list[sqlite3.Row], conn: sqlite3.Connection | None = None, *, view: str = "player") -> str:
    lines = ["### 长期记忆摘要", ""]
    for row in rows:
        title = row["title"]
        summary = row["summary"]
        points = parse_json(row["key_points_json"], [])
        if conn is not None and not can_read_hidden(view):
            title = redact_hidden_entity_refs(conn, title) or ""
            summary = redact_hidden_entity_refs(conn, summary) or ""
            points = redact_hidden_entity_refs(conn, points) or []
        lines.append(f"- `{row['id']}` {title}（{row['kind']}）：{summary}")
        for point in as_text_list(points)[:3]:
            lines.append(f"  - {point}")
    return "\n".join(lines)


def redact_memory_row_for_view(conn: sqlite3.Connection, row: sqlite3.Row, *, view: str = "player") -> dict[str, Any]:
    safe = dict(row)
    if can_read_hidden(view):
        return safe
    safe["subject_id"] = redact_hidden_entity_refs(conn, safe.get("subject_id"), drop_empty=False)
    safe["title"] = redact_hidden_entity_refs(conn, str(safe.get("title") or ""), drop_empty=False) or ""
    safe["summary"] = redact_hidden_entity_refs(conn, str(safe.get("summary") or ""), drop_empty=False) or ""
    points = parse_json(str(safe.get("key_points_json") or "[]"), [])
    safe["key_points_json"] = json.dumps(
        redact_hidden_entity_refs(conn, points, drop_empty=False) or [],
        ensure_ascii=False,
        sort_keys=True,
    )
    return safe


def write_memory_report(campaign: Campaign, conn: sqlite3.Connection) -> Path:
    rows = [
        redact_memory_row_for_view(conn, row, view="player")
        for row in conn.execute(
            """
            select *
            from memory_summaries
            order by kind, id
            """
        ).fetchall()
    ]
    path = campaign.root / "reports" / "memory-current.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {campaign.name} 长期记忆摘要",
        "",
        f"- 条目数：{len(rows)}",
        "",
    ]
    for row in rows:
        lines.append(f"## `{row['id']}` {row['title']}")
        lines.append("")
        lines.append(f"- 类型：{row['kind']}")
        if row["subject_id"]:
            lines.append(f"- 主体：`{row['subject_id']}`")
        lines.append(f"- 摘要：{row['summary']}")
        points = parse_json(row["key_points_json"], [])
        if points:
            lines.append("- 要点：")
            for point in as_text_list(points):
                lines.append(f"  - {point}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def parse_day(value: str | None) -> str | None:
    if not value:
        return None
    match = DAY_PATTERN.search(value)
    return match.group(1) if match else None


def event_point(row: sqlite3.Row, conn: sqlite3.Connection | None = None, *, view: str = "player") -> str:
    title = str(row["title"] or row["type"])
    summary = str(row["summary"] or "")
    if conn is not None and not can_read_hidden(view):
        title = redact_hidden_entity_refs(conn, title) or ""
        summary = redact_hidden_entity_refs(conn, summary) or ""
    return trim_join([title, summary], "：", 180)


def history_points(conn: sqlite3.Connection, rows: list[sqlite3.Row], *, view: str = "player") -> list[str]:
    points: list[str] = []
    for row in rows:
        points.append(event_point(row, conn, view=view))
        payload = parse_json(row["payload_json"], {})
        key_points = payload.get("key_points") if isinstance(payload, dict) else None
        if isinstance(key_points, list):
            if can_read_hidden(view):
                points.extend(str(point) for point in key_points[:8] if str(point))
            else:
                points.extend(
                    str(redact_hidden_entity_refs(conn, str(point)) or "")
                    for point in key_points[:8]
                    if str(point)
                )
        provenance = payload.get("provenance") if isinstance(payload, dict) else None
        if isinstance(provenance, dict):
            tier = provenance.get("tier")
            if tier:
                points.append(f"来源等级：{tier}")
    return points


def as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def format_memory_value(value: Any) -> str:
    if isinstance(value, list):
        return trim_join([format_memory_value(item) for item in value[:4]], "；", 180)
    if isinstance(value, dict):
        parts = [f"{key}={format_memory_value(item)}" for key, item in list(value.items())[:4]]
        return trim_join(parts, "；", 180)
    return str(value)


def trim_join(items: list[str], separator: str, limit: int) -> str:
    text = separator.join(item for item in items if item)
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return text.strip("-") or "unknown"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
