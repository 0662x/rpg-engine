from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ..db import get_meta
from ..memory import find_relevant_memories, render_memory_section
from ..palette import render_compact_palette_table, suggest_palette_entries
from ..render import parse_json
from ..visibility import clock_visibility_sql, context_visibility_view, world_setting_visibility_sql
from .sections import ContextSection, estimate_tokens


EXPLORATION_TERMS = ["附近", "周围", "有没有", "看看", "探索", "找找"]
PALETTE_ACTION_SUBMODES = {"explore", "gather", "travel", "craft"}


@dataclass(frozen=True)
class ContextCollector:
    name: str
    collect: Callable[[Any], None] | None = None
    section: Callable[[Any], ContextSection | None] | None = None
    loaded_items: Callable[[Any], Iterable[dict[str, Any]]] | None = None


def run_context_collectors(state: Any, collectors: list[ContextCollector]) -> None:
    for collector in collectors:
        if collector.collect:
            collector.collect(state)


def build_collector_sections(state: Any, collectors: list[ContextCollector]) -> list[ContextSection]:
    sections: list[ContextSection] = []
    for collector in collectors:
        if not collector.section:
            continue
        section = collector.section(state)
        if not section:
            continue
        section.estimated_tokens = estimate_tokens(section.content)
        sections.append(section)
    return sections


def collect_loaded_items(state: Any, collectors: list[ContextCollector]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for collector in collectors:
        if collector.loaded_items:
            items.extend(collector.loaded_items(state))
    return items


def collect_routes(state: Any) -> None:
    if state.submode not in {"travel", "gather", "social"}:
        return
    meta = get_meta(state.conn)
    current = meta.get("current_location_id")
    destinations = [
        hit.id
        for hit in state.entity_hits
        if hit.type == "location" and hit.id != current and is_direct_hit(hit)
    ]
    if not current or not destinations:
        return
    start_ids = [current]
    parent_id = location_parent_id(state.conn, current)
    if parent_id and parent_id not in start_ids:
        start_ids.append(parent_id)
    start_placeholders = ",".join("?" for _ in start_ids)
    destination_placeholders = ",".join("?" for _ in destinations)
    state.routes = state.conn.execute(
        f"""
        select *
        from routes
        where (from_location_id in ({start_placeholders}) and to_location_id in ({destination_placeholders}))
           or (to_location_id in ({start_placeholders}) and from_location_id in ({destination_placeholders}))
        order by travel_minutes, id
        limit 5
        """,
        [*start_ids, *destinations, *start_ids, *destinations],
    ).fetchall()


def collect_palettes(state: Any) -> None:
    should_include = state.include_palettes == "always"
    if state.include_palettes == "auto":
        should_include = state.mode == "action" and (
            state.submode in PALETTE_ACTION_SUBMODES or contains_any(state.user_text, EXPLORATION_TERMS)
        )
    if not should_include or state.include_palettes == "never":
        return

    location = first_location_query(state)
    kind = "all"
    if state.submode == "gather":
        kind = "all"
    context, candidates = suggest_palette_entries(
        state.campaign,
        state.conn,
        kind=kind,
        location_query=location,
        intent=state.submode,
        include_locked=False,
        limit=5,
    )
    location_row = context.get("location")
    lines = [
        "### 素材库候选",
        "",
        "这些是候选，不是当前事实；只有观察、采样、研究、交易并保存后才成为实体。",
        "",
        f"- 查询地点：{location_row['id'] + ' ' + location_row['name'] if location_row else location or '当前地点未解析'}",
        f"- 查询行动：{state.submode}",
        "",
    ]
    lines.extend(render_compact_palette_table(candidates, empty_text="没有符合条件的素材库候选。"))
    state.palette_lines = lines


def collect_world_settings(state: Any) -> None:
    if not table_exists(state.conn, "world_settings"):
        return
    view = context_visibility_view(state.mode)
    visibility_clause = world_setting_visibility_sql(view, entity_alias="e", setting_alias="ws")
    rows = state.conn.execute(
        f"""
        select ws.*, e.name, e.summary as entity_summary, e.visibility as entity_visibility
        from world_settings ws
        join entities e on e.id = ws.entity_id
        where e.status != 'archived'
          {visibility_clause}
        order by ws.priority desc, e.name
        """
    ).fetchall()
    if not rows:
        return
    active_clock_ids = set(active_clock_ids_for_world_settings(state.conn, view=view))
    direct_ids = {hit.id for hit in state.entity_hits if hit.type == "world_setting"}
    direct_non_world_hits = any(is_direct_hit(hit) and hit.type != "world_setting" for hit in state.entity_hits)
    category_matches = categories_for_submode(state.submode)
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        applies_when = parse_json(row["applies_when_json"], {})
        linked_clocks = parse_json(row["linked_clocks_json"], [])
        keywords = [str(item) for item in applies_when.get("keywords", [])] if isinstance(applies_when, dict) else []
        submodes = [str(item) for item in applies_when.get("submodes", [])] if isinstance(applies_when, dict) else []
        reason = ""
        priority = int(row["priority"])
        if row["entity_id"] in direct_ids:
            reason = "玩家直接查询该大世界设定"
            priority += 30
        elif keywords and contains_any(state.user_text, keywords) and not (state.mode == "query" and direct_non_world_hits):
            matched = next((keyword for keyword in keywords if keyword in state.user_text), keywords[0])
            reason = f"玩家文本命中关键词：{matched}"
            priority += 20
        elif state.mode == "action" and row["category"] in category_matches and state.submode in submodes:
            reason = f"行动子模式 {state.submode} 需要 {row['category']} 设定"
            priority += 8
        elif (
            state.mode == "action"
            and row["category"] in category_matches
            and active_clock_ids.intersection(str(item) for item in linked_clocks)
        ):
            clock_id = sorted(active_clock_ids.intersection(str(item) for item in linked_clocks))[0]
            reason = f"关联活跃进度钟：{clock_id}"
            priority += 4
        if not reason:
            continue
        selected[row["entity_id"]] = {
            "row": row,
            "name": row["name"],
            "reason": reason,
            "priority": priority,
        }
    state.world_settings = sorted(
        selected.values(),
        key=lambda item: (-int(item["priority"]), str(item["row"]["entity_id"])),
    )[:4]


def collect_related_history(state: Any) -> None:
    if state.max_events <= 0:
        return
    related = find_related_events(state)
    state.related_events = related[: state.max_events]
    remaining = max(0, state.max_events - len(state.related_events))
    if remaining:
        related_ids = {row["id"] for row in state.related_events}
        state.general_events = find_general_recent_events(state, remaining, exclude_ids=related_ids)


def collect_memory_summaries(state: Any) -> None:
    targets = history_targets(state)
    state.memory_summaries = find_relevant_memories(state.conn, targets=targets, limit=4)


def active_clocks_section(state: Any) -> ContextSection:
    return ContextSection(
        key="active_clocks",
        title="Active Clocks",
        content=render_active_clocks(state.conn, view=context_visibility_view(state.mode)),
        priority=75,
        required=state.mode == "action",
    )


def routes_section(state: Any) -> ContextSection | None:
    if not state.routes:
        return None
    return ContextSection(
        key="routes",
        title="Relevant Routes",
        content=render_routes(state),
        priority=72,
        required=False,
    )


def palettes_section(state: Any) -> ContextSection | None:
    if not state.palette_lines:
        return None
    preserve = bool(getattr(state, "preserve_palette_candidates", False))
    return ContextSection(
        key="palette_candidates",
        title="Palette Candidates",
        content="\n".join(state.palette_lines),
        priority=96 if preserve else 82,
        required=preserve,
    )


def collect_discovery_states(state: Any) -> None:
    if not table_exists(state.conn, "discovery_states"):
        return
    should_include = state.mode == "action" and (
        state.submode in PALETTE_ACTION_SUBMODES or contains_any(state.user_text, EXPLORATION_TERMS)
    )
    if state.mode == "query" and contains_any(state.user_text, ["线索", "发现", "追踪", "未确认"]):
        should_include = True
    if not should_include:
        return

    targets = discovery_targets(state)
    rows: list[sqlite3.Row] = []
    if targets:
        clauses = []
        params: list[Any] = []
        for target in targets[:12]:
            clauses.append("(subject_id = ? or palette_id = ? or notes like ?)")
            params.extend([target, target, f"%{target}%"])
        rows = state.conn.execute(
            f"""
            select *
            from discovery_states
            where stage != 'archived'
              and visibility in ('hinted', 'known')
              and ({' or '.join(clauses)})
            order by
              case stage when 'confirmed' then 0 when 'observed' then 1 when 'clue' then 2 else 3 end,
              evidence_count desc,
              updated_at desc
            limit 6
            """,
            params,
        ).fetchall()
    if len(rows) < 6:
        existing = {row["id"] for row in rows}
        extra = state.conn.execute(
            """
            select *
            from discovery_states
            where stage != 'archived'
              and visibility in ('hinted', 'known')
            order by
              case stage when 'confirmed' then 0 when 'observed' then 1 when 'clue' then 2 else 3 end,
              evidence_count desc,
              updated_at desc
            limit ?
            """,
            (6,),
        ).fetchall()
        for row in extra:
            if row["id"] in existing:
                continue
            rows.append(row)
            existing.add(row["id"])
            if len(rows) >= 6:
                break
    state.discovery_states = rows[:6]


def discovery_states_section(state: Any) -> ContextSection | None:
    if not state.discovery_states:
        return None
    preserve = bool(getattr(state, "preserve_palette_candidates", False))
    return ContextSection(
        key="discovery_states",
        title="Discovery Leads",
        content=render_discovery_states(state.discovery_states),
        priority=92 if preserve else 76,
        required=False,
    )


def world_settings_section(state: Any) -> ContextSection | None:
    if not state.world_settings:
        return None
    return ContextSection(
        key="world_settings",
        title="World Settings",
        content=render_world_settings_section(state),
        priority=80 if state.mode == "query" else 68,
        required=state.mode == "query" and any(hit.type == "world_setting" for hit in state.entity_hits),
    )


def world_settings_compact_section(state: Any) -> ContextSection | None:
    if not state.world_settings or state.mode != "action":
        return None
    return ContextSection(
        key="world_settings_core",
        title="Required World Constraints",
        content=render_world_settings_compact(state),
        priority=94,
        required=True,
    )


def recent_events_section(state: Any) -> ContextSection | None:
    recent = render_history_events(state)
    if not recent:
        return None
    return ContextSection(
        key="recent_events",
        title="Relevant History",
        content=recent,
        priority=70 if state.related_events else 56,
        required=False,
    )


def memory_summaries_section(state: Any) -> ContextSection | None:
    if not state.memory_summaries:
        return None
    return ContextSection(
        key="memory_summaries",
        title="Long-Term Memory",
        content=render_memory_section(state.memory_summaries),
        priority=64,
        required=False,
    )


def route_loaded_items(state: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "kind": "route",
            "name": row["id"],
            "reason": "route relevant to requested location",
            "priority": 70,
            "depth": 1,
        }
        for row in state.routes
    ]


def discovery_loaded_items(state: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "kind": "discovery_state",
            "name": row["subject_id"] or row["palette_id"] or row["id"],
            "reason": "unconfirmed lead relevant to exploration/generation context",
            "priority": 76,
            "depth": 0,
        }
        for row in state.discovery_states
    ]


def world_setting_loaded_items(state: Any) -> list[dict[str, Any]]:
    entity_hit_ids = {hit.id for hit in state.entity_hits}
    return [
        {
            "id": item["row"]["entity_id"],
            "kind": "world_setting",
            "name": item["name"],
            "reason": item["reason"],
            "priority": item["priority"],
            "depth": 0,
        }
        for item in state.world_settings
        if item["row"]["entity_id"] not in entity_hit_ids
    ]


def event_loaded_items(state: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "kind": "event",
            "name": row["title"],
            "reason": "history relevant to loaded entities",
            "priority": 60,
            "depth": 0,
        }
        for row in state.related_events
    ]


def memory_loaded_items(state: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": row["id"],
            "kind": "memory",
            "name": row["title"],
            "reason": "long-term memory relevant to loaded entities",
            "priority": 64,
            "depth": 0,
        }
        for row in state.memory_summaries
    ]


DEFAULT_CONTEXT_COLLECTORS = [
    ContextCollector(
        name="active_clocks",
        section=active_clocks_section,
    ),
    ContextCollector(
        name="routes",
        collect=collect_routes,
        section=routes_section,
        loaded_items=route_loaded_items,
    ),
    ContextCollector(
        name="palettes",
        collect=collect_palettes,
        section=palettes_section,
    ),
    ContextCollector(
        name="discovery_states",
        collect=collect_discovery_states,
        section=discovery_states_section,
        loaded_items=discovery_loaded_items,
    ),
    ContextCollector(
        name="world_settings",
        collect=collect_world_settings,
        section=world_settings_section,
        loaded_items=world_setting_loaded_items,
    ),
    ContextCollector(
        name="world_settings_core",
        section=world_settings_compact_section,
    ),
    ContextCollector(
        name="recent_events",
        collect=collect_related_history,
        section=recent_events_section,
        loaded_items=event_loaded_items,
    ),
    ContextCollector(
        name="memory_summaries",
        collect=collect_memory_summaries,
        section=memory_summaries_section,
        loaded_items=memory_loaded_items,
    ),
]


def render_active_clocks(conn: sqlite3.Connection, *, view: str = "player") -> str:
    visibility_clause = clock_visibility_sql(view, "c")
    rows = conn.execute(
        f"""
        select e.id, e.name, e.summary, c.clock_type, c.segments_filled, c.segments_total,
               c.visibility, c.trigger_when_full
        from clocks c
        join entities e on e.id = c.entity_id
        where e.status != 'archived'
          {visibility_clause}
        order by c.visibility, e.name
        limit 10
        """
    ).fetchall()
    lines = ["### 活跃进度钟", ""]
    if not rows:
        lines.append("- 无")
        return "\n".join(lines)
    for row in rows:
        filled = int(row["segments_filled"])
        total = int(row["segments_total"])
        bar = "■" * filled + "□" * max(total - filled, 0)
        lines.append(
            f"- `{row['id']}` {row['name']}：{bar} {filled}/{total}（{row['visibility']}）"
        )
        if row["summary"]:
            lines.append(f"  - {trim_inline(row['summary'], 100)}")
    return "\n".join(lines)


def render_routes(state: Any) -> str:
    lines = [
        "### 相关路线",
        "",
        "| 路线 | 起点 | 终点 | 耗时 | 难度 |",
        "|------|------|------|------|------|",
    ]
    for row in state.routes:
        lines.append(
            f"| `{row['id']}` | `{row['from_location_id']}` | `{row['to_location_id']}` | "
            f"{row['travel_minutes']}分钟 | {row['difficulty']} |"
        )
    return "\n".join(lines)


def render_discovery_states(rows: list[sqlite3.Row]) -> str:
    lines = [
        "### 可召回线索",
        "",
        "这些是探索/采集阶段保留的线索状态，不是已确认事实；只有后续确认并保存后才可写入事实库。",
        "",
        "| 线索 | 阶段 | 可见性 | 证据 | 备注 |",
        "|------|------|--------|------|------|",
    ]
    for row in rows:
        subject = row["subject_id"] or row["palette_id"] or row["id"]
        methods = parse_json(row["confirmation_methods_json"], [])
        method_text = "；确认：" + "、".join(str(item) for item in methods[:3]) if methods else ""
        note = trim_inline(f"{row['notes'] or ''}{method_text}", 120)
        lines.append(
            f"| `{subject}` | {row['stage']} | {row['visibility']} | {row['evidence_count']} | {note} |"
        )
    return "\n".join(lines)


def render_world_settings_section(state: Any) -> str:
    lines = [
        "### 大世界设定",
        "",
        "这些是当前事实库中的稳定设定，用于约束结算；不要把素材库候选当成已发生事实。",
        "",
    ]
    for item in state.world_settings:
        row = item["row"]
        content = parse_json(row["content_json"], {})
        linked_rules = parse_json(row["linked_rules_json"], [])
        linked_clocks = parse_json(row["linked_clocks_json"], [])
        lines.extend(
            [
                f"#### `{row['entity_id']}` {item['name']}",
                "",
                f"- 召回原因：{item['reason']}",
                f"- 分类：{row['category']}；范围：{row['scope']}；可见性：{row['visibility']}",
                f"- 摘要：{trim_inline(row['summary'], 180)}",
            ]
        )
        if linked_rules:
            lines.append(f"- 关联规则：{format_context_value(linked_rules, max_chars=180)}")
        if linked_clocks:
            lines.append(f"- 关联进度钟：{format_context_value(linked_clocks, max_chars=180)}")
        if content:
            lines.append(f"- 关键内容：{format_context_value(content, max_chars=280, list_limit=3)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_world_settings_compact(state: Any) -> str:
    lines = ["### 必要世界约束", ""]
    for item in state.world_settings:
        row = item["row"]
        linked_rules = parse_json(row["linked_rules_json"], [])
        rule_suffix = f"；规则 {', '.join(str(value) for value in linked_rules[:3])}" if linked_rules else ""
        lines.append(
            f"- `{row['entity_id']}` {item['name']}：{trim_inline(row['summary'], 110)}{rule_suffix}"
        )
    lines.append("- 上述内容是结算边界；完整设定区若因预算省略，仍必须遵守这些摘要和关联规则。")
    return "\n".join(lines)


def render_history_events(state: Any) -> str:
    rows = [*state.related_events, *state.general_events]
    if not rows:
        return ""
    lines = ["### 相关/近期事件", ""]
    if state.related_events:
        lines.append("#### 相关事件")
        for row in reversed(state.related_events):
            lines.append(render_event_line(row))
    if state.general_events:
        if state.related_events:
            lines.extend(["", "#### 近期事件"])
        for row in reversed(state.general_events):
            lines.append(render_event_line(row))
    return "\n".join(lines)


def render_event_line(row: sqlite3.Row) -> str:
    time = f"（{row['game_time']}）" if row["game_time"] else ""
    return f"- `{row['turn_id']}` `{row['id']}` {row['title']}{time}：{trim_inline(row['summary'], 120)}"


def find_related_events(state: Any) -> list[sqlite3.Row]:
    targets = history_targets(state)
    if not targets:
        return []
    clauses: list[str] = []
    params: list[str] = []
    for target in targets[:18]:
        clauses.append("(payload_json like ? or summary like ? or title like ? or game_time like ?)")
        like = f"%{target}%"
        params.extend([like, like, like, like])
    rows = state.conn.execute(
        f"""
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from events
        where ({' or '.join(clauses)})
        order by
          case type when 'import' then 1 else 0 end,
          created_at desc,
          id desc
        limit ?
        """,
        [*params, max(state.max_events * 2, state.max_events)],
    ).fetchall()
    return rows


def find_general_recent_events(
    state: Any,
    limit: int,
    *,
    exclude_ids: set[str],
) -> list[sqlite3.Row]:
    rows = state.conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from events
        where type not in ('import', 'campaign_seeded')
          and id != 'event:seed'
        order by created_at desc, id desc
        limit ?
        """,
        (limit + len(exclude_ids),),
    ).fetchall()
    result = [row for row in rows if row["id"] not in exclude_ids]
    return result[:limit]


def history_targets(state: Any) -> list[str]:
    targets: list[str] = []
    for hit in state.entity_hits:
        if is_direct_hit(hit) or hit.depth <= 1:
            targets.append(hit.id)
            if hit.name and len(hit.name) >= 2:
                targets.append(hit.name)
    for row in state.routes:
        targets.append(row["id"])
        targets.append(row["from_location_id"])
        targets.append(row["to_location_id"])
    seen: set[str] = set()
    result: list[str] = []
    for target in targets:
        if target and target not in seen:
            seen.add(target)
            result.append(target)
    return result


def discovery_targets(state: Any) -> list[str]:
    targets = history_targets(state)
    for hit in state.entity_hits:
        targets.append(hit.id)
        if hit.name and len(hit.name) >= 2:
            targets.append(hit.name)
    for token in extract_chinese_terms(state.user_text):
        targets.append(token)
    seen: set[str] = set()
    result: list[str] = []
    for target in targets:
        if target and target not in seen:
            seen.add(target)
            result.append(target)
    return result


def extract_chinese_terms(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}", text)
        if token not in {"附近", "周围", "有没有", "看看", "探索", "寻找", "线索"}
    ][:8]


def first_location_query(state: Any) -> str | None:
    current = get_meta(state.conn).get("current_location_id")
    for hit in state.entity_hits:
        if hit.type == "location" and is_direct_hit(hit):
            return hit.id
    for hit in state.entity_hits:
        if hit.type == "location" and hit.id != current:
            return hit.id
    return current


def location_parent_id(conn: sqlite3.Connection, location_id: str | None) -> str | None:
    if not location_id:
        return None
    row = conn.execute("select parent_id from locations where entity_id = ?", (location_id,)).fetchone()
    return row["parent_id"] if row and row["parent_id"] else None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone()
    return bool(row)


def active_clock_ids_for_world_settings(conn: sqlite3.Connection, *, view: str = "player") -> list[str]:
    if not table_exists(conn, "clocks"):
        return []
    visibility_clause = clock_visibility_sql(view, "c")
    return [
        row["entity_id"]
        for row in conn.execute(
            f"""
            select c.entity_id
            from clocks c
            where 1 = 1
              {visibility_clause}
            """
        ).fetchall()
    ]


def categories_for_submode(submode: str) -> set[str]:
    return {
        "travel": {"calendar", "weather", "ecology", "faction"},
        "gather": {"weather", "ecology"},
        "craft": {"power", "ecology", "economy", "technology"},
        "combat": {"power", "technology"},
        "social": {"species_culture", "faction", "economy"},
        "rest": {"calendar", "weather"},
        "maintenance": {"calendar", "weather", "power", "species_culture", "faction", "ecology", "economy", "technology"},
    }.get(submode, set())


def contains_any(text: str, terms: list[str]) -> bool:
    return any(term and term in text for term in terms)


def is_direct_hit(hit: Any) -> bool:
    return hit.reason.startswith(("name", "alias", "short alias", "id", "candidate"))


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


def trim_inline(text: str | None, limit_chars: int) -> str:
    raw = str(text or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw if len(raw) <= limit_chars else raw[: max(0, limit_chars - 1)] + "…"
