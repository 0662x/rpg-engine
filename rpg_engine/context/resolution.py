from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..db import get_meta, get_player_entity_id
from ..render import parse_json
from ..visibility import context_visibility_view, entity_visibility_sql


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
    "查询",
    "说明",
    "我",
    "想",
    "要",
    "的",
]
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


def collect_entity_hits(state: Any) -> None:
    hits: dict[str, EntityHit] = {}
    text = state.user_text
    view = context_visibility_view(state.mode)

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

    if not hits and state.submode == "entity":
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
    view = context_visibility_view(state.mode)
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
    view = context_visibility_view(state.mode)
    visibility_clause = entity_visibility_sql(view, "e")
    row = state.conn.execute(
        f"""
        select e.*
        from entities e
        where e.id = ?
          and e.status != 'archived'
          {visibility_clause}
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
    visibility_clause = entity_visibility_sql(view, "e")
    rows.extend(
        conn.execute(
            f"""
            select e.*
            from entities e
            where e.status != 'archived'
              {visibility_clause}
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
            where e.status != 'archived'
              {visibility_clause}
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
    visibility_clause = entity_visibility_sql(view, "e")
    exact = conn.execute(
        f"""
        select e.*, 'id exact' as _reason
        from entities e
        where e.id = ?
          and e.status != 'archived'
          {visibility_clause}
        limit 1
        """,
        (stripped,),
    ).fetchall()
    rows.extend(exact)
    names = conn.execute(
        f"""
        select e.*, 'name contains' as _reason
        from entities e
        where e.status != 'archived'
          {visibility_clause}
          and length(e.name) >= 2
          and instr(?, e.name) > 0
        order by length(e.name) desc, e.type, e.name
        limit 20
        """,
        (text,),
    ).fetchall()
    rows.extend(names)
    aliases = conn.execute(
        f"""
        select e.*, 'alias contains: ' || a.alias as _reason
        from aliases a
        join entities e on e.id = a.entity_id
        where e.status != 'archived'
          {visibility_clause}
          and (length(a.alias) >= 2 or a.alias = ?)
          and instr(?, a.alias) > 0
        order by length(a.alias) desc, e.type, e.name
        limit 20
        """,
        (stripped, text),
    ).fetchall()
    rows.extend(aliases)
    short_aliases = conn.execute(
        f"""
        select e.*, 'short alias contains: ' || a.alias as _reason
        from aliases a
        join entities e on e.id = a.entity_id
        where e.status != 'archived'
          {visibility_clause}
          and length(a.alias) = 1
          and instr(?, a.alias) > 0
          and e.type in ('equipment', 'item', 'threat')
        order by e.type, e.name
        limit 8
        """,
        (text,),
    ).fetchall()
    rows.extend(short_aliases)
    return dedupe_rows(rows)


def find_candidate_entities(
    conn: sqlite3.Connection,
    text: str,
    *,
    limit: int,
    view: str = "player",
) -> list[sqlite3.Row]:
    like = f"%{text.strip()}%"
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        where e.status != 'archived'
          {visibility_clause}
          and (e.name like ? or e.summary like ?)
        order by
          case e.status when 'active' then 0 when 'retired' then 1 else 2 end,
          e.type,
          e.name
        limit ?
        """,
        (like, like, limit),
    ).fetchall()
    if rows:
        return rows
    safe_query = sanitize_fts_query(text)
    if not safe_query:
        return []
    return conn.execute(
        f"""
        select e.*
        from fts_index f
        join entities e on e.id = f.entity_id
        where fts_index match ?
          and e.status != 'archived'
          {visibility_clause}
        limit ?
        """,
        (safe_query, limit),
    ).fetchall()


def ambiguous_candidates(conn: sqlite3.Connection, text: str, *, view: str = "player") -> list[EntityHit]:
    keywords = ambiguous_keywords(text)
    if not keywords:
        return salient_ambiguous_candidates(conn, view=view)
    clauses = " or ".join(["e.name like ? or e.summary like ? or e.details_json like ?" for _ in keywords])
    visibility_clause = entity_visibility_sql(view, "e")
    params: list[str] = []
    for keyword in keywords:
        like = f"%{keyword}%"
        params.extend([like, like, like])
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        where e.status != 'archived'
          {visibility_clause}
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
    visibility_clause = entity_visibility_sql(view, "e")
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
        where e.status != 'archived'
          {visibility_clause}
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
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text)
    return " OR ".join(tokens[:6])


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
