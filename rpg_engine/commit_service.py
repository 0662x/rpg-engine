from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .archivist import run_archivist_workflow
from .backup import create_backup
from .campaign import Campaign
from .projection_service import ProjectionReport, ProjectionService
from .proposal import TurnProposal
from .save import save_turn_delta
from .validation_pipeline import COMMIT_ALLOWED_PROFILES, ValidationReport, stable_delta_digest
from .validators import run_checks


@dataclass(frozen=True)
class CommitResult:
    campaign_id: str
    profile: str
    turn_id: str
    write_status: str = "committed"
    projection_status: str | None = None
    backup_id: str | None = None
    snapshot_path: Path | None = None
    snapshot_json_path: Path | None = None
    cards_count: int = 0
    check_errors: tuple[str, ...] = ()
    memory_report_path: Path | None = None
    memory_summaries: int | None = None
    archivist_suggestion_id: str | None = None
    archivist_proposal_ids: tuple[str, ...] = ()
    archivist_ai_status: str | None = None
    state_audit: dict | None = None
    validation_report: ValidationReport | None = None
    projection_report: ProjectionReport | None = None

    @property
    def ok(self) -> bool:
        return (
            self.write_status == "committed"
            and not self.check_errors
            and (self.projection_report is None or self.projection_report.ok)
        )

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "profile": self.profile,
            "turn_id": self.turn_id,
            "ok": self.ok,
            "write_status": self.write_status,
            "projection_status": self.projection_status,
            "backup_id": self.backup_id,
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "snapshot_json_path": str(self.snapshot_json_path) if self.snapshot_json_path else None,
            "cards_count": self.cards_count,
            "check_errors": list(self.check_errors),
            "memory_report_path": str(self.memory_report_path) if self.memory_report_path else None,
            "memory_summaries": self.memory_summaries,
            "archivist_suggestion_id": self.archivist_suggestion_id,
            "archivist_proposal_ids": list(self.archivist_proposal_ids),
            "archivist_ai_status": self.archivist_ai_status,
            "state_audit": self.state_audit,
            "validation_report": self.validation_report.to_dict() if self.validation_report else None,
            "projection_report": self.projection_report.to_dict() if self.projection_report else None,
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def commit_turn_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    delta: dict,
    validation: ValidationReport,
    backup: bool = True,
    backup_reason: str = "pre_commit_turn",
    archivist_suggest: bool = False,
    archivist_ai: str = "off",
    archivist_provider: str = "",
    archivist_model: str = "",
    archivist_timeout: int = 20,
    archivist_enqueue: bool = True,
    rebuild_memory: bool = False,
    run_post_check: bool = True,
) -> CommitResult:
    if not validation.ok:
        raise ValueError("Validation blocked commit:\n" + "\n".join(f"- {error}" for error in validation.errors))
    if validation.profile not in COMMIT_ALLOWED_PROFILES:
        raise ValueError(f"validation profile cannot commit: {validation.profile}")
    if validation.profile == "player_turn_commit" and not validation.proposal_id:
        raise ValueError("player_turn_commit requires an approved TurnProposal validation")
    if validation.profile == "player_turn_commit":
        missing = [key for key in ("expected_turn_id", "command_id") if not delta.get(key)]
        if missing:
            raise ValueError("player_turn_commit requires " + ", ".join(missing))
    current_delta_digest = stable_delta_digest(delta)
    if (
        validation.delta_digest is None
        or current_delta_digest is None
        or validation.delta_digest != current_delta_digest
    ):
        raise ValueError("validation report does not match commit delta")

    backup_record = None
    archivist_suggestion_id = None
    archivist_proposal_ids: tuple[str, ...] = ()
    archivist_ai_status = None
    memory_report_path = None
    memory_summaries = None

    def create_pre_commit_backup() -> None:
        nonlocal backup_record
        backup_record = create_backup(campaign, reason=backup_reason)

    def remove_pre_commit_backup() -> None:
        if backup_record is not None:
            shutil.rmtree(backup_record.path)

    turn_id = save_turn_delta(
        campaign,
        conn,
        delta,
        before_write=create_pre_commit_backup if backup else None,
        rollback_write_artifacts=remove_pre_commit_backup if backup else None,
    )
    if archivist_suggest:
        archivist_result = run_archivist_workflow(
            conn,
            turn_id=turn_id,
            ai=archivist_ai,
            provider=archivist_provider,
            model=archivist_model,
            timeout=archivist_timeout,
            enqueue=archivist_enqueue,
        )
        archivist_suggestion_id = archivist_result.suggestion_id
        archivist_proposal_ids = tuple(record.id for record in archivist_result.proposals)
        archivist_ai_status = archivist_result.suggest_result.ai_status

    if conn.in_transaction:
        conn.commit()
    projection_names = ["snapshots", "cards"]
    if rebuild_memory:
        projection_names.append("memory")
    projection_report = ProjectionService(campaign, conn).refresh(
        names=projection_names,
        dirty_only=False,
        profile=f"{validation.profile}:post_commit",
        commit_policy="caller_committed_required",
    )
    snapshot_artifacts = projection_report.artifacts_for("snapshots")
    cards_item = projection_report.item("cards")
    memory_item = projection_report.item("memory")
    snapshot_path = Path(snapshot_artifacts[0]) if len(snapshot_artifacts) >= 1 else None
    snapshot_json_path = Path(snapshot_artifacts[1]) if len(snapshot_artifacts) >= 2 else None
    cards_count = int(cards_item.metadata.get("count", 0)) if cards_item else 0

    check_errors = tuple(run_checks(conn)) if run_post_check else ()
    if memory_item and memory_item.status == "clean":
        memory_report_paths = memory_item.artifacts
        memory_report_path = Path(memory_report_paths[0]) if memory_report_paths else None
        memory_summaries = int(memory_item.metadata.get("summaries", 0))

    return CommitResult(
        campaign_id=campaign.campaign_id,
        profile=validation.profile,
        turn_id=turn_id,
        write_status="committed",
        projection_status=projection_report.status,
        backup_id=backup_record.id if backup_record else None,
        snapshot_path=snapshot_path,
        snapshot_json_path=snapshot_json_path,
        cards_count=cards_count,
        check_errors=check_errors,
        memory_report_path=memory_report_path,
        memory_summaries=memory_summaries,
        archivist_suggestion_id=archivist_suggestion_id,
        archivist_proposal_ids=archivist_proposal_ids,
        archivist_ai_status=archivist_ai_status,
        state_audit=validation.state_audit,
        validation_report=validation,
        projection_report=projection_report,
    )


def commit_turn_proposal(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    proposal: TurnProposal,
    validation: ValidationReport,
    backup: bool = True,
    backup_reason: str = "pre_commit_turn",
    archivist_suggest: bool = False,
    archivist_ai: str = "off",
    archivist_provider: str = "",
    archivist_model: str = "",
    archivist_timeout: int = 20,
    archivist_enqueue: bool = True,
    rebuild_memory: bool = False,
    run_post_check: bool = True,
) -> CommitResult:
    if validation.proposal_id != proposal.proposal_id:
        raise ValueError("validation report does not match TurnProposal")
    if proposal.delta is None:
        raise ValueError("TurnProposal has no delta to commit")
    assert_turn_proposal_not_committed(conn, proposal)
    return commit_turn_delta(
        campaign,
        conn,
        delta=proposal.delta,
        validation=validation,
        backup=backup,
        backup_reason=backup_reason,
        archivist_suggest=archivist_suggest,
        archivist_ai=archivist_ai,
        archivist_provider=archivist_provider,
        archivist_model=archivist_model,
        archivist_timeout=archivist_timeout,
        archivist_enqueue=archivist_enqueue,
        rebuild_memory=rebuild_memory,
        run_post_check=run_post_check,
    )


def assert_turn_proposal_not_committed(conn: sqlite3.Connection, proposal: TurnProposal) -> None:
    delta = proposal.delta or {}
    command_id = delta.get("command_id")
    if not command_id:
        return
    row = conn.execute("select id from turns where command_id = ?", (str(command_id),)).fetchone()
    if row:
        raise ValueError(f"TurnProposal already committed as {row['id']}")
