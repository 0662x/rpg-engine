from __future__ import annotations

import sqlite3
from typing import Any

from ..campaign import Campaign
from ..db import get_meta, get_player_entity_id
from ..preview import (
    build_rest_delta,
    current_location_row,
    normalize_rest_until,
    parse_game_day,
    primary_energy_label,
    render_rest_preview,
    rest_confirmations,
    summarize_crop_plots,
    suggested_rest_clock_ticks,
)
from ..redaction import redact_hidden_entity_refs
from .base import (
    ActionOptionSpec,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
    option_value,
)
from .taxonomy import ActionTaxonomySpec, taxonomy_terms


def preview_rest(campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> str:
    del campaign, context
    return render_rest_preview(
        conn,
        until=option_value(options, "until"),
        user_text=option_value(options, "user_text"),
    )


def resolve_rest(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
) -> ResolutionResult:
    del campaign, context_data
    meta = get_meta(conn)
    rest_target = normalize_rest_until(option_value(options, "until"))
    current_day = parse_game_day(meta.get("current_game_day"))
    target_day = current_day + 1 if rest_target["overnight"] and current_day else current_day
    target_time = rest_target["time_block"]
    location = current_location_row(conn, meta)
    if not location:
        return ResolutionResult(
            status="blocked",
            warnings=("当前地点未解析，不能可靠结算休息。",),
            narrative_constraints=("Repair current_location_id before resolving rest.",),
        )

    player_id = get_player_entity_id(conn)
    pc = conn.execute("select * from entities where id = ?", (player_id,)).fetchone()
    character = conn.execute("select * from characters where entity_id = ?", (player_id,)).fetchone()
    crop_summary = summarize_crop_plots(conn)
    suggested_ticks = suggested_rest_clock_ticks(conn, meta, rest_target)
    confirmations = rest_confirmations(
        rest_target,
        location,
        crop_summary,
        suggested_ticks,
        energy_label=primary_energy_label(meta),
    )
    warnings = [item for item in confirmations if item]
    proposed_delta = build_rest_delta(
        conn,
        meta=meta,
        pc=pc,
        character=character,
        target_day=target_day,
        target_time=target_time,
        location=location,
        suggested_ticks=suggested_ticks,
        user_text=option_value(options, "user_text"),
    )

    facts = [player_id, location["id"]]
    facts.extend(str(row["entity_id"]) for row in crop_summary.get("sample_rows", [])[:6])
    facts.extend(str(item["id"]) for item in suggested_ticks)
    rules = []
    if conn.execute("select 1 from rules where entity_id = 'rule:player-agency'").fetchone():
        rules.append("rule:player-agency")

    return ResolutionResult(
        status="ready",
        facts_used=tuple(redact_hidden_entity_refs(conn, tuple(dict.fromkeys(str(item) for item in facts if item)), drop_empty=False)),
        rules_applied=tuple(rules),
        warnings=tuple(redact_hidden_entity_refs(conn, tuple(warnings), drop_empty=False)),
        proposed_delta=redact_hidden_entity_refs(conn, proposed_delta, drop_empty=False),
        narrative_constraints=(
            "Use rest_turn.md for the response.",
            "Do not introduce night interruptions, dreams, attacks or weather changes unless they are saved in delta.",
            "Treat clock ticks as suggestions that must match the narrated night outcome.",
        ),
    )


def validate_rest_delta(
    campaign: Campaign,
    conn: sqlite3.Connection,
    context_data: dict[str, Any],
    options: Any,
    delta: dict[str, Any],
) -> ActionValidationResult:
    del campaign, context_data
    meta = get_meta(conn)
    rest_target = normalize_rest_until(option_value(options, "until"))
    current_day = parse_game_day(meta.get("current_game_day"))
    target_day = current_day + 1 if rest_target["overnight"] and current_day else current_day
    target_time = rest_target["time_block"]
    current = current_location_row(conn, meta)
    current_location_id = current["id"] if current else None
    errors: list[str] = []
    warnings: list[str] = []
    if not current_location_id:
        errors.append("current_location_id is missing or unreadable")
    if delta.get("intent") != "rest":
        warnings.append("delta intent is not rest")
    if delta.get("location_after") and str(delta["location_after"]) != str(current_location_id):
        errors.append(f"location_after must remain {current_location_id}")
    delta_meta = delta.get("meta", {})
    if isinstance(delta_meta, dict):
        if delta_meta.get("current_location_id") and str(delta_meta["current_location_id"]) != str(current_location_id):
            errors.append(f"meta.current_location_id must remain {current_location_id}")
        if target_day and delta_meta.get("current_game_day") and str(delta_meta["current_game_day"]) != str(target_day):
            errors.append(f"meta.current_game_day must be {target_day}")
        if delta_meta.get("current_time_block") and target_time not in str(delta_meta["current_time_block"]):
            errors.append(f"meta.current_time_block must include {target_time}")
    for index, event in enumerate(delta.get("events", []) if isinstance(delta.get("events", []), list) else []):
        if not isinstance(event, dict):
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        after = payload.get("after", {})
        if isinstance(after, dict):
            if after.get("location_id") and str(after["location_id"]) != str(current_location_id):
                errors.append(f"events[{index}].payload.after.location_id must remain {current_location_id}")
            if target_day and after.get("day") and str(after["day"]) != str(target_day):
                errors.append(f"events[{index}].payload.after.day must be {target_day}")
            if after.get("time_block") and str(after["time_block"]) != target_time:
                errors.append(f"events[{index}].payload.after.time_block must be {target_time}")
    return ActionValidationResult(errors=tuple(errors), warnings=tuple(warnings))


REST_RESOLVER = ActionResolverSpec(
    name="rest",
    preview=preview_rest,
    response_template="rest_turn.md",
    option_specs=option_specs_for(
        ActionOptionSpec("until", "target rest time", default="morning"),
        ActionOptionSpec("user_text", "original player action text", dest="user-text"),
    ),
    taxonomy=ActionTaxonomySpec(
        terms=(
            *taxonomy_terms(
                "zh-Hans",
                ("睡", "休息", "守夜", "等到明早", "过夜"),
                roles=("preview.mismatch", "simple"),
            ),
            *taxonomy_terms("en", ("rest", "sleep", "wait"), roles=("preview.mismatch", "simple")),
        ),
        semantic_labels=("rest", "sleep", "wait"),
        inference_priority=20,
    ),
    resolve=resolve_rest,
    validate_delta=validate_rest_delta,
)
