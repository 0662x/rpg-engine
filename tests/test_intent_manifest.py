from __future__ import annotations

import unittest

from rpg_engine.ai_intent.risk import ACTION_BASE_RISK
from rpg_engine.ai_intent.slot_contract import ACTION_REQUIRED_SLOTS, AI_SUPPLIED_CONFIRMATION_SLOTS
from rpg_engine.capabilities import ACTION_CAPABILITIES
from rpg_engine.intent_manifest import QUERY_KINDS, build_intent_manifest


class IntentManifestTests(unittest.TestCase):
    def test_manifest_lists_all_registered_actions_and_query_kinds(self) -> None:
        manifest = build_intent_manifest()

        self.assertEqual(manifest["schema_version"], "1")
        self.assertEqual(manifest["generated_by"], "kernel")
        self.assertEqual(
            [action["name"] for action in manifest["actions"]],
            ["combat", "craft", "explore", "gather", "random_table", "rest", "routine", "social", "travel"],
        )
        self.assertEqual([query["kind"] for query in manifest["queries"]], list(QUERY_KINDS))
        self.assertEqual([query["kind"] for query in manifest["queries"]], ["scene", "entity", "context"])
        self.assertNotIn("rule", [query["kind"] for query in manifest["queries"]])

    def test_manifest_merges_resolver_binder_risk_and_capability_contracts(self) -> None:
        manifest = build_intent_manifest()
        actions = {action["name"]: action for action in manifest["actions"]}

        for name, action in actions.items():
            with self.subTest(action=name):
                self.assertEqual(action["capability"], ACTION_CAPABILITIES[name])
                self.assertEqual(action["risk"], ACTION_BASE_RISK[name])
                self.assertTrue(action["resolver_contract"]["has_preview"])
                self.assertTrue(action["resolver_contract"]["has_request_contract"])
                self.assertTrue(action["resolver_contract"]["has_resolve_contract"])
                self.assertTrue(action["resolver_contract"]["has_delta_contract"])
                slot_names = {slot["name"] for slot in action["slots"]}
                self.assertIn("user_text", slot_names)
                for required in ACTION_REQUIRED_SLOTS.get(name, ()):
                    if required == "table or dice":
                        continue
                    self.assertIn(required, slot_names)

    def test_manifest_records_slot_aliases_required_groups_and_confirmation_policy(self) -> None:
        manifest = build_intent_manifest()
        actions = {action["name"]: action for action in manifest["actions"]}

        travel_slots = {slot["name"]: slot for slot in actions["travel"]["slots"]}
        self.assertTrue(travel_slots["destination"]["required"])
        self.assertEqual(travel_slots["destination"]["type"], "entity")
        self.assertEqual(travel_slots["destination"]["allowed_entity_types"], ("location",))
        self.assertEqual(travel_slots["destination"]["aliases"], ("place", "target", "to"))

        combat_slots = {slot["name"]: slot for slot in actions["combat"]["slots"]}
        self.assertEqual(AI_SUPPLIED_CONFIRMATION_SLOTS["combat"], {"ready_state"})
        self.assertFalse(combat_slots["ready_state"]["ai_fillable"])
        self.assertTrue(combat_slots["ready_state"]["player_confirmation_required"])
        self.assertEqual(combat_slots["target"]["allowed_entity_types"], ("threat", "character", "species"))

        random_table = actions["random_table"]
        self.assertEqual(
            random_table["requirement_groups"],
            [{"name": "random_source", "any_of": ("table", "dice"), "required": True}],
        )
        random_slots = {slot["name"]: slot for slot in random_table["slots"]}
        self.assertEqual(random_slots["table"]["type"], "random_table_id")
        self.assertEqual(random_slots["dice"]["type"], "dice_expr")

        routine = actions["routine"]
        self.assertEqual(
            routine["requirement_groups"],
            [{"name": "routine_scope", "any_of": ("task", "target"), "required": True}],
        )

    def test_query_manifest_is_read_only_and_owned_by_kernel(self) -> None:
        manifest = build_intent_manifest()
        queries = {query["kind"]: query for query in manifest["queries"]}

        self.assertFalse(queries["scene"]["requires_query_text"])
        self.assertTrue(queries["entity"]["requires_query_text"])
        self.assertTrue(queries["context"]["requires_query_text"])
        for query in queries.values():
            with self.subTest(query=query["kind"]):
                self.assertTrue(query["read_only"])
                self.assertFalse(query["advances_time"])
                self.assertEqual(query["result_owner"], "kernel")
                slots = {slot["name"]: slot for slot in query["slots"]}
                self.assertEqual(slots["query_kind"]["allowed_values"], tuple(QUERY_KINDS))
                self.assertTrue(slots["query_kind"]["required"])
                self.assertEqual(slots["query_text"]["required"], query["kind"] in {"entity", "context"})
        self.assertEqual(manifest["unsupported_query_kind_policy"], {"rule": "context", "default": "entity"})


if __name__ == "__main__":
    unittest.main()
