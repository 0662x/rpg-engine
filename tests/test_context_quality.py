from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from rpg_engine.context import DEFAULT_CONTEXT_COLLECTORS, ContextPipeline, ContextPipelineStep
from rpg_engine.context.resolution import dedupe_texts, extract_entity_ids, sanitize_fts_query
from rpg_engine.context.sections import ContextSection, apply_budget, estimate_tokens
from rpg_engine.context.semantic import normalize_semantic_suggestion, parse_semantic_json
from rpg_engine.context_builder import (
    apply_semantic_request_decision,
    default_context_pipeline,
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
                "routes",
                "palettes",
                "discovery_states",
                "world_settings",
                "world_settings_core",
                "recent_events",
                "memory_summaries",
            ],
        )

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
