from __future__ import annotations

from typing import Any

from ..ai.schema_validation import validate_ai_output_schema
from .normalization import normalize_intent_candidate
from .types import IntentCandidate


def normalize_external_intent_candidate(value: dict[str, Any], *, user_text: str = "") -> IntentCandidate:
    if not isinstance(value, dict):
        raise ValueError("external_intent_candidate must be an object")
    schema_errors = validate_ai_output_schema("intent_candidate.schema.json", value)
    if schema_errors:
        raise ValueError(f"external_intent_candidate schema validation failed: {schema_errors[0]}")
    return normalize_intent_candidate({**value, "source": "external_ai", "source_user_text": user_text}, source="external_ai", user_text=user_text)
