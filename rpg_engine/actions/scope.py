from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from ..preview import location_detail_row
from ..db import entity_subtype_visibility_sql
from ..visibility import ensure_visibility_sql_functions, entity_not_archived_sql, entity_visibility_sql, normalized_text_sql


ScopeKind = Literal["same_location", "same_parent", "one_hop", "remote", "blocked"]


@dataclass(frozen=True)
class InteractionScope:
    kind: ScopeKind
    from_location_id: str | None
    target_location_id: str | None
    parent_id: str | None = None
    route_id: str | None = None
    estimated_minutes: int | None = None
    requires_travel: bool = False


def location_scope(conn: sqlite3.Connection, from_location_id: str | None, target_location_id: str | None) -> InteractionScope:
    if not from_location_id or not target_location_id:
        return InteractionScope("blocked", from_location_id, target_location_id, requires_travel=True)
    from_location = location_detail_row(conn, from_location_id)
    target_location = location_detail_row(conn, target_location_id)
    if not from_location or not target_location:
        return InteractionScope("blocked", from_location_id, target_location_id, requires_travel=True)
    if from_location_id == target_location_id:
        return InteractionScope("same_location", from_location_id, target_location_id, requires_travel=False)

    from_parent = location_parent(conn, from_location_id)
    target_parent = location_parent(conn, target_location_id)
    if from_parent and from_parent == target_parent:
        return InteractionScope(
            "same_parent",
            from_location_id,
            target_location_id,
            parent_id=from_parent,
            estimated_minutes=2,
            requires_travel=True,
        )

    route = direct_route(conn, from_location_id, target_location_id)
    if route:
        return InteractionScope(
            "one_hop",
            from_location_id,
            target_location_id,
            route_id=str(route["id"]),
            estimated_minutes=int(route["travel_minutes"]) if route["travel_minutes"] is not None else None,
            requires_travel=True,
        )

    return InteractionScope("remote", from_location_id, target_location_id, requires_travel=True)


def location_parent(conn: sqlite3.Connection, location_id: str) -> str | None:
    row = conn.execute("select parent_id from locations where entity_id = ?", (location_id,)).fetchone()
    if not row or not row["parent_id"]:
        return None
    parent_id = str(row["parent_id"])
    return parent_id if location_detail_row(conn, parent_id) else None


def direct_route(conn: sqlite3.Connection, from_location_id: str, target_location_id: str) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    from_visibility_clause = entity_visibility_sql("player", "from_e")
    to_visibility_clause = entity_visibility_sql("player", "to_e")
    from_subtype_clause = entity_subtype_visibility_sql("player", "from_e", "from_clock")
    to_subtype_clause = entity_subtype_visibility_sql("player", "to_e", "to_clock")
    return conn.execute(
        f"""
        select r.id, r.travel_minutes
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
            (r.from_location_id = ? and r.to_location_id = ?)
            or (r.from_location_id = ? and r.to_location_id = ?)
          )
        order by r.travel_minutes
        limit 1
        """,
        (from_location_id, target_location_id, target_location_id, from_location_id),
    ).fetchone()
