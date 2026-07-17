from __future__ import annotations

import math
import pickle
import shutil
import tempfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from rpg_engine.campaign import Campaign, load_campaign
from rpg_engine.actions.gather import validate_gather_delta, validate_palette_gather_delta
from rpg_engine.db import connect, get_meta, init_database, upsert_entity
from rpg_engine.intent_router import ActionIntent, TurnContract
from rpg_engine.proposal import TurnProposal
from rpg_engine.validation_pipeline import ValidationReport, run_validation_pipeline


ENGINE_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_EXAMPLE = ENGINE_ROOT / "rpg_engine" / "resources" / "examples" / "v1_minimal_adventure"
SOURCE_ID = "mat:moon-herb"
OUTPUT_ID = "item:test-intake-herb"
OTHER_OUTPUT_ID = "item:test-intake-other"
EXISTING_OUTPUT_ID = "item:test-intake-existing"
LOCATION_ID = "loc:watch-camp"
OTHER_LOCATION_ID = "loc:test-intake-other"
RETIRED_LOCATION_ID = "loc:test-intake-retired"
OWNER_ID = "pc:runner"
RETIRED_OWNER_ID = "pc:test-intake-retired"
HIDDEN_LOCATION_ID = "loc:test-intake-hidden"
HIDDEN_OWNER_ID = "pc:test-intake-hidden"
HIDDEN_CLOCK_OWNER_ID = "clock:storm-front"
HIDDEN_WORLD_SETTING_OWNER_ID = "world:river-road"


def _hide_subtype_owner_anchors(conn: Any) -> None:
    clock = conn.execute(
        "update clocks set visibility = 'gm-only' where entity_id = ?",
        (HIDDEN_CLOCK_OWNER_ID,),
    )
    world_setting = conn.execute(
        "update world_settings set visibility = 'gm-only' where entity_id = ?",
        (HIDDEN_WORLD_SETTING_OWNER_ID,),
    )
    assert clock.rowcount == 1
    assert world_setting.rowcount == 1


def _output_entity(
    entity_id: str = OUTPUT_ID,
    *,
    quantity: Any = 2.0,
    unit: Any = "bundle",
    location_id: Any = LOCATION_ID,
    owner_id: Any = None,
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "type": "item",
        "name": "Test Intake Herb",
        "status": "active",
        "visibility": "known",
        "location_id": location_id,
        "owner_id": owner_id,
        "summary": "A temporary structured Intake validation fixture.",
        "details": {"source": "story-1.10", "nested": {"preserve": True}},
        "aliases": ["intake herb", "测试入库草药"],
        "item": {
            "category": "material",
            "quantity": quantity,
            "unit": unit,
            "quality": "standard",
            "durability_current": None,
            "durability_max": None,
            "stackable": True,
            "equipped_slot": None,
            "properties": {"fresh": True, "grade": 2},
        },
    }


@pytest.fixture(scope="module")
def intake_campaign() -> Iterator[Campaign]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "campaign"
        shutil.copytree(OFFICIAL_EXAMPLE, root)
        campaign = load_campaign(root)
        init_database(campaign, force=True)
        with connect(campaign) as conn:
            upsert_entity(
                conn,
                {
                    "id": OTHER_LOCATION_ID,
                    "type": "location",
                    "name": "Other Intake Location",
                    "status": "active",
                    "visibility": "known",
                    "summary": "A second temporary location.",
                },
            )
            upsert_entity(
                conn,
                {
                    "id": RETIRED_LOCATION_ID,
                    "type": "location",
                    "name": "Retired Intake Location",
                    "status": "retired",
                    "visibility": "known",
                    "summary": "A retired temporary location.",
                },
            )
            upsert_entity(
                conn,
                {
                    "id": RETIRED_OWNER_ID,
                    "type": "character",
                    "name": "Retired Intake Owner",
                    "status": "retired",
                    "visibility": "known",
                    "summary": "A retired temporary owner.",
                },
            )
            upsert_entity(
                conn,
                {
                    "id": HIDDEN_LOCATION_ID,
                    "type": "location",
                    "name": "Hidden Intake Location",
                    "status": "active",
                    "visibility": "gm-only",
                    "summary": "A hidden temporary location.",
                },
            )
            upsert_entity(
                conn,
                {
                    "id": HIDDEN_OWNER_ID,
                    "type": "character",
                    "name": "Hidden Intake Owner",
                    "status": "active",
                    "visibility": "hidden",
                    "summary": "A hidden temporary owner.",
                },
            )
            upsert_entity(
                conn,
                _output_entity(
                    EXISTING_OUTPUT_ID,
                    quantity=1.5,
                    location_id=None,
                    owner_id=OWNER_ID,
                ),
            )
            _hide_subtype_owner_anchors(conn)
            conn.commit()
        pending_root = root / ".aigm"
        pending_root.mkdir()
        (pending_root / "pending-player-action.json").write_text(
            '{"sentinel":"pending-action"}\n',
            encoding="utf-8",
        )
        (pending_root / "pending-player-clarification.json").write_text(
            '{"sentinel":"pending-clarification"}\n',
            encoding="utf-8",
        )
        yield campaign


def _base_delta(campaign: Campaign) -> dict[str, Any]:
    with connect(campaign) as conn:
        meta = get_meta(conn)
    entity = _output_entity()
    return {
        "expected_turn_id": meta["current_turn_id"],
        "command_id": "test-gather-intake-validation",
        "user_text": "Confirm two bundles of gathered herb",
        "intent": "gather",
        "changed": True,
        "game_time_before": meta["current_time_block"],
        "game_time_after": meta["current_time_block"],
        "location_before": LOCATION_ID,
        "location_after": LOCATION_ID,
        "summary": "Confirmed two bundles of gathered herb.",
        "events": [
            {
                "type": "gather",
                "title": "Gather Intake",
                "summary": "Confirmed two bundles of gathered herb.",
                "payload": {
                    "target_id": SOURCE_ID,
                    "location_id": LOCATION_ID,
                    "output_entity_id": OUTPUT_ID,
                    "output_quantity": 2.0,
                    "output_unit": "bundle",
                    "output_quantity_required": True,
                    "resource_state_update_required": False,
                    "state_changes_must_be_structured": True,
                },
                "source": "test",
            }
        ],
        "upsert_entities": [entity],
        "tick_clocks": [],
    }


def _proposal(delta: dict[str, Any]) -> TurnProposal:
    options = {
        "target": SOURCE_ID,
        "location": LOCATION_ID,
        "output_confirmed": True,
        "user_text": delta["user_text"],
    }
    intent = ActionIntent(
        user_text=delta["user_text"],
        mode="action",
        submode="gather",
        action="gather",
        options=options,
        confidence="high",
        source="structured_test_candidate",
    )
    contract = TurnContract(
        intent=intent,
        required_template="gather_turn.md",
        response_headings=("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
        requires_preview=True,
        must_save=True,
        allowed_delta_sources=("human_edited",),
        validation_profile="player_turn_commit",
    )
    return TurnProposal(
        proposal_id="turn-proposal:test:gather-intake-validation",
        intent=intent,
        preview={"action": "gather", "status": "ready"},
        delta=delta,
        delta_source="human_edited",
        provenance={"source": "story-1.10-test"},
        human_confirmed=True,
        turn_contract=contract,
    )


def _existing_update_delta(campaign: Campaign) -> dict[str, Any]:
    delta = _base_delta(campaign)
    payload = delta["events"][0]["payload"]
    payload["location_id"] = None
    payload["owner_id"] = OWNER_ID
    payload["output_entity_id"] = EXISTING_OUTPUT_ID
    payload["output_quantity"] = 3.0
    delta["upsert_entities"] = [
        _output_entity(
            EXISTING_OUTPUT_ID,
            quantity=3.0,
            location_id=None,
            owner_id=OWNER_ID,
        )
    ]
    return delta


def _persistence_snapshot(campaign: Campaign) -> tuple[bytes, bytes, str, dict[str, bytes]]:
    with connect(campaign) as conn:
        logical_dump = "\n".join(conn.iterdump())
    pending_root = campaign.root / ".aigm"
    pending = {
        path.relative_to(pending_root).as_posix(): path.read_bytes()
        for path in sorted(pending_root.rglob("*"))
        if path.is_file()
    }
    return campaign.database_path.read_bytes(), campaign.events_path.read_bytes(), logical_dump, pending


def _run_report(campaign: Campaign, delta: dict[str, Any]) -> ValidationReport:
    proposal = _proposal(delta)
    delta_before = pickle.dumps(delta)
    proposal_before = pickle.dumps(proposal)
    persistence_before = _persistence_snapshot(campaign)
    with connect(campaign) as conn:
        report = run_validation_pipeline(
            campaign,
            conn,
            profile="player_turn_commit",
            delta=delta,
            proposal=proposal,
            action="gather",
            action_options=dict(proposal.intent.options),
            state_audit=False,
        )
    assert pickle.dumps(delta) == delta_before
    assert pickle.dumps(proposal) == proposal_before
    assert _persistence_snapshot(campaign) == persistence_before
    return report


def _assert_intake_blocked(report: ValidationReport, reason: str) -> None:
    stage = report.stage("resolver_delta_contract")
    assert stage is not None
    assert stage.status == "blocked", report.to_dict()
    rendered = "\n".join(stage.issues)
    assert "gather intake:" in rendered
    assert reason in rendered
    rendered.encode("utf-8")


def test_valid_gather_intake_semantics_pass_without_mutating_inputs_or_state(
    intake_campaign: Campaign,
) -> None:
    report = _run_report(intake_campaign, _base_delta(intake_campaign))
    stage = report.stage("resolver_delta_contract")
    assert stage is not None
    assert stage.status == "ok", report.to_dict()


def test_intake_gate_runs_on_gather_target_early_return(intake_campaign: Campaign) -> None:
    delta = _invalid_delta(intake_campaign, "zero")
    with connect(intake_campaign) as conn:
        result = validate_gather_delta(
            intake_campaign,
            conn,
            {},
            SimpleNamespace(),
            delta,
        )
    assert "target" in result.missing_required
    assert any("gather intake: intake output quantity must be positive" in error for error in result.errors)


def test_direct_palette_validator_cannot_bypass_intake_gate(intake_campaign: Campaign) -> None:
    delta = _invalid_delta(intake_campaign, "zero")
    with connect(intake_campaign) as conn:
        result = validate_palette_gather_delta(
            intake_campaign,
            conn,
            SimpleNamespace(),
            delta,
            "pal:test-intake",
        )
    assert any("gather intake: intake output quantity must be positive" in error for error in result.errors)


@pytest.mark.parametrize(
    "payload",
    [
        {"target_id": SOURCE_ID, "location_id": LOCATION_ID, "output_quantity_required": True},
        {
            "target_id": SOURCE_ID,
            "location_id": LOCATION_ID,
            "materials": [{"output_entity_id": OUTPUT_ID, "output_quantity": 2.0, "output_unit": "bundle"}],
        },
    ],
    ids=["draft-marker-only", "nested-output-shape"],
)
def test_gather_intake_contract_ignores_non_direct_output_shapes(
    intake_campaign: Campaign,
    payload: dict[str, Any],
) -> None:
    delta = _base_delta(intake_campaign)
    delta["events"][0]["payload"] = payload
    delta["upsert_entities"] = []
    report = _run_report(intake_campaign, delta)
    stage = report.stage("resolver_delta_contract")
    assert stage is not None
    assert stage.status in {"ok", "warning"}, report.to_dict()
    assert not any("gather intake:" in issue for issue in stage.issues)


def _invalid_delta(campaign: Campaign, case: str) -> dict[str, Any]:
    delta = _base_delta(campaign)
    event = delta["events"][0]
    payload = event["payload"]
    target = delta["upsert_entities"][0]
    item = target["item"]

    if case == "single-output-id":
        payload.pop("output_quantity")
        payload.pop("output_unit")
    elif case == "single-output-quantity":
        payload.pop("output_entity_id")
        payload.pop("output_unit")
    elif case == "single-output-unit":
        payload.pop("output_entity_id")
        payload.pop("output_quantity")
    elif case == "duplicate-declaration":
        delta["events"].append(deepcopy(event))
    elif case == "extra-event":
        delta["events"].append(
            {"type": "note", "title": "Extra", "summary": "Extra event.", "payload": {}, "source": "test"}
        )
    elif case == "missing-event-title":
        event.pop("title")
    elif case == "non-string-event-key":
        event[1] = "invalid key"
    elif case == "non-string-payload-key":
        payload[1] = "invalid key"
    elif case == "non-gather-event":
        event["type"] = "combat"
    elif case == "unsafe-event-summary":
        event["summary"] = "forged\nplayer surface"
    elif case == "extra-event-field":
        event["unexpected_intake_field"] = "must not be discarded"
    elif case == "tick-clock":
        delta["tick_clocks"] = [
            {"id": "clock:storm-front", "delta": 1, "reason": "Forbidden Intake side effect"}
        ]
    elif case == "changed-false":
        delta["changed"] = False
    elif case == "wrong-intent":
        delta["intent"] = "routine"
    elif case == "meta-update":
        delta["meta"] = {"current_location_id": HIDDEN_LOCATION_ID}
    elif case == "missing-upsert":
        delta["upsert_entities"] = []
    elif case == "non-list-upsert":
        delta["upsert_entities"] = {"not": "a list"}
    elif case == "duplicate-upsert":
        delta["upsert_entities"].append(deepcopy(target))
    elif case == "non-string-upsert-key":
        target[1] = "invalid key"
    elif case == "non-string-item-key":
        item[1] = "invalid key"
    elif case == "extra-upsert":
        delta["upsert_entities"].append(_output_entity(OTHER_OUTPUT_ID))
    elif case == "output-id-mismatch":
        payload["output_entity_id"] = OTHER_OUTPUT_ID
    elif case == "quantity-mismatch":
        item["quantity"] = 3.0
    elif case == "unit-mismatch":
        item["unit"] = "kg"
    elif case == "empty-unit":
        payload["output_unit"] = ""
        item["unit"] = ""
    elif case == "blank-unit":
        payload["output_unit"] = "   "
        item["unit"] = "   "
    elif case == "unsafe-unit":
        payload["output_unit"] = "bundle\nforged"
        item["unit"] = "bundle\nforged"
    elif case == "edge-space-unit":
        payload["output_unit"] = " bundle "
        item["unit"] = " bundle "
    elif case == "unsafe-alias":
        target["aliases"].append("forged\nplayer surface")
    elif case == "blank-output-id":
        payload["output_entity_id"] = "   "
        target["id"] = "   "
    elif case == "missing-item":
        target.pop("item")
    elif case == "non-item-target":
        target["type"] = "material"
    elif case == "missing-item-quantity":
        item.pop("quantity")
    elif case == "missing-item-unit":
        item.pop("unit")
    elif case == "missing-anchors":
        payload["location_id"] = None
        target["location_id"] = None
    elif case == "ownership-mismatch":
        payload["location_id"] = OTHER_LOCATION_ID
    elif case == "unknown-location":
        payload["location_id"] = "loc:test-intake-unknown"
        target["location_id"] = "loc:test-intake-unknown"
    elif case == "retired-location":
        payload["location_id"] = RETIRED_LOCATION_ID
        target["location_id"] = RETIRED_LOCATION_ID
    elif case == "hidden-location":
        payload["location_id"] = HIDDEN_LOCATION_ID
        target["location_id"] = HIDDEN_LOCATION_ID
    elif case == "blank-location":
        payload["location_id"] = "   "
        target["location_id"] = "   "
    elif case == "wrong-location-type":
        payload["location_id"] = OWNER_ID
        target["location_id"] = OWNER_ID
    elif case in {
        "unknown-owner",
        "retired-owner",
        "hidden-owner",
        "hidden-clock-owner",
        "hidden-world-setting-owner",
    }:
        owner_id = {
            "unknown-owner": "pc:test-intake-unknown",
            "retired-owner": RETIRED_OWNER_ID,
            "hidden-owner": HIDDEN_OWNER_ID,
            "hidden-clock-owner": HIDDEN_CLOCK_OWNER_ID,
            "hidden-world-setting-owner": HIDDEN_WORLD_SETTING_OWNER_ID,
        }[case]
        payload["location_id"] = None
        payload["owner_id"] = owner_id
        target["location_id"] = None
        target["owner_id"] = owner_id
    elif case == "both-anchors":
        payload["owner_id"] = OWNER_ID
        target["owner_id"] = OWNER_ID
    elif case == "zero":
        payload["output_quantity"] = item["quantity"] = 0
    elif case == "negative":
        payload["output_quantity"] = item["quantity"] = -1.0
    elif case == "bool":
        payload["output_quantity"] = item["quantity"] = True
    elif case == "string":
        payload["output_quantity"] = item["quantity"] = "2"
    elif case == "nan":
        payload["output_quantity"] = item["quantity"] = float("nan")
    elif case == "infinity":
        payload["output_quantity"] = item["quantity"] = float("inf")
    elif case == "negative-infinity":
        payload["output_quantity"] = item["quantity"] = float("-inf")
    elif case == "sqlite-int-high":
        payload["output_quantity"] = item["quantity"] = 2**63
    elif case == "sqlite-int-low":
        payload["output_quantity"] = item["quantity"] = -(2**63) - 1
    elif case == "float-overflow-int":
        payload["output_quantity"] = item["quantity"] = 10**400
    elif case == "float-int-precision-loss":
        payload["output_quantity"] = item["quantity"] = 2**53 + 1
    elif case == "invalid-new-properties":
        item["properties"] = ["not", "a", "mapping"]
    elif case == "huge-metadata-int":
        item["properties"]["huge"] = 10**5000
    elif case == "cyclic-payload":
        cycle: dict[str, Any] = {}
        cycle["self"] = cycle
        payload["extra"] = cycle
    elif case == "invalid-new-stackable":
        item["stackable"] = 1
    elif case == "invalid-new-durability":
        item["durability_current"] = True
    elif case == "negative-new-durability":
        item["durability_current"] = -1
    elif case == "oversized-new-durability":
        item["durability_max"] = 2**63
    elif case == "inverted-new-durability":
        item["durability_current"] = 2
        item["durability_max"] = 1
    elif case == "hidden-output-target":
        target["visibility"] = "gm-only"
    elif case == "unknown-output-visibility":
        target["visibility"] = "not-a-visibility"
    else:
        raise AssertionError(f"unknown invalid case: {case}")
    return delta


INVALID_INTAKE_CASES = (
    ("single-output-id", "missing field: payload.output_quantity"),
    ("single-output-quantity", "missing field: payload.output_entity_id"),
    ("single-output-unit", "missing field: payload.output_entity_id"),
    ("duplicate-declaration", "multiple declarations"),
    ("extra-event", "event cardinality mismatch"),
    ("missing-event-title", "missing field: event.title"),
    ("non-string-event-key", "invalid event field type"),
    ("non-string-payload-key", "invalid payload field type"),
    ("non-gather-event", "declaration event must be gather"),
    ("unsafe-event-summary", "invalid event field: summary"),
    ("extra-event-field", "unexpected event field unexpected_intake_field"),
    ("tick-clock", "unexpected clock update"),
    ("changed-false", "state-changing intake must set changed true"),
    ("wrong-intent", "intent must be gather"),
    ("meta-update", "unexpected meta update"),
    ("missing-upsert", "missing/duplicate target upsert"),
    ("non-list-upsert", "missing/duplicate target upsert"),
    ("duplicate-upsert", "missing/duplicate target upsert"),
    ("non-string-upsert-key", "invalid upsert field type"),
    ("non-string-item-key", "invalid item field type"),
    ("extra-upsert", "unexpected entity upsert"),
    ("output-id-mismatch", "missing/duplicate target upsert"),
    ("quantity-mismatch", "quantity mismatch"),
    ("unit-mismatch", "unit mismatch"),
    ("empty-unit", "unit must be a non-empty string"),
    ("blank-unit", "unit must be a non-empty string"),
    ("unsafe-unit", "unit must be a non-empty string"),
    ("edge-space-unit", "unit must be a non-empty string"),
    ("unsafe-alias", "metadata mismatch: aliases"),
    ("blank-output-id", "invalid output_entity_id"),
    ("missing-item", "target item payload must be an exact mapping"),
    ("non-item-target", "target must be an item"),
    ("missing-item-quantity", "missing field: upsert item.quantity"),
    ("missing-item-unit", "missing field: upsert item.unit"),
    ("missing-anchors", "intake output requires location_id or owner_id"),
    ("ownership-mismatch", "ownership mismatch"),
    ("unknown-location", "unknown location anchor"),
    ("retired-location", "retired location anchor"),
    ("hidden-location", "hidden location anchor"),
    ("blank-location", "invalid location anchor"),
    ("wrong-location-type", "location anchor must reference a location"),
    ("unknown-owner", "unknown owner anchor"),
    ("retired-owner", "retired owner anchor"),
    ("hidden-owner", "hidden owner anchor"),
    ("hidden-clock-owner", "hidden owner anchor"),
    ("hidden-world-setting-owner", "hidden owner anchor"),
    ("both-anchors", "intake output requires exactly one location_id or owner_id"),
    ("zero", "intake output quantity must be positive"),
    ("negative", "intake output quantity must be positive"),
    ("bool", "invalid numeric type"),
    ("string", "invalid numeric type"),
    ("nan", "non-finite quantity"),
    ("infinity", "non-finite quantity"),
    ("negative-infinity", "non-finite quantity"),
    ("sqlite-int-high", "quantity out of range"),
    ("sqlite-int-low", "quantity out of range"),
    ("float-overflow-int", "quantity out of range"),
    ("float-int-precision-loss", "quantity out of range"),
    ("invalid-new-properties", "metadata mismatch: item.properties"),
    ("huge-metadata-int", "metadata mismatch: item.properties"),
    ("cyclic-payload", "invalid payload value"),
    ("invalid-new-stackable", "invalid new metadata: item.stackable"),
    ("invalid-new-durability", "invalid new metadata: item.durability_current"),
    ("negative-new-durability", "invalid new metadata: item.durability_current"),
    ("oversized-new-durability", "invalid new metadata: item.durability_max"),
    ("inverted-new-durability", "invalid new metadata: item.durability"),
    ("hidden-output-target", "hidden output target"),
    ("unknown-output-visibility", "invalid new metadata: entity.visibility"),
)


@pytest.mark.parametrize(("case", "reason"), INVALID_INTAKE_CASES)
def test_invalid_gather_intake_is_blocked_by_stable_semantic_error_without_mutation(
    intake_campaign: Campaign,
    case: str,
    reason: str,
) -> None:
    report = _run_report(intake_campaign, _invalid_delta(intake_campaign, case))
    _assert_intake_blocked(report, reason)


def test_cyclic_new_metadata_is_rejected_without_recursion_or_mutation(
    intake_campaign: Campaign,
) -> None:
    delta = _base_delta(intake_campaign)
    details = delta["upsert_entities"][0]["details"]
    details["cycle"] = details

    report = _run_report(intake_campaign, delta)

    _assert_intake_blocked(report, "metadata mismatch: entity.details")


def test_shared_acyclic_new_metadata_is_valid(intake_campaign: Campaign) -> None:
    delta = _base_delta(intake_campaign)
    shared = {"preserve": True}
    delta["upsert_entities"][0]["details"] = {"left": shared, "right": shared}

    report = _run_report(intake_campaign, delta)

    stage = report.stage("resolver_delta_contract")
    assert stage is not None
    assert stage.status == "ok", report.to_dict()


def test_existing_intake_update_accepts_declared_quantity_and_alias_reordering_only(
    intake_campaign: Campaign,
) -> None:
    delta = _existing_update_delta(intake_campaign)
    delta["upsert_entities"][0]["aliases"] = ["测试入库草药", "intake herb"]
    report = _run_report(intake_campaign, delta)
    stage = report.stage("resolver_delta_contract")
    assert stage is not None
    assert stage.status == "ok", report.to_dict()


def _invalid_existing_update(campaign: Campaign, case: str) -> dict[str, Any]:
    delta = _existing_update_delta(campaign)
    target = delta["upsert_entities"][0]
    item = target["item"]
    if case == "updated-turn":
        target["updated_turn_id"] = "turn:forged"
    elif case == "name":
        target["name"] = "Replacement Name"
    elif case == "status":
        target["status"] = "inactive"
    elif case == "visibility":
        target["visibility"] = "hidden"
    elif case == "summary":
        target["summary"] = "Replacement summary."
    elif case == "missing-summary":
        target.pop("summary")
    elif case == "details":
        target["details"]["nested"]["preserve"] = 1
    elif case == "missing-details":
        target.pop("details")
    elif case == "missing-aliases":
        target.pop("aliases")
    elif case == "duplicate-alias":
        target["aliases"].append("intake herb")
    elif case == "new-alias":
        target["aliases"].append("replacement alias")
    elif case == "category":
        item["category"] = "consumable"
    elif case == "quality":
        item["quality"] = "legendary"
    elif case == "durability":
        item["durability_current"] = 1
    elif case == "stackable":
        item["stackable"] = 1
    elif case == "properties":
        item["properties"]["fresh"] = 1
    elif case == "missing-properties":
        item.pop("properties")
    elif case == "extra-target-field":
        target["future_metadata"] = {"must_persist": True}
    elif case == "extra-item-field":
        item["future_metadata"] = {"must_persist": True}
    elif case == "extra-subrecord":
        target["character"] = {"role": "forged"}
    elif case == "self-owner":
        payload = delta["events"][0]["payload"]
        payload["owner_id"] = EXISTING_OUTPUT_ID
        target["owner_id"] = EXISTING_OUTPUT_ID
    else:
        raise AssertionError(f"unknown existing update case: {case}")
    return delta


INVALID_EXISTING_UPDATE_CASES = (
    ("updated-turn", "updated_turn_id is commit-owned"),
    ("name", "metadata mismatch: entity.name"),
    ("status", "metadata mismatch: entity.status"),
    ("visibility", "hidden output target"),
    ("summary", "metadata mismatch: entity.summary"),
    ("missing-summary", "metadata mismatch: entity.summary"),
    ("details", "metadata mismatch: entity.details"),
    ("missing-details", "metadata mismatch: entity.details"),
    ("missing-aliases", "metadata mismatch: aliases"),
    ("duplicate-alias", "metadata mismatch: aliases"),
    ("new-alias", "metadata mismatch: aliases"),
    ("category", "metadata mismatch: item.category"),
    ("quality", "metadata mismatch: item.quality"),
    ("durability", "metadata mismatch: item.durability_current"),
    ("stackable", "metadata mismatch: item.stackable"),
    ("properties", "metadata mismatch: item.properties"),
    ("missing-properties", "metadata mismatch: item.properties"),
    ("extra-target-field", "metadata mismatch: unexpected target field future_metadata"),
    ("extra-item-field", "metadata mismatch: unexpected item field future_metadata"),
    ("extra-subrecord", "metadata mismatch: unexpected target field character"),
    ("self-owner", "output cannot own itself"),
)


@pytest.mark.parametrize(("case", "reason"), INVALID_EXISTING_UPDATE_CASES)
def test_existing_intake_update_cannot_overwrite_undeclared_metadata(
    intake_campaign: Campaign,
    case: str,
    reason: str,
) -> None:
    report = _run_report(intake_campaign, _invalid_existing_update(intake_campaign, case))
    _assert_intake_blocked(report, reason)
