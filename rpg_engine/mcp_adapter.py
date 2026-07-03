from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ai.defaults import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
    DEFAULT_INTENT_TIMEOUT_SECONDS,
    DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
    DEFAULT_STATE_AUDIT_AI,
    DEFAULT_STATE_AUDIT_ENABLED,
    DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
)
from .ai.config import AI_HELPER_BACKENDS, AI_HELPER_FALLBACK_BACKENDS, AI_PROFILES, resolve_ai_helper_settings
from .campaign_validation import validate_campaign_package
from .db import utc_now
from .game_session import hash_identity
from .intent_manifest import build_intent_manifest
from .runtime import GMRuntime
from .save_manager import SaveManager
from .save_service import inspect_v1_save
from .validation_issues import issues_from_messages


MCP_SERVER_NAME = "aigm-kernel"
PLAYER_PROFILE = "player"
DEVELOPER_PROFILE = "developer"
TRUSTED_GM_PROFILE = "trusted_gm"
MAINTENANCE_PROFILE = "maintenance"
ADMIN_PROFILE = "admin"
MCP_PROFILES = {
    PLAYER_PROFILE,
    DEVELOPER_PROFILE,
    TRUSTED_GM_PROFILE,
    MAINTENANCE_PROFILE,
    ADMIN_PROFILE,
}
LOW_LEVEL_PROFILES = {
    DEVELOPER_PROFILE,
    TRUSTED_GM_PROFILE,
    MAINTENANCE_PROFILE,
    ADMIN_PROFILE,
}
HIDDEN_READ_PROFILES = {
    TRUSTED_GM_PROFILE,
    MAINTENANCE_PROFILE,
    ADMIN_PROFILE,
}
PLAYER_MCP_TOOL_NAMES = (
    "workspace_inspect",
    "campaign_list",
    "save_list",
    "save_current",
    "save_create",
    "save_switch",
    "start_or_continue",
    "intent_manifest",
    "player_turn",
    "player_confirm",
    "campaign_validate",
    "save_inspect",
    "health",
)
LOW_LEVEL_MCP_TOOL_NAMES = (
    "player_query",
    "player_act",
    "start_turn",
    "intent_preflight",
    "query",
    "preview_from_text",
    "preview_action",
    "validate_delta",
    "commit_turn",
)
MCP_TOOL_NAMES = PLAYER_MCP_TOOL_NAMES + LOW_LEVEL_MCP_TOOL_NAMES


def mcp_tool_names_for_profile(profile: str) -> tuple[str, ...]:
    normalized = str(profile or PLAYER_PROFILE).strip() or PLAYER_PROFILE
    if normalized in LOW_LEVEL_PROFILES:
        return MCP_TOOL_NAMES
    return PLAYER_MCP_TOOL_NAMES


def has_override_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    return True


def configured_value(value: Any, default: Any) -> Any:
    return value if has_override_value(value) else default


@dataclass(frozen=True)
class MCPAdapterConfig:
    root: Path
    default_campaign: str | None = None
    default_save: str | None = None
    default_starter_save: str | None = None
    registry_active: bool = False
    mcp_profile: str = PLAYER_PROFILE
    ai_profile: str = "off"
    semantic_ai: str = "off"
    semantic_provider: str = DEFAULT_AI_PROVIDER
    semantic_model: str = DEFAULT_AI_MODEL
    semantic_timeout: int = DEFAULT_SEMANTIC_TIMEOUT_SECONDS
    intent_ai: str = "off"
    intent_backend: str = "direct"
    intent_provider: str = DEFAULT_AI_PROVIDER
    intent_model: str = DEFAULT_AI_MODEL
    intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS
    intent_base_url: str = ""
    intent_api_key_env: str = ""
    intent_fallback_backend: str = "off"
    state_audit_ai: str = DEFAULT_STATE_AUDIT_AI
    state_audit_provider: str = DEFAULT_AI_PROVIDER
    state_audit_model: str = DEFAULT_AI_MODEL
    state_audit_timeout: int = DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS
    archivist_suggest: bool = False
    archivist_ai: str = "off"
    archivist_provider: str = DEFAULT_AI_PROVIDER
    archivist_model: str = DEFAULT_AI_MODEL
    archivist_timeout: int = DEFAULT_ARCHIVIST_TIMEOUT_SECONDS
    archivist_enqueue: bool = True
    audit_log: Path | None = None

    @classmethod
    def from_values(
        cls,
        root: str | Path,
        *,
        default_campaign: str | None = None,
        default_save: str | None = None,
        default_starter_save: str | None = None,
        registry_active: bool = False,
        mcp_profile: str = PLAYER_PROFILE,
        ai_profile: str = "off",
        ai_provider: str | None = None,
        ai_model: str | None = None,
        ai_timeout: int | None = None,
        semantic_ai: str | None = None,
        semantic_provider: str | None = None,
        semantic_model: str | None = None,
        semantic_timeout: int | None = None,
        intent_ai: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        state_audit_ai: str | None = None,
        state_audit_provider: str | None = None,
        state_audit_model: str | None = None,
        state_audit_timeout: int | None = None,
        archivist_suggest: bool | None = None,
        archivist_ai: str | None = None,
        archivist_provider: str | None = None,
        archivist_model: str | None = None,
        archivist_timeout: int | None = None,
        archivist_enqueue: bool = True,
        audit_log: str | Path | None = None,
    ) -> "MCPAdapterConfig":
        resolved_root = Path(root).expanduser().resolve()
        ai = resolve_ai_helper_settings(
            profile=ai_profile,
            provider=ai_provider,
            model=ai_model,
            timeout=ai_timeout,
            semantic_ai=semantic_ai,
            semantic_provider=semantic_provider,
            semantic_model=semantic_model,
            semantic_timeout=semantic_timeout,
            intent_ai=intent_ai,
            intent_backend=intent_backend,
            intent_provider=intent_provider,
            intent_model=intent_model,
            intent_timeout=intent_timeout,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
            state_audit_ai=state_audit_ai,
            state_audit_provider=state_audit_provider,
            state_audit_model=state_audit_model,
            state_audit_timeout=state_audit_timeout,
            archivist_suggest=archivist_suggest,
            archivist_ai=archivist_ai,
            archivist_provider=archivist_provider,
            archivist_model=archivist_model,
            archivist_timeout=archivist_timeout,
        )
        return cls(
            root=resolved_root,
            default_campaign=normalize_optional_relative(default_campaign, "default_campaign"),
            default_save=normalize_optional_relative(default_save, "default_save"),
            default_starter_save=normalize_optional_relative(default_starter_save, "default_starter_save"),
            registry_active=registry_active,
            mcp_profile=normalize_mcp_profile(mcp_profile),
            ai_profile=ai.profile,
            semantic_ai=ai.semantic_ai,
            semantic_provider=ai.semantic_provider,
            semantic_model=ai.semantic_model,
            semantic_timeout=ai.semantic_timeout,
            intent_ai=ai.intent_ai,
            intent_backend=ai.intent_backend,
            intent_provider=ai.intent_provider,
            intent_model=ai.intent_model,
            intent_timeout=ai.intent_timeout,
            intent_base_url=ai.intent_base_url,
            intent_api_key_env=ai.intent_api_key_env,
            intent_fallback_backend=ai.intent_fallback_backend,
            state_audit_ai=ai.state_audit_ai,
            state_audit_provider=ai.state_audit_provider,
            state_audit_model=ai.state_audit_model,
            state_audit_timeout=ai.state_audit_timeout,
            archivist_suggest=ai.archivist_suggest,
            archivist_ai=ai.archivist_ai,
            archivist_provider=ai.archivist_provider,
            archivist_model=ai.archivist_model,
            archivist_timeout=ai.archivist_timeout,
            archivist_enqueue=archivist_enqueue,
            audit_log=resolve_audit_log_path(resolved_root, audit_log),
        )


class AIGMMCPAdapter:
    """Thin MCP-facing wrapper over the V1 runtime and validators."""

    def __init__(self, config: MCPAdapterConfig) -> None:
        self.config = config
        self.pending_clarifications: dict[str, dict[str, Any]] = {}

    def workspace_inspect(self) -> dict[str, Any]:
        return self.call_with_audit("workspace_inspect", {}, lambda: self.save_manager().inspect_workspace())

    def campaign_list(self, refresh: bool = False) -> dict[str, Any]:
        return self.call_with_audit("campaign_list", {"refresh": refresh}, lambda: self.save_manager().list_campaigns(refresh=refresh))

    def save_list(
        self,
        campaign_id: str | None = None,
        include_archived: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        request = {"campaign_id": campaign_id, "include_archived": include_archived, "refresh": refresh}
        return self.call_with_audit(
            "save_list",
            request,
            lambda: self.save_manager().list_saves(
                campaign_id=campaign_id,
                include_archived=include_archived,
                refresh=refresh,
            ),
        )

    def save_current(self, refresh: bool = False) -> dict[str, Any]:
        return self.call_with_audit("save_current", {"refresh": refresh}, lambda: self.save_manager().current_save(refresh=refresh))

    def save_create(
        self,
        campaign: str | None = None,
        label: str | None = None,
        starter_save: str | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        request = {"campaign": campaign, "label": label, "starter_save": starter_save, "activate": activate}
        return self.call_with_audit(
            "save_create",
            request,
            lambda: self.save_manager().create_save(
                campaign=campaign,
                label=label,
                starter_save=starter_save,
                activate=activate,
            ),
        )

    def save_switch(self, save_id: str) -> dict[str, Any]:
        return self.call_with_audit("save_switch", {"save_id": save_id}, lambda: self.save_manager().switch_save(save_id))

    def start_or_continue(
        self,
        campaign: str | None = None,
        user_text: str | None = None,
        create_if_missing: bool = True,
        starter_save: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        request = {
            "campaign": campaign,
            "user_text": user_text,
            "create_if_missing": create_if_missing,
            "starter_save": starter_save,
            "label": label,
        }
        return self.call_with_audit(
            "start_or_continue",
            request,
            lambda: self.save_manager().start_or_continue(
                campaign=campaign,
                user_text=user_text,
                create_if_missing=create_if_missing,
                starter_save=starter_save,
                label=label,
            ),
        )

    def intent_manifest(self) -> dict[str, Any]:
        return self.call_with_audit("intent_manifest", {}, build_intent_manifest)

    def player_query(
        self,
        kind: str = "scene",
        query_text: str | None = None,
        budget: int | None = None,
    ) -> dict[str, Any]:
        request = {"kind": kind, "query_text": query_text, "budget": budget}
        return self.call_with_audit(
            "player_query",
            request,
            lambda: self.save_manager().player_query(kind=kind, query_text=query_text, budget=budget),
        )

    def player_turn(
        self,
        user_text: str,
        external_intent_candidate: dict[str, Any] | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        request = {
            "user_text": user_text,
            "external_intent_candidate": external_intent_candidate,
            "preflight_id": preflight_id,
            "message_id": message_id,
            "platform": platform,
            "session_key": session_key,
            "source_user_text_hash": source_user_text_hash,
            "preflight_pending_wait_ms": preflight_pending_wait_ms,
            "intent_ai": self.config.intent_ai,
            "intent_backend": self.config.intent_backend,
            "intent_provider": self.config.intent_provider,
            "intent_model": self.config.intent_model,
            "intent_timeout": self.config.intent_timeout,
            "intent_base_url": self.config.intent_base_url,
            "intent_api_key_env": self.config.intent_api_key_env,
            "intent_fallback_backend": self.config.intent_fallback_backend,
        }
        return self.call_with_audit(
            "player_turn",
            request,
            lambda: self.save_manager().player_turn(
                user_text=user_text,
                external_intent_candidate=external_intent_candidate,
                intent_ai=self.config.intent_ai,
                intent_backend=self.config.intent_backend,
                intent_provider=self.config.intent_provider,
                intent_model=self.config.intent_model,
                intent_timeout=self.config.intent_timeout,
                intent_base_url=self.config.intent_base_url,
                intent_api_key_env=self.config.intent_api_key_env,
                intent_fallback_backend=self.config.intent_fallback_backend,
                preflight_id=preflight_id,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_pending_wait_ms=preflight_pending_wait_ms,
            ),
        )

    def player_act(
        self,
        user_text: str,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        request = {
            "user_text": user_text,
            "preflight_id": preflight_id,
            "message_id": message_id,
            "platform": platform,
            "session_key": session_key,
            "source_user_text_hash": source_user_text_hash,
            "preflight_pending_wait_ms": preflight_pending_wait_ms,
            "intent_ai": self.config.intent_ai,
            "intent_backend": self.config.intent_backend,
            "intent_provider": self.config.intent_provider,
            "intent_model": self.config.intent_model,
            "intent_timeout": self.config.intent_timeout,
            "intent_base_url": self.config.intent_base_url,
            "intent_api_key_env": self.config.intent_api_key_env,
            "intent_fallback_backend": self.config.intent_fallback_backend,
        }
        return self.call_with_audit(
            "player_act",
            request,
            lambda: self.save_manager().player_act(
                user_text=user_text,
                intent_ai=self.config.intent_ai,
                intent_backend=self.config.intent_backend,
                intent_provider=self.config.intent_provider,
                intent_model=self.config.intent_model,
                intent_timeout=self.config.intent_timeout,
                intent_base_url=self.config.intent_base_url,
                intent_api_key_env=self.config.intent_api_key_env,
                intent_fallback_backend=self.config.intent_fallback_backend,
                preflight_id=preflight_id,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_pending_wait_ms=preflight_pending_wait_ms,
            ),
        )

    def player_confirm(self, session_id: str = "") -> dict[str, Any]:
        return self.call_with_audit(
            "player_confirm",
            {"session_id": session_id},
            lambda: self.save_manager().player_confirm(session_id=session_id),
        )

    def campaign_validate(self, campaign: str | None = None) -> dict[str, Any]:
        return self.call_with_audit(
            "campaign_validate",
            {"campaign": campaign},
            lambda: validate_campaign_package(self.resolve_campaign(campaign)).to_dict(),
        )

    def save_inspect(self, save: str | None = None) -> dict[str, Any]:
        return self.call_with_audit("save_inspect", {"save": save}, lambda: inspect_v1_save(self.resolve_save(save)))

    def intent_preflight(
        self,
        user_text: str,
        save: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        external_intent_candidate: dict[str, Any] | None = None,
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_identity_profile: str = "candidate_bound",
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        effective_intent_backend = configured_value(intent_backend, self.config.intent_backend)
        effective_intent_provider = configured_value(intent_provider, self.config.intent_provider)
        effective_intent_model = configured_value(intent_model, self.config.intent_model)
        effective_intent_timeout = configured_value(intent_timeout, self.config.intent_timeout)
        effective_intent_base_url = configured_value(intent_base_url, self.config.intent_base_url)
        effective_intent_api_key_env = configured_value(intent_api_key_env, self.config.intent_api_key_env)
        effective_intent_fallback_backend = configured_value(
            intent_fallback_backend,
            self.config.intent_fallback_backend,
        )
        request = {
            "save": save,
            "user_text": user_text,
            "intent_backend": effective_intent_backend,
            "intent_provider": effective_intent_provider,
            "intent_model": effective_intent_model,
            "intent_timeout": effective_intent_timeout,
            "intent_base_url": effective_intent_base_url,
            "intent_api_key_env": effective_intent_api_key_env,
            "intent_fallback_backend": effective_intent_fallback_backend,
            "external_intent_candidate": external_intent_candidate,
            "message_id": message_id,
            "platform": platform,
            "session_key": session_key,
            "source_user_text_hash": source_user_text_hash,
            "preflight_identity_profile": preflight_identity_profile,
            "ttl_seconds": ttl_seconds,
        }

        def run() -> dict[str, Any]:
            self.require_low_level_profile("intent_preflight")
            self.require_no_pending_clarification(save, "intent_preflight")
            runtime = self.runtime_for_save(save)
            return runtime.preflight_intent(
                user_text,
                intent_backend=effective_intent_backend,
                intent_provider=effective_intent_provider,
                intent_model=effective_intent_model,
                intent_timeout=effective_intent_timeout,
                intent_base_url=effective_intent_base_url,
                intent_api_key_env=effective_intent_api_key_env,
                intent_fallback_backend=effective_intent_fallback_backend,
                external_intent_candidate=external_intent_candidate,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_identity_profile=preflight_identity_profile,
                ttl_seconds=ttl_seconds,
            ).to_dict()

        return self.call_with_audit("intent_preflight", request, run)

    def start_turn(
        self,
        user_text: str,
        save: str | None = None,
        mode: str = "auto",
        submode: str | None = None,
        budget: int | None = None,
        max_events: int = 6,
        max_depth: int = 1,
        semantic_ai: str | None = None,
        semantic_provider: str | None = None,
        semantic_model: str | None = None,
        semantic_timeout: int | None = None,
        intent_ai: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        external_intent_candidate: dict[str, Any] | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        semantic_override = any(has_override_value(value) for value in (semantic_ai, semantic_provider, semantic_model, semantic_timeout))
        intent_override = any(
            has_override_value(value)
            for value in (
                intent_ai,
                intent_backend,
                intent_provider,
                intent_model,
                intent_timeout,
                external_intent_candidate,
                intent_base_url,
                intent_api_key_env,
                intent_fallback_backend,
            )
        )
        effective_semantic_ai = configured_value(semantic_ai, self.config.semantic_ai)
        effective_semantic_provider = configured_value(semantic_provider, self.config.semantic_provider)
        effective_semantic_model = configured_value(semantic_model, self.config.semantic_model)
        effective_semantic_timeout = configured_value(semantic_timeout, self.config.semantic_timeout)
        effective_intent_ai = configured_value(intent_ai, self.config.intent_ai)
        effective_intent_backend = configured_value(intent_backend, self.config.intent_backend)
        effective_intent_provider = configured_value(intent_provider, self.config.intent_provider)
        effective_intent_model = configured_value(intent_model, self.config.intent_model)
        effective_intent_timeout = configured_value(intent_timeout, self.config.intent_timeout)
        effective_intent_base_url = configured_value(intent_base_url, self.config.intent_base_url)
        effective_intent_api_key_env = configured_value(intent_api_key_env, self.config.intent_api_key_env)
        effective_intent_fallback_backend = configured_value(
            intent_fallback_backend,
            self.config.intent_fallback_backend,
        )
        request = {
            "save": save,
            "user_text": user_text,
            "mode": mode,
            "submode": submode,
            "budget": budget,
            "max_events": max_events,
            "max_depth": max_depth,
            "semantic_ai": effective_semantic_ai,
            "semantic_model": effective_semantic_model,
            "intent_ai": effective_intent_ai,
            "intent_backend": effective_intent_backend,
            "intent_provider": effective_intent_provider,
            "intent_model": effective_intent_model,
            "intent_timeout": effective_intent_timeout,
            "intent_base_url": effective_intent_base_url,
            "intent_api_key_env": effective_intent_api_key_env,
            "intent_fallback_backend": effective_intent_fallback_backend,
            "external_intent_candidate": external_intent_candidate,
            "preflight_id": preflight_id,
            "message_id": message_id,
            "platform": platform,
            "session_key": session_key,
            "source_user_text_hash": source_user_text_hash,
            "preflight_pending_wait_ms": preflight_pending_wait_ms,
        }

        def run() -> dict[str, Any]:
            self.require_player_safe_start(
                mode=mode,
                semantic_override=semantic_override,
                intent_override=intent_override,
            )
            self.require_fresh_clarification_repreview("start_turn", save, request)
            runtime = self.runtime_for_save(save)
            result = runtime.start_turn(
                user_text,
                mode=mode,
                submode=submode,
                budget=budget,
                max_events=max_events,
                max_depth=max_depth,
                semantic_ai=effective_semantic_ai,
                semantic_provider=effective_semantic_provider,
                semantic_model=effective_semantic_model,
                semantic_timeout=effective_semantic_timeout,
                intent_ai=effective_intent_ai,
                intent_backend=effective_intent_backend,
                intent_provider=effective_intent_provider,
                intent_model=effective_intent_model,
                intent_timeout=effective_intent_timeout,
                intent_base_url=effective_intent_base_url,
                intent_api_key_env=effective_intent_api_key_env,
                intent_fallback_backend=effective_intent_fallback_backend,
                external_intent_candidate=external_intent_candidate,
                preflight_id=preflight_id,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_pending_wait_ms=preflight_pending_wait_ms,
            ).to_dict()
            self.update_pending_clarification(save, request, result)
            return result

        return self.call_with_audit("start_turn", request, run)

    def query(
        self,
        kind: str,
        save: str | None = None,
        query_text: str | None = None,
        view: str = "player",
        budget: int | None = None,
    ) -> dict[str, Any]:
        request = {"kind": kind, "save": save, "query_text": query_text, "view": view, "budget": budget}

        def run() -> dict[str, Any]:
            self.require_view_allowed(view)
            runtime = self.runtime_for_save(save)
            return runtime.query(kind, query_text, view=view, budget=budget).to_dict()

        return self.call_with_audit("query", request, run)

    def preview_from_text(
        self,
        user_text: str,
        save: str | None = None,
        mode: str = "auto",
        submode: str | None = None,
        semantic_ai: str | None = None,
        semantic_provider: str | None = None,
        semantic_model: str | None = None,
        semantic_timeout: int | None = None,
        intent_ai: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        external_intent_candidate: dict[str, Any] | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        semantic_override = any(has_override_value(value) for value in (semantic_ai, semantic_provider, semantic_model, semantic_timeout))
        intent_override = any(
            has_override_value(value)
            for value in (
                intent_ai,
                intent_backend,
                intent_provider,
                intent_model,
                intent_timeout,
                external_intent_candidate,
                intent_base_url,
                intent_api_key_env,
                intent_fallback_backend,
            )
        )
        effective_semantic_ai = configured_value(semantic_ai, self.config.semantic_ai)
        effective_semantic_provider = configured_value(semantic_provider, self.config.semantic_provider)
        effective_semantic_model = configured_value(semantic_model, self.config.semantic_model)
        effective_semantic_timeout = configured_value(semantic_timeout, self.config.semantic_timeout)
        effective_intent_ai = configured_value(intent_ai, self.config.intent_ai)
        effective_intent_backend = configured_value(intent_backend, self.config.intent_backend)
        effective_intent_provider = configured_value(intent_provider, self.config.intent_provider)
        effective_intent_model = configured_value(intent_model, self.config.intent_model)
        effective_intent_timeout = configured_value(intent_timeout, self.config.intent_timeout)
        effective_intent_base_url = configured_value(intent_base_url, self.config.intent_base_url)
        effective_intent_api_key_env = configured_value(intent_api_key_env, self.config.intent_api_key_env)
        effective_intent_fallback_backend = configured_value(
            intent_fallback_backend,
            self.config.intent_fallback_backend,
        )
        request = {
            "save": save,
            "user_text": user_text,
            "mode": mode,
            "submode": submode,
            "semantic_ai": effective_semantic_ai,
            "semantic_model": effective_semantic_model,
            "intent_ai": effective_intent_ai,
            "intent_backend": effective_intent_backend,
            "intent_provider": effective_intent_provider,
            "intent_model": effective_intent_model,
            "intent_timeout": effective_intent_timeout,
            "intent_base_url": effective_intent_base_url,
            "intent_api_key_env": effective_intent_api_key_env,
            "intent_fallback_backend": effective_intent_fallback_backend,
            "external_intent_candidate": external_intent_candidate,
            "preflight_id": preflight_id,
            "message_id": message_id,
            "platform": platform,
            "session_key": session_key,
            "source_user_text_hash": source_user_text_hash,
            "preflight_pending_wait_ms": preflight_pending_wait_ms,
        }

        def run() -> dict[str, Any]:
            self.require_player_safe_start(
                mode=mode,
                semantic_override=semantic_override,
                intent_override=intent_override,
            )
            self.require_fresh_clarification_repreview("preview_from_text", save, request)
            runtime = self.runtime_for_save(save)
            result = runtime.preview_from_text(
                user_text,
                mode=mode,
                submode=submode,
                semantic_ai=effective_semantic_ai,
                semantic_provider=effective_semantic_provider,
                semantic_model=effective_semantic_model,
                semantic_timeout=effective_semantic_timeout,
                intent_ai=effective_intent_ai,
                intent_backend=effective_intent_backend,
                intent_provider=effective_intent_provider,
                intent_model=effective_intent_model,
                intent_timeout=effective_intent_timeout,
                intent_base_url=effective_intent_base_url,
                intent_api_key_env=effective_intent_api_key_env,
                intent_fallback_backend=effective_intent_fallback_backend,
                external_intent_candidate=external_intent_candidate,
                preflight_id=preflight_id,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_pending_wait_ms=preflight_pending_wait_ms,
            ).to_dict()
            self.update_pending_clarification(save, request, result)
            return result

        return self.call_with_audit("preview_from_text", request, run)

    def preview_action(
        self,
        action: str,
        save: str | None = None,
        options: dict[str, Any] | None = None,
        source_user_text: str | None = None,
    ) -> dict[str, Any]:
        request = {"action": action, "save": save, "options": options or {}, "source_user_text": source_user_text}

        def run() -> dict[str, Any]:
            self.require_low_level_profile("preview_action")
            self.require_no_pending_clarification(save, "preview_action")
            runtime = self.runtime_for_save(save)
            return runtime.preview_action(action, options or {}, source_user_text=source_user_text).to_dict()

        return self.call_with_audit("preview_action", request, run)

    def validate_delta(
        self,
        delta: dict[str, Any],
        save: str | None = None,
        action: str | None = None,
        action_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = {"save": save, "action": action, "action_options": action_options or {}, "delta": delta}

        def run() -> dict[str, Any]:
            self.require_low_level_profile("validate_delta")
            self.require_no_pending_clarification(save, "validate_delta")
            if not isinstance(delta, dict):
                raise ValueError("delta must be an object")
            runtime = self.runtime_for_save(save)
            return runtime.validate_delta(delta, action=action, action_options=action_options or {}).to_dict()

        return self.call_with_audit("validate_delta", request, run)

    def commit_turn(
        self,
        delta: dict[str, Any],
        save: str | None = None,
        turn_proposal: dict[str, Any] | None = None,
        action: str | None = None,
        action_options: dict[str, Any] | None = None,
        state_audit: bool = DEFAULT_STATE_AUDIT_ENABLED,
        state_audit_ai: str | None = None,
        state_audit_provider: str | None = None,
        state_audit_model: str | None = None,
        state_audit_timeout: int | None = None,
        state_audit_block: bool = True,
        archivist_suggest: bool | None = None,
        archivist_ai: str | None = None,
        archivist_provider: str | None = None,
        archivist_model: str | None = None,
        archivist_timeout: int | None = None,
        archivist_enqueue: bool | None = None,
    ) -> dict[str, Any]:
        effective_state_audit_ai = self.config.state_audit_ai if state_audit_ai is None else state_audit_ai
        effective_state_audit_provider = state_audit_provider or self.config.state_audit_provider
        effective_state_audit_model = state_audit_model or self.config.state_audit_model
        effective_state_audit_timeout = (
            state_audit_timeout if state_audit_timeout is not None else self.config.state_audit_timeout
        )
        effective_archivist_suggest = (
            self.config.archivist_suggest if archivist_suggest is None else archivist_suggest
        )
        effective_archivist_ai = self.config.archivist_ai if archivist_ai is None else archivist_ai
        effective_archivist_provider = archivist_provider or self.config.archivist_provider
        effective_archivist_model = archivist_model or self.config.archivist_model
        effective_archivist_timeout = archivist_timeout if archivist_timeout is not None else self.config.archivist_timeout
        effective_archivist_enqueue = self.config.archivist_enqueue if archivist_enqueue is None else archivist_enqueue
        state_audit_override = any(
            value is not None
            for value in (
                state_audit_ai,
                state_audit_provider,
                state_audit_model,
                state_audit_timeout,
                archivist_suggest,
                archivist_ai,
                archivist_provider,
                archivist_model,
                archivist_timeout,
                archivist_enqueue,
            )
        )
        request = {
            "save": save,
            "action": action,
            "action_options": action_options or {},
            "delta": delta,
            "turn_proposal": turn_proposal,
            "state_audit": state_audit,
            "state_audit_ai": effective_state_audit_ai,
            "state_audit_model": effective_state_audit_model,
            "state_audit_block": state_audit_block,
            "archivist_suggest": effective_archivist_suggest,
            "archivist_ai": effective_archivist_ai,
            "archivist_model": effective_archivist_model,
            "archivist_enqueue": effective_archivist_enqueue,
        }

        def run() -> dict[str, Any]:
            self.require_low_level_profile("commit_turn")
            self.require_no_pending_clarification(save, "commit_turn")
            self.require_commit_policy(state_audit=state_audit, helper_override=state_audit_override)
            if not isinstance(delta, dict):
                raise ValueError("delta must be an object")
            runtime = self.runtime_for_save(save)
            return runtime.commit_turn(
                delta,
                turn_proposal=turn_proposal,
                backup=True,
                action=action,
                action_options=action_options or {},
                state_audit=state_audit or effective_state_audit_ai != "off",
                state_audit_ai=effective_state_audit_ai,
                state_audit_provider=effective_state_audit_provider,
                state_audit_model=effective_state_audit_model,
                state_audit_timeout=effective_state_audit_timeout,
                state_audit_block=state_audit_block,
                archivist_suggest=effective_archivist_suggest,
                archivist_ai=effective_archivist_ai,
                archivist_provider=effective_archivist_provider,
                archivist_model=effective_archivist_model,
                archivist_timeout=effective_archivist_timeout,
                archivist_enqueue=effective_archivist_enqueue,
            ).to_dict()

        return self.call_with_audit("commit_turn", request, run)

    def require_low_level_profile(self, tool: str) -> None:
        if self.config.mcp_profile not in LOW_LEVEL_PROFILES:
            raise PermissionError(
                f"{tool} requires developer, trusted_gm, maintenance, or admin MCP profile"
            )

    def require_view_allowed(self, view: str | None) -> None:
        normalized = (view or "player").strip().lower()
        if normalized in {"gm", "maintenance"} and self.config.mcp_profile not in HIDDEN_READ_PROFILES:
            raise PermissionError(f"view={normalized!r} requires trusted_gm, maintenance, or admin MCP profile")

    def require_player_safe_start(self, *, mode: str, semantic_override: bool, intent_override: bool = False) -> None:
        if self.config.mcp_profile == PLAYER_PROFILE and mode == "maintenance":
            raise PermissionError("mode='maintenance' requires maintenance or admin MCP profile")
        if self.config.mcp_profile == PLAYER_PROFILE and semantic_override:
            raise PermissionError("per-call semantic AI overrides require developer, trusted_gm, maintenance, or admin MCP profile")
        if self.config.mcp_profile == PLAYER_PROFILE and intent_override:
            raise PermissionError("per-call intent AI overrides require developer, trusted_gm, maintenance, or admin MCP profile")

    def require_commit_policy(self, *, state_audit: bool, helper_override: bool) -> None:
        if self.config.mcp_profile == PLAYER_PROFILE and not state_audit:
            raise PermissionError("disabling state_audit requires developer, trusted_gm, maintenance, or admin MCP profile")
        if self.config.mcp_profile == PLAYER_PROFILE and helper_override:
            raise PermissionError("per-call commit AI overrides require developer, trusted_gm, maintenance, or admin MCP profile")

    def clarification_key(self, save: str | None) -> str:
        return str(self.resolve_save(save))

    def require_fresh_clarification_repreview(self, tool: str, save: str | None, request: dict[str, Any]) -> None:
        key = self.clarification_key(save)
        pending = self.pending_clarifications.get(key)
        if pending is None:
            return
        if not low_level_request_is_fresh(request, pending.get("request") if isinstance(pending.get("request"), dict) else {}):
            clarification_id = str(pending.get("clarification_id") or "unknown")
            raise PermissionError(
                f"{tool} must answer pending clarification {clarification_id} with fresh user_text or external_intent_candidate"
            )

    def require_no_pending_clarification(self, save: str | None, tool: str) -> None:
        key = self.clarification_key(save)
        pending = self.pending_clarifications.get(key)
        if pending is None:
            return
        clarification_id = str(pending.get("clarification_id") or "unknown")
        raise PermissionError(f"{tool} cannot run while clarification {clarification_id} is pending")

    def update_pending_clarification(self, save: str | None, request: dict[str, Any], result: dict[str, Any]) -> None:
        key = self.clarification_key(save)
        clarification = extract_result_clarification(result)
        if clarification is None:
            self.pending_clarifications.pop(key, None)
            return
        clarification_id = str(clarification.get("clarification_id") or f"clarification:{int(time.time() * 1000)}")
        clarification["clarification_id"] = clarification_id
        self.pending_clarifications[key] = {
            "clarification_id": clarification_id,
            "request": dict(request),
            "clarification": clarification,
        }

    def health(self, save: str | None = None) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            runtime = self.runtime_for_save(save)
            return runtime.health().to_dict()

        return self.call_with_audit("health", {"save": save}, run)

    def call_with_audit(self, tool: str, request: dict[str, Any], callback: Any) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = callback()
        except Exception as exc:
            result = error_dict(exc)
        duration_ms = int((time.monotonic() - started) * 1000)
        self.write_audit_record(tool, request, result, duration_ms=duration_ms)
        return result

    def write_audit_record(
        self,
        tool: str,
        request: dict[str, Any],
        result: dict[str, Any],
        *,
        duration_ms: int,
    ) -> None:
        path = self.config.audit_log
        if path is None:
            return
        record = {
            "created_at": utc_now(),
            "server": MCP_SERVER_NAME,
            "tool": tool,
            "duration_ms": duration_ms,
            "status": "error" if result_has_error(result) else "ok",
            "request": sanitize_for_audit(request),
            "result": summarize_result_for_audit(result),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception as exc:  # pragma: no cover - audit must never break MCP calls
            print(f"aigm-kernel MCP audit write failed: {exc}", file=sys.stderr)

    def runtime_for_save(self, save: str | None = None) -> GMRuntime:
        return GMRuntime.from_path(self.resolve_save(save))

    def save_manager(self) -> SaveManager:
        return SaveManager(
            self.config.root,
            default_campaign=self.config.default_campaign,
            default_starter_save=self.config.default_starter_save,
        )

    def resolve_campaign(self, campaign: str | None = None) -> Path:
        value = campaign or self.config.default_campaign
        if not value:
            raise ValueError("campaign is required because no default campaign is configured")
        return resolve_relative_under_root(self.config.root, value, label="campaign")

    def resolve_save(self, save: str | None = None) -> Path:
        if save:
            return resolve_relative_under_root(self.config.root, save, label="save")
        if self.config.registry_active:
            return self.save_manager().resolve_save_path_for_runtime(default_save=self.config.default_save)
        if not self.config.default_save:
            raise ValueError("save is required because no default save is configured")
        return resolve_relative_under_root(self.config.root, self.config.default_save, label="save")


def serve_mcp(config: MCPAdapterConfig, *, transport: str = "stdio") -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "MCP support requires the optional dependency: pip install 'aigm-kernel[mcp]'"
        ) from exc

    adapter = AIGMMCPAdapter(config)
    server = FastMCP(MCP_SERVER_NAME)

    def low_level_tool(callback: Any) -> Any:
        if config.mcp_profile in LOW_LEVEL_PROFILES:
            return server.tool()(callback)
        return callback

    @server.tool()
    def workspace_inspect() -> dict[str, Any]:
        """Inspect the configured player workspace and save registry."""
        return adapter.workspace_inspect()

    @server.tool()
    def campaign_list(refresh: bool = False) -> dict[str, Any]:
        """List registered player-facing campaign packages."""
        return adapter.campaign_list(refresh)

    @server.tool()
    def save_list(
        campaign_id: str | None = None,
        include_archived: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """List registered player-facing saves."""
        return adapter.save_list(campaign_id, include_archived, refresh)

    @server.tool()
    def save_current(refresh: bool = False) -> dict[str, Any]:
        """Return the active player-facing save."""
        return adapter.save_current(refresh)

    @server.tool()
    def save_create(
        campaign: str | None = None,
        label: str | None = None,
        starter_save: str | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        """Create a new save package; this does not advance story or gameplay facts."""
        return adapter.save_create(campaign, label, starter_save, activate)

    @server.tool()
    def save_switch(save_id: str) -> dict[str, Any]:
        """Switch the active player-facing save."""
        return adapter.save_switch(save_id)

    @server.tool()
    def start_or_continue(
        campaign: str | None = None,
        user_text: str | None = None,
        create_if_missing: bool = True,
        starter_save: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Continue or create onboarding context; gameplay facts still require player_turn/player_confirm."""
        return adapter.start_or_continue(campaign, user_text, create_if_missing, starter_save, label)

    @server.tool()
    def intent_manifest() -> dict[str, Any]:
        """Read-only kernel-generated action/query manifest; not a gameplay entry point."""
        return adapter.intent_manifest()

    if config.mcp_profile in LOW_LEVEL_PROFILES:

        @server.tool()
        def player_query(kind: str = "scene", query_text: str | None = None, budget: int | None = None) -> dict[str, Any]:
            """Structured compatibility query against the active save; normal natural language enters player_turn."""
            return adapter.player_query(kind, query_text, budget)

    @server.tool()
    def player_turn(
        user_text: str,
        external_intent_candidate: dict[str, Any] | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        """Standard player turn entry: route query/action/clarify/block without exposing delta JSON."""
        return adapter.player_turn(
            user_text,
            external_intent_candidate=external_intent_candidate,
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )

    if config.mcp_profile in LOW_LEVEL_PROFILES:

        @server.tool()
        def player_act(
            user_text: str,
            preflight_id: str = "",
            message_id: str = "",
            platform: str = "",
            session_key: str = "",
            source_user_text_hash: str = "",
            preflight_pending_wait_ms: int = 0,
        ) -> dict[str, Any]:
            """Compatibility wrapper for older player-safe clients; new natural-language play uses player_turn."""
            return adapter.player_act(
                user_text,
                preflight_id=preflight_id,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_pending_wait_ms=preflight_pending_wait_ms,
            )

    @server.tool()
    def player_confirm(session_id: str) -> dict[str, Any]:
        """Confirm and save the pending player action using the session_id returned by player_turn."""
        return adapter.player_confirm(session_id=session_id)

    @server.tool()
    def campaign_validate(campaign: str | None = None) -> dict[str, Any]:
        """Read-only validation for a configured campaign package."""
        return adapter.campaign_validate(campaign)

    @server.tool()
    def save_inspect(save: str | None = None) -> dict[str, Any]:
        """Read-only inspection for a configured save package."""
        return adapter.save_inspect(save)

    @low_level_tool
    def intent_preflight(
        user_text: str,
        save: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        external_intent_candidate: dict[str, Any] | None = None,
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_identity_profile: str = "candidate_bound",
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        """Precompute advisory internal intent review; does not preview, commit, or change gameplay facts."""
        return adapter.intent_preflight(
            user_text=user_text,
            save=save,
            intent_backend=intent_backend,
            intent_provider=intent_provider,
            intent_model=intent_model,
            intent_timeout=intent_timeout,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
            external_intent_candidate=external_intent_candidate,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_identity_profile=preflight_identity_profile,
            ttl_seconds=ttl_seconds,
        )

    @low_level_tool
    def start_turn(
        user_text: str,
        save: str | None = None,
        mode: str = "auto",
        submode: str | None = None,
        budget: int | None = None,
        max_events: int = 6,
        max_depth: int = 1,
        semantic_ai: str | None = None,
        semantic_provider: str | None = None,
        semantic_model: str | None = None,
        semantic_timeout: int | None = None,
        intent_ai: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        external_intent_candidate: dict[str, Any] | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        """Build context for one player request; if clarification is present, ask the player before continuing."""
        return adapter.start_turn(
            user_text=user_text,
            save=save,
            mode=mode,
            submode=submode,
            budget=budget,
            max_events=max_events,
            max_depth=max_depth,
            semantic_ai=semantic_ai,
            semantic_provider=semantic_provider,
            semantic_model=semantic_model,
            semantic_timeout=semantic_timeout,
            intent_ai=intent_ai,
            intent_backend=intent_backend,
            intent_provider=intent_provider,
            intent_model=intent_model,
            intent_timeout=intent_timeout,
            external_intent_candidate=external_intent_candidate,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )

    @low_level_tool
    def query(
        kind: str,
        save: str | None = None,
        query_text: str | None = None,
        view: str = "player",
        budget: int | None = None,
    ) -> dict[str, Any]:
        """Run a non-mutating query against a configured save."""
        return adapter.query(kind, save, query_text, view, budget)

    @low_level_tool
    def preview_from_text(
        user_text: str,
        save: str | None = None,
        mode: str = "auto",
        submode: str | None = None,
        semantic_ai: str | None = None,
        semantic_provider: str | None = None,
        semantic_model: str | None = None,
        semantic_timeout: int | None = None,
        intent_ai: str | None = None,
        intent_backend: str | None = None,
        intent_provider: str | None = None,
        intent_model: str | None = None,
        intent_timeout: int | None = None,
        external_intent_candidate: dict[str, Any] | None = None,
        intent_base_url: str | None = None,
        intent_api_key_env: str | None = None,
        intent_fallback_backend: str | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> dict[str, Any]:
        """Low-level natural-language preview primitive; default player profile uses player_turn."""
        return adapter.preview_from_text(
            user_text=user_text,
            save=save,
            mode=mode,
            submode=submode,
            semantic_ai=semantic_ai,
            semantic_provider=semantic_provider,
            semantic_model=semantic_model,
            semantic_timeout=semantic_timeout,
            intent_ai=intent_ai,
            intent_backend=intent_backend,
            intent_provider=intent_provider,
            intent_model=intent_model,
            intent_timeout=intent_timeout,
            external_intent_candidate=external_intent_candidate,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )

    @low_level_tool
    def preview_action(
        action: str,
        save: str | None = None,
        options: dict[str, Any] | None = None,
        source_user_text: str | None = None,
    ) -> dict[str, Any]:
        """Preview an already-selected low-level action contract without saving it."""
        return adapter.preview_action(action, save, options, source_user_text)

    @low_level_tool
    def validate_delta(
        delta: dict[str, Any],
        save: str | None = None,
        action: str | None = None,
        action_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate a structured turn delta without saving."""
        return adapter.validate_delta(delta, save, action, action_options)

    @low_level_tool
    def commit_turn(
        delta: dict[str, Any],
        save: str | None = None,
        turn_proposal: dict[str, Any] | None = None,
        action: str | None = None,
        action_options: dict[str, Any] | None = None,
        state_audit: bool = DEFAULT_STATE_AUDIT_ENABLED,
        state_audit_ai: str | None = None,
        state_audit_provider: str | None = None,
        state_audit_model: str | None = None,
        state_audit_timeout: int | None = None,
        state_audit_block: bool = True,
        archivist_suggest: bool | None = None,
        archivist_ai: str | None = None,
        archivist_provider: str | None = None,
        archivist_model: str | None = None,
        archivist_timeout: int | None = None,
        archivist_enqueue: bool | None = None,
    ) -> dict[str, Any]:
        """Commit one validated and accepted TurnProposal delta to a configured save."""
        return adapter.commit_turn(
            delta=delta,
            save=save,
            turn_proposal=turn_proposal,
            action=action,
            action_options=action_options,
            state_audit=state_audit,
            state_audit_ai=state_audit_ai,
            state_audit_provider=state_audit_provider,
            state_audit_model=state_audit_model,
            state_audit_timeout=state_audit_timeout,
            state_audit_block=state_audit_block,
            archivist_suggest=archivist_suggest,
            archivist_ai=archivist_ai,
            archivist_provider=archivist_provider,
            archivist_model=archivist_model,
            archivist_timeout=archivist_timeout,
            archivist_enqueue=archivist_enqueue,
        )

    @server.tool()
    def health(save: str | None = None) -> dict[str, Any]:
        """Run a read-only health check for a configured save; this does not repair state."""
        return adapter.health(save)

    server.run(transport=transport)


def build_client_config(
    root: str | Path,
    *,
    default_campaign: str | None = None,
    default_save: str | None = None,
    default_starter_save: str | None = None,
    registry_active: bool = False,
    mcp_profile: str = PLAYER_PROFILE,
    command: str = "aigm",
    server_name: str = MCP_SERVER_NAME,
) -> dict[str, Any]:
    config = MCPAdapterConfig.from_values(
        root,
        default_campaign=default_campaign,
        default_save=default_save,
        default_starter_save=default_starter_save,
        registry_active=registry_active,
        mcp_profile=mcp_profile,
    )
    args = ["mcp", "serve", "--root", str(config.root)]
    if config.default_campaign:
        args.extend(["--default-campaign", config.default_campaign])
    if config.default_save:
        args.extend(["--default-save", config.default_save])
    if config.default_starter_save:
        args.extend(["--default-starter-save", config.default_starter_save])
    if config.registry_active:
        args.append("--registry-active")
    if config.mcp_profile != PLAYER_PROFILE:
        args.extend(["--mcp-profile", config.mcp_profile])
    return {
        "mcpServers": {
            server_name: {
                "command": command,
                "args": args,
            }
        }
    }


def render_client_config(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def resolve_audit_log_path(root: Path, audit_log: str | Path | None) -> Path | None:
    if audit_log is False:
        return None
    if audit_log is None:
        return root / "logs" / "aigm-mcp-audit.jsonl"
    path = Path(audit_log).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def resolve_relative_under_root(root: Path, value: str, *, label: str) -> Path:
    relative = normalize_optional_relative(value, label)
    if not relative:
        raise ValueError(f"{label} is required")
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"{label} escapes configured MCP root")
    return candidate


def normalize_optional_relative(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    path = Path(raw)
    if path.is_absolute():
        raise ValueError(f"{label} must be relative to the configured MCP root")
    if ".." in path.parts:
        raise ValueError(f"{label} must not contain '..'")
    return path.as_posix()


def normalize_mcp_profile(value: str | None) -> str:
    profile = (value or PLAYER_PROFILE).strip().lower().replace("-", "_")
    if profile not in MCP_PROFILES:
        raise ValueError(f"unknown MCP profile {value!r}; expected one of {sorted(MCP_PROFILES)}")
    return profile


def error_dict(exc: Exception) -> dict[str, Any]:
    message = str(exc)
    return {"ok": False, "errors": [message], "error_details": issues_from_messages([message], default_code="MCP_ADAPTER_ERROR")}


def result_has_error(result: dict[str, Any]) -> bool:
    if result.get("ok") is False:
        return True
    errors = result.get("errors")
    return bool(errors)


def extract_result_clarification(result: dict[str, Any]) -> dict[str, Any] | None:
    direct = result.get("clarification")
    if isinstance(direct, dict):
        return dict(direct)
    interpretation = result.get("interpretation")
    if isinstance(interpretation, dict):
        clarification = interpretation.get("clarification")
        if isinstance(clarification, dict):
            return dict(clarification)
        intent = interpretation.get("intent")
        if isinstance(intent, dict) and isinstance(intent.get("clarification"), dict):
            return dict(intent["clarification"])
    intent = result.get("intent")
    if isinstance(intent, dict) and isinstance(intent.get("clarification"), dict):
        return dict(intent["clarification"])
    return None


def low_level_request_is_fresh(request: dict[str, Any], previous: dict[str, Any]) -> bool:
    old_text = normalize_compact_text(previous.get("user_text"))
    new_text = normalize_compact_text(request.get("user_text"))
    if new_text and new_text != old_text:
        return True
    old_candidate = previous.get("external_intent_candidate")
    new_candidate = request.get("external_intent_candidate")
    return isinstance(new_candidate, dict) and new_candidate != old_candidate


def normalize_compact_text(value: Any) -> str:
    return "".join(str(value or "").lower().split()).strip("。！？!?,，")


def sanitize_for_audit(value: Any, *, max_text: int = 1200, depth: int = 0) -> Any:
    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) <= max_text:
            return value
        return value[:max_text] + f"... <truncated {len(value) - max_text} chars>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            if normalized_key == "session_key":
                sanitized[normalized_key] = f"sha256:{hash_identity(str(item or ''))}" if str(item or "").strip() else ""
            else:
                sanitized[normalized_key] = sanitize_for_audit(item, max_text=max_text, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple)):
        items = [sanitize_for_audit(item, max_text=max_text, depth=depth + 1) for item in value[:30]]
        if len(value) > 30:
            items.append(f"<truncated {len(value) - 30} items>")
        return items
    return str(value)


def summarize_result_for_audit(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "ok",
        "campaign_id",
        "campaign_name",
        "kind",
        "action",
        "turn_id",
        "backup_id",
        "current_turn_id",
        "current_location_id",
        "current_time_block",
        "cards_count",
        "write_status",
        "projection_status",
        "errors",
        "warnings",
        "missing_required",
        "needs_user_confirmation",
        "assumptions",
        "counts",
    ):
        if key in result:
            summary[key] = sanitize_for_audit(result[key])
    if isinstance(result.get("projection_report"), dict):
        projection = result["projection_report"]
        summary["projection_report"] = sanitize_for_audit(
            {
                "status": projection.get("status"),
                "requested_dirty": projection.get("requested_dirty") or projection.get("dirty"),
                "requested_failed": projection.get("requested_failed") or projection.get("failed"),
                "global_dirty": projection.get("global_dirty"),
                "global_failed": projection.get("global_failed"),
                "refreshed": projection.get("refreshed"),
            }
        )
    for text_key in ("text", "markdown"):
        if text_key in result and result[text_key]:
            summary[f"{text_key}_preview"] = sanitize_for_audit(str(result[text_key]), max_text=600)
    if "context" in result and isinstance(result["context"], dict):
        context = result["context"]
        summary["context"] = sanitize_for_audit(
            {
                "request": context.get("request"),
                "budget": context.get("budget"),
                "completeness": context.get("completeness"),
            }
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m rpg_engine.mcp_adapter")
    parser.add_argument("--root", required=True)
    parser.add_argument("--default-campaign")
    parser.add_argument("--default-save")
    parser.add_argument("--default-starter-save")
    parser.add_argument("--registry-active", action="store_true")
    parser.add_argument("--mcp-profile", default=PLAYER_PROFILE, choices=sorted(MCP_PROFILES))
    parser.add_argument("--ai-profile", default="off", choices=AI_PROFILES)
    parser.add_argument("--ai-provider")
    parser.add_argument("--ai-model")
    parser.add_argument("--ai-timeout", type=int)
    helper_backend_choices = [*AI_HELPER_BACKENDS, "hermes"]
    fallback_backend_choices = [*AI_HELPER_FALLBACK_BACKENDS, "hermes"]
    parser.add_argument("--semantic-ai", choices=helper_backend_choices)
    parser.add_argument("--semantic-provider")
    parser.add_argument("--semantic-model")
    parser.add_argument("--semantic-timeout", type=int)
    parser.add_argument("--intent-ai", choices=["off", "consensus"])
    parser.add_argument("--intent-backend", choices=helper_backend_choices)
    parser.add_argument("--intent-provider")
    parser.add_argument("--intent-model")
    parser.add_argument("--intent-timeout", type=int)
    parser.add_argument("--intent-base-url")
    parser.add_argument("--intent-api-key-env")
    parser.add_argument("--intent-fallback-backend", choices=fallback_backend_choices)
    parser.add_argument("--state-audit-ai", choices=helper_backend_choices)
    parser.add_argument("--state-audit-provider")
    parser.add_argument("--state-audit-model")
    parser.add_argument("--state-audit-timeout", type=int)
    parser.add_argument("--archivist-suggest", action="store_true", default=None)
    parser.add_argument("--archivist-ai", choices=helper_backend_choices)
    parser.add_argument("--archivist-provider")
    parser.add_argument("--archivist-model")
    parser.add_argument("--archivist-timeout", type=int)
    parser.add_argument("--no-archivist-enqueue", action="store_true")
    parser.add_argument("--transport", default="stdio", choices=["stdio"])
    args = parser.parse_args(argv)
    config = MCPAdapterConfig.from_values(
        args.root,
        default_campaign=args.default_campaign,
        default_save=args.default_save,
        default_starter_save=args.default_starter_save,
        registry_active=args.registry_active,
        mcp_profile=args.mcp_profile,
        ai_profile=args.ai_profile,
        ai_provider=args.ai_provider,
        ai_model=args.ai_model,
        ai_timeout=args.ai_timeout,
        semantic_ai=args.semantic_ai,
        semantic_provider=args.semantic_provider,
        semantic_model=args.semantic_model,
        semantic_timeout=args.semantic_timeout,
        intent_ai=args.intent_ai,
        intent_backend=args.intent_backend,
        intent_provider=args.intent_provider,
        intent_model=args.intent_model,
        intent_timeout=args.intent_timeout,
        intent_base_url=args.intent_base_url,
        intent_api_key_env=args.intent_api_key_env,
        intent_fallback_backend=args.intent_fallback_backend,
        state_audit_ai=args.state_audit_ai,
        state_audit_provider=args.state_audit_provider,
        state_audit_model=args.state_audit_model,
        state_audit_timeout=args.state_audit_timeout,
        archivist_suggest=args.archivist_suggest,
        archivist_ai=args.archivist_ai,
        archivist_provider=args.archivist_provider,
        archivist_model=args.archivist_model,
        archivist_timeout=args.archivist_timeout,
        archivist_enqueue=not args.no_archivist_enqueue,
    )
    serve_mcp(config, transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
