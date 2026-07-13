from __future__ import annotations

import json
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
    return ActionValidationResult(
        errors=tuple(errors),
        warnings=tuple(warnings),
        missing_required=validation.missing_required,
    )


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
        ActionOptionSpec("target", "optional entity id/name/alias"),
        ActionOptionSpec("focus", "optional focus or safety concern"),
        ActionOptionSpec("time_cost", "estimated routine time", dest="time"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    taxonomy=ROUTINE_TAXONOMY,
    validate_request=validate_routine_request,
    resolve=resolve_routine,
    validate_delta=validate_routine_delta,
)
