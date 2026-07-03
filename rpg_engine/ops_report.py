from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .audit import run_audit
from .campaign import Campaign
from .context_builder import build_context
from .db import get_meta


DEFAULT_SAMPLE_TEXTS = [
    "look around",
    "inspect the current location",
    "travel to a known nearby place",
    "gather a visible resource",
    "talk to a visible character",
]


def build_ops_report(campaign: Campaign, conn: sqlite3.Connection, *, run_speed: bool = False) -> str:
    meta = get_meta(conn)
    lines = [
        f"# {campaign.name} 运维报告",
        "",
        "## Current",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| current_turn_id | `{meta.get('current_turn_id', '')}` |",
        f"| current_location_id | `{meta.get('current_location_id', '')}` |",
        f"| current_time_block | {meta.get('current_time_block', '')} |",
        f"| weather | {meta.get('weather_condition', '')}/{meta.get('weather_precipitation', '')} |",
        "",
        "## Counts",
        "",
        "| 项目 | 数量 |",
        "|------|------|",
    ]
    for label, sql in [
        ("entities", "select count(*) from entities where status != 'archived'"),
        ("cards", None),
        ("events", "select count(*) from events"),
        ("turns", "select count(*) from turns"),
        ("routes", "select count(*) from routes"),
        ("clocks", "select count(*) from clocks"),
        ("memory_summaries", table_count_sql(conn, "memory_summaries")),
        ("context_runs", table_count_sql(conn, "context_runs")),
    ]:
        if label == "cards":
            count = len(list(campaign.cards_path.rglob("*.md"))) if campaign.cards_path.exists() else 0
        elif sql:
            count = scalar(conn, sql)
        else:
            count = 0
        lines.append(f"| {label} | {count} |")

    lines.extend(["", "## Entity Types", "", "| 类型 | 数量 |", "|------|------|"])
    for row in conn.execute(
        """
        select type, count(*) as count
        from entities
        where status != 'archived'
        group by type
        order by count desc, type
        """
    ).fetchall():
        lines.append(f"| {row['type']} | {row['count']} |")

    findings = run_audit(conn)
    lines.extend(["", "## Audit", "", f"- findings: {len(findings)}"])
    for severity in ["error", "warn", "info"]:
        count = sum(1 for finding in findings if finding.severity == severity)
        lines.append(f"- {severity}: {count}")
    for finding in findings[:8]:
        lines.append(f"- `{finding.code}` {finding.severity}: {finding.title}")

    lines.extend(["", "## Context Runs"])
    if table_exists(conn, "context_runs"):
        recent = conn.execute(
            """
            select id, created_at, mode, submode, budget_limit, estimated_tokens, allow_proceed
            from context_runs
            order by created_at desc
            limit 5
            """
        ).fetchall()
        if recent:
            lines.extend(["", "| ID | 模式 | 预算 | 允许推进 |", "|----|------|------|----------|"])
            for row in recent:
                lines.append(
                    f"| `{row['id']}` | {row['mode']}:{row['submode']} | "
                    f"{row['estimated_tokens']}/{row['budget_limit']} | {row['allow_proceed']} |"
                )
        else:
            lines.append("")
            lines.append("- 无 context audit 记录。")
    else:
        lines.append("")
        lines.append("- context_runs 表不存在。")

    if run_speed:
        lines.extend(["", "## Speed Sample", "", "| 输入 | 秒 | 估算 token |", "|------|----|------------|"])
        timings = []
        for text in campaign.sample_texts or DEFAULT_SAMPLE_TEXTS:
            start = time.perf_counter()
            packet = build_context(campaign, conn, user_text=text, mode="auto", budget=3000, output_format="json")
            elapsed = time.perf_counter() - start
            data = json.loads(packet.to_json_text())
            timings.append(elapsed)
            lines.append(f"| {text} | {elapsed:.4f} | {data['budget']['estimated']} |")
        if timings:
            lines.append("")
            lines.append(f"- average: {sum(timings) / len(timings):.4f}s")
            lines.append(f"- max: {max(timings):.4f}s")
    return "\n".join(lines).rstrip() + "\n"


def write_ops_report(campaign: Campaign, conn: sqlite3.Connection, path: str | Path | None, *, run_speed: bool) -> Path:
    output = Path(path) if path else campaign.root / "reports" / "ops-current.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_ops_report(campaign, conn, run_speed=run_speed), encoding="utf-8")
    return output


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    return int(row[0]) if row else 0


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone()
    return bool(row)


def table_count_sql(conn: sqlite3.Connection, name: str) -> str | None:
    return f"select count(*) from {name}" if table_exists(conn, name) else None
