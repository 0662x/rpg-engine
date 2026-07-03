from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..campaign import Campaign
from ..db import utc_now


LOCK_SCHEMA_VERSION = 1
LOCK_FILENAME = "package-lock.json"
PACKAGE_LOCK_META_KEY = "package_lock_json"
PACKAGE_LOCK_FINGERPRINT_META_KEY = "package_lock_fingerprint"


@dataclass(frozen=True)
class PackageFileChecksum:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class PackageLock:
    package_id: str
    package_version: str
    content_schema_version: str
    installed_at: str
    manifest_path: str
    files: tuple[PackageFileChecksum, ...] = ()
    record_counts: dict[str, int] = field(default_factory=dict)
    applied_migrations: tuple[str, ...] = ()
    applied_migration_checksums: dict[str, str] = field(default_factory=dict)
    schema_version: int = LOCK_SCHEMA_VERSION

    @property
    def fingerprint(self) -> str:
        payload = {
            "package_id": self.package_id,
            "package_version": self.package_version,
            "content_schema_version": self.content_schema_version,
            "files": [item.__dict__ for item in self.files],
            "record_counts": self.record_counts,
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_lock_path(campaign: Campaign) -> Path:
    return campaign.root / LOCK_FILENAME


def read_package_lock(campaign: Campaign) -> PackageLock | None:
    path = package_lock_path(campaign)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return package_lock_from_dict(data)


def read_package_lock_from_meta(conn: Any) -> PackageLock | None:
    row = conn.execute("select value from meta where key = ?", (PACKAGE_LOCK_META_KEY,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(str(row["value"] if hasattr(row, "keys") else row[0]))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return package_lock_from_dict(data)


def read_effective_package_lock(campaign: Campaign, conn: Any | None = None) -> PackageLock | None:
    file_lock = read_package_lock(campaign)
    meta_lock = read_package_lock_from_meta(conn) if conn is not None else None
    if meta_lock is None:
        return file_lock
    if file_lock is None:
        return meta_lock
    if package_lock_to_dict(file_lock) != package_lock_to_dict(meta_lock):
        return meta_lock
    return file_lock


def store_package_lock_meta(conn: Any, lock: PackageLock) -> None:
    text = json.dumps(package_lock_to_dict(lock), ensure_ascii=False, sort_keys=True)
    conn.execute(
        "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
        (PACKAGE_LOCK_META_KEY, text),
    )
    conn.execute(
        "insert into meta(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
        (PACKAGE_LOCK_FINGERPRINT_META_KEY, lock.fingerprint),
    )


def write_package_lock_from_meta(campaign: Campaign, conn: Any) -> Path | None:
    lock = read_package_lock_from_meta(conn)
    if lock is None:
        path = package_lock_path(campaign)
        return path if path.exists() else None
    return write_package_lock(campaign, lock)


def package_lock_from_dict(data: dict[str, Any]) -> PackageLock:
    files = tuple(
        PackageFileChecksum(path=str(item["path"]), sha256=str(item["sha256"]), bytes=int(item["bytes"]))
        for item in data.get("files", [])
        if isinstance(item, dict)
    )
    migrations = tuple(str(item) for item in data.get("applied_migrations", []) if str(item).strip())
    migration_checksums = data.get("applied_migration_checksums", {})
    if not isinstance(migration_checksums, dict):
        migration_checksums = {}
    counts = data.get("record_counts", {})
    return PackageLock(
        package_id=str(data.get("package_id", "")),
        package_version=str(data.get("package_version", "")),
        content_schema_version=str(data.get("content_schema_version", "")),
        installed_at=str(data.get("installed_at", "")),
        manifest_path=str(data.get("manifest_path", "")),
        files=files,
        record_counts=counts if isinstance(counts, dict) else {},
        applied_migrations=migrations,
        applied_migration_checksums={str(key): str(value) for key, value in migration_checksums.items()},
        schema_version=int(data.get("schema_version", LOCK_SCHEMA_VERSION)),
    )


def write_package_lock(campaign: Campaign, lock: PackageLock) -> Path:
    path = package_lock_path(campaign)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = package_lock_to_dict(lock)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def package_lock_to_dict(lock: PackageLock) -> dict[str, Any]:
    return {
        "schema_version": lock.schema_version,
        "package_id": lock.package_id,
        "package_version": lock.package_version,
        "content_schema_version": lock.content_schema_version,
        "installed_at": lock.installed_at,
        "manifest_path": lock.manifest_path,
        "fingerprint": lock.fingerprint,
        "record_counts": dict(sorted(lock.record_counts.items())),
        "applied_migrations": list(lock.applied_migrations),
        "applied_migration_checksums": dict(sorted(lock.applied_migration_checksums.items())),
        "files": [item.__dict__ for item in lock.files],
    }


def build_package_lock(
    source: Any,
    *,
    installed_at: str | None = None,
    applied_migrations: tuple[str, ...] = (),
    applied_migration_checksums: dict[str, str] | None = None,
) -> PackageLock:
    files = tuple(package_file_checksums(source))
    record_counts = {name: len(records) for name, records in sorted(source.records_by_type.items())}
    manifest_rel = relative_to_root(source.root, source.manifest_path)
    return PackageLock(
        package_id=source.package_id,
        package_version=source.package_version,
        content_schema_version=str(source.manifest.get("content_schema_version") or "1"),
        installed_at=installed_at or utc_now(),
        manifest_path=manifest_rel,
        files=files,
        record_counts=record_counts,
        applied_migrations=applied_migrations,
        applied_migration_checksums=applied_migration_checksums or {},
    )


def package_file_checksums(source: Any) -> list[PackageFileChecksum]:
    paths: list[Path] = [source.manifest_path]
    for values in source.files_by_type.values():
        for value in values:
            path = source.root / value
            paths.append(path)
    for migration in getattr(source, "migrations", ()):
        paths.append(migration.path)
    checksums: list[PackageFileChecksum] = []
    seen: set[str] = set()
    for path in sorted(paths, key=lambda item: str(item)):
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        data = path.read_bytes()
        checksums.append(
            PackageFileChecksum(
                path=relative_to_root(source.root, path),
                sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data),
            )
        )
    return checksums


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def validate_lock_for_source(lock: PackageLock | None, source: Any, *, require_lock: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    current = build_package_lock(
        source,
        installed_at=lock.installed_at if lock else utc_now(),
        applied_migrations=lock.applied_migrations if lock else (),
        applied_migration_checksums=lock.applied_migration_checksums if lock else {},
    )
    if lock is None:
        message = "package-lock.json is missing; real package upgrade is blocked until package install --adopt-existing"
        (errors if require_lock else warnings).append(message)
        return errors, warnings
    if lock.schema_version != LOCK_SCHEMA_VERSION:
        errors.append(f"package-lock schema_version mismatch: expected {LOCK_SCHEMA_VERSION}, got {lock.schema_version}")
    if lock.package_id != current.package_id:
        errors.append(f"package-lock package_id mismatch: {lock.package_id} != {current.package_id}")
    if lock.content_schema_version != current.content_schema_version:
        errors.append(
            f"package-lock content_schema_version mismatch: {lock.content_schema_version} != {current.content_schema_version}"
        )
    if lock.package_version == current.package_version and lock.fingerprint == current.fingerprint:
        warnings.append("package source matches package-lock; upgrade may be a no-op unless runtime state diverged")
    elif lock.package_version == current.package_version:
        message = "package source checksum changed without package_version change"
        (errors if require_lock else warnings).append(message)
    for migration in getattr(source, "migrations", ()):
        if migration.id not in lock.applied_migrations:
            continue
        recorded = lock.applied_migration_checksums.get(migration.id)
        if recorded and recorded != migration.checksum:
            errors.append(f"package migration checksum mismatch: {migration.id}")
        elif not recorded:
            message = f"package migration has no recorded checksum: {migration.id}"
            (errors if require_lock else warnings).append(message)
    return errors, warnings
