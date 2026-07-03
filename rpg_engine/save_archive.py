from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .atomic_io import atomic_output_path, fsync_directory, write_bytes_atomic, write_text_atomic
from .campaign import Campaign
from .db import utc_now


ARCHIVE_VERSION = 1
MANIFEST_NAME = "save-archive.json"
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_TOTAL_BYTES = 1024 * 1024 * 1024
CORE_FILES = (
    "campaign.yaml",
    "save.yaml",
    "data/game.sqlite",
    "data/events.jsonl",
    "package-lock.json",
    "snapshots/current.md",
    "snapshots/current.json",
)
DERIVED_DIRS = (
    "cards",
    "memory",
)


@dataclass(frozen=True)
class ArchiveFile:
    path: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class SaveArchiveResult:
    archive_path: Path
    files: tuple[ArchiveFile, ...] = field(default_factory=tuple)
    manifest: dict[str, Any] = field(default_factory=dict)

    def render_export(self) -> str:
        lines = [
            "# Save Export",
            "",
            "- status: `OK`",
            f"- archive: `{self.archive_path}`",
            f"- files: `{len(self.files)}`",
            "",
            "| File | Bytes | SHA256 |",
            "|------|-------|--------|",
        ]
        for item in self.files:
            lines.append(f"| `{item.path}` | {item.bytes} | `{item.sha256}` |")
        return "\n".join(lines).rstrip() + "\n"

    def render_import(self) -> str:
        lines = [
            "# Save Import",
            "",
            "- status: `OK`",
            f"- target: `{self.archive_path}`",
            f"- files: `{len(self.files)}`",
        ]
        return "\n".join(lines).rstrip() + "\n"


def export_save(campaign: Campaign, output_path: str | Path | None = None) -> SaveArchiveResult:
    archive_path = resolve_export_path(campaign, output_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    exported_at = utc_now()
    files = tuple(existing_archive_files(campaign.root))
    manifest = {
        "archive_schema_version": ARCHIVE_VERSION,
        "campaign_id": campaign.campaign_id,
        "campaign_name": campaign.name,
        "engine_version": campaign.engine_version,
        "package_version": campaign.package_version,
        "content_schema_version": campaign.content_schema_version,
        "exported_at": exported_at,
        "files": [archive_file_to_dict(item) for item in files],
    }
    with atomic_output_path(archive_path) as tmp_archive:
        with zipfile.ZipFile(tmp_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            for item in files:
                archive.write(campaign.root / item.path, item.path)
    return SaveArchiveResult(archive_path=archive_path, files=files, manifest=manifest)


def import_save_archive(archive_path: str | Path, target_dir: str | Path, *, force: bool = False) -> SaveArchiveResult:
    source = Path(archive_path).expanduser().resolve()
    target = Path(target_dir).expanduser().resolve()
    ensure_import_target_is_replaceable(target, force=force)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.import-", dir=target.parent))
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = archive.namelist()
            validate_archive_names(names)
            if MANIFEST_NAME not in names:
                raise ValueError(f"missing {MANIFEST_NAME}")
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            if int(manifest.get("archive_schema_version", 0)) != ARCHIVE_VERSION:
                raise ValueError("save archive schema version mismatch")
            files = tuple(parse_manifest_files(manifest))
            expected = {item.path: item for item in files}
            archive_file_names = {name for name in names if not name.endswith("/")}
            extra = sorted(archive_file_names - {MANIFEST_NAME, *expected.keys()})
            if extra:
                raise ValueError(f"archive contains unlisted file: {extra[0]}")
            total_bytes = 0
            for path, item in expected.items():
                if path not in names:
                    raise ValueError(f"archive missing file listed in manifest: {path}")
                if item.bytes > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValueError(f"archive member too large: {path}")
                data = archive.read(path)
                if len(data) != item.bytes:
                    raise ValueError(f"size mismatch for {path}")
                total_bytes += len(data)
                if total_bytes > MAX_ARCHIVE_TOTAL_BYTES:
                    raise ValueError("archive exceeds maximum total size")
                digest = hashlib.sha256(data).hexdigest()
                if digest != item.sha256:
                    raise ValueError(f"checksum mismatch for {path}")
                output = resolve_archive_output(staging, path)
                output.parent.mkdir(parents=True, exist_ok=True)
                write_bytes_atomic(output, data)
            write_text_atomic(
                staging / MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        fsync_directory(staging)
        replace_directory_atomically(staging, target)
        staging = None
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return SaveArchiveResult(archive_path=target, files=files, manifest=manifest)


def ensure_import_target_is_replaceable(target: Path, *, force: bool) -> None:
    if not target.exists():
        return
    if target.is_dir() and not any(target.iterdir()):
        return
    if not force:
        raise FileExistsError(f"target directory is not empty: {target}")


def replace_directory_atomically(staging: Path, target: Path) -> None:
    backup_holder: Path | None = None
    backup: Path | None = None
    if target.exists():
        backup_holder = Path(tempfile.mkdtemp(prefix=f".{target.name}.previous-", dir=target.parent))
        backup = backup_holder / "target"
        os.replace(target, backup)
    try:
        os.replace(staging, target)
        fsync_directory(target.parent)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            os.replace(backup, target)
            fsync_directory(target.parent)
        raise
    finally:
        if backup_holder is not None:
            shutil.rmtree(backup_holder, ignore_errors=True)


def resolve_archive_output(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    output = (resolved_root / relative).resolve()
    try:
        output.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"unsafe archive path: {relative}") from exc
    return output


def resolve_export_path(campaign: Campaign, output_path: str | Path | None) -> Path:
    if output_path:
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = campaign.root / path
        return path
    stamp = utc_now().replace(":", "").replace("-", "").replace(".", "")
    return campaign.root / "exports" / f"{campaign.campaign_id}-save-{stamp}.aigmsave"


def existing_archive_files(root: Path) -> list[ArchiveFile]:
    files: list[ArchiveFile] = []
    for relative in CORE_FILES:
        path = root / relative
        if not path.exists() or not path.is_file():
            continue
        files.append(checksum_file(root, path))
    for relative_dir in DERIVED_DIRS:
        path = root / relative_dir
        if not path.exists() or not path.is_dir():
            continue
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            files.append(checksum_file(root, child))
    return files


def checksum_file(root: Path, path: Path) -> ArchiveFile:
    data = path.read_bytes()
    return ArchiveFile(
        path=path.relative_to(root).as_posix(),
        bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def archive_file_to_dict(item: ArchiveFile) -> dict[str, Any]:
    return {"path": item.path, "bytes": item.bytes, "sha256": item.sha256}


def parse_manifest_files(manifest: dict[str, Any]) -> list[ArchiveFile]:
    raw = manifest.get("files", [])
    if not isinstance(raw, list):
        raise ValueError("manifest files must be an array")
    if len(raw) > MAX_ARCHIVE_FILES:
        raise ValueError("archive lists too many files")
    files: list[ArchiveFile] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"manifest files[{index}] must be object")
        path = str(item.get("path", ""))
        if not path:
            raise ValueError(f"manifest files[{index}].path is required")
        if path in seen:
            raise ValueError(f"manifest files[{index}].path is duplicated: {path}")
        seen.add(path)
        bytes_count = int(item.get("bytes", 0))
        if bytes_count < 0:
            raise ValueError(f"manifest files[{index}].bytes must be non-negative")
        files.append(
            ArchiveFile(
                path=path,
                bytes=bytes_count,
                sha256=str(item.get("sha256", "")),
            )
        )
    return files


def validate_archive_names(names: list[str]) -> None:
    for name in names:
        if not name or "\\" in name:
            raise ValueError(f"unsafe archive path: {name}")
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe archive path: {name}")
