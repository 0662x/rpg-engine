from __future__ import annotations

import sqlite3
import hashlib
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import rpg_engine.ai.advisory_review as advisory_review_module
from rpg_engine.ai.advisory import normalize_resident_ai_advisory
from rpg_engine.ai.advisory_review import (
    ADVISORY_REVIEW_SCHEMA_VERSION,
    AdvisoryReviewArtifact,
    build_advisory_review_artifact,
    advisory_review_to_maintenance_dict,
    advisory_review_to_player_dict,
)
from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, upsert_clock, upsert_entity

from tests.helpers import (
    CURRENT_SAVE_ROOT,
    copy_current_packages,
    copy_initialized_minimal,
    normalize_current_native_story_fixture,
)


PRIVATE_CANARY = "RAW_PRIVATE_REASONING_PROVIDER_PROMPT_CANARY"


def advisory(
    *target_ids: str,
    advisory_type: str = "entity_maintenance",
    visibility_mode: str = "maintenance",
    freshness_status: str = "current",
    source_event_ids: tuple[str, ...] = (),
    as_of_turn_id: int | None = 0,
):
    first = target_ids[0] if target_ids else ""
    evidence_kind = "progress" if first.startswith("clock:") else "relationship" if first.startswith("rel:") else "entity"
    return normalize_resident_ai_advisory(
        {
            "advisory_type": advisory_type,
            "target_ids": list(target_ids),
            "evidence": [
                {
                    "kind": evidence_kind,
                    "ref_id": target_ids[0],
                    "as_of_turn_id": as_of_turn_id,
                }
            ]
            if target_ids
            else [],
            "confidence": 0.5,
            "freshness": {
                "status": freshness_status,
                "as_of_turn_id": as_of_turn_id,
                "source_event_ids": list(source_event_ids),
            },
            "visibility_mode": visibility_mode,
            "source_assistant": "entity_maintenance",
            "schema_version": "resident_ai_advisory:v1",
            "proposed_next_workflow": advisory_type,
            "provenance": {"trace_id": "trace:review-test", "source_ids": []},
            "authority": {
                "advisory_only": True,
                "no_direct_writes": True,
                "can_write_facts": False,
                "can_approve_proposals": False,
                "can_confirm_players": False,
                "can_read_hidden": False,
                "can_inject_trusted_delta": False,
                "can_authorize_save": False,
                "can_escalate_profile": False,
                "can_bypass_validation": False,
                "can_commit": False,
            },
        }
    )


def entity_candidate(entity_id: str, *, name: str = "Review Target") -> dict[str, object]:
    return {
        "upsert_entities": [
            {
                "id": entity_id,
                "type": "character",
                "name": name,
                "status": "active",
                "visibility": "known",
                "location_id": None,
                "owner_id": None,
                "summary": "Bounded review candidate.",
                "details": {},
            }
        ]
    }


def relationship_candidate(relationship_id: str) -> dict[str, object]:
    return {
        "upsert_entities": [
            {
                "id": relationship_id,
                "type": "relationship",
                "name": "Traveler knows guide",
                "status": "active",
                "visibility": "known",
                "summary": "A reviewable relationship.",
                "details": {
                    "source_id": "pc:traveler",
                    "target_id": "npc:guide",
                    "kind": "knows",
                },
            }
        ]
    }


class ResidentAIAdvisoryReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.campaign_root = copy_initialized_minimal(self.tmp.name)
        self.campaign = load_campaign(self.campaign_root)
        self.conn = connect(self.campaign)
        upsert_entity(
            self.conn,
            {
                "id": "npc:guide",
                "type": "character",
                "name": "Guide",
                "status": "active",
                "visibility": "known",
                "summary": "A visible guide.",
                "updated_turn_id": "turn:seed",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "npc:hidden-guide",
                "type": "character",
                "name": PRIVATE_CANARY,
                "status": "active",
                "visibility": "hidden",
                "summary": PRIVATE_CANARY,
                "updated_turn_id": "turn:seed",
            },
        )
        upsert_clock(
            self.conn,
            {
                "id": "clock:quest:phase-1",
                "name": "Quest progress",
                "segments_total": 6,
                "segments_filled": 1,
                "visibility": "visible",
            },
        )
        upsert_clock(
            self.conn,
            {
                "id": "clock:hidden",
                "name": PRIVATE_CANARY,
                "segments_total": 4,
                "segments_filled": 1,
                "visibility": "hidden",
            },
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def build(
        self,
        *,
        source,
        family: str,
        operation: str,
        candidate: dict[str, object],
        disposition: str = "reviewable",
        base_turn_id: str = "turn:seed",
        supersedes: tuple[str, ...] = (),
        rollback_hint: dict[str, object] | None = None,
    ) -> AdvisoryReviewArtifact:
        return build_advisory_review_artifact(
            self.conn,
            advisory=source,
            suggestion_family=family,
            suggestion_operation=operation,
            candidate=candidate,
            disposition=disposition,
            base_turn_id=base_turn_id,
            supersedes=supersedes,
            rollback_hint=rollback_hint or {},
        )

    def test_entity_create_and_update_have_distinct_existence_contracts(self) -> None:
        created = self.build(
            source=advisory("npc:new-guide"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
        )
        self.assertEqual(created.schema_version, ADVISORY_REVIEW_SCHEMA_VERSION)
        self.assertEqual(created.disposition, "reviewable")
        self.assertEqual(created.required_gate, "validate_content_delta")
        self.assertEqual(created.next_owner, "content_maintenance")
        self.assertTrue(created.application_eligible)
        self.assertFalse(created.authority.current_fact_authority)
        self.assertFalse(created.authority.application_authorized)
        self.assertFalse(created.authority.proposal_approval_is_commit)

        existing_create = self.build(
            source=advisory("npc:guide"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:guide"),
        )
        self.assertEqual(existing_create.disposition, "conflict")
        self.assertFalse(existing_create.application_eligible)

        updated = self.build(
            source=advisory("npc:guide"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide", name="Updated Guide"),
        )
        self.assertTrue(updated.application_eligible)

        missing_update = self.build(
            source=advisory("npc:missing"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:missing"),
        )
        self.assertEqual(missing_update.disposition, "stale")
        self.assertFalse(missing_update.application_eligible)

    def test_entity_namespaces_match_canonical_card_registry_prefixes(self) -> None:
        cases = (
            ("char:new-helper", "character", None),
            ("creature:new-species", "species", None),
            (
                "plot:new",
                "crop_plot",
                {
                    "plot_no": 99,
                    "crop_entity_id": "npc:guide",
                },
            ),
        )
        for entity_id, entity_type, crop_plot in cases:
            candidate = entity_candidate(entity_id)
            candidate["upsert_entities"][0]["type"] = entity_type  # type: ignore[index]
            if crop_plot is not None:
                candidate["upsert_entities"][0]["crop_plot"] = crop_plot  # type: ignore[index]
            with self.subTest(entity_id=entity_id):
                artifact = self.build(
                    source=advisory(entity_id),
                    family="entity",
                    operation="create",
                    candidate=candidate,
                )
                self.assertEqual(artifact.disposition, "reviewable")
                self.assertTrue(artifact.application_eligible)
        equipment = entity_candidate("item:new-shield")
        equipment["upsert_entities"][0]["type"] = "equipment"  # type: ignore[index]
        equipment["upsert_entities"][0]["item"] = {"category": "shield"}  # type: ignore[index]
        equipment_artifact = self.build(
            source=advisory("item:new-shield"),
            family="entity",
            operation="create",
            candidate=equipment,
        )
        self.assertTrue(equipment_artifact.application_eligible)
        wrong_equipment = entity_candidate("equipment:new-shield")
        wrong_equipment["upsert_entities"][0]["type"] = "equipment"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("equipment:new-shield"),
                family="entity",
                operation="create",
                candidate=wrong_equipment,
            )

    def test_player_scoped_content_candidate_cannot_introduce_hidden_visibility(self) -> None:
        cases = (
            ("entity", "create", entity_candidate("npc:hidden-create")),
            ("entity", "update", entity_candidate("npc:guide")),
            (
                "relationship",
                "create",
                relationship_candidate("rel:hidden-create"),
            ),
        )
        for family, operation, candidate in cases:
            candidate["upsert_entities"][0]["visibility"] = "hidden"  # type: ignore[index]
            target_id = candidate["upsert_entities"][0]["id"]  # type: ignore[index]
            with self.subTest(family=family, operation=operation):
                artifact = self.build(
                    source=advisory(target_id, visibility_mode="player"),
                    family=family,
                    operation=operation,
                    candidate=candidate,
                )
                self.assertEqual(artifact.disposition, "conflict")
                self.assertFalse(artifact.application_eligible)

        for view in ("player", "maintenance"):
            for family, candidate in (
                ("entity", entity_candidate("npc:missing-visibility")),
                (
                    "relationship",
                    relationship_candidate("rel:missing-visibility"),
                ),
            ):
                candidate["upsert_entities"][0].pop("visibility")  # type: ignore[index]
                target_id = candidate["upsert_entities"][0]["id"]  # type: ignore[index]
                with self.subTest(view=view, family=family):
                    with self.assertRaisesRegex(
                        ValueError, "invalid advisory review input"
                    ):
                        self.build(
                            source=advisory(target_id, visibility_mode=view),
                            family=family,
                            operation="create",
                            candidate=candidate,
                        )

    def test_relationship_create_requires_absent_id_and_visible_live_endpoints(self) -> None:
        artifact = self.build(
            source=advisory("rel:traveler-guide"),
            family="relationship",
            operation="create",
            candidate=relationship_candidate("rel:traveler-guide"),
        )
        self.assertEqual(artifact.required_gate, "validate_content_delta")
        self.assertTrue(artifact.application_eligible)

        class StringSubclass(str):
            pass

        for invalid_kind in (None, "", StringSubclass("knows")):
            missing_kind = relationship_candidate("rel:missing-kind")
            if invalid_kind is None:
                missing_kind["upsert_entities"][0]["details"].pop("kind")  # type: ignore[index]
            else:
                missing_kind["upsert_entities"][0]["details"]["kind"] = invalid_kind  # type: ignore[index]
            with self.subTest(invalid_kind=invalid_kind):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory("rel:missing-kind"),
                        family="relationship",
                        operation="create",
                        candidate=missing_kind,
                    )

        hidden = relationship_candidate("rel:traveler-hidden")
        hidden["upsert_entities"][0]["details"]["target_id"] = "npc:hidden-guide"  # type: ignore[index]
        hidden_artifact = self.build(
            source=advisory("rel:traveler-hidden", visibility_mode="player"),
            family="relationship",
            operation="create",
            candidate=hidden,
        )
        self.assertEqual(hidden_artifact.disposition, "conflict")
        self.assertFalse(hidden_artifact.application_eligible)

        incompatible = relationship_candidate("rel:incompatible")
        incompatible["upsert_entities"][0]["character"] = {}  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("rel:incompatible"),
                family="relationship",
                operation="create",
                candidate=incompatible,
            )
        unsafe_details = relationship_candidate("rel:unsafe-details")
        unsafe_details["upsert_entities"][0]["details"]["notes"] = "safe\x1b[31mFORGED"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("rel:unsafe-details"),
                family="relationship",
                operation="create",
                candidate=unsafe_details,
            )
        wrong_namespace = relationship_candidate("npc:not-a-relationship-id")
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:not-a-relationship-id"),
                family="relationship",
                operation="create",
                candidate=wrong_namespace,
            )

    def test_alias_memory_and_progress_review_never_guess_application_owner(self) -> None:
        cases = [
            ("alias", "review", {"target_id": "npc:guide", "alias": "Pathfinder"}),
            (
                "memory_summary",
                "review",
                {"target_id": "npc:guide", "summary": "Derived summary.", "source_event_ids": []},
            ),
            (
                "progress_definition",
                "create",
                {"target_id": "clock:new", "segments_total": 6, "summary": "Draft progress."},
            ),
        ]
        for family, operation, candidate in cases:
            with self.subTest(family=family):
                artifact = self.build(
                    source=advisory(
                        str(candidate["target_id"]),
                        advisory_type=(
                            "progress_management"
                            if family == "progress_definition"
                            else "entity_maintenance"
                        ),
                    ),
                    family=family,
                    operation=operation,
                    candidate=candidate,
                )
                self.assertFalse(artifact.application_eligible)
                self.assertEqual(artifact.next_owner, "none")
                self.assertEqual(artifact.required_gate, "manual_review_only")

    def test_clock_tick_uses_progress_reference_preflight_without_applying(self) -> None:
        before = self.conn.execute(
            "select segments_filled from clocks where entity_id='clock:quest:phase-1'"
        ).fetchone()[0]
        artifact = self.build(
            source=advisory("clock:quest:phase-1", advisory_type="progress_management"),
            family="clock_tick",
            operation="tick",
            candidate={"tick_clocks": [{"id": "clock:quest:phase-1", "delta": 1, "reason": "Milestone"}]},
        )
        self.assertEqual(artifact.required_gate, "validate_delta_progress_references")
        self.assertEqual(artifact.next_owner, "confirmed_turn_or_maintenance_validation")
        self.assertTrue(artifact.application_eligible)
        after = self.conn.execute(
            "select segments_filled from clocks where entity_id='clock:quest:phase-1'"
        ).fetchone()[0]
        self.assertEqual(after, before)

    def test_non_current_dispositions_are_never_application_eligible(self) -> None:
        for disposition in ("rejected", "stale", "superseded", "conflict"):
            with self.subTest(disposition=disposition):
                artifact = self.build(
                    source=advisory("npc:new-guide"),
                    family="entity",
                    operation="create",
                    candidate=entity_candidate("npc:new-guide"),
                    disposition=disposition,
                    supersedes=("advisory:older",),
                    rollback_hint={"strategy": "discard_draft"},
                )
                self.assertEqual(artifact.disposition, disposition)
                self.assertFalse(artifact.application_eligible)
                maintenance = advisory_review_to_maintenance_dict(artifact)
                self.assertEqual(maintenance["supersedes"], ["advisory:older"])
                self.assertEqual(maintenance["rollback_hint"], {"strategy": "discard_draft"})
                self.assertFalse(maintenance["authority"]["current_fact_authority"])

        automatic = self.build(
            source=advisory("npc:new-guide"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
            disposition="conflict",
        )
        automatic_wire = advisory_review_to_maintenance_dict(automatic)
        self.assertEqual(automatic_wire["rollback_hint"], {"strategy": "revalidate"})

    def test_artifact_is_deeply_immutable_and_serialization_is_defensive(self) -> None:
        candidate = entity_candidate("npc:new-guide")
        artifact = self.build(
            source=advisory("npc:new-guide"),
            family="entity",
            operation="create",
            candidate=candidate,
        )
        first = advisory_review_to_maintenance_dict(artifact)
        candidate["upsert_entities"][0]["name"] = PRIVATE_CANARY  # type: ignore[index]
        first["validation"]["errors"].append(PRIVATE_CANARY)
        second = advisory_review_to_maintenance_dict(artifact)
        self.assertNotIn(PRIVATE_CANARY, str(second))
        self.assertIsNot(first, second)
        self.assertIsInstance(artifact.candidate, tuple)

    def test_envelope_without_candidate_and_authority_smuggling_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            build_advisory_review_artifact(
                self.conn,
                advisory=advisory("npc:new-guide"),
                suggestion_family="entity",
                suggestion_operation="create",
                candidate=None,  # type: ignore[arg-type]
            )
        hostile = entity_candidate("npc:new-guide")
        hostile["can_commit"] = True
        hostile["private_reasoning"] = PRIVATE_CANARY
        with self.assertRaisesRegex(ValueError, "invalid advisory review input") as caught:
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=hostile,
            )
        self.assertNotIn(PRIVATE_CANARY, str(caught.exception))

    def test_unknown_tokens_and_non_exact_containers_fail_closed(self) -> None:
        class DictSubclass(dict):
            pass

        for family, operation, disposition, candidate in [
            ("entities", "create", "reviewable", entity_candidate("npc:new")),
            ("entity", "CREATE", "reviewable", entity_candidate("npc:new")),
            ("entity", "create", "approved", entity_candidate("npc:new")),
            ("entity", "create", "reviewable", DictSubclass(entity_candidate("npc:new"))),
        ]:
            with self.subTest(family=family, operation=operation, disposition=disposition):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory("npc:new"),
                        family=family,
                        operation=operation,
                        candidate=candidate,
                        disposition=disposition,
                    )

    def test_player_projection_omits_hidden_targets_with_generic_result(self) -> None:
        artifact = self.build(
            source=advisory("clock:hidden", advisory_type="progress_management", visibility_mode="player"),
            family="clock_tick",
            operation="tick",
            candidate={"tick_clocks": [{"id": "clock:hidden", "delta": 1, "reason": "Secret"}]},
        )
        player = advisory_review_to_player_dict(self.conn, artifact)
        self.assertEqual(player, {"available": False, "reason": "advisory review unavailable"})
        self.assertNotIn(PRIVATE_CANARY, str(player))

    def test_player_projection_reuses_advisory_access_contract_and_rejects_forgery(self) -> None:
        artifact = self.build(
            source=advisory("npc:guide", visibility_mode="player"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide", name="Guide"),
        )
        player = advisory_review_to_player_dict(self.conn, artifact)
        self.assertTrue(player["available"])
        self.assertEqual(player["target_ids"], ["npc:guide"])
        self.assertNotIn("candidate", player)
        forged = replace(artifact, application_eligible=False)
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, forged),
            {"available": False, "reason": "advisory review unavailable"},
        )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            advisory_review_to_maintenance_dict(forged)

    def test_fact_reads_fail_closed_on_temp_shadow(self) -> None:
        self.conn.execute("create temp table entities(id text)")
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
            )

    def test_delegated_content_validator_temp_shadow_and_messages_fail_closed(self) -> None:
        self.conn.execute("create temp table items(entity_id text)")
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
            )
        self.conn.execute("drop table temp.items")

        validation = SimpleNamespace(errors=[PRIVATE_CANARY], warnings=[PRIVATE_CANARY])
        with mock.patch.object(advisory_review_module, "validate_content_delta", return_value=validation):
            artifact = self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
            )
        wire = advisory_review_to_maintenance_dict(artifact)
        self.assertNotIn(PRIVATE_CANARY, str(wire))
        self.assertEqual(wire["validation"]["errors"], ["content_validation_failed"])
        self.assertEqual(wire["validation"]["warnings"], ["content_validation_warning"])

    def test_hidden_or_archived_create_ids_conflict_without_player_oracle(self) -> None:
        hidden = self.build(
            source=advisory("npc:hidden-guide", visibility_mode="player"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:hidden-guide"),
        )
        self.assertEqual(hidden.disposition, "conflict")
        self.assertFalse(hidden.application_eligible)
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, hidden),
            {"available": False, "reason": "advisory review unavailable"},
        )

        upsert_entity(
            self.conn,
            {
                "id": "npc:archived",
                "type": "character",
                "name": "Archived",
                "status": "archived",
                "visibility": "known",
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.commit()
        archived = self.build(
            source=advisory("npc:archived"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:archived"),
        )
        self.assertEqual(archived.disposition, "conflict")

    def test_create_identity_collision_is_global_across_entity_subtypes(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "rel:collision",
                "type": "character",
                "name": "Wrong relationship subtype",
                "status": "active",
                "visibility": "known",
                "summary": "Occupies a relationship ID.",
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.commit()
        relationship = relationship_candidate("rel:collision")
        collision = self.build(
            source=advisory("rel:collision"),
            family="relationship",
            operation="create",
            candidate=relationship,
        )
        self.assertEqual(collision.disposition, "conflict")
        upsert_entity(
            self.conn,
            {
                "id": "clock:collision",
                "type": "character",
                "name": "Wrong subtype",
                "status": "active",
                "visibility": "known",
                "summary": "Occupies a clock namespace ID.",
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.commit()
        progress = self.build(
            source=advisory("clock:collision", advisory_type="progress_management"),
            family="progress_definition",
            operation="create",
            candidate={
                "target_id": "clock:collision",
                "segments_total": 4,
                "summary": "Draft.",
            },
        )
        self.assertEqual(progress.disposition, "conflict")

    def test_entity_family_rejects_clock_and_type_changing_update(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("clock:new"),
                family="entity",
                operation="create",
                candidate={
                    "upsert_entities": [
                        {
                            "id": "clock:new",
                            "type": "clock",
                            "name": "Clock bypass",
                            "status": "active",
                            "visibility": "known",
                            "summary": "No subtype owner.",
                        }
                    ]
                },
            )
        for reserved_id in (
            "clock:reserved",
            "rel:reserved",
            "rule:reserved",
            "world:reserved",
            "setting:reserved",
            "route:reserved",
            "fact:reserved",
            "table:reserved",
            "pal:reserved",
            "summary:reserved",
            "migration:reserved",
        ):
            with self.subTest(reserved_id=reserved_id):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory(reserved_id),
                        family="entity",
                        operation="create",
                        candidate=entity_candidate(reserved_id),
                    )
        for dedicated_type in ("rule", "world_setting"):
            candidate = entity_candidate(f"npc:fake-{dedicated_type}")
            candidate["upsert_entities"][0]["type"] = dedicated_type  # type: ignore[index]
            with self.subTest(dedicated_type=dedicated_type):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory(f"npc:fake-{dedicated_type}"),
                        family="entity",
                        operation="create",
                        candidate=candidate,
                    )
        changed_type = entity_candidate("npc:guide")
        changed_type["upsert_entities"][0]["type"] = "location"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:guide"),
                family="entity",
                operation="update",
                candidate=changed_type,
            )

    def test_player_entity_references_must_be_visible(self) -> None:
        candidate = entity_candidate("pc:traveler")
        candidate["upsert_entities"][0]["owner_id"] = "npc:hidden-guide"  # type: ignore[index]
        artifact = self.build(
            source=advisory("pc:traveler", visibility_mode="player"),
            family="entity",
            operation="update",
            candidate=candidate,
        )
        self.assertEqual(artifact.disposition, "conflict")
        self.assertFalse(artifact.application_eligible)

    def test_location_discovered_turn_must_exist_and_not_exceed_base(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "loc:known",
                "type": "location",
                "name": "Known location",
                "status": "active",
                "visibility": "known",
                "summary": "Existing.",
                "details": {},
                "updated_turn_id": "turn:seed",
                "location": {
                    "parent_id": None,
                    "coord_x": 0,
                    "coord_y": 0,
                    "coord_z": 0,
                    "biome": "plain",
                    "safety_level": "safe",
                    "discovered_turn_id": "turn:seed",
                    "travel_minutes_from_home": 0,
                    "description_short": "Known.",
                    "exits": [],
                    "resources": [],
                },
            },
        )
        self.conn.commit()
        candidate = entity_candidate("loc:known", name="Known location")
        candidate_entity = candidate["upsert_entities"][0]  # type: ignore[index]
        candidate_entity["type"] = "location"
        candidate_entity["summary"] = "Existing."
        candidate_entity["location"] = {
            "parent_id": None,
            "coord_x": 0,
            "coord_y": 0,
            "coord_z": 0,
            "biome": "plain",
            "safety_level": "safe",
            "discovered_turn_id": "turn:999999",
            "travel_minutes_from_home": 0,
            "description_short": "Known.",
            "exits": [],
            "resources": [],
        }
        artifact = self.build(
            source=advisory("loc:known"),
            family="entity",
            operation="update",
            candidate=candidate,
        )
        self.assertEqual(artifact.disposition, "stale")
        create_candidate = entity_candidate("loc:new", name="New location")
        create_entity = create_candidate["upsert_entities"][0]  # type: ignore[index]
        create_entity["type"] = "location"
        create_entity["location"] = dict(candidate_entity["location"])
        unknown_source = advisory(
            "loc:new", freshness_status="unknown", as_of_turn_id=None
        )
        created = build_advisory_review_artifact(
            self.conn,
            advisory=unknown_source,
            suggestion_family="entity",
            suggestion_operation="create",
            candidate=create_candidate,
            base_turn_id=None,
        )
        self.assertEqual(created.disposition, "stale")
        self.assertIn(
            "target_stale",
            advisory_review_to_maintenance_dict(created)["validation"]["errors"],
        )
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, artifact),
            {"available": False, "reason": "advisory review unavailable"},
        )

    def test_current_operations_require_existing_canonical_base_turn(self) -> None:
        derived = build_advisory_review_artifact(
            self.conn,
            advisory=advisory("npc:guide"),
            suggestion_family="entity",
            suggestion_operation="update",
            candidate=entity_candidate("npc:guide"),
            base_turn_id=None,
        )
        self.assertEqual(derived.base_turn_id, "turn:seed")
        for base_turn_id in ("", "turn:missing", "event:seed"):
            with self.subTest(base_turn_id=base_turn_id):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    build_advisory_review_artifact(
                        self.conn,
                        advisory=advisory("npc:guide"),
                        suggestion_family="entity",
                        suggestion_operation="update",
                        candidate=entity_candidate("npc:guide"),
                        base_turn_id=base_turn_id,
                    )

    def test_relationship_update_rejects_endpoint_changed_after_base(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "rel:traveler-guide",
                "type": "relationship",
                "name": "Knows",
                "status": "active",
                "visibility": "known",
                "summary": "Existing relationship.",
                "details": {
                    "source_id": "pc:traveler",
                    "target_id": "npc:guide",
                    "kind": "knows",
                },
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.execute(
            """
            insert into main.turns
              (id, user_text, intent, changed, created_at)
            values ('turn:after-review-base', 'test', 'test', 0, '9999-01-01T00:00:00+00:00')
            """
        )
        self.conn.execute(
            "update main.entities set updated_turn_id='turn:after-review-base' where id='npc:guide'"
        )
        self.conn.commit()
        artifact = self.build(
            source=advisory("rel:traveler-guide"),
            family="relationship",
            operation="update",
            candidate=relationship_candidate("rel:traveler-guide"),
        )
        self.assertEqual(artifact.disposition, "stale")
        self.assertIn("endpoint_stale", advisory_review_to_maintenance_dict(artifact)["validation"]["errors"])

    def test_relationship_update_preserves_current_details_shape(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "rel:with-notes",
                "type": "relationship",
                "name": "Noted bond",
                "status": "active",
                "visibility": "known",
                "summary": "Existing relationship.",
                "details": {
                    "source_id": "pc:traveler",
                    "target_id": "npc:guide",
                    "kind": "knows",
                    "notes": "Preserve me",
                },
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.commit()
        omitted = self.build(
            source=advisory("rel:with-notes"),
            family="relationship",
            operation="update",
            candidate=relationship_candidate("rel:with-notes"),
        )
        self.assertEqual(omitted.disposition, "conflict")
        preserved_candidate = relationship_candidate("rel:with-notes")
        preserved_candidate["upsert_entities"][0]["details"]["notes"] = "Updated safely"  # type: ignore[index]
        preserved = self.build(
            source=advisory("rel:with-notes"),
            family="relationship",
            operation="update",
            candidate=preserved_candidate,
        )
        self.assertEqual(preserved.disposition, "reviewable")
        upsert_entity(
            self.conn,
            {
                "id": "npc:other",
                "type": "character",
                "name": "Other",
                "status": "active",
                "visibility": "known",
                "summary": "Another endpoint.",
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.commit()
        redirected_candidate = relationship_candidate("rel:with-notes")
        redirected_candidate["upsert_entities"][0]["details"].update(  # type: ignore[index]
            {"target_id": "npc:other", "notes": "Preserve me"}
        )
        redirected = self.build(
            source=advisory("rel:with-notes"),
            family="relationship",
            operation="update",
            candidate=redirected_candidate,
        )
        self.assertEqual(redirected.disposition, "conflict")
        incomplete = relationship_candidate("rel:with-notes")
        incomplete["upsert_entities"][0].pop("visibility")  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("rel:with-notes"),
                family="relationship",
                operation="update",
                candidate=incomplete,
            )

    def test_entity_update_requires_complete_replacement_subtype_shape(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "item:tool",
                "type": "item",
                "name": "Tool",
                "status": "active",
                "visibility": "known",
                "summary": "Existing item.",
                "details": {},
                "updated_turn_id": "turn:seed",
                "item": {
                    "category": "tool",
                    "quantity": 1,
                    "unit": "piece",
                    "quality": "normal",
                    "durability_current": 3,
                    "durability_max": 5,
                    "stackable": False,
                    "equipped_slot": None,
                    "properties": {},
                },
            },
        )
        self.conn.commit()
        partial = entity_candidate("item:tool", name="Tool")
        partial["upsert_entities"][0]["type"] = "item"  # type: ignore[index]
        partial["upsert_entities"][0]["summary"] = "Existing item."  # type: ignore[index]
        partial["upsert_entities"][0]["item"] = {"durability_current": 2}  # type: ignore[index]
        artifact = self.build(
            source=advisory("item:tool"),
            family="entity",
            operation="update",
            candidate=partial,
        )
        self.assertEqual(artifact.disposition, "conflict")
        self.assertFalse(artifact.application_eligible)

        mixed = entity_candidate("item:tool", name="Tool")
        mixed_entity = mixed["upsert_entities"][0]  # type: ignore[index]
        mixed_entity["type"] = "item"
        mixed_entity["summary"] = "Existing item."
        mixed_entity["item"] = {
            "category": "tool",
            "quantity": 1,
            "unit": "piece",
            "quality": "normal",
            "durability_current": 2,
            "durability_max": 5,
            "stackable": False,
            "equipped_slot": None,
            "properties": {},
        }
        mixed_entity["character"] = {
            "species_id": None,
            "role": None,
            "attitude": None,
            "trust": 0,
            "health_state": None,
            "stress": {},
            "consequences": [],
            "goals": [],
            "knowledge": {},
        }
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("item:tool"),
                family="entity",
                operation="update",
                candidate=mixed,
            )

    def test_entity_candidate_references_reject_primary_target_self_reference(self) -> None:
        created = entity_candidate("loc:self")
        created_entity = created["upsert_entities"][0]  # type: ignore[index]
        created_entity["type"] = "location"
        created_entity["location"] = {"parent_id": "loc:self"}
        create_artifact = self.build(
            source=advisory("loc:self"),
            family="entity",
            operation="create",
            candidate=created,
        )
        self.assertEqual(create_artifact.disposition, "conflict")
        self.assertFalse(create_artifact.application_eligible)

        updated = entity_candidate("npc:guide")
        updated["upsert_entities"][0]["owner_id"] = "npc:guide"  # type: ignore[index]
        update_artifact = self.build(
            source=advisory("npc:guide"),
            family="entity",
            operation="update",
            candidate=updated,
        )
        self.assertEqual(update_artifact.disposition, "conflict")
        self.assertFalse(update_artifact.application_eligible)

    def test_memory_sources_are_bound_existing_and_not_newer_than_base(self) -> None:
        missing = self.build(
            source=advisory("npc:guide", source_event_ids=("event:missing",)),
            family="memory_summary",
            operation="review",
            candidate={
                "target_id": "npc:guide",
                "summary": "Derived summary.",
                "source_event_ids": ["event:missing"],
            },
        )
        self.assertEqual(missing.disposition, "stale")
        self.assertFalse(missing.validation == ())

        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:guide", source_event_ids=("event:seed",)),
                family="memory_summary",
                operation="review",
                candidate={
                    "target_id": "npc:guide",
                    "summary": "Derived summary.",
                    "source_event_ids": ["event:different"],
                },
            )

    def test_player_memory_and_general_source_events_reject_hidden_or_missing_evidence(self) -> None:
        self.conn.execute(
            """
            insert into main.events
              (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
            values (?, 'turn:seed', 'day 1', 'test', 'Hidden', 'Hidden', ?, 'test',
                    '2000-01-01T00:00:00+00:00')
            """,
            ("event:hidden-source", json.dumps({"entity_id": "npc:hidden-guide"})),
        )
        self.conn.commit()
        memory = self.build(
            source=advisory(
                "npc:guide",
                visibility_mode="player",
                source_event_ids=("event:hidden-source",),
            ),
            family="memory_summary",
            operation="review",
            candidate={
                "target_id": "npc:guide",
                "summary": "Derived.",
                "source_event_ids": ["event:hidden-source"],
            },
        )
        self.assertEqual(memory.disposition, "stale")
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, memory),
            {"available": False, "reason": "advisory review unavailable"},
        )
        entity = self.build(
            source=advisory("npc:new-guide", source_event_ids=("event:missing",)),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
        )
        self.assertEqual(entity.disposition, "stale")
        self.assertFalse(entity.application_eligible)

    def test_progress_review_checks_target_visibility_and_currentness(self) -> None:
        missing = self.build(
            source=advisory("clock:missing", advisory_type="progress_management"),
            family="progress_definition",
            operation="review",
            candidate={"target_id": "clock:missing", "segments_total": 4, "summary": "Review."},
        )
        self.assertEqual(missing.disposition, "stale")
        hidden = self.build(
            source=advisory(
                "clock:hidden", advisory_type="progress_management", visibility_mode="player"
            ),
            family="progress_definition",
            operation="review",
            candidate={"target_id": "clock:hidden", "segments_total": 4, "summary": "Review."},
        )
        self.assertEqual(hidden.disposition, "stale")

    def test_stale_source_and_mixed_targets_fail_closed(self) -> None:
        stale = self.build(
            source=advisory("npc:new-guide", freshness_status="stale"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
        )
        self.assertEqual(stale.disposition, "stale")
        self.assertFalse(stale.application_eligible)
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("pc:traveler", "npc:hidden-guide", visibility_mode="player"),
                family="entity",
                operation="update",
                candidate=entity_candidate("pc:traveler"),
            )

    def test_rollback_and_candidate_control_fields_use_exact_safe_vocabularies(self) -> None:
        for rollback_hint in (
            {"approval": True},
            {"strategy": "discard_draft", "private_reasoning": PRIVATE_CANARY},
            {"strategy": "unknown"},
        ):
            with self.subTest(rollback_hint=rollback_hint):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input") as caught:
                    self.build(
                        source=advisory("npc:new-guide"),
                        family="entity",
                        operation="create",
                        candidate=entity_candidate("npc:new-guide"),
                        rollback_hint=rollback_hint,
                    )
                self.assertNotIn(PRIVATE_CANARY, str(caught.exception))

        legitimate = entity_candidate("npc:new-guide")
        legitimate["upsert_entities"][0]["details"] = {  # type: ignore[index]
            "approval_rating": 4,
            "profile": {"role": "guide"},
            "session_key_item": "story prop",
            "preflight_notes": "in-world wording",
        }
        artifact = self.build(
            source=advisory("npc:new-guide"),
            family="entity",
            operation="create",
            candidate=legitimate,
        )
        self.assertEqual(artifact.disposition, "reviewable")
        char_artifact = self.build(
            source=advisory("char:new-helper"),
            family="entity",
            operation="create",
            candidate=entity_candidate("char:new-helper"),
            rollback_hint={
                "strategy": "discard_draft",
                "reference_ids": ["char:new-helper"],
            },
        )
        self.assertEqual(
            advisory_review_to_maintenance_dict(char_artifact)["rollback_hint"][
                "reference_ids"
            ],
            ["char:new-helper"],
        )
        mixed_case_artifact = self.build(
            source=advisory("npc:Eve"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:Eve"),
            disposition="rejected",
            rollback_hint={
                "strategy": "discard_draft",
                "reference_ids": ["npc:Eve"],
            },
        )
        self.assertEqual(
            advisory_review_to_maintenance_dict(mixed_case_artifact)["rollback_hint"][
                "reference_ids"
            ],
            ["npc:Eve"],
        )

        for control_key in (
            "advisory_only",
            "no_direct_writes",
            "reasoning",
            "fact_authority",
            "application_eligible",
            "current_fact",
            "application_authorized",
            "current_fact_authority",
            "proposal_approval_is_commit",
            "can_approve_proposals",
            "can_bypass_validation",
            "save_authorized",
            "validation_bypass",
            "commit_capability",
            "provider_output",
            "raw_helper_output",
            "commit",
            "confirmation",
            "approved",
            "validation_profile",
            "prompt",
            "audit",
            "session",
            "hidden_token",
            "system_prompt",
            "developer_prompt",
            "session_id",
            "error_message",
            "proposal_id",
            "proposal_state",
            "proposal_payload",
            "raw_response",
            "model_response",
            "assistant_response",
            "provider_response",
        ):
            hostile = entity_candidate("npc:new-guide")
            hostile["upsert_entities"][0]["details"] = {control_key: True}  # type: ignore[index]
            with self.subTest(control_key=control_key):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory("npc:new-guide"),
                        family="entity",
                        operation="create",
                        candidate=hostile,
                    )

    def test_content_families_cannot_mutate_aliases(self) -> None:
        create = entity_candidate("npc:new-guide")
        create["upsert_entities"][0]["aliases"] = ["New alias"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=create,
            )
        self.conn.execute(
            "insert into main.aliases(alias, entity_id, kind) values ('Guide alias', 'npc:guide', 'name')"
        )
        self.conn.commit()
        preserving_candidate = entity_candidate("npc:guide")
        preserving_candidate["upsert_entities"][0]["aliases"] = ["Guide alias"]  # type: ignore[index]
        update = self.build(
            source=advisory("npc:guide"),
            family="entity",
            operation="update",
            candidate=preserving_candidate,
        )
        self.assertEqual(update.disposition, "reviewable")
        self.assertTrue(update.application_eligible)
        omitted = self.build(
            source=advisory("npc:guide"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide"),
        )
        self.assertEqual(omitted.disposition, "conflict")

        upsert_entity(
            self.conn,
            {
                "id": "rel:aliased",
                "type": "relationship",
                "name": "Aliased bond",
                "status": "active",
                "visibility": "known",
                "summary": "Existing.",
                "details": {
                    "source_id": "pc:traveler",
                    "target_id": "npc:guide",
                    "kind": "knows",
                },
                "updated_turn_id": "turn:seed",
            },
        )
        self.conn.execute(
            "insert into main.aliases(alias, entity_id, kind) values ('Old bond', 'rel:aliased', 'name')"
        )
        self.conn.commit()
        relationship_update = relationship_candidate("rel:aliased")
        relationship_update["upsert_entities"][0]["aliases"] = ["Old bond"]  # type: ignore[index]
        preserved = self.build(
            source=advisory("rel:aliased"),
            family="relationship",
            operation="update",
            candidate=relationship_update,
        )
        self.assertEqual(preserved.disposition, "reviewable")
        self.assertTrue(preserved.application_eligible)

    def test_create_sources_and_relationship_endpoints_honor_freshness_base(self) -> None:
        self.conn.execute(
            """
            insert into main.turns (id, user_text, intent, changed, created_at)
            values ('turn:000001', 'test', 'test', 0, '2000-01-02T00:00:00+00:00')
            """
        )
        self.conn.execute(
            """
            insert into main.events
              (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
            values ('event:future-source', 'turn:000001', 'day 2', 'test', 'Future', 'Future',
                    '{}', 'test', '2000-01-02T00:00:00+00:00')
            """
        )
        self.conn.commit()
        create = self.build(
            source=advisory(
                "npc:new-guide", source_event_ids=("event:future-source",), as_of_turn_id=0
            ),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
            base_turn_id=None,
        )
        self.assertEqual(create.disposition, "stale")
        upsert_entity(
            self.conn,
            {
                "id": "loc:future",
                "type": "location",
                "name": "Future location",
                "status": "active",
                "visibility": "known",
                "summary": "Created after base.",
                "updated_turn_id": "turn:000001",
            },
        )
        self.conn.commit()
        referenced = entity_candidate("npc:future-reference")
        referenced["upsert_entities"][0]["location_id"] = "loc:future"  # type: ignore[index]
        reference_artifact = self.build(
            source=advisory("npc:future-reference", as_of_turn_id=0),
            family="entity",
            operation="create",
            candidate=referenced,
        )
        self.assertEqual(reference_artifact.disposition, "stale")
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory(
                    "npc:event-only",
                    source_event_ids=("event:future-source",),
                    as_of_turn_id=None,
                ),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:event-only"),
                base_turn_id=None,
            )
        self.conn.execute(
            "update main.entities set updated_turn_id='turn:000001' where id='npc:guide'"
        )
        self.conn.commit()
        relationship = self.build(
            source=advisory("rel:new", as_of_turn_id=0),
            family="relationship",
            operation="create",
            candidate=relationship_candidate("rel:new"),
        )
        self.assertEqual(relationship.disposition, "stale")
        self.assertFalse(relationship.application_eligible)

    def test_evidence_as_of_must_exactly_match_freshness(self) -> None:
        value = advisory("npc:guide").to_dict()
        value["evidence"][0]["as_of_turn_id"] = None
        source = normalize_resident_ai_advisory(value)
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=source,
                family="entity",
                operation="update",
                candidate=entity_candidate("npc:guide"),
            )

    def test_suggestion_family_is_bound_to_advisory_type_and_workflow(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide", advisory_type="plot_progression"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
            )
        mismatched_workflow = normalize_resident_ai_advisory(
            {
                **advisory("npc:new-guide").to_dict(),
                "proposed_next_workflow": "progress_management",
            }
        )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=mismatched_workflow,
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
            )

    def test_builder_and_serializer_share_static_candidate_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("clock:quest:phase-1", advisory_type="progress_management"),
                family="clock_tick",
                operation="tick",
                candidate={
                    "tick_clocks": [
                        {"id": "clock:quest:phase-1", "delta": 1, "reason": "x" * 241}
                    ]
                },
            )
        huge_tick = {
            "tick_clocks": [
                {"id": "clock:quest:phase-1", "delta": 10**1000, "reason": "Huge"}
            ]
        }
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory(
                    "clock:quest:phase-1", advisory_type="progress_management"
                ),
                family="clock_tick",
                operation="tick",
                candidate=huge_tick,
            )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:not-a-clock", advisory_type="progress_management"),
                family="clock_tick",
                operation="tick",
                candidate={
                    "tick_clocks": [
                        {"id": "npc:not-a-clock", "delta": 1, "reason": "Invalid"}
                    ]
                },
            )
        unknown_visibility = entity_candidate("npc:new-guide")
        unknown_visibility["upsert_entities"][0]["visibility"] = "totally-secret"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=unknown_visibility,
            )
        for entity_id, entity_type, nested in (
            ("npc:invalid", "character", {"character": {"trust": True}}),
            ("npc:invalid", "character", {"character": {"stress": []}}),
            ("npc:invalid", "character", {"character": {"goals": {}}}),
            ("npc:invalid", "character", {"character": {"unknown_extension": "x"}}),
            ("item:invalid", "item", {"item": {"quantity": True}}),
            ("item:invalid", "item", {"item": {"quantity": 1e308}}),
            ("item:invalid", "item", {"item": {"properties": []}}),
            ("item:invalid", "item", {"item": {"unknown_extension": "x"}}),
            ("loc:invalid", "location", {"location": {"exits": {}}}),
            ("loc:invalid", "location", {"location": {"unknown_extension": "x"}}),
            (
                "item:invalid",
                "item",
                {"item": {"durability_current": 5, "durability_max": 4}},
            ),
            (
                "plot:invalid",
                "crop_plot",
                {
                    "crop_plot": {
                        "plot_no": 1,
                        "crop_entity_id": "plant:test",
                        "growth_stage": 3,
                        "growth_stage_max": 2,
                    }
                },
            ),
            (
                "plot:invalid",
                "crop_plot",
                {
                    "crop_plot": {
                        "plot_no": 1,
                        "crop_entity_id": "plant:test",
                        "harvest_day_min": 9,
                        "harvest_day_max": 8,
                    }
                },
            ),
            (
                "plot:invalid",
                "crop_plot",
                {
                    "crop_plot": {
                        "plot_no": 1,
                        "crop_entity_id": "plant:test",
                        "unknown_extension": "x",
                    }
                },
            ),
        ):
            numeric = entity_candidate(entity_id)
            numeric["upsert_entities"][0]["type"] = entity_type  # type: ignore[index]
            numeric["upsert_entities"][0].update(nested)  # type: ignore[index]
            with self.subTest(entity_id=entity_id, nested=nested):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory(entity_id),
                        family="entity",
                        operation="create",
                        candidate=numeric,
                    )
        invalid_crop = entity_candidate("plot:invalid-scalar")
        invalid_crop_entity = invalid_crop["upsert_entities"][0]  # type: ignore[index]
        invalid_crop_entity["type"] = "crop_plot"
        invalid_crop_entity["crop_plot"] = {
            "plot_no": 1,
            "crop_entity_id": "npc:guide",
            "expected_yield": {"nested": "value"},
        }
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("plot:invalid-scalar"),
                family="entity",
                operation="create",
                candidate=invalid_crop,
            )

    def test_maintenance_visible_candidate_text_rejects_control_and_bidi(self) -> None:
        cases = (
            ("alias", {"target_id": "npc:guide", "alias": "ok\nFORGED"}),
            (
                "memory_summary",
                {"target_id": "npc:guide", "summary": "safe\u202eunsafe", "source_event_ids": []},
            ),
            (
                "progress_definition",
                {"target_id": "clock:new", "segments_total": 4, "summary": "safe\x1b[31m"},
            ),
        )
        for family, candidate in cases:
            operation = "create" if family == "progress_definition" else "review"
            source_type = (
                "progress_management" if family == "progress_definition" else "entity_maintenance"
            )
            with self.subTest(family=family):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory(
                            str(candidate["target_id"]), advisory_type=source_type
                        ),
                        family=family,
                        operation=operation,
                        candidate=candidate,
                    )
        unknown = entity_candidate("npc:new-guide")
        unknown["upsert_entities"][0]["provider_output"] = PRIVATE_CANARY  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=unknown,
            )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:not-a-clock", advisory_type="progress_management"),
                family="progress_definition",
                operation="create",
                candidate={
                    "target_id": "npc:not-a-clock",
                    "segments_total": 4,
                    "summary": "Invalid namespace.",
                },
            )

        unsafe_key_candidates = []
        details = entity_candidate("npc:unsafe-details-key")
        details["upsert_entities"][0]["details"] = {"safe\u202ename": "value"}  # type: ignore[index]
        unsafe_key_candidates.append(("npc:unsafe-details-key", details))

        properties = entity_candidate("item:unsafe-properties-key")
        properties["upsert_entities"][0]["type"] = "item"  # type: ignore[index]
        properties["upsert_entities"][0]["item"] = {  # type: ignore[index]
            "properties": {"safe\x1b[31m": "value"}
        }
        unsafe_key_candidates.append(("item:unsafe-properties-key", properties))

        knowledge = entity_candidate("npc:unsafe-knowledge-key")
        knowledge["upsert_entities"][0]["character"] = {  # type: ignore[index]
            "knowledge": {"safe\u202ename": "value"}
        }
        unsafe_key_candidates.append(("npc:unsafe-knowledge-key", knowledge))

        for target_id, candidate in unsafe_key_candidates:
            with self.subTest(target_id=target_id):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory(target_id),
                        family="entity",
                        operation="create",
                        candidate=candidate,
                    )

    def test_base_turn_and_reference_ids_use_canonical_safe_syntax(self) -> None:
        self.conn.execute(
            """
            insert into main.turns (id, user_text, intent, changed, created_at)
            values ('turn:not-canonical', 'test', 'test', 0, '2000-01-02T00:00:00+00:00')
            """
        )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            build_advisory_review_artifact(
                self.conn,
                advisory=advisory("npc:guide"),
                suggestion_family="entity",
                suggestion_operation="update",
                candidate=entity_candidate("npc:guide"),
                base_turn_id="turn:not-canonical",
            )
        for supersedes, rollback_hint in (
            (("advisory:x\nINJECT",), {}),
            ((), {"strategy": "discard_draft", "reference_ids": ["npc:x\u202e"]}),
        ):
            with self.subTest(supersedes=supersedes, rollback_hint=rollback_hint):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory("npc:new-guide"),
                        family="entity",
                        operation="create",
                        candidate=entity_candidate("npc:new-guide"),
                        supersedes=supersedes,
                        rollback_hint=rollback_hint,
                    )
        self.conn.execute(
            """
            insert into main.turns (id, user_text, intent, changed, created_at)
            values ('turn:000001', 'test', 'test', 0, '2000-01-03T00:00:00+00:00')
            """
        )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            build_advisory_review_artifact(
                self.conn,
                advisory=advisory("npc:guide", as_of_turn_id=0),
                suggestion_family="entity",
                suggestion_operation="update",
                candidate=entity_candidate("npc:guide"),
                base_turn_id="turn:000001",
            )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
                rollback_hint={
                    "strategy": "discard_draft",
                    "reference_ids": ["prompt:private"],
                },
            )

    def test_turn_freshness_compares_timezone_aware_instants(self) -> None:
        self.conn.executemany(
            """
            insert into main.turns (id, user_text, intent, changed, created_at)
            values (?, 'test', 'test', 0, ?)
            """,
            (
                ("turn:000001", "2020-01-01T01:00:00+01:00"),
                ("turn:000002", "2020-01-01T00:30:00+00:00"),
            ),
        )
        self.conn.execute(
            "update main.entities set updated_turn_id='turn:000002' where id='npc:guide'"
        )
        self.conn.execute(
            "update main.meta set value='turn:000002' where key='current_turn_id'"
        )
        self.conn.commit()
        artifact = self.build(
            source=advisory("npc:guide", as_of_turn_id=1),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide"),
            base_turn_id="turn:000001",
        )
        self.assertEqual(artifact.disposition, "stale")

    def test_future_base_turn_is_rejected_against_authoritative_current_turn(self) -> None:
        self.conn.execute(
            """
            insert into main.turns (id, user_text, intent, changed, created_at)
            values ('turn:000999', 'future', 'test', 0, '9999-01-01T00:00:00+00:00')
            """
        )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            build_advisory_review_artifact(
                self.conn,
                advisory=advisory("npc:guide", as_of_turn_id=999),
                suggestion_family="entity",
                suggestion_operation="update",
                candidate=entity_candidate("npc:guide"),
                base_turn_id="turn:000999",
            )

    def test_player_projection_fails_closed_when_data_version_changes(self) -> None:
        artifact = self.build(
            source=advisory("npc:guide", visibility_mode="player"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide"),
        )
        with mock.patch.object(advisory_review_module, "_data_version", side_effect=(1, 2)):
            self.assertEqual(
                advisory_review_to_player_dict(self.conn, artifact),
                {"available": False, "reason": "advisory review unavailable"},
            )

    def test_player_projection_rejects_same_turn_authoritative_fact_replacement(self) -> None:
        artifact = self.build(
            source=advisory("npc:guide", visibility_mode="player"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide"),
        )
        self.conn.execute(
            """
            update main.entities
            set name = 'Same-turn replacement', summary = 'Changed after issuance',
                updated_turn_id = 'turn:seed'
            where id = 'npc:guide'
            """
        )
        self.conn.commit()
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, artifact),
            {"available": False, "reason": "advisory review unavailable"},
        )
        self.assertEqual(
            advisory_review_to_maintenance_dict(artifact)["target_ids"],
            ["npc:guide"],
        )

    def test_intake_and_player_projection_detect_connection_state_changes(self) -> None:
        with mock.patch.object(advisory_review_module, "_data_version", side_effect=(1, 2)):
            with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                self.build(
                    source=advisory("npc:new-guide"),
                    family="entity",
                    operation="create",
                    candidate=entity_candidate("npc:new-guide"),
                )

        artifact = self.build(
            source=advisory("npc:guide", visibility_mode="player"),
            family="entity",
            operation="update",
            candidate=entity_candidate("npc:guide"),
        )
        original_preflight = advisory_review_module._preflight_candidate

        def add_temp_shadow(*args, **kwargs):
            result = original_preflight(*args, **kwargs)
            self.conn.execute("create temp table events(id text)")
            return result

        with mock.patch.object(
            advisory_review_module, "_preflight_candidate", side_effect=add_temp_shadow
        ):
            self.assertEqual(
                advisory_review_to_player_dict(self.conn, artifact),
                {"available": False, "reason": "advisory review unavailable"},
            )
        self.conn.execute("drop table temp.events")

        original_factory = self.conn.row_factory
        self.conn.row_factory = lambda _conn, row: row
        try:
            self.assertEqual(
                advisory_review_to_player_dict(self.conn, artifact),
                {"available": False, "reason": "advisory review unavailable"},
            )
        finally:
            self.conn.row_factory = original_factory

    def test_player_projection_requires_every_source_target_to_be_visible(self) -> None:
        source = normalize_resident_ai_advisory(
            {
                **advisory("npc:new-guide", visibility_mode="player").to_dict(),
                "evidence": [
                    {"kind": "entity", "ref_id": "pc:traveler", "as_of_turn_id": 0}
                ],
            }
        )
        artifact = self.build(
            source=source,
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
        )
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, artifact),
            {"available": False, "reason": "advisory review unavailable"},
        )

    def test_recomputed_digest_cannot_validate_forged_dataclass(self) -> None:
        artifact = self.build(
            source=advisory("npc:new-guide"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
        )
        wire = advisory_review_to_maintenance_dict(artifact)
        wire["suggestion_operation"] = "tick"
        payload = dict(wire)
        payload.pop("artifact_id")
        payload.pop("authority")
        forged_id = "advisory-review:" + hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        forged = replace(artifact, suggestion_operation="tick", artifact_id=forged_id)
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            advisory_review_to_maintenance_dict(forged)
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, forged),
            {"available": False, "reason": "advisory review unavailable"},
        )

        invalid_candidate = {
            "upsert_entities": [{"id": "npc:new-guide", "type": "character"}]
        }
        invalid_wire = dict(wire)
        invalid_wire["suggestion_operation"] = "create"
        invalid_wire["candidate"] = invalid_candidate
        invalid_payload = dict(invalid_wire)
        invalid_payload.pop("artifact_id")
        invalid_payload.pop("authority")
        invalid_id = "advisory-review:" + hashlib.sha256(
            json.dumps(
                invalid_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        forged_candidate = replace(
            artifact,
            candidate=advisory_review_module._snapshot(invalid_candidate),
            artifact_id=invalid_id,
        )
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            advisory_review_to_maintenance_dict(forged_candidate)
        exact_clone = replace(artifact)
        self.assertIsNot(exact_clone, artifact)
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            advisory_review_to_maintenance_dict(exact_clone)

        issued = self.build(
            source=advisory("npc:issued-mutation"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:issued-mutation"),
        )
        issued_wire = advisory_review_to_maintenance_dict(issued)
        mutated_candidate = entity_candidate("npc:issued-mutation", name="Mutated after preflight")
        mutated_payload = dict(issued_wire)
        mutated_payload["candidate"] = mutated_candidate
        mutated_payload.pop("artifact_id")
        mutated_payload.pop("authority")
        mutated_id = "advisory-review:" + hashlib.sha256(
            json.dumps(
                mutated_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(issued, "candidate", advisory_review_module._snapshot(mutated_candidate))
        object.__setattr__(issued, "artifact_id", mutated_id)
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            advisory_review_to_maintenance_dict(issued)

    def test_snapshot_limits_exact_types_cycles_and_source_aliasing(self) -> None:
        cycle: dict[str, object] = {}
        cycle["cycle"] = cycle

        class StringSubclass(str):
            pass

        invalid_candidates = [
            cycle,
            {"nested": [[[[[[[[["too deep"]]]]]]]]]},
            {"items": list(range(300))},
            {"upsert_entities": [{"id": StringSubclass("npc:new-guide")}]},
            {"upsert_entities": [entity_candidate("npc:new-guide"), None]},
        ]
        for candidate in invalid_candidates:
            with self.subTest(candidate_type=type(candidate).__name__):
                with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                    self.build(
                        source=advisory("npc:new-guide"),
                        family="entity",
                        operation="create",
                        candidate=candidate,  # type: ignore[arg-type]
                    )

        candidate = entity_candidate("npc:new-guide")
        original_snapshot = advisory_review_module._snapshot
        snapshot_ready = threading.Event()
        mutation_done = threading.Event()

        def coordinated_snapshot(value):
            snapshot = original_snapshot(value)
            if value is candidate:
                snapshot_ready.set()
                mutation_done.wait(timeout=2)
            return snapshot

        def mutate_source() -> None:
            snapshot_ready.wait(timeout=2)
            candidate["upsert_entities"][0]["name"] = PRIVATE_CANARY  # type: ignore[index]
            mutation_done.set()

        worker = threading.Thread(target=mutate_source)
        worker.start()
        with mock.patch.object(advisory_review_module, "_snapshot", side_effect=coordinated_snapshot):
            with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
                self.build(
                    source=advisory("npc:new-guide"),
                    family="entity",
                    operation="create",
                    candidate=candidate,
                )
        worker.join(timeout=2)

    def test_intake_does_not_call_queue_apply_commit_or_provider_owners(self) -> None:
        with (
            mock.patch("rpg_engine.proposal_queue.create_proposal") as queue_create,
            mock.patch("rpg_engine.content_delta.apply_content_delta") as content_apply,
            mock.patch("rpg_engine.commit_service.commit_turn_delta") as commit,
            mock.patch("rpg_engine.ai.provider.run_ai_helper_json") as provider,
        ):
            artifact = self.build(
                source=advisory("npc:new-guide"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:new-guide"),
            )
            advisory_review_to_maintenance_dict(artifact)
        queue_create.assert_not_called()
        content_apply.assert_not_called()
        commit.assert_not_called()
        provider.assert_not_called()

    def test_intake_and_serializers_do_not_write_authoritative_or_review_state(self) -> None:
        def database_snapshot() -> dict[str, tuple[tuple[object, ...], ...]]:
            tables = [
                str(row["name"])
                for row in self.conn.execute(
                    "select name from main.sqlite_master where type='table' order by name"
                ).fetchall()
                if not str(row["name"]).startswith("sqlite_")
            ]
            return {
                table: tuple(
                    sorted(
                        (tuple(row) for row in self.conn.execute(f'select * from main."{table}"')),
                        key=repr,
                    )
                )
                for table in tables
            }

        before = database_snapshot()
        total_changes = self.conn.total_changes
        artifact = self.build(
            source=advisory("npc:new-guide"),
            family="entity",
            operation="create",
            candidate=entity_candidate("npc:new-guide"),
        )
        advisory_review_to_maintenance_dict(artifact)
        self.assertEqual(database_snapshot(), before)
        self.assertEqual(self.conn.total_changes, total_changes)

        self.conn.execute("begin")
        with self.assertRaisesRegex(ValueError, "invalid advisory review input"):
            self.build(
                source=advisory("npc:another-guide"),
                family="entity",
                operation="create",
                candidate=entity_candidate("npc:another-guide"),
            )
        self.assertEqual(
            advisory_review_to_player_dict(self.conn, artifact),
            {"available": False, "reason": "advisory review unavailable"},
        )
        self.assertEqual(database_snapshot(), before)
        self.assertEqual(self.conn.total_changes, total_changes)
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()

    def test_temporary_fixture_normalizer_rejects_formal_save_and_missing_rows(self) -> None:
        with self.assertRaisesRegex(AssertionError, "temporary Save copy required"):
            normalize_current_native_story_fixture(CURRENT_SAVE_ROOT)

        with tempfile.TemporaryDirectory() as tmp:
            linked_save = Path(tmp) / "linked-save"
            (linked_save / "data").mkdir(parents=True)
            (linked_save / "data" / "game.sqlite").hardlink_to(
                CURRENT_SAVE_ROOT / "data" / "game.sqlite"
            )
            with self.assertRaisesRegex(AssertionError, "independent temporary Save database"):
                normalize_current_native_story_fixture(linked_save)

        with tempfile.TemporaryDirectory() as tmp:
            save_root = copy_current_packages(tmp)
            with sqlite3.connect(save_root / "data" / "game.sqlite") as conn:
                conn.execute("delete from projection_state where name='memory'")
            with self.assertRaisesRegex(AssertionError, "normalization target missing"):
                normalize_current_native_story_fixture(save_root)


if __name__ == "__main__":
    unittest.main()
