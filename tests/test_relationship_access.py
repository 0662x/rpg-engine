from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rpg_engine.campaign import load_campaign
from rpg_engine.content_validation import validate_content_delta
from rpg_engine.db import connect, upsert_entity
from rpg_engine.delta_schema import validate_delta_schema
from rpg_engine.relationship_access import (
    RelationshipRecord,
    list_relationships,
    read_relationship,
    validate_delta_relationship_references,
)
from rpg_engine.save_service import init_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


class RelationshipAccessContractTests(unittest.TestCase):
    def test_read_relationship_exposes_stable_fields_and_filters_player_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "pc:host",
                        "type": "character",
                        "name": "Host",
                        "summary": "Visible player host.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:mira",
                        "type": "character",
                        "name": "Mira",
                        "summary": "Visible NPC.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden",
                        "type": "character",
                        "name": "Hidden NPC",
                        "visibility": "hidden",
                        "summary": "Hidden NPC.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:archived",
                        "type": "character",
                        "name": "Archived NPC",
                        "status": "archived",
                        "summary": "Archived NPC.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:visible",
                        "type": "relationship",
                        "name": "Host and Mira",
                        "summary": "Mira trusts careful proof.",
                        "details": {
                            "source_id": "pc:host",
                            "target_id": "npc:mira",
                            "kind": "social",
                            "state": "cautious ally",
                            "attitude": "guarded",
                            "stance": "proof before risk",
                            "trust": 20,
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:hidden",
                        "type": "relationship",
                        "name": "Hidden Relationship",
                        "visibility": "hidden",
                        "summary": "Hidden relationship.",
                        "details": {"source_id": "pc:host", "target_id": "npc:mira"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:hidden-endpoint",
                        "type": "relationship",
                        "name": "Hidden Endpoint",
                        "summary": "Endpoint is hidden.",
                        "details": {"source_id": "pc:host", "target_id": "npc:hidden"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:archived-endpoint",
                        "type": "relationship",
                        "name": "Archived Endpoint",
                        "summary": "Endpoint is archived.",
                        "details": {"source_id": "pc:host", "target_id": "npc:archived"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:missing-endpoint",
                        "type": "relationship",
                        "name": "Missing Endpoint",
                        "summary": "Endpoint is missing.",
                        "details": {"source_id": "pc:host", "target_id": "npc:missing"},
                    },
                )
                conn.commit()

                relationship = read_relationship(conn, "rel:visible")
                self.assertIsInstance(relationship, RelationshipRecord)
                assert relationship is not None
                self.assertEqual(relationship.id, "rel:visible")
                self.assertEqual(relationship.source_id, "pc:host")
                self.assertEqual(relationship.target_id, "npc:mira")
                self.assertEqual(relationship.kind, "social")
                self.assertEqual(relationship.state, "cautious ally")
                self.assertEqual(relationship.attitude, "guarded")
                self.assertEqual(relationship.stance, "proof before risk")
                self.assertEqual(relationship.trust, 20)
                self.assertEqual(relationship.visibility, "known")
                self.assertEqual(relationship.summary, "Mira trusts careful proof.")
                self.assertEqual(relationship.details["source_id"], "pc:host")
                self.assertEqual(relationship.details["target_id"], "npc:mira")
                self.assertEqual(relationship.updated_turn_id, "turn:seed")
                self.assertRegex(relationship.updated_at, r"^\d{4}-\d{2}-\d{2}T")
                self.assertEqual(relationship.endpoint_issues, ())
                self.assertEqual(relationship.source.id, "pc:host")
                self.assertEqual(relationship.target.id, "npc:mira")
                self.assertEqual(relationship.to_dict()["summary"], "Mira trusts careful proof.")

                player_ids = {item.id for item in list_relationships(conn, view="player")}
                self.assertIn("rel:visible", player_ids)
                self.assertNotIn("rel:hidden", player_ids)
                self.assertNotIn("rel:hidden-endpoint", player_ids)
                self.assertNotIn("rel:archived-endpoint", player_ids)
                self.assertNotIn("rel:missing-endpoint", player_ids)
                self.assertIsNone(read_relationship(conn, "rel:hidden-endpoint", view="player"))
                self.assertEqual(list_relationships(conn, view="player", limit=0), [])
                self.assertEqual(list_relationships(conn, view="player", limit=-1), [])
                with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                    list_relationships(conn, view="player", limit=True)  # type: ignore[arg-type]
                with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                    list_relationships(conn, view="player", limit="1")  # type: ignore[arg-type]

                hidden_for_gm = read_relationship(conn, "rel:hidden", view="gm")
                self.assertIsNotNone(hidden_for_gm)
                hidden_endpoint_for_gm = read_relationship(conn, "rel:hidden-endpoint", view="gm")
                self.assertIsNotNone(hidden_endpoint_for_gm)
                assert hidden_endpoint_for_gm is not None
                self.assertEqual(hidden_endpoint_for_gm.target.id, "npc:hidden")

                missing_for_maintenance = read_relationship(conn, "rel:missing-endpoint", view="maintenance")
                self.assertIsNotNone(missing_for_maintenance)
                assert missing_for_maintenance is not None
                self.assertEqual(missing_for_maintenance.endpoint_issues, ("target_id: missing entity npc:missing",))

                archived_for_maintenance = read_relationship(conn, "rel:archived-endpoint", view="maintenance")
                self.assertIsNotNone(archived_for_maintenance)
                assert archived_for_maintenance is not None
                self.assertEqual(archived_for_maintenance.endpoint_issues, ("target_id: archived entity npc:archived",))
                self.assertIsNone(archived_for_maintenance.target)
                self.assertIsNone(archived_for_maintenance.to_dict()["target"])

    def test_delta_schema_validates_runtime_relationship_endpoint_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "pc:host",
                        "type": "character",
                        "name": "Host",
                        "summary": "Visible player host.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:mira",
                        "type": "character",
                        "name": "Mira",
                        "summary": "Visible NPC.",
                    },
                )
                conn.commit()

                valid_delta = {
                    "user_text": "record relationship",
                    "intent": "test",
                    "summary": "Relationship changed.",
                    "events": [{"type": "test", "title": "Relation", "summary": "Changed.", "source": "test"}],
                    "upsert_entities": [
                        {
                            "id": "npc:new",
                            "type": "character",
                            "name": "New NPC",
                            "summary": "Created with relationship.",
                        },
                        {
                            "id": "rel:host-new",
                            "type": "relationship",
                            "name": "Host and New NPC",
                            "summary": "New relationship.",
                            "details": {"source_id": "pc:host", "target_id": "npc:new", "state": "new contact"},
                        },
                    ],
                }
                self.assertEqual(validate_delta_relationship_references(conn, valid_delta), [])
                self.assertEqual(validate_delta_schema(valid_delta, conn), [])

                invalid_delta = {
                    "user_text": "record relationship",
                    "intent": "test",
                    "summary": "Relationship invalid.",
                    "events": [{"type": "test", "title": "Relation", "summary": "Changed.", "source": "test"}],
                    "upsert_entities": [
                        {
                            "id": "rel:missing-target",
                            "type": "relationship",
                            "name": "Missing Target",
                            "summary": "Missing target.",
                            "details": {"source_id": "pc:host"},
                        },
                        {
                            "id": "rel:empty-source",
                            "type": "relationship",
                            "name": "Empty Source",
                            "summary": "Empty source.",
                            "details": {"source_id": "", "target_id": "npc:mira"},
                        },
                        {
                            "id": "rel:bad-target",
                            "type": "relationship",
                            "name": "Bad Target",
                            "summary": "Bad target.",
                            "details": {"source_id": "pc:host", "target_id": 0},
                        },
                        {
                            "id": "rel:space-source",
                            "type": "relationship",
                            "name": "Space Source",
                            "summary": "Space source.",
                            "details": {"source_id": " pc:host ", "target_id": "npc:mira"},
                        },
                        {
                            "id": "rel:invalid-id",
                            "type": "relationship",
                            "name": "Invalid ID",
                            "summary": "Invalid endpoint id.",
                            "details": {"source_id": "not-an-entity-id", "target_id": "npc:mira"},
                        },
                        {
                            "id": "rel:missing-entity",
                            "type": "relationship",
                            "name": "Missing Entity",
                            "summary": "Missing endpoint entity.",
                            "details": {"source_id": "pc:host", "target_id": "npc:missing"},
                        },
                        {
                            "id": "rel:bad-details",
                            "type": "relationship",
                            "name": "Bad Details",
                            "summary": "Details must be an object.",
                            "details": "bad",
                        },
                    ],
                }
                errors = validate_delta_schema(invalid_delta, conn)
                self.assertIn("$.upsert_entities[0].details.target_id: required", errors)
                self.assertIn("$.upsert_entities[1].details.source_id: must be non-empty string", errors)
                self.assertIn("$.upsert_entities[2].details.target_id: must be non-empty string", errors)
                self.assertIn("$.upsert_entities[3].details.source_id: must not contain leading or trailing whitespace", errors)
                self.assertIn("$.upsert_entities[4].details.source_id: invalid entity id", errors)
                self.assertIn("$.upsert_entities[5].details.target_id: missing entity npc:missing", errors)
                self.assertIn("$.upsert_entities[6].details: must be object", errors)
                self.assertIn("$.upsert_entities[6].details.source_id: required", errors)
                self.assertIn("$.upsert_entities[6].details.target_id: required", errors)

                content_delta = {
                    "title": "bad relationship content delta",
                    "description": "relationship upsert must validate endpoints",
                    "upsert_entities": [
                        {
                            "id": "rel:content-bad",
                            "type": "relationship",
                            "name": "Content Delta Bad Relationship",
                            "summary": "Missing target endpoint.",
                            "details": {"source_id": "pc:host"},
                        }
                    ],
                }
                content_errors = validate_content_delta(content_delta, conn).errors
                self.assertIn("$.upsert_entities[0].details.target_id: required", content_errors)


if __name__ == "__main__":
    unittest.main()
