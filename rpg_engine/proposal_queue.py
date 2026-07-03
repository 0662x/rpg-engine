from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .content_validation import validate_content_delta
from .db import utc_now


@dataclass(frozen=True)
class ProposalRecord:
    id: str
    kind: str
    status: str
    risk_level: str
    source_turn_id: str | None
    payload: dict[str, Any]
    validation: dict[str, Any]
    reviewed_by: str | None
    review_reason: str | None
    applied_turn_id: str | None
    rollback_hint: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "risk_level": self.risk_level,
            "source_turn_id": self.source_turn_id,
            "payload": self.payload,
            "validation": self.validation,
            "reviewed_by": self.reviewed_by,
            "review_reason": self.review_reason,
            "applied_turn_id": self.applied_turn_id,
            "rollback_hint": self.rollback_hint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def create_proposal(
    conn: sqlite3.Connection,
    *,
    kind: str,
    payload: dict[str, Any],
    validation: dict[str, Any] | None = None,
    source_turn_id: str | None = None,
    status: str | None = None,
    risk_level: str | None = None,
    review_reason: str | None = None,
    rollback_hint: dict[str, Any] | None = None,
) -> ProposalRecord:
    ensure_table(conn)
    validation = validation or validate_payload(conn, kind, payload)
    risk_level = risk_level or infer_risk_level(validation, payload)
    status = status or ("needs_review" if risk_level in {"high", "critical"} or payload_requires_review(payload) else "draft")
    now = utc_now()
    proposal_id = next_proposal_id(conn)
    conn.execute(
        """
        insert into proposal_queue
        (id, kind, status, risk_level, source_turn_id, payload_json, validation_json,
         reviewed_by, review_reason, applied_turn_id, rollback_hint_json, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, null, ?, null, ?, ?, ?)
        """,
        (
            proposal_id,
            kind,
            status,
            risk_level,
            source_turn_id,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            json.dumps(validation, ensure_ascii=False, sort_keys=True),
            review_reason,
            json.dumps(rollback_hint or rollback_hint_for_payload(kind, payload), ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    row = conn.execute("select * from proposal_queue where id = ?", (proposal_id,)).fetchone()
    return row_to_record(row)


def list_proposals(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    risk_level: str | None = None,
    limit: int = 50,
) -> list[ProposalRecord]:
    ensure_table(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if risk_level:
        clauses.append("risk_level = ?")
        params.append(risk_level)
    where = "where " + " and ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"""
        select * from proposal_queue
        {where}
        order by created_at desc, id desc
        limit ?
        """,
        (*params, max(1, int(limit))),
    ).fetchall()
    return [row_to_record(row) for row in rows]


def review_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    *,
    approve: bool,
    reviewed_by: str,
    reason: str | None = None,
) -> ProposalRecord:
    ensure_table(conn)
    status = "approved" if approve else "rejected"
    now = utc_now()
    conn.execute(
        "update proposal_queue set status=?, reviewed_by=?, review_reason=?, updated_at=? where id=?",
        (status, reviewed_by, reason, now, proposal_id),
    )
    row = conn.execute("select * from proposal_queue where id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"proposal not found: {proposal_id}")
    return row_to_record(row)


def batch_review_proposals(
    conn: sqlite3.Connection,
    *,
    proposal_ids: list[str] | None = None,
    status_filter: str = "needs_review",
    kind: str | None = None,
    risk_level: str | None = None,
    approve: bool,
    reviewed_by: str,
    reason: str | None = None,
    limit: int = 50,
) -> list[ProposalRecord]:
    ensure_table(conn)
    records = (
        [get_proposal(conn, proposal_id) for proposal_id in proposal_ids]
        if proposal_ids
        else list_proposals(conn, status=status_filter, kind=kind, risk_level=risk_level, limit=limit)
    )
    reviewed: list[ProposalRecord] = []
    for record in records:
        if record.status not in {"draft", "needs_review", "approved", "rejected"}:
            continue
        reviewed.append(
            review_proposal(
                conn,
                record.id,
                approve=approve,
                reviewed_by=reviewed_by,
                reason=reason,
            )
        )
    return reviewed


def mark_proposal_applied(
    conn: sqlite3.Connection,
    proposal_id: str,
    *,
    applied_turn_id: str | None = None,
    rollback_hint: dict[str, Any] | None = None,
) -> ProposalRecord:
    ensure_table(conn)
    now = utc_now()
    record = get_proposal(conn, proposal_id)
    hint = rollback_hint or record.rollback_hint or rollback_hint_for_payload(record.kind, record.payload)
    conn.execute(
        "update proposal_queue set status='applied', applied_turn_id=?, rollback_hint_json=?, updated_at=? where id=?",
        (applied_turn_id, json.dumps(hint, ensure_ascii=False, sort_keys=True), now, proposal_id),
    )
    row = conn.execute("select * from proposal_queue where id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"proposal not found: {proposal_id}")
    return row_to_record(row)


def get_proposal(conn: sqlite3.Connection, proposal_id: str) -> ProposalRecord:
    ensure_table(conn)
    row = conn.execute("select * from proposal_queue where id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError(f"proposal not found: {proposal_id}")
    return row_to_record(row)


def validate_payload(conn: sqlite3.Connection, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "content_delta":
        result = validate_content_delta(payload, conn)
        return {"ok": result.ok, "errors": result.errors, "warnings": result.warnings}
    return {"ok": True, "errors": [], "warnings": []}


def infer_risk_level(validation: dict[str, Any], payload: dict[str, Any]) -> str:
    warnings = [str(item) for item in validation.get("warnings", []) if item]
    if any("high-impact" in item or "route" in item or "world_setting" in item or "rule" in item for item in warnings):
        return "high"
    if payload_requires_review(payload):
        return "high"
    if warnings:
        return "medium"
    return "low"


def payload_requires_review(payload: dict[str, Any]) -> bool:
    meta = payload.get("meta", {})
    return isinstance(meta, dict) and bool(meta.get("review_required")) and not bool(meta.get("reviewed_by"))


def next_proposal_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        select id from proposal_queue
        where id glob 'proposal:[0-9][0-9][0-9][0-9][0-9][0-9]'
        order by id desc
        limit 1
        """
    ).fetchone()
    if not row:
        return "proposal:000001"
    number = int(str(row["id"]).split(":", 1)[1]) + 1
    return f"proposal:{number:06d}"


def row_to_record(row: sqlite3.Row) -> ProposalRecord:
    keys = set(row.keys())
    return ProposalRecord(
        id=str(row["id"]),
        kind=str(row["kind"]),
        status=str(row["status"]),
        risk_level=str(row["risk_level"]),
        source_turn_id=row["source_turn_id"],
        payload=json.loads(row["payload_json"]),
        validation=json.loads(row["validation_json"]),
        reviewed_by=row["reviewed_by"],
        review_reason=row["review_reason"] if "review_reason" in keys else None,
        applied_turn_id=row["applied_turn_id"] if "applied_turn_id" in keys else None,
        rollback_hint=json.loads(row["rollback_hint_json"]) if "rollback_hint_json" in keys else {},
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def render_proposal_list(records: list[ProposalRecord]) -> str:
    lines = [
        "# Proposal Queue",
        "",
        "| ID | Kind | Status | Risk | Reviewed By |",
        "|----|------|--------|------|-------------|",
    ]
    for record in records:
        lines.append(
            f"| `{record.id}` | {record.kind} | {record.status} | {record.risk_level} | {record.reviewed_by or ''} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def proposal_report(conn: sqlite3.Connection) -> dict[str, Any]:
    ensure_table(conn)
    total = conn.execute("select count(*) as count from proposal_queue").fetchone()["count"]
    by_status = {
        row["status"]: int(row["count"])
        for row in conn.execute("select status, count(*) as count from proposal_queue group by status").fetchall()
    }
    by_kind = {
        row["kind"]: int(row["count"])
        for row in conn.execute("select kind, count(*) as count from proposal_queue group by kind").fetchall()
    }
    by_risk = {
        row["risk_level"]: int(row["count"])
        for row in conn.execute("select risk_level, count(*) as count from proposal_queue group by risk_level").fetchall()
    }
    stale = [
        row_to_record(row).to_dict()
        for row in conn.execute(
            """
            select * from proposal_queue
            where status in ('draft', 'needs_review')
            order by created_at, id
            limit 10
            """
        ).fetchall()
    ]
    return {
        "total": int(total),
        "by_status": by_status,
        "by_kind": by_kind,
        "by_risk": by_risk,
        "oldest_open": stale,
    }


def render_proposal_report(data: dict[str, Any]) -> str:
    lines = ["# Proposal Maintenance Report", ""]
    lines.append(f"- total: `{data['total']}`")
    lines.extend(["", "## By Status"])
    for key, value in sorted(data.get("by_status", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Kind"])
    for key, value in sorted(data.get("by_kind", {}).items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## By Risk"])
    for key, value in sorted(data.get("by_risk", {}).items()):
        lines.append(f"- {key}: {value}")
    open_records = data.get("oldest_open", [])
    if open_records:
        lines.extend(["", "## Oldest Open"])
        for record in open_records:
            lines.append(f"- `{record['id']}` {record['kind']} {record['status']} {record['risk_level']}")
    return "\n".join(lines).rstrip() + "\n"


def rollback_hint_for_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind != "content_delta":
        return {
            "strategy": "manual_review",
            "message": "Review the proposal payload and apply a compensating patch if needed.",
        }
    affected: dict[str, list[str]] = {}
    for key in sorted(payload):
        if not key.startswith("upsert_"):
            continue
        records = payload.get(key, [])
        if isinstance(records, list):
            affected[key] = [str(record.get("id")) for record in records if isinstance(record, dict) and record.get("id")]
    return {
        "strategy": "restore_backup_or_compensating_delta",
        "message": "Prefer restoring the pre-apply backup. Otherwise inspect affected ids and apply a reviewed compensating delta.",
        "affected": affected,
        "turn_id": payload.get("turn_id") or payload.get("updated_turn_id"),
    }


def render_rollback_plan(record: ProposalRecord) -> str:
    lines = [
        "# Proposal Rollback Plan",
        "",
        f"- proposal: `{record.id}`",
        f"- status: `{record.status}`",
        f"- kind: `{record.kind}`",
        f"- applied_turn_id: `{record.applied_turn_id or ''}`",
        f"- backup: `{record.rollback_hint.get('backup_id') or ''}`",
        "",
        "## Strategy",
        "",
        str(record.rollback_hint.get("strategy") or "manual_review"),
        "",
        "## Guidance",
        "",
        str(record.rollback_hint.get("message") or "Review payload and restore from backup or apply a compensating patch."),
    ]
    affected = record.rollback_hint.get("affected")
    if isinstance(affected, dict) and affected:
        lines.extend(["", "## Affected IDs"])
        for key, values in sorted(affected.items()):
            lines.append(f"- {key}: " + ", ".join(f"`{value}`" for value in values))
    return "\n".join(lines).rstrip() + "\n"


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists proposal_queue (
          id text primary key,
          kind text not null,
          status text not null,
          risk_level text not null,
          source_turn_id text,
          payload_json text not null,
          validation_json text not null default '{}',
          reviewed_by text,
          review_reason text,
          applied_turn_id text,
          rollback_hint_json text not null default '{}',
          created_at text not null,
          updated_at text not null
        )
        """
    )
    ensure_columns(conn)


def ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("pragma table_info(proposal_queue)").fetchall()}
    additions = {
        "review_reason": "alter table proposal_queue add column review_reason text",
        "applied_turn_id": "alter table proposal_queue add column applied_turn_id text",
        "rollback_hint_json": "alter table proposal_queue add column rollback_hint_json text not null default '{}'",
    }
    for column, statement in additions.items():
        if column not in columns:
            conn.execute(statement)
