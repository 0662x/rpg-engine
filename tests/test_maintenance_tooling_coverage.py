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
from rpg_engine.db import connect, upsert_entity
from rpg_engine.memory import (
    as_text_list,
    build_day_memories,
    build_memory_records,
    build_world_memories,
    dedupe,
    find_relevant_memories,
    format_memory_value,
    history_points,
    memory_table_exists,
    parse_day,
    rebuild_memory_summaries,
    render_memory_section,
    safe_id,
    trim_join,
)
from rpg_engine.ops_report import build_ops_report, scalar as ops_scalar, table_count_sql, table_exists, write_ops_report
from rpg_engine.reflection import (
    draft_reflection,
    format_value,
    related_events,
    trim,
    validate_reflection_draft,
)
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

from tests.helpers import copy_initialized_minimal, current_turn


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
        self.assertIn("$.operations[4].visibility: must be known/hinted/hidden", errors)
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
                with mock.patch("rpg_engine.memory.build_memory_records", return_value=[{"id": "bad", "kind": "day"}]):
                    with self.assertRaises(KeyError):
                        rebuild_memory_summaries(campaign, conn)
                rows = conn.execute("select count(*) from memory_summaries").fetchone()[0]

        self.assertEqual(rows, 0)

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
                entity = conn.execute("select * from entities where id='world:rain-law'").fetchone()
                hidden = conn.execute("select details_json from entities where id='world:hidden'").fetchone()
                rendered = render_world_setting_entity(conn, entity)
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
