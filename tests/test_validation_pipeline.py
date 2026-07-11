from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from rpg_engine.campaign import Campaign, load_campaign
from rpg_engine.commit_service import commit_turn_delta
from rpg_engine.db import connect, init_database, upsert_clock
from rpg_engine.proposal import turn_proposal_from_dict
from rpg_engine.runtime import GMRuntime
from rpg_engine.validation_pipeline import VALIDATION_PROFILES, run_validation_pipeline, stable_delta_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
OFFICIAL_EXAMPLE = ENGINE_ROOT / "examples" / "v1_minimal_adventure"


def copy_initialized_campaign(tmp: str | Path, source: Path) -> Path:
    target = Path(tmp) / source.name
    shutil.copytree(source, target)
    init_database(load_campaign(target), force=True)
    return target


def current_turn(campaign: Campaign | Path) -> str:
    root = campaign.root if isinstance(campaign, Campaign) else campaign
    conn = sqlite3.connect(root / "data" / "game.sqlite")
    try:
        row = conn.execute("select value from meta where key = 'current_turn_id'").fetchone()
    finally:
        conn.close()
    return "" if row is None else str(row[0])


def wait_delta(command_id: str = "validation-pipeline-wait") -> dict[str, object]:
    return {
        "expected_turn_id": "turn:seed",
        "command_id": command_id,
        "user_text": "等待片刻",
        "intent": "wait",
        "changed": False,
        "summary": "No significant change.",
    }


class ValidationPipelineTests(unittest.TestCase):
    def test_known_profiles_are_centralized_contract(self) -> None:
        self.assertEqual(
            VALIDATION_PROFILES,
            {
                "preview_only",
                "player_turn_commit",
                "response_acceptance",
                "maintenance_commit",
                "admin_or_legacy_save_turn",
                "import_or_migration",
            },
        )

    def test_preview_only_profile_runs_request_and_resolve_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp, MINIMAL_FIXTURE))
            with connect(campaign) as conn:
                report = run_validation_pipeline(
                    campaign,
                    conn,
                    profile="preview_only",
                    action="rest",
                    action_options={"until": "morning"},
                )

            self.assertTrue(report.ok, report.to_dict())
            self.assertEqual(report.stage("profile").artifacts["allowed_commit"], False)
            self.assertEqual(report.stage("resolver_request_contract").status, "ok")
            self.assertIn(report.stage("resolver_resolve_contract").status, {"ok", "warning"})
            self.assertEqual(report.stage("delta_schema").status, "skipped")
            self.assertEqual(report.stage("write_guard").status, "ok")

    def test_player_turn_profile_reports_proposal_and_resolver_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GMRuntime.from_path(copy_initialized_campaign(tmp, OFFICIAL_EXAMPLE))
            preview = runtime.preview_action("rest", {"until": "morning", "user_text": "rest until morning"})
            proposal = turn_proposal_from_dict(preview.turn_proposal or {})
            with connect(runtime.campaign) as conn:
                report = run_validation_pipeline(
                    runtime.campaign,
                    conn,
                    profile="player_turn_commit",
                    delta=proposal.delta,
                    proposal=proposal,
                    state_audit=True,
                )

            self.assertTrue(report.ok, report.to_dict())
            self.assertEqual(report.proposal_id, proposal.proposal_id)
            self.assertIn(report.stage("proposal_guard").status, {"ok", "warning"})
            self.assertEqual(report.stage("delta_schema").status, "ok")
            self.assertEqual(report.stage("resolver_request_contract").status, "ok")
            self.assertIn(report.stage("resolver_resolve_contract").status, {"ok", "warning"})
            self.assertEqual(report.stage("resolver_delta_contract").status, "ok")
            self.assertEqual(report.stage("state_audit").status, "ok")
            self.assertEqual(report.delta_digest, stable_delta_digest(proposal.delta))
            self.assertEqual(report.to_dict()["delta_digest"], stable_delta_digest(proposal.delta))

    def test_player_turn_profile_requires_write_guard_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GMRuntime.from_path(copy_initialized_campaign(tmp, OFFICIAL_EXAMPLE))
            preview = runtime.preview_action("rest", {"until": "morning", "user_text": "rest until morning"})
            proposal = turn_proposal_from_dict(preview.turn_proposal or {})
            bad_delta = dict(proposal.delta or {})
            bad_delta.pop("expected_turn_id", None)
            bad_delta.pop("command_id", None)
            bad_proposal = replace(proposal, proposal_id="proposal:test-missing-write-guard", delta=bad_delta)
            with connect(runtime.campaign) as conn:
                report = run_validation_pipeline(
                    runtime.campaign,
                    conn,
                    profile="player_turn_commit",
                    delta=bad_delta,
                    proposal=bad_proposal,
                    state_audit=True,
                )
                with self.assertRaisesRegex(ValueError, "Validation blocked commit"):
                    commit_turn_delta(runtime.campaign, conn, delta=bad_delta, validation=report, backup=False)

            self.assertFalse(report.ok)
            self.assertEqual(report.stage("write_guard").status, "blocked")
            self.assertIn("player_turn_commit requires expected_turn_id, command_id", report.errors)

    def test_response_acceptance_profile_blocks_unconfirmed_response_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GMRuntime.from_path(copy_initialized_campaign(tmp, OFFICIAL_EXAMPLE))
            preview = runtime.preview_action("rest", {"until": "morning", "user_text": "rest until morning"})
            proposal = replace(
                turn_proposal_from_dict(preview.turn_proposal or {}),
                proposal_id="proposal:test-response-draft",
                delta_source="response_draft",
                human_confirmed=False,
            )
            response_text = "\n".join(
                [
                    "## 场景",
                    "营地安静下来。",
                    "## 行动结果",
                    "你休息到早上。",
                    "## 状态变化",
                    "无",
                    "## 保存状态",
                    "尚未保存，需要 validate_delta 和 commit_turn。",
                    "## 后续行动",
                    "1. 观察营地",
                ]
            )
            with connect(runtime.campaign) as conn:
                report = run_validation_pipeline(
                    runtime.campaign,
                    conn,
                    profile="response_acceptance",
                    delta=proposal.delta,
                    proposal=proposal,
                    response_text=response_text,
                    state_audit=True,
                )

            self.assertFalse(report.ok)
            self.assertEqual(report.stage("proposal_guard").status, "blocked")
            self.assertTrue(any("response_draft requires human confirmation" in item for item in report.errors))

    def test_admin_legacy_profile_warns_and_can_commit_without_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp, MINIMAL_FIXTURE))
            delta = wait_delta("validation-admin-legacy")
            with connect(campaign) as conn:
                report = run_validation_pipeline(
                    campaign,
                    conn,
                    profile="admin_or_legacy_save_turn",
                    delta=delta,
                    state_audit=True,
                )
                result = commit_turn_delta(campaign, conn, delta=delta, validation=report, backup=False)

            self.assertTrue(report.ok, report.to_dict())
            self.assertEqual(report.status, "warning")
            self.assertEqual(report.stage("write_guard").status, "warning")
            self.assertEqual(report.stage("resolver_delta_contract").status, "warning")
            self.assertEqual(result.profile, "admin_or_legacy_save_turn")
            self.assertEqual(current_turn(campaign), "turn:000001")

    def test_commit_service_rejects_validation_report_for_different_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp, MINIMAL_FIXTURE))
            delta = wait_delta("validation-digest-a")
            other_delta = wait_delta("validation-digest-b")
            with connect(campaign) as conn:
                report = run_validation_pipeline(
                    campaign,
                    conn,
                    profile="admin_or_legacy_save_turn",
                    delta=delta,
                    state_audit=True,
                )
                with self.assertRaisesRegex(ValueError, "does not match commit delta"):
                    commit_turn_delta(campaign, conn, delta=other_delta, validation=report, backup=False)
                with self.assertRaisesRegex(ValueError, "does not match commit delta"):
                    commit_turn_delta(
                        campaign,
                        conn,
                        delta={"meta": {"private": object()}},
                        validation=replace(report, delta_digest=None),
                        backup=False,
                    )

            self.assertTrue(report.ok, report.to_dict())
            self.assertEqual(report.delta_digest, stable_delta_digest(delta))
            self.assertNotEqual(report.delta_digest, stable_delta_digest(other_delta))
            self.assertEqual(current_turn(campaign), "turn:seed")

    def test_maintenance_profile_validates_without_player_action_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp, MINIMAL_FIXTURE))
            with connect(campaign) as conn:
                report = run_validation_pipeline(
                    campaign,
                    conn,
                    profile="maintenance_commit",
                    delta=wait_delta("validation-maintenance"),
                    state_audit=True,
                )

            self.assertTrue(report.ok, report.to_dict())
            self.assertEqual(report.profile, "maintenance_commit")
            self.assertEqual(report.stage("resolver_request_contract").status, "skipped")
            self.assertEqual(report.stage("resolver_delta_contract").status, "skipped")

    def test_player_commit_service_rejects_delta_without_turn_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp, MINIMAL_FIXTURE))
            delta = wait_delta("validation-player-no-proposal")
            with connect(campaign) as conn:
                report = run_validation_pipeline(campaign, conn, profile="player_turn_commit", delta=delta)
                with self.assertRaisesRegex(ValueError, "requires an approved TurnProposal"):
                    commit_turn_delta(campaign, conn, delta=delta, validation=report, backup=False)

            self.assertTrue(report.ok, report.to_dict())
            self.assertEqual(current_turn(campaign), "turn:seed")

    def test_player_turn_profile_uses_player_progress_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp, MINIMAL_FIXTURE))
            delta = {
                "expected_turn_id": "turn:seed",
                "command_id": "validation-hidden-clock",
                "user_text": "advance hidden clock",
                "intent": "clock",
                "summary": "Hidden progress attempted.",
                "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                "tick_clocks": [{"id": "clock:hidden-pipeline", "delta": 1, "reason": "Hidden pipeline pressure."}],
            }
            with connect(campaign) as conn:
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-pipeline",
                        "name": "Hidden Pipeline Clock",
                        "summary": "Hidden from player validation.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "Hidden consequence.",
                    },
                )
                conn.commit()
                player_report = run_validation_pipeline(campaign, conn, profile="player_turn_commit", delta=delta)
                response_report = run_validation_pipeline(campaign, conn, profile="response_acceptance", delta=delta)
                maintenance_report = run_validation_pipeline(campaign, conn, profile="maintenance_commit", delta=delta)

            self.assertFalse(player_report.ok, player_report.to_dict())
            self.assertEqual(player_report.stage("delta_schema").artifacts["caller_view"], "player")
            self.assertIn("$.tick_clocks[0].id: unavailable clock clock:hidden-pipeline", player_report.errors)
            self.assertFalse(response_report.ok, response_report.to_dict())
            self.assertEqual(response_report.stage("delta_schema").artifacts["caller_view"], "player")
            self.assertIn("$.tick_clocks[0].id: unavailable clock clock:hidden-pipeline", response_report.errors)
            self.assertEqual(maintenance_report.stage("delta_schema").status, "ok")
            self.assertEqual(maintenance_report.stage("delta_schema").artifacts["caller_view"], "maintenance")


if __name__ == "__main__":
    unittest.main()
