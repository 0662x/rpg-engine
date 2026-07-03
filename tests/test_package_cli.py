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

from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, init_database
from rpg_engine.packages.service import apply_package_upgrade, load_package_source


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
            result = run_cli("package", "upgrade", campaign_path, package)
            self.assertIn("# Package Apply", result.stdout)
            self.assertFalse(entity_exists(campaign.database_path, "loc:start"))
            self.assertTrue(entity_exists(campaign.database_path, "loc:renamed-start"))
            self.assertEqual(entity_location(campaign.database_path, "pc:traveler"), "loc:renamed-start")
            self.assertEqual(meta_value(campaign.database_path, "current_location_id"), "loc:renamed-start")

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
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            result = run_cli("package", "validate", package, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("unsupported operation arbitrary_sql", result.stdout)
            self.assertIn("reason: required", result.stdout)

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


def meta_value(database_path: Path, key: str) -> str:
    conn = sqlite3.connect(database_path)
    try:
        row = conn.execute("select value from meta where key=?", (key,)).fetchone()
        return "" if row is None else str(row[0])
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
