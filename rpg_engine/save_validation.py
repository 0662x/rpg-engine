from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from .campaign import load_campaign
from .card_registry import get_default_card_registry
from .cards import GENERATED_MARKER, card_relative_path
from .db import connect
from .migrations import migration_checksum, migration_files
from .projections import (
    PROJECTION_STATE_SCHEMA_COLUMNS,
    PROJECTION_VERSIONS,
    STORED_PROJECTION_STATUSES,
    _inspect_outbox_health,
    _outbox_issue_message,
    projection_effective_status,
)
from .validation_issues import issues_from_messages
from .validators import run_checks
from .visibility import can_read_entity_row


REQUIRED_SAVE_FILES = {
    "campaign_yaml": "campaign.yaml",
    "save_yaml": "save.yaml",
    "database": "data/game.sqlite",
    "events": "data/events.jsonl",
    "snapshot": "snapshots/current.md",
    "snapshot_json": "snapshots/current.json",
    "cards": "cards",
}
REQUIRED_TABLES = {
    "aliases",
    "characters",
    "clocks",
    "entities",
    "events",
    "facts",
    "fts_index",
    "items",
    "locations",
    "meta",
    "outbox",
    "projection_state",
    "routes",
    "schema_migrations",
    "turns",
}
REQUIRED_PROJECTIONS = ("events_jsonl", "search", "snapshots", "cards")
PROJECTION_ARTIFACT_PATHS = {
    "events_jsonl": ("data/events.jsonl",),
    "search": ("sqlite:fts_index",),
    "snapshots": ("snapshots/current.md", "snapshots/current.json"),
    "cards": ("cards/",),
}
AUTHORITY_CONTRACT = {
    "current_fact_authority": {
        "path": "data/game.sqlite",
        "source": "sqlite",
        "role": "current_fact_authority",
        "authority": "authoritative",
    },
    "authoritative_audit": {
        "source": "sqlite.events",
        "role": "authoritative_audit",
        "authority": "authoritative",
    },
    "audit_projection": {
        "path": "data/events.jsonl",
        "source": "projection.events_jsonl",
        "role": "audit_projection",
        "authority": "derived",
    },
    "snapshots": {
        "path": "snapshots/",
        "source": "projection.snapshots",
        "role": "read_model",
        "authority": "derived",
    },
    "cards": {
        "path": "cards/",
        "source": "projection.cards",
        "role": "read_model",
        "authority": "derived",
    },
    "search": {
        "source": "sqlite.fts_index",
        "role": "read_model",
        "authority": "derived",
    },
    "memory": {
        "path": "memory/",
        "source": "projection.memory",
        "role": "read_model",
        "authority": "derived",
    },
    "projection_state": {
        "source": "sqlite.projection_state",
        "role": "projection_health",
        "authority": "evidence",
    },
    "outbox": {
        "source": "sqlite.outbox",
        "role": "projection_work_queue",
        "authority": "evidence",
    },
    "workspace_registry": {
        "path": ".aigm/save-registry.json",
        "role": "workspace_index",
        "authority": "entry_state",
    },
    "pending_state": {
        "path": ".aigm/pending-*.json",
        "role": "player_entry_state",
        "authority": "entry_state",
    },
    "preflight_cache": {
        "source": "intent_preflight_cache",
        "role": "intent_advisory_cache",
        "authority": "advisory",
    },
    "mcp_audit_logs": {
        "source": "mcp.audit",
        "role": "call_evidence",
        "authority": "evidence",
    },
    "archive_manifest": {
        "path": "save-archive.json",
        "role": "archive_evidence",
        "authority": "evidence",
    },
}


def inspect_save_package(save_dir: str | Path) -> dict[str, Any]:
    campaign = load_campaign(save_dir)
    files = {name: campaign.root / relative for name, relative in REQUIRED_SAVE_FILES.items()}
    counts = {"entities": 0, "turns": 0, "events": 0, "clocks": 0}
    meta: dict[str, str] = {}
    health: dict[str, Any] = projection_health_unavailable()
    errors: list[str] = []
    warnings: list[str] = []

    missing_files = [name for name, path in files.items() if not path.exists()]
    errors.extend(f"missing file: {REQUIRED_SAVE_FILES[name]}" for name in missing_files)

    save_manifest = load_save_manifest(files["save_yaml"], errors)
    validate_save_manifest(campaign, save_manifest, errors)

    if campaign.database_path.exists():
        try:
            with connect(campaign) as conn:
                counts = {
                    "entities": table_count(conn, "entities"),
                    "turns": table_count(conn, "turns"),
                    "events": table_count(conn, "events"),
                    "clocks": table_count(conn, "clocks"),
                }
                meta = {str(row["key"]): str(row["value"]) for row in conn.execute("select key, value from meta")}
                validate_meta_compatibility(campaign, save_manifest, meta, errors)
                validate_time_meta(meta, errors)
                validate_sqlite_schema(conn, errors)
                validate_migrations(conn, errors)
                errors.extend(run_checks(conn))
                health = build_projection_health(conn, meta)
                validate_projection_state(conn, meta, errors)
                validate_events_jsonl(campaign.events_path, conn, errors)
                validate_snapshot_json(campaign.current_snapshot_json_path, meta, campaign.campaign_id, errors)
                validate_cards(campaign.cards_path, conn, errors)
                validate_search_projection(conn, errors)
        except Exception as exc:
            errors.append(str(exc))
    else:
        errors.append(f"missing database: {campaign.database_path}")

    return {
        "ok": not errors and not missing_files,
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.name,
        "save_dir": str(campaign.root),
        "engine_version": campaign.engine_version,
        "package_version": campaign.package_version,
        "current_turn_id": meta.get("current_turn_id"),
        "current_location_id": meta.get("current_location_id"),
        "current_game_day": meta.get("current_game_day"),
        "current_time_block": meta.get("current_time_block"),
        "files": {name: {"path": str(path), "exists": path.exists()} for name, path in files.items()},
        "authority_contract": authority_contract(),
        "projection_health": health,
        "missing_files": missing_files,
        "counts": counts,
        "errors": dedupe(errors),
        "warnings": dedupe(warnings),
        "error_details": issues_from_messages(dedupe(errors), default_code="SAVE_VALIDATION_ERROR"),
    }


def authority_contract() -> dict[str, dict[str, str]]:
    return {name: dict(values) for name, values in AUTHORITY_CONTRACT.items()}


def projection_health_unavailable() -> dict[str, Any]:
    return {
        "role": "projection_health",
        "authority": "evidence",
        "current_turn_id": None,
        "required": list(REQUIRED_PROJECTIONS),
        "status": "missing",
        "ok": False,
        "items": [missing_projection_item(name, current_turn=None) for name in REQUIRED_PROJECTIONS],
        "errors": ["projection_health: unavailable"],
        "outbox": {
            "role": "projection_work_queue",
            "authority": "evidence",
            "status": "missing",
            "ok": False,
            "counts": {},
            "non_done": [],
            "errors": ["outbox: unavailable"],
        },
    }


def build_projection_health(conn: sqlite3.Connection, meta: dict[str, str]) -> dict[str, Any]:
    current_turn = non_blank_str(meta.get("current_turn_id"))
    rows = {}
    errors: list[str] = []
    if table_exists(conn, "projection_state"):
        columns = table_columns(conn, "projection_state")
        missing_columns = sorted(set(PROJECTION_STATE_SCHEMA_COLUMNS) - columns)
        if missing_columns:
            errors.append(f"projection_state schema: missing columns {', '.join(missing_columns)}")
        duplicate_names = duplicate_projection_state_names(conn) if "name" in columns else []
        if duplicate_names:
            errors.append(f"projection_state: duplicate names {', '.join(duplicate_names)}")
        if missing_columns or duplicate_names:
            items = [malformed_projection_item(name, current_turn=current_turn) for name in REQUIRED_PROJECTIONS]
        else:
            rows = {str(row["name"]): row for row in conn.execute("select * from projection_state").fetchall()}
            items = [projection_health_item(name, rows.get(name), current_turn=current_turn) for name in REQUIRED_PROJECTIONS]
    else:
        items = [missing_projection_item(name, current_turn=current_turn) for name in REQUIRED_PROJECTIONS]
    outbox = outbox_health(conn)
    return {
        "role": "projection_health",
        "authority": "evidence",
        "current_turn_id": current_turn,
        "required": list(REQUIRED_PROJECTIONS),
        "status": projection_health_status(items, outbox),
        "ok": not errors and all(bool(item["ok"]) for item in items) and bool(outbox["ok"]),
        "items": items,
        "outbox": outbox,
        "errors": errors,
    }


def projection_health_item(name: str, row: sqlite3.Row | None, *, current_turn: str | None) -> dict[str, Any]:
    if row is None:
        return missing_projection_item(name, current_turn=current_turn)
    expected_version = PROJECTION_VERSIONS.get(name)
    version = int_or_none(row["version"])
    last_turn_id = none_or_str(row["last_turn_id"])
    raw_status = none_or_str(row["status"])
    if raw_status not in STORED_PROJECTION_STATUSES:
        effective_status = "invalid"
    else:
        effective_status = projection_effective_status(row)
    aligned = bool(current_turn and last_turn_id == current_turn)
    ok = (
        effective_status == "clean"
        and (expected_version is None or (version is not None and version >= expected_version))
        and current_turn is not None
        and last_turn_id == current_turn
    )
    if effective_status == "invalid":
        health_status = "invalid"
    elif effective_status == "clean" and current_turn is None:
        health_status = "missing_current_turn"
    elif effective_status == "clean" and last_turn_id != current_turn:
        health_status = "behind"
    else:
        health_status = effective_status
    return {
        "name": name,
        "required": True,
        "status": raw_status or "unknown",
        "effective_status": effective_status,
        "health_status": health_status,
        "version": version,
        "expected_version": expected_version,
        "last_turn_id": last_turn_id,
        "aligned_with_current_turn": aligned,
        "last_error": none_or_str(row["last_error"]),
        "updated_at": none_or_str(row["updated_at"]),
        "artifact_paths": list(PROJECTION_ARTIFACT_PATHS.get(name, ())),
        "ok": ok,
    }


def malformed_projection_item(name: str, *, current_turn: str | None) -> dict[str, Any]:
    return {
        "name": name,
        "required": True,
        "status": "malformed",
        "effective_status": "malformed",
        "health_status": "malformed",
        "version": None,
        "expected_version": PROJECTION_VERSIONS.get(name),
        "last_turn_id": None,
        "aligned_with_current_turn": False if current_turn else None,
        "last_error": None,
        "updated_at": None,
        "artifact_paths": list(PROJECTION_ARTIFACT_PATHS.get(name, ())),
        "ok": False,
    }


def missing_projection_item(name: str, *, current_turn: str | None) -> dict[str, Any]:
    return {
        "name": name,
        "required": True,
        "status": "missing",
        "effective_status": "missing",
        "health_status": "missing",
        "version": None,
        "expected_version": PROJECTION_VERSIONS.get(name),
        "last_turn_id": None,
        "aligned_with_current_turn": False if current_turn else None,
        "last_error": None,
        "updated_at": None,
        "artifact_paths": list(PROJECTION_ARTIFACT_PATHS.get(name, ())),
        "ok": False,
    }


def outbox_health(conn: sqlite3.Connection) -> dict[str, Any]:
    return _inspect_outbox_health(conn)


def projection_health_status(items: list[dict[str, Any]], outbox: dict[str, Any]) -> str:
    statuses = [str(item["health_status"]) for item in items]
    outbox_status = str(outbox.get("status") or "clean")
    if "malformed" in statuses:
        return "malformed"
    if "invalid" in statuses:
        return "invalid"
    if outbox_status == "malformed":
        return "malformed"
    if any(status == "failed" for status in statuses) or outbox_status == "failed":
        return "failed"
    if "missing_current_turn" in statuses:
        return "missing_current_turn"
    if "missing" in statuses or outbox_status == "missing":
        return "missing"
    for status in ("missing", "refreshing", "stale", "behind", "dirty"):
        if status in statuses:
            return status
    if outbox_status == "pending":
        return "outbox_pending"
    return "clean"


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def none_or_str(value: Any) -> str | None:
    return None if value is None else str(value)


def non_blank_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_save_manifest(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        errors.append(f"save.yaml: invalid YAML: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append("save.yaml: must be object")
        return {}
    return data


def validate_save_manifest(campaign: Any, manifest: dict[str, Any], errors: list[str]) -> None:
    if not manifest:
        return
    expected = {
        "campaign_id": campaign.campaign_id,
        "campaign_version": campaign.package_version,
        "engine_version": campaign.engine_version,
    }
    for key, value in expected.items():
        if str(manifest.get(key, "")) != value:
            errors.append(f"save.yaml.{key}: expected {value}, got {manifest.get(key)}")


def validate_meta_compatibility(campaign: Any, manifest: dict[str, Any], meta: dict[str, str], errors: list[str]) -> None:
    expected = {
        "campaign_id": campaign.campaign_id,
        "package_version": campaign.package_version,
        "engine_version": campaign.engine_version,
    }
    for key, value in expected.items():
        if meta.get(key) != value:
            errors.append(f"meta.{key}: expected {value}, got {meta.get(key)}")
    if non_blank_str(meta.get("current_turn_id")) is None:
        errors.append("meta.current_turn_id: missing")
    if manifest and meta.get("campaign_id") and str(manifest.get("campaign_id", "")) != meta["campaign_id"]:
        errors.append("save.yaml.campaign_id does not match meta.campaign_id")


def validate_time_meta(meta: dict[str, str], errors: list[str]) -> None:
    time_block = meta.get("current_time_block", "")
    day = meta.get("current_game_day", "")
    if not time_block or not day:
        return
    matches = re.findall(r"第\s*(\d+)\s*天", time_block)
    if not matches:
        return
    block_day = matches[-1]
    if str(day) != block_day:
        errors.append(f"meta.current_game_day {day} does not match current_time_block day {block_day}")


def validate_sqlite_schema(conn: sqlite3.Connection, errors: list[str]) -> None:
    tables = {row[0] for row in conn.execute("select name from sqlite_master where type in ('table', 'virtual')").fetchall()}
    for table in sorted(REQUIRED_TABLES - tables):
        errors.append(f"sqlite schema: missing table {table}")


def validate_migrations(conn: sqlite3.Connection, errors: list[str]) -> None:
    if not table_exists(conn, "schema_migrations"):
        errors.append("schema_migrations: missing")
        return
    columns = table_columns(conn, "schema_migrations")
    rows = {
        row["id"]: row
        for row in conn.execute(
            "select id, checksum from schema_migrations" if "checksum" in columns else "select id, null as checksum from schema_migrations"
        ).fetchall()
    }
    for migration in migration_files():
        row = rows.get(migration.id)
        if row is None:
            errors.append(f"schema_migrations: missing applied migration {migration.id}")
            continue
        checksum = row["checksum"]
        if checksum and checksum != migration_checksum(migration):
            errors.append(f"schema_migrations.{migration.id}: checksum mismatch")


def validate_projection_state(conn: sqlite3.Connection, meta: dict[str, str], errors: list[str]) -> None:
    if not table_exists(conn, "projection_state"):
        errors.append("projection_state: missing")
        return
    current_turn = non_blank_str(meta.get("current_turn_id"))
    columns = table_columns(conn, "projection_state")
    missing_columns = sorted(set(PROJECTION_STATE_SCHEMA_COLUMNS) - columns)
    if missing_columns:
        errors.append(f"projection_state schema: missing columns {', '.join(missing_columns)}")
    duplicate_names = duplicate_projection_state_names(conn) if "name" in columns else []
    if duplicate_names:
        errors.append(f"projection_state: duplicate names {', '.join(duplicate_names)}")
    rows = {}
    if "name" in columns:
        select_list = ", ".join(projection_state_select_expression(column, columns) for column in PROJECTION_STATE_SCHEMA_COLUMNS)
        rows = {
            row["name"]: row
            for row in conn.execute(f"select {select_list} from projection_state").fetchall()
            if row["name"] is not None
        }
    for name in REQUIRED_PROJECTIONS:
        row = rows.get(name)
        if row is None:
            errors.append(f"projection_state.{name}: missing")
            continue
        raw_status = none_or_str(row["status"])
        if raw_status not in STORED_PROJECTION_STATUSES:
            errors.append(f"projection_state.{name}: invalid status {raw_status}")
            status = "invalid"
        else:
            status = projection_effective_status(row)
        if status != "clean":
            errors.append(f"projection_state.{name}: status is {status}")
        expected_version = PROJECTION_VERSIONS.get(name)
        if expected_version is not None and "version" in columns:
            try:
                actual_version = int(row["version"])
            except (TypeError, ValueError):
                actual_version = 0
            if actual_version < expected_version:
                errors.append(f"projection_state.{name}: version {actual_version} < {expected_version}")
        if current_turn and "last_turn_id" in columns and row["last_turn_id"] != current_turn:
            errors.append(f"projection_state.{name}: last_turn_id {row['last_turn_id']} != current_turn_id {current_turn}")
    outbox = outbox_health(conn)
    errors.extend(str(error) for error in outbox.get("errors", []))
    for row in outbox["non_done"]:
        errors.append(_outbox_issue_message(row))


def projection_state_select_expression(column: str, columns: set[str]) -> str:
    if column in columns:
        return column
    return f"null as {column}"


def duplicate_projection_state_names(conn: sqlite3.Connection) -> list[str]:
    try:
        return [
            str(row["name"])
            for row in conn.execute(
                """
                select name
                from projection_state
                group by name
                having count(*) > 1
                order by name
                """
            ).fetchall()
            if row["name"] is not None
        ]
    except sqlite3.Error:
        return []


def validate_events_jsonl(path: Path, conn: sqlite3.Connection, errors: list[str]) -> None:
    if not path.exists():
        return
    seen: set[str] = set()
    jsonl_ids: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"data/events.jsonl:{line_no}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"data/events.jsonl:{line_no}: must be object")
            continue
        event_id = value.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            errors.append(f"data/events.jsonl:{line_no}: missing event_id")
            continue
        if event_id in seen:
            errors.append(f"data/events.jsonl:{line_no}: duplicate event_id {event_id}")
        seen.add(event_id)
        jsonl_ids.add(event_id)
        if not conn.execute("select 1 from events where id = ?", (event_id,)).fetchone():
            errors.append(f"data/events.jsonl:{line_no}: event_id {event_id} not found in SQLite")
    db_ids = {row["id"] for row in conn.execute("select id from events").fetchall()}
    for event_id in sorted(db_ids - jsonl_ids):
        errors.append(f"data/events.jsonl: missing SQLite event {event_id}")


def validate_snapshot_json(path: Path, meta: dict[str, str], campaign_id: str, errors: list[str]) -> None:
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"snapshots/current.json: invalid JSON: {exc}")
        return
    if not isinstance(data, dict):
        errors.append("snapshots/current.json: must be object")
        return
    campaign = data.get("campaign", {})
    if not isinstance(campaign, dict) or campaign.get("id") != campaign_id:
        errors.append("snapshots/current.json.campaign.id: does not match campaign")
    snapshot_meta = data.get("meta", {})
    if not isinstance(snapshot_meta, dict):
        errors.append("snapshots/current.json.meta: missing")
        return
    for key in ("current_turn_id", "current_location_id", "current_game_day", "current_time_block"):
        if meta.get(key) and snapshot_meta.get(key) != meta[key]:
            errors.append(f"snapshots/current.json.meta.{key}: expected {meta[key]}, got {snapshot_meta.get(key)}")


def validate_cards(cards_path: Path, conn: sqlite3.Connection, errors: list[str]) -> None:
    if not cards_path.exists():
        return
    index = cards_path / "INDEX.md"
    if not index.exists():
        errors.append("cards/INDEX.md: missing")
    registry = get_default_card_registry()
    rows = conn.execute("select * from entities where status != 'archived'").fetchall()
    for row in rows:
        if not can_read_entity_row(row):
            continue
        path = cards_path / card_relative_path(row, registry)
        if not path.exists():
            errors.append(f"cards: missing generated card {path.relative_to(cards_path).as_posix()}")
            continue
        try:
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
        except (OSError, IndexError, UnicodeDecodeError) as exc:
            errors.append(f"cards/{path.relative_to(cards_path).as_posix()}: unreadable: {exc}")
            continue
        if first_line != GENERATED_MARKER:
            errors.append(f"cards/{path.relative_to(cards_path).as_posix()}: not a generated card")


def validate_search_projection(conn: sqlite3.Connection, errors: list[str]) -> None:
    if not table_exists(conn, "fts_index"):
        errors.append("fts_index: missing")
        return
    expected = conn.execute(
        "select count(*) from entities where status != 'archived' and visibility != 'hidden'"
    ).fetchone()[0]
    actual = conn.execute("select count(*) from fts_index").fetchone()[0]
    if int(actual) != int(expected):
        errors.append(f"fts_index: expected {expected} indexed entities, got {actual}")


def table_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        row = conn.execute(f"select count(*) from {table}").fetchone()
    except sqlite3.Error:
        return 0
    return 0 if row is None else int(row[0])


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type in ('table', 'virtual') and name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
