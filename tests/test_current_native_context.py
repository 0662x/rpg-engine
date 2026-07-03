from __future__ import annotations

import tempfile
from typing import Any

from rpg_engine.campaign import load_campaign
from rpg_engine.context_builder import build_context
from rpg_engine.db import connect
from rpg_engine.runtime import GMRuntime

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    CURRENT_SAVE_ROOT as SAVE_ROOT,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
    current_turn,
    event_log_text,
    load_stdout_json,
    loaded_ids,
    query_int,
    run_cli,
)


@CURRENT_NATIVE_REQUIRED
class CurrentNativeContextTests(FormalCurrentSaveReadOnlyTestCase):
    def test_formal_save_read_only_surfaces_do_not_mutate(self) -> None:
        db_path = SAVE_ROOT / "data" / "game.sqlite"
        before_turn = current_turn(SAVE_ROOT)
        before_events = event_log_text(SAVE_ROOT)
        before_context_runs = query_int(db_path, "select count(*) from context_runs")

        self.assertEqual(run_cli("check", SAVE_ROOT).stdout.strip(), "OK")

        runtime = GMRuntime.from_path(SAVE_ROOT)
        scene = runtime.query("scene")
        crossbow = runtime.query("entity", "终极复合弩")
        social_context = runtime.start_turn("询问夏娃基地状态和物资交换安排", mode="auto")

        self.assertIn("六边形菌丝复合屋", scene.text)
        self.assertIn("item:ultimate-compound-crossbow", crossbow.text)
        self.assertEqual(social_context.mode, "action")
        self.assertEqual(social_context.submode, "social")
        self.assertTrue(social_context.must_save)
        self.assertTrue(social_context.requires_preview)
        self.assertIn("char:eve-mycelium-core", loaded_ids(social_context.context))

        self.assertEqual(current_turn(SAVE_ROOT), before_turn)
        self.assertEqual(event_log_text(SAVE_ROOT), before_events)
        self.assertEqual(query_int(db_path, "select count(*) from context_runs"), before_context_runs)

    def test_context_audit_records_loaded_and_omitted_items_on_temp_save_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            db_path = save / "data" / "game.sqlite"
            before_runs = query_int(db_path, "select count(*) from context_runs")
            before_turn = current_turn(save)

            packet = load_stdout_json(
                run_cli(
                    "context",
                    "build",
                    save,
                    "--user-text",
                    "检查终极复合弩",
                    "--mode",
                    "auto",
                    "--budget",
                    "1200",
                    "--format",
                    "json",
                    "--audit-context",
                    "--context-run-id",
                    "context:current-native-audit",
                )
            )

            self.assertEqual(packet["request"]["context_audit_run_id"], "context:current-native-audit")
            self.assertEqual(current_turn(save), before_turn)
            self.assertEqual(query_int(db_path, "select count(*) from context_runs"), before_runs + 1)
            self.assertEqual(
                query_int(db_path, "select count(*) from context_runs where id='context:current-native-audit'"),
                1,
            )
            self.assertGreater(
                query_int(
                    db_path,
                    "select count(*) from context_items where context_run_id='context:current-native-audit' and included=1",
                ),
                0,
            )
            self.assertGreater(
                query_int(
                    db_path,
                    "select count(*) from context_items where context_run_id='context:current-native-audit' and included=0",
                ),
                0,
            )

    def test_current_entity_query_matrix_covers_inventory_people_threats_and_clocks(self) -> None:
        runtime = GMRuntime.from_path(SAVE_ROOT)
        cases = [
            ("终极复合弩", "item:ultimate-compound-crossbow"),
            ("盐", "item:salt"),
            ("竹编鱼笼", "item:fishing-trap"),
            ("夏娃", "char:eve-mycelium-core"),
            ("大型猫科", "threat:t2-large-cat"),
            ("春末干旱", "clock:drought-spring"),
        ]
        for query, expected_id in cases:
            with self.subTest(query=query):
                result = runtime.query("entity", query)
                self.assertIn(expected_id, result.text)

    def test_missing_entity_query_is_helpful_and_read_only(self) -> None:
        runtime = GMRuntime.from_path(SAVE_ROOT)
        before_turn = current_turn(SAVE_ROOT)

        result = runtime.query("entity", "不存在的月亮钥匙")

        self.assertIn("未找到实体", result.text)
        self.assertIn("可尝试", result.text)
        self.assertEqual(current_turn(SAVE_ROOT), before_turn)

    def test_query_context_for_direct_entity_keeps_direct_hit_under_low_budget(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        with connect(campaign) as conn:
            packet = build_context(campaign, conn, user_text="终极复合弩", mode="auto", budget=900)

        self.assertEqual(packet.request["mode"], "query")
        self.assertEqual(packet.request["submode"], "entity")
        self.assertIn("item:ultimate-compound-crossbow", loaded_ids(packet))
        self.assertIn("relevant_entities", packet.sections)
        self.assertNotIn("palette_candidates", packet.sections)

    def test_repeat_context_builds_are_stable_for_current_key_query(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        fingerprints: set[tuple[Any, ...]] = set()
        with connect(campaign) as conn:
            for _ in range(3):
                packet = build_context(campaign, conn, user_text="终极复合弩", mode="auto", budget=1800)
                fingerprints.add(
                    (
                        packet.request["mode"],
                        packet.request["submode"],
                        tuple(item.get("id") for item in packet.loaded_items[:12]),
                        tuple(packet.sections.keys()),
                    )
                )

        self.assertEqual(len(fingerprints), 1)

    def test_start_turn_routing_matrix_for_current_story_language(self) -> None:
        runtime = GMRuntime.from_path(SAVE_ROOT)
        cases = [
            ("查看当前场景", "query", "scene", False),
            ("检查终极复合弩", "action", "explore", True),
            ("去地下菌丝城", "action", "travel", True),
            ("询问夏娃基地状态和物资交换安排", "action", "social", True),
            ("在六边形菌丝复合屋休息到清晨", "action", "rest", True),
            ("盘点盐和调料库存", "action", "routine", True),
        ]
        for text, mode, submode, must_save in cases:
            with self.subTest(text=text):
                result = runtime.start_turn(text, mode="auto")
                self.assertEqual(result.mode, mode)
                self.assertEqual(result.submode, submode)
                self.assertEqual(result.must_save, must_save)
                self.assertEqual(result.requires_preview, must_save)
                self.assertTrue(result.can_proceed)

    def test_context_recall_matrix_loads_story_critical_ids_under_budget(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        cases = [
            (
                "检查终极复合弩",
                "action",
                "explore",
                {"item:ultimate-compound-crossbow", "item:stun-thorn-bolts"},
            ),
            (
                "去地下菌丝城",
                "action",
                "travel",
                {"loc:home-mycelium-city", "route:home-mycelium-house--home-mycelium-city"},
            ),
            (
                "询问夏娃基地状态和物资交换安排",
                "action",
                "social",
                {"char:eve-mycelium-core", "world:economy-trade"},
            ),
            (
                "天气会影响农田浇水吗",
                "action",
                "routine",
                {"project:water-crops", "world:weather", "clock:drought-spring"},
            ),
        ]
        with connect(campaign) as conn:
            for text, mode, submode, expected_ids in cases:
                with self.subTest(text=text):
                    packet = build_context(campaign, conn, user_text=text, mode="auto", budget=2600)
                    self.assertEqual(packet.request["mode"], mode)
                    self.assertEqual(packet.request["submode"], submode)
                    self.assertTrue(packet.completeness["allow_proceed"])
                    self.assertLessEqual(packet.budget["limit"], 2600)
                    self.assertTrue(expected_ids.issubset(loaded_ids(packet)), loaded_ids(packet))


if __name__ == "__main__":
    import unittest

    unittest.main()
