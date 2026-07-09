from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .campaign import Campaign, load_yaml_file
from .content_types import ContentRegistry, ContentTypeSpec, get_default_registry
from .relationship_access import validate_delta_relationship_references
from .visibility import is_player_hidden_visibility


CONTENT_METADATA_KEYS = {
    "title",
    "description",
    "summary",
    "intent",
    "event_type",
    "source",
    "updated_turn_id",
    "turn_id",
    "session_id",
    "user_text",
    "event_id",
    "game_time",
    "changed",
    "events",
    "meta",
    "expected_turn_id",
    "command_id",
}
TURN_ID_PATTERN = re.compile(r"^turn:(seed|[0-9]{6})$")
COMMAND_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")


@dataclass(frozen=True)
class ContentValidationResult:
    errors: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = ["OK" if self.ok else "FAILED"]
        lines.extend(f"- warning: {warning}" for warning in self.warnings)
        lines.extend(f"- {error}" for error in self.errors)
        return "\n".join(lines) + "\n"


def validate_content_delta(
    delta: Any,
    conn: sqlite3.Connection,
    *,
    registry: ContentRegistry | None = None,
    extra_created_entity_ids: set[str] | None = None,
    extra_created_rule_ids: set[str] | None = None,
    extra_created_clock_ids: set[str] | None = None,
) -> ContentValidationResult:
    if not isinstance(delta, dict):
        return ContentValidationResult(["$: must be object"])

    registry = registry or get_default_registry()
    delta_specs = registry.delta_specs()
    known_delta_keys = {spec.delta_key for spec in delta_specs if spec.delta_key}
    allowed = CONTENT_METADATA_KEYS | known_delta_keys
    errors: list[str] = []

    for key in sorted(set(delta) - allowed):
        errors.append(f"$.{key}: unknown top-level field")

    for key in sorted(set(delta)):
        if key.startswith("upsert_") and key not in known_delta_keys:
            message = f"$.{key}: unregistered content delta key"
            if message not in errors:
                errors.append(message)

    validate_metadata(delta, errors)
    created = collect_created_records(delta, delta_specs, errors)

    for spec in delta_specs:
        key = spec.delta_key
        if not key or key not in delta:
            continue
        records = delta[key]
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            path = f"$.{key}[{index}]"
            if not isinstance(record, dict):
                continue
            if spec.validate_record:
                errors.extend(f"{path}.{error}" for error in spec.validate_record(record))

    validate_references(
        delta,
        conn,
        created,
        errors,
        extra_created_entity_ids=extra_created_entity_ids,
        extra_created_rule_ids=extra_created_rule_ids,
        extra_created_clock_ids=extra_created_clock_ids,
    )
    warnings = high_impact_warnings(delta, conn)
    return ContentValidationResult(dedupe(errors), dedupe(warnings))


def validate_content_sources(
    campaign: Campaign,
    conn: sqlite3.Connection,
    specs: list[ContentTypeSpec],
    *,
    registry: ContentRegistry | None = None,
) -> ContentValidationResult:
    registry = registry or get_default_registry()
    pseudo_delta: dict[str, Any] = {
        "title": "campaign content preflight",
        "description": "validate registered campaign content before sync",
    }
    errors: list[str] = []
    extra_created_entity_ids: set[str] = set()
    extra_created_rule_ids: set[str] = set()
    extra_created_clock_ids: set[str] = set()
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        if not spec.campaign_key or not spec.yaml_key:
            continue
        collected: list[dict[str, Any]] = []
        for path in campaign.content_files(spec.campaign_key):
            data = load_yaml_file(path)
            relative = campaign.display_path(path)
            records, shape_errors = content_source_records(data, spec, relative)
            if shape_errors:
                errors.extend(shape_errors)
                continue
            for index, record in enumerate(records):
                if spec.validate_record and not spec.delta_key:
                    errors.extend(
                        f"{relative}.{spec.yaml_key}[{index}].{error}"
                        for error in spec.validate_record(record)
                    )
                collected.append(record)
        records_by_type[spec.name] = collected
        collect_extra_created_ref_ids(
            spec,
            collected,
            entity_ids=extra_created_entity_ids,
            rule_ids=extra_created_rule_ids,
            clock_ids=extra_created_clock_ids,
        )
        if spec.delta_key:
            pseudo_delta[spec.delta_key] = collected
    delta_result = validate_content_delta(
        pseudo_delta,
        conn,
        registry=registry,
        extra_created_entity_ids=extra_created_entity_ids,
        extra_created_rule_ids=extra_created_rule_ids,
        extra_created_clock_ids=extra_created_clock_ids,
    )
    errors.extend(delta_result.errors)
    if "relationship" in records_by_type:
        errors.extend(
            validate_relationship_refs(
                records_by_type["relationship"],
                conn,
                content_record_ids(registry.get("entity"), records_by_type.get("entity", [])),
                prefix="relationship",
            )
        )
    return ContentValidationResult(dedupe(errors))


def collect_extra_created_ref_ids(
    spec: ContentTypeSpec,
    records: list[dict[str, Any]],
    *,
    entity_ids: set[str],
    rule_ids: set[str],
    clock_ids: set[str],
) -> None:
    ids = {content_record_id(spec, record) for record in records}
    ids.discard("")
    if spec.name != "route":
        entity_ids.update(ids)
    if spec.name == "rule":
        rule_ids.update(ids)
    if spec.name == "clock":
        clock_ids.update(ids)


def content_record_id(spec: ContentTypeSpec, record: dict[str, Any]) -> str:
    if spec.record_id:
        return str(spec.record_id(record) or "")
    return str(record.get("id") or "")


def content_record_ids(spec: ContentTypeSpec, records: list[dict[str, Any]]) -> set[str]:
    ids = {content_record_id(spec, record) for record in records}
    ids.discard("")
    return ids


def content_source_records(data: Any, spec: ContentTypeSpec, relative: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(data, dict):
        return [], [f"{relative}: must be object"]
    if not spec.yaml_key:
        return [], []
    if spec.yaml_key not in data:
        return [], [f"{relative}.{spec.yaml_key}: required"]
    raw_records = data[spec.yaml_key]
    if not isinstance(raw_records, list):
        return [], [f"{relative}.{spec.yaml_key}: must be array"]
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, record in enumerate(raw_records):
        if not isinstance(record, dict):
            errors.append(f"{relative}.{spec.yaml_key}[{index}]: must be object")
            continue
        records.append(record)
    return records, errors


def validate_metadata(delta: dict[str, Any], errors: list[str]) -> None:
    for key in ("title", "description", "summary", "intent", "event_type", "source", "session_id", "user_text", "game_time"):
        if key in delta and (not isinstance(delta[key], str) or not delta[key].strip()):
            errors.append(f"$.{key}: must be non-empty string")
    for key in ("turn_id", "updated_turn_id", "expected_turn_id"):
        if key in delta and delta[key] is not None and not TURN_ID_PATTERN.match(str(delta[key])):
            errors.append(f"$.{key}: must match turn:000001 style")
    if "command_id" in delta and not COMMAND_ID_PATTERN.match(str(delta["command_id"])):
        errors.append("$.command_id: must be 3-128 safe identifier characters")
    if "changed" in delta and not isinstance(delta["changed"], bool):
        errors.append("$.changed: must be boolean")
    if "events" in delta and not isinstance(delta["events"], list):
        errors.append("$.events: must be array")
    if "meta" in delta:
        meta = delta["meta"]
        if not isinstance(meta, dict):
            errors.append("$.meta: must be object")
        elif not all(isinstance(key, str) and isinstance(value, (str, int, float, bool)) for key, value in meta.items()):
            errors.append("$.meta: keys must be strings and values must be scalar")


def collect_created_records(delta: dict[str, Any], specs: list[Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    created: dict[str, dict[str, Any]] = {}
    owners: dict[str, str] = {}
    for spec in specs:
        key = spec.delta_key
        if not key or key not in delta:
            continue
        records = delta[key]
        if not isinstance(records, list):
            errors.append(f"$.{key}: must be array")
            continue
        seen: set[str] = set()
        for index, record in enumerate(records):
            path = f"$.{key}[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{path}: must be object")
                continue
            record_id = str(record.get("id", ""))
            if record_id:
                if record_id in seen:
                    errors.append(f"{path}.id: duplicate record id {record_id}")
                seen.add(record_id)
                if record_id in owners and owners[record_id] != key:
                    errors.append(f"{path}.id: record id {record_id} also appears in $.{owners[record_id]}")
                owners[record_id] = key
                created[record_id] = record
    return created


def validate_references(
    delta: dict[str, Any],
    conn: sqlite3.Connection,
    created: dict[str, dict[str, Any]],
    errors: list[str],
    *,
    extra_created_entity_ids: set[str] | None = None,
    extra_created_rule_ids: set[str] | None = None,
    extra_created_clock_ids: set[str] | None = None,
) -> None:
    created_rule_ids = ids_for_key(delta, "upsert_rules") | set(extra_created_rule_ids or set())
    created_world_ids = ids_for_key(delta, "upsert_world_settings")
    created_clock_ids = set(extra_created_clock_ids or set())
    created_entity_ids = (
        ids_for_key(delta, "upsert_entities")
        | created_rule_ids
        | created_world_ids
        | created_clock_ids
        | set(extra_created_entity_ids or set())
    )
    for error in validate_delta_relationship_references(conn, delta, extra_entity_ids=created_entity_ids):
        if error not in errors:
            errors.append(error)

    for index, entity in enumerate(records_for_key(delta, "upsert_entities")):
        if not isinstance(entity, dict):
            continue
        path = f"$.upsert_entities[{index}]"
        if entity.get("type") in {"item", "equipment"} and "item" not in entity:
            if not conn.execute("select 1 from items where entity_id = ?", (str(entity.get("id", "")),)).fetchone():
                errors.append(f"{path}.item: required for new item/equipment")
        for field in ("location_id", "owner_id"):
            target = entity.get(field)
            if target and not entity_exists(conn, str(target), created_entity_ids):
                errors.append(f"{path}.{field}: missing entity {target}")
        character = entity.get("character")
        if isinstance(character, dict) and character.get("species_id"):
            target = str(character["species_id"])
            if not entity_exists(conn, target, created_entity_ids):
                errors.append(f"{path}.character.species_id: missing entity {target}")
        location = entity.get("location")
        if isinstance(location, dict) and location.get("parent_id"):
            target = str(location["parent_id"])
            if not location_exists(conn, target, created):
                errors.append(f"{path}.location.parent_id: missing location {target}")
        plot = entity.get("crop_plot")
        if isinstance(plot, dict) and plot.get("crop_entity_id"):
            target = str(plot["crop_entity_id"])
            if not entity_exists(conn, target, created_entity_ids):
                errors.append(f"{path}.crop_plot.crop_entity_id: missing entity {target}")

    for index, route in enumerate(records_for_key(delta, "upsert_routes")):
        if not isinstance(route, dict):
            continue
        path = f"$.upsert_routes[{index}]"
        for field in ("from_location_id", "to_location_id"):
            target = route.get(field)
            if target and not location_exists(conn, str(target), created):
                errors.append(f"{path}.{field}: missing location {target}")

    for index, setting in enumerate(records_for_key(delta, "upsert_world_settings")):
        if not isinstance(setting, dict):
            continue
        path = f"$.upsert_world_settings[{index}]"
        for target in setting.get("linked_rules", []) if isinstance(setting.get("linked_rules", []), list) else []:
            if str(target) not in created_rule_ids and not table_entity_exists(conn, "rules", str(target)):
                errors.append(f"{path}.linked_rules: missing rule {target}")
        for target in setting.get("linked_clocks", []) if isinstance(setting.get("linked_clocks", []), list) else []:
            if str(target) not in created_clock_ids and not table_entity_exists(conn, "clocks", str(target)):
                errors.append(f"{path}.linked_clocks: missing clock {target}")
        for target in setting.get("linked_entities", []) if isinstance(setting.get("linked_entities", []), list) else []:
            if not entity_exists(conn, str(target), created_entity_ids):
                errors.append(f"{path}.linked_entities: missing entity {target}")


def validate_relationship_refs(
    relationships: list[dict[str, Any]],
    conn: sqlite3.Connection,
    created_entity_ids: set[str],
    *,
    prefix: str,
) -> list[str]:
    errors: list[str] = []
    for index, relationship in enumerate(relationships):
        for field in ("source_id", "target_id"):
            top_level_target = relationship.get(field)
            details = relationship.get("details")
            details_target = details.get(field) if isinstance(details, dict) else None
            if top_level_target and details_target and str(top_level_target) != str(details_target):
                errors.append(f"{prefix}[{index}].details.{field}: must match {field} {top_level_target}")
            for path, target in relationship_endpoint_values(index, field, top_level_target, details_target, prefix=prefix):
                if target and str(target) not in created_entity_ids and not entity_exists(conn, str(target), set()):
                    errors.append(f"{path}: missing entity {target}")
    return errors


def relationship_endpoint_values(
    index: int,
    field: str,
    top_level_target: Any,
    details_target: Any,
    *,
    prefix: str,
) -> tuple[tuple[str, Any], ...]:
    values: list[tuple[str, Any]] = []
    if top_level_target:
        values.append((f"{prefix}[{index}].{field}", top_level_target))
    if details_target:
        values.append((f"{prefix}[{index}].details.{field}", details_target))
    return tuple(values)


def records_for_key(delta: dict[str, Any], key: str) -> list[Any]:
    value = delta.get(key, [])
    return value if isinstance(value, list) else []


def ids_for_key(delta: dict[str, Any], key: str) -> set[str]:
    return {
        str(record["id"])
        for record in records_for_key(delta, key)
        if isinstance(record, dict) and record.get("id")
    }


def entity_exists(conn: sqlite3.Connection, entity_id: str, created_ids: set[str]) -> bool:
    if entity_id in created_ids:
        return True
    return bool(conn.execute("select 1 from entities where id = ?", (entity_id,)).fetchone())


def location_exists(conn: sqlite3.Connection, entity_id: str, created: dict[str, dict[str, Any]]) -> bool:
    record = created.get(entity_id)
    if record is not None:
        return record.get("type") == "location" or isinstance(record.get("location"), dict)
    return bool(
        conn.execute(
            "select 1 from entities where id = ? and type = 'location'",
            (entity_id,),
        ).fetchone()
    )


def table_entity_exists(conn: sqlite3.Connection, table: str, entity_id: str) -> bool:
    return bool(conn.execute(f"select 1 from {table} where entity_id = ?", (entity_id,)).fetchone())


def high_impact_warnings(delta: dict[str, Any], conn: sqlite3.Connection) -> list[str]:
    warnings: list[str] = []
    meta = delta.get("meta", {})
    reviewed = isinstance(meta, dict) and bool(meta.get("reviewed_by") or meta.get("review_required"))
    for index, entity in enumerate(records_for_key(delta, "upsert_entities")):
        if not isinstance(entity, dict):
            continue
        entity_type = str(entity.get("type", ""))
        entity_id = str(entity.get("id", ""))
        rarity = str(nested_lookup(entity, ("details", "rarity")) or nested_lookup(entity, ("details", "resource_profile", "rarity")) or "")
        if entity_type in {"location", "faction", "faction_state", "world_setting"}:
            warnings.append(review_warning(f"$.upsert_entities[{index}] creates or updates high-impact {entity_type} {entity_id}", reviewed))
        if entity_type == "species" and rarity in {"rare", "very_rare", "hidden", "legendary"}:
            warnings.append(review_warning(f"$.upsert_entities[{index}] creates or updates rare species {entity_id}", reviewed))
        existing = existing_entity(conn, entity_id)
        if existing and promotes_to_known_review_boundary(existing.get("visibility"), entity.get("visibility", existing.get("visibility"))):
            warnings.append(review_warning(f"$.upsert_entities[{index}] promotes {entity_id} from {existing['visibility']} to known", reviewed))
    for index, route in enumerate(records_for_key(delta, "upsert_routes")):
        if isinstance(route, dict):
            warnings.append(review_warning(f"$.upsert_routes[{index}] creates or updates route {route.get('id', '')}", reviewed))
    for index, rule in enumerate(records_for_key(delta, "upsert_rules")):
        if isinstance(rule, dict):
            warnings.append(review_warning(f"$.upsert_rules[{index}] creates or updates rule {rule.get('id', '')}", reviewed))
    for index, setting in enumerate(records_for_key(delta, "upsert_world_settings")):
        if isinstance(setting, dict):
            warnings.append(review_warning(f"$.upsert_world_settings[{index}] creates or updates world_setting {setting.get('id', '')}", reviewed))
    return warnings


def review_warning(message: str, reviewed: bool) -> str:
    suffix = "review marker present" if reviewed else "requires meta.review_required=true or meta.reviewed_by"
    return f"{message}; {suffix}"


def promotes_to_known_review_boundary(existing_visibility: Any, next_visibility: Any) -> bool:
    return str(next_visibility) == "known" and (
        str(existing_visibility) == "hinted" or is_player_hidden_visibility(str(existing_visibility))
    )


def existing_entity(conn: sqlite3.Connection, entity_id: str) -> dict[str, Any] | None:
    if not entity_id:
        return None
    row = conn.execute("select id, type, visibility, details_json from entities where id = ?", (entity_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "type": row["type"],
        "visibility": row["visibility"],
        "details": parse_json(row["details_json"], {}),
    }


def nested_lookup(value: Any, keys: tuple[str, ...]) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def parse_json(text: Any, default: Any) -> Any:
    if not isinstance(text, str) or not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
