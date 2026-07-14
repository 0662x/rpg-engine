from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys
import unittest

from rpg_engine.ai_intent import arbiter, normalization, risk
from rpg_engine.ai_intent.risk import ACTION_BASE_RISK
from rpg_engine.ai_intent.safety_contract import (
    ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE,
    ActiveIntentContract,
    ExternalIntentContractError,
    SAFETY_FLAG_VALUES,
    SAFETY_VOCABULARY_DIGEST,
    SAFETY_VOCABULARY_VERSION,
    canonical_json_sha256,
)
from rpg_engine.ai_intent.external import validate_external_intent_candidate
from rpg_engine.ai_intent.slot_contract import ACTION_REQUIRED_SLOTS, AI_SUPPLIED_CONFIRMATION_SLOTS
from rpg_engine.capabilities import ACTION_CAPABILITIES
from rpg_engine.intent_manifest import QUERY_KINDS, build_intent_manifest
from rpg_engine.actions import (
    ActionOptionSpec,
    ActionRequirementGroupSpec,
    ActionResolverRegistry,
    ActionResolverSpec,
    get_default_action_registry,
)
from rpg_engine.ai_intent.prompts import internal_prompt_action_contract
from rpg_engine.resource_paths import schema_resource_text


class IntentManifestTests(unittest.TestCase):
    def test_safety_contract_is_canonical_immutable_and_digest_is_reproducible(self) -> None:
        expected_values = (
            "forced_save",
            "hidden_info",
            "maintenance_request",
            "out_of_world",
            "prompt_injection",
            "unsafe_command",
        )
        payload = {
            "version": SAFETY_VOCABULARY_VERSION,
            "values": list(expected_values),
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

        self.assertIsInstance(SAFETY_FLAG_VALUES, frozenset)
        self.assertEqual(tuple(sorted(SAFETY_FLAG_VALUES)), expected_values)
        self.assertEqual(SAFETY_VOCABULARY_VERSION, "1")
        self.assertEqual(SAFETY_VOCABULARY_DIGEST, hashlib.sha256(canonical).hexdigest())
        self.assertTrue(ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE)

    def test_all_runtime_safety_aliases_reference_the_canonical_value(self) -> None:
        self.assertIs(normalization.SAFETY_FLAG_VALUES, SAFETY_FLAG_VALUES)
        self.assertIs(risk.BLOCKING_SAFETY_FLAGS, SAFETY_FLAG_VALUES)
        self.assertIs(arbiter.BLOCKER_SAFETY_FLAGS, SAFETY_FLAG_VALUES)

    def test_manifest_lists_all_registered_actions_and_query_kinds(self) -> None:
        manifest = build_intent_manifest()

        self.assertEqual(manifest["schema_version"], "4")
        self.assertEqual(manifest["generated_by"], "kernel")
        self.assertEqual(
            [action["name"] for action in manifest["actions"]],
            ["combat", "craft", "explore", "gather", "random_table", "rest", "routine", "social", "travel"],
        )
        self.assertEqual([query["kind"] for query in manifest["queries"]], list(QUERY_KINDS))
        self.assertEqual([query["kind"] for query in manifest["queries"]], ["scene", "entity", "context"])
        self.assertNotIn("rule", [query["kind"] for query in manifest["queries"]])

    def test_manifest_v4_embeds_the_exact_registry_taxonomy_projection(self) -> None:
        registry = get_default_action_registry()
        manifest = build_intent_manifest(registry=registry)
        taxonomy = registry.taxonomy_projection()

        self.assertEqual(manifest["action_taxonomy"], taxonomy)
        self.assertEqual(manifest["action_taxonomy"]["version"], "1")
        self.assertEqual(manifest["action_taxonomy"]["digest"], registry.taxonomy_digest)
        taxonomy_actions = {action["name"]: action for action in taxonomy["actions"]}
        manifest_actions = {action["name"]: action for action in manifest["actions"]}
        self.assertEqual(set(taxonomy_actions), set(manifest_actions))
        for name, action in manifest_actions.items():
            with self.subTest(action=name):
                projected = taxonomy_actions[name]
                self.assertEqual(action["keywords"], tuple(term["value"] for term in projected["terms"] if "simple" in term["roles"]))
                self.assertEqual(action["semantic_labels"], tuple(projected["semantic_labels"]))
                self.assertEqual(action["inference_priority"], projected["inference_priority"])

    def test_manifest_publishes_complete_contract_identity_and_canonical_digest(self) -> None:
        manifest = build_intent_manifest()
        payload = dict(manifest)
        digest = payload.pop("manifest_digest")

        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(digest, canonical_json_sha256(payload))
        self.assertEqual(
            manifest["safety_vocabulary"],
            {
                "version": "1",
                "digest": SAFETY_VOCABULARY_DIGEST,
                "values": tuple(sorted(SAFETY_FLAG_VALUES)),
            },
        )
        self.assertEqual(manifest["candidate_shape"]["safety_flags"], tuple(sorted(SAFETY_FLAG_VALUES)))
        self.assertEqual(
            manifest["candidate_shape"]["contract"],
            {
                "required": False,
                "all_or_nothing": True,
                "additional_properties": False,
                "legacy_unversioned_allowed": True,
                "required_fields_when_present": (
                    "manifest_schema_version",
                    "manifest_digest",
                    "safety_vocabulary_version",
                    "safety_vocabulary_digest",
                ),
            },
        )
        self.assertEqual(
            canonical_json_sha256({"values": ("a", "b")}),
            canonical_json_sha256({"values": ["a", "b"]}),
        )
        with self.assertRaises(ValueError):
            canonical_json_sha256({"invalid": float("nan")})

    def test_manifest_wire_and_digests_are_stable_across_hash_seeds(self) -> None:
        script = (
            "import json; "
            "from rpg_engine.intent_manifest import build_intent_manifest; "
            "print(json.dumps(build_intent_manifest(), ensure_ascii=False, sort_keys=True, "
            "separators=(',', ':'), allow_nan=False))"
        )
        outputs: list[str] = []
        for seed in ("1", "8675309"):
            env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            outputs.append(result.stdout.strip())

        self.assertEqual(outputs[0], outputs[1])
        manifests = [json.loads(output) for output in outputs]
        self.assertEqual(manifests[0]["manifest_digest"], manifests[1]["manifest_digest"])
        self.assertEqual(
            manifests[0]["safety_vocabulary"]["digest"],
            manifests[1]["safety_vocabulary"]["digest"],
        )

    def test_independent_safety_change_rotates_both_digests_and_rejects_stale_candidate(self) -> None:
        baseline = build_intent_manifest()
        changed_values = (*baseline["safety_vocabulary"]["values"], "future_safety_flag")
        changed_safety_digest = canonical_json_sha256(
            {
                "version": baseline["safety_vocabulary"]["version"],
                "values": list(changed_values),
            }
        )
        changed_payload = deepcopy(baseline)
        changed_payload.pop("manifest_digest")
        changed_payload["safety_vocabulary"]["values"] = changed_values
        changed_payload["safety_vocabulary"]["digest"] = changed_safety_digest
        changed_payload["candidate_shape"]["safety_flags"] = changed_values
        changed_manifest_digest = canonical_json_sha256(changed_payload)

        self.assertNotEqual(changed_safety_digest, baseline["safety_vocabulary"]["digest"])
        self.assertNotEqual(changed_manifest_digest, baseline["manifest_digest"])

        stale_candidate = {
            "contract": {
                "manifest_schema_version": baseline["schema_version"],
                "manifest_digest": baseline["manifest_digest"],
                "safety_vocabulary_version": baseline["safety_vocabulary"]["version"],
                "safety_vocabulary_digest": baseline["safety_vocabulary"]["digest"],
            },
            "kind": "single",
            "mode": "action",
            "action": "rest",
            "slots": {"until": "morning"},
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [],
            "reason": "stale provider candidate",
        }
        changed_contract = ActiveIntentContract(
            manifest_schema_version=baseline["schema_version"],
            manifest_digest=changed_manifest_digest,
            safety_vocabulary_version=baseline["safety_vocabulary"]["version"],
            safety_vocabulary_digest=changed_safety_digest,
        )

        with self.assertRaises(ExternalIntentContractError) as raised:
            validate_external_intent_candidate(stale_candidate, _active_contract=changed_contract)

        self.assertEqual(raised.exception.code, "INTENT_CONTRACT_VERSION_MISMATCH")
        self.assertEqual(raised.exception.reason, "contract_version_mismatch")
        self.assertTrue(raised.exception.retriable)
        self.assertEqual(raised.exception.action, "refresh_manifest_and_regenerate_candidate")

    def test_candidate_schema_matches_canonical_safety_and_contract_envelope(self) -> None:
        schema = json.loads(schema_resource_text("intent_candidate.schema.json"))
        properties = schema["properties"]
        safety = properties["safety_flags"]
        contract = properties["contract"]

        self.assertEqual(safety["items"]["enum"], sorted(SAFETY_FLAG_VALUES))
        self.assertTrue(safety["uniqueItems"])
        self.assertEqual(safety["minItems"], 0)
        self.assertEqual(safety["maxItems"], 6)
        self.assertFalse(contract["additionalProperties"])
        self.assertEqual(
            contract["required"],
            [
                "manifest_schema_version",
                "manifest_digest",
                "safety_vocabulary_version",
                "safety_vocabulary_digest",
            ],
        )
        for key in ("manifest_schema_version", "safety_vocabulary_version"):
            self.assertEqual(contract["properties"][key]["minLength"], 1)
            self.assertEqual(contract["properties"][key]["maxLength"], 32)
        for key in ("manifest_digest", "safety_vocabulary_digest"):
            self.assertEqual(contract["properties"][key]["minLength"], 64)
            self.assertEqual(contract["properties"][key]["maxLength"], 64)
            self.assertEqual(contract["properties"][key]["pattern"], "^[0-9a-f]{64}$")

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
            [
                {
                    "name": "random_source",
                    "any_of": ("table", "dice"),
                    "required": True,
                    "cardinality": "exactly_one",
                    "binding_rule": "slots_only",
                }
            ],
        )
        random_slots = {slot["name"]: slot for slot in random_table["slots"]}
        self.assertEqual(random_slots["table"]["type"], "random_table_id")
        self.assertEqual(random_slots["dice"]["type"], "dice_expr")

        routine = actions["routine"]
        self.assertEqual(
            routine["requirement_groups"],
            [
                {
                    "name": "routine_scope",
                    "any_of": ("task", "target"),
                    "required": True,
                    "cardinality": "at_least_one",
                    "binding_rule": "source_user_text_fallback",
                }
            ],
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

    def test_manifest_slots_and_groups_are_exact_registry_contract_projections(self) -> None:
        registry = get_default_action_registry()
        manifest = build_intent_manifest(registry=registry)
        actions = {action["name"]: action for action in manifest["actions"]}

        for spec in registry.all():
            expected_slots = [
                {
                    "name": slot.name,
                    "dest": slot.dest,
                    "description": slot.description,
                    "type": slot.binding_type,
                    "allowed_entity_types": slot.allowed_entity_types,
                    "aliases": slot.aliases,
                    "required": slot.required,
                    "default": slot.to_projection()["default"],
                    "ai_fillable": slot.ai_fillable,
                    "player_confirmation_required": slot.player_confirmation_required,
                }
                for slot in spec.slot_contract.slots
            ]
            expected_groups = [
                {
                    "name": group.name,
                    "any_of": group.members,
                    "required": group.required,
                    "cardinality": group.cardinality,
                    "binding_rule": group.binding_rule,
                }
                for group in spec.slot_contract.requirement_groups
            ]
            with self.subTest(action=spec.name):
                self.assertEqual(actions[spec.name]["slots"], expected_slots)
                self.assertEqual(actions[spec.name]["requirement_groups"], expected_groups)

    def test_group_behavior_change_rotates_manifest_digest_at_schema_v4(self) -> None:
        def registry_with_group(
            cardinality: str,
            binding_rule: str,
        ) -> ActionResolverRegistry:
            registry = ActionResolverRegistry()
            registry.register(
                ActionResolverSpec(
                    name="survey",
                    preview=lambda *_args: "preview\n",
                    response_template="action.md",
                    option_specs=(
                        ActionOptionSpec("target", "survey target"),
                        ActionOptionSpec("approach", "survey approach"),
                    ),
                    requirement_groups=(
                        ActionRequirementGroupSpec(
                            "survey_scope",
                            ("target", "approach"),
                            cardinality=cardinality,
                            binding_rule=binding_rule,
                        ),
                    ),
                )
            )
            return registry

        baseline = build_intent_manifest(
            registry=registry_with_group("at_least_one", "slots_only")
        )
        cardinality_changed = build_intent_manifest(
            registry=registry_with_group("exactly_one", "slots_only")
        )
        binding_rule_changed = build_intent_manifest(
            registry=registry_with_group("at_least_one", "source_user_text_fallback")
        )

        self.assertEqual(baseline["schema_version"], "4")
        self.assertEqual(cardinality_changed["schema_version"], "4")
        self.assertEqual(binding_rule_changed["schema_version"], "4")
        self.assertEqual(
            cardinality_changed["actions"][0]["requirement_groups"][0]["cardinality"],
            "exactly_one",
        )
        self.assertEqual(
            binding_rule_changed["actions"][0]["requirement_groups"][0]["binding_rule"],
            "source_user_text_fallback",
        )
        self.assertNotEqual(baseline["manifest_digest"], cardinality_changed["manifest_digest"])
        self.assertNotEqual(baseline["manifest_digest"], binding_rule_changed["manifest_digest"])

    def test_falsey_custom_registry_reaches_manifest_and_internal_prompt_projection(self) -> None:
        class FalseyRegistry(ActionResolverRegistry):
            def __bool__(self) -> bool:
                return False

        registry = FalseyRegistry()
        registry.register(
            ActionResolverSpec(
                name="survey",
                preview=lambda *_args: "preview\n",
                response_template="action.md",
                option_specs=(
                    ActionOptionSpec("target", "survey target", required=True, aliases=("subject",)),
                    ActionOptionSpec(
                        "approval",
                        "direct player approval",
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                    ActionOptionSpec("user_text", "source text", ai_fillable=False),
                ),
            )
        )
        manifest = build_intent_manifest(registry=registry)
        action = manifest["actions"][0]
        taxonomy_action = manifest["action_taxonomy"]["actions"][0]
        prompt_contract = internal_prompt_action_contract(action, taxonomy_action)
        slots = {slot["name"]: slot for slot in prompt_contract["slots"]}

        self.assertEqual([item["name"] for item in manifest["actions"]], ["survey"])
        self.assertEqual(slots["target"]["aliases"], ["subject"])
        self.assertTrue(slots["target"]["required"])
        self.assertFalse(slots["approval"]["ai_fillable"])
        self.assertTrue(slots["approval"]["player_confirmation_required"])
        self.assertNotIn("user_text", slots)


if __name__ == "__main__":
    unittest.main()
