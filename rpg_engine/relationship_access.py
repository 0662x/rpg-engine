from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .entity_access import EntityRecord, list_entities, read_entity, validate_entity_reference
from .visibility import PLAYER_VIEW, can_read_hidden, normalize_visibility_label, normalize_visibility_view


_ENTITY_ID_PATTERN = re.compile(r"^[a-z]+:[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class RelationshipRecord:
    id: str
    source_id: str
    target_id: str
    kind: Any
    state: Any
    attitude: Any
    stance: Any
    trust: Any
    visibility: str
    status: str
    summary: str
    details: dict[str, Any]
    updated_turn_id: str
    updated_at: str
    source: EntityRecord | None = None
    target: EntityRecord | None = None
    endpoint_issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "state": self.state,
            "attitude": self.attitude,
            "stance": self.stance,
            "trust": self.trust,
            "visibility": self.visibility,
            "status": self.status,
            "summary": self.summary,
            "details": self.details,
            "updated_turn_id": self.updated_turn_id,
            "updated_at": self.updated_at,
            "source": self.source.to_dict() if self.source else None,
            "target": self.target.to_dict() if self.target else None,
            "endpoint_issues": list(self.endpoint_issues),
        }


def read_relationship(
    conn: sqlite3.Connection,
    relationship_id: str,
    *,
    view: str | None = PLAYER_VIEW,
    include_archived: bool = False,
) -> RelationshipRecord | None:
    relationship = read_entity(conn, relationship_id, view=view, include_archived=include_archived)
    if relationship is None or normalize_visibility_label(relationship.type) != "relationship":
        return None
    record = _relationship_from_entity(conn, relationship, view=view)
    if record.endpoint_issues and not can_read_hidden(normalize_visibility_view(view)):
        return None
    return record


def list_relationships(
    conn: sqlite3.Connection,
    *,
    view: str | None = PLAYER_VIEW,
    source_id: str | None = None,
    target_id: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> list[RelationshipRecord]:
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            return []
    records: list[RelationshipRecord] = []
    for entity in list_entities(
        conn,
        view=view,
        types="relationship",
        include_archived=include_archived,
    ):
        relationship = _relationship_from_entity(conn, entity, view=view)
        if relationship.endpoint_issues and not can_read_hidden(normalize_visibility_view(view)):
            continue
        if source_id is not None and relationship.source_id != source_id:
            continue
        if target_id is not None and relationship.target_id != target_id:
            continue
        records.append(relationship)
        if limit is not None and len(records) >= limit:
            break
    return records


def validate_delta_relationship_references(
    conn: sqlite3.Connection,
    delta: Any,
    *,
    extra_entity_ids: Iterable[str] | None = None,
) -> list[str]:
    if not isinstance(delta, dict):
        return []
    errors: list[str] = []
    same_delta_ids = _same_delta_entity_ids(delta, extra_entity_ids=extra_entity_ids)
    upsert_entities = delta.get("upsert_entities", [])
    if not isinstance(upsert_entities, list):
        return errors
    for index, entity in enumerate(upsert_entities):
        if not isinstance(entity, dict):
            continue
        if normalize_visibility_label(entity.get("type")) != "relationship":
            continue
        path = f"$.upsert_entities[{index}]"
        details = entity.get("details", {})
        if details is None:
            details = {}
        if not isinstance(details, dict):
            _append_error_once(errors, f"{path}.details: must be object")
            for field in ("source_id", "target_id"):
                _append_error_once(errors, f"{path}.details.{field}: required")
            continue
        for field in ("source_id", "target_id"):
            endpoint_path = f"{path}.details.{field}"
            if field not in details:
                _append_error_once(errors, f"{endpoint_path}: required")
                continue
            _validate_relationship_endpoint(errors, conn, details[field], endpoint_path, same_delta_ids)
    return errors


def _relationship_from_entity(
    conn: sqlite3.Connection,
    entity: EntityRecord,
    *,
    view: str | None,
) -> RelationshipRecord:
    details = dict(entity.details)
    source_id = _detail_string(details.get("source_id"))
    target_id = _detail_string(details.get("target_id"))
    source, source_issue = _endpoint_entity(conn, source_id, "source_id", view=view)
    target, target_issue = _endpoint_entity(conn, target_id, "target_id", view=view)
    issues = tuple(issue for issue in (source_issue, target_issue) if issue)
    return RelationshipRecord(
        id=entity.id,
        source_id=source_id or "",
        target_id=target_id or "",
        kind=details.get("kind"),
        state=details.get("state"),
        attitude=details.get("attitude"),
        stance=details.get("stance"),
        trust=details.get("trust"),
        visibility=entity.visibility,
        status=entity.status,
        summary=entity.summary,
        details=details,
        updated_turn_id=entity.updated_turn_id,
        updated_at=entity.updated_at,
        source=source,
        target=target,
        endpoint_issues=issues,
    )


def _endpoint_entity(
    conn: sqlite3.Connection,
    entity_id: str | None,
    field: str,
    *,
    view: str | None,
) -> tuple[EntityRecord | None, str | None]:
    if not entity_id:
        return None, f"{field}: required"
    normalized_view = normalize_visibility_view(view)
    if can_read_hidden(normalized_view):
        record = read_entity(conn, entity_id, view=view, include_archived=True)
        if record is None:
            return None, f"{field}: missing entity {entity_id}"
        if normalize_visibility_label(record.status) == "archived":
            return None, f"{field}: archived entity {entity_id}"
        return record, None
    record = read_entity(conn, entity_id, view=view, include_archived=False)
    if record is None:
        return None, f"{field}: unavailable entity {entity_id}"
    return record, None


def _validate_relationship_endpoint(
    errors: list[str],
    conn: sqlite3.Connection,
    entity_id: Any,
    path: str,
    same_delta_entity_ids: Iterable[str],
) -> None:
    if not isinstance(entity_id, str):
        _append_error_once(errors, f"{path}: must be non-empty string")
        return
    if entity_id != entity_id.strip():
        _append_error_once(errors, f"{path}: must not contain leading or trailing whitespace")
        return
    if not entity_id.strip():
        _append_error_once(errors, f"{path}: must be non-empty string")
        return
    before = len(errors)
    validate_entity_reference(errors, conn, entity_id, path, same_delta_entity_ids)
    if len(errors) == before:
        return


def _same_delta_entity_ids(delta: dict[str, Any], *, extra_entity_ids: Iterable[str] | None = None) -> set[str]:
    ids: set[str] = set()
    for entity_id in extra_entity_ids or ():
        if isinstance(entity_id, str) and _ENTITY_ID_PATTERN.match(entity_id):
            ids.add(entity_id)
    upsert_entities = delta.get("upsert_entities", [])
    if not isinstance(upsert_entities, list):
        return ids
    for entity in upsert_entities:
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get("id")
        if isinstance(entity_id, str) and _ENTITY_ID_PATTERN.match(entity_id):
            ids.add(entity_id)
    return ids


def _detail_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _append_error_once(errors: list[str], error: str) -> None:
    if error not in errors:
        errors.append(error)
