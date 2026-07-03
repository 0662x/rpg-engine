from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .campaign import Campaign
from .content_types import ContentRuntime, get_default_registry
from .content_validation import validate_content_delta
from .db import utc_now
from .save import next_turn_id
from .time_weather import enrich_time_weather_meta
from .unit_of_work import UnitOfWork


def load_content_delta(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_content_delta(campaign: Campaign, conn: sqlite3.Connection, delta: dict[str, Any]) -> dict[str, int]:
    validation = validate_content_delta(delta, conn)
    if not validation.ok:
        raise ValueError("Invalid content delta:\n" + "\n".join(f"- {error}" for error in validation.errors))
    now = utc_now()
    meta = {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}
    updated_turn_id = str(delta.get("updated_turn_id") or delta.get("turn_id") or next_turn_id(conn))
    summary = str(delta.get("description") or delta.get("summary") or "Content maintenance delta applied.")
    registry = get_default_registry()
    delta_specs = registry.delta_specs()
    counts = {spec.result_key: 0 for spec in delta_specs}
    payload_records = {spec.event_payload_key: [] for spec in delta_specs}
    event_record: dict[str, Any] | None = None

    uow = UnitOfWork(campaign, conn, delta)
    try:
        existing_turn = uow.begin()
        if existing_turn:
            return counts
        turn_values = (
            updated_turn_id,
            str(delta.get("session_id", "content_delta")),
            str(delta.get("user_text", summary)),
            str(delta.get("intent", "content_maintenance")),
            meta.get("current_time_block"),
            meta.get("current_time_block"),
            meta.get("current_location_id"),
            meta.get("current_location_id"),
            summary,
            1,
            now,
        )
        uow.insert_turn(turn_values)
        runtime = ContentRuntime(campaign=campaign, conn=conn, turn_id=updated_turn_id, now=now)
        for spec in delta_specs:
            if not spec.delta_key or not spec.upsert:
                continue
            for record in delta.get(spec.delta_key, []):
                spec.upsert(runtime, record)
                counts[spec.result_key] += 1
                payload_records[spec.event_payload_key].append(spec.record_id(record))

        for key, value in enrich_time_weather_meta({str(key): str(value) for key, value in delta.get("meta", {}).items()}).items():
            conn.execute(
                "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
                (str(key), str(value)),
            )

        event_id = str(delta.get("event_id") or f"event:{updated_turn_id.split(':', 1)[1]}:001")
        payload = {
            "counts": counts,
            **payload_records,
            "meta_keys": [str(key) for key in delta.get("meta", {}).keys()],
        }
        conn.execute(
            """
            insert into events
            (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                updated_turn_id,
                str(delta.get("game_time", meta.get("current_time_block", ""))),
                str(delta.get("event_type", "content_delta")),
                str(delta.get("title", "Content delta applied")),
                summary,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                str(delta.get("source", "content_delta")),
                now,
            ),
        )
        event_record = {
            "event_id": event_id,
            "turn_id": updated_turn_id,
            "game_time": str(delta.get("game_time", meta.get("current_time_block", ""))),
            "type": str(delta.get("event_type", "content_delta")),
            "title": str(delta.get("title", "Content delta applied")),
            "summary": summary,
            "payload": payload,
            "source": str(delta.get("source", "content_delta")),
            "created_at": now,
        }
        conn.execute(
            "insert into meta(key, value) values('current_turn_id', ?) on conflict(key) do update set value=excluded.value",
            (updated_turn_id,),
        )
        conn.execute(
            "insert into meta(key, value) values('last_saved_at', ?) on conflict(key) do update set value=excluded.value",
            (now,),
        )

        uow.mark_standard_projections(
            turn_id=updated_turn_id,
            event_records=[event_record] if event_record else [],
        )
        uow.commit()
    except Exception:
        uow.rollback()
        raise

    uow.finalize_artifacts()

    return counts
