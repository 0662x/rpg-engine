from __future__ import annotations

import shutil
import json
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import yaml

from rpg_engine.campaign import load_campaign
from rpg_engine.content_types import ContentRuntime
from rpg_engine.content_types.world_setting import upsert_world_setting
from rpg_engine.db import connect, init_database, upsert_entity
from rpg_engine.packages.lock import build_package_lock
from rpg_engine.packages.service import apply_package_upgrade, diff_package_against_campaign, load_package_source


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def write_package(
    root: Path,
    entities_yaml: str,
    *,
    package_id: str = "package-fixture",
    version: str = "0.2.0",
    name: str = "Package Fixture",
    dirname: str = "package",
) -> Path:
    package = root / dirname
    (package / "content").mkdir(parents=True)
    (package / "campaign.yaml").write_text(
        textwrap.dedent(
            f"""
            id: {package_id}
            name: {name}
            package_version: "{version}"
            content_schema_version: "1"
            content:
              entities:
                - content/entities.yaml
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (package / "content" / "entities.yaml").write_text(textwrap.dedent(entities_yaml).strip() + "\n", encoding="utf-8")
    return package


class PackageCliTests(unittest.TestCase):
    def test_package_validate_accepts_existing_campaign_content_shape(self) -> None:
        result = run_cli("package", "validate", MINIMAL_FIXTURE)
        self.assertIn("OK", result.stdout)
        self.assertIn("package: minimal-campaign", result.stdout)
        self.assertIn("| `entity` | 2 |", result.stdout)

    def test_package_validate_rejects_unknown_content_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = write_package(
                Path(tmp),
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A room.
                """,
            )
            manifest_path = package / "campaign.yaml"
            manifest_path.write_text(
                manifest_path.read_text(encoding="utf-8")
                + "\n  characters:\n    - content/characters.yaml\n",
                encoding="utf-8",
            )
            (package / "content" / "characters.yaml").write_text("characters: []\n", encoding="utf-8")

            result = run_cli("package", "validate", package, check=False)

            self.assertEqual(result.returncode, 1)
            self.assertIn("manifest.content.characters: unsupported content key", result.stdout)

    def test_package_workflows_reject_invalid_content_contracts(self) -> None:
        cases = [
            ("unknown", "characters", "content/characters.yaml", "manifest.content.characters: unsupported content key"),
            ("absolute", "entities", "/tmp/entities.yaml", "manifest.content.entities: must use relative package path"),
            ("escape", "entities", "../outside/entities.yaml", "manifest.content.entities: path escapes package root"),
            ("dotdot", "entities", "content/../content/entities.yaml", "manifest.content.entities: path escapes package root"),
            ("tilde", "entities", "~/entities.yaml", "manifest.content.entities: must use relative package path"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            for name, key, value, expected in cases:
                with self.subTest(case=name):
                    package = write_package(
                        tmp_path,
                        """
                        entities:
                          - id: loc:start
                            type: location
                            name: Start
                            status: active
                            visibility: known
                            summary: A room.
                        """,
                        dirname=f"bad-{name}",
                    )
                    manifest_path = package / "campaign.yaml"
                    if key == "characters":
                        manifest_path.write_text(
                            manifest_path.read_text(encoding="utf-8")
                            + "\n  characters:\n    - content/characters.yaml\n",
                            encoding="utf-8",
                        )
                        (package / "content" / "characters.yaml").write_text("characters: []\n", encoding="utf-8")
                    else:
                        manifest = manifest_path.read_text(encoding="utf-8").replace(
                            "content/entities.yaml",
                            value,
                        )
                        manifest_path.write_text(manifest, encoding="utf-8")

                    for command in [
                        ("validate", package),
                        ("diff", campaign_path, package),
                        ("upgrade", campaign_path, package, "--dry-run"),
                    ]:
                        result = run_cli("package", *command, check=False)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn(expected, result.stdout)

    def test_package_workflows_reject_non_object_manifest_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A room.
                """,
            )
            manifest_path = package / "campaign.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["content"] = ["content/entities.yaml"]
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

            for command in [
                ("validate", package),
                ("diff", campaign_path, package),
                ("upgrade", campaign_path, package, "--dry-run"),
            ]:
                result = run_cli("package", *command, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("manifest.content must be object", result.stdout)

    def test_package_workflows_reject_invalid_registered_content_record_shape(self) -> None:
        cases = [
            ("missing-root", "rules: []\n", "entity content/entities.yaml: missing entities array"),
            ("non-list", "entities:\n  id: loc:start\n", "entity content/entities.yaml: entities must be array"),
            ("non-object-record", "entities:\n  - not-an-object\n", "entity content/entities.yaml[0]: record must be object"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            for name, content, expected in cases:
                with self.subTest(case=name):
                    package = write_package(
                        tmp_path,
                        """
                        entities:
                          - id: loc:start
                            type: location
                            name: Start
                            status: active
                            visibility: known
                            summary: A room.
                        """,
                        dirname=f"bad-record-shape-{name}",
                    )
                    (package / "content" / "entities.yaml").write_text(content, encoding="utf-8")

                    for command in [
                        ("validate", package),
                        ("diff", campaign_path, package),
                        ("upgrade", campaign_path, package, "--dry-run"),
                    ]:
                        result = run_cli("package", *command, check=False)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn(expected, result.stdout)

    def test_package_build_and_lock_include_auxiliary_content_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = tmp_path / "package"
            shutil.copytree(MINIMAL_FIXTURE, package)
            manifest_path = package / "campaign.yaml"
            manifest = manifest_path.read_text(encoding="utf-8")
            manifest = manifest.replace(
                "  world_settings:\n    - content/world_settings.yaml",
                "  world_settings:\n    - content/world_settings.yaml\n  palettes:\n    - content/palettes/test.yaml",
            )
            manifest_path.write_text(manifest, encoding="utf-8")
            (package / "content" / "palettes").mkdir()
            (package / "content" / "palettes" / "test.yaml").write_text(
                "palettes:\n  - id: palette:test\n    entries: []\n",
                encoding="utf-8",
            )
            archive = tmp_path / "package.zip"

            result = run_cli("package", "build", package, "--output", archive)

            self.assertIn("# Package Build", result.stdout)
            with zipfile.ZipFile(archive, "r") as package_zip:
                names = package_zip.namelist()
                self.assertIn("content/random_tables.yaml", names)
                self.assertIn("content/palettes/test.yaml", names)
                build_manifest = json.loads(package_zip.read("package-build.json"))
            file_paths = {item["path"] for item in build_manifest["files"]}
            self.assertIn("content/random_tables.yaml", file_paths)
            self.assertIn("content/palettes/test.yaml", file_paths)

    def test_package_build_and_lock_include_auto_discovered_palette_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = tmp_path / "package"
            shutil.copytree(MINIMAL_FIXTURE, package)
            (package / "content" / "palettes").mkdir()
            (package / "content" / "palettes" / "auto.yaml").write_text(
                "materials:\n  - id: mat:auto\n    name: Auto Material\n",
                encoding="utf-8",
            )
            archive = tmp_path / "package.zip"

            source = load_package_source(package)
            lock = build_package_lock(source)
            result = run_cli("package", "build", package, "--output", archive)

            self.assertIn("# Package Build", result.stdout)
            lock_paths = {item.path for item in lock.files}
            self.assertIn("content/palettes/auto.yaml", lock_paths)
            with zipfile.ZipFile(archive, "r") as package_zip:
                names = package_zip.namelist()
                self.assertIn("content/palettes/auto.yaml", names)
                build_manifest = json.loads(package_zip.read("package-build.json"))
            file_paths = {item["path"] for item in build_manifest["files"]}
            self.assertIn("content/palettes/auto.yaml", file_paths)

    def test_package_build_and_lock_treat_empty_palette_list_like_runtime_auto_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = tmp_path / "package"
            shutil.copytree(MINIMAL_FIXTURE, package)
            manifest_path = package / "campaign.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["content"]["palettes"] = []
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "content" / "palettes").mkdir()
            (package / "content" / "palettes" / "auto.yaml").write_text(
                "materials:\n  - id: mat:auto\n    name: Auto Material\n",
                encoding="utf-8",
            )

            source = load_package_source(package)
            lock = build_package_lock(source)

            self.assertIn("content/palettes/auto.yaml", {item.path for item in lock.files})

    def test_package_build_and_lock_preserve_manifest_path_for_in_root_content_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A room.
                """,
            )
            link_path = package / "content" / "entities-link.yaml"
            try:
                link_path.symlink_to(package / "content" / "entities.yaml")
            except OSError:
                self.skipTest("symlink creation is unavailable")
            manifest_path = package / "campaign.yaml"
            manifest = manifest_path.read_text(encoding="utf-8").replace(
                "content/entities.yaml",
                "content/entities-link.yaml",
            )
            manifest_path.write_text(manifest, encoding="utf-8")
            archive = tmp_path / "package.zip"

            source = load_package_source(package)
            lock = build_package_lock(source)
            run_cli("package", "build", package, "--output", archive)

            self.assertIn("content/entities-link.yaml", {item.path for item in lock.files})
            with zipfile.ZipFile(archive, "r") as package_zip:
                self.assertIn("content/entities-link.yaml", package_zip.namelist())

    def test_package_build_and_test_use_validated_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Revised
                    status: active
                    visibility: known
                    summary: Revised package-owned summary.
                    aliases: [starting room, revised start]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A revised quiet starting room.
                      exits: []
                      resources: []
                """,
            )
            archive = tmp_path / "package.zip"
            built = run_cli("package", "build", package, "--output", archive).stdout
            self.assertIn("# Package Build", built)
            self.assertTrue(archive.exists())
            with zipfile.ZipFile(archive, "r") as package_zip:
                self.assertIn("package-build.json", package_zip.namelist())
                self.assertIn("campaign.yaml", package_zip.namelist())
                self.assertIn("content/entities.yaml", package_zip.namelist())
            tested = run_cli("package", "test", package, "--campaign-dir", campaign_path).stdout
            self.assertIn("# Package Test", tested)
            self.assertIn("- status: `OK`", tested)
            self.assertIn("# Package Dry Run", tested)

    def test_package_diff_reports_create_and_update_without_mutating_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            before_turn = current_turn(campaign.database_path)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Revised
                    status: active
                    visibility: known
                    summary: Revised package-owned summary.
                    aliases: [starting room, revised start]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A revised quiet starting room.
                      exits: []
                      resources: []
                  - id: loc:added
                    type: location
                    name: Added Room
                    status: active
                    visibility: known
                    summary: A new package-authored room.
                    aliases: [added]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A new room.
                      exits: []
                      resources: []
                """,
            )
            result = run_cli("package", "diff", campaign_path, package)
            self.assertIn("- status: `OK`", result.stdout)
            self.assertIn("| `loc:start` | update | ok |", result.stdout)
            self.assertIn("| `loc:added` | create | ok |", result.stdout)
            self.assertEqual(current_turn(campaign.database_path), before_turn)

    def test_package_diff_uses_relationship_merge_policy_for_existing_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "rel:traveler-start",
                        "type": "relationship",
                        "name": "Traveler at Start",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Current relationship summary.",
                        "details": {
                            "source_id": "pc:traveler",
                            "target_id": "loc:start",
                            "state": "settled",
                            "trust": 7,
                            "stance": "cautious",
                            "notes": "Runtime notes.",
                        },
                    },
                )
                conn.commit()
            package = tmp_path / "relationship-package"
            (package / "content").mkdir(parents=True)
            (package / "campaign.yaml").write_text(
                textwrap.dedent(
                    """
                    id: relationship-package
                    name: Relationship Package
                    package_version: "0.2.0"
                    content_schema_version: "1"
                    content:
                      relationships:
                        - content/relationships.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "relationships.yaml").write_text(
                textwrap.dedent(
                    """
                    relationships:
                      - id: rel:traveler-start
                        name: Traveler at Start Revised
                        status: archived
                        visibility: hinted
                        summary: Package relationship summary.
                        source_id: pc:traveler
                        target_id: loc:start
                        state: encouraged
                        trust: 99
                        stance: friendly
                        notes: Package notes.
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            source = load_package_source(package)
            with connect(campaign) as conn:
                diff = diff_package_against_campaign(conn, source, target_name=campaign.name, campaign=campaign)

            relationship = diff.type_results[0].records[0]
            self.assertEqual(diff.type_results[0].content_type, "relationship")
            self.assertEqual(relationship.action, "update")
            self.assertEqual(relationship.merged["name"], "Traveler at Start Revised")
            self.assertEqual(relationship.merged["summary"], "Package relationship summary.")
            self.assertEqual(relationship.merged["trust"], 7)
            self.assertEqual(relationship.merged["status"], "active")

    def test_package_upgrade_dry_run_uses_same_diff_and_apply_requires_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Revised
                    status: active
                    visibility: known
                    summary: Revised package-owned summary.
                """,
            )
            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run")
            self.assertIn("# Package Dry Run", dry_run.stdout)
            blocked = run_cli("package", "upgrade", campaign_path, package, check=False)
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("package-lock.json is missing", blocked.stdout)

    def test_package_install_adopts_lock_without_mutating_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            before_turn = current_turn(campaign.database_path)
            before_name = entity_name(campaign.database_path, "loc:start")
            result = run_cli("package", "install", campaign_path, MINIMAL_FIXTURE, "--adopt-existing")
            self.assertIn("# Package Adoption", result.stdout)
            self.assertIn("- status: `OK`", result.stdout)
            self.assertIn("package-lock.json", result.stdout)
            self.assertTrue((campaign_path / "package-lock.json").exists())
            self.assertEqual(current_turn(campaign.database_path), before_turn)
            self.assertEqual(entity_name(campaign.database_path, "loc:start"), before_name)
            self.assertEqual(meta_value(campaign.database_path, "package_lock_fingerprint") != "", True)

    def test_package_install_creates_new_campaign_from_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "installed"
            result = run_cli("package", "install", target, MINIMAL_FIXTURE)
            self.assertIn("# Package Install", result.stdout)
            self.assertIn("- status: `OK`", result.stdout)
            self.assertTrue((target / "campaign.yaml").exists())
            self.assertTrue((target / "data" / "game.sqlite").exists())
            self.assertTrue((target / "package-lock.json").exists())
            check = run_cli("check", target)
            self.assertEqual(check.stdout.strip(), "OK")
            self.assertEqual(entity_name(target / "data" / "game.sqlite", "loc:start"), "Start")

    def test_package_install_adoption_rejects_drift_without_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Drift
                    status: active
                    visibility: known
                    summary: Drift must be reported before adoption.
                """,
            )
            result = run_cli("package", "install", campaign_path, package, "--adopt-existing", check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("# Package Adoption", result.stdout)
            self.assertIn("- status: `FAILED`", result.stdout)
            self.assertIn("drift_records", result.stdout)
            self.assertFalse((campaign_path / "package-lock.json").exists())

    def test_package_reconcile_reports_clean_adoption_without_writing_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = Path(tmp) / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            result = run_cli("package", "reconcile", campaign_path, MINIMAL_FIXTURE)
            self.assertIn("# Package Adoption", result.stdout)
            self.assertIn("- status: `OK`", result.stdout)
            self.assertIn("- adopted: `no`", result.stdout)
            self.assertFalse((campaign_path / "package-lock.json").exists())

    def test_package_upgrade_applies_conflict_free_changes_with_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            before_turn = current_turn(campaign.database_path)
            upgraded = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Revised
                    status: active
                    visibility: known
                    summary: Revised package-owned summary.
                    aliases: [starting room, revised start]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A revised quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="upgraded",
            )
            result = run_cli("package", "upgrade", campaign_path, upgraded)
            self.assertIn("# Package Apply", result.stdout)
            self.assertIn("- status: `OK`", result.stdout)
            self.assertIn("- backup: `backup-", result.stdout)
            self.assertIn("| `entity` | 1 |", result.stdout)
            self.assertNotEqual(current_turn(campaign.database_path), before_turn)
            self.assertEqual(entity_name(campaign.database_path, "loc:start"), "Start Revised")
            self.assertEqual(fts_title(campaign.database_path, "loc:start"), "Start Revised")
            lock_text = (campaign_path / "package-lock.json").read_text(encoding="utf-8")
            self.assertIn('"package_version": "0.2.0"', lock_text)
            self.assertIn('"package_lock_json"', sqlite_meta_dump(campaign.database_path))

    def test_package_upgrade_blocks_same_version_checksum_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            changed = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Same Version Drift
                    status: active
                    visibility: known
                    summary: Same version source changes must not apply.
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="changed",
            )
            result = run_cli("package", "upgrade", campaign_path, changed, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("package source checksum changed without package_version change", result.stdout)
            self.assertEqual(entity_name(campaign.database_path, "loc:start"), "Start")

    def test_package_migration_update_conflict_field_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    details:
                      lore: package-authored detail
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="upgraded",
            )
            (package / "migrations").mkdir()
            (package / "campaign.yaml").write_text(
                textwrap.dedent(
                    """
                    id: package-fixture
                    name: Package Fixture
                    package_version: "0.2.0"
                    content_schema_version: "1"
                    content:
                      entities:
                        - content/entities.yaml
                    migrations:
                      - migrations/001.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "migrations" / "001.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:001
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: update_conflict_field
                        content_type: entity
                        record_id: loc:start
                        field: details
                        reason: package owns this newly introduced details subtree
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            validate = run_cli("package", "validate", package)
            self.assertIn("OK", validate.stdout)
            result = run_cli("package", "upgrade", campaign_path, package)
            self.assertIn("# Package Apply", result.stdout)
            self.assertEqual(entity_details(campaign.database_path, "loc:start")["lore"], "package-authored detail")
            lock_text = (campaign_path / "package-lock.json").read_text(encoding="utf-8")
            self.assertIn('"path": "migrations/001.yaml"', lock_text)
            self.assertIn('"migration:001"', lock_text)
            self.assertIn("migration:001", sqlite_meta_dump(campaign.database_path))

            with connect(campaign) as conn:
                conn.execute(
                    "update entities set details_json = ? where id = 'loc:start'",
                    (json.dumps({"lore": "runtime changed"}),),
                )
                conn.commit()
            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run", check=False)
            self.assertEqual(dry_run.returncode, 1)
            self.assertIn("conflict `loc:start.details`", dry_run.stdout)
            blocked = run_cli("package", "upgrade", campaign_path, package, check=False)
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("conflict `loc:start.details`", blocked.stdout)
            self.assertEqual(entity_details(campaign.database_path, "loc:start")["lore"], "runtime changed")

    def test_package_upgrade_blocks_applied_migration_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    details:
                      lore: package-authored detail
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="upgraded",
            )
            add_conflict_migration(package, reason="first checksum")
            run_cli("package", "upgrade", campaign_path, package)
            package_v3 = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    details:
                      lore: package-authored detail
                """,
                package_id="package-fixture",
                version="0.3.0",
                dirname="v3",
            )
            add_conflict_migration(package_v3, reason="changed checksum")
            result = run_cli("package", "upgrade", campaign_path, package_v3, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("package migration checksum mismatch: migration:001", result.stdout)

    def test_package_migration_rename_entity_updates_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            with connect(campaign) as conn:
                conn.execute("update entities set status = 'retired' where id = 'loc:start'")
                upsert_entity(
                    conn,
                    {
                        "id": "rel:start-self",
                        "type": "relationship",
                        "name": "Start Self Link",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Relationship JSON should follow renames.",
                        "details": {
                            "source_id": "loc:start",
                            "target_id": "loc:start",
                            "state": "linked",
                            "history": ["loc:start"],
                        },
                    },
                )
                upsert_world_setting(
                    ContentRuntime(campaign=campaign, conn=conn, turn_id=current_turn(campaign.database_path), now="now"),
                    {
                        "id": "world:start-link",
                        "name": "Start Link",
                        "summary": "World setting links to the start location.",
                        "category": "truth",
                        "linked_entities": ["loc:start"],
                    },
                )
                conn.commit()
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:renamed-start
                    type: location
                    name: Renamed Start
                    status: active
                    visibility: known
                    summary: The same starting room after a package ID rename.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A renamed quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="upgraded",
            )
            (package / "migrations").mkdir()
            (package / "campaign.yaml").write_text(
                textwrap.dedent(
                    """
                    id: package-fixture
                    name: Package Fixture
                    package_version: "0.2.0"
                    content_schema_version: "1"
                    content:
                      entities:
                        - content/entities.yaml
                      routes:
                        - content/routes.yaml
                      relationships:
                        - content/relationships.yaml
                    migrations:
                      - migrations/rename.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "migrations" / "rename.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:rename-start
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: rename_entity
                        from: loc:start
                        to: loc:renamed-start
                        reason: stable package ID rename
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "routes.yaml").write_text(
                textwrap.dedent(
                    """
                    routes:
                      - id: route:renamed-loop
                        from_location_id: loc:renamed-start
                        to_location_id: loc:renamed-start
                        travel_minutes: 1
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "relationships.yaml").write_text(
                textwrap.dedent(
                    """
                    relationships:
                      - id: rel:start-self
                        name: Start Self Link
                        status: active
                        visibility: known
                        summary: Relationship JSON should follow renames.
                        source_id: loc:renamed-start
                        target_id: loc:renamed-start
                        state: linked
                        details:
                          source_id: loc:renamed-start
                          target_id: loc:renamed-start
                          state: linked
                          history:
                            - loc:renamed-start
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run")
            self.assertIn("pending migration migration:rename-start: rename_entity loc:start -> loc:renamed-start", dry_run.stdout)
            self.assertIn("| `loc:renamed-start` | update | ok |", dry_run.stdout)
            self.assertNotIn("| `loc:renamed-start` | create | ok |", dry_run.stdout)
            self.assertNotIn("missing location loc:renamed-start", dry_run.stdout)
            result = run_cli("package", "upgrade", campaign_path, package)
            self.assertIn("# Package Apply", result.stdout)
            self.assertFalse(entity_exists(campaign.database_path, "loc:start"))
            self.assertTrue(entity_exists(campaign.database_path, "loc:renamed-start"))
            self.assertEqual(entity_status(campaign.database_path, "loc:renamed-start"), "retired")
            self.assertEqual(entity_location(campaign.database_path, "pc:traveler"), "loc:renamed-start")
            self.assertEqual(meta_value(campaign.database_path, "current_location_id"), "loc:renamed-start")
            self.assertEqual(relationship_details(campaign.database_path, "rel:start-self")["source_id"], "loc:renamed-start")
            self.assertEqual(relationship_details(campaign.database_path, "rel:start-self")["target_id"], "loc:renamed-start")
            self.assertEqual(relationship_details(campaign.database_path, "rel:start-self")["history"], ["loc:renamed-start"])
            self.assertEqual(world_setting_linked_entities(campaign.database_path, "world:start-link"), ["loc:renamed-start"])

    def test_pending_delete_record_migration_is_preflighted_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="delete-package",
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["migrations"] = ["migrations/delete.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "migrations" / "delete.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:delete-start
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: delete_record
                        content_type: entity
                        record_id: loc:start
                        reason: exercise migration preflight
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run", check=False)

            self.assertEqual(dry_run.returncode, 1)
            self.assertIn("pending migration migration:delete-start: delete_record entity.loc:start", dry_run.stdout)
            self.assertIn("pending migration preflight failed: foreign key constraint failed", dry_run.stdout)

    def test_package_relationship_refs_are_validated_after_pending_renames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:renamed-start
                    type: location
                    name: Renamed Start
                    status: active
                    visibility: known
                    summary: The renamed location.
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="bad-relationship-ref",
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["content"]["relationships"] = ["content/relationships.yaml"]
            manifest["migrations"] = ["migrations/rename.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "content" / "relationships.yaml").write_text(
                textwrap.dedent(
                    """
                    relationships:
                      - id: rel:bad-old-ref
                        name: Bad Old Ref
                        visibility: known
                        summary: This package still points at the old id.
                        source_id: loc:start
                        target_id: loc:renamed-start
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "migrations" / "rename.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:rename-start
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: rename_entity
                        from: loc:start
                        to: loc:renamed-start
                        reason: stable package ID rename
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run", check=False)

            self.assertEqual(dry_run.returncode, 1)
            self.assertIn("database-ref.relationship[0].source_id: missing entity loc:start", dry_run.stdout)

    def test_package_relationship_refs_reject_same_package_non_entity_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A starting room.
                """,
                dirname="bad-route-relationship-ref",
            )
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["content"]["routes"] = ["content/routes.yaml"]
            manifest["content"]["relationships"] = ["content/relationships.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "content" / "routes.yaml").write_text(
                textwrap.dedent(
                    """
                    routes:
                      - id: route:loop
                        from_location_id: loc:start
                        to_location_id: loc:start
                        travel_minutes: 1
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "relationships.yaml").write_text(
                textwrap.dedent(
                    """
                    relationships:
                      - id: rel:route-start
                        name: Route Start
                        visibility: known
                        summary: A route is not a relationship endpoint entity.
                        source_id: route:loop
                        target_id: loc:start
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run", check=False)

            self.assertEqual(dry_run.returncode, 1)
            self.assertIn("database-ref.relationship[0].source_id: missing entity route:loop", dry_run.stdout)

    def test_package_relationship_refs_validate_details_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A starting room.
                """,
                dirname="bad-relationship-details-ref",
            )
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["content"]["relationships"] = ["content/relationships.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "content" / "relationships.yaml").write_text(
                textwrap.dedent(
                    """
                    relationships:
                      - id: rel:details-mismatch
                        name: Details Mismatch
                        visibility: known
                        summary: Details endpoint must agree with top-level endpoint.
                        source_id: loc:start
                        target_id: loc:start
                        details:
                          source_id: loc:missing
                          target_id: loc:start
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run", check=False)

            self.assertEqual(dry_run.returncode, 1)
            self.assertIn("database-ref.relationship[0].details.source_id: must match source_id loc:start", dry_run.stdout)
            self.assertIn("database-ref.relationship[0].details.source_id: missing entity loc:missing", dry_run.stdout)

    def test_relationship_only_package_still_validates_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = tmp_path / "relationship-only"
            (package / "content").mkdir(parents=True)
            (package / "campaign.yaml").write_text(
                textwrap.dedent(
                    """
                    id: relationship-only
                    name: Relationship Only
                    package_version: "0.2.0"
                    content_schema_version: "1"
                    content:
                      relationships:
                        - content/relationships.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "relationships.yaml").write_text(
                textwrap.dedent(
                    """
                    relationships:
                      - id: rel:relationship-only
                        name: Relationship Only
                        visibility: known
                        summary: Relationship-only packages still need endpoint checks.
                        source_id: loc:start
                        target_id: loc:start
                        details:
                          source_id: loc:missing
                          target_id: loc:start
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run", check=False)

            self.assertEqual(dry_run.returncode, 1)
            self.assertIn("database-ref.relationship[0].details.source_id: must match source_id loc:start", dry_run.stdout)
            self.assertIn("database-ref.relationship[0].details.source_id: missing entity loc:missing", dry_run.stdout)

    def test_package_db_refs_include_same_package_clock_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = tmp_path / "clock-world"
            (package / "content").mkdir(parents=True)
            (package / "campaign.yaml").write_text(
                textwrap.dedent(
                    """
                    id: clock-world
                    name: Clock World
                    package_version: "0.2.0"
                    content_schema_version: "1"
                    content:
                      clocks:
                        - content/clocks.yaml
                      world_settings:
                        - content/world_settings.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "clocks.yaml").write_text(
                textwrap.dedent(
                    """
                    clocks:
                      - id: clock:package-test
                        name: Package Test Clock
                        segments_total: 4
                        segments_filled: 0
                        trigger_when_full: The package clock completes.
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "content" / "world_settings.yaml").write_text(
                textwrap.dedent(
                    """
                    world_settings:
                      - id: world:package-test
                        name: Package Test Setting
                        category: truth
                        summary: This setting links to a same-package clock.
                        linked_clocks:
                          - clock:package-test
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            dry_run = run_cli("package", "upgrade", campaign_path, package, "--dry-run")

            self.assertIn("- status: `OK`", dry_run.stdout)
            self.assertNotIn("missing clock clock:package-test", dry_run.stdout)

    def test_pending_migration_source_ids_cannot_reappear_in_package_content(self) -> None:
        cases = [
            (
                "rename",
                "rename-package",
                "loc:start",
                """
                id: migration:rename-start
                from_package_version: "0.1.0"
                to_package_version: "0.2.0"
                operations:
                  - type: rename_entity
                    from: loc:start
                    to: loc:renamed-start
                    reason: old id must not be recreated by package content
                """,
                "rename_entity source id loc:start also appears in package content",
            ),
            (
                "delete",
                "delete-package",
                "loc:start",
                """
                id: migration:delete-start
                from_package_version: "0.1.0"
                to_package_version: "0.2.0"
                operations:
                  - type: delete_record
                    content_type: entity
                    record_id: loc:start
                    reason: deleted id must not be recreated by package content
                """,
                "delete_record collides with package content entity.loc:start",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, dirname, record_id, migration_yaml, expected in cases:
                with self.subTest(case=name):
                    package = write_package(
                        tmp_path,
                        f"""
                        entities:
                          - id: {record_id}
                            type: location
                            name: Start
                            status: active
                            visibility: known
                            summary: A starting room.
                        """,
                        version="0.2.0",
                        dirname=dirname,
                    )
                    (package / "migrations").mkdir()
                    manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
                    manifest["migrations"] = ["migrations/change.yaml"]
                    (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
                    (package / "migrations" / "change.yaml").write_text(
                        textwrap.dedent(migration_yaml).strip() + "\n",
                        encoding="utf-8",
                    )

                    result = run_cli("package", "validate", package, check=False)

                    self.assertEqual(result.returncode, 1)
                    self.assertIn(expected, result.stdout)

    def test_pending_delete_record_entity_collision_checks_entity_backed_roots(self) -> None:
        cases = [
            (
                "clock",
                "clocks",
                "content/clocks.yaml",
                """
                clocks:
                  - id: clock:test
                    name: Test Clock
                    segments_total: 4
                    segments_filled: 0
                    trigger_when_full: Something happens.
                """,
                "clock:test",
            ),
            (
                "relationship",
                "relationships",
                "content/relationships.yaml",
                """
                relationships:
                  - id: rel:test
                    name: Test Relationship
                    summary: A relationship backed by the entities table.
                    source_id: loc:start
                    target_id: loc:start
                """,
                "rel:test",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, content_key, content_path, content_yaml, record_id in cases:
                with self.subTest(case=name):
                    package = write_package(
                        tmp_path,
                        """
                        entities:
                          - id: loc:start
                            type: location
                            name: Start
                            status: active
                            visibility: known
                            summary: A starting room.
                        """,
                        version="0.2.0",
                        dirname=f"delete-entity-backed-{name}",
                    )
                    (package / "migrations").mkdir()
                    manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
                    manifest["content"][content_key] = [content_path]
                    manifest["migrations"] = ["migrations/delete.yaml"]
                    (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
                    (package / content_path).write_text(textwrap.dedent(content_yaml).strip() + "\n", encoding="utf-8")
                    (package / "migrations" / "delete.yaml").write_text(
                        textwrap.dedent(
                            f"""
                            id: migration:delete-{name}
                            from_package_version: "0.1.0"
                            to_package_version: "0.2.0"
                            operations:
                              - type: delete_record
                                content_type: entity
                                record_id: {record_id}
                                reason: deleted entity-backed id must not reappear in package content
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )

                    result = run_cli("package", "validate", package, check=False)

                    self.assertEqual(result.returncode, 1)
                    self.assertIn(f"delete_record collides with package content entity.{record_id}", result.stdout)

    def test_package_validate_rejects_invalid_update_conflict_field_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A starting room.
                """,
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["migrations"] = ["migrations/bad-values.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "migrations" / "bad-values.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:bad-values
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: update_conflict_field
                        content_type: entity
                        record_id: loc:start
                        field: type
                        value: impossible_type
                        reason: invalid entity type must be rejected
                      - type: update_conflict_field
                        content_type: entity
                        record_id: loc:start
                        field: details
                        value: not-an-object
                        reason: details must remain structured
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = run_cli("package", "validate", package, check=False)

            self.assertEqual(result.returncode, 1)
            self.assertIn("value: unsupported entity type impossible_type", result.stdout)
            self.assertIn("value: entity.details must be object or null", result.stdout)

    def test_update_conflict_field_explicit_value_must_match_package_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: equipment
                    name: Start
                    status: active
                    visibility: known
                    summary: Reclassification disagrees with migration value.
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="bad-value-mismatch",
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["migrations"] = ["migrations/type.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "migrations" / "type.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:type
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: update_conflict_field
                        content_type: entity
                        record_id: loc:start
                        field: type
                        value: material
                        reason: explicit value must match package content
                      - type: update_conflict_field
                        content_type: entity
                        record_id: loc:missing
                        field: type
                        value: material
                        reason: explicit value requires matching package record
                      - type: update_conflict_field
                        content_type: entity
                        record_id: loc:start
                        field: details
                        value:
                          lore: expected
                        reason: explicit value requires matching package field
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = run_cli("package", "validate", package, check=False)

            self.assertEqual(result.returncode, 1)
            self.assertIn("value: must match package content entity.loc:start.type", result.stdout)
            self.assertIn("value: explicit update_conflict_field value requires package content entity.loc:missing", result.stdout)
            self.assertIn("value: explicit update_conflict_field value requires package content entity.loc:start.details", result.stdout)

    def test_pending_migration_preflight_preserves_defer_foreign_keys_pragma(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:renamed-start
                    type: location
                    name: Renamed Start
                    status: active
                    visibility: known
                    summary: The renamed starting room.
                """,
                version="0.2.0",
                dirname="pragma-preserved",
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["migrations"] = ["migrations/rename.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "migrations" / "rename.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:rename-start
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: rename_entity
                        from: loc:start
                        to: loc:renamed-start
                        reason: exercise dry-run preflight
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            source = load_package_source(package)

            with connect(campaign) as conn:
                conn.execute("pragma defer_foreign_keys = on")
                self.assertEqual(conn.execute("pragma defer_foreign_keys").fetchone()[0], 1)
                diff = diff_package_against_campaign(conn, source, target_name=campaign.name, campaign=campaign)

                self.assertTrue(diff.ok, diff.validation.errors)
                self.assertEqual(conn.execute("pragma defer_foreign_keys").fetchone()[0], 1)

    def test_package_lock_projection_repair_recovers_after_lock_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            baseline = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A quiet starting room used by the generic campaign fixture.
                    aliases: [starting room]
                    location:
                      biome: interior
                      safety_level: safe
                      description_short: A quiet starting room.
                      exits: []
                      resources: []
                """,
                package_id="package-fixture",
                version="0.1.0",
                dirname="baseline",
            )
            run_cli("package", "install", campaign_path, baseline, "--adopt-existing")
            upgraded = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start Recovered
                    status: active
                    visibility: known
                    summary: Upgrade should survive lock projection failure.
                """,
                package_id="package-fixture",
                version="0.2.0",
                dirname="upgraded",
            )
            with patch("rpg_engine.packages.lock.write_package_lock", side_effect=OSError("disk full")):
                with connect(campaign) as conn:
                    with self.assertRaises(OSError):
                        apply_package_upgrade(campaign, conn, load_package_source(upgraded))
            self.assertEqual(entity_name(campaign.database_path, "loc:start"), "Start Recovered")
            self.assertIn('"package_version": "0.2.0"', meta_value(campaign.database_path, "package_lock_json"))
            self.assertEqual(projection_status(campaign.database_path, "package_lock"), "failed")
            self.assertIn('"package_version": "0.1.0"', (campaign_path / "package-lock.json").read_text(encoding="utf-8"))
            repair = run_cli("projection", "repair", campaign_path, "--name", "package_lock", "--all")
            self.assertIn("OK", repair.stdout)
            self.assertEqual(projection_status(campaign.database_path, "package_lock"), "clean")
            self.assertIn('"package_version": "0.2.0"', (campaign_path / "package-lock.json").read_text(encoding="utf-8"))

    def test_package_validate_rejects_bad_migration_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: location
                    name: Start
                    status: active
                    visibility: known
                    summary: A room.
                """,
            )
            (package / "migrations").mkdir()
            (package / "campaign.yaml").write_text(
                textwrap.dedent(
                    """
                    id: package-fixture
                    name: Package Fixture
                    package_version: "0.2.0"
                    content_schema_version: "1"
                    content:
                      entities:
                        - content/entities.yaml
                    migrations:
                      - migrations/bad.yaml
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "migrations" / "bad.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:bad
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: arbitrary_sql
                      - type: update_conflict_field
                        content_type: relationship
                        record_id: rel:test
                        field: details
                        reason: unsupported conflict field
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            result = run_cli("package", "validate", package, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unsupported operation arbitrary_sql", result.stdout)
            self.assertIn("reason: required", result.stdout)
            self.assertIn("update_conflict_field unsupported field relationship.details", result.stdout)

    def test_package_workflows_reject_invalid_migration_manifest_paths(self) -> None:
        cases = [
            ("dotdot", "migrations/../migrations/001.yaml", "package migration path escapes package root"),
            ("tilde", "~/migrations/001.yaml", "package migration paths must be relative"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, migration_path, expected in cases:
                with self.subTest(case=name):
                    package = write_package(
                        tmp_path,
                        """
                        entities:
                          - id: loc:start
                            type: location
                            name: Start
                            status: active
                            visibility: known
                            summary: A room.
                        """,
                        dirname=f"bad-migration-path-{name}",
                    )
                    (package / "migrations").mkdir()
                    (package / "migrations" / "001.yaml").write_text(
                        textwrap.dedent(
                            """
                            id: migration:001
                            from_package_version: "0.1.0"
                            to_package_version: "0.2.0"
                            operations:
                              - type: rename_alias
                                entity_id: loc:start
                                from: old
                                to: new
                                reason: test path guard
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )
                    manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
                    manifest["migrations"] = [migration_path]
                    (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

                    for command in [
                        ("validate", package),
                        ("build", package, "--output", tmp_path / f"{name}.zip"),
                    ]:
                        result = run_cli("package", *command, check=False)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn(expected, result.stdout)

    def test_package_validate_rejects_pending_rename_chains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:final-start
                    type: location
                    name: Final Start
                    status: active
                    visibility: known
                    summary: A chained rename target.
                """,
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["migrations"] = ["migrations/one.yaml", "migrations/two.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "migrations" / "one.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:one
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: rename_entity
                        from: loc:start
                        to: loc:middle-start
                        reason: first hop
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            (package / "migrations" / "two.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:two
                    from_package_version: "0.2.0"
                    to_package_version: "0.3.0"
                    operations:
                      - type: rename_entity
                        from: loc:middle-start
                        to: loc:final-start
                        reason: second hop
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = run_cli("package", "validate", package, check=False)

            self.assertEqual(result.returncode, 1)
            self.assertIn("rename_entity chains are not supported for loc:middle-start", result.stdout)

    def test_package_validate_rejects_duplicate_rename_sources_and_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:a
                    type: location
                    name: A
                    status: active
                    visibility: known
                    summary: First target.
                  - id: loc:b
                    type: location
                    name: B
                    status: active
                    visibility: known
                    summary: Second target.
                """,
                dirname="duplicate-renames",
            )
            (package / "migrations").mkdir()
            manifest = yaml.safe_load((package / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["migrations"] = ["migrations/duplicate.yaml"]
            (package / "campaign.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (package / "migrations" / "duplicate.yaml").write_text(
                textwrap.dedent(
                    """
                    id: migration:duplicate-renames
                    from_package_version: "0.1.0"
                    to_package_version: "0.2.0"
                    operations:
                      - type: rename_entity
                        from: loc:start
                        to: loc:a
                        reason: first rename source
                      - type: rename_entity
                        from: loc:start
                        to: loc:b
                        reason: duplicate rename source
                      - type: rename_entity
                        from: loc:other
                        to: loc:b
                        reason: duplicate rename target
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = run_cli("package", "validate", package, check=False)

            self.assertEqual(result.returncode, 1)
            self.assertIn("duplicate rename_entity source loc:start", result.stdout)
            self.assertIn("duplicate rename_entity target loc:b", result.stdout)

    def test_package_diff_reports_conflict_only_field_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            campaign_path = tmp_path / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_path)
            campaign = load_campaign(campaign_path)
            init_database(campaign, force=True)
            package = write_package(
                tmp_path,
                """
                entities:
                  - id: loc:start
                    type: material
                    name: Start Reclassified
                    status: active
                    visibility: known
                    summary: Illegal reclassification must require migration.
                """,
            )
            result = run_cli("package", "diff", campaign_path, package, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("- status: `FAILED`", result.stdout)
            self.assertIn("conflict `loc:start.type`", result.stdout)
            self.assertIn("explicit migration", result.stdout)


def current_turn(database_path: Path) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select value from meta where key='current_turn_id'").fetchone()
        return str(row[0])
    finally:
        conn.close()


def entity_name(database_path: Path, entity_id: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select name from entities where id=?", (entity_id,)).fetchone()
        return str(row[0])
    finally:
        conn.close()


def fts_title(database_path: Path, entity_id: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select title from fts_index where entity_id=?", (entity_id,)).fetchone()
        return str(row[0])
    finally:
        conn.close()


def entity_details(database_path: Path, entity_id: str) -> dict[str, object]:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select details_json from entities where id=?", (entity_id,)).fetchone()
        return json.loads(str(row[0])) if row else {}
    finally:
        conn.close()


def relationship_details(database_path: Path, entity_id: str) -> dict[str, object]:
    return entity_details(database_path, entity_id)


def world_setting_linked_entities(database_path: Path, entity_id: str) -> list[str]:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select linked_entities_json from world_settings where entity_id=?", (entity_id,)).fetchone()
        value = json.loads(str(row[0])) if row else []
        return [str(item) for item in value] if isinstance(value, list) else []
    finally:
        conn.close()


def add_conflict_migration(package: Path, *, reason: str) -> None:
    (package / "migrations").mkdir()
    (package / "campaign.yaml").write_text(
        textwrap.dedent(
            """
            id: package-fixture
            name: Package Fixture
            package_version: "__VERSION__"
            content_schema_version: "1"
            content:
              entities:
                - content/entities.yaml
            migrations:
              - migrations/001.yaml
            """
        )
        .strip()
        .replace("__VERSION__", package_version(package))
        + "\n",
        encoding="utf-8",
    )
    (package / "migrations" / "001.yaml").write_text(
        textwrap.dedent(
            f"""
            id: migration:001
            from_package_version: "0.1.0"
            to_package_version: "{package_version(package)}"
            operations:
              - type: update_conflict_field
                content_type: entity
                record_id: loc:start
                field: details
                reason: {reason}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def package_version(package: Path) -> str:
    text = (package / "campaign.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("package_version:"):
            return line.split(":", 1)[1].strip().strip('"')
    return "0.1.0"


def sqlite_meta_dump(database_path: Path) -> str:
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute("select key, value from meta order by key").fetchall()
        return json.dumps({key: value for key, value in rows}, ensure_ascii=False, sort_keys=True)
    finally:
        conn.close()


def projection_status(database_path: Path, name: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select status from projection_state where name=?", (name,)).fetchone()
        return str(row[0]) if row else ""
    finally:
        conn.close()


def entity_exists(database_path: Path, entity_id: str) -> bool:
    conn = sqlite3.connect(database_path)
    try:
        return conn.execute("select 1 from entities where id=?", (entity_id,)).fetchone() is not None
    finally:
        conn.close()


def entity_location(database_path: Path, entity_id: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select location_id from entities where id=?", (entity_id,)).fetchone()
        return "" if row is None else str(row[0])
    finally:
        conn.close()


def entity_status(database_path: Path, entity_id: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select status from entities where id=?", (entity_id,)).fetchone()
        return "" if row is None else str(row[0])
    finally:
        conn.close()


def meta_value(database_path: Path, key: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select value from meta where key=?", (key,)).fetchone()
        return "" if row is None else str(row[0])
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
