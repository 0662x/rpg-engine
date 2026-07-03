from __future__ import annotations

import unittest
from pathlib import Path

from rpg_engine.mcp_adapter import LOW_LEVEL_MCP_TOOL_NAMES, MCP_TOOL_NAMES, PLAYER_MCP_TOOL_NAMES
from rpg_engine.surface_inventory import (
    AI_PROMPT_SURFACE_INVENTORY,
    MCP_SURFACE_INVENTORY,
    PACKAGE_SURFACE_INVENTORY,
    default_mcp_violations,
    mcp_default_tool_names,
    render_surface_inventory_markdown,
)


ENGINE_ROOT = Path(__file__).resolve().parents[1]


class SurfaceInventoryTests(unittest.TestCase):
    def test_surface_inventory_matches_default_mcp_tools(self) -> None:
        self.assertEqual(mcp_default_tool_names(), PLAYER_MCP_TOOL_NAMES)
        self.assertEqual(
            {entry.name for entry in MCP_SURFACE_INVENTORY},
            set(MCP_TOOL_NAMES),
        )
        self.assertEqual(len({entry.name for entry in MCP_SURFACE_INVENTORY}), len(MCP_SURFACE_INVENTORY))

    def test_default_mcp_surface_excludes_admin_and_maintenance_tools(self) -> None:
        self.assertEqual(default_mcp_violations(), ())
        forbidden_profiles = ("admin", "maintenance", "import", "export", "repair", "migration", "plugin")
        for entry in MCP_SURFACE_INVENTORY:
            with self.subTest(tool=entry.name):
                self.assertFalse(any(token in entry.profile for token in forbidden_profiles), entry)
                if entry.name in LOW_LEVEL_MCP_TOOL_NAMES:
                    self.assertFalse(entry.default_exposed, entry)
                else:
                    self.assertTrue(entry.default_exposed, entry)

    def test_default_mcp_write_modes_make_story_mutation_boundary_explicit(self) -> None:
        write_modes = {entry.name: entry.write_mode for entry in MCP_SURFACE_INVENTORY}
        by_name = {entry.name: entry for entry in MCP_SURFACE_INVENTORY}

        self.assertEqual(write_modes["start_turn"], "read_only")
        self.assertEqual(write_modes["intent_preflight"], "advisory_only")
        self.assertEqual(write_modes["query"], "read_only")
        self.assertEqual(write_modes["intent_manifest"], "read_only")
        self.assertEqual(write_modes["player_query"], "read_only")
        self.assertEqual(write_modes["player_turn"], "preview_only")
        self.assertEqual(write_modes["player_act"], "preview_only")
        self.assertEqual(write_modes["player_confirm"], "validated_commit")
        self.assertEqual(write_modes["preview_from_text"], "preview_only")
        self.assertEqual(write_modes["preview_action"], "preview_only")
        self.assertEqual(write_modes["validate_delta"], "validation_only")
        self.assertEqual(write_modes["commit_turn"], "validated_commit")
        self.assertEqual(write_modes["save_create"], "controlled_create")
        self.assertTrue(by_name["intent_manifest"].normal_play)
        self.assertTrue(by_name["player_turn"].normal_play)
        self.assertFalse(by_name["player_query"].normal_play)
        self.assertFalse(by_name["player_act"].normal_play)
        self.assertTrue(by_name["player_confirm"].normal_play)
        self.assertFalse(by_name["start_turn"].normal_play)
        self.assertFalse(by_name["intent_preflight"].normal_play)
        self.assertFalse(by_name["query"].normal_play)
        self.assertFalse(by_name["preview_from_text"].normal_play)
        self.assertFalse(by_name["preview_action"].normal_play)
        self.assertFalse(by_name["validate_delta"].normal_play)
        self.assertFalse(by_name["commit_turn"].normal_play)
        self.assertIn("must not advance story", " ".join(by_name["save_create"].notes))

    def test_ai_prompt_surfaces_are_low_trust_guidance_not_permissions(self) -> None:
        prompt_paths = {entry.name for entry in AI_PROMPT_SURFACE_INVENTORY}
        self.assertIn("docs/prompts/ai-client-prompt.md", prompt_paths)
        self.assertIn("docs/prompts/author-ai-prompt.md", prompt_paths)

        ai_client_prompt = (ENGINE_ROOT / "docs" / "prompts" / "ai-client-prompt.md").read_text(encoding="utf-8")
        author_prompt = (ENGINE_ROOT / "docs" / "prompts" / "author-ai-prompt.md").read_text(encoding="utf-8")

        self.assertIn("Prompt version:", ai_client_prompt)
        self.assertIn("external_agent_low_trust", ai_client_prompt)
        self.assertIn("not a permission grant", ai_client_prompt)
        self.assertIn("default player-safe MCP profile", ai_client_prompt)
        self.assertIn("start_turn, then preview_from_text", ai_client_prompt)
        self.assertIn("Use preview_action only when a low-level action has already been selected", ai_client_prompt)
        self.assertIn("mcp_aigm_kernel_campaign_validate", ai_client_prompt)
        self.assertIn("save import/export/patch", ai_client_prompt)

        self.assertIn("authoring_low_trust", author_prompt)
        self.assertIn("not grant access to runtime saves", author_prompt)
        self.assertIn("Never write Python code, plugins, scripts", author_prompt)

    def test_package_management_inventory_separates_player_and_maintenance_profiles(self) -> None:
        by_name = {entry.name: entry for entry in PACKAGE_SURFACE_INVENTORY}

        self.assertEqual(by_name["aigm save inspect"].write_mode, "read_only")
        self.assertEqual(by_name["aigm save import"].profile, "maintenance_import")
        self.assertEqual(by_name["aigm save patch"].profile, "maintenance_repair")
        self.assertEqual(by_name["aigm package upgrade"].profile, "admin_maintenance")
        self.assertFalse(by_name["aigm save import"].default_exposed)
        self.assertFalse(by_name["aigm projection repair"].default_exposed)

        restricted_terms = ("admin", "maintenance", "import", "export", "repair", "migration", "plugin")
        for entry in PACKAGE_SURFACE_INVENTORY:
            with self.subTest(entry=entry.name):
                if any(term in entry.profile for term in restricted_terms):
                    self.assertFalse(entry.default_exposed, entry)
                if any(term in entry.write_mode for term in ("admin", "maintenance", "import", "export")):
                    self.assertFalse(entry.default_exposed, entry)

    def test_inventory_can_render_phase_zero_markdown_report(self) -> None:
        report = render_surface_inventory_markdown()

        self.assertIn("# Phase 0 Surface Inventory", report)
        self.assertIn("`preview_from_text`", report)
        self.assertIn("`docs/prompts/ai-client-prompt.md`", report)
        self.assertIn("`aigm package upgrade`", report)

    def test_canonical_contract_docs_mention_all_inventory_entries(self) -> None:
        mcp_document = (ENGINE_ROOT / "docs" / "mcp-contracts.md").read_text(encoding="utf-8")
        prompt_document = "\n".join(
            [
                (ENGINE_ROOT / "docs" / "prompt-contracts.md").read_text(encoding="utf-8"),
                (ENGINE_ROOT / "docs" / "authoring-guide.md").read_text(encoding="utf-8"),
            ]
        )
        cli_document = (ENGINE_ROOT / "docs" / "cli-contracts.md").read_text(encoding="utf-8")
        testing_document = (ENGINE_ROOT / "docs" / "testing-and-quality-gates.md").read_text(encoding="utf-8")

        for entry in MCP_SURFACE_INVENTORY:
            with self.subTest(entry=entry.name):
                self.assertIn(f"`{entry.name}`", mcp_document)

        for entry in AI_PROMPT_SURFACE_INVENTORY:
            with self.subTest(entry=entry.name):
                self.assertIn(f"`{entry.name}`", prompt_document)

        for entry in PACKAGE_SURFACE_INVENTORY:
            with self.subTest(entry=entry.name):
                self.assertIn(f"`{entry.name}`", cli_document)

        self.assertIn("tests/fixtures/intent_router_gold_set.yaml", testing_document)
        self.assertIn("tests/fixtures/mcp_external_agent_transcripts.yaml", testing_document)
        self.assertIn("phase-0-performance-baseline.md", testing_document)

    def test_archived_architecture_review_remains_discoverable_from_stub(self) -> None:
        stub = (ENGINE_ROOT / "docs" / "architecture" / "turn-flow-architecture.md").read_text(
            encoding="utf-8"
        )
        document = (
            ENGINE_ROOT
            / "docs"
            / "archive"
            / "pre-bmad-docs-2026-07-03"
            / "architecture"
            / "turn-flow-architecture.md"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn("archive/pre-bmad-docs-2026-07-03/architecture/turn-flow-architecture.md", stub)
        self.assertIn("[架构](../architecture.md)", stub)
        self.assertIn("历史材料仅作证据", stub)
        self.assertIn("### 14.5 Phase 0-4 实现后多角色复审", document)
        for phrase in (
            "Phase 0 inventory/baseline",
            "Phase 1 `IntentRouter`",
            "Phase 2 `player_turn`/`preview_from_text`",
            "Phase 3 `TurnContract`",
            "Phase 4 `TurnProposal`",
            "本次复审直接阅读的关键代码入口",
            "rpg_engine.mcp_adapter.MCP_TOOL_NAMES",
            "GMRuntime.preview_action()",
            "response_lint.lint_response()",
            "turn_proposal_from_dict()",
            "没有发现需要回滚 Phase 3/4 的阻塞问题",
            "semantic_ai",
            "preview_action",
            "ValidationPipeline",
            "TurnCommitService",
            "ProjectionService",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, document)


if __name__ == "__main__":
    unittest.main()
