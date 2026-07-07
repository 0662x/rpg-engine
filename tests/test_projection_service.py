from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rpg_engine.campaign import load_campaign
from rpg_engine.commit_service import commit_turn_delta
from rpg_engine.db import connect, init_database
from rpg_engine.projection_service import ProjectionReport, ProjectionService
from rpg_engine.projections import PROJECTION_VERSIONS, refresh_projections, render_projection_status
from rpg_engine.save import save_turn_delta
from rpg_engine.validation_pipeline import run_validation_pipeline


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def copy_initialized_campaign(tmp: str | Path) -> Path:
    target = Path(tmp) / "campaign"
    shutil.copytree(MINIMAL_FIXTURE, target)
    init_database(load_campaign(target), force=True)
    return target


def current_turn(conn: sqlite3.Connection) -> str:
    row = conn.execute("select value from meta where key='current_turn_id'").fetchone()
    return str(row["value"] if isinstance(row, sqlite3.Row) else row[0])


def wait_delta(conn: sqlite3.Connection, command_id: str) -> dict[str, object]:
    return {
        "expected_turn_id": current_turn(conn),
        "command_id": command_id,
        "user_text": "等待片刻",
        "intent": "wait",
        "changed": False,
        "summary": "No significant change.",
    }


def projection_status(conn: sqlite3.Connection, name: str) -> tuple[str, str | None]:
    row = conn.execute("select status, last_error from projection_state where name=?", (name,)).fetchone()
    return str(row["status"]), row["last_error"]


class ProjectionServiceTests(unittest.TestCase):
    def test_refresh_reports_projection_success_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                save_turn_delta(campaign, conn, wait_delta(conn, "projection-success"))
                report = ProjectionService(campaign, conn).refresh(
                    names=["snapshots", "cards"],
                    dirty_only=True,
                    profile="test:projection_success",
                )

                self.assertTrue(report.ok, report.to_dict())
                self.assertEqual(report.status, "clean")
                self.assertEqual(report.global_status, "dirty")
                self.assertIn("snapshots", report.refreshed)
                self.assertIn("cards", report.refreshed)
                self.assertEqual(report.dirty, ())
                self.assertIn("memory", report.global_dirty)
                self.assertEqual(projection_status(conn, "snapshots")[0], "clean")
                self.assertEqual(projection_status(conn, "cards")[0], "clean")
                self.assertTrue(report.artifacts_for("snapshots")[0].endswith("snapshots/current.md"))
                self.assertGreater(projection_count(report, "cards"), 0)
                self.assertIsNotNone(report.duration_ms)
                self.assertIsNotNone(report.item("snapshots").duration_ms)
                report_dict = report.to_dict()
                self.assertEqual(report_dict["profile"], "test:projection_success")
                self.assertEqual(report_dict["requested"], ["snapshots", "cards"])
                self.assertIsNotNone(report_dict["started_at"])
                self.assertIsNotNone(report_dict["finished_at"])
                items = {item["name"]: item for item in report_dict["items"]}
                self.assertEqual(items["snapshots"]["previous_status"], "dirty")
                self.assertEqual(items["snapshots"]["turn_id"], current_turn(conn))
                self.assertEqual(items["snapshots"]["version"], PROJECTION_VERSIONS["snapshots"])
                self.assertTrue(items["snapshots"]["artifacts"][0].endswith("snapshots/current.md"))
                self.assertEqual(items["cards"]["version"], PROJECTION_VERSIONS["cards"])
                self.assertGreater(items["cards"]["metadata"]["count"], 0)

    def test_refresh_partial_failure_marks_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                save_turn_delta(campaign, conn, wait_delta(conn, "projection-partial-failure"))
                with mock.patch("rpg_engine.render.write_current_snapshot", side_effect=OSError("injected snapshot failure")):
                    report = ProjectionService(campaign, conn).refresh(
                        names=["snapshots", "cards"],
                        dirty_only=False,
                        profile="test:projection_failure",
                    )

                self.assertFalse(report.ok)
                self.assertEqual(report.status, "partial_failure")
                self.assertIn("snapshots", report.failed)
                self.assertIn("cards", report.refreshed)
                status, error = projection_status(conn, "snapshots")
                self.assertEqual(status, "failed")
                self.assertIn("injected snapshot failure", error or "")
                self.assertEqual(projection_status(conn, "cards")[0], "clean")

    def test_targeted_repair_ignores_unrelated_failed_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                save_turn_delta(campaign, conn, wait_delta(conn, "projection-targeted-repair"))
                conn.execute(
                    "update projection_state set status='dirty', last_error=null where name='snapshots'"
                )
                conn.execute(
                    "update projection_state set status='failed', last_error='cards still broken' where name='cards'"
                )
                conn.commit()

                report = ProjectionService(campaign, conn).refresh(
                    names=["snapshots"],
                    dirty_only=True,
                    profile="test:targeted_repair",
                    commit_policy="caller_committed_required",
                )

                self.assertTrue(report.ok, report.to_dict())
                self.assertEqual(report.status, "clean")
                self.assertEqual(report.failed, ())
                self.assertIn("snapshots", report.refreshed)
                self.assertIn("cards", report.global_failed)
                self.assertEqual(report.global_status, "failed")
                report_dict = report.to_dict()
                self.assertEqual(report_dict["requested"], ["snapshots"])
                self.assertEqual(report_dict["requested_failed"], [])
                self.assertEqual(report_dict["global_failed"], ["cards"])
                self.assertEqual(report_dict["global_status"], "failed")
                self.assertIsNotNone(report_dict["duration_ms"])

    def test_targeted_repair_reports_unrelated_failed_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                save_turn_delta(campaign, conn, wait_delta(conn, "projection-targeted-outbox"))
                conn.execute("update projection_state set status='dirty', last_error=null where name='snapshots'")
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values('out:unrelated-failed', 'unsupported.topic', '{}', 'failed', 2, 'now', null, 'unsupported outbox topic')
                    """
                )
                conn.commit()

                report = ProjectionService(campaign, conn).refresh(
                    names=["snapshots"],
                    dirty_only=True,
                    profile="test:targeted_outbox",
                    commit_policy="caller_committed_required",
                )

                self.assertFalse(report.ok, report.to_dict())
                self.assertEqual(report.status, "partial_failure")
                self.assertEqual(report.global_status, "failed")
                self.assertEqual(report.outbox_status, "failed")
                self.assertIn("snapshots", report.refreshed)
                self.assertIn("outbox.out:unrelated-failed: status is failed", "\n".join(report.errors))
                report_dict = report.to_dict()
                self.assertEqual(report_dict["outbox_status"], "failed")
                self.assertEqual(report_dict["outbox_non_done"][0]["id"], "out:unrelated-failed")
                self.assertEqual(report_dict["outbox_non_done"][0]["status"], "failed")
                rendered = report.render()
                self.assertIn("last_error=`unsupported outbox topic`", rendered)
                self.assertIn("created_at=`now`", rendered)
                self.assertIn("processed_at=`-`", rendered)

    def test_commit_result_carries_projection_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                delta = wait_delta(conn, "projection-commit-report")
                validation = run_validation_pipeline(
                    campaign,
                    conn,
                    profile="admin_or_legacy_save_turn",
                    delta=delta,
                    state_audit=True,
                )
                result = commit_turn_delta(campaign, conn, delta=delta, validation=validation, backup=False)

                self.assertIsNotNone(result.projection_report)
                assert result.projection_report is not None
                self.assertTrue(result.ok, result.to_dict())
                self.assertEqual(result.write_status, "committed")
                self.assertEqual(result.projection_status, "clean")
                self.assertIn("snapshots", result.projection_report.refreshed)
                self.assertIn("cards", result.projection_report.refreshed)
                self.assertEqual(result.projection_report.status, "clean")
                self.assertIn("projection_report", result.to_dict())
                self.assertEqual(result.to_dict()["write_status"], "committed")
                self.assertEqual(result.to_dict()["projection_status"], "clean")
                self.assertEqual(result.to_dict()["projection_report"]["profile"], "admin_or_legacy_save_turn:post_commit")

    def test_commit_result_reports_projection_failure_without_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                delta = wait_delta(conn, "projection-commit-failure")
                validation = run_validation_pipeline(
                    campaign,
                    conn,
                    profile="admin_or_legacy_save_turn",
                    delta=delta,
                    state_audit=True,
                )
                with mock.patch(
                    "rpg_engine.render.write_current_snapshot",
                    side_effect=OSError("injected post-commit projection failure"),
                ):
                    result = commit_turn_delta(
                        campaign,
                        conn,
                        delta=delta,
                        validation=validation,
                        backup=False,
                        run_post_check=False,
                    )

                self.assertFalse(result.ok)
                self.assertEqual(result.write_status, "committed")
                self.assertEqual(result.projection_status, "partial_failure")
                self.assertEqual(current_turn(conn), result.turn_id)
                assert result.projection_report is not None
                self.assertIn("snapshots", result.projection_report.requested_failed)
                self.assertIn("cards", result.projection_report.refreshed)

    def test_strict_commit_policy_rejects_uncommitted_caller_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute("update meta set value=value where key='current_turn_id'")
                self.assertTrue(conn.in_transaction)

                with self.assertRaisesRegex(RuntimeError, "committed before refresh"):
                    ProjectionService(campaign, conn).refresh(
                        names=["snapshots"],
                        dirty_only=False,
                        profile="test:strict_policy",
                        commit_policy="caller_committed_required",
                    )
                conn.rollback()

    def test_stale_projection_version_is_reported_and_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    insert into projection_state(name, version, last_turn_id, status, updated_at, last_error)
                    values ('snapshots', 0, ?, 'clean', '2026-01-01T00:00:00+00:00', null)
                    on conflict(name) do update set
                      version=0,
                      status='clean',
                      last_error=null
                    """,
                    (current_turn(conn),),
                )
                conn.commit()

                status_text = render_projection_status(conn)
                self.assertIn("| `snapshots` | 0 |", status_text)
                self.assertIn("stale", status_text)
                conn.commit()

                report = ProjectionService(campaign, conn).refresh(
                    names=["snapshots"],
                    dirty_only=True,
                    profile="test:stale_repair",
                    commit_policy="caller_committed_required",
                )

                self.assertTrue(report.ok, report.to_dict())
                self.assertEqual(report.status, "clean")
                self.assertIn("snapshots", report.refreshed)
                row = conn.execute("select version, status from projection_state where name='snapshots'").fetchone()
                self.assertEqual(int(row["version"]), PROJECTION_VERSIONS["snapshots"])
                self.assertEqual(row["status"], "clean")

    def test_legacy_refresh_entry_returns_projection_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                save_turn_delta(campaign, conn, wait_delta(conn, "projection-legacy-entry"))
                report = refresh_projections(campaign, conn, names=["snapshots"], dirty_only=False)

                self.assertIsInstance(report, ProjectionReport)
                self.assertEqual(report.profile, "legacy_refresh_projections")
                self.assertTrue(report.ok, report.to_dict())
                self.assertEqual(report.item("snapshots").status, "clean")


def projection_count(report: ProjectionReport, name: str) -> int:
    item = report.item(name)
    if not item:
        return 0
    return int(item.metadata.get("count", len(item.artifacts)))


if __name__ == "__main__":
    unittest.main()
