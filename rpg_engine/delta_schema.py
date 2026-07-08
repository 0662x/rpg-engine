from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .entity_access import validate_delta_entity_references
from .relationship_access import validate_delta_relationship_references
from .resource_paths import schema_resource_text


TURN_ID_PATTERN = re.compile(r"^turn:(seed|[0-9]{6})$")
EVENT_ID_PATTERN = re.compile(r"^event:([0-9]{6}|seed):[0-9]{3}$|^event:seed$")
ENTITY_ID_PATTERN = re.compile(r"^[a-z]+:[A-Za-z0-9_.-]+$")
COMMAND_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")

ALLOWED_TOP_LEVEL = {
    "turn_id",
    "session_id",
    "user_text",
    "intent",
    "changed",
    "summary",
    "game_time_before",
    "game_time_after",
    "location_before",
    "location_after",
    "events",
    "upsert_entities",
    "tick_clocks",
    "meta",
    "expected_turn_id",
    "command_id",
}

ALLOWED_ENTITY_TYPES = {
    "character",
    "equipment",
    "item",
    "location",
    "material",
    "plant",
    "species",
    "faction",
    "faction_state",
    "threat",
    "rule",
    "clock",
    "project",
    "recipe",
    "reference",
    "relationship",
    "world_setting",
    "crop_plot",
}


def schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / "turn_delta.schema.json"


def validate_delta_schema(delta: dict[str, Any], conn: sqlite3.Connection | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(delta, dict):
        return ["$ must be an object"]

    unknown = sorted(set(delta) - ALLOWED_TOP_LEVEL)
    for key in unknown:
        errors.append(f"$.{key}: unknown top-level field")

    require_string(errors, delta, "user_text")
    require_string(errors, delta, "intent")
    require_string(errors, delta, "summary")

    if "turn_id" in delta and not TURN_ID_PATTERN.match(str(delta["turn_id"])):
        errors.append("$.turn_id: must match turn:000001 style")
    if "expected_turn_id" in delta and not TURN_ID_PATTERN.match(str(delta["expected_turn_id"])):
        errors.append("$.expected_turn_id: must match turn:000001 style")
    if "command_id" in delta and not COMMAND_ID_PATTERN.match(str(delta["command_id"])):
        errors.append("$.command_id: must be 3-128 safe identifier characters")
    if "changed" in delta and not isinstance(delta["changed"], bool):
        errors.append("$.changed: must be boolean")

    validate_optional_string(errors, delta, "session_id")
    validate_optional_string(errors, delta, "game_time_before")
    validate_optional_string(errors, delta, "game_time_after")
    validate_optional_string(errors, delta, "location_before")
    validate_optional_string(errors, delta, "location_after")

    validate_events(errors, delta.get("events"))
    validate_entities(errors, delta.get("upsert_entities"))
    validate_tick_clocks(errors, delta.get("tick_clocks"), conn)
    validate_meta(errors, delta.get("meta"))
    validate_cross_field_rules(errors, delta)
    if conn is not None:
        validate_database_refs(errors, delta, conn)
    return errors


def render_delta_validation(errors: list[str]) -> str:
    if not errors:
        return "OK"
    lines = ["FAILED"]
    lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)


def load_schema_text() -> str:
    try:
        return schema_resource_text("turn_delta.schema.json")
    except FileNotFoundError:
        path = schema_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return json.dumps({"title": "turn_delta", "type": "object"}, ensure_ascii=False, indent=2)


def require_string(errors: list[str], value: dict[str, Any], key: str, *, path_prefix: str = "$") -> None:
    path = f"{path_prefix}.{key}"
    if key not in value:
        errors.append(f"{path}: required")
        return
    validate_non_empty_string(errors, value[key], path)


def validate_optional_string(errors: list[str], value: dict[str, Any], key: str, *, path_prefix: str = "$") -> None:
    if key in value and value[key] is not None:
        validate_non_empty_string(errors, value[key], f"{path_prefix}.{key}")


def validate_non_empty_string(errors: list[str], value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: must be non-empty string")


def validate_events(errors: list[str], events: Any) -> None:
    if events is None:
        return
    if not isinstance(events, list):
        errors.append("$.events: must be array")
        return
    for index, event in enumerate(events):
        path = f"$.events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{path}: must be object")
            continue
        validate_optional_string(errors, event, "id", path_prefix=path)
        if "id" in event and event["id"] and not EVENT_ID_PATTERN.match(str(event["id"])):
            errors.append(f"{path}.id: must match event:000001:001 style")
        for key in ["type", "title", "summary", "source"]:
            require_string(errors, event, key, path_prefix=path)
        if "game_time" in event:
            validate_optional_string(errors, event, "game_time", path_prefix=path)
        payload = event.get("payload", {})
        if not isinstance(payload, (dict, list)):
            errors.append(f"{path}.payload: must be object or array")


def validate_entities(errors: list[str], entities: Any) -> None:
    if entities is None:
        return
    if not isinstance(entities, list):
        errors.append("$.upsert_entities: must be array")
        return
    seen: set[str] = set()
    for index, entity in enumerate(entities):
        path = f"$.upsert_entities[{index}]"
        if not isinstance(entity, dict):
            errors.append(f"{path}: must be object")
            continue
        for key in ["id", "type", "name", "summary"]:
            require_string(errors, entity, key, path_prefix=path)
        entity_id = str(entity.get("id", ""))
        if entity_id:
            if not ENTITY_ID_PATTERN.match(entity_id):
                errors.append(f"{path}.id: invalid entity id")
            if entity_id in seen:
                errors.append(f"{path}.id: duplicate entity id {entity_id}")
            seen.add(entity_id)
        entity_type = str(entity.get("type", ""))
        if entity_type and entity_type not in ALLOWED_ENTITY_TYPES:
            errors.append(f"{path}.type: unsupported entity type {entity_type}")
        if entity.get("owner_id") and entity.get("location_id"):
            errors.append(f"{path}: active entity cannot set both owner_id and location_id")
        aliases = entity.get("aliases", [])
        if aliases is not None:
            if not isinstance(aliases, list) or not all(isinstance(item, str) and item.strip() for item in aliases):
                errors.append(f"{path}.aliases: must be array of non-empty strings")
        details = entity.get("details", {})
        if details is not None and not isinstance(details, dict):
            errors.append(f"{path}.details: must be object")
        validate_entity_subrecords(errors, entity, path)


def validate_entity_subrecords(errors: list[str], entity: dict[str, Any], path: str) -> None:
    entity_type = str(entity.get("type", ""))
    if "item" in entity:
        item = entity["item"]
        if not isinstance(item, dict):
            errors.append(f"{path}.item: must be object")
        else:
            if "quantity" in item and item["quantity"] is not None and not isinstance(item["quantity"], (int, float)):
                errors.append(f"{path}.item.quantity: must be number")
            if "stackable" in item and not isinstance(item["stackable"], bool):
                errors.append(f"{path}.item.stackable: must be boolean")
    if entity_type in {"item", "equipment"} and "item" not in entity:
        errors.append(f"{path}.item: recommended and required by engine for item/equipment details")
    if "location" in entity and not isinstance(entity["location"], dict):
        errors.append(f"{path}.location: must be object")
    if "character" in entity:
        character = entity["character"]
        if not isinstance(character, dict):
            errors.append(f"{path}.character: must be object")
        elif "trust" in character and not isinstance(character["trust"], int):
            errors.append(f"{path}.character.trust: must be integer")
    if "crop_plot" in entity:
        crop_plot = entity["crop_plot"]
        if not isinstance(crop_plot, dict):
            errors.append(f"{path}.crop_plot: must be object")
        else:
            if "plot_no" not in crop_plot or isinstance(crop_plot["plot_no"], bool) or not isinstance(crop_plot["plot_no"], int):
                errors.append(f"{path}.crop_plot.plot_no: required integer")
            require_string(errors, crop_plot, "crop_entity_id", path_prefix=f"{path}.crop_plot")
    elif entity_type == "crop_plot":
        errors.append(f"{path}.crop_plot: required")


def validate_tick_clocks(errors: list[str], tick_clocks: Any, conn: sqlite3.Connection | None) -> None:
    if tick_clocks is None:
        return
    if not isinstance(tick_clocks, list):
        errors.append("$.tick_clocks: must be array")
        return
    for index, item in enumerate(tick_clocks):
        path = f"$.tick_clocks[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: must be object")
            continue
        require_string(errors, item, "id", path_prefix=path)
        if "delta" not in item:
            errors.append(f"{path}.delta: required")
        elif not isinstance(item["delta"], int) or item["delta"] == 0:
            errors.append(f"{path}.delta: must be non-zero integer")
        if conn is not None and item.get("id"):
            row = conn.execute("select 1 from clocks where entity_id = ?", (str(item["id"]),)).fetchone()
            if not row:
                errors.append(f"{path}.id: Missing clock {item['id']}")


def validate_meta(errors: list[str], meta: Any) -> None:
    if meta is None:
        return
    if not isinstance(meta, dict):
        errors.append("$.meta: must be object")
        return
    for key, value in meta.items():
        if not isinstance(key, str) or not key:
            errors.append("$.meta: keys must be non-empty strings")
        if isinstance(value, (dict, list)):
            errors.append(f"$.meta.{key}: must be scalar")


def validate_cross_field_rules(errors: list[str], delta: dict[str, Any]) -> None:
    changed = bool(delta.get("changed", True))
    has_state_change = any(delta.get(key) for key in ["meta", "upsert_entities", "tick_clocks"])
    has_events = bool(delta.get("events"))
    if changed and not (has_state_change or has_events):
        errors.append("$: changed turn must include events or state changes")
    if has_state_change and not has_events:
        errors.append("$: state-changing delta should include at least one event explaining the change")


def validate_database_refs(errors: list[str], delta: dict[str, Any], conn: sqlite3.Connection) -> None:
    for error in [
        *validate_delta_entity_references(conn, delta),
        *validate_delta_relationship_references(conn, delta),
    ]:
        if error not in errors:
            errors.append(error)


def validate_entity_ref(
    errors: list[str],
    conn: sqlite3.Connection,
    entity_id: str,
    path: str,
    upsert_ids: set[str],
) -> None:
    from .entity_access import validate_entity_reference

    validate_entity_reference(errors, conn, entity_id, path, upsert_ids)
