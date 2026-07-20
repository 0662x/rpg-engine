from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from rpg_engine.save_manager import SaveManager


ENGINE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAMPAIGN_SOURCE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
DEFAULT_CONTRACT_PATH = ENGINE_ROOT / "tests" / "fixtures" / "hermes_stdio_compatibility.yaml"
EXPECTED_STEP_IDS = (
    "manifest_initial",
    "stale_candidate_rejected",
    "manifest_refreshed",
    "player_turn_ready",
    "explicit_player_confirmation",
    "wrong_session_rejected",
    "player_confirm_committed",
    "player_confirm_replayed",
    "safe_audit",
)
ALLOWED_STEP_ACTORS = {"client", "fixture", "player", "scripted_model"}
EXPECTED_FIXTURE_ID = "rpg-engine-hermes-stdio-v1"
EXPECTED_PLAYER_TOOLS = (
    "workspace_inspect",
    "campaign_list",
    "save_list",
    "save_current",
    "save_create",
    "save_switch",
    "start_or_continue",
    "intent_manifest",
    "player_turn",
    "player_cancel",
    "player_confirm",
    "campaign_validate",
    "save_inspect",
    "health",
)
STEP_FIELDS = {"id", "actor", "tool", "capture", "arguments", "hook", "expect"}
CANDIDATE_CANONICAL_FIELDS = {
    "contract",
    "kind",
    "mode",
    "action",
    "slots",
    "plan",
    "confidence",
    "missing_slots",
    "needs_confirmation",
    "safety_flags",
    "reason",
}
EXPECTED_CANDIDATE_GENERATIONS = {
    "stale": {
        "action": "rest",
        "slots": {"until": "wire-hidden-slot-canary"},
        "reason": "wire-private-reason-canary",
        "manifest_digest": "stale_zero_sha256",
    },
    "refreshed": {
        "action": "rest",
        "slots": {"until": "morning"},
        "reason": "scripted-model generation refreshed-v1",
        "manifest_digest": "live",
    },
}
EXPECTED_STEP_SHAPES = {
    "manifest_initial": ("client", "intent_manifest", "manifest_initial", "manifest"),
    "stale_candidate_rejected": (
        "scripted_model",
        "player_turn",
        "stale_candidate_rejected",
        "candidate_rejection",
    ),
    "manifest_refreshed": ("client", "intent_manifest", "manifest_refreshed", "manifest"),
    "player_turn_ready": ("scripted_model", "player_turn", "player_turn_ready", "player_turn"),
    "explicit_player_confirmation": (
        "player",
        None,
        "explicit_player_confirmation",
        "explicit_player_confirmation",
    ),
    "wrong_session_rejected": (
        "client",
        "player_confirm",
        "wrong_session_rejected",
        "wrong_confirmation",
    ),
    "player_confirm_committed": (
        "client",
        "player_confirm",
        "player_confirm_committed",
        "player_confirm",
    ),
    "player_confirm_replayed": (
        "client",
        "player_confirm",
        "player_confirm_replayed",
        "player_replay",
    ),
    "safe_audit": ("fixture", None, None, "safe_audit"),
}
EXPECTED_HOOK_FIELDS = {
    "manifest": (
        "schema_version",
        "manifest_digest",
        "safety_vocabulary.version",
        "safety_vocabulary.digest",
    ),
    "candidate_rejection": (
        "ok",
        "error_details.0.code",
        "error_details.0.reason",
        "error_details.0.retriable",
        "error_details.0.action",
    ),
    "player_turn": (
        "ok",
        "status",
        "action",
        "ready_to_confirm",
        "session_id_present",
        "saved",
    ),
    "explicit_player_confirmation": ("confirmed", "session_id_present"),
    "wrong_confirmation": ("ok", "errors.0"),
    "player_confirm": ("ok", "saved", "write_status", "idempotent_replay", "turn_id_present"),
    "player_replay": ("ok", "saved", "write_status", "idempotent_replay", "turn_id_present"),
    "safe_audit": ("tool", "status", "identity.profile", "result.ok"),
}
EXPECTED_STEP_EXPECTATIONS = {
    "manifest_initial": {
        "schema_version": "4",
        "manifest_digest": {"$matches": "sha256"},
        "safety_vocabulary.version": "1",
        "safety_vocabulary.digest": {"$matches": "sha256"},
    },
    "stale_candidate_rejected": {
        "ok": False,
        "error_details.0.code": "INTENT_CONTRACT_VERSION_MISMATCH",
        "error_details.0.reason": "contract_version_mismatch",
        "error_details.0.retriable": True,
        "error_details.0.action": "refresh_manifest_and_regenerate_candidate",
    },
    "manifest_refreshed": {
        "schema_version": "4",
        "manifest_digest": {"$matches": "sha256"},
        "safety_vocabulary.version": "1",
        "safety_vocabulary.digest": {"$matches": "sha256"},
    },
    "player_turn_ready": {
        "ok": True,
        "status": "ready",
        "action": "rest",
        "ready_to_confirm": True,
        "session_id_present": True,
        "saved": False,
    },
    "explicit_player_confirmation": {"confirmed": True, "session_id_present": True},
    "wrong_session_rejected": {
        "ok": False,
        "errors.0": "player_confirm session_id does not match the pending player action",
    },
    "player_confirm_committed": {
        "ok": True,
        "saved": True,
        "write_status": "committed",
        "idempotent_replay": False,
        "turn_id_present": True,
    },
    "player_confirm_replayed": {
        "ok": True,
        "saved": False,
        "write_status": "already_confirmed",
        "idempotent_replay": True,
        "turn_id_present": True,
    },
    "safe_audit": {
        "tool": {"$matches": "nonempty"},
        "status": {"$in": ["ok", "error"]},
        "identity.profile": "player",
        "result.ok": {"$in": [True, False, None]},
    },
}


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("compatibility contract mapping keys must be scalar") from exc
        if duplicate:
            raise ValueError(f"compatibility contract contains duplicate mapping key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class ProviderLaunch:
    command: str
    args: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]

    def value_after(self, option: str) -> str:
        try:
            index = self.args.index(option)
        except ValueError as exc:
            raise KeyError(option) from exc
        if index + 1 >= len(self.args):
            raise ValueError(f"provider option has no value: {option}")
        return self.args[index + 1]


@dataclass(frozen=True)
class ProviderFixture:
    root: Path
    campaign_path: Path
    save_path: Path
    launch: ProviderLaunch
    network_guard_path: Path
    network_attempts_path: Path
    network_guard_ready_path: Path
    dotenv_attempts_path: Path
    dotenv_path: Path


@dataclass(frozen=True)
class ScriptStep:
    id: str
    actor: str
    tool: str | None
    capture: str | None
    arguments: Mapping[str, Any]
    hook: str | None
    expect: Mapping[str, Any]


@dataclass(frozen=True)
class ScriptContract:
    schema_version: str
    fixture_id: str
    player_tools: tuple[str, ...]
    steps: tuple[ScriptStep, ...]
    candidate_generations: Mapping[str, Mapping[str, Any]]
    hooks: Mapping[str, tuple[str, ...]]

    def step(self, step_id: str) -> ScriptStep:
        for item in self.steps:
            if item.id == step_id:
                return item
        raise KeyError(step_id)

    def capture_references(self) -> tuple[str, ...]:
        return tuple(step.capture for step in self.steps if step.capture)

    def resolve_arguments(self, step_id: str, captures: dict[str, Any]) -> dict[str, Any]:
        step = self.step(step_id)
        resolved = self._resolve_value(step.arguments, captures)
        if not isinstance(resolved, dict):  # pragma: no cover - schema validation owns this path
            raise ValueError("compatibility step arguments must resolve to an object")
        _validate_resolved_step_arguments(step, resolved)
        return resolved

    def _resolve_value(self, value: Any, captures: dict[str, Any]) -> Any:
        if isinstance(value, list | tuple):
            return [self._resolve_value(item, captures) for item in value]
        if not isinstance(value, Mapping):
            return value
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise ValueError("compatibility $ref must be the only key and name a capture path")
            capture_name, separator, nested_path = value["$ref"].partition(".")
            if capture_name not in captures:
                raise KeyError(f"unresolved compatibility capture: {capture_name}")
            captured = captures[capture_name]
            return _strict_nested_value(captured, nested_path) if separator else captured
        if "$candidate" in value:
            if set(value) != {"$candidate"} or not isinstance(value["$candidate"], Mapping):
                raise ValueError("compatibility $candidate must be the only key and contain a spec")
            spec = value["$candidate"]
            if set(spec) != {"generation", "manifest", "overrides"}:
                raise ValueError("compatibility $candidate spec must contain generation, manifest, and overrides")
            manifest = self._resolve_value(spec["manifest"], captures)
            overrides = self._resolve_value(spec["overrides"], captures)
            if not isinstance(manifest, dict) or not isinstance(overrides, dict):
                raise ValueError("compatibility candidate manifest and overrides must resolve to objects")
            forbidden = sorted(set(overrides) & CANDIDATE_CANONICAL_FIELDS)
            if forbidden:
                raise ValueError(
                    "compatibility candidate overrides cannot replace canonical fields: "
                    + ", ".join(forbidden)
                )
            candidate = self.build_candidate(str(spec["generation"]), manifest)
            candidate.update(overrides)
            return candidate
        if any(str(key).startswith("$") for key in value):
            raise ValueError("unsupported compatibility interpolation operator")
        return {str(key): self._resolve_value(item, captures) for key, item in value.items()}

    def assert_step_expectation(self, step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        step = self.step(step_id)
        if not step.hook:
            raise ValueError(f"compatibility step has no hook: {step_id}")
        projected = self.project_hook(step.hook, payload)
        for field, expectation in step.expect.items():
            if not _expectation_matches(projected.get(field), expectation):
                raise AssertionError(
                    f"compatibility expectation failed for {step_id}.{field}: "
                    f"expected {expectation!r}, got {projected.get(field)!r}"
                )
        if step_id == "safe_audit":
            expected_status = "error" if projected["result.ok"] is False else "ok"
            if projected["status"] != expected_status:
                raise AssertionError(
                    "compatibility safe audit status must agree with the bounded result.ok summary"
                )
        return projected

    def hook_fields(self, hook_id: str) -> tuple[str, ...]:
        try:
            return self.hooks[hook_id]
        except KeyError as exc:
            raise KeyError(f"unknown compatibility hook: {hook_id}") from exc

    def project_hook(self, hook_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for field in self.hook_fields(hook_id):
            if field.endswith("_present"):
                source_field = field.removesuffix("_present")
                if source_field == "turn_id":
                    source_field = "save.current_turn_id"
                projected[field] = bool(_nested_value(payload, source_field))
            else:
                projected[field] = _nested_value(payload, field)
        return projected

    def build_candidate(self, generation_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        try:
            generation = self.candidate_generations[generation_id]
        except KeyError as exc:
            raise KeyError(f"unknown candidate generation: {generation_id}") from exc
        safety = manifest.get("safety_vocabulary")
        if not isinstance(safety, dict):
            raise ValueError("manifest safety_vocabulary must be an object")
        manifest_digest = str(manifest.get("manifest_digest") or "")
        if generation["manifest_digest"] == "stale_zero_sha256":
            manifest_digest = "0" * 64
        elif generation["manifest_digest"] != "live":
            raise ValueError(f"unsupported manifest digest source: {generation['manifest_digest']}")
        return {
            "contract": {
                "manifest_schema_version": str(manifest.get("schema_version") or ""),
                "manifest_digest": manifest_digest,
                "safety_vocabulary_version": str(safety.get("version") or ""),
                "safety_vocabulary_digest": str(safety.get("digest") or ""),
            },
            "kind": "single",
            "mode": "action",
            "action": str(generation["action"]),
            "slots": dict(generation["slots"]),
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [],
            "reason": str(generation["reason"]),
        }


def prepare_provider_fixture(
    root: str | Path,
    *,
    engine_root: str | Path = ENGINE_ROOT,
    campaign_source: str | Path = DEFAULT_CAMPAIGN_SOURCE,
    protected_paths: tuple[Path, ...] | None = None,
) -> ProviderFixture:
    resolved_root = Path(root).expanduser().resolve()
    resolved_engine = Path(engine_root).expanduser().resolve()
    resolved_source = Path(campaign_source).expanduser().resolve()
    for label, path in (("workspace", resolved_root), ("engine", resolved_engine)):
        if os.pathsep in str(path):
            raise ValueError(f"compatibility {label} path cannot contain {os.pathsep!r}")
    protected = tuple(
        dict.fromkeys(
            (
                *default_protected_paths(resolved_engine),
                resolved_source,
                *(protected_paths or ()),
            )
        )
    )
    for protected_path in protected:
        resolved_protected = protected_path.expanduser().resolve()
        if (
            resolved_root == resolved_protected
            or resolved_root.is_relative_to(resolved_protected)
            or resolved_protected.is_relative_to(resolved_root)
        ):
            raise ValueError(f"compatibility workspace aliases protected data: {resolved_protected}")
    resolved_root.mkdir(parents=True, exist_ok=True)
    if any(resolved_root.iterdir()):
        raise ValueError("compatibility workspace must be empty")

    campaign_path = resolved_root / "campaigns" / "minimal"
    shutil.copytree(resolved_source, campaign_path)
    manager = SaveManager(resolved_root, default_campaign="campaigns/minimal")
    started = manager.start_or_continue(campaign="campaigns/minimal")
    if not started.get("ok") or not isinstance(started.get("save"), dict):
        raise RuntimeError(f"failed to prepare compatibility Save: {started.get('errors', [])}")
    save_path = resolved_root / str(started["save"]["path"])

    guard_dir = resolved_root / ".aigm" / "network-guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    process_cwd = resolved_root / ".aigm" / "provider-cwd"
    process_cwd.mkdir(parents=True, exist_ok=True)
    network_attempts_path = resolved_root / "logs" / "network-attempts.jsonl"
    network_guard_ready_path = resolved_root / "logs" / "network-guard-ready.json"
    dotenv_attempts_path = resolved_root / "logs" / "dotenv-attempts.jsonl"
    dotenv_path = resolved_root / ".env"
    network_guard_path = guard_dir / "sitecustomize.py"
    network_guard_path.write_text(_network_guard_source(), encoding="utf-8")
    dotenv_path.write_text(
        "RPG_ENGINE_COMPATIBILITY_DOTENV_CANARY=must-not-load\n",
        encoding="utf-8",
    )
    launch = ProviderLaunch(
        command=sys.executable,
        args=(
            "-m",
            "rpg_engine",
            "mcp",
            "serve",
            "--root",
            str(resolved_root),
            "--default-campaign",
            "campaigns/minimal",
            "--registry-active",
            "--mcp-profile",
            "player",
            "--ai-profile",
            "off",
            "--semantic-ai",
            "off",
            "--intent-ai",
            "off",
            "--state-audit-ai",
            "off",
            "--archivist-ai",
            "off",
            "--no-archivist-enqueue",
            "--transport",
            "stdio",
        ),
        cwd=process_cwd,
        environment={
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": os.pathsep.join((str(guard_dir), str(resolved_engine))),
            "RPG_ENGINE_NETWORK_GUARD_LOG": str(network_attempts_path),
            "RPG_ENGINE_NETWORK_GUARD_READY": str(network_guard_ready_path),
            "RPG_ENGINE_DOTENV_GUARD_LOG": str(dotenv_attempts_path),
            "RPG_ENGINE_DOTENV_CANARY_PATH": str(dotenv_path),
        },
    )
    return ProviderFixture(
        root=resolved_root,
        campaign_path=campaign_path,
        save_path=save_path,
        launch=launch,
        network_guard_path=network_guard_path,
        network_attempts_path=network_attempts_path,
        network_guard_ready_path=network_guard_ready_path,
        dotenv_attempts_path=dotenv_attempts_path,
        dotenv_path=dotenv_path,
    )


def load_script_contract(path: str | Path = DEFAULT_CONTRACT_PATH) -> ScriptContract:
    source = Path(path).read_text(encoding="utf-8")
    payload = yaml.load(source, Loader=_UniqueKeySafeLoader)
    if not isinstance(payload, dict):
        raise ValueError("compatibility contract must be an object")
    if set(payload) != {
        "schema_version",
        "fixture_id",
        "player_tools",
        "steps",
        "candidate_generations",
        "hooks",
    }:
        raise ValueError("compatibility contract top-level fields must match the versioned schema")
    if str(payload.get("schema_version")) != "1":
        raise ValueError("compatibility contract schema_version must be 1")
    if payload.get("fixture_id") != EXPECTED_FIXTURE_ID:
        raise ValueError(f"compatibility contract fixture_id must be {EXPECTED_FIXTURE_ID}")
    raw_player_tools = payload.get("player_tools")
    if (
        not isinstance(raw_player_tools, list)
        or any(not isinstance(tool, str) or not tool for tool in raw_player_tools)
        or tuple(raw_player_tools) != EXPECTED_PLAYER_TOOLS
    ):
        raise ValueError("compatibility contract player_tools must match the schema-v1 surface")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("compatibility contract steps must be a list")
    steps = tuple(_parse_step(item) for item in raw_steps)
    if tuple(step.id for step in steps) != EXPECTED_STEP_IDS:
        raise ValueError("compatibility contract steps must use the canonical order")
    captures = tuple(step.capture for step in steps if step.capture)
    if len(captures) != len(set(captures)):
        raise ValueError("compatibility contract capture names must be unique")
    available_captures: set[str] = set()
    for step in steps:
        for reference in _contract_references(step.arguments):
            if reference not in available_captures:
                raise ValueError(f"compatibility reference must target an earlier capture: {reference}")
        if step.capture:
            available_captures.add(step.capture)

    raw_generations = payload.get("candidate_generations")
    if not isinstance(raw_generations, dict) or set(raw_generations) != {"stale", "refreshed"}:
        raise ValueError("compatibility contract must define stale and refreshed candidate generations")
    candidate_generations = {
        str(key): _parse_candidate_generation(str(key), value)
        for key, value in raw_generations.items()
    }
    raw_hooks = payload.get("hooks")
    if not isinstance(raw_hooks, dict) or set(raw_hooks) != set(EXPECTED_HOOK_FIELDS):
        raise ValueError("compatibility contract hook ids must match the versioned schema")
    hooks: dict[str, tuple[str, ...]] = {}
    for key, value in raw_hooks.items():
        if (
            not isinstance(value, dict)
            or set(value) != {"fields"}
            or not isinstance(value.get("fields"), list)
        ):
            raise ValueError(f"compatibility hook fields must be a list: {key}")
        fields = tuple(str(field) for field in value["fields"])
        if not fields or len(fields) != len(set(fields)):
            raise ValueError(f"compatibility hook fields must be unique and non-empty: {key}")
        if fields != EXPECTED_HOOK_FIELDS[str(key)]:
            raise ValueError(f"compatibility hook fields must match the bounded schema: {key}")
        hooks[str(key)] = fields
    return ScriptContract(
        schema_version="1",
        fixture_id=EXPECTED_FIXTURE_ID,
        player_tools=EXPECTED_PLAYER_TOOLS,
        steps=steps,
        candidate_generations=_deep_freeze(candidate_generations),
        hooks=_deep_freeze(hooks),
    )


def stdio_server_parameters(fixture: ProviderFixture):
    try:
        from mcp import StdioServerParameters
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the optional extra
        raise RuntimeError("the compatibility fixture requires the project mcp extra") from exc
    return StdioServerParameters(
        command=fixture.launch.command,
        args=list(fixture.launch.args),
        env=dict(fixture.launch.environment),
        cwd=fixture.launch.cwd,
    )


def decode_tool_result(result: Any) -> dict[str, Any]:
    if bool(getattr(result, "isError", False)):
        raise ValueError("MCP tool returned a protocol-level error")
    content = getattr(result, "content", None)
    if not isinstance(content, list):
        raise ValueError("MCP tool result content must be a list")
    if len(content) != 1 or getattr(content[0], "type", "") != "text":
        raise ValueError("MCP tool result must contain exactly one TextContent block")
    text_blocks = [str(content[0].text)]
    try:
        payload = json.loads(text_blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError("MCP tool text block must contain JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("MCP tool JSON payload must be an object")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        if not isinstance(structured, dict) or not _strict_json_equal(structured, payload):
            raise ValueError("MCP structuredContent must exactly match the TextContent JSON object")
    meta = getattr(result, "meta", None)
    if meta not in (None, {}):
        raise ValueError("MCP tool result must not contain an opaque _meta envelope")
    return payload


def default_protected_paths(engine_root: str | Path = ENGINE_ROOT) -> tuple[Path, ...]:
    engine = Path(engine_root).expanduser().resolve()
    hermes_root = engine.parent
    workspace_root = hermes_root / "rp"
    campaign_root = _configured_path(
        "RPG_ENGINE_CURRENT_CAMPAIGN_ROOT",
        workspace_root / "isekai-farm-campaign-native-v1",
    )
    save_root = _configured_path(
        "RPG_ENGINE_CURRENT_SAVE_ROOT",
        workspace_root / "isekai-farm-save-native-v1",
    )
    candidates = (
        engine / "tests" / "fixtures" / "minimal_campaign",
        campaign_root,
        save_root,
        workspace_root / ".aigm" / "save-registry.json",
        campaign_root.parent / ".aigm" / "save-registry.json",
        save_root.parent / ".aigm" / "save-registry.json",
    )
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def fingerprint_paths(paths: tuple[Path, ...]) -> dict[str, str]:
    return {str(path.expanduser().resolve()): _path_digest(path.expanduser().resolve()) for path in paths}


def _parse_step(value: Any) -> ScriptStep:
    if not isinstance(value, dict):
        raise ValueError("compatibility step must be an object")
    if set(value) != STEP_FIELDS:
        raise ValueError("compatibility step fields must match the versioned schema")
    step_id = str(value.get("id") or "")
    actor = str(value.get("actor") or "")
    if actor not in ALLOWED_STEP_ACTORS:
        raise ValueError(f"unsupported compatibility actor: {actor}")
    arguments = value.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("compatibility step arguments must be an object")
    expect = value.get("expect")
    if not isinstance(expect, dict):
        raise ValueError("compatibility step expect must be an object")
    tool = str(value["tool"]) if value.get("tool") else None
    capture = str(value["capture"]) if value.get("capture") else None
    hook = str(value["hook"]) if value.get("hook") else None
    expected_shape = EXPECTED_STEP_SHAPES.get(step_id)
    if expected_shape != (actor, tool, capture, hook):
        raise ValueError(f"compatibility step shape must match the versioned schema: {step_id}")
    _validate_raw_step_arguments(step_id, arguments)
    expected_fields = EXPECTED_HOOK_FIELDS.get(hook or "", ())
    if tuple(expect) != expected_fields:
        raise ValueError(f"compatibility step expectations must match hook fields: {step_id}")
    if not _strict_json_equal(expect, EXPECTED_STEP_EXPECTATIONS.get(step_id)):
        raise ValueError(f"compatibility step expectations must match the versioned schema: {step_id}")
    for field, expectation in expect.items():
        _validate_expectation_spec(field, expectation)
    return ScriptStep(
        id=step_id,
        actor=actor,
        tool=tool,
        capture=capture,
        arguments=_deep_freeze({str(key): item for key, item in arguments.items()}),
        hook=hook,
        expect=_deep_freeze({str(key): item for key, item in expect.items()}),
    )


def _configured_path(name: str, default: Path) -> Path:
    configured = os.environ.get(name)
    return Path(configured) if configured is not None and configured.strip() else default


def _validate_raw_step_arguments(step_id: str, arguments: dict[Any, Any]) -> None:
    if step_id in {"manifest_initial", "manifest_refreshed", "safe_audit"}:
        if arguments:
            raise ValueError(f"compatibility step must not declare arguments: {step_id}")
        return
    if step_id == "stale_candidate_rejected":
        if set(arguments) != {"user_text", "external_intent_candidate", "platform", "session_key"}:
            raise ValueError("stale candidate step arguments must match the versioned schema")
        for field in ("user_text", "platform", "session_key"):
            if not isinstance(arguments[field], str) or not arguments[field]:
                raise ValueError(f"stale candidate {field} must be a non-empty string")
        _validate_candidate_operator(
            arguments["external_intent_candidate"],
            generation="stale",
            manifest_capture="manifest_initial",
            override_fields={"Private-Reasoning"},
        )
        return
    if step_id == "player_turn_ready":
        if set(arguments) != {"user_text", "external_intent_candidate"}:
            raise ValueError("player turn step arguments must match the versioned schema")
        if not isinstance(arguments["user_text"], str) or not arguments["user_text"]:
            raise ValueError("player turn user_text must be a non-empty string")
        _validate_candidate_operator(
            arguments["external_intent_candidate"],
            generation="refreshed",
            manifest_capture="manifest_refreshed",
            override_fields=set(),
        )
        return
    if step_id == "explicit_player_confirmation":
        if not _strict_json_equal(arguments, {
            "confirmed": True,
            "session_id": {"$ref": "player_turn_ready.session_id"},
        }):
            raise ValueError("explicit player confirmation must affirm the captured pending session")
        return
    if step_id == "wrong_session_rejected":
        if not _strict_json_equal(arguments, {"session_id": "player_action:wrong-wire-canary"}):
            raise ValueError("wrong-session step must use the canonical invalid session canary")
        return
    if step_id in {"player_confirm_committed", "player_confirm_replayed"}:
        if not _strict_json_equal(
            arguments,
            {"session_id": {"$ref": "explicit_player_confirmation.session_id"}},
        ):
            raise ValueError(f"compatibility confirm step must use the explicit player capture: {step_id}")
        return
    raise ValueError(f"unsupported compatibility step arguments: {step_id}")


def _validate_candidate_operator(
    value: Any,
    *,
    generation: str,
    manifest_capture: str,
    override_fields: set[str],
) -> None:
    if not isinstance(value, dict) or set(value) != {"$candidate"}:
        raise ValueError("external_intent_candidate must use the versioned $candidate operator")
    spec = value["$candidate"]
    if not isinstance(spec, dict) or set(spec) != {"generation", "manifest", "overrides"}:
        raise ValueError("compatibility $candidate spec must contain generation, manifest, and overrides")
    if spec["generation"] != generation or spec["manifest"] != {"$ref": manifest_capture}:
        raise ValueError("compatibility candidate generation and manifest capture must match the step")
    overrides = spec["overrides"]
    if not isinstance(overrides, dict) or set(overrides) != override_fields:
        raise ValueError("compatibility candidate override fields must match the versioned schema")
    if any(not isinstance(item, str) or not item for item in overrides.values()):
        raise ValueError("compatibility candidate override values must be non-empty strings")


def _validate_resolved_step_arguments(step: ScriptStep, arguments: dict[str, Any]) -> None:
    if step.id == "explicit_player_confirmation":
        session_id = arguments.get("session_id")
        if arguments.get("confirmed") is not True or not isinstance(session_id, str) or not session_id:
            raise ValueError("explicit player confirmation requires a non-empty captured session_id")
    elif step.id in {"player_confirm_committed", "player_confirm_replayed"}:
        session_id = arguments.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError(f"compatibility confirm requires a non-empty session_id: {step.id}")


def _validate_expectation_spec(field: str, expectation: Any) -> None:
    if isinstance(expectation, dict):
        if set(expectation) == {"$matches"} and expectation["$matches"] in {"sha256", "nonempty"}:
            return
        if set(expectation) == {"$in"} and isinstance(expectation["$in"], list) and expectation["$in"]:
            if all(isinstance(item, str | bool) or item is None for item in expectation["$in"]):
                return
        if set(expectation) == {"$type"} and expectation["$type"] == "boolean":
            return
        raise ValueError(f"unsupported compatibility expectation operator: {field}")
    if not isinstance(expectation, str | bool | int | float) and expectation is not None:
        raise ValueError(f"compatibility expectation must be bounded scalar: {field}")


def _expectation_matches(value: Any, expectation: Any) -> bool:
    if not isinstance(expectation, Mapping):
        return type(value) is type(expectation) and value == expectation
    if "$matches" in expectation:
        if expectation["$matches"] == "sha256":
            return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
        return isinstance(value, str) and bool(value.strip())
    if "$in" in expectation:
        return any(type(value) is type(item) and value == item for item in expectation["$in"])
    if "$type" in expectation:
        return isinstance(value, bool)
    return False  # pragma: no cover - load-time validation owns this path


def _contract_references(value: Any) -> tuple[str, ...]:
    references: list[str] = []
    if isinstance(value, list):
        for item in value:
            references.extend(_contract_references(item))
    elif isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"} or not isinstance(value["$ref"], str):
                raise ValueError("compatibility $ref must be the only key and name a capture path")
            references.append(value["$ref"].partition(".")[0])
        elif "$candidate" in value:
            if set(value) != {"$candidate"} or not isinstance(value["$candidate"], dict):
                raise ValueError("compatibility $candidate must be the only key and contain a spec")
            spec = value["$candidate"]
            if set(spec) != {"generation", "manifest", "overrides"}:
                raise ValueError("compatibility $candidate spec must contain generation, manifest, and overrides")
            references.extend(_contract_references(spec["manifest"]))
            references.extend(_contract_references(spec["overrides"]))
        elif any(str(key).startswith("$") for key in value):
            raise ValueError("unsupported compatibility interpolation operator")
        else:
            for item in value.values():
                references.extend(_contract_references(item))
    return tuple(references)


def _nested_value(payload: Any, field: str) -> Any:
    value = payload
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    if isinstance(value, dict | list):
        raise ValueError(f"compatibility hook cannot project nested payloads: {field}")
    return value


def _strict_nested_value(payload: Any, field: str) -> Any:
    value = payload
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise KeyError(f"compatibility capture path is missing: {field}")
    if value is None:
        raise ValueError(f"compatibility capture path cannot resolve to null: {field}")
    return value


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        digest.update(b"MISSING\0")
        return digest.hexdigest()
    if path.is_file():
        digest.update(b"F\0")
        digest.update(path.read_bytes())
        return digest.hexdigest()
    if not path.is_dir():
        raise ValueError(f"protected path must be a file or directory: {path}")
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path).as_posix()
        if item.is_symlink():
            raise ValueError(f"protected path tree cannot contain symlinks: {item}")
        elif item.is_dir():
            digest.update(f"D:{relative}\0".encode())
        elif item.is_file():
            digest.update(f"F:{relative}\0".encode())
            digest.update(item.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _parse_candidate_generation(generation_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("candidate generation must be an object")
    slots = value.get("slots")
    if not isinstance(slots, dict):
        raise ValueError("candidate generation slots must be an object")
    required = {"action", "slots", "reason", "manifest_digest"}
    if set(value) != required:
        raise ValueError("candidate generation fields must match the versioned schema")
    if not _strict_json_equal(value, EXPECTED_CANDIDATE_GENERATIONS.get(generation_id)):
        raise ValueError(f"candidate generation content must match the versioned schema: {generation_id}")
    return {
        "action": str(value["action"]),
        "slots": dict(slots),
        "reason": str(value["reason"]),
        "manifest_digest": str(value["manifest_digest"]),
    }


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _strict_json_equal(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if isinstance(value, dict):
        return set(value) == set(expected) and all(
            _strict_json_equal(value[key], expected[key]) for key in value
        )
    if isinstance(value, list):
        return len(value) == len(expected) and all(
            _strict_json_equal(item, expected_item)
            for item, expected_item in zip(value, expected, strict=True)
        )
    return value == expected


def _network_guard_source() -> str:
    return """\
import builtins
import io
import json
import os
import socket
import sys
from pathlib import Path

_LOG = Path(os.environ["RPG_ENGINE_NETWORK_GUARD_LOG"])
_READY = Path(os.environ["RPG_ENGINE_NETWORK_GUARD_READY"])
_DOTENV_LOG = Path(os.environ["RPG_ENGINE_DOTENV_GUARD_LOG"])
_DOTENV_CANARY = Path(os.environ["RPG_ENGINE_DOTENV_CANARY_PATH"]).resolve()
_BUILTIN_OPEN = builtins.open
_IO_OPEN = io.open
_OS_OPEN = os.open


def _deny(operation):
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _IO_OPEN(_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"operation": operation}, sort_keys=True) + "\\n")
    raise RuntimeError("network access is forbidden by the compatibility fixture")


def _dotenv_target(file, *, dir_fd=None):
    try:
        path = Path(os.fsdecode(os.fspath(file)))
    except TypeError:
        return None
    if not path.is_absolute():
        if dir_fd is None:
            path = Path.cwd() / path
        else:
            descriptor_root = Path(f"/dev/fd/{dir_fd}")
            try:
                path = descriptor_root.resolve(strict=True) / path
            except OSError:
                return path
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _is_dotenv_read(file, *, dir_fd=None):
    target = _dotenv_target(file, dir_fd=dir_fd)
    if target is None:
        return False, ""
    filename = target.name
    lowered = filename.casefold()
    if lowered == ".env" or lowered.startswith(".env."):
        return True, filename
    try:
        aliases_canary = target == _DOTENV_CANARY or (
            target.exists() and _DOTENV_CANARY.exists() and os.path.samefile(target, _DOTENV_CANARY)
        )
    except OSError:
        aliases_canary = False
    return aliases_canary, filename


def _deny_dotenv(filename):
    _DOTENV_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _IO_OPEN(_DOTENV_LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"operation": "open", "name": filename}, sort_keys=True) + "\\n")
    raise RuntimeError("dotenv access is forbidden by the compatibility fixture")


def _guarded_file_open(file, *args, **kwargs):
    is_dotenv, filename = _is_dotenv_read(file)
    if is_dotenv:
        _deny_dotenv(filename)
    return _BUILTIN_OPEN(file, *args, **kwargs)


def _guarded_io_open(file, *args, **kwargs):
    is_dotenv, filename = _is_dotenv_read(file)
    if is_dotenv:
        _deny_dotenv(filename)
    return _IO_OPEN(file, *args, **kwargs)


def _guarded_os_open(file, flags, mode=0o777, *, dir_fd=None):
    is_dotenv, filename = _is_dotenv_read(file, dir_fd=dir_fd)
    if is_dotenv:
        _deny_dotenv(filename)
    if dir_fd is None:
        return _OS_OPEN(file, flags, mode)
    return _OS_OPEN(file, flags, mode, dir_fd=dir_fd)


_DNS_AUDIT_EVENTS = {
    "socket.getaddrinfo",
    "socket.gethostbyaddr",
    "socket.gethostbyname",
    "socket.gethostbyname_ex",
    "socket.getnameinfo",
}


def _network_audit(event, args):
    if event == "open" and args:
        is_dotenv, filename = _is_dotenv_read(args[0])
        if is_dotenv:
            _deny_dotenv(filename)
        return
    if event == "socket.__new__":
        family = args[1] if len(args) > 1 else None
        if family in {socket.AF_INET, socket.AF_INET6}:
            _deny(event)
        return
    if event in _DNS_AUDIT_EVENTS:
        _deny(event)
    if event.startswith("socket.") and args:
        family = getattr(args[0], "family", None)
        if family in {socket.AF_INET, socket.AF_INET6}:
            _deny(event)


sys.addaudithook(_network_audit)
builtins.open = _guarded_file_open
io.open = _guarded_io_open
os.open = _guarded_os_open
_READY.parent.mkdir(parents=True, exist_ok=True)
_READY.write_text(json.dumps({"loaded": True, "pid": os.getpid()}, sort_keys=True) + "\\n", encoding="utf-8")
"""
