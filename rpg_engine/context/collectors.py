from __future__ import annotations

import re
import sqlite3
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from ..campaign import load_yaml_file
from ..db import entity_subtype_visibility_sql, get_meta
from ..memory import (
    find_omitted_relevant_memories,
    find_relevant_memories,
    memory_freshness_status,
    memory_fallback_item,
    memory_row_authority,
    memory_row_freshness_evidence,
    memory_row_freshness,
    memory_row_freshness_turn_id,
    memory_row_has_hidden_refs,
    memory_row_summary_type,
    memory_row_source_event_ids,
    memory_row_source_turn_ids,
    memory_projection_health,
    memory_projection_change_omissions,
    memory_projection_snapshot,
    memory_projection_snapshot_change,
    player_safe_memory_reason,
    render_memory_section,
    row_value,
    safe_memory_summary_id,
)
from ..palette import render_compact_palette_table, suggest_palette_entries
from ..progress_access import ProgressRecord, list_progress
from ..redaction import find_hidden_entity_id_substrings, find_hidden_entity_ref_tokens, redact_hidden_entity_refs
from ..relationship_access import RelationshipRecord, list_relationships
from ..render import parse_json
from ..visibility import (
    can_read_hidden,
    clock_visibility_sql,
    context_visibility_view,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    is_player_hidden_visibility,
    normalized_text_sql,
    player_hidden_visibility_sql,
    world_setting_visibility_sql,
)
from .sections import ContextSection, estimate_tokens


EXPLORATION_TERMS = ["附近", "周围", "有没有", "看看", "探索", "找找"]
PALETTE_ACTION_SUBMODES = {"explore", "gather", "travel", "craft"}
DISCOVERY_VISIBILITIES_FOR_TRUSTED = ("known", "hinted", "hidden", "gm", "maintenance")
DISCOVERY_VISIBILITIES_FOR_PLAYER = ("known", "hinted")
RELATIONSHIP_CONTEXT_LIMIT = 8
PROGRESS_CONTEXT_LIMIT = 8
PLOT_SIGNAL_LIMIT = 8
PLOT_HINT_OBJECT_FIELDS = frozenset(
    {"id", "name", "title", "summary", "text", "description", "goal", "clue", "visibility", "audience"}
)


@dataclass(frozen=True)
class ContextCollector:
    name: str
    collect: Callable[[Any], None] | None = None
    section: Callable[[Any], ContextSection | None] | None = None
    loaded_items: Callable[[Any], Iterable[dict[str, Any]]] | None = None
    source: str = ""
    visibility: str = ""
    provenance: str = ""
    budget_behavior: str = ""
    omitted_items: Callable[[Any], Iterable[dict[str, Any]]] | None = None


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
            for item in collector.loaded_items(state):
                items.append(enrich_collector_item(state, collector, item, included=True))
    return items


def collect_omitted_items(state: Any, collectors: list[ContextCollector]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for collector in collectors:
        if collector.omitted_items:
            for item in collector.omitted_items(state):
                items.append(enrich_collector_item(state, collector, item, included=False))
    return items


def enrich_collector_item(
    state: Any,
    collector: ContextCollector,
    item: dict[str, Any],
    *,
    included: bool,
) -> dict[str, Any]:
    enriched = dict(item)
    enriched.setdefault("source", collector.source or collector.name)
    enriched.setdefault(
        "provenance",
        {
            "collector": collector.name,
            "source": collector.source or collector.name,
            "detail": collector.provenance or collector.name,
        },
    )
    enriched.setdefault(
        "visibility",
        {
            "mode": state_visibility_view(state),
            "policy": collector.visibility,
        },
    )
    default_budget = {
        "included": included,
        "behavior": collector.budget_behavior,
        "priority": enriched.get("priority", 0),
        "estimated_tokens": enriched.get("estimated_tokens"),
        "reason": None if included else enriched.get("reason", "omitted by collector policy"),
    }
    budget = enriched.get("budget")
    enriched["budget"] = default_budget | (dict(budget) if isinstance(budget, dict) else {})
    enriched.setdefault("depth", None)
    return enriched


def state_visibility_view(state: Any) -> str:
    return getattr(state, "visibility_view", None) or context_visibility_view(getattr(state, "mode", None))


def context_target_ids(state: Any) -> set[str]:
    ids = {
        hit.id
        for hit in getattr(state, "entity_hits", [])
        if is_direct_hit(hit) or getattr(hit, "depth", 0) <= 1
    }
    meta = get_meta(state.conn)
    for value in (meta.get("current_location_id"), getattr(state.campaign, "player_entity_id", None)):
        if value:
            ids.add(str(value))
    ids.update(raw_context_entity_ids(getattr(state, "user_text", "")))
    return ids


def target_search_values(state: Any) -> list[str]:
    values = list(context_target_ids(state))
    for hit in getattr(state, "entity_hits", []):
        if hit.name and len(hit.name) >= 2:
            values.append(hit.name)
    for token in extract_chinese_terms(getattr(state, "user_text", "")):
        values.append(token)
    values.extend(raw_context_entity_ids(getattr(state, "user_text", "")))
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def raw_context_entity_ids(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_-]*:[A-Za-z0-9_.:-]+", str(text or "")))


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
    ensure_visibility_sql_functions(state.conn)
    view = state_visibility_view(state)
    start_ids = [current]
    parent_id = location_parent_id(state.conn, current, view=view)
    if parent_id and parent_id not in start_ids:
        start_ids.append(parent_id)
    start_placeholders = ",".join("?" for _ in start_ids)
    destination_placeholders = ",".join("?" for _ in destinations)
    from_visibility_clause = entity_visibility_sql(view, "from_e")
    to_visibility_clause = entity_visibility_sql(view, "to_e")
    from_subtype_clause = entity_subtype_visibility_sql(view, "from_e", "from_clock")
    to_subtype_clause = entity_subtype_visibility_sql(view, "to_e", "to_clock")
    state.routes = state.conn.execute(
        f"""
        select r.*
        from routes r
        join entities from_e on from_e.id = r.from_location_id
        join entities to_e on to_e.id = r.to_location_id
        left join clocks from_clock on from_clock.entity_id = from_e.id
        left join clocks to_clock on to_clock.entity_id = to_e.id
        where {normalized_text_sql("from_e.type")} = 'location'
          and {normalized_text_sql("to_e.type")} = 'location'
          and {entity_not_archived_sql("from_e")}
          and {entity_not_archived_sql("to_e")}
          {from_visibility_clause}
          {to_visibility_clause}
          {from_subtype_clause}
          {to_subtype_clause}
          and (
            (r.from_location_id in ({start_placeholders}) and r.to_location_id in ({destination_placeholders}))
            or (r.to_location_id in ({start_placeholders}) and r.from_location_id in ({destination_placeholders}))
          )
        order by r.travel_minutes, r.id
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
    state.palette_candidates = candidates
    view = state_visibility_view(state)
    should_redact = not can_read_hidden(view)
    location_row = context.get("location")
    location_label = (
        location_row["id"] + " " + location_row["name"]
        if location_row
        else (redact_hidden_entity_refs(state.conn, location) if location and should_redact else location)
    )
    lines = [
        "### 素材库候选",
        "",
        "这些是候选，不是当前事实；只有观察、采样、研究、交易并保存后才成为实体。",
        "",
        f"- 查询地点：{location_label or '当前地点未解析'}",
        f"- 查询行动：{state.submode}",
        "",
    ]
    lines.extend(
        render_compact_palette_table(
            candidates,
            empty_text="没有符合条件的素材库候选。",
            conn=state.conn if should_redact else None,
        )
    )
    if should_redact:
        lines = redact_hidden_entity_refs(state.conn, lines)
    state.palette_lines = lines


def collect_world_settings(state: Any) -> None:
    if not table_exists(state.conn, "world_settings"):
        return
    ensure_visibility_sql_functions(state.conn)
    view = state_visibility_view(state)
    visibility_clause = world_setting_visibility_sql(view, entity_alias="e", setting_alias="ws")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    rows = state.conn.execute(
        f"""
        select ws.*, e.name, e.summary as entity_summary, e.visibility as entity_visibility
        from world_settings ws
        join entities e on e.id = ws.entity_id
        left join clocks c on c.entity_id = e.id
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
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


def collect_relationships(state: Any) -> None:
    view = state_visibility_view(state)
    targets = context_target_ids(state)
    selected: dict[str, dict[str, Any]] = {}
    structural_omissions: list[dict[str, Any]] = []
    for relationship in list_relationships(state.conn, view=view):
        if relationship.endpoint_issues:
            if can_read_hidden(view) and relationship_related_to_targets(relationship, targets):
                structural_omissions.append(relationship_omission_item(relationship, reason_code_for_relationship(relationship)))
            continue
        relevance = relationship_relevance(state, relationship, targets)
        if relevance is None:
            continue
        reason, priority = relevance
        selected[relationship.id] = {
            "record": relationship,
            "reason": reason,
            "priority": priority,
            "depth": 1,
        }
    ranked = sorted(
        selected.values(),
        key=lambda item: (-int(item["priority"]), item["record"].id),
    )
    state.relationships = ranked[:RELATIONSHIP_CONTEXT_LIMIT]
    capped = ranked[RELATIONSHIP_CONTEXT_LIMIT:]
    included_ids = {item["record"].id for item in state.relationships}
    capped_ids = {item["record"].id for item in capped}
    structural_ids = {item["id"] for item in structural_omissions}
    state.relationship_omissions = [
        *structural_omissions,
        *relationship_cap_omissions(capped),
        *relationship_omission_evidence_for_state(state, omitted_ids=included_ids | capped_ids | structural_ids),
    ]


def relationship_relevance(
    state: Any,
    relationship: RelationshipRecord,
    targets: set[str],
) -> tuple[str, int] | None:
    endpoints = {relationship.source_id, relationship.target_id}
    direct_hit_ids = {hit.id for hit in getattr(state, "entity_hits", []) if is_direct_hit(hit)}
    if relationship.id in direct_hit_ids or relationship.id in getattr(state, "user_text", ""):
        return "玩家直接查询该 relationship", 88
    if endpoints & direct_hit_ids:
        return "relationship endpoint directly referenced by player text", 84
    if endpoints & targets and state.submode == "social":
        return "social action needs relationship context for visible endpoint", 82
    if endpoints & targets:
        return "relationship shares a loaded context endpoint", 72
    return None


def relationship_omission_evidence_for_state(
    state: Any,
    *,
    omitted_ids: set[str],
) -> list[dict[str, Any]]:
    view = state_visibility_view(state)
    targets = context_target_ids(state)
    omitted: list[dict[str, Any]] = []
    maintenance_records = list_relationships(state.conn, view="maintenance", include_archived=True)
    for relationship in maintenance_records:
        if relationship.id in omitted_ids:
            continue
        if not relationship_related_to_targets(relationship, targets):
            continue
        reason_code = reason_code_for_relationship(relationship)
        if can_read_hidden(view):
            if reason_code:
                omitted.append(relationship_omission_item(relationship, reason_code))
            continue
    return omitted[:RELATIONSHIP_CONTEXT_LIMIT]


def relationship_cap_omissions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        relationship_omission_item(
            item["record"],
            "over_budget",
            priority=item["priority"],
            reason="relationship omitted by collector-local relevance cap",
        )
        for item in items
    ]


def relationship_omission_item(
    relationship: RelationshipRecord,
    reason_code: str | None,
    *,
    priority: int = 35,
    reason: str | None = None,
    player_safe: bool = False,
) -> dict[str, Any]:
    safe_reason = reason or f"relationship omitted: {reason_code or 'conflict'}"
    if player_safe:
        safe_reason = f"relationship omitted: {reason_code or 'conflict'}"
    return {
        "id": relationship.id,
        "kind": "relationship",
        "name": relationship.id,
        "reason": safe_reason,
        "reason_code": reason_code or "conflict",
        "priority": priority,
        "depth": 1,
    }


def reason_code_for_relationship(relationship: RelationshipRecord) -> str | None:
    if normalize_label(getattr(relationship, "status", "")) == "archived":
        return "archived"
    issues = [str(issue).lower() for issue in relationship.endpoint_issues]
    if any("missing entity" in issue or "required" in issue for issue in issues):
        return "missing_reference"
    if any("archived entity" in issue for issue in issues):
        return "archived"
    if issues:
        return "conflict"
    return None


def relationship_related_to_targets(relationship: RelationshipRecord, targets: set[str]) -> bool:
    return bool({relationship.id, relationship.source_id, relationship.target_id} & targets)


def relationships_section(state: Any) -> ContextSection | None:
    if not state.relationships:
        return None
    return ContextSection(
        key="relationships",
        title="Relevant Relationships",
        content=render_relationships(state),
        priority=83 if state.submode == "social" else 73,
        required=False,
    )


def render_relationships(state: Any) -> str:
    lines = [
        "### 相关关系",
        "",
        "| Relationship | Endpoints | Kind/State | Trust/Attitude | Reason | Summary |",
        "|--------------|-----------|------------|----------------|--------|---------|",
    ]
    for item in state.relationships:
        relationship: RelationshipRecord = item["record"]
        endpoints = f"`{markdown_code_text(relationship.source_id)}` -> `{markdown_code_text(relationship.target_id)}`"
        kind_state = " / ".join(str(value) for value in (relationship.kind, relationship.state) if value) or "unknown"
        trust_attitude = " / ".join(str(value) for value in (relationship.trust, relationship.attitude, relationship.stance) if value) or "n/a"
        lines.append(
            f"| `{markdown_code_text(relationship.id)}` | {endpoints} | {markdown_table_cell(kind_state, 80)} | "
            f"{markdown_table_cell(trust_attitude, 80)} | {markdown_table_cell(item['reason'], 120)} | "
            f"{markdown_table_cell(relationship.summary, 100)} |"
        )
    return "\n".join(lines)


def collect_progress_context(state: Any) -> None:
    view = state_visibility_view(state)
    targets = set(target_search_values(state))
    if state.mode == "action":
        targets.update(relevant_world_setting_linked_clock_ids(state, view=view))
        targets.update(recent_activity_progress_ids(state, view=view))
    selected: dict[str, dict[str, Any]] = {}
    structural_omissions: list[dict[str, Any]] = []
    for progress in list_progress(state.conn, view=view, statuses="active"):
        if not can_read_hidden(view) and progress_has_hidden_refs(state.conn, progress):
            continue
        reason_code = reason_code_for_progress(state.conn, progress, view=view)
        relevance = progress_relevance(state, progress, targets)
        if reason_code:
            if can_read_hidden(view) and (
                relevance is not None or progress_relevant_to_targets(progress, targets)
            ):
                structural_omissions.append(progress_omission_item(progress, reason_code))
            continue
        if relevance is None:
            continue
        reason, priority = relevance
        selected[progress.id] = {
            "record": progress,
            "reason": reason,
            "priority": priority,
            "depth": 1,
        }
    ranked = sorted(
        selected.values(),
        key=lambda item: (-int(item["priority"]), item["record"].id),
    )
    state.progress_context = ranked[:PROGRESS_CONTEXT_LIMIT]
    capped = ranked[PROGRESS_CONTEXT_LIMIT:]
    included_ids = {item["record"].id for item in state.progress_context}
    capped_ids = {item["record"].id for item in capped}
    structural_ids = {item["id"] for item in structural_omissions}
    state.progress_omissions = [
        *structural_omissions,
        *progress_cap_omissions(capped),
        *progress_omission_evidence_for_state(state, omitted_ids=included_ids | capped_ids | structural_ids),
    ]


def progress_relevance(
    state: Any,
    progress: ProgressRecord,
    targets: set[str],
) -> tuple[str, int] | None:
    direct_hit_ids = {hit.id for hit in getattr(state, "entity_hits", []) if is_direct_hit(hit)}
    if progress.id in direct_hit_ids or progress.id in getattr(state, "user_text", ""):
        return "玩家直接查询该 progress track", 88
    progress_name = progress.entity.name if progress.entity else ""
    if progress_name and progress_name in getattr(state, "user_text", ""):
        return "玩家文本命中 progress 名称", 86
    searchable = progress_searchable_text(progress)
    for target in targets:
        if target and target in searchable:
            return "progress scope or rules reference loaded context target", 78
    if state.mode == "action" and normalize_clock_kind(progress.clock_type) in progress_kinds_for_submode(state.submode):
        return f"action submode {state.submode} needs {progress.clock_type} progress context", 68
    if state.mode == "action" and progress_is_active(progress):
        return "active progress track considered for action context", 54
    return None


def progress_omission_evidence_for_state(
    state: Any,
    *,
    omitted_ids: set[str],
) -> list[dict[str, Any]]:
    view = state_visibility_view(state)
    targets = set(target_search_values(state))
    if state.mode == "action":
        targets.update(relevant_world_setting_linked_clock_ids(state, view=view))
        targets.update(recent_activity_progress_ids(state, view=view))
    omitted: list[dict[str, Any]] = []
    for progress in list_progress(state.conn, view="maintenance", include_archived=True):
        if progress.id in omitted_ids:
            continue
        if progress_relevant_to_targets(progress, targets) is False:
            continue
        reason_code = reason_code_for_progress(state.conn, progress, view=view)
        if can_read_hidden(view):
            if reason_code:
                omitted.append(progress_omission_item(progress, reason_code))
            continue
    return omitted[:PROGRESS_CONTEXT_LIMIT]


def progress_cap_omissions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        progress_omission_item(
            item["record"],
            "over_budget",
            priority=item["priority"],
            reason="progress omitted by collector-local relevance cap",
        )
        for item in items
    ]


def progress_omission_item(
    progress: ProgressRecord,
    reason_code: str | None,
    *,
    priority: int = 35,
    reason: str | None = None,
    player_safe: bool = False,
) -> dict[str, Any]:
    safe_reason = reason or f"progress omitted: {reason_code or 'conflict'}"
    if player_safe:
        safe_reason = f"progress omitted: {reason_code or 'conflict'}"
    return {
        "id": progress.id,
        "kind": "progress",
        "name": progress.entity.name if progress.entity and not player_safe else progress.id,
        "reason": safe_reason,
        "reason_code": reason_code or "conflict",
        "priority": priority,
        "depth": 1,
    }


def reason_code_for_progress(conn: sqlite3.Connection, progress: ProgressRecord, *, view: str | None = None) -> str | None:
    if normalize_label(progress.status) == "archived":
        return "archived"
    reference_issue = progress_reference_issue_code(conn, progress, view=view)
    if reference_issue:
        return reference_issue
    if not progress_is_active(progress):
        return "conflict"
    return None


def progress_relevant_to_targets(progress: ProgressRecord, targets: set[str]) -> bool:
    text = progress_searchable_text(progress)
    return any(target and target in text for target in targets)


def progress_searchable_text(progress: ProgressRecord) -> str:
    return jsonish_text(
        {
            "id": progress.id,
            "name": progress.entity.name if progress.entity else "",
            "summary": progress.summary,
            "trigger": progress.trigger_when_full,
            "scope": progress.scope,
            "tick_rules": progress.tick_rules,
            "details": progress.details,
        }
    )


def relevant_world_setting_linked_clock_ids(state: Any, *, view: str) -> set[str]:
    if not table_exists(state.conn, "world_settings"):
        return set()
    ensure_visibility_sql_functions(state.conn)
    visibility_clause = world_setting_visibility_sql(view, entity_alias="e", setting_alias="ws")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    direct_ids = {hit.id for hit in getattr(state, "entity_hits", []) if hit.type == "world_setting"}
    category_matches = categories_for_submode(getattr(state, "submode", ""))
    rows = state.conn.execute(
        f"""
        select ws.*, e.name
        from world_settings ws
        join entities e on e.id = ws.entity_id
        left join clocks c on c.entity_id = e.id
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
        """
    ).fetchall()
    linked: set[str] = set()
    for row in rows:
        applies_when = parse_json(row["applies_when_json"], {})
        linked_clocks = [str(item) for item in parse_json(row["linked_clocks_json"], []) if str(item).strip()]
        if not linked_clocks:
            continue
        keywords = [str(item) for item in applies_when.get("keywords", [])] if isinstance(applies_when, dict) else []
        submodes = [str(item) for item in applies_when.get("submodes", [])] if isinstance(applies_when, dict) else []
        relevant = row["entity_id"] in direct_ids
        relevant = relevant or (keywords and contains_any(getattr(state, "user_text", ""), keywords))
        relevant = relevant or (row["category"] in category_matches and getattr(state, "submode", "") in submodes)
        if relevant:
            linked.update(linked_clocks)
    return linked


def recent_activity_progress_ids(state: Any, *, view: str | None = None) -> set[str]:
    if not table_exists(state.conn, "events"):
        return set()
    rows = state.conn.execute(
        """
        select id, turn_id, title, summary, game_time, payload_json
        from events
        order by created_at desc, id desc
        limit 30
        """
    ).fetchall()
    ids: set[str] = set()
    for row in rows:
        if not can_read_hidden(view) and history_event_has_hidden_refs(state.conn, row):
            continue
        text = jsonish_text(
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "payload": row["payload_json"],
            }
        )
        ids.update(re.findall(r"clock:[A-Za-z0-9_.:-]+", text))
    return ids


def progress_reference_issue_code(conn: sqlite3.Connection, progress: ProgressRecord, *, view: str | None = None) -> str | None:
    for entity_id in referenced_entity_ids(
        {
            "scope": progress.scope,
            "tick_rules": progress.tick_rules,
            "details": progress.details,
        }
    ):
        if entity_id == progress.id:
            continue
        row = conn.execute(
            "select status, visibility from entities where id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return "missing_reference"
        if normalize_label(row["status"]) == "archived":
            return "archived"
        if not can_read_hidden(view) and is_player_hidden_visibility(row["visibility"]):
            return "hidden"
    return "hidden" if not can_read_hidden(view) and progress_has_hidden_refs(conn, progress) else None


def referenced_entity_ids(value: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            ids.update(referenced_entity_ids(item))
        return ids
    if isinstance(value, list):
        for item in value:
            ids.update(referenced_entity_ids(item))
        return ids
    if isinstance(value, str):
        ids.update(re.findall(r"\b[A-Za-z_][A-Za-z0-9_-]*:[A-Za-z0-9_.:-]+", value))
    return ids


def progress_has_hidden_refs(conn: sqlite3.Connection, progress: ProgressRecord) -> bool:
    payload = {
        "id": progress.id,
        "name": progress.entity.name if progress.entity else "",
        "summary": progress.summary,
        "trigger": progress.trigger_when_full,
        "scope": progress.scope,
        "tick_rules": progress.tick_rules,
        "details": progress.details,
    }
    return bool(find_hidden_entity_ref_tokens(conn, payload)) or bool(find_hidden_entity_id_substrings(conn, payload))


def normalize_label(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def normalize_clock_kind(value: Any) -> str:
    return normalize_label(value)


def progress_kinds_for_submode(submode: str) -> set[str]:
    return {
        "social": {"relationship", "faction"},
        "travel": {"season", "faction", "mystery", "threat", "condition"},
        "gather": {"season", "ecology", "base", "project"},
        "craft": {"project", "base", "technology", "ecology"},
        "combat": {"threat", "mystery", "condition"},
        "rest": {"condition", "base", "season"},
        "routine": {"base", "ecology", "season", "project", "condition"},
        "explore": {"mystery", "threat", "season", "ecology", "project"},
    }.get(submode, set())


def progress_is_active(progress: ProgressRecord) -> bool:
    return normalize_label(progress.status) == "active" and progress.segments_filled < progress.segments_total


def progress_context_section(state: Any) -> ContextSection | None:
    if not state.progress_context:
        return None
    return ContextSection(
        key="progress_context",
        title="Relevant Progress",
        content=render_progress_context(state),
        priority=84 if state.mode == "action" else 74,
        required=False,
    )


def render_progress_context(state: Any) -> str:
    lines = [
        "### 相关进度",
        "",
        "| Progress | Kind | State | Trigger | Reason | Summary |",
        "|----------|------|-------|---------|--------|---------|",
    ]
    for item in state.progress_context:
        progress: ProgressRecord = item["record"]
        filled = int(progress.segments_filled)
        total = int(progress.segments_total)
        bar = "■" * filled + "□" * max(total - filled, 0)
        lines.append(
            f"| `{markdown_code_text(progress.id)}` | {markdown_table_cell(progress.clock_type, 60)} | "
            f"{markdown_table_cell(f'{bar} {filled}/{total}', 80)} | "
            f"{markdown_table_cell(progress.trigger_when_full, 80)} | {markdown_table_cell(item['reason'], 120)} | "
            f"{markdown_table_cell(progress.summary, 100)} |"
        )
        tick_when = progress.tick_rules.get("tick_when") or progress.tick_rules.get("on")
        reduce_when = progress.tick_rules.get("reduce_when")
        scope = progress.scope
        hints = []
        if scope:
            hints.append(f"scope={format_context_value(scope, max_chars=120)}")
        if tick_when:
            hints.append(f"tick={format_context_value(tick_when, max_chars=120)}")
        if reduce_when:
            hints.append(f"reduce={format_context_value(reduce_when, max_chars=120)}")
        if hints:
            lines.append(f"|  |  |  |  | rules | {markdown_table_cell('；'.join(hints), 180)} |")
    return "\n".join(lines)


def collect_related_history(state: Any) -> None:
    if state.max_events <= 0:
        return
    related = player_safe_history_events(state, find_related_events(state))
    state.related_events = related[: state.max_events]
    remaining = max(0, state.max_events - len(state.related_events))
    if remaining:
        related_ids = {row["id"] for row in state.related_events}
        state.general_events = player_safe_history_events(
            state,
            find_general_recent_events(state, remaining, exclude_ids=related_ids),
        )[:remaining]


def collect_memory_summaries(state: Any) -> None:
    targets = history_targets(state)
    health = memory_projection_health(state.conn)
    projection_snapshot = memory_projection_snapshot(state.conn, health)
    state.memory_summaries = find_relevant_memories(
        state.conn,
        targets=targets,
        limit=4,
        view=state_visibility_view(state),
    )
    state.memory_omissions = find_omitted_relevant_memories(
        state.conn,
        targets=targets,
        limit=4,
        view=state_visibility_view(state),
    )
    changed_health = memory_projection_snapshot_change(
        state.conn,
        projection_snapshot,
    )
    if changed_health is not None:
        state.memory_summaries = []
        state.memory_omissions = memory_projection_change_omissions(
            state.conn,
            view=state_visibility_view(state),
            health=changed_health,
            limit=4,
        )
        projection_snapshot = memory_projection_snapshot(
            state.conn,
            changed_health,
        )
    state.memory_projection_snapshot = projection_snapshot


def memory_context_snapshot_is_current(state: Any) -> bool:
    if getattr(state, "memory_context_frozen", False):
        return True
    snapshot = getattr(state, "memory_projection_snapshot", None)
    if snapshot is None:
        if getattr(state, "memory_summaries", []):
            _invalidate_memory_context(state)
            return False
        return True
    changed_health = memory_projection_snapshot_change(state.conn, snapshot)
    if changed_health is None:
        return True
    _invalidate_memory_context(state, health=changed_health)
    return False


def _invalidate_memory_context(
    state: Any,
    *,
    health: dict[str, Any] | None = None,
) -> None:
    state.memory_summaries = []
    current_health = health or memory_projection_health(state.conn)
    state.memory_omissions = memory_projection_change_omissions(
        state.conn,
        view=state_visibility_view(state),
        health=current_health,
        limit=4,
    )
    state.plot_signals = [
        signal
        for signal in getattr(state, "plot_signals", [])
        if not memory_derived_plot_signal(signal)
    ]
    state.plot_signal_omissions = [
        signal
        for signal in getattr(state, "plot_signal_omissions", [])
        if not memory_derived_plot_signal(signal)
    ]
    state.memory_projection_snapshot = memory_projection_snapshot(
        state.conn,
        current_health,
    )
    state.memory_context_revision = int(
        getattr(state, "memory_context_revision", 0)
    ) + 1


def memory_derived_plot_signal(signal: dict[str, Any]) -> bool:
    return (
        str(signal.get("signal_type") or "") == "memory"
        or str(signal.get("id") or "").startswith("plot:memory:")
        or "memory_summaries" in (signal.get("required_section_keys") or [])
    )


def freeze_unstable_memory_context(state: Any) -> None:
    state.memory_context_frozen = True
    state.memory_summaries = []
    state.memory_omissions = [
        memory_fallback_item(
            item_id="memory:fallback:unstable-generation",
            title="Memory summaries unavailable",
            reason=(
                "memory projection changed repeatedly during context assembly; "
                "using lower-quality fallback context"
            ),
            stale_reason="projection_memory_unstable",
            evidence={"projection": "memory", "status": "stale"},
        )
    ]
    state.plot_signals = [
        signal
        for signal in getattr(state, "plot_signals", [])
        if not memory_derived_plot_signal(signal)
    ]
    state.plot_signal_omissions = [
        signal
        for signal in getattr(state, "plot_signal_omissions", [])
        if not memory_derived_plot_signal(signal)
    ]
    state.memory_projection_snapshot = None
    state.memory_context_revision = int(
        getattr(state, "memory_context_revision", 0)
    ) + 1


def active_clocks_section(state: Any) -> ContextSection:
    return ContextSection(
        key="active_clocks",
        title="Active Clocks",
        content=render_active_clocks(state.conn, view=state_visibility_view(state)),
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

    ensure_visibility_sql_functions(state.conn)
    targets = discovery_targets(state)
    view = state_visibility_view(state)
    rows: list[sqlite3.Row] = []
    if targets:
        clauses = []
        params: list[Any] = []
        for target in targets[:12]:
            clauses.append("(subject_id = ? or palette_id = ? or notes like ?)")
            params.extend([target, target, f"%{target}%"])
        rows = fetch_discovery_state_rows(
            state,
            view=view,
            where_suffix=f"and ({' or '.join(clauses)})",
            params=params,
            limit=6,
        )
    if len(rows) < 6:
        existing = {row["id"] for row in rows}
        extra = fetch_discovery_state_rows(
            state,
            view=view,
            where_suffix="",
            params=[],
            limit=6,
        )
        for row in extra:
            if row["id"] in existing:
                continue
            rows.append(row)
            existing.add(row["id"])
            if len(rows) >= 6:
                break
    state.discovery_states = rows[:6]


def discovery_visibility_clause(view: str) -> str:
    allowed = DISCOVERY_VISIBILITIES_FOR_TRUSTED if can_read_hidden(view) else DISCOVERY_VISIBILITIES_FOR_PLAYER
    values = ", ".join(f"'{item}'" for item in allowed)
    return f"and {normalized_text_sql('visibility')} in ({values})"


def discovery_fetch_limit(view: str, limit: int) -> int:
    return limit if can_read_hidden(view) else max(limit * 4, 25)


def fetch_discovery_state_rows(
    state: Any,
    *,
    view: str,
    where_suffix: str,
    params: list[Any],
    limit: int,
) -> list[sqlite3.Row]:
    page_size = discovery_fetch_limit(view, limit)
    offset = 0
    rows: list[sqlite3.Row] = []
    seen: set[str] = set()
    while len(rows) < limit:
        page = state.conn.execute(
            f"""
            select *
            from discovery_states
            where stage != 'archived'
              {discovery_visibility_clause(view)}
              {where_suffix}
            order by
              case stage when 'confirmed' then 0 when 'observed' then 1 when 'clue' then 2 else 3 end,
              evidence_count desc,
              updated_at desc,
              id desc
            limit ? offset ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        if not page:
            break
        offset += len(page)
        for row in player_safe_discovery_states(state, page):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            rows.append(row)
            if len(rows) >= limit:
                break
        if can_read_hidden(view):
            break
    return rows[:limit]


def player_safe_discovery_states(state: Any, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    if can_read_hidden(state_visibility_view(state)):
        return rows
    return [row for row in rows if not discovery_state_has_hidden_refs(state.conn, row)]


def discovery_state_has_hidden_refs(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    payload = {
        "id": row["id"],
        "subject_id": row["subject_id"],
        "palette_id": row["palette_id"],
        "notes": row["notes"],
        "confirmation_methods": row["confirmation_methods_json"],
        "source_event_ids": row["source_event_ids_json"],
    }
    identifiers = {"id": row["id"], "subject_id": row["subject_id"], "palette_id": row["palette_id"]}
    return (
        bool(find_hidden_entity_ref_tokens(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, identifiers))
        or discovery_state_has_hidden_subject(conn, row)
    )


def discovery_state_has_hidden_subject(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    if not table_exists(conn, "entities"):
        return False
    candidates: set[str] = set()
    for value in (row["subject_id"], row["palette_id"]):
        text = str(value or "").strip()
        if not text:
            continue
        candidates.add(text)
        if text.startswith("pal:"):
            candidates.add(text.removeprefix("pal:"))
    if not candidates:
        return False
    ensure_visibility_sql_functions(conn)
    placeholders = ",".join("?" for _ in candidates)
    hidden = conn.execute(
        f"""
        select 1
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id in ({placeholders})
          and (
            {normalized_text_sql("e.status")} = 'archived'
            or {player_hidden_visibility_sql("e.visibility")}
            or ({normalized_text_sql("e.type")} = 'clock'
                and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
          )
        limit 1
        """,
        sorted(candidates),
    ).fetchone()
    return hidden is not None


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
    if not memory_context_snapshot_is_current(state):
        return None
    discard_stale_memory_rows(state)
    if not state.memory_summaries:
        return None
    return ContextSection(
        key="memory_summaries",
        title="Long-Term Memory",
        content=render_memory_section(state.memory_summaries, state.conn, view=state_visibility_view(state)),
        priority=64,
        required=False,
    )


def collect_plot_signals(state: Any) -> None:
    signals: list[dict[str, Any]] = []

    for item in getattr(state, "progress_context", [])[:4]:
        progress: ProgressRecord = item["record"]
        add_plot_signal(
            signals,
            signal_id=f"plot:progress:{progress.id}",
            name=progress.entity.name if progress.entity else progress.id,
            signal_type="progress",
            reason=f"active progress can shape next narration: {item['reason']}",
            priority=76,
            source_refs=[progress.id],
            required_section_keys=["progress_context"],
        )
    for item in getattr(state, "relationships", [])[:4]:
        relationship: RelationshipRecord = item["record"]
        add_plot_signal(
            signals,
            signal_id=f"plot:relationship:{relationship.id}",
            name=relationship.id,
            signal_type="relationship",
            reason=f"relationship state can shape social framing: {item['reason']}",
            priority=72,
            source_refs=[relationship.id, relationship.source_id, relationship.target_id],
            required_section_keys=["relationships"],
        )
    for item in getattr(state, "world_settings", [])[:3]:
        row = item["row"]
        add_plot_signal(
            signals,
            signal_id=f"plot:world:{row['entity_id']}",
            name=item["name"],
            signal_type="world_setting",
            reason=f"world constraint relevant to current context: {item['reason']}",
            priority=68,
            source_refs=[row["entity_id"]],
            required_section_keys=["world_settings"],
        )
    for row in getattr(state, "discovery_states", [])[:3]:
        subject = row["subject_id"] or row["palette_id"] or row["id"]
        add_plot_signal(
            signals,
            signal_id=f"plot:discovery:{row['id']}",
            name=subject,
            signal_type="discovery",
            reason="visible clue can be recalled as an optional plot signal",
            priority=66,
            source_refs=[row["id"], subject],
            required_section_keys=["discovery_states"],
        )
    for row in getattr(state, "routes", [])[:2]:
        add_plot_signal(
            signals,
            signal_id=f"plot:route:{row['id']}",
            name=row["id"],
            signal_type="route",
            reason="route option can influence travel framing without forcing action",
            priority=58,
            source_refs=[row["id"], row["from_location_id"], row["to_location_id"]],
            required_section_keys=["routes"],
        )
    for row in getattr(state, "related_events", [])[:2]:
        add_plot_signal(
            signals,
            signal_id=f"plot:event:{row['id']}",
            name=row["title"],
            signal_type="recent_event",
            reason="recent event can inform continuity without changing facts",
            priority=56,
            source_refs=[row["id"]],
            required_section_keys=["recent_events"],
        )
    memory_rows = (
        getattr(state, "memory_summaries", [])
        if memory_context_snapshot_is_current(state)
        else []
    )
    for row in memory_rows[:3]:
        add_plot_signal(
            signals,
            signal_id=f"plot:memory:{row['id']}",
            name=row["title"],
            signal_type="memory",
            reason="visible long-term memory can inform continuity without changing facts",
            priority=54,
            source_refs=[row["id"]],
            required_section_keys=["memory_summaries"],
        )
    for row in collect_visible_rules(state)[:3]:
        add_plot_signal(
            signals,
            signal_id=f"plot:rule:{row['entity_id']}",
            name=row["name"],
            signal_type="rule",
            reason="visible rule constrains optional narration and intent handling",
            priority=70,
            source_refs=[row["entity_id"]],
        )
    for candidate in getattr(state, "palette_candidates", [])[:3]:
        entry = candidate.get("entry", {})
        palette_id = str(entry.get("id", "")).strip()
        if not palette_id:
            continue
        add_plot_signal(
            signals,
            signal_id=f"plot:palette:{palette_id}",
            name=str(entry.get("name") or palette_id),
            signal_type="palette_candidate",
            reason="visible palette candidate can serve as optional clue or color, not confirmed fact",
            priority=52,
            source_refs=[palette_id],
            required_section_keys=["palette_candidates"],
        )
    for goal in collect_visible_character_goals(state)[:3]:
        add_plot_signal(
            signals,
            signal_id=f"plot:goal:{goal['entity_id']}:{safe_signal_fragment(goal['text'])}",
            name=goal["entity_name"],
            signal_type="character_goal",
            reason=f"visible character goal can shape optional framing: {goal['text']}",
            priority=62,
            source_refs=[goal["entity_id"]],
        )
    for project in collect_visible_project_summaries(state)[:3]:
        add_plot_signal(
            signals,
            signal_id=f"plot:project:{project['id']}",
            name=project["name"],
            signal_type="project_summary",
            reason=f"visible project summary can guide continuity: {project['summary']}",
            priority=64,
            source_refs=[project["id"]],
        )
    for hint in collect_campaign_plot_hints(state)[:4]:
        add_plot_signal(
            signals,
            signal_id=f"plot:campaign:{hint['kind']}:{safe_signal_fragment(hint['id'])}",
            name=hint["name"],
            signal_type=f"campaign_{hint['kind']}",
            reason=f"campaign visible {hint['kind']} can guide optional plot continuity: {hint['text']}",
            priority=campaign_hint_priority(hint["kind"]),
            source_refs=[hint["source"]],
            detail_text=hint["text"],
        )

    ranked_signals = sorted(signals, key=lambda item: (-int(item.get("priority", 0)), str(item.get("id", ""))))
    state.plot_signals = ranked_signals[:PLOT_SIGNAL_LIMIT]
    state.plot_signal_omissions = [
        plot_signal_omission_item(signal, reason_code="over_budget")
        for signal in ranked_signals[PLOT_SIGNAL_LIMIT:]
    ]


def add_plot_signal(
    signals: list[dict[str, Any]],
    *,
    signal_id: str,
    name: str,
    signal_type: str,
    reason: str,
    priority: int,
    source_refs: list[str],
    required_section_keys: list[str] | None = None,
    detail_text: str | None = None,
) -> None:
    if any(item["id"] == signal_id for item in signals):
        return
    signals.append(
        {
            "id": signal_id,
            "kind": "plot_signal",
            "name": name,
            "signal_type": signal_type,
            "reason": reason,
            "detail_text": detail_text or "",
            "priority": priority,
            "depth": 1,
            "source_refs": source_refs,
            "required_section_keys": [key for key in (required_section_keys or []) if key],
            "provenance": {
                "collector": "plot_signals",
                "source": "plot_signals",
                "detail": "derived from visible context evidence",
                "advisory_only": True,
                "requires_storylet": False,
                "automatic_director_command": False,
            },
            "authority": {
                "advisory_only": True,
                "fact_authority": False,
                "can_tick_clocks": False,
                "can_approve_proposals": False,
            },
        }
    )


def collect_visible_rules(state: Any) -> list[sqlite3.Row]:
    if not table_exists(state.conn, "rules"):
        return []
    ensure_visibility_sql_functions(state.conn)
    view = state_visibility_view(state)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    category_matches = categories_for_submode(getattr(state, "submode", ""))
    rows = state.conn.execute(
        f"""
        select r.*, e.name, e.summary
        from rules r
        join entities e on e.id = r.entity_id
        left join clocks c on c.entity_id = e.id
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
        order by r.locked desc, r.entity_id
        limit 20
        """
    ).fetchall()
    selected: list[sqlite3.Row] = []
    text = getattr(state, "user_text", "")
    for row in rows:
        haystack = " ".join(
            str(value or "")
            for value in (row["entity_id"], row["name"], row["category"], row["scope"], row["statement"])
        )
        if row["category"] in category_matches or contains_any(text, extract_chinese_terms(haystack)):
            selected.append(row)
    return selected[:5]


def campaign_hint_priority(kind: str) -> int:
    return {
        "clue": 66,
        "light_hook": 66,
        "goal": 64,
        "project_summary": 64,
        "hint": 60,
    }.get(kind, 58)


def collect_visible_character_goals(state: Any) -> list[dict[str, str]]:
    if not table_exists(state.conn, "characters"):
        return []
    ensure_visibility_sql_functions(state.conn)
    view = state_visibility_view(state)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = state.conn.execute(
        f"""
        select e.id, e.name, c.goals_json
        from characters c
        join entities e on e.id = c.entity_id
        where {entity_not_archived_sql("e")}
          {visibility_clause}
        order by c.trust desc, e.name
        limit 20
        """
    ).fetchall()
    targets = set(target_search_values(state))
    goals: list[dict[str, str]] = []
    for row in rows:
        for goal in parse_json(row["goals_json"], []):
            text = str(goal or "").strip()
            if not text:
                continue
            if not can_read_hidden(view) and (
                find_hidden_entity_ref_tokens(state.conn, text)
                or find_hidden_entity_id_substrings(state.conn, {"goal": text})
            ):
                continue
            if row["id"] in targets or row["name"] in targets or contains_any(getattr(state, "user_text", ""), [text]):
                goals.append({"entity_id": row["id"], "entity_name": row["name"], "text": trim_inline(text, 100)})
    return goals


def collect_visible_project_summaries(state: Any) -> list[dict[str, str]]:
    ensure_visibility_sql_functions(state.conn)
    view = state_visibility_view(state)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = state.conn.execute(
        f"""
        select e.id, e.name, e.summary, e.details_json
        from entities e
        left join clocks c on c.entity_id = e.id
        where {entity_not_archived_sql("e")}
          and {normalized_text_sql("e.type")} = 'project'
          {visibility_clause}
          {entity_subtype_visibility_sql(view, "e", "c")}
        order by e.name
        limit 20
        """
    ).fetchall()
    targets = set(target_search_values(state))
    result: list[dict[str, str]] = []
    for row in rows:
        details = parse_json(row["details_json"], {})
        summary = str(row["summary"] or details.get("summary") or details.get("next_steps") or "").strip()
        if not summary:
            continue
        if not can_read_hidden(view) and (
            find_hidden_entity_ref_tokens(state.conn, {"summary": summary, "details": details})
            or find_hidden_entity_id_substrings(state.conn, {"id": row["id"], "summary": summary, "details": details})
        ):
            continue
        if row["id"] in targets or row["name"] in targets or contains_any(getattr(state, "user_text", ""), [row["name"], summary]):
            result.append({"id": row["id"], "name": row["name"], "summary": trim_inline(summary, 120)})
    return result


def collect_campaign_plot_hints(state: Any) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    config = getattr(state.campaign, "config", {})
    collect_plot_hints_from_mapping(hints, config, "campaign.yaml")
    for key in ("plot_hints", "light_hooks", "goals", "clues", "project_summaries"):
        for path in getattr(state.campaign, "content_files")(key):
            try:
                data = load_yaml_file(path)
            except (FileNotFoundError, ValueError, TypeError):
                continue
            collect_plot_hints_from_mapping(hints, data, getattr(state.campaign, "display_path")(path))
    view = state_visibility_view(state)
    if not can_read_hidden(view):
        hints = [
            hint
            for hint in hints
            if not is_player_hidden_visibility(hint.get("visibility"))
            and not find_hidden_entity_ref_tokens(state.conn, hint)
            and not find_hidden_entity_id_substrings(state.conn, hint)
        ]
    text = getattr(state, "user_text", "")
    targets = set(target_search_values(state))
    relevant: list[dict[str, str]] = []
    for hint in hints:
        haystack = " ".join(str(hint.get(key, "")) for key in ("id", "name", "text", "source"))
        if any(target and target in haystack for target in targets) or contains_any(text, extract_chinese_terms(haystack)):
            relevant.append(hint)
    return relevant[:8]


def collect_plot_hints_from_mapping(hints: list[dict[str, str]], data: Any, source: str) -> None:
    if not isinstance(data, dict):
        return
    for key, kind in (
        ("plot_hints", "hint"),
        ("light_hooks", "light_hook"),
        ("hooks", "light_hook"),
        ("goals", "goal"),
        ("clues", "clue"),
        ("project_summaries", "project_summary"),
    ):
        collect_plot_hints_from_value(hints, data.get(key), kind, source)
    for nested_key in ("campaign", "story", "plot", "metadata"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            collect_plot_hints_from_mapping(hints, nested, source)


def collect_plot_hints_from_value(hints: list[dict[str, str]], value: Any, kind: str, source: str) -> None:
    if is_plot_hint_object(value):
        entries = [(str(value.get("id") or value.get("name") or value.get("title") or 0), value)]
    elif isinstance(value, dict):
        entries = list(value.items())
    elif isinstance(value, list):
        entries = list(enumerate(value))
    else:
        entries = []
    for index, (entry_key, item) in enumerate(entries):
        stable_hint_id = safe_signal_fragment(f"{source}:{kind}:{entry_key}")
        if isinstance(item, dict):
            text = str(item.get("summary") or item.get("text") or item.get("description") or item.get("goal") or item.get("clue") or "").strip()
            name = str(item.get("name") or item.get("title") or item.get("id") or f"{kind} {index + 1}").strip()
            visibility = str(item.get("visibility") or item.get("audience") or "known")
            hint_id = str(item.get("id") or stable_hint_id)
        else:
            text = str(item or "").strip()
            name = f"{kind} {index + 1}"
            visibility = "known"
            hint_id = stable_hint_id
        if not text:
            continue
        hints.append(
            {
                "id": hint_id,
                "kind": kind,
                "name": name,
                "text": trim_inline(text, 140),
                "visibility": visibility,
                "source": source,
            }
        )


def is_plot_hint_object(value: Any) -> bool:
    return isinstance(value, dict) and bool(PLOT_HINT_OBJECT_FIELDS.intersection(str(key) for key in value))


def plot_signal_omission_item(signal: dict[str, Any], *, reason_code: str) -> dict[str, Any]:
    return {
        "id": signal["id"],
        "kind": "plot_signal",
        "name": signal.get("name", signal["id"]),
        "reason": f"plot signal omitted: {reason_code}",
        "reason_code": reason_code,
        "priority": signal.get("priority", 0),
        "depth": signal.get("depth", 1),
        "source_refs": list(signal.get("source_refs", [])),
        "required_section_keys": list(signal.get("required_section_keys", [])),
    }


def plot_signal_omitted_items(state: Any) -> list[dict[str, Any]]:
    return list(getattr(state, "plot_signal_omissions", []))


def plot_signals_section(state: Any) -> ContextSection | None:
    if not state.plot_signals:
        return None
    return ContextSection(
        key="plot_signals",
        title="Plot Progression Signals",
        content=render_plot_signals(state),
        priority=82 if state.mode == "action" else 58,
        required=False,
    )


def render_plot_signals(state: Any) -> str:
    lines = [
        "### 剧情推进信号",
        "",
        "这些是可见上下文中的 advisory signals，不是 mandatory storylets、automatic director commands 或事实写入授权。",
        "",
        "| Signal | Type | Reason | Source refs |",
        "|--------|------|--------|-------------|",
    ]
    for signal in state.plot_signals:
        refs = ", ".join(f"`{markdown_code_text(ref)}`" for ref in signal.get("source_refs", [])[:4] if ref)
        lines.append(
            f"| `{markdown_code_text(signal['id'])}` | {markdown_table_cell(signal['signal_type'], 60)} | "
            f"{markdown_table_cell(signal['reason'], 120)} | {refs or 'n/a'} |"
        )
    return "\n".join(lines)


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


def relationship_loaded_items(state: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": item["record"].id,
            "kind": "relationship",
            "name": item["record"].id,
            "reason": item["reason"],
            "priority": item["priority"],
            "depth": item["depth"],
        }
        for item in state.relationships
    ]


def relationship_omitted_items(state: Any) -> list[dict[str, Any]]:
    return list(getattr(state, "relationship_omissions", []))


def progress_loaded_items(state: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": item["record"].id,
            "kind": "progress",
            "name": item["record"].entity.name if item["record"].entity else item["record"].id,
            "reason": item["reason"],
            "priority": item["priority"],
            "depth": item["depth"],
        }
        for item in state.progress_context
    ]


def progress_omitted_items(state: Any) -> list[dict[str, Any]]:
    return list(getattr(state, "progress_omissions", []))


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
    if not memory_context_snapshot_is_current(state):
        return []
    discard_stale_memory_rows(state)
    items: list[dict[str, Any]] = []
    view = state_visibility_view(state)
    for row in state.memory_summaries:
        freshness = memory_row_freshness(state.conn, row, view=view)
        items.append(
            {
            "id": row["id"],
            "kind": "memory",
            "name": row["title"],
            "reason": "long-term memory relevant to loaded entities",
            "priority": 64,
            "depth": 0,
            "provenance": {
                "collector": "memory_summaries",
                "source": "memory_summaries",
                "source_event_ids": memory_row_source_event_ids(row, conn=state.conn, view=view),
                "source_turn_ids": memory_row_source_turn_ids(row, conn=state.conn, view=view),
                "summary_type": memory_row_summary_type(row),
            },
            "visibility": {
                "mode": state_visibility_view(state),
                "record_visibility_mode": row_value(row, "visibility_mode", "player"),
                "policy": "memory lookup receives context visibility view",
            },
            "freshness": {
                "status": freshness["status"],
                "reason": freshness["reason"],
                "freshness_turn_id": memory_row_freshness_turn_id(state.conn, row, view=view) or None,
                "evidence": memory_row_freshness_evidence(row, conn=state.conn, view=view),
            },
            "authority": memory_row_authority(row),
        }
        )
    return items


def discard_stale_memory_rows(state: Any) -> None:
    view = state_visibility_view(state)
    retained: list[sqlite3.Row | dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []
    existing_omission_ids = {
        str(row.get("id") or "")
        for row in getattr(state, "memory_omissions", [])
        if isinstance(row, dict)
    }
    for row in getattr(state, "memory_summaries", []):
        freshness = memory_row_freshness(state.conn, row, view=view)
        if freshness["status"] != "stale":
            retained.append(row)
            continue
        stale_row = dict(row)
        stale_row["freshness_status"] = "stale"
        stale_row["stale_reason"] = (
            freshness["reason"]
            if can_read_hidden(view)
            else player_safe_memory_reason(freshness["reason"])
        )
        if str(stale_row.get("id") or "") not in existing_omission_ids:
            stale_rows.append(stale_row)
    if len(retained) == len(getattr(state, "memory_summaries", [])):
        return
    state.memory_summaries = retained
    state.memory_omissions = [
        *getattr(state, "memory_omissions", []),
        *stale_rows,
    ]
    state.memory_context_revision = int(
        getattr(state, "memory_context_revision", 0)
    ) + 1


def memory_omitted_items(state: Any) -> list[dict[str, Any]]:
    memory_context_snapshot_is_current(state)
    items: list[dict[str, Any]] = []
    view = state_visibility_view(state)
    hidden_signal_added = False
    for omission_index, row in enumerate(getattr(state, "memory_omissions", [])):
        raw_reason = str(row.get("stale_reason") or row.get("reason") or "memory summary omitted")
        record_visibility_mode = str(row.get("visibility_mode") or "").strip().lower()
        hidden_sensitive = not can_read_hidden(view) and (
            record_visibility_mode != "player"
            or memory_row_has_hidden_refs(state.conn, row)
        )
        if hidden_sensitive and hidden_signal_added:
            continue
        hidden_signal_added = hidden_signal_added or hidden_sensitive
        reason = player_safe_memory_reason(raw_reason) if not can_read_hidden(view) else raw_reason
        if hidden_sensitive:
            reason = "memory_summary_omitted"
        safe_row_id = safe_memory_summary_id(row.get("id")) or (
            f"memory:omitted:unverifiable:{omission_index}"
        )
        item_id = "memory:omitted:hidden-sensitive" if hidden_sensitive else safe_row_id
        raw_name = row.get("title", safe_row_id)
        item_name = (
            "Memory summary omitted"
            if hidden_sensitive or not isinstance(raw_name, str)
            else raw_name
        )
        source_event_ids = (
            [] if hidden_sensitive else memory_row_source_event_ids(row, conn=state.conn, view=view)
        )
        source_turn_ids = (
            [] if hidden_sensitive else memory_row_source_turn_ids(row, conn=state.conn, view=view)
        )
        freshness_evidence = (
            {}
            if hidden_sensitive
            else memory_row_freshness_evidence(row, conn=state.conn, view=view)
        )
        items.append(
            {
                "id": item_id,
                "kind": "memory",
                "source": "memory_summaries",
                "name": item_name,
                "reason": reason,
                "priority": 64,
                "depth": 0,
                "provenance": {
                    "collector": "memory_summaries",
                    "source": "memory_summaries",
                    "source_event_ids": source_event_ids,
                    "source_turn_ids": source_turn_ids,
                    "summary_type": (
                        "deterministic_fallback"
                        if hidden_sensitive
                        else memory_row_summary_type(row)
                    ),
                },
                "visibility": {
                    "mode": view,
                    "record_visibility_mode": (
                        "player"
                        if hidden_sensitive
                        else row.get("visibility_mode", "player")
                    ),
                    "policy": "player-safe omitted memory evidence is sanitized",
                },
                "freshness": {
                    "status": (
                        "fallback"
                        if hidden_sensitive
                        else memory_freshness_status(
                            row.get("freshness_status"),
                            default="stale",
                        )
                    ),
                    "reason": reason,
                    "freshness_turn_id": (
                        None
                        if hidden_sensitive
                        else memory_row_freshness_turn_id(state.conn, row, view=view) or None
                    ),
                    "evidence": freshness_evidence,
                },
                "authority": (
                    {
                        "authority": "derived_context",
                        "fact_authority": False,
                        "fact_source": "data/game.sqlite",
                        "summary_overrides_facts": False,
                    }
                    if hidden_sensitive
                    else memory_row_authority(row)
                ),
                "player_safe_signal": "memory_summaries" if hidden_sensitive else safe_row_id,
                "player_safe_reason": reason if hidden_sensitive else row.get("player_safe_reason"),
                "budget": {
                    "included": False,
                    "behavior": "memory summaries are optional; stale or unavailable rows fall back to recent events/context",
                    "priority": 64,
                    "estimated_tokens": None,
                    "reason": reason,
                },
            }
        )
    return items


def plot_signal_loaded_items(state: Any) -> list[dict[str, Any]]:
    return list(getattr(state, "plot_signals", []))


DEFAULT_CONTEXT_COLLECTORS = [
    ContextCollector(
        name="active_clocks",
        source="active_clocks",
        visibility="query filters clocks and entity rows by context view",
        provenance="clocks joined to entities via render_active_clocks",
        budget_behavior="required for action mode, otherwise section priority 75",
        section=active_clocks_section,
    ),
    ContextCollector(
        name="relationships",
        source="relationships",
        visibility="relationship access contract filters relationship and endpoints by context view",
        provenance="relationship_access list_relationships scoped by loaded entity endpoints",
        budget_behavior="optional section priority 73/83; relationship item evidence follows section budget",
        collect=collect_relationships,
        section=relationships_section,
        loaded_items=relationship_loaded_items,
        omitted_items=relationship_omitted_items,
    ),
    ContextCollector(
        name="progress_context",
        source="progress_context",
        visibility="progress access contract filters clock entity and side-table visibility by context view",
        provenance="progress_access list_progress scoped by loaded targets, action submode, and active tracks",
        budget_behavior="optional section priority 74/84; progress item evidence follows section budget",
        collect=collect_progress_context,
        section=progress_context_section,
        loaded_items=progress_loaded_items,
        omitted_items=progress_omitted_items,
    ),
    ContextCollector(
        name="routes",
        source="routes",
        visibility="route endpoint entities filtered by context view",
        provenance="routes joined through visible current and destination locations",
        budget_behavior="optional section priority 72",
        collect=collect_routes,
        section=routes_section,
        loaded_items=route_loaded_items,
    ),
    ContextCollector(
        name="palettes",
        source="palettes",
        visibility="palette context redacts hidden entity references in player view",
        provenance="campaign palette suggestions scoped by action and location",
        budget_behavior="optional section priority 82, promoted when palette preservation is required",
        collect=collect_palettes,
        section=palettes_section,
    ),
    ContextCollector(
        name="discovery_states",
        source="discovery_states",
        visibility="only hinted or known non-archived discovery rows in player view",
        provenance="discovery_states table filtered by action/query targets",
        budget_behavior="optional section priority 76, promoted when palette preservation is required",
        collect=collect_discovery_states,
        section=discovery_states_section,
        loaded_items=discovery_loaded_items,
    ),
    ContextCollector(
        name="world_settings",
        source="world_settings",
        visibility="world setting and backing entity visibility filtered by context view",
        provenance="world_settings joined to entities and related clocks",
        budget_behavior="required only for direct world-setting query, otherwise priority 68/80",
        collect=collect_world_settings,
        section=world_settings_section,
        loaded_items=world_setting_loaded_items,
    ),
    ContextCollector(
        name="world_settings_core",
        source="world_settings_core",
        visibility="inherits filtered world_settings selection",
        provenance="compact summary derived from selected world_settings rows",
        budget_behavior="required for action mode when world settings are selected",
        section=world_settings_compact_section,
    ),
    ContextCollector(
        name="recent_events",
        source="recent_events",
        visibility="event text is redacted for player view before rendering",
        provenance="events table selected by loaded context targets and recency",
        budget_behavior="optional section priority 56/70",
        collect=collect_related_history,
        section=recent_events_section,
        loaded_items=event_loaded_items,
    ),
    ContextCollector(
        name="memory_summaries",
        source="memory_summaries",
        visibility="memory lookup receives context visibility view",
        provenance="memory_summaries selected by loaded context targets",
        budget_behavior="optional section priority 64",
        collect=collect_memory_summaries,
        section=memory_summaries_section,
        loaded_items=memory_loaded_items,
        omitted_items=memory_omitted_items,
    ),
    ContextCollector(
        name="plot_signals",
        source="plot_signals",
        visibility="derived only from already player-visible context evidence for the selected view",
        provenance="non-authoritative synthesis from visible relationship, progress, world, discovery, route, event, and memory context",
        budget_behavior="optional section priority 82 for action, 58 for query; advisory-only plot signal evidence follows section budget",
        collect=collect_plot_signals,
        section=plot_signals_section,
        loaded_items=plot_signal_loaded_items,
        omitted_items=plot_signal_omitted_items,
    ),
]


def render_active_clocks(conn: sqlite3.Connection, *, view: str = "player") -> str:
    should_redact = not can_read_hidden(view)
    progress_rows = [
        progress
        for progress in list_progress(conn, view=view, statuses="active")
        if progress_is_active(progress)
        and reason_code_for_progress(conn, progress, view=view) is None
        and (can_read_hidden(view) or not progress_has_hidden_refs(conn, progress))
    ][:10]
    lines = ["### 活跃进度钟", ""]
    if not progress_rows:
        lines.append("- 无")
        return "\n".join(lines)
    for progress in progress_rows:
        filled = int(progress.segments_filled)
        total = int(progress.segments_total)
        bar = "■" * filled + "□" * max(total - filled, 0)
        lines.append(
            f"- `{progress.id}` {progress.entity.name if progress.entity else progress.id}："
            f"{bar} {filled}/{total}（{progress.visibility}）"
        )
        if progress.summary:
            summary = redact_hidden_entity_refs(conn, progress.summary) if should_redact else progress.summary
            summary = summary or ""
            lines.append(f"  - {trim_inline(summary, 100)}")
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
    view = state_visibility_view(state)
    should_redact = not can_read_hidden(view)
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
        summary = row["summary"] or ""
        name = item["name"]
        if should_redact:
            content = redact_hidden_entity_refs(state.conn, content)
            linked_rules = redact_hidden_entity_refs(state.conn, linked_rules)
            linked_clocks = redact_hidden_entity_refs(state.conn, linked_clocks)
            summary = redact_hidden_entity_refs(state.conn, summary) or ""
            name = redact_hidden_entity_refs(state.conn, name) or item["name"]
        lines.extend(
            [
                f"#### `{row['entity_id']}` {name}",
                "",
                f"- 召回原因：{item['reason']}",
                f"- 分类：{row['category']}；范围：{row['scope']}；可见性：{row['visibility']}",
                f"- 摘要：{trim_inline(summary, 180)}",
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
    view = state_visibility_view(state)
    should_redact = not can_read_hidden(view)
    lines = ["### 必要世界约束", ""]
    for item in state.world_settings:
        row = item["row"]
        linked_rules = parse_json(row["linked_rules_json"], [])
        if should_redact:
            linked_rules = redact_hidden_entity_refs(state.conn, linked_rules)
        rule_suffix = f"；规则 {', '.join(str(value) for value in linked_rules[:3])}" if linked_rules else ""
        name = item["name"]
        summary = row["summary"] or ""
        if should_redact:
            name = redact_hidden_entity_refs(state.conn, name) or item["name"]
            summary = redact_hidden_entity_refs(state.conn, summary) or ""
        lines.append(
            f"- `{row['entity_id']}` {name}：{trim_inline(summary, 110)}{rule_suffix}"
        )
    lines.append("- 上述内容是结算边界；完整设定区若因预算省略，仍必须遵守这些摘要和关联规则。")
    return "\n".join(lines)


def render_history_events(state: Any) -> str:
    view = state_visibility_view(state)
    rows = [*state.related_events, *state.general_events]
    if not rows:
        return ""
    lines = ["### 相关/近期事件", ""]
    if state.related_events:
        lines.append("#### 相关事件")
        for row in reversed(state.related_events):
            lines.append(render_event_line(row, state.conn, view=view))
    if state.general_events:
        if state.related_events:
            lines.extend(["", "#### 近期事件"])
        for row in reversed(state.general_events):
            lines.append(render_event_line(row, state.conn, view=view))
    return "\n".join(lines)


def render_event_line(row: sqlite3.Row, conn: sqlite3.Connection | None = None, *, view: str = "player") -> str:
    time = f"（{row['game_time']}）" if row["game_time"] else ""
    title = row["title"]
    summary = row["summary"]
    if conn is not None and not can_read_hidden(view):
        title = redact_hidden_entity_refs(conn, title) or ""
        summary = redact_hidden_entity_refs(conn, summary) or ""
    return f"- `{row['turn_id']}` `{row['id']}` {title}{time}：{trim_inline(summary, 120)}"


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
    view = state_visibility_view(state)
    if not can_read_hidden(view):
        return find_player_safe_related_events(state, clauses=clauses, params=params)
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


def find_player_safe_related_events(
    state: Any,
    *,
    clauses: list[str],
    params: list[str],
) -> list[sqlite3.Row]:
    limit = max(state.max_events, 0)
    if limit <= 0:
        return []
    page_size = max(limit * 4, 25)
    offset = 0
    result: list[sqlite3.Row] = []
    seen: set[str] = set()
    while len(result) < limit:
        rows = state.conn.execute(
            f"""
            select id, turn_id, type, title, summary, game_time, payload_json, created_at
            from events
            where ({' or '.join(clauses)})
            order by
              case type when 'import' then 1 else 0 end,
              created_at desc,
              id desc
            limit ? offset ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            if history_event_has_hidden_refs(state.conn, row):
                continue
            result.append(row)
            if len(result) >= limit:
                break
    return result[:limit]


def find_general_recent_events(
    state: Any,
    limit: int,
    *,
    exclude_ids: set[str],
) -> list[sqlite3.Row]:
    if not can_read_hidden(state_visibility_view(state)):
        return find_player_safe_general_recent_events(state, limit, exclude_ids=exclude_ids)
    fetch_limit = max(limit + len(exclude_ids), (limit + len(exclude_ids)) * 4)
    rows = state.conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from events
        where type not in ('import', 'campaign_seeded')
          and id != 'event:seed'
        order by created_at desc, id desc
        limit ?
        """,
        (fetch_limit,),
    ).fetchall()
    result = [row for row in rows if row["id"] not in exclude_ids]
    return result[:limit]


def find_player_safe_general_recent_events(
    state: Any,
    limit: int,
    *,
    exclude_ids: set[str],
) -> list[sqlite3.Row]:
    if limit <= 0:
        return []
    page_size = max(limit * 4, 25)
    offset = 0
    result: list[sqlite3.Row] = []
    seen: set[str] = set(exclude_ids)
    while len(result) < limit:
        rows = state.conn.execute(
            """
            select id, turn_id, type, title, summary, game_time, payload_json, created_at
            from events
            where type not in ('import', 'campaign_seeded')
              and id != 'event:seed'
            order by created_at desc, id desc
            limit ? offset ?
            """,
            (page_size, offset),
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            if history_event_has_hidden_refs(state.conn, row):
                continue
            result.append(row)
            if len(result) >= limit:
                break
    return result[:limit]


def player_safe_history_events(state: Any, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    if can_read_hidden(state_visibility_view(state)):
        return rows
    return [row for row in rows if not history_event_has_hidden_refs(state.conn, row)]


def history_event_has_hidden_refs(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    payload = {
        "title": row["title"],
        "summary": row["summary"],
        "payload": row["payload_json"],
    }
    identifiers = {
        "id": row["id"],
        "turn_id": row["turn_id"],
        "game_time": row["game_time"],
    }
    return (
        bool(find_hidden_entity_ref_tokens(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, identifiers))
    )


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


def location_parent_id(conn: sqlite3.Connection, location_id: str | None, *, view: str = "player") -> str | None:
    if not location_id:
        return None
    row = conn.execute("select parent_id from locations where entity_id = ?", (location_id,)).fetchone()
    parent_id = row["parent_id"] if row and row["parent_id"] else None
    if not parent_id:
        return None
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_clause = entity_subtype_visibility_sql(view, "e", "c")
    parent = conn.execute(
        f"""
        select e.id
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_clause}
        """,
        (parent_id,),
    ).fetchone()
    return str(parent_id) if parent else None


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone()
    return bool(row)


def active_clock_ids_for_world_settings(conn: sqlite3.Connection, *, view: str = "player") -> list[str]:
    if not table_exists(conn, "clocks"):
        return []
    ensure_visibility_sql_functions(conn)
    clock_visibility_clause = clock_visibility_sql(view, "c")
    entity_visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    return [
        row["entity_id"]
        for row in conn.execute(
            f"""
            select c.entity_id
            from clocks c
            join entities e on e.id = c.entity_id
            where {entity_not_archived_sql("e")}
              and {normalized_text_sql("e.status")} = 'active'
              and c.segments_filled < c.segments_total
              {entity_visibility_clause}
              {clock_visibility_clause}
              {subtype_visibility_clause}
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


def jsonish_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def markdown_table_cell(value: Any, limit_chars: int) -> str:
    text = trim_inline(str(value or ""), limit_chars)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\n", " ")
    text = text.replace("`", "\\`")
    return text or "n/a"


def markdown_code_text(value: Any) -> str:
    return str(value or "").replace("`", "\\`").replace("|", "\\|").replace("\n", " ")


def safe_signal_fragment(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip()).strip("-._:")
    return text[:48] or "hint"


def trim_inline(text: str | None, limit_chars: int) -> str:
    raw = str(text or "")
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw if len(raw) <= limit_chars else raw[: max(0, limit_chars - 1)] + "…"
