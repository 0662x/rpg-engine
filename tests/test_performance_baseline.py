from __future__ import annotations

import unittest
from pathlib import Path

from rpg_engine.performance_baseline import (
    DEFAULT_OPERATIONS,
    render_performance_baseline_markdown,
    run_runtime_performance_baseline,
)


ENGINE_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_EXAMPLE = ENGINE_ROOT / "examples" / "v1_minimal_adventure"


class PerformanceBaselineTests(unittest.TestCase):
    def test_runtime_performance_baseline_reports_required_operations(self) -> None:
        report = run_runtime_performance_baseline(OFFICIAL_EXAMPLE, iterations=1)

        self.assertEqual(report.campaign_id, "v1-minimal-adventure")
        self.assertEqual(report.iterations, 1)
        self.assertEqual(tuple(report.operations), DEFAULT_OPERATIONS)
        for operation, stats in report.operations.items():
            with self.subTest(operation=operation):
                self.assertEqual(len(stats.samples_ms), 1)
                self.assertGreaterEqual(stats.min_ms, 0.0)
                self.assertGreaterEqual(stats.p50_ms, 0.0)
                self.assertGreaterEqual(stats.p95_ms, 0.0)

    def test_runtime_performance_baseline_renders_markdown(self) -> None:
        report = run_runtime_performance_baseline(OFFICIAL_EXAMPLE, iterations=1)
        markdown = render_performance_baseline_markdown(report)

        self.assertIn("# Phase 0 Runtime Performance Baseline", markdown)
        self.assertIn("`start_turn`", markdown)
        self.assertIn("`preview_from_text`", markdown)
        self.assertIn("No external AI calls are used.", markdown)


if __name__ == "__main__":
    unittest.main()
