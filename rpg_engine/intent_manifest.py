from __future__ import annotations

from typing import Any

from .actions import ActionResolverRegistry, get_default_action_registry
from .actions.base import ActionResolverSpec
from .actions.slot_contract import ActionRequirementGroup, ActionSlotSpec
from .ai_intent.risk import ACTION_BASE_RISK
from .ai_intent.safety_contract import (
    ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE,
    SAFETY_FLAG_VALUES,
    SAFETY_VOCABULARY_DIGEST,
    SAFETY_VOCABULARY_VERSION,
    canonical_json_sha256,
)
from .capabilities import ACTION_CAPABILITIES


MANIFEST_SCHEMA_VERSION = "4"
QUERY_KINDS = ("scene", "entity", "context")
CONTRACT_FIELDS = (
    "manifest_schema_version",
    "manifest_digest",
    "safety_vocabulary_version",
    "safety_vocabulary_digest",
)


def build_intent_manifest(registry: ActionResolverRegistry | None = None) -> dict[str, Any]:
    """Build the kernel-owned machine-readable action/query contract."""
    action_registry = registry if registry is not None else get_default_action_registry()
    action_taxonomy = action_registry.taxonomy_projection()
    taxonomy_actions = {
        str(action["name"]): action
        for action in action_taxonomy["actions"]
    }
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_by": "kernel",
        "modes": ("query", "action", "unknown"),
        "action_taxonomy": action_taxonomy,
        "safety_vocabulary": {
            "version": SAFETY_VOCABULARY_VERSION,
            "digest": SAFETY_VOCABULARY_DIGEST,
            "values": tuple(sorted(SAFETY_FLAG_VALUES)),
        },
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
            "safety_flags": tuple(sorted(SAFETY_FLAG_VALUES)),
            "contract": {
                "required": False,
                "all_or_nothing": True,
                "additional_properties": False,
                "legacy_unversioned_allowed": ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE,
                "required_fields_when_present": CONTRACT_FIELDS,
            },
        },
        "actions": [action_manifest(spec, taxonomy_actions[spec.name]) for spec in action_registry.all()],
        "queries": [query_manifest(kind) for kind in QUERY_KINDS],
        "unsupported_query_kind_policy": {
            "rule": "context",
            "default": "entity",
        },
    }
    return {
        "schema_version": payload["schema_version"],
        "manifest_digest": canonical_json_sha256(payload),
        **{key: value for key, value in payload.items() if key != "schema_version"},
    }


def action_manifest(spec: ActionResolverSpec, taxonomy_action: dict[str, Any]) -> dict[str, Any]:
    requirement_groups = [requirement_group_manifest(group) for group in spec.slot_contract.requirement_groups]
    return {
        "name": spec.name,
        "mode": "action",
        "capability": ACTION_CAPABILITIES.get(spec.name),
        "risk": ACTION_BASE_RISK.get(spec.name, "yellow_consensus"),
        "response_template": spec.response_template,
        "keywords": tuple(
            term["value"]
            for term in taxonomy_action["terms"]
            if "simple" in term["roles"]
        ),
        "semantic_labels": tuple(taxonomy_action["semantic_labels"]),
        "inference_priority": taxonomy_action["inference_priority"],
        "slots": [
            slot_manifest(slot)
            for slot in spec.slot_contract.slots
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
    slot: ActionSlotSpec,
) -> dict[str, Any]:
    return {
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


def requirement_group_manifest(group: ActionRequirementGroup) -> dict[str, Any]:
    """Project every executable group constraint into the public manifest."""
    return {
        "name": group.name,
        "any_of": group.members,
        "required": group.required,
        "cardinality": group.cardinality,
        "binding_rule": group.binding_rule,
    }


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
