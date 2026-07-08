from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .campaign import Campaign
from .db import get_meta
from .time_weather import format_time_brief
from .visibility import ensure_visibility_sql_functions, normalized_text_sql


@dataclass(frozen=True)
class AuditFinding:
    severity: str
    code: str
    title: str
    detail: str


def run_audit(conn: sqlite3.Connection) -> list[AuditFinding]:
    ensure_visibility_sql_functions(conn)
    findings: list[AuditFinding] = []
    findings.extend(audit_duplicate_aliases(conn))
    findings.extend(audit_duplicate_names(conn))
    findings.extend(audit_sparse_entities(conn))
    findings.extend(audit_hidden_clocks(conn))
    return findings


def audit_duplicate_aliases(conn: sqlite3.Connection) -> list[AuditFinding]:
    rows = conn.execute(
        """
        select alias, group_concat(entity_id, ', ') as targets, count(*) as count
        from aliases
        group by alias
        having count(*) > 1
        order by count desc, alias
        """
    ).fetchall()
    return [
        AuditFinding(
            severity="warn",
            code="duplicate_alias",
            title=f"别名有 {row['count']} 个目标：{row['alias']}",
            detail=row["targets"],
        )
        for row in rows
    ]


def audit_duplicate_names(conn: sqlite3.Connection) -> list[AuditFinding]:
    ensure_visibility_sql_functions(conn)
    rows = conn.execute(
        f"""
        select name, group_concat(id, ', ') as targets, count(*) as count
        from entities
        where {normalized_text_sql("status")} = 'active'
        group by name
        having count(*) > 1
        order by count desc, name
        """
    ).fetchall()
    return [
        AuditFinding(
            severity="info",
            code="duplicate_name",
            title=f"活跃实体重名：{row['name']}",
            detail=row["targets"],
        )
        for row in rows
    ]


def audit_sparse_entities(conn: sqlite3.Connection) -> list[AuditFinding]:
    ensure_visibility_sql_functions(conn)
    rows = conn.execute(
        f"""
        select id, type, name
        from entities
        where {normalized_text_sql("status")} = 'active'
          and (summary is null or trim(summary) = '')
        order by type, name
        limit 80
        """
    ).fetchall()
    return [
        AuditFinding(
            severity="info",
            code="missing_summary",
            title=f"缺少摘要：{row['name']}",
            detail=f"{row['id']} ({row['type']})",
        )
        for row in rows
    ]


def audit_hidden_clocks(conn: sqlite3.Connection) -> list[AuditFinding]:
    ensure_visibility_sql_functions(conn)
    rows = conn.execute(
        f"""
        select e.id, e.name, c.segments_filled, c.segments_total, c.trigger_when_full
        from clocks c
        join entities e on e.id = c.entity_id
        where {normalized_text_sql("c.visibility")} = 'hidden'
        order by e.name
        """
    ).fetchall()
    return [
        AuditFinding(
            severity="info",
            code="hidden_clock",
            title=f"隐藏进度钟：{row['name']} {row['segments_filled']}/{row['segments_total']}",
            detail=f"{row['id']} full: {row['trigger_when_full']}",
        )
        for row in rows
    ]


def render_audit_markdown(campaign: Campaign, conn: sqlite3.Connection, findings: list[AuditFinding]) -> str:
    meta = get_meta(conn)
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    lines = [
        f"# {campaign.name} 存档审计报告",
        "",
        "| 字段 | 值 |",
        "|------|----|",
        f"| 当前回合 | {meta.get('current_turn_id', 'unknown')} |",
        f"| 游戏时间 | {format_time_brief(meta)} |",
        f"| findings | {len(findings)} |",
        "",
        "## 统计",
        "| 严重度 | 数量 |",
        "|--------|------|",
    ]
    for severity in sorted(counts):
        lines.append(f"| {severity} | {counts[severity]} |")
    if not findings:
        lines.extend(["", "## 结果", "- 无需要人工处理的发现。"])
        return "\n".join(lines)
    for severity in ["warn", "info"]:
        group = [finding for finding in findings if finding.severity == severity]
        if not group:
            continue
        lines.extend(["", f"## {severity}"])
        for finding in group:
            lines.append(f"- `{finding.code}` {finding.title}: {finding.detail}")
    lines.extend(
        [
            "",
            "## 处理建议",
            "- `duplicate_alias`：常查对象应加更具体别名，例如 `畦6空心菜`、`库存空心菜`。",
            "- `duplicate_name`：同名但不同对象可保留，但要保证 ID 和卡片清楚。",
            "- `missing_summary`：高频实体应补一句摘要，低频实体可暂缓。",
        ]
    )
    return "\n".join(lines)


def write_audit_report(campaign: Campaign, conn: sqlite3.Connection, report_path: str | Path | None) -> Path:
    findings = run_audit(conn)
    path = Path(report_path).expanduser() if report_path else campaign.root / "reports" / "audit-current.md"
    if not path.is_absolute():
        path = campaign.root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_audit_markdown(campaign, conn, findings) + "\n", encoding="utf-8")
    return path
