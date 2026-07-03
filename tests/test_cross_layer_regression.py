from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from rpg_engine.campaign import load_campaign
from rpg_engine.context_audit import write_context_audit
from rpg_engine.content_sync import sync_campaign_content, sync_specs_for_names
from rpg_engine.db import connect
from rpg_engine.response_acceptance import accept_response, decide_save, response_state_change_blockers
from rpg_engine.runtime import GMRuntime

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    copy_current_packages,
    copy_initialized_minimal,
    current_location,
    current_turn,
    loaded_ids,
    query_int,
    query_scalar,
    run_cli,
)


class WhiteBoxContractTests(unittest.TestCase):
    def test_response_acceptance_save_decision_matrix_blocks_unsafe_paths(self) -> None:
        cases = [
            ({"lint_errors": ["missing heading"]}, False, "blocked:lint"),
            ({"draft_errors": ["bad schema"]}, False, "blocked:draft_schema"),
            ({"consistency_warnings": ["delta mismatch"]}, False, "blocked:response_delta_mismatch"),
            ({"confirm_save": True}, True, "confirmed_save"),
            ({}, False, "ready:preview_only"),
            ({"save_if_safe": True, "draft_warnings": ["needs review"]}, False, "confirmation_required"),
            ({"save_if_safe": True}, True, "safe_precheck_passed"),
        ]
        defaults = {
            "lint_errors": [],
            "draft_errors": [],
            "draft_warnings": [],
            "consistency_warnings": [],
            "save_if_safe": False,
            "confirm_save": False,
        }
        for overrides, expected_allowed, expected_decision in cases:
            with self.subTest(overrides=overrides):
                allowed, decision = decide_save(**{**defaults, **overrides})
                self.assertEqual(allowed, expected_allowed)
                self.assertEqual(decision, expected_decision)

    def test_response_acceptance_blocks_meaningful_state_change_drafts(self) -> None:
        safe_delta = {
            "events": [
                {
                    "payload": {
                        "state_changes": [
                            {"type": "无", "change": "无"},
                            {"type": "物品", "change": "无"},
                        ]
                    }
                }
            ]
        }
        risky_delta = {
            "events": [
                {
                    "payload": {
                        "state_changes": [
                            {"type": "物品", "change": "获得盐"},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(response_state_change_blockers(safe_delta), [])
        blockers = response_state_change_blockers(risky_delta)
        self.assertEqual(len(blockers), 1)
        self.assertIn("authoritative gameplay delta", blockers[0])

    def test_content_sync_default_specs_are_safe_only_and_explicit_unsafe_requires_flag(self) -> None:
        self.assertEqual([spec.name for spec in sync_specs_for_names(None)], ["world_setting"])

        with self.assertRaisesRegex(ValueError, "not sync_safe: route"):
            sync_specs_for_names(["route"])

        self.assertEqual([spec.name for spec in sync_specs_for_names(["route"], allow_unsafe=True)], ["route"])


class GrayBoxStateTests(unittest.TestCase):
    def test_context_audit_reuses_run_id_without_stale_item_rows(self) -> None:
        class AuditResult:
            def __init__(self, loaded: list[dict[str, object]], omitted: list[dict[str, object]]) -> None:
                self.request = {"user_text": "inspect", "mode": "query", "submode": "entity"}
                self.completeness = {"allow_proceed": True, "confidence": "high", "missing_required": []}
                self.budget = {"limit": 1200, "estimated": 300}
                self.loaded_items = loaded
                self.omitted_items = omitted

            def to_json_text(self) -> str:
                return json.dumps(
                    {
                        "request": self.request,
                        "loaded_items": self.loaded_items,
                        "omitted_items": self.omitted_items,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )

        conn = sqlite3.connect(":memory:")
        try:
            first = AuditResult(
                loaded=[
                    {"id": "item:a", "kind": "entity", "reason": "direct", "priority": 100, "depth": 0},
                    {"id": "item:b", "kind": "entity", "reason": "related", "priority": 50, "depth": 1},
                ],
                omitted=[{"id": "item:c", "kind": "entity", "reason": "token budget", "priority": 10, "estimated_tokens": 99}],
            )
            second = AuditResult(
                loaded=[{"id": "item:a", "kind": "entity", "reason": "direct", "priority": 100, "depth": 0}],
                omitted=[{"id": "item:d", "kind": "entity", "reason": "token budget", "priority": 5, "estimated_tokens": 44}],
            )

            self.assertEqual(write_context_audit(conn, first, run_id="context:test-stable"), "context:test-stable")
            self.assertEqual(write_context_audit(conn, second, run_id="context:test-stable"), "context:test-stable")

            item_rows = conn.execute(
                "select item_id, source, included, omitted_reason from context_items order by item_id"
            ).fetchall()
            run_count = conn.execute("select count(*) from context_runs where id='context:test-stable'").fetchone()[0]
        finally:
            conn.close()

        self.assertEqual(run_count, 1)
        self.assertEqual(
            [(row[0], row[1], int(row[2]), row[3]) for row in item_rows],
            [
                ("item:a", "loaded", 1, None),
                ("item:d", "omitted", 0, "token budget"),
            ],
        )

    def test_content_sync_is_guarded_idempotent_and_records_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_initialized_minimal(tmp)
            world_settings_path = campaign_path / "content" / "world_settings.yaml"
            world_settings_path.write_text(
                yaml.safe_dump(
                    {
                        "world_settings": [
                            {
                                "id": "world:test-sync-weather",
                                "name": "Test Sync Weather",
                                "summary": "A test-only world setting synced after initialization.",
                                "category": "weather",
                                "visibility": "known",
                                "priority": 10,
                                "content": {"rule": "Stay dry."},
                                "aliases": ["sync weather"],
                            }
                        ]
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            campaign = load_campaign(campaign_path)
            db_path = campaign_path / "data" / "game.sqlite"

            with connect(campaign) as conn:
                before_turns = conn.execute("select count(*) from turns").fetchone()[0]
                before_events = conn.execute("select count(*) from events").fetchone()[0]
                counts = sync_campaign_content(
                    campaign,
                    conn,
                    expected_turn_id="turn:seed",
                    command_id="content-sync:test-weather",
                )
                second_counts = sync_campaign_content(
                    campaign,
                    conn,
                    expected_turn_id="turn:seed",
                    command_id="content-sync:test-weather",
                )
                payload = json.loads(
                    conn.execute("select payload_json from events where type='content_sync'").fetchone()["payload_json"]
                )

            self.assertEqual(counts, {"world_settings": 1})
            self.assertEqual(second_counts, {"world_settings": 0})
            self.assertEqual(query_int(db_path, "select count(*) from turns"), before_turns + 1)
            self.assertEqual(query_int(db_path, "select count(*) from events"), before_events + 1)
            self.assertEqual(
                query_scalar(db_path, "select name from entities where id='world:test-sync-weather'"),
                "Test Sync Weather",
            )
            self.assertEqual(payload["counts"], {"world_settings": 1})
            self.assertEqual(payload["world_settings"], ["world:test-sync-weather"])
            self.assertTrue(any(path.endswith("content/world_settings.yaml") for path in payload["files"]["world_setting"]))

    def test_content_sync_validation_failure_and_stale_guard_are_zero_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid_path = copy_initialized_minimal(Path(tmp) / "invalid")
            world_settings_path = invalid_path / "content" / "world_settings.yaml"
            world_settings_path.write_text(
                yaml.safe_dump(
                    {
                        "world_settings": [
                            {
                                "id": "world:test-invalid-sync",
                                "name": "Invalid Sync",
                                "summary": "Invalid test-only record.",
                                "category": "impossible",
                            }
                        ]
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            campaign = load_campaign(invalid_path)
            db_path = invalid_path / "data" / "game.sqlite"
            before_turns = query_int(db_path, "select count(*) from turns")
            before_events = query_int(db_path, "select count(*) from events")

            with connect(campaign) as conn:
                with self.assertRaisesRegex(ValueError, "Invalid campaign content"):
                    sync_campaign_content(
                        campaign,
                        conn,
                        expected_turn_id="turn:seed",
                        command_id="content-sync:invalid",
                    )

            self.assertEqual(query_int(db_path, "select count(*) from turns"), before_turns)
            self.assertEqual(query_int(db_path, "select count(*) from events"), before_events)
            self.assertEqual(query_scalar(db_path, "select name from entities where id='world:test-invalid-sync'"), "")

        with tempfile.TemporaryDirectory() as tmp:
            stale_path = copy_initialized_minimal(Path(tmp) / "stale")
            world_settings_path = stale_path / "content" / "world_settings.yaml"
            world_settings_path.write_text(
                yaml.safe_dump(
                    {
                        "world_settings": [
                            {
                                "id": "world:test-stale-sync",
                                "name": "Stale Sync",
                                "summary": "Valid record that must not write with a stale guard.",
                                "category": "weather",
                            }
                        ]
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            campaign = load_campaign(stale_path)
            db_path = stale_path / "data" / "game.sqlite"
            before_turns = query_int(db_path, "select count(*) from turns")
            before_events = query_int(db_path, "select count(*) from events")

            with connect(campaign) as conn:
                with self.assertRaisesRegex(ValueError, "stale write"):
                    sync_campaign_content(
                        campaign,
                        conn,
                        expected_turn_id="turn:000000",
                        command_id="content-sync:stale",
                    )

            self.assertEqual(query_int(db_path, "select count(*) from turns"), before_turns)
            self.assertEqual(query_int(db_path, "select count(*) from events"), before_events)
            self.assertEqual(query_scalar(db_path, "select name from entities where id='world:test-stale-sync'"), "")


class ResponseAcceptanceIntegrationTests(unittest.TestCase):
    def test_accept_response_requires_explicit_confirmation_before_saving_response_draft(self) -> None:
        response_text = "\n".join(
            [
                "## 场景",
                "Start 很安静。",
                "",
                "## 行动结果",
                "你休息到早上。",
                "",
                "## 状态变化",
                "| 类型 | 变化 |",
                "|------|------|",
                "| 无 | 无 |",
                "",
                "## 保存状态",
                "尚未保存，需要 validate_delta 和 commit_turn。",
                "",
                "## 后续行动",
                "| # | 行动 | 预计耗时 | 风险/代价 |",
                "|---|------|----------|-----------|",
                "| 1 | 观察房间 | 片刻 | 低 |",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_initialized_minimal(tmp)
            campaign = load_campaign(campaign_path)
            db_path = campaign_path / "data" / "game.sqlite"
            before_turn = current_turn(campaign_path)
            before_turns = query_int(db_path, "select count(*) from turns")
            before_events = query_int(db_path, "select count(*) from events")

            with connect(campaign) as conn:
                preview = accept_response(
                    campaign,
                    conn,
                    user_text="rest until morning",
                    response_text=response_text,
                    mode="action",
                    submode="rest",
                )
                save_if_safe = accept_response(
                    campaign,
                    conn,
                    user_text="rest until morning",
                    response_text=response_text,
                    mode="action",
                    submode="rest",
                    save_if_safe=True,
                )

            self.assertEqual(preview.decision, "ready:preview_only")
            self.assertFalse(preview.save_allowed)
            self.assertIsNone(preview.saved_turn_id)
            self.assertEqual(save_if_safe.decision, "confirmation_required")
            self.assertFalse(save_if_safe.save_allowed)
            self.assertIsNone(save_if_safe.saved_turn_id)
            self.assertIn("response_draft requires human confirmation", "\n".join(save_if_safe.validation_errors))
            self.assertEqual(current_turn(campaign_path), before_turn)
            self.assertEqual(query_int(db_path, "select count(*) from turns"), before_turns)
            self.assertEqual(query_int(db_path, "select count(*) from events"), before_events)

            with connect(campaign) as conn:
                confirmed = accept_response(
                    campaign,
                    conn,
                    user_text="rest until morning",
                    response_text=response_text,
                    mode="action",
                    submode="rest",
                    confirm_save=True,
                )

            self.assertEqual(confirmed.decision, "confirmed_save")
            self.assertTrue(confirmed.save_allowed)
            self.assertIsNotNone(confirmed.saved_turn_id)
            self.assertTrue(confirmed.backup_id and confirmed.backup_id.startswith("backup-"))
            self.assertNotEqual(current_turn(campaign_path), before_turn)
            self.assertEqual(query_int(db_path, "select count(*) from turns"), before_turns + 1)
            self.assertEqual(query_int(db_path, "select count(*) from events"), before_events + 1)
            self.assertEqual(
                query_scalar(db_path, "select source from events where turn_id = (select value from meta where key='current_turn_id')"),
                "response_delta_draft",
            )


@CURRENT_NATIVE_REQUIRED
class CurrentNativeSystemBlackBoxTests(unittest.TestCase):
    def test_travel_commit_reopens_runtime_at_new_scene_and_social_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            runtime = GMRuntime.from_path(save)
            initial_turn = current_turn(save)

            start = runtime.start_turn("去地下菌丝城", mode="auto")
            self.assertEqual((start.mode, start.submode), ("action", "travel"))
            self.assertTrue(start.can_proceed)
            self.assertTrue(start.must_save)

            options = {"destination": "地下菌丝城", "pace": "careful", "user_text": "去地下菌丝城"}
            preview = runtime.preview_action("travel", options)
            self.assertTrue(preview.ready_to_save, preview.errors)
            self.assertEqual((preview.delta_draft or {})["expected_turn_id"], initial_turn)

            commit = runtime.commit_turn(
                preview.delta_draft or {},
                turn_proposal=preview.turn_proposal,
                action="travel",
                action_options=options,
                backup=False,
            )

            self.assertEqual(commit.write_status, "committed")
            self.assertEqual(commit.projection_status, "clean")
            self.assertNotEqual(current_turn(save), initial_turn)
            self.assertEqual(current_location(save), "loc:home-mycelium-city")
            self.assertEqual(run_cli("check", save).stdout.strip(), "OK")

            reopened = GMRuntime.from_path(save)
            self.assertIn("地下菌丝城", reopened.query("scene").text)
            social = reopened.start_turn("询问夏娃基地状态和物资交换安排", mode="auto")
            self.assertEqual((social.mode, social.submode), ("action", "social"))
            self.assertTrue(social.can_proceed, social.missing_required)
            self.assertTrue({"char:eve-mycelium-core", "world:economy-trade"}.issubset(loaded_ids(social.context)))


if __name__ == "__main__":
    unittest.main()
