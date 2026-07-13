from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


SAFETY_FLAG_VALUES = frozenset(
    {
        "prompt_injection",
        "out_of_world",
        "forced_save",
        "hidden_info",
        "maintenance_request",
        "unsafe_command",
    }
)
SAFETY_VOCABULARY_VERSION = "1"
ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE = True


def canonical_json_sha256(value: Any) -> str:
    wire = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


SAFETY_VOCABULARY_DIGEST = canonical_json_sha256(
    {
        "version": SAFETY_VOCABULARY_VERSION,
        "values": sorted(SAFETY_FLAG_VALUES),
    }
)


@dataclass(frozen=True)
class ActiveIntentContract:
    manifest_schema_version: str
    manifest_digest: str
    safety_vocabulary_version: str
    safety_vocabulary_digest: str

    def __post_init__(self) -> None:
        _validate_contract_identity_fields(self)

    def evidence(self, status: str) -> ExternalContractEvidence:
        return ExternalContractEvidence(
            status=status,
            validated_manifest_schema_version=self.manifest_schema_version,
            validated_manifest_digest=self.manifest_digest,
            validated_safety_vocabulary_version=self.safety_vocabulary_version,
            validated_safety_vocabulary_digest=self.safety_vocabulary_digest,
        )


@dataclass(frozen=True)
class ExternalContractEvidence:
    status: str
    validated_manifest_schema_version: str
    validated_manifest_digest: str
    validated_safety_vocabulary_version: str
    validated_safety_vocabulary_digest: str

    def __post_init__(self) -> None:
        if self.status not in {"matched", "legacy_unversioned"}:
            raise ValueError("invalid external contract evidence status")
        _validate_contract_identity_fields(self)

    def to_trace_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "validated_manifest_schema_version": self.validated_manifest_schema_version,
            "validated_manifest_digest": self.validated_manifest_digest,
            "validated_safety_vocabulary_version": self.validated_safety_vocabulary_version,
            "validated_safety_vocabulary_digest": self.validated_safety_vocabulary_digest,
        }


@dataclass(frozen=True)
class ValidatedExternalCandidate:
    candidate: Any
    contract_evidence: ExternalContractEvidence


def _validate_contract_identity_fields(value: ActiveIntentContract | ExternalContractEvidence) -> None:
    prefix = "validated_" if isinstance(value, ExternalContractEvidence) else ""
    for key in ("manifest_schema_version", "safety_vocabulary_version"):
        item = getattr(value, f"{prefix}{key}")
        if type(item) is not str or not 1 <= len(item) <= 32:
            raise ValueError("contract identity version must be an exact bounded string")
    for key in ("manifest_digest", "safety_vocabulary_digest"):
        item = getattr(value, f"{prefix}{key}")
        if type(item) is not str or len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
            raise ValueError("contract identity digest must be lowercase sha256")


class ExternalIntentContractError(ValueError):
    """Safe machine-readable failure at the external intent boundary."""

    def __init__(
        self,
        *,
        code: str,
        reason: str,
        retriable: bool,
        action: str,
        path: str,
        message: str,
        count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.retriable = retriable
        self.action = action
        self.path = path
        self.message = message
        self.count = count if type(count) is int and 0 <= count <= 6 else None

    @classmethod
    def unknown_safety_flag(cls, *, count: int | None = None) -> ExternalIntentContractError:
        return cls(
            code="UNKNOWN_INTENT_SAFETY_FLAG",
            reason="unknown_safety_flag",
            retriable=False,
            action="regenerate_candidate",
            path="$.safety_flags",
            message="External intent candidate contains unsupported safety flags.",
            count=count,
        )

    @classmethod
    def contract_version_mismatch(cls) -> ExternalIntentContractError:
        return cls(
            code="INTENT_CONTRACT_VERSION_MISMATCH",
            reason="contract_version_mismatch",
            retriable=True,
            action="refresh_manifest_and_regenerate_candidate",
            path="$.contract",
            message="External intent contract does not match the current provider.",
        )


def external_intent_contract_error_detail(error: ExternalIntentContractError) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": error.code,
        "reason": error.reason,
        "retriable": error.retriable,
        "action": error.action,
        "path": error.path,
        "message": error.message,
    }
    if type(error.count) is int and 0 <= error.count <= 6:
        detail["count"] = error.count
    return detail


def external_intent_contract_error_dict(error: ExternalIntentContractError) -> dict[str, Any]:
    return {
        "ok": False,
        "errors": [error.message],
        "error_details": [external_intent_contract_error_detail(error)],
    }
