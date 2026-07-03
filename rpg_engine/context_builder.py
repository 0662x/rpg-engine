from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .campaign import Campaign
from .context.collectors import (
    DEFAULT_CONTEXT_COLLECTORS,
    build_collector_sections,
    collect_loaded_items,
    run_context_collectors,
)
from .context.budget import context_budget_policy
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
    action_intent_to_dict,
    route_intent,
    turn_contract_for_intent,
    turn_contract_to_dict,
)
from .render import render_scene
from .visibility import context_visibility_view
from .actions import get_default_action_registry
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_INTENT_TIMEOUT_SECONDS, DEFAULT_SEMANTIC_TIMEOUT_SECONDS


@dataclass
class ContextBuildResult:
    request: dict[str, Any]
    budget: dict[str, Any]
    completeness: dict[str, Any]
    loaded_items: list[dict[str, Any]]
    omitted_items: list[dict[str, Any]]
    sections: dict[str, str]
    markdown: str

    def to_json_text(self) -> str:
        data = {
            "request": self.request,
            "budget": self.budget,
            "completeness": self.completeness,
            "loaded_items": self.loaded_items,
            "omitted_items": self.omitted_items,
            "sections": self.sections,
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
    intent_ai: str
    intent_backend: str
    intent_model: str
    intent_provider: str
    intent_timeout: int
    intent_base_url: str
    intent_api_key_env: str
    intent_fallback_backend: str
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
    entity_hits: list[EntityHit] = field(default_factory=list)
    ambiguous_hits: list[EntityHit] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    needs_user_confirmation: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    routes: list[sqlite3.Row] = field(default_factory=list)
    palette_lines: list[str] = field(default_factory=list)
    discovery_states: list[sqlite3.Row] = field(default_factory=list)
    world_settings: list[dict[str, Any]] = field(default_factory=list)
    related_events: list[sqlite3.Row] = field(default_factory=list)
    general_events: list[sqlite3.Row] = field(default_factory=list)
    memory_summaries: list[sqlite3.Row] = field(default_factory=list)
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
) -> ContextBuildResult:
    del output_format
    state = BuildState(
        campaign=campaign,
        conn=conn,
        user_text=user_text.strip(),
        mode_arg=mode,
        submode_arg=submode,
        requested_budget=budget,
        campaign_budget=int(campaign.context_budget or 2500),
        budget_limit=max(500, int(budget if budget is not None else campaign.context_budget or 2500)),
        max_events=max(0, int(max_events)),
        max_depth=max(0, int(max_depth)),
        include_palettes=include_palettes,
        debug=debug,
        semantic_ai=semantic_ai,
        semantic_model=semantic_model,
        semantic_provider=semantic_provider,
        semantic_timeout=max(3, int(semantic_timeout)),
        intent_ai=intent_ai,
        intent_backend=intent_backend,
        intent_model=intent_model,
        intent_provider=intent_provider,
        intent_timeout=max(3, int(intent_timeout)),
        intent_base_url=str(intent_base_url or ""),
        intent_api_key_env=str(intent_api_key_env or ""),
        intent_fallback_backend=str(intent_fallback_backend or "off"),
        external_intent_candidate=external_intent_candidate,
        preflight_id=str(preflight_id or ""),
        message_id=str(message_id or ""),
        platform=str(platform or ""),
        session_key=str(session_key or ""),
        source_user_text_hash=str(source_user_text_hash or ""),
        preflight_pending_wait_ms=max(0, int(preflight_pending_wait_ms)),
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
        intent_ai=state.intent_ai,
        intent_backend=state.intent_backend,
        intent_provider=state.intent_provider,
        intent_model=state.intent_model,
        intent_timeout=state.intent_timeout,
        intent_base_url=state.intent_base_url,
        intent_api_key_env=state.intent_api_key_env,
        intent_fallback_backend=state.intent_fallback_backend,
        external_intent_candidate=state.external_intent_candidate,
        preflight_id=state.preflight_id,
        message_id=state.message_id,
        platform=state.platform,
        session_key=state.session_key,
        source_user_text_hash=state.source_user_text_hash,
        preflight_pending_wait_ms=state.preflight_pending_wait_ms,
    )
    apply_intent_classification(state, intent)


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
    action_names = set(get_default_action_registry().names())
    state.mode = mode
    state.submode = submode
    state.will_advance_time = mode == "action"
    state.must_save = mode == "action"
    state.requires_preview = mode == "action" and submode in action_names
    state.required_template = template_for(mode, submode)
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

    decision = semantic_request_decision(suggestion)
    if decision is None:
        return
    semantic_mode, semantic_submode = decision
    if (state.mode, state.submode) != (semantic_mode, semantic_submode):
        note = f"AI 语义判断仅记录，不覆盖最终路由：`{state.mode}:{state.submode}` vs `{semantic_mode}:{semantic_submode}`。"
        if note not in state.assumptions:
            state.assumptions.append(note)


def semantic_request_decision(suggestion: dict[str, Any]) -> tuple[str, str] | None:
    mode = str(suggestion.get("mode") or "").strip().lower()
    submode = str(suggestion.get("submode") or "").strip().lower()
    action_names = set(get_default_action_registry().names())

    if mode == "action" and submode in action_names:
        return mode, submode
    if mode == "query" and submode in {"entity", "scene", "context"}:
        return mode, submode
    return None


def template_for(mode: str, submode: str) -> str:
    if mode == "query":
        if submode == "scene":
            return "scene_entry.md"
        return "entity_query.md"
    spec = get_default_action_registry().get(submode)
    return spec.response_template if spec else "action_turn.md"


def render_context_result(state: BuildState) -> ContextBuildResult:
    sections = build_sections(state)
    selected, omitted = apply_budget(sections, state.budget_limit)
    included_tokens = sum(section.estimated_tokens for section in selected)
    section_token_map = {section.key: section.estimated_tokens for section in selected}
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

    request = {
        "user_text": state.user_text,
        "mode": state.mode,
        "submode": state.submode,
        "action": state.intent.action if state.intent else None,
        "intent": action_intent_to_dict(state.intent),
        "clarification": clarification,
        "turn_contract": turn_contract_to_dict(turn_contract_for_intent(state.intent)) if state.intent else None,
        "decision_trace": state.intent.decision_trace if state.intent else {},
        "visibility_view": context_visibility_view(state.mode),
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
            "suggestion": state.semantic_suggestion,
            "alias_gaps": state.semantic_alias_gaps,
            "error": state.semantic_error,
            "audit": state.semantic_audit,
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
    completeness = {
        "confidence": confidence,
        "allow_proceed": allow_proceed,
        "missing_required": state.missing_required,
        "needs_user_confirmation": state.needs_user_confirmation,
        "clarification": clarification,
        "assumptions": state.assumptions,
    }
    loaded_items = [
        {
            "id": hit.id,
            "kind": hit.type,
            "name": hit.name,
            "reason": hit.reason,
            "priority": hit.priority,
            "depth": hit.depth,
        }
        for hit in state.entity_hits
    ]
    loaded_items.extend(collect_loaded_items(state, DEFAULT_CONTEXT_COLLECTORS))
    omitted_items = [
        {
            "id": section.key,
            "kind": "section",
            "reason": section.omitted_reason or "budget",
            "priority": section.priority,
            "estimated_tokens": section.estimated_tokens,
        }
        for section in omitted
    ]
    omitted_items.append({"id": "archive_v1/journal.md", "kind": "archive", "reason": "forbidden by default"})
    budget = {
        "limit": state.budget_limit,
        "requested": state.requested_budget,
        "campaign_default": state.campaign_budget,
        "policy_profile": state.budget_policy_profile,
        "policy_reason": state.budget_policy_reason,
        "estimated": included_tokens,
        "sections": section_token_map,
        "trimmed": bool(omitted),
    }
    section_texts = {section.key: section.content for section in selected}
    markdown = render_markdown(state, request, completeness, budget, selected, omitted, loaded_items, omitted_items)
    return ContextBuildResult(
        request=request,
        budget=budget,
        completeness=completeness,
        loaded_items=loaded_items,
        omitted_items=omitted_items,
        sections=section_texts,
        markdown=markdown,
    )


def build_sections(state: BuildState) -> list[ContextSection]:
    sections = [
        ContextSection(
            key="current_scene",
            title="Current Scene",
            content=render_scene(state.conn, view=context_visibility_view(state.mode)),
            priority=100,
            required=True,
        ),
        ContextSection(
            key="player_state",
            title="Player State",
            content=render_player_state(state.conn),
            priority=100,
            required=True,
        ),
    ]
    if state.entity_hits:
        sections.append(
            ContextSection(
                key="relevant_entities",
                title="Relevant Entities",
                content=render_relevant_entities(state),
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
        lines.append(f"| 错误 | {state.semantic_error} |")
        return "\n".join(lines)

    suggestion = state.semantic_suggestion or {}
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
    if state.semantic_alias_gaps:
        lines.extend(["", "#### 别名缺口候选", "", "| 语义目标 | 状态 | 候选 | 建议 |", "|----------|------|------|------|"])
        for gap in state.semantic_alias_gaps:
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
    lines = [
        "# Context Packet",
        "",
        "## Request",
        "| 字段 | 值 |",
        "|------|----|",
        f"| 玩家输入 | {state.user_text} |",
        f"| 模式 | `{request['mode']}:{request['submode']}` |",
        f"| 是否推进时间 | {'是' if request['will_advance_time'] else '否'} |",
        f"| 是否需要保存 | {'是' if request['must_save'] else '否'} |",
        f"| 回复模板 | `{request['required_template']}` |",
        f"| 预算 | {budget['estimated']} / {budget['limit']} |",
        "",
        "## Context Completeness",
        "| 项目 | 状态 |",
        "|------|------|",
        f"| 置信度 | {completeness['confidence']} |",
        f"| 是否允许推进 | {'是' if completeness['allow_proceed'] else '否'} |",
        f"| 缺失关键信息 | {join_list(completeness['missing_required'])} |",
        f"| 需要玩家确认 | {join_list(completeness['needs_user_confirmation'])} |",
        f"| 假设 | {join_list(completeness['assumptions'])} |",
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
        lines.append(f"| `{item['id']}` | {item['kind']} | {item['reason']} | {item['priority']} |")
    if len(loaded_items) > 24:
        lines.append(f"| ... | ... | 另有 {len(loaded_items) - 24} 项 | ... |")
    lines.extend(["", "### 已省略/默认禁止"])
    for item in omitted_items:
        lines.append(f"- `{item['id']}`：{item['reason']}")
    if omitted and state.debug:
        lines.extend(["", "### 省略分区"])
        for section in omitted:
            lines.append(f"- `{section.key}`：{section.estimated_tokens} tokens，priority {section.priority}")
    return "\n".join(lines).rstrip() + "\n"


def join_list(items: list[str]) -> str:
    return "无" if not items else "；".join(items)
