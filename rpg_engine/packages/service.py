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
from ..delta_schema import ALLOWED_ENTITY_TYPES
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
PACKAGE_AUXILIARY_CONTENT_KEYS = frozenset({"random_tables", "palettes"})
SUPPORTED_CONFLICT_FIELD_UPDATES = frozenset({("entity", "details"), ("entity", "type")})
RENAMED_ID_FIELDS = frozenset(
    {
        "id",
        "entity_id",
        "location_id",
        "owner_id",
        "species_id",
        "parent_id",
        "crop_entity_id",
        "from_location_id",
        "to_location_id",
        "source_id",
        "target_id",
    }
)
RENAMED_ID_LIST_FIELDS = frozenset({"linked_entities", "linked_rules", "linked_clocks"})
CONFLICT_FIELD_VALUE_UNSET = object()
NO_CONFLICT_FIELD_AUTH = object()


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
    raw_content = manifest.get("content", {})
    if raw_content is None:
        content = {}
    elif not isinstance(raw_content, dict):
        raise ValueError("manifest.content must be object")
    else:
        content = raw_content
    content_errors = validate_package_content_contract(root, content, registry)
    if content_errors:
        raise ValueError("; ".join(content_errors))
    for spec in registry.seed_specs():
        if not spec.campaign_key or not spec.yaml_key or spec.campaign_key not in content:
            continue
        records: list[dict[str, Any]] = []
        files: list[str] = []
        shape_errors: list[str] = []
        for path in content_paths(root, content[spec.campaign_key]):
            files.append(str(path.relative_to(root)) if path.is_relative_to(root) else str(path))
            data = load_yaml_file(path)
            raw_records = data.get(spec.yaml_key) if isinstance(data, dict) else None
            shape_errors.extend(validate_content_document_shape(root, path, spec, data, raw_records))
            if not shape_errors and isinstance(raw_records, list):
                records.extend(item for item in raw_records if isinstance(item, dict))
        if shape_errors:
            raise ValueError("; ".join(shape_errors))
        records_by_type[spec.name] = records
        files_by_type[spec.name] = files
    for key in sorted(PACKAGE_AUXILIARY_CONTENT_KEYS):
        files_by_type[key] = [
            str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
            for path in auxiliary_content_paths(root, key, content)
        ]
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
    else:
        errors.extend(validate_package_content_contract(source.root, content, registry))
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


def validate_package_content_contract(root: Path, content: dict[str, Any], registry: ContentRegistry) -> list[str]:
    errors: list[str] = []
    allowed_keys = {spec.campaign_key for spec in registry.seed_specs() if spec.campaign_key}
    allowed_keys.update(PACKAGE_AUXILIARY_CONTENT_KEYS)
    for key, raw in content.items():
        if key not in allowed_keys:
            errors.append(f"manifest.content.{key}: unsupported content key")
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"manifest.content.{key}: entries must be non-empty paths")
                continue
            if value.startswith("~"):
                errors.append(f"manifest.content.{key}: must use relative package path, got {value}")
                continue
            path = Path(value)
            if path.is_absolute():
                errors.append(f"manifest.content.{key}: must use relative package path, got {value}")
                continue
            if ".." in path.parts:
                errors.append(f"manifest.content.{key}: path escapes package root {value}")
                continue
            candidate = root / path
            try:
                candidate.resolve().relative_to(root.resolve())
            except ValueError:
                errors.append(f"manifest.content.{key}: path escapes package root {value}")
                continue
            if not candidate.exists():
                errors.append(f"manifest.content.{key}: missing file {value}")
            elif not candidate.is_file():
                errors.append(f"manifest.content.{key}: not a file {value}")
    return errors


def auxiliary_content_paths(root: Path, key: str, content: dict[str, Any]) -> list[Path]:
    if key in content:
        paths = content_paths(root, content[key])
        if paths or key != "palettes":
            return paths
    if key != "palettes":
        return []
    palette_dir = root / "content" / "palettes"
    if not palette_dir.exists():
        return []
    try:
        palette_dir.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("package palette directory escapes package root: content/palettes") from exc
    if not palette_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(palette_dir.glob("*.yaml")):
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"package palette file escapes package root: {path}") from exc
        if path.is_file():
            files.append(path)
    return files


def validate_content_document_shape(
    root: Path,
    path: Path,
    spec: ContentTypeSpec,
    data: Any,
    raw_records: Any,
) -> list[str]:
    relative = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    if not isinstance(data, dict):
        return [f"{spec.name} {relative}: YAML document must be object"]
    if spec.yaml_key not in data:
        return [f"{spec.name} {relative}: missing {spec.yaml_key} array"]
    if not isinstance(raw_records, list):
        return [f"{spec.name} {relative}: {spec.yaml_key} must be array"]
    errors: list[str] = []
    for index, record in enumerate(raw_records):
        if not isinstance(record, dict):
            errors.append(f"{spec.name} {relative}[{index}]: record must be object")
    return errors


def diff_package_against_campaign(
    conn: sqlite3.Connection,
    source: PackageSource,
    *,
    target_name: str,
    campaign: Campaign | None = None,
    require_lock: bool = False,
    registry: ContentRegistry | None = None,
) -> PackageDiffResult:
    defer_foreign_keys_enabled = current_defer_foreign_keys(conn)
    try:
        return _diff_package_against_campaign(
            conn,
            source,
            target_name=target_name,
            campaign=campaign,
            require_lock=require_lock,
            registry=registry,
        )
    finally:
        restore_defer_foreign_keys(conn, defer_foreign_keys_enabled)


def _diff_package_against_campaign(
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
    lock = None
    if campaign is not None:
        lock = read_effective_package_lock(campaign, conn)
        lock_errors, lock_warnings = validate_lock_for_source(
            lock,
            source,
            require_lock=require_lock,
        )
    applied_migrations = set(lock.applied_migrations) if lock else set()
    pending_migrations = tuple(migration for migration in source.migrations if migration.id not in applied_migrations)
    rename_map = pending_entity_rename_map(pending_migrations)
    migration_errors = validate_pending_migration_preflight(conn, pending_migrations, registry)
    db_errors = validate_package_database_refs(conn, source, registry, migrations=pending_migrations)
    migration_warnings = pending_migration_warnings(pending_migrations)
    if db_errors or lock_errors or lock_warnings or migration_errors or migration_warnings:
        validation = PackageValidationResult(
            package_id=validation.package_id,
            package_version=validation.package_version,
            errors=(*validation.errors, *tuple(lock_errors), *tuple(migration_errors), *tuple(db_errors)),
            warnings=(*validation.warnings, *tuple(lock_warnings), *tuple(migration_warnings)),
            record_counts=validation.record_counts,
        )
    type_results: list[PackageDryRunResult] = []
    for spec in registry.seed_specs():
        incoming = source.records_by_type.get(spec.name, [])
        if not incoming:
            continue
        current = current_records_for_spec(
            conn,
            spec,
            incoming,
            registry=registry,
            extra_record_ids=pending_rename_source_ids(spec, incoming, rename_map),
        )
        current = project_pending_record_renames(current, rename_map)
        dry_run = dry_run_package_upgrade(spec, current, incoming)
        type_results.append(
            apply_migration_authorizations(source, spec.name, dry_run, migrations=pending_migrations)
        )
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
    *,
    migrations: tuple[PackageMigration, ...] | None = None,
) -> PackageDryRunResult:
    authorizations = conflict_field_authorizations(source, content_type, migrations=migrations)
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
            expected_value = authorizations.get((record.record_id, conflict.field), NO_CONFLICT_FIELD_AUTH)
            if expected_value is NO_CONFLICT_FIELD_AUTH:
                conflicts.append(conflict)
                continue
            if expected_value is not CONFLICT_FIELD_VALUE_UNSET and conflict.incoming != expected_value:
                conflicts.append(
                    PackageFieldDiff(
                        field=conflict.field,
                        ownership=conflict.ownership,
                        action=conflict.action,
                        current=conflict.current,
                        incoming=conflict.incoming,
                        merged=conflict.merged,
                        message="explicit migration value mismatch",
                    )
                )
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


def conflict_field_authorizations(
    source: PackageSource,
    content_type: str,
    *,
    migrations: tuple[PackageMigration, ...] | None = None,
) -> dict[tuple[str, str], Any]:
    authorizations: dict[tuple[str, str], Any] = {}
    selected_migrations = source.migrations if migrations is None else migrations
    for migration in selected_migrations:
        for operation in migration.operations:
            if str(operation.get("type")) != "update_conflict_field":
                continue
            if str(operation.get("content_type") or "") != content_type:
                continue
            record_id = str(operation.get("record_id") or operation.get("entity_id") or "")
            field = str(operation.get("field") or "")
            if record_id and field and is_supported_conflict_field_update(content_type, field):
                authorizations[(record_id, field)] = (
                    operation["value"] if "value" in operation else CONFLICT_FIELD_VALUE_UNSET
                )
    return authorizations


def pending_migration_warnings(migrations: tuple[PackageMigration, ...]) -> list[str]:
    warnings: list[str] = []
    for migration in migrations:
        for operation in migration.operations:
            op_type = str(operation.get("type") or "")
            if op_type == "rename_entity":
                warnings.append(
                    "pending migration "
                    f"{migration.id}: rename_entity {operation.get('from', '')} -> {operation.get('to', '')}"
                )
            elif op_type == "delete_record":
                warnings.append(
                    "pending migration "
                    f"{migration.id}: delete_record {operation.get('content_type', '')}.{operation.get('record_id', '')}"
                )
            elif op_type == "update_conflict_field":
                record_id = str(operation.get("record_id") or operation.get("entity_id") or "")
                warnings.append(
                    "pending migration "
                    f"{migration.id}: update_conflict_field "
                    f"{operation.get('content_type', '')}.{operation.get('field', '')} {record_id}"
                )
    return warnings


def validate_pending_migration_preflight(
    conn: sqlite3.Connection,
    migrations: tuple[PackageMigration, ...],
    registry: ContentRegistry,
) -> list[str]:
    if not migrations:
        return []
    errors: list[str] = []
    defer_foreign_keys_enabled = current_defer_foreign_keys(conn)
    conn.execute("savepoint package_migration_preflight")
    try:
        apply_package_migrations(conn, migrations, turn_id=current_turn_id(conn) or "turn:seed", now=utc_now(), registry=registry)
        violations = conn.execute("pragma foreign_key_check").fetchall()
        if violations:
            errors.append("pending migration preflight failed: foreign key constraint failed")
    except Exception as exc:
        errors.append(f"pending migration preflight failed: {exc}")
    finally:
        conn.execute("rollback to package_migration_preflight")
        conn.execute("release package_migration_preflight")
        restore_defer_foreign_keys(conn, defer_foreign_keys_enabled)
    return errors


def current_defer_foreign_keys(conn: sqlite3.Connection) -> bool:
    row = conn.execute("pragma defer_foreign_keys").fetchone()
    return bool(row[0]) if row else False


def restore_defer_foreign_keys(conn: sqlite3.Connection, enabled: bool) -> None:
    conn.execute(f"pragma defer_foreign_keys = {'on' if enabled else 'off'}")


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
        if not is_supported_conflict_field_update(content_type, field):
            raise ValueError(f"update_conflict_field unsupported field: {content_type}.{field}")
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
    update_world_setting_json_refs(conn, old_id, new_id)
    update_relationship_json_refs(conn, old_id, new_id)
    for key in ("current_location_id", "player_entity_id"):
        conn.execute("update meta set value = ? where key = ? and value = ?", (new_id, key, old_id))


def update_world_setting_json_refs(conn: sqlite3.Connection, old_id: str, new_id: str) -> None:
    for row in conn.execute(
        "select entity_id, linked_rules_json, linked_clocks_json, linked_entities_json from world_settings"
    ).fetchall():
        updates: dict[str, str] = {}
        for column in ("linked_rules_json", "linked_clocks_json", "linked_entities_json"):
            current = parse_json(row[column], [])
            updated = replace_json_refs(current, old_id, new_id)
            if updated != current:
                updates[column] = json_dumps(updated)
        if not updates:
            continue
        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(
            f"update world_settings set {assignments} where entity_id = ?",
            (*updates.values(), row["entity_id"]),
        )


def update_relationship_json_refs(conn: sqlite3.Connection, old_id: str, new_id: str) -> None:
    rows = conn.execute("select id, details_json from entities where type = 'relationship'").fetchall()
    for row in rows:
        details = parse_json(row["details_json"], {})
        if not isinstance(details, dict):
            continue
        updated = replace_json_refs(details, old_id, new_id)
        if updated != details:
            conn.execute("update entities set details_json = ? where id = ?", (json_dumps(updated), row["id"]))


def replace_json_refs(value: Any, old_id: str, new_id: str) -> Any:
    if isinstance(value, dict):
        return {key: replace_json_refs(item, old_id, new_id) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_json_refs(item, old_id, new_id) for item in value]
    if isinstance(value, str) and value == old_id:
        return new_id
    return value


def replace_json_refs_multi(value: Any, rename_map: dict[str, str]) -> Any:
    updated = value
    for old_id, new_id in rename_map.items():
        updated = replace_json_refs(updated, old_id, new_id)
    return updated


def validate_no_json_references_before_delete(conn: sqlite3.Connection, record_id: str) -> None:
    relationship_rows = conn.execute("select id, details_json from entities where type = 'relationship'").fetchall()
    for row in relationship_rows:
        details = parse_json(row["details_json"], {})
        if json_ref_contains(details, record_id):
            raise ValueError(f"delete_record blocked by relationship JSON reference: {row['id']} -> {record_id}")
    setting_rows = conn.execute(
        "select entity_id, linked_rules_json, linked_clocks_json, linked_entities_json from world_settings"
    ).fetchall()
    for row in setting_rows:
        for column in ("linked_rules_json", "linked_clocks_json", "linked_entities_json"):
            if json_ref_contains(parse_json(row[column], []), record_id):
                raise ValueError(f"delete_record blocked by world_setting JSON reference: {row['entity_id']} -> {record_id}")


def json_ref_contains(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return any(json_ref_contains(item, target) for item in value.values())
    if isinstance(value, list):
        return any(json_ref_contains(item, target) for item in value)
    return isinstance(value, str) and value == target


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
        validate_no_json_references_before_delete(conn, record_id)
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
            if value is not None and not isinstance(value, dict):
                raise ValueError("update_conflict_field.details: value must be object or null")
            conn.execute(
                "update entities set details_json = ?, updated_turn_id = ?, updated_at = ? where id = ?",
                (json_dumps(value if value is not None else {}), turn_id, now, record_id),
            )
            return
        if field == "type":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("update_conflict_field.type: value must be non-empty string")
            if value not in ALLOWED_ENTITY_TYPES:
                raise ValueError(f"update_conflict_field.type: unsupported entity type {value}")
            conn.execute(
                "update entities set type = ?, updated_turn_id = ?, updated_at = ? where id = ?",
                (value, turn_id, now, record_id),
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
    *,
    migrations: tuple[PackageMigration, ...] = (),
) -> list[str]:
    if migrations:
        defer_foreign_keys_enabled = current_defer_foreign_keys(conn)
        conn.execute("savepoint package_database_ref_preflight")
        try:
            apply_package_migrations(conn, migrations, turn_id=current_turn_id(conn) or "turn:seed", now=utc_now(), registry=registry)
            return validate_package_database_refs(conn, source, registry)
        except Exception as exc:
            return [f"database-ref.pending migration preflight failed: {exc}"]
        finally:
            conn.execute("rollback to package_database_ref_preflight")
            conn.execute("release package_database_ref_preflight")
            restore_defer_foreign_keys(conn, defer_foreign_keys_enabled)
    pseudo_delta: dict[str, Any] = {
        "title": "package dry-run preflight",
        "description": f"validate package {source.package_id} against target database",
    }
    for spec in registry.delta_specs():
        records = source.records_by_type.get(spec.name, [])
        if records and spec.delta_key:
            pseudo_delta[spec.delta_key] = records
    errors = validate_package_relationship_refs(conn, source)
    if len(pseudo_delta) <= 2:
        return errors
    source_record_ids = package_record_ids_by_type(source)
    result = validate_content_delta(
        pseudo_delta,
        conn,
        registry=registry,
        extra_created_entity_ids=package_entity_record_ids(source),
        extra_created_rule_ids=source_record_ids.get("rule", set()),
        extra_created_clock_ids=source_record_ids.get("clock", set()),
    )
    errors.extend(f"database-ref.{error}" for error in result.errors)
    return errors


def validate_package_relationship_refs(conn: sqlite3.Connection, source: PackageSource) -> list[str]:
    created_ids = {
        str(record["id"])
        for record in source.records_by_type.get("entity", [])
        if isinstance(record, dict) and record.get("id")
    }
    errors: list[str] = []
    for index, relationship in enumerate(source.records_by_type.get("relationship", [])):
        for field in ("source_id", "target_id"):
            top_level_target = relationship.get(field)
            details = relationship.get("details")
            details_target = details.get(field) if isinstance(details, dict) else None
            if top_level_target and details_target and str(top_level_target) != str(details_target):
                errors.append(f"database-ref.relationship[{index}].details.{field}: must match {field} {top_level_target}")
            for path, target in relationship_endpoint_values(index, field, top_level_target, details_target):
                if target and str(target) not in created_ids and not entity_exists_in_db(conn, str(target)):
                    errors.append(f"database-ref.{path}: missing entity {target}")
    return errors


def relationship_endpoint_values(
    index: int,
    field: str,
    top_level_target: Any,
    details_target: Any,
) -> tuple[tuple[str, Any], ...]:
    values: list[tuple[str, Any]] = []
    if top_level_target:
        values.append((f"relationship[{index}].{field}", top_level_target))
    if details_target:
        values.append((f"relationship[{index}].details.{field}", details_target))
    return tuple(values)


def entity_exists_in_db(conn: sqlite3.Connection, entity_id: str) -> bool:
    return conn.execute("select 1 from entities where id = ?", (entity_id,)).fetchone() is not None


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
    if value.startswith("~"):
        raise ValueError(f"package migration paths must be relative to package root: {value}")
    path = Path(value)
    if path.is_absolute():
        raise ValueError(f"package migration paths must be relative to package root: {value}")
    if ".." in path.parts:
        raise ValueError(f"package migration path escapes package root: {value}")
    candidate = root / path
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"package migration path escapes package root: {value}") from exc
    return candidate


def validate_package_migrations(source: PackageSource) -> list[str]:
    errors: list[str] = []
    raw = source.manifest.get("migrations", [])
    if raw is not None and not isinstance(raw, list):
        errors.append("manifest.migrations must be array")
    seen: set[str] = set()
    supported_operations = {"rename_entity", "rename_alias", "delete_record", "update_conflict_field"}
    rename_sources: dict[str, str] = {}
    rename_targets: dict[str, str] = {}
    source_record_ids = package_record_ids_by_type(source)
    source_entity_ids = package_entity_record_ids(source)
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
            if op_type == "rename_entity":
                old_id = str(operation.get("from") or "")
                new_id = str(operation.get("to") or "")
                if old_id and new_id:
                    if old_id in rename_sources:
                        errors.append(f"{op_path}.from: duplicate rename_entity source {old_id}")
                    if new_id in rename_targets:
                        errors.append(f"{op_path}.to: duplicate rename_entity target {new_id}")
                    rename_sources[old_id] = op_path
                    rename_targets[new_id] = op_path
                if old_id and old_id in source_entity_ids:
                    errors.append(f"{op_path}.from: rename_entity source id {old_id} also appears in package content")
            if op_type == "delete_record":
                content_type = str(operation.get("content_type") or "")
                record_id = str(operation.get("record_id") or "")
                if content_type and record_id and record_id in delete_collision_record_ids(source, source_record_ids, content_type):
                    errors.append(
                        f"{op_path}.record_id: delete_record collides with package content {content_type}.{record_id}"
                    )
            if op_type == "update_conflict_field" and "value" in operation:
                content_type = str(operation.get("content_type") or "")
                record_id = str(operation.get("record_id") or operation.get("entity_id") or "")
                field = str(operation.get("field") or "")
                if content_type and record_id and field and is_supported_conflict_field_update(content_type, field):
                    errors.extend(validate_explicit_conflict_value(source, operation, op_path, content_type, record_id, field))
    for chained_id in sorted(set(rename_sources) & set(rename_targets)):
        errors.append(f"{rename_sources[chained_id]}.from: rename_entity chains are not supported for {chained_id}")
    return errors


def package_record_ids_by_type(source: PackageSource) -> dict[str, set[str]]:
    return {
        content_type: {str(record["id"]) for record in records if isinstance(record, dict) and record.get("id")}
        for content_type, records in source.records_by_type.items()
    }


def package_entity_record_ids(source: PackageSource) -> set[str]:
    ids: set[str] = set()
    for content_type, records in source.records_by_type.items():
        if content_type == "route":
            continue
        for record in records:
            if isinstance(record, dict) and record.get("id"):
                ids.add(str(record["id"]))
    return ids


def delete_collision_record_ids(
    source: PackageSource,
    source_record_ids: dict[str, set[str]],
    content_type: str,
) -> set[str]:
    if content_type == "route":
        return source_record_ids.get("route", set())
    return package_entity_record_ids(source)


def validate_explicit_conflict_value(
    source: PackageSource,
    operation: dict[str, Any],
    path: str,
    content_type: str,
    record_id: str,
    field: str,
) -> list[str]:
    incoming = next(
        (
            record
            for record in source.records_by_type.get(content_type, [])
            if isinstance(record, dict) and str(record.get("id") or "") == record_id
        ),
        None,
    )
    if incoming is None:
        return [f"{path}.value: explicit update_conflict_field value requires package content {content_type}.{record_id}"]
    if field not in incoming:
        return [f"{path}.value: explicit update_conflict_field value requires package content {content_type}.{record_id}.{field}"]
    if incoming.get(field) != operation.get("value"):
        return [f"{path}.value: must match package content {content_type}.{record_id}.{field}"]
    return []


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
    if op_type == "update_conflict_field":
        content_type = str(operation.get("content_type") or "")
        field = str(operation.get("field") or "")
        if content_type and field and not is_supported_conflict_field_update(content_type, field):
            errors.append(f"{path}.field: update_conflict_field unsupported field {content_type}.{field}")
        if content_type == "entity" and field == "details" and "value" in operation:
            value = operation.get("value")
            if value is not None and not isinstance(value, dict):
                errors.append(f"{path}.value: entity.details must be object or null")
        if content_type == "entity" and field == "type" and "value" in operation:
            value = operation.get("value")
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{path}.value: entity.type must be non-empty string")
            elif value not in ALLOWED_ENTITY_TYPES:
                errors.append(f"{path}.value: unsupported entity type {value}")
    return errors


def is_supported_conflict_field_update(content_type: str, field: str) -> bool:
    return (content_type, field) in SUPPORTED_CONFLICT_FIELD_UPDATES


def current_records_for_spec(
    conn: sqlite3.Connection,
    spec: ContentTypeSpec,
    incoming_records: list[dict[str, Any]],
    *,
    registry: ContentRegistry,
    extra_record_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    incoming_ids = {safe_record_id(spec, record) for record in incoming_records}
    incoming_ids.discard("")
    incoming_ids.update(extra_record_ids or set())
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
    if spec.name == "relationship":
        return current_relationship_records(conn, incoming_ids)
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


def current_relationship_records(conn: sqlite3.Connection, record_ids: set[str]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in record_ids)
    rows = conn.execute(
        f"""
        select *
        from entities
        where type = 'relationship'
          and id in ({placeholders})
        order by id
        """,
        tuple(sorted(record_ids)),
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        details = parse_json(row["details_json"], {})
        record = {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "visibility": row["visibility"],
            "summary": row["summary"],
            "details": details,
            "aliases": aliases_for(conn, row["id"]),
        }
        for key in ("source_id", "target_id", "state", "trust", "stance", "notes"):
            if key in details:
                record[key] = details[key]
        records.append(compact_record(record))
    return records


def pending_entity_rename_map(migrations: tuple[PackageMigration, ...]) -> dict[str, str]:
    renames: dict[str, str] = {}
    targets: set[str] = set()
    for migration in migrations:
        for operation in migration.operations:
            if str(operation.get("type") or "") != "rename_entity":
                continue
            old_id = str(operation.get("from") or "")
            new_id = str(operation.get("to") or "")
            if old_id and new_id:
                if old_id in targets:
                    continue
                renames[old_id] = new_id
                targets.add(new_id)
    return renames


def pending_rename_source_ids(
    spec: ContentTypeSpec,
    incoming_records: list[dict[str, Any]],
    rename_map: dict[str, str],
) -> set[str]:
    if spec.name == "route" or not rename_map:
        return set()
    incoming_ids = {safe_record_id(spec, record) for record in incoming_records}
    return {old_id for old_id, new_id in rename_map.items() if new_id in incoming_ids}


def project_pending_record_renames(
    records: list[dict[str, Any]],
    rename_map: dict[str, str],
) -> list[dict[str, Any]]:
    if not rename_map:
        return records
    return [project_pending_renames_in_value(record, rename_map) for record in records]


def project_pending_renames_in_value(value: Any, rename_map: dict[str, str], key: str | None = None) -> Any:
    if key == "details":
        return replace_json_refs_multi(value, rename_map)
    if isinstance(value, dict):
        return {
            item_key: project_pending_renames_in_value(item_value, rename_map, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [project_pending_renames_in_value(item, rename_map, key) for item in value]
    if key in RENAMED_ID_FIELDS | RENAMED_ID_LIST_FIELDS and isinstance(value, str):
        return rename_map.get(value, value)
    return value


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
        item_text = str(item)
        if item_text.startswith("~"):
            raise ValueError(f"package content paths must be relative to package root: {item}")
        path = Path(item_text)
        if path.is_absolute():
            raise ValueError(f"package content paths must be relative to package root: {item}")
        if ".." in path.parts:
            raise ValueError(f"package content path escapes package root: {item}")
        candidate = root / path
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"package content path escapes package root: {item}") from exc
        paths.append(candidate)
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
