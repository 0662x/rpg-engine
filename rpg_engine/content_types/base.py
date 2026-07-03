from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from ..campaign import Campaign


@dataclass(frozen=True)
class ContentRuntime:
    campaign: Campaign
    conn: sqlite3.Connection
    turn_id: str
    now: str


def default_record_id(record: dict[str, Any]) -> str:
    return str(record.get("id", ""))


@dataclass(frozen=True)
class MergePolicy:
    author_owned: frozenset[str] = field(default_factory=frozenset)
    runtime_owned: frozenset[str] = field(default_factory=frozenset)
    mergeable: frozenset[str] = field(default_factory=frozenset)
    conflict_only: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for name in ("author_owned", "runtime_owned", "mergeable", "conflict_only"):
            object.__setattr__(self, name, frozenset(getattr(self, name)))

    def ownership_for(self, field_name: str) -> str:
        if field_name in self.author_owned:
            return "author-owned"
        if field_name in self.runtime_owned:
            return "runtime-owned"
        if field_name in self.mergeable:
            return "mergeable"
        return "conflict-only"


@dataclass(frozen=True)
class ContentTypeSpec:
    name: str
    campaign_key: str | None = None
    yaml_key: str | None = None
    delta_key: str | None = None
    entity_type: str | None = None
    table: str | None = None
    count_key: str | None = None
    payload_key: str | None = None
    sync_safe: bool = False
    seed: Callable[[ContentRuntime, dict[str, Any]], None] | None = None
    upsert: Callable[[ContentRuntime, dict[str, Any]], None] | None = None
    validate_record: Callable[[dict[str, Any]], list[str]] | None = None
    validate_database: Callable[[sqlite3.Connection], list[str]] | None = None
    record_id: Callable[[dict[str, Any]], str] = default_record_id
    merge_policy: MergePolicy | None = None

    @property
    def result_key(self) -> str:
        return self.count_key or self.name

    @property
    def event_payload_key(self) -> str:
        return self.payload_key or self.result_key

    @property
    def seed_handler(self) -> Callable[[ContentRuntime, dict[str, Any]], None] | None:
        return self.seed or self.upsert
