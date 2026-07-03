from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rpg_engine.resource_paths import resource_file


ENGINE_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ENGINE_ROOT / "examples" / "v1_minimal_adventure"


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


def clock_progress(save_dir: Path, clock_id: str) -> tuple[int, int]:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    try:
        row = conn.execute(
            "select segments_filled, segments_total from clocks where entity_id = ?",
            (clock_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return (0, 0)
    return int(row[0]), int(row[1])


class OfficialExampleTests(unittest.TestCase):
    def test_packaged_resources_match_public_specs_and_example(self) -> None:
        for source in sorted((ENGINE_ROOT / "schemas").glob("*.json")):
            with self.subTest(schema=source.name):
                packaged = resource_file("schemas", source.name).read_text(encoding="utf-8")
                self.assertEqual(packaged, source.read_text(encoding="utf-8"))

        for source in sorted(EXAMPLE.rglob("*")):
            if not source.is_file():
                continue
            rel = source.relative_to(EXAMPLE)
            with self.subTest(example=str(rel)):
                packaged = resource_file("examples", "v1_minimal_adventure", *rel.parts).read_text(encoding="utf-8")
                self.assertEqual(packaged, source.read_text(encoding="utf-8"))

    def test_official_example_validates_tests_and_runs_minimal_gameplay_loop(self) -> None:
        validate = load_stdout_json(run_cli("campaign", "validate", EXAMPLE, "--format", "json"))
        smoke = load_stdout_json(run_cli("campaign", "test", EXAMPLE, "--format", "json"))

        self.assertTrue(validate["ok"], validate)
        self.assertEqual(
            validate["capabilities"],
            [
                "query",
                "explore",
                "social",
                "travel",
                "clock",
                "random_table",
                "clue",
                "risk",
                "inventory_resource",
                "project_task",
                "rest_time",
                "trade_exchange",
                "gather_search",
            ],
        )
        self.assertTrue(smoke["ok"], smoke)
        self.assertEqual(len(smoke["smoke_results"]), 12)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            delta_path = root / "delta.json"
            proposal_path = root / "proposal.json"
            run_cli("save", "init", EXAMPLE, save_dir, "--format", "json")

            scene = load_stdout_json(run_cli("play", "query", save_dir, "scene", "--format", "json"))
            preview = load_stdout_json(
                run_cli(
                    "play",
                    "preview",
                    save_dir,
                    "explore",
                    "--target",
                    "Broken Seal Mark",
                    "--approach",
                    "careful visual inspection",
                    "--user-text",
                    "Inspect the broken bridge seal",
                    "--format",
                    "json",
                )
            )
            delta = {
                "expected_turn_id": "turn:seed",
                "command_id": "official-example-explore",
                "user_text": "Inspect the broken bridge seal",
                "intent": "explore",
                "changed": True,
                "summary": "The bridge seal is confirmed as recently chipped.",
                "location_before": "loc:watch-camp",
                "location_after": "loc:watch-camp",
                "events": [
                    {
                        "type": "explore",
                        "title": "Broken seal confirmed",
                        "summary": "A careful inspection confirms fresh tool marks on the bridge seal.",
                        "payload": {
                            "target_id": "ref:broken-seal",
                            "clue_stage": "confirmed",
                        },
                        "source": "official_example_test",
                    }
                ],
                "upsert_entities": [
                    {
                        "id": "ref:broken-seal",
                        "type": "reference",
                        "name": "Broken Seal Mark",
                        "status": "active",
                        "visibility": "known",
                        "location_id": "loc:old-bridge",
                        "summary": "Fresh tool marks confirm the bridge seal was deliberately chipped.",
                        "aliases": ["seal mark", "bridge clue"],
                        "details": {
                            "gameplay_role": "clue",
                            "clue_stage": "confirmed",
                            "leads_to": ["ref:tower-signal-code"],
                        },
                    }
                ],
                "tick_clocks": [
                    {
                        "id": "clock:storm-front",
                        "delta": 1,
                        "reason": "time spent inspecting bridge risk",
                    }
                ],
            }
            proposal = dict(preview["turn_proposal"])
            proposal["proposal_id"] = "proposal:official-example-explore"
            proposal["delta"] = delta
            proposal["delta_source"] = "human_edited"
            proposal["human_confirmed"] = True
            proposal["provenance"] = {"source": "official_example_test", "preview": proposal.get("proposal_id")}
            delta_path.write_text(json.dumps(delta, ensure_ascii=False) + "\n", encoding="utf-8")
            proposal_path.write_text(json.dumps(proposal, ensure_ascii=False) + "\n", encoding="utf-8")

            validation = run_cli("validate", "delta", save_dir, delta_path)
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
            clue = load_stdout_json(
                run_cli("play", "query", save_dir, "entity", "Broken Seal Mark", "--format", "json")
            )
            context = load_stdout_json(
                run_cli(
                    "play",
                    "query",
                    save_dir,
                    "context",
                    "What did the seal inspection prove?",
                    "--format",
                    "json",
                )
            )
            relationship = load_stdout_json(
                run_cli("play", "query", save_dir, "entity", "Mira relationship", "--format", "json")
            )

            self.assertIn("Watch Camp", scene["text"])
            self.assertTrue(preview["ok"], preview)
            self.assertIn("Delta 草案", preview["markdown"])
            self.assertEqual(validation.stdout.strip(), "OK")
            self.assertEqual(commit["turn_id"], "turn:000001")
            self.assertEqual(clock_progress(save_dir, "clock:storm-front"), (1, 4))
            self.assertIn("deliberately chipped", clue["text"])
            self.assertIn("deliberately chipped", context["text"])
            self.assertIn("careful proof", relationship["text"])


if __name__ == "__main__":
    unittest.main()
