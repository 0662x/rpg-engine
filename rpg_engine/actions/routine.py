from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, resolve_entity
from ..ux import RepairOption
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)


@dataclass(frozen=True)
class RoutineTemplate:
    id: str
    labels: tuple[str, ...]
    keywords: tuple[str, ...]
    default_time_minutes: int
    allowed_scope: str
    risk_level: str
    produces_delta: bool = True
    requires_confirmation: bool = False


ROUTINE_TEMPLATES = (
    RoutineTemplate(
        id="routine:inventory-audit",
        labels=("盘点库存", "整理库存", "查看物资"),
        keywords=("盘点", "库存", "物资", "整理库存", "查看库存"),
        default_time_minutes=5,
        allowed_scope="base",
        risk_level="none",
        produces_delta=False,
    ),
    RoutineTemplate(
        id="routine:upkeep",
        labels=("日常维护", "检查", "整理"),
        keywords=("维护", "检查", "整理", "巡查", "照看", "喂", "吃饭", "灌", "金光"),
        default_time_minutes=10,
        allowed_scope="current_location",
        risk_level="low",
    ),
)


def preview_routine(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    del campaign, context
    delta = build_routine_delta(conn, options)
    template = routine_template(options)
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
        "",
        "```json",
        json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
    ]
    return "\n".join(lines)


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
    facts = [str(target["id"])] if target else []
    if not validation.ok:
        return ResolutionResult(
            status="needs_confirmation",
            facts_used=tuple(facts),
            confirmations=validation.missing_required,
            narrative_constraints=("Ask for the routine task or target before saving.",),
        )
    return ResolutionResult(
        status="ready",
        facts_used=tuple(facts),
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
    current_location_id = meta.get("current_location_id")
    if delta.get("location_after") and current_location_id and str(delta["location_after"]) != str(current_location_id):
        errors.append(f"location_after must remain {current_location_id} for routine; use travel for movement")
    if not delta.get("events"):
        errors.append("routine delta must include an audit event")
    return ActionValidationResult(
        errors=tuple(errors),
        warnings=tuple(warnings),
        missing_required=validation.missing_required,
    )


def build_routine_delta(conn: sqlite3.Connection, options: Any) -> dict[str, Any]:
    meta = get_meta(conn)
    target = routine_target(conn, options)
    template = routine_template(options)
    task = option_value(options, "task") or option_value(options, "user_text") or option_value(options, "target") or "日常维护"
    summary = f"日常行动：{task}。"
    return {
        "user_text": option_value(options, "user_text") or str(task),
        "intent": "routine",
        "changed": bool(template.produces_delta) if template else True,
        "game_time_before": meta.get("current_time_block"),
        "game_time_after": meta.get("current_time_block"),
        "location_before": meta.get("current_location_id"),
        "location_after": meta.get("current_location_id"),
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
        if any(keyword in text for keyword in template.keywords):
            return template
    return None


ROUTINE_RESOLVER = ActionResolverSpec(
    name="routine",
    preview=preview_routine,
    response_template="action.md",
    option_specs=option_specs_for(
        ActionOptionSpec("task", "routine task such as upkeep, feeding, checking or golden-light transfer"),
        ActionOptionSpec("target", "optional entity id/name/alias"),
        ActionOptionSpec("focus", "optional focus or safety concern"),
        ActionOptionSpec("time_cost", "estimated routine time", dest="time"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    keywords=("日常", "例行", "整理", "巡查", "照看", "喂", "吃饭", "灌", "金光", "盘点", "维护", "检查"),
    semantic_labels=("routine", "upkeep", "maintenance", "daily", "care", "check"),
    inference_priority=65,
    validate_request=validate_routine_request,
    resolve=resolve_routine,
    validate_delta=validate_routine_delta,
)
