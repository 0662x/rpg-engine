from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib import resources
from pathlib import Path

from rpg_engine.eval_suite import EvalCaseResult, EvalRunResult, EvalSuiteResult, render_eval_report, run_eval_suite


ENGINE_ROOT = Path(__file__).resolve().parents[1]


class EvalSuiteTests(unittest.TestCase):
    def test_packaged_eval_resources_are_available(self) -> None:
        evals = resources.files("rpg_engine.resources").joinpath("evals")

        self.assertTrue(evals.joinpath("intent_router_gold_set.yaml").is_file())
        self.assertTrue(evals.joinpath("intent_consensus_gold_set.yaml").is_file())
        self.assertTrue(evals.joinpath("intent_consensus_commit_paths.yaml").is_file())
        self.assertTrue(evals.joinpath("intent_real_canary.yaml").is_file())
        self.assertTrue(evals.joinpath("intent_clarification_loops.yaml").is_file())
        self.assertTrue(evals.joinpath("mcp_external_agent_transcripts.yaml").is_file())

    def test_eval_suite_runs_intent_and_mcp_metrics(self) -> None:
        result = run_eval_suite(suite="all")
        data = result.to_dict()

        self.assertTrue(result.ok, data)
        self.assertEqual(
            [suite.suite for suite in result.suites],
            ["intent", "intent-consensus", "intent-consensus-commit", "intent-clarification-loop", "mcp"],
        )
        self.assertGreater(data["metrics"]["total"], 0)
        self.assertEqual(data["metrics"]["accuracy"], 1.0)
        self.assertIn("block_rate", result.suites[0].metrics)
        self.assertIn("selected_outcome_sources", result.suites[1].metrics)
        self.assertIn("clarification_reasons", result.suites[1].metrics)
        self.assertIn("commit_ok_rate", result.suites[2].metrics)
        self.assertIn("closed_rate", result.suites[3].metrics)
        self.assertIn("final_selected_outcome_sources", result.suites[3].metrics)
        self.assertIn("tool_misuse_rate", result.suites[4].metrics)
        self.assertIn("# Eval Report", render_eval_report(result))
        first_intent_case = result.suites[0].cases[0].metrics
        self.assertIn("legacy_rule_route", first_intent_case)
        self.assertIn("rules_outcome", first_intent_case)
        self.assertIn("selected_outcome", first_intent_case)
        self.assertIn("selected_outcome_sources", result.suites[0].metrics)

    def test_intent_eval_supports_fake_consensus_selected_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_hermes = Path(tmp) / "hermes"
            fake_hermes.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' '{\"kind\":\"single\",\"mode\":\"action\",\"action\":\"rest\",\"slots\":{\"until\":\"morning\"},\"plan\":[],\"confidence\":\"high\",\"missing_slots\":[],\"needs_confirmation\":[],\"safety_flags\":[],\"reason\":\"玩家要休息到早上\",\"agreement_with_external\":\"agree\",\"disagreements\":[],\"external_candidate_quality\":\"usable\"}'\n",
                encoding="utf-8",
            )
            fake_hermes.chmod(0o755)
            gold_path = Path(tmp) / "fake-consensus.yaml"
            gold_path.write_text(
                """
cases:
  - id: fake_consensus_rest
    text: 休息到早上
    runtime:
      intent_ai: consensus
      intent_backend: hermes_z
      external_intent_candidate:
        kind: single
        mode: action
        action: rest
        slots:
          until: morning
        plan: []
        confidence: high
        missing_slots: []
        needs_confirmation: []
        safety_flags: []
        reason: 外部 AI 判断这是休息行动。
    start:
      mode: action
      submode: rest
      requires_preview: true
      can_proceed: true
      intent_kind: single
      intent_action: rest
      intent_status: ready
    preview:
      action: rest
      status: ready
      ready_to_save: true
      recommended_next_tool: validate_delta
      plan: []
      selected_outcome:
        source: ai_consensus
        mode: action
        submode: rest
        action: rest
      consensus_outcome:
        source: ai_consensus
        action: rest
""".lstrip(),
                encoding="utf-8",
            )
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
            try:
                result = run_eval_suite(suite="intent", intent_gold_path=gold_path)
            finally:
                os.environ["PATH"] = old_path

        data = result.to_dict()
        self.assertTrue(result.ok, data)
        case = result.suites[0].cases[0]
        self.assertEqual(case.metrics["selected_outcome"]["source"], "ai_consensus")
        self.assertEqual(case.metrics["consensus_outcome"]["action"], "rest")
        self.assertEqual(result.suites[0].metrics["selected_outcome_sources"], {"ai_consensus": 1})
        self.assertEqual(result.suites[0].metrics["clarification_reasons"], {"none": 1})

    def test_intent_eval_supports_direct_fake_response_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_path = Path(tmp) / "direct-fake-consensus.yaml"
            gold_path.write_text(
                """
cases:
  - id: direct_fake_consensus_rest
    text: 休息到早上
    runtime:
      intent_ai: consensus
      intent_backend: direct
      external_intent_candidate:
        kind: single
        mode: action
        action: rest
        slots:
          until: morning
        plan: []
        confidence: high
        missing_slots: []
        needs_confirmation: []
        safety_flags: []
        reason: 外部 AI 判断这是休息行动。
    start:
      mode: action
      submode: rest
      requires_preview: true
      can_proceed: true
      intent_kind: single
      intent_action: rest
      intent_status: ready
    preview:
      action: rest
      status: ready
      ready_to_save: true
      recommended_next_tool: validate_delta
      plan: []
      selected_outcome:
        source: ai_consensus
        mode: action
        submode: rest
        action: rest
      consensus_outcome:
        source: ai_consensus
        action: rest
""".lstrip(),
                encoding="utf-8",
            )
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "rest",
                    "slots": {"until": "morning"},
                    "plan": [],
                    "confidence": "high",
                    "missing_slots": [],
                    "needs_confirmation": [],
                    "safety_flags": [],
                    "reason": "direct fake internal review agrees.",
                    "agreement_with_external": "agree",
                    "disagreements": [],
                    "external_candidate_quality": "usable",
                },
                ensure_ascii=False,
            )
            try:
                result = run_eval_suite(suite="intent", intent_gold_path=gold_path)
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

        data = result.to_dict()
        self.assertTrue(result.ok, data)
        self.assertEqual(result.suites[0].cases[0].metrics["selected_outcome"]["source"], "ai_consensus")

    def test_eval_cli_outputs_json_report(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "rpg_engine", "eval", "run", "--format", "json"],
            cwd=ENGINE_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(completed.stdout)

        self.assertTrue(data["ok"], data)
        self.assertEqual(data["metrics"]["accuracy"], 1.0)
        self.assertEqual(
            [suite["suite"] for suite in data["suites"]],
            ["intent", "intent-consensus", "intent-consensus-commit", "intent-clarification-loop", "mcp"],
        )

    def test_eval_cli_can_run_intent_consensus_commit_suite(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "rpg_engine", "eval", "run", "--suite", "intent-consensus-commit", "--format", "json"],
            cwd=ENGINE_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(completed.stdout)

        self.assertTrue(data["ok"], data)
        self.assertEqual([suite["suite"] for suite in data["suites"]], ["intent-consensus-commit"])
        self.assertEqual(data["suites"][0]["metrics"]["commit_ok_rate"], 0.6667)

    def test_eval_cli_can_run_real_canary_as_non_gating_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_hermes = Path(tmp) / "hermes"
            fake_hermes.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' '{\"kind\":\"single\",\"mode\":\"action\",\"action\":\"rest\",\"slots\":{\"until\":\"morning\"},\"plan\":[],\"confidence\":\"high\",\"missing_slots\":[],\"needs_confirmation\":[],\"safety_flags\":[],\"reason\":\"canary fake\",\"agreement_with_external\":\"agree\",\"disagreements\":[],\"external_candidate_quality\":\"usable\"}'\n",
                encoding="utf-8",
            )
            fake_hermes.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
            try:
                completed = subprocess.run(
                    [sys.executable, "-m", "rpg_engine", "eval", "run", "--suite", "intent-real-canary", "--format", "json"],
                    cwd=ENGINE_ROOT,
                    text=True,
                    capture_output=True,
                    check=True,
                )
            finally:
                os.environ["PATH"] = old_path
        data = json.loads(completed.stdout)

        self.assertTrue(data["ok"], data)
        self.assertEqual([suite["suite"] for suite in data["suites"]], ["intent-real-canary"])
        self.assertEqual(data["suites"][0]["metrics"]["canary_ok_rate"], 1.0)
        self.assertIn("expectation_met_rate", data["suites"][0]["metrics"])
        self.assertEqual(data["suites"][0]["metrics"]["timeout_budget_ms"], 8000)
        self.assertIn("over_budget_rate", data["suites"][0]["metrics"])
        self.assertIn("latency_p50_ms", data["suites"][0]["metrics"])
        self.assertIn("latency_p95_ms", data["suites"][0]["metrics"])
        self.assertIn("selected_outcome_sources", data["suites"][0]["metrics"])

    def test_eval_cli_can_run_intent_consensus_suite(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "rpg_engine", "eval", "run", "--suite", "intent-consensus", "--format", "json"],
            cwd=ENGINE_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(completed.stdout)

        self.assertTrue(data["ok"], data)
        self.assertEqual([suite["suite"] for suite in data["suites"]], ["intent-consensus"])
        self.assertIn("ai_consensus", data["suites"][0]["metrics"]["selected_outcome_sources"])

    def test_eval_cli_can_run_intent_clarification_loop_suite(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "rpg_engine",
                "eval",
                "run",
                "--suite",
                "intent-clarification-loop",
                "--format",
                "json",
            ],
            cwd=ENGINE_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        data = json.loads(completed.stdout)

        self.assertTrue(data["ok"], data)
        self.assertEqual([suite["suite"] for suite in data["suites"]], ["intent-clarification-loop"])
        self.assertEqual(data["suites"][0]["metrics"]["intent_resolved_rate"], 1.0)
        self.assertEqual(data["suites"][0]["metrics"]["closed_rate"], 0.8)
        self.assertEqual(data["suites"][0]["metrics"]["final_selected_outcome_sources"], {"ai_consensus": 5})

    def test_eval_report_failed_cases_include_outcome_and_clarification(self) -> None:
        result = EvalRunResult(
            ok=False,
            suites=(
                EvalSuiteResult(
                    suite="intent-consensus",
                    ok=False,
                    metrics={"total": 1, "passed": 0, "failed": 1, "accuracy": 0.0},
                    cases=(
                        EvalCaseResult(
                            id="bad_case",
                            ok=False,
                            errors=("preview.status: expected 'ready', got 'needs_confirmation'",),
                            metrics={
                                "selected_outcome": {
                                    "source": "ai_disagreement",
                                    "mode": "action",
                                    "submode": "travel",
                                    "action": None,
                                    "status": "needs_confirmation",
                                },
                                "clarification": {
                                    "reason": "external_internal_slot_mismatch",
                                    "choice_count": 2,
                                    "missing_slots": [],
                                },
                            },
                        ),
                    ),
                ),
            ),
        )

        report = render_eval_report(result)

        self.assertIn("| Case | Selected Outcome | Clarification | Errors |", report)
        self.assertIn("source=ai_disagreement", report)
        self.assertIn("reason=external_internal_slot_mismatch", report)

    def test_eval_report_warns_on_non_gating_canary_expectation_miss(self) -> None:
        result = EvalRunResult(
            ok=True,
            suites=(
                EvalSuiteResult(
                    suite="intent-real-canary",
                    ok=True,
                    metrics={
                        "total": 1,
                        "passed": 1,
                        "failed": 0,
                        "accuracy": 1.0,
                        "expectation_miss_count": 1,
                    },
                    cases=(
                        EvalCaseResult(
                            id="canary_miss",
                            ok=True,
                            errors=(),
                            metrics={
                                "expectation_met": False,
                                "expectation_errors": ["selected_source mismatch"],
                                "selected_outcome": {"source": "rules_fallback"},
                            },
                        ),
                    ),
                ),
            ),
        )

        report = render_eval_report(result)

        self.assertIn("non-gating canary expectation miss", report)
        self.assertIn("selected_source mismatch", report)

    def test_eval_report_includes_clarification_reason_distribution(self) -> None:
        result = EvalRunResult(
            ok=True,
            suites=(
                EvalSuiteResult(
                    suite="intent-consensus",
                    ok=True,
                    metrics={
                        "total": 2,
                        "passed": 2,
                        "failed": 0,
                        "accuracy": 1.0,
                        "clarification_reasons": {"none": 1, "missing_slots": 1},
                    },
                    cases=(),
                ),
            ),
        )

        report = render_eval_report(result)

        self.assertIn("clarification_reasons", report)
        self.assertIn("missing_slots", report)


if __name__ == "__main__":
    unittest.main()
