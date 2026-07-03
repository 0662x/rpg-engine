from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rpg_engine.game_session import ACTIVE_GAME, INACTIVE, PlatformMessage
from rpg_engine.platform_prewarm import GameSessionBindingStore, PlatformPrewarmConfig
from rpg_engine.platform_sidecar import (
    PlatformSidecar,
    PlatformSidecarConfig,
    platform_message_from_event,
)
from rpg_engine.save_manager import SaveManager


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def fake_internal_review(reason: str = "sidecar preflight agrees") -> str:
    return json.dumps(
        {
            "kind": "single",
            "mode": "action",
            "action": "rest",
            "slots": {"until": "morning"},
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [],
            "reason": reason,
            "agreement_with_external": "no_external",
            "disagreements": [],
            "external_candidate_quality": "no_external",
        },
        ensure_ascii=False,
    )


def sidecar_config(*, enabled: bool = True, ttl: int = 1800, player_intent_ai: str = "consensus") -> PlatformSidecarConfig:
    prewarm = PlatformPrewarmConfig(
        enabled=enabled,
        intent_backend="direct",
        intent_provider="deepseek",
        intent_model="deepseek-v4-flash",
        intent_timeout=6,
        intent_api_key_env="AIGM_TEST_MISSING_KEY",
    )
    return PlatformSidecarConfig.from_prewarm_config(
        prewarm,
        player_intent_ai=player_intent_ai,
        active_ttl_seconds=ttl,
        preflight_pending_wait_ms=10,
    )


class PlatformSidecarTests(unittest.TestCase):
    def test_raw_event_normalization_derives_supported_session_key(self) -> None:
        message = platform_message_from_event(
            {
                "platform": "qq",
                "msg_id": "msg:1",
                "content": "休息到早上",
                "type": "group",
                "group_id": "group:1",
                "user_id": "user:1",
                "at_bot": True,
            }
        )

        self.assertEqual(message.platform, "qq")
        self.assertEqual(message.message_id, "msg:1")
        self.assertEqual(message.text, "休息到早上")
        self.assertEqual(message.chat_type, "group_at")
        self.assertEqual(message.session_key, "qq:group:group:1")
        self.assertEqual(message.actor_id, "user:1")

    def test_start_activates_binding_and_expire_marks_it_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False, ttl=1))

            result = sidecar.start_or_continue_from_message(
                PlatformMessage(
                    platform="qq",
                    session_key="qq:user:1",
                    message_id="qq:start",
                    text="开始游戏",
                    actor_id="user:1",
                ),
                campaign="campaigns/minimal",
            ).to_dict()
            binding = GameSessionBindingStore(root).get(platform="qq", session_key="qq:user:1")
            expired = sidecar.expire_stale_bindings(now=datetime.now(timezone.utc) + timedelta(seconds=2))
            inactive = GameSessionBindingStore(root).get(platform="qq", session_key="qq:user:1")

            self.assertTrue(result["ok"], result)
            self.assertIsNotNone(binding)
            self.assertEqual(binding.state, ACTIVE_GAME)
            self.assertEqual(expired, 1)
            self.assertEqual(inactive.state, INACTIVE)

    def test_platform_act_and_confirm_reject_inactive_session_before_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))

            acted = sidecar.player_act_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:user:missing",
                    "message_id": "qq:act:missing",
                    "text": "休息到早上",
                    "actor_id": "user:missing",
                }
            ).to_dict()
            confirmed = sidecar.player_confirm_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:user:missing",
                    "message_id": "qq:confirm:missing",
                    "text": "确认",
                    "actor_id": "user:missing",
                },
                session_id="player_action:missing",
            ).to_dict()

            self.assertFalse(acted["ok"], acted)
            self.assertEqual(acted["status"], "platform_rejected")
            self.assertEqual(acted["platform_gate"]["reason"], "inactive")
            self.assertFalse(confirmed["ok"], confirmed)
            self.assertEqual(confirmed["platform_gate"]["reason"], "inactive")
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())

    def test_message_prewarm_then_player_act_uses_same_message_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=True))
            start = sidecar.start_or_continue_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:user:1",
                    "message_id": "qq:start",
                    "text": "开始游戏",
                    "actor_id": "user:1",
                },
                campaign="campaigns/minimal",
            )

            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = fake_internal_review("sidecar message-only preflight hit")
            try:
                prewarm = sidecar.handle_message_event(
                    {
                        "platform": "qq",
                        "session_key": "qq:user:1",
                        "message_id": "qq:act",
                        "text": "休息到早上",
                        "actor_id": "user:1",
                    }
                )
                worker_results = sidecar.drain_prewarm()
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            old_missing_key = os.environ.pop("AIGM_TEST_MISSING_KEY", None)
            try:
                acted = sidecar.player_act_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:user:1",
                        "message_id": "qq:act",
                        "text": "休息到早上",
                        "actor_id": "user:1",
                    }
                ).to_dict()
            finally:
                if old_missing_key is not None:
                    os.environ["AIGM_TEST_MISSING_KEY"] = old_missing_key

            metrics = sidecar.metrics_snapshot()

            self.assertTrue(start.result["ok"], start.to_dict())
            self.assertTrue(prewarm.enqueued, prewarm.to_dict())
            self.assertEqual(worker_results[0].status, "ready")
            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertEqual(acted["status"], "ready")
            self.assertEqual(acted["action"], "rest")
            self.assertIn("session_id", acted)
            self.assertNotIn("missing API key", json.dumps(acted, ensure_ascii=False))
            self.assertEqual(metrics["preflight_cache"]["message_only_used_count"], 1)
            self.assertGreaterEqual(metrics["sidecar"]["player_act_count"], 1)
            self.assertGreaterEqual(metrics["sidecar"]["ready_to_confirm_count"], 1)

            duplicate = sidecar.player_act_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:user:1",
                    "message_id": "qq:act",
                    "text": "休息到早上",
                    "actor_id": "user:1",
                }
            ).to_dict()

            self.assertFalse(duplicate["ok"], duplicate)
            self.assertEqual(duplicate["platform_gate"]["reason"], "duplicate_action_message")

    def test_platform_act_uses_bound_save_instead_of_global_active_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            start = sidecar.start_or_continue_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:user:1",
                    "message_id": "qq:start",
                    "text": "开始游戏",
                    "actor_id": "user:1",
                },
                campaign="campaigns/minimal",
            )
            bound_save = start.result["save"]
            manager = SaveManager(root)
            second = manager.duplicate_save(bound_save["id"], label="Second", activate=True)
            self.assertEqual(manager.current_save()["active_save_id"], second["save"]["id"])

            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = fake_internal_review("bound save action")
            try:
                acted = sidecar.player_act_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:user:1",
                        "message_id": "qq:act:bound",
                        "text": "休息到早上",
                        "actor_id": "user:1",
                    }
                ).to_dict()
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            self.assertEqual(manager.current_save()["active_save_id"], second["save"]["id"])
            self.assertEqual(acted["active_save_id"], bound_save["id"], acted)
            self.assertEqual(acted["save"]["path"], bound_save["path"])
            self.assertEqual(acted["platform_binding"]["active_save"], bound_save["path"])


if __name__ == "__main__":
    unittest.main()
