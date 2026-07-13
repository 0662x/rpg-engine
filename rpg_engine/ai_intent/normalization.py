from __future__ import annotations

from typing import Any

from ..actions import ActionResolverRegistry, get_default_action_registry
from ..context.rendering import trim_inline
from .safety_contract import SAFETY_FLAG_VALUES
from .types import CandidateStep, InternalIntentReview, IntentCandidate


KIND_VALUES = {"single", "composite", "query", "unresolved"}
MODE_VALUES = {"action", "query", "unknown"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
AGREEMENT_VALUES = {"agree", "partial", "disagree", "no_external"}
EXTERNAL_QUALITY_VALUES = {"usable", "incomplete", "unsafe", "wrong_action", "wrong_mode", "no_external"}
def normalize_intent_candidate_dict(
    value: dict[str, Any],
    *,
    source: str = "unknown",
    user_text: str = "",
    registry: ActionResolverRegistry | None = None,
) -> dict[str, Any]:
    return normalize_intent_candidate(
        value,
        source=source,
        user_text=user_text,
        registry=registry,
    ).to_dict()


def normalize_intent_candidate(
    value: dict[str, Any],
    *,
    source: str = "unknown",
    user_text: str = "",
    registry: ActionResolverRegistry | None = None,
) -> IntentCandidate:
    action_names = set((registry if registry is not None else get_default_action_registry()).names())
    mode = normalize_choice(value.get("mode"), MODE_VALUES, "unknown")
    kind = normalize_choice(value.get("kind"), KIND_VALUES, "unresolved")
    action = normalize_action(value.get("action"), action_names)
    if mode != "action":
        action = None
    elif action is None and kind == "single":
        kind = "unresolved"

    return IntentCandidate(
        source=clean_short(value.get("source") or source, limit=40),
        source_user_text=clean_short(value.get("source_user_text") or user_text, limit=500),
        kind=kind,
        mode=mode,
        action=action,
        slots=normalize_slots(value.get("slots")),
        plan=normalize_plan(value.get("plan"), action_names),
        confidence=normalize_choice(value.get("confidence"), CONFIDENCE_VALUES, "low"),
        missing_slots=tuple(normalize_string_list(value.get("missing_slots"), limit=12, item_limit=80)),
        needs_confirmation=tuple(normalize_string_list(value.get("needs_confirmation"), limit=12, item_limit=120)),
        safety_flags=tuple(normalize_safety_flags(value.get("safety_flags"))),
        reason=clean_short(value.get("reason"), limit=500),
    )


def normalize_internal_intent_review(
    value: dict[str, Any],
    *,
    source: str = "internal_ai",
    user_text: str = "",
    registry: ActionResolverRegistry | None = None,
) -> dict[str, Any]:
    candidate = normalize_intent_candidate(
        {**value, "source": source, "source_user_text": user_text},
        source=source,
        user_text=user_text,
        registry=registry,
    )
    review = InternalIntentReview(
        source=candidate.source,
        source_user_text=candidate.source_user_text,
        kind=candidate.kind,
        mode=candidate.mode,
        action=candidate.action,
        slots=candidate.slots,
        plan=candidate.plan,
        confidence=candidate.confidence,
        missing_slots=candidate.missing_slots,
        needs_confirmation=candidate.needs_confirmation,
        safety_flags=candidate.safety_flags,
        reason=candidate.reason,
        agreement_with_external=normalize_choice(
            value.get("agreement_with_external"),
            AGREEMENT_VALUES,
            "no_external",
        ),
        disagreements=tuple(normalize_string_list(value.get("disagreements"), limit=12, item_limit=160)),
        external_candidate_quality=normalize_choice(
            value.get("external_candidate_quality"),
            EXTERNAL_QUALITY_VALUES,
            "no_external",
        ),
    )
    return review.to_dict()


def normalize_plan(value: Any, action_names: set[str]) -> tuple[CandidateStep, ...]:
    if not isinstance(value, list):
        return ()
    steps: list[CandidateStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        action = normalize_action(item.get("action"), action_names)
        if not action:
            continue
        steps.append(
            CandidateStep(
                action=action,
                slots=normalize_slots(item.get("slots")),
                reason=clean_short(item.get("reason"), limit=240),
            )
        )
        if len(steps) >= 8:
            break
    return tuple(steps)


def normalize_slots(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        name = clean_short(key, limit=60)
        if not name:
            continue
        normalized = normalize_slot_value(item)
        if normalized is not None:
            result[name] = normalized
        if len(result) >= 24:
            break
    return result


def normalize_slot_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, list):
        return normalize_string_list(value, limit=12, item_limit=160)
    if isinstance(value, dict):
        compact = {clean_short(key, limit=60): normalize_slot_value(item) for key, item in value.items()}
        return {key: item for key, item in compact.items() if key and item is not None}
    return clean_short(value, limit=240)


def normalize_action(value: Any, action_names: set[str]) -> str | None:
    text = str(value or "").strip().lower()
    if not text or text in {"none", "null", "unknown"}:
        return None
    return text if text in action_names else None


def normalize_safety_flags(value: Any) -> list[str]:
    flags = normalize_string_list(value, limit=12, item_limit=80)
    return [flag for flag in flags if flag in SAFETY_FLAG_VALUES]


def normalize_string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = clean_short(item, limit=item_limit)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def clean_short(value: Any, *, limit: int) -> str:
    return trim_inline(str(value or "").strip(), limit)
