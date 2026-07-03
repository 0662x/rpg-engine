from __future__ import annotations

import sqlite3

from .content_types import get_default_registry


def run_checks(conn: sqlite3.Connection) -> list[str]:
    errors = run_core_checks(conn)
    for spec in get_default_registry().all():
        if spec.validate_database:
            errors.extend(spec.validate_database(conn))
    return errors


def run_core_checks(conn: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    meta = {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}

    current_location = meta.get("current_location_id")
    if current_location:
        exists = conn.execute("select 1 from entities where id = ?", (current_location,)).fetchone()
        if not exists:
            errors.append(f"meta.current_location_id points to missing entity: {current_location}")

    current_turn = meta.get("current_turn_id")
    if current_turn:
        exists = conn.execute("select 1 from turns where id = ?", (current_turn,)).fetchone()
        if not exists:
            errors.append(f"meta.current_turn_id points to missing turn: {current_turn}")

    missing_locations = conn.execute(
        """
        select e.id, e.location_id
        from entities e
        left join entities loc on loc.id = e.location_id
        where e.location_id is not null and loc.id is null
        """
    ).fetchall()
    for row in missing_locations:
        errors.append(f"{row['id']} has missing location_id {row['location_id']}")

    missing_owners = conn.execute(
        """
        select e.id, e.owner_id
        from entities e
        left join entities owner on owner.id = e.owner_id
        where e.owner_id is not null and owner.id is null
        """
    ).fetchall()
    for row in missing_owners:
        errors.append(f"{row['id']} has missing owner_id {row['owner_id']}")

    negative_items = conn.execute(
        """
        select e.id, e.name, i.quantity
        from items i
        join entities e on e.id = i.entity_id
        where i.quantity < 0
        """
    ).fetchall()
    for row in negative_items:
        errors.append(f"{row['id']} {row['name']} has negative quantity {row['quantity']}")

    owner_location_conflicts = conn.execute(
        """
        select id, name, owner_id, location_id
        from entities
        where status = 'active'
          and owner_id is not null
          and location_id is not null
        """
    ).fetchall()
    for row in owner_location_conflicts:
        errors.append(
            f"{row['id']} {row['name']} has both owner_id {row['owner_id']} "
            f"and location_id {row['location_id']}"
        )

    duplicate_plots = conn.execute(
        """
        select plot_no, count(*) as count
        from crop_plots
        group by plot_no
        having count(*) > 1
        """
    ).fetchall()
    for row in duplicate_plots:
        errors.append(f"crop plot number {row['plot_no']} is duplicated {row['count']} times")

    bad_clocks = conn.execute(
        """
        select e.id, e.name, c.segments_filled, c.segments_total
        from clocks c
        join entities e on e.id = c.entity_id
        where c.segments_filled < 0
           or c.segments_total <= 0
           or c.segments_filled > c.segments_total
        """
    ).fetchall()
    for row in bad_clocks:
        errors.append(
            f"{row['id']} {row['name']} has invalid clock {row['segments_filled']}/{row['segments_total']}"
        )

    bad_routes = conn.execute(
        """
        select r.id, r.from_location_id, r.to_location_id, r.travel_minutes
        from routes r
        left join entities source on source.id = r.from_location_id and source.type = 'location'
        left join entities target on target.id = r.to_location_id and target.type = 'location'
        where source.id is null
           or target.id is null
           or r.travel_minutes <= 0
        """
    ).fetchall()
    for row in bad_routes:
        errors.append(
            f"route {row['id']} has invalid endpoints/time "
            f"{row['from_location_id']} -> {row['to_location_id']} ({row['travel_minutes']})"
        )

    missing_alias_targets = conn.execute(
        """
        select a.alias, a.entity_id
        from aliases a
        left join entities e on e.id = a.entity_id
        where e.id is null
        """
    ).fetchall()
    for row in missing_alias_targets:
        errors.append(f"alias {row['alias']} points to missing entity {row['entity_id']}")

    bad_fact_ranges = conn.execute(
        """
        select id, valid_from_turn, valid_to_turn
        from facts
        where valid_to_turn is not null
          and valid_to_turn < valid_from_turn
        """
    ).fetchall()
    for row in bad_fact_ranges:
        errors.append(
            f"fact {row['id']} valid_to_turn {row['valid_to_turn']} is before "
            f"valid_from_turn {row['valid_from_turn']}"
        )

    return errors
