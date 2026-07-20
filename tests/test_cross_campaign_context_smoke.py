from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rpg_engine.campaign import Campaign
from rpg_engine.db import connect
from rpg_engine.entity_access import read_entity
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import (
    DEFAULT_CONFIRMATION_HISTORY_RELATIVE,
    DEFAULT_CONFIRMATION_LOCK_RELATIVE,
    DEFAULT_CONFIRMATION_RECEIPT_RELATIVE,
    DEFAULT_PENDING_ACTION_RELATIVE,
    DEFAULT_PENDING_CLARIFICATION_RELATIVE,
    DEFAULT_PENDING_REVISION_RELATIVE,
    DEFAULT_REGISTRY_RELATIVE,
    SaveManager,
    SaveManagerError,
)
from rpg_engine.save_service import inspect_v1_save
from tests.helpers import CURRENT_SAVE_ROOT, tree_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT = ENGINE_ROOT.parent
DEFAULT_WORKSPACE_ROOT = HERMES_ROOT / "rp"
SAVE_REGISTRY_RELATIVE = Path(DEFAULT_REGISTRY_RELATIVE)
ALLOWED_TEMP_ENTRY_FILES = {
    Path(DEFAULT_CONFIRMATION_HISTORY_RELATIVE),
    Path(DEFAULT_CONFIRMATION_LOCK_RELATIVE),
    Path(DEFAULT_CONFIRMATION_RECEIPT_RELATIVE),
    Path(DEFAULT_REGISTRY_RELATIVE),
    Path(f"{DEFAULT_REGISTRY_RELATIVE}.lock"),
    Path(DEFAULT_PENDING_ACTION_RELATIVE),
    Path(DEFAULT_PENDING_CLARIFICATION_RELATIVE),
    Path(DEFAULT_PENDING_REVISION_RELATIVE),
    Path(DEFAULT_CONFIRMATION_LOCK_RELATIVE).parent
    / f".{Path(DEFAULT_CONFIRMATION_LOCK_RELATIVE).name}.authority",
    Path(f"{DEFAULT_REGISTRY_RELATIVE}.lock").parent
    / f".{Path(f'{DEFAULT_REGISTRY_RELATIVE}.lock').name}.authority",
}


@dataclass(frozen=True)
class CampaignCase:
    name: str
    source: Path
    context_text: str
    scene_marker: str
    rest_text: str
    hidden_entity_id: str
    hidden_canaries: tuple[str, ...]
    visible_context_markers: tuple[tuple[str, str], ...]


CASES = (
    CampaignCase(
        name="v1-minimal-adventure",
        source=ENGINE_ROOT / "examples" / "v1_minimal_adventure",
        context_text="Mira River Road Premise Storm Front",
        scene_marker="Watch Camp",
        rest_text="Rest until morning",
        hidden_entity_id="ref:tower-signal-code",
        hidden_canaries=(
            "ref:tower-signal-code",
            "Tower Signal Code",
            "A hidden code that can identify who last used the tower.",
            "signal code",
        ),
        visible_context_markers=(
            ("entity_resolution", "npc:warden-mira"),
            ("relationships", "rel:runner-mira"),
            ("progress_context", "clock:storm-front"),
            ("progress_context", "Storm Front"),
            ("world_settings", "world:river-road"),
        ),
    ),
    CampaignCase(
        name="small-cn-campaign",
        source=ENGINE_ROOT / "examples" / "small_cn_campaign",
        context_text="林向导 风暴与旧河路 风暴逼近",
        scene_marker="河道巡查营地",
        rest_text="休息到清晨",
        hidden_entity_id="ref:hidden-signal-code",
        hidden_canaries=(
            "ref:hidden-signal-code",
            "隐藏信号码",
            "山岗信号架上隐藏的编号，可指认最后使用信号的人。",
            "信号码",
        ),
        visible_context_markers=(
            ("entity_resolution", "npc:guide-lin"),
            ("relationships", "rel:pc-guide-lin"),
            ("progress_context", "clock:storm-front"),
            ("progress_context", "风暴逼近"),
            ("world_settings", "world:storm-road"),
        ),
    ),
)

EXPECTED_CONTEXT_SOURCES = {"relationships", "progress_context", "world_settings", "active_clocks"}
CONTEXT_TOP_LEVEL_KEYS = {
    "contract",
    "scope",
    "request",
    "budget",
    "completeness",
    "loaded_items",
    "omitted_items",
    "sections",
    "markdown",
}
HIDDEN_LABELS = {"hidden", "gm", "gm-only", "gm_only", "gm only"}


class CrossCampaignContextSmokeTests(unittest.TestCase):
    def test_two_campaigns_share_context_and_player_safe_loop_on_temp_saves(self) -> None:
        self.assertGreaterEqual(len(CASES), 2, global_report("campaign_prerequisites", "campaign_cases"))
        source_before = {case.name: tree_digest(case.source) for case in CASES}
        registry_paths = protected_registry_paths()
        protected_roots = protected_save_roots(registry_paths)
        protected_before = protected_save_fingerprints(protected_roots)
        registry_before = protected_registry_fingerprints(registry_paths)
        self.addCleanup(
            assert_protected_packages_unchanged,
            self,
            source_before,
            protected_before,
            protected_roots,
            registry_before,
            registry_paths,
        )
        contract_signatures: dict[str, tuple[Any, ...]] = {}
        capability_profiles: dict[str, set[str]] = {}

        for case in CASES:
            with self.subTest(campaign=case.name):
                with tempfile.TemporaryDirectory() as tmp:
                    workspace = Path(tmp)
                    assert_temp_workspace_isolated(self, workspace, case, protected_roots)
                    campaign_relative = Path("campaigns") / case.name
                    campaign_copy = workspace / campaign_relative
                    campaign_copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(case.source, campaign_copy)
                    campaign_copy_before = tree_digest(campaign_copy)
                    started: dict[str, Any] = {"save": {"path": "temporary-save"}}
                    save_path: Path | None = None
                    try:
                        manager = SaveManager(workspace, default_campaign=campaign_relative.as_posix())
                        start_report = stage_report(case, started, "player_start", "SaveManager.start_or_continue")
                        started = require_mapping_keys(
                            self,
                            call_stage(
                                start_report,
                                lambda: manager.start_or_continue(campaign=campaign_relative.as_posix()),
                            ),
                            {"ok", "save"},
                            start_report,
                        )
                        start_report = stage_report(case, started, "player_start", "SaveManager.start_or_continue")
                        self.assertTrue(bool(started.get("ok")), start_report)
                        save_record = require_mapping_keys(
                            self,
                            started.get("save"),
                            {"id", "path"},
                            start_report,
                        )
                        save_path = (workspace / str(save_record.get("path"))).resolve()
                        self.assertTrue(save_path.is_relative_to(workspace.resolve()), start_report)
                        runtime = call_stage(
                            stage_report(case, started, "runtime_open", "GMRuntime.from_path"),
                            lambda: GMRuntime.from_path(save_path),
                        )
                        capability_profiles[case.name] = set(runtime.campaign.config.get("capabilities", ()))
                        self.assertTrue(
                            {"query", "rest_time"} <= capability_profiles[case.name],
                            stage_report(case, started, "campaign_prerequisites", "capabilities"),
                        )
                        hidden_report = stage_report(case, started, "hidden_fixture", "entity_access")
                        self.assertTrue(
                            bool(case.hidden_canaries)
                            and all(isinstance(canary, str) and bool(canary) for canary in case.hidden_canaries),
                            hidden_report,
                        )
                        hidden_payload = call_stage(
                            hidden_report,
                            lambda: hidden_fixture_payload(runtime.campaign, case.hidden_entity_id),
                        )
                        self.assertTrue(hidden_payload.get("visibility") in HIDDEN_LABELS, hidden_report)
                        hidden_blob = json.dumps(hidden_payload, ensure_ascii=False, sort_keys=True)
                        self.assertTrue(all(canary in hidden_blob for canary in case.hidden_canaries), hidden_report)

                        before_context = authoritative_snapshot(save_path)
                        audit_rows_before = context_run_count(save_path)
                        start_context_report = stage_report(
                            case,
                            started,
                            "start_turn_context",
                            "ContextBuildResult",
                        )
                        start_turn = call_stage(
                            start_context_report,
                            lambda: runtime.start_turn(
                                case.context_text,
                                mode="query",
                                submode="context",
                                view="player",
                            ),
                        )
                        context_query_report = stage_report(
                            case,
                            started,
                            "context_query",
                            "ContextBuildResult",
                        )
                        context_query = call_stage(
                            context_query_report,
                            lambda: runtime.query("context", case.context_text, view="player"),
                        )
                        scene_report = stage_report(case, started, "basic_query", "scene_renderer")
                        scene_query = call_stage(
                            scene_report,
                            lambda: runtime.query("scene", view="player"),
                        )
                        self.assertTrue(bool(start_turn.can_proceed), start_context_report)
                        self.assertTrue(start_turn.context is not None, start_context_report)
                        self.assertTrue(context_query.context is not None, context_query_report)
                        self.assertTrue(case.scene_marker in scene_query.text, scene_report)

                        entry_contexts = {
                            "start_turn_context": start_turn.context,
                            "context_query": context_query.context,
                        }
                        entry_signatures: dict[str, tuple[Any, ...]] = {}
                        for entry_stage, context in entry_contexts.items():
                            assert context is not None
                            entry_report = stage_report(case, started, entry_stage, "ContextBuildResult")
                            payload_text = context.to_json_text()
                            payload = call_stage(entry_report, lambda: json.loads(payload_text))
                            self.assertTrue(CONTEXT_TOP_LEVEL_KEYS <= set(payload), entry_report)
                            self.assertTrue(context.contract.get("id") == "ContextBuildResult", entry_report)
                            self.assertTrue(context.contract.get("version") == "1.0", entry_report)
                            self.assertTrue(context.contract.get("visibility_mode") == "player", entry_report)
                            self.assertTrue(context.scope.get("visibility_mode") == "player", entry_report)
                            for field in ("pipeline_steps", "collector_sources", "audit_tables"):
                                value = context.contract.get(field)
                                self.assertTrue(
                                    isinstance(value, (list, tuple)) and bool(value),
                                    stage_report(case, started, f"{entry_stage}_contract", f"contract.{field}"),
                                )
                            loaded_sources = {str(item.get("source")) for item in context.loaded_items}
                            for source in EXPECTED_CONTEXT_SOURCES:
                                self.assertTrue(
                                    source in loaded_sources,
                                    stage_report(case, started, f"{entry_stage}_source", source),
                                )
                            for source, marker in case.visible_context_markers:
                                self.assertTrue(
                                    marker in source_evidence_payload(context, source),
                                    stage_report(case, started, f"{entry_stage}_content", source),
                                )
                            for foreign_marker in foreign_visible_markers(case):
                                self.assertTrue(
                                    foreign_marker not in payload_text,
                                    stage_report(
                                        case,
                                        started,
                                        f"{entry_stage}_campaign_isolation",
                                        "foreign_campaign_marker",
                                    ),
                                )
                            assert_player_context_has_no_hidden_canary(
                                self,
                                case,
                                payload_text,
                                stage_report(case, started, f"{entry_stage}_hidden_guard", "player_payload"),
                            )
                            assert_no_hidden_oracle_evidence(
                                self,
                                {"omitted_items": context.omitted_items, "completeness": context.completeness},
                                stage_report(case, started, f"{entry_stage}_non_oracle", "context_evidence"),
                            )
                            entry_signatures[entry_stage] = context_signature(context)
                        self.assertTrue(
                            entry_signatures["start_turn_context"] == entry_signatures["context_query"],
                            stage_report(case, started, "context_signature", "start_turn+query"),
                        )
                        contract_signatures[case.name] = entry_signatures["start_turn_context"]

                        player_payloads = (
                            ("start_turn_hidden_guard", "StartTurnResult", start_turn.to_json_text()),
                            ("context_query_hidden_guard", "QueryResult", context_query.to_json_text()),
                            ("scene_query_hidden_guard", "scene_renderer", scene_query.to_json_text()),
                        )
                        for stage, source, payload in player_payloads:
                            assert_player_context_has_no_hidden_canary(
                                self,
                                case,
                                payload,
                                stage_report(case, started, stage, source),
                            )
                        self.assertTrue(
                            authoritative_snapshot(save_path) == before_context,
                            stage_report(case, started, "context_no_write", "sqlite_application_tables"),
                        )
                        self.assertTrue(
                            context_run_count(save_path) == audit_rows_before,
                            stage_report(case, started, "context_audit_opt_in", "main.context_runs"),
                        )

                        preview_options = {"until": "morning", "user_text": case.rest_text}
                        preview_report = stage_report(case, started, "preview", "rest_resolver")
                        preview = call_stage(
                            preview_report,
                            lambda: runtime.preview_action("rest", preview_options),
                        )
                        self.assertTrue(bool(preview.ok and preview.ready_to_save), preview_report)
                        self.assertTrue(isinstance(preview.delta_draft, dict), preview_report)
                        self.assertTrue(isinstance(preview.turn_proposal, dict), preview_report)
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            safe_json(preview.to_dict()),
                            stage_report(case, started, "preview_hidden_guard", "PreviewActionResult"),
                        )
                        assert_no_hidden_oracle_evidence(
                            self,
                            preview.to_dict(),
                            stage_report(case, started, "preview_non_oracle", "PreviewActionResult"),
                        )
                        self.assertTrue(authoritative_snapshot(save_path) == before_context, preview_report)

                        assert preview.delta_draft is not None
                        validation_report = stage_report(case, started, "validation", "player_turn_commit")
                        validation = call_stage(
                            validation_report,
                            lambda: runtime.validate_delta(
                                preview.delta_draft,
                                action="rest",
                                action_options=preview_options,
                            ),
                        )
                        self.assertTrue(bool(validation.ok), validation_report)
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            safe_json(validation.to_dict()),
                            stage_report(case, started, "validation_hidden_guard", "DeltaValidationResult"),
                        )
                        assert_no_hidden_oracle_evidence(
                            self,
                            validation.to_dict(),
                            stage_report(case, started, "validation_non_oracle", "DeltaValidationResult"),
                        )
                        self.assertTrue(authoritative_snapshot(save_path) == before_context, validation_report)

                        pending_report = stage_report(case, started, "pending_action", "SaveManager.player_turn")
                        acted = require_mapping_keys(
                            self,
                            call_stage(pending_report, lambda: manager.player_turn(user_text=case.rest_text)),
                            {"ok", "ready_to_confirm", "saved", "session_id"},
                            pending_report,
                        )
                        self.assertTrue(bool(acted.get("ok")), pending_report)
                        self.assertTrue(bool(acted.get("ready_to_confirm")), pending_report)
                        self.assertTrue(acted.get("saved") is False, pending_report)
                        self.assertTrue(bool(acted.get("session_id")), pending_report)
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            safe_json(acted),
                            stage_report(case, started, "player_turn_hidden_guard", "SaveManager.player_turn"),
                        )
                        assert_no_hidden_oracle_evidence(
                            self,
                            acted,
                            stage_report(case, started, "player_turn_non_oracle", "SaveManager.player_turn"),
                        )
                        pending = require_mapping_keys(
                            self,
                            call_stage(pending_report, manager.read_pending_action),
                            {
                                "session_id",
                                "save_id",
                                "save_path",
                                "user_text",
                                "action",
                                "delta",
                                "turn_proposal",
                                "expires_at",
                            },
                            pending_report,
                        )
                        self.assertTrue(pending.get("session_id") == acted.get("session_id"), pending_report)
                        self.assertTrue(pending.get("save_id") == save_record.get("id"), pending_report)
                        self.assertTrue(pending.get("save_path") == save_record.get("path"), pending_report)
                        self.assertTrue(pending.get("user_text") == case.rest_text, pending_report)
                        self.assertTrue(pending.get("action") == "rest", pending_report)
                        self.assertTrue(isinstance(pending.get("delta"), dict), pending_report)
                        self.assertTrue(isinstance(pending.get("turn_proposal"), dict), pending_report)
                        self.assertTrue(bool(pending.get("expires_at")), pending_report)
                        pending_proposal = require_mapping_keys(
                            self,
                            pending.get("turn_proposal"),
                            {"delta", "human_confirmed", "turn_contract"},
                            pending_report,
                        )
                        pending_contract = require_mapping_keys(
                            self,
                            pending_proposal.get("turn_contract"),
                            {"validation_profile"},
                            pending_report,
                        )
                        self.assertTrue(
                            pending_contract.get("validation_profile") == "player_turn_commit",
                            pending_report,
                        )
                        self.assertTrue(pending_proposal.get("human_confirmed") is False, pending_report)
                        self.assertTrue(pending_proposal.get("delta") == pending.get("delta"), pending_report)
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            safe_json(pending),
                            stage_report(case, started, "pending_hidden_guard", "pending_action"),
                        )
                        assert_no_hidden_oracle_evidence(
                            self,
                            pending,
                            stage_report(case, started, "pending_non_oracle", "pending_action"),
                        )
                        self.assertTrue(authoritative_snapshot(save_path) == before_context, pending_report)

                        pending_before_wrong = safe_json(pending)
                        wrong_session_report = stage_report(
                            case,
                            started,
                            "wrong_session_reject",
                            "SaveManager.player_confirm",
                        )
                        wrong_session_error = assert_stage_raises(
                            self,
                            SaveManagerError,
                            wrong_session_report,
                            lambda: manager.player_confirm("player_action:wrong-session"),
                        )
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            str(wrong_session_error),
                            stage_report(case, started, "wrong_session_error_guard", "SaveManagerError"),
                        )
                        self.assertTrue(authoritative_snapshot(save_path) == before_context, wrong_session_report)
                        self.assertTrue(
                            safe_json(call_stage(wrong_session_report, manager.read_pending_action)) == pending_before_wrong,
                            wrong_session_report,
                        )

                        confirm_report = stage_report(
                            case,
                            started,
                            "confirm_commit",
                            "SaveManager.player_confirm",
                        )
                        confirmed = require_mapping_keys(
                            self,
                            call_stage(
                                confirm_report,
                                lambda: manager.player_confirm(str(acted.get("session_id"))),
                            ),
                            {"ok", "saved", "projection_status"},
                            confirm_report,
                        )
                        self.assertTrue(bool(confirmed.get("ok")), confirm_report)
                        self.assertTrue(bool(confirmed.get("saved")), confirm_report)
                        self.assertTrue(call_stage(confirm_report, manager.read_pending_action) is None, confirm_report)
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            safe_json(confirmed),
                            stage_report(case, started, "confirm_hidden_guard", "SaveManager.player_confirm"),
                        )
                        assert_no_hidden_oracle_evidence(
                            self,
                            confirmed,
                            stage_report(case, started, "confirm_non_oracle", "SaveManager.player_confirm"),
                        )
                        after_confirm = authoritative_snapshot(save_path)
                        self.assertTrue(after_confirm != before_context, confirm_report)
                        self.assertTrue(
                            after_confirm["turn_count"] == before_context["turn_count"] + 1,
                            confirm_report,
                        )
                        self.assertTrue(after_confirm["event_count"] > before_context["event_count"], confirm_report)
                        replay_report = stage_report(
                            case,
                            started,
                            "confirmed_session_replay",
                            "SaveManager.player_confirm",
                        )
                        replayed = require_mapping_keys(
                            self,
                            call_stage(
                                replay_report,
                                lambda: manager.player_confirm(str(acted.get("session_id"))),
                            ),
                            {"ok", "saved", "write_status", "idempotent_replay", "message"},
                            replay_report,
                        )
                        self.assertTrue(replayed["ok"], replay_report)
                        self.assertFalse(replayed["saved"], replay_report)
                        self.assertEqual(replayed["write_status"], "already_confirmed", replay_report)
                        self.assertTrue(replayed["idempotent_replay"], replay_report)
                        assert_player_context_has_no_hidden_canary(
                            self,
                            case,
                            str(replayed),
                            stage_report(case, started, "replay_result_guard", "SaveManager.player_confirm"),
                        )
                        self.assertTrue(authoritative_snapshot(save_path) == after_confirm, replay_report)
                        self.assertTrue(
                            call_stage(replay_report, manager.read_pending_action) is None,
                            replay_report,
                        )
                        inspected = require_mapping_keys(
                            self,
                            call_stage(
                                stage_report(case, started, "projection_health", "inspect_v1_save"),
                                lambda: inspect_v1_save(save_path),
                            ),
                            {"ok", "projection_health"},
                            confirm_report,
                        )
                        self.assertTrue(bool(inspected.get("ok")), confirm_report)
                        projection_health = require_mapping_keys(
                            self,
                            inspected.get("projection_health"),
                            {"authority"},
                            confirm_report,
                        )
                        self.assertTrue(projection_health.get("authority") == "evidence", confirm_report)
                    finally:
                        campaign_copy_unchanged = tree_digest(campaign_copy) == campaign_copy_before
                        workspace_scope_valid = temp_workspace_write_scope_is_valid(
                            workspace,
                            campaign_copy,
                            save_path,
                        )
                        self.assertTrue(
                            campaign_copy_unchanged,
                            stage_report(case, started, "campaign_copy_no_mutation", "campaign_fingerprint"),
                        )
                        self.assertTrue(
                            workspace_scope_valid,
                            stage_report(case, started, "workspace_write_scope", "temporary_workspace"),
                        )

        signatures = list(contract_signatures.values())
        self.assertTrue(
            len(signatures) == len(CASES),
            global_report("context_signature", "campaign_cases"),
        )
        self.assertTrue(
            all(signature == signatures[0] for signature in signatures[1:]),
            global_report("context_signature", "cross_campaign_contract"),
        )
        profiles = list(capability_profiles.values())
        self.assertTrue(
            len(profiles) == len(CASES) and any(profile != profiles[0] for profile in profiles[1:]),
            global_report("campaign_prerequisites", "capability_profiles"),
        )


def stage_report(
    case: CampaignCase,
    started: dict[str, Any],
    stage: str,
    context_source: str,
) -> str:
    save = started.get("save") if isinstance(started.get("save"), dict) else {}
    return json.dumps(
        {
            "campaign": case.name,
            "save": str(save.get("path") or "temporary-save"),
            "stage": stage,
            "context_source": context_source,
            "visibility_mode": "player",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def global_report(stage: str, context_source: str) -> str:
    return json.dumps(
        {
            "campaign": "all-campaigns",
            "save": "configured-formal-saves",
            "stage": stage,
            "context_source": context_source,
            "visibility_mode": "player",
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def call_stage(report: str, callback: Callable[[], Any]) -> Any:
    try:
        return callback()
    except Exception:
        raise AssertionError(report) from None


def require_mapping_keys(
    testcase: unittest.TestCase,
    value: Any,
    required: set[str],
    report: str,
) -> dict[str, Any]:
    testcase.assertTrue(isinstance(value, dict), report)
    assert isinstance(value, dict)
    testcase.assertTrue(required <= set(value), report)
    return value


def assert_stage_raises(
    testcase: unittest.TestCase,
    expected: type[Exception],
    report: str,
    callback: Callable[[], Any],
) -> Exception:
    try:
        callback()
    except expected as exc:
        return exc
    except Exception:
        raise AssertionError(report) from None
    testcase.fail(report)


def authoritative_snapshot(save_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(save_path / "data" / "game.sqlite")
    try:
        schema = tuple(
            tuple(row)
            for row in conn.execute(
                """
                SELECT type, name, tbl_name, COALESCE(sql, '')
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            ).fetchall()
        )
        tables = tuple(
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        )
        rows_by_table: dict[str, tuple[tuple[Any, ...], ...]] = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows = conn.execute(f"SELECT * FROM {quoted}").fetchall()
            rows_by_table[table] = tuple(sorted((tuple(row) for row in rows), key=repr))
        return {
            "schema": schema,
            "rows": rows_by_table,
            "turn_count": len(rows_by_table["turns"]),
            "event_count": len(rows_by_table["events"]),
        }
    finally:
        conn.close()


def context_run_count(save_path: Path) -> int:
    conn = sqlite3.connect(save_path / "data" / "game.sqlite")
    try:
        row = conn.execute("SELECT count(*) FROM main.context_runs").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def assert_player_context_has_no_hidden_canary(
    testcase: unittest.TestCase,
    case: CampaignCase,
    payload: str,
    report: str,
) -> None:
    testcase.assertFalse(
        any(canary in payload for campaign in CASES for canary in campaign.hidden_canaries),
        report,
    )
    testcase.assertFalse(any(marker in payload for marker in foreign_visible_markers(case)), report)


def assert_no_hidden_oracle_evidence(
    testcase: unittest.TestCase,
    evidence: Any,
    report: str,
) -> None:
    testcase.assertFalse(contains_hidden_oracle(evidence), report)


def contains_hidden_oracle(value: Any, *, parent_key: str = "") -> bool:
    normalized_parent = normalize_evidence_key(parent_key)
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = normalize_evidence_key(key)
            visibility_key = (
                "hidden" in normalized_key
                or "gm_only" in normalized_key
                or normalized_key.startswith("gm_")
                or normalized_key.endswith("_gm")
            )
            if visibility_key:
                if normalized_key == "hidden_allowed":
                    if nested is not False:
                        return True
                else:
                    return True
            if normalized_key in {"hidden", "gm", "gm_only"}:
                return True
            if (
                visibility_key
                and any(token in normalized_key for token in ("count", "total", "exists", "present"))
            ):
                return True
            if normalized_parent in {"hidden", "gm", "gm_only"} and normalized_key in {
                "endpoint",
                "alias",
                "id",
                "name",
                "summary",
            }:
                return True
            if normalized_key in {
                "hidden_endpoint",
                "hidden_alias",
                "hidden_id",
                "hidden_name",
                "hidden_summary",
                "gm_endpoint",
                "gm_alias",
                "gm_id",
                "gm_name",
                "gm_summary",
                "gm_only_endpoint",
                "gm_only_alias",
                "gm_only_id",
                "gm_only_name",
                "gm_only_summary",
            }:
                return True
            if contains_hidden_oracle(nested, parent_key=normalized_key):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(contains_hidden_oracle(item, parent_key=parent_key) for item in value)
    if isinstance(value, str) and normalized_parent in {
        "visibility",
        "visibilities",
        "visibility_count",
        "visibility_counts",
        "visibility_mode",
        "reason_code",
        "reason_codes",
        "omission_category",
        "omission_categories",
        "category",
        "categories",
    }:
        return contains_hidden_visibility_label(value)
    return False


def normalize_evidence_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def contains_hidden_visibility_label(value: Any) -> bool:
    normalized = normalize_evidence_key(value)
    return re.search(r"(^|[^a-z0-9])(hidden|gm(?:_only)?)(?=$|[^a-z0-9])", normalized) is not None


def context_signature(context: Any) -> tuple[Any, ...]:
    contract = context.contract if isinstance(context.contract, dict) else {}
    return (
        contract.get("id"),
        contract.get("version"),
        tuple(contract["pipeline_steps"]),
        tuple(contract["collector_sources"]),
        tuple(sorted(contract["audit_tables"])),
    )


def source_evidence_payload(context: Any, source: str) -> str:
    loaded_items = [item for item in context.loaded_items if str(item.get("source")) == source]
    section_keys = {
        str(item.get("provenance", {}).get("section"))
        for item in loaded_items
        if isinstance(item.get("provenance"), dict) and item.get("provenance", {}).get("section")
    }
    return safe_json(
        {
            "loaded_items": loaded_items,
            "sections": {key: context.sections.get(key) for key in section_keys},
        }
    )


def foreign_visible_markers(case: CampaignCase) -> tuple[str, ...]:
    own = {marker for _, marker in case.visible_context_markers}
    foreign = {
        marker
        for other in CASES
        if other.name != case.name
        for _, marker in other.visible_context_markers
        if marker not in own
    }
    return tuple(sorted(foreign))


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def hidden_fixture_payload(campaign: Campaign, entity_id: str) -> dict[str, Any]:
    with connect(campaign) as conn:
        entity = read_entity(conn, entity_id, view="maintenance")
        if entity is None:
            return {}
        aliases = [
            str(row[0])
            for row in conn.execute(
                "SELECT alias FROM main.aliases WHERE entity_id = ? ORDER BY alias",
                (entity_id,),
            ).fetchall()
        ]
        return {
            "id": entity.id,
            "name": entity.name,
            "summary": entity.summary,
            "visibility": str(entity.visibility).strip().lower(),
            "aliases": aliases,
        }


def assert_temp_workspace_isolated(
    testcase: unittest.TestCase,
    workspace: Path,
    case: CampaignCase,
    protected_roots: tuple[Path, ...],
) -> None:
    target = workspace.resolve()
    roots = tuple(item.source.resolve() for item in CASES) + tuple(root.resolve() for root in protected_roots)
    for protected in roots:
        overlaps = target == protected or protected in target.parents or target in protected.parents
        testcase.assertFalse(
            overlaps,
            stage_report(case, {"save": {"path": "temporary-save"}}, "workspace_isolation", "path_boundary"),
        )


def temp_workspace_write_scope_is_valid(
    workspace: Path,
    campaign_copy: Path,
    save_path: Path | None,
) -> bool:
    if not workspace.is_dir():
        return False
    allowed_top_level = {".aigm", "campaigns", "saves"}
    top_level = {path.name for path in workspace.iterdir()}
    if not top_level <= allowed_top_level:
        return False
    campaigns_root = workspace / "campaigns"
    if not campaigns_root.is_dir() or {path.name for path in campaigns_root.iterdir()} != {campaign_copy.name}:
        return False
    workspace_resolved = workspace.resolve()
    paths = tuple(workspace.rglob("*"))
    if any(path.is_symlink() for path in paths):
        return False
    for root in (workspace / ".aigm", campaigns_root, workspace / "saves"):
        if root.exists() and (not root.is_dir() or not root.resolve().is_relative_to(workspace_resolved)):
            return False
    entry_root = workspace / ".aigm"
    if entry_root.exists():
        entry_items = tuple(entry_root.rglob("*"))
        if any(not path.is_file() for path in entry_items):
            return False
        entry_paths = {path.relative_to(workspace) for path in entry_items}
        if not entry_paths <= ALLOWED_TEMP_ENTRY_FILES:
            return False
    saves_root = workspace / "saves"
    if saves_root.exists():
        if save_path is None:
            if any(saves_root.iterdir()):
                return False
        else:
            expected_save = save_path.resolve()
            if not expected_save.is_dir() or not expected_save.is_relative_to(saves_root.resolve()):
                return False
            for path in saves_root.rglob("*"):
                resolved = path.resolve()
                if resolved != expected_save and expected_save not in resolved.parents and resolved not in expected_save.parents:
                    return False
    return True


def protected_registry_paths() -> tuple[Path, ...]:
    registry_paths = {DEFAULT_WORKSPACE_ROOT / SAVE_REGISTRY_RELATIVE}
    configured = Path(os.environ.get("RPG_ENGINE_CURRENT_SAVE_ROOT", CURRENT_SAVE_ROOT)).expanduser()
    resolved_configured = configured.resolve()
    for candidate in (configured, *configured.parents, resolved_configured, *resolved_configured.parents):
        registry_paths.add(candidate / SAVE_REGISTRY_RELATIVE)
    return tuple(sorted(registry_paths, key=lambda path: str(path.absolute())))


def protected_save_roots(registry_paths: tuple[Path, ...]) -> tuple[Path, ...]:
    roots = [CURRENT_SAVE_ROOT]
    for registry_path in registry_paths:
        if not registry_path.exists() and not registry_path.is_symlink():
            continue
        try:
            workspace_root = registry_path.parent.parent
            if not registry_path.resolve().is_relative_to(workspace_root.resolve()):
                raise ValueError("registry escapes workspace root")
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if not isinstance(registry, dict):
                raise ValueError("registry must be an object")
            if str(registry.get("schema_version") or "") != "1" or "saves" not in registry:
                raise ValueError("registry schema is unsupported")
            saves = registry["saves"]
            if not isinstance(saves, list):
                raise ValueError("registry saves must be a list")
            for item in saves:
                if not isinstance(item, dict):
                    raise ValueError("registry save record must be an object")
                path = item.get("path")
                if not isinstance(path, str) or not path.strip():
                    raise ValueError("registry save path must be a non-empty string")
                roots.append(SaveManager(workspace_root).resolve_relative(path, "save.path"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            raise AssertionError(
                global_report("formal_save_registry", "registry_parse_and_shape")
            ) from None
    unique: dict[Path, Path] = {}
    for root in roots:
        unique[root.resolve()] = root
    return tuple(unique.values())


def protected_save_fingerprints(roots: tuple[Path, ...]) -> dict[str, str]:
    return {str(root.resolve()): optional_tree_digest(root) for root in roots}


def protected_registry_fingerprints(
    paths: tuple[Path, ...],
) -> dict[str, tuple[str | None, bytes | None]]:
    try:
        return {
            str(path.absolute()): (
                os.readlink(path) if path.is_symlink() else None,
                path.read_bytes() if path.exists() else None,
            )
            for path in paths
        }
    except OSError:
        raise AssertionError(
            global_report("formal_save_registry", "registry_fingerprint")
        ) from None


def assert_protected_packages_unchanged(
    testcase: unittest.TestCase,
    source_before: dict[str, str],
    protected_before: dict[str, str],
    protected_roots: tuple[Path, ...],
    registry_before: dict[str, tuple[str | None, bytes | None]],
    registry_paths: tuple[Path, ...],
) -> None:
    source_unchanged = {case.name: tree_digest(case.source) for case in CASES} == source_before
    saves_unchanged = protected_save_fingerprints(protected_roots) == protected_before
    registries_unchanged = protected_registry_fingerprints(registry_paths) == registry_before
    testcase.assertTrue(
        source_unchanged,
        global_report("source_campaign_no_mutation", "campaign_fingerprint"),
    )
    testcase.assertTrue(
        saves_unchanged,
        global_report("formal_save_no_mutation", "save_fingerprint"),
    )
    testcase.assertTrue(
        registries_unchanged,
        global_report("formal_registry_no_mutation", "registry_fingerprint"),
    )


def optional_tree_digest(root: Path) -> str:
    return tree_digest(root) if root.exists() else "missing"


if __name__ == "__main__":
    unittest.main()
