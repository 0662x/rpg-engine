from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .actions import ActionResolverRegistry, get_default_action_registry
from .ai.config import normalize_backend, normalize_fallback_backend
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
from .ai.provider import AIHelperResult, public_ai_helper_result_dict
from .campaign import Campaign, load_campaign
from .capabilities import ACTION_CAPABILITIES, CAPABILITY_INTENTS, capability_for_action
from .commit_service import commit_turn_proposal
from .context_builder import ContextBuildResult, build_context
from .db import connect
from .ai_intent.internal_review import collect_internal_intent_candidate
from .intent_router import (
    ActionIntent,
    ExternalCandidateInput,
    IntentAIConfig,
    IntentRequestMeta,
    action_intent_from_dict,
    action_intent_to_dict,
    detect_preview_action_mismatch,
    make_intent_ai_config,
    make_intent_request_meta,
    normalize_player_text,
    prepare_intent_candidates,
    route_intent,
    turn_contract_from_dict,
    turn_contract_to_dict,
    turn_contract_for_intent,
)
from .preflight_cache import (
    PREFLIGHT_EXPIRED,
    PREFLIGHT_FAILED,
    PREFLIGHT_IDENTITY_CANDIDATE_BOUND,
    PREFLIGHT_IDENTITY_MESSAGE_ONLY,
    PREFLIGHT_READY,
    create_pending_intent_preflight,
    hash_text,
    is_expired,
    mark_intent_preflight_failed,
    mark_intent_preflight_ready,
    normalize_identity_profile,
    validate_preflight_creation_identity,
)
from .proposal import TurnProposal, intent_context_id_from_intent, preflight_id_from_intent, turn_proposal_from_dict
from .redaction import redact_player_hidden_material
from .render import render_entity, render_scene
from .ux import PlanStep, RepairOption, UxStatus
from .validation_issues import issues_from_messages
from .validators import run_checks
from .validation_pipeline import run_validation_pipeline
from .visibility import can_read_hidden, normalize_visibility_view
from .write_guard import add_generated_write_guards


@dataclass(frozen=True)
class StartTurnResult:
    campaign_id: str
    user_text: str
    mode: str
    submode: str
    can_proceed: bool
    must_save: bool
    requires_preview: bool
    missing_required: tuple[str, ...] = ()
    needs_user_confirmation: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    intent: dict[str, Any] | None = None
    clarification: dict[str, Any] | None = None
    turn_contract: dict[str, Any] | None = None
    decision_trace: dict[str, Any] = field(default_factory=dict)
    context: ContextBuildResult | None = None

    @property
    def markdown(self) -> str:
        return self.context.markdown if self.context else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "user_text": self.user_text,
            "mode": self.mode,
            "submode": self.submode,
            "can_proceed": self.can_proceed,
            "must_save": self.must_save,
            "requires_preview": self.requires_preview,
            "missing_required": list(self.missing_required),
            "needs_user_confirmation": list(self.needs_user_confirmation),
            "assumptions": list(self.assumptions),
            "intent": self.intent,
            "clarification": self.clarification,
            "turn_contract": self.turn_contract,
            "decision_trace": self.decision_trace,
            "context": context_to_dict(self.context),
            "markdown": self.markdown,
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class QueryResult:
    campaign_id: str
    kind: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    context: ContextBuildResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "kind": self.kind,
            "text": self.text,
            "data": self.data,
            "context": context_to_dict(self.context),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class IntentPreflightResult:
    campaign_id: str
    ok: bool
    preflight_id: str
    status: str
    source_user_text_hash: str
    message_id: str = ""
    identity_profile: str = PREFLIGHT_IDENTITY_CANDIDATE_BOUND
    expires_at: str = ""
    internal_review: dict[str, Any] | None = None
    internal_helper: dict[str, Any] | None = None
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "ok": self.ok,
            "preflight_id": self.preflight_id,
            "status": self.status,
            "source_user_text_hash": self.source_user_text_hash,
            "message_id": self.message_id,
            "identity_profile": self.identity_profile,
            "expires_at": self.expires_at,
            "internal_review": self.internal_review,
            "internal_helper": self.internal_helper,
            "errors": list(self.errors),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class PreviewActionResult:
    campaign_id: str
    action: str
    ok: bool
    status: UxStatus = "ready"
    ready_to_save: bool = False
    markdown: str = ""
    player_message: str = ""
    interpretation: dict[str, Any] = field(default_factory=dict)
    plan: tuple[PlanStep, ...] = ()
    repair_options: tuple[RepairOption, ...] = ()
    delta_draft: dict[str, Any] | None = None
    turn_proposal: dict[str, Any] | None = None
    missing_required: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "action": self.action,
            "ok": self.ok,
            "status": self.status,
            "ready_to_save": self.ready_to_save,
            "markdown": self.markdown,
            "player_message": self.player_message,
            "interpretation": self.interpretation,
            "plan": [asdict(item) for item in self.plan],
            "repair_options": [asdict(item) for item in self.repair_options],
            "delta_draft": self.delta_draft if self.ready_to_save else None,
            "turn_proposal": self.turn_proposal if self.ready_to_save else None,
            "missing_required": list(self.missing_required),
            "errors": list(self.errors),
            "error_details": issues_from_messages(self.errors, default_code="PREVIEW_ACTION_ERROR"),
            "warnings": list(self.warnings),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class DeltaValidationResult:
    campaign_id: str
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "ok": self.ok,
            "errors": list(self.errors),
            "error_details": issues_from_messages(self.errors, default_code="DELTA_VALIDATION_ERROR"),
            "warnings": list(self.warnings),
            "missing_required": list(self.missing_required),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class CommitTurnResult:
    campaign_id: str
    turn_id: str
    profile: str = "player_turn_commit"
    write_status: str = "committed"
    projection_status: str | None = None
    backup_id: str | None = None
    snapshot_path: Path | None = None
    snapshot_json_path: Path | None = None
    cards_count: int = 0
    archivist_suggestion_id: str | None = None
    archivist_proposal_ids: tuple[str, ...] = ()
    archivist_ai_status: str | None = None
    state_audit: dict[str, Any] | None = None
    check_errors: tuple[str, ...] = ()
    validation_report: dict[str, Any] | None = None
    projection_report: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        projection_ok = True
        if self.projection_report is not None:
            projection_ok = bool(self.projection_report.get("ok", self.projection_status == "clean"))
        return self.write_status == "committed" and not self.check_errors and projection_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "turn_id": self.turn_id,
            "profile": self.profile,
            "ok": self.ok,
            "write_status": self.write_status,
            "projection_status": self.projection_status,
            "backup_id": self.backup_id,
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
            "snapshot_json_path": str(self.snapshot_json_path) if self.snapshot_json_path else None,
            "cards_count": self.cards_count,
            "archivist_suggestion_id": self.archivist_suggestion_id,
            "archivist_proposal_ids": list(self.archivist_proposal_ids),
            "archivist_ai_status": self.archivist_ai_status,
            "state_audit": self.state_audit,
            "check_errors": list(self.check_errors),
            "validation_report": self.validation_report,
            "projection_report": self.projection_report,
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class HealthResult:
    campaign_id: str
    ok: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "ok": self.ok,
            "errors": list(self.errors),
            "error_details": issues_from_messages(self.errors, default_code="HEALTH_CHECK_ERROR"),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class UxMetricsResult:
    campaign_id: str
    current_turn_id: str
    current_location_id: str
    total_turns: int
    turns_by_intent: dict[str, int] = field(default_factory=dict)
    recent_intents: tuple[str, ...] = ()
    scene_affordance_count: int = 0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "current_turn_id": self.current_turn_id,
            "current_location_id": self.current_location_id,
            "total_turns": self.total_turns,
            "turns_by_intent": dict(self.turns_by_intent),
            "recent_intents": list(self.recent_intents),
            "scene_affordance_count": self.scene_affordance_count,
            "notes": list(self.notes),
        }

    def to_json_text(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def context_to_dict(context: ContextBuildResult | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "contract": context.contract,
        "scope": context.scope,
        "request": context.request,
        "budget": context.budget,
        "completeness": context.completeness,
        "loaded_items": context.loaded_items,
        "omitted_items": context.omitted_items,
        "sections": context.sections,
        "markdown": context.markdown,
    }


def ai_helper_result_to_dict(helper: Any) -> dict[str, Any]:
    return public_ai_helper_result_dict(helper)


def normalize_turn_proposal(proposal: dict[str, Any] | TurnProposal | None) -> TurnProposal | None:
    if proposal is None:
        return None
    if isinstance(proposal, TurnProposal):
        return proposal
    if isinstance(proposal, dict):
        return turn_proposal_from_dict(proposal)
    raise TypeError("turn_proposal must be a TurnProposal or object")


def preview_status(validation: Any, resolution: Any) -> UxStatus:
    if validation.errors:
        return "blocked"
    if validation.missing_required:
        return "clarify"
    status = str(getattr(resolution, "status", "") or "").strip()
    if status == "ready":
        return "ready"
    if status == "blocked":
        return "blocked"
    if status == "clarify":
        return "clarify"
    if status == "internal_error":
        return "internal_error"
    if status == "needs_confirmation":
        return "needs_confirmation"
    return "needs_confirmation"


def default_player_message(
    action: str,
    status: UxStatus,
    missing_required: list[str],
    errors: list[str],
    warnings: list[str],
    confirmations: tuple[str, ...],
) -> str:
    if status == "ready":
        return f"{action} 预演已准备好，可以提交结构化 delta。"
    if status == "clarify":
        missing = ", ".join(missing_required) if missing_required else "更多行动细节"
        return f"还需要补充 {missing}，我才能可靠结算这次 {action}。"
    if status == "needs_confirmation":
        detail = first_text(confirmations) or first_text(warnings) or "这次行动需要确认。"
        return f"需要确认后再结算：{detail}"
    if status == "blocked":
        detail = first_text(errors) or first_text(confirmations) or "当前世界状态不允许直接执行。"
        return f"无法直接执行 {action}：{detail}"
    detail = first_text(errors) or "系统未能完成预演。"
    return f"预演失败：{detail}"


def turn_proposal_from_preview_context(
    campaign_id: str,
    action: str,
    options: dict[str, Any],
    context: dict[str, Any],
    delta: dict[str, Any] | None,
    status: str,
    resolution: Any,
    source_user_text: str = "",
    registry: ActionResolverRegistry | None = None,
) -> dict[str, Any] | None:
    if delta is None:
        return None
    intent_data = context.get("intent")
    contract_data = context.get("turn_contract")
    if isinstance(intent_data, dict) and isinstance(contract_data, dict):
        intent = action_intent_from_dict(intent_data)
        contract = turn_contract_from_dict(contract_data)
    else:
        intent = ActionIntent(
            user_text=source_user_text,
            mode="action",
            submode=action,
            action=action,
            options=dict(options or {}),
            confidence=str(getattr(resolution, "confidence", "") or "explicit"),
            source="preview_action",
            kind="single",
            status="ready",
        )
        contract = turn_contract_for_intent(intent, registry=registry)
    intent_context_id = intent_context_id_from_intent(intent)
    preflight_id = preflight_id_from_intent(intent)
    provenance = {"source": "runtime.preview_action", "resolver": action}
    if intent_context_id:
        provenance["intent_context_id"] = intent_context_id
    if preflight_id:
        provenance["preflight_id"] = preflight_id
    return TurnProposal(
        proposal_id=f"turn-proposal:{campaign_id}:{action}",
        intent=intent,
        context_id=intent_context_id,
        preview={
            "action": action,
            "status": status,
            "facts_used": list(resolution.facts_used),
            "rules_applied": list(resolution.rules_applied),
        },
        response_text=None,
        delta=delta,
        delta_source="resolver_proposed",
        provenance=provenance,
        human_confirmed=False,
        facts_used=tuple(str(item) for item in resolution.facts_used),
        narrative_claims=(),
        turn_contract=contract,
    ).to_dict()


def redact_runtime_value(conn: Any, value: Any) -> Any:
    return redact_player_hidden_material(conn, value, drop_empty=False)


def redact_runtime_value_for_view(conn: Any, value: Any, view: str | None) -> Any:
    return value if can_read_hidden(view) else redact_runtime_value(conn, value)


def redact_runtime_tuple(conn: Any, values: tuple[Any, ...] | list[Any]) -> tuple[Any, ...]:
    redacted = redact_runtime_value(conn, tuple(values))
    return redacted if isinstance(redacted, tuple) else tuple(values)


def redact_runtime_tuple_for_view(conn: Any, values: tuple[Any, ...] | list[Any], view: str | None) -> tuple[Any, ...]:
    return tuple(values) if can_read_hidden(view) else redact_runtime_tuple(conn, values)


def redact_repair_options(conn: Any, options: tuple[RepairOption, ...]) -> tuple[RepairOption, ...]:
    return tuple(
        replace(
            option,
            label=str(redact_runtime_value(conn, option.label)),
            description=str(redact_runtime_value(conn, option.description)),
            action=str(redact_runtime_value(conn, option.action)) if option.action is not None else None,
            options=redact_runtime_value(conn, option.options),
            effect=str(redact_runtime_value(conn, option.effect)),
        )
        for option in options
    )


def redact_plan_steps(conn: Any, steps: tuple[PlanStep, ...]) -> tuple[PlanStep, ...]:
    return tuple(
        replace(
            step,
            action=str(redact_runtime_value(conn, step.action)),
            label=str(redact_runtime_value(conn, step.label)),
            options=redact_runtime_value(conn, step.options),
            delta_draft=redact_runtime_value(conn, step.delta_draft) if step.delta_draft is not None else None,
        )
        for step in steps
    )


def redact_preview_result(conn: Any, result: PreviewActionResult) -> PreviewActionResult:
    return replace(
        result,
        action=str(redact_runtime_value(conn, result.action)),
        markdown=str(redact_runtime_value(conn, result.markdown)),
        player_message=str(redact_runtime_value(conn, result.player_message)),
        interpretation=redact_runtime_value(conn, result.interpretation),
        plan=redact_plan_steps(conn, tuple(result.plan)),
        repair_options=redact_repair_options(conn, tuple(result.repair_options)),
        delta_draft=redact_runtime_value(conn, result.delta_draft) if result.delta_draft is not None else None,
        turn_proposal=redact_runtime_value(conn, result.turn_proposal) if result.turn_proposal is not None else None,
        missing_required=redact_runtime_tuple(conn, tuple(result.missing_required)),
        errors=redact_runtime_tuple(conn, tuple(result.errors)),
        warnings=redact_runtime_tuple(conn, tuple(result.warnings)),
    )


def redact_preview_result_for_view(conn: Any, result: PreviewActionResult, view: str | None) -> PreviewActionResult:
    return result if can_read_hidden(view) else redact_preview_result(conn, result)


def default_repair_options(
    action: str,
    status: UxStatus,
    missing_required: list[str],
    errors: list[str],
    confirmations: tuple[str, ...],
) -> tuple[RepairOption, ...]:
    if status == "ready":
        return ()
    if status == "clarify":
        missing = ", ".join(missing_required) if missing_required else "行动细节"
        return (
            RepairOption(
                id="clarify_request",
                label="补充细节",
                description=f"补充 {missing} 后重新预演。",
                action=action,
                effect="重新解析玩家意图",
                requires_confirmation=False,
            ),
        )
    if status == "needs_confirmation":
        detail = first_text(confirmations) or "确认后重新预演或提交。"
        return (
            RepairOption(
                id="confirm_or_adjust",
                label="确认或调整",
                description=detail,
                action=action,
                effect="确认 GM 裁决后继续",
            ),
        )
    detail = first_text(errors) or first_text(confirmations) or "修改行动后重试。"
    return (
        RepairOption(
            id="revise_action",
            label="修改行动",
            description=detail,
            action=action,
            effect="用更明确或可行的方式重新预演",
            risk_level="none",
            requires_confirmation=False,
        ),
    )


def invalid_action_option_errors(options: dict[str, Any] | None) -> list[str]:
    if options is None:
        return []
    if not isinstance(options, dict):
        return [f"options must be an object, got {type(options).__name__}"]
    errors: list[str] = []
    for key, value in options.items():
        if not isinstance(key, str):
            errors.append(f"option key must be a string: {key!r}")
            continue
        if isinstance(value, (dict, list, tuple, set)):
            errors.append(f"option {key} must be a scalar value")
            continue
        if isinstance(value, str):
            normalized = normalize_player_text(value)
            lowered = normalized.lower()
            if len(normalized) > 8000:
                errors.append(f"option {key} is too long")
            if has_unsafe_control_characters(normalized):
                errors.append(f"option {key} contains control characters")
            if (
                normalized.strip().startswith(("/", "---", "{", "["))
                or "```" in normalized
                or re.search(r"(\.\./|~/.ssh|/etc/passwd|id_rsa|<script|</script|{{|}})", lowered)
                or re.search(r"\b(drop\s+table|delete\s+from|rm\s+-rf|python\s+-c|aigm\s+|commit_turn)\b", lowered)
            ):
                errors.append(f"option {key} looks like a command or structured payload")
    return errors


def first_text(items: tuple[str, ...] | list[str]) -> str:
    for item in items:
        text = str(item).strip()
        if text:
            return text
    return ""


def normalize_player_text(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text))


def has_unsafe_control_characters(text: str) -> bool:
    for char in str(text):
        if char in "\n\r\t":
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            return True
    return False


def render_intent_plan_markdown(intent: ActionIntent) -> str:
    lines = [
        "# 行动计划预演",
        "",
        "## GM理解",
        intent.summary or intent.user_text,
        "",
        "## 将执行",
    ]
    for step in intent.plan:
        lines.append(f"- `{step.action}` {step.label}")
    lines.extend(["", "## 选择"])
    for option in intent.repair_options:
        lines.append(f"- {option.label}: {option.effect}")
    return "\n".join(lines).rstrip() + "\n"


def query_kind_for_intent(submode: str) -> str:
    normalized = str(submode or "").strip().lower()
    if normalized in {"scene", "entity", "context"}:
        return normalized
    if normalized == "rule":
        return "context"
    return "entity"


def query_text_for_intent(intent: ActionIntent, query_kind: str) -> str | None:
    if query_kind == "scene":
        return None
    for key in ("query_text", "query", "target"):
        text = str(intent.options.get(key) or "").strip()
        if text:
            return text
    return intent.user_text


def intent_ai_config_kwargs(config: IntentAIConfig) -> dict[str, Any]:
    return {
        "intent_ai": config.mode,
        "intent_backend": config.backend,
        "intent_provider": config.provider,
        "intent_model": config.model,
        "intent_timeout": config.timeout,
        "intent_base_url": config.base_url,
        "intent_api_key_env": config.api_key_env,
        "intent_fallback_backend": config.fallback_backend,
    }


def intent_request_meta_kwargs(meta: IntentRequestMeta) -> dict[str, Any]:
    return {
        "preflight_id": meta.preflight_id,
        "message_id": meta.message_id,
        "platform": meta.platform,
        "session_key": meta.session_key,
        "source_user_text_hash": meta.source_user_text_hash,
        "preflight_pending_wait_ms": meta.preflight_pending_wait_ms,
    }


class GMRuntime:
    """Stable V1-facing facade over the existing engine internals."""

    def __init__(self, campaign: Campaign) -> None:
        self.campaign = campaign
        self.action_registry = get_default_action_registry()

    @classmethod
    def from_path(cls, campaign_dir: str | Path) -> GMRuntime:
        return cls(load_campaign(campaign_dir))

    def preflight_intent(
        self,
        user_text: str,
        *,
        intent_backend: str = "direct",
        intent_model: str = DEFAULT_AI_MODEL,
        intent_provider: str = DEFAULT_AI_PROVIDER,
        intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        intent_base_url: str = "",
        intent_api_key_env: str = "",
        intent_fallback_backend: str = "off",
        external_intent_candidate: dict[str, Any] | None = None,
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_identity_profile: str = PREFLIGHT_IDENTITY_CANDIDATE_BOUND,
        ttl_seconds: int = 300,
    ) -> IntentPreflightResult:
        text = normalize_player_text(user_text).strip()
        resolved_hash = hash_text(text)
        try:
            effective_intent_backend = normalize_backend(intent_backend, "direct")
            effective_intent_fallback_backend = normalize_fallback_backend(intent_fallback_backend, "off")
            effective_identity_profile = validate_preflight_creation_identity(
                normalize_identity_profile(preflight_identity_profile),
                platform=platform,
                session_key=session_key,
                message_id=message_id,
                source_user_text_hash=resolved_hash,
            )
        except ValueError as exc:
            return IntentPreflightResult(
                campaign_id=self.campaign.campaign_id,
                ok=False,
                preflight_id="",
                status="failed",
                source_user_text_hash=resolved_hash,
                message_id=message_id,
                identity_profile=preflight_identity_profile,
                errors=(str(exc),),
            )
        if not text:
            return IntentPreflightResult(
                campaign_id=self.campaign.campaign_id,
                ok=False,
                preflight_id="",
                status="failed",
                source_user_text_hash=resolved_hash,
                message_id=message_id,
                identity_profile=effective_identity_profile,
                errors=("user_text is required",),
            )
        if source_user_text_hash and source_user_text_hash.strip() != resolved_hash:
            return IntentPreflightResult(
                campaign_id=self.campaign.campaign_id,
                ok=False,
                preflight_id="",
                status="failed",
                source_user_text_hash=resolved_hash,
                message_id=message_id,
                identity_profile=effective_identity_profile,
                errors=("source_user_text_hash mismatch",),
            )
        with connect(self.campaign) as conn:
            prepared = prepare_intent_candidates(
                conn,
                text,
                external_candidate_input=ExternalCandidateInput(external_intent_candidate),
                registry=self.action_registry,
            )
            helper_external = (
                None
                if effective_identity_profile == PREFLIGHT_IDENTITY_MESSAGE_ONLY
                else prepared.external_low_trust_candidate
            )
            rule_candidate = prepared.rules_candidate
            record = create_pending_intent_preflight(
                conn,
                self.campaign,
                text,
                provider=intent_provider,
                model=intent_model,
                backend=effective_intent_backend,
                fallback_backend=effective_intent_fallback_backend,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=resolved_hash,
                external_candidate=helper_external.to_dict() if helper_external else None,
                rule_candidate=rule_candidate.to_dict(),
                action_taxonomy_digest=self.action_registry.taxonomy_digest,
                action_slot_digest=str(self.action_registry.slot_projection()["digest"]),
                identity_profile=effective_identity_profile,
                ttl_seconds=ttl_seconds,
            )
            conn.commit()
            try:
                helper = collect_internal_intent_candidate(
                    self.campaign,
                    conn,
                    text,
                    external_candidate=helper_external,
                    rule_candidate=rule_candidate,
                    backend=effective_intent_backend,
                    provider=intent_provider,
                    model=intent_model,
                    timeout=intent_timeout,
                    base_url=intent_base_url,
                    api_key_env=intent_api_key_env,
                    fallback_backend=effective_intent_fallback_backend,
                    execution_class="background",
                    registry=self.action_registry,
                )
            except Exception:
                helper = AIHelperResult(
                    task="internal_intent_review",
                    backend=effective_intent_backend,
                    provider=intent_provider,
                    model=intent_model,
                    status="error",
                    error="internal_intent_review ai unavailable",
                    failure_reason="unavailable",
                )
            if helper.ok and helper.parsed:
                final_status = mark_intent_preflight_ready(
                    conn,
                    record.id,
                    internal_review=helper.parsed,
                    helper_audit=helper.audit,
                )
                conn.commit()
                if final_status != PREFLIGHT_READY:
                    return IntentPreflightResult(
                        campaign_id=self.campaign.campaign_id,
                        ok=False,
                        preflight_id=record.id,
                        status=final_status,
                        source_user_text_hash=record.identity.source_user_text_hash,
                        message_id=record.message_id,
                        identity_profile=record.identity.identity_profile,
                        expires_at=record.expires_at,
                        internal_review=None,
                        internal_helper=ai_helper_result_to_dict(helper),
                        errors=("late_ready_unused",),
                    )
                ready_row = conn.execute(
                    "select status, expires_at, internal_review_json from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()
                try:
                    authoritative_review = json.loads(str(ready_row["internal_review_json"])) if ready_row else None
                except (json.JSONDecodeError, TypeError):
                    authoritative_review = None
                authoritative_expires_at = str(ready_row["expires_at"]) if ready_row else record.expires_at
                if (
                    ready_row is None
                    or str(ready_row["status"]) != PREFLIGHT_READY
                    or is_expired(authoritative_expires_at)
                    or not isinstance(authoritative_review, dict)
                    or not authoritative_review
                ):
                    authoritative_status = str(ready_row["status"]) if ready_row else PREFLIGHT_FAILED
                    return IntentPreflightResult(
                        campaign_id=self.campaign.campaign_id,
                        ok=False,
                        preflight_id=record.id,
                        status=(
                            PREFLIGHT_EXPIRED if is_expired(authoritative_expires_at) else authoritative_status
                        ),
                        source_user_text_hash=record.identity.source_user_text_hash,
                        message_id=record.message_id,
                        identity_profile=record.identity.identity_profile,
                        expires_at=authoritative_expires_at,
                        internal_helper=ai_helper_result_to_dict(helper),
                        errors=("late_ready_unused",),
                    )
                return IntentPreflightResult(
                    campaign_id=self.campaign.campaign_id,
                    ok=True,
                    preflight_id=record.id,
                    status="ready",
                    source_user_text_hash=record.identity.source_user_text_hash,
                    message_id=record.message_id,
                    identity_profile=record.identity.identity_profile,
                    expires_at=authoritative_expires_at,
                    internal_review=authoritative_review,
                    internal_helper=None,
                )
            public_helper = ai_helper_result_to_dict(helper)
            error = str(public_helper.get("error") or "internal_intent_review ai unavailable")
            final_status = mark_intent_preflight_failed(conn, record.id, error=error)
            conn.commit()
            result_expires_at = record.expires_at
            if final_status == PREFLIGHT_READY:
                ready_row = conn.execute(
                    "select status, expires_at, internal_review_json from intent_preflight_cache where id=?",
                    (record.id,),
                ).fetchone()
                if ready_row:
                    result_expires_at = str(ready_row["expires_at"])
                try:
                    authoritative_review = json.loads(str(ready_row["internal_review_json"])) if ready_row else None
                except (json.JSONDecodeError, TypeError):
                    authoritative_review = None
                authoritative_ready = (
                    ready_row is not None
                    and str(ready_row["status"]) == PREFLIGHT_READY
                    and not is_expired(result_expires_at)
                )
                if authoritative_ready and isinstance(authoritative_review, dict) and authoritative_review:
                    return IntentPreflightResult(
                        campaign_id=self.campaign.campaign_id,
                        ok=True,
                        preflight_id=record.id,
                        status=PREFLIGHT_READY,
                        source_user_text_hash=record.identity.source_user_text_hash,
                        message_id=record.message_id,
                        identity_profile=record.identity.identity_profile,
                        expires_at=result_expires_at,
                        internal_review=authoritative_review,
                    )
                final_status = (
                    PREFLIGHT_EXPIRED
                    if ready_row and is_expired(result_expires_at)
                    else str(ready_row["status"])
                    if ready_row
                    else PREFLIGHT_FAILED
                )
            return IntentPreflightResult(
                campaign_id=self.campaign.campaign_id,
                ok=False,
                preflight_id=record.id,
                status=final_status,
                source_user_text_hash=record.identity.source_user_text_hash,
                message_id=record.message_id,
                identity_profile=record.identity.identity_profile,
                expires_at=result_expires_at,
                internal_helper=public_helper,
                errors=(error,),
            )

    def start_turn(
        self,
        user_text: str,
        *,
        mode: str = "auto",
        submode: str | None = None,
        budget: int | None = None,
        max_events: int = 6,
        max_depth: int = 1,
        include_palettes: str = "auto",
        view: str | None = None,
        semantic_ai: str = "off",
        semantic_model: str = DEFAULT_AI_MODEL,
        semantic_provider: str = DEFAULT_AI_PROVIDER,
        semantic_timeout: int = DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
        intent_ai: str = "off",
        intent_backend: str = "direct",
        intent_model: str = DEFAULT_AI_MODEL,
        intent_provider: str = DEFAULT_AI_PROVIDER,
        intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        intent_base_url: str = "",
        intent_api_key_env: str = "",
        intent_fallback_backend: str = "off",
        external_intent_candidate: dict[str, Any] | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
        audit_context: bool = False,
        context_run_id: str | None = None,
    ) -> StartTurnResult:
        with connect(self.campaign) as conn:
            context = build_context(
                self.campaign,
                conn,
                user_text=user_text,
                mode=mode,
                submode=submode,
                budget=budget,
                max_events=max_events,
                max_depth=max_depth,
                include_palettes=include_palettes,
                view=view,
                semantic_ai=semantic_ai,
                semantic_model=semantic_model,
                semantic_provider=semantic_provider,
                semantic_timeout=semantic_timeout,
                intent_ai=intent_ai,
                intent_backend=intent_backend,
                intent_model=intent_model,
                intent_provider=intent_provider,
                intent_timeout=intent_timeout,
                intent_base_url=intent_base_url,
                intent_api_key_env=intent_api_key_env,
                intent_fallback_backend=intent_fallback_backend,
                external_intent_candidate=external_intent_candidate,
                preflight_id=preflight_id,
                message_id=message_id,
                platform=platform,
                session_key=session_key,
                source_user_text_hash=source_user_text_hash,
                preflight_pending_wait_ms=preflight_pending_wait_ms,
                audit_context=audit_context,
                audit_context_run_id=context_run_id,
                registry=self.action_registry,
            )
            if audit_context:
                conn.commit()
        request = context.request
        completeness = context.completeness
        missing_required = [str(item) for item in completeness.get("missing_required", [])]
        can_proceed = bool(completeness["allow_proceed"])
        if str(request["mode"]) == "action":
            capability = self.capability_for_action(str(request["submode"]))
            if capability and not self.supports_capability(capability):
                missing_required.append(f"unsupported capability: {capability}")
                can_proceed = False
        return StartTurnResult(
            campaign_id=self.campaign.campaign_id,
            user_text=str(request["user_text"]),
            mode=str(request["mode"]),
            submode=str(request["submode"]),
            can_proceed=can_proceed,
            must_save=bool(request["must_save"]),
            requires_preview=bool(request["requires_preview"]),
            missing_required=tuple(missing_required),
            needs_user_confirmation=tuple(str(item) for item in completeness.get("needs_user_confirmation", [])),
            assumptions=tuple(str(item) for item in completeness.get("assumptions", [])),
            intent=request.get("intent"),
            clarification=request.get("clarification") if isinstance(request.get("clarification"), dict) else None,
            turn_contract=request.get("turn_contract"),
            decision_trace=dict(request.get("decision_trace") or {}),
            context=context,
        )

    def query(
        self,
        kind: str,
        query_text: str | None = None,
        *,
        view: str = "player",
        budget: int | None = None,
    ) -> QueryResult:
        self.require_capability("query")
        normalized_kind = kind.strip().lower()
        normalized_view = normalize_visibility_view(view)
        with connect(self.campaign) as conn:
            if normalized_kind == "scene":
                text = render_scene(conn, view=normalized_view)
                return QueryResult(
                    campaign_id=self.campaign.campaign_id,
                    kind=normalized_kind,
                    text=str(redact_runtime_value_for_view(conn, text, normalized_view)),
                    data=redact_runtime_value_for_view(conn, {"view": normalized_view}, normalized_view),
                )
            if normalized_kind == "entity":
                if not query_text:
                    raise ValueError("entity query requires query_text")
                text = render_entity(conn, query_text, view=normalized_view)
                return QueryResult(
                    campaign_id=self.campaign.campaign_id,
                    kind=normalized_kind,
                    text=str(redact_runtime_value_for_view(conn, text, normalized_view)),
                    data=redact_runtime_value_for_view(conn, {"query": query_text, "view": normalized_view}, normalized_view),
                )
            if normalized_kind == "context":
                if not query_text:
                    raise ValueError("context query requires query_text")
                context = build_context(
                    self.campaign,
                    conn,
                    user_text=query_text,
                    mode="query",
                    submode="context",
                    view=normalized_view,
                    budget=budget,
                    registry=self.action_registry,
                )
                return QueryResult(
                    campaign_id=self.campaign.campaign_id,
                    kind=normalized_kind,
                    text=str(redact_runtime_value_for_view(conn, context.markdown, normalized_view)),
                    data=redact_runtime_value_for_view(conn, {"query": query_text, "view": normalized_view}, normalized_view),
                    context=context,
                )
            safe_kind = str(redact_runtime_value(conn, kind))
        raise ValueError(f"unsupported query kind: {safe_kind}")

    def preview_action(
        self,
        action: str,
        options: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
        source_user_text: str | None = None,
    ) -> PreviewActionResult:
        action_name = action.strip()
        runtime_context = context or {}
        request_view = normalize_visibility_view(str(runtime_context.get("view") or "player"))

        def safe_result(result: PreviewActionResult) -> PreviewActionResult:
            with connect(self.campaign) as conn:
                return redact_preview_result_for_view(conn, result, request_view)

        resolver = self.action_registry.get(action_name)
        if resolver is None:
            errors = [f"unsupported action: {action_name}"]
            return safe_result(PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action=action_name,
                ok=False,
                status="blocked",
                player_message=f"不支持的行动类型：{action_name}",
                repair_options=default_repair_options(action_name, "blocked", [], errors, ()),
                errors=tuple(errors),
            ))
        capability_error = self.capability_error_for_action(action_name)
        if capability_error:
            errors = [capability_error]
            return safe_result(PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action=action_name,
                ok=False,
                status="blocked",
                player_message=capability_error,
                repair_options=default_repair_options(action_name, "blocked", [], errors, ()),
                errors=tuple(errors),
            ))
        option_errors = invalid_action_option_errors(options)
        if option_errors:
            return safe_result(PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action=action_name,
                ok=False,
                status="blocked",
                player_message="行动参数格式不安全或不可解析，请改用普通文本、数字或布尔值。",
                repair_options=default_repair_options(action_name, "blocked", [], option_errors, ()),
                errors=tuple(option_errors),
            ))
        mismatch = detect_preview_action_mismatch(
            source_user_text,
            action_name,
            registry=self.action_registry,
        )
        if mismatch and mismatch.get("severity") == "needs_confirmation":
            warning = str(mismatch.get("message") or "source_user_text and action need confirmation")
            suggested_action = str(mismatch.get("expected_action") or "")
            result = PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action=action_name,
                ok=False,
                status="needs_confirmation",
                ready_to_save=False,
                player_message=warning,
                interpretation={
                    "action": action_name,
                    "source_user_text": source_user_text,
                    "suggested_action": suggested_action,
                    "decision_source": "preview_action_mismatch_guard",
                },
                repair_options=(
                    RepairOption(
                        id="use_preview_from_text",
                        label="改用文本预演",
                        description="让 IntentRouter 先判断自然语言行动类型。",
                        action=suggested_action if suggested_action in self.action_registry.names() else None,
                        effect="重新从玩家文本路由到正确 resolver",
                        risk_level="none",
                        requires_confirmation=False,
                    ),
                ),
                warnings=(warning,),
            )
            with connect(self.campaign) as conn:
                return redact_preview_result_for_view(conn, result, request_view)
        option_object = SimpleNamespace(**(options or {}))
        with connect(self.campaign) as conn:
            validation = resolver.request_contract(self.campaign, conn, runtime_context, option_object)
            resolution = resolver.resolve_contract(self.campaign, conn, runtime_context, option_object)
            preview_context = dict(runtime_context)
            if resolution.proposed_delta is not None:
                proposed_delta = dict(resolution.proposed_delta)
                add_generated_write_guards(conn, proposed_delta, prefix=f"preview-{action_name}")
                proposed_delta = redact_runtime_value_for_view(conn, proposed_delta, request_view)
                resolution = replace(resolution, proposed_delta=proposed_delta)
                preview_context["proposed_delta"] = proposed_delta
            markdown = resolver.preview(self.campaign, conn, preview_context, option_object)
            markdown = str(redact_runtime_value_for_view(conn, markdown, request_view))
            safe_runtime_context = redact_runtime_value_for_view(conn, runtime_context, request_view)
            safe_options = redact_runtime_value_for_view(conn, options or {}, request_view)
            safe_source_user_text = str(redact_runtime_value_for_view(conn, source_user_text, request_view))
            validation_missing_required = redact_runtime_tuple_for_view(conn, tuple(validation.missing_required), request_view)
            validation_errors = redact_runtime_tuple_for_view(conn, tuple(validation.errors), request_view)
            validation_warnings = redact_runtime_tuple_for_view(conn, tuple(validation.warnings), request_view)
            if not can_read_hidden(request_view):
                resolution = replace(
                    resolution,
                    facts_used=redact_runtime_tuple(conn, tuple(resolution.facts_used)),
                    rules_applied=redact_runtime_tuple(conn, tuple(resolution.rules_applied)),
                    confirmations=redact_runtime_tuple(conn, tuple(resolution.confirmations)),
                    warnings=redact_runtime_tuple(conn, tuple(resolution.warnings)),
                    narrative_constraints=redact_runtime_tuple(conn, tuple(resolution.narrative_constraints)),
                    player_message=str(redact_runtime_value(conn, resolution.player_message)),
                    repair_options=redact_repair_options(conn, tuple(resolution.repair_options)),
                    plan=redact_plan_steps(conn, tuple(resolution.plan)),
                )
        missing_required = list(validation_missing_required)
        errors = list(validation_errors)
        warnings = list(validation_warnings)
        if not resolution.ok:
            for item in resolution.confirmations:
                if item not in missing_required and item not in errors:
                    errors.append(item)
            if resolution.status == "blocked":
                for item in resolution.warnings:
                    if item not in errors:
                        errors.append(item)
            else:
                for item in resolution.warnings:
                    if item not in warnings:
                        warnings.append(item)
        else:
            for item in resolution.warnings:
                if item not in warnings:
                    warnings.append(item)
        mismatch_warning = detect_preview_action_mismatch(
            source_user_text,
            action_name,
            registry=self.action_registry,
        )
        if mismatch_warning and mismatch_warning.get("severity") == "warning":
            warning = str(mismatch_warning.get("message") or "")
            if warning and warning not in warnings:
                warnings.append(warning)
        status = preview_status(validation, resolution)
        delta_draft = resolution.proposed_delta if status == "ready" else None
        ready_to_save = status == "ready" and delta_draft is not None
        turn_proposal = turn_proposal_from_preview_context(
            self.campaign.campaign_id,
            action_name,
            safe_options,
            safe_runtime_context,
            delta_draft,
            status,
            resolution,
            safe_source_user_text,
            registry=self.action_registry,
        ) if ready_to_save else None
        return PreviewActionResult(
            campaign_id=self.campaign.campaign_id,
            action=action_name,
            ok=status == "ready",
            status=status,
            ready_to_save=ready_to_save,
            markdown=markdown,
            player_message=resolution.player_message or default_player_message(
                action_name,
                status,
                missing_required,
                errors,
                warnings,
                resolution.confirmations,
            ),
            interpretation={
                "action": action_name,
                "confidence": resolution.confidence,
                "facts_used": list(resolution.facts_used),
                "rules_applied": list(resolution.rules_applied),
                "narrative_constraints": list(resolution.narrative_constraints),
            },
            plan=resolution.plan,
            repair_options=resolution.repair_options or default_repair_options(
                action_name,
                status,
                missing_required,
                errors,
                resolution.confirmations,
            ),
            delta_draft=delta_draft,
            turn_proposal=turn_proposal,
            missing_required=tuple(missing_required),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def preview_from_text(
        self,
        user_text: str,
        *,
        view: str = "player",
        mode: str = "auto",
        submode: str | None = None,
        semantic_ai: str = "off",
        semantic_model: str = DEFAULT_AI_MODEL,
        semantic_provider: str = DEFAULT_AI_PROVIDER,
        semantic_timeout: int = DEFAULT_SEMANTIC_TIMEOUT_SECONDS,
        intent_ai: str = "off",
        intent_backend: str = "direct",
        intent_model: str = DEFAULT_AI_MODEL,
        intent_provider: str = DEFAULT_AI_PROVIDER,
        intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        intent_base_url: str = "",
        intent_api_key_env: str = "",
        intent_fallback_backend: str = "off",
        external_intent_candidate: dict[str, Any] | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> PreviewActionResult:
        text = user_text.strip()
        if not text:
            return PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action="act",
                ok=False,
                status="clarify",
                player_message="请描述你想做什么。",
                repair_options=(
                    RepairOption(
                        id="describe_action",
                        label="补充行动",
                        description="例如：找 An 问异常、在家盘点库存、去 L1 小溪收鱼笼。",
                        risk_level="none",
                        requires_confirmation=False,
                    ),
                ),
                missing_required=("user_text",),
            )
        intent_config = make_intent_ai_config(
            intent_ai=intent_ai,
            intent_backend=intent_backend,
            intent_provider=intent_provider,
            intent_model=intent_model,
            intent_timeout=intent_timeout,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
        )
        request_meta = make_intent_request_meta(
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )
        with connect(self.campaign) as conn:
            intent = route_intent(
                self.campaign,
                conn,
                text,
                mode=mode,
                submode=submode,
                semantic_ai=semantic_ai,
                semantic_provider=semantic_provider,
                semantic_model=semantic_model,
                semantic_timeout=semantic_timeout,
                **intent_ai_config_kwargs(intent_config),
                external_intent_candidate=external_intent_candidate,
                **intent_request_meta_kwargs(request_meta),
                view=view,
                registry=self.action_registry,
            )
        return self.preview_intent(intent, view=view)

    def preview_intent(self, intent: ActionIntent, *, view: str = "player") -> PreviewActionResult:
        intent_data = action_intent_to_dict(intent) or {}
        clarification_data = intent.clarification.to_dict() if intent.clarification else None
        turn_contract = turn_contract_for_intent(intent, registry=self.action_registry)
        contract_data = turn_contract_to_dict(turn_contract) or {}
        if intent.kind == "unresolved":
            next_tool = "reject_request" if intent.status == "blocked" and not clarification_data else "ask_clarification"
            result = PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action=str(intent.action or "act"),
                ok=False,
                status=intent.status,
                ready_to_save=False,
                player_message=intent.player_message or "需要补充行动细节。",
                interpretation={
                    "intent": intent_data,
                    "turn_contract": contract_data,
                    "clarification": clarification_data,
                    "recommended_next_tool": next_tool,
                    "commit_state": "not_saved",
                },
                plan=intent.plan,
                repair_options=intent.repair_options,
                missing_required=intent.missing_required,
                errors=intent.errors,
                warnings=intent.needs_confirmation,
            )
            with connect(self.campaign) as conn:
                return redact_preview_result_for_view(conn, result, view)
        if intent.mode == "query":
            query_kind = query_kind_for_intent(intent.submode)
            query_text = query_text_for_intent(intent, query_kind)
            try:
                query_result = self.query(
                    query_kind,
                    query_text,
                    view=view,
                )
            except Exception as exc:
                result = PreviewActionResult(
                    campaign_id=self.campaign.campaign_id,
                    action="query",
                    ok=False,
                    status="blocked",
                    ready_to_save=False,
                    player_message=f"查询无法执行：{exc}",
                    interpretation={
                        "intent": intent_data,
                        "turn_contract": contract_data,
                        "clarification": clarification_data,
                        "recommended_next_tool": "ask_clarification",
                        "commit_state": "not_saved",
                        "query": {"kind": query_kind, "executed": False},
                    },
                    errors=(str(exc),),
                )
                with connect(self.campaign) as conn:
                    return redact_preview_result_for_view(conn, result, view)
            query_data = query_result.to_dict()
            result = PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action="query",
                ok=True,
                status="ready",
                ready_to_save=False,
                markdown=query_result.text,
                player_message=query_result.text or "查询完成。",
                interpretation={
                    "intent": intent_data,
                    "turn_contract": contract_data,
                    "clarification": clarification_data,
                    "recommended_next_tool": "respond_to_player",
                    "commit_state": "not_saved",
                    "query": {
                        "kind": query_kind,
                        "executed": True,
                        "result": query_data,
                    },
                },
            )
            with connect(self.campaign) as conn:
                return redact_preview_result_for_view(conn, result, view)
        if intent.mode == "maintenance":
            result = PreviewActionResult(
                campaign_id=self.campaign.campaign_id,
                action="maintenance",
                ok=False,
                status="blocked",
                ready_to_save=False,
                player_message="这是维护或作者工具请求，不会作为普通玩家回合预演。",
                interpretation={
                    "intent": intent_data,
                    "turn_contract": contract_data,
                    "clarification": clarification_data,
                    "recommended_next_tool": "admin_or_maintenance_profile",
                    "commit_state": "not_saved",
                },
                warnings=("maintenance request is outside the player turn profile",),
            )
            with connect(self.campaign) as conn:
                return redact_preview_result_for_view(conn, result, view)
        if intent.kind == "single" and intent.action:
            result = self.preview_action(
                intent.action,
                dict(intent.options),
                context={"view": view, "intent": intent_data, "turn_contract": contract_data},
            )
            interpretation = dict(result.interpretation)
            route_mismatch = detect_preview_action_mismatch(
                intent.user_text,
                intent.action,
                registry=self.action_registry,
            )
            if route_mismatch:
                diagnostic = {**route_mismatch, "effect": "diagnostic_only"}
                interpretation["route_mismatch_diagnostic"] = diagnostic
                warning = str(route_mismatch.get("message") or "")
                if warning and warning not in result.warnings:
                    result = replace(result, warnings=(*result.warnings, warning))
            interpretation["intent"] = intent_data
            interpretation["turn_contract"] = contract_data
            interpretation["clarification"] = clarification_data
            interpretation["recommended_next_tool"] = "validate_delta" if result.ready_to_save else "ask_clarification"
            interpretation["commit_state"] = "validated_preview" if result.ready_to_save else "not_saved"
            turn_proposal = None
            if result.ready_to_save and result.delta_draft is not None:
                intent_context_id = intent_context_id_from_intent(intent)
                preflight_id = preflight_id_from_intent(intent)
                provenance = {
                    "source": "runtime.preview_intent",
                    "resolver": result.action,
                }
                if intent_context_id:
                    provenance["intent_context_id"] = intent_context_id
                if preflight_id:
                    provenance["preflight_id"] = preflight_id
                turn_proposal = TurnProposal(
                    proposal_id=f"turn-proposal:{self.campaign.campaign_id}:{intent.action or 'action'}",
                    intent=intent,
                    context_id=intent_context_id,
                    preview={
                        "action": result.action,
                        "status": result.status,
                        "facts_used": list(result.interpretation.get("facts_used", [])),
                        "rules_applied": list(result.interpretation.get("rules_applied", [])),
                    },
                    response_text=None,
                    delta=result.delta_draft,
                    delta_source="resolver_proposed",
                    provenance=provenance,
                    human_confirmed=False,
                    facts_used=tuple(str(item) for item in result.interpretation.get("facts_used", [])),
                    narrative_claims=(),
                    turn_contract=turn_contract,
                ).to_dict()
            with connect(self.campaign) as conn:
                interpretation = redact_runtime_value_for_view(conn, interpretation, view)
                turn_proposal = redact_runtime_value_for_view(conn, turn_proposal, view) if turn_proposal is not None else None
            result = replace(result, interpretation=interpretation, turn_proposal=turn_proposal)
            with connect(self.campaign) as conn:
                return redact_preview_result_for_view(conn, result, view)
        result = PreviewActionResult(
            campaign_id=self.campaign.campaign_id,
            action="act",
            ok=False,
            status="needs_confirmation",
            ready_to_save=False,
            markdown=render_intent_plan_markdown(intent),
            player_message=intent.player_message or "这是复合行动，需要确认拆步后再逐步预演和保存。",
            interpretation={
                "intent": intent_data,
                "turn_contract": contract_data,
                "clarification": clarification_data,
                "recommended_next_tool": "confirm_plan",
                "commit_state": "not_saved",
            },
            plan=intent.plan,
            repair_options=intent.repair_options,
            warnings=intent.needs_confirmation,
        )
        with connect(self.campaign) as conn:
            return redact_preview_result_for_view(conn, result, view)

    def act(
        self,
        user_text: str,
        *,
        view: str = "player",
        auto_confirm_low_risk: bool = False,
        intent_ai: str = "off",
        intent_backend: str = "direct",
        intent_model: str = DEFAULT_AI_MODEL,
        intent_provider: str = DEFAULT_AI_PROVIDER,
        intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        intent_base_url: str = "",
        intent_api_key_env: str = "",
        intent_fallback_backend: str = "off",
        external_intent_candidate: dict[str, Any] | None = None,
        preflight_id: str = "",
        message_id: str = "",
        platform: str = "",
        session_key: str = "",
        source_user_text_hash: str = "",
        preflight_pending_wait_ms: int = 0,
    ) -> PreviewActionResult:
        del auto_confirm_low_risk
        return self.preview_from_text(
            user_text,
            view=view,
            mode="auto",
            intent_ai=intent_ai,
            intent_backend=intent_backend,
            intent_model=intent_model,
            intent_provider=intent_provider,
            intent_timeout=intent_timeout,
            intent_base_url=intent_base_url,
            intent_api_key_env=intent_api_key_env,
            intent_fallback_backend=intent_fallback_backend,
            external_intent_candidate=external_intent_candidate,
            preflight_id=preflight_id,
            message_id=message_id,
            platform=platform,
            session_key=session_key,
            source_user_text_hash=source_user_text_hash,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )

    def validate_delta(
        self,
        delta: dict[str, Any],
        *,
        action: str | None = None,
        action_options: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> DeltaValidationResult:
        with connect(self.campaign) as conn:
            report = run_validation_pipeline(
                self.campaign,
                conn,
                profile="player_turn_commit",
                delta=delta,
                action=action,
                action_options=action_options or {},
                context=context or {},
                state_audit=False,
                registry=self.action_registry,
            )
        errors: list[str] = []
        missing_required: list[str] = []
        for issue in report.errors:
            if issue.startswith("missing: "):
                missing_required.append(issue.removeprefix("missing: "))
            else:
                errors.append(issue)
        with connect(self.campaign) as conn:
            errors = list(redact_runtime_tuple(conn, tuple(errors)))
            warnings = redact_runtime_tuple(conn, tuple(report.warnings))
            missing_required = list(redact_runtime_tuple(conn, tuple(missing_required)))
        return DeltaValidationResult(
            campaign_id=self.campaign.campaign_id,
            ok=not errors and not missing_required,
            errors=tuple(errors),
            warnings=warnings,
            missing_required=tuple(missing_required),
        )

    def commit_turn(
        self,
        delta: dict[str, Any],
        *,
        turn_proposal: dict[str, Any] | TurnProposal | None = None,
        backup: bool = True,
        action: str | None = None,
        action_options: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        archivist_suggest: bool = False,
        archivist_ai: str = "off",
        archivist_provider: str = DEFAULT_AI_PROVIDER,
        archivist_model: str = DEFAULT_AI_MODEL,
        archivist_timeout: int = DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
        archivist_enqueue: bool = True,
        state_audit: bool = DEFAULT_STATE_AUDIT_ENABLED,
        state_audit_ai: str = DEFAULT_STATE_AUDIT_AI,
        state_audit_provider: str = DEFAULT_AI_PROVIDER,
        state_audit_model: str = DEFAULT_AI_MODEL,
        state_audit_timeout: int = DEFAULT_STATE_AUDIT_TIMEOUT_SECONDS,
        state_audit_block: bool = True,
    ) -> CommitTurnResult:
        proposal = normalize_turn_proposal(turn_proposal)
        if proposal is not None and proposal.delta != delta:
            raise ValueError("TurnProposal delta does not match commit delta")
        with connect(self.campaign) as conn:
            validation_report = run_validation_pipeline(
                self.campaign,
                conn,
                profile="player_turn_commit",
                delta=delta,
                proposal=proposal,
                action=action,
                action_options=action_options or {},
                context=context or {},
                state_audit=state_audit,
                state_audit_ai=state_audit_ai,
                state_audit_provider=state_audit_provider,
                state_audit_model=state_audit_model,
                state_audit_timeout=state_audit_timeout,
                state_audit_block=state_audit_block,
                registry=self.action_registry,
            )
            if not validation_report.ok:
                audit_stage = validation_report.stage("state_audit")
                if audit_stage and audit_stage.status == "blocked":
                    issues = redact_runtime_tuple(conn, tuple(audit_stage.issues))
                    raise ValueError(
                        "State audit blocked turn delta:\n"
                        + "\n".join(f"- {message}" for message in issues)
                    )
                errors = redact_runtime_tuple(conn, tuple(validation_report.errors))
                raise ValueError(
                    "Invalid turn delta:\n"
                    + "\n".join(f"- {error}" for error in errors)
                )
            if proposal is None:
                raise ValueError("player_turn_commit requires an approved TurnProposal validation")
            result = commit_turn_proposal(
                self.campaign,
                conn,
                proposal=proposal,
                validation=validation_report,
                backup=backup,
                backup_reason="pre_commit_turn",
                archivist_suggest=archivist_suggest,
                archivist_ai=archivist_ai,
                archivist_provider=archivist_provider,
                archivist_model=archivist_model,
                archivist_timeout=archivist_timeout,
                archivist_enqueue=archivist_enqueue,
                run_post_check=True,
            )
        return CommitTurnResult(
            campaign_id=self.campaign.campaign_id,
            profile=result.profile,
            turn_id=result.turn_id,
            write_status=result.write_status,
            projection_status=result.projection_status,
            backup_id=result.backup_id,
            snapshot_path=result.snapshot_path,
            snapshot_json_path=result.snapshot_json_path,
            cards_count=result.cards_count,
            archivist_suggestion_id=result.archivist_suggestion_id,
            archivist_proposal_ids=result.archivist_proposal_ids,
            archivist_ai_status=result.archivist_ai_status,
            state_audit=result.state_audit,
            check_errors=result.check_errors,
            validation_report=result.validation_report.to_dict() if result.validation_report else None,
            projection_report=result.projection_report.to_dict() if result.projection_report else None,
        )

    def health(self) -> HealthResult:
        with connect(self.campaign) as conn:
            errors = tuple(run_checks(conn))
        return HealthResult(
            campaign_id=self.campaign.campaign_id,
            ok=not errors,
            errors=errors,
        )

    def ux_metrics(self) -> UxMetricsResult:
        with connect(self.campaign) as conn:
            meta = {row["key"]: row["value"] for row in conn.execute("select key, value from meta")}
            rows = conn.execute(
                "select intent, count(*) as count from turns group by intent order by count desc, intent"
            ).fetchall()
            recent = conn.execute("select intent from turns order by created_at desc, id desc limit 8").fetchall()
            scene = render_scene(conn, view="player")
            current_location_id = str(redact_runtime_value(conn, meta.get("current_location_id", "")))
        affordance_count = sum(1 for line in scene.splitlines() if line.startswith("| ") and " | " in line) - 2
        notes = []
        if affordance_count <= 0:
            notes.append("scene affordance section appears empty")
        return UxMetricsResult(
            campaign_id=self.campaign.campaign_id,
            current_turn_id=str(meta.get("current_turn_id", "")),
            current_location_id=current_location_id,
            total_turns=sum(int(row["count"]) for row in rows),
            turns_by_intent={str(row["intent"]): int(row["count"]) for row in rows},
            recent_intents=tuple(str(row["intent"]) for row in recent),
            scene_affordance_count=max(affordance_count, 0),
            notes=tuple(notes),
        )

    def declared_capabilities(self) -> set[str]:
        raw = self.campaign.config.get("capabilities", [])
        if not isinstance(raw, list):
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    def supports_capability(self, capability: str) -> bool:
        return capability in self.declared_capabilities()

    def require_capability(self, capability: str) -> None:
        if not self.supports_capability(capability):
            raise ValueError(f"unsupported capability: {capability}")

    def capability_for_action(self, action: str | None) -> str | None:
        return capability_for_action(action)

    def capability_error_for_action(self, action: str) -> str | None:
        capability = self.capability_for_action(action)
        if capability is None:
            return None
        if self.supports_capability(capability):
            return None
        return f"unsupported capability: {capability}"

    def capability_errors_for_delta(self, delta: dict[str, Any], action: str | None) -> list[str]:
        required: set[str] = set()
        action_capability = self.capability_for_action(action)
        if action_capability:
            required.add(action_capability)
        intent = str(delta.get("intent", "")).strip()
        if intent in ACTION_CAPABILITIES:
            required.add(ACTION_CAPABILITIES[intent])
        elif intent in CAPABILITY_INTENTS:
            required.add(intent)
        if delta.get("tick_clocks"):
            required.add("clock")
        if not required:
            return []
        declared = self.declared_capabilities()
        return [f"unsupported capability: {capability}" for capability in sorted(required) if capability not in declared]

    def action_from_delta(self, delta: dict[str, Any]) -> str | None:
        intent = str(delta.get("intent", "")).strip()
        if intent in self.action_registry.names():
            return intent
        return None

    def effective_action_options(
        self,
        action: str,
        delta: dict[str, Any],
        explicit_options: dict[str, Any] | None,
    ) -> dict[str, Any]:
        options = self.action_options_from_delta(action, delta)
        for key, value in (explicit_options or {}).items():
            if value is not None:
                options[str(key)] = value
        return options

    def action_options_from_delta(self, action: str, delta: dict[str, Any]) -> dict[str, Any]:
        payloads = event_payloads(delta)
        options: dict[str, Any] = {}
        if action == "travel":
            put_first(options, "palette_id", payloads, ("palette_id",))
            put_first(options, "destination", payloads, ("to_location_id", "destination_id"))
            if not options.get("destination"):
                options["destination"] = delta.get("location_after")
            put_first(options, "pace", payloads, ("pace",))
        elif action == "social":
            put_first(options, "palette_id", payloads, ("palette_id",))
            put_first(options, "npc", payloads, ("npc_id", "npc", "target_id"))
            put_first(options, "topic", payloads, ("topic",))
            put_first(options, "approach", payloads, ("approach",))
        elif action == "gather":
            put_first(options, "palette_id", payloads, ("palette_id",))
            put_first(options, "target", payloads, ("target_id", "target", "resource_id", "crop_entity_id"))
            put_first(options, "location", payloads, ("location_id", "from_location_id"))
        elif action == "craft":
            put_first(options, "palette_id", payloads, ("palette_id",))
            put_first(options, "project", payloads, ("project_id",))
            put_first(options, "target", payloads, ("target_id", "target_name", "recipe_output"))
            put_first(options, "time_cost", payloads, ("time_cost",))
            materials = material_terms_from_payloads(payloads)
            if materials:
                options["materials"] = materials
        elif action == "combat":
            put_first(options, "target", payloads, ("target_id",))
            put_first(options, "weapon", payloads, ("weapon_id",))
            put_first(options, "ammo", payloads, ("ammo_id",))
            put_first(options, "distance", payloads, ("distance",))
            put_first(options, "ready_state", payloads, ("ready_state",))
        elif action == "rest":
            after = first_mapping(payloads, "after")
            if after and after.get("time_block"):
                options["until"] = after["time_block"]
            elif nested_meta(delta, "current_time_block"):
                options["until"] = nested_meta(delta, "current_time_block")
        elif action == "routine":
            put_first(options, "task", payloads, ("task",))
            put_first(options, "target", payloads, ("target_id",))
            put_first(options, "focus", payloads, ("focus",))
            put_first(options, "time_cost", payloads, ("time_cost",))
        elif action == "explore":
            put_first(options, "palette_id", payloads, ("palette_id",))
            put_first(options, "target", payloads, ("target_id", "target_query"))
            put_first(options, "approach", payloads, ("approach",))
            if any(payload.get("target_kind") == "unknown_lead" for payload in payloads):
                options["unknown_lead"] = True
        return options


def event_payloads(delta: dict[str, Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    events = delta.get("events", [])
    if not isinstance(events, list):
        return payloads
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def put_first(
    target: dict[str, Any],
    option_name: str,
    payloads: list[dict[str, Any]],
    keys: tuple[str, ...],
) -> None:
    if target.get(option_name) is not None:
        return
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if value is not None and value != "":
                target[option_name] = value
                return


def first_mapping(payloads: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for payload in payloads:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def nested_meta(delta: dict[str, Any], key: str) -> Any:
    meta = delta.get("meta", {})
    if isinstance(meta, dict):
        return meta.get(key)
    return None


def material_terms_from_payloads(payloads: list[dict[str, Any]]) -> str:
    terms: list[str] = []
    for payload in payloads:
        materials = payload.get("materials")
        if not isinstance(materials, list):
            continue
        for item in materials:
            if not isinstance(item, dict):
                continue
            value = item.get("entity_id") or item.get("query")
            if value is not None and value != "":
                terms.append(str(value))
    return ", ".join(dict.fromkeys(terms))
