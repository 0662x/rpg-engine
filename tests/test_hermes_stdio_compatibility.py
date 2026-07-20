from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - CI and the focused gate install the mcp extra
    ClientSession = None
    stdio_client = None
    MCP_AVAILABLE = False

from rpg_engine.game_session import hash_identity
from rpg_engine.mcp_adapter import LOW_LEVEL_MCP_TOOL_NAMES, PLAYER_MCP_TOOL_NAMES
from tests.helpers import MINIMAL_FIXTURE, tree_digest


ENGINE_ROOT = Path(__file__).resolve().parents[1]


def compatibility_module():
    return importlib.import_module("tests.compatibility.hermes_stdio_provider")


def authoritative_snapshot(save_path: Path) -> tuple[int, int, str, bytes, str]:
    with sqlite3.connect(save_path / "data" / "game.sqlite") as conn:
        turns = int(conn.execute("select count(*) from turns").fetchone()[0])
        events = int(conn.execute("select count(*) from events").fetchone()[0])
        current_turn = str(conn.execute("select value from meta where key='current_turn_id'").fetchone()[0])
        schema_objects = conn.execute(
            "select type, name, tbl_name, coalesce(sql, '') from sqlite_master "
            "order by type, name, tbl_name"
        ).fetchall()
        authority_pragmas = {
            "application_id": int(conn.execute("pragma application_id").fetchone()[0]),
            "schema_version": int(conn.execute("pragma schema_version").fetchone()[0]),
            "user_version": int(conn.execute("pragma user_version").fetchone()[0]),
        }
        logical_rows: list[object] = [
            ("sqlite_master", schema_objects),
            ("authority_pragmas", authority_pragmas),
        ]
        tables = sorted(str(row[1]) for row in schema_objects if row[0] == "table")
        for table_name in tables:
            quoted = str(table_name).replace('"', '""')
            rows = conn.execute(f'select * from "{quoted}"').fetchall()
            normalized_rows = sorted(
                (
                    tuple(
                        {"blob_sha256": hashlib.sha256(value).hexdigest()}
                        if isinstance(value, bytes)
                        else value
                        for value in row
                    )
                    for row in rows
                ),
                key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
            )
            logical_rows.append((str(table_name), normalized_rows))
    sqlite_digest = hashlib.sha256(
        json.dumps(logical_rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return (
        turns,
        events,
        current_turn,
        (save_path / "data" / "events.jsonl").read_bytes(),
        sqlite_digest,
    )


def optional_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def guard_ready(fixture) -> dict[str, object]:
    payload = json.loads(fixture.network_guard_ready_path.read_text(encoding="utf-8"))
    if payload.get("loaded") is not True or not isinstance(payload.get("pid"), int):
        raise AssertionError(f"invalid compatibility guard-ready evidence: {payload}")
    return payload


def flattened_exceptions(exc: BaseException) -> tuple[BaseException, ...]:
    if isinstance(exc, BaseExceptionGroup):
        return tuple(item for nested in exc.exceptions for item in flattened_exceptions(nested))
    return (exc,)


class HermesStdioProviderFixtureTests(unittest.TestCase):
    def test_fixture_prepares_isolated_active_save_and_stable_player_launcher(self) -> None:
        compatibility = compatibility_module()
        source_before = tree_digest(MINIMAL_FIXTURE)

        with tempfile.TemporaryDirectory() as tmp:
            fixture = compatibility.prepare_provider_fixture(Path(tmp), engine_root=ENGINE_ROOT)

            self.assertEqual(fixture.root, Path(tmp).resolve())
            self.assertTrue(fixture.campaign_path.is_relative_to(fixture.root))
            self.assertTrue(fixture.save_path.is_relative_to(fixture.root))
            self.assertNotEqual(fixture.campaign_path.resolve(), MINIMAL_FIXTURE.resolve())
            self.assertTrue((fixture.save_path / "data" / "game.sqlite").is_file())
            self.assertTrue((fixture.root / ".aigm" / "save-registry.json").is_file())
            self.assertEqual(fixture.launch.command, sys.executable)
            self.assertEqual(fixture.launch.cwd, fixture.root / ".aigm" / "provider-cwd")
            self.assertEqual(
                fixture.launch.args[:4],
                ("-m", "rpg_engine", "mcp", "serve"),
            )
            self.assertIn("--registry-active", fixture.launch.args)
            self.assertNotIn("--default-save", fixture.launch.args)
            for option in ("--mcp-profile", "--semantic-ai", "--intent-ai", "--state-audit-ai", "--transport"):
                self.assertIn(option, fixture.launch.args)
            self.assertEqual(fixture.launch.value_after("--mcp-profile"), "player")
            self.assertEqual(fixture.launch.value_after("--semantic-ai"), "off")
            self.assertEqual(fixture.launch.value_after("--intent-ai"), "off")
            self.assertEqual(fixture.launch.value_after("--state-audit-ai"), "off")
            self.assertEqual(fixture.launch.value_after("--transport"), "stdio")
            self.assertEqual(
                set(fixture.launch.environment),
                {
                    "PYTHONDONTWRITEBYTECODE",
                    "PYTHONNOUSERSITE",
                    "PYTHONPATH",
                    "RPG_ENGINE_NETWORK_GUARD_LOG",
                    "RPG_ENGINE_NETWORK_GUARD_READY",
                    "RPG_ENGINE_DOTENV_GUARD_LOG",
                    "RPG_ENGINE_DOTENV_CANARY_PATH",
                },
            )
            self.assertEqual(fixture.launch.environment["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(fixture.launch.environment["PYTHONNOUSERSITE"], "1")
            self.assertEqual(
                fixture.launch.environment["PYTHONPATH"].split(os.pathsep),
                [str(fixture.network_guard_path.parent), str(ENGINE_ROOT)],
            )
            self.assertTrue(fixture.network_guard_path.is_file())
            self.assertEqual(
                fixture.dotenv_path.read_text(encoding="utf-8"),
                "RPG_ENGINE_COMPATIBILITY_DOTENV_CANARY=must-not-load\n",
            )
            self.assertFalse(fixture.network_attempts_path.exists())
            self.assertFalse(fixture.network_guard_ready_path.exists())
            self.assertFalse(fixture.dotenv_attempts_path.exists())

            user_base = Path(tmp) / "poison-user-base"
            user_site = Path(
                subprocess.check_output(
                    [sys.executable, "-c", "import site; print(site.getusersitepackages())"],
                    env={**os.environ, "PYTHONUSERBASE": str(user_base)},
                    text=True,
                ).strip()
            )
            user_site.mkdir(parents=True)
            usercustomize_marker = Path(tmp) / "usercustomize-loaded"
            (user_site / "usercustomize.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(usercustomize_marker)!r}).write_text('loaded', encoding='utf-8')\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, "-c", "import site; print(site.ENABLE_USER_SITE)"],
                cwd=fixture.launch.cwd,
                env={
                    **os.environ,
                    **fixture.launch.environment,
                    "PYTHONUSERBASE": str(user_base),
                },
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "False")
            self.assertFalse(usercustomize_marker.exists())
            campaign_argument = fixture.launch.value_after("--default-campaign")
            self.assertFalse(Path(campaign_argument).is_absolute())
            self.assertNotIn("..", Path(campaign_argument).parts)

        self.assertEqual(tree_digest(MINIMAL_FIXTURE), source_before)

    def test_script_contract_is_versioned_executable_and_regenerates_whole_candidate(self) -> None:
        compatibility = compatibility_module()
        contract = compatibility.load_script_contract()
        manifest = {
            "schema_version": "4",
            "manifest_digest": "a" * 64,
            "safety_vocabulary": {"version": "1", "digest": "b" * 64},
        }

        self.assertEqual(contract.schema_version, "1")
        self.assertEqual(contract.fixture_id, "rpg-engine-hermes-stdio-v1")
        self.assertEqual(
            contract.player_tools,
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
                "player_cancel",
                "player_confirm",
                "campaign_validate",
                "save_inspect",
                "health",
            ),
        )
        self.assertEqual(
            tuple(step.id for step in contract.steps),
            (
                "manifest_initial",
                "stale_candidate_rejected",
                "manifest_refreshed",
                "player_turn_ready",
                "explicit_player_confirmation",
                "wrong_session_rejected",
                "player_confirm_committed",
                "player_confirm_replayed",
                "safe_audit",
            ),
        )
        self.assertEqual(contract.step("explicit_player_confirmation").actor, "player")
        self.assertEqual(contract.step("player_turn_ready").actor, "scripted_model")
        self.assertEqual(contract.step("player_confirm_committed").actor, "client")

        stale = contract.build_candidate("stale", manifest)
        refreshed = contract.build_candidate("refreshed", manifest)

        self.assertIsNot(stale, refreshed)
        self.assertEqual(stale["contract"]["manifest_digest"], "0" * 64)
        self.assertEqual(refreshed["contract"]["manifest_digest"], manifest["manifest_digest"])
        self.assertNotEqual(stale["reason"], refreshed["reason"])
        self.assertEqual(stale["action"], "rest")
        self.assertEqual(refreshed["action"], "rest")
        self.assertEqual(refreshed["slots"], {"until": "morning"})
        self.assertEqual(
            contract.capture_references(),
            (
                "manifest_initial",
                "stale_candidate_rejected",
                "manifest_refreshed",
                "player_turn_ready",
                "explicit_player_confirmation",
                "wrong_session_rejected",
                "player_confirm_committed",
                "player_confirm_replayed",
            ),
        )
        self.assertEqual(
            contract.hook_fields("manifest"),
            (
                "schema_version",
                "manifest_digest",
                "safety_vocabulary.version",
                "safety_vocabulary.digest",
            ),
        )

        captures = {"manifest_initial": manifest}
        stale_arguments = contract.resolve_arguments("stale_candidate_rejected", captures)
        self.assertEqual(stale_arguments["user_text"], "wire-user-text-canary")
        self.assertEqual(
            stale_arguments["external_intent_candidate"]["contract"]["manifest_digest"],
            "0" * 64,
        )
        self.assertEqual(
            stale_arguments["external_intent_candidate"]["Private-Reasoning"],
            "wire-private-body-canary",
        )
        captures["manifest_refreshed"] = manifest
        refreshed_arguments = contract.resolve_arguments("player_turn_ready", captures)
        self.assertIsNot(
            stale_arguments["external_intent_candidate"],
            refreshed_arguments["external_intent_candidate"],
        )
        captures["player_turn_ready"] = {"session_id": "player_action:typed-reference"}
        confirmation = contract.resolve_arguments("explicit_player_confirmation", captures)
        self.assertEqual(
            confirmation,
            {"confirmed": True, "session_id": "player_action:typed-reference"},
        )
        captures["explicit_player_confirmation"] = confirmation
        self.assertEqual(
            contract.resolve_arguments("player_confirm_committed", captures),
            {"session_id": "player_action:typed-reference"},
        )
        self.assertEqual(
            contract.project_hook("explicit_player_confirmation", confirmation),
            {"confirmed": True, "session_id_present": True},
        )
        with self.assertRaises(TypeError):
            contract.candidate_generations["refreshed"]["action"] = "travel"
        with self.assertRaises(TypeError):
            contract.step("wrong_session_rejected").expect["ok"] = 0
        with self.assertRaises(TypeError):
            contract.step("player_turn_ready").arguments["user_text"] = "mutated"
        self.assertEqual(
            contract.resolve_arguments("wrong_session_rejected", captures),
            {"session_id": "player_action:wrong-wire-canary"},
        )
        self.assertEqual(
            contract.assert_step_expectation("manifest_initial", manifest),
            contract.project_hook("manifest", manifest),
        )
        with self.assertRaises(AssertionError):
            contract.assert_step_expectation("wrong_session_rejected", {"ok": 0})
        with self.assertRaises(AssertionError):
            contract.assert_step_expectation(
                "wrong_session_rejected",
                {"ok": False, "errors": ["no active save is configured"]},
            )
        with self.assertRaises(AssertionError):
            contract.assert_step_expectation(
                "safe_audit",
                {
                    "tool": "   ",
                    "status": "ok",
                    "identity": {"profile": "player"},
                    "result": {"ok": True},
                },
            )
        with self.assertRaisesRegex(AssertionError, "status must agree"):
            contract.assert_step_expectation(
                "safe_audit",
                {
                    "tool": "player_confirm",
                    "status": "ok",
                    "identity": {"profile": "player"},
                    "result": {"ok": False},
                },
            )

    def test_contract_schema_and_wire_decoder_fail_closed(self) -> None:
        compatibility = compatibility_module()
        payload = yaml.safe_load(compatibility.DEFAULT_CONTRACT_PATH.read_text(encoding="utf-8"))

        mutations = []
        unknown_top_level = copy.deepcopy(payload)
        unknown_top_level["unknown"] = True
        mutations.append(unknown_top_level)
        unknown_step_field = copy.deepcopy(payload)
        unknown_step_field["steps"][0]["unknown"] = True
        mutations.append(unknown_step_field)
        changed_player_surface = copy.deepcopy(payload)
        changed_player_surface["player_tools"].append("unexpected_tool")
        mutations.append(changed_player_surface)
        raw_hook_field = copy.deepcopy(payload)
        raw_hook_field["hooks"]["player_turn"]["fields"][4] = "session_id"
        mutations.append(raw_hook_field)
        unknown_hook_field = copy.deepcopy(payload)
        unknown_hook_field["hooks"]["manifest"]["ignored_extension"] = {
            "raw": "wire-secret"
        }
        mutations.append(unknown_hook_field)
        forward_reference = copy.deepcopy(payload)
        forward_reference["steps"][0]["arguments"] = {"bad": {"$ref": "player_turn_ready.session_id"}}
        mutations.append(forward_reference)
        false_confirmation = copy.deepcopy(payload)
        false_confirmation["steps"][4]["arguments"]["confirmed"] = False
        mutations.append(false_confirmation)
        contract_override = copy.deepcopy(payload)
        contract_override["steps"][3]["arguments"]["external_intent_candidate"]["$candidate"][
            "overrides"
        ] = {"contract": {"manifest_digest": "override"}}
        mutations.append(contract_override)
        changed_expectation = copy.deepcopy(payload)
        changed_expectation["steps"][5]["expect"]["ok"] = True
        mutations.append(changed_expectation)
        bool_as_integer_expectation = copy.deepcopy(payload)
        bool_as_integer_expectation["steps"][3]["expect"]["ok"] = 1
        mutations.append(bool_as_integer_expectation)
        changed_generation = copy.deepcopy(payload)
        changed_generation["candidate_generations"]["refreshed"]["action"] = "travel"
        mutations.append(changed_generation)

        for index, mutation in enumerate(mutations):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "contract.yaml"
                path.write_text(yaml.safe_dump(mutation, allow_unicode=True, sort_keys=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    compatibility.load_script_contract(path)

        duplicate_source = compatibility.DEFAULT_CONTRACT_PATH.read_text(encoding="utf-8").replace(
            "    arguments: {}\n    hook: manifest",
            "    arguments: {}\n    arguments: {}\n    hook: manifest",
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            duplicate_path = Path(tmp) / "duplicate.yaml"
            duplicate_path.write_text(duplicate_source, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate mapping key"):
                compatibility.load_script_contract(duplicate_path)

        contract = compatibility.load_script_contract()
        with self.assertRaisesRegex(KeyError, "capture path is missing"):
            contract.resolve_arguments(
                "explicit_player_confirmation",
                {"player_turn_ready": {"ok": True}},
            )
        with self.assertRaisesRegex(ValueError, "cannot resolve to null"):
            contract.resolve_arguments(
                "explicit_player_confirmation",
                {"player_turn_ready": {"session_id": None}},
            )

        text = SimpleNamespace(type="text", text='{"ok": true}')
        image = SimpleNamespace(type="image", data="hidden-wire-canary")
        with self.assertRaisesRegex(ValueError, "exactly one TextContent"):
            compatibility.decode_tool_result(SimpleNamespace(isError=False, content=[text, image]))
        self.assertEqual(
            compatibility.decode_tool_result(
                SimpleNamespace(
                    isError=False,
                    content=[text],
                    structuredContent={"ok": True},
                    meta=None,
                )
            ),
            {"ok": True},
        )
        with self.assertRaisesRegex(ValueError, "structuredContent must exactly match"):
            compatibility.decode_tool_result(
                SimpleNamespace(
                    isError=False,
                    content=[text],
                    structuredContent={"ok": True, "hidden": "gm-canary"},
                    meta=None,
                )
            )
        with self.assertRaisesRegex(ValueError, "opaque _meta"):
            compatibility.decode_tool_result(
                SimpleNamespace(
                    isError=False,
                    content=[text],
                    structuredContent={"ok": True},
                    meta={"private": "gm-canary"},
                )
            )

    def test_fixture_protects_custom_sources_aliases_and_path_separator_roots(self) -> None:
        compatibility = compatibility_module()
        source_before = tree_digest(MINIMAL_FIXTURE)

        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            custom_source = parent / "custom-source"
            shutil.copytree(MINIMAL_FIXTURE, custom_source)
            workspace = parent / "workspace"
            fixture = compatibility.prepare_provider_fixture(
                workspace,
                engine_root=ENGINE_ROOT,
                campaign_source=custom_source,
                protected_paths=(),
            )
            self.assertTrue(fixture.save_path.is_relative_to(workspace.resolve()))
            self.assertEqual(tree_digest(custom_source), tree_digest(fixture.campaign_path))

            nested_alias = custom_source / "empty-workspace"
            nested_alias.mkdir()
            with self.assertRaisesRegex(ValueError, "aliases protected data"):
                compatibility.prepare_provider_fixture(
                    nested_alias,
                    engine_root=ENGINE_ROOT,
                    campaign_source=custom_source,
                    protected_paths=(),
                )

            symlink_alias = parent / "source-alias"
            symlink_alias.symlink_to(MINIMAL_FIXTURE, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "aliases protected data"):
                compatibility.prepare_provider_fixture(
                    symlink_alias,
                    engine_root=ENGINE_ROOT,
                    protected_paths=(),
                )

            separator_root = parent / f"invalid{os.pathsep}workspace"
            with self.assertRaisesRegex(ValueError, "cannot contain"):
                compatibility.prepare_provider_fixture(separator_root, engine_root=ENGINE_ROOT)

            with patch.dict(
                os.environ,
                {
                    "RPG_ENGINE_CURRENT_CAMPAIGN_ROOT": "",
                    "RPG_ENGINE_CURRENT_SAVE_ROOT": "   ",
                },
            ):
                blank_env_paths = compatibility.default_protected_paths(ENGINE_ROOT)
            self.assertNotIn(Path.cwd().resolve(), blank_env_paths)

            campaign_workspace = parent / "formal-campaign-workspace"
            formal_campaign = campaign_workspace / "campaign"
            formal_campaign.mkdir(parents=True)
            campaign_registry = campaign_workspace / ".aigm" / "save-registry.json"
            campaign_registry.parent.mkdir()
            campaign_registry.write_text("{}\n", encoding="utf-8")
            save_workspace = parent / "formal-save-workspace"
            formal_save = save_workspace / "save"
            formal_save.mkdir(parents=True)
            save_registry = save_workspace / ".aigm" / "save-registry.json"
            save_registry.parent.mkdir()
            save_registry.write_text("{}\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "RPG_ENGINE_CURRENT_CAMPAIGN_ROOT": str(formal_campaign),
                    "RPG_ENGINE_CURRENT_SAVE_ROOT": str(formal_save),
                },
            ):
                configured_paths = compatibility.default_protected_paths(ENGINE_ROOT)
            self.assertIn(formal_campaign.resolve(), configured_paths)
            self.assertIn(formal_save.resolve(), configured_paths)
            self.assertIn(campaign_registry.resolve(), configured_paths)
            self.assertIn(save_registry.resolve(), configured_paths)

            reserved_campaign = parent / "reserved-formal-campaign"
            reserved_save = parent / "reserved-formal-save"
            with patch.dict(
                os.environ,
                {
                    "RPG_ENGINE_CURRENT_CAMPAIGN_ROOT": str(reserved_campaign),
                    "RPG_ENGINE_CURRENT_SAVE_ROOT": str(reserved_save),
                },
            ):
                missing_paths = compatibility.default_protected_paths(ENGINE_ROOT)
                missing_before = compatibility.fingerprint_paths(missing_paths)
                self.assertIn(reserved_campaign.resolve(), missing_paths)
                self.assertIn(reserved_save.resolve(), missing_paths)
                with self.assertRaisesRegex(ValueError, "aliases protected data"):
                    compatibility.prepare_provider_fixture(
                        reserved_campaign / "compatibility-workspace",
                        engine_root=ENGINE_ROOT,
                    )
                self.assertEqual(
                    compatibility.fingerprint_paths(missing_paths),
                    missing_before,
                )
            self.assertFalse(reserved_campaign.exists())
            self.assertFalse(reserved_save.exists())

        self.assertEqual(tree_digest(MINIMAL_FIXTURE), source_before)

    def test_network_guard_is_loaded_and_denies_dns_and_connectionless_io(self) -> None:
        compatibility = compatibility_module()
        probe = """
import _socket
import _io
import importlib
import os
import sitecustomize
import socket

if hasattr(sitecustomize, "_SOCKET"):
    raise SystemExit("network guard exposes its raw socket constructor")
operations = (
    lambda: socket.gethostbyname("localhost"),
    lambda: socket.getaddrinfo("localhost", 80),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9)),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", 9)),
    lambda: socket.socket(socket.AF_INET6, socket.SOCK_STREAM).connect(("::1", 9)),
    lambda: socket.socket(socket.AF_INET6, socket.SOCK_DGRAM).sendto(b"x", ("::1", 9)),
    lambda: _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9)),
    lambda: _socket.SocketType(_socket.AF_INET, _socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9)),
    lambda: socket._socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9)),
    lambda: importlib.reload(_socket).SocketType(_socket.AF_INET, _socket.SOCK_DGRAM).sendto(b"x", ("127.0.0.1", 9)),
    lambda: _socket.socket.__init__.__objclass__(_socket.AF_INET, _socket.SOCK_DGRAM),
    lambda: importlib.reload(socket).socket(socket.AF_INET, socket.SOCK_DGRAM),
)
for operation in operations:
    try:
        operation()
    except RuntimeError:
        pass
    else:
        raise SystemExit("network operation escaped compatibility guard")
try:
    open(os.environ["RPG_ENGINE_DOTENV_CANARY_PATH"], encoding="utf-8").read()
except RuntimeError:
    pass
else:
    raise SystemExit("dotenv read escaped compatibility guard")
try:
    os.open(os.environ["RPG_ENGINE_DOTENV_CANARY_PATH"], os.O_RDONLY)
except RuntimeError:
    pass
else:
    raise SystemExit("os.open dotenv read escaped compatibility guard")
try:
    importlib.reload(__import__("io")).open(
        os.environ["RPG_ENGINE_DOTENV_CANARY_PATH"],
        encoding="utf-8",
    ).read()
except RuntimeError:
    pass
else:
    raise SystemExit("reloaded io.open dotenv read escaped compatibility guard")
try:
    _io.open(os.environ["RPG_ENGINE_DOTENV_CANARY_PATH"], encoding="utf-8").read()
except RuntimeError:
    pass
else:
    raise SystemExit("_io.open dotenv read escaped compatibility guard")
canary = __import__("pathlib").Path(os.environ["RPG_ENGINE_DOTENV_CANARY_PATH"])
symlink_alias = canary.with_name("config-link")
symlink_alias.symlink_to(canary)
try:
    open(symlink_alias, encoding="utf-8").read()
except RuntimeError:
    pass
else:
    raise SystemExit("symlink dotenv read escaped compatibility guard")
hardlink_alias = canary.with_name("config-hardlink")
os.link(canary, hardlink_alias)
try:
    os.open(hardlink_alias, os.O_RDONLY)
except RuntimeError:
    pass
else:
    raise SystemExit("hardlink dotenv read escaped compatibility guard")
"""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = compatibility.prepare_provider_fixture(Path(tmp), engine_root=ENGINE_ROOT)
            completed = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=ENGINE_ROOT,
                env=fixture.launch.environment,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                guard_ready(fixture)["loaded"],
                True,
            )
            attempts = [
                json.loads(line)["operation"]
                for line in fixture.network_attempts_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                attempts,
                [
                    "socket.gethostbyname",
                    "socket.getaddrinfo",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                    "socket.__new__",
                ],
            )
            self.assertEqual(
                [
                    json.loads(line)
                    for line in fixture.dotenv_attempts_path.read_text(encoding="utf-8").splitlines()
                ],
                [
                    {"name": ".env", "operation": "open"},
                    {"name": ".env", "operation": "open"},
                    {"name": ".env", "operation": "open"},
                    {"name": ".env", "operation": "open"},
                    {"name": ".env", "operation": "open"},
                    {"name": "config-hardlink", "operation": "open"},
                ],
            )

    def test_protected_fingerprint_rejects_symlink_blind_spots(self) -> None:
        compatibility = compatibility_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "formal.sqlite"
            target.write_bytes(b"formal-data")
            protected = root / "protected"
            protected.mkdir()
            (protected / "player.sqlite").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "cannot contain symlinks"):
                compatibility.fingerprint_paths((protected,))


@unittest.skipUnless(MCP_AVAILABLE, "requires the project mcp extra")
class HermesRealStdioContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_player_surface_manifest_and_candidate_refresh_contract(self) -> None:
        compatibility = compatibility_module()

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr:
            parent = Path(tmp)
            fixture = compatibility.prepare_provider_fixture(parent / "provider-one", engine_root=ENGINE_ROOT)
            campaign_before = compatibility.fingerprint_paths((fixture.campaign_path,))
            contract = compatibility.load_script_contract()
            parameters = compatibility.stdio_server_parameters(fixture)
            captures: dict[str, object] = {}

            async with asyncio_timeout(15):
                async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        tool_names = tuple(tool.name for tool in listed.tools)
                        manifest_step = contract.step("manifest_initial")
                        initial_manifest = compatibility.decode_tool_result(
                            await session.call_tool(
                                manifest_step.tool or "",
                                contract.resolve_arguments(manifest_step.id, captures),
                            )
                        )
                        captures[manifest_step.capture or ""] = initial_manifest
                        contract.assert_step_expectation(manifest_step.id, initial_manifest)
                        stale_step = contract.step("stale_candidate_rejected")
                        stale_arguments = contract.resolve_arguments(stale_step.id, captures)
                        stale_candidate = stale_arguments["external_intent_candidate"]
                        stale = compatibility.decode_tool_result(
                            await session.call_tool(stale_step.tool or "", stale_arguments)
                        )
                        captures[stale_step.capture or ""] = stale
                        contract.assert_step_expectation(stale_step.id, stale)
                        refreshed_step = contract.step("manifest_refreshed")
                        refreshed_manifest = compatibility.decode_tool_result(
                            await session.call_tool(
                                refreshed_step.tool or "",
                                contract.resolve_arguments(refreshed_step.id, captures),
                            )
                        )
                        captures[refreshed_step.capture or ""] = refreshed_manifest
                        contract.assert_step_expectation(refreshed_step.id, refreshed_manifest)
                        refreshed_candidate = contract.resolve_arguments("player_turn_ready", captures)[
                            "external_intent_candidate"
                        ]

            second_fixture = compatibility.prepare_provider_fixture(
                parent / "provider-two",
                engine_root=ENGINE_ROOT,
            )
            second_campaign_before = compatibility.fingerprint_paths((second_fixture.campaign_path,))
            second_parameters = compatibility.stdio_server_parameters(second_fixture)
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as second_stderr:
                async with asyncio_timeout(15):
                    async with stdio_client(second_parameters, errlog=second_stderr) as (read_stream, write_stream):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            second_manifest = compatibility.decode_tool_result(
                                await session.call_tool("intent_manifest", {})
                            )

            self.assertEqual(tool_names, contract.player_tools)
            self.assertEqual(PLAYER_MCP_TOOL_NAMES, contract.player_tools)
            for tool in LOW_LEVEL_MCP_TOOL_NAMES:
                self.assertNotIn(tool, tool_names)
            self.assertEqual(initial_manifest, refreshed_manifest)
            self.assertEqual(initial_manifest["schema_version"], "4")
            self.assertRegex(initial_manifest["manifest_digest"], r"^[0-9a-f]{64}$")
            self.assertRegex(initial_manifest["safety_vocabulary"]["digest"], r"^[0-9a-f]{64}$")
            self.assertFalse(stale["ok"], stale)
            self.assertEqual(stale["error_details"][0]["code"], "INTENT_CONTRACT_VERSION_MISMATCH")
            self.assertEqual(stale["error_details"][0]["reason"], "contract_version_mismatch")
            self.assertTrue(stale["error_details"][0]["retriable"])
            self.assertEqual(
                stale["error_details"][0]["action"],
                "refresh_manifest_and_regenerate_candidate",
            )
            self.assertIsNot(stale_candidate, refreshed_candidate)
            self.assertNotEqual(stale_candidate["reason"], refreshed_candidate["reason"])
            self.assertEqual(
                refreshed_candidate["contract"]["manifest_digest"],
                refreshed_manifest["manifest_digest"],
            )
            self.assertEqual(
                {
                    "schema_version": second_manifest["schema_version"],
                    "manifest_digest": second_manifest["manifest_digest"],
                    "safety_vocabulary_version": second_manifest["safety_vocabulary"]["version"],
                    "safety_vocabulary_digest": second_manifest["safety_vocabulary"]["digest"],
                },
                {
                    "schema_version": initial_manifest["schema_version"],
                    "manifest_digest": initial_manifest["manifest_digest"],
                    "safety_vocabulary_version": initial_manifest["safety_vocabulary"]["version"],
                    "safety_vocabulary_digest": initial_manifest["safety_vocabulary"]["digest"],
                },
            )
            stderr.seek(0)
            self.assertNotIn("Failed to parse JSONRPC", stderr.read())
            self.assertFalse(fixture.network_attempts_path.exists())
            self.assertFalse(second_fixture.network_attempts_path.exists())
            self.assertTrue(guard_ready(fixture)["loaded"])
            self.assertTrue(guard_ready(second_fixture)["loaded"])
            self.assertFalse(fixture.dotenv_attempts_path.exists())
            self.assertFalse(second_fixture.dotenv_attempts_path.exists())
            self.assertEqual(
                compatibility.fingerprint_paths((fixture.campaign_path,)),
                campaign_before,
            )
            self.assertEqual(
                compatibility.fingerprint_paths((second_fixture.campaign_path,)),
                second_campaign_before,
            )

    async def test_scripted_turn_confirm_replay_audit_and_protected_data_contract(self) -> None:
        compatibility = compatibility_module()
        protected_paths = compatibility.default_protected_paths(ENGINE_ROOT)
        protected_before = compatibility.fingerprint_paths(protected_paths)
        self.addCleanup(
            lambda: self.assertEqual(
                compatibility.fingerprint_paths(protected_paths),
                protected_before,
            )
        )

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr:
            fixture = compatibility.prepare_provider_fixture(
                Path(tmp),
                engine_root=ENGINE_ROOT,
                protected_paths=protected_paths,
            )
            campaign_before = compatibility.fingerprint_paths((fixture.campaign_path,))
            contract = compatibility.load_script_contract()
            parameters = compatibility.stdio_server_parameters(fixture)
            pending_path = fixture.root / ".aigm" / "pending-player-action.json"
            receipt_path = fixture.root / ".aigm" / "last-confirmed-player-action.json"
            initial = authoritative_snapshot(fixture.save_path)
            captures: dict[str, object] = {}
            self.assertIsNone(optional_bytes(pending_path))
            self.assertIsNone(optional_bytes(receipt_path))

            async with asyncio_timeout(20):
                async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        manifest_step = contract.step("manifest_initial")
                        manifest_initial = compatibility.decode_tool_result(
                            await session.call_tool(
                                manifest_step.tool or "",
                                contract.resolve_arguments(manifest_step.id, captures),
                            )
                        )
                        captures[manifest_step.capture or ""] = manifest_initial
                        contract.assert_step_expectation(manifest_step.id, manifest_initial)
                        stale_step = contract.step("stale_candidate_rejected")
                        stale_arguments = contract.resolve_arguments(stale_step.id, captures)
                        stale_candidate = stale_arguments["external_intent_candidate"]
                        stale = compatibility.decode_tool_result(
                            await session.call_tool(stale_step.tool or "", stale_arguments)
                        )
                        captures[stale_step.capture or ""] = stale
                        contract.assert_step_expectation(stale_step.id, stale)
                        after_stale = authoritative_snapshot(fixture.save_path)
                        pending_after_stale = optional_bytes(pending_path)
                        receipt_after_stale = optional_bytes(receipt_path)
                        refreshed_step = contract.step("manifest_refreshed")
                        manifest_refreshed = compatibility.decode_tool_result(
                            await session.call_tool(
                                refreshed_step.tool or "",
                                contract.resolve_arguments(refreshed_step.id, captures),
                            )
                        )
                        captures[refreshed_step.capture or ""] = manifest_refreshed
                        contract.assert_step_expectation(refreshed_step.id, manifest_refreshed)
                        turn_step = contract.step("player_turn_ready")
                        turn_arguments = contract.resolve_arguments(turn_step.id, captures)
                        refreshed_candidate = turn_arguments["external_intent_candidate"]
                        turn = compatibility.decode_tool_result(
                            await session.call_tool(turn_step.tool or "", turn_arguments)
                        )
                        captures[turn_step.capture or ""] = turn
                        contract.assert_step_expectation(turn_step.id, turn)
                        after_turn = authoritative_snapshot(fixture.save_path)
                        pending_before_wrong = optional_bytes(pending_path)
                        receipt_before_wrong = optional_bytes(receipt_path)
                        confirmation_step = contract.step("explicit_player_confirmation")
                        explicit_confirmation = contract.resolve_arguments(confirmation_step.id, captures)
                        captures[confirmation_step.capture or ""] = explicit_confirmation
                        contract.assert_step_expectation(confirmation_step.id, explicit_confirmation)
                        wrong_step = contract.step("wrong_session_rejected")
                        wrong = compatibility.decode_tool_result(
                            await session.call_tool(
                                wrong_step.tool or "",
                                contract.resolve_arguments(wrong_step.id, captures),
                            )
                        )
                        captures[wrong_step.capture or ""] = wrong
                        contract.assert_step_expectation(wrong_step.id, wrong)
                        after_wrong = authoritative_snapshot(fixture.save_path)
                        pending_after_wrong = optional_bytes(pending_path)
                        receipt_after_wrong = optional_bytes(receipt_path)
                        confirm_step = contract.step("player_confirm_committed")
                        confirmed = compatibility.decode_tool_result(
                            await session.call_tool(
                                confirm_step.tool or "",
                                contract.resolve_arguments(confirm_step.id, captures),
                            )
                        )
                        captures[confirm_step.capture or ""] = confirmed
                        contract.assert_step_expectation(confirm_step.id, confirmed)
                        after_confirm = authoritative_snapshot(fixture.save_path)
                        replay_step = contract.step("player_confirm_replayed")
                        replayed = compatibility.decode_tool_result(
                            await session.call_tool(
                                replay_step.tool or "",
                                contract.resolve_arguments(replay_step.id, captures),
                            )
                        )
                        captures[replay_step.capture or ""] = replayed
                        contract.assert_step_expectation(replay_step.id, replayed)
                        after_replay = authoritative_snapshot(fixture.save_path)

            self.assertFalse(stale["ok"], stale)
            self.assertEqual(after_stale, initial)
            self.assertIsNone(pending_after_stale)
            self.assertIsNone(receipt_after_stale)
            self.assertEqual(manifest_initial, manifest_refreshed)
            self.assertIsNot(stale_candidate, refreshed_candidate)
            self.assertTrue(turn["ok"], turn)
            self.assertTrue(turn["ready_to_confirm"], turn)
            self.assertFalse(turn["saved"], turn)
            self.assertEqual(turn["action"], "rest")
            self.assertNotIn("delta_draft", turn)
            self.assertNotIn("turn_proposal", turn)
            self.assertEqual(after_turn, initial)
            self.assertIsNotNone(pending_before_wrong)
            self.assertFalse(wrong["ok"], wrong)
            self.assertEqual(after_wrong, after_turn)
            self.assertEqual(pending_after_wrong, pending_before_wrong)
            self.assertIsNone(receipt_before_wrong)
            self.assertIsNone(receipt_after_wrong)
            self.assertTrue(confirmed["ok"], confirmed)
            self.assertTrue(confirmed["saved"], confirmed)
            self.assertEqual(confirmed["write_status"], "committed")
            self.assertFalse(confirmed["idempotent_replay"])
            self.assertEqual(after_confirm[0], initial[0] + 1)
            self.assertEqual(after_confirm[1], initial[1] + 1)
            self.assertNotEqual(after_confirm[2], initial[2])
            self.assertNotEqual(after_confirm[3], initial[3])
            self.assertNotEqual(after_confirm[4], initial[4])
            self.assertIsNone(optional_bytes(pending_path))
            self.assertIsNotNone(optional_bytes(receipt_path))
            self.assertTrue(replayed["ok"], replayed)
            self.assertFalse(replayed["saved"], replayed)
            self.assertEqual(replayed["write_status"], "already_confirmed")
            self.assertTrue(replayed["idempotent_replay"])
            self.assertEqual(after_replay, after_confirm)

            audit_records = [
                json.loads(line)
                for line in (fixture.root / "logs" / "aigm-mcp-audit.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            audit_text = json.dumps(audit_records, ensure_ascii=False, sort_keys=True)
            self.assertEqual(
                [record["tool"] for record in audit_records],
                [
                    "intent_manifest",
                    "player_turn",
                    "intent_manifest",
                    "player_turn",
                    "player_confirm",
                    "player_confirm",
                    "player_confirm",
                ],
            )
            for canary in (
                "wire-user-text-canary",
                "wire-hidden-slot-canary",
                "wire-private-reason-canary",
                "wire-private-body-canary",
                "wire-session-key-canary",
                "player_action:wrong-wire-canary",
                str(turn["session_id"]),
            ):
                self.assertNotIn(canary, audit_text)
            for result in (stale, wrong):
                result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
                for canary in (
                    "wire-user-text-canary",
                    "wire-hidden-slot-canary",
                    "wire-private-reason-canary",
                    "wire-private-body-canary",
                    "wire-session-key-canary",
                    "player_action:wrong-wire-canary",
                    str(turn["session_id"]),
                ):
                    self.assertNotIn(canary, result_text)
            stale_audit = audit_records[1]
            self.assertEqual(
                stale_audit["request"]["session_key"],
                f"sha256:{hash_identity('wire-session-key-canary')}",
            )
            self.assertTrue(stale_audit["request"]["external_intent_candidate"]["redacted"])
            self.assertEqual(
                [record["request"]["session_id"] for record in audit_records[4:]],
                [
                    f"sha256:{hash_identity('player_action:wrong-wire-canary')}",
                    f"sha256:{hash_identity(str(turn['session_id']))}",
                    f"sha256:{hash_identity(str(turn['session_id']))}",
                ],
            )

            hooks = {
                "manifest": contract.project_hook("manifest", manifest_initial),
                "candidate_rejection": contract.project_hook("candidate_rejection", stale),
                "player_turn": contract.project_hook("player_turn", turn),
                "explicit_player_confirmation": contract.project_hook(
                    "explicit_player_confirmation",
                    explicit_confirmation,
                ),
                "wrong_confirmation": contract.project_hook("wrong_confirmation", wrong),
                "player_confirm": contract.project_hook("player_confirm", confirmed),
                "player_replay": contract.project_hook("player_replay", replayed),
                "safe_audit": tuple(contract.project_hook("safe_audit", record) for record in audit_records),
            }
            for record in audit_records:
                contract.assert_step_expectation("safe_audit", record)
            hook_text = json.dumps(hooks, ensure_ascii=False, sort_keys=True)
            for canary in (
                "wire-user-text-canary",
                "wire-hidden-slot-canary",
                "wire-private-reason-canary",
                "wire-private-body-canary",
                "wire-session-key-canary",
                "player_action:wrong-wire-canary",
                str(turn["session_id"]),
            ):
                self.assertNotIn(canary, hook_text)
            self.assertTrue(hooks["player_turn"]["session_id_present"])
            self.assertTrue(hooks["explicit_player_confirmation"]["session_id_present"])
            self.assertTrue(hooks["player_confirm"]["turn_id_present"])
            self.assertFalse(fixture.network_attempts_path.exists())
            self.assertTrue(guard_ready(fixture)["loaded"])
            self.assertFalse(fixture.dotenv_attempts_path.exists())
            stderr.seek(0)
            self.assertNotIn("Failed to parse JSONRPC", stderr.read())
            self.assertEqual(
                compatibility.fingerprint_paths((fixture.campaign_path,)),
                campaign_before,
            )

        self.assertEqual(compatibility.fingerprint_paths(protected_paths), protected_before)

    async def test_real_stdio_normal_query_hides_temporary_gm_only_canaries(self) -> None:
        compatibility = compatibility_module()
        protected_paths = compatibility.default_protected_paths(ENGINE_ROOT)
        protected_before = compatibility.fingerprint_paths(protected_paths)
        self.addCleanup(
            lambda: self.assertEqual(
                compatibility.fingerprint_paths(protected_paths),
                protected_before,
            )
        )

        hidden_canaries = (
            "entity:wire-hidden-query-canary",
            "Wire Hidden Query Canary",
            "wire-hidden-summary-canary",
            "entity:wire-gm-only-query-canary",
            "Wire GM Only Query Canary",
            "wire-gm-only-summary-canary",
        )
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr:
            parent = Path(tmp)
            source = parent / "campaign-source"
            shutil.copytree(MINIMAL_FIXTURE, source)
            entities_path = source / "content" / "entities.yaml"
            entities = yaml.safe_load(entities_path.read_text(encoding="utf-8"))
            entities["entities"].extend(
                (
                    {
                        "id": hidden_canaries[0],
                        "type": "location",
                        "name": hidden_canaries[1],
                        "status": "active",
                        "visibility": "hidden",
                        "summary": hidden_canaries[2],
                    },
                    {
                        "id": hidden_canaries[3],
                        "type": "location",
                        "name": hidden_canaries[4],
                        "status": "active",
                        "visibility": "gm-only",
                        "summary": hidden_canaries[5],
                    },
                )
            )
            entities_path.write_text(
                yaml.safe_dump(entities, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            source_before = compatibility.fingerprint_paths((source,))
            fixture = compatibility.prepare_provider_fixture(
                parent / "provider-workspace",
                engine_root=ENGINE_ROOT,
                campaign_source=source,
                protected_paths=protected_paths,
            )
            campaign_before = compatibility.fingerprint_paths((fixture.campaign_path,))
            parameters = compatibility.stdio_server_parameters(fixture)
            initial = authoritative_snapshot(fixture.save_path)
            pending_path = fixture.root / ".aigm" / "pending-player-action.json"

            async with asyncio_timeout(15):
                async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        manifest = compatibility.decode_tool_result(
                            await session.call_tool("intent_manifest", {})
                        )
                        safety = manifest["safety_vocabulary"]
                        query_candidate = {
                            "contract": {
                                "manifest_schema_version": manifest["schema_version"],
                                "manifest_digest": manifest["manifest_digest"],
                                "safety_vocabulary_version": safety["version"],
                                "safety_vocabulary_digest": safety["digest"],
                            },
                            "kind": "query",
                            "mode": "query",
                            "action": "",
                            "slots": {
                                "query_kind": "scene",
                            },
                            "plan": [],
                            "confidence": "high",
                            "missing_slots": [],
                            "needs_confirmation": [],
                            "safety_flags": [],
                            "reason": "wire-hidden-query-reason-canary",
                        }
                        query = compatibility.decode_tool_result(
                            await session.call_tool(
                                "player_turn",
                                {
                                    "user_text": "查看周围",
                                    "external_intent_candidate": query_candidate,
                                },
                            )
                        )

            self.assertTrue(query["ok"], query)
            self.assertEqual(query["action"], "query")
            self.assertFalse(query["ready_to_confirm"], query)
            self.assertFalse(query["saved"], query)
            self.assertEqual(authoritative_snapshot(fixture.save_path), initial)
            self.assertIsNone(optional_bytes(pending_path))
            response_text = json.dumps(query, ensure_ascii=False, sort_keys=True)
            hook_text = json.dumps(
                compatibility.load_script_contract().project_hook("player_turn", query),
                ensure_ascii=False,
                sort_keys=True,
            )
            audit_text = (fixture.root / "logs" / "aigm-mcp-audit.jsonl").read_text(encoding="utf-8")
            stderr.seek(0)
            stderr_text = stderr.read()
            for canary in (*hidden_canaries, "wire-hidden-query-reason-canary"):
                self.assertNotIn(canary, response_text)
                self.assertNotIn(canary, hook_text)
                self.assertNotIn(canary, audit_text)
                self.assertNotIn(canary, stderr_text)
            self.assertEqual(compatibility.fingerprint_paths((source,)), source_before)
            self.assertEqual(
                compatibility.fingerprint_paths((fixture.campaign_path,)),
                campaign_before,
            )
            self.assertFalse(fixture.network_attempts_path.exists())
            self.assertTrue(guard_ready(fixture)["loaded"])
            self.assertFalse(fixture.dotenv_attempts_path.exists())
            self.assertNotIn("Failed to parse JSONRPC", stderr_text)

    async def test_stdio_exception_teardown_closes_child_and_preserves_protected_data(self) -> None:
        compatibility = compatibility_module()
        protected_paths = compatibility.default_protected_paths(ENGINE_ROOT)
        protected_before = compatibility.fingerprint_paths(protected_paths)
        self.addCleanup(
            lambda: self.assertEqual(
                compatibility.fingerprint_paths(protected_paths),
                protected_before,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "teardown-workspace"
            fixture = compatibility.prepare_provider_fixture(
                workspace,
                engine_root=ENGINE_ROOT,
                protected_paths=protected_paths,
            )
            campaign_before = compatibility.fingerprint_paths((fixture.campaign_path,))
            parameters = compatibility.stdio_server_parameters(fixture)
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr:
                with self.assertRaises(BaseExceptionGroup) as captured:
                    async with asyncio_timeout(15):
                        async with stdio_client(parameters, errlog=stderr) as (read_stream, write_stream):
                            async with ClientSession(read_stream, write_stream) as session:
                                await session.initialize()
                                child_pid = int(guard_ready(fixture)["pid"])
                                raise RuntimeError("intentional compatibility cancellation")

            exceptions = flattened_exceptions(captured.exception)
            self.assertEqual(len(exceptions), 1, exceptions)
            self.assertIsInstance(exceptions[0], RuntimeError)
            self.assertEqual(str(exceptions[0]), "intentional compatibility cancellation")
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertFalse(fixture.network_attempts_path.exists())
            self.assertTrue(guard_ready(fixture)["loaded"])
            self.assertFalse(fixture.dotenv_attempts_path.exists())
            self.assertEqual(compatibility.fingerprint_paths(protected_paths), protected_before)
            self.assertEqual(
                compatibility.fingerprint_paths((fixture.campaign_path,)),
                campaign_before,
            )
        self.assertFalse(workspace.exists())


def asyncio_timeout(seconds: float):
    import asyncio

    return asyncio.timeout(seconds)


if __name__ == "__main__":
    unittest.main()
