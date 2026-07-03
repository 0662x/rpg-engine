from __future__ import annotations

import sqlite3
import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..campaign import Campaign, load_campaign, load_yaml_file
from ..content_types import ContentRuntime, ContentTypeSpec, get_default_registry
from ..content_types.registry import ContentRegistry
from ..content_validation import validate_content_delta
from ..db import connect, init_database, utc_now
from .lock import (
    build_package_lock,
    package_lock_path,
    read_effective_package_lock,
    store_package_lock_meta,
    validate_lock_for_source,
)
from .merge import (
    PackageFieldDiff,
    PackageDryRunResult,
    PackageRecordMerge,
    dry_run_package_upgrade,
    record_effective_action,
    record_mutating_diffs,
)
from ..projection_service import ProjectionService
from ..projections import mark_projections_dirty
from ..render import parse_json
from ..save import next_turn_id
from ..unit_of_work import UnitOfWork
from ..write_guard import add_generated_write_guards


MANIFEST_CANDIDATES = ("package.yaml", "package.yml", "campaign.yaml")


@dataclass(frozen=True)
class PackageMigration:
    id: str
    path: Path
    checksum: str
    from_package_version: str
    to_package_version: str
    operations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class PackageSource:
    root: Path
    manifest_path: Path
    manifest: dict[str, Any]
    records_by_type: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    files_by_type: dict[str, list[str]] = field(default_factory=dict)
    migrations: tuple[PackageMigration, ...] = ()

    @property
    def package_id(self) -> str:
        return str(self.manifest.get("package_id") or self.manifest.get("id") or self.root.name)

    @property
    def package_version(self) -> str:
        return str(self.manifest.get("package_version") or self.manifest.get("version") or "")


@dataclass(frozen=True)
class PackageValidationResult:
    package_id: str
    package_version: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    record_counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class PackageDiffResult:
    package_id: str
    package_version: str
    target_name: str
    validation: PackageValidationResult
    type_results: tuple[PackageDryRunResult, ...] = ()

    @property
    def ok(self) -> bool:
        return self.validation.ok and all(result.ok for result in self.type_results)


@dataclass(frozen=True)
class PackageApplyResult:
    package_id: str
    package_version: str
    target_name: str
    turn_id: str | None
    lock_path: Path
    counts: dict[str, int] = field(default_factory=dict)
    records_by_type: dict[str, list[str]] = field(default_factory=dict)
    noop: bool = False

    @property
    def total_changes(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class PackageAdoptionResult:
    package_id: str
    package_version: str
    target_name: str
    diff: PackageDiffResult
    lock_path: Path | None = None
    adopted: bool = False

    @property
    def drift_records(self) -> int:
        return package_diff_drift_count(self.diff)

    @property
    def conflicts(self) -> int:
        return sum(len(record.conflicts) for result in self.diff.type_results for record in result.records)

    @property
    def ok(self) -> bool:
        return self.diff.validation.ok and self.drift_records == 0 and self.conflicts == 0


@dataclass(frozen=True)
class PackageInstallResult:
    package_id: str
    package_version: str
    target_dir: Path
    lock_path: Path
    records: dict[str, int] = field(default_factory=dict)


def load_package_source(
    package_dir: str | Path,
    *,
    registry: ContentRegistry | None = None,
) -> PackageSource:
    registry = registry or get_default_registry()
    root = Path(package_dir).expanduser().resolve()
    manifest_path = first_existing_manifest(root)
    manifest = load_yaml_file(manifest_path)
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    files_by_type: dict[str, list[str]] = {}
    content = manifest.get("content", {})
    if not isinstance(content, dict):
        content = {}
    for spec in registry.seed_specs():
        if not spec.campaign_key or not spec.yaml_key or spec.campaign_key not in content:
            continue
        records: list[dict[str, Any]] = []
        files: list[str] = []
        for path in content_paths(root, content[spec.campaign_key]):
            files.append(str(path.relative_to(root)) if path.is_relative_to(root) else str(path))
            data = load_yaml_file(path)
            raw_records = data.get(spec.yaml_key, [])
            if isinstance(raw_records, list):
                records.extend(item for item in raw_records if isinstance(item, dict))
        records_by_type[spec.name] = records
        files_by_type[spec.name] = files
    return PackageSource(
        root=root,
        manifest_path=manifest_path,
        manifest=manifest,
        records_by_type=records_by_type,
        files_by_type=files_by_type,
        migrations=load_package_migrations(root, manifest),
    )


def validate_package_source(
    source: PackageSource,
    *,
    registry: ContentRegistry | None = None,
) -> PackageValidationResult:
    registry = registry or get_default_registry()
    errors: list[str] = []
    warnings: list[str] = []
    if not source.package_id.strip():
        errors.append("manifest.id or manifest.package_id is required")
    if not source.package_version.strip():
        errors.append("manifest.package_version or manifest.version is required")
    if "content_schema_version" in source.manifest and not str(source.manifest.get("content_schema_version", "")).strip():
        errors.append("manifest.content_schema_version must be non-empty string")
    content = source.manifest.get("content", {})
    if not isinstance(content, dict):
        errors.append("manifest.content must be object")
    seen_global: dict[str, str] = {}
    record_counts: dict[str, int] = {}
    for spec in registry.seed_specs():
        records = source.records_by_type.get(spec.name, [])
        if not records:
            continue
        record_counts[spec.name] = len(records)
        seen_type: set[str] = set()
        for index, record in enumerate(records):
            path = f"{spec.name}[{index}]"
            record_id = safe_record_id(spec, record)
            if record_id:
                if record_id in seen_type:
                    errors.append(f"{path}.id: duplicate record id {record_id}")
                seen_type.add(record_id)
                if record_id in seen_global and seen_global[record_id] != spec.name:
                    errors.append(f"{path}.id: also appears in {seen_global[record_id]}")
                seen_global[record_id] = spec.name
            if spec.validate_record:
                errors.extend(f"{path}.{error}" for error in spec.validate_record(record))
    errors.extend(validate_package_migrations(source))
    if not record_counts:
        warnings.append("package has no registered content records")
    return PackageValidationResult(
        package_id=source.package_id,
        package_version=source.package_version,
        errors=tuple(dedupe(errors)),
        warnings=tuple(dedupe(warnings)),
        record_counts=record_counts,
    )


def diff_package_against_campaign(
    conn: sqlite3.Connection,
    source: PackageSource,
    *,
    target_name: str,
    campaign: Campaign | None = None,
    require_lock: bool = False,
    registry: ContentRegistry | None = None,
) -> PackageDiffResult:
    registry = registry or get_default_registry()
    validation = validate_package_source(source, registry=registry)
    lock_errors: list[str] = []
    lock_warnings: list[str] = []
    if campaign is not None:
        lock_errors, lock_warnings = validate_lock_for_source(
            read_effective_package_lock(campaign, conn),
            source,
            require_lock=require_lock,
        )
    db_errors = validate_package_database_refs(conn, source, registry)
    if db_errors or lock_errors or lock_warnings:
        validation = PackageValidationResult(
            package_id=validation.package_id,
            package_version=validation.package_version,
            errors=(*validation.errors, *tuple(lock_errors), *tuple(db_errors)),
            warnings=(*validation.warnings, *tuple(lock_warnings)),
            record_counts=validation.record_counts,
        )
    type_results: list[PackageDryRunResult] = []
    for spec in registry.seed_specs():
        incoming = source.records_by_type.get(spec.name, [])
        if not incoming:
            continue
        current = current_records_for_spec(conn, spec, incoming, registry=registry)
        dry_run = dry_run_package_upgrade(spec, current, incoming)
        type_results.append(apply_migration_authorizations(source, spec.name, dry_run))
    return PackageDiffResult(
        package_id=source.package_id,
        package_version=source.package_version,
        target_name=target_name,
        validation=validation,
        type_results=tuple(type_results),
    )


def reconcile_package_adoption(
    campaign: Campaign,
    conn: sqlite3.Connection,
    source: PackageSource,
    *,
    registry: ContentRegistry | None = None,
) -> PackageAdoptionResult:
    registry = registry or get_default_registry()
    diff = diff_package_against_campaign(
        conn,
        source,
        target_name=campaign.name,
        campaign=campaign,
        require_lock=False,
        registry=registry,
    )
    return PackageAdoptionResult(
        package_id=source.package_id,
        package_version=source.package_version,
        target_name=campaign.name,
        diff=diff,
    )


def adopt_existing_package_lock(
    campaign: Campaign,
    conn: sqlite3.Connection,
    source: PackageSource,
    *,
    force: bool = False,
    registry: ContentRegistry | None = None,
) -> PackageAdoptionResult:
    path = package_lock_path(campaign)
    if path.exists() and not force:
        raise FileExistsError(f"package-lock already exists: {path}")
    result = reconcile_package_adoption(campaign, conn, source, registry=registry)
    if not result.ok:
        raise ValueError(render_package_adoption(result))
    lock = build_package_lock(source)
    store_package_lock_meta(conn, lock)
    mark_projections_dirty(conn, ["package_lock"], turn_id=current_turn_id(conn))
    conn.commit()
    lock_path = sync_package_lock_projection(campaign, conn)
    return PackageAdoptionResult(
        package_id=source.package_id,
        package_version=source.package_version,
        target_name=campaign.name,
        diff=result.diff,
        lock_path=lock_path,
        adopted=True,
    )


def install_package_to_new_campaign(
    source: PackageSource,
    target_dir: str | Path,
    *,
    force: bool = False,
) -> PackageInstallResult:
    validation = validate_package_source(source)
    if not validation.ok:
        raise ValueError("Invalid package:\n" + "\n".join(f"- {error}" for error in validation.errors))
    target = Path(target_dir).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        if not force:
            raise FileExistsError(f"target directory is not empty: {target}")
        shutil.rmtree(target)
    if target.exists() and not target.is_dir():
        raise FileExistsError(f"target exists and is not a directory: {target}")
    if target.resolve() == source.root.resolve():
        raise ValueError("target directory must be different from package source")
    if not target.exists():
        shutil.copytree(source.root, target)
    else:
        shutil.copytree(source.root, target, dirs_exist_ok=True)
    campaign = load_campaign(target)
    init_database(campaign, force=True)
    installed_source = load_package_source(target)
    lock = build_package_lock(installed_source)
    with connect(campaign) as conn:
        store_package_lock_meta(conn, lock)
        mark_projections_dirty(conn, ["package_lock"], turn_id=current_turn_id(conn))
        conn.commit()
        lock_path = sync_package_lock_projection(campaign, conn)
    return PackageInstallResult(
        package_id=installed_source.package_id,
        package_version=installed_source.package_version,
        target_dir=target,
        lock_path=lock_path,
        records=validation.record_counts,
    )


def apply_package_upgrade(
    campaign: Campaign,
    conn: sqlite3.Connection,
    source: PackageSource,
    *,
    registry: ContentRegistry | None = None,
) -> PackageApplyResult:
    registry = registry or get_default_registry()
    diff = diff_package_against_campaign(
        conn,
        source,
        target_name=campaign.name,
        campaign=campaign,
        require_lock=True,
        registry=registry,
    )
    if not diff.ok:
        raise ValueError(render_package_diff(diff))
    operations = package_apply_operations(diff)
    existing_lock = read_effective_package_lock(campaign, conn)
    previously_applied = existing_lock.applied_migrations if existing_lock else ()
    previous_migration_checksums = dict(existing_lock.applied_migration_checksums) if existing_lock else {}
    pending_migrations = tuple(migration for migration in source.migrations if migration.id not in previously_applied)
    migration_checksums = {
        **previous_migration_checksums,
        **{migration.id: migration.checksum for migration in pending_migrations},
    }
    new_lock = build_package_lock(
        source,
        applied_migrations=(*previously_applied, *(migration.id for migration in pending_migrations)),
        applied_migration_checksums=migration_checksums,
    )
    if not operations and not pending_migrations:
        store_package_lock_meta(conn, new_lock)
        conn.commit()
        lock_path = sync_package_lock_projection(campaign, conn)
        return PackageApplyResult(
            package_id=source.package_id,
            package_version=source.package_version,
            target_name=campaign.name,
            turn_id=None,
            lock_path=lock_path,
            noop=True,
        )

    now = utc_now()
    turn_id = next_turn_id(conn)
    summary = f"Package upgrade applied: {source.package_id} {source.package_version}"
    guard_payload = add_generated_write_guards(
        conn,
        {
            "title": "package upgrade",
            "description": summary,
            "intent": "package_upgrade",
            "package_id": source.package_id,
            "package_version": source.package_version,
            "package_fingerprint": new_lock.fingerprint,
            "operation_count": len(operations),
            "turn_id": turn_id,
        },
        prefix="package-upgrade",
    )
    counts: dict[str, int] = {}
    records_by_type: dict[str, list[str]] = {}
    meta = {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}
    event_record: dict[str, Any] | None = None
    uow = UnitOfWork(campaign, conn, guard_payload)
    try:
        existing_turn = uow.begin()
        if existing_turn:
            return PackageApplyResult(
                package_id=source.package_id,
                package_version=source.package_version,
                target_name=campaign.name,
                turn_id=existing_turn,
                lock_path=package_lock_path(campaign),
                noop=True,
            )
        uow.insert_turn(
            (
                turn_id,
                "package_upgrade",
                summary,
                "package_upgrade",
                meta.get("current_time_block"),
                meta.get("current_time_block"),
                meta.get("current_location_id"),
                meta.get("current_location_id"),
                summary,
                1,
                now,
            )
        )
        applied_migration_ids, migrated_entity_ids = apply_package_migrations(
            conn,
            pending_migrations,
            turn_id=turn_id,
            now=now,
            registry=registry,
        )
        runtime = ContentRuntime(campaign=campaign, conn=conn, turn_id=turn_id, now=now)
        specs_by_name = {spec.name: spec for spec in registry.seed_specs()}
        for content_type, record_id, record in operations:
            spec = specs_by_name[content_type]
            if not spec.upsert:
                raise ValueError(f"content type cannot be applied: {content_type}")
            upsert_record = dict(record)
            upsert_record.setdefault("updated_turn_id", turn_id)
            spec.upsert(runtime, upsert_record)
            counts[content_type] = counts.get(content_type, 0) + 1
            records_by_type.setdefault(content_type, []).append(record_id)
        event_id = f"event:{turn_id.split(':', 1)[1]}:001"
        payload = {
            "package_id": source.package_id,
            "package_version": source.package_version,
            "package_fingerprint": new_lock.fingerprint,
            "counts": counts,
            "records": records_by_type,
            "applied_migrations": applied_migration_ids,
        }
        conn.execute(
            """
            insert into events
            (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                turn_id,
                str(meta.get("current_time_block", "")),
                "package_upgrade",
                "Package upgrade applied",
                summary,
                json_dumps(payload),
                "package_upgrade",
                now,
            ),
        )
        event_record = {
            "event_id": event_id,
            "turn_id": turn_id,
            "game_time": str(meta.get("current_time_block", "")),
            "type": "package_upgrade",
            "title": "Package upgrade applied",
            "summary": summary,
            "payload": payload,
            "source": "package_upgrade",
            "created_at": now,
        }
        conn.execute(
            "insert into meta(key, value) values('current_turn_id', ?) on conflict(key) do update set value=excluded.value",
            (turn_id,),
        )
        conn.execute(
            "insert into meta(key, value) values('last_saved_at', ?) on conflict(key) do update set value=excluded.value",
            (now,),
        )
        conn.execute(
            "insert into meta(key, value) values('package_version', ?) on conflict(key) do update set value=excluded.value",
            (source.package_version,),
        )
        store_package_lock_meta(conn, new_lock)
        mark_projections_dirty(conn, ["package_lock"], turn_id=turn_id)
        search_entity_ids = [
            record_id
            for content_type, values in records_by_type.items()
            if content_type != "route"
            for record_id in values
        ]
        search_entity_ids.extend(migrated_entity_ids)
        uow.mark_standard_projections(
            turn_id=turn_id,
            event_records=[event_record] if event_record else [],
            changed_entity_ids=search_entity_ids,
        )
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    uow.finalize_artifacts()
    lock_path = sync_package_lock_projection(campaign, conn)
    return PackageApplyResult(
        package_id=source.package_id,
        package_version=source.package_version,
        target_name=campaign.name,
        turn_id=turn_id,
        lock_path=lock_path,
        counts=counts,
        records_by_type=records_by_type,
    )


def sync_package_lock_projection(campaign: Campaign, conn: sqlite3.Connection) -> Path:
    report = ProjectionService(campaign, conn).refresh(
        names=["package_lock"],
        dirty_only=False,
        profile="package_lock:maintenance_projection",
        commit_policy="caller_committed_required",
    )
    item = report.item("package_lock")
    if item is None or item.status != "clean":
        error = item.error if item and item.error else "package lock projection failed"
        raise OSError(error)
    if not item.artifacts:
        raise ValueError("package lock projection did not produce an artifact")
    return Path(item.artifacts[0])


def current_turn_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("select value from meta where key='current_turn_id'").fetchone()
    return str(row[0]) if row else None


def package_apply_operations(diff: PackageDiffResult) -> list[tuple[str, str, dict[str, Any]]]:
    operations: list[tuple[str, str, dict[str, Any]]] = []
    for type_result in diff.type_results:
        for record in type_result.records:
            if not record.ok or record.merged is None:
                continue
            if record.action == "create":
                operations.append((type_result.content_type, record.record_id, record.merged))
            elif record.action == "update" and record_mutating_diffs(record):
                operations.append((type_result.content_type, record.record_id, record.merged))
    return operations


def apply_migration_authorizations(
    source: PackageSource,
    content_type: str,
    dry_run: PackageDryRunResult,
) -> PackageDryRunResult:
    authorizations = conflict_field_authorizations(source, content_type)
    if not authorizations:
        return dry_run
    records: list[PackageRecordMerge] = []
    for record in dry_run.records:
        if not record.conflicts or record.merged is None:
            records.append(record)
            continue
        merged = dict(record.merged)
        diffs = list(record.diffs)
        conflicts: list[PackageFieldDiff] = []
        for conflict in record.conflicts:
            if (record.record_id, conflict.field) not in authorizations:
                conflicts.append(conflict)
                continue
            merged[conflict.field] = conflict.incoming
            diffs.append(
                PackageFieldDiff(
                    field=conflict.field,
                    ownership="explicit-migration",
                    action="package-update",
                    current=conflict.current,
                    incoming=conflict.incoming,
                    merged=conflict.incoming,
                    message="authorized by explicit package migration",
                )
            )
        records.append(
            PackageRecordMerge(
                record_id=record.record_id,
                action=record.action,
                merged=merged,
                diffs=tuple(diffs),
                conflicts=tuple(conflicts),
            )
        )
    return PackageDryRunResult(content_type=dry_run.content_type, records=tuple(records))


def conflict_field_authorizations(source: PackageSource, content_type: str) -> set[tuple[str, str]]:
    authorizations: set[tuple[str, str]] = set()
    for migration in source.migrations:
        for operation in migration.operations:
            if str(operation.get("type")) != "update_conflict_field":
                continue
            if str(operation.get("content_type") or "") != content_type:
                continue
            record_id = str(operation.get("record_id") or operation.get("entity_id") or "")
            field = str(operation.get("field") or "")
            if record_id and field:
                authorizations.add((record_id, field))
    return authorizations


def apply_package_migrations(
    conn: sqlite3.Connection,
    migrations: tuple[PackageMigration, ...],
    *,
    turn_id: str,
    now: str,
    registry: ContentRegistry,
) -> tuple[list[str], list[str]]:
    if not migrations:
        return [], []
    conn.execute("pragma defer_foreign_keys = on")
    applied: list[str] = []
    changed_entity_ids: list[str] = []
    for migration in migrations:
        for operation in migration.operations:
            changed_entity_ids.extend(
                apply_package_migration_operation(conn, operation, turn_id=turn_id, now=now, registry=registry)
            )
        applied.append(migration.id)
    return applied, list(dict.fromkeys(changed_entity_ids))


def apply_package_migration_operation(
    conn: sqlite3.Connection,
    operation: dict[str, Any],
    *,
    turn_id: str,
    now: str,
    registry: ContentRegistry,
) -> list[str]:
    op_type = str(operation.get("type") or "")
    if op_type == "rename_alias":
        entity_id = required_operation_value(operation, "entity_id")
        old_alias = required_operation_value(operation, "from")
        new_alias = required_operation_value(operation, "to")
        conn.execute("delete from aliases where entity_id = ? and alias = ?", (entity_id, old_alias))
        conn.execute(
            "insert or ignore into aliases(alias, entity_id, kind) values (?, ?, 'name')",
            (new_alias, entity_id),
        )
        conn.execute("update entities set updated_turn_id = ?, updated_at = ? where id = ?", (turn_id, now, entity_id))
        return [entity_id]
    if op_type == "rename_entity":
        old_id = required_operation_value(operation, "from")
        new_id = required_operation_value(operation, "to")
        rename_entity_id(conn, old_id, new_id)
        conn.execute("update entities set updated_turn_id = ?, updated_at = ? where id = ?", (turn_id, now, new_id))
        return [old_id, new_id]
    if op_type == "delete_record":
        content_type = required_operation_value(operation, "content_type")
        record_id = required_operation_value(operation, "record_id")
        delete_package_record(conn, content_type, record_id, registry=registry)
        return [record_id] if content_type != "route" else []
    if op_type == "update_conflict_field":
        content_type = required_operation_value(operation, "content_type")
        record_id = str(operation.get("record_id") or operation.get("entity_id") or "")
        field = required_operation_value(operation, "field")
        if not record_id:
            raise ValueError("update_conflict_field.record_id: required")
        update_conflict_field(conn, content_type, record_id, field, operation.get("value"), turn_id=turn_id, now=now)
        return [record_id] if content_type != "route" else []
    raise ValueError(f"unsupported package migration operation: {op_type}")


def required_operation_value(operation: dict[str, Any], key: str) -> str:
    value = operation.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{operation.get('type', '<operation>')}.{key}: required")
    return value


def rename_entity_id(conn: sqlite3.Connection, old_id: str, new_id: str) -> None:
    if not conn.execute("select 1 from entities where id = ?", (old_id,)).fetchone():
        raise ValueError(f"rename_entity missing source entity: {old_id}")
    if conn.execute("select 1 from entities where id = ?", (new_id,)).fetchone():
        raise ValueError(f"rename_entity target already exists: {new_id}")
    conn.execute("update entities set id = ? where id = ?", (new_id, old_id))
    for table in ("aliases", "characters", "items", "locations", "crop_plots", "clocks", "rules", "world_settings"):
        conn.execute(f"update {table} set entity_id = ? where entity_id = ?", (new_id, old_id))
    conn.execute("update facts set subject_id = ? where subject_id = ?", (new_id, old_id))
    conn.execute("update facts set object_entity_id = ? where object_entity_id = ?", (new_id, old_id))
    conn.execute("update characters set species_id = ? where species_id = ?", (new_id, old_id))
    conn.execute("update locations set parent_id = ? where parent_id = ?", (new_id, old_id))
    conn.execute("update routes set from_location_id = ? where from_location_id = ?", (new_id, old_id))
    conn.execute("update routes set to_location_id = ? where to_location_id = ?", (new_id, old_id))
    conn.execute("update crop_plots set crop_entity_id = ? where crop_entity_id = ?", (new_id, old_id))
    conn.execute("update entities set location_id = ? where location_id = ?", (new_id, old_id))
    conn.execute("update entities set owner_id = ? where owner_id = ?", (new_id, old_id))
    conn.execute("update memory_summaries set subject_id = ? where subject_id = ?", (new_id, old_id))
    conn.execute("update context_items set item_id = ? where item_id = ?", (new_id, old_id))
    conn.execute("update fts_index set entity_id = ? where entity_id = ?", (new_id, old_id))
    for key in ("current_location_id", "player_entity_id"):
        conn.execute("update meta set value = ? where key = ? and value = ?", (new_id, key, old_id))


def delete_package_record(
    conn: sqlite3.Connection,
    content_type: str,
    record_id: str,
    *,
    registry: ContentRegistry,
) -> None:
    if content_type == "route":
        conn.execute("delete from routes where id = ?", (record_id,))
        return
    try:
        spec = registry.get(content_type)
    except KeyError:
        spec = None
    entity_type = spec.entity_type if spec else None
    if content_type in {"entity", "rule", "clock", "world_setting"} or entity_type:
        conn.execute("delete from entities where id = ?", (record_id,))
        conn.execute("delete from fts_index where entity_id = ?", (record_id,))
        return
    raise ValueError(f"delete_record unsupported content_type: {content_type}")


def update_conflict_field(
    conn: sqlite3.Connection,
    content_type: str,
    record_id: str,
    field: str,
    value: Any,
    *,
    turn_id: str,
    now: str,
) -> None:
    if content_type == "entity":
        if field == "details":
            conn.execute(
                "update entities set details_json = ?, updated_turn_id = ?, updated_at = ? where id = ?",
                (json_dumps(value if value is not None else {}), turn_id, now, record_id),
            )
            return
        if field == "type":
            conn.execute(
                "update entities set type = ?, updated_turn_id = ?, updated_at = ? where id = ?",
                (str(value), turn_id, now, record_id),
            )
            return
    raise ValueError(f"update_conflict_field unsupported field: {content_type}.{field}")


def package_diff_drift_count(diff: PackageDiffResult) -> int:
    count = 0
    for type_result in diff.type_results:
        for record in type_result.records:
            if record.conflicts:
                count += 1
            elif record_effective_action(record) != "unchanged":
                count += 1
    return count


def render_package_adoption(result: PackageAdoptionResult) -> str:
    status = "OK" if result.ok else "FAILED"
    lines = [
        "# Package Adoption",
        "",
        f"- status: `{status}`",
        f"- package: `{result.package_id}`",
        f"- target: `{result.target_name}`",
        f"- version: `{result.package_version}`",
        f"- drift_records: `{result.drift_records}`",
        f"- conflicts: `{result.conflicts}`",
    ]
    if result.lock_path:
        lines.append(f"- lock: `{result.lock_path}`")
    lines.append(f"- adopted: `{'yes' if result.adopted else 'no'}`")
    if not result.ok:
        lines.extend(
            [
                "",
                "## Reconcile Diff",
                "",
                render_package_diff(result.diff).rstrip(),
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_package_install(result: PackageInstallResult) -> str:
    lines = [
        "# Package Install",
        "",
        "- status: `OK`",
        f"- package: `{result.package_id}`",
        f"- version: `{result.package_version}`",
        f"- target: `{result.target_dir}`",
        f"- lock: `{result.lock_path}`",
        "",
        "## Records",
        "",
        "| Content Type | Records |",
        "|--------------|---------|",
    ]
    for name, count in sorted(result.records.items()):
        lines.append(f"| `{name}` | {count} |")
    return "\n".join(lines).rstrip() + "\n"


def render_package_apply(result: PackageApplyResult, *, backup_id: str | None = None) -> str:
    lines = [
        "# Package Apply",
        "",
        "- status: `OK`",
        f"- package: `{result.package_id}`",
        f"- target: `{result.target_name}`",
        f"- version: `{result.package_version}`",
    ]
    if backup_id:
        lines.append(f"- backup: `{backup_id}`")
    if result.turn_id:
        lines.append(f"- turn: `{result.turn_id}`")
    lines.append(f"- lock: `{result.lock_path}`")
    if result.noop:
        lines.append("- changes: `0`")
        return "\n".join(lines) + "\n"
    lines.extend(["", "## Summary", "", "| Content Type | Records |", "|--------------|---------|"])
    for name, count in sorted(result.counts.items()):
        lines.append(f"| `{name}` | {count} |")
    return "\n".join(lines) + "\n"


def validate_package_database_refs(
    conn: sqlite3.Connection,
    source: PackageSource,
    registry: ContentRegistry,
) -> list[str]:
    pseudo_delta: dict[str, Any] = {
        "title": "package dry-run preflight",
        "description": f"validate package {source.package_id} against target database",
    }
    for spec in registry.delta_specs():
        records = source.records_by_type.get(spec.name, [])
        if records and spec.delta_key:
            pseudo_delta[spec.delta_key] = records
    if len(pseudo_delta) <= 2:
        return []
    result = validate_content_delta(pseudo_delta, conn, registry=registry)
    return [f"database-ref.{error}" for error in result.errors]


def load_package_migrations(root: Path, manifest: dict[str, Any]) -> tuple[PackageMigration, ...]:
    raw = manifest.get("migrations", [])
    if raw is None:
        return ()
    if not isinstance(raw, list):
        return ()
    migrations: list[PackageMigration] = []
    for item in raw:
        migration_path = migration_entry_path(root, item)
        if migration_path is None:
            continue
        data = load_yaml_file(migration_path)
        file_bytes = migration_path.read_bytes()
        operations = data.get("operations", [])
        if not isinstance(operations, list):
            operations = []
        migrations.append(
            PackageMigration(
                id=str(data.get("id") or ""),
                path=migration_path,
                checksum=hashlib.sha256(file_bytes).hexdigest(),
                from_package_version=str(data.get("from_package_version") or ""),
                to_package_version=str(data.get("to_package_version") or ""),
                operations=tuple(item for item in operations if isinstance(item, dict)),
            )
        )
    return tuple(migrations)


def migration_entry_path(root: Path, item: Any) -> Path | None:
    if isinstance(item, str):
        value = item
    elif isinstance(item, dict):
        value = str(item.get("path") or "")
    else:
        return None
    if not value.strip():
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def validate_package_migrations(source: PackageSource) -> list[str]:
    errors: list[str] = []
    raw = source.manifest.get("migrations", [])
    if raw is not None and not isinstance(raw, list):
        errors.append("manifest.migrations must be array")
    seen: set[str] = set()
    supported_operations = {"rename_entity", "rename_alias", "delete_record", "update_conflict_field"}
    for index, migration in enumerate(source.migrations):
        path = f"migrations[{index}]"
        if not migration.id.strip():
            errors.append(f"{path}.id: required non-empty string")
        elif migration.id in seen:
            errors.append(f"{path}.id: duplicate migration id {migration.id}")
        seen.add(migration.id)
        if not migration.from_package_version.strip():
            errors.append(f"{path}.from_package_version: required non-empty string")
        if not migration.to_package_version.strip():
            errors.append(f"{path}.to_package_version: required non-empty string")
        if not migration.operations:
            errors.append(f"{path}.operations: must contain at least one operation")
        for op_index, operation in enumerate(migration.operations):
            op_type = str(operation.get("type") or "")
            if op_type not in supported_operations:
                errors.append(f"{path}.operations[{op_index}].type: unsupported operation {op_type or '<missing>'}")
            if not operation.get("reason"):
                errors.append(f"{path}.operations[{op_index}].reason: required")
            op_path = f"{path}.operations[{op_index}]"
            errors.extend(validate_migration_operation_shape(operation, op_path))
    return errors


def validate_migration_operation_shape(operation: dict[str, Any], path: str) -> list[str]:
    op_type = str(operation.get("type") or "")
    required_by_type = {
        "rename_entity": ("from", "to"),
        "rename_alias": ("entity_id", "from", "to"),
        "delete_record": ("content_type", "record_id"),
        "update_conflict_field": ("content_type", "field"),
    }
    errors: list[str] = []
    for key in required_by_type.get(op_type, ()):
        if not isinstance(operation.get(key), str) or not str(operation.get(key, "")).strip():
            errors.append(f"{path}.{key}: required")
    if op_type == "update_conflict_field" and not (operation.get("record_id") or operation.get("entity_id")):
        errors.append(f"{path}.record_id: required")
    return errors


def current_records_for_spec(
    conn: sqlite3.Connection,
    spec: ContentTypeSpec,
    incoming_records: list[dict[str, Any]],
    *,
    registry: ContentRegistry,
) -> list[dict[str, Any]]:
    incoming_ids = {safe_record_id(spec, record) for record in incoming_records}
    incoming_ids.discard("")
    if not incoming_ids:
        return []
    if spec.name == "entity":
        excluded_types = {item.entity_type for item in registry.all() if item.entity_type}
        return [
            record
            for record in current_entity_records(conn, incoming_ids)
            if str(record.get("type")) not in excluded_types
        ]
    if spec.name == "rule":
        return current_rule_records(conn, incoming_ids)
    if spec.name == "clock":
        return current_clock_records(conn, incoming_ids)
    if spec.name == "route":
        return current_route_records(conn, incoming_ids)
    if spec.name == "world_setting":
        return current_world_setting_records(conn, incoming_ids)
    return []


def current_entity_records(conn: sqlite3.Connection, record_ids: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = conn.execute(
        f"select * from entities where id in ({placeholders}) order by id",
        tuple(sorted(record_ids)),
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = compact_record(
            {
                "id": row["id"],
                "type": row["type"],
                "name": row["name"],
                "status": row["status"],
                "visibility": row["visibility"],
                "location_id": row["location_id"],
                "owner_id": row["owner_id"],
                "summary": row["summary"],
                "details": parse_json(row["details_json"], {}),
                "aliases": aliases_for(conn, row["id"]),
            }
        )
        item = conn.execute("select * from items where entity_id = ?", (row["id"],)).fetchone()
        if item:
            record["item"] = compact_record(
                {
                    "category": item["category"],
                    "quantity": item["quantity"],
                    "unit": item["unit"],
                    "quality": item["quality"],
                    "durability_current": item["durability_current"],
                    "durability_max": item["durability_max"],
                    "stackable": bool(item["stackable"]),
                    "equipped_slot": item["equipped_slot"],
                    "properties": parse_json(item["properties_json"], {}),
                }
            )
        character = conn.execute("select * from characters where entity_id = ?", (row["id"],)).fetchone()
        if character:
            record["character"] = compact_record(
                {
                    "species_id": character["species_id"],
                    "role": character["role"],
                    "attitude": character["attitude"],
                    "trust": character["trust"],
                    "health_state": character["health_state"],
                    "stress": parse_json(character["stress_json"], {}),
                    "consequences": parse_json(character["consequences_json"], []),
                    "goals": parse_json(character["goals_json"], []),
                    "knowledge": parse_json(character["knowledge_json"], {}),
                }
            )
        location = conn.execute("select * from locations where entity_id = ?", (row["id"],)).fetchone()
        if location:
            record["location"] = compact_record(
                {
                    "parent_id": location["parent_id"],
                    "coord_x": location["coord_x"],
                    "coord_y": location["coord_y"],
                    "coord_z": location["coord_z"],
                    "biome": location["biome"],
                    "safety_level": location["safety_level"],
                    "discovered_turn_id": location["discovered_turn_id"],
                    "travel_minutes_from_home": location["travel_minutes_from_home"],
                    "description_short": location["description_short"],
                    "exits": parse_json(location["exits_json"], []),
                    "resources": parse_json(location["resources_json"], []),
                }
            )
        crop = conn.execute("select * from crop_plots where entity_id = ?", (row["id"],)).fetchone()
        if crop:
            record["crop_plot"] = compact_record(dict(crop))
        records.append(record)
    return records


def current_rule_records(conn: sqlite3.Connection, record_ids: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = conn.execute(
        f"""
        select r.*, e.name
        from rules r
        join entities e on e.id = r.entity_id
        where r.entity_id in ({placeholders})
        order by r.entity_id
        """,
        tuple(sorted(record_ids)),
    ).fetchall()
    return [
        compact_record(
            {
                "id": row["entity_id"],
                "name": row["name"],
                "category": row["category"],
                "scope": row["scope"],
                "statement": row["statement"],
                "examples": parse_json(row["examples_json"], []),
                "exceptions": parse_json(row["exceptions_json"], []),
                "source": row["source"],
                "locked": bool(row["locked"]),
                "aliases": aliases_for(conn, row["entity_id"]),
            }
        )
        for row in rows
    ]


def current_clock_records(conn: sqlite3.Connection, record_ids: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = conn.execute(
        f"""
        select c.*, e.name, e.summary
        from clocks c
        join entities e on e.id = c.entity_id
        where c.entity_id in ({placeholders})
        order by c.entity_id
        """,
        tuple(sorted(record_ids)),
    ).fetchall()
    return [
        compact_record(
            {
                "id": row["entity_id"],
                "name": row["name"],
                "clock_type": row["clock_type"],
                "segments_total": row["segments_total"],
                "segments_filled": row["segments_filled"],
                "visibility": row["visibility"],
                "summary": row["summary"],
                "trigger_when_full": row["trigger_when_full"],
                "tick_rules": parse_json(row["tick_rules_json"], {}),
                "last_ticked_turn_id": row["last_ticked_turn_id"],
                "aliases": aliases_for(conn, row["entity_id"]),
            }
        )
        for row in rows
    ]


def current_route_records(conn: sqlite3.Connection, record_ids: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = conn.execute(
        f"select * from routes where id in ({placeholders}) order by id",
        tuple(sorted(record_ids)),
    ).fetchall()
    return [
        compact_record(
            {
                "id": row["id"],
                "from_location_id": row["from_location_id"],
                "to_location_id": row["to_location_id"],
                "travel_minutes": row["travel_minutes"],
                "difficulty": row["difficulty"],
                "hazards": parse_json(row["hazards_json"], []),
                "requirements": parse_json(row["requirements_json"], []),
                "last_verified_turn_id": row["last_verified_turn_id"],
            }
        )
        for row in rows
    ]


def current_world_setting_records(conn: sqlite3.Connection, record_ids: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = conn.execute(
        f"""
        select ws.*, e.name, e.status
        from world_settings ws
        join entities e on e.id = ws.entity_id
        where ws.entity_id in ({placeholders})
        order by ws.entity_id
        """,
        tuple(sorted(record_ids)),
    ).fetchall()
    return [
        compact_record(
            {
                "id": row["entity_id"],
                "name": row["name"],
                "status": row["status"],
                "summary": row["summary"],
                "category": row["category"],
                "scope": row["scope"],
                "visibility": row["visibility"],
                "priority": row["priority"],
                "content": parse_json(row["content_json"], {}),
                "linked_rules": parse_json(row["linked_rules_json"], []),
                "linked_clocks": parse_json(row["linked_clocks_json"], []),
                "linked_entities": parse_json(row["linked_entities_json"], []),
                "applies_when": parse_json(row["applies_when_json"], {}),
                "source": row["source"],
                "aliases": aliases_for(conn, row["entity_id"]),
            }
        )
        for row in rows
    ]


def render_package_validation(result: PackageValidationResult) -> str:
    lines = ["OK" if result.ok else "FAILED"]
    lines.append(f"package: {result.package_id}")
    if result.package_version:
        lines.append(f"version: {result.package_version}")
    if result.record_counts:
        lines.append("")
        lines.append("| Content Type | Records |")
        lines.append("|--------------|---------|")
        for name, count in sorted(result.record_counts.items()):
            lines.append(f"| `{name}` | {count} |")
    for warning in result.warnings:
        lines.append(f"- warning: {warning}")
    for error in result.errors:
        lines.append(f"- error: {error}")
    return "\n".join(lines) + "\n"


def render_package_diff(result: PackageDiffResult) -> str:
    lines = [
        "# Package Dry Run",
        "",
        f"- status: `{'OK' if result.ok else 'FAILED'}`",
        f"- package: `{result.package_id}`",
        f"- target: `{result.target_name}`",
    ]
    if result.package_version:
        lines.append(f"- version: `{result.package_version}`")
    if result.validation.errors:
        lines.extend(["", "## Validation Errors", ""])
        lines.extend(f"- {error}" for error in result.validation.errors)
    if result.validation.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result.validation.warnings)
    lines.extend(["", "## Summary", "", "| Content Type | Records | Creates | Updates | Conflicts |", "|--------------|---------|---------|---------|-----------|"])
    for type_result in result.type_results:
        creates = sum(1 for record in type_result.records if record.action == "create")
        updates = sum(1 for record in type_result.records if record.action == "update" and record_mutating_diffs(record))
        conflicts = sum(len(record.conflicts) for record in type_result.records)
        lines.append(
            f"| `{type_result.content_type}` | {len(type_result.records)} | {creates} | {updates} | {conflicts} |"
        )
    if not result.type_results:
        lines.append("| empty | 0 | 0 | 0 | 0 |")
    for type_result in result.type_results:
        lines.extend(["", f"## {type_result.content_type}", "", "| Record | Action | Status | Changes | Conflicts |", "|--------|--------|--------|---------|-----------|"])
        for record in type_result.records:
            changed = len(record_mutating_diffs(record))
            conflicted = len(record.conflicts)
            lines.append(
                f"| `{record.record_id}` | {record_effective_action(record)} | {'ok' if record.ok else 'conflict'} | {changed} | {conflicted} |"
            )
            for conflict in record.conflicts:
                lines.append(
                    f"- conflict `{record.record_id}.{conflict.field}` ({conflict.ownership}): {conflict.message or conflict.action}"
                )
    return "\n".join(lines) + "\n"


def first_existing_manifest(root: Path) -> Path:
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Missing package directory: {root}")
    for name in MANIFEST_CANDIDATES:
        path = root / name
        if path.exists():
            return path
    raise FileNotFoundError(f"Missing package manifest: {root}/package.yaml or campaign.yaml")


def content_paths(root: Path, value: Any) -> list[Path]:
    values = value if isinstance(value, list) else [value]
    paths: list[Path] = []
    for item in values:
        path = Path(str(item)).expanduser()
        if not path.is_absolute():
            path = root / path
        paths.append(path)
    return paths


def safe_record_id(spec: ContentTypeSpec, record: dict[str, Any]) -> str:
    try:
        value = spec.record_id(record)
    except Exception:
        value = record.get("id", "")
    return str(value or "")


def aliases_for(conn: sqlite3.Connection, entity_id: str) -> list[str]:
    return [
        str(row["alias"])
        for row in conn.execute(
            "select alias from aliases where entity_id = ? and kind = 'name' order by alias",
            (entity_id,),
        ).fetchall()
    ]


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in record.items():
        if value is None:
            continue
        if value == [] or value == {}:
            continue
        compact[key] = value
    return compact


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)
