from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from .atomic_io import write_text_atomic
from .campaign import load_campaign
from .db import connect, init_database, utc_now
from .projection_service import ProjectionService
from .save_validation import inspect_save_package


def relative_to_save(target: Path, path: Path) -> str:
    return Path(os.path.relpath(path, target)).as_posix()


def normalize_content_paths_for_save(source: Any, target: Path) -> dict[str, Any]:
    content = source.config.get("content", {})
    if not isinstance(content, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in content.items():
        if isinstance(value, list):
            normalized[key] = [copy_content_file_for_save(source, target, str(item)) for item in value]
        elif isinstance(value, str):
            normalized[key] = copy_content_file_for_save(source, target, value)
        else:
            normalized[key] = value
    return normalized


def copy_content_file_for_save(source: Any, target: Path, relative_path: str) -> str:
    source_path = source.resolve_under_root(relative_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"content file is missing or not a file: {relative_path}")
    local_relative = source_path.relative_to(source.root.resolve())
    destination = target / local_relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != destination.resolve():
        shutil.copy2(source_path, destination)
    return local_relative.as_posix()


def init_v1_save(campaign_dir: str | Path, save_dir: str | Path, *, force: bool = False) -> dict[str, Any]:
    source = load_campaign(campaign_dir)
    target = Path(save_dir).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        if not force:
            raise FileExistsError(f"save directory is not empty: {target}")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    config = copy.deepcopy(source.config)
    config["database"] = "data/game.sqlite"
    config["events"] = "data/events.jsonl"
    config["current_snapshot"] = "snapshots/current.md"
    config["current_snapshot_json"] = "snapshots/current.json"
    config["cards"] = "cards"
    config["content"] = normalize_content_paths_for_save(source, target)
    write_text_atomic(
        target / "campaign.yaml",
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    )
    save_manifest = {
        "save_schema_version": "1",
        "campaign_id": source.campaign_id,
        "campaign_version": source.package_version,
        "engine_version": source.engine_version,
        "source_campaign_path": relative_to_save(target, source.root),
        "created_at": utc_now(),
    }
    write_text_atomic(
        target / "save.yaml",
        yaml.safe_dump(save_manifest, allow_unicode=True, sort_keys=False),
    )

    save_campaign = load_campaign(target)
    init_database(save_campaign, force=True)
    with connect(save_campaign) as conn:
        projection_report = ProjectionService(save_campaign, conn).refresh(
            names=["events_jsonl", "search", "snapshots", "cards"],
            dirty_only=False,
            profile="save_init:maintenance_projection",
            commit_policy="caller_committed_required",
        )
    snapshot_artifacts = projection_report.artifacts_for("snapshots")
    cards_item = projection_report.item("cards")
    return {
        "ok": projection_report.ok,
        "campaign_id": save_campaign.campaign_id,
        "save_dir": str(target),
        "database": str(save_campaign.database_path),
        "events": str(save_campaign.events_path),
        "snapshot_path": snapshot_artifacts[0] if len(snapshot_artifacts) >= 1 else None,
        "snapshot_json_path": snapshot_artifacts[1] if len(snapshot_artifacts) >= 2 else None,
        "cards_count": int(cards_item.metadata.get("count", 0)) if cards_item else 0,
        "projection_report": projection_report.to_dict(),
    }


def inspect_v1_save(save_dir: str | Path) -> dict[str, Any]:
    return inspect_save_package(save_dir)
