from __future__ import annotations

from dataclasses import dataclass

from .defaults import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
    DEFAULT_INTENT_TIMEOUT_SECONDS,
    DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
    DEFAULT_STATE_AUDIT_AI,
    DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
)

AI_PROFILES = ("off", "balanced", "full")
INTENT_AI_MODES = ("off", "consensus")
AI_HELPER_BACKENDS = ("off", "direct", "hermes_z")
AI_HELPER_FALLBACK_BACKENDS = ("off", "hermes_z")
AI_HELPER_BACKEND_ALIASES = {"hermes": "hermes_z"}


@dataclass(frozen=True)
class AIHelperSettings:
    profile: str
    semantic_ai: str
    semantic_provider: str
    semantic_model: str
    semantic_timeout: int
    intent_ai: str
    intent_backend: str
    intent_provider: str
    intent_model: str
    intent_timeout: int
    intent_base_url: str
    intent_api_key_env: str
    intent_fallback_backend: str
    state_audit_ai: str
    state_audit_provider: str
    state_audit_model: str
    state_audit_timeout: int
    archivist_suggest: bool
    archivist_ai: str
    archivist_provider: str
    archivist_model: str
    archivist_timeout: int


def resolve_ai_helper_settings(
    *,
    profile: str = "off",
    provider: str | None = None,
    model: str | None = None,
    timeout: int | None = None,
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
) -> AIHelperSettings:
    normalized_profile = str(profile or "off").strip().lower()
    if normalized_profile not in AI_PROFILES:
        raise ValueError(f"unsupported ai profile: {profile}; expected one of {', '.join(AI_PROFILES)}")

    profile_defaults = {
        "off": ("off", "off", "direct", DEFAULT_STATE_AUDIT_AI, False, "off"),
        "balanced": ("direct", "off", "direct", DEFAULT_STATE_AUDIT_AI, False, "off"),
        "full": ("direct", "consensus", "direct", "direct", True, "direct"),
    }
    (
        default_semantic,
        default_intent,
        default_intent_backend,
        default_state_audit,
        default_archivist_suggest,
        default_archivist,
    ) = profile_defaults[normalized_profile]
    common_provider = clean_required(provider, DEFAULT_AI_PROVIDER, "ai provider")
    common_model = clean_required(model, DEFAULT_AI_MODEL, "ai model")

    return AIHelperSettings(
        profile=normalized_profile,
        semantic_ai=normalize_backend(semantic_ai, default_semantic),
        semantic_provider=clean_required(semantic_provider, common_provider, "semantic provider"),
        semantic_model=clean_required(semantic_model, common_model, "semantic model"),
        semantic_timeout=normalize_timeout_value(semantic_timeout, timeout, DEFAULT_SEMANTIC_TIMEOUT_SECONDS),
        intent_ai=normalize_intent_ai(intent_ai, default_intent),
        intent_backend=normalize_backend(intent_backend, default_intent_backend),
        intent_provider=clean_required(intent_provider, common_provider, "intent provider"),
        intent_model=clean_required(intent_model, common_model, "intent model"),
        intent_timeout=normalize_timeout_value(intent_timeout, timeout, DEFAULT_INTENT_TIMEOUT_SECONDS),
        intent_base_url=clean_optional(intent_base_url),
        intent_api_key_env=clean_optional(intent_api_key_env),
        intent_fallback_backend=normalize_fallback_backend(intent_fallback_backend, "off"),
        state_audit_ai=normalize_backend(state_audit_ai, default_state_audit),
        state_audit_provider=clean_required(state_audit_provider, common_provider, "state audit provider"),
        state_audit_model=clean_required(state_audit_model, common_model, "state audit model"),
        state_audit_timeout=normalize_timeout_value(
            state_audit_timeout, timeout, DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS
        ),
        archivist_suggest=default_archivist_suggest if archivist_suggest is None else bool(archivist_suggest),
        archivist_ai=normalize_backend(archivist_ai, default_archivist),
        archivist_provider=clean_required(archivist_provider, common_provider, "archivist provider"),
        archivist_model=clean_required(archivist_model, common_model, "archivist model"),
        archivist_timeout=normalize_timeout_value(archivist_timeout, timeout, DEFAULT_ARCHIVIST_TIMEOUT_SECONDS),
    )


def normalize_backend(value: str | None, default: str) -> str:
    backend = str(default if value is None else value).strip().lower()
    backend = AI_HELPER_BACKEND_ALIASES.get(backend, backend)
    if backend not in set(AI_HELPER_BACKENDS):
        raise ValueError(f"unsupported ai helper backend: {backend}")
    return backend


def normalize_fallback_backend(value: str | None, default: str = "off") -> str:
    backend = str(default if value is None else value).strip().lower()
    backend = AI_HELPER_BACKEND_ALIASES.get(backend, backend)
    if backend not in set(AI_HELPER_FALLBACK_BACKENDS):
        raise ValueError(
            f"unsupported ai helper fallback backend: {backend}; expected one of {', '.join(AI_HELPER_FALLBACK_BACKENDS)}"
        )
    return backend


def normalize_intent_ai(value: str | None, default: str) -> str:
    mode = str(default if value is None else value).strip().lower()
    if mode not in INTENT_AI_MODES:
        raise ValueError(f"unsupported intent ai mode: {mode}; expected one of {', '.join(INTENT_AI_MODES)}")
    return mode


def clean_required(value: str | None, default: str, label: str) -> str:
    resolved = str(default if value is None else value).strip()
    if not resolved:
        raise ValueError(f"{label} must not be empty")
    return resolved


def clean_optional(value: str | None) -> str:
    return str(value or "").strip()


def normalize_timeout_value(task_value: int | None, common_value: int | None, default: int) -> int:
    value = default if task_value is None and common_value is None else (common_value if task_value is None else task_value)
    return min(120, max(3, int(value)))
