from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from tests.helpers import (
    CURRENT_CAMPAIGN_ROOT,
    CURRENT_SAVE_ROOT,
    copy_current_packages,
    normalize_current_native_story_fixture,
    run_cli,
    tree_digest,
)


@pytest.fixture
def current_native_temp_save(tmp_path: Path) -> Iterator[Path]:
    if not CURRENT_CAMPAIGN_ROOT.exists() or not CURRENT_SAVE_ROOT.exists():
        pytest.skip("requires current native Campaign and Save packages")
    source_before = tree_digest(CURRENT_CAMPAIGN_ROOT)
    formal_before = tree_digest(CURRENT_SAVE_ROOT)
    registry_path = CURRENT_CAMPAIGN_ROOT.parent / ".aigm" / "save-registry.json"
    registry_before = registry_path.read_bytes() if registry_path.exists() else None
    save = normalize_current_native_story_fixture(copy_current_packages(tmp_path))
    run_cli("migrate", "apply", save)
    _set_current_location(save, "loc:home-old-hut")
    yield save
    assert tree_digest(CURRENT_CAMPAIGN_ROOT) == source_before
    assert tree_digest(CURRENT_SAVE_ROOT) == formal_before
    assert (registry_path.read_bytes() if registry_path.exists() else None) == registry_before


@pytest.fixture
def db_snapshot() -> Callable[[Path], dict[str, Any]]:
    return snapshot_save


def snapshot_save(save: Path) -> dict[str, Any]:
    db_path = save / "data" / "game.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            select e.id, e.type, e.name, e.status, e.visibility, e.location_id, e.owner_id,
                   e.summary, e.details_json, i.category, i.quantity, i.unit, i.quality,
                   i.durability_current, i.durability_max, i.stackable, i.equipped_slot,
                   i.properties_json
            from entities e
            join items i on i.entity_id = e.id
            order by e.id
            """
        ).fetchall()
        aliases = {
            str(row["entity_id"]): []
            for row in conn.execute("select distinct entity_id from aliases order by entity_id")
        }
        for row in conn.execute(
            "select entity_id, alias from aliases where kind='name' order by entity_id, alias"
        ):
            aliases.setdefault(str(row["entity_id"]), []).append(str(row["alias"]))
        inventory = {str(row["id"]): _snapshot_item(row, aliases.get(str(row["id"]), [])) for row in rows}
        turn_count = int(conn.execute("select count(*) from turns").fetchone()[0])
        event_count = int(conn.execute("select count(*) from events").fetchone()[0])
    return {
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "events_jsonl": (save / "data" / "events.jsonl").read_text(encoding="utf-8"),
        "inventory": inventory,
        "turn_count": turn_count,
        "event_count": event_count,
    }


def meta_value(save: Path, key: str) -> str:
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        row = conn.execute("select value from meta where key=?", (key,)).fetchone()
    if row is None:
        raise ValueError(f"missing Save meta: {key}")
    return str(row[0])


def _set_current_location(save: Path, location_id: str) -> None:
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        player_row = conn.execute("select value from meta where key='player_entity_id'").fetchone()
        if player_row is None:
            raise ValueError("missing Save meta: player_entity_id")
        player_id = str(player_row[0])
        conn.execute("update meta set value=? where key='current_location_id'", (location_id,))
        conn.execute("update entities set location_id=? where id=?", (location_id, player_id))
        conn.commit()


def _snapshot_item(row: sqlite3.Row, aliases: list[str]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "type": str(row["type"]),
        "name": str(row["name"]),
        "status": str(row["status"]),
        "visibility": str(row["visibility"]),
        "location_id": row["location_id"],
        "owner_id": row["owner_id"],
        "summary": str(row["summary"] or ""),
        "details": json.loads(row["details_json"] or "{}"),
        "aliases": aliases,
        "category": str(row["category"]),
        "quantity": float(row["quantity"]) if row["quantity"] is not None else None,
        "unit": row["unit"],
        "quality": row["quality"],
        "durability_current": row["durability_current"],
        "durability_max": row["durability_max"],
        "stackable": bool(row["stackable"]),
        "equipped_slot": row["equipped_slot"],
        "properties": json.loads(row["properties_json"] or "{}"),
    }
