from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    file: str
    path: str
    message: str
    suggestion: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "file": self.file,
            "path": self.path,
            "message": self.message,
            "suggestion": self.suggestion,
        }


def issues_from_messages(messages: list[str] | tuple[str, ...], *, default_code: str = "VALIDATION_ERROR") -> list[dict[str, str]]:
    return [issue_from_message(message, default_code=default_code).to_dict() for message in messages]


def issue_from_message(message: str, *, default_code: str = "VALIDATION_ERROR") -> ValidationIssue:
    file, path = split_file_path(message)
    return ValidationIssue(
        code=code_for_message(message, default_code),
        file=file,
        path=path,
        message=message,
        suggestion=suggestion_for_message(message),
    )


def split_file_path(message: str) -> tuple[str, str]:
    head, sep, tail = message.partition(":")
    if not sep:
        return "", ""
    if "/" in head or head.endswith((".yaml", ".yml", ".json", ".jsonl", ".md", ".py")):
        return head, tail.strip().split(":", 1)[0]
    if head.startswith("$") or "." in head:
        return "", head
    return "", ""


def code_for_message(message: str, default_code: str) -> str:
    lowered = message.lower()
    if "unsupported capability" in lowered:
        return "UNSUPPORTED_CAPABILITY"
    if "events.jsonl" in lowered:
        return "EVENT_LOG_INCONSISTENT"
    if "projection_state" in lowered or "fts_index" in lowered:
        return "PROJECTION_INCONSISTENT"
    if "schema" in lowered or "migration" in lowered or "checksum" in lowered:
        return "SCHEMA_INCONSISTENT"
    if "missing" in lowered or "required" in lowered:
        return "MISSING_REQUIRED_VALUE"
    if "reference" in lowered or "points to missing" in lowered:
        return "MISSING_REFERENCE"
    if "visibility" in lowered:
        return "INVALID_VISIBILITY"
    if "random table" in lowered or "dice" in lowered:
        return "INVALID_RANDOM"
    if "clock" in lowered:
        return "INVALID_CLOCK"
    if "stale write" in lowered or "expected current turn" in lowered:
        return "STALE_WRITE"
    if "duplicate" in lowered:
        return "DUPLICATE_ID"
    return default_code


def suggestion_for_message(message: str) -> str:
    lowered = message.lower()
    if "unsupported capability" in lowered:
        return "Declare the capability in campaign.yaml and cover it with a smoke test, or choose a supported action."
    if "events.jsonl" in lowered:
        return "Rebuild the event log from SQLite through a controlled repair path before sharing the save."
    if "projection_state" in lowered or "fts_index" in lowered:
        return "Run the explicit projection repair/admin path, then validate again."
    if "schema" in lowered or "migration" in lowered or "checksum" in lowered:
        return "Run migration status/apply on a backup, then validate again."
    if "missing" in lowered or "required" in lowered:
        return "Add the missing field or file, then rerun validation."
    if "reference" in lowered or "points to missing" in lowered:
        return "Create the referenced object or fix the reference ID."
    if "visibility" in lowered:
        return "Use one of the visibility values allowed by the V1 spec."
    if "random table" in lowered or "dice" in lowered:
        return "Fix the random table/dice input and rerun the kernel roll."
    if "clock" in lowered:
        return "Check the clock id, segment total and tick amount."
    if "stale write" in lowered or "expected current turn" in lowered:
        return "Refresh the turn context and retry with the current expected_turn_id."
    return "Fix the reported issue and rerun validation."
