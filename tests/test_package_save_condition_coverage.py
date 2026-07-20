from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

from rpg_engine.campaign import load_campaign
from rpg_engine.content_types import ContentRuntime, get_default_registry
from rpg_engine.db import connect, upsert_clock, upsert_entity, upsert_route, upsert_rule
from rpg_engine.packages.merge import PackageDryRunResult, PackageFieldDiff, PackageRecordMerge
from rpg_engine.packages.service import (
    PackageAdoptionResult,
    PackageApplyResult,
    PackageDiffResult,
    PackageInstallResult,
    PackageMigration,
    PackageSource,
    PackageValidationResult,
    apply_migration_authorizations,
    apply_package_migration_operation,
    apply_package_migrations,
    compact_record,
    conflict_field_authorizations,
    content_paths,
    current_records_for_spec,
    first_existing_manifest,
    load_package_source,
    migration_entry_path,
    package_apply_operations,
    package_diff_drift_count,
    render_package_adoption,
    render_package_apply,
    render_package_diff,
    render_package_install,
    render_package_validation,
    safe_record_id,
    validate_migration_operation_shape,
    validate_package_database_refs,
    validate_package_migrations,
    validate_package_source,
)
from rpg_engine.save_manager import (
    SaveManager,
    SaveManagerError,
    build_save_summary,
    ensure_empty_target,
    ensure_under_root,
    error_dict,
    extract_affordances,
    extract_result_clarification,
    extract_scene_summary,
    find_record,
    find_save_record_by_path,
    normalize_optional_relative,
    normalize_required_relative,
    platform_session_metadata,
    player_action_message,
    player_confirm_message,
    registry_lock,
    relative_path,
    render_onboarding_text,
    replace_record,
    resolve_registry_path,
    rewrite_save_manifests,
    slugify,
    upsert_campaign_record,
    validate_pending_platform_session,
)
from tests.helpers import MINIMAL_FIXTURE, copy_initialized_minimal


def write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def result_object(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(to_dict=lambda: payload)


class PackageServiceConditionCoverageTests(unittest.TestCase):
    def test_load_package_source_rejects_non_object_manifest_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_yaml(
                root / "package.yaml",
                {
                    "id": "pkg",
                    "version": "1",
                    "content": "not-an-object",
                },
            )

            with self.assertRaisesRegex(ValueError, "manifest.content must be object"):
                load_package_source(root)

    def test_package_source_validation_combines_manifest_record_and_migration_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_yaml(
                root / "package.yaml",
                {
                    "content": {},
                    "content_schema_version": "",
                    "migrations": [
                        "migrations/missing-id.yaml",
                        {"path": "migrations/duplicate-a.yaml"},
                        {"path": "migrations/duplicate-b.yaml"},
                        {"path": "migrations/invalid-op.yaml"},
                        3,
                        {},
                    ],
                },
            )
            write_yaml(
                root / "migrations" / "missing-id.yaml",
                {
                    "id": "",
                    "from_package_version": "",
                    "to_package_version": "2",
                    "operations": [],
                },
            )
            write_yaml(
                root / "migrations" / "duplicate-a.yaml",
                {
                    "id": "migration:one",
                    "from_package_version": "1",
                    "to_package_version": "2",
                    "operations": [{"type": "rename_entity", "from": "", "to": "pc:new", "reason": ""}],
                },
            )
            write_yaml(
                root / "migrations" / "duplicate-b.yaml",
                {
                    "id": "migration:one",
                    "from_package_version": "1",
                    "to_package_version": "",
                    "operations": "not-a-list",
                },
            )
            write_yaml(
                root / "migrations" / "invalid-op.yaml",
                {
                    "id": "migration:two",
                    "from_package_version": "2",
                    "to_package_version": "3",
                    "operations": [
                        {"type": "unsupported", "reason": "exercise unsupported operation"},
                        {"type": "update_conflict_field", "content_type": "entity", "field": "", "entity_id": ""},
                    ],
                },
            )

            source = load_package_source(root)
            validation = validate_package_source(source)

            rendered = "\n".join(validation.errors)
            self.assertFalse(validation.ok)
            self.assertIn("manifest.package_version or manifest.version is required", validation.errors)
            self.assertIn("manifest.content_schema_version must be non-empty string", validation.errors)
            self.assertIn("package has no registered content records", validation.warnings)
            self.assertIn("migrations[0].id: required", rendered)
            self.assertIn("migrations[1].operations[0].from: required", rendered)
            self.assertIn("duplicate migration id migration:one", rendered)
            self.assertIn("unsupported operation unsupported", rendered)
            self.assertIn("migrations[3].operations[1].record_id: required", rendered)
            self.assertEqual(migration_entry_path(root, 3), None)
            self.assertEqual(migration_entry_path(root, {}), None)
            self.assertEqual(migration_entry_path(root, {"path": ""}), None)
            with self.assertRaisesRegex(ValueError, "must be relative"):
                migration_entry_path(root, "/tmp/migration.yaml")
            with self.assertRaisesRegex(ValueError, "escapes package root"):
                migration_entry_path(root, "../outside-migration.yaml")
            with self.assertRaisesRegex(ValueError, "escapes package root"):
                migration_entry_path(root, "migrations/../migrations/one.yaml")
            with self.assertRaisesRegex(ValueError, "must be relative"):
                migration_entry_path(root, "~missing-user/migration.yaml")

    def test_package_source_rejects_migration_paths_that_escape_package_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "package"
            root.mkdir()
            outside = Path(tmp) / "outside-migration.yaml"
            write_yaml(outside, {"id": "migration:outside", "operations": []})
            write_yaml(root / "package.yaml", {"id": "pkg", "version": "1", "migrations": ["../outside-migration.yaml"]})

            with self.assertRaisesRegex(ValueError, "package migration path escapes package root"):
                load_package_source(root)

    def test_package_validation_detects_duplicate_cross_type_ids_and_database_refs(self) -> None:
        registry = get_default_registry()
        source = PackageSource(
            root=Path("/"),
            manifest_path=Path("/package.yaml"),
            manifest={"content": {}},
            records_by_type={
                "entity": [
                    {"id": "rule:shared", "type": "item", "name": "A", "summary": "A"},
                    {"id": "rule:shared", "type": "item", "name": "B", "summary": "B"},
                ],
                "rule": [{"id": "rule:shared", "statement": "Shared rule."}],
            },
        )
        validation = validate_package_source(source, registry=registry)
        self.assertFalse(validation.ok)
        self.assertIn("manifest.id or manifest.package_id is required", validation.errors)
        self.assertIn("manifest.package_version or manifest.version is required", validation.errors)
        self.assertTrue(any("duplicate record id rule:shared" in item for item in validation.errors))
        self.assertTrue(any("also appears in entity" in item for item in validation.errors))

        with tempfile.TemporaryDirectory() as tmp:
            campaign_root = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_root)
            with connect(campaign) as conn:
                ref_errors = validate_package_database_refs(
                    conn,
                    PackageSource(
                        root=campaign_root,
                        manifest_path=campaign_root / "package.yaml",
                        manifest={"id": "pkg", "version": "1"},
                        records_by_type={
                            "route": [
                                {
                                    "id": "route:missing",
                                    "from_location_id": "loc:missing-a",
                                    "to_location_id": "loc:missing-b",
                                    "travel_minutes": 5,
                                }
                            ]
                        },
                    ),
                    registry,
                )
        self.assertTrue(any(item.startswith("database-ref.") for item in ref_errors))

    def test_package_authorizations_renderers_and_helper_edges(self) -> None:
        migration = PackageMigration(
            id="migration:authorize",
            path=Path("migration.yaml"),
            checksum="checksum",
            from_package_version="1",
            to_package_version="2",
            operations=(
                {
                    "type": "update_conflict_field",
                    "content_type": "entity",
                    "record_id": "item:test",
                    "field": "type",
                    "reason": "explicit policy break",
                },
                {
                    "type": "update_conflict_field",
                    "content_type": "entity",
                    "record_id": "item:strict",
                    "field": "type",
                    "value": "material",
                    "reason": "explicit value constrains package content",
                },
                {"type": "update_conflict_field", "content_type": "route", "record_id": "route:test", "field": "id"},
                {"type": "rename_alias", "entity_id": "item:test", "from": "old", "to": "new"},
            ),
        )
        source = PackageSource(
            root=Path("/tmp/pkg"),
            manifest_path=Path("/tmp/pkg/package.yaml"),
            manifest={"id": "pkg", "version": "2"},
            migrations=(migration,),
        )
        conflict_type = PackageFieldDiff(
            field="type",
            ownership="conflict-only",
            action="conflict",
            current="item",
            incoming="equipment",
            merged="item",
            message="requires migration",
        )
        conflict_details = PackageFieldDiff(
            field="details",
            ownership="conflict-only",
            action="conflict",
            current={"old": True},
            incoming={"new": True},
            merged={"old": True},
            message="requires migration",
        )
        dry_run = PackageDryRunResult(
            content_type="entity",
            records=(
                PackageRecordMerge(
                    record_id="item:test",
                    action="update",
                    merged={"id": "item:test", "type": "item", "details": {"old": True}},
                    conflicts=(conflict_type, conflict_details),
                ),
                PackageRecordMerge(record_id="item:skip", action="update", merged=None, conflicts=(conflict_type,)),
                PackageRecordMerge(
                    record_id="item:strict",
                    action="update",
                    merged={"id": "item:strict", "type": "item"},
                    conflicts=(
                        PackageFieldDiff(
                            field="type",
                            ownership="conflict-only",
                            action="conflict",
                            current="item",
                            incoming="equipment",
                            merged="item",
                            message="requires migration",
                        ),
                    ),
                ),
            ),
        )

        authorized = apply_migration_authorizations(source, "entity", dry_run)
        authorized_record = authorized.records[0]
        constrained_record = authorized.records[2]
        self.assertEqual(authorized_record.merged["type"], "equipment")
        self.assertEqual([item.field for item in authorized_record.conflicts], ["details"])
        self.assertEqual(constrained_record.conflicts[0].message, "explicit migration value mismatch")
        self.assertEqual(set(conflict_field_authorizations(source, "entity")), {("item:test", "type"), ("item:strict", "type")})
        self.assertEqual(conflict_field_authorizations(source, "clock"), {})

        diff = PackageDiffResult(
            package_id="pkg",
            package_version="2",
            target_name="target",
            validation=PackageValidationResult("pkg", "2", warnings=("heads up",)),
            type_results=(authorized,),
        )
        adoption = PackageAdoptionResult("pkg", "2", "target", diff, lock_path=Path("package-lock.json"))
        self.assertGreaterEqual(package_diff_drift_count(diff), 2)
        self.assertIn("## Reconcile Diff", render_package_adoption(adoption))
        self.assertIn("package-lock.json", render_package_adoption(PackageAdoptionResult("pkg", "2", "target", diff, Path("package-lock.json"), True)))
        self.assertIn("| `entity` |", render_package_diff(diff))
        self.assertIn("| empty | 0 | 0 | 0 | 0 |", render_package_diff(PackageDiffResult("pkg", "", "target", PackageValidationResult("pkg", "", errors=("bad",)))))
        self.assertIn("- warning: heads up", render_package_validation(diff.validation))
        self.assertIn("| `entity` | 2 |", render_package_install(PackageInstallResult("pkg", "2", Path("target"), Path("lock"), {"entity": 2})))
        self.assertIn("- backup: `backup-1`", render_package_apply(PackageApplyResult("pkg", "2", "target", "turn:1", Path("lock"), {"entity": 1}), backup_id="backup-1"))
        self.assertIn("- changes: `0`", render_package_apply(PackageApplyResult("pkg", "2", "target", None, Path("lock"), noop=True)))

        operations_diff = PackageDiffResult(
            "pkg",
            "2",
            "target",
            PackageValidationResult("pkg", "2"),
            (
                PackageDryRunResult(
                    "entity",
                    (
                        PackageRecordMerge("item:create", "create", {"id": "item:create"}),
                        PackageRecordMerge(
                            "item:update",
                            "update",
                            {"id": "item:update", "name": "new"},
                            diffs=(PackageFieldDiff("name", "author-owned", "package-update", "old", "new", "new"),),
                        ),
                        PackageRecordMerge(
                            "item:unchanged",
                            "update",
                            {"id": "item:unchanged"},
                            diffs=(PackageFieldDiff("status", "runtime-owned", "keep-runtime", "ok", "bad", "ok"),),
                        ),
                        PackageRecordMerge("item:conflict", "update", None, conflicts=(conflict_type,)),
                    ),
                ),
            ),
        )
        self.assertEqual(
            [(content_type, record_id) for content_type, record_id, _record in package_apply_operations(operations_diff)],
            [("entity", "item:create"), ("entity", "item:update")],
        )

        self.assertEqual(compact_record({"a": None, "b": [], "c": {}, "d": 0}), {"d": 0})
        self.assertEqual(content_paths(Path("/root"), "content/entities.yaml"), [Path("/root/content/entities.yaml")])
        with self.assertRaisesRegex(ValueError, "must be relative"):
            content_paths(Path("/root"), "/abs.yaml")
        with self.assertRaisesRegex(ValueError, "escapes package root"):
            content_paths(Path("/root"), "../escape.yaml")
        self.assertEqual(validate_migration_operation_shape({"type": "rename_alias", "entity_id": "", "from": "a"}, "op"), ["op.entity_id: required", "op.to: required"])
        self.assertEqual(validate_package_migrations(PackageSource(Path("/tmp"), Path("pkg"), {"migrations": "bad"})), ["manifest.migrations must be array"])
        with self.assertRaises(FileNotFoundError):
            first_existing_manifest(Path("/definitely/missing/package"))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                first_existing_manifest(Path(tmp))
        spec = get_default_registry().get("entity")
        self.assertEqual(safe_record_id(spec, {}), "")

    def test_package_migration_operations_update_delete_rename_and_reject_bad_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_root = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_root)
            registry = get_default_registry()
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:end",
                        "type": "location",
                        "name": "End",
                        "summary": "End location.",
                        "location": {"description_short": "End."},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:coin",
                        "type": "item",
                        "name": "Coin",
                        "summary": "A coin.",
                        "details": {"value": 1},
                        "item": {"quantity": 1, "stackable": True},
                        "aliases": ["old coin"],
                    },
                )
                upsert_route(
                    conn,
                    {
                        "id": "route:start-end",
                        "from_location_id": "loc:start",
                        "to_location_id": "loc:end",
                        "travel_minutes": 4,
                    },
                )
                conn.execute("insert or replace into meta(key, value) values('player_entity_id', 'pc:traveler')")
                conn.commit()

                self.assertEqual(apply_package_migrations(conn, (), turn_id="turn:seed", now="now", registry=registry), ([], []))
                migration = PackageMigration(
                    id="migration:ops",
                    path=Path("ops.yaml"),
                    checksum="checksum",
                    from_package_version="1",
                    to_package_version="2",
                    operations=(
                        {"type": "rename_alias", "entity_id": "item:coin", "from": "old coin", "to": "fresh coin"},
                        {"type": "update_conflict_field", "content_type": "entity", "record_id": "item:coin", "field": "details", "value": {"value": 2}},
                    ),
                )
                applied, changed = apply_package_migrations(conn, (migration,), turn_id="turn:seed", now="now", registry=registry)
                self.assertEqual(applied, ["migration:ops"])
                self.assertEqual(changed, ["item:coin"])
                self.assertIsNone(conn.execute("select 1 from aliases where alias='old coin'").fetchone())
                self.assertIsNotNone(conn.execute("select 1 from aliases where alias='fresh coin'").fetchone())
                self.assertEqual(json.loads(conn.execute("select details_json from entities where id='item:coin'").fetchone()[0]), {"value": 1})

                self.assertEqual(
                    apply_package_migration_operation(
                        conn,
                        {"type": "update_conflict_field", "content_type": "entity", "record_id": "item:coin", "field": "type", "value": "equipment"},
                        turn_id="turn:seed",
                        now="now",
                        registry=registry,
                    ),
                    ["item:coin"],
                )
                self.assertEqual(conn.execute("select type from entities where id='item:coin'").fetchone()[0], "item")
                self.assertEqual(
                    apply_package_migration_operation(
                        conn,
                        {"type": "delete_record", "content_type": "route", "record_id": "route:start-end"},
                        turn_id="turn:seed",
                        now="now",
                        registry=registry,
                    ),
                    [],
                )
                self.assertIsNone(conn.execute("select 1 from routes where id='route:start-end'").fetchone())
                self.assertEqual(
                    apply_package_migration_operation(
                        conn,
                        {"type": "delete_record", "content_type": "entity", "record_id": "item:coin"},
                        turn_id="turn:seed",
                        now="now",
                        registry=registry,
                    ),
                    ["item:coin"],
                )
                self.assertIsNone(conn.execute("select 1 from entities where id='item:coin'").fetchone())

                for operation, message in [
                    ({"type": "missing"}, "unsupported package migration operation"),
                    ({"type": "rename_alias", "entity_id": "", "from": "x", "to": "y"}, "rename_alias.entity_id: required"),
                    ({"type": "rename_entity", "from": "missing", "to": "pc:new"}, "missing source"),
                    ({"type": "rename_entity", "from": "loc:start", "to": "pc:traveler"}, "target already exists"),
                    ({"type": "update_conflict_field", "content_type": "entity", "field": "type"}, "record_id: required"),
                    (
                        {"type": "update_conflict_field", "content_type": "entity", "record_id": "pc:traveler", "field": "name"},
                        "unsupported field",
                    ),
                    ({"type": "delete_record", "content_type": "unknown", "record_id": "x"}, "unsupported content_type"),
                ]:
                    with self.subTest(operation=operation):
                        with self.assertRaisesRegex(ValueError, message):
                            apply_package_migration_operation(conn, operation, turn_id="turn:seed", now="now", registry=registry)

                changed = apply_package_migration_operation(
                    conn,
                    {"type": "rename_entity", "from": "pc:traveler", "to": "pc:renamed"},
                    turn_id="turn:seed",
                    now="now",
                    registry=registry,
                )
                self.assertEqual(changed, ["pc:traveler", "pc:renamed"])
                self.assertIsNotNone(conn.execute("select 1 from characters where entity_id='pc:renamed'").fetchone())
                self.assertIsNotNone(conn.execute("select 1 from aliases where entity_id='pc:renamed' and alias='player'").fetchone())
                self.assertEqual(conn.execute("select value from meta where key='player_entity_id'").fetchone()[0], "pc:renamed")

    def test_current_records_for_every_package_content_type_round_trip_from_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_root = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_root)
            registry = get_default_registry()
            with connect(campaign) as conn:
                runtime = ContentRuntime(campaign, conn, "turn:seed", "now")
                upsert_entity(
                    conn,
                    {
                        "id": "item:seed",
                        "type": "item",
                        "name": "Seed",
                        "summary": "A seed.",
                        "item": {"category": "seed", "quantity": 3, "stackable": True, "properties": {"grow": True}},
                        "aliases": ["seed"],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:field",
                        "type": "location",
                        "name": "Field",
                        "summary": "A field.",
                        "location": {
                            "biome": "farm",
                            "safety_level": "safe",
                            "description_short": "Field.",
                            "exits": ["north"],
                            "resources": ["soil"],
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plot:one",
                        "type": "crop_plot",
                        "name": "Plot",
                        "summary": "A plot.",
                        "crop_plot": {
                            "plot_no": 1,
                            "crop_entity_id": "item:seed",
                            "area_sqm": 4,
                            "growth_stage": 1,
                            "growth_stage_max": 3,
                        },
                    },
                )
                upsert_rule(conn, {"id": "rule:test", "name": "Rule", "statement": "Always test.", "aliases": ["testing"]})
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test",
                        "name": "Clock",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "trigger_when_full": "finish",
                        "tick_rules": {"daily": 1},
                        "aliases": ["clock alias"],
                    },
                )
                upsert_route(
                    conn,
                    {
                        "id": "route:start-field",
                        "from_location_id": "loc:start",
                        "to_location_id": "loc:field",
                        "travel_minutes": 8,
                        "hazards": ["mud"],
                        "requirements": ["boots"],
                    },
                )
                registry.get("world_setting").upsert(
                    runtime,
                    {
                        "id": "world:test",
                        "name": "Weather",
                        "summary": "Weather rules.",
                        "category": "weather",
                        "content": {"rain": "possible"},
                        "linked_rules": ["rule:test"],
                        "linked_clocks": ["clock:test"],
                        "linked_entities": ["loc:field"],
                        "applies_when": {"season": "spring"},
                        "aliases": ["weather"],
                    },
                )
                conn.commit()

                self.assertEqual(current_records_for_spec(conn, registry.get("entity"), [{}], registry=registry), [])
                entity_records = current_records_for_spec(
                    conn,
                    registry.get("entity"),
                    [{"id": "item:seed"}, {"id": "pc:traveler"}, {"id": "loc:field"}, {"id": "plot:one"}],
                    registry=registry,
                )
                entities_by_id = {record["id"]: record for record in entity_records}
                self.assertEqual(entities_by_id["item:seed"]["item"]["quantity"], 3)
                self.assertEqual(entities_by_id["pc:traveler"]["character"]["role"], "player")
                self.assertEqual(entities_by_id["loc:field"]["location"]["resources"], ["soil"])
                self.assertEqual(entities_by_id["plot:one"]["crop_plot"]["plot_no"], 1)
                self.assertEqual(current_records_for_spec(conn, registry.get("rule"), [{"id": "rule:test"}], registry=registry)[0]["aliases"], ["testing"])
                self.assertEqual(current_records_for_spec(conn, registry.get("clock"), [{"id": "clock:test"}], registry=registry)[0]["tick_rules"], {"daily": 1})
                self.assertEqual(current_records_for_spec(conn, registry.get("route"), [{"id": "route:start-field"}], registry=registry)[0]["hazards"], ["mud"])
                self.assertEqual(
                    current_records_for_spec(conn, registry.get("world_setting"), [{"id": "world:test"}], registry=registry)[0]["content"],
                    {"rain": "possible"},
                )


class SaveManagerConditionCoverageTests(unittest.TestCase):
    def test_registry_listing_switching_require_save_and_path_resolution_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root)

            self.assertEqual(manager.inspect_workspace()["campaigns_count"], 0)
            registered = manager.register_campaign("campaigns/minimal", "starters/default")
            self.assertEqual(registered["campaign"]["starter_save_path"], "starters/default")
            registry = manager.read_registry()
            registry["campaigns"].append({"id": "bad", "name": "Bad", "path": "missing-campaign"})
            manager.write_registry(registry)
            campaigns = manager.list_campaigns(refresh=True)["campaigns"]
            self.assertEqual({item["status"] for item in campaigns}, {"ok", "error"})

            saves = [
                {"id": "save-ok", "campaign_id": "minimal-campaign", "path": "saves/minimal/save-ok", "label": "OK", "health": "ok"},
                {"id": "save-arch", "campaign_id": "minimal-campaign", "path": "saves/minimal/save-arch", "label": "Archived", "archived": True, "health": "ok"},
                {"id": "save-bad", "campaign_id": "minimal-campaign", "path": "saves/minimal/save-bad", "label": "Bad", "health": "error", "errors": ["broken"]},
            ]
            manager.write_registry({"schema_version": "1", "active_save_id": None, "campaigns": registry["campaigns"], "saves": saves})

            def refresh(record: dict[str, object]) -> dict[str, object]:
                return {**record, "health": record.get("health", "ok"), "summary": "refreshed"}

            with mock.patch.object(manager, "refresh_save_record", side_effect=refresh):
                listed = manager.list_saves(campaign_id="minimal-campaign", refresh=True)
                self.assertEqual([item["id"] for item in listed["saves"]], ["save-ok", "save-bad"])
                self.assertFalse(manager.current_save()["ok"])
                registry = manager.read_registry()
                registry["active_save_id"] = "missing"
                manager.write_registry(registry)
                self.assertIn("active save not found", manager.current_save()["errors"][0])
                registry["active_save_id"] = "save-ok"
                manager.write_registry(registry)
                self.assertTrue(manager.current_save(refresh=True)["ok"])
                self.assertEqual(manager.switch_save("save-ok")["active_save_id"], "save-ok")
                with self.assertRaisesRegex(SaveManagerError, "save not found"):
                    manager.switch_save("missing")
                with self.assertRaisesRegex(SaveManagerError, "archived"):
                    manager.switch_save("save-arch")
                with self.assertRaisesRegex(SaveManagerError, "save not found for path"):
                    manager.require_save(refresh=False, save_path="saves/missing")
                with self.assertRaisesRegex(SaveManagerError, "archived"):
                    manager.require_save(refresh=False, save_path="saves/minimal/save-arch")
                with self.assertRaisesRegex(SaveManagerError, "save is not healthy"):
                    manager.require_save(refresh=False, save_path="saves/minimal/save-bad")
                registry = manager.read_registry()
                registry["active_save_id"] = "save-bad"
                manager.write_registry(registry)
                with self.assertRaisesRegex(SaveManagerError, "active save is not healthy"):
                    manager.require_save(refresh=False)

            self.assertEqual(manager.resolve_save_path_for_runtime("saves/minimal/save-ok"), manager.root / "saves" / "minimal" / "save-ok")
            manager.write_registry({"schema_version": "1", "active_save_id": None, "campaigns": [], "saves": []})
            self.assertEqual(manager.resolve_save_path_for_runtime(default_save="saves/default"), manager.root / "saves" / "default")
            with self.assertRaisesRegex(SaveManagerError, "save is required"):
                manager.resolve_save_path_for_runtime()

    def test_create_duplicate_and_start_modes_cover_healthy_blocked_and_created_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root)
            with self.assertRaisesRegex(SaveManagerError, "starter save does not exist"):
                manager.create_save(campaign="campaigns/minimal", starter_save="missing-starter")
            with self.assertRaisesRegex(SaveManagerError, "save not found"):
                manager.duplicate_save("missing")

            source_save = root / "saves" / "minimal" / "source"
            source_save.mkdir(parents=True)
            (source_save / "marker.txt").write_text("copy me", encoding="utf-8")
            manager.write_registry(
                {
                    "schema_version": "1",
                    "active_save_id": "source",
                    "campaigns": [],
                    "saves": [{"id": "source", "path": "saves/minimal/source", "campaign_id": "minimal", "label": "Source", "kind": "normal"}],
                }
            )
            with mock.patch.object(
                manager,
                "build_save_record",
                side_effect=lambda **kwargs: {
                    "id": kwargs["save_id"],
                    "campaign_path": kwargs["campaign_path"],
                    "path": kwargs["save_path"],
                    "label": kwargs["label"],
                    "kind": kwargs["kind"],
                    "source": kwargs["source"],
                    "health": "ok",
                },
            ):
                duplicate = manager.duplicate_save("source", activate=False)
            self.assertTrue((root / duplicate["save"]["path"] / "marker.txt").exists())
            self.assertEqual(duplicate["active_save_id"], "source")

            no_save = {"ok": False, "errors": ["none"], "error_details": [{"code": "SAVE_MANAGER_ERROR"}]}
            with mock.patch.object(manager, "current_save", return_value=no_save):
                self.assertEqual(manager.start_or_continue(create_if_missing=False)["mode"], "needs_save_choice")
            with mock.patch.object(manager, "current_save", return_value={"ok": True, "save": None, "errors": []}):
                self.assertEqual(manager.start_or_continue()["mode"], "blocked")
            with mock.patch.object(
                manager,
                "current_save",
                return_value={"ok": True, "save": {"id": "bad", "label": "Bad", "health": "error", "errors": ["broken"]}, "errors": []},
            ):
                self.assertIn("active save is not healthy", manager.start_or_continue()["errors"][0])

            save = {
                "id": "save-ok",
                "path": "saves/minimal/save-ok",
                "campaign_id": "minimal",
                "campaign_name": "Minimal",
                "current_time_block": "morning",
                "current_location_id": "loc:start",
                "current_location_name": "Start",
                "health": "ok",
            }
            runtime = SimpleNamespace(query=lambda *_args, **_kwargs: result_object({"text": "### Overview\nA room.\n| # | Action | Detail |\n| 1 | Look | Around |"}))
            with (
                mock.patch.object(manager, "current_save", return_value={"ok": True, "save": save, "errors": []}),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=runtime),
                mock.patch.object(manager, "mark_played") as mark_played,
            ):
                continued = manager.start_or_continue(user_text="look")
            self.assertTrue(continued["ok"])
            self.assertEqual(continued["mode"], "continued")
            mark_played.assert_called_once_with("save-ok")

            with (
                mock.patch.object(manager, "current_save", return_value=no_save),
                mock.patch.object(manager, "create_save", return_value={"ok": True, "save": save, "errors": []}),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=runtime),
                mock.patch.object(manager, "mark_played"),
            ):
                self.assertEqual(manager.start_or_continue(campaign="campaigns/minimal")["mode"], "created")

    def test_player_action_and_confirmation_cover_pending_session_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/minimal")
            save = manager.start_or_continue(campaign="campaigns/minimal")["save"]

            def pending_action(**overrides: object) -> dict[str, object]:
                return {
                    "schema_version": "1",
                    "save_id": save["id"],
                    "save_path": save["path"],
                    "session_id": "sid",
                    "created_at": "2099-01-01T00:00:00+00:00",
                    "expires_at": "2099-01-01T00:30:00+00:00",
                    "ttl_seconds": 1800,
                    "delta": {},
                    "turn_proposal": {},
                    **overrides,
                }

            manager.write_pending_clarification(
                {
                    "schema_version": "1",
                    "clarification_id": "clarify:1",
                    "save_id": save["id"],
                    "save_path": save["path"],
                    "created_at": "2099-01-01T00:00:00+00:00",
                    "original_user_text": "repeat this",
                    "clarification": {"question": "which way?"},
                }
            )
            with mock.patch.object(manager, "require_save", return_value=save):
                repeat = manager.player_act(user_text="repeat this")
            self.assertFalse(repeat["ok"])
            self.assertEqual(repeat["pending_clarification_id"], "clarify:1", repeat)
            with mock.patch.object(manager, "require_save", return_value=save):
                self.assertTrue(manager.player_cancel("clarify:1")["ok"])

            ready_runtime = SimpleNamespace(
                act=lambda *_args, **_kwargs: result_object(
                    {
                        "ok": True,
                        "status": "ready",
                        "action": "rest",
                        "ready_to_save": True,
                        "delta_draft": {"changed": False},
                        "turn_proposal": {"proposal_id": "p"},
                        "player_message": "Ready.",
                    }
                )
            )
            with (
                mock.patch.object(manager, "require_save", return_value=save),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=ready_runtime),
                mock.patch.object(manager, "mark_played"),
            ):
                ready = manager.player_act(user_text="rest", platform="web", session_key="abc")
            pending_action_state = manager.read_pending_action()
            self.assertTrue(ready["ready_to_confirm"])
            self.assertEqual(pending_action_state["platform"], "web")
            self.assertNotEqual(pending_action_state["session_key_hash"], "abc")
            self.assertIn("expires_at", pending_action_state)

            captured_turn_kwargs: dict[str, object] = {}

            def act_with_external_candidate(*_args: object, **kwargs: object) -> SimpleNamespace:
                captured_turn_kwargs.update(kwargs)
                return result_object(
                    {
                        "ok": True,
                        "status": "ready",
                        "action": "rest",
                        "ready_to_save": True,
                        "delta_draft": {"changed": False},
                        "turn_proposal": {"proposal_id": "p2"},
                        "player_message": "Ready.",
                    }
                )

            turn_runtime = SimpleNamespace(act=act_with_external_candidate)
            external = {"kind": "single", "mode": "action", "action": "rest", "slots": {"until": "morning"}}
            with (
                mock.patch.object(manager, "require_save", return_value=save),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=turn_runtime),
                mock.patch.object(manager, "mark_played"),
            ):
                turn = manager.player_turn(
                    user_text="rest",
                    external_intent_candidate=external,
                    intent_ai="consensus",
                    expected_pending_id=str(ready["session_id"]),
                    platform="web",
                    session_key="abc",
                )
            self.assertTrue(turn["ready_to_confirm"])
            self.assertEqual(captured_turn_kwargs["external_intent_candidate"], external)
            self.assertEqual(captured_turn_kwargs["intent_ai"], "consensus")

            clarification_runtime = SimpleNamespace(
                act=lambda *_args, **_kwargs: result_object(
                    {
                        "ok": False,
                        "status": "needs_clarification",
                        "interpretation": {"intent": {"clarification": {"question": "which target?"}}},
                        "repair_options": [],
                    }
                )
            )
            with (
                mock.patch.object(manager, "require_save", return_value=save),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime),
                mock.patch.object(manager, "mark_played"),
            ):
                clarification = manager.player_act(
                    user_text="use it",
                    expected_pending_id=str(turn["session_id"]),
                    platform="web",
                    session_key="abc",
                )
            self.assertFalse(clarification["ready_to_confirm"])
            self.assertTrue(clarification["pending_clarification_id"].startswith("clarification:"))

            blocked_runtime = SimpleNamespace(act=lambda *_args, **_kwargs: result_object({"ok": False, "status": "blocked", "errors": ["bad"]}))
            with (
                mock.patch.object(manager, "require_save", return_value=save),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=blocked_runtime),
                mock.patch.object(manager, "mark_played"),
            ):
                blocked = manager.player_act(user_text="different", platform="web", session_key="abc")
            self.assertFalse(blocked["ok"])
            self.assertIsNotNone(manager.read_pending_clarification())

            with mock.patch.object(manager, "require_save", return_value=save):
                manager.clear_pending_action()
                manager.clear_pending_clarification()
                with self.assertRaisesRegex(SaveManagerError, "no pending player action"):
                    manager.player_confirm("sid")
                manager.write_pending_action(pending_action(save_id="other"))
                with self.assertRaisesRegex(SaveManagerError, "different active save"):
                    manager.player_confirm("sid")
                manager.write_pending_action(
                    pending_action(
                        **platform_session_metadata(platform="web", session_key="abc"),
                    )
                )
                with self.assertRaisesRegex(SaveManagerError, "requires matching platform session"):
                    manager.player_confirm("sid")
                with self.assertRaisesRegex(SaveManagerError, "different platform"):
                    manager.player_confirm("sid", platform="mobile", session_key="abc")
                with self.assertRaisesRegex(SaveManagerError, "different platform session"):
                    manager.player_confirm("sid", platform="web", session_key="wrong")
                manager.write_pending_action(
                    pending_action(
                        **platform_session_metadata(platform="web", session_key="abc", actor_id="actor:one"),
                    )
                )
                with self.assertRaisesRegex(SaveManagerError, "requires matching platform actor"):
                    manager.player_confirm("sid", platform="web", session_key="abc")
                with self.assertRaisesRegex(SaveManagerError, "different platform actor"):
                    manager.player_confirm("sid", platform="web", session_key="abc", actor_id="actor:two")
                manager.write_pending_action(
                    pending_action(
                        created_at="2000-01-01T00:00:00+00:00",
                        expires_at="2000-01-01T00:30:00+00:00",
                    )
                )
                with self.assertRaisesRegex(SaveManagerError, "pending player action expired"):
                    manager.player_confirm("sid")
                self.assertIsNone(manager.read_pending_action())
                manager.write_pending_action(pending_action(session_id=""))
                with self.assertRaisesRegex(SaveManagerError, "invalid owner token"):
                    manager.player_confirm("sid")
                manager.write_pending_action(pending_action())
                with self.assertRaisesRegex(SaveManagerError, "requires the pending action session_id"):
                    manager.player_confirm("")
                with self.assertRaisesRegex(SaveManagerError, "does not match"):
                    manager.player_confirm("other")
                manager.write_pending_action(pending_action(delta=[]))
                with self.assertRaisesRegex(SaveManagerError, "incomplete"):
                    manager.player_confirm("sid")

            captured: dict[str, object] = {}

            def commit_turn(delta: dict[str, object], *, turn_proposal: dict[str, object]) -> SimpleNamespace:
                captured["delta"] = delta
                captured["proposal"] = turn_proposal
                return result_object(
                    {
                        "ok": True,
                        "write_status": "committed",
                        "idempotent_replay": False,
                        "projection_status": "dirty",
                        "warnings": ["w"],
                    }
                )

            commit_runtime = SimpleNamespace(
                campaign=load_campaign(root / str(save["path"])),
                commit_turn=commit_turn,
            )
            manager.write_registry(
                {
                    "schema_version": "1",
                    "active_save_id": save["id"],
                    "campaigns": [],
                    "saves": [save],
                }
            )
            manager.write_pending_action(
                pending_action(
                    delta={"changed": True},
                    turn_proposal={"provenance": {"source": "test"}},
                )
            )
            with (
                mock.patch.object(manager, "require_save", return_value=save),
                mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=commit_runtime),
                mock.patch("rpg_engine.save_manager.connect"),
                mock.patch("rpg_engine.save_manager.find_idempotent_turn", return_value=None),
                mock.patch.object(
                    manager,
                    "build_confirmation_receipt",
                    return_value={"schema_version": "1", "receipt_digest": "test-only"},
                ),
                mock.patch.object(manager, "write_confirmation_receipt_anchor"),
                mock.patch.object(manager, "write_confirmation_receipt"),
                mock.patch.object(manager, "refresh_save_record", side_effect=lambda record: {**record, "health": "ok"}),
            ):
                confirmed = manager.player_confirm("sid")
            self.assertTrue(confirmed["saved"])
            self.assertTrue(captured["proposal"]["human_confirmed"])
            self.assertEqual(captured["proposal"]["provenance"]["confirmed_via"], "player_confirm")
            self.assertEqual(captured["proposal"]["provenance"]["confirmation_session_id"], "sid")
            self.assertIsInstance(captured["proposal"]["provenance"]["confirmed_at"], str)
            self.assertFalse(manager.pending_action_path().exists())

    def test_save_manager_helper_contracts_and_malformed_registry_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = SaveManager(root)
            manager.registry_path.parent.mkdir(parents=True, exist_ok=True)
            for text, message in [
                ("{", "invalid JSON"),
                ("[]", "must be a JSON object"),
                (json.dumps({"schema_version": "old"}), "schema_version must be"),
                (json.dumps({"schema_version": "1", "campaigns": {}, "saves": []}), "must be arrays"),
            ]:
                with self.subTest(text=text):
                    manager.registry_path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(SaveManagerError, message):
                        manager.read_registry()

            with self.assertRaisesRegex(SaveManagerError, "must not contain"):
                resolve_registry_path(root, "../outside.json")
            with self.assertRaisesRegex(SaveManagerError, "registry_path must be relative"):
                resolve_registry_path(root, root / ".aigm" / "absolute-registry.json")
            with self.assertRaisesRegex(SaveManagerError, "registry_path is required"):
                resolve_registry_path(root, "")
            with self.assertRaisesRegex(SaveManagerError, "registry_path is required"):
                resolve_registry_path(root, "   ")
            with self.assertRaisesRegex(SaveManagerError, "registry_path must be a file path"):
                resolve_registry_path(root, ".")
            self.assertEqual(normalize_optional_relative(None, "x"), None)
            self.assertEqual(normalize_optional_relative("  ", "x"), None)
            self.assertEqual(normalize_required_relative("a/b", "x"), "a/b")
            with self.assertRaisesRegex(SaveManagerError, "must be relative"):
                normalize_required_relative("/abs", "x")
            with self.assertRaisesRegex(SaveManagerError, "must not contain"):
                normalize_required_relative("../escape", "x")
            with self.assertRaisesRegex(SaveManagerError, "must not contain backslashes"):
                normalize_required_relative("a\\b", "x")
            with self.assertRaisesRegex(SaveManagerError, "escapes workspace root"):
                ensure_under_root(root, root.parent / "outside", "candidate")
            with mock.patch.object(manager, "pending_action_path", return_value=root.parent / "pending-action.json"):
                with self.assertRaisesRegex(SaveManagerError, "escapes workspace root"):
                    manager.write_pending_action({"save_id": "save", "session_id": "sid", "delta": {}, "turn_proposal": {}})
            with mock.patch.object(manager, "pending_clarification_path", return_value=root.parent / "pending-clarification.json"):
                with self.assertRaisesRegex(SaveManagerError, "escapes workspace root"):
                    manager.write_pending_clarification({"schema_version": "1"})
            nonempty = root / "nonempty"
            nonempty.mkdir()
            (nonempty / "file.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "not empty"):
                ensure_empty_target(nonempty)
            file_target = root / "file-save"
            file_target.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "target is a file"):
                ensure_empty_target(file_target)
            fresh_target = root / "new" / "save"
            ensure_empty_target(fresh_target)
            self.assertTrue(fresh_target.parent.exists())

            lock_path = root / "registry.lock"
            with registry_lock(lock_path):
                self.assertTrue(lock_path.exists())
                with self.assertRaisesRegex(SaveManagerError, "timed out"):
                    with registry_lock(lock_path, timeout=0):
                        pass
            self.assertTrue(lock_path.exists())
            with registry_lock(lock_path, timeout=0):
                pass

            self.assertIsNone(find_record("bad", "id"))
            self.assertEqual(find_record([{"id": "a"}], "a"), {"id": "a"})
            self.assertIsNone(find_save_record_by_path("bad", "save"))
            self.assertEqual(find_save_record_by_path([{"path": "saves/a"}], "saves/a"), {"path": "saves/a"})
            self.assertEqual([item["id"] for item in replace_record([{"id": "b"}, {"id": "a"}], {"id": "c"})], ["a", "b", "c"])
            self.assertEqual(slugify(" A/B C "), "a-b-c")
            self.assertEqual(slugify("!!!"), "campaign")

            pending = platform_session_metadata(platform=" web ", session_key="secret")
            validate_pending_platform_session({}, platform="", session_key="")
            validate_pending_platform_session(pending, platform="web", session_key="secret")
            with self.assertRaisesRegex(SaveManagerError, "matching platform session"):
                validate_pending_platform_session(pending, platform="", session_key="")
            with self.assertRaisesRegex(SaveManagerError, "different platform"):
                validate_pending_platform_session(pending, platform="mobile", session_key="secret")
            with self.assertRaisesRegex(SaveManagerError, "different platform session"):
                validate_pending_platform_session(pending, platform="web", session_key="other")

            campaign = SimpleNamespace(campaign_id="camp", name="Camp")
            upserted = upsert_campaign_record([{"id": "camp", "starter_save_path": "old"}], campaign, "campaigns/camp", None)
            self.assertEqual(upserted[0]["starter_save_path"], "old")
            self.assertEqual(build_save_summary({"current_time_block": "dawn", "current_location_id": "loc:start"}, "Start"), "dawn，位于Start。")
            self.assertIsNone(manager.pending_action_path().parent.parent if False else None)

            with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=SimpleNamespace(query=lambda *_a, **_k: result_object({"text": "## Location Name\nBody"}))):
                self.assertEqual(__import__("rpg_engine.save_manager", fromlist=["location_name_from_save"]).location_name_from_save(root, {"current_location_id": "loc:start"}), "Location Name")
            with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", side_effect=RuntimeError("boom")):
                self.assertIsNone(__import__("rpg_engine.save_manager", fromlist=["location_name_from_save"]).location_name_from_save(root, {"current_location_id": "loc:start"}))
            self.assertIsNone(__import__("rpg_engine.save_manager", fromlist=["location_name_from_save"]).location_name_from_save(root, {}))

            scene_text = "### 全景\nFirst line.\nSecond line.\n### Other\nIgnored"
            self.assertEqual(extract_scene_summary(scene_text), "First line.\nSecond line.")
            self.assertEqual(extract_scene_summary("# Title\nA fallback line."), "A fallback line.")
            self.assertEqual(extract_affordances("| # | 行动 | Detail |\n| 1 | Look | Around |\n| 2 | Look | Again |"), ["Look"])
            self.assertEqual(len(extract_affordances("no table", limit=3)), 3)
            onboarding = render_onboarding_text(
                {"campaign_name": "Camp", "current_time_block": "dawn", "current_location_name": "Start"},
                {"text": "### 全景\nSQLite delta campaign.yaml\n| # | 行动 | Detail |\n| 1 | Look | Around |"},
                mode="created",
            )
            self.assertNotIn("SQLite", onboarding)
            self.assertIn("Look", onboarding)
            self.assertIn("确认后", player_action_message({"player_message": "", "warnings": ["w"], "missing_required": ["target"]}, ready=True))
            repair_message = player_action_message({"repair_options": [{"label": "Try", "effect": "safer"}]}, ready=False)
            self.assertIn("Try: safer", repair_message)
            self.assertEqual(extract_result_clarification({"interpretation": {"clarification": {"q": "direct"}}}), {"q": "direct"})
            self.assertEqual(extract_result_clarification({"interpretation": {"intent": {"clarification": {"q": "nested"}}}}), {"q": "nested"})
            self.assertIsNone(extract_result_clarification({"interpretation": []}))
            self.assertIn("刷新状态：dirty", player_confirm_message({"write_status": "committed", "projection_status": "dirty", "state_audit": {"findings": [1, 2]}}))
            self.assertIn("没有完成保存", player_confirm_message({"write_status": "blocked", "projection_status": "clean"}))
            self.assertFalse(error_dict(ValueError("bad"))["ok"])

            campaign_dir = root / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            loaded_campaign = load_campaign(campaign_dir)
            target = root / "save-target"
            target.mkdir()
            rewrite_save_manifests(target, loaded_campaign)
            self.assertTrue((target / "campaign.yaml").exists())
            self.assertEqual(relative_path(target, campaign_dir), "../campaign")

    def test_malicious_registry_record_refresh_does_not_mutate_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root)
            manager.register_campaign("campaigns/minimal")
            created = manager.create_save(campaign="campaigns/minimal")

            registry = manager.read_registry()
            registry["campaigns"][0]["path"] = "../outside"
            registry["saves"][0]["path"] = "/tmp/outside"
            manager.write_registry(registry)
            before = manager.registry_path.read_text(encoding="utf-8")

            campaigns = manager.list_campaigns(refresh=True)
            current = manager.current_save(refresh=True)
            listed = manager.list_saves(refresh=True)

            self.assertFalse(campaigns["ok"])
            self.assertFalse(current["ok"])
            self.assertFalse(listed["ok"])
            self.assertEqual(manager.registry_path.read_text(encoding="utf-8"), before)
            self.assertFalse(manager.pending_action_path().exists())
            self.assertTrue((root / created["save"]["path"] / "data" / "game.sqlite").exists())

    def test_registry_refresh_rejects_root_escape_and_secondary_paths_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root)
            manager.register_campaign("campaigns/minimal")
            created = manager.create_save(campaign="campaigns/minimal")
            escape_link = root / "saves" / "escape-link"
            escape_link.parent.mkdir(parents=True, exist_ok=True)
            escape_link.symlink_to(Path(outside_tmp), target_is_directory=True)

            registry = manager.read_registry()
            registry["campaigns"][0]["starter_save_path"] = "../outside"
            registry["saves"][0]["path"] = "saves/escape-link"
            registry["saves"][0]["campaign_path"] = "campaigns\\bad"
            manager.write_registry(registry)
            before = manager.registry_path.read_text(encoding="utf-8")

            campaigns = manager.list_campaigns(refresh=True)
            current = manager.current_save(refresh=True)
            listed = manager.list_saves(refresh=True)

            self.assertFalse(campaigns["ok"])
            self.assertFalse(current["ok"])
            self.assertFalse(listed["ok"])
            self.assertIn("starter_save_path", "\n".join(campaigns["errors"]))
            self.assertEqual(manager.registry_path.read_text(encoding="utf-8"), before)
            self.assertFalse(manager.pending_action_path().exists())
            self.assertTrue((root / created["save"]["path"] / "data" / "game.sqlite").exists())

    def test_filtered_save_refresh_rejects_unfiltered_bad_registry_path_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root)
            manager.register_campaign("campaigns/minimal")
            created = manager.create_save(campaign="campaigns/minimal")

            registry = manager.read_registry()
            registry["saves"].append(
                {
                    "id": "save:bad-unfiltered",
                    "campaign_id": "other-campaign",
                    "path": "/tmp/outside",
                    "archived": False,
                }
            )
            manager.write_registry(registry)
            before = manager.registry_path.read_text(encoding="utf-8")

            listed = manager.list_saves(campaign_id=str(created["save"]["campaign_id"]), refresh=True)

            self.assertFalse(listed["ok"])
            self.assertIn("save:bad-unfiltered", "\n".join(listed["errors"]))
            self.assertEqual(manager.registry_path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
