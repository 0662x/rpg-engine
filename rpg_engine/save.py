from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .campaign import Campaign
from .db import upsert_entity, utc_now
from .delta_schema import validate_delta_schema
from .discovery import record_discovery_from_events
from .time_weather import enrich_time_weather_meta
from .unit_of_work import UnitOfWork


@dataclass(frozen=True)
class SaveTurnResult:
    turn_id: str
    write_status: str

    @property
    def idempotent_replay(self) -> bool:
        return self.write_status == "already_confirmed"


def load_delta(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def next_turn_id(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        select id
        from turns
        where id glob 'turn:[0-9][0-9][0-9][0-9][0-9][0-9]'
        order by id desc
        limit 1
        """
    ).fetchone()
    if not row:
        return "turn:000001"
    number = int(row["id"].split(":", 1)[1]) + 1
    return f"turn:{number:06d}"


def save_turn_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    delta: dict[str, Any],
    *,
    before_write: Callable[[], None] | None = None,
    rollback_write_artifacts: Callable[[], None] | None = None,
) -> str:
    return save_turn_delta_outcome(
        campaign,
        conn,
        delta,
        before_write=before_write,
        rollback_write_artifacts=rollback_write_artifacts,
    ).turn_id


def save_turn_delta_outcome(
    campaign: Campaign,
    conn: sqlite3.Connection,
    delta: dict[str, Any],
    *,
    before_write: Callable[[], None] | None = None,
    rollback_write_artifacts: Callable[[], None] | None = None,
) -> SaveTurnResult:
    schema_errors = validate_delta_schema(delta, conn)
    if schema_errors:
        raise ValueError("Invalid turn delta:\n" + "\n".join(f"- {error}" for error in schema_errors))

    now = utc_now()
    meta = {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}
    turn_id = str(delta.get("turn_id") or next_turn_id(conn))
    changed = 1 if delta.get("changed", True) else 0
    delta_meta = enrich_time_weather_meta({str(key): str(value) for key, value in delta.get("meta", {}).items()})

    uow = UnitOfWork(campaign, conn, delta)
    write_artifacts_started = False
    try:
        existing_turn = uow.begin()
        if existing_turn:
            return SaveTurnResult(turn_id=existing_turn, write_status="already_confirmed")
        if before_write:
            write_artifacts_started = True
            before_write()
        turn_values = (
            turn_id,
            delta.get("session_id"),
            str(delta.get("user_text", "")),
            str(delta.get("intent", "advance_action")),
            delta.get("game_time_before", meta.get("current_time_block")),
            delta.get("game_time_after", delta_meta.get("current_time_block", meta.get("current_time_block"))),
            delta.get("location_before", meta.get("current_location_id")),
            delta.get("location_after", delta_meta.get("current_location_id", meta.get("current_location_id"))),
            delta.get("summary"),
            changed,
            now,
        )
        uow.insert_turn(turn_values)

        event_records = []
        for index, event in enumerate(delta.get("events", []), start=1):
            event_id = str(event.get("id") or f"event:{turn_id.split(':', 1)[1]}:{index:03d}")
            payload = event.get("payload", {})
            conn.execute(
                """
                insert into events
                (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    turn_id,
                    str(event.get("game_time", delta.get("game_time_after", ""))),
                    str(event.get("type", "note")),
                    str(event.get("title", "")),
                    str(event.get("summary", "")),
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    str(event.get("source", "assistant")),
                    now,
                ),
            )
            event_records.append(
                {
                    "event_id": event_id,
                    "turn_id": turn_id,
                    "game_time": str(event.get("game_time", delta.get("game_time_after", ""))),
                    "type": str(event.get("type", "note")),
                    "title": str(event.get("title", "")),
                    "summary": str(event.get("summary", "")),
                    "payload": payload,
                    "source": str(event.get("source", "assistant")),
                    "created_at": now,
                }
            )

        for entity in delta.get("upsert_entities", []):
            entity.setdefault("updated_turn_id", turn_id)
            upsert_entity(conn, entity)

        for item in delta.get("tick_clocks", []):
            clock_id = str(item["id"])
            amount = int(item.get("delta", 0))
            row = conn.execute(
                "select segments_filled, segments_total from clocks where entity_id = ?",
                (clock_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Missing clock: {clock_id}")
            filled = max(0, min(int(row["segments_total"]), int(row["segments_filled"]) + amount))
            conn.execute(
                "update clocks set segments_filled = ?, last_ticked_turn_id = ? where entity_id = ?",
                (filled, turn_id, clock_id),
            )
            conn.execute(
                "update entities set updated_turn_id = ?, updated_at = ? where id = ?",
                (turn_id, now, clock_id),
            )

        for key, value in delta_meta.items():
            conn.execute(
                "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
                (str(key), str(value)),
            )
        record_discovery_from_events(
            conn,
            turn_id=turn_id,
            events=[
                {
                    "id": record["event_id"],
                    "type": record["type"],
                    "payload": record["payload"],
                    "summary": record["summary"],
                }
                for record in event_records
            ],
        )
        conn.execute(
            "insert into meta(key, value) values('current_turn_id', ?) on conflict(key) do update set value=excluded.value",
            (turn_id,),
        )
        conn.execute(
            "insert into meta(key, value) values('last_saved_at', ?) on conflict(key) do update set value=excluded.value",
            (now,),
        )

        uow.mark_standard_projections(turn_id=turn_id, event_records=event_records)
        uow.commit()
    except Exception as exc:
        try:
            uow.rollback()
        except Exception as rollback_exc:
            exc.add_note(f"rollback failed: {rollback_exc!r}")
        finally:
            if write_artifacts_started and rollback_write_artifacts:
                try:
                    rollback_write_artifacts()
                except Exception as cleanup_exc:
                    exc.add_note(f"write artifact rollback failed: {cleanup_exc!r}")
        raise

    uow.finalize_artifacts()

    return SaveTurnResult(turn_id=turn_id, write_status="committed")
