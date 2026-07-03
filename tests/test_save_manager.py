from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rpg_engine.save_manager import SaveManager
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
            self.assertFalse((root / ".aigm" / "pending-clarification.json").exists())

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
