from __future__ import annotations

import re
import sqlite3
from typing import Any

from ..actions import get_default_action_registry
from ..db import get_meta
from ..render import parse_json
from .resolution import is_direct_hit


EXPLORATION_TERMS = ["附近", "周围", "有没有", "看看", "探索", "找找"]


def validate_context(state: Any) -> None:
    if state.mode == "query":
        if state.submode == "entity" and not state.direct_non_context_hits():
            state.missing_required.append("未命中要查询的实体。")
        return

    if state.mode != "action":
        return

    direct_hits = [hit for hit in state.entity_hits if is_direct_hit(hit)]
    if state.submode == "combat":
        if not any(hit.type in {"threat", "character", "species"} for hit in direct_hits):
            state.missing_required.append("战斗目标未明确。")
        if not any(hit.type in {"equipment", "item"} and ("弩" in hit.name or "矛" in hit.name or "刀" in hit.name) for hit in direct_hits):
            state.missing_required.append("武器未明确。")
        if not any(is_ammo_entity(state.conn, hit.id) for hit in direct_hits):
            state.missing_required.append("弹药未明确。")
        if not has_distance_text(state.user_text):
            state.missing_required.append("距离/接敌状态未明确。")
    elif state.submode == "travel":
        current = get_meta(state.conn).get("current_location_id")
        if not any(hit.type == "location" and hit.id != current for hit in direct_hits):
            state.missing_required.append("目的地未明确。")
    elif state.submode == "gather":
        if not any(hit.type in {"item", "material", "plant", "crop_plot", "location"} for hit in direct_hits) and not contains_any(state.user_text, EXPLORATION_TERMS):
            state.missing_required.append("采集目标或探索范围未明确。")
    elif state.submode == "craft":
        if not direct_hits and not re.search(r"(制作|做|加工|修理|升级).+", state.user_text):
            state.missing_required.append("制作目标未明确。")
    elif state.submode == "social":
        if not any(hit.type in {"character", "faction", "faction_state", "location", "species"} for hit in direct_hits):
            state.missing_required.append("社交对象未明确。")
    else:
        spec = get_default_action_registry().get(state.submode)
        if spec and "target" in spec.required_options and not direct_hits:
            state.missing_required.append("行动目标未明确。")


def is_ammo_entity(conn: sqlite3.Connection, entity_id: str) -> bool:
    row = conn.execute("select properties_json, category from items where entity_id = ?", (entity_id,)).fetchone()
    if not row:
        return False
    props = parse_json(row["properties_json"], {})
    return row["category"] == "ammo" or "ammo_profile" in props


def has_distance_text(text: str) -> bool:
    if re.search(r"\d+\s*(步|米|尺|格|m|M)", text):
        return True
    return contains_any(text, ["贴身", "近身", "近距离", "中距离", "远处", "远距离", "视线内"])


def contains_any(text: str, terms: list[str]) -> bool:
    return any(term and term in text for term in terms)
