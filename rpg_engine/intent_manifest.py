from __future__ import annotations

from typing import Any

from .actions import ActionResolverRegistry, get_default_action_registry
from .actions.base import ActionOptionSpec, ActionResolverSpec
from .ai_intent.slot_contract import (
    ACTION_REQUIRED_SLOTS,
    ACTION_SLOT_BINDINGS,
    AI_SUPPLIED_CONFIRMATION_SLOTS,
    SLOT_ALIASES,
)
from .ai_intent.risk import ACTION_BASE_RISK, BLOCKING_SAFETY_FLAGS
from .capabilities import ACTION_CAPABILITIES


MANIFEST_SCHEMA_VERSION = "1"
QUERY_KINDS = ("scene", "entity", "context")


def build_intent_manifest(registry: ActionResolverRegistry | None = None) -> dict[str, Any]:
    """Build the kernel-owned machine-readable action/query contract."""
    action_registry = registry or get_default_action_registry()
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_by": "kernel",
        "modes": ("query", "action", "unknown"),
        "candidate_shape": {
            "required_fields": (
                "kind",
                "mode",
                "action",
                "slots",
                "plan",
                "confidence",
                "missing_slots",
                "needs_confirmation",
                "safety_flags",
                "reason",
            ),
            "action_names": tuple(action_registry.names()),
            "query_kinds": QUERY_KINDS,
            "safety_flags": tuple(sorted(BLOCKING_SAFETY_FLAGS)),
        },
        "actions": [action_manifest(spec) for spec in action_registry.all()],
        "queries": [query_manifest(kind) for kind in QUERY_KINDS],
        "unsupported_query_kind_policy": {
            "rule": "context",
            "default": "entity",
        },
    }


def action_manifest(spec: ActionResolverSpec) -> dict[str, Any]:
    required_slots = tuple(ACTION_REQUIRED_SLOTS.get(spec.name, ()))
    requirement_groups = action_requirement_groups(spec.name)
    group_slots = {slot for group in requirement_groups for slot in group["any_of"]}
    confirmation_slots = AI_SUPPLIED_CONFIRMATION_SLOTS.get(spec.name, set())
    return {
        "name": spec.name,
        "mode": "action",
        "capability": ACTION_CAPABILITIES.get(spec.name),
        "risk": ACTION_BASE_RISK.get(spec.name, "yellow_consensus"),
        "response_template": spec.response_template,
        "keywords": tuple(spec.keywords),
        "semantic_labels": tuple(spec.semantic_labels),
        "inference_priority": spec.inference_priority,
        "slots": [
            slot_manifest(
                spec.name,
                option,
                required=option.name in required_slots and option.name not in group_slots,
                player_confirmation_required=option.name in confirmation_slots,
            )
            for option in spec.option_specs
        ],
        "requirement_groups": requirement_groups,
        "resolver_contract": {
            "has_preview": spec.preview is not None,
            "has_request_contract": True,
            "has_validate_request_hook": spec.validate_request is not None,
            "has_resolve_contract": True,
            "has_resolve_hook": spec.resolve is not None,
            "has_delta_contract": True,
            "has_validate_delta_hook": spec.validate_delta is not None,
            "request_model": spec.request_model.__name__,
            "proposal_model": spec.proposal_model.__name__,
        },
    }


def slot_manifest(
    action: str,
    option: ActionOptionSpec,
    *,
    required: bool,
    player_confirmation_required: bool,
) -> dict[str, Any]:
    slot_type = ACTION_SLOT_BINDINGS.get(action, {}).get(option.name, "text")
    return {
        "name": option.name,
        "dest": option.dest,
        "description": option.help,
        "type": manifest_slot_type(slot_type),
        "allowed_entity_types": manifest_allowed_entity_types(slot_type),
        "aliases": tuple(slot_aliases(action, option.name)),
        "required": required,
        "default": option.default,
        "ai_fillable": option.name != "user_text" and not player_confirmation_required,
        "player_confirmation_required": player_confirmation_required,
    }


def action_requirement_groups(action: str) -> list[dict[str, Any]]:
    if action == "random_table":
        return [{"name": "random_source", "any_of": ("table", "dice"), "required": True}]
    if action == "routine":
        return [{"name": "routine_scope", "any_of": ("task", "target"), "required": True}]
    return []


def slot_aliases(action: str, slot: str) -> list[str]:
    aliases = SLOT_ALIASES.get(action, {})
    return sorted(alias for alias, canonical in aliases.items() if canonical == slot)


def manifest_slot_type(slot_type: Any) -> str:
    if isinstance(slot_type, tuple):
        return "entity"
    if slot_type in {"entity_or_text", "text_or_entity"}:
        return str(slot_type)
    if isinstance(slot_type, str) and slot_type not in {"text", "text_list", "dice_expr", "random_table_id"}:
        return "entity"
    return str(slot_type)


def manifest_allowed_entity_types(slot_type: Any) -> tuple[str, ...]:
    if isinstance(slot_type, tuple):
        return tuple(str(item) for item in slot_type)
    if isinstance(slot_type, str) and slot_type not in {"text", "text_list", "dice_expr", "random_table_id", "entity_or_text", "text_or_entity"}:
        return (slot_type,)
    return ()


def query_manifest(kind: str) -> dict[str, Any]:
    requires_query_text = kind in {"entity", "context"}
    return {
        "kind": kind,
        "mode": "query",
        "read_only": True,
        "advances_time": False,
        "requires_query_text": requires_query_text,
        "slots": (
            {
                "name": "query_kind",
                "type": "enum",
                "allowed_values": QUERY_KINDS,
                "required": True,
                "ai_fillable": True,
                "player_confirmation_required": False,
            },
            {
                "name": "query_text",
                "type": "text",
                "allowed_values": (),
                "required": requires_query_text,
                "ai_fillable": True,
                "player_confirmation_required": False,
            },
        ),
        "result_owner": "kernel",
    }
