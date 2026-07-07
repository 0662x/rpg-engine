from __future__ import annotations

import json
import sqlite3
from typing import Any

from .campaign import Campaign, load_yaml_file
from .content_types import ContentRuntime, ContentTypeSpec, get_default_registry
from .db import utc_now
from .save import next_turn_id
from .content_validation import content_source_records, validate_content_sources
from .unit_of_work import UnitOfWork


def sync_campaign_content(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    type_names: list[str] | None = None,
    allow_unsafe: bool = False,
    expected_turn_id: str | None = None,
    command_id: str | None = None,
) -> dict[str, int]:
    specs = sync_specs_for_names(type_names, allow_unsafe=allow_unsafe)
    validation = validate_content_sources(campaign, conn, specs)
    if not validation.ok:
        raise ValueError("Invalid campaign content:\n" + "\n".join(f"- {error}" for error in validation.errors))
    now = utc_now()
    meta = {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}
    turn_id = next_turn_id(conn)
    counts = {spec.result_key: 0 for spec in specs}
    payload_records: dict[str, list[str]] = {spec.event_payload_key: [] for spec in specs}
    file_records: dict[str, list[str]] = {spec.name: [] for spec in specs}
    summary = "Sync registered campaign content into the current database."

    event_record: dict[str, Any] | None = None
    guard_payload = {
        "intent": "content_sync",
        "type_names": type_names or [],
        "allow_unsafe": allow_unsafe,
        "expected_turn_id": expected_turn_id,
        "command_id": command_id,
    }
    uow = UnitOfWork(campaign, conn, guard_payload)
    try:
        existing_turn = uow.begin()
        if existing_turn:
            return counts
        turn_values = (
            turn_id,
            "content_sync",
            summary,
            "content_maintenance",
            meta.get("current_time_block"),
            meta.get("current_time_block"),
            meta.get("current_location_id"),
            meta.get("current_location_id"),
            summary,
            1,
            now,
        )
        uow.insert_turn(turn_values)
        runtime = ContentRuntime(campaign=campaign, conn=conn, turn_id=turn_id, now=now)
        for spec in specs:
            handler = spec.seed_handler
            if not handler or not spec.campaign_key or not spec.yaml_key:
                continue
            for path in campaign.content_files(spec.campaign_key):
                file_records[spec.name].append(campaign.display_path(path))
                data = load_yaml_file(path)
                records, shape_errors = content_source_records(data, spec, campaign.display_path(path))
                if shape_errors:
                    raise ValueError("Invalid campaign content:\n" + "\n".join(f"- {error}" for error in shape_errors))
                for record in records:
                    handler(runtime, record)
                    counts[spec.result_key] += 1
                    payload_records[spec.event_payload_key].append(spec.record_id(record))

        event_id = f"event:{turn_id.split(':', 1)[1]}:001"
        payload: dict[str, Any] = {
            "counts": counts,
            "files": file_records,
            **payload_records,
        }
        conn.execute(
            """
            insert into events
            (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                turn_id,
                str(meta.get("current_time_block", "")),
                "content_sync",
                "Campaign content synced",
                summary,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                "content_sync",
                now,
            ),
        )
        conn.execute(
            "insert into meta(key, value) values('current_turn_id', ?) on conflict(key) do update set value=excluded.value",
            (turn_id,),
        )
        conn.execute(
            "insert into meta(key, value) values('last_saved_at', ?) on conflict(key) do update set value=excluded.value",
            (now,),
        )
        event_record = {
            "event_id": event_id,
            "turn_id": turn_id,
            "game_time": str(meta.get("current_time_block", "")),
            "type": "content_sync",
            "title": "Campaign content synced",
            "summary": summary,
            "payload": payload,
            "source": "content_sync",
            "created_at": now,
        }
        uow.mark_standard_projections(turn_id=turn_id, event_records=[event_record])
        uow.commit()
    except Exception:
        uow.rollback()
        raise

    uow.finalize_artifacts()
    return counts


def sync_specs_for_names(type_names: list[str] | None, *, allow_unsafe: bool = False) -> list[ContentTypeSpec]:
    registry = get_default_registry()
    if not type_names:
        specs = registry.sync_specs()
        if not specs:
            raise ValueError("no content types are marked sync_safe")
        return specs

    specs = [registry.get(name) for name in type_names]
    unsafe = [spec.name for spec in specs if not spec.sync_safe]
    if unsafe and not allow_unsafe:
        joined = ", ".join(sorted(unsafe))
        raise ValueError(f"content type(s) not sync_safe: {joined}; pass --allow-unsafe to sync explicitly")
    return specs
