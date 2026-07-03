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


class AuthorKitDoctorTests(unittest.TestCase):
    def test_doctor_ok_for_generated_small_cn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "small-cn", "--format", "json")

            result = load_json(run_cli("campaign", "doctor", target, "--format", "json"))

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["summary"]["errors"], 0)

    def test_doctor_reports_validation_error_with_repair_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "blank", "--format", "json")
            manifest_path = target / "campaign.yaml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest["initial_location_id"] = "loc:missing"
            manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

            result = load_json(run_cli("campaign", "doctor", target, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertGreater(result["summary"]["errors"], 0)
            self.assertTrue(any(issue["repair_options"] for issue in result["issues"]))

    def test_doctor_detects_save_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign"
            save = root / "save"
            run_cli("campaign", "new", campaign, "--template", "blank", "--format", "json")
            run_cli("save", "init", campaign, save, "--format", "json")

            result = load_json(run_cli("campaign", "doctor", save, "--format", "json", check=False))

            self.assertFalse(result["ok"])
            self.assertEqual(result["issues"][0]["code"], "SAVE_PACKAGE_PASSED_TO_CAMPAIGN_DOCTOR")

    def test_doctor_warns_generated_dirs_and_strict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "blank", "--format", "json")
            (target / "cards").mkdir()

            normal = load_json(run_cli("campaign", "doctor", target, "--format", "json"))
            strict = load_json(run_cli("campaign", "doctor", target, "--strict", "--format", "json", check=False))

            self.assertTrue(normal["ok"], normal)
            self.assertFalse(strict["ok"], strict)
            self.assertIn("GENERATED_PATH_IN_CAMPAIGN", {issue["code"] for issue in strict["issues"]})

    def test_check_ai_reports_hidden_leak_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "story"
            run_cli("campaign", "new", target, "--template", "blank", "--format", "json")
            entities_path = target / "content" / "entities.yaml"
            data = yaml.safe_load(entities_path.read_text(encoding="utf-8"))
            data["entities"][0]["summary"] = "这里包含隐藏线索。"
            entities_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

            result = load_json(run_cli("campaign", "check-ai", target, "--format", "json"))

            self.assertTrue(any(issue["code"] == "POSSIBLE_HIDDEN_LEAK_IN_SUMMARY" for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
