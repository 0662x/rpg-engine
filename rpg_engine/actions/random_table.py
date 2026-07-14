from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..campaign import Campaign
from ..random_tables import RandomOutcome, roll_dice, roll_random_table
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .slot_contract import ActionRequirementGroupSpec
from .taxonomy import ActionTaxonomySpec, taxonomy_terms


def preview_random_table(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> str:
    del conn
    try:
        delta = context_data.get("proposed_delta") if isinstance(context_data, dict) else None
        outcome = random_outcome_from_delta(delta) if isinstance(delta, dict) else random_outcome_from_options(campaign, options)
        errors: list[str] = []
    except Exception as exc:
        outcome = None
        errors = [str(exc)]

    user_text = option_value(options, "user_text") or option_value(options, "reason") or "kernel random roll"
    lines = [
        "## 随机结果预演",
        "",
        "### 输入",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 随机表 | {option_value(options, 'table') or ''} |",
        f"| 骰子 | {option_value(options, 'dice') or ''} |",
        f"| 原因 | {option_value(options, 'reason') or ''} |",
    ]
    if errors or outcome is None:
        lines.extend(["", "### 错误"])
        lines.extend(f"- {item}" for item in errors)
        return "\n".join(lines)

    lines.extend(
        [
            "",
            "### 内核结果",
            "| 字段 | 值 |",
            "|------|----|",
            f"| 类型 | `{outcome.kind}` |",
            f"| 结果 | {outcome.result} |",
        ]
    )
    if outcome.table_id:
        lines.append(f"| 随机表 | `{outcome.table_id}` {outcome.table_name or ''} |")
        lines.append(f"| 条目 | `{outcome.entry_index}` |")
    if outcome.dice:
        lines.append(f"| 掷骰 | `{outcome.dice}` |")
        lines.append(f"| 骰面 | {', '.join(str(item) for item in outcome.rolls)} |")
        lines.append(f"| 总计 | `{outcome.total}` |")

    if not isinstance(delta, dict):
        delta = build_random_delta(outcome, user_text=str(user_text), reason=option_value(options, "reason"))
    lines.extend(
        [
            "",
            "### Delta 草案",
            "该结果由内核生成；AI 只能叙事化，保存时必须提交此结构化事件。",
            "",
            "```json",
            json.dumps(delta, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    return "\n".join(lines)


def resolve_random_table(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    del conn, context_data
    try:
        outcome = random_outcome_from_options(campaign, options)
    except Exception as exc:
        return ResolutionResult(
            status="needs_confirmation",
            confirmations=(str(exc),),
            narrative_constraints=("Ask for a valid random table id or dice expression before saving.",),
            player_message="需要一个有效的随机表 id 或骰子表达式，才能由内核生成可保存的随机结果。",
        )
    user_text = option_value(options, "user_text") or option_value(options, "reason") or "kernel random roll"
    delta = build_random_delta(outcome, user_text=str(user_text), reason=option_value(options, "reason"))
    return ResolutionResult(
        status="ready",
        facts_used=(outcome.table_id or outcome.dice or outcome.kind,),
        rules_applied=("kernel_random_audit_event",),
        proposed_delta=delta,
        narrative_constraints=(
            "Narrate only the kernel-generated random outcome in delta.events[0].payload.",
            "Do not reroll or replace the random result outside this resolver.",
        ),
        player_message=f"随机结果已由内核生成：{outcome.summary}。确认后会保存为审计事件。",
        confidence="high",
    )


def validate_random_request(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ActionValidationResult:
    del conn, context_data
    errors: list[str] = []
    missing: list[str] = []
    if not option_value(options, "table") and not option_value(options, "dice"):
        missing.append("table or dice")
    if option_value(options, "table") and option_value(options, "dice"):
        errors.append("choose either table or dice, not both")
    if not missing and not errors:
        try:
            random_outcome_from_options(campaign, options)
        except Exception as exc:
            errors.append(str(exc))
    return ActionValidationResult(errors=tuple(errors), missing_required=tuple(missing))


def validate_random_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del campaign, conn, context_data, options
    errors: list[str] = []
    events = delta.get("events", [])
    if not isinstance(events, list) or not events:
        errors.append("random_table delta must include an audit event")
    found = False
    for index, event in enumerate(events if isinstance(events, list) else []):
        if not isinstance(event, dict):
            continue
        if event.get("type") not in {"random_table_roll", "dice_roll"}:
            continue
        found = True
        if event.get("source") != "kernel_random":
            errors.append(f"events[{index}].source must be kernel_random")
        payload = event.get("payload", {})
        if not isinstance(payload, dict) or payload.get("generated_by") != "aigm_kernel":
            errors.append(f"events[{index}].payload.generated_by must be aigm_kernel")
    if not found:
        errors.append("random_table delta must include random_table_roll or dice_roll event")
    return ActionValidationResult(errors=tuple(errors))


def random_outcome_from_options(campaign: Campaign, options: Any) -> RandomOutcome:
    table = option_value(options, "table")
    dice = option_value(options, "dice")
    if table and dice:
        raise ValueError("choose either table or dice, not both")
    if table:
        return roll_random_table(campaign, str(table))
    if dice:
        return roll_dice(str(dice))
    raise ValueError("table or dice is required")


def build_random_delta(outcome: RandomOutcome, *, user_text: str, reason: Any = None) -> dict[str, Any]:
    event_type = "dice_roll" if outcome.kind == "dice" else "random_table_roll"
    title = "Dice rolled" if outcome.kind == "dice" else "Random table rolled"
    payload = outcome.to_dict()
    if reason:
        payload["reason"] = str(reason)
    return {
        "user_text": user_text,
        "intent": "random_table",
        "changed": True,
        "summary": f"Kernel random result: {outcome.summary}",
        "events": [
            {
                "type": event_type,
                "title": title,
                "summary": outcome.summary,
                "payload": payload,
                "source": "kernel_random",
            }
        ],
    }


def random_outcome_from_delta(delta: dict[str, Any]) -> RandomOutcome:
    events = delta.get("events", [])
    if not isinstance(events, list):
        raise ValueError("random_table delta events must be a list")
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in {"random_table_roll", "dice_roll"}:
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("random_table delta payload must be an object")
        return RandomOutcome(
            kind=str(payload.get("kind") or ("dice" if event.get("type") == "dice_roll" else "random_table")),
            result=str(payload.get("result") or ""),
            table_id=str(payload["table_id"]) if payload.get("table_id") is not None else None,
            table_name=str(payload["table_name"]) if payload.get("table_name") is not None else None,
            visibility=str(payload["visibility"]) if payload.get("visibility") is not None else None,
            entry_index=int(payload["entry_index"]) if payload.get("entry_index") is not None else None,
            weight=float(payload["weight"]) if payload.get("weight") is not None else None,
            dice=str(payload["dice"]) if payload.get("dice") is not None else None,
            rolls=tuple(int(item) for item in payload.get("rolls", []) if isinstance(item, int)),
            modifier=int(payload.get("modifier") or 0),
            total=int(payload["total"]) if payload.get("total") is not None else None,
            tags=tuple(str(item) for item in payload.get("tags", []) if isinstance(item, str)),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        )
    raise ValueError("random_table delta must include random_table_roll or dice_roll event")


RANDOM_TABLE_RESOLVER = ActionResolverSpec(
    name="random_table",
    preview=preview_random_table,
    response_template="action.md",
    option_specs=option_specs_for(
        ActionOptionSpec("table", "random table id to roll", binding_type="random_table_id", aliases=("table_id",)),
        ActionOptionSpec("dice", "dice expression such as d20, 2d6 or 2d6+1", binding_type="dice_expr"),
        ActionOptionSpec("reason", "why the kernel random result is needed"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text", ai_fillable=False),
    ),
    requirement_groups=(
        ActionRequirementGroupSpec(
            "random_source",
            ("table", "dice"),
            cardinality="exactly_one",
        ),
    ),
    taxonomy=ActionTaxonomySpec(
        terms=(
            *taxonomy_terms("zh-Hans", ("随机", "掷骰", "骰子", "事件表", "随机表")),
            *taxonomy_terms("en", ("random", "roll", "dice", "random table", "event table")),
        ),
        semantic_labels=("random", "roll", "dice", "random-table"),
        inference_priority=15,
    ),
    validate_request=validate_random_request,
    resolve=resolve_random_table,
    validate_delta=validate_random_delta,
)
