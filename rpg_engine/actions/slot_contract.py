from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ..canonical_json import canonical_json_sha256


ACTION_SLOT_CONTRACT_VERSION = "1"
MAX_ACTION_CANDIDATE_SLOTS = 24
MAX_ACTION_SLOT_IDENTIFIER_LENGTH = 60
SLOT_BINDING_TYPES = frozenset(
    {
        "text",
        "text_list",
        "dice_expr",
        "random_table_id",
        "entity",
        "entity_or_text",
        "text_or_entity",
    }
)
ENTITY_BINDING_TYPES = frozenset({"entity", "entity_or_text", "text_or_entity"})
GROUP_CARDINALITIES = frozenset({"at_least_one", "exactly_one"})
GROUP_BINDING_RULES = frozenset({"slots_only", "source_user_text_fallback"})
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ACTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class _FrozenJSONMap(Mapping[str, Any]):
    """Owned immutable JSON object storage used by resolved contracts."""

    __slots__ = ("__items",)

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_FrozenJSONMap__items", tuple(values.items()))

    def __getitem__(self, key: str) -> Any:
        for item_key, value in self.__items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _value in self.__items)

    def __len__(self) -> int:
        return len(self.__items)

    def _owned_items(self) -> tuple[tuple[str, Any], ...]:
        return self.__items

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("resolved JSON object is immutable")


@dataclass(frozen=True)
class ActionOptionSpec:
    """Resolver option declaration kept as the source-compatible constructor surface."""

    name: str
    help: str
    required: bool = False
    default: Any = None
    dest: str | None = None
    binding_type: str = "text"
    allowed_entity_types: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    ai_fillable: bool = True
    player_confirmation_required: bool = False


@dataclass(frozen=True)
class ActionRequirementGroupSpec:
    name: str
    members: tuple[str, ...]
    required: bool = True
    cardinality: str = "at_least_one"
    binding_rule: str = "slots_only"


@dataclass(frozen=True)
class ActionSlotSpec:
    name: str
    dest: str | None
    description: str
    binding_type: str
    allowed_entity_types: tuple[str, ...]
    aliases: tuple[str, ...]
    required: bool
    default: Any
    ai_fillable: bool
    player_confirmation_required: bool

    def to_projection(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dest": self.dest,
            "description": self.description,
            "binding_type": self.binding_type,
            "allowed_entity_types": list(self.allowed_entity_types),
            "aliases": list(self.aliases),
            "required": self.required,
            "default": _thaw_json(self.default),
            "ai_fillable": self.ai_fillable,
            "player_confirmation_required": self.player_confirmation_required,
        }

    def to_option_spec(self, *, read_only_default: bool = False) -> ActionOptionSpec:
        return ActionOptionSpec(
            name=self.name,
            help=self.description,
            required=self.required,
            default=self.default if read_only_default else _thaw_json(self.default),
            dest=self.dest,
            binding_type=self.binding_type,
            allowed_entity_types=self.allowed_entity_types,
            aliases=self.aliases,
            ai_fillable=self.ai_fillable,
            player_confirmation_required=self.player_confirmation_required,
        )


@dataclass(frozen=True)
class ActionRequirementGroup:
    name: str
    members: tuple[str, ...]
    required: bool
    cardinality: str
    binding_rule: str

    def to_projection(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "members": list(self.members),
            "required": self.required,
            "cardinality": self.cardinality,
            "binding_rule": self.binding_rule,
        }

    def to_spec(self) -> ActionRequirementGroupSpec:
        return ActionRequirementGroupSpec(
            name=self.name,
            members=self.members,
            required=self.required,
            cardinality=self.cardinality,
            binding_rule=self.binding_rule,
        )


@dataclass(frozen=True)
class RequirementEvaluation:
    missing: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedActionSlotContract:
    action: str
    slots: tuple[ActionSlotSpec, ...]
    requirement_groups: tuple[ActionRequirementGroup, ...]

    def slot(self, name: str) -> ActionSlotSpec:
        for slot in self.slots:
            if slot.name == name:
                return slot
        raise KeyError(f"{self.action} slot contract has no slot {name!r}")

    def normalize_name(self, name: str) -> str:
        text = str(name or "").strip()
        for slot in self.slots:
            if text in slot.aliases:
                return slot.name
        return text

    def evaluate_requirements(self, options: Mapping[str, Any]) -> RequirementEvaluation:
        missing = [slot.name for slot in self.slots if slot.required and not _has_value(options.get(slot.name))]
        errors: list[str] = []
        for group in self.requirement_groups:
            present = tuple(member for member in group.members if _has_value(options.get(member)))
            source_fallback = group.binding_rule == "source_user_text_fallback" and _has_value(
                options.get("user_text")
            )
            if group.required and not present and not source_fallback:
                missing.append(" or ".join(group.members))
            if group.cardinality == "exactly_one" and len(present) > 1:
                errors.append(f"{group.name} requires exactly one of: {', '.join(group.members)}")
        return RequirementEvaluation(missing=_dedupe(missing), errors=_dedupe(errors))

    def to_projection(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "slots": [slot.to_projection() for slot in self.slots],
            "requirement_groups": [group.to_projection() for group in self.requirement_groups],
        }


def build_action_slot_contract(
    action: str,
    option_specs: tuple[ActionOptionSpec, ...],
    *,
    legacy_required_options: tuple[str, ...] = (),
    requirement_groups: tuple[ActionRequirementGroupSpec, ...] = (),
) -> ResolvedActionSlotContract:
    action = _exact_action_name(action, label="action")
    if type(option_specs) is not tuple:
        raise TypeError(f"{action}.option_specs must be an exact tuple")
    if type(legacy_required_options) is not tuple:
        raise TypeError(f"{action}.required_options must be an exact tuple")
    if type(requirement_groups) is not tuple:
        raise TypeError(f"{action}.requirement_groups must be an exact tuple")

    declarations: list[ActionOptionSpec] = []
    declared_names: set[str] = set()
    for index, option in enumerate(option_specs):
        if type(option) is not ActionOptionSpec:
            raise TypeError(f"{action}.option_specs[{index}] must be an exact ActionOptionSpec")
        name = _exact_slot_identifier(
            option.name,
            label=f"{action}.option_specs[{index}].name",
        )
        if name in declared_names:
            raise ValueError(f"{action}.option_specs has duplicate slot: {name}")
        declared_names.add(name)
        declarations.append(option)

    legacy_names: list[str] = []
    for index, value in enumerate(legacy_required_options):
        name = _exact_slot_identifier(value, label=f"{action}.required_options[{index}]")
        if name in legacy_names:
            raise ValueError(f"{action}.required_options has duplicate slot: {name}")
        if name in declared_names:
            raise ValueError(
                f"{action}.required_options conflicts with canonical option_specs slot: {name}"
            )
        legacy_names.append(name)
        declarations.append(
            ActionOptionSpec(
                name=name,
                help=f"Legacy required action option: {name}",
                required=True,
            )
        )

    slots = tuple(sorted((_normalize_slot(action, item) for item in declarations), key=lambda item: item.name))
    ai_fillable_count = sum(slot.ai_fillable for slot in slots)
    if ai_fillable_count > MAX_ACTION_CANDIDATE_SLOTS:
        raise ValueError(
            f"{action}.slots has {ai_fillable_count} AI-fillable slots; "
            f"maximum is {MAX_ACTION_CANDIDATE_SLOTS}"
        )
    slot_names = {slot.name for slot in slots}
    alias_owners: dict[str, str] = {}
    for slot in slots:
        for alias in slot.aliases:
            if alias in slot_names:
                raise ValueError(f"{action}.slots.{slot.name}.aliases has alias collision with slot: {alias}")
            owner = alias_owners.get(alias)
            if owner is not None:
                raise ValueError(
                    f"{action}.slots has alias collision: {alias} belongs to both {owner} and {slot.name}"
                )
            alias_owners[alias] = slot.name

    groups = _normalize_groups(
        action,
        requirement_groups,
        slot_names=slot_names,
        aliases=frozenset(alias_owners),
    )
    grouped_members: set[str] = set()
    for group in groups:
        for member in group.members:
            if member in grouped_members:
                raise ValueError(f"{action}.requirement_groups has duplicate member across groups: {member}")
            grouped_members.add(member)
            if _slot_by_name(slots, member).required:
                raise ValueError(
                    f"{action}.requirement_groups.{group.name} conflicts with required slot: {member}"
                )

    return ResolvedActionSlotContract(action=action, slots=slots, requirement_groups=groups)


def build_action_slot_registry_projection(
    entries: Iterable[tuple[str, ResolvedActionSlotContract]],
    *,
    version: str = ACTION_SLOT_CONTRACT_VERSION,
) -> dict[str, Any]:
    version = _exact_text(version, label="slot contract version")
    collected: list[tuple[str, ResolvedActionSlotContract]] = []
    for index, entry in enumerate(tuple(entries)):
        if type(entry) is not tuple or len(entry) != 2:
            raise TypeError(f"slot projection entries[{index}] must be an exact pair")
        raw_name, contract = entry
        action = _exact_action_name(
            raw_name,
            label=f"slot projection entries[{index}].action",
        )
        collected.append((action, contract))
    collected.sort(key=lambda item: item[0])
    actions: list[dict[str, Any]] = []
    names: set[str] = set()
    for name, contract in collected:
        action = name
        if action in names:
            raise ValueError(f"duplicate slot projection action: {action}")
        names.add(action)
        if type(contract) is not ResolvedActionSlotContract:
            raise TypeError(f"{action}.slot_contract must be an exact ResolvedActionSlotContract")
        contract_action = _exact_action_name(
            contract.action,
            label=f"{action}.slot_contract.action",
        )
        if contract_action != action:
            raise ValueError(f"{action}.slot_contract action mismatch: {contract.action}")
        if type(contract.slots) is not tuple:
            raise TypeError(f"{action}.slot_contract.slots must be an exact tuple")
        if type(contract.requirement_groups) is not tuple:
            raise TypeError(f"{action}.slot_contract.requirement_groups must be an exact tuple")
        for index, slot in enumerate(contract.slots):
            if type(slot) is not ActionSlotSpec:
                raise TypeError(
                    f"{action}.slot_contract.slots[{index}] must be an exact ActionSlotSpec"
                )
            if not _is_frozen_json(slot.default):
                raise ValueError(
                    f"{action}.slot_contract.slots.{slot.name}.default must be frozen"
                )
        for index, group in enumerate(contract.requirement_groups):
            if type(group) is not ActionRequirementGroup:
                raise TypeError(
                    f"{action}.slot_contract.requirement_groups[{index}] "
                    "must be an exact ActionRequirementGroup"
                )
        rebuilt = build_action_slot_contract(
            action,
            tuple(slot.to_option_spec() for slot in contract.slots),
            requirement_groups=tuple(group.to_spec() for group in contract.requirement_groups),
        )
        if rebuilt != contract:
            raise ValueError(f"{action}.slot_contract must be normalized")
        actions.append(contract.to_projection())
    payload = {"version": version, "actions": actions}
    return {"version": version, "digest": canonical_json_sha256(payload), "actions": actions}


def _normalize_slot(action: str, option: ActionOptionSpec) -> ActionSlotSpec:
    name = _exact_slot_identifier(option.name, label=f"{action}.slot.name")
    description = _exact_text(option.help, label=f"{action}.slots.{name}.description")
    dest = option.dest
    if dest is not None:
        dest = _exact_text(dest, label=f"{action}.slots.{name}.dest")
    if type(option.binding_type) is not str or option.binding_type not in SLOT_BINDING_TYPES:
        raise ValueError(f"{action}.slots.{name}.binding_type is invalid: {option.binding_type!r}")
    if type(option.allowed_entity_types) is not tuple:
        raise TypeError(f"{action}.slots.{name}.allowed_entity_types must be an exact tuple")
    allowed_entity_types = tuple(
        _exact_identifier(item, label=f"{action}.slots.{name}.allowed_entity_types")
        for item in option.allowed_entity_types
    )
    if len(set(allowed_entity_types)) != len(allowed_entity_types):
        raise ValueError(f"{action}.slots.{name}.allowed_entity_types has duplicates")
    if option.binding_type == "entity" and not allowed_entity_types:
        raise ValueError(f"{action}.slots.{name}.allowed_entity_types is required for entity binding")
    if option.binding_type not in ENTITY_BINDING_TYPES and allowed_entity_types:
        raise ValueError(
            f"{action}.slots.{name}.allowed_entity_types is invalid for {option.binding_type} binding"
        )
    if type(option.aliases) is not tuple:
        raise TypeError(f"{action}.slots.{name}.aliases must be an exact tuple")
    aliases = tuple(
        sorted(
            _exact_slot_identifier(item, label=f"{action}.slots.{name}.aliases")
            for item in option.aliases
        )
    )
    if len(set(aliases)) != len(aliases):
        raise ValueError(f"{action}.slots.{name}.aliases has duplicates")
    if "user_text" in aliases:
        raise ValueError(f"{action}.slots.{name}.aliases cannot use reserved source slot: user_text")
    for field_name, value in (
        ("required", option.required),
        ("ai_fillable", option.ai_fillable),
        ("player_confirmation_required", option.player_confirmation_required),
    ):
        if type(value) is not bool:
            raise TypeError(f"{action}.slots.{name}.{field_name} must be an exact bool")
    if option.player_confirmation_required and option.ai_fillable:
        raise ValueError(
            f"{action}.slots.{name} confirmation conflicts with ai_fillable=true"
        )
    if option.player_confirmation_required and option.default is not None:
        raise ValueError(
            f"{action}.slots.{name} confirmation slot cannot have a default"
        )
    if name == "user_text" and (
        option.binding_type != "text"
        or option.ai_fillable
        or option.player_confirmation_required
    ):
        raise ValueError(
            f"{action}.slots.user_text must be source-only text with ai_fillable=false "
            "and player_confirmation_required=false"
        )
    default = _validated_frozen_json(option.default, label=f"{action}.slots.{name}.default")
    return ActionSlotSpec(
        name=name,
        dest=dest,
        description=description,
        binding_type=option.binding_type,
        allowed_entity_types=allowed_entity_types,
        aliases=aliases,
        required=option.required,
        default=default,
        ai_fillable=option.ai_fillable,
        player_confirmation_required=option.player_confirmation_required,
    )


def _normalize_groups(
    action: str,
    declarations: tuple[ActionRequirementGroupSpec, ...],
    *,
    slot_names: set[str],
    aliases: frozenset[str],
) -> tuple[ActionRequirementGroup, ...]:
    groups: list[ActionRequirementGroup] = []
    group_names: set[str] = set()
    for index, declaration in enumerate(declarations):
        if type(declaration) is not ActionRequirementGroupSpec:
            raise TypeError(
                f"{action}.requirement_groups[{index}] must be an exact ActionRequirementGroupSpec"
            )
        name = _exact_identifier(declaration.name, label=f"{action}.requirement_groups[{index}].name")
        if name in group_names:
            raise ValueError(f"{action}.requirement_groups has duplicate group: {name}")
        if name in slot_names:
            raise ValueError(f"{action}.requirement_groups.{name} has slot collision")
        if name in aliases:
            raise ValueError(f"{action}.requirement_groups.{name} has alias collision")
        group_names.add(name)
        if type(declaration.members) is not tuple:
            raise TypeError(f"{action}.requirement_groups.{name}.members must be an exact tuple")
        members = tuple(
            _exact_slot_identifier(item, label=f"{action}.requirement_groups.{name}.members")
            for item in declaration.members
        )
        if len(members) < 2:
            raise ValueError(f"{action}.requirement_groups.{name} must have at least two members")
        if len(set(members)) != len(members):
            raise ValueError(f"{action}.requirement_groups.{name} has duplicate member")
        if "user_text" in members:
            raise ValueError(
                f"{action}.requirement_groups.{name} cannot use reserved source slot: user_text"
            )
        unknown = tuple(member for member in members if member not in slot_names)
        if unknown:
            raise ValueError(
                f"{action}.requirement_groups.{name} has unknown member: {', '.join(unknown)}"
            )
        if type(declaration.required) is not bool:
            raise TypeError(f"{action}.requirement_groups.{name}.required must be an exact bool")
        if type(declaration.cardinality) is not str or declaration.cardinality not in GROUP_CARDINALITIES:
            raise ValueError(f"{action}.requirement_groups.{name}.cardinality is invalid")
        if type(declaration.binding_rule) is not str or declaration.binding_rule not in GROUP_BINDING_RULES:
            raise ValueError(f"{action}.requirement_groups.{name}.binding_rule is invalid")
        groups.append(
            ActionRequirementGroup(
                name=name,
                members=members,
                required=declaration.required,
                cardinality=declaration.cardinality,
                binding_rule=declaration.binding_rule,
            )
        )
    return tuple(sorted(groups, key=lambda item: item.name))


def _slot_by_name(slots: tuple[ActionSlotSpec, ...], name: str) -> ActionSlotSpec:
    return next(slot for slot in slots if slot.name == name)


def _exact_identifier(value: Any, *, label: str) -> str:
    if type(value) is not str or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase ASCII identifier")
    return value


def _exact_slot_identifier(value: Any, *, label: str) -> str:
    identifier = _exact_identifier(value, label=label)
    if len(identifier) > MAX_ACTION_SLOT_IDENTIFIER_LENGTH:
        raise ValueError(
            f"{label} exceeds {MAX_ACTION_SLOT_IDENTIFIER_LENGTH} characters"
        )
    return identifier


def _exact_action_name(value: Any, *, label: str) -> str:
    if type(value) is not str or not _ACTION_NAME_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase ASCII action identifier")
    return value


def _exact_text(value: Any, *, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError(f"{label} must be a non-empty exact string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8 text") from exc
    return value


def _validated_frozen_json(value: Any, *, label: str) -> Any:
    _validate_json_source(value, label=label)
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_canonical_json_default,
        )
        serialized.encode("utf-8")
        candidate = json.loads(serialized)
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"{label} must be deterministic JSON-safe data") from exc
    try:
        return _freeze_json(candidate, label=label)
    except RecursionError as exc:
        raise ValueError(f"{label} must be deterministic JSON-safe data") from exc


def _freeze_json(value: Any, *, label: str) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{label} must contain finite JSON numbers")
        return value
    if type(value) in {list, tuple}:
        return tuple(_freeze_json(item, label=label) for item in value)
    if type(value) is dict:
        frozen: dict[str, Any] = {}
        for key in sorted(value):
            if type(key) is not str:
                raise ValueError(f"{label} must contain exact string object keys")
            frozen[key] = _freeze_json(value[key], label=label)
        return _FrozenJSONMap(frozen)
    raise ValueError(f"{label} must be deterministic JSON-safe data")


def _thaw_json(value: Any) -> Any:
    root: dict[str, Any] = {}
    stack: list[tuple[Any, Any, Any]] = [(value, root, "value")]
    seen_containers: set[int] = set()
    while stack:
        item, parent, key = stack.pop()
        if isinstance(item, Mapping):
            if id(item) in seen_containers:
                raise ValueError("resolved JSON object contains a repeated or cyclic container")
            seen_containers.add(id(item))
            thawed: dict[str, Any] = {}
            parent[key] = thawed
            entries = (
                item._owned_items()
                if type(item) is _FrozenJSONMap
                else tuple(item.items())
            )
            stack.extend(
                (child, thawed, child_key)
                for child_key, child in reversed(entries)
            )
            continue
        if type(item) is tuple:
            if item and id(item) in seen_containers:
                raise ValueError("resolved JSON array contains a repeated or cyclic container")
            if item:
                seen_containers.add(id(item))
            thawed_list: list[Any] = [None] * len(item)
            parent[key] = thawed_list
            stack.extend(
                (child, thawed_list, index)
                for index, child in reversed(tuple(enumerate(item)))
            )
            continue
        parent[key] = item
    return root["value"]


def _validate_json_source(value: Any, *, label: str) -> None:
    stack = [value]
    seen_containers: set[int] = set()
    while stack:
        item = stack.pop()
        if item is None or type(item) in {str, bool, int, float}:
            continue
        if type(item) in {list, tuple}:
            if id(item) in seen_containers:
                continue
            seen_containers.add(id(item))
            stack.extend(item)
            continue
        if type(item) is dict:
            if id(item) in seen_containers:
                continue
            seen_containers.add(id(item))
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError(f"{label} must contain exact string object keys")
                stack.append(child)
            continue
        if type(item) is _FrozenJSONMap:
            if id(item) in seen_containers:
                continue
            seen_containers.add(id(item))
            for key, child in item._owned_items():
                if type(key) is not str:
                    raise ValueError(f"{label} must contain exact string object keys")
                stack.append(child)
            continue
        raise ValueError(f"{label} must be deterministic JSON-safe data")


def _canonical_json_default(value: Any) -> Any:
    if type(value) is _FrozenJSONMap:
        return dict(value._owned_items())
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _is_frozen_json(value: Any) -> bool:
    stack = [value]
    seen_containers: set[int] = set()
    while stack:
        item = stack.pop()
        if item is None or type(item) in {bool, int}:
            continue
        if type(item) is str:
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return False
            continue
        if type(item) is float:
            if not math.isfinite(item):
                return False
            continue
        if type(item) is tuple:
            if not item:
                continue
            if id(item) in seen_containers:
                return False
            seen_containers.add(id(item))
            stack.extend(item)
            continue
        if type(item) is _FrozenJSONMap:
            if id(item) in seen_containers:
                return False
            seen_containers.add(id(item))
            try:
                items = item._owned_items()
            except AttributeError:
                return False
            if type(items) is not tuple or any(
                type(entry) is not tuple or len(entry) != 2
                for entry in items
            ):
                return False
            keys = tuple(entry[0] for entry in items)
            if (
                not all(type(key) is str for key in keys)
                or len(set(keys)) != len(keys)
                or keys != tuple(sorted(keys))
            ):
                return False
            try:
                for key in keys:
                    key.encode("utf-8")
            except UnicodeEncodeError:
                return False
            stack.extend(entry[1] for entry in items)
            continue
        return False
    return True


def _has_value(value: Any) -> bool:
    return bool(value)


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
