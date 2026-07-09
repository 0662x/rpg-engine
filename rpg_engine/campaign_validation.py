from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .campaign import Campaign, load_campaign, validate_campaign_config
from .capabilities import V1_CAPABILITY_SET
from .content_types import get_default_registry
from .db import connect, init_database
from .packages.service import PACKAGE_AUXILIARY_CONTENT_KEYS, load_package_source, validate_package_source
from .palette import KIND_KEYS, PALETTE_DISCOVERY_MODES, PALETTE_INTENTS
from .projection_service import ProjectionService
from .runtime import GMRuntime
from .validation_issues import issues_from_messages
from .validators import run_checks
from .visibility import CLOCK_VISIBILITY_LABELS, ENTITY_VISIBILITY_LABELS


ALLOWED_ENTITY_VISIBILITY = set(ENTITY_VISIBILITY_LABELS)
ALLOWED_CLOCK_VISIBILITY = set(CLOCK_VISIBILITY_LABELS)
ALLOWED_RANDOM_TABLE_VISIBILITY = {"known", "hinted", "hidden", "gm"}
REQUIRED_V1_FILES = (
    "prompts/gm.md",
    "templates/action.md",
    "templates/query.md",
    "tests/smoke.yaml",
)
REQUIRED_CONTENT_KEYS = ("entities", "rules", "clocks")
OPTIONAL_CONTENT_KEYS = tuple(sorted(PACKAGE_AUXILIARY_CONTENT_KEYS))
SMOKE_TYPES = {"start_turn", "query", "preview", "validate_delta", "random_table"}
RUNTIME_ARTIFACT_FILES = (
    "save.yaml",
    "data/game.sqlite",
    "data/events.jsonl",
)
RUNTIME_ARTIFACT_DIRS = ("data", "snapshots", "cards", "memory", "backups", "reports", "exports")
RUNTIME_ARTIFACT_SUFFIXES = (
    ".aigmsave",
    ".sqlite",
    ".sqlite3",
    ".sqlite-wal",
    ".sqlite3-wal",
    ".sqlite-shm",
    ".sqlite3-shm",
    ".sqlite-journal",
    ".sqlite3-journal",
    ".db",
    ".db-wal",
    ".db-shm",
    ".db-journal",
)
RUNTIME_AIGM_DIR = ".aigm"
RUNTIME_AIGM_PENDING_PREFIX = "pending-"
RUNTIME_AIGM_FILES = ("save-registry.json",)


@dataclass(frozen=True)
class CampaignValidationResult:
    campaign_id: str = ""
    package_version: str = ""
    ok: bool = False
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    record_counts: dict[str, int] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    smoke_tests: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "package_version": self.package_version,
            "ok": self.ok,
            "errors": list(self.errors),
            "error_details": issues_from_messages(self.errors, default_code="CAMPAIGN_VALIDATION_ERROR"),
            "warnings": list(self.warnings),
            "record_counts": dict(self.record_counts),
            "capabilities": list(self.capabilities),
            "smoke_tests": list(self.smoke_tests),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class SmokeCaseResult:
    case_id: str
    ok: bool
    type: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "ok": self.ok,
            "type": self.type,
            "message": self.message,
        }


@dataclass(frozen=True)
class CampaignTestResult:
    campaign_id: str
    ok: bool
    validation: CampaignValidationResult
    init_ok: bool = False
    health_ok: bool = False
    health_errors: tuple[str, ...] = ()
    smoke_results: tuple[SmokeCaseResult, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "ok": self.ok,
            "validation": self.validation.to_dict(),
            "init_ok": self.init_ok,
            "health": {
                "ok": self.health_ok,
                "errors": list(self.health_errors),
            },
            "smoke_results": [item.to_dict() for item in self.smoke_results],
            "errors": list(self.errors),
            "error_details": issues_from_messages(self.errors, default_code="CAMPAIGN_TEST_ERROR"),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def validate_campaign_package(campaign_dir: str | Path) -> CampaignValidationResult:
    root = Path(campaign_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    record_counts: dict[str, int] = {}
    capabilities: list[str] = []
    smoke_ids: list[str] = []

    config_path = root / "campaign.yaml"
    data: Any = {}
    if not config_path.exists():
        return CampaignValidationResult(errors=(f"campaign.yaml: missing at {config_path}",), ok=False)
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return CampaignValidationResult(errors=(f"campaign.yaml: invalid YAML: {exc}",), ok=False)

    errors.extend(prefix_errors("campaign.yaml", validate_campaign_config(data)))
    if isinstance(data, dict):
        capabilities = parse_capabilities(data, errors)
        validate_v1_structure(root, data, errors)
        validate_no_v1_code_extensions(root, errors)
        validate_no_runtime_artifacts(root, warnings)
        validate_content_paths(root, data, errors)
        validate_required_files(root, errors)
        validate_random_tables(root, data, errors)
        smoke_ids = validate_smoke_file(root, capabilities, errors)
    else:
        errors.append("campaign.yaml: must be object")

    try:
        source = load_package_source(root)
        package_validation = validate_package_source(source)
        errors.extend(prefix_errors("content", package_validation.errors))
        warnings.extend(prefix_errors("content", package_validation.warnings))
        record_counts.update(package_validation.record_counts)
        validate_content_references(source.records_by_type, data if isinstance(data, dict) else {}, errors)
        validate_palettes(root, data if isinstance(data, dict) else {}, source.records_by_type, errors, warnings)
    except Exception as exc:
        message = str(exc)
        if message == "package palette directory escapes package root: content/palettes":
            errors.append("content/palettes: path escapes campaign root")
        else:
            errors.append(f"content: failed to load registered content: {message}")

    return CampaignValidationResult(
        campaign_id=str(data.get("id", "")) if isinstance(data, dict) else "",
        package_version=str(data.get("package_version", data.get("version", ""))) if isinstance(data, dict) else "",
        ok=not errors,
        errors=tuple(dedupe(errors)),
        warnings=tuple(dedupe(warnings)),
        record_counts=record_counts,
        capabilities=tuple(capabilities),
        smoke_tests=tuple(smoke_ids),
    )


def run_campaign_smoke_tests(campaign_dir: str | Path) -> CampaignTestResult:
    validation = validate_campaign_package(campaign_dir)
    if not validation.ok:
        return CampaignTestResult(
            campaign_id=validation.campaign_id,
            ok=False,
            validation=validation,
            errors=validation.errors,
        )

    source_root = Path(campaign_dir).expanduser().resolve()
    smoke_cases = load_smoke_cases(source_root / "tests" / "smoke.yaml")
    results: list[SmokeCaseResult] = []
    errors: list[str] = []
    health_ok = False
    health_errors: tuple[str, ...] = ()
    init_ok = False

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "campaign"
        shutil.copytree(
            source_root,
            target,
            ignore=root_runtime_artifact_ignore(source_root),
        )
        campaign = load_campaign(target)
        init_database(campaign, force=True)
        with connect(campaign) as conn:
            ProjectionService(campaign, conn).refresh(
                names=["events_jsonl", "search", "snapshots", "cards"],
                dirty_only=False,
                profile="campaign_validation:maintenance_projection",
                commit_policy="caller_committed_required",
            )
        init_ok = True

        with connect(campaign) as conn:
            health_errors = tuple(run_checks(conn))
        health_ok = not health_errors
        runtime = GMRuntime(campaign)
        for case in smoke_cases:
            result = run_smoke_case(runtime, case)
            results.append(result)
            if not result.ok:
                errors.append(f"{result.case_id}: {result.message}")

    ok = validation.ok and init_ok and health_ok and all(item.ok for item in results)
    return CampaignTestResult(
        campaign_id=validation.campaign_id,
        ok=ok,
        validation=validation,
        init_ok=init_ok,
        health_ok=health_ok,
        health_errors=health_errors,
        smoke_results=tuple(results),
        errors=tuple(errors),
    )


def parse_capabilities(data: dict[str, Any], errors: list[str]) -> list[str]:
    raw = data.get("capabilities", [])
    if not isinstance(raw, list) or not all(isinstance(item, str) and item.strip() for item in raw):
        errors.append("campaign.yaml.capabilities: must be array of non-empty strings")
        return []
    capabilities = [str(item).strip() for item in raw]
    for item in capabilities:
        if item not in V1_CAPABILITY_SET:
            errors.append(f"campaign.yaml.capabilities: unsupported capability {item}")
    duplicates = sorted(item for item in set(capabilities) if capabilities.count(item) > 1)
    for item in duplicates:
        errors.append(f"campaign.yaml.capabilities: duplicate capability {item}")
    return capabilities


def validate_v1_structure(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    for key in ("id", "name", "engine_version", "package_version", "content_schema_version"):
        if not isinstance(data.get(key), str) or not str(data.get(key, "")).strip():
            errors.append(f"campaign.yaml.{key}: required non-empty string")
    if not isinstance(data.get("initial_location_id"), str) or not str(data.get("initial_location_id", "")).strip():
        errors.append("campaign.yaml.initial_location_id: required non-empty string")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict) or not isinstance(defaults.get("player_entity_id"), str):
        errors.append("campaign.yaml.defaults.player_entity_id: required entity id string")
    content = data.get("content", {})
    if not isinstance(content, dict):
        errors.append("campaign.yaml.content: required object")
        return
    for key in REQUIRED_CONTENT_KEYS:
        if key not in content:
            errors.append(f"campaign.yaml.content.{key}: required")
    allowed_keys = {
        *(spec.campaign_key for spec in get_default_registry().seed_specs() if spec.campaign_key),
        *OPTIONAL_CONTENT_KEYS,
    }
    for key in content:
        if key not in allowed_keys:
            errors.append(f"campaign.yaml.content.{key}: unsupported V1 content key")
    if not (root / "content").exists():
        errors.append("content/: required directory")


def validate_no_v1_code_extensions(root: Path, errors: list[str]) -> None:
    if (root / "plugins").exists():
        errors.append("plugins/: V1 campaign packages must not include plugins")
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts:
            errors.append(f"{relative_path(root, path)}: V1 campaign packages must not include Python code")


def validate_no_runtime_artifacts(root: Path, warnings: list[str]) -> None:
    seen: set[str] = set()

    def warn(path: Path, *, directory: bool = False) -> None:
        relative = relative_path(root, path)
        if directory and not relative.endswith("/"):
            relative += "/"
        if relative in seen:
            return
        seen.add(relative)
        warnings.append(f"{relative}: runtime Save Package artifact should not be included in a Campaign Package")

    for relative in RUNTIME_ARTIFACT_FILES:
        path = root / relative
        if path.exists() or path.is_symlink():
            warn(path)
    aigm = root / RUNTIME_AIGM_DIR
    if aigm.is_symlink():
        warn(aigm, directory=True)
    elif aigm.exists() and not aigm.is_dir():
        warn(aigm)
    elif aigm.is_dir():
        for path in sorted(aigm.iterdir()):
            if path.name in RUNTIME_AIGM_FILES or path.name.startswith(RUNTIME_AIGM_PENDING_PREFIX):
                warn(path, directory=path.is_dir())
    for path in sorted(root.rglob("*")):
        if path.is_file() or path.is_symlink():
            if path.name.endswith(RUNTIME_ARTIFACT_SUFFIXES):
                warn(path)
    for relative in RUNTIME_ARTIFACT_DIRS:
        path = root / relative
        if path.is_symlink():
            warn(path, directory=True)
            continue
        if not path.exists():
            continue
        if not path.is_dir():
            warn(path)
            continue
        artifacts = sorted(item for item in path.rglob("*") if item.is_file() or item.is_symlink())
        if not artifacts:
            warn(path, directory=True)
            continue
        for item in artifacts:
            warn(item, directory=item.is_dir())


def root_runtime_artifact_ignore(source_root: Path):
    source_root = source_root.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        current = Path(directory).resolve()
        if current != source_root:
            return set()
        ignored: set[str] = set()
        for name in names:
            path = current / name
            if name in RUNTIME_ARTIFACT_DIRS or name == RUNTIME_AIGM_DIR or name == "save.yaml":
                ignored.add(name)
            elif path.is_file() or path.is_symlink():
                if name.endswith(RUNTIME_ARTIFACT_SUFFIXES):
                    ignored.add(name)
        return ignored

    return ignore


def validate_content_paths(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    content = data.get("content", {})
    if not isinstance(content, dict):
        return
    for key, raw in content.items():
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"campaign.yaml.content.{key}: entries must be non-empty paths")
                continue
            path = Path(value)
            if path.is_absolute():
                errors.append(f"campaign.yaml.content.{key}: must use relative package path, got {value}")
                continue
            if ".." in path.parts:
                errors.append(f"campaign.yaml.content.{key}: path escapes campaign root {value}")
                continue
            full_path = root / path
            try:
                full_path.resolve().relative_to(root.resolve())
            except ValueError:
                errors.append(f"campaign.yaml.content.{key}: path escapes campaign root {value}")
                continue
            if not full_path.exists():
                errors.append(f"campaign.yaml.content.{key}: missing file {value}")
            elif not full_path.is_file():
                errors.append(f"campaign.yaml.content.{key}: not a file {value}")


def validate_required_files(root: Path, errors: list[str]) -> None:
    for relative in REQUIRED_V1_FILES:
        path = root / relative
        if not path.exists():
            errors.append(f"{relative}: required")
        elif path.is_file() and not path.read_text(encoding="utf-8").strip():
            errors.append(f"{relative}: must not be empty")


def validate_random_tables(root: Path, data: dict[str, Any], errors: list[str]) -> None:
    content = data.get("content", {})
    if not isinstance(content, dict) or "random_tables" not in content:
        return
    seen: set[str] = set()
    for path in content_paths(root, content["random_tables"], errors, "random_tables"):
        if not path.is_file():
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{relative_path(root, path)}: invalid YAML: {exc}")
            continue
        tables = document.get("random_tables")
        if not isinstance(tables, list):
            errors.append(f"{relative_path(root, path)}.random_tables: must be array")
            continue
        for index, table in enumerate(tables):
            table_path = f"{relative_path(root, path)}.random_tables[{index}]"
            if not isinstance(table, dict):
                errors.append(f"{table_path}: must be object")
                continue
            table_id = str(table.get("id", ""))
            if not table_id:
                errors.append(f"{table_path}.id: required")
            elif table_id in seen:
                errors.append(f"{table_path}.id: duplicate random table id {table_id}")
            seen.add(table_id)
            if not isinstance(table.get("name"), str) or not table.get("name", "").strip():
                errors.append(f"{table_path}.name: required non-empty string")
            visibility = str(table.get("visibility", "known"))
            if visibility not in ALLOWED_RANDOM_TABLE_VISIBILITY:
                errors.append(f"{table_path}.visibility: unsupported value {visibility}")
            entries = table.get("entries")
            if not isinstance(entries, list) or not entries:
                errors.append(f"{table_path}.entries: must be non-empty array")
                continue
            for entry_index, entry in enumerate(entries):
                entry_path = f"{table_path}.entries[{entry_index}]"
                if not isinstance(entry, dict):
                    errors.append(f"{entry_path}: must be object")
                    continue
                if "result" not in entry or not str(entry.get("result", "")).strip():
                    errors.append(f"{entry_path}.result: required")
                weight = entry.get("weight", 1)
                if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
                    errors.append(f"{entry_path}.weight: must be positive number")


def validate_palettes(
    root: Path,
    data: dict[str, Any],
    records_by_type: dict[str, list[dict[str, Any]]],
    errors: list[str],
    warnings: list[str],
) -> None:
    paths = palette_paths(root, data, errors)
    if not paths:
        return
    entities = records_by_type.get("entity", [])
    entity_ids = {str(record.get("id")) for record in entities if record.get("id")}
    location_ids = {str(record.get("id")) for record in entities if record.get("type") == "location" and record.get("id")}
    clock_ids = {str(record.get("id")) for record in records_by_type.get("clock", []) if record.get("id")}
    seen: set[str] = set()
    allowed_keys = set(KIND_KEYS.values())
    for path in paths:
        relative = relative_path(root, path)
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{relative}: invalid YAML: {exc}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{relative}: must be object")
            continue
        for key in document:
            if key not in allowed_keys:
                errors.append(f"{relative}.{key}: unsupported palette key")
        for key in sorted(allowed_keys):
            entries = document.get(key, [])
            if entries is None:
                continue
            if not isinstance(entries, list):
                errors.append(f"{relative}.{key}: must be array")
                continue
            for index, entry in enumerate(entries):
                entry_path = f"{relative}.{key}[{index}]"
                validate_palette_entry(
                    entry,
                    entry_path,
                    key,
                    seen,
                    location_ids,
                    entity_ids,
                    clock_ids,
                    errors,
                    warnings,
                )


def palette_paths(root: Path, data: dict[str, Any], errors: list[str]) -> list[Path]:
    content = data.get("content", {})
    if isinstance(content, dict) and "palettes" in content:
        raw = content["palettes"]
        paths = content_paths(root, raw, errors, "palettes")
        if paths or not (isinstance(raw, list) and not raw):
            return paths
    palette_dir = root / "content" / "palettes"
    if not palette_dir.exists():
        return []
    try:
        palette_dir.resolve().relative_to(root.resolve())
    except ValueError:
        errors.append("content/palettes: path escapes campaign root")
        return []
    paths: list[Path] = []
    for path in sorted(palette_dir.glob("*.yaml")):
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            errors.append(f"{relative_path(root, path)}: path escapes campaign root")
            continue
        paths.append(path)
    return paths


def validate_palette_entry(
    entry: Any,
    entry_path: str,
    yaml_key: str,
    seen: set[str],
    location_ids: set[str],
    entity_ids: set[str],
    clock_ids: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    if not isinstance(entry, dict):
        errors.append(f"{entry_path}: must be object")
        return
    entry_id = str(entry.get("id", "")).strip()
    if not entry_id:
        errors.append(f"{entry_path}.id: required")
    elif entry_id in seen:
        errors.append(f"{entry_path}.id: duplicate palette id {entry_id}")
    seen.add(entry_id)
    for field in ("name", "summary", "rarity"):
        if not isinstance(entry.get(field), str) or not str(entry.get(field, "")).strip():
            errors.append(f"{entry_path}.{field}: required non-empty string")
    locations = as_list(entry.get("locations"))
    biomes = as_list(entry.get("biomes"))
    if not locations and not biomes:
        warnings.append(f"{entry_path}: should define locations or biomes")
    for location in locations:
        if str(location) not in location_ids:
            errors.append(f"{entry_path}.locations: missing location {location}")
    intents = as_list(entry.get("intents"))
    if not intents:
        warnings.append(f"{entry_path}.intents: should list action intents")
    for intent in intents:
        if str(intent) not in PALETTE_INTENTS:
            errors.append(f"{entry_path}.intents: unsupported intent {intent}")
    discovery = entry.get("discovery")
    if not isinstance(discovery, dict):
        errors.append(f"{entry_path}.discovery: required object")
        discovery = {}
    mode = str(discovery.get("mode", "confirm_required"))
    if mode not in PALETTE_DISCOVERY_MODES:
        errors.append(f"{entry_path}.discovery.mode: unsupported value {mode}")
    if not str(discovery.get("clue_text", "")).strip():
        warnings.append(f"{entry_path}.discovery.clue_text: should describe player-facing clue text")
    confirm_methods = as_list(discovery.get("confirm_methods"))
    if mode != "direct" and not confirm_methods:
        warnings.append(f"{entry_path}.discovery.confirm_methods: should list confirmation methods")
    if str(entry.get("rarity", "")).strip() == "hidden" and mode == "direct":
        errors.append(f"{entry_path}: hidden rarity cannot use discovery.mode direct")
    unlock = entry.get("unlock", {})
    if unlock is not None and not isinstance(unlock, dict):
        errors.append(f"{entry_path}.unlock: must be object")
        unlock = {}
    if isinstance(unlock, dict):
        for location in as_list(unlock.get("required_locations")):
            if str(location) not in location_ids:
                errors.append(f"{entry_path}.unlock.required_locations: missing location {location}")
        required_clocks = unlock.get("required_clocks", {})
        if required_clocks is not None and not isinstance(required_clocks, dict):
            errors.append(f"{entry_path}.unlock.required_clocks: must be object")
        elif isinstance(required_clocks, dict):
            for clock_id in required_clocks:
                if str(clock_id) not in clock_ids:
                    errors.append(f"{entry_path}.unlock.required_clocks: missing clock {clock_id}")
    save_as = entry.get("save_as", {})
    if save_as is not None and not isinstance(save_as, dict):
        errors.append(f"{entry_path}.save_as: must be object")
        save_as = {}
    if isinstance(save_as, dict):
        save_type = str(save_as.get("type", "")).strip()
        if save_type and save_type not in {
            "material",
            "item",
            "location",
            "species",
            "faction",
            "faction_state",
            "reference",
            "character",
            "npc",
        }:
            errors.append(f"{entry_path}.save_as.type: unsupported value {save_type}")
        for field in ("entity_id", "id"):
            target = save_as.get(field)
            if target and str(target) in entity_ids:
                warnings.append(f"{entry_path}.save_as.{field}: will update existing entity {target}")
    risks = as_list(entry.get("risks"))
    if yaml_key in {"materials", "species", "factions", "locations"} and not risks:
        warnings.append(f"{entry_path}.risks: should list at least one risk or limitation")


def validate_smoke_file(root: Path, capabilities: list[str], errors: list[str]) -> list[str]:
    path = root / "tests" / "smoke.yaml"
    if not path.exists():
        return []
    try:
        cases = load_smoke_cases(path)
    except ValueError as exc:
        errors.append(str(exc))
        return []
    smoke_ids: list[str] = []
    covered: set[str] = set()
    for index, case in enumerate(cases):
        case_path = f"tests/smoke.yaml.smoke_tests[{index}]"
        case_id = str(case.get("id", ""))
        smoke_ids.append(case_id)
        if not case_id:
            errors.append(f"{case_path}.id: required")
        case_type = case.get("type")
        if case_type not in SMOKE_TYPES:
            errors.append(f"{case_path}.type: unsupported value {case_type}")
        case_capabilities = case.get("capabilities", [])
        if not isinstance(case_capabilities, list) or not all(isinstance(item, str) for item in case_capabilities):
            errors.append(f"{case_path}.capabilities: must be array of strings")
            continue
        for item in case_capabilities:
            if item not in capabilities:
                errors.append(f"{case_path}.capabilities: {item} is not declared in campaign.yaml")
            covered.add(item)
        validate_smoke_case_shape(case, case_path, errors)
    for capability in capabilities:
        if capability not in covered:
            errors.append(f"tests/smoke.yaml: capability {capability} has no smoke test coverage")
    return smoke_ids


def validate_smoke_case_shape(case: dict[str, Any], case_path: str, errors: list[str]) -> None:
    case_type = case.get("type")
    if case_type == "start_turn":
        if not isinstance(case.get("user_text"), str) or not case.get("user_text", "").strip():
            errors.append(f"{case_path}.user_text: required")
    elif case_type == "query":
        if case.get("kind") not in {"scene", "entity", "context"}:
            errors.append(f"{case_path}.kind: must be scene/entity/context")
        if case.get("kind") in {"entity", "context"} and not isinstance(case.get("query_text"), str):
            errors.append(f"{case_path}.query_text: required for entity/context query")
    elif case_type == "preview":
        if not isinstance(case.get("action"), str) or not case.get("action", "").strip():
            errors.append(f"{case_path}.action: required")
        if "options" in case and not isinstance(case.get("options"), dict):
            errors.append(f"{case_path}.options: must be object")
        if "expect_status" in case and not isinstance(case.get("expect_status"), str):
            errors.append(f"{case_path}.expect_status: must be string")
    elif case_type == "validate_delta":
        if not isinstance(case.get("delta"), dict):
            errors.append(f"{case_path}.delta: required object")
    elif case_type == "random_table":
        if not isinstance(case.get("table"), str) or not case.get("table", "").strip():
            errors.append(f"{case_path}.table: required")
    if "contains" in case and not isinstance(case.get("contains"), str):
        errors.append(f"{case_path}.contains: must be string")


def validate_content_references(
    records_by_type: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
    errors: list[str],
) -> None:
    entities = records_by_type.get("entity", [])
    entity_ids = {str(record.get("id")) for record in entities if record.get("id")}
    location_ids = {str(record.get("id")) for record in entities if record.get("type") == "location" and record.get("id")}
    clock_ids = {str(record.get("id")) for record in records_by_type.get("clock", []) if record.get("id")}
    rule_ids = {str(record.get("id")) for record in records_by_type.get("rule", []) if record.get("id")}
    relationship_ids = {str(record.get("id")) for record in records_by_type.get("relationship", []) if record.get("id")}
    world_setting_ids = {str(record.get("id")) for record in records_by_type.get("world_setting", []) if record.get("id")}
    entity_backed_ids = entity_ids | rule_ids | clock_ids | relationship_ids | world_setting_ids
    for index, entity in enumerate(entities):
        path = f"entity[{index}]"
        visibility = str(entity.get("visibility", "known"))
        if visibility not in ALLOWED_ENTITY_VISIBILITY:
            errors.append(f"{path}.visibility: unsupported value {visibility}")
        for field in ("location_id", "owner_id"):
            if entity.get(field) and str(entity[field]) not in entity_ids:
                errors.append(f"{path}.{field}: missing entity {entity[field]}")
        character = entity.get("character", {})
        if isinstance(character, dict) and character.get("species_id") and str(character["species_id"]) not in entity_ids:
            errors.append(f"{path}.character.species_id: missing entity {character['species_id']}")
        location = entity.get("location", {})
        if isinstance(location, dict) and location.get("parent_id") and str(location["parent_id"]) not in location_ids:
            errors.append(f"{path}.location.parent_id: missing location {location['parent_id']}")
    for index, route in enumerate(records_by_type.get("route", [])):
        for field in ("from_location_id", "to_location_id"):
            if route.get(field) and str(route[field]) not in location_ids:
                errors.append(f"route[{index}].{field}: missing location {route[field]}")
    for index, relationship in enumerate(records_by_type.get("relationship", [])):
        for field in ("source_id", "target_id"):
            if relationship.get(field) and str(relationship[field]) not in entity_ids:
                errors.append(f"relationship[{index}].{field}: missing entity {relationship[field]}")
    for index, clock in enumerate(records_by_type.get("clock", [])):
        visibility = str(clock.get("visibility", "visible"))
        if visibility not in ALLOWED_CLOCK_VISIBILITY:
            errors.append(f"clock[{index}].visibility: unsupported value {visibility}")
    for index, setting in enumerate(records_by_type.get("world_setting", [])):
        for field, targets in [
            ("linked_rules", rule_ids),
            ("linked_clocks", clock_ids),
            ("linked_entities", entity_backed_ids),
        ]:
            value = setting.get(field, [])
            if not isinstance(value, list):
                continue
            for target in value:
                if str(target) not in targets:
                    errors.append(f"world_setting[{index}].{field}: missing reference {target}")
    initial_location = config.get("initial_location_id")
    if initial_location and str(initial_location) not in location_ids:
        errors.append(f"campaign.yaml.initial_location_id: missing location {initial_location}")
    player_id = config.get("defaults", {}).get("player_entity_id") if isinstance(config.get("defaults"), dict) else None
    if player_id and str(player_id) not in entity_ids:
        errors.append(f"campaign.yaml.defaults.player_entity_id: missing entity {player_id}")


def load_smoke_cases(path: Path) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"tests/smoke.yaml: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("tests/smoke.yaml: must be object")
    cases = data.get("smoke_tests")
    if not isinstance(cases, list) or not cases:
        raise ValueError("tests/smoke.yaml.smoke_tests: must be non-empty array")
    return [case for case in cases if isinstance(case, dict)]


def run_smoke_case(runtime: GMRuntime, case: dict[str, Any]) -> SmokeCaseResult:
    case_id = str(case.get("id", "unnamed"))
    case_type = str(case.get("type", ""))
    try:
        if case_type == "start_turn":
            result = runtime.start_turn(
                str(case.get("user_text", "")),
                mode=str(case.get("mode", "auto")),
                submode=case.get("submode"),
            )
            ok = result.can_proceed
            message = "" if ok else "; ".join([*result.missing_required, *result.needs_user_confirmation])
            return check_contains(case, result.markdown, SmokeCaseResult(case_id, ok, case_type, message))
        if case_type == "query":
            result = runtime.query(
                str(case.get("kind", "")),
                case.get("query_text"),
                view=str(case.get("view", "player")),
            )
            return check_contains(case, result.text, SmokeCaseResult(case_id, bool(result.text.strip()), case_type))
        if case_type == "preview":
            options = dict(case.get("options", {}) or {})
            if case.get("user_text") and "user_text" not in options:
                options["user_text"] = case["user_text"]
            result = runtime.preview_action(str(case.get("action", "")), options)
            message = "; ".join([*result.errors, *result.missing_required, *result.warnings])
            expected_status = case.get("expect_status")
            if expected_status is not None:
                ok = result.status == str(expected_status)
                if not ok:
                    message = f"expected status {expected_status!r}, got {result.status!r}; {message}"
                return check_contains(case, result.markdown, SmokeCaseResult(case_id, ok, case_type, message))
            return check_contains(case, result.markdown, SmokeCaseResult(case_id, result.ok, case_type, message))
        if case_type == "validate_delta":
            result = runtime.validate_delta(dict(case.get("delta", {}) or {}))
            return SmokeCaseResult(case_id, result.ok, case_type, "; ".join(result.errors))
        if case_type == "random_table":
            text = first_random_table_result(runtime.campaign, str(case.get("table", "")))
            return check_contains(case, text, SmokeCaseResult(case_id, bool(text.strip()), case_type))
        return SmokeCaseResult(case_id, False, case_type, f"unsupported smoke type {case_type}")
    except Exception as exc:
        return SmokeCaseResult(case_id, False, case_type, str(exc))


def check_contains(case: dict[str, Any], text: str, result: SmokeCaseResult) -> SmokeCaseResult:
    needle = case.get("contains")
    if not needle:
        return result
    if str(needle) in text:
        return result
    return SmokeCaseResult(result.case_id, False, result.type, f"expected output to contain {needle!r}")


def first_random_table_result(campaign: Campaign, table_id: str) -> str:
    if not table_id.strip():
        raise ValueError("random_table smoke requires table")
    for path in campaign.content_files("random_tables"):
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for table in document.get("random_tables", []):
            if not isinstance(table, dict) or str(table.get("id", "")) != table_id:
                continue
            entries = table.get("entries", [])
            if not isinstance(entries, list) or not entries:
                raise ValueError(f"random table has no entries: {table_id}")
            for entry in entries:
                if isinstance(entry, dict) and str(entry.get("result", "")).strip():
                    return str(entry["result"])
            raise ValueError(f"random table has no result entries: {table_id}")
    raise ValueError(f"random table not found: {table_id}")


def content_paths(root: Path, raw: Any, errors: list[str], key: str) -> list[Path]:
    values = raw if isinstance(raw, list) else [raw]
    paths: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            errors.append(f"campaign.yaml.content.{key}: entries must be non-empty paths")
            continue
        path = Path(value)
        if path.is_absolute():
            errors.append(f"campaign.yaml.content.{key}: must use relative package path, got {value}")
            continue
        if ".." in path.parts:
            errors.append(f"campaign.yaml.content.{key}: path escapes campaign root {value}")
            continue
        candidate = root / path
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            errors.append(f"campaign.yaml.content.{key}: path escapes campaign root {value}")
            continue
        paths.append(candidate)
    return paths


def render_campaign_validation(result: CampaignValidationResult) -> str:
    lines = ["OK" if result.ok else "FAILED"]
    if result.campaign_id:
        lines.append(f"campaign: {result.campaign_id}")
    if result.package_version:
        lines.append(f"version: {result.package_version}")
    if result.capabilities:
        lines.append("capabilities: " + ", ".join(result.capabilities))
    if result.record_counts:
        lines.extend(["", "| Content Type | Records |", "|--------------|---------|"])
        for name, count in sorted(result.record_counts.items()):
            lines.append(f"| `{name}` | {count} |")
    if result.smoke_tests:
        lines.extend(["", "smoke_tests: " + ", ".join(result.smoke_tests)])
    for warning in result.warnings:
        lines.append(f"- warning: {warning}")
    for error in result.errors:
        lines.append(f"- error: {error}")
    return "\n".join(lines).rstrip() + "\n"


def render_campaign_test(result: CampaignTestResult) -> str:
    lines = [
        "# Campaign Test",
        "",
        f"- status: `{'OK' if result.ok else 'FAILED'}`",
        f"- campaign: `{result.campaign_id}`",
        f"- init: `{'OK' if result.init_ok else 'FAILED'}`",
        f"- health: `{'OK' if result.health_ok else 'FAILED'}`",
        "",
        "## Smoke Tests",
        "",
        "| ID | Type | Status | Message |",
        "|----|------|--------|---------|",
    ]
    for item in result.smoke_results:
        lines.append(f"| `{item.case_id}` | `{item.type}` | {'OK' if item.ok else 'FAILED'} | {item.message} |")
    if not result.smoke_results:
        lines.append("| none |  | FAILED | no smoke tests ran |")
    if result.errors or result.health_errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {item}" for item in result.health_errors)
        lines.extend(f"- {item}" for item in result.errors)
    return "\n".join(lines).rstrip() + "\n"


def prefix_errors(prefix: str, errors: tuple[str, ...] | list[str]) -> list[str]:
    return [f"{prefix}.{error}" for error in errors]


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
