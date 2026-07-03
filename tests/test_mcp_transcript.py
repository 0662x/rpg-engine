from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from rpg_engine.mcp_transcript import normalize_mcp_tool_name, validate_external_agent_transcript


ENGINE_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "mcp_external_agent_transcripts.yaml"


class MCPTranscriptTests(unittest.TestCase):
    def test_external_agent_transcript_fixture_matches_expected_findings(self) -> None:
        transcripts = yaml.safe_load(TRANSCRIPT_FIXTURE.read_text(encoding="utf-8"))["transcripts"]

        for transcript in transcripts:
            with self.subTest(transcript=transcript["id"]):
                findings = validate_external_agent_transcript(transcript)
                codes = [finding.code for finding in findings]

                self.assertEqual(codes, transcript["expected_findings"])

    def test_tool_name_normalization_accepts_hermes_mcp_prefix(self) -> None:
        self.assertEqual(normalize_mcp_tool_name("mcp_aigm_kernel_player_turn"), "player_turn")
        self.assertEqual(normalize_mcp_tool_name("player_turn"), "player_turn")

    def test_natural_language_commit_requires_preview_and_validation(self) -> None:
        findings = validate_external_agent_transcript(
            {
                "kind": "natural_language_player_action",
                "steps": [
                    {
                        "tool": "commit_turn",
                        "result": {"ok": False},
                    }
                ],
            }
        )

        self.assertEqual(
            [finding.code for finding in findings],
            [
                "forbidden_normal_play_tool",
                "commit_without_validation",
                "commit_without_preview",
                "commit_without_turn_proposal",
            ],
        )

    def test_clarification_result_must_be_asked_before_more_tools(self) -> None:
        findings = validate_external_agent_transcript(
            {
                "kind": "natural_language_player_action",
                "steps": [
                    {
                        "tool": "player_turn",
                        "result": {
                            "action": "act",
                            "status": "needs_confirmation",
                            "ready_to_save": False,
                            "interpretation": {
                                "clarification": {
                                    "reason": "external_internal_action_mismatch",
                                    "question": "我需要确认你想按哪类行动结算。",
                                    "choices": [{"id": "external_candidate"}],
                                }
                            },
                        },
                    },
                    {"tool": "player_confirm", "result": {"ok": False}},
                ],
            }
        )

        self.assertEqual([finding.code for finding in findings], ["clarification_not_asked"])

    def test_clarification_can_be_asked_as_assistant_message(self) -> None:
        findings = validate_external_agent_transcript(
            {
                "kind": "natural_language_player_action",
                "steps": [
                    {
                        "tool": "player_turn",
                        "result": {
                            "clarification": {
                                "reason": "external_internal_mode_mismatch",
                                "question": "我需要确认这句话是要执行游戏行动，还是只读取/维护信息？",
                                "choices": [{"id": "external_candidate"}, {"id": "internal_candidate"}],
                            }
                        },
                    },
                    {
                        "role": "assistant",
                        "message": "我需要确认这句话是要执行游戏行动，还是只读取/维护信息？",
                    },
                ],
            }
        )

        self.assertEqual(findings, ())

    def test_clarification_choice_cannot_be_self_selected(self) -> None:
        findings = validate_external_agent_transcript(
            {
                "kind": "natural_language_player_action",
                "steps": [
                    {
                        "tool": "player_turn",
                        "result": {
                            "interpretation": {
                                "clarification": {
                                    "reason": "external_internal_slot_mismatch",
                                    "question": "我需要确认这次行动的目标对象或关键参数。",
                                    "choices": [{"id": "external_candidate"}, {"id": "internal_candidate"}],
                                }
                            }
                        },
                    },
                    {
                        "role": "assistant",
                        "clarification_response": {"selected_choice_id": "external_candidate"},
                    },
                ],
            }
        )

        self.assertEqual([finding.code for finding in findings], ["clarification_self_selected"])

    def test_clarification_choice_cannot_be_self_selected_in_prose(self) -> None:
        findings = validate_external_agent_transcript(
            {
                "kind": "natural_language_player_action",
                "steps": [
                    {
                        "tool": "player_turn",
                        "result": {
                            "interpretation": {
                                "clarification": {
                                    "reason": "external_internal_action_mismatch",
                                    "question": "我需要确认你想按哪类行动结算。",
                                    "choices": [{"id": "external_candidate"}, {"id": "internal_candidate"}],
                                }
                            }
                        },
                    },
                    {
                        "role": "assistant",
                        "message": "我选择 external_candidate 来继续。",
                    },
                ],
            }
        )

        self.assertEqual([finding.code for finding in findings], ["clarification_self_selected"])

    def test_clarification_answer_requires_fresh_repreview(self) -> None:
        findings = validate_external_agent_transcript(
            {
                "kind": "natural_language_player_action",
                "steps": [
                    {
                        "tool": "player_turn",
                        "request": {
                            "user_text": "守夜到天亮",
                            "external_intent_candidate": {"action": "rest"},
                        },
                        "result": {
                            "interpretation": {
                                "clarification": {
                                    "reason": "external_internal_action_mismatch",
                                    "question": "我需要确认你想按哪类行动结算。",
                                    "choices": [{"id": "external_candidate"}, {"id": "internal_candidate"}],
                                }
                            }
                        },
                    },
                    {"role": "assistant", "message": "我需要确认你想按哪类行动结算。"},
                    {"role": "player", "message": "我是想休息到天亮。"},
                    {
                        "tool": "player_turn",
                        "request": {
                            "user_text": "守夜到天亮",
                            "external_intent_candidate": {"action": "rest"},
                        },
                        "result": {"action": "rest", "status": "ready", "ready_to_save": True},
                    },
                ],
            }
        )

        self.assertEqual([finding.code for finding in findings], ["clarification_stale_repreview"])


if __name__ == "__main__":
    unittest.main()
