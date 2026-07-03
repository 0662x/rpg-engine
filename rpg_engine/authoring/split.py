from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..campaign import load_campaign


TARGET_BY_ENTITY_TYPE = {
    "location": "content/locations.yaml",
    "character": "content/characters.yaml",
    "item": "content/items.yaml",
    "equipment": "content/items.yaml",
    "material": "content/items.yaml",
    "project": "content/projects.yaml",
    "reference": "content/references.yaml",
    "species": "content/species.yaml",
    "threat": "content/threats.yaml",
}


@dataclass(frozen=True)
class SplitMove:
    source: str
    target: str
    record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "record_ids": list(self.record_ids),
        }


@dataclass(frozen=True)
class SplitPlan:
    ok: bool
    dry_run: bool
    moves: tuple[SplitMove, ...]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "moves": [move.to_dict() for move in self.moves],
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_split_plan(campaign_dir: str | Path, *, by: str = "type", dry_run: bool = True) -> SplitPlan:
    if by != "type":
        return SplitPlan(ok=False, dry_run=dry_run, moves=(), errors=(f"unsupported split mode: {by}",))
    if not dry_run:
        return SplitPlan(ok=False, dry_run=dry_run, moves=(), errors=("split --apply is not implemented in V1.1",))
    campaign = load_campaign(campaign_dir)
    moves_by_pair: dict[tuple[str, str], list[str]] = {}
    for path in campaign.content_files("entities"):
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        records = data.get("entities", [])
        if not isinstance(records, list):
            continue
        source = relative_path(campaign.root, path)
        for record in records:
            if not isinstance(record, dict):
                continue
            record_id = str(record.get("id", ""))
            target = TARGET_BY_ENTITY_TYPE.get(str(record.get("type")), "content/entities_misc.yaml")
            if source == target:
                continue
            moves_by_pair.setdefault((source, target), []).append(record_id)
    moves = tuple(
        SplitMove(source=source, target=target, record_ids=tuple(ids))
        for (source, target), ids in sorted(moves_by_pair.items())
    )
    return SplitPlan(ok=True, dry_run=True, moves=moves)


def render_split_plan(plan: SplitPlan) -> str:
    if not plan.ok:
        lines = ["FAILED"]
        lines.extend(f"- error: {item}" for item in plan.errors)
        return "\n".join(lines).rstrip() + "\n"
    lines = ["# Campaign Split Plan", "", f"- dry_run: `{str(plan.dry_run).lower()}`"]
    if not plan.moves:
        lines.append("- no moves suggested")
        return "\n".join(lines).rstrip() + "\n"
    lines.extend(["", "| Source | Target | Records |", "|--------|--------|--------:|"])
    for move in plan.moves:
        lines.append(f"| `{move.source}` | `{move.target}` | {len(move.record_ids)} |")
    lines.extend(["", "No files were modified. V1.1 only reports a split plan."])
    return "\n".join(lines).rstrip() + "\n"


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
