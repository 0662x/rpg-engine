from __future__ import annotations

import json
from typing import Any

from ..resource_paths import schema_resource_text


def validate_ai_output_schema(schema_name: str, value: dict[str, Any]) -> list[str]:
    if not schema_name.endswith(".json"):
        return [f"{schema_name}: schema name must end with .json"]
    try:
        schema = json.loads(schema_resource_text(schema_name))
    except Exception as exc:
        return [f"{schema_name}: schema unavailable: {exc}"]
    jsonschema_errors = validate_with_jsonschema(schema, value)
    return jsonschema_errors


def validate_with_jsonschema(schema: dict[str, Any], value: Any) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except Exception as exc:
        return [f"$: jsonschema dependency unavailable: {exc}"]
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    return [format_jsonschema_error(error) for error in errors[:8]]


def format_jsonschema_error(error: Any) -> str:
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        properties = error.schema.get("properties") if isinstance(error.schema, dict) else None
        if isinstance(properties, dict):
            extras = sorted(set(error.instance) - set(properties))
            if extras:
                base = "$" + "".join(
                    f"[{item}]" if isinstance(item, int) else f".{item}" for item in error.absolute_path
                )
                return f"{base}.{extras[0]}: unknown field" if base != "$" else f"$.{extras[0]}: unknown field"
    path = "$" + "".join(f"[{item}]" if isinstance(item, int) else f".{item}" for item in error.absolute_path)
    return f"{path}: {error.message}"


def validate_schema_value(schema: dict[str, Any], value: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        branch_errors = [
            validate_schema_value(child, value, path=path)
            for child in schema["oneOf"]
            if isinstance(child, dict)
        ]
        matched = [items for items in branch_errors if not items]
        if len(matched) != 1:
            errors.append(f"{path}: expected exactly one matching schema")
        return errors
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        branch_errors = [
            validate_schema_value(child, value, path=path)
            for child in schema["anyOf"]
            if isinstance(child, dict)
        ]
        if not any(not items for items in branch_errors):
            errors.append(f"{path}: expected one matching schema")
        return errors
    if "allOf" in schema and isinstance(schema["allOf"], list):
        for child in schema["allOf"]:
            if isinstance(child, dict):
                errors.extend(validate_schema_value(child, value, path=path))

    schema_type = schema.get("type")
    if schema_type and not matches_schema_type(value, schema_type):
        return [f"{path}: expected {schema_type}"]

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: expected one of {', '.join(str(item) for item in enum)}")

    if schema_type == "object" and isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}.{key}: required")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            if schema.get("additionalProperties") is False:
                for key in sorted(set(value) - set(properties)):
                    errors.append(f"{path}.{key}: unknown field")
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, dict):
                    errors.extend(validate_schema_value(child_schema, value[key], path=f"{path}.{key}"))

    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_schema_value(item_schema, item, path=f"{path}[{index}]"))

    return errors


def matches_schema_type(value: Any, schema_type: Any) -> bool:
    if isinstance(schema_type, list):
        return any(matches_type(value, str(item)) for item in schema_type)
    return matches_type(value, str(schema_type))


def matches_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return True
