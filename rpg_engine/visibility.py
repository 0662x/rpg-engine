from __future__ import annotations

import unicodedata
import sqlite3
from typing import Any


PLAYER_VIEW = "player"
GM_VIEW = "gm"
MAINTENANCE_VIEW = "maintenance"
VISIBILITY_VIEWS = {PLAYER_VIEW, GM_VIEW, MAINTENANCE_VIEW}
EDGE_WHITESPACE_CODEPOINTS = (
    0x0009,
    0x000A,
    0x000B,
    0x000C,
    0x000D,
    0x001C,
    0x001D,
    0x001E,
    0x001F,
    0x0020,
    0x0085,
    0x00A0,
    0x1680,
    0x2000,
    0x2001,
    0x2002,
    0x2003,
    0x2004,
    0x2005,
    0x2006,
    0x2007,
    0x2008,
    0x2009,
    0x200A,
    0x2028,
    0x2029,
    0x202F,
    0x205F,
    0x3000,
    0xFEFF,
    0x200B,
    0x2060,
)
EDGE_WHITESPACE_CHARS = "".join(chr(item) for item in EDGE_WHITESPACE_CODEPOINTS)


def normalize_visibility_view(value: str | None) -> str:
    view = normalize_visibility_label(value or PLAYER_VIEW)
    return view if view in VISIBILITY_VIEWS else PLAYER_VIEW


def context_visibility_view(mode: str | None) -> str:
    return MAINTENANCE_VIEW if mode == "maintenance" else PLAYER_VIEW


def can_read_hidden(view: str | None) -> bool:
    return normalize_visibility_view(view) in {GM_VIEW, MAINTENANCE_VIEW}


def can_read_entity_visibility(visibility: str | None, view: str | None = PLAYER_VIEW) -> bool:
    return can_read_hidden(view) or normalize_visibility_label(visibility) != "hidden"


def normalize_visibility_label(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.strip(EDGE_WHITESPACE_CHARS)
    text = "".join(
        char
        for char in text
        if unicodedata.category(char) != "Cf" and not unicodedata.category(char).startswith("M")
    )
    return text.strip(EDGE_WHITESPACE_CHARS).lower()


def ensure_visibility_sql_functions(conn: sqlite3.Connection) -> None:
    conn.create_function("nfkc_label", 1, normalize_visibility_label, deterministic=True)


def normalized_text_sql(expression: str) -> str:
    return f"nfkc_label({expression})"


def entity_status_sql(alias: str = "e") -> str:
    return normalized_text_sql(f"{alias}.status")


def entity_not_archived_sql(alias: str = "e") -> str:
    return f"{entity_status_sql(alias)} != 'archived'"


def entity_visibility_sql(view: str | None = PLAYER_VIEW, alias: str = "e") -> str:
    if can_read_hidden(view):
        return ""
    return f"and {normalized_text_sql(f'{alias}.visibility')} != 'hidden'"


def clock_visibility_sql(view: str | None = PLAYER_VIEW, alias: str = "c") -> str:
    if can_read_hidden(view):
        return ""
    return f"and {normalized_text_sql(f'{alias}.visibility')} != 'hidden'"


def world_setting_visibility_sql(
    view: str | None = PLAYER_VIEW,
    *,
    entity_alias: str = "e",
    setting_alias: str = "ws",
) -> str:
    if can_read_hidden(view):
        return ""
    return (
        f"and {normalized_text_sql(f'{setting_alias}.visibility')} in ('known', 'hinted') "
        f"and {normalized_text_sql(f'{entity_alias}.visibility')} != 'hidden'"
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
