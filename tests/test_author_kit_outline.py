from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ENGINE_ROOT = Path(__file__).resolve().parents[1]


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


class AuthorKitOutlineTests(unittest.TestCase):
    def test_outline_markdown_contains_start_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "small-cn", "--format", "json")

            result = run_cli("campaign", "outline", target)

            self.assertIn("## Start", result.stdout)
            self.assertIn("## Content Counts", result.stdout)
            self.assertIn("河道巡查营地", result.stdout)

    def test_outline_json_has_counts_and_smoke_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "small-cn", "--format", "json")

            result = load_json(run_cli("campaign", "outline", target, "--format", "json"))

            self.assertEqual(result["counts"]["location"], 3)
            self.assertTrue(result["smoke_coverage"]["query"])
            self.assertTrue(result["smoke_coverage"]["travel"])

    def test_outline_does_not_expand_hidden_summary_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "small-cn", "--format", "json")
            hidden_path = target / "content" / "characters.yaml"
            data = yaml.safe_load(hidden_path.read_text(encoding="utf-8"))
            data["entities"].append(
                {
                    "id": "npc:hidden-witness",
                    "type": "character",
                    "name": "隐藏证人",
                    "status": "active",
                    "visibility": "hidden",
                    "location_id": "loc:camp",
                    "summary": "不能在 author 默认 outline 展开的隐藏证词。",
                    "character": {"role": "witness", "health_state": "unknown"},
                }
            )
            hidden_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

            result = run_cli("campaign", "outline", target)

            self.assertIn("npc:hidden-witness", result.stdout)
            self.assertNotIn("不能在 author 默认 outline 展开的隐藏证词", result.stdout)


if __name__ == "__main__":
    unittest.main()
