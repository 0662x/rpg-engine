from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .backup import create_backup
from .campaign import Campaign
from .db import connect, utc_now
from .projection_service import ProjectionReport, ProjectionService
from .projections import mark_projections_dirty
from .render import parse_json
from .validation_issues import issues_from_messages
from .visibility import ENTITY_VISIBILITY_LABELS


PATCH_SCHEMA_VERSION = "1"
ALLOWED_TOP_LEVEL = {"patch_schema_version", "reason", "operations"}
ALLOWED_OPS = {
    "set_entity_name",
    "set_entity_summary",
    "set_entity_visibility",
    "add_entity_alias",
    "remove_entity_alias",
    "set_entity_detail",
    "remove_entity_detail",
    "set_character_field",
}
ALLOWED_VISIBILITY = set(ENTITY_VISIBILITY_LABELS)
ALLOWED_VISIBILITY_MESSAGE = "/".join(sorted(ALLOWED_VISIBILITY))
ALLOWED_CHARACTER_FIELDS = {"attitude", "trust", "health_state"}
DETAIL_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class SavePatchResult:
    campaign_id: str
    ok: bool
    operations_applied: int = 0
    touched_entities: tuple[str, ...] = ()
    backup_id: str | None = None
    snapshot_path: Path | None = None
    snapshot_json_path: Path | None = None
    cards_count: int = 0
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)
    projection_report: ProjectionReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "ok": self.ok,
            "operations_applied": self.operations_applied,
            "touched_entities": list(self.touched_entities),
            "backup_id": self.backup_id,
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "snapshot_json_path": str(self.snapshot_json_path) if self.snapshot_json_path else None,
            "cards_count": self.cards_count,
            "errors": list(self.errors),
            "error_details": issues_from_messages(self.errors, default_code="SAVE_PATCH_ERROR"),
            "warnings": list(self.warnings),
            "projection_report": self.projection_report.to_dict() if self.projection_report else None,
        }

    def render(self) -> str:
        if not self.ok:
            lines = ["FAILED"]
            if self.projection_report:
                lines.append(f"- projection_status: `{self.projection_report.status}`")
                if self.projection_report.requested_failed:
                    lines.append(f"- projection_failed: `{', '.join(self.projection_report.requested_failed)}`")
                if self.projection_report.global_failed:
                    lines.append(f"- projection_global_failed: `{', '.join(self.projection_report.global_failed)}`")
            lines.extend(f"- error: {item}" for item in self.errors)
            lines.extend(f"- warning: {item}" for item in self.warnings)
            return "\n".join(lines).rstrip() + "\n"
        lines = [
            "# Save Patch",
            "",
            "- status: `OK`",
            f"- campaign: `{self.campaign_id}`",
            f"- operations_applied: `{self.operations_applied}`",
            f"- backup_id: `{self.backup_id}`",
            f"- cards: `{self.cards_count}`",
        ]
        if self.projection_report:
            lines.append(f"- projection_status: `{self.projection_report.status}`")
            if self.projection_report.requested_failed:
                lines.append(f"- projection_failed: `{', '.join(self.projection_report.requested_failed)}`")
            if self.projection_report.global_failed:
                lines.append(f"- projection_global_failed: `{', '.join(self.projection_report.global_failed)}`")
        if self.touched_entities:
            lines.extend(["", "## Touched Entities", ""])
            lines.extend(f"- `{item}`" for item in self.touched_entities)
        if self.warnings:
            lines.extend(["", "## Warnings", ""])
            lines.extend(f"- {item}" for item in self.warnings)
        return "\n".join(lines).rstrip() + "\n"


def load_patch_file(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("save patch file must contain an object")
    return data


def validate_save_patch(patch: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(patch) - ALLOWED_TOP_LEVEL)
    for key in unknown:
        errors.append(f"$.{key}: unknown top-level field")
    version = str(patch.get("patch_schema_version", PATCH_SCHEMA_VERSION))
    if version != PATCH_SCHEMA_VERSION:
        errors.append(f"$.patch_schema_version: unsupported version {version}")
    reason = patch.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        errors.append("$.reason: must be a non-empty string when present")
    operations = patch.get("operations")
    if not isinstance(operations, list) or not operations:
        errors.append("$.operations: must be a non-empty array")
        return errors
    for index, operation in enumerate(operations):
        path = f"$.operations[{index}]"
        if not isinstance(operation, dict):
            errors.append(f"{path}: must be object")
            continue
        op = operation.get("op")
        if op not in ALLOWED_OPS:
            errors.append(f"{path}.op: unsupported maintenance operation {op}")
            continue
        entity_id = operation.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.strip():
            errors.append(f"{path}.entity_id: required non-empty string")
        validate_operation_shape(operation, path, errors)
    return errors


def validate_operation_shape(operation: dict[str, Any], path: str, errors: list[str]) -> None:
    op = str(operation.get("op", ""))
    if op == "set_entity_name":
        require_text(operation, "name", f"{path}.name", errors)
    elif op == "set_entity_summary":
        require_text(operation, "summary", f"{path}.summary", errors)
    elif op == "set_entity_visibility":
        visibility = operation.get("visibility")
        if visibility not in ALLOWED_VISIBILITY:
            errors.append(f"{path}.visibility: must be {ALLOWED_VISIBILITY_MESSAGE}")
    elif op in {"add_entity_alias", "remove_entity_alias"}:
        require_text(operation, "alias", f"{path}.alias", errors)
    elif op == "set_entity_detail":
        validate_detail_key(operation.get("key"), f"{path}.key", errors)
        if "value" not in operation:
            errors.append(f"{path}.value: required")
        elif not is_safe_detail_value(operation["value"]):
            errors.append(f"{path}.value: must be scalar, list or object without nested binary data")
    elif op == "remove_entity_detail":
        validate_detail_key(operation.get("key"), f"{path}.key", errors)
    elif op == "set_character_field":
        field = operation.get("field")
        if field not in ALLOWED_CHARACTER_FIELDS:
            errors.append(f"{path}.field: must be attitude/trust/health_state")
        if "value" not in operation:
            errors.append(f"{path}.value: required")
        elif field == "trust" and (not isinstance(operation["value"], int) or isinstance(operation["value"], bool)):
            errors.append(f"{path}.value: trust must be integer")
        elif field in {"attitude", "health_state"}:
            value = operation["value"]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{path}.value: must be non-empty string")


def require_text(operation: dict[str, Any], key: str, path: str, errors: list[str]) -> None:
    value = operation.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: required non-empty string")


def validate_detail_key(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not DETAIL_KEY_PATTERN.match(value):
        errors.append(f"{path}: must be 1-64 safe characters")
    elif value in {"location_id", "owner_id", "status", "quantity", "segments_filled", "current_turn_id"}:
        errors.append(f"{path}: protected gameplay field cannot be patched through details")


def is_safe_detail_value(value: Any, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return len(value) <= 100 and all(is_safe_detail_value(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return len(value) <= 100 and all(
            isinstance(key, str) and DETAIL_KEY_PATTERN.match(key) and is_safe_detail_value(item, depth + 1)
            for key, item in value.items()
        )
    return False


def apply_save_patch(campaign: Campaign, patch: dict[str, Any], *, backup: bool = True) -> SavePatchResult:
    errors = validate_save_patch(patch)
    if errors:
        return SavePatchResult(campaign_id=campaign.campaign_id, ok=False, errors=tuple(errors))

    backup_record = create_backup(campaign, reason="pre_save_patch") if backup else None
    touched: set[str] = set()
    warnings: list[str] = []
    now = utc_now()

    try:
        with connect(campaign) as conn:
            current_turn_row = conn.execute("select value from meta where key = 'current_turn_id'").fetchone()
            current_turn_id = str(current_turn_row["value"]) if current_turn_row else "turn:seed"
            for operation in patch["operations"]:
                entity_id = str(operation["entity_id"])
                row = conn.execute("select * from entities where id = ?", (entity_id,)).fetchone()
                if row is None:
                    raise ValueError(f"missing entity: {entity_id}")
                apply_operation(conn, operation, current_turn_id=current_turn_id, now=now)
                touched.add(entity_id)

            if touched:
                memory_invalidated = mark_projections_dirty(
                    conn,
                    ["memory"],
                    turn_id=current_turn_id,
                )
                if not memory_invalidated:
                    warnings.append(
                        "memory projection metadata unavailable; readers will use fail-closed fallback"
                    )
            conn.commit()
            projection_report = ProjectionService(campaign, conn).refresh(
                names=["search", "snapshots", "cards"],
                dirty_only=False,
                profile="save_patch:maintenance_projection",
                commit_policy="caller_committed_required",
            )
            snapshot_artifacts = projection_report.artifacts_for("snapshots")
            cards_item = projection_report.item("cards")
            snapshot_path = Path(snapshot_artifacts[0]) if len(snapshot_artifacts) >= 1 else None
            snapshot_json_path = Path(snapshot_artifacts[1]) if len(snapshot_artifacts) >= 2 else None
            cards_count = int(cards_item.metadata.get("count", 0)) if cards_item else 0
    except Exception as exc:
        return SavePatchResult(
            campaign_id=campaign.campaign_id,
            ok=False,
            backup_id=backup_record.id if backup_record else None,
            errors=(str(exc),),
        )

    return SavePatchResult(
        campaign_id=campaign.campaign_id,
        ok=projection_report.ok,
        operations_applied=len(patch["operations"]),
        touched_entities=tuple(sorted(touched)),
        backup_id=backup_record.id if backup_record else None,
        snapshot_path=snapshot_path,
        snapshot_json_path=snapshot_json_path,
        cards_count=cards_count,
        warnings=tuple(warnings),
        projection_report=projection_report,
    )


def apply_operation(conn: Any, operation: dict[str, Any], *, current_turn_id: str, now: str) -> None:
    op = str(operation["op"])
    entity_id = str(operation["entity_id"])
    if op == "set_entity_name":
        conn.execute(
            "update entities set name = ?, updated_turn_id = ?, updated_at = ? where id = ?",
            (str(operation["name"]).strip(), current_turn_id, now, entity_id),
        )
    elif op == "set_entity_summary":
        conn.execute(
            "update entities set summary = ?, updated_turn_id = ?, updated_at = ? where id = ?",
            (str(operation["summary"]).strip(), current_turn_id, now, entity_id),
        )
    elif op == "set_entity_visibility":
        conn.execute(
            "update entities set visibility = ?, updated_turn_id = ?, updated_at = ? where id = ?",
            (str(operation["visibility"]), current_turn_id, now, entity_id),
        )
        if table_exists(conn, "world_settings"):
            conn.execute(
                "update world_settings set visibility = ? where entity_id = ?",
                (str(operation["visibility"]), entity_id),
            )
    elif op == "add_entity_alias":
        conn.execute(
            "insert or ignore into aliases(alias, entity_id, kind) values (?, ?, 'name')",
            (str(operation["alias"]).strip(), entity_id),
        )
        touch_entity(conn, entity_id, current_turn_id, now)
    elif op == "remove_entity_alias":
        conn.execute(
            "delete from aliases where entity_id = ? and alias = ?",
            (entity_id, str(operation["alias"]).strip()),
        )
        touch_entity(conn, entity_id, current_turn_id, now)
    elif op == "set_entity_detail":
        details = entity_details(conn, entity_id)
        details[str(operation["key"])] = operation["value"]
        write_entity_details(conn, entity_id, details, current_turn_id, now)
    elif op == "remove_entity_detail":
        details = entity_details(conn, entity_id)
        details.pop(str(operation["key"]), None)
        write_entity_details(conn, entity_id, details, current_turn_id, now)
    elif op == "set_character_field":
        row = conn.execute("select 1 from characters where entity_id = ?", (entity_id,)).fetchone()
        if row is None:
            raise ValueError(f"entity is not a character: {entity_id}")
        field = str(operation["field"])
        conn.execute(f"update characters set {field} = ? where entity_id = ?", (operation["value"], entity_id))
        touch_entity(conn, entity_id, current_turn_id, now)
    else:
        raise ValueError(f"unsupported operation: {op}")


def entity_details(conn: Any, entity_id: str) -> dict[str, Any]:
    row = conn.execute("select details_json from entities where id = ?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(f"missing entity: {entity_id}")
    details = parse_json(row["details_json"], {})
    return details if isinstance(details, dict) else {}


def write_entity_details(
    conn: Any,
    entity_id: str,
    details: dict[str, Any],
    current_turn_id: str,
    now: str,
) -> None:
    conn.execute(
        "update entities set details_json = ?, updated_turn_id = ?, updated_at = ? where id = ?",
        (json.dumps(details, ensure_ascii=False, sort_keys=True), current_turn_id, now, entity_id),
    )


def touch_entity(conn: Any, entity_id: str, current_turn_id: str, now: str) -> None:
    conn.execute(
        "update entities set updated_turn_id = ?, updated_at = ? where id = ?",
        (current_turn_id, now, entity_id),
    )


def table_exists(conn: Any, table: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name = ?", (table,)).fetchone()
    return bool(row)
