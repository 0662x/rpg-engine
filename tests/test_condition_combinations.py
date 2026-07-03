from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rpg_engine.intent_router import template_for, turn_contract_from_dict
from rpg_engine.ai.schema_validation import (
    matches_schema_type,
    validate_ai_output_schema,
    validate_schema_value,
    validate_with_jsonschema,
)
from rpg_engine.delta_schema import validate_delta_schema
from rpg_engine.response_acceptance import (
    AcceptanceResult,
    first_blocked_stage,
    response_state_change_blockers,
)
from rpg_engine.response_lint import (
    contains_forbidden_save_claim,
    expected_validation_profile,
    json_blocks_parse,
    lint_response,
    load_response_text,
    load_turn_contract_from_context,
    markdown_headings,
    section_text,
)
from rpg_engine.time_weather import (
    enrich_time_weather_meta,
    format_time_brief,
    format_weather_brief,
    infer_temperature,
    infer_wind,
    parse_weather_label,
)


def base_delta(**overrides: object) -> dict[str, object]:
    delta: dict[str, object] = {
        "user_text": "等待片刻",
        "intent": "wait",
        "changed": False,
        "summary": "No significant change.",
    }
    delta.update(overrides)
    return delta


def event(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "type": "note",
        "title": "记录",
        "summary": "记录一次状态。",
        "source": "condition_combination_test",
        "payload": {},
    }
    value.update(overrides)
    return value


def entity(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": "item:test",
        "type": "item",
        "name": "测试物品",
        "summary": "A test item.",
        "item": {"quantity": 1, "stackable": True},
    }
    value.update(overrides)
    return value


def memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("create table entities (id text primary key)")
    conn.execute("create table clocks (entity_id text primary key)")
    conn.executemany("insert into entities (id) values (?)", [("loc:known",), ("char:known",), ("species:known",)])
    conn.execute("insert into clocks (entity_id) values ('clock:known')")
    return conn


def acceptance_result(**overrides: object) -> AcceptanceResult:
    base = {
        "delta": base_delta(),
        "lint_errors": [],
        "lint_warnings": [],
        "draft_errors": [],
        "draft_warnings": [],
        "consistency_warnings": [],
        "validation_errors": [],
        "validation_warnings": [],
        "saved_turn_id": None,
        "backup_id": None,
        "check_errors": [],
        "memory_report_path": None,
        "diff_markdown": "## Diff\n\nOK\n",
        "save_requested": False,
        "save_allowed": False,
        "decision": "ready:preview_only",
        "turn_proposal": {"proposal_id": "proposal:test"},
        "validation_report": {"profile": "test", "status": "ok", "stages": []},
    }
    base.update(overrides)
    return AcceptanceResult(**base)


def response_contract(
    *,
    mode: str = "action",
    submode: str = "rest",
    headings: tuple[str, ...] = ("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
    required_template: str | None = None,
    validation_profile: str | None = None,
    must_save: bool | None = None,
):
    return turn_contract_from_dict(
        {
            "intent": {
                "user_text": "test",
                "mode": mode,
                "submode": submode,
                "action": submode if mode == "action" else None,
                "options": {},
                "confidence": "high",
                "source": "test",
            },
            "required_template": required_template if required_template is not None else template_for(mode, submode),
            "response_headings": list(headings),
            "requires_preview": mode == "action",
            "must_save": (mode == "action") if must_save is None else must_save,
            "allowed_delta_sources": ["response_draft"],
            "validation_profile": validation_profile
            if validation_profile is not None
            else expected_validation_profile(mode),
        }
    )


class SchemaValidationCombinationTests(unittest.TestCase):
    def test_matches_schema_type_covers_json_type_matrix_and_bool_edges(self) -> None:
        cases = [
            ({}, "object", True),
            ([], "array", True),
            ("x", "string", True),
            (True, "boolean", True),
            (1, "integer", True),
            (True, "integer", False),
            (1.5, "number", True),
            (False, "number", False),
            (None, "null", True),
            ("x", "unknown-extension-type", True),
            (5, ["string", "integer"], True),
            (True, ["integer", "number"], False),
        ]
        for value, schema_type, expected in cases:
            with self.subTest(value=value, schema_type=schema_type):
                self.assertEqual(matches_schema_type(value, schema_type), expected)

    def test_composition_keywords_cover_zero_one_and_multiple_matches(self) -> None:
        one_of = {"oneOf": [{"type": "integer"}, {"type": "number"}]}
        self.assertEqual(validate_schema_value(one_of, 3.5, path="$"), [])
        self.assertEqual(validate_schema_value(one_of, 3, path="$"), ["$: expected exactly one matching schema"])
        self.assertEqual(validate_schema_value(one_of, "3", path="$"), ["$: expected exactly one matching schema"])

        any_of = {"anyOf": [{"enum": ["red"]}, {"type": "integer"}]}
        self.assertEqual(validate_schema_value(any_of, "red", path="$"), [])
        self.assertEqual(validate_schema_value(any_of, 7, path="$"), [])
        self.assertEqual(validate_schema_value(any_of, False, path="$"), ["$: expected one matching schema"])

    def test_allof_object_array_enum_and_additional_property_combinations(self) -> None:
        schema = {
            "allOf": [
                {"type": "object", "required": ["kind"]},
                {"type": "object", "properties": {"kind": {"enum": ["ok"]}}},
            ],
            "type": "object",
            "required": ["items"],
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string"},
                "items": {"type": "array", "items": {"type": "integer"}},
            },
        }

        self.assertEqual(validate_schema_value(schema, {"kind": "ok", "items": [1, 2]}, path="$"), [])

        errors = validate_schema_value(schema, {"kind": "bad", "items": [1, True, "x"], "extra": 1}, path="$")

        self.assertIn("$.kind: expected one of ok", errors)
        self.assertIn("$.extra: unknown field", errors)
        self.assertIn("$.items[1]: expected integer", errors)
        self.assertIn("$.items[2]: expected integer", errors)

    def test_resource_and_jsonschema_validation_error_shapes(self) -> None:
        self.assertEqual(validate_ai_output_schema("not-a-json-resource", {}), ["not-a-json-resource: schema name must end with .json"])
        self.assertTrue(validate_ai_output_schema("missing-test-schema.json", {})[0].startswith("missing-test-schema.json: schema unavailable:"))

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"id": {"type": "string"}},
                    },
                }
            },
        }

        errors = validate_with_jsonschema(schema, {"items": [{"id": 1, "extra": True}], "root_extra": 1})

        self.assertIn("$.root_extra: unknown field", errors)
        self.assertIn("$.items[0].extra: unknown field", errors)
        self.assertTrue(any("$.items[0].id" in item for item in errors))


class TimeWeatherCombinationTests(unittest.TestCase):
    def test_enrich_time_weather_meta_combines_time_weather_water_and_existing_values(self) -> None:
        meta = enrich_time_weather_meta(
            {
                "current_time_block": "第27天 · 上午 → 第28天 · 清晨（鸟鸣很近）",
                "weather_label": "干旱晴朗，大风炎热，地表水全断",
                "season_label": "晚春",
                "weather_temperature": "already-set",
            }
        )

        self.assertEqual(meta["current_game_day"], "28")
        self.assertEqual(meta["current_period"], "dawn")
        self.assertEqual(meta["current_period_label"], "清晨")
        self.assertEqual(meta["current_time_note"], "鸟鸣很近")
        self.assertEqual(meta["weather_condition"], "clear")
        self.assertEqual(meta["weather_precipitation"], "none")
        self.assertEqual(meta["weather_temperature"], "already-set")
        self.assertEqual(meta["weather_wind"], "strong")
        self.assertEqual(meta["drought_state"], "active")
        self.assertEqual(meta["water_pressure"], "severe")
        self.assertEqual(format_time_brief(meta), "第28天 · 清晨（鸟鸣很近）")

    def test_weather_condition_precipitation_temperature_and_wind_matrix(self) -> None:
        weather_cases = [
            ("storm warning", "storm", "heavy"),
            ("雷雨", "storm", "heavy"),
            ("中雨", "rain", "moderate"),
            ("小雨", "rain", "light"),
            ("雪", "snow", "present"),
            ("雾无风", "fog", "none"),
            ("overcast", "overcast", "none"),
            ("cloud cover", "cloudy", "none"),
            ("clear", "clear", "none"),
            ("未知天气", "unknown", "unknown"),
            ("缺水但未下雨", "rain", "present"),
        ]
        for text, condition, precipitation in weather_cases:
            with self.subTest(text=text):
                parsed = parse_weather_label(text)
                self.assertEqual(parsed["weather_condition"], condition)
                self.assertEqual(parsed["weather_precipitation"], precipitation)

        temperature_cases = [
            ("酷热", {}, "hot"),
            ("热", {}, "warm"),
            ("严寒", {}, "cold"),
            ("微凉", {}, "cool"),
            ("温暖", {}, "mild"),
            ("普通天气", {"season_label": "春"}, "mild"),
            ("普通天气", {}, "unknown"),
        ]
        for text, meta, expected in temperature_cases:
            with self.subTest(temperature=text):
                self.assertEqual(infer_temperature(text, meta), expected)

        wind_cases = [("无风", "calm"), ("微风", "light"), ("有风", "present"), ("安静", "unrecorded")]
        for text, expected in wind_cases:
            with self.subTest(wind=text):
                self.assertEqual(infer_wind(text), expected)

    def test_weather_brief_uses_label_or_filters_unknown_parts(self) -> None:
        self.assertEqual(format_weather_brief({"weather_label": "晴，微风"}), "晴，微风")
        self.assertEqual(
            format_weather_brief(
                {
                    "weather_condition_label": "多云",
                    "weather_temperature": "unknown",
                    "weather_precipitation": "none",
                }
            ),
            "多云；precipitation=none",
        )
        self.assertEqual(format_weather_brief({}), "未登记")


class DeltaSchemaCombinationTests(unittest.TestCase):
    def test_cross_field_changed_events_and_state_change_matrix(self) -> None:
        cases = [
            (base_delta(changed=True), "$: changed turn must include events or state changes"),
            (base_delta(changed=True, events=[event()]), None),
            (base_delta(changed=False, meta={"current_location_id": "loc:known"}), "$: state-changing delta should include at least one event explaining the change"),
            (base_delta(changed=True, meta={"current_location_id": "loc:known"}, events=[event()]), None),
            (base_delta(changed=False), None),
        ]
        for delta, expected_error in cases:
            with self.subTest(delta=delta):
                errors = validate_delta_schema(delta)
                if expected_error:
                    self.assertIn(expected_error, errors)
                else:
                    self.assertNotIn("$: changed turn must include events or state changes", errors)
                    self.assertNotIn("$: state-changing delta should include at least one event explaining the change", errors)

    def test_invalid_delta_shape_accumulates_nested_condition_errors(self) -> None:
        conn = memory_conn()
        try:
            delta = base_delta(
                unexpected=True,
                turn_id="turn:bad",
                expected_turn_id="bad",
                command_id="x",
                changed="yes",
                session_id="",
                game_time_before=3,
                location_before="",
                events=[
                    "bad event",
                    {"id": "bad", "type": "", "title": "", "summary": "", "source": "", "payload": "not structured"},
                ],
                upsert_entities=[
                    "bad entity",
                    {
                        "id": "bad id",
                        "type": "mystery",
                        "name": "",
                        "summary": "Bad entity.",
                        "owner_id": "char:known",
                        "location_id": "loc:known",
                        "aliases": ["ok", ""],
                        "details": [],
                        "item": {"quantity": "lots", "stackable": "yes"},
                        "location": "bad",
                        "character": {"trust": "high"},
                        "crop_plot": "bad",
                    },
                    entity(id="item:dup", name="First", item=None),
                    entity(id="item:dup", name="Second"),
                    entity(id="equip:gear", type="equipment", name="Gear", item=None),
                    {"id": "item:missing-details", "type": "item", "name": "Missing details", "summary": "No item subrecord."},
                ],
                tick_clocks=["bad clock", {"id": "", "delta": 0}, {"id": "clock:missing", "delta": 1}],
                meta={"": {}, "list_value": []},
            )

            errors = validate_delta_schema(delta, conn)
        finally:
            conn.close()

        expected_substrings = [
            "$.unexpected: unknown top-level field",
            "$.turn_id: must match turn:000001 style",
            "$.expected_turn_id: must match turn:000001 style",
            "$.command_id: must be 3-128 safe identifier characters",
            "$.changed: must be boolean",
            "$.session_id: must be non-empty string",
            "$.game_time_before: must be non-empty string",
            "$.events[0]: must be object",
            "$.events[1].id: must match event:000001:001 style",
            "$.events[1].type: must be non-empty string",
            "$.events[1].title: must be non-empty string",
            "$.events[1].summary: must be non-empty string",
            "$.events[1].source: must be non-empty string",
            "$.events[1].payload: must be object or array",
            "$.upsert_entities[0]: must be object",
            "$.upsert_entities[1].id: invalid entity id",
            "$.upsert_entities[1].type: unsupported entity type mystery",
            "$.upsert_entities[1].name: must be non-empty string",
            "$.upsert_entities[1]: active entity cannot set both owner_id and location_id",
            "$.upsert_entities[1].aliases: must be array of non-empty strings",
            "$.upsert_entities[1].details: must be object",
            "$.upsert_entities[1].item.quantity: must be number",
            "$.upsert_entities[1].item.stackable: must be boolean",
            "$.upsert_entities[1].location: must be object",
            "$.upsert_entities[1].character.trust: must be integer",
            "$.upsert_entities[1].crop_plot: must be object",
            "$.upsert_entities[2].item: must be object",
            "$.upsert_entities[3].id: duplicate entity id item:dup",
            "$.upsert_entities[4].item: must be object",
            "$.upsert_entities[5].item: recommended and required by engine for item/equipment details",
            "$.tick_clocks[0]: must be object",
            "$.tick_clocks[1].id: must be non-empty string",
            "$.tick_clocks[1].delta: must be non-zero integer",
            "$.tick_clocks[2].id: Missing clock clock:missing",
            "$.meta: keys must be non-empty strings",
            "$.meta.: must be scalar",
            "$.meta.list_value: must be scalar",
        ]
        for expected in expected_substrings:
            with self.subTest(expected=expected):
                self.assertIn(expected, errors)

    def test_database_reference_validation_allows_same_delta_upserts_and_reports_missing_refs(self) -> None:
        conn = memory_conn()
        try:
            delta = base_delta(
                events=[event()],
                location_before="loc:known",
                location_after="loc:new",
                meta={"current_location_id": "loc:missing"},
                upsert_entities=[
                    {
                        "id": "loc:new",
                        "type": "location",
                        "name": "New location",
                        "summary": "Created in the same delta.",
                        "location": {"parent_id": "loc:missing-parent"},
                    },
                    {
                        "id": "char:new",
                        "type": "character",
                        "name": "New character",
                        "summary": "References missing owner and species.",
                        "owner_id": "char:missing",
                        "character": {"species_id": "species:missing"},
                    },
                ],
                tick_clocks=[{"id": "clock:known", "delta": 1}, {"id": "clock:missing", "delta": 1}],
            )

            errors = validate_delta_schema(delta, conn)
        finally:
            conn.close()

        self.assertNotIn("$.location_after: missing entity loc:new", errors)
        self.assertIn("$.meta.current_location_id: missing entity loc:missing", errors)
        self.assertIn("$.upsert_entities[0].location.parent_id: missing entity loc:missing-parent", errors)
        self.assertIn("$.upsert_entities[1].owner_id: missing entity char:missing", errors)
        self.assertIn("$.upsert_entities[1].character.species_id: missing entity species:missing", errors)
        self.assertIn("$.tick_clocks[1].id: Missing clock clock:missing", errors)


class ResponseLintCombinationTests(unittest.TestCase):
    def test_action_lint_accumulates_contract_shape_json_table_and_save_claim_conditions(self) -> None:
        empty = lint_response("", turn_contract=response_contract())
        self.assertFalse(empty.ok)
        self.assertEqual(empty.errors, ["response is empty"])
        self.assertIn("FAILED", empty.render())

        contract = response_contract(
            headings=(),
            required_template="wrong.md",
            validation_profile="preview_only",
            must_save=True,
        )
        response = "\n".join(
            [
                "## 场景",
                "空地很安静。",
                "## 你的状态",
                "状态良好。",
                "## 状态变化",
                "背包增加了盐。",
                "## 后续行动",
                "1. 继续探索",
                "```json",
                "{bad}",
                "```",
                "已经写入存档。",
            ]
        )

        result = lint_response(response, turn_contract=contract, strict=True)

        expected_errors = [
            "turn contract response_headings is empty",
            "turn contract required_template mismatch: wrong.md != rest_turn.md",
            "turn contract validation_profile mismatch: preview_only != player_turn_commit",
            "你的状态 section should contain a structured table",
            "状态变化 section should contain a structured table",
            "follow-up action section should contain numbered options table",
            "response contains invalid fenced JSON",
        ]
        for expected in expected_errors:
            with self.subTest(expected=expected):
                self.assertIn(expected, result.errors)
        self.assertIn(
            "strict mode: state-changing response should mention that play validate-delta/play commit with TurnProposal was or must be run",
            result.warnings,
        )
        self.assertIn("response claims saved/已保存", "\n".join(result.warnings))

    def test_action_submode_warnings_distinguish_combat_gather_and_nonchanging_state(self) -> None:
        base_response = "\n".join(
            [
                "## 场景",
                "现场可控。",
                "## 行动结果",
                "你完成动作。",
                "## 状态变化",
                "| 类型 | 项目 | 变化 |",
                "| --- | --- | --- |",
                "| 无 | 无 | 无 |",
                "## 保存状态",
                "尚未保存，需要 play commit。",
                "## 后续行动",
                "| # | 行动 |",
                "| --- | --- |",
                "| 1 | 等待 |",
            ]
        )
        combat = lint_response(base_response, turn_contract=response_contract(submode="combat"), strict=True)
        gather = lint_response(base_response, turn_contract=response_contract(submode="gather"), strict=True)
        rest = lint_response(base_response, turn_contract=response_contract(submode="rest"), strict=True)

        self.assertIn("combat response should mention ammo/distance/target context", combat.warnings)
        self.assertIn("gather response should mention harvest/gather result and tools/container", gather.warnings)
        self.assertNotIn("strict mode: state-changing response", "\n".join(rest.warnings))
        self.assertTrue(rest.ok, rest.render())

    def test_query_and_maintenance_contracts_cover_structure_and_profile_paths(self) -> None:
        unstructured_query = lint_response(
            "plain answer",
            turn_contract=response_contract(mode="query", submode="entity", headings=(), must_save=False),
            strict=True,
        )
        structured_query = lint_response(
            "## 资料\n| 字段 | 值 |\n| --- | --- |\n| 名称 | Traveler |",
            turn_contract=response_contract(mode="query", submode="entity", headings=("资料",), must_save=False),
            strict=True,
        )
        maintenance = lint_response(
            "## 维护\nOK",
            turn_contract=response_contract(
                mode="maintenance",
                submode="maintenance",
                headings=("维护",),
                required_template="wrong.md",
                validation_profile="player_turn_commit",
                must_save=False,
            ),
        )

        self.assertIn("turn contract response_headings is empty", unstructured_query.errors)
        self.assertIn("query response should use markdown headings", unstructured_query.errors)
        self.assertIn("query response should be structured with a table or subsections", unstructured_query.errors)
        self.assertTrue(structured_query.ok)
        self.assertIn("strict mode: entity query should include an ID when answering about a known entity", structured_query.warnings)
        self.assertIn("turn contract required_template mismatch: wrong.md != action_turn.md", maintenance.errors)
        self.assertIn("turn contract validation_profile mismatch: player_turn_commit != maintenance_commit", maintenance.errors)

    def test_response_lint_helpers_cover_context_loading_sections_json_and_file_text(self) -> None:
        contract_dict = {
            "intent": {
                "user_text": "查看",
                "mode": "query",
                "submode": "scene",
                "action": None,
                "options": {},
                "confidence": "high",
                "source": "test",
            },
            "required_template": "scene_entry.md",
            "response_headings": ["场景"],
            "requires_preview": False,
            "must_save": False,
            "allowed_delta_sources": [],
            "validation_profile": "preview_only",
        }
        text = "   ## 场景\n正文\n### 细节\n更多\n####太紧不会识别\n"

        self.assertEqual(load_turn_contract_from_context({"turn_contract": contract_dict}).intent.mode, "query")
        self.assertEqual(load_turn_contract_from_context({"request": {"turn_contract": contract_dict}}).intent.submode, "scene")
        with self.assertRaisesRegex(ValueError, "context_json must be an object"):
            load_turn_contract_from_context(None)
        with self.assertRaisesRegex(ValueError, "missing request.turn_contract"):
            load_turn_contract_from_context({"request": {}})

        self.assertEqual(markdown_headings(text), ["场景", "细节"])
        self.assertEqual(section_text(text, "场景"), "正文")
        self.assertEqual(section_text(text, "不存在"), "")
        self.assertTrue(json_blocks_parse("```json\n{\"ok\": true}\n```\n```json\n[1]\n```"))
        self.assertFalse(json_blocks_parse("```json\n{bad}\n```"))
        self.assertTrue(contains_forbidden_save_claim("保存完成"))
        self.assertFalse(contains_forbidden_save_claim("尚未保存，需要确认"))
        self.assertEqual(expected_validation_profile("query"), "preview_only")
        self.assertEqual(expected_validation_profile("maintenance"), "maintenance_commit")
        self.assertEqual(expected_validation_profile("action"), "player_turn_commit")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "response.md"
            path.write_text("from file", encoding="utf-8")
            self.assertEqual(load_response_text(path, "ignored"), "from file")
        self.assertEqual(load_response_text(None, "inline"), "inline")
        self.assertEqual(load_response_text(None, None), "")


class ResponseAcceptanceCombinationTests(unittest.TestCase):
    def test_acceptance_result_properties_distinguish_confirmation_from_hard_blockers(self) -> None:
        confirmation = acceptance_result(
            validation_errors=["response_draft requires human confirmation before approval"],
            validation_report={"profile": "test", "status": "blocked", "stages": [{"name": "proposal_guard", "status": "blocked"}]},
        )
        mixed = acceptance_result(
            validation_errors=[
                "response_draft requires human confirmation before approval",
                "delta schema failed",
            ]
        )

        self.assertFalse(confirmation.hard_blocked)
        self.assertTrue(confirmation.validation_requires_confirmation)
        self.assertTrue(mixed.hard_blocked)
        self.assertFalse(mixed.validation_requires_confirmation)
        self.assertEqual(first_blocked_stage(confirmation.validation_report), "proposal_guard")
        self.assertEqual(first_blocked_stage({"stages": ["bad", {"name": "", "status": "ok"}]}), "")

    def test_render_next_step_matrix_covers_saved_blocked_confirm_preview_and_requested_paths(self) -> None:
        stagey_report = {
            "profile": "test-profile",
            "status": "warning",
            "stages": [
                "ignored",
                {"name": "profile", "status": "ok", "skipped_reason": "not needed", "issues": ["minor issue"]},
            ],
        }
        cases = [
            (
                acceptance_result(
                    saved_turn_id="turn:000001",
                    backup_id="backup-1",
                    memory_report_path=Path("memory.md"),
                    validation_report=stagey_report,
                ),
                "已保存",
            ),
            (acceptance_result(lint_errors=["bad response"]), "修复 lint/schema/一致性问题后重新验收"),
            (
                acceptance_result(validation_errors=["requires human confirmation before approval"]),
                "response draft 需要人工确认",
            ),
            (
                acceptance_result(draft_warnings=["ambiguous 状态变化"], validation_warnings=["soft warning"]),
                "解析结果需要确认",
            ),
            (acceptance_result(save_requested=False), "需要自动保存时重跑并加 `--save-if-safe`"),
            (acceptance_result(save_requested=True, decision="confirmation_required"), "本次未保存"),
        ]
        for result, expected in cases:
            with self.subTest(expected=expected):
                rendered = result.render()
                self.assertIn(expected, rendered)
                self.assertIn("## Delta", rendered)
                self.assertIn("## Turn Proposal", rendered)

    def test_response_state_change_blockers_ignore_empty_rows_and_block_meaningful_rows(self) -> None:
        safe_delta = {
            "events": [
                "bad",
                {"payload": []},
                {"payload": {"state_changes": "not a list"}},
                {"payload": {"state_changes": [{}, {"type": "无", "change": "获得盐"}, {"type": "inventory", "change": "无"}]}},
            ]
        }
        risky_delta = {
            "events": [
                {"payload": {"state_changes": [{"type": "inventory", "change": "获得盐"}]}},
            ]
        }

        self.assertEqual(response_state_change_blockers({"events": "not a list"}), [])
        self.assertEqual(response_state_change_blockers(safe_delta), [])
        blockers = response_state_change_blockers(risky_delta)
        self.assertEqual(len(blockers), 1)
        self.assertIn("parsed non-empty 状态变化", blockers[0])


if __name__ == "__main__":
    unittest.main()
