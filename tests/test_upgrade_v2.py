from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from rpg_engine.campaign import load_campaign
from rpg_engine.card_registry import get_default_card_registry
from rpg_engine.content_delta import apply_content_delta
from rpg_engine.content_validation import validate_content_delta
from rpg_engine.content_types import get_default_registry
from rpg_engine.context_builder import build_context
from rpg_engine.db import connect, init_database
from rpg_engine.render import render_current_snapshot, render_entity


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def copy_minimal_campaign(target_root: Path) -> Path:
    target = target_root / "minimal"
    shutil.copytree(MINIMAL_FIXTURE, target)
    return target


class ArchitectureCompatibilityTests(unittest.TestCase):
    def test_legacy_actions_builtin_wrapper_still_exports_existing_symbols(self) -> None:
        from rpg_engine.actions.builtin import REST_RESOLVER, SOCIAL_RESOLVER, preview_rest

        self.assertEqual(REST_RESOLVER.name, "rest")
        self.assertEqual(SOCIAL_RESOLVER.name, "social")
        self.assertTrue(callable(preview_rest))


class EngineUpgradeFixtureTests(unittest.TestCase):
    def test_every_delta_content_type_has_record_preflight(self) -> None:
        for spec in get_default_registry().delta_specs():
            with self.subTest(content_type=spec.name):
                self.assertIsNotNone(spec.validate_record)

    def test_configurable_player_id_works_in_second_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_minimal_campaign(Path(tmp))
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            with connect(campaign) as conn:
                snapshot = render_current_snapshot(campaign, conn)
                packet = build_context(
                    campaign,
                    conn,
                    user_text="look around",
                    mode="query",
                    submode="scene",
                    budget=1800,
                    output_format="json",
                )

        self.assertIn("The configurable player character", snapshot)
        self.assertNotIn("pc:shenyan", snapshot)
        self.assertIn("pc:traveler", packet.to_json_text())

    def test_campaign_sample_texts_are_configurable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_minimal_campaign(Path(tmp))
            config_path = campaign_path / "campaign.yaml"
            text = config_path.read_text(encoding="utf-8")
            config_path.write_text(
                text.replace(
                    "  context_budget: 1800\n",
                    "  context_budget: 1800\n  sample_texts:\n    - inspect camp\n    - travel north\n    - ''\n",
                ),
                encoding="utf-8",
            )
            campaign = load_campaign(campaign_path)

        self.assertEqual(campaign.sample_texts, ["inspect camp", "travel north"])

    def test_faction_state_runtime_entity_type_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_minimal_campaign(Path(tmp))
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            delta = {
                "title": "faction state",
                "description": "add a runtime faction state record",
                "upsert_entities": [
                    {
                        "id": "fstate:test-guild",
                        "type": "faction_state",
                        "name": "Test Guild State",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Runtime state for a test faction.",
                        "details": {
                            "relationship": "neutral",
                            "resources": {"food": "low"},
                            "current_goal": "secure water",
                        },
                    }
                ],
            }
            with connect(campaign) as conn:
                validation = validate_content_delta(delta, conn)
                self.assertTrue(validation.ok, validation.errors)
                apply_content_delta(campaign, conn, delta)
                rendered = render_entity(conn, "fstate:test-guild")

        self.assertIn("Runtime state for a test faction", rendered)
        self.assertEqual(get_default_card_registry().card_dir("faction_state"), "faction_states")

    def test_unknown_content_key_is_rejected_without_turn_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_minimal_campaign(Path(tmp))
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            with connect(campaign) as conn:
                before_turns = conn.execute("select count(*) from turns").fetchone()[0]
                before_events = conn.execute("select count(*) from events").fetchone()[0]
                delta = {
                    "title": "bad content",
                    "description": "must fail before writing",
                    "upsert_magic": [{"id": "magic:bad"}],
                }
                result = validate_content_delta(delta, conn)
                self.assertTrue(any("unregistered content delta key" in item for item in result.errors))
                with self.assertRaises(ValueError):
                    apply_content_delta(campaign, conn, delta)
                self.assertEqual(conn.execute("select count(*) from turns").fetchone()[0], before_turns)
                self.assertEqual(conn.execute("select count(*) from events").fetchone()[0], before_events)

    def test_missing_route_cross_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_minimal_campaign(Path(tmp))
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            delta = {
                "description": "bad route",
                "upsert_routes": [
                    {
                        "id": "route:missing",
                        "from_location_id": "loc:missing",
                        "to_location_id": "loc:start",
                        "travel_minutes": 5,
                    }
                ],
            }
            with connect(campaign) as conn:
                result = validate_content_delta(delta, conn)

        self.assertIn("$.upsert_routes[0].from_location_id: missing location loc:missing", result.errors)


if __name__ == "__main__":
    unittest.main()
