from __future__ import annotations

from typing import Any

from .base import ContentRuntime, ContentTypeSpec, MergePolicy
from .registry import ContentRegistry
from ..progress_access import is_valid_clock_id


def _require_strings(record: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for key in keys:
        if not isinstance(record.get(key), str) or not str(record.get(key, "")).strip():
            errors.append(f"{key}: required non-empty string")
    return errors


def _validate_aliases(record: dict[str, Any]) -> list[str]:
    aliases = record.get("aliases", [])
    if aliases is None:
        return []
    if not isinstance(aliases, list) or not all(isinstance(item, str) and item.strip() for item in aliases):
        return ["aliases: must be an array of non-empty strings"]
    return []


def validate_entity_record(record: dict[str, Any]) -> list[str]:
    from ..delta_schema import ALLOWED_ENTITY_TYPES, ENTITY_ID_PATTERN

    errors = _require_strings(record, ("id", "type", "name", "summary"))
    entity_id = str(record.get("id", ""))
    if entity_id and not ENTITY_ID_PATTERN.match(entity_id):
        errors.append("id: invalid entity id")
    entity_type = str(record.get("type", ""))
    if entity_type and entity_type not in ALLOWED_ENTITY_TYPES:
        errors.append(f"type: unsupported entity type {entity_type}")
    if record.get("owner_id") and record.get("location_id"):
        errors.append("active entity cannot set both owner_id and location_id")
    if "details" in record and not isinstance(record.get("details"), dict):
        errors.append("details: must be object")
    if "item" in record and not isinstance(record.get("item"), dict):
        errors.append("item: must be object")
    if "character" in record and not isinstance(record.get("character"), dict):
        errors.append("character: must be object")
    if "location" in record and not isinstance(record.get("location"), dict):
        errors.append("location: must be object")
    if "crop_plot" in record:
        crop_plot = record.get("crop_plot")
        if not isinstance(crop_plot, dict):
            errors.append("crop_plot: must be object")
        else:
            if "plot_no" not in crop_plot or isinstance(crop_plot.get("plot_no"), bool) or not isinstance(crop_plot.get("plot_no"), int):
                errors.append("crop_plot.plot_no: required integer")
            if not isinstance(crop_plot.get("crop_entity_id"), str) or not str(crop_plot.get("crop_entity_id", "")).strip():
                errors.append("crop_plot.crop_entity_id: required non-empty string")
    elif entity_type == "crop_plot":
        errors.append("crop_plot: required")
    return [*errors, *_validate_aliases(record)]


def validate_rule_record(record: dict[str, Any]) -> list[str]:
    errors = _require_strings(record, ("id", "statement"))
    if record.get("id") and not str(record["id"]).startswith("rule:"):
        errors.append("id: rule id must start with rule:")
    for key in ("examples", "exceptions"):
        if key in record and not isinstance(record.get(key), list):
            errors.append(f"{key}: must be array")
    return [*errors, *_validate_aliases(record)]


def validate_clock_record(record: dict[str, Any]) -> list[str]:
    errors = _require_strings(record, ("id", "name", "trigger_when_full"))
    if record.get("id") and not is_valid_clock_id(record["id"]):
        errors.append("id: invalid clock id")
    total = record.get("segments_total")
    filled = record.get("segments_filled", 0)
    if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
        errors.append("segments_total: must be positive integer")
    if not isinstance(filled, int) or isinstance(filled, bool) or filled < 0:
        errors.append("segments_filled: must be non-negative integer")
    elif isinstance(total, int) and filled > total:
        errors.append("segments_filled: cannot exceed segments_total")
    return [*errors, *_validate_aliases(record)]


def validate_route_record(record: dict[str, Any]) -> list[str]:
    errors = _require_strings(record, ("id", "from_location_id", "to_location_id"))
    minutes = record.get("travel_minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
        errors.append("travel_minutes: must be positive integer")
    for key in ("hazards", "requirements"):
        if key in record and not isinstance(record.get(key), list):
            errors.append(f"{key}: must be array")
    return errors


def validate_relationship_record(record: dict[str, Any]) -> list[str]:
    errors = _require_strings(record, ("id", "name", "summary", "source_id", "target_id"))
    if record.get("id") and not str(record["id"]).startswith("rel:"):
        errors.append("id: relationship id must start with rel:")
    if "visibility" in record and str(record.get("visibility")) not in {"known", "hinted", "hidden"}:
        errors.append("visibility: must be known/hinted/hidden")
    if "details" in record and not isinstance(record.get("details"), dict):
        errors.append("details: must be object")
    return [*errors, *_validate_aliases(record)]


def _record_id(record: dict[str, Any]) -> str:
    return str(record["id"])


def _upsert_entity(runtime: ContentRuntime, record: dict[str, Any]) -> None:
    from ..db import upsert_entity

    entity = dict(record)
    entity.setdefault("updated_turn_id", runtime.turn_id)
    upsert_entity(runtime.conn, entity)


def _upsert_rule(runtime: ContentRuntime, record: dict[str, Any]) -> None:
    from ..db import upsert_rule

    upsert_rule(runtime.conn, dict(record))
    runtime.conn.execute(
        "update entities set updated_turn_id = ?, updated_at = ? where id = ?",
        (runtime.turn_id, runtime.now, str(record["id"])),
    )


def _upsert_clock(runtime: ContentRuntime, record: dict[str, Any]) -> None:
    from ..db import upsert_clock

    clock = dict(record)
    clock.setdefault("last_ticked_turn_id", runtime.turn_id)
    upsert_clock(runtime.conn, clock)


def _upsert_route(runtime: ContentRuntime, record: dict[str, Any]) -> None:
    from ..db import upsert_route

    route = dict(record)
    route.setdefault("last_verified_turn_id", runtime.turn_id)
    upsert_route(runtime.conn, route)


def _upsert_relationship(runtime: ContentRuntime, record: dict[str, Any]) -> None:
    from ..db import upsert_entity

    details = dict(record.get("details", {}) or {})
    for key in ("source_id", "target_id", "state", "trust", "stance", "notes"):
        if key in record:
            details[key] = record[key]
    entity = {
        "id": record["id"],
        "type": "relationship",
        "name": record["name"],
        "status": record.get("status", "active"),
        "visibility": record.get("visibility", "known"),
        "summary": record["summary"],
        "details": details,
        "aliases": record.get("aliases", []),
        "updated_turn_id": runtime.turn_id,
    }
    upsert_entity(runtime.conn, entity)


def register_core_content_types(registry: ContentRegistry) -> None:
    entity_merge = MergePolicy(
        author_owned={"name", "summary", "visibility"},
        runtime_owned={"status", "location_id", "owner_id", "item", "character", "location", "crop_plot"},
        mergeable={"aliases"},
        conflict_only={"id", "type", "details"},
    )
    registry.register(
        ContentTypeSpec(
            name="entity",
            campaign_key="entities",
            yaml_key="entities",
            delta_key="upsert_entities",
            table="entities",
            count_key="entities",
            payload_key="entities",
            upsert=_upsert_entity,
            validate_record=validate_entity_record,
            record_id=_record_id,
            merge_policy=entity_merge,
        )
    )
    registry.register(
        ContentTypeSpec(
            name="rule",
            campaign_key="rules",
            yaml_key="rules",
            delta_key="upsert_rules",
            entity_type="rule",
            table="rules",
            count_key="rules",
            payload_key="rules",
            upsert=_upsert_rule,
            validate_record=validate_rule_record,
            record_id=_record_id,
            merge_policy=MergePolicy(
                author_owned={"statement", "priority", "scope", "examples", "exceptions"},
                mergeable={"aliases"},
                conflict_only={"id"},
            ),
        )
    )
    registry.register(
        ContentTypeSpec(
            name="clock",
            campaign_key="clocks",
            yaml_key="clocks",
            entity_type="clock",
            table="clocks",
            upsert=_upsert_clock,
            validate_record=validate_clock_record,
            record_id=_record_id,
            merge_policy=MergePolicy(
                author_owned={"name", "clock_type", "segments_total", "visibility", "trigger_when_full", "tick_rules"},
                runtime_owned={"segments_filled", "last_ticked_turn_id"},
                mergeable={"aliases"},
                conflict_only={"id"},
            ),
        )
    )
    registry.register(
        ContentTypeSpec(
            name="route",
            campaign_key="routes",
            yaml_key="routes",
            delta_key="upsert_routes",
            table="routes",
            count_key="routes",
            payload_key="routes",
            upsert=_upsert_route,
            validate_record=validate_route_record,
            record_id=_record_id,
            merge_policy=MergePolicy(
                author_owned={"from_location_id", "to_location_id", "travel_minutes", "hazards", "requirements"},
                runtime_owned={"last_verified_turn_id"},
                conflict_only={"id"},
            ),
        )
    )
    registry.register(
        ContentTypeSpec(
            name="relationship",
            campaign_key="relationships",
            yaml_key="relationships",
            delta_key=None,
            entity_type="relationship",
            table="entities",
            count_key="relationships",
            payload_key="relationships",
            upsert=_upsert_relationship,
            validate_record=validate_relationship_record,
            record_id=_record_id,
            merge_policy=MergePolicy(
                author_owned={"name", "summary", "visibility", "source_id", "target_id", "state", "stance", "notes"},
                runtime_owned={"trust", "status"},
                mergeable={"aliases"},
                conflict_only={"id", "details"},
            ),
        )
    )
