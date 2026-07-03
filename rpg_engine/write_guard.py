from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any


def canonical_command_hash(payload: dict[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("turn_id", None)
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def add_generated_write_guards(
    conn: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    prefix: str,
) -> dict[str, Any]:
    row = conn.execute("select value from meta where key='current_turn_id'").fetchone()
    current_turn = str(row[0]) if row else "turn:seed"
    payload.setdefault("expected_turn_id", current_turn)
    if not payload.get("command_id"):
        seed_payload = dict(payload)
        seed_payload.pop("command_id", None)
        digest = canonical_command_hash(seed_payload)[:16]
        safe_prefix = "".join(char if char.isalnum() or char in "_.:-" else "-" for char in prefix)
        payload["command_id"] = f"{safe_prefix}:{current_turn.replace(':', '-')}-{digest}"
    return payload


def write_guard_supported(conn: sqlite3.Connection) -> bool:
    columns = {row[1] for row in conn.execute("pragma table_info(turns)").fetchall()}
    return {"command_id", "command_hash", "expected_turn_id"}.issubset(columns)


def find_idempotent_turn(conn: sqlite3.Connection, payload: dict[str, Any]) -> str | None:
    command_id = payload.get("command_id")
    if not command_id:
        return None
    if not write_guard_supported(conn):
        return None
    row = conn.execute(
        "select id, command_hash from turns where command_id = ?",
        (str(command_id),),
    ).fetchone()
    if not row:
        return None
    expected_hash = canonical_command_hash(payload)
    if row["command_hash"] != expected_hash:
        raise ValueError(f"command_id conflict: {command_id} was already used with different payload")
    return str(row["id"])


def assert_expected_turn(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    expected = payload.get("expected_turn_id")
    if expected is None:
        return
    current_row = conn.execute("select value from meta where key = 'current_turn_id'").fetchone()
    current = str(current_row[0]) if current_row else ""
    if str(expected) != current:
        raise ValueError(f"stale write: expected current turn {expected}, actual {current or 'missing'}")


def turn_guard_columns(payload: dict[str, Any], *, supported: bool) -> tuple[str | None, str | None, str | None]:
    if not supported:
        return None, None, None
    command_id = str(payload["command_id"]) if payload.get("command_id") else None
    command_hash = canonical_command_hash(payload) if command_id else None
    expected_turn_id = str(payload["expected_turn_id"]) if payload.get("expected_turn_id") else None
    return command_id, command_hash, expected_turn_id
