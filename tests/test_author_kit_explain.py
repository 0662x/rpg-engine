from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


class AuthorKitExplainTests(unittest.TestCase):
    def test_explain_visibility(self) -> None:
        result = run_cli("campaign", "explain", "field:visibility")

        self.assertIn("known", result.stdout)
        self.assertIn("hidden", result.stdout)

    def test_explain_unknown_key_lists_candidates(self) -> None:
        result = load_json(run_cli("campaign", "explain", "field:nope", "--format", "json", check=False))

        self.assertFalse(result["ok"])
        self.assertIn("field:visibility", result["candidates"])

    def test_split_dry_run_reports_moves_for_blank_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "blank"
            run_cli("campaign", "new", target, "--template", "blank", "--format", "json")

            result = load_json(run_cli("campaign", "split", target, "--format", "json"))

            self.assertTrue(result["ok"], result)
            self.assertTrue(result["dry_run"])
            self.assertTrue(result["moves"])


if __name__ == "__main__":
    unittest.main()
