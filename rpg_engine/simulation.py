from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .campaign import load_campaign
from .context_builder import build_context
from .db import connect
from .projection_service import ProjectionService
from .save import save_turn_delta
from .validators import run_checks


DEFAULT_SIM_TEXTS = [
    "look around",
    "inspect the current location",
    "travel to a known nearby place",
    "gather a visible resource",
    "talk to a visible character",
    "rest until morning",
]


@dataclass(frozen=True)
class SimulationResult:
    turns: int
    report: str
    temp_dir: str


def run_long_simulation(source_campaign_dir: Path, *, turns: int = 30, budget: int = 3000) -> SimulationResult:
    temp = tempfile.TemporaryDirectory()
    source = Path(source_campaign_dir).resolve()
    target = Path(temp.name) / "campaign"
    shutil.copytree(source, target)
    campaign = load_campaign(target)
    timings: list[float] = []
    estimates: list[int] = []
    section_counts: dict[str, int] = {}
    max_loaded = 0
    sample_texts = campaign.sample_texts or DEFAULT_SIM_TEXTS
    with connect(campaign) as conn:
        for index in range(max(0, turns)):
            text = sample_texts[index % len(sample_texts)]
            start = time.perf_counter()
            packet = build_context(campaign, conn, user_text=text, mode="auto", budget=budget, output_format="json")
            timings.append(time.perf_counter() - start)
            data = json.loads(packet.to_json_text())
            estimates.append(int(data["budget"]["estimated"]))
            for key in data["sections"]:
                section_counts[key] = section_counts.get(key, 0) + 1
            max_loaded = max(max_loaded, len(data["loaded_items"]))
            if data["request"]["mode"] == "action" and data["completeness"]["allow_proceed"]:
                save_turn_delta(campaign, conn, synthetic_turn_delta(index, text, data))
            if (index + 1) % 10 == 0:
                ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=False,
                    profile="simulation:maintenance_projection",
                    commit_policy="caller_committed_required",
                )
        errors = run_checks(conn)
        memory_count = scalar(conn, "select count(*) from memory_summaries")
        event_count = scalar(conn, "select count(*) from events")
    report = render_simulation_report(
        turns=turns,
        timings=timings,
        estimates=estimates,
        section_counts=section_counts,
        max_loaded=max_loaded,
        memory_count=memory_count,
        event_count=event_count,
        errors=errors,
        temp_dir=temp.name,
    )
    temp.cleanup()
    return SimulationResult(turns=turns, report=report, temp_dir=temp.name)


def synthetic_turn_delta(index: int, text: str, context_data: dict) -> dict:
    return {
        "user_text": f"长跑模拟：{text}",
        "intent": "longrun_simulation",
        "changed": True,
        "summary": f"长跑模拟第{index + 1}轮：验证上下文、保存和长期记忆压力。",
        "events": [
            {
                "type": "longrun_simulation",
                "title": f"长跑模拟第{index + 1}轮",
                "summary": f"模拟输入：{text}；mode={context_data['request']['mode']}:{context_data['request']['submode']}。",
                "payload": {
                    "index": index + 1,
                    "user_text": text,
                    "estimated_tokens": context_data["budget"]["estimated"],
                    "sections": sorted(context_data["sections"].keys()),
                },
                "source": "longrun_simulation",
            }
        ],
    }


def render_simulation_report(
    *,
    turns: int,
    timings: list[float],
    estimates: list[int],
    section_counts: dict[str, int],
    max_loaded: int,
    memory_count: int,
    event_count: int,
    errors: list[str],
    temp_dir: str,
) -> str:
    avg_time = sum(timings) / len(timings) if timings else 0.0
    max_time = max(timings) if timings else 0.0
    avg_tokens = sum(estimates) / len(estimates) if estimates else 0.0
    max_tokens = max(estimates) if estimates else 0
    lines = [
        "# Long Run Simulation Report",
        "",
        "| 指标 | 值 |",
        "|------|----|",
        f"| turns | {turns} |",
        f"| avg_seconds | {avg_time:.4f} |",
        f"| max_seconds | {max_time:.4f} |",
        f"| avg_estimated_tokens | {avg_tokens:.1f} |",
        f"| max_estimated_tokens | {max_tokens} |",
        f"| max_loaded_items | {max_loaded} |",
        f"| memory_summaries | {memory_count} |",
        f"| events | {event_count} |",
        f"| check_errors | {len(errors)} |",
        f"| temp_dir | {temp_dir} |",
        "",
        "## Section Frequency",
        "",
        "| Section | Count |",
        "|---------|-------|",
    ]
    for key, count in sorted(section_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {key} | {count} |")
    if errors:
        lines.extend(["", "## Check Errors"])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines).rstrip() + "\n"


def write_simulation_report(source_campaign_dir: Path, output: Path | None, *, turns: int, budget: int) -> Path:
    source = Path(source_campaign_dir).resolve()
    result = run_long_simulation(source, turns=turns, budget=budget)
    path = output or source / "reports" / "longrun-simulation-current.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.report, encoding="utf-8")
    return path


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0
