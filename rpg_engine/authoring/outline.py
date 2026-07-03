from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..campaign import load_campaign
from ..campaign_validation import load_smoke_cases
from ..packages.service import load_package_source
from ..palette import load_palette_entries


@dataclass(frozen=True)
class CampaignOutline:
    campaign_id: str
    name: str
    package_version: str
    capabilities: tuple[str, ...]
    start: dict[str, str]
    counts: dict[str, int]
    key_locations: tuple[dict[str, str], ...] = ()
    key_characters: tuple[dict[str, str], ...] = ()
    rules: tuple[dict[str, str], ...] = ()
    clocks: tuple[dict[str, str], ...] = ()
    random_tables: tuple[dict[str, str], ...] = ()
    palette_counts: dict[str, int] = field(default_factory=dict)
    smoke_coverage: dict[str, bool] = field(default_factory=dict)
    maintenance_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "name": self.name,
            "package_version": self.package_version,
            "capabilities": list(self.capabilities),
            "start": dict(self.start),
            "counts": dict(self.counts),
            "key_locations": list(self.key_locations),
            "key_characters": list(self.key_characters),
            "rules": list(self.rules),
            "clocks": list(self.clocks),
            "random_tables": list(self.random_tables),
            "palette_counts": dict(self.palette_counts),
            "smoke_coverage": dict(self.smoke_coverage),
            "maintenance_notes": list(self.maintenance_notes),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_campaign_outline(campaign_dir: str | Path, *, view: str = "author") -> CampaignOutline:
    campaign = load_campaign(campaign_dir)
    source = load_package_source(campaign.root)
    entities = source.records_by_type.get("entity", [])
    entity_by_id = {str(record.get("id")): record for record in entities if record.get("id")}
    counts = build_counts(source.records_by_type)
    capabilities = tuple(str(item) for item in campaign.config.get("capabilities", []) if str(item).strip())
    start = {
        "player_entity_id": campaign.player_entity_id,
        "player_name": str(entity_by_id.get(campaign.player_entity_id, {}).get("name", "")),
        "initial_location_id": str(campaign.config.get("initial_location_id", "")),
        "initial_location_name": str(entity_by_id.get(str(campaign.config.get("initial_location_id", "")), {}).get("name", "")),
        "initial_game_time": str(campaign.config.get("initial_game_time", "")),
    }
    key_locations = tuple(
        summarize_entity(record, view=view)
        for record in entities
        if str(record.get("type")) == "location"
    )[:8]
    key_characters = tuple(
        summarize_entity(record, view=view)
        for record in entities
        if str(record.get("type")) == "character"
    )[:8]
    rules = tuple(
        {
            "id": str(record.get("id", "")),
            "statement": str(record.get("statement", "")),
        }
        for record in source.records_by_type.get("rule", [])[:8]
    )
    clocks = tuple(
        {
            "id": str(record.get("id", "")),
            "name": str(record.get("name", "")),
            "visibility": str(record.get("visibility", "visible")),
            "segments": f"{record.get('segments_filled', 0)}/{record.get('segments_total', '?')}",
        }
        for record in source.records_by_type.get("clock", [])[:8]
    )
    random_tables = tuple(load_random_table_summaries(campaign.root, campaign.config))
    palette_counts = load_palette_counts(campaign)
    smoke_coverage = load_smoke_coverage(campaign.root, capabilities)
    notes = maintenance_notes(campaign.root, campaign.config, counts)
    return CampaignOutline(
        campaign_id=campaign.campaign_id,
        name=campaign.name,
        package_version=campaign.package_version,
        capabilities=capabilities,
        start=start,
        counts=counts,
        key_locations=key_locations,
        key_characters=key_characters,
        rules=rules,
        clocks=clocks,
        random_tables=random_tables,
        palette_counts=palette_counts,
        smoke_coverage=smoke_coverage,
        maintenance_notes=tuple(notes),
    )


def render_campaign_outline(outline: CampaignOutline) -> str:
    lines = [
        f"# Campaign Outline: {outline.name}",
        "",
        "## Package",
        "",
        f"- id: `{outline.campaign_id}`",
        f"- version: `{outline.package_version}`",
        "- capabilities: " + (", ".join(f"`{item}`" for item in outline.capabilities) or "none"),
        "",
        "## Start",
        "",
        f"- player: `{outline.start.get('player_entity_id', '')}` {outline.start.get('player_name', '')}".rstrip(),
        f"- initial_location: `{outline.start.get('initial_location_id', '')}` {outline.start.get('initial_location_name', '')}".rstrip(),
        f"- initial_time: {outline.start.get('initial_game_time', '') or 'not specified'}",
        "",
        "## Content Counts",
        "",
        "| Type | Count |",
        "|------|------:|",
    ]
    for key, value in sorted(outline.counts.items()):
        lines.append(f"| `{key}` | {value} |")
    append_record_table(lines, "Key Locations", outline.key_locations)
    append_record_table(lines, "Key Characters", outline.key_characters)
    if outline.rules:
        lines.extend(["", "## Rules", ""])
        for rule in outline.rules:
            lines.append(f"- `{rule['id']}` {rule['statement']}")
    if outline.clocks:
        lines.extend(["", "## Clocks", ""])
        for clock in outline.clocks:
            lines.append(f"- `{clock['id']}` {clock['name']} ({clock['visibility']}, {clock['segments']})")
    if outline.random_tables:
        lines.extend(["", "## Random Tables", ""])
        for table in outline.random_tables:
            lines.append(f"- `{table['id']}` {table['name']} ({table['entries']} entries)")
    if outline.palette_counts:
        lines.extend(["", "## Palette Candidates", "", "| Kind | Count |", "|------|------:|"])
        for key, value in sorted(outline.palette_counts.items()):
            lines.append(f"| `{key}` | {value} |")
    if outline.smoke_coverage:
        lines.extend(["", "## Smoke Coverage", "", "| Capability | Covered |", "|------------|---------|"])
        for capability, covered in sorted(outline.smoke_coverage.items()):
            lines.append(f"| `{capability}` | {'yes' if covered else 'no'} |")
    if outline.maintenance_notes:
        lines.extend(["", "## Maintenance Notes", ""])
        lines.extend(f"- {item}" for item in outline.maintenance_notes)
    return "\n".join(lines).rstrip() + "\n"


def summarize_entity(record: dict[str, Any], *, view: str) -> dict[str, str]:
    visibility = str(record.get("visibility", "known"))
    summary = "" if visibility == "hidden" and view != "debug" else str(record.get("summary", ""))
    return {
        "id": str(record.get("id", "")),
        "name": str(record.get("name", "")),
        "type": str(record.get("type", "")),
        "visibility": visibility,
        "summary": summary,
    }


def append_record_table(lines: list[str], title: str, records: tuple[dict[str, str], ...]) -> None:
    if not records:
        return
    lines.extend(["", f"## {title}", "", "| ID | Name | Visibility | Summary |", "|----|------|------------|---------|"])
    for record in records:
        lines.append(
            f"| `{record['id']}` | {record['name']} | {record['visibility']} | {record['summary']} |"
        )


def build_counts(records_by_type: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for content_type, records in records_by_type.items():
        if content_type == "entity":
            for record in records:
                entity_type = str(record.get("type") or "unknown")
                counts[entity_type] = counts.get(entity_type, 0) + 1
        else:
            counts[content_type] = len(records)
    return counts


def load_smoke_coverage(root: Path, capabilities: tuple[str, ...]) -> dict[str, bool]:
    coverage = {capability: False for capability in capabilities}
    path = root / "tests" / "smoke.yaml"
    if not path.exists():
        return coverage
    try:
        for case in load_smoke_cases(path):
            for capability in case.get("capabilities", []) or []:
                if capability in coverage:
                    coverage[str(capability)] = True
    except ValueError:
        return coverage
    return coverage


def load_random_table_summaries(root: Path, config: dict[str, Any]) -> list[dict[str, str]]:
    content = config.get("content", {}) if isinstance(config.get("content"), dict) else {}
    raw = content.get("random_tables", [])
    values = raw if isinstance(raw, list) else [raw]
    tables: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, str):
            continue
        path = root / value
        if not path.exists():
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for table in document.get("random_tables", []) or []:
            if not isinstance(table, dict):
                continue
            entries = table.get("entries", [])
            tables.append(
                {
                    "id": str(table.get("id", "")),
                    "name": str(table.get("name", "")),
                    "visibility": str(table.get("visibility", "known")),
                    "entries": str(len(entries) if isinstance(entries, list) else 0),
                }
            )
    return tables[:12]


def load_palette_counts(campaign: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in load_palette_entries(campaign):
        kind = str(entry.get("_kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def maintenance_notes(root: Path, config: dict[str, Any], counts: dict[str, int]) -> list[str]:
    notes: list[str] = []
    for path in sorted(root.rglob("*.yaml")):
        try:
            line_count = len(path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            continue
        if line_count > 800:
            notes.append(f"{relative_path(root, path)} has {line_count} lines; consider splitting it.")
    for field in ("database", "events", "current_snapshot", "current_snapshot_json", "cards"):
        if field in config:
            notes.append(f"campaign.yaml exposes runtime field `{field}`; new author templates can omit it.")
    if not counts:
        notes.append("No registered content records were found.")
    return notes


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
