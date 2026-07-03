from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from rpg_engine.campaign_validation import validate_campaign_package, run_campaign_smoke_tests
from rpg_engine.campaign import load_campaign


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def copy_fixture(tmp: str | Path) -> Path:
    target = Path(tmp) / "campaign"
    shutil.copytree(MINIMAL_FIXTURE, target)
    return target


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


class CampaignValidationTests(unittest.TestCase):
    def test_minimal_campaign_passes_v1_validation_and_smoke_tests(self) -> None:
        result = validate_campaign_package(MINIMAL_FIXTURE)
        smoke = run_campaign_smoke_tests(MINIMAL_FIXTURE)

        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.capabilities, ("query", "rest_time"))
        self.assertEqual(result.smoke_tests, ("query-scene", "rest-preview"))
        self.assertTrue(smoke.ok, smoke.errors)
        self.assertTrue(all(item.ok for item in smoke.smoke_results))

    def test_rejects_unsupported_capability_and_missing_smoke_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["capabilities"] = ["query", "arbitrary_code", "travel"]
            write_yaml(manifest_path, manifest)

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            joined = "\n".join(result.errors)
            self.assertIn("unsupported capability arbitrary_code", joined)
            self.assertIn("capability travel has no smoke test coverage", joined)

    def test_rejects_bad_references_for_entry_player_and_entity_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["initial_location_id"] = "loc:missing"
            manifest["defaults"]["player_entity_id"] = "pc:missing"
            write_yaml(manifest_path, manifest)

            entities_path = campaign / "content" / "entities.yaml"
            entities = load_yaml(entities_path)
            entities["entities"][1]["location_id"] = "loc:missing"
            write_yaml(entities_path, entities)

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            joined = "\n".join(result.errors)
            self.assertIn("campaign.yaml.initial_location_id: missing location loc:missing", joined)
            self.assertIn("campaign.yaml.defaults.player_entity_id: missing entity pc:missing", joined)
            self.assertIn("entity[1].location_id: missing entity loc:missing", joined)

    def test_rejects_invalid_random_table_weights_and_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            random_tables_path = campaign / "content" / "random_tables.yaml"
            data = load_yaml(random_tables_path)
            data["random_tables"][0]["visibility"] = "public"
            data["random_tables"][0]["entries"][0]["weight"] = 0
            write_yaml(random_tables_path, data)

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            joined = "\n".join(result.errors)
            self.assertIn("visibility: unsupported value public", joined)
            self.assertIn("weight: must be positive number", joined)

    def test_rejects_absolute_content_paths_and_code_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["entities"] = ["/tmp/entities.yaml"]
            write_yaml(manifest_path, manifest)
            (campaign / "plugins").mkdir()
            (campaign / "author_rules.py").write_text("print('no')\n", encoding="utf-8")

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            joined = "\n".join(result.errors)
            self.assertIn("must use relative package path", joined)
            self.assertIn("plugins/: V1 campaign packages must not include plugins", joined)
            self.assertIn("author_rules.py: V1 campaign packages must not include Python code", joined)

    def test_campaign_runtime_paths_must_stay_under_campaign_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_dir = copy_fixture(tmp)
            campaign = load_campaign(campaign_dir)

            self.assertEqual(campaign.database_path, (campaign_dir / "data" / "game.sqlite").resolve())

            manifest_path = campaign_dir / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["database"] = "/tmp/escape.sqlite"
            write_yaml(manifest_path, manifest)
            escaped = load_campaign(campaign_dir)
            with self.assertRaisesRegex(ValueError, "must be relative"):
                _ = escaped.database_path

            manifest["database"] = "../escape.sqlite"
            write_yaml(manifest_path, manifest)
            escaped_parent = load_campaign(campaign_dir)
            with self.assertRaisesRegex(ValueError, "escapes campaign root"):
                _ = escaped_parent.database_path

    def test_campaign_test_reports_failed_smoke_assertion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            smoke_path = campaign / "tests" / "smoke.yaml"
            smoke = load_yaml(smoke_path)
            smoke["smoke_tests"][0]["contains"] = "text-that-will-not-appear"
            write_yaml(smoke_path, smoke)

            result = run_campaign_smoke_tests(campaign)

            self.assertFalse(result.ok)
            self.assertIn("expected output to contain", "\n".join(result.errors))


if __name__ == "__main__":
    unittest.main()
