from __future__ import annotations

from typing import Any


TEXT_SLOT_TYPES = {"text", "text_list", "dice_expr", "random_table_id"}
ENTITY_SLOT_TYPES = {"location", "entity_or_text", "text_or_entity"}

ACTION_SLOT_BINDINGS: dict[str, dict[str, Any]] = {
    "travel": {
        "destination": "location",
        "location": "location",
        "pace": "text",
    },
    "social": {
        "npc": ("character", "faction", "faction_state"),
        "target": ("character", "faction", "faction_state"),
        "topic": "text",
        "approach": "text",
        "palette_id": "text",
    },
    "gather": {
        "target": ("plant", "item", "material", "crop_plot"),
        "location": "location",
        "destination": "location",
        "palette_id": "text",
        "output_confirmed": "text",
    },
    "explore": {
        "target": "entity_or_text",
        "location": "location",
        "approach": "text",
        "unknown_lead": "text",
        "palette_id": "text",
    },
    "craft": {
        "project": "project",
        "target": "text_or_entity",
        "materials": "text_list",
        "time_cost": "text",
        "palette_id": "text",
    },
    "combat": {
        "target": ("threat", "character", "species"),
        "weapon": ("equipment", "item"),
        "ammo": "item",
        "distance": "text",
        "ready_state": "text",
    },
    "rest": {
        "until": "text",
    },
    "routine": {
        "task": "text",
        "target": "entity_or_text",
        "focus": "text",
        "time_cost": "text",
    },
    "random_table": {
        "table": "random_table_id",
        "dice": "dice_expr",
        "reason": "text",
    },
}

SLOT_ALIASES: dict[str, dict[str, str]] = {
    "travel": {"target": "destination", "to": "destination", "place": "destination"},
    "social": {"character": "npc", "faction": "npc", "question": "topic"},
    "gather": {"resource": "target", "destination": "location", "place": "location"},
    "explore": {"object": "target", "clue": "target", "place": "location"},
    "craft": {"output": "target", "item": "target", "time": "time_cost"},
    "combat": {"enemy": "target", "foe": "target", "range": "distance"},
    "rest": {"time": "until"},
    "routine": {"object": "target", "time": "time_cost"},
    "random_table": {"table_id": "table"},
}

ACTION_REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    "travel": ("destination",),
    "social": ("npc",),
    "gather": ("target",),
    "explore": ("target",),
    "craft": ("target",),
    "combat": ("target", "weapon", "ammo", "distance"),
    "routine": ("task",),
    "random_table": ("table or dice",),
}

AI_SUPPLIED_CONFIRMATION_SLOTS: dict[str, set[str]] = {
    "combat": {"ready_state"},
}
