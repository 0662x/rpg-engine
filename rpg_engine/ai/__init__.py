from __future__ import annotations

from .defaults import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_AI_HARD_TIMEOUT_SECONDS,
    DEFAULT_AI_SOFT_WAIT_SECONDS,
    DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
    DEFAULT_BACKGROUND_TARGET_MAX_SECONDS,
    DEFAULT_BACKGROUND_TARGET_MIN_SECONDS,
    DEFAULT_INTENT_TIMEOUT_SECONDS,
    DEFAULT_REFLECTION_TIMEOUT_SECONDS,
    DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
    DEFAULT_STATE_AUDIT_AI,
    DEFAULT_STATE_AUDIT_ENABLED,
    DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
)
from .config import (
    AI_HELPER_BACKENDS,
    AI_HELPER_FALLBACK_BACKENDS,
    AI_PROFILES,
    INTENT_AI_MODES,
    AIHelperSettings,
    resolve_ai_helper_settings,
)
from .provider import AIHelperResult, InternalAIService, run_ai_helper_json
from .advisory import (
    ResidentAIAdvisory,
    normalize_resident_ai_advisory,
    resident_ai_advisory_to_maintenance_dict,
    resident_ai_advisory_to_player_dict,
)
from .advisory_adapters import adapt_internal_intent_review_advisory, adapt_state_audit_progress_advisory
from .advisory_review import (
    AdvisoryReviewArtifact,
    advisory_review_to_maintenance_dict,
    advisory_review_to_player_dict,
    build_advisory_review_artifact,
)
from .schemas import ArchivistSuggestion, ReflectionAIOutput, SemanticSuggestion, StateAuditResult
from .tasks import AIHelperTask

__all__ = [
    "AIHelperResult",
    "AIHelperSettings",
    "AIHelperTask",
    "AI_HELPER_BACKENDS",
    "AI_HELPER_FALLBACK_BACKENDS",
    "AI_PROFILES",
    "ArchivistSuggestion",
    "AdvisoryReviewArtifact",
    "DEFAULT_AI_MODEL",
    "DEFAULT_AI_PROVIDER",
    "DEFAULT_AI_HARD_TIMEOUT_SECONDS",
    "DEFAULT_AI_SOFT_WAIT_SECONDS",
    "DEFAULT_ARCHIVIST_TIMEOUT_SECONDS",
    "DEFAULT_BACKGROUND_TARGET_MAX_SECONDS",
    "DEFAULT_BACKGROUND_TARGET_MIN_SECONDS",
    "DEFAULT_INTENT_TIMEOUT_SECONDS",
    "DEFAULT_REFLECTION_TIMEOUT_SECONDS",
    "DEFAULT_SEMANTIC_TIMEOUT_SECONDS",
    "DEFAULT_STATE_AUDIT_AI",
    "DEFAULT_STATE_AUDIT_ENABLED",
    "DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS",
    "INTENT_AI_MODES",
    "InternalAIService",
    "ReflectionAIOutput",
    "ResidentAIAdvisory",
    "SemanticSuggestion",
    "StateAuditResult",
    "run_ai_helper_json",
    "adapt_internal_intent_review_advisory",
    "adapt_state_audit_progress_advisory",
    "advisory_review_to_maintenance_dict",
    "advisory_review_to_player_dict",
    "build_advisory_review_artifact",
    "normalize_resident_ai_advisory",
    "resident_ai_advisory_to_maintenance_dict",
    "resident_ai_advisory_to_player_dict",
    "resolve_ai_helper_settings",
]
