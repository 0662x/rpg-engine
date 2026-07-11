from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from typing import Any

from ..entity_access import read_entity
from ..progress_access import read_progress
from ..redaction import redact_player_hidden_material
from ..relationship_access import read_relationship
from ..visibility import normalize_visibility_label
from .schema_validation import validate_ai_output_schema


ADVISORY_SCHEMA = "resident_ai_advisory.schema.json"
ADVISORY_SCHEMA_VERSION = "resident_ai_advisory:v1"
MAX_STRUCTURE_DEPTH = 8
MAX_STRUCTURE_NODES = 512
MAX_CONTAINER_ITEMS = 64
MAX_STRING_LENGTH = 512
MAX_TOTAL_STRING_LENGTH = 32768
MAX_AS_OF_TURN_ID = 9_007_199_254_740_991
MAX_TARGET_IDS = 32
MAX_EVIDENCE_ITEMS = 64
MAX_SOURCE_IDS = 32

_FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "humanconfirmed",
        "playerconfirmed",
        "canconfirmplayers",
        "confirm",
        "approveproposal",
        "proposalapproved",
        "canapproveproposals",
        "approve",
        "hiddenaccess",
        "hiddenpermission",
        "canreadhidden",
        "hidden",
        "rawdelta",
        "deltadraft",
        "trusteddelta",
        "caninjecttrusteddelta",
        "saveauthorized",
        "saveauthorization",
        "canauthorizesave",
        "profileescalation",
        "canescalateprofile",
        "validationbypass",
        "canbypassvalidation",
        "privatereasoning",
        "chainofthought",
        "commit",
        "cancommit",
        "commitcapability",
        "commitauthority",
        "writefacts",
        "factwrite",
        "canwritefacts",
        "factwriteauthority",
        "writeauthority",
        "directwrite",
        "proposalapproval",
        "proposalapprovalauthority",
        "playerconfirmation",
        "confirmationauthority",
        "hiddenread",
        "hiddenreadauthority",
        "trusteddeltaauthority",
        "saveauthority",
        "saveauthorizationauthority",
        "profileescalationauthority",
        "validationbypassauthority",
        "authority",
        "approval",
        "confirmation",
    }
)
_SAFE_PATH_KEYS = frozenset(
    {
        "advisory_type",
        "target_ids",
        "evidence",
        "kind",
        "ref_id",
        "as_of_turn_id",
        "confidence",
        "freshness",
        "status",
        "source_event_ids",
        "visibility_mode",
        "source_assistant",
        "schema_version",
        "proposed_next_workflow",
        "provenance",
        "trace_id",
        "source_ids",
        "authority",
        "advisory_only",
        "no_direct_writes",
        "can_write_facts",
        "can_approve_proposals",
        "can_confirm_players",
        "can_read_hidden",
        "can_inject_trusted_delta",
        "can_authorize_save",
        "can_escalate_profile",
        "can_bypass_validation",
        "can_commit",
    }
)
_PLAYER_EVIDENCE_KINDS = frozenset({"entity", "relationship", "progress", "world_setting", "rule"})
_GENERIC_UNAVAILABLE = {
    "ok": False,
    "status": "unavailable",
    "advisory": True,
    "no_direct_writes": True,
}


@dataclass(frozen=True)
class AdvisoryEvidence:
    kind: str
    ref_id: str
    as_of_turn_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref_id": self.ref_id,
            "as_of_turn_id": self.as_of_turn_id,
        }


@dataclass(frozen=True)
class AdvisoryFreshness:
    status: str
    as_of_turn_id: int | None
    source_event_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of_turn_id": self.as_of_turn_id,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True)
class AdvisoryProvenance:
    trace_id: str
    source_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id, "source_ids": list(self.source_ids)}


@dataclass(frozen=True)
class AdvisoryAuthority:
    advisory_only: bool = True
    no_direct_writes: bool = True
    can_write_facts: bool = False
    can_approve_proposals: bool = False
    can_confirm_players: bool = False
    can_read_hidden: bool = False
    can_inject_trusted_delta: bool = False
    can_authorize_save: bool = False
    can_escalate_profile: bool = False
    can_bypass_validation: bool = False
    can_commit: bool = False

    def to_dict(self) -> dict[str, bool]:
        if not _is_canonical_authority(self):
            raise ValueError("$.authority: invalid advisory authority")
        return {
            "advisory_only": True,
            "no_direct_writes": True,
            "can_write_facts": False,
            "can_approve_proposals": False,
            "can_confirm_players": False,
            "can_read_hidden": False,
            "can_inject_trusted_delta": False,
            "can_authorize_save": False,
            "can_escalate_profile": False,
            "can_bypass_validation": False,
            "can_commit": False,
        }


@dataclass(frozen=True)
class ResidentAIAdvisory:
    advisory_type: str
    target_ids: tuple[str, ...]
    evidence: tuple[AdvisoryEvidence, ...]
    confidence: float
    freshness: AdvisoryFreshness
    visibility_mode: str
    source_assistant: str
    schema_version: str
    proposed_next_workflow: str
    provenance: AdvisoryProvenance
    authority: AdvisoryAuthority

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] | None = None
        normalized: ResidentAIAdvisory | None = None
        failure_message: str | None = None
        try:
            normalized = normalize_resident_ai_advisory(self._raw_dict())
            result = normalized._raw_dict()
        except ValueError as error:
            failure_message = str(error)
        except Exception:
            failure_message = "$: advisory serialization failed"
        self = None
        normalized = None
        if failure_message is not None:
            result = None
            raise ValueError(failure_message)
        if result is None:
            raise ValueError("$: advisory serialization failed")
        return result

    def _raw_dict(self) -> dict[str, Any]:
        advisory_type = self.advisory_type
        target_ids = self.target_ids
        evidence = self.evidence
        confidence = self.confidence
        freshness = self.freshness
        visibility_mode = self.visibility_mode
        source_assistant = self.source_assistant
        schema_version = self.schema_version
        proposed_next_workflow = self.proposed_next_workflow
        provenance = self.provenance
        authority = self.authority
        if type(target_ids) is not tuple or type(evidence) is not tuple:
            raise ValueError("$: advisory collections must be tuples")
        if type(freshness) is not AdvisoryFreshness:
            raise ValueError("$.freshness: invalid advisory freshness")
        freshness_status = freshness.status
        freshness_turn_id = freshness.as_of_turn_id
        source_event_ids = freshness.source_event_ids
        if type(source_event_ids) is not tuple:
            raise ValueError("$.freshness.source_event_ids: invalid advisory collection")
        if type(provenance) is not AdvisoryProvenance:
            raise ValueError("$.provenance: invalid advisory provenance")
        trace_id = provenance.trace_id
        source_ids = provenance.source_ids
        if type(source_ids) is not tuple:
            raise ValueError("$.provenance.source_ids: invalid advisory collection")
        if len(target_ids) > MAX_TARGET_IDS:
            raise ValueError("$.target_ids: advisory collection exceeds item budget")
        if len(evidence) > MAX_EVIDENCE_ITEMS:
            raise ValueError("$.evidence: advisory collection exceeds item budget")
        if len(source_event_ids) > MAX_SOURCE_IDS:
            raise ValueError("$.freshness.source_event_ids: advisory collection exceeds item budget")
        if len(source_ids) > MAX_SOURCE_IDS:
            raise ValueError("$.provenance.source_ids: advisory collection exceeds item budget")
        if not _is_canonical_authority(authority):
            raise ValueError("$.authority: invalid advisory authority")
        if not all(type(item) is AdvisoryEvidence for item in evidence):
            raise ValueError("$.evidence: invalid advisory evidence")
        return {
            "advisory_type": advisory_type,
            "target_ids": list(target_ids),
            "evidence": [item.to_dict() for item in evidence],
            "confidence": confidence,
            "freshness": {
                "status": freshness_status,
                "as_of_turn_id": freshness_turn_id,
                "source_event_ids": list(source_event_ids),
            },
            "visibility_mode": visibility_mode,
            "source_assistant": source_assistant,
            "schema_version": schema_version,
            "proposed_next_workflow": proposed_next_workflow,
            "provenance": {"trace_id": trace_id, "source_ids": list(source_ids)},
            "authority": authority.to_dict(),
        }


def normalize_resident_ai_advisory(value: Any) -> ResidentAIAdvisory:
    failure_message: str | None = None
    try:
        return _normalize_resident_ai_advisory(value)
    except ValueError as error:
        failure_message = str(error)
    except Exception:
        failure_message = "$: advisory normalization failed"
    value = None
    raise ValueError(failure_message)


def _normalize_resident_ai_advisory(value: Any) -> ResidentAIAdvisory:
    _validate_json_structure(value)
    snapshot_failed = False
    try:
        value = _copy_json_value(value)
    except Exception:
        snapshot_failed = True
    if snapshot_failed:
        raise ValueError("$: advisory snapshot failed")
    _validate_json_structure(value)
    _reject_authority_smuggling(value)
    if not isinstance(value, dict):
        raise ValueError("$: expected object")
    schema_validation_failed = False
    try:
        errors = validate_ai_output_schema(ADVISORY_SCHEMA, value)
    except Exception:
        schema_validation_failed = True
    if schema_validation_failed:
        raise ValueError("$: advisory schema validation failed")
    if errors:
        raise ValueError(_redacted_schema_error(errors[0]))
    _reject_integral_float_turn_ids(value)
    _reject_duplicates(value)

    freshness = value["freshness"]
    provenance = value["provenance"]
    return ResidentAIAdvisory(
        advisory_type=value["advisory_type"],
        target_ids=tuple(value["target_ids"]),
        evidence=tuple(
            AdvisoryEvidence(
                kind=item["kind"],
                ref_id=item["ref_id"],
                as_of_turn_id=item["as_of_turn_id"],
            )
            for item in value["evidence"]
        ),
        confidence=float(value["confidence"]),
        freshness=AdvisoryFreshness(
            status=freshness["status"],
            as_of_turn_id=freshness["as_of_turn_id"],
            source_event_ids=tuple(freshness["source_event_ids"]),
        ),
        visibility_mode=value["visibility_mode"],
        source_assistant=value["source_assistant"],
        schema_version=value["schema_version"],
        proposed_next_workflow=value["proposed_next_workflow"],
        provenance=AdvisoryProvenance(
            trace_id=provenance["trace_id"],
            source_ids=tuple(provenance["source_ids"]),
        ),
        authority=AdvisoryAuthority(),
    )


def resident_ai_advisory_to_maintenance_dict(envelope: ResidentAIAdvisory) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    failure_type: type[Exception] | None = None
    failure_message: str | None = None
    try:
        if type(envelope) is not ResidentAIAdvisory:
            raise TypeError("envelope must be ResidentAIAdvisory")
        result = envelope.to_dict()
    except TypeError as error:
        failure_type = TypeError
        failure_message = str(error)
    except ValueError as error:
        failure_type = ValueError
        failure_message = str(error)
    except Exception:
        failure_type = ValueError
        failure_message = "$: advisory serialization failed"
    envelope = None
    if failure_type is not None:
        raise failure_type(failure_message)
    if result is None:
        raise ValueError("$: advisory serialization failed")
    return result


def resident_ai_advisory_to_player_dict(
    envelope: ResidentAIAdvisory,
    conn: sqlite3.Connection | None,
) -> dict[str, Any]:
    if type(envelope) is not ResidentAIAdvisory:
        return dict(_GENERIC_UNAVAILABLE)
    if not isinstance(conn, sqlite3.Connection):
        return dict(_GENERIC_UNAVAILABLE)
    try:
        if _connection_lacks_authoritative_schema_or_has_shadow(conn):
            return dict(_GENERIC_UNAVAILABLE)
        canonical = envelope.to_dict()
        if canonical["visibility_mode"] != "player":
            return dict(_GENERIC_UNAVAILABLE)
        target_ids = [
            target_id for target_id in canonical["target_ids"] if _player_visible_target(conn, target_id)
        ]
        canonical_evidence = [
            AdvisoryEvidence(item["kind"], item["ref_id"], item["as_of_turn_id"])
            for item in canonical["evidence"]
        ]
        evidence = [item for item in canonical_evidence if _player_visible_evidence(conn, item)]
        if not target_ids and not evidence:
            return dict(_GENERIC_UNAVAILABLE)
        result: dict[str, Any] = {
            "ok": True,
            "status": "available",
            "advisory": True,
            "no_direct_writes": True,
            "target_ids": target_ids,
            "evidence": [{"kind": item.kind, "ref_id": item.ref_id} for item in evidence],
            "schema_version": canonical["schema_version"],
            "authority": canonical["authority"],
        }
        if not _valid_player_projection(result):
            return dict(_GENERIC_UNAVAILABLE)
        dynamic_refs = [*target_ids, *(item["ref_id"] for item in result["evidence"])]
        expected_refs_wire = _wire_json(dynamic_refs)
        redacted_refs = redact_player_hidden_material(
            conn,
            dynamic_refs,
            drop_empty=False,
            structured_reference_ids=True,
        )
        if (
            type(redacted_refs) is not list
            or not all(type(item) is str for item in redacted_refs)
            or expected_refs_wire is None
            or _wire_json(redacted_refs) != expected_refs_wire
        ):
            return dict(_GENERIC_UNAVAILABLE)
        if any(not _player_visible_target(conn, target_id) for target_id in target_ids):
            return dict(_GENERIC_UNAVAILABLE)
        if any(not _player_visible_evidence(conn, item) for item in evidence):
            return dict(_GENERIC_UNAVAILABLE)
        if _connection_lacks_authoritative_schema_or_has_shadow(conn):
            return dict(_GENERIC_UNAVAILABLE)
        return result
    except Exception:
        return dict(_GENERIC_UNAVAILABLE)


def _connection_lacks_authoritative_schema_or_has_shadow(conn: sqlite3.Connection) -> bool:
    authoritative_tables = conn.execute(
        """
        select count(*)
        from main.sqlite_master
        where type = 'table'
          and lower(name) in ('entities', 'clocks')
        """
    ).fetchone()
    if authoritative_tables is None or int(authoritative_tables[0]) != 2:
        return True
    shadow = conn.execute(
        """
        select 1
        from sqlite_temp_master
        where type in ('table', 'view')
          and lower(name) in ('entities', 'clocks', 'world_settings')
        limit 1
        """
    ).fetchone()
    return shadow is not None


def _player_visible_target(conn: sqlite3.Connection, target_id: str) -> bool:
    try:
        record = read_entity(conn, target_id, view="player")
        if record is None:
            return False
        record_type = normalize_visibility_label(record.type)
        if target_id.startswith("rel:"):
            return read_relationship(conn, target_id, view="player") is not None
        if target_id.startswith("clock:"):
            return read_progress(conn, target_id, view="player") is not None
        if target_id.startswith("rule:"):
            return record_type == "rule"
        if target_id.startswith(("world:", "setting:")):
            return record_type == "world_setting"
        if record_type == "relationship":
            return read_relationship(conn, target_id, view="player") is not None
        if record_type == "clock":
            return read_progress(conn, target_id, view="player") is not None
        return True
    except Exception:
        return False


def _player_visible_evidence(conn: sqlite3.Connection, item: AdvisoryEvidence) -> bool:
    try:
        if item.kind not in _PLAYER_EVIDENCE_KINDS:
            return False
        if item.kind == "relationship":
            return read_relationship(conn, item.ref_id, view="player") is not None
        if item.kind == "progress":
            return read_progress(conn, item.ref_id, view="player") is not None
        record = read_entity(conn, item.ref_id, view="player")
        if record is None:
            return False
        record_type = normalize_visibility_label(record.type)
        if item.kind == "entity":
            if item.ref_id.startswith("rel:"):
                return read_relationship(conn, item.ref_id, view="player") is not None
            if item.ref_id.startswith("clock:"):
                return read_progress(conn, item.ref_id, view="player") is not None
            if item.ref_id.startswith("rule:"):
                return record_type == "rule"
            if item.ref_id.startswith(("world:", "setting:")):
                return record_type == "world_setting"
            if record_type == "relationship":
                return read_relationship(conn, item.ref_id, view="player") is not None
            if record_type == "clock":
                return read_progress(conn, item.ref_id, view="player") is not None
        if item.kind == "world_setting":
            return record_type == "world_setting"
        if item.kind == "rule":
            return record_type == "rule"
        return True
    except Exception:
        return False


def _valid_player_projection(value: Any) -> bool:
    expected_keys = {
        "ok",
        "status",
        "advisory",
        "no_direct_writes",
        "target_ids",
        "evidence",
        "schema_version",
        "authority",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        return False
    if value.get("ok") is not True or value.get("status") != "available":
        return False
    if value.get("advisory") is not True or value.get("no_direct_writes") is not True:
        return False
    if value.get("schema_version") != ADVISORY_SCHEMA_VERSION:
        return False
    authority = value.get("authority")
    expected_authority = AdvisoryAuthority().to_dict()
    if type(authority) is not dict or set(authority) != set(expected_authority):
        return False
    if any(type(authority[key]) is not bool or authority[key] is not expected for key, expected in expected_authority.items()):
        return False
    target_ids = value.get("target_ids")
    evidence = value.get("evidence")
    if type(target_ids) is not list or not all(type(item) is str for item in target_ids):
        return False
    if type(evidence) is not list:
        return False
    for item in evidence:
        if type(item) is not dict or set(item) != {"kind", "ref_id"}:
            return False
        if item["kind"] not in _PLAYER_EVIDENCE_KINDS or type(item["ref_id"]) is not str:
            return False
    return bool(target_ids or evidence)


def _wire_json(value: Any) -> str | None:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None


def _validate_json_structure(value: Any) -> None:
    state = {"nodes": 0, "strings": 0}
    failure_message: str | None = None
    try:
        _walk_json_structure(value, path="$", depth=0, active=set(), state=state)
    except RecursionError:
        failure_message = "$: structure exceeds safe depth"
    except ValueError:
        raise
    except Exception:
        failure_message = "$: structure traversal failed"
    if failure_message is not None:
        raise ValueError(failure_message)


def _walk_json_structure(
    value: Any,
    *,
    path: str,
    depth: int,
    active: set[int],
    state: dict[str, int],
) -> None:
    state["nodes"] += 1
    if state["nodes"] > MAX_STRUCTURE_NODES:
        raise ValueError(f"{path}: structure exceeds node budget")
    if depth > MAX_STRUCTURE_DEPTH:
        raise ValueError(f"{path}: structure exceeds safe depth")
    if type(value) is str:
        _count_string(value, path=path, state=state)
        return
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > MAX_AS_OF_TURN_ID:
            raise ValueError(f"{path}: integer exceeds safe range")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path}: number must be finite")
        return
    if type(value) not in (dict, list):
        raise ValueError(f"{path}: expected JSON value")
    identity = id(value)
    if identity in active:
        raise ValueError(f"{path}: cyclic structure")
    if len(value) > MAX_CONTAINER_ITEMS:
        raise ValueError(f"{path}: container exceeds item budget")
    active.add(identity)
    try:
        if isinstance(value, dict):
            for key, item in value.items():
                if type(key) is not str:
                    raise ValueError(f"{path}: object keys must be strings")
                _count_string(key, path=path, state=state)
                _walk_json_structure(
                    item,
                    path=_object_path(path, key),
                    depth=depth + 1,
                    active=active,
                    state=state,
                )
        else:
            for index, item in enumerate(value):
                _walk_json_structure(
                    item,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    active=active,
                    state=state,
                )
    finally:
        active.remove(identity)


def _count_string(value: str, *, path: str, state: dict[str, int]) -> None:
    if len(value) > MAX_STRING_LENGTH:
        raise ValueError(f"{path}: string exceeds length budget")
    state["strings"] += len(value)
    if state["strings"] > MAX_TOTAL_STRING_LENGTH:
        raise ValueError(f"{path}: structure exceeds string budget")


def _copy_json_value(value: Any) -> Any:
    return _copy_json_node(value, path="$", depth=0, active=set(), state={"nodes": 0, "strings": 0})


def _copy_json_node(
    value: Any,
    *,
    path: str,
    depth: int,
    active: set[int],
    state: dict[str, int],
) -> Any:
    state["nodes"] += 1
    if state["nodes"] > MAX_STRUCTURE_NODES:
        raise ValueError(f"{path}: structure exceeds node budget")
    if depth > MAX_STRUCTURE_DEPTH:
        raise ValueError(f"{path}: structure exceeds safe depth")
    if type(value) is str:
        _count_string(value, path=path, state=state)
        return value
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if abs(value) > MAX_AS_OF_TURN_ID:
            raise ValueError(f"{path}: integer exceeds safe range")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path}: number must be finite")
        return value
    if type(value) not in (dict, list):
        raise ValueError(f"{path}: expected JSON value")
    identity = id(value)
    if identity in active:
        raise ValueError(f"{path}: cyclic structure")
    active.add(identity)
    try:
        if type(value) is list:
            items = value[: MAX_CONTAINER_ITEMS + 1]
            if len(items) > MAX_CONTAINER_ITEMS:
                raise ValueError(f"{path}: container exceeds item budget")
            return [
                _copy_json_node(
                    item,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    active=active,
                    state=state,
                )
                for index, item in enumerate(items)
            ]
        copied: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_CONTAINER_ITEMS:
                raise ValueError(f"{path}: container exceeds item budget")
            if type(key) is not str:
                raise ValueError(f"{path}: object keys must be strings")
            _count_string(key, path=path, state=state)
            copied[key] = _copy_json_node(
                item,
                path=_object_path(path, key),
                depth=depth + 1,
                active=active,
                state=state,
            )
        return copied
    finally:
        active.remove(identity)


def _reject_authority_smuggling(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if path == "$" and key == "authority":
                _reject_authority_smuggling(item, path="$.authority")
                continue
            if path == "$.authority":
                expected = AdvisoryAuthority().to_dict()
                if key in expected and item is expected[key]:
                    continue
            if _canonical_key(key) in _FORBIDDEN_AUTHORITY_KEYS:
                raise ValueError(f"{_object_path(path, key)}: forbidden authority field")
            _reject_authority_smuggling(item, path=_object_path(path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_authority_smuggling(item, path=f"{path}[{index}]")


def _canonical_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = unicodedata.normalize("NFD", text)
    return "".join(
        char
        for char in text
        if not (
            unicodedata.category(char).startswith("Z")
            or unicodedata.category(char).startswith("P")
            or unicodedata.category(char) == "Cf"
            or unicodedata.category(char).startswith("M")
        )
    )


def _reject_duplicates(value: dict[str, Any]) -> None:
    _require_unique(value["target_ids"], path="$.target_ids")
    _require_unique(value["freshness"]["source_event_ids"], path="$.freshness.source_event_ids")
    _require_unique(value["provenance"]["source_ids"], path="$.provenance.source_ids")
    evidence_keys = [(item["ref_id"], item["as_of_turn_id"]) for item in value["evidence"]]
    _require_unique(evidence_keys, path="$.evidence")


def _reject_integral_float_turn_ids(value: dict[str, Any]) -> None:
    freshness_turn = value["freshness"]["as_of_turn_id"]
    if freshness_turn is not None and type(freshness_turn) is not int:
        raise ValueError("$.freshness.as_of_turn_id: expected integer")
    for index, item in enumerate(value["evidence"]):
        turn_id = item["as_of_turn_id"]
        if turn_id is not None and type(turn_id) is not int:
            raise ValueError(f"$.evidence[{index}].as_of_turn_id: expected integer")


def _require_unique(values: list[Any], *, path: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{path}: duplicate items are not allowed")


def _object_path(path: str, key: str) -> str:
    if key in _SAFE_PATH_KEYS:
        return f"{path}.{key}"
    return f"{path}[*]"


def _redacted_schema_error(error: str) -> str:
    candidate = error.partition(":")[0].strip()
    return f"{_safe_error_path(candidate)}: invalid advisory envelope"


def _safe_error_path(path: str) -> str:
    if not path.startswith("$"):
        return "$"
    suffix = path[1:]
    tokens = re.findall(r"\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\]", suffix)
    if "".join(tokens) != suffix:
        return "$"
    for token in tokens:
        if token.startswith(".") and token[1:] not in _SAFE_PATH_KEYS:
            return "$[*]"
    return path


def _is_canonical_authority(value: Any) -> bool:
    if type(value) is not AdvisoryAuthority:
        return False
    expected = {
        "advisory_only": True,
        "no_direct_writes": True,
        "can_write_facts": False,
        "can_approve_proposals": False,
        "can_confirm_players": False,
        "can_read_hidden": False,
        "can_inject_trusted_delta": False,
        "can_authorize_save": False,
        "can_escalate_profile": False,
        "can_bypass_validation": False,
        "can_commit": False,
    }
    return all(type(getattr(value, key)) is bool and getattr(value, key) is item for key, item in expected.items())
