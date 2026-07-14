from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any

from ..actions.slot_contract import (
    ACTION_SLOT_CONTRACT_VERSION,
    SLOT_BINDING_TYPES,
    ActionRequirementGroup,
    ActionRequirementGroupSpec,
    ActionSlotSpec,
    ResolvedActionSlotContract,
)


TEXT_SLOT_TYPES = frozenset({"text", "text_list", "dice_expr", "random_table_id"})
ENTITY_SLOT_TYPES = frozenset({"location", "entity_or_text", "text_or_entity"})


class _DerivedSlotMapping(Mapping[str, Any]):
    """Read-only compatibility view derived from the default resolver registry."""

    def __init__(self, projection: str) -> None:
        self._projection = projection

    def _data(self) -> Mapping[str, Any]:
        from ..actions import get_default_action_registry

        values: dict[str, Any] = {}
        for spec in get_default_action_registry().all():
            contract = spec.slot_contract
            if self._projection == "bindings":
                item = {
                    slot.name: _legacy_binding_value(slot)
                    for slot in contract.slots
                    if slot.name != "user_text"
                }
                values[spec.name] = MappingProxyType(item)
            elif self._projection == "aliases":
                item = {
                    alias: slot.name
                    for slot in contract.slots
                    for alias in slot.aliases
                }
                values[spec.name] = MappingProxyType(item)
            elif self._projection == "required":
                required = [slot.name for slot in contract.slots if slot.required]
                required.extend(
                    _legacy_group_requirement(group)
                    for group in contract.requirement_groups
                    if group.required
                )
                if required:
                    values[spec.name] = tuple(required)
            elif self._projection == "confirmation":
                confirmation = frozenset(
                    slot.name for slot in contract.slots if slot.player_confirmation_required
                )
                if confirmation:
                    values[spec.name] = confirmation
            else:  # pragma: no cover - constructor is module-owned
                raise AssertionError(f"unknown compatibility projection: {self._projection}")
        return MappingProxyType(values)

    def __getitem__(self, key: str) -> Any:
        return self._data()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())


def _legacy_binding_value(slot: ActionSlotSpec) -> Any:
    if slot.binding_type == "entity":
        if len(slot.allowed_entity_types) == 1:
            return slot.allowed_entity_types[0]
        return slot.allowed_entity_types
    return slot.binding_type


def _legacy_group_requirement(group: ActionRequirementGroup) -> str:
    if group.binding_rule == "source_user_text_fallback":
        return group.members[0]
    return " or ".join(group.members)


ACTION_SLOT_BINDINGS: Mapping[str, Mapping[str, Any]] = _DerivedSlotMapping("bindings")
SLOT_ALIASES: Mapping[str, Mapping[str, str]] = _DerivedSlotMapping("aliases")
ACTION_REQUIRED_SLOTS: Mapping[str, tuple[str, ...]] = _DerivedSlotMapping("required")
AI_SUPPLIED_CONFIRMATION_SLOTS: Mapping[str, frozenset[str]] = _DerivedSlotMapping("confirmation")


__all__ = [
    "ACTION_REQUIRED_SLOTS",
    "ACTION_SLOT_BINDINGS",
    "ACTION_SLOT_CONTRACT_VERSION",
    "AI_SUPPLIED_CONFIRMATION_SLOTS",
    "ENTITY_SLOT_TYPES",
    "SLOT_ALIASES",
    "SLOT_BINDING_TYPES",
    "TEXT_SLOT_TYPES",
    "ActionRequirementGroup",
    "ActionRequirementGroupSpec",
    "ActionSlotSpec",
    "ResolvedActionSlotContract",
]
