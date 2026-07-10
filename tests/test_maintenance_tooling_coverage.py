from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

import rpg_engine.memory as memory_module
from rpg_engine.ai.state_audit import (
    build_state_audit_prompt,
    compact_json,
    current_location_id,
    deterministic_state_audit,
    explicit_no_change,
    first_present,
    has_explicit_no_change,
    higher_risk,
    is_high_risk_entity,
    max_risk,
    missing_high_risk_fields,
    run_state_audit,
    should_block_state_audit,
    with_ai_status,
)
from rpg_engine.admin.plugins import (
    discover_plugin_manifests,
    first_manifest_path,
    load_manifest_data,
    load_plugin_manifest,
    render_plugin_list,
    render_plugin_validation,
    validate_manifest_data,
)
from rpg_engine.actions.combat import combat_blockers, resolve_combat, validate_combat_delta, validate_combat_request
from rpg_engine.actions.craft import (
    craft_facts,
    craft_player_message,
    craft_repair_options,
    resolve_craft,
    resolve_craft_inputs,
    validate_craft_delta,
    validate_craft_request,
)
from rpg_engine.actions.gather import (
    gather_blockers,
    gather_player_message,
    gather_repair_options,
    resolve_gather,
    validate_gather_delta,
    validate_gather_request,
)
from rpg_engine.actions.social import (
    attach_palette_to_social_delta,
    location_blocked_only,
    location_name,
    mark_social_no_change_when_low_impact,
    render_social_palette_section,
    resolve_social,
    social_facts,
    social_scope,
    validate_social_delta,
    validate_social_palette_candidate,
    validate_social_request,
)
from rpg_engine.backup import create_backup, list_backups, render_backup_list, restore_backup
from rpg_engine.campaign import Campaign, load_campaign
from rpg_engine.cards import write_cards
from rpg_engine.content_types.base import ContentRuntime
from rpg_engine.content_types.world_setting import (
    append_world_setting_card_sections,
    content_ref_exists,
    parse_json_list,
    parse_json_value,
    render_world_setting_entity,
    table_exists as world_setting_table_exists,
    upsert_world_setting,
    validate_world_setting_record,
    validate_world_settings_database,
)
from rpg_engine.content_factory import (
    audit_content_quality,
    base_details,
    contains_key_recursive,
    has_any_key,
    has_uses,
    kind_to_entity_type,
    make_content_delta,
    render_content_quality,
    split_csv,
    write_content_delta,
)
from rpg_engine.context.collectors import (
    memory_loaded_items,
    memory_omitted_items,
    memory_summaries_section,
)
from rpg_engine.context_builder import build_context, missing_signal_evidence
from rpg_engine.db import connect, upsert_entity
from rpg_engine.memory import (
    as_text_list,
    build_day_memories,
    build_memory_records,
    build_world_memories,
    dedupe,
    ensure_memory_tables,
    find_omitted_relevant_memories,
    find_relevant_memories,
    format_memory_value,
    history_points,
    latest_turn_id,
    memory_row_freshness,
    memory_row_authority,
    memory_row_freshness_evidence,
    memory_row_has_hidden_refs,
    memory_row_source_event_ids,
    memory_row_source_turn_ids,
    memory_metadata_columns_present,
    memory_projection_health,
    memory_projection_snapshot,
    memory_rows_have_trusted_provenance,
    memory_table_exists,
    memory_summary_metadata,
    parse_day,
    player_safe_memory_reason,
    rebuild_memory_summaries,
    redact_memory_row_for_view,
    render_memory_section,
    safe_id,
    trim_join,
    turn_is_after,
    write_memory_report,
)
from rpg_engine.migrations import (
    additive_column_has_write_blocking_constraints,
    apply_pending_migrations,
    ensure_schema_migrations,
    execute_migration_statement,
    migration_files,
    migration_id,
)
from rpg_engine.ops_report import build_ops_report, scalar as ops_scalar, table_count_sql, table_exists, write_ops_report
from rpg_engine.projection_service import ProjectionService
from rpg_engine.projections import mark_projections_dirty
from rpg_engine.resource_paths import read_resource_text
from rpg_engine.reflection import (
    draft_reflection,
    format_value,
    related_events,
    trim,
    validate_reflection_draft,
)
from rpg_engine.render import render_current_snapshot_json, render_scene
from rpg_engine.save import save_turn_delta
from rpg_engine.save_patch import (
    SavePatchResult,
    apply_operation,
    apply_save_patch,
    entity_details,
    is_safe_detail_value,
    load_patch_file,
    validate_save_patch,
)
from rpg_engine.simulation import (
    render_simulation_report,
    run_long_simulation,
    scalar as simulation_scalar,
    synthetic_turn_delta,
    write_simulation_report,
)
from rpg_engine.turn_assistant import (
    TurnAssistantOptions,
    render_delta_validation_for_options,
    render_next_steps,
    render_response_lint,
    run_save_pipeline,
)

from tests.helpers import ENGINE_ROOT, copy_initialized_minimal, current_turn


def minimal_context(mode: str = "action", submode: str = "rest", *, allow: bool = True) -> dict[str, object]:
    return {
        "request": {
            "mode": mode,
            "submode": submode,
            "requires_preview": mode == "action",
            "must_save": mode == "action",
            "turn_contract": {
                "intent": {
                    "user_text": "休息",
                    "mode": mode,
                    "submode": submode,
                    "action": submode if mode == "action" else None,
                    "options": {},
                    "confidence": "high",
                    "source": "test",
                },
                "required_template": "rest_turn.md" if mode == "action" else "scene_entry.md",
                "response_headings": ["场景", "行动结果", "状态变化", "保存状态", "后续行动"]
                if mode == "action"
                else ["场景"],
                "requires_preview": mode == "action",
                "must_save": mode == "action",
                "allowed_delta_sources": ["response_draft"],
                "validation_profile": "player_turn_commit" if mode == "action" else "preview_only",
            },
        },
        "completeness": {
            "allow_proceed": allow,
            "missing_required": ["destination"] if not allow else [],
            "needs_user_confirmation": [],
        },
    }


def wait_delta(command_id: str = "maintenance-tooling-wait") -> dict[str, object]:
    return {
        "expected_turn_id": "turn:seed",
        "command_id": command_id,
        "user_text": "等待片刻",
        "intent": "wait",
        "changed": False,
        "summary": "No significant change.",
    }


def insert_test_memory(conn: sqlite3.Connection, **overrides: object) -> sqlite3.Row:
    values: dict[str, object] = {
        "id": "memory:test",
        "kind": "world",
        "subject_id": None,
        "title": "Test memory",
        "summary": "Visible test summary.",
        "key_points_json": "[]",
        "source_event_ids_json": "[]",
        "source_turn_ids_json": "[]",
        "valid_from_turn": None,
        "valid_to_turn": None,
        "summary_type": "deterministic_world",
        "visibility_mode": "player",
        "freshness_status": "fresh",
        "freshness_turn_id": "turn:seed",
        "stale_reason": "",
        "freshness_evidence_json": json.dumps({"current_turn_id": "turn:seed"}),
        "derived_authority_json": json.dumps(
            {"authority": "derived_context", "fact_authority": False}
        ),
        "updated_at": "2026-07-10T00:00:00+00:00",
    }
    values.update(overrides)
    columns = list(values)
    conn.execute(
        f"insert into memory_summaries ({', '.join(columns)}) values ({', '.join('?' for _ in columns)})",
        [values[column] for column in columns],
    )
    return conn.execute("select * from memory_summaries where id = ?", (values["id"],)).fetchone()


def set_test_memory_projection_clean(
    conn: sqlite3.Connection,
    *,
    last_turn_id: str = "turn:seed",
) -> None:
    conn.execute(
        """
        insert or replace into projection_state
        (name, version, last_turn_id, status, updated_at, last_error)
        values('memory', 1, ?, 'clean', strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'), null)
        """,
        (last_turn_id,),
    )


def action_options(**values: object) -> SimpleNamespace:
    defaults = {
        "target": None,
        "location": None,
        "destination": None,
        "palette_id": None,
        "output_confirmed": False,
        "user_text": None,
        "project": None,
        "output": None,
        "materials": None,
        "time_cost": None,
        "npc": None,
        "topic": None,
        "approach": None,
        "weapon": None,
        "ammo": None,
        "distance": None,
        "ready_state": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def populate_action_fixture(conn: sqlite3.Connection) -> None:
    upsert_entity(
        conn,
        {
            "id": "loc:base",
            "type": "location",
            "name": "基地",
            "status": "active",
            "visibility": "known",
            "summary": "父地点。",
            "location": {"description_short": "基地", "exits": [], "resources": []},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "loc:start",
            "type": "location",
            "name": "Start",
            "status": "active",
            "visibility": "known",
            "summary": "当前地点。",
            "location": {"parent_id": "loc:base", "description_short": "Start", "exits": [], "resources": []},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "loc:yard",
            "type": "location",
            "name": "院子",
            "status": "active",
            "visibility": "known",
            "summary": "相邻院子。",
            "location": {"parent_id": "loc:base", "description_short": "Yard", "exits": [], "resources": []},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:berries",
            "type": "item",
            "name": "浆果",
            "status": "active",
            "visibility": "known",
            "location_id": "loc:start",
            "summary": "可采集浆果。",
            "aliases": ["Berry"],
            "item": {"category": "material", "quantity": 3, "unit": "把", "stackable": True},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:wood",
            "type": "item",
            "name": "木材",
            "status": "active",
            "visibility": "known",
            "location_id": "loc:start",
            "summary": "制作材料。",
            "aliases": ["wood"],
            "item": {"category": "material", "quantity": 5, "unit": "根", "stackable": True},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:trap",
            "type": "item",
            "name": "陷阱",
            "status": "active",
            "visibility": "known",
            "summary": "制作目标。",
            "aliases": ["trap"],
            "item": {"category": "tool", "quantity": 1, "unit": "个"},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "recipe:trap",
            "type": "recipe",
            "name": "陷阱配方",
            "status": "active",
            "visibility": "known",
            "summary": "制作陷阱的配方。",
            "aliases": ["trap recipe"],
            "details": {
                "recipe_profile": {
                    "inputs": [{"id": "item:wood"}],
                    "tools": [],
                    "output": {"id": "item:trap"},
                    "time_cost": "30m",
                }
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": "project:trap",
            "type": "project",
            "name": "陷阱项目",
            "status": "active",
            "visibility": "known",
            "summary": "已有制作项目。",
            "aliases": ["trap project"],
        },
    )
    upsert_entity(
        conn,
        {
            "id": "char:npc",
            "type": "character",
            "name": "邻居",
            "status": "active",
            "visibility": "known",
            "location_id": "loc:yard",
            "summary": "在院子的 NPC。",
            "aliases": ["Neighbor"],
            "character": {"role": "npc", "attitude": "neutral", "trust": 1, "health_state": "healthy"},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "threat:wolf",
            "type": "threat",
            "name": "狼",
            "status": "active",
            "visibility": "known",
            "location_id": "loc:start",
            "summary": "当前地点的威胁。",
            "aliases": ["Wolf"],
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:bow",
            "type": "item",
            "name": "弓",
            "status": "active",
            "visibility": "known",
            "owner_id": "pc:traveler",
            "summary": "测试武器。",
            "aliases": ["Bow"],
            "item": {
                "category": "weapon",
                "quantity": 1,
                "properties": {"combat_profile": {"ready_state": True, "risks": ["弦可能松动"]}},
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:arrow",
            "type": "item",
            "name": "箭",
            "status": "active",
            "visibility": "known",
            "owner_id": "pc:traveler",
            "summary": "测试弹药。",
            "aliases": ["Arrow"],
            "item": {
                "category": "ammunition",
                "quantity": 2,
                "unit": "支",
                "stackable": True,
                "properties": {"ammo_profile": {"compatible_weapon_id": "item:bow", "risks": ["噪音"], "effect_type": "impact_burst"}},
            },
        },
    )
    conn.execute(
        """
        insert or replace into routes
        (id, from_location_id, to_location_id, travel_minutes, difficulty, hazards_json, requirements_json)
        values ('route:start-yard', 'loc:start', 'loc:yard', 4, 'easy', '[]', '[]')
        """
    )
    conn.commit()


class PluginAdminToolingTests(unittest.TestCase):
    def test_plugin_manifest_discovery_loading_validation_and_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = Campaign(root=root, config={"id": "plugin-test"})
            plugins = root / "plugins"
            (plugins / "missing").mkdir(parents=True)
            good = plugins / "good"
            good.mkdir()
            (good / "plugin.yaml").write_text(
                yaml.safe_dump(
                    {
                        "id": "good-plugin",
                        "version": "1.0.0",
                        "engine_api_version": "1",
                        "enabled": True,
                        "capabilities": ["content_type", "importer"],
                        "entrypoint": "plugin:main",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            bad = plugins / "bad"
            bad.mkdir()
            (bad / "plugin.json").write_text('{"id": 3, "version": "", "engine_api_version": "2", "enabled": "yes", "capabilities": ["nope", ""]}', encoding="utf-8")
            broken = plugins / "broken"
            broken.mkdir()
            (broken / "plugin.yml").write_text("[not, object]", encoding="utf-8")

            manifests = discover_plugin_manifests(campaign)
            by_id = {manifest.id: manifest for manifest in manifests}
            failed_manifest_errors = [manifest.errors for manifest in manifests if manifest.errors]
            first_manifest_name = first_manifest_path(good).name

        self.assertEqual(first_manifest_name, "plugin.yaml")
        self.assertTrue(by_id["good-plugin"].ok)
        self.assertTrue(by_id["good-plugin"].enabled)
        self.assertEqual(by_id["good-plugin"].capabilities, ("content_type", "importer"))
        self.assertIn("plugin manifest is enabled", by_id["good-plugin"].warnings[0])
        self.assertIn("missing plugin manifest", by_id["missing"].errors)
        self.assertTrue(
            any("engine_api_version: unsupported 2" in error for errors in failed_manifest_errors for error in errors)
        )
        self.assertIn("cannot read manifest", by_id["broken"].errors[0])
        self.assertIn("good-plugin", render_plugin_list(manifests))
        self.assertIn("FAILED", render_plugin_validation(manifests))
        self.assertIn("no plugin manifests found", render_plugin_validation([]))
        self.assertIn("`none`", render_plugin_list([]))

    def test_manifest_shape_helpers_cover_json_yaml_and_bad_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "plugin.json"
            yaml_path = root / "plugin.yaml"
            list_path = root / "plugin.yml"
            json_path.write_text('{"id":"j","version":"1","engine_api_version":"1","capabilities":[]}', encoding="utf-8")
            yaml_path.write_text("id: y\nversion: '1'\nengine_api_version: '1'\ncapabilities: []\n", encoding="utf-8")
            list_path.write_text("- bad\n", encoding="utf-8")

            self.assertEqual(load_manifest_data(json_path)["id"], "j")
            self.assertEqual(load_manifest_data(yaml_path)["id"], "y")
            with self.assertRaisesRegex(ValueError, "manifest root must be object"):
                load_manifest_data(list_path)
            loaded = load_plugin_manifest(json_path)

        self.assertEqual(loaded.id, "j")
        errors, warnings = validate_manifest_data("bad")
        self.assertEqual(errors, ["manifest root must be object"])
        self.assertEqual(warnings, [])


class ContentFactoryToolingTests(unittest.TestCase):
    def test_make_content_delta_variants_and_file_output(self) -> None:
        material = make_content_delta(
            kind="material",
            entity_id="mat:salt",
            name="盐晶",
            summary="可测试的盐晶材料。",
            location_id="loc:start",
            rarity="rare",
            uses=["调味", "防腐"],
            risks=["吸潮"],
        )
        location = make_content_delta(
            kind="location",
            entity_id="loc:cave",
            name="洞穴",
            summary="临时生成的洞穴地点。",
            location_id="loc:start",
        )
        npc = make_content_delta(kind="npc", entity_id="char:new", name="新人", summary="临时 NPC。")

        self.assertEqual(material["upsert_entities"][0]["type"], "material")
        self.assertEqual(material["upsert_entities"][0]["location_id"], "loc:start")
        self.assertEqual(location["upsert_entities"][0]["type"], "location")
        self.assertNotIn("location_id", location["upsert_entities"][0])
        self.assertEqual(location["upsert_entities"][0]["location"]["parent_id"], "loc:start")
        self.assertEqual(npc["upsert_entities"][0]["type"], "character")
        self.assertEqual(kind_to_entity_type("recipe"), "recipe")
        self.assertEqual(base_details("species", location_id=None, rarity=None, uses=[], risks=[])["profile"]["habitat"], "待定")
        self.assertIn("contact_protocol", base_details("faction", location_id=None, rarity=None, uses=[], risks=[])["profile"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "delta.json"
            written = write_content_delta(material, path)
            inline = write_content_delta(material, None)

        self.assertEqual(written, str(path))
        self.assertIn('"mat:salt"', inline)

    def test_content_quality_audit_helpers_cover_recursive_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "mat:weak",
                        "type": "material",
                        "name": "短",
                        "status": "active",
                        "visibility": "known",
                        "summary": "短",
                        "details": {"note": "no discovery or uses"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "species:ok",
                        "type": "species",
                        "name": "有档案种",
                        "status": "active",
                        "visibility": "known",
                        "summary": "有足够摘要的测试物种。",
                        "aliases": ["测试物种"],
                        "details": {"profile": {"risks": ["低"], "discovery": {"clue": "脚印"}, "yields": ["纤维"]}},
                    },
                )
                conn.commit()
                findings = audit_content_quality(conn)

        rendered = render_content_quality(findings)
        self.assertTrue(any(finding.entity_id == "mat:weak" for finding in findings))
        self.assertIn("Content Quality Audit", rendered)
        self.assertIn("| OK |", render_content_quality([]))
        self.assertTrue(has_any_key({"risks": []}, ["risks"]))
        self.assertTrue(contains_key_recursive({"a": [{"discovery": True}]}, "discovery"))
        self.assertFalse(contains_key_recursive("plain", "discovery"))
        self.assertTrue(has_uses({"profile": {"用途": ["建造"]}}))
        self.assertFalse(has_uses({"profile": {"risk": "none"}}))
        self.assertEqual(split_csv("a， b;c；d,, "), ["a", "b", "c", "d"])
        self.assertEqual(split_csv(None), [])


class OpsReflectionSimulationToolingTests(unittest.TestCase):
    def test_ops_report_and_simulation_reports_cover_empty_and_speed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_path)
            with connect(campaign) as conn:
                self.assertTrue(table_exists(conn, "entities"))
                self.assertIsNotNone(table_count_sql(conn, "entities"))
                report = build_ops_report(campaign, conn, run_speed=True)
                output = write_ops_report(campaign, conn, None, run_speed=False)
                output_exists = output.exists()
                self.assertEqual(ops_scalar(conn, "select count(*) from turns where id='missing'"), 0)

            sim = run_long_simulation(campaign_path, turns=0, budget=500)
            sim_report = render_simulation_report(
                turns=2,
                timings=[0.1, 0.3],
                estimates=[10, 30],
                section_counts={"b": 1, "a": 2},
                max_loaded=3,
                memory_count=4,
                event_count=5,
                errors=["bad"],
                temp_dir="/tmp/sim",
            )
            sim_output = write_simulation_report(campaign_path, Path(tmp) / "sim.md", turns=0, budget=500)
            sim_output_exists = sim_output.exists()

        self.assertIn("运维报告", report)
        self.assertIn("Speed Sample", report)
        self.assertTrue(output_exists)
        self.assertEqual(sim.turns, 0)
        self.assertIn("check_errors | 1", sim_report)
        self.assertIn("## Check Errors", sim_report)
        self.assertTrue(sim_output_exists)
        delta = synthetic_turn_delta(1, "look", {"request": {"mode": "query", "submode": "scene"}, "budget": {"estimated": 12}, "sections": {"scene": {}}})
        self.assertEqual(delta["events"][0]["payload"]["sections"], ["scene"])

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("create table x (value integer)")
            self.assertFalse(table_exists(conn, "missing"))
            self.assertIsNone(table_count_sql(conn, "missing"))
            self.assertEqual(simulation_scalar(conn, "select count(*) from x"), 0)
        finally:
            conn.close()

    def test_reflection_draft_ai_validation_and_related_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                save_turn_delta(
                    campaign,
                    conn,
                    {
                        "user_text": "记录 Traveler",
                        "intent": "note",
                        "changed": True,
                        "summary": "Traveler 进行了测试事件。",
                        "events": [
                            {
                                "type": "note",
                                "title": "Traveler 事件",
                                "summary": "Traveler 被记录进事件。",
                                "payload": {"subject_id": "pc:traveler"},
                                "source": "test",
                            }
                        ],
                    },
                )
                subject = conn.execute("select * from entities where id='pc:traveler'").fetchone()
                events = related_events(conn, "pc:traveler", "Traveler", limit=4)
                deterministic = draft_reflection(campaign, conn, subject_id="pc:traveler")
                missing = draft_reflection(campaign, conn, subject_id="missing")
                unsupported = draft_reflection(campaign, conn, subject_id="pc:traveler", ai="other")
                failed = validate_reflection_draft(None, subject, [], ai_status="failed")
                invalid = validate_reflection_draft(
                    {"title": "T" * 100, "summary": "", "key_points": [], "source_event_ids": ["event:bad"]},
                    subject,
                    [row["id"] for row in events],
                    ai_status="ok",
                )
                with mock.patch(
                    "rpg_engine.reflection.run_ai_helper_json",
                    return_value=SimpleNamespace(ok=True, parsed={"title": "AI", "summary": "摘要", "key_points": ["点"], "source_event_ids": [events[0]["id"]]}),
                ):
                    ai = draft_reflection(campaign, conn, subject_id="pc:traveler", ai="hermes")

        self.assertIn("Reflection Draft", deterministic.render())
        self.assertEqual(missing.errors, ["missing subject: missing"])
        self.assertIn("unsupported ai backend", unsupported.errors[0])
        self.assertIn("AI reflection failed", failed.errors[0])
        self.assertIn("summary is required", invalid.errors)
        self.assertIn("key_points is required", invalid.errors)
        self.assertTrue(any("non-allowed" in item for item in invalid.errors))
        self.assertEqual(ai.ai_status, "ok")
        self.assertEqual(ai.source_event_ids, [events[0]["id"]])
        self.assertEqual(format_value(["a", {"b": [1, 2, 3, 4, 5]}]), "a；b=1；2；3；4")
        self.assertTrue(trim("x" * 20, 6).endswith("…"))


class SavePatchAndTurnAssistantToolingTests(unittest.TestCase):
    def test_save_patch_validation_file_loading_and_safe_values(self) -> None:
        bad_patch = {
            "unknown": True,
            "patch_schema_version": "2",
            "reason": "",
            "operations": [
                "bad",
                {"op": "bad", "entity_id": ""},
                {"op": "set_entity_name", "entity_id": "", "name": ""},
                {"op": "set_entity_summary", "entity_id": "x", "summary": ""},
                {"op": "set_entity_visibility", "entity_id": "x", "visibility": "public"},
                {"op": "add_entity_alias", "entity_id": "x", "alias": ""},
                {"op": "set_entity_detail", "entity_id": "x", "key": "location_id", "value": object()},
                {"op": "remove_entity_detail", "entity_id": "x", "key": "bad key"},
                {"op": "set_character_field", "entity_id": "x", "field": "unknown", "value": True},
                {"op": "set_character_field", "entity_id": "x", "field": "trust", "value": True},
                {"op": "set_character_field", "entity_id": "x", "field": "attitude", "value": ""},
            ],
        }

        errors = validate_save_patch(bad_patch)

        self.assertIn("$.unknown: unknown top-level field", errors)
        self.assertIn("$.patch_schema_version: unsupported version 2", errors)
        self.assertIn("$.operations[0]: must be object", errors)
        self.assertIn("$.operations[2].entity_id: required non-empty string", errors)
        self.assertTrue(
            any(error.startswith("$.operations[4].visibility: must be ") and "gm" in error for error in errors),
            errors,
        )
        for schema_path in (
            ENGINE_ROOT / "schemas" / "save_patch.schema.json",
            ENGINE_ROOT / "rpg_engine" / "resources" / "schemas" / "save_patch.schema.json",
        ):
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            visibility_branch = next(
                branch
                for branch in schema["properties"]["operations"]["items"]["oneOf"]
                if branch["properties"]["op"].get("const") == "set_entity_visibility"
            )
            visibility_enum = visibility_branch["properties"]["visibility"]["enum"]
            self.assertIn("gm", visibility_enum)
            self.assertIn("gm-only", visibility_enum)
        self.assertIn("$.operations[6].key: protected gameplay field cannot be patched through details", errors)
        self.assertIn("$.operations[8].field: must be attitude/trust/health_state", errors)
        self.assertIn("$.operations[9].value: trust must be integer", errors)
        self.assertFalse(is_safe_detail_value({"bad key": "x"}))
        self.assertFalse(is_safe_detail_value([0] * 101))
        deep: object = {"a": {"b": {"c": {"d": {"e": {"f": "too deep"}}}}}}
        self.assertFalse(is_safe_detail_value(deep))
        self.assertTrue(is_safe_detail_value({"ok": [None, "x", 1, 1.5, False]}))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            json_path = root / "patch.json"
            yaml_path = root / "patch.yaml"
            list_path = root / "patch.json"
            json_path.write_text('{"operations":[]}', encoding="utf-8")
            self.assertEqual(load_patch_file(json_path)["operations"], [])
            yaml_path.write_text("operations: []\n", encoding="utf-8")
            self.assertEqual(load_patch_file(yaml_path)["operations"], [])
            list_path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "save patch file must contain an object"):
                load_patch_file(list_path)

    def test_apply_save_patch_operations_and_render_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            patch = {
                "patch_schema_version": "1",
                "reason": "test",
                "operations": [
                    {"op": "set_entity_name", "entity_id": "pc:traveler", "name": "Traveler Prime"},
                    {"op": "set_entity_summary", "entity_id": "pc:traveler", "summary": "Updated summary."},
                    {"op": "set_entity_visibility", "entity_id": "pc:traveler", "visibility": "hinted"},
                    {"op": "add_entity_alias", "entity_id": "pc:traveler", "alias": "Prime"},
                    {"op": "remove_entity_alias", "entity_id": "pc:traveler", "alias": "player"},
                    {"op": "set_entity_detail", "entity_id": "pc:traveler", "key": "note", "value": {"ok": True}},
                    {"op": "remove_entity_detail", "entity_id": "pc:traveler", "key": "note"},
                    {"op": "set_character_field", "entity_id": "pc:traveler", "field": "trust", "value": 2},
                    {"op": "set_character_field", "entity_id": "pc:traveler", "field": "attitude", "value": "calm"},
                ],
            }
            result = apply_save_patch(campaign, patch, backup=False)
            missing = apply_save_patch(
                campaign,
                {"patch_schema_version": "1", "operations": [{"op": "set_entity_name", "entity_id": "missing", "name": "x"}]},
                backup=False,
            )
            with connect(campaign) as conn:
                row = conn.execute("select name, visibility from entities where id='pc:traveler'").fetchone()
                character = conn.execute("select trust, attitude from characters where entity_id='pc:traveler'").fetchone()
                details = entity_details(conn, "pc:traveler")
                with self.assertRaisesRegex(ValueError, "entity is not a character"):
                    apply_operation(
                        conn,
                        {"op": "set_character_field", "entity_id": "loc:start", "field": "trust", "value": 1},
                        current_turn_id="turn:seed",
                        now="now",
                    )
                with self.assertRaisesRegex(ValueError, "unsupported operation"):
                    apply_operation(conn, {"op": "unsupported", "entity_id": "pc:traveler"}, current_turn_id="turn:seed", now="now")

        self.assertTrue(result.ok, result.render())
        self.assertEqual(row["name"], "Traveler Prime")
        self.assertEqual(row["visibility"], "hinted")
        self.assertEqual(character["trust"], 2)
        self.assertEqual(character["attitude"], "calm")
        self.assertNotIn("note", details)
        self.assertIn("Save Patch", result.render())
        self.assertFalse(missing.ok)
        self.assertIn("missing entity", missing.render())
        failed = SavePatchResult(campaign_id="x", ok=False, errors=("bad",), warnings=("warn",))
        self.assertIn("FAILED", failed.render())
        self.assertIn("error_details", failed.to_dict())

    def test_apply_save_patch_visibility_tolerates_missing_world_settings_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table world_settings")
                conn.commit()

            result = apply_save_patch(
                campaign,
                {
                    "patch_schema_version": "1",
                    "reason": "missing world_settings table visibility sync",
                    "operations": [
                        {"op": "set_entity_visibility", "entity_id": "pc:traveler", "visibility": "hinted"},
                    ],
                },
                backup=False,
            )
            with connect(campaign) as conn:
                row = conn.execute("select visibility from entities where id='pc:traveler'").fetchone()

        self.assertTrue(result.ok, result.render())
        self.assertEqual(row["visibility"], "hinted")

    def test_turn_assistant_branch_helpers_and_save_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            delta_path = Path(tmp) / "delta.json"
            delta_path.write_text(json.dumps(wait_delta(), ensure_ascii=False), encoding="utf-8")
            bad_delta_path = Path(tmp) / "bad-delta.json"
            bad_delta_path.write_text(json.dumps({"user_text": "", "intent": "", "summary": ""}), encoding="utf-8")
            response_path = Path(tmp) / "response.md"
            response_path.write_text(
                "## 场景\n安静。\n## 行动结果\n等待。\n## 状态变化\n| 类型 | 项目 | 变化 |\n| --- | --- | --- |\n| 无 | 无 | 无 |\n## 保存状态\n尚未保存。\n## 后续行动\n| # | 行动 |\n| --- | --- |\n| 1 | 继续 |\n",
                encoding="utf-8",
            )
            with connect(campaign) as conn:
                no_delta_text, no_delta_errors, no_delta = render_delta_validation_for_options(conn, TurnAssistantOptions(user_text="x"))
                ok_text, ok_errors, ok_delta = render_delta_validation_for_options(conn, TurnAssistantOptions(user_text="x", delta_json=str(delta_path)))
                bad_text, bad_errors, bad_delta = render_delta_validation_for_options(conn, TurnAssistantOptions(user_text="x", delta_json=str(bad_delta_path)))
                no_save_delta = run_save_pipeline(campaign, conn, TurnAssistantOptions(user_text="x", save=True), None, [])
                blocked_save = run_save_pipeline(
                    campaign,
                    conn,
                    TurnAssistantOptions(user_text="x", save=True, delta_json=str(delta_path)),
                    ok_delta,
                    ["bad schema"],
                )
                saved = run_save_pipeline(
                    campaign,
                    conn,
                    TurnAssistantOptions(user_text="x", save=True, delta_json=str(delta_path)),
                    ok_delta,
                    [],
                )
                linted = render_response_lint(
                    minimal_context(),
                    TurnAssistantOptions(user_text="x", response_file=str(response_path)),
                )
                saved_turn = current_turn(campaign.root)

        self.assertIn("跳过 schema", no_delta_text)
        self.assertEqual(no_delta_errors, [])
        self.assertIsNone(no_delta)
        self.assertEqual(ok_text, "OK")
        self.assertEqual(ok_errors, [])
        self.assertTrue(ok_delta)
        self.assertIn("FAILED", bad_text)
        self.assertTrue(bad_errors)
        self.assertTrue(bad_delta)
        self.assertIn("--save requires --delta-json", no_save_delta)
        self.assertIn("delta schema validation failed", blocked_save)
        self.assertIn("saved_turn", saved)
        self.assertEqual(saved_turn, "turn:000001")
        self.assertIn("OK", linted)

        cases = [
            (minimal_context(allow=False), TurnAssistantOptions(user_text="x"), "先向玩家确认缺失信息"),
            (minimal_context(mode="query", submode="scene"), TurnAssistantOptions(user_text="x"), "不保存"),
            (minimal_context(), TurnAssistantOptions(user_text="x"), "补充 preview 参数"),
            (minimal_context(), TurnAssistantOptions(user_text="x", response_text="ok", delta_json=str(delta_path)), "显式加 `--save`"),
            (
                minimal_context(),
                TurnAssistantOptions(user_text="x", response_text="ok", delta_json=str(delta_path), save=True),
                "保存后继续下一轮",
            ),
        ]
        for context, options, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, "\n".join(render_next_steps(context, options, preview_ran=False, delta_errors=[])))
        self.assertIn("修复 delta schema", "\n".join(render_next_steps(minimal_context(), TurnAssistantOptions(user_text="x", response_text="ok", delta_json=str(delta_path)), True, ["bad"])))


class MemoryBackupAndWorldSettingCoverageTests(unittest.TestCase):
    def test_memory_table_schema_backfills_provenance_and_freshness_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            create table entities(id text primary key);
            create table turns(id text primary key);
            create table memory_summaries (
              id text primary key,
              kind text not null,
              subject_id text,
              title text not null,
              summary text not null,
              key_points_json text not null default '[]',
              source_event_ids_json text not null default '[]',
              source_turn_ids_json text not null default '[]',
              valid_from_turn text,
              valid_to_turn text,
              updated_at text not null,
              foreign key(subject_id) references entities(id),
              foreign key(valid_from_turn) references turns(id),
              foreign key(valid_to_turn) references turns(id)
            );
            """
        )

        ensure_memory_tables(conn)
        columns = {row["name"] for row in conn.execute("pragma table_info(memory_summaries)").fetchall()}

        self.assertTrue(
            {
                "summary_type",
                "visibility_mode",
                "freshness_status",
                "freshness_turn_id",
                "stale_reason",
                "freshness_evidence_json",
                "derived_authority_json",
            }.issubset(columns)
        )

    def test_memory_metadata_migration_tolerates_helper_backfilled_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(read_resource_text("migrations", "0001_init.sql"))
        ensure_schema_migrations(conn)
        for path in migration_files():
            mid = migration_id(path)
            if mid != "0009_memory_summary_provenance":
                conn.execute(
                    "insert or ignore into schema_migrations(id, applied_at) values(?, ?)",
                    (mid, "2026-07-10T00:00:00+00:00"),
                )
        ensure_memory_tables(conn)

        applied = apply_pending_migrations(conn)
        columns = {row["name"] for row in conn.execute("pragma table_info(memory_summaries)").fetchall()}

        self.assertEqual([record.id for record in applied], ["0009_memory_summary_provenance"])
        self.assertIn("0009_memory_summary_provenance", {
            row["id"] for row in conn.execute("select id from schema_migrations").fetchall()
        })
        self.assertTrue(
            {
                "summary_type",
                "visibility_mode",
                "freshness_status",
                "freshness_turn_id",
                "stale_reason",
                "freshness_evidence_json",
                "derived_authority_json",
            }.issubset(columns)
        )

    def test_memory_metadata_migration_rejects_incompatible_existing_column(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(read_resource_text("migrations", "0001_init.sql"))
        ensure_schema_migrations(conn)
        for path in migration_files():
            mid = migration_id(path)
            if mid != "0009_memory_summary_provenance":
                conn.execute(
                    "insert or ignore into schema_migrations(id, applied_at) values(?, ?)",
                    (mid, "2026-07-10T00:00:00+00:00"),
                )
        conn.execute(
            "alter table memory_summaries add column summary_type integer not null default 99"
        )
        conn.commit()

        with self.assertRaisesRegex(sqlite3.OperationalError, "incompatible existing column"):
            apply_pending_migrations(conn)

        self.assertFalse(
            conn.execute(
                "select 1 from schema_migrations where id = '0009_memory_summary_provenance'"
            ).fetchone()
        )

    def test_memory_metadata_migration_accepts_casefolded_compatible_column(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(read_resource_text("migrations", "0001_init.sql"))
        ensure_schema_migrations(conn)
        for path in migration_files():
            mid = migration_id(path)
            if mid != "0009_memory_summary_provenance":
                conn.execute(
                    "insert or ignore into schema_migrations(id, applied_at) values(?, ?)",
                    (mid, "2026-07-10T00:00:00+00:00"),
                )
        conn.execute(
            "alter table memory_summaries add column SUMMARY_TYPE text not null default 'deterministic'"
        )
        conn.commit()

        applied = apply_pending_migrations(conn)

        self.assertEqual([record.id for record in applied], ["0009_memory_summary_provenance"])
        self.assertEqual(
            sum(
                1
                for row in conn.execute("pragma table_info(memory_summaries)").fetchall()
                if str(row["name"]).casefold() == "summary_type"
            ),
            1,
        )

    def test_memory_metadata_migration_normalizes_null_default_and_rejects_authority_escalation(self) -> None:
        def legacy_conn() -> sqlite3.Connection:
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.executescript(read_resource_text("migrations", "0001_init.sql"))
            ensure_schema_migrations(conn)
            for path in migration_files():
                mid = migration_id(path)
                if mid != "0009_memory_summary_provenance":
                    conn.execute(
                        "insert or ignore into schema_migrations(id, applied_at) values(?, ?)",
                        (mid, "2026-07-10T00:00:00+00:00"),
                    )
            return conn

        compatible = legacy_conn()
        compatible.execute(
            "alter table memory_summaries add column freshness_turn_id text default null"
        )
        compatible.commit()

        applied = apply_pending_migrations(compatible)

        self.assertEqual([record.id for record in applied], ["0009_memory_summary_provenance"])

        incompatible = legacy_conn()
        incompatible.execute(
            """
            alter table memory_summaries add column derived_authority_json text not null
            default '{"authority":"derived_context","fact_authority":false,"summary_overrides_facts":true}'
            """
        )
        incompatible.commit()

        with self.assertRaisesRegex(sqlite3.OperationalError, "incompatible existing column"):
            apply_pending_migrations(incompatible)

    def test_memory_metadata_migration_rejects_temp_shadow_constraints_and_numeric_boolean(self) -> None:
        def legacy_conn() -> sqlite3.Connection:
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.executescript(read_resource_text("migrations", "0001_init.sql"))
            ensure_schema_migrations(conn)
            for path in migration_files():
                mid = migration_id(path)
                if mid != "0009_memory_summary_provenance":
                    conn.execute(
                        "insert or ignore into schema_migrations(id, applied_at) values(?, ?)",
                        (mid, "2026-07-10T00:00:00+00:00"),
                    )
            return conn

        temp_shadow = legacy_conn()
        temp_shadow.execute("create temp table memory_summaries(id text primary key)")
        with self.assertRaisesRegex(sqlite3.OperationalError, "TEMP schema shadows"):
            apply_pending_migrations(temp_shadow)
        self.assertNotIn(
            "summary_type",
            {row["name"] for row in temp_shadow.execute("pragma main.table_info(memory_summaries)")},
        )
        self.assertIsNone(
            temp_shadow.execute(
                "select 1 from schema_migrations where id='0009_memory_summary_provenance'"
            ).fetchone()
        )

        constrained = legacy_conn()
        constrained.execute(
            "alter table memory_summaries add column freshness_status text not null "
            "default 'fresh' check(freshness_status='fresh')"
        )
        constrained.commit()
        with self.assertRaisesRegex(sqlite3.OperationalError, "incompatible existing column"):
            apply_pending_migrations(constrained)

        numeric_boolean = legacy_conn()
        numeric_boolean.execute(
            "alter table memory_summaries add column derived_authority_json text not null "
            "default '{\"authority\":\"derived_context\",\"fact_authority\":0}'"
        )
        numeric_boolean.commit()
        with self.assertRaisesRegex(sqlite3.OperationalError, "incompatible existing column"):
            apply_pending_migrations(numeric_boolean)

    def test_fresh_migration_chain_installs_complete_memory_metadata_contract(self) -> None:
        fresh = sqlite3.connect(":memory:")
        fresh.row_factory = sqlite3.Row

        applied = apply_pending_migrations(fresh)
        fresh_columns = {
            str(row["name"])
            for row in fresh.execute(
                "pragma main.table_info('memory_summaries')"
            ).fetchall()
        }

        helper = sqlite3.connect(":memory:")
        helper.row_factory = sqlite3.Row
        helper.executescript(read_resource_text("migrations", "0001_init.sql"))
        ensure_memory_tables(helper)
        helper_columns = {
            str(row["name"])
            for row in helper.execute(
                "pragma main.table_info('memory_summaries')"
            ).fetchall()
        }

        self.assertIn("0009_memory_summary_provenance", [record.id for record in applied])
        self.assertTrue(memory_metadata_columns_present(fresh))
        self.assertTrue(memory_metadata_columns_present(helper))
        self.assertEqual(
            fresh_columns & memory_module.MEMORY_METADATA_COLUMN_NAMES,
            helper_columns & memory_module.MEMORY_METADATA_COLUMN_NAMES,
        )
        self.assertIsNotNone(
            fresh.execute(
                "select 1 from main.schema_migrations "
                "where id='0009_memory_summary_provenance'"
            ).fetchone()
        )

    def test_memory_migration_ledger_and_statement_targets_ignore_temp_hijacks(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "create temp table schema_migrations(id text primary key, applied_at text)"
        )
        conn.execute(
            "insert into temp.schema_migrations values"
            "('0009_memory_summary_provenance', '2099-01-01T00:00:00+00:00')"
        )

        ensure_schema_migrations(conn)

        self.assertIsNone(
            conn.execute(
                "select 1 from main.schema_migrations "
                "where id='0009_memory_summary_provenance'"
            ).fetchone()
        )
        conn.execute("create table main.meta(key text primary key, value text not null)")
        conn.execute("create temp table meta(key text primary key, value text not null)")
        with self.assertRaisesRegex(sqlite3.OperationalError, "TEMP schema shadows"):
            execute_migration_statement(
                conn,
                "insert into meta(key, value) values('schema_version', 'bad')",
            )
        self.assertIsNone(
            conn.execute(
                "select 1 from main.meta where key='schema_version'"
            ).fetchone()
        )

    def test_late_memory_migration_failure_rolls_back_all_prior_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(read_resource_text("migrations", "0001_init.sql"))
        ensure_schema_migrations(conn)
        for path in migration_files():
            mid = migration_id(path)
            if mid != "0009_memory_summary_provenance":
                conn.execute(
                    "insert or ignore into main.schema_migrations(id, applied_at) values(?, ?)",
                    (mid, "2026-07-10T00:00:00+00:00"),
                )
        conn.execute(
            "alter table main.memory_summaries add column derived_authority_json "
            "text not null default '{\"authority\":\"fact\",\"fact_authority\":true}'"
        )
        conn.commit()
        before = {
            str(row["name"])
            for row in conn.execute(
                "pragma main.table_info('memory_summaries')"
            ).fetchall()
        }

        with self.assertRaisesRegex(sqlite3.OperationalError, "incompatible existing column"):
            apply_pending_migrations(conn)

        after = {
            str(row["name"])
            for row in conn.execute(
                "pragma main.table_info('memory_summaries')"
            ).fetchall()
        }
        self.assertEqual(after, before)
        self.assertIsNone(
            conn.execute(
                "select 1 from main.schema_migrations "
                "where id='0009_memory_summary_provenance'"
            ).fetchone()
        )

    def test_memory_helper_and_migration_reject_executable_schema_extensions_atomically(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            create table entities(id text primary key);
            create table turns(id text primary key);
            create table memory_summaries(
              id text primary key,
              kind integer not null,
              subject_id text
            );
            """
        )
        with self.assertRaisesRegex(
            sqlite3.OperationalError,
            "schema contract|incompatible existing column",
        ):
            ensure_memory_tables(conn)
        self.assertIsNone(
            conn.execute(
                "select 1 from main.sqlite_master "
                "where type='index' and name='idx_memory_kind_subject'"
            ).fetchone()
        )

        harmless = sqlite3.connect(":memory:")
        harmless.execute(
            "create table memory_summaries("
            "id text primary key, kind text default 'check(', subject_id text)"
        )
        self.assertFalse(
            additive_column_has_write_blocking_constraints(
                harmless,
                table="memory_summaries",
                column="summary_type",
            )
        )

        blocked = sqlite3.connect(":memory:")
        blocked.execute(
            "create table memory_summaries("
            "id text primary key, kind text collate nocase, subject_id text, "
            "check /* executable gap */ (length(kind) > 0))"
        )
        self.assertTrue(
            additive_column_has_write_blocking_constraints(
                blocked,
                table="memory_summaries",
                column="summary_type",
            )
        )

    def test_memory_helper_prevalidates_metadata_and_requires_schema_contract(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            create table entities(id text primary key);
            create table turns(id text primary key);
            create table memory_summaries (
              id text primary key,
              kind text not null,
              subject_id text,
              title text not null,
              summary text not null,
              key_points_json text not null default '[]',
              source_event_ids_json text not null default '[]',
              source_turn_ids_json text not null default '[]',
              valid_from_turn text,
              valid_to_turn text,
              derived_authority_json integer not null default 0,
              updated_at text not null,
              foreign key(subject_id) references entities(id),
              foreign key(valid_from_turn) references turns(id),
              foreign key(valid_to_turn) references turns(id)
            );
            create index idx_memory_kind_subject on memory_summaries(kind, subject_id);
            """
        )

        with self.assertRaisesRegex(sqlite3.OperationalError, "derived_authority_json"):
            ensure_memory_tables(conn)

        columns = {
            row["name"] for row in conn.execute("pragma main.table_info(memory_summaries)")
        }
        self.assertNotIn("summary_type", columns)
        self.assertNotIn("freshness_evidence_json", columns)

    def test_memory_schema_rejects_case_variant_triggers_missing_fk_and_missing_lookup_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    "create trigger mixed_case_memory_trigger before insert on Memory_Summaries "
                    "begin select 1; end"
                )
                mixed_case_trigger_ready = memory_metadata_columns_present(conn)
                conn.execute("drop trigger mixed_case_memory_trigger")

                conn.execute("drop index idx_memory_kind_subject")
                missing_index_ready = memory_metadata_columns_present(conn)
                conn.execute(
                    "create index idx_memory_kind_subject on memory_summaries(kind, subject_id)"
                )

                schema_sql = str(
                    conn.execute(
                        "select sql from main.sqlite_master "
                        "where type='table' and name='memory_summaries'"
                    ).fetchone()[0]
                )
                conn.execute("pragma foreign_keys=off")
                conn.execute("alter table memory_summaries rename to memory_summaries_original")
                without_subject_fk = schema_sql.replace(
                    ",\n          foreign key(subject_id) references entities(id)",
                    "",
                    1,
                )
                conn.execute(without_subject_fk)
                conn.execute(
                    "create index idx_memory_kind_subject_v2 "
                    "on memory_summaries(kind, subject_id)"
                )
                missing_fk_ready = memory_metadata_columns_present(conn)

        self.assertFalse(mixed_case_trigger_ready)
        self.assertFalse(missing_index_ready)
        self.assertFalse(missing_fk_ready)

    def test_partial_memory_schema_returns_sanitized_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table memory_summaries")
                conn.execute(
                    """
                    create table memory_summaries (
                      id text primary key,
                      summary_type text not null default 'deterministic',
                      visibility_mode text not null default 'player',
                      freshness_status text not null default 'fresh',
                      freshness_turn_id text,
                      stale_reason text not null default '',
                      freshness_evidence_json text not null default '{}',
                      derived_authority_json text not null default '{}'
                    )
                    """
                )

                loaded = find_relevant_memories(conn, targets=["anything"], view="player", limit=4)
                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="player",
                    limit=4,
                )
                no_items = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="player",
                    limit=0,
                )

        self.assertEqual(loaded, [])
        self.assertEqual(no_items, [])
        self.assertEqual(len(omitted), 1)
        self.assertEqual(omitted[0]["stale_reason"], "missing_memory_metadata_columns")
        self.assertIn("kind", json.loads(omitted[0]["freshness_evidence_json"])["missing_columns"])

    def test_memory_schema_visibility_and_projection_rows_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'failed', '2026-07-10T00:00:00+00:00', ?)
                    """,
                    (sqlite3.Binary(b"broken\x00projection"),),
                )
                blob_omissions = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="maintenance",
                    limit=4,
                )

                conn.execute("drop table memory_summaries")
                conn.execute(
                    """
                    create table memory_summaries (
                      id text primary key, kind text not null, subject_id text, title text not null,
                      summary text not null, key_points_json text not null default '[]',
                      source_event_ids_json text not null default '[]',
                      source_turn_ids_json text not null default '[]', valid_from_turn text,
                      valid_to_turn text, summary_type text not null default 'deterministic',
                      visibility_mode text default null, freshness_status text not null default 'fresh',
                      freshness_turn_id text, stale_reason text not null default '',
                      freshness_evidence_json text not null default '{}',
                      derived_authority_json text not null default '{"authority":"derived_context","fact_authority":false}',
                      updated_at text not null
                    )
                    """
                )
                insert_test_memory(conn, id="memory:empty-visibility", visibility_mode="")
                schema_ready = memory_metadata_columns_present(conn)
                loaded = find_relevant_memories(
                    conn,
                    targets=["Test memory"],
                    view="player",
                    limit=4,
                )

                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state (
                      name text, version integer, last_turn_id text, status text,
                      updated_at text, last_error text
                    )
                    """
                )
                conn.executemany(
                    "insert into projection_state values('memory', 1, 'turn:seed', ?, '2026-07-10T00:00:00+00:00', ?)",
                    [("clean", None), ("failed", "broken")],
                )
                duplicate_health = memory_projection_health(conn)

        self.assertTrue(blob_omissions)
        self.assertFalse(schema_ready)
        self.assertEqual(loaded, [])
        self.assertEqual(duplicate_health["status"], "stale")

    def test_memory_projection_refreshes_when_schema_migration_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'clean',
                           '2026-07-10T00:00:00+00:00', null)
                    """
                )
                conn.execute(
                    """
                    update schema_migrations
                    set applied_at = '2026-07-10T01:00:00+00:00'
                    where id = '0009_memory_summary_provenance'
                    """
                )
                insert_test_memory(
                    conn,
                    id="memory:legacy-before-schema-upgrade",
                    freshness_turn_id=None,
                    freshness_evidence_json="{}",
                )

                before = memory_projection_health(conn)
                report = ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=True,
                    include_outbox=False,
                    profile="test:memory_schema_upgrade",
                )
                after = memory_projection_health(conn)

        self.assertEqual(before["status"], "stale")
        self.assertIn("memory", report.refreshed)
        self.assertEqual(after["status"], "clean")

    def test_memory_projection_refreshes_legacy_rows_with_sources_or_bad_migration_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(
                    conn,
                    id="memory:legacy-with-source-turn",
                    source_turn_ids_json=json.dumps(["turn:seed"]),
                    freshness_turn_id=None,
                    freshness_evidence_json="{}",
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'clean', '2026-07-10T00:00:00+00:00', null)
                    """
                )
                conn.execute(
                    """
                    update schema_migrations
                    set applied_at = '2026-07-10T01:00:00+00:00'
                    where id = '0009_memory_summary_provenance'
                    """
                )
                newer_migration = memory_projection_health(conn)

                conn.execute(
                    "delete from schema_migrations where id = '0009_memory_summary_provenance'"
                )
                missing_migration = memory_projection_health(conn)

                conn.execute(
                    "insert into schema_migrations(id, applied_at) values(?, ?)",
                    (
                        "0009_memory_summary_provenance",
                        sqlite3.Binary(b"invalid-migration-time"),
                    ),
                )
                corrupt_migration = memory_projection_health(conn)

        self.assertEqual(newer_migration["status"], "stale")
        self.assertEqual(missing_migration["status"], "stale")
        self.assertEqual(corrupt_migration["status"], "stale")

    def test_direct_memory_rebuild_reconciles_orphaned_refreshing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'refreshing',
                           '2026-07-10T00:00:00+00:00', null)
                    """
                )
                conn.commit()

                rebuild_memory_summaries(campaign, conn)
                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "clean")

    def test_direct_memory_rebuild_does_not_mark_newer_turn_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                original_write_report = write_memory_report

                def advance_turn_after_report(*args: object, **kwargs: object) -> Path:
                    path = original_write_report(*args, **kwargs)
                    conn.execute(
                        """
                        insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                        values('turn:after-memory-build', 's', 'advance', 'note', 'advance', 1,
                               '2099-01-01T00:00:00+00:00')
                        """
                    )
                    conn.execute(
                        "update meta set value='turn:after-memory-build' where key='current_turn_id'"
                    )
                    return path

                with mock.patch(
                    "rpg_engine.memory.write_memory_report",
                    side_effect=advance_turn_after_report,
                ):
                    rebuild_memory_summaries(campaign, conn)
                health = memory_projection_health(conn)

        self.assertNotEqual(health["status"], "clean")

    def test_direct_memory_rebuild_report_failure_marks_owned_generation_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                rebuild_memory_summaries(campaign, conn)

                with (
                    mock.patch("rpg_engine.memory.build_memory_records", return_value=[]),
                    mock.patch(
                        "rpg_engine.memory.write_memory_report",
                        side_effect=OSError("memory report failed"),
                    ),
                    self.assertRaisesRegex(OSError, "memory report failed"),
                ):
                    rebuild_memory_summaries(campaign, conn)
                health = memory_projection_health(conn)

        self.assertNotEqual(health["status"], "clean")

    def test_memory_storage_visibility_scans_all_freshness_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-freshness-turn-probe",
                        "type": "item",
                        "name": "Hidden Freshness Turn Probe",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden.",
                    },
                )
                conn.execute(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values('turn:hidden-freshness-evidence', 's', 'item:hidden-freshness-turn-probe',
                           'note', 'item:hidden-freshness-turn-probe', 1,
                           '2026-07-10T00:00:00+00:00')
                    """
                )
                conn.execute(
                    "update meta set value='turn:hidden-freshness-evidence' where key='current_turn_id'"
                )

                metadata = memory_summary_metadata(
                    conn,
                    {
                        "id": "memory:hidden-freshness-turn",
                        "kind": "world",
                        "title": "Safe title",
                        "summary": "Safe summary",
                        "key_points": [],
                        "source_event_ids": [],
                        "source_turn_ids": [],
                    },
                )

        self.assertEqual(metadata["visibility_mode"], "maintenance")

    def test_legacy_memory_rows_without_freshness_turn_are_omitted_when_subject_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values
                      ('turn:legacy-memory-old', 's', 'old', 'note', 'old', 1, '2024-01-01T00:00:00+00:00'),
                      ('turn:legacy-memory-new', 's', 'new', 'note', 'new', 1, '2024-01-02T00:00:00+00:00')
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:legacy-memory-subject",
                        "type": "item",
                        "name": "Legacy Memory Subject",
                        "status": "active",
                        "visibility": "known",
                        "summary": "SQLite fact is newer.",
                        "updated_turn_id": "turn:legacy-memory-new",
                    },
                )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:legacy-no-freshness-turn",
                        "project",
                        "item:legacy-memory-subject",
                        "Legacy Memory Subject",
                        "Old summary",
                        "[]",
                        "[]",
                        json.dumps(["turn:legacy-memory-old"], ensure_ascii=False),
                        "turn:legacy-memory-old",
                        None,
                        "deterministic_project",
                        "player",
                        "fresh",
                        None,
                        "",
                        json.dumps({"valid_from_turn": "turn:legacy-memory-old"}),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-03T00:00:00+00:00",
                    ),
                )
                row = conn.execute("select * from memory_summaries where id='memory:legacy-no-freshness-turn'").fetchone()
                set_test_memory_projection_clean(conn)
                freshness = memory_row_freshness(conn, row, view="player")
                loaded = find_relevant_memories(conn, targets=["Legacy Memory Subject"], view="player", limit=4)
                omitted = find_omitted_relevant_memories(conn, targets=["Legacy Memory Subject"], view="player", limit=4)

        self.assertEqual(freshness["reason"], "subject_updated_after_summary")
        self.assertNotIn("memory:legacy-no-freshness-turn", {item["id"] for item in loaded})
        self.assertTrue(
            any(
                item["id"] == "memory:legacy-no-freshness-turn"
                and item["stale_reason"] == "subject_updated_after_summary"
                for item in omitted
            )
        )

    def test_memory_visibility_mode_blocks_player_lookup_and_report_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:maintenance-only",
                        "world",
                        None,
                        "Maintenance Only Memory",
                        "private maintenance summary",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "maintenance",
                        "fresh",
                        None,
                        "",
                        "{}",
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-03T00:00:00+00:00",
                    ),
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden-reviewer",
                        "type": "character",
                        "name": "Hidden Reviewer",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden subject.",
                    },
                )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "reflection:character:npc-hidden-reviewer",
                        "character",
                        "npc:hidden-reviewer",
                        "Hidden Reviewer Memory",
                        "hidden character summary",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_character",
                        "maintenance",
                        "fresh",
                        None,
                        "",
                        "{}",
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-03T00:00:00+00:00",
                    ),
                )
                loaded = find_relevant_memories(conn, targets=["Maintenance Only Memory"], view="player", limit=4)
                report_path = write_memory_report(campaign, conn)

            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual([row["id"] for row in loaded], [])
        self.assertNotIn("private maintenance summary", report_text)
        self.assertNotIn("npc-hidden-reviewer", report_text)
        self.assertNotIn("hidden character summary", report_text)

    def test_subjectless_legacy_memory_without_freshness_evidence_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:legacy-subjectless-no-evidence",
                        "world",
                        None,
                        "Legacy World",
                        "Old subjectless summary",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "fresh",
                        None,
                        "",
                        "{}",
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-03T00:00:00+00:00",
                    ),
                )
                set_test_memory_projection_clean(conn)
                loaded = find_relevant_memories(conn, targets=["Legacy World"], view="player", limit=4)
                omitted = find_omitted_relevant_memories(conn, targets=["Legacy World"], view="player", limit=4)

        self.assertEqual([row["id"] for row in loaded], [])
        self.assertTrue(
            any(
                item["id"] == "memory:legacy-subjectless-no-evidence"
                and item["stale_reason"] == "missing_freshness_evidence"
                for item in omitted
            )
        )

    def test_player_memory_lookup_skips_hidden_refs_in_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-source-probe",
                        "type": "item",
                        "name": "Hidden Source Probe",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden source.",
                    },
                )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:hidden-source-evidence",
                        "world",
                        None,
                        "Safe looking world memory",
                        "No visible hidden text here",
                        "[]",
                        json.dumps(["event:item:hidden-source-probe"], ensure_ascii=False),
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "fresh",
                        None,
                        "",
                        json.dumps({"source_event_ids": ["event:item:hidden-source-probe"]}, ensure_ascii=False),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-03T00:00:00+00:00",
                    ),
                )
                loaded = find_relevant_memories(conn, targets=["Safe looking world memory"], view="player", limit=4)

        self.assertEqual([row["id"] for row in loaded], [])

    def test_memory_fallback_evidence_for_empty_table_and_stale_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute("delete from memory_summaries")
                conn.execute(
                    """
                    insert or replace into projection_state(name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'stale', '2026-07-10T00:00:00+00:00', null)
                    """
                )
                omissions = find_omitted_relevant_memories(conn, targets=["anything"], view="player", limit=4)

        reasons = {item["stale_reason"] for item in omissions}
        self.assertIn("projection_memory_stale", reasons)
        self.assertNotIn("empty_memory_table", reasons)

    def test_non_clean_or_misaligned_memory_projection_omits_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values('turn:projection-old', 's', 'old', 'note', 'old', 1, '2024-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:projection-old-world",
                        "world",
                        None,
                        "Old projected world",
                        "OLD PROJECTED WORLD SUMMARY",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "fresh",
                        "turn:seed",
                        "",
                        json.dumps({"current_turn_id": "turn:seed"}, ensure_ascii=False),
                        json.dumps({"authority": "derived_context", "fact_authority": False}),
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'clean', '2026-07-10T00:00:00+00:00', null)
                    """
                )
                cases = [
                    ("dirty", 1, "turn:seed", "projection_memory_dirty"),
                    ("failed", 1, "turn:seed", "projection_memory_failed"),
                    ("refreshing", 1, "turn:seed", "projection_memory_refreshing"),
                    ("stale", 1, "turn:seed", "projection_memory_stale"),
                    ("clean", 0, "turn:seed", "projection_memory_stale"),
                    ("clean", 1, "turn:projection-old", "projection_memory_stale"),
                ]
                for status, version, last_turn_id, expected_reason in cases:
                    with self.subTest(status=status, version=version, last_turn_id=last_turn_id):
                        conn.execute(
                            """
                            update projection_state
                            set status = ?, version = ?, last_turn_id = ?, last_error = null
                            where name = 'memory'
                            """,
                            (status, version, last_turn_id),
                        )
                        loaded = find_relevant_memories(
                            conn,
                            targets=["Old projected world"],
                            view="player",
                            limit=4,
                        )
                        omitted = find_omitted_relevant_memories(
                            conn,
                            targets=["Old projected world"],
                            view="player",
                            limit=4,
                        )

                        self.assertEqual(loaded, [])
                        self.assertTrue(
                            any(item["stale_reason"] == expected_reason for item in omitted)
                        )
                        self.assertFalse(
                            any(item["id"] == "memory:projection-old-world" for item in omitted)
                        )

    def test_player_memory_projection_fallback_redacts_last_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute("delete from memory_summaries")
                conn.execute(
                    """
                    insert or replace into projection_state(name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'failed', '2026-07-10T00:00:00+00:00', 'hidden npc:hidden-reviewer exploded')
                    """
                )
                player_omissions = find_omitted_relevant_memories(conn, targets=["anything"], view="player", limit=4)
                maintenance_omissions = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="maintenance",
                    limit=4,
                )

        player_projection = next(item for item in player_omissions if item["stale_reason"] == "projection_memory_failed")
        maintenance_projection = next(
            item for item in maintenance_omissions if item["stale_reason"] == "projection_memory_failed"
        )
        player_evidence = json.loads(player_projection["freshness_evidence_json"])
        maintenance_evidence = json.loads(maintenance_projection["freshness_evidence_json"])
        self.assertTrue(player_evidence["has_last_error"])
        self.assertNotIn("last_error", player_evidence)
        self.assertEqual(maintenance_evidence["last_error"], "hidden npc:hidden-reviewer exploded")

    def test_memory_metadata_visibility_scans_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-source-probe",
                        "type": "item",
                        "name": "Hidden Source Probe",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden source.",
                    },
                )
                conn.execute(
                    """
                    insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values('turn:hidden-source-metadata', 's', 'hidden turn item:hidden-source-probe', 'note',
                           'hidden turn summary item:hidden-source-probe', 1, '2024-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    insert or replace into events(id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:opaque-hidden-source",
                        "turn:hidden-source-metadata",
                        "第1天",
                        "note",
                        "opaque event title",
                        "opaque event summary references item:hidden-source-probe",
                        json.dumps({"hidden_ref": "item:hidden-source-probe"}, ensure_ascii=False),
                        "test",
                        "2024-01-01T00:00:00+00:00",
                    ),
                )
                metadata = memory_summary_metadata(
                    conn,
                    {
                        "id": "memory:hidden-source-metadata",
                        "kind": "world",
                        "title": "Safe looking metadata",
                        "summary": "Text has no hidden name.",
                        "key_points": [],
                        "source_event_ids": ["event:opaque-hidden-source"],
                        "source_turn_ids": ["turn:hidden-source-metadata"],
                        "visibility_mode": "player",
                    },
                )

        self.assertEqual(metadata["visibility_mode"], "maintenance")

    def test_memory_hidden_scan_checks_all_source_rows_and_event_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-source-probe",
                        "type": "item",
                        "name": "Hidden Source Probe",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden source.",
                    },
                )
                source_event_ids = []
                for index in range(65):
                    turn_id = f"turn:opaque-source-{index:03d}"
                    event_id = f"event:opaque-source-{index:03d}"
                    turn_summary = (
                        "hidden turn item:hidden-source-probe"
                        if index == 64
                        else "safe turn"
                    )
                    conn.execute(
                        """
                        insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                        values(?, 's', ?, 'note', ?, 1, ?)
                        """,
                        (
                            turn_id,
                            turn_summary,
                            turn_summary,
                            f"2024-01-01T00:{index:02d}:00+00:00",
                        ),
                    )
                    conn.execute(
                        """
                        insert or replace into events(id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                        values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            turn_id,
                            "第1天",
                            "note",
                            "safe opaque event",
                            "safe opaque event summary",
                            "{}",
                            "test",
                            f"2024-01-01T00:{index:02d}:30+00:00",
                        ),
                    )
                    source_event_ids.append(event_id)
                metadata = memory_summary_metadata(
                    conn,
                    {
                        "id": "memory:many-opaque-source-events",
                        "kind": "world",
                        "title": "Many safe looking source events",
                        "summary": "Text has no hidden name.",
                        "key_points": [],
                        "source_event_ids": source_event_ids,
                        "source_turn_ids": [],
                        "visibility_mode": "player",
                    },
                )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:many-opaque-source-events",
                        "world",
                        None,
                        "Many safe looking source events",
                        "Text has no hidden name.",
                        "[]",
                        json.dumps(source_event_ids, ensure_ascii=False),
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "fresh",
                        "turn:opaque-source-000",
                        "",
                        json.dumps({"source_event_ids": source_event_ids}, ensure_ascii=False),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-01T02:00:00+00:00",
                    ),
                )
                loaded = find_relevant_memories(
                    conn,
                    targets=["Many safe looking source events"],
                    view="player",
                    limit=4,
                )

        self.assertEqual(metadata["visibility_mode"], "maintenance")
        self.assertEqual([row["id"] for row in loaded], [])

    def test_memory_row_authority_clamps_corrupt_rows_to_derived_context(self) -> None:
        authority = memory_row_authority(
            {
                "derived_authority_json": json.dumps(
                    {
                        "authority": "save_fact",
                        "fact_authority": True,
                        "fact_source": "memory",
                        "private_ai_reasoning": "do not expose",
                        "summary_overrides_facts": True,
                    },
                    ensure_ascii=False,
                )
            }
        )

        self.assertEqual(authority["authority"], "derived_context")
        self.assertEqual(authority["fact_source"], "data/game.sqlite")
        self.assertFalse(authority["fact_authority"])
        self.assertFalse(authority["summary_overrides_facts"])
        self.assertNotIn("private_ai_reasoning", authority)

    def test_memory_freshness_evidence_and_player_reasons_are_allowlisted(self) -> None:
        evidence = memory_row_freshness_evidence(
            {
                "freshness_evidence_json": json.dumps(
                    {
                        "basis": "private_ai_reasoning: secret",
                        "current_turn_id": "turn:seed",
                        "has_last_error": True,
                        "last_turn_id": "turn:seed private_ai_reasoning: secret",
                        "missing_columns": ["freshness_status", "private_ai_reasoning"],
                        "private_ai_reasoning": "do not expose",
                        "projection": "private_ai_reasoning: memory",
                        "source_event_ids": [
                            "event:seed",
                            "event:seed private_ai_reasoning: secret",
                            "private_ai_reasoning:secret",
                        ],
                        "source_turn_ids": [
                            "turn:seed",
                            "turn:seed private_ai_reasoning: secret",
                        ],
                        "status": "failed",
                        "subject_id": "item:public",
                        "subject_updated_turn_id": "private_ai_reasoning:secret",
                    },
                    ensure_ascii=False,
                )
            }
        )

        self.assertEqual(
            evidence,
            {
                "current_turn_id": "turn:seed",
                "has_last_error": True,
                "missing_columns": ["freshness_status"],
                "source_event_ids": ["event:seed"],
                "source_turn_ids": ["turn:seed"],
                "status": "failed",
                "subject_id": "item:public",
            },
        )
        self.assertEqual(
            memory_row_source_event_ids(
                {
                    "source_event_ids_json": json.dumps(
                        ["event:seed", "event:seed private_ai_reasoning: secret"],
                        ensure_ascii=False,
                    )
                }
            ),
            ["event:seed"],
        )
        self.assertEqual(
            memory_row_source_turn_ids(
                {
                    "source_turn_ids_json": json.dumps(
                        ["turn:seed", "turn:seed private_ai_reasoning: secret"],
                        ensure_ascii=False,
                    )
                }
            ),
            ["turn:seed"],
        )
        rendered = render_memory_section(
            [
                {
                    "id": "summary:safe",
                    "kind": "world",
                    "title": "Safe memory",
                    "summary": "Safe summary",
                    "key_points_json": "[]",
                    "freshness_status": "private_ai_reasoning: secret",
                }
            ]
        )
        self.assertIn("；stale", rendered)
        self.assertNotIn("private_ai_reasoning", rendered)
        self.assertEqual(player_safe_memory_reason("subject_hidden_unavailable"), "memory_summary_omitted")
        self.assertEqual(player_safe_memory_reason("private_ai_reasoning: secret"), "memory_summary_omitted")

    def test_player_memory_provenance_resolves_ids_and_clamps_summary_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:fake-player-provenance",
                        "world",
                        None,
                        "Fake provenance memory",
                        "Visible summary text.",
                        "[]",
                        json.dumps(["event:private_ai_reasoning:secret"]),
                        json.dumps(["turn:private_ai_reasoning-secret"]),
                        None,
                        None,
                        "private_ai_reasoning: secret",
                        "player",
                        "fresh",
                        "turn:seed",
                        "",
                        json.dumps(
                            {
                                "current_turn_id": "turn:seed",
                                "has_last_error": "false",
                                "source_event_ids": ["event:private_ai_reasoning:secret"],
                                "source_turn_ids": ["turn:private_ai_reasoning-secret"],
                                "subject_id": "item:private_ai_reasoning-secret",
                            }
                        ),
                        json.dumps({"authority": "derived_context", "fact_authority": False}),
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'clean', '2026-07-10T00:00:00+00:00', null)
                    """
                )
                row = conn.execute(
                    "select * from memory_summaries where id = 'memory:fake-player-provenance'"
                ).fetchone()
                items = memory_loaded_items(
                    SimpleNamespace(
                        conn=conn,
                        memory_summaries=[row],
                        visibility_view="player",
                        mode="query",
                    )
                )
                evidence = memory_row_freshness_evidence(row, conn=conn, view="player")
                event_ids = memory_row_source_event_ids(row, conn=conn, view="player")
                turn_ids = memory_row_source_turn_ids(row, conn=conn, view="player")
                report_path = write_memory_report(campaign, conn)

            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(event_ids, [])
        self.assertEqual(turn_ids, [])
        self.assertEqual(evidence, {"current_turn_id": "turn:seed"})
        self.assertEqual(items, [])
        self.assertNotIn("private_ai_reasoning", json.dumps(items, ensure_ascii=False))
        self.assertNotIn("private_ai_reasoning", report_text)
        self.assertNotIn("Fake provenance memory", report_text)

    def test_player_lookup_sanitizes_raw_metadata_and_hidden_only_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                set_test_memory_projection_clean(conn)
                empty_omissions = find_omitted_relevant_memories(
                    conn,
                    targets=["Oracle probe"],
                    view="player",
                    limit=4,
                )
                insert_test_memory(
                    conn,
                    id="memory:hidden-only-oracle",
                    title="Oracle probe",
                    visibility_mode="maintenance",
                )
                hidden_only_omissions = find_omitted_relevant_memories(
                    conn,
                    targets=["Oracle probe"],
                    view="player",
                    limit=4,
                )

                conn.execute("delete from memory_summaries")
                insert_test_memory(
                    conn,
                    id="memory:raw-player-metadata",
                    title="Raw metadata probe",
                    source_event_ids_json=json.dumps(["event:seed"]),
                    source_turn_ids_json=json.dumps(["turn:seed"]),
                    summary_type="resident_ai",
                    freshness_evidence_json=json.dumps(
                        {
                            "current_turn_id": "turn:seed",
                            "private_ai_reasoning": "must disappear",
                            "source_event_ids": ["event:seed"],
                            "source_turn_ids": ["turn:seed"],
                        }
                    ),
                    derived_authority_json=json.dumps(
                        {
                            "authority": "save_fact",
                            "fact_authority": True,
                            "private_ai_reasoning": "must disappear",
                        }
                    ),
                )
                loaded = find_relevant_memories(
                    conn,
                    targets=["Raw metadata probe"],
                    view="player",
                    limit=4,
                )
                report_path = write_memory_report(campaign, conn)

            report_text = report_path.read_text(encoding="utf-8")

        self.assertEqual(
            [(item["id"], item["stale_reason"]) for item in empty_omissions],
            [(item["id"], item["stale_reason"]) for item in hidden_only_omissions],
        )
        self.assertEqual(len(loaded), 1)
        serialized_row = json.dumps(dict(loaded[0]), ensure_ascii=False, sort_keys=True)
        self.assertNotIn("private_ai_reasoning", serialized_row)
        self.assertNotIn("save_fact", serialized_row)
        self.assertEqual(
            json.loads(loaded[0]["derived_authority_json"])["authority"],
            "derived_context",
        )
        self.assertIn("- 来源事件：", report_text)
        self.assertIn("event:seed", report_text)
        self.assertIn("- 来源回合：", report_text)
        self.assertIn("- 新鲜度证据：", report_text)
        self.assertIn("- 派生权威：", report_text)
        self.assertIn("derived_context", report_text)
        self.assertNotIn("private_ai_reasoning", report_text)

    def test_corrupt_freshness_status_and_unresolved_evidence_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:corrupt-freshness",
                        "world",
                        None,
                        "Corrupt freshness memory",
                        "Must not load as fresh.",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "private_ai_reasoning: fresh",
                        None,
                        "",
                        json.dumps({"current_turn_id": "turn:not-real"}),
                        json.dumps({"authority": "derived_context", "fact_authority": False}),
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                set_test_memory_projection_clean(conn)

                loaded = find_relevant_memories(
                    conn,
                    targets=["Corrupt freshness memory"],
                    view="player",
                    limit=4,
                )
                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["Corrupt freshness memory"],
                    view="player",
                    limit=4,
                )

        self.assertEqual(loaded, [])
        self.assertFalse(any(item["id"] == "memory:corrupt-freshness" for item in omitted))
        self.assertEqual(omitted[0]["stale_reason"], "memory_summary_omitted")

    def test_memory_freshness_rejects_future_missing_invalid_and_unresolved_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.executemany(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values(?, 's', 'u', 'note', 'summary', 1, ?)
                    """,
                    [
                        ("turn:future-memory", "2099-01-01T00:00:00+00:00"),
                        ("turn:with space", "2026-07-10T00:00:00+00:00"),
                        ("turn:offset-a", "2024-01-01T01:00:00+01:00"),
                        ("turn:offset-b", "2024-01-01T00:30:00+00:00"),
                        ("turn:valid-created", "2024-01-01T00:00:00+00:00"),
                        ("turn:invalid-created", "zzzz"),
                    ],
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'clean', '2026-07-10T00:00:00+00:00', null)
                    """
                )
                future_row = insert_test_memory(
                    conn,
                    id="memory:future-evidence",
                    freshness_turn_id="turn:future-memory",
                )
                space_row = insert_test_memory(
                    conn,
                    id="memory:space-evidence",
                    freshness_turn_id="turn:with space",
                    freshness_evidence_json="{}",
                )
                unresolved_row = insert_test_memory(
                    conn,
                    id="memory:unresolved-source",
                    source_event_ids_json=json.dumps(["event:not-real"]),
                )
                deep_row = insert_test_memory(
                    conn,
                    id="memory:deep-evidence",
                    freshness_turn_id=None,
                    freshness_evidence_json="[" * 2000 + "]" * 2000,
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:missing-update-turn",
                        "type": "item",
                        "name": "Missing Update Turn",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Broken update evidence.",
                    },
                )
                conn.commit()
                conn.execute("pragma foreign_keys = off")
                conn.execute(
                    "update entities set updated_turn_id = '' where id = 'item:missing-update-turn'"
                )
                conn.commit()
                conn.execute("pragma foreign_keys = on")
                subject_row = insert_test_memory(
                    conn,
                    id="memory:missing-subject-update",
                    kind="project",
                    subject_id="item:missing-update-turn",
                    summary_type="deterministic_project",
                )
                long_turn_id = "turn:" + "x" * 10000
                conn.execute(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values(?, 's', 'u', 'note', 'long', 1, '2026-07-10T00:00:00+00:00')
                    """,
                    (long_turn_id,),
                )
                long_evidence = memory_row_freshness_evidence(
                    {
                        "freshness_evidence_json": json.dumps(
                            {"current_turn_id": long_turn_id}
                        )
                    },
                    conn=conn,
                    view="player",
                )

                results = {
                    "future": memory_row_freshness(conn, future_row, view="player"),
                    "space": memory_row_freshness(conn, space_row, view="player"),
                    "unresolved": memory_row_freshness(conn, unresolved_row, view="player"),
                    "deep": memory_row_freshness(conn, deep_row, view="player"),
                    "subject": memory_row_freshness(conn, subject_row, view="player"),
                }
                offset_order = turn_is_after(conn, "turn:offset-a", "turn:offset-b")
                latest_valid = latest_turn_id(
                    conn,
                    ["turn:valid-created", "turn:invalid-created"],
                )

        self.assertTrue(all(item["status"] == "stale" for item in results.values()))
        self.assertFalse(offset_order)
        self.assertEqual(latest_valid, "turn:valid-created")
        self.assertEqual(long_evidence, {})

    def test_memory_freshness_checks_every_provenance_turn_and_raw_evidence_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values('turn:future-provenance', 's', 'future', 'note', 'future', 1,
                           '2099-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    insert into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values('event:future-provenance', 'turn:future-provenance', '', 'note', 'future',
                           'future', '{}', 'test', '2099-01-01T00:00:00+00:00')
                    """
                )
                future_evidence = insert_test_memory(
                    conn,
                    id="memory:future-evidence-only",
                    freshness_evidence_json=json.dumps(
                        {"current_turn_id": "turn:future-provenance"}
                    ),
                )
                future_event = insert_test_memory(
                    conn,
                    id="memory:future-event-turn",
                    source_event_ids_json=json.dumps(["event:future-provenance"]),
                    freshness_evidence_json=json.dumps(
                        {
                            "current_turn_id": "turn:seed",
                            "source_event_ids": ["event:future-provenance"],
                        }
                    ),
                )
                mixed_invalid = insert_test_memory(
                    conn,
                    id="memory:mixed-invalid-evidence",
                    freshness_evidence_json=json.dumps(
                        {"source_turn_ids": ["turn:seed", "not-a-turn"]}
                    ),
                )
                set_test_memory_projection_clean(conn)

                results = [
                    memory_row_freshness(conn, future_evidence, view="player"),
                    memory_row_freshness(conn, future_event, view="player"),
                    memory_row_freshness(conn, mixed_invalid, view="player"),
                ]

        self.assertTrue(all(item["status"] == "stale" for item in results))

    def test_corrupt_provenance_and_blob_source_rows_fail_closed_for_player(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values('event:blob-provenance', 'turn:seed', '', 'note', 'visible', 'visible', ?,
                           'test', '2026-07-10T00:00:00+00:00')
                    """,
                    (sqlite3.Binary(b"private_ai_reasoning: secret"),),
                )
                deep_row = {
                    "id": "memory:deep-hidden-scan",
                    "subject_id": None,
                    "title": "Deep metadata",
                    "summary": "Visible",
                    "key_points_json": "[]",
                    "source_event_ids_json": "[]",
                    "source_turn_ids_json": "[]",
                    "freshness_evidence_json": "[" * 2000 + "]" * 2000,
                }
                blob_source_row = {
                    "id": "memory:blob-source-row",
                    "subject_id": None,
                    "title": "Blob source",
                    "summary": "Visible",
                    "key_points_json": "[]",
                    "source_event_ids_json": json.dumps(["event:blob-provenance"]),
                    "source_turn_ids_json": "[]",
                    "freshness_evidence_json": "{}",
                }

                deep_is_hidden = memory_row_has_hidden_refs(conn, deep_row)
                blob_is_hidden = memory_row_has_hidden_refs(conn, blob_source_row)

        self.assertTrue(deep_is_hidden)
        self.assertTrue(blob_is_hidden)

    def test_player_omission_boundary_sanitizes_reason_projection_turn_and_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    update projection_state
                    set status='failed', last_turn_id='turn:private_ai_reasoning.secret',
                        last_error='private_ai_reasoning: projection-secret'
                    where name='memory'
                    """
                )
                projection_omission = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="player",
                    limit=4,
                )[0]

                set_test_memory_projection_clean(conn)
                insert_test_memory(
                    conn,
                    id=sqlite3.Binary(b"private-memory-id"),
                    title="Unsafe omission",
                    freshness_status="stale",
                    stale_reason="private_ai_reasoning: stale-secret",
                )
                row_omission = find_omitted_relevant_memories(
                    conn,
                    targets=["Unsafe omission"],
                    view="player",
                    limit=4,
                )[0]

        projection_json = json.dumps(projection_omission, ensure_ascii=False)
        self.assertNotIn("private_ai_reasoning", projection_json)
        self.assertIsInstance(row_omission["id"], str)
        self.assertLessEqual(len(row_omission["id"]), 256)
        self.assertEqual(row_omission["stale_reason"], "memory_summary_omitted")

    def test_memory_schema_contract_rejects_bad_base_columns_and_helper_columns(self) -> None:
        bad_base = sqlite3.connect(":memory:")
        bad_base.row_factory = sqlite3.Row
        bad_base.executescript(
            """
            create table memory_summaries (
              id text not null,
              kind text not null,
              subject_id text,
              title text not null,
              summary text not null,
              key_points_json text not null default '[]',
              source_event_ids_json text not null default '[]',
              source_turn_ids_json text not null default '[]',
              valid_from_turn text,
              valid_to_turn text,
              summary_type text not null default 'deterministic',
              visibility_mode text not null default 'player',
              freshness_status text not null default 'fresh',
              freshness_turn_id text,
              stale_reason text not null default '',
              freshness_evidence_json text not null default '{}',
              derived_authority_json text not null default '{"authority":"derived_context","fact_authority":false}',
              updated_at text not null
            );
            """
        )
        self.assertFalse(memory_metadata_columns_present(bad_base))
        bad_base.close()

        bad_helper = sqlite3.connect(":memory:")
        bad_helper.row_factory = sqlite3.Row
        bad_helper.executescript(
            """
            create table entities(id text primary key);
            create table turns(id text primary key);
            create table memory_summaries (
              id text primary key,
              kind text not null,
              subject_id text,
              title text not null,
              summary text not null,
              key_points_json text not null default '[]',
              source_event_ids_json text not null default '[]',
              source_turn_ids_json text not null default '[]',
              valid_from_turn text,
              valid_to_turn text,
              summary_type integer not null default 99,
              updated_at text not null
            );
            """
        )
        with self.assertRaisesRegex(sqlite3.OperationalError, "incompatible existing column"):
            ensure_memory_tables(bad_helper)
        bad_helper.close()

    def test_composite_projection_state_primary_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state (
                      name text not null,
                      shard text not null,
                      version integer not null,
                      last_turn_id text,
                      status text not null,
                      updated_at text not null,
                      last_error text,
                      primary key(name, shard)
                    )
                    """
                )
                conn.execute(
                    """
                    insert into projection_state
                    (name, shard, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 'only', 1, 'turn:seed', 'clean',
                           '2026-07-10T00:00:00+00:00', null)
                    """
                )

                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "stale")

    def test_memory_timestamp_overflow_is_incomparable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.executemany(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values(?, 's', 'u', 'note', 'summary', 1, ?)
                    """,
                    [
                        ("turn:underflow", "0001-01-01T00:00:00+14:00"),
                        ("turn:normal", "2026-07-10T00:00:00+00:00"),
                    ],
                )

                comparison = turn_is_after(conn, "turn:underflow", "turn:normal")

        self.assertIsNone(comparison)

    def test_memory_query_limits_are_bounded_before_sqlite_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                set_test_memory_projection_clean(conn)
                loaded = find_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="player",
                    limit=2**100,
                )
                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="player",
                    limit=2**100,
                )

        self.assertLessEqual(len(loaded), 256)
        self.assertLessEqual(len(omitted), 256)

    def test_memory_overfetch_stops_at_total_row_scan_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                set_test_memory_projection_clean(conn)
                for index in range(6):
                    insert_test_memory(
                        conn,
                        id=f"memory:scan-cap-{index}",
                        title="scan cap candidate",
                        visibility_mode="maintenance",
                    )
                statements: list[str] = []
                conn.set_trace_callback(statements.append)
                with (
                    mock.patch.object(
                        memory_module,
                        "MAX_MEMORY_ROWS_SCANNED",
                        2,
                    ),
                    mock.patch(
                        "rpg_engine.memory.memory_projection_health",
                        return_value={
                            "status": "clean",
                            "last_turn_id": "turn:seed",
                            "last_error": None,
                            "updated_at": "2026-07-10T00:00:00+00:00",
                        },
                    ),
                ):
                    omitted = find_omitted_relevant_memories(
                        conn,
                        targets=["scan cap candidate"],
                        view="player",
                        limit=4,
                    )
                conn.set_trace_callback(None)

        paged_selects = [
            statement
            for statement in statements
            if "from main.memory_summaries m" in statement.lower()
            and "limit" in statement.lower()
        ]
        self.assertEqual(len(paged_selects), 1)
        self.assertEqual(omitted[0]["id"], "memory:fallback:unavailable")

    def test_save_patch_dirties_memory_and_omits_same_turn_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                rebuild_memory_summaries(campaign, conn)
                before = find_relevant_memories(
                    conn,
                    targets=["pc:traveler"],
                    view="player",
                    limit=8,
                )

            result = apply_save_patch(
                campaign,
                {
                    "patch_schema_version": "1",
                    "reason": "same-turn authoritative fact update",
                    "operations": [
                        {
                            "op": "set_entity_summary",
                            "entity_id": "pc:traveler",
                            "summary": "Authoritative same-turn update.",
                        }
                    ],
                },
                backup=False,
            )
            with connect(campaign) as conn:
                fact = conn.execute(
                    "select summary from entities where id='pc:traveler'"
                ).fetchone()[0]
                health = memory_projection_health(conn)
                loaded = find_relevant_memories(
                    conn,
                    targets=["pc:traveler"],
                    view="player",
                    limit=8,
                )
                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["pc:traveler"],
                    view="player",
                    limit=8,
                )

        self.assertTrue(before)
        self.assertTrue(result.ok, result.render())
        self.assertEqual(fact, "Authoritative same-turn update.")
        self.assertEqual(health["status"], "dirty")
        self.assertEqual(loaded, [])
        self.assertEqual(omitted[0]["stale_reason"], "projection_memory_dirty")

    def test_save_patch_commits_fact_when_projection_metadata_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    create trigger memory_projection_metadata_block
                    before update on projection_state
                    when new.name='memory'
                    begin
                      select raise(abort, 'projection metadata blocked');
                    end
                    """
                )
                conn.commit()

            result = apply_save_patch(
                campaign,
                {
                    "patch_schema_version": "1",
                    "reason": "projection metadata must not own facts",
                    "operations": [
                        {
                            "op": "set_entity_summary",
                            "entity_id": "pc:traveler",
                            "summary": "Fact committed despite projection metadata failure.",
                        }
                    ],
                },
                backup=False,
            )
            with connect(campaign) as conn:
                summary = conn.execute(
                    "select summary from entities where id='pc:traveler'"
                ).fetchone()[0]
                health = memory_projection_health(conn)

        self.assertEqual(
            summary,
            "Fact committed despite projection metadata failure.",
        )
        self.assertEqual(result.operations_applied, 1)
        self.assertEqual(health["status"], "stale")

    def test_save_patch_dirties_memory_when_outbox_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                rebuild_memory_summaries(campaign, conn)
                conn.execute("drop table main.outbox")
                conn.commit()

            result = apply_save_patch(
                campaign,
                {
                    "patch_schema_version": "1",
                    "reason": "outbox is unrelated to memory invalidation",
                    "operations": [
                        {
                            "op": "set_entity_summary",
                            "entity_id": "pc:traveler",
                            "summary": "Fact survives missing outbox.",
                        }
                    ],
                },
                backup=False,
            )
            with connect(campaign) as conn:
                summary = conn.execute(
                    "select summary from main.entities where id='pc:traveler'"
                ).fetchone()[0]
                memory_status = conn.execute(
                    "select status from main.projection_state where name='memory'"
                ).fetchone()[0]

        self.assertEqual(result.operations_applied, 1)
        self.assertEqual(summary, "Fact survives missing outbox.")
        self.assertEqual(memory_status, "dirty")

    def test_player_memory_row_allowlist_and_kind_canonicalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    "alter table memory_summaries add column private_ai_reasoning text"
                )
                insert_test_memory(
                    conn,
                    id="memory:extended-player-row",
                    kind="private_ai_reasoning:secret-token",
                    title="Extended row probe",
                )
                conn.execute(
                    """
                    update memory_summaries
                    set private_ai_reasoning='secret-token'
                    where id='memory:extended-player-row'
                    """
                )
                set_test_memory_projection_clean(conn)
                loaded = find_relevant_memories(
                    conn,
                    targets=["Extended row probe"],
                    view="player",
                    limit=4,
                )
                raw = conn.execute(
                    "select * from memory_summaries where id='memory:extended-player-row'"
                ).fetchone()
                rendered = render_memory_section([raw], conn, view="player")

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["kind"], "unknown")
        self.assertNotIn("private_ai_reasoning", loaded[0])
        self.assertNotIn("secret-token", json.dumps(loaded[0], ensure_ascii=False))
        self.assertNotIn("secret-token", rendered)

    def test_source_turn_hidden_locations_fail_closed_direct_and_event_linked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden-memory-source",
                        "type": "location",
                        "name": "Hidden Source Location",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden.",
                    },
                )
                conn.execute(
                    """
                    insert into turns
                    (id, session_id, user_text, intent, location_before, location_after,
                     summary, changed, created_at)
                    values('turn:hidden-location-source', 's', 'safe text', 'note',
                           'loc:hidden-memory-source', 'loc:start', 'safe summary', 1,
                           '2024-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    insert into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values('event:hidden-location-source', 'turn:hidden-location-source', '',
                           'note', 'safe', 'safe', '{}', 'test',
                           '2024-01-01T00:00:00+00:00')
                    """
                )
                direct = insert_test_memory(
                    conn,
                    id="memory:hidden-location-direct",
                    source_turn_ids_json=json.dumps(["turn:hidden-location-source"]),
                )
                linked = insert_test_memory(
                    conn,
                    id="memory:hidden-location-event",
                    source_event_ids_json=json.dumps(["event:hidden-location-source"]),
                )

                direct_hidden = memory_row_has_hidden_refs(conn, direct)
                linked_hidden = memory_row_has_hidden_refs(conn, linked)

        self.assertTrue(direct_hidden)
        self.assertTrue(linked_hidden)

    def test_memory_validity_window_expiry_and_reverse_order_are_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values('turn:validity-later', 's', 'later', 'note', 'later', 1,
                           '2099-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    "update meta set value='turn:validity-later' where key='current_turn_id'"
                )
                expired = insert_test_memory(
                    conn,
                    id="memory:expired-window",
                    freshness_turn_id="turn:validity-later",
                    valid_to_turn="turn:seed",
                    freshness_evidence_json=json.dumps(
                        {"current_turn_id": "turn:validity-later"}
                    ),
                )
                reversed_window = insert_test_memory(
                    conn,
                    id="memory:reversed-window",
                    freshness_turn_id="turn:validity-later",
                    valid_from_turn="turn:validity-later",
                    valid_to_turn="turn:seed",
                    freshness_evidence_json=json.dumps(
                        {"current_turn_id": "turn:validity-later"}
                    ),
                )
                set_test_memory_projection_clean(
                    conn,
                    last_turn_id="turn:validity-later",
                )

                expired_status = memory_row_freshness(conn, expired, view="player")
                reversed_status = memory_row_freshness(
                    conn,
                    reversed_window,
                    view="player",
                )

        self.assertEqual(expired_status["status"], "stale")
        self.assertEqual(reversed_status["status"], "stale")

    def test_trusted_rebuild_marker_requires_resolvable_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(
                    conn,
                    id="memory:unresolved-trusted-marker",
                    freshness_evidence_json=json.dumps(
                        {
                            "basis": "deterministic_rebuild",
                            "current_turn_id": "turn:not-real",
                        }
                    ),
                    derived_authority_json=json.dumps(
                        {
                            "authority": "derived_context",
                            "fact_authority": False,
                            "fact_source": "data/game.sqlite",
                            "summary_overrides_facts": False,
                        }
                    ),
                )
                set_test_memory_projection_clean(conn)
                conn.execute(
                    "delete from schema_migrations where id='0009_memory_summary_provenance'"
                )

                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "stale")

    def test_memory_lookup_rechecks_projection_snapshot_before_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(conn, id="memory:projection-toctou")
                set_test_memory_projection_clean(conn)
                with mock.patch(
                    "rpg_engine.memory.memory_projection_health",
                    side_effect=[
                        {
                            "status": "clean",
                            "last_turn_id": "turn:seed",
                            "last_error": None,
                        },
                        {
                            "status": "dirty",
                            "last_turn_id": "turn:next",
                            "last_error": None,
                        },
                    ],
                ):
                    loaded = find_relevant_memories(
                        conn,
                        targets=["Test memory"],
                        view="player",
                        limit=4,
                    )

        self.assertEqual(loaded, [])

    def test_memory_provenance_queries_are_bounded_and_reference_count_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                turn_ids = [f"turn:bounded-source-{index:03d}" for index in range(129)]
                conn.executemany(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values(?, 's', 'safe', 'note', 'safe', 1, ?)
                    """,
                    [
                        (turn_id, f"2024-01-{1 + index % 28:02d}T00:00:00+00:00")
                        for index, turn_id in enumerate(turn_ids)
                    ],
                )
                bounded = insert_test_memory(
                    conn,
                    id="memory:bounded-provenance",
                    source_turn_ids_json=json.dumps(turn_ids[:64]),
                )
                over_limit = insert_test_memory(
                    conn,
                    id="memory:over-limit-provenance",
                    source_turn_ids_json=json.dumps(turn_ids),
                )
                set_test_memory_projection_clean(conn)
                statements: list[str] = []
                conn.set_trace_callback(statements.append)
                bounded_status = memory_row_freshness(conn, bounded, view="player")
                conn.set_trace_callback(None)
                over_limit_status = memory_row_freshness(
                    conn,
                    over_limit,
                    view="maintenance",
                )

        selects = [
            statement
            for statement in statements
            if statement.lstrip().lower().startswith("select")
        ]
        self.assertEqual(bounded_status["status"], "fresh")
        self.assertLessEqual(len(selects), 200)
        self.assertEqual(over_limit_status["status"], "stale")

    def test_direct_memory_rebuild_does_not_overwrite_new_dirty_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                original_write_report = write_memory_report

                def dirty_after_rows(*args: object, **kwargs: object) -> Path:
                    path = original_write_report(*args, **kwargs)
                    mark_projections_dirty(conn, ["memory"], turn_id="turn:seed")
                    conn.commit()
                    return path

                with mock.patch(
                    "rpg_engine.memory.write_memory_report",
                    side_effect=dirty_after_rows,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "generation changed during rebuild completion",
                    ):
                        rebuild_memory_summaries(campaign, conn)
                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "dirty")

    def test_memory_lookup_detects_clean_generation_aba(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(conn, id="memory:projection-aba")
                set_test_memory_projection_clean(conn)
                with mock.patch(
                    "rpg_engine.memory.memory_projection_health",
                    side_effect=[
                        {
                            "status": "clean",
                            "last_turn_id": "turn:seed",
                            "last_error": None,
                            "updated_at": "2026-07-10T00:00:00+00:00",
                        },
                        {
                            "status": "clean",
                            "last_turn_id": "turn:seed",
                            "last_error": None,
                            "updated_at": "2026-07-10T00:00:01+00:00",
                        },
                    ],
                ):
                    loaded = find_relevant_memories(
                        conn,
                        targets=["Test memory"],
                        view="player",
                        limit=4,
                    )

        self.assertEqual(loaded, [])

    def test_maintenance_memory_lookup_rejects_blob_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(
                    conn,
                    id="memory:maintenance-blob-row",
                    title=sqlite3.Binary(b"private-title"),
                    updated_at=sqlite3.Binary(b"invalid-time"),
                )
                set_test_memory_projection_clean(conn)

                loaded = find_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="maintenance",
                    limit=4,
                )

        self.assertEqual(loaded, [])

    def test_memory_schema_rejects_composite_primary_key_and_required_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    "alter table memory_summaries add column tenant text not null"
                )
                required_extension_ready = memory_metadata_columns_present(conn)

                conn.execute("drop table memory_summaries")
                conn.execute(
                    """
                    create table memory_summaries (
                      id text not null,
                      shard text not null default 'main',
                      kind text not null,
                      subject_id text,
                      title text not null,
                      summary text not null,
                      key_points_json text not null default '[]',
                      source_event_ids_json text not null default '[]',
                      source_turn_ids_json text not null default '[]',
                      valid_from_turn text,
                      valid_to_turn text,
                      summary_type text not null default 'deterministic',
                      visibility_mode text not null default 'player',
                      freshness_status text not null default 'fresh',
                      freshness_turn_id text,
                      stale_reason text not null default '',
                      freshness_evidence_json text not null default '{}',
                      derived_authority_json text not null default '{"authority":"derived_context","fact_authority":false}',
                      updated_at text not null,
                      primary key(id, shard)
                    )
                    """
                )
                composite_ready = memory_metadata_columns_present(conn)

        self.assertFalse(required_extension_ready)
        self.assertFalse(composite_ready)

    def test_memory_schema_rejects_unicode_and_write_blocking_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)

                def contract_after(statement: str) -> bool:
                    conn.execute("savepoint memory_contract_extension")
                    try:
                        conn.execute(statement)
                        return memory_metadata_columns_present(conn)
                    finally:
                        conn.execute("rollback to memory_contract_extension")
                        conn.execute("release memory_contract_extension")

                unicode_required = contract_after(
                    'alter table memory_summaries add column "ſummary" text not null'
                )
                unique_non_identity = contract_after(
                    "create unique index memory_unique_updated_at "
                    "on memory_summaries(updated_at)"
                )
                partial_identity = contract_after(
                    "create unique index memory_partial_identity on memory_summaries(id) "
                    "where kind='world'"
                )
                expression_identity = contract_after(
                    "create unique index memory_expression_identity "
                    "on memory_summaries(lower(id))"
                )
                generated_poison = contract_after(
                    "alter table memory_summaries add column poison text "
                    "generated always as (null) virtual not null"
                )
                blocking_trigger = contract_after(
                    "create trigger memory_blocking_insert before insert on memory_summaries "
                    "begin select raise(abort, 'blocked'); end"
                )
                non_unique_expression = contract_after(
                    "create index memory_expression_read on "
                    "memory_summaries(json_extract(summary, '$.x'))"
                )
                non_unique_partial = contract_after(
                    "create index memory_partial_read on memory_summaries(kind) "
                    "where length(summary) > 0"
                )
                commented_check = contract_after(
                    "alter table memory_summaries add column check_poison text not null "
                    "default 'x' check /* gap */ (check_poison='y')"
                )
                temp_trigger = contract_after(
                    "create temp trigger memory_temp_block before insert on memory_summaries "
                    "begin select raise(abort, 'temp blocked'); end"
                )

                schema_sql = str(
                    conn.execute(
                        "select sql from sqlite_master "
                        "where type='table' and name='memory_summaries'"
                    ).fetchone()[0]
                )
                conn.execute(
                    "alter table memory_summaries rename to memory_summaries_original"
                )
                poison_schema = schema_sql.replace(
                    "foreign key(subject_id)",
                    "poison_default text default (poison()), "
                    "foreign key(subject_id)",
                    1,
                )
                self.assertNotEqual(poison_schema, schema_sql)
                conn.execute(poison_schema)
                conn.create_function(
                    "poison",
                    0,
                    lambda: (_ for _ in ()).throw(
                        RuntimeError("poison default ran")
                    ),
                )
                unsafe_default = memory_metadata_columns_present(conn)
                with self.assertRaises(sqlite3.Error):
                    insert_test_memory(
                        conn,
                        id="memory:unsafe-default-probe",
                    )

        self.assertFalse(unicode_required)
        self.assertFalse(unique_non_identity)
        self.assertFalse(partial_identity)
        self.assertFalse(expression_identity)
        self.assertFalse(generated_poison)
        self.assertFalse(blocking_trigger)
        self.assertFalse(non_unique_expression)
        self.assertFalse(non_unique_partial)
        self.assertFalse(commented_check)
        self.assertFalse(temp_trigger)
        self.assertFalse(unsafe_default)

    def test_trusted_rebuild_marker_validates_row_subject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.commit()
                conn.execute("pragma foreign_keys=off")
                insert_test_memory(
                    conn,
                    id="memory:missing-trusted-subject",
                    kind="project",
                    subject_id="item:not-real",
                    summary_type="deterministic_project",
                    freshness_evidence_json=json.dumps(
                        {
                            "basis": "deterministic_rebuild",
                            "current_turn_id": "turn:seed",
                        }
                    ),
                    derived_authority_json=json.dumps(
                        {
                            "authority": "derived_context",
                            "fact_authority": False,
                            "fact_source": "data/game.sqlite",
                            "summary_overrides_facts": False,
                        }
                    ),
                )
                conn.commit()
                conn.execute("pragma foreign_keys=on")
                set_test_memory_projection_clean(conn)
                conn.execute(
                    "delete from schema_migrations where id='0009_memory_summary_provenance'"
                )

                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "stale")

    def test_future_validity_bounds_are_separate_from_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values('turn:future-validity-bound', 's', 'future', 'note', 'future', 1,
                           '2099-01-01T00:00:00+00:00')
                    """
                )
                future_end = insert_test_memory(
                    conn,
                    id="memory:future-valid-to",
                    valid_to_turn="turn:future-validity-bound",
                    freshness_evidence_json=json.dumps(
                        {
                            "current_turn_id": "turn:seed",
                            "valid_to_turn": "turn:future-validity-bound",
                        }
                    ),
                )
                future_start = insert_test_memory(
                    conn,
                    id="memory:future-valid-from",
                    valid_from_turn="turn:future-validity-bound",
                    freshness_evidence_json=json.dumps(
                        {
                            "current_turn_id": "turn:seed",
                            "valid_from_turn": "turn:future-validity-bound",
                        }
                    ),
                )
                mismatched_bound = insert_test_memory(
                    conn,
                    id="memory:mismatched-validity-evidence",
                    valid_to_turn="turn:future-validity-bound",
                    freshness_evidence_json=json.dumps(
                        {"current_turn_id": "turn:seed"}
                    ),
                )
                bound_only = insert_test_memory(
                    conn,
                    id="memory:validity-bound-only",
                    freshness_turn_id=None,
                    valid_to_turn="turn:future-validity-bound",
                    freshness_evidence_json=json.dumps(
                        {"valid_to_turn": "turn:future-validity-bound"}
                    ),
                )
                bound_scalar = insert_test_memory(
                    conn,
                    id="memory:validity-bound-scalar",
                    freshness_turn_id="turn:seed",
                    valid_from_turn="turn:seed",
                    freshness_evidence_json=json.dumps(
                        {
                            "basis": "deterministic_rebuild",
                            "valid_from_turn": "turn:seed",
                        }
                    ),
                )
                set_test_memory_projection_clean(conn)

                end_status = memory_row_freshness(conn, future_end, view="player")
                start_status = memory_row_freshness(conn, future_start, view="player")
                mismatched_status = memory_row_freshness(
                    conn,
                    mismatched_bound,
                    view="player",
                )
                bound_only_status = memory_row_freshness(conn, bound_only, view="player")
                bound_scalar_status = memory_row_freshness(
                    conn,
                    bound_scalar,
                    view="player",
                )

        self.assertEqual(end_status["status"], "fresh")
        self.assertEqual(start_status["status"], "stale")
        self.assertEqual(start_status["reason"], "summary_not_yet_valid")
        self.assertEqual(mismatched_status["status"], "stale")
        self.assertEqual(
            mismatched_status["reason"],
            "invalid_summary_validity_window",
        )
        self.assertEqual(bound_only_status["status"], "stale")
        self.assertEqual(bound_only_status["reason"], "missing_freshness_evidence")
        self.assertEqual(bound_scalar_status["status"], "stale")
        self.assertEqual(
            bound_scalar_status["reason"],
            "missing_freshness_evidence",
        )

    def test_trusted_memory_metadata_rejects_extra_authority_and_nonfinite_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                row = insert_test_memory(
                    conn,
                    id="memory:strict-metadata",
                    freshness_evidence_json=json.dumps(
                        {
                            "basis": "deterministic_rebuild",
                            "current_turn_id": "turn:seed",
                            "subject_id": None,
                            "subject_updated_turn_id": None,
                            "source_event_ids": [],
                            "source_turn_ids": [],
                            "valid_from_turn": None,
                            "valid_to_turn": None,
                        }
                    ),
                    derived_authority_json=json.dumps(
                        memory_module.DERIVED_MEMORY_AUTHORITY,
                        sort_keys=True,
                    ),
                )
                set_test_memory_projection_clean(conn)
                self.assertTrue(memory_rows_have_trusted_provenance(conn))

                conn.execute(
                    "update main.memory_summaries set derived_authority_json=? where id=?",
                    (
                        json.dumps(
                            {
                                **memory_module.DERIVED_MEMORY_AUTHORITY,
                                "trusted_override": True,
                            },
                            sort_keys=True,
                        ),
                        row["id"],
                    ),
                )
                self.assertFalse(memory_rows_have_trusted_provenance(conn))

                conn.execute(
                    "update main.memory_summaries "
                    "set derived_authority_json=?, freshness_evidence_json=? where id=?",
                    (
                        json.dumps(memory_module.DERIVED_MEMORY_AUTHORITY, sort_keys=True),
                        '{"current_turn_id": NaN}',
                        row["id"],
                    ),
                )
                nonfinite_row = conn.execute(
                    "select * from main.memory_summaries where id=?",
                    (row["id"],),
                ).fetchone()
                nonfinite_trusted = memory_rows_have_trusted_provenance(conn)
                nonfinite_status = memory_row_freshness(
                    conn,
                    nonfinite_row,
                    view="player",
                )["status"]

        self.assertFalse(nonfinite_trusted)
        self.assertEqual(nonfinite_status, "stale")

    def test_player_memory_ids_reports_and_snapshot_publication_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                upsert_entity(
                    conn,
                    {
                        "id": "item:veiled-auditor",
                        "type": "item",
                        "name": "VeiledAuditor",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "hidden",
                        "updated_turn_id": "turn:seed",
                    },
                )
                insert_test_memory(
                    conn,
                    id="memory:VeiledAuditor",
                    title="Visible-looking title",
                    freshness_evidence_json=json.dumps(
                        {"current_turn_id": "turn:seed"}
                    ),
                )
                set_test_memory_projection_clean(conn)

                loaded = find_relevant_memories(
                    conn,
                    targets=["Visible-looking title"],
                    view="player",
                    limit=4,
                )
                report_path = write_memory_report(campaign, conn)
                report_text = report_path.read_text(encoding="utf-8")

                conn.execute("create temp table entities(id text primary key)")
                with self.assertRaisesRegex(sqlite3.OperationalError, "TEMP shadow"):
                    write_memory_report(campaign, conn)
                conn.execute("drop table temp.entities")

                with mock.patch(
                    "rpg_engine.memory.memory_projection_snapshot_change",
                    return_value={"status": "dirty"},
                ):
                    with self.assertRaisesRegex(RuntimeError, "changed during report"):
                        write_memory_report(campaign, conn)
                changed_report = report_path.read_text(encoding="utf-8")

        self.assertFalse(
            any(row.get("id") == "memory:VeiledAuditor" for row in loaded)
        )
        self.assertNotIn("VeiledAuditor", report_text)
        self.assertNotIn("VeiledAuditor", changed_report)
        self.assertIn("report unavailable until refresh", changed_report)

    def test_player_missing_memory_evidence_rejects_overrides_and_collapses_hidden_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden",
                        "type": "character",
                        "name": "Hidden Name",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "hidden",
                        "updated_turn_id": "turn:seed",
                    },
                )
                state = SimpleNamespace(
                    conn=conn,
                    mode="query",
                    visibility_view="player",
                    missing_required=[],
                    needs_user_confirmation=[],
                    memory_omissions=[
                        {
                            "id": "npc:hidden",
                            "reason": "stored_stale",
                            "player_safe_reason": "npc:hidden secret",
                            "player_safe_signal": "npc:hidden",
                        },
                        {
                            "id": "memory:npc:hidden",
                            "reason": "stored_stale",
                            "player_safe_reason": "npc:hidden secret two",
                            "player_safe_signal": "memory:npc:hidden",
                        },
                    ],
                )

                evidence = missing_signal_evidence(state)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["signal"], "memory_summaries")
        self.assertEqual(evidence[0]["reason"], "memory_summary_omitted")
        self.assertNotIn("hidden", json.dumps(evidence).lower())

    def test_memory_context_without_snapshot_and_malformed_omissions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                row = insert_test_memory(conn, id="memory:no-snapshot")
                set_test_memory_projection_clean(conn)
                state = SimpleNamespace(
                    conn=conn,
                    mode="query",
                    visibility_view="player",
                    memory_context_frozen=False,
                    memory_projection_snapshot=None,
                    memory_summaries=[row],
                    memory_omissions=[],
                    plot_signals=[],
                    plot_signal_omissions=[],
                    memory_context_revision=0,
                )

                section = memory_summaries_section(state)
                maintenance_state = SimpleNamespace(
                    conn=conn,
                    mode="query",
                    visibility_view="maintenance",
                    memory_projection_snapshot=memory_projection_snapshot(
                        conn,
                        memory_projection_health(conn),
                    ),
                    memory_omissions=[
                        {"id": "bad id one", "reason": "stored_stale"},
                        {"id": "bad id two", "reason": "stored_stale"},
                    ],
                )
                omitted = memory_omitted_items(maintenance_state)

        self.assertIsNone(section)
        self.assertEqual(state.memory_summaries, [])
        self.assertEqual(len({item["id"] for item in omitted}), 2)

    def test_clean_empty_memory_and_nonclean_context_keep_lower_quality_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute("delete from main.memory_summaries")
                clean_health = {
                    "status": "clean",
                    "last_turn_id": "turn:seed",
                    "last_error": None,
                    "updated_at": "2026-07-10T00:00:00+00:00",
                }
                with mock.patch(
                    "rpg_engine.memory.memory_projection_health",
                    return_value=clean_health,
                ):
                    empty = find_omitted_relevant_memories(
                        conn,
                        targets=["anything"],
                        view="maintenance",
                        limit=4,
                    )

                conn.execute(
                    """
                    insert into main.events
                    (id, turn_id, game_time, type, title, summary,
                     payload_json, source, created_at)
                    values('event:memory-fallback-context', 'turn:seed', 'day 1',
                           'note', 'Fallback Trail', 'Authoritative recent event',
                           '{}', 'test', '2099-01-01T00:00:00+00:00')
                    """
                )
                conn.execute(
                    "update main.projection_state set status='dirty' where name='memory'"
                )
                conn.commit()
                result = build_context(
                    campaign,
                    conn,
                    user_text="回顾最近发生了什么",
                    mode="query",
                    view="player",
                    budget=1800,
                    max_events=4,
                )

        self.assertEqual(empty[0]["stale_reason"], "empty_memory_table")
        self.assertIn("recent_events", result.sections)
        self.assertIn("Authoritative recent event", result.sections["recent_events"])
        self.assertTrue(
            any(
                item.get("id") == "memory:fallback:projection-status"
                for item in result.omitted_items
            )
        )

    def test_player_direct_memory_boundaries_hide_maintenance_rows_and_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    "update entities set visibility='gm' where id='pc:traveler'"
                )
                row = insert_test_memory(
                    conn,
                    id="memory:character:pc:traveler",
                    title="Maintenance-only title",
                    summary="Maintenance-only summary",
                    visibility_mode="maintenance",
                )
                rendered = render_memory_section([row], conn, view="player")
                redacted = redact_memory_row_for_view(conn, row, view="player")
                state = SimpleNamespace(
                    conn=conn,
                    visibility_view="player",
                    mode="query",
                    memory_projection_snapshot=None,
                    memory_omissions=[dict(row), dict(row)],
                )
                omitted = memory_omitted_items(state)

        serialized = json.dumps(omitted, ensure_ascii=False)
        self.assertNotIn("Maintenance-only", rendered)
        self.assertEqual(redacted["id"], "memory:omitted:unverifiable")
        self.assertEqual(len(omitted), 1)
        self.assertEqual(omitted[0]["id"], "memory:omitted:hidden-sensitive")
        self.assertNotIn("Maintenance-only", serialized)
        self.assertNotIn("maintenance", serialized)

    def test_direct_memory_rebuild_without_current_turn_leaves_projection_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute("update meta set value='' where key='current_turn_id'")
                conn.commit()
                with mock.patch("rpg_engine.memory.build_memory_records", return_value=[]):
                    rebuild_memory_summaries(campaign, conn)
                state = conn.execute(
                    "select status, last_turn_id from main.projection_state "
                    "where name='memory'"
                ).fetchone()

        self.assertEqual(state["status"], "dirty")
        self.assertIsNone(state["last_turn_id"])

    def test_memory_subject_evidence_must_match_authoritative_subject_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.executemany(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values(?, 's', 'subject evidence', 'note', 'subject evidence', 1, ?)
                    """,
                    [
                        ("turn:subject-evidence-1", "2026-07-10T01:00:00+00:00"),
                        ("turn:subject-evidence-2", "2026-07-10T02:00:00+00:00"),
                        ("turn:subject-evidence-3", "2026-07-10T03:00:00+00:00"),
                    ],
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:subject-a",
                        "type": "item",
                        "name": "Subject A",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Authoritative A",
                        "updated_turn_id": "turn:subject-evidence-2",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:subject-b",
                        "type": "item",
                        "name": "Subject B",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Authoritative B",
                        "updated_turn_id": "turn:subject-evidence-3",
                    },
                )
                conn.execute(
                    "update meta set value='turn:subject-evidence-3' where key='current_turn_id'"
                )
                unrelated = insert_test_memory(
                    conn,
                    id="memory:unrelated-subject-evidence",
                    kind="project",
                    subject_id="item:subject-a",
                    summary_type="deterministic_project",
                    freshness_turn_id="turn:subject-evidence-1",
                    source_turn_ids_json=json.dumps(["turn:subject-evidence-1"]),
                    freshness_evidence_json=json.dumps(
                        {
                            "current_turn_id": "turn:subject-evidence-3",
                            "subject_id": "item:subject-b",
                            "subject_updated_turn_id": "turn:subject-evidence-3",
                        }
                    ),
                )
                wrong_update = insert_test_memory(
                    conn,
                    id="memory:wrong-subject-update-evidence",
                    kind="project",
                    subject_id="item:subject-a",
                    summary_type="deterministic_project",
                    freshness_turn_id="turn:subject-evidence-1",
                    source_turn_ids_json=json.dumps(["turn:subject-evidence-1"]),
                    freshness_evidence_json=json.dumps(
                        {
                            "current_turn_id": "turn:subject-evidence-3",
                            "subject_id": "item:subject-a",
                            "subject_updated_turn_id": "turn:subject-evidence-3",
                        }
                    ),
                )
                set_test_memory_projection_clean(
                    conn,
                    last_turn_id="turn:subject-evidence-3",
                )

                unrelated_status = memory_row_freshness(conn, unrelated, view="player")
                wrong_update_status = memory_row_freshness(conn, wrong_update, view="player")

        self.assertEqual(unrelated_status["status"], "stale")
        self.assertEqual(wrong_update_status["status"], "stale")

    def test_trusted_rebuild_marker_rejects_invalid_dynamic_row_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(
                    conn,
                    id="memory:trusted-blob-row",
                    title=sqlite3.Binary(b"blob-title"),
                    summary=sqlite3.Binary(b"blob-summary"),
                    visibility_mode="maintenance",
                    freshness_evidence_json=json.dumps(
                        {
                            "basis": "deterministic_rebuild",
                            "current_turn_id": "turn:seed",
                        }
                    ),
                    derived_authority_json=json.dumps(
                        {
                            "authority": "derived_context",
                            "fact_authority": False,
                            "fact_source": "data/game.sqlite",
                            "summary_overrides_facts": False,
                        }
                    ),
                )
                set_test_memory_projection_clean(conn)
                conn.execute(
                    "delete from schema_migrations where id='0009_memory_summary_provenance'"
                )

                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "stale")

    def test_maintenance_omission_reports_invalid_dynamic_row_generically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(
                    conn,
                    id="memory:maintenance-invalid-row",
                    title=sqlite3.Binary(b"private-title"),
                    visibility_mode="maintenance",
                )
                set_test_memory_projection_clean(conn)

                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["anything"],
                    view="maintenance",
                    limit=4,
                )

        self.assertEqual(omitted[0]["id"], "memory:fallback:invalid-row")
        self.assertEqual(omitted[0]["stale_reason"], "invalid_memory_row")
        self.assertNotIn("private-title", repr(omitted))

    def test_non_clean_projection_short_circuits_memory_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                for index in range(50):
                    insert_test_memory(conn, id=f"memory:non-clean-{index:03d}")
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, 'turn:seed', 'dirty', '2026-07-10T00:00:00+00:00', null)
                    """
                )
                statements: list[str] = []
                conn.set_trace_callback(statements.append)
                loaded = find_relevant_memories(
                    conn,
                    targets=["Test memory"],
                    view="player",
                    limit=50,
                )
                conn.set_trace_callback(None)

        projection_reads = [
            statement
            for statement in statements
            if "from main.projection_state" in " ".join(statement.lower().split())
            and statement.lstrip().lower().startswith("select")
        ]
        self.assertEqual(loaded, [])
        self.assertLessEqual(len(projection_reads), 3)

    def test_memory_source_scan_fails_closed_on_sqlite_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute("alter table events rename to events_unreadable")
                conn.execute("create table events(id text primary key)")
                conn.execute("insert into events(id) values('event:seed')")
                row = {
                    "id": "memory:unreadable-source",
                    "subject_id": None,
                    "title": "Unreadable source",
                    "summary": "Visible text",
                    "key_points_json": "[]",
                    "source_event_ids_json": json.dumps(["event:seed"]),
                    "source_turn_ids_json": "[]",
                    "freshness_evidence_json": "{}",
                }

                unsafe = memory_row_has_hidden_refs(conn, row)

        self.assertTrue(unsafe)

    def test_memory_omission_paginates_past_fresh_rows_and_honors_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                for index in range(25):
                    conn.execute(
                        """
                        insert into memory_summaries
                        (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                         source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                         freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                         derived_authority_json, updated_at)
                        values (?, 'world', null, 'Paged memory', 'fresh', '[]', '[]', '[]', null, null,
                                'deterministic_world', 'player', 'fresh', 'turn:seed', '', ?, ?, ?)
                        """,
                        (
                            f"memory:paged-fresh-{index:02d}",
                            json.dumps({"current_turn_id": "turn:seed"}),
                            json.dumps({"authority": "derived_context", "fact_authority": False}),
                            f"2025-01-01T00:00:{index:02d}+00:00",
                        ),
                    )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values ('memory:paged-stale', 'world', null, 'Paged memory', 'stale', '[]', '[]', '[]',
                            null, null, 'deterministic_world', 'player', 'stale', 'turn:seed', 'stored_stale',
                            '{}', '{}', '2024-01-01T00:00:00+00:00')
                    """
                )
                set_test_memory_projection_clean(conn)

                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["Paged memory"],
                    view="player",
                    limit=1,
                )
                conn.execute("drop table memory_summaries")
                no_items = find_omitted_relevant_memories(
                    conn,
                    targets=["Paged memory"],
                    view="player",
                    limit=0,
                )

        self.assertEqual([item["id"] for item in omitted], ["memory:paged-stale"])
        self.assertEqual(no_items, [])

    def test_latest_turn_id_chunks_and_turn_order_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                turn_ids = []
                for index in range(130):
                    turn_id = f"turn:chunk-{index:03d}"
                    month = 1 + index // 28
                    day = 1 + index % 28
                    conn.execute(
                        """
                        insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                        values(?, 's', 'u', 'note', 'summary', 1, ?)
                        """,
                        (turn_id, f"2024-{month:02d}-{day:02d}T00:00:00+00:00"),
                    )
                    turn_ids.append(turn_id)
                conn.execute(
                    """
                    insert into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values
                      ('turn:tie-a', 's', 'u', 'note', 'a', 1, '2026-01-01T00:00:00+00:00'),
                      ('turn:tie-b', 's', 'u', 'note', 'b', 1, '2026-01-01T00:00:00+00:00')
                    """
                )

                latest = latest_turn_id(conn, turn_ids)
                tie_after = turn_is_after(conn, "turn:tie-b", "turn:tie-a")
                tie_before = turn_is_after(conn, "turn:tie-a", "turn:tie-b")
                unknown = turn_is_after(conn, "turn:not-real", "turn:tie-a")

        self.assertEqual(latest, "turn:chunk-129")
        self.assertTrue(tie_after)
        self.assertFalse(tie_before)
        self.assertIsNone(unknown)

    def test_memory_omissions_include_archived_subject_for_maintenance_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                upsert_entity(
                    conn,
                    {
                        "id": "item:archived-memory-subject",
                        "type": "item",
                        "name": "Archived Memory Subject",
                        "status": "archived",
                        "visibility": "known",
                        "summary": "Archived.",
                    },
                )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:archived-subject",
                        "project",
                        "item:archived-memory-subject",
                        "Archived Memory Subject",
                        "Archived summary",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_project",
                        "player",
                        "fresh",
                        None,
                        "",
                        "{}",
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-03T00:00:00+00:00",
                    ),
                )
                set_test_memory_projection_clean(conn)
                omitted = find_omitted_relevant_memories(
                    conn,
                    targets=["Archived Memory Subject"],
                    view="maintenance",
                    limit=4,
                )

        self.assertTrue(
            any(
                item["id"] == "memory:archived-subject"
                and item["stale_reason"] == "subject_archived"
                for item in omitted
            )
        )

    def test_trusted_memory_lookup_overfetches_past_stale_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values
                      ('turn:trusted-memory-old', 's', 'old', 'note', 'old', 1, '2024-01-01T00:00:00+00:00'),
                      ('turn:trusted-memory-new', 's', 'new', 'note', 'new', 1, '2024-01-02T00:00:00+00:00')
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:trusted-memory-stale",
                        "type": "item",
                        "name": "Trusted Memory Target",
                        "status": "active",
                        "visibility": "known",
                        "summary": "Newer fact.",
                        "updated_turn_id": "turn:trusted-memory-new",
                    },
                )
                for index in range(5):
                    conn.execute(
                        """
                        insert into memory_summaries
                        (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                         source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                         freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                         derived_authority_json, updated_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"memory:trusted-stale-{index}",
                            "world",
                            "item:trusted-memory-stale",
                            "Trusted Memory Target",
                            f"stale {index}",
                            "[]",
                            "[]",
                            json.dumps(["turn:trusted-memory-old"], ensure_ascii=False),
                            "turn:trusted-memory-old",
                            None,
                            "deterministic_world",
                            "player",
                            "fresh",
                            "turn:trusted-memory-old",
                            "",
                            "{}",
                            json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                            f"2024-01-03T00:00:0{index}+00:00",
                        ),
                    )
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:trusted-fresh",
                        "world",
                        None,
                        "Trusted Memory Target",
                        "fresh row",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "fresh",
                        "turn:trusted-memory-new",
                        "",
                        json.dumps({"current_turn_id": "turn:trusted-memory-new"}, ensure_ascii=False),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-02T00:00:00+00:00",
                    ),
                )
                set_test_memory_projection_clean(conn)
                loaded = find_relevant_memories(conn, targets=["Trusted Memory Target"], view="maintenance", limit=1)

        self.assertEqual([row["id"] for row in loaded], ["memory:trusted-fresh"])

    def test_player_renderers_tolerate_missing_world_settings_side_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table world_settings")
                conn.commit()

                scene = render_scene(conn, view="player")
                snapshot = render_current_snapshot_json(campaign, conn, view="player")
                written = write_cards(campaign, conn, index_view="player")

        self.assertIsInstance(scene, str)
        self.assertIsInstance(snapshot, dict)
        self.assertTrue(written)

    def test_memory_rebuild_finds_subjects_filters_hidden_and_renders_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    "insert into meta(key, value) values('current_game_day', '7') "
                    "on conflict(key) do update set value=excluded.value"
                )
                upsert_entity(
                    conn,
                    {
                        "id": "clock:storm",
                        "type": "clock",
                        "name": "暴雨压力",
                        "status": "active",
                        "visibility": "known",
                        "summary": "",
                    },
                )
                conn.execute(
                    """
                    insert or replace into clocks
                    (entity_id, clock_type, segments_total, segments_filled, visibility, trigger_when_full, tick_rules_json)
                    values ('clock:storm', 'weather', 6, 4, 'hinted', '暴雨抵达', '{}')
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "char:ally",
                        "type": "character",
                        "name": "盟友",
                        "status": "active",
                        "visibility": "known",
                        "summary": "可靠但谨慎。",
                        "character": {
                            "role": "",
                            "attitude": "",
                            "trust": 5,
                            "health_state": "",
                            "goals": ["修复水车", ""],
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "project:mill",
                        "type": "project",
                        "name": "水车修复",
                        "status": "active",
                        "visibility": "known",
                        "summary": "修复水车以稳定供水。",
                        "details": {
                            "status": "blocked",
                            "next_steps": ["找木材", "找铁钉"],
                            "risks": {"storm": "high"},
                            "linked_entities": ["char:ally"],
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "fstate:guild",
                        "type": "faction_state",
                        "name": "河岸公会",
                        "status": "active",
                        "visibility": "known",
                        "summary": "控制渡口的组织。",
                        "details": {"encyclopedia": {"stance": "wary", "resources": ["boats", "maps"]}},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "species:hidden",
                        "type": "species",
                        "name": "隐藏族群",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "不应进入玩家记忆。",
                    },
                )
                conn.execute(
                    """
                    insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values
                      ('turn:memory-1', 's', '记录1', 'note', '第1天', 1, '2024-01-01T00:00:00+00:00'),
                      ('turn:memory-2', 's', '记录2', 'note', '第2天', 1, '2024-01-02T00:00:00+00:00')
                    """
                )
                events = [
                    (
                        "event:memory-history-1",
                        "turn:memory-1",
                        "第 1 天 · 夜晚",
                        "history_reconstruction",
                        "旧史一",
                        "盟友曾承诺帮忙。",
                        {"key_points": ["承诺修水车", ""], "provenance": {"tier": "confirmed"}},
                        "2024-01-01T01:00:00+00:00",
                    ),
                    (
                        "event:memory-history-2",
                        "turn:memory-1",
                        "第 1 天 · 夜晚",
                        "history_reconstruction",
                        "旧史二",
                        "河岸公会封锁渡口。",
                        {"key_points": ["渡口受控"], "provenance": {"tier": "rumor"}},
                        "2024-01-01T02:00:00+00:00",
                    ),
                    (
                        "event:memory-action",
                        "turn:memory-2",
                        "",
                        "note",
                        "盟友检查",
                        "char:ally 与水车修复均被记录。",
                        {"subject_id": "char:ally", "project": "project:mill"},
                        "2024-01-02T01:00:00+00:00",
                    ),
                    (
                        "event:memory-fallback-day",
                        "turn:memory-2",
                        "",
                        "note",
                        "无日期事件",
                        "使用 meta 中的日期归档。",
                        {},
                        "2024-01-02T02:00:00+00:00",
                    ),
                ]
                conn.executemany(
                    """
                    insert or replace into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, 'test', ?)
                    """,
                    [
                        (event_id, turn_id, game_time, event_type, title, summary, json.dumps(payload, ensure_ascii=False), created_at)
                        for event_id, turn_id, game_time, event_type, title, summary, payload, created_at in events
                    ],
                )
                conn.commit()

                day_memories = build_day_memories(conn)
                world_memories = build_world_memories(conn)
                records = build_memory_records(conn)
                result = rebuild_memory_summaries(campaign, conn)
                has_memory_table = memory_table_exists(conn)
                relevant = find_relevant_memories(conn, targets=["", "char:ally", "水车"], limit=8)
                rendered = render_memory_section(relevant)
                report_text = result.report_path.read_text(encoding="utf-8")
                metadata = conn.execute(
                    """
                    select summary_type, visibility_mode, freshness_status, freshness_turn_id,
                           stale_reason, freshness_evidence_json, derived_authority_json
                    from memory_summaries
                    where id = 'summary:current-world'
                    """
                ).fetchone()

        self.assertTrue(has_memory_table)
        self.assertTrue(any(memory["id"] == "summary:day-001" for memory in day_memories))
        self.assertTrue(any(memory["id"] == "summary:day-007" for memory in day_memories))
        self.assertIn("暴雨压力 4/6", world_memories[0]["key_points"][-1])
        self.assertGreaterEqual(result.by_kind["day"], 2)
        self.assertGreaterEqual(result.by_kind["world"], 1)
        self.assertGreaterEqual(result.by_kind["character"], 1)
        self.assertTrue(any(memory["kind"] == "project" for memory in records))
        self.assertTrue(any(memory["kind"] == "faction" for memory in records))
        self.assertIn("盟友", rendered)
        self.assertIn("条目数", report_text)
        self.assertEqual(metadata["summary_type"], "deterministic_world")
        self.assertEqual(metadata["visibility_mode"], "player")
        self.assertEqual(metadata["freshness_status"], "fresh")
        self.assertEqual(metadata["stale_reason"], "")
        authority = json.loads(metadata["derived_authority_json"])
        self.assertEqual(authority["authority"], "derived_context")
        self.assertEqual(authority["fact_source"], "data/game.sqlite")
        self.assertFalse(authority["fact_authority"])
        self.assertFalse(authority["summary_overrides_facts"])
        self.assertIn("current_turn_id", json.loads(metadata["freshness_evidence_json"]))
        self.assertIn("- 新鲜度：fresh", report_text)
        self.assertNotIn("隐藏族群", report_text)
        self.assertEqual(parse_day(None), None)
        self.assertEqual(parse_day("第 12 天 · 黄昏"), "12")
        self.assertEqual(as_text_list(None), [])
        self.assertEqual(as_text_list(["a", "", 3]), ["a", "3"])
        self.assertIn("b=1", format_memory_value({"a": [1, 2, 3, 4, 5], "b": 1}))
        self.assertTrue(trim_join(["x" * 20], "", 8).endswith("…"))
        self.assertEqual(safe_id(" ** "), "unknown")
        self.assertEqual(dedupe(["a", "", "a", "b"]), ["a", "b"])

    def test_memory_rebuild_rolls_back_on_bad_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                insert_test_memory(conn, id="memory:preexisting-before-failure")
                conn.commit()
                valid_record = build_memory_records(conn)[0]
                with mock.patch(
                    "rpg_engine.memory.build_memory_records",
                    return_value=[valid_record, {"id": "bad", "kind": "day"}],
                ):
                    with self.assertRaises(KeyError):
                        rebuild_memory_summaries(campaign, conn)
                ids = {
                    str(row["id"])
                    for row in conn.execute(
                        "select id from main.memory_summaries"
                    ).fetchall()
                }

        self.assertEqual(ids, {"memory:preexisting-before-failure"})

    def test_backup_create_list_restore_collision_and_render_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            root = campaign.root
            (root / "package-lock.json").write_text('{"lock": 1}\n', encoding="utf-8")
            (root / "snapshots" / "current.md").write_text("# Original\n", encoding="utf-8")
            (root / "snapshots" / "current.json").write_text('{"snapshot": 1}\n', encoding="utf-8")
            (root / "cards").mkdir(exist_ok=True)
            (root / "cards" / "card.md").write_text("original-card\n", encoding="utf-8")
            (root / "reports").mkdir(exist_ok=True)
            (root / "reports" / "report.md").write_text("original-report\n", encoding="utf-8")

            with mock.patch("rpg_engine.backup.utc_now", return_value="2024-01-02T03:04:05.123456+00:00"):
                first = create_backup(campaign, reason="manual")
                second = create_backup(campaign, reason="manual")

            (root / "package-lock.json").write_text('{"lock": 2}\n', encoding="utf-8")
            (root / "data" / "events.jsonl").write_text("mutated\n", encoding="utf-8")
            (root / "snapshots" / "current.md").write_text("# Mutated\n", encoding="utf-8")
            (root / "cards" / "card.md").write_text("mutated-card\n", encoding="utf-8")
            (root / "reports" / "report.md").write_text("mutated-report\n", encoding="utf-8")
            legacy = first.path.parent / "legacy"
            legacy.mkdir()
            (first.path.parent / "not-a-dir").write_text("skip\n", encoding="utf-8")

            listed = list_backups(campaign)
            rendered = render_backup_list(listed)
            with mock.patch("rpg_engine.backup.utc_now", return_value="2024-01-03T04:05:06+00:00"):
                pre_restore = restore_backup(campaign, first.id)
            restored_lock = (root / "package-lock.json").read_text(encoding="utf-8")
            restored_card = (root / "cards" / "card.md").read_text(encoding="utf-8")
            first_database_backed_up = first.path.joinpath("data", "game.sqlite").exists()
            with self.assertRaises(FileNotFoundError):
                restore_backup(campaign, "missing", create_pre_restore_backup=False)
            no_pre_restore = restore_backup(campaign, second.id, create_pre_restore_backup=False)

        self.assertEqual(first.id, "backup-20240102T030405123456Z")
        self.assertEqual(second.id, "backup-20240102T030405123456Z-2")
        self.assertTrue(first_database_backed_up)
        self.assertTrue(any(item.id == "legacy" and item.reason == "legacy" for item in listed))
        self.assertIn(first.id, rendered)
        self.assertIn("| 无 |", render_backup_list([]))
        self.assertIsNotNone(pre_restore)
        self.assertTrue(pre_restore.id.startswith("backup-20240103T040506Z"))
        self.assertEqual(restored_lock, '{"lock": 1}\n')
        self.assertEqual(restored_card, "original-card\n")
        self.assertIsNone(no_pre_restore)

    def test_backup_create_removes_partial_directory_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            root = campaign.root
            (root / "package-lock.json").write_text('{"lock": 1}\n', encoding="utf-8")
            expected_path = root / "backups" / "v2" / "backup-20240102T030405Z"

            with (
                mock.patch("rpg_engine.backup.utc_now", return_value="2024-01-02T03:04:05+00:00"),
                mock.patch("rpg_engine.backup.shutil.copy2", side_effect=OSError("copy failed")),
            ):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    create_backup(campaign, reason="manual")

            self.assertFalse(expected_path.exists())
            self.assertEqual(list_backups(campaign), [])

    def test_save_turn_delta_cleans_write_artifacts_when_before_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            partial_artifact = campaign.root / "backups" / "v2" / "hook-partial"

            def before_write() -> None:
                partial_artifact.mkdir(parents=True)
                raise RuntimeError("hook failed")

            def cleanup() -> None:
                shutil.rmtree(partial_artifact, ignore_errors=True)

            with connect(campaign) as conn:
                with self.assertRaisesRegex(RuntimeError, "hook failed"):
                    save_turn_delta(
                        campaign,
                        conn,
                        {
                            "user_text": "hook failure",
                            "intent": "wait",
                            "changed": False,
                            "summary": "No change.",
                        },
                        before_write=before_write,
                        rollback_write_artifacts=cleanup,
                    )

            self.assertFalse(partial_artifact.exists())

    def test_save_turn_delta_cleanup_failure_preserves_original_write_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))

            def cleanup() -> None:
                raise RuntimeError("cleanup failed")

            with connect(campaign) as conn:
                with self.assertRaisesRegex(sqlite3.IntegrityError, "UNIQUE constraint failed"):
                    save_turn_delta(
                        campaign,
                        conn,
                        {
                            "turn_id": "turn:seed",
                            "user_text": "duplicate seed",
                            "intent": "wait",
                            "changed": False,
                            "summary": "Duplicate seed.",
                        },
                        before_write=lambda: None,
                        rollback_write_artifacts=cleanup,
                    )

    def test_world_setting_validation_upsert_render_and_database_checks(self) -> None:
        bad_record = {
            "id": "bad:id",
            "name": "",
            "summary": "",
            "category": "invalid",
            "visibility": "public",
            "content": [],
            "applies_when": [],
            "linked_rules": ["rule:ok", ""],
            "linked_clocks": "clock:bad",
            "linked_entities": [3],
            "aliases": [""],
            "priority": True,
        }
        bad_errors = validate_world_setting_record(bad_record)

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "rule:weather",
                        "type": "rule",
                        "name": "天气规则",
                        "status": "active",
                        "visibility": "known",
                        "summary": "天气影响采集。",
                    },
                )
                conn.execute(
                    """
                    insert or replace into rules
                    (entity_id, category, scope, statement, examples_json, exceptions_json, source, locked)
                    values ('rule:weather', 'weather', 'world', '雨天降低视野', '[]', '[]', 'test', 0)
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "clock:rain",
                        "type": "clock",
                        "name": "雨势",
                        "status": "active",
                        "visibility": "known",
                        "summary": "雨势累积。",
                    },
                )
                conn.execute(
                    """
                    insert or replace into clocks
                    (entity_id, clock_type, segments_total, segments_filled, visibility, trigger_when_full, tick_rules_json)
                    values ('clock:rain', 'weather', 4, 1, 'visible', '雨势爆发', '{}')
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:river",
                        "type": "location",
                        "name": "河岸",
                        "status": "active",
                        "visibility": "known",
                        "summary": "河岸地点。",
                    },
                )
                runtime = ContentRuntime(campaign=campaign, conn=conn, turn_id="turn:seed", now="now")
                record = {
                    "id": "world:rain-law",
                    "name": "雨势法则",
                    "summary": "雨势会改变行动风险。",
                    "category": "weather",
                    "scope": "region",
                    "visibility": "known",
                    "priority": 80,
                    "content": {"effect": ["泥泞", "视野降低"]},
                    "applies_when": {"weather": "rain"},
                    "linked_rules": ["rule:weather"],
                    "linked_clocks": ["clock:rain"],
                    "linked_entities": ["loc:river"],
                    "aliases": ["雨天法则"],
                    "source": "test",
                }
                upsert_world_setting(runtime, record)
                upsert_world_setting(runtime, {**record, "id": "world:hidden", "visibility": "hidden"})
                upsert_world_setting(
                    runtime,
                    {
                        **record,
                        "id": "world:gm-only",
                        "visibility": "gm",
                        "summary": "GM-only 世界设定摘要",
                        "content": {"secret": "GM-only 世界设定真相"},
                    },
                )
                gm_only = conn.execute("select details_json from entities where id='world:gm-only'").fetchone()
                conn.execute(
                    "update entities set visibility='known', summary=?, details_json=? where id='world:gm-only'",
                    ("玩家可见外壳摘要", json.dumps({"content": "GM-only 世界设定真相"}, ensure_ascii=False)),
                )
                entity = conn.execute("select * from entities where id='world:rain-law'").fetchone()
                hidden = conn.execute("select details_json from entities where id='world:hidden'").fetchone()
                gm_only_entity = conn.execute("select * from entities where id='world:gm-only'").fetchone()
                rendered = render_world_setting_entity(conn, entity)
                gm_only_rendered = render_world_setting_entity(conn, gm_only_entity)
                lines: list[str] = []
                append_world_setting_card_sections(conn, lines, entity)
                generic = render_world_setting_entity(conn, conn.execute("select * from entities where id='loc:river'").fetchone())
                missing_lines: list[str] = ["before"]
                append_world_setting_card_sections(conn, missing_lines, conn.execute("select * from entities where id='loc:river'").fetchone())
                db_errors = validate_world_settings_database(conn)

        self.assertIn("name: required non-empty string", bad_errors)
        self.assertIn("id: world setting id must start with world:", bad_errors)
        self.assertIn("category: unsupported value invalid", bad_errors)
        self.assertIn("visibility: unsupported value public", bad_errors)
        self.assertIn("content: must be object", bad_errors)
        self.assertIn("applies_when: must be object", bad_errors)
        self.assertIn("priority: must be integer", bad_errors)
        self.assertTrue(any(error.startswith("linked_rules") for error in bad_errors))
        self.assertTrue(any(error.startswith("linked_clocks") for error in bad_errors))
        self.assertTrue(any(error.startswith("linked_entities") for error in bad_errors))
        self.assertTrue(any(error.startswith("aliases") for error in bad_errors))
        self.assertIn("关联规则", rendered)
        self.assertIn("适用条件", rendered)
        self.assertIn("内容", rendered)
        self.assertIn("## 大世界设定", "\n".join(lines))
        self.assertIn("河岸地点", generic)
        self.assertEqual(missing_lines, ["before"])
        self.assertEqual(db_errors, [])
        self.assertNotIn("content", json.loads(hidden["details_json"]))
        self.assertNotIn("content", json.loads(gm_only["details_json"]))
        self.assertIn("此设定摘要对玩家不可见", gm_only_rendered)
        self.assertNotIn("玩家可见外壳摘要", gm_only_rendered)
        self.assertNotIn("GM-only 世界设定真相", gm_only_rendered)
        self.assertNotIn("GM-only 世界设定摘要", gm_only_rendered)

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            self.assertFalse(world_setting_table_exists(conn, "world_settings"))
            self.assertEqual(validate_world_settings_database(conn), [])
            conn.executescript(
                """
                create table entities(id text primary key, name text);
                create table rules(entity_id text primary key);
                create table clocks(entity_id text primary key);
                create table world_settings(
                  entity_id text primary key,
                  category text,
                  scope text,
                  visibility text,
                  priority integer,
                  summary text,
                  content_json text,
                  linked_rules_json text,
                  linked_clocks_json text,
                  linked_entities_json text,
                  applies_when_json text,
                  source text
                );
                insert into world_settings
                values (
                  'world:bad', 'bad_category', 'world', 'public', 10, 'bad',
                  '[]', '["rule:missing"]', '["clock:missing"]', '["loc:missing"]',
                  '[]', 'test'
                );
                """
            )
            invalid_errors = validate_world_settings_database(conn)
        finally:
            conn.close()

        self.assertIn("world setting world:bad has no matching entity", invalid_errors)
        self.assertIn("world setting world:bad has unsupported category bad_category", invalid_errors)
        self.assertIn("world setting world:bad has unsupported visibility public", invalid_errors)
        self.assertIn("world setting world:bad links missing rules row rule:missing", invalid_errors)
        self.assertIn("world setting world:bad links missing clocks row clock:missing", invalid_errors)
        self.assertIn("world setting world:bad links missing entities row loc:missing", invalid_errors)
        self.assertIn("world setting world:bad content_json must be object", invalid_errors)
        self.assertIn("world setting world:bad applies_when_json must be object", invalid_errors)
        self.assertEqual(parse_json_value("{bad", {"fallback": True}), {"fallback": True})
        self.assertEqual(parse_json_list('{"not":"list"}'), [])
        ref_conn = sqlite3.connect(":memory:")
        try:
            ref_conn.execute("create table entities(id text primary key)")
            self.assertFalse(content_ref_exists(ref_conn, "entities", "missing"))
        finally:
            ref_conn.close()


class StateAuditCoverageTests(unittest.TestCase):
    def test_state_audit_flags_payload_keywords_query_and_high_risk_combinations(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            required_delta = {
                "intent": "inspect",
                "changed": True,
                "summary": "获得鱼后消耗木材，承诺交易，并装备弓。",
                "user_text": "查看并记录",
                "events": [
                    "bad-event",
                    {
                        "type": "note",
                        "title": "产出与交易",
                        "summary": "received food and crafted a trade promise",
                        "source": "test",
                        "payload": {
                            "output_quantity_required": True,
                            "material_consumption_required": True,
                            "output_delta_required": True,
                            "relationship_update_required": True,
                            "trade_items_required": True,
                            "state_changes_must_be_structured": True,
                        },
                    },
                    {"payload": "not-object"},
                ],
            }
            required = deterministic_state_audit(conn, delta=required_delta, validation_result={"ok": False})
            required_codes = {finding["code"] for finding in required.findings}

            high_risk_delta = {
                "intent": "query",
                "changed": False,
                "summary": "只是查询但写入箭。",
                "events": [{"type": "note", "summary": "query wrote state", "payload": {}}],
                "upsert_entities": [
                    "bad-entity",
                    {"id": "item:arrow-bad", "type": "item", "name": "箭", "summary": "arrow weapon"},
                ],
            }
            high_risk = deterministic_state_audit(conn, delta=high_risk_delta, validation_result={"ok": True})
            high_risk_codes = {finding["code"] for finding in high_risk.findings}

            explicit_delta = {
                "intent": "note",
                "changed": True,
                "summary": "获得材料，消耗燃料，承诺交易，移动装备。",
                "meta": {
                    "no_output": True,
                    "no_material_consumption": True,
                    "no_relationship_change": True,
                    "no_trade": True,
                    "no_equipment_change": True,
                },
                "events": [
                    {
                        "payload": {
                            "output_quantity_required": True,
                            "material_consumption_required": True,
                            "output_delta_required": True,
                            "relationship_update_required": True,
                            "trade_items_required": True,
                            "state_changes_must_be_structured": True,
                            "no_state_change": True,
                            "no_inventory_change": True,
                            "no_social_change": True,
                        }
                    }
                ],
            }
            explicit = deterministic_state_audit(conn, delta=explicit_delta, validation_result={"ok": True})
        finally:
            conn.close()

        self.assertFalse(required.ok)
        self.assertTrue(should_block_state_audit(required))
        self.assertIn("validate_delta is not ok", required.warnings[0])
        self.assertIn("QUERY_MUTATES_STATE", required_codes)
        self.assertIn("OUTPUT_REQUIRED_WITHOUT_ENTITY", required_codes)
        self.assertIn("MATERIAL_CONSUMPTION_NOT_STRUCTURED", required_codes)
        self.assertIn("OUTPUT_DELTA_REQUIRED_WITHOUT_OUTPUT", required_codes)
        self.assertIn("RELATIONSHIP_NOT_STRUCTURED", required_codes)
        self.assertIn("TRADE_NOT_STRUCTURED", required_codes)
        self.assertIn("STRUCTURED_STATE_REQUIRED", required_codes)
        self.assertIn("NARRATED_GAIN_WITHOUT_INVENTORY", required_codes)
        self.assertIn("NARRATED_CONSUMPTION_WITHOUT_STATE_OP", required_codes)
        self.assertIn("NARRATED_SOCIAL_CHANGE_WITHOUT_STATE_OP", required_codes)
        self.assertIn("NARRATED_EQUIPMENT_CHANGE_WITHOUT_ENTITY", required_codes)
        self.assertIn("QUERY_MUTATES_STATE", high_risk_codes)
        self.assertIn("UNCHANGED_DELTA_HAS_STATE_OPS", high_risk_codes)
        self.assertIn("HIGH_RISK_ITEM_METADATA_INCOMPLETE", high_risk_codes)
        self.assertEqual(high_risk.risk, "high")
        self.assertEqual(missing_high_risk_fields({"type": "item", "item": {"unit": "支"}, "details": {"profile": {"confidence": "low"}}}), ["quantity", "location_id", "source"])
        self.assertTrue(is_high_risk_entity({"type": "material", "name": "火药"}))
        self.assertFalse(is_high_risk_entity({"type": "location", "name": "火药库"}))
        self.assertTrue(explicit_no_change({"no_inventory_change": True}, "trade"))
        self.assertTrue(has_explicit_no_change(explicit_delta, "equipment"))
        self.assertEqual(explicit.risk, "medium")
        self.assertFalse(explicit.requires_human_review)
        self.assertEqual(higher_risk("medium", "high"), "high")
        self.assertEqual(max_risk([{"severity": "medium"}, {"severity": ""}]), "medium")
        self.assertEqual(first_present(({"a": ""}, "bad", {"a": "x"}), ("a",)), "x")

    def test_state_audit_ai_prompt_success_failure_and_compaction_helpers(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("create table meta(key text primary key, value text)")
            conn.execute("insert into meta(key, value) values('current_location_id', 'loc:test')")
            clean_delta = {"intent": "wait", "changed": False, "summary": "No significant change."}
            deterministic = deterministic_state_audit(conn, delta=clean_delta, validation_result={"ok": True})
            prompt = build_state_audit_prompt(
                conn,
                delta=clean_delta,
                validation_result={"ok": True},
                deterministic=deterministic,
                action=None,
                action_options={"mode": "wait"},
            )
            with mock.patch(
                "rpg_engine.ai.state_audit.run_ai_helper_json",
                return_value=SimpleNamespace(ok=False, parsed=None, error=" failure\n" * 80, audit={"backend": "fake"}),
            ):
                failed = run_state_audit(conn, delta=clean_delta, validation_result={"ok": True}, ai="direct")
            with mock.patch(
                "rpg_engine.ai.state_audit.run_ai_helper_json",
                return_value=SimpleNamespace(
                    ok=True,
                    parsed={
                        "ok": False,
                        "risk": "medium",
                        "findings": [{"code": "AI_WARN", "severity": "medium", "message": "m", "path": "$"}],
                        "missing_structured_changes": [{"kind": "ai", "severity": "medium", "message": "m", "path": "$"}],
                        "requires_human_review": False,
                        "warnings": ["ai warning"],
                    },
                    audit={"backend": "fake"},
                ),
            ):
                merged = run_state_audit(
                    conn,
                    delta=clean_delta,
                    validation_result={"ok": True},
                    action="wait",
                    action_options={"speed": "slow"},
                    ai="direct",
                )
            conn_no_meta = sqlite3.connect(":memory:")
            missing_location = current_location_id(conn_no_meta)
            conn_no_meta.close()
        finally:
            conn.close()

        self.assertIn("loc:test", prompt)
        self.assertIn("State Auditor", prompt)
        self.assertEqual(failed.ai_status, "failed")
        self.assertEqual(failed.audit, {"backend": "fake"})
        self.assertLessEqual(len(failed.warnings[-1]), 220)
        self.assertEqual(merged.ai_status, "ok")
        self.assertEqual(merged.risk, "medium")
        self.assertFalse(merged.ok)
        self.assertEqual(merged.audit, {"backend": "fake"})
        self.assertEqual(missing_location, "")
        self.assertEqual(current_location_id(sqlite3.connect(":memory:")), "")
        self.assertTrue(compact_json({"x": "y" * 20}, limit=8).endswith("…"))
        self.assertEqual(with_ai_status(deterministic, ai_status="ok", audit=None).ai_status, "ok")


class ActionResolverCombinationCoverageTests(unittest.TestCase):
    def test_gather_resolver_ready_blocked_and_delta_validation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                populate_action_fixture(conn)

                missing_request = validate_gather_request(campaign, conn, {}, action_options())
                blocked = resolve_gather(campaign, conn, {}, action_options(target="Berry", location="loc:yard", user_text="采集浆果"))
                needs_output = resolve_gather(campaign, conn, {}, action_options(target="Berry", location="loc:start", user_text="采集浆果"))
                ready = resolve_gather(
                    campaign,
                    conn,
                    {},
                    action_options(target="Berry", location="loc:start", user_text="采集浆果", output_confirmed=True),
                )
                delta = dict(ready.proposed_delta or {})
                bad_delta = {
                    **delta,
                    "intent": "wait",
                    "location_after": "loc:yard",
                    "events": [{"payload": {"target_id": "item:wrong", "location_id": "loc:yard", "travel_required": True}}],
                }
                validation = validate_gather_delta(campaign, conn, {}, action_options(target="Berry", location="loc:start"), bad_delta)
                target = conn.execute("select * from entities where id='item:berries'").fetchone()
                location = conn.execute("select * from entities where id='loc:yard'").fetchone()
                blockers = gather_blockers("Berry", target, location, None, {"current_location_id": "loc:start"})
                message = gather_player_message("Berry", target, location, {"current_location_id": "loc:start"}, blockers)
                repairs = gather_repair_options("Berry", target, location, {"current_location_id": "loc:start"}, blockers)

        self.assertEqual(missing_request.missing_required, ("target",))
        self.assertEqual(blocked.status, "needs_confirmation")
        self.assertIn("先前往", blocked.player_message)
        self.assertEqual(needs_output.status, "needs_confirmation")
        self.assertEqual(ready.status, "ready")
        self.assertIn("delta intent is not gather", validation.warnings)
        self.assertTrue(any("location_after must be" in item for item in validation.errors))
        self.assertIn("你现在不在", message)
        self.assertTrue(any(option.id == "travel_then_gather" for option in repairs))

    def test_craft_resolver_ready_blocked_and_delta_validation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                populate_action_fixture(conn)

                missing_request = validate_craft_request(campaign, conn, {}, action_options())
                blocked = resolve_craft(campaign, conn, {}, action_options(target="unknown output", materials="", time_cost=None))
                ready_options = action_options(
                    project="trap project",
                    target="trap",
                    materials="wood",
                    time_cost="30m",
                    user_text="制作陷阱",
                )
                ready = resolve_craft(campaign, conn, {}, ready_options)
                data = resolve_craft_inputs(conn, ready_options)
                delta = dict(ready.proposed_delta or {})
                bad_delta = {
                    **delta,
                    "intent": "wait",
                    "location_after": "loc:yard",
                    "events": [
                        {
                            "payload": {
                                "project_id": "project:wrong",
                                "recipe_id": "recipe:wrong",
                                "target_id": "item:wrong",
                                "location_id": "loc:yard",
                            }
                        }
                    ],
                    "upsert_entities": [],
                }
                validation = validate_craft_delta(campaign, conn, {}, ready_options, bad_delta)
                facts = craft_facts(data)
                message = craft_player_message(data, ["材料未指定：保存前必须列出材料、工具、消耗量和剩余量。"])
                repairs = craft_repair_options(data, ["材料未指定", "配方未指定", "耗时未指定"])

        self.assertEqual(missing_request.missing_required, ("target",))
        self.assertEqual(blocked.status, "needs_confirmation")
        self.assertEqual(ready.status, "ready")
        self.assertIn("project:trap", facts)
        self.assertIn("现在还不能可靠完成", message)
        self.assertTrue(any(option.id == "list_materials" for option in repairs))
        self.assertIn("delta intent is not craft", validation.warnings)
        self.assertTrue(any("location_after must remain" in item for item in validation.errors))
        self.assertTrue(any("payload.project_id" in item for item in validation.errors))

    def test_social_resolver_scope_palette_and_delta_validation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                populate_action_fixture(conn)

                missing_request = validate_social_request(campaign, conn, {}, action_options())
                blocked = resolve_social(campaign, conn, {}, action_options(npc="Neighbor", topic="问候", approach="低压"))
                scope = social_scope(conn, {"meta": {"current_location_id": "loc:start"}, "npc": conn.execute("select * from entities where id='char:npc'").fetchone()})
                facts = social_facts(
                    {
                        "current_location": conn.execute("select * from entities where id='loc:start'").fetchone(),
                        "npc": conn.execute("select * from entities where id='char:npc'").fetchone(),
                    }
                )
                same_place_options = action_options(npc="Traveler", topic="交易盐", approach="赠送")
                same_place = resolve_social(campaign, conn, {}, same_place_options)
                delta = dict(same_place.proposed_delta or {})
                bad_delta = {
                    **delta,
                    "intent": "wait",
                    "location_after": "loc:yard",
                    "events": [{"payload": {"npc_id": "char:wrong", "topic": "wrong", "approach": "wrong"}}],
                }
                validation = validate_social_delta(campaign, conn, {}, same_place_options, bad_delta)
                no_change_delta = {"events": [{"payload": {}}]}
                mark_social_no_change_when_low_impact(no_change_delta, "天气", "闲聊")
                trade_delta = {"events": [{"payload": {}}]}
                mark_social_no_change_when_low_impact(trade_delta, "交易盐", "赠送")
                attached = {"events": [{"payload": {}}]}
                attach_palette_to_social_delta(
                    conn,
                    attached,
                    {"status": "available", "entry": {"id": "palette:test", "_kind": "faction", "name": "传闻"}},
                )

        self.assertEqual(missing_request.missing_required, ("npc",))
        self.assertEqual(blocked.status, "needs_confirmation")
        self.assertTrue(location_blocked_only(list(blocked.confirmations)))
        self.assertEqual(scope.kind, "same_parent")
        self.assertIn("char:npc", facts)
        self.assertEqual(location_name(sqlite3.connect(":memory:"), None), "未知地点")
        self.assertEqual(same_place.status, "ready")
        self.assertIn("delta intent is not social", validation.warnings)
        self.assertTrue(any("location_after must remain" in item for item in validation.errors))
        self.assertTrue(no_change_delta["events"][0]["payload"]["no_relationship_change"])
        self.assertTrue(trade_delta["events"][0]["payload"]["trade_items_required"])
        self.assertNotIn("no_trade", trade_delta["events"][0]["payload"])
        self.assertEqual(attached["events"][0]["payload"]["topic_kind"], "palette_candidate")
        self.assertIn("palette not found", render_social_palette_section(None, "palette:missing"))
        self.assertEqual(validate_social_palette_candidate({"status": "locked", "entry": {}}, "p").errors, ("palette candidate is locked: p",))

    def test_combat_resolver_ready_blocked_and_delta_validation_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                populate_action_fixture(conn)

                missing_request = validate_combat_request(campaign, conn, {}, action_options())
                blocked_data = {
                    "target": None,
                    "ammo": None,
                    "distance": None,
                    "combat": {"ready_state": True},
                    "ammo_item": None,
                    "weapon_query": "missing bow",
                    "weapon": None,
                    "target_query": "missing target",
                    "current_location_id": "loc:start",
                    "ammo_query": "missing ammo",
                    "ready_state": None,
                }
                blockers = combat_blockers(blocked_data)
                ready_options = action_options(
                    target="Wolf",
                    weapon="Bow",
                    ammo="Arrow",
                    distance="近距",
                    ready_state="已上弦",
                    user_text="射击狼",
                )
                ready = resolve_combat(campaign, conn, {}, ready_options)
                delta = dict(ready.proposed_delta or {})
                wrong_decrement = {
                    **delta,
                    "intent": "wait",
                    "events": [
                        {
                            "payload": {
                                "target_id": "threat:wrong",
                                "weapon_id": "item:wrong",
                                "ammo_id": "item:wrong",
                                "distance": "远距",
                            }
                        }
                    ],
                    "upsert_entities": [{"id": "item:arrow", "item": {"quantity": 2}}],
                }
                validation = validate_combat_delta(campaign, conn, {}, ready_options, wrong_decrement)

        self.assertEqual(missing_request.missing_required, ("target", "weapon", "ammo", "distance"))
        self.assertTrue(any("目标未明确" in item for item in blockers))
        self.assertTrue(any("武器未找到" in item for item in blockers))
        self.assertEqual(ready.status, "ready")
        self.assertIn("delta intent is not combat", validation.warnings)
        self.assertTrue(any("payload.target_id" in item for item in validation.errors))
        self.assertTrue(any("quantity must be 1" in item for item in validation.errors))


if __name__ == "__main__":
    unittest.main()
