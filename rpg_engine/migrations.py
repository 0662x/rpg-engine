from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from .db import utc_now
from .resource_paths import ResourceFile, migration_resource_files


ADD_COLUMN_STATEMENT = re.compile(
    r"^alter\s+table\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s+add\s+column\s+"
    r"(?P<column>[A-Za-z_][A-Za-z0-9_]*)\s+(?P<definition>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
MIGRATION_TABLE_TARGET_PATTERNS = (
    re.compile(
        r"^\s*(?:create\s+table(?:\s+if\s+not\s+exists)?|alter\s+table|"
        r"insert(?:\s+or\s+\w+)?\s+into|update(?:\s+or\s+\w+)?|delete\s+from)\s+"
        r"(?:(?:main|temp)\s*\.\s*)?[\"`\[]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"^\s*create\s+(?:unique\s+)?index(?:\s+if\s+not\s+exists)?\s+"
        r"(?:(?:main|temp)\s*\.\s*)?[\"`\[]?[A-Za-z_][A-Za-z0-9_]*[\"`\]]?\s+on\s+"
        r"(?:(?:main|temp)\s*\.\s*)?[\"`\[]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE | re.DOTALL,
    ),
)
DEFAULT_CLAUSE = re.compile(
    r"\bdefault\s+(?P<value>'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\([^)]*\)|\S+)",
    re.IGNORECASE | re.DOTALL,
)
FULL_DERIVED_MEMORY_AUTHORITY_DEFAULT = {
    "authority": "derived_context",
    "fact_authority": False,
    "fact_source": "data/game.sqlite",
    "summary_overrides_facts": False,
}
SQLITE_ASCII_IDENTIFIER_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
)


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
        create table if not exists main.schema_migrations (
          id text primary key,
          applied_at text not null
        )
        """
    )
    mark_existing_initial_schema(conn)
    conn.commit()


def mark_existing_initial_schema(conn: sqlite3.Connection) -> None:
    row = conn.execute("select count(*) from main.schema_migrations").fetchone()
    if row and int(row[0]) > 0:
        return
    has_entities = conn.execute(
        "select 1 from main.sqlite_master where type='table' and name='entities'"
    ).fetchone()
    if has_entities:
        conn.execute(
            "insert or ignore into main.schema_migrations(id, applied_at) values(?, ?)",
            ("0001_init", utc_now()),
        )


def migration_status(conn: sqlite3.Connection) -> list[MigrationRecord]:
    ensure_schema_migrations(conn)
    has_checksum = "checksum" in table_columns(conn, "schema_migrations")
    applied_rows = conn.execute(
        "select id, applied_at, checksum from main.schema_migrations" if has_checksum
        else "select id, applied_at, null as checksum from main.schema_migrations"
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
        for row in conn.execute("select id from main.schema_migrations").fetchall()
    }
    applied_now: list[MigrationRecord] = []
    for path in migration_files():
        mid = migration_id(path)
        if mid in applied_ids:
            continue
        conn.execute("begin")
        try:
            for statement in split_sql_statements(path.text):
                execute_migration_statement(conn, statement)
            applied_at = utc_now()
            if "checksum" in table_columns(conn, "schema_migrations"):
                conn.execute(
                    "insert into main.schema_migrations(id, applied_at, checksum) values(?, ?, ?)",
                    (mid, applied_at, migration_checksum(path)),
                )
            else:
                conn.execute("insert into main.schema_migrations(id, applied_at) values(?, ?)", (mid, applied_at))
            conn.commit()
            applied_now.append(MigrationRecord(id=mid, path=path, applied=True, applied_at=applied_at))
        except Exception:
            conn.rollback()
            raise
    populate_missing_checksums(conn)
    return applied_now


def execute_migration_statement(conn: sqlite3.Connection, statement: str) -> None:
    for table in migration_statement_target_tables(statement):
        if temporary_schema_object_exists(conn, table):
            raise sqlite3.OperationalError(
                f"TEMP schema shadows migration table {table}"
            )
    match = ADD_COLUMN_STATEMENT.match(statement)
    if match:
        table = match.group("table")
        column = match.group("column")
        existing = table_column_info(conn, match.group("table")).get(
            sqlite_identifier_key(column)
        )
        if existing is not None:
            if not additive_column_is_compatible(
                conn=conn,
                table=table,
                column=column,
                definition=match.group("definition"),
                existing=existing,
            ):
                raise sqlite3.OperationalError(
                    f"incompatible existing column {table}.{column}"
                )
            return
        if table.casefold() == "memory_summaries" and additive_column_has_write_blocking_constraints(
            conn,
            table=table,
            column=column,
        ):
            raise sqlite3.OperationalError(
                f"incompatible existing column {table}.{column}"
            )
        escaped_table = table.replace('"', '""')
        escaped_column = column.replace('"', '""')
        conn.execute(
            f'alter table main."{escaped_table}" add column "{escaped_column}" '
            f'{match.group("definition")}'
        )
        return
    conn.execute(statement)


def migration_statement_target_tables(statement: str) -> tuple[str, ...]:
    targets: list[str] = []
    for pattern in MIGRATION_TABLE_TARGET_PATTERNS:
        match = pattern.match(statement)
        if match:
            targets.append(match.group("table"))
    return tuple(dict.fromkeys(targets))


def table_column_info(conn: sqlite3.Connection, table: str) -> dict[str, tuple[object, ...]]:
    escaped = table.replace('"', '""')
    return {
        sqlite_identifier_key(row[1]): tuple(row)
        for row in conn.execute(f'pragma main.table_info("{escaped}")').fetchall()
    }


def temporary_schema_object_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "select 1 from temp.sqlite_master "
        "where type in ('table', 'view') and name = ? collate nocase limit 1",
        (name,),
    ).fetchone()
    return row is not None


def sqlite_identifier_key(value: object) -> str:
    return str(value).translate(SQLITE_ASCII_IDENTIFIER_TRANSLATION)


def additive_column_is_compatible(
    *,
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
    existing: tuple[object, ...],
) -> bool:
    expected_type = definition.split(None, 1)[0].strip().casefold()
    actual_type = str(existing[2] or "").strip().casefold()
    expected_not_null = bool(re.search(r"\bnot\s+null\b", definition, re.IGNORECASE))
    actual_not_null = bool(existing[3])
    default_match = DEFAULT_CLAUSE.search(definition)
    expected_default = normalize_sql_default(default_match.group("value") if default_match else None)
    actual_default = normalize_sql_default(existing[4])
    return (
        actual_type == expected_type
        and actual_not_null == expected_not_null
        and column_default_is_compatible(
            table=table,
            column=column,
            actual=actual_default,
            expected=expected_default,
        )
        and not additive_column_has_write_blocking_constraints(
            conn,
            table=table,
            column=column,
        )
    )


def additive_column_has_write_blocking_constraints(
    conn: sqlite3.Connection,
    *,
    table: str,
    column: str,
) -> bool:
    escaped_table = table.replace('"', '""')
    column_key = sqlite_identifier_key(column)
    for index in conn.execute(f'pragma main.index_list("{escaped_table}")').fetchall():
        if not bool(index[2]):
            continue
        index_name = str(index[1]).replace('"', '""')
        indexed = {
            sqlite_identifier_key(item[2])
            for item in conn.execute(
                f'pragma main.index_xinfo("{index_name}")'
            ).fetchall()
            if bool(item[5]) and item[2] is not None
        }
        if column_key in indexed:
            return True
    for foreign_key in conn.execute(
        f'pragma main.foreign_key_list("{escaped_table}")'
    ).fetchall():
        if sqlite_identifier_key(foreign_key[3]) == column_key:
            return True
    schema_rows = conn.execute(
        """
        select type, sql
        from main.sqlite_master
        where (type='table' and name = ? collate nocase)
           or (type='trigger' and tbl_name = ? collate nocase)
        union all
        select type, sql
        from temp.sqlite_master
        where type='trigger' and tbl_name = ? collate nocase
        """,
        (table, table, table),
    ).fetchall()
    if any(row[0] == "trigger" for row in schema_rows):
        return True
    table_sql = next(
        (row[1] for row in schema_rows if row[0] == "table"),
        None,
    )
    if not isinstance(table_sql, str):
        return True
    executable_sql = sql_without_comments_or_quoted_text(table_sql)
    return bool(
        re.search(r"\bcheck\s*\(", executable_sql, flags=re.IGNORECASE)
        or re.search(r"\bcollate\b", executable_sql, flags=re.IGNORECASE)
    )


def sql_without_comments_or_quoted_text(sql: str) -> str:
    result: list[str] = []
    index = 0
    state = "normal"
    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "normal":
            if char == "-" and following == "-":
                result.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if char == "/" and following == "*":
                result.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if char in {"'", '"', "`", "["}:
                result.append(" ")
                state = {"'": "single", '"': "double", "`": "backtick", "[": "bracket"}[char]
            else:
                result.append(char)
            index += 1
            continue
        if state == "line_comment":
            result.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "normal"
            index += 1
            continue
        if state == "block_comment":
            result.append(" ")
            if char == "*" and following == "/":
                result.append(" ")
                index += 2
                state = "normal"
            else:
                index += 1
            continue
        terminator = {
            "single": "'",
            "double": '"',
            "backtick": "`",
            "bracket": "]",
        }[state]
        result.append(" ")
        if char == terminator:
            if state != "bracket" and following == terminator:
                result.append(" ")
                index += 2
                continue
            state = "normal"
        index += 1
    return "".join(result)


def normalize_sql_default(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    while len(text) >= 2 and text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return None if text.casefold() == "null" else text


def column_default_is_compatible(
    *,
    table: str,
    column: str,
    actual: str | None,
    expected: str | None,
) -> bool:
    if actual == expected:
        return True
    if table.casefold() != "memory_summaries" or column.casefold() != "derived_authority_json":
        return False
    actual_json = sql_json_default(actual)
    expected_json = sql_json_default(expected)
    return bool(
        isinstance(actual_json, dict)
        and isinstance(expected_json, dict)
        and any(
            json_values_equal_strict(actual_json, candidate)
            for candidate in (expected_json, FULL_DERIVED_MEMORY_AUTHORITY_DEFAULT)
        )
    )


def json_values_equal_strict(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            json_values_equal_strict(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            json_values_equal_strict(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def sql_json_default(value: str | None) -> object:
    if not value or len(value) < 2 or value[0] != "'" or value[-1] != "'":
        return None
    try:
        return json.loads(value[1:-1].replace("''", "'"))
    except (TypeError, ValueError):
        return None


def populate_missing_checksums(conn: sqlite3.Connection) -> None:
    if "checksum" not in table_columns(conn, "schema_migrations"):
        return
    for path in migration_files():
        conn.execute(
            "update main.schema_migrations set checksum=? where id=? and checksum is null",
            (migration_checksum(path), migration_id(path)),
        )
    conn.commit()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    escaped = table.replace('"', '""')
    return {
        sqlite_identifier_key(row[1])
        for row in conn.execute(f'pragma main.table_info("{escaped}")').fetchall()
    }


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
