from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..campaign import Campaign


PLUGIN_MANIFEST_NAMES = ("plugin.yaml", "plugin.yml", "plugin.json")
SUPPORTED_ENGINE_API_VERSION = "1"
ALLOWED_CAPABILITIES = {"content_type", "action_resolver", "context_collector", "card_renderer", "importer"}


@dataclass(frozen=True)
class PluginManifest:
    id: str
    version: str
    engine_api_version: str
    enabled: bool
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    entrypoint: str | None = None
    path: Path | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors


def discover_plugin_manifests(campaign: Campaign) -> list[PluginManifest]:
    root = campaign.root / "plugins"
    if not root.exists():
        return []
    manifests: list[PluginManifest] = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        path = first_manifest_path(child)
        if path is None:
            manifests.append(
                PluginManifest(
                    id=child.name,
                    version="",
                    engine_api_version="",
                    enabled=False,
                    path=child,
                    errors=("missing plugin manifest",),
                )
            )
            continue
        manifests.append(load_plugin_manifest(path))
    return manifests


def first_manifest_path(root: Path) -> Path | None:
    for name in PLUGIN_MANIFEST_NAMES:
        path = root / name
        if path.exists():
            return path
    return None


def load_plugin_manifest(path: Path) -> PluginManifest:
    try:
        data = load_manifest_data(path)
    except Exception as exc:
        return PluginManifest(
            id=path.parent.name,
            version="",
            engine_api_version="",
            enabled=False,
            path=path,
            errors=(f"cannot read manifest: {exc}",),
        )
    errors, warnings = validate_manifest_data(data)
    capabilities = data.get("capabilities", []) if isinstance(data, dict) else []
    return PluginManifest(
        id=str(data.get("id", "")) if isinstance(data, dict) else "",
        version=str(data.get("version", "")) if isinstance(data, dict) else "",
        engine_api_version=str(data.get("engine_api_version", "")) if isinstance(data, dict) else "",
        enabled=bool(data.get("enabled", False)) if isinstance(data, dict) else False,
        capabilities=tuple(str(item) for item in capabilities) if isinstance(capabilities, list) else (),
        entrypoint=str(data.get("entrypoint")) if isinstance(data, dict) and data.get("entrypoint") else None,
        path=path,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def load_manifest_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("manifest root must be object")
    return data


def validate_manifest_data(data: Any) -> tuple[list[str], list[str]]:
    if not isinstance(data, dict):
        return ["manifest root must be object"], []
    errors: list[str] = []
    warnings: list[str] = []
    for key in ("id", "version", "engine_api_version"):
        if not isinstance(data.get(key), str) or not data.get(key, "").strip():
            errors.append(f"{key}: required non-empty string")
    if data.get("engine_api_version") and str(data["engine_api_version"]) != SUPPORTED_ENGINE_API_VERSION:
        errors.append(
            f"engine_api_version: unsupported {data['engine_api_version']} "
            f"(expected {SUPPORTED_ENGINE_API_VERSION})"
        )
    if "enabled" in data and not isinstance(data["enabled"], bool):
        errors.append("enabled: must be boolean")
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list) or not all(isinstance(item, str) and item.strip() for item in capabilities):
        errors.append("capabilities: must be array of non-empty strings")
    else:
        for capability in capabilities:
            if capability not in ALLOWED_CAPABILITIES:
                errors.append(f"capabilities: unsupported capability {capability}")
    if data.get("enabled", False):
        warnings.append("plugin manifest is enabled, but dynamic plugin loading is not implemented")
    return errors, warnings


def render_plugin_list(manifests: list[PluginManifest]) -> str:
    lines = [
        "# Plugins",
        "",
        "| ID | Version | API | Enabled | Status | Capabilities |",
        "|----|---------|-----|---------|--------|--------------|",
    ]
    for manifest in manifests:
        status = "ok" if manifest.ok else "failed"
        lines.append(
            f"| `{manifest.id}` | `{manifest.version}` | `{manifest.engine_api_version}` | "
            f"`{'yes' if manifest.enabled else 'no'}` | `{status}` | {', '.join(manifest.capabilities)} |"
        )
    if not manifests:
        lines.append("|  |  |  |  | `none` |  |")
    return "\n".join(lines).rstrip() + "\n"


def render_plugin_validation(manifests: list[PluginManifest]) -> str:
    ok = all(manifest.ok for manifest in manifests)
    lines = ["OK" if ok else "FAILED"]
    if not manifests:
        lines.append("- no plugin manifests found")
    for manifest in manifests:
        prefix = manifest.id or str(manifest.path or "plugin")
        for error in manifest.errors:
            lines.append(f"- {prefix}: {error}")
        for warning in manifest.warnings:
            lines.append(f"- warning {prefix}: {warning}")
    return "\n".join(lines).rstrip() + "\n"
