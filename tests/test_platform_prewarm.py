from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rpg_engine.game_session import ACTIVE_GAME, PlatformMessage, hash_identity
from rpg_engine.platform_prewarm import (
    DROP_AI_TIMEOUT,
    DROP_DUPLICATE_MESSAGE,
    DROP_FEATURE_DISABLED,
    DROP_MISSING_PLATFORM,
    DROP_QUEUE_FULL,
    GameSessionBindingStore,
    PlatformPrewarmConfig,
    PlatformPrewarmRequest,
    PlatformPrewarmService,
    PrewarmMetrics,
    PrewarmQueue,
    PrewarmWorker,
)


def active_until() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()


def message(message_id: str = "qq:msg:1", **overrides: object) -> PlatformMessage:
    values = {
        "platform": "qq",
        "session_key": "qq:user:1",
        "message_id": message_id,
        "text": "休息到早上",
    }
    values.update(overrides)
    return PlatformMessage(**values)


class FakeRuntime:
    def __init__(self, path: Path, calls: list[dict[str, object]]) -> None:
        self.path = path
        self.calls = calls

    def preflight_intent(self, user_text: str, **kwargs: object) -> dict[str, object]:
        self.calls.append({"path": self.path, "user_text": user_text, **kwargs})
        return {"ok": True, "status": "ready", "preflight_id": "preflight:test", "errors": []}


class TimeoutRuntime:
    def preflight_intent(self, user_text: str, **kwargs: object) -> dict[str, object]:
        raise TimeoutError("internal AI timed out")


class PlatformPrewarmTests(unittest.TestCase):
    def test_binding_store_persists_hashes_without_raw_platform_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)

            binding = store.upsert_raw(
                platform="qq",
                session_key="qq:user:1",
                user_id="player:1",
                active_save="saves/run",
                state=ACTIVE_GAME,
                active_until=active_until(),
            )
            loaded = store.get(platform="qq", session_key="qq:user:1")
            raw = store.path.read_text(encoding="utf-8")

            self.assertEqual(binding.session_key_hash, hash_identity("qq:user:1"))
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.active_save, "saves/run")
            self.assertNotIn("qq:user:1", raw)
            self.assertNotIn("player:1", raw)

            store.record_last_message(platform="qq", session_key="qq:user:1", message_id="qq:last")
            updated = store.get(platform="qq", session_key="qq:user:1")
            self.assertEqual(updated.last_message_id, "qq:last")

    def test_service_feature_flag_missing_identity_and_duplicate_drops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = GameSessionBindingStore(root)
            store.upsert_raw(
                platform="qq",
                session_key="qq:user:1",
                active_save="saves/run",
                state=ACTIVE_GAME,
                active_until=active_until(),
            )
            metrics = PrewarmMetrics()
            disabled = PlatformPrewarmService(
                root,
                config=PlatformPrewarmConfig(enabled=False),
                binding_store=store,
                metrics=metrics,
            )
            dropped = disabled.handle_message(message())
            self.assertTrue(dropped.allow_platform)
            self.assertTrue(dropped.dropped)
            self.assertEqual(dropped.reason, DROP_FEATURE_DISABLED)

            enabled = PlatformPrewarmService(
                root,
                config=PlatformPrewarmConfig(enabled=True, max_queue_size=2),
                binding_store=store,
                metrics=metrics,
            )
            missing = enabled.handle_message(message(platform=""))
            first = enabled.handle_message(message())
            duplicate = enabled.handle_message(message())

            self.assertEqual(missing.reason, DROP_MISSING_PLATFORM)
            self.assertTrue(first.enqueued, first.to_dict())
            self.assertEqual(first.queue_depth, 1)
            self.assertEqual(duplicate.reason, DROP_DUPLICATE_MESSAGE)
            snapshot = metrics.snapshot(queue_depth=enabled.queue.qsize())
            self.assertGreaterEqual(snapshot["prewarm_drop_reasons"][DROP_FEATURE_DISABLED], 1)
            self.assertGreaterEqual(snapshot["prewarm_drop_reasons"][DROP_DUPLICATE_MESSAGE], 1)

    def test_queue_dedupes_and_drops_when_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metrics = PrewarmMetrics()
            queue = PrewarmQueue(maxsize=1, metrics=metrics)
            first = PlatformPrewarmRequest(
                root=root,
                active_save="saves/run",
                message=message("qq:1"),
                source_user_text_hash="hash:1",
            )
            duplicate = PlatformPrewarmRequest(
                root=root,
                active_save="saves/run",
                message=message("qq:1"),
                source_user_text_hash="hash:1",
            )
            second = PlatformPrewarmRequest(
                root=root,
                active_save="saves/run",
                message=message("qq:2"),
                source_user_text_hash="hash:2",
            )

            self.assertTrue(queue.enqueue(first).enqueued)
            self.assertEqual(queue.enqueue(duplicate).reason, DROP_DUPLICATE_MESSAGE)
            self.assertEqual(queue.enqueue(second).reason, DROP_QUEUE_FULL)
            snapshot = metrics.snapshot(queue_depth=queue.qsize())
            self.assertEqual(snapshot["prewarm_enqueue_count"], 1)
            self.assertEqual(snapshot["prewarm_drop_reasons"][DROP_QUEUE_FULL], 1)

    def test_worker_runs_message_only_preflight_and_records_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls: list[dict[str, object]] = []
            metrics = PrewarmMetrics()
            request = PlatformPrewarmRequest(
                root=root,
                active_save="saves/run",
                message=message("qq:worker"),
                source_user_text_hash="hash:worker",
            )
            worker = PrewarmWorker(
                config=PlatformPrewarmConfig(enabled=True, intent_timeout=6),
                metrics=metrics,
                runtime_factory=lambda path: FakeRuntime(path, calls),
            )

            result = worker.process(request)

            self.assertTrue(result.ok, result.to_dict())
            self.assertEqual(calls[0]["preflight_identity_profile"], "message_only")
            self.assertIsNone(calls[0]["external_intent_candidate"])
            self.assertEqual(calls[0]["message_id"], "qq:worker")
            self.assertEqual(calls[0]["platform"], "qq")
            self.assertEqual(calls[0]["session_key"], "qq:user:1")
            self.assertEqual(calls[0]["intent_timeout"], 6)

            timeout_worker = PrewarmWorker(
                config=PlatformPrewarmConfig(enabled=True),
                metrics=metrics,
                runtime_factory=lambda path: TimeoutRuntime(),
            )
            timeout = timeout_worker.process(request)
            self.assertFalse(timeout.ok)
            self.assertEqual(timeout.reason, DROP_AI_TIMEOUT)
            self.assertGreaterEqual(metrics.snapshot()["prewarm_finish_count"], 2)


if __name__ == "__main__":
    unittest.main()
