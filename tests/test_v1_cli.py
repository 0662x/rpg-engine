from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import zipfile
from argparse import Namespace
from pathlib import Path

import yaml

from rpg_engine.cli_v1 import (
    handle_mcp,
    handle_platform,
    handle_player,
    intent_option_kwargs_from_args,
    intent_preflight_kwargs_from_args,
    intent_preview_kwargs_from_args,
    preflight_consume_kwargs_from_args,
)
import rpg_engine.cli_v1 as cli_v1
import rpg_engine.mcp_adapter as mcp_adapter
from tests.helpers import tree_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
EXAMPLE = ENGINE_ROOT / "rpg_engine" / "resources" / "examples" / "v1_minimal_adventure"


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def load_stdout_json(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def current_turn(save_dir: Path) -> str:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    try:
        row = conn.execute("select value from meta where key = 'current_turn_id'").fetchone()
    finally:
        conn.close()
    return "" if row is None else str(row[0])


def delta_from_markdown(markdown: str) -> dict[str, object]:
    parts = markdown.split("```json", 1)
    if len(parts) != 2:
        raise AssertionError("markdown has no json delta block")
    return json.loads(parts[1].split("```", 1)[0])


class V1CliTests(unittest.TestCase):
    def test_platform_cli_explicit_timeout_applies_to_player_and_prewarm_paths(self) -> None:
        from rpg_engine.platform_prewarm import PlatformPrewarmConfig

        args = Namespace(
            root="/tmp/platform-root",
            enable_prewarm=True,
            prewarm_queue_size=None,
            prewarm_workers=None,
            intent_ai="consensus",
            intent_backend=None,
            intent_provider=None,
            intent_model=None,
            intent_timeout=23,
            intent_base_url=None,
            intent_api_key_env=None,
            intent_fallback_backend=None,
            active_ttl_seconds=1800,
            preflight_pending_wait_ms=200,
        )

        with patch.object(PlatformPrewarmConfig, "from_env", return_value=PlatformPrewarmConfig()):
            sidecar = cli_v1.build_platform_sidecar(args)

        self.assertEqual(sidecar.config.prewarm.intent_timeout, 23)
        self.assertEqual(sidecar.config.player_intent_timeout, 23)

        args.intent_timeout = 0
        with patch.object(PlatformPrewarmConfig, "from_env", return_value=PlatformPrewarmConfig()):
            zero_sidecar = cli_v1.build_platform_sidecar(args)

        self.assertEqual(zero_sidecar.config.prewarm.intent_timeout, 0)
        self.assertEqual(zero_sidecar.config.player_intent_timeout, 0)

    def test_cli_help_separates_player_safe_and_trusted_low_level_groups(self) -> None:
        help_text = run_cli("--help").stdout

        self.assertRegex(help_text, r"\bplay\s+developer/trusted low-level runtime commands")
        self.assertRegex(help_text, r"\bplayer\s+player-safe save registry and turn commands")
        self.assertRegex(help_text, r"\bplatform\s+platform sidecar prewarm and player entry commands")
        self.assertRegex(help_text, r"\bmcp\s+MCP adapter host/profile commands")

    def test_play_help_labels_subcommands_as_trusted_low_level(self) -> None:
        help_text = run_cli("play", "--help").stdout

        self.assertRegex(help_text, r"\bpreflight\s+developer/trusted low-level advisory intent preflight")
        self.assertRegex(help_text, r"\bstart-turn\s+developer/trusted low-level turn classification")
        self.assertRegex(help_text, r"\bquery\s+developer/trusted low-level read-only runtime query")
        self.assertRegex(help_text, r"\bact\s+developer/trusted low-level natural-language action\s+preview")
        self.assertRegex(help_text, r"\bpreview\s+developer/trusted low-level action preview without\s+saving")
        self.assertRegex(help_text, r"\bvalidate-delta\s+developer/trusted low-level delta validation through\s+GMRuntime")
        self.assertRegex(help_text, r"\bcommit\s+developer/trusted low-level commit of approved\s+TurnProposal delta")
        self.assertRegex(help_text, r"\bhealth\s+developer/trusted low-level read-only runtime health\s+check")
        self.assertRegex(help_text, r"\bux-metrics\s+developer/trusted low-level read-only runtime UX\s+metrics")

    def test_player_handler_routes_turn_act_cancel_and_confirm_through_save_manager(self) -> None:
        calls: list[tuple[str, object]] = []

        class RecordingSaveManager:
            def __init__(self, root: str) -> None:
                calls.append(("__init__", root))

            def player_turn(self, **kwargs: object) -> dict[str, object]:
                calls.append(("player_turn", kwargs))
                return {"ok": True, "kind": "turn"}

            def player_act(self, **kwargs: object) -> dict[str, object]:
                calls.append(("player_act", kwargs))
                return {"ok": True, "kind": "act"}

            def player_confirm(self, **kwargs: object) -> dict[str, object]:
                calls.append(("player_confirm", kwargs))
                return {"ok": True, "kind": "confirm"}

            def player_cancel(self, expected_pending_id: str, **kwargs: object) -> dict[str, object]:
                calls.append(("player_cancel", {"expected_pending_id": expected_pending_id, **kwargs}))
                return {"ok": True, "kind": "cancel", "status": "canceled"}

        def player_args(player_type: str, **overrides: object) -> Namespace:
            values = {
                "root": "/tmp/player-root",
                "player_type": player_type,
                "format": "json",
                "user_text": "look around",
                "user_text_file": None,
                "user_text_stdin": False,
                "intent_ai": "off",
                "intent_backend": "direct",
                "intent_provider": "fake",
                "intent_model": "fake-model",
                "intent_timeout": 1,
                "intent_base_url": "",
                "intent_api_key_env": "",
                "intent_fallback_backend": "off",
                "external_intent_candidate": None,
                "preflight_id": "",
                "message_id": "",
                "platform": "",
                "session_key": "",
                "actor_id": "",
                "expected_pending_id": "",
                "clarification_id": "",
                "source_user_text_hash": "",
                "preflight_pending_wait_ms": 0,
                "session_id": "pending:1",
                "save_path": "",
            }
            values.update(overrides)
            return Namespace(**values)

        with (
            patch.object(cli_v1, "SaveManager", RecordingSaveManager),
            patch.object(cli_v1.GMRuntime, "from_path", side_effect=AssertionError("player CLI must not use GMRuntime")),
        ):
            self.assertEqual(
                handle_player(
                    player_args(
                        "turn",
                        external_intent_candidate=json.dumps(
                            {"kind": "single", "mode": "action", "action": "rest", "slots": {"until": "morning"}}
                        ),
                    )
                ),
                0,
            )
            self.assertEqual(handle_player(player_args("act")), 0)
            self.assertEqual(handle_player(player_args("cancel", expected_pending_id="pending:1")), 0)
            self.assertEqual(handle_player(player_args("confirm")), 0)

        self.assertEqual(
            calls,
            [
                ("__init__", "/tmp/player-root"),
                (
                    "player_turn",
                    {
                        "user_text": "look around",
                        "intent_ai": "off",
                        "intent_backend": "direct",
                        "intent_provider": "fake",
                        "intent_model": "fake-model",
                        "intent_timeout": 1,
                        "intent_base_url": "",
                        "intent_api_key_env": "",
                        "intent_fallback_backend": "off",
                        "external_intent_candidate": {
                            "kind": "single",
                            "mode": "action",
                            "action": "rest",
                            "slots": {"until": "morning"},
                        },
                        "preflight_id": "",
                        "message_id": "",
                        "platform": "",
                        "session_key": "",
                        "actor_id": "",
                        "expected_pending_id": "",
                        "clarification_id": "",
                        "source_user_text_hash": "",
                        "preflight_pending_wait_ms": 0,
                    },
                ),
                ("__init__", "/tmp/player-root"),
                (
                    "player_act",
                    {
                        "user_text": "look around",
                        "intent_ai": "off",
                        "intent_backend": "direct",
                        "intent_provider": "fake",
                        "intent_model": "fake-model",
                        "intent_timeout": 1,
                        "intent_base_url": "",
                        "intent_api_key_env": "",
                        "intent_fallback_backend": "off",
                        "preflight_id": "",
                        "message_id": "",
                        "platform": "",
                        "session_key": "",
                        "actor_id": "",
                        "expected_pending_id": "",
                        "clarification_id": "",
                        "source_user_text_hash": "",
                        "preflight_pending_wait_ms": 0,
                    },
                ),
                ("__init__", "/tmp/player-root"),
                (
                    "player_cancel",
                    {
                        "expected_pending_id": "pending:1",
                        "save_path": "",
                        "platform": "",
                        "session_key": "",
                        "actor_id": "",
                    },
                ),
                ("__init__", "/tmp/player-root"),
                (
                    "player_confirm",
                    {
                        "session_id": "pending:1",
                        "save_path": "",
                        "platform": "",
                        "session_key": "",
                        "actor_id": "",
                    },
                ),
            ],
        )

    def test_player_handler_does_not_call_low_level_runtime_or_sqlite(self) -> None:
        tree = ast.parse(textwrap.dedent(inspect.getsource(handle_player)))
        forbidden_names = {
            "GMRuntime",
            "Path",
            "os",
            "open",
            "shutil",
            "sqlite3",
            "connect",
            "load_delta",
            "load_turn_proposal",
            "write_text_atomic",
        }
        forbidden_attrs = {
            "from_path",
            "preview_action",
            "validate_delta",
            "commit_turn",
            "connect",
            "copy",
            "copyfile",
            "copytree",
            "hardlink_to",
            "open",
            "rmdir",
            "symlink_to",
            "touch",
            "write_text",
            "write_bytes",
            "mkdir",
            "unlink",
            "rename",
            "replace",
        }

        found_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and node.id in forbidden_names
        }
        found_attrs = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs
        }

        self.assertEqual(found_names, set())
        self.assertEqual(found_attrs, set())

    def test_platform_handler_routes_player_entries_through_sidecar(self) -> None:
        calls: list[tuple[str, object]] = []

        class SidecarResult:
            def __init__(self, kind: str) -> None:
                self.kind = kind

            def to_dict(self) -> dict[str, object]:
                return {"ok": True, "message": self.kind}

        class RecordingSidecar:
            def start_or_continue_from_message(self, event: dict[str, object], **kwargs: object) -> SidecarResult:
                calls.append(("start_or_continue_from_message", {"event": event, **kwargs}))
                return SidecarResult("started")

            def player_act_from_message(self, event: dict[str, object]) -> SidecarResult:
                calls.append(("player_act_from_message", event))
                return SidecarResult("acted")

            def player_confirm_from_message(self, event: dict[str, object], **kwargs: object) -> SidecarResult:
                calls.append(("player_confirm_from_message", {"event": event, **kwargs}))
                return SidecarResult("confirmed")

        sidecar = RecordingSidecar()

        def platform_args(platform_type: str, **overrides: object) -> Namespace:
            values = {
                "root": "/tmp/player-root",
                "platform_type": platform_type,
                "format": "json",
                "event_json": None,
                "user_text": "look around",
                "user_text_file": None,
                "user_text_stdin": False,
                "platform": "qq",
                "session_key": "chat:1",
                "message_id": "msg:1",
                "actor_id": "actor:1",
                "chat_type": None,
                "message_type": None,
                "actor_is_bot": False,
                "actor_is_self": False,
                "is_approval": False,
                "campaign": "camp",
                "starter_save": "starter",
                "label": "label",
                "no_create": False,
                "drain_before_act": False,
                "session_id": "pending:1",
            }
            values.update(overrides)
            return Namespace(**values)

        with (
            patch.object(cli_v1, "build_platform_sidecar", return_value=sidecar),
            patch.object(cli_v1, "SaveManager", side_effect=AssertionError("platform CLI must use sidecar")),
            patch.object(cli_v1.GMRuntime, "from_path", side_effect=AssertionError("platform CLI must not use GMRuntime")),
        ):
            self.assertEqual(handle_platform(platform_args("start")), 0)
            self.assertEqual(handle_platform(platform_args("act")), 0)
            self.assertEqual(handle_platform(platform_args("confirm")), 0)

        event = {
            "text": "look around",
            "platform": "qq",
            "session_key": "chat:1",
            "message_id": "msg:1",
            "actor_id": "actor:1",
        }
        self.assertEqual(
            calls,
            [
                (
                    "start_or_continue_from_message",
                    {
                        "event": event,
                        "campaign": "camp",
                        "starter_save": "starter",
                        "label": "label",
                        "create_if_missing": True,
                    },
                ),
                ("player_act_from_message", event),
                ("player_confirm_from_message", {"event": event, "session_id": "pending:1"}),
            ],
        )

    def test_mcp_handler_routes_config_and_serve_through_adapter_boundary(self) -> None:
        config = object()
        print_args = Namespace(
            mcp_type="print-config",
            root="/tmp/player-root",
            default_campaign="camp",
            default_save="save",
            default_starter_save="starter",
            registry_active=True,
            mcp_profile="player",
            client_command="aigm",
            server_name="aigm-kernel",
        )
        serve_args = Namespace(
            mcp_type="serve",
            root="/tmp/player-root",
            default_campaign="camp",
            default_save="save",
            default_starter_save="starter",
            registry_active=True,
            mcp_profile="player",
            ai_profile="off",
            ai_provider="fake",
            ai_model="fake-model",
            ai_timeout=1,
            semantic_ai=None,
            semantic_provider=None,
            semantic_model=None,
            semantic_timeout=None,
            intent_ai="off",
            intent_backend="direct",
            intent_provider="fake",
            intent_model="fake-model",
            intent_timeout=1,
            intent_base_url="",
            intent_api_key_env="",
            intent_fallback_backend="off",
            state_audit_ai="off",
            state_audit_provider="fake",
            state_audit_model="fake-model",
            state_audit_timeout=1,
            archivist_suggest=False,
            archivist_ai="off",
            archivist_provider="fake",
            archivist_model="fake-model",
            archivist_timeout=1,
            no_archivist_enqueue=False,
            transport="stdio",
        )

        with (
            patch.object(mcp_adapter, "build_client_config", return_value={"ok": True}) as build_client_config,
            patch.object(mcp_adapter, "render_client_config", return_value="{}\n") as render_client_config,
            patch.object(mcp_adapter.MCPAdapterConfig, "from_values", return_value=config) as from_values,
            patch.object(mcp_adapter, "serve_mcp") as serve_mcp,
            patch.object(cli_v1, "SaveManager", side_effect=AssertionError("mcp CLI must not use SaveManager")),
            patch.object(cli_v1.GMRuntime, "from_path", side_effect=AssertionError("mcp CLI must not use GMRuntime")),
        ):
            self.assertEqual(handle_mcp(print_args), 0)
            self.assertEqual(handle_mcp(serve_args), 0)

        build_client_config.assert_called_once_with(
            "/tmp/player-root",
            default_campaign="camp",
            default_save="save",
            default_starter_save="starter",
            registry_active=True,
            mcp_profile="player",
            command="aigm",
            server_name="aigm-kernel",
        )
        render_client_config.assert_called_once_with({"ok": True})
        self.assertEqual(from_values.call_args.kwargs["mcp_profile"], "player")
        self.assertEqual(from_values.call_args.kwargs["intent_ai"], "off")
        serve_mcp.assert_called_once_with(config, transport="stdio")

    def test_platform_and_mcp_handlers_do_not_call_low_level_runtime_or_sqlite(self) -> None:
        for handler in (handle_platform, handle_mcp):
            with self.subTest(handler=handler.__name__):
                tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
                forbidden_names = {"GMRuntime", "SaveManager", "sqlite3", "connect", "load_delta", "load_turn_proposal"}
                forbidden_attrs = {"from_path", "preview_action", "validate_delta", "commit_turn", "connect"}

                found_names = {
                    node.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name) and node.id in forbidden_names
                }
                found_attrs = {
                    node.attr
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs
                }

                self.assertEqual(found_names, set())
                self.assertEqual(found_attrs, set())

    def test_cli_intent_helpers_preserve_option_and_preflight_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path = Path(tmp) / "external.json"
            candidate = {"kind": "single", "mode": "action", "action": "rest", "slots": {"until": "morning"}}
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            args = Namespace(
                intent_ai="consensus",
                intent_backend="direct",
                intent_provider="deepseek",
                intent_model="deepseek-v4-flash",
                intent_timeout=7,
                intent_base_url="https://ai.example.test/v1",
                intent_api_key_env="AIGM_TEST_KEY",
                intent_fallback_backend="off",
                external_intent_candidate=str(candidate_path),
                preflight_id="preflight:cli",
                message_id="msg:cli",
                platform="qq",
                session_key="qq:user:1",
                source_user_text_hash="hash:cli",
                preflight_pending_wait_ms=10,
                preflight_identity_profile="message_only",
                ttl_seconds=300,
            )

            intent_options = intent_option_kwargs_from_args(args)
            preflight_options = preflight_consume_kwargs_from_args(args)
            preview_options = intent_preview_kwargs_from_args(args)
            production_options = intent_preflight_kwargs_from_args(args)

            self.assertEqual(intent_options["intent_ai"], "consensus")
            self.assertEqual(intent_options["intent_backend"], "direct")
            self.assertNotIn("external_intent_candidate", intent_options)
            self.assertEqual(preflight_options["message_id"], "msg:cli")
            self.assertEqual(preflight_options["preflight_pending_wait_ms"], 10)
            self.assertEqual(preview_options["external_intent_candidate"], candidate)
            self.assertEqual(preview_options["preflight_id"], "preflight:cli")
            self.assertNotIn("intent_ai", production_options)
            self.assertNotIn("preflight_id", production_options)
            self.assertNotIn("preflight_pending_wait_ms", production_options)
            self.assertEqual(production_options["preflight_identity_profile"], "message_only")
            self.assertEqual(production_options["ttl_seconds"], 300)

    def test_campaign_validate_and_test_commands(self) -> None:
        validate = load_stdout_json(run_cli("campaign", "validate", MINIMAL_FIXTURE, "--format", "json"))
        smoke = load_stdout_json(run_cli("campaign", "test", MINIMAL_FIXTURE, "--format", "json"))

        self.assertTrue(validate["ok"], validate)
        self.assertEqual(validate["campaign_id"], "minimal-campaign")
        self.assertEqual(validate["capabilities"], ["query", "rest_time"])
        self.assertTrue(smoke["ok"], smoke)
        self.assertTrue(smoke["init_ok"])
        self.assertTrue(smoke["health"]["ok"])
        self.assertEqual(len(smoke["smoke_results"]), 2)
        self.assertTrue(all(item["ok"] for item in smoke["smoke_results"]))

    def test_campaign_copy_example_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "copied-example"

            copied = load_stdout_json(run_cli("campaign", "copy-example", target, "--format", "json"))
            validate = load_stdout_json(run_cli("campaign", "validate", target, "--format", "json"))
            smoke = load_stdout_json(run_cli("campaign", "test", target, "--format", "json"))

            self.assertTrue(copied["ok"], copied)
            self.assertEqual(copied["example"], "v1_minimal_adventure")
            self.assertTrue((target / "campaign.yaml").exists())
            self.assertTrue(validate["ok"], validate)
            self.assertTrue(smoke["ok"], smoke)

    def test_campaign_copy_example_force_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "example"
            target.write_text("not a directory", encoding="utf-8")

            blocked = load_stdout_json(
                run_cli("campaign", "copy-example", target, "--format", "json", check=False)
            )
            forced = load_stdout_json(run_cli("campaign", "copy-example", target, "--force", "--format", "json"))

            self.assertFalse(blocked["ok"])
            self.assertTrue(forced["ok"], forced)
            self.assertTrue((target / "campaign.yaml").exists())

    def test_player_confirm_cli_json_hides_raw_commit_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MINIMAL_FIXTURE, root / "campaigns" / "minimal")

            started = load_stdout_json(
                run_cli("player", "start", root, "--campaign", "campaigns/minimal", "--format", "json")
            )
            acted = load_stdout_json(run_cli("player", "turn", root, "休息到早上", "--format", "json"))
            confirmed = load_stdout_json(
                run_cli("player", "confirm", root, "--session-id", acted["session_id"], "--format", "json")
            )
            replayed = load_stdout_json(
                run_cli("player", "confirm", root, "--session-id", acted["session_id"], "--format", "json")
            )

            self.assertTrue(started["ok"], started)
            self.assertTrue(acted["ready_to_confirm"], acted)
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertEqual(confirmed["write_status"], "committed")
            self.assertFalse(confirmed["idempotent_replay"])
            self.assertTrue(replayed["ok"], replayed)
            self.assertFalse(replayed["saved"], replayed)
            self.assertEqual(replayed["write_status"], "already_confirmed")
            self.assertTrue(replayed["idempotent_replay"])
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
                self.assertNotIn(hidden_key, replayed)

    def test_save_init_inspect_validate_export_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_campaign = root / "source-campaign"
            shutil.copytree(MINIMAL_FIXTURE, source_campaign)
            save_dir = root / "save"
            imported_dir = root / "imported"
            archive_path = root / "run.aigmsave"
            source_digest_before = tree_digest(source_campaign)

            init = load_stdout_json(run_cli("save", "init", source_campaign, save_dir, "--format", "json"))
            source_digest_after = tree_digest(source_campaign)
            inspect = load_stdout_json(run_cli("save", "inspect", save_dir, "--format", "json"))
            validate = run_cli("save", "validate", save_dir)
            export = load_stdout_json(
                run_cli("save", "export", save_dir, "--output", archive_path, "--format", "json")
            )
            default_export = load_stdout_json(run_cli("save", "export", save_dir, "--format", "json"))
            imported = load_stdout_json(
                run_cli("save", "import", archive_path, imported_dir, "--yes", "--format", "json")
            )
            imported_inspect = load_stdout_json(run_cli("save", "inspect", imported_dir, "--format", "json"))

            self.assertTrue(init["ok"], init)
            self.assertEqual(source_digest_after, source_digest_before)
            save_manifest = yaml.safe_load((save_dir / "save.yaml").read_text(encoding="utf-8"))
            save_campaign = yaml.safe_load((save_dir / "campaign.yaml").read_text(encoding="utf-8"))
            self.assertFalse(Path(save_manifest["source_campaign_path"]).is_absolute())
            self.assertEqual((save_dir / save_manifest["source_campaign_path"]).resolve(), source_campaign.resolve())
            self.assertEqual(save_campaign["database"], "data/game.sqlite")
            self.assertEqual(save_campaign["events"], "data/events.jsonl")
            self.assertEqual(save_campaign["current_snapshot"], "snapshots/current.md")
            self.assertEqual(save_campaign["current_snapshot_json"], "snapshots/current.json")
            self.assertEqual(save_campaign["cards"], "cards")
            for values in save_campaign["content"].values():
                paths = values if isinstance(values, list) else [values]
                self.assertTrue(all(not Path(path).is_absolute() for path in paths))
            self.assertTrue((save_dir / "campaign.yaml").exists())
            self.assertTrue((save_dir / "save.yaml").exists())
            self.assertTrue((save_dir / "data" / "game.sqlite").exists())
            self.assertTrue((save_dir / "data" / "events.jsonl").exists())
            self.assertTrue((save_dir / "snapshots" / "current.md").exists())
            self.assertTrue((save_dir / "snapshots" / "current.json").exists())
            self.assertTrue((save_dir / "cards").exists())
            self.assertEqual(inspect["current_turn_id"], "turn:seed")
            contract = inspect["authority_contract"]
            self.assertEqual(contract["current_fact_authority"]["path"], "data/game.sqlite")
            self.assertEqual(contract["current_fact_authority"]["role"], "current_fact_authority")
            self.assertEqual(contract["authoritative_audit"]["source"], "sqlite.events")
            self.assertEqual(contract["authoritative_audit"]["role"], "authoritative_audit")
            self.assertEqual(contract["audit_projection"]["path"], "data/events.jsonl")
            self.assertEqual(contract["audit_projection"]["authority"], "derived")
            self.assertEqual(contract["workspace_registry"]["role"], "workspace_index")
            self.assertEqual(contract["pending_state"]["authority"], "entry_state")
            self.assertEqual(contract["preflight_cache"]["authority"], "advisory")
            self.assertEqual(contract["archive_manifest"]["authority"], "evidence")
            health = inspect["projection_health"]
            self.assertEqual(health["authority"], "evidence")
            self.assertEqual(health["role"], "projection_health")
            self.assertEqual(health["current_turn_id"], "turn:seed")
            self.assertEqual(health["required"], ["events_jsonl", "search", "snapshots", "cards"])
            required = {item["name"]: item for item in health["items"]}
            self.assertEqual(required["events_jsonl"]["effective_status"], "clean")
            self.assertEqual(required["events_jsonl"]["version"], 1)
            self.assertEqual(required["events_jsonl"]["expected_version"], 1)
            self.assertEqual(required["events_jsonl"]["last_turn_id"], "turn:seed")
            self.assertEqual(required["events_jsonl"]["artifact_paths"], ["data/events.jsonl"])
            self.assertEqual(required["search"]["artifact_paths"], ["sqlite:fts_index"])
            self.assertEqual(required["snapshots"]["artifact_paths"], ["snapshots/current.md", "snapshots/current.json"])
            self.assertEqual(required["cards"]["artifact_paths"], ["cards/"])
            self.assertTrue(health["outbox"]["ok"])
            self.assertEqual(health["outbox"]["status"], "clean")
            self.assertEqual(health["outbox"]["counts"], {})
            self.assertEqual(health["outbox"]["non_done"], [])
            self.assertEqual(validate.stdout.strip(), "OK")
            self.assertEqual(export["archive_path"], str(archive_path))
            self.assertTrue(str(default_export["archive_path"]).endswith(".aigmsave"))
            self.assertTrue(imported["ok"], imported)
            self.assertTrue(imported_inspect["ok"], imported_inspect)
            self.assertEqual(current_turn(save_dir), "turn:seed")
            self.assertEqual(imported_inspect["current_turn_id"], "turn:seed")
            self.assertFalse((imported_dir / ".aigm" / "pending-player-action.json").exists())
            self.assertFalse((imported_dir / ".aigm" / "pending-player-clarification.json").exists())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("save.yaml", archive.namelist())

    def test_save_init_rejects_target_inside_source_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_campaign = root / "source-campaign"
            shutil.copytree(MINIMAL_FIXTURE, source_campaign)
            source_digest_before = tree_digest(source_campaign)
            nested_save = source_campaign / "saves" / "run"

            result = load_stdout_json(run_cli("save", "init", source_campaign, nested_save, "--format", "json", check=False))

            self.assertFalse(result["ok"], result)
            self.assertIn("save directory must not be inside source campaign package", "\n".join(result["errors"]))
            self.assertEqual(tree_digest(source_campaign), source_digest_before)
            self.assertFalse(nested_save.exists())

    def test_save_init_rejects_target_that_contains_source_campaign_even_with_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_campaign = root / "workspace" / "source-campaign"
            shutil.copytree(MINIMAL_FIXTURE, source_campaign)
            source_digest_before = tree_digest(source_campaign)

            result = load_stdout_json(run_cli("save", "init", source_campaign, root / "workspace", "--force", "--format", "json", check=False))

            self.assertFalse(result["ok"], result)
            self.assertIn("save directory must not contain source campaign package", "\n".join(result["errors"]))
            self.assertEqual(tree_digest(source_campaign), source_digest_before)
            self.assertTrue((source_campaign / "campaign.yaml").exists())

    def test_save_validate_rejects_dirty_projection_and_event_log_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirty_save = root / "dirty"
            event_save = root / "event-drift"
            run_cli("save", "init", MINIMAL_FIXTURE, dirty_save, "--format", "json")
            run_cli("save", "init", MINIMAL_FIXTURE, event_save, "--format", "json")

            conn = sqlite3.connect(dirty_save / "data" / "game.sqlite")
            try:
                conn.execute("update projection_state set status='dirty' where name='cards'")
                conn.commit()
            finally:
                conn.close()
            (event_save / "data" / "events.jsonl").write_text("", encoding="utf-8")
            event_turn_before_repair = current_turn(event_save)

            dirty = load_stdout_json(run_cli("save", "validate", dirty_save, "--format", "json", check=False))
            event_drift = load_stdout_json(run_cli("save", "validate", event_save, "--format", "json", check=False))
            repair = run_cli("projection", "repair", event_save, "--name", "events_jsonl", "--all")
            event_repaired = run_cli("save", "validate", event_save)

            self.assertFalse(dirty["ok"])
            self.assertIn("PROJECTION_INCONSISTENT", {item["code"] for item in dirty["error_details"]})
            self.assertFalse(event_drift["ok"])
            self.assertIn("EVENT_LOG_INCONSISTENT", {item["code"] for item in event_drift["error_details"]})
            self.assertIn("profile: projection_repair:maintenance_projection", repair.stdout)
            self.assertIn("requested: events_jsonl", repair.stdout)
            self.assertIn("refreshed: events_jsonl", repair.stdout)
            self.assertIn("outbox_status: clean", repair.stdout)
            self.assertIn("started_at:", repair.stdout)
            self.assertIn("finished_at:", repair.stdout)
            self.assertIn("duration_ms:", repair.stdout)
            self.assertEqual(current_turn(event_save), event_turn_before_repair)
            self.assertEqual(event_repaired.stdout.strip(), "OK")

    def test_save_validate_projection_health_covers_required_state_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "projection-health"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("delete from projection_state where name='events_jsonl'")
                conn.execute("update projection_state set version=0, status='clean' where name='search'")
                conn.execute(
                    "update projection_state set status='refreshing', last_turn_id='turn:old' where name='snapshots'"
                )
                conn.execute("update projection_state set status='dirty' where name='cards'")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            health = result["projection_health"]
            items = {item["name"]: item for item in health["items"]}
            self.assertEqual(items["events_jsonl"]["effective_status"], "missing")
            self.assertIsNone(items["events_jsonl"]["version"])
            self.assertFalse(items["events_jsonl"]["ok"])
            self.assertEqual(items["search"]["effective_status"], "stale")
            self.assertEqual(items["search"]["version"], 0)
            self.assertEqual(items["search"]["expected_version"], 1)
            self.assertEqual(items["snapshots"]["effective_status"], "refreshing")
            self.assertEqual(items["snapshots"]["last_turn_id"], "turn:old")
            self.assertFalse(items["snapshots"]["aligned_with_current_turn"])
            self.assertEqual(items["cards"]["effective_status"], "dirty")
            joined = "\n".join(result["errors"])
            self.assertIn("projection_state.events_jsonl: missing", joined)
            self.assertIn("projection_state.search: status is stale", joined)
            self.assertIn("projection_state.search: version 0 < 1", joined)
            self.assertIn("projection_state.snapshots: status is refreshing", joined)
            self.assertIn("projection_state.snapshots: last_turn_id turn:old != current_turn_id turn:seed", joined)
            self.assertIn("projection_state.cards: status is dirty", joined)

    def test_save_validate_rejects_missing_current_turn_id_in_projection_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "missing-current-turn"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("delete from meta where key='current_turn_id'")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIsNone(result["current_turn_id"])
            self.assertIn("meta.current_turn_id: missing", result["errors"])
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "missing_current_turn")
            self.assertIsNone(health["current_turn_id"])
            for item in health["items"]:
                self.assertFalse(item["ok"])
                self.assertFalse(item["aligned_with_current_turn"])

    def test_save_validate_rejects_blank_current_turn_id_in_projection_health(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "blank-current-turn"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("update meta set value='' where key='current_turn_id'")
                conn.execute("update projection_state set status='clean', last_turn_id='', version=1")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertEqual(result["current_turn_id"], "")
            self.assertIn("meta.current_turn_id: missing", result["errors"])
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "missing_current_turn")
            self.assertIsNone(health["current_turn_id"])
            for item in health["items"]:
                self.assertFalse(item["ok"])
                self.assertEqual(item["health_status"], "missing_current_turn")

    def test_save_validate_projection_health_reports_missing_outbox_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "missing-outbox"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("drop table outbox")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIn("sqlite schema: missing table outbox", result["errors"])
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "missing")
            self.assertFalse(health["outbox"]["ok"])
            self.assertEqual(health["outbox"]["status"], "missing")
            self.assertEqual(health["outbox"]["errors"], ["outbox: missing"])

    def test_save_validate_tolerates_partial_outbox_schema_and_reports_health_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "partial-outbox"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("drop table outbox")
                conn.execute("create table outbox(id text primary key, status text)")
                conn.execute("insert into outbox(id, status) values('out:partial', null)")
                conn.commit()
            finally:
                conn.close()
            (save_dir / "data" / "events.jsonl").write_text("", encoding="utf-8")

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            joined = "\n".join(result["errors"])
            self.assertIn("outbox schema: missing columns attempts, created_at, last_error, payload_json, processed_at, topic", joined)
            self.assertIn("outbox.out:partial: status is None", joined)
            self.assertIn("data/events.jsonl: missing SQLite event event:seed", joined)
            health = result["projection_health"]
            self.assertFalse(health["outbox"]["ok"])
            self.assertEqual(health["outbox"]["status"], "malformed")
            non_done = {row["id"]: row for row in health["outbox"]["non_done"]}
            self.assertIsNone(non_done["out:partial"]["status"])

    def test_save_validate_tolerates_partial_projection_state_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "partial-projection-state"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("drop table projection_state")
                conn.execute("create table projection_state(name text primary key, status text)")
                conn.execute("insert into projection_state(name, status) values('events_jsonl', 'clean')")
                conn.commit()
            finally:
                conn.close()
            (save_dir / "data" / "events.jsonl").write_text("", encoding="utf-8")

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            joined = "\n".join(result["errors"])
            self.assertNotIn("No item with that key", joined)
            self.assertIn("projection_state schema: missing columns last_error, last_turn_id, updated_at, version", joined)
            self.assertIn("data/events.jsonl: missing SQLite event event:seed", joined)
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "malformed")
            self.assertEqual(
                health["errors"],
                ["projection_state schema: missing columns last_error, last_turn_id, updated_at, version"],
            )
            for item in health["items"]:
                self.assertEqual(item["health_status"], "malformed")
                self.assertFalse(item["ok"])

    def test_save_validate_reports_unknown_projection_state_status_as_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "invalid-projection-status"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("update projection_state set status='weird' where name='cards'")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIn("projection_state.cards: invalid status weird", result["errors"])
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "invalid")
            cards = {item["name"]: item for item in health["items"]}["cards"]
            self.assertEqual(cards["effective_status"], "invalid")
            self.assertEqual(cards["health_status"], "invalid")
            self.assertFalse(cards["ok"])

    def test_save_validate_accepts_stored_stale_projection_state_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "stale-projection-status"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("update projection_state set status='stale' where name='cards'")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIn("projection_state.cards: status is stale", result["errors"])
            self.assertNotIn("projection_state.cards: invalid status stale", result["errors"])
            health = result["projection_health"]
            self.assertEqual(health["status"], "stale")
            cards = {item["name"]: item for item in health["items"]}["cards"]
            self.assertEqual(cards["effective_status"], "stale")
            self.assertEqual(cards["health_status"], "stale")

    def test_save_validate_rejects_duplicate_projection_state_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "duplicate-projection-state"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                rows = conn.execute(
                    "select name, version, last_turn_id, status, updated_at, last_error from projection_state"
                ).fetchall()
                conn.execute("drop table projection_state")
                conn.execute(
                    """
                    create table projection_state(
                      name text,
                      version integer,
                      last_turn_id text,
                      status text,
                      updated_at text,
                      last_error text
                    )
                    """
                )
                conn.executemany("insert into projection_state values(?, ?, ?, ?, ?, ?)", rows)
                conn.execute(
                    """
                    insert into projection_state(name, version, last_turn_id, status, updated_at, last_error)
                    values('cards', 1, 'turn:seed', 'failed', 'now', 'hidden failure')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIn("projection_state: duplicate names cards", result["errors"])
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "malformed")
            self.assertIn("projection_state: duplicate names cards", health["errors"])

    def test_save_validate_rejects_projection_state_and_outbox_views_as_missing_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "projection-views"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("alter table projection_state rename to projection_state_real")
                conn.execute("alter table outbox rename to outbox_real")
                conn.execute("create view projection_state as select * from projection_state_real")
                conn.execute("create view outbox as select * from outbox_real")
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIn("sqlite schema: missing table projection_state", result["errors"])
            self.assertIn("sqlite schema: missing table outbox", result["errors"])
            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "missing")
            self.assertEqual(health["outbox"]["status"], "missing")

    def test_save_validate_rejects_outbox_row_with_missing_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "outbox-missing-id"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("drop table outbox")
                conn.execute(
                    """
                    create table outbox(
                      id text,
                      topic text,
                      payload_json text,
                      status text,
                      attempts integer,
                      created_at text,
                      processed_at text,
                      last_error text
                    )
                    """
                )
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values(null, 'events.jsonl.append', '{}', 'pending', 0, 'created', null, null)
                    """
                )
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertIn("outbox row: missing id", result["errors"])
            health = result["projection_health"]["outbox"]
            self.assertEqual(health["status"], "malformed")
            self.assertEqual(health["non_done"][0]["id"], "<missing>")

    def test_save_validate_outbox_error_code_precedes_event_log_path_in_last_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "outbox-error-code"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values('out:event-path-error', 'events.jsonl.append', '{}', 'failed', 1, 'now', null, 'data/events.jsonl write failed')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            message = "outbox.out:event-path-error: status is failed (last_error: data/events.jsonl write failed)"
            error_codes = {item["message"]: item["code"] for item in result["error_details"]}
            self.assertEqual(error_codes[message], "PROJECTION_INCONSISTENT")

    def test_save_validate_event_log_error_code_precedes_outbox_text_in_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "event-id-with-outbox-text"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            (save_dir / "data" / "events.jsonl").write_text(
                json.dumps({"event_id": "outbox:looks-like-projection"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))

            message = "data/events.jsonl:1: event_id outbox:looks-like-projection not found in SQLite"
            error_codes = {item["message"]: item["code"] for item in result["error_details"]}
            self.assertEqual(error_codes[message], "EVENT_LOG_INCONSISTENT")

    def test_projection_repair_reports_unrelated_failed_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "repair-outbox"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("update projection_state set status='dirty' where name='snapshots'")
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values('out:unrelated-failed', 'unsupported.topic', '{}', 'failed', 2, 'now', null, 'unsupported outbox topic')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            repair = run_cli("projection", "repair", save_dir, "--name", "snapshots", "--all", check=False)

            self.assertEqual(repair.returncode, 1)
            self.assertIn("FAILED", repair.stdout)
            self.assertIn("status: partial_failure", repair.stdout)
            self.assertIn("global_status: failed", repair.stdout)
            self.assertIn("outbox_status: failed", repair.stdout)
            self.assertIn("outbox: out:unrelated-failed status=failed", repair.stdout)

    def test_projection_repair_reports_invalid_outbox_status_with_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "repair-invalid-outbox"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("update projection_state set status='dirty' where name='snapshots'")
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values('out:blocked', 'events.jsonl.append', '{}', 'blocked', 1, 'created', null, ?)
                    """
                    ,
                    ("blocked reason\nforged: yes",),
                )
                conn.commit()
            finally:
                conn.close()

            result = load_stdout_json(run_cli("save", "validate", save_dir, "--format", "json", check=False))
            self.assertEqual(result["projection_health"]["outbox"]["status"], "malformed")
            self.assertIn("outbox.out:blocked: invalid status blocked", result["errors"])

            repair = run_cli("projection", "repair", save_dir, "--name", "snapshots", "--all", check=False)

            self.assertEqual(repair.returncode, 1)
            self.assertIn("outbox_status: malformed", repair.stdout)
            self.assertIn("outbox: out:blocked status=blocked", repair.stdout)
            self.assertIn("created_at=created", repair.stdout)
            self.assertIn("processed_at=-", repair.stdout)
            self.assertIn("last_error=blocked reason forged: yes", repair.stdout)
            self.assertNotIn("\nforged: yes", repair.stdout)

    def test_projection_repair_reports_missing_projection_state_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "repair-missing-projection-state"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("drop table projection_state")
                conn.commit()
            finally:
                conn.close()

            repair = run_cli("projection", "repair", save_dir, "--name", "snapshots", "--all", check=False)

            self.assertEqual(repair.returncode, 1)
            self.assertIn("FAILED", repair.stdout)
            self.assertIn("global_status: failed", repair.stdout)
            self.assertIn("error: projection_state: missing", repair.stdout)
            self.assertNotIn("Traceback", repair.stderr)

    def test_projection_repair_reports_malformed_projection_state_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "repair-malformed-projection-state"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("drop table projection_state")
                conn.execute("create table projection_state(name text primary key, status text)")
                conn.commit()
            finally:
                conn.close()

            repair = run_cli("projection", "repair", save_dir, "--name", "snapshots", "--all", check=False)

            self.assertEqual(repair.returncode, 1)
            self.assertIn("FAILED", repair.stdout)
            self.assertIn("global_status: failed", repair.stdout)
            self.assertIn("error: projection_state schema: missing columns", repair.stdout)
            self.assertNotIn("Traceback", repair.stderr)

    def test_projection_repair_reports_invalid_projection_state_status_globally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "repair-invalid-projection-state"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                conn.execute("update projection_state set status='weird' where name='cards'")
                conn.commit()
            finally:
                conn.close()

            repair = run_cli("projection", "repair", save_dir, "--name", "snapshots", "--all", check=False)

            self.assertEqual(repair.returncode, 1)
            self.assertIn("global_status: failed", repair.stdout)
            self.assertIn("error: projection_state.cards: invalid status weird", repair.stdout)
            self.assertEqual(repair.stdout.count("global_stale: cards"), 1)

    def test_save_inspect_projection_health_unavailable_keeps_errors_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "missing-db-health"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            (save_dir / "data" / "game.sqlite").unlink()

            result = load_stdout_json(run_cli("save", "inspect", save_dir, "--format", "json", check=False))

            health = result["projection_health"]
            self.assertFalse(health["ok"])
            self.assertEqual(health["status"], "missing")
            self.assertIn("projection_health: unavailable", health["errors"])

    def test_save_inspect_reports_derived_drift_without_promoting_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "drift"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            before_turn = current_turn(save_dir)

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                before_counts = {
                    "entities": conn.execute("select count(*) from entities").fetchone()[0],
                    "turns": conn.execute("select count(*) from turns").fetchone()[0],
                    "events": conn.execute("select count(*) from events").fetchone()[0],
                    "clocks": conn.execute("select count(*) from clocks").fetchone()[0],
                }
                conn.execute("delete from fts_index")
                conn.execute(
                    "update projection_state set status='failed', last_error='broken' where name='snapshots'"
                )
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values('out:derived-drift', 'events_jsonl', '{}', 'pending', 0, 'now', null, null)
                    """
                )
                conn.execute(
                    """
                    insert into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error)
                    values('out:derived-failed', 'events_jsonl', '{}', 'failed', 2, 'now', null, 'boom')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            (save_dir / "data" / "events.jsonl").write_text(
                json.dumps({"event_id": "event:not-sqlite"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            snapshot_path = save_dir / "snapshots" / "current.json"
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            snapshot["meta"]["current_turn_id"] = "turn:artifact-only"
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            (save_dir / "cards" / "INDEX.md").unlink()

            inspected = load_stdout_json(run_cli("save", "inspect", save_dir, "--format", "json", check=False))

            self.assertFalse(inspected["ok"])
            self.assertEqual(inspected["current_turn_id"], before_turn)
            self.assertEqual(inspected["counts"], before_counts)
            joined = "\n".join(inspected["errors"])
            self.assertIn("data/events.jsonl:1: event_id event:not-sqlite not found in SQLite", joined)
            self.assertIn("data/events.jsonl: missing SQLite event event:seed", joined)
            self.assertIn("snapshots/current.json.meta.current_turn_id: expected", joined)
            self.assertIn("cards/INDEX.md: missing", joined)
            self.assertIn("fts_index: expected", joined)
            self.assertIn("projection_state.snapshots: status is failed", joined)
            self.assertIn("outbox.out:derived-drift: status is pending", joined)
            self.assertIn("outbox.out:derived-failed: status is failed (last_error: boom)", joined)
            error_codes = {item["message"]: item["code"] for item in inspected["error_details"]}
            self.assertEqual(error_codes["outbox.out:derived-failed: status is failed (last_error: boom)"], "PROJECTION_INCONSISTENT")
            health = inspected["projection_health"]
            items = {item["name"]: item for item in health["items"]}
            self.assertEqual(items["snapshots"]["status"], "failed")
            self.assertEqual(items["snapshots"]["effective_status"], "failed")
            self.assertEqual(items["snapshots"]["last_error"], "broken")
            non_done = {row["id"]: row for row in health["outbox"]["non_done"]}
            self.assertEqual(non_done["out:derived-drift"]["status"], "pending")
            self.assertEqual(non_done["out:derived-failed"]["status"], "failed")
            self.assertEqual(non_done["out:derived-failed"]["last_error"], "boom")

    def test_player_path_rejections_do_not_write_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            for bad_path in ("/tmp/outside", "../outside", "campaigns\\minimal"):
                with self.subTest(path=bad_path):
                    result = load_stdout_json(
                        run_cli(
                            "player",
                            "start",
                            root,
                            "--campaign",
                            bad_path,
                            "--format",
                            "json",
                            check=False,
                        )
                    )

                    self.assertFalse(result["ok"])
                    self.assertFalse((root / ".aigm").exists())

    def test_player_start_rejects_bad_paths_with_active_save_without_registry_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_dir = root / "campaigns" / "minimal"
            shutil.copytree(MINIMAL_FIXTURE, campaign_dir)
            started = load_stdout_json(
                run_cli("player", "start", root, "--campaign", "campaigns/minimal", "--format", "json")
            )
            save_dir = root / started["save"]["path"]
            before_registry = (root / ".aigm" / "save-registry.json").read_text(encoding="utf-8")
            before_turn = current_turn(save_dir)

            for bad_path in ("../outside", "campaigns\\minimal"):
                with self.subTest(path=bad_path):
                    result = load_stdout_json(
                        run_cli(
                            "player",
                            "start",
                            root,
                            "--campaign",
                            bad_path,
                            "--format",
                            "json",
                            check=False,
                        )
                    )

                    self.assertFalse(result["ok"])
                    self.assertEqual((root / ".aigm" / "save-registry.json").read_text(encoding="utf-8"), before_registry)
                    self.assertEqual(current_turn(save_dir), before_turn)
                    self.assertFalse((root / ".aigm" / "pending-player-action.json").exists())

    def test_save_archive_import_rejects_unsafe_or_drifted_members_without_replacing_target(self) -> None:
        def write_archive(path: Path, manifest: dict[str, object], members: dict[str, bytes]) -> None:
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("save-archive.json", json.dumps(manifest, ensure_ascii=False))
                for name, data in members.items():
                    archive.writestr(name, data)

        def assert_import_rejected(archive_path: Path, expected: str) -> None:
            result = load_stdout_json(
                run_cli("save", "import", archive_path, target, "--yes", "--force", "--format", "json", check=False)
            )
            self.assertFalse(result["ok"])
            self.assertIn(expected, "\n".join(result["errors"]))
            self.assertEqual((target / "sentinel.txt").read_text(encoding="utf-8"), "keep")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            target = root / "target"
            archive_path = root / "valid.aigmsave"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            exported = load_stdout_json(run_cli("save", "export", save_dir, "--output", archive_path, "--format", "json"))
            imported = load_stdout_json(run_cli("save", "import", archive_path, target, "--yes", "--format", "json"))
            self.assertTrue(exported["files"])
            self.assertTrue(imported["ok"], imported)
            (target / "sentinel.txt").write_text("keep", encoding="utf-8")

            base_manifest = {
                "archive_schema_version": 1,
                "campaign_id": "minimal-campaign",
                "files": [],
            }
            required_core_members = {
                "campaign.yaml": b"campaign: x\n",
                "save.yaml": b"save: x\n",
                "data/game.sqlite": b"sqlite-placeholder",
                "data/events.jsonl": b"",
                "snapshots/current.md": b"# Current\n",
                "snapshots/current.json": b"{}",
            }

            def manifest_for(members: dict[str, bytes], overrides: dict[str, dict[str, object]] | None = None) -> dict[str, object]:
                overrides = overrides or {}
                files = []
                for name, member_data in members.items():
                    entry = {
                        "path": name,
                        "bytes": len(member_data),
                        "sha256": hashlib.sha256(member_data).hexdigest(),
                    }
                    entry.update(overrides.get(name, {}))
                    files.append(entry)
                return {**base_manifest, "files": files}

            for member_name in ("/absolute.txt", "../escape.txt", "bad\\path.txt"):
                bad_archive = root / f"unsafe-{len(member_name)}.aigmsave"
                write_archive(bad_archive, base_manifest, {member_name: b"x"})
                assert_import_rejected(bad_archive, "unsafe archive path")

            unlisted = root / "unlisted.aigmsave"
            write_archive(unlisted, base_manifest, {"extra.txt": b"x"})
            assert_import_rejected(unlisted, "archive contains unlisted file")

            empty_manifest = root / "empty-manifest.aigmsave"
            write_archive(empty_manifest, base_manifest, {})
            assert_import_rejected(empty_manifest, "archive missing core file")

            missing_database = root / "missing-database.aigmsave"
            campaign_data = b"campaign: x\n"
            write_archive(
                missing_database,
                {
                    **base_manifest,
                    "files": [
                        {
                            "path": "campaign.yaml",
                            "bytes": len(campaign_data),
                            "sha256": hashlib.sha256(campaign_data).hexdigest(),
                        }
                    ],
                },
                {"campaign.yaml": campaign_data},
            )
            assert_import_rejected(missing_database, "archive missing core file")

            missing_core_with_bad_payload = root / "missing-core-with-bad-payload.aigmsave"
            data = b"campaign: x\n"
            write_archive(
                missing_core_with_bad_payload,
                manifest_for({"campaign.yaml": data}, {"campaign.yaml": {"bytes": len(data) + 1}}),
                {"campaign.yaml": data},
            )
            assert_import_rejected(missing_core_with_bad_payload, "archive missing core file")

            checksum = hashlib.sha256(data).hexdigest()
            size_mismatch = root / "size-mismatch.aigmsave"
            write_archive(
                size_mismatch,
                manifest_for(required_core_members, {"campaign.yaml": {"bytes": len(data) + 1, "sha256": checksum}}),
                required_core_members,
            )
            assert_import_rejected(size_mismatch, "size mismatch")

            checksum_mismatch = root / "checksum-mismatch.aigmsave"
            write_archive(
                checksum_mismatch,
                manifest_for(required_core_members, {"campaign.yaml": {"sha256": "bad"}}),
                required_core_members,
            )
            assert_import_rejected(checksum_mismatch, "checksum mismatch")

    def test_play_start_query_preview_and_commit_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "delta.json"
            proposal_path = root / "proposal.json"
            user_text_path = root / "user-text.txt"
            preview_user_text = "从L7泉眼取水。回厨房清点溪虾"
            user_text_path.write_text(preview_user_text + "\n", encoding="utf-8")
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")

            start = load_stdout_json(
                run_cli(
                    "play",
                    "start-turn",
                    save_dir,
                    "--user-text",
                    "查看周围",
                    "--mode",
                    "query",
                    "--submode",
                    "scene",
                    "--format",
                    "json",
                )
            )
            query = load_stdout_json(run_cli("play", "query", save_dir, "scene", "--format", "json"))
            preview = load_stdout_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "rest",
                    "--until",
                    "morning",
                    "--user-text-file",
                    user_text_path,
                    "--format",
                    "json",
                )
            )
            health = load_stdout_json(run_cli("play", "health", save_dir, "--format", "json"))
            delta_path.write_text(json.dumps(preview["delta_draft"], ensure_ascii=False), encoding="utf-8")
            proposal_path.write_text(json.dumps(preview["turn_proposal"], ensure_ascii=False), encoding="utf-8")
            commit = load_stdout_json(
                run_cli(
                    "play",
                    "commit",
                    save_dir,
                    delta_path,
                    "--proposal-json",
                    proposal_path,
                    "--format",
                    "json",
                )
            )

            self.assertTrue(start["can_proceed"], start)
            self.assertEqual(start["mode"], "query")
            self.assertIn("Start", query["text"])
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["status"], "ready")
            self.assertTrue(preview["ready_to_save"])
            self.assertIsInstance(preview["delta_draft"], dict)
            self.assertEqual(preview["delta_draft"]["user_text"], preview_user_text)
            self.assertIn("Delta 草案", preview["markdown"])
            self.assertTrue(health["ok"], health)
            self.assertEqual(commit["turn_id"], "turn:000001")
            self.assertEqual(current_turn(save_dir), "turn:000001")

    def test_external_contract_failures_are_safe_on_v1_cli_surfaces(self) -> None:
        sentinel = "secret-external-safety-token"
        user_text = "secret-user-request"
        base = {
            "kind": "single",
            "mode": "action",
            "action": "rest",
            "slots": {"until": "morning"},
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [sentinel],
            "reason": "test external contract boundary",
        }
        candidates = {
            "unknown": base,
            "mismatch": {
                **base,
                "contract": {
                    "manifest_schema_version": "1",
                    "manifest_digest": "0" * 64,
                    "safety_vocabulary_version": "1",
                    "safety_vocabulary_digest": "0" * 64,
                },
            },
        }
        expected_details = {
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
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            workspace = root / "workspace"
            shutil.copytree(MINIMAL_FIXTURE, workspace / "campaigns" / "minimal")
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            started = load_stdout_json(
                run_cli(
                    "player",
                    "start",
                    workspace,
                    "--campaign",
                    "campaigns/minimal",
                    "--format",
                    "json",
                )
            )
            active_save = workspace / str(started["save"]["path"])
            save_before = tree_digest(save_dir)
            active_save_before = tree_digest(active_save)

            for case, candidate_value in candidates.items():
                candidate = json.dumps(candidate_value)
                expected_detail = expected_details[case]
                commands = (
                    (
                        "play",
                        "start-turn",
                        save_dir,
                        "--user-text",
                        user_text,
                        "--external-intent-candidate",
                        candidate,
                        "--format",
                        "json",
                    ),
                    (
                        "play",
                        "preflight",
                        save_dir,
                        "--user-text",
                        user_text,
                        "--external-intent-candidate",
                        candidate,
                        "--format",
                        "json",
                    ),
                    (
                        "play",
                        "act",
                        save_dir,
                        user_text,
                        "--external-intent-candidate",
                        candidate,
                        "--format",
                        "json",
                    ),
                    (
                        "player",
                        "turn",
                        workspace,
                        user_text,
                        "--external-intent-candidate",
                        candidate,
                        "--format",
                        "json",
                    ),
                )
                for command in commands:
                    with self.subTest(case=case, command=command[:2]):
                        result = run_cli(*command, check=False)
                        data = load_stdout_json(result)

                        self.assertEqual(result.returncode, 1)
                        self.assertEqual(data["ok"], False)
                        self.assertEqual(data["error_details"], [expected_detail])
                        combined = result.stdout + result.stderr
                        self.assertNotIn(sentinel, combined)
                        self.assertNotIn(user_text, combined)
                        self.assertNotIn("Traceback", combined)

                human = run_cli(
                    "play",
                    "start-turn",
                    save_dir,
                    "--user-text",
                    user_text,
                    "--external-intent-candidate",
                    candidate,
                    check=False,
                )

                self.assertEqual(human.returncode, 1)
                self.assertIn("FAILED", human.stdout)
                self.assertIn(expected_detail["message"], human.stdout)
                self.assertIn(expected_detail["action"], human.stdout)
                self.assertNotIn(sentinel, human.stdout + human.stderr)
                self.assertNotIn(user_text, human.stdout + human.stderr)
                self.assertNotIn("Traceback", human.stdout + human.stderr)
            self.assertEqual(tree_digest(save_dir), save_before)
            self.assertEqual(tree_digest(active_save), active_save_before)
            self.assertFalse((workspace / ".aigm" / "pending-player-action.json").exists())

    def test_random_table_preview_rejects_table_and_dice_without_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", EXAMPLE, save_dir, "--format", "json")

            result = run_cli(
                "play",
                "preview",
                save_dir,
                "random_table",
                "--table",
                "table:bridge-risk",
                "--dice",
                "1d6",
                "--reason",
                "ambiguous random input",
                "--format",
                "json",
                check=False,
            )
            data = load_stdout_json(result)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(data["ok"])
            self.assertEqual(data["status"], "blocked")
            self.assertFalse(data["ready_to_save"])
            self.assertIsNone(data["delta_draft"])
            self.assertTrue(data["repair_options"])
            self.assertIn("choose either table or dice, not both", data["errors"])
            self.assertIn("### 错误", data["markdown"])
            self.assertNotIn("Delta 草案", data["markdown"])

    def test_top_level_preview_returns_nonzero_for_invalid_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", EXAMPLE, save_dir, "--format", "json")

            result = run_cli(
                "preview",
                "random_table",
                save_dir,
                "--table",
                "table:bridge-risk",
                "--dice",
                "1d6",
                check=False,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("choose either table or dice, not both", result.stdout)
            self.assertNotIn("Delta 草案", result.stdout)

    def test_play_validate_delta_and_commit_use_same_runtime_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "travel-delta.json"
            proposal_path = root / "travel-proposal.json"
            run_cli("save", "init", EXAMPLE, save_dir, "--format", "json")

            preview = load_stdout_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "travel",
                    "--destination",
                    "loc:old-bridge",
                    "--pace",
                    "careful",
                    "--user-text",
                    "Go to the old bridge",
                    "--format",
                    "json",
                )
            )
            self.assertEqual(preview["status"], "ready")
            self.assertTrue(preview["ready_to_save"])
            self.assertIsInstance(preview["delta_draft"], dict)
            delta_path.write_text(json.dumps(preview["delta_draft"], ensure_ascii=False), encoding="utf-8")
            proposal_path.write_text(json.dumps(preview["turn_proposal"], ensure_ascii=False), encoding="utf-8")

            validation = load_stdout_json(run_cli("play", "validate-delta", save_dir, delta_path, "--format", "json"))
            commit = load_stdout_json(
                run_cli(
                    "play",
                    "commit",
                    save_dir,
                    delta_path,
                    "--proposal-json",
                    proposal_path,
                    "--format",
                    "json",
                )
            )

            self.assertTrue(validation["ok"], validation)
            self.assertEqual(commit["turn_id"], "turn:000001")
            self.assertEqual(current_turn(save_dir), "turn:000001")

    def test_play_commit_state_audit_blocks_and_warn_only_reports_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "missing-inventory.json"
            proposal_path = root / "missing-inventory-proposal.json"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            preview = load_stdout_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "rest",
                    "--until",
                    "morning",
                    "--user-text",
                    "把鱼放进仓库",
                    "--format",
                    "json",
                )
            )
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
            proposal["proposal_id"] = "proposal:cli-state-audit-missing-inventory"
            proposal["delta"] = delta
            delta_path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
            proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")

            blocked = run_cli(
                "play",
                "commit",
                save_dir,
                delta_path,
                "--proposal-json",
                proposal_path,
                "--state-audit",
                "--format",
                "json",
                check=False,
            )
            allowed = load_stdout_json(
                run_cli(
                    "play",
                    "commit",
                    save_dir,
                    delta_path,
                    "--proposal-json",
                    proposal_path,
                    "--state-audit",
                    "--no-state-audit-block",
                    "--no-backup",
                    "--format",
                    "json",
                )
            )

            self.assertEqual(blocked.returncode, 1)
            self.assertIn("State audit blocked turn delta", blocked.stdout)
            self.assertEqual(allowed["turn_id"], "turn:000001")
            self.assertEqual(allowed["state_audit"]["risk"], "high")
            self.assertTrue(allowed["state_audit"]["findings"])

    def test_play_act_and_ux_metrics_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", EXAMPLE, save_dir, "--format", "json")

            act = load_stdout_json(
                run_cli(
                    "play",
                    "act",
                    save_dir,
                    "在家盘点库存",
                    "--format",
                    "json",
                )
            )
            metrics = load_stdout_json(run_cli("play", "ux-metrics", save_dir, "--format", "json"))

            self.assertEqual(act["action"], "routine")
            self.assertEqual(act["status"], "ready")
            self.assertTrue(act["ready_to_save"])
            self.assertEqual(act["delta_draft"]["events"][0]["payload"]["template_id"], "routine:inventory-audit")
            self.assertEqual(metrics["campaign_id"], "v1-minimal-adventure")
            self.assertGreater(metrics["scene_affordance_count"], 0)

    def test_aigm_console_script_is_declared(self) -> None:
        import tomllib

        data = tomllib.loads((ENGINE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["scripts"]["aigm"], "rpg_engine.cli:main")
        self.assertEqual(data["project"]["name"], "aigm-kernel")
        self.assertIn("mcp", data["project"]["optional-dependencies"])

    def test_mcp_print_config_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = load_stdout_json(
                run_cli(
                    "mcp",
                    "print-config",
                    root,
                    "--default-campaign",
                    "campaigns/minimal",
                    "--default-save",
                    "saves/run",
                    "--command",
                    "aigm",
                )
            )

            server = config["mcpServers"]["aigm-kernel"]
            self.assertEqual(server["command"], "aigm")
            self.assertEqual(server["args"][:4], ["mcp", "serve", "--root", str(root.resolve())])


if __name__ == "__main__":
    unittest.main()
