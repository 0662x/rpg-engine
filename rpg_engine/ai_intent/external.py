from __future__ import annotations

from typing import Any

from ..actions import get_default_action_registry
from ..ai.schema_validation import validate_ai_output_schema
from .normalization import normalize_intent_candidate
from .safety_contract import (
    ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE,
    ActiveIntentContract,
    ExternalIntentContractError,
    SAFETY_FLAG_VALUES,
    ValidatedExternalCandidate,
)
from .types import IntentCandidate


def normalize_external_intent_candidate(value: dict[str, Any], *, user_text: str = "") -> IntentCandidate:
    return validate_external_intent_candidate(value, user_text=user_text).candidate


def validate_external_intent_candidate(
    value: dict[str, Any],
    *,
    user_text: str = "",
    _active_contract: ActiveIntentContract | None = None,
) -> ValidatedExternalCandidate:
    if type(value) is not dict:
        raise ValueError("external_intent_candidate must be an object")
    contract = _validate_external_contract_shape(value)
    active_contract = _active_contract or _build_active_intent_contract()
    if contract is None:
        if not ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE:
            raise ExternalIntentContractError.contract_version_mismatch()
        evidence = active_contract.evidence("legacy_unversioned")
    else:
        if contract != {
            "manifest_schema_version": active_contract.manifest_schema_version,
            "manifest_digest": active_contract.manifest_digest,
            "safety_vocabulary_version": active_contract.safety_vocabulary_version,
            "safety_vocabulary_digest": active_contract.safety_vocabulary_digest,
        }:
            raise ExternalIntentContractError.contract_version_mismatch()
        evidence = active_contract.evidence("matched")

    if "safety_flags" in value:
        _validate_external_safety_flags(value["safety_flags"])
    schema_errors = validate_ai_output_schema("intent_candidate.schema.json", value)
    if schema_errors:
        raise ValueError(f"external_intent_candidate schema validation failed: {schema_errors[0]}")
    action_names = set(get_default_action_registry().names())
    for index, step in enumerate(value.get("plan", [])):
        action = str(step.get("action") or "").strip().lower()
        if action not in action_names:
            raise ValueError(
                "external_intent_candidate schema validation failed: "
                f"$.plan[{index}].action: action is not registered"
            )
    candidate_payload = {key: item for key, item in value.items() if key != "contract"}
    candidate = normalize_intent_candidate(
        {**candidate_payload, "source": "external_ai", "source_user_text": user_text},
        source="external_ai",
        user_text=user_text,
    )
    return ValidatedExternalCandidate(candidate=candidate, contract_evidence=evidence)


def _build_active_intent_contract() -> ActiveIntentContract:
    from ..intent_manifest import build_intent_manifest

    manifest = build_intent_manifest()
    safety = manifest["safety_vocabulary"]
    return ActiveIntentContract(
        manifest_schema_version=manifest["schema_version"],
        manifest_digest=manifest["manifest_digest"],
        safety_vocabulary_version=safety["version"],
        safety_vocabulary_digest=safety["digest"],
    )


def _validate_external_contract_shape(value: dict[str, Any]) -> dict[str, str] | None:
    if "contract" not in value:
        return None
    contract = value["contract"]
    if type(contract) is not dict:
        raise ValueError("external_intent_candidate schema validation failed: $.contract: expected object")
    fields = {
        "manifest_schema_version",
        "manifest_digest",
        "safety_vocabulary_version",
        "safety_vocabulary_digest",
    }
    if set(contract) != fields:
        raise ValueError("external_intent_candidate schema validation failed: $.contract: invalid contract shape")
    for key in ("manifest_schema_version", "safety_vocabulary_version"):
        item = contract[key]
        if type(item) is not str or not 1 <= len(item) <= 32:
            raise ValueError(
                "external_intent_candidate schema validation failed: "
                f"$.contract.{key}: expected bounded string"
            )
    for key in ("manifest_digest", "safety_vocabulary_digest"):
        item = contract[key]
        if type(item) is not str or len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
            raise ValueError(
                "external_intent_candidate schema validation failed: "
                f"$.contract.{key}: expected lowercase sha256"
            )
    return contract


def _validate_external_safety_flags(value: Any) -> None:
    if type(value) is not list:
        raise ValueError(
            "external_intent_candidate schema validation failed: "
            "$.safety_flags: expected exact array"
        )
    if len(value) > len(SAFETY_FLAG_VALUES):
        raise ValueError(
            "external_intent_candidate schema validation failed: "
            "$.safety_flags: too many values"
        )
    if any(type(item) is not str for item in value):
        raise ValueError(
            "external_intent_candidate schema validation failed: "
            "$.safety_flags: expected exact string tokens"
        )
    unknown_count = sum(type(item) is str and item not in SAFETY_FLAG_VALUES for item in value)
    if unknown_count:
        raise ExternalIntentContractError.unknown_safety_flag(count=min(unknown_count, 6))
    if len(value) != len(set(value)):
        raise ValueError(
            "external_intent_candidate schema validation failed: "
            "$.safety_flags: values must be unique"
        )
