from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .entity_access import validate_delta_entity_references
from .progress_access import (
    has_visible_text,
    is_safe_visible_text,
    is_valid_clock_id,
    normalize_visible_text,
    validate_delta_progress_references,
)
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


def validate_delta_schema(
    delta: dict[str, Any],
    conn: sqlite3.Connection | None = None,
    *,
    caller_view: str | None = "maintenance",
) -> list[str]:
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
    validate_cross_field_rules(errors, delta, conn)
    if conn is not None:
        validate_database_refs(errors, delta, conn, caller_view=caller_view)
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
    if not isinstance(value, str) or not has_visible_text(value):
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
            require_safe_visible_string(errors, event, key, path_prefix=path)
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
            if is_valid_clock_id(entity_id):
                errors.append(f"{path}.id: clock entities must be mutated through tick_clocks")
            if entity_id in seen:
                errors.append(f"{path}.id: duplicate entity id {entity_id}")
            seen.add(entity_id)
        entity_type = str(entity.get("type", ""))
        if entity_type and entity_type not in ALLOWED_ENTITY_TYPES:
            errors.append(f"{path}.type: unsupported entity type {entity_type}")
        if entity_type == "clock":
            errors.append(f"{path}.type: clock entities must be mutated through tick_clocks")
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
        if isinstance(item.get("id"), str) and item["id"] != item["id"].strip():
            errors.append(f"{path}.id: must not contain leading or trailing whitespace")
        elif isinstance(item.get("id"), str) and item["id"].strip() and not is_valid_clock_id(item["id"]):
            errors.append(f"{path}.id: invalid clock id")
        if "delta" not in item:
            errors.append(f"{path}.delta: required")
        elif isinstance(item["delta"], bool) or not isinstance(item["delta"], int) or item["delta"] == 0:
            errors.append(f"{path}.delta: must be non-zero integer")
        if "reason" not in item:
            errors.append(f"{path}.reason: required")
        elif not is_safe_visible_text(item["reason"]):
            errors.append(f"{path}.reason: must be non-empty string when present")
        if (
            conn is not None
            and isinstance(item.get("id"), str)
            and item["id"].strip()
            and item["id"] == item["id"].strip()
            and is_valid_clock_id(item["id"])
        ):
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


def require_safe_visible_string(errors: list[str], value: dict[str, Any], key: str, *, path_prefix: str = "$") -> None:
    path = f"{path_prefix}.{key}"
    if key not in value:
        errors.append(f"{path}: required")
        return
    if not is_safe_visible_text(value[key]):
        errors.append(f"{path}: must be non-empty string")


def validate_cross_field_rules(
    errors: list[str],
    delta: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> None:
    changed = bool(delta.get("changed", True))
    has_state_change = any(delta.get(key) for key in ["meta", "upsert_entities", "tick_clocks"])
    has_events = bool(delta.get("events"))
    if changed and not (has_state_change or has_events):
        errors.append("$: changed turn must include events or state changes")
    if has_state_change and not has_events:
        errors.append("$: state-changing delta should include at least one event explaining the change")
    validate_progress_event_claims(errors, delta, conn)


def validate_progress_event_claims(
    errors: list[str],
    delta: dict[str, Any],
    conn: sqlite3.Connection | None = None,
) -> None:
    tick_clocks = delta.get("tick_clocks")
    ticked_clock_ids = _ticked_clock_ids(tick_clocks)
    clock_names = _clock_names(conn)
    top_level_claim = _top_level_progress_claim(delta, clock_names)
    if _progress_claim_needs_structured_tick(top_level_claim, ticked_clock_ids):
        errors.append("$: progress update narrative requires structured tick_clocks")
    events = delta.get("events")
    event_claims: list[dict[str, Any]] = []
    if not isinstance(events, list):
        events = []
    for index, event in enumerate(events):
        claim = _event_progress_claim(event, clock_names) if isinstance(event, dict) else _empty_progress_claim()
        event_claims.append(claim)
        if isinstance(event, dict) and _progress_claim_needs_structured_tick(claim, ticked_clock_ids):
            errors.append(f"$.events[{index}]: progress update event requires structured tick_clocks")
    _validate_tick_evidence(errors, tick_clocks, event_claims)


def _progress_claim_needs_structured_tick(claim: dict[str, Any], ticked_clock_ids: set[str]) -> bool:
    if not claim["claims_update"]:
        return False
    if not ticked_clock_ids:
        return True
    claimed_clock_ids = claim["clock_ids"]
    return bool(claim["unbound_progress_ids"] or (claimed_clock_ids and not claimed_clock_ids.issubset(ticked_clock_ids)))


def _ticked_clock_ids(tick_clocks: Any) -> set[str]:
    if not isinstance(tick_clocks, list):
        return set()
    return {item["id"] for item in tick_clocks if isinstance(item, dict) and isinstance(item.get("id"), str)}


def _empty_progress_claim() -> dict[str, Any]:
    return {"claims_update": False, "has_update_signal": False, "clock_ids": set(), "unbound_progress_ids": set()}


def _top_level_progress_claim(delta: dict[str, Any], clock_names: dict[str, str]) -> dict[str, Any]:
    texts = [str(delta.get("summary") or "")]
    user_text = str(delta.get("user_text") or "")
    if _contains_progress_identifier(user_text):
        texts.append(user_text)
    return _text_progress_claim(" ".join(texts), clock_names)


def _event_progress_claim(event: dict[str, Any], clock_names: dict[str, str]) -> dict[str, Any]:
    event_type = str(event.get("type") or "").strip().lower().replace("-", "_")
    text_claim = _text_progress_claim(" ".join(str(event.get(key) or "") for key in ("title", "summary")), clock_names)
    payload_claim = _payload_progress_claim(event.get("payload"), clock_names)
    return {
        "claims_update": (
            event_type in {"clock_tick", "clock_update", "progress_tick", "progress_update"}
            or text_claim["claims_update"]
            or payload_claim["claims_update"]
        ),
        "clock_ids": text_claim["clock_ids"] | payload_claim["clock_ids"],
        "unbound_progress_ids": text_claim["unbound_progress_ids"] | payload_claim["unbound_progress_ids"],
    }


def _text_progress_claim(text: str, clock_names: dict[str, str]) -> dict[str, Any]:
    text = normalize_visible_text(text)
    clock_ids = _narrative_ids(text, "clock")
    progress_ids = _narrative_ids(text, "progress")
    text_lower = text.lower()
    has_update_verb = _has_progress_update_verb(text_lower)
    clock_name_ids = {
        clock_id
        for clock_id, name in clock_names.items()
        if name and _clock_name_mentioned(text_lower, name) and has_update_verb
    }
    return {
        "claims_update": bool((clock_ids and has_update_verb) or (progress_ids and has_update_verb) or clock_name_ids),
        "has_update_signal": has_update_verb,
        "clock_ids": clock_ids | clock_name_ids,
        "unbound_progress_ids": progress_ids,
    }


def _payload_progress_claim(payload: Any, clock_names: dict[str, str]) -> dict[str, Any]:
    if isinstance(payload, list):
        merged = _empty_progress_claim()
        for item in payload:
            item_claim = _payload_progress_claim(item, clock_names)
            merged["has_update_signal"] = merged["has_update_signal"] or item_claim["has_update_signal"]
            merged["clock_ids"].update(item_claim["clock_ids"])
            merged["unbound_progress_ids"].update(item_claim["unbound_progress_ids"])
            merged["claims_update"] = merged["claims_update"] or item_claim["claims_update"]
        merged["claims_update"] = merged["claims_update"] or bool(
            merged["has_update_signal"] and (merged["clock_ids"] or merged["unbound_progress_ids"])
        )
        return merged
    if isinstance(payload, str):
        return _text_progress_claim(payload, clock_names)
    if not isinstance(payload, dict):
        return _empty_progress_claim()
    clock_ids: set[str] = set()
    progress_ids: set[str] = set()
    explicit_update = _payload_has_update_signal(payload)
    for key in payload:
        if isinstance(key, str) and is_valid_clock_id(key):
            clock_ids.add(key)
        elif isinstance(key, str) and re.fullmatch(r"progress:[A-Za-z0-9_.:-]+", key):
            progress_ids.add(key)
    for key in ("clock_id", "progress_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith("clock:"):
            clock_ids.add(value)
        elif isinstance(value, str) and value.startswith("progress:"):
            progress_ids.add(value)
    tick_clocks = payload.get("tick_clocks")
    if isinstance(tick_clocks, list):
        clock_ids.update(item["id"] for item in tick_clocks if isinstance(item, dict) and isinstance(item.get("id"), str))
    for value in payload.values():
        child_claim = _payload_progress_claim(value, clock_names)
        explicit_update = explicit_update or child_claim["has_update_signal"] or child_claim["claims_update"]
        clock_ids.update(child_claim["clock_ids"])
        progress_ids.update(child_claim["unbound_progress_ids"])
    return {
        "claims_update": bool(explicit_update),
        "has_update_signal": explicit_update,
        "clock_ids": clock_ids,
        "unbound_progress_ids": progress_ids,
    }


def _validate_tick_evidence(errors: list[str], tick_clocks: Any, event_claims: list[dict[str, Any]]) -> None:
    if not isinstance(tick_clocks, list):
        return
    claimed_clock_ids = set().union(*(claim["clock_ids"] for claim in event_claims)) if event_claims else set()
    for index, item in enumerate(tick_clocks):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        if "reason" in item and is_safe_visible_text(item["reason"]):
            continue
        clock_id = item["id"]
        if clock_id in claimed_clock_ids:
            continue
        errors.append(f"$.tick_clocks[{index}].reason: required when no event explains this clock tick")


def _contains_progress_identifier(text: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])(?:clock|progress):[A-Za-z0-9_.:-]+", normalize_visible_text(text)) is not None


def _narrative_ids(text: str, prefix: str) -> set[str]:
    ids: set[str] = set()
    for match in re.finditer(rf"(?<![A-Za-z0-9_]){prefix}:[A-Za-z0-9_.:-]+", text):
        value = match.group(0).rstrip(".,;!?")
        if value != f"{prefix}:":
            ids.add(value)
    return ids


def _payload_has_update_signal(payload: dict[str, Any]) -> bool:
    if "tick_clocks" in payload or "delta" in payload:
        return True
    progress_keys = {"segments_filled", "filled_segments", "segments", "filled", "progress"}
    if any(key in payload for key in progress_keys):
        return True
    status = payload.get("status")
    return isinstance(status, str) and status.strip().lower() in {
        "advanced",
        "complete",
        "completed",
        "done",
        "filled",
        "resolved",
    }


def _has_progress_update_verb(text_lower: str) -> bool:
    return re.search(
        r"(?:\b(?:advance|advances|advanced|tick|ticks|ticked|change|changes|changed|progressed|fill|fills|filled|segment|segments|complete|completes|completed|increase|increases|increased|move|moves|moved|forward|goes up|went up|escalate|escalates|escalated|resolve|resolves|resolved)\b|[0-9]+/[0-9]+|推进|推進|前进|前進|增加|变化|變化|改变|改變|填充|完成|上升|升级|升級|解决|解決|一段|一格|刻度|进度|進度)",
        text_lower,
    ) is not None


def _clock_names(conn: sqlite3.Connection | None) -> dict[str, str]:
    if conn is None:
        return {}
    try:
        rows = conn.execute(
            """
            select c.entity_id, e.name
            from clocks c
            join entities e on e.id = c.entity_id
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(row["entity_id"]): normalize_visible_text(str(row["name"])).strip().lower() for row in rows if str(row["name"]).strip()}


def _clock_name_mentioned(text_lower: str, name: str) -> bool:
    if len(name) < 3:
        return False
    escaped = re.escape(name)
    if re.fullmatch(r"[a-z0-9_ .:-]+", name):
        return re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text_lower) is not None
    return name in text_lower


def validate_database_refs(
    errors: list[str],
    delta: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    caller_view: str | None,
) -> None:
    for error in [
        *validate_delta_entity_references(conn, delta),
        *validate_delta_relationship_references(conn, delta),
        *validate_delta_progress_references(conn, delta, view=caller_view),
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
