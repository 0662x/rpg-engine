from __future__ import annotations

import math
from dataclasses import dataclass


TOKEN_CHAR_RATIO = 2.2


@dataclass
class ContextSection:
    key: str
    title: str
    content: str
    priority: int
    required: bool = False
    estimated_tokens: int = 0
    included: bool = True
    omitted_reason: str | None = None


def estimate_tokens(text: str) -> int:
    return int(math.ceil(len(text) / TOKEN_CHAR_RATIO))


def apply_budget(sections: list[ContextSection], limit: int) -> tuple[list[ContextSection], list[ContextSection]]:
    required = [section for section in sections if section.required]
    optional = sorted(
        [section for section in sections if not section.required],
        key=lambda section: (-section.priority, section.estimated_tokens, section.key),
    )
    selected: list[ContextSection] = []
    omitted: list[ContextSection] = []
    used = 0
    for section in required:
        selected.append(section)
        used += section.estimated_tokens
    for section in optional:
        if used + section.estimated_tokens <= limit:
            selected.append(section)
            used += section.estimated_tokens
        else:
            section.included = False
            section.omitted_reason = "token budget"
            omitted.append(section)
    selected.sort(key=lambda section: section_order(section.key))
    return selected, omitted


def section_order(key: str) -> int:
    order = {
        "current_scene": 10,
        "player_state": 20,
        "relevant_entities": 30,
        "ambiguous_candidates": 35,
        "world_settings_core": 36,
        "world_settings": 38,
        "active_clocks": 40,
        "progress_context": 42,
        "relationships": 45,
        "routes": 50,
        "discovery_states": 55,
        "recent_events": 60,
        "memory_summaries": 62,
        "plot_signals": 63,
        "semantic_ai": 65,
        "palette_candidates": 70,
        "required_procedure": 80,
        "response_template": 90,
    }
    return order.get(key, 999)
