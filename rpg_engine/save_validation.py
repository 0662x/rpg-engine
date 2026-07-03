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
from .projections import PROJECTION_VERSIONS, projection_effective_status
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


def inspect_save_package(save_dir: str | Path) -> dict[str, Any]:
    campaign = load_campaign(save_dir)
    files = {name: campaign.root / relative for name, relative in REQUIRED_SAVE_FILES.items()}
    counts = {"entities": 0, "turns": 0, "events": 0, "clocks": 0}
    meta: dict[str, str] = {}
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
        "missing_files": missing_files,
        "counts": counts,
        "errors": dedupe(errors),
        "warnings": dedupe(warnings),
        "error_details": issues_from_messages(dedupe(errors), default_code="SAVE_VALIDATION_ERROR"),
    }


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
    current_turn = meta.get("current_turn_id")
    rows = {row["name"]: row for row in conn.execute("select * from projection_state").fetchall()}
    for name in REQUIRED_PROJECTIONS:
        row = rows.get(name)
        if row is None:
            errors.append(f"projection_state.{name}: missing")
            continue
        status = projection_effective_status(row)
        if status != "clean":
            errors.append(f"projection_state.{name}: status is {status}")
        expected_version = PROJECTION_VERSIONS.get(name)
        if expected_version is not None:
            try:
                actual_version = int(row["version"])
            except (TypeError, ValueError):
                actual_version = 0
            if actual_version < expected_version:
                errors.append(f"projection_state.{name}: version {actual_version} < {expected_version}")
        if current_turn and row["last_turn_id"] != current_turn:
            errors.append(f"projection_state.{name}: last_turn_id {row['last_turn_id']} != current_turn_id {current_turn}")
    if table_exists(conn, "outbox"):
        pending = conn.execute("select id, status from outbox where status != 'done'").fetchall()
        for row in pending:
            errors.append(f"outbox.{row['id']}: status is {row['status']}")


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
    row = conn.execute("select 1 from sqlite_master where name = ?", (table,)).fetchone()
    return bool(row)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"pragma table_info({table})").fetchall()}


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
