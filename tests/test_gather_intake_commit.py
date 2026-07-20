from __future__ import annotations

import json
import shutil
import sqlite3
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from rpg_engine.campaign import Campaign, load_campaign
from rpg_engine.db import connect, init_database, upsert_entity
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import (
    CONFIRMATION_CLAIM_META_KEY,
    CONFIRMATION_RECEIPT_META_KEY,
    SaveManager,
)
from tests.helpers import tree_digest
from tests.test_gather_intake_validation import (
    EXISTING_OUTPUT_ID,
    HIDDEN_LOCATION_ID,
    HIDDEN_OWNER_ID,
    INVALID_EXISTING_UPDATE_CASES,
    INVALID_INTAKE_CASES,
    LOCATION_ID,
    OFFICIAL_EXAMPLE,
    OUTPUT_ID,
    OWNER_ID,
    OTHER_LOCATION_ID,
    RETIRED_LOCATION_ID,
    RETIRED_OWNER_ID,
    _base_delta,
    _existing_update_delta,
    _invalid_delta,
    _invalid_existing_update,
    _hide_subtype_owner_anchors,
    _output_entity,
    _proposal,
)

def _fresh_campaign(root: Path) -> Campaign:
    shutil.copytree(OFFICIAL_EXAMPLE, root)
    campaign = load_campaign(root)
    init_database(campaign, force=True)
    with connect(campaign) as conn:
        for entity in (
            {
                "id": OTHER_LOCATION_ID,
                "type": "location",
                "name": "Other Intake Location",
                "status": "active",
                "visibility": "known",
                "summary": "A second temporary location.",
            },
            {
                "id": RETIRED_LOCATION_ID,
                "type": "location",
                "name": "Retired Intake Location",
                "status": "retired",
                "visibility": "known",
                "summary": "A retired temporary location.",
            },
            {
                "id": RETIRED_OWNER_ID,
                "type": "character",
                "name": "Retired Intake Owner",
                "status": "retired",
                "visibility": "known",
                "summary": "A retired temporary owner.",
            },
            {
                "id": HIDDEN_LOCATION_ID,
                "type": "location",
                "name": "Hidden Intake Location",
                "status": "active",
                "visibility": "gm-only",
                "summary": "A hidden temporary location.",
            },
            {
                "id": HIDDEN_OWNER_ID,
                "type": "character",
                "name": "Hidden Intake Owner",
                "status": "active",
                "visibility": "hidden",
                "summary": "A hidden temporary owner.",
            },
            _output_entity(
                EXISTING_OUTPUT_ID,
                quantity=1.5,
                location_id=None,
                owner_id=OWNER_ID,
            ),
        ):
            upsert_entity(conn, entity)
        _hide_subtype_owner_anchors(conn)
        conn.commit()
    return campaign


def _inventory_snapshot(campaign: Campaign) -> dict[str, dict[str, Any]]:
    with connect(campaign) as conn:
        rows = conn.execute(
            """
            select e.id, e.type, e.name, e.status, e.visibility, e.location_id,
                   e.owner_id, e.summary, e.details_json,
                   i.category, i.quantity, i.unit, i.quality,
                   i.durability_current, i.durability_max, i.stackable,
                   i.equipped_slot, i.properties_json
            from entities e
            join items i on i.entity_id = e.id
            order by e.id
            """
        ).fetchall()
        snapshot: dict[str, dict[str, Any]] = {}
        for row in rows:
            aliases = [
                str(alias["alias"])
                for alias in conn.execute(
                    "select alias from aliases where entity_id=? and kind='name' order by alias",
                    (row["id"],),
                ).fetchall()
            ]
            snapshot[str(row["id"])] = {
                "type": row["type"],
                "name": row["name"],
                "status": row["status"],
                "visibility": row["visibility"],
                "location_id": row["location_id"],
                "owner_id": row["owner_id"],
                "summary": row["summary"],
                "details": json.loads(row["details_json"] or "{}"),
                "aliases": aliases,
                "category": row["category"],
                "quantity": row["quantity"],
                "unit": row["unit"],
                "quality": row["quality"],
                "durability_current": row["durability_current"],
                "durability_max": row["durability_max"],
                "stackable": bool(row["stackable"]),
                "equipped_slot": row["equipped_slot"],
                "properties": json.loads(row["properties_json"] or "{}"),
            }
    return snapshot


def _fact_snapshot(campaign: Campaign) -> dict[str, Any]:
    with connect(campaign) as conn:
        logical_dump = "\n".join(conn.iterdump())
        turn_count = int(conn.execute("select count(*) from turns").fetchone()[0])
        event_count = int(conn.execute("select count(*) from events").fetchone()[0])
    return {
        "database": campaign.database_path.read_bytes(),
        "logical_dump": logical_dump,
        "events_jsonl": campaign.events_path.read_bytes(),
        "inventory": _inventory_snapshot(campaign),
        "turn_count": turn_count,
        "event_count": event_count,
    }


def _other_entity_snapshot(campaign: Campaign, excluded_id: str) -> dict[str, tuple[Any, ...]]:
    with connect(campaign) as conn:
        rows = conn.execute(
            """
            select e.id, e.type, e.name, e.status, e.visibility, e.location_id,
                   e.owner_id, e.summary, e.details_json,
                   c.segments_filled, c.segments_total, c.last_ticked_turn_id
            from entities e
            left join clocks c on c.entity_id = e.id
            where e.id != ?
            order by e.id
            """,
            (excluded_id,),
        ).fetchall()
    return {
        str(row["id"]): tuple(row[key] for key in row.keys() if key != "id")
        for row in rows
    }


def _commit(runtime: GMRuntime, delta: dict[str, Any]) -> Any:
    proposal = _proposal(delta)
    return runtime.commit_turn(
        delta,
        turn_proposal=proposal,
        backup=False,
        action="gather",
        action_options=dict(proposal.intent.options),
        state_audit=False,
        state_audit_ai="off",
    )


def _assert_single_gather_event(campaign: Campaign, turn_id: str, delta: dict[str, Any]) -> None:
    with connect(campaign) as conn:
        rows = conn.execute(
            """
            select id, game_time, type, title, summary, payload_json, source
            from events
            where turn_id=?
            order by id
            """,
            (turn_id,),
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    expected = delta["events"][0]
    assert row["type"] == "gather"
    assert row["title"] == expected["title"]
    assert row["summary"] == expected["summary"]
    assert row["source"] == expected["source"]
    assert row["game_time"] == expected.get("game_time", delta["game_time_after"])
    assert json.loads(row["payload_json"]) == expected["payload"]
    if "id" in expected:
        assert row["id"] == expected["id"]


def _assert_item_updated_turn(campaign: Campaign, entity_id: str, turn_id: str) -> None:
    with connect(campaign) as conn:
        row = conn.execute(
            "select updated_turn_id from entities where id = ?",
            (entity_id,),
        ).fetchone()
    assert row is not None
    assert row["updated_turn_id"] == turn_id


def test_confirmed_intake_creates_exactly_one_item_turn_and_event(tmp_path: Path) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    runtime = GMRuntime.from_path(campaign.root)
    delta = _base_delta(campaign)
    before = _fact_snapshot(campaign)
    other_entities_before = _other_entity_snapshot(campaign, OUTPUT_ID)

    result = _commit(runtime, delta)

    after = _fact_snapshot(campaign)
    assert result.ok
    assert OUTPUT_ID not in before["inventory"]
    expected_inventory = deepcopy(before["inventory"])
    expected_inventory[OUTPUT_ID] = {
        "type": "item",
        "name": "Test Intake Herb",
        "status": "active",
        "visibility": "known",
        "location_id": LOCATION_ID,
        "owner_id": None,
        "summary": "A temporary structured Intake validation fixture.",
        "details": {"source": "story-1.10", "nested": {"preserve": True}},
        "aliases": ["intake herb", "测试入库草药"],
        "category": "material",
        "quantity": 2.0,
        "unit": "bundle",
        "quality": "standard",
        "durability_current": None,
        "durability_max": None,
        "stackable": True,
        "equipped_slot": None,
        "properties": {"fresh": True, "grade": 2},
    }
    assert after["inventory"] == expected_inventory
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
    assert _other_entity_snapshot(campaign, OUTPUT_ID) == other_entities_before
    _assert_single_gather_event(campaign, result.turn_id, delta)
    _assert_item_updated_turn(campaign, OUTPUT_ID, result.turn_id)


def test_confirmed_intake_updates_only_declared_quantity_and_preserves_metadata(tmp_path: Path) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    runtime = GMRuntime.from_path(campaign.root)
    delta = _existing_update_delta(campaign)
    delta["upsert_entities"][0]["aliases"] = ["测试入库草药", "intake herb"]
    before = _fact_snapshot(campaign)
    other_entities_before = _other_entity_snapshot(campaign, EXISTING_OUTPUT_ID)
    expected_item = deepcopy(before["inventory"][EXISTING_OUTPUT_ID])
    expected_item["quantity"] = 3.0

    result = _commit(runtime, delta)

    after = _fact_snapshot(campaign)
    assert after["inventory"][EXISTING_OUTPUT_ID] == expected_item
    assert {
        key: value for key, value in after["inventory"].items() if key != EXISTING_OUTPUT_ID
    } == {
        key: value for key, value in before["inventory"].items() if key != EXISTING_OUTPUT_ID
    }
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
    assert _other_entity_snapshot(campaign, EXISTING_OUTPUT_ID) == other_entities_before
    _assert_single_gather_event(campaign, result.turn_id, delta)
    _assert_item_updated_turn(campaign, EXISTING_OUTPUT_ID, result.turn_id)


def test_confirmed_intake_can_change_declared_unit_and_ownership_only(tmp_path: Path) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    runtime = GMRuntime.from_path(campaign.root)
    delta = _existing_update_delta(campaign)
    payload = delta["events"][0]["payload"]
    target = delta["upsert_entities"][0]
    payload["output_unit"] = "kg"
    target["item"]["unit"] = "kg"
    payload["owner_id"] = None
    payload["location_id"] = LOCATION_ID
    target["owner_id"] = None
    target["location_id"] = LOCATION_ID
    before = _fact_snapshot(campaign)
    other_entities_before = _other_entity_snapshot(campaign, EXISTING_OUTPUT_ID)
    expected_item = deepcopy(before["inventory"][EXISTING_OUTPUT_ID])
    expected_item.update({"quantity": 3.0, "unit": "kg", "owner_id": None, "location_id": LOCATION_ID})

    result = _commit(runtime, delta)

    after = _fact_snapshot(campaign)
    assert result.ok
    assert after["inventory"][EXISTING_OUTPUT_ID] == expected_item
    assert {
        key: value for key, value in after["inventory"].items() if key != EXISTING_OUTPUT_ID
    } == {
        key: value for key, value in before["inventory"].items() if key != EXISTING_OUTPUT_ID
    }
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
    assert _other_entity_snapshot(campaign, EXISTING_OUTPUT_ID) == other_entities_before
    _assert_single_gather_event(campaign, result.turn_id, delta)
    _assert_item_updated_turn(campaign, EXISTING_OUTPUT_ID, result.turn_id)


@pytest.mark.parametrize("case", [case for case, _reason in INVALID_INTAKE_CASES])
def test_invalid_intake_commit_preserves_sqlite_events_entities_and_pending_state(
    tmp_path: Path,
    case: str,
) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    pending_root = campaign.root / ".aigm"
    pending_root.mkdir()
    (pending_root / "pending-player-action.json").write_text('{"sentinel":"action"}\n', encoding="utf-8")
    (pending_root / "pending-player-clarification.json").write_text(
        '{"sentinel":"clarification"}\n',
        encoding="utf-8",
    )
    pending_before = {
        path.name: path.read_bytes() for path in sorted(pending_root.iterdir()) if path.is_file()
    }
    runtime = GMRuntime.from_path(campaign.root)
    delta = _invalid_delta(campaign, case)
    before = _fact_snapshot(campaign)

    with pytest.raises(ValueError, match="gather intake:"):
        _commit(runtime, delta)

    assert _fact_snapshot(campaign) == before
    assert {
        path.name: path.read_bytes() for path in sorted(pending_root.iterdir()) if path.is_file()
    } == pending_before


@pytest.mark.parametrize(
    ("synchronize_delta_intent", "event_type"),
    [(False, "gather"), (True, "gather"), (True, "routine")],
)
def test_proposal_action_cannot_bypass_gather_intake_gate(
    tmp_path: Path,
    synchronize_delta_intent: bool,
    event_type: str,
) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    runtime = GMRuntime.from_path(campaign.root)
    delta = _invalid_delta(campaign, "zero")
    proposal = _proposal(delta)
    assert proposal.turn_contract is not None
    routine_intent = replace(
        proposal.intent,
        submode="routine",
        action="routine",
        options={"task": "Rest", "user_text": delta["user_text"]},
    )
    forged = replace(
        proposal,
        intent=routine_intent,
        turn_contract=replace(proposal.turn_contract, intent=routine_intent),
    )
    if synchronize_delta_intent:
        delta["intent"] = "routine"
    delta["events"][0]["type"] = event_type
    before = _fact_snapshot(campaign)

    with pytest.raises(ValueError, match="gather intake: direct Intake declaration requires gather resolver"):
        runtime.commit_turn(
            delta,
            turn_proposal=forged,
            backup=False,
            state_audit=False,
            state_audit_ai="off",
        )

    assert _fact_snapshot(campaign) == before


@pytest.mark.parametrize("case", [case for case, _reason in INVALID_EXISTING_UPDATE_CASES])
def test_existing_metadata_drift_commit_preserves_all_authoritative_state(
    tmp_path: Path,
    case: str,
) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    runtime = GMRuntime.from_path(campaign.root)
    before = _fact_snapshot(campaign)

    with pytest.raises(ValueError, match="gather intake:"):
        _commit(runtime, _invalid_existing_update(campaign, case))

    assert _fact_snapshot(campaign) == before


@pytest.mark.parametrize(
    ("table", "column", "value", "reason"),
    [
        ("entities", "details_json", "{broken", "invalid live metadata: entity.details"),
        ("items", "properties_json", "[1, 2]", "invalid live metadata: item.properties"),
        ("items", "stackable", 2, "invalid live metadata: item.stackable"),
        ("entities", "type", "equipment", "existing target must be an item"),
        ("entities", "type", "ITEM", "existing target must be an item"),
        ("entities", "visibility", "hidden", "hidden output target"),
        (
            "entities",
            "visibility",
            "not-a-visibility",
            "invalid live metadata: entity.visibility",
        ),
        (
            "items",
            "properties_json",
            '{"fresh":true,"grade":1,"grade":2}',
            "invalid live metadata: item.properties",
        ),
    ],
)
def test_corrupt_live_metadata_fails_with_stable_error_without_writes(
    tmp_path: Path,
    table: str,
    column: str,
    value: Any,
    reason: str,
) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    with connect(campaign) as conn:
        conn.execute(
            f"update {table} set {column} = ? where "  # noqa: S608
            + ("id = ?" if table == "entities" else "entity_id = ?"),
            (value, EXISTING_OUTPUT_ID),
        )
        conn.commit()
    with connect(campaign) as conn:
        logical_before = "\n".join(conn.iterdump())
    database_before = campaign.database_path.read_bytes()
    events_before = campaign.events_path.read_bytes()
    runtime = GMRuntime.from_path(campaign.root)

    with pytest.raises(ValueError, match=f"gather intake: {reason}"):
        _commit(runtime, _existing_update_delta(campaign))

    with connect(campaign) as conn:
        assert "\n".join(conn.iterdump()) == logical_before
    assert campaign.database_path.read_bytes() == database_before
    assert campaign.events_path.read_bytes() == events_before


def test_signed_zero_live_metadata_cannot_be_silently_rewritten(tmp_path: Path) -> None:
    campaign = _fresh_campaign(tmp_path / "campaign")
    with connect(campaign) as conn:
        conn.execute(
            "update items set properties_json = ? where entity_id = ?",
            ('{"fresh":true,"grade":-0.0}', EXISTING_OUTPUT_ID),
        )
        conn.commit()
    delta = _existing_update_delta(campaign)
    delta["upsert_entities"][0]["item"]["properties"]["grade"] = 0.0
    database_before = campaign.database_path.read_bytes()
    events_before = campaign.events_path.read_bytes()

    with pytest.raises(ValueError, match="gather intake: metadata mismatch: item.properties"):
        _commit(GMRuntime.from_path(campaign.root), delta)

    assert campaign.database_path.read_bytes() == database_before
    assert campaign.events_path.read_bytes() == events_before


def _manager_with_temp_save(tmp_path: Path) -> tuple[SaveManager, Path, Path]:
    workspace = tmp_path / "workspace"
    campaign_source = workspace / "campaign"
    shutil.copytree(OFFICIAL_EXAMPLE, campaign_source)
    manager = SaveManager(workspace)
    manager.register_campaign("campaign")
    created = manager.create_save(campaign="campaign", kind="test", label="Story 1.10 temporary Save")
    assert created["ok"], created
    save = workspace / created["save"]["path"]
    return manager, save, campaign_source


def _replace_pending_with_intake(
    manager: SaveManager,
    save: Path,
    *,
    invalid_case: str | None = None,
    existing_update: bool = False,
) -> tuple[str, dict[str, Any]]:
    acted = manager.player_turn(user_text="Rest until morning")
    assert acted["ready_to_confirm"], acted
    pending = manager.read_pending_action()
    assert pending is not None
    campaign = load_campaign(save)
    if invalid_case:
        delta = _invalid_delta(campaign, invalid_case)
    elif existing_update:
        delta = _existing_update_delta(campaign)
    else:
        delta = _base_delta(campaign)
    proposal = _proposal(delta).to_dict()
    proposal["human_confirmed"] = False
    manager.write_pending_action(
        {
            **pending,
            "user_text": delta["user_text"],
            "action": "gather",
            "delta": delta,
            "turn_proposal": proposal,
        }
    )
    return str(acted["session_id"]), delta


def _confirmation_anchors(save: Path) -> dict[str, str]:
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        rows = conn.execute(
            "select key, value from meta where key in (?, ?) order by key",
            (CONFIRMATION_CLAIM_META_KEY, CONFIRMATION_RECEIPT_META_KEY),
        ).fetchall()
    return {str(key): str(value) for key, value in rows}


def _optional_tree_digest(path: Path) -> str | None:
    return tree_digest(path) if path.exists() else None


def test_player_confirm_commits_valid_intake_and_clears_pending_once(tmp_path: Path) -> None:
    manager, save, campaign_source = _manager_with_temp_save(tmp_path)
    source_before = tree_digest(campaign_source)
    session_id, delta = _replace_pending_with_intake(manager, save)
    campaign = load_campaign(save)
    before = _fact_snapshot(campaign)
    other_entities_before = _other_entity_snapshot(campaign, OUTPUT_ID)

    result = manager.player_confirm(session_id)

    after = _fact_snapshot(campaign)
    assert result["saved"] is True
    assert result["write_status"] == "committed"
    assert OUTPUT_ID not in before["inventory"]
    expected_inventory = deepcopy(before["inventory"])
    expected_inventory[OUTPUT_ID] = {
        "type": "item",
        "name": "Test Intake Herb",
        "status": "active",
        "visibility": "known",
        "location_id": LOCATION_ID,
        "owner_id": None,
        "summary": "A temporary structured Intake validation fixture.",
        "details": {"source": "story-1.10", "nested": {"preserve": True}},
        "aliases": ["intake herb", "测试入库草药"],
        "category": "material",
        "quantity": 2.0,
        "unit": "bundle",
        "quality": "standard",
        "durability_current": None,
        "durability_max": None,
        "stackable": True,
        "equipped_slot": None,
        "properties": {"fresh": True, "grade": 2},
    }
    assert after["inventory"] == expected_inventory
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
    assert _other_entity_snapshot(campaign, OUTPUT_ID) == other_entities_before
    assert manager.read_pending_action() is None
    assert manager.confirmation_receipt_path().exists()
    assert _confirmation_anchors(save)[CONFIRMATION_RECEIPT_META_KEY]
    _assert_single_gather_event(campaign, str(result["save"]["current_turn_id"]), delta)
    _assert_item_updated_turn(campaign, OUTPUT_ID, str(result["save"]["current_turn_id"]))
    assert tree_digest(campaign_source) == source_before


def test_player_confirm_updates_existing_item_and_preserves_metadata(tmp_path: Path) -> None:
    manager, save, campaign_source = _manager_with_temp_save(tmp_path)
    source_before = tree_digest(campaign_source)
    campaign = load_campaign(save)
    seed_delta = _existing_update_delta(campaign)
    seed_delta["command_id"] = "test-gather-intake-seed-existing"
    seed_delta["events"][0]["payload"]["output_quantity"] = 1.5
    seed_delta["upsert_entities"][0]["item"]["quantity"] = 1.5
    seed_result = _commit(GMRuntime.from_path(save), seed_delta)
    assert seed_result.ok
    session_id, delta = _replace_pending_with_intake(manager, save, existing_update=True)
    before = _fact_snapshot(campaign)
    other_entities_before = _other_entity_snapshot(campaign, EXISTING_OUTPUT_ID)
    expected_inventory = deepcopy(before["inventory"])
    expected_inventory[EXISTING_OUTPUT_ID]["quantity"] = 3.0

    result = manager.player_confirm(session_id)

    after = _fact_snapshot(campaign)
    assert result["saved"] is True
    assert result["write_status"] == "committed"
    assert after["inventory"] == expected_inventory
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
    assert _other_entity_snapshot(campaign, EXISTING_OUTPUT_ID) == other_entities_before
    assert manager.read_pending_action() is None
    assert manager.confirmation_receipt_path().exists()
    _assert_single_gather_event(campaign, str(result["save"]["current_turn_id"]), delta)
    _assert_item_updated_turn(
        campaign,
        EXISTING_OUTPUT_ID,
        str(result["save"]["current_turn_id"]),
    )
    assert tree_digest(campaign_source) == source_before


@pytest.mark.parametrize(
    "invalid_case",
    [
        "zero",
        "missing-anchors",
        "unknown-owner",
        "retired-location",
        "output-id-mismatch",
        "duplicate-upsert",
        "hidden-output-target",
        "meta-update",
    ],
)
def test_failed_player_confirm_restores_pending_and_all_authoritative_state(
    tmp_path: Path,
    invalid_case: str,
) -> None:
    manager, save, campaign_source = _manager_with_temp_save(tmp_path)
    source_before = tree_digest(campaign_source)
    session_id, _delta = _replace_pending_with_intake(manager, save, invalid_case=invalid_case)
    pending_before = manager.pending_action_path().read_bytes()
    assert not manager.pending_clarification_path().exists()
    campaign = load_campaign(save)
    before = _fact_snapshot(campaign)
    backups_before = _optional_tree_digest(save / "backups")
    assert _confirmation_anchors(save) == {}
    assert not manager.confirmation_receipt_path().exists()

    with pytest.raises(ValueError, match="gather intake:"):
        manager.player_confirm(session_id)

    after = _fact_snapshot(campaign)
    assert after["logical_dump"] == before["logical_dump"]
    assert after["events_jsonl"] == before["events_jsonl"]
    assert after["inventory"] == before["inventory"]
    assert after["turn_count"] == before["turn_count"]
    assert after["event_count"] == before["event_count"]
    assert manager.pending_action_path().read_bytes() == pending_before
    assert not manager.pending_clarification_path().exists()
    assert _confirmation_anchors(save) == {}
    assert not manager.confirmation_receipt_path().exists()
    assert _optional_tree_digest(save / "backups") == backups_before
    assert tree_digest(campaign_source) == source_before
