from __future__ import annotations

import math
import pickle
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

import pytest

from rpg_engine.campaign import Campaign, load_campaign
from rpg_engine.db import connect, get_meta, init_database, upsert_entity
from rpg_engine.intent_router import ActionIntent, TurnContract
from rpg_engine.proposal import TurnProposal
from rpg_engine.validation_pipeline import ValidationReport, run_validation_pipeline


ENGINE_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_EXAMPLE = ENGINE_ROOT / "rpg_engine" / "resources" / "examples" / "v1_minimal_adventure"
TARGET_ID = "item:test-routine-ration"
OTHER_ID = "item:test-routine-water"
CONSUMPTION_KEYS = ("consumed_item_id", "before_quantity", "consumed_quantity", "after_quantity")


class _HostileKey:
    def __init__(self, mode: str, *, hash_value: int = 17) -> None:
        self.mode = mode
        self.hash_value = hash_value
        self.armed = False

    def __hash__(self) -> int:
        if self.armed and self.mode == "hash":
            raise RuntimeError("hash exploded")
        return self.hash_value

    def __eq__(self, other: object) -> bool:
        if self.armed and self.mode == "eq":
            raise RuntimeError("equality exploded")
        return self is other

    def __repr__(self) -> str:
        if self.armed and self.mode == "repr":
            raise RuntimeError("repr exploded")
        return f"_HostileKey({self.mode})"


class _HostileEqualityValue:
    def __eq__(self, other: object) -> bool:
        del other
        raise RuntimeError("value equality exploded")


def _item_entity(entity_id: str, *, name: str, quantity: float, aliases: list[str]) -> dict[str, Any]:
    return {
        "id": entity_id,
        "type": "item",
        "name": name,
        "status": "active",
        "visibility": "known",
        "location_id": None,
        "owner_id": "pc:runner",
        "summary": f"Structured validation fixture: {name}.",
        "details": {"source": "routine_consumption_validation", "nested": {"safe": True}},
        "aliases": aliases,
        "item": {
            "category": "consumable",
            "quantity": quantity,
            "unit": "kg",
            "quality": "standard",
            "durability_current": 7,
            "durability_max": 10,
            "stackable": True,
            "equipped_slot": None,
            "properties": {"sealed": True, "grade": 2},
        },
    }


@pytest.fixture(scope="module")
def routine_campaign() -> Iterator[Campaign]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "campaign"
        shutil.copytree(OFFICIAL_EXAMPLE, root)
        campaign = load_campaign(root)
        init_database(campaign, force=True)
        with connect(campaign) as conn:
            upsert_entity(conn, _item_entity(TARGET_ID, name="Test Ration", quantity=0.3, aliases=["ration", "口粮"]))
            upsert_entity(conn, _item_entity(OTHER_ID, name="Test Water", quantity=5.0, aliases=["water", "清水"]))
            conn.commit()
        yield campaign


def _base_delta(campaign: Campaign) -> dict[str, Any]:
    with connect(campaign) as conn:
        meta = get_meta(conn)
    entity = _item_entity(TARGET_ID, name="Test Ration", quantity=0.2, aliases=["ration", "口粮"])
    return {
        "expected_turn_id": meta["current_turn_id"],
        "command_id": "test-routine-consumption-validation",
        "user_text": "consume a structured ration",
        "intent": "routine",
        "changed": True,
        "game_time_before": meta["current_time_block"],
        "game_time_after": meta["current_time_block"],
        "location_before": meta["current_location_id"],
        "location_after": meta["current_location_id"],
        "summary": "Consumed a structured ration.",
        "events": [
            {
                "type": "routine",
                "title": "Routine consumption",
                "summary": "Consumed a structured ration.",
                "payload": {
                    "task": "consume ration",
                    "consumed_item_id": TARGET_ID,
                    "before_quantity": 0.3,
                    "consumed_quantity": 0.1,
                    "after_quantity": 0.2,
                    "unit": "kg",
                },
                "source": "test",
            }
        ],
        "upsert_entities": [entity],
        "tick_clocks": [],
    }


def _run_report(campaign: Campaign, delta: dict[str, Any]) -> ValidationReport:
    before_bytes = pickle.dumps(delta)
    persistence_before = _persistence_snapshot(campaign)
    intent = ActionIntent(
        user_text="consume a structured ration",
        mode="action",
        submode="routine",
        action="routine",
        options={"task": "consume ration", "target": TARGET_ID},
        confidence="high",
        source="structured_test_candidate",
    )
    contract = TurnContract(
        intent=intent,
        required_template="routine_turn.md",
        response_headings=("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
        requires_preview=True,
        must_save=True,
        allowed_delta_sources=("human_edited",),
        validation_profile="player_turn_commit",
    )
    proposal = TurnProposal(
        proposal_id="turn-proposal:test:routine-consumption-validation",
        intent=intent,
        preview={"action": "routine", "status": "ready"},
        delta=delta,
        delta_source="human_edited",
        provenance={"source": "routine_consumption_validation"},
        human_confirmed=True,
        turn_contract=contract,
    )
    proposal_before_bytes = pickle.dumps(proposal)
    with connect(campaign) as conn:
        report = run_validation_pipeline(
            campaign,
            conn,
            profile="player_turn_commit",
            delta=delta,
            proposal=proposal,
            action="routine",
            action_options={"task": "consume ration", "target": TARGET_ID},
        )
    assert pickle.dumps(delta) == before_bytes
    assert pickle.dumps(proposal) == proposal_before_bytes
    assert _persistence_snapshot(campaign) == persistence_before
    return report


def _persistence_snapshot(campaign: Campaign) -> tuple[bytes, bytes, str]:
    with connect(campaign) as conn:
        logical_dump = "\n".join(conn.iterdump())
    return campaign.database_path.read_bytes(), campaign.events_path.read_bytes(), logical_dump


def _assert_routine_blocked(report: ValidationReport, reason: str) -> None:
    stage = report.stage("resolver_delta_contract")
    assert stage is not None
    assert stage.status == "blocked", report.to_dict()
    rendered = "\n".join(stage.issues)
    assert "routine consumption:" in rendered
    assert reason in rendered
    rendered.encode("utf-8")


@pytest.mark.parametrize(
    "payload",
    [
        {"task": "ordinary routine"},
        {"materials": [{"consumed_quantity": 0.1, "unit": "kg"}], "material_consumption_required": True},
        {"ammo_id": TARGET_ID, "fired": True},
    ],
    ids=["ordinary-routine", "nested-craft-materials", "combat-ammo-shape"],
)
def test_routine_consumption_contract_ignores_payloads_without_top_level_trigger(
    routine_campaign: Campaign,
    payload: dict[str, Any],
) -> None:
    delta = _base_delta(routine_campaign)
    delta["events"][0]["payload"] = payload
    report = _run_report(routine_campaign, delta)
    assert report.stage("resolver_delta_contract").status == "ok", report.to_dict()


def test_routine_consumption_accepts_one_ulp_arithmetic_and_alias_reordering(
    routine_campaign: Campaign,
) -> None:
    delta = _base_delta(routine_campaign)
    delta["upsert_entities"][0]["aliases"] = ["口粮", "ration"]
    assert abs((0.3 - 0.1) - 0.2) == max(math.ulp(0.3 - 0.1), math.ulp(0.2))
    report = _run_report(routine_campaign, delta)
    assert report.stage("resolver_delta_contract").status == "ok", report.to_dict()


def _invalid_delta(campaign: Campaign, case: str) -> dict[str, Any]:
    delta = _base_delta(campaign)
    event = delta["events"][0]
    payload = event["payload"]
    target = delta["upsert_entities"][0]
    item = target["item"]

    if case == "single-consumed-item-id":
        event["payload"] = {"consumed_item_id": TARGET_ID}
    elif case == "single-before-quantity":
        event["payload"] = {"before_quantity": 0.3}
    elif case == "single-consumed-quantity":
        event["payload"] = {"consumed_quantity": 0.1}
    elif case == "single-after-quantity":
        event["payload"] = {"after_quantity": 0.2}
    elif case in {"two-same", "two-different"}:
        second = deepcopy(event)
        if case == "two-different":
            second["payload"]["consumed_item_id"] = OTHER_ID
        delta["events"].append(second)
    elif case == "extra-event":
        delta["events"].append(
            {"type": "note", "title": "Extra", "summary": "Extra audit note.", "payload": {}, "source": "test"}
        )
    elif case == "missing-upsert":
        delta["upsert_entities"] = []
    elif case == "duplicate-upsert":
        delta["upsert_entities"].append(deepcopy(target))
    elif case == "item-mismatch":
        payload["consumed_item_id"] = OTHER_ID
    elif case == "missing-target":
        payload["consumed_item_id"] = "item:test-missing"
        target["id"] = "item:test-missing"
    elif case == "payload-unit":
        payload["unit"] = "L"
    elif case == "upsert-unit":
        item["unit"] = "L"
    elif case == "arithmetic":
        payload["after_quantity"] = 0.19
        item["quantity"] = 0.19
    elif case == "upsert-quantity":
        item["quantity"] = 0.19
    elif case == "zero-consumed":
        payload["consumed_quantity"] = 0.0
    elif case == "negative-consumed":
        payload["consumed_quantity"] = -0.1
    elif case == "negative-after":
        payload["consumed_quantity"] = 0.4
        payload["after_quantity"] = -0.1
        item["quantity"] = -0.1
    elif case == "after-equals-before":
        payload["after_quantity"] = 0.3
        item["quantity"] = 0.3
    elif case == "bool-number":
        payload["consumed_quantity"] = True
    elif case == "string-number":
        payload["consumed_quantity"] = "0.1"
    elif case == "nan-number":
        payload["consumed_quantity"] = float("nan")
    elif case == "infinite-number":
        payload["consumed_quantity"] = float("inf")
    elif case == "negative-infinite-number":
        payload["consumed_quantity"] = float("-inf")
    elif case == "sqlite-int-high":
        payload["consumed_quantity"] = 2**63
    elif case == "sqlite-int-low":
        payload["consumed_quantity"] = -(2**63) - 1
    elif case == "float-overflow-int":
        payload["consumed_quantity"] = 10**400
    elif case == "float-int-precision-loss":
        payload["consumed_quantity"] = 2**53 + 1
    elif case == "missing-item":
        target.pop("item")
    elif case == "nonmapping-item":
        target["item"] = []
    elif case == "missing-item-quantity":
        item.pop("quantity")
    elif case == "missing-item-unit":
        item.pop("unit")
    elif case == "metadata":
        item["quality"] = "legendary"
    elif case == "details-bool-int":
        target["details"]["nested"]["safe"] = 1
    elif case == "properties-bool-int":
        item["properties"]["sealed"] = 1
    elif case == "extra-item-field":
        item["future_metadata"] = {"must_persist": True}
    elif case == "heterogeneous-target-fields":
        target["future_metadata"] = True
        target[7] = False
    elif case == "heterogeneous-item-fields":
        item["future_metadata"] = True
        item[7] = False
    elif case == "hostile-payload-key":
        payload.pop("consumed_item_id")
        key = _HostileKey("eq", hash_value=hash("consumed_item_id"))
        payload[key] = TARGET_ID
        key.armed = True
    elif case == "hostile-target-key":
        key = _HostileKey("repr")
        target[key] = True
        key.armed = True
    elif case == "hostile-details-key":
        key = _HostileKey("hash")
        target["details"][key] = True
        key.armed = True
    elif case == "hostile-target-id-value":
        target["id"] = _HostileEqualityValue()
    elif case == "hostile-item-unit-value":
        item["unit"] = _HostileEqualityValue()
    elif case == "surrogate-consumed-item-id":
        payload["consumed_item_id"] = "item:\ud800"
        target["id"] = "item:\ud800"
    elif case == "surrogate-other-upsert-id":
        other = _item_entity("item:test-other", name="Other", quantity=1.0, aliases=[])
        other["id"] = "item:\ud800"
        delta["upsert_entities"].append(other)
    elif case == "surrogate-target-key":
        target["\ud800"] = True
    elif case == "surrogate-item-key":
        item["\ud800"] = True
    elif case == "updated-turn":
        target["updated_turn_id"] = "turn:forged"
    elif case == "extra-character-subrecord":
        target["character"] = {"role": "forged"}
    elif case == "aliases-missing":
        target.pop("aliases")
    elif case == "aliases-duplicate":
        target["aliases"].append("ration")
    elif case == "aliases-new":
        target["aliases"].append("new alias")
    elif case == "other-existing-item":
        other = _item_entity(OTHER_ID, name="Test Water", quantity=5.0, aliases=["water", "清水"])
        other.pop("item")
        delta["upsert_entities"].append(other)
    elif case == "other-new-item":
        delta["upsert_entities"].append(
            _item_entity("item:test-new", name="New Item", quantity=1.0, aliases=["new"])
        )
    else:
        raise AssertionError(f"unknown invalid case: {case}")
    return delta


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("single-consumed-item-id", "missing field"),
        ("single-before-quantity", "missing field"),
        ("single-consumed-quantity", "missing field"),
        ("single-after-quantity", "missing field"),
        ("two-same", "multiple declarations"),
        ("two-different", "multiple declarations"),
        ("extra-event", "event cardinality mismatch"),
        ("missing-upsert", "missing/duplicate target upsert"),
        ("duplicate-upsert", "missing/duplicate target upsert"),
        ("item-mismatch", "missing/duplicate target upsert"),
        ("missing-target", "target item not found"),
        ("payload-unit", "unit mismatch"),
        ("upsert-unit", "unit mismatch"),
        ("arithmetic", "arithmetic mismatch"),
        ("upsert-quantity", "upsert quantity mismatch"),
        ("zero-consumed", "non-positive consumed_quantity"),
        ("negative-consumed", "non-positive consumed_quantity"),
        ("negative-after", "insufficient quantity"),
        ("after-equals-before", "arithmetic mismatch"),
        ("bool-number", "invalid numeric type"),
        ("string-number", "invalid numeric type"),
        ("nan-number", "non-finite quantity"),
        ("infinite-number", "non-finite quantity"),
        ("negative-infinite-number", "non-finite quantity"),
        ("sqlite-int-high", "quantity out of range"),
        ("sqlite-int-low", "quantity out of range"),
        ("float-overflow-int", "quantity out of range"),
        ("float-int-precision-loss", "quantity out of range"),
        ("missing-item", "target item payload"),
        ("nonmapping-item", "target item payload"),
        ("missing-item-quantity", "missing field"),
        ("missing-item-unit", "missing field"),
        ("metadata", "metadata mismatch"),
        ("details-bool-int", "metadata mismatch"),
        ("properties-bool-int", "metadata mismatch"),
        ("extra-item-field", "unexpected item field"),
        ("heterogeneous-target-fields", "invalid upsert field type"),
        ("heterogeneous-item-fields", "unexpected item field"),
        ("hostile-payload-key", "invalid payload field type"),
        ("hostile-target-key", "invalid upsert field type"),
        ("hostile-details-key", "metadata mismatch"),
        ("hostile-target-id-value", "missing/duplicate target upsert"),
        ("hostile-item-unit-value", "unit mismatch"),
        ("surrogate-consumed-item-id", "invalid consumed_item_id"),
        ("surrogate-other-upsert-id", "invalid upsert id"),
        ("surrogate-target-key", "unexpected target field <invalid-text>"),
        ("surrogate-item-key", "unexpected item field <invalid-text>"),
        ("updated-turn", "metadata mismatch"),
        ("extra-character-subrecord", "metadata mismatch"),
        ("aliases-missing", "metadata mismatch"),
        ("aliases-duplicate", "metadata mismatch"),
        ("aliases-new", "metadata mismatch"),
        ("other-existing-item", "unexpected inventory upsert"),
        ("other-new-item", "unexpected inventory upsert"),
    ],
)
def test_routine_consumption_invalid_matrix_blocks_in_resolver_stage_without_mutating_input(
    routine_campaign: Campaign,
    case: str,
    reason: str,
) -> None:
    report = _run_report(routine_campaign, _invalid_delta(routine_campaign, case))
    _assert_routine_blocked(report, reason)


@pytest.mark.parametrize(
    ("before_quantity", "consumed_quantity"),
    [
        (1e308, 1.0),
        (1.0, math.ulp(0.0)),
    ],
    ids=["large-before", "minimum-subnormal-consumed"],
)
def test_routine_consumption_rejects_subtraction_that_rounds_back_to_before(
    routine_campaign: Campaign,
    before_quantity: float,
    consumed_quantity: float,
) -> None:
    after_quantity = math.nextafter(before_quantity, -math.inf)
    assert before_quantity - consumed_quantity == before_quantity

    with connect(routine_campaign) as conn:
        conn.execute("update items set quantity = ? where entity_id = ?", (before_quantity, TARGET_ID))
        conn.commit()
    try:
        delta = _base_delta(routine_campaign)
        payload = delta["events"][0]["payload"]
        payload["before_quantity"] = before_quantity
        payload["consumed_quantity"] = consumed_quantity
        payload["after_quantity"] = after_quantity
        delta["upsert_entities"][0]["item"]["quantity"] = after_quantity

        report = _run_report(routine_campaign, delta)
        _assert_routine_blocked(report, "arithmetic mismatch")
    finally:
        with connect(routine_campaign) as conn:
            conn.execute("update items set quantity = 0.3 where entity_id = ?", (TARGET_ID,))
            conn.commit()


def test_routine_consumption_rejects_realized_decrement_larger_than_declared(
    routine_campaign: Campaign,
) -> None:
    before_quantity = 9007199254740994.0
    consumed_quantity = 1.0
    after_quantity = 9007199254740992.0
    assert before_quantity - consumed_quantity == after_quantity
    assert before_quantity - after_quantity == 2.0

    with connect(routine_campaign) as conn:
        conn.execute("update items set quantity = ? where entity_id = ?", (before_quantity, TARGET_ID))
        conn.commit()
    try:
        delta = _base_delta(routine_campaign)
        payload = delta["events"][0]["payload"]
        payload["before_quantity"] = before_quantity
        payload["consumed_quantity"] = consumed_quantity
        payload["after_quantity"] = after_quantity
        delta["upsert_entities"][0]["item"]["quantity"] = after_quantity

        report = _run_report(routine_campaign, delta)
        _assert_routine_blocked(report, "arithmetic mismatch")
    finally:
        with connect(routine_campaign) as conn:
            conn.execute("update items set quantity = 0.3 where entity_id = ?", (TARGET_ID,))
            conn.commit()


def test_routine_consumption_accepts_exact_binade_boundary_decrement(
    routine_campaign: Campaign,
) -> None:
    before_quantity = float(2**53)
    consumed_quantity = 1.0
    after_quantity = float(2**53 - 1)
    assert before_quantity - consumed_quantity == after_quantity
    assert before_quantity - after_quantity == consumed_quantity

    with connect(routine_campaign) as conn:
        conn.execute("update items set quantity = ? where entity_id = ?", (before_quantity, TARGET_ID))
        conn.commit()
    try:
        delta = _base_delta(routine_campaign)
        payload = delta["events"][0]["payload"]
        payload["before_quantity"] = before_quantity
        payload["consumed_quantity"] = consumed_quantity
        payload["after_quantity"] = after_quantity
        delta["upsert_entities"][0]["item"]["quantity"] = after_quantity

        report = _run_report(routine_campaign, delta)
        assert report.stage("resolver_delta_contract").status == "ok", report.to_dict()
    finally:
        with connect(routine_campaign) as conn:
            conn.execute("update items set quantity = 0.3 where entity_id = ?", (TARGET_ID,))
            conn.commit()


@pytest.mark.parametrize("after_quantity", [0.0, math.ulp(0.0)])
def test_routine_consumption_subnormal_realized_decrement_is_relative_exact(
    routine_campaign: Campaign,
    after_quantity: float,
) -> None:
    consumed_quantity = math.ulp(0.0)
    before_quantity = 2 * consumed_quantity

    with connect(routine_campaign) as conn:
        conn.execute("update items set quantity = ? where entity_id = ?", (before_quantity, TARGET_ID))
        conn.commit()
    try:
        delta = _base_delta(routine_campaign)
        payload = delta["events"][0]["payload"]
        payload["before_quantity"] = before_quantity
        payload["consumed_quantity"] = consumed_quantity
        payload["after_quantity"] = after_quantity
        delta["upsert_entities"][0]["item"]["quantity"] = after_quantity

        report = _run_report(routine_campaign, delta)
        stage = report.stage("resolver_delta_contract")
        if after_quantity == 0.0:
            _assert_routine_blocked(report, "arithmetic mismatch")
        else:
            assert stage is not None
            assert stage.status == "ok", report.to_dict()
    finally:
        with connect(routine_campaign) as conn:
            conn.execute("update items set quantity = 0.3 where entity_id = ?", (TARGET_ID,))
            conn.commit()
