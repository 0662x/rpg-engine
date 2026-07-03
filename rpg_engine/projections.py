from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

from .atomic_io import write_text_atomic
from .campaign import Campaign
from .db import utc_now

if TYPE_CHECKING:
    from .projection_service import ProjectionReport


PROJECTION_VERSIONS = {
    "events_jsonl": 1,
    "search": 1,
    "snapshots": 1,
    "cards": 1,
    "memory": 1,
    "reports": 1,
    "package_lock": 1,
}


@dataclass
class ProjectionRefreshResult:
    refreshed: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def projection_tables_exist(conn: sqlite3.Connection) -> bool:
    names = {
        row[0]
        for row in conn.execute(
            "select name from sqlite_master where type='table' and name in ('outbox', 'projection_state')"
        ).fetchall()
    }
    return names == {"outbox", "projection_state"}


def ensure_projection_rows(conn: sqlite3.Connection, *, turn_id: str | None = None) -> None:
    if not projection_tables_exist(conn):
        return
    now = utc_now()
    for name, version in PROJECTION_VERSIONS.items():
        conn.execute(
            """
            insert into projection_state(name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'clean', ?, null)
            on conflict(name) do nothing
            """,
            (name, version, turn_id, now),
        )


def mark_projections_dirty(conn: sqlite3.Connection, names: Iterable[str], *, turn_id: str) -> None:
    if not projection_tables_exist(conn):
        return
    ensure_projection_rows(conn, turn_id=turn_id)
    now = utc_now()
    for name in names:
        version = PROJECTION_VERSIONS[name]
        conn.execute(
            """
            insert into projection_state(name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'dirty', ?, null)
            on conflict(name) do update set
              version=excluded.version,
              last_turn_id=excluded.last_turn_id,
              status='dirty',
              updated_at=excluded.updated_at,
              last_error=null
            """,
            (name, version, turn_id, now),
        )


def mark_projection_clean(conn: sqlite3.Connection, name: str, *, turn_id: str | None) -> None:
    if not projection_tables_exist(conn):
        return
    conn.execute(
        """
        insert into projection_state(name, version, last_turn_id, status, updated_at, last_error)
        values (?, ?, ?, 'clean', ?, null)
        on conflict(name) do update set
          version=excluded.version,
          last_turn_id=excluded.last_turn_id,
          status='clean',
          updated_at=excluded.updated_at,
          last_error=null
        """,
        (name, PROJECTION_VERSIONS[name], turn_id, utc_now()),
    )


def mark_projections_clean(conn: sqlite3.Connection, names: Iterable[str]) -> None:
    turn_id = current_turn_id(conn)
    for name in names:
        mark_projection_clean(conn, name, turn_id=turn_id)


def mark_projection_failed(conn: sqlite3.Connection, name: str, error: str) -> None:
    if not projection_tables_exist(conn):
        return
    conn.execute(
        "update projection_state set status='failed', updated_at=?, last_error=? where name=?",
        (utc_now(), error[:1000], name),
    )


def projection_effective_status(row: sqlite3.Row) -> str:
    name = str(row["name"])
    status = str(row["status"])
    try:
        version = int(row["version"])
    except (TypeError, ValueError):
        version = 0
    if status == "clean" and version < PROJECTION_VERSIONS.get(name, version):
        return "stale"
    return status


def enqueue_event_export(conn: sqlite3.Connection, *, turn_id: str, records: list[dict[str, Any]]) -> None:
    if not projection_tables_exist(conn) or not records:
        return
    outbox_id = f"outbox:{turn_id}:events-jsonl"
    conn.execute(
        """
        insert into outbox(id, topic, payload_json, status, attempts, created_at)
        values (?, 'events.jsonl.append', ?, 'pending', 0, ?)
        on conflict(id) do nothing
        """,
        (outbox_id, json.dumps({"records": records}, ensure_ascii=False, sort_keys=True), utc_now()),
    )


def process_outbox(campaign: Campaign, conn: sqlite3.Connection) -> ProjectionRefreshResult:
    result = ProjectionRefreshResult()
    if not projection_tables_exist(conn):
        return result
    rows = conn.execute(
        "select * from outbox where status in ('pending', 'failed') order by created_at, id"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
            if row["topic"] == "events.jsonl.append":
                append_event_records_idempotently(campaign, payload.get("records", []))
                result.artifacts.append(str(campaign.events_path))
            else:
                raise ValueError(f"unsupported outbox topic: {row['topic']}")
            conn.execute(
                "update outbox set status='done', attempts=attempts+1, processed_at=?, last_error=null where id=?",
                (utc_now(), row["id"]),
            )
            result.refreshed.append(str(row["topic"]))
        except Exception as exc:
            message = f"{row['id']}: {exc}"
            conn.execute(
                "update outbox set status='failed', attempts=attempts+1, last_error=? where id=?",
                (str(exc)[:1000], row["id"]),
            )
            result.errors.append(message)
    if rows:
        pending = conn.execute(
            "select count(*) from outbox where topic='events.jsonl.append' and status!='done'"
        ).fetchone()[0]
        current_turn = current_turn_id(conn)
        if pending == 0:
            mark_projection_clean(conn, "events_jsonl", turn_id=current_turn)
        else:
            mark_projection_failed(conn, "events_jsonl", f"{pending} outbox item(s) pending")
        conn.commit()
    return result


def append_event_records_idempotently(campaign: Campaign, records: list[Any]) -> None:
    valid = [record for record in records if isinstance(record, dict) and record.get("event_id")]
    if not valid:
        return
    campaign.events_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids: set[str] = set()
    lines: list[str] = []
    if campaign.events_path.exists():
        lines = campaign.events_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("event_id"):
                existing_ids.add(str(value["event_id"]))
    changed = False
    for record in valid:
        if str(record["event_id"]) in existing_ids:
            continue
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        existing_ids.add(str(record["event_id"]))
        changed = True
    if changed:
        write_text_atomic(campaign.events_path, "\n".join(lines).rstrip() + "\n")


def event_records_from_db(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select id, turn_id, game_time, type, title, summary, payload_json, source, created_at
        from events
        order by turn_id, id
        """
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {"_invalid_payload_json": row["payload_json"]}
        records.append(
            {
                "event_id": row["id"],
                "turn_id": row["turn_id"],
                "game_time": row["game_time"],
                "type": row["type"],
                "title": row["title"],
                "summary": row["summary"],
                "payload": payload,
                "source": row["source"],
                "created_at": row["created_at"],
            }
        )
    return records


def rewrite_events_jsonl(campaign: Campaign, conn: sqlite3.Connection) -> None:
    records = event_records_from_db(conn)
    campaign.events_path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    write_text_atomic(campaign.events_path, text)


def refresh_projections(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    names: Iterable[str] | None = None,
    dirty_only: bool = True,
) -> "ProjectionReport":
    from .projection_service import ProjectionService

    return ProjectionService(campaign, conn).refresh(
        names=names,
        dirty_only=dirty_only,
        profile="legacy_refresh_projections",
    )


def render_projection_status(conn: sqlite3.Connection) -> str:
    if not projection_tables_exist(conn):
        return "# Projection Status\n\n- migration_required: `0003_write_reliability`\n"
    started_in_transaction = conn.in_transaction
    ensure_projection_rows(conn, turn_id=current_turn_id(conn))
    if not started_in_transaction and conn.in_transaction:
        conn.commit()
    rows = conn.execute("select * from projection_state order by name").fetchall()
    pending = conn.execute("select status, count(*) from outbox group by status order by status").fetchall()
    lines = [
        "# Projection Status",
        "",
        "| Name | Version | Last Turn | Status | Error |",
        "|------|---------|-----------|--------|-------|",
    ]
    for row in rows:
        status = projection_effective_status(row)
        error = row["last_error"] or ""
        if status == "stale" and not error:
            error = f"version {row['version']} < {PROJECTION_VERSIONS.get(str(row['name']), row['version'])}"
        lines.append(
            f"| `{row['name']}` | {row['version']} | `{row['last_turn_id'] or ''}` | {status} | {error} |"
        )
    lines.extend(["", "## Outbox", "", "| Status | Count |", "|--------|-------|"])
    for row in pending:
        lines.append(f"| {row[0]} | {row[1]} |")
    if not pending:
        lines.append("| empty | 0 |")
    return "\n".join(lines) + "\n"


def current_turn_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("select value from meta where key='current_turn_id'").fetchone()
    return str(row[0]) if row else None
