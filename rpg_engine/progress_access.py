from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Sequence

from .entity_access import EntityRecord, list_entities, read_entity
from .visibility import (
    PLAYER_VIEW,
    can_read_hidden,
    is_player_hidden_visibility,
    normalize_visibility_label,
    normalize_visibility_view,
)


CLOCK_ID_PREFIX = "clock:"
CLOCK_ID_PATTERN = re.compile(r"^clock:[A-Za-z0-9_.:-]+$")
UNSAFE_TEXT_PATTERN = re.compile(
    "["
    "\u0000-\u001f"
    "\u0080-\u009f"
    "\u007f"
    "\u00a8"
    "\u00af"
    "\u00b4"
    "\u00b8"
    "\u00ad"
    "\u02d8-\u02dd"
    "\u034f"
    "\u037a"
    "\u0384-\u0385"
    "\u0600-\u0605"
    "\u061c"
    "\u06dd"
    "\u070f"
    "\u0890-\u0891"
    "\u08e2"
    "\u180e"
    "\u2017"
    "\u203e"
    "\u200b-\u200f"
    "\u202a-\u202e"
    "\u2060-\u206f"
    "\ufeff"
    "\u0300-\u036f"
    "\u1ab0-\u1aff"
    "\u1dc0-\u1dff"
    "\u1fbd"
    "\u1fbf-\u1fc1"
    "\u1fcd-\u1fcf"
    "\u1fdd-\u1fdf"
    "\u1fed-\u1fef"
    "\u1ffd-\u1ffe"
    "\u20d0-\u20ff"
    "\ufe00-\ufe0f"
    "\ufe20-\ufe2f"
    "\uffe3"
    "\ufff9-\ufffb"
    "\U000110bd"
    "\U000110cd"
    "\U00013430-\U0001343f"
    "\U0001bca0-\U0001bca3"
    "\U0001d173-\U0001d17a"
    "\U000e0000-\U000e007f"
    "\U000e0100-\U000e01ef"
    "]"
)


@dataclass(frozen=True)
class ProgressRecord:
    id: str
    kind: str
    clock_type: str
    scope: Any
    segments_total: int
    segments_filled: int
    visibility: str
    status: str
    summary: str
    trigger_when_full: str
    tick_rules: dict[str, Any]
    details: dict[str, Any]
    last_ticked_turn_id: str | None
    updated_turn_id: str
    updated_at: str
    entity: EntityRecord | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "clock_type": self.clock_type,
            "scope": self.scope,
            "segments_total": self.segments_total,
            "segments_filled": self.segments_filled,
            "visibility": self.visibility,
            "status": self.status,
            "summary": self.summary,
            "trigger_when_full": self.trigger_when_full,
            "tick_rules": self.tick_rules,
            "details": self.details,
            "last_ticked_turn_id": self.last_ticked_turn_id,
            "updated_turn_id": self.updated_turn_id,
            "updated_at": self.updated_at,
            "entity": self.entity.to_dict() if self.entity else None,
        }


def read_progress(
    conn: sqlite3.Connection,
    progress_id: str,
    *,
    view: str | None = PLAYER_VIEW,
    include_archived: bool = False,
) -> ProgressRecord | None:
    _validate_bool("include_archived", include_archived)
    entity = read_entity(conn, progress_id, view=view, include_archived=include_archived)
    if entity is None or normalize_visibility_label(entity.type) != "clock":
        return None
    return _progress_from_entity(conn, entity)


def list_progress(
    conn: sqlite3.Connection,
    *,
    view: str | None = PLAYER_VIEW,
    statuses: str | Sequence[str] | None = None,
    kinds: str | Sequence[str] | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> list[ProgressRecord]:
    _validate_bool("include_archived", include_archived)
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            return []
    kind_values = set(_filter_values("kinds", kinds)) if kinds is not None else None
    records: list[ProgressRecord] = []
    for entity in list_entities(
        conn,
        view=view,
        statuses=statuses,
        types="clock",
        include_archived=include_archived,
    ):
        progress = _progress_from_entity(conn, entity)
        if progress is None:
            continue
        if kind_values is not None and normalize_visibility_label(progress.clock_type) not in kind_values:
            continue
        records.append(progress)
        if limit is not None and len(records) >= limit:
            break
    return records


def validate_delta_progress_references(
    conn: sqlite3.Connection,
    delta: Any,
    *,
    view: str | None = "maintenance",
    extra_clock_ids: Iterable[str] | None = None,
) -> list[str]:
    if not isinstance(delta, dict):
        return []
    tick_clocks = delta.get("tick_clocks")
    if tick_clocks is None:
        return []
    errors: list[str] = []
    if not isinstance(tick_clocks, list):
        return ["$.tick_clocks: must be array"]
    same_delta_clock_ids = {item for item in (extra_clock_ids or ()) if is_valid_clock_id(item)}
    for index, item in enumerate(tick_clocks):
        path = f"$.tick_clocks[{index}]"
        if not isinstance(item, dict):
            _append_error_once(errors, f"{path}: must be object")
            continue
        clock_id = _validate_tick_clock_shape(errors, item, path)
        if not clock_id:
            continue
        if clock_id in same_delta_clock_ids:
            continue
        row = _clock_reference_row(conn, clock_id)
        if row is None:
            _append_error_once(errors, f"{path}.id: Missing clock {clock_id}")
            continue
        status = _row_value(row, "status")
        if status is not None and normalize_visibility_label(str(status)) == "archived":
            _append_error_once(errors, f"{path}.id: archived clock {clock_id}")
            continue
        if not can_read_hidden(normalize_visibility_view(view)) and read_progress(conn, clock_id, view=view) is None:
            _append_error_once(errors, f"{path}.id: unavailable clock {clock_id}")
    return errors


def _progress_from_entity(conn: sqlite3.Connection, entity: EntityRecord) -> ProgressRecord | None:
    row = conn.execute(
        """
        select *
        from clocks
        where entity_id = ?
        """,
        (entity.id,),
    ).fetchone()
    if row is None:
        return None
    tick_rules = _parse_json(row["tick_rules_json"])
    details = dict(entity.details)
    scope = details.get("scope")
    if scope is None:
        scope = tick_rules.get("scope")
    clock_type = str(row["clock_type"] or "")
    return ProgressRecord(
        id=entity.id,
        kind=clock_type,
        clock_type=clock_type,
        scope=scope,
        segments_total=int(row["segments_total"]),
        segments_filled=int(row["segments_filled"]),
        visibility=_effective_progress_visibility(entity.visibility, row["visibility"]),
        status=entity.status,
        summary=entity.summary,
        trigger_when_full=str(row["trigger_when_full"] or ""),
        tick_rules=tick_rules,
        details=details,
        last_ticked_turn_id=_optional_str(row["last_ticked_turn_id"]),
        updated_turn_id=entity.updated_turn_id,
        updated_at=entity.updated_at,
        entity=entity,
    )


def _clock_reference_row(conn: sqlite3.Connection, clock_id: str) -> sqlite3.Row | None:
    try:
        return conn.execute(
            """
            select e.status
            from clocks c
            join entities e on e.id = c.entity_id
            where c.entity_id = ?
            """,
            (clock_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return conn.execute("select 1 as exists_flag from clocks where entity_id = ?", (clock_id,)).fetchone()


def _validate_tick_clock_shape(errors: list[str], item: dict[str, Any], path: str) -> str | None:
    clock_id = item.get("id")
    normalized_clock_id: str | None = None
    if not isinstance(clock_id, str) or not has_visible_text(clock_id):
        _append_error_once(errors, f"{path}.id: must be non-empty string")
    elif clock_id != clock_id.strip():
        _append_error_once(errors, f"{path}.id: must not contain leading or trailing whitespace")
    elif not is_valid_clock_id(clock_id):
        _append_error_once(errors, f"{path}.id: invalid clock id")
    else:
        normalized_clock_id = clock_id

    if "delta" not in item:
        _append_error_once(errors, f"{path}.delta: required")
    elif isinstance(item["delta"], bool) or not isinstance(item["delta"], int) or item["delta"] == 0:
        _append_error_once(errors, f"{path}.delta: must be non-zero integer")

    if "reason" not in item:
        _append_error_once(errors, f"{path}.reason: required")
    else:
        reason = item["reason"]
        if not is_safe_visible_text(reason):
            _append_error_once(errors, f"{path}.reason: must be non-empty string when present")
    return normalized_clock_id


def is_valid_clock_id(value: Any) -> bool:
    return isinstance(value, str) and CLOCK_ID_PATTERN.match(value) is not None


def has_visible_text(value: str) -> bool:
    return bool(normalize_visible_text(value).strip())


def is_safe_visible_text(value: Any) -> bool:
    if not isinstance(value, str) or not has_visible_text(value):
        return False
    return UNSAFE_TEXT_PATTERN.search(value) is None and UNSAFE_TEXT_PATTERN.search(unicodedata.normalize("NFKC", value)) is None


def normalize_visible_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    return UNSAFE_TEXT_PATTERN.sub("", text)


def _effective_progress_visibility(entity_visibility: Any, clock_visibility: Any) -> str:
    if is_player_hidden_visibility(str(entity_visibility)):
        return "hidden"
    return str(clock_visibility)


def _parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _row_value(row: sqlite3.Row, key: str) -> Any:
    try:
        keys = row.keys()
    except AttributeError:
        return None
    return row[key] if key in keys else None


def _validate_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")


def _filter_values(name: str, values: str | Sequence[str]) -> list[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, (bytes, bytearray)) or not isinstance(values, SequenceABC):
        raise ValueError(f"{name} must be string or sequence of strings")
    else:
        raw_values = list(values)
    normalized: list[str] = []
    for item in raw_values:
        if item is None:
            continue
        if not isinstance(item, str):
            raise ValueError(f"{name} must be string or sequence of strings")
        label = normalize_visibility_label(item)
        if label:
            normalized.append(label)
    return normalized


def _append_error_once(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)
