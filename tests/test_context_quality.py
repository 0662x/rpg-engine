from __future__ import annotations

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
from rpg_engine.context.resolution import dedupe_texts, extract_entity_ids, sanitize_fts_query
from rpg_engine.context.sections import ContextSection, apply_budget, estimate_tokens
from rpg_engine.context.semantic import normalize_semantic_suggestion, parse_semantic_json
from rpg_engine.context_builder import (
    apply_semantic_request_decision,
    collector_item_omitted_by_budget,
    default_context_pipeline,
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
