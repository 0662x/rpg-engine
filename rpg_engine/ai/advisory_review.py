from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import weakref
from dataclasses import dataclass
from typing import Any

from ..content_types import get_default_registry
from ..content_validation import TURN_ID_PATTERN, validate_content_delta
from ..entity_access import read_entity
from ..memory import resolvable_memory_event_ids
from ..progress_access import (
    is_safe_visible_text,
    is_valid_clock_id,
    read_progress,
    validate_delta_progress_references,
)
from ..relationship_access import read_relationship
from ..visibility import (
    ENTITY_VISIBILITY_LABELS,
    is_player_hidden_visibility,
    normalize_visibility_view,
)
from .advisory import (
    _FORBIDDEN_AUTHORITY_KEYS,
    ResidentAIAdvisory,
    normalize_resident_ai_advisory,
    resident_ai_advisory_to_player_dict,
)


ADVISORY_REVIEW_SCHEMA_VERSION = "resident_ai_advisory_review:v1"
MAX_DEPTH = 8
MAX_ITEMS = 256
MAX_STRING = 1024
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_PROGRESS_VALUE = 1_000_000
GENERIC_ERROR = "$: invalid advisory review input"
GENERIC_UNAVAILABLE = {"available": False, "reason": "advisory review unavailable"}
AUTHORITATIVE_FACT_TABLES = (
    "aliases",
    "characters",
    "clocks",
    "crop_plots",
    "entities",
    "events",
    "facts",
    "items",
    "locations",
    "memory_summaries",
    "meta",
    "routes",
    "rules",
    "turns",
    "world_settings",
)

SUGGESTION_FAMILIES = frozenset(
    {"entity", "relationship", "alias", "memory_summary", "progress_definition", "clock_tick"}
)
SUGGESTION_OPERATIONS = frozenset({"create", "update", "review", "tick"})
DISPOSITIONS = frozenset({"reviewable", "rejected", "stale", "superseded", "conflict"})
FAMILY_OPERATIONS = {
    "entity": frozenset({"create", "update"}),
    "relationship": frozenset({"create", "update"}),
    "alias": frozenset({"review"}),
    "memory_summary": frozenset({"review"}),
    "progress_definition": frozenset({"create", "review"}),
    "clock_tick": frozenset({"tick"}),
}
FAMILY_SOURCE_BINDINGS = {
    "entity": ("entity_maintenance", "entity_maintenance"),
    "relationship": ("entity_maintenance", "entity_maintenance"),
    "alias": ("entity_maintenance", "entity_maintenance"),
    "memory_summary": ("entity_maintenance", "entity_maintenance"),
    "progress_definition": ("progress_management", "progress_management"),
    "clock_tick": ("progress_management", "progress_management"),
}
GATE_OWNER = {
    "entity": ("validate_content_delta", "content_maintenance"),
    "relationship": ("validate_content_delta", "content_maintenance"),
    "alias": ("manual_review_only", "none"),
    "memory_summary": ("manual_review_only", "none"),
    "progress_definition": ("manual_review_only", "none"),
    "clock_tick": ("validate_delta_progress_references", "confirmed_turn_or_maintenance_validation"),
}
NO_APPLICATION_OWNER = frozenset({"alias", "memory_summary", "progress_definition"})
FORBIDDEN_CONTROL_KEYS = frozenset(
    {
        "advisoryonly",
        "approval",
        "applicationauthorized",
        "applicationeligible",
        "approve",
        "approved",
        "approveproposal",
        "assistantresponse",
        "audit",
        "authorization",
        "authorize",
        "bypassvalidation",
        "canapproveproposals",
        "canauthorizesave",
        "canbypassvalidation",
        "cancommit",
        "canconfirmplayers",
        "canescalateprofile",
        "caninjecttrusteddelta",
        "canreadhidden",
        "canwritefacts",
        "commit",
        "commitcapability",
        "confirm",
        "confirmation",
        "confirmed",
        "confirmplayer",
        "currentfact",
        "currentfactauthority",
        "developerprompt",
        "errormessage",
        "factauthority",
        "grantaccess",
        "hiddenpermission",
        "hiddentoken",
        "modelresponse",
        "nodirectwrites",
        "preflight",
        "privatereasoning",
        "prompt",
        "proposalapprovaliscommit",
        "proposalid",
        "proposalpayload",
        "proposalstate",
        "providerbody",
        "provideroutput",
        "providerresponse",
        "rawhelperoutput",
        "rawoutput",
        "rawprompt",
        "rawresponse",
        "reasoning",
        "saveauthorization",
        "saveauthorized",
        "session",
        "sessionid",
        "sessionkey",
        "systemprompt",
        "trusteddelta",
        "validationbypass",
        "validationprofile",
    }
) | _FORBIDDEN_AUTHORITY_KEYS
SAFE_VALIDATION_CODES = frozenset(
    {
        "content_validation_failed",
        "content_validation_warning",
        "details_shape_conflict",
        "alias_boundary_unavailable",
        "endpoint_unavailable",
        "endpoint_stale",
        "memory_source_unavailable",
        "memory_source_stale",
        "progress_reference_validation_failed",
        "reference_unavailable",
        "replacement_shape_conflict",
        "source_not_current",
        "source_unavailable",
        "source_stale",
        "target_already_exists",
        "target_unavailable",
        "target_stale",
        "value_exceeds_limit",
        "value_invalid",
        "visibility_unavailable",
    }
)
ROLLBACK_STRATEGIES = frozenset({"discard_draft", "supersede", "revalidate"})
SAFE_REFERENCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[_.:-][a-z0-9]+)*$")
SAFE_ROLLBACK_REFERENCE_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]*(?::[A-Za-z0-9_.-]+)+$"
)
ENTITY_CANDIDATE_KEYS = frozenset(
    {
        "aliases",
        "character",
        "crop_plot",
        "details",
        "id",
        "item",
        "location",
        "location_id",
        "name",
        "owner_id",
        "status",
        "summary",
        "type",
        "visibility",
    }
)
RELATIONSHIP_CANDIDATE_KEYS = frozenset(
    {"aliases", "details", "id", "name", "status", "summary", "type", "visibility"}
)
ENTITY_UPDATE_BASE_KEYS = frozenset(
    {"details", "id", "location_id", "name", "owner_id", "status", "summary", "type", "visibility"}
)
RELATIONSHIP_UPDATE_BASE_KEYS = frozenset(
    {"details", "id", "name", "status", "summary", "type", "visibility"}
)
ENTITY_TYPE_SUBTYPES = {
    "character": frozenset({"character"}),
    "crop_plot": frozenset({"crop_plot"}),
    "equipment": frozenset({"item"}),
    "item": frozenset({"item"}),
    "location": frozenset({"location"}),
    "material": frozenset({"item"}),
}
ENTITY_SUBTYPE_SHAPES = {
    "character": (
        "characters",
        frozenset(
            {
                "attitude",
                "consequences",
                "goals",
                "health_state",
                "knowledge",
                "role",
                "species_id",
                "stress",
                "trust",
            }
        ),
    ),
    "item": (
        "items",
        frozenset(
            {
                "category",
                "durability_current",
                "durability_max",
                "equipped_slot",
                "properties",
                "quality",
                "quantity",
                "stackable",
                "unit",
            }
        ),
    ),
    "location": (
        "locations",
        frozenset(
            {
                "biome",
                "coord_x",
                "coord_y",
                "coord_z",
                "description_short",
                "discovered_turn_id",
                "exits",
                "parent_id",
                "resources",
                "safety_level",
                "travel_minutes_from_home",
            }
        ),
    ),
    "crop_plot": (
        "crop_plots",
        frozenset(
            {
                "area_sqm",
                "crop_entity_id",
                "expected_yield",
                "growth_stage",
                "growth_stage_max",
                "harvest_day_max",
                "harvest_day_min",
                "harvest_status",
                "notes",
                "planted_day",
                "plot_no",
                "soil_status",
                "water_status",
            }
        ),
    ),
}
SAFE_ROLLBACK_NAMESPACES = frozenset(
    {
        "advisory",
        "advisory-review",
        "clock",
        "crop",
        "entity",
        "event",
        "item",
        "loc",
        "memory",
        "npc",
        "pc",
        "rel",
        "rule",
        "setting",
        "turn",
        "world",
    }
)
ENTITY_TYPE_NAMESPACES = {
    "character": frozenset({"char", "npc", "pc"}),
    "crop_plot": frozenset({"plot"}),
    "equipment": frozenset({"item"}),
    "faction": frozenset({"faction"}),
    "faction_state": frozenset({"fstate"}),
    "item": frozenset({"item"}),
    "location": frozenset({"loc"}),
    "material": frozenset({"mat"}),
    "plant": frozenset({"plant"}),
    "project": frozenset({"project"}),
    "recipe": frozenset({"recipe"}),
    "reference": frozenset({"ref"}),
    "species": frozenset({"creature", "species"}),
    "threat": frozenset({"threat"}),
}
SAFE_ROLLBACK_NAMESPACES = SAFE_ROLLBACK_NAMESPACES | frozenset().union(
    *ENTITY_TYPE_NAMESPACES.values()
)

FrozenValue = None | bool | int | float | str | tuple[Any, ...]


@dataclass(frozen=True)
class AdvisoryReviewAuthority:
    current_fact_authority: bool = False
    application_authorized: bool = False
    proposal_approval_is_commit: bool = False

    def to_dict(self) -> dict[str, bool]:
        if (
            type(self.current_fact_authority) is not bool
            or type(self.application_authorized) is not bool
            or type(self.proposal_approval_is_commit) is not bool
            or self.current_fact_authority
            or self.application_authorized
            or self.proposal_approval_is_commit
        ):
            raise ValueError(GENERIC_ERROR)
        return {
            "current_fact_authority": False,
            "application_authorized": False,
            "proposal_approval_is_commit": False,
        }


@dataclass(frozen=True)
class AdvisoryReviewArtifact:
    schema_version: str
    artifact_id: str
    suggestion_family: str
    suggestion_operation: str
    disposition: str
    target_ids: tuple[str, ...]
    candidate: tuple[Any, ...]
    validation: tuple[Any, ...]
    required_gate: str
    next_owner: str
    application_eligible: bool
    base_turn_id: str | None
    supersedes: tuple[str, ...]
    rollback_hint: tuple[Any, ...]
    source_advisory: tuple[Any, ...]
    authority: AdvisoryReviewAuthority


_ISSUED_ARTIFACTS: dict[
    int, tuple[weakref.ReferenceType[AdvisoryReviewArtifact], str, str]
] = {}


def _issue_artifact(artifact: AdvisoryReviewArtifact, fact_fingerprint: str) -> None:
    identity = id(artifact)

    def discard(reference: weakref.ReferenceType[AdvisoryReviewArtifact]) -> None:
        current = _ISSUED_ARTIFACTS.get(identity)
        if current is not None and current[0] is reference:
            _ISSUED_ARTIFACTS.pop(identity, None)

    _ISSUED_ARTIFACTS[identity] = (
        weakref.ref(artifact, discard),
        _artifact_issue_fingerprint(artifact),
        fact_fingerprint,
    )


def _is_issued_artifact(artifact: AdvisoryReviewArtifact) -> bool:
    issued = _ISSUED_ARTIFACTS.get(id(artifact))
    return (
        issued is not None
        and issued[0]() is artifact
        and issued[1] == _artifact_issue_fingerprint(artifact)
    )


def _issued_fact_fingerprint(artifact: AdvisoryReviewArtifact) -> str | None:
    issued = _ISSUED_ARTIFACTS.get(id(artifact))
    if (
        issued is None
        or issued[0]() is not artifact
        or issued[1] != _artifact_issue_fingerprint(artifact)
    ):
        return None
    return issued[2]


def _artifact_issue_fingerprint(artifact: AdvisoryReviewArtifact) -> str:
    return _digest(
        {
            "schema_version": artifact.schema_version,
            "artifact_id": artifact.artifact_id,
            "suggestion_family": artifact.suggestion_family,
            "suggestion_operation": artifact.suggestion_operation,
            "disposition": artifact.disposition,
            "target_ids": list(artifact.target_ids),
            "candidate": _thaw_mapping(artifact.candidate),
            "validation": _thaw_mapping(artifact.validation),
            "required_gate": artifact.required_gate,
            "next_owner": artifact.next_owner,
            "application_eligible": artifact.application_eligible,
            "base_turn_id": artifact.base_turn_id,
            "supersedes": list(artifact.supersedes),
            "rollback_hint": _thaw_mapping(artifact.rollback_hint),
            "source_advisory": _thaw_mapping(artifact.source_advisory),
            "authority": artifact.authority.to_dict(),
        }
    )


def build_advisory_review_artifact(
    conn: sqlite3.Connection,
    *,
    advisory: ResidentAIAdvisory,
    suggestion_family: str,
    suggestion_operation: str,
    candidate: dict[str, Any],
    disposition: str = "reviewable",
    base_turn_id: str | None = None,
    supersedes: tuple[str, ...] = (),
    rollback_hint: dict[str, Any] | None = None,
) -> AdvisoryReviewArtifact:
    try:
        _validate_connection(conn)
        if conn.in_transaction:
            raise ValueError(GENERIC_ERROR)
        initial_connection_state = _connection_state(conn)
        _validate_token(suggestion_family, SUGGESTION_FAMILIES)
        _validate_token(suggestion_operation, SUGGESTION_OPERATIONS)
        _validate_token(disposition, DISPOSITIONS)
        if suggestion_operation not in FAMILY_OPERATIONS[suggestion_family]:
            raise ValueError(GENERIC_ERROR)
        if type(advisory) is not ResidentAIAdvisory:
            raise ValueError(GENERIC_ERROR)
        normalized_advisory = normalize_resident_ai_advisory(advisory.to_dict())
        if normalized_advisory.visibility_mode not in {"player", "gm", "maintenance"}:
            raise ValueError(GENERIC_ERROR)
        if (
            normalized_advisory.advisory_type,
            normalized_advisory.proposed_next_workflow,
        ) != FAMILY_SOURCE_BINDINGS[suggestion_family]:
            raise ValueError(GENERIC_ERROR)
        candidate_snapshot = _stable_snapshot(candidate)
        rollback_snapshot = _stable_snapshot({} if rollback_hint is None else rollback_hint)
        candidate_dict = _thaw_mapping(candidate_snapshot)
        _validate_candidate_keys(candidate_dict)
        rollback_dict = _thaw_mapping(rollback_snapshot)
        _validate_rollback_hint(rollback_dict)
        supersedes_ids = _validate_string_tuple(supersedes)
        _validate_supersedes(supersedes_ids)

        targets = tuple(normalized_advisory.target_ids)
        if not targets:
            raise ValueError(GENERIC_ERROR)
        _validate_static_candidate(
            family=suggestion_family,
            operation=suggestion_operation,
            candidate=candidate_dict,
            targets=targets,
        )
        if suggestion_family == "memory_summary" and (
            tuple(candidate_dict["source_event_ids"])
            != normalized_advisory.freshness.source_event_ids
        ):
            raise ValueError(GENERIC_ERROR)
        bound_base_turn_id = (
            _source_base_turn_id(normalized_advisory)
            if base_turn_id is None
            else base_turn_id
        )
        _validate_base_turn(
            conn,
            bound_base_turn_id,
            required=_operation_requires_base(suggestion_family, suggestion_operation),
        )
        _validate_source_freshness_binding(
            normalized_advisory,
            base_turn_id=bound_base_turn_id,
            required=_operation_requires_base(suggestion_family, suggestion_operation),
        )
        required_gate, next_owner = GATE_OWNER[suggestion_family]
        validation, resolved_disposition = _preflight_candidate(
            conn,
            family=suggestion_family,
            operation=suggestion_operation,
            candidate=candidate_dict,
            targets=targets,
            view=normalized_advisory.visibility_mode,
            base_turn_id=bound_base_turn_id,
            requested_disposition=disposition,
            source_freshness_status=normalized_advisory.freshness.status,
            source_event_ids=normalized_advisory.freshness.source_event_ids,
        )
        eligible = (
            resolved_disposition == "reviewable"
            and bool(validation["ok"])
            and suggestion_family not in NO_APPLICATION_OWNER
        )
        if resolved_disposition != "reviewable" and not supersedes_ids and not rollback_dict:
            rollback_dict = {
                "strategy": (
                    "discard_draft" if resolved_disposition in {"rejected", "superseded"} else "revalidate"
                )
            }
            rollback_snapshot = _snapshot(rollback_dict)
        source_wire = normalized_advisory.to_dict()
        source_snapshot = _snapshot(source_wire)
        validation_snapshot = _snapshot(validation)
        digest_payload = {
            "schema_version": ADVISORY_REVIEW_SCHEMA_VERSION,
            "suggestion_family": suggestion_family,
            "suggestion_operation": suggestion_operation,
            "disposition": resolved_disposition,
            "target_ids": list(targets),
            "candidate": candidate_dict,
            "validation": validation,
            "required_gate": required_gate,
            "next_owner": next_owner,
            "application_eligible": eligible,
            "base_turn_id": bound_base_turn_id,
            "supersedes": list(supersedes_ids),
            "rollback_hint": rollback_dict,
            "source_advisory": source_wire,
        }
        artifact_id = "advisory-review:" + _digest(digest_payload)
        artifact = AdvisoryReviewArtifact(
            schema_version=ADVISORY_REVIEW_SCHEMA_VERSION,
            artifact_id=artifact_id,
            suggestion_family=suggestion_family,
            suggestion_operation=suggestion_operation,
            disposition=resolved_disposition,
            target_ids=targets,
            candidate=candidate_snapshot,
            validation=validation_snapshot,
            required_gate=required_gate,
            next_owner=next_owner,
            application_eligible=eligible,
            base_turn_id=bound_base_turn_id,
            supersedes=supersedes_ids,
            rollback_hint=rollback_snapshot,
            source_advisory=source_snapshot,
            authority=AdvisoryReviewAuthority(),
        )
        fact_fingerprint = _authoritative_fact_fingerprint(conn)
        _validate_connection(conn)
        if _connection_state(conn) != initial_connection_state:
            raise ValueError(GENERIC_ERROR)
        _issue_artifact(artifact, fact_fingerprint)
        return artifact
    except (MemoryError, RecursionError):
        raise
    except Exception:
        raise ValueError(GENERIC_ERROR) from None


def advisory_review_to_maintenance_dict(artifact: AdvisoryReviewArtifact) -> dict[str, Any]:
    try:
        wire = _artifact_wire(artifact, include_candidate=True)
        _validate_artifact_digest(wire)
        return _json_copy(wire)
    except (MemoryError, RecursionError):
        raise
    except Exception:
        raise ValueError(GENERIC_ERROR) from None


def advisory_review_to_player_dict(
    conn: sqlite3.Connection,
    artifact: AdvisoryReviewArtifact,
) -> dict[str, Any]:
    try:
        _validate_connection(conn)
        if conn.in_transaction:
            return dict(GENERIC_UNAVAILABLE)
        initial_connection_state = _connection_state(conn)
        wire = _artifact_wire(artifact, include_candidate=False)
        _validate_artifact_digest(_artifact_wire(artifact, include_candidate=True))
        issued_fact_fingerprint = _issued_fact_fingerprint(artifact)
        if issued_fact_fingerprint is None:
            return dict(GENERIC_UNAVAILABLE)
        if artifact.disposition != "reviewable":
            return dict(GENERIC_UNAVAILABLE)
        source = normalize_resident_ai_advisory(_thaw_mapping(artifact.source_advisory))
        _validate_base_turn(
            conn,
            artifact.base_turn_id,
            required=_operation_requires_base(
                artifact.suggestion_family, artifact.suggestion_operation
            ),
        )
        source_projection = resident_ai_advisory_to_player_dict(source, conn=conn)
        if source_projection.get("ok") is not True or source_projection.get("status") != "available":
            return dict(GENERIC_UNAVAILABLE)
        if tuple(source_projection.get("target_ids", ())) != artifact.target_ids:
            return dict(GENERIC_UNAVAILABLE)
        current_validation, current_disposition = _preflight_candidate(
            conn,
            family=artifact.suggestion_family,
            operation=artifact.suggestion_operation,
            candidate=_thaw_mapping(artifact.candidate),
            targets=artifact.target_ids,
            view="player",
            base_turn_id=artifact.base_turn_id,
            requested_disposition="reviewable",
            source_freshness_status=source.freshness.status,
            source_event_ids=source.freshness.source_event_ids,
        )
        if current_disposition != "reviewable" or current_validation["ok"] is not True:
            return dict(GENERIC_UNAVAILABLE)
        if _authoritative_fact_fingerprint(conn) != issued_fact_fingerprint:
            return dict(GENERIC_UNAVAILABLE)
        _validate_connection(conn)
        if _connection_state(conn) != initial_connection_state:
            return dict(GENERIC_UNAVAILABLE)
        return {
            "available": True,
            "schema_version": wire["schema_version"],
            "suggestion_family": wire["suggestion_family"],
            "suggestion_operation": wire["suggestion_operation"],
            "disposition": wire["disposition"],
            "target_ids": list(artifact.target_ids),
            "authority": wire["authority"],
        }
    except (MemoryError, RecursionError):
        raise
    except Exception:
        return dict(GENERIC_UNAVAILABLE)


def _preflight_candidate(
    conn: sqlite3.Connection,
    *,
    family: str,
    operation: str,
    candidate: dict[str, Any],
    targets: tuple[str, ...],
    view: str,
    base_turn_id: str | None,
    requested_disposition: str,
    source_freshness_status: str,
    source_event_ids: tuple[str, ...],
) -> tuple[dict[str, Any], str]:
    errors: list[str] = []
    warnings: list[str] = []
    state_disposition = requested_disposition

    if source_freshness_status != "current" and state_disposition == "reviewable":
        state_disposition = "stale"
        errors.append("source_not_current")
    source_error_count = len(errors)
    _validate_source_events(
        conn,
        source_event_ids,
        view=view,
        base_turn_id=base_turn_id,
        errors=errors,
    )
    if len(errors) > source_error_count and state_disposition == "reviewable":
        state_disposition = "stale"

    if family in {"entity", "relationship"}:
        primary_id = _content_candidate_primary_id(candidate, family)
        _require_exact_targets((primary_id,), targets)
        candidate_entity = candidate["upsert_entities"][0]
        if operation == "create" and "visibility" not in candidate_entity:
            raise ValueError(GENERIC_ERROR)
        candidate_visibility = candidate_entity.get("visibility")
        if view == "player" and is_player_hidden_visibility(candidate_visibility):
            state_disposition = "conflict"
            errors.append("visibility_unavailable")
        validation = validate_content_delta(candidate, conn)
        if validation.errors:
            errors.append("content_validation_failed")
        if validation.warnings:
            warnings.append("content_validation_warning")
        authoritative_entity = read_entity(
            conn, primary_id, view="maintenance", include_archived=True
        )
        authoritative_current = (
            authoritative_entity
            if family == "entity"
            else read_relationship(conn, primary_id, view="maintenance", include_archived=True)
        )
        if family == "entity":
            current = read_entity(conn, primary_id, view=view, include_archived=False)
            reference_error_count = len(errors)
            _validate_entity_candidate_references(
                conn,
                candidate,
                view=view,
                base_turn_id=base_turn_id,
                errors=errors,
            )
            if len(errors) > reference_error_count and state_disposition == "reviewable":
                state_disposition = (
                    "stale" if "target_stale" in errors[reference_error_count:] else "conflict"
                )
        else:
            current = read_relationship(conn, primary_id, view=view, include_archived=False)
            endpoint_error_count = len(errors)
            _validate_relationship_candidate_endpoints(
                conn,
                candidate,
                view=view,
                base_turn_id=base_turn_id,
                errors=errors,
            )
            if len(errors) > endpoint_error_count and state_disposition == "reviewable":
                state_disposition = (
                    "stale" if "endpoint_stale" in errors[endpoint_error_count:] else "conflict"
                )
        if operation == "create" and authoritative_entity is not None:
            state_disposition = "conflict"
            errors.append("target_already_exists")
        if operation == "update":
            if current is None:
                state_disposition = "stale"
                errors.append("target_unavailable")
            elif family == "entity" and not _entity_update_shape_complete(
                conn, candidate, primary_id
            ):
                state_disposition = "conflict"
                errors.append("replacement_shape_conflict")
            elif not _candidate_preserves_aliases(conn, candidate, primary_id):
                state_disposition = "conflict"
                errors.append("alias_boundary_unavailable")
            elif family == "relationship" and set(
                candidate["upsert_entities"][0]["details"]
            ) != set(current.details):
                state_disposition = "conflict"
                errors.append("details_shape_conflict")
            elif family == "relationship" and any(
                candidate["upsert_entities"][0]["details"].get(key)
                != current.details.get(key)
                for key in ("source_id", "target_id", "kind")
            ):
                state_disposition = "conflict"
                errors.append("details_shape_conflict")
            elif _updated_after_base(conn, current.updated_turn_id, base_turn_id):
                state_disposition = "stale"
                errors.append("target_stale")
            elif family == "entity" and current.type != candidate["upsert_entities"][0]["type"]:
                state_disposition = "conflict"
                errors.append("value_invalid")
    elif family == "alias":
        primary_id = _exact_string(candidate, "target_id")
        _require_exact_keys(candidate, {"target_id", "alias"})
        _require_exact_targets((primary_id,), targets)
        alias = _exact_string(candidate, "alias")
        if len(alias) > 160:
            errors.append("value_exceeds_limit")
        current = read_entity(conn, primary_id, view=view, include_archived=False)
        if current is None or _updated_after_base(conn, current.updated_turn_id if current else "", base_turn_id):
            state_disposition = "stale"
            errors.append("target_unavailable" if current is None else "target_stale")
    elif family == "memory_summary":
        _require_exact_keys(candidate, {"target_id", "summary", "source_event_ids"})
        primary_id = _exact_string(candidate, "target_id")
        _require_exact_targets((primary_id,), targets)
        summary = _exact_string(candidate, "summary")
        if len(summary) > 1024:
            errors.append("value_exceeds_limit")
        event_ids = _validate_string_list(candidate["source_event_ids"], prefix="event:")
        if event_ids != source_event_ids:
            raise ValueError(GENERIC_ERROR)
        else:
            _validate_source_events(
                conn,
                event_ids,
                view=view,
                base_turn_id=base_turn_id,
                errors=errors,
            )
        current = read_entity(conn, primary_id, view=view, include_archived=False)
        if current is None or _updated_after_base(conn, current.updated_turn_id if current else "", base_turn_id):
            state_disposition = "stale"
            errors.append("target_unavailable" if current is None else "target_stale")
        if errors and state_disposition == "reviewable":
            state_disposition = "stale"
    elif family == "progress_definition":
        _require_exact_keys(candidate, {"target_id", "segments_total", "summary"})
        primary_id = _exact_string(candidate, "target_id")
        _require_exact_targets((primary_id,), targets)
        total = candidate["segments_total"]
        if type(total) is not int or total <= 0:
            errors.append("value_invalid")
        _exact_string(candidate, "summary")
        authoritative_entity = read_entity(
            conn, primary_id, view="maintenance", include_archived=True
        )
        if operation == "create":
            if authoritative_entity is not None:
                state_disposition = "conflict"
                errors.append("target_already_exists")
        else:
            current = read_progress(conn, primary_id, view=view, include_archived=False)
            if current is None:
                state_disposition = "stale"
                errors.append("target_unavailable")
            elif _updated_after_base(conn, current.updated_turn_id, base_turn_id):
                state_disposition = "stale"
                errors.append("target_stale")
    else:
        _require_exact_keys(candidate, {"tick_clocks"})
        ticks = candidate["tick_clocks"]
        if type(ticks) is not list or not ticks:
            raise ValueError(GENERIC_ERROR)
        tick_ids: list[str] = []
        for item in ticks:
            if type(item) is not dict:
                raise ValueError(GENERIC_ERROR)
            _require_exact_keys(item, {"id", "delta", "reason"})
            clock_id = _exact_string(item, "id")
            if not is_valid_clock_id(clock_id):
                raise ValueError(GENERIC_ERROR)
            tick_ids.append(clock_id)
        _require_exact_targets(tuple(tick_ids), targets)
        if validate_delta_progress_references(conn, candidate, view=view):
            errors.append("progress_reference_validation_failed")
        for clock_id in tick_ids:
            current = read_progress(conn, clock_id, view=view, include_archived=False)
            if current is None or _updated_after_base(conn, current.updated_turn_id if current else "", base_turn_id):
                state_disposition = "stale"
                errors.append("target_unavailable" if current is None else "target_stale")

    if requested_disposition != "reviewable":
        state_disposition = requested_disposition
    return {
        "ok": not errors and state_disposition == "reviewable",
        "errors": _safe_validation_messages(errors),
        "warnings": _safe_validation_messages(warnings),
        "preflight_only": True,
        "requires_revalidation_on_apply": True,
    }, state_disposition


def _content_candidate_primary_id(candidate: dict[str, Any], family: str) -> str:
    _require_exact_keys(candidate, {"upsert_entities"})
    entities = candidate["upsert_entities"]
    if type(entities) is not list or len(entities) != 1 or type(entities[0]) is not dict:
        raise ValueError(GENERIC_ERROR)
    entity = entities[0]
    entity_id = _exact_string(entity, "id")
    entity_type = _exact_string(entity, "type")
    if family == "relationship" and entity_type != "relationship":
        raise ValueError(GENERIC_ERROR)
    if family == "relationship" and not entity_id.startswith("rel:"):
        raise ValueError(GENERIC_ERROR)
    if family == "entity" and entity_type in {
        "relationship",
        "clock",
        "rule",
        "world_setting",
    }:
        raise ValueError(GENERIC_ERROR)
    if family == "entity":
        namespace = entity_id.split(":", 1)[0]
        if namespace not in ENTITY_TYPE_NAMESPACES.get(entity_type, frozenset()):
            raise ValueError(GENERIC_ERROR)
    return entity_id


def _validate_static_candidate(
    *,
    family: str,
    operation: str,
    candidate: dict[str, Any],
    targets: tuple[str, ...],
) -> None:
    if family in {"entity", "relationship"}:
        primary_id = _content_candidate_primary_id(candidate, family)
        _require_exact_targets((primary_id,), targets)
        entity = candidate["upsert_entities"][0]
        if not set(entity).issubset(ENTITY_CANDIDATE_KEYS):
            raise ValueError(GENERIC_ERROR)
        if family == "relationship" and not set(entity).issubset(RELATIONSHIP_CANDIDATE_KEYS):
            raise ValueError(GENERIC_ERROR)
        if (
            family == "relationship"
            and operation == "update"
            and not RELATIONSHIP_UPDATE_BASE_KEYS.issubset(entity)
        ):
            raise ValueError(GENERIC_ERROR)
        if family == "entity" and operation == "update" and not ENTITY_UPDATE_BASE_KEYS.issubset(entity):
            raise ValueError(GENERIC_ERROR)
        if family == "entity":
            subtype_sections = {
                section for section in ENTITY_SUBTYPE_SHAPES if section in entity
            }
            if not subtype_sections.issubset(
                ENTITY_TYPE_SUBTYPES.get(str(entity["type"]), frozenset())
            ):
                raise ValueError(GENERIC_ERROR)
            for section in subtype_sections:
                block = entity[section]
                allowed_keys = ENTITY_SUBTYPE_SHAPES[section][1]
                if type(block) is not dict or not set(block).issubset(allowed_keys):
                    raise ValueError(GENERIC_ERROR)
        if "aliases" in entity and operation != "update":
            raise ValueError(GENERIC_ERROR)
        if "visibility" in entity and (
            type(entity["visibility"]) is not str
            or entity["visibility"] not in ENTITY_VISIBILITY_LABELS
        ):
            raise ValueError(GENERIC_ERROR)
        if "status" in entity and (
            type(entity["status"]) is not str
            or entity["status"] not in {"active", "archived"}
        ):
            raise ValueError(GENERIC_ERROR)
        entity_spec = next(
            (
                spec
                for spec in get_default_registry().delta_specs()
                if spec.delta_key == "upsert_entities"
            ),
            None,
        )
        if entity_spec is None or entity_spec.validate_record is None:
            raise ValueError(GENERIC_ERROR)
        if entity_spec.validate_record(entity):
            raise ValueError(GENERIC_ERROR)
        _safe_visible_candidate_text(entity, "name", maximum=240)
        _safe_visible_candidate_text(entity, "summary", maximum=1024)
        _validate_entity_numeric_fields(entity)
        if family == "relationship":
            details = entity.get("details")
            if type(details) is not dict:
                raise ValueError(GENERIC_ERROR)
            if not {"source_id", "target_id", "kind"}.issubset(details):
                raise ValueError(GENERIC_ERROR)
            if not set(details).issubset(
                {
                    "source_id",
                    "target_id",
                    "kind",
                    "state",
                    "attitude",
                    "stance",
                    "trust",
                    "notes",
                }
            ):
                raise ValueError(GENERIC_ERROR)
            _exact_string(details, "source_id")
            _exact_string(details, "target_id")
            for key in ("kind", "state", "attitude", "stance", "notes"):
                if key == "kind" or key in details:
                    _safe_visible_candidate_text(details, key, maximum=160)
            if "trust" in details:
                _require_bounded_number(details["trust"], integer=True, minimum=-MAX_PROGRESS_VALUE)
        _validate_candidate_text_safety(entity)
    elif family == "alias":
        _require_exact_keys(candidate, {"target_id", "alias"})
        primary_id = _exact_string(candidate, "target_id")
        _safe_visible_candidate_text(candidate, "alias", maximum=160)
        _require_exact_targets((primary_id,), targets)
    elif family == "memory_summary":
        _require_exact_keys(candidate, {"target_id", "summary", "source_event_ids"})
        primary_id = _exact_string(candidate, "target_id")
        _safe_visible_candidate_text(candidate, "summary", maximum=1024)
        _validate_string_list(candidate["source_event_ids"], prefix="event:")
        _require_exact_targets((primary_id,), targets)
    elif family == "progress_definition":
        _require_exact_keys(candidate, {"target_id", "segments_total", "summary"})
        primary_id = _exact_string(candidate, "target_id")
        if not is_valid_clock_id(primary_id):
            raise ValueError(GENERIC_ERROR)
        if (
            type(candidate["segments_total"]) is not int
            or candidate["segments_total"] <= 0
            or candidate["segments_total"] > MAX_PROGRESS_VALUE
        ):
            raise ValueError(GENERIC_ERROR)
        _safe_visible_candidate_text(candidate, "summary", maximum=1024)
        _require_exact_targets((primary_id,), targets)
    else:
        _require_exact_keys(candidate, {"tick_clocks"})
        ticks = candidate["tick_clocks"]
        if type(ticks) is not list or not ticks:
            raise ValueError(GENERIC_ERROR)
        tick_ids: list[str] = []
        for item in ticks:
            if type(item) is not dict:
                raise ValueError(GENERIC_ERROR)
            _require_exact_keys(item, {"id", "delta", "reason"})
            tick_ids.append(_exact_string(item, "id"))
            if (
                type(item["delta"]) is not int
                or item["delta"] == 0
                or abs(item["delta"]) > MAX_PROGRESS_VALUE
            ):
                raise ValueError(GENERIC_ERROR)
            _safe_visible_candidate_text(item, "reason", maximum=240)
        _require_exact_targets(tuple(tick_ids), targets)


def _validate_validation_summary(value: dict[str, Any], *, disposition: str) -> None:
    _require_exact_keys(
        value,
        {"ok", "errors", "warnings", "preflight_only", "requires_revalidation_on_apply"},
    )
    if (
        type(value["ok"]) is not bool
        or value["preflight_only"] is not True
        or value["requires_revalidation_on_apply"] is not True
    ):
        raise ValueError(GENERIC_ERROR)
    errors = _validate_safe_message_list(value["errors"])
    _validate_safe_message_list(value["warnings"])
    if value["ok"] is not (not errors and disposition == "reviewable"):
        raise ValueError(GENERIC_ERROR)


def _validate_relationship_candidate_endpoints(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    *,
    view: str,
    base_turn_id: str | None,
    errors: list[str],
) -> None:
    entity = candidate["upsert_entities"][0]
    details = entity.get("details")
    if type(details) is not dict:
        return
    for key in ("source_id", "target_id"):
        endpoint = details.get(key)
        current = (
            read_entity(conn, endpoint, view=view, include_archived=False)
            if type(endpoint) is str
            else None
        )
        if current is None:
            errors.append("endpoint_unavailable")
        elif base_turn_id is not None and _updated_after_base(conn, current.updated_turn_id, base_turn_id):
            errors.append("endpoint_stale")


def _validate_source_events(
    conn: sqlite3.Connection,
    event_ids: tuple[str, ...],
    *,
    view: str,
    base_turn_id: str | None,
    errors: list[str],
) -> None:
    if tuple(resolvable_memory_event_ids(conn, list(event_ids), view=view)) != event_ids:
        errors.append("source_unavailable")
        return
    for event_id in event_ids:
        row = conn.execute(
            "select e.turn_id from main.events e where e.id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            errors.append("source_unavailable")
        elif _updated_after_base(conn, str(row["turn_id"]), base_turn_id):
            errors.append("source_stale")


def _validate_entity_candidate_references(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    *,
    view: str,
    base_turn_id: str | None,
    errors: list[str],
) -> None:
    entity = candidate["upsert_entities"][0]
    refs: list[Any] = [entity.get("location_id"), entity.get("owner_id")]
    for section, key in (
        ("character", "species_id"),
        ("location", "parent_id"),
        ("crop_plot", "crop_entity_id"),
    ):
        nested = entity.get(section)
        if type(nested) is dict:
            refs.append(nested.get(key))
    primary_id = entity["id"]
    for ref in refs:
        if ref is None:
            continue
        if ref == primary_id:
            errors.append("reference_unavailable")
            continue
        current = (
            read_entity(conn, ref, view=view, include_archived=False)
            if type(ref) is str
            else None
        )
        if current is None:
            errors.append("reference_unavailable")
        elif _updated_after_base(conn, current.updated_turn_id, base_turn_id):
            errors.append("target_stale")
    location = entity.get("location")
    if type(location) is dict and location.get("discovered_turn_id") is not None:
        discovered_turn_id = location["discovered_turn_id"]
        if (
            not _is_turn_id(discovered_turn_id)
            or conn.execute(
                "select 1 from main.turns where id = ?", (discovered_turn_id,)
            ).fetchone()
            is None
            or _updated_after_base(conn, discovered_turn_id, base_turn_id)
        ):
            errors.append("target_stale")


def _candidate_preserves_aliases(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    entity_id: str,
) -> bool:
    current = tuple(
        str(row["alias"])
        for row in conn.execute(
            "select alias from main.aliases where entity_id = ? and kind = 'name' order by alias",
            (entity_id,),
        ).fetchall()
    )
    entity = candidate["upsert_entities"][0]
    if "aliases" not in entity:
        return not current
    aliases = entity["aliases"]
    if type(aliases) is not list or any(type(alias) is not str for alias in aliases):
        return False
    return tuple(sorted(aliases)) == current and len(set(aliases)) == len(aliases)


def _entity_update_shape_complete(
    conn: sqlite3.Connection,
    candidate: dict[str, Any],
    entity_id: str,
) -> bool:
    entity = candidate["upsert_entities"][0]
    current_sections: set[str] = set()
    candidate_sections = {
        section for section in ENTITY_SUBTYPE_SHAPES if section in entity
    }
    for section, (table, required_keys) in ENTITY_SUBTYPE_SHAPES.items():
        exists = conn.execute(
            f'select 1 from main."{table}" where entity_id = ? limit 1',
            (entity_id,),
        ).fetchone() is not None
        if exists:
            current_sections.add(section)
        if section in entity:
            value = entity[section]
            if type(value) is not dict or set(value) != required_keys:
                return False
    return candidate_sections == current_sections


def _artifact_wire(artifact: AdvisoryReviewArtifact, *, include_candidate: bool) -> dict[str, Any]:
    if type(artifact) is not AdvisoryReviewArtifact or not _is_issued_artifact(artifact):
        raise ValueError(GENERIC_ERROR)
    _validate_token(artifact.schema_version, frozenset({ADVISORY_REVIEW_SCHEMA_VERSION}))
    _validate_token(artifact.suggestion_family, SUGGESTION_FAMILIES)
    _validate_token(artifact.suggestion_operation, SUGGESTION_OPERATIONS)
    _validate_token(artifact.disposition, DISPOSITIONS)
    if artifact.suggestion_operation not in FAMILY_OPERATIONS[artifact.suggestion_family]:
        raise ValueError(GENERIC_ERROR)
    if type(artifact.application_eligible) is not bool or type(artifact.artifact_id) is not str:
        raise ValueError(GENERIC_ERROR)
    if type(artifact.authority) is not AdvisoryReviewAuthority:
        raise ValueError(GENERIC_ERROR)
    if artifact.base_turn_id is not None and not _is_turn_id(artifact.base_turn_id):
        raise ValueError(GENERIC_ERROR)
    if _operation_requires_base(artifact.suggestion_family, artifact.suggestion_operation) and artifact.base_turn_id is None:
        raise ValueError(GENERIC_ERROR)
    if GATE_OWNER.get(artifact.suggestion_family) != (artifact.required_gate, artifact.next_owner):
        raise ValueError(GENERIC_ERROR)
    targets = _validate_string_tuple(artifact.target_ids)
    candidate = _thaw_mapping(artifact.candidate)
    _validate_candidate_keys(candidate)
    _validate_static_candidate(
        family=artifact.suggestion_family,
        operation=artifact.suggestion_operation,
        candidate=candidate,
        targets=targets,
    )
    validation = _thaw_mapping(artifact.validation)
    _validate_validation_summary(validation, disposition=artifact.disposition)
    expected_eligible = (
        artifact.disposition == "reviewable"
        and validation["ok"] is True
        and artifact.suggestion_family not in NO_APPLICATION_OWNER
    )
    if artifact.application_eligible is not expected_eligible:
        raise ValueError(GENERIC_ERROR)
    supersedes = _validate_string_tuple(artifact.supersedes)
    _validate_supersedes(supersedes)
    rollback = _thaw_mapping(artifact.rollback_hint)
    _validate_rollback_hint(rollback)
    source_wire = _thaw_mapping(artifact.source_advisory)
    source = normalize_resident_ai_advisory(source_wire)
    if (
        source.advisory_type,
        source.proposed_next_workflow,
    ) != FAMILY_SOURCE_BINDINGS[artifact.suggestion_family]:
        raise ValueError(GENERIC_ERROR)
    if tuple(source.target_ids) != targets:
        raise ValueError(GENERIC_ERROR)
    if artifact.suggestion_family == "memory_summary" and (
        tuple(candidate["source_event_ids"]) != source.freshness.source_event_ids
    ):
        raise ValueError(GENERIC_ERROR)
    if source.freshness.status != "current" and artifact.disposition == "reviewable":
        raise ValueError(GENERIC_ERROR)
    _validate_source_freshness_binding(
        source,
        base_turn_id=artifact.base_turn_id,
        required=_operation_requires_base(
            artifact.suggestion_family, artifact.suggestion_operation
        ),
    )
    if artifact.disposition != "reviewable" and not supersedes and not rollback:
        raise ValueError(GENERIC_ERROR)
    wire = {
        "schema_version": artifact.schema_version,
        "artifact_id": artifact.artifact_id,
        "suggestion_family": artifact.suggestion_family,
        "suggestion_operation": artifact.suggestion_operation,
        "disposition": artifact.disposition,
        "target_ids": list(targets),
        "candidate": candidate,
        "validation": validation,
        "required_gate": artifact.required_gate,
        "next_owner": artifact.next_owner,
        "application_eligible": artifact.application_eligible,
        "base_turn_id": artifact.base_turn_id,
        "supersedes": list(supersedes),
        "rollback_hint": rollback,
        "source_advisory": source.to_dict(),
        "authority": artifact.authority.to_dict(),
    }
    if not include_candidate:
        wire.pop("candidate")
        wire.pop("validation")
        wire.pop("rollback_hint")
        wire.pop("source_advisory")
        wire.pop("artifact_id")
        wire.pop("base_turn_id")
        wire.pop("supersedes")
        wire.pop("required_gate")
        wire.pop("next_owner")
        wire.pop("application_eligible")
    return wire


def _validate_artifact_digest(wire: dict[str, Any]) -> None:
    artifact_id = wire.get("artifact_id")
    payload = dict(wire)
    payload.pop("artifact_id", None)
    payload.pop("authority", None)
    expected = "advisory-review:" + _digest(payload)
    if artifact_id != expected:
        raise ValueError(GENERIC_ERROR)


def _updated_after_base(conn: sqlite3.Connection, updated_turn_id: str, base_turn_id: str | None) -> bool:
    if not base_turn_id or not updated_turn_id or updated_turn_id == base_turn_id:
        return False
    rows = conn.execute(
        "select id from main.turns where id in (?, ?)",
        (updated_turn_id, base_turn_id),
    ).fetchall()
    ids = {str(row["id"]) for row in rows}
    if updated_turn_id not in ids or base_turn_id not in ids:
        return True
    updated_order = _canonical_turn_order(updated_turn_id)
    base_order = _canonical_turn_order(base_turn_id)
    if updated_order is None or base_order is None:
        return True
    return updated_order > base_order


def _canonical_turn_order(turn_id: str) -> int | None:
    if turn_id == "turn:seed":
        return 0
    if TURN_ID_PATTERN.fullmatch(turn_id) is None:
        return None
    return int(turn_id.split(":", 1)[1])


def _validate_candidate_keys(value: Any) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if (
                type(key) is not str
                or not key
                or len(key) > MAX_STRING
                or not is_safe_visible_text(key)
            ):
                raise ValueError(GENERIC_ERROR)
            if _canonical_control_key(key) in FORBIDDEN_CONTROL_KEYS:
                raise ValueError(GENERIC_ERROR)
            _validate_candidate_keys(item)
    elif type(value) is list:
        for item in value:
            _validate_candidate_keys(item)


def _validate_candidate_text_safety(value: Any) -> None:
    if type(value) is dict:
        for item in value.values():
            _validate_candidate_text_safety(item)
    elif type(value) is list:
        for item in value:
            _validate_candidate_text_safety(item)
    elif type(value) is str and value and not is_safe_visible_text(value):
        raise ValueError(GENERIC_ERROR)


def _snapshot(value: Any) -> tuple[Any, ...]:
    budget = [0]
    frozen = _freeze(value, depth=0, budget=budget)
    if type(frozen) is not tuple or not frozen or frozen[0] != "dict":
        raise ValueError(GENERIC_ERROR)
    return frozen


def _stable_snapshot(value: Any) -> tuple[Any, ...]:
    first = _snapshot(value)
    second = _snapshot(value)
    if first != second:
        raise ValueError(GENERIC_ERROR)
    return first


def _freeze(value: Any, *, depth: int, budget: list[int]) -> FrozenValue:
    budget[0] += 1
    if depth > MAX_DEPTH or budget[0] > MAX_ITEMS:
        raise ValueError(GENERIC_ERROR)
    if value is None or type(value) in {bool, int, str}:
        if type(value) is str:
            if len(value) > MAX_STRING:
                raise ValueError(GENERIC_ERROR)
            value.encode("utf-8")
        if type(value) is int and abs(value) > MAX_SAFE_INTEGER:
            raise ValueError(GENERIC_ERROR)
        return value
    if type(value) is float:
        if not math.isfinite(value) or abs(value) > MAX_SAFE_INTEGER:
            raise ValueError(GENERIC_ERROR)
        return value
    if type(value) is dict:
        items: list[tuple[str, FrozenValue]] = []
        keys = list(value)
        if any(type(key) is not str or len(key) > 128 for key in keys):
            raise ValueError(GENERIC_ERROR)
        for key in sorted(keys):
            if type(key) is not str:
                raise ValueError(GENERIC_ERROR)
            items.append((key, _freeze(value[key], depth=depth + 1, budget=budget)))
        return ("dict", *items)
    if type(value) is list:
        return ("list", *(_freeze(item, depth=depth + 1, budget=budget) for item in value))
    raise ValueError(GENERIC_ERROR)


def _thaw(value: FrozenValue) -> Any:
    if type(value) is tuple:
        if not value:
            raise ValueError(GENERIC_ERROR)
        if value[0] == "dict":
            result: dict[str, Any] = {}
            for item in value[1:]:
                if type(item) is not tuple or len(item) != 2 or type(item[0]) is not str or item[0] in result:
                    raise ValueError(GENERIC_ERROR)
                result[item[0]] = _thaw(item[1])
            return result
        if value[0] == "list":
            return [_thaw(item) for item in value[1:]]
        raise ValueError(GENERIC_ERROR)
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise ValueError(GENERIC_ERROR)


def _thaw_mapping(value: tuple[Any, ...]) -> dict[str, Any]:
    result = _thaw(value)
    if type(result) is not dict:
        raise ValueError(GENERIC_ERROR)
    return result


def _json_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _digest(value: dict[str, Any]) -> str:
    wire = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def _validate_connection(conn: sqlite3.Connection) -> None:
    if not isinstance(conn, sqlite3.Connection) or conn.row_factory is not sqlite3.Row:
        raise ValueError(GENERIC_ERROR)
    normalize_visibility_view("maintenance")
    authoritative = conn.execute(
        "select count(*) from main.sqlite_master where type='table' and lower(name) in ('entities', 'clocks')"
    ).fetchone()
    if authoritative is None or int(authoritative[0]) != 2:
        raise ValueError(GENERIC_ERROR)
    shadow = conn.execute(
        """
        select 1
        from sqlite_temp_master temp
        join main.sqlite_master authoritative
          on lower(authoritative.name) = lower(temp.name)
        where temp.type in ('table', 'view')
          and authoritative.type in ('table', 'view')
        limit 1
        """
    ).fetchone()
    if shadow is not None:
        raise ValueError(GENERIC_ERROR)


def _data_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("pragma data_version").fetchone()
    if row is None or type(row[0]) is not int:
        raise ValueError(GENERIC_ERROR)
    return int(row[0])


def _schema_version(conn: sqlite3.Connection, schema: str) -> int:
    if schema not in {"main", "temp"}:
        raise ValueError(GENERIC_ERROR)
    row = conn.execute(f"pragma {schema}.schema_version").fetchone()
    if row is None or type(row[0]) is not int:
        raise ValueError(GENERIC_ERROR)
    return int(row[0])


def _connection_state(conn: sqlite3.Connection) -> tuple[int, int, int, bool, int]:
    return (
        _data_version(conn),
        _schema_version(conn, "main"),
        _schema_version(conn, "temp"),
        conn.in_transaction,
        conn.total_changes,
    )


def _authoritative_fact_fingerprint(conn: sqlite3.Connection) -> str:
    existing_tables = {
        str(row["name"])
        for row in conn.execute(
            "select name from main.sqlite_master where type = 'table'"
        ).fetchall()
    }
    digest = hashlib.sha256()
    for table in AUTHORITATIVE_FACT_TABLES:
        if table not in existing_tables:
            continue
        rows = [
            tuple(row)
            for row in conn.execute(f'select * from main."{table}"').fetchall()
        ]
        digest.update(table.encode("utf-8"))
        for row in sorted(rows, key=repr):
            digest.update(repr(row).encode("utf-8"))
    return digest.hexdigest()


def _validate_token(value: Any, allowed: frozenset[str]) -> None:
    if type(value) is not str or value not in allowed:
        raise ValueError(GENERIC_ERROR)


def _validate_string_tuple(value: Any) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > 32:
        raise ValueError(GENERIC_ERROR)
    result: list[str] = []
    for item in value:
        if type(item) is not str or not item or len(item) > 256 or item in result:
            raise ValueError(GENERIC_ERROR)
        item.encode("utf-8")
        result.append(item)
    return tuple(result)


def _require_exact_keys(value: dict[str, Any], allowed: set[str]) -> None:
    if type(value) is not dict or set(value) != allowed:
        raise ValueError(GENERIC_ERROR)


def _exact_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if type(item) is not str or not item or item != item.strip():
        raise ValueError(GENERIC_ERROR)
    item.encode("utf-8")
    return item


def _safe_visible_candidate_text(
    value: dict[str, Any],
    key: str,
    *,
    maximum: int,
) -> str:
    item = _exact_string(value, key)
    if len(item) > maximum or not is_safe_visible_text(item):
        raise ValueError(GENERIC_ERROR)
    return item


def _validate_entity_numeric_fields(entity: dict[str, Any]) -> None:
    character = entity.get("character")
    if type(character) is dict:
        _require_optional_string_fields(
            character, ("species_id", "role", "attitude", "health_state")
        )
        if "trust" in character:
            _require_bounded_number(character["trust"], integer=True, minimum=-MAX_PROGRESS_VALUE)
        _require_optional_container_fields(character, ("stress", "knowledge"), dict)
        _require_optional_container_fields(character, ("consequences", "goals"), list)

    item = entity.get("item")
    if type(item) is dict:
        _require_optional_string_fields(
            item, ("category", "unit", "quality", "equipped_slot")
        )
        if "quantity" in item:
            _require_bounded_number(item["quantity"], integer=False, minimum=0)
        for key in ("durability_current", "durability_max"):
            if key in item:
                _require_bounded_number(item[key], integer=True, minimum=0)
        if (
            "durability_current" in item
            and "durability_max" in item
            and item["durability_current"] > item["durability_max"]
        ):
            raise ValueError(GENERIC_ERROR)
        if "stackable" in item and type(item["stackable"]) is not bool:
            raise ValueError(GENERIC_ERROR)
        _require_optional_container_fields(item, ("properties",), dict)

    location = entity.get("location")
    if type(location) is dict:
        _require_optional_string_fields(
            location,
            ("parent_id", "biome", "safety_level", "discovered_turn_id", "description_short"),
        )
        for key in ("coord_x", "coord_y", "coord_z"):
            if key in location:
                _require_bounded_number(location[key], integer=False, minimum=-MAX_PROGRESS_VALUE)
        if "travel_minutes_from_home" in location:
            _require_bounded_number(location["travel_minutes_from_home"], integer=True, minimum=0)
        _require_optional_container_fields(location, ("exits", "resources"), list)

    crop_plot = entity.get("crop_plot")
    if type(crop_plot) is dict:
        _require_optional_string_fields(
            crop_plot,
            (
                "crop_entity_id",
                "expected_yield",
                "harvest_status",
                "notes",
                "soil_status",
                "water_status",
            ),
        )
        if "area_sqm" in crop_plot:
            _require_bounded_number(crop_plot["area_sqm"], integer=False, minimum=0)
        for key in (
            "plot_no",
            "planted_day",
            "growth_stage",
            "growth_stage_max",
            "harvest_day_min",
            "harvest_day_max",
        ):
            if key in crop_plot:
                _require_bounded_number(crop_plot[key], integer=True, minimum=0)
        if (
            "growth_stage" in crop_plot
            and "growth_stage_max" in crop_plot
            and crop_plot["growth_stage"] > crop_plot["growth_stage_max"]
        ):
            raise ValueError(GENERIC_ERROR)
        if (
            "harvest_day_min" in crop_plot
            and "harvest_day_max" in crop_plot
            and crop_plot["harvest_day_min"] > crop_plot["harvest_day_max"]
        ):
            raise ValueError(GENERIC_ERROR)


def _require_bounded_number(value: Any, *, integer: bool, minimum: int) -> None:
    valid_type = type(value) is int if integer else type(value) in {int, float}
    if (
        not valid_type
        or value < minimum
        or value > MAX_PROGRESS_VALUE
        or (type(value) is float and not math.isfinite(value))
    ):
        raise ValueError(GENERIC_ERROR)


def _require_optional_string_fields(value: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in value and value[key] is not None and type(value[key]) is not str:
            raise ValueError(GENERIC_ERROR)


def _require_optional_container_fields(
    value: dict[str, Any],
    keys: tuple[str, ...],
    expected_type: type[dict] | type[list],
) -> None:
    for key in keys:
        if key in value and type(value[key]) is not expected_type:
            raise ValueError(GENERIC_ERROR)


def _require_exact_targets(candidate_targets: tuple[str, ...], targets: tuple[str, ...]) -> None:
    if not candidate_targets or len(set(candidate_targets)) != len(candidate_targets) or candidate_targets != targets:
        raise ValueError(GENERIC_ERROR)


def _validate_string_list(value: Any, *, prefix: str) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 32:
        raise ValueError(GENERIC_ERROR)
    result: list[str] = []
    for item in value:
        if type(item) is not str or not item.startswith(prefix) or item in result:
            raise ValueError(GENERIC_ERROR)
        result.append(item)
    return tuple(result)


def _safe_validation_messages(values: list[str]) -> list[str]:
    return list(_validate_safe_message_list(values[:32]))


def _validate_safe_message_list(value: Any) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 32:
        raise ValueError(GENERIC_ERROR)
    result: list[str] = []
    for item in value:
        if type(item) is not str or item not in SAFE_VALIDATION_CODES:
            raise ValueError(GENERIC_ERROR)
        if item not in result:
            result.append(item)
    return tuple(result)


def _canonical_control_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = unicodedata.normalize("NFD", text)
    return "".join(
        character
        for character in text
        if not (
            unicodedata.category(character).startswith("Z")
            or unicodedata.category(character).startswith("P")
            or unicodedata.category(character) == "Cf"
            or unicodedata.category(character).startswith("M")
        )
    )


def _validate_rollback_hint(value: dict[str, Any]) -> None:
    if not value:
        return
    allowed = {"strategy", "reference_ids"}
    if not set(value).issubset(allowed) or "strategy" not in value:
        raise ValueError(GENERIC_ERROR)
    _validate_candidate_keys(value)
    _validate_token(value["strategy"], ROLLBACK_STRATEGIES)
    if "reference_ids" in value:
        refs = value["reference_ids"]
        if type(refs) is not list or len(refs) > 16:
            raise ValueError(GENERIC_ERROR)
        seen: set[str] = set()
        for ref in refs:
            if (
                not _is_safe_rollback_reference_id(ref)
                or ref.split(":", 1)[0] not in SAFE_ROLLBACK_NAMESPACES
                or ref in seen
            ):
                raise ValueError(GENERIC_ERROR)
            seen.add(ref)


def _validate_supersedes(value: tuple[str, ...]) -> None:
    if any(
        not item.startswith(("advisory:", "advisory-review:")) or not _is_safe_reference_id(item)
        for item in value
    ):
        raise ValueError(GENERIC_ERROR)


def _operation_requires_base(family: str, operation: str) -> bool:
    return operation in {"update", "review", "tick"}


def _is_turn_id(value: Any) -> bool:
    return type(value) is str and TURN_ID_PATTERN.fullmatch(value) is not None


def _is_safe_reference_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) <= 256
        and SAFE_REFERENCE_ID_PATTERN.fullmatch(value) is not None
    )


def _is_safe_rollback_reference_id(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) <= 256
        and SAFE_ROLLBACK_REFERENCE_ID_PATTERN.fullmatch(value) is not None
    )


def _validate_base_turn(conn: sqlite3.Connection, base_turn_id: str | None, *, required: bool) -> None:
    if base_turn_id is None:
        if required:
            raise ValueError(GENERIC_ERROR)
        return
    if not _is_turn_id(base_turn_id):
        raise ValueError(GENERIC_ERROR)
    if conn.execute("select 1 from main.turns where id = ?", (base_turn_id,)).fetchone() is None:
        raise ValueError(GENERIC_ERROR)
    current_row = conn.execute(
        "select value from main.meta where key = 'current_turn_id'"
    ).fetchone()
    if current_row is None:
        raise ValueError(GENERIC_ERROR)
    current_turn_id = str(current_row["value"])
    current_order = _canonical_turn_order(current_turn_id)
    base_order = _canonical_turn_order(base_turn_id)
    if (
        current_order is None
        or base_order is None
        or conn.execute(
            "select 1 from main.turns where id = ?", (current_turn_id,)
        ).fetchone()
        is None
        or base_order > current_order
    ):
        raise ValueError(GENERIC_ERROR)


def _validate_source_freshness_binding(
    source: ResidentAIAdvisory,
    *,
    base_turn_id: str | None,
    required: bool,
) -> None:
    as_of = source.freshness.as_of_turn_id
    expected_base: str | None = None
    if as_of is not None:
        if type(as_of) is not int or as_of < 0 or as_of > 999_999:
            raise ValueError(GENERIC_ERROR)
        expected_base = "turn:seed" if as_of == 0 else f"turn:{as_of:06d}"
    if required and (expected_base is None or base_turn_id != expected_base):
        raise ValueError(GENERIC_ERROR)
    if base_turn_id is None and source.freshness.source_event_ids:
        raise ValueError(GENERIC_ERROR)
    if base_turn_id is not None and expected_base is not None and base_turn_id != expected_base:
        raise ValueError(GENERIC_ERROR)
    for evidence in source.evidence:
        evidence_as_of = evidence.as_of_turn_id
        if evidence_as_of != as_of:
            raise ValueError(GENERIC_ERROR)


def _source_base_turn_id(source: ResidentAIAdvisory) -> str | None:
    as_of = source.freshness.as_of_turn_id
    if as_of is None:
        return None
    if type(as_of) is not int or as_of < 0 or as_of > 999_999:
        raise ValueError(GENERIC_ERROR)
    return "turn:seed" if as_of == 0 else f"turn:{as_of:06d}"
