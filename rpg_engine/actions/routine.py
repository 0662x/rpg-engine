from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..preview import current_location_row
from ..redaction import redact_hidden_entity_refs
from ..ux import RepairOption
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .slot_contract import ActionRequirementGroupSpec
from .taxonomy import ActionTaxonomySpec, taxonomy_term_matches, taxonomy_terms


ROUTINE_TAXONOMY = ActionTaxonomySpec(
    terms=(
        *taxonomy_terms(
            "zh-Hans",
            ("盘点", "整理库存", "查看库存", "看看物资", "清点"),
            roles=("inventory", "preview.mismatch", "simple", "template.inventory"),
        ),
        *taxonomy_terms("zh-Hans", ("库存", "物资"), roles=("template.inventory",)),
        *taxonomy_terms(
            "en",
            ("inventory", "audit"),
            roles=("inventory", "preview.mismatch", "simple", "template.inventory"),
        ),
        *taxonomy_terms(
            "zh-Hans",
            (
                "巡查",
                "照看",
                "维护",
            ),
            roles=("preview.mismatch", "simple", "template.upkeep"),
        ),
        *taxonomy_terms(
            "zh-Hans",
            (
                "巡视",
                "巡逻",
                "巡检",
                "查看各单位",
                "查看各角色",
                "各单位和角色",
                "领地状态",
                "单位状态",
                "角色状态",
                "浇水",
                "灌溉",
                "喂养",
                "喂食",
            ),
            roles=("preview.mismatch", "simple"),
        ),
        *taxonomy_terms("zh-Hans", ("日常", "例行")),
        *taxonomy_terms(
            "zh-Hans",
            ("整理", "喂", "吃饭", "灌", "金光"),
            roles=("simple", "template.upkeep"),
        ),
        *taxonomy_terms("zh-Hans", ("检查",), roles=("context.explore", "template.upkeep")),
        *taxonomy_terms("en", ("patrol", "upkeep", "maintenance", "daily", "care")),
        *taxonomy_terms("en", ("check",), roles=("context.explore", "template.upkeep")),
    ),
    semantic_labels=("routine", "upkeep", "maintenance", "daily", "care", "check"),
    inference_priority=65,
)


@dataclass(frozen=True)
class RoutineTemplate:
    id: str
    labels: tuple[str, ...]
    taxonomy_role: str
    default_time_minutes: int
    allowed_scope: str
    risk_level: str
    produces_delta: bool = True
    requires_confirmation: bool = False


ROUTINE_TEMPLATES = (
    RoutineTemplate(
        id="routine:inventory-audit",
        labels=("盘点库存", "整理库存", "查看物资"),
        taxonomy_role="template.inventory",
        default_time_minutes=5,
        allowed_scope="base",
        risk_level="none",
        produces_delta=False,
    ),
    RoutineTemplate(
        id="routine:upkeep",
        labels=("日常维护", "检查", "整理"),
        taxonomy_role="template.upkeep",
        default_time_minutes=10,
        allowed_scope="current_location",
        risk_level="low",
    ),
)

_CONSUMPTION_KEYS = ("consumed_item_id", "before_quantity", "consumed_quantity", "after_quantity")
_CONSUMPTION_PREFIX = "routine consumption:"
_SQLITE_INTEGER_MIN = -(2**63)
_SQLITE_INTEGER_MAX = 2**63 - 1
_ENTITY_METADATA_KEYS = (
    "type",
    "name",
    "status",
    "visibility",
    "location_id",
    "owner_id",
    "summary",
    "details",
)
_ITEM_METADATA_KEYS = (
    "category",
    "unit",
    "quality",
    "durability_current",
    "durability_max",
    "stackable",
    "equipped_slot",
    "properties",
)
_TARGET_ITEM_KEYS = {"quantity", *_ITEM_METADATA_KEYS}
_TARGET_UPSERT_KEYS = {"id", "aliases", "item", *_ENTITY_METADATA_KEYS}


def preview_routine(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    del campaign, context
    template = routine_template(options)
    current = current_location_row(conn, get_meta(conn))
    can_generate_delta = bool(current or (template and not template.produces_delta))
    lines = [
        "## 日常维护行动预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 行动 | {option_value(options, 'task') or option_value(options, 'user_text') or '未明确'} |",
        f"| 对象 | {option_value(options, 'target') or '未明确'} |",
        f"| 重点 | {option_value(options, 'focus') or '未明确'} |",
        f"| 模板 | {template.id if template else '未匹配'} |",
        f"| 耗时 | {option_value(options, 'time_cost') or (str(template.default_time_minutes) + 'm' if template else '未明确')} |",
        "",
        "### 结算边界",
        "- 可用于吃饭、巡查、整理、照看、灌注、盘点等低风险日常行动。",
        "- 真实资源扣减、关系变化、进度钟推进或新事实仍必须写入结构化 delta。",
        "- 不自动推进剧情，不自动创建物品，不自动改变 NPC 态度。",
        "",
        "### Delta 草案",
    ]
    if not can_generate_delta:
        lines.append("当前地点不可见，不能生成保存草案。")
    else:
        delta = build_routine_delta(conn, options)
        lines.extend(["", "```json", json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True), "```"])
    return str(redact_hidden_entity_refs(conn, "\n".join(lines)))


def resolve_routine(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    del campaign, context_data
    validation = validate_routine_request(None, conn, {}, options)
    target = routine_target(conn, options)
    template = routine_template(options)
    current = current_location_row(conn, get_meta(conn))
    facts = [str(target["id"])] if target else []
    if template and template.produces_delta and not current:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(facts),
            confirmations=("当前地点未登记、不可见或不存在：不能保存日常行动。",),
            narrative_constraints=("Ask the player to resolve current location before saving routine output.",),
        )
    if not validation.ok:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(facts),
            confirmations=validation.missing_required,
            narrative_constraints=("Ask for the routine task or target before saving.",),
        )
    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_hidden_entity_refs(conn, tuple(facts), drop_empty=False)),
        proposed_delta=build_routine_delta(conn, options),
        player_message=(
            f"已识别为{template.labels[0]}。这是低风险 routine，不会自动制造资源、推进关系或创建新事实。"
            if template
            else "日常行动预演已准备好。"
        ),
        repair_options=(
            RepairOption(
                id="convert_to_query",
                label="只查看，不保存",
                action="query",
                effect="把这次 routine 当作只读查询处理",
                risk_level="none",
                requires_confirmation=False,
            ),
        )
        if template and not template.produces_delta
        else (),
        narrative_constraints=(
            "Use action.md for concise routine narration.",
            "Do not convert routine narration into real state changes unless the delta records them.",
        ),
    )


def validate_routine_request(
    campaign: Campaign | None,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    del campaign, conn, context_data
    if not (option_value(options, "task") or option_value(options, "target") or option_value(options, "user_text")):
        return ActionValidationResult(missing_required=("task",))
    return ActionValidationResult()


def validate_routine_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del campaign, context_data
    validation = validate_routine_request(None, conn, {}, options)
    errors: list[str] = []
    warnings: list[str] = []
    if delta.get("intent") != "routine":
        warnings.append("delta intent is not routine")
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    current_location_id = current["id"] if current else None
    if delta.get("location_after") and current_location_id and str(delta["location_after"]) != str(current_location_id):
        errors.append(f"location_after must remain {current_location_id} for routine; use travel for movement")
    elif delta.get("location_after") and not current_location_id:
        errors.append("location_after must remain at a visible current location for routine; use travel for movement")
    if not delta.get("events"):
        errors.append("routine delta must include an audit event")
    errors.extend(_validate_routine_consumption(conn, delta))
    return ActionValidationResult(
        errors=tuple(errors),
        warnings=tuple(warnings),
        missing_required=validation.missing_required,
    )


def _validate_routine_consumption(conn: sqlite3.Connection, delta: dict[str, Any]) -> list[str]:
    events = delta.get("events")
    if not isinstance(events, list):
        return []

    declarations: list[dict[str, Any]] = []
    for event in events:
        if type(event) is not dict:
            continue
        if not _mapping_has_only_string_keys(event):
            return [_consumption_error("invalid event field type")]
        payload = event.get("payload")
        if type(payload) is dict and any(
            type(key) is str and key in _CONSUMPTION_KEYS for key in payload
        ):
            declarations.append(payload)

    if not declarations:
        return []
    if len(declarations) != 1:
        return [_consumption_error("multiple declarations")]
    if len(events) != 1 or type(events[0]) is not dict:
        return [_consumption_error("event cardinality mismatch")]

    payload = declarations[0]
    if not _mapping_has_only_string_keys(payload):
        return [_consumption_error("invalid payload field type")]
    missing_payload_fields = [key for key in (*_CONSUMPTION_KEYS, "unit") if key not in payload]
    if missing_payload_fields:
        return [_consumption_error(f"missing field: payload.{missing_payload_fields[0]}")]

    item_id = payload["consumed_item_id"]
    payload_unit = payload["unit"]
    if not _is_utf8_text(item_id) or not item_id:
        return [_consumption_error("invalid consumed_item_id")]
    if type(payload_unit) is not str or not payload_unit:
        return [_consumption_error("unit mismatch: payload.unit must be a non-empty string")]

    upserts = delta.get("upsert_entities")
    if not isinstance(upserts, list):
        return [_consumption_error("missing/duplicate target upsert")]
    if any(type(record) is dict and not _mapping_has_only_string_keys(record) for record in upserts):
        return [_consumption_error("invalid upsert field type")]
    if any(
        type(record) is dict
        and type(record.get("id")) is str
        and not _is_utf8_text(record["id"])
        for record in upserts
    ):
        return [_consumption_error("invalid upsert id")]
    matching_upserts = [
        record
        for record in upserts
        if type(record) is dict
        and type(record.get("id")) is str
        and record["id"] == item_id
    ]
    if len(matching_upserts) != 1:
        return [_consumption_error("missing/duplicate target upsert")]
    target = matching_upserts[0]
    item = target.get("item")
    if type(item) is not dict:
        return [_consumption_error("target item payload must be an exact mapping")]
    if not _mapping_has_only_string_keys(item):
        return [_consumption_error("metadata mismatch: unexpected item field <non-string>")]
    for key in ("quantity", "unit"):
        if key not in item:
            return [_consumption_error(f"missing field: upsert item.{key}")]

    for record in upserts:
        if record is target or type(record) is not dict:
            continue
        record_id = record.get("id")
        is_existing_item = (
            type(record_id) is str
            and conn.execute("select 1 from items where entity_id = ?", (record_id,)).fetchone() is not None
        )
        if "item" in record or is_existing_item:
            return [_consumption_error("unexpected inventory upsert")]

    row = conn.execute(
        """
        select e.id, e.type, e.name, e.status, e.visibility, e.location_id, e.owner_id,
               e.summary, e.details_json, i.category, i.quantity, i.unit, i.quality,
               i.durability_current, i.durability_max, i.stackable, i.equipped_slot,
               i.properties_json
        from entities e
        join items i on i.entity_id = e.id
        where e.id = ?
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        return [_consumption_error("target item not found")]

    quantities: dict[str, float] = {}
    for field, raw_value in (
        ("live quantity", row["quantity"]),
        ("before_quantity", payload["before_quantity"]),
        ("consumed_quantity", payload["consumed_quantity"]),
        ("after_quantity", payload["after_quantity"]),
        ("upsert item.quantity", item["quantity"]),
    ):
        normalized, error = _normalize_consumption_quantity(raw_value, field)
        if error:
            return [error]
        quantities[field] = normalized

    live_quantity = quantities["live quantity"]
    before_quantity = quantities["before_quantity"]
    consumed_quantity = quantities["consumed_quantity"]
    after_quantity = quantities["after_quantity"]
    upsert_quantity = quantities["upsert item.quantity"]

    if before_quantity != live_quantity:
        return [_consumption_error("stale before_quantity")]
    if consumed_quantity <= 0:
        return [_consumption_error("non-positive consumed_quantity")]
    if consumed_quantity > before_quantity or after_quantity < 0:
        return [_consumption_error("insufficient quantity")]
    expected_after = before_quantity - consumed_quantity
    if (
        expected_after >= before_quantity
        or after_quantity >= before_quantity
        or not _within_one_ulp(after_quantity, expected_after)
    ):
        return [_consumption_error("arithmetic mismatch")]
    realized_consumption = before_quantity - after_quantity
    if not _within_two_ulps(realized_consumption, consumed_quantity):
        return [_consumption_error("arithmetic mismatch")]
    if upsert_quantity != after_quantity:
        return [_consumption_error("upsert quantity mismatch")]
    if payload_unit != row["unit"] or type(item["unit"]) is not str or item["unit"] != row["unit"]:
        return [_consumption_error("unit mismatch")]

    metadata_error = _validate_consumption_metadata(conn, row, target, item)
    if metadata_error:
        return [metadata_error]
    return []


def _normalize_consumption_quantity(value: Any, field: str) -> tuple[float, str | None]:
    if type(value) not in (int, float):
        return 0.0, _consumption_error(f"invalid numeric type: {field}")
    if type(value) is int and not (_SQLITE_INTEGER_MIN <= value <= _SQLITE_INTEGER_MAX):
        return 0.0, _consumption_error(f"quantity out of range: {field}")
    try:
        normalized = float(value)
    except OverflowError:
        return 0.0, _consumption_error(f"quantity out of range: {field}")
    if not math.isfinite(normalized):
        return 0.0, _consumption_error(f"non-finite quantity: {field}")
    if type(value) is int and int(normalized) != value:
        return 0.0, _consumption_error(f"quantity out of range: {field}")
    return normalized, None


def _within_one_ulp(actual: float, expected: float) -> bool:
    if not math.isfinite(expected):
        return False
    return abs(actual - expected) <= max(math.ulp(actual), math.ulp(expected))


def _within_two_ulps(actual: float, expected: float) -> bool:
    if not math.isfinite(expected):
        return False
    return abs(actual - expected) <= 2 * max(math.ulp(actual), math.ulp(expected)) and math.isclose(
        actual,
        expected,
        rel_tol=2 * math.ulp(1.0),
        abs_tol=0.0,
    )


def _validate_consumption_metadata(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    target: dict[str, Any],
    item: dict[str, Any],
) -> str | None:
    if "updated_turn_id" in target:
        return _consumption_error("metadata mismatch: updated_turn_id is commit-owned")
    unexpected_target_keys = _unexpected_mapping_keys(target, _TARGET_UPSERT_KEYS)
    if unexpected_target_keys:
        return _consumption_error(f"metadata mismatch: unexpected target field {unexpected_target_keys[0]}")
    unexpected_item_keys = _unexpected_mapping_keys(item, _TARGET_ITEM_KEYS)
    if unexpected_item_keys:
        return _consumption_error(f"metadata mismatch: unexpected item field {unexpected_item_keys[0]}")

    entity_live = {
        "type": row["type"],
        "name": row["name"],
        "status": row["status"],
        "visibility": row["visibility"],
        "location_id": row["location_id"],
        "owner_id": row["owner_id"],
        "summary": row["summary"],
        "details": json.loads(row["details_json"] or "{}"),
    }
    for key in _ENTITY_METADATA_KEYS:
        if key not in target or not _exact_metadata_equal(target[key], entity_live[key]):
            return _consumption_error(f"metadata mismatch: entity.{key}")

    item_live = {
        "category": row["category"],
        "unit": row["unit"],
        "quality": row["quality"],
        "durability_current": row["durability_current"],
        "durability_max": row["durability_max"],
        "stackable": bool(row["stackable"]),
        "equipped_slot": row["equipped_slot"],
        "properties": json.loads(row["properties_json"] or "{}"),
    }
    for key in _ITEM_METADATA_KEYS:
        if key not in item or not _exact_metadata_equal(item[key], item_live[key]):
            return _consumption_error(f"metadata mismatch: item.{key}")

    aliases = target.get("aliases")
    if type(aliases) is not list or any(type(alias) is not str for alias in aliases):
        return _consumption_error("metadata mismatch: aliases")
    live_aliases = [
        str(alias_row["alias"])
        for alias_row in conn.execute(
            "select alias from aliases where entity_id = ? and kind = 'name' order by alias",
            (row["id"],),
        ).fetchall()
    ]
    if len(aliases) != len(set(aliases)) or sorted(aliases) != live_aliases:
        return _consumption_error("metadata mismatch: aliases")
    return None


def _exact_metadata_equal(candidate: Any, live: Any) -> bool:
    if type(candidate) is not type(live):
        return False
    if type(candidate) is dict:
        if not _mapping_has_only_string_keys(candidate):
            return False
        if candidate.keys() != live.keys():
            return False
        return all(_exact_metadata_equal(candidate[key], live[key]) for key in candidate)
    if type(candidate) is list:
        return len(candidate) == len(live) and all(
            _exact_metadata_equal(candidate_item, live_item)
            for candidate_item, live_item in zip(candidate, live, strict=True)
        )
    return candidate == live


def _mapping_has_only_string_keys(mapping: dict[Any, Any]) -> bool:
    return all(type(key) is str for key in mapping)


def _unexpected_mapping_keys(mapping: dict[Any, Any], allowed: set[str]) -> list[str]:
    unexpected = [
        key if _is_utf8_text(key) else "<invalid-text>"
        for key in mapping
        if type(key) is str and key not in allowed
    ]
    if any(type(key) is not str for key in mapping):
        unexpected.append("<non-string>")
    return sorted(unexpected)


def _is_utf8_text(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _consumption_error(reason: str) -> str:
    return f"{_CONSUMPTION_PREFIX} {reason}"


def build_routine_delta(conn: sqlite3.Connection, options: Any) -> dict[str, Any]:
    meta = get_meta(conn)
    current = current_location_row(conn, meta)
    location_id = current["id"] if current else None
    target = routine_target(conn, options)
    template = routine_template(options)
    task = option_value(options, "task") or option_value(options, "user_text") or option_value(options, "target") or "日常维护"
    summary = f"日常行动：{task}。"
    delta = {
        "user_text": option_value(options, "user_text") or str(task),
        "intent": "routine",
        "changed": bool(template.produces_delta) if template else True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": meta.get("current_time_block"),
        "location_before": location_id,
        "location_after": location_id,
        "summary": summary,
        "events": [
            {
                "type": "routine",
                "title": "日常维护结算",
                "summary": summary,
                "payload": {
                    "template_id": template.id if template else None,
                    "task": str(task),
                    "target_id": target["id"] if target else option_value(options, "target"),
                    "focus": option_value(options, "focus"),
                    "time_cost": option_value(options, "time_cost")
                    or (f"{template.default_time_minutes}m" if template else None),
                    "needs_gm_resolution": True,
                    "state_changes_must_be_structured": True,
                },
                "source": "routine_preview",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }
    return redact_hidden_entity_refs(conn, delta, drop_empty=False)


def routine_target(conn: sqlite3.Connection, options: Any) -> sqlite3.Row | None:
    target_query = option_value(options, "target")
    return resolve_entity(conn, str(target_query)) if target_query else None


def routine_template(options: Any) -> RoutineTemplate | None:
    text = " ".join(
        str(value)
        for value in [
            option_value(options, "task"),
            option_value(options, "target"),
            option_value(options, "focus"),
            option_value(options, "user_text"),
        ]
        if value
    )
    for template in ROUTINE_TEMPLATES:
        if any(
            template.taxonomy_role in term.roles and taxonomy_term_matches(text, term)
            for term in ROUTINE_TAXONOMY.terms
        ):
            return template
    return None


ROUTINE_RESOLVER = ActionResolverSpec(
    name="routine",
    preview=preview_routine,
    response_template="action.md",
    option_specs=option_specs_for(
        ActionOptionSpec("task", "routine task such as upkeep, feeding, checking or golden-light transfer"),
        ActionOptionSpec("target", "optional entity id/name/alias", binding_type="entity_or_text", aliases=("object",)),
        ActionOptionSpec("focus", "optional focus or safety concern"),
        ActionOptionSpec("time_cost", "estimated routine time", dest="time", aliases=("time",)),
        ActionOptionSpec("user_text", "original player action text", dest="user-text", ai_fillable=False),
    ),
    requirement_groups=(
        ActionRequirementGroupSpec(
            "routine_scope",
            ("task", "target"),
            binding_rule="source_user_text_fallback",
        ),
    ),
    taxonomy=ROUTINE_TAXONOMY,
    validate_request=validate_routine_request,
    resolve=resolve_routine,
    validate_delta=validate_routine_delta,
)
