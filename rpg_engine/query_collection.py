from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .db import entity_subtype_visibility_sql
from .visibility import (
    PLAYER_VIEW,
    entity_visibility_sql,
    ensure_visibility_sql_functions,
    normalize_visibility_label,
    normalized_text_sql,
    world_setting_entity_visibility_sql,
)


CONTRACT_ID = "PlayerSafeEntityCollectionResult"
CONTRACT_VERSION = "1"
INVALID_REQUEST_ERROR = "structured entity query request is invalid"
PLAYER_ONLY_ERROR = "structured entity query is player-only"
UNAVAILABLE_ERROR = "structured entity query is unavailable"

_REQUEST_FIELDS = frozenset({"entity_type", "category", "scope", "scope_id", "aggregation"})
_SCOPES = frozenset({"all", "owner", "location"})
_AGGREGATIONS = frozenset({"none", "count", "quantity"})
_ENTITY_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_ENTITY_ID_PATTERN = re.compile(r"[a-z]+:[A-Za-z0-9_.-]+\Z")


def _invalid() -> ValueError:
    return ValueError(INVALID_REQUEST_ERROR)


def _query_label(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _normalized_label(value: object) -> str:
    if type(value) is not str:
        raise _invalid()
    normalized = _query_label(value)
    if not normalized or len(normalized) > 128 or any(unicodedata.category(char).startswith("C") for char in normalized):
        raise _invalid()
    return normalized


def _canonical_entity_id(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or not _ENTITY_ID_PATTERN.fullmatch(value):
        raise _invalid()
    return value


@dataclass(frozen=True)
class EntityCollectionRequest:
    entity_type: str
    category: str | None
    scope: str
    scope_id: str | None
    aggregation: str

    @classmethod
    def from_value(cls, value: object) -> EntityCollectionRequest:
        if type(value) is not dict or set(value) - _REQUEST_FIELDS:
            raise _invalid()
        if set(value) < {"entity_type", "scope", "aggregation"}:
            raise _invalid()

        entity_type = _normalized_label(value.get("entity_type"))
        if not _ENTITY_TYPE_PATTERN.fullmatch(entity_type):
            raise _invalid()
        category = _normalized_label(value["category"]) if "category" in value else None
        scope = _normalized_label(value.get("scope"))
        aggregation = _normalized_label(value.get("aggregation"))
        if scope not in _SCOPES or aggregation not in _AGGREGATIONS:
            raise _invalid()

        raw_scope_id = value.get("scope_id")
        if scope == "all":
            if raw_scope_id is not None:
                raise _invalid()
            scope_id = None
        else:
            scope_id = _canonical_entity_id(raw_scope_id)

        if (category is not None or aggregation == "quantity") and entity_type != "item":
            raise _invalid()
        return cls(
            entity_type=entity_type,
            category=category,
            scope=scope,
            scope_id=scope_id,
            aggregation=aggregation,
        )


@dataclass(frozen=True)
class EntityCollectionMember:
    id: str
    name: str
    quantity: int | float | None
    unit: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "quantity": self.quantity, "unit": self.unit}


@dataclass(frozen=True)
class EntityCollectionTotal:
    unit: str | None
    quantity: int | float

    def to_dict(self) -> dict[str, Any]:
        return {"unit": self.unit, "quantity": self.quantity}


@dataclass(frozen=True)
class EntityCollectionResult:
    status: str
    scope: str
    entity_type: str
    category: str | None
    aggregation: str
    members: tuple[EntityCollectionMember, ...]
    totals: tuple[EntityCollectionTotal, ...]

    @property
    def member_count(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": {"id": CONTRACT_ID, "version": CONTRACT_VERSION},
            "status": self.status,
            "view": PLAYER_VIEW,
            "scope": self.scope,
            "entity_type": self.entity_type,
            "category": self.category,
            "aggregation": self.aggregation,
            "members": [member.to_dict() for member in self.members],
            "member_count": self.member_count,
            "totals": [total.to_dict() for total in self.totals],
            "provenance": {
                "source": "current_save_sqlite",
                "pipeline": ["collection", "scope", "status", "visibility", "aggregation"],
            },
            "authority": {
                "current_fact_authority": "data/game.sqlite",
                "read_only": True,
                "creates_pending": False,
                "writes_gameplay_facts": False,
            },
        }


def _has_main_table(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "select 1 from main.sqlite_master where type='table' and name=?",
            (name,),
        ).fetchone()
    )


def _world_setting_sql(conn: sqlite3.Connection, entity_alias: str, setting_alias: str) -> tuple[str, str]:
    has_world_settings = _has_main_table(conn, "world_settings")
    join = (
        f"left join main.world_settings {setting_alias} on {setting_alias}.entity_id={entity_alias}.id"
        if has_world_settings
        else ""
    )
    clause = world_setting_entity_visibility_sql(
        PLAYER_VIEW,
        entity_alias=entity_alias,
        setting_alias=setting_alias,
        has_world_settings=has_world_settings,
    )
    return join, clause


def _scope_anchor_is_visible(conn: sqlite3.Connection, request: EntityCollectionRequest) -> bool:
    if request.scope == "all":
        return True
    world_join, world_clause = _world_setting_sql(conn, "anchor", "anchor_ws")
    type_clause = f"and {normalized_text_sql('anchor.type')}='location'" if request.scope == "location" else ""
    row = conn.execute(
        f"""
        select anchor.id
        from main.entities anchor
        left join main.clocks anchor_clock on anchor_clock.entity_id=anchor.id
        {world_join}
        where anchor.id=?
          and {normalized_text_sql('anchor.status')}='active'
          {type_clause}
          {entity_visibility_sql(PLAYER_VIEW, 'anchor')}
          {entity_subtype_visibility_sql(PLAYER_VIEW, 'anchor', 'anchor_clock')}
          {world_clause}
        limit 1
        """,
        (request.scope_id,),
    ).fetchone()
    return row is not None


def _ensure_query_sql_functions(conn: sqlite3.Connection) -> None:
    conn.create_function("query_nfkc_casefold", 1, _query_label, deterministic=True)


def _query_label_sql(expression: str) -> str:
    return f"query_nfkc_casefold({expression})"


def _json_number(value: object) -> int | float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise ValueError(UNAVAILABLE_ERROR)
    number = value
    if not math.isfinite(number):
        raise ValueError(UNAVAILABLE_ERROR)
    if isinstance(number, float) and number == 0:
        return 0.0
    return number


def _unit_sort_key(unit: str | None) -> tuple[int, str]:
    return (0, "") if unit is None else (1, unit)


def _sum_quantities(values: list[int | float]) -> int | float:
    try:
        total = sum(values) if all(type(value) is int for value in values) else math.fsum(values)
    except OverflowError:
        try:
            exact_total = sum(
                (Fraction.from_float(value) if type(value) is float else Fraction(value) for value in values),
                start=Fraction(),
            )
            total = float(exact_total)
        except (OverflowError, ValueError):
            raise ValueError(UNAVAILABLE_ERROR) from None
    except ValueError:
        raise ValueError(UNAVAILABLE_ERROR) from None
    normalized = _json_number(total)
    if normalized is None:
        raise ValueError(UNAVAILABLE_ERROR)
    return normalized


def collect_entity_query(
    conn: sqlite3.Connection,
    structured: object,
    *,
    view: str = PLAYER_VIEW,
) -> EntityCollectionResult:
    if type(view) is not str or normalize_visibility_label(view) != PLAYER_VIEW:
        raise ValueError(PLAYER_ONLY_ERROR)
    request = EntityCollectionRequest.from_value(structured)
    ensure_visibility_sql_functions(conn)
    _ensure_query_sql_functions(conn)
    if not _scope_anchor_is_visible(conn, request):
        return EntityCollectionResult(
            status="empty",
            scope=request.scope,
            entity_type=request.entity_type,
            category=request.category,
            aggregation=request.aggregation,
            members=(),
            totals=(),
        )

    item_join = "left join main.items i on i.entity_id=e.id"
    world_join, world_clause = _world_setting_sql(conn, "e", "ws")
    predicates = [
        f"{_query_label_sql('e.type')}=?",
        f"{normalized_text_sql('e.status')}='active'",
    ]
    parameters: list[object] = [request.entity_type]
    if request.category is not None:
        predicates.append(f"{_query_label_sql('i.category')}=?")
        parameters.append(request.category)
    if request.scope == "owner":
        predicates.append("e.owner_id=?")
        parameters.append(request.scope_id)
    elif request.scope == "location":
        predicates.append("e.location_id=?")
        parameters.append(request.scope_id)

    rows = conn.execute(
        f"""
        select e.id, e.name, i.quantity, i.unit
        from main.entities e
        {item_join}
        left join main.clocks c on c.entity_id=e.id
        {world_join}
        where {' and '.join(predicates)}
          {entity_visibility_sql(PLAYER_VIEW, 'e')}
          {entity_subtype_visibility_sql(PLAYER_VIEW, 'e', 'c')}
          {world_clause}
        order by e.id
        """,
        tuple(parameters),
    ).fetchall()

    members: list[EntityCollectionMember] = []
    seen: set[str] = set()
    grouped: dict[str | None, list[int | float]] = {}
    for row in rows:
        entity_id = str(row["id"])
        if entity_id in seen:
            continue
        seen.add(entity_id)
        quantity = _json_number(row["quantity"])
        unit_value = row["unit"]
        unit = None if unit_value is None else str(unit_value)
        members.append(
            EntityCollectionMember(
                id=entity_id,
                name=str(row["name"]),
                quantity=quantity,
                unit=unit,
            )
        )
        if request.aggregation == "quantity" and quantity is not None:
            grouped.setdefault(unit, []).append(quantity)

    totals = tuple(
        EntityCollectionTotal(unit=unit, quantity=_sum_quantities(values))
        for unit, values in sorted(grouped.items(), key=lambda item: _unit_sort_key(item[0]))
    )
    return EntityCollectionResult(
        status="ok" if members else "empty",
        scope=request.scope,
        entity_type=request.entity_type,
        category=request.category,
        aggregation=request.aggregation,
        members=tuple(members),
        totals=totals,
    )


def render_entity_collection(result: EntityCollectionResult) -> str:
    if not result.members:
        return "未找到符合条件的可见实体。"
    lines = [
        "## 可见实体集合",
        "",
        f"- 范围：`{result.scope}`",
        f"- 成员数：{result.member_count}",
        "",
        "### 成员",
    ]
    for member in result.members:
        quantity = (
            "数量未知"
            if member.quantity is None
            else f"{_render_number(member.quantity)}{_render_unit(member.unit)}"
        )
        lines.append(f"- `{member.id}` {member.name}：{quantity}")
    if result.totals:
        lines.extend(["", "### 数量聚合"])
        for total in result.totals:
            lines.append(f"- {_render_number(total.quantity)}{_render_unit(total.unit)}")
    return "\n".join(lines)


def _render_number(value: int | float) -> str:
    return str(value) if type(value) is int else repr(value)


def _render_unit(unit: str | None) -> str:
    if unit is None:
        return "（无单位）"
    if unit == "":
        return "（空单位）"
    return unit
