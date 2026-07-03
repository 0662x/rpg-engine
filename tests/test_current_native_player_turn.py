from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from rpg_engine.intent_manifest import build_intent_manifest
from rpg_engine.save_manager import SaveManager
from tests.helpers import (
    CURRENT_CAMPAIGN_ROOT,
    CURRENT_NATIVE_REQUIRED,
    FormalCurrentSaveReadOnlyTestCase,
    consensus_candidate,
    copy_current_packages,
    current_turn,
    internal_query_review,
    internal_review,
    query_candidate,
    run_cli,
)


def prepare_current_player_manager(tmp_root: str | Path) -> tuple[SaveManager, Path]:
    root = Path(tmp_root)
    save = copy_current_packages(root)
    run_cli("migrate", "apply", save)

    manager = SaveManager(root)
    campaign_path = CURRENT_CAMPAIGN_ROOT.name
    manager.register_campaign(campaign_path)
    record = manager.build_save_record(
        save_id="current-native-copy",
        campaign_path=campaign_path,
        save_path=save.name,
        label="current native copy",
        kind="test",
        source="copy_current_packages",
    )
    registry = manager.read_registry()
    registry["active_save_id"] = record["id"]
    registry["saves"] = [record]
    manager.write_registry(registry)
    return manager, save


@CURRENT_NATIVE_REQUIRED
class CurrentNativePlayerTurnTests(FormalCurrentSaveReadOnlyTestCase):
    def test_player_turn_standard_entry_covers_current_native_actions(self) -> None:
        cases = [
            ("travel", "去地下菌丝城", {"destination": "地下菌丝城", "pace": "careful"}, "ready", "travel", True, "确认后"),
            ("rest", "在六边形菌丝复合屋休息到清晨", {"until": "morning"}, "ready", "rest", True, "确认后"),
            (
                "explore",
                "谨慎查看空地边缘的旧痕迹",
                {"target": "空地/家", "approach": "谨慎巡查"},
                "ready",
                "explore",
                True,
                "确认后",
            ),
            (
                "social",
                "询问夏娃基地状态和物资交换安排",
                {"npc": "夏娃", "topic": "基地状态和物资交换安排", "approach": "低压询问"},
                "needs_confirmation",
                "social",
                False,
                "不在你当前地点",
            ),
            (
                "gather",
                "在六边形菌丝复合屋收集盐",
                {"target": "item:salt", "location": "loc:home-mycelium-house"},
                "needs_confirmation",
                "gather",
                False,
                "产出数量",
            ),
            (
                "combat",
                "用终极复合弩和麻痹棘刺弩矢保持中距压制大型猫科",
                {
                    "target": "threat:t2-large-cat",
                    "weapon": "item:ultimate-compound-crossbow",
                    "ammo": "item:stun-thorn-bolts",
                    "distance": "中距",
                },
                "needs_confirmation",
                "combat",
                False,
                "武器是否已上弦",
            ),
            ("routine", "盘点盐和调料库存", {"task": "盘点盐和调料库存"}, "ready", "routine", True, "确认后"),
            (
                "craft",
                "用盐和现有材料试做保存食品",
                {"target": "保存食品", "materials": ["盐"], "time_cost": "半小时"},
                "needs_confirmation",
                "craft",
                False,
                "配方",
            ),
            (
                "random_table",
                "掷骰 1d6 判断菌丝城路上风险",
                {"dice": "1d6", "reason": "判断菌丝城路上风险"},
                "ready",
                "random_table",
                True,
                "随机结果",
            ),
        ]
        manifest_actions = {str(item["name"]) for item in build_intent_manifest()["actions"]}
        self.assertEqual({case[0] for case in cases}, manifest_actions)

        with tempfile.TemporaryDirectory() as tmp:
            manager, save = prepare_current_player_manager(tmp)
            before_turn = current_turn(save)
            pending_action = Path(tmp) / ".aigm" / "pending-player-action.json"
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            try:
                for action, user_text, slots, expected_status, expected_action, expected_ready, expected_message in cases:
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
                        self.assertIn(expected_message, result["message"])
                        self.assertEqual(current_turn(save), before_turn)
                        self.assertNotIn("delta_draft", result)
                        self.assertNotIn("turn_proposal", result)
                        if expected_ready:
                            self.assertTrue(result["ok"], result)
                            self.assertTrue(result["session_id"], result)
                            self.assertTrue(pending_action.exists())
                        else:
                            self.assertFalse(result["session_id"], result)
                            self.assertFalse(pending_action.exists())
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

    def test_player_turn_queries_use_the_same_current_native_query_output(self) -> None:
        cases = [
            ("scene", "查看当前场景", "查看当前场景", "## 当前场景：六边形菌丝复合屋"),
            ("entity", "查看终极复合弩", "终极复合弩", "item:ultimate-compound-crossbow"),
            ("context", "查看地下菌丝城上下文", "地下菌丝城", "# Context Packet"),
        ]
        manifest_queries = {str(item["kind"]) for item in build_intent_manifest()["queries"]}
        self.assertEqual({case[0] for case in cases}, manifest_queries)

        with tempfile.TemporaryDirectory() as tmp:
            manager, save = prepare_current_player_manager(tmp)
            before_turn = current_turn(save)
            pending_action = Path(tmp) / ".aigm" / "pending-player-action.json"
            pending_clarification = Path(tmp) / ".aigm" / "pending-player-clarification.json"
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
                        direct = manager.player_query(
                            kind=kind,
                            query_text=None if kind == "scene" else query_text,
                        )

                        self.assertTrue(result["ok"], result)
                        self.assertEqual(result["status"], "ready", result)
                        self.assertEqual(result["action"], "query", result)
                        self.assertFalse(result["ready_to_confirm"], result)
                        self.assertFalse(result["saved"], result)
                        self.assertIn(expected_text, result["message"])
                        self.assertEqual(str(result["message"]).rstrip(), str(direct["text"]).rstrip())
                        self.assertEqual(current_turn(save), before_turn)
                        self.assertNotIn("delta_draft", result)
                        self.assertNotIn("turn_proposal", result)
                        self.assertFalse(pending_action.exists())
                        self.assertFalse(pending_clarification.exists())
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake


if __name__ == "__main__":
    import unittest

    unittest.main()
