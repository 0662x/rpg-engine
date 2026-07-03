from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..content_types import ContentTypeSpec, MergePolicy


@dataclass(frozen=True)
class PackageFieldDiff:
    field: str
    ownership: str
    action: str
    current: Any = None
    incoming: Any = None
    merged: Any = None
    message: str = ""


@dataclass(frozen=True)
class PackageRecordMerge:
    record_id: str
    action: str
    merged: dict[str, Any] | None = None
    diffs: tuple[PackageFieldDiff, ...] = ()
    conflicts: tuple[PackageFieldDiff, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.conflicts


@dataclass(frozen=True)
class PackageDryRunResult:
    content_type: str
    records: tuple[PackageRecordMerge, ...] = ()

    @property
    def ok(self) -> bool:
        return all(record.ok for record in self.records)

    @property
    def conflicts(self) -> tuple[PackageFieldDiff, ...]:
        items: list[PackageFieldDiff] = []
        for record in self.records:
            items.extend(record.conflicts)
        return tuple(items)


MUTATING_ACTIONS = frozenset({"package-update", "package-add", "merge"})


def field_diff_mutates(diff: PackageFieldDiff) -> bool:
    return diff.action in MUTATING_ACTIONS and diff.current != diff.merged


def record_mutating_diffs(record: PackageRecordMerge) -> tuple[PackageFieldDiff, ...]:
    return tuple(diff for diff in record.diffs if field_diff_mutates(diff))


def record_effective_action(record: PackageRecordMerge) -> str:
    if record.action == "update" and record.ok and not record_mutating_diffs(record):
        return "unchanged"
    return record.action


def merge_package_record(
    spec: ContentTypeSpec,
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> PackageRecordMerge:
    policy = spec.merge_policy or MergePolicy()
    record_id = record_id_for(spec, incoming or current)
    merged = dict(current)
    diffs: list[PackageFieldDiff] = []
    conflicts: list[PackageFieldDiff] = []
    for field_name in sorted(set(current) | set(incoming)):
        if current.get(field_name) == incoming.get(field_name) and (field_name in current) == (field_name in incoming):
            continue
        ownership = policy.ownership_for(field_name)
        current_missing = field_name not in current
        incoming_missing = field_name not in incoming
        if incoming_missing:
            diffs.append(
                PackageFieldDiff(
                    field=field_name,
                    ownership=ownership,
                    action="keep-current",
                    current=current.get(field_name),
                    incoming=None,
                    merged=current.get(field_name),
                )
            )
            continue
        if ownership == "author-owned":
            merged[field_name] = incoming[field_name]
            diffs.append(
                PackageFieldDiff(
                    field=field_name,
                    ownership=ownership,
                    action="package-update" if not current_missing else "package-add",
                    current=current.get(field_name),
                    incoming=incoming[field_name],
                    merged=incoming[field_name],
                )
            )
        elif ownership == "runtime-owned":
            if current_missing:
                diffs.append(
                    PackageFieldDiff(
                        field=field_name,
                        ownership=ownership,
                        action="ignore-runtime-package-field",
                        current=None,
                        incoming=incoming[field_name],
                        merged=None,
                    )
                )
            else:
                diffs.append(
                    PackageFieldDiff(
                        field=field_name,
                        ownership=ownership,
                        action="keep-runtime",
                        current=current[field_name],
                        incoming=incoming[field_name],
                        merged=current[field_name],
                    )
                )
        elif ownership == "mergeable":
            try:
                merged_value = merge_values(current.get(field_name), incoming[field_name])
            except TypeError as exc:
                conflicts.append(
                    PackageFieldDiff(
                        field=field_name,
                        ownership=ownership,
                        action="conflict",
                        current=current.get(field_name),
                        incoming=incoming[field_name],
                        merged=current.get(field_name),
                        message=str(exc),
                    )
                )
                continue
            merged[field_name] = merged_value
            diffs.append(
                PackageFieldDiff(
                    field=field_name,
                    ownership=ownership,
                    action="merge",
                    current=current.get(field_name),
                    incoming=incoming[field_name],
                    merged=merged_value,
                )
            )
        else:
            conflicts.append(
                PackageFieldDiff(
                    field=field_name,
                    ownership="conflict-only",
                    action="conflict",
                    current=current.get(field_name),
                    incoming=incoming[field_name],
                    merged=current.get(field_name),
                    message="field requires explicit migration or content-type merge policy",
                )
            )
    return PackageRecordMerge(
        record_id=record_id,
        action="update",
        merged=merged,
        diffs=tuple(diffs),
        conflicts=tuple(conflicts),
    )


def dry_run_package_upgrade(
    spec: ContentTypeSpec,
    current_records: Iterable[dict[str, Any]],
    incoming_records: Iterable[dict[str, Any]],
) -> PackageDryRunResult:
    current_by_id = {record_id_for(spec, record): record for record in current_records}
    incoming_by_id = {record_id_for(spec, record): record for record in incoming_records}
    results: list[PackageRecordMerge] = []
    for record_id in sorted(set(current_by_id) | set(incoming_by_id)):
        current = current_by_id.get(record_id)
        incoming = incoming_by_id.get(record_id)
        if current is None and incoming is not None:
            results.append(PackageRecordMerge(record_id=record_id, action="create", merged=dict(incoming)))
            continue
        if current is not None and incoming is None:
            results.append(
                PackageRecordMerge(
                    record_id=record_id,
                    action="delete",
                    merged=dict(current),
                    conflicts=(
                        PackageFieldDiff(
                            field="__record__",
                            ownership="conflict-only",
                            action="conflict",
                            current=record_id,
                            incoming=None,
                            merged=record_id,
                            message="record deletion requires explicit migration",
                        ),
                    ),
                )
            )
            continue
        if current is not None and incoming is not None:
            results.append(merge_package_record(spec, current, incoming))
    return PackageDryRunResult(content_type=spec.name, records=tuple(results))


def merge_values(current: Any, incoming: Any) -> Any:
    if current is None:
        return incoming
    if isinstance(current, list) and isinstance(incoming, list):
        merged: list[Any] = []
        seen: set[str] = set()
        for value in [*current, *incoming]:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
        return merged
    if isinstance(current, dict) and isinstance(incoming, dict):
        merged = dict(current)
        for key, value in incoming.items():
            if key not in merged:
                merged[key] = value
            elif merged[key] != value:
                raise TypeError(f"mergeable object key conflicts: {key}")
        return merged
    raise TypeError("mergeable field values must both be arrays or both be objects")


def record_id_for(spec: ContentTypeSpec, record: dict[str, Any]) -> str:
    value = spec.record_id(record)
    if not value:
        raise ValueError(f"{spec.name} record has no id")
    return str(value)


def render_package_dry_run(result: PackageDryRunResult) -> str:
    lines = [
        f"# Package Dry Run: {result.content_type}",
        "",
        "| Record | Action | Status | Changes | Conflicts |",
        "|--------|--------|--------|---------|-----------|",
    ]
    for record in result.records:
        changed = len(record_mutating_diffs(record))
        lines.append(
            f"| `{record.record_id}` | {record_effective_action(record)} | {'ok' if record.ok else 'conflict'} | "
            f"{changed} | {len(record.conflicts)} |"
        )
    conflicts = result.conflicts
    if conflicts:
        lines.extend(["", "## Conflicts", ""])
        for conflict in conflicts:
            lines.append(
                f"- `{conflict.field}` ({conflict.ownership}): {conflict.message or conflict.action}"
            )
    return "\n".join(lines) + "\n"
