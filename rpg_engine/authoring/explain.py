from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..capabilities import V1_CAPABILITIES


BASE_EXPLANATIONS: dict[str, dict[str, str]] = {
    "field:visibility": {
        "title": "visibility",
        "body": "Controls who can see a record. Use known for player-visible facts, hinted for clues or partial knowledge, and hidden for GM-only facts.",
    },
    "field:summary": {
        "title": "summary",
        "body": "A short player/GM-facing description used in search, cards and context. Keep it concise; put long detail in structured details.",
    },
    "field:aliases": {
        "title": "aliases",
        "body": "Short search names for an entity. Add natural names, abbreviations and Chinese nicknames so players do not need exact IDs.",
    },
    "field:location_id": {
        "title": "location_id",
        "body": "The entity's starting location. It must reference an existing location entity.",
    },
    "error:MISSING_REFERENCE": {
        "title": "Missing reference",
        "body": "A field points to an ID that does not exist. Create the referenced object or update the field to an existing ID.",
    },
    "error:MISSING_REQUIRED_VALUE": {
        "title": "Missing required value",
        "body": "The campaign is missing a required field or file. Add the missing item and run campaign doctor again.",
    },
    "error:UNSUPPORTED_CAPABILITY": {
        "title": "Unsupported capability",
        "body": "The campaign declares a gameplay capability that the V1 runtime does not support. Use a supported capability or remove it.",
    },
}


@dataclass(frozen=True)
class AuthorExplanation:
    ok: bool
    key: str
    title: str = ""
    body: str = ""
    candidates: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "key": self.key,
            "title": self.title,
            "body": self.body,
            "candidates": list(self.candidates),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def explain_author_topic(key: str) -> AuthorExplanation:
    normalized = key.strip()
    explanations = all_explanations()
    if normalized in explanations:
        item = explanations[normalized]
        return AuthorExplanation(ok=True, key=normalized, title=item["title"], body=item["body"])
    return AuthorExplanation(
        ok=False,
        key=normalized,
        candidates=tuple(sorted(explanations)[:50]),
    )


def all_explanations() -> dict[str, dict[str, str]]:
    explanations = dict(BASE_EXPLANATIONS)
    for capability in V1_CAPABILITIES:
        explanations[f"capability:{capability}"] = {
            "title": f"Capability: {capability}",
            "body": capability_body(capability),
        }
    return explanations


def capability_body(capability: str) -> str:
    return {
        "query": "Allows non-mutating scene, entity and context queries.",
        "explore": "Allows inspecting a place, object or clue and drafting exploration consequences.",
        "social": "Allows NPC interaction previews and relationship-aware context.",
        "travel": "Allows movement previews between defined locations and routes.",
        "clock": "Allows progress clocks to track pressure and consequences.",
        "random_table": "Allows auditable random table results from campaign YAML.",
        "clue": "Declares that references, hints or mystery clues are part of the campaign.",
        "risk": "Declares that risk bands, warnings and pressure are gameplay-relevant.",
        "inventory_resource": "Declares inventory, supplies or resources as structured gameplay facts.",
        "project_task": "Declares projects, tasks or crafting goals as gameplay facts.",
        "rest_time": "Allows rest and time passage previews.",
        "trade_exchange": "Declares trade, exchange or bargaining as structured social gameplay.",
        "gather_search": "Allows gathering, harvesting or searching for resources.",
        "combat": "Allows combat or armed threat previews. Use only when the campaign has explicit combat rules and smoke tests.",
    }.get(capability, "Supported V1 gameplay capability.")


def render_explanation(result: AuthorExplanation) -> str:
    if not result.ok:
        lines = ["FAILED", f"- unknown topic: `{result.key}`", "", "## Available Topics"]
        lines.extend(f"- `{item}`" for item in result.candidates)
        return "\n".join(lines).rstrip() + "\n"
    return "\n".join(["# Campaign Explain", "", f"## {result.title}", "", result.body]).rstrip() + "\n"
