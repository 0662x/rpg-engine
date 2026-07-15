from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest

from rpg_engine.intent_router import ActionIntent, TurnContract
from rpg_engine.proposal import TurnProposal
from rpg_engine.runtime import GMRuntime
from tests.automation_support.domain_environment import meta_value


CONSUMPTION_ITEM_ID = "item:v1-515c3e4a2f"
CRAFT_MATERIAL_ID = "item:v1-515c3e4a2f"
CRAFT_OUTPUT_ID = "item:test-thorn-bolt-batch"
MISMATCH_ITEM_ID = "item:black-powder"


@pytest.fixture
def structured_delta_builder() -> Callable[..., dict[str, Any]]:
    return build_structured_delta


def build_structured_delta(
    runtime: GMRuntime,
    *,
    scenario: str,
    invalid_case: str | None = None,
) -> dict[str, Any]:
    save = runtime.campaign.root
    if scenario in {"consumption_success", "consumption_metadata", "consumption_invalid"}:
        return _consumption_case(save, invalid_case=invalid_case if scenario == "consumption_invalid" else None)
    if scenario == "craft_gm_resolved":
        return _craft_case(save)
    raise ValueError(f"unknown structured delta scenario: {scenario}")


def _consumption_case(save: Path, *, invalid_case: str | None) -> dict[str, Any]:
    row = _item_row(save, CONSUMPTION_ITEM_ID)
    before = float(row["quantity"])
    consumed = 0.5
    after = before - consumed
    payload_item_id = CONSUMPTION_ITEM_ID
    expected_error: str | None = None
    if invalid_case == "insufficient":
        consumed = before + 1.0
        after = 0.0
        expected_error = "insufficient quantity"
    elif invalid_case == "stale_before":
        before += 1.0
        expected_error = "stale before_quantity"
    elif invalid_case == "item_mismatch":
        payload_item_id = MISMATCH_ITEM_ID
        expected_error = "missing/duplicate target upsert"
    elif invalid_case == "malformed_quantity":
        consumed = -0.5
        expected_error = "non-positive consumed_quantity"
    elif invalid_case == "sub_ulp_noop":
        consumed = math.ulp(before) / 4
        after = math.nextafter(before, -math.inf)
        expected_error = "arithmetic mismatch"
    elif invalid_case == "extra_item_field":
        expected_error = "unexpected item field"
    elif invalid_case is not None:
        raise ValueError(f"unknown invalid consumption case: {invalid_case}")

    actual_before = float(row["quantity"])
    user_text = "结构化记录：消耗半米备用纤维绳"
    delta = _base_delta(save, action="routine", user_text=user_text)
    delta["summary"] = f"{user_text}；库存备用纤维绳 {actual_before:g}->{after:g}m。"
    delta["events"][0]["summary"] = delta["summary"]
    delta["events"][0]["payload"].update(
        {
            "consumed_item_id": payload_item_id,
            "before_quantity": before,
            "consumed_quantity": consumed,
            "after_quantity": after,
            "unit": row["unit"],
            "material_consumption_required": True,
        }
    )
    delta["upsert_entities"] = [_entity_payload(row, quantity=after)]
    if invalid_case == "extra_item_field":
        delta["upsert_entities"][0]["item"]["future_metadata"] = {"must_persist": True}
    options = {"task": user_text, "target": CONSUMPTION_ITEM_ID, "user_text": user_text}
    return {
        "delta": delta,
        "proposal": _human_proposal("routine", options, delta),
        "target_id": CONSUMPTION_ITEM_ID,
        "before_quantity": actual_before,
        "consumed_quantity": 0.5,
        "after_quantity": actual_before - 0.5,
        "expected_error": expected_error,
    }


def _craft_case(save: Path) -> dict[str, Any]:
    material = _item_row(save, CRAFT_MATERIAL_ID)
    before = float(material["quantity"])
    consumed = 0.5
    after = before - consumed
    user_text = "结构化结算：用备用纤维绳装配一批渊刺藤箭"
    delta = _base_delta(save, action="craft", user_text=user_text)
    output = {
        "id": CRAFT_OUTPUT_ID,
        "type": "item",
        "name": "渊刺藤测试箭批次",
        "status": "active",
        "visibility": "known",
        "location_id": meta_value(save, "current_location_id"),
        "owner_id": None,
        "summary": "临时 Save 中按已确认配方装配的一批渊刺藤测试箭。",
        "details": {
            "quantity_confidence": "confirmed",
            "recipe_id": "recipe:thorn-bolt-assembly",
            "source": "structured_delta_builder",
        },
        "aliases": [],
        "item": {
            "category": "ammunition",
            "quantity": 1.0,
            "unit": "批",
            "quality": "standard",
            "durability_current": None,
            "durability_max": None,
            "stackable": True,
            "equipped_slot": None,
            "properties": {"recipe_id": "recipe:thorn-bolt-assembly"},
        },
    }
    delta["summary"] = f"{user_text}；备用纤维绳 {before:g}->{after:g}m，产出1批。"
    delta["events"][0] = {
        "type": "craft",
        "title": "制作行动结算",
        "summary": delta["summary"],
        "payload": {
            "recipe_id": "recipe:thorn-bolt-assembly",
            "target_id": CRAFT_OUTPUT_ID,
            "target_name": "临时结构化箭批次",
            "location_id": meta_value(save, "current_location_id"),
            "time_cost": "1小时",
            "materials": [{"entity_id": CRAFT_MATERIAL_ID, "consumed_quantity": consumed, "unit": "m"}],
            "material_consumption_required": True,
            "output_entity_required": True,
            "output_entity_id": CRAFT_OUTPUT_ID,
            "needs_gm_resolution": False,
        },
        "source": "structured_delta_builder",
    }
    material_payload = _entity_payload(material, quantity=after)
    delta["upsert_entities"] = [material_payload, output]
    options = {
        "project": "recipe:thorn-bolt-assembly",
        "target": "临时结构化箭批次",
        "materials": "备用纤维绳",
        "time_cost": "1小时",
        "user_text": user_text,
    }
    return {
        "delta": delta,
        "proposal": _human_proposal("craft", options, delta),
        "material_id": CRAFT_MATERIAL_ID,
        "material_after_quantity": after,
        "output_id": CRAFT_OUTPUT_ID,
        "expected_output": _snapshot_payload(output),
    }


def _base_delta(save: Path, *, action: str, user_text: str) -> dict[str, Any]:
    current_location = meta_value(save, "current_location_id")
    current_time = meta_value(save, "current_time_block")
    return {
        "expected_turn_id": meta_value(save, "current_turn_id"),
        "command_id": f"test-{action}-structured-delta",
        "user_text": user_text,
        "intent": action,
        "changed": True,
        "game_time_before": current_time,
        "game_time_after": current_time,
        "location_before": current_location,
        "location_after": current_location,
        "summary": user_text,
        "events": [
            {
                "type": action,
                "title": "结构化领域结算",
                "summary": user_text,
                "payload": {"task": user_text, "state_changes_must_be_structured": True},
                "source": "structured_delta_builder",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }


def _human_proposal(action: str, options: dict[str, Any], delta: dict[str, Any]) -> TurnProposal:
    intent = ActionIntent(
        user_text=str(options["user_text"]),
        mode="action",
        submode=action,
        action=action,
        options=options,
        confidence="high",
        source="structured_test_candidate",
    )
    contract = TurnContract(
        intent=intent,
        required_template=f"{action}_turn.md",
        response_headings=("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
        requires_preview=True,
        must_save=True,
        allowed_delta_sources=("resolver_proposed", "ai_generated", "human_edited", "response_draft"),
        validation_profile="player_turn_commit",
    )
    digest = hashlib.sha256(json.dumps(delta, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return TurnProposal(
        proposal_id=f"turn-proposal:test:{action}:{digest}",
        intent=intent,
        preview={"action": action, "status": "ready", "facts_used": [], "rules_applied": []},
        delta=delta,
        delta_source="human_edited",
        provenance={"source": "structured_delta_builder", "resolver": action},
        human_confirmed=True,
        turn_contract=contract,
    )


def _item_row(save: Path, entity_id: str) -> dict[str, Any]:
    with sqlite3.connect(save / "data" / "game.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            select e.id, e.type, e.name, e.status, e.visibility, e.location_id, e.owner_id,
                   e.summary, e.details_json, i.category, i.quantity, i.unit, i.quality,
                   i.durability_current, i.durability_max, i.stackable, i.equipped_slot,
                   i.properties_json
            from entities e join items i on i.entity_id=e.id where e.id=?
            """,
            (entity_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"missing current-native item: {entity_id}")
        data = dict(row)
        data["aliases"] = [
            str(item[0])
            for item in conn.execute(
                "select alias from aliases where entity_id=? and kind='name' order by alias",
                (entity_id,),
            )
        ]
    return data


def _entity_payload(row: dict[str, Any], *, quantity: float) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "status": row["status"],
        "visibility": row["visibility"],
        "location_id": row["location_id"],
        "owner_id": row["owner_id"],
        "summary": row["summary"],
        "details": json.loads(row["details_json"] or "{}"),
        "aliases": list(row["aliases"]),
        "item": {
            "category": row["category"],
            "quantity": quantity,
            "unit": row["unit"],
            "quality": row["quality"],
            "durability_current": row["durability_current"],
            "durability_max": row["durability_max"],
            "stackable": bool(row["stackable"]),
            "equipped_slot": row["equipped_slot"],
            "properties": json.loads(row["properties_json"] or "{}"),
        },
    }


def _snapshot_payload(entity: dict[str, Any]) -> dict[str, Any]:
    item = entity["item"]
    return {
        "id": entity["id"],
        "type": entity["type"],
        "name": entity["name"],
        "status": entity["status"],
        "visibility": entity["visibility"],
        "location_id": entity.get("location_id"),
        "owner_id": entity.get("owner_id"),
        "summary": entity["summary"],
        "details": deepcopy(entity["details"]),
        "aliases": list(entity.get("aliases", [])),
        "category": item["category"],
        "quantity": float(item["quantity"]),
        "unit": item.get("unit"),
        "quality": item.get("quality"),
        "durability_current": item.get("durability_current"),
        "durability_max": item.get("durability_max"),
        "stackable": bool(item.get("stackable")),
        "equipped_slot": item.get("equipped_slot"),
        "properties": deepcopy(item.get("properties", {})),
    }
