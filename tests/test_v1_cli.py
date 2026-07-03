from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from argparse import Namespace
from pathlib import Path

import yaml

from rpg_engine.cli_v1 import (
    intent_option_kwargs_from_args,
    intent_preflight_kwargs_from_args,
    intent_preview_kwargs_from_args,
    preflight_consume_kwargs_from_args,
)


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

    def test_save_init_inspect_validate_export_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            imported_dir = root / "imported"
            archive_path = root / "run.aigmsave"

            init = load_stdout_json(run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json"))
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
            save_manifest = yaml.safe_load((save_dir / "save.yaml").read_text(encoding="utf-8"))
            save_campaign = yaml.safe_load((save_dir / "campaign.yaml").read_text(encoding="utf-8"))
            self.assertFalse(Path(save_manifest["source_campaign_path"]).is_absolute())
            for values in save_campaign["content"].values():
                paths = values if isinstance(values, list) else [values]
                self.assertTrue(all(not Path(path).is_absolute() for path in paths))
            self.assertEqual(inspect["current_turn_id"], "turn:seed")
            self.assertEqual(validate.stdout.strip(), "OK")
            self.assertEqual(export["archive_path"], str(archive_path))
            self.assertTrue(str(default_export["archive_path"]).endswith(".aigmsave"))
            self.assertTrue(imported["ok"], imported)
            self.assertTrue(imported_inspect["ok"], imported_inspect)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("save.yaml", archive.namelist())

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

            dirty = load_stdout_json(run_cli("save", "validate", dirty_save, "--format", "json", check=False))
            event_drift = load_stdout_json(run_cli("save", "validate", event_save, "--format", "json", check=False))
            repair = run_cli("projection", "repair", event_save, "--name", "events_jsonl", "--all")
            event_repaired = run_cli("save", "validate", event_save)

            self.assertFalse(dirty["ok"])
            self.assertIn("PROJECTION_INCONSISTENT", {item["code"] for item in dirty["error_details"]})
            self.assertFalse(event_drift["ok"])
            self.assertIn("EVENT_LOG_INCONSISTENT", {item["code"] for item in event_drift["error_details"]})
            self.assertIn("refreshed: events_jsonl", repair.stdout)
            self.assertEqual(event_repaired.stdout.strip(), "OK")

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
