from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import utc_now
from .resource_paths import ResourceFile, migration_resource_files


@dataclass(frozen=True)
class MigrationRecord:
    id: str
    path: str
    applied: bool
    applied_at: str | None = None
    checksum: str | None = None
    checksum_ok: bool | None = None


def migration_files() -> list[ResourceFile]:
    return migration_resource_files()


def migration_id(path: ResourceFile) -> str:
    return path.id


def migration_checksum(path: ResourceFile) -> str:
    return path.checksum


def ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists schema_migrations (
          id text primary key,
          applied_at text not null
        )
        """
    )
    mark_existing_initial_schema(conn)
    conn.commit()


def mark_existing_initial_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute("select count(*) from schema_migrations").fetchone()
    if row and int(row[0]) > 0:
        return
    has_entities = conn.execute("select 1 from sqlite_master where type='table' and name='entities'").fetchone()
    if has_entities:
        conn.execute(
            "insert or ignore into schema_migrations(id, applied_at) values(?, ?)",
            ("0001_init", utc_now()),
        )


def migration_status(conn: sqlite3.Connection) -> list[MigrationRecord]:
    ensure_schema_migrations(conn)
    has_checksum = "checksum" in table_columns(conn, "schema_migrations")
    applied_rows = conn.execute(
        "select id, applied_at, checksum from schema_migrations" if has_checksum
        else "select id, applied_at, null as checksum from schema_migrations"
    ).fetchall()
    applied = {row["id"]: row for row in applied_rows}
    return [
        MigrationRecord(
            id=migration_id(path),
            path=path,
            applied=migration_id(path) in applied,
            applied_at=applied[migration_id(path)]["applied_at"] if migration_id(path) in applied else None,
            checksum=applied[migration_id(path)]["checksum"] if migration_id(path) in applied else None,
            checksum_ok=(
                applied[migration_id(path)]["checksum"] == migration_checksum(path)
                if migration_id(path) in applied and applied[migration_id(path)]["checksum"]
                else None
            ),
        )
        for path in migration_files()
    ]


def apply_pending_migrations(conn: sqlite3.Connection) -> list[MigrationRecord]:
    ensure_schema_migrations(conn)
    applied_ids = {
        row["id"]
        for row in conn.execute("select id from schema_migrations").fetchall()
    }
    applied_now: list[MigrationRecord] = []
    for path in migration_files():
        mid = migration_id(path)
        if mid in applied_ids:
            continue
        conn.execute("begin")
        try:
            for statement in split_sql_statements(path.text):
                conn.execute(statement)
            applied_at = utc_now()
            if "checksum" in table_columns(conn, "schema_migrations"):
                conn.execute(
                    "insert into schema_migrations(id, applied_at, checksum) values(?, ?, ?)",
                    (mid, applied_at, migration_checksum(path)),
                )
            else:
                conn.execute("insert into schema_migrations(id, applied_at) values(?, ?)", (mid, applied_at))
            conn.commit()
            applied_now.append(MigrationRecord(id=mid, path=path, applied=True, applied_at=applied_at))
        except Exception:
            conn.rollback()
            raise
    populate_missing_checksums(conn)
    return applied_now


def populate_missing_checksums(conn: sqlite3.Connection) -> None:
    if "checksum" not in table_columns(conn, "schema_migrations"):
        return
    for path in migration_files():
        conn.execute(
            "update schema_migrations set checksum=? where id=? and checksum is null",
            (migration_checksum(path), migration_id(path)),
        )
    conn.commit()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}


def split_sql_statements(text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            buffer = []
    tail = "\n".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def render_migration_status(records: list[MigrationRecord]) -> str:
    lines = [
        "# Migration Status",
        "",
        "| ID | Applied | Checksum | Applied At | Path |",
        "|----|---------|----------|------------|------|",
    ]
    for record in records:
        checksum_status = "ok" if record.checksum_ok else "mismatch" if record.checksum_ok is False else "untracked"
        lines.append(
            f"| `{record.id}` | {'yes' if record.applied else 'no'} | {checksum_status} | {record.applied_at or ''} | `{record.path}` |"
        )
    return "\n".join(lines) + "\n"
