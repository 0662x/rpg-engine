from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .campaign import Campaign
from .db import utc_now


@dataclass(frozen=True)
class BackupInfo:
    id: str
    path: Path
    created_at: str
    reason: str


def backup_root(campaign: Campaign) -> Path:
    return campaign.root / "backups" / "v2"


def create_backup(campaign: Campaign, *, reason: str = "manual") -> BackupInfo:
    created_at = utc_now()
    timestamp = created_at.replace("+00:00", "Z")
    backup_id = "backup-" + timestamp.replace("-", "").replace(":", "").replace(".", "")
    root = backup_root(campaign)
    path = root / backup_id
    suffix = 1
    while path.exists():
        suffix += 1
        path = root / f"{backup_id}-{suffix}"
    backup_id = path.name
    path.mkdir(parents=True, exist_ok=False)

    try:
        database_source = campaign.database_path
        if database_source.exists():
            database_target = path / "data" / "game.sqlite"
            database_target.parent.mkdir(parents=True, exist_ok=True)
            source_conn = sqlite3.connect(database_source)
            target_conn = sqlite3.connect(database_target)
            try:
                source_conn.backup(target_conn)
            finally:
                target_conn.close()
                source_conn.close()

        for relative in ["package-lock.json", "data/events.jsonl", "snapshots/current.md", "snapshots/current.json"]:
            source = campaign.root / relative
            if source.exists():
                target = path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for relative_dir in ["cards", "reports"]:
            source_dir = campaign.root / relative_dir
            if source_dir.exists():
                shutil.copytree(source_dir, path / relative_dir)
        manifest = {
            "id": backup_id,
            "created_at": created_at,
            "reason": reason,
            "campaign_id": campaign.campaign_id,
            "campaign_name": campaign.name,
        }
        (path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return BackupInfo(id=backup_id, path=path, created_at=created_at, reason=reason)
    except Exception as exc:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
        except Exception as cleanup_exc:
            exc.add_note(f"partial backup cleanup failed: {cleanup_exc!r}")
        raise


def list_backups(campaign: Campaign) -> list[BackupInfo]:
    root = backup_root(campaign)
    if not root.exists():
        return []
    result: list[BackupInfo] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        manifest_path = path / "manifest.json"
        if manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            result.append(
                BackupInfo(
                    id=str(data.get("id", path.name)),
                    path=path,
                    created_at=str(data.get("created_at", "")),
                    reason=str(data.get("reason", "")),
                )
            )
        else:
            result.append(BackupInfo(id=path.name, path=path, created_at="", reason="legacy"))
    return result


def restore_backup(campaign: Campaign, backup_id: str, *, create_pre_restore_backup: bool = True) -> BackupInfo | None:
    source = backup_root(campaign) / backup_id
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Missing backup: {backup_id}")
    pre_restore = create_backup(campaign, reason=f"pre_restore:{backup_id}") if create_pre_restore_backup else None
    for relative in ["package-lock.json", "data/game.sqlite", "data/events.jsonl", "snapshots/current.md", "snapshots/current.json"]:
        backup_file = source / relative
        target = campaign.root / relative
        if backup_file.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_file, target)
    for relative_dir in ["cards", "reports"]:
        backup_dir = source / relative_dir
        target_dir = campaign.root / relative_dir
        if backup_dir.exists():
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(backup_dir, target_dir)
    return pre_restore


def render_backup_list(backups: list[BackupInfo]) -> str:
    lines = ["# Backups", "", "| ID | Created | Reason | Path |", "|----|---------|--------|------|"]
    for backup in backups:
        lines.append(f"| `{backup.id}` | {backup.created_at} | {backup.reason} | `{backup.path}` |")
    if not backups:
        lines.append("| 无 |  |  |  |")
    return "\n".join(lines) + "\n"
