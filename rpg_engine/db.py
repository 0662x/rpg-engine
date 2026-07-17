from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .atomic_io import write_text_atomic
from .campaign import Campaign, load_yaml_file
from .resource_paths import read_resource_text
from .redaction import hidden_entity_refs, redact_player_hidden_material_from_refs
from .time_weather import enrich_time_weather_meta
from .visibility import (
    PLAYER_VIEW,
    can_read_hidden,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalize_visibility_view,
    normalized_text_sql,
    player_visible_visibility_sql,
    world_setting_entity_visibility_sql,
)


SEED_TURN_ID = "turn:seed"
SEED_EVENT_ID = "event:seed"
SAVE_SCHEMA_VERSION = "0.3"
CONTENT_SCHEMA_VERSION = "1"
PROJECTION_SCHEMA_VERSION = "1"


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc_value, traceback))
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(campaign: Campaign) -> sqlite3.Connection:
    conn = sqlite3.connect(campaign.database_path, factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma busy_timeout = 5000")
    ensure_visibility_sql_functions(conn)
    return conn


def init_database(campaign: Campaign, *, force: bool = False) -> None:
    campaign.database_path.parent.mkdir(parents=True, exist_ok=True)
    campaign.events_path.parent.mkdir(parents=True, exist_ok=True)
    campaign.current_snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    if force and campaign.database_path.exists():
        campaign.database_path.unlink()
    if force and campaign.events_path.exists():
        campaign.events_path.unlink()

    with connect(campaign) as conn:
        conn.executescript(read_resource_text("migrations", "0001_init.sql"))
        from .migrations import apply_pending_migrations

        apply_pending_migrations(conn)
        seed_base_rows(conn, campaign)
        seed_content(conn, campaign)
        rebuild_fts(conn)
        conn.commit()
        from .projections import rewrite_events_jsonl

        rewrite_events_jsonl(campaign, conn)

    if not campaign.events_path.exists():
        write_text_atomic(campaign.events_path, "")


def seed_base_rows(conn: sqlite3.Connection, campaign: Campaign) -> None:
    now = utc_now()
    conn.execute(
        """
        insert or ignore into turns
        (id, session_id, user_text, intent, summary, changed, created_at)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            SEED_TURN_ID,
            "seed",
            "initialize campaign",
            "seed",
            f"Initial seed for {campaign.name}",
            1,
            now,
        ),
    )
    conn.execute(
        """
        insert or ignore into events
        (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            SEED_EVENT_ID,
            SEED_TURN_ID,
            str(campaign.config.get("initial_game_time", "")),
            "campaign_seeded",
            "Campaign initialized",
            f"Seeded campaign {campaign.name}",
            "{}",
            "campaign_content",
            now,
        ),
    )
    meta = enrich_time_weather_meta({
        "schema_version": SAVE_SCHEMA_VERSION,
        "save_schema_version": SAVE_SCHEMA_VERSION,
        "content_schema_version": campaign.content_schema_version or CONTENT_SCHEMA_VERSION,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "engine_version": campaign.engine_version,
        "package_version": campaign.package_version,
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.name,
        "player_entity_id": campaign.player_entity_id,
        "current_turn_id": SEED_TURN_ID,
        "current_game_day": str(campaign.config.get("initial_game_day", "")),
        "current_time_block": str(campaign.config.get("initial_time_block", "")),
        "current_location_id": str(campaign.config.get("initial_location_id", "")),
        "last_saved_at": now,
    })
    for key in (
        "home_location_ids",
        "base_location_ids",
        "default_combat_weapon_id",
        "default_weapon_id",
        "primary_energy_label",
        "primary_energy_detail_key",
        "primary_energy_full_value",
    ):
        if key not in campaign.defaults:
            continue
        value = campaign.defaults[key]
        meta[key] = json_text(value, "[]") if isinstance(value, (list, dict)) else str(value)
    for key, value in meta.items():
        conn.execute(
            "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
            (key, value),
        )


def seed_content(conn: sqlite3.Connection, campaign: Campaign) -> None:
    from .content_types import ContentRuntime, get_default_registry

    runtime = ContentRuntime(campaign=campaign, conn=conn, turn_id=SEED_TURN_ID, now=utc_now())
    for spec in get_default_registry().seed_specs():
        handler = spec.seed_handler
        if not handler or not spec.campaign_key or not spec.yaml_key:
            continue
        for path in campaign.content_files(spec.campaign_key):
            data = load_yaml_file(path)
            for record in data.get(spec.yaml_key, []):
                handler(runtime, record)


def json_text(value: Any, default: str) -> str:
    if value is None:
        return default
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def upsert_entity(conn: sqlite3.Connection, entity: dict[str, Any]) -> None:
    now = utc_now()
    entity_id = str(entity["id"])
    details = entity.get("details", {})
    conn.execute(
        """
        insert into entities
        (id, type, name, status, visibility, location_id, owner_id, summary, details_json, updated_turn_id, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
          type=excluded.type,
          name=excluded.name,
          status=excluded.status,
          visibility=excluded.visibility,
          location_id=excluded.location_id,
          owner_id=excluded.owner_id,
          summary=excluded.summary,
          details_json=excluded.details_json,
          updated_turn_id=excluded.updated_turn_id,
          updated_at=excluded.updated_at
        """,
        (
            entity_id,
            str(entity["type"]),
            str(entity["name"]),
            str(entity.get("status", "active")),
            str(entity.get("visibility", "known")),
            entity.get("location_id"),
            entity.get("owner_id"),
            str(entity.get("summary", "")),
            json_text(details, "{}"),
            str(entity.get("updated_turn_id", SEED_TURN_ID)),
            now,
        ),
    )
    conn.execute("delete from aliases where entity_id = ? and kind = 'name'", (entity_id,))
    for alias in entity.get("aliases", []):
        conn.execute(
            "insert or ignore into aliases(alias, entity_id, kind) values(?, ?, ?)",
            (str(alias), entity_id, "name"),
        )

    if "character" in entity:
        character = entity["character"] or {}
        conn.execute(
            """
            insert into characters
            (entity_id, species_id, role, attitude, trust, health_state, stress_json,
             consequences_json, goals_json, knowledge_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(entity_id) do update set
              species_id=excluded.species_id,
              role=excluded.role,
              attitude=excluded.attitude,
              trust=excluded.trust,
              health_state=excluded.health_state,
              stress_json=excluded.stress_json,
              consequences_json=excluded.consequences_json,
              goals_json=excluded.goals_json,
              knowledge_json=excluded.knowledge_json
            """,
            (
                entity_id,
                character.get("species_id"),
                character.get("role"),
                character.get("attitude"),
                int(character.get("trust", 0)),
                character.get("health_state"),
                json_text(character.get("stress"), "{}"),
                json_text(character.get("consequences"), "[]"),
                json_text(character.get("goals"), "[]"),
                json_text(character.get("knowledge"), "{}"),
            ),
        )

    if "item" in entity:
        item = entity["item"] or {}
        conn.execute(
            """
            insert into items
            (entity_id, category, quantity, unit, quality, durability_current,
             durability_max, stackable, equipped_slot, properties_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(entity_id) do update set
              category=excluded.category,
              quantity=excluded.quantity,
              unit=excluded.unit,
              quality=excluded.quality,
              durability_current=excluded.durability_current,
              durability_max=excluded.durability_max,
              stackable=excluded.stackable,
              equipped_slot=excluded.equipped_slot,
              properties_json=excluded.properties_json
            """,
            (
                entity_id,
                str(item.get("category", entity.get("type", "item"))),
                item.get("quantity"),
                item.get("unit"),
                item.get("quality"),
                item.get("durability_current"),
                item.get("durability_max"),
                1 if item.get("stackable", False) else 0,
                item.get("equipped_slot"),
                json_text(item.get("properties"), "{}"),
            ),
        )

    if "location" in entity:
        location = entity["location"] or {}
        conn.execute(
            """
            insert into locations
            (entity_id, parent_id, coord_x, coord_y, coord_z, biome, safety_level,
             discovered_turn_id, travel_minutes_from_home, description_short, exits_json, resources_json)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(entity_id) do update set
              parent_id=excluded.parent_id,
              coord_x=excluded.coord_x,
              coord_y=excluded.coord_y,
              coord_z=excluded.coord_z,
              biome=excluded.biome,
              safety_level=excluded.safety_level,
              discovered_turn_id=excluded.discovered_turn_id,
              travel_minutes_from_home=excluded.travel_minutes_from_home,
              description_short=excluded.description_short,
              exits_json=excluded.exits_json,
              resources_json=excluded.resources_json
            """,
            (
                entity_id,
                location.get("parent_id"),
                location.get("coord_x"),
                location.get("coord_y"),
                location.get("coord_z"),
                location.get("biome"),
                location.get("safety_level"),
                location.get("discovered_turn_id", SEED_TURN_ID),
                location.get("travel_minutes_from_home"),
                location.get("description_short"),
                json_text(location.get("exits"), "[]"),
                json_text(location.get("resources"), "[]"),
            ),
        )

    if "crop_plot" in entity:
        plot = entity["crop_plot"] or {}
        conn.execute(
            """
            insert into crop_plots
            (entity_id, plot_no, crop_entity_id, area_sqm, planted_day, growth_stage,
             growth_stage_max, harvest_day_min, harvest_day_max, harvest_status,
             water_status, soil_status, expected_yield, notes)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(entity_id) do update set
              plot_no=excluded.plot_no,
              crop_entity_id=excluded.crop_entity_id,
              area_sqm=excluded.area_sqm,
              planted_day=excluded.planted_day,
              growth_stage=excluded.growth_stage,
              growth_stage_max=excluded.growth_stage_max,
              harvest_day_min=excluded.harvest_day_min,
              harvest_day_max=excluded.harvest_day_max,
              harvest_status=excluded.harvest_status,
              water_status=excluded.water_status,
              soil_status=excluded.soil_status,
              expected_yield=excluded.expected_yield,
              notes=excluded.notes
            """,
            (
                entity_id,
                int(plot["plot_no"]),
                str(plot["crop_entity_id"]),
                plot.get("area_sqm"),
                plot.get("planted_day"),
                plot.get("growth_stage"),
                plot.get("growth_stage_max"),
                plot.get("harvest_day_min"),
                plot.get("harvest_day_max"),
                plot.get("harvest_status"),
                plot.get("water_status"),
                plot.get("soil_status"),
                plot.get("expected_yield"),
                plot.get("notes"),
            ),
        )


def upsert_rule(conn: sqlite3.Connection, rule: dict[str, Any]) -> None:
    entity = {
        "id": rule["id"],
        "type": "rule",
        "name": rule.get("name", rule["id"]),
        "summary": rule["statement"],
        "details": {
            "category": rule.get("category"),
            "scope": rule.get("scope"),
            "examples": rule.get("examples", []),
            "exceptions": rule.get("exceptions", []),
            "source": rule.get("source"),
            "locked": bool(rule.get("locked", False)),
        },
        "aliases": rule.get("aliases", []),
    }
    upsert_entity(conn, entity)
    conn.execute(
        """
        insert into rules
        (entity_id, category, scope, statement, examples_json, exceptions_json, source, locked)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(entity_id) do update set
          category=excluded.category,
          scope=excluded.scope,
          statement=excluded.statement,
          examples_json=excluded.examples_json,
          exceptions_json=excluded.exceptions_json,
          source=excluded.source,
          locked=excluded.locked
        """,
        (
            str(rule["id"]),
            str(rule.get("category", "general")),
            str(rule.get("scope", "world")),
            str(rule["statement"]),
            json_text(rule.get("examples"), "[]"),
            json_text(rule.get("exceptions"), "[]"),
            str(rule.get("source", "content")),
            1 if rule.get("locked", False) else 0,
        ),
    )


def upsert_clock(conn: sqlite3.Connection, clock: dict[str, Any]) -> None:
    entity = {
        "id": clock["id"],
        "type": "clock",
        "name": clock["name"],
        "summary": clock.get("summary", ""),
        "details": {
            "visibility": clock.get("visibility", "visible"),
            "trigger_when_full": clock.get("trigger_when_full", ""),
        },
        "aliases": clock.get("aliases", []),
    }
    upsert_entity(conn, entity)
    conn.execute(
        """
        insert into clocks
        (entity_id, clock_type, segments_total, segments_filled, visibility,
         trigger_when_full, tick_rules_json, last_ticked_turn_id)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(entity_id) do update set
          clock_type=excluded.clock_type,
          segments_total=excluded.segments_total,
          segments_filled=excluded.segments_filled,
          visibility=excluded.visibility,
          trigger_when_full=excluded.trigger_when_full,
          tick_rules_json=excluded.tick_rules_json,
          last_ticked_turn_id=excluded.last_ticked_turn_id
        """,
        (
            str(clock["id"]),
            str(clock.get("clock_type", "project")),
            int(clock["segments_total"]),
            int(clock.get("segments_filled", 0)),
            str(clock.get("visibility", "visible")),
            str(clock.get("trigger_when_full", "")),
            json_text(clock.get("tick_rules"), "{}"),
            clock.get("last_ticked_turn_id", SEED_TURN_ID),
        ),
    )


def upsert_route(conn: sqlite3.Connection, route: dict[str, Any]) -> None:
    conn.execute(
        """
        insert into routes
        (id, from_location_id, to_location_id, travel_minutes, difficulty,
         hazards_json, requirements_json, last_verified_turn_id)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
          from_location_id=excluded.from_location_id,
          to_location_id=excluded.to_location_id,
          travel_minutes=excluded.travel_minutes,
          difficulty=excluded.difficulty,
          hazards_json=excluded.hazards_json,
          requirements_json=excluded.requirements_json,
          last_verified_turn_id=excluded.last_verified_turn_id
        """,
        (
            str(route["id"]),
            str(route["from_location_id"]),
            str(route["to_location_id"]),
            int(route["travel_minutes"]),
            str(route.get("difficulty", "normal")),
            json_text(route.get("hazards"), "[]"),
            json_text(route.get("requirements"), "[]"),
            route.get("last_verified_turn_id", SEED_TURN_ID),
        ),
    )


def rebuild_fts(conn: sqlite3.Connection) -> None:
    ensure_visibility_sql_functions(conn)
    conn.execute("delete from fts_index")
    hidden_refs = hidden_entity_refs(conn)
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        "player",
        entity_alias="e",
        setting_alias="ws",
    )
    rows = conn.execute(
        f"""
        select e.id, e.type, e.name, e.summary, e.details_json
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          and {player_visible_visibility_sql("e.visibility")}
          {entity_subtype_visibility_sql("player", "e", "c")}
          {world_setting_visibility_clause}
        """
    ).fetchall()
    for row in rows:
        aliases = [
            item["alias"]
            for item in conn.execute("select alias from aliases where entity_id = ?", (row["id"],)).fetchall()
        ]
        body = " ".join(
            part
            for part in [row["summary"], row["details_json"], " ".join(aliases)]
            if part
        )
        title = redact_player_hidden_material_from_refs(row["name"], hidden_refs, drop_empty=False) or ""
        body = redact_player_hidden_material_from_refs(body, hidden_refs, drop_empty=False) or ""
        tags = redact_player_hidden_material_from_refs(" ".join(aliases), hidden_refs, drop_empty=False) or ""
        conn.execute(
            "insert into fts_index(entity_id, type, title, body, tags) values (?, ?, ?, ?, ?)",
            (row["id"], row["type"], title, body, tags),
        )


def rebuild_fts_for_entities(conn: sqlite3.Connection, entity_ids: list[str] | set[str] | tuple[str, ...]) -> None:
    ensure_visibility_sql_functions(conn)
    ids = sorted({str(item) for item in entity_ids if str(item).strip()})
    if not ids:
        return
    # Redaction depends on the global hidden/archived ref set. If an entity
    # becomes hidden, archived, renamed, or gains aliases, previously indexed
    # visible rows may need redaction even when their ids did not change.
    rebuild_fts(conn)


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}


def get_player_entity_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("select value from meta where key = 'player_entity_id'").fetchone()
    return str(row[0]) if row and row[0] else "pc:player"


def resolve_entity(conn: sqlite3.Connection, text: str, *, view: str = PLAYER_VIEW) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    text = str(text).strip()
    if not text:
        return None
    view = normalize_visibility_view(view)
    if player_query_contains_hidden_ref(conn, text, view=view):
        return None
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    exact_id = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.id = ?
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        """,
        (text,),
    ).fetchone()
    if exact_id:
        return exact_id
    exact_id_ci = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where lower(e.id) = lower(?)
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        limit 1
        """,
        (text,),
    ).fetchone()
    if exact_id_ci:
        return exact_id_ci
    if looks_like_qualified_entity_id(text):
        return None
    exact_name = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.name = ?
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        order by
          case e.status
            when 'active' then 0
            when 'retired' then 1
            when 'unknown' then 2
            when 'archived' then 9
            else 3
          end,
          e.type,
          e.id
        limit 1
        """,
        (text,),
    ).fetchone()
    if exact_name:
        return exact_name
    alias = conn.execute(
        f"""
        select e.*
        from aliases a
        join entities e on e.id = a.entity_id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where a.alias = ?
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        order by
          case e.status
            when 'active' then 0
            when 'retired' then 1
            when 'unknown' then 2
            else 3
          end,
          e.type,
          e.id
        limit 1
        """,
        (text,),
    ).fetchone()
    if alias:
        return alias

    for token in query_tokens(text):
        exact_token = resolve_entity_exact_token(conn, token, view=view)
        if exact_token:
            return exact_token

    partial = resolve_entity_partial_token(conn, text, view=view)
    if partial:
        return partial
    for token in query_tokens(text):
        partial = resolve_entity_partial_token(conn, token, view=view)
        if partial:
            return partial

    fuzzy = resolve_entity_body_match(conn, text, view=view)
    if fuzzy:
        return fuzzy
    for token in query_tokens(text):
        fuzzy = resolve_entity_body_match(conn, token, view=view)
        if fuzzy:
            return fuzzy

    safe_query = sanitize_fts_query(text)
    if not safe_query:
        return None
    fts = conn.execute(
        f"""
        select e.*
        from fts_index f
        join entities e on e.id = f.entity_id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where fts_index match ?
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
        order by {entity_type_priority_sql("e")}, bm25(fts_index), e.id
        limit 1
        """,
        (safe_query,),
    ).fetchone()
    return fts


def entity_subtype_visibility_sql(view: str | None = PLAYER_VIEW, entity_alias: str = "e", clock_alias: str = "c") -> str:
    if can_read_hidden(view):
        return ""
    return (
        f"and ({normalized_text_sql(f'{entity_alias}.type')} != 'clock' or "
        f"{player_visible_visibility_sql(f'coalesce({clock_alias}.visibility, {entity_alias}.visibility)')})"
    )


def world_setting_entity_join_and_clause(
    conn: sqlite3.Connection,
    view: str | None = PLAYER_VIEW,
    *,
    entity_alias: str = "e",
    setting_alias: str = "ws",
) -> tuple[str, str]:
    has_world_settings = bool(
        conn.execute("select 1 from sqlite_master where type='table' and name='world_settings'").fetchone()
    )
    join = f"left join world_settings {setting_alias} on {setting_alias}.entity_id = {entity_alias}.id" if has_world_settings else ""
    clause = world_setting_entity_visibility_sql(
        view,
        entity_alias=entity_alias,
        setting_alias=setting_alias,
        has_world_settings=has_world_settings,
    )
    return join, clause


def query_tokens(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_:-]+|[\u4e00-\u9fff]+", _normalize_query_token_text(text))
    tokens = [token.strip() for token in tokens if token.strip()]
    return sorted(dict.fromkeys(tokens), key=lambda item: (-len(item), item))


def looks_like_qualified_entity_id(text: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*:[A-Za-z0-9_:-]+", str(text).strip()))


def sanitize_fts_query(text: str) -> str:
    normalized = _normalize_query_token_text(text).replace("-", " ")
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    safe_tokens = []
    for token in tokens[:8]:
        token = token.strip().replace('"', '""')
        if token:
            safe_tokens.append(f'"{token}"')
    return " OR ".join(safe_tokens)


def _normalize_query_token_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    return "".join(
        char
        for char in normalized
        if not unicodedata.category(char).startswith("M") and not _is_default_ignorable_query_character(char)
    )


def _is_default_ignorable_query_character(value: str) -> bool:
    codepoint = ord(value)
    return (
        unicodedata.category(value) == "Cf"
        or value == "\u034f"
        or codepoint in {0x115F, 0x1160, 0x3164, 0xFFA0}
        or 0x17B4 <= codepoint <= 0x17B5
        or 0x180B <= codepoint <= 0x180F
        or 0x200B <= codepoint <= 0x200F
        or 0x202A <= codepoint <= 0x202E
        or 0x2060 <= codepoint <= 0x206F
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xFFF0 <= codepoint <= 0xFFFB
        or 0x1BCA0 <= codepoint <= 0x1BCA3
        or 0x1D173 <= codepoint <= 0x1D17A
        or 0xE0000 <= codepoint <= 0xE0FFF
        or 0xE0100 <= codepoint <= 0xE01EF
    )


def _escape_query_like_literal(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def should_search_body(term: str) -> bool:
    term = str(term).strip()
    if not term:
        return False
    if re.fullmatch(r"[A-Za-z]*\d+[A-Za-z0-9_-]*", term):
        return len(term) >= 5
    if re.fullmatch(r"[A-Za-z]+", term):
        return len(term) >= 4
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", term)
    if cjk_chars and len(cjk_chars) < 2:
        return False
    return len(term) >= 2


def entity_type_priority_sql(alias: str = "e") -> str:
    return (
        f"case {alias}.type "
        "when 'item' then 0 "
        "when 'material' then 1 "
        "when 'plant' then 2 "
        "when 'crop_plot' then 3 "
        "when 'location' then 4 "
        "when 'threat' then 5 "
        "when 'project' then 6 "
        "when 'recipe' then 7 "
        "when 'character' then 8 "
        "when 'faction' then 9 "
        "when 'species' then 10 "
        "when 'clock' then 20 "
        "when 'rule' then 21 "
        "when 'world_setting' then 22 "
        "else 30 end"
    )


def resolve_entity_exact_token(conn: sqlite3.Connection, token: str, *, view: str = PLAYER_VIEW) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    escaped_token = _escape_query_like_literal(token)
    view = normalize_visibility_view(view)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    return conn.execute(
        f"""
        select e.*
        from entities e
        left join aliases a on a.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and (
            lower(e.id) = lower(?)
            or lower(e.id) like '%:' || lower(?) escape '!'
            or e.name = ?
            or a.alias = ?
          )
        order by
          case
            when lower(e.id) = lower(?) then 0
            when lower(e.id) like '%:' || lower(?) escape '!' then 1
            when e.name = ? then 2
            when a.alias = ? then 3
            else 9
          end,
          {entity_type_priority_sql("e")},
          e.id
        limit 1
        """,
        (token, escaped_token, token, token, token, escaped_token, token, token),
    ).fetchone()


def resolve_entity_partial_token(conn: sqlite3.Connection, token: str, *, view: str = PLAYER_VIEW) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    token = str(token).strip()
    if not token:
        return None
    view = normalize_visibility_view(view)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    escaped_token = _escape_query_like_literal(token)
    like = f"%{escaped_token}%"
    suffix_like = f"%:{escaped_token}"
    prefix_like = f"{escaped_token}%"
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        left join aliases a on a.entity_id = e.id
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and (
            lower(e.id) like lower(?) escape '!'
            or lower(e.id) like lower(?) escape '!'
            or e.name like ? escape '!'
            or a.alias like ? escape '!'
          )
        order by
          case
            when lower(e.id) like lower(?) escape '!' then 0
            when e.name like ? escape '!' then 1
            when a.alias like ? escape '!' then 2
            when e.name like ? escape '!' then 3
            when a.alias like ? escape '!' then 4
            when lower(e.id) like lower(?) escape '!' then 5
            else 9
          end,
          {entity_type_priority_sql("e")},
          length(e.name),
          e.id
        limit 12
        """,
        (suffix_like, like, like, like, suffix_like, prefix_like, prefix_like, like, like, like),
    ).fetchall()
    for row in rows:
        if player_candidate_matches_redacted_text(conn, row, token, view=view):
            return row
    return None


def resolve_entity_body_match(conn: sqlite3.Connection, term: str, *, view: str = PLAYER_VIEW) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    if not should_search_body(term):
        return None
    view = normalize_visibility_view(view)
    if player_query_contains_hidden_ref(conn, term, view=view):
        return None
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    world_setting_join, world_setting_visibility_clause = world_setting_entity_join_and_clause(
        conn,
        view,
        entity_alias="e",
        setting_alias="ws",
    )
    like = f"%{_escape_query_like_literal(term)}%"
    rows = conn.execute(
        f"""
        select e.*
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
          {world_setting_visibility_clause}
          and (e.summary like ? escape '!' or e.details_json like ? escape '!')
        order by
          {entity_type_priority_sql("e")},
          length(e.summary),
          e.id
        limit 12
        """,
        (like, like),
    ).fetchall()
    for row in rows:
        if player_candidate_matches_redacted_text(conn, row, term, view=view):
            return row
    return None


def player_query_contains_hidden_ref(conn: sqlite3.Connection, term: str, *, view: str = PLAYER_VIEW) -> bool:
    if can_read_hidden(view):
        return False
    redacted_term = redact_player_hidden_material_from_refs(term, hidden_entity_refs(conn))
    return not redacted_term or redacted_term != term


def player_candidate_matches_redacted_text(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    term: str,
    *,
    view: str = PLAYER_VIEW,
) -> bool:
    if can_read_hidden(view):
        return True
    aliases = [
        item["alias"]
        for item in conn.execute("select alias from aliases where entity_id = ?", (row["id"],)).fetchall()
    ]
    searchable = " ".join(
        str(part)
        for part in [row["id"], row["name"], row["summary"], row["details_json"], " ".join(aliases)]
        if part
    )
    redacted = redact_player_hidden_material_from_refs(searchable, hidden_entity_refs(conn), drop_empty=False)
    return bool(redacted and str(term).lower() in str(redacted).lower())
