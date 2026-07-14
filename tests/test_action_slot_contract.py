from __future__ import annotations

import argparse
from dataclasses import FrozenInstanceError
from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest import mock

from rpg_engine.actions import ActionResolverRegistry, get_default_action_registry
from rpg_engine.actions.base import ActionOptionSpec, ActionResolverSpec
from rpg_engine.actions.slot_contract import (
    ACTION_SLOT_CONTRACT_VERSION,
    ActionRequirementGroupSpec,
    build_action_slot_registry_projection,
)
from rpg_engine.actions.social import SOCIAL_RESOLVER
from rpg_engine.ai_intent.slot_contract import (
    ACTION_REQUIRED_SLOTS,
    ACTION_SLOT_BINDINGS,
    AI_SUPPLIED_CONFIRMATION_SLOTS,
    ENTITY_SLOT_TYPES,
    SLOT_ALIASES,
)
from rpg_engine.ai_intent.arbiter import duplicate_normalized_slots
from rpg_engine.ai_intent.binder import bind_intent_candidate
from rpg_engine.ai_intent.normalization import normalize_intent_candidate
from rpg_engine.ai_intent.prompts import internal_prompt_action_contract
from rpg_engine.cli import add_preview_parsers
from rpg_engine.intent_manifest import build_intent_manifest


def preview_stub(*_args: object) -> str:
    return "preview\n"


def deep_json_default() -> object:
    value: object = None
    for _index in range(sys.getrecursionlimit() + 100):
        value = [value]
    return value


def deep_tuple_default() -> object:
    value: object = None
    for _index in range(sys.getrecursionlimit() + 100):
        value = (value,)
    return value


def nested_object_default(depth: int) -> object:
    value: object = "leaf"
    for index in range(depth):
        value = {f"k{index}": value}
    return value


def resolver_spec(
    name: str = "survey",
    *,
    required_options: tuple[str, ...] = (),
    option_specs: tuple[ActionOptionSpec, ...] = (),
    requirement_groups: tuple[ActionRequirementGroupSpec, ...] = (),
) -> ActionResolverSpec:
    return ActionResolverSpec(
        name=name,
        preview=preview_stub,
        response_template="action.md",
        required_options=required_options,
        option_specs=option_specs,
        requirement_groups=requirement_groups,
    )


def assert_action_projection_parity(
    spec: ActionResolverSpec,
    action_manifest: dict[str, object],
) -> None:
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
    _assert_named_projection(spec.name, "slots", expected_slots, action_manifest.get("slots"))
    _assert_named_projection(
        spec.name,
        "requirement_groups",
        expected_groups,
        action_manifest.get("requirement_groups"),
    )


def assert_internal_prompt_projection_parity(
    spec: ActionResolverSpec,
    prompt: dict[str, object],
) -> None:
    expected_slots = []
    for slot in spec.slot_contract.slots:
        if slot.name == "user_text":
            continue
        item: dict[str, object] = {
            "name": slot.name,
            "type": slot.binding_type,
            "required": slot.required,
            "ai_fillable": slot.ai_fillable,
            "player_confirmation_required": slot.player_confirmation_required,
        }
        if slot.aliases:
            item["aliases"] = list(slot.aliases)
        if slot.allowed_entity_types:
            item["allowed_entity_types"] = list(slot.allowed_entity_types)
        if slot.default is not None:
            item["default"] = slot.to_projection()["default"]
        expected_slots.append(item)
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
    _assert_named_projection(spec.name, "prompt.slots", expected_slots, prompt.get("slots"))
    _assert_named_projection(
        spec.name,
        "prompt.requirement_groups",
        expected_groups,
        prompt.get("requirement_groups"),
    )


def _assert_named_projection(
    action: str,
    path: str,
    expected_items: list[dict[str, object]],
    actual_value: object,
) -> None:
    if not isinstance(actual_value, (list, tuple)):
        raise AssertionError(f"{action}.{path}: expected an ordered projection")
    actual_items = list(actual_value)
    if not all(isinstance(item, dict) for item in actual_items):
        raise AssertionError(f"{action}.{path}: every item must be an object")
    actual_names = [str(item.get("name")) for item in actual_items]
    if len(actual_names) != len(set(actual_names)):
        raise AssertionError(f"{action}.{path}: duplicate item names: {actual_names!r}")
    expected_names = [str(item["name"]) for item in expected_items]
    if actual_names != expected_names:
        raise AssertionError(
            f"{action}.{path}: expected names {expected_names!r}, got {actual_names!r}"
        )
    for expected, actual in zip(expected_items, actual_items, strict=True):
        name = str(expected["name"])
        if set(actual) != set(expected):
            raise AssertionError(
                f"{action}.{path}.{name}: expected fields {sorted(expected)!r}, "
                f"got {sorted(actual)!r}"
            )
        for field, expected_value in expected.items():
            actual_value = actual[field]
            if actual_value != expected_value:
                raise AssertionError(
                    f"{action}.{path}.{name}.{field}: "
                    f"expected {expected_value!r}, got {actual_value!r}"
                )


class ActionSlotContractTests(unittest.TestCase):
    def test_resolver_builds_frozen_sorted_defensive_projection(self) -> None:
        aliases = ("zone", "area")
        spec = resolver_spec(
            option_specs=(
                ActionOptionSpec("target", "survey target", required=True, aliases=aliases),
                ActionOptionSpec("approach", "survey approach"),
            )
        )

        contract = spec.slot_contract
        self.assertEqual(contract.action, "survey")
        self.assertEqual(tuple(slot.name for slot in contract.slots), ("approach", "target"))
        self.assertEqual(contract.slot("target").aliases, ("area", "zone"))
        self.assertEqual(spec.required_options, ("target",))
        self.assertEqual(tuple(option.name for option in spec.option_specs), ("approach", "target"))
        with self.assertRaises(FrozenInstanceError):
            contract.slot("target").required = False  # type: ignore[misc]

        first = contract.to_projection()
        first["slots"][1]["aliases"].append("mutated")
        second = contract.to_projection()
        self.assertEqual(second["slots"][1]["aliases"], ["area", "zone"])

        default_source = {"nested": ["stable"]}
        default_spec = resolver_spec(
            option_specs=(ActionOptionSpec("detail", "detail", default=default_source),)
        )
        default_source["nested"].append("source mutation")
        normalized_default = default_spec.option_specs[0].default
        self.assertEqual(dict(normalized_default), {"nested": ("stable",)})
        with self.assertRaises(TypeError):
            normalized_default["nested"] = ("mutated",)
        with self.assertRaises(TypeError):
            dict.__setitem__(normalized_default, "nested", ("mutated",))
        self.assertEqual(default_spec.slot_contract.to_projection()["slots"][0]["default"], {"nested": ["stable"]})

        reused_default_spec = resolver_spec("resurvey", option_specs=default_spec.option_specs)
        self.assertEqual(
            reused_default_spec.slot_contract.slot("detail").to_projection()["default"],
            {"nested": ["stable"]},
        )
        self.assertIsNot(
            reused_default_spec.slot_contract.slot("detail").default,
            normalized_default,
        )

        deep_default_spec = resolver_spec(
            "deep",
            option_specs=(
                ActionOptionSpec("detail", "detail", default=nested_object_default(500)),
            ),
        )
        deep_reused_spec = resolver_spec(
            "deep_copy",
            option_specs=deep_default_spec.option_specs,
        )
        deep_registry = ActionResolverRegistry()
        deep_registry.register(deep_default_spec)
        deep_registry.register(deep_reused_spec)
        self.assertEqual(deep_registry.names(), ["deep", "deep_copy"])

        original_recursion_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(5000)
            very_deep_spec = resolver_spec(
                "very_deep",
                option_specs=(
                    ActionOptionSpec(
                        "detail",
                        "detail",
                        default=nested_object_default(1100),
                    ),
                ),
            )
        finally:
            sys.setrecursionlimit(original_recursion_limit)
        very_deep_projection = very_deep_spec.slot_contract.to_projection()
        self.assertEqual(very_deep_projection["slots"][0]["name"], "detail")
        very_deep_registry = ActionResolverRegistry()
        with self.assertRaisesRegex(
            ValueError,
            r"very_deep\.slots\.detail\.default.*deterministic JSON-safe",
        ):
            very_deep_registry.register(very_deep_spec)
        self.assertEqual(very_deep_registry.names(), [])

    def test_legacy_required_option_is_synthesized_once_with_binder_defaults(self) -> None:
        spec = resolver_spec(required_options=("target",))

        target = spec.slot_contract.slot("target")
        self.assertEqual(target.binding_type, "text")
        self.assertTrue(target.required)
        self.assertEqual(target.aliases, ())
        self.assertEqual(target.allowed_entity_types, ())
        self.assertIsNone(target.default)
        self.assertTrue(target.ai_fillable)
        self.assertFalse(target.player_confirmation_required)
        self.assertEqual(tuple(option.name for option in spec.option_specs), ("target",))

    def test_legacy_and_canonical_required_declarations_conflict(self) -> None:
        with self.assertRaisesRegex(ValueError, r"survey.*required_options.*target"):
            resolver_spec(
                required_options=("target",),
                option_specs=(ActionOptionSpec("target", "survey target", required=True),),
            )

    def test_slot_contract_rejects_nondeterministic_and_invalid_inputs(self) -> None:
        cases = (
            (
                "option_specs exact tuple",
                lambda: ActionResolverSpec(
                    name="survey",
                    preview=preview_stub,
                    response_template="action.md",
                    option_specs=[ActionOptionSpec("target", "target")],  # type: ignore[arg-type]
                ),
            ),
            (
                "duplicate slot",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("target", "one"), ActionOptionSpec("target", "two"))
                ),
            ),
            (
                "alias collision",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec("target", "target", aliases=("approach",)),
                        ActionOptionSpec("approach", "approach"),
                    )
                ),
            ),
            (
                "allowed_entity_types",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec(
                            "target",
                            "target",
                            binding_type="text",
                            allowed_entity_types=("character",),
                        ),
                    )
                ),
            ),
            (
                "confirmation",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec(
                            "ready_state",
                            "ready state",
                            ai_fillable=True,
                            player_confirmation_required=True,
                        ),
                    )
                ),
            ),
            (
                "confirmation default",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec(
                            "ready_state",
                            "ready state",
                            default="ready",
                            ai_fillable=False,
                            player_confirmation_required=True,
                        ),
                    )
                ),
            ),
            (
                "source-only user_text",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("user_text", "source text"),)
                ),
            ),
            (
                "reserved user_text alias",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec(
                            "target",
                            "target",
                            aliases=("user_text",),
                        ),
                    )
                ),
            ),
            (
                "JSON-safe default",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("target", "target", default={"bad"}),),
                ),
            ),
            (
                "exact string JSON object key",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("target", "target", default={1: "bad"}),),
                ),
            ),
            (
                "UTF-8 description",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("target", "bad\ud800description"),),
                ),
            ),
            (
                "UTF-8 default",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("target", "target", default="bad\ud800default"),),
                ),
            ),
            (
                "deep JSON default",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec("target", "target", default=deep_json_default()),
                    ),
                ),
            ),
            (
                "deep tuple default",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec("target", "target", default=deep_tuple_default()),
                    ),
                ),
            ),
            (
                "long slot name",
                lambda: resolver_spec(
                    option_specs=(ActionOptionSpec("s" * 61, "target"),),
                ),
            ),
            (
                "long slot alias",
                lambda: resolver_spec(
                    option_specs=(
                        ActionOptionSpec("target", "target", aliases=("a" * 61,)),
                    ),
                ),
            ),
            (
                "too many AI-fillable slots",
                lambda: resolver_spec(
                    option_specs=tuple(
                        ActionOptionSpec(f"s{index}", f"slot {index}")
                        for index in range(25)
                    ),
                ),
            ),
        )
        for label, build in cases:
            with self.subTest(label=label), self.assertRaises((TypeError, ValueError)):
                build()

    def test_requirement_groups_fail_closed_on_duplicates_unknown_members_and_aliases(self) -> None:
        target = ActionOptionSpec("target", "target", aliases=("object",))
        approach = ActionOptionSpec("approach", "approach")
        invalid_groups = (
            (
                ActionRequirementGroupSpec("scope", ("target", "target")),
                "duplicate member",
            ),
            (
                ActionRequirementGroupSpec("scope", ("target", "missing")),
                "unknown member",
            ),
            (
                ActionRequirementGroupSpec("object", ("target", "approach")),
                "alias collision",
            ),
        )
        for group, expected in invalid_groups:
            with self.subTest(group=group), self.assertRaisesRegex(ValueError, rf"survey.*{expected}"):
                resolver_spec(option_specs=(target, approach), requirement_groups=(group,))

        with self.assertRaisesRegex(ValueError, r"survey.*reserved source slot.*user_text"):
            resolver_spec(
                option_specs=(
                    ActionOptionSpec("user_text", "source text", ai_fillable=False),
                    approach,
                ),
                requirement_groups=(
                    ActionRequirementGroupSpec("scope", ("user_text", "approach")),
                ),
            )

    def test_registry_slot_projection_is_atomic_sorted_and_digest_stable(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid UTF-8"):
            build_action_slot_registry_projection((), version="v\ud800")

        registry = ActionResolverRegistry()
        registry.register(resolver_spec("zeta", option_specs=(ActionOptionSpec("target", "target"),)))
        before_names = registry.names()
        before_taxonomy = registry.taxonomy_projection()
        before_slots = registry.slot_projection()

        registered_zeta = registry.get("zeta")
        self.assertIsNotNone(registered_zeta)
        object.__setattr__(registered_zeta, "name", "tampered")
        with self.assertRaisesRegex(ValueError, r"zeta\.resolver name mismatch"):
            registry.register(
                resolver_spec(
                    "alpha",
                    option_specs=(ActionOptionSpec("target", "target"),),
                )
            )
        self.assertEqual(registry.names(), ["zeta"])
        object.__setattr__(registered_zeta, "name", "zeta")
        self.assertEqual(registry.taxonomy_projection(), before_taxonomy)
        self.assertEqual(registry.slot_projection(), before_slots)

        invalid = resolver_spec("alpha", option_specs=(ActionOptionSpec("target", "target"),))
        object.__setattr__(invalid.slot_contract, "action", "other")
        with self.assertRaisesRegex(ValueError, "alpha.slot_contract action mismatch"):
            registry.register(invalid)

        invalid_spec_name = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target"),),
        )
        object.__setattr__(invalid_spec_name, "name", 1)
        with self.assertRaisesRegex(
            ValueError,
            r"slot projection entries\[\d+\]\.action",
        ):
            registry.register(invalid_spec_name)

        unhashable_spec_name = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target"),),
        )
        object.__setattr__(unhashable_spec_name, "name", [])
        with self.assertRaisesRegex(
            ValueError,
            r"slot projection entries\[0\]\.action",
        ):
            registry.register(unhashable_spec_name)

        class StringSubclass(str):
            pass

        invalid_action_type = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target"),),
        )
        object.__setattr__(
            invalid_action_type.slot_contract,
            "action",
            StringSubclass("alpha"),
        )
        with self.assertRaisesRegex(ValueError, r"alpha\.slot_contract\.action"):
            registry.register(invalid_action_type)

        invalid_leaf = resolver_spec(
            "alpha",
            option_specs=(
                ActionOptionSpec("approach", "approach"),
                ActionOptionSpec("target", "target"),
            ),
        )
        object.__setattr__(invalid_leaf.slot_contract.slot("approach"), "aliases", ("target",))
        with self.assertRaisesRegex(ValueError, r"alpha.*alias collision.*target"):
            registry.register(invalid_leaf)

        invalid_compatibility = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target"),),
        )
        object.__setattr__(invalid_compatibility, "option_specs", ())
        with self.assertRaisesRegex(
            ValueError,
            r"alpha\.slot_contract compatibility mismatch: option_specs",
        ):
            registry.register(invalid_compatibility)

        mutable_default = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target", default={"mode": "stable"}),),
        )
        object.__setattr__(mutable_default.slot_contract.slot("target"), "default", {"mode": "stable"})
        with self.assertRaisesRegex(ValueError, r"alpha.*default must be frozen"):
            registry.register(mutable_default)

        mutable_compatibility = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target", default={"mode": "stable"}),),
        )
        object.__setattr__(
            mutable_compatibility,
            "option_specs",
            (ActionOptionSpec("target", "target", default={"mode": "stable"}),),
        )
        with self.assertRaisesRegex(
            ValueError,
            r"alpha\.slot_contract compatibility mismatch: option_specs",
        ):
            registry.register(mutable_compatibility)

        foreign_compatibility = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target", default={"mode": "stable"}),),
        )
        donor = resolver_spec(
            "donor",
            option_specs=(ActionOptionSpec("target", "target", default={"mode": "stable"}),),
        )
        object.__setattr__(foreign_compatibility, "option_specs", donor.option_specs)
        with self.assertRaisesRegex(
            ValueError,
            r"alpha\.slot_contract compatibility mismatch: option_specs\.default",
        ):
            registry.register(foreign_compatibility)

        non_exact_compatibility = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target", required=True),),
        )
        object.__setattr__(non_exact_compatibility.option_specs[0], "required", 1)
        with self.assertRaisesRegex(
            ValueError,
            r"alpha\.slot_contract compatibility mismatch: option_specs",
        ):
            registry.register(non_exact_compatibility)

        backing_default = {"mode": "stable"}
        external_mapping_proxy = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target", default=backing_default),),
        )
        object.__setattr__(
            external_mapping_proxy.slot_contract.slot("target"),
            "default",
            MappingProxyType(backing_default),
        )
        with self.assertRaisesRegex(ValueError, r"alpha.*default must be frozen"):
            registry.register(external_mapping_proxy)

        noncanonical_object_default = resolver_spec(
            "alpha",
            option_specs=(
                ActionOptionSpec("target", "target", default={"a": 1, "b": 2}),
            ),
        )
        object.__setattr__(
            noncanonical_object_default.slot_contract.slot("target").default,
            "_FrozenJSONMap__items",
            (("b", 2), ("a", 1)),
        )
        with self.assertRaisesRegex(ValueError, r"alpha.*default must be frozen"):
            registry.register(noncanonical_object_default)

        duplicate_object_default = resolver_spec(
            "alpha",
            option_specs=(
                ActionOptionSpec("target", "target", default={"a": 1, "b": 2}),
            ),
        )
        object.__setattr__(
            duplicate_object_default.slot_contract.slot("target").default,
            "_FrozenJSONMap__items",
            (("a", 1), ("a", 1)),
        )
        with self.assertRaisesRegex(ValueError, r"alpha.*default must be frozen"):
            registry.register(duplicate_object_default)

        cyclic_object_default = resolver_spec(
            "alpha",
            option_specs=(ActionOptionSpec("target", "target", default={"self": None}),),
        )
        cyclic_default = cyclic_object_default.slot_contract.slot("target").default
        object.__setattr__(
            cyclic_default,
            "_FrozenJSONMap__items",
            (("self", cyclic_default),),
        )
        with self.assertRaisesRegex(ValueError, r"alpha.*default must be frozen"):
            registry.register(cyclic_object_default)

        self.assertEqual(registry.names(), before_names)
        self.assertEqual(registry.taxonomy_projection(), before_taxonomy)
        self.assertEqual(registry.slot_projection(), before_slots)
        self.assertEqual(before_slots["version"], ACTION_SLOT_CONTRACT_VERSION)
        self.assertEqual([action["action"] for action in before_slots["actions"]], ["zeta"])
        self.assertRegex(before_slots["digest"], r"^[0-9a-f]{64}$")

    def test_registry_slot_projection_wire_is_stable_across_hash_seeds(self) -> None:
        script = (
            "import json; "
            "from rpg_engine.actions import get_default_action_registry; "
            "print(json.dumps(get_default_action_registry().slot_projection(), "
            "ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False))"
        )
        outputs = []
        for seed in ("1", "8675309"):
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
                env={**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                check=True,
            )
            outputs.append(result.stdout.strip())

        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(json.loads(outputs[0])["digest"], json.loads(outputs[1])["digest"])

    def test_builtin_resolvers_own_complete_slot_metadata(self) -> None:
        registry = get_default_action_registry()
        expected = {
            "combat": {
                "target": ("entity", ("threat", "character", "species"), ("enemy", "foe"), True),
                "weapon": ("entity", ("equipment", "item"), (), True),
                "ammo": ("entity", ("item",), (), True),
                "distance": ("text", (), ("range",), True),
            },
            "craft": {
                "project": ("entity", ("project",), (), False),
                "target": ("text_or_entity", (), ("item", "output"), True),
                "materials": ("text_list", (), (), False),
            },
            "explore": {
                "target": ("entity_or_text", (), ("clue", "object"), True),
                "location": ("entity", ("location",), ("place",), False),
            },
            "gather": {
                "target": ("entity", ("plant", "item", "material", "crop_plot"), ("resource",), True),
                "location": ("entity", ("location",), ("destination", "place"), False),
            },
            "random_table": {
                "table": ("random_table_id", (), ("table_id",), False),
                "dice": ("dice_expr", (), (), False),
            },
            "rest": {"until": ("text", (), ("time",), False)},
            "routine": {
                "task": ("text", (), (), False),
                "target": ("entity_or_text", (), ("object",), False),
            },
            "social": {
                "npc": ("entity", ("character", "faction", "faction_state"), ("character", "faction"), True),
                "topic": ("text", (), ("question",), False),
            },
            "travel": {
                "destination": ("entity", ("location",), ("place", "target", "to"), True),
                "palette_id": ("text", (), (), False),
            },
        }
        for action, slots in expected.items():
            contract = registry.get(action).slot_contract  # type: ignore[union-attr]
            for name, value in slots.items():
                with self.subTest(action=action, slot=name):
                    slot = contract.slot(name)
                    self.assertEqual(
                        (slot.binding_type, slot.allowed_entity_types, slot.aliases, slot.required),
                        value,
                    )

        self.assertNotIn("target", {slot.name for slot in registry.get("social").slot_contract.slots})  # type: ignore[union-attr]
        self.assertEqual(registry.get("gather").slot_contract.normalize_name("destination"), "location")  # type: ignore[union-attr]

        ready_state = registry.get("combat").slot_contract.slot("ready_state")  # type: ignore[union-attr]
        self.assertFalse(ready_state.ai_fillable)
        self.assertTrue(ready_state.player_confirmation_required)

    def test_builtin_requirement_groups_encode_cardinality_and_source_text_fallback(self) -> None:
        registry = get_default_action_registry()
        random_group = registry.get("random_table").slot_contract.requirement_groups[0]  # type: ignore[union-attr]
        routine_group = registry.get("routine").slot_contract.requirement_groups[0]  # type: ignore[union-attr]

        self.assertEqual(random_group.name, "random_source")
        self.assertEqual(random_group.members, ("table", "dice"))
        self.assertEqual(random_group.cardinality, "exactly_one")
        self.assertEqual(random_group.binding_rule, "slots_only")
        self.assertEqual(routine_group.name, "routine_scope")
        self.assertEqual(routine_group.members, ("task", "target"))
        self.assertEqual(routine_group.cardinality, "at_least_one")
        self.assertEqual(routine_group.binding_rule, "source_user_text_fallback")

        random_contract = registry.get("random_table").slot_contract  # type: ignore[union-attr]
        self.assertEqual(random_contract.evaluate_requirements({}).missing, ("table or dice",))
        self.assertEqual(random_contract.evaluate_requirements({"table": "weather"}).errors, ())
        self.assertEqual(random_contract.evaluate_requirements({"dice": "d20"}).errors, ())
        self.assertEqual(
            random_contract.evaluate_requirements({"table": "weather", "dice": "d20"}).errors,
            ("random_source requires exactly one of: table, dice",),
        )
        routine_contract = registry.get("routine").slot_contract  # type: ignore[union-attr]
        self.assertEqual(routine_contract.evaluate_requirements({}).missing, ("task or target",))
        self.assertEqual(routine_contract.evaluate_requirements({"user_text": "巡视围墙"}).missing, ())

    def test_legacy_import_path_is_a_read_only_projection_not_a_parallel_owner(self) -> None:
        registry = get_default_action_registry()
        for spec in registry.all():
            expected_bindings = {}
            expected_aliases = {}
            expected_required = [slot.name for slot in spec.slot_contract.slots if slot.required]
            for slot in spec.slot_contract.slots:
                if slot.name == "user_text":
                    continue
                if slot.binding_type == "entity":
                    expected_bindings[slot.name] = (
                        slot.allowed_entity_types[0]
                        if len(slot.allowed_entity_types) == 1
                        else slot.allowed_entity_types
                    )
                else:
                    expected_bindings[slot.name] = slot.binding_type
                expected_aliases.update({alias: slot.name for alias in slot.aliases})
            expected_required.extend(
                group.members[0]
                if group.binding_rule == "source_user_text_fallback"
                else " or ".join(group.members)
                for group in spec.slot_contract.requirement_groups
            )
            with self.subTest(action=spec.name):
                self.assertEqual(dict(ACTION_SLOT_BINDINGS[spec.name]), expected_bindings)
                self.assertEqual(dict(SLOT_ALIASES[spec.name]), expected_aliases)
                self.assertEqual(ACTION_REQUIRED_SLOTS.get(spec.name, ()), tuple(expected_required))
                self.assertEqual(
                    AI_SUPPLIED_CONFIRMATION_SLOTS.get(spec.name, frozenset()),
                    frozenset(
                        slot.name
                        for slot in spec.slot_contract.slots
                        if slot.player_confirmation_required
                    ),
                )

        self.assertNotIn("target", ACTION_SLOT_BINDINGS["social"])
        self.assertNotIn("destination", ACTION_SLOT_BINDINGS["gather"])
        self.assertNotIn("user_text", ACTION_SLOT_BINDINGS["travel"])
        self.assertEqual(ENTITY_SLOT_TYPES, {"location", "entity_or_text", "text_or_entity"})
        self.assertEqual(SLOT_ALIASES["gather"]["destination"], "location")
        with self.assertRaises(TypeError):
            ACTION_SLOT_BINDINGS["travel"]["destination"] = "text"  # type: ignore[index]

        optional_registry = ActionResolverRegistry()
        optional_registry.register(
            resolver_spec(
                option_specs=(
                    ActionOptionSpec("target", "target"),
                    ActionOptionSpec("approach", "approach"),
                ),
                requirement_groups=(
                    ActionRequirementGroupSpec(
                        "optional_scope",
                        ("target", "approach"),
                        required=False,
                    ),
                ),
            )
        )
        with mock.patch(
            "rpg_engine.actions.get_default_action_registry",
            return_value=optional_registry,
        ):
            self.assertEqual(ACTION_REQUIRED_SLOTS.get("survey", ()), ())

    def test_social_target_remains_low_level_only_and_is_not_added_to_ai_contract(self) -> None:
        validation = SOCIAL_RESOLVER.request_contract(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            {},
            SimpleNamespace(npc=None, target="legacy target", palette_id=None),
        )

        self.assertTrue(validation.ok)
        self.assertNotIn("target", {slot.name for slot in SOCIAL_RESOLVER.slot_contract.slots})

    def test_binder_uses_group_cardinality_and_source_user_text_rule(self) -> None:
        conn = sqlite3.connect(":memory:")
        cases = (
            ({}, "missing", ("table or dice",), ()),
            ({"table": "weather"}, "bound", (), ()),
            ({"dice": "d20"}, "bound", (), ()),
            (
                {"table": "weather", "dice": "d20"},
                "invalid",
                (),
                ("random_source requires exactly one of: table, dice",),
            ),
        )
        for slots, status, missing, errors in cases:
            with self.subTest(slots=slots):
                candidate = normalize_intent_candidate(
                    {"kind": "single", "mode": "action", "action": "random_table", "slots": slots},
                    user_text="掷骰",
                )
                bound = bind_intent_candidate(conn, candidate)
                self.assertEqual(bound.binding_status, status)
                self.assertEqual(bound.missing_required, missing)
                self.assertEqual(bound.errors, errors)

        routine = bind_intent_candidate(
            conn,
            normalize_intent_candidate(
                {"kind": "single", "mode": "action", "action": "routine", "slots": {}},
                user_text="巡视围墙",
            ),
        )
        self.assertEqual(routine.binding_status, "bound")
        self.assertEqual(routine.missing_required, ())
        self.assertEqual(routine.options, {"user_text": "巡视围墙"})

    def test_falsey_custom_registry_drives_alias_type_requirement_and_confirmation(self) -> None:
        class FalseyRegistry(ActionResolverRegistry):
            def __bool__(self) -> bool:
                return False

        registry = FalseyRegistry()
        registry.register(
            resolver_spec(
                option_specs=(
                    ActionOptionSpec("target", "survey target", required=True, aliases=("subject",)),
                    ActionOptionSpec(
                        "approval",
                        "direct player approval",
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                    ActionOptionSpec("private_note", "kernel-owned note", ai_fillable=False),
                )
            )
        )
        candidate = normalize_intent_candidate(
            {
                "kind": "single",
                "mode": "action",
                "action": "survey",
                "slots": {
                    "subject": "north wall",
                    "approval": "yes",
                    "private_note": "AI must not set this",
                    "destination": "default leak",
                },
            },
            registry=registry,
            user_text="survey the north wall",
        )
        bound = bind_intent_candidate(sqlite3.connect(":memory:"), candidate, registry=registry)

        self.assertEqual(bound.options["target"], "north wall")
        self.assertNotIn("destination", bound.options)
        self.assertNotIn("approval", bound.options)
        self.assertNotIn("private_note", bound.options)
        self.assertIn("approval requires direct player confirmation", bound.needs_confirmation)
        self.assertIn("ignored AI-supplied non-fillable slot: private_note", bound.warnings)
        self.assertEqual(
            bound.decision_trace["binder"]["slot_trace"]["private_note"]["reason"],
            "not_ai_fillable",
        )
        self.assertEqual(
            bound.decision_trace["binder"]["allowed_options"],
            ["approval", "private_note", "target"],
        )
        self.assertEqual(duplicate_normalized_slots(candidate, registry=registry), ())

        duplicate = normalize_intent_candidate(
            {
                "kind": "single",
                "mode": "action",
                "action": "survey",
                "slots": {"target": "north wall", "subject": "south wall"},
            },
            registry=registry,
        )
        self.assertEqual(duplicate_normalized_slots(duplicate, registry=registry), ("target",))
        duplicate_bound = bind_intent_candidate(
            sqlite3.connect(":memory:"),
            duplicate,
            registry=registry,
        )
        self.assertEqual(duplicate_bound.binding_status, "invalid")
        self.assertIn("duplicate normalized slot: target", duplicate_bound.errors)
        self.assertEqual(duplicate_bound.options["target"], "north wall")

        whitespace_duplicate = normalize_intent_candidate(
            {
                "kind": "single",
                "mode": "action",
                "action": "survey",
                "slots": {"target": "north wall", " target ": "south wall"},
            },
            registry=registry,
        )
        whitespace_duplicate_bound = bind_intent_candidate(
            sqlite3.connect(":memory:"),
            whitespace_duplicate,
            registry=registry,
        )
        self.assertEqual(whitespace_duplicate_bound.binding_status, "invalid")
        self.assertIn(
            "duplicate normalized slot: target",
            whitespace_duplicate_bound.errors,
        )

        confirmation_registry = ActionResolverRegistry()
        confirmation_registry.register(
            resolver_spec(
                option_specs=(
                    ActionOptionSpec(
                        "approval",
                        "direct player approval",
                        required=True,
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                )
            )
        )
        confirmation = bind_intent_candidate(
            sqlite3.connect(":memory:"),
            normalize_intent_candidate(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "survey",
                    "slots": {},
                },
                registry=confirmation_registry,
            ),
            registry=confirmation_registry,
        )
        self.assertEqual(confirmation.binding_status, "ambiguous")
        self.assertEqual(confirmation.missing_required, ())
        self.assertEqual(
            confirmation.needs_confirmation,
            ("approval requires direct player confirmation",),
        )

        group_registry = ActionResolverRegistry()
        group_registry.register(
            resolver_spec(
                option_specs=(
                    ActionOptionSpec(
                        "approve",
                        "approve directly",
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                    ActionOptionSpec(
                        "decline",
                        "decline directly",
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                ),
                requirement_groups=(
                    ActionRequirementGroupSpec(
                        "direct_choice",
                        ("approve", "decline"),
                    ),
                ),
            )
        )
        group_confirmation = bind_intent_candidate(
            sqlite3.connect(":memory:"),
            normalize_intent_candidate(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "survey",
                    "slots": {},
                },
                registry=group_registry,
            ),
            registry=group_registry,
        )
        self.assertEqual(group_confirmation.binding_status, "ambiguous")
        self.assertEqual(group_confirmation.missing_required, ())
        self.assertEqual(
            group_confirmation.needs_confirmation,
            ("direct_choice requires direct player confirmation: one of approve, decline",),
        )

        fallback_group_registry = ActionResolverRegistry()
        fallback_group_registry.register(
            resolver_spec(
                option_specs=(
                    ActionOptionSpec(
                        "approve",
                        "approve directly",
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                    ActionOptionSpec(
                        "decline",
                        "decline directly",
                        ai_fillable=False,
                        player_confirmation_required=True,
                    ),
                ),
                requirement_groups=(
                    ActionRequirementGroupSpec(
                        "direct_choice",
                        ("approve", "decline"),
                        binding_rule="source_user_text_fallback",
                    ),
                ),
            )
        )
        fallback_group_confirmation = bind_intent_candidate(
            sqlite3.connect(":memory:"),
            normalize_intent_candidate(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "survey",
                    "slots": {},
                },
                registry=fallback_group_registry,
                user_text="yes",
            ),
            registry=fallback_group_registry,
        )
        self.assertEqual(fallback_group_confirmation.binding_status, "ambiguous")
        self.assertEqual(fallback_group_confirmation.missing_required, ())
        self.assertEqual(
            fallback_group_confirmation.needs_confirmation,
            ("direct_choice requires direct player confirmation: one of approve, decline",),
        )

    def test_low_level_cli_keeps_required_classification_in_kernel(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="action", required=True)
        add_preview_parsers(subparsers, get_default_action_registry())

        palette = parser.parse_args(
            ["travel", "dummy-campaign", "--palette-id", "pal:loc:test"]
        )
        missing = parser.parse_args(["combat", "dummy-campaign"])

        self.assertIsNone(palette.destination)
        self.assertEqual(palette.palette_id, "pal:loc:test")
        self.assertIsNone(missing.target)
        self.assertIsNone(missing.weapon)

    def test_binder_preserves_stale_social_and_gather_alias_boundaries(self) -> None:
        conn = sqlite3.connect(":memory:")
        social = bind_intent_candidate(
            conn,
            normalize_intent_candidate(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "social",
                    "slots": {"target": "legacy npc"},
                },
                user_text="找 legacy npc",
            ),
        )
        gather = bind_intent_candidate(
            conn,
            normalize_intent_candidate(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "gather",
                    "slots": {"destination": "creek", "target": "herb"},
                },
                user_text="去 creek 采 herb",
            ),
        )

        self.assertIn("ignored slot outside resolver contract: target", social.warnings)
        self.assertIn("npc", social.missing_required)
        self.assertNotIn("target", social.options)
        self.assertNotIn("ignored slot outside resolver contract: destination", gather.warnings)
        self.assertIn("location", gather.decision_trace["binder"]["slot_trace"])
        self.assertNotIn("destination", gather.decision_trace["binder"]["slot_trace"])

    def test_builtin_required_matrix_and_optional_rest_are_deterministic(self) -> None:
        registry = get_default_action_registry()
        expected = {
            "combat": ("ammo", "distance", "target", "weapon"),
            "craft": ("target",),
            "explore": ("target",),
            "gather": ("target",),
            "random_table": ("table or dice",),
            "rest": (),
            "routine": ("task or target",),
            "social": ("npc",),
            "travel": ("destination",),
        }
        for action, missing in expected.items():
            with self.subTest(action=action):
                contract = registry.get(action).slot_contract  # type: ignore[union-attr]
                self.assertEqual(contract.evaluate_requirements({}).missing, missing)

        routine = registry.get("routine").slot_contract  # type: ignore[union-attr]
        self.assertEqual(routine.evaluate_requirements({"user_text": "巡视"}).missing, ())

    def test_default_request_contract_enforces_groups_and_preserves_falsey_missing_semantics(self) -> None:
        spec = resolver_spec(
            option_specs=(
                ActionOptionSpec("table", "table"),
                ActionOptionSpec("dice", "dice"),
                ActionOptionSpec("count", "count", required=True),
            ),
            requirement_groups=(
                ActionRequirementGroupSpec(
                    "random_source",
                    ("table", "dice"),
                    cardinality="exactly_one",
                ),
            ),
        )

        missing = spec.request_contract(
            None,  # type: ignore[arg-type]
            sqlite3.connect(":memory:"),
            {},
            SimpleNamespace(table=None, dice=None, count=0, user_text=""),
        )
        conflicting = spec.request_contract(
            None,  # type: ignore[arg-type]
            sqlite3.connect(":memory:"),
            {},
            {"table": "weather", "dice": "d20", "count": 1},
        )

        self.assertEqual(missing.missing_required, ("count", "table or dice"))
        self.assertEqual(missing.errors, ())
        self.assertEqual(
            conflicting.errors,
            ("random_source requires exactly one of: table, dice",),
        )
        resolution = spec.resolve_contract(
            None,  # type: ignore[arg-type]
            sqlite3.connect(":memory:"),
            {},
            {"table": "weather", "dice": "d20", "count": 1},
        )
        self.assertEqual(resolution.status, "blocked")
        self.assertIn("random_source requires exactly one of: table, dice", resolution.warnings)


    def test_manifest_binder_and_internal_prompt_parity_has_precise_paths(self) -> None:
        registry = get_default_action_registry()
        manifest = build_intent_manifest(registry=registry)
        actions = {action["name"]: action for action in manifest["actions"]}
        taxonomy = {action["name"]: action for action in manifest["action_taxonomy"]["actions"]}

        for spec in registry.all():
            with self.subTest(action=spec.name):
                assert_action_projection_parity(spec, actions[spec.name])
                prompt = internal_prompt_action_contract(actions[spec.name], taxonomy[spec.name])
                assert_internal_prompt_projection_parity(spec, prompt)

        broken = deepcopy(actions["travel"])
        next(slot for slot in broken["slots"] if slot["name"] == "destination")["aliases"] = ()
        with self.assertRaisesRegex(AssertionError, r"travel\.slots\.destination\.aliases"):
            assert_action_projection_parity(registry.get("travel"), broken)  # type: ignore[arg-type]

        extra = deepcopy(actions["travel"])
        extra["slots"].append(deepcopy(extra["slots"][0]))
        with self.assertRaisesRegex(AssertionError, r"travel\.slots: duplicate item names"):
            assert_action_projection_parity(registry.get("travel"), extra)  # type: ignore[arg-type]

        broken_group = deepcopy(actions["random_table"])
        broken_group["requirement_groups"][0]["cardinality"] = "at_least_one"
        with self.assertRaisesRegex(
            AssertionError,
            r"random_table\.requirement_groups\.random_source\.cardinality",
        ):
            assert_action_projection_parity(
                registry.get("random_table"),  # type: ignore[arg-type]
                broken_group,
            )

    def test_binding_is_read_only_for_connection_state(self) -> None:
        conn = sqlite3.connect(":memory:")
        before_changes = conn.total_changes
        before_transaction = conn.in_transaction

        bound = bind_intent_candidate(
            conn,
            normalize_intent_candidate(
                {
                    "kind": "single",
                    "mode": "action",
                    "action": "random_table",
                    "slots": {"dice": "2d6+1"},
                },
                user_text="掷骰",
            ),
        )

        self.assertEqual(bound.binding_status, "bound")
        self.assertEqual(conn.total_changes, before_changes)
        self.assertEqual(conn.in_transaction, before_transaction)


if __name__ == "__main__":
    unittest.main()
