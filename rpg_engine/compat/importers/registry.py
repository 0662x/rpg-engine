from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ...campaign import Campaign
from .isekai_farm_v1 import ImportReport, import_v1_state


ImporterRun = Callable[[Campaign, Path, bool], ImportReport]


@dataclass(frozen=True)
class ImporterSpec:
    name: str
    description: str
    default_source: str
    run: ImporterRun


class ImporterRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ImporterSpec] = {}

    def register(self, spec: ImporterSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate importer: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ImporterSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def all(self) -> list[ImporterSpec]:
        return [self._specs[name] for name in self.names()]


def get_default_importer_registry() -> ImporterRegistry:
    registry = ImporterRegistry()
    registry.register(
        ImporterSpec(
            name="isekai_farm_v1",
            description="campaign-specific v1 markdown save importer",
            default_source="archive_v1",
            run=run_isekai_farm_v1,
        )
    )
    return registry


def run_isekai_farm_v1(campaign: Campaign, source_dir: Path, apply: bool) -> ImportReport:
    return import_v1_state(campaign, source_dir, apply=apply)


def render_importer_list(registry: ImporterRegistry | None = None) -> str:
    registry = registry or get_default_importer_registry()
    lines = [
        "# Importers",
        "",
        "| Name | Default Source | Description |",
        "|------|----------------|-------------|",
    ]
    for spec in registry.all():
        lines.append(f"| `{spec.name}` | `{spec.default_source}` | {spec.description} |")
    return "\n".join(lines).rstrip() + "\n"


def render_importer_detail(name: str, registry: ImporterRegistry | None = None) -> tuple[str, bool]:
    registry = registry or get_default_importer_registry()
    spec = registry.get(name)
    if spec is None:
        return f"FAILED\n- unknown importer: {name}\n", False
    lines = [
        f"# Importer: {spec.name}",
        "",
        f"- default_source: `{spec.default_source}`",
        f"- description: {spec.description}",
        "- apply_mode: `dry-run by default; --apply writes through save_turn_delta`",
    ]
    return "\n".join(lines).rstrip() + "\n", True


def run_importer(
    campaign: Campaign,
    name: str,
    *,
    source: str | Path | None = None,
    apply: bool = False,
    registry: ImporterRegistry | None = None,
) -> ImportReport:
    registry = registry or get_default_importer_registry()
    spec = registry.get(name)
    if spec is None:
        raise KeyError(f"unknown importer: {name}")
    source_dir = Path(source).expanduser() if source else campaign.resolve(spec.default_source)
    if not source_dir.is_absolute():
        source_dir = campaign.root / source_dir
    return spec.run(campaign, source_dir, apply)
