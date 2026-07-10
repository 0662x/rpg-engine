from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from rpg_engine.campaign import load_campaign
from rpg_engine.campaign_validation import run_campaign_smoke_tests, validate_campaign_package
from rpg_engine.db import connect
from rpg_engine.memory import memory_metadata_columns_present
from rpg_engine.migrations import migration_status

from tests.helpers import (
    CURRENT_CAMPAIGN_ROOT as CAMPAIGN_ROOT,
    CURRENT_NATIVE_REQUIRED,
    CURRENT_SAVE_ROOT as SAVE_ROOT,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
    load_stdout_json,
    run_cli,
)


@CURRENT_NATIVE_REQUIRED
class CurrentNativePackageTests(FormalCurrentSaveReadOnlyTestCase):
    def test_author_campaign_package_validates_and_smoke_tests_current_contracts(self) -> None:
        validation = validate_campaign_package(CAMPAIGN_ROOT)
        self.assertTrue(validation.ok, validation.errors)
        self.assertIn("combat", validation.capabilities)
        self.assertIn("gather_search", validation.capabilities)
        self.assertGreaterEqual(validation.record_counts.get("entity", 0), 150)
        self.assertGreaterEqual(validation.record_counts.get("route", 0), 20)
        self.assertIn("preview-gather", validation.smoke_tests)

        smoke = run_campaign_smoke_tests(CAMPAIGN_ROOT)
        self.assertTrue(smoke.ok, smoke.errors)
        by_id = {item.case_id: item for item in smoke.smoke_results}
        self.assertEqual(by_id["preview-gather"].ok, True)
        self.assertEqual(by_id["validate-clock-delta"].ok, True)
        self.assertTrue(all(item.ok for item in smoke.smoke_results), smoke.errors)

    def test_author_campaign_manifest_declares_current_native_capabilities(self) -> None:
        manifest = yaml.safe_load((CAMPAIGN_ROOT / "campaign.yaml").read_text(encoding="utf-8"))

        self.assertEqual(manifest["id"], "isekai-farm")
        self.assertEqual(manifest["defaults"]["player_entity_id"], "pc:shenyan")
        self.assertEqual(manifest["initial_location_id"], "loc:home-clearing")
        self.assertEqual(manifest["defaults"]["default_weapon_id"], "item:ultimate-compound-crossbow")
        self.assertTrue({"query", "travel", "social", "gather_search", "combat"}.issubset(manifest["capabilities"]))
        self.assertGreaterEqual(len(manifest["content"]["entities"]), 10)

    def test_save_package_manifest_is_runtime_state_not_author_package(self) -> None:
        save_manifest = yaml.safe_load((SAVE_ROOT / "save.yaml").read_text(encoding="utf-8"))
        save_campaign = yaml.safe_load((SAVE_ROOT / "campaign.yaml").read_text(encoding="utf-8"))

        self.assertEqual(save_manifest["campaign_id"], "isekai-farm")
        self.assertEqual(save_manifest["source_campaign_path"], "../isekai-farm-campaign-native-v1")
        self.assertEqual(save_campaign["database"], "data/game.sqlite")
        self.assertEqual(save_campaign["events"], "data/events.jsonl")
        self.assertEqual(save_campaign["current_snapshot_json"], "snapshots/current.json")
        self.assertTrue((SAVE_ROOT / "data" / "game.sqlite").exists())
        self.assertTrue((SAVE_ROOT / "cards" / "INDEX.md").exists())

    def test_author_and_save_packages_keep_clean_responsibility_boundary(self) -> None:
        author_manifest = yaml.safe_load((CAMPAIGN_ROOT / "campaign.yaml").read_text(encoding="utf-8"))

        for runtime_path in ["data/game.sqlite", "data/events.jsonl", "cards", "snapshots", "backups"]:
            with self.subTest(runtime_path=runtime_path):
                self.assertFalse((CAMPAIGN_ROOT / runtime_path).exists())

        for runtime_path in ["data/game.sqlite", "data/events.jsonl", "cards/INDEX.md", "snapshots/current.json"]:
            with self.subTest(save_path=runtime_path):
                self.assertTrue((SAVE_ROOT / runtime_path).exists())

        for key, paths in author_manifest["content"].items():
            with self.subTest(content_group=key):
                self.assertTrue(paths)
                for relative_path in paths:
                    self.assertFalse(Path(relative_path).is_absolute())
                    self.assertTrue((CAMPAIGN_ROOT / relative_path).exists(), relative_path)

    def test_cli_campaign_validate_json_contract_for_current_author_package(self) -> None:
        result = load_stdout_json(run_cli("campaign", "validate", CAMPAIGN_ROOT, "--format", "json"))

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["campaign_id"], "isekai-farm")
        self.assertIn("preview-combat-with-ammo", result["smoke_tests"])
        self.assertGreaterEqual(result["record_counts"]["entity"], 150)
        self.assertGreaterEqual(result["record_counts"]["world_setting"], 10)

    def test_current_save_check_and_inspect_report_runtime_shape(self) -> None:
        self.assertEqual(run_cli("check", SAVE_ROOT).stdout.strip(), "OK")

        inspect = load_stdout_json(run_cli("save", "inspect", SAVE_ROOT, "--format", "json", check=False))

        self.assertEqual(inspect["campaign_id"], "isekai-farm")
        self.assertEqual(inspect["current_turn_id"], "turn:000044")
        self.assertEqual(inspect["current_location_id"], "loc:home-mycelium-house")
        self.assertGreaterEqual(inspect["counts"]["entities"], 250)
        self.assertGreaterEqual(inspect["counts"]["events"], 70)

    def test_current_save_validate_surfaces_pending_migrations_without_hiding_other_health(self) -> None:
        validation = load_stdout_json(run_cli("save", "validate", SAVE_ROOT, "--format", "json", check=False))
        codes = {item["code"] for item in validation["error_details"]}

        if validation["ok"]:
            self.assertEqual(validation["errors"], [])
            self.assertEqual(codes, set())
        else:
            self.assertEqual(codes, {"SCHEMA_INCONSISTENT"})
            self.assertTrue(any("0006_intent_preflight_cache" in item for item in validation["errors"]))
            self.assertTrue(any("0008_intent_joiner_message_only" in item for item in validation["errors"]))
            self.assertTrue(any("0009_memory_summary_provenance" in item for item in validation["errors"]))
        self.assertEqual(run_cli("check", SAVE_ROOT).stdout.strip(), "OK")

    def test_pending_migrations_apply_cleanly_on_temp_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)

            applied = run_cli("migrate", "apply", save).stdout
            validation = load_stdout_json(run_cli("save", "validate", save, "--format", "json"))

            if "no pending migrations" in applied:
                self.assertNotIn("backup: backup-", applied)
            else:
                self.assertIn("backup: backup-", applied)
                self.assertIn("0006_intent_preflight_cache", applied)
                self.assertIn("0008_intent_joiner_message_only", applied)
            self.assertTrue(validation["ok"], validation)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                by_id = {record.id: record for record in migration_status(conn)}
                self.assertTrue(by_id["0009_memory_summary_provenance"].applied)
                self.assertTrue(memory_metadata_columns_present(conn))


if __name__ == "__main__":
    import unittest

    unittest.main()
