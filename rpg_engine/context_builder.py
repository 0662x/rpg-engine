from __future__ import annotations

import json
import sqlite3
from copy import copy
from dataclasses import dataclass, field
from typing import Any

from .campaign import Campaign
from .ai.policy import normalize_timeout
from .context.collectors import (
    DEFAULT_CONTEXT_COLLECTORS,
    build_collector_sections,
    collect_loaded_items,
    collect_omitted_items,
    freeze_unstable_memory_context,
    memory_derived_plot_signal,
    memory_context_snapshot_is_current,
    plot_signals_section,
    run_context_collectors,
)
from .context.budget import context_budget_policy
from .context.diagnostics import (
    build_budget_evidence,
    build_quality_diagnostics,
    high_value_missing_signals,
)
from .context.pipeline import ContextPipeline, ContextPipelineStep
from .context.procedure import render_required_procedure, render_template_text
from .context.rendering import (
    render_ambiguous_candidates,
    render_player_state,
    render_relevant_entities,
)
from .context.resolution import (
    EntityHit,
    collect_entity_hits,
    expand_related_entities,
    is_direct_hit,
)
from .context.semantic import collect_semantic_suggestion
from .context.sections import ContextSection, apply_budget, estimate_tokens
from .context.validation import validate_context
from .context_audit import write_context_audit
from .db import get_meta
from .intent_router import (
    ActionIntent,
    IntentAIConfig,
    IntentRequestMeta,
    action_intent_to_dict,
    make_intent_ai_config,
    make_intent_request_meta,
    route_intent,
    turn_contract_for_intent,
    turn_contract_to_dict,
)
from .memory import player_safe_memory_reason, safe_memory_summary_id
from .redaction import redact_hidden_entity_id_substrings, redact_hidden_entity_refs
from .render import render_scene
from .visibility import can_read_hidden, context_visibility_view, normalize_visibility_view
from .actions import ActionResolverRegistry, get_default_action_registry
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_INTENT_TIMEOUT_SECONDS, DEFAULT_SEMANTIC_TIMEOUT_SECONDS


COLLECTOR_SECTION_ALIASES = {
    "palettes": {"palette_candidates"},
}

SOURCE_SECTION_ALIASES = {
    "world_settings": {"world_settings_core"},
}

REQUIRED_SECTION_ALIASES = {
    "world_settings": {"world_settings_core"},
}


@dataclass
class ContextBuildResult:
    contract: dict[str, Any]
    scope: dict[str, Any]
    request: dict[str, Any]
    budget: dict[str, Any]
    completeness: dict[str, Any]
    loaded_items: list[dict[str, Any]]
    omitted_items: list[dict[str, Any]]
    sections: dict[str, str]
    markdown: str

    def to_json_text(self) -> str:
        data = {
            "contract": self.contract,
            "scope": self.scope,
            "request": self.request,
            "budget": self.budget,
            "completeness": self.completeness,
            "loaded_items": self.loaded_items,
            "omitted_items": self.omitted_items,
            "sections": self.sections,
            "markdown": self.markdown,
        }
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


@dataclass
class BuildState:
    campaign: Campaign
    conn: sqlite3.Connection
    user_text: str
    mode_arg: str
    submode_arg: str | None
    requested_budget: int | None
    campaign_budget: int
    budget_limit: int
    max_events: int
    max_depth: int
    include_palettes: str
    debug: bool
    semantic_ai: str
    semantic_model: str
    semantic_provider: str
    semantic_timeout: int
    intent_config: IntentAIConfig
    request_meta: IntentRequestMeta
    intent_ai: str
    intent_backend: str
    intent_model: str
    intent_provider: str
    intent_timeout: int
    intent_base_url: str
    intent_api_key_env: str
    intent_fallback_backend: str
    action_registry: ActionResolverRegistry
    external_intent_candidate: dict[str, Any] | None = None
    preflight_id: str = ""
    message_id: str = ""
    platform: str = ""
    session_key: str = ""
    source_user_text_hash: str = ""
    preflight_pending_wait_ms: int = 0
    budget_policy_profile: str = "initial"
    budget_policy_reason: str = "initial"
    preserve_palette_candidates: bool = False
    mode: str = "query"
    submode: str = "entity"
    will_advance_time: bool = False
    must_save: bool = False
    requires_preview: bool = False
    required_template: str = "entity_query.md"
    visibility_view: str | None = None
    entity_hits: list[EntityHit] = field(default_factory=list)
    ambiguous_hits: list[EntityHit] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    needs_user_confirmation: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    routes: list[sqlite3.Row] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    relationship_omissions: list[dict[str, Any]] = field(default_factory=list)
    progress_context: list[dict[str, Any]] = field(default_factory=list)
    progress_omissions: list[dict[str, Any]] = field(default_factory=list)
    plot_signals: list[dict[str, Any]] = field(default_factory=list)
    plot_signal_omissions: list[dict[str, Any]] = field(default_factory=list)
    palette_lines: list[str] = field(default_factory=list)
    palette_candidates: list[dict[str, Any]] = field(default_factory=list)
    discovery_states: list[sqlite3.Row] = field(default_factory=list)
    world_settings: list[dict[str, Any]] = field(default_factory=list)
    related_events: list[sqlite3.Row] = field(default_factory=list)
    general_events: list[sqlite3.Row] = field(default_factory=list)
    memory_summaries: list[sqlite3.Row] = field(default_factory=list)
    memory_omissions: list[dict[str, Any]] = field(default_factory=list)
    memory_projection_snapshot: tuple[str, str, str, str] | None = None
    memory_context_revision: int = 0
    memory_context_frozen: bool = False
    semantic_suggestion: dict[str, Any] | None = None
    semantic_error: str | None = None
    semantic_audit: dict[str, Any] | None = None
    semantic_alias_gaps: list[dict[str, Any]] = field(default_factory=list)
    intent: ActionIntent | None = None

    def direct_non_context_hits(self) -> list[EntityHit]:
        current_location_id = get_meta(self.conn).get("current_location_id")
        return [
            hit
            for hit in self.entity_hits
            if is_direct_hit(hit)
            and hit.id not in {current_location_id, self.campaign.player_entity_id}
        ]


def build_context(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    user_text: str,
    mode: str = "auto",
    submode: str | None = None,
    budget: int | None = None,
    output_format: str = "markdown",
    max_events: int = 6,
    max_depth: int = 1,
    include_palettes: str = "auto",
    view: str | None = None,
    debug: bool = False,
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
    audit_context_run_id: str | None = None,
    registry: ActionResolverRegistry | None = None,
) -> ContextBuildResult:
    del output_format
    campaign_budget = int(campaign.context_budget or 2500)
    budget_limit = max(500, int(budget if budget is not None else campaign.context_budget or 2500))
    max_events_value = max(0, int(max_events))
    max_depth_value = max(0, int(max_depth))
    semantic_timeout_value = normalize_timeout(semantic_timeout)
    intent_timeout_value = normalize_timeout(intent_timeout)
    intent_base_url_value = str(intent_base_url or "")
    intent_api_key_env_value = str(intent_api_key_env or "")
    intent_fallback_backend_value = str(intent_fallback_backend or "off")
    preflight_id_value = str(preflight_id or "")
    message_id_value = str(message_id or "")
    platform_value = str(platform or "")
    session_key_value = str(session_key or "")
    source_user_text_hash_value = str(source_user_text_hash or "")
    preflight_pending_wait_ms_value = max(0, int(preflight_pending_wait_ms))
    intent_config = make_intent_ai_config(
        intent_ai=intent_ai,
        intent_backend=intent_backend,
        intent_provider=intent_provider,
        intent_model=intent_model,
        intent_timeout=intent_timeout_value,
        intent_base_url=intent_base_url_value,
        intent_api_key_env=intent_api_key_env_value,
        intent_fallback_backend=intent_fallback_backend_value,
    )
    action_registry = registry if registry is not None else get_default_action_registry()
    request_meta = make_intent_request_meta(
        preflight_id=preflight_id_value,
        message_id=message_id_value,
        platform=platform_value,
        session_key=session_key_value,
        source_user_text_hash=source_user_text_hash_value,
        preflight_pending_wait_ms=preflight_pending_wait_ms_value,
    )
    state = BuildState(
        campaign=campaign,
        conn=conn,
        user_text=user_text.strip(),
        mode_arg=mode,
        submode_arg=submode,
        requested_budget=budget,
        campaign_budget=campaign_budget,
        budget_limit=budget_limit,
        max_events=max_events_value,
        max_depth=max_depth_value,
        include_palettes=include_palettes,
        visibility_view=normalize_visibility_view(view) if view is not None else None,
        debug=debug,
        semantic_ai=semantic_ai,
        semantic_model=semantic_model,
        semantic_provider=semantic_provider,
        semantic_timeout=semantic_timeout_value,
        intent_config=intent_config,
        request_meta=request_meta,
        intent_ai=intent_ai,
        intent_backend=intent_backend,
        intent_model=intent_model,
        intent_provider=intent_provider,
        intent_timeout=intent_timeout_value,
        intent_base_url=intent_base_url_value,
        intent_api_key_env=intent_api_key_env_value,
        intent_fallback_backend=intent_fallback_backend_value,
        action_registry=action_registry,
        external_intent_candidate=external_intent_candidate,
        preflight_id=preflight_id_value,
        message_id=message_id_value,
        platform=platform_value,
        session_key=session_key_value,
        source_user_text_hash=source_user_text_hash_value,
        preflight_pending_wait_ms=preflight_pending_wait_ms_value,
    )
    return default_context_pipeline().run(
        state,
        audit_context=audit_context,
        audit_context_run_id=audit_context_run_id,
    )


def default_context_pipeline() -> ContextPipeline:
    return ContextPipeline(
        steps=[
            ContextPipelineStep("classify_request", classify_request),
            ContextPipelineStep("collect_entity_hits", collect_entity_hits),
            ContextPipelineStep("collect_semantic_suggestion", collect_semantic_suggestion),
            ContextPipelineStep("apply_semantic_request_decision", apply_semantic_request_decision),
            ContextPipelineStep("expand_related_entities", expand_related_entities),
            ContextPipelineStep("run_context_collectors", run_registered_context_collectors),
            ContextPipelineStep("validate_context", validate_context),
        ],
        render_result=render_context_result,
        audit_result=write_context_audit_result,
    )


def context_state_visibility_view(state: BuildState) -> str:
    return getattr(state, "visibility_view", None) or context_visibility_view(state.mode)


def run_registered_context_collectors(state: BuildState) -> None:
    run_context_collectors(state, DEFAULT_CONTEXT_COLLECTORS)


def write_context_audit_result(
    state: BuildState,
    result: ContextBuildResult,
    run_id: str | None,
) -> str:
    return write_context_audit(state.conn, result, run_id=run_id)


def classify_request(state: BuildState) -> None:
    intent = route_intent(
        state.campaign,
        state.conn,
        state.user_text,
        mode=state.mode_arg,
        submode=state.submode_arg,
        semantic_ai=state.semantic_ai,
        semantic_provider=state.semantic_provider,
        semantic_model=state.semantic_model,
        semantic_timeout=state.semantic_timeout,
        intent_ai=state.intent_config.mode,
        intent_backend=state.intent_config.backend,
        intent_provider=state.intent_config.provider,
        intent_model=state.intent_config.model,
        intent_timeout=state.intent_config.timeout,
        intent_base_url=state.intent_config.base_url,
        intent_api_key_env=state.intent_config.api_key_env,
        intent_fallback_backend=state.intent_config.fallback_backend,
        external_intent_candidate=state.external_intent_candidate,
        preflight_id=state.request_meta.preflight_id,
        message_id=state.request_meta.message_id,
        platform=state.request_meta.platform,
        session_key=state.request_meta.session_key,
        source_user_text_hash=state.request_meta.source_user_text_hash,
        preflight_pending_wait_ms=state.request_meta.preflight_pending_wait_ms,
        view=classification_visibility_view(state),
        registry=state.action_registry,
    )
    apply_intent_classification(state, intent)


def classification_visibility_view(state: BuildState) -> str:
    return state.visibility_view or context_visibility_view(state.mode_arg)


def apply_intent_classification(state: BuildState, intent: ActionIntent) -> None:
    state.intent = intent
    set_request_classification(state, intent.mode, intent.submode)
    if intent.status == "blocked":
        state.will_advance_time = False
        state.must_save = False
        state.requires_preview = False
    state.missing_required = list(intent.missing_required)
    state.needs_user_confirmation = list(intent.needs_confirmation)
    for assumption in intent.decision_trace.get("overrides", []):
        if assumption not in state.assumptions:
            state.assumptions.append(str(assumption))


def set_request_classification(state: BuildState, mode: str, submode: str) -> None:
    action_names = set(state.action_registry.names())
    state.mode = mode
    state.submode = submode
    state.will_advance_time = mode == "action"
    state.must_save = mode == "action"
    state.requires_preview = mode == "action" and submode in action_names
    state.required_template = template_for(mode, submode, registry=state.action_registry)
    decision = context_budget_policy(
        mode=state.mode,
        submode=state.submode,
        campaign_default=state.campaign_budget,
        explicit_budget=state.requested_budget,
    )
    state.budget_limit = decision.limit
    state.budget_policy_profile = decision.profile
    state.budget_policy_reason = decision.reason
    state.preserve_palette_candidates = decision.preserve_palette_candidates


def apply_semantic_request_decision(state: BuildState) -> None:
    suggestion = state.semantic_suggestion or {}
    if not suggestion:
        return

    confidence = str(suggestion.get("confidence") or "").strip().lower()
    if confidence != "high":
        return

    decision = semantic_request_decision(
        suggestion,
        registry=getattr(state, "action_registry", None),
    )
    if decision is None:
        return
    semantic_mode, semantic_submode = decision
    if (state.mode, state.submode) != (semantic_mode, semantic_submode):
        note = f"AI 语义判断仅记录，不覆盖最终路由：`{state.mode}:{state.submode}` vs `{semantic_mode}:{semantic_submode}`。"
        if note not in state.assumptions:
            state.assumptions.append(note)


def semantic_request_decision(
    suggestion: dict[str, Any],
    *,
    registry: ActionResolverRegistry | None = None,
) -> tuple[str, str] | None:
    mode = str(suggestion.get("mode") or "").strip().lower()
    submode = str(suggestion.get("submode") or "").strip().lower()
    action_names = set((registry if registry is not None else get_default_action_registry()).names())

    if mode == "action" and submode in action_names:
        return mode, submode
    if mode == "query" and submode in {"entity", "scene", "context"}:
        return mode, submode
    return None


def template_for(
    mode: str,
    submode: str,
    *,
    registry: ActionResolverRegistry | None = None,
) -> str:
    if mode == "query":
        if submode == "scene":
            return "scene_entry.md"
        return "entity_query.md"
    action_registry = registry if registry is not None else get_default_action_registry()
    spec = action_registry.get(submode)
    return spec.response_template if spec else "action_turn.md"


def filter_plot_signals_for_selected_sections(
    state: BuildState,
    selected: list[ContextSection],
    omitted_sections: list[ContextSection],
    selected_section_keys: set[str],
) -> None:
    if not getattr(state, "plot_signals", None):
        return
    kept: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    budget_omitted_section_keys = {
        section.key
        for section in omitted_sections
        if section.omitted_reason == "token budget"
    }
    for signal in state.plot_signals:
        required = {
            str(value)
            for value in signal.get("required_section_keys", [])
            if str(value).strip()
        }
        missing_required = missing_required_section_keys(required, selected_section_keys)
        if missing_required:
            reason_code = (
                "over_budget"
                if set(missing_required).issubset(budget_omitted_section_keys)
                else "unavailable"
            )
            reason = (
                "plot signal omitted because source section was omitted by token budget"
                if reason_code == "over_budget"
                else "plot signal omitted because a required source section is unavailable"
            )
            budget_reason = (
                "source section omitted by token budget"
                if reason_code == "over_budget"
                else "required source section unavailable"
            )
            evidence = dict(signal)
            evidence.update(
                {
                    "reason": reason,
                    "reason_code": reason_code,
                }
            )
            evidence.pop("detail_text", None)
            budget = dict(evidence.get("budget") or {})
            budget.update(
                {
                    "included": False,
                    "reason": budget_reason,
                    "reason_code": reason_code,
                    "required_sections": sorted(required),
                    "selected_sections": sorted(selected_section_keys),
                    "missing_required_sections": missing_required,
                }
            )
            evidence["budget"] = budget
            omitted.append(evidence)
        else:
            kept.append(signal)
    if len(kept) == len(state.plot_signals):
        return
    state.plot_signals = kept
    state.plot_signal_omissions.extend(omitted)
    for section in selected:
        if section.key != "plot_signals":
            continue
        replacement = plot_signals_section(state)
        if replacement is None:
            section.omitted_reason = (
                "source section omitted by token budget"
                if omitted
                and all(item.get("reason_code") == "over_budget" for item in omitted)
                else "required source section unavailable"
            )
            selected[:] = [item for item in selected if item.key != "plot_signals"]
            omitted_sections.append(section)
            selected_section_keys.discard("plot_signals")
        else:
            section.content = replacement.content
            section.estimated_tokens = estimate_tokens(section.content)
        break


def render_context_result(state: BuildState) -> ContextBuildResult:
    for _ in range(2):
        revision = state.memory_context_revision
        render_state = context_render_state_copy(state)
        result = _render_context_result_once(render_state)
        render_changed = render_state.memory_context_revision != revision
        if render_changed:
            reconcile_render_memory_state(state, render_state)
        snapshot_current = memory_context_snapshot_is_current(state)
        if not render_changed and snapshot_current:
            return result
    freeze_unstable_memory_context(state)
    return _render_context_result_once(context_render_state_copy(state))


def context_render_state_copy(state: BuildState) -> BuildState:
    render_state = copy(state)
    render_state.plot_signals = list(state.plot_signals)
    render_state.plot_signal_omissions = list(state.plot_signal_omissions)
    render_state.memory_summaries = list(state.memory_summaries)
    render_state.memory_omissions = list(state.memory_omissions)
    return render_state


def reconcile_render_memory_state(
    state: BuildState,
    render_state: BuildState,
) -> None:
    state.memory_summaries = list(render_state.memory_summaries)
    state.memory_omissions = list(render_state.memory_omissions)
    state.memory_projection_snapshot = render_state.memory_projection_snapshot
    state.memory_context_revision = render_state.memory_context_revision
    state.plot_signals = [
        signal
        for signal in state.plot_signals
        if not memory_derived_plot_signal(signal)
    ]
    state.plot_signal_omissions = [
        signal
        for signal in state.plot_signal_omissions
        if not memory_derived_plot_signal(signal)
    ]


def _render_context_result_once(state: BuildState) -> ContextBuildResult:
    sections = build_sections(state)
    selected, omitted = apply_budget(sections, state.budget_limit)
    selected_section_keys = {section.key for section in selected}
    filter_plot_signals_for_selected_sections(
        state,
        selected,
        omitted,
        selected_section_keys,
    )
    intent_blocked = bool(
        state.intent
        and (
            state.intent.status == "blocked"
            or state.intent.errors
        )
    )
    confidence = "低" if state.missing_required or state.needs_user_confirmation or intent_blocked else "高"
    allow_proceed = not state.missing_required and not state.needs_user_confirmation and not intent_blocked
    clarification = state.intent.clarification.to_dict() if state.intent and state.intent.clarification else None
    context_view = context_state_visibility_view(state)
    should_redact = not can_read_hidden(context_view)

    semantic_suggestion = state.semantic_suggestion
    semantic_alias_gaps = state.semantic_alias_gaps
    semantic_error = state.semantic_error
    semantic_audit = state.semantic_audit
    contract = context_contract_metadata(state, context_view)
    scope = context_scope_metadata(state, context_view)
    if should_redact:
        semantic_suggestion = redact_player_context_value(state.conn, semantic_suggestion)
        semantic_alias_gaps = redact_player_context_value(state.conn, semantic_alias_gaps)
        semantic_error = (
            str(redact_player_context_value(state.conn, semantic_error))
            if semantic_error
            else None
        )
        semantic_audit = redact_player_context_value(state.conn, semantic_audit)
    request = {
        "user_text": state.user_text,
        "mode": state.mode,
        "submode": state.submode,
        "action": state.intent.action if state.intent else None,
        "intent": action_intent_to_dict(state.intent),
        "clarification": clarification,
        "turn_contract": turn_contract_to_dict(
            turn_contract_for_intent(state.intent, registry=state.action_registry)
        )
        if state.intent
        else None,
        "decision_trace": state.intent.decision_trace if state.intent else {},
        "visibility_view": context_view,
        "will_advance_time": state.will_advance_time,
        "must_save": state.must_save,
        "requires_preview": state.requires_preview,
        "required_template": state.required_template,
        "semantic_ai": {
            "enabled": state.semantic_ai != "off",
            "backend": state.semantic_ai,
            "provider": state.semantic_provider,
            "model": state.semantic_model,
            "status": semantic_status(state),
            "suggestion": semantic_suggestion,
            "alias_gaps": semantic_alias_gaps,
            "error": semantic_error,
            "audit": semantic_audit,
        },
        "intent_ai": {
            "enabled": state.intent_ai != "off",
            "mode": state.intent_ai,
            "backend": state.intent_backend,
            "provider": state.intent_provider,
            "model": state.intent_model,
            "timeout": state.intent_timeout,
            "base_url": state.intent_base_url,
            "api_key_env": state.intent_api_key_env,
            "fallback_backend": state.intent_fallback_backend,
            "preflight_id": state.preflight_id,
            "message_id": state.message_id,
            "platform": state.platform,
            "session_key": state.session_key,
            "source_user_text_hash": state.source_user_text_hash,
            "preflight_pending_wait_ms": state.preflight_pending_wait_ms,
            "external_candidate": state.intent.decision_trace.get("intent_ai", {}).get("external_candidate")
            if state.intent
            else None,
            "decision": state.intent.decision_trace.get("intent_ai", {}).get("decision") if state.intent else None,
        },
    }
    omitted_section_keys = {section.key for section in omitted}
    loaded_items = [section_item_evidence(section, context_view, included=True) for section in selected]
    loaded_items.extend(
        [
        {
            "id": hit.id,
            "kind": hit.type,
            "name": hit.name,
            "reason": hit.reason,
            "priority": hit.priority,
            "depth": hit.depth,
            "source": "entity_resolution",
            "provenance": {
                "collector": "entity_resolution",
                "source": "collect_entity_hits",
                "match_reason": hit.reason,
            },
            "visibility": item_visibility_evidence(context_view),
            "budget": {
                "included": True,
                "behavior": "entity hits are item evidence; rendered sections remain token-budgeted",
                "priority": hit.priority,
                "estimated_tokens": None,
            },
        }
        for hit in state.entity_hits
        ]
    )
    omitted_items = [section_item_evidence(section, context_view, included=False) for section in omitted]
    omitted_items.extend(collect_omitted_items(state, DEFAULT_CONTEXT_COLLECTORS))
    for item in collect_loaded_items(state, DEFAULT_CONTEXT_COLLECTORS):
        if collector_item_omitted_by_budget(item, selected_section_keys):
            omitted_items.append(
                collector_item_omission_evidence(
                    item,
                    selected_section_keys=selected_section_keys,
                    omitted_section_keys=omitted_section_keys,
                )
            )
        else:
            loaded_items.append(item)
    omitted_items.append(
        {
            "id": "archive_v1/journal.md",
            "kind": "archive",
            "reason": "forbidden by default",
            "priority": 0,
            "estimated_tokens": None,
            "depth": None,
            "source": "default_policy",
            "provenance": {
                "policy": "archive_forbidden_by_default",
                "source": "render_context_result",
            },
            "visibility": item_visibility_evidence(context_view),
            "budget": {
                "included": False,
                "behavior": "default forbidden source, not token budget",
                "priority": 0,
                "estimated_tokens": None,
                "reason": "forbidden by default",
            },
        }
    )
    budget = build_budget_evidence(
        sections=sections,
        selected=selected,
        omitted=omitted,
        limit=state.budget_limit,
        requested=state.requested_budget,
        campaign_default=state.campaign_budget,
        policy_profile=state.budget_policy_profile,
        policy_reason=state.budget_policy_reason,
    )
    completeness = {
        "confidence": confidence,
        "allow_proceed": allow_proceed,
        "missing_required": state.missing_required,
        "missing_signal_evidence": [
            *missing_signal_evidence(state),
            *high_value_missing_signals(
                budget=budget,
                omitted_items=omitted_items,
            ),
        ],
        "quality_diagnostics": build_quality_diagnostics(
            state=state,
            budget=budget,
            loaded_items=loaded_items,
            omitted_items=omitted_items,
            context_view=context_view,
        ),
        "needs_user_confirmation": state.needs_user_confirmation,
        "clarification": clarification,
        "assumptions": state.assumptions,
    }
    if should_redact:
        contract = redact_player_context_value(state.conn, contract)
        scope = redact_player_context_value(state.conn, scope)
        request = redact_player_context_value(state.conn, request)
        completeness = redact_player_context_value(state.conn, completeness)
        loaded_items = redact_player_context_value(state.conn, loaded_items)
        omitted_items = redact_player_context_value(state.conn, omitted_items)
    section_texts = {section.key: section.content for section in selected}
    markdown = render_markdown(state, request, completeness, budget, selected, omitted, loaded_items, omitted_items)
    if should_redact:
        section_texts = redact_player_context_value(state.conn, section_texts)
        markdown = str(redact_player_context_value(state.conn, markdown))
    return ContextBuildResult(
        contract=contract,
        scope=scope,
        request=request,
        budget=budget,
        completeness=completeness,
        loaded_items=loaded_items,
        omitted_items=omitted_items,
        sections=section_texts,
        markdown=markdown,
    )


def redact_player_context_value(conn: sqlite3.Connection, value: Any) -> Any:
    redacted = redact_hidden_entity_refs(conn, value, drop_empty=False)
    return redact_hidden_entity_id_substrings(conn, redacted, drop_empty=False)


def context_contract_metadata(state: BuildState, context_view: str) -> dict[str, Any]:
    return {
        "id": "ContextBuildResult",
        "version": "1.0",
        "visibility_mode": context_view,
        "audit_tables": ["context_runs", "context_items"],
        "rendering_source": "ContextBuildResult",
        "pipeline_steps": [step.name for step in default_context_pipeline().steps],
        "collector_sources": [collector.name for collector in DEFAULT_CONTEXT_COLLECTORS],
        "visibility_invariants": context_visibility_invariants(context_view),
        "authority": {
            "fact_source": "save_sqlite",
            "audit_is_fact_authority": False,
            "ai_advisory_only": state.semantic_ai != "off" or state.intent_ai != "off",
        },
    }


def context_visibility_invariants(context_view: str) -> list[dict[str, Any]]:
    return [
        {
            "source": "events",
            "structured_visibility": "not_applicable",
            "hidden_allowed": can_read_hidden(context_view),
            "policy": "player view omits rows containing hidden entity refs before rendering; events do not carry standalone hidden authority in the current schema",
        },
        {
            "source": "memory_summaries",
            "structured_visibility": "visibility_mode_metadata",
            "hidden_allowed": can_read_hidden(context_view),
            "policy": "player view omits rows containing hidden entity refs before rendering; memory summaries carry visibility_mode and freshness metadata but do not override SQLite facts",
        },
    ]


def context_scope_metadata(state: BuildState, context_view: str) -> dict[str, Any]:
    return {
        "user_text": state.user_text,
        "mode": state.mode,
        "submode": state.submode,
        "visibility_mode": context_view,
        "budget_limit": state.budget_limit,
        "requested_budget": state.requested_budget,
        "max_events": state.max_events,
        "max_depth": state.max_depth,
        "include_palettes": state.include_palettes,
        "semantic_ai": state.semantic_ai,
        "intent_ai": state.intent_ai,
        "source": "build_context",
    }


def item_visibility_evidence(context_view: str) -> dict[str, Any]:
    return {
        "mode": context_view,
        "hidden_allowed": can_read_hidden(context_view),
        "policy": "context_visibility_view",
    }


def missing_signal_evidence(state: BuildState) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    generic_memory_signal_added = False
    for item in state.missing_required:
        evidence.append(
            {
                "signal": str(item),
                "source": "context_validation",
                "severity": "blocking",
            }
        )
    for item in state.needs_user_confirmation:
        evidence.append(
            {
                "signal": str(item),
                "source": "intent_or_context_confirmation",
                "severity": "confirmation",
            }
        )
    for item in getattr(state, "memory_omissions", []):
        reason = str(item.get("stale_reason") or item.get("reason") or "memory summary omitted")
        signal = str(item.get("id") or "memory_summaries")
        if not can_read_hidden(context_state_visibility_view(state)):
            redacted_reason = redact_hidden_entity_refs(state.conn, reason, drop_empty=False) or ""
            redacted_reason = redact_hidden_entity_id_substrings(state.conn, redacted_reason, drop_empty=False) or ""
            requested_reason = str(item.get("player_safe_reason") or redacted_reason)
            requested_reason = redact_hidden_entity_refs(
                state.conn,
                requested_reason,
                drop_empty=False,
            ) or ""
            requested_reason = redact_hidden_entity_id_substrings(
                state.conn,
                requested_reason,
                drop_empty=False,
            ) or ""
            reason = player_safe_memory_reason(requested_reason)
            requested_signal = str(item.get("player_safe_signal") or signal)
            requested_signal = redact_hidden_entity_refs(
                state.conn,
                requested_signal,
                drop_empty=False,
            ) or ""
            requested_signal = redact_hidden_entity_id_substrings(
                state.conn,
                requested_signal,
                drop_empty=False,
            ) or ""
            signal = safe_memory_summary_id(requested_signal) or "memory_summaries"
            if signal == "memory_summaries":
                if generic_memory_signal_added:
                    continue
                generic_memory_signal_added = True
        evidence.append(
            {
                "signal": signal,
                "source": "memory_summaries",
                "severity": "advisory",
                "reason": reason,
                "fallback": "recent_events_or_lower_quality_context",
            }
        )
    return evidence


def section_source_metadata(section: ContextSection) -> dict[str, Any]:
    collectors = {collector.name: collector for collector in DEFAULT_CONTEXT_COLLECTORS}
    collector_name = collector_name_for_section(section.key)
    collector = collectors.get(collector_name)
    if collector:
        return {
            "source": collector.source or collector.name,
            "provenance": {
                "collector": collector.name,
                "source": collector.source or collector.name,
                "detail": collector.provenance,
            },
            "visibility_policy": collector.visibility,
            "budget_behavior": collector.budget_behavior,
        }
    core_sources = {
        "current_scene": {
            "source": "scene_renderer",
            "detail": "render_scene",
            "visibility_policy": "render_scene receives context visibility view",
            "budget_behavior": "required section priority 100",
        },
        "player_state": {
            "source": "player_state_renderer",
            "detail": "render_player_state",
            "visibility_policy": "render_player_state receives context visibility view",
            "budget_behavior": "required section priority 100",
        },
        "relevant_entities": {
            "source": "entity_resolution",
            "detail": "render_relevant_entities from entity hits",
            "visibility_policy": "entity hits are collected and redacted by context visibility view",
            "budget_behavior": "required for entity query or missing required signals, otherwise priority 90",
        },
        "ambiguous_candidates": {
            "source": "entity_resolution",
            "detail": "render_ambiguous_candidates",
            "visibility_policy": "entity candidates are collected under context visibility view",
            "budget_behavior": "required section priority 95",
        },
        "semantic_ai": {
            "source": "semantic_ai",
            "detail": "render_semantic_suggestion",
            "visibility_policy": "semantic suggestions are redacted for player view",
            "budget_behavior": "optional section priority 78",
        },
        "required_procedure": {
            "source": "procedure_template",
            "detail": "render_required_procedure",
            "visibility_policy": "procedure text is selected from route/template metadata",
            "budget_behavior": "required section priority 95",
        },
        "response_template": {
            "source": "response_template",
            "detail": "render_template_text",
            "visibility_policy": "template text is selected from action/query mode",
            "budget_behavior": "optional section priority 65",
        },
    }
    metadata = core_sources.get(
        section.key,
        {
            "source": section.key,
            "detail": "context section",
            "visibility_policy": "inherits context visibility view",
            "budget_behavior": "section priority token budget",
        },
    )
    return {
        "source": metadata["source"],
        "provenance": {
            "section": section.key,
            "source": metadata["source"],
            "detail": metadata["detail"],
        },
        "visibility_policy": metadata["visibility_policy"],
        "budget_behavior": metadata["budget_behavior"],
    }


def section_item_evidence(
    section: ContextSection,
    context_view: str,
    *,
    included: bool,
) -> dict[str, Any]:
    metadata = section_source_metadata(section)
    omission_reason = section.omitted_reason or "token budget"
    reason_code = (
        None
        if included
        else "over_budget"
        if omission_reason in {"token budget", "source section omitted by token budget"}
        else "unavailable"
    )
    return {
        "id": f"section:{section.key}",
        "kind": "section",
        "name": section.title,
        "reason": "selected for context output" if included else omission_reason,
        "reason_code": reason_code,
        "priority": section.priority,
        "depth": None,
        "estimated_tokens": section.estimated_tokens,
        "source": metadata["source"],
        "provenance": metadata["provenance"] | {"section": section.key},
        "visibility": item_visibility_evidence(context_view) | {"policy": metadata["visibility_policy"]},
        "budget": {
            "included": included,
            "behavior": metadata["budget_behavior"],
            "priority": section.priority,
            "estimated_tokens": section.estimated_tokens,
            "reason": None if included else omission_reason,
            "reason_code": reason_code,
        },
    }


def collector_name_for_section(section_key: str) -> str:
    for collector in DEFAULT_CONTEXT_COLLECTORS:
        keys = {collector.name} | COLLECTOR_SECTION_ALIASES.get(collector.name, set())
        if section_key in keys:
            return collector.name
    return section_key


def section_keys_for_context_source(source: str) -> set[str]:
    keys: set[str] = set()
    for collector in DEFAULT_CONTEXT_COLLECTORS:
        collector_source = collector.source or collector.name
        if source in {collector_source, collector.name}:
            keys.add(collector.name)
            keys.update(COLLECTOR_SECTION_ALIASES.get(collector.name, set()))
            keys.update(SOURCE_SECTION_ALIASES.get(collector_source, set()))
    return keys


def collector_item_omitted_by_budget(item: dict[str, Any], selected_section_keys: set[str]) -> bool:
    source = str(item.get("source", ""))
    section_keys = section_keys_for_context_source(source)
    if section_keys and section_keys.isdisjoint(selected_section_keys):
        return True
    required_section_keys = {
        str(value)
        for value in item.get("required_section_keys", [])
        if str(value).strip()
    }
    return bool(missing_required_section_keys(required_section_keys, selected_section_keys))


def missing_required_section_keys(required_section_keys: set[str], selected_section_keys: set[str]) -> list[str]:
    return sorted(
        section_key
        for section_key in required_section_keys
        if not section_requirement_satisfied(section_key, selected_section_keys)
    )


def section_requirement_satisfied(section_key: str, selected_section_keys: set[str]) -> bool:
    if section_key in selected_section_keys:
        return True
    return bool(REQUIRED_SECTION_ALIASES.get(section_key, set()) & selected_section_keys)


def collector_item_omission_evidence(
    item: dict[str, Any],
    *,
    selected_section_keys: set[str],
    omitted_section_keys: set[str],
) -> dict[str, Any]:
    evidence = dict(item)
    if evidence.get("kind") == "plot_signal":
        evidence.pop("detail_text", None)
    section_keys = section_keys_for_context_source(str(evidence.get("source", "")))
    required_section_keys = {
        str(value)
        for value in evidence.get("required_section_keys", [])
        if str(value).strip()
    }
    omitted_sections = sorted(section_keys & omitted_section_keys)
    missing_required_sections = missing_required_section_keys(required_section_keys, selected_section_keys)
    budget = dict(evidence.get("budget") or {})
    budget.update(
        {
            "included": False,
            "reason": "source section omitted by token budget",
            "reason_code": "over_budget",
            "section_keys": sorted(section_keys),
            "selected_sections": sorted(selected_section_keys),
        }
    )
    if omitted_sections:
        budget["omitted_sections"] = omitted_sections
    if required_section_keys:
        budget["required_sections"] = sorted(required_section_keys)
    if missing_required_sections:
        budget["missing_required_sections"] = missing_required_sections
    provenance = dict(evidence.get("provenance") or {})
    provenance["omission_stage"] = "apply_budget"
    evidence.update(
        {
            "reason": "source section omitted by token budget",
            "reason_code": "over_budget",
            "provenance": provenance,
            "budget": budget,
            "estimated_tokens": evidence.get("estimated_tokens"),
            "depth": evidence.get("depth"),
        }
    )
    return evidence


def build_sections(state: BuildState) -> list[ContextSection]:
    context_view = context_state_visibility_view(state)
    sections = [
        ContextSection(
            key="current_scene",
            title="Current Scene",
            content=render_scene(state.conn, view=context_view),
            priority=100,
            required=True,
        ),
        ContextSection(
            key="player_state",
            title="Player State",
            content=render_player_state(state.conn, view=context_view),
            priority=100,
            required=True,
        ),
    ]
    if state.entity_hits:
        sections.append(
            ContextSection(
                key="relevant_entities",
                title="Relevant Entities",
                content=render_relevant_entities(state, view=context_view),
                priority=90,
                required=state.mode == "query" or bool(state.missing_required),
            )
        )
    if state.ambiguous_hits:
        sections.append(
            ContextSection(
                key="ambiguous_candidates",
                title="Ambiguous Candidates",
                content=render_ambiguous_candidates(state),
                priority=95,
                required=True,
            )
        )
    sections.extend(build_collector_sections(state, DEFAULT_CONTEXT_COLLECTORS))
    if state.semantic_ai != "off":
        sections.append(
            ContextSection(
                key="semantic_ai",
                title="Semantic AI Suggestion",
                content=render_semantic_suggestion(state),
                priority=78,
                required=False,
            )
        )
    sections.append(
        ContextSection(
            key="required_procedure",
            title="Required Procedure",
            content=render_required_procedure(state),
            priority=95,
            required=True,
        )
    )
    template_text = render_template_text(state)
    if template_text:
        sections.append(
            ContextSection(
                key="response_template",
                title="Response Template",
                content=template_text,
                priority=65,
                required=False,
            )
        )
    for section in sections:
        section.estimated_tokens = estimate_tokens(section.content)
    return sections


def semantic_status(state: BuildState) -> str:
    if state.semantic_ai == "off":
        return "off"
    if state.semantic_error:
        return "error"
    if state.semantic_suggestion:
        return "ok"
    return "empty"


def render_semantic_suggestion(state: BuildState) -> str:
    lines = [
        "### AI 语义判断",
        "",
        "用于补充意图识别和实体提示；只作为观测信号，不覆盖最终 mode/submode，也不能绕过 resolver、delta schema、state audit 和 commit 门禁。",
        "",
        "| 项目 | 值 |",
        "|------|----|",
        f"| 后端 | {state.semantic_ai} |",
        f"| 模型 | {state.semantic_provider}/{state.semantic_model} |",
        f"| 状态 | {semantic_status(state)} |",
    ]
    if state.semantic_error:
        error = (
            state.semantic_error
            if can_read_hidden(context_state_visibility_view(state))
            else redact_hidden_entity_refs(state.conn, state.semantic_error, drop_empty=False)
        )
        lines.append(f"| 错误 | {error} |")
        return "\n".join(lines)

    suggestion = state.semantic_suggestion or {}
    if not can_read_hidden(context_state_visibility_view(state)):
        suggestion = redact_hidden_entity_refs(state.conn, suggestion, drop_empty=False)
    if not suggestion:
        lines.append("| 结果 | 无 |")
        return "\n".join(lines)

    lines.extend(
        [
            f"| 建议模式 | `{suggestion.get('mode', 'unknown')}:{suggestion.get('submode', 'unknown')}` |",
            f"| 置信度 | {suggestion.get('confidence', 'low')} |",
            f"| 目标 | {join_list(suggestion.get('targets', []))} |",
            f"| 提到实体 | {join_list(suggestion.get('entities_mentioned', []))} |",
            f"| 建议补充 | {join_list(suggestion.get('missing_confirmations', []))} |",
            f"| 备注 | {join_list(suggestion.get('notes', []))} |",
        ]
    )
    semantic_alias_gaps = state.semantic_alias_gaps
    if not can_read_hidden(context_state_visibility_view(state)):
        semantic_alias_gaps = redact_hidden_entity_refs(state.conn, semantic_alias_gaps, drop_empty=False)
    if semantic_alias_gaps:
        lines.extend(["", "#### 别名缺口候选", "", "| 语义目标 | 状态 | 候选 | 建议 |", "|----------|------|------|------|"])
        for gap in semantic_alias_gaps:
            candidates = gap.get("candidates") or []
            candidate_text = "；".join(f"`{item['id']}` {item['name']}" for item in candidates) if candidates else "无"
            lines.append(
                f"| {gap.get('label', '')} | {gap.get('status', '')} | {candidate_text} | {gap.get('suggestion', '')} |"
            )
    return "\n".join(lines)


def render_markdown(
    state: BuildState,
    request: dict[str, Any],
    completeness: dict[str, Any],
    budget: dict[str, Any],
    selected: list[ContextSection],
    omitted: list[ContextSection],
    loaded_items: list[dict[str, Any]],
    omitted_items: list[dict[str, Any]],
) -> str:
    mode_label = f"{request['mode']}:{request['submode']}"
    lines = [
        "# Context Packet",
        "",
        "## Request",
        "| 字段 | 值 |",
        "|------|----|",
        f"| 玩家输入 | {markdown_table_cell(request['user_text'])} |",
        f"| 模式 | `{markdown_code_text(mode_label)}` |",
        f"| 是否推进时间 | {'是' if request['will_advance_time'] else '否'} |",
        f"| 是否需要保存 | {'是' if request['must_save'] else '否'} |",
        f"| 回复模板 | `{markdown_code_text(request['required_template'])}` |",
        f"| 预算 | {budget['estimated']} / {budget['limit']} |",
        "",
        "## Context Completeness",
        "| 项目 | 状态 |",
        "|------|------|",
        f"| 置信度 | {markdown_table_cell(completeness['confidence'])} |",
        f"| 是否允许推进 | {'是' if completeness['allow_proceed'] else '否'} |",
        f"| 缺失关键信息 | {markdown_table_cell(join_list(completeness['missing_required']))} |",
        f"| 需要玩家确认 | {markdown_table_cell(join_list(completeness['needs_user_confirmation']))} |",
        f"| 假设 | {markdown_table_cell(join_list(completeness['assumptions']))} |",
        "",
    ]
    for section in selected:
        lines.extend([f"## {section.title}", section.content, ""])
    lines.extend(
        [
            "## Loaded And Omitted",
            "",
            "### 已加载",
            "| ID | 类型 | 原因 | 优先级 |",
            "|----|------|------|--------|",
        ]
    )
    for item in loaded_items[:24]:
        lines.append(
            f"| `{markdown_code_text(item['id'])}` | {markdown_table_cell(item['kind'])} | "
            f"{markdown_table_cell(item['reason'])} | {markdown_table_cell(item['priority'])} |"
        )
    if len(loaded_items) > 24:
        lines.append(f"| ... | ... | 另有 {len(loaded_items) - 24} 项 | ... |")
    lines.extend(["", "### 已省略/默认禁止"])
    for item in omitted_items:
        lines.append(f"- `{markdown_code_text(item['id'])}`：{markdown_inline_text(item['reason'])}")
    if omitted and state.debug:
        lines.extend(["", "### 省略分区"])
        for section in omitted:
            lines.append(f"- `{section.key}`：{section.estimated_tokens} tokens，priority {section.priority}")
    return "\n".join(lines).rstrip() + "\n"


def join_list(items: list[str]) -> str:
    return "无" if not items else "；".join(items)


def markdown_table_cell(value: Any, limit_chars: int = 180) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) > limit_chars:
        text = text[: max(0, limit_chars - 1)] + "…"
    text = text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")
    return text or "无"


def markdown_inline_text(value: Any, limit_chars: int = 240) -> str:
    text = str(value or "")
    text = " ".join(text.split())
    if len(text) > limit_chars:
        text = text[: max(0, limit_chars - 1)] + "…"
    return text.replace("`", "\\`")


def markdown_code_text(value: Any) -> str:
    return str(value or "").replace("`", "\\`").replace("|", "\\|").replace("\n", " ")
