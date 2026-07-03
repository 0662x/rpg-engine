from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, rebuild_fts, resolve_entity, upsert_entity
from rpg_engine.preview import resolve_location
from rpg_engine.save_service import init_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


class EntityResolutionTests(unittest.TestCase):
    def test_resolution_handles_hyphen_chinese_queries_short_terms_and_hidden_clocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "project:arrow-upgrade",
                        "type": "project",
                        "name": "箭杆升级",
                        "summary": "测试用连字符项目。",
                        "aliases": ["箭杆升级"],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:powder-arrows",
                        "type": "item",
                        "name": "火药箭",
                        "summary": "火药爆破箭库存。",
                        "aliases": ["火药箭"],
                        "item": {"category": "ammo", "quantity": 5, "unit": "支", "stackable": True},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:black-powder",
                        "type": "item",
                        "name": "黑火药",
                        "summary": "造粒火药。",
                        "aliases": ["黑火药", "造粒火药"],
                        "item": {"category": "material", "quantity": 1, "unit": "碗", "stackable": True},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "pc:shenyan",
                        "type": "character",
                        "name": "亚",
                        "summary": "菌蛋白+菜+鱼，状态良好。",
                        "character": {"role": "player_character", "trust": 100},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plant:amaranth",
                        "type": "plant",
                        "name": "苋菜",
                        "summary": "测试用蔬菜作物。",
                        "aliases": ["苋菜"],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "threat:t2-large-cat",
                        "type": "threat",
                        "name": "大型猫科（推测）",
                        "summary": "T2 大猫已关押在地下室。",
                        "aliases": ["T2"],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:l05-oldwood",
                        "type": "location",
                        "name": "老树林",
                        "summary": "北侧巨树老林。",
                        "aliases": ["老树林"],
                        "location": {"safety_level": "risky", "travel_minutes_from_home": 20},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:l12-niter-crust",
                        "type": "location",
                        "name": "硝石岩壳",
                        "summary": "硝石资源点，描述里提到 L05 但不是 L05。",
                        "location": {"safety_level": "risky", "travel_minutes_from_home": 40},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "clock:civilization-rumor",
                        "type": "clock",
                        "name": "文明传闻",
                        "summary": "外部文明尚未接触，但火药可能外溢成传闻。",
                    },
                )
                conn.execute(
                    """
                    insert into clocks
                    (entity_id, clock_type, segments_filled, segments_total, visibility, trigger_when_full, tick_rules_json)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("clock:civilization-rumor", "faction", 0, 8, "hidden", "侦查者出现。", "[]"),
                )
                rebuild_fts(conn)
                conn.commit()

                self.assertEqual(resolve_entity(conn, "arrow-upgrade")["id"], "project:arrow-upgrade")
                self.assertEqual(resolve_entity(conn, "火药箭 库存")["id"], "item:powder-arrows")
                self.assertEqual(resolve_entity(conn, "T2 大猫 关押")["id"], "threat:t2-large-cat")
                self.assertEqual(resolve_entity(conn, "菜")["id"], "plant:amaranth")
                self.assertEqual(resolve_entity(conn, "火药")["id"], "item:powder-arrows")
                self.assertIsNone(resolve_entity(conn, "clock:civilization-rumor", view="player"))
                self.assertEqual(resolve_entity(conn, "clock:civilization-rumor", view="gm")["id"], "clock:civilization-rumor")
                self.assertEqual(resolve_location(conn, "L05")["id"], "loc:l05-oldwood")


if __name__ == "__main__":
    unittest.main()
