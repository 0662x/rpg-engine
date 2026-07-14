from __future__ import annotations

import shutil
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, init_database
from rpg_engine.preflight_cache import (
    PREFLIGHT_EXPIRED,
    PREFLIGHT_IDENTITY_MESSAGE_ONLY,
    PREFLIGHT_REJECTED,
    build_preflight_identity as _build_preflight_identity,
    consume_intent_preflight as _consume_intent_preflight,
    consume_intent_preflight_by_message as _consume_intent_preflight_by_message,
    consume_intent_preflight_row as _consume_intent_preflight_row,
    create_pending_intent_preflight as _create_pending_intent_preflight,
    hash_text,
    mark_intent_preflight_failed,
    mark_intent_preflight_ready,
    update_preflight_status,
)


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
TEST_ACTION_SLOT_DIGEST = "slots:test"


def _with_test_slot_digest(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"action_slot_digest": TEST_ACTION_SLOT_DIGEST, **kwargs}


def build_preflight_identity(*args: Any, **kwargs: Any) -> Any:
    return _build_preflight_identity(*args, **_with_test_slot_digest(kwargs))


def create_pending_intent_preflight(*args: Any, **kwargs: Any) -> Any:
    return _create_pending_intent_preflight(*args, **_with_test_slot_digest(kwargs))


def consume_intent_preflight(*args: Any, **kwargs: Any) -> Any:
    return _consume_intent_preflight(*args, **_with_test_slot_digest(kwargs))


def consume_intent_preflight_by_message(*args: Any, **kwargs: Any) -> Any:
    return _consume_intent_preflight_by_message(*args, **_with_test_slot_digest(kwargs))


def consume_intent_preflight_row(*args: Any, **kwargs: Any) -> Any:
    return _consume_intent_preflight_row(*args, **_with_test_slot_digest(kwargs))


def cached_rest_review() -> dict[str, object]:
    return {
        "kind": "single",
        "mode": "action",
        "action": "rest",
        "slots": {"until": "morning"},
        "plan": [],
        "confidence": "high",
        "missing_slots": [],
        "needs_confirmation": [],
        "safety_flags": [],
        "reason": "cached",
        "agreement_with_external": "agree",
        "disagreements": [],
        "external_candidate_quality": "usable",
    }


class PreflightCacheTests(unittest.TestCase):
    def copy_campaign(self, tmp: str | Path) -> Path:
        target = Path(tmp) / "campaign"
        shutil.copytree(MINIMAL_FIXTURE, target)
        init_database(load_campaign(target), force=True)
        return target

    def test_message_identity_binds_active_action_taxonomy_and_slot_digests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                default_identity = build_preflight_identity(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    action_taxonomy_digest="taxonomy:default",
                    action_slot_digest="slots:default",
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                custom_identity = build_preflight_identity(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    action_taxonomy_digest="taxonomy:custom",
                    action_slot_digest="slots:default",
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                custom_slot_identity = build_preflight_identity(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    action_taxonomy_digest="taxonomy:default",
                    action_slot_digest="slots:custom",
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:taxonomy-bound",
                    platform="qq",
                    session_key="qq:user:taxonomy-bound",
                    source_user_text_hash=hash_text("休息到早上"),
                    action_taxonomy_digest="taxonomy:default",
                    action_slot_digest="slots:default",
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                wrong_taxonomy = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:taxonomy-bound",
                    platform="qq",
                    session_key="qq:user:taxonomy-bound",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    action_taxonomy_digest="taxonomy:custom",
                    action_slot_digest="slots:default",
                )
                wrong_slots = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:taxonomy-bound",
                    platform="qq",
                    session_key="qq:user:taxonomy-bound",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    action_taxonomy_digest="taxonomy:default",
                    action_slot_digest="slots:custom",
                )
                matching_taxonomy = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:taxonomy-bound",
                    platform="qq",
                    session_key="qq:user:taxonomy-bound",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    action_taxonomy_digest="taxonomy:default",
                    action_slot_digest="slots:default",
                )

            self.assertNotEqual(default_identity.context_hash, custom_identity.context_hash)
            self.assertNotEqual(default_identity.intent_context_id, custom_identity.intent_context_id)
            self.assertNotEqual(default_identity.context_hash, custom_slot_identity.context_hash)
            self.assertNotEqual(default_identity.intent_context_id, custom_slot_identity.intent_context_id)
            self.assertEqual(wrong_taxonomy.status, "miss")
            self.assertEqual(wrong_slots.status, "miss")
            self.assertTrue(matching_taxonomy.hit)

    def test_preflight_identity_requires_action_slot_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn, self.assertRaisesRegex(
                ValueError,
                "action_slot_digest is required",
            ):
                _build_preflight_identity(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    action_slot_digest="",
                )

    def test_preflight_cache_ready_hit_is_single_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:1",
                )
                mark_intent_preflight_ready(
                    conn,
                    record.id,
                    internal_review=cached_rest_review(),
                    helper_audit={"backend": "direct"},
                )
                hit = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:1",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )
                second = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:1",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertTrue(hit.hit)
            self.assertEqual(hit.internal_review["action"], "rest")
            self.assertEqual(second.status, "used")

    def test_preflight_ids_are_unique_and_match_the_public_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                first = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                second = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )

            self.assertNotEqual(first.id, second.id)
            self.assertRegex(first.id, r"^preflight:[0-9a-f]{32}$")
            self.assertRegex(second.id, r"^preflight:[0-9a-f]{32}$")

    def test_ready_preflight_is_single_use_across_concurrent_connections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                conn.commit()

            barrier = threading.Barrier(3)
            statuses: list[str] = []
            failures: list[BaseException] = []

            def consume() -> None:
                try:
                    with connect(campaign) as conn:
                        barrier.wait()
                        result = consume_intent_preflight(
                            conn,
                            campaign,
                            "休息到早上",
                            preflight_id=record.id,
                            provider="deepseek",
                            model="deepseek-v4-flash",
                            backend="direct",
                            source_user_text_hash=record.identity.source_user_text_hash,
                        )
                        statuses.append(result.status)
                except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
                    failures.append(exc)

            threads = [threading.Thread(target=consume) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

            self.assertEqual(failures, [])
            self.assertCountEqual(statuses, ["hit", "used"])
            with connect(campaign) as conn:
                row = conn.execute(
                    "select status from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()
                late_expire = update_preflight_status(
                    conn,
                    record.id,
                    PREFLIGHT_EXPIRED,
                    reason="late expiry",
                )
            self.assertEqual(row["status"], "used")
            self.assertFalse(late_expire)

    def test_ready_consume_cas_rechecks_ttl_at_the_authoritative_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                stale_ready = conn.execute(
                    "select * from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()
                conn.execute(
                    "update intent_preflight_cache set expires_at=? where id=?",
                    ("2000-01-01T00:00:00+00:00", record.id),
                )
                result = consume_intent_preflight_row(
                    conn,
                    campaign,
                    stale_ready,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )
                row = conn.execute(
                    "select status, used_at from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            self.assertEqual(result.status, "expired")
            self.assertEqual(row["status"], "expired")
            self.assertIsNone(row["used_at"])

    def test_ready_consume_cas_loser_returns_database_rejected_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                stale_ready = conn.execute(
                    "select * from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()
                self.assertTrue(
                    update_preflight_status(conn, record.id, PREFLIGHT_REJECTED, reason="raced reject")
                )
                result = consume_intent_preflight_row(
                    conn,
                    campaign,
                    stale_ready,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "preflight is rejected")

    def test_ready_consume_rechecks_turn_after_cross_connection_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                conn.commit()
                stale_ready = conn.execute(
                    "select * from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            with connect(campaign) as other:
                other.execute(
                    "update meta set value='turn:raced' where key='current_turn_id'"
                )

            with connect(campaign) as conn:
                result = consume_intent_preflight_row(
                    conn,
                    campaign,
                    stale_ready,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )
                row = conn.execute(
                    "select status, used_at from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            self.assertEqual(result.status, "rejected")
            self.assertIn("base_turn_id", result.reason)
            self.assertEqual(row["status"], "rejected")
            self.assertIsNone(row["used_at"])

    def test_helper_identity_fields_cannot_collide_through_model_version_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="provider",
                    model="model:backend=shared",
                    backend="original",
                    fallback_backend="off",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                self.assertEqual(
                    record.identity.model_version,
                    "provider:model:backend=shared:backend=original:fallback=off",
                )
                result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="provider",
                    model="model",
                    backend="shared:backend=original",
                    fallback_backend="off",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(result.status, "rejected")
            self.assertIn(result.reason, {"model mismatch", "backend mismatch"})

    def test_message_only_creation_requires_complete_platform_identity_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            valid_hash = hash_text("ABC")
            cases = (
                {
                    "platform": "",
                    "session_key": "session:1",
                    "message_id": "message:1",
                    "source_user_text_hash": valid_hash,
                },
                {
                    "platform": "qq",
                    "session_key": "",
                    "message_id": "message:1",
                    "source_user_text_hash": valid_hash,
                },
                {
                    "platform": "qq",
                    "session_key": "session:1",
                    "message_id": "",
                    "source_user_text_hash": valid_hash,
                },
                {
                    "platform": "qq",
                    "session_key": "session:1",
                    "message_id": "message:1",
                    "source_user_text_hash": "",
                },
            )
            with connect(campaign) as conn:
                before = conn.execute("select count(*) from intent_preflight_cache").fetchone()[0]
                for identity in cases:
                    with self.subTest(identity=identity):
                        with self.assertRaisesRegex(ValueError, "message_only preflight requires"):
                            create_pending_intent_preflight(
                                conn,
                                campaign,
                                "  ＡＢＣ  ",
                                provider="deepseek",
                                model="deepseek-v4-flash",
                                backend="direct",
                                identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                                **identity,
                            )
                with self.assertRaisesRegex(ValueError, "source_user_text_hash mismatch"):
                    create_pending_intent_preflight(
                        conn,
                        campaign,
                        "  ＡＢＣ  ",
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        backend="direct",
                        source_user_text_hash=hash_text("different text"),
                        platform="qq",
                        session_key="session:1",
                        message_id="message:forged-hash",
                        identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                    )
                after = conn.execute("select count(*) from intent_preflight_cache").fetchone()[0]

            self.assertEqual(after, before)

    def test_preflight_cache_rejects_stale_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                conn.execute("update meta set value='turn:later' where key='current_turn_id'")
                result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(result.status, "rejected")
            self.assertIn("base_turn_id", result.reason)

    def test_preflight_cache_rejects_caller_supplied_hash_for_different_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:hash",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                result = consume_intent_preflight(
                    conn,
                    campaign,
                    "攻击 NPC",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:hash",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "source_user_text_hash mismatch")

    def test_preflight_cache_rejects_declared_hash_on_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                with self.assertRaisesRegex(ValueError, "source_user_text_hash mismatch"):
                    create_pending_intent_preflight(
                        conn,
                        campaign,
                        "休息到早上",
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        backend="direct",
                        source_user_text_hash=hash_text("攻击 NPC"),
                    )

    def test_preflight_cache_requires_message_platform_and_session_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:strict",
                    platform="qq",
                    session_key="qq:user:1",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.reason, "message_id mismatch")

    def test_preflight_cache_rejects_platform_and_session_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    platform="qq",
                    session_key="qq:user:1",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                platform_result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    platform="discord",
                    session_key="qq:user:1",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(platform_result.status, "rejected")
            self.assertEqual(platform_result.reason, "platform mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    platform="qq",
                    session_key="qq:user:1",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                session_result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    platform="qq",
                    session_key="qq:user:2",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(session_result.status, "rejected")
            self.assertEqual(session_result.reason, "session_key mismatch")

    def test_preflight_cache_rejects_backend_fallback_and_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                external = {
                    "kind": "single",
                    "mode": "action",
                    "action": "rest",
                    "slots": {"until": "morning"},
                    "confidence": "high",
                }
                rule = {
                    "kind": "single",
                    "mode": "action",
                    "action": "rest",
                    "slots": {"until": "morning"},
                    "confidence": "medium",
                }
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="hermes_z",
                    fallback_backend="off",
                    external_candidate=external,
                    rule_candidate=rule,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                backend_result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="off",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    external_candidate=external,
                    rule_candidate=rule,
                )

            self.assertEqual(backend_result.status, "rejected")
            self.assertEqual(backend_result.reason, "backend mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="hermes_z",
                    external_candidate=external,
                    rule_candidate=rule,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                fallback_result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="off",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    external_candidate=external,
                    rule_candidate=rule,
                )

            self.assertEqual(fallback_result.status, "rejected")
            self.assertEqual(fallback_result.reason, "fallback_backend mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="off",
                    external_candidate=external,
                    rule_candidate=rule,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                candidate_result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="off",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    external_candidate={**external, "action": "travel"},
                    rule_candidate=rule,
                )

            self.assertEqual(candidate_result.status, "rejected")
            self.assertEqual(candidate_result.reason, "external_candidate_hash mismatch")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="off",
                    external_candidate=external,
                    rule_candidate=rule,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                rule_result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    fallback_backend="off",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    external_candidate=external,
                    rule_candidate={**rule, "action": "travel"},
                )

            self.assertEqual(rule_result.status, "rejected")
            self.assertEqual(rule_result.reason, "rule_candidate_hash mismatch")

    def test_preflight_cache_rejects_provider_and_model_mismatch(self) -> None:
        for field, replacement in (("provider", "other-provider"), ("model", "other-model")):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as tmp:
                    campaign = load_campaign(self.copy_campaign(tmp))
                    with connect(campaign) as conn:
                        record = create_pending_intent_preflight(
                            conn,
                            campaign,
                            "休息到早上",
                            provider="deepseek",
                            model="deepseek-v4-flash",
                            backend="direct",
                        )
                        mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                        kwargs = {
                            "provider": "deepseek",
                            "model": "deepseek-v4-flash",
                            "backend": "direct",
                        }
                        kwargs[field] = replacement
                        result = consume_intent_preflight(
                            conn,
                            campaign,
                            "休息到早上",
                            preflight_id=record.id,
                            source_user_text_hash=record.identity.source_user_text_hash,
                            **kwargs,
                        )

                    self.assertEqual(result.status, "rejected")
                    self.assertEqual(result.reason, f"{field} mismatch")

    def test_candidate_bound_rejects_save_context_schema_and_task_mismatch(self) -> None:
        fields = (
            "save_id",
            "context_hash",
            "intent_context_id",
            "schema_version",
            "task_version",
        )
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                campaign = load_campaign(self.copy_campaign(tmp))
                with connect(campaign) as conn:
                    record = create_pending_intent_preflight(
                        conn,
                        campaign,
                        "休息到早上",
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        backend="direct",
                    )
                    mark_intent_preflight_ready(
                        conn,
                        record.id,
                        internal_review=cached_rest_review(),
                    )
                    conn.execute(
                        f"update intent_preflight_cache set {field}=? where id=?",
                        (f"mismatch:{field}", record.id),
                    )
                    result = consume_intent_preflight(
                        conn,
                        campaign,
                        "休息到早上",
                        preflight_id=record.id,
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        backend="direct",
                        source_user_text_hash=record.identity.source_user_text_hash,
                    )
                    row = conn.execute(
                        "select status, used_at from intent_preflight_cache where id=?",
                        (record.id,),
                    ).fetchone()

                self.assertEqual(result.status, "rejected")
                self.assertEqual(result.reason, f"{field} mismatch")
                self.assertEqual(row["status"], "rejected")
                self.assertIsNone(row["used_at"])

    def test_preflight_cache_reports_expired_and_failed_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                conn.execute(
                    "update intent_preflight_cache set expires_at=? where id=?",
                    ("2000-01-01T00:00:00+00:00", record.id),
                )
                expired = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(expired.status, "expired")
            self.assertEqual(expired.reason, "preflight expired")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                self.assertEqual(mark_intent_preflight_failed(conn, record.id, error="timeout"), "failed")
                failed = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )

            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.reason, "preflight is failed")

        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                conn.execute(
                    "update intent_preflight_cache set expires_at=? where id=?",
                    ("2000-01-01T00:00:00+00:00", record.id),
                )
                final_status = mark_intent_preflight_failed(conn, record.id, error="ai timed out")
                row = conn.execute(
                    "select status from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            self.assertEqual(final_status, "expired")
            self.assertEqual(row["status"], "expired")

    def test_late_reject_transition_cannot_overwrite_used_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                hit = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )
                late_reject = update_preflight_status(conn, record.id, PREFLIGHT_REJECTED, reason="late mismatch")
                row = conn.execute("select status from intent_preflight_cache where id=?", (record.id,)).fetchone()

            self.assertTrue(hit.hit)
            self.assertFalse(late_reject)
            self.assertEqual(row["status"], "used")

    def test_preflight_cache_ready_transition_is_pending_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                self.assertEqual(
                    mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review()),
                    "ready",
                )
                self.assertEqual(
                    mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review()),
                    "ready",
                )

    def test_expired_late_ready_returns_final_status_without_storing_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                conn.execute(
                    "update intent_preflight_cache set expires_at=? where id=?",
                    ("2000-01-01T00:00:00+00:00", record.id),
                )
                final_status = mark_intent_preflight_ready(
                    conn,
                    record.id,
                    internal_review=cached_rest_review(),
                )
                row = conn.execute(
                    "select status, internal_review_json from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            self.assertEqual(final_status, "expired")
            self.assertEqual(row["status"], "expired")
            self.assertEqual(row["internal_review_json"], "{}")

    def test_expired_transition_lost_race_returns_database_final_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            for transition, raced_status in (("ready", "failed"), ("failed", "ready")):
                with self.subTest(transition=transition, raced_status=raced_status):
                    with connect(campaign) as conn:
                        record = create_pending_intent_preflight(
                            conn,
                            campaign,
                            f"休息到早上 {transition}",
                            provider="deepseek",
                            model="deepseek-v4-flash",
                            backend="direct",
                        )
                        conn.execute(
                            "update intent_preflight_cache set expires_at=? where id=?",
                            ("2000-01-01T00:00:00+00:00", record.id),
                        )

                        def lose_expire_race(*args: object, **kwargs: object) -> bool:
                            conn.execute(
                                "update intent_preflight_cache set status=? where id=?",
                                (raced_status, record.id),
                            )
                            return False

                        with patch(
                            "rpg_engine.preflight_cache.update_preflight_status",
                            side_effect=lose_expire_race,
                        ):
                            final_status = (
                                mark_intent_preflight_ready(
                                    conn,
                                    record.id,
                                    internal_review=cached_rest_review(),
                                )
                                if transition == "ready"
                                else mark_intent_preflight_failed(conn, record.id, error="timeout")
                            )

                    self.assertEqual(final_status, raced_status)

    def test_message_only_preflight_consumes_by_message_with_later_external_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "confidence": "high",
            }
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:message-only",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                hit = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:message-only",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    external_candidate=external,
                    rule_candidate={"kind": "single", "mode": "action", "action": "rest", "slots": {}},
                )

            self.assertTrue(hit.hit)
            assert hit.record is not None
            self.assertEqual(hit.record.identity.identity_profile, PREFLIGHT_IDENTITY_MESSAGE_ONLY)
            self.assertEqual(hit.record.identity.external_candidate_hash, "")
            self.assertEqual(hit.internal_review["action"], "rest")
            trace = hit.to_trace()
            self.assertNotIn("session_key", trace["record"])
            self.assertEqual(trace["record"]["session_key_hash"], hash_text("qq:user:1"))

    def test_message_only_preflight_strips_external_candidate_at_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
            }
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:external-first",
                    platform="qq",
                    session_key="qq:user:1",
                    external_candidate=external,
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                row = conn.execute(
                    "select external_candidate_hash, external_candidate_json from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            self.assertEqual(record.identity.external_candidate_hash, "")
            self.assertEqual(row["external_candidate_hash"], "")
            self.assertEqual(row["external_candidate_json"], "{}")

    def test_message_lookup_rejects_duplicate_ready_preflights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                for _ in range(2):
                    record = create_pending_intent_preflight(
                        conn,
                        campaign,
                        "休息到早上",
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        backend="direct",
                        message_id="qq:dupe",
                        platform="qq",
                        session_key="qq:user:1",
                        source_user_text_hash=hash_text("休息到早上"),
                        identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                    )
                    mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                result = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:dupe",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                )

            self.assertEqual(result.status, "ambiguous")

    def test_message_lookup_rechecks_duplicates_after_pending_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            text_hash = hash_text("休息到早上")
            with connect(campaign) as conn:
                first = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:wait-race-dupe",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=text_hash,
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                conn.commit()
                duplicate_id = ""

                def insert_duplicate(*_args: object, **_kwargs: object) -> sqlite3.Row | None:
                    nonlocal duplicate_id
                    with connect(campaign) as other:
                        duplicate = create_pending_intent_preflight(
                            other,
                            campaign,
                            "休息到早上",
                            provider="deepseek",
                            model="deepseek-v4-flash",
                            backend="direct",
                            message_id="qq:wait-race-dupe",
                            platform="qq",
                            session_key="qq:user:1",
                            source_user_text_hash=text_hash,
                            identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                        )
                        duplicate_id = duplicate.id
                        mark_intent_preflight_ready(
                            other,
                            duplicate.id,
                            internal_review=cached_rest_review(),
                        )
                    return conn.execute(
                        "select * from intent_preflight_cache where id=?",
                        (first.id,),
                    ).fetchone()

                with patch(
                    "rpg_engine.preflight_cache.wait_for_preflight_ready",
                    side_effect=insert_duplicate,
                ):
                    result = consume_intent_preflight_by_message(
                        conn,
                        campaign,
                        "休息到早上",
                        provider="deepseek",
                        model="deepseek-v4-flash",
                        backend="direct",
                        message_id="qq:wait-race-dupe",
                        platform="qq",
                        session_key="qq:user:1",
                        source_user_text_hash=text_hash,
                        pending_wait_ms=1,
                    )
                rows = conn.execute(
                    "select id, status, used_at from intent_preflight_cache where id in (?, ?) order by id",
                    (first.id, duplicate_id),
                ).fetchall()

            self.assertEqual(result.status, "ambiguous")
            self.assertCountEqual([row["status"] for row in rows], ["pending", "ready"])
            self.assertTrue(all(row["used_at"] is None for row in rows))

    def test_pending_preflight_expires_before_bypass_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                )
                conn.execute(
                    "update intent_preflight_cache set expires_at='2000-01-01T00:00:00+00:00' where id=?",
                    (record.id,),
                )
                result = consume_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    preflight_id=record.id,
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    pending_wait_ms=10,
                )
                row = conn.execute("select status, rejected_reason from intent_preflight_cache where id=?", (record.id,)).fetchone()

            self.assertEqual(result.status, PREFLIGHT_EXPIRED)
            self.assertEqual(row["status"], PREFLIGHT_EXPIRED)
            self.assertEqual(row["rejected_reason"], "expired")

    def test_expired_message_preflight_does_not_hide_new_active_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                expired = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:retry",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                conn.execute(
                    "update intent_preflight_cache set expires_at='2000-01-01T00:00:00+00:00' where id=?",
                    (expired.id,),
                )
                active = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:retry",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                mark_intent_preflight_ready(conn, active.id, internal_review=cached_rest_review())
                hit = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:retry",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=active.identity.source_user_text_hash,
                )
                expired_row = conn.execute("select status from intent_preflight_cache where id=?", (expired.id,)).fetchone()

            self.assertTrue(hit.hit)
            assert hit.record is not None
            self.assertEqual(hit.record.id, active.id)
            self.assertEqual(expired_row["status"], PREFLIGHT_EXPIRED)

    def test_pending_message_preflight_bypasses_and_late_ready_is_unused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:pending",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                pending = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:pending",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    pending_wait_ms=10,
                )
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                row = conn.execute(
                    "select status, rejected_reason, bypassed_at, late_ready_unused_at from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()

            self.assertEqual(pending.status, "pending")
            self.assertEqual(row["status"], "rejected")
            self.assertEqual(row["rejected_reason"], "late_ready_unused")
            self.assertTrue(row["bypassed_at"])
            self.assertTrue(row["late_ready_unused_at"])

    def test_bypassed_pending_message_preflight_is_ignored_by_later_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                bypassed = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:bypassed",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                pending = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:bypassed",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=bypassed.identity.source_user_text_hash,
                    pending_wait_ms=1,
                )
                active = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:bypassed",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                mark_intent_preflight_ready(conn, active.id, internal_review=cached_rest_review())
                hit = consume_intent_preflight_by_message(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:bypassed",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=active.identity.source_user_text_hash,
                )

            self.assertEqual(pending.status, "pending")
            self.assertTrue(hit.hit)
            assert hit.record is not None
            self.assertEqual(hit.record.id, active.id)

    def test_pending_bypass_lost_race_reloads_ready_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(self.copy_campaign(tmp))
            with connect(campaign) as conn:
                record = create_pending_intent_preflight(
                    conn,
                    campaign,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:ready-race",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=hash_text("休息到早上"),
                    identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                )
                stale_pending = conn.execute("select * from intent_preflight_cache where id=?", (record.id,)).fetchone()
                mark_intent_preflight_ready(conn, record.id, internal_review=cached_rest_review())
                hit = consume_intent_preflight_row(
                    conn,
                    campaign,
                    stale_pending,
                    "休息到早上",
                    provider="deepseek",
                    model="deepseek-v4-flash",
                    backend="direct",
                    message_id="qq:ready-race",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=record.identity.source_user_text_hash,
                )
                row = conn.execute("select status, bypassed_at from intent_preflight_cache where id=?", (record.id,)).fetchone()

            self.assertTrue(hit.hit)
            self.assertEqual(row["status"], "used")
            self.assertFalse(row["bypassed_at"])


if __name__ == "__main__":
    unittest.main()
