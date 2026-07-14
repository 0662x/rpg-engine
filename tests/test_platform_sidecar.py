from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from rpg_engine.game_session import (
    ACTIVE_GAME,
    INACTIVE,
    PENDING_APPROVAL,
    GameSessionBinding,
    PlatformMessage,
    hash_identity,
    hash_text,
)
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


def sidecar_config(
    *,
    enabled: bool = True,
    ttl: int = 1800,
    player_intent_ai: str = "consensus",
    audit_log: Path | None = None,
) -> PlatformSidecarConfig:
    prewarm = PlatformPrewarmConfig(
        enabled=enabled,
        intent_backend="direct",
        intent_provider="deepseek",
        intent_model="deepseek-v4-flash",
        intent_timeout=6,
        intent_api_key_env="AIGM_TEST_MISSING_KEY",
    )
    if audit_log is not None:
        return PlatformSidecarConfig.from_prewarm_config(
            prewarm,
            player_intent_ai=player_intent_ai,
            active_ttl_seconds=ttl,
            preflight_pending_wait_ms=10,
            audit_log=audit_log,
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

    def test_platform_start_rejects_actorless_event_before_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", side_effect=AssertionError("SaveManager called before start gate")):
                result = sidecar.start_or_continue_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:user:missing-actor",
                        "message_id": "qq:start:missing-actor",
                        "text": "开始游戏",
                    },
                    campaign="campaigns/minimal",
                ).to_dict()

            self.assertFalse(result["ok"], result)
            self.assertEqual(result["status"], "platform_rejected")
            self.assertEqual(result["platform_gate"]["reason"], "missing_actor_id")
            self.assertIsNone(result["platform_binding"])

    def test_platform_duplicate_start_is_reserved_before_forwarding_to_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            second_sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            calls: list[dict[str, object]] = []
            duplicates: list[dict[str, object]] = []
            event = {
                "platform": "qq",
                "session_key": "qq:user:1",
                "message_id": "qq:start:reentrant",
                "text": "开始游戏",
                "actor_id": "user:1",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def start_or_continue(self, **kwargs: object) -> dict[str, object]:
                    calls.append(kwargs)
                    duplicates.append(second_sidecar.start_or_continue_from_message(event, campaign="campaigns/minimal").to_dict())
                    return {
                        "ok": True,
                        "status": "started",
                        "active_save_id": "save:bound",
                        "save": {"id": "save:bound", "path": "saves/bound-run"},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.start_or_continue_from_message(event, campaign="campaigns/minimal").to_dict()

            self.assertTrue(result["ok"], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertFalse(duplicates[0]["ok"], duplicates[0])
            self.assertEqual(duplicates[0]["platform_gate"]["reason"], "duplicate_start_message")

    def test_platform_start_completion_preserves_a_newer_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            event = {
                "platform": "qq",
                "session_key": "qq:session:start-race",
                "message_id": "qq:start:older",
                "text": "开始游戏",
                "actor_id": "actor:start-race",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def start_or_continue(self, **kwargs: object) -> dict[str, object]:
                    store.upsert_raw(
                        platform="qq",
                        session_key="qq:session:start-race",
                        user_id="actor:start-race",
                        active_save="saves/newer-run",
                        state=ACTIVE_GAME,
                        active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
                        last_message_id="qq:start:newer",
                    )
                    return {
                        "ok": True,
                        "status": "started",
                        "active_save_id": "save:older",
                        "save": {"id": "save:older", "path": "saves/older-run"},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.start_or_continue_from_message(event, campaign="campaigns/minimal").to_dict()

            binding = store.get(platform="qq", session_key="qq:session:start-race")
            self.assertTrue(result["ok"], result)
            self.assertIsNotNone(binding)
            self.assertEqual(binding.active_save, "saves/newer-run")
            self.assertEqual(result["platform_binding"]["active_save"], "saves/newer-run")

    def test_platform_start_completion_does_not_undo_placeholder_deactivate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            event = {
                "platform": "qq",
                "session_key": "qq:session:start-deactivate",
                "message_id": "qq:start:before-deactivate",
                "text": "开始游戏",
                "actor_id": "actor:start-deactivate",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def start_or_continue(self, **_kwargs: object) -> dict[str, object]:
                    deactivated = sidecar.deactivate_from_message(
                        {
                            **event,
                            "message_id": "qq:deactivate:newer",
                            "text": "退出",
                        }
                    )
                    self.deactivated = deactivated
                    return {
                        "ok": True,
                        "status": "started",
                        "active_save_id": "save:older",
                        "save": {"id": "save:older", "path": "saves/older-run"},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.start_or_continue_from_message(event, campaign="campaigns/minimal").to_dict()

            binding = sidecar.binding_store.get(platform="qq", session_key="qq:session:start-deactivate")
            self.assertTrue(result["ok"], result)
            self.assertIsNotNone(binding)
            self.assertEqual(binding.state, INACTIVE)
            self.assertEqual(binding.active_save, "")
            self.assertEqual(result["platform_binding"]["state"], INACTIVE)
            self.assertEqual(result["platform_binding"]["active_save"], "")

    def test_platform_act_and_confirm_reject_inactive_session_before_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", side_effect=AssertionError("SaveManager called before gate")):
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

    def test_platform_act_forwards_bound_save_and_passive_identity_to_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:raw",
                user_id="actor:raw",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            calls: list[dict[str, object]] = []

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_turn(self, **kwargs: object) -> dict[str, object]:
                    calls.append(kwargs)
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": "player_action:test",
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                acted = sidecar.player_act_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:session:raw",
                        "message_id": "qq:act:identity",
                        "text": "休息到早上",
                        "actor_id": "actor:raw",
                    }
                ).to_dict()

            self.assertTrue(acted["ok"], acted)
            self.assertEqual(calls[0]["save_path"], "saves/bound-run")
            self.assertEqual(calls[0]["message_id"], "qq:act:identity")
            self.assertEqual(calls[0]["platform"], "qq")
            self.assertEqual(calls[0]["session_key"], "qq:session:raw")
            self.assertEqual(calls[0]["actor_id"], "actor:raw")
            self.assertEqual(calls[0]["source_user_text_hash"], hash_text("休息到早上"))
            self.assertEqual(calls[0]["preflight_pending_wait_ms"], 10)
            self.assertNotIn("external_intent_candidate", calls[0])
            self.assertEqual(acted["platform_binding"]["active_save"], "saves/bound-run")

    def test_platform_sidecar_writes_sanitized_audit_for_rejected_and_forwarded_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_log = root / "logs" / "platform-audit.jsonl"
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:raw",
                user_id="actor:raw",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_turn(self, **kwargs: object) -> dict[str, object]:
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": "player_action:audit",
                        "turn_proposal": {"privateReasonings": ["do not audit"]},
                        "delta": {"HiddenFacts": ["do not audit"]},
                        "warnings": [{"gmNotes": "do not audit"}],
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False, audit_log=audit_log))
            rejected = sidecar.player_act_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:missing",
                    "message_id": "qq:act:missing",
                    "text": "休息到早上",
                    "actor_id": "actor:raw",
                }
            ).to_dict()
            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                forwarded = sidecar.player_act_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:session:raw",
                        "message_id": "qq:act:audit",
                        "text": "休息到早上",
                        "actor_id": "actor:raw",
                    }
                ).to_dict()

            records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
            audit_text = json.dumps(records, ensure_ascii=False)

            self.assertFalse(rejected["ok"], rejected)
            self.assertTrue(forwarded["ok"], forwarded)
            self.assertEqual([record["operation"] for record in records], ["PlatformSidecar.player_act_from_message"] * 2)
            self.assertEqual(records[0]["status"], "rejected")
            self.assertEqual(records[1]["status"], "ok")
            self.assertEqual(records[0]["surface_category"], "platform sidecar")
            self.assertEqual(records[1]["surface_category"], "platform sidecar")
            self.assertEqual(records[1]["identity"]["platform"], "qq")
            self.assertEqual(records[1]["identity"]["message_id"], "qq:act:audit")
            self.assertTrue(records[1]["identity"]["session_key_hash"].startswith("sha256:"))
            self.assertTrue(records[1]["identity"]["actor_id_hash"].startswith("sha256:"))
            self.assertNotIn("qq:session:raw", audit_text)
            self.assertNotIn("actor:raw", audit_text)
            self.assertNotIn("do not audit", audit_text)
            self.assertNotIn("Hidden-Facts", audit_text)
            self.assertNotIn("HiddenFacts", audit_text)
            self.assertNotIn("privateReasonings", audit_text)
            self.assertNotIn("gmNotes", audit_text)
            self.assertNotIn("turn_proposal", audit_text)

    def test_platform_audit_write_failure_does_not_change_operation_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad_audit_path = root / "logs"
            bad_audit_path.mkdir()
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False, audit_log=bad_audit_path))

            result = sidecar.player_act_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:missing",
                    "message_id": "qq:act:missing",
                    "text": "休息到早上",
                    "actor_id": "actor:raw",
                }
            ).to_dict()

            self.assertFalse(result["ok"], result)
            self.assertEqual(result["status"], "platform_rejected")
            self.assertEqual(result["platform_gate"]["reason"], "inactive")

    def test_platform_duplicate_act_is_reserved_before_forwarding_to_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:raw",
                user_id="actor:raw",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            second_sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            calls: list[dict[str, object]] = []
            duplicates: list[dict[str, object]] = []
            event = {
                "platform": "qq",
                "session_key": "qq:session:raw",
                "message_id": "qq:act:reentrant",
                "text": "休息到早上",
                "actor_id": "actor:raw",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_turn(self, **kwargs: object) -> dict[str, object]:
                    calls.append(kwargs)
                    duplicates.append(second_sidecar.player_act_from_message(event).to_dict())
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": "player_action:reserved",
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.player_act_from_message(event).to_dict()

            self.assertTrue(result["ok"], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertFalse(duplicates[0]["ok"], duplicates[0])
            self.assertEqual(duplicates[0]["platform_gate"]["reason"], "duplicate_action_message")

    def test_platform_act_completion_does_not_reactivate_a_newly_inactive_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:deactivate",
                user_id="actor:deactivate",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            event = {
                "platform": "qq",
                "session_key": "qq:session:deactivate",
                "message_id": "qq:act:before-deactivate",
                "text": "休息到早上",
                "actor_id": "actor:deactivate",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_turn(self, **kwargs: object) -> dict[str, object]:
                    sidecar.deactivate_from_message(
                        {
                            **event,
                            "message_id": "qq:deactivate:newer",
                            "text": "退出",
                        }
                    )
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": "player_action:stale-completion",
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.player_act_from_message(event).to_dict()

            binding = store.get(platform="qq", session_key="qq:session:deactivate")
            self.assertTrue(result["ok"], result)
            self.assertIsNotNone(binding)
            self.assertEqual(binding.state, INACTIVE)
            self.assertEqual(result["platform_binding"]["state"], INACTIVE)

    def test_platform_act_completion_merges_advisory_prewarm_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:prewarm-race",
                user_id="actor:prewarm-race",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=True))
            event = {
                "platform": "qq",
                "session_key": "qq:session:prewarm-race",
                "message_id": "qq:act:before-prewarm",
                "text": "休息到早上",
                "actor_id": "actor:prewarm-race",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_turn(self, **kwargs: object) -> dict[str, object]:
                    prewarm = sidecar.handle_message_event(
                        {
                            **event,
                            "message_id": "qq:prewarm:newer",
                            "text": "查看四周",
                        }
                    )
                    self.prewarm = prewarm
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": "player_action:prewarm-race",
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.player_act_from_message(event).to_dict()

            binding = store.get(platform="qq", session_key="qq:session:prewarm-race")
            self.assertTrue(result["ok"], result)
            self.assertIsNotNone(binding)
            self.assertEqual(binding.state, PENDING_APPROVAL)
            self.assertEqual(binding.last_message_id, "qq:prewarm:newer")
            self.assertEqual(binding.last_action_message_id, "qq:act:before-prewarm")
            self.assertEqual(result["platform_binding"]["state"], PENDING_APPROVAL)

    def test_platform_duplicate_confirm_is_reserved_before_forwarding_to_save_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:raw",
                user_id="actor:raw",
                active_save="saves/bound-run",
                state=PENDING_APPROVAL,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            second_sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            calls: list[dict[str, object]] = []
            duplicates: list[dict[str, object]] = []
            event = {
                "platform": "qq",
                "session_key": "qq:session:raw",
                "message_id": "qq:confirm:reentrant",
                "text": "确认",
                "actor_id": "actor:raw",
            }

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def player_confirm(self, **kwargs: object) -> dict[str, object]:
                    calls.append(kwargs)
                    duplicates.append(second_sidecar.player_confirm_from_message(event, session_id="player_action:reserved").to_dict())
                    return {
                        "ok": True,
                        "status": "saved",
                        "saved": True,
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.player_confirm_from_message(event, session_id="player_action:reserved").to_dict()

            self.assertTrue(result["ok"], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(duplicates), 1)
            self.assertFalse(duplicates[0]["ok"], duplicates[0])
            self.assertEqual(duplicates[0]["platform_gate"]["reason"], "duplicate_confirm_message")

    def test_platform_prewarm_exception_is_audited_without_being_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_log = root / "logs" / "platform-audit.jsonl"
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False, audit_log=audit_log))

            def fail_prewarm(_message: PlatformMessage) -> object:
                raise RuntimeError("prewarm boom")

            sidecar.prewarm_service.handle_message = fail_prewarm  # type: ignore[method-assign]
            with self.assertRaisesRegex(RuntimeError, "prewarm boom"):
                sidecar.handle_message_event(
                    {
                        "platform": "qq",
                        "session_key": "qq:user:1",
                        "message_id": "qq:prewarm:boom",
                        "text": "休息到早上",
                        "actor_id": "user:1",
                    }
                )

            records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["operation"], "PlatformSidecar.handle_message_event")
            self.assertEqual(records[0]["surface_category"], "platform prewarm")
            self.assertEqual(records[0]["status"], "error")
            self.assertIn("prewarm boom", records[0]["result"]["errors"][0])

    def test_platform_act_prewarm_exception_remains_advisory_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_log = root / "logs" / "platform-audit.jsonl"
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:raw",
                user_id="actor:raw",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False, audit_log=audit_log))
            calls: list[dict[str, object]] = []

            def fail_prewarm(_message: PlatformMessage) -> object:
                raise RuntimeError("advisory boom")

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_turn(self, **kwargs: object) -> dict[str, object]:
                    calls.append(kwargs)
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": "player_action:advisory",
                        "save": {"id": "save:bound", "path": kwargs["save_path"]},
                    }

            sidecar.prewarm_service.handle_message = fail_prewarm  # type: ignore[method-assign]
            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                result = sidecar.player_act_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:session:raw",
                        "message_id": "qq:act:advisory-boom",
                        "text": "休息到早上",
                        "actor_id": "actor:raw",
                    }
                ).to_dict()

            records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
            audit_text = json.dumps(records, ensure_ascii=False)

            self.assertTrue(result["ok"], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["platform_prewarm"]["reason"], "platform_prewarm_error")
            self.assertTrue(result["platform_prewarm"]["dropped"])
            self.assertEqual(records[0]["operation"], "PlatformSidecar.player_act_from_message")
            self.assertEqual(records[0]["status"], "ok")
            self.assertEqual(records[0]["result"]["platform_prewarm"]["reason"], "platform_prewarm_error")
            self.assertNotIn("advisory boom", audit_text)
            self.assertNotIn("qq:session:raw", audit_text)
            self.assertNotIn("actor:raw", audit_text)

    def test_platform_start_exception_is_audited_without_being_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_log = root / "logs" / "platform-audit.jsonl"
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False, audit_log=audit_log))

            class ExplodingSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def start_or_continue(self, **_kwargs: object) -> dict[str, object]:
                    raise RuntimeError("start boom qq:user:1 user:1 privateReasoning do not audit")

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", ExplodingSaveManager):
                with self.assertRaisesRegex(RuntimeError, "start boom"):
                    sidecar.start_or_continue_from_message(
                        {
                            "platform": "qq",
                            "session_key": "qq:user:1",
                            "message_id": "qq:start:boom",
                            "text": "开始游戏",
                            "actor_id": "user:1",
                        },
                        campaign="campaigns/minimal",
                    )

            records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
            audit_text = json.dumps(records, ensure_ascii=False)
            self.assertEqual(records[0]["operation"], "PlatformSidecar.start_or_continue_from_message")
            self.assertEqual(records[0]["status"], "error")
            self.assertEqual(records[0]["result"]["errors"][0], "<redacted sensitive audit text>")
            self.assertNotIn("qq:user:1", audit_text)
            self.assertNotIn("user:1", audit_text)
            self.assertNotIn("privateReasoning", audit_text)
            self.assertNotIn("do not audit", audit_text)

    def test_platform_start_exception_rolls_back_existing_confirmation_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            pending_session_id = "player_action:pending-before-start"
            before = store.upsert_raw(
                platform="qq",
                session_key="qq:session:start-failure",
                user_id="actor:start-failure",
                active_save="saves/existing-run",
                state=PENDING_APPROVAL,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
                pending_confirmation_session_hash=hash_identity(pending_session_id),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))

            class ExplodingSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def start_or_continue(self, **_kwargs: object) -> dict[str, object]:
                    raise RuntimeError("start failed")

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", ExplodingSaveManager):
                with self.assertRaisesRegex(RuntimeError, "start failed"):
                    sidecar.start_or_continue_from_message(
                        {
                            "platform": "qq",
                            "session_key": "qq:session:start-failure",
                            "message_id": "qq:start:failing",
                            "text": "开始新游戏",
                            "actor_id": "actor:start-failure",
                        }
                    )

            after = store.get(platform="qq", session_key="qq:session:start-failure")
            self.assertIsNotNone(after)
            self.assertEqual(after.active_save, before.active_save)
            self.assertEqual(after.state, before.state)
            self.assertEqual(after.revision, before.revision)
            self.assertEqual(after.pending_confirmation_revision, before.pending_confirmation_revision)
            self.assertEqual(after.pending_confirmation_session_hash, before.pending_confirmation_session_hash)
            self.assertEqual(after.last_message_id, before.last_message_id)

    def test_platform_gate_rejects_different_actor_on_bound_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            started = sidecar.start_or_continue_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:group:1",
                    "message_id": "qq:start",
                    "text": "开始游戏",
                    "actor_id": "user:one",
                },
                campaign="campaigns/minimal",
            ).to_dict()
            acted = sidecar.player_act_from_message(
                {
                    "platform": "qq",
                    "session_key": "qq:group:1",
                    "message_id": "qq:act:wrong-actor",
                    "text": "休息到早上",
                    "actor_id": "user:two",
                }
            ).to_dict()

            self.assertTrue(started["ok"], started)
            self.assertFalse(acted["ok"], acted)
            self.assertEqual(acted["platform_gate"]["reason"], "actor_mismatch")
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())

    def test_message_prewarm_then_player_act_uses_same_message_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=True))
            raw_session = "qq:user:raw-session"
            raw_actor = "user:raw-actor"
            start = sidecar.start_or_continue_from_message(
                {
                    "platform": "qq",
                    "session_key": raw_session,
                    "message_id": "qq:start",
                    "text": "开始游戏",
                    "actor_id": raw_actor,
                },
                campaign="campaigns/minimal",
            )

            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = fake_internal_review("sidecar message-only preflight hit")
            try:
                prewarm = sidecar.handle_message_event(
                    {
                        "platform": "qq",
                        "session_key": raw_session,
                        "message_id": "qq:act",
                        "text": "休息到早上",
                        "actor_id": raw_actor,
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
                        "session_key": raw_session,
                        "message_id": "qq:act",
                        "text": "休息到早上",
                        "actor_id": raw_actor,
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

            pending = json.loads((root / ".aigm" / "pending-player-action.json").read_text(encoding="utf-8"))
            raw_pending = json.dumps(pending, ensure_ascii=False)
            preflight_record = pending["turn_proposal"]["intent"]["decision_trace"]["intent_ai"]["preflight"]["record"]
            self.assertEqual(pending["session_key_hash"], hash_identity(raw_session))
            self.assertEqual(pending["actor_id_hash"], hash_identity(raw_actor))
            self.assertEqual(preflight_record["session_key_hash"], hash_identity(raw_session))
            self.assertNotIn("session_key", preflight_record)
            self.assertNotIn(raw_session, raw_pending)
            self.assertNotIn(raw_actor, raw_pending)

            duplicate = sidecar.player_act_from_message(
                {
                    "platform": "qq",
                    "session_key": raw_session,
                    "message_id": "qq:act",
                    "text": "休息到早上",
                    "actor_id": raw_actor,
                }
            ).to_dict()

            self.assertFalse(duplicate["ok"], duplicate)
            self.assertEqual(duplicate["platform_gate"]["reason"], "duplicate_action_message")

            confirmed = sidecar.player_confirm_from_message(
                {
                    "platform": "qq",
                    "session_key": raw_session,
                    "message_id": "qq:confirm",
                    "text": "确认",
                    "actor_id": raw_actor,
                },
                session_id=acted["session_id"],
            ).to_dict()
            binding_after_fresh = sidecar.binding_store.get(platform="qq", session_key=raw_session)
            self.assertIsNotNone(binding_after_fresh)
            replayed = sidecar.player_confirm_from_message(
                {
                    "platform": "qq",
                    "session_key": raw_session,
                    "message_id": "qq:confirm:retry",
                    "text": "再次确认",
                    "actor_id": raw_actor,
                },
                session_id=acted["session_id"],
            ).to_dict()
            binding_after_replay = sidecar.binding_store.get(platform="qq", session_key=raw_session)
            self.assertIsNotNone(binding_after_replay)
            confirmed_text = json.dumps(confirmed, ensure_ascii=False)

            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertEqual(confirmed["write_status"], "committed")
            self.assertFalse(confirmed["idempotent_replay"])
            self.assertTrue(replayed["ok"], replayed)
            self.assertFalse(replayed["saved"], replayed)
            self.assertEqual(replayed["write_status"], "already_confirmed")
            self.assertTrue(replayed["idempotent_replay"])
            self.assertEqual(replayed["platform_metrics"]["sidecar"]["saved_count"], 1)
            self.assertEqual(binding_after_replay.active_until, binding_after_fresh.active_until)
            self.assertEqual(binding_after_replay.state, binding_after_fresh.state)
            self.assertEqual(binding_after_replay.active_save, binding_after_fresh.active_save)
            stale_fresh_message = PlatformMessage(
                platform="qq",
                session_key=raw_session,
                message_id="qq:confirm:stale-fresh",
                text="确认",
                actor_id=raw_actor,
            )
            later_retry_message = PlatformMessage(
                platform="qq",
                session_key=raw_session,
                message_id="qq:confirm:later-retry",
                text="再次确认",
                actor_id=raw_actor,
            )
            stale_reservation = sidecar._reserve_platform_message(
                binding_after_replay,
                stale_fresh_message,
                kind="confirm",
            )
            later_reservation = sidecar._reserve_platform_message(
                stale_reservation,
                later_retry_message,
                kind="confirm",
            )
            merged = sidecar._merge_confirm_result_binding(
                stale_fresh_message,
                {
                    "ok": True,
                    "save": confirmed["save"],
                    "write_status": "committed",
                    "idempotent_replay": False,
                },
                fallback=stale_reservation,
                confirmation_session_id=str(acted["session_id"]),
            )
            self.assertEqual(merged.last_message_id, later_reservation.last_message_id)
            self.assertEqual(merged.last_confirm_message_id, later_reservation.last_confirm_message_id)
            next_confirm = PlatformMessage(
                platform="qq",
                session_key=raw_session,
                message_id="qq:confirm:before-deactivate",
                text="确认",
                actor_id=raw_actor,
            )
            before_deactivate = sidecar._reserve_platform_message(merged, next_confirm, kind="confirm")
            inactive = GameSessionBinding(
                platform=before_deactivate.platform,
                session_key_hash=before_deactivate.session_key_hash,
                active_save=before_deactivate.active_save,
                state=INACTIVE,
                active_until="",
                user_id_hash=before_deactivate.user_id_hash,
                last_message_id="qq:deactivate:newer",
                last_action_message_id=before_deactivate.last_action_message_id,
                last_confirm_message_id=before_deactivate.last_confirm_message_id,
                clarification_id=before_deactivate.clarification_id,
                updated_at="newer-deactivate",
            )
            sidecar.binding_store.upsert(inactive)
            preserved = sidecar._merge_confirm_result_binding(
                next_confirm,
                {
                    "ok": True,
                    "save": confirmed["save"],
                    "write_status": "committed",
                    "idempotent_replay": False,
                },
                fallback=before_deactivate,
                confirmation_session_id=str(acted["session_id"]),
            )
            self.assertEqual(preserved.state, INACTIVE)
            self.assertEqual(preserved.last_message_id, "qq:deactivate:newer")
            for hidden_key in (
                "delta",
                "delta_draft",
                "turn_proposal",
                "validation_report",
                "projection_report",
                "state_audit",
                "check_errors",
            ):
                self.assertNotIn(hidden_key, confirmed)
            self.assertNotIn(raw_session, confirmed_text)
            self.assertNotIn(raw_actor, confirmed_text)

    def test_platform_replay_repairs_missing_fresh_confirmation_completion_without_ttl_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=True))
            raw_session = "qq:user:completion-crash"
            raw_actor = "user:completion-crash"
            sidecar.start_or_continue_from_message(
                {
                    "platform": "qq",
                    "session_key": raw_session,
                    "message_id": "qq:start:completion-crash",
                    "text": "开始游戏",
                    "actor_id": raw_actor,
                },
                campaign="campaigns/minimal",
            )

            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = fake_internal_review("completion crash preflight")
            try:
                prewarm = sidecar.handle_message_event(
                    {
                        "platform": "qq",
                        "session_key": raw_session,
                        "message_id": "qq:act:completion-crash",
                        "text": "休息到早上",
                        "actor_id": raw_actor,
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
                        "session_key": raw_session,
                        "message_id": "qq:act:completion-crash",
                        "text": "休息到早上",
                        "actor_id": raw_actor,
                    }
                ).to_dict()
            finally:
                if old_missing_key is not None:
                    os.environ["AIGM_TEST_MISSING_KEY"] = old_missing_key

            self.assertTrue(prewarm.enqueued, prewarm.to_dict())
            self.assertEqual(worker_results[0].status, "ready")
            self.assertTrue(acted["ready_to_confirm"], acted)
            before_confirm = sidecar.binding_store.get(platform="qq", session_key=raw_session)
            self.assertIsNotNone(before_confirm)
            ttl_before = before_confirm.active_until
            expected_session_hash = hash_identity(str(acted["session_id"]))
            self.assertEqual(before_confirm.pending_confirmation_session_hash, expected_session_hash)

            with mock.patch.object(
                sidecar,
                "_merge_confirm_result_binding",
                side_effect=RuntimeError("crash before platform completion"),
            ):
                with self.assertRaisesRegex(RuntimeError, "crash before platform completion"):
                    sidecar.player_confirm_from_message(
                        {
                            "platform": "qq",
                            "session_key": raw_session,
                            "message_id": "qq:confirm:completion-crash",
                            "text": "确认",
                            "actor_id": raw_actor,
                        },
                        session_id=str(acted["session_id"]),
                    )

            stuck = sidecar.binding_store.get(platform="qq", session_key=raw_session)
            self.assertIsNotNone(stuck)
            self.assertEqual(stuck.state, PENDING_APPROVAL)
            self.assertEqual(stuck.pending_confirmation_session_hash, expected_session_hash)

            replay = sidecar.player_confirm_from_message(
                {
                    "platform": "qq",
                    "session_key": raw_session,
                    "message_id": "qq:confirm:completion-retry",
                    "text": "再次确认",
                    "actor_id": raw_actor,
                },
                session_id=str(acted["session_id"]),
            ).to_dict()
            repaired = sidecar.binding_store.get(platform="qq", session_key=raw_session)

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertTrue(replay["idempotent_replay"])
            self.assertFalse(replay["saved"])
            self.assertIsNotNone(repaired)
            self.assertEqual(repaired.state, ACTIVE_GAME)
            self.assertEqual(repaired.active_until, ttl_before)
            self.assertEqual(repaired.pending_confirmation_session_hash, "")
            self.assertEqual(repaired.last_completed_confirmation_session_hash, expected_session_hash)
            self.assertEqual(replay["platform_metrics"]["sidecar"]["saved_count"], 1)

    def test_platform_replay_backfills_owner_validated_legacy_revision_zero_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            confirmation_session_id = "player_action:legacy-owner-validated"
            confirmation_session_hash = hash_identity(confirmation_session_id)
            legacy = GameSessionBinding.from_raw(
                platform="qq",
                session_key="qq:session:legacy-confirm",
                user_id="actor:legacy-confirm",
                active_save="saves/legacy-run",
                state=PENDING_APPROVAL,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
                revision=0,
            )
            sidecar.binding_store.upsert(legacy)
            message = PlatformMessage(
                platform="qq",
                session_key="qq:session:legacy-confirm",
                message_id="qq:confirm:legacy-retry",
                text="再次确认",
                actor_id="actor:legacy-confirm",
            )
            fallback = sidecar._reserve_platform_message(legacy, message, kind="confirm")

            repaired = sidecar._merge_confirm_result_binding(
                message,
                {
                    "ok": True,
                    "saved": False,
                    "write_status": "already_confirmed",
                    "idempotent_replay": True,
                    "confirmation_session_hash": confirmation_session_hash,
                    "save": {"id": "save:legacy", "path": "saves/legacy-run"},
                },
                fallback=fallback,
                confirmation_session_id=confirmation_session_id,
            )

            self.assertEqual(repaired.state, ACTIVE_GAME)
            self.assertEqual(repaired.pending_confirmation_session_hash, "")
            self.assertEqual(repaired.pending_confirmation_revision, 0)
            self.assertEqual(repaired.last_completed_confirmation_session_hash, confirmation_session_hash)
            self.assertEqual(repaired.revision, 1)

    def test_newer_start_revision_wins_over_older_confirmation_replay_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            confirmation_session_id = "player_action:older-confirm"
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:confirm-start-race",
                user_id="actor:confirm-start-race",
                active_save="saves/old-run",
                state=PENDING_APPROVAL,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
                last_action_message_id="qq:act:old",
                pending_confirmation_session_hash=hash_identity(confirmation_session_id),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            confirm_message = PlatformMessage(
                platform="qq",
                session_key="qq:session:confirm-start-race",
                message_id="qq:confirm:older",
                text="确认",
                actor_id="actor:confirm-start-race",
            )
            observed_confirm_bindings: list[GameSessionBinding] = []

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def player_confirm(self, **_kwargs: object) -> dict[str, object]:
                    return {
                        "ok": True,
                        "saved": False,
                        "write_status": "already_confirmed",
                        "idempotent_replay": True,
                        "confirmation_session_hash": hash_identity(confirmation_session_id),
                        "save": {"id": "save:old", "path": "saves/old-run"},
                    }

                def start_or_continue(self, **_kwargs: object) -> dict[str, object]:
                    sidecar.player_confirm_from_message(
                        confirm_message,
                        session_id=confirmation_session_id,
                    )
                    observed_confirm_bindings.append(
                        sidecar.binding_store.get(
                            platform=confirm_message.platform,
                            session_key=confirm_message.session_key,
                        )
                    )
                    return {
                        "ok": True,
                        "status": "started",
                        "active_save_id": "save:new",
                        "save": {"id": "save:new", "path": "saves/new-run"},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                started = sidecar.start_or_continue_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:session:confirm-start-race",
                        "message_id": "qq:start:newer",
                        "text": "开始新游戏",
                        "actor_id": "actor:confirm-start-race",
                    },
                    campaign="campaigns/minimal",
                ).to_dict()

            final_binding = store.get(platform="qq", session_key="qq:session:confirm-start-race")
            self.assertEqual(observed_confirm_bindings[0].state, PENDING_APPROVAL)
            self.assertEqual(observed_confirm_bindings[0].active_save, "saves/old-run")
            self.assertTrue(started["ok"], started)
            self.assertIsNotNone(final_binding)
            self.assertEqual(final_binding.active_save, "saves/new-run")
            self.assertEqual(final_binding.state, ACTIVE_GAME)

    def test_platform_act_completion_ignores_non_authoritative_confirm_message_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:session:act-confirm-race",
                user_id="actor:act-confirm-race",
                active_save="saves/bound-run",
                state=ACTIVE_GAME,
                active_until=(datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            )
            sidecar = PlatformSidecar(root, config=sidecar_config(enabled=False))
            old_confirmation_id = "player_action:already-completed"
            new_confirmation_id = "player_action:new-action"

            class FakeSaveManager:
                def __init__(self, manager_root: Path) -> None:
                    self.manager_root = manager_root

                def read_pending_action(self) -> None:
                    return None

                def read_pending_clarification(self) -> None:
                    return None

                def player_confirm(self, **_kwargs: object) -> dict[str, object]:
                    return {
                        "ok": True,
                        "saved": False,
                        "write_status": "already_confirmed",
                        "idempotent_replay": True,
                        "confirmation_session_hash": hash_identity(old_confirmation_id),
                        "save": {"id": "save:bound", "path": "saves/bound-run"},
                    }

                def player_turn(self, **_kwargs: object) -> dict[str, object]:
                    sidecar.player_confirm_from_message(
                        {
                            "platform": "qq",
                            "session_key": "qq:session:act-confirm-race",
                            "message_id": "qq:confirm:during-act",
                            "text": "重试旧确认",
                            "actor_id": "actor:act-confirm-race",
                        },
                        session_id=old_confirmation_id,
                    )
                    return {
                        "ok": True,
                        "status": "ready",
                        "ready_to_confirm": True,
                        "session_id": new_confirmation_id,
                        "save": {"id": "save:bound", "path": "saves/bound-run"},
                    }

            with mock.patch("rpg_engine.platform_sidecar.SaveManager", FakeSaveManager):
                acted = sidecar.player_act_from_message(
                    {
                        "platform": "qq",
                        "session_key": "qq:session:act-confirm-race",
                        "message_id": "qq:act:new",
                        "text": "休息到早上",
                        "actor_id": "actor:act-confirm-race",
                    }
                ).to_dict()

            final_binding = store.get(platform="qq", session_key="qq:session:act-confirm-race")
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertIsNotNone(final_binding)
            self.assertEqual(final_binding.state, PENDING_APPROVAL)
            self.assertEqual(final_binding.pending_confirmation_session_hash, hash_identity(new_confirmation_id))
            self.assertEqual(final_binding.pending_confirmation_revision, final_binding.revision)
            self.assertEqual(final_binding.last_confirm_message_id, "qq:confirm:during-act")

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
