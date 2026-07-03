from __future__ import annotations

from typing import Any


PLAYER_VIEW = "player"
GM_VIEW = "gm"
MAINTENANCE_VIEW = "maintenance"
VISIBILITY_VIEWS = {PLAYER_VIEW, GM_VIEW, MAINTENANCE_VIEW}


def normalize_visibility_view(value: str | None) -> str:
    view = (value or PLAYER_VIEW).strip().lower()
    return view if view in VISIBILITY_VIEWS else PLAYER_VIEW


def context_visibility_view(mode: str | None) -> str:
    return MAINTENANCE_VIEW if mode == "maintenance" else PLAYER_VIEW


def can_read_hidden(view: str | None) -> bool:
    return normalize_visibility_view(view) in {GM_VIEW, MAINTENANCE_VIEW}


def can_read_entity_visibility(visibility: str | None, view: str | None = PLAYER_VIEW) -> bool:
    return can_read_hidden(view) or visibility != "hidden"


def entity_visibility_sql(view: str | None = PLAYER_VIEW, alias: str = "e") -> str:
    if can_read_hidden(view):
        return ""
    return f"and {alias}.visibility != 'hidden'"


def clock_visibility_sql(view: str | None = PLAYER_VIEW, alias: str = "c") -> str:
    if can_read_hidden(view):
        return ""
    return f"and {alias}.visibility != 'hidden'"


def world_setting_visibility_sql(
    view: str | None = PLAYER_VIEW,
    *,
    entity_alias: str = "e",
    setting_alias: str = "ws",
) -> str:
    if can_read_hidden(view):
        return ""
    return (
        f"and {setting_alias}.visibility in ('known', 'hinted') "
        f"and {entity_alias}.visibility != 'hidden'"
    )


def row_visibility(row: Any) -> str | None:
    try:
        keys = set(row.keys())
    except AttributeError:
        return None
    if "visibility" in keys:
        return row["visibility"]
    if "entity_visibility" in keys:
        return row["entity_visibility"]
    return None


def can_read_entity_row(row: Any, view: str | None = PLAYER_VIEW) -> bool:
    return can_read_entity_visibility(row_visibility(row), view)

