from __future__ import annotations

import argparse
import inspect
import unittest
from pathlib import Path

from rpg_engine import projections as projections_module
from rpg_engine.cli_v1 import V1_COMMANDS, add_v1_parsers
from rpg_engine.mcp_adapter import LOW_LEVEL_MCP_TOOL_NAMES, MCP_TOOL_NAMES, PLAYER_MCP_TOOL_NAMES
from rpg_engine.platform_prewarm import PlatformPrewarmService
from rpg_engine.platform_sidecar import PlatformSidecar
from rpg_engine.projection_service import ProjectionService
from rpg_engine.runtime import GMRuntime
from rpg_engine.surface_inventory import (
    AI_PROMPT_SURFACE_INVENTORY,
    CANONICAL_TAXONOMY_CATEGORIES,
    CLI_V1_COMMAND_SURFACE_INVENTORY,
    CLI_V1_SUBCOMMAND_SURFACE_INVENTORY,
    MCP_SURFACE_INVENTORY,
    NON_SURFACE_PUBLIC_APIS,
    PACKAGE_SURFACE_INVENTORY,
    PLATFORM_SURFACE_INVENTORY,
    PROJECTION_OUTBOX_SURFACE_INVENTORY,
    RUNTIME_API_SURFACE_INVENTORY,
    SurfaceEntry,
    all_surface_entries,
    default_mcp_violations,
    mcp_default_tool_names,
    render_surface_inventory_markdown,
    validate_surface_inventory,
)


ENGINE_ROOT = Path(__file__).resolve().parents[1]

def v1_parser_subcommand_names() -> set[str]:
    parser = argparse.ArgumentParser(prog="aigm-test")
    subparsers = parser.add_subparsers(dest="command")
    add_v1_parsers(subparsers, registered_actions=["gather", "travel"])

    names: set[str] = set()
    for group, group_parser in subparsers.choices.items():
        for action in group_parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                names.update(f"aigm {group} {subcommand}" for subcommand in action.choices)
    return names


def public_method_names(cls: type[object]) -> set[str]:
    return {name for name, value in inspect.getmembers(cls, inspect.isfunction) if not name.startswith("_")}


class SurfaceInventoryTests(unittest.TestCase):
    def test_all_surface_entries_validate_canonical_authority_contract(self) -> None:
        self.assertEqual(validate_surface_inventory(), ())
        for entry in all_surface_entries():
            with self.subTest(surface=entry.surface, name=entry.name):
                self.assertIn(entry.taxonomy_category, CANONICAL_TAXONOMY_CATEGORIES)
                self.assertTrue(entry.write_authority.strip(), entry)
                self.assertTrue(entry.intended_caller.strip(), entry)
                self.assertTrue(entry.forbidden_bypasses, entry)
        public_cli_names = [entry.name for entry in all_surface_entries() if entry.name.startswith("aigm ")]
        self.assertEqual(len(public_cli_names), len(set(public_cli_names)))

    def test_surface_validation_reports_actionable_missing_metadata(self) -> None:
        broken = SurfaceEntry(
            name="broken_surface",
            surface="mcp",
            category="turn_low_level",
            profile="developer_or_trusted_gm",
            write_mode="validated_commit",
            default_exposed=False,
            normal_play=False,
            description="Deliberately incomplete test entry.",
        )

        errors = validate_surface_inventory((broken,))

        self.assertTrue(any("broken_surface" in error for error in errors), errors)
        self.assertTrue(any("missing taxonomy_category" in error for error in errors), errors)
        self.assertTrue(any("missing write_authority" in error for error in errors), errors)
        self.assertTrue(any("missing forbidden_bypasses" in error for error in errors), errors)

    def test_surface_validation_rejects_duplicate_names_within_surface(self) -> None:
        entry = MCP_SURFACE_INVENTORY[0]
        errors = validate_surface_inventory((entry, entry))

        self.assertIn(f"{entry.surface}:{entry.name}: duplicate surface entry", errors)

    def test_surface_validation_rejects_duplicate_public_cli_names_across_surfaces(self) -> None:
        first = SurfaceEntry(
            name="aigm duplicate",
            surface="cli_admin",
            category="maintenance",
            taxonomy_category="maintenance/admin",
            profile="admin",
            write_mode="read_only",
            write_authority="read maintenance status",
            intended_caller="admin maintainer",
            default_exposed=False,
            normal_play=False,
            description="First duplicate.",
            forbidden_bypasses=("normal player profile exposure",),
        )
        second = SurfaceEntry(
            name="aigm duplicate",
            surface="projection/outbox_cli",
            category="projection",
            taxonomy_category="projection/outbox",
            profile="operator_read",
            write_mode="read_only",
            write_authority="read projection status",
            intended_caller="operator",
            default_exposed=False,
            normal_play=False,
            description="Second duplicate.",
            forbidden_bypasses=("fact authority",),
        )

        errors = validate_surface_inventory((first, second))

        self.assertIn("projection/outbox_cli:aigm duplicate: duplicate public CLI surface entry", errors)

    def test_surface_validation_rejects_player_safe_low_level_bypass(self) -> None:
        unsafe = SurfaceEntry(
            name="unsafe_commit",
            surface="mcp",
            category="turn_low_level",
            taxonomy_category="player-safe",
            profile="developer_or_trusted_gm_commit",
            write_mode="validated_commit",
            write_authority="direct low-level commit",
            intended_caller="player",
            default_exposed=True,
            normal_play=True,
            description="Invalid player-safe low-level commit.",
            forbidden_bypasses=("none",),
        )

        errors = validate_surface_inventory((unsafe,))

        self.assertTrue(any("player-safe entry exposes low-level authority" in error for error in errors), errors)
        self.assertTrue(any("missing forbidden_bypasses" in error for error in errors), errors)

    def test_surface_validation_requires_authority_gate_for_dispatch_surfaces(self) -> None:
        dispatch = SurfaceEntry(
            name="aigm ambiguous",
            surface="cli_v1",
            category="command_group",
            taxonomy_category="maintenance/admin",
            profile="maintenance",
            write_mode="subcommand_dispatch",
            write_authority="dispatch ambiguous subcommands",
            intended_caller="maintainer",
            default_exposed=False,
            normal_play=False,
            description="Invalid dispatch entry without a gate.",
            forbidden_bypasses=("normal player profile exposure",),
        )

        errors = validate_surface_inventory((dispatch,))

        self.assertIn("cli_v1:aigm ambiguous: missing authority_gate", errors)

    def test_surface_validation_rejects_raw_string_forbidden_bypasses(self) -> None:
        raw = SurfaceEntry(
            name="raw_bypass",
            surface="mcp",
            category="runtime_health",
            taxonomy_category="player-safe",
            profile="player_read",
            write_mode="read_only",
            write_authority="read health only",
            intended_caller="player",
            default_exposed=True,
            normal_play=True,
            description="Invalid raw bypass string.",
            forbidden_bypasses="none",  # type: ignore[arg-type]
        )

        errors = validate_surface_inventory((raw,))

        self.assertIn("mcp:raw_bypass: missing forbidden_bypasses", errors)

    def test_surface_validation_rejects_default_exposed_non_player_safe_mcp_entry(self) -> None:
        unsafe_default = SurfaceEntry(
            name="unsafe_default",
            surface="mcp",
            category="turn_low_level",
            taxonomy_category="trusted low-level",
            profile="developer_or_trusted_gm",
            write_mode="read_only",
            write_authority="read low-level context",
            intended_caller="developer",
            default_exposed=True,
            normal_play=False,
            description="Invalid default exposed low-level MCP entry.",
            forbidden_bypasses=("default player profile exposure",),
        )

        errors = validate_surface_inventory((unsafe_default,))

        self.assertIn("mcp:unsafe_default: default-exposed MCP entry must be player-safe", errors)

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
        self.assertEqual(by_name["aigm package install"].profile, "admin_maintenance")
        self.assertEqual(by_name["aigm package reconcile"].write_mode, "read_only")
        self.assertEqual(by_name["aigm proposal apply"].profile, "maintenance_content_apply")
        self.assertEqual(by_name["aigm apply-content-delta"].profile, "maintenance_content_apply")
        self.assertEqual(by_name["aigm save-turn"].profile, "admin_or_legacy_save_turn")
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
        self.assertIn("Taxonomy", report)
        self.assertIn("Forbidden bypasses", report)
        self.assertIn("`preview_from_text`", report)
        self.assertIn("`GMRuntime.commit_turn`", report)
        self.assertIn("`PlatformSidecar.player_act_from_message`", report)
        self.assertIn("`ProjectionService.refresh`", report)
        self.assertIn("`docs/prompts/ai-client-prompt.md`", report)
        self.assertIn("`aigm package upgrade`", report)
        self.assertIn("`aigm player turn`", report)

    def test_cli_v1_command_inventory_covers_declared_command_groups(self) -> None:
        self.assertEqual(
            {entry.name.removeprefix("aigm ") for entry in CLI_V1_COMMAND_SURFACE_INVENTORY},
            V1_COMMANDS,
        )
        by_name = {entry.name: entry for entry in CLI_V1_COMMAND_SURFACE_INVENTORY}
        self.assertEqual(by_name["aigm player"].taxonomy_category, "player-safe")
        self.assertEqual(by_name["aigm platform"].taxonomy_category, "platform sidecar")
        self.assertIn("subcommand", by_name["aigm mcp"].authority_gate)

    def test_cli_v1_subcommand_inventory_covers_parser_derived_subcommands(self) -> None:
        inventoried = {entry.name for entry in all_surface_entries()}

        self.assertLessEqual(v1_parser_subcommand_names(), inventoried)
        self.assertIn("aigm player turn", {entry.name for entry in CLI_V1_SUBCOMMAND_SURFACE_INVENTORY})
        self.assertIn("aigm play commit", {entry.name for entry in CLI_V1_SUBCOMMAND_SURFACE_INVENTORY})

    def test_runtime_platform_and_projection_inventory_cover_source_entrypoints(self) -> None:
        for group, entries in NON_SURFACE_PUBLIC_APIS.items():
            with self.subTest(group=group):
                self.assertTrue(entries)
                self.assertTrue(all(reason.strip() for reason in entries.values()))

        runtime_sources = public_method_names(GMRuntime) - set(NON_SURFACE_PUBLIC_APIS["GMRuntime"])
        runtime_inventory = {entry.name.removeprefix("GMRuntime.") for entry in RUNTIME_API_SURFACE_INVENTORY}
        self.assertLessEqual(runtime_sources, runtime_inventory)

        platform_sources = public_method_names(PlatformSidecar) - set(NON_SURFACE_PUBLIC_APIS["PlatformSidecar"])
        platform_sources.add("PlatformPrewarmService.handle_message")
        platform_inventory = {
            entry.name.removeprefix("PlatformSidecar.") for entry in PLATFORM_SURFACE_INVENTORY
        }
        platform_inventory.add(
            next(
                entry.name
                for entry in PLATFORM_SURFACE_INVENTORY
                if entry.name == "PlatformPrewarmService.handle_message"
            )
        )
        self.assertLessEqual(platform_sources, platform_inventory)

        projection_service_sources = public_method_names(ProjectionService)
        projection_function_sources = {
            name
            for name, value in inspect.getmembers(projections_module, inspect.isfunction)
            if not name.startswith("_") and ("projection" in name or "outbox" in name)
        } - set(NON_SURFACE_PUBLIC_APIS["projections"])
        projection_inventory = {entry.name for entry in PROJECTION_OUTBOX_SURFACE_INVENTORY}
        self.assertLessEqual({f"ProjectionService.{name}" for name in projection_service_sources}, projection_inventory)
        self.assertLessEqual(projection_function_sources, projection_inventory)

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
