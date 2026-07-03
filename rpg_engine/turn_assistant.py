from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .campaign import Campaign
from .commit_service import commit_turn_delta
from .context_builder import build_context
from .delta_schema import render_delta_validation, validate_delta_schema
from .proposal import load_turn_proposal, validate_turn_proposal
from .response_lint import lint_response, load_response_text, load_turn_contract_from_context
from .save import load_delta
from .validation_pipeline import run_validation_pipeline
from .actions import get_default_action_registry


@dataclass(frozen=True)
class TurnAssistantOptions:
    user_text: str
    budget: int = 2500
    mode: str = "auto"
    submode: str | None = None
    format: str = "markdown"
    target: str | None = None
    project: str | None = None
    output: str | None = None
    weapon: str | None = None
    ammo: str | None = None
    distance: str | None = None
    ready_state: str | None = None
    destination: str | None = None
    pace: str = "normal"
    location: str | None = None
    materials: str | None = None
    time_cost: str | None = None
    npc: str | None = None
    topic: str | None = None
    approach: str | None = None
    until: str | None = None
    response_file: str | None = None
    response_text: str | None = None
    proposal_json: str | None = None
    delta_json: str | None = None
    save: bool = False
    rebuild_memory: bool = False
    audit_context: bool = False
    context_run_id: str | None = None


def run_turn_assistant(campaign: Campaign, conn: sqlite3.Connection, options: TurnAssistantOptions) -> str:
    packet = build_context(
        campaign,
        conn,
        user_text=options.user_text,
        mode=options.mode,
        submode=options.submode,
        budget=options.budget,
        output_format="json",
        audit_context=options.audit_context,
        audit_context_run_id=options.context_run_id,
    )
    context_data = json.loads(packet.to_json_text())
    action_contract_text = render_action_contract_for_context(campaign, conn, context_data, options)
    preview_text = render_preview_for_context(campaign, conn, context_data, options)
    proposal_text = render_proposal_validation(campaign, conn, options)
    response_lint_text = render_response_lint(context_data, options)
    delta_text, delta_errors, delta = render_delta_validation_for_options(conn, options)
    save_text = ""
    if options.save:
        save_text = run_save_pipeline(campaign, conn, options, delta, delta_errors)

    lines = [
        "# Turn Assistant Report",
        "",
        "## Context",
        "",
        f"- mode: `{context_data['request']['mode']}:{context_data['request']['submode']}`",
        f"- allow_proceed: `{context_data['completeness']['allow_proceed']}`",
        f"- must_save: `{context_data['request']['must_save']}`",
        f"- budget: `{context_data['budget']['estimated']} / {context_data['budget']['limit']}`",
    ]
    if context_data["completeness"].get("missing_required"):
        lines.append("- missing_required:")
        lines.extend(f"  - {item}" for item in context_data["completeness"]["missing_required"])
    if context_data["completeness"].get("needs_user_confirmation"):
        lines.append("- needs_user_confirmation:")
        lines.extend(f"  - {item}" for item in context_data["completeness"]["needs_user_confirmation"])

    if action_contract_text:
        lines.extend(["", "## Action Contract", "", action_contract_text])
    lines.extend(["", "## Preview", "", preview_text or "未运行 preview：当前模式不需要，或缺少对应参数。"])
    if proposal_text:
        lines.extend(["", "## Proposal Guard", "", proposal_text])
    lines.extend(["", "## Response Lint", "", response_lint_text or "未提供回复文本，跳过 response lint。"])
    lines.extend(["", "## Delta Validation", "", delta_text])
    if save_text:
        lines.extend(["", "## Save Pipeline", "", save_text])
    lines.extend(["", "## Required Next Step"])
    lines.extend(render_next_steps(context_data, options, bool(preview_text), delta_errors))
    return "\n".join(lines).rstrip() + "\n"


def render_action_contract_for_context(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: TurnAssistantOptions,
) -> str:
    if context_data["request"]["mode"] != "action":
        return ""
    submode = str(context_data["request"]["submode"])
    registered = get_default_action_registry().get(submode)
    if not registered:
        return ""
    validation = registered.request_contract(campaign, conn, context_data, options)
    resolution = registered.resolve_contract(campaign, conn, context_data, options)
    lines = [
        f"- resolver: `{registered.name}`",
        f"- request_contract: `{'OK' if validation.ok else 'FAILED'}`",
        f"- resolution_status: `{resolution.status}`",
    ]
    for item in validation.missing_required:
        lines.append(f"- missing_required: `{item}`")
    for item in validation.errors:
        lines.append(f"- error: `{item}`")
    for item in validation.warnings:
        lines.append(f"- warning: `{item}`")
    for item in resolution.facts_used:
        lines.append(f"- fact_used: `{item}`")
    for item in resolution.rules_applied:
        lines.append(f"- rule_applied: `{item}`")
    for item in resolution.confirmations:
        lines.append(f"- confirmation: `{item}`")
    for item in resolution.warnings:
        lines.append(f"- resolution_warning: `{item}`")
    for item in resolution.narrative_constraints:
        lines.append(f"- narrative_constraint: `{item}`")
    return "\n".join(lines)


def render_preview_for_context(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: TurnAssistantOptions,
) -> str:
    if context_data["request"]["mode"] != "action":
        return ""
    submode = str(context_data["request"]["submode"])
    registered = get_default_action_registry().get(submode)
    if registered:
        return registered.preview(campaign, conn, context_data, options)
    return ""


def render_response_lint(context_data: dict[str, Any], options: TurnAssistantOptions) -> str:
    if not options.response_file and not options.response_text:
        return ""
    text = load_response_text(options.response_file, options.response_text)
    result = lint_response(
        text,
        turn_contract=load_turn_contract_from_context(context_data),
        strict=True,
    )
    return result.render().rstrip()


def render_proposal_validation(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: TurnAssistantOptions,
) -> str:
    if not options.proposal_json:
        return ""
    proposal = load_turn_proposal(options.proposal_json)
    response_text = load_response_text(options.response_file, options.response_text) if options.response_file or options.response_text else None
    return validate_turn_proposal(campaign, conn, proposal, response_text=response_text).render().rstrip()


def render_delta_validation_for_options(
    conn: sqlite3.Connection,
    options: TurnAssistantOptions,
) -> tuple[str, list[str], dict[str, Any] | None]:
    if not options.delta_json:
        return "未提供 delta，跳过 schema 校验。", [], None
    delta = load_delta(options.delta_json)
    errors = validate_delta_schema(delta, conn)
    return render_delta_validation(errors), errors, delta


def run_save_pipeline(
    campaign: Campaign,
    conn: sqlite3.Connection,
    options: TurnAssistantOptions,
    delta: dict[str, Any] | None,
    delta_errors: list[str],
) -> str:
    if not options.delta_json or delta is None:
        return "FAILED\n- --save requires --delta-json"
    if delta_errors:
        return "FAILED\n- delta schema validation failed; save was not run"
    validation = run_validation_pipeline(
        campaign,
        conn,
        profile="admin_or_legacy_save_turn",
        delta=delta,
        state_audit=True,
    )
    if not validation.ok:
        lines = ["FAILED", f"- profile: `{validation.profile}`", "- validation blocked save"]
        lines.extend(f"- {error}" for error in validation.errors)
        return "\n".join(lines)
    result = commit_turn_delta(
        campaign,
        conn,
        delta=delta,
        validation=validation,
        backup=True,
        backup_reason="pre_turn_assistant_save",
        rebuild_memory=options.rebuild_memory,
        run_post_check=True,
    )
    lines = [
        "OK" if result.ok else "FAILED",
        f"- profile: `{result.profile}`",
        f"- write_status: `{result.write_status}`",
        f"- projection_status: `{result.projection_status}`",
        f"- backup: `{result.backup_id}`",
        f"- saved_turn: `{result.turn_id}`",
        f"- snapshot: `{result.snapshot_path}`",
        f"- snapshot_json: `{result.snapshot_json_path}`",
        f"- cards: `{result.cards_count}`",
    ]
    if result.projection_report:
        if result.projection_report.requested_dirty:
            lines.append(f"- projection_dirty: `{', '.join(result.projection_report.requested_dirty)}`")
        if result.projection_report.requested_failed:
            lines.append(f"- projection_failed: `{', '.join(result.projection_report.requested_failed)}`")
        if result.projection_report.global_failed:
            lines.append(f"- projection_global_failed: `{', '.join(result.projection_report.global_failed)}`")
    if result.memory_summaries is not None:
        lines.append(f"- memory_summaries: `{result.memory_summaries}`")
        lines.append(f"- memory_report: `{result.memory_report_path}`")
    if result.check_errors:
        lines.append("- check errors:")
        lines.extend(f"  - {error}" for error in result.check_errors)
    else:
        lines.append("- check: `OK`")
    return "\n".join(lines)


def render_next_steps(
    context_data: dict[str, Any],
    options: TurnAssistantOptions,
    preview_ran: bool,
    delta_errors: list[str],
) -> list[str]:
    if not context_data["completeness"]["allow_proceed"]:
        return ["- 先向玩家确认缺失信息，不要推进结算。"]
    if context_data["request"]["mode"] == "query":
        return ["- 直接按结构化查询回复；不保存。"]
    steps: list[str] = []
    if not preview_ran and context_data["request"].get("requires_preview"):
        steps.append("- 补充 preview 参数并重跑 turn assistant。")
    if not options.response_file and not options.response_text:
        steps.append("- 生成 AI 回复后用 `response lint` 或 turn assistant 的 response lint 检查结构。")
    if not options.delta_json:
        steps.append("- 根据 preview 和实际叙事写 delta，再运行 `play validate-delta`。")
    elif delta_errors:
        steps.append("- 修复 delta schema 错误后再保存。")
    elif not options.save:
        steps.append("- 确认叙事和 delta 一致后，显式加 `--save` 保存。")
    else:
        steps.append("- 保存后继续下一轮 context build。")
    return steps
