from __future__ import annotations

from .adapters import route_outcome_from_consensus_decision
from .arbiter import arbitrate_intent_candidates
from .binder import bind_intent_candidate, options_namespace
from .external import normalize_external_intent_candidate
from .internal_review import build_internal_intent_review_prompt, collect_internal_intent_candidate
from .normalization import (
    normalize_internal_intent_review,
    normalize_intent_candidate,
    normalize_intent_candidate_dict,
)
from .risk import IntentRiskDecision, assess_rules_fallback
from .safety_contract import ExternalIntentContractError
from .types import (
    BoundIntent,
    CandidateStep,
    ClarificationChoice,
    ClarificationQuestion,
    ConsensusDecision,
    ConsensusRouteAdoption,
    InternalIntentReview,
    IntentCandidate,
    RouteOutcome,
)

__all__ = [
    "AIIntentRouter",
    "AIIntentRouteResult",
    "BoundIntent",
    "CandidateStep",
    "ClarificationChoice",
    "ClarificationQuestion",
    "ConsensusDecision",
    "ConsensusRouteAdoption",
    "ExternalIntentContractError",
    "InternalIntentReview",
    "IntentCandidate",
    "IntentRiskDecision",
    "RouteOutcome",
    "action_intent_from_bound",
    "arbitrate_intent_candidates",
    "assess_rules_fallback",
    "bind_intent_candidate",
    "build_internal_intent_review_prompt",
    "collect_internal_intent_candidate",
    "normalize_external_intent_candidate",
    "normalize_internal_intent_review",
    "normalize_intent_candidate",
    "normalize_intent_candidate_dict",
    "options_namespace",
    "route_outcome_from_consensus_decision",
]


def __getattr__(name: str):
    if name in {"AIIntentRouter", "AIIntentRouteResult", "action_intent_from_bound"}:
        from .router import AIIntentRouteResult, AIIntentRouter, action_intent_from_bound

        return {
            "AIIntentRouter": AIIntentRouter,
            "AIIntentRouteResult": AIIntentRouteResult,
            "action_intent_from_bound": action_intent_from_bound,
        }[name]
    raise AttributeError(name)
