from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..campaign import Campaign
from ..db import utc_now
from .lock import PackageFileChecksum, package_file_checksums
from .service import (
    PackageDiffResult,
    PackageSource,
    PackageValidationResult,
    diff_package_against_campaign,
    render_package_diff,
    render_package_validation,
    validate_package_source,
)


BUILD_MANIFEST = "package-build.json"


@dataclass(frozen=True)
class PackageBuildResult:
    package_id: str
    package_version: str
    archive_path: Path
    files: tuple[PackageFileChecksum, ...]

    @property
    def ok(self) -> bool:
        return True


@dataclass(frozen=True)
class PackageTestResult:
    validation: PackageValidationResult
    diff: PackageDiffResult | None = None

    @property
    def ok(self) -> bool:
        return self.validation.ok and (self.diff is None or self.diff.ok)


def build_package_archive(source: PackageSource, output_path: str | Path | None = None) -> PackageBuildResult:
    validation = validate_package_source(source)
    if not validation.ok:
        raise ValueError("Invalid package:\n" + "\n".join(f"- {error}" for error in validation.errors))
    archive_path = resolve_build_path(source, output_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    files = tuple(package_file_checksums(source))
    manifest = {
        "build_schema_version": 1,
        "package_id": source.package_id,
        "package_version": source.package_version,
        "content_schema_version": str(source.manifest.get("content_schema_version") or "1"),
        "built_at": utc_now(),
        "files": [
            {"path": item.path, "bytes": item.bytes, "sha256": item.sha256}
            for item in files
        ],
    }
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(BUILD_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        for item in files:
            archive.write(source.root / item.path, item.path)
    return PackageBuildResult(
        package_id=source.package_id,
        package_version=source.package_version,
        archive_path=archive_path,
        files=files,
    )


def test_package_source(
    source: PackageSource,
    *,
    campaign: Campaign | None = None,
    conn: sqlite3.Connection | None = None,
) -> PackageTestResult:
    validation = validate_package_source(source)
    diff = None
    if campaign is not None and conn is not None:
        diff = diff_package_against_campaign(
            conn,
            source,
            target_name=campaign.name,
            campaign=campaign,
            require_lock=False,
        )
        validation = diff.validation
    return PackageTestResult(validation=validation, diff=diff)


def resolve_build_path(source: PackageSource, output_path: str | Path | None) -> Path:
    if output_path:
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = source.root / path
        return path
    name = safe_archive_name(f"{source.package_id}-{source.package_version}") or "package"
    return source.root / "dist" / f"{name}.rpgpkg.zip"


def safe_archive_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def render_package_build(result: PackageBuildResult) -> str:
    lines = [
        "# Package Build",
        "",
        "- status: `OK`",
        f"- package: `{result.package_id}`",
        f"- version: `{result.package_version}`",
        f"- archive: `{result.archive_path}`",
        f"- files: `{len(result.files)}`",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_package_test(result: PackageTestResult) -> str:
    lines = ["# Package Test", ""]
    lines.append("- status: `OK`" if result.ok else "- status: `FAILED`")
    lines.extend(["", "## Validate", "", render_package_validation(result.validation).rstrip()])
    if result.diff is not None:
        lines.extend(["", "## Diff", "", render_package_diff(result.diff).rstrip()])
    return "\n".join(lines).rstrip() + "\n"
