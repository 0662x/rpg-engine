from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ..actions import ActionResolverRegistry
from ..ai.provider import AIHelperResult
from ..ai.schema_validation import validate_ai_output_schema
from ..campaign import Campaign
from ..preflight_cache import (
    PreflightLookupResult,
    consume_intent_preflight,
    consume_intent_preflight_by_message,
)
from ..ux import UxStatus
from .adapters import route_outcome_from_consensus_decision
from .arbiter import arbitrate_intent_candidates
from .binder import bind_intent_candidate
from .internal_review import collect_internal_intent_candidate
from .normalization import normalize_intent_candidate
from .risk import RED, assess_rules_fallback
from .types import BoundIntent, ConsensusDecision, IntentCandidate, RouteOutcome

if TYPE_CHECKING:
    from ..intent_router import ActionIntent


@dataclass(frozen=True)
class AIIntentRouteResult:
    internal_candidate: IntentCandidate | None
    internal_helper: AIHelperResult | None
    decision: ConsensusDecision | None
    trace: dict[str, Any]
    rules_outcome: RouteOutcome | None = None
    consensus_outcome: RouteOutcome | None = None
    selected_outcome: RouteOutcome | None = None
    guards: tuple[str, ...] = ()


class AIIntentRouter:
    """Long-term AI intent entry point.

    The router owns AI candidate collection, consensus arbitration and binding
    trace assembly. Callers still decide whether a consensus result is allowed
    to replace their deterministic fallback.
    """

    def __init__(self, conn: sqlite3.Connection, *, registry: ActionResolverRegistry | None = None) -> None:
        self.conn = conn
        self.registry = registry

    def bind(self, candidate: IntentCandidate | dict[str, Any]) -> BoundIntent:
        return bind_intent_candidate(self.conn, candidate, registry=self.registry)

    def decide(
        self,
        *,
        external_candidate: IntentCandidate | dict[str, Any] | None = None,
        internal_candidate: IntentCandidate | dict[str, Any] | None = None,
        rule_candidate: IntentCandidate | dict[str, Any] | None = None,
        internal_review_metadata: dict[str, Any] | None = None,
    ) -> ConsensusDecision:
        return arbitrate_intent_candidates(
            self.conn,
            external_candidate=external_candidate,
            internal_candidate=internal_candidate,
            rule_candidate=rule_candidate,
            internal_review_metadata=internal_review_metadata,
            registry=self.registry,
        )

    def route_candidates(
        self,
        campaign: Campaign,
        user_text: str,
        *,
        intent_ai_mode: str,
        external_candidate: IntentCandidate | dict[str, Any] | None,
        rule_candidate: IntentCandidate | dict[str, Any],
        rules_outcome: RouteOutcome | None = None,
        backend: str,
        provider: str,
        model: str,
        timeout: int,
        base_url: str = "",
        api_key_env: str = "",
        fallback_backend: str = "off",
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> AIIntentRouteResult:
        internal_candidate: IntentCandidate | None = None
        internal_helper: AIHelperResult | None = None
        guards: list[str] = []
        rule = coerce_route_candidate(rule_candidate, source="rules", user_text=user_text)
        external = (
            coerce_route_candidate(external_candidate, source="external_ai", user_text=user_text)
            if external_candidate is not None
            else None
        )
        internal_review_metadata: dict[str, Any] | None = None
        preflight_lookup: PreflightLookupResult | None = None
        preflight_provenance_allowed = False

        if intent_ai_mode == "consensus":
            if preflight_id or message_id:
                preflight_lookup = self.lookup_preflight(
                    campaign,
                    user_text,
                    preflight_id=preflight_id,
                    provider=provider,
                    model=model,
                    backend=backend,
                    fallback_backend=fallback_backend,
                    message_id=message_id,
                    platform=platform,
                    session_key=session_key,
                    source_user_text_hash=source_user_text_hash,
                    external_candidate=external.to_dict() if external else None,
                    rule_candidate=rule.to_dict(),
                    pending_wait_ms=preflight_pending_wait_ms,
                )
                if preflight_lookup.hit and preflight_lookup.internal_review is not None:
                    cached_helper = ai_helper_result_from_preflight(preflight_lookup, provider=provider, model=model)
                    if cached_helper.ok:
                        internal_helper = cached_helper
                        preflight_provenance_allowed = True
                    else:
                        guards.append(f"intent preflight cache invalid: {cached_helper.error}".strip())
                else:
                    guards.append(f"intent preflight cache not used: {preflight_lookup.status} {preflight_lookup.reason}".strip())
            if internal_helper is None:
                if preflight_lookup is not None:
                    self.conn.commit()
                internal_helper = collect_internal_intent_candidate(
                    campaign,
                    self.conn,
                    user_text,
                    external_candidate=external,
                    rule_candidate=rule,
                    backend=backend,
                    provider=provider,
                    model=model,
                    timeout=timeout,
                    base_url=base_url,
                    api_key_env=api_key_env,
                    fallback_backend=fallback_backend,
                )
            if internal_helper.ok and internal_helper.parsed:
                internal_review_metadata = internal_helper.parsed
                internal_candidate = normalize_intent_candidate(
                    internal_helper.parsed,
                    source="internal_ai",
                    user_text=user_text,
                )
            else:
                guards.append(
                    "intent AI internal review unavailable"
                    if not internal_helper.error
                    else f"intent AI internal review unavailable: {internal_helper.error}"
                )

        decision = self.decide(
            external_candidate=external,
            internal_candidate=internal_candidate,
            rule_candidate=rule,
            internal_review_metadata=internal_review_metadata,
        )
        if intent_ai_mode == "consensus" and internal_helper is not None and not internal_helper.ok:
            decision, fallback_guard = self.apply_unavailable_internal_policy(
                rule=rule,
                external=external,
                decision=decision,
                rules_outcome=rules_outcome,
            )
            guards.append(fallback_guard)
        fallback_submode = rules_outcome.submode if rules_outcome else (rule.action or "entity")
        adoption = (
            route_outcome_from_consensus_decision(decision, fallback_submode=fallback_submode)
            if intent_ai_mode == "consensus"
            else None
        )
        consensus_outcome = adoption.outcome if adoption else None
        selected_outcome = consensus_outcome or rules_outcome
        trace: dict[str, Any] = {
            "router": "AIIntentRouter",
            "mode": intent_ai_mode,
            "enabled": intent_ai_mode != "off",
            "backend": backend,
            "provider": provider,
            "model": model,
            "timeout": timeout,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "fallback_backend": fallback_backend,
            "preflight": preflight_trace_for_intent(
                preflight_lookup,
                allow_record=preflight_provenance_allowed,
            ),
            "external_candidate": external.to_dict() if external else None,
            "internal_candidate": internal_candidate.to_dict() if internal_candidate else None,
            "internal_review": summarize_internal_review_metadata(internal_review_metadata),
            "internal_helper": summarize_ai_helper_result(internal_helper),
            "rules_candidate": rule.to_dict(),
            "decision": decision.to_dict(),
            "rules_outcome": rules_outcome.final_trace() if rules_outcome else None,
            "consensus_outcome": consensus_outcome.final_trace() if consensus_outcome else None,
            "selected_outcome": selected_outcome.final_trace() if selected_outcome else None,
        }
        return AIIntentRouteResult(
            internal_candidate=internal_candidate,
            internal_helper=internal_helper,
            decision=decision,
            trace=trace,
            rules_outcome=rules_outcome,
            consensus_outcome=consensus_outcome,
            selected_outcome=selected_outcome,
            guards=tuple(guards),
        )

    def lookup_preflight(
        self,
        campaign: Campaign,
        user_text: str,
        *,
        preflight_id: str = "",
        provider: str,
        model: str,
        backend: str,
        fallback_backend: str = "off",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        external_candidate: dict[str, Any] | None = None,
        rule_candidate: dict[str, Any] | None = None,
        pending_wait_ms: int = 0,
    ) -> PreflightLookupResult:
        if preflight_id:
            return consume_intent_preflight(
                self.conn,
                campaign,
                user_text,
                preflight_id=preflight_id,
                provider=provider,
                model=model,
                backend=backend,
                fallback_backend=fallback_backend,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                external_candidate=external_candidate,
                rule_candidate=rule_candidate,
                pending_wait_ms=pending_wait_ms,
            )
        return consume_intent_preflight_by_message(
            self.conn,
            campaign,
            user_text,
            provider=provider,
            model=model,
            backend=backend,
            fallback_backend=fallback_backend,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            external_candidate=external_candidate,
            rule_candidate=rule_candidate,
            pending_wait_ms=pending_wait_ms,
        )

    def action_intent_from_bound(self, bound: BoundIntent, *, source: str = "ai_consensus") -> ActionIntent:
        return action_intent_from_bound(bound, source=source)

    def apply_unavailable_internal_policy(
        self,
        *,
        rule: IntentCandidate,
        external: IntentCandidate | None,
        decision: ConsensusDecision,
        rules_outcome: RouteOutcome | None,
    ) -> tuple[ConsensusDecision, str]:
        if decision.status != "fallback":
            return decision, "intent AI internal review unavailable; non-fallback consensus decision kept"
        risk = assess_rules_fallback(
            rule,
            external_candidate=external,
            bound=decision.bound,
            rules_outcome=rules_outcome,
        )
        trace = dict(decision.decision_trace)
        trace["fallback_risk"] = risk.to_dict()
        if risk.allow_rules_fallback:
            trace["consensus"] = {
                "status": "fallback",
                "source": "rules_fallback",
                "binding_status": decision.bound.binding_status if decision.bound else "not_applicable",
                "risk": risk.to_dict(),
            }
            return (
                ConsensusDecision(
                    status=decision.status,
                    source=decision.source,
                    candidate=decision.candidate,
                    bound=decision.bound,
                    disagreements=decision.disagreements,
                    decision_trace=trace,
                ),
                f"intent AI internal review unavailable; rules fallback allowed: {risk.reason}",
            )

        status = "blocked" if risk.risk == RED else "clarify"
        source = "ai_helper_unavailable_blocked" if status == "blocked" else "ai_helper_unavailable"
        trace["consensus"] = {
            "status": status,
            "source": source,
            "reason": risk.reason,
            "risk": risk.to_dict(),
        }
        return (
            ConsensusDecision(
                status=status,
                source=source,
                candidate=rule,
                bound=decision.bound,
                disagreements=(f"internal AI unavailable; {risk.reason}",),
                decision_trace=trace,
            ),
            f"intent AI internal review unavailable; rules fallback denied: {risk.reason}",
        )


def action_intent_from_bound(bound: BoundIntent, *, source: str = "ai_consensus") -> ActionIntent:
    from ..intent_router import ActionAlternative, ActionIntent

    candidate = bound.candidate
    mode = "action" if bound.action else candidate.mode
    submode = bound.action or candidate.action or candidate.mode
    status = status_from_bound(bound)
    confidence = candidate.confidence if bound.binding_status == "bound" else "medium"
    alternative = ActionAlternative(
        mode=mode,
        submode=submode,
        action=bound.action,
        score=0.90 if source == "ai_consensus" and bound.binding_status == "bound" else 0.65,
        source=source,
        reason=f"AI intent binding status: {bound.binding_status}",
    )
    return ActionIntent(
        user_text=candidate.source_user_text,
        mode=mode,
        submode=submode,
        action=bound.action,
        options=dict(bound.options),
        confidence=confidence,
        source=source,
        alternatives=(alternative,),
        missing_required=bound.missing_required,
        needs_confirmation=bound.needs_confirmation,
        errors=bound.errors,
        decision_trace={
            "source": source,
            "confidence": confidence,
            "binding": bound.to_dict(),
            "ai_intent": {
                "candidate": candidate.to_dict(),
                "binding": bound.to_dict(),
            },
            "candidates": [asdict(alternative)],
        },
        kind=candidate.kind,
        status=status,
        player_message=player_message_from_bound(bound),
    )


def status_from_bound(bound: BoundIntent) -> UxStatus:
    if bound.binding_status == "bound":
        return "ready"
    if bound.binding_status == "invalid" and bound.errors:
        return "blocked"
    if bound.binding_status == "not_applicable":
        return "clarify"
    return "needs_confirmation"


def player_message_from_bound(bound: BoundIntent) -> str:
    if bound.binding_status == "bound":
        return ""
    if bound.errors:
        return "AI 意图候选未通过内核绑定校验。"
    if bound.missing_required:
        return "需要补充行动槽位：" + "、".join(bound.missing_required)
    if bound.needs_confirmation:
        return "需要确认行动指向：" + "；".join(bound.needs_confirmation)
    return ""


def coerce_route_candidate(
    value: IntentCandidate | dict[str, Any],
    *,
    source: str,
    user_text: str,
) -> IntentCandidate:
    if isinstance(value, IntentCandidate):
        return value
    return normalize_intent_candidate(value, source=source, user_text=user_text)


def summarize_ai_helper_result(result: AIHelperResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "task": result.task,
        "backend": result.backend,
        "provider": result.provider,
        "model": result.model,
        "status": result.status,
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
        "advisory": result.advisory,
        "no_direct_writes": result.no_direct_writes,
        "audit": result.audit,
    }


def preflight_trace_for_intent(
    lookup: PreflightLookupResult | None,
    *,
    allow_record: bool,
) -> dict[str, Any] | None:
    if lookup is None:
        return None
    trace = lookup.to_trace()
    if not allow_record:
        trace["record"] = None
    return trace


def ai_helper_result_from_preflight(
    lookup: PreflightLookupResult,
    *,
    provider: str,
    model: str,
) -> AIHelperResult:
    parsed = lookup.internal_review if isinstance(lookup.internal_review, dict) else {}
    schema_errors = validate_ai_output_schema("internal_intent_review.schema.json", parsed)
    if schema_errors:
        return AIHelperResult(
            task="internal_intent_review",
            backend="preflight_cache",
            provider=provider,
            model=model,
            status="error",
            parsed=None,
            raw_text="",
            error=f"cached internal intent review schema validation failed: {schema_errors[0]}",
            elapsed_ms=0,
            advisory=True,
            no_direct_writes=True,
            audit={
                "preflight": lookup.to_trace(),
                "schema_errors": schema_errors,
                "cached_helper_audit": lookup.helper_audit or {},
            },
        )
    return AIHelperResult(
        task="internal_intent_review",
        backend="preflight_cache",
        provider=provider,
        model=model,
        status="ok",
        parsed=parsed,
        raw_text="",
        error=None,
        elapsed_ms=0,
        advisory=True,
        no_direct_writes=True,
        audit={
            "preflight": lookup.to_trace(),
            "cached_helper_audit": lookup.helper_audit or {},
        },
    )


def summarize_internal_review_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    disagreements = metadata.get("disagreements")
    disagreement_items = disagreements if isinstance(disagreements, list) else ([disagreements] if disagreements else [])
    return {
        "agreement_with_external": metadata.get("agreement_with_external"),
        "external_candidate_quality": metadata.get("external_candidate_quality"),
        "disagreements": [str(item).strip() for item in disagreement_items if str(item).strip()],
    }
