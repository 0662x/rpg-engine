from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from rpg_engine.campaign_validation import OPTIONAL_CONTENT_KEYS, validate_campaign_package, run_campaign_smoke_tests
from rpg_engine.campaign import load_campaign
from rpg_engine.content_types import get_default_registry
from rpg_engine.content_sync import sync_campaign_content
from rpg_engine.content_validation import validate_content_sources
from rpg_engine.db import connect, init_database
from rpg_engine.ai.schema_validation import validate_with_jsonschema
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

    def test_rejects_missing_or_non_file_random_table_paths_without_traceback(self) -> None:
        cases = [
            ("missing", "content/missing-random-tables.yaml", "campaign.yaml.content.random_tables: missing file"),
            ("directory", "content/random-table-dir", "campaign.yaml.content.random_tables: not a file"),
        ]
        for name, relative, expected in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                campaign = copy_fixture(tmp)
                manifest_path = campaign / "campaign.yaml"
                manifest = load_yaml(manifest_path)
                manifest["content"]["random_tables"] = [relative]
                write_yaml(manifest_path, manifest)
                if name == "directory":
                    (campaign / relative).mkdir()

                result = validate_campaign_package(campaign)

                self.assertFalse(result.ok)
                self.assertIn(expected, "\n".join(result.errors))

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

    def test_rejects_content_paths_with_parent_segments_even_when_they_stay_in_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["entities"] = ["content/../content/entities.yaml"]
            write_yaml(manifest_path, manifest)

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            self.assertIn(
                "campaign.yaml.content.entities: path escapes campaign root content/../content/entities.yaml",
                result.errors,
            )

    def test_rejects_unknown_content_key_from_unregistered_entity_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["characters"] = "content/characters.yaml"
            write_yaml(manifest_path, manifest)
            (campaign / "content" / "characters.yaml").write_text("characters: []\n", encoding="utf-8")

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            self.assertIn("campaign.yaml.content.characters: unsupported V1 content key", result.errors)

    def test_campaign_schema_rejects_unregistered_content_roots(self) -> None:
        manifest = load_yaml(MINIMAL_FIXTURE / "campaign.yaml")
        manifest["content"]["characters"] = "content/characters.yaml"

        for schema_path in [
            ENGINE_ROOT / "schemas" / "campaign.schema.json",
            ENGINE_ROOT / "rpg_engine" / "resources" / "schemas" / "campaign.schema.json",
        ]:
            with self.subTest(schema=str(schema_path)):
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                content_schema = {
                    "$schema": schema["$schema"],
                    "$defs": schema["$defs"],
                    **schema["properties"]["content"],
                }
                errors = validate_with_jsonschema(content_schema, manifest["content"])
                self.assertIn("$.characters: unknown field", errors)

    def test_campaign_schema_content_keys_match_registry_contract(self) -> None:
        expected = {
            *(spec.campaign_key for spec in get_default_registry().seed_specs() if spec.campaign_key),
            *OPTIONAL_CONTENT_KEYS,
        }

        for schema_path in [
            ENGINE_ROOT / "schemas" / "campaign.schema.json",
            ENGINE_ROOT / "rpg_engine" / "resources" / "schemas" / "campaign.schema.json",
        ]:
            with self.subTest(schema=str(schema_path)):
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                content = schema["properties"]["content"]
                self.assertEqual(set(content["properties"]), expected)

    def test_campaign_palette_empty_list_uses_runtime_auto_discovery_for_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            manifest_path = campaign / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["palettes"] = []
            write_yaml(manifest_path, manifest)
            palette_dir = campaign / "content" / "palettes"
            palette_dir.mkdir()
            (palette_dir / "bad.yaml").write_text("unexpected: []\n", encoding="utf-8")

            result = validate_campaign_package(campaign)

            self.assertFalse(result.ok)
            self.assertIn("content/palettes/bad.yaml.unexpected: unsupported palette key", result.errors)

    def test_content_sync_rejects_missing_registered_yaml_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_fixture(tmp)
            (campaign_path / "content" / "world_settings.yaml").write_text("rules: []\n", encoding="utf-8")
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            spec = get_default_registry().get("world_setting")

            with connect(campaign) as conn:
                validation = validate_content_sources(campaign, conn, [spec])
                self.assertFalse(validation.ok)
                self.assertIn("content/world_settings.yaml.world_settings: required", validation.errors)
                with self.assertRaisesRegex(ValueError, "content/world_settings.yaml.world_settings: required"):
                    sync_campaign_content(campaign, conn, type_names=["world_setting"])

    def test_content_source_validation_allows_same_source_clock_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_fixture(tmp)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            clocks_path = campaign_path / "content" / "clocks.yaml"
            clocks = load_yaml(clocks_path)
            clocks["clocks"].append(
                {
                    "id": "clock:source-test",
                    "name": "Source Test Clock",
                    "segments_total": 4,
                    "segments_filled": 0,
                    "trigger_when_full": "The source test clock completes.",
                }
            )
            write_yaml(clocks_path, clocks)
            settings_path = campaign_path / "content" / "world_settings.yaml"
            settings = load_yaml(settings_path)
            settings["world_settings"].append(
                {
                    "id": "world:source-test",
                    "name": "Source Test Setting",
                    "category": "truth",
                    "summary": "This setting links to a same-source clock.",
                    "linked_clocks": ["clock:source-test"],
                }
            )
            write_yaml(settings_path, settings)
            registry = get_default_registry()

            with connect(campaign) as conn:
                validation = validate_content_sources(
                    campaign,
                    conn,
                    [registry.get("clock"), registry.get("world_setting")],
                )

            self.assertTrue(validation.ok, validation.errors)

    def test_content_source_validation_rejects_relationship_details_endpoint_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_fixture(tmp)
            manifest_path = campaign_path / "campaign.yaml"
            manifest = load_yaml(manifest_path)
            manifest["content"]["relationships"] = ["content/relationships.yaml"]
            write_yaml(manifest_path, manifest)
            (campaign_path / "content" / "relationships.yaml").write_text(
                """
relationships:
  - id: rel:bad-details-ref
    name: Bad Details Ref
    visibility: known
    summary: Details endpoint must resolve.
    source_id: loc:start
    target_id: loc:start
    details:
      source_id: loc:missing
      target_id: loc:start
""".lstrip(),
                encoding="utf-8",
            )
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            spec = get_default_registry().get("relationship")

            with connect(campaign) as conn:
                validation = validate_content_sources(campaign, conn, [spec])
                self.assertFalse(validation.ok)
                self.assertIn("relationship[0].details.source_id: must match source_id loc:start", validation.errors)
                self.assertIn("relationship[0].details.source_id: missing entity loc:missing", validation.errors)
                with self.assertRaisesRegex(ValueError, "relationship\\[0\\].details.source_id: missing entity loc:missing"):
                    sync_campaign_content(campaign, conn, type_names=["relationship"], allow_unsafe=True)

    def test_campaign_validation_allows_world_setting_linked_entities_same_source_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = copy_fixture(tmp)
            settings_path = campaign / "content" / "world_settings.yaml"
            settings = load_yaml(settings_path)
            settings["world_settings"].extend(
                [
                    {
                        "id": "world:linked-a",
                        "name": "Linked A",
                        "category": "truth",
                        "summary": "Links to another same-source world setting.",
                        "linked_entities": ["world:linked-b"],
                    },
                    {
                        "id": "world:linked-b",
                        "name": "Linked B",
                        "category": "truth",
                        "summary": "Target world setting.",
                    },
                ]
            )
            write_yaml(settings_path, settings)

            result = validate_campaign_package(campaign)

            self.assertTrue(result.ok, result.errors)

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
