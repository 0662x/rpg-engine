from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from rpg_engine.mcp_adapter import (
    AIGMMCPAdapter,
    DEVELOPER_PROFILE,
    LOW_LEVEL_MCP_TOOL_NAMES,
    MCPAdapterConfig,
    MCP_TOOL_NAMES,
    PLAYER_MCP_TOOL_NAMES,
    PLAYER_PROFILE,
    build_client_config,
    mcp_tool_names_for_profile,
    serve_mcp,
)
from rpg_engine.db import connect, upsert_entity
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_service import init_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def sqlite_counts(save_dir: Path) -> dict[str, int]:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    try:
        return {
            name: int(conn.execute(f"select count(*) from {name}").fetchone()[0])
            for name in ("turns", "events", "entities", "clocks", "intent_preflight_cache")
        }
    finally:
        conn.close()


def install_fake_hermes(tmp: str | Path, output: str) -> str:
    bin_dir = Path(tmp) / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_hermes = bin_dir / "hermes"
    fake_hermes.write_text("#!/bin/sh\nprintf '%s\\n' " + repr(output) + "\n", encoding="utf-8")
    fake_hermes.chmod(0o755)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old_path}"
    return old_path


class MCPAdapterTests(unittest.TestCase):
    def test_mcp_adapter_exposes_only_v1_runtime_tools(self) -> None:
        self.assertEqual(
            MCP_TOOL_NAMES,
            (
                "workspace_inspect",
                "campaign_list",
                "save_list",
                "save_current",
                "save_create",
                "save_switch",
                "start_or_continue",
                "intent_manifest",
                "player_turn",
                "player_confirm",
                "campaign_validate",
                "save_inspect",
                "health",
                "player_query",
                "player_act",
                "start_turn",
                "intent_preflight",
                "query",
                "preview_from_text",
                "preview_action",
                "validate_delta",
                "commit_turn",
            ),
        )
        self.assertEqual(mcp_tool_names_for_profile(PLAYER_PROFILE), PLAYER_MCP_TOOL_NAMES)
        self.assertEqual(mcp_tool_names_for_profile(DEVELOPER_PROFILE), MCP_TOOL_NAMES)
        self.assertEqual(MCP_TOOL_NAMES, PLAYER_MCP_TOOL_NAMES + LOW_LEVEL_MCP_TOOL_NAMES)
        self.assertNotIn("repair", MCP_TOOL_NAMES)
        self.assertNotIn("plugin", MCP_TOOL_NAMES)
        for forbidden in (
            "package_install",
            "package_upgrade",
            "package_reconcile",
            "migration_apply",
            "projection_repair",
            "file_read",
            "file_write",
            "model_proxy",
        ):
            self.assertNotIn(forbidden, MCP_TOOL_NAMES)

    def test_mcp_contract_names_every_player_profile_forbidden_low_level_tool(self) -> None:
        contract = (ENGINE_ROOT / "docs" / "mcp-contracts.md").read_text(encoding="utf-8")

        self.assertIn("player profile 不能注册或调用", contract)
        for tool in LOW_LEVEL_MCP_TOOL_NAMES:
            self.assertIn(f"`{tool}`", contract)
            self.assertIn(f"`{tool}`", contract.split("player profile 不能注册或调用", 1)[1].split("## 工具清单", 1)[0])

    def test_mcp_adapter_does_not_depend_on_cli_handlers(self) -> None:
        source = (ENGINE_ROOT / "rpg_engine" / "mcp_adapter.py").read_text(encoding="utf-8")
        self.assertNotIn("from .cli", source)
        self.assertNotIn("import .cli", source)

    def test_mcp_tool_descriptions_explain_external_ai_boundaries(self) -> None:
        source = (ENGINE_ROOT / "rpg_engine" / "mcp_adapter.py").read_text(encoding="utf-8")

        self.assertIn("does not advance story or gameplay facts", source)
        self.assertIn("gameplay facts still require player_turn/player_confirm", source)
        self.assertIn("Read-only kernel-generated action/query manifest", source)
        self.assertIn("Read-only validation for a configured campaign package", source)
        self.assertIn("Standard player turn entry", source)
        self.assertIn("without exposing delta JSON", source)
        self.assertIn("Confirm and save the pending player action", source)
        self.assertIn("Low-level natural-language preview primitive", source)
        self.assertIn("already-selected low-level action contract", source)
        self.assertIn("validated and accepted TurnProposal delta", source)
        self.assertIn("does not repair state", source)

    def test_mcp_server_registers_player_surface_by_profile(self) -> None:
        class FakeFastMCP:
            instances: list["FakeFastMCP"] = []

            def __init__(self, name: str) -> None:
                self.name = name
                self.tools: list[str] = []
                FakeFastMCP.instances.append(self)

            def tool(self):
                def decorate(callback):
                    self.tools.append(callback.__name__)
                    return callback

                return decorate

            def run(self, transport: str = "stdio") -> None:
                self.transport = transport

        fastmcp_module = types.ModuleType("mcp.server.fastmcp")
        fastmcp_module.FastMCP = FakeFastMCP
        server_module = types.ModuleType("mcp.server")
        mcp_module = types.ModuleType("mcp")

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            sys.modules,
            {
                "mcp": mcp_module,
                "mcp.server": server_module,
                "mcp.server.fastmcp": fastmcp_module,
            },
        ):
            serve_mcp(MCPAdapterConfig.from_values(tmp, mcp_profile=PLAYER_PROFILE))
            player_tools = tuple(FakeFastMCP.instances[-1].tools)
            serve_mcp(MCPAdapterConfig.from_values(tmp, mcp_profile=DEVELOPER_PROFILE))
            developer_tools = tuple(FakeFastMCP.instances[-1].tools)

        self.assertEqual(player_tools, PLAYER_MCP_TOOL_NAMES)
        self.assertEqual(set(developer_tools), set(MCP_TOOL_NAMES))
        for tool in LOW_LEVEL_MCP_TOOL_NAMES:
            self.assertNotIn(tool, player_tools)

    def test_mcp_adapter_runs_campaign_save_and_runtime_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )
            campaign = adapter.campaign_validate()
            inspect = adapter.save_inspect()
            manifest = adapter.intent_manifest()
            start = adapter.start_turn("查看周围", mode="query", submode="scene")
            query = adapter.query("scene")
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 判断这是休息行动。",
            }
            text_preview = adapter.preview_from_text("休息到早上", external_intent_candidate=external)
            preview = adapter.preview_action("rest", options={"until": "morning", "user_text": "休息到早上"})
            delta = preview["delta_draft"]
            validation = adapter.validate_delta(delta)
            commit = adapter.commit_turn(delta, turn_proposal=preview["turn_proposal"])
            health = adapter.health()

            self.assertTrue(campaign["ok"], campaign)
            self.assertTrue(inspect["ok"], inspect)
            self.assertIn("travel", [action["name"] for action in manifest["actions"]])
            self.assertEqual([query["kind"] for query in manifest["queries"]], ["scene", "entity", "context"])
            self.assertTrue(start["can_proceed"], start)
            self.assertIn("Start", query["text"])
            self.assertEqual(text_preview["action"], "rest")
            self.assertTrue(text_preview["ready_to_save"], text_preview)
            self.assertEqual(
                text_preview["interpretation"]["intent"]["decision_trace"]["intent_ai"]["external_candidate"]["action"],
                "rest",
            )
            self.assertEqual(text_preview["interpretation"]["intent"]["source"], "external_primary")
            self.assertEqual(
                text_preview["interpretation"]["intent"]["decision_trace"]["intent_ai"]["route_authority"],
                "external_primary",
            )
            self.assertEqual(text_preview["turn_proposal"]["delta_source"], "resolver_proposed")
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["turn_proposal"]["delta_source"], "resolver_proposed")
            self.assertTrue(validation["ok"], validation)
            self.assertEqual(commit["turn_id"], "turn:000001")
            self.assertEqual(commit["state_audit"]["risk"], "low")
            self.assertTrue(health["ok"], health)

    def test_mcp_preview_returns_structured_error_for_malformed_external_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )
            before_counts = sqlite_counts(save_dir)

            result = adapter.preview_from_text(
                "休息到早上",
                external_intent_candidate={
                    "kind": "single",
                    "mode": "action",
                    "action": "rest",
                    "slots": {"until": "morning"},
                },
            )

            self.assertFalse(result["ok"], result)
            self.assertTrue(any("external_intent_candidate schema validation failed" in item for item in result["errors"]))
            self.assertTrue(result["error_details"])
            self.assertNotIn("turn_proposal", result)
            self.assertEqual(sqlite_counts(save_dir), before_counts)

    def test_mcp_external_contract_errors_are_canonical_redacted_and_no_write(self) -> None:
        sentinels = {
            "flag": "FLAG_SENTINEL_7f1d9c",
            "reason": "REASON_SENTINEL_7f1d9c",
            "slot": "SLOT_SENTINEL_7f1d9c",
            "user": "USER_SENTINEL_7f1d9c",
            "session": "SESSION_SENTINEL_7f1d9c",
            "provider_body": "PROVIDER_BODY_SENTINEL_7f1d9c",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    mcp_profile="developer",
                )
            )
            entry = adapter.start_or_continue(campaign="campaigns/minimal")
            save_dir = root / str(entry["save"]["path"])
            before_counts = sqlite_counts(save_dir)
            unknown = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"note": sentinels["slot"]},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [sentinels["flag"]],
                "reason": sentinels["reason"],
                "source": sentinels["provider_body"],
            }
            stale = {
                **unknown,
                "contract": {
                    "manifest_schema_version": "1",
                    "manifest_digest": "0" * 64,
                    "safety_vocabulary_version": "1",
                    "safety_vocabulary_digest": "0" * 64,
                },
            }

            operations = {
                "player_turn": lambda candidate: adapter.player_turn(
                    sentinels["user"],
                    external_intent_candidate=candidate,
                    platform="qq",
                    session_key=sentinels["session"],
                ),
                "start_turn": lambda candidate: adapter.start_turn(
                    sentinels["user"],
                    external_intent_candidate=candidate,
                    platform="qq",
                    session_key=sentinels["session"],
                ),
                "preview_from_text": lambda candidate: adapter.preview_from_text(
                    sentinels["user"],
                    external_intent_candidate=candidate,
                    platform="qq",
                    session_key=sentinels["session"],
                ),
                "intent_preflight": lambda candidate: adapter.intent_preflight(
                    sentinels["user"],
                    external_intent_candidate=candidate,
                    platform="qq",
                    session_key=sentinels["session"],
                ),
            }
            expected = {
                "unknown": {
                    "code": "UNKNOWN_INTENT_SAFETY_FLAG",
                    "reason": "unknown_safety_flag",
                    "retriable": False,
                    "action": "regenerate_candidate",
                    "path": "$.safety_flags",
                    "message": "External intent candidate contains unsupported safety flags.",
                    "count": 1,
                },
                "mismatch": {
                    "code": "INTENT_CONTRACT_VERSION_MISMATCH",
                    "reason": "contract_version_mismatch",
                    "retriable": True,
                    "action": "refresh_manifest_and_regenerate_candidate",
                    "path": "$.contract",
                    "message": "External intent contract does not match the current provider.",
                },
            }

            with mock.patch("rpg_engine.ai_intent.router.collect_internal_intent_candidate") as helper:
                for case, candidate in (("unknown", unknown), ("mismatch", stale)):
                    for surface, operation in operations.items():
                        with self.subTest(case=case, surface=surface):
                            result = operation(candidate)
                            self.assertFalse(result["ok"], result)
                            self.assertEqual(result["errors"], [expected[case]["message"]])
                            self.assertEqual(result["error_details"], [expected[case]])
                            wire = json.dumps(result, ensure_ascii=False)
                            for sentinel in sentinels.values():
                                self.assertNotIn(sentinel, wire)
                helper.assert_not_called()

            self.assertEqual(sqlite_counts(save_dir), before_counts)
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())
            audit_text = (root / "logs" / "aigm-mcp-audit.jsonl").read_text(encoding="utf-8")
            for sentinel in sentinels.values():
                self.assertNotIn(sentinel, audit_text)

    def test_mcp_exact_contract_from_live_manifest_reaches_matched_route_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    mcp_profile="developer",
                )
            )
            adapter.start_or_continue(campaign="campaigns/minimal")
            manifest = adapter.intent_manifest()
            candidate = {
                "contract": {
                    "manifest_schema_version": manifest["schema_version"],
                    "manifest_digest": manifest["manifest_digest"],
                    "safety_vocabulary_version": manifest["safety_vocabulary"]["version"],
                    "safety_vocabulary_digest": manifest["safety_vocabulary"]["digest"],
                },
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "live manifest exact match",
            }

            result = adapter.start_turn(
                "休息到早上",
                intent_ai="off",
                external_intent_candidate=candidate,
            )

            self.assertTrue(result["can_proceed"], result)
            intent_trace = result["decision_trace"]["intent_ai"]
            evidence = intent_trace["external_contract"]
            self.assertEqual(evidence["status"], "matched")
            self.assertEqual(evidence["validated_manifest_digest"], manifest["manifest_digest"])
            self.assertEqual(
                evidence["validated_safety_vocabulary_digest"],
                manifest["safety_vocabulary"]["digest"],
            )
            self.assertEqual(intent_trace["route_authority"], "external_primary")

    def test_mcp_adapter_player_entry_and_registry_active_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    mcp_profile="developer",
                )
            )

            entry = adapter.start_or_continue(campaign="campaigns/minimal", user_text="开始游戏")
            saves = adapter.save_list(refresh=True)
            current = adapter.save_current(refresh=True)
            query = adapter.query("scene")
            player_query = adapter.player_query("scene")

            self.assertTrue(entry["ok"], entry)
            self.assertEqual(entry["mode"], "created")
            self.assertIn("Start", entry["onboarding_text"])
            self.assertEqual(len(saves["saves"]), 1)
            self.assertTrue(current["ok"], current)
            self.assertIn("Start", query["text"])
            self.assertIn("Start", player_query["text"])

    def test_player_save_inspect_and_health_redact_hidden_current_location_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            runtime = GMRuntime.from_path(save_dir)
            with connect(runtime.campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.route",
                        "type": "location",
                        "name": "Hidden Grove",
                        "summary": "GM-only location.",
                        "visibility": "hidden",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.remote",
                        "type": "location",
                        "name": "Hidden Shrine",
                        "summary": "GM-only remote location.",
                        "visibility": "hidden",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.obelisk",
                        "type": "location",
                        "name": "Azure Obelisk",
                        "summary": "GM-only proof location.",
                        "visibility": "hidden",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.azure-only",
                        "type": "location",
                        "name": "Azure Hall",
                        "summary": "GM-only azure place without the second token.",
                        "visibility": "hidden",
                    },
                )
                for index in range(6):
                    upsert_entity(
                        conn,
                        {
                            "id": f"loc:public-noise-{index}",
                            "type": "location",
                            "name": f"Public Azure Obelisk Noise {index}",
                            "summary": "Visible public FTS noise for azure obelisk context recall.",
                        },
                    )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:hidden.route",),
                )
                conn.commit()

            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_save="saves/run",
                    mcp_profile=PLAYER_PROFILE,
                )
            )
            inspect = adapter.save_inspect()
            health = adapter.health()
            rendered = json.dumps({"inspect": inspect, "health": health}, ensure_ascii=False, sort_keys=True)

            self.assertNotIn("loc:hidden.route", rendered)
            self.assertNotIn("Hidden Grove", rendered)
            self.assertIn("[hidden]", rendered)

            trusted = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_save="saves/run",
                    mcp_profile="trusted_gm",
                )
            )
            developer = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_save="saves/run",
                    mcp_profile=DEVELOPER_PROFILE,
                )
            )
            trusted_preview = trusted.preview_action("loc:hidden.route", view="gm")
            denied_preview = developer.preview_action("loc:hidden.route", view="gm")

            self.assertFalse(trusted_preview["ok"], trusted_preview)
            self.assertIn("loc:hidden.route", json.dumps(trusted_preview, ensure_ascii=False, sort_keys=True))
            self.assertFalse(denied_preview["ok"], denied_preview)
            self.assertIn("requires trusted_gm", "\n".join(denied_preview["errors"]))
            denied_start = developer.start_turn("维护 Hidden Grove", mode="maintenance")
            trusted_start = trusted.start_turn("维护 Hidden Grove", mode="maintenance")
            denied_query_context = developer.start_turn("查看 Hidden Grove", mode="query", submode="context", view="gm")
            trusted_query_context = trusted.start_turn("查看 Hidden Shrine", mode="query", submode="context", view="gm")
            player_query_context = adapter.start_turn("查看 Hidden Shrine", mode="query", submode="context")
            trusted_runtime_context_query = trusted.query("context", query_text="Hidden Shrine", view="gm")
            player_runtime_context_query = adapter.query("context", query_text="Hidden Shrine")
            trusted_natural_context_query = trusted.query(
                "context",
                query_text="What did the azure obelisk prove?",
                view="gm",
            )
            trusted_request_context_query = trusted.query(
                "context",
                query_text="Please show me the azure obelisk",
                view="gm",
            )
            trusted_can_context_query = trusted.query(
                "context",
                query_text="Can you show me the azure obelisk",
                view="gm",
            )
            player_natural_context_query = adapter.query("context", query_text="What did the azure obelisk prove?")
            player_can_context_query = adapter.query("context", query_text="Can you show me the azure obelisk")

            self.assertFalse(denied_start["ok"], denied_start)
            self.assertIn("mode='maintenance' requires", "\n".join(denied_start["errors"]))
            self.assertIn("loc:hidden.route", json.dumps(trusted_start, ensure_ascii=False, sort_keys=True))
            self.assertFalse(denied_query_context["ok"], denied_query_context)
            self.assertIn("view='gm' requires", "\n".join(denied_query_context["errors"]))
            self.assertIn("loc:hidden.route", json.dumps(trusted_query_context, ensure_ascii=False, sort_keys=True))
            self.assertIn(
                "loc:hidden.remote",
                {item["id"] for item in trusted_query_context["context"]["loaded_items"]},
            )
            self.assertIn("loc:hidden.remote", trusted_query_context["context"]["sections"]["relevant_entities"])
            self.assertNotIn("loc:hidden.remote", json.dumps(player_query_context, ensure_ascii=False, sort_keys=True))
            self.assertEqual(trusted_runtime_context_query["context"]["request"]["mode"], "query")
            self.assertEqual(trusted_runtime_context_query["context"]["request"]["submode"], "context")
            self.assertEqual(trusted_runtime_context_query["context"]["request"]["visibility_view"], "gm")
            self.assertIn(
                "loc:hidden.remote",
                {item["id"] for item in trusted_runtime_context_query["context"]["loaded_items"]},
            )
            self.assertNotIn(
                "loc:hidden.remote",
                json.dumps(player_runtime_context_query, ensure_ascii=False, sort_keys=True),
            )
            self.assertIn(
                "loc:hidden.obelisk",
                {item["id"] for item in trusted_natural_context_query["context"]["loaded_items"]},
            )
            self.assertIn(
                "loc:hidden.obelisk",
                {item["id"] for item in trusted_request_context_query["context"]["loaded_items"]},
            )
            self.assertIn(
                "loc:hidden.obelisk",
                {item["id"] for item in trusted_can_context_query["context"]["loaded_items"]},
            )
            self.assertNotIn(
                "loc:hidden.azure-only",
                {item["id"] for item in trusted_natural_context_query["context"]["loaded_items"]},
            )
            self.assertNotIn(
                "loc:hidden.obelisk",
                json.dumps(player_natural_context_query, ensure_ascii=False, sort_keys=True),
            )
            self.assertNotIn(
                "loc:hidden.obelisk",
                json.dumps(player_can_context_query, ensure_ascii=False, sort_keys=True),
            )

    def test_registry_active_runtime_resolution_refreshes_and_blocks_unhealthy_active_save(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    mcp_profile=DEVELOPER_PROFILE,
                )
            )
            created = adapter.save_create(campaign="campaigns/minimal", label="Run")
            save_path = root / created["save"]["path"]
            runtime = GMRuntime.from_path(save_path)
            with connect(runtime.campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.route",
                        "type": "location",
                        "name": "Hidden Grove",
                        "summary": "GM-only location.",
                        "visibility": "hidden",
                    },
                )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:hidden.route",),
                )
                conn.commit()

            result = adapter.query("scene")
            rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)

            self.assertFalse(result["ok"], result)
            self.assertIn("active save is not healthy", "\n".join(result["errors"]))
            self.assertNotIn("loc:hidden.route", rendered)

    def test_mcp_player_workflow_hides_delta_and_confirms_pending_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                )
            )

            entry = adapter.start_or_continue(campaign="campaigns/minimal")
            acted = adapter.player_turn("休息到早上")
            rejected = adapter.player_confirm()
            confirmed = adapter.player_confirm(session_id=acted["session_id"])
            replayed = adapter.player_confirm(session_id=acted["session_id"])
            current = adapter.save_current(refresh=True)

            self.assertTrue(entry["ok"], entry)
            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertNotIn("delta_draft", acted)
            self.assertNotIn("turn_proposal", acted)
            self.assertFalse(rejected["ok"], rejected)
            self.assertIn("session_id", rejected["errors"][0])
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertEqual(confirmed["write_status"], "committed")
            self.assertFalse(confirmed["idempotent_replay"])
            self.assertTrue(replayed["ok"], replayed)
            self.assertFalse(replayed["saved"], replayed)
            self.assertEqual(replayed["write_status"], "already_confirmed")
            self.assertTrue(replayed["idempotent_replay"])
            self.assertNotIn("delta_draft", confirmed)
            self.assertNotIn("turn_proposal", confirmed)
            self.assertEqual(current["save"]["current_turn_id"], "turn:000001")

    def test_mcp_player_turn_hides_delta_and_confirms_pending_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                )
            )

            entry = adapter.start_or_continue(campaign="campaigns/minimal")
            turn = adapter.player_turn("休息到早上")
            confirmed = adapter.player_confirm(session_id=turn["session_id"])
            current = adapter.save_current(refresh=True)

            self.assertTrue(entry["ok"], entry)
            self.assertTrue(turn["ok"], turn)
            self.assertTrue(turn["ready_to_confirm"], turn)
            self.assertNotIn("delta_draft", turn)
            self.assertNotIn("turn_proposal", turn)
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertEqual(current["save"]["current_turn_id"], "turn:000001")

    def test_mcp_developer_player_act_clears_stale_pending_action_when_new_action_needs_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    mcp_profile="developer",
                )
            )

            adapter.start_or_continue(campaign="campaigns/minimal")
            ready = adapter.player_act("休息到早上")
            needs_clarification = adapter.player_act("不要去 Old Bridge。")
            confirmed = adapter.player_confirm(session_id=ready["session_id"])

            self.assertTrue(ready["ready_to_confirm"], ready)
            self.assertFalse(needs_clarification["ready_to_confirm"], needs_clarification)
            self.assertFalse(confirmed["ok"], confirmed)
            self.assertIn("no pending player action", confirmed["errors"][0])

    def test_mcp_developer_start_and_preview_ignore_empty_intent_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    mcp_profile="developer",
                )
            )

            adapter.start_or_continue(campaign="campaigns/minimal")
            started = adapter.start_turn("休息到早上", intent_ai="", preflight_pending_wait_ms=0)
            preview = adapter.preview_from_text(
                "休息到早上",
                intent_ai="",
                message_id="qq:passive",
                platform="qq",
                session_key="qq:user:1",
                preflight_pending_wait_ms=0,
            )

            self.assertNotIn("error", started, started)
            self.assertNotIn("error", preview, preview)
            self.assertTrue(started["can_proceed"], started)
            self.assertTrue(preview["ok"], preview)

    def test_mcp_preview_empty_text_keeps_clarification_before_intent_config_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )

            result = adapter.preview_from_text("   ", intent_backend="not-a-backend")

            self.assertFalse(result["ok"], result)
            self.assertEqual(result["status"], "clarify")
            self.assertEqual(result["missing_required"], ["user_text"])
            self.assertEqual(result["errors"], [])

    def test_mcp_start_turn_bundling_preserves_request_surface_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            old_path = install_fake_hermes(
                root,
                '{"kind":"single","mode":"action","action":"rest","slots":{"until":"morning"},"plan":[],"confidence":"high","missing_slots":[],"needs_confirmation":[],"safety_flags":[],"reason":"MCP start_turn agrees.","agreement_with_external":"agree","disagreements":[],"external_candidate_quality":"usable"}',
            )
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 判断这是休息行动。",
            }
            try:
                result = adapter.start_turn(
                    "休息到早上",
                    intent_ai="CONSENSUS",
                    intent_backend="hermes",
                    intent_provider="deepseek",
                    intent_model="deepseek-v4-flash",
                    intent_timeout=1,
                    intent_base_url="https://ai.example.test/v1",
                    intent_api_key_env="AIGM_TEST_KEY",
                    intent_fallback_backend="hermes",
                    external_intent_candidate=external,
                    message_id="msg:mcp-start-bundle",
                    platform="qq",
                    session_key="room:mcp-start-bundle",
                    preflight_pending_wait_ms=-5,
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(result["can_proceed"], result)
            request_ai = result["context"]["request"]["intent_ai"]
            trace = result["decision_trace"]["intent_ai"]
            self.assertEqual(request_ai["mode"], "CONSENSUS")
            self.assertEqual(request_ai["backend"], "hermes")
            self.assertEqual(request_ai["provider"], "deepseek")
            self.assertEqual(request_ai["model"], "deepseek-v4-flash")
            self.assertEqual(request_ai["timeout"], 3)
            self.assertEqual(request_ai["base_url"], "https://ai.example.test/v1")
            self.assertEqual(request_ai["api_key_env"], "AIGM_TEST_KEY")
            self.assertEqual(request_ai["fallback_backend"], "hermes")
            self.assertEqual(request_ai["preflight_pending_wait_ms"], 0)
            self.assertEqual(trace["mode"], "consensus")
            self.assertEqual(trace["backend"], "hermes_z")
            self.assertEqual(trace["fallback_backend"], "hermes_z")

    def test_mcp_developer_preview_from_text_can_use_intent_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            old_path = install_fake_hermes(
                root,
                '{"kind":"single","mode":"action","action":"rest","slots":{"until":"morning"},"plan":[],"confidence":"high","missing_slots":[],"needs_confirmation":[],"safety_flags":[],"reason":"玩家要休息到早上","agreement_with_external":"agree","disagreements":[],"external_candidate_quality":"usable"}',
            )
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 判断这是休息行动。",
            }
            try:
                result = adapter.preview_from_text(
                    "休息到早上",
                    intent_ai="consensus",
                    intent_backend="hermes_z",
                    external_intent_candidate=external,
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["action"], "rest")
            self.assertEqual(result["interpretation"]["intent"]["source"], "ai_consensus")
            self.assertEqual(
                result["interpretation"]["intent"]["decision_trace"]["intent_ai"]["internal_helper"]["status"],
                "ok",
            )

    def test_mcp_intent_direct_options_reach_internal_ai_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
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
                    "reason": "内部 AI 认可休息到早上的行动。",
                    "agreement_with_external": "agree",
                    "disagreements": [],
                    "external_candidate_quality": "usable",
                },
                ensure_ascii=False,
            )
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                    intent_ai="consensus",
                    intent_backend="direct",
                    intent_provider="deepseek",
                    intent_model="deepseek-v4-flash",
                    intent_timeout=7,
                    intent_base_url="https://unit.test/chat",
                    intent_api_key_env="AIGM_TEST_KEY",
                    intent_fallback_backend="off",
                )
            )
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 判断这是休息行动。",
            }
            try:
                result = adapter.preview_from_text("休息到早上", external_intent_candidate=external)
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            self.assertTrue(result["ok"], result)
            trace = result["interpretation"]["intent"]["decision_trace"]["intent_ai"]
            self.assertEqual(trace["backend"], "direct")
            self.assertEqual(trace["provider"], "deepseek")
            self.assertEqual(trace["model"], "deepseek-v4-flash")
            self.assertEqual(trace["timeout"], 7)
            self.assertEqual(trace["base_url"], "https://unit.test/chat")
            self.assertEqual(trace["api_key_env"], "AIGM_TEST_KEY")
            self.assertEqual(trace["fallback_backend"], "off")
            self.assertEqual(trace["internal_helper"]["backend"], "direct")
            self.assertEqual(trace["internal_helper"]["status"], "ok")

    def test_mcp_intent_preflight_can_be_consumed_by_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                    intent_ai="consensus",
                    intent_backend="direct",
                )
            )
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 判断这是休息行动。",
            }
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
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
                    "reason": "preflight agrees.",
                    "agreement_with_external": "agree",
                    "disagreements": [],
                    "external_candidate_quality": "usable",
                },
                ensure_ascii=False,
            )
            try:
                preflight = adapter.intent_preflight(
                    "休息到早上",
                    external_intent_candidate=external,
                    message_id="qq:1",
                )
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            old_missing_key = os.environ.pop("AIGM_TEST_MISSING_KEY", None)
            try:
                preview = adapter.preview_from_text(
                    "休息到早上",
                    external_intent_candidate=external,
                    intent_api_key_env="AIGM_TEST_MISSING_KEY",
                    preflight_id=preflight["preflight_id"],
                    message_id="qq:1",
                    source_user_text_hash=preflight["source_user_text_hash"],
                )
            finally:
                if old_missing_key is not None:
                    os.environ["AIGM_TEST_MISSING_KEY"] = old_missing_key

            self.assertTrue(preflight["ok"], preflight)
            self.assertTrue(preview["ok"], preview)
            trace = preview["interpretation"]["intent"]["decision_trace"]["intent_ai"]
            self.assertEqual(trace["preflight"]["status"], "hit")
            self.assertEqual(trace["internal_helper"]["backend"], "preflight_cache")

    def test_mcp_message_only_preflight_can_be_consumed_without_preflight_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                    intent_ai="consensus",
                    intent_backend="direct",
                )
            )
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 后到，但同意这是休息行动。",
            }
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
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
                    "reason": "message-only preflight agrees.",
                    "agreement_with_external": "no_external",
                    "disagreements": [],
                    "external_candidate_quality": "no_external",
                },
                ensure_ascii=False,
            )
            try:
                preflight = adapter.intent_preflight(
                    "休息到早上",
                    message_id="qq:mcp-message-only",
                    platform="qq",
                    session_key="qq:user:1",
                    preflight_identity_profile="message_only",
                )
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            old_missing_key = os.environ.pop("AIGM_TEST_MISSING_KEY", None)
            try:
                preview = adapter.preview_from_text(
                    "休息到早上",
                    external_intent_candidate=external,
                    intent_api_key_env="AIGM_TEST_MISSING_KEY",
                    message_id="qq:mcp-message-only",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=preflight["source_user_text_hash"],
                    preflight_pending_wait_ms=10,
                )
            finally:
                if old_missing_key is not None:
                    os.environ["AIGM_TEST_MISSING_KEY"] = old_missing_key

            self.assertTrue(preflight["ok"], preflight)
            self.assertEqual(preflight["identity_profile"], "message_only")
            self.assertTrue(preview["ok"], preview)
            trace = preview["interpretation"]["intent"]["decision_trace"]["intent_ai"]
            self.assertEqual(trace["preflight"]["status"], "hit")
            self.assertEqual(trace["preflight"]["record"]["identity"]["identity_profile"], "message_only")
            self.assertEqual(trace["internal_helper"]["backend"], "preflight_cache")

    def test_mcp_player_act_can_consume_passive_message_only_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    registry_active=True,
                    intent_ai="consensus",
                    intent_backend="direct",
                    intent_provider="deepseek",
                    intent_model="deepseek-v4-flash",
                    intent_api_key_env="AIGM_TEST_MISSING_KEY",
                    intent_fallback_backend="off",
                    mcp_profile="developer",
                )
            )
            entry = adapter.start_or_continue(campaign="campaigns/minimal")
            runtime = GMRuntime.from_path(root / entry["save"]["path"])
            old_fake = os.environ.get("AIGM_AI_FAKE_RESPONSE")
            os.environ["AIGM_AI_FAKE_RESPONSE"] = json.dumps(
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
                    "reason": "message-only preflight agrees for player_act.",
                    "agreement_with_external": "no_external",
                    "disagreements": [],
                    "external_candidate_quality": "no_external",
                },
                ensure_ascii=False,
            )
            try:
                preflight = runtime.preflight_intent(
                    "休息到早上",
                    intent_backend="direct",
                    intent_provider="deepseek",
                    intent_model="deepseek-v4-flash",
                    intent_api_key_env="AIGM_TEST_MISSING_KEY",
                    intent_fallback_backend="off",
                    message_id="qq:player-act-message-only",
                    platform="qq",
                    session_key="qq:user:1",
                    preflight_identity_profile="message_only",
                ).to_dict()
            finally:
                if old_fake is None:
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                else:
                    os.environ["AIGM_AI_FAKE_RESPONSE"] = old_fake

            old_missing_key = os.environ.pop("AIGM_TEST_MISSING_KEY", None)
            try:
                acted = adapter.player_act(
                    "休息到早上",
                    message_id="qq:player-act-message-only",
                    platform="qq",
                    session_key="qq:user:1",
                    source_user_text_hash=preflight["source_user_text_hash"],
                    preflight_pending_wait_ms=10,
                )
            finally:
                if old_missing_key is not None:
                    os.environ["AIGM_TEST_MISSING_KEY"] = old_missing_key

            self.assertTrue(preflight["ok"], preflight)
            self.assertEqual(preflight["identity_profile"], "message_only")
            self.assertTrue(acted["ok"], acted)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertEqual(acted["status"], "ready")
            self.assertEqual(acted["action"], "rest")
            self.assertIn("session_id", acted)
            self.assertNotIn("missing API key", json.dumps(acted, ensure_ascii=False))
            self.assertNotIn("delta_draft", acted)
            self.assertNotIn("turn_proposal", acted)

    def test_mcp_low_level_clarification_requires_fresh_repreview_before_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            old_path = install_fake_hermes(
                root,
                '{"kind":"single","mode":"action","action":"routine","slots":{"task":"守夜到天亮"},"plan":[],"confidence":"high","missing_slots":[],"needs_confirmation":[],"safety_flags":[],"reason":"内部复核认为这是 routine","agreement_with_external":"disagree","disagreements":["action mismatch"],"external_candidate_quality":"wrong_action"}',
            )
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )
            external = {
                "kind": "single",
                "mode": "action",
                "action": "rest",
                "slots": {"until": "morning"},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "外部 AI 判断这是休息行动。",
            }
            try:
                start = adapter.start_turn(
                    "守夜到天亮",
                    intent_ai="consensus",
                    intent_backend="hermes_z",
                    external_intent_candidate=external,
                )
                stale_preview = adapter.preview_from_text(
                    "守夜到天亮",
                    intent_ai="consensus",
                    intent_backend="hermes_z",
                    external_intent_candidate=external,
                )
                low_level_preview = adapter.preview_action("rest", options={"until": "morning"})
                preflight_blocked = adapter.intent_preflight("休息到早上", intent_backend="off")
                fresh_preview = adapter.preview_from_text(
                    "我是想休息到天亮",
                    intent_ai="consensus",
                    intent_backend="hermes_z",
                    external_intent_candidate=external,
                )
            finally:
                os.environ["PATH"] = old_path

            self.assertFalse(start["can_proceed"], start)
            self.assertIn("clarification_id", start["clarification"])
            self.assertFalse(stale_preview["ok"], stale_preview)
            self.assertIn("pending clarification", stale_preview["errors"][0])
            self.assertFalse(low_level_preview["ok"], low_level_preview)
            self.assertIn("cannot run while clarification", low_level_preview["errors"][0])
            self.assertFalse(preflight_blocked["ok"], preflight_blocked)
            self.assertIn("cannot run while clarification", preflight_blocked["errors"][0])
            self.assertNotIn("must answer pending clarification", " ".join(fresh_preview.get("errors", [])))

    def test_mcp_commit_runs_default_state_audit_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )
            preview = adapter.preview_action("rest", options={"until": "morning", "user_text": "rest until morning"})
            delta = dict(preview["delta_draft"])
            delta["summary"] = "获得小鱼并入库。"
            delta["upsert_entities"] = []
            delta["events"] = [
                *delta.get("events", []),
                {
                    "type": "routine",
                    "title": "入库",
                    "summary": "获得小鱼并入库。",
                    "payload": {"output_quantity_required": True},
                    "source": "test",
                },
            ]
            proposal = dict(preview["turn_proposal"])
            proposal["proposal_id"] = "proposal:mcp-state-audit-default"
            proposal["delta"] = delta
            result = adapter.commit_turn(delta, turn_proposal=proposal)

            self.assertFalse(result.get("ok", False))
            self.assertIn("State audit blocked turn delta", "\n".join(result["errors"]))

    def test_mcp_adapter_writes_structured_audit_log_for_success_and_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )

            ok = adapter.query("scene")
            failed = adapter.campaign_validate("../escape")

            self.assertIn("Start", ok["text"])
            self.assertFalse(failed["ok"])
            audit_path = root / "logs" / "aigm-mcp-audit.jsonl"
            records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["tool"] for record in records], ["query", "campaign_validate"])
            self.assertEqual(records[0]["status"], "ok")
            self.assertEqual(records[1]["status"], "error")
            self.assertEqual(records[0]["surface_category"], "trusted low-level")
            self.assertEqual(records[1]["surface_category"], "player-safe")
            self.assertEqual(records[0]["identity"], {"profile": "developer", "tool": "query"})
            self.assertEqual(records[0]["request"]["kind"], "scene")
            self.assertIn("text_preview", records[0]["result"])
            self.assertNotIn("text", records[0]["result"])
            self.assertIn("must not contain", records[1]["result"]["errors"][0])

    def test_mcp_audit_scrubs_sensitive_free_text_errors_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    mcp_profile="developer",
                )
            )

            adapter.write_audit_record(
                "player_turn",
                {
                    "platform": "qq",
                    "session_key": "qq:raw-session",
                    "actor_id": "actor:raw",
                    "message_id": "qq:msg:1",
                },
                {
                    "ok": False,
                    "errors": ["failed qq:raw-session for actor:raw"],
                    "warnings": ["Private-Reasoning: do not audit"],
                    "text": "HiddenFacts: do not audit either",
                },
                duration_ms=1,
            )

            audit_path = root / "logs" / "aigm-mcp-audit.jsonl"
            records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            audit_text = json.dumps(records, ensure_ascii=False)

            self.assertEqual(records[0]["result"]["errors"], ["failed <redacted> for <redacted>"])
            self.assertEqual(records[0]["result"]["warnings"], ["<redacted sensitive audit text>"])
            self.assertEqual(records[0]["result"]["text_preview"], "<redacted sensitive audit text>")
            self.assertNotIn("qq:raw-session", audit_text)
            self.assertNotIn("actor:raw", audit_text)
            self.assertNotIn("Private-Reasoning", audit_text)
            self.assertNotIn("HiddenFacts", audit_text)
            self.assertNotIn("do not audit", audit_text)

    def test_mcp_audit_write_failure_does_not_change_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            bad_audit_path = root / "logs"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            bad_audit_path.mkdir()
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                    audit_log=bad_audit_path,
                )
            )

            result = adapter.query("scene")

            self.assertIn("Start", result["text"])
            self.assertNotIn("errors", result)

    def test_mcp_player_profile_rejects_all_low_level_adapter_methods_without_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            before_counts = sqlite_counts(save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                )
            )

            results = {
                "player_query": adapter.player_query("scene"),
                "player_act": adapter.player_act("休息到早上"),
                "start_turn": adapter.start_turn("查看周围"),
                "intent_preflight": adapter.intent_preflight(
                    "休息到早上",
                    platform="qq",
                    session_key="qq:raw-secret",
                ),
                "query": adapter.query("scene"),
                "preview_from_text": adapter.preview_from_text("休息到早上"),
                "preview_action": adapter.preview_action("rest", options={"until": "morning"}),
                "validate_delta": adapter.validate_delta({"summary": "x"}),
                "commit_turn": adapter.commit_turn(
                    {"summary": "x"},
                    turn_proposal={"proposal_id": "proposal:test", "delta": {"summary": "x"}},
                    state_audit=False,
                ),
            }

            for tool, result in results.items():
                self.assertFalse(result.get("ok", False), result)
                joined = "\n".join(result["errors"])
                self.assertIn(tool, joined)
                self.assertIn("profile/surface category mismatch", joined)
                self.assertIn("profile=player", joined)
                detail = result["error_details"][0]
                self.assertEqual(detail["code"], "MCP_PROFILE_MISMATCH")
                self.assertEqual(detail["tool"], tool)
                self.assertEqual(detail["profile"], "player")
                self.assertEqual(detail["surface_category"], "trusted low-level")
                self.assertIn("developer", detail["required_profiles"])
            self.assertEqual(sqlite_counts(save_dir), before_counts)
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())
            self.assertFalse((root / ".aigm" / "pending-player-clarification.json").exists())
            self.assertEqual(adapter.pending_clarifications, {})

    def test_mcp_developer_profile_keeps_hidden_read_gate_separate_from_low_level_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                    mcp_profile="developer",
                )
            )

            player_view = adapter.query("scene")
            hidden_view = adapter.query("scene", view="maintenance")

            self.assertIn("Start", player_view["text"])
            self.assertFalse(hidden_view["ok"], hidden_view)
            self.assertIn("requires trusted_gm", "\n".join(hidden_view["errors"]))

    def test_mcp_player_profile_permission_audit_is_sanitized_and_summarized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(
                MCPAdapterConfig.from_values(
                    root,
                    default_campaign="campaigns/minimal",
                    default_save="saves/run",
                )
            )

            preflight = adapter.intent_preflight(
                "休息到早上",
                platform="qq",
                session_key="qq:raw-secret",
                external_intent_candidate={
                    "Private-Reasoning": "do not audit this",
                    "plan": ["raw external plan should not audit"],
                },
            )
            commit = adapter.commit_turn(
                {"summary": "raw delta internals", "Hidden-Facts": ["secret"]},
                turn_proposal={
                    "proposal_id": "proposal:raw",
                    "delta": {"summary": "raw proposal internals"},
                    "private-reasoning": "do not audit proposal",
                },
            )

            self.assertFalse(preflight["ok"], preflight)
            self.assertFalse(commit["ok"], commit)
            audit_path = root / "logs" / "aigm-mcp-audit.jsonl"
            records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
            audit_text = json.dumps(records, ensure_ascii=False)
            self.assertEqual([record["tool"] for record in records], ["intent_preflight", "commit_turn"])
            self.assertEqual(records[0]["surface_category"], "trusted low-level")
            self.assertEqual(records[1]["surface_category"], "trusted low-level")
            self.assertEqual(records[0]["identity"]["profile"], "player")
            self.assertEqual(records[0]["identity"]["tool"], "intent_preflight")
            self.assertEqual(records[0]["identity"]["platform"], "qq")
            self.assertTrue(records[0]["identity"]["session_key_hash"].startswith("sha256:"))
            self.assertNotIn("qq:raw-secret", audit_text)
            self.assertNotIn("raw external plan", audit_text)
            self.assertNotIn("raw delta internals", audit_text)
            self.assertNotIn("raw proposal internals", audit_text)
            self.assertNotIn("do not audit", audit_text)
            self.assertNotIn("Private-Reasoning", audit_text)
            self.assertNotIn("private-reasoning", audit_text)
            self.assertNotIn("private_reasoning", audit_text)
            self.assertNotIn("Hidden-Facts", audit_text)
            self.assertNotIn("hidden_facts", audit_text)
            self.assertTrue(records[0]["request"]["session_key"].startswith("sha256:"))
            self.assertTrue(records[0]["request"]["external_intent_candidate"]["redacted"])
            self.assertEqual(records[0]["request"]["external_intent_candidate"]["type"], "object")
            self.assertEqual(records[0]["request"]["external_intent_candidate"]["key_count"], 2)
            self.assertEqual(records[1]["request"]["delta"]["key_count"], 2)
            self.assertEqual(records[1]["request"]["turn_proposal"]["key_count"], 3)
            self.assertEqual(records[0]["status"], "error")
            self.assertEqual(records[1]["status"], "error")
            self.assertEqual(records[0]["result"]["ok"], False)
            self.assertIn("errors", records[0]["result"])
            self.assertNotIn("error_details", records[0]["result"])

    def test_mcp_adapter_rejects_absolute_and_escaping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = AIGMMCPAdapter(MCPAdapterConfig.from_values(tmp, default_campaign="campaign"))

            absolute = adapter.campaign_validate("/tmp/other")
            escaping = adapter.campaign_validate("../other")
            backslash = adapter.campaign_validate("bad\\path")
            missing_default = adapter.save_inspect()

            self.assertFalse(absolute["ok"])
            self.assertIn("must be relative", "\n".join(absolute["errors"]))
            self.assertFalse(escaping["ok"])
            self.assertIn("must not contain", "\n".join(escaping["errors"]))
            self.assertFalse(backslash["ok"])
            self.assertIn("must not contain backslashes", "\n".join(backslash["errors"]))
            self.assertFalse(missing_default["ok"])
            self.assertIn("save is required", "\n".join(missing_default["errors"]))

    def test_mcp_start_or_continue_rejects_bad_paths_with_active_save_without_registry_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            save_dir = root / "saves" / "run"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            init_v1_save(campaign_dir, save_dir)
            adapter = AIGMMCPAdapter(MCPAdapterConfig.from_values(root, default_campaign="campaigns/minimal"))
            adapter.save_create(campaign="campaigns/minimal", label="Run", starter_save="saves/run")
            registry_path = root / ".aigm" / "save-registry.json"
            before_registry = registry_path.read_text(encoding="utf-8")

            escaping = adapter.start_or_continue(campaign="../outside")
            backslash = adapter.start_or_continue(campaign="campaigns\\minimal")

            self.assertFalse(escaping["ok"])
            self.assertIn("must not contain", "\n".join(escaping["errors"]))
            self.assertFalse(backslash["ok"])
            self.assertIn("must not contain backslashes", "\n".join(backslash["errors"]))
            self.assertEqual(registry_path.read_text(encoding="utf-8"), before_registry)
            self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())

    def test_mcp_client_config_uses_relative_defaults_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = build_client_config(
                tmp,
                default_campaign="campaigns/minimal",
                default_save="saves/run",
                default_starter_save="starters/minimal",
                registry_active=True,
                command="python3",
            )
            text = json.dumps(data, sort_keys=True)

            self.assertEqual(data["mcpServers"]["aigm-kernel"]["command"], "python3")
            self.assertNotIn("--mcp-profile", data["mcpServers"]["aigm-kernel"]["args"])
            self.assertIn("--default-campaign", data["mcpServers"]["aigm-kernel"]["args"])
            self.assertIn("saves/run", text)
            self.assertIn("--default-starter-save", data["mcpServers"]["aigm-kernel"]["args"])
            self.assertIn("--registry-active", data["mcpServers"]["aigm-kernel"]["args"])

            developer = build_client_config(tmp, mcp_profile=DEVELOPER_PROFILE)
            self.assertIn("--mcp-profile", developer["mcpServers"]["aigm-kernel"]["args"])
            self.assertIn(DEVELOPER_PROFILE, developer["mcpServers"]["aigm-kernel"]["args"])


if __name__ == "__main__":
    unittest.main()
