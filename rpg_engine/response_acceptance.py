from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .campaign import Campaign
from .commit_service import commit_turn_proposal
from .delta_draft import (
    check_delta_response_consistency,
    draft_delta_from_response,
    render_delta_diff,
)
from .intent_router import route_intent, turn_contract_for_intent
from .response_lint import lint_response
from .proposal import TurnProposal
from .validation_pipeline import run_validation_pipeline


@dataclass(frozen=True)
class AcceptanceResult:
    delta: dict[str, Any]
    lint_errors: list[str]
    lint_warnings: list[str]
    draft_errors: list[str]
    draft_warnings: list[str]
    consistency_warnings: list[str]
    validation_errors: list[str]
    validation_warnings: list[str]
    saved_turn_id: str | None
    backup_id: str | None
    check_errors: list[str]
    memory_report_path: Path | None
    diff_markdown: str
    save_requested: bool
    save_allowed: bool
    decision: str
    turn_proposal: dict[str, Any]
    validation_report: dict[str, Any]

    @property
    def hard_blocked(self) -> bool:
        validation_blockers = [item for item in self.validation_errors if not is_confirmation_issue(item)]
        return bool(
            self.lint_errors
            or self.draft_errors
            or self.consistency_warnings
            or validation_blockers
            or self.check_errors
        )

    @property
    def validation_requires_confirmation(self) -> bool:
        return bool(self.validation_errors) and all(is_confirmation_issue(item) for item in self.validation_errors)

    def render(self) -> str:
        lines = [
            "# Response Acceptance Report",
            "",
            "## Decision",
            "",
            f"- decision: `{self.decision}`",
            f"- save_requested: `{'yes' if self.save_requested else 'no'}`",
            f"- save_allowed: `{'yes' if self.save_allowed else 'no'}`",
            f"- saved_turn: `{self.saved_turn_id or ''}`",
            f"- backup: `{self.backup_id or ''}`",
            f"- validation_profile: `{self.validation_report.get('profile', '')}`",
            "",
            "## Lint",
            "",
            "OK" if not self.lint_errors else "FAILED",
        ]
        if self.lint_errors:
            lines.extend(f"- {item}" for item in self.lint_errors)
        if self.lint_warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {item}" for item in self.lint_warnings)

        lines.extend(["", "## Draft Validation", "", "OK" if not self.draft_errors else "FAILED"])
        if self.draft_errors:
            lines.extend(f"- {item}" for item in self.draft_errors)
        if self.draft_warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {item}" for item in self.draft_warnings)

        lines.extend(["", "## Consistency", "", "OK" if not self.consistency_warnings else "WARN"])
        if self.consistency_warnings:
            lines.extend(f"- {item}" for item in self.consistency_warnings)

        lines.extend(["", "## Validation", "", "OK" if not self.validation_errors else "FAILED"])
        lines.append(f"- status: `{self.validation_report.get('status', '')}`")
        for stage in self.validation_report.get("stages", []):
            if not isinstance(stage, dict):
                continue
            lines.append(f"- {stage.get('name')}: `{stage.get('status')}`")
            skipped_reason = stage.get("skipped_reason")
            if skipped_reason:
                lines.append(f"  - skipped: {skipped_reason}")
            for issue in stage.get("issues", []):
                lines.append(f"  - {issue}")
        if self.validation_warnings and not self.validation_errors:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {item}" for item in self.validation_warnings)

        lines.extend(["", self.diff_markdown.rstrip()])
        if self.saved_turn_id:
            lines.extend(["", "## Save Pipeline", "", "OK" if not self.check_errors else "FAILED"])
            lines.append(f"- saved_turn: `{self.saved_turn_id}`")
            lines.append(f"- backup: `{self.backup_id}`")
            if self.memory_report_path:
                lines.append(f"- memory_report: `{self.memory_report_path}`")
            if self.check_errors:
                lines.extend(f"- {item}" for item in self.check_errors)
            else:
                lines.append("- check: `OK`")

        lines.extend(["", "## Delta", "", "```json", json.dumps(self.delta, ensure_ascii=False, indent=2, sort_keys=True), "```"])
        lines.extend(
            [
                "",
                "## Turn Proposal",
                "",
                "```json",
                json.dumps(self.turn_proposal, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
        lines.extend(["", "## Next Step"])
        if self.saved_turn_id:
            lines.append("- 已保存，下一轮用 `context build` 继续。")
        elif self.hard_blocked:
            lines.append("- 修复 lint/schema/一致性问题后重新验收，不要保存。")
        elif self.validation_requires_confirmation:
            lines.append("- response draft 需要人工确认；确认无误后可重跑并加 `--confirm-save`。")
        elif needs_confirmation(self.draft_warnings):
            lines.append("- 解析结果需要确认；确认无误后可重跑并加 `--confirm-save`。")
        elif not self.save_requested:
            lines.append("- 当前可保存；需要自动保存时重跑并加 `--save-if-safe`。")
        else:
            lines.append("- 本次未保存；检查 decision 和 warning 后决定是否显式确认。")
        return "\n".join(lines).rstrip() + "\n"


def accept_response(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    user_text: str,
    response_text: str,
    mode: str = "action",
    submode: str | None = None,
    intent: str = "accepted_response",
    save_if_safe: bool = False,
    confirm_save: bool = False,
    rebuild_memory: bool = False,
) -> AcceptanceResult:
    intent_obj = route_intent(campaign, conn, user_text, mode=mode, submode=submode)
    turn_contract = turn_contract_for_intent(intent_obj)
    lint = lint_response(response_text, turn_contract=turn_contract, strict=True)
    draft = draft_delta_from_response(conn, user_text=user_text, response_text=response_text, intent=intent)
    turn_proposal = TurnProposal(
        proposal_id=f"response-draft:{intent}",
        intent=intent_obj,
        context_id=None,
        preview=None,
        response_text=response_text,
        delta=draft.delta,
        delta_source="response_draft",
        provenance={"source": "response_acceptance.accept_response", "draft_intent": intent},
        human_confirmed=confirm_save,
        facts_used=(),
        narrative_claims=(),
        turn_contract=turn_contract,
    )
    consistency = check_delta_response_consistency(draft.delta, response_text)
    consistency.extend(response_state_change_blockers(draft.delta))
    diff = render_delta_diff(conn, draft.delta)

    save_requested = save_if_safe or confirm_save
    save_allowed, decision = decide_save(
        lint_errors=lint.errors,
        draft_errors=draft.errors,
        draft_warnings=draft.warnings,
        consistency_warnings=consistency,
        save_if_safe=save_if_safe,
        confirm_save=confirm_save,
    )
    validation = run_validation_pipeline(
        campaign,
        conn,
        profile="response_acceptance",
        delta=draft.delta,
        proposal=turn_proposal,
        response_text=response_text,
        state_audit=True,
    )
    validation_errors = list(validation.errors)
    validation_warnings = list(validation.warnings)
    validation_report = validation.to_dict()

    if save_allowed and not validation.ok:
        save_allowed = False
        if validation_errors and all(is_confirmation_issue(item) for item in validation_errors):
            decision = "confirmation_required"
        else:
            blocked_stage = first_blocked_stage(validation_report)
            decision = f"blocked:{blocked_stage or 'validation_pipeline'}"

    saved_turn_id: str | None = None
    backup_id: str | None = None
    check_errors: list[str] = []
    memory_report_path: Path | None = None

    if save_allowed:
        commit = commit_turn_proposal(
            campaign,
            conn,
            proposal=turn_proposal,
            validation=validation,
            backup=True,
            backup_reason="pre_accept_response_save",
            rebuild_memory=rebuild_memory,
            run_post_check=True,
        )
        saved_turn_id = commit.turn_id
        backup_id = commit.backup_id
        check_errors = list(commit.check_errors)
        memory_report_path = commit.memory_report_path

    return AcceptanceResult(
        delta=draft.delta,
        lint_errors=lint.errors,
        lint_warnings=lint.warnings,
        draft_errors=draft.errors,
        draft_warnings=draft.warnings,
        consistency_warnings=consistency,
        validation_errors=validation_errors,
        validation_warnings=validation_warnings,
        saved_turn_id=saved_turn_id,
        backup_id=backup_id,
        check_errors=check_errors,
        memory_report_path=memory_report_path,
        diff_markdown=diff,
        save_requested=save_requested,
        save_allowed=save_allowed,
        decision=decision,
        turn_proposal=turn_proposal.to_dict(),
        validation_report=validation_report,
    )


def decide_save(
    *,
    lint_errors: list[str],
    draft_errors: list[str],
    draft_warnings: list[str],
    consistency_warnings: list[str],
    save_if_safe: bool,
    confirm_save: bool,
) -> tuple[bool, str]:
    if lint_errors:
        return False, "blocked:lint"
    if draft_errors:
        return False, "blocked:draft_schema"
    if consistency_warnings:
        return False, "blocked:response_delta_mismatch"
    if confirm_save:
        return True, "confirmed_save"
    if not save_if_safe:
        return False, "ready:preview_only"
    if needs_confirmation(draft_warnings):
        return False, "confirmation_required"
    return True, "safe_precheck_passed"


def needs_confirmation(warnings: list[str]) -> bool:
    return bool(warnings)


def is_confirmation_issue(issue: str) -> bool:
    text = str(issue)
    return "requires human confirmation" in text or "human confirmation before approval" in text


def first_blocked_stage(report: dict[str, Any]) -> str:
    for stage in report.get("stages", []):
        if isinstance(stage, dict) and stage.get("status") == "blocked":
            return str(stage.get("name") or "")
    return ""


def response_state_change_blockers(delta: dict[str, Any]) -> list[str]:
    rows = parsed_state_change_rows(delta)
    meaningful_rows = [
        row for row in rows
        if str(row.get("type", "")).strip() not in {"", "无"}
        and str(row.get("change", "")).strip() not in {"", "无"}
    ]
    if not meaningful_rows:
        return []
    return [
        "accept-response parsed non-empty 状态变化 but only produced a response_delta_draft event; "
        "save an authoritative gameplay delta through play validate-delta/play commit with TurnProposal instead."
    ]


def parsed_state_change_rows(delta: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    events = delta.get("events", [])
    if not isinstance(events, list):
        return rows
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        state_changes = payload.get("state_changes", [])
        if isinstance(state_changes, list):
            rows.extend(item for item in state_changes if isinstance(item, dict))
    return rows
