from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


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


class SavePatchTests(unittest.TestCase):
    def test_save_patch_applies_safe_maintenance_without_advancing_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            patch_path = root / "patch.json"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            before = current_turn(save_dir)
            patch_path.write_text(
                json.dumps(
                    {
                        "patch_schema_version": "1",
                        "reason": "maintenance test",
                        "operations": [
                            {
                                "op": "set_entity_summary",
                                "entity_id": "pc:traveler",
                                "summary": "A patched traveler summary.",
                            },
                            {"op": "add_entity_alias", "entity_id": "pc:traveler", "alias": "patched traveler"},
                            {
                                "op": "set_character_field",
                                "entity_id": "pc:traveler",
                                "field": "attitude",
                                "value": "ready",
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = load_stdout_json(run_cli("save", "patch", save_dir, patch_path, "--format", "json"))
            query = load_stdout_json(
                run_cli("play", "query", save_dir, "entity", "patched traveler", "--format", "json")
            )
            inspect = load_stdout_json(run_cli("save", "inspect", save_dir, "--format", "json"))

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["operations_applied"], 3)
            self.assertEqual(result["touched_entities"], ["pc:traveler"])
            self.assertEqual(current_turn(save_dir), before)
            self.assertEqual(inspect["current_turn_id"], before)
            self.assertIn("A patched traveler summary.", query["text"])
            self.assertIn("ready", query["text"])

    def test_save_patch_rejects_story_progression_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            patch_path = root / "bad-patch.json"
            run_cli("save", "init", MINIMAL_FIXTURE, save_dir, "--format", "json")
            patch_path.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "op": "set_entity_detail",
                                "entity_id": "pc:traveler",
                                "key": "current_turn_id",
                                "value": "turn:999999",
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = run_cli("save", "patch", save_dir, patch_path, "--format", "json", check=False)
            data = load_stdout_json(result)

            self.assertEqual(result.returncode, 1)
            self.assertFalse(data["ok"])
            self.assertIn("protected gameplay field", "\n".join(data["errors"]))
            self.assertEqual(current_turn(save_dir), "turn:seed")


if __name__ == "__main__":
    unittest.main()
