from __future__ import annotations

import sqlite3
from typing import Any

from .campaign import Campaign
from .db import rebuild_fts, rebuild_fts_for_entities
from .projections import (
    append_event_records_idempotently,
    enqueue_event_export,
    mark_projection_clean,
    mark_projections_dirty,
    process_outbox,
    projection_tables_exist,
)
from .write_guard import assert_expected_turn, find_idempotent_turn, turn_guard_columns, write_guard_supported


STANDARD_PROJECTIONS = ("events_jsonl", "search", "snapshots", "cards", "memory", "reports")


class UnitOfWork:
    def __init__(self, campaign: Campaign, conn: sqlite3.Connection, guard_payload: dict[str, Any]) -> None:
        self.campaign = campaign
        self.conn = conn
        self.guard_payload = guard_payload
        self.guard_supported = False
        self.command_id: str | None = None
        self.command_hash: str | None = None
        self.expected_turn_id: str | None = None
        self.event_records: list[dict[str, Any]] = []
        self._begun = False

    def begin(self) -> str | None:
        self.conn.execute("begin immediate")
        self._begun = True
        existing_turn = find_idempotent_turn(self.conn, self.guard_payload)
        if existing_turn:
            self.rollback()
            return existing_turn
        assert_expected_turn(self.conn, self.guard_payload)
        self.guard_supported = write_guard_supported(self.conn)
        self.command_id, self.command_hash, self.expected_turn_id = turn_guard_columns(
            self.guard_payload,
            supported=self.guard_supported,
        )
        return None

    def insert_turn(self, values: tuple[Any, ...]) -> None:
        if len(values) != 11:
            raise ValueError("turn insert requires 11 base values")
        if self.guard_supported:
            self.conn.execute(
                """
                insert into turns
                (id, session_id, user_text, intent, game_time_before, game_time_after,
                 location_before, location_after, summary, changed, created_at,
                 command_id, command_hash, expected_turn_id)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, self.command_id, self.command_hash, self.expected_turn_id),
            )
            return
        self.conn.execute(
            """
            insert into turns
            (id, session_id, user_text, intent, game_time_before, game_time_after,
             location_before, location_after, summary, changed, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    def mark_standard_projections(
        self,
        *,
        turn_id: str,
        event_records: list[dict[str, Any]],
        changed_entity_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.event_records.extend(event_records)
        mark_projections_dirty(self.conn, STANDARD_PROJECTIONS, turn_id=turn_id)
        enqueue_event_export(self.conn, turn_id=turn_id, records=event_records)
        if changed_entity_ids is None:
            rebuild_fts(self.conn)
        else:
            rebuild_fts_for_entities(self.conn, changed_entity_ids)
        mark_projection_clean(self.conn, "search", turn_id=turn_id)

    def commit(self) -> None:
        self.conn.commit()
        self._begun = False

    def rollback(self) -> None:
        if not self._begun:
            return
        self.conn.rollback()
        self._begun = False

    def finalize_artifacts(self) -> None:
        if projection_tables_exist(self.conn):
            process_outbox(self.campaign, self.conn)
        elif self.event_records:
            append_event_records_idempotently(self.campaign, self.event_records)
