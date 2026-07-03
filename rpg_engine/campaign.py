from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Campaign:
    root: Path
    config: dict[str, Any]
    trusted_content_roots: tuple[Path, ...] = ()

    @property
    def campaign_id(self) -> str:
        return str(self.config["id"])

    @property
    def name(self) -> str:
        return str(self.config.get("name", self.campaign_id))

    @property
    def engine_version(self) -> str:
        return str(self.config.get("engine_version", "0.1"))

    @property
    def package_version(self) -> str:
        return str(self.config.get("package_version", "0.1.0"))

    @property
    def content_schema_version(self) -> str:
        return str(self.config.get("content_schema_version", "1"))

    @property
    def database_path(self) -> Path:
        return self.resolve_under_root(str(self.config.get("database", "data/game.sqlite")))

    @property
    def events_path(self) -> Path:
        return self.resolve_under_root(str(self.config.get("events", "data/events.jsonl")))

    @property
    def current_snapshot_path(self) -> Path:
        return self.resolve_under_root(str(self.config.get("current_snapshot", "snapshots/current.md")))

    @property
    def current_snapshot_json_path(self) -> Path:
        return self.resolve_under_root(str(self.config.get("current_snapshot_json", "snapshots/current.json")))

    @property
    def cards_path(self) -> Path:
        return self.resolve_under_root(str(self.config.get("cards", "cards")))

    @property
    def defaults(self) -> dict[str, Any]:
        value = self.config.get("defaults", {})
        return value if isinstance(value, dict) else {}

    @property
    def player_entity_id(self) -> str:
        return str(self.defaults.get("player_entity_id", self.config.get("player_entity_id", "pc:player")))

    @property
    def context_budget(self) -> int:
        return int(self.defaults.get("context_budget", 2500))

    @property
    def sample_texts(self) -> list[str]:
        value = self.defaults.get("sample_texts", self.config.get("sample_texts", []))
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def resolve(self, relative_or_absolute: str) -> Path:
        path = Path(relative_or_absolute).expanduser()
        if path.is_absolute():
            return path
        return self.root / path

    def resolve_under_root(self, relative_or_absolute: str) -> Path:
        path = Path(relative_or_absolute)
        if path.is_absolute():
            raise ValueError(f"campaign paths must be relative to campaign root: {relative_or_absolute}")
        resolved = (self.root / path).resolve()
        root = self.root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"campaign path escapes campaign root: {relative_or_absolute}") from exc
        return resolved

    def resolve_content_file(self, relative_or_absolute: str) -> Path:
        path = Path(relative_or_absolute)
        if path.is_absolute():
            raise ValueError(f"campaign content paths must be relative: {relative_or_absolute}")
        resolved = (self.root / path).resolve()
        if path_is_under(resolved, self.root):
            return resolved
        for trusted_root in self.trusted_content_roots:
            if path_is_under(resolved, trusted_root):
                return resolved
        raise ValueError(f"campaign content path escapes campaign root and trusted source roots: {relative_or_absolute}")

    def display_path(self, path: Path) -> str:
        resolved = path.resolve()
        if path_is_under(resolved, self.root):
            return str(resolved.relative_to(self.root.resolve()))
        for trusted_root in self.trusted_content_roots:
            if path_is_under(resolved, trusted_root):
                return str(Path("source_campaign") / resolved.relative_to(trusted_root.resolve()))
        return str(path)

    def content_files(self, key: str) -> list[Path]:
        raw = self.config.get("content", {}).get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        return [self.resolve_content_file(str(item)) for item in raw]


def load_campaign(campaign_dir: str | Path) -> Campaign:
    root = Path(campaign_dir).expanduser().resolve()
    config_path = root / "campaign.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing campaign.yaml: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    errors = validate_campaign_config(data)
    if errors:
        raise ValueError("Invalid campaign.yaml:\n" + "\n".join(f"- {error}" for error in errors))
    return Campaign(root=root, config=data, trusted_content_roots=trusted_content_roots(root, data))


def trusted_content_roots(root: Path, config: dict[str, Any]) -> tuple[Path, ...]:
    save_manifest_path = root / "save.yaml"
    if not save_manifest_path.exists():
        return ()
    try:
        save_manifest = yaml.safe_load(save_manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ()
    if not isinstance(save_manifest, dict):
        return ()
    raw_source = save_manifest.get("source_campaign_path")
    if not isinstance(raw_source, str) or not raw_source.strip():
        return ()
    source_path = Path(raw_source).expanduser()
    source_root = source_path.resolve() if source_path.is_absolute() else (root / source_path).resolve()
    source_config_path = source_root / "campaign.yaml"
    if not source_config_path.exists():
        return ()
    try:
        source_config = yaml.safe_load(source_config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return ()
    if not isinstance(source_config, dict):
        return ()
    source_id = str(source_config.get("id", "")).strip()
    expected_ids = {
        str(config.get("id", "")).strip(),
        str(save_manifest.get("campaign_id", "")).strip(),
    }
    if not source_id or source_id not in expected_ids:
        return ()
    return (source_root,)


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_campaign_config(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["$ must be object"]
    errors: list[str] = []
    if not isinstance(data.get("id"), str) or not data.get("id", "").strip():
        errors.append("id: required non-empty string")
    for key in ("name", "engine_version", "package_version", "content_schema_version"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            errors.append(f"{key}: must be non-empty string")
    content = data.get("content", {})
    if not isinstance(content, dict):
        errors.append("content: must be object")
    else:
        for key, value in content.items():
            if not isinstance(key, str):
                errors.append("content: keys must be strings")
            if not isinstance(value, (str, list)):
                errors.append(f"content.{key}: must be string or array")
            elif isinstance(value, list) and not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"content.{key}: entries must be non-empty strings")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        errors.append("defaults: must be object")
    else:
        player_id = defaults.get("player_entity_id")
        if player_id is not None and (not isinstance(player_id, str) or ":" not in player_id):
            errors.append("defaults.player_entity_id: must be entity id")
        budget = defaults.get("context_budget")
        if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool) or budget < 500):
            errors.append("defaults.context_budget: must be integer >= 500")
    return errors


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
