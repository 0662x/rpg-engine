from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
SMALL_CN = ENGINE_ROOT / "examples" / "small_cn_campaign"
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


class BugReportRegressionTests(unittest.TestCase):
    def test_context_build_external_contract_failure_is_safe_and_does_not_audit(self) -> None:
        sentinel = "secret-context-safety-token"
        user_text = "secret-context-user-request"
        base = {
            "kind": "single",
            "mode": "query",
            "action": "query",
            "slots": {},
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [sentinel],
            "reason": "test legacy context boundary",
        }
        cases = {
            "unknown": (
                base,
                {
                    "code": "UNKNOWN_INTENT_SAFETY_FLAG",
                    "reason": "unknown_safety_flag",
                    "retriable": False,
                    "action": "regenerate_candidate",
                    "path": "$.safety_flags",
                    "message": "External intent candidate contains unsupported safety flags.",
                    "count": 1,
                },
            ),
            "mismatch": (
                {
                    **base,
                    "contract": {
                        "manifest_schema_version": "1",
                        "manifest_digest": "0" * 64,
                        "safety_vocabulary_version": "1",
                        "safety_vocabulary_digest": "0" * 64,
                    },
                },
                {
                    "code": "INTENT_CONTRACT_VERSION_MISMATCH",
                    "reason": "contract_version_mismatch",
                    "retriable": True,
                    "action": "refresh_manifest_and_regenerate_candidate",
                    "path": "$.contract",
                    "message": "External intent contract does not match the current provider.",
                },
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            shutil.copytree(MINIMAL_FIXTURE, Path(tmp) / "source")
            run_cli("save", "init", Path(tmp) / "source", save_dir, "--format", "json")
            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                counts_before = {
                    table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                    for table in ("facts", "events", "turns", "context_runs")
                }
            finally:
                conn.close()

            for case, (candidate_value, expected_detail) in cases.items():
                candidate = json.dumps(candidate_value)
                json_result = run_cli(
                    "context",
                    "build",
                    save_dir,
                    "--user-text",
                    user_text,
                    "--external-intent-candidate",
                    candidate,
                    "--format",
                    "json",
                    check=False,
                )
                human_result = run_cli(
                    "context",
                    "build",
                    save_dir,
                    "--user-text",
                    user_text,
                    "--external-intent-candidate",
                    candidate,
                    check=False,
                )

                with self.subTest(case=case):
                    data = json.loads(json_result.stdout)
                    self.assertEqual(json_result.returncode, 1)
                    self.assertEqual(data["ok"], False)
                    self.assertEqual(data["error_details"], [expected_detail])
                    self.assertEqual(human_result.returncode, 1)
                    self.assertIn("FAILED", human_result.stdout)
                    self.assertIn(str(expected_detail["action"]), human_result.stdout)
                    for result in (json_result, human_result):
                        combined = result.stdout + result.stderr
                        self.assertNotIn(sentinel, combined)
                        self.assertNotIn(user_text, combined)
                        self.assertNotIn("Traceback", combined)

            conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
            try:
                counts_after = {
                    table: conn.execute(f"select count(*) from {table}").fetchone()[0]
                    for table in counts_before
                }
            finally:
                conn.close()
            self.assertEqual(counts_after, counts_before)

    def test_user_text_file_handles_chinese_punctuation_next_to_ascii_tokens(self) -> None:
        user_text = "让夏娃启动菌丝从L7泉眼引水自动灌溉十六畦农田。派腐工蕈去菌丝复合屋取小杂鱼和溪虾，送到厨房做成菜"
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            user_text_path = Path(tmp) / "user-text.txt"
            user_text_path.write_text(user_text + "\n", encoding="utf-8")
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            start = run_cli(
                "play",
                "start-turn",
                save_dir,
                "--user-text-file",
                user_text_path,
                "--mode",
                "query",
                "--submode",
                "scene",
                "--format",
                "json",
            )
            context = run_cli(
                "context",
                "build",
                save_dir,
                "--user-text-file",
                user_text_path,
                "--mode",
                "query",
                "--submode",
                "scene",
                "--format",
                "json",
            )

        start_data = json.loads(start.stdout)
        context_data = json.loads(context.stdout)
        self.assertEqual(start_data["user_text"], user_text)
        self.assertEqual(start_data["context"]["request"]["user_text"], user_text)
        self.assertEqual(context_data["request"]["user_text"], user_text)

    def test_delta_draft_does_not_flag_sleep_or_consumption_words_as_high_risk_noise(self) -> None:
        response = "\n".join(
            [
                "## 场景",
                "你在营火旁短暂睡了一会儿。",
                "## 你的状态",
                "| 项目 | 当前 |",
                "|------|------|",
                "| 位置 | 营地 |",
                "## 行动结果",
                "这次休息不消耗额外资源，也没有改变任何状态。",
                "## 状态变化",
                "| 类型 | 变化 |",
                "|------|------|",
                "| 无 | 无 |",
                "## 可选行动",
                "| # | 行动 | 预计耗时 | 风险/代价 |",
                "|---|------|----------|-----------|",
                "| 1 | 继续守夜 | 10分钟 | 低 |",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            response_path = Path(tmp) / "response.md"
            response_path.write_text(response, encoding="utf-8")
            run_cli("save", "init", SMALL_CN, save_dir, "--format", "json")

            result = run_cli(
                "delta",
                "draft",
                save_dir,
                "--user-text",
                "短睡一下，不消耗资源",
                "--response-file",
                response_path,
            )

        self.assertNotIn("高风险词命中：睡", result.stdout)
        self.assertNotIn("高风险词命中：消耗", result.stdout)


if __name__ == "__main__":
    unittest.main()
