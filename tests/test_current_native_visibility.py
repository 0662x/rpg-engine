from __future__ import annotations

import tempfile

from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, upsert_entity
from rpg_engine.projection_service import ProjectionService
from rpg_engine.runtime import GMRuntime

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
)


@CURRENT_NATIVE_REQUIRED
class CurrentNativeVisibilityTests(FormalCurrentSaveReadOnlyTestCase):
    def test_hidden_entity_probe_is_not_visible_to_player_but_is_visible_to_gm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-hidden-leak",
                        "type": "item",
                        "name": "泄漏诱饵SECRET",
                        "visibility": "hidden",
                        "status": "active",
                        "location_id": "loc:home-mycelium-house",
                        "summary": "绝密摘要不要给玩家",
                        "aliases": ["泄漏诱饵SECRET"],
                        "details": {"secret": "紫色密钥"},
                    },
                )
                conn.commit()
                report = ProjectionService(campaign, conn).refresh(names=["search"], dirty_only=False, profile="test:hidden_probe")
                conn.commit()
                self.assertTrue(report.ok, report.errors)

            runtime = GMRuntime.from_path(save)
            player = runtime.query("entity", "泄漏诱饵SECRET", view="player")
            gm = runtime.query("entity", "泄漏诱饵SECRET", view="gm")

            self.assertIn("未找到实体", player.text)
            self.assertNotIn("绝密摘要不要给玩家", player.text)
            self.assertNotIn("紫色密钥", player.text)
            self.assertIn("item:test-hidden-leak", gm.text)
            self.assertIn("绝密摘要不要给玩家", gm.text)
            self.assertIn("紫色密钥", gm.text)


if __name__ == "__main__":
    import unittest

    unittest.main()
