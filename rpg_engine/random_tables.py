from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .campaign import Campaign


DICE_PATTERN = re.compile(r"^(?P<count>[1-9][0-9]*)?d(?P<sides>[1-9][0-9]*)(?P<modifier>[+-][0-9]+)?$")


@dataclass(frozen=True)
class RandomOutcome:
    kind: str
    result: str
    table_id: str | None = None
    table_name: str | None = None
    visibility: str | None = None
    entry_index: int | None = None
    weight: float | None = None
    dice: str | None = None
    rolls: tuple[int, ...] = ()
    modifier: int = 0
    total: int | None = None
    tags: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "result": self.result,
            "table_id": self.table_id,
            "table_name": self.table_name,
            "visibility": self.visibility,
            "entry_index": self.entry_index,
            "weight": self.weight,
            "dice": self.dice,
            "rolls": list(self.rolls),
            "modifier": self.modifier,
            "total": self.total,
            "tags": list(self.tags),
            "payload": self.payload,
            "generated_by": "aigm_kernel",
        }

    @property
    def summary(self) -> str:
        if self.kind == "dice":
            return f"{self.dice} -> {self.total} ({', '.join(str(item) for item in self.rolls)})"
        return f"{self.table_id} -> {self.result}"


def roll_random_table(campaign: Campaign, table_id: str, *, rng: random.Random | None = None) -> RandomOutcome:
    rng = rng or random.SystemRandom()
    target = table_id.strip()
    if not target:
        raise ValueError("random table id is required")
    for path in campaign.content_files("random_tables"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tables = document.get("random_tables", [])
        if not isinstance(tables, list):
            continue
        for table in tables:
            if not isinstance(table, dict) or str(table.get("id", "")) != target:
                continue
            entries = [entry for entry in table.get("entries", []) if isinstance(entry, dict)]
            if not entries:
                raise ValueError(f"random table has no entries: {target}")
            weighted: list[tuple[int, dict[str, Any], float]] = []
            total_weight = 0.0
            for index, entry in enumerate(entries):
                weight = entry.get("weight", 1)
                if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
                    raise ValueError(f"random table {target} has invalid weight at entry {index}")
                total_weight += float(weight)
                weighted.append((index, entry, float(weight)))
            pick = rng.random() * total_weight
            cursor = 0.0
            chosen_index, chosen_entry, chosen_weight = weighted[-1]
            for index, entry, weight in weighted:
                cursor += weight
                if pick < cursor:
                    chosen_index, chosen_entry, chosen_weight = index, entry, weight
                    break
            result = str(chosen_entry.get("result", "")).strip()
            if not result:
                raise ValueError(f"random table {target} entry {chosen_index} has no result")
            tags = chosen_entry.get("tags", [])
            payload = chosen_entry.get("payload", {})
            return RandomOutcome(
                kind="random_table",
                result=result,
                table_id=target,
                table_name=str(table.get("name", target)),
                visibility=str(table.get("visibility", "known")),
                entry_index=chosen_index,
                weight=chosen_weight,
                tags=tuple(str(item) for item in tags) if isinstance(tags, list) else (),
                payload=payload if isinstance(payload, dict) else {},
            )
    raise ValueError(f"random table not found: {target}")


def roll_dice(expression: str, *, rng: random.Random | None = None) -> RandomOutcome:
    rng = rng or random.SystemRandom()
    raw = expression.strip().lower().replace(" ", "")
    match = DICE_PATTERN.match(raw)
    if not match:
        raise ValueError("dice expression must look like d20, 2d6 or 2d6+1")
    count = int(match.group("count") or "1")
    sides = int(match.group("sides"))
    modifier = int(match.group("modifier") or "0")
    if count > 100:
        raise ValueError("dice count must be <= 100")
    if sides > 10000:
        raise ValueError("dice sides must be <= 10000")
    rolls = tuple(rng.randint(1, sides) for _ in range(count))
    total = sum(rolls) + modifier
    return RandomOutcome(
        kind="dice",
        result=str(total),
        dice=raw,
        rolls=rolls,
        modifier=modifier,
        total=total,
    )
