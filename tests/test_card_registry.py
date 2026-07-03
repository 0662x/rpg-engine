from __future__ import annotations

import unittest

from rpg_engine.card_registry import CardRegistry, CardTypeSpec, get_default_card_registry
from rpg_engine.cards import card_directory, entity_type_from_id, ordered_entity_types


class CardRegistryTests(unittest.TestCase):
    def test_default_card_registry_exposes_entity_presentation_specs(self) -> None:
        registry = get_default_card_registry()
        specs = {spec.entity_type: spec for spec in registry.sorted_specs()}

        self.assertEqual(specs["character"].card_dir, "characters")
        self.assertEqual(specs["location"].card_dir, "locations")
        self.assertEqual(specs["equipment"].card_dir, "items")
        self.assertEqual(specs["item"].card_dir, "items")
        self.assertEqual(specs["world_setting"].card_dir, "world_settings")
        self.assertIsNotNone(specs["character"].append_sections)
        self.assertIsNotNone(specs["item"].append_sections)
        self.assertIsNotNone(specs["rule"].append_sections)
        self.assertIsNotNone(specs["world_setting"].append_sections)
        self.assertIsNotNone(specs["character"].render_query)
        self.assertIsNotNone(specs["item"].render_query)
        self.assertIsNotNone(specs["rule"].render_query)
        self.assertIsNotNone(specs["world_setting"].render_query)

    def test_card_helpers_use_registry_for_paths_prefixes_and_ordering(self) -> None:
        registry = get_default_card_registry()

        self.assertEqual(card_directory("crop_plot", registry), "crop_plots")
        self.assertEqual(card_directory("unknown_type", registry), "misc")
        self.assertEqual(entity_type_from_id("world:weather", registry), "world_setting")
        self.assertEqual(entity_type_from_id("pc:shenyan", registry), "character")
        self.assertEqual(entity_type_from_id("creature:forest-sprite", registry), "species")
        self.assertEqual(
            ordered_entity_types(["world_setting", "character", "item", "location"], registry),
            ["character", "location", "item", "world_setting"],
        )

    def test_card_registry_rejects_duplicate_entity_types_and_prefixes(self) -> None:
        registry = CardRegistry()
        registry.register(CardTypeSpec("alpha", "alpha", id_prefixes=("a",)))

        with self.assertRaises(ValueError):
            registry.register(CardTypeSpec("alpha", "other"))
        with self.assertRaises(ValueError):
            registry.register(CardTypeSpec("beta", "beta", id_prefixes=("a",)))


if __name__ == "__main__":
    unittest.main()
