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
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest import mock

from rpg_engine.backup import list_backups
from rpg_engine.commit_service import commit_turn_delta
from rpg_engine.db import connect
from rpg_engine.proposal import turn_proposal_from_dict
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import (
    SaveManager,
    SaveManagerError,
    confirmation_claim_lock,
    hash_identity,
    stable_payload_digest,
)
from rpg_engine.save_service import inspect_v1_save
from rpg_engine.validation_pipeline import run_validation_pipeline
from tests.helpers import tree_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_EXAMPLE = ENGINE_ROOT / "rpg_engine" / "resources" / "examples" / "v1_minimal_adventure"


def authoritative_counts(save_path: Path) -> tuple[int, int, str]:
    conn = sqlite3.connect(save_path / "data" / "game.sqlite")
    try:
        turns = int(conn.execute("select count(*) from turns").fetchone()[0])
        events = int(conn.execute("select count(*) from events").fetchone()[0])
        current = str(conn.execute("select value from meta where key='current_turn_id'").fetchone()[0])
    finally:
        conn.close()
    return turns, events, current


class PendingConfirmationReplayTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> tuple[SaveManager, Path]:
        campaign_dir = root / "campaigns" / "official"
        shutil.copytree(OFFICIAL_EXAMPLE, campaign_dir)
        manager = SaveManager(root, default_campaign="campaigns/official")
        started = manager.start_or_continue(campaign="campaigns/official")
        return manager, root / str(started["save"]["path"])

    def test_two_thread_confirm_has_one_fresh_commit_and_one_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before_turns, before_events, _ = authoritative_counts(save_path)
            barrier = threading.Barrier(2)

            def confirm() -> dict[str, object]:
                barrier.wait(timeout=10)
                return SaveManager(root).player_confirm(str(acted["session_id"]))

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: confirm(), range(2)))

            by_status = {str(result["write_status"]): result for result in results}
            self.assertEqual(set(by_status), {"committed", "already_confirmed"}, results)
            self.assertFalse(bool(by_status["committed"]["idempotent_replay"]))
            self.assertTrue(bool(by_status["committed"]["saved"]))
            self.assertTrue(bool(by_status["already_confirmed"]["idempotent_replay"]))
            self.assertFalse(bool(by_status["already_confirmed"]["saved"]))
            after_turns, after_events, _ = authoritative_counts(save_path)
            self.assertEqual(after_turns, before_turns + 1)
            self.assertGreater(after_events, before_events)
            self.assertIsNone(manager.read_pending_action())

    def test_normal_clear_retry_returns_stable_bounded_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(
                user_text="休息到早上",
                platform="qq",
                session_key="room:private-session",
                actor_id="actor:private-id",
            )
            pending_text = manager.pending_action_path().read_text(encoding="utf-8")

            fresh = manager.player_confirm(
                str(acted["session_id"]),
                platform="qq",
                session_key="room:private-session",
                actor_id="actor:private-id",
            )
            before_replay = authoritative_counts(save_path)
            registry_before_replay = manager.registry_path.read_bytes()
            replay = manager.player_confirm(
                str(acted["session_id"]),
                platform="qq",
                session_key="room:private-session",
                actor_id="actor:private-id",
            )

            self.assertEqual(fresh["write_status"], "committed")
            self.assertFalse(fresh["idempotent_replay"])
            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertTrue(replay["idempotent_replay"])
            self.assertTrue(replay["ok"])
            self.assertFalse(replay["saved"])
            self.assertEqual(authoritative_counts(save_path), before_replay)
            self.assertEqual(manager.registry_path.read_bytes(), registry_before_replay)
            receipt_path = manager.confirmation_receipt_path()
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertLess(receipt_path.stat().st_size, 4096)
            self.assertEqual(receipt["schema_version"], "1")
            receipt_text = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
            for forbidden in (
                "休息到早上",
                "room:private-session",
                "actor:private-id",
                str(acted["session_id"]),
                pending_text,
            ):
                self.assertNotIn(forbidden, receipt_text)

    def test_two_subprocess_confirm_serializes_on_owner_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            gate = root / "start.gate"
            script = """
import json
import sys
import time
from pathlib import Path
from rpg_engine.save_manager import SaveManager

root, session_id, gate, ready, output = map(Path, sys.argv[1:])
ready.write_text("ready", encoding="utf-8")
while not gate.exists():
    time.sleep(0.01)
result = SaveManager(root).player_confirm(str(session_id))
output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
"""
            children: list[subprocess.Popen[str]] = []
            outputs: list[Path] = []
            ready_paths: list[Path] = []
            for index in range(2):
                output = root / f"result-{index}.json"
                ready = root / f"ready-{index}"
                outputs.append(output)
                ready_paths.append(ready)
                children.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-c",
                            script,
                            str(root),
                            str(acted["session_id"]),
                            str(gate),
                            str(ready),
                            str(output),
                        ],
                        cwd=ENGINE_ROOT,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                )
            deadline = time.monotonic() + 10
            while not all(path.exists() for path in ready_paths):
                self.assertLess(time.monotonic(), deadline, "subprocess confirmation barrier timed out")
                time.sleep(0.01)
            gate.write_text("go", encoding="utf-8")
            failures: list[str] = []
            for child in children:
                stdout, stderr = child.communicate(timeout=30)
                if child.returncode != 0:
                    failures.append(f"returncode={child.returncode} stdout={stdout!r} stderr={stderr!r}")
            self.assertFalse(failures, failures)
            results = [json.loads(path.read_text(encoding="utf-8")) for path in outputs]
            self.assertEqual({result["write_status"] for result in results}, {"committed", "already_confirmed"})
            self.assertEqual(sum(bool(result["saved"]) for result in results), 1)
            after = authoritative_counts(save_path)
            self.assertEqual(after[0], before[0] + 1)
            self.assertGreater(after[1], before[1])

    def test_process_crash_after_sqlite_commit_recovers_as_replay_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            source_path = root / "campaigns" / "official"
            source_before = tree_digest(source_path)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            script = """
import os
import sys
from pathlib import Path
from rpg_engine.save_manager import SaveManager

manager = SaveManager(Path(sys.argv[1]))
manager.write_confirmation_receipt = lambda receipt: os._exit(91)
manager.player_confirm(sys.argv[2])
"""
            crashed = subprocess.run(
                [sys.executable, "-c", script, str(root), str(acted["session_id"])],
                cwd=ENGINE_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(crashed.returncode, 91, crashed.stderr)
            after_crash = authoritative_counts(save_path)
            self.assertEqual(after_crash[0], before[0] + 1)
            self.assertGreater(after_crash[1], before[1])
            self.assertIsNotNone(manager.read_pending_action())
            self.assertFalse(manager.confirmation_receipt_path().exists())
            backups_after_crash = list_backups(GMRuntime.from_path(save_path).campaign)

            replay = manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertTrue(replay["idempotent_replay"])
            self.assertFalse(replay["saved"])
            self.assertEqual(authoritative_counts(save_path), after_crash)
            self.assertEqual(list_backups(GMRuntime.from_path(save_path).campaign), backups_after_crash)
            self.assertIsNone(manager.read_pending_action())
            self.assertTrue(manager.confirmation_receipt_path().exists())
            self.assertEqual(tree_digest(source_path), source_before)

    def test_receipt_and_pending_reconcile_fail_closed_on_payload_or_evidence_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            with mock.patch.object(manager, "clear_pending_action", side_effect=OSError("clear failed")):
                with self.assertRaisesRegex(OSError, "clear failed"):
                    manager.player_confirm(str(acted["session_id"]))
            committed = authoritative_counts(save_path)
            self.assertEqual(committed[0], before[0] + 1)
            pending = manager.read_pending_action()
            self.assertIsNotNone(pending)
            self.assertTrue(manager.confirmation_receipt_path().exists())

            tampered = dict(pending or {})
            tampered_proposal = dict(tampered["turn_proposal"])
            tampered_proposal["response_text"] = "tampered replay proposal"
            tampered["turn_proposal"] = tampered_proposal
            manager.write_pending_action(tampered)
            with self.assertRaisesRegex(SaveManagerError, "claim conflicts|proposal digest"):
                manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(authoritative_counts(save_path), committed)

            manager.write_pending_action(dict(pending or {}))
            replay = manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(replay["write_status"], "already_confirmed")
            receipt = manager.read_confirmation_receipt()
            self.assertIsNotNone(receipt)
            forged = dict(receipt or {})
            forged["turn_id"] = "turn:forged"
            body = {key: value for key, value in forged.items() if key != "receipt_digest"}
            forged["receipt_digest"] = stable_payload_digest(body)
            manager.write_confirmation_receipt(forged)
            with self.assertRaisesRegex(SaveManagerError, "authoritative turn evidence"):
                manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(authoritative_counts(save_path), committed)

            rebound = dict(receipt or {})
            rebound_session_id = "player_action:receipt-rebound"
            rebound["confirmation_session_hash"] = hash_identity(rebound_session_id)
            body = {key: value for key, value in rebound.items() if key != "receipt_digest"}
            rebound["receipt_digest"] = stable_payload_digest(body)
            manager.write_confirmation_receipt(rebound)
            with self.assertRaisesRegex(SaveManagerError, "SQLite receipt anchor"):
                manager.player_confirm(rebound_session_id)

            for malformed_count in (float(receipt["event_count"]), str(receipt["event_count"])):
                malformed = {**dict(receipt or {}), "event_count": malformed_count}
                body = {key: value for key, value in malformed.items() if key != "receipt_digest"}
                malformed["receipt_digest"] = stable_payload_digest(body)
                manager.write_confirmation_receipt(malformed)
                with self.subTest(event_count=malformed_count), self.assertRaisesRegex(
                    SaveManagerError,
                    "invalid event count",
                ):
                    manager.player_confirm(str(acted["session_id"]))

            duplicate_key_text = json.dumps(receipt, ensure_ascii=False, sort_keys=True).replace(
                '"schema_version": "1"',
                '"schema_version": "1", "schema_version": "1"',
                1,
            )
            manager.confirmation_receipt_path().write_text(duplicate_key_text, encoding="utf-8")
            with self.assertRaisesRegex(SaveManagerError, "duplicate JSON key"):
                manager.player_confirm(str(acted["session_id"]))

    def test_receipt_write_failure_preserves_claim_and_different_payload_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            with mock.patch.object(manager, "write_confirmation_receipt", side_effect=OSError("receipt failed")):
                with self.assertRaisesRegex(OSError, "receipt failed"):
                    manager.player_confirm(str(acted["session_id"]))
            committed = authoritative_counts(save_path)
            self.assertEqual(committed[0], before[0] + 1)
            pending = manager.read_pending_action()
            self.assertIsNotNone(pending)

            tampered = dict(pending or {})
            tampered_delta = {**tampered["delta"], "summary": "different durable payload"}
            tampered["delta"] = tampered_delta
            tampered["turn_proposal"] = {**tampered["turn_proposal"], "delta": tampered_delta}
            manager.write_pending_action(tampered)
            with self.assertRaisesRegex(SaveManagerError, "claim conflicts"):
                manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(authoritative_counts(save_path), committed)

            manager.write_pending_action(dict(pending or {}))
            replay = manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertEqual(authoritative_counts(save_path), committed)

    def test_durable_claim_rejects_save_rebinding_when_receipt_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, first_path = self.make_workspace(root)
            second = manager.create_save(campaign="campaigns/official", label="Second", activate=False)
            second_path = root / str(second["save"]["path"])
            acted = manager.player_turn(user_text="休息到早上")
            first_before = authoritative_counts(first_path)
            second_before = authoritative_counts(second_path)
            with mock.patch.object(manager, "write_confirmation_receipt", side_effect=OSError("receipt failed")):
                with self.assertRaisesRegex(OSError, "receipt failed"):
                    manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(authoritative_counts(first_path)[0], first_before[0] + 1)

            pending = dict(manager.read_pending_action() or {})
            rebound = {
                **pending,
                "save_id": second["save"]["id"],
                "save_path": second["save"]["path"],
            }
            claim = dict(rebound["confirmation_claim"])
            claim["save_id"] = str(second["save"]["id"])
            claim["save_path"] = str(second["save"]["path"])
            claim_body = {key: value for key, value in claim.items() if key != "claim_digest"}
            claim["claim_digest"] = stable_payload_digest(claim_body)
            rebound["confirmation_claim"] = claim
            manager.write_pending_action(rebound)
            manager.switch_save(str(second["save"]["id"]), refresh=False)

            with self.assertRaisesRegex(SaveManagerError, "SQLite claim anchor"):
                manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(authoritative_counts(second_path), second_before)

    def test_replay_identity_mismatch_and_lock_timeout_fail_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            first_save = dict(manager.current_save(refresh=False)["save"])
            acted = manager.player_turn(
                user_text="休息到早上",
                platform="qq",
                session_key="room:identity",
                actor_id="actor:one",
            )
            manager.player_confirm(
                str(acted["session_id"]),
                platform="qq",
                session_key="room:identity",
                actor_id="actor:one",
            )
            committed = authoritative_counts(save_path)
            cases = [
                ({"session_id": "player_action:wrong", "platform": "qq", "session_key": "room:identity", "actor_id": "actor:one"}, "confirmation_session_hash"),
                ({"session_id": acted["session_id"], "platform": "discord", "session_key": "room:identity", "actor_id": "actor:one"}, "platform_hash"),
                ({"session_id": acted["session_id"], "platform": "qq", "session_key": "room:wrong", "actor_id": "actor:one"}, "session_key_hash"),
                ({"session_id": acted["session_id"], "platform": "qq", "session_key": "room:identity", "actor_id": "actor:two"}, "actor_id_hash"),
            ]
            for kwargs, expected in cases:
                with self.subTest(expected=expected), self.assertRaisesRegex(SaveManagerError, expected):
                    manager.player_confirm(**kwargs)
                self.assertEqual(authoritative_counts(save_path), committed)

            second = manager.create_save(campaign="campaigns/official", label="Second", activate=True)
            second_path = root / str(second["save"]["path"])
            second_before = authoritative_counts(second_path)
            with self.assertRaisesRegex(SaveManagerError, "save_id"):
                manager.player_confirm(
                    str(acted["session_id"]),
                    platform="qq",
                    session_key="room:identity",
                    actor_id="actor:one",
                )
            bound_replay = manager.player_confirm(
                str(acted["session_id"]),
                save_path=str(first_save["path"]),
                platform="qq",
                session_key="room:identity",
                actor_id="actor:one",
            )
            self.assertEqual(bound_replay["write_status"], "already_confirmed")
            self.assertEqual(authoritative_counts(second_path), second_before)

            manager.clear_confirmation_receipt()
            acted_again = manager.player_turn(user_text="休息到早上")
            with confirmation_claim_lock(manager.confirmation_lock_path()):
                with self.assertRaisesRegex(SaveManagerError, "timed out"):
                    with confirmation_claim_lock(manager.confirmation_lock_path(), timeout=0.05):
                        pass
            self.assertIsNotNone(manager.read_pending_action())
            self.assertEqual(manager.read_pending_action()["session_id"], acted_again["session_id"])

    def test_unconfirmed_low_level_replay_and_malformed_receipt_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            pending = manager.read_pending_action()
            self.assertIsNotNone(pending)
            delta = dict(pending["delta"])
            unconfirmed_proposal = dict(pending["turn_proposal"])
            manager.player_confirm(str(acted["session_id"]))
            committed = authoritative_counts(save_path)

            runtime = GMRuntime.from_path(save_path)
            with self.assertRaises(ValueError):
                runtime.commit_turn(delta, turn_proposal=unconfirmed_proposal)
            self.assertEqual(authoritative_counts(save_path), committed)

            manager.confirmation_receipt_path().write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(SaveManagerError, "receipt is invalid"):
                manager.player_confirm(str(acted["session_id"]))
            self.assertEqual(authoritative_counts(save_path), committed)

    def test_player_turn_publication_cannot_be_deleted_by_inflight_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, _ = self.make_workspace(root)
            first = manager.player_turn(user_text="休息到早上")
            receipt_started = threading.Event()
            release_receipt = threading.Event()
            pending_published = threading.Event()
            release_pending = threading.Event()
            original_write_receipt = manager.write_confirmation_receipt
            next_manager = SaveManager(root)
            original_write_pending = next_manager.write_pending_action

            def pause_receipt(receipt: dict[str, object]) -> None:
                receipt_started.set()
                self.assertTrue(release_receipt.wait(timeout=20))
                original_write_receipt(receipt)

            def pause_pending(session: dict[str, object]) -> None:
                original_write_pending(session)
                pending_published.set()
                self.assertTrue(release_pending.wait(timeout=20))

            with (
                mock.patch.object(manager, "write_confirmation_receipt", side_effect=pause_receipt),
                mock.patch.object(next_manager, "write_pending_action", side_effect=pause_pending),
            ):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    confirming = executor.submit(manager.player_confirm, str(first["session_id"]))
                    self.assertTrue(receipt_started.wait(timeout=20))
                    next_turn = executor.submit(next_manager.player_turn, user_text="休息到早上")
                    published_before_release = pending_published.wait(timeout=0.5)
                    release_receipt.set()
                    if not published_before_release:
                        self.assertTrue(pending_published.wait(timeout=20))
                    release_pending.set()
                    confirmed = confirming.result(timeout=30)
                    second = next_turn.result(timeout=30)

            pending = manager.read_pending_action()
            self.assertEqual(confirmed["write_status"], "committed")
            self.assertTrue(second["ready_to_confirm"], second)
            self.assertIsNotNone(pending)
            self.assertEqual(pending["session_id"], second["session_id"])

    def test_supersede_loses_cleanly_to_inflight_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            turns_before = authoritative_counts(save_path)[0]
            first = manager.player_turn(user_text="休息到早上")
            receipt_started = threading.Event()
            release_receipt = threading.Event()
            original_write_receipt = manager.write_confirmation_receipt
            next_manager = SaveManager(root)

            def pause_receipt(receipt: dict[str, object]) -> None:
                receipt_started.set()
                self.assertTrue(release_receipt.wait(timeout=20))
                original_write_receipt(receipt)

            with mock.patch.object(manager, "write_confirmation_receipt", side_effect=pause_receipt):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    confirming = executor.submit(manager.player_confirm, str(first["session_id"]))
                    self.assertTrue(receipt_started.wait(timeout=20))
                    superseding = executor.submit(
                        next_manager.player_turn,
                        user_text="休息到早上",
                        expected_pending_id=str(first["session_id"]),
                    )
                    self.assertFalse(superseding.done())
                    release_receipt.set()
                    confirmed = confirming.result(timeout=30)
                    supersede = superseding.result(timeout=30)

            self.assertEqual(confirmed["write_status"], "committed")
            self.assertEqual(supersede["status"], "not_found", supersede)
            self.assertEqual(supersede["lifecycle"]["state"], "not_found")
            self.assertIsNone(manager.read_pending_action())
            self.assertEqual(authoritative_counts(save_path)[0], turns_before + 1)

    def test_expired_pending_with_durable_turn_recovers_instead_of_deleting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            with mock.patch.object(manager, "write_confirmation_receipt", side_effect=OSError("receipt failed")):
                with self.assertRaisesRegex(OSError, "receipt failed"):
                    manager.player_confirm(str(acted["session_id"]))
            committed = authoritative_counts(save_path)
            pending = manager.read_pending_action()
            self.assertIsNotNone(pending)
            manager.write_pending_action(
                {
                    **dict(pending or {}),
                    "created_at": "1999-12-31T23:30:00+00:00",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                }
            )

            replay = manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertEqual(authoritative_counts(save_path), committed)
            self.assertIsNone(manager.read_pending_action())

    def test_post_commit_exception_preserves_claim_for_expired_replay_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            original_commit = GMRuntime.commit_turn

            def commit_then_raise(runtime: GMRuntime, *args: object, **kwargs: object) -> object:
                original_commit(runtime, *args, **kwargs)
                raise RuntimeError("failure after durable commit")

            with mock.patch.object(GMRuntime, "commit_turn", new=commit_then_raise):
                with self.assertRaisesRegex(RuntimeError, "failure after durable commit"):
                    manager.player_confirm(str(acted["session_id"]))

            committed = authoritative_counts(save_path)
            self.assertEqual(committed[0], before[0] + 1)
            pending = manager.read_pending_action()
            self.assertIsNotNone(pending)
            self.assertIn("confirmation_claim", pending or {})
            manager.write_pending_action(
                {
                    **dict(pending or {}),
                    "created_at": "1999-12-31T23:30:00+00:00",
                    "expires_at": "2000-01-01T00:00:00+00:00",
                }
            )

            replay = manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertTrue(replay["idempotent_replay"])
            self.assertFalse(replay["saved"])
            self.assertEqual(authoritative_counts(save_path), committed)
            self.assertIsNone(manager.read_pending_action())

    def test_crash_after_sqlite_commit_before_projection_finalize_repairs_dirty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            script = """
import os
import sys
from pathlib import Path
from rpg_engine.save_manager import SaveManager
from rpg_engine.unit_of_work import UnitOfWork

UnitOfWork.finalize_artifacts = lambda self: os._exit(92)
SaveManager(Path(sys.argv[1])).player_confirm(sys.argv[2])
"""
            crashed = subprocess.run(
                [sys.executable, "-c", script, str(root), str(acted["session_id"])],
                cwd=ENGINE_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(crashed.returncode, 92, crashed.stderr)
            committed = authoritative_counts(save_path)
            self.assertEqual(committed[0], before[0] + 1)
            self.assertIsNotNone(manager.read_pending_action())

            replay = manager.player_confirm(str(acted["session_id"]))
            inspected = inspect_v1_save(save_path)

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertTrue(inspected["ok"], inspected)
            self.assertEqual(inspected["projection_health"]["status"], "clean")
            self.assertEqual(authoritative_counts(save_path), committed)

    def test_crash_after_pending_clear_repairs_stale_registry_on_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            registry_turn_before = manager.current_save(refresh=False)["save"]["current_turn_id"]
            script = """
import os
import sys
from pathlib import Path
from rpg_engine.save_manager import SaveManager

manager = SaveManager(Path(sys.argv[1]))
manager.player_confirm_result = lambda **kwargs: os._exit(93)
manager.player_confirm(sys.argv[2])
"""
            crashed = subprocess.run(
                [sys.executable, "-c", script, str(root), str(acted["session_id"])],
                cwd=ENGINE_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(crashed.returncode, 93, crashed.stderr)
            self.assertIsNone(manager.read_pending_action())
            self.assertTrue(manager.confirmation_receipt_path().exists())
            durable_turn = authoritative_counts(save_path)[2]
            self.assertEqual(manager.current_save(refresh=False)["save"]["current_turn_id"], registry_turn_before)

            replay = manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertEqual(manager.current_save(refresh=False)["save"]["current_turn_id"], durable_turn)

    def test_registry_lock_crash_releases_owner_for_durable_replay_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            script = """
import os
import sys
from pathlib import Path
from rpg_engine.save_manager import SaveManager, registry_lock

def crash_result_while_registry_locked(self, **kwargs):
    lock_path = self.registry_path.with_suffix(self.registry_path.suffix + ".lock")
    with registry_lock(lock_path, root=self.root):
        os._exit(94)

SaveManager.player_confirm_result = crash_result_while_registry_locked
SaveManager(Path(sys.argv[1])).player_confirm(sys.argv[2])
"""
            crashed = subprocess.run(
                [sys.executable, "-c", script, str(root), str(acted["session_id"])],
                cwd=ENGINE_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(crashed.returncode, 94, crashed.stderr)
            committed = authoritative_counts(save_path)
            self.assertEqual(committed[0], before[0] + 1)
            self.assertIsNone(manager.read_pending_action())
            registry_lock_path = manager.registry_path.with_suffix(manager.registry_path.suffix + ".lock")
            self.assertTrue(registry_lock_path.exists())

            replay = manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(replay["write_status"], "already_confirmed")
            self.assertTrue(replay["idempotent_replay"])
            self.assertFalse(replay["saved"])
            self.assertEqual(authoritative_counts(save_path), committed)
            self.assertEqual(manager.current_save(refresh=False)["save"]["current_turn_id"], committed[2])

    def test_current_save_refresh_cannot_overwrite_concurrent_confirmation_registry_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            cached_turn_id = str(manager.current_save(refresh=False)["save"]["current_turn_id"])
            before = authoritative_counts(save_path)
            confirm_manager = SaveManager(root)
            refresh_manager = SaveManager(root)
            commit_waiting = threading.Event()
            allow_commit = threading.Event()
            refresh_captured = threading.Event()
            allow_refresh = threading.Event()
            final_merge_started = threading.Event()
            final_merge_finished = threading.Event()
            original_commit = GMRuntime.commit_turn
            original_refresh = refresh_manager.refresh_save_record
            original_merge = confirm_manager.merge_registry_save_record

            def paused_commit(runtime: GMRuntime, *args: object, **kwargs: object) -> object:
                commit_waiting.set()
                self.assertTrue(allow_commit.wait(timeout=20))
                return original_commit(runtime, *args, **kwargs)

            def paused_stale_refresh(record: dict[str, object]) -> dict[str, object]:
                refreshed = original_refresh(record)
                self.assertEqual(str(refreshed["current_turn_id"]), cached_turn_id)
                refresh_captured.set()
                self.assertTrue(allow_refresh.wait(timeout=20))
                return refreshed

            def observed_merge(record: dict[str, object]) -> dict[str, object]:
                final_merge_started.set()
                merged = original_merge(record)
                final_merge_finished.set()
                return merged

            with (
                mock.patch.object(GMRuntime, "commit_turn", new=paused_commit),
                mock.patch.object(refresh_manager, "refresh_save_record", new=paused_stale_refresh),
                mock.patch.object(confirm_manager, "merge_registry_save_record", new=observed_merge),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                confirming = executor.submit(confirm_manager.player_confirm, str(acted["session_id"]))
                self.assertTrue(commit_waiting.wait(timeout=20))
                refreshing = executor.submit(refresh_manager.current_save, refresh=True)
                self.assertTrue(refresh_captured.wait(timeout=20))
                allow_commit.set()
                self.assertTrue(final_merge_started.wait(timeout=20))
                final_merge_finished.wait(timeout=0.5)
                allow_refresh.set()
                refreshed = refreshing.result(timeout=30)
                confirmed = confirming.result(timeout=30)

            self.assertTrue(refreshed["ok"], refreshed)
            self.assertEqual(confirmed["write_status"], "committed")
            committed = authoritative_counts(save_path)
            self.assertEqual(committed[0], before[0] + 1)
            self.assertEqual(
                manager.current_save(refresh=False)["save"]["current_turn_id"],
                committed[2],
            )

    def test_replay_requires_trusted_confirmation_provenance_and_direct_delta_default_denies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            pending = manager.read_pending_action()
            self.assertIsNotNone(pending)
            delta = deepcopy(pending["delta"])
            proposal_data = deepcopy(pending["turn_proposal"])
            proposal_data["human_confirmed"] = True
            proposal_data["provenance"] = {
                **proposal_data.get("provenance", {}),
                "confirmed_via": "player_confirm",
                "confirmation_session_id": str(acted["session_id"]),
            }
            proposal = turn_proposal_from_dict(proposal_data)
            runtime = GMRuntime.from_path(save_path)
            validated_delta = deepcopy(delta)
            with connect(runtime.campaign) as conn:
                validation = run_validation_pipeline(
                    runtime.campaign,
                    conn,
                    profile="player_turn_commit",
                    delta=validated_delta,
                    proposal=proposal,
                    registry=runtime.action_registry,
                )
                self.assertTrue(validation.ok, validation.errors)
                first = commit_turn_delta(
                    runtime.campaign,
                    conn,
                    delta=deepcopy(validated_delta),
                    validation=validation,
                    backup=False,
                )
                self.assertEqual(first.write_status, "committed")
                with self.assertRaisesRegex(ValueError, "human-confirmed"):
                    commit_turn_delta(
                        runtime.campaign,
                        conn,
                        delta=deepcopy(validated_delta),
                        validation=validation,
                        backup=False,
                    )

            untrusted = deepcopy(proposal_data)
            untrusted["provenance"] = {"source": "forged"}
            with self.assertRaises(ValueError):
                runtime.commit_turn(delta, turn_proposal=untrusted)

            spoofed = deepcopy(proposal_data)
            spoofed["response_text"] = "caller-mutated proposal outside the confirmed digest"
            with self.assertRaises(ValueError):
                runtime.commit_turn(delta, turn_proposal=spoofed)

    def test_invalid_result_identity_presence_and_lock_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            before = authoritative_counts(save_path)
            with self.assertRaisesRegex(SaveManagerError, "unexpected platform identity"):
                manager.player_confirm(
                    str(acted["session_id"]),
                    platform="qq",
                    session_key="room:extra",
                    actor_id="actor:extra",
                )
            self.assertEqual(authoritative_counts(save_path), before)
            self.assertIsNotNone(manager.read_pending_action())
            with self.assertRaisesRegex(SaveManagerError, "invalid confirmation write result"):
                manager.player_confirm_result(
                    save=dict(manager.current_save(refresh=False)["save"]),
                    result={
                        "ok": True,
                        "write_status": "already_confirmed",
                        "idempotent_replay": False,
                    },
                    refresh_registry=False,
                )
            with self.assertRaisesRegex(SaveManagerError, "invalid confirmation write result"):
                manager.player_confirm_result(
                    save=dict(manager.current_save(refresh=False)["save"]),
                    result={
                        "ok": "yes",
                        "write_status": "committed",
                        "idempotent_replay": 0,
                    },
                    refresh_registry=False,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(
                user_text="休息到早上",
                platform="qq",
                session_key="room:partially-bound",
            )
            before = authoritative_counts(save_path)
            with self.assertRaisesRegex(SaveManagerError, "unexpected platform identity"):
                manager.player_confirm(
                    str(acted["session_id"]),
                    platform="qq",
                    session_key="room:partially-bound",
                    actor_id="actor:extra",
                )
            self.assertEqual(authoritative_counts(save_path), before)
            self.assertIsNotNone(manager.read_pending_action())

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp)
            manager = SaveManager(root)
            (root / ".aigm").mkdir()
            (root / ".aigm" / "pending-player-action.lock").symlink_to(outside / "outside.lock")
            with self.assertRaisesRegex(SaveManagerError, "pending confirmation claim is unavailable"):
                manager.player_confirm("player_action:any")
            self.assertFalse((outside / "outside.lock").exists())

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp)
            manager = SaveManager(root)
            (root / ".aigm").mkdir()
            outside_pending = outside / "pending.json"
            outside_pending.write_text("{}\n", encoding="utf-8")
            (root / ".aigm" / "pending-player-action.json").symlink_to(outside_pending)
            with self.assertRaisesRegex(SaveManagerError, "pending player action is invalid"):
                manager.read_pending_action()
            self.assertTrue(outside_pending.exists())

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "confirmation.lock"
            raw_error = OSError("cannot open /private/secret/confirmation.lock")
            with mock.patch("rpg_engine.save_manager.os.open", side_effect=raw_error):
                with self.assertRaises(SaveManagerError) as raised:
                    with confirmation_claim_lock(path):
                        pass
            self.assertNotIn("/private/secret", str(raised.exception))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "confirmation.lock"
            close_spy = mock.Mock(wraps=os.close)
            with (
                mock.patch(
                    "rpg_engine.save_manager.release_confirmation_file_lock",
                    side_effect=OSError("unlock failed"),
                ),
                mock.patch("rpg_engine.save_manager.os.close", close_spy),
            ):
                with confirmation_claim_lock(path):
                    pass
            close_spy.assert_called_once()

    def test_pending_save_path_binding_rejects_registry_path_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, first_path = self.make_workspace(root)
            first = dict(manager.current_save(refresh=False)["save"])
            second = manager.create_save(campaign="campaigns/official", label="Second", activate=False)
            second_path = root / str(second["save"]["path"])
            acted = manager.player_turn(user_text="休息到早上")
            first_before = authoritative_counts(first_path)
            second_before = authoritative_counts(second_path)
            registry = manager.read_registry()
            registry["saves"] = [
                {**dict(item), "path": second["save"]["path"]}
                if str(item.get("id")) == str(first["id"])
                else dict(item)
                for item in registry["saves"]
                if str(item.get("id")) != str(second["save"]["id"])
            ]
            manager.write_registry(registry)

            with self.assertRaisesRegex(SaveManagerError, "save path"):
                manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(authoritative_counts(first_path), first_before)
            self.assertEqual(authoritative_counts(second_path), second_before)
            self.assertIsNotNone(manager.read_pending_action())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, save_path = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            pending = dict(manager.read_pending_action() or {})
            pending.pop("save_path")
            manager.write_pending_action(pending)
            before = authoritative_counts(save_path)

            with self.assertRaisesRegex(SaveManagerError, "save path"):
                manager.player_confirm(str(acted["session_id"]))

            self.assertEqual(authoritative_counts(save_path), before)

    def test_active_save_switch_during_confirm_refresh_preserves_bound_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, first_path = self.make_workspace(root)
            first = dict(manager.current_save(refresh=False)["save"])
            second = manager.create_save(campaign="campaigns/official", label="Second", activate=False)
            second_path = root / str(second["save"]["path"])
            acted = manager.player_turn(user_text="休息到早上")
            first_before = authoritative_counts(first_path)
            second_before = authoritative_counts(second_path)
            original_require_save = manager.require_save
            switched = False

            def switch_before_refresh(*, refresh: bool, save_path: str = "") -> dict[str, object]:
                nonlocal switched
                if refresh and not switched:
                    switched = True
                    manager.switch_save(str(second["save"]["id"]), refresh=False)
                return original_require_save(refresh=refresh, save_path=save_path)

            with (
                mock.patch.object(manager, "require_save", side_effect=switch_before_refresh),
                mock.patch.object(manager, "write_registry", side_effect=AssertionError("stale registry write")),
            ):
                confirmed = manager.player_confirm(str(acted["session_id"]))

            self.assertTrue(switched)
            self.assertEqual(confirmed["write_status"], "committed")
            self.assertEqual(confirmed["save"]["id"], first["id"])
            self.assertEqual(authoritative_counts(first_path)[0], first_before[0] + 1)
            self.assertEqual(authoritative_counts(second_path), second_before)

    def test_confirmation_registry_merge_preserves_concurrent_active_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, _ = self.make_workspace(root)
            first = dict(manager.current_save(refresh=False)["save"])
            second = manager.create_save(campaign="campaigns/official", label="Second", activate=True)
            with (
                mock.patch.object(manager, "refresh_save_record", return_value={**first, "health": "ok"}),
                mock.patch.object(manager, "write_registry", side_effect=AssertionError("stale registry write")),
            ):
                manager.player_confirm_result(
                    save=first,
                    result={
                        "ok": True,
                        "turn_id": first["current_turn_id"],
                        "write_status": "committed",
                        "idempotent_replay": False,
                    },
                    refresh_registry=True,
                )

            self.assertEqual(manager.read_registry()["active_save_id"], second["save"]["id"])
            registry = manager.read_registry()
            registry["saves"] = [
                {**item, "last_played_at": "confirmation metadata marker"}
                if item["id"] == first["id"]
                else item
                for item in registry["saves"]
            ]
            manager.write_registry(registry)
            manager.merge_registry_save_record(first)
            with mock.patch.object(manager, "write_registry", side_effect=AssertionError("stale switch write")):
                manager.switch_save(str(second["save"]["id"]), refresh=False)
            registry = manager.read_registry()
            preserved_first = next(item for item in registry["saves"] if item["id"] == first["id"])
            self.assertEqual(preserved_first["last_played_at"], "confirmation metadata marker")

    def test_new_pending_publish_failure_restores_previous_replay_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager, _ = self.make_workspace(root)
            acted = manager.player_turn(user_text="休息到早上")
            manager.player_confirm(str(acted["session_id"]))
            receipt_before = manager.confirmation_receipt_path().read_bytes()

            with mock.patch.object(manager, "write_pending_action", side_effect=OSError("pending publish failed")):
                with self.assertRaisesRegex(OSError, "pending publish failed"):
                    manager.player_turn(user_text="休息到早上")

            self.assertEqual(manager.confirmation_receipt_path().read_bytes(), receipt_before)
            self.assertIsNone(manager.read_pending_action())


if __name__ == "__main__":
    unittest.main()
