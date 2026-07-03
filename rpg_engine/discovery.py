from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .db import utc_now


STAGE_RANK = {
    "rumor": 0,
    "clue": 1,
    "sampled": 2,
    "confirmed": 3,
    "archived": 4,
}


def record_discovery_from_events(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    events: list[dict[str, Any]],
) -> None:
    if not table_exists(conn, "discovery_states"):
        return
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if not payload.get("palette_id") and payload.get("target_kind") != "unknown_lead":
            continue
        event_id = str(event.get("id") or "")
        upsert_discovery_from_payload(conn, turn_id=turn_id, event_id=event_id, payload=payload)


def upsert_discovery_from_payload(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    event_id: str,
    payload: dict[str, Any],
) -> str:
    now = utc_now()
    palette_id = str(payload.get("palette_id") or "").strip() or None
    subject_id = str(payload.get("target_id") or payload.get("subject_id") or "").strip() or None
    kind = str(payload.get("palette_kind") or payload.get("target_kind") or "unknown_lead")
    stage = discovery_stage(payload)
    visibility = "hinted" if stage in {"rumor", "clue", "sampled"} else "known"
    discovery_id = discovery_state_id(palette_id=palette_id, subject_id=subject_id, kind=kind)
    existing = conn.execute("select * from discovery_states where id = ?", (discovery_id,)).fetchone()
    source_event_ids = []
    confirmation_methods = []
    if existing:
        source_event_ids = read_json_list(existing["source_event_ids_json"])
        confirmation_methods = read_json_list(existing["confirmation_methods_json"])
        stage = stronger_stage(str(existing["stage"]), stage)
    if event_id and event_id not in source_event_ids:
        source_event_ids.append(event_id)
    for method in payload.get("confirmation_methods", []) if isinstance(payload.get("confirmation_methods"), list) else []:
        text = str(method)
        if text and text not in confirmation_methods:
            confirmation_methods.append(text)
    note = str(payload.get("palette_name") or payload.get("target_query") or payload.get("summary") or "")
    conn.execute(
        """
        insert into discovery_states
        (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
         confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
         notes, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
          subject_id=coalesce(excluded.subject_id, discovery_states.subject_id),
          palette_id=coalesce(excluded.palette_id, discovery_states.palette_id),
          kind=excluded.kind,
          stage=excluded.stage,
          visibility=excluded.visibility,
          evidence_count=excluded.evidence_count,
          confirmation_methods_json=excluded.confirmation_methods_json,
          source_event_ids_json=excluded.source_event_ids_json,
          updated_turn_id=excluded.updated_turn_id,
          notes=excluded.notes,
          updated_at=excluded.updated_at
        """,
        (
            discovery_id,
            subject_id,
            palette_id,
            kind,
            stage,
            visibility,
            len(source_event_ids),
            json.dumps(confirmation_methods, ensure_ascii=False, sort_keys=True),
            json.dumps(source_event_ids, ensure_ascii=False, sort_keys=True),
            turn_id if not existing else existing["created_turn_id"],
            turn_id,
            note,
            now if not existing else existing["created_at"],
            now,
        ),
    )
    return discovery_id


def discovery_stage(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("discovery_stage") or payload.get("clue_stage") or "").strip()
    if explicit in STAGE_RANK:
        return explicit
    if explicit in {"hint", "hinted", "lead"}:
        return "clue"
    status = str(payload.get("palette_status") or "")
    event_kind = str(payload.get("event_type") or payload.get("target_kind") or "")
    if payload.get("sampled") is True or status == "available" and event_kind != "palette_candidate":
        return "sampled"
    if status in {"clue_only", "confirm_required", "available"}:
        return "clue"
    return "rumor"


def stronger_stage(left: str, right: str) -> str:
    return left if STAGE_RANK.get(left, -1) >= STAGE_RANK.get(right, -1) else right


def discovery_state_id(*, palette_id: str | None, subject_id: str | None, kind: str) -> str:
    raw = palette_id or subject_id or kind
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-._:")
    return f"discovery:{slug or 'unknown'}"


def read_json_list(text: Any) -> list[str]:
    try:
        value = json.loads(str(text or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone()
    return bool(row)
