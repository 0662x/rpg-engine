from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from weakref import WeakSet

from .actions import ActionResolverRegistry, get_default_action_registry
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS
from .ai.advisory import (
    MAX_CONTAINER_ITEMS,
    ResidentAIAdvisory,
    normalize_resident_ai_advisory,
    resident_ai_advisory_to_maintenance_dict,
)
from .ai.advisory_adapters import (
    adapt_state_audit_progress_advisory,
    matches_state_audit_progress_projection,
)
from .ai.state_audit import run_state_audit, should_block_state_audit
from .campaign import Campaign
from .capabilities import ACTION_CAPABILITIES, CAPABILITY_INTENTS, capability_for_action
from .delta_draft import check_delta_response_consistency
from .delta_schema import validate_delta_schema
from .proposal import TurnProposal, validate_turn_proposal
from .response_lint import lint_response
from .visibility import normalize_visibility_label


VALIDATION_PROFILES = {
    "preview_only",
    "player_turn_commit",
    "response_acceptance",
    "maintenance_commit",
    "admin_or_legacy_save_turn",
    "import_or_migration",
}

COMMIT_ALLOWED_PROFILES = {
    "player_turn_commit",
    "response_acceptance",
    "maintenance_commit",
    "admin_or_legacy_save_turn",
    "import_or_migration",
}

MAINTENANCE_ADVISORY_PROFILES = frozenset({
    "maintenance_commit",
    "admin_or_legacy_save_turn",
    "import_or_migration",
})


@dataclass(frozen=True, eq=False)
class _ValidatedDeltaProof:
    delta_digest: str
    clock_ids: tuple[str, ...] | None
    canonical_delta_json: str = field(repr=False)
    connection: sqlite3.Connection = field(repr=False)


_MINTED_DELTA_PROOFS: WeakSet[_ValidatedDeltaProof] = WeakSet()


@dataclass(frozen=True)
class ValidationStageResult:
    name: str
    profile: str
    status: str
    issues: tuple[str, ...] = ()
    skipped_reason: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    _validated_delta_proof: _ValidatedDeltaProof | None = field(default=None, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return self.status != "blocked"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "profile": self.profile,
            "status": self.status,
            "issues": list(self.issues),
            "skipped_reason": self.skipped_reason,
            "artifacts": self.artifacts,
        }


@dataclass(frozen=True)
class ValidationReport:
    profile: str
    stages: tuple[ValidationStageResult, ...]
    proposal_id: str | None = None
    delta_source: str | None = None
    delta_digest: str | None = None

    @property
    def ok(self) -> bool:
        return all(stage.ok for stage in self.stages)

    @property
    def status(self) -> str:
        if any(stage.status == "blocked" for stage in self.stages):
            return "blocked"
        if any(stage.status == "warning" for stage in self.stages):
            return "warning"
        return "ok"

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(issue for stage in self.stages if stage.status == "blocked" for issue in stage.issues)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(issue for stage in self.stages if stage.status == "warning" for issue in stage.issues)

    @property
    def state_audit(self) -> dict[str, Any] | None:
        for stage in self.stages:
            if stage.name == "state_audit":
                audit = stage.artifacts.get("audit")
                return audit if isinstance(audit, dict) else None
        return None

    def stage(self, name: str) -> ValidationStageResult | None:
        for stage in self.stages:
            if stage.name == name:
                return stage
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "status": self.status,
            "ok": self.ok,
            "proposal_id": self.proposal_id,
            "delta_source": self.delta_source,
            "delta_digest": self.delta_digest,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "stages": [stage.to_dict() for stage in self.stages],
        }

    def render(self) -> str:
        lines = [
            "# Validation Report",
            "",
            f"- profile: `{self.profile}`",
            f"- status: `{self.status}`",
            f"- ok: `{'yes' if self.ok else 'no'}`",
        ]
        if self.proposal_id:
            lines.append(f"- proposal_id: `{self.proposal_id}`")
        if self.delta_source:
            lines.append(f"- delta_source: `{self.delta_source}`")
        if self.delta_digest:
            lines.append(f"- delta_digest: `{self.delta_digest}`")
        lines.extend(["", "## Stages", ""])
        for stage in self.stages:
            lines.append(f"- `{stage.name}`: `{stage.status}`")
            if stage.skipped_reason:
                lines.append(f"  - skipped: {stage.skipped_reason}")
            for issue in stage.issues:
                lines.append(f"  - {issue}")
        return "\n".join(lines).rstrip() + "\n"


def run_validation_pipeline(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    profile: str,
    delta: dict[str, Any] | None = None,
    proposal: TurnProposal | None = None,
    response_text: str | None = None,
    action: str | None = None,
    action_options: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    state_audit: bool = False,
    state_audit_ai: str = "off",
    state_audit_provider: str = DEFAULT_AI_PROVIDER,
    state_audit_model: str = DEFAULT_AI_MODEL,
    state_audit_timeout: int = DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
    state_audit_block: bool = True,
    response_lint_strict: bool = True,
    registry: ActionResolverRegistry | None = None,
) -> ValidationReport:
    if proposal is not None and delta is None:
        delta = proposal.delta
    action_registry = registry if registry is not None else get_default_action_registry()
    effective_action = action or (
        proposal.intent.action
        if proposal
        else action_from_delta(delta or {}, registry=action_registry)
    )
    effective_options = effective_action_options(effective_action, delta or {}, proposal, action_options)
    stages: list[ValidationStageResult] = []

    stages.append(validate_profile_stage(profile))
    stages.append(validate_write_guard_stage(profile, delta=delta))
    stages.append(
        validate_proposal_stage(
            campaign,
            conn,
            profile,
            proposal,
            response_text=response_text,
            registry=action_registry,
        )
    )
    stages.append(validate_delta_schema_stage(conn, profile, delta))
    stages.append(validate_capability_stage(campaign, profile, delta, effective_action))
    stages.append(
        validate_resolver_request_stage(
            campaign,
            conn,
            profile,
            action=effective_action,
            action_options=effective_options,
            context=context or {},
            registry=action_registry,
        )
    )
    stages.append(
        validate_resolver_resolution_stage(
            campaign,
            conn,
            profile,
            action=effective_action,
            action_options=effective_options,
            context=context or {},
            registry=action_registry,
        )
    )
    stages.append(
        validate_resolver_contract_stage(
            campaign,
            conn,
            profile,
            delta,
            action=effective_action,
            action_options=effective_options,
            context=context or {},
            registry=action_registry,
        )
    )
    stages.append(
        validate_response_lint_stage(
            profile,
            proposal,
            response_text,
            strict=response_lint_strict,
            registry=action_registry,
        )
    )
    stages.append(validate_response_consistency_stage(profile, delta, response_text))
    stages.append(
        validate_state_audit_stage(
            conn,
            profile,
            delta,
            state_audit=state_audit,
            state_audit_ai=state_audit_ai,
            state_audit_provider=state_audit_provider,
            state_audit_model=state_audit_model,
            state_audit_timeout=state_audit_timeout,
            state_audit_block=state_audit_block,
            action=effective_action,
            action_options=effective_options,
            context=context or {},
            stages=tuple(stages),
        )
    )

    return ValidationReport(
        profile=profile,
        stages=tuple(stages),
        proposal_id=proposal.proposal_id if proposal else None,
        delta_source=proposal.delta_source if proposal else None,
        delta_digest=stable_delta_digest(delta),
    )


def stable_delta_digest(delta: dict[str, Any] | None) -> str | None:
    if delta is None:
        return None
    payload = _canonical_delta_json(delta)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload is not None else None


def _canonical_delta_json(delta: Any) -> str | None:
    try:
        _require_exact_json_value(delta)
        payload = json.dumps(
            delta,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload.encode("utf-8")
        return payload
    except Exception:
        return None


def _require_exact_json_value(value: Any) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("delta mapping keys must be exact strings")
            _require_exact_json_value(item)
        return
    if type(value) is list:
        for item in value:
            _require_exact_json_value(item)
        return
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float and math.isfinite(value):
        return
    raise ValueError("delta contains a non-canonical JSON value")


def validate_profile_stage(profile: str) -> ValidationStageResult:
    if profile not in VALIDATION_PROFILES:
        return blocked("profile", profile, f"unsupported validation profile: {profile}")
    return ok("profile", profile, artifacts={"allowed_commit": profile in COMMIT_ALLOWED_PROFILES})


def validate_write_guard_stage(profile: str, *, delta: dict[str, Any] | None) -> ValidationStageResult:
    if profile == "preview_only" and delta is not None:
        return blocked("write_guard", profile, "preview_only profile cannot approve a commit delta")
    if profile == "player_turn_commit" and delta is not None:
        missing = [key for key in ("expected_turn_id", "command_id") if not delta.get(key)]
        if missing:
            return blocked("write_guard", profile, "player_turn_commit requires " + ", ".join(missing))
    if profile == "admin_or_legacy_save_turn":
        return warning(
            "write_guard",
            profile,
            "admin_or_legacy_save_turn is not the ordinary player commit path",
        )
    return ok("write_guard", profile)


def validate_proposal_stage(
    campaign: Campaign,
    conn: sqlite3.Connection,
    profile: str,
    proposal: TurnProposal | None,
    *,
    response_text: str | None,
    registry: ActionResolverRegistry,
) -> ValidationStageResult:
    if proposal is None:
        if profile == "player_turn_commit":
            return skipped("proposal_guard", profile, "validation-only delta path without proposal")
        return skipped("proposal_guard", profile, "profile does not require a TurnProposal")
    outcome = validate_turn_proposal(
        campaign,
        conn,
        proposal,
        response_text=response_text,
        registry=registry,
    )
    artifacts = {
        "proposal_status": outcome.status,
        "delta_source": proposal.delta_source,
        "human_confirmed": proposal.human_confirmed,
    }
    issues = tuple(dict.fromkeys([*outcome.errors, *outcome.confirmations]))
    if outcome.ok:
        status = "warning" if outcome.warnings else "ok"
        return ValidationStageResult(
            name="proposal_guard",
            profile=profile,
            status=status,
            issues=tuple(outcome.warnings),
            artifacts=artifacts,
        )
    return ValidationStageResult(
        name="proposal_guard",
        profile=profile,
        status="blocked",
        issues=issues or (f"proposal status is {outcome.status}",),
        artifacts=artifacts,
    )


def validate_delta_schema_stage(
    conn: sqlite3.Connection,
    profile: str,
    delta: dict[str, Any] | None,
) -> ValidationStageResult:
    if delta is None:
        return skipped("delta_schema", profile, "no delta provided")
    caller_view = "player" if profile in {"player_turn_commit", "response_acceptance"} else "maintenance"
    try:
        validated_delta = deepcopy(delta)
    except Exception:
        return blocked("delta_schema", profile, "$: delta snapshot failed")
    source_wire = _canonical_delta_json(delta)
    validated_wire = _canonical_delta_json(validated_delta)
    if source_wire is None or validated_wire is None or source_wire != validated_wire:
        return blocked("delta_schema", profile, "$: delta snapshot mismatch")
    errors = tuple(validate_delta_schema(validated_delta, conn, caller_view=caller_view))
    artifacts = {"caller_view": caller_view}
    if errors:
        return ValidationStageResult("delta_schema", profile, "blocked", issues=errors, artifacts=artifacts)
    validated_digest = hashlib.sha256(validated_wire.encode("utf-8")).hexdigest()
    proof = _ValidatedDeltaProof(
        validated_digest,
        _validated_clock_ids(validated_delta),
        validated_wire,
        conn,
    )
    _MINTED_DELTA_PROOFS.add(proof)
    return ValidationStageResult(
        "delta_schema",
        profile,
        "ok",
        artifacts=artifacts,
        _validated_delta_proof=proof,
    )


def validate_capability_stage(
    campaign: Campaign,
    profile: str,
    delta: dict[str, Any] | None,
    action: str | None,
) -> ValidationStageResult:
    required = required_capabilities(delta or {}, action)
    if not required:
        return skipped("capability_check", profile, "no gameplay capability required")
    declared = declared_capabilities(campaign)
    missing = tuple(f"unsupported capability: {item}" for item in sorted(required) if item not in declared)
    if missing:
        return ValidationStageResult("capability_check", profile, "blocked", issues=missing)
    return ok("capability_check", profile, artifacts={"required": sorted(required)})


def validate_resolver_contract_stage(
    campaign: Campaign,
    conn: sqlite3.Connection,
    profile: str,
    delta: dict[str, Any] | None,
    *,
    action: str | None,
    action_options: dict[str, Any],
    context: dict[str, Any],
    registry: ActionResolverRegistry,
) -> ValidationStageResult:
    if delta is None:
        return skipped("resolver_delta_contract", profile, "no delta provided")
    if not action:
        if profile == "admin_or_legacy_save_turn":
            return warning(
                "resolver_delta_contract",
                profile,
                "action resolver contract skipped because admin/legacy save did not provide an action",
            )
        return skipped("resolver_delta_contract", profile, "no action could be inferred")
    resolver = registry.get(action)
    if resolver is None:
        return blocked("resolver_delta_contract", profile, f"unsupported action: {action}")
    result = resolver.delta_contract(campaign, conn, context, SimpleNamespace(**action_options), delta)
    issues = tuple([*result.errors, *(f"missing: {item}" for item in result.missing_required)])
    if issues:
        return ValidationStageResult("resolver_delta_contract", profile, "blocked", issues=issues)
    if result.warnings:
        return ValidationStageResult("resolver_delta_contract", profile, "warning", issues=tuple(result.warnings))
    return ok("resolver_delta_contract", profile)


def validate_resolver_request_stage(
    campaign: Campaign,
    conn: sqlite3.Connection,
    profile: str,
    *,
    action: str | None,
    action_options: dict[str, Any],
    context: dict[str, Any],
    registry: ActionResolverRegistry,
) -> ValidationStageResult:
    if not action:
        return skipped("resolver_request_contract", profile, "no action could be inferred")
    resolver = registry.get(action)
    if resolver is None:
        return blocked("resolver_request_contract", profile, f"unsupported action: {action}")
    result = resolver.request_contract(campaign, conn, context, SimpleNamespace(**action_options))
    issues = tuple([*result.errors, *(f"missing: {item}" for item in result.missing_required)])
    if issues:
        return ValidationStageResult("resolver_request_contract", profile, "blocked", issues=issues)
    if result.warnings:
        return ValidationStageResult("resolver_request_contract", profile, "warning", issues=tuple(result.warnings))
    return ok("resolver_request_contract", profile)


def validate_resolver_resolution_stage(
    campaign: Campaign,
    conn: sqlite3.Connection,
    profile: str,
    *,
    action: str | None,
    action_options: dict[str, Any],
    context: dict[str, Any],
    registry: ActionResolverRegistry,
) -> ValidationStageResult:
    if not action:
        return skipped("resolver_resolve_contract", profile, "no action could be inferred")
    resolver = registry.get(action)
    if resolver is None:
        return blocked("resolver_resolve_contract", profile, f"unsupported action: {action}")
    result = resolver.resolve_contract(campaign, conn, context, SimpleNamespace(**action_options))
    artifacts = {
        "resolver_status": result.status,
        "facts_used": list(result.facts_used),
        "rules_applied": list(result.rules_applied),
    }
    if result.status == "blocked":
        issues = tuple(result.warnings or result.confirmations or ("resolver status is blocked",))
        return ValidationStageResult("resolver_resolve_contract", profile, "blocked", issues=issues, artifacts=artifacts)
    if result.status != "ready":
        issues = tuple(result.confirmations or result.warnings or (f"resolver status is {result.status}",))
        return ValidationStageResult("resolver_resolve_contract", profile, "warning", issues=issues, artifacts=artifacts)
    if result.warnings:
        return ValidationStageResult("resolver_resolve_contract", profile, "warning", issues=tuple(result.warnings), artifacts=artifacts)
    return ok("resolver_resolve_contract", profile, artifacts=artifacts)


def validate_response_lint_stage(
    profile: str,
    proposal: TurnProposal | None,
    response_text: str | None,
    *,
    strict: bool,
    registry: ActionResolverRegistry,
) -> ValidationStageResult:
    if not response_text:
        return skipped("response_lint", profile, "no response text provided")
    if proposal is None or proposal.turn_contract is None:
        return skipped("response_lint", profile, "no TurnContract available")
    result = lint_response(
        response_text,
        turn_contract=proposal.turn_contract,
        strict=strict,
        registry=registry,
    )
    if result.errors:
        return ValidationStageResult("response_lint", profile, "blocked", issues=tuple(result.errors))
    if result.warnings:
        return ValidationStageResult("response_lint", profile, "warning", issues=tuple(result.warnings))
    return ok("response_lint", profile)


def validate_response_consistency_stage(
    profile: str,
    delta: dict[str, Any] | None,
    response_text: str | None,
) -> ValidationStageResult:
    if not response_text or delta is None:
        return skipped("response_delta_consistency", profile, "response text or delta not provided")
    warnings = tuple(check_delta_response_consistency(delta, response_text))
    if not warnings:
        return ok("response_delta_consistency", profile)
    status = "blocked" if profile == "response_acceptance" else "warning"
    return ValidationStageResult("response_delta_consistency", profile, status, issues=warnings)


def validate_state_audit_stage(
    conn: sqlite3.Connection,
    profile: str,
    delta: dict[str, Any] | None,
    *,
    state_audit: bool,
    state_audit_ai: str,
    state_audit_provider: str,
    state_audit_model: str,
    state_audit_timeout: int,
    state_audit_block: bool,
    action: str | None,
    action_options: dict[str, Any],
    context: dict[str, Any],
    stages: tuple[ValidationStageResult, ...],
) -> ValidationStageResult:
    if delta is None:
        return skipped("state_audit", profile, "no delta provided")
    if not state_audit and state_audit_ai == "off":
        return skipped("state_audit", profile, "state audit was not requested")
    partial_report = {
        "ok": all(stage.ok for stage in stages),
        "errors": [issue for stage in stages if stage.status == "blocked" for issue in stage.issues],
        "warnings": [issue for stage in stages if stage.status == "warning" for issue in stage.issues],
    }
    advisory_snapshot = _state_audit_progress_snapshot(
        conn=conn,
        profile=profile,
        delta=delta,
        stages=stages,
    )
    try:
        audit_delta = deepcopy(delta)
    except Exception:
        audit_delta = {}
    if advisory_snapshot is not None:
        audit_delta = advisory_snapshot.audit_delta
    audit = run_state_audit(
        conn,
        delta=audit_delta,
        validation_result=partial_report,
        action=action,
        action_options=action_options,
        context=context,
        ai=state_audit_ai,
        provider=state_audit_provider,
        model=state_audit_model,
        timeout=state_audit_timeout,
    )
    try:
        audit_artifact = deepcopy(audit.to_dict())
        advisory_audit: Any = deepcopy(audit)
    except Exception:
        audit_artifact = audit.to_dict()
        advisory_audit = None
    artifacts = {"audit": audit_artifact}
    if advisory_snapshot is not None and (
        not _state_audit_snapshot_is_current(advisory_snapshot, delta)
        or not _state_audit_snapshot_is_current(advisory_snapshot, audit_delta)
    ):
        advisory_snapshot = None
    if advisory_snapshot is not None and not _clock_ids_live(conn, advisory_snapshot.clock_ids):
        advisory_snapshot = None
    advisory = _state_audit_progress_advisory(
        advisory_audit,
        clock_ids=advisory_snapshot.clock_ids if advisory_snapshot is not None else None,
    )
    if advisory is not None and advisory_snapshot is not None and (
        _state_audit_snapshot_is_current(advisory_snapshot, delta)
        and _state_audit_snapshot_is_current(advisory_snapshot, audit_delta)
        and _clock_ids_live(conn, advisory_snapshot.clock_ids)
    ):
        artifacts = {**artifacts, "advisory": advisory}
    if should_block_state_audit(audit):
        messages = tuple(state_audit_messages(audit))
        status = "blocked" if state_audit_block else "warning"
        return ValidationStageResult("state_audit", profile, status, issues=messages, artifacts=artifacts)
    if audit.warnings:
        return ValidationStageResult("state_audit", profile, "warning", issues=tuple(audit.warnings), artifacts=artifacts)
    return ValidationStageResult("state_audit", profile, "ok", artifacts=artifacts)


def _state_audit_progress_advisory(
    audit: Any,
    *,
    clock_ids: tuple[str, ...] | None,
) -> dict[str, Any] | None:
    try:
        if clock_ids is None:
            return None
        envelope = adapt_state_audit_progress_advisory(audit, clock_ids=clock_ids)
        if type(envelope) is not ResidentAIAdvisory:
            return None
        normalized_envelope = normalize_resident_ai_advisory(envelope.to_dict())
        if (
            normalized_envelope.advisory_type != "progress_management"
            or normalized_envelope.source_assistant != "state_audit"
            or normalized_envelope.visibility_mode != "maintenance"
            or normalized_envelope.proposed_next_workflow != "none"
            or not matches_state_audit_progress_projection(
                normalized_envelope,
                audit,
                clock_ids=clock_ids,
            )
        ):
            return None
        return resident_ai_advisory_to_maintenance_dict(normalized_envelope)
    except Exception:
        return None


def _state_audit_progress_snapshot(
    *,
    conn: sqlite3.Connection,
    profile: str,
    delta: dict[str, Any],
    stages: tuple[ValidationStageResult, ...],
) -> _StateAuditAdvisorySnapshot | None:
    try:
        if type(profile) is not str or profile not in MAINTENANCE_ADVISORY_PROFILES:
            return None
        delta_schema_stages = tuple(
            stage
            for stage in stages
            if type(stage) is ValidationStageResult
            and type(stage.name) is str
            and stage.name == "delta_schema"
        )
        if len(delta_schema_stages) != 1:
            return None
        delta_schema = delta_schema_stages[0]
        proof = delta_schema._validated_delta_proof
        if (
            type(proof) is not _ValidatedDeltaProof
            or proof not in _MINTED_DELTA_PROOFS
            or proof.connection is not conn
            or type(delta_schema.profile) is not str
            or type(delta_schema.status) is not str
            or delta_schema.profile != profile
            or delta_schema.status != "ok"
        ):
            return None
        _MINTED_DELTA_PROOFS.discard(proof)
        validated_digest = proof.delta_digest
        validated_clock_ids = proof.clock_ids
        if type(validated_digest) is not str or not validated_digest:
            return None
        if type(validated_clock_ids) is not tuple or not validated_clock_ids:
            return None
        if any(type(clock_id) is not str for clock_id in validated_clock_ids):
            return None
        current_clock_ids = _validated_clock_ids(delta)
        if current_clock_ids != validated_clock_ids:
            return None
        audit_delta = json.loads(proof.canonical_delta_json)
        if type(audit_delta) is not dict:
            return None
        snapshot = _StateAuditAdvisorySnapshot(validated_clock_ids, validated_digest, audit_delta)
        return snapshot if _state_audit_snapshot_is_current(snapshot, delta) else None
    except Exception:
        return None


@dataclass(frozen=True)
class _StateAuditAdvisorySnapshot:
    clock_ids: tuple[str, ...]
    delta_digest: str
    audit_delta: dict[str, Any] = field(compare=False, repr=False)


def _state_audit_snapshot_is_current(
    snapshot: _StateAuditAdvisorySnapshot,
    delta: dict[str, Any],
) -> bool:
    try:
        return (
            type(delta) is dict
            and stable_delta_digest(delta) == snapshot.delta_digest
            and _validated_clock_ids(delta) == snapshot.clock_ids
        )
    except Exception:
        return False


def _validated_clock_ids(delta: dict[str, Any]) -> tuple[str, ...] | None:
    try:
        found_tick_clocks, tick_clocks = _exact_dict_value(delta, "tick_clocks")
        if not found_tick_clocks:
            return ()
        if type(tick_clocks) is not list or len(tick_clocks) > MAX_CONTAINER_ITEMS:
            return None
        clock_ids: list[str] = []
        for item in tuple(tick_clocks):
            found_id, item_id = _exact_dict_value(item, "id")
            if not found_id or type(item_id) is not str:
                return None
            clock_ids.append(item_id)
        return tuple(clock_ids)
    except Exception:
        return None


def _clock_ids_live(conn: sqlite3.Connection, clock_ids: tuple[str, ...]) -> bool:
    try:
        unique_ids = tuple(dict.fromkeys(clock_ids))
        if not unique_ids:
            return False
        placeholders = ", ".join("?" for _ in unique_ids)
        rows = conn.execute(
            f"""
            select c.entity_id, e.status
            from main.clocks c
            join main.entities e on e.id = c.entity_id
            where c.entity_id in ({placeholders})
            """,  # noqa: S608
            unique_ids,
        ).fetchall()
        live_ids = {
            entity_id
            for entity_id, status in rows
            if type(entity_id) is str and normalize_visibility_label(status) != "archived"
        }
        return live_ids == set(unique_ids)
    except Exception:
        return False


def _exact_dict_value(value: Any, target_key: str) -> tuple[bool, Any]:
    if type(value) is not dict:
        raise ValueError("invalid exact mapping")
    if len(value) > MAX_CONTAINER_ITEMS:
        raise ValueError("exact mapping exceeds item budget")
    found = False
    result: Any = None
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError("invalid exact mapping key")
        if key == target_key:
            found = True
            result = item
    return found, result


def ok(name: str, profile: str, *, artifacts: dict[str, Any] | None = None) -> ValidationStageResult:
    return ValidationStageResult(name, profile, "ok", artifacts=artifacts or {})


def warning(name: str, profile: str, *issues: str) -> ValidationStageResult:
    return ValidationStageResult(name, profile, "warning", issues=tuple(issues))


def blocked(name: str, profile: str, *issues: str) -> ValidationStageResult:
    return ValidationStageResult(name, profile, "blocked", issues=tuple(issues))


def skipped(name: str, profile: str, reason: str) -> ValidationStageResult:
    return ValidationStageResult(name, profile, "skipped", skipped_reason=reason)


def state_audit_messages(audit: Any) -> list[str]:
    messages = [
        str(item.get("message") or item.get("code") or item)
        for item in audit.findings[:8]
        if isinstance(item, dict)
    ]
    if not messages:
        messages = [f"state_audit risk={audit.risk} requires_human_review={audit.requires_human_review}"]
    return messages


def declared_capabilities(campaign: Campaign) -> set[str]:
    raw = campaign.config.get("capabilities", [])
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def required_capabilities(delta: dict[str, Any], action: str | None) -> set[str]:
    required: set[str] = set()
    action_capability = capability_for_action(action)
    if action_capability:
        required.add(action_capability)
    intent = str(delta.get("intent", "")).strip()
    if intent in ACTION_CAPABILITIES:
        required.add(ACTION_CAPABILITIES[intent])
    elif intent in CAPABILITY_INTENTS:
        required.add(intent)
    if delta.get("tick_clocks"):
        required.add("clock")
    return required


def action_from_delta(
    delta: dict[str, Any],
    *,
    registry: ActionResolverRegistry | None = None,
) -> str | None:
    intent = str(delta.get("intent", "")).strip()
    action_registry = registry if registry is not None else get_default_action_registry()
    if intent in action_registry.names():
        return intent
    return None


def effective_action_options(
    action: str | None,
    delta: dict[str, Any],
    proposal: TurnProposal | None,
    explicit_options: dict[str, Any] | None,
) -> dict[str, Any]:
    options = dict(proposal.intent.options) if proposal else action_options_from_delta(action or "", delta)
    for key, value in (explicit_options or {}).items():
        if value is not None:
            options[str(key)] = value
    return options


def action_options_from_delta(action: str, delta: dict[str, Any]) -> dict[str, Any]:
    payloads = event_payloads(delta)
    options: dict[str, Any] = {}
    if action == "travel":
        put_first(options, "palette_id", payloads, ("palette_id",))
        put_first(options, "destination", payloads, ("to_location_id", "destination_id"))
        if not options.get("destination"):
            options["destination"] = delta.get("location_after")
        put_first(options, "pace", payloads, ("pace",))
    elif action == "social":
        put_first(options, "palette_id", payloads, ("palette_id",))
        put_first(options, "npc", payloads, ("npc_id", "npc", "target_id"))
        put_first(options, "topic", payloads, ("topic",))
        put_first(options, "approach", payloads, ("approach",))
    elif action == "gather":
        put_first(options, "palette_id", payloads, ("palette_id",))
        put_first(options, "target", payloads, ("target_id", "target", "resource_id", "crop_entity_id"))
        put_first(options, "location", payloads, ("location_id", "from_location_id"))
    elif action == "craft":
        put_first(options, "palette_id", payloads, ("palette_id",))
        put_first(options, "project", payloads, ("project_id",))
        put_first(options, "target", payloads, ("target_id", "target_name", "recipe_output"))
        put_first(options, "time_cost", payloads, ("time_cost",))
    elif action == "combat":
        put_first(options, "target", payloads, ("target_id",))
        put_first(options, "weapon", payloads, ("weapon_id",))
        put_first(options, "ammo", payloads, ("ammo_id",))
        put_first(options, "distance", payloads, ("distance",))
        put_first(options, "ready_state", payloads, ("ready_state",))
    elif action == "rest":
        for payload in payloads:
            after = payload.get("after")
            if isinstance(after, dict) and after.get("time_block"):
                options["until"] = after["time_block"]
                break
        meta = delta.get("meta")
        if "until" not in options and isinstance(meta, dict) and meta.get("current_time_block"):
            options["until"] = meta["current_time_block"]
    elif action == "routine":
        put_first(options, "task", payloads, ("task",))
        put_first(options, "target", payloads, ("target_id",))
        put_first(options, "focus", payloads, ("focus",))
        put_first(options, "time_cost", payloads, ("time_cost",))
    elif action == "explore":
        put_first(options, "palette_id", payloads, ("palette_id",))
        put_first(options, "target", payloads, ("target_id", "target_query"))
        put_first(options, "approach", payloads, ("approach",))
        if any(payload.get("target_kind") == "unknown_lead" for payload in payloads):
            options["unknown_lead"] = True
    return options


def event_payloads(delta: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    events = delta.get("events", [])
    if not isinstance(events, list):
        return payloads
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def put_first(target: dict[str, Any], option_name: str, payloads: list[dict[str, Any]], keys: tuple[str, ...]) -> None:
    if target.get(option_name) is not None:
        return
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if value is not None and value != "":
                target[option_name] = value
                return
