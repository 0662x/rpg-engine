from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from ..actions import ActionResolverRegistry
from ..ai.advisory import ResidentAIAdvisory, normalize_resident_ai_advisory
from ..ai.advisory_adapters import (
    adapt_internal_intent_review_advisory,
    matches_internal_intent_review_projection,
)
from ..ai.provider import AIHelperResult, public_ai_helper_result_dict
from ..ai.policy import normalize_timeout
from ..ai.schema_validation import validate_ai_output_schema
from ..campaign import Campaign
from ..db import connect
from ..preflight_cache import (
    PreflightLookupResult,
    consume_intent_preflight,
    consume_intent_preflight_by_message,
)
from ..ux import UxStatus
from ..visibility import PLAYER_VIEW
from .adapters import route_outcome_from_intent_decision
from .arbiter import arbitrate_intent_candidates
from .binder import bind_intent_candidate
from .internal_review import collect_internal_intent_candidate
from .normalization import normalize_intent_candidate
from .risk import RED, assess_rules_fallback
from .safety_contract import ExternalContractEvidence
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
    adopted_outcome: RouteOutcome | None = None
    selected_outcome: RouteOutcome | None = None
    guards: tuple[str, ...] = ()
    internal_advisory: ResidentAIAdvisory | None = None


class AIIntentRouter:
    """Long-term AI intent entry point.

    The router owns AI candidate collection, mode-gated arbitration, binding,
    and route-adoption trace assembly.
    """

    def __init__(self, conn: sqlite3.Connection, *, registry: ActionResolverRegistry | None = None) -> None:
        self.conn = conn
        self.registry = registry

    def bind(self, candidate: IntentCandidate | dict[str, Any], *, view: str = PLAYER_VIEW) -> BoundIntent:
        return bind_intent_candidate(self.conn, candidate, registry=self.registry, view=view)

    def decide(
        self,
        *,
        external_candidate: IntentCandidate | dict[str, Any] | None = None,
        internal_candidate: IntentCandidate | dict[str, Any] | None = None,
        rule_candidate: IntentCandidate | dict[str, Any] | None = None,
        internal_review_metadata: dict[str, Any] | None = None,
        intent_ai_mode: str = "consensus",
        view: str = PLAYER_VIEW,
    ) -> ConsensusDecision:
        return arbitrate_intent_candidates(
            self.conn,
            external_candidate=external_candidate,
            internal_candidate=internal_candidate,
            rule_candidate=rule_candidate,
            internal_review_metadata=internal_review_metadata,
            intent_ai_mode=intent_ai_mode,
            registry=self.registry,
            view=view,
        )

    def route_candidates(
        self,
        campaign: Campaign,
        user_text: str,
        *,
        intent_ai_mode: str,
        external_candidate: IntentCandidate | dict[str, Any] | None,
        external_contract_evidence: ExternalContractEvidence | None = None,
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
        view: str = PLAYER_VIEW,
    ) -> AIIntentRouteResult:
        try:
            trace_timeout: int | None = normalize_timeout(timeout)
        except (TypeError, ValueError):
            trace_timeout = None
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
                if self.conn.in_transaction:
                    preflight_lookup = PreflightLookupResult(
                        "unavailable",
                        reason="preflight cache unavailable",
                    )
                else:
                    try:
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
                    except sqlite3.OperationalError as exc:
                        if not sqlite_busy_error(exc):
                            raise
                        preflight_lookup = PreflightLookupResult(
                            "unavailable",
                            reason="preflight cache unavailable",
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
                    view=view,
                )
            if internal_helper.ok and internal_helper.parsed:
                internal_review_metadata = internal_helper.parsed
                internal_candidate = normalize_intent_candidate(
                    internal_helper.parsed,
                    source="internal_ai",
                    user_text=user_text,
                )
            else:
                unavailable_label = (
                    "intent AI internal review timed out"
                    if internal_helper.failure_reason == "timeout"
                    else "intent AI internal review unavailable"
                )
                guards.append(unavailable_label)

        decision = self.decide(
            external_candidate=external,
            internal_candidate=internal_candidate,
            rule_candidate=rule,
            internal_review_metadata=internal_review_metadata,
            intent_ai_mode=intent_ai_mode,
            view=view,
        )
        if intent_ai_mode == "off" and external is not None and (
            rules_outcome is None or rules_outcome.status == "blocked"
        ):
            raw_kernel_errors = (
                rules_outcome.errors
                if rules_outcome is not None and rules_outcome.errors
                else ("deterministic safety evidence unavailable",)
            )
            kernel_errors = tuple(f"kernel safety guard: {item}" for item in raw_kernel_errors)
            decision_trace = {
                **decision.decision_trace,
                "kernel_safety_guard": {
                    "status": "blocked",
                    "errors": list(raw_kernel_errors),
                },
                "consensus": {
                    "status": "blocked",
                    "source": "external_primary",
                    "reason": "kernel safety guard",
                },
            }
            decision = ConsensusDecision(
                status="blocked",
                source="external_primary",
                candidate=decision.candidate or external,
                bound=None,
                disagreements=kernel_errors,
                decision_trace=decision_trace,
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
        may_adopt = intent_ai_mode == "consensus" or (intent_ai_mode == "off" and external is not None)
        adoption = route_outcome_from_intent_decision(decision, fallback_submode=fallback_submode) if may_adopt else None
        adopted_outcome = adoption.outcome if adoption else None
        consensus_outcome = adopted_outcome if intent_ai_mode == "consensus" else None
        selected_outcome = adopted_outcome or rules_outcome
        route_authority = (
            "external_primary"
            if intent_ai_mode == "off" and external is not None and decision.status == "accepted"
            else "kernel_validation"
            if intent_ai_mode == "off" and external is not None
            else "deterministic_rules"
            if intent_ai_mode == "consensus" and adopted_outcome is None
            else "kernel_validation"
            if intent_ai_mode == "consensus" and decision.source.startswith("ai_helper_unavailable")
            else "external_internal_arbitration"
            if intent_ai_mode == "consensus" and external is not None
            else "internal_review"
            if intent_ai_mode == "consensus"
            else "deterministic_rules"
        )
        trace: dict[str, Any] = {
            "router": "AIIntentRouter",
            "mode": intent_ai_mode,
            "route_authority": route_authority,
            "enabled": intent_ai_mode != "off",
            "backend": backend,
            "provider": provider,
            "model": model,
            "timeout": trace_timeout,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "fallback_backend": fallback_backend,
            "preflight": preflight_trace_for_intent(
                preflight_lookup,
                allow_record=preflight_provenance_allowed,
            ),
            "external_candidate": external.to_dict() if external else None,
            "external_contract": (
                external_contract_evidence.to_trace_dict()
                if external is not None and external_contract_evidence is not None
                else None
            ),
            "internal_candidate": internal_candidate.to_dict() if internal_candidate else None,
            "internal_review": summarize_internal_review_metadata(internal_review_metadata),
            "internal_helper": summarize_ai_helper_result(internal_helper),
            "rules_candidate": rule.to_dict(),
            "decision": decision.to_dict(),
            "rules_outcome": rules_outcome.final_trace() if rules_outcome else None,
            "consensus_outcome": consensus_outcome.final_trace() if consensus_outcome else None,
            "adopted_outcome": adopted_outcome.final_trace() if adopted_outcome else None,
            "selected_outcome": selected_outcome.final_trace() if selected_outcome else None,
        }
        internal_advisory: ResidentAIAdvisory | None = None
        if internal_helper is not None and decision.bound is not None:
            try:
                bound_target_ids = tuple(decision.bound.entity_bindings.values())
                adapted_advisory = adapt_internal_intent_review_advisory(
                    internal_helper,
                    bound_target_ids=bound_target_ids,
                    visibility_mode=view,
                )
                if type(adapted_advisory) is ResidentAIAdvisory:
                    normalized_advisory = normalize_resident_ai_advisory(adapted_advisory.to_dict())
                    if (
                        type(view) is str
                        and normalized_advisory.advisory_type == "intent_recognition"
                        and normalized_advisory.source_assistant == "internal_intent_review"
                        and normalized_advisory.visibility_mode == view
                        and normalized_advisory.proposed_next_workflow == "none"
                        and matches_internal_intent_review_projection(
                            normalized_advisory,
                            internal_helper,
                            bound_target_ids=bound_target_ids,
                            visibility_mode=view,
                        )
                    ):
                        internal_advisory = normalized_advisory
            except Exception:
                internal_advisory = None
        return AIIntentRouteResult(
            internal_candidate=internal_candidate,
            internal_helper=internal_helper,
            decision=decision,
            trace=trace,
            rules_outcome=rules_outcome,
            consensus_outcome=consensus_outcome,
            adopted_outcome=adopted_outcome,
            selected_outcome=selected_outcome,
            guards=tuple(guards),
            internal_advisory=internal_advisory,
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
        with connect(campaign) as cache_conn:
            cache_conn.execute("pragma busy_timeout=0")
            if preflight_id:
                return consume_intent_preflight(
                    cache_conn,
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
                cache_conn,
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
    payload = value.to_dict() if isinstance(value, IntentCandidate) else dict(value)
    return normalize_intent_candidate(
        {**payload, "source": source, "source_user_text": user_text},
        source=source,
        user_text=user_text,
    )


def summarize_ai_helper_result(result: AIHelperResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return public_ai_helper_result_dict(result)


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


def sqlite_busy_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message
