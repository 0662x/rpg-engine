from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rpg_engine.ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER
from rpg_engine.game_session import hash_identity
from rpg_engine.save_manager import DEFAULT_PENDING_ACTION_TTL_SECONDS, SaveManager, SaveManagerError
from rpg_engine.save_service import init_v1_save, inspect_v1_save
from tests.helpers import consensus_candidate, internal_query_review, internal_review, query_candidate


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
OFFICIAL_EXAMPLE = ENGINE_ROOT / "rpg_engine" / "resources" / "examples" / "v1_minimal_adventure"


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def load_json(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def result_object(data: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(to_dict=lambda: dict(data))


def quote_sqlite_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sqlite_application_tables(conn: sqlite3.Connection) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def sqlite_table_schema(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute(
        "SELECT COALESCE(sql, '') FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return str(row[0]) if row else ""


def sqlite_rows(conn: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    quoted = quote_sqlite_identifier(table)
    rows = conn.execute(f"SELECT * FROM {quoted}").fetchall()
    return sorted((tuple(row) for row in rows), key=repr)


def authoritative_save_snapshot(save_path: Path) -> dict[str, object]:
    inspected = inspect_v1_save(save_path)
    conn = sqlite3.connect(save_path / "data" / "game.sqlite")
    try:
        tables = sqlite_application_tables(conn)
        table_rows = {table: sqlite_rows(conn, table) for table in tables}
        table_schema = {table: sqlite_table_schema(conn, table) for table in tables}
    finally:
        conn.close()
    return {
        "current_turn_id": inspected.get("current_turn_id"),
        "current_game_day": inspected.get("current_game_day"),
        "current_time_block": inspected.get("current_time_block"),
        "current_location_id": inspected.get("current_location_id"),
        "schemas": table_schema,
        "tables": table_rows,
    }


class SaveManagerTests(unittest.TestCase):
    def test_start_or_continue_creates_from_starter_then_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            starter_dir = root / "starters" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, starter_dir)

            created = load_json(
                run_cli(
                    "player",
                    "start",
                    root,
                    "--campaign",
                    "campaigns/minimal",
                    "--starter-save",
                    "starters/minimal",
                    "--format",
                    "json",
                )
            )
            continued = load_json(run_cli("player", "start", root, "--format", "json"))

            self.assertTrue(created["ok"], created)
            self.assertEqual(created["mode"], "created")
            self.assertIn("onboarding_text", created)
            self.assertIn("Start", created["onboarding_text"])
            self.assertNotIn("SQLite", created["onboarding_text"])
            self.assertEqual(continued["mode"], "continued")
            self.assertEqual(continued["active_save_id"], created["active_save_id"])

            save_path = root / created["save"]["path"]
            inspected = inspect_v1_save(save_path)
            self.assertTrue(inspected["ok"], inspected)
            self.assertTrue((root / ".aigm" / "save-registry.json").exists())

    def test_multiple_saves_can_be_created_listed_and_switched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)

            first = load_json(
                run_cli("player", "new", root, "--campaign", "campaigns/minimal", "--label", "First", "--format", "json")
            )
            second = load_json(
                run_cli("player", "new", root, "--campaign", "campaigns/minimal", "--label", "Second", "--format", "json")
            )
            listed = load_json(run_cli("player", "saves", root, "--refresh", "--format", "json"))
            switched = load_json(run_cli("player", "switch", root, first["save"]["id"], "--format", "json"))

            self.assertTrue(first["ok"], first)
            self.assertTrue(second["ok"], second)
            self.assertEqual(second["active_save_id"], second["save"]["id"])
            self.assertEqual(len(listed["saves"]), 2)
            self.assertEqual(switched["active_save_id"], first["save"]["id"])
            self.assertEqual(switched["save"]["label"], "First")

    def test_player_act_confirm_hides_internal_delta_and_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)

            started = load_json(
                run_cli("player", "start", root, "--campaign", "campaigns/minimal", "--format", "json")
            )
            acted = load_json(run_cli("player", "act", root, "休息到早上", "--format", "json"))

            self.assertTrue(started["ok"], started)
            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertNotIn("delta_draft", acted)
            self.assertNotIn("turn_proposal", acted)
            self.assertTrue((root / ".aigm" / "pending-player-action.json").exists())
            rejected = run_cli("player", "confirm", root, "--format", "json", check=False)
            confirmed = load_json(
                run_cli("player", "confirm", root, "--session-id", acted["session_id"], "--format", "json")
            )
            current = load_json(run_cli("player", "current", root, "--refresh", "--format", "json"))
            self.assertNotEqual(rejected.returncode, 0)
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertNotIn("delta_draft", confirmed)
            self.assertNotIn("turn_proposal", confirmed)
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())
            self.assertEqual(current["save"]["current_turn_id"], "turn:000001")

    def test_player_act_executes_query_without_pending_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)

            load_json(run_cli("player", "start", root, "--campaign", "campaigns/official", "--format", "json"))
            acted = load_json(run_cli("player", "act", root, "查看周围", "--format", "json"))

            self.assertTrue(acted["ok"], acted)
            self.assertEqual(acted["action"], "query")
            self.assertFalse(acted["ready_to_confirm"], acted)
            self.assertFalse(acted["saved"], acted)
            self.assertIn("当前场景", acted["message"])
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())
            self.assertFalse((root / ".aigm" / "pending-player-clarification.json").exists())

    def test_player_turn_ready_preview_does_not_mutate_authoritative_state_until_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            started = manager.start_or_continue(campaign="campaigns/official")
            save_path = root / started["save"]["path"]
            before_preview = authoritative_save_snapshot(save_path)

            acted = manager.player_turn(user_text="休息到早上")
            after_preview = authoritative_save_snapshot(save_path)
            pending = manager.read_pending_action()
            registry_save = manager.current_save(refresh=False)["save"]

            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertTrue(acted["session_id"], acted)
            self.assertFalse(acted["saved"], acted)
            self.assertNotIn("delta_draft", acted)
            self.assertNotIn("turn_proposal", acted)
            self.assertEqual(after_preview, before_preview)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["session_id"], acted["session_id"])
            self.assertIsNotNone(registry_save.get("last_played_at"))

            confirmed = manager.player_confirm(acted["session_id"])
            after_confirm = authoritative_save_snapshot(save_path)

            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertNotEqual(after_confirm["current_turn_id"], before_preview["current_turn_id"])
            self.assertGreater(
                len(after_confirm["tables"]["turns"]),
                len(before_preview["tables"]["turns"]),
            )
            self.assertGreater(
                len(after_confirm["tables"]["events"]),
                len(before_preview["tables"]["events"]),
            )
            self.assertFalse(manager.pending_action_path().exists())

    def test_player_turn_pending_action_payload_binds_confirmation_identity_and_unaccepted_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            started = manager.start_or_continue(campaign="campaigns/official")

            acted = manager.player_turn(
                user_text="休息到早上",
                platform="qq",
                session_key="room:pending-contract",
                actor_id="actor:one",
            )
            pending = manager.read_pending_action()

            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertIsNotNone(pending)
            required_keys = {
                "schema_version",
                "session_id",
                "save_id",
                "save_path",
                "created_at",
                "expires_at",
                "ttl_seconds",
                "user_text",
                "action",
                "delta",
                "turn_proposal",
                "platform",
                "session_key_hash",
                "actor_id_hash",
            }
            self.assertLessEqual(required_keys, set(pending))
            self.assertEqual(pending["schema_version"], "1")
            self.assertEqual(pending["session_id"], acted["session_id"])
            self.assertEqual(pending["save_id"], started["save"]["id"])
            self.assertEqual(pending["save_path"], started["save"]["path"])
            self.assertEqual(pending["ttl_seconds"], DEFAULT_PENDING_ACTION_TTL_SECONDS)
            self.assertEqual(pending["user_text"], "休息到早上")
            self.assertEqual(pending["action"], "rest")
            self.assertIsInstance(pending["delta"], dict)
            self.assertIsInstance(pending["turn_proposal"], dict)
            self.assertEqual(pending["platform"], "qq")
            self.assertEqual(pending["session_key_hash"], hash_identity("room:pending-contract"))
            self.assertEqual(pending["actor_id_hash"], hash_identity("actor:one"))
            self.assertNotIn("session_key", pending)
            self.assertNotIn("actor_id", pending)
            pending_text = manager.pending_action_path().read_text(encoding="utf-8")
            self.assertNotIn("room:pending-contract", pending_text)
            self.assertNotIn("actor:one", pending_text)
            created_at = datetime.fromisoformat(pending["created_at"])
            expires_at = datetime.fromisoformat(pending["expires_at"])
            self.assertIsNotNone(created_at.utcoffset())
            self.assertIsNotNone(expires_at.utcoffset())
            self.assertAlmostEqual(
                (expires_at - created_at).total_seconds(),
                DEFAULT_PENDING_ACTION_TTL_SECONDS,
                delta=2,
            )

            proposal = pending["turn_proposal"]
            provenance = proposal.get("provenance") if isinstance(proposal.get("provenance"), dict) else {}
            self.assertFalse(bool(proposal.get("human_confirmed", False)))
            self.assertNotEqual(provenance.get("confirmed_via"), "player_confirm")
            with self.assertRaisesRegex(SaveManagerError, "different platform actor"):
                manager.player_confirm(
                    acted["session_id"],
                    platform="qq",
                    session_key="room:pending-contract",
                    actor_id="actor:two",
                )
            self.assertIsNotNone(manager.read_pending_action())
            with self.assertRaisesRegex(SaveManagerError, "different platform session"):
                manager.player_confirm(
                    acted["session_id"],
                    platform="qq",
                    session_key="room:wrong",
                    actor_id="actor:one",
                )
            self.assertIsNotNone(manager.read_pending_action())
            confirmed = manager.player_confirm(
                acted["session_id"],
                platform="qq",
                session_key="room:pending-contract",
                actor_id="actor:one",
            )
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertIsNone(manager.read_pending_action())

    def test_player_turn_non_ready_outcomes_clear_stale_pending_and_cannot_be_confirmed(self) -> None:
        cases = [
            ("query", "查看周围", "ready", "query"),
            ("needs_confirmation", "去 Old Bridge 找 Scout Ren 问情况", "needs_confirmation", "act"),
            ("maintenance_block", "系统维护：修复存档索引", "blocked", "act"),
            ("empty_text", "   ", "clarify", "act"),
            ("blocked_out_of_world", "commit_turn raw delta", "blocked", "act"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            manager.start_or_continue(campaign="campaigns/official")

            for case_id, user_text, expected_status, expected_action in cases:
                with self.subTest(case=case_id):
                    stale = manager.player_turn(user_text="休息到早上")
                    self.assertTrue(stale["ready_to_confirm"], stale)
                    self.assertTrue(manager.pending_action_path().exists())
                    save_path = root / manager.current_save(refresh=False)["save"]["path"]
                    before_non_ready = authoritative_save_snapshot(save_path)

                    result = manager.player_turn(user_text=user_text)
                    after_non_ready = authoritative_save_snapshot(save_path)

                    self.assertEqual(result["status"], expected_status, result)
                    self.assertEqual(result["action"], expected_action, result)
                    self.assertFalse(result["ready_to_confirm"], result)
                    self.assertIsNone(result["session_id"], result)
                    self.assertFalse(result["saved"], result)
                    self.assertNotIn("delta_draft", result)
                    self.assertNotIn("turn_proposal", result)
                    self.assertEqual(after_non_ready, before_non_ready)
                    self.assertFalse(manager.pending_action_path().exists())
                    if manager.pending_clarification_path().exists():
                        self.assertIsNotNone(manager.read_pending_clarification())
                    with self.assertRaises(SaveManagerError):
                        manager.player_confirm(stale["session_id"])
                    manager.clear_pending_clarification()

    def test_player_turn_unsupported_capability_clears_stale_pending_without_mutating_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/minimal")
            started = manager.start_or_continue(campaign="campaigns/minimal")
            save_path = root / started["save"]["path"]

            stale = manager.player_turn(user_text="休息到早上")
            self.assertTrue(stale["ready_to_confirm"], stale)
            self.assertTrue(manager.pending_action_path().exists())
            before_blocked = authoritative_save_snapshot(save_path)

            result = manager.player_turn(user_text="掷骰 1d6")
            after_blocked = authoritative_save_snapshot(save_path)

            self.assertFalse(result["ok"], result)
            self.assertEqual(result["status"], "blocked", result)
            self.assertEqual(result["action"], "random_table", result)
            self.assertFalse(result["ready_to_confirm"], result)
            self.assertIsNone(result["session_id"], result)
            self.assertFalse(result["saved"], result)
            self.assertIn("unsupported capability", " ".join(result.get("errors", [])))
            self.assertEqual(after_blocked, before_blocked)
            self.assertFalse(manager.pending_action_path().exists())
            with self.assertRaises(SaveManagerError):
                manager.player_confirm(stale["session_id"])

    def test_player_turn_pending_clarification_clears_stale_pending_without_mutating_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            started = manager.start_or_continue(campaign="campaigns/official")
            save_path = root / started["save"]["path"]

            stale = manager.player_turn(user_text="休息到早上")
            self.assertTrue(stale["ready_to_confirm"], stale)
            self.assertTrue(manager.pending_action_path().exists())
            before_clarification = authoritative_save_snapshot(save_path)
            clarification_runtime = SimpleNamespace(
                act=lambda *_args, **_kwargs: result_object(
                    {
                        "ok": False,
                        "status": "needs_clarification",
                        "action": "act",
                        "interpretation": {"intent": {"clarification": {"question": "which target?"}}},
                        "repair_options": [],
                    }
                )
            )

            with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime):
                result = manager.player_turn(user_text="使用它")
            after_clarification = authoritative_save_snapshot(save_path)
            pending_clarification_path = root / ".aigm" / "pending-player-clarification.json"
            legacy_clarification_path = root / ".aigm" / "pending-clarification.json"
            pending_clarification = manager.read_pending_clarification()

            self.assertFalse(result["ready_to_confirm"], result)
            self.assertIsNone(result["session_id"], result)
            self.assertFalse(result["saved"], result)
            self.assertEqual(after_clarification, before_clarification)
            self.assertFalse(manager.pending_action_path().exists())
            self.assertEqual(manager.pending_clarification_path(), pending_clarification_path.resolve())
            self.assertTrue(pending_clarification_path.exists())
            self.assertFalse(legacy_clarification_path.exists())
            self.assertIsNotNone(pending_clarification)
            self.assertEqual(pending_clarification["save_id"], started["save"]["id"])
            self.assertEqual(pending_clarification["original_user_text"], "使用它")
            with self.assertRaises(SaveManagerError):
                manager.player_confirm(stale["session_id"])

    def test_player_turn_surface_keeps_route_preparation_cases_unsaved(self) -> None:
        cases = [
            ("query_scene", "查看周围", True, "ready", "query", False),
            ("single_action", "休息到早上", True, "ready", "rest", True),
            ("maintenance_block", "系统维护：修复存档索引", False, "blocked", "act", False),
            ("composite_plan_boundary", "去 Old Bridge 找 Scout Ren 问情况", False, "needs_confirmation", "act", False),
            ("query_entity", "查看 Broken Seal Mark 信息", True, "ready", "query", False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            manager.start_or_continue(campaign="campaigns/official")

            for case_id, user_text, expected_ok, expected_status, expected_action, expected_ready in cases:
                with self.subTest(case=case_id):
                    result = manager.player_turn(user_text=user_text)

                    self.assertEqual(result["ok"], expected_ok, result)
                    self.assertEqual(result["status"], expected_status, result)
                    self.assertEqual(result["action"], expected_action, result)
                    self.assertEqual(result["ready_to_confirm"], expected_ready, result)
                    self.assertFalse(result["saved"], result)
                    self.assertNotIn("delta_draft", result)
                    self.assertNotIn("turn_proposal", result)
                    if expected_ready:
                        self.assertTrue(result["session_id"], result)
                        self.assertTrue((root / ".aigm" / "pending-player-action.json").exists())
                        self.assertIn("确认后", result["message"])
                    else:
                        self.assertFalse(result["session_id"], result)
                        self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())
                    self.assertFalse((root / ".aigm" / "pending-player-clarification.json").exists())

    def test_player_act_confirm_supports_random_dice_without_exposing_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)

            load_json(run_cli("player", "start", root, "--campaign", "campaigns/official", "--format", "json"))
            acted = load_json(run_cli("player", "act", root, "掷骰 1d6 判断桥上风险", "--format", "json"))
            confirmed = load_json(
                run_cli("player", "confirm", root, "--session-id", acted["session_id"], "--format", "json")
            )
            current = load_json(run_cli("player", "current", root, "--refresh", "--format", "json"))

            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertEqual(acted["action"], "random_table")
            self.assertNotIn("delta_draft", acted)
            self.assertNotIn("turn_proposal", acted)
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertEqual(current["save"]["current_turn_id"], "turn:000001")

    def test_player_turn_cli_accepts_external_candidate_and_hides_internal_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            external = consensus_candidate("rest", {"until": "morning"}, reason="external AI selected rest")
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
                internal_review("rest", {"until": "morning"}, reason="internal AI selected rest"),
                ensure_ascii=False,
            )
            try:
                started = load_json(run_cli("player", "start", root, "--campaign", "campaigns/official", "--format", "json"))
                acted = load_json(
                    run_cli(
                        "player",
                        "turn",
                        root,
                        "休息到早上",
                        "--intent-ai",
                        "consensus",
                        "--intent-backend",
                        "direct",
                        "--external-intent-candidate",
                        json.dumps(external, ensure_ascii=False),
                        "--format",
                        "json",
                    )
                )
                confirmed = load_json(
                    run_cli("player", "confirm", root, "--session-id", acted["session_id"], "--format", "json")
                )
                legacy = run_cli(
                    "player",
                    "act",
                    root,
                    "休息到早上",
                    "--external-intent-candidate",
                    json.dumps(external, ensure_ascii=False),
                    "--format",
                    "json",
                    check=False,
                )
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            self.assertTrue(started["ok"], started)
            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertEqual(acted["action"], "rest")
            self.assertNotIn("delta_draft", acted)
            self.assertNotIn("turn_proposal", acted)
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertNotEqual(legacy.returncode, 0)
            self.assertIn("unrecognized arguments: --external-intent-candidate", legacy.stderr)

    def test_player_turn_empty_text_keeps_clarification_before_intent_config_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            manager.start_or_continue(campaign="campaigns/official")

            result = manager.player_turn(user_text="   ", intent_backend="not-a-backend")

            self.assertFalse(result["ok"], result)
            self.assertEqual(result["status"], "clarify")
            self.assertFalse(result["ready_to_confirm"], result)
            self.assertFalse(result["saved"], result)
            self.assertEqual(result["errors"], [])
            self.assertNotIn("delta_draft", result)
            self.assertNotIn("turn_proposal", result)
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())

    def test_player_turn_bundles_intent_inputs_without_exposing_internal_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            manager.start_or_continue(campaign="campaigns/official")
            external = consensus_candidate("rest", {"until": "morning"}, reason="external AI selected rest")
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
                internal_review("rest", {"until": "morning"}, reason="internal AI selected rest"),
                ensure_ascii=False,
            )
            try:
                result = manager.player_turn(
                    user_text="休息到早上",
                    external_intent_candidate=external,
                    intent_ai="CONSENSUS",
                    intent_backend="direct",
                    intent_provider="",
                    intent_model="",
                    intent_timeout=1,
                    intent_base_url="https://ai.example.test/v1",
                    intent_api_key_env="AIGM_TEST_KEY",
                    intent_fallback_backend="off",
                    message_id="msg:save-manager-bundle",
                    platform="qq",
                    session_key="room:save-manager-bundle",
                    preflight_pending_wait_ms=-5,
                )
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            self.assertTrue(result["ok"], result)
            self.assertTrue(result["ready_to_confirm"], result)
            self.assertEqual(result["action"], "rest")
            self.assertNotIn("delta_draft", result)
            self.assertNotIn("turn_proposal", result)
            pending = json.loads((root / ".aigm" / "pending-player-action.json").read_text(encoding="utf-8"))
            trace = pending["turn_proposal"]["intent"]["decision_trace"]["intent_ai"]
            self.assertEqual(trace["mode"], "consensus")
            self.assertEqual(trace["backend"], "direct")
            self.assertEqual(trace["provider"], DEFAULT_AI_PROVIDER)
            self.assertEqual(trace["model"], DEFAULT_AI_MODEL)
            self.assertEqual(trace["timeout"], 3)
            self.assertEqual(trace["base_url"], "https://ai.example.test/v1")
            self.assertEqual(trace["api_key_env"], "AIGM_TEST_KEY")
            self.assertEqual(trace["fallback_backend"], "off")

    def test_player_turn_standard_entry_covers_all_manifest_actions(self) -> None:
        cases = [
            ("rest", "休息到早上", {"until": "morning"}, "ready", "rest", True),
            ("travel", "去 Old Bridge", {"destination": "Old Bridge"}, "ready", "travel", True),
            (
                "social",
                "问 Mira 关于 Old Bridge",
                {"npc": "Mira", "topic": "Old Bridge", "approach": "direct"},
                "ready",
                "social",
                True,
            ),
            ("gather", "采集 Moon Herb", {"target": "Moon Herb"}, "needs_confirmation", "gather", False),
            (
                "explore",
                "调查 Broken Seal Mark",
                {"target": "Broken Seal Mark", "approach": "careful"},
                "ready",
                "explore",
                True,
            ),
            (
                "craft",
                "修理 Repair Signal Frame",
                {"target": "Repair Signal Frame", "materials": ["Moon Herb"]},
                "needs_confirmation",
                "craft",
                False,
            ),
            ("routine", "盘点营地库存", {"task": "盘点营地库存"}, "ready", "routine", True),
            ("random_table", "掷 table:bridge-risk", {"table": "table:bridge-risk"}, "ready", "random_table", True),
            (
                "combat",
                "攻击桥边威胁",
                {"target": "bridge threat", "weapon": "Signal Flare", "ammo": "Field Rations", "distance": "near"},
                "needs_confirmation",
                "act",
                False,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            manager.start_or_continue(campaign="campaigns/official")

            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            try:
                for action, user_text, slots, expected_status, expected_action, expected_ready in cases:
                    with self.subTest(action=action):
                        external = consensus_candidate(action, slots, reason=f"external AI selected {action}")
                        os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
                            internal_review(action, slots, reason=f"internal AI selected {action}"),
                            ensure_ascii=False,
                        )

                        result = manager.player_turn(
                            user_text=user_text,
                            external_intent_candidate=external,
                            intent_ai="consensus",
                            intent_backend="direct",
                        )

                        self.assertEqual(result["status"], expected_status, result)
                        self.assertEqual(result["action"], expected_action, result)
                        self.assertEqual(result["ready_to_confirm"], expected_ready, result)
                        self.assertFalse(result["saved"], result)
                        self.assertNotIn("delta_draft", result)
                        self.assertNotIn("turn_proposal", result)
                        if expected_ready:
                            self.assertTrue(result["ok"], result)
                            self.assertTrue(result["session_id"], result)
                            self.assertIn("确认后", result["message"])
                        else:
                            self.assertFalse(result["session_id"], result)
                            self.assertTrue(result["message"], result)
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

    def test_player_turn_standard_entry_covers_all_manifest_queries(self) -> None:
        cases = [
            ("scene", "查看周围", "查看周围", "当前场景"),
            ("entity", "查看 Warden Mira", "Warden Mira", "Warden Mira"),
            ("context", "查看 Old Bridge 上下文", "Old Bridge", "Context Packet"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "official"
            shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
            manager = SaveManager(root, default_campaign="campaigns/official")
            manager.start_or_continue(campaign="campaigns/official")

            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            try:
                for kind, user_text, query_text, expected_text in cases:
                    with self.subTest(query=kind):
                        external = query_candidate(kind, query_text)
                        os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
                            internal_query_review(kind, query_text),
                            ensure_ascii=False,
                        )

                        result = manager.player_turn(
                            user_text=user_text,
                            external_intent_candidate=external,
                            intent_ai="consensus",
                            intent_backend="direct",
                        )

                        self.assertTrue(result["ok"], result)
                        self.assertEqual(result["status"], "ready", result)
                        self.assertEqual(result["action"], "query", result)
                        self.assertFalse(result["ready_to_confirm"], result)
                        self.assertFalse(result["saved"], result)
                        self.assertIn(expected_text, result["message"])
                        self.assertNotIn("delta_draft", result)
                        self.assertNotIn("turn_proposal", result)
                        self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

    def test_manager_rejects_escaping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = SaveManager(tmp)

            with self.assertRaises(ValueError):
                manager.create_save(campaign="../outside")

if __name__ == "__main__":
    unittest.main()
