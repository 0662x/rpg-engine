from __future__ import annotations

DEFAULT_AI_PROVIDER = "deepseek"
DEFAULT_AI_MODEL = "deepseek-v4-flash"

# Keep live play responsive. Model-backed helpers stay opt-in; deterministic
# state audit is the default write guard and does not call the model.
DEFAULT_SEMANTIC_TIMEOUT_SECONDS = 8
DEFAULT_INTENT_TIMEOUT_SECONDS = 8
DEFAULT_ARCHIVIST_TIMEOUT_SECONDS = 8
DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS = 8
DEFAULT_REFLECTION_TIMEOUT_SECONDS = 12

DEFAULT_STATE_AUDIT_ENABLED = True
DEFAULT_STATE_AUDIT_AI = "off"
