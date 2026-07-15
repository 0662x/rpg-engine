from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest

from rpg_engine.proposal import TurnProposal
from rpg_engine.runtime import GMRuntime
from tests.automation_support.domain_deltas import structured_delta_builder
from tests.automation_support.domain_environment import current_native_temp_save, db_snapshot


pytestmark = pytest.mark.p0

SnapshotFactory = Callable[[Path], dict[str, Any]]
StructuredDeltaBuilder = Callable[..., dict[str, Any]]


def _commit(runtime: GMRuntime, case: dict[str, Any]) -> Any:
    proposal = case["proposal"]
    assert isinstance(proposal, TurnProposal)
    assert proposal.delta == case["delta"]
    return runtime.commit_turn(
        case["delta"],
        turn_proposal=proposal,
        backup=False,
        action=proposal.intent.action,
        action_options=dict(proposal.intent.options),
        state_audit=True,
        state_audit_ai="off",
    )


def _without(inventory: dict[str, Any], *entity_ids: str) -> dict[str, Any]:
    excluded = set(entity_ids)
    return {entity_id: deepcopy(value) for entity_id, value in inventory.items() if entity_id not in excluded}


def test_consumption_commit_decrements_exact_quantity_and_writes_one_turn_event(
    current_native_temp_save: Path,
    structured_delta_builder: StructuredDeltaBuilder,
    db_snapshot: SnapshotFactory,
) -> None:
    """[P0][CON-01] 结构化消耗精确扣量，只新增一个 turn/event，且无关库存不变。"""
    # Given：临时 current-native Save 与 human-confirmed 结构化消费 delta。
    runtime = GMRuntime.from_path(current_native_temp_save)
    case = structured_delta_builder(runtime, scenario="consumption_success")
    before = db_snapshot(current_native_temp_save)
    target_id = case["target_id"]

    # When：通过真实 player_turn_commit validation/transaction 提交。
    result = _commit(runtime, case)

    # Then：只发生声明过的数量变化，并且 turn/event 各新增一条。
    after = db_snapshot(current_native_temp_save)
    assert result.ok
    assert after["inventory"][target_id]["quantity"] == case["after_quantity"]
    assert case["after_quantity"] == case["before_quantity"] - case["consumed_quantity"]
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
    assert _without(after["inventory"], target_id) == _without(before["inventory"], target_id)


def test_consumption_changes_only_quantity_and_preserves_all_item_metadata(
    current_native_temp_save: Path,
    structured_delta_builder: StructuredDeltaBuilder,
    db_snapshot: SnapshotFactory,
) -> None:
    """[P0][CON-02] 消耗不得丢失或改写 unit/quality/properties/durability 等 metadata。"""
    # Given：保存目标物品的完整 entity/item metadata 快照。
    runtime = GMRuntime.from_path(current_native_temp_save)
    case = structured_delta_builder(runtime, scenario="consumption_metadata")
    before = db_snapshot(current_native_temp_save)
    target_id = case["target_id"]
    expected_item = deepcopy(before["inventory"][target_id])
    expected_item["quantity"] = case["after_quantity"]

    # When：只提交 quantity decrement。
    _commit(runtime, case)

    # Then：深比较证明 quantity 是唯一业务字段变化。
    after = db_snapshot(current_native_temp_save)
    assert after["inventory"][target_id] == expected_item


@pytest.mark.parametrize(
    "invalid_case",
    [
        "insufficient",
        "stale_before",
        "item_mismatch",
        "malformed_quantity",
        "sub_ulp_noop",
        "extra_item_field",
    ],
    ids=[
        "insufficient",
        "stale-before",
        "item-mismatch",
        "malformed-quantity",
        "sub-ulp-noop",
        "extra-item-field",
    ],
)
def test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation(
    invalid_case: str,
    current_native_temp_save: Path,
    structured_delta_builder: StructuredDeltaBuilder,
    db_snapshot: SnapshotFactory,
) -> None:
    """[P0][CON-03] 非法消耗必须在 commit 前拒绝，DB 与 events.jsonl 均零变化。"""
    # Given：distinct historical failure signature 与提交前完整指纹。
    runtime = GMRuntime.from_path(current_native_temp_save)
    case = structured_delta_builder(
        runtime,
        scenario="consumption_invalid",
        invalid_case=invalid_case,
    )
    before = db_snapshot(current_native_temp_save)

    # When：攻击真实 commit boundary；不得用 validation-only 假替身。
    with pytest.raises(ValueError) as exc_info:
        _commit(runtime, case)
    message = str(exc_info.value)
    assert "routine consumption:" in message
    assert case["expected_error"] in message

    # Then：拒绝后 SQLite、JSONL、库存与计数必须逐项不变。
    after = db_snapshot(current_native_temp_save)
    assert after["database_sha256"] == before["database_sha256"]
    assert after["events_jsonl"] == before["events_jsonl"]
    assert after["inventory"] == before["inventory"]
    assert after["turn_count"] == before["turn_count"]
    assert after["event_count"] == before["event_count"]


def test_gm_resolved_craft_delta_consumes_material_and_upserts_output_exactly(
    current_native_temp_save: Path,
    structured_delta_builder: StructuredDeltaBuilder,
    db_snapshot: SnapshotFactory,
) -> None:
    """[P0][CRF-01] GM 确认的真实 TurnProposal 精确扣材料、upsert 产出并形成 exact inventory diff。"""
    # Given：临时 Save、匹配 recipe 与 human-confirmed GM-resolved delta。
    runtime = GMRuntime.from_path(current_native_temp_save)
    case = structured_delta_builder(runtime, scenario="craft_gm_resolved")
    proposal = case["proposal"]
    assert isinstance(proposal, TurnProposal)
    assert proposal.delta_source == "human_edited"
    assert proposal.human_confirmed is True
    before = db_snapshot(current_native_temp_save)
    material_id = case["material_id"]
    output_id = case["output_id"]
    assert output_id not in before["inventory"]

    # When：通过真实 craft resolver contract 与 transaction 提交。
    result = _commit(runtime, case)

    # Then：inventory diff 只能包含声明的材料 decrement 与成品 upsert。
    after = db_snapshot(current_native_temp_save)
    expected_inventory = deepcopy(before["inventory"])
    expected_inventory[material_id]["quantity"] = case["material_after_quantity"]
    expected_inventory[output_id] = deepcopy(case["expected_output"])
    assert result.ok
    assert after["inventory"] == expected_inventory
    assert after["turn_count"] == before["turn_count"] + 1
    assert after["event_count"] == before["event_count"] + 1
