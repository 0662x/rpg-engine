from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rpg_engine.db import connect, upsert_entity
from rpg_engine.runtime import GMRuntime


ENGINE_ROOT = Path(__file__).resolve().parents[1]
SMALL_CN = ENGINE_ROOT / "examples" / "small_cn_campaign"


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def load_json(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


class PaletteGovernanceTests(unittest.TestCase):
    def test_small_cn_palette_content_validates_and_appears_in_context(self) -> None:
        validation = load_json(run_cli("campaign", "validate", SMALL_CN, "--format", "json"))
        self.assertTrue(validation["ok"], validation)
        self.assertIn("gather_search", validation["capabilities"])
        self.assertEqual(validation["warnings"], [])

        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            suggestions = run_cli(
                "palette",
                "suggest",
                save_dir,
                "--kind",
                "material",
                "--location",
                "loc:camp",
                "--intent",
                "gather",
            )
            self.assertIn("pal:mat:moon-herb-fresh", suggestions.stdout)
            self.assertIn("pal:mat:silver-moon-herb", suggestions.stdout)

            context = load_json(
                run_cli(
                    "play",
                    "start-turn",
                    save_dir,
                    "--user-text",
                    "在营地附近找草药",
                    "--submode",
                    "gather",
                    "--format",
                    "json",
                )
            )
            self.assertIn("palette_candidates", context["context"]["sections"])
            self.assertGreaterEqual(context["context"]["budget"]["limit"], 5500)
            self.assertEqual(context["context"]["budget"]["policy_profile"], "action_gather_discovery")

    def test_gather_palette_candidate_preview_validate_commit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "delta.json"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            preview = load_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "gather",
                    "--palette-id",
                    "pal:mat:moon-herb-fresh",
                    "--user-text",
                    "采一点新鲜月白草",
                    "--format",
                    "json",
                )
            )
            self.assertTrue(preview["ok"], preview)
            delta = preview["delta_draft"]
            self.assertEqual(delta["events"][0]["payload"]["palette_id"], "pal:mat:moon-herb-fresh")
            delta_path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")

            validation = load_json(run_cli("play", "validate-delta", save_dir, delta_path, "--format", "json"))
            self.assertTrue(validation["ok"], validation)

    def test_clue_only_palette_explore_does_not_create_entity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            preview = load_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "explore",
                    "--palette-id",
                    "pal:faction:bridge-wardens",
                    "--location",
                    "loc:old-bridge",
                    "--approach",
                    "谨慎观察刻痕",
                    "--format",
                    "json",
                )
            )
            self.assertTrue(preview["ok"], preview)
            delta = preview["delta_draft"]
            self.assertEqual(delta["events"][0]["payload"]["palette_status"], "clue_only")
            self.assertEqual(delta["upsert_entities"], [])

    def test_trusted_explore_palette_preview_preserves_hidden_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")
            runtime = GMRuntime.from_path(save_dir)
            runtime.campaign.config.setdefault("capabilities", []).append("explore")
            with connect(runtime.campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "faction:bridge-wardens",
                        "type": "faction_state",
                        "name": "旧桥守路人",
                        "summary": "GM-only faction identity.",
                        "visibility": "hidden",
                    },
                )
                conn.commit()

            options = {"palette_id": "pal:faction:bridge-wardens", "location": "loc:old-bridge"}
            player = runtime.preview_action("explore", options, context={"view": "player"})
            gm = runtime.preview_action("explore", options, context={"view": "gm"})
            player_text = json.dumps(player.to_dict(), ensure_ascii=False, sort_keys=True)
            gm_text = json.dumps(gm.to_dict(), ensure_ascii=False, sort_keys=True)

            self.assertTrue(gm.ready_to_save, gm.to_dict())
            self.assertNotIn("faction:bridge-wardens", player_text)
            self.assertNotIn("旧桥守路人", player_text)
            self.assertIn("faction:bridge-wardens", gm_text)
            self.assertIn("旧桥守路人", gm_text)

    def test_trusted_palette_action_previews_preserve_hidden_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")
            runtime = GMRuntime.from_path(save_dir)
            runtime.campaign.config.setdefault("capabilities", []).extend(["gather", "craft", "travel", "social"])
            hidden_entities = [
                {
                    "id": "mat:silver-moon-herb",
                    "type": "material",
                    "name": "银边月白草",
                    "summary": "GM-only material candidate.",
                    "visibility": "hidden",
                },
                {
                    "id": "loc:under-bridge-bank",
                    "type": "location",
                    "name": "桥下碎石滩",
                    "summary": "GM-only location candidate.",
                    "visibility": "hidden",
                },
                {
                    "id": "faction:bridge-wardens",
                    "type": "faction_state",
                    "name": "旧桥守路人",
                    "summary": "GM-only faction identity.",
                    "visibility": "hidden",
                },
            ]
            with connect(runtime.campaign) as conn:
                for entity in hidden_entities:
                    upsert_entity(conn, entity)
                conn.commit()

            cases = [
                ("gather", {"palette_id": "pal:mat:silver-moon-herb", "location": "loc:camp"}, "mat:silver-moon-herb", "银边月白草"),
                ("craft", {"palette_id": "pal:mat:silver-moon-herb", "target": "草药包"}, "mat:silver-moon-herb", "银边月白草"),
                ("travel", {"palette_id": "pal:loc:under-bridge-bank", "location": "loc:old-bridge"}, "loc:under-bridge-bank", "桥下碎石滩"),
                (
                    "social",
                    {"palette_id": "pal:faction:bridge-wardens", "npc": "npc:guide-lin", "topic": "旧桥刻痕"},
                    "faction:bridge-wardens",
                    "旧桥守路人",
                ),
            ]
            for action, options, hidden_id, hidden_name in cases:
                with self.subTest(action=action):
                    player = runtime.preview_action(action, options, context={"view": "player"})
                    gm = runtime.preview_action(action, options, context={"view": "gm"})
                    player_text = json.dumps(player.to_dict(), ensure_ascii=False, sort_keys=True)
                    gm_text = json.dumps(gm.to_dict(), ensure_ascii=False, sort_keys=True)

                    self.assertNotIn(hidden_id, player_text)
                    self.assertNotIn(hidden_name, player_text)
                    self.assertIn(hidden_id, gm_text)
                    self.assertIn(hidden_name, gm_text)

    def test_travel_palette_candidate_records_discovery_without_route_or_location_fact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "travel-lead.json"
            proposal_path = root / "travel-lead-proposal.json"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            preview = load_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "travel",
                    "--palette-id",
                    "pal:loc:reed-bend",
                    "--user-text",
                    "沿着泥路找去芦苇河湾的路",
                    "--format",
                    "json",
                )
            )
            self.assertTrue(preview["ok"], preview)
            delta = preview["delta_draft"]
            self.assertEqual(delta["location_after"], "loc:camp")
            self.assertEqual(delta["upsert_entities"], [])
            self.assertEqual(delta["events"][0]["payload"]["palette_kind"], "location")
            delta_path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")
            proposal_path.write_text(json.dumps(preview["turn_proposal"], ensure_ascii=False), encoding="utf-8")

            validation = load_json(run_cli("play", "validate-delta", save_dir, delta_path, "--format", "json"))
            self.assertTrue(validation["ok"], validation)
            committed = load_json(
                run_cli(
                    "play",
                    "commit",
                    save_dir,
                    delta_path,
                    "--proposal-json",
                    proposal_path,
                    "--no-backup",
                    "--archivist-suggest",
                    "--format",
                    "json",
                )
            )
            self.assertEqual(committed["archivist_suggestion_id"], f"archivist:{committed['turn_id'].replace(':', '-')}")
            self.assertGreaterEqual(len(committed["archivist_proposal_ids"]), 1)

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                count = conn.execute(
                    "select count(*) from discovery_states where palette_id='pal:loc:reed-bend' and stage='clue'"
                ).fetchone()[0]
                route_count = conn.execute("select count(*) from routes where id like '%reed-bend%'").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)
            self.assertEqual(route_count, 0)

            context = load_json(
                run_cli(
                    "play",
                    "start-turn",
                    save_dir,
                    "--user-text",
                    "继续查芦苇河湾的线索",
                    "--submode",
                    "explore",
                    "--format",
                    "json",
                    check=False,
                )
            )
            self.assertIn("discovery_states", context["context"]["sections"])
            self.assertIn("pal:loc:reed-bend", context["context"]["sections"]["discovery_states"])

    def test_craft_palette_candidate_creates_plan_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "craft-plan.json"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            preview = load_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "craft",
                    "--palette-id",
                    "pal:mat:moon-herb-fresh",
                    "--target",
                    "草药包",
                    "--time",
                    "30m",
                    "--format",
                    "json",
                )
            )
            self.assertTrue(preview["ok"], preview)
            delta = preview["delta_draft"]
            self.assertEqual(delta["events"][0]["payload"]["palette_id"], "pal:mat:moon-herb-fresh")
            self.assertTrue(delta["events"][0]["payload"]["material_consumption_required"])
            self.assertEqual(delta["upsert_entities"], [])
            delta_path.write_text(json.dumps(delta, ensure_ascii=False), encoding="utf-8")

            validation = load_json(run_cli("play", "validate-delta", save_dir, delta_path, "--format", "json"))
            self.assertTrue(validation["ok"], validation)

    def test_content_from_palette_marks_review_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            draft_path = Path(tmp) / "draft.json"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")
            run_cli(
                "content",
                "from-palette",
                save_dir,
                "pal:faction:bridge-wardens",
                "--output",
                draft_path,
            )

            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(draft["source"], "content_factory_from_palette")
            self.assertTrue(draft["meta"]["review_required"])
            self.assertEqual(draft["upsert_entities"][0]["visibility"], "hinted")

            validation = run_cli("content", "validate-delta", save_dir, draft_path)
            self.assertIn("warning:", validation.stdout)
            self.assertIn("high-impact faction", validation.stdout)

    def test_strict_review_blocks_and_queues_high_impact_content_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            draft_path = Path(tmp) / "draft.json"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")
            run_cli(
                "content",
                "from-palette",
                save_dir,
                "pal:faction:bridge-wardens",
                "--output",
                draft_path,
            )

            blocked = run_cli("apply-content-delta", save_dir, draft_path, "--strict-review", check=False)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("queued: proposal:000001", blocked.stdout)

            proposals = load_json(run_cli("proposal", "list", save_dir, "--format", "json"))
            self.assertEqual(proposals["proposals"][0]["status"], "needs_review")
            self.assertEqual(proposals["proposals"][0]["risk_level"], "high")
            proposal_id = proposals["proposals"][0]["id"]

            report = load_json(run_cli("proposal", "report", save_dir, "--format", "json"))
            self.assertEqual(report["by_status"]["needs_review"], 1)

            reviewed = load_json(
                run_cli(
                    "proposal",
                    "review",
                    save_dir,
                    proposal_id,
                    "--approve",
                    "--reviewed-by",
                    "test-reviewer",
                    "--reason",
                    "人工核对通过",
                    "--format",
                    "json",
                )
            )
            self.assertEqual(reviewed["status"], "approved")
            self.assertEqual(reviewed["review_reason"], "人工核对通过")
            applied = load_json(run_cli("proposal", "apply", save_dir, proposal_id, "--format", "json"))
            self.assertEqual(applied["proposal"]["status"], "applied")
            self.assertIn("backup_id", applied["proposal"]["rollback_hint"])
            rollback = run_cli("proposal", "rollback-plan", save_dir, proposal_id)
            self.assertIn("Proposal Rollback Plan", rollback.stdout)
            self.assertIn(applied["backup"], rollback.stdout)

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                faction_count = conn.execute(
                    "select count(*) from entities where id='faction:bridge-wardens'"
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(faction_count, 1)

    def test_proposal_queue_batch_review_and_rejection_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            proposal_a = root / "proposal-a.json"
            proposal_b = root / "proposal-b.json"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")
            proposal_a.write_text(json.dumps({"summary": "候选记忆 A", "advisory": True}, ensure_ascii=False), encoding="utf-8")
            proposal_b.write_text(json.dumps({"summary": "候选记忆 B", "advisory": True}, ensure_ascii=False), encoding="utf-8")
            run_cli("proposal", "create", save_dir, proposal_a, "--kind", "memory_update", "--format", "json")
            run_cli("proposal", "create", save_dir, proposal_b, "--kind", "memory_update", "--format", "json")

            reviewed = load_json(
                run_cli(
                    "proposal",
                    "batch-review",
                    save_dir,
                    "--status",
                    "draft",
                    "--kind",
                    "memory_update",
                    "--reject",
                    "--reviewed-by",
                    "test-reviewer",
                    "--reason",
                    "证据不足",
                    "--format",
                    "json",
                )
            )
            self.assertEqual(reviewed["count"], 2)
            self.assertEqual({item["status"] for item in reviewed["reviewed"]}, {"rejected"})
            self.assertEqual({item["review_reason"] for item in reviewed["reviewed"]}, {"证据不足"})

            report = load_json(run_cli("proposal", "report", save_dir, "--format", "json"))
            self.assertEqual(report["by_status"]["rejected"], 2)

    def test_chinese_natural_input_prefers_gather_for_resource_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")
            gather = load_json(run_cli("play", "act", save_dir, "找草药", "--format", "json", check=False))
            self.assertEqual(gather["interpretation"]["action"], "gather")

            craft = load_json(run_cli("play", "act", save_dir, "做个草药包", "--format", "json", check=False))
            self.assertEqual(craft["interpretation"]["action"], "craft")


if __name__ == "__main__":
    unittest.main()
