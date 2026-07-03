from __future__ import annotations

import argparse
import json
import shutil
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .campaign import load_campaign
from .db import init_database
from .runtime import GMRuntime


DEFAULT_OPERATIONS = (
    "start_turn",
    "preview_from_text",
    "validate_delta",
    "commit_turn",
)


@dataclass(frozen=True)
class LatencyStats:
    samples_ms: tuple[float, ...]
    min_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    mean_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceBaselineReport:
    campaign_id: str
    iterations: int
    operations: dict[str, LatencyStats]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "iterations": self.iterations,
            "operations": {name: stats.to_dict() for name, stats in self.operations.items()},
            "notes": list(self.notes),
        }


def run_runtime_performance_baseline(campaign_source: str | Path, *, iterations: int = 5) -> PerformanceBaselineReport:
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    source = Path(campaign_source)
    samples: dict[str, list[float]] = {operation: [] for operation in DEFAULT_OPERATIONS}
    campaign_id = ""

    for index in range(iterations):
        with tempfile.TemporaryDirectory() as tmp:
            campaign_dir = Path(tmp) / f"campaign-{index}"
            shutil.copytree(source, campaign_dir)
            campaign = load_campaign(campaign_dir)
            init_database(campaign, force=True)
            campaign_id = campaign.campaign_id
            runtime = GMRuntime(campaign)
            delta = {
                "expected_turn_id": "turn:seed",
                "command_id": f"perf-baseline-{index}",
                "user_text": "等待片刻",
                "intent": "wait",
                "changed": False,
                "summary": "No significant change.",
            }

            samples["start_turn"].append(measure_ms(lambda: runtime.start_turn("查看周围")))
            samples["preview_from_text"].append(measure_ms(lambda: runtime.preview_from_text("巡视领地，查看各单位和角色的状态")))
            samples["validate_delta"].append(measure_ms(lambda: runtime.validate_delta(delta)))
            preview = runtime.preview_action("rest", {"until": "morning", "user_text": "等待片刻"})
            samples["commit_turn"].append(
                measure_ms(
                    lambda: runtime.commit_turn(
                        preview.delta_draft or {},
                        turn_proposal=preview.turn_proposal,
                        backup=False,
                    )
                )
            )

    return PerformanceBaselineReport(
        campaign_id=campaign_id,
        iterations=iterations,
        operations={name: latency_stats(values) for name, values in samples.items()},
        notes=(
            "No external AI calls are used.",
            "Each iteration uses a fresh temporary campaign copy so commit_turn does not pollute later samples.",
            "Numbers are local-environment baselines, not universal pass/fail thresholds.",
        ),
    )


def measure_ms(callback: Any) -> float:
    started = time.perf_counter()
    callback()
    return (time.perf_counter() - started) * 1000.0


def latency_stats(samples_ms: list[float]) -> LatencyStats:
    if not samples_ms:
        raise ValueError("samples_ms must not be empty")
    sorted_samples = sorted(samples_ms)
    p95_index = min(len(sorted_samples) - 1, int(round((len(sorted_samples) - 1) * 0.95)))
    return LatencyStats(
        samples_ms=tuple(round(value, 3) for value in samples_ms),
        min_ms=round(min(samples_ms), 3),
        p50_ms=round(statistics.median(samples_ms), 3),
        p95_ms=round(sorted_samples[p95_index], 3),
        max_ms=round(max(samples_ms), 3),
        mean_ms=round(statistics.mean(samples_ms), 3),
    )


def render_performance_baseline_markdown(report: PerformanceBaselineReport) -> str:
    lines = [
        "# Phase 0 Runtime Performance Baseline",
        "",
        f"Campaign: `{report.campaign_id}`",
        f"Iterations: `{report.iterations}`",
        "",
        "| Operation | P50 ms | P95 ms | Mean ms | Min ms | Max ms | Samples ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for name in DEFAULT_OPERATIONS:
        stats = report.operations[name]
        samples = ", ".join(f"{value:.3f}" for value in stats.samples_ms)
        lines.append(
            f"| `{name}` | {stats.p50_ms:.3f} | {stats.p95_ms:.3f} | {stats.mean_ms:.3f} | "
            f"{stats.min_ms:.3f} | {stats.max_ms:.3f} | {samples} |"
        )
    lines.extend(["", "Notes:", ""])
    lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rpg_engine.performance_baseline")
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args(argv)

    report = run_runtime_performance_baseline(args.campaign, iterations=args.iterations)
    if args.format == "json":
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_performance_baseline_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
