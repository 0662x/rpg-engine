from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .atomic_io import write_text_atomic
from .campaign import Campaign
from .db import entity_subtype_visibility_sql, utc_now
from .projections import (
    mark_projection_clean_if_unchanged,
    mark_projection_dirty_if_unchanged,
    mark_projection_failed_if_unchanged,
    mark_projection_refreshing_if_unchanged,
    projection_effective_status,
    projection_state_generation,
)
from .redaction import (
    find_hidden_entity_id_substrings,
    find_hidden_entity_ref_substrings,
    find_hidden_entity_ref_tokens,
    redact_hidden_entity_refs,
)
from .render import parse_json
from .time_weather import format_time_brief, format_weather_brief
from .visibility import (
    MAINTENANCE_VIEW,
    can_read_hidden,
    clock_visibility_sql,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalized_text_sql,
)


DAY_PATTERN = re.compile(r"第\s*(\d+)\s*天")
DERIVED_MEMORY_AUTHORITY = {
    "authority": "derived_context",
    "fact_authority": False,
    "fact_source": "data/game.sqlite",
    "summary_overrides_facts": False,
}
MINIMAL_DERIVED_MEMORY_AUTHORITY = {
    "authority": "derived_context",
    "fact_authority": False,
}
DERIVED_MEMORY_AUTHORITY_SQL_DEFAULT = json.dumps(
    DERIVED_MEMORY_AUTHORITY,
    ensure_ascii=False,
    sort_keys=True,
).replace("'", "''")
MEMORY_METADATA_COLUMNS = {
    "summary_type": "text not null default 'deterministic'",
    "visibility_mode": "text not null default 'player'",
    "freshness_status": "text not null default 'fresh'",
    "freshness_turn_id": "text",
    "stale_reason": "text not null default ''",
    "freshness_evidence_json": "text not null default '{}'",
    "derived_authority_json": f"text not null default '{DERIVED_MEMORY_AUTHORITY_SQL_DEFAULT}'",
}
MEMORY_METADATA_COLUMN_NAMES = frozenset(MEMORY_METADATA_COLUMNS)
MEMORY_BASE_COLUMN_NAMES = frozenset(
    {
        "id",
        "kind",
        "subject_id",
        "title",
        "summary",
        "key_points_json",
        "source_event_ids_json",
        "source_turn_ids_json",
        "valid_from_turn",
        "valid_to_turn",
        "updated_at",
    }
)
MEMORY_REQUIRED_COLUMN_NAMES = MEMORY_BASE_COLUMN_NAMES | MEMORY_METADATA_COLUMN_NAMES
MEMORY_COLUMN_CONTRACTS: dict[str, tuple[str, bool | None, str | None, int]] = {
    "id": ("text", None, None, 1),
    "kind": ("text", True, None, 0),
    "subject_id": ("text", False, None, 0),
    "title": ("text", True, None, 0),
    "summary": ("text", True, None, 0),
    "key_points_json": ("text", True, "'[]'", 0),
    "source_event_ids_json": ("text", True, "'[]'", 0),
    "source_turn_ids_json": ("text", True, "'[]'", 0),
    "valid_from_turn": ("text", False, None, 0),
    "valid_to_turn": ("text", False, None, 0),
    "summary_type": ("text", True, "'deterministic'", 0),
    "visibility_mode": ("text", True, "'player'", 0),
    "freshness_status": ("text", True, "'fresh'", 0),
    "freshness_turn_id": ("text", False, None, 0),
    "stale_reason": ("text", True, "''", 0),
    "freshness_evidence_json": ("text", True, "'{}'", 0),
    "derived_authority_json": ("text", True, None, 0),
    "updated_at": ("text", True, None, 0),
}
MEMORY_FALLBACK_AUTHORITY_JSON = json.dumps(DERIVED_MEMORY_AUTHORITY, ensure_ascii=False, sort_keys=True)
PLAYER_SAFE_MEMORY_REASONS = frozenset(
    {
        "empty_memory_table",
        "memory_summary_omitted",
        "missing_freshness_evidence",
        "missing_memory_metadata_columns",
        "missing_memory_table",
        "missing_subject",
        "projection_memory_dirty",
        "projection_memory_failed",
        "projection_memory_refreshing",
        "projection_memory_stale",
        "invalid_summary_validity_window",
        "invalid_memory_row",
        "projection_memory_unstable",
        "summary_not_yet_valid",
        "summary_validity_expired",
        "stored_stale",
        "subject_archived",
        "subject_updated_after_summary",
    }
)
MEMORY_FRESHNESS_EVIDENCE_KEYS = frozenset(
    {
        "basis",
        "current_turn_id",
        "has_last_error",
        "last_turn_id",
        "missing_columns",
        "projection",
        "source_event_ids",
        "source_turn_ids",
        "status",
        "subject_id",
        "subject_updated_turn_id",
        "valid_from_turn",
        "valid_to_turn",
    }
)
MEMORY_FRESHNESS_ENUMS = {
    "basis": frozenset({"deterministic_rebuild"}),
    "projection": frozenset({"memory"}),
    "status": frozenset({"dirty", "failed", "refreshing", "stale"}),
}
MEMORY_FRESHNESS_STATUSES = frozenset({"fallback", "fresh", "stale"})
MEMORY_SUMMARY_TYPES = frozenset(
    {
        "deterministic",
        "deterministic_character",
        "deterministic_day",
        "deterministic_faction",
        "deterministic_fallback",
        "deterministic_project",
        "deterministic_world",
        "unknown",
    }
)
MEMORY_SUMMARY_KINDS = frozenset({"character", "day", "faction", "project", "world"})
MEMORY_PLAYER_ROW_FIELDS = frozenset(
    {
        "id",
        "kind",
        "subject_id",
        "title",
        "summary",
        "key_points_json",
        "source_event_ids_json",
        "source_turn_ids_json",
        "valid_from_turn",
        "valid_to_turn",
        "summary_type",
        "visibility_mode",
        "freshness_status",
        "freshness_turn_id",
        "stale_reason",
        "freshness_evidence_json",
        "derived_authority_json",
        "updated_at",
    }
)
MEMORY_FRESHNESS_TURN_ID_KEYS = frozenset(
    {
        "current_turn_id",
        "last_turn_id",
        "subject_updated_turn_id",
        "valid_from_turn",
        "valid_to_turn",
    }
)
MEMORY_TURN_ID_PATTERN = re.compile(r"^turn:[A-Za-z0-9_.-]+$")
MEMORY_EVENT_ID_PATTERN = re.compile(r"^event:[A-Za-z0-9_.:-]+$")
MEMORY_ENTITY_ID_PATTERN = re.compile(r"^[a-z]+:[A-Za-z0-9_.-]+$")
MAX_MEMORY_IDENTIFIER_LENGTH = 256
MAX_MEMORY_METADATA_JSON_CHARS = 65536
MAX_MEMORY_METADATA_JSON_DEPTH = 64
MAX_MEMORY_METADATA_JSON_NODES = 4096
MAX_MEMORY_PROVENANCE_REFERENCES = 128
MAX_MEMORY_QUERY_LIMIT = 256
MAX_MEMORY_ROWS_SCANNED = 4096
MEMORY_SUMMARY_ID_PATTERN = re.compile(r"^[a-z]+:[A-Za-z0-9_.:-]+$")
MEMORY_PROJECTION_SCHEMA_COLUMNS = frozenset(
    {"name", "version", "last_turn_id", "status", "updated_at", "last_error"}
)
MEMORY_PROJECTION_COLUMN_CONTRACTS: dict[str, tuple[str, bool | None, str | None, int]] = {
    "name": ("text", None, None, 1),
    "version": ("integer", True, "1", 0),
    "last_turn_id": ("text", False, None, 0),
    "status": ("text", True, "'clean'", 0),
    "updated_at": ("text", True, None, 0),
    "last_error": ("text", False, None, 0),
}
SQLITE_ASCII_IDENTIFIER_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
)
CANONICAL_TABLE_IDENTITIES = {
    "memory_summaries": "id",
    "projection_state": "name",
}
CANONICAL_TABLE_FOREIGN_KEYS = {
    "memory_summaries": frozenset(
        {
            ("subject_id", "entities", "id"),
            ("valid_from_turn", "turns", "id"),
            ("valid_to_turn", "turns", "id"),
        }
    ),
    "projection_state": frozenset({("last_turn_id", "turns", "id")}),
}
MEMORY_AUTHORITY_TABLES = frozenset(
    {
        "memory_summaries",
        "projection_state",
        "turns",
        "events",
        "entities",
        "meta",
    }
)
INVALID_MEMORY_METADATA = object()


@dataclass(frozen=True)
class MemoryBuildResult:
    total: int
    by_kind: dict[str, int]
    report_path: Path


def ensure_memory_tables(conn: sqlite3.Connection) -> None:
    if memory_authority_temp_shadow_exists(conn):
        raise sqlite3.OperationalError("memory authority schema has a TEMP shadow")
    savepoint = "ensure_memory_tables"
    conn.execute(f"savepoint {savepoint}")
    try:
        conn.execute(
            """
            create table if not exists main.memory_summaries (
              id text primary key,
              kind text not null,
              subject_id text,
              title text not null,
              summary text not null,
              key_points_json text not null default '[]',
              source_event_ids_json text not null default '[]',
              source_turn_ids_json text not null default '[]',
              valid_from_turn text,
              valid_to_turn text,
              summary_type text not null default 'deterministic',
              visibility_mode text not null default 'player',
              freshness_status text not null default 'fresh',
              freshness_turn_id text,
              stale_reason text not null default '',
              freshness_evidence_json text not null default '{}',
              derived_authority_json text not null default '{"authority": "derived_context", "fact_authority": false, "fact_source": "data/game.sqlite", "summary_overrides_facts": false}',
              updated_at text not null,
              foreign key(subject_id) references entities(id),
              foreign key(valid_from_turn) references turns(id),
              foreign key(valid_to_turn) references turns(id)
            )
            """
        )
        conn.execute(
            "create index if not exists main.idx_memory_kind_subject "
            "on memory_summaries(kind, subject_id)"
        )
        ensure_memory_metadata_columns(conn)
    except Exception:
        conn.execute(f"rollback to {savepoint}")
        conn.execute(f"release {savepoint}")
        raise
    conn.execute(f"release {savepoint}")


def ensure_memory_metadata_columns(conn: sqlite3.Connection) -> None:
    info = table_column_info(conn, "memory_summaries")
    if not sole_primary_key_is_binary(
        conn,
        "memory_summaries",
        "id",
    ):
        raise sqlite3.OperationalError("memory_summaries schema contract is incompatible")
    for name in MEMORY_BASE_COLUMN_NAMES:
        if name not in info or not memory_column_is_compatible(name, info[name]):
            raise sqlite3.OperationalError(
                f"memory_summaries incompatible existing column: {name}"
            )
    for name in MEMORY_METADATA_COLUMNS:
        if name in info and not memory_column_is_compatible(name, info[name]):
            raise sqlite3.OperationalError(
                f"memory_summaries incompatible existing column: {name}"
            )
    if not table_extensions_are_insert_compatible(
        conn,
        "memory_summaries",
        MEMORY_REQUIRED_COLUMN_NAMES,
    ):
        raise sqlite3.OperationalError("memory_summaries schema contract is incompatible")
    savepoint = "ensure_memory_metadata_columns"
    conn.execute(f"savepoint {savepoint}")
    try:
        for name, definition in MEMORY_METADATA_COLUMNS.items():
            if name not in info:
                conn.execute(
                    f"alter table main.memory_summaries add column {name} {definition}"
                )
        refreshed = table_column_info(conn, "memory_summaries")
        if not all(
            name in refreshed and memory_column_is_compatible(name, refreshed[name])
            for name in MEMORY_REQUIRED_COLUMN_NAMES
        ) or not table_extensions_are_insert_compatible(
            conn,
            "memory_summaries",
            MEMORY_REQUIRED_COLUMN_NAMES,
        ):
            raise sqlite3.OperationalError(
                "memory_summaries schema contract is incompatible"
            )
    except Exception:
        conn.execute(f"rollback to {savepoint}")
        conn.execute(f"release {savepoint}")
        raise
    conn.execute(f"release {savepoint}")


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    escaped = table.replace('"', '""')
    return {
        sqlite_identifier_key(row[1])
        for row in conn.execute(f'pragma main.table_info("{escaped}")').fetchall()
    }


def table_column_info(conn: sqlite3.Connection, table: str) -> dict[str, tuple[Any, ...]]:
    escaped = table.replace('"', '""')
    return {
        sqlite_identifier_key(row[1]): tuple(row)
        for row in conn.execute(f'pragma main.table_info("{escaped}")').fetchall()
    }


def table_xinfo(conn: sqlite3.Connection, table: str) -> dict[str, tuple[Any, ...]]:
    escaped = table.replace('"', '""')
    return {
        sqlite_identifier_key(row[1]): tuple(row)
        for row in conn.execute(f'pragma main.table_xinfo("{escaped}")').fetchall()
    }


def sqlite_identifier_key(value: Any) -> str:
    return str(value).translate(SQLITE_ASCII_IDENTIFIER_TRANSLATION)


def memory_authority_temp_shadow_exists(conn: sqlite3.Connection) -> bool:
    placeholders = ", ".join("?" for _ in MEMORY_AUTHORITY_TABLES)
    row = conn.execute(
        f"""
        select 1
        from temp.sqlite_master
        where type in ('table', 'view')
          and name collate nocase in ({placeholders})
        limit 1
        """,
        sorted(MEMORY_AUTHORITY_TABLES),
    ).fetchone()
    return bool(row)


def memory_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(row["key"]): str(row["value"])
        for row in conn.execute("select key, value from main.meta")
    }


def memory_player_entity_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "select value from main.meta where key = 'player_entity_id'"
    ).fetchone()
    return str(row[0]) if row and row[0] else "pc:player"


def memory_sql_default_is_safe_literal(value: str | None) -> bool:
    if value is None:
        return True
    return bool(
        re.fullmatch(r"'(?:''|[^'])*'", value, flags=re.DOTALL)
        or re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value)
        or re.fullmatch(r"[xX]'[0-9A-Fa-f]*'", value)
    )


def sqlite_sql_without_comments_or_quoted_text(sql: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if char == "-" and following == "-":
            index += 2
            while index < len(sql) and sql[index] not in "\r\n":
                index += 1
            output.append(" ")
            continue
        if char == "/" and following == "*":
            index += 2
            while index + 1 < len(sql) and sql[index : index + 2] != "*/":
                index += 1
            index = min(len(sql), index + 2)
            output.append(" ")
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            while index < len(sql):
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            output.append(" ")
            continue
        if char == "[":
            index += 1
            while index < len(sql) and sql[index] != "]":
                index += 1
            index = min(len(sql), index + 1)
            output.append(" ")
            continue
        output.append(char)
        index += 1
    return "".join(output)


def table_extensions_are_insert_compatible(
    conn: sqlite3.Connection,
    table: str,
    required_columns: frozenset[str],
) -> bool:
    escaped_table = table.replace('"', '""')
    info = table_xinfo(conn, table)
    required = {sqlite_identifier_key(name) for name in required_columns}
    for name, column in info.items():
        if name in required:
            continue
        hidden = int(column[6] or 0) if len(column) > 6 else 0
        if int(column[5] or 0) or hidden != 0:
            return False
        default = normalize_memory_sql_default(column[4])
        if bool(column[3]) and default is None:
            return False
        if not memory_sql_default_is_safe_literal(default):
            return False
    identity = CANONICAL_TABLE_IDENTITIES.get(sqlite_identifier_key(table))
    if identity is None:
        return False
    for index in conn.execute(f'pragma main.index_list("{escaped_table}")').fetchall():
        if str(index[3] or "") == "pk":
            continue
        if bool(index[4]):
            return False
        index_name = str(index[1]).replace('"', '""')
        indexed_columns = [
            (
                None if item[2] is None else sqlite_identifier_key(item[2]),
                sqlite_identifier_key(item[4] or "binary"),
            )
            for item in conn.execute(f'pragma main.index_xinfo("{index_name}")').fetchall()
            if bool(item[5])
        ]
        if any(not name or collation != "binary" for name, collation in indexed_columns):
            return False
        if bool(index[2]) and indexed_columns != [(identity, "binary")]:
            return False
    allowed_foreign_keys = CANONICAL_TABLE_FOREIGN_KEYS.get(
        sqlite_identifier_key(table),
        frozenset(),
    )
    actual_foreign_keys: set[tuple[str, str, str]] = set()
    for foreign_key in conn.execute(
        f'pragma main.foreign_key_list("{escaped_table}")'
    ).fetchall():
        if int(foreign_key[1] or 0) != 0:
            return False
        signature = (
            sqlite_identifier_key(foreign_key[3]),
            sqlite_identifier_key(foreign_key[2]),
            sqlite_identifier_key(foreign_key[4]),
        )
        if signature not in allowed_foreign_keys:
            return False
        actions = tuple(
            sqlite_identifier_key(foreign_key[index] or "")
            for index in (5, 6, 7)
        )
        if actions != ("no action", "no action", "none"):
            return False
        actual_foreign_keys.add(signature)
    if actual_foreign_keys != set(allowed_foreign_keys):
        return False
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
        return False
    table_sql = next(
        (row[1] for row in schema_rows if row[0] == "table"),
        None,
    )
    if not isinstance(table_sql, str):
        return False
    if re.search(
        r"\bcheck\s*\(",
        sqlite_sql_without_comments_or_quoted_text(table_sql),
        flags=re.IGNORECASE,
    ):
        return False
    if sqlite_identifier_key(table) == "memory_summaries" and not canonical_memory_lookup_index_present(conn):
        return False
    return True


def canonical_memory_lookup_index_present(conn: sqlite3.Connection) -> bool:
    for index in conn.execute(
        'pragma main.index_list("memory_summaries")'
    ).fetchall():
        if sqlite_identifier_key(index[1]) != "idx_memory_kind_subject":
            continue
        if bool(index[2]) or bool(index[4]):
            return False
        index_name = str(index[1]).replace('"', '""')
        keys = [
            (
                sqlite_identifier_key(item[2] or ""),
                sqlite_identifier_key(item[4] or "binary"),
            )
            for item in conn.execute(
                f'pragma main.index_xinfo("{index_name}")'
            ).fetchall()
            if bool(item[5])
        ]
        return keys == [("kind", "binary"), ("subject_id", "binary")]
    return False


def sole_primary_key_is_binary(
    conn: sqlite3.Connection,
    table: str,
    column_name: str,
) -> bool:
    escaped_table = table.replace('"', '""')
    info = table_xinfo(conn, table)
    primary_key_columns = [
        (int(column[5] or 0), name)
        for name, column in info.items()
        if int(column[5] or 0)
    ]
    if sorted(primary_key_columns) != [(1, column_name)]:
        return False
    for index in conn.execute(f'pragma main.index_list("{escaped_table}")').fetchall():
        if str(index[3] or "") != "pk":
            continue
        index_name = str(index[1]).replace('"', '""')
        key_columns = [
            item
            for item in conn.execute(f'pragma main.index_xinfo("{index_name}")').fetchall()
            if bool(item[5])
        ]
        return (
            len(key_columns) == 1
            and sqlite_identifier_key(key_columns[0][2]) == column_name
            and sqlite_identifier_key(key_columns[0][4] or "") == "binary"
        )
    return False


def memory_table_exists(conn: sqlite3.Connection) -> bool:
    if memory_authority_temp_shadow_exists(conn):
        return False
    row = conn.execute(
        "select 1 from main.sqlite_master "
        "where type = 'table' and name = 'memory_summaries' collate nocase"
    ).fetchone()
    return bool(row)


def memory_metadata_columns_present(conn: sqlite3.Connection) -> bool:
    if not memory_table_exists(conn):
        return False
    info = table_column_info(conn, "memory_summaries")
    if not MEMORY_REQUIRED_COLUMN_NAMES.issubset(info):
        return False
    return (
        all(memory_column_is_compatible(name, info[name]) for name in MEMORY_REQUIRED_COLUMN_NAMES)
        and sole_primary_key_is_binary(conn, "memory_summaries", "id")
        and table_extensions_are_insert_compatible(
            conn,
            "memory_summaries",
            MEMORY_REQUIRED_COLUMN_NAMES,
        )
    )


def memory_column_is_compatible(name: str, info: tuple[Any, ...]) -> bool:
    contract = MEMORY_COLUMN_CONTRACTS.get(name)
    if contract is None:
        return False
    expected_type, expected_not_null, expected_default, expected_pk = contract
    if str(info[2] or "").strip().casefold() != expected_type:
        return False
    if expected_not_null is not None and bool(info[3]) != expected_not_null:
        return False
    if int(info[5] or 0) != expected_pk:
        return False
    actual_default = normalize_memory_sql_default(info[4])
    if name == "derived_authority_json":
        value = parse_sql_json_literal(actual_default)
        return any(
            memory_json_values_equal_strict(value, candidate)
            for candidate in (MINIMAL_DERIVED_MEMORY_AUTHORITY, DERIVED_MEMORY_AUTHORITY)
        )
    return actual_default == expected_default


def memory_metadata_column_is_compatible(name: str, info: tuple[Any, ...]) -> bool:
    return name in MEMORY_METADATA_COLUMNS and memory_column_is_compatible(name, info)


def normalize_memory_sql_default(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    while len(text) >= 2 and text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return None if text.casefold() == "null" else text


def parse_sql_json_literal(value: str | None) -> Any:
    if not value or len(value) < 2 or value[0] != "'" or value[-1] != "'":
        return None
    return parse_memory_metadata_json(value[1:-1].replace("''", "'"), None)


def memory_json_values_equal_strict(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            memory_json_values_equal_strict(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            memory_json_values_equal_strict(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def rebuild_memory_summaries(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    manage_projection_state: bool = True,
) -> MemoryBuildResult:
    ensure_memory_tables(conn)
    owned_generation: tuple[str, str] | None = None
    if manage_projection_state:
        if not projection_state_readable(conn):
            raise sqlite3.OperationalError(
                "projection_state schema contract is incompatible"
            )
        expected_generation = projection_state_generation(conn, "memory")
        owned_generation = mark_projection_refreshing_if_unchanged(
            conn,
            "memory",
            turn_id=str(memory_meta(conn).get("current_turn_id") or "") or None,
            expected_generation=expected_generation,
        )
        if owned_generation is None:
            conn.rollback()
            raise RuntimeError("memory projection generation changed before rebuild")
        conn.commit()
    try:
        conn.execute("begin")
        now = utc_now()
        build_turn_id = str(memory_meta(conn).get("current_turn_id") or "")
        memories = build_memory_records(conn)
        conn.execute("delete from main.memory_summaries")
        for memory in memories:
            metadata = memory_summary_metadata(conn, memory, current_turn_id=build_turn_id)
            conn.execute(
                """
                insert into main.memory_summaries
                (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                 source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                 freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                 derived_authority_json, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory["id"],
                    memory["kind"],
                    memory.get("subject_id"),
                    memory["title"],
                    memory["summary"],
                    json.dumps(memory.get("key_points", []), ensure_ascii=False, sort_keys=True),
                    json.dumps(memory.get("source_event_ids", []), ensure_ascii=False, sort_keys=True),
                    json.dumps(memory.get("source_turn_ids", []), ensure_ascii=False, sort_keys=True),
                    memory.get("valid_from_turn"),
                    memory.get("valid_to_turn"),
                    metadata["summary_type"],
                    metadata["visibility_mode"],
                    metadata["freshness_status"],
                    metadata["freshness_turn_id"],
                    metadata["stale_reason"],
                    json.dumps(metadata["freshness_evidence"], ensure_ascii=False, sort_keys=True),
                    json.dumps(metadata["derived_authority"], ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
        conn.commit()
        report_path = write_memory_report(campaign, conn, check_projection=False)
        current_turn_id = str(memory_meta(conn).get("current_turn_id") or "")
        if manage_projection_state and owned_generation is not None:
            if current_turn_id and current_turn_id == build_turn_id:
                transitioned = mark_projection_clean_if_unchanged(
                    conn,
                    "memory",
                    turn_id=build_turn_id,
                    expected_generation=owned_generation,
                )
            else:
                transitioned = mark_projection_dirty_if_unchanged(
                    conn,
                    "memory",
                    turn_id=current_turn_id or None,
                    expected_generation=owned_generation,
                )
            if not transitioned:
                raise RuntimeError(
                    "memory projection generation changed during rebuild completion"
                )
            conn.commit()
    except Exception as exc:
        if conn.in_transaction:
            conn.rollback()
        if manage_projection_state and owned_generation is not None:
            try:
                mark_projection_failed_if_unchanged(
                    conn,
                    "memory",
                    error=str(exc),
                    expected_generation=owned_generation,
                )
                conn.commit()
            except sqlite3.Error:
                conn.rollback()
        raise
    by_kind: dict[str, int] = {}
    for memory in memories:
        by_kind[memory["kind"]] = by_kind.get(memory["kind"], 0) + 1
    return MemoryBuildResult(total=len(memories), by_kind=by_kind, report_path=report_path)


def memory_summary_metadata(
    conn: sqlite3.Connection,
    memory: dict[str, Any],
    *,
    current_turn_id: str | None = None,
) -> dict[str, Any]:
    kind = str(memory.get("kind") or "summary")
    source_event_ids = string_list(memory.get("source_event_ids", []))
    source_turn_ids = string_list(memory.get("source_turn_ids", []))
    subject_id = str(memory.get("subject_id") or "")
    current_turn_id = (
        str(memory_meta(conn).get("current_turn_id") or "")
        if current_turn_id is None
        else str(current_turn_id)
    )
    subject_updated_turn_id = subject_updated_turn(conn, subject_id) if subject_id else ""
    requested_freshness_turn_id = safe_memory_turn_id(memory.get("freshness_turn_id"))
    freshness_turn_id = (
        (
            requested_freshness_turn_id
            if requested_freshness_turn_id and turn_exists(conn, requested_freshness_turn_id)
            else ""
        )
        or latest_turn_id(conn, [subject_updated_turn_id, *source_turn_ids])
        or (current_turn_id if turn_exists(conn, current_turn_id) else "")
        or None
    )
    freshness_evidence = {
        "basis": "deterministic_rebuild",
        "current_turn_id": current_turn_id,
        "subject_id": subject_id or None,
        "subject_updated_turn_id": subject_updated_turn_id or None,
        "source_event_ids": source_event_ids,
        "source_turn_ids": source_turn_ids,
        "valid_from_turn": memory.get("valid_from_turn"),
        "valid_to_turn": memory.get("valid_to_turn"),
    }
    computed_visibility_mode = memory_visibility_mode(
        conn,
        {
            **memory,
            "source_event_ids": source_event_ids,
            "source_turn_ids": source_turn_ids,
            "freshness_evidence": freshness_evidence,
        },
    )
    requested_visibility_mode = str(memory.get("visibility_mode") or computed_visibility_mode)
    return {
        "summary_type": memory_summary_type(memory.get("summary_type"), kind=kind),
        "visibility_mode": (
            MAINTENANCE_VIEW
            if computed_visibility_mode == MAINTENANCE_VIEW
            else requested_visibility_mode
        ),
        "freshness_status": memory_freshness_status(memory.get("freshness_status")),
        "freshness_turn_id": freshness_turn_id,
        "stale_reason": str(memory.get("stale_reason") or ""),
        "freshness_evidence": freshness_evidence,
        "derived_authority": clamp_memory_authority(memory.get("derived_authority")),
    }


def memory_fallback_item(
    *,
    item_id: str,
    title: str,
    reason: str,
    stale_reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "kind": "memory_fallback",
        "title": title,
        "summary": "",
        "reason": reason,
        "summary_type": "deterministic_fallback",
        "visibility_mode": "player",
        "freshness_status": "fallback",
        "stale_reason": stale_reason,
        "source_event_ids_json": "[]",
        "source_turn_ids_json": "[]",
        "derived_authority_json": MEMORY_FALLBACK_AUTHORITY_JSON,
        "freshness_evidence_json": json.dumps(evidence or {}, ensure_ascii=False, sort_keys=True),
    }


def memory_projection_omissions(
    conn: sqlite3.Connection,
    *,
    view: str,
    health: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    health = health or memory_projection_health(conn)
    status = health["status"]
    if status == "clean":
        return []
    reason = f"memory projection status is {status}; using lower-quality fallback context"
    raw_last_turn_id = safe_memory_turn_id(health.get("last_turn_id"))
    resolved_last_turn_ids = (
        resolvable_memory_turn_ids(conn, [raw_last_turn_id], view=view)
        if raw_last_turn_id
        else []
    )
    evidence = {
        "projection": "memory",
        "status": status,
        "last_turn_id": resolved_last_turn_ids[0] if resolved_last_turn_ids else None,
        "has_last_error": bool(health.get("last_error")),
    }
    if can_read_hidden(view):
        last_error = safe_memory_diagnostic_text(health.get("last_error"))
        if last_error:
            evidence["last_error"] = last_error
    return [
        memory_fallback_item(
            item_id="memory:fallback:projection-status",
            title="Memory projection needs refresh",
            reason=reason,
            stale_reason=f"projection_memory_{status}",
            evidence=evidence,
        )
    ]


def memory_projection_health(conn: sqlite3.Connection) -> dict[str, Any]:
    fallback = {
        "status": "stale",
        "last_turn_id": None,
        "last_error": None,
        "updated_at": None,
    }
    if not projection_state_readable(conn):
        return fallback
    try:
        rows = conn.execute(
            """
            select name, version, last_turn_id, status, updated_at, last_error
            from main.projection_state
            where name = 'memory' collate binary
            """
        ).fetchall()
        if len(rows) != 1:
            return fallback
        row = rows[0]
        if row["name"] != "memory":
            return fallback
        status = projection_effective_status(row)
        if status not in {"clean", "dirty", "failed", "refreshing", "stale"}:
            status = "stale"
        current_turn_id = str(memory_meta(conn).get("current_turn_id") or "")
        last_turn_id = str(row["last_turn_id"] or "")
        updated_at = parse_memory_timestamp(row["updated_at"])
        if updated_at is None:
            status = "stale"
        if status == "clean" and bool(row["last_error"]):
            status = "stale"
        if status == "clean" and (
            not current_turn_id
            or last_turn_id != current_turn_id
            or not turn_exists(conn, current_turn_id)
        ):
            status = "stale"
        if status == "clean" and memory_projection_requires_refresh(conn, updated_at=updated_at):
            status = "stale"
        return {
            "status": status,
            "last_turn_id": last_turn_id or None,
            "last_error": row["last_error"],
            "updated_at": row["updated_at"] if isinstance(row["updated_at"], str) else None,
        }
    except (KeyError, OverflowError, TypeError, ValueError, sqlite3.Error):
        return fallback


def projection_state_readable(conn: sqlite3.Connection) -> bool:
    if memory_authority_temp_shadow_exists(conn):
        return False
    row = conn.execute(
        "select 1 from main.sqlite_master "
        "where type = 'table' and name = 'projection_state'"
    ).fetchone()
    if not row:
        return False
    info = table_column_info(conn, "projection_state")
    if not MEMORY_PROJECTION_SCHEMA_COLUMNS.issubset(info):
        return False
    if not sole_primary_key_is_binary(conn, "projection_state", "name"):
        return False
    for name, (expected_type, expected_not_null, expected_default, expected_pk) in (
        MEMORY_PROJECTION_COLUMN_CONTRACTS.items()
    ):
        column = info[name]
        if str(column[2] or "").strip().casefold() != expected_type:
            return False
        if expected_not_null is not None and bool(column[3]) != expected_not_null:
            return False
        if normalize_memory_sql_default(column[4]) != expected_default:
            return False
        if int(column[5] or 0) != expected_pk:
            return False
    return table_extensions_are_insert_compatible(
        conn,
        "projection_state",
        MEMORY_PROJECTION_SCHEMA_COLUMNS,
    )


def memory_projection_requires_refresh(
    conn: sqlite3.Connection,
    *,
    updated_at: datetime | None = None,
) -> bool:
    try:
        if not memory_metadata_columns_present(conn):
            return True
        migration = conn.execute(
            "select applied_at from main.schema_migrations "
            "where id = '0009_memory_summary_provenance'"
        ).fetchone()
        migration_at = parse_memory_timestamp(migration["applied_at"]) if migration else None
        if migration_at is None or updated_at is None:
            return not memory_rows_have_trusted_provenance(conn)
        if migration_at <= updated_at:
            return False
        return not memory_rows_have_trusted_provenance(conn)
    except (KeyError, TypeError, ValueError, sqlite3.Error):
        return True


def memory_rows_have_trusted_provenance(conn: sqlite3.Connection) -> bool:
    cursor = conn.execute(
        "select * from main.memory_summaries"
    )
    seen = False
    while rows := cursor.fetchmany(128):
        for row in rows:
            seen = True
            if not memory_row_structure_is_valid(row):
                return False
            evidence = parse_memory_metadata_json(
                row["freshness_evidence_json"],
                INVALID_MEMORY_METADATA,
            )
            authority = parse_memory_metadata_json(
                row["derived_authority_json"],
                INVALID_MEMORY_METADATA,
            )
            source_events = parse_memory_metadata_json(
                row["source_event_ids_json"],
                INVALID_MEMORY_METADATA,
            )
            source_turns = parse_memory_metadata_json(
                row["source_turn_ids_json"],
                INVALID_MEMORY_METADATA,
            )
            if not (
                isinstance(evidence, dict)
                and evidence.get("basis") == "deterministic_rebuild"
                and memory_json_values_equal_strict(
                    authority,
                    DERIVED_MEMORY_AUTHORITY,
                )
                and str(row["summary_type"] or "") in MEMORY_SUMMARY_TYPES - {"unknown"}
                and str(row["visibility_mode"] or "") in {"player", MAINTENANCE_VIEW}
                and str(row["freshness_status"] or "") in MEMORY_FRESHNESS_STATUSES
                and isinstance(source_events, list)
                and all(isinstance(item, str) and safe_memory_event_id(item) == item for item in source_events)
                and isinstance(source_turns, list)
                and all(isinstance(item, str) and safe_memory_turn_id(item) == item for item in source_turns)
            ):
                return False
            freshness_turn_id = row["freshness_turn_id"]
            if freshness_turn_id is not None and safe_memory_turn_id(freshness_turn_id) != freshness_turn_id:
                return False
            references = memory_row_provenance_references(
                conn,
                row,
                view=MAINTENANCE_VIEW,
            )
            if references is None or not memory_turn_ids_are_current_or_older(
                conn,
                references["turn_ids"],
            ):
                return False
            row_subject_id = str(row["subject_id"] or "")
            evidence_subject_id = str(evidence.get("subject_id") or "")
            if row_subject_id != evidence_subject_id:
                return False
            if row_subject_id and not conn.execute(
                "select 1 from main.entities where id = ?",
                (row_subject_id,),
            ).fetchone():
                return False
            if (
                str(row["visibility_mode"] or "") == "player"
                and (
                    (row_subject_id and not subject_is_player_visible(conn, row_subject_id))
                    or memory_row_has_hidden_refs(conn, row)
                )
            ):
                return False
            if memory_row_freshness(
                conn,
                row,
                view=MAINTENANCE_VIEW,
                check_projection=False,
            )["status"] == "stale":
                return False
    return seen


def safe_memory_diagnostic_text(value: Any, *, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.splitlines()).strip()[:limit]


def subject_updated_turn(conn: sqlite3.Connection, subject_id: str) -> str:
    if not subject_id:
        return ""
    row = conn.execute(
        "select updated_turn_id from main.entities where id = ?",
        (subject_id,),
    ).fetchone()
    return str(row["updated_turn_id"] or "") if row else ""


def latest_turn_id(conn: sqlite3.Connection, turn_ids: list[str]) -> str:
    ids = safe_memory_id_list(turn_ids, safe_memory_turn_id)
    if not ids:
        return ""
    candidates: list[tuple[datetime, str]] = []
    for turn_chunk in chunks(ids, 64):
        placeholders = ",".join("?" for _ in turn_chunk)
        rows = conn.execute(
            f"""
            select id, created_at
            from main.turns
            where id in ({placeholders})
            """,
            turn_chunk,
        ).fetchall()
        for row in rows:
            created_at = parse_memory_timestamp(row["created_at"])
            if created_at is not None:
                candidates.append((created_at, str(row["id"])))
    return max(candidates)[1] if candidates else ""


def turn_exists(conn: sqlite3.Connection, turn_id: str) -> bool:
    safe_turn_id = safe_memory_turn_id(turn_id)
    if not safe_turn_id:
        return False
    return bool(
        conn.execute(
            "select 1 from main.turns where id = ?",
            (safe_turn_id,),
        ).fetchone()
    )


def memory_visibility_mode(conn: sqlite3.Connection, memory: dict[str, Any]) -> str:
    subject_id = str(memory.get("subject_id") or "")
    if subject_id and not subject_is_player_visible(conn, subject_id):
        return MAINTENANCE_VIEW
    if memory_record_has_hidden_refs(conn, memory):
        return MAINTENANCE_VIEW
    return "player"


def subject_is_player_visible(conn: sqlite3.Connection, subject_id: str) -> bool:
    ensure_visibility_sql_functions(conn)
    row = conn.execute(
        f"""
        select e.id
        from main.entities e
        left join main.clocks c on c.entity_id = e.id
        where e.id = ?
          and {entity_not_archived_sql("e")}
          {entity_visibility_sql("player", "e")}
          {entity_subtype_visibility_sql("player", "e", "c")}
        """,
        (subject_id,),
    ).fetchone()
    return bool(row)


def memory_record_has_hidden_refs(conn: sqlite3.Connection, memory: dict[str, Any]) -> bool:
    source_event_ids = string_list(memory.get("source_event_ids", []))
    source_turn_ids = string_list(memory.get("source_turn_ids", []))
    freshness_evidence = memory.get("freshness_evidence", {})
    if isinstance(freshness_evidence, dict):
        source_event_ids.extend(string_list(freshness_evidence.get("source_event_ids", [])))
        source_turn_ids.extend(string_list(freshness_evidence.get("source_turn_ids", [])))
        source_turn_ids.extend(memory_freshness_reference_turn_ids(freshness_evidence))
    payload = {
        "title": memory.get("title"),
        "summary": memory.get("summary"),
        "key_points": memory.get("key_points", []),
        "source_event_ids": source_event_ids,
        "source_turn_ids": source_turn_ids,
        "valid_from_turn": memory.get("valid_from_turn"),
        "valid_to_turn": memory.get("valid_to_turn"),
        "freshness_evidence": freshness_evidence,
    }
    source_turn_ids.extend(string_list(memory.get("valid_from_turn")))
    source_turn_ids.extend(string_list(memory.get("valid_to_turn")))
    source_turn_ids.extend(string_list(memory.get("freshness_turn_id")))
    identifiers = {
        "id": memory.get("id"),
        "subject_id": memory.get("subject_id"),
    }
    return (
        bool(find_hidden_entity_ref_tokens(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, identifiers))
        or memory_source_rows_have_hidden_refs(conn, event_ids=source_event_ids, turn_ids=source_turn_ids)
    )


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if value is None:
        return []
    return [str(value)] if str(value) else []


def memory_freshness_reference_turn_ids(evidence: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in (
        "current_turn_id",
        "last_turn_id",
        "subject_updated_turn_id",
        "valid_from_turn",
        "valid_to_turn",
    ):
        ids.extend(string_list(evidence.get(key)))
    return ids


def parse_memory_metadata_json(text: Any, default: Any) -> Any:
    if not isinstance(text, str) or not text or len(text) > MAX_MEMORY_METADATA_JSON_CHARS:
        return default
    try:
        value = json.loads(text, parse_constant=reject_nonfinite_json_constant)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return default
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_MEMORY_METADATA_JSON_NODES or depth > MAX_MEMORY_METADATA_JSON_DEPTH:
            return default
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def reject_nonfinite_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def memory_metadata_json_is_valid(text: Any, *, expected_type: type) -> bool:
    value = parse_memory_metadata_json(text, INVALID_MEMORY_METADATA)
    return value is not INVALID_MEMORY_METADATA and isinstance(value, expected_type)


def parse_memory_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def build_memory_records(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if memory_authority_temp_shadow_exists(conn):
        raise sqlite3.OperationalError("memory authority schema has a TEMP shadow")
    ensure_visibility_sql_functions(conn)
    projection_view = MAINTENANCE_VIEW
    memories: list[dict[str, Any]] = []
    memories.extend(build_day_memories(conn, view=projection_view))
    memories.extend(build_world_memories(conn, view=projection_view))
    memories.extend(build_character_memories(conn, view=projection_view))
    memories.extend(build_project_memories(conn, view=projection_view))
    memories.extend(build_faction_memories(conn, view=projection_view))
    return memories


def build_day_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    meta = memory_meta(conn)
    fallback_day = str(meta.get("current_game_day") or "unknown")
    rows = recent_memory_events(conn, limit=80)
    by_day: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        day = parse_day(row["game_time"]) or fallback_day
        by_day.setdefault(day, []).append(row)
    memories: list[dict[str, Any]] = []
    for day, events in sorted(by_day.items(), key=lambda item: item[0]):
        if not events:
            continue
        ordered = sorted(events, key=lambda row: row["id"])
        history_rows = [row for row in ordered if row["type"] == "history_reconstruction"]
        if history_rows:
            selected = history_rows[-2:]
            non_history = [row for row in ordered if row["type"] != "history_reconstruction"][-4:]
            points = history_points(conn, selected, view=view)
            points.extend(event_point(row, conn, view=view) for row in non_history)
            source_rows = [*selected, *non_history]
        else:
            source_rows = ordered[-12:]
            points = [event_point(row, conn, view=view) for row in ordered[-8:]]
        memories.append(
            {
                "id": f"summary:day-{safe_id(day).zfill(3) if day.isdigit() else safe_id(day)}",
                "kind": "day",
                "title": f"第{day}天摘要" if day.isdigit() else f"{day} 摘要",
                "summary": trim_join(points[:3], "；", 260),
                "key_points": points,
                "source_event_ids": [row["id"] for row in source_rows],
                "source_turn_ids": dedupe([row["turn_id"] for row in source_rows]),
                "valid_from_turn": ordered[0]["turn_id"],
            }
        )
    return memories


def build_world_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    meta = memory_meta(conn)
    should_redact = not can_read_hidden(view)
    clock_public_clause = f"and {normalized_text_sql('c.visibility')} in ('visible', 'hinted')" if should_redact else ""
    entity_visibility_clause = entity_visibility_sql(view, "e")
    clock_visibility_clause = clock_visibility_sql(view, "c")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    clocks = conn.execute(
        f"""
        select e.id, e.name, e.summary, c.segments_filled, c.segments_total, c.visibility, c.trigger_when_full
        from main.clocks c
        join main.entities e on e.id = c.entity_id
        where {entity_not_archived_sql("e")}
          {clock_public_clause}
          {entity_visibility_clause}
          {clock_visibility_clause}
          {subtype_visibility_clause}
        order by c.visibility, e.name
        limit 8
        """
    ).fetchall()
    points = [
        f"当前时间：{format_time_brief(meta)}",
        f"当前天气：{format_weather_brief(meta)}",
        f"当前位置：{current_world_location_label(conn, meta, view=view)}",
    ]
    for row in clocks:
        clock_text = str(row["summary"] or row["trigger_when_full"] or "")
        if should_redact:
            clock_text = redact_hidden_entity_refs(conn, clock_text) or ""
        points.append(f"{row['name']} {row['segments_filled']}/{row['segments_total']}：{clock_text}")
    return [
        {
            "id": "summary:current-world",
            "kind": "world",
            "title": "当前世界压力摘要",
            "summary": trim_join(points[:4], "；", 260),
            "key_points": points,
            "source_event_ids": [],
            "source_turn_ids": [],
        }
    ]


def current_world_location_label(conn: sqlite3.Connection, meta: dict[str, str], *, view: str = "player") -> str:
    location_id = meta.get("current_location_id", "")
    if not location_id:
        return "未知"
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    row = conn.execute(
        f"""
        select e.id, e.name
        from main.entities e
        left join main.clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
        """,
        (location_id,),
    ).fetchone()
    return f"{row['id']} {row['name']}" if row else "当前地点不可见或不存在"


def build_character_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    player_entity_id = memory_player_entity_id(conn)
    should_redact = not can_read_hidden(view)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*, c.role, c.attitude, c.trust, c.health_state, c.goals_json, c.knowledge_json
        from main.characters c
        join main.entities e on e.id = c.entity_id
        where {normalized_text_sql("e.status")} = 'active'
          {visibility_clause}
          and e.id != ?
        order by c.trust desc, e.name
        limit 20
        """,
        (player_entity_id,),
    ).fetchall()
    memories: list[dict[str, Any]] = []
    for row in rows:
        events = related_events_for_subject(conn, row["id"], row["name"], limit=5)
        goals = parse_json(row["goals_json"], [])
        row_summary = str(row["summary"] or "")
        if should_redact:
            goals = redact_hidden_entity_refs(conn, goals) or []
            row_summary = redact_hidden_entity_refs(conn, row_summary) or ""
        points = [
            f"角色：{row['role'] or '未知'}",
            f"态度/信任：{row['attitude'] or '未知'} / {row['trust']}",
            f"健康：{row['health_state'] or '未知'}",
            f"摘要：{row_summary}",
        ]
        points.extend(f"目标：{goal}" for goal in as_text_list(goals)[:3])
        points.extend(event_point(event, conn, view=view) for event in events[:3])
        memories.append(
            {
                "id": f"reflection:character:{row['id'].replace(':', '-')}",
                "kind": "character",
                "subject_id": row["id"],
                "title": f"{row['name']} 长期状态",
                "summary": trim_join(points[:4], "；", 260),
                "key_points": points,
                "source_event_ids": [event["id"] for event in events],
                "source_turn_ids": dedupe([event["turn_id"] for event in events]),
            }
        )
    return memories


def build_project_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    should_redact = not can_read_hidden(view)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*
        from main.entities e
        where {normalized_text_sql("e.status")} = 'active'
          and e.type = 'project'
          {visibility_clause}
        order by e.name
        limit 30
        """
    ).fetchall()
    memories: list[dict[str, Any]] = []
    for row in rows:
        events = related_events_for_subject(conn, row["id"], row["name"], limit=5)
        details = parse_json(row["details_json"], {})
        row_summary = str(row["summary"] or "")
        if should_redact:
            details = redact_hidden_entity_refs(conn, details) or {}
            row_summary = redact_hidden_entity_refs(conn, row_summary) or ""
        points = [f"摘要：{row_summary}"]
        for key in ["status", "next_steps", "risks", "linked_entities"]:
            if key in details:
                points.append(f"{key}: {format_memory_value(details[key])}")
        points.extend(event_point(event, conn, view=view) for event in events[:3])
        memories.append(
            {
                "id": f"reflection:project:{row['id'].replace(':', '-')}",
                "kind": "project",
                "subject_id": row["id"],
                "title": f"{row['name']} 项目摘要",
                "summary": trim_join(points[:3], "；", 260),
                "key_points": points,
                "source_event_ids": [event["id"] for event in events],
                "source_turn_ids": dedupe([event["turn_id"] for event in events]),
            }
        )
    return memories


def build_faction_memories(conn: sqlite3.Connection, *, view: str = "player") -> list[dict[str, Any]]:
    ensure_visibility_sql_functions(conn)
    should_redact = not can_read_hidden(view)
    visibility_clause = entity_visibility_sql(view, "e")
    rows = conn.execute(
        f"""
        select e.*
        from main.entities e
        where {normalized_text_sql("e.status")} = 'active'
          and e.type in ('faction', 'faction_state', 'species')
          {visibility_clause}
        order by e.type, e.name
        limit 20
        """
    ).fetchall()
    memories: list[dict[str, Any]] = []
    for row in rows:
        events = related_events_for_subject(conn, row["id"], row["name"], limit=5)
        details = parse_json(row["details_json"], {})
        if should_redact:
            details = redact_hidden_entity_refs(conn, details) or {}
        profile = details.get("profile") or details.get("encyclopedia") or details
        row_summary = str(row["summary"] or "")
        if should_redact:
            row_summary = redact_hidden_entity_refs(conn, row_summary) or ""
        points = [f"摘要：{row_summary}"]
        if isinstance(profile, dict):
            for key, value in list(profile.items())[:4]:
                points.append(f"{key}: {format_memory_value(value)}")
        points.extend(event_point(event, conn, view=view) for event in events[:3])
        memories.append(
            {
                "id": f"reflection:faction:{row['id'].replace(':', '-')}",
                "kind": "faction",
                "subject_id": row["id"],
                "title": f"{row['name']} 势力/族群反思",
                "summary": trim_join(points[:3], "；", 260),
                "key_points": points,
                "source_event_ids": [event["id"] for event in events],
                "source_turn_ids": dedupe([event["turn_id"] for event in events]),
            }
        )
    return memories


def recent_memory_events(conn: sqlite3.Connection, *, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from main.events
        where type not in ('import', 'campaign_seeded')
          and id != 'event:seed'
        order by created_at desc, id desc
        limit ?
        """,
        (limit,),
    ).fetchall()


def related_events_for_subject(conn: sqlite3.Connection, subject_id: str, name: str, *, limit: int) -> list[sqlite3.Row]:
    like_id = f"%{subject_id}%"
    like_name = f"%{name}%"
    return conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from main.events
        where payload_json like ?
           or summary like ?
           or title like ?
        order by created_at desc, id desc
        limit ?
        """,
        (like_id, like_name, like_name, limit),
    ).fetchall()


def find_relevant_memories(
    conn: sqlite3.Connection,
    *,
    targets: list[str],
    limit: int = 4,
    view: str = "player",
) -> list[sqlite3.Row]:
    limit = bounded_memory_query_limit(limit)
    if limit <= 0:
        return []
    try:
        return _find_relevant_memories(conn, targets=targets, limit=limit, view=view)
    except (OverflowError, RecursionError, TypeError, ValueError, sqlite3.Error):
        return []


def _find_relevant_memories(
    conn: sqlite3.Connection,
    *,
    targets: list[str],
    limit: int,
    view: str,
) -> list[sqlite3.Row]:
    if not memory_metadata_columns_present(conn):
        return []
    projection_health = memory_projection_health(conn)
    projection_status = str(projection_health["status"])
    if projection_status != "clean":
        return []
    projection_snapshot = memory_projection_snapshot(conn, projection_health)
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    clauses = ["m.kind in ('world', 'day')"]
    params: list[str] = []
    for target in targets[:16]:
        if not target:
            continue
        clauses.append("(m.subject_id = ? or m.title like ? or m.summary like ? or m.key_points_json like ?)")
        like = f"%{target}%"
        params.extend([target, like, like, like])
    rows = find_visible_relevant_memory_rows(
        conn,
        clauses=clauses,
        params=params,
        limit=limit,
        view=view,
        visibility_clause=visibility_clause,
        subtype_visibility_clause=subtype_visibility_clause,
        projection_status=projection_status,
    )
    return rows if memory_projection_snapshot_change(conn, projection_snapshot) is None else []


def find_omitted_relevant_memories(
    conn: sqlite3.Connection,
    *,
    targets: list[str],
    limit: int = 4,
    view: str = "player",
) -> list[dict[str, Any]]:
    limit = bounded_memory_query_limit(limit)
    if limit <= 0:
        return []
    try:
        return _find_omitted_relevant_memories(conn, targets=targets, limit=limit, view=view)
    except (OverflowError, RecursionError, TypeError, ValueError, sqlite3.Error):
        return [
            memory_fallback_item(
                item_id="memory:fallback:read-error",
                title="Memory summaries unavailable",
                reason="memory summary data could not be verified; using lower-quality fallback context",
                stale_reason="missing_memory_metadata_columns",
            )
        ][:limit]


def bounded_memory_query_limit(value: Any) -> int:
    try:
        return max(0, min(int(value), MAX_MEMORY_QUERY_LIMIT))
    except (OverflowError, TypeError, ValueError):
        return 0


def _find_omitted_relevant_memories(
    conn: sqlite3.Connection,
    *,
    targets: list[str],
    limit: int,
    view: str,
) -> list[dict[str, Any]]:
    if not memory_table_exists(conn):
        return [
            memory_fallback_item(
                item_id="memory:fallback:missing-table",
                title="Memory summaries unavailable",
                reason="memory_summaries table is unavailable; using lower-quality fallback context",
                stale_reason="missing_memory_table",
            )
        ]
    if not memory_metadata_columns_present(conn):
        return [
            memory_fallback_item(
                item_id="memory:fallback:missing-metadata-columns",
                title="Memory summary metadata unavailable",
                reason="memory_summaries is missing required schema columns; using lower-quality fallback context",
                stale_reason="missing_memory_metadata_columns",
                evidence={
                    "missing_columns": sorted(
                        MEMORY_REQUIRED_COLUMN_NAMES - table_columns(conn, "memory_summaries")
                    )
                },
            )
        ]
    projection_health = memory_projection_health(conn)
    projection_snapshot = memory_projection_snapshot(conn, projection_health)
    omitted: list[dict[str, Any]] = memory_projection_omissions(
        conn,
        view=view,
        health=projection_health,
    )
    if projection_health["status"] != "clean" or len(omitted) >= limit:
        return omitted[:limit]
    if int(
        conn.execute("select count(*) from main.memory_summaries").fetchone()[0] or 0
    ) == 0:
        omitted.append(memory_empty_or_hidden_fallback(view=view, empty=True))
        changed_health = memory_projection_snapshot_change(conn, projection_snapshot)
        if changed_health is not None:
            return memory_projection_change_omissions(
                conn,
                view=view,
                health=changed_health,
                limit=limit,
            )
        return omitted[:limit]
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    clauses = ["m.kind in ('world', 'day')"]
    params: list[str] = []
    for target in targets[:16]:
        if not target:
            continue
        clauses.append("(m.subject_id = ? or m.title like ? or m.summary like ? or m.key_points_json like ?)")
        like = f"%{target}%"
        params.extend([target, like, like, like])
    page_size = max(limit * 4, 24)
    offset = 0
    visible_relevant_found = False
    while len(omitted) < limit and offset < MAX_MEMORY_ROWS_SCANNED:
        page_limit = min(page_size, MAX_MEMORY_ROWS_SCANNED - offset)
        rows = conn.execute(
            f"""
            select m.*
            from main.memory_summaries m
            left join main.entities e on e.id = m.subject_id
            left join main.clocks c on c.entity_id = e.id
            where (e.id is null or (1=1 {visibility_clause} {subtype_visibility_clause}))
              and ({' or '.join(clauses)})
            order by
              case m.kind
                when 'world' then 0
                when 'character' then 1
                when 'project' then 2
                when 'faction' then 3
                when 'day' then 4
                else 5
              end,
              m.updated_at desc,
              m.id
            limit ? offset ?
            """,
            [*params, page_limit, offset],
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            if not memory_row_structure_is_valid(row):
                if can_read_hidden(view):
                    visible_relevant_found = True
                    omitted.append(
                        memory_fallback_item(
                            item_id="memory:fallback:invalid-row",
                            title="Invalid memory summary",
                            reason=(
                                "memory summary row failed the structural contract; "
                                "using lower-quality fallback context"
                            ),
                            stale_reason="invalid_memory_row",
                        )
                    )
                    if len(omitted) >= limit:
                        break
                continue
            if not memory_row_visible_for_view(conn, row, view=view):
                continue
            visible_relevant_found = True
            freshness = memory_row_freshness(
                conn,
                row,
                view=view,
                projection_status="clean",
            )
            if freshness["status"] != "stale":
                continue
            safe = redact_memory_row_for_view(conn, row, view=view)
            safe["freshness_status"] = freshness["status"]
            safe["stale_reason"] = (
                freshness["reason"]
                if can_read_hidden(view)
                else player_safe_memory_reason(freshness["reason"])
            )
            omitted.append(safe)
            if len(omitted) >= limit:
                break
    if not visible_relevant_found and not can_read_hidden(view) and len(omitted) < limit:
        omitted.append(memory_empty_or_hidden_fallback(view=view, empty=False))
    changed_health = memory_projection_snapshot_change(conn, projection_snapshot)
    if changed_health is not None:
        return memory_projection_change_omissions(
            conn,
            view=view,
            health=changed_health,
            limit=limit,
        )
    return omitted[:limit]


def memory_projection_snapshot(
    conn: sqlite3.Connection,
    health: dict[str, Any],
) -> tuple[str, str, str, str]:
    return (
        str(health.get("status") or "stale"),
        str(health.get("last_turn_id") or ""),
        str(memory_meta(conn).get("current_turn_id") or ""),
        str(health.get("updated_at") or ""),
    )


def memory_projection_snapshot_change(
    conn: sqlite3.Connection,
    snapshot: tuple[str, str, str, str],
) -> dict[str, Any] | None:
    health = memory_projection_health(conn)
    return None if memory_projection_snapshot(conn, health) == snapshot else health


def memory_projection_change_omissions(
    conn: sqlite3.Connection,
    *,
    view: str,
    health: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    if str(health.get("status")) == "clean":
        health = {
            "status": "stale",
            "last_turn_id": health.get("last_turn_id"),
            "last_error": None,
        }
    return memory_projection_omissions(conn, view=view, health=health)[:limit]


def memory_empty_or_hidden_fallback(*, view: str, empty: bool) -> dict[str, Any]:
    if can_read_hidden(view) and empty:
        return memory_fallback_item(
            item_id="memory:fallback:empty-table",
            title="Memory summaries unavailable",
            reason="memory_summaries table is empty; using lower-quality fallback context",
            stale_reason="empty_memory_table",
        )
    return memory_fallback_item(
        item_id="memory:fallback:unavailable",
        title="Memory summaries unavailable",
        reason="memory summaries are unavailable for this context; using lower-quality fallback context",
        stale_reason="memory_summary_omitted",
    )


def find_visible_relevant_memory_rows(
    conn: sqlite3.Connection,
    *,
    clauses: list[str],
    params: list[str],
    limit: int,
    view: str,
    visibility_clause: str,
    subtype_visibility_clause: str,
    projection_status: str,
) -> list[sqlite3.Row]:
    if limit <= 0:
        return []
    page_size = max(limit * 4, limit + 12)
    offset = 0
    result: list[sqlite3.Row] = []
    while len(result) < limit and offset < MAX_MEMORY_ROWS_SCANNED:
        page_limit = min(page_size, MAX_MEMORY_ROWS_SCANNED - offset)
        rows = conn.execute(
            f"""
            select m.*
            from main.memory_summaries m
            left join main.entities e on e.id = m.subject_id
            left join main.clocks c on c.entity_id = e.id
            where (e.id is null or ({entity_not_archived_sql("e")} {visibility_clause} {subtype_visibility_clause}))
              and ({' or '.join(clauses)})
            order by
              case m.kind
                when 'world' then 0
                when 'character' then 1
                when 'project' then 2
                when 'faction' then 3
                when 'day' then 4
                else 5
              end,
              m.updated_at desc,
              m.id
            limit ? offset ?
            """,
            [*params, page_limit, offset],
        ).fetchall()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            if not memory_row_visible_for_view(conn, row, view=view):
                continue
            if memory_row_freshness(
                conn,
                row,
                view=view,
                projection_status=projection_status,
            )["status"] == "stale":
                continue
            result.append(redact_memory_row_for_view(conn, row, view=view))
            if len(result) >= limit:
                break
    return result[:limit]


def memory_row_visible_for_view(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any], *, view: str) -> bool:
    if not memory_row_structure_is_valid(row):
        return False
    if can_read_hidden(view):
        return True
    visibility_mode = str(row_value(row, "visibility_mode", "") or "").strip().lower()
    if visibility_mode != "player":
        return False
    subject_id = str(row_value(row, "subject_id", "") or "")
    if subject_id and not subject_is_player_visible(conn, subject_id):
        return False
    return not memory_row_has_hidden_refs(conn, row)


def memory_row_structure_is_valid(row: sqlite3.Row | dict[str, Any]) -> bool:
    if safe_memory_summary_id(row_value(row, "id", None)) is None:
        return False
    text_fields = (
        "kind",
        "title",
        "summary",
        "summary_type",
        "visibility_mode",
        "freshness_status",
        "stale_reason",
        "updated_at",
    )
    if any(not isinstance(row_value(row, key, None), str) for key in text_fields):
        return False
    subject_id = row_value(row, "subject_id", None)
    if subject_id not in (None, "") and safe_memory_entity_id(subject_id) != subject_id:
        return False
    if parse_memory_timestamp(row_value(row, "updated_at", None)) is None:
        return False
    if not memory_metadata_json_is_valid(
        row_value(row, "key_points_json", None),
        expected_type=list,
    ):
        return False
    if canonical_memory_json_id_list(
        row_value(row, "source_event_ids_json", None),
        safe_memory_event_id,
    ) is None:
        return False
    if canonical_memory_json_id_list(
        row_value(row, "source_turn_ids_json", None),
        safe_memory_turn_id,
    ) is None:
        return False
    evidence = parse_memory_metadata_json(
        row_value(row, "freshness_evidence_json", None),
        INVALID_MEMORY_METADATA,
    )
    if canonical_memory_evidence_references(evidence) is None:
        return False
    if not memory_metadata_json_is_valid(
        row_value(row, "derived_authority_json", None),
        expected_type=dict,
    ):
        return False
    for key in ("valid_from_turn", "valid_to_turn", "freshness_turn_id"):
        value = row_value(row, key, None)
        if value not in (None, "") and safe_memory_turn_id(value) != value:
            return False
    return True


def memory_row_freshness(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
    *,
    view: str,
    check_projection: bool = True,
    projection_status: str | None = None,
) -> dict[str, str]:
    stored_status = memory_freshness_status(
        row_value(row, "freshness_status", "stale"),
        default="stale",
    )
    stored_reason = str(row_value(row, "stale_reason", "") or "")
    if stored_status == "stale" or stored_reason:
        return {"status": "stale", "reason": stored_reason or "stored_stale"}
    validity_reason = memory_row_validity_stale_reason(conn, row)
    if validity_reason:
        return {"status": "stale", "reason": validity_reason}
    subject_id = str(row_value(row, "subject_id", "") or "")
    subject: sqlite3.Row | None = None
    updated_turn_id = ""
    if subject_id:
        subject = conn.execute(
            "select id, status, visibility, updated_turn_id "
            "from main.entities where id = ?",
            (subject_id,),
        ).fetchone()
        if not subject:
            return {"status": "stale", "reason": "missing_subject"}
        if str(subject["status"] or "").lower() == "archived":
            return {"status": "stale", "reason": "subject_archived"}
        if not can_read_hidden(view) and not subject_is_player_visible(conn, subject_id):
            return {"status": "stale", "reason": "subject_hidden_unavailable"}
        updated_turn_id = str(subject["updated_turn_id"] or "")
        if not safe_memory_turn_id(updated_turn_id) or not turn_exists(
            conn,
            updated_turn_id,
        ):
            return {"status": "stale", "reason": "missing_freshness_evidence"}
    references = memory_row_provenance_references(conn, row, view=view)
    if references is None:
        return {"status": "stale", "reason": "missing_freshness_evidence"}
    if not memory_turn_ids_are_current_or_older(conn, references["turn_ids"]):
        return {"status": "stale", "reason": "missing_freshness_evidence"}
    freshness_turn_id = latest_turn_id(conn, references["turn_ids"])
    if not subject_id:
        if not memory_row_has_freshness_evidence(conn, row):
            return {"status": "stale", "reason": "missing_freshness_evidence"}
        if check_projection:
            effective_projection_status = projection_status or str(memory_projection_health(conn)["status"])
            if effective_projection_status != "clean":
                return {"status": "stale", "reason": f"projection_memory_{effective_projection_status}"}
        return {"status": stored_status, "reason": ""}
    if freshness_turn_id:
        update_is_after = turn_is_after(conn, updated_turn_id, freshness_turn_id)
        if update_is_after is None:
            return {"status": "stale", "reason": "missing_freshness_evidence"}
        if update_is_after:
            return {"status": "stale", "reason": "subject_updated_after_summary"}
    if not freshness_turn_id:
        return {"status": "stale", "reason": "missing_freshness_evidence"}
    raw_evidence = parse_memory_metadata_json(
        row_value(row, "freshness_evidence_json", "{}"),
        INVALID_MEMORY_METADATA,
    )
    evidence_updated_turn_id = (
        raw_evidence.get("subject_updated_turn_id")
        if isinstance(raw_evidence, dict)
        else None
    )
    if evidence_updated_turn_id != updated_turn_id:
        evidence_is_older = (
            turn_is_after(conn, updated_turn_id, evidence_updated_turn_id)
            if safe_memory_turn_id(evidence_updated_turn_id)
            else None
        )
        if evidence_is_older:
            return {"status": "stale", "reason": "subject_updated_after_summary"}
        return {"status": "stale", "reason": "missing_freshness_evidence"}
    if check_projection:
        effective_projection_status = projection_status or str(memory_projection_health(conn)["status"])
        if effective_projection_status != "clean":
            return {"status": "stale", "reason": f"projection_memory_{effective_projection_status}"}
    return {"status": stored_status, "reason": ""}


def memory_row_freshness_turn_id(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
    *,
    view: str | None = None,
) -> str:
    references = memory_row_provenance_references(
        conn,
        row,
        view=view or MAINTENANCE_VIEW,
    )
    if references is None:
        return ""
    return latest_turn_id(conn, references["turn_ids"])


def memory_row_has_freshness_evidence(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
) -> bool:
    evidence = memory_row_freshness_evidence(row, conn=conn, view=MAINTENANCE_VIEW)
    return any(
        bool(evidence.get(key))
        for key in (
            "current_turn_id",
            "subject_updated_turn_id",
            "source_event_ids",
            "source_turn_ids",
        )
    )


def memory_row_validity_stale_reason(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
) -> str:
    bounds: dict[str, str | None] = {}
    for key in ("valid_from_turn", "valid_to_turn"):
        raw_value = row_value(row, key, None)
        if raw_value in (None, ""):
            bounds[key] = None
            continue
        safe_value = safe_memory_turn_id(raw_value)
        if safe_value != raw_value or not turn_exists(conn, safe_value or ""):
            return "missing_freshness_evidence"
        bounds[key] = safe_value
    raw_evidence = parse_memory_metadata_json(
        row_value(row, "freshness_evidence_json", "{}"),
        INVALID_MEMORY_METADATA,
    )
    if not isinstance(raw_evidence, dict):
        return "missing_freshness_evidence"
    for key, bound in bounds.items():
        evidence_value = raw_evidence.get(key)
        if bound is None:
            if evidence_value is not None:
                return "invalid_summary_validity_window"
            continue
        if evidence_value != bound or safe_memory_turn_id(evidence_value) != evidence_value:
            return "invalid_summary_validity_window"
    valid_from_turn = bounds["valid_from_turn"]
    valid_to_turn = bounds["valid_to_turn"]
    current_turn_id = safe_memory_turn_id(memory_meta(conn).get("current_turn_id"))
    if not current_turn_id or not turn_exists(conn, current_turn_id):
        return "missing_freshness_evidence"
    if valid_from_turn and valid_to_turn:
        starts_after_end = turn_is_after(conn, valid_from_turn, valid_to_turn)
        if starts_after_end is not False:
            return "invalid_summary_validity_window"
    if valid_from_turn:
        starts_after_current = turn_is_after(conn, valid_from_turn, current_turn_id)
        if starts_after_current is not False:
            return "summary_not_yet_valid"
    if valid_to_turn:
        current_after_end = turn_is_after(conn, current_turn_id, valid_to_turn)
        if current_after_end is not False:
            return "summary_validity_expired"
    return ""


def turn_is_after(
    conn: sqlite3.Connection,
    candidate_turn_id: str,
    reference_turn_id: str,
) -> bool | None:
    candidate_turn_id = safe_memory_turn_id(candidate_turn_id) or ""
    reference_turn_id = safe_memory_turn_id(reference_turn_id) or ""
    if not candidate_turn_id or not reference_turn_id:
        return None
    if candidate_turn_id == reference_turn_id:
        return False
    rows = conn.execute(
        """
        select id, created_at
        from main.turns
        where id in (?, ?)
        """,
        (candidate_turn_id, reference_turn_id),
    ).fetchall()
    values = {
        str(row["id"]): parse_memory_timestamp(row["created_at"])
        for row in rows
    }
    if candidate_turn_id not in values or reference_turn_id not in values:
        return None
    candidate_created = values[candidate_turn_id]
    reference_created = values[reference_turn_id]
    if candidate_created is None or reference_created is None:
        return None
    return (candidate_created, candidate_turn_id) > (
        reference_created,
        reference_turn_id,
    )


def memory_row_source_event_ids(
    row: sqlite3.Row | dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    view: str = MAINTENANCE_VIEW,
) -> list[str]:
    value = parse_memory_metadata_json(row_value(row, "source_event_ids_json", "[]"), [])
    ids = safe_memory_id_list(value, safe_memory_event_id)
    return resolvable_memory_event_ids(conn, ids, view=view) if conn is not None else ids


def memory_row_source_turn_ids(
    row: sqlite3.Row | dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    view: str = MAINTENANCE_VIEW,
) -> list[str]:
    value = parse_memory_metadata_json(row_value(row, "source_turn_ids_json", "[]"), [])
    ids = safe_memory_id_list(value, safe_memory_turn_id)
    return resolvable_memory_turn_ids(conn, ids, view=view) if conn is not None else ids


def memory_row_source_event_turn_ids(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
) -> list[str]:
    event_ids = canonical_memory_json_id_list(
        row_value(row, "source_event_ids_json", "[]"),
        safe_memory_event_id,
    )
    if event_ids is None:
        return []
    return resolve_memory_event_turn_ids(conn, event_ids) or []


def memory_freshness_turn_is_current_or_older(conn: sqlite3.Connection, turn_id: str) -> bool:
    current_turn_id = safe_memory_turn_id(memory_meta(conn).get("current_turn_id"))
    if not current_turn_id or not turn_exists(conn, current_turn_id):
        return False
    is_future = turn_is_after(conn, turn_id, current_turn_id)
    return is_future is False


def memory_turn_ids_are_current_or_older(conn: sqlite3.Connection, turn_ids: list[str]) -> bool:
    current_turn_id = safe_memory_turn_id(memory_meta(conn).get("current_turn_id"))
    ids = safe_memory_id_list([*turn_ids, current_turn_id or ""], safe_memory_turn_id)
    if not current_turn_id or len(ids) != len(dedupe([*turn_ids, current_turn_id])):
        return False
    values: dict[str, datetime] = {}
    try:
        for turn_chunk in chunks(ids, 64):
            placeholders = ",".join("?" for _ in turn_chunk)
            rows = conn.execute(
                f"select id, created_at from main.turns where id in ({placeholders})",
                turn_chunk,
            ).fetchall()
            for row in rows:
                created_at = parse_memory_timestamp(row["created_at"])
                if not isinstance(row["id"], str) or created_at is None:
                    return False
                values[row["id"]] = created_at
    except sqlite3.Error:
        return False
    if set(values) != set(ids):
        return False
    current_order = (values[current_turn_id], current_turn_id)
    return all((values[turn_id], turn_id) <= current_order for turn_id in turn_ids)


def memory_row_authority(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return clamp_memory_authority(row_value(row, "derived_authority_json", None))


def memory_row_freshness_evidence(
    row: sqlite3.Row | dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    view: str = MAINTENANCE_VIEW,
) -> dict[str, Any]:
    value = parse_memory_metadata_json(row_value(row, "freshness_evidence_json", "{}"), {})
    if not isinstance(value, dict):
        return {}
    evidence: dict[str, Any] = {}
    for key in sorted(MEMORY_FRESHNESS_EVIDENCE_KEYS):
        if key not in value:
            continue
        sanitized = sanitize_memory_freshness_evidence_value(key, value[key])
        if sanitized is not None:
            evidence[key] = sanitized
    if conn is not None:
        resolve_memory_freshness_evidence_refs(conn, evidence, view=view)
    return evidence


def memory_row_provenance_is_resolvable(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
    *,
    view: str,
) -> bool:
    return memory_row_provenance_references(conn, row, view=view) is not None


def memory_row_provenance_references(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
    *,
    view: str,
) -> dict[str, list[str]] | None:
    source_event_ids = canonical_memory_json_id_list(
        row_value(row, "source_event_ids_json", "[]"),
        safe_memory_event_id,
    )
    source_turn_ids = canonical_memory_json_id_list(
        row_value(row, "source_turn_ids_json", "[]"),
        safe_memory_turn_id,
    )
    if source_event_ids is None or source_turn_ids is None:
        return None

    raw_evidence = parse_memory_metadata_json(
        row_value(row, "freshness_evidence_json", "{}"),
        INVALID_MEMORY_METADATA,
    )
    evidence_refs = canonical_memory_evidence_references(raw_evidence)
    if evidence_refs is None:
        return None
    row_subject_id = str(row_value(row, "subject_id", "") or "")
    evidence_subject_ids = evidence_refs["subject_ids"]
    evidence_subject_updated_turn_id = raw_evidence.get("subject_updated_turn_id")
    if row_subject_id:
        if evidence_subject_ids and evidence_subject_ids != [row_subject_id]:
            return None
        if evidence_subject_ids and (
            not isinstance(evidence_subject_updated_turn_id, str)
            or safe_memory_turn_id(evidence_subject_updated_turn_id)
            != evidence_subject_updated_turn_id
        ):
            return None
        if not evidence_subject_ids and evidence_subject_updated_turn_id not in (
            None,
            "",
        ):
            return None
    elif evidence_subject_ids or evidence_subject_updated_turn_id not in (None, ""):
        return None

    scalar_turn_ids: list[str] = []
    for key in ("freshness_turn_id",):
        raw_value = row_value(row, key, None)
        if raw_value in (None, ""):
            continue
        if not isinstance(raw_value, str) or safe_memory_turn_id(raw_value) != raw_value:
            return None
        scalar_turn_ids.append(raw_value)

    all_event_ids = dedupe([*source_event_ids, *evidence_refs["event_ids"]])
    if len(all_event_ids) > MAX_MEMORY_PROVENANCE_REFERENCES:
        return None
    if resolvable_memory_event_ids(conn, all_event_ids, view=view) != all_event_ids:
        return None
    event_turn_ids = resolve_memory_event_turn_ids(conn, all_event_ids)
    if event_turn_ids is None:
        return None

    all_turn_ids = dedupe(
        [
            *source_turn_ids,
            *scalar_turn_ids,
            *evidence_refs["turn_ids"],
            *event_turn_ids,
        ]
    )
    if len(all_event_ids) + len(all_turn_ids) > MAX_MEMORY_PROVENANCE_REFERENCES:
        return None
    if resolvable_memory_turn_ids(conn, all_turn_ids, view=view) != all_turn_ids:
        return None
    if not memory_source_turn_rows_are_verifiable(conn, all_turn_ids):
        return None
    if not memory_turn_ids_are_orderable(conn, all_turn_ids):
        return None

    if evidence_subject_ids and (
        resolvable_memory_subject_id(conn, evidence_subject_ids[0], view=view)
        != evidence_subject_ids[0]
    ):
        return None
    return {"event_ids": all_event_ids, "turn_ids": all_turn_ids}


def canonical_memory_json_id_list(
    raw_json: Any,
    sanitizer: Callable[[Any], str | None],
) -> list[str] | None:
    value = parse_memory_metadata_json(raw_json, INVALID_MEMORY_METADATA)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    if len(value) > MAX_MEMORY_PROVENANCE_REFERENCES:
        return None
    canonical = safe_memory_id_list(value, sanitizer)
    return canonical if canonical == value else None


def canonical_memory_evidence_references(raw_evidence: Any) -> dict[str, list[str]] | None:
    if not isinstance(raw_evidence, dict):
        return None
    turn_ids: list[str] = []
    validity_turn_ids: list[str] = []
    event_ids: list[str] = []
    subject_ids: list[str] = []
    for key in MEMORY_FRESHNESS_TURN_ID_KEYS:
        if key not in raw_evidence or raw_evidence[key] in (None, ""):
            continue
        value = raw_evidence[key]
        if not isinstance(value, str) or safe_memory_turn_id(value) != value:
            return None
        if key in {"valid_from_turn", "valid_to_turn"}:
            validity_turn_ids.append(value)
        else:
            turn_ids.append(value)
    for key, sanitizer, target in (
        ("source_event_ids", safe_memory_event_id, event_ids),
        ("source_turn_ids", safe_memory_turn_id, turn_ids),
    ):
        if key not in raw_evidence:
            continue
        value = raw_evidence[key]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        if len(value) > MAX_MEMORY_PROVENANCE_REFERENCES:
            return None
        canonical = safe_memory_id_list(value, sanitizer)
        if canonical != value:
            return None
        target.extend(canonical)
    if "subject_id" in raw_evidence and raw_evidence["subject_id"] not in (None, ""):
        value = raw_evidence["subject_id"]
        if not isinstance(value, str) or safe_memory_entity_id(value) != value:
            return None
        subject_ids.append(value)
    return {
        "turn_ids": dedupe(turn_ids),
        "event_ids": dedupe(event_ids),
        "subject_ids": dedupe(subject_ids),
        "validity_turn_ids": dedupe(validity_turn_ids),
    }


def resolve_memory_event_turn_ids(
    conn: sqlite3.Connection,
    event_ids: list[str],
) -> list[str] | None:
    if not event_ids:
        return []
    by_event: dict[str, str] = {}
    try:
        for event_chunk in chunks(event_ids, 64):
            placeholders = ",".join("?" for _ in event_chunk)
            rows = conn.execute(
                f"""
                select id, turn_id, title, summary, payload_json, source
                from main.events
                where id in ({placeholders})
                """,
                event_chunk,
            ).fetchall()
            for item in rows:
                event_id = item["id"]
                turn_id = item["turn_id"]
                if not all(
                    isinstance(item[key], str)
                    for key in ("id", "turn_id", "title", "summary", "payload_json", "source")
                ):
                    return None
                if safe_memory_event_id(event_id) != event_id or safe_memory_turn_id(turn_id) != turn_id:
                    return None
                if parse_memory_metadata_json(
                    item["payload_json"],
                    INVALID_MEMORY_METADATA,
                ) is INVALID_MEMORY_METADATA:
                    return None
                by_event[event_id] = turn_id
    except sqlite3.Error:
        return None
    if set(by_event) != set(event_ids):
        return None
    return dedupe([by_event[event_id] for event_id in event_ids])


def memory_source_turn_rows_are_verifiable(
    conn: sqlite3.Connection,
    turn_ids: list[str],
) -> bool:
    if not turn_ids:
        return True
    rows: list[sqlite3.Row] = []
    try:
        for turn_chunk in chunks(turn_ids, 64):
            placeholders = ",".join("?" for _ in turn_chunk)
            rows.extend(
                conn.execute(
                    f"""
                    select id, user_text, summary, intent, location_before, location_after
                    from main.turns
                    where id in ({placeholders})
                    """,
                    turn_chunk,
                ).fetchall()
            )
    except sqlite3.Error:
        return False
    return len(rows) == len(turn_ids) and all(
        isinstance(item["id"], str)
        and safe_memory_turn_id(item["id"]) == item["id"]
        and isinstance(item["user_text"], str)
        and isinstance(item["intent"], str)
        and (item["summary"] is None or isinstance(item["summary"], str))
        and memory_turn_location_is_well_formed(item["location_before"])
        and memory_turn_location_is_well_formed(item["location_after"])
        for item in rows
    )


def memory_turn_location_is_well_formed(value: Any) -> bool:
    return value in (None, "") or (
        isinstance(value, str) and safe_memory_entity_id(value) == value
    )


def memory_turn_ids_are_orderable(conn: sqlite3.Connection, turn_ids: list[str]) -> bool:
    ids = safe_memory_id_list(turn_ids, safe_memory_turn_id)
    if len(ids) != len(dedupe([item for item in turn_ids if item])):
        return False
    if not ids:
        return True
    rows: list[sqlite3.Row] = []
    try:
        for turn_chunk in chunks(ids, 64):
            placeholders = ",".join("?" for _ in turn_chunk)
            rows.extend(
                conn.execute(
                    f"select id, created_at from main.turns where id in ({placeholders})",
                    turn_chunk,
                ).fetchall()
            )
    except sqlite3.Error:
        return False
    return len(rows) == len(ids) and all(parse_memory_timestamp(row["created_at"]) is not None for row in rows)


def sanitize_memory_freshness_evidence_value(key: str, value: Any) -> Any:
    if key == "has_last_error":
        return value if isinstance(value, bool) else None
    if key in MEMORY_FRESHNESS_ENUMS:
        text = str(value or "")
        return text if text in MEMORY_FRESHNESS_ENUMS[key] else None
    if key in MEMORY_FRESHNESS_TURN_ID_KEYS:
        return safe_memory_turn_id(value)
    if key == "subject_id":
        return safe_memory_entity_id(value)
    if key == "source_event_ids":
        items = safe_memory_id_list(value, safe_memory_event_id)
        return items if items else None
    if key == "source_turn_ids":
        items = safe_memory_id_list(value, safe_memory_turn_id)
        return items if items else None
    if key == "missing_columns":
        items = dedupe([item for item in string_list(value) if item in MEMORY_REQUIRED_COLUMN_NAMES])
        return items if items else None
    return None


def resolve_memory_freshness_evidence_refs(
    conn: sqlite3.Connection,
    evidence: dict[str, Any],
    *,
    view: str,
) -> None:
    for key in MEMORY_FRESHNESS_TURN_ID_KEYS:
        if key not in evidence:
            continue
        resolved = resolvable_memory_turn_ids(conn, [str(evidence[key])], view=view)
        if resolved:
            evidence[key] = resolved[0]
        else:
            evidence.pop(key, None)
    if "source_event_ids" in evidence:
        resolved = resolvable_memory_event_ids(conn, evidence["source_event_ids"], view=view)
        if resolved:
            evidence["source_event_ids"] = resolved
        else:
            evidence.pop("source_event_ids", None)
    if "source_turn_ids" in evidence:
        resolved = resolvable_memory_turn_ids(conn, evidence["source_turn_ids"], view=view)
        if resolved:
            evidence["source_turn_ids"] = resolved
        else:
            evidence.pop("source_turn_ids", None)
    if "subject_id" in evidence:
        subject_id = resolvable_memory_subject_id(conn, evidence["subject_id"], view=view)
        if subject_id:
            evidence["subject_id"] = subject_id
        else:
            evidence.pop("subject_id", None)


def memory_freshness_status(value: Any, *, default: str = "fresh") -> str:
    fallback = str(default or "fresh").strip().lower()
    if fallback not in MEMORY_FRESHNESS_STATUSES:
        fallback = "fresh"
    status = str(value or "").strip().lower()
    return status if status in MEMORY_FRESHNESS_STATUSES else fallback


def memory_summary_type(value: Any, *, kind: Any = "") -> str:
    normalized_kind = str(kind or "").strip().lower()
    inferred = f"deterministic_{normalized_kind}"
    fallback = inferred if inferred in MEMORY_SUMMARY_TYPES else "deterministic"
    summary_type = str(value or "").strip().lower()
    if not summary_type:
        return fallback
    return summary_type if summary_type in MEMORY_SUMMARY_TYPES else "unknown"


def memory_summary_kind(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip().lower()
    return normalized if normalized in MEMORY_SUMMARY_KINDS else "unknown"


def memory_row_summary_type(row: sqlite3.Row | dict[str, Any]) -> str:
    return memory_summary_type(
        row_value(row, "summary_type", ""),
        kind=row_value(row, "kind", ""),
    )


def safe_memory_turn_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value
    return (
        text
        if len(text) <= MAX_MEMORY_IDENTIFIER_LENGTH and MEMORY_TURN_ID_PATTERN.fullmatch(text)
        else None
    )


def safe_memory_event_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value
    return (
        text
        if len(text) <= MAX_MEMORY_IDENTIFIER_LENGTH and MEMORY_EVENT_ID_PATTERN.fullmatch(text)
        else None
    )


def safe_memory_entity_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value
    return (
        text
        if len(text) <= MAX_MEMORY_IDENTIFIER_LENGTH and MEMORY_ENTITY_ID_PATTERN.fullmatch(text)
        else None
    )


def safe_memory_summary_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return (
        value
        if len(value) <= MAX_MEMORY_IDENTIFIER_LENGTH
        and MEMORY_SUMMARY_ID_PATTERN.fullmatch(value)
        else None
    )


def safe_memory_id_list(value: Any, sanitizer: Callable[[Any], str | None]) -> list[str]:
    return dedupe([safe for item in string_list(value) if (safe := sanitizer(item)) is not None])


def resolvable_memory_event_ids(
    conn: sqlite3.Connection,
    ids: list[str],
    *,
    view: str,
) -> list[str]:
    existing = existing_memory_ids(conn, "events", safe_memory_id_list(ids, safe_memory_event_id))
    if can_read_hidden(view):
        return existing
    return (
        []
        if memory_source_rows_have_hidden_refs(
            conn,
            event_ids=existing,
            turn_ids=[],
        )
        else existing
    )


def resolvable_memory_turn_ids(
    conn: sqlite3.Connection,
    ids: list[str],
    *,
    view: str,
) -> list[str]:
    existing = existing_memory_ids(conn, "turns", safe_memory_id_list(ids, safe_memory_turn_id))
    if can_read_hidden(view):
        return existing
    return (
        []
        if memory_source_rows_have_hidden_refs(
            conn,
            event_ids=[],
            turn_ids=existing,
        )
        else existing
    )


def existing_memory_ids(conn: sqlite3.Connection, table: str, ids: list[str]) -> list[str]:
    if table not in {"events", "turns"}:
        return []
    existing: set[str] = set()
    try:
        for id_chunk in chunks(dedupe(ids), 64):
            placeholders = ",".join("?" for _ in id_chunk)
            rows = conn.execute(
                f"select id from {table} where id in ({placeholders})",
                id_chunk,
            ).fetchall()
            existing.update(str(row["id"]) for row in rows)
    except sqlite3.Error:
        return []
    return [item for item in dedupe(ids) if item in existing]


def resolvable_memory_subject_id(conn: sqlite3.Connection, value: Any, *, view: str) -> str | None:
    subject_id = safe_memory_entity_id(value)
    if not subject_id:
        return None
    try:
        if not conn.execute(
            "select 1 from main.entities where id = ?",
            (subject_id,),
        ).fetchone():
            return None
        if not can_read_hidden(view) and not subject_is_player_visible(conn, subject_id):
            return None
    except sqlite3.Error:
        return None
    return subject_id


def clamp_memory_authority(value: Any) -> dict[str, Any]:
    return dict(DERIVED_MEMORY_AUTHORITY)


def player_safe_memory_reason(reason: Any) -> str:
    text = str(reason or "").strip()
    return text if text in PLAYER_SAFE_MEMORY_REASONS else "memory_summary_omitted"


def memory_row_has_hidden_refs(conn: sqlite3.Connection, row: sqlite3.Row | dict[str, Any]) -> bool:
    source_event_ids = canonical_memory_json_id_list(
        row_value(row, "source_event_ids_json", "[]"),
        safe_memory_event_id,
    )
    source_turn_ids = canonical_memory_json_id_list(
        row_value(row, "source_turn_ids_json", "[]"),
        safe_memory_turn_id,
    )
    freshness_evidence = parse_memory_metadata_json(
        row_value(row, "freshness_evidence_json", "{}"),
        INVALID_MEMORY_METADATA,
    )
    evidence_refs = canonical_memory_evidence_references(freshness_evidence)
    points = parse_memory_metadata_json(
        row_value(row, "key_points_json", "[]"),
        INVALID_MEMORY_METADATA,
    )
    if (
        source_event_ids is None
        or source_turn_ids is None
        or evidence_refs is None
        or not isinstance(points, list)
    ):
        return True
    text_fields = (
        "id",
        "kind",
        "subject_id",
        "title",
        "summary",
        "summary_type",
        "visibility_mode",
        "freshness_status",
        "stale_reason",
    )
    if any(
        row_value(row, key, None) is not None
        and not isinstance(row_value(row, key, None), str)
        for key in text_fields
    ):
        return True
    for key in ("valid_from_turn", "valid_to_turn", "freshness_turn_id"):
        value = row_value(row, key, None)
        if value in (None, ""):
            continue
        if not isinstance(value, str) or safe_memory_turn_id(value) != value:
            return True
        source_turn_ids.append(value)
    source_event_ids = dedupe([*source_event_ids, *evidence_refs["event_ids"]])
    source_turn_ids = dedupe(
        [
            *source_turn_ids,
            *evidence_refs["turn_ids"],
            *evidence_refs["validity_turn_ids"],
        ]
    )
    payload = {
        "kind": row_value(row, "kind", ""),
        "title": row_value(row, "title", ""),
        "summary": row_value(row, "summary", ""),
        "key_points": points,
        "summary_type": row_value(row, "summary_type", ""),
        "visibility_mode": row_value(row, "visibility_mode", ""),
        "freshness_status": row_value(row, "freshness_status", ""),
        "source_event_ids": source_event_ids,
        "source_turn_ids": source_turn_ids,
        "freshness_evidence": freshness_evidence,
    }
    identifiers = {
        "id": row_value(row, "id", ""),
        "subject_id": row_value(row, "subject_id", ""),
    }
    return (
        bool(find_hidden_entity_ref_tokens(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, identifiers))
        or bool(find_hidden_entity_ref_substrings(conn, identifiers))
        or memory_source_rows_have_hidden_refs(conn, event_ids=source_event_ids, turn_ids=source_turn_ids)
    )


def memory_source_rows_have_hidden_refs(
    conn: sqlite3.Connection,
    *,
    event_ids: list[str],
    turn_ids: list[str],
) -> bool:
    payload: dict[str, Any] = {}
    if not all(
        isinstance(item, str) and safe_memory_event_id(item) == item
        for item in event_ids
    ) or not all(
        isinstance(item, str) and safe_memory_turn_id(item) == item
        for item in turn_ids
    ):
        return True
    safe_event_ids = dedupe(event_ids)
    safe_turn_ids = dedupe(turn_ids)
    try:
        for event_chunk in chunks(safe_event_ids, 64):
            placeholders = ",".join("?" for _ in event_chunk)
            rows = conn.execute(
                f"""
                select id, turn_id, title, summary, payload_json, source
                from main.events
                where id in ({placeholders})
                """,
                event_chunk,
            ).fetchall()
            if len(rows) != len(event_chunk):
                return True
            for row in rows:
                values = [row[key] for key in ("id", "turn_id", "title", "summary", "payload_json", "source")]
                if not all(isinstance(value, str) for value in values):
                    return True
                if safe_memory_event_id(row["id"]) != row["id"] or safe_memory_turn_id(row["turn_id"]) != row["turn_id"]:
                    return True
                event_payload = parse_memory_metadata_json(
                    row["payload_json"],
                    INVALID_MEMORY_METADATA,
                )
                if event_payload is INVALID_MEMORY_METADATA:
                    return True
                payload.setdefault("source_events", []).append(
                    {
                        "id": row["id"],
                        "turn_id": row["turn_id"],
                        "title": row["title"],
                        "summary": row["summary"],
                        "payload": event_payload,
                        "source": row["source"],
                    }
                )
                safe_turn_ids.append(row["turn_id"])
            safe_turn_ids = dedupe(safe_turn_ids)
        for turn_chunk in chunks(safe_turn_ids, 64):
            placeholders = ",".join("?" for _ in turn_chunk)
            rows = conn.execute(
                f"""
                select id, user_text, summary, intent, location_before, location_after
                from main.turns
                where id in ({placeholders})
                """,
                turn_chunk,
            ).fetchall()
            if len(rows) != len(turn_chunk):
                return True
            for row in rows:
                if not (
                    isinstance(row["id"], str)
                    and safe_memory_turn_id(row["id"]) == row["id"]
                    and isinstance(row["user_text"], str)
                    and isinstance(row["intent"], str)
                    and (row["summary"] is None or isinstance(row["summary"], str))
                    and memory_turn_location_is_well_formed(row["location_before"])
                    and memory_turn_location_is_well_formed(row["location_after"])
                ):
                    return True
                payload.setdefault("source_turns", []).append(
                    {
                        "id": row["id"],
                        "user_text": row["user_text"],
                        "summary": row["summary"],
                        "intent": row["intent"],
                        "location_before": row["location_before"],
                        "location_after": row["location_after"],
                    }
                )
    except sqlite3.Error:
        return True
    return bool(payload) and (
        bool(find_hidden_entity_ref_tokens(conn, payload))
        or bool(find_hidden_entity_id_substrings(conn, payload))
    )


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def render_memory_section(rows: list[sqlite3.Row], conn: sqlite3.Connection | None = None, *, view: str = "player") -> str:
    lines = ["### 长期记忆摘要", ""]
    for row in rows:
        if conn is not None:
            if not memory_row_visible_for_view(conn, row, view=view):
                continue
            render_row: sqlite3.Row | dict[str, Any] = redact_memory_row_for_view(
                conn,
                row,
                view=view,
            )
        else:
            render_row = row
        raw_title = row_value(render_row, "title", "")
        raw_summary = row_value(render_row, "summary", "")
        title = raw_title if isinstance(raw_title, str) else ""
        summary = raw_summary if isinstance(raw_summary, str) else ""
        points = parse_memory_metadata_json(
            row_value(render_row, "key_points_json", "[]"),
            [],
        )
        freshness_status = (
            memory_row_freshness(conn, render_row, view=view)["status"]
            if conn is not None
            else memory_freshness_status(
                row_value(render_row, "freshness_status", "stale"),
                default="stale",
            )
        )
        if conn is not None and not can_read_hidden(view):
            title = redact_hidden_entity_refs(conn, title) or ""
            summary = redact_hidden_entity_refs(conn, summary) or ""
            points = redact_hidden_entity_refs(conn, points) or []
        item_id = safe_memory_summary_id(row_value(render_row, "id", None)) or "memory:omitted:unverifiable"
        kind = memory_summary_kind(row_value(render_row, "kind", None))
        lines.append(f"- `{item_id}` {title}（{kind}；{freshness_status}）：{summary}")
        for point in as_text_list(points)[:3]:
            lines.append(f"  - {point}")
    return "\n".join(lines)


def redact_memory_row_for_view(
    conn: sqlite3.Connection,
    row: sqlite3.Row | dict[str, Any],
    *,
    view: str = "player",
) -> dict[str, Any]:
    raw = dict(row)
    safe = {key: raw.get(key) for key in MEMORY_PLAYER_ROW_FIELDS}
    trusted_view = can_read_hidden(view)
    raw_id = safe_memory_summary_id(raw.get("id"))
    if not trusted_view and raw_id:
        id_payload = {"id": raw_id}
        if find_hidden_entity_id_substrings(
            conn,
            id_payload,
        ) or find_hidden_entity_ref_substrings(conn, id_payload):
            raw_id = None
    safe["id"] = raw_id or "memory:omitted:unverifiable"
    safe["kind"] = memory_summary_kind(raw.get("kind"))
    safe["subject_id"] = resolvable_memory_subject_id(conn, raw.get("subject_id"), view=view)
    raw_title = raw.get("title")
    raw_summary = raw.get("summary")
    safe_title = raw_title if isinstance(raw_title, str) else ""
    safe_summary = raw_summary if isinstance(raw_summary, str) else ""
    safe["title"] = (
        safe_title
        if trusted_view
        else redact_hidden_entity_refs(conn, safe_title, drop_empty=False) or ""
    )
    safe["summary"] = (
        safe_summary
        if trusted_view
        else redact_hidden_entity_refs(conn, safe_summary, drop_empty=False) or ""
    )
    safe["summary_type"] = memory_row_summary_type(raw)
    safe["freshness_status"] = memory_freshness_status(
        safe.get("freshness_status"),
        default="stale",
    )
    raw_visibility = raw.get("visibility_mode")
    safe["visibility_mode"] = (
        raw_visibility
        if trusted_view and raw_visibility in {"player", MAINTENANCE_VIEW}
        else "player"
    )
    updated_at = parse_memory_timestamp(raw.get("updated_at"))
    safe["updated_at"] = updated_at.isoformat() if updated_at is not None else None
    safe["source_event_ids_json"] = json.dumps(
        memory_row_source_event_ids(row, conn=conn, view=view),
        ensure_ascii=False,
        sort_keys=True,
    )
    safe["source_turn_ids_json"] = json.dumps(
        memory_row_source_turn_ids(row, conn=conn, view=view),
        ensure_ascii=False,
        sort_keys=True,
    )
    for key in ("valid_from_turn", "valid_to_turn"):
        value = safe_memory_turn_id(row_value(row, key, ""))
        resolved = resolvable_memory_turn_ids(conn, [value], view=view) if value else []
        safe[key] = resolved[0] if resolved else None
    safe["freshness_turn_id"] = memory_row_freshness_turn_id(conn, row, view=view) or None
    safe["freshness_evidence_json"] = json.dumps(
        memory_row_freshness_evidence(row, conn=conn, view=view),
        ensure_ascii=False,
        sort_keys=True,
    )
    safe["derived_authority_json"] = json.dumps(
        memory_row_authority(row),
        ensure_ascii=False,
        sort_keys=True,
    )
    raw_stale_reason = raw.get("stale_reason")
    raw_stale_reason = raw_stale_reason if isinstance(raw_stale_reason, str) else ""
    safe["stale_reason"] = (
        safe_memory_diagnostic_text(raw_stale_reason)
        if trusted_view
        else player_safe_memory_reason(raw_stale_reason)
        if raw_stale_reason
        else ""
    )
    points = parse_memory_metadata_json(raw.get("key_points_json"), [])
    safe["key_points_json"] = json.dumps(
        points
        if trusted_view
        else redact_hidden_entity_refs(conn, points, drop_empty=False) or [],
        ensure_ascii=False,
        sort_keys=True,
    )
    return safe


def row_value(row: sqlite3.Row | dict[str, Any], key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def write_memory_report(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    check_projection: bool = True,
) -> Path:
    if memory_authority_temp_shadow_exists(conn):
        raise sqlite3.OperationalError("memory authority schema has a TEMP shadow")
    projection_health = memory_projection_health(conn) if check_projection else None
    projection_status = str(projection_health["status"]) if projection_health else "clean"
    projection_snapshot = (
        memory_projection_snapshot(conn, projection_health)
        if projection_health is not None
        else None
    )
    rows = [
        redact_memory_row_for_view(conn, row, view="player")
        for row in conn.execute(
            """
            select *
            from main.memory_summaries
            order by kind, id
            """
        ).fetchall()
        if memory_row_visible_for_view(conn, row, view="player")
        and memory_row_freshness(
            conn,
            row,
            view="player",
            check_projection=check_projection,
            projection_status=projection_status,
        )["status"]
        != "stale"
    ]
    path = campaign.root / "reports" / "memory-current.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {campaign.name} 长期记忆摘要",
        "",
        f"- 条目数：{len(rows)}",
        "",
    ]
    for row in rows:
        freshness = memory_row_freshness(
            conn,
            row,
            view="player",
            check_projection=check_projection,
            projection_status=projection_status,
        )
        freshness_turn_id = memory_row_freshness_turn_id(conn, row, view="player")
        lines.append(f"## `{row['id']}` {row['title']}")
        lines.append("")
        lines.append(f"- 类型：{row['kind']}")
        if row["subject_id"]:
            lines.append(f"- 主体：`{row['subject_id']}`")
        lines.append(f"- 摘要类型：{memory_row_summary_type(row)}")
        lines.append(f"- 可见性模式：{row_value(row, 'visibility_mode', 'player')}")
        lines.append(f"- 新鲜度：{freshness['status']}")
        if freshness_turn_id:
            lines.append(f"- 新鲜度回合：`{freshness_turn_id}`")
        if row_value(row, "stale_reason"):
            lines.append(f"- 过期原因：{row_value(row, 'stale_reason')}")
        source_event_ids = memory_row_source_event_ids(row, conn=conn, view="player")
        source_turn_ids = memory_row_source_turn_ids(row, conn=conn, view="player")
        freshness_evidence = memory_row_freshness_evidence(row, conn=conn, view="player")
        authority = memory_row_authority(row)
        lines.append(
            "- 来源事件："
            + ("、".join(f"`{item}`" for item in source_event_ids) if source_event_ids else "无")
        )
        lines.append(
            "- 来源回合："
            + ("、".join(f"`{item}`" for item in source_turn_ids) if source_turn_ids else "无")
        )
        lines.append(
            "- 新鲜度证据：`"
            + json.dumps(freshness_evidence, ensure_ascii=False, sort_keys=True)
            + "`"
        )
        lines.append(
            "- 派生权威：`"
            + json.dumps(authority, ensure_ascii=False, sort_keys=True)
            + "`"
        )
        lines.append(f"- 摘要：{row['summary']}")
        points = parse_json(row["key_points_json"], [])
        if points:
            lines.append("- 要点：")
            for point in as_text_list(points):
                lines.append(f"  - {point}")
        lines.append("")
    report_text = "\n".join(lines).rstrip() + "\n"
    if projection_snapshot is not None and memory_projection_snapshot_change(
        conn,
        projection_snapshot,
    ) is not None:
        write_text_atomic(path, memory_report_unavailable_text(campaign))
        raise RuntimeError("memory projection changed during report generation")
    write_text_atomic(path, report_text)
    if projection_snapshot is not None and memory_projection_snapshot_change(
        conn,
        projection_snapshot,
    ) is not None:
        write_text_atomic(path, memory_report_unavailable_text(campaign))
        raise RuntimeError("memory projection changed during report publication")
    return path


def memory_report_unavailable_text(campaign: Campaign) -> str:
    return (
        f"# {campaign.name} 长期记忆摘要\n\n"
        "- 条目数：0\n"
        "- 状态：memory projection changed; report unavailable until refresh\n"
    )


def parse_day(value: str | None) -> str | None:
    if not value:
        return None
    match = DAY_PATTERN.search(value)
    return match.group(1) if match else None


def event_point(row: sqlite3.Row, conn: sqlite3.Connection | None = None, *, view: str = "player") -> str:
    title = str(row["title"] or row["type"])
    summary = str(row["summary"] or "")
    if conn is not None and not can_read_hidden(view):
        title = redact_hidden_entity_refs(conn, title) or ""
        summary = redact_hidden_entity_refs(conn, summary) or ""
    return trim_join([title, summary], "：", 180)


def history_points(conn: sqlite3.Connection, rows: list[sqlite3.Row], *, view: str = "player") -> list[str]:
    points: list[str] = []
    for row in rows:
        points.append(event_point(row, conn, view=view))
        payload = parse_json(row["payload_json"], {})
        key_points = payload.get("key_points") if isinstance(payload, dict) else None
        if isinstance(key_points, list):
            if can_read_hidden(view):
                points.extend(str(point) for point in key_points[:8] if str(point))
            else:
                points.extend(
                    str(redact_hidden_entity_refs(conn, str(point)) or "")
                    for point in key_points[:8]
                    if str(point)
                )
        provenance = payload.get("provenance") if isinstance(payload, dict) else None
        if isinstance(provenance, dict):
            tier = provenance.get("tier")
            if tier:
                points.append(f"来源等级：{tier}")
    return points


def as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def format_memory_value(value: Any) -> str:
    if isinstance(value, list):
        return trim_join([format_memory_value(item) for item in value[:4]], "；", 180)
    if isinstance(value, dict):
        parts = [f"{key}={format_memory_value(item)}" for key, item in list(value.items())[:4]]
        return trim_join(parts, "；", 180)
    return str(value)


def trim_join(items: list[str], separator: str, limit: int) -> str:
    text = separator.join(item for item in items if item)
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def safe_id(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return text.strip("-") or "unknown"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
