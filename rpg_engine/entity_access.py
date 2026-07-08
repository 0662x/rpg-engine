from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .visibility import (
    PLAYER_VIEW,
    can_read_hidden,
    ensure_visibility_sql_functions,
    normalize_visibility_label,
    normalize_visibility_view,
    normalized_text_sql,
)


_ENTITY_ID_PATTERN = re.compile(r"^[a-z]+:[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class EntityRecord:
    id: str
    type: str
    name: str
    status: str
    visibility: str
    location_id: str | None
    owner_id: str | None
    summary: str
    details: dict[str, Any]
    updated_turn_id: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> EntityRecord:
        return cls(
            id=str(row["id"]),
            type=str(row["type"]),
            name=str(row["name"]),
            status=str(row["status"]),
            visibility=str(row["visibility"]),
            location_id=_optional_str(row["location_id"]),
            owner_id=_optional_str(row["owner_id"]),
            summary=str(row["summary"] or ""),
            details=_parse_details(row["details_json"]),
            updated_turn_id=str(row["updated_turn_id"]),
            updated_at=str(row["updated_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "status": self.status,
            "visibility": self.visibility,
            "location_id": self.location_id,
            "owner_id": self.owner_id,
            "summary": self.summary,
            "details": self.details,
            "updated_turn_id": self.updated_turn_id,
            "updated_at": self.updated_at,
        }


def read_entity(
    conn: sqlite3.Connection,
    entity_id: str,
    *,
    view: str | None = PLAYER_VIEW,
    include_archived: bool = False,
) -> EntityRecord | None:
    _validate_bool("include_archived", include_archived)
    ensure_visibility_sql_functions(conn)
    entity_id = str(entity_id).strip()
    if not entity_id:
        return None
    status_clause = "" if include_archived else f"and {normalized_text_sql('e.status')} != 'archived'"
    visibility_clause = _entity_access_visibility_sql(view)
    row = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          {status_clause}
          {visibility_clause}
        """,
        (entity_id,),
    ).fetchone()
    return EntityRecord.from_row(row) if row else None


def list_entities(
    conn: sqlite3.Connection,
    *,
    view: str | None = PLAYER_VIEW,
    statuses: str | Sequence[str] | None = None,
    types: str | Sequence[str] | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> list[EntityRecord]:
    _validate_bool("include_archived", include_archived)
    ensure_visibility_sql_functions(conn)
    clauses: list[str] = []
    params: list[Any] = []
    if statuses is not None:
        status_values = _filter_values("statuses", statuses)
        if not include_archived:
            status_values = [value for value in status_values if value != "archived"]
        if not status_values:
            return []
        placeholders = ",".join("?" for _ in status_values)
        clauses.append(f"{normalized_text_sql('e.status')} in ({placeholders})")
        params.extend(status_values)
    elif not include_archived:
        clauses.append(f"{normalized_text_sql('e.status')} != 'archived'")

    if types is not None:
        type_values = _filter_values("types", types)
        if not type_values:
            return []
        placeholders = ",".join("?" for _ in type_values)
        clauses.append(f"{normalized_text_sql('e.type')} in ({placeholders})")
        params.extend(type_values)

    visibility_clause = _entity_access_visibility_sql(view).strip()
    if visibility_clause.startswith("and "):
        clauses.append(visibility_clause[4:])

    where = f"where {' and '.join(clauses)}" if clauses else ""
    limit_clause = ""
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit_value = max(0, limit)
        limit_clause = "limit ?"
        params.append(limit_value)

    rows = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {where}
        order by e.type, e.id
        {limit_clause}
        """,
        tuple(params),
    ).fetchall()
    return [EntityRecord.from_row(row) for row in rows]


def validate_delta_entity_references(conn: sqlite3.Connection, delta: Any) -> list[str]:
    if not isinstance(delta, dict):
        return ["$ must be an object"]
    errors: list[str] = []
    upsert_types = _delta_upsert_types(delta)
    upsert_ids = set(upsert_types)
    for field in ["location_before", "location_after"]:
        if field in delta and delta[field] is not None:
            _validate_optional_entity_reference(errors, conn, delta[field], f"$.{field}", upsert_ids)
    meta = delta.get("meta", {})
    if isinstance(meta, dict) and meta.get("current_location_id") is not None:
        _validate_optional_entity_reference(
            errors,
            conn,
            meta["current_location_id"],
            "$.meta.current_location_id",
            upsert_ids,
            required_type="location",
            same_delta_entity_types=upsert_types,
        )
    upsert_entities = delta.get("upsert_entities", [])
    if not isinstance(upsert_entities, list):
        return errors
    for index, entity in enumerate(upsert_entities):
        if not isinstance(entity, dict):
            continue
        path = f"$.upsert_entities[{index}]"
        for field in ["location_id", "owner_id"]:
            if field in entity and entity[field] is not None:
                _validate_optional_entity_reference(errors, conn, entity[field], f"{path}.{field}", upsert_ids)
        character = entity.get("character")
        if isinstance(character, dict) and character.get("species_id") is not None:
            _validate_optional_entity_reference(
                errors,
                conn,
                character["species_id"],
                f"{path}.character.species_id",
                upsert_ids,
            )
        location = entity.get("location")
        if isinstance(location, dict) and location.get("parent_id") is not None:
            _validate_optional_entity_reference(
                errors,
                conn,
                location["parent_id"],
                f"{path}.location.parent_id",
                upsert_ids,
            )
        crop_plot = entity.get("crop_plot")
        if isinstance(crop_plot, dict):
            if "crop_entity_id" in crop_plot and crop_plot["crop_entity_id"] is not None:
                _validate_optional_entity_reference(
                    errors,
                    conn,
                    crop_plot["crop_entity_id"],
                    f"{path}.crop_plot.crop_entity_id",
                    upsert_ids,
                )
    return errors


def validate_entity_reference(
    errors: list[str],
    conn: sqlite3.Connection,
    entity_id: str,
    path: str,
    same_delta_entity_ids: Iterable[str],
) -> None:
    if not isinstance(entity_id, str) or not entity_id.strip():
        _append_error_once(errors, f"{path}: must be non-empty string")
        return
    if entity_id != entity_id.strip():
        _append_error_once(errors, f"{path}: must not contain leading or trailing whitespace")
        return
    if not _ENTITY_ID_PATTERN.match(entity_id):
        _append_error_once(errors, f"{path}: invalid entity id")
        return
    if entity_id in set(same_delta_entity_ids):
        return
    row = conn.execute("select 1 from entities where id = ?", (entity_id,)).fetchone()
    if not row:
        errors.append(f"{path}: missing entity {entity_id}")


def _delta_upsert_ids(delta: dict[str, Any]) -> set[str]:
    return set(_delta_upsert_types(delta))


def _delta_upsert_types(delta: dict[str, Any]) -> dict[str, str]:
    entities = delta.get("upsert_entities", [])
    if not isinstance(entities, list):
        return {}
    ids: dict[str, str] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get("id")
        if isinstance(entity_id, str) and _ENTITY_ID_PATTERN.match(entity_id):
            entity_type = entity.get("type")
            ids[entity_id] = normalize_visibility_label(entity_type) if isinstance(entity_type, str) else ""
    return ids


def _validate_optional_entity_reference(
    errors: list[str],
    conn: sqlite3.Connection,
    entity_id: Any,
    path: str,
    same_delta_entity_ids: Iterable[str],
    *,
    required_type: str | None = None,
    same_delta_entity_types: dict[str, str] | None = None,
) -> None:
    if not isinstance(entity_id, str):
        _append_error_once(errors, f"{path}: must be non-empty string")
        return
    if entity_id != entity_id.strip():
        _append_error_once(errors, f"{path}: must not contain leading or trailing whitespace")
        return
    text = str(entity_id).strip()
    if not text:
        _append_error_once(errors, f"{path}: must be non-empty string")
        return
    before = len(errors)
    validate_entity_reference(errors, conn, text, path, same_delta_entity_ids)
    if len(errors) != before or required_type is None:
        return
    normalized_required = normalize_visibility_label(required_type)
    if same_delta_entity_types and text in same_delta_entity_types:
        if same_delta_entity_types[text] != normalized_required:
            _append_error_once(errors, f"{path}: must reference {normalized_required} entity {text}")
        return
    row = conn.execute("select type from entities where id = ?", (text,)).fetchone()
    if row and normalize_visibility_label(str(row["type"])) != normalized_required:
        _append_error_once(errors, f"{path}: must reference {normalized_required} entity {text}")


def _validate_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")


def _append_error_once(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)


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


def _entity_access_visibility_sql(view: str | None = PLAYER_VIEW) -> str:
    normalized = normalize_visibility_view(view)
    if can_read_hidden(normalized):
        return ""
    return (
        f"and {normalized_text_sql('e.visibility')} != 'hidden' "
        f"and ({normalized_text_sql('e.type')} != 'clock' or "
        f"{normalized_text_sql('coalesce(c.visibility, e.visibility)')} != 'hidden')"
    )


def _parse_details(text: str | None) -> dict[str, Any]:
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
