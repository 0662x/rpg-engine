from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from rpg_engine.game_session import (
    ACTIVE_GAME,
    PENDING_APPROVAL,
    PENDING_CLARIFICATION,
    GameSessionBinding,
    PlatformMessage,
    hash_identity,
    should_prewarm_message,
)


class GameSessionGateTests(unittest.TestCase):
    def binding(self, **overrides: object) -> GameSessionBinding:
        active_until = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        values = {
            "platform": "qq",
            "session_key": "qq:user:1",
            "active_save": "saves/run",
            "state": ACTIVE_GAME,
            "active_until": active_until,
        }
        values.update(overrides)
        return GameSessionBinding.from_raw(**values)

    def message(self, **overrides: object) -> PlatformMessage:
        values = {
            "platform": "qq",
            "session_key": "qq:user:1",
            "message_id": "qq:msg:1",
            "text": "休息到早上",
        }
        values.update(overrides)
        return PlatformMessage(**values)

    def test_active_game_text_message_can_prewarm(self) -> None:
        decision = should_prewarm_message(self.binding(), self.message())

        self.assertTrue(decision.allow, decision.to_dict())
        self.assertEqual(decision.reason, ACTIVE_GAME)
        self.assertEqual(decision.active_save, "saves/run")
        self.assertEqual(decision.session_key_hash, hash_identity("qq:user:1"))
        self.assertTrue(decision.source_user_text_hash)

    def test_gate_blocks_inactive_expired_or_pending_sessions(self) -> None:
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        cases = [
            (None, "inactive"),
            (GameSessionBinding.from_raw(platform="qq", session_key="qq:user:1", active_save="saves/run"), "inactive"),
            (self.binding(state="inactive"), "inactive"),
            (self.binding(state=PENDING_CLARIFICATION), PENDING_CLARIFICATION),
            (self.binding(state=PENDING_APPROVAL), PENDING_APPROVAL),
            (self.binding(active_until=""), "expired"),
            (self.binding(active_until=expired), "expired"),
            (self.binding(active_save=""), "no_active_save"),
        ]
        for binding, reason in cases:
            with self.subTest(reason=reason):
                decision = should_prewarm_message(binding, self.message())
                self.assertFalse(decision.allow, decision.to_dict())
                self.assertEqual(decision.reason, reason)

    def test_gate_blocks_non_game_or_unsafe_message_shapes(self) -> None:
        cases = [
            (self.message(message_id=""), "missing_message_id"),
            (self.message(text=""), "empty_text"),
            (self.message(text="/help"), "command"),
            (self.message(message_type="media"), "unsupported_message_type"),
            (self.message(chat_type="guild_dm"), "unsupported_chat"),
            (self.message(actor_is_bot=True), "actor_not_allowed"),
            (self.message(actor_is_self=True), "actor_not_allowed"),
            (self.message(is_approval=True), PENDING_APPROVAL),
            (self.message(platform="discord"), "platform_mismatch"),
            (self.message(session_key="qq:user:2"), "session_mismatch"),
            (self.message(message_id="qq:last"), "duplicate_message"),
        ]
        binding = self.binding(last_message_id="qq:last")
        for message, reason in cases:
            with self.subTest(reason=reason):
                decision = should_prewarm_message(binding, message)
                self.assertFalse(decision.allow, decision.to_dict())
                self.assertEqual(decision.reason, reason)


if __name__ == "__main__":
    unittest.main()
