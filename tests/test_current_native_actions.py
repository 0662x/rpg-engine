from __future__ import annotations

import tempfile

from rpg_engine.runtime import GMRuntime

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
    current_turn,
    normalize_current_native_story_fixture,
)


@CURRENT_NATIVE_REQUIRED
class CurrentNativeActionTests(FormalCurrentSaveReadOnlyTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.save = normalize_current_native_story_fixture(copy_current_packages(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_low_level_previews_enforce_delta_guards_and_confirmation_boundaries(self) -> None:
        runtime = GMRuntime.from_path(self.save)
        turn = current_turn(self.save)
        ready_cases = [
            (
                "travel",
                {
                    "destination": "地下菌丝城",
                    "pace": "careful",
                    "user_text": "去地下菌丝城",
                },
            ),
            (
                "rest",
                {
                    "until": "morning",
                    "user_text": "在六边形菌丝复合屋休息到清晨",
                },
            ),
            (
                "explore",
                {
                    "target": "空地/家",
                    "approach": "谨慎巡查",
                    "user_text": "谨慎查看空地边缘的旧痕迹",
                },
            ),
        ]
        for action, options in ready_cases:
            with self.subTest(action=action):
                preview = runtime.preview_action(action, options)
                self.assertTrue(preview.ok, preview.errors)
                self.assertEqual(preview.status, "ready")
                self.assertTrue(preview.ready_to_save)
                self.assertIsInstance(preview.delta_draft, dict)
                self.assertEqual(preview.delta_draft["expected_turn_id"], turn)
                self.assertTrue(str(preview.delta_draft["command_id"]).startswith(f"preview-{action}:"))
                validation = runtime.validate_delta(preview.delta_draft, action=action, action_options=options)
                self.assertTrue(validation.ok, validation.errors)

        blocked_cases = [
            (
                "social",
                {
                    "npc": "夏娃",
                    "topic": "基地状态和交易安排",
                    "approach": "低压询问",
                    "user_text": "询问夏娃基地状态和物资交换安排",
                },
                "对象不在当前地点",
            ),
            (
                "gather",
                {
                    "target": "盐",
                    "location": "六边形菌丝复合屋",
                    "user_text": "盘点盐和调料库存",
                },
                "实际产出数量",
            ),
            (
                "combat",
                {
                    "target": "threat:t2-large-cat",
                    "weapon": "item:ultimate-compound-crossbow",
                    "ammo": "item:stun-thorn-bolts",
                    "distance": "中距",
                    "ready_state": "已上弦并确认射界",
                    "user_text": "用终极复合弩保持距离压制大型猫科威胁",
                },
                "目标不在当前地点",
            ),
        ]
        for action, options, expected_error in blocked_cases:
            with self.subTest(action=action):
                preview = runtime.preview_action(action, options)
                self.assertFalse(preview.ok)
                self.assertEqual(preview.status, "needs_confirmation")
                self.assertFalse(preview.ready_to_save)
                self.assertIn(expected_error, "\n".join([*preview.errors, *preview.missing_required]))

    def test_travel_preview_delta_contract_uses_known_route_and_destination(self) -> None:
        runtime = GMRuntime.from_path(self.save)
        options = {"destination": "地下菌丝城", "pace": "careful", "user_text": "去地下菌丝城"}

        preview = runtime.preview_action("travel", options)
        delta = preview.delta_draft or {}
        event_payload = delta["events"][0]["payload"]

        self.assertTrue(preview.ready_to_save, preview.errors)
        self.assertEqual(delta["location_before"], "loc:home-mycelium-house")
        self.assertEqual(delta["location_after"], "loc:home-mycelium-city")
        self.assertEqual(event_payload["route_id"], "route:home-mycelium-house--home-mycelium-city")
        self.assertEqual(delta["meta"]["current_location_id"], "loc:home-mycelium-city")
        self.assertEqual(delta["tick_clocks"][0]["id"], "clock:lake-settlement-suspicion")

    def test_rest_preview_delta_contract_advances_day_and_ticks_drought(self) -> None:
        runtime = GMRuntime.from_path(self.save)
        options = {"until": "morning", "user_text": "在六边形菌丝复合屋休息到清晨"}

        preview = runtime.preview_action("rest", options)
        delta = preview.delta_draft or {}

        self.assertTrue(preview.ready_to_save, preview.errors)
        self.assertEqual(delta["game_time_before"], "第28天 · 上午")
        self.assertEqual(delta["game_time_after"], "第29天 · 清晨")
        self.assertEqual(delta["location_before"], "loc:home-mycelium-house")
        self.assertEqual(delta["location_after"], "loc:home-mycelium-house")
        self.assertEqual(delta["meta"]["current_game_day"], "29")
        self.assertIn("clock:drought-spring", {item["id"] for item in delta["tick_clocks"]})
        drought_tick = next(item for item in delta["tick_clocks"] if item["id"] == "clock:drought-spring")
        self.assertEqual(drought_tick["delta"], 1)
        self.assertTrue(drought_tick["reason"].strip())

    def test_explore_preview_delta_does_not_silently_confirm_hidden_facts(self) -> None:
        runtime = GMRuntime.from_path(self.save)
        options = {"target": "空地/家", "approach": "谨慎巡查", "user_text": "谨慎查看空地边缘的旧痕迹"}

        preview = runtime.preview_action("explore", options)
        delta = preview.delta_draft or {}

        self.assertTrue(preview.ready_to_save, preview.errors)
        self.assertEqual(delta["events"][0]["payload"]["target_id"], "loc:home-clearing")
        self.assertTrue(delta["events"][0]["payload"]["needs_gm_resolution"])
        self.assertEqual(delta["upsert_entities"], [])

    def test_blocked_previews_do_not_expose_delta_or_turn_proposal(self) -> None:
        runtime = GMRuntime.from_path(self.save)
        cases = [
            ("gather", {"target": "盐", "location": "六边形菌丝复合屋", "user_text": "盘点盐和调料库存"}),
            (
                "combat",
                {
                    "target": "threat:t2-large-cat",
                    "weapon": "item:ultimate-compound-crossbow",
                    "ammo": "item:stun-thorn-bolts",
                    "distance": "中距",
                    "ready_state": "已上弦并确认射界",
                    "user_text": "用终极复合弩保持距离压制大型猫科威胁",
                },
            ),
        ]
        for action, options in cases:
            with self.subTest(action=action):
                data = runtime.preview_action(action, options).to_dict()
                self.assertFalse(data["ready_to_save"])
                self.assertIsNone(data["delta_draft"])
                self.assertIsNone(data["turn_proposal"])

    def test_validate_delta_rejects_missing_guards_for_current_save(self) -> None:
        runtime = GMRuntime.from_path(self.save)

        validation = runtime.validate_delta(
            {
                "user_text": "记录春末干旱压力。",
                "intent": "clock",
                "changed": True,
                "summary": "缺少 guard 的 delta。",
                "events": [],
            }
        )

        self.assertFalse(validation.ok)
        self.assertIn("player_turn_commit requires expected_turn_id, command_id", "\n".join(validation.errors))


if __name__ == "__main__":
    import unittest

    unittest.main()
