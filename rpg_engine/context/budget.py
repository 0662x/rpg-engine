from __future__ import annotations

from dataclasses import dataclass


DISCOVERY_SUBMODES = {"explore", "gather", "travel", "craft"}


@dataclass(frozen=True)
class ContextBudgetDecision:
    limit: int
    profile: str
    reason: str
    preserve_palette_candidates: bool = False


def context_budget_policy(
    *,
    mode: str,
    submode: str | None,
    campaign_default: int,
    explicit_budget: int | None,
) -> ContextBudgetDecision:
    if explicit_budget is not None:
        limit = max(500, int(explicit_budget))
        return ContextBudgetDecision(
            limit=limit,
            profile="explicit",
            reason=f"explicit budget {limit}",
            preserve_palette_candidates=False,
        )

    submode = str(submode or "entity")
    base = max(500, int(campaign_default or 2500))
    profile = "query_entity"
    policy_limit = 3400
    preserve_palette = False
    if mode == "maintenance":
        profile = "maintenance"
        policy_limit = 8000
    elif mode == "action":
        profile = "action"
        policy_limit = 5000
        if submode in {"social", "travel", "combat"}:
            profile = f"action_{submode}"
            policy_limit = 5800
        if submode in {"explore", "gather", "travel", "craft"}:
            profile = f"action_{submode}_discovery"
            policy_limit = 6500
            preserve_palette = True
    elif submode == "scene":
        profile = "query_scene"
        policy_limit = 3800

    limit = max(base, policy_limit)
    return ContextBudgetDecision(
        limit=limit,
        profile=profile,
        reason=f"{profile}: max(campaign_default={base}, policy={policy_limit})",
        preserve_palette_candidates=preserve_palette,
    )
