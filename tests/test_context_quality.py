from __future__ import annotations

import json
import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any

from rpg_engine.context import DEFAULT_CONTEXT_COLLECTORS, ContextCollector, ContextPipeline, ContextPipelineStep
from rpg_engine.context.collectors import (
    collect_plot_hints_from_value,
    enrich_collector_item,
    plot_signal_omission_item,
    progress_is_active,
)
from rpg_engine.context.diagnostics import (
    build_budget_evidence,
    build_quality_diagnostics,
    high_value_missing_signals,
)
from rpg_engine.context.resolution import dedupe_texts, extract_entity_ids, sanitize_fts_query
from rpg_engine.context.sections import ContextSection, apply_budget, estimate_tokens
from rpg_engine.context.semantic import normalize_semantic_suggestion, parse_semantic_json
from rpg_engine.context_builder import (
    apply_semantic_request_decision,
    collector_item_omitted_by_budget,
    default_context_pipeline,
    filter_plot_signals_for_selected_sections,
    section_item_evidence,
    section_source_metadata,
    semantic_request_decision,
    template_for,
)
from rpg_engine.intent_router import infer_mode, infer_submode


class ContextBuilderUnitTests(unittest.TestCase):
    def test_intent_classifier_matrix(self) -> None:
        cases = [
            ("看一下终极复合弩属性", "entity", "query", "entity_query.md"),
            ("我去小溪", "travel", "action", "scene_entry.md"),
            ("我收鱼笼", "gather", "action", "gather_turn.md"),
            ("制作折光透镜", "craft", "action", "craft_turn.md"),
            ("找 An 交易", "social", "action", "social_turn.md"),
            ("我用终极复合弩攻击T3", "combat", "action", "combat_turn.md"),
            ("睡到天亮", "rest", "action", "rest_turn.md"),
            ("同步一下系统设计", "maintenance", "maintenance", "action_turn.md"),
            ("系统维护：修复存档索引", "maintenance", "maintenance", "action_turn.md"),
        ]
        for text, expected_submode, expected_mode, expected_template in cases:
            with self.subTest(text=text):
                submode = infer_submode(text)
                mode = infer_mode(text, submode)
                self.assertEqual(submode, expected_submode)
                self.assertEqual(mode, expected_mode)
                self.assertEqual(template_for(mode, submode), expected_template)

    def test_semantic_json_parser_extracts_fenced_and_prefixed_json(self) -> None:
        parsed = parse_semantic_json(
            "说明文字\n```json\n{\"mode\":\"QUERY\",\"submode\":\"entity\",\"targets\":[\"终极复合弩\"]}\n```"
        )
        self.assertEqual(parsed["mode"], "QUERY")
        parsed = parse_semantic_json("prefix {\"mode\":\"action\",\"submode\":\"travel\"} suffix")
        self.assertEqual(parsed["submode"], "travel")
        self.assertIsNone(parse_semantic_json("not json"))

    def test_semantic_normalizer_bounds_values_and_lists(self) -> None:
        normalized = normalize_semantic_suggestion(
            {
                "mode": "QUERY",
                "submode": "bad",
                "targets": ["终极复合弩", "终极复合弩", "x" * 100],
                "entities_mentioned": "An",
                "missing_confirmations": ["距离", "", "弹药"],
                "notes": ["n"] * 10,
                "confidence": "HIGH",
            }
        )
        self.assertEqual(normalized["mode"], "query")
        self.assertEqual(normalized["submode"], "unknown")
        self.assertEqual(normalized["targets"][0], "终极复合弩")
        self.assertEqual(len(normalized["targets"][1]), 80)
        self.assertTrue(normalized["targets"][1].endswith("…"))
        self.assertEqual(normalized["entities_mentioned"], ["An"])
        self.assertEqual(normalized["missing_confirmations"], ["距离", "弹药"])
        self.assertEqual(len(normalized["notes"]), 1)
        self.assertEqual(normalized["confidence"], "high")

    def test_semantic_request_decision_only_accepts_valid_modes(self) -> None:
        self.assertEqual(
            semantic_request_decision({"mode": "action", "submode": "routine"}),
            ("action", "routine"),
        )
        self.assertEqual(
            semantic_request_decision({"mode": "query", "submode": "scene"}),
            ("query", "scene"),
        )
        self.assertIsNone(semantic_request_decision({"mode": "query", "submode": "craft"}))
        self.assertIsNone(semantic_request_decision({"mode": "action", "submode": "unknown"}))

    def test_high_confidence_semantic_decision_is_trace_only(self) -> None:
        state = SimpleNamespace(
            semantic_suggestion={"mode": "action", "submode": "routine", "confidence": "high"},
            submode_arg=None,
            mode_arg="auto",
            mode="query",
            submode="entity",
            requested_budget=None,
            campaign_budget=3000,
            assumptions=[],
        )

        apply_semantic_request_decision(state)

        self.assertEqual(state.mode, "query")
        self.assertEqual(state.submode, "entity")
        self.assertFalse(hasattr(state, "must_save"))
        self.assertIn("AI 语义判断仅记录", state.assumptions[0])

    def test_semantic_decision_does_not_override_explicit_submode_or_low_confidence(self) -> None:
        explicit = SimpleNamespace(
            semantic_suggestion={"mode": "action", "submode": "routine", "confidence": "high"},
            submode_arg="craft",
            mode_arg="auto",
            mode="action",
            submode="craft",
            requested_budget=None,
            campaign_budget=3000,
            assumptions=[],
        )
        apply_semantic_request_decision(explicit)
        self.assertEqual(explicit.submode, "craft")

        low = SimpleNamespace(
            semantic_suggestion={"mode": "action", "submode": "routine", "confidence": "medium"},
            submode_arg=None,
            mode_arg="auto",
            mode="query",
            submode="entity",
            requested_budget=None,
            campaign_budget=3000,
            assumptions=[],
        )
        apply_semantic_request_decision(low)
        self.assertEqual(low.mode, "query")
        self.assertEqual(low.submode, "entity")
        self.assertEqual(low.assumptions, [])

    def test_fts_sanitizer_and_entity_id_extraction(self) -> None:
        self.assertEqual(sanitize_fts_query("终极@复合/弩!!! T3? 火药箭"), '"终极" OR "复合" OR "弩" OR "T3" OR "火药箭"')
        self.assertEqual(sanitize_fts_query("NOT official notice"), '"NOT" OR "official" OR "notice"')
        self.assertEqual(sanitize_fts_query("看 弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("查 弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("问 弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("找 弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("看弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("查弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("问弩"), '"弩"')
        self.assertEqual(sanitize_fts_query("找弩"), '"弩"')
        ids = extract_entity_ids({"a": "item:test-harmonic-bow", "b": ["loc:test-crystal-marsh", "not:id"]})
        self.assertEqual(ids, ["item:test-harmonic-bow", "loc:test-crystal-marsh"])

    def test_budget_keeps_required_sections_and_omits_low_priority_optional(self) -> None:
        required = ContextSection(key="current_scene", title="Scene", content="x" * 1600, priority=100, required=True)
        useful = ContextSection(key="relevant_entities", title="Entities", content="y" * 200, priority=90)
        low = ContextSection(key="background", title="Background", content="z" * 1200, priority=10)
        for section in [required, useful, low]:
            section.estimated_tokens = estimate_tokens(section.content)
        selected, omitted = apply_budget([low, useful, required], limit=900)
        self.assertIn(required, selected)
        self.assertIn(useful, selected)
        self.assertIn(low, omitted)
        self.assertEqual(low.omitted_reason, "token budget")

    def test_budget_evidence_records_effective_limit_decisions_and_required_overflow(self) -> None:
        required = ContextSection(
            key="current_scene",
            title="Scene",
            content="x" * 1320,
            priority=100,
            required=True,
        )
        useful = ContextSection(
            key="relationships",
            title="Relationships",
            content="y" * 220,
            priority=73,
        )
        for section in (required, useful):
            section.estimated_tokens = estimate_tokens(section.content)

        selected, omitted = apply_budget([required, useful], limit=500)
        evidence = build_budget_evidence(
            sections=[required, useful],
            selected=selected,
            omitted=omitted,
            limit=500,
            requested=100,
            campaign_default=3000,
            policy_profile="explicit",
            policy_reason="explicit budget 500",
        )

        self.assertEqual(evidence["limit"], 500)
        self.assertEqual(evidence["requested"], 100)
        self.assertTrue(evidence["over_limit"])
        self.assertEqual(evidence["overflow_tokens"], evidence["estimated"] - 500)
        self.assertTrue(evidence["required_over_limit"])
        self.assertEqual(evidence["required_overflow_tokens"], evidence["required_tokens"] - 500)
        self.assertGreater(evidence["utilization"], 1.0)
        self.assertEqual(evidence["included_sections"], ["current_scene"])
        self.assertEqual(evidence["omitted_sections"], ["relationships"])
        self.assertEqual(
            [decision["section"] for decision in evidence["decisions"]],
            ["current_scene", "relationships"],
        )
        self.assertEqual(evidence["decisions"][0]["reason"], "required")
        self.assertEqual(evidence["decisions"][1]["reason"], "token budget")
        self.assertEqual(evidence["sections"], {"current_scene": required.estimated_tokens})

    def test_budget_evidence_bounds_json_numeric_edges(self) -> None:
        required = ContextSection(
            key="current_scene",
            title="Scene",
            content="scene",
            priority=100,
            required=True,
            estimated_tokens=10**100,
        )

        evidence = build_budget_evidence(
            sections=[required],
            selected=[required],
            omitted=[],
            limit=10**100,
            requested=10**100,
            campaign_default=10**100,
            policy_profile="explicit",
            policy_reason="numeric edge",
        )

        json.dumps(evidence, allow_nan=False)
        self.assertEqual(evidence["limit"], (1 << 53) - 1)
        self.assertEqual(evidence["requested"], (1 << 53) - 1)
        self.assertEqual(evidence["estimated"], (1 << 53) - 1)
        self.assertEqual(evidence["campaign_default"], (1 << 53) - 1)

    def test_budget_evidence_preserves_signed_request_and_compares_before_saturation(self) -> None:
        maximum = (1 << 53) - 1
        required_a = ContextSection(
            key="required_a",
            title="Required A",
            content="a",
            priority=100,
            required=True,
            estimated_tokens=maximum,
        )
        required_b = ContextSection(
            key="required_b",
            title="Required B",
            content="b",
            priority=99,
            required=True,
            estimated_tokens=1,
        )

        evidence = build_budget_evidence(
            sections=[required_a, required_b],
            selected=[required_a, required_b],
            omitted=[],
            limit=maximum,
            requested=-9,
            campaign_default=3000,
            policy_profile="explicit",
            policy_reason="signed and saturated edge",
        )

        self.assertEqual(evidence["requested"], -9)
        self.assertEqual(evidence["estimated"], maximum)
        self.assertEqual(evidence["required_tokens"], maximum)
        self.assertTrue(evidence["over_limit"])
        self.assertEqual(evidence["overflow_tokens"], 1)
        self.assertTrue(evidence["required_over_limit"])
        self.assertEqual(evidence["required_overflow_tokens"], 1)

    def test_plot_signal_reconciliation_records_removed_section_as_omitted(self) -> None:
        section = ContextSection(
            key="plot_signals",
            title="Plot Signals",
            content="plot",
            priority=82,
            estimated_tokens=4,
        )
        selected = [section]
        relationship_section = ContextSection(
            key="relationships",
            title="Relationships",
            content="relationships",
            priority=83,
            estimated_tokens=20,
            omitted_reason="token budget",
        )
        omitted = [relationship_section]
        selected_keys = {"plot_signals"}
        state = SimpleNamespace(
            mode="action",
            plot_signals=[
                {
                    "id": "plot:relationship:missing-source",
                    "signal_type": "relationship",
                    "reason": "relevant relationship",
                    "priority": 82,
                    "source_refs": ["rel:missing-source"],
                    "required_section_keys": ["relationships"],
                    "budget": {"included": True, "priority": 82},
                }
            ],
            plot_signal_omissions=[],
        )

        filter_plot_signals_for_selected_sections(
            state,
            selected,
            omitted,
            selected_keys,
        )

        self.assertEqual(selected, [])
        self.assertEqual(selected_keys, set())
        self.assertEqual(omitted, [relationship_section, section])
        self.assertEqual(section.omitted_reason, "source section omitted by token budget")
        self.assertEqual(state.plot_signal_omissions[0]["reason_code"], "over_budget")

    def test_plot_signal_reconciliation_uses_unavailable_reason_without_budget_omission(self) -> None:
        section = ContextSection(
            key="plot_signals",
            title="Plot Signals",
            content="plot",
            priority=82,
            estimated_tokens=4,
        )
        selected = [section]
        omitted: list[ContextSection] = []
        selected_keys = {"plot_signals"}
        state = SimpleNamespace(
            mode="action",
            plot_signals=[
                {
                    "id": "plot:relationship:unavailable-source",
                    "signal_type": "relationship",
                    "reason": "relationship dependency",
                    "priority": 82,
                    "source_refs": ["rel:unavailable-source"],
                    "required_section_keys": ["relationships"],
                    "budget": {"included": True, "priority": 82},
                }
            ],
            plot_signal_omissions=[],
        )

        filter_plot_signals_for_selected_sections(
            state,
            selected,
            omitted,
            selected_keys,
        )

        self.assertEqual(selected, [])
        self.assertEqual(omitted, [section])
        self.assertEqual(section.omitted_reason, "required source section unavailable")
        self.assertEqual(state.plot_signal_omissions[0]["reason_code"], "unavailable")
        self.assertNotIn("budget", state.plot_signal_omissions[0]["reason"])

    def test_unavailable_section_does_not_set_trimmed_or_budget_tradeoff(self) -> None:
        selected_section = ContextSection(
            key="low_priority_context",
            title="Low Priority",
            content="selected",
            priority=20,
            estimated_tokens=10,
        )
        unavailable_section = ContextSection(
            key="plot_signals",
            title="Plot Signals",
            content="unavailable",
            priority=82,
            estimated_tokens=40,
            omitted_reason="required source section unavailable",
        )
        budget = build_budget_evidence(
            sections=[selected_section, unavailable_section],
            selected=[selected_section],
            omitted=[unavailable_section],
            limit=500,
            requested=500,
            campaign_default=3000,
            policy_profile="explicit",
            policy_reason="unavailable dependency",
        )

        self.assertFalse(budget["trimmed"])
        unavailable_decision = next(
            item for item in budget["decisions"] if item["section"] == "plot_signals"
        )
        self.assertEqual(unavailable_decision["reason_code"], "unavailable")

        state = SimpleNamespace(
            conn=None,
            entity_hits=[],
            semantic_alias_gaps=[],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )
        diagnostics = build_quality_diagnostics(
            state=state,
            budget=budget,
            loaded_items=[],
            omitted_items=[],
            context_view="maintenance",
        )
        self.assertFalse(
            any(item["code"] == "low_value_budget_tradeoff" for item in diagnostics),
            diagnostics,
        )

    def test_high_value_missing_signals_are_thresholded_deduped_sorted_and_bounded(self) -> None:
        omitted_items = [
            {
                "id": f"item:{index}",
                "source": "relationships" if index % 2 else "progress_context",
                "priority": 70 + index,
                "reason": "source section omitted by token budget",
                "reason_code": "over_budget",
                "budget": {
                    "included": False,
                    "reason": "source section omitted by token budget",
                    "reason_code": "over_budget",
                    "priority": 70 + index,
                    "estimated_tokens": 20 + index,
                },
            }
            for index in range(12)
        ]
        omitted_items.extend(
            [
                dict(omitted_items[-1]),
                {
                    "id": "item:low",
                    "source": "recent_events",
                    "priority": 69,
                    "reason": "source section omitted by token budget",
                    "reason_code": "over_budget",
                    "budget": {
                        "included": False,
                        "reason": "source section omitted by token budget",
                        "reason_code": "over_budget",
                    },
                },
                {
                    "id": "item:not-budget",
                    "source": "memory_summaries",
                    "priority": 99,
                    "reason": "stale",
                    "budget": {"included": False, "reason": "stale"},
                },
            ]
        )
        budget = {
            "limit": 500,
            "required_tokens": 620,
            "required_over_limit": True,
            "required_overflow_tokens": 120,
        }

        signals = high_value_missing_signals(budget=budget, omitted_items=omitted_items)

        self.assertEqual(len(signals), 8)
        self.assertEqual(signals[0]["code"], "required_budget_overflow")
        self.assertEqual(signals[0]["signal"], "required_sections")
        self.assertEqual(
            [signal["priority"] for signal in signals],
            sorted((signal["priority"] for signal in signals), reverse=True),
        )
        keys = [(signal["code"], signal["source"], signal["signal"]) for signal in signals]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertNotIn("item:low", {signal["signal"] for signal in signals})
        self.assertNotIn("item:not-budget", {signal["signal"] for signal in signals})
        self.assertTrue(all(signal["severity"] == "advisory" for signal in signals))

    def test_high_value_signals_use_structured_budget_reason_and_reserve_required_overflow(self) -> None:
        omitted_items = [
            {
                "id": f"item:structured-{index}",
                "source": "progress_context",
                "priority": 101 + index,
                "reason": "over limit",
                "reason_code": "over_budget",
                "budget": {
                    "included": False,
                    "reason": "over limit",
                    "reason_code": "over_budget",
                    "priority": 101 + index,
                },
            }
            for index in range(8)
        ]
        omitted_items.append(
            {
                "id": "item:false-budget-text",
                "source": "memory_summaries",
                "priority": 999,
                "reason": "budget diagnostics unavailable",
                "budget": {
                    "included": False,
                    "reason": "budget diagnostics unavailable",
                    "priority": 999,
                },
            }
        )
        omitted_items.append(
            {
                "id": "item:collector-cap",
                "source": "relationships",
                "priority": 998,
                "reason": "relationship omitted by collector-local relevance cap",
                "reason_code": "over_budget",
                "budget": {
                    "included": False,
                    "reason": "relationship omitted by collector-local relevance cap",
                    "priority": 998,
                },
            }
        )

        signals = high_value_missing_signals(
            budget={
                "limit": 500,
                "required_tokens": 520,
                "required_over_limit": True,
                "required_overflow_tokens": 20,
            },
            omitted_items=omitted_items,
        )

        self.assertEqual(len(signals), 8)
        self.assertIn("required_budget_overflow", {item["code"] for item in signals})
        self.assertNotIn("item:false-budget-text", {item["signal"] for item in signals})
        self.assertNotIn("item:collector-cap", {item["signal"] for item in signals})
        self.assertEqual(
            [item["priority"] for item in signals],
            sorted((item["priority"] for item in signals), reverse=True),
        )

    def test_quality_diagnostics_cover_structural_context_gaps_without_taste_scoring(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "create table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        state = SimpleNamespace(
            conn=conn,
            entity_hits=[
                SimpleNamespace(
                    id="char:missing-context",
                    type="character",
                    summary="",
                )
            ],
            world_settings=[
                {
                    "row": {
                        "entity_id": "world:missing-summary",
                        "entity_summary": "",
                    }
                }
            ],
            relationships=[
                {
                    "record": SimpleNamespace(
                        id="rel:missing-endpoint",
                        summary="",
                        endpoint_issues=("target_id: missing entity char:absent",),
                    )
                },
                {
                    "record": SimpleNamespace(
                        id="rel:missing-endpoint",
                        summary="",
                        endpoint_issues=("target_id: missing entity char:absent",),
                    )
                },
            ],
            relationship_omissions=[],
            progress_context=[
                {
                    "record": SimpleNamespace(
                        id="clock:missing-metadata",
                        summary="",
                        scope=None,
                        kind="countdown",
                        clock_type="",
                        segments_total=0,
                        segments_filled=1,
                        tick_rules={},
                        trigger_when_full="",
                    )
                }
            ],
            progress_omissions=[],
        )
        omitted_items = [
            {
                "id": "memory:stale-context",
                "kind": "memory",
                "source": "memory_summaries",
                "reason": "subject_updated_after_summary",
                "freshness": {
                    "status": "stale",
                    "reason": "subject_updated_after_summary",
                },
            }
        ]
        budget = {
            "limit": 500,
            "decisions": [
                {
                    "section": "oversized_context",
                    "required": False,
                    "priority": 90,
                    "estimated_tokens": 900,
                    "included": False,
                    "reason": "token budget",
                    "reason_code": "over_budget",
                },
                {
                    "section": "low_value_context",
                    "required": False,
                    "priority": 20,
                    "estimated_tokens": 10,
                    "included": True,
                    "reason": "selected by priority within token budget",
                    "reason_code": "selected",
                },
            ],
        }

        diagnostics = build_quality_diagnostics(
            state=state,
            budget=budget,
            loaded_items=[],
            omitted_items=omitted_items,
            context_view="maintenance",
        )

        codes = {item["code"] for item in diagnostics}
        self.assertTrue(
            {
                "missing_summary",
                "missing_aliases",
                "missing_endpoint_reference",
                "missing_progress_metadata",
                "stale_summary_evidence",
                "oversized_context_section",
                "low_value_budget_tradeoff",
            }.issubset(codes),
            diagnostics,
        )
        expected_fields = {
            "code",
            "severity",
            "source",
            "subject_kind",
            "subject_id",
            "missing_fields",
            "reason",
            "visibility",
            "provenance",
            "advisory_only",
        }
        self.assertTrue(all(set(item) == expected_fields for item in diagnostics))
        self.assertTrue(all(item["advisory_only"] is True for item in diagnostics))
        self.assertEqual(
            diagnostics,
            sorted(
                diagnostics,
                key=lambda item: (
                    item["severity"],
                    item["code"],
                    item["source"],
                    item["subject_id"],
                    tuple(item["missing_fields"]),
                ),
            ),
        )
        dedupe_keys = [
            (
                item["code"],
                item["source"],
                item["subject_kind"],
                item["subject_id"],
                tuple(item["missing_fields"]),
            )
            for item in diagnostics
        ]
        self.assertEqual(len(dedupe_keys), len(set(dedupe_keys)))
        serialized = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("prose", serialized.lower())
        self.assertNotIn("taste", serialized.lower())
        self.assertNotIn("quality_score", serialized.lower())
        progress_warning = next(
            item
            for item in diagnostics
            if item["code"] == "missing_progress_metadata"
            and item["subject_id"] == "clock:missing-metadata"
        )
        self.assertNotIn("clock_type", progress_warning["missing_fields"])
        self.assertNotIn("clock_type_or_kind", progress_warning["missing_fields"])

    def test_quality_diagnostics_use_final_loaded_memory_evidence(self) -> None:
        state = SimpleNamespace(
            conn=None,
            entity_hits=[],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )
        loaded_items = [
            {
                "id": "memory:loaded-stale",
                "kind": "memory",
                "source": "memory_summaries",
                "freshness": {"status": "stale"},
            },
            {
                "id": "memory:loaded-missing-freshness",
                "kind": "memory",
                "source": "memory_summaries",
            },
            {
                "id": "memory:loaded-unverifiable",
                "kind": "memory",
                "source": "memory_summaries",
                "freshness": {"status": "unverifiable"},
            },
            {
                "id": "section:memory_summaries",
                "kind": "section",
                "source": "memory_summaries",
            },
        ]

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=loaded_items,
            omitted_items=[],
            context_view="maintenance",
        )

        self.assertTrue(
            any(
                item["code"] == "stale_summary_evidence"
                and item["subject_id"] == "memory:loaded-stale"
                for item in diagnostics
            ),
            diagnostics,
        )
        stale_subjects = {
            item["subject_id"]
            for item in diagnostics
            if item["code"] == "stale_summary_evidence"
        }
        self.assertNotIn("section:memory_summaries", stale_subjects)
        self.assertTrue(
            {
                "memory:loaded-stale",
                "memory:loaded-missing-freshness",
                "memory:loaded-unverifiable",
            }.issubset(stale_subjects),
            diagnostics,
        )

    def test_quality_diagnostics_isolate_source_failures(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "create table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        state = SimpleNamespace(
            conn=conn,
            entity_hits=[
                SimpleNamespace(
                    id="char:valid-warning",
                    type="character",
                    summary="",
                )
            ],
            semantic_alias_gaps=[],
            world_settings=[],
            relationships=[
                {
                    "record": SimpleNamespace(
                        id="rel:corrupt-issues",
                        summary="summary",
                        endpoint_issues=1,
                    )
                }
            ],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="maintenance",
        )

        self.assertTrue(
            any(
                item["code"] == "missing_summary"
                and item["subject_id"] == "char:valid-warning"
                for item in diagnostics
            ),
            diagnostics,
        )
        self.assertTrue(
            any(
                item["code"] == "quality_diagnostics_unavailable"
                and item["source"] == "relationships"
                for item in diagnostics
            ),
            diagnostics,
        )

    def test_quality_diagnostics_preserve_source_failure_with_thirty_two_item_cap(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "create table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        hits = [
            SimpleNamespace(
                id=f"char:missing-summary-{index:02d}",
                type="character",
                summary="",
            )
            for index in range(40)
        ]
        conn.executemany(
            "insert into aliases(alias, entity_id) values (?, ?)",
            [(f"Alias {index}", hit.id) for index, hit in enumerate(hits)],
        )
        state = SimpleNamespace(
            conn=conn,
            entity_hits=hits,
            semantic_alias_gaps=[],
            world_settings=[],
            relationships=[
                {
                    "record": SimpleNamespace(
                        id="rel:corrupt-capped",
                        summary="summary",
                        endpoint_issues=1,
                    )
                }
            ],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="maintenance",
        )

        self.assertEqual(len(diagnostics), 32)
        unavailable = next(
            item
            for item in diagnostics
            if item["code"] == "quality_diagnostics_unavailable"
            and item["source"] == "relationships"
        )
        self.assertEqual(unavailable["severity"], "error")
        self.assertTrue(
            any(
                item["code"] == "quality_diagnostics_unavailable"
                and item["source"] == "relationships"
                for item in diagnostics
            ),
            diagnostics,
        )

    def test_quality_diagnostics_report_conflict_progress_omission(self) -> None:
        state = SimpleNamespace(
            conn=None,
            entity_hits=[],
            semantic_alias_gaps=[],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[
                {
                    "id": "clock:invalid-segments",
                    "reason_code": "conflict",
                }
            ],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="maintenance",
        )

        warning = next(
            item
            for item in diagnostics
            if item["code"] == "missing_progress_metadata"
            and item["subject_id"] == "clock:invalid-segments"
        )
        self.assertEqual(warning["missing_fields"], ["segments_or_status"])

    def test_scope_only_tick_rules_do_not_count_as_tick_metadata(self) -> None:
        state = SimpleNamespace(
            conn=None,
            entity_hits=[],
            semantic_alias_gaps=[],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[
                {
                    "record": SimpleNamespace(
                        id="clock:scope-only-rules",
                        summary="summary",
                        scope=["loc:known"],
                        kind="project",
                        clock_type="project",
                        segments_total=4,
                        segments_filled=1,
                        tick_rules={"scope": ["loc:known"]},
                        trigger_when_full="",
                    )
                }
            ],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="maintenance",
        )

        warning = next(
            item
            for item in diagnostics
            if item["code"] == "missing_progress_metadata"
            and item["subject_id"] == "clock:scope-only-rules"
        )
        self.assertIn("tick_rules_or_trigger_when_full", warning["missing_fields"])

    def test_quality_diagnostics_emit_generic_semantic_alias_gap(self) -> None:
        state = SimpleNamespace(
            conn=None,
            entity_hits=[],
            semantic_alias_gaps=[
                {
                    "label": "PRIVATE_UNRESOLVED_LABEL",
                    "status": "unresolved",
                    "candidates": [],
                }
            ],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="player",
        )

        warning = next(
            item
            for item in diagnostics
            if item["code"] == "missing_aliases"
            and item["source"] == "semantic_resolution"
        )
        self.assertEqual(warning["subject_id"], "semantic_alias_gap")
        self.assertNotIn("PRIVATE_UNRESOLVED_LABEL", json.dumps(warning, sort_keys=True))

    def test_blank_alias_does_not_count_as_lookup_alias(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "create table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        conn.execute(
            "insert into aliases(alias, entity_id) values ('   ', 'char:blank-alias')"
        )
        state = SimpleNamespace(
            conn=conn,
            entity_hits=[
                SimpleNamespace(
                    id="char:blank-alias",
                    type="character",
                    summary="summary",
                )
            ],
            semantic_alias_gaps=[],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="player",
        )

        self.assertTrue(
            any(
                item["code"] == "missing_aliases"
                and item["subject_id"] == "char:blank-alias"
                for item in diagnostics
            ),
            diagnostics,
        )

    def test_alias_diagnostics_batch_read_canonical_main_table(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "create table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        conn.executemany(
            "insert into main.aliases(alias, entity_id) values (?, ?)",
            [(f"Alias {index}", f"char:alias-{index}") for index in range(3)],
        )
        conn.execute(
            "create temp table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        self.addCleanup(conn.set_trace_callback, None)
        state = SimpleNamespace(
            conn=conn,
            entity_hits=[
                SimpleNamespace(
                    id=f"char:alias-{index}",
                    type="character",
                    summary="summary",
                )
                for index in range(3)
            ],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="player",
        )

        self.assertFalse(
            any(item["code"] == "missing_aliases" for item in diagnostics),
            diagnostics,
        )
        alias_queries = [
            statement
            for statement in statements
            if "from main.aliases" in statement.lower()
        ]
        self.assertEqual(len(alias_queries), 1, statements)

    def test_quality_diagnostics_are_bounded_to_thirty_two_items(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        conn.execute(
            "create table aliases(alias text not null, entity_id text not null, kind text not null default 'name')"
        )
        state = SimpleNamespace(
            conn=conn,
            entity_hits=[
                SimpleNamespace(
                    id=f"char:missing-{index:02d}",
                    type="character",
                    summary="",
                )
                for index in range(40)
            ],
            world_settings=[],
            relationships=[],
            relationship_omissions=[],
            progress_context=[],
            progress_omissions=[],
        )

        diagnostics = build_quality_diagnostics(
            state=state,
            budget={"limit": 500, "decisions": []},
            loaded_items=[],
            omitted_items=[],
            context_view="player",
        )

        self.assertEqual(len(diagnostics), 32)

    def test_default_context_collectors_are_registered_in_stable_order(self) -> None:
        self.assertEqual(
            [collector.name for collector in DEFAULT_CONTEXT_COLLECTORS],
            [
                "active_clocks",
                "relationships",
                "progress_context",
                "routes",
                "palettes",
                "discovery_states",
                "world_settings",
                "world_settings_core",
                "recent_events",
                "memory_summaries",
                "plot_signals",
            ],
        )

    def test_default_context_collectors_declare_contract_metadata(self) -> None:
        default = ContextCollector(name="placeholder")
        self.assertEqual(default.source, "")
        self.assertEqual(default.visibility, "")
        self.assertEqual(default.provenance, "")
        self.assertEqual(default.budget_behavior, "")
        for collector in DEFAULT_CONTEXT_COLLECTORS:
            with self.subTest(collector=collector.name):
                self.assertTrue(collector.source)
                self.assertTrue(collector.visibility)
                self.assertTrue(collector.provenance)
                self.assertTrue(collector.budget_behavior)

    def test_context_collector_positional_callbacks_remain_compatible(self) -> None:
        def collect(state: Any) -> None:
            state.collected = True

        def section(state: Any) -> ContextSection | None:
            return ContextSection(key="legacy", title="Legacy", content="legacy", priority=1)

        def loaded_items(state: Any) -> list[dict[str, Any]]:
            return [{"id": "legacy:item", "kind": "legacy", "reason": "legacy", "priority": 1}]

        def omitted_items(state: Any) -> list[dict[str, Any]]:
            return [{"id": "legacy:omitted", "kind": "legacy", "reason": "legacy omitted", "priority": 0}]

        collector = ContextCollector("legacy", collect, section, loaded_items)
        collector_with_omissions = ContextCollector("legacy2", collect, section, loaded_items, omitted_items=omitted_items)
        collector_with_source = ContextCollector("legacy3", collect, section, loaded_items, "legacy-source")

        self.assertIs(collector.collect, collect)
        self.assertIs(collector.section, section)
        self.assertIs(collector.loaded_items, loaded_items)
        self.assertIs(collector_with_omissions.omitted_items, omitted_items)
        self.assertEqual(collector_with_source.source, "legacy-source")
        self.assertIsNone(collector_with_source.omitted_items)
        self.assertEqual(collector.source, "")
        self.assertEqual(collector.visibility, "")
        self.assertEqual(collector.provenance, "")
        self.assertEqual(collector.budget_behavior, "")

    def test_enrich_collector_item_merges_partial_budget_evidence(self) -> None:
        collector = ContextCollector(
            name="plot_signals",
            source="plot_signals",
            budget_behavior="optional advisory signal section",
        )
        item = {
            "id": "plot:test",
            "kind": "plot_signal",
            "priority": 42,
            "budget": {"included": False, "reason": "source section omitted by token budget"},
        }

        enriched = enrich_collector_item(SimpleNamespace(mode="query"), collector, item, included=False)

        self.assertEqual(enriched["budget"]["included"], False)
        self.assertEqual(enriched["budget"]["reason"], "source section omitted by token budget")
        self.assertEqual(enriched["budget"]["behavior"], "optional advisory signal section")
        self.assertEqual(enriched["budget"]["priority"], 42)
        self.assertIn("estimated_tokens", enriched["budget"])

    def test_campaign_hint_fallback_identity_does_not_use_body_text(self) -> None:
        hints: list[dict[str, str]] = []
        collect_plot_hints_from_value(hints, ["VISIBLE_SCALAR_HINT_BODY"], "hint", "campaign.yaml")
        collect_plot_hints_from_value(
            hints,
            [{"text": "VISIBLE_DICT_HINT_BODY", "visibility": "known"}],
            "hint",
            "campaign.yaml",
        )
        collect_plot_hints_from_value(
            hints,
            {"id": "hidden-single", "text": "SECRET_SINGLE_HINT_BODY", "visibility": "hidden"},
            "hint",
            "campaign.yaml",
        )

        self.assertEqual(
            [hint["text"] for hint in hints],
            ["VISIBLE_SCALAR_HINT_BODY", "VISIBLE_DICT_HINT_BODY", "SECRET_SINGLE_HINT_BODY"],
        )
        self.assertEqual(hints[-1]["id"], "hidden-single")
        self.assertEqual(hints[-1]["visibility"], "hidden")
        for hint in hints[:2]:
            omitted = plot_signal_omission_item(
                {"id": f"plot:campaign:hint:{hint['id']}", "name": hint["name"]},
                reason_code="over_budget",
            )
            serialized_identity = f"{omitted['id']} {omitted['name']}"
            self.assertNotIn("VISIBLE_SCALAR_HINT_BODY", serialized_identity)
            self.assertNotIn("VISIBLE_DICT_HINT_BODY", serialized_identity)
            self.assertNotIn("SECRET_SINGLE_HINT_BODY", serialized_identity)

    def test_progress_active_check_normalizes_status_label(self) -> None:
        progress = SimpleNamespace(status="Active", segments_filled=1, segments_total=4)

        self.assertTrue(progress_is_active(progress))

    def test_world_settings_core_satisfies_world_setting_plot_signal_source(self) -> None:
        item = {
            "source": "plot_signals",
            "kind": "plot_signal",
            "required_section_keys": ["world_settings"],
        }

        self.assertFalse(collector_item_omitted_by_budget(item, {"plot_signals", "world_settings_core"}))
        self.assertTrue(collector_item_omitted_by_budget(item, {"plot_signals"}))

    def test_section_evidence_uses_stable_section_identity_and_alias_metadata(self) -> None:
        palette = ContextSection(key="palette_candidates", title="Palette", content="x", priority=82)
        metadata = section_source_metadata(palette)
        self.assertEqual(metadata["source"], "palettes")
        self.assertEqual(metadata["provenance"]["collector"], "palettes")

        route_section = ContextSection(key="routes", title="Routes", content="x", priority=72)
        evidence = section_item_evidence(route_section, "player", included=True)
        self.assertEqual(evidence["id"], "section:routes")
        self.assertEqual(evidence["source"], "routes")

    def test_context_pipeline_runs_steps_in_order_and_writes_audit_id(self) -> None:
        calls: list[str] = []

        class Result:
            def __init__(self) -> None:
                self.request: dict[str, Any] = {}

        pipeline = ContextPipeline(
            steps=[
                ContextPipelineStep("first", lambda state: calls.append("first")),
                ContextPipelineStep("second", lambda state: calls.append("second")),
            ],
            render_result=lambda state: Result(),
            audit_result=lambda state, result, run_id: f"context:{run_id}",
        )

        result = pipeline.run(object(), audit_context=True, audit_context_run_id="unit-test")
        self.assertEqual(calls, ["first", "second"])
        self.assertEqual(result.request["context_audit_run_id"], "context:unit-test")

    def test_default_context_pipeline_has_stable_step_order(self) -> None:
        self.assertEqual(
            [step.name for step in default_context_pipeline().steps],
            [
                "classify_request",
                "collect_entity_hits",
                "collect_semantic_suggestion",
                "apply_semantic_request_decision",
                "expand_related_entities",
                "run_context_collectors",
                "validate_context",
            ],
        )

    def test_token_estimate_and_dedupe_are_stable(self) -> None:
        self.assertLess(estimate_tokens("短文本"), estimate_tokens("短文本" * 50))
        self.assertEqual(dedupe_texts(["终极复合弩", "终极复合弩", "", "火药箭"]), ["终极复合弩", "火药箭"])


if __name__ == "__main__":
    unittest.main()
