from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..db import (
    entity_subtype_visibility_sql,
    get_meta,
    get_player_entity_id,
    player_candidate_matches_redacted_text,
    player_query_contains_hidden_ref,
    world_setting_entity_join_and_clause,
)
from ..render import parse_json
from ..visibility import (
    can_read_hidden,
    context_visibility_view,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalized_text_sql,
    player_hidden_visibility_sql,
)


ENTITY_ID_PATTERN = re.compile(
    r"\b(?:pc|char|loc|item|mat|plant|species|faction|threat|rule|clock|project|recipe|plot|ref):[A-Za-z0-9_.-]+"
)

AMBIGUOUS_TERMS = ["那个", "这个", "它", "那边", "这里", "刚才"]
AMBIGUOUS_STOP_TERMS = [
    "是什么",
    "是谁",
    "在哪",
    "哪里",
    "什么",
    "怎么",
    "如何",
    "一下",
    "看看",
    "查看",
    "看",
    "查询",
    "说明",
    "我",
    "想",
    "要",
    "的",
]
QUERY_STOP_WORDS = {
    "what",
    "a",
    "an",
    "can",
    "did",
    "does",
    "is",
    "are",
    "was",
    "were",
    "in",
    "of",
    "to",
    "at",
    "the",
    "and",
    "for",
    "me",
    "with",
    "that",
    "this",
    "tell",
    "you",
    "please",
    "show",
    "look",
    "around",
    "see",
    "prove",
    "proved",
    "about",
    "where",
    "which",
    "who",
    "how",
    "查看",
    "看",
    "查",
    "问",
    "找",
    "查询",
    "看看",
    "说明",
    "是什么",
    "是谁",
    "在哪",
    "哪里",
    "什么",
    "怎么",
    "如何",
    "一下",
}
CJK_REQUEST_PREFIXES = ("查看", "查询", "看看", "说明", "看", "查", "问", "找")
AMBIGUOUS_SPLIT_PATTERN = re.compile(r"[\s,，。！？!?、；;：:（）()【】\[\]{}<>《》\"']+")
AMBIGUOUS_CJK_OR_WORD_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_.:-]{1,}")


@dataclass
class EntityHit:
    id: str
    type: str
    name: str
    summary: str
    status: str
    location_id: str | None
    owner_id: str | None
    reason: str
    priority: int
    depth: int = 0


def state_visibility_view(state: Any) -> str:
    return getattr(state, "visibility_view", None) or context_visibility_view(getattr(state, "mode", None))


def entity_visibility_parts(
    conn: sqlite3.Connection,
    view: str,
    *,
    entity_alias: str = "e",
    clock_alias: str = "c",
    setting_alias: str = "ws",
) -> tuple[str, str, str, str]:
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql(view, entity_alias)
    subtype_visibility_clause = entity_subtype_visibility_sql(view, entity_alias, clock_alias)
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias=entity_alias,
        setting_alias=setting_alias,
    )
    return visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause


def world_setting_hidden_condition(conn: sqlite3.Connection, *, entity_alias: str = "e", setting_alias: str = "ws") -> str:
    if table_exists(conn, "world_settings"):
        visibility_expr = f"coalesce({setting_alias}.visibility, '')"
        return (
            f"({normalized_text_sql(f'{entity_alias}.type')} = 'world_setting' "
            f"and ({setting_alias}.entity_id is null "
            f"or {normalized_text_sql(visibility_expr)} not in ('known', 'hinted')))"
        )
    return f"{normalized_text_sql(f'{entity_alias}.type')} = 'world_setting'"


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name = ?", (table,)).fetchone()
    return bool(row)


def player_context_query_is_hidden(conn: sqlite3.Connection, text: str, *, view: str) -> bool:
    return not can_read_hidden(view) and player_query_contains_hidden_ref(conn, text, view=view)


def filter_player_candidate_rows(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    term: str,
    *,
    view: str,
) -> list[sqlite3.Row]:
    if can_read_hidden(view):
        return rows
    return [row for row in rows if player_candidate_matches_redacted_text(conn, row, term, view=view)]


def filter_player_candidate_rows_any(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    terms: list[str],
    *,
    view: str,
) -> list[sqlite3.Row]:
    if can_read_hidden(view):
        return rows
    usable_terms = [term for term in terms if term.strip() and not player_context_query_is_hidden(conn, term, view=view)]
    return [
        row
        for row in rows
        if any(player_candidate_matches_redacted_text(conn, row, term, view=view) for term in usable_terms)
    ]


def alias_from_reason(row: sqlite3.Row) -> str:
    reason = str(row["_reason"] or "") if "_reason" in row.keys() else ""
    return reason.split(": ", 1)[1] if ": " in reason else ""


def collect_entity_hits(state: Any) -> None:
    hits: dict[str, EntityHit] = {}
    text = state.user_text
    view = state_visibility_view(state)

    for row in find_explicit_entity_matches(state.conn, text, view=view):
        add_hit(
            hits,
            EntityHit(
                id=row["id"],
                type=row["type"],
                name=row["name"],
                summary=row["summary"] or "",
                status=row["status"],
                location_id=row["location_id"],
                owner_id=row["owner_id"],
                reason=row["_reason"],
                priority=90 if row["_reason"].startswith("name") or row["_reason"].startswith("alias") else 80,
            ),
        )

    if not hits and state.mode == "query":
        for row in find_candidate_entities(state.conn, text, limit=5, view=view):
            add_hit(
                hits,
                EntityHit(
                    id=row["id"],
                    type=row["type"],
                    name=row["name"],
                    summary=row["summary"] or "",
                    status=row["status"],
                    location_id=row["location_id"],
                    owner_id=row["owner_id"],
                    reason="candidate search",
                    priority=70,
                ),
            )

    if contains_any(text, AMBIGUOUS_TERMS) and not hits:
        state.ambiguous_hits = ambiguous_candidates(state.conn, text, view=view)
        if state.ambiguous_hits:
            state.needs_user_confirmation.append("存在指代词，需要确认目标实体。")

    state.entity_hits = sort_hits(hits.values())


def apply_semantic_entity_hints(state: Any) -> None:
    suggestion = state.semantic_suggestion or {}
    labels = dedupe_texts([*suggestion.get("targets", []), *suggestion.get("entities_mentioned", [])])
    if not labels:
        return

    hits = {hit.id: hit for hit in state.entity_hits}
    view = state_visibility_view(state)
    for label in labels[:10]:
        rows = resolve_exact_entity_label(state.conn, label, view=view)
        exact = bool(rows)
        if not rows:
            rows = find_candidate_entities(state.conn, label, limit=2, view=view)
        if not exact:
            state.semantic_alias_gaps.append(
                {
                    "label": label,
                    "status": "candidate_only" if rows else "unresolved",
                    "candidates": [
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "type": row["type"],
                        }
                        for row in rows[:3]
                    ],
                    "suggestion": "补充实体别名或确认该说法不是当前事实实体。",
                }
            )
        for row in rows[:3]:
            reason = f"candidate semantic ai: {label}" if exact else f"semantic ai candidate: {label}"
            priority = 64 if exact else 45
            add_hit(
                hits,
                EntityHit(
                    id=row["id"],
                    type=row["type"],
                    name=row["name"],
                    summary=row["summary"] or "",
                    status=row["status"],
                    location_id=row["location_id"],
                    owner_id=row["owner_id"],
                    reason=reason,
                    priority=priority,
                ),
            )
    state.entity_hits = sort_hits(hits.values())


def expand_related_entities(state: Any) -> None:
    hits = {hit.id: hit for hit in state.entity_hits}
    current_location_id = get_meta(state.conn).get("current_location_id")
    maybe_add_entity(state, hits, current_location_id, "current location", 100, depth=0)
    player_entity_id = state.campaign.player_entity_id
    maybe_add_entity(state, hits, player_entity_id, "player character", 100, depth=0)

    queue = list(hits.values())
    processed: set[str] = set()
    while queue:
        hit = queue.pop(0)
        if hit.id in processed:
            continue
        processed.add(hit.id)
        if hit.location_id and state.mode == "action":
            added = maybe_add_entity(state, hits, hit.location_id, f"location of {hit.id}", 75, depth=hit.depth + 1)
            if added:
                queue.append(added)
        if hit.owner_id and state.mode == "query":
            added = maybe_add_entity(state, hits, hit.owner_id, f"owner of {hit.id}", 55, depth=hit.depth + 1)
            if added:
                queue.append(added)
        if hit.type == "character" and hit.id != player_entity_id:
            species_id = character_species_id(state.conn, hit.id)
            if species_id:
                added = maybe_add_entity(state, hits, species_id, f"species of {hit.id}", 65, depth=hit.depth + 1)
                if added:
                    queue.append(added)
        for linked_id, reason, priority in linked_entity_ids(state.conn, hit, state):
            added = maybe_add_entity(state, hits, linked_id, reason, priority, depth=hit.depth + 1)
            if added:
                queue.append(added)

    if state.submode == "combat":
        maybe_add_entity(state, hits, "rule:player-agency", "combat requires player agency boundary", 85, depth=1)
        maybe_add_entity(state, hits, "rule:monster-tier", "combat threat tier rule", 75, depth=1)
    elif state.mode == "action":
        maybe_add_entity(state, hits, "rule:player-agency", "action requires player agency boundary", 75, depth=1)

    state.entity_hits = sort_hits(hits.values())


def maybe_add_entity(
    state: Any,
    hits: dict[str, EntityHit],
    entity_id: str | None,
    reason: str,
    priority: int,
    *,
    depth: int,
) -> EntityHit | None:
    if not entity_id or entity_id in hits or depth > state.max_depth:
        return None
    view = state_visibility_view(state)
    visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
        state.conn,
        view,
    )
    row = state.conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.id = ?
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        """,
        (entity_id,),
    ).fetchone()
    if not row:
        return None
    hit = EntityHit(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        summary=row["summary"] or "",
        status=row["status"],
        location_id=row["location_id"],
        owner_id=row["owner_id"],
        reason=reason,
        priority=priority,
        depth=depth,
    )
    hits[entity_id] = hit
    return hit


def resolve_exact_entity_label(
    conn: sqlite3.Connection,
    label: str,
    *,
    view: str = "player",
) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    stripped = label.strip()
    if not stripped:
        return rows
    visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
        conn,
        view,
    )
    rows.extend(
        conn.execute(
            f"""
            select e.*
            from entities e
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where {entity_not_archived_sql("e")}
              {visibility_clause}
              {subtype_visibility_clause}
              {world_setting_visibility_clause}
              and (e.id = ? or e.name = ?)
            order by e.type, e.name
            limit 6
            """,
            (stripped, stripped),
        ).fetchall()
    )
    rows.extend(
        conn.execute(
            f"""
            select e.*
            from aliases a
            join entities e on e.id = a.entity_id
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where {entity_not_archived_sql("e")}
              {visibility_clause}
              {subtype_visibility_clause}
              {world_setting_visibility_clause}
              and a.alias = ?
            order by e.type, e.name
            limit 6
            """,
            (stripped,),
        ).fetchall()
    )
    return dedupe_rows(rows)


def find_explicit_entity_matches(
    conn: sqlite3.Connection,
    text: str,
    *,
    view: str = "player",
) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    stripped = text.strip()
    if player_context_query_is_hidden(conn, stripped, view=view):
        return []
    visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
        conn,
        view,
    )
    exact = conn.execute(
        f"""
        select e.*, 'id exact' as _reason
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.id = ?
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        limit 1
        """,
        (stripped,),
    ).fetchall()
    rows.extend(filter_player_candidate_rows(conn, exact, stripped, view=view))
    names = conn.execute(
        f"""
        select e.*, 'name contains' as _reason
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and length(e.name) >= 2
          and instr(?, e.name) > 0
        order by length(e.name) desc, e.type, e.name
        limit 20
        """,
        (text,),
    ).fetchall()
    rows.extend(
        [
            row
            for row in names
            if can_read_hidden(view) or player_candidate_matches_redacted_text(conn, row, str(row["name"] or ""), view=view)
        ]
    )
    aliases = conn.execute(
        f"""
        select e.*, 'alias contains: ' || a.alias as _reason
        from aliases a
        join entities e on e.id = a.entity_id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and (length(a.alias) >= 2 or a.alias = ?)
          and instr(?, a.alias) > 0
        order by length(a.alias) desc, e.type, e.name
        limit 20
        """,
        (stripped, text),
    ).fetchall()
    rows.extend(
        [
            row
            for row in aliases
            if can_read_hidden(view) or player_candidate_matches_redacted_text(conn, row, alias_from_reason(row), view=view)
        ]
    )
    short_aliases = conn.execute(
        f"""
        select e.*, 'short alias contains: ' || a.alias as _reason
        from aliases a
        join entities e on e.id = a.entity_id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and length(a.alias) = 1
          and instr(?, a.alias) > 0
          and e.type in ('equipment', 'item', 'threat')
        order by e.type, e.name
        limit 8
        """,
        (text,),
    ).fetchall()
    rows.extend(
        [
            row
            for row in short_aliases
            if can_read_hidden(view) or player_candidate_matches_redacted_text(conn, row, alias_from_reason(row), view=view)
        ]
    )
    return dedupe_rows(rows)


def find_candidate_entities(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int,
    view: str = "player",
) -> list[sqlite3.Row]:
    query = text.strip()
    if not query:
        return []
    if is_stopword_only_query(query):
        return []
    if not has_searchable_literal(query):
        return []
    if player_context_query_is_hidden(conn, query, view=view):
        return []
    tokens = candidate_search_tokens(query)
    significant_query = " ".join(tokens)
    public_view = "player"
    exact_matches = find_literal_candidate_entities(conn, query, limit=limit, view=public_view, exact_only=True)
    if significant_query and significant_query != query:
        exact_matches.extend(find_literal_candidate_entities(conn, significant_query, limit=limit, view=public_view, exact_only=True))
    broad_matches: list[sqlite3.Row] = []
    if significant_query and significant_query != query:
        broad_matches.extend(find_literal_candidate_entities(conn, significant_query, limit=limit, view=public_view))
    else:
        broad_matches.extend(find_literal_candidate_entities(conn, query, limit=limit, view=public_view))
    safe_query = sanitize_fts_query(text)
    if safe_query:
        visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
            conn,
            public_view,
        )
        fts_matches = (
            conn.execute(
                f"""
                select e.*
                from fts_index f
                join entities e on e.id = f.entity_id
                left join clocks c on c.entity_id = e.id
                {world_setting_join}
                where fts_index match ?
                  and {entity_not_archived_sql("e")}
                  {visibility_clause}
                  {subtype_visibility_clause}
                  {world_setting_visibility_clause}
                limit ?
                """,
                (safe_query, limit),
            ).fetchall()
        )
        broad_matches.extend(filter_player_candidate_rows_any(conn, fts_matches, [*tokens, significant_query, query], view=public_view))
    if significant_query and significant_query != query:
        broad_matches.extend(find_literal_candidate_entities(conn, query, limit=limit, view=public_view))
    trusted_exact_matches = (
        find_trusted_literal_candidate_entities(conn, query, limit=limit, view=view, exact_only=True)
        if can_read_hidden(view)
        else []
    )
    if can_read_hidden(view) and significant_query and significant_query != query:
        trusted_exact_matches.extend(
            find_trusted_literal_candidate_entities(conn, significant_query, limit=limit, view=view, exact_only=True)
        )
    trusted_broad_matches = find_trusted_token_candidate_entities(conn, query, limit=limit, view=view) if can_read_hidden(view) else []
    return dedupe_rows([*trusted_exact_matches, *exact_matches, *trusted_broad_matches, *broad_matches])[:limit]


def find_literal_candidate_entities(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int,
    view: str,
    exact_only: bool = False,
) -> list[sqlite3.Row]:
    literal = text.strip()
    if not literal:
        return []
    visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
        conn,
        view,
    )
    if exact_only:
        rows = conn.execute(
            f"""
            select e.*
            from entities e
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where {entity_not_archived_sql("e")}
              {visibility_clause}
              {subtype_visibility_clause}
              {world_setting_visibility_clause}
              and lower(e.name) = lower(?)
            order by
              case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
              e.type,
              e.name
            limit ?
            """,
            (literal, limit),
        ).fetchall()
        return filter_player_candidate_rows(conn, rows, literal, view=view)

    like = f"%{escape_like(literal)}%"
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and (e.name like ? escape '\\' or e.summary like ? escape '\\')
        order by
          case
            when lower(e.name) = lower(?) then 0
            when e.name like ? escape '\\' then 1
            else 2
          end,
          case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
          e.type,
          e.name
        limit ?
        """,
        (like, like, literal, like, limit),
    ).fetchall()
    return filter_player_candidate_rows(conn, rows, literal, view=view)


def find_trusted_token_candidate_entities(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int,
    view: str,
) -> list[sqlite3.Row]:
    if not can_read_hidden(view):
        return []
    query = text.strip()
    if not query or is_stopword_only_query(query) or not has_searchable_literal(query):
        return []
    literal_matches = find_trusted_literal_candidate_entities(conn, query, limit=limit, view=view)
    tokens = candidate_search_tokens(query)
    if not tokens:
        tokens = [query]
    if not tokens:
        return literal_matches
    ensure_visibility_sql_functions(conn)
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, _ = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    world_setting_hidden_clause = world_setting_hidden_condition(conn)
    clauses: list[str] = []
    params: list[str] = []
    for token in tokens[:8]:
        like = f"%{escape_like(token)}%"
        clauses.append(
            """
            e.name like ? escape '\\' or e.summary like ? escape '\\' or e.details_json like ? escape '\\'
            or exists (select 1 from aliases a where a.entity_id = e.id and a.alias like ? escape '\\')
            """
        )
        params.extend([like, like, like, like])
    token_clause = " and ".join(f"({clause})" for clause in clauses)
    token_matches = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {subtype_visibility_clause}
          and (
            {player_hidden_visibility_sql("e.visibility")}
            or ({normalized_text_sql("e.type")} = 'clock'
                and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
            or {world_setting_hidden_clause}
          )
          and ({token_clause})
        order by
          case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
          e.type,
          e.name
        limit ?
        """,
        [*params, limit],
    ).fetchall()
    return dedupe_rows([*literal_matches, *token_matches])[:limit]


def find_trusted_literal_candidate_entities(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int,
    view: str,
    exact_only: bool = False,
) -> list[sqlite3.Row]:
    literal = text.strip()
    if not can_read_hidden(view):
        return []
    if not literal or is_stopword_only_query(literal) or not has_searchable_literal(literal):
        return []
    ensure_visibility_sql_functions(conn)
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, _ = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    world_setting_hidden_clause = world_setting_hidden_condition(conn)
    if exact_only:
        return conn.execute(
            f"""
            select e.*
            from entities e
            left join clocks c on c.entity_id = e.id
            {world_setting_join}
            where {entity_not_archived_sql("e")}
              {subtype_visibility_clause}
              and (
                {player_hidden_visibility_sql("e.visibility")}
                or ({normalized_text_sql("e.type")} = 'clock'
                    and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
                or {world_setting_hidden_clause}
              )
              and lower(e.name) = lower(?)
            order by
              case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
              e.type,
              e.name
            limit ?
            """,
            (literal, limit),
        ).fetchall()

    like = f"%{escape_like(literal)}%"
    return conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {subtype_visibility_clause}
          and (
            {player_hidden_visibility_sql("e.visibility")}
            or ({normalized_text_sql("e.type")} = 'clock'
                and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
            or {world_setting_hidden_clause}
          )
          and (
            e.name like ? escape '\\'
            or e.summary like ? escape '\\'
            or e.details_json like ? escape '\\'
            or exists (select 1 from aliases a where a.entity_id = e.id and a.alias like ? escape '\\')
          )
        order by
          case
            when lower(e.name) = lower(?) then 0
            when e.name like ? escape '\\' then 1
            else 2
          end,
          case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
          e.type,
          e.name
        limit ?
        """,
        (like, like, like, like, literal, like, limit),
    ).fetchall()


def is_stopword_only_query(text: str) -> bool:
    raw_tokens = [token for token in re.findall(r"[\w\u4e00-\u9fff]+", text) if token.strip()]
    if len(raw_tokens) == 1 and raw_tokens[0][:1].isupper():
        return False
    tokens = [token.lower() for token in raw_tokens]
    return bool(tokens) and all(token in QUERY_STOP_WORDS for token in tokens)


def has_searchable_literal(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text))


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def candidate_search_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[\w\u4e00-\u9fff]+", text):
        for normalized in significant_token_parts(token):
            lower = normalized.lower()
            has_cjk = bool(re.search(r"[\u4e00-\u9fff]", normalized))
            if lower in QUERY_STOP_WORDS:
                continue
            if not has_cjk and len(lower) < 3 and not any(char.isdigit() for char in lower):
                continue
            if normalized not in tokens:
                tokens.append(normalized)
    return tokens


def significant_token_parts(token: str) -> list[str]:
    normalized = token.strip()
    if not normalized:
        return []
    if not re.search(r"[\u4e00-\u9fff]", normalized):
        return [normalized]
    stripped = normalized
    while True:
        for prefix in CJK_REQUEST_PREFIXES:
            if stripped.startswith(prefix) and len(stripped) > len(prefix):
                stripped = stripped[len(prefix) :]
                break
        else:
            break
    return [stripped] if stripped else []


def ambiguous_candidates(conn: sqlite3.Connection, text: str, *, view: str = "player") -> list[EntityHit]:
    if player_context_query_is_hidden(conn, text, view=view):
        return []
    keywords = ambiguous_keywords(text)
    if not keywords:
        return salient_ambiguous_candidates(conn, view=view)
    clauses = " or ".join(["e.name like ? or e.summary like ? or e.details_json like ?" for _ in keywords])
    visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
        conn,
        view,
    )
    params: list[str] = []
    for keyword in keywords:
        like = f"%{keyword}%"
        params.extend([like, like, like])
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and ({clauses})
        order by
          case e.type
            when 'character' then 0
            when 'species' then 1
            when 'item' then 2
            when 'location' then 3
            else 4
          end,
          e.name
        limit 6
        """,
        params,
    ).fetchall()
    if not rows:
        return salient_ambiguous_candidates(conn, view=view)
    if not can_read_hidden(view):
        rows = [
            row
            for row in rows
            if any(player_candidate_matches_redacted_text(conn, row, keyword, view=view) for keyword in keywords)
        ]
    if not rows:
        return []
    return entity_rows_to_hits(rows, reason="ambiguous pronoun candidate", priority=50)


def ambiguous_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    if "蘑菇" in text:
        keywords.extend(["蘑菇", "孢子"])
    elif "菌" in text:
        keywords.extend(["菌", "孢子"])

    normalized = text
    for stop in [*AMBIGUOUS_TERMS, *AMBIGUOUS_STOP_TERMS]:
        normalized = normalized.replace(stop, " ")
    normalized = AMBIGUOUS_SPLIT_PATTERN.sub(" ", normalized)
    for token in AMBIGUOUS_CJK_OR_WORD_PATTERN.findall(normalized):
        token = token.strip()
        if token and token not in AMBIGUOUS_STOP_TERMS:
            keywords.append(token)
    return dedupe_texts(keywords)[:8]


def salient_ambiguous_candidates(conn: sqlite3.Connection, *, view: str = "player") -> list[EntityHit]:
    meta = get_meta(conn)
    current_location_id = meta.get("current_location_id") or ""
    player_entity_id = get_player_entity_id(conn)
    visibility_clause, subtype_visibility_clause, world_setting_join, world_setting_visibility_clause = entity_visibility_parts(
        conn,
        view,
    )
    rows = conn.execute(
        f"""
        select e.*,
               case
                 when e.location_id = ? and e.type = 'character' then 0
                 when e.location_id = ? then 1
                 when e.owner_id = ? then 2
                 when e.type = 'character' then 3
                 else 4
	               end as _rank
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and e.id != ?
          and (
            (? != '' and e.location_id = ?)
            or e.owner_id = ?
            or e.type = 'character'
          )
        order by
          _rank,
          case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
          e.type,
          e.name
        limit 6
        """,
        (
            current_location_id,
            current_location_id,
            player_entity_id,
            player_entity_id,
            current_location_id,
            current_location_id,
            player_entity_id,
        ),
    ).fetchall()
    return entity_rows_to_hits(rows, reason="salient ambiguous pronoun candidate", priority=45)


def entity_rows_to_hits(rows: list[sqlite3.Row], *, reason: str, priority: int) -> list[EntityHit]:
    return [
        EntityHit(
            id=row["id"],
            type=row["type"],
            name=row["name"],
            summary=row["summary"] or "",
            status=row["status"],
            location_id=row["location_id"],
            owner_id=row["owner_id"],
            reason=reason,
            priority=priority,
        )
        for row in rows
    ]


def linked_entity_ids(conn: sqlite3.Connection, hit: EntityHit, state: Any) -> list[tuple[str, str, int]]:
    if hit.depth >= state.max_depth:
        return []
    row = conn.execute("select details_json from entities where id = ?", (hit.id,)).fetchone()
    details = parse_json(row["details_json"], {}) if row else {}
    links: list[tuple[str, str, int]] = []

    item = conn.execute("select category, properties_json from items where entity_id = ?", (hit.id,)).fetchone()
    properties = parse_json(item["properties_json"], {}) if item else {}

    if properties:
        links.extend(profile_links(hit, properties, state))
    if details:
        links.extend(recipe_links(hit, details, state))
        for linked_id in extract_entity_ids(details):
            links.append((linked_id, f"linked from details of {hit.id}", linked_priority(hit, state)))

    return dedupe_links(links, source_id=hit.id)


def profile_links(hit: EntityHit, properties: dict[str, Any], state: Any) -> list[tuple[str, str, int]]:
    links: list[tuple[str, str, int]] = []
    combat = properties.get("combat_profile")
    if isinstance(combat, dict):
        for item in as_list(combat.get("compatible_ammo")):
            if isinstance(item, dict) and item.get("id"):
                priority = 82 if state.submode == "combat" else 68
                links.append((str(item["id"]), f"compatible ammo for {hit.id}", priority))
    ammo = properties.get("ammo_profile")
    if isinstance(ammo, dict) and ammo.get("compatible_weapon_id"):
        priority = 80 if state.submode == "combat" else 65
        links.append((str(ammo["compatible_weapon_id"]), f"compatible weapon for {hit.id}", priority))
    for linked_id in extract_entity_ids(properties):
        links.append((linked_id, f"linked from item profile of {hit.id}", linked_priority(hit, state)))
    return links


def recipe_links(hit: EntityHit, details: dict[str, Any], state: Any) -> list[tuple[str, str, int]]:
    profile = details.get("recipe_profile")
    if not isinstance(profile, dict):
        return []
    links: list[tuple[str, str, int]] = []
    for key, reason in [("inputs", "recipe input"), ("tools", "recipe tool")]:
        for item in as_list(profile.get(key)):
            if isinstance(item, dict) and item.get("id"):
                priority = 74 if state.submode in {"gather", "craft"} else 62
                links.append((str(item["id"]), f"{reason} for {hit.id}", priority))
    output = profile.get("output")
    if isinstance(output, dict) and output.get("id"):
        links.append((str(output["id"]), f"recipe output for {hit.id}", 62))
    return links


def linked_priority(hit: EntityHit, state: Any) -> int:
    if state.submode == "combat" and hit.type in {"equipment", "item", "threat"}:
        return 72
    if state.submode in {"gather", "craft"} and hit.type in {"recipe", "item", "material", "plant"}:
        return 68
    if state.submode == "social" and hit.type in {"character", "faction"}:
        return 68
    return 58


def extract_entity_ids(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value
    return sorted(set(ENTITY_ID_PATTERN.findall(text)))


def dedupe_links(links: list[tuple[str, str, int]], *, source_id: str) -> list[tuple[str, str, int]]:
    result: dict[str, tuple[str, str, int]] = {}
    for linked_id, reason, priority in links:
        if linked_id == source_id:
            continue
        existing = result.get(linked_id)
        if not existing or priority > existing[2]:
            result[linked_id] = (linked_id, reason, priority)
    return list(result.values())


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def character_species_id(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute("select species_id from characters where entity_id = ?", (entity_id,)).fetchone()
    return row["species_id"] if row and row["species_id"] else None


def sanitize_fts_query(text: str) -> str:
    safe_tokens: list[str] = []
    for token in candidate_search_tokens(text)[:6]:
        escaped = token.replace('"', '""')
        if escaped:
            safe_tokens.append(f'"{escaped}"')
    return " OR ".join(safe_tokens)


def dedupe_rows(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    seen: set[str] = set()
    result: list[sqlite3.Row] = []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        result.append(row)
    return result


def dedupe_texts(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def add_hit(hits: dict[str, EntityHit], hit: EntityHit) -> None:
    existing = hits.get(hit.id)
    if not existing or hit.priority > existing.priority:
        hits[hit.id] = hit


def contains_any(text: str, terms: list[str]) -> bool:
    return any(term and term in text for term in terms)


def is_direct_hit(hit: EntityHit) -> bool:
    return hit.reason.startswith(("name", "alias", "short alias", "id", "candidate"))


def sort_hits(hits: Any) -> list[EntityHit]:
    return sorted(
        hits,
        key=lambda item: (
            0 if is_direct_hit(item) else 1,
            -item.priority,
            item.depth,
            item.type,
            item.name,
        ),
    )
