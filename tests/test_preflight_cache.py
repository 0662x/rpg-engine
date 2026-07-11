from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, init_database
from rpg_engine.preflight_cache import (
    PREFLIGHT_EXPIRED,
    PREFLIGHT_IDENTITY_MESSAGE_ONLY,
    PREFLIGHT_REJECTED,
    consume_intent_preflight_by_message,
    consume_intent_preflight_row,
    consume_intent_preflight,
    create_pending_intent_preflight,
    hash_text,
    mark_intent_preflight_failed,
    mark_intent_preflight_ready,
    update_preflight_status,
)


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


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
            self.assertEqual(backend_result.reason, "model_version mismatch")

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
            self.assertEqual(fallback_result.reason, "model_version mismatch")

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
