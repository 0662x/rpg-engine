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


class AuthorKitNewTests(unittest.TestCase):
    def test_campaign_new_creates_valid_small_cn_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"

            created = load_json(run_cli("campaign", "new", target, "--template", "small-cn", "--format", "json"))
            validation = load_json(run_cli("campaign", "validate", target, "--format", "json"))
            smoke = load_json(run_cli("campaign", "test", target, "--format", "json"))

            self.assertTrue(created["ok"], created)
            self.assertEqual(created["template"], "small_cn_campaign")
            self.assertTrue((target / "AUTHOR_AI_PROMPT.md").exists())
            self.assertTrue(validation["ok"], validation)
            self.assertTrue(smoke["ok"], smoke)

    def test_campaign_new_creates_valid_blank_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "blank"

            created = load_json(run_cli("campaign", "new", target, "--template", "blank", "--format", "json"))
            validation = load_json(run_cli("campaign", "validate", target, "--format", "json"))

            self.assertTrue(created["ok"], created)
            self.assertTrue(validation["ok"], validation)
            self.assertEqual(validation["capabilities"], ["query", "rest_time"])

    def test_campaign_new_overrides_id_and_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "custom"

            created = load_json(
                run_cli(
                    "campaign",
                    "new",
                    target,
                    "--template",
                    "blank",
                    "--id",
                    "my-story",
                    "--name",
                    "My Story",
                    "--format",
                    "json",
                )
            )
            manifest = yaml.safe_load((target / "campaign.yaml").read_text(encoding="utf-8"))

            self.assertTrue(created["ok"], created)
            self.assertEqual(manifest["id"], "my-story")
            self.assertEqual(manifest["name"], "My Story")

    def test_campaign_new_rejects_non_empty_target_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "note.txt").write_text("existing\n", encoding="utf-8")

            blocked = load_json(
                run_cli("campaign", "new", target, "--template", "blank", "--format", "json", check=False)
            )
            forced = load_json(
                run_cli("campaign", "new", target, "--template", "blank", "--force", "--format", "json")
            )

            self.assertFalse(blocked["ok"], blocked)
            self.assertTrue(forced["ok"], forced)
            self.assertTrue((target / "campaign.yaml").exists())


if __name__ == "__main__":
    unittest.main()
