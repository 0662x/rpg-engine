from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable


AppendCardSections = Callable[[sqlite3.Connection, list[str], sqlite3.Row], None]
QueryRenderer = Callable[[sqlite3.Connection, sqlite3.Row], str]


@dataclass(frozen=True)
class CardTypeSpec:
    entity_type: str
    card_dir: str
    sort_order: int = 1000
    index_title: str | None = None
    id_prefixes: tuple[str, ...] = field(default_factory=tuple)
    append_sections: AppendCardSections | None = None
    render_query: QueryRenderer | None = None

    @property
    def title(self) -> str:
        return self.index_title or self.entity_type


class CardRegistry:
    def __init__(self) -> None:
        self._by_entity_type: dict[str, CardTypeSpec] = {}
        self._by_id_prefix: dict[str, str] = {}

    def register(self, spec: CardTypeSpec) -> None:
        if spec.entity_type in self._by_entity_type:
            raise ValueError(f"Duplicate card entity type: {spec.entity_type}")
        self._by_entity_type[spec.entity_type] = spec
        for prefix in spec.id_prefixes:
            if prefix in self._by_id_prefix:
                raise ValueError(f"Duplicate card id prefix: {prefix}")
            self._by_id_prefix[prefix] = spec.entity_type

    def by_entity_type(self, entity_type: str) -> CardTypeSpec | None:
        return self._by_entity_type.get(entity_type)

    def entity_type_from_id(self, entity_id: str) -> str:
        prefix = entity_id.split(":", 1)[0]
        return self._by_id_prefix.get(prefix, prefix)

    def card_dir(self, entity_type: str) -> str:
        spec = self.by_entity_type(entity_type)
        return spec.card_dir if spec else "misc"

    def sort_key(self, entity_type: str, name: str) -> tuple[int, str, str]:
        spec = self.by_entity_type(entity_type)
        order = spec.sort_order if spec else 1000
        return (order, entity_type, name)

    def sorted_specs(self) -> list[CardTypeSpec]:
        return sorted(self._by_entity_type.values(), key=lambda spec: (spec.sort_order, spec.entity_type))


def get_default_card_registry() -> CardRegistry:
    registry = CardRegistry()
    register_default_card_types(registry)
    return registry


def register_default_card_types(registry: CardRegistry) -> None:
    from .cards import (
        append_character_card,
        append_clock_card,
        append_crop_plot_card,
        append_details_card,
        append_item_card,
        append_knowledge_card,
        append_location_card,
        append_rule_card,
        hidden_entity_ids,
        redact_hidden_refs,
    )
    from .content_types.world_setting import append_world_setting_card_sections
    from .render import parse_json
    from .render import (
        render_character,
        render_clock,
        render_generic_entity,
        render_item,
        render_knowledge_entity,
        render_location,
        render_rule,
        render_species,
    )

    from .content_types.world_setting import render_world_setting_entity

    def append_knowledge(conn: sqlite3.Connection, lines: list[str], entity: sqlite3.Row) -> None:
        append_knowledge_card(lines, redact_hidden_refs(parse_json(entity["details_json"], {}), hidden_entity_ids(conn)))

    def append_details(conn: sqlite3.Connection, lines: list[str], entity: sqlite3.Row) -> None:
        append_details_card(lines, redact_hidden_refs(parse_json(entity["details_json"], {}), hidden_entity_ids(conn)))

    def query_knowledge(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
        return render_knowledge_entity(entity)

    def query_generic(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
        return render_generic_entity(entity)

    def query_species(conn: sqlite3.Connection, entity: sqlite3.Row) -> str:
        return render_species(entity)

    for spec in [
        CardTypeSpec(
            "character",
            "characters",
            0,
            id_prefixes=("char", "pc"),
            append_sections=append_character_card,
            render_query=render_character,
        ),
        CardTypeSpec(
            "location",
            "locations",
            1,
            id_prefixes=("loc",),
            append_sections=append_location_card,
            render_query=render_location,
        ),
        CardTypeSpec("equipment", "items", 2, append_sections=append_item_card, render_query=render_item),
        CardTypeSpec("item", "items", 3, id_prefixes=("item",), append_sections=append_item_card, render_query=render_item),
        CardTypeSpec("plant", "plants", 4, id_prefixes=("plant",), append_sections=append_knowledge, render_query=query_knowledge),
        CardTypeSpec("material", "materials", 5, id_prefixes=("mat",), append_sections=append_knowledge, render_query=query_knowledge),
        CardTypeSpec(
            "species",
            "species",
            6,
            id_prefixes=("species", "creature"),
            append_sections=append_knowledge,
            render_query=query_species,
        ),
        CardTypeSpec("clock", "clocks", 7, id_prefixes=("clock",), append_sections=append_clock_card, render_query=render_clock),
        CardTypeSpec("rule", "rules", 8, id_prefixes=("rule",), append_sections=append_rule_card, render_query=render_rule),
        CardTypeSpec(
            "world_setting",
            "world_settings",
            9,
            id_prefixes=("world",),
            append_sections=append_world_setting_card_sections,
            render_query=render_world_setting_entity,
        ),
        CardTypeSpec("crop_plot", "crop_plots", 20, id_prefixes=("plot",), append_sections=append_crop_plot_card, render_query=query_generic),
        CardTypeSpec("faction_state", "faction_states", 25, id_prefixes=("fstate",), append_sections=append_details, render_query=query_generic),
        CardTypeSpec("relationship", "relationships", 26, id_prefixes=("rel",), append_sections=append_details, render_query=query_generic),
        CardTypeSpec("project", "projects", 30, id_prefixes=("project",), append_sections=append_details, render_query=query_generic),
        CardTypeSpec("recipe", "recipes", 40, id_prefixes=("recipe",), append_sections=append_details, render_query=query_generic),
        CardTypeSpec("reference", "references", 50, id_prefixes=("ref",), append_sections=append_knowledge, render_query=query_knowledge),
        CardTypeSpec("threat", "threats", 60, id_prefixes=("threat",), append_sections=append_details, render_query=query_generic),
    ]:
        registry.register(spec)
