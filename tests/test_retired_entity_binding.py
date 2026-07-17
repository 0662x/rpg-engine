from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterator

import pytest

from rpg_engine.ai_intent import ExternalIntentContractError, bind_intent_candidate
from rpg_engine.ai_intent.binder import find_entity_candidates
from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, resolve_entity, resolve_entity_partial_token, upsert_entity
from rpg_engine.intent_manifest import build_intent_manifest
from rpg_engine.projection_service import ProjectionService
from rpg_engine.save_manager import SaveManager
from tests.helpers import tree_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_ADVENTURE = ENGINE_ROOT / "examples" / "v1_minimal_adventure"


@pytest.fixture
def temporary_authority(tmp_path: Path) -> Iterator[tuple[SaveManager, Path]]:
    source_before = tree_digest(MINIMAL_ADVENTURE)
    manager, save = start_temporary_authority(tmp_path / "workspace")
    try:
        yield manager, save
    finally:
        assert tree_digest(MINIMAL_ADVENTURE) == source_before


def start_temporary_authority(workspace: Path) -> tuple[SaveManager, Path]:
    campaign = workspace / "campaigns" / "adventure"
    campaign.parent.mkdir(parents=True)
    shutil.copytree(MINIMAL_ADVENTURE, campaign)
    manager = SaveManager(workspace, default_campaign="campaigns/adventure")
    started = manager.start_or_continue(campaign="campaigns/adventure")
    assert started["ok"] is True
    save = workspace / str(started["save"]["path"])
    return manager, save


def external_candidate(
    *,
    action: str,
    slots: dict[str, Any],
    stale_contract: bool = False,
) -> dict[str, Any]:
    manifest = build_intent_manifest()
    manifest_digest = str(manifest["manifest_digest"])
    if stale_contract:
        manifest_digest = "0" * 64 if manifest_digest != "0" * 64 else "1" * 64
    return {
        "contract": {
            "manifest_schema_version": str(manifest["schema_version"]),
            "manifest_digest": manifest_digest,
            "safety_vocabulary_version": str(manifest["safety_vocabulary"]["version"]),
            "safety_vocabulary_digest": str(manifest["safety_vocabulary"]["digest"]),
        },
        "kind": "single",
        "mode": "action",
        "action": action,
        "slots": dict(slots),
        "plan": [],
        "confidence": "high",
        "missing_slots": [],
        "needs_confirmation": [],
        "safety_flags": [],
        "reason": "Story 6.9 low-trust external candidate.",
    }


def set_entity_status(save: Path, entity_id: str, status: str, *, refresh: bool = True) -> None:
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        updated = conn.execute("update entities set status=? where id=?", (status, entity_id))
        assert updated.rowcount == 1
        conn.commit()
        if refresh:
            report = ProjectionService(campaign, conn).refresh(
                names=["search", "snapshots", "cards"],
                dirty_only=False,
                profile="test:story_6_9_status",
            )
            assert report.ok, report.to_dict()


def confirmation_state_snapshot(manager: SaveManager) -> dict[str, bytes | None]:
    paths = {
        "pending_action": manager.pending_action_path(),
        "confirmation_receipt": manager.confirmation_receipt_path(),
    }
    return {name: path.read_bytes() if path.exists() else None for name, path in paths.items()}


def assert_pending_has_no_entity_provenance(pending: dict[str, Any]) -> None:
    proposal = pending["turn_proposal"]
    binding = proposal["intent"]["decision_trace"]["binding"]
    assert binding["entity_bindings"] == {}
    assert proposal["preview"]["facts_used"] == []
    assert proposal["facts_used"] == []


@pytest.mark.parametrize("status", ["retired", "archived"])
@pytest.mark.parametrize("reference", ["loc:old-bridge", "Old Bridge", "sealed bridge"])
def test_public_non_active_location_references_never_create_committable_pending(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
    reference: str,
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", status)
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="前往候选目的地",
        external_intent_candidate=external_candidate(
            action="travel",
            slots={"destination": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert result["session_id"] is None
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize(
    "reference",
    [
        "loc:old-bridge",
        "Old Bridge",
        "sealed bridge",
        "\u200bloc:old-bridge\u200b",
        "\u2060loc:old-bridge\u2060",
    ],
)
def test_public_active_location_references_keep_the_positive_preview_path(
    temporary_authority: tuple[SaveManager, Path],
    reference: str,
) -> None:
    manager, save = temporary_authority
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="前往旧桥",
        external_intent_candidate=external_candidate(
            action="travel",
            slots={"destination": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["action"] == "travel"
    assert result["ready_to_confirm"] is True
    assert result["saved"] is False
    assert result["session_id"]
    assert manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["action"] == "travel"
    assert pending["turn_proposal"]["intent"]["options"]["destination"] == "loc:old-bridge"
    assert pending["delta"]["location_after"] == "loc:old-bridge"
    assert tree_digest(save) == before


def test_direct_binder_rejects_non_active_id_name_alias_and_free_text_fallback(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", "\u001cＲｅｔｉｒｅｄ\u2060", refresh=False)

    with connect(load_campaign(save)) as conn:
        for reference in ("loc:old-bridge", "Old Bridge", "sealed bridge"):
            travel = bind_intent_candidate(
                conn,
                external_candidate(action="travel", slots={"destination": reference}),
            )
            assert travel.binding_status == "missing"
            assert "destination" not in travel.options
            assert travel.entity_bindings == {}
            trace = travel.decision_trace["binder"]["slot_trace"]["destination"]
            assert "candidates" not in trace
            assert "entity_id" not in trace

        explore = bind_intent_candidate(
            conn,
            external_candidate(action="explore", slots={"target": "sealed bridge"}),
        )
        assert explore.binding_status == "missing"
        assert "target" not in explore.options
        assert explore.entity_bindings == {}

        missing_free_text = bind_intent_candidate(
            conn,
            external_candidate(action="explore", slots={"target": "unmapped cairn"}),
        )
        assert missing_free_text.binding_status == "bound"
        assert missing_free_text.options["target"] == "unmapped cairn"


@pytest.mark.parametrize("status", ["retired", "archived"])
def test_non_active_partial_entity_match_cannot_fall_back_to_free_text(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
) -> None:
    _, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", status, refresh=False)

    with connect(load_campaign(save)) as conn:
        bound = bind_intent_candidate(
            conn,
            external_candidate(action="explore", slots={"target": "Old Brid"}),
        )

    assert bound.binding_status == "missing"
    assert "target" not in bound.options
    assert bound.entity_bindings == {}


@pytest.mark.parametrize("status", ["retired", "archived"])
@pytest.mark.parametrize("reference", ["sealed bridge", "Old Brid"])
def test_public_entity_or_text_cannot_publish_non_active_reference_as_free_text(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
    reference: str,
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", status)
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize("status", ["retired", "archived", "unknown"])
@pytest.mark.parametrize(
    "reference",
    [
        "Inspect Old Bridge nearby",
        "Inspect OLD BRIDGE nearby",
        "Please inspect sealed bridge nearby",
        "inspect ｓｅａｌｅｄ ｂｒｉｄｇｅ nearby",
    ],
)
def test_public_hybrid_composite_reference_cannot_be_reresolved_as_non_active(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
    reference: str,
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", status)
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_public_hybrid_resolver_body_match_cannot_revive_retired_entity(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        conn.execute(
            "update entities set status='retired', summary='Quartzium resonance audit control.' "
            "where id='loc:old-bridge'"
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_resolver_body",
        )
        assert report.ok, report.to_dict()
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": "inspect quartzium nearby"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_non_active_resolver_body_match_cannot_be_hidden_by_active_winner(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        conn.execute(
            "update entities set status='retired', summary='Quartzium resonance audit control.' "
            "where id='loc:old-bridge'"
        )
        upsert_entity(
            conn,
            {
                "id": "item:quartzium-active-control",
                "type": "item",
                "name": "Quartzium Active Control",
                "status": "active",
                "visibility": "known",
                "summary": "Quartzium resonance audit control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_resolver_non_active_any_match",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": "inspect quartzium nearby"},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": "inspect quartzium nearby"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_active_exact_resolver_token_shields_non_active_partial_body_match(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        conn.execute(
            "update entities set status='retired', summary='Quartzium historical audit control.' "
            "where id='loc:old-bridge'"
        )
        upsert_entity(
            conn,
            {
                "id": "item:quartzium-active-control",
                "type": "item",
                "name": "quartzium",
                "status": "active",
                "visibility": "known",
                "summary": "Current quartzium control.",
            },
        )
        conn.commit()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": "inspect quartzium nearby"},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == "inspect quartzium nearby"
    assert direct.entity_bindings == {}


def test_first_exact_resolver_token_non_active_winner_cannot_be_hidden_by_later_active_token(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", "retired")
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "item:z-active-control",
                "type": "item",
                "name": "z",
                "status": "active",
                "visibility": "known",
                "summary": "Active resolver ordering control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_resolver_exact_token_order",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": "old-bridge z"},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": "old-bridge z"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_unpaired_unicode_surrogate_fails_closed_before_sqlite_binding(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    malformed_reference = "Old" + chr(0xD800) + " Bridge"
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="travel",
                slots={"destination": malformed_reference},
            ),
        )

    assert direct.binding_status == "invalid"
    assert "destination" not in direct.options
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="前往候选目标",
        external_intent_candidate=external_candidate(
            action="travel",
            slots={"destination": malformed_reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize("reference", ["前往古桥附近", "去旧桥遗址看看"])
def test_public_cjk_composite_non_active_name_and_alias_fail_closed(
    temporary_authority: tuple[SaveManager, Path],
    reference: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:ancient-bridge-control",
                "type": "location",
                "name": "旧桥遗址",
                "status": "retired",
                "visibility": "known",
                "summary": "中文复合引用控制实体。",
                "aliases": ["古桥"],
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_cjk_composite",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize(
    ("entity_name", "reference"),
    [
        ("고대교", "고대교근처"),
        ("コダイバシ", "コダイバシノチカク"),
        ("สะพานเก่า", "ไปสะพานเก่าเถอะ"),
        ("ຂົວເກົ່າ", "ໄປຂົວເກົ່າກັນ"),
        ("ស្ពានចាស់", "ទៅស្ពានចាស់មើល"),
        ("တံတားဟောင်း", "တံတားဟောင်းနားသွား"),
        ("पुरानापुल", "मैंपुरानापुलजाऊंगा"),
        ("পুরানোসেতু", "আমিপুরানোসেতুতেযাব"),
        ("பழையபாலம்", "நான்பழையபாலம்போகிறேன்"),
        ("పాతవంతెన", "పాతవంతెనకువెళ్దాం"),
        ("جسرقديم", "اذهبجسرقديمالآن"),
        ("ძველიხიდი", "ძველიხიდიახლა"),
        ("старыймост", "кстарыймостсейчас"),
        ("παλιάγέφυρα", "στηπαλιάγέφυρατώρα"),
    ],
)
def test_public_unsegmented_script_composite_non_active_name_fails_closed(
    temporary_authority: tuple[SaveManager, Path],
    entity_name: str,
    reference: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:unsegmented-cjk-retired",
                "type": "location",
                "name": entity_name,
                "status": "retired",
                "visibility": "known",
                "summary": "Unsegmented-script lifecycle control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_unsegmented_script",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize(
    ("canonical_reference", "prefix", "suffix"),
    [
        ("Old Bridge", "前往", "附近"),
        ("sealed bridge", "前往", "附近"),
        ("Old Bridge", "اذهب", "الآن"),
        ("sealed bridge", "ИдиК", "Сейчас"),
    ],
)
def test_public_cross_script_composite_non_active_reference_fails_closed(
    temporary_authority: tuple[SaveManager, Path],
    canonical_reference: str,
    prefix: str,
    suffix: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    reference = f"{prefix}{canonical_reference}{suffix}"
    with connect(campaign) as conn:
        conn.execute("update entities set status='retired' where id='loc:old-bridge'")
        upsert_entity(
            conn,
            {
                "id": "loc:cross-script-active-partial",
                "type": "location",
                "name": f"{reference}哨站",
                "status": "active",
                "visibility": "known",
                "summary": "Cross-script active partial control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_cross_script",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize(
    "separator",
    [
        "\u0338",  # Mn: COMBINING LONG SOLIDUS OVERLAY
        "\u0903",  # Mc: DEVANAGARI SIGN VISARGA
        "\u20dd",  # Me: COMBINING ENCLOSING CIRCLE
    ],
)
def test_unicode_mark_or_format_inside_word_does_not_trigger_non_active_short_alias(
    temporary_authority: tuple[SaveManager, Path],
    separator: str,
) -> None:
    manager, save = temporary_authority
    reference = f"ore{separator}work"
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "item:retired-ore-marker",
                "type": "item",
                "name": "Retired Ore Marker",
                "status": "retired",
                "visibility": "known",
                "summary": "Unicode continuation control.",
                "aliases": ["ore"],
            },
        )
        conn.commit()
        report = ProjectionService(load_campaign(save), conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_unicode_continuation",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == reference
    assert direct.entity_bindings == {}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    assert result["saved"] is False
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["turn_proposal"]["intent"]["options"]["target"] == reference
    assert_pending_has_no_entity_provenance(pending)
    assert tree_digest(save) == before


@pytest.mark.parametrize(
    "reference",
    [
        "O\u034fl\u034fd B\u034fr\u034fi\u034fd\u034fg\u034fe",
        "Old\ufe0f Bridge",
    ],
)
def test_default_ignorable_inside_non_active_canonical_reference_fails_closed(
    temporary_authority: tuple[SaveManager, Path],
    reference: str,
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", "retired")
    with connect(load_campaign(save)) as conn:
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_shared_resolver_default_ignorable_folding_cannot_revive_retired_fts_fact(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    target = "inspect quartz\u115fium nearby"
    with connect(campaign) as conn:
        conn.execute(
            "update entities set status='retired', summary=? where id='loc:old-bridge'",
            ("Quartz\u115fium resonance audit control.",),
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_resolver_default_ignorable",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": target},
            ),
        )
        assert resolve_entity(conn, target) is None

    assert direct.binding_status == "bound"
    assert direct.options["target"] == target
    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": target},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    pending = manager.read_pending_action() or {}
    assert_pending_has_no_entity_provenance(pending)


def test_shared_partial_like_order_uses_literal_escape_semantics(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _manager, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "item:alias-source",
                "type": "item",
                "name": "x",
                "status": "active",
                "visibility": "known",
                "summary": "Alias priority control.",
                "aliases": ["a_b"],
            },
        )
        upsert_entity(
            conn,
            {
                "id": "item:name-target",
                "type": "item",
                "name": "a_b-long-name",
                "status": "active",
                "visibility": "known",
                "summary": "Name prefix priority control.",
            },
        )
        conn.commit()
        resolved = resolve_entity_partial_token(conn, "a_b")

    assert resolved is not None
    assert resolved["id"] == "item:name-target"


@pytest.mark.parametrize("separator", ["\u0338", "\u0903", "\u20dd", "\u115f"])
def test_mark_or_filler_inside_non_active_canonical_reference_fails_closed(
    temporary_authority: tuple[SaveManager, Path],
    separator: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    reference = f"Alpha{separator} Bravo nearby"
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:retired-alpha-bravo",
                "type": "location",
                "name": "Alpha Bravo",
                "status": "retired",
                "visibility": "known",
                "summary": "Canonical mark-folding control.",
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:active-alpha-bravo-outpost",
                "type": "location",
                "name": f"{reference} Outpost",
                "status": "active",
                "visibility": "known",
                "summary": "Active partial control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_canonical_mark_folding",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_precomposed_marks_cannot_bypass_non_active_canonical_reference(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    reference = "M\u0301o\u0301 patrol"
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:retired-mo-control",
                "type": "location",
                "name": "Mo",
                "status": "retired",
                "visibility": "known",
                "summary": "Precomposed mark control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_precomposed_mark",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "patrol", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="执行巡逻",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "patrol", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_non_latin_multicodepoint_identity_survives_mark_folding(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    reference = "मैंकाआऊंगा"
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:devanagari-mark-retired",
                "type": "location",
                "name": "का",
                "status": "retired",
                "visibility": "known",
                "summary": "Devanagari multi-codepoint control.",
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:devanagari-mark-active",
                "type": "location",
                "name": f"{reference} Annex",
                "status": "active",
                "visibility": "known",
                "summary": "Active partial control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_non_latin_mark_identity",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="लक्ष्य जाँचें",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize("ignorable", ["\u2065", "\ufff0", "\U000e0001"])
def test_full_default_ignorable_ranges_preserve_canonical_lifecycle_identity(
    temporary_authority: tuple[SaveManager, Path],
    ignorable: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        active = bind_intent_candidate(
            conn,
            external_candidate(
                action="travel",
                slots={"destination": f"Old{ignorable} Bridge"},
            ),
        )
        upsert_entity(
            conn,
            {
                "id": "loc:retired-default-ignorable",
                "type": "location",
                "name": f"Alpha{ignorable}Bravo",
                "status": "retired",
                "visibility": "known",
                "summary": "Default-ignorable lifecycle control.",
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:active-default-ignorable-partial",
                "type": "location",
                "name": "AlphaBravo nearby Outpost",
                "status": "active",
                "visibility": "known",
                "summary": "Default-ignorable active partial control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_full_default_ignorable",
        )
        assert report.ok, report.to_dict()
        non_active = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": "AlphaBravo nearby"},
            ),
        )

    assert active.binding_status == "bound"
    assert active.options["destination"] == "loc:old-bridge"
    assert active.entity_bindings == {"destination": "loc:old-bridge"}
    assert non_active.binding_status == "missing"
    assert "target" not in non_active.options
    assert non_active.entity_bindings == {}
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": "AlphaBravo nearby"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


def test_public_cjk_extension_b_composite_blocks_active_partial_rebinding(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    ideograph = "\U00020000\U00020001"
    reference = f"前往{ideograph}附近"
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:extension-b-retired",
                "type": "location",
                "name": ideograph,
                "status": "retired",
                "visibility": "known",
                "summary": "CJK Extension B lifecycle control.",
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:extension-b-active-annex",
                "type": "location",
                "name": f"{reference}哨站",
                "status": "active",
                "visibility": "known",
                "summary": "CJK Extension B active partial control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_cjk_extension_b",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "target" not in direct.options
    assert direct.entity_bindings == {}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert not manager.pending_action_path().exists()
    assert tree_digest(save) == before


def test_public_text_or_entity_checks_non_active_partial_before_free_text_fallback(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        conn.execute("update entities set status='retired' where id='item:field-rations'")
        upsert_entity(
            conn,
            {
                "id": "project:rations-plan",
                "type": "project",
                "name": "Rations Plan",
                "status": "active",
                "visibility": "known",
                "location_id": "loc:watch-camp",
                "summary": "A temporary craft project control.",
            },
        )
        upsert_entity(
            conn,
            {
                "id": "recipe:rations-plan",
                "type": "recipe",
                "name": "Rations Plan",
                "status": "active",
                "visibility": "known",
                "summary": "A temporary structured recipe control.",
                "details": {
                    "recipe_profile": {
                        "inputs": ["item:signal-flare"],
                        "output": "Field Rations",
                        "time_cost": "30m",
                    }
                },
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_text_or_entity",
        )
        assert report.ok, report.to_dict()
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="制作候选补给",
        external_intent_candidate=external_candidate(
            action="craft",
            slots={
                "project": "Rations Plan",
                "target": "Field Ratio",
                "materials": ["Signal Flare"],
                "time_cost": "30m",
            },
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == before


@pytest.mark.parametrize("reference", ["_", "%", "!"])
def test_free_text_like_metacharacters_are_not_entity_patterns(
    temporary_authority: tuple[SaveManager, Path],
    reference: str,
) -> None:
    _, save = temporary_authority

    with connect(load_campaign(save)) as conn:
        bound = bind_intent_candidate(
            conn,
            external_candidate(action="explore", slots={"target": reference}),
        )

    assert bound.binding_status == "bound"
    assert bound.options["target"] == reference
    assert bound.entity_bindings == {}


@pytest.mark.parametrize("reference", ["\u200b", "\u2060", "\u200b \u2060"])
def test_edge_whitespace_only_entity_input_never_binds_or_creates_pending(
    temporary_authority: tuple[SaveManager, Path],
    reference: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        conn.execute(
            "insert into aliases(entity_id, alias) values (?, ?)",
            ("loc:old-bridge", "\u200b"),
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_edge_whitespace_only",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": reference}),
        )
        hybrid = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "missing"
    assert "destination" not in direct.options
    assert direct.entity_bindings == {}
    assert hybrid.binding_status == "missing"
    assert "target" not in hybrid.options
    assert hybrid.entity_bindings == {}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert not manager.pending_action_path().exists()
    assert tree_digest(save) == before


def test_text_or_entity_exact_only_keeps_composite_active_id_as_literal(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    reference = "make item:signal-flare now"
    with connect(load_campaign(save)) as conn:
        bound = bind_intent_candidate(
            conn,
            external_candidate(action="craft", slots={"target": reference}),
        )

    assert bound.binding_status == "bound"
    assert bound.options["target"] == reference
    assert bound.entity_bindings == {}


@pytest.mark.parametrize(
    ("entity_id", "name", "reference"),
    [
        ("loc:percent-literal", "100% Pure", "100%"),
        ("loc:underscore-literal", "A_B Outpost", "A_"),
        ("loc:bang-literal", "Bang!Mark Camp", "!M"),
    ],
)
def test_like_metacharacters_match_literal_entity_text_for_binder_and_shared_query(
    temporary_authority: tuple[SaveManager, Path],
    entity_id: str,
    name: str,
    reference: str,
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": entity_id,
                "type": "location",
                "name": name,
                "status": "active",
                "visibility": "known",
                "summary": "A literal SQL LIKE metacharacter control.",
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": reference}),
        )
        shared_matches = find_entity_candidates(conn, reference, allowed_types={"location"})

    assert bound.binding_status == "bound"
    assert bound.options["destination"] == entity_id
    assert bound.entity_bindings == {"destination": entity_id}
    assert [str(row["id"]) for row in shared_matches] == [entity_id]


def test_short_non_active_alias_does_not_match_inside_unrelated_literal_word(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "item:retired-ore-control",
                "type": "item",
                "name": "Retired Mineral Control",
                "status": "retired",
                "visibility": "known",
                "summary": "A short-alias boundary control.",
                "aliases": ["ore"],
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "patrol", "target": "forest patrol"},
            ),
        )

    assert bound.binding_status == "bound"
    assert bound.options["target"] == "forest patrol"
    assert bound.entity_bindings == {}


def test_single_unsegmented_non_active_alias_does_not_match_inside_literal_word(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    reference = "山路巡逻"
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:retired-mountain-alias",
                "type": "location",
                "name": "Retired Mountain Alias",
                "status": "retired",
                "visibility": "known",
                "summary": "Single-character alias control.",
                "aliases": ["山"],
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_single_unsegmented_alias",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "patrol", "target": reference},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == reference
    assert direct.entity_bindings == {}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="执行巡逻",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "patrol", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["turn_proposal"]["intent"]["options"]["target"] == reference
    assert_pending_has_no_entity_provenance(pending)
    assert tree_digest(save) == before


@pytest.mark.parametrize("literal", ["%", "_", "!"])
def test_resolver_like_metacharacter_literal_does_not_match_non_active_entity(
    temporary_authority: tuple[SaveManager, Path],
    literal: str,
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "item:retired-like-metacharacter",
                "type": "item",
                "name": "Retired Like Metacharacter",
                "status": "retired",
                "visibility": "known",
                "summary": f"Temporary {literal} marker.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_resolver_like_literal",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": literal},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == literal
    assert direct.entity_bindings == {}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": literal},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["turn_proposal"]["intent"]["options"]["target"] == literal
    assert_pending_has_no_entity_provenance(pending)
    assert tree_digest(save) == before


def test_resolver_exact_token_suffix_like_treats_underscore_as_literal(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    reference = "foo_%"
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:food",
                "type": "location",
                "name": "Retired Food",
                "status": "retired",
                "visibility": "known",
                "summary": "Exact-token suffix LIKE control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_exact_token_suffix_like",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == reference
    assert direct.entity_bindings == {}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["turn_proposal"]["intent"]["options"]["target"] == reference
    assert_pending_has_no_entity_provenance(pending)
    assert tree_digest(save) == before


def test_non_active_short_id_does_not_shadow_active_qualified_id_composite(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:old",
                "type": "location",
                "name": "Retired Short ID Control",
                "status": "retired",
                "visibility": "known",
                "summary": "A qualified-ID boundary control.",
            },
        )
        conn.commit()
        report = ProjectionService(load_campaign(save), conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_qualified_id_boundary",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "visit", "target": "visit loc:old-bridge today"},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == "loc:old-bridge"
    assert direct.entity_bindings == {"target": "loc:old-bridge"}

    before = tree_digest(save)
    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "visit", "target": "visit loc:old-bridge today"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    assert result["saved"] is False
    assert tree_digest(save) == before
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["turn_proposal"]["facts_used"] == ["loc:old-bridge"]


def test_non_active_short_id_does_not_shadow_active_dotted_id_composite(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    campaign = load_campaign(save)
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:old",
                "type": "location",
                "name": "Retired Dotted Prefix Control",
                "status": "retired",
                "visibility": "known",
                "summary": "A dotted-ID retired prefix control.",
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:old.bridge",
                "type": "location",
                "name": "Active Dotted Bridge",
                "status": "active",
                "visibility": "known",
                "summary": "A legal active dotted-ID control.",
            },
        )
        conn.commit()
        report = ProjectionService(campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_dotted_id_boundary",
        )
        assert report.ok, report.to_dict()
        direct = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "visit", "target": "visit loc:old.bridge today"},
            ),
        )

    assert direct.binding_status == "bound"
    assert direct.options["target"] == "loc:old.bridge"
    assert direct.entity_bindings == {"target": "loc:old.bridge"}
    before = tree_digest(save)

    result = manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "visit", "target": "visit loc:old.bridge today"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is True
    assert result["ready_to_confirm"] is True
    assert tree_digest(save) == before
    pending = manager.read_pending_action()
    assert pending is not None
    assert pending["turn_proposal"]["facts_used"] == ["loc:old.bridge"]


@pytest.mark.parametrize(
    ("status", "expected_status"),
    [
        ("active", "bound"),
        ("\u001cＡｃｔｉｖｅ\u2060", "bound"),
        ("retired", "missing"),
        ("\u001cＲｅｔｉｒｅｄ\u2060", "missing"),
        ("archived", "missing"),
        ("\u001cＡｒｃｈｉｖｅｄ\u2060", "missing"),
        ("unknown", "missing"),
        ("", "missing"),
    ],
)
def test_binder_lifecycle_status_is_nfkc_normalized_and_unknown_fails_closed(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
    expected_status: str,
) -> None:
    _, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", status, refresh=False)

    with connect(load_campaign(save)) as conn:
        bound = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "loc:old-bridge"}),
        )

    assert bound.binding_status == expected_status
    if expected_status == "bound":
        assert bound.options["destination"] == "loc:old-bridge"
    else:
        assert "destination" not in bound.options


@pytest.mark.parametrize(
    ("status", "expected_ready"),
    [
        ("\u001cＡｃｔｉｖｅ\u2060", True),
        ("\u001cＲｅｔｉｒｅｄ\u2060", False),
        ("unknown", False),
        ("", False),
    ],
)
def test_public_ingress_uses_normalized_active_only_lifecycle(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
    expected_ready: bool,
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", status)
    before = tree_digest(save)
    confirmation_before = confirmation_state_snapshot(manager)

    result = manager.player_turn(
        user_text="前往候选目的地",
        external_intent_candidate=external_candidate(
            action="travel",
            slots={"destination": "loc:old-bridge"},
        ),
        intent_ai="off",
    )

    assert result["ready_to_confirm"] is expected_ready
    assert result["saved"] is False
    assert tree_digest(save) == before
    if expected_ready:
        assert result["ok"] is True
        pending = manager.read_pending_action()
        assert pending is not None
        assert pending["turn_proposal"]["intent"]["options"]["destination"] == "loc:old-bridge"
    else:
        assert result["ok"] is False
        assert not manager.pending_action_path().exists()
        assert not manager.confirmation_receipt_path().exists()
        assert confirmation_state_snapshot(manager) == confirmation_before


def test_default_entity_candidate_lookup_keeps_existing_query_read_semantics(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", "retired", refresh=False)

    with connect(load_campaign(save)) as conn:
        for reference in ("loc:old-bridge", "Old Bridge", "sealed bridge", "Old Brid"):
            matches = find_entity_candidates(conn, reference, allowed_types=None)
            assert [str(row["id"]) for row in matches] == ["loc:old-bridge"]

        conn.execute("update entities set visibility='gm-only' where id='loc:old-bridge'")
        assert find_entity_candidates(conn, "sealed bridge", allowed_types=None) == []
        gm_matches = find_entity_candidates(conn, "Old Brid", allowed_types=None, view="gm")
        assert [str(row["id"]) for row in gm_matches] == ["loc:old-bridge"]

        conn.execute("update entities set status='archived', visibility='known' where id='loc:old-bridge'")
        assert find_entity_candidates(conn, "Old Bridge", allowed_types=None) == []


def test_inactive_exact_match_blocks_unrelated_active_partial_match(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        conn.execute("update entities set status='retired' where id='loc:old-bridge'")
        upsert_entity(
            conn,
            {
                "id": "loc:old-bridge-annex",
                "type": "location",
                "name": "Old Bridge Annex",
                "status": "active",
                "visibility": "known",
                "summary": "A temporary active control location.",
                "aliases": ["annex"],
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "Old Bridge"}),
        )

    assert bound.binding_status == "missing"
    assert "destination" not in bound.options
    assert bound.entity_bindings == {}


def test_inactive_partial_match_blocks_active_partial_match(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        conn.execute("update entities set status='retired' where id='loc:old-bridge'")
        upsert_entity(
            conn,
            {
                "id": "loc:old-bridge-annex",
                "type": "location",
                "name": "Old Bridge Annex",
                "status": "active",
                "visibility": "known",
                "summary": "A temporary active partial-match control.",
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "Old Brid"}),
        )

    assert bound.binding_status == "missing"
    assert "destination" not in bound.options
    assert bound.entity_bindings == {}


def test_non_active_composite_reference_blocks_unrelated_active_partial_rebinding(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        conn.execute("update entities set status='retired' where id='loc:old-bridge'")
        upsert_entity(
            conn,
            {
                "id": "loc:inspection-annex",
                "type": "location",
                "name": "Inspect Old Bridge nearby annex",
                "status": "active",
                "visibility": "known",
                "summary": "An unrelated active partial-match control.",
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": "Inspect Old Bridge nearby"},
            ),
        )

    assert bound.binding_status == "missing"
    assert "target" not in bound.options
    assert bound.entity_bindings == {}


def test_active_exact_match_wins_over_non_active_partial_history(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:old-bridge-annex",
                "type": "location",
                "name": "Old Bridge Annex",
                "status": "retired",
                "visibility": "known",
                "summary": "A retired partial-match history control.",
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "Old Bridge"}),
        )

    assert bound.binding_status == "bound"
    assert bound.options["destination"] == "loc:old-bridge"
    assert bound.entity_bindings == {"destination": "loc:old-bridge"}


def test_active_alias_wins_when_retired_history_uses_the_same_old_alias(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        conn.execute("update entities set status='retired' where id='loc:old-bridge'")
        upsert_entity(
            conn,
            {
                "id": "loc:new-bridge",
                "type": "location",
                "name": "New Bridge",
                "status": "active",
                "visibility": "known",
                "summary": "The active replacement bridge.",
                "aliases": ["sealed bridge"],
            },
        )
        conn.commit()

        bound = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "sealed bridge"}),
        )

    assert bound.binding_status == "bound"
    assert bound.options["destination"] == "loc:new-bridge"
    assert bound.entity_bindings == {"destination": "loc:new-bridge"}


@pytest.mark.parametrize("visibility", ["hidden", "gm", "gm-only", "gm_only", "gm only"])
@pytest.mark.parametrize("status", ["active", "retired", "archived"])
def test_player_hidden_exact_match_is_indistinguishable_from_absent(
    temporary_authority: tuple[SaveManager, Path],
    visibility: str,
    status: str,
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:obsidian-vault",
                "type": "location",
                "name": "Obsidian Vault",
                "status": status,
                "visibility": visibility,
                "summary": "Hidden Obsidian Summary",
                "aliases": ["Obsidian Key"],
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:obsidian-vault-annex",
                "type": "location",
                "name": "Obsidian Vault Annex",
                "status": "active",
                "visibility": "known",
                "summary": "A visible partial-match control.",
            },
        )
        conn.commit()

        hidden_result = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "Obsidian Vault"}),
        )
        conn.execute("delete from aliases where entity_id='loc:obsidian-vault'")
        conn.execute("delete from entities where id='loc:obsidian-vault'")
        conn.commit()
        absent_result = bind_intent_candidate(
            conn,
            external_candidate(action="travel", slots={"destination": "Obsidian Vault"}),
        )

    assert hidden_result.to_dict() == absent_result.to_dict()
    assert hidden_result.binding_status == "bound"
    assert hidden_result.options["destination"] == "loc:obsidian-vault-annex"
    assert hidden_result.entity_bindings == {"destination": "loc:obsidian-vault-annex"}


@pytest.mark.parametrize("status", ["active", "retired", "archived"])
def test_player_entity_only_hidden_present_and_absent_are_both_missing_without_visible_candidate(
    temporary_authority: tuple[SaveManager, Path],
    status: str,
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:isolated-hidden-vault",
                "type": "location",
                "name": "Isolated Hidden Vault",
                "status": status,
                "visibility": "gm-only",
                "summary": "An isolated player-hidden control.",
                "aliases": ["Isolated Hidden Key"],
            },
        )
        conn.commit()

        hidden_result = bind_intent_candidate(
            conn,
            external_candidate(
                action="travel",
                slots={"destination": "Isolated Hidden Vault"},
            ),
        )
        conn.execute("delete from aliases where entity_id='loc:isolated-hidden-vault'")
        conn.execute("delete from entities where id='loc:isolated-hidden-vault'")
        conn.commit()
        absent_result = bind_intent_candidate(
            conn,
            external_candidate(
                action="travel",
                slots={"destination": "Isolated Hidden Vault"},
            ),
        )

    assert hidden_result.to_dict() == absent_result.to_dict()
    assert hidden_result.binding_status == "missing"
    assert "destination" not in hidden_result.options
    assert hidden_result.entity_bindings == {}


@pytest.mark.parametrize("view", ["gm", "maintenance"])
@pytest.mark.parametrize("status", ["retired", "archived", "unknown", ""])
def test_privileged_view_binds_hidden_active_but_rejects_hidden_non_active(
    temporary_authority: tuple[SaveManager, Path],
    view: str,
    status: str,
) -> None:
    _, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:privileged-vault",
                "type": "location",
                "name": "Privileged Vault",
                "status": "active",
                "visibility": "gm-only",
                "summary": "A privileged visibility control.",
            },
        )
        conn.commit()
        active = bind_intent_candidate(
            conn,
            external_candidate(
                action="travel",
                slots={"destination": "loc:privileged-vault"},
            ),
            view=view,
        )

        conn.execute(
            "update entities set status=? where id='loc:privileged-vault'",
            (status,),
        )
        conn.commit()
        non_active = bind_intent_candidate(
            conn,
            external_candidate(
                action="travel",
                slots={"destination": "loc:privileged-vault"},
            ),
            view=view,
        )

    assert active.binding_status == "bound"
    assert active.entity_bindings == {"destination": "loc:privileged-vault"}
    assert non_active.binding_status == "missing"
    assert "destination" not in non_active.options
    assert non_active.entity_bindings == {}


def test_player_hidden_world_setting_subtype_matches_absent_while_gm_can_bind(
    temporary_authority: tuple[SaveManager, Path],
    tmp_path: Path,
) -> None:
    hidden_manager, hidden_save = temporary_authority
    hidden_campaign = load_campaign(hidden_save)
    reference = "QZX69SideHiddenWorldAlias"
    with connect(hidden_campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "world:side-hidden-audit",
                "type": "world_setting",
                "name": "Side Hidden World Audit",
                "status": "active",
                "visibility": "known",
                "summary": "Side Hidden World Summary",
                "aliases": [reference],
            },
        )
        conn.execute(
            "insert into world_settings(entity_id, category, visibility) values (?, ?, ?)",
            ("world:side-hidden-audit", "truth", "gm-only"),
        )
        conn.commit()

        player_hidden = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
        )
        gm_visible = bind_intent_candidate(
            conn,
            external_candidate(
                action="routine",
                slots={"task": "inspect", "target": reference},
            ),
            view="gm",
        )

    assert player_hidden.binding_status == "bound"
    assert player_hidden.options["target"] == reference
    assert player_hidden.entity_bindings == {}
    assert gm_visible.binding_status == "bound"
    assert gm_visible.options["target"] == "world:side-hidden-audit"
    assert gm_visible.entity_bindings == {"target": "world:side-hidden-audit"}

    hidden_before = tree_digest(hidden_save)
    hidden_result = hidden_manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )
    assert hidden_result["ok"] is True
    assert hidden_result["ready_to_confirm"] is True
    assert tree_digest(hidden_save) == hidden_before
    hidden_pending = hidden_manager.read_pending_action()
    assert hidden_pending is not None
    assert_pending_has_no_entity_provenance(hidden_pending)
    hidden_text = json.dumps({"result": hidden_result, "pending": hidden_pending}, ensure_ascii=False)
    for canary in (
        "world:side-hidden-audit",
        "Side Hidden World Audit",
        "Side Hidden World Summary",
    ):
        assert canary not in hidden_text

    absent_manager, absent_save = start_temporary_authority(tmp_path / "absent-world-workspace")
    absent_before = tree_digest(absent_save)
    absent_result = absent_manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": reference},
        ),
        intent_ai="off",
    )
    assert absent_result["ok"] is True
    assert absent_result["ready_to_confirm"] is True
    assert tree_digest(absent_save) == absent_before
    absent_pending = absent_manager.read_pending_action()
    assert absent_pending is not None
    assert_pending_has_no_entity_provenance(absent_pending)

    semantic_keys = (
        "ok",
        "status",
        "action",
        "message",
        "ready_to_confirm",
        "saved",
        "warnings",
        "errors",
        "clarification",
    )
    assert {key: hidden_result.get(key) for key in semantic_keys} == {
        key: absent_result.get(key) for key in semantic_keys
    }


def test_public_hidden_non_active_hybrid_match_is_indistinguishable_from_absent(
    temporary_authority: tuple[SaveManager, Path],
    tmp_path: Path,
) -> None:
    hidden_manager, hidden_save = temporary_authority
    hidden_campaign = load_campaign(hidden_save)
    with connect(hidden_campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:hidden-retired-qzx",
                "type": "location",
                "name": "Hidden Retired Qzx",
                "status": "retired",
                "visibility": "gm only",
                "summary": "Hidden Retired Summary Qzx",
                "aliases": ["QZX69OpaqueHiddenAlias"],
            },
        )
        conn.commit()
        report = ProjectionService(hidden_campaign, conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_hidden_retired",
        )
        assert report.ok, report.to_dict()
    hidden_before = tree_digest(hidden_save)

    hidden_result = hidden_manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": "QZX69OpaqueHiddenAlias"},
        ),
        intent_ai="off",
    )
    assert tree_digest(hidden_save) == hidden_before
    hidden_public_text = json.dumps(hidden_result, ensure_ascii=False)
    for canary in (
        "loc:hidden-retired-qzx",
        "Hidden Retired Qzx",
        "Hidden Retired Summary Qzx",
        "QZX69OpaqueHiddenAlias",
    ):
        assert canary not in hidden_public_text
    hidden_pending = hidden_manager.read_pending_action()
    assert hidden_pending is not None
    assert_pending_has_no_entity_provenance(hidden_pending)
    hidden_pending_text = json.dumps(hidden_pending, ensure_ascii=False)
    for canary in (
        "loc:hidden-retired-qzx",
        "Hidden Retired Qzx",
        "Hidden Retired Summary Qzx",
        "QZX69OpaqueHiddenAlias",
    ):
        assert canary not in hidden_pending_text
    assert not hidden_manager.confirmation_receipt_path().exists()

    absent_manager, absent_save = start_temporary_authority(tmp_path / "absent-workspace")
    absent_before = tree_digest(absent_save)
    absent_result = absent_manager.player_turn(
        user_text="检查候选目标",
        external_intent_candidate=external_candidate(
            action="routine",
            slots={"task": "inspect", "target": "QZX69OpaqueHiddenAlias"},
        ),
        intent_ai="off",
    )

    semantic_keys = (
        "ok",
        "status",
        "action",
        "message",
        "ready_to_confirm",
        "saved",
        "warnings",
        "errors",
        "clarification",
    )
    assert {key: hidden_result.get(key) for key in semantic_keys} == {
        key: absent_result.get(key) for key in semantic_keys
    }
    assert hidden_result["ok"] is True
    assert hidden_result["ready_to_confirm"] is True
    assert hidden_result["saved"] is False
    assert absent_result["ready_to_confirm"] is True
    assert tree_digest(absent_save) == absent_before
    absent_pending = absent_manager.read_pending_action()
    assert absent_pending is not None
    assert_pending_has_no_entity_provenance(absent_pending)
    assert absent_pending["turn_proposal"]["intent"]["options"]["target"] == "QZX69OpaqueHiddenAlias"
    assert not absent_manager.confirmation_receipt_path().exists()


def test_foreign_campaign_active_row_cannot_override_current_save_lifecycle(
    temporary_authority: tuple[SaveManager, Path],
    tmp_path: Path,
) -> None:
    manager, save = temporary_authority
    set_entity_status(save, "loc:old-bridge", "retired")

    foreign_workspace = tmp_path / "foreign-workspace"
    foreign_campaign = foreign_workspace / "campaigns" / "adventure"
    foreign_campaign.parent.mkdir(parents=True)
    shutil.copytree(MINIMAL_ADVENTURE, foreign_campaign)
    foreign_manager = SaveManager(foreign_workspace, default_campaign="campaigns/adventure")
    foreign_started = foreign_manager.start_or_continue(campaign="campaigns/adventure")
    assert foreign_started["ok"] is True
    foreign_save = foreign_workspace / str(foreign_started["save"]["path"])
    with connect(load_campaign(foreign_save)) as conn:
        foreign_status = conn.execute("select status from entities where id='loc:old-bridge'").fetchone()
        assert foreign_status is not None
        assert str(foreign_status["status"]) == "active"

    current_before = tree_digest(save)
    foreign_before = tree_digest(foreign_save)
    confirmation_before = confirmation_state_snapshot(manager)
    result = manager.player_turn(
        user_text="前往另一个 Campaign 的候选地点",
        external_intent_candidate=external_candidate(
            action="travel",
            slots={"destination": "loc:old-bridge"},
        ),
        intent_ai="off",
    )

    assert result["ok"] is False
    assert result["ready_to_confirm"] is False
    assert result["saved"] is False
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert confirmation_state_snapshot(manager) == confirmation_before
    assert tree_digest(save) == current_before
    assert tree_digest(foreign_save) == foreign_before


def test_hidden_missing_ambiguous_foreign_and_stale_contract_behaviors_remain_closed(
    temporary_authority: tuple[SaveManager, Path],
) -> None:
    manager, save = temporary_authority
    with connect(load_campaign(save)) as conn:
        upsert_entity(
            conn,
            {
                "id": "loc:hidden-qzx",
                "type": "location",
                "name": "Hidden Obsidian Qzx",
                "status": "active",
                "visibility": "hidden",
                "summary": "Hidden Summary Qzx",
                "aliases": ["Hidden Alias Qzx"],
            },
        )
        upsert_entity(
            conn,
            {
                "id": "loc:bridge-copy",
                "type": "location",
                "name": "Bridge Copy",
                "status": "active",
                "visibility": "known",
                "summary": "Ambiguity control.",
                "aliases": ["bridge"],
            },
        )
        conn.commit()
        report = ProjectionService(load_campaign(save), conn).refresh(
            names=["search", "snapshots", "cards"],
            dirty_only=False,
            profile="test:story_6_9_hidden",
        )
        assert report.ok, report.to_dict()
    before = tree_digest(save)

    for reference in ("loc:hidden-qzx", "loc:foreign-only", "loc:missing"):
        result = manager.player_turn(
            user_text="前往候选地点",
            external_intent_candidate=external_candidate(
                action="travel",
                slots={"destination": reference},
            ),
            intent_ai="off",
        )
        assert result["ok"] is False
        assert result["ready_to_confirm"] is False
        assert result["saved"] is False
        assert not manager.pending_action_path().exists()
        public_text = json.dumps(result, ensure_ascii=False)
        for canary in ("Hidden Obsidian Qzx", "Hidden Alias Qzx", "Hidden Summary Qzx"):
            assert canary not in public_text

    ambiguous = manager.player_turn(
        user_text="前往桥边",
        external_intent_candidate=external_candidate(
            action="travel",
            slots={"destination": "bridge"},
        ),
        intent_ai="off",
    )
    assert ambiguous["ok"] is False
    assert ambiguous["ready_to_confirm"] is False
    assert not manager.pending_action_path().exists()

    with pytest.raises(ExternalIntentContractError) as exc_info:
        manager.player_turn(
            user_text="前往旧桥",
            external_intent_candidate=external_candidate(
                action="travel",
                slots={"destination": "loc:old-bridge"},
                stale_contract=True,
            ),
            intent_ai="off",
        )
    assert exc_info.value.code == "INTENT_CONTRACT_VERSION_MISMATCH"
    assert not manager.pending_action_path().exists()
    assert not manager.confirmation_receipt_path().exists()
    assert tree_digest(save) == before
