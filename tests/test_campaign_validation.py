from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from rpg_engine.campaign_validation import validate_campaign_package, run_campaign_smoke_tests
from rpg_engine.campaign import load_campaign
from rpg_engine.palette import palette_files


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

    def test_reports_runtime_artifacts_without_rejecting_author_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            (campaign / "AUTHOR_NOTES.md").write_text("Author notes.\n", encoding="utf-8")
            (campaign / "AUTHOR_AI_PROMPT.md").write_text("Author prompt.\n", encoding="utf-8")
            (campaign / "docs").mkdir()
            (campaign / "docs" / "README.md").write_text("Author docs.\n", encoding="utf-8")
            (campaign / "package-lock.json").write_text("{}\n", encoding="utf-8")

            runtime_files = {
                "game.sqlite": b"not-a-real-db",
                "runtime.db": b"not-a-real-db",
                "runtime.sqlite3": b"not-a-real-db",
                "game.sqlite-wal": b"wal\n",
                "runtime.sqlite3-wal": b"wal\n",
                "data/game.sqlite": b"not-a-real-db",
                "data/events.jsonl": b"{}\n",
                "data/runtime-cache.tmp": b"cache\n",
                "save.yaml": b"campaign_id: runtime\n",
                "snapshots/current.json": b"{}\n",
                "cards/INDEX.md": b"# Cards\n",
                "memory/summary.md": b"memory\n",
                "backups/backup-1/manifest.json": b"{}\n",
                "reports/runtime.md": b"runtime report\n",
                "archive.aigmsave": b"archive\n",
                ".aigm/save-registry.json": b"{}\n",
                ".aigm/pending-player-action.json": b"{}\n",
                ".aigm/pending-player-clarification.json": b"{}\n",
                ".aigm/pending-late-review.json": b"{}\n",
            }
            for relative, content in runtime_files.items():
                path = campaign / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            symlink_runtime: list[str] = []
            external_runtime_dir = Path(tmp) / "external-runtime"
            external_runtime_dir.mkdir()
            try:
                (campaign / "exports").symlink_to(external_runtime_dir, target_is_directory=True)
                symlink_runtime.append("exports/")
                (campaign / ".aigm" / "pending-dangling.json").symlink_to("missing-pending.json")
                symlink_runtime.append(".aigm/pending-dangling.json")
                (campaign / "data" / "dangling-runtime.tmp").symlink_to("missing-runtime.tmp")
                symlink_runtime.append("data/dangling-runtime.tmp")
                (campaign / "data" / "runtime-dir-link").symlink_to(external_runtime_dir, target_is_directory=True)
                symlink_runtime.append("data/runtime-dir-link/")
            except OSError:
                symlink_runtime = []

            result = validate_campaign_package(campaign)

            self.assertTrue(result.ok, result.errors)
            joined_warnings = "\n".join(result.warnings)
            joined_errors = "\n".join(result.errors)
            for relative in [*runtime_files, *symlink_runtime]:
                with self.subTest(relative=relative):
                    self.assertIn(relative, joined_warnings)
                    self.assertIn(
                        f"{relative}: runtime Save Package artifact should not be included in a Campaign Package",
                        result.warnings,
                    )
                    self.assertNotIn(relative, joined_errors)
            self.assertNotIn("AUTHOR_NOTES.md", joined_warnings)
            self.assertNotIn("AUTHOR_AI_PROMPT.md", joined_warnings)
            self.assertNotIn("docs/README.md", joined_warnings)
            self.assertNotIn("package-lock.json", joined_warnings)

    def test_reports_aigm_symlink_without_following_external_pending_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            external_runtime_dir = Path(tmp) / "external-aigm"
            external_runtime_dir.mkdir()
            (external_runtime_dir / "save-registry.json").write_text("{}\n", encoding="utf-8")
            (external_runtime_dir / "pending-external.json").write_text("{}\n", encoding="utf-8")
            try:
                (campaign / ".aigm").symlink_to(external_runtime_dir, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable")

            result = validate_campaign_package(campaign)

            self.assertTrue(result.ok, result.errors)
            self.assertIn(
                ".aigm/: runtime Save Package artifact should not be included in a Campaign Package",
                result.warnings,
            )
            joined_warnings = "\n".join(result.warnings)
            self.assertNotIn(".aigm/save-registry.json", joined_warnings)
            self.assertNotIn("pending-external.json", joined_warnings)

    def test_rejects_content_paths_that_escape_campaign_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = copy_fixture(root)
            outside = root / "outside"
            outside.mkdir()
            shutil.copy2(campaign / "content" / "entities.yaml", outside / "entities.yaml")
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["entities"] = "../outside/entities.yaml"
            write_yaml(manifest_path, manifest)

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            self.assertIn(
                "campaign.yaml.content.entities: path escapes campaign root ../outside/entities.yaml",
                result.errors,
            )
            self.assertNotIn("entity", result.record_counts)

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

    def test_campaign_test_ignores_runtime_symlink_artifacts_when_copying_temp_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            external_runtime_dir = Path(tmp) / "external-memory"
            external_runtime_dir.mkdir()
            try:
                (external_runtime_dir / "dangling").symlink_to("missing-target")
                (campaign / "memory").symlink_to(external_runtime_dir, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable")

            result = run_campaign_smoke_tests(campaign)

            self.assertTrue(result.ok, result.errors)

    def test_campaign_test_keeps_author_content_directories_named_like_runtime_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            nested_data = campaign / "content" / "data"
            nested_data.mkdir()
            shutil.move(campaign / "content" / "entities.yaml", nested_data / "entities.yaml")
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["entities"] = "content/data/entities.yaml"
            write_yaml(manifest_path, manifest)

            result = run_campaign_smoke_tests(campaign)

            self.assertTrue(result.ok, result.errors)

    def test_palette_auto_discovery_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            outside = Path(tmp) / "outside-palettes"
            outside.mkdir()
            (outside / "external.yaml").write_text("materials: []\n", encoding="utf-8")
            palette_dir = campaign / "content" / "palettes"
            try:
                palette_dir.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation is unavailable")

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            self.assertIn("content/palettes: path escapes campaign root", result.errors)
            with self.assertRaisesRegex(ValueError, "palette directory escapes campaign root"):
                palette_files(load_campaign(campaign))


if __name__ == "__main__":
    unittest.main()
