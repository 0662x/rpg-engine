from __future__ import annotations

from pathlib import Path
import unittest

from rpg_engine.packages.service import load_package_source
from rpg_engine.package_service import load_package_source as legacy_load_package_source
from rpg_engine.packages.merge import PackageFieldDiff
from rpg_engine.package_merge import PackageFieldDiff as legacy_package_field_diff
from rpg_engine.compat.importers.registry import get_default_importer_registry
from rpg_engine.importers.registry import get_default_importer_registry as legacy_importer_registry
from rpg_engine.cli_v1 import V1_COMMANDS
from rpg_engine.mcp_adapter import HIDDEN_READ_PROFILES, LOW_LEVEL_PROFILES, PLAYER_PROFILE
from rpg_engine.surface_inventory import MCP_SURFACE_INVENTORY


ROOT = Path(__file__).resolve().parents[1]


class NamespaceBoundaryTests(unittest.TestCase):
    def test_legacy_package_wrappers_export_new_namespace_symbols(self) -> None:
        self.assertIs(load_package_source, legacy_load_package_source)
        self.assertIs(PackageFieldDiff, legacy_package_field_diff)

    def test_legacy_importer_wrapper_exports_compat_registry(self) -> None:
        self.assertIs(get_default_importer_registry, legacy_importer_registry)

    def test_v1_and_mcp_sources_do_not_import_legacy_or_admin_surfaces(self) -> None:
        for relative in ("rpg_engine/cli_v1.py", "rpg_engine/mcp_adapter.py", "rpg_engine/runtime.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("rpg_engine.package_", source)
            self.assertNotIn("from .package_", source)
            self.assertNotIn("from .admin", source)
            self.assertNotIn("from .compat", source)
            self.assertNotIn("from .legacy", source)

    def test_player_profile_cannot_enter_low_level_or_hidden_mcp_boundaries(self) -> None:
        self.assertNotIn(PLAYER_PROFILE, LOW_LEVEL_PROFILES)
        self.assertNotIn(PLAYER_PROFILE, HIDDEN_READ_PROFILES)

        source = (ROOT / "rpg_engine/mcp_adapter.py").read_text(encoding="utf-8")
        for tool in ("preview_action", "validate_delta", "commit_turn"):
            with self.subTest(tool=tool):
                self.assertIn(f'self.require_low_level_profile("{tool}")', source)

    def test_player_confirm_is_the_only_normal_play_validated_commit_surface(self) -> None:
        normal_commits = [
            entry.name
            for entry in MCP_SURFACE_INVENTORY
            if entry.normal_play and entry.write_mode == "validated_commit"
        ]
        self.assertEqual(normal_commits, ["player_confirm"])

    def test_v1_command_set_exposes_player_and_eval_but_not_admin(self) -> None:
        self.assertIn("player", V1_COMMANDS)
        self.assertIn("eval", V1_COMMANDS)
        self.assertNotIn("admin", V1_COMMANDS)


if __name__ == "__main__":
    unittest.main()
