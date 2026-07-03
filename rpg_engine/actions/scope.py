from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal


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
    return str(row["parent_id"]) if row and row["parent_id"] else None


def direct_route(conn: sqlite3.Connection, from_location_id: str, target_location_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select id, travel_minutes
        from routes
        where (from_location_id = ? and to_location_id = ?)
           or (from_location_id = ? and to_location_id = ?)
        order by travel_minutes
        limit 1
        """,
        (from_location_id, target_location_id, target_location_id, from_location_id),
    ).fetchone()
