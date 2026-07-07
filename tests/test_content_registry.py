from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from rpg_engine.delta_schema import ALLOWED_ENTITY_TYPES
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
        for spec in registry.all():
            with self.subTest(content_type=spec.name):
                self.assertTrue(spec.contract_metadata()["name"])
                self.assertEqual(spec.contract_metadata()["has_record_validation"], spec.validate_record is not None)
                self.assertEqual(spec.contract_metadata()["has_database_validation"], spec.validate_database is not None)
                self.assertIn("merge_policy", spec.contract_metadata())
                self.assertIn("author_owned", spec.contract_metadata()["merge_policy"])
                self.assertIn("runtime_owned", spec.contract_metadata()["merge_policy"])
                self.assertIn("mergeable", spec.contract_metadata()["merge_policy"])
                self.assertIn("conflict_only", spec.contract_metadata()["merge_policy"])
                self.assertEqual(spec.contract_metadata()["merge_policy"]["default_ownership"], ("conflict-only",))
        self.assertEqual(registry.get("clock").contract_metadata()["delta_key"], None)
        self.assertFalse(registry.get("clock").contract_metadata()["has_delta_upsert"])
        self.assertEqual(registry.get("relationship").contract_metadata()["delta_key"], None)
        self.assertFalse(registry.get("relationship").contract_metadata()["has_delta_upsert"])

    def test_allowed_entity_types_are_not_implicitly_package_content_roots(self) -> None:
        registry = get_default_registry()
        registered_campaign_keys = {spec.campaign_key for spec in registry.seed_specs()}

        for entity_type in ("character", "item", "location"):
            with self.subTest(entity_type=entity_type):
                self.assertIn(entity_type, ALLOWED_ENTITY_TYPES)
                self.assertIsNone(registry.by_entity_type(entity_type))
                self.assertNotIn(entity_type, registered_campaign_keys)

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
        self.assertIn("## Merge Policy", rule_detail.stdout)
        self.assertIn("| Author Owned | `examples`, `exceptions`, `priority`, `scope`, `statement` |", rule_detail.stdout)
        self.assertIn("| Mergeable | `aliases` |", rule_detail.stdout)
        self.assertIn("| Conflict Only | `id` |", rule_detail.stdout)
        self.assertIn("| Unlisted Fields | `conflict-only` |", rule_detail.stdout)
        self.assertNotIn("Legacy Content", rule_detail.stdout)

        clock_detail = run_cli("content", "inspect-type", "clock")
        self.assertIn("| Presentation Card Dir | `clocks` |", clock_detail.stdout)
        self.assertIn("| Has Presentation Sections | yes |", clock_detail.stdout)
        self.assertIn("| Has Query Renderer | yes |", clock_detail.stdout)
        self.assertIn("| Delta Key |  |", clock_detail.stdout)
        self.assertIn("| Has Delta Upsert | no |", clock_detail.stdout)

        world_detail = run_cli("content", "inspect-type", "world_setting")
        self.assertIn("| Presentation Card Dir | `world_settings` |", world_detail.stdout)
        self.assertIn("| Has Presentation Sections | yes |", world_detail.stdout)
        self.assertIn("| Has Query Renderer | yes |", world_detail.stdout)
        self.assertIn("| Has Database Check | yes |", world_detail.stdout)
        self.assertIn("| Sync Safe | yes |", world_detail.stdout)
        self.assertIn("| Database Validation | yes |", world_detail.stdout)
        self.assertIn("| Runtime Owned |  |", world_detail.stdout)

        missing = run_cli("content", "inspect-type", "missing", check=False)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("unknown content type", missing.stdout)


if __name__ == "__main__":
    unittest.main()
