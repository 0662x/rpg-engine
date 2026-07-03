from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

from rpg_engine.actions.registry import (
    get_default_action_registry,
    render_action_resolver_detail,
    render_action_resolver_list,
)
from rpg_engine.ai_intent.risk import (
    GREEN,
    RED,
    YELLOW_CONSENSUS,
    YELLOW_FAST,
    assess_rules_fallback,
)
from rpg_engine.ai_intent.types import BoundIntent, IntentCandidate, RouteOutcome
from rpg_engine.authoring.split import build_split_plan, relative_path as split_relative_path, render_split_plan
from rpg_engine.campaign import load_campaign
from rpg_engine.compat.importers.registry import (
    ImporterRegistry,
    ImporterSpec,
    render_importer_detail,
    render_importer_list,
    run_importer,
)
from rpg_engine.content_types.core import (
    validate_clock_record,
    validate_entity_record,
    validate_relationship_record,
    validate_route_record,
    validate_rule_record,
)
from rpg_engine.db import connect, upsert_clock
from rpg_engine.delta_draft import (
    DeltaDraftResult,
    apply_obvious_meta,
    check_delta_response_consistency,
    dedupe as delta_dedupe,
    parse_state_changes,
    render_consistency_report,
    render_delta_diff,
    risk_warnings,
    summarize_response,
)
from rpg_engine.discovery import (
    discovery_stage,
    discovery_state_id,
    read_json_list,
    record_discovery_from_events,
    stronger_stage,
    table_exists,
    upsert_discovery_from_payload,
)
from rpg_engine.proposal_queue import (
    batch_review_proposals,
    create_proposal,
    ensure_table,
    get_proposal,
    infer_risk_level,
    list_proposals,
    mark_proposal_applied,
    next_proposal_id,
    payload_requires_review,
    proposal_report,
    render_proposal_list,
    render_proposal_report,
    render_rollback_plan,
    review_proposal,
    rollback_hint_for_payload,
    validate_payload,
)
from rpg_engine import save_archive
from rpg_engine.save_archive import (
    ArchiveFile,
    SaveArchiveResult,
    archive_file_to_dict,
    ensure_import_target_is_replaceable,
    export_save,
    import_save_archive,
    parse_manifest_files,
    resolve_archive_output,
    resolve_export_path,
    validate_archive_names,
)
from rpg_engine.save_service import init_v1_save
from rpg_engine.validators import run_checks, run_core_checks
from tests.helpers import MINIMAL_FIXTURE, copy_initialized_minimal


def write_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def candidate(
    *,
    mode: str = "action",
    action: str | None = "rest",
    kind: str = "single",
    safety_flags: tuple[str, ...] = (),
    missing_slots: tuple[str, ...] = (),
    needs_confirmation: tuple[str, ...] = (),
) -> IntentCandidate:
    return IntentCandidate(
        source="rules",
        source_user_text="test",
        kind=kind,
        mode=mode,
        action=action,
        safety_flags=safety_flags,
        missing_slots=missing_slots,
        needs_confirmation=needs_confirmation,
    )


class LowLevelConditionCoverageTests(unittest.TestCase):
    def test_core_database_validators_report_every_integrity_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_root = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_root)
            with connect(campaign) as conn:
                conn.execute("pragma foreign_keys=off")
                conn.execute("insert or replace into meta(key, value) values('current_location_id', 'loc:missing')")
                conn.execute("insert or replace into meta(key, value) values('current_turn_id', 'turn:missing')")
                conn.execute(
                    """
                    insert into entities
                    (id, type, name, status, visibility, location_id, owner_id, summary, details_json, updated_turn_id, updated_at)
                    values
                    ('item:bad-location', 'item', 'BadLoc', 'active', 'known', 'loc:missing', null, 'bad', '{}', 'turn:seed', 'now'),
                    ('item:bad-owner', 'item', 'BadOwner', 'active', 'known', null, 'pc:missing', 'bad', '{}', 'turn:seed', 'now'),
                    ('item:conflict', 'item', 'Conflict', 'active', 'known', 'loc:start', 'pc:traveler', 'bad', '{}', 'turn:seed', 'now'),
                    ('item:negative', 'item', 'Negative', 'active', 'known', null, null, 'bad', '{}', 'turn:seed', 'now'),
                    ('plot:a', 'crop_plot', 'Plot A', 'active', 'known', null, null, 'bad', '{}', 'turn:seed', 'now'),
                    ('plot:b', 'crop_plot', 'Plot B', 'active', 'known', null, null, 'bad', '{}', 'turn:seed', 'now'),
                    ('clock:bad', 'clock', 'Bad Clock', 'active', 'known', null, null, 'bad', '{}', 'turn:seed', 'now')
                    """
                )
                conn.execute(
                    """
                    insert into items(entity_id, category, quantity, unit, quality, durability_current, durability_max, stackable, equipped_slot, properties_json)
                    values('item:negative', 'test', -1, null, null, null, null, 0, null, '{}')
                    """
                )
                conn.execute(
                    """
                    insert into crop_plots(entity_id, plot_no, crop_entity_id, area_sqm, planted_day, growth_stage, growth_stage_max,
                                           harvest_day_min, harvest_day_max, harvest_status, water_status, soil_status, expected_yield, notes)
                    values
                    ('plot:a', 7, 'item:negative', null, null, null, null, null, null, null, null, null, null, null),
                    ('plot:b', 7, 'item:negative', null, null, null, null, null, null, null, null, null, null, null)
                    """
                )
                conn.execute(
                    """
                    insert into clocks(entity_id, clock_type, segments_total, segments_filled, visibility, trigger_when_full, tick_rules_json, last_ticked_turn_id)
                    values('clock:bad', 'project', 0, 3, 'visible', 'bad', '{}', 'turn:seed')
                    """
                )
                conn.execute(
                    """
                    insert into routes(id, from_location_id, to_location_id, travel_minutes, difficulty, hazards_json, requirements_json, last_verified_turn_id)
                    values('route:bad', 'loc:missing-a', 'loc:missing-b', 0, 'normal', '[]', '[]', 'turn:seed')
                    """
                )
                conn.execute("insert into aliases(alias, entity_id, kind) values('ghost', 'entity:missing', 'name')")
                conn.execute(
                    """
                    insert into facts(id, subject_id, predicate, object_entity_id, object_value, value_type, confidence,
                                      valid_from_turn, valid_to_turn, source_event_id, note)
                    values('fact:bad', 'item:negative', 'test', null, 'value', 'text', 1.0, 'turn:002', 'turn:001', 'event:bad', '')
                    """
                )

                core_errors = run_core_checks(conn)
                all_errors = run_checks(conn)

        joined = "\n".join(core_errors)
        self.assertIn("meta.current_location_id points to missing entity", joined)
        self.assertIn("meta.current_turn_id points to missing turn", joined)
        self.assertIn("missing location_id", joined)
        self.assertIn("missing owner_id", joined)
        self.assertIn("negative quantity", joined)
        self.assertIn("both owner_id", joined)
        self.assertIn("crop plot number 7 is duplicated", joined)
        self.assertIn("invalid clock", joined)
        self.assertIn("route route:bad has invalid endpoints/time", joined)
        self.assertIn("alias ghost points to missing entity", joined)
        self.assertIn("fact fact:bad valid_to_turn", joined)
        self.assertGreaterEqual(len(all_errors), len(core_errors))

    def test_discovery_state_recording_handles_absent_tables_existing_rows_and_stage_shapes(self) -> None:
        memory = sqlite3.connect(":memory:")
        record_discovery_from_events(memory, turn_id="turn:seed", events=[{"payload": {"palette_id": "pal:none"}}])
        self.assertFalse(table_exists(memory, "discovery_states"))
        memory.close()

        with tempfile.TemporaryDirectory() as tmp:
            campaign_root = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_root)
            with connect(campaign) as conn:
                self.assertTrue(table_exists(conn, "discovery_states"))
                record_discovery_from_events(
                    conn,
                    turn_id="turn:seed",
                    events=[
                        "bad",
                        {"id": "event:bad", "payload": "not-object"},
                        {"id": "event:skip", "payload": {"target_kind": "item"}},
                        {
                            "id": "event:lead",
                            "payload": {"target_kind": "unknown_lead", "target_query": "strange smoke", "confirmation_methods": "bad"},
                        },
                        {
                            "id": "event:palette",
                            "payload": {
                                "palette_id": "pal:ore",
                                "palette_kind": "material",
                                "palette_status": "available",
                                "event_type": "survey",
                                "palette_name": "Ore",
                                "confirmation_methods": ["seen", "seen", "tested"],
                            },
                        },
                    ],
                )
                discovery_id = upsert_discovery_from_payload(
                    conn,
                    turn_id="turn:seed",
                    event_id="event:confirm",
                    payload={"palette_id": "pal:ore", "palette_status": "clue_only", "discovery_stage": "confirmed", "confirmation_methods": ["confirmed"]},
                )
                row = conn.execute("select * from discovery_states where id = ?", (discovery_id,)).fetchone()

        self.assertEqual(discovery_state_id(palette_id="pal:ore", subject_id=None, kind="material"), "discovery:pal:ore")
        self.assertEqual(discovery_state_id(palette_id=None, subject_id=None, kind="???"), "discovery:unknown")
        self.assertEqual(row["stage"], "confirmed")
        self.assertEqual(row["visibility"], "known")
        self.assertEqual(read_json_list(row["confirmation_methods_json"]), ["seen", "tested", "confirmed"])
        self.assertEqual(read_json_list("not json"), [])
        self.assertEqual(read_json_list('{"bad": true}'), [])
        self.assertEqual(stronger_stage("sampled", "clue"), "sampled")
        stage_cases = [
            ({"discovery_stage": "hinted"}, "clue"),
            ({"sampled": True}, "sampled"),
            ({"palette_status": "available", "event_type": "palette_candidate"}, "clue"),
            ({"palette_status": "available", "target_kind": "material"}, "sampled"),
            ({}, "rumor"),
        ]
        for payload, expected in stage_cases:
            with self.subTest(payload=payload):
                self.assertEqual(discovery_stage(payload), expected)

    def test_semantic_prompt_parsing_normalization_and_ai_collection_edges(self) -> None:
        from rpg_engine.context import semantic

        off_state = SimpleNamespace(semantic_ai="off")
        semantic.collect_semantic_suggestion(off_state)
        self.assertFalse(hasattr(off_state, "semantic_suggestion"))

        with tempfile.TemporaryDirectory() as tmp:
            campaign_root = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_root)
            with connect(campaign) as conn:
                state = SimpleNamespace(
                    semantic_ai="mock",
                    semantic_provider="provider",
                    semantic_model="model",
                    semantic_timeout=1,
                    conn=conn,
                    user_text="look at player",
                    mode="query",
                    submode="entity",
                    entity_hits=[SimpleNamespace(id="pc:traveler", type="character", name="Traveler", reason="explicit")],
                )
                prompt = semantic.build_semantic_prompt(state)
                self.assertIn("pc:traveler", prompt)
                self.assertIn("rest", prompt)

                with mock.patch("rpg_engine.context.semantic.run_ai_helper_json", return_value=SimpleNamespace(ok=False, parsed=None, audit={"id": 1}, error="")):
                    semantic.collect_semantic_suggestion(state)
                self.assertEqual(state.semantic_error, "semantic ai returned no usable suggestion")
                self.assertEqual(state.semantic_audit, {"id": 1})

                parsed = {"mode": "ACTION", "submode": "rest", "targets": ["a", "a", "", "b"], "confidence": "HIGH"}
                with (
                    mock.patch("rpg_engine.context.semantic.run_ai_helper_json", return_value=SimpleNamespace(ok=True, parsed=parsed, audit={"id": 2}, error="")),
                    mock.patch("rpg_engine.context.semantic.apply_semantic_entity_hints") as apply_hints,
                ):
                    semantic.collect_semantic_suggestion(state)
                self.assertEqual(state.semantic_suggestion, parsed)
                apply_hints.assert_called_once_with(state)

        self.assertEqual(semantic.parse_semantic_json("```json\n{\"mode\":\"query\"}\n```"), {"mode": "query"})
        self.assertEqual(semantic.parse_semantic_json("noise {\"mode\":\"query\"} tail"), {"mode": "query"})
        self.assertIsNone(semantic.parse_semantic_json("not json"))
        self.assertEqual(semantic.normalize_string_list(None, limit=3), [])
        normalized = semantic.normalize_semantic_suggestion(
            {
                "mode": "ACTION",
                "submode": "bad",
                "targets": ["alpha", "alpha", "", "beta"],
                "entities_mentioned": "Traveler",
                "missing_confirmations": list(range(10)),
                "notes": "  note  ",
                "confidence": "HIGH",
            }
        )
        self.assertEqual(normalized["mode"], "action")
        self.assertEqual(normalized["submode"], "unknown")
        self.assertEqual(normalized["targets"], ["alpha", "beta"])
        self.assertEqual(len(normalized["missing_confirmations"]), 6)
        self.assertEqual(normalized["confidence"], "high")

    def test_action_registry_core_content_validators_and_importer_registry_edges(self) -> None:
        registry = get_default_action_registry()
        self.assertIsNotNone(__import__("rpg_engine.package_archive"))
        self.assertIsNotNone(__import__("rpg_engine.package_lock"))
        self.assertIsNotNone(__import__("rpg_engine.plugins"))
        self.assertIn("rest", registry.names())
        self.assertIn("Action Resolvers", render_action_resolver_list())
        detail, ok = render_action_resolver_detail("rest")
        self.assertTrue(ok)
        self.assertIn("has_preview", detail)
        missing, ok = render_action_resolver_detail("not-real")
        self.assertFalse(ok)
        self.assertIn("unknown action resolver", missing)

        entity_errors = validate_entity_record(
            {
                "id": "bad id",
                "type": "bad-type",
                "name": "",
                "summary": "",
                "owner_id": "pc:a",
                "location_id": "loc:a",
                "details": [],
                "item": [],
                "character": [],
                "location": [],
                "crop_plot": [],
                "aliases": ["ok", ""],
            }
        )
        self.assertIn("id: invalid entity id", entity_errors)
        self.assertIn("type: unsupported entity type bad-type", entity_errors)
        self.assertIn("active entity cannot set both owner_id and location_id", entity_errors)
        self.assertEqual(validate_entity_record({"id": "item:ok", "type": "item", "name": "Item", "summary": "Item", "aliases": None}), [])
        self.assertIn("id: rule id must start with rule:", validate_rule_record({"id": "bad", "statement": "", "examples": {}, "exceptions": {}, "aliases": [1]}))
        self.assertIn("segments_total: must be positive integer", validate_clock_record({"id": "bad", "name": "", "trigger_when_full": "", "segments_total": False, "segments_filled": -1}))
        self.assertIn("segments_filled: cannot exceed segments_total", validate_clock_record({"id": "clock:x", "name": "Clock", "trigger_when_full": "done", "segments_total": 2, "segments_filled": 3}))
        self.assertIn("travel_minutes: must be positive integer", validate_route_record({"id": "", "from_location_id": "", "to_location_id": "", "travel_minutes": True, "hazards": {}, "requirements": {}}))
        self.assertIn("visibility: must be known/hinted/hidden", validate_relationship_record({"id": "bad", "name": "", "summary": "", "source_id": "", "target_id": "", "visibility": "public", "details": []}))

        calls: list[tuple[object, Path, bool]] = []

        def fake_run(campaign: object, source_dir: Path, apply: bool) -> dict[str, object]:
            calls.append((campaign, source_dir, apply))
            return {"source": str(source_dir), "apply": apply}

        importers = ImporterRegistry()
        spec = ImporterSpec("fake", "fake importer", "archive", fake_run)
        importers.register(spec)
        with self.assertRaisesRegex(ValueError, "duplicate importer"):
            importers.register(spec)
        self.assertEqual(importers.names(), ["fake"])
        self.assertIn("fake importer", render_importer_list(importers))
        self.assertEqual(render_importer_detail("missing", importers), ("FAILED\n- unknown importer: missing\n", False))
        self.assertTrue(render_importer_detail("fake", importers)[1])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = SimpleNamespace(root=root, resolve=lambda value: root / value)
            result = run_importer(campaign, "fake", registry=importers)
            self.assertEqual(result["source"], str(root / "archive"))
            result = run_importer(campaign, "fake", source="relative-source", apply=True, registry=importers)
            self.assertEqual(result["source"], str(root / "relative-source"))
            self.assertTrue(result["apply"])
            with self.assertRaisesRegex(KeyError, "unknown importer"):
                run_importer(campaign, "missing", registry=importers)
        self.assertEqual(len(calls), 2)

    def test_intent_risk_matrix_covers_safety_query_action_and_rules_outcome_combinations(self) -> None:
        cases = [
            (None, {}, RED, False, "missing rules candidate"),
            (candidate(safety_flags=("prompt_injection",)), {}, RED, False, "safety flag"),
            (candidate(mode="query", action=None), {}, GREEN, True, "read-only query"),
            (candidate(mode="maintenance", action=None), {}, RED, False, "maintenance"),
            (candidate(mode="unknown", action=None), {}, YELLOW_CONSENSUS, False, "unknown mode"),
            (candidate(kind="composite"), {}, YELLOW_CONSENSUS, False, "composite"),
            (candidate(action="combat"), {}, RED, False, "high risk"),
            (candidate(action="gather"), {}, YELLOW_CONSENSUS, False, "consensus"),
            (candidate(action="rest"), {"external_candidate": candidate(mode="query", action=None)}, YELLOW_CONSENSUS, False, "mode mismatch"),
            (candidate(action="rest"), {"external_candidate": candidate(action="travel")}, YELLOW_CONSENSUS, False, "action mismatch"),
            (candidate(action="rest"), {"external_candidate": candidate(action="rest", kind="composite")}, YELLOW_CONSENSUS, False, "composite"),
            (
                candidate(action="rest"),
                {"bound": BoundIntent(candidate=candidate(action="rest"), action="rest", options={}, binding_status="missing")},
                YELLOW_CONSENSUS,
                False,
                "binding is missing",
            ),
            (candidate(action="rest", missing_slots=("target",)), {}, YELLOW_CONSENSUS, False, "clarification"),
            (candidate(action="rest"), {"rules_outcome": RouteOutcome(mode="query", submode="scene", action=None)}, YELLOW_CONSENSUS, False, "mode mismatch"),
            (candidate(action="rest"), {"rules_outcome": RouteOutcome(mode="action", submode="travel", action="travel")}, YELLOW_CONSENSUS, False, "action mismatch"),
            (candidate(action="rest"), {"rules_outcome": RouteOutcome(mode="action", submode="rest", action="rest", status="blocked")}, YELLOW_CONSENSUS, False, "blocked"),
            (
                candidate(action="rest"),
                {"rules_outcome": RouteOutcome(mode="action", submode="rest", action="rest", missing_required=("x",))},
                YELLOW_CONSENSUS,
                False,
                "incomplete",
            ),
            (
                candidate(action="rest"),
                {"external_candidate": candidate(action="rest"), "rules_outcome": RouteOutcome(mode="action", submode="rest", action="rest")},
                YELLOW_FAST,
                True,
                "eligible",
            ),
        ]
        for cand, kwargs, risk, allowed, reason in cases:
            with self.subTest(reason=reason):
                decision = assess_rules_fallback(cand, **kwargs)
                self.assertEqual(decision.risk, risk)
                self.assertEqual(decision.allow_rules_fallback, allowed)
                self.assertIn(reason, decision.reason)
                self.assertIsInstance(decision.to_dict()["flags"], list)

        external_flag = assess_rules_fallback(candidate(action="rest"), external_candidate=candidate(action="rest", safety_flags=("hidden_info",)))
        self.assertEqual(external_flag.flags, ("hidden_info",))

    def test_split_planner_delta_draft_and_proposal_queue_edges(self) -> None:
        self.assertFalse(build_split_plan(MINIMAL_FIXTURE, by="chapter").ok)
        self.assertIn("not implemented", render_split_plan(build_split_plan(MINIMAL_FIXTURE, dry_run=False)))
        self.assertEqual(split_relative_path(Path("/root"), Path("/elsewhere/file")), "/elsewhere/file")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_root = root / "campaign"
            shutil.copytree(MINIMAL_FIXTURE, campaign_root)
            manifest = yaml.safe_load((campaign_root / "campaign.yaml").read_text(encoding="utf-8"))
            manifest["content"]["entities"] = [
                "content/entities.yaml",
                "content/items.yaml",
                "content/not-list.yaml",
                "content/missing.yaml",
            ]
            write_yaml(campaign_root / "campaign.yaml", manifest)
            write_yaml(
                campaign_root / "content" / "entities.yaml",
                {
                    "entities": [
                        {"id": "loc:new", "type": "location"},
                        {"id": "item:new", "type": "item"},
                        {"id": "thing:new", "type": "mystery"},
                        "bad",
                    ]
                },
            )
            write_yaml(campaign_root / "content" / "items.yaml", {"entities": [{"id": "item:same", "type": "item"}]})
            write_yaml(campaign_root / "content" / "not-list.yaml", {"entities": "bad"})
            plan = build_split_plan(campaign_root)
            self.assertTrue(plan.ok)
            self.assertGreaterEqual(len(plan.moves), 3)
            self.assertIn("Campaign Split Plan", render_split_plan(plan))
            self.assertIn("record_ids", plan.to_json_text())
            self.assertIn("no moves suggested", render_split_plan(type(plan)(ok=True, dry_run=True, moves=())))

            initialized = copy_initialized_minimal(root / "db")
            campaign = load_campaign(initialized)
            with connect(campaign) as conn:
                upsert_clock(conn, {"id": "clock:test", "name": "Clock", "segments_total": 4, "segments_filled": 1, "trigger_when_full": "done"})
                response = (
                    "## 行动结果\n你离开到 `loc:start`。\n\n"
                    "## 状态变化\n| 类型 | 变化 |\n|---|---|\n| 位置 | 到达 `loc:start` |\n| 时间 | dusk |\n"
                )
                changes = parse_state_changes(response)
                delta = {"summary": "not present", "tick_clocks": [{"id": "clock:test", "delta": 1}], "upsert_entities": [{"id": "item:x", "name": "X", "type": "item"}], "meta": {"current_location_id": "loc:elsewhere"}, "events": [{"type": "test", "title": "T", "summary": "S"}]}
                apply_obvious_meta(delta, changes, {"current_location_id": "loc:start", "current_time_block": "morning"})
                warnings = risk_warnings("攻击并过夜", changes)
                consistency = check_delta_response_consistency(delta, "plain response")
                diff = render_delta_diff(conn, delta)
                self.assertIn("位置变化", changes["title"])
                self.assertEqual(summarize_response(""), "AI 回复草案，需 GM 复核。")
                self.assertTrue(any(item.startswith("高风险词命中：攻击") for item in warnings))
                self.assertIn("未解析到状态变化表", risk_warnings("plain", {"rows": []})[0])
                self.assertTrue(any(item.startswith("delta.summary is not directly present") for item in consistency))
                self.assertIn("clock:test", diff)
                self.assertIn("WARN", render_consistency_report(consistency))
                self.assertEqual(render_consistency_report([]), "OK\n")
                self.assertEqual(delta_dedupe(["a", "a", "b"]), ["a", "b"])
                self.assertIn("## Errors", DeltaDraftResult({"x": 1}, [], ["bad"]).render())

                first = create_proposal(
                    conn,
                    kind="content_delta",
                    payload={"meta": {"review_required": True}, "upsert_entities": [{"id": "item:x"}], "turn_id": "turn:test"},
                    validation={"ok": True, "errors": [], "warnings": ["high-impact route warning"]},
                    source_turn_id="turn:seed",
                )
                second = create_proposal(conn, kind="note", payload={}, validation={"ok": True, "errors": [], "warnings": ["minor"]})
                self.assertEqual(first.id, "proposal:000001")
                self.assertEqual(next_proposal_id(conn), "proposal:000003")
                self.assertEqual(first.risk_level, "high")
                self.assertEqual(second.risk_level, "medium")
                self.assertTrue(payload_requires_review({"meta": {"review_required": True}}))
                self.assertFalse(payload_requires_review({"meta": {"review_required": True, "reviewed_by": "gm"}}))
                self.assertEqual(infer_risk_level({"warnings": []}, {}), "low")
                self.assertEqual(list_proposals(conn, status="needs_review", kind="content_delta", risk_level="high", limit=0)[0].id, first.id)
                reviewed = review_proposal(conn, first.id, approve=True, reviewed_by="gm", reason="ok")
                self.assertEqual(reviewed.status, "approved")
                self.assertIn("reviewed_by", reviewed.to_dict())
                applied = mark_proposal_applied(conn, first.id, applied_turn_id="turn:000001", rollback_hint={"strategy": "backup", "backup_id": "backup-1", "affected": {"upsert_entities": ["item:x"]}})
                self.assertEqual(applied.status, "applied")
                self.assertIn("Affected IDs", render_rollback_plan(applied))
                self.assertEqual(batch_review_proposals(conn, proposal_ids=[applied.id], approve=False, reviewed_by="gm"), [])
                self.assertEqual(batch_review_proposals(conn, status_filter="draft", approve=False, reviewed_by="gm")[0].status, "rejected")
                self.assertEqual(get_proposal(conn, first.id).id, first.id)
                with self.assertRaisesRegex(ValueError, "proposal not found"):
                    review_proposal(conn, "proposal:missing", approve=True, reviewed_by="gm")
                with self.assertRaisesRegex(ValueError, "proposal not found"):
                    get_proposal(conn, "proposal:missing")
                self.assertFalse(validate_payload(conn, "content_delta", {"bad": object()})["ok"])
                self.assertTrue(validate_payload(conn, "note", {})["ok"])
                self.assertIn("Proposal Queue", render_proposal_list(list_proposals(conn)))
                report = proposal_report(conn)
                self.assertIn("by_status", report)
                self.assertIn("Proposal Maintenance Report", render_proposal_report(report))
                self.assertIn("manual_review", rollback_hint_for_payload("note", {})["strategy"])
                self.assertIn("upsert_entities", rollback_hint_for_payload("content_delta", {"upsert_entities": [{"id": "item:x"}]})["affected"])

        old = sqlite3.connect(":memory:")
        old.execute(
            """
            create table proposal_queue (
              id text primary key,
              kind text not null,
              status text not null,
              risk_level text not null,
              source_turn_id text,
              payload_json text not null,
              validation_json text not null default '{}',
              reviewed_by text,
              created_at text not null,
              updated_at text not null
            )
            """
        )
        ensure_table(old)
        columns = {row[1] for row in old.execute("pragma table_info(proposal_queue)").fetchall()}
        self.assertTrue({"review_reason", "applied_turn_id", "rollback_hint_json"}.issubset(columns))
        old.close()

    def test_save_archive_round_trip_and_rejects_corrupt_or_unsafe_archives(self) -> None:
        def write_archive(path: Path, manifest: dict[str, object] | None, members: dict[str, bytes]) -> None:
            with zipfile.ZipFile(path, "w") as archive:
                if manifest is not None:
                    archive.writestr(save_archive.MANIFEST_NAME, json.dumps(manifest))
                for name, data in members.items():
                    archive.writestr(name, data)

        def manifest_for(files: list[ArchiveFile]) -> dict[str, object]:
            return {
                "archive_schema_version": save_archive.ARCHIVE_VERSION,
                "files": [archive_file_to_dict(item) for item in files],
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir)
            campaign = load_campaign(save_dir)
            archive_path = root / "export.aigmsave"
            exported = export_save(campaign, archive_path)
            imported = import_save_archive(archive_path, root / "imported")
            self.assertTrue(exported.files)
            self.assertEqual(resolve_export_path(campaign, "relative/export.aigmsave"), campaign.root / "relative" / "export.aigmsave")
            self.assertIn("Save Export", exported.render_export())
            self.assertIn("Save Import", imported.render_import())
            self.assertEqual(exported.archive_path, archive_path)
            self.assertTrue((root / "imported" / "campaign.yaml").exists())
            self.assertEqual(parse_manifest_files({"files": [archive_file_to_dict(exported.files[0])]}), [exported.files[0]])
            self.assertEqual(resolve_archive_output(root, "nested/file.txt"), root.resolve() / "nested" / "file.txt")
            self.assertEqual(SaveArchiveResult(Path("target"), (ArchiveFile("a", 1, "x"),), {}).render_import().count("files"), 1)

            empty_target = root / "empty"
            empty_target.mkdir()
            ensure_import_target_is_replaceable(empty_target, force=False)
            nonempty_target = root / "nonempty"
            nonempty_target.mkdir()
            (nonempty_target / "file.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "not empty"):
                ensure_import_target_is_replaceable(nonempty_target, force=False)
            ensure_import_target_is_replaceable(nonempty_target, force=True)

            for bad_names in [[""], ["bad\\path"], ["/abs"], ["../escape"]]:
                with self.subTest(bad_names=bad_names):
                    with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                        validate_archive_names(bad_names)
            with self.assertRaisesRegex(ValueError, "unsafe archive path"):
                resolve_archive_output(root, "../escape")

            parse_cases = [
                ({"files": "bad"}, "manifest files must be an array"),
                ({"files": [None]}, "must be object"),
                ({"files": [{}]}, "path is required"),
                ({"files": [{"path": "a", "bytes": 1}, {"path": "a", "bytes": 1}]}, "duplicated"),
                ({"files": [{"path": "a", "bytes": -1}]}, "non-negative"),
            ]
            for manifest, message in parse_cases:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        parse_manifest_files(manifest)
            too_many = {"files": [{"path": f"{index}.txt", "bytes": 0, "sha256": ""} for index in range(save_archive.MAX_ARCHIVE_FILES + 1)]}
            with self.assertRaisesRegex(ValueError, "too many files"):
                parse_manifest_files(too_many)

            data = b"hello"
            good_file = ArchiveFile("data.txt", len(data), hashlib.sha256(data).hexdigest())
            corrupt_archives = [
                (None, {"data.txt": data}, "missing save-archive.json"),
                ({"archive_schema_version": 999, "files": []}, {}, "schema version mismatch"),
                (manifest_for([]), {"extra.txt": b"x"}, "unlisted file"),
                (manifest_for([good_file]), {}, "missing file listed"),
                (manifest_for([ArchiveFile("data.txt", save_archive.MAX_ARCHIVE_MEMBER_BYTES + 1, good_file.sha256)]), {"data.txt": data}, "member too large"),
                (manifest_for([ArchiveFile("data.txt", len(data) + 1, good_file.sha256)]), {"data.txt": data}, "size mismatch"),
                (manifest_for([ArchiveFile("data.txt", len(data), "bad")]), {"data.txt": data}, "checksum mismatch"),
            ]
            for index, (manifest, members, message) in enumerate(corrupt_archives):
                bad_archive = root / f"bad-{index}.aigmsave"
                write_archive(bad_archive, manifest, members)
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        import_save_archive(bad_archive, root / f"target-{index}")

            total_archive = root / "too-large-total.aigmsave"
            write_archive(total_archive, manifest_for([good_file]), {"data.txt": data})
            with mock.patch("rpg_engine.save_archive.MAX_ARCHIVE_TOTAL_BYTES", 1):
                with self.assertRaisesRegex(ValueError, "maximum total size"):
                    import_save_archive(total_archive, root / "target-total")


if __name__ == "__main__":
    unittest.main()
