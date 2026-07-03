from __future__ import annotations

V1_CAPABILITIES: tuple[str, ...] = (
    "query",
    "explore",
    "social",
    "travel",
    "clock",
    "random_table",
    "clue",
    "risk",
    "inventory_resource",
    "project_task",
    "rest_time",
    "trade_exchange",
    "gather_search",
    "combat",
)

V1_CAPABILITY_SET = set(V1_CAPABILITIES)

ACTION_CAPABILITIES: dict[str, str] = {
    "explore": "explore",
    "travel": "travel",
    "social": "social",
    "gather": "gather_search",
    "rest": "rest_time",
    "routine": "project_task",
    "craft": "project_task",
    "combat": "combat",
    "random_table": "random_table",
}

CAPABILITY_INTENTS = set(V1_CAPABILITIES)


def capability_for_action(action: str | None) -> str | None:
    if not action:
        return None
    return ACTION_CAPABILITIES.get(action.strip())


def is_v1_capability(value: str) -> bool:
    return value in V1_CAPABILITY_SET
