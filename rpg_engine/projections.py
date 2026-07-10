from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterable
from uuid import uuid4

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
PROJECTION_STATE_SCHEMA_COLUMNS = (
    "name",
    "version",
    "last_turn_id",
    "status",
    "updated_at",
    "last_error",
)
STORED_PROJECTION_STATUSES = {"clean", "dirty", "failed", "refreshing", "stale"}
OUTBOX_SCHEMA_COLUMNS = (
    "id",
    "topic",
    "payload_json",
    "status",
    "attempts",
    "created_at",
    "processed_at",
    "last_error",
)
OUTBOX_HEALTH_COLUMNS = (
    "id",
    "topic",
    "status",
    "attempts",
    "created_at",
    "processed_at",
    "last_error",
)
OUTBOX_KNOWN_STATUSES = {"done", "failed", "pending"}
OUTBOX_REPAIRABLE_STATUSES = {"failed", "pending"}


@dataclass
class ProjectionRefreshResult:
    refreshed: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def projection_tables_exist(conn: sqlite3.Connection) -> bool:
    return projection_state_table_exists(conn) and outbox_table_exists(conn)


def projection_state_table_exists(conn: sqlite3.Connection) -> bool:
    return _sqlite_table_exists(conn, "projection_state")


def outbox_table_exists(conn: sqlite3.Connection) -> bool:
    return _sqlite_table_exists(conn, "outbox")


def _inspect_outbox_health(conn: sqlite3.Connection) -> dict[str, Any]:
    health: dict[str, Any] = {
        "role": "projection_work_queue",
        "authority": "evidence",
        "status": "clean",
        "ok": True,
        "counts": {},
        "non_done": [],
        "errors": [],
    }
    if not _sqlite_table_exists(conn, "outbox"):
        health["status"] = "missing"
        health["ok"] = False
        health["errors"] = ["outbox: missing"]
        return health

    columns = _sqlite_table_columns(conn, "outbox")
    errors: list[str] = []
    missing = sorted(set(OUTBOX_SCHEMA_COLUMNS) - columns)
    if missing:
        errors.append(f"outbox schema: missing columns {', '.join(missing)}")

    try:
        if "status" in columns:
            health["counts"] = {
                _outbox_status_key(row["status"]): int(row["count"])
                for row in conn.execute(
                    "select status, count(*) as count from main.outbox group by status order by status"
                ).fetchall()
            }
        else:
            total = int(conn.execute("select count(*) from main.outbox").fetchone()[0])
            health["counts"] = {"<unknown>": total} if total else {}

        select_list = ", ".join(_outbox_select_expression(column, columns) for column in OUTBOX_HEALTH_COLUMNS)
        where_clause = "status is null or status != 'done'" if "status" in columns else "1=1"
        order_by = ", ".join(column for column in ("created_at", "id") if column in columns) or "rowid"
        health["non_done"] = [
            {
                "id": _outbox_id(row["id"]),
                "topic": _none_or_str(row["topic"]),
                "status": _none_or_str(row["status"]),
                "attempts": _int_or_none(row["attempts"]),
                "last_error": _none_or_str(row["last_error"]),
                "created_at": _none_or_str(row["created_at"]),
                "processed_at": _none_or_str(row["processed_at"]),
            }
            for row in conn.execute(
                f"""
                select {select_list}
                from main.outbox
                where {where_clause}
                order by {order_by}
                """
            ).fetchall()
        ]
        for row in health["non_done"]:
            if row.get("id") == "<missing>":
                errors.append("outbox row: missing id")
            status = row.get("status")
            if status not in OUTBOX_KNOWN_STATUSES:
                errors.append(f"outbox.{row.get('id')}: invalid status {status}")
    except sqlite3.Error as exc:
        errors.append(f"outbox schema: unreadable: {exc}")

    health["errors"] = errors
    if errors:
        health["status"] = "malformed"
    elif any(row.get("status") == "failed" for row in health["non_done"]):
        health["status"] = "failed"
    elif any(row.get("status") in OUTBOX_REPAIRABLE_STATUSES for row in health["non_done"]):
        health["status"] = "pending"
    else:
        health["status"] = "clean"
    health["ok"] = health["status"] == "clean"
    return health


def _outbox_issue_message(row: dict[str, Any]) -> str:
    suffix = f" (last_error: {row['last_error']})" if row.get("last_error") else ""
    return f"outbox.{row.get('id')}: status is {row.get('status')}{suffix}"


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from main.sqlite_master where type='table' and name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def _sqlite_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    escaped = table.replace('"', '""')
    return {
        str(row[1])
        for row in conn.execute(f'pragma main.table_info("{escaped}")').fetchall()
    }


def _outbox_select_expression(column: str, columns: set[str]) -> str:
    if column in columns:
        return column
    if column == "id":
        return "rowid as id"
    return f"null as {column}"


def _outbox_status_key(value: Any) -> str:
    return "<null>" if value is None else str(value)


def _outbox_id(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text or "<missing>"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _none_or_str(value: Any) -> str | None:
    return None if value is None else str(value)


def ensure_projection_rows(conn: sqlite3.Connection, *, turn_id: str | None = None) -> None:
    if not projection_state_table_exists(conn):
        return
    now = utc_now()
    for name, version in PROJECTION_VERSIONS.items():
        initial_status = "dirty" if name == "memory" else "clean"
        conn.execute(
            """
            insert into main.projection_state(name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, ?, ?, null)
            on conflict(name) do nothing
            """,
            (name, version, turn_id, initial_status, now),
        )


def projection_state_generation(
    conn: sqlite3.Connection,
    name: str,
) -> tuple[str, str] | None:
    if not projection_state_table_exists(conn):
        return None
    row = conn.execute(
        """
        select status, updated_at
        from main.projection_state
        where name = ? collate binary
        """,
        (name,),
    ).fetchone()
    if not row or not isinstance(row["status"], str) or not isinstance(row["updated_at"], str):
        return None
    return row["status"], row["updated_at"]


def next_projection_generation(conn: sqlite3.Connection, name: str) -> str:
    now = _parse_projection_generation(utc_now()) or datetime.now(timezone.utc)
    current = projection_state_generation(conn, name)
    previous = _parse_projection_generation(current[1]) if current else None
    if previous is not None and now <= previous:
        try:
            now = previous + timedelta(microseconds=1)
        except OverflowError:
            pass
    return _projection_generation_token(now)


def _projection_generation_token(value: datetime) -> str:
    timestamp = value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    local, offset = timestamp.rsplit("+", 1)
    return f"{local}{uuid4().int:039d}+{offset}"


def _parse_projection_generation(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def mark_projection_clean_if_unchanged(
    conn: sqlite3.Connection,
    name: str,
    *,
    turn_id: str | None,
    expected_generation: tuple[str, str] | None,
) -> tuple[str, str] | None:
    if not _projection_state_metadata_writable(conn):
        return None
    generation = next_projection_generation(conn, name)
    if expected_generation is None:
        cursor = conn.execute(
            """
            insert into main.projection_state
            (name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'clean', ?, null)
            on conflict(name) do nothing
            """,
            (name, PROJECTION_VERSIONS[name], turn_id, generation),
        )
        return ("clean", generation) if cursor.rowcount == 1 else None
    expected_status, expected_updated_at = expected_generation
    cursor = conn.execute(
        """
        update main.projection_state
        set version=?, last_turn_id=?, status='clean', updated_at=?, last_error=null
        where name = ? collate binary
          and status = ?
          and updated_at = ?
        """,
        (
            PROJECTION_VERSIONS[name],
            turn_id,
            generation,
            name,
            expected_status,
            expected_updated_at,
        ),
    )
    return ("clean", generation) if cursor.rowcount == 1 else None


def mark_projection_refreshing_if_unchanged(
    conn: sqlite3.Connection,
    name: str,
    *,
    turn_id: str | None,
    expected_generation: tuple[str, str] | None,
) -> tuple[str, str] | None:
    if not _projection_state_metadata_writable(conn):
        return None
    generation = next_projection_generation(conn, name)
    if expected_generation is None:
        cursor = conn.execute(
            """
            insert into main.projection_state
            (name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'refreshing', ?, null)
            on conflict(name) do nothing
            """,
            (name, PROJECTION_VERSIONS[name], turn_id, generation),
        )
        return ("refreshing", generation) if cursor.rowcount == 1 else None
    expected_status, expected_updated_at = expected_generation
    cursor = conn.execute(
        """
        update main.projection_state
        set version=?, last_turn_id=?, status='refreshing', updated_at=?, last_error=null
        where name = ? collate binary
          and status = ?
          and updated_at = ?
        """,
        (
            PROJECTION_VERSIONS[name],
            turn_id,
            generation,
            name,
            expected_status,
            expected_updated_at,
        ),
    )
    return ("refreshing", generation) if cursor.rowcount == 1 else None


def mark_projection_failed_if_unchanged(
    conn: sqlite3.Connection,
    name: str,
    *,
    error: str,
    expected_generation: tuple[str, str],
) -> bool:
    if not _projection_state_metadata_writable(conn):
        return False
    expected_status, expected_updated_at = expected_generation
    cursor = conn.execute(
        """
        update main.projection_state
        set status='failed', updated_at=?, last_error=?
        where name = ? collate binary
          and status = ?
          and updated_at = ?
        """,
        (
            next_projection_generation(conn, name),
            error[:1000],
            name,
            expected_status,
            expected_updated_at,
        ),
    )
    return cursor.rowcount == 1


def mark_projection_dirty_if_unchanged(
    conn: sqlite3.Connection,
    name: str,
    *,
    turn_id: str | None,
    expected_generation: tuple[str, str],
) -> bool:
    if not _projection_state_metadata_writable(conn):
        return False
    expected_status, expected_updated_at = expected_generation
    cursor = conn.execute(
        """
        update main.projection_state
        set version=?, last_turn_id=?, status='dirty', updated_at=?, last_error=null
        where name = ? collate binary
          and status = ?
          and updated_at = ?
        """,
        (
            PROJECTION_VERSIONS[name],
            turn_id,
            next_projection_generation(conn, name),
            name,
            expected_status,
            expected_updated_at,
        ),
    )
    return cursor.rowcount == 1


def mark_projections_dirty(conn: sqlite3.Connection, names: Iterable[str], *, turn_id: str) -> bool:
    names = tuple(names)
    if not names:
        return True
    if any(name not in PROJECTION_VERSIONS for name in names):
        return False
    if not projection_state_table_exists(conn) or not _projection_state_metadata_writable(conn):
        return False

    def write() -> None:
        ensure_projection_rows(conn, turn_id=turn_id)
        for name in names:
            version = PROJECTION_VERSIONS[name]
            generation = next_projection_generation(conn, name)
            conn.execute(
                """
                insert into main.projection_state
                (name, version, last_turn_id, status, updated_at, last_error)
                values (?, ?, ?, 'dirty', ?, null)
                on conflict(name) do update set
                  version=excluded.version,
                  last_turn_id=excluded.last_turn_id,
                  status='dirty',
                  updated_at=excluded.updated_at,
                  last_error=null
                """,
                (name, version, turn_id, generation),
            )

    if _run_projection_metadata_write(conn, write):
        return True

    def fallback_write() -> None:
        for name in names:
            conn.execute(
                """
                insert into main.projection_state
                (name, version, last_turn_id, status, updated_at, last_error)
                values (?, ?, ?, 'dirty',
                        strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now'), null)
                on conflict(name) do update set
                  version=excluded.version,
                  last_turn_id=excluded.last_turn_id,
                  status='dirty',
                  updated_at=excluded.updated_at,
                  last_error=null
                """,
                (name, PROJECTION_VERSIONS[name], turn_id),
            )

    return _run_projection_metadata_write(conn, fallback_write)


def mark_projection_clean(conn: sqlite3.Connection, name: str, *, turn_id: str | None) -> bool:
    if name not in PROJECTION_VERSIONS:
        return False
    if not projection_state_table_exists(conn) or not _projection_state_metadata_writable(conn):
        return False

    def write() -> None:
        conn.execute(
            """
            insert into main.projection_state
            (name, version, last_turn_id, status, updated_at, last_error)
            values (?, ?, ?, 'clean', ?, null)
            on conflict(name) do update set
              version=excluded.version,
              last_turn_id=excluded.last_turn_id,
              status='clean',
              updated_at=excluded.updated_at,
              last_error=null
            """,
            (name, PROJECTION_VERSIONS[name], turn_id, next_projection_generation(conn, name)),
        )

    return _run_projection_metadata_write(conn, write)


def mark_projections_clean(conn: sqlite3.Connection, names: Iterable[str]) -> bool:
    turn_id = current_turn_id(conn)
    results = [
        mark_projection_clean(conn, name, turn_id=turn_id)
        for name in names
    ]
    return all(results)


def mark_projection_failed(conn: sqlite3.Connection, name: str, error: str) -> bool:
    if name not in PROJECTION_VERSIONS:
        return False
    if not projection_state_table_exists(conn) or not _projection_state_metadata_writable(conn):
        return False

    updated = False

    def write() -> None:
        nonlocal updated
        cursor = conn.execute(
            "update main.projection_state "
            "set status='failed', updated_at=?, last_error=? where name=?",
            (next_projection_generation(conn, name), error[:1000], name),
        )
        updated = cursor.rowcount == 1

    return _run_projection_metadata_write(conn, write) and updated


def _run_projection_metadata_write(
    conn: sqlite3.Connection,
    write: Any,
) -> bool:
    started_in_transaction = conn.in_transaction
    savepoint = "projection_metadata_write"
    savepoint_open = False
    try:
        if not started_in_transaction:
            conn.execute("begin")
        conn.execute(f"savepoint {savepoint}")
        savepoint_open = True
        write()
        conn.execute(f"release {savepoint}")
        savepoint_open = False
        if not started_in_transaction:
            conn.commit()
        return True
    except Exception:
        if savepoint_open:
            try:
                conn.execute(f"rollback to {savepoint}")
            except sqlite3.Error:
                pass
            try:
                conn.execute(f"release {savepoint}")
            except sqlite3.Error:
                pass
        if not started_in_transaction and conn.in_transaction:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        return False


def _projection_state_metadata_writable(conn: sqlite3.Connection) -> bool:
    try:
        from .memory import projection_state_readable

        return projection_state_readable(conn)
    except Exception:
        return False


def projection_effective_status(row: sqlite3.Row) -> str:
    name = str(row["name"])
    if name not in PROJECTION_VERSIONS:
        return "stale"
    if name.casefold() in PROJECTION_VERSIONS and name.casefold() != name:
        return "stale"
    status = str(row["status"])
    if status not in STORED_PROJECTION_STATUSES:
        return "stale"
    raw_version = row["version"]
    if isinstance(raw_version, bool) or not isinstance(raw_version, int):
        return "stale"
    version = raw_version
    if status == "clean" and version != PROJECTION_VERSIONS.get(name, version):
        return "stale"
    return status


def enqueue_event_export(conn: sqlite3.Connection, *, turn_id: str, records: list[dict[str, Any]]) -> None:
    if not outbox_table_exists(conn) or not records:
        return
    outbox_id = f"outbox:{turn_id}:events-jsonl"
    conn.execute(
        """
        insert into main.outbox(id, topic, payload_json, status, attempts, created_at)
        values (?, 'events.jsonl.append', ?, 'pending', 0, ?)
        on conflict(id) do nothing
        """,
        (outbox_id, json.dumps({"records": records}, ensure_ascii=False, sort_keys=True), utc_now()),
    )


def process_outbox(campaign: Campaign, conn: sqlite3.Connection) -> ProjectionRefreshResult:
    result = ProjectionRefreshResult()
    if not outbox_table_exists(conn):
        return result
    rows = conn.execute(
        "select * from main.outbox "
        "where status in ('pending', 'failed') order by created_at, id"
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
                "update main.outbox set status='done', attempts=attempts+1, "
                "processed_at=?, last_error=null where id=?",
                (utc_now(), row["id"]),
            )
            result.refreshed.append(str(row["topic"]))
        except Exception as exc:
            message = f"{row['id']}: {exc}"
            conn.execute(
                "update main.outbox set status='failed', attempts=attempts+1, "
                "last_error=? where id=?",
                (str(exc)[:1000], row["id"]),
            )
            result.errors.append(message)
    if rows:
        pending = conn.execute(
            "select count(*) from main.outbox "
            "where topic='events.jsonl.append' and status!='done'"
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
        from main.events
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
    if not projection_state_table_exists(conn):
        return "# Projection Status\n\n- migration_required: `0003_write_reliability`\n"
    from .memory import projection_state_readable

    if not projection_state_readable(conn):
        columns = _sqlite_table_columns(conn, "projection_state")
        lines = [
            "# Projection Status",
            "",
            "- projection_state schema incompatible: `stale`",
            "",
            "| Name | Version | Last Turn | Status | Error |",
            "|------|---------|-----------|--------|-------|",
        ]
        if set(PROJECTION_STATE_SCHEMA_COLUMNS).issubset(columns):
            rows = conn.execute(
                """
                select name, version, last_turn_id
                from main.projection_state
                order by name
                """
            ).fetchall()
            lines.extend(
                f"| `{row['name']}` | {row['version']} | `{row['last_turn_id'] or ''}` | "
                "stale | projection_state schema incompatible |"
                for row in rows
            )
        if len(lines) == 6:
            lines.append(
                "| `memory` | ? | `` | stale | projection_state schema incompatible |"
            )
        return "\n".join(lines) + "\n"
    started_in_transaction = conn.in_transaction
    ensure_projection_rows(conn, turn_id=current_turn_id(conn))
    if not started_in_transaction and conn.in_transaction:
        conn.commit()
    rows = conn.execute("select * from main.projection_state order by name").fetchall()
    pending = (
        conn.execute(
            "select status, count(*) from main.outbox group by status order by status"
        ).fetchall()
        if outbox_table_exists(conn)
        else []
    )
    lines = [
        "# Projection Status",
        "",
        "| Name | Version | Last Turn | Status | Error |",
        "|------|---------|-----------|--------|-------|",
    ]
    for row in rows:
        name = str(row["name"])
        status = projection_effective_status(row)
        if name.casefold() == "memory" and name != "memory":
            status = "stale"
        elif name == "memory":
            from .memory import memory_projection_health

            status = str(memory_projection_health(conn)["status"])
        error = row["last_error"] or ""
        if status == "stale" and not error:
            raw_status = str(row["status"])
            if name not in PROJECTION_VERSIONS:
                error = "canonical projection identity required"
            elif raw_status not in STORED_PROJECTION_STATUSES:
                error = f"invalid stored status: {raw_status}"
            elif name == "memory":
                error = "memory provenance refresh required"
            else:
                error = (
                    f"version {row['version']} != "
                    f"{PROJECTION_VERSIONS[name]}"
                )
        lines.append(
            f"| `{name}` | {row['version']} | `{row['last_turn_id'] or ''}` | {status} | {error} |"
        )
    lines.extend(["", "## Outbox", "", "| Status | Count |", "|--------|-------|"])
    for row in pending:
        lines.append(f"| {row[0]} | {row[1]} |")
    if not outbox_table_exists(conn):
        lines.append("| missing | 0 |")
    elif not pending:
        lines.append("| empty | 0 |")
    return "\n".join(lines) + "\n"


def current_turn_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("select value from main.meta where key='current_turn_id'").fetchone()
    return str(row[0]) if row else None
