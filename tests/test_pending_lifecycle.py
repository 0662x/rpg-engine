from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rpg_engine.game_session import hash_identity
from rpg_engine.mcp_adapter import AIGMMCPAdapter, MCPAdapterConfig
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import (
    CONFIRMATION_CLAIM_META_KEY,
    CONFIRMATION_HISTORY_ORDER_META_KEY,
    CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,
    CONFIRMATION_RECEIPT_HISTORY_META_PREFIX,
    CONFIRMATION_RECEIPT_META_KEY,
    DEFAULT_PENDING_ACTION_TTL_SECONDS,
    MAX_PENDING_STRING_LENGTH,
    MAX_REGISTRY_STATE_BYTES,
    SaveManager,
    SaveManagerError,
    confirmation_claim_lock,
    confirmation_lock_held_by_current_thread,
    remove_created_directory_if_unchanged,
    process_file_lock,
    registry_file_matches,
    registry_parent_matches,
    stable_payload_digest,
    unlink_anchored_file,
)
from tests.helpers import consensus_candidate, tree_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def result_object(data: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(to_dict=lambda: dict(data))


def gameplay_snapshot(save_path: Path) -> dict[str, object]:
    database = save_path / "data" / "game.sqlite"
    conn = sqlite3.connect(database)
    try:
        tables = tuple(
            str(row[0])
            for row in conn.execute(
                """
                select name
                from sqlite_master
                where type = 'table' and name not like 'sqlite_%'
                order by name
                """
            ).fetchall()
        )
        schemas = {
            table: str(
                conn.execute(
                    "select coalesce(sql, '') from sqlite_master where type = 'table' and name = ?",
                    (table,),
                ).fetchone()[0]
            )
            for table in tables
        }
        rows = {
            table: tuple(sorted((tuple(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()), key=repr))
            for table in tables
        }
    finally:
        conn.close()
    projections = {
        relative: (save_path / relative).read_bytes()
        for relative in (
            "data/events.jsonl",
            "save.yaml",
            "snapshots/current.json",
            "snapshots/current.md",
            "cards/current.md",
        )
        if (save_path / relative).is_file()
    }
    return {"schemas": schemas, "rows": rows, "projections": projections}


def clarification_runtime(question: str = "你具体指哪个目标？") -> SimpleNamespace:
    return SimpleNamespace(
        act=lambda *_args, **_kwargs: result_object(
            {
                "ok": False,
                "status": "needs_clarification",
                "action": "act",
                "interpretation": {
                    "intent": {
                        "clarification": {
                            "question": question,
                            "options": ["第一个", "第二个"],
                        }
                    }
                },
                "repair_options": [],
                "warnings": [],
                "errors": [],
            }
        )
    )


def ready_runtime(command_id: str = "cmd:pending-lifecycle") -> SimpleNamespace:
    return SimpleNamespace(
        act=lambda *_args, **_kwargs: result_object(
            {
                "ok": True,
                "status": "ready",
                "action": "rest",
                "ready_to_save": True,
                "delta_draft": {"command_id": command_id, "events": [], "upsert_entities": []},
                "turn_proposal": {"proposal_id": f"proposal:{command_id}"},
                "warnings": [],
                "errors": [],
            }
        )
    )


def mismatch_clarification_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        act=lambda *_args, **_kwargs: result_object(
            {
                "ok": False,
                "status": "needs_clarification",
                "action": "act",
                "interpretation": {
                    "intent": {
                        "source": "ai_disagreement",
                        "agreement_with_external": "disagree",
                        "external_candidate_quality": "wrong_action",
                        "clarification": {"question": "候选动作是否应改为休息？"},
                    }
                },
                "repair_options": [],
                "warnings": [],
                "errors": [],
            }
        )
    )


class PendingLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.campaign_path = self.root / "campaigns" / "minimal"
        shutil.copytree(MINIMAL_FIXTURE, self.campaign_path)
        self.source_digest = tree_digest(self.campaign_path)
        self.manager = SaveManager(self.root, default_campaign="campaigns/minimal")
        self.started = self.manager.start_or_continue(campaign="campaigns/minimal")
        self.save_path = self.root / str(self.started["save"]["path"])

    def tearDown(self) -> None:
        self.assertEqual(tree_digest(self.campaign_path), self.source_digest)
        self.temporary.cleanup()

    def assert_lifecycle(self, result: dict[str, object], *, state: str, kind: str) -> dict[str, object]:
        lifecycle = result.get("lifecycle")
        self.assertIsInstance(lifecycle, dict, result)
        assert isinstance(lifecycle, dict)
        self.assertEqual(lifecycle.get("state"), state, result)
        self.assertEqual(lifecycle.get("kind"), kind, result)
        return lifecycle

    def test_existing_action_without_expected_token_conflicts_and_preserves_session(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        second = self.manager.player_turn(user_text="休息到早上")

        self.assertFalse(second["ok"], second)
        self.assertEqual(second["status"], "pending_conflict", second)
        lifecycle = self.assert_lifecycle(second, state="conflict", kind="action")
        self.assertEqual(lifecycle.get("pending_id"), first["session_id"])
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_matching_expected_token_supersedes_same_identity_action(self) -> None:
        first = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:one",
            actor_id="player:one",
        )

        second = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=str(first["session_id"]),
            platform="qq",
            session_key="room:one",
            actor_id="player:one",
        )

        self.assertTrue(second["ready_to_confirm"], second)
        self.assertNotEqual(second["session_id"], first["session_id"])
        self.assert_lifecycle(second, state="superseded", kind="action")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        self.assertEqual(pending["session_id"], second["session_id"])
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_noncanonical_action_compare_and_cancel_tokens_preserve_pending(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)
        noncanonical = f" {first['session_id']} "

        supersede = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=noncanonical,
        )
        canceled = self.manager.player_cancel(noncanonical)

        self.assertFalse(supersede["ok"], supersede)
        self.assertEqual(supersede["status"], "pending_conflict")
        self.assertFalse(canceled["ok"], canceled)
        self.assertEqual(canceled["status"], "invalid_state")
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_claimed_action_cannot_be_superseded_before_confirmation_recovery(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        claimed = self.manager.prepare_pending_confirmation_claim(
            pending,
            save=dict(self.started["save"]),
        )
        before_pending = self.manager.pending_action_path().read_bytes()
        before_facts = gameplay_snapshot(self.save_path)

        supersede = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=str(first["session_id"]),
        )

        self.assertFalse(supersede["ok"], supersede)
        self.assertEqual(supersede["status"], "invalid_state")
        self.assert_lifecycle(supersede, state="invalid_state", kind="action")
        self.assertEqual(self.manager.pending_action_path().read_bytes(), before_pending)
        self.assertEqual(self.manager.read_pending_action(), claimed)
        self.assertEqual(gameplay_snapshot(self.save_path), before_facts)

    def test_expired_claimed_action_preserves_recovery_evidence(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        claimed = self.manager.prepare_pending_confirmation_claim(
            pending,
            save=dict(self.started["save"]),
        )
        expired = {
            **claimed,
            "created_at": "1999-12-31T23:30:00+00:00",
            "expires_at": "2000-01-01T00:00:00+00:00",
        }
        self.manager.write_pending_action(expired)
        before_pending = self.manager.pending_action_path().read_bytes()
        before_facts = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "requires confirmation recovery"):
            self.manager.player_confirm(str(first["session_id"]))

        self.assertEqual(self.manager.pending_action_path().read_bytes(), before_pending)
        self.assertEqual(gameplay_snapshot(self.save_path), before_facts)

    def test_noncanonical_claim_digest_and_anchor_cannot_confirm(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        claimed = self.manager.prepare_pending_confirmation_claim(
            pending,
            save=dict(self.started["save"]),
        )
        tampered_claim = dict(claimed["confirmation_claim"])
        tampered_claim["claim_digest"] = f" {tampered_claim['claim_digest']} "
        self.manager.write_pending_action({**claimed, "confirmation_claim": tampered_claim})
        before_pending = self.manager.pending_action_path().read_bytes()
        before_facts = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "integrity validation"):
            self.manager.player_confirm(str(first["session_id"]))
        self.assertEqual(self.manager.pending_action_path().read_bytes(), before_pending)
        self.assertEqual(gameplay_snapshot(self.save_path), before_facts)

        self.manager.write_pending_action(claimed)
        claim_digest = str(claimed["confirmation_claim"]["claim_digest"])
        with sqlite3.connect(self.save_path / "data" / "game.sqlite") as conn:
            conn.execute(
                "update meta set value = ? where key = ?",
                (f" {claim_digest} ", CONFIRMATION_CLAIM_META_KEY),
            )
            conn.commit()
        anchor_before = gameplay_snapshot(self.save_path)
        with self.assertRaisesRegex(SaveManagerError, "SQLite claim anchor"):
            self.manager.player_confirm(str(first["session_id"]))
        self.assertEqual(self.manager.read_pending_action(), claimed)
        self.assertEqual(gameplay_snapshot(self.save_path), anchor_before)

    def test_claim_anchor_only_crash_window_cannot_be_superseded(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        with mock.patch.object(self.manager, "write_pending_action", side_effect=OSError("claim publish failed")):
            with self.assertRaisesRegex(OSError, "claim publish failed"):
                self.manager.prepare_pending_confirmation_claim(
                    pending,
                    save=dict(self.started["save"]),
                )
        self.assertNotIn("confirmation_claim", self.manager.read_pending_action() or {})
        before_pending = self.manager.pending_action_path().read_bytes()
        before_facts = gameplay_snapshot(self.save_path)

        supersede = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=str(first["session_id"]),
        )

        self.assertFalse(supersede["ok"], supersede)
        self.assertEqual(supersede["status"], "invalid_state")
        self.assert_lifecycle(supersede, state="invalid_state", kind="action")
        self.assertEqual(self.manager.pending_action_path().read_bytes(), before_pending)
        self.assertEqual(gameplay_snapshot(self.save_path), before_facts)

    def test_cross_identity_supersede_conflict_is_private_and_non_mutating(self) -> None:
        private_text = "PRIVATE_PENDING_ORIGINAL_ALPHA"
        first = self.manager.player_turn(
            user_text=private_text,
            external_intent_candidate=consensus_candidate(
                "rest",
                {"until": "morning"},
                reason="synthetic external candidate for owner conflict",
            ),
            platform="qq",
            session_key="private:session:alpha",
            actor_id="private:actor:alpha",
        )
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        conflict = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=str(first["session_id"]),
            platform="qq",
            session_key="private:session:alpha",
            actor_id="private:actor:other",
        )

        self.assertFalse(conflict["ok"], conflict)
        self.assertEqual(conflict["status"], "pending_conflict", conflict)
        lifecycle = self.assert_lifecycle(conflict, state="conflict", kind="action")
        self.assertNotIn("pending_id", lifecycle)
        public_text = json.dumps(conflict, ensure_ascii=False, sort_keys=True)
        for forbidden in (
            str(first["session_id"]),
            private_text,
            "private:session:alpha",
            "private:actor:alpha",
            "morning",
        ):
            self.assertNotIn(forbidden, public_text)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_partial_platform_session_identity_is_rejected_before_publication(self) -> None:
        facts_before = gameplay_snapshot(self.save_path)
        registry_before = self.manager.registry_path.read_bytes()

        for identity in ({"platform": "qq"}, {"session_key": "room:partial"}):
            with self.subTest(identity=identity):
                result = self.manager.player_turn(user_text="休息到早上", **identity)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["status"], "invalid_state")
                self.assertEqual(result["lifecycle"], {"state": "invalid_state", "kind": "unknown"})
                self.assertIsNone(self.manager.read_pending_action())
                self.assertIsNone(self.manager.read_pending_clarification())

        with self.assertRaisesRegex(SaveManagerError, "provided together"):
            self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": "哪一个？"},
                platform="qq",
            )
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)
        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)

    def test_tampered_identity_binding_and_noncanonical_owner_token_fail_closed(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        cases = (
            {"platform": "qq"},
            {"session_key_hash": "a" * 64},
            {"session_id": 7},
            {"session_id": f" {acted['session_id']} "},
            {"save_id": f" {pending['save_id']} "},
            {"save_path": f" {pending['save_path']} "},
        )
        for mutation in cases:
            with self.subTest(mutation=mutation):
                tampered = {**pending, **mutation}
                self.manager.write_pending_action(tampered)
                before = self.manager.pending_action_path().read_bytes()

                with self.assertRaisesRegex(
                    SaveManagerError,
                    "incomplete platform identity|invalid owner token|identity is incomplete",
                ):
                    self.manager.inspect_pending()

                self.assertEqual(self.manager.pending_action_path().read_bytes(), before)

    def test_query_preserves_existing_action_without_supersede_token(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()

        queried = self.manager.player_turn(user_text="查看周围")

        self.assertTrue(queried["ok"], queried)
        self.assertEqual(queried["action"], "query", queried)
        self.assertFalse(queried["ready_to_confirm"], queried)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.read_pending_action()["session_id"], first["session_id"])

    def test_clarification_records_ttl_origin_and_cancel_writes_no_gameplay_facts(self) -> None:
        facts_before = gameplay_snapshot(self.save_path)
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            result = self.manager.player_turn(user_text="使用那个物品")

        clarification_id = str(result["pending_clarification_id"])
        pending = self.manager.read_pending_clarification()
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending["schema_version"], "1")
        self.assertEqual(pending["clarification_id"], clarification_id)
        self.assertEqual(pending["save_id"], self.started["save"]["id"])
        self.assertEqual(pending["save_path"], self.started["save"]["path"])
        self.assertEqual(pending["ttl_seconds"], DEFAULT_PENDING_ACTION_TTL_SECONDS)
        self.assertEqual(pending["clarification_origin"], "player_input_ambiguity")
        self.assertEqual(pending["original_user_text"], "使用那个物品")
        created_at = datetime.fromisoformat(str(pending["created_at"]))
        expires_at = datetime.fromisoformat(str(pending["expires_at"]))
        self.assertEqual(int((expires_at - created_at).total_seconds()), DEFAULT_PENDING_ACTION_TTL_SECONDS)
        inspected = self.manager.inspect_pending()
        self.assert_lifecycle(inspected, state="active", kind="clarification")

        canceled = self.manager.player_cancel(clarification_id)

        self.assertTrue(canceled["ok"], canceled)
        self.assert_lifecycle(canceled, state="canceled", kind="clarification")
        self.assertFalse(self.manager.pending_clarification_path().exists())
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)
        terminal = self.manager.player_cancel(clarification_id)
        self.assert_lifecycle(terminal, state="not_found", kind="clarification")

    def test_adapter_restart_gates_low_level_tools_from_canonical_clarification(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])

        restarted = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                default_save=str(self.started["save"]["path"]),
                mcp_profile="developer",
            )
        )
        low_level_runtime = SimpleNamespace(
            preflight_intent=lambda *_args, **_kwargs: result_object(
                {
                    "ok": True,
                    "status": "ready",
                    "errors": [],
                }
            )
        )
        with mock.patch.object(restarted, "runtime_for_save", return_value=low_level_runtime):
            blocked = restarted.intent_preflight("休息到早上", intent_backend="off")

        self.assertFalse(blocked["ok"], blocked)
        self.assertIn("clarification", " ".join(blocked["errors"]).lower())
        persisted = self.manager.inspect_pending()
        lifecycle = self.assert_lifecycle(persisted, state="active", kind="clarification")
        self.assertEqual(lifecycle.get("pending_id"), clarification_id)
        self.assertFalse(hasattr(restarted, "pending_clarifications"))

    def test_explicit_save_low_level_gate_survives_missing_active_registry_save(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        registry = self.manager.read_registry()
        registry["active_save_id"] = None
        self.manager.write_registry(registry)
        restarted = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="developer",
            )
        )
        reached_runtime = False

        def preflight(*_args: object, **_kwargs: object) -> SimpleNamespace:
            nonlocal reached_runtime
            reached_runtime = True
            return result_object({"ok": True, "status": "ready", "errors": []})

        low_level_runtime = SimpleNamespace(preflight_intent=preflight)
        with mock.patch.object(restarted, "runtime_for_save", return_value=low_level_runtime):
            blocked = restarted.intent_preflight(
                "休息到早上",
                save=str(self.started["save"]["path"]),
                intent_backend="off",
            )

        self.assertFalse(blocked["ok"], blocked)
        self.assertIn("clarification", " ".join(blocked["errors"]).lower())
        self.assertFalse(reached_runtime)

    def test_switch_save_reports_preserved_and_keeps_original_binding(self) -> None:
        first_save = dict(self.started["save"])
        acted = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)

        switched = self.manager.switch_save(str(second["save"]["id"]), refresh=False)

        self.assertEqual(switched["active_save_id"], second["save"]["id"])
        lifecycle = self.assert_lifecycle(switched, state="preserved", kind="action")
        self.assertEqual(lifecycle.get("save_id"), first_save["id"])
        self.assertNotIn("pending_id", lifecycle)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        pending = self.manager.read_pending_action()
        self.assertEqual(pending["session_id"], acted["session_id"])
        self.assertEqual(pending["save_id"], first_save["id"])
        self.assertEqual(pending["save_path"], first_save["path"])

    def test_switch_save_reports_claimed_action_as_preserved(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        claimed = self.manager.prepare_pending_confirmation_claim(
            pending,
            save=dict(self.started["save"]),
        )
        before = gameplay_snapshot(self.save_path)
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)

        switched = self.manager.switch_save(str(second["save"]["id"]), refresh=False)

        self.assertTrue(switched["ok"], switched)
        self.assert_lifecycle(switched, state="preserved", kind="action")
        self.assertEqual(self.manager.read_pending_action(), claimed)
        self.assertEqual(self.manager.read_pending_action()["session_id"], acted["session_id"])
        self.assertEqual(gameplay_snapshot(self.save_path), before)

    def test_delayed_replay_uses_bounded_history_after_new_pending_publication(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        confirmed = self.manager.player_confirm(str(first["session_id"]))
        self.assertEqual(confirmed["write_status"], "committed", confirmed)
        second = self.manager.player_turn(user_text="休息到早上")
        second_pending_before = self.manager.pending_action_path().read_bytes()
        facts_before_replay = gameplay_snapshot(self.save_path)

        delayed = self.manager.player_confirm(str(first["session_id"]))

        self.assertEqual(delayed["write_status"], "already_confirmed", delayed)
        self.assertTrue(delayed["idempotent_replay"], delayed)
        self.assertFalse(delayed["saved"], delayed)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before_replay)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), second_pending_before)
        self.assertEqual(self.manager.read_pending_action()["session_id"], second["session_id"])

    def test_noncanonical_confirm_token_cannot_commit_or_replay(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)
        for invalid_token in (f" {first['session_id']} ", 7):
            with self.subTest(active_token=invalid_token):
                with self.assertRaisesRegex(SaveManagerError, "exact canonical string"):
                    self.manager.player_confirm(invalid_token)  # type: ignore[arg-type]
                self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
                self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

        self.manager.player_confirm(str(first["session_id"]))
        second = self.manager.player_turn(user_text="休息到早上")
        replay_before = gameplay_snapshot(self.save_path)
        pending_replay_before = self.manager.pending_action_path().read_bytes()
        history_before = self.manager.confirmation_history_path().read_bytes()

        with self.assertRaisesRegex(SaveManagerError, "exact canonical string"):
            self.manager.player_confirm(f" {first['session_id']} ")

        self.assertEqual(gameplay_snapshot(self.save_path), replay_before)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_replay_before)
        self.assertEqual(self.manager.read_pending_action()["session_id"], second["session_id"])
        self.assertEqual(self.manager.confirmation_history_path().read_bytes(), history_before)

    def test_noncanonical_receipt_digest_cannot_replay(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        receipt = self.manager.read_confirmation_receipt()
        self.assertIsNotNone(receipt)
        assert receipt is not None
        receipt["receipt_digest"] = f" {receipt['receipt_digest']} "
        self.manager.write_confirmation_receipt(receipt)
        receipt_before = self.manager.confirmation_receipt_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "invalid digest"):
            self.manager.player_confirm(str(first["session_id"]))

        self.assertEqual(self.manager.confirmation_receipt_path().read_bytes(), receipt_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_noncanonical_receipt_session_hash_cannot_replay(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        receipt = self.manager.read_confirmation_receipt()
        self.assertIsNotNone(receipt)
        assert receipt is not None
        canonical_hash = str(receipt["confirmation_session_hash"])
        receipt["confirmation_session_hash"] = f" {canonical_hash} "
        receipt["receipt_digest"] = stable_payload_digest(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
        self.manager.write_confirmation_receipt(receipt)
        receipt_before = self.manager.confirmation_receipt_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "invalid confirmation_session_hash|invalid session identity"):
            self.manager.player_confirm(str(first["session_id"]))

        self.assertEqual(self.manager.confirmation_receipt_path().read_bytes(), receipt_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_noncanonical_receipt_authority_scalars_cannot_replay(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        receipt = self.manager.read_confirmation_receipt()
        self.assertIsNotNone(receipt)
        assert receipt is not None
        cases = (
            {"save_id": f" {receipt['save_id']} "},
            {"save_path": f" {receipt['save_path']} "},
            {"command_id": f" {receipt['command_id']} "},
            {"turn_id": f" {receipt['turn_id']} "},
            {"command_hash": f" {receipt['command_hash']} "},
            {"delta_digest": f" {receipt['delta_digest']} "},
            {"proposal_digest": f" {receipt['proposal_digest']} "},
            {"platform_hash": " "},
            {"session_key_hash": " "},
            {"actor_id_hash": " "},
            {"projection_status": " clean "},
            {"event_count": True},
            {"write_status": "committed"},
        )
        facts_before = gameplay_snapshot(self.save_path)
        for mutation in cases:
            with self.subTest(mutation=mutation):
                tampered = {**receipt, **mutation}
                tampered["receipt_digest"] = stable_payload_digest(
                    {key: value for key, value in tampered.items() if key != "receipt_digest"}
                )
                self.manager.write_confirmation_receipt(tampered)
                receipt_before = self.manager.confirmation_receipt_path().read_bytes()

                with self.assertRaisesRegex(SaveManagerError, "invalid|incomplete"):
                    self.manager.player_confirm(str(first["session_id"]))

                self.assertEqual(self.manager.confirmation_receipt_path().read_bytes(), receipt_before)
                self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_noncanonical_historical_receipt_authority_cannot_replay(self) -> None:
        first = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:history",
            actor_id="actor:history",
        )
        self.manager.player_confirm(
            str(first["session_id"]),
            platform="qq",
            session_key="room:history",
            actor_id="actor:history",
        )
        second = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:history",
            actor_id="actor:history",
        )
        history_path = self.manager.confirmation_history_path()
        envelope = json.loads(history_path.read_text(encoding="utf-8"))
        receipt = dict(envelope["receipts"][0])
        receipt["session_key_hash"] = f" {receipt['session_key_hash']} "
        receipt["receipt_digest"] = stable_payload_digest(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
        envelope["receipts"] = [receipt]
        envelope["order_digest"] = stable_payload_digest(
            {"schema_version": "1", "receipt_digests": [receipt["receipt_digest"]]}
        )
        history_path.write_text(json.dumps(envelope), encoding="utf-8")
        history_before = history_path.read_bytes()
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "invalid identity evidence"):
            self.manager.player_confirm(
                str(first["session_id"]),
                platform="qq",
                session_key="room:history",
                actor_id="actor:history",
            )

        self.assertEqual(history_path.read_bytes(), history_before)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.read_pending_action()["session_id"], second["session_id"])
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_noncanonical_receipt_sqlite_anchors_cannot_replay(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        receipt = self.manager.read_confirmation_receipt()
        self.assertIsNotNone(receipt)
        assert receipt is not None
        receipt_digest = str(receipt["receipt_digest"])
        session_hash = str(receipt["confirmation_session_hash"])
        with sqlite3.connect(self.save_path / "data" / "game.sqlite") as conn:
            conn.execute(
                "update meta set value = ? where key = ?",
                (f" {receipt_digest} ", CONFIRMATION_RECEIPT_META_KEY),
            )
            conn.execute(
                "update meta set value = ? where key = ?",
                (
                    f" {receipt_digest} ",
                    f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}{session_hash}",
                ),
            )
            conn.commit()
        before = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "SQLite receipt anchor"):
            self.manager.player_confirm(str(first["session_id"]))

        self.assertEqual(gameplay_snapshot(self.save_path), before)

    def test_cross_save_expected_token_cannot_supersede_original_binding(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)

        conflict = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=str(first["session_id"]),
        )

        self.assertFalse(conflict["ok"], conflict)
        self.assert_lifecycle(conflict, state="conflict", kind="action")
        self.assertNotIn("pending_id", conflict["lifecycle"])
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.read_pending_action()["save_id"], self.started["save"]["id"])
        self.assertNotEqual(second["save"]["id"], self.started["save"]["id"])

        inspected = self.manager.inspect_pending()
        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["status"], "conflict")
        self.assertEqual(inspected["lifecycle"], {"state": "conflict", "kind": "action"})

    def test_low_level_cross_save_conflict_does_not_disclose_pending_token(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)

        with self.assertRaisesRegex(SaveManagerError, "conflicts with another pending") as raised:
            self.manager.begin_low_level_clarification_publication(
                save_path=str(second["save"]["path"]),
            )

        self.assertNotIn(str(first["session_id"]), str(raised.exception))
        self.assertEqual(self.manager.read_pending_action()["session_id"], first["session_id"])

    def test_low_level_publication_snapshot_is_required_and_identity_bound(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=save_path,
            platform="qq",
            session_key="room:owner-a",
            actor_id="actor:owner-a",
        )

        with self.assertRaisesRegex(SaveManagerError, "evidence is invalid"):
            self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": "哪一个？"},
                save_path=save_path,
                platform="qq",
                session_key="room:owner-b",
                actor_id="actor:owner-b",
                expected_publication=snapshot,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

        with self.assertRaisesRegex(SaveManagerError, "requires an owner snapshot"):
            self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": "哪一个？"},
                save_path=save_path,
            )
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_publication_snapshot_rejects_flag_tampering(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=save_path,
            require_active_save_match=True,
        )
        self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)
        snapshot["require_active_save_match"] = False

        with self.assertRaisesRegex(SaveManagerError, "evidence is invalid"):
            self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": "哪一个？"},
                save_path=save_path,
                expected_publication=snapshot,
            )

        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_adapter_rejects_preview_flag_tampering_before_skip(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=save_path,
        )
        snapshot["canonical_publication"] = False
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                default_save=save_path,
                mcp_profile="developer",
            )
        )
        result = clarification_runtime().act().to_dict()

        adapter.update_pending_clarification(
            save_path,
            {"view": "player", "mode": "action", "user_text": "使用那个物品"},
            result,
            expected_publication=snapshot,
        )

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status"], "invalid_state", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_adapter_does_not_publish_typed_error_clarification(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(save_path=save_path)
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                default_save=save_path,
                mcp_profile="developer",
            )
        )
        result = clarification_runtime().act().to_dict()
        result.update(
            {
                "status": "invalid_request",
                "error_details": [
                    {
                        "code": "INTENT_CONTRACT_VERSION_MISMATCH",
                        "reason": "contract_version_mismatch",
                    }
                ],
                "errors": ["external intent contract version mismatch"],
            }
        )

        adapter.update_pending_clarification(
            save_path,
            {"view": "player", "mode": "action", "user_text": "使用那个物品"},
            result,
            expected_publication=snapshot,
        )

        self.assertEqual(result["status"], "invalid_request", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_adapter_forwards_actor_bound_clarification_owner(self) -> None:
        save_path = str(self.started["save"]["path"])
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="developer",
            )
        )
        runtime = SimpleNamespace(
            start_turn=lambda *_args, **_kwargs: clarification_runtime().act(),
            preview_from_text=lambda *_args, **_kwargs: clarification_runtime().act(),
        )

        for method_name in ("start_turn", "preview_from_text"):
            with self.subTest(method_name=method_name), mock.patch.object(
                adapter,
                "runtime_for_save",
                return_value=runtime,
            ):
                result = getattr(adapter, method_name)(
                    "使用那个物品",
                    platform="qq",
                    session_key="room:actor-bound",
                    actor_id="actor:owner",
                )
            clarification_id = str(result["pending_clarification_id"])
            pending = self.manager.read_pending_clarification()
            assert pending is not None
            self.assertEqual(pending["actor_id_hash"], hash_identity("actor:owner"))

            wrong_actor = self.manager.player_cancel(
                clarification_id,
                save_path=save_path,
                platform="qq",
                session_key="room:actor-bound",
                actor_id="actor:other",
            )
            self.assertEqual(wrong_actor["status"], "conflict", wrong_actor)
            canceled = self.manager.player_cancel(
                clarification_id,
                save_path=save_path,
                platform="qq",
                session_key="room:actor-bound",
                actor_id="actor:owner",
            )
            self.assertEqual(canceled["status"], "canceled", canceled)

    def test_low_level_snapshot_cannot_replay_across_workspace_owner(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(save_path=save_path)
        with tempfile.TemporaryDirectory() as clone_tmp:
            clone_root = Path(clone_tmp) / "workspace"
            shutil.copytree(self.root, clone_root)
            clone_manager = SaveManager(clone_root)

            with self.assertRaisesRegex(SaveManagerError, "evidence is invalid"):
                clone_manager.record_low_level_clarification(
                    user_text="使用那个物品",
                    clarification={"question": "哪一个？"},
                    save_path=save_path,
                    expected_publication=snapshot,
                )

            self.assertIsNone(clone_manager.read_pending_action())
            self.assertIsNone(clone_manager.read_pending_clarification())

    def test_low_level_publication_snapshot_rejects_empty_state_aba(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(save_path=save_path)
        acted = self.manager.player_turn(user_text="休息到早上")
        canceled = self.manager.player_cancel(str(acted["session_id"]))
        self.assertEqual(canceled["status"], "canceled", canceled)

        result = self.manager.record_low_level_clarification(
            user_text="使用那个物品",
            clarification={"question": "哪一个？"},
            save_path=save_path,
            expected_publication=snapshot,
        )

        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_publication_snapshot_rejects_revision_loss(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(save_path=save_path)
        acted = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_cancel(str(acted["session_id"]))
        self.manager.pending_lifecycle_revision_path().unlink()

        result = self.manager.record_low_level_clarification(
            user_text="使用那个物品",
            clarification={"question": "哪一个？"},
            save_path=save_path,
            expected_publication=snapshot,
        )

        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_default_inspect_without_active_save_fails_closed_without_pending_token(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        registry = self.manager.read_registry()
        registry["active_save_id"] = None
        self.manager.write_registry(registry)

        inspected = self.manager.inspect_pending()

        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["status"], "invalid_state")
        self.assertEqual(inspected["lifecycle"], {"state": "invalid_state", "kind": "unknown"})
        self.assertNotIn(str(first["session_id"]), json.dumps(inspected, ensure_ascii=False))

        self.manager.clear_pending_action()
        no_pending = self.manager.inspect_pending()
        self.assertFalse(no_pending["ok"], no_pending)
        self.assertEqual(no_pending["status"], "invalid_state")
        self.assertEqual(no_pending["lifecycle"], {"state": "invalid_state", "kind": "unknown"})

    def test_default_inspect_without_active_save_precedes_identity_classification(self) -> None:
        acted = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:no-active",
            actor_id="actor:no-active",
        )
        registry = self.manager.read_registry()
        registry["active_save_id"] = None
        self.manager.write_registry(registry)

        inspected = self.manager.inspect_pending()

        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["status"], "invalid_state")
        self.assertEqual(inspected["lifecycle"], {"state": "invalid_state", "kind": "unknown"})
        self.assertNotIn(str(acted["session_id"]), json.dumps(inspected, ensure_ascii=False))

    def test_canonical_inspect_and_cancel_fail_closed_on_malformed_revision(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        self.manager.pending_lifecycle_revision_path().write_bytes(b"{malformed")

        inspected = self.manager.inspect_pending()
        canceled = self.manager.player_cancel(str(acted["session_id"]))

        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["status"], "invalid_state", inspected)
        self.assertFalse(canceled["ok"], canceled)
        self.assertEqual(canceled["status"], "invalid_state", canceled)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

    def test_no_pending_inspect_fails_closed_on_malformed_revision(self) -> None:
        revision_path = self.manager.pending_lifecycle_revision_path()
        revision_path.parent.mkdir(parents=True, exist_ok=True)
        revision_path.write_bytes(b"{malformed")

        inspected = self.manager.inspect_pending()

        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["status"], "invalid_state", inspected)
        self.assertEqual(inspected["lifecycle"], {"state": "invalid_state", "kind": "unknown"})

    def test_bounded_pending_json_rejects_oversized_integer_as_owner_error(self) -> None:
        path = self.manager.pending_action_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"n": ' + ("9" * 5000) + "}", encoding="utf-8")

        with self.assertRaisesRegex(SaveManagerError, "pending player action is invalid"):
            self.manager.read_pending_action()

    def test_switch_rejects_invalid_pending_save_binding_before_registry_mutation(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        pending = self.manager.read_pending_action()
        assert pending is not None
        pending["save_id"] = "save:missing"
        self.manager.write_pending_action(pending)
        registry_before = self.manager.registry_path.read_bytes()

        with self.assertRaisesRegex(SaveManagerError, "unresolved save evidence"):
            self.manager.switch_save(str(second["save"]["id"]), refresh=False)

        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)
        self.assertEqual(self.manager.read_pending_action()["save_id"], "save:missing")

    def test_failed_switch_does_not_migrate_legacy_clarification(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        assert legacy is not None
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        self.manager.write_pending_clarification(legacy)
        pending_before = self.manager.pending_clarification_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        registry_before = self.manager.registry_path.read_bytes()

        with self.assertRaisesRegex(SaveManagerError, "save not found"):
            self.manager.switch_save("save:does-not-exist", refresh=False)

        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.pending_lifecycle_revision_path().read_bytes(), revision_before)
        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)

    def test_create_and_duplicate_activation_report_preserved_pending_lifecycle(self) -> None:
        first_save = dict(self.started["save"])
        self.manager.player_turn(user_text="休息到早上")

        created = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)
        duplicated = self.manager.duplicate_save(str(first_save["id"]), label="Copy", activate=True)

        self.assert_lifecycle(created, state="preserved", kind="action")
        self.assert_lifecycle(duplicated, state="preserved", kind="action")
        self.assertEqual(self.manager.read_pending_action()["save_id"], first_save["id"])
        self.assertEqual(self.manager.read_registry()["active_save_id"], duplicated["save"]["id"])

    def test_candidate_mismatch_requires_exact_tokens_and_changed_candidate(self) -> None:
        original_text = "保持原样"
        original_candidate = {"kind": "single", "mode": "action", "action": "travel", "slots": {}}
        facts_before = gameplay_snapshot(self.save_path)
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=mismatch_clarification_runtime()):
            created = self.manager.player_turn(
                user_text=original_text,
                external_intent_candidate=original_candidate,
            )
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        self.assertEqual(self.manager.read_pending_clarification()["clarification_origin"], "candidate_contract_mismatch")

        unchanged = self.manager.player_turn(
            user_text=original_text,
            expected_pending_id=clarification_id,
            clarification_id=clarification_id,
            external_intent_candidate=original_candidate,
        )
        self.assertEqual(unchanged["status"], "needs_clarification", unchanged)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

        corrected_candidate = {**original_candidate, "action": "rest", "slots": {"until": "morning"}}
        for expected_token, correction_token in (
            (f" {clarification_id} ", clarification_id),
            (clarification_id, f" {clarification_id} "),
        ):
            with self.subTest(expected_token=expected_token, correction_token=correction_token):
                rejected = self.manager.player_turn(
                    user_text=original_text,
                    expected_pending_id=expected_token,
                    clarification_id=correction_token,
                    external_intent_candidate=corrected_candidate,
                )
                self.assertEqual(rejected["status"], "pending_conflict", rejected)
                self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=ready_runtime("cmd:corrected")):
            corrected = self.manager.player_turn(
                user_text=original_text,
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
                external_intent_candidate=corrected_candidate,
            )
        self.assertTrue(corrected["ready_to_confirm"], corrected)
        self.assert_lifecycle(corrected, state="superseded", kind="action")
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_typed_corrected_candidate_error_preserves_clarification(self) -> None:
        original_text = "保持原样"
        original_candidate = {"kind": "single", "mode": "action", "action": "travel", "slots": {}}
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=mismatch_clarification_runtime()):
            created = self.manager.player_turn(
                user_text=original_text,
                external_intent_candidate=original_candidate,
            )
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        typed_error = SimpleNamespace(
            act=lambda *_args, **_kwargs: result_object(
                {
                    "ok": False,
                    "status": "invalid_request",
                    "action": "act",
                    "error_details": [
                        {
                            "code": "INTENT_CONTRACT_VERSION_MISMATCH",
                            "reason": "contract_version_mismatch",
                        }
                    ],
                    "warnings": [],
                    "errors": ["external intent contract version mismatch"],
                }
            )
        )
        corrected_candidate = {**original_candidate, "action": "rest", "slots": {"until": "morning"}}

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=typed_error):
            result = self.manager.player_turn(
                user_text=original_text,
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
                external_intent_candidate=corrected_candidate,
            )

        self.assertFalse(result["ok"], result)
        self.assert_lifecycle(result, state="preserved", kind="clarification")
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_typed_fresh_answer_error_preserves_clarification(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)
        typed_error = SimpleNamespace(
            act=lambda *_args, **_kwargs: result_object(
                {
                    "ok": False,
                    "status": "invalid_request",
                    "action": "act",
                    "error_details": [
                        {
                            "code": "UNKNOWN_INTENT_SAFETY_FLAG",
                            "reason": "unknown_safety_flag",
                        }
                    ],
                    "warnings": [],
                    "errors": ["external intent candidate contains unsupported safety flags"],
                }
            )
        )

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=typed_error):
            result = self.manager.player_turn(
                user_text="我指第一个",
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
                external_intent_candidate={"safety_flags": ["future_flag"]},
            )

        self.assertFalse(result["ok"], result)
        self.assert_lifecycle(result, state="preserved", kind="clarification")
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_typed_error_cannot_publish_or_replace_clarification(self) -> None:
        typed_with_clarification = SimpleNamespace(
            act=lambda *_args, **_kwargs: result_object(
                {
                    "ok": False,
                    "status": "invalid_request",
                    "action": "act",
                    "interpretation": {
                        "intent": {"clarification": {"question": "错误候选中的问题"}}
                    },
                    "error_details": [
                        {
                            "code": "INTENT_CONTRACT_VERSION_MISMATCH",
                            "reason": "contract_version_mismatch",
                        }
                    ],
                    "warnings": [],
                    "errors": ["external intent contract version mismatch"],
                }
            )
        )
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=typed_with_clarification,
        ):
            initial = self.manager.player_turn(
                user_text="新请求",
                external_intent_candidate={"contract": {"version": "old"}},
            )
        self.assertEqual(initial["status"], "invalid_request", initial)
        self.assertIsNone(self.manager.read_pending_clarification())

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=typed_with_clarification,
        ):
            replacement = self.manager.player_turn(
                user_text="我指第一个",
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
                external_intent_candidate={"contract": {"version": "old"}},
            )

        self.assertEqual(replacement["status"], "invalid_request", replacement)
        self.assert_lifecycle(replacement, state="preserved", kind="clarification")
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_nonsemantic_external_candidate_failure_stays_player_ambiguity(self) -> None:
        runtime = clarification_runtime()
        result = runtime.act().to_dict()
        intent = result["interpretation"]["intent"]
        intent.update(
            {
                "source": "ai_disagreement",
                "agreement_with_external": "partial",
                "external_candidate_quality": "malformed",
            }
        )
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=lambda *_args, **_kwargs: result_object(result)),
        ):
            self.manager.player_turn(
                user_text="保持原样",
                external_intent_candidate={"kind": "single", "mode": "action", "action": "rest", "slots": {}},
            )

        pending = self.manager.read_pending_clarification()
        self.assertEqual(pending["clarification_origin"], "player_input_ambiguity")

    def test_genuine_ambiguity_rejects_candidate_only_retry_but_accepts_fresh_answer(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        before = self.manager.pending_clarification_path().read_bytes()

        candidate_only = self.manager.player_turn(
            user_text="使用那个物品",
            expected_pending_id=clarification_id,
            clarification_id=clarification_id,
            external_intent_candidate={"kind": "single", "mode": "action", "action": "rest", "slots": {}},
        )
        self.assertEqual(candidate_only["status"], "needs_clarification", candidate_only)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=ready_runtime("cmd:fresh-answer")):
            answered = self.manager.player_turn(
                user_text="第一个物品",
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
            )
        self.assertTrue(answered["ready_to_confirm"], answered)
        self.assert_lifecycle(answered, state="superseded", kind="action")

    def test_matching_fresh_answer_query_ends_old_clarification_with_cas(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])

        queried = self.manager.player_turn(
            user_text="查看周围",
            expected_pending_id=clarification_id,
            clarification_id=clarification_id,
        )

        self.assertTrue(queried["ok"], queried)
        self.assertEqual(queried["action"], "query", queried)
        self.assert_lifecycle(queried, state="superseded", kind="clarification")
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertIsNone(self.manager.read_pending_action())

    def test_matching_fresh_answer_preserves_clarification_if_save_is_archived_inflight(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("clarification resolution Save gate timed out")
            return result_object(
                {
                    "ok": True,
                    "status": "query",
                    "action": "query",
                    "warnings": [],
                    "errors": [],
                }
            )

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="查看周围",
                save_path=str(self.started["save"]["path"]),
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
            )

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                registry = self.manager.read_registry()
                registry["saves"] = [
                    {**dict(record), "archived": True}
                    if record.get("id") == self.started["save"]["id"]
                    else record
                    for record in registry["saves"]
                ]
                self.manager.write_registry(registry)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)
        self.assertIsNone(self.manager.read_pending_action())

    def test_expired_clarification_is_preserved_if_save_is_archived_inflight(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("expired clarification Save gate timed out")
            return result_object(
                {"ok": True, "status": "query", "action": "query", "warnings": [], "errors": []}
            )

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="查看周围",
                save_path=str(self.started["save"]["path"]),
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
            )

        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(act=act),
            ),
            mock.patch(
                "rpg_engine.save_manager.pending_action_is_expired",
                side_effect=[False, True],
            ),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            registry = self.manager.read_registry()
            registry["saves"] = [
                {**dict(record), "archived": True}
                if record.get("id") == self.started["save"]["id"]
                else record
                for record in registry["saves"]
            ]
            self.manager.write_registry(registry)
            release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["result"]["status"], "pending_conflict", outcome["result"])
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_clarification_resolution_maps_inflight_malformed_registry_to_conflict(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        pending_before = self.manager.pending_clarification_path().read_bytes()
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("malformed registry gate timed out")
            return result_object(
                {"ok": True, "status": "query", "action": "query", "warnings": [], "errors": []}
            )

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="查看周围",
                save_path=str(self.started["save"]["path"]),
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
            )

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            self.manager.registry_path.write_text("{invalid", encoding="utf-8")
            release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["result"]["status"], "pending_conflict", outcome["result"])
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_clarification_supersede_requires_both_tokens_and_semantically_fresh_answer(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            created = self.manager.player_turn(user_text="使用那个物品")
        clarification_id = str(created["pending_clarification_id"])
        before = self.manager.pending_clarification_path().read_bytes()

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=ready_runtime("cmd:missing-token")):
            missing_token = self.manager.player_turn(
                user_text="第一个物品",
                expected_pending_id=clarification_id,
            )
        self.assertEqual(missing_token["status"], "pending_conflict", missing_token)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=ready_runtime("cmd:whitespace")):
            whitespace_only = self.manager.player_turn(
                user_text=" 使用那个物品 ",
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
            )
        self.assertEqual(whitespace_only["status"], "needs_clarification", whitespace_only)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_each_clarification_publication_gets_a_fresh_owner_token(self) -> None:
        runtime = clarification_runtime()
        runtime_result = runtime.act().to_dict()
        runtime_result["interpretation"]["intent"]["clarification"]["clarification_id"] = "clarification:semantic"
        repeated_runtime = SimpleNamespace(act=lambda *_args, **_kwargs: result_object(runtime_result))
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=repeated_runtime):
            first = self.manager.player_turn(user_text="first")
            first_id = str(first["pending_clarification_id"])
            second = self.manager.player_turn(
                user_text="second",
                expected_pending_id=first_id,
                clarification_id=first_id,
            )
        second_id = str(second["pending_clarification_id"])
        self.assertNotEqual(first_id, "clarification:semantic")
        self.assertNotEqual(second_id, first_id)

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=ready_runtime("cmd:delayed-old-token")):
            delayed = self.manager.player_turn(
                user_text="first answer",
                expected_pending_id=first_id,
                clarification_id=first_id,
            )
        self.assertEqual(delayed["status"], "pending_conflict", delayed)
        self.assertEqual(self.manager.read_pending_clarification()["clarification_id"], second_id)

    def test_legacy_clarification_migrates_and_expired_clarification_is_terminal(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            created = self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        self.manager.write_pending_clarification(legacy)

        migrated = self.manager.inspect_pending()
        self.assert_lifecycle(migrated, state="migrated", kind="clarification")
        persisted = self.manager.read_pending_clarification()
        self.assertEqual(persisted["clarification_origin"], "player_input_ambiguity")
        self.assertEqual(persisted["ttl_seconds"], DEFAULT_PENDING_ACTION_TTL_SECONDS)

        expired_created = datetime.now(timezone.utc) - timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS + 1)
        persisted["created_at"] = expired_created.isoformat()
        persisted["expires_at"] = (
            expired_created + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
        ).isoformat()
        self.manager.write_pending_clarification(persisted)
        expired = self.manager.inspect_pending()
        self.assert_lifecycle(expired, state="expired", kind="clarification")
        self.assertFalse(self.manager.pending_clarification_path().exists())
        terminal = self.manager.player_cancel(str(created["pending_clarification_id"]))
        self.assert_lifecycle(terminal, state="not_found", kind="clarification")

    def test_cross_identity_cannot_expire_or_migrate_owner_clarification(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(
                user_text="使用那个物品",
                platform="qq",
                session_key="room:owner",
                actor_id="actor:owner",
            )
        legacy = self.manager.read_pending_clarification()
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        self.manager.write_pending_clarification(legacy)
        before_legacy = self.manager.pending_clarification_path().read_bytes()

        inspected = self.manager.inspect_pending(
            platform="qq",
            session_key="room:intruder",
            actor_id="actor:intruder",
        )

        self.assertEqual(inspected["status"], "conflict", inspected)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before_legacy)
        migrated = self.manager.inspect_pending(
            platform="qq",
            session_key="room:owner",
            actor_id="actor:owner",
        )
        self.assert_lifecycle(migrated, state="migrated", kind="clarification")
        expired = self.manager.read_pending_clarification()
        expired_created = datetime.now(timezone.utc) - timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS + 1)
        expired["created_at"] = expired_created.isoformat()
        expired["expires_at"] = (
            expired_created + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
        ).isoformat()
        self.manager.write_pending_clarification(expired)
        before_expired = self.manager.pending_clarification_path().read_bytes()

        intruder = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:intruder",
            actor_id="actor:intruder",
        )

        self.assertEqual(intruder["status"], "pending_conflict", intruder)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before_expired)
        owner_expired = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:owner",
            actor_id="actor:owner",
        )
        self.assert_lifecycle(owner_expired, state="expired", kind="clarification")
        self.assertFalse(self.manager.pending_clarification_path().exists())

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(
                user_text="使用那个物品",
                platform="qq",
                session_key="room:owner",
                actor_id="actor:owner",
            )

    def test_archived_active_save_preserves_expired_clarification_before_runtime(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        pending = self.manager.read_pending_clarification()
        assert pending is not None
        expired_created = datetime.now(timezone.utc) - timedelta(
            seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS + 1
        )
        pending["created_at"] = expired_created.isoformat()
        pending["expires_at"] = (
            expired_created + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
        ).isoformat()
        self.manager.write_pending_clarification(pending)
        pending_before = self.manager.pending_clarification_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        registry = self.manager.read_registry()
        registry["saves"] = [
            {**dict(record), "archived": True}
            if record.get("id") == self.started["save"]["id"]
            else record
            for record in registry["saves"]
        ]
        self.manager.write_registry(registry)

        result = self.manager.player_turn(
            user_text="查看周围",
            expected_pending_id=str(created["pending_clarification_id"]),
            clarification_id=str(created["pending_clarification_id"]),
        )

        self.assertEqual(result["status"], "invalid_state", result)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.pending_lifecycle_revision_path().read_bytes(), revision_before)

    def test_archived_active_save_preserves_expired_action_before_runtime(self) -> None:
        created = self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        assert pending is not None
        expired_created = datetime.now(timezone.utc) - timedelta(
            seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS + 1
        )
        pending["created_at"] = expired_created.isoformat()
        pending["expires_at"] = (
            expired_created + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
        ).isoformat()
        self.manager.write_pending_action(pending)
        pending_before = self.manager.pending_action_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        registry = self.manager.read_registry()
        registry["saves"] = [
            {**dict(record), "archived": True}
            if record.get("id") == self.started["save"]["id"]
            else record
            for record in registry["saves"]
        ]
        self.manager.write_registry(registry)

        result = self.manager.player_turn(
            user_text="改为继续休息",
            expected_pending_id=str(created["session_id"]),
        )

        self.assertEqual(result["status"], "invalid_state", result)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.pending_lifecycle_revision_path().read_bytes(), revision_before)

    def test_missing_sqlite_returns_invalid_state_and_preserves_pending(self) -> None:
        created = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        (self.save_path / "data" / "game.sqlite").unlink()

        inspected = self.manager.inspect_pending()
        result = self.manager.player_turn(
            user_text="改为继续休息",
            expected_pending_id=str(created["session_id"]),
        )

        self.assertEqual(inspected["status"], "invalid_state", inspected)
        self.assertEqual(result["status"], "invalid_state", result)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.pending_lifecycle_revision_path().read_bytes(), revision_before)

    def test_unavailable_default_save_result_never_discloses_other_save_pending(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        second = self.manager.create_save(
            campaign="campaigns/minimal",
            label="Second",
            activate=True,
        )
        second_path = self.root / str(second["save"]["path"])
        (second_path / "data" / "game.sqlite").unlink()

        unavailable = self.manager.player_turn(
            user_text="继续休息",
            expected_pending_id=str(first["session_id"]),
        )

        self.assertEqual(unavailable["status"], "invalid_state", unavailable)
        self.assertEqual(unavailable["lifecycle"], {"state": "invalid_state", "kind": "unknown"})
        self.assertIsNone(unavailable["active_save_id"])
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

        registry = self.manager.read_registry()
        registry["active_save_id"] = None
        self.manager.write_registry(registry)
        no_active = self.manager.player_turn(
            user_text="继续休息",
            expected_pending_id=str(first["session_id"]),
        )
        self.assertEqual(no_active["lifecycle"], {"state": "invalid_state", "kind": "unknown"})
        self.assertIsNone(no_active["active_save_id"])
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

    def test_first_phase_live_gate_preserves_expired_clarification_on_sqlite_race(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        pending = self.manager.read_pending_clarification()
        assert pending is not None
        expired_created = datetime.now(timezone.utc) - timedelta(
            seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS + 1
        )
        pending["created_at"] = expired_created.isoformat()
        pending["expires_at"] = (
            expired_created + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
        ).isoformat()
        self.manager.write_pending_clarification(pending)
        pending_before = self.manager.pending_clarification_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        original_classification = SaveManager.pending_orphan_classification

        def corrupt_before_classification(
            manager: SaveManager,
            kind: str,
            current: dict[str, object],
        ) -> str:
            (self.save_path / "data" / "game.sqlite").unlink(missing_ok=True)
            return original_classification(manager, kind, current)

        with mock.patch.object(
            SaveManager,
            "pending_orphan_classification",
            autospec=True,
            side_effect=corrupt_before_classification,
        ):
            result = self.manager.player_turn(
                user_text="查看周围",
                expected_pending_id=str(created["pending_clarification_id"]),
                clarification_id=str(created["pending_clarification_id"]),
            )

        self.assertEqual(result["status"], "invalid_state", result)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.pending_lifecycle_revision_path().read_bytes(), revision_before)

    def test_inspect_and_cancel_terminal_mutations_hold_live_save_gate(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            self.manager.player_turn(user_text="使用那个物品")
        pending = self.manager.read_pending_clarification()
        assert pending is not None
        expired_created = datetime.now(timezone.utc) - timedelta(
            seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS + 1
        )
        pending["created_at"] = expired_created.isoformat()
        pending["expires_at"] = (
            expired_created + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
        ).isoformat()
        self.manager.write_pending_clarification(pending)
        frozen_depth = 0
        original_frozen = self.manager.frozen_save_publication_registry
        original_clear = self.manager.clear_pending_kind

        @contextmanager
        def tracked_frozen(*args: object, **kwargs: object):
            nonlocal frozen_depth
            with original_frozen(*args, **kwargs):
                frozen_depth += 1
                try:
                    yield
                finally:
                    frozen_depth -= 1

        def checked_clear(kind: str) -> None:
            self.assertGreater(frozen_depth, 0)
            original_clear(kind)

        with (
            mock.patch.object(
                self.manager,
                "frozen_save_publication_registry",
                side_effect=tracked_frozen,
            ),
            mock.patch.object(
                self.manager,
                "clear_pending_kind",
                side_effect=checked_clear,
            ),
        ):
            expired = self.manager.inspect_pending()
            acted = self.manager.player_turn(user_text="休息到早上")
            canceled = self.manager.player_cancel(str(acted["session_id"]))

        self.assertEqual(expired["status"], "expired", expired)
        self.assertEqual(canceled["status"], "canceled", canceled)

    def test_legacy_answer_does_not_reenter_registry_lock_during_migration(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            created = self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        assert legacy is not None
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        self.manager.write_pending_clarification(legacy)

        with (
            mock.patch.object(
                self.manager,
                "pending_orphan_classification",
                wraps=self.manager.pending_orphan_classification,
            ) as classified,
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=ready_runtime("cmd:legacy-answer"),
            ),
        ):
            result = self.manager.player_turn(
                user_text="第一个物品",
                expected_pending_id=str(created["pending_clarification_id"]),
                clarification_id=str(created["pending_clarification_id"]),
            )

        self.assertTrue(result["ready_to_confirm"], result)
        self.assertEqual(classified.call_count, 1)

    def test_orphan_cleanup_rechecks_registry_after_save_is_restored(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            self.manager.player_turn(user_text="使用那个物品")
        pending_before = self.manager.pending_clarification_path().read_bytes()
        registry = self.manager.read_registry()
        record = next(
            dict(item)
            for item in registry["saves"]
            if item.get("id") == self.started["save"]["id"]
        )
        registry["saves"] = [
            item
            for item in registry["saves"]
            if item.get("id") != self.started["save"]["id"]
        ]
        self.manager.write_registry(registry)
        backup = self.root / "save-backup"
        shutil.move(self.save_path, backup)
        original_clear = self.manager.clear_pending_if_still_orphaned

        def restore_then_recheck(kind: str, pending: dict[str, object]) -> bool:
            shutil.move(backup, self.save_path)
            restored_registry = self.manager.read_registry()
            restored_registry["saves"].append(record)
            self.manager.write_registry(restored_registry)
            return original_clear(kind, pending)

        with mock.patch.object(
            self.manager,
            "clear_pending_if_still_orphaned",
            side_effect=restore_then_recheck,
        ):
            inspected = self.manager.inspect_pending(
                save_path=str(self.started["save"]["path"]),
            )

        self.assertEqual(inspected["status"], "invalid_state", inspected)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_partial_legacy_clarification_fields_migrate_conservatively(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=mismatch_clarification_runtime()):
            self.manager.player_turn(
                user_text="保持原样",
                external_intent_candidate={"kind": "single", "mode": "action", "action": "travel", "slots": {}},
            )
        legacy = self.manager.read_pending_clarification()
        legacy.pop("clarification_origin")
        legacy.pop("external_candidate_digest")
        self.manager.write_pending_clarification(legacy)

        migrated = self.manager.inspect_pending()

        self.assert_lifecycle(migrated, state="migrated", kind="clarification")
        persisted = self.manager.read_pending_clarification()
        self.assertEqual(persisted["clarification_origin"], "player_input_ambiguity")
        self.assertEqual(persisted["external_candidate_digest"], "")

    def test_partial_legacy_clarification_rejects_existing_invalid_migration_evidence(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        pending = self.manager.read_pending_clarification()
        self.assertIsNotNone(pending)
        assert pending is not None
        cases = (
            ({"clarification_origin": "invalid-origin"}, "ttl_seconds"),
            ({"external_candidate_digest": "not-a-digest"}, "expires_at"),
        )
        for mutation, missing_key in cases:
            with self.subTest(mutation=mutation, missing_key=missing_key):
                legacy = {**pending, **mutation}
                legacy.pop(missing_key)
                self.manager.write_pending_clarification(legacy)
                before = self.manager.pending_clarification_path().read_bytes()

                with self.assertRaisesRegex(SaveManagerError, "invalid origin|invalid candidate evidence"):
                    self.manager.inspect_pending()

                self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_invalid_legacy_clarification_is_never_rewritten_before_failure(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        legacy["clarification"] = "not-an-object"
        self.manager.write_pending_clarification(legacy)
        before = self.manager.pending_clarification_path().read_bytes()

        with self.assertRaisesRegex(SaveManagerError, "clarification is incomplete"):
            self.manager.inspect_pending()

        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_legacy_conflicting_binding_is_not_migrated_or_deleted(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        legacy["save_id"] = "save:conflict"
        self.manager.write_pending_clarification(legacy)
        before = self.manager.pending_clarification_path().read_bytes()

        invalid = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))

        self.assert_lifecycle(invalid, state="invalid_state", kind="clarification")
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_legacy_clarification_rejects_raw_identity_and_unknown_fields(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        legacy.update(
            {
                "session_key": "RAW_SESSION_SECRET",
                "actor_id": "RAW_ACTOR_SECRET",
                "unknown_evidence": "not-allowlisted",
            }
        )
        self.manager.write_pending_clarification(legacy)
        before = self.manager.pending_clarification_path().read_bytes()

        with self.assertRaisesRegex(SaveManagerError, "unknown or raw identity fields"):
            self.manager.inspect_pending()

        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_clarification_payload_rejects_raw_identity_at_publication_and_read(self) -> None:
        raw_session = "room:raw-owner-secret"
        raw_actor = "actor:raw-owner-secret"
        unsafe_runtime = clarification_runtime()
        unsafe_result = unsafe_runtime.act().to_dict()
        unsafe_result["interpretation"]["intent"]["clarification"].update(
            {"sessionKey": raw_session, "actor_id": raw_actor}
        )
        before_facts = gameplay_snapshot(self.save_path)

        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_result)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "raw identity"),
        ):
            self.manager.player_turn(
                user_text="使用那个物品",
                platform="qq",
                session_key=raw_session,
                actor_id=raw_actor,
            )
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertEqual(gameplay_snapshot(self.save_path), before_facts)

        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=str(self.started["save"]["path"]),
            platform="qq",
            session_key=raw_session,
            actor_id=raw_actor,
        )
        with self.assertRaisesRegex(SaveManagerError, "raw identity"):
            self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": raw_session},
                save_path=str(self.started["save"]["path"]),
                platform="qq",
                session_key=raw_session,
                actor_id=raw_actor,
                expected_publication=snapshot,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            self.manager.player_turn(user_text="使用那个物品")
        tampered = self.manager.read_pending_clarification()
        assert tampered is not None
        tampered["clarification"]["session_key"] = "raw-persisted"
        self.manager.write_pending_clarification(tampered)
        pending_before = self.manager.pending_clarification_path().read_bytes()
        with self.assertRaisesRegex(SaveManagerError, "raw identity"):
            self.manager.inspect_pending()
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_short_identity_does_not_false_positive_in_clarification_text(self) -> None:
        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime("What target?"),
        ):
            result = self.manager.player_turn(
                user_text="choose",
                platform="p",
                session_key="s",
                actor_id="a",
            )

        self.assertEqual(result["status"], "needs_clarification", result)
        self.assertIsNotNone(self.manager.read_pending_clarification())

    def test_clarification_payload_rejects_raw_identity_nested_key_and_persisted_scalar(self) -> None:
        raw_session = "room:raw-owner-secret"
        raw_actor = "actor:raw-owner-secret"
        unsafe_runtime = clarification_runtime()
        unsafe_result = unsafe_runtime.act().to_dict()
        unsafe_result["interpretation"]["intent"]["clarification"]["choices"] = {
            raw_session: "option"
        }
        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_result)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "raw identity"),
        ):
            self.manager.player_turn(
                user_text="choose",
                platform="qq",
                session_key=raw_session,
                actor_id=raw_actor,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=str(self.started["save"]["path"]),
            platform="qq",
            session_key=raw_session,
            actor_id=raw_actor,
        )
        with self.assertRaisesRegex(SaveManagerError, "raw identity"):
            self.manager.record_low_level_clarification(
                user_text="choose",
                clarification={"choices": {raw_session: "option"}},
                save_path=str(self.started["save"]["path"]),
                platform="qq",
                session_key=raw_session,
                actor_id=raw_actor,
                expected_publication=snapshot,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=clarification_runtime(),
        ):
            self.manager.player_turn(
                user_text="使用那个物品",
                platform="qq",
                session_key=raw_session,
                actor_id=raw_actor,
            )
        tampered = self.manager.read_pending_clarification()
        assert tampered is not None
        tampered["clarification"]["question"] = raw_session
        self.manager.write_pending_clarification(tampered)
        pending_before = self.manager.pending_clarification_path().read_bytes()
        with self.assertRaisesRegex(SaveManagerError, "raw identity"):
            self.manager.inspect_pending(
                platform="qq",
                session_key=raw_session,
                actor_id=raw_actor,
            )
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), pending_before)

    def test_clarification_privacy_validation_reuses_bounded_json_shape(self) -> None:
        cyclic: dict[str, object] = {"question": "which one"}
        cyclic["cycle"] = cyclic
        unsafe_result = clarification_runtime().act().to_dict()
        unsafe_result["interpretation"]["intent"]["clarification"] = cyclic
        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_result)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "JSON structure limit"),
        ):
            self.manager.player_turn(user_text="choose")
        self.assertIsNone(self.manager.read_pending_clarification())

        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=str(self.started["save"]["path"]),
        )
        with self.assertRaisesRegex(SaveManagerError, "JSON structure limit"):
            self.manager.record_low_level_clarification(
                user_text="choose",
                clarification=cyclic,
                save_path=str(self.started["save"]["path"]),
                expected_publication=snapshot,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_pending_writers_convert_oversized_integer_serialization_errors(self) -> None:
        oversized_integer = 10**5000
        unsafe_clarification = clarification_runtime().act().to_dict()
        unsafe_clarification["interpretation"]["intent"]["clarification"][
            "ordinal"
        ] = oversized_integer
        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_clarification)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "safely serializable"),
        ):
            self.manager.player_turn(user_text="choose")
        self.assertIsNone(self.manager.read_pending_clarification())

        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=str(self.started["save"]["path"]),
        )
        with self.assertRaisesRegex(SaveManagerError, "safely serializable"):
            self.manager.record_low_level_clarification(
                user_text="choose",
                clarification={"question": "which one", "ordinal": oversized_integer},
                save_path=str(self.started["save"]["path"]),
                expected_publication=snapshot,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

        unsafe_action = ready_runtime("cmd:oversized-integer").act().to_dict()
        unsafe_action["delta_draft"]["oversized_integer"] = oversized_integer
        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_action)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "safely serializable"),
        ):
            self.manager.player_turn(user_text="rest")
        self.assertIsNone(self.manager.read_pending_action())

    def test_pending_json_and_digests_convert_invalid_unicode_errors(self) -> None:
        invalid_unicode = "\ud800"
        unsafe_clarification = clarification_runtime().act().to_dict()
        unsafe_clarification["interpretation"]["intent"]["clarification"][
            "question"
        ] = invalid_unicode
        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_clarification)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "invalid Unicode"),
        ):
            self.manager.player_turn(user_text="choose")
        self.assertIsNone(self.manager.read_pending_clarification())

        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=str(self.started["save"]["path"]),
        )
        with self.assertRaisesRegex(SaveManagerError, "invalid Unicode"):
            self.manager.record_low_level_clarification(
                user_text="choose",
                clarification={"question": invalid_unicode},
                save_path=str(self.started["save"]["path"]),
                expected_publication=snapshot,
            )
        self.assertIsNone(self.manager.read_pending_clarification())

        unsafe_action = ready_runtime("cmd:invalid-unicode").act().to_dict()
        unsafe_action["delta_draft"]["invalid_unicode"] = invalid_unicode
        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(
                    act=lambda *_args, **_kwargs: result_object(unsafe_action)
                ),
            ),
            self.assertRaisesRegex(SaveManagerError, "invalid Unicode"),
        ):
            self.manager.player_turn(user_text="rest")
        self.assertIsNone(self.manager.read_pending_action())

        with self.assertRaisesRegex(SaveManagerError, "not canonical JSON"):
            stable_payload_digest({"invalid_unicode": invalid_unicode})
        with self.assertRaisesRegex(SaveManagerError, "exact canonical string"):
            self.manager.player_confirm(invalid_unicode)
        canceled = self.manager.player_cancel(invalid_unicode)
        self.assertEqual(canceled["status"], "invalid_state", canceled)

    def test_inspect_pending_maps_malformed_registry_to_invalid_state(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)
        malformed_registries = {
            "invalid_json": b"{invalid",
            "root_list": b"[]",
            "non_array_records": b'{"schema_version":"1","campaigns":{},"saves":[]}',
            "non_object_records": (
                b'{"schema_version":"1","active_save_id":null,"campaigns":[7],"saves":[false]}'
            ),
            "numeric_authority": (
                b'{"schema_version":"1","active_save_id":7,"campaigns":[],"saves":[{"id":7,"path":"saves/run"}]}'
            ),
            "invalid_utf8": b"\xff",
            "duplicate_keys": (
                b'{"schema_version":"0","schema_version":"1","campaigns":[],"saves":[]}'
            ),
            "escaped_invalid_unicode": (
                b'{"schema_version":"1","campaigns":[],"saves":[{"id":"save:x","path":"saves/\\ud800"}]}'
            ),
        }
        for case, registry_bytes in malformed_registries.items():
            with self.subTest(case=case):
                self.manager.registry_path.write_bytes(registry_bytes)

                inspected = self.manager.inspect_pending()
                turned = self.manager.player_turn(user_text="继续休息")

                self.assertEqual(inspected["status"], "invalid_state", inspected)
                self.assertEqual(
                    inspected["lifecycle"],
                    {"state": "invalid_state", "kind": "unknown"},
                )
                self.assertEqual(
                    inspected["errors"],
                    ["pending player session has no verifiable selected save"],
                )
                self.assertEqual(turned["status"], "invalid_state", turned)
                self.assertEqual(
                    turned["lifecycle"],
                    {"state": "invalid_state", "kind": "unknown"},
                )
                self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
                self.assertEqual(
                    self.manager.pending_lifecycle_revision_path().read_bytes(),
                    revision_before,
                )
                self.assertEqual(self.manager.registry_path.read_bytes(), registry_bytes)
                self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_external_identity_inputs_fail_closed_before_hashing(self) -> None:
        acted = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:one",
            actor_id="player:one",
        )
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)
        invalid_identities = {
            "invalid_utf8_session": {
                "platform": "qq",
                "session_key": "\ud800",
                "actor_id": "",
            },
            "oversized_actor": {
                "platform": "qq",
                "session_key": "room:one",
                "actor_id": "x" * (MAX_PENDING_STRING_LENGTH + 1),
            },
        }
        for case, identity in invalid_identities.items():
            with self.subTest(case=case):
                turned = self.manager.player_turn(user_text="继续休息", **identity)
                inspected = self.manager.inspect_pending(**identity)
                canceled = self.manager.player_cancel(str(acted["session_id"]), **identity)
                with self.assertRaisesRegex(SaveManagerError, "bounded valid UTF-8"):
                    self.manager.player_confirm(str(acted["session_id"]), **identity)

                for result in (turned, inspected, canceled):
                    self.assertEqual(result["status"], "invalid_state", result)
                    self.assertEqual(
                        result["lifecycle"],
                        {"state": "invalid_state", "kind": "unknown"},
                    )
                self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
                self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_registry_writer_rejects_oversize_state_without_registry_or_save_mutation(self) -> None:
        registry_before = self.manager.registry_path.read_bytes()
        save_dirs_before = tuple(sorted(path.name for path in (self.root / "saves").iterdir()))

        with self.assertRaisesRegex(SaveManagerError, "oversized string|bounded size limit"):
            self.manager.create_save(
                campaign="campaigns/minimal",
                label="x" * (MAX_REGISTRY_STATE_BYTES + 1),
                activate=False,
            )

        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)
        self.assertEqual(
            tuple(sorted(path.name for path in (self.root / "saves").iterdir())),
            save_dirs_before,
        )

    def test_failed_save_publication_does_not_delete_replacement_directory(self) -> None:
        registry_before = self.manager.registry_path.read_bytes()
        saves_root = self.root / "saves"
        save_dirs_before = {path.parent for path in saves_root.rglob("save.yaml")}
        replacement_marker: Path | None = None
        moved_created: Path | None = None

        def race_and_fail(_registry: dict[str, object]) -> None:
            nonlocal replacement_marker, moved_created
            created = next(
                path.parent
                for path in saves_root.rglob("save.yaml")
                if path.parent not in save_dirs_before
            )
            moved_created = created.with_name(f"{created.name}.original-raced")
            created.rename(moved_created)
            created.mkdir()
            replacement_marker = created / "other-process.txt"
            replacement_marker.write_text("preserve", encoding="utf-8")
            raise SaveManagerError("forced registry publication failure")

        with (
            mock.patch.object(
                self.manager,
                "write_registry_unlocked",
                side_effect=race_and_fail,
            ),
            self.assertRaisesRegex(SaveManagerError, "forced registry publication failure"),
        ):
            self.manager.create_save(
                campaign="campaigns/minimal",
                label="Raced",
                activate=False,
            )

        assert replacement_marker is not None
        assert moved_created is not None
        self.assertEqual(replacement_marker.read_text(encoding="utf-8"), "preserve")
        self.assertTrue(moved_created.is_dir())
        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)

    def test_save_rollback_rechecks_entry_after_atomic_quarantine(self) -> None:
        target = self.manager.root / "rollback" / "created-save"
        target.mkdir(parents=True)
        (target / "owned.txt").write_text("owned", encoding="utf-8")
        identity = (target.stat().st_dev, target.stat().st_ino)
        moved = target.with_name("created-save.original")
        replacement_marker = target / "other-process.txt"
        real_stat = os.stat
        swapped = False

        def swap_after_identity_check(path: object, *args: object, **kwargs: object) -> os.stat_result:
            nonlocal swapped
            result = real_stat(path, *args, **kwargs)
            if path == target.name and kwargs.get("dir_fd") is not None and not swapped:
                target.rename(moved)
                target.mkdir()
                replacement_marker.write_text("preserve", encoding="utf-8")
                swapped = True
            return result

        with mock.patch("rpg_engine.save_manager.os.stat", side_effect=swap_after_identity_check):
            remove_created_directory_if_unchanged(self.manager.root, target, identity)

        self.assertEqual(replacement_marker.read_text(encoding="utf-8"), "preserve")
        self.assertTrue(moved.is_dir())

    def test_post_replace_registry_fsync_failure_preserves_registered_save(self) -> None:
        source_save_id = str(self.started["save"]["id"])
        operations = (
            ("create", lambda: self.manager.create_save(campaign="campaigns/minimal", activate=False)),
            ("duplicate", lambda: self.manager.duplicate_save(source_save_id, activate=False)),
        )
        real_fsync = os.fsync
        real_replace = os.replace

        for operation, publish in operations:
            before_paths = {
                str(record["path"])
                for record in self.manager.read_registry()["saves"]
            }
            registry_replaced = False

            def fail_directory_fsync(fd: int) -> None:
                if registry_replaced:
                    raise OSError("forced directory fsync failure")
                real_fsync(fd)

            def mark_registry_replace(
                source: object,
                destination: object,
                *args: object,
                **kwargs: object,
            ) -> None:
                nonlocal registry_replaced
                real_replace(source, destination, *args, **kwargs)
                if destination == self.manager.registry_path.name:
                    registry_replaced = True

            with (
                self.subTest(operation=operation),
                mock.patch("rpg_engine.save_manager.os.replace", side_effect=mark_registry_replace),
                mock.patch("rpg_engine.save_manager.os.fsync", side_effect=fail_directory_fsync),
                self.assertRaisesRegex(SaveManagerError, "durability is uncertain"),
            ):
                publish()

            registry = self.manager.read_registry()
            added = [record for record in registry["saves"] if str(record["path"]) not in before_paths]
            self.assertEqual(len(added), 1, registry)
            self.assertTrue((self.root / str(added[0]["path"])).is_dir())

    def test_registry_schema_version_requires_exact_string_without_rewrite(self) -> None:
        registry = self.manager.read_registry()
        registry["schema_version"] = 1
        malformed = json.dumps(registry, ensure_ascii=False, sort_keys=True) + "\n"
        self.manager.registry_path.write_text(malformed, encoding="utf-8")

        with self.assertRaisesRegex(SaveManagerError, "schema_version"):
            self.manager.read_registry()
        self.assertEqual(self.manager.registry_path.read_text(encoding="utf-8"), malformed)
        with self.assertRaisesRegex(SaveManagerError, "schema_version"):
            self.manager.write_registry(registry)
        self.assertEqual(self.manager.registry_path.read_text(encoding="utf-8"), malformed)

    def test_registry_symlink_escape_is_rejected_without_pending_or_external_mutation(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        revision_before = self.manager.pending_lifecycle_revision_path().read_bytes()
        registry_before = self.manager.registry_path.read_bytes()
        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            external_registry = Path(external_tmp) / "external-registry.json"
            external_registry.write_bytes(registry_before)
            self.manager.registry_path.unlink()
            self.manager.registry_path.symlink_to(external_registry)

            inspected = self.manager.inspect_pending()
            turned = self.manager.player_turn(user_text="继续休息")

            self.assertEqual(inspected["status"], "invalid_state", inspected)
            self.assertEqual(
                inspected["lifecycle"],
                {"state": "invalid_state", "kind": "unknown"},
            )
            self.assertEqual(turned["status"], "invalid_state", turned)
            self.assertEqual(
                turned["lifecycle"],
                {"state": "invalid_state", "kind": "unknown"},
            )
            self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
            self.assertEqual(
                self.manager.pending_lifecycle_revision_path().read_bytes(),
                revision_before,
            )
            self.assertEqual(external_registry.read_bytes(), registry_before)

    def test_registry_read_aborts_if_parent_is_replaced_after_open(self) -> None:
        registry_before = self.manager.registry_path.read_bytes()
        local_parent = self.manager.registry_path.parent
        moved_parent = self.root / ".aigm-read-raced"
        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            external_parent = Path(external_tmp)
            external_registry = external_parent / self.manager.registry_path.name
            external_registry.write_bytes(registry_before)
            swapped = False

            def replace_parent(root: Path, path: Path, directory_fd: int) -> bool:
                nonlocal swapped
                if not swapped:
                    local_parent.rename(moved_parent)
                    local_parent.symlink_to(external_parent, target_is_directory=True)
                    swapped = True
                return registry_parent_matches(root, path, directory_fd)

            with (
                mock.patch(
                    "rpg_engine.save_manager.registry_parent_matches",
                    side_effect=replace_parent,
                ),
                self.assertRaisesRegex(SaveManagerError, "changed while being read"),
            ):
                self.manager.read_registry()

            self.assertEqual((moved_parent / self.manager.registry_path.name).read_bytes(), registry_before)
            self.assertEqual(external_registry.read_bytes(), registry_before)

    def test_pending_read_aborts_if_file_is_replaced_after_open(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_path = self.manager.pending_action_path()
        pending_before = pending_path.read_bytes()
        moved_pending = pending_path.with_name("pending-player-action.raced.json")
        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            external_pending = Path(external_tmp) / "external-pending.json"
            external_pending.write_bytes(pending_before)
            swapped = False

            def replace_pending(
                directory_fd: int,
                name: str,
                expected: os.stat_result | None,
            ) -> bool:
                nonlocal swapped
                if not swapped:
                    pending_path.rename(moved_pending)
                    pending_path.symlink_to(external_pending)
                    swapped = True
                return registry_file_matches(directory_fd, name, expected)

            with (
                mock.patch(
                    "rpg_engine.save_manager.registry_file_matches",
                    side_effect=replace_pending,
                ),
                self.assertRaisesRegex(SaveManagerError, "pending player action is invalid"),
            ):
                self.manager.read_pending_action()

            self.assertEqual(moved_pending.read_bytes(), pending_before)
            self.assertEqual(external_pending.read_bytes(), pending_before)

    def test_pending_reader_rejects_external_leaf_symlink_as_invalid_state(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_path = self.manager.pending_action_path()
        pending_before = pending_path.read_bytes()
        moved_pending = pending_path.with_name("pending-player-action.local.json")
        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            external_pending = Path(external_tmp) / "external-pending.json"
            external_pending.write_bytes(pending_before)
            pending_path.rename(moved_pending)
            pending_path.symlink_to(external_pending)

            with self.assertRaisesRegex(SaveManagerError, "pending player action is invalid"):
                self.manager.read_pending_action()

            self.assertEqual(moved_pending.read_bytes(), pending_before)
            self.assertEqual(external_pending.read_bytes(), pending_before)

    def test_pending_reader_rejects_internal_leaf_symlink_without_following_it(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_path = self.manager.pending_action_path()
        pending_before = pending_path.read_bytes()
        internal_target = pending_path.with_name("alternate-pending.json")
        pending_path.rename(internal_target)
        pending_path.symlink_to(internal_target.name)

        with self.assertRaisesRegex(SaveManagerError, "pending player action is invalid"):
            self.manager.read_pending_action()

        self.assertEqual(internal_target.read_bytes(), pending_before)

    def test_registry_reader_rejects_internal_parent_symlink_before_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alternate = root / "alternate-authority"
            alternate.mkdir()
            forged = {
                "schema_version": "1",
                "active_save_id": None,
                "campaigns": [],
                "saves": [],
            }
            (alternate / "save-registry.json").write_text(
                json.dumps(forged) + "\n",
                encoding="utf-8",
            )
            (root / ".aigm").symlink_to(alternate, target_is_directory=True)
            manager = SaveManager(root)

            with self.assertRaisesRegex(SaveManagerError, "registry is invalid JSON"):
                manager.read_registry()

    def test_anchored_unlink_preserves_replacement_created_after_identity_check(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_path = self.manager.pending_action_path()
        pending_before = pending_path.read_bytes()
        moved_pending = pending_path.with_name("pending-player-action.original.json")
        real_rename = os.rename
        swapped = False

        def swap_before_quarantine(
            source: object,
            destination: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal swapped
            if source == pending_path.name and not swapped:
                directory_fd = kwargs["src_dir_fd"]
                real_rename(
                    source,
                    moved_pending.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                replacement_fd = os.open(
                    pending_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                try:
                    os.write(replacement_fd, pending_before)
                finally:
                    os.close(replacement_fd)
                swapped = True
            real_rename(source, destination, *args, **kwargs)

        with (
            mock.patch("rpg_engine.save_manager.os.rename", side_effect=swap_before_quarantine),
            self.assertRaisesRegex(SaveManagerError, "path changed before removal"),
        ):
            unlink_anchored_file(self.manager.root, pending_path, label="pending player action")

        self.assertEqual(pending_path.read_bytes(), pending_before)
        self.assertEqual(moved_pending.read_bytes(), pending_before)

    def test_anchored_unlink_restores_symlink_replacement_without_following_it(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_path = self.manager.pending_action_path()
        pending_before = pending_path.read_bytes()
        moved_pending = pending_path.with_name("pending-player-action.original-symlink.json")
        symlink_target = pending_path.with_name("other-owner-evidence.json")
        symlink_target.write_text("preserve\n", encoding="utf-8")
        real_rename = os.rename
        swapped = False

        def swap_before_quarantine(
            source: object,
            destination: object,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal swapped
            if source == pending_path.name and not swapped:
                directory_fd = kwargs["src_dir_fd"]
                real_rename(
                    source,
                    moved_pending.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                os.symlink(
                    symlink_target.name,
                    pending_path.name,
                    dir_fd=directory_fd,
                )
                swapped = True
            real_rename(source, destination, *args, **kwargs)

        with (
            mock.patch("rpg_engine.save_manager.os.rename", side_effect=swap_before_quarantine),
            self.assertRaisesRegex(SaveManagerError, "path changed before removal"),
        ):
            unlink_anchored_file(self.manager.root, pending_path, label="pending player action")

        self.assertTrue(pending_path.is_symlink())
        self.assertEqual(os.readlink(pending_path), symlink_target.name)
        self.assertEqual(symlink_target.read_text(encoding="utf-8"), "preserve\n")
        self.assertEqual(moved_pending.read_bytes(), pending_before)

    def test_workspace_lock_prevents_split_holder_after_leaf_replacement(self) -> None:
        lock_path = self.manager.confirmation_lock_path()
        first_entered = threading.Event()
        release_first = threading.Event()

        def hold_first() -> None:
            with process_file_lock(
                lock_path,
                root=self.manager.root,
                timeout=1,
                unavailable_message="owner lock unavailable",
                timeout_message="owner lock timeout",
            ):
                first_entered.set()
                release_first.wait(timeout=2)

        holder = threading.Thread(target=hold_first)
        holder.start()
        self.assertTrue(first_entered.wait(timeout=1))
        moved_lock = lock_path.with_name("pending-player-action.original.lock")
        lock_path.rename(moved_lock)

        try:
            with self.assertRaisesRegex(SaveManagerError, "owner lock timeout"):
                with process_file_lock(
                    lock_path,
                    root=self.manager.root,
                    timeout=0.1,
                    unavailable_message="owner lock unavailable",
                    timeout_message="owner lock timeout",
                ):
                    self.fail("replacement lock obtained concurrent owner authority")
        finally:
            release_first.set()
            holder.join(timeout=2)
        self.assertFalse(holder.is_alive())

    @unittest.skipUnless(hasattr(os, "fork"), "fork inheritance is POSIX-only")
    def test_forked_child_does_not_inherit_reentrant_lock_authority(self) -> None:
        lock_path = self.manager.confirmation_lock_path()
        read_fd, write_fd = os.pipe()
        with confirmation_claim_lock(lock_path, root=self.manager.root):
            child_pid = os.fork()
            if child_pid == 0:  # pragma: no cover - assertions run in the parent.
                os.close(read_fd)
                result = {
                    "inherited_confirmation_state": confirmation_lock_held_by_current_thread(
                        lock_path
                    )
                }
                try:
                    with process_file_lock(
                        lock_path,
                        root=self.manager.root,
                        timeout=0.1,
                        unavailable_message="owner lock unavailable",
                        timeout_message="owner lock timeout",
                    ):
                        result["outcome"] = "acquired"
                except SaveManagerError as exc:
                    result["outcome"] = str(exc)
                os.write(write_fd, json.dumps(result).encode("utf-8"))
                os.close(write_fd)
                os._exit(0)
            os.close(write_fd)
            payload = os.read(read_fd, 4096)
            os.close(read_fd)
            _, status = os.waitpid(child_pid, 0)

        self.assertEqual(status, 0)
        result = json.loads(payload.decode("utf-8"))
        self.assertFalse(result["inherited_confirmation_state"], result)
        self.assertEqual(result["outcome"], "owner lock timeout", result)

    @unittest.skipUnless(hasattr(os, "fork"), "fork cleanup is POSIX-only")
    def test_forked_child_unwind_does_not_release_parent_kernel_lock(self) -> None:
        lock_path = self.manager.confirmation_lock_path()
        read_fd, write_fd = os.pipe()

        def fork_and_probe() -> tuple[str, int] | None:
            with process_file_lock(
                lock_path,
                root=self.manager.root,
                timeout=1,
                unavailable_message="owner lock unavailable",
                timeout_message="owner lock timeout",
            ):
                child_pid = os.fork()
                if child_pid == 0:  # pragma: no cover - assertions run in parent.
                    return None
                os.close(write_fd)
                self.assertEqual(os.read(read_fd, 64), b"child-unwound")
                os.close(read_fd)
                outcomes: list[str] = []

                def contend() -> None:
                    try:
                        with process_file_lock(
                            lock_path,
                            root=self.manager.root,
                            timeout=0.1,
                            unavailable_message="owner lock unavailable",
                            timeout_message="owner lock timeout",
                        ):
                            outcomes.append("acquired")
                    except SaveManagerError as exc:
                        outcomes.append(str(exc))

                contender = threading.Thread(target=contend)
                contender.start()
                contender.join(timeout=1)
                self.assertFalse(contender.is_alive())
                _, status = os.waitpid(child_pid, 0)
                return outcomes[0], status

        result = fork_and_probe()
        if result is None:  # pragma: no cover - child reports only through the pipe.
            os.close(read_fd)
            os.write(write_fd, b"child-unwound")
            os.close(write_fd)
            os._exit(0)

        outcome, status = result
        self.assertEqual(status, 0)
        self.assertEqual(outcome, "owner lock timeout")

    def test_anchored_unlink_does_not_delete_after_parent_leaves_workspace(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_path = self.manager.pending_action_path()
        pending_before = pending_path.read_bytes()
        local_parent = pending_path.parent
        real_rename = os.rename
        moved = False

        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            moved_parent = Path(external_tmp) / "moved-aigm"

            def move_parent_after_quarantine(
                source: object,
                destination: object,
                *args: object,
                **kwargs: object,
            ) -> None:
                nonlocal moved
                real_rename(source, destination, *args, **kwargs)
                if source == pending_path.name and not moved:
                    real_rename(local_parent, moved_parent)
                    local_parent.mkdir()
                    moved = True

            with (
                mock.patch(
                    "rpg_engine.save_manager.os.rename",
                    side_effect=move_parent_after_quarantine,
                ),
                self.assertRaisesRegex(SaveManagerError, "path changed during removal"),
            ):
                unlink_anchored_file(
                    self.manager.root,
                    pending_path,
                    label="pending player action",
                )

            quarantined = list(moved_parent.glob(".pending-player-action.json.*.remove"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual(quarantined[0].read_bytes(), pending_before)

    def test_save_rollback_does_not_delete_after_parent_leaves_workspace(self) -> None:
        local_parent = self.manager.root / "rollback-parent"
        target = local_parent / "created-save"
        target.mkdir(parents=True)
        marker = target / "owned.txt"
        marker.write_text("owned", encoding="utf-8")
        identity = (target.stat().st_dev, target.stat().st_ino)
        real_rename = os.rename
        moved = False

        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            moved_parent = Path(external_tmp) / "moved-rollback-parent"

            def move_parent_after_quarantine(
                source: object,
                destination: object,
                *args: object,
                **kwargs: object,
            ) -> None:
                nonlocal moved
                real_rename(source, destination, *args, **kwargs)
                if source == target.name and not moved:
                    real_rename(local_parent, moved_parent)
                    local_parent.mkdir()
                    moved = True

            with mock.patch(
                "rpg_engine.save_manager.os.rename",
                side_effect=move_parent_after_quarantine,
            ):
                remove_created_directory_if_unchanged(
                    self.manager.root,
                    target,
                    identity,
                )

            quarantined = list(moved_parent.glob(".created-save.*.rollback"))
            self.assertEqual(len(quarantined), 1)
            self.assertEqual((quarantined[0] / "owned.txt").read_text(encoding="utf-8"), "owned")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO evidence is POSIX-only")
    def test_pending_reader_rejects_fifo_without_blocking(self) -> None:
        pending_path = self.manager.pending_action_path()
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(pending_path)

        with self.assertRaisesRegex(SaveManagerError, "pending player action is invalid"):
            self.manager.read_pending_action()

    def test_registry_write_aborts_if_parent_is_replaced_before_publication(self) -> None:
        registry_before = self.manager.registry_path.read_bytes()
        registry = self.manager.read_registry()
        registry["active_save_id"] = None
        local_parent = self.manager.registry_path.parent
        moved_parent = self.root / ".aigm-write-raced"
        with tempfile.TemporaryDirectory(dir=self.root.parent) as external_tmp:
            external_parent = Path(external_tmp)
            external_registry = external_parent / self.manager.registry_path.name
            external_registry.write_bytes(registry_before)
            swapped = False

            def replace_parent(root: Path, path: Path, directory_fd: int) -> bool:
                nonlocal swapped
                if not swapped:
                    local_parent.rename(moved_parent)
                    local_parent.symlink_to(external_parent, target_is_directory=True)
                    swapped = True
                return registry_parent_matches(root, path, directory_fd)

            with (
                mock.patch(
                    "rpg_engine.save_manager.registry_parent_matches",
                    side_effect=replace_parent,
                ),
                self.assertRaisesRegex(
                    SaveManagerError,
                    "changed before publication|save registry lock is unavailable",
                ),
            ):
                self.manager.write_registry(registry)

            self.assertEqual((moved_parent / self.manager.registry_path.name).read_bytes(), registry_before)
            self.assertEqual(external_registry.read_bytes(), registry_before)

    def test_clarification_payload_id_mismatch_fails_closed(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        pending = self.manager.read_pending_clarification()
        self.assertIsNotNone(pending)
        assert pending is not None
        owner_id = str(pending["clarification_id"])
        for conflicting_id in (f" {owner_id} ", 7, "clarification:conflicting"):
            with self.subTest(conflicting_id=conflicting_id):
                tampered = {
                    **pending,
                    "clarification": {
                        **dict(pending["clarification"]),
                        "clarification_id": conflicting_id,
                    },
                }
                self.manager.write_pending_clarification(tampered)
                before = self.manager.pending_clarification_path().read_bytes()

                with self.assertRaisesRegex(SaveManagerError, "conflicting identity"):
                    self.manager.inspect_pending()

                self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_invalid_clarification_candidate_digest_fails_closed(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=mismatch_clarification_runtime()):
            self.manager.player_turn(
                user_text="保持原样",
                external_intent_candidate={"kind": "single", "mode": "action", "action": "travel", "slots": {}},
            )
        pending = self.manager.read_pending_clarification()
        self.assertIsNotNone(pending)
        assert pending is not None
        pending["external_candidate_digest"] = "not-a-digest"
        self.manager.write_pending_clarification(pending)
        before = self.manager.pending_clarification_path().read_bytes()

        with self.assertRaisesRegex(SaveManagerError, "invalid candidate evidence"):
            self.manager.inspect_pending()

        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_pending_reader_fails_closed_on_duplicate_oversize_and_deep_json(self) -> None:
        path = self.manager.pending_clarification_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"schema_version":"1","schema_version":"1"}\n', encoding="utf-8")
        with self.assertRaises(SaveManagerError):
            self.manager.inspect_pending()
        path.write_bytes(b'{"payload":"' + (b"x" * (1024 * 1024)) + b'"}')
        with self.assertRaisesRegex(SaveManagerError, "bounded size"):
            self.manager.inspect_pending()
        nested: object = "leaf"
        for _ in range(70):
            nested = [nested]
        path.write_text(json.dumps({"payload": nested}), encoding="utf-8")
        with self.assertRaisesRegex(SaveManagerError, "structure limit"):
            self.manager.inspect_pending()
        path.write_text('{"payload":' + ("[" * 1600) + "0" + ("]" * 1600) + "}", encoding="utf-8")
        with self.assertRaisesRegex(SaveManagerError, "invalid|structure limit"):
            self.manager.inspect_pending()

    def test_tampered_ttl_fails_closed(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        pending["ttl_seconds"] = 1
        pending["expires_at"] = "2099-01-01T00:00:00+00:00"
        self.manager.write_pending_action(pending)

        with self.assertRaisesRegex(SaveManagerError, "invalid TTL"):
            self.manager.inspect_pending()

    def test_noninteger_and_overflowing_ttl_evidence_fails_closed(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        original = self.manager.read_pending_action()
        for invalid_ttl in (1800.5, "1800", True):
            with self.subTest(ttl=invalid_ttl):
                self.manager.write_pending_action({**original, "ttl_seconds": invalid_ttl})
                with self.assertRaisesRegex(SaveManagerError, "invalid TTL"):
                    self.manager.inspect_pending()
        overflow = {
            **original,
            "created_at": "9999-12-31T23:59:59+00:00",
            "expires_at": "9999-12-31T23:59:59+00:00",
        }
        self.manager.write_pending_action(overflow)
        with self.assertRaisesRegex(SaveManagerError, "invalid TTL"):
            self.manager.inspect_pending()

    def test_noncanonical_pending_timestamps_fail_closed_without_rewrite(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        original = self.manager.read_pending_action()
        self.assertIsNotNone(original)
        assert original is not None
        created = datetime.fromisoformat(str(original["created_at"]))
        expires = datetime.fromisoformat(str(original["expires_at"]))
        plus_one = timezone(timedelta(hours=1))
        cases = (
            ({"created_at": f" {original['created_at']} "}, "invalid creation time"),
            ({"expires_at": f" {original['expires_at']} "}, "invalid TTL"),
            (
                {"created_at": created.replace(tzinfo=None).isoformat(), "expires_at": expires.replace(tzinfo=None).isoformat()},
                "invalid creation time",
            ),
            (
                {
                    "created_at": str(original["created_at"]).replace("+00:00", "Z"),
                    "expires_at": str(original["expires_at"]).replace("+00:00", "Z"),
                },
                "invalid creation time",
            ),
            (
                {"created_at": created.astimezone(plus_one).isoformat(), "expires_at": expires.astimezone(plus_one).isoformat()},
                "invalid creation time",
            ),
        )
        for mutation, message in cases:
            with self.subTest(mutation=mutation):
                self.manager.write_pending_action({**original, **mutation})
                before = self.manager.pending_action_path().read_bytes()

                with self.assertRaisesRegex(SaveManagerError, message):
                    self.manager.inspect_pending()

                self.assertEqual(self.manager.pending_action_path().read_bytes(), before)

    def test_malformed_pending_cancel_returns_invalid_state_and_preserves_bytes(self) -> None:
        path = self.manager.pending_action_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
        before = path.read_bytes()

        canceled = self.manager.player_cancel("player_action:unknown")

        self.assertEqual(canceled["status"], "invalid_state", canceled)
        self.assertEqual(canceled["lifecycle"], {"state": "invalid_state", "kind": "action"})
        self.assertEqual(path.read_bytes(), before)

    def test_deep_corrected_candidate_fails_closed_and_preserves_clarification(self) -> None:
        original_text = "保持原样"
        original_candidate = {"kind": "single", "mode": "action", "action": "travel", "slots": {}}
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=mismatch_clarification_runtime()):
            created = self.manager.player_turn(
                user_text=original_text,
                external_intent_candidate=original_candidate,
            )
        clarification_id = str(created["pending_clarification_id"])
        before = self.manager.pending_clarification_path().read_bytes()
        nested: object = "leaf"
        for _ in range(12000):
            nested = [nested]

        with self.assertRaisesRegex(SaveManagerError, "not canonical JSON"):
            self.manager.player_turn(
                user_text=original_text,
                expected_pending_id=clarification_id,
                clarification_id=clarification_id,
                external_intent_candidate={"payload": nested},
            )

        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_missing_registry_record_with_existing_save_is_invalid_and_preserved(self) -> None:
        facts_before = gameplay_snapshot(self.save_path)
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        registry = self.manager.read_registry()
        registry["saves"] = []
        registry["active_save_id"] = None
        self.manager.write_registry(registry)

        invalid = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))
        self.assert_lifecycle(invalid, state="invalid_state", kind="clarification")
        self.assertTrue(self.manager.pending_clarification_path().exists())
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_missing_registry_record_with_existing_action_save_is_invalid_and_preserved(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        before = self.manager.pending_action_path().read_bytes()
        registry = self.manager.read_registry()
        registry["saves"] = []
        registry["active_save_id"] = None
        self.manager.write_registry(registry)

        invalid = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))

        self.assert_lifecycle(invalid, state="invalid_state", kind="action")
        self.assertEqual(self.manager.pending_action_path().read_bytes(), before)
        self.assertEqual(self.manager.read_pending_action()["session_id"], acted["session_id"])

    def test_unrecoverable_orphan_clarification_is_removed_without_gameplay_write(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        registry = self.manager.read_registry()
        registry["saves"] = []
        registry["active_save_id"] = None
        self.manager.write_registry(registry)
        shutil.rmtree(self.save_path)

        orphaned = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))

        self.assert_lifecycle(orphaned, state="orphaned", kind="clarification")
        self.assertFalse(self.manager.pending_clarification_path().exists())

    def test_registered_missing_save_path_is_invalid_and_preserves_pending(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        registry_before = self.manager.registry_path.read_bytes()
        shutil.rmtree(self.save_path)

        invalid = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))

        self.assertFalse(invalid["ok"], invalid)
        self.assert_lifecycle(invalid, state="invalid_state", kind="action")
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(self.manager.read_pending_action()["session_id"], acted["session_id"])
        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)

    def test_unclaimed_action_with_deleted_save_is_removed_as_orphan(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        registry = self.manager.read_registry()
        registry["saves"] = []
        registry["active_save_id"] = None
        self.manager.write_registry(registry)
        shutil.rmtree(self.save_path)

        orphaned = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))

        self.assert_lifecycle(orphaned, state="orphaned", kind="action")
        self.assertFalse(self.manager.pending_action_path().exists())

    def test_orphan_action_with_matching_receipt_is_preserved_as_invalid_state(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        original_pending = self.manager.read_pending_action()
        assert original_pending is not None
        confirmed = self.manager.player_confirm(str(acted["session_id"]))
        self.assertTrue(confirmed["ok"], confirmed)
        self.assertIsNotNone(self.manager.read_confirmation_receipt())
        self.manager.write_pending_action(original_pending)
        pending_before = self.manager.pending_action_path().read_bytes()
        registry = self.manager.read_registry()
        registry["saves"] = []
        registry["active_save_id"] = None
        self.manager.write_registry(registry)
        shutil.rmtree(self.save_path)

        inspected = self.manager.inspect_pending(
            save_path=str(self.started["save"]["path"]),
        )

        self.assertEqual(inspected["status"], "invalid_state", inspected)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

    def test_orphan_action_with_conflicting_binding_receipt_is_preserved_as_invalid_state(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        original_pending = self.manager.read_pending_action()
        assert original_pending is not None
        confirmed = self.manager.player_confirm(str(acted["session_id"]))
        self.assertTrue(confirmed["ok"], confirmed)
        receipt = self.manager.read_confirmation_receipt()
        assert receipt is not None
        receipt["save_id"] = "save:conflicting"
        receipt["save_path"] = "saves/conflicting"
        receipt["receipt_digest"] = stable_payload_digest(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
        self.manager.write_confirmation_receipt(receipt)
        self.manager.confirmation_history_path().unlink(missing_ok=True)
        self.manager.write_pending_action(original_pending)
        pending_before = self.manager.pending_action_path().read_bytes()
        registry = self.manager.read_registry()
        registry["saves"] = []
        registry["active_save_id"] = None
        self.manager.write_registry(registry)
        shutil.rmtree(self.save_path)

        inspected = self.manager.inspect_pending(
            save_path=str(self.started["save"]["path"]),
        )

        self.assertEqual(inspected["status"], "invalid_state", inspected)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

    def test_wrong_explicit_save_cannot_orphan_clean_another_save_pending(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        original_path = str(self.started["save"]["path"])
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        registry = self.manager.read_registry()
        second_record = next(
            dict(record)
            for record in registry["saves"]
            if record.get("id") == second["save"]["id"]
        )
        registry["saves"] = [second_record]
        registry["active_save_id"] = second_record["id"]
        self.manager.write_registry(registry)
        shutil.rmtree(self.save_path)

        conflict = self.manager.inspect_pending(save_path=str(second_record["path"]))

        self.assert_lifecycle(conflict, state="conflict", kind="action")
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

        orphaned = self.manager.inspect_pending(save_path=original_path)
        self.assert_lifecycle(orphaned, state="orphaned", kind="action")
        self.assertFalse(self.manager.pending_action_path().exists())

    def test_conflicting_or_archived_save_binding_is_preserved_as_invalid_state(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        pending = self.manager.read_pending_clarification()
        pending["save_id"] = "save:conflict"
        self.manager.write_pending_clarification(pending)

        conflict = self.manager.inspect_pending()
        self.assert_lifecycle(conflict, state="invalid_state", kind="clarification")
        self.assertTrue(self.manager.pending_clarification_path().exists())

        pending["save_id"] = self.started["save"]["id"]
        self.manager.write_pending_clarification(pending)
        registry = self.manager.read_registry()
        registry["saves"] = [
            {**dict(record), "archived": True}
            if record.get("id") == self.started["save"]["id"]
            else record
            for record in registry["saves"]
        ]
        self.manager.write_registry(registry)
        archived = self.manager.inspect_pending()
        self.assert_lifecycle(archived, state="invalid_state", kind="clarification")
        self.assertTrue(self.manager.pending_clarification_path().exists())

    def test_same_save_id_at_different_registry_path_is_invalid_and_preserved(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        before = self.manager.pending_clarification_path().read_bytes()
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        registry = self.manager.read_registry()
        registry["saves"] = [
            {
                **dict(record),
                "path": second["save"]["path"],
            }
            for record in registry["saves"]
            if record.get("id") == self.started["save"]["id"]
        ]
        self.manager.write_registry(registry)

        invalid = self.manager.inspect_pending()

        self.assert_lifecycle(invalid, state="invalid_state", kind="clarification")
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_duplicate_registry_save_id_is_invalid_even_when_first_record_matches(self) -> None:
        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=clarification_runtime()):
            self.manager.player_turn(user_text="使用那个物品")
        legacy = self.manager.read_pending_clarification()
        for key in ("expires_at", "ttl_seconds", "clarification_origin", "external_candidate_digest"):
            legacy.pop(key)
        self.manager.write_pending_clarification(legacy)
        before = self.manager.pending_clarification_path().read_bytes()
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        registry = self.manager.read_registry()
        matching = next(
            dict(record)
            for record in registry["saves"]
            if record.get("id") == self.started["save"]["id"]
        )
        conflicting = {
            **matching,
            "path": second["save"]["path"],
        }
        registry["saves"] = [matching, conflicting]
        self.manager.write_registry(registry)

        invalid = self.manager.inspect_pending(save_path=str(self.started["save"]["path"]))

        self.assert_lifecycle(invalid, state="invalid_state", kind="clarification")
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)

    def test_duplicate_registry_evidence_blocks_turn_refresh_and_cancel_without_mutation(self) -> None:
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        acted = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)
        registry = self.manager.read_registry()
        matching = next(
            dict(record)
            for record in registry["saves"]
            if record.get("id") == self.started["save"]["id"]
        )
        registry["saves"].append({**matching, "path": second["save"]["path"]})
        self.manager.write_registry(registry)
        registry_before = self.manager.registry_path.read_bytes()

        turned = self.manager.player_turn(
            user_text="休息到早上",
            expected_pending_id=str(acted["session_id"]),
        )
        self.assertFalse(turned["ok"], turned)
        self.assertEqual(turned["status"], "invalid_state", turned)
        self.assertEqual(turned["lifecycle"], {"state": "invalid_state", "kind": "unknown"})
        with self.assertRaisesRegex(SaveManagerError, "duplicate id"):
            self.manager.require_active_save(refresh=True)
        canceled = self.manager.player_cancel(str(acted["session_id"]))

        self.assertFalse(canceled["ok"], canceled)
        self.assertEqual(canceled["status"], "invalid_state")
        self.assertEqual(self.manager.registry_path.read_bytes(), registry_before)
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_switch_prevalidates_dual_pending_before_registry_write(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        original_active = self.manager.read_registry()["active_save_id"]
        created_at = datetime.now(timezone.utc).isoformat()
        self.manager.write_pending_clarification(
            {
                "schema_version": "1",
                "clarification_id": "clarification:switch-dual",
                "save_id": self.started["save"]["id"],
                "save_path": self.started["save"]["path"],
                "created_at": created_at,
                "expires_at": (
                    datetime.fromisoformat(created_at) + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
                ).isoformat(),
                "ttl_seconds": DEFAULT_PENDING_ACTION_TTL_SECONDS,
                "clarification_origin": "player_input_ambiguity",
                "original_user_text": "which one",
                "external_candidate_digest": "",
                "clarification": {"question": "which one"},
            }
        )

        with self.assertRaisesRegex(SaveManagerError, "multiple active sessions"):
            self.manager.switch_save(str(second["save"]["id"]))

        self.assertEqual(self.manager.read_registry()["active_save_id"], original_active)
        self.assertEqual(self.manager.read_pending_action()["session_id"], acted["session_id"])
        self.assertIsNotNone(self.manager.read_pending_clarification())

    def test_dual_active_state_cannot_bypass_confirmation_invariant(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        facts_before = gameplay_snapshot(self.save_path)
        created_at = datetime.now(timezone.utc).isoformat()
        self.manager.write_pending_clarification(
            {
                "schema_version": "1",
                "clarification_id": "clarification:dual",
                "save_id": self.started["save"]["id"],
                "save_path": self.started["save"]["path"],
                "created_at": created_at,
                "expires_at": (
                    datetime.fromisoformat(created_at) + timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
                ).isoformat(),
                "ttl_seconds": DEFAULT_PENDING_ACTION_TTL_SECONDS,
                "clarification_origin": "player_input_ambiguity",
                "original_user_text": "which one",
                "external_candidate_digest": "",
                "clarification": {"question": "which one"},
            }
        )

        with self.assertRaisesRegex(SaveManagerError, "multiple active sessions"):
            self.manager.player_confirm(str(acted["session_id"]))
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_two_concurrent_first_publications_leave_exactly_one_pending(self) -> None:
        barrier = threading.Barrier(2)

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            barrier.wait(timeout=5)
            return ready_runtime("cmd:concurrent").act()

        results: list[dict[str, object]] = []

        def run() -> None:
            results.append(SaveManager(self.root).player_turn(user_text="休息到早上"))

        with mock.patch("rpg_engine.save_manager.GMRuntime.from_path", return_value=SimpleNamespace(act=act)):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(sum(bool(result.get("ready_to_confirm")) for result in results), 1, results)
        self.assertEqual(sum(result.get("status") == "pending_conflict" for result in results), 1, results)
        self.assertIsNotNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_default_save_publication_conflicts_if_active_save_switches_inflight(self) -> None:
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("active Save switch runtime gate timed out")
            return ready_runtime("cmd:active-switch").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(user_text="休息到早上")

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                switched = self.manager.switch_save(str(second["save"]["id"]), refresh=False)
                self.assertTrue(switched["ok"], switched)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        conflict = outcome["result"]
        self.assertEqual(conflict["status"], "pending_conflict", conflict)
        self.assertEqual(conflict["active_save_id"], second["save"]["id"])
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertEqual(self.manager.read_registry()["active_save_id"], second["save"]["id"])

    def test_default_save_publication_rejects_active_selection_aba(self) -> None:
        original_id = str(self.started["save"]["id"])
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("active Save ABA runtime gate timed out")
            return ready_runtime("cmd:active-selection-aba").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(user_text="休息到早上")

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                self.manager.switch_save(str(second["save"]["id"]), refresh=False)
                self.manager.switch_save(original_id, refresh=False)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        conflict = outcome["result"]
        self.assertEqual(conflict["status"], "pending_conflict", conflict)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertEqual(self.manager.read_registry()["active_save_id"], original_id)

    def test_expired_compare_token_cannot_publish_runtime_result(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        before_facts = gameplay_snapshot(self.save_path)

        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=ready_runtime("cmd:expired-compare"),
            ),
            mock.patch(
                "rpg_engine.save_manager.pending_action_is_expired",
                side_effect=[False, True],
            ),
        ):
            result = self.manager.player_turn(
                user_text="改为继续休息",
                expected_pending_id=str(first["session_id"]),
            )

        self.assertEqual(result["status"], "expired", result)
        self.assert_lifecycle(result, state="expired", kind="action")
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertEqual(gameplay_snapshot(self.save_path), before_facts)

    def test_expired_action_is_preserved_if_save_is_archived_inflight(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        pending_before = self.manager.pending_action_path().read_bytes()
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("expired action Save gate timed out")
            return ready_runtime("cmd:expired-archive").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="改为继续休息",
                save_path=str(self.started["save"]["path"]),
                expected_pending_id=str(first["session_id"]),
            )

        with (
            mock.patch(
                "rpg_engine.save_manager.GMRuntime.from_path",
                return_value=SimpleNamespace(act=act),
            ),
            mock.patch(
                "rpg_engine.save_manager.pending_action_is_expired",
                side_effect=[False, True],
            ),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            registry = self.manager.read_registry()
            registry["saves"] = [
                {**dict(record), "archived": True}
                if record.get("id") == self.started["save"]["id"]
                else record
                for record in registry["saves"]
            ]
            self.manager.write_registry(registry)
            release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        self.assertEqual(outcome["result"]["status"], "pending_conflict", outcome["result"])
        self.assertEqual(self.manager.pending_action_path().read_bytes(), pending_before)

    def test_explicit_save_publication_rechecks_archived_registry_binding(self) -> None:
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("archive publication runtime gate timed out")
            return ready_runtime("cmd:archive-race").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="休息到早上",
                save_path=str(self.started["save"]["path"]),
            )

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                registry = self.manager.read_registry()
                registry["saves"] = [
                    {**dict(record), "archived": True}
                    if record.get("id") == self.started["save"]["id"]
                    else record
                    for record in registry["saves"]
                ]
                self.manager.write_registry(registry)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_explicit_save_publication_rechecks_live_save_health(self) -> None:
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("deleted Save publication runtime gate timed out")
            return ready_runtime("cmd:deleted-save-race").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="休息到早上",
                save_path=str(self.started["save"]["path"]),
            )

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                shutil.rmtree(self.save_path)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_player_turn_publication_rejects_empty_state_aba(self) -> None:
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(user_text: str, *_args: object, **_kwargs: object) -> SimpleNamespace:
            if user_text == "旧请求":
                runtime_started.set()
                if not release_runtime.wait(timeout=20):
                    raise TimeoutError("pending ABA runtime gate timed out")
            return ready_runtime(f"cmd:{user_text}").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(user_text="旧请求")

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                newer = self.manager.player_turn(user_text="新请求")
                self.assertEqual(newer["status"], "ready", newer)
                canceled = self.manager.player_cancel(str(newer["session_id"]))
                self.assertEqual(canceled["status"], "canceled", canceled)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_player_turn_publication_rejects_revision_loss_after_aba(self) -> None:
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(user_text: str, *_args: object, **_kwargs: object) -> SimpleNamespace:
            if user_text == "旧请求":
                runtime_started.set()
                if not release_runtime.wait(timeout=20):
                    raise TimeoutError("pending revision-loss runtime gate timed out")
            if user_text == "只读查询":
                return result_object(
                    {
                        "ok": True,
                        "status": "query",
                        "action": "query",
                        "warnings": [],
                        "errors": [],
                    }
                )
            return ready_runtime(f"cmd:{user_text}").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(user_text="旧请求")

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                newer = self.manager.player_turn(user_text="新请求")
                self.manager.player_cancel(str(newer["session_id"]))
                self.manager.pending_lifecycle_revision_path().unlink()
                query = self.manager.player_turn(user_text="只读查询")
                self.assertEqual(query["status"], "query", query)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_publication_rechecks_registry_inside_owner_lock(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(save_path=save_path)
        original_reader = self.manager.read_canonical_pending_locked
        archived = False

        def read_after_archive(*, migrate: bool) -> tuple[str, dict[str, object] | None, bool]:
            nonlocal archived
            if not archived:
                registry = self.manager.read_registry()
                registry["saves"] = [
                    {**dict(record), "archived": True}
                    if record.get("id") == self.started["save"]["id"]
                    else record
                    for record in registry["saves"]
                ]
                self.manager.write_registry(registry)
                archived = True
            return original_reader(migrate=migrate)

        with mock.patch.object(
            self.manager,
            "read_canonical_pending_locked",
            side_effect=read_after_archive,
        ):
            result = self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": "哪一个？"},
                save_path=save_path,
                expected_publication=snapshot,
            )

        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_publication_rechecks_live_save_health(self) -> None:
        save_path = str(self.started["save"]["path"])
        snapshot = self.manager.begin_low_level_clarification_publication(save_path=save_path)
        shutil.rmtree(self.save_path)

        result = self.manager.record_low_level_clarification(
            user_text="使用那个物品",
            clarification={"question": "哪一个？"},
            save_path=save_path,
            expected_publication=snapshot,
        )

        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_clarification_publication_rejects_inflight_pending_change(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="developer",
            )
        )
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def start_turn(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("low-level pending CAS runtime gate timed out")
            return clarification_runtime().act()

        def run() -> None:
            outcome["result"] = adapter.start_turn("使用那个物品")

        with mock.patch.object(
            adapter,
            "runtime_for_save",
            return_value=SimpleNamespace(start_turn=start_turn),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                canceled = self.manager.player_cancel(str(first["session_id"]))
                self.assertTrue(canceled["ok"], canceled)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_clarification_freezes_runtime_save_and_rejects_active_switch(self) -> None:
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="developer",
            )
        )
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        runtime_saves: list[str] = []
        outcome: dict[str, dict[str, object]] = {}

        def runtime_for_save(save: str | None = None) -> SimpleNamespace:
            runtime_saves.append(str(save))

            def start_turn(*_args: object, **_kwargs: object) -> SimpleNamespace:
                runtime_started.set()
                if not release_runtime.wait(timeout=20):
                    raise TimeoutError("low-level active Save runtime gate timed out")
                return clarification_runtime().act()

            return SimpleNamespace(start_turn=start_turn)

        def run() -> None:
            outcome["result"] = adapter.start_turn("使用那个物品")

        with mock.patch.object(adapter, "runtime_for_save", side_effect=runtime_for_save):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                switched = self.manager.switch_save(str(second["save"]["id"]), refresh=False)
                self.assertTrue(switched["ok"], switched)
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(runtime_saves, [str(self.started["save"]["path"])])
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())
        self.assertEqual(self.manager.read_registry()["active_save_id"], second["save"]["id"])

    def test_low_level_publication_rejects_active_selection_aba(self) -> None:
        original_id = str(self.started["save"]["id"])
        save_path = str(self.started["save"]["path"])
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=save_path,
            require_active_save_match=True,
        )
        self.manager.switch_save(str(second["save"]["id"]), refresh=False)
        self.manager.switch_save(original_id, refresh=False)

        result = self.manager.record_low_level_clarification(
            user_text="使用那个物品",
            clarification={"question": "哪一个？"},
            save_path=save_path,
            expected_publication=snapshot,
        )

        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_publication_uses_verified_snapshot_copy(self) -> None:
        save_path = str(self.started["save"]["path"])
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        snapshot = self.manager.begin_low_level_clarification_publication(
            save_path=save_path,
            require_active_save_match=True,
        )
        self.manager.switch_save(str(second["save"]["id"]), refresh=False)

        def mutate_after_verification(*_args: object, **_kwargs: object) -> bool:
            snapshot["require_active_save_match"] = False
            return True

        with mock.patch.object(
            self.manager,
            "pending_lifecycle_revision_matches",
            side_effect=mutate_after_verification,
        ):
            result = self.manager.record_low_level_clarification(
                user_text="使用那个物品",
                clarification={"question": "哪一个？"},
                save_path=save_path,
                expected_publication=snapshot,
            )

        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertIsNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_low_level_begin_cannot_mutate_expired_pending_of_another_identity(self) -> None:
        self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:owner",
            actor_id="actor:owner",
        )
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        expired = {
            **pending,
            "created_at": "1999-12-31T23:30:00+00:00",
            "expires_at": "2000-01-01T00:00:00+00:00",
        }
        self.manager.write_pending_action(expired)
        before = self.manager.pending_action_path().read_bytes()
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="developer",
            )
        )

        result = adapter.start_turn("使用那个物品")

        self.assertFalse(result["ok"], result)
        self.assertIn("cannot verify canonical pending state", result["errors"][0])
        self.assertEqual(self.manager.pending_action_path().read_bytes(), before)
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_losing_publication_does_not_migrate_later_legacy_clarification(self) -> None:
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}

        def act(*_args: object, **_kwargs: object) -> SimpleNamespace:
            runtime_started.set()
            if not release_runtime.wait(timeout=20):
                raise TimeoutError("legacy publication CAS runtime gate timed out")
            return ready_runtime("cmd:legacy-cas").act()

        def run() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(user_text="休息到早上")

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act),
        ):
            thread = threading.Thread(target=run)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                created_at = datetime.now(timezone.utc).isoformat()
                legacy = {
                    "schema_version": "1",
                    "clarification_id": "clarification:later-legacy",
                    "save_id": self.started["save"]["id"],
                    "save_path": self.started["save"]["path"],
                    "created_at": created_at,
                    "original_user_text": "使用那个物品",
                    "clarification": {"question": "你指哪一个？"},
                    "platform": "qq",
                    "session_key_hash": hash_identity("room:later"),
                    "actor_id_hash": hash_identity("actor:later"),
                }
                self.manager.write_pending_clarification(legacy)
                before = self.manager.pending_clarification_path().read_bytes()
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        result = outcome["result"]
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertEqual(self.manager.pending_clarification_path().read_bytes(), before)
        self.assertEqual(self.manager.read_pending_clarification(), legacy)
        self.assertIsNone(self.manager.read_pending_action())

    def test_generation_conflict_recomputes_identity_before_returning_current_token(self) -> None:
        first = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:a",
            actor_id="actor:a",
        )
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}
        actual_runtime = GMRuntime.from_path(self.save_path)

        def act(user_text: str, *_args: object, **_kwargs: object) -> SimpleNamespace:
            if user_text == "A replacement":
                runtime_started.set()
                if not release_runtime.wait(timeout=20):
                    raise TimeoutError("supersede runtime gate timed out")
            return ready_runtime(f"cmd:{user_text}").act()

        def supersede() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="A replacement",
                expected_pending_id=str(first["session_id"]),
                platform="qq",
                session_key="room:a",
                actor_id="actor:a",
            )

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act, campaign=actual_runtime.campaign),
        ):
            thread = threading.Thread(target=supersede)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                canceled = self.manager.player_cancel(
                    str(first["session_id"]),
                    platform="qq",
                    session_key="room:a",
                    actor_id="actor:a",
                )
                self.assertTrue(canceled["ok"], canceled)
                other = SaveManager(self.root).player_turn(
                    user_text="B replacement",
                    platform="qq",
                    session_key="room:b",
                    actor_id="actor:b",
                )
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        self.assertIn("result", outcome)
        conflict = outcome["result"]
        self.assertEqual(conflict["status"], "pending_conflict", conflict)
        self.assertNotIn("pending_id", conflict["lifecycle"])
        self.assertEqual(self.manager.read_pending_action()["session_id"], other["session_id"])

    def test_generation_conflict_does_not_expose_same_identity_pending_from_another_save(self) -> None:
        first_save = dict(self.started["save"])
        first = self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="room:same",
            actor_id="actor:same",
        )
        runtime_started = threading.Event()
        release_runtime = threading.Event()
        outcome: dict[str, dict[str, object]] = {}
        actual_runtime = GMRuntime.from_path(self.save_path)

        def act(user_text: str, *_args: object, **_kwargs: object) -> SimpleNamespace:
            if user_text == "slow replacement":
                runtime_started.set()
                if not release_runtime.wait(timeout=20):
                    raise TimeoutError("cross-save runtime gate timed out")
            return ready_runtime(f"cmd:{user_text}").act()

        def supersede() -> None:
            outcome["result"] = SaveManager(self.root).player_turn(
                user_text="slow replacement",
                save_path=str(first_save["path"]),
                expected_pending_id=str(first["session_id"]),
                platform="qq",
                session_key="room:same",
                actor_id="actor:same",
            )

        with mock.patch(
            "rpg_engine.save_manager.GMRuntime.from_path",
            return_value=SimpleNamespace(act=act, campaign=actual_runtime.campaign),
        ):
            thread = threading.Thread(target=supersede)
            thread.start()
            self.assertTrue(runtime_started.wait(timeout=20))
            try:
                canceled = self.manager.player_cancel(
                    str(first["session_id"]),
                    save_path=str(first_save["path"]),
                    platform="qq",
                    session_key="room:same",
                    actor_id="actor:same",
                )
                self.assertTrue(canceled["ok"], canceled)
                second = self.manager.create_save(campaign="campaigns/minimal", label="Other", activate=True)
                other = self.manager.player_turn(
                    user_text="other save action",
                    save_path=str(second["save"]["path"]),
                    platform="qq",
                    session_key="room:same",
                    actor_id="actor:same",
                )
            finally:
                release_runtime.set()
            thread.join(timeout=20)

        self.assertFalse(thread.is_alive())
        conflict = outcome["result"]
        self.assertEqual(conflict["status"], "pending_conflict", conflict)
        self.assertNotIn("pending_id", conflict["lifecycle"])
        self.assertNotIn(str(other["session_id"]), json.dumps(conflict, ensure_ascii=False))

    def test_two_process_first_publications_leave_exactly_one_pending(self) -> None:
        script = """
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from rpg_engine.save_manager import SaveManager

root = Path(sys.argv[1])
identity = sys.argv[2]

def act(*_args, **_kwargs):
    (root / f\"ready.{identity}\").write_text(\"ready\", encoding=\"utf-8\")
    deadline = time.monotonic() + 20
    while not (root / \"publication.go\").exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(\"publication gate timed out\")
        time.sleep(0.01)
    return SimpleNamespace(to_dict=lambda: {
        \"ok\": True,
        \"status\": \"ready\",
        \"action\": \"rest\",
        \"ready_to_save\": True,
        \"delta_draft\": {\"command_id\": f\"cmd:process:{identity}\", \"events\": [], \"upsert_entities\": []},
        \"turn_proposal\": {\"proposal_id\": f\"proposal:process:{identity}\"},
        \"warnings\": [],
        \"errors\": [],
    })

with mock.patch(\"rpg_engine.save_manager.GMRuntime.from_path\", return_value=SimpleNamespace(act=act)):
    result = SaveManager(root).player_turn(user_text=\"休息到早上\")
(root / f\"result.{identity}.json\").write_text(json.dumps(result), encoding=\"utf-8\")
"""
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(self.root), str(index)],
                cwd=ENGINE_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for index in range(2)
        ]
        deadline = time.monotonic() + 20
        while not all((self.root / f"ready.{index}").exists() for index in range(2)):
            if time.monotonic() >= deadline:
                for process in processes:
                    process.kill()
                self.fail("subprocess publication barrier timed out")
            time.sleep(0.01)
        (self.root / "publication.go").write_text("go", encoding="utf-8")
        outputs = [process.communicate(timeout=30) for process in processes]
        for process, (_stdout, stderr) in zip(processes, outputs, strict=True):
            self.assertEqual(process.returncode, 0, stderr)
        results = [
            json.loads((self.root / f"result.{index}.json").read_text(encoding="utf-8"))
            for index in range(2)
        ]
        self.assertEqual(sum(bool(result.get("ready_to_confirm")) for result in results), 1, results)
        self.assertEqual(sum(result.get("status") == "pending_conflict" for result in results), 1, results)
        self.assertIsNotNone(self.manager.read_pending_action())
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_confirmation_history_is_bounded_and_evicts_oldest(self) -> None:
        session_ids: list[str] = []
        for _ in range(10):
            acted = self.manager.player_turn(user_text="休息到早上")
            session_ids.append(str(acted["session_id"]))
            confirmed = self.manager.player_confirm(str(acted["session_id"]))
            self.assertTrue(confirmed["ok"], confirmed)
        history = self.manager.read_confirmation_history()
        self.assertEqual(len(history), 8)
        historical_hashes = {str(item["confirmation_session_hash"]) for item in history}
        self.assertNotIn(hash_identity(session_ids[0]), historical_hashes)
        self.assertIn(hash_identity(session_ids[-2]), historical_hashes)
        with sqlite3.connect(self.save_path / "data" / "game.sqlite") as conn:
            anchors = conn.execute(
                "select key from meta where key like ? order by key",
                (f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}%",),
            ).fetchall()
        self.assertEqual(len(anchors), 9)
        self.assertNotIn(
            f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}{hash_identity(session_ids[0])}",
            {str(row[0]) for row in anchors},
        )

    def test_confirmation_history_rejects_duplicate_session_hash_on_read_and_write(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        self.manager.player_turn(user_text="休息到早上")
        history = self.manager.read_confirmation_history()
        self.assertEqual(len(history), 1)
        duplicate = [history[0], dict(history[0])]

        with self.assertRaisesRegex(SaveManagerError, "duplicate session"):
            self.manager.write_confirmation_history(duplicate)

        envelope = json.loads(self.manager.confirmation_history_path().read_text(encoding="utf-8"))
        envelope["receipts"] = duplicate
        self.manager.confirmation_history_path().write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(SaveManagerError, "duplicate session"):
            self.manager.read_confirmation_history()

    def test_confirmation_history_rejects_reordered_valid_receipts(self) -> None:
        for _ in range(4):
            acted = self.manager.player_turn(user_text="休息到早上")
            self.manager.player_confirm(str(acted["session_id"]))
        self.manager.player_turn(user_text="休息到早上")
        history = self.manager.read_confirmation_history()
        self.assertGreaterEqual(len(history), 3)

        with self.assertRaisesRegex(SaveManagerError, "order cannot be rewritten"):
            self.manager.write_confirmation_history(list(reversed(history)))

        envelope = json.loads(self.manager.confirmation_history_path().read_text(encoding="utf-8"))
        envelope["receipts"] = list(reversed(envelope["receipts"]))
        self.manager.confirmation_history_path().write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(SaveManagerError, "order integrity"):
            self.manager.read_confirmation_history()

    def test_confirmation_history_order_anchor_is_bounded_and_rejects_snapshot_rollback(self) -> None:
        snapshots: list[bytes] = []
        for _ in range(12):
            acted = self.manager.player_turn(user_text="休息到早上")
            self.manager.player_confirm(str(acted["session_id"]))
            if self.manager.confirmation_history_path().exists():
                snapshots.append(self.manager.confirmation_history_path().read_bytes())
        self.manager.player_turn(user_text="休息到早上")
        self.assertGreaterEqual(len(snapshots), 2)
        with sqlite3.connect(self.save_path / "data" / "game.sqlite") as conn:
            keys = {
                str(row[0])
                for row in conn.execute(
                    "select key from meta where key = ? or key = ? or key glob ?",
                    (
                        CONFIRMATION_HISTORY_ORDER_META_KEY,
                        CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,
                        "confirmation_replay_history_order_digest:*",
                    ),
                ).fetchall()
            }
        self.assertEqual(keys, {CONFIRMATION_HISTORY_ORDER_META_KEY})

        self.manager.confirmation_history_path().write_bytes(snapshots[0])
        with self.assertRaisesRegex(SaveManagerError, "SQLite order anchor"):
            self.manager.read_confirmation_history()

    def test_history_order_digest_and_sqlite_anchors_reject_whitespace_tamper(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        self.manager.player_turn(user_text="休息到早上")
        history_path = self.manager.confirmation_history_path()
        envelope = json.loads(history_path.read_text(encoding="utf-8"))
        order_digest = str(envelope["order_digest"])
        database_path = self.save_path / "data" / "game.sqlite"

        envelope["order_digest"] = f" {order_digest} "
        history_path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaisesRegex(SaveManagerError, "order integrity"):
            self.manager.read_confirmation_history()
        envelope["order_digest"] = order_digest
        history_path.write_text(json.dumps(envelope), encoding="utf-8")

        with sqlite3.connect(database_path) as conn:
            conn.execute(
                "update meta set value = ? where key = ?",
                (f" {order_digest} ", CONFIRMATION_HISTORY_ORDER_META_KEY),
            )
            conn.commit()
        with self.assertRaisesRegex(SaveManagerError, "SQLite order anchor"):
            self.manager.read_confirmation_history()

        with sqlite3.connect(database_path) as conn:
            conn.execute(
                "delete from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_META_KEY,),
            )
            conn.execute(
                "insert or replace into meta(key, value) values (?, ?)",
                (CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY, f" {order_digest} "),
            )
            conn.commit()
        with self.assertRaisesRegex(SaveManagerError, "SQLite order anchor"):
            self.manager.read_confirmation_history()

    def test_committed_history_read_clears_stale_prepared_order_anchor(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        self.manager.player_turn(user_text="休息到早上")
        history = self.manager.read_confirmation_history()
        self.assertEqual(len(history), 1)
        self.manager.write_confirmation_history_order_anchor(history[-1], "f" * 64)

        self.assertEqual(self.manager.read_confirmation_history(), history)
        with sqlite3.connect(self.save_path / "data" / "game.sqlite") as conn:
            prepared = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,),
            ).fetchone()
        self.assertIsNone(prepared)

    def test_committed_history_read_clears_cross_save_stale_prepared_anchor(self) -> None:
        first_save_path = self.save_path
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        awaiting = self.manager.player_turn(user_text="休息到早上")
        history = self.manager.read_confirmation_history()
        self.assertEqual(len(history), 1)
        self.manager.player_cancel(str(awaiting["session_id"]))

        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)
        second_save_path = self.root / str(second["save"]["path"])
        second_action = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(second_action["session_id"]))
        second_receipt = self.manager.read_confirmation_receipt()
        self.assertIsNotNone(second_receipt)
        assert second_receipt is not None
        self.manager.write_confirmation_history_order_anchor(second_receipt, "e" * 64)

        self.assertEqual(self.manager.read_confirmation_history(), history)
        with sqlite3.connect(second_save_path / "data" / "game.sqlite") as conn:
            prepared = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_PREPARED_META_KEY,),
            ).fetchone()
        self.assertIsNone(prepared)
        with sqlite3.connect(first_save_path / "data" / "game.sqlite") as conn:
            committed = conn.execute(
                "select value from meta where key = ?",
                (CONFIRMATION_HISTORY_ORDER_META_KEY,),
            ).fetchone()
        self.assertIsNotNone(committed)

    def test_missing_history_file_with_sqlite_order_anchor_fails_closed(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        self.manager.player_turn(user_text="休息到早上")
        self.assertEqual(len(self.manager.read_confirmation_history()), 1)
        self.manager.confirmation_history_path().unlink()

        with self.assertRaisesRegex(SaveManagerError, "history is missing"):
            self.manager.read_confirmation_history()

    def test_latest_receipt_replay_validates_missing_history_authority_first(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        second = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(second["session_id"]))
        self.assertEqual(len(self.manager.read_confirmation_history()), 1)
        self.manager.confirmation_history_path().unlink()
        receipt_before = self.manager.confirmation_receipt_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "history is missing"):
            self.manager.player_confirm(str(second["session_id"]))

        self.assertEqual(self.manager.confirmation_receipt_path().read_bytes(), receipt_before)
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_missing_history_authority_scan_does_not_create_missing_save_database(self) -> None:
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        second_save_path = self.root / str(second["save"]["path"])
        database_path = second_save_path / "data" / "game.sqlite"
        database_path.unlink()
        before = tree_digest(second_save_path)

        with self.assertRaisesRegex(SaveManagerError, "authority cannot be verified"):
            self.manager.read_confirmation_history()

        self.assertFalse(database_path.exists())
        self.assertEqual(tree_digest(second_save_path), before)

    def test_committed_history_cleanup_does_not_create_missing_save_database(self) -> None:
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        self.manager.player_turn(user_text="休息到早上")
        self.assertEqual(len(self.manager.read_confirmation_history()), 1)
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=False)
        second_save_path = self.root / str(second["save"]["path"])
        database_path = second_save_path / "data" / "game.sqlite"
        database_path.unlink()
        before = tree_digest(second_save_path)

        with self.assertRaisesRegex(SaveManagerError, "anchors cannot be cleaned safely"):
            self.manager.read_confirmation_history()

        self.assertFalse(database_path.exists())
        self.assertEqual(tree_digest(second_save_path), before)

    def test_pending_recovery_probe_does_not_create_missing_save_database(self) -> None:
        self.manager.player_turn(user_text="休息到早上")
        pending = self.manager.read_pending_action()
        self.assertIsNotNone(pending)
        assert pending is not None
        self.manager.write_pending_action(
            {
                **pending,
                "created_at": "1999-12-31T23:30:00+00:00",
                "expires_at": "2000-01-01T00:00:00+00:00",
            }
        )
        database_path = self.save_path / "data" / "game.sqlite"
        database_path.unlink()
        before = tree_digest(self.save_path)

        inspected = self.manager.inspect_pending()

        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["status"], "invalid_state")
        self.assertFalse(database_path.exists())
        self.assertEqual(tree_digest(self.save_path), before)

    def test_pending_publication_failure_restores_history_order_sqlite_evidence(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(acted["session_id"]))
        before = gameplay_snapshot(self.save_path)

        with mock.patch.object(self.manager, "write_pending_action", side_effect=OSError("publish failed")):
            with self.assertRaisesRegex(OSError, "publish failed"):
                self.manager.player_turn(user_text="休息到早上")

        self.assertEqual(gameplay_snapshot(self.save_path), before)
        self.assertFalse(self.manager.confirmation_history_path().exists())

    def test_forged_latest_receipt_cannot_be_archived_before_new_pending(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(acted["session_id"]))
        receipt = self.manager.read_confirmation_receipt()
        self.assertIsNotNone(receipt)
        assert receipt is not None
        forged = {**receipt, "turn_id": "turn:forged"}
        forged["receipt_digest"] = stable_payload_digest(
            {key: value for key, value in forged.items() if key != "receipt_digest"}
        )
        self.manager.write_confirmation_receipt(forged)
        receipt_before = self.manager.confirmation_receipt_path().read_bytes()
        facts_before = gameplay_snapshot(self.save_path)

        with self.assertRaisesRegex(SaveManagerError, "authoritative turn evidence|SQLite receipt anchor"):
            self.manager.player_turn(user_text="休息到早上")

        self.assertEqual(self.manager.confirmation_receipt_path().read_bytes(), receipt_before)
        self.assertFalse(self.manager.pending_action_path().exists())
        self.assertEqual(gameplay_snapshot(self.save_path), facts_before)

    def test_history_anchor_eviction_retries_after_abrupt_termination(self) -> None:
        session_ids: list[str] = []
        for _ in range(9):
            acted = self.manager.player_turn(user_text="休息到早上")
            session_ids.append(str(acted["session_id"]))
            self.manager.player_confirm(str(acted["session_id"]))
        history_before = self.manager.read_confirmation_history()
        self.assertEqual(len(history_before), 8)
        oldest_hash = str(history_before[0]["confirmation_session_hash"])

        with mock.patch.object(
            self.manager,
            "delete_confirmation_receipt_anchor",
            side_effect=SystemExit("simulated abrupt termination"),
        ):
            with self.assertRaisesRegex(SystemExit, "abrupt termination"):
                self.manager.player_turn(user_text="休息到早上")

        retry = SaveManager(self.root).player_turn(user_text="休息到早上")

        self.assertTrue(retry["ready_to_confirm"], retry)
        history_after = self.manager.read_confirmation_history()
        self.assertEqual(len(history_after), 8)
        self.assertNotIn(oldest_hash, {str(item["confirmation_session_hash"]) for item in history_after})
        with sqlite3.connect(self.save_path / "data" / "game.sqlite") as conn:
            anchors = {
                str(row[0])
                for row in conn.execute(
                    "select key from meta where key like ?",
                    (f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}%",),
                ).fetchall()
            }
        self.assertNotIn(f"{CONFIRMATION_RECEIPT_HISTORY_META_PREFIX}{oldest_hash}", anchors)
        self.assertEqual(len(anchors), 8)

    def test_missing_evicted_receipt_save_does_not_block_healthy_pending_publication(self) -> None:
        first_save_path = self.save_path
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)
        second_path = self.root / str(second["save"]["path"])
        second_before = gameplay_snapshot(second_path)
        for _ in range(8):
            acted = self.manager.player_turn(user_text="休息到早上")
            self.manager.player_confirm(str(acted["session_id"]))
        self.assertEqual(len(self.manager.read_confirmation_history()), 8)
        shutil.rmtree(first_save_path)

        next_turn = self.manager.player_turn(user_text="休息到早上")

        self.assertTrue(next_turn["ready_to_confirm"], next_turn)
        self.assertEqual(len(self.manager.read_confirmation_history()), 8)
        second_after = gameplay_snapshot(second_path)
        self.assertEqual(
            len(second_after["rows"]["turns"]),
            len(second_before["rows"]["turns"]) + 8,
        )

    def test_cross_save_eviction_removes_generic_and_historical_replay_authority(self) -> None:
        first_save = dict(self.started["save"])
        first = self.manager.player_turn(user_text="休息到早上")
        self.manager.player_confirm(str(first["session_id"]))
        first_receipt = self.manager.read_confirmation_receipt()
        assert first_receipt is not None
        self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)
        for _ in range(9):
            acted = self.manager.player_turn(user_text="休息到早上")
            self.manager.player_confirm(str(acted["session_id"]))
        self.assertEqual(len(self.manager.read_confirmation_history()), 8)

        self.manager.write_confirmation_receipt(first_receipt)
        with self.assertRaisesRegex(SaveManagerError, "SQLite receipt anchor"):
            self.manager.player_confirm(
                str(first["session_id"]),
                save_path=str(first_save["path"]),
            )

    def test_cancel_requires_current_or_explicit_exact_save_and_has_stable_conflict_status(self) -> None:
        first_save = dict(self.started["save"])
        acted = self.manager.player_turn(user_text="休息到早上")
        wrong_token = self.manager.player_cancel("player_action:wrong")
        self.assertEqual(wrong_token["status"], "conflict", wrong_token)
        second = self.manager.create_save(campaign="campaigns/minimal", label="Second", activate=True)

        cross_save = self.manager.player_cancel(str(acted["session_id"]))
        self.assertEqual(cross_save["status"], "conflict", cross_save)
        self.assertIsNotNone(self.manager.read_pending_action())
        explicit = self.manager.player_cancel(
            str(acted["session_id"]),
            save_path=str(first_save["path"]),
        )
        self.assertTrue(explicit["ok"], explicit)
        self.assertNotEqual(second["save"]["id"], first_save["id"])

    def test_cross_identity_inspect_returns_only_redacted_lifecycle(self) -> None:
        self.manager.player_turn(
            user_text="休息到早上",
            platform="qq",
            session_key="private-room",
            actor_id="private-owner",
        )

        inspected = self.manager.inspect_pending(
            platform="qq",
            session_key="private-room",
            actor_id="other-actor",
        )

        self.assertFalse(inspected["ok"], inspected)
        self.assertEqual(inspected["lifecycle"], {"state": "conflict", "kind": "action"})

    def test_low_level_mcp_conflict_does_not_return_unpersisted_clarification(self) -> None:
        acted = self.manager.player_turn(user_text="休息到早上")
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                default_save=str(self.started["save"]["path"]),
                mcp_profile="developer",
            )
        )
        runtime = SimpleNamespace(start_turn=lambda *_args, **_kwargs: clarification_runtime().act())
        with mock.patch.object(adapter, "runtime_for_save", return_value=runtime):
            result = adapter.start_turn("使用那个物品")

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status"], "pending_conflict", result)
        self.assertNotIn("clarification", result)
        self.assertEqual(self.manager.read_pending_action()["session_id"], acted["session_id"])
        self.assertIsNone(self.manager.read_pending_clarification())

    def test_mcp_player_cancel_forwards_exact_identity_to_owner(self) -> None:
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="player",
            )
        )
        acted = adapter.player_turn(
            "休息到早上",
            platform="qq",
            session_key="room:cancel",
            actor_id="actor:cancel",
        )
        conflict = adapter.player_cancel(
            "player_action:wrong",
            platform="qq",
            session_key="room:cancel",
            actor_id="actor:cancel",
        )
        self.assertEqual(conflict["status"], "conflict", conflict)
        canceled = adapter.player_cancel(
            str(acted["session_id"]),
            platform="qq",
            session_key="room:cancel",
            actor_id="actor:cancel",
        )
        self.assertTrue(canceled["ok"], canceled)
        self.assert_lifecycle(canceled, state="canceled", kind="action")
        self.assertIsNone(self.manager.read_pending_action())

    def test_mcp_confirm_and_cancel_without_explicit_save_use_active_registry_save(self) -> None:
        adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=False,
                mcp_profile="player",
            )
        )
        first = adapter.player_turn("休息到早上")
        canceled = adapter.player_cancel(str(first["session_id"]))
        second = adapter.player_turn("休息到早上")
        confirmed = adapter.player_confirm(str(second["session_id"]))

        self.assertTrue(canceled["ok"], canceled)
        self.assertEqual(canceled["status"], "canceled")
        self.assertTrue(confirmed["ok"], confirmed)
        self.assertEqual(confirmed["write_status"], "committed")

    def test_gm_view_low_level_clarification_is_not_persisted_to_player_lifecycle(self) -> None:
        hidden = "HIDDEN_GM_ONLY_DRAGON_NAME"
        gm_adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                default_save=str(self.started["save"]["path"]),
                mcp_profile="trusted_gm",
            )
        )
        hidden_runtime = SimpleNamespace(
            start_turn=lambda *_args, **_kwargs: clarification_runtime(hidden).act()
        )
        with mock.patch.object(gm_adapter, "runtime_for_save", return_value=hidden_runtime):
            result = gm_adapter.start_turn("检查隐藏目标", view="gm")

        self.assertIn(hidden, json.dumps(result, ensure_ascii=False))
        self.assertIsNone(self.manager.read_pending_clarification())
        player_adapter = AIGMMCPAdapter(
            MCPAdapterConfig.from_values(
                self.root,
                default_campaign="campaigns/minimal",
                registry_active=True,
                mcp_profile="player",
            )
        )
        player_result = player_adapter.player_turn("查看周围")
        self.assertNotIn(hidden, json.dumps(player_result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
