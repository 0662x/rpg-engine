from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from pathlib import Path
from unittest import mock

import pytest

from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import (
    CONFIRMATION_CLAIM_META_KEY,
    CONFIRMATION_RECEIPT_META_KEY,
    SaveManager,
    confirmation_claim_lock,
)
from tests.automation_support.domain_deltas import build_structured_delta
from tests.automation_support.domain_environment import current_native_temp_save, db_snapshot
from tests.helpers import CURRENT_CAMPAIGN_ROOT, tree_digest


pytestmark = pytest.mark.p0


def _manager_for_save(save: Path) -> SaveManager:
    snapshot = json.loads((save / "snapshots" / "current.json").read_text(encoding="utf-8"))
    snapshot_location = str(snapshot["meta"]["current_location_id"])
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        player_id = str(conn.execute("select value from meta where key='player_entity_id'").fetchone()[0])
        conn.execute("update meta set value=? where key='current_location_id'", (snapshot_location,))
        conn.execute("update entities set location_id=? where id=?", (snapshot_location, player_id))
        conn.commit()
    manager = SaveManager(save.parent)
    campaign_path = CURRENT_CAMPAIGN_ROOT.name
    manager.register_campaign(campaign_path)
    record = manager.build_save_record(
        save_id="routine-consumption-copy",
        campaign_path=campaign_path,
        save_path=save.name,
        label="routine consumption temporary copy",
        kind="test",
        source="story-1.9",
    )
    registry = manager.read_registry()
    registry["active_save_id"] = record["id"]
    registry["saves"] = [record]
    manager.write_registry(registry)
    return manager


def _replace_pending_with_consumption(
    manager: SaveManager,
    save: Path,
    *,
    invalid_case: str | None = None,
) -> tuple[str, dict[str, object]]:
    acted = manager.player_turn(user_text="休息到早上")
    assert acted["ready_to_confirm"], acted
    pending = manager.read_pending_action()
    assert pending is not None
    runtime = GMRuntime.from_path(save)
    scenario = "consumption_invalid" if invalid_case else "consumption_success"
    case = build_structured_delta(runtime, scenario=scenario, invalid_case=invalid_case)
    proposal = case["proposal"].to_dict()
    proposal["human_confirmed"] = False
    rewritten = {
        **pending,
        "user_text": case["delta"]["user_text"],
        "action": "routine",
        "delta": case["delta"],
        "turn_proposal": proposal,
    }
    manager.write_pending_action(rewritten)
    return str(acted["session_id"]), case


def _logical_database_dump(save: Path) -> str:
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        return "\n".join(conn.iterdump())


def _confirmation_anchors(save: Path) -> dict[str, str]:
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        rows = conn.execute(
            "select key, value from meta where key in (?, ?) order by key",
            (CONFIRMATION_CLAIM_META_KEY, CONFIRMATION_RECEIPT_META_KEY),
        ).fetchall()
    return {str(key): str(value) for key, value in rows}


def _inventory_without(snapshot: dict[str, object], target_id: str) -> dict[str, object]:
    inventory = snapshot["inventory"]
    assert isinstance(inventory, dict)
    return {key: deepcopy(value) for key, value in inventory.items() if key != target_id}


def _optional_tree_digest(path: Path) -> str | None:
    return tree_digest(path) if path.exists() else None


def test_player_confirm_commits_consumption_once_and_replay_skips_validation(
    current_native_temp_save: Path,
    db_snapshot,
) -> None:
    """[P0][CON-04] pending→confirm 精确扣量一次；receipt replay 不重入 validation/commit。"""
    save = current_native_temp_save
    manager = _manager_for_save(save)
    campaign_source = save.parent / CURRENT_CAMPAIGN_ROOT.name
    source_before = tree_digest(campaign_source)
    session_id, case = _replace_pending_with_consumption(manager, save)
    before = db_snapshot(save)

    fresh = manager.player_confirm(session_id)

    after_fresh = db_snapshot(save)
    target_id = str(case["target_id"])
    assert fresh["write_status"] == "committed"
    assert fresh["saved"] is True
    assert fresh["idempotent_replay"] is False
    assert after_fresh["inventory"][target_id]["quantity"] == case["after_quantity"]
    assert after_fresh["turn_count"] == before["turn_count"] + 1
    assert after_fresh["event_count"] == before["event_count"] + 1
    assert _inventory_without(after_fresh, target_id) == _inventory_without(before, target_id)
    assert manager.read_pending_action() is None
    assert manager.confirmation_receipt_path().exists()
    receipt = json.loads(manager.confirmation_receipt_path().read_text(encoding="utf-8"))
    anchors_after_fresh = _confirmation_anchors(save)
    assert anchors_after_fresh[CONFIRMATION_CLAIM_META_KEY]
    assert anchors_after_fresh[CONFIRMATION_RECEIPT_META_KEY] == receipt["receipt_digest"]

    with (
        mock.patch.object(GMRuntime, "commit_turn", side_effect=AssertionError("replay re-entered commit")),
        mock.patch(
            "rpg_engine.runtime.run_validation_pipeline",
            side_effect=AssertionError("replay re-entered validation"),
        ),
    ):
        replay = manager.player_confirm(session_id)

    after_replay = db_snapshot(save)
    assert replay["write_status"] == "already_confirmed"
    assert replay["saved"] is False
    assert replay["idempotent_replay"] is True
    assert after_replay["inventory"] == after_fresh["inventory"]
    assert after_replay["turn_count"] == after_fresh["turn_count"]
    assert after_replay["event_count"] == after_fresh["event_count"]
    assert after_replay["events_jsonl"] == after_fresh["events_jsonl"]
    assert _confirmation_anchors(save) == anchors_after_fresh
    assert json.loads(manager.confirmation_receipt_path().read_text(encoding="utf-8")) == receipt
    assert tree_digest(campaign_source) == source_before


def test_failed_player_confirm_restores_pending_and_removes_claim_without_state_mutation(
    current_native_temp_save: Path,
    db_snapshot,
) -> None:
    """[P0][CON-05] 失败确认回滚 claim，保留原 pending，且事实权威状态零变化。"""
    save = current_native_temp_save
    manager = _manager_for_save(save)
    campaign_source = save.parent / CURRENT_CAMPAIGN_ROOT.name
    source_before = tree_digest(campaign_source)
    session_id, _case = _replace_pending_with_consumption(manager, save, invalid_case="stale_before")
    pending_before = manager.pending_action_path().read_bytes()
    snapshot_before = db_snapshot(save)
    logical_before = _logical_database_dump(save)
    backups_before = _optional_tree_digest(save / "backups")
    assert _confirmation_anchors(save) == {}
    assert not manager.confirmation_receipt_path().exists()

    with pytest.raises(ValueError, match="routine consumption: stale before_quantity"):
        manager.player_confirm(session_id)

    snapshot_after = db_snapshot(save)
    assert manager.pending_action_path().read_bytes() == pending_before
    assert _confirmation_anchors(save) == {}
    assert not manager.confirmation_receipt_path().exists()
    assert _logical_database_dump(save) == logical_before
    assert snapshot_after["inventory"] == snapshot_before["inventory"]
    assert snapshot_after["turn_count"] == snapshot_before["turn_count"]
    assert snapshot_after["event_count"] == snapshot_before["event_count"]
    assert snapshot_after["events_jsonl"] == snapshot_before["events_jsonl"]
    assert _optional_tree_digest(save / "backups") == backups_before
    assert tree_digest(campaign_source) == source_before

    with confirmation_claim_lock(manager.confirmation_lock_path(), root=manager.root):
        pass
