from __future__ import annotations

import json
import math
import os
import sqlite3
from pathlib import Path

import pytest

from rpg_engine.db import (
    connect,
    entity_subtype_visibility_sql,
    world_setting_entity_join_and_clause,
)
from rpg_engine.query_collection import collect_entity_query
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_service import init_v1_save
from rpg_engine.visibility import entity_visibility_sql, normalized_text_sql
from rpg_engine.visibility import ensure_visibility_sql_functions
from tests.helpers import (
    CURRENT_CAMPAIGN_ROOT,
    CURRENT_SAVE_ROOT,
    copy_current_packages,
    copy_initialized_minimal,
    tree_digest,
)


ENGINE_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CAMPAIGNS = (
    ENGINE_ROOT / "examples" / "v1_minimal_adventure",
    ENGINE_ROOT / "examples" / "small_cn_campaign",
)
FORMAL_REGISTRY = CURRENT_SAVE_ROOT.parent / ".aigm" / "save-registry.json"


def _request(
    *,
    category: str | None = "ammunition",
    scope: str = "all",
    scope_id: str | None = None,
    aggregation: str = "quantity",
) -> dict[str, object]:
    value: dict[str, object] = {
        "entity_type": "item",
        "scope": scope,
        "aggregation": aggregation,
    }
    if category is not None:
        value["category"] = category
    if scope_id is not None:
        value["scope_id"] = scope_id
    return value


def _database_snapshot(db_path: Path) -> tuple[tuple[tuple[str, str | None], ...], tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]]:
    with sqlite3.connect(db_path) as conn:
        schema = tuple(
            (str(row[0]), None if row[1] is None else str(row[1]))
            for row in conn.execute(
                """
                select name, sql
                from main.sqlite_master
                where type in ('table', 'index', 'trigger', 'view')
                order by type, name
                """
            )
        )
        tables: list[tuple[str, tuple[tuple[object, ...], ...]]] = []
        for (name,) in conn.execute(
            """
            select name
            from main.sqlite_master
            where type='table' and name not like 'sqlite_%'
            order by name
            """
        ):
            quoted = str(name).replace('"', '""')
            rows = tuple(
                sorted(
                    (tuple(row) for row in conn.execute(f'select * from main."{quoted}"')),
                    key=repr,
                )
            )
            tables.append((str(name), rows))
    return schema, tuple(tables)


def _path_snapshot(path: Path) -> tuple[object, ...]:
    if path.is_symlink():
        target = os.readlink(path)
        resolved = path.resolve(strict=False)
        payload = resolved.read_bytes() if resolved.is_file() else None
        return ("symlink", target, payload)
    if path.is_file():
        return ("file", path.read_bytes())
    if path.is_dir():
        return ("directory", tree_digest(path))
    return ("missing",)


def _expected_totals(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
    grouped: dict[str | None, list[int | float]] = {}
    for row in rows:
        quantity = row["quantity"]
        if type(quantity) in {int, float}:
            grouped.setdefault(row["unit"], []).append(quantity)
    return [
        {"unit": unit, "quantity": math.fsum(values)}
        for unit, values in sorted(grouped.items(), key=lambda pair: (0, "") if pair[0] is None else (1, pair[0]))
    ]


def _visible_item_rows(conn: sqlite3.Connection, category: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    ensure_visibility_sql_functions(conn)
    visibility = entity_visibility_sql("player", "e")
    subtype_visibility = entity_subtype_visibility_sql("player", "e", "c")
    world_join, world_visibility = world_setting_entity_join_and_clause(
        conn,
        "player",
        entity_alias="e",
        setting_alias="ws",
    )
    return conn.execute(
        f"""
        select e.id, e.name, i.quantity, i.unit
        from main.entities e
        join main.items i on i.entity_id=e.id
        left join main.clocks c on c.entity_id=e.id
        {world_join}
        where {normalized_text_sql('e.type')}='item'
          and {normalized_text_sql('e.status')}='active'
          and {normalized_text_sql('i.category')}=?
          {visibility}
          {subtype_visibility}
          {world_visibility}
        order by e.id
        """,
        (category,),
    ).fetchall()


def _insert_entity(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    entity_type: str,
    name: str,
    status: str = "active",
    visibility: str = "known",
    owner_id: str | None = None,
    location_id: str | None = None,
) -> None:
    conn.execute(
        """
        insert into main.entities
        (id, type, name, status, visibility, location_id, owner_id, summary,
         details_json, updated_turn_id, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, '', '{}', 'turn:seed', '2026-07-18T00:00:00+00:00')
        """,
        (entity_id, entity_type, name, status, visibility, location_id, owner_id),
    )


def _insert_item(
    conn: sqlite3.Connection,
    *,
    entity_id: str,
    name: str,
    quantity: float | None,
    unit: str | None,
    category: str = "ammunition",
    status: str = "active",
    visibility: str = "known",
    owner_id: str | None = None,
    location_id: str | None = None,
) -> None:
    _insert_entity(
        conn,
        entity_id=entity_id,
        entity_type="item",
        name=name,
        status=status,
        visibility=visibility,
        owner_id=owner_id,
        location_id=location_id,
    )
    conn.execute(
        """
        insert into main.items
        (entity_id, category, quantity, unit, stackable, properties_json)
        values (?, ?, ?, ?, 1, '{}')
        """,
        (entity_id, category, quantity, unit),
    )


@pytest.fixture
def aggregate_save(tmp_path: Path) -> tuple[Path, str, str]:
    save = copy_initialized_minimal(tmp_path)
    workspace_state = save.parent / ".aigm"
    workspace_state.mkdir(exist_ok=True)
    (workspace_state / "save-registry.json").write_text(
        json.dumps({"active_save": str(save)}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (workspace_state / "pending-query.json").write_text(
        '{"status":"must-remain-unchanged"}\n',
        encoding="utf-8",
    )
    db_path = save / "data" / "game.sqlite"
    with sqlite3.connect(db_path) as conn:
        player_id = str(conn.execute("select value from main.meta where key='player_entity_id'").fetchone()[0])
        location_id = str(conn.execute("select value from main.meta where key='current_location_id'").fetchone()[0])
        _insert_item(conn, entity_id="item:owner-a", name="Owner A", quantity=5, unit="支", owner_id=player_id)
        _insert_item(conn, entity_id="item:owner-b", name="Owner B", quantity=7, unit="支", owner_id=player_id)
        _insert_item(conn, entity_id="item:location", name="Location", quantity=3, unit="支", location_id=location_id)
        _insert_item(conn, entity_id="item:box", name="Box", quantity=2, unit="盒")
        _insert_item(conn, entity_id="item:null-unit", name="Null Unit", quantity=4, unit=None)
        _insert_item(conn, entity_id="item:empty-unit", name="Empty Unit", quantity=6, unit="")
        _insert_item(conn, entity_id="item:null-quantity", name="Null Quantity", quantity=None, unit="支")
        _insert_item(conn, entity_id="item:hidden", name="Hidden Canary", quantity=101, unit="支", visibility="hidden")
        _insert_item(conn, entity_id="item:gm", name="GM Canary", quantity=103, unit="支", visibility="gm-only")
        _insert_item(conn, entity_id="item:retired", name="Retired Canary", quantity=107, unit="支", status="retired")
        _insert_item(conn, entity_id="item:archived", name="Archived Canary", quantity=113, unit="支", status="archived")
        _insert_item(conn, entity_id="item:other-category", name="Other", quantity=109, unit="支", category="food")
        conn.executemany(
            "insert into main.aliases(alias, entity_id, kind) values (?, 'item:owner-a', 'name')",
            (("ammo duplicate a",), ("ammo duplicate b",)),
        )
        conn.commit()
    return save, player_id, location_id


def test_collection_contract_filters_before_aggregation_and_preserves_exact_members(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, player_id, location_id = aggregate_save
    db_path = save / "data" / "game.sqlite"
    before_tree = tree_digest(save.parent)
    before_db = _database_snapshot(db_path)

    runtime = GMRuntime.from_path(save)
    all_result = runtime.query("entity", structured=_request(), view="player")
    owner_result = runtime.query(
        "entity",
        structured=_request(scope="owner", scope_id=player_id),
        view="player",
    )
    location_result = runtime.query(
        "entity",
        structured=_request(scope="location", scope_id=location_id),
        view="player",
    )

    all_data = all_result.data
    assert all_data["status"] == "ok"
    assert all_data["view"] == "player"
    assert all_data["scope"] == "all"
    assert all_data["member_count"] == 7
    assert [member["id"] for member in all_data["members"]] == [
        "item:box",
        "item:empty-unit",
        "item:location",
        "item:null-quantity",
        "item:null-unit",
        "item:owner-a",
        "item:owner-b",
    ]
    assert all_data["members"] == [
        {"id": "item:box", "name": "Box", "quantity": 2.0, "unit": "盒"},
        {"id": "item:empty-unit", "name": "Empty Unit", "quantity": 6.0, "unit": ""},
        {"id": "item:location", "name": "Location", "quantity": 3.0, "unit": "支"},
        {"id": "item:null-quantity", "name": "Null Quantity", "quantity": None, "unit": "支"},
        {"id": "item:null-unit", "name": "Null Unit", "quantity": 4.0, "unit": None},
        {"id": "item:owner-a", "name": "Owner A", "quantity": 5.0, "unit": "支"},
        {"id": "item:owner-b", "name": "Owner B", "quantity": 7.0, "unit": "支"},
    ]
    assert all_data["totals"] == [
        {"unit": None, "quantity": 4.0},
        {"unit": "", "quantity": 6.0},
        {"unit": "支", "quantity": 15.0},
        {"unit": "盒", "quantity": 2.0},
    ]
    assert owner_result.data["member_count"] == 2
    assert {member["id"] for member in owner_result.data["members"]} == {"item:owner-a", "item:owner-b"}
    assert location_result.data["members"] == [
        {"id": "item:location", "name": "Location", "quantity": 3.0, "unit": "支"}
    ]
    assert "scope_id" not in all_data
    assert "scope_id" not in owner_result.data
    assert "Hidden Canary" not in all_result.text
    assert "GM Canary" not in all_result.text
    assert "Retired Canary" not in all_result.text
    assert "Archived Canary" not in all_result.text
    assert "4.0（无单位）" in all_result.text
    assert "6.0（空单位）" in all_result.text
    assert _database_snapshot(db_path) == before_db
    assert tree_digest(save.parent) == before_tree


def test_aggregation_none_keeps_complete_members_and_omits_totals(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    before = tree_digest(save.parent)

    result = GMRuntime.from_path(save).query(
        "entity",
        structured=_request(aggregation="none"),
        view="player",
    )

    assert result.data["member_count"] == 7
    assert result.data["totals"] == []
    assert result.data["aggregation"] == "none"
    assert tree_digest(save.parent) == before


def test_hidden_or_invalid_scope_anchor_is_identical_to_absent_and_zero_write(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    db_path = save / "data" / "game.sqlite"
    with sqlite3.connect(db_path) as conn:
        _insert_entity(
            conn,
            entity_id="npc:hidden-owner-canary",
            entity_type="character",
            name="Hidden Owner Canary",
            visibility="hidden",
        )
        _insert_item(
            conn,
            entity_id="item:hidden-owner-stock",
            name="Hidden Owner Stock",
            quantity=211,
            unit="支",
            owner_id="npc:hidden-owner-canary",
        )
        _insert_entity(
            conn,
            entity_id="loc:retired-anchor",
            entity_type="location",
            name="Retired Location Canary",
            status="retired",
        )
        _insert_item(
            conn,
            entity_id="item:retired-location-stock",
            name="Retired Location Stock",
            quantity=223,
            unit="支",
            location_id="loc:retired-anchor",
        )
        conn.commit()
    before = tree_digest(save.parent)
    runtime = GMRuntime.from_path(save)

    hidden = runtime.query(
        "entity",
        structured=_request(scope="owner", scope_id="npc:hidden-owner-canary"),
        view="player",
    )
    absent = runtime.query(
        "entity",
        structured=_request(scope="owner", scope_id="npc:absent-owner-canary"),
        view="player",
    )
    retired = runtime.query(
        "entity",
        structured=_request(scope="location", scope_id="loc:retired-anchor"),
        view="player",
    )
    missing_location = runtime.query(
        "entity",
        structured=_request(scope="location", scope_id="loc:absent-anchor"),
        view="player",
    )

    assert hidden.data == absent.data
    assert hidden.text == absent.text
    assert retired.data == missing_location.data
    assert retired.text == missing_location.text
    expected_keys = {
        "contract",
        "status",
        "view",
        "scope",
        "entity_type",
        "category",
        "aggregation",
        "members",
        "member_count",
        "totals",
        "provenance",
        "authority",
    }
    for result in (hidden, absent, retired, missing_location):
        assert set(result.data) == expected_keys
        assert result.data["status"] == "empty"
        assert result.data["members"] == []
        assert result.data["member_count"] == 0
        assert result.data["totals"] == []
        wire = json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True)
        assert "canary" not in wire.casefold()
    assert tree_digest(save.parent) == before


@pytest.mark.parametrize(
    "structured",
    [
        {},
        {"entity_type": True, "scope": "all", "aggregation": "quantity"},
        {"entity_type": "item", "category": True, "scope": "all", "aggregation": "quantity"},
        {"entity_type": "item", "scope": True, "aggregation": "quantity"},
        {"entity_type": "item", "scope": "all", "scope_id": "pc:runner", "aggregation": "quantity"},
        {"entity_type": "item", "scope": "owner", "aggregation": "quantity"},
        {"entity_type": "item", "scope": "location", "scope_id": "", "aggregation": "quantity"},
        {
            "entity_type": "item",
            "scope": "owner",
            "scope_id": "NPC:bad:extra",
            "aggregation": "quantity",
        },
        {"entity_type": "item", "scope": "world", "aggregation": "quantity"},
        {"entity_type": "item", "scope": "all", "aggregation": "sum"},
        {"entity_type": "item", "scope": "all", "aggregation": "quantity", "unknown": "x"},
    ],
)
def test_invalid_structured_request_has_one_safe_error_and_zero_write(
    aggregate_save: tuple[Path, str, str],
    structured: dict[str, object],
) -> None:
    save, _, _ = aggregate_save
    before = tree_digest(save.parent)
    with pytest.raises(ValueError, match=r"^structured entity query request is invalid$"):
        GMRuntime.from_path(save).query("entity", structured=structured, view="player")
    assert tree_digest(save.parent) == before


def test_structured_request_is_player_only_conflict_safe_and_defensively_copied(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    runtime = GMRuntime.from_path(save)
    before = tree_digest(save.parent)
    mutable_request = _request(category="ＡＭＭＵＮＩＴＩＯＮ")
    result = runtime.query("entity", structured=mutable_request, view="player")
    mutable_request["category"] = "food"
    assert result.data["category"] == "ammunition"
    assert result.data["member_count"] == 7
    json.loads(result.to_json_text(), parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(value)))

    for invalid_view in ("gm", "maintenance", "bogus", "", True, None):
        with pytest.raises(ValueError, match=r"^structured entity query is player-only$"):
            runtime.query("entity", structured=_request(), view=invalid_view)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"^structured entity query request is invalid$"):
        runtime.query("entity", "Owner A", structured=_request(), view="player")
    old_result = runtime.query("entity", "Owner A", view="player")
    assert "Owner A" in old_result.text
    assert tree_digest(save.parent) == before


def test_category_matching_uses_the_same_nfkc_casefold_for_request_and_sqlite(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    db_path = save / "data" / "game.sqlite"
    with sqlite3.connect(db_path) as conn:
        _insert_item(
            conn,
            entity_id="item:unicode-category",
            name="Unicode Category",
            quantity=9,
            unit="支",
            category="Straße",
        )
        conn.commit()
    before = tree_digest(save.parent)

    result = GMRuntime.from_path(save).query(
        "entity",
        structured=_request(category="ＳＴＲＡＳＳＥ"),
        view="player",
    )

    assert result.data["category"] == "strasse"
    assert result.data["members"] == [
        {"id": "item:unicode-category", "name": "Unicode Category", "quantity": 9.0, "unit": "支"}
    ]
    assert result.data["totals"] == [{"unit": "支", "quantity": 9.0}]
    assert tree_digest(save.parent) == before


def test_quantity_overflow_has_fixed_safe_error_and_zero_write(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    db_path = save / "data" / "game.sqlite"
    with sqlite3.connect(db_path) as conn:
        _insert_item(
            conn,
            entity_id="item:overflow-a",
            name="Overflow A",
            quantity=1e308,
            unit="overflow-unit",
        )
        _insert_item(
            conn,
            entity_id="item:overflow-b",
            name="Overflow B",
            quantity=1e308,
            unit="overflow-unit",
        )
        conn.commit()
    before = tree_digest(save.parent)

    with pytest.raises(ValueError, match=r"^structured entity query is unavailable$"):
        GMRuntime.from_path(save).query("entity", structured=_request(), view="player")

    assert tree_digest(save.parent) == before


def test_renderer_preserves_round_trip_quantity_text(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    db_path = save / "data" / "game.sqlite"
    with sqlite3.connect(db_path) as conn:
        _insert_item(
            conn,
            entity_id="item:render-precision",
            name="Render Precision",
            quantity=1234567.125,
            unit="份",
            category="render-precision",
        )
        conn.commit()
    before = tree_digest(save.parent)

    result = GMRuntime.from_path(save).query(
        "entity",
        structured=_request(category="render-precision"),
        view="player",
    )

    assert result.data["members"][0]["quantity"] == 1234567.125
    assert result.data["totals"] == [{"unit": "份", "quantity": 1234567.125}]
    assert result.text.count("1234567.125份") == 2
    assert tree_digest(save.parent) == before


def test_cancelling_finite_quantities_are_exact_and_order_independent(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    db_path = save / "data" / "game.sqlite"
    rows = (
        ("item:cancel-a", 1e308, "cancellation-one"),
        ("item:cancel-b", 1e308, "cancellation-one"),
        ("item:cancel-c", -1e308, "cancellation-one"),
        ("item:cancel-d", 1e308, "cancellation-two"),
        ("item:cancel-e", -1e308, "cancellation-two"),
        ("item:cancel-f", 1e308, "cancellation-two"),
    )
    with sqlite3.connect(db_path) as conn:
        for entity_id, quantity, category in rows:
            _insert_item(
                conn,
                entity_id=entity_id,
                name=entity_id,
                quantity=quantity,
                unit="份",
                category=category,
            )
        conn.commit()
    before = tree_digest(save.parent)
    runtime = GMRuntime.from_path(save)

    first = runtime.query(
        "entity",
        structured=_request(category="cancellation-one"),
        view="player",
    )
    second = runtime.query(
        "entity",
        structured=_request(category="cancellation-two"),
        view="player",
    )

    assert first.data["totals"] == [{"unit": "份", "quantity": 1e308}]
    assert second.data["totals"] == first.data["totals"]
    assert "1e+308份" in first.text
    assert "1e+308份" in second.text
    assert tree_digest(save.parent) == before


def test_hidden_rows_cannot_change_an_identical_visible_collection(tmp_path: Path) -> None:
    results = []
    for index, include_hidden_collision in enumerate((False, True)):
        save = copy_initialized_minimal(tmp_path / str(index))
        db_path = save / "data" / "game.sqlite"
        with sqlite3.connect(db_path) as conn:
            _insert_item(
                conn,
                entity_id="item:visible-protocol",
                name="Shared Protocol Token",
                quantity=1,
                unit="份",
                category="collision-test",
            )
            if include_hidden_collision:
                _insert_item(
                    conn,
                    entity_id="item:hidden-protocol",
                    name="Shared Protocol Token",
                    quantity=999,
                    unit="份",
                    category="hidden-collision",
                    visibility="hidden",
                )
            conn.commit()
        before = tree_digest(save)
        result = GMRuntime.from_path(save).query(
            "entity",
            structured=_request(category="collision-test"),
            view="player",
        )
        results.append(result.to_dict())
        assert result.data["members"] == [
            {
                "id": "item:visible-protocol",
                "name": "Shared Protocol Token",
                "quantity": 1.0,
                "unit": "份",
            }
        ]
        assert "Shared Protocol Token" in result.text
        assert tree_digest(save) == before

    assert results[0] == results[1]


def test_direct_service_preserves_caller_connection_and_transaction(
    aggregate_save: tuple[Path, str, str],
) -> None:
    save, _, _ = aggregate_save
    campaign = GMRuntime.from_path(save).campaign
    conn = connect(campaign)
    try:
        conn.execute("begin")
        conn.execute("create temp table caller_owned_marker(value text)")
        conn.execute("insert into caller_owned_marker values ('open')")
        result = collect_entity_query(conn, _request(), view="player")
        assert result.member_count == 7
        for invalid_view in ("bogus", True, None):
            with pytest.raises(ValueError, match=r"^structured entity query is player-only$"):
                collect_entity_query(conn, _request(), view=invalid_view)  # type: ignore[arg-type]
        assert conn.in_transaction
        assert conn.execute("select value from temp.caller_owned_marker").fetchone()[0] == "open"
        conn.rollback()
        assert conn.execute("select 1").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.skipif(
    not CURRENT_CAMPAIGN_ROOT.exists() or not CURRENT_SAVE_ROOT.exists(),
    reason="requires configured current-native Campaign and Save",
)
def test_current_native_all_ammunition_matches_complete_sqlite_oracle_on_temp_copy(tmp_path: Path) -> None:
    formal_campaign_before = tree_digest(CURRENT_CAMPAIGN_ROOT)
    formal_save_before = tree_digest(CURRENT_SAVE_ROOT)
    formal_registry_before = _path_snapshot(FORMAL_REGISTRY)
    try:
        save = copy_current_packages(tmp_path)
        db_path = save / "data" / "game.sqlite"
        with sqlite3.connect(db_path) as conn:
            rows = _visible_item_rows(conn, "ammunition")
        assert len(rows) >= 2
        expected = [
            {"id": str(row["id"]), "name": str(row["name"]), "quantity": row["quantity"], "unit": row["unit"]}
            for row in rows
        ]
        before_temp = tree_digest(save)

        result = GMRuntime.from_path(save).query("entity", structured=_request(), view="player")

        assert result.data["members"] == expected
        assert result.data["member_count"] == len(expected)
        assert result.data["totals"] == _expected_totals(rows)
        assert all(member["id"] in result.text for member in expected)
        assert tree_digest(save) == before_temp
    finally:
        assert tree_digest(CURRENT_CAMPAIGN_ROOT) == formal_campaign_before
        assert tree_digest(CURRENT_SAVE_ROOT) == formal_save_before
        assert _path_snapshot(FORMAL_REGISTRY) == formal_registry_before


def test_two_campaigns_reuse_the_same_contract_and_remain_isolated(tmp_path: Path) -> None:
    source_before = {root.name: tree_digest(root) for root in EXAMPLE_CAMPAIGNS}
    try:
        results: list[dict[str, object]] = []
        expected_members: list[list[dict[str, object]]] = []
        for root in EXAMPLE_CAMPAIGNS:
            save = tmp_path / root.name / "save"
            assert init_v1_save(root, save)["ok"] is True
            db_path = save / "data" / "game.sqlite"
            with sqlite3.connect(db_path) as conn:
                rows = _visible_item_rows(conn, "supply")
            members = [
                {
                    "id": str(row["id"]),
                    "name": str(row["name"]),
                    "quantity": row["quantity"],
                    "unit": row["unit"],
                }
                for row in rows
            ]
            expected_members.append(members)
            before = tree_digest(save)
            result = GMRuntime.from_path(save).query(
                "entity",
                structured=_request(category="supply", aggregation="quantity"),
                view="player",
            )
            results.append(result.data)
            assert result.data["members"] == members
            assert result.data["member_count"] == len(members)
            assert result.data["totals"] == _expected_totals(rows)
            assert tree_digest(save) == before

        assert results[0]["contract"] == results[1]["contract"]
        assert results[0]["authority"] == results[1]["authority"]
        expected_ids = [{member["id"] for member in members} for members in expected_members]
        assert expected_ids[0].isdisjoint(expected_ids[1])
        for index, data in enumerate(results):
            foreign = expected_ids[1 - index]
            assert all(member["id"] not in foreign for member in data["members"])
    finally:
        assert {root.name: tree_digest(root) for root in EXAMPLE_CAMPAIGNS} == source_before
