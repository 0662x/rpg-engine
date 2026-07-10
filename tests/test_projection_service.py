from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from rpg_engine.campaign import load_campaign
from rpg_engine.commit_service import commit_turn_delta
from rpg_engine.db import connect, init_database
from rpg_engine.memory import memory_projection_health, write_memory_report
from rpg_engine import projection_service as projection_service_module
from rpg_engine.projection_service import (
    ProjectionItemReport,
    ProjectionReport,
    ProjectionService,
)
from rpg_engine.projections import (
    PROJECTION_VERSIONS,
    mark_projection_clean,
    mark_projection_failed,
    mark_projection_failed_if_unchanged,
    mark_projections_clean,
    mark_projections_dirty,
    next_projection_generation,
    refresh_projections,
    render_projection_status,
)
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

    def test_memory_effective_health_is_used_by_status_and_global_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, source_turn_ids_json,
                     freshness_turn_id, freshness_evidence_json, updated_at)
                    values('memory:legacy-diagnostics', 'world', null, 'Legacy memory',
                           'Legacy summary', '["turn:seed"]', null, '{}',
                           '2026-07-10T00:00:00+00:00')
                    """
                )
                conn.execute(
                    """
                    update schema_migrations
                    set applied_at='2026-07-10T01:00:00+00:00'
                    where id='0009_memory_summary_provenance'
                    """
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean', '2026-07-10T00:00:00+00:00', null)
                    """,
                    (current_turn(conn),),
                )
                conn.commit()

                status_text = render_projection_status(conn)
                report = ProjectionService(campaign, conn).refresh(
                    names=["snapshots"],
                    dirty_only=False,
                    profile="test:memory_effective_health",
                )

        self.assertIn("| `memory` | 1 | `turn:seed` | stale |", status_text)
        self.assertIn("memory", report.global_stale)
        self.assertNotIn("memory", report.global_clean)

    def test_missing_memory_projection_row_stays_dirty_until_rebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    insert into memory_summaries
                    (id, kind, subject_id, title, summary, source_turn_ids_json,
                     freshness_turn_id, freshness_evidence_json, updated_at)
                    values('memory:legacy-missing-state', 'world', null, 'Legacy', 'Legacy',
                           '["turn:seed"]', null, '{}',
                           '2026-07-10T00:00:00+00:00')
                    """
                )
                conn.execute("delete from projection_state where name='memory'")
                conn.commit()

                status_text = render_projection_status(conn)
                before = memory_projection_health(conn)
                report = ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=True,
                    include_outbox=False,
                    profile="test:missing_memory_state",
                )
                after = memory_projection_health(conn)

        self.assertIn("| `memory` | 1 | `turn:seed` | dirty |", status_text)
        self.assertEqual(before["status"], "dirty")
        self.assertIn("memory", report.refreshed)
        self.assertEqual(after["status"], "clean")

    def test_memory_projection_allows_non_conflicting_additive_state_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                first = ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:additive_projection_state:first",
                )
                conn.execute(
                    "alter table projection_state add column diagnostics_json text"
                )
                conn.commit()
                before = memory_projection_health(conn)
                second = ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:additive_projection_state:second",
                )
                after = memory_projection_health(conn)

        self.assertTrue(first.ok, first.to_dict())
        self.assertEqual(before["status"], "clean")
        self.assertTrue(second.ok, second.to_dict())
        self.assertEqual(second.item("memory").status, "clean")
        self.assertEqual(after["status"], "clean")

    def test_memory_projection_rejects_non_identity_unique_state_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                turn_id = current_turn(conn)
                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state (
                      name text primary key,
                      version integer not null default 1,
                      last_turn_id text,
                      status text not null default 'clean',
                      updated_at text not null,
                      last_error text,
                      foreign key(last_turn_id) references turns(id)
                    )
                    """
                )
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean', '2099-07-10T00:00:00+00:00', null)
                    """,
                    (turn_id,),
                )
                conn.execute(
                    "create unique index projection_state_unique_updated_at "
                    "on projection_state(updated_at)"
                )

                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "stale")

    def test_projection_version_infinity_fails_stale_without_diagnostic_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:infinite_version:seed",
                )
                conn.execute(
                    "update projection_state set version=? where name='memory'",
                    (float("inf"),),
                )
                conn.commit()

                health = memory_projection_health(conn)
                status_text = render_projection_status(conn)

        self.assertEqual(health["status"], "stale")
        self.assertIn("| `memory` | inf | `turn:seed` | stale |", status_text)

    def test_projection_version_above_supported_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                ProjectionService(campaign, conn).refresh(
                    names=["memory"],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:future_version:seed",
                )
                conn.execute(
                    "update main.projection_state set version=? where name='memory'",
                    (PROJECTION_VERSIONS["memory"] + 1,),
                )
                conn.commit()

                health = memory_projection_health(conn)
                status_text = render_projection_status(conn)

        self.assertEqual(health["status"], "stale")
        self.assertIn("| `memory` | 2 | `turn:seed` | stale |", status_text)

    def test_temp_projection_tables_cannot_hijack_main_status_or_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                ProjectionService(campaign, conn).refresh(
                    names=[],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:temp_shadow:init",
                )
                main_state = dict(
                    conn.execute(
                        "select * from main.projection_state where name='memory'"
                    ).fetchone()
                )
                conn.executescript(
                    """
                    create temp table projection_state (
                      name text primary key,
                      version integer not null default 1,
                      last_turn_id text,
                      status text not null default 'clean',
                      updated_at text not null,
                      last_error text
                    );
                    insert into temp.projection_state
                    values('memory', 999, null, 'failed', '2099-01-01T00:00:00+00:00', 'temp-secret');
                    create temp table outbox (
                      id text primary key, topic text, payload_json text, status text,
                      attempts integer, created_at text, processed_at text, last_error text
                    );
                    insert into temp.outbox
                    values('temp:item', 'events.jsonl.append', '{}', 'failed', 9,
                           '2099-01-01T00:00:00+00:00', null, 'temp-secret');
                    """
                )
                conn.execute("delete from main.outbox")
                conn.execute(
                    """
                    insert into main.outbox
                    (id, topic, payload_json, status, attempts, created_at)
                    values('main:item', 'events.jsonl.append', ?, 'pending', 0,
                           '2026-07-10T00:00:00+00:00')
                    """,
                    (
                        '{"records":[{"event_id":"event:main-outbox",'
                        '"turn_id":"turn:seed","title":"main queue"}]}',
                    ),
                )
                conn.commit()

                service = ProjectionService(campaign, conn)
                state = service._state_for("memory")
                status_text = render_projection_status(conn)
                conn.execute("drop table temp.projection_state")
                report = service.refresh(
                    names=["events_jsonl"],
                    dirty_only=True,
                    include_outbox=True,
                    profile="test:temp_shadow",
                )
                main_outbox_status = conn.execute(
                    "select status from main.outbox where id='main:item'"
                ).fetchone()["status"]
                temp_outbox_status = conn.execute(
                    "select status from temp.outbox where id='temp:item'"
                ).fetchone()["status"]
                events_text = campaign.events_path.read_text(encoding="utf-8")

        self.assertEqual(state, main_state)
        self.assertNotIn("temp-secret", status_text)
        self.assertNotIn("temp:item", status_text)
        self.assertEqual(report.outbox_status, "clean")
        self.assertEqual(main_outbox_status, "done")
        self.assertEqual(temp_outbox_status, "failed")
        self.assertIn("event:main-outbox", events_text)

    def test_projection_metadata_helpers_preserve_transaction_and_cleanup_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                ProjectionService(campaign, conn).refresh(
                    names=[],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:metadata_transaction:init",
                )
                conn.execute(
                    "update main.projection_state set status='dirty' where name='memory'"
                )
                conn.commit()
                self.assertFalse(conn.in_transaction)

                self.assertTrue(
                    mark_projection_clean(
                        conn,
                        "memory",
                        turn_id=current_turn(conn),
                    )
                )
                self.assertFalse(conn.in_transaction)
                conn.rollback()
                self.assertEqual(projection_status(conn, "memory")[0], "clean")

                conn.execute("delete from main.projection_state where name='reports'")
                conn.commit()
                self.assertFalse(mark_projection_failed(conn, "reports", "missing"))
                conn.rollback()

                before = dict(
                    conn.execute(
                        "select status, updated_at from main.projection_state "
                        "where name='memory'"
                    ).fetchone()
                )
                self.assertFalse(
                    mark_projections_dirty(
                        conn,
                        ["memory", "unknown"],
                        turn_id=current_turn(conn),
                    )
                )
                self.assertFalse(conn.in_transaction)
                after = dict(
                    conn.execute(
                        "select status, updated_at from main.projection_state "
                        "where name='memory'"
                    ).fetchone()
                )

        self.assertEqual(after, before)

    def test_projection_metadata_survives_missing_outbox_and_non_sql_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table main.outbox")
                conn.execute(
                    "update main.projection_state set status='clean' where name='memory'"
                )
                conn.commit()
                before_rows = conn.execute(
                    "select count(*) from main.projection_state"
                ).fetchone()[0]
                self.assertTrue(
                    mark_projections_dirty(
                        conn,
                        [],
                        turn_id=current_turn(conn),
                    )
                )
                after_rows = conn.execute(
                    "select count(*) from main.projection_state"
                ).fetchone()[0]

                with mock.patch(
                    "rpg_engine.projections.next_projection_generation",
                    side_effect=RuntimeError("clock unavailable"),
                ):
                    invalidated = mark_projections_dirty(
                        conn,
                        ["memory"],
                        turn_id=current_turn(conn),
                    )
                state = conn.execute(
                    "select status from main.projection_state where name='memory'"
                ).fetchone()["status"]
                status_text = render_projection_status(conn)
                in_transaction = conn.in_transaction

        self.assertTrue(invalidated)
        self.assertEqual(after_rows, before_rows)
        self.assertEqual(state, "dirty")
        self.assertFalse(in_transaction)
        self.assertIn("| missing | 0 |", status_text)

    def test_multi_projection_clean_reports_partial_failure_and_visits_every_name(self) -> None:
        conn = sqlite3.connect(":memory:")
        with mock.patch(
            "rpg_engine.projections.current_turn_id",
            return_value="turn:seed",
        ), mock.patch(
            "rpg_engine.projections.mark_projection_clean",
            side_effect=[True, False, True],
        ) as clean:
            result = mark_projections_clean(
                conn,
                ["search", "cards", "reports"],
            )

        self.assertFalse(result)
        self.assertEqual(clean.call_count, 3)

    def test_dirty_only_report_reconciles_projection_dirtied_after_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                service = ProjectionService(campaign, conn)

                def sample_then_dirty(statuses: set[str]) -> set[str]:
                    conn.execute(
                        "update main.projection_state set status='dirty', "
                        "updated_at='2099-07-10T00:00:00+00:00' where name='memory'"
                    )
                    conn.commit()
                    return set()

                with mock.patch.object(
                    service,
                    "_names_with_status",
                    side_effect=sample_then_dirty,
                ):
                    report = service.refresh(
                        names=["memory"],
                        dirty_only=True,
                        include_outbox=False,
                        profile="test:dirty_after_sampling",
                    )

        self.assertEqual(report.requested, ("memory",))
        self.assertIn("memory", report.skipped)
        self.assertIn("memory", report.requested_dirty)
        self.assertEqual(report.status, "dirty")

    def test_projection_status_rejects_unknown_alias_status_and_explains_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                ProjectionService(campaign, conn).refresh(
                    names=[],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:strict_projection_identity:init",
                )
                conn.execute(
                    """
                    insert into main.projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('Search', 1, ?, 'clean', '2099-01-01T00:00:00+00:00', null)
                    """,
                    (current_turn(conn),),
                )
                conn.execute(
                    "update main.projection_state set version=2 where name='cards'"
                )
                conn.execute(
                    "update main.projection_state set status='clean-ish' where name='reports'"
                )
                conn.commit()

                report = ProjectionService(campaign, conn).refresh(
                    names=[],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:strict_projection_identity",
                )
                status_text = render_projection_status(conn)

        self.assertIn("Search", report.global_stale)
        self.assertIn("reports", report.global_stale)
        self.assertIn("version 2 != 1", status_text)

    def test_refresh_acquisition_failure_returns_structured_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                service = ProjectionService(campaign, conn)
                with mock.patch.object(
                    service,
                    "_mark_refreshing",
                    side_effect=sqlite3.OperationalError("ownership unavailable"),
                ):
                    report = service.refresh(
                        names=["memory"],
                        dirty_only=False,
                        include_outbox=False,
                        profile="test:acquisition_failure",
                    )

        item = report.item("memory")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.status, "failed")
        self.assertIn("ownership unavailable", item.error or "")

    def test_final_report_reconciles_clean_item_with_new_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                service = ProjectionService(campaign, conn)

                def clean_then_dirty(
                    name: str,
                    *,
                    options: dict[str, object],
                ) -> ProjectionItemReport:
                    conn.execute(
                        "update main.projection_state set status='dirty', "
                        "updated_at='2099-07-10T00:00:00+00:00' where name=?",
                        (name,),
                    )
                    conn.commit()
                    return ProjectionItemReport(name=name, status="clean")

                with mock.patch.object(
                    service,
                    "_refresh_one",
                    side_effect=clean_then_dirty,
                ):
                    report = service.refresh(
                        names=["memory"],
                        dirty_only=False,
                        include_outbox=False,
                        profile="test:final_reconcile",
                    )

        item = report.item("memory")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.status, "dirty")
        self.assertNotIn("memory", report.refreshed)
        self.assertIn("memory", report.requested_dirty)
        self.assertFalse(report.ok)

    def test_projection_publication_lock_serializes_same_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            attempting = threading.Event()
            acquired = threading.Event()

            def contender() -> None:
                attempting.set()
                with projection_service_module._projection_refresh_lock(
                    campaign,
                    "memory",
                ):
                    acquired.set()

            with projection_service_module._projection_refresh_lock(campaign, "memory"):
                worker = threading.Thread(target=contender)
                worker.start()
                self.assertTrue(attempting.wait(1.0))
                self.assertFalse(acquired.wait(0.05))
            worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(acquired.is_set())

    def test_projection_publication_lock_timeout_is_bounded(self) -> None:
        class NeverAcquire:
            def acquire(self, *, timeout: float) -> bool:
                return False

            def release(self) -> None:
                raise AssertionError("unacquired lock must not be released")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            key = f"{campaign.database_path.resolve()}::memory"
            with mock.patch.dict(
                projection_service_module._REFRESH_LOCKS,
                {key: NeverAcquire()},
            ):
                with self.assertRaisesRegex(TimeoutError, "lock timed out"):
                    with projection_service_module._projection_refresh_lock(
                        campaign,
                        "memory",
                    ):
                        self.fail("timeout lock unexpectedly acquired")

    def test_projection_publication_lock_serializes_across_processes(self) -> None:
        if projection_service_module.fcntl is None:
            self.skipTest("cross-process flock is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_initialized_campaign(tmp)
            campaign = load_campaign(campaign_path)
            ready = Path(tmp) / "child-ready"
            release = Path(tmp) / "child-release"
            child_code = """
import sys, time
from pathlib import Path
from rpg_engine.campaign import load_campaign
from rpg_engine.projection_service import _projection_refresh_lock
campaign = load_campaign(Path(sys.argv[1]))
ready = Path(sys.argv[2])
release = Path(sys.argv[3])
with _projection_refresh_lock(campaign, 'memory'):
    ready.write_text('ready', encoding='utf-8')
    while not release.exists():
        time.sleep(0.01)
"""
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(campaign_path),
                    str(ready),
                    str(release),
                ],
                cwd=ENGINE_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            acquired = threading.Event()
            try:
                deadline = time.monotonic() + 5.0
                while not ready.exists() and time.monotonic() < deadline:
                    if child.poll() is not None:
                        break
                    time.sleep(0.01)
                if not ready.exists():
                    stdout, stderr = child.communicate(timeout=1)
                    self.fail(f"child lock holder failed: {stdout}\n{stderr}")

                def contender() -> None:
                    with projection_service_module._projection_refresh_lock(
                        campaign,
                        "memory",
                    ):
                        acquired.set()

                worker = threading.Thread(target=contender)
                worker.start()
                self.assertFalse(acquired.wait(0.1))
                release.write_text("release", encoding="utf-8")
                worker.join(timeout=5.0)
                self.assertFalse(worker.is_alive())
                self.assertTrue(acquired.is_set())
            finally:
                release.touch()
                if child.poll() is None:
                    child.wait(timeout=5.0)

    def test_memory_refresh_loses_generation_to_real_second_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn, connect(campaign) as writer:
                original_write_report = write_memory_report

                def dirty_during_refresh(*args: object, **kwargs: object) -> Path:
                    path = original_write_report(*args, **kwargs)
                    mark_projections_dirty(
                        writer,
                        ["memory"],
                        turn_id=current_turn(writer),
                    )
                    writer.commit()
                    return path

                with mock.patch(
                    "rpg_engine.memory.write_memory_report",
                    side_effect=dirty_during_refresh,
                ):
                    report = ProjectionService(campaign, conn).refresh(
                        names=["memory"],
                        dirty_only=False,
                        include_outbox=False,
                        profile="test:memory_refresh_second_connection",
                    )
                health = memory_projection_health(conn)

        item = report.item("memory")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.status, "dirty")
        self.assertEqual(health["status"], "dirty")

    def test_memory_refresh_does_not_overwrite_new_dirty_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                original_write_report = write_memory_report

                def dirty_during_refresh(*args: object, **kwargs: object) -> Path:
                    path = original_write_report(*args, **kwargs)
                    mark_projections_dirty(conn, ["memory"], turn_id=current_turn(conn))
                    conn.commit()
                    return path

                with mock.patch(
                    "rpg_engine.memory.write_memory_report",
                    side_effect=dirty_during_refresh,
                ):
                    report = ProjectionService(campaign, conn).refresh(
                        names=["memory"],
                        dirty_only=False,
                        include_outbox=False,
                        profile="test:memory_refresh_generation",
                    )
                health = memory_projection_health(conn)

        self.assertEqual(report.item("memory").status, "dirty")
        self.assertEqual(health["status"], "dirty")

    def test_memory_refresh_reconciles_post_refresh_stale_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    update schema_migrations
                    set applied_at='9999-12-31T23:59:59.999999+00:00'
                    where id='0009_memory_summary_provenance'
                    """
                )
                conn.commit()

                with mock.patch("rpg_engine.memory.build_memory_records", return_value=[]):
                    report = ProjectionService(campaign, conn).refresh(
                        names=["memory"],
                        dirty_only=False,
                        include_outbox=False,
                        profile="test:memory_post_refresh_health",
                    )
                health = memory_projection_health(conn)

        item = report.item("memory")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertNotEqual(item.status, "clean")
        self.assertNotIn("memory", report.refreshed)
        self.assertIn("memory projection remains stale", "\n".join(report.errors))
        self.assertNotEqual(health["status"], "clean")

    def test_max_projection_generation_does_not_block_turn_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                maximum = "9999-12-31T23:59:59.999999+00:00"
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean', ?, null)
                    on conflict(name) do update set
                      version=excluded.version,
                      last_turn_id=excluded.last_turn_id,
                      status=excluded.status,
                      updated_at=excluded.updated_at,
                      last_error=null
                    """,
                    (current_turn(conn), maximum),
                )
                conn.commit()

                turn_id = save_turn_delta(
                    campaign,
                    conn,
                    wait_delta(conn, "projection-max-generation"),
                )
                state = conn.execute(
                    "select status, updated_at from projection_state where name='memory'"
                ).fetchone()
                saved = conn.execute(
                    "select 1 from turns where id=?",
                    (turn_id,),
                ).fetchone()

        self.assertIsNotNone(saved)
        self.assertEqual(state["status"], "dirty")
        self.assertNotEqual(state["updated_at"], maximum)

    def test_max_projection_generation_cannot_reuse_stale_owner_token(self) -> None:
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz: object = None) -> datetime:
                return cls.fromisoformat("2026-07-10T00:00:00+00:00")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                stale_token = "2026-07-10T00:00:00+00:00"
                maximum = "9999-12-31T23:59:59.999999+00:00"
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean', ?, null)
                    on conflict(name) do update set status='clean', updated_at=excluded.updated_at
                    """,
                    (current_turn(conn), maximum),
                )
                with (
                    mock.patch("rpg_engine.projections.datetime", FrozenDateTime),
                    mock.patch("rpg_engine.projections.utc_now", return_value=stale_token),
                ):
                    repaired_token = next_projection_generation(conn, "memory")
                conn.execute(
                    "update projection_state set status='clean', updated_at=? where name='memory'",
                    (repaired_token,),
                )

                stale_owner_won = mark_projection_failed_if_unchanged(
                    conn,
                    "memory",
                    error="stale owner",
                    expected_generation=("clean", stale_token),
                )

        self.assertNotEqual(repaired_token, stale_token)
        self.assertFalse(stale_owner_won)

    def test_projection_metadata_trigger_does_not_rollback_turn_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    create trigger projection_metadata_block
                    before update on projection_state
                    begin
                      select raise(abort, 'projection metadata blocked');
                    end
                    """
                )
                conn.commit()

                turn_id = save_turn_delta(
                    campaign,
                    conn,
                    wait_delta(conn, "projection-schema-fails-open-for-facts"),
                )
                saved = conn.execute(
                    "select 1 from turns where id=?",
                    (turn_id,),
                ).fetchone()
                health = memory_projection_health(conn)

        self.assertIsNotNone(saved)
        self.assertEqual(health["status"], "stale")

    def test_failed_refresh_superseded_by_clean_generation_is_not_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                def supersede_then_fail(
                    *args: object,
                    **kwargs: object,
                ) -> tuple[list[str], dict[str, object]]:
                    conn.execute(
                        """
                        update projection_state
                        set status='clean', updated_at='2099-07-10T00:00:00+00:00'
                        where name='snapshots'
                        """
                    )
                    conn.commit()
                    raise RuntimeError("superseded refresh failed")

                with mock.patch.object(
                    ProjectionService,
                    "_write_projection",
                    side_effect=supersede_then_fail,
                ):
                    report = ProjectionService(campaign, conn).refresh(
                        names=["snapshots"],
                        dirty_only=False,
                        include_outbox=False,
                        profile="test:superseded_failure",
                    )

        item = report.item("snapshots")
        self.assertIsNotNone(item)
        assert item is not None
        self.assertNotEqual(item.status, "clean")
        self.assertIsNotNone(item.error)
        self.assertNotIn("snapshots", report.refreshed)

    def test_projection_alias_is_stale_in_machine_readable_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('MEMORY', 1, ?, 'clean', '2099-07-10T00:00:00+00:00', null)
                    """,
                    (current_turn(conn),),
                )
                conn.commit()

                report = ProjectionService(campaign, conn).refresh(
                    names=[],
                    dirty_only=False,
                    include_outbox=False,
                    profile="test:memory_alias_report",
                )

        self.assertNotIn("MEMORY", report.global_clean)
        self.assertIn("MEMORY", report.global_stale)

    def test_projection_status_renders_incompatible_required_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                turn_id = current_turn(conn)
                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state (
                      name text primary key,
                      version integer not null default 1,
                      last_turn_id text,
                      status text not null default 'clean',
                      updated_at text not null,
                      last_error text,
                      tenant text not null,
                      foreign key(last_turn_id) references turns(id)
                    )
                    """
                )
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error, tenant)
                    values('memory', 1, ?, 'clean', '2099-07-10T00:00:00+00:00', null, 'a')
                    """,
                    (turn_id,),
                )

                status_text = render_projection_status(conn)
                conn.commit()
                turn_id = save_turn_delta(
                    campaign,
                    conn,
                    wait_delta(conn, "projection-required-extension-fact-commit"),
                )
                saved = conn.execute(
                    "select 1 from turns where id=?",
                    (turn_id,),
                ).fetchone()

        self.assertIn("schema incompatible", status_text)
        self.assertIn("stale", status_text)
        self.assertIsNotNone(saved)

    def test_projection_state_rejects_required_extension_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state (
                      name text primary key,
                      version integer not null default 1,
                      last_turn_id text,
                      status text not null default 'clean',
                      updated_at text not null,
                      last_error text,
                      tenant text not null
                    )
                    """
                )
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error, tenant)
                    values('memory', 1, 'turn:seed', 'clean',
                           '2099-07-10T00:00:00+00:00', null, 'tenant-a')
                    """
                )

                health = memory_projection_health(conn)

        self.assertEqual(health["status"], "stale")

    def test_projection_state_requires_binary_canonical_memory_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_campaign(tmp))
            with connect(campaign) as conn:
                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state (
                      name text collate nocase primary key,
                      version integer not null default 1,
                      last_turn_id text,
                      status text not null default 'clean',
                      updated_at text not null,
                      last_error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('MEMORY', 1, 'turn:seed', 'clean',
                           '2026-07-10T00:00:00+00:00', null)
                    """
                )
                conn.commit()

                health = memory_projection_health(conn)
                status_text = render_projection_status(conn)

        self.assertEqual(health["status"], "stale")
        self.assertIn("| `MEMORY` | 1 | `turn:seed` | stale |", status_text)

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
