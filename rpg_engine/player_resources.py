from __future__ import annotations

from typing import Any


DEFAULT_PLAYER_DETAIL_LABELS = {
    "health": "health",
    "stamina": "stamina",
    "hunger": "hunger",
    "thirst": "thirst",
}


def primary_energy_label(meta: dict[str, str]) -> str:
    return str(meta.get("primary_energy_label") or "能量")


def primary_energy_detail_key(meta: dict[str, str]) -> str:
    return str(meta.get("primary_energy_detail_key") or "primary_energy")


def primary_energy_full_value(meta: dict[str, str]) -> str:
    return str(meta.get("primary_energy_full_value") or "██████████  100%")


def primary_energy_value(details: dict[str, Any], meta: dict[str, str]) -> str:
    return str(details.get(primary_energy_detail_key(meta), "未登记"))


def player_detail_items(details: dict[str, Any], meta: dict[str, str]) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    for key, label in DEFAULT_PLAYER_DETAIL_LABELS.items():
        if key in details:
            items.append((label, details[key]))
    energy_key = primary_energy_detail_key(meta)
    if energy_key in details:
        items.append((primary_energy_label(meta), details[energy_key]))
    return items
