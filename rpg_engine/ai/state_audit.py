from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from .defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS
from .provider import run_ai_helper_json
from .schemas import StateAuditResult, normalize_state_audit_result
from .tasks import AIHelperTask

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

GAIN_KEYWORDS = (
    "获得",
    "得到",
    "收获",
    "入库",
    "装满",
    "采集到",
    "捡到",
    "gained",
    "received",
    "collected",
)
CONSUME_KEYWORDS = (
    "消耗",
    "用掉",
    "扣减",
    "制作",
    "装配",
    "修理",
    "发酵",
    "consume",
    "spent",
    "crafted",
)
RELATIONSHIP_KEYWORDS = (
    "承诺",
    "关系",
    "信任",
    "交易",
    "交换",
    "赠送",
    "promise",
    "relationship",
    "trust",
    "trade",
)
EQUIPMENT_KEYWORDS = (
    "装备",
    "携带",
    "放下",
    "移动",
    "转移",
    "装箭",
    "equip",
    "carry",
    "moved",
)
HIGH_RISK_KEYWORDS = (
    "弹",
    "箭",
    "火药",
    "毒",
    "药剂",
    "地雷",
    "武器",
    "食物",
    "鱼",
    "虾",
    "肉",
    "ammo",
    "arrow",
    "powder",
    "poison",
    "mine",
    "weapon",
    "food",
    "trade",
)


def run_state_audit(
    conn: sqlite3.Connection,
    *,
    delta: dict[str, Any],
    validation_result: dict[str, Any],
    action: str | None = None,
    action_options: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    ai: str = "off",
    provider: str = DEFAULT_AI_PROVIDER,
    model: str = DEFAULT_AI_MODEL,
    timeout: int = DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
) -> StateAuditResult:
    deterministic = deterministic_state_audit(
        conn,
        delta=delta,
        validation_result=validation_result,
        action=action,
        action_options=action_options or {},
        context=context or {},
    )
    if ai == "off":
        return deterministic

    task = AIHelperTask(
        name="state_audit",
        output_schema="state_audit.schema.json",
        prompt=build_state_audit_prompt(
            conn,
            delta=delta,
            validation_result=validation_result,
            deterministic=deterministic,
            action=action,
            action_options=action_options or {},
        ),
        parser=lambda value: normalize_state_audit_result(value).to_dict(),
    )
    result = run_ai_helper_json(task, backend=ai, provider=provider, model=model, timeout=timeout)
    if not result.ok or result.parsed is None:
        return with_ai_status(
            deterministic,
            ai_status="failed",
            warning=result.error or "state_audit ai failed; deterministic audit used",
            audit=result.audit,
        )
    ai_audit = normalize_state_audit_result(result.parsed)
    return merge_state_audit_results(deterministic, ai_audit, ai_status="ok", audit=result.audit)


def deterministic_state_audit(
    conn: sqlite3.Connection,
    *,
    delta: dict[str, Any],
    validation_result: dict[str, Any],
    action: str | None = None,
    action_options: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> StateAuditResult:
    del conn, action, action_options, context
    findings: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    warnings: list[str] = []

    events = delta.get("events") if isinstance(delta.get("events"), list) else []
    upserts = delta.get("upsert_entities") if isinstance(delta.get("upsert_entities"), list) else []
    ticks = delta.get("tick_clocks") if isinstance(delta.get("tick_clocks"), list) else []
    has_upserts = bool(upserts)
    has_ticks = bool(ticks)
    has_state_ops = has_upserts or has_ticks
    text = combined_delta_text(delta)

    if validation_result and not validation_result.get("ok", True):
        warnings.append("validate_delta is not ok; commit should already be blocked before state_audit.")

    if str(delta.get("intent") or "").lower() in {"query", "inspect", "look"} and (
        delta.get("changed") or has_state_ops or events
    ):
        add_finding(
            findings,
            missing,
            code="QUERY_MUTATES_STATE",
            severity="high",
            message="query/inspect style delta attempts to save state changes.",
            path="$.intent",
            suggested_fix="Use query for read-only answers; use an action resolver and explicit delta for state changes.",
            kind="query_state_mutation",
        )

    if delta.get("changed") is False and has_state_ops:
        add_finding(
            findings,
            missing,
            code="UNCHANGED_DELTA_HAS_STATE_OPS",
            severity="high",
            message="changed=false but delta contains structured state operations.",
            path="$",
            suggested_fix="Set changed=true or remove upsert/tick operations.",
            kind="changed_flag_mismatch",
        )

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        path = f"$.events[{index}].payload"
        if payload.get("output_quantity_required") is True and not has_upserts and not explicit_no_change(payload, "output"):
            add_finding(
                findings,
                missing,
                code="OUTPUT_REQUIRED_WITHOUT_ENTITY",
                severity="high",
                message="event requires output quantity but delta has no upsert_entities output.",
                path=f"{path}.output_quantity_required",
                suggested_fix="Add item/material entity with quantity, unit, location and source, or set no_output=true.",
                kind="inventory_output",
            )
        if payload.get("material_consumption_required") is True and not has_state_ops and not explicit_no_change(payload, "material"):
            add_finding(
                findings,
                missing,
                code="MATERIAL_CONSUMPTION_NOT_STRUCTURED",
                severity="medium",
                message="event requires material consumption but delta has no structured material/project update.",
                path=f"{path}.material_consumption_required",
                suggested_fix="Add material decrement/project update, or explicitly mark no_material_consumption=true.",
                kind="material_consumption",
            )
        if payload.get("output_delta_required") is True and not has_upserts and not explicit_no_change(payload, "output"):
            add_finding(
                findings,
                missing,
                code="OUTPUT_DELTA_REQUIRED_WITHOUT_OUTPUT",
                severity="medium",
                message="event requires output delta but no output entity/project update is present.",
                path=f"{path}.output_delta_required",
                suggested_fix="Add output entity/project state or explicitly mark no_output=true.",
                kind="craft_output",
            )
        if payload.get("relationship_update_required") is True and not has_state_ops and not explicit_no_change(payload, "relationship"):
            add_finding(
                findings,
                missing,
                code="RELATIONSHIP_NOT_STRUCTURED",
                severity="high",
                message="event requires relationship update but delta has no relationship/project/clock update.",
                path=f"{path}.relationship_update_required",
                suggested_fix="Add relationship/project/clock update, or explicitly mark no_relationship_change=true.",
                kind="relationship",
            )
        if payload.get("trade_items_required") is True and not has_state_ops and not explicit_no_change(payload, "trade"):
            add_finding(
                findings,
                missing,
                code="TRADE_NOT_STRUCTURED",
                severity="high",
                message="event requires trade items but delta has no structured item or project update.",
                path=f"{path}.trade_items_required",
                suggested_fix="Add item transfer/update, or explicitly mark no_trade=true.",
                kind="trade",
            )
        if payload.get("state_changes_must_be_structured") is True and delta.get("changed") and not has_state_ops:
            add_finding(
                findings,
                missing,
                code="STRUCTURED_STATE_REQUIRED",
                severity="medium",
                message="event says state changes must be structured, but delta has no upsert_entities or tick_clocks.",
                path=f"{path}.state_changes_must_be_structured",
                suggested_fix="Add the structured change or mark the event as no_state_change=true.",
                kind="state_ops",
            )

    if contains_any(text, GAIN_KEYWORDS) and not has_upserts and not has_explicit_no_change(delta, "output"):
        add_finding(
            findings,
            missing,
            code="NARRATED_GAIN_WITHOUT_INVENTORY",
            severity="high",
            message="delta text/event mentions gained or stored output, but no inventory/entity upsert is present.",
            path="$",
            suggested_fix="Add item/material upsert with quantity, unit, location and source.",
            kind="inventory_output",
        )
    if contains_any(text, CONSUME_KEYWORDS) and not has_state_ops and not has_explicit_no_change(delta, "material"):
        add_finding(
            findings,
            missing,
            code="NARRATED_CONSUMPTION_WITHOUT_STATE_OP",
            severity="medium",
            message="delta text/event mentions consumption or crafting, but no structured material/project update is present.",
            path="$",
            suggested_fix="Add material decrement, item output, project state, or explicit no_material_consumption=true.",
            kind="material_consumption",
        )
    if contains_any(text, RELATIONSHIP_KEYWORDS) and not has_state_ops and not has_explicit_no_change(delta, "relationship"):
        severity = "high" if contains_any(text, ("交易", "交换", "承诺", "trade", "promise")) else "medium"
        add_finding(
            findings,
            missing,
            code="NARRATED_SOCIAL_CHANGE_WITHOUT_STATE_OP",
            severity=severity,
            message="delta text/event mentions social, promise or trade consequences without structured state operations.",
            path="$",
            suggested_fix="Add relationship/project/clock/item update or explicit no_relationship_change/no_trade marker.",
            kind="relationship_or_trade",
        )
    if contains_any(text, EQUIPMENT_KEYWORDS) and not has_upserts and not has_explicit_no_change(delta, "equipment"):
        add_finding(
            findings,
            missing,
            code="NARRATED_EQUIPMENT_CHANGE_WITHOUT_ENTITY",
            severity="medium",
            message="delta text/event mentions equipment or carried-item movement without entity update.",
            path="$",
            suggested_fix="Add equipment/item location or carried state update.",
            kind="equipment",
        )

    for index, entity in enumerate(upserts):
        if not isinstance(entity, dict):
            continue
        if is_high_risk_entity(entity):
            missing_fields = missing_high_risk_fields(entity)
            if missing_fields:
                add_finding(
                    findings,
                    missing,
                    code="HIGH_RISK_ITEM_METADATA_INCOMPLETE",
                    severity="medium",
                    message=f"high-risk item/entity update is missing: {', '.join(missing_fields)}.",
                    path=f"$.upsert_entities[{index}]",
                    suggested_fix="Record quantity, unit, location, source and confidence for high-risk inventory.",
                    kind="high_risk_inventory",
                    extra={"missing_fields": missing_fields, "entity_id": entity.get("id")},
                )

    risk = max_risk(findings)
    requires_review = risk == "high"
    return StateAuditResult(
        ok=not requires_review,
        risk=risk,
        findings=findings,
        missing_structured_changes=missing,
        requires_human_review=requires_review,
        ai_status="off",
        warnings=warnings,
    )


def build_state_audit_prompt(
    conn: sqlite3.Connection,
    *,
    delta: dict[str, Any],
    validation_result: dict[str, Any],
    deterministic: StateAuditResult,
    action: str | None,
    action_options: dict[str, Any],
) -> str:
    payload = {
        "current_location_id": current_location_id(conn),
        "action": action or delta.get("intent"),
        "action_options": action_options,
        "validation_result": validation_result,
        "deterministic_audit": deterministic.to_dict(),
        "delta": delta,
    }
    return "\n".join(
        [
            "你是文字 RPG 引擎的提交前 State Auditor。只输出 JSON，不要 Markdown。",
            "你只能审计待提交 delta 是否漏写结构化状态变化，不能写事实，不能修改 delta，不能确认隐藏信息。",
            "SQLite、resolver、validate_delta 和玩家确认才是权威；你的输出必须是 advisory。",
            "",
            "输出格式：",
            '{"ok":true,"risk":"low","findings":[],"missing_structured_changes":[],"requires_human_review":false,"warnings":[]}',
            "",
            "重点检查：库存获得/消耗、装备移动、材料制作、交易、承诺、关系变化、进度钟、查询误写新事实。",
            "若叙事或 event 提到状态变化但没有 upsert_entities/tick_clocks/meta 或明确 no_* 声明，请指出。",
            "",
            "输入：",
            compact_json(payload, limit=10000),
        ]
    )


def should_block_state_audit(result: StateAuditResult) -> bool:
    return not result.ok or result.risk == "high" or result.requires_human_review


def merge_state_audit_results(
    base: StateAuditResult,
    extra: StateAuditResult,
    *,
    ai_status: str,
    audit: dict[str, Any] | None = None,
) -> StateAuditResult:
    risk = higher_risk(base.risk, extra.risk)
    requires_review = base.requires_human_review or extra.requires_human_review or risk == "high"
    return StateAuditResult(
        ok=base.ok and extra.ok and not requires_review,
        risk=risk,
        findings=[*base.findings, *extra.findings],
        missing_structured_changes=[*base.missing_structured_changes, *extra.missing_structured_changes],
        requires_human_review=requires_review,
        ai_status=ai_status,
        warnings=[*base.warnings, *extra.warnings],
        audit=audit or {},
    )


def with_ai_status(
    result: StateAuditResult,
    *,
    ai_status: str,
    warning: str | None = None,
    audit: dict[str, Any] | None = None,
) -> StateAuditResult:
    warnings = list(result.warnings)
    if warning:
        warnings.append(short_text(warning, 220))
    return StateAuditResult(
        ok=result.ok,
        risk=result.risk,
        findings=list(result.findings),
        missing_structured_changes=list(result.missing_structured_changes),
        requires_human_review=result.requires_human_review,
        ai_status=ai_status,
        warnings=warnings,
        audit=audit or result.audit,
    )


def add_finding(
    findings: list[dict[str, Any]],
    missing: list[dict[str, Any]],
    *,
    code: str,
    severity: str,
    message: str,
    path: str,
    suggested_fix: str,
    kind: str,
    extra: dict[str, Any] | None = None,
) -> None:
    finding = {
        "code": code,
        "severity": severity,
        "message": message,
        "path": path,
        "suggested_fix": suggested_fix,
    }
    if extra:
        finding.update(extra)
    if finding not in findings:
        findings.append(finding)
    missing_item = {"kind": kind, "severity": severity, "message": message, "path": path}
    if extra:
        missing_item.update(extra)
    if missing_item not in missing:
        missing.append(missing_item)


def explicit_no_change(payload: dict[str, Any], kind: str) -> bool:
    keys_by_kind = {
        "output": ("no_output", "no_items_gained", "no_inventory_change", "no_state_change"),
        "material": ("no_material_consumption", "no_inventory_change", "no_state_change"),
        "relationship": ("no_relationship_change", "no_social_change", "no_state_change"),
        "trade": ("no_trade", "no_inventory_change", "no_state_change"),
        "equipment": ("no_equipment_change", "no_inventory_change", "no_state_change"),
    }
    return any(payload.get(key) is True for key in keys_by_kind.get(kind, ()))


def has_explicit_no_change(delta: dict[str, Any], kind: str) -> bool:
    if isinstance(delta.get("meta"), dict) and explicit_no_change(delta["meta"], kind):
        return True
    for event in delta.get("events", []) if isinstance(delta.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if isinstance(payload, dict) and explicit_no_change(payload, kind):
            return True
    return False


def combined_delta_text(delta: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("intent", "summary", "user_text"):
        value = delta.get(key)
        if value is not None:
            parts.append(str(value))
    for event in delta.get("events", []) if isinstance(delta.get("events"), list) else []:
        if not isinstance(event, dict):
            continue
        for key in ("type", "title", "summary", "source"):
            value = event.get(key)
            if value is not None:
                parts.append(str(value))
        payload = event.get("payload")
        if isinstance(payload, dict):
            parts.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return "\n".join(parts)


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def is_high_risk_entity(entity: dict[str, Any]) -> bool:
    entity_type = str(entity.get("type") or "")
    text = json.dumps(entity, ensure_ascii=False, sort_keys=True).lower()
    return entity_type in {"item", "equipment", "material"} and contains_any(text, HIGH_RISK_KEYWORDS)


def missing_high_risk_fields(entity: dict[str, Any]) -> list[str]:
    item = entity.get("item") if isinstance(entity.get("item"), dict) else {}
    details = entity.get("details") if isinstance(entity.get("details"), dict) else {}
    profile = details.get("profile") if isinstance(details.get("profile"), dict) else {}
    missing: list[str] = []
    objects = (entity, item, details, profile)
    if first_present(objects, ("quantity",)) is None:
        missing.append("quantity")
    if first_present(objects, ("unit",)) is None:
        missing.append("unit")
    if first_present(objects, ("location_id",)) is None:
        missing.append("location_id")
    if first_present(objects, ("source_event_id", "source", "provenance")) is None:
        missing.append("source")
    if first_present(objects, ("quantity_confidence", "confidence")) is None:
        missing.append("confidence")
    return missing


def first_present(objects: tuple[dict[str, Any], ...], keys: tuple[str, ...]) -> Any:
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for key in keys:
            value = obj.get(key)
            if value not in (None, ""):
                return value
    return None


def max_risk(findings: list[dict[str, Any]]) -> str:
    risk = "low"
    for finding in findings:
        risk = higher_risk(risk, str(finding.get("severity") or "low"))
    return risk


def higher_risk(left: str, right: str) -> str:
    return left if RISK_ORDER.get(left, 0) >= RISK_ORDER.get(right, 0) else right


def current_location_id(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("select value from meta where key = 'current_location_id'").fetchone()
    except Exception:
        return ""
    return str(row["value"] if hasattr(row, "keys") else row[0]) if row else ""


def compact_json(value: Any, *, limit: int) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def short_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
