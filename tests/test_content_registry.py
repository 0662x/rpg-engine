from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from rpg_engine.content_types import ContentRegistry, ContentTypeSpec, get_default_registry


ENGINE_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


class ContentRegistryTests(unittest.TestCase):
    def test_default_registry_exposes_core_content_types(self) -> None:
        registry = get_default_registry()
        names = [spec.name for spec in registry.all()]
        self.assertEqual(names, ["entity", "rule", "clock", "route", "relationship", "world_setting"])
        self.assertEqual(registry.by_campaign_key("clocks").name, "clock")
        self.assertEqual(registry.by_campaign_key("relationships").name, "relationship")
        self.assertEqual(registry.by_delta_key("upsert_rules").name, "rule")
        self.assertEqual(registry.by_delta_key("upsert_world_settings").name, "world_setting")
        self.assertEqual(registry.by_entity_type("rule").name, "rule")
        self.assertEqual(registry.by_entity_type("relationship").name, "relationship")
        self.assertIsNone(registry.by_delta_key("upsert_clocks"))
        world_setting = registry.get("world_setting")
        self.assertIsNotNone(world_setting.validate_database)
        self.assertTrue(world_setting.sync_safe)
        self.assertFalse(registry.get("route").sync_safe)
        self.assertTrue(all(spec.merge_policy is not None for spec in registry.all()))

    def test_registry_rejects_duplicate_keys(self) -> None:
        registry = ContentRegistry()
        registry.register(ContentTypeSpec(name="alpha", campaign_key="alpha"))
        with self.assertRaises(ValueError):
            registry.register(ContentTypeSpec(name="alpha"))
        with self.assertRaises(ValueError):
            registry.register(ContentTypeSpec(name="beta", campaign_key="alpha"))

    def test_content_type_cli_is_observable(self) -> None:
        result = run_cli("content", "list-types")
        self.assertIn("`clock`", result.stdout)
        self.assertIn("`upsert_rules`", result.stdout)
        self.assertIn("`world_setting`", result.stdout)

        detail = run_cli("content", "inspect-type", "route")
        self.assertIn("# Content Type: route", detail.stdout)
        self.assertIn("`upsert_routes`", detail.stdout)

        rule_detail = run_cli("content", "inspect-type", "rule")
        self.assertIn("## Presentation", rule_detail.stdout)
        self.assertIn("| Presentation Card Dir | `rules` |", rule_detail.stdout)
        self.assertIn("| Has Presentation Sections | yes |", rule_detail.stdout)
        self.assertIn("| Has Query Renderer | yes |", rule_detail.stdout)
        self.assertNotIn("Legacy Content", rule_detail.stdout)

        clock_detail = run_cli("content", "inspect-type", "clock")
        self.assertIn("| Presentation Card Dir | `clocks` |", clock_detail.stdout)
        self.assertIn("| Has Presentation Sections | yes |", clock_detail.stdout)
        self.assertIn("| Has Query Renderer | yes |", clock_detail.stdout)

        world_detail = run_cli("content", "inspect-type", "world_setting")
        self.assertIn("| Presentation Card Dir | `world_settings` |", world_detail.stdout)
        self.assertIn("| Has Presentation Sections | yes |", world_detail.stdout)
        self.assertIn("| Has Query Renderer | yes |", world_detail.stdout)
        self.assertIn("| Has Database Check | yes |", world_detail.stdout)
        self.assertIn("| Sync Safe | yes |", world_detail.stdout)

        missing = run_cli("content", "inspect-type", "missing", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("unknown content type", missing.stdout)


if __name__ == "__main__":
    unittest.main()
