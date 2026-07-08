from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from .actions import get_default_action_registry
from .ai.config import normalize_backend, normalize_fallback_backend
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_INTENT_TIMEOUT_SECONDS
from .ai_intent.external import normalize_external_intent_candidate
from .ai_intent.normalization import normalize_intent_candidate
from .ai_intent.router import AIIntentRouter
from .ai_intent.types import ClarificationChoice, ClarificationQuestion, IntentCandidate, RouteOutcome
from .campaign import Campaign
from .db import entity_subtype_visibility_sql
from .ux import PlanStep, RepairOption, UxStatus
from .visibility import ensure_visibility_sql_functions, entity_visibility_sql, normalized_text_sql


QUERY_KEYWORDS = [
    "看",
    "查看",
    "查",
    "查询",
    "属性",
    "信息",
    "资料",
    "是谁",
    "是什么",
    "在哪",
    "哪里",
    "周围",
    "场景",
]
MAINTENANCE_KEYWORDS = [
    "同步",
    "测试",
    "审计",
    "补卡",
    "迁移",
    "设计",
    "实现",
    "重构",
    "系统",
]
OUT_OF_WORLD_MAINTENANCE_TERMS = (
    "系统维护",
    "维护系统",
    "系统设计",
    "存档",
    "存档索引",
    "数据库",
    "迁移",
    "审计",
    "重构",
    "实现",
    "代码",
    "引擎",
    "schema",
    "migration",
    "database",
    "save index",
)

ROUTINE_INTENT_TERMS = (
    "盘点",
    "整理库存",
    "查看库存",
    "看看物资",
    "清点",
    "inventory",
    "audit",
    "巡查",
    "巡视",
    "巡逻",
    "巡检",
    "照看",
    "维护",
    "查看各单位",
    "查看各角色",
    "各单位和角色",
    "领地状态",
    "单位状态",
    "角色状态",
    "浇水",
    "灌溉",
    "喂养",
    "喂食",
)
CRAFT_INTENT_TERMS = (
    "制作",
    "做个",
    "做一个",
    "做成",
    "做出",
    "修理",
    "校准",
    "装配",
    "craft",
    "make",
    "build",
    "repair",
    "fix",
)
DICE_TEXT_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(?:[1-9][0-9]*)?d[1-9][0-9]*(?:[+-][0-9]+)?(?![A-Za-z0-9_])", re.I)
TABLE_ID_TEXT_PATTERN = re.compile(r"(?<![A-Za-z0-9_])(table:[A-Za-z0-9_.:-]+)(?![A-Za-z0-9_])", re.I)


@dataclass(frozen=True)
class ActionAlternative:
    mode: str
    submode: str
    action: str | None = None
    score: float = 0.0
    source: str = "rules"
    reason: str = ""


@dataclass(frozen=True)
class ActionIntent:
    user_text: str
    mode: str
    submode: str
    action: str | None
    options: dict[str, Any]
    confidence: str
    source: str
    alternatives: tuple[ActionAlternative, ...] = ()
    missing_required: tuple[str, ...] = ()
    needs_confirmation: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    decision_trace: dict[str, Any] = field(default_factory=dict)
    kind: str = "single"
    status: UxStatus = "ready"
    player_message: str = ""
    summary: str = ""
    plan: tuple[PlanStep, ...] = ()
    repair_options: tuple[RepairOption, ...] = ()
    clarification: ClarificationQuestion | None = None


@dataclass(frozen=True)
class LegacyRuleRoute:
    rule_mode: str
    rule_submode: str
    inferred: dict[str, Any]
    outcome: RouteOutcome
    alternatives: tuple[ActionAlternative, ...] = ()
    guards: tuple[str, ...] = ()

    def trace(self) -> dict[str, Any]:
        return {
            "rule": {"mode": self.rule_mode, "submode": self.rule_submode},
            "inferred": summarize_inferred_action(self.inferred),
            "outcome": self.outcome.final_trace(),
            "guards": list(self.guards),
        }


@dataclass(frozen=True)
class TurnContract:
    intent: ActionIntent
    required_template: str
    response_headings: tuple[str, ...]
    requires_preview: bool
    must_save: bool
    allowed_delta_sources: tuple[str, ...]
    validation_profile: str


@dataclass(frozen=True)
class IntentAIConfig:
    mode: str
    backend: str
    provider: str
    model: str
    timeout: int
    base_url: str
    api_key_env: str
    fallback_backend: str


@dataclass(frozen=True)
class IntentRequestMeta:
    preflight_id: str = ""
    message_id: str = ""
    platform: str = ""
    session_key: str = ""
    source_user_text_hash: str = ""
    preflight_pending_wait_ms: int = 0


@dataclass(frozen=True)
class ExternalCandidateInput:
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreparedIntentCandidates:
    text: str
    explicit_mode: str | None
    explicit_submode: str | None
    legacy_route: LegacyRuleRoute
    rules_candidate: IntentCandidate
    external_low_trust_candidate: IntentCandidate | None


def route_intent(
    campaign: Campaign,
    conn: sqlite3.Connection,
    user_text: str,
    *,
    mode: str = "auto",
    submode: str | None = None,
    semantic_suggestion: dict[str, Any] | None = None,
    semantic_ai: str = "off",
    semantic_provider: str | None = None,
    semantic_model: str | None = None,
    semantic_timeout: int | None = None,
    intent_ai: str = "off",
    intent_backend: str = "direct",
    intent_provider: str | None = None,
    intent_model: str | None = None,
    intent_timeout: int | None = None,
    intent_base_url: str | None = None,
    intent_api_key_env: str | None = None,
    intent_fallback_backend: str | None = None,
    external_intent_candidate: dict[str, Any] | None = None,
    preflight_id: str | None = None,
    message_id: str | None = None,
    platform: str | None = None,
    session_key: str | None = None,
    source_user_text_hash: str | None = None,
    preflight_pending_wait_ms: int = 0,
) -> ActionIntent:
    """Return the single intent contract shared by context, CLI and MCP flows."""
    del semantic_ai, semantic_provider, semantic_model, semantic_timeout
    ai_config = make_intent_ai_config(
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
    prepared = prepare_intent_candidates(
        conn,
        user_text,
        mode=mode,
        submode=submode,
        external_candidate_input=ExternalCandidateInput(external_intent_candidate),
    )
    text = prepared.text
    explicit_mode = prepared.explicit_mode
    explicit_submode = prepared.explicit_submode
    legacy_route = prepared.legacy_route
    rules_candidate = prepared.rules_candidate
    external_candidate = prepared.external_low_trust_candidate
    outcome = legacy_route.outcome
    alternatives: list[ActionAlternative] = list(legacy_route.alternatives)
    guards: list[str] = list(legacy_route.guards)
    overrides: list[str] = []
    action_names = set(get_default_action_registry().names())

    semantic_decision = semantic_request_decision(semantic_suggestion or {})
    if semantic_decision:
        semantic_mode, semantic_submode = semantic_decision
        alternatives.append(
            ActionAlternative(
                mode=semantic_mode,
                submode=semantic_submode,
                action=semantic_submode if semantic_mode == "action" and semantic_submode in action_names else None,
                score=0.40,
                source="semantic_ai_trace",
                reason="semantic suggestion recorded as trace-only",
            )
        )
        if explicit_mode and semantic_mode != explicit_mode:
            guards.append(f"semantic mode {semantic_mode} observed but explicit mode is {explicit_mode}")
        elif not explicit_submode and (semantic_mode, semantic_submode) != (outcome.mode, outcome.submode):
            old = f"{outcome.mode}:{outcome.submode}"
            new = f"{semantic_mode}:{semantic_submode}"
            overrides.append(f"AI 语义判断仅记录，不覆盖最终路由：`{old}` vs `{new}`。")

    intent_router = AIIntentRouter(conn)
    intent_route = intent_router.route_candidates(
        campaign,
        text,
        intent_ai_mode=ai_config.mode,
        external_candidate=external_candidate,
        rule_candidate=rules_candidate,
        rules_outcome=outcome,
        backend=ai_config.backend,
        provider=ai_config.provider,
        model=ai_config.model,
        timeout=ai_config.timeout,
        base_url=ai_config.base_url,
        api_key_env=ai_config.api_key_env,
        fallback_backend=ai_config.fallback_backend,
        preflight_id=request_meta.preflight_id,
        message_id=request_meta.message_id,
        platform=request_meta.platform,
        session_key=request_meta.session_key,
        source_user_text_hash=request_meta.source_user_text_hash,
        preflight_pending_wait_ms=request_meta.preflight_pending_wait_ms,
    )
    guards.extend(intent_route.guards)
    intent_ai_trace = intent_route.trace
    decision = intent_route.decision
    selected_outcome = intent_route.selected_outcome or outcome
    if intent_route.consensus_outcome is not None and selected_outcome == intent_route.consensus_outcome:
        outcome = selected_outcome
        alternatives.append(
            ActionAlternative(
                mode=outcome.mode,
                submode=outcome.submode,
                action=outcome.action,
                score=0.94 if outcome.source == "ai_consensus" else 0.50,
                source=outcome.source,
                reason=f"intent AI consensus decision: {decision.status if decision else 'unknown'}",
            )
        )
    else:
        outcome = selected_outcome

    decision_trace = {
        "source": outcome.source,
        "confidence": outcome.confidence,
        "rule": {"mode": legacy_route.rule_mode, "submode": legacy_route.rule_submode},
        "legacy_rule_route": legacy_route.trace(),
        "inferred": summarize_inferred_action(legacy_route.inferred),
        "semantic": semantic_trace(semantic_suggestion),
        "rules_candidate": rules_candidate.to_dict(),
        "intent_ai": intent_ai_trace,
        "consensus": (intent_ai_trace.get("decision") or {}).get("decision_trace", {}).get("consensus")
        if isinstance(intent_ai_trace.get("decision"), dict)
        else None,
        "binding": (intent_ai_trace.get("decision") or {}).get("bound")
        if isinstance(intent_ai_trace.get("decision"), dict)
        else None,
        "final_intent": outcome.final_trace(),
        "candidates": [asdict(item) for item in alternatives],
        "overrides": overrides,
        "guards": guards,
        "explicit": {"mode": explicit_mode, "submode": explicit_submode},
    }
    return ActionIntent(
        user_text=text,
        mode=outcome.mode,
        submode=outcome.submode,
        action=outcome.action,
        options=dict(outcome.options),
        confidence=outcome.confidence,
        source=outcome.source,
        alternatives=tuple(alternatives),
        missing_required=outcome.missing_required,
        needs_confirmation=outcome.needs_confirmation,
        errors=outcome.errors,
        decision_trace=decision_trace,
        kind=outcome.kind,
        status=outcome.status,
        player_message=outcome.player_message,
        summary=outcome.summary,
        plan=outcome.plan,
        repair_options=outcome.repair_options,
        clarification=outcome.clarification,
    )


def make_intent_ai_config(
    *,
    intent_ai: str = "off",
    intent_backend: str = "direct",
    intent_provider: str | None = None,
    intent_model: str | None = None,
    intent_timeout: int | None = None,
    intent_base_url: str | None = None,
    intent_api_key_env: str | None = None,
    intent_fallback_backend: str | None = None,
) -> IntentAIConfig:
    return IntentAIConfig(
        mode=normalize_intent_ai_mode(intent_ai),
        backend=normalize_backend(intent_backend, "direct"),
        provider=intent_provider or DEFAULT_AI_PROVIDER,
        model=intent_model or DEFAULT_AI_MODEL,
        timeout=DEFAULT_INTENT_TIMEOUT_SECONDS if intent_timeout is None else max(3, int(intent_timeout)),
        base_url=str(intent_base_url or ""),
        api_key_env=str(intent_api_key_env or ""),
        fallback_backend=normalize_fallback_backend(intent_fallback_backend, "off"),
    )


def make_intent_request_meta(
    *,
    preflight_id: str | None = None,
    message_id: str | None = None,
    platform: str | None = None,
    session_key: str | None = None,
    source_user_text_hash: str | None = None,
    preflight_pending_wait_ms: int = 0,
) -> IntentRequestMeta:
    return IntentRequestMeta(
        preflight_id=str(preflight_id or ""),
        message_id=str(message_id or ""),
        platform=str(platform or ""),
        session_key=str(session_key or ""),
        source_user_text_hash=str(source_user_text_hash or ""),
        preflight_pending_wait_ms=preflight_pending_wait_ms,
    )


def prepare_intent_candidates(
    conn: sqlite3.Connection,
    user_text: str,
    *,
    mode: str = "auto",
    submode: str | None = None,
    external_candidate_input: ExternalCandidateInput | None = None,
) -> PreparedIntentCandidates:
    text = normalize_player_text(user_text).strip()
    external_payload = external_candidate_input.payload if external_candidate_input is not None else None
    external_candidate = (
        normalize_external_intent_candidate(external_payload, user_text=text)
        if external_payload is not None
        else None
    )
    explicit_mode = mode if mode != "auto" else None
    explicit_submode = submode
    legacy_route = build_legacy_rule_route(
        conn,
        text,
        explicit_mode=explicit_mode,
        explicit_submode=explicit_submode,
    )
    outcome = legacy_route.outcome
    rules_candidate = build_rules_intent_candidate(
        text,
        rule_mode=legacy_route.rule_mode,
        rule_submode=legacy_route.rule_submode,
        inferred=legacy_route.inferred,
        route_mode=outcome.mode,
        route_action=outcome.action,
        route_options=outcome.options,
        route_kind=outcome.kind,
        confidence=outcome.confidence,
    )
    return PreparedIntentCandidates(
        text=text,
        explicit_mode=explicit_mode,
        explicit_submode=explicit_submode,
        legacy_route=legacy_route,
        rules_candidate=rules_candidate,
        external_low_trust_candidate=external_candidate,
    )


def build_legacy_rule_route(
    conn: sqlite3.Connection,
    text: str,
    *,
    explicit_mode: str | None,
    explicit_submode: str | None,
) -> LegacyRuleRoute:
    action_names = set(get_default_action_registry().names())
    rule_submode = explicit_submode or infer_submode(text)
    rule_mode = explicit_mode or infer_mode(text, rule_submode)
    if rule_mode == "query" and rule_submode in action_names:
        rule_mode = "action"
    if rule_mode == "query" and rule_submode == "rule":
        rule_submode = "context"
    if rule_mode == "action" and rule_submode in {"entity", "scene", "context"}:
        rule_submode = infer_action_submode(text)
    if rule_mode == "maintenance":
        rule_submode = "maintenance"

    inferred = infer_player_action(conn, text)
    alternatives: list[ActionAlternative] = [
        ActionAlternative(
            mode=rule_mode,
            submode=rule_submode,
            action=rule_submode if rule_mode == "action" and rule_submode in action_names else None,
            score=0.60,
            source="rules",
            reason="keyword and explicit mode classification",
        )
    ]
    guards: list[str] = []

    route_mode = rule_mode
    route_submode = rule_submode
    route_action: str | None = None
    route_options: dict[str, Any] = {}
    route_kind = "single"
    route_status: UxStatus = "ready"
    route_missing: tuple[str, ...] = ()
    route_confirmations: tuple[str, ...] = ()
    route_errors: tuple[str, ...] = ()
    route_plan: tuple[PlanStep, ...] = ()
    route_repairs: tuple[RepairOption, ...] = ()
    route_message = ""
    route_summary = ""
    source = "explicit" if explicit_mode or explicit_submode else "rules"
    confidence = "medium"

    if should_use_playable_inference(
        conn,
        text,
        explicit_mode=explicit_mode,
        rule_mode=rule_mode,
        rule_submode=rule_submode,
        inferred=inferred,
    ):
        route_mode = "action"
        route_kind = str(inferred.get("kind") or "single")
        route_action = str(inferred.get("action") or "") or None
        route_submode = route_action if route_action in action_names else route_submode
        route_options = dict(inferred.get("options", {})) if isinstance(inferred.get("options"), dict) else {}
        route_status = inferred_status(inferred)
        route_missing = tuple(str(item) for item in inferred.get("missing_required", ()))
        route_confirmations = tuple(str(item) for item in inferred.get("needs_confirmation", ()))
        route_errors = tuple(str(item) for item in inferred.get("errors", ()))
        route_plan = tuple(inferred.get("plan", ()))
        route_repairs = tuple(inferred.get("repair_options", ()))
        route_message = str(inferred.get("player_message") or "")
        route_summary = str(inferred.get("summary") or "")
        source = "action_inference" if source == "rules" else source
        confidence = "high" if not inferred.get("fallback") else "medium"
        alternatives.append(
            ActionAlternative(
                mode="action",
                submode=route_submode,
                action=route_action,
                score=0.78 if not inferred.get("fallback") else 0.52,
                source="action_inference",
                reason=f"natural-language action inference returned {route_kind}",
            )
        )
    elif route_mode == "action" and route_submode in action_names:
        route_action = route_submode
        route_options = {"user_text": text}

    if route_mode == "maintenance":
        route_action = None
        route_kind = "maintenance"
        source = "explicit" if explicit_mode == "maintenance" else source
    if route_mode != "action":
        route_action = None
        route_options = {}
        route_status = "ready"
        route_missing = ()
        route_confirmations = ()
        route_errors = ()
        route_plan = ()
        route_repairs = ()

    if route_mode == "maintenance" and explicit_mode != "maintenance":
        route_mode = "unknown"
        route_submode = "unknown"
        route_kind = "unresolved"
        route_status = "blocked"
        route_errors = ("maintenance request is outside the normal player intent mode",)
        route_message = "这是维护或作者工具请求，不会作为普通玩家回合处理。"
        guards.append("auto maintenance classification blocked from normal player intent mode")

    if route_mode == "action" and route_kind == "composite":
        route_submode = "composite"
        route_action = None
        route_status = "needs_confirmation"
        route_confirmations = route_confirmations or ("composite action requires step confirmation",)

    if route_mode == "action" and route_action and route_action not in action_names:
        route_missing = tuple(dict.fromkeys([*route_missing, "action"]))
        guards.append(f"unknown inferred action ignored: {route_action}")

    return LegacyRuleRoute(
        rule_mode=rule_mode,
        rule_submode=rule_submode,
        inferred=inferred,
        outcome=RouteOutcome(
            mode=route_mode,
            submode=route_submode,
            action=route_action,
            options=route_options,
            kind=route_kind,
            status=route_status,
            missing_required=route_missing,
            needs_confirmation=route_confirmations,
            errors=route_errors,
            player_message=route_message,
            summary=route_summary,
            source=source,
            confidence=confidence,
            plan=route_plan,
            repair_options=route_repairs,
        ),
        alternatives=tuple(alternatives),
        guards=tuple(guards),
    )


def build_rules_intent_candidate(
    user_text: str,
    *,
    rule_mode: str,
    rule_submode: str,
    inferred: dict[str, Any],
    route_mode: str,
    route_action: str | None,
    route_options: dict[str, Any],
    route_kind: str,
    confidence: str,
) -> IntentCandidate:
    action_names = set(get_default_action_registry().names())
    mode = route_mode if route_mode in {"action", "query", "maintenance", "unknown"} else rule_mode
    kind = route_kind if route_kind in {"single", "composite", "query", "maintenance", "unresolved"} else "single"
    action: str | None = None
    if str(inferred.get("action") or "") in action_names:
        action = str(inferred.get("action"))
    elif route_action in action_names:
        action = route_action
    elif rule_mode == "action" and rule_submode in action_names:
        action = rule_submode
    slots = {}
    inferred_options = inferred.get("options")
    if isinstance(inferred_options, dict):
        slots.update(inferred_options)
    if route_options:
        slots.update(route_options)
    slots.pop("user_text", None)
    if mode != "action":
        action = None
        slots = {}
        kind = "maintenance" if mode == "maintenance" else ("query" if mode == "query" else "unresolved")
    return normalize_intent_candidate(
        {
            "kind": kind,
            "mode": mode,
            "action": action or "",
            "slots": slots,
            "plan": [],
            "confidence": confidence if confidence in {"high", "medium", "low"} else "medium",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [],
            "reason": "legacy rules and action inference candidate",
        },
        source="rules",
        user_text=user_text,
    )


def normalize_intent_ai_mode(value: str | None) -> str:
    mode = str(value or "off").strip().lower()
    if mode not in {"off", "consensus"}:
        raise ValueError("intent_ai must be one of: off, consensus")
    return mode


def should_use_playable_inference(
    conn: sqlite3.Connection,
    text: str,
    *,
    explicit_mode: str | None,
    rule_mode: str,
    rule_submode: str,
    inferred: dict[str, Any],
) -> bool:
    if explicit_mode == "query":
        return False
    if str(inferred.get("kind") or "") == "unresolved" and inferred.get("action") == "act":
        return True
    if rule_mode == "maintenance":
        return False
    action_names = set(get_default_action_registry().names())
    if inferred.get("fallback") and rule_mode == "action" and rule_submode in action_names:
        return False
    if (
        str(inferred.get("kind") or "") == "unresolved"
        and rule_mode == "action"
        and rule_submode in action_names
        and inferred.get("action") != rule_submode
    ):
        if rule_submode in {"social", "travel"}:
            return True
        return False
    if explicit_mode == "action":
        return True
    kind = str(inferred.get("kind") or "")
    if kind in {"unresolved", "composite"}:
        return True
    if is_read_only_status_or_inventory_query(text):
        return False
    if kind == "single" and not inferred.get("fallback"):
        return True
    if is_pure_query_text(conn, text, rule_submode=rule_submode, inferred=inferred):
        return False
    return rule_mode == "action"


def is_pure_query_text(
    conn: sqlite3.Connection,
    text: str,
    *,
    rule_submode: str,
    inferred: dict[str, Any],
) -> bool:
    del conn
    if rule_submode == "scene" and text_has_any(text, ("周围", "场景", "我在哪", "where am i", "look around")):
        return True
    if text_has_any(text, ("属性", "信息", "资料", "是谁", "是什么", "在哪", "哪里")):
        return True
    if is_read_only_status_or_inventory_query(text):
        return True
    if contains_any(text, QUERY_KEYWORDS) and inferred.get("fallback"):
        return True
    return False


def is_read_only_status_or_inventory_query(text: str) -> bool:
    return text_has_any(
        text,
        (
            "数量",
            "多少",
            "还剩",
            "剩余",
            "有几",
            "库存数量",
            "当前状态",
            "有哪些待处理项目",
            "待处理项目",
            "待办",
        ),
    )


def turn_contract_for_intent(intent: ActionIntent) -> TurnContract:
    action_names = set(get_default_action_registry().names())
    blocked = intent.status == "blocked"
    requires_preview = (
        intent.mode == "action"
        and intent.kind == "single"
        and bool(intent.action in action_names)
        and not blocked
    )
    must_save = intent.mode == "action" and not blocked
    if intent.mode == "query":
        headings = ("查询结果", "相关事实", "可选后续")
        allowed_sources: tuple[str, ...] = ()
        profile = "preview_only"
    elif intent.mode == "maintenance":
        headings = ("维护结果", "状态", "后续处理")
        allowed_sources = ("maintenance_delta",)
        profile = "maintenance_commit"
    elif intent.mode == "unknown":
        headings = ("无法处理", "原因", "可选后续")
        allowed_sources = ()
        profile = "preview_only"
    else:
        headings = ("场景", "行动结果", "状态变化", "保存状态", "后续行动")
        allowed_sources = ("resolver_proposed", "ai_generated", "human_edited", "response_draft")
        profile = "player_turn_commit"
    return TurnContract(
        intent=intent,
        required_template=template_for(intent.mode, intent.submode),
        response_headings=headings,
        requires_preview=requires_preview,
        must_save=must_save,
        allowed_delta_sources=allowed_sources,
        validation_profile=profile,
    )


def action_intent_to_dict(intent: ActionIntent | None) -> dict[str, Any] | None:
    if intent is None:
        return None
    return {
        "user_text": intent.user_text,
        "mode": intent.mode,
        "submode": intent.submode,
        "action": intent.action,
        "options": intent.options,
        "confidence": intent.confidence,
        "source": intent.source,
        "alternatives": [asdict(item) for item in intent.alternatives],
        "missing_required": list(intent.missing_required),
        "needs_confirmation": list(intent.needs_confirmation),
        "errors": list(intent.errors),
        "decision_trace": intent.decision_trace,
        "kind": intent.kind,
        "status": intent.status,
        "player_message": intent.player_message,
        "summary": intent.summary,
        "plan": [asdict(item) for item in intent.plan],
        "repair_options": [asdict(item) for item in intent.repair_options],
        "clarification": intent.clarification.to_dict() if intent.clarification else None,
    }


def action_intent_from_dict(data: dict[str, Any]) -> ActionIntent:
    if not isinstance(data, dict):
        raise ValueError("ActionIntent must be an object")
    return ActionIntent(
        user_text=str(data.get("user_text") or ""),
        mode=str(data.get("mode") or ""),
        submode=str(data.get("submode") or ""),
        action=str(data["action"]) if data.get("action") is not None else None,
        options=dict(data.get("options") or {}),
        confidence=str(data.get("confidence") or "unknown"),
        source=str(data.get("source") or "unknown"),
        alternatives=tuple(
            ActionAlternative(
                mode=str(item.get("mode") or ""),
                submode=str(item.get("submode") or ""),
                action=str(item["action"]) if item.get("action") is not None else None,
                score=float(item.get("score") or 0.0),
                source=str(item.get("source") or "rules"),
                reason=str(item.get("reason") or ""),
            )
            for item in data.get("alternatives", [])
            if isinstance(item, dict)
        ),
        missing_required=tuple(str(item) for item in data.get("missing_required", [])),
        needs_confirmation=tuple(str(item) for item in data.get("needs_confirmation", [])),
        errors=tuple(str(item) for item in data.get("errors", [])),
        decision_trace=dict(data.get("decision_trace") or {}),
        kind=str(data.get("kind") or "single"),
        status=coerce_status(data.get("status")),
        player_message=str(data.get("player_message") or ""),
        summary=str(data.get("summary") or ""),
        plan=tuple(
            PlanStep(
                step_id=str(item.get("step_id") or ""),
                action=str(item.get("action") or ""),
                label=str(item.get("label") or ""),
                status=coerce_status(item.get("status")),
                options=dict(item.get("options") or {}),
                estimated_minutes=item.get("estimated_minutes") if isinstance(item.get("estimated_minutes"), int) else None,
                risk_level=str(item.get("risk_level") or "low"),
                delta_draft=item.get("delta_draft") if isinstance(item.get("delta_draft"), dict) else None,
            )
            for item in data.get("plan", [])
            if isinstance(item, dict)
        ),
        repair_options=tuple(
            RepairOption(
                id=str(item.get("id") or ""),
                label=str(item.get("label") or ""),
                description=str(item.get("description") or ""),
                action=str(item["action"]) if item.get("action") is not None else None,
                options=dict(item.get("options") or {}),
                effect=str(item.get("effect") or ""),
                risk_level=str(item.get("risk_level") or "low"),
                requires_confirmation=bool(item.get("requires_confirmation", True)),
            )
            for item in data.get("repair_options", [])
            if isinstance(item, dict)
        ),
        clarification=clarification_from_dict(data.get("clarification")),
    )


def clarification_from_dict(data: Any) -> ClarificationQuestion | None:
    if not isinstance(data, dict):
        return None
    return ClarificationQuestion(
        clarification_id=str(data.get("clarification_id") or ""),
        reason=str(data.get("reason") or ""),
        question=str(data.get("question") or ""),
        choices=tuple(
            ClarificationChoice(
                id=str(item.get("id") or ""),
                label=str(item.get("label") or ""),
                source=str(item.get("source") or ""),
                mode=str(item.get("mode") or ""),
                action=str(item["action"]) if item.get("action") is not None else None,
                slots=dict(item.get("slots") or {}),
                confidence=str(item.get("confidence") or "unknown"),
                reason=str(item.get("reason") or ""),
            )
            for item in data.get("choices", [])
            if isinstance(item, dict)
        ),
        disagreements=tuple(str(item) for item in data.get("disagreements", [])),
        missing_slots=tuple(str(item) for item in data.get("missing_slots", [])),
        suggested_next_tool=str(data.get("suggested_next_tool") or "ask_clarification"),
    )


def turn_contract_to_dict(contract: TurnContract | None) -> dict[str, Any] | None:
    if contract is None:
        return None
    return {
        "intent": action_intent_to_dict(contract.intent),
        "required_template": contract.required_template,
        "response_headings": list(contract.response_headings),
        "requires_preview": contract.requires_preview,
        "must_save": contract.must_save,
        "allowed_delta_sources": list(contract.allowed_delta_sources),
        "validation_profile": contract.validation_profile,
    }


def turn_contract_from_dict(data: dict[str, Any]) -> TurnContract:
    if not isinstance(data, dict):
        raise ValueError("TurnContract must be an object")
    intent_data = data.get("intent")
    if not isinstance(intent_data, dict):
        raise ValueError("TurnContract.intent must be an object")
    return TurnContract(
        intent=action_intent_from_dict(intent_data),
        required_template=str(data.get("required_template") or ""),
        response_headings=tuple(str(item) for item in data.get("response_headings", [])),
        requires_preview=bool(data.get("requires_preview")),
        must_save=bool(data.get("must_save")),
        allowed_delta_sources=tuple(str(item) for item in data.get("allowed_delta_sources", [])),
        validation_profile=str(data.get("validation_profile") or ""),
    )


def semantic_request_decision(suggestion: dict[str, Any]) -> tuple[str, str] | None:
    confidence = str(suggestion.get("confidence") or "").strip().lower()
    if confidence and confidence != "high":
        return None
    mode = str(suggestion.get("mode") or "").strip().lower()
    submode = str(suggestion.get("submode") or "").strip().lower()
    action_names = set(get_default_action_registry().names())

    if mode == "action" and submode in action_names:
        return mode, submode
    if mode == "query" and submode in {"entity", "scene", "context"}:
        return mode, submode
    return None


def infer_mode(text: str, submode: str) -> str:
    if is_out_of_world_maintenance_request(text):
        return "maintenance"
    if contains_any(text, MAINTENANCE_KEYWORDS) and not contains_any(text, [*QUERY_KEYWORDS, *action_keywords()]):
        return "maintenance"
    if submode in set(get_default_action_registry().names()):
        return "action"
    return "query"


def infer_submode(text: str) -> str:
    if is_out_of_world_maintenance_request(text):
        return "maintenance"
    action = infer_action_from_registry(text)
    if action and not (action == "social" and contains_any(text, QUERY_KEYWORDS)):
        if action != "travel" or not contains_any(text, QUERY_KEYWORDS):
            return action
    if text_has_any(text, ("有哪些待处理项目", "待处理项目", "待办")):
        return "scene"
    if "规则" in text or "能不能" in text:
        return "context"
    if "周围" in text or "场景" in text or "我在哪" in text:
        return "scene"
    return "entity"


def infer_action_submode(text: str) -> str:
    return infer_action_from_registry(text) or default_action_submode()


def is_out_of_world_maintenance_request(text: str) -> bool:
    if text_has_any(text, OUT_OF_WORLD_MAINTENANCE_TERMS):
        return True
    return text_has_any(text, ("同步", "设计", "重构", "实现", "审计", "迁移", "补卡")) and text_has_any(
        text,
        ("系统", "存档", "内容", "规则", "代码", "引擎", "工具", "schema", "database", "migration"),
    )


def infer_action_from_registry(text: str) -> str | None:
    specs = sorted(
        get_default_action_registry().all(),
        key=lambda spec: (spec.inference_priority, spec.name),
    )
    for spec in specs:
        if spec.name == "travel":
            continue
        if contains_any(text, list(spec.keywords)):
            return spec.name
    travel = get_default_action_registry().get("travel")
    if travel and contains_any(text, list(travel.keywords)):
        return travel.name
    if text_has_any(text, ROUTINE_INTENT_TERMS):
        return "routine"
    return None


def default_action_submode() -> str:
    registry = get_default_action_registry()
    return "travel" if registry.get("travel") else (registry.names()[0] if registry.names() else "action")


def action_keywords() -> list[str]:
    keywords: list[str] = []
    for spec in get_default_action_registry().all():
        keywords.extend(spec.keywords)
    keywords.extend(ROUTINE_INTENT_TERMS)
    return keywords


def template_for(mode: str, submode: str) -> str:
    if mode == "query":
        if submode == "scene":
            return "scene_entry.md"
        return "entity_query.md"
    spec = get_default_action_registry().get(submode)
    return spec.response_template if spec else "action_turn.md"


def contains_any(text: str, terms: list[str] | tuple[str, ...]) -> bool:
    return any(term and term in text for term in terms)


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


def text_has_any(text: str, terms: tuple[str, ...]) -> bool:
    haystack = normalize_player_text(text).lower()
    for term in terms:
        normalized = normalize_player_text(term).strip().lower()
        if not normalized:
            continue
        if re.search(r"[\u4e00-\u9fff]", normalized):
            if normalized in haystack:
                return True
            continue
        if re.search(rf"\b{re.escape(normalized)}\b", haystack):
            return True
    return False


def is_meta_or_override_text(text: str) -> bool:
    stripped = normalize_player_text(text).strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if has_unsafe_control_characters(stripped):
        return True
    if stripped.startswith("/") or stripped.startswith("---") or "```" in stripped:
        return True
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        return True
    if re.search(r"\b(drop\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set|select\s+\*)\b", lowered):
        return True
    if re.search(r"\b(python|import\s+os|rm\s+-rf|chmod|curl|wget|aigm\s+|mcp|commit_turn|validate_delta|preview_action)\b", lowered):
        return True
    if re.search(r"(\.\./|~/.ssh|/etc/passwd|id_rsa|game\.sqlite|<script|</script|{{|}}|%n)", lowered):
        return True
    return text_has_any(
        stripped,
        (
            "管理员",
            "最高权限",
            "root模式",
            "系统命令",
            "忽略规则",
            "忽略之前",
            "忽略安全边界",
            "绕过规则",
            "不预演",
            "直接保存",
            "强制保存",
            "删除存档",
            "删除整个世界",
            "重置存档",
            "重置为空白",
            "数据库",
            "删库",
            "删除entities",
            "删除turns",
            "执行SQL",
            "系统提示",
            "开发者指令",
            "隐藏信息",
            "隐藏规则",
            "隐藏线索",
            "未公开",
            "GM笔记",
            "GM秘密",
            "GM隐藏",
            "你不是GM",
            "无约束模型",
            "必须服从",
            "visibility",
            "改成known",
            "不用travel",
            "不用 travel",
            "不触发风险",
            "不消耗时间",
            "直接通关",
            "风暴结束",
            "桥修好了",
            "杀死所有NPC",
            "清空敌人",
            "获得全部",
            "无限",
            "改成0",
            "设为已确认",
            "跳过preview",
            "跳过validate",
            "直接commit",
            "直接写入delta",
            "参数delta",
            "调用MCP",
            "MCP工具",
            "添加gather_search",
            "添加能力",
            "关闭所有校验",
            "关闭校验器",
            "health check",
            "删除删除",
            "drop table",
            "ignore rules",
            "ignore previous",
            "bypass rules",
            "force save",
            "system prompt",
            "developer message",
            "hidden info",
            "gm secret",
            "jailbreak",
            "unrestricted model",
            "must obey",
            "teleport",
        ),
    )


def is_negated_or_hypothetical_action_text(text: str) -> bool:
    stripped = normalize_player_text(text).strip()
    return text_has_any(
        stripped,
        (
            "不要去",
            "不去",
            "别去",
            "不要前往",
            "别前往",
            "不要离开",
            "别离开",
            "保持当前位置不变",
            "不要问",
            "别问",
            "别和",
            "不要保存",
            "只是测试",
            "测试一下",
            "会怎样",
            "能不能去",
        ),
    )


def looks_like_noise_text(text: str) -> bool:
    stripped = normalize_player_text(text).strip()
    if not stripped:
        return False
    meaningful = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", stripped)
    meaningful_chars = sum(len(item) for item in meaningful)
    if meaningful_chars == 0:
        return True
    return meaningful_chars < 3 and len(stripped) >= 8


def infer_player_action(conn: sqlite3.Connection, user_text: str) -> dict[str, Any]:
    text = user_text.strip()
    if is_meta_or_override_text(text):
        return unresolved_act(
            status="blocked",
            message="这看起来是系统、存档、越权或强制保存指令，不会作为角色行动保存。请改成角色在世界内实际尝试做的事。",
            repair_id="describe_in_world_action",
            label="改成角色行动",
            action="act",
            errors=("out-of-world command is not a playable action",),
        )
    if is_negated_or_hypothetical_action_text(text):
        return unresolved_act(
            status="clarify",
            message="这句话像是否定、假设或测试请求，不会保存为角色行动。请直接说明角色现在要实际执行的动作。",
            repair_id="confirm_actual_action",
            label="确认实际行动",
            action="act",
            missing_required=("actual_action",),
        )
    if looks_like_noise_text(text):
        return unresolved_act(
            status="clarify",
            message="这段输入没有足够可解析的角色行动。请换成一句明确的游戏内动作。",
            repair_id="rewrite_clear_action",
            label="重写行动",
            action="act",
            missing_required=("user_text",),
        )

    location = first_visible_entity_in_text(conn, text, "location")
    character = first_visible_entity_in_text(conn, text, "character")
    gather_target = first_visible_entity_in_text(conn, text, None, preferred_types=("plant", "item", "material", "crop_plot"))
    if gather_target and gather_target["type"] not in {"plant", "item", "material", "crop_plot"}:
        gather_target = None
    explore_target = first_visible_entity_in_text(
        conn,
        text,
        None,
        preferred_types=("reference", "location", "threat", "project", "faction_state", "world_setting"),
    )
    has_inventory_intent = text_has_any(text, ("盘点", "整理库存", "查看库存", "看看物资", "清点", "inventory", "audit"))
    has_routine_intent = has_inventory_intent or text_has_any(text, ROUTINE_INTENT_TERMS)
    has_travel_intent = text_has_any(text, ("去", "前往", "到", "移动", "go", "travel", "move", "walk", "head"))
    has_social_intent = text_has_any(text, ("问", "聊", "谈", "告诉", "询问", "ask", "talk", "speak", "tell", "chat"))
    has_find_intent = text_has_any(text, ("找", "寻找", "查找", "find", "look for", "search for"))
    has_search_intent = has_find_intent or text_has_any(text, ("搜索", "搜寻", "search"))
    has_explore_intent = text_has_any(text, ("探索", "调查", "搜索", "检查", "侦查", "explore", "investigate", "inspect", "check", "scout"))
    has_craft_intent = text_has_any(text, CRAFT_INTENT_TERMS)
    has_rest_intent = text_has_any(text, ("睡", "休息", "守夜", "等到明早", "过夜", "rest", "sleep", "wait"))
    has_random_intent = text_has_any(text, ("随机", "掷骰", "骰子", "事件表", "随机表", "roll", "dice", "random"))
    resource_terms = ("草药", "药草", "月白草", "材料", "食材", "芦苇", "河泥", "灰", "纤维", "样本")
    explicit_gather_intent = text_has_any(
        text,
        ("采", "采集", "采药", "摘", "收", "拾取", "捡", "收集", "弄点", "gather", "collect", "pick", "harvest"),
    )
    resource_search_intent = has_find_intent and text_has_any(text, resource_terms) and not has_craft_intent
    has_gather_intent = explicit_gather_intent or resource_search_intent

    if has_inventory_intent and (
        has_travel_intent or has_social_intent or has_gather_intent or has_search_intent or has_explore_intent or has_craft_intent
    ):
        return composite_inventory_plan(text, user_text, location, character, gather_target, explore_target)

    if has_inventory_intent:
        return {
            "kind": "single",
            "action": "routine",
            "options": {"task": "盘点库存", "user_text": user_text},
        }

    if has_routine_intent and not (has_travel_intent or has_social_intent or has_gather_intent or has_craft_intent):
        return {
            "kind": "single",
            "action": "routine",
            "options": {"task": text, "user_text": user_text},
        }

    if has_rest_intent:
        return {
            "kind": "single",
            "action": "rest",
            "options": {"until": infer_rest_until(text), "user_text": user_text},
        }

    if has_random_intent:
        random_options = infer_random_options(text, user_text)
        if "table" in random_options or "dice" in random_options:
            return {
                "kind": "single",
                "action": "random_table",
                "options": random_options,
            }
        return unresolved_act(
            status="clarify",
            message="请提供随机表 id（例如 table:bridge-risk）或骰子表达式（例如 1d6）。",
            repair_id="clarify_random_source",
            label="补充随机来源",
            action="random_table",
            missing_required=("table or dice",),
        )

    if location and text_has_any(text, ("再回来", "往返", "一圈", "return", "come back", "round trip")):
        return {
            "kind": "composite",
            "summary": f"前往{location['name']}，处理现场后返回。",
            "player_message": f"我理解你想去 {location['name']} 探索一圈再回来。需要确认总耗时和风险后再拆步保存。",
            "plan": (
                PlanStep(
                    step_id="step:1",
                    action="travel",
                    label=f"前往{location['name']}",
                    options={"destination": location["id"], "pace": "normal"},
                    risk_level="medium",
                ),
                PlanStep(
                    step_id="step:2",
                    action="explore",
                    label=f"探索{location['name']}",
                    options={"target": location["id"], "approach": "careful"},
                    risk_level="medium",
                ),
                PlanStep(
                    step_id="step:3",
                    action="travel",
                    label="返回出发地",
                    options={"destination": current_location_id(conn), "pace": "normal"},
                    risk_level="medium",
                ),
            ),
            "repair_options": (
                RepairOption(
                    id="confirm_round_trip",
                    label="确认往返计划",
                    effect="按 travel + explore + travel 拆步预演并保存",
                ),
                RepairOption(
                    id="travel_only",
                    label=f"只去{location['name']}",
                    action="travel",
                    options={"destination": location["id"], "pace": "normal"},
                    effect="只移动到目的地",
                ),
            ),
        }

    if location and character and has_travel_intent and (has_social_intent or has_find_intent):
        return {
            "kind": "composite",
            "summary": f"前往{location['name']}后与{character['name']}互动。",
            "player_message": f"我理解你想先去 {location['name']}，再找 {character['name']} 互动。需要先确认 travel，再重新预演 social。",
            "plan": (
                PlanStep(
                    step_id="step:1",
                    action="travel",
                    label=f"前往{location['name']}",
                    options={"destination": location["id"], "pace": "normal"},
                    risk_level="medium",
                ),
                PlanStep(
                    step_id="step:2",
                    action="social",
                    label=f"与{character['name']}互动",
                    options={"npc": character["id"], "topic": infer_topic(text), "approach": infer_approach(text)},
                    risk_level="low",
                ),
            ),
            "repair_options": (
                RepairOption(
                    id="travel_then_social",
                    label=f"先去{location['name']}再交谈",
                    action="travel",
                    options={"destination": location["id"], "pace": "normal"},
                    effect="先保存 travel，再预演 social",
                ),
            ),
        }

    if character and (has_social_intent or has_find_intent):
        return {
            "kind": "single",
            "action": "social",
            "options": {
                "npc": character["id"],
                "topic": infer_topic(text),
                "approach": infer_approach(text),
                "user_text": user_text,
            },
        }

    if location and has_travel_intent and (has_gather_intent or has_search_intent or has_explore_intent):
        followup_action = "gather" if gather_target else "explore"
        followup_target = gather_target or explore_target or location
        target_options = {"target": followup_target["id"], "location": location["id"]}
        return {
            "kind": "composite",
            "summary": f"前往{location['name']}后继续处理现场目标。",
            "player_message": f"我理解你想先去 {location['name']}，再处理现场目标。需要先确认 travel，再重新预演后续行动。",
            "plan": (
                PlanStep(
                    step_id="step:1",
                    action="travel",
                    label=f"前往{location['name']}",
                    options={"destination": location["id"], "pace": "normal"},
                    risk_level="medium",
                ),
                PlanStep(
                    step_id="step:2",
                    action=followup_action,
                    label="处理现场目标",
                    options=target_options,
                    risk_level="medium",
                ),
            ),
            "repair_options": (
                RepairOption(
                    id="travel_then_gather",
                    label=f"先去{location['name']}再采集",
                    action="travel",
                    options={"destination": location["id"], "pace": "normal"},
                    effect="先保存 travel，再预演 gather",
                ),
            ),
        }

    if gather_target and (has_gather_intent or has_search_intent):
        return {
            "kind": "single",
            "action": "gather",
            "options": {"target": gather_target["id"], "user_text": user_text},
        }

    if explore_target and (has_explore_intent or has_search_intent):
        return {
            "kind": "single",
            "action": "explore",
            "options": {"target": explore_target["id"], "approach": "careful", "user_text": user_text},
        }

    if location and has_travel_intent:
        return {
            "kind": "single",
            "action": "travel",
            "options": {"destination": location["id"], "pace": "normal", "user_text": user_text},
        }

    if has_craft_intent:
        return {
            "kind": "single",
            "action": "craft",
            "options": {"target": text, "user_text": user_text},
        }

    if has_explore_intent:
        return {
            "kind": "single",
            "action": "explore",
            "options": {"target": location["id"] if location else text, "approach": "careful", "user_text": user_text},
        }

    if has_travel_intent:
        return unresolved_act(
            status="clarify",
            message="我没有匹配到这个目的地。请从当前场景的可行动地点里选择，或补充地点名称。",
            repair_id="clarify_destination",
            label="补充目的地",
            action="travel",
            missing_required=("destination",),
        )

    if has_social_intent:
        return unresolved_act(
            status="clarify",
            message="我没有匹配到要交谈的角色。请改用角色名、别名，或先查看当前场景。",
            repair_id="clarify_npc",
            label="补充交谈对象",
            action="social",
            missing_required=("npc",),
        )

    if has_gather_intent:
        return unresolved_act(
            status="clarify",
            message="我没有匹配到可采集对象。请改用资源名、别名，或先查看当前地点的可行动列表。",
            repair_id="clarify_gather_target",
            label="补充采集对象",
            action="gather",
            missing_required=("target",),
        )

    if has_search_intent or has_explore_intent:
        return unresolved_act(
            status="clarify",
            message="我没有匹配到要寻找或探索的对象。请改用可见对象、线索、地点名称，或明确这是未知线索。",
            repair_id="clarify_search_target",
            label="补充搜索目标",
            action="explore",
            missing_required=("target",),
        )

    return {
        "kind": "single",
        "action": "routine",
        "options": {"task": text, "user_text": user_text},
        "fallback": True,
    }


def unresolved_act(
    *,
    status: UxStatus,
    message: str,
    repair_id: str,
    label: str,
    action: str,
    missing_required: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "kind": "unresolved",
        "action": action,
        "status": status,
        "player_message": message,
        "missing_required": missing_required,
        "errors": errors,
        "repair_options": (
            RepairOption(
                id=repair_id,
                label=label,
                description=message,
                action=action,
                effect="补充信息后重新预演",
                risk_level="none",
                requires_confirmation=False,
            ),
        ),
    }


def composite_inventory_plan(
    text: str,
    user_text: str,
    location: sqlite3.Row | None,
    character: sqlite3.Row | None,
    gather_target: sqlite3.Row | None,
    explore_target: sqlite3.Row | None,
) -> dict[str, Any]:
    followup: PlanStep | None = None
    if location:
        followup = PlanStep(
            step_id="step:2",
            action="travel",
            label=f"前往{location['name']}",
            options={"destination": location["id"], "pace": "normal"},
            risk_level="medium",
        )
    elif character:
        followup = PlanStep(
            step_id="step:2",
            action="social",
            label=f"与{character['name']}互动",
            options={"npc": character["id"], "topic": infer_topic(text), "approach": infer_approach(text)},
            risk_level="low",
        )
    elif gather_target:
        followup = PlanStep(
            step_id="step:2",
            action="gather",
            label=f"处理{gather_target['name']}",
            options={"target": gather_target["id"]},
            risk_level="medium",
        )
    elif explore_target:
        followup = PlanStep(
            step_id="step:2",
            action="explore",
            label=f"探索{explore_target['name']}",
            options={"target": explore_target["id"], "approach": "careful"},
            risk_level="medium",
        )
    plan = [
        PlanStep(
            step_id="step:1",
            action="routine",
            label="盘点库存",
            options={"task": "盘点库存", "user_text": user_text},
            risk_level="none",
        )
    ]
    if followup:
        plan.append(followup)
    return {
        "kind": "composite",
        "summary": "先盘点库存，再继续执行后续行动。",
        "player_message": "我理解这是一个复合行动：先盘点库存，再继续处理后续目标。需要确认拆步后再保存，避免只保存其中一半。",
        "plan": tuple(plan),
        "repair_options": (
            RepairOption(
                id="inventory_only",
                label="只盘点库存",
                action="routine",
                options={"task": "盘点库存", "user_text": user_text},
                effect="只保存低风险库存盘点",
                risk_level="none",
                requires_confirmation=False,
            ),
            RepairOption(
                id="confirm_split_steps",
                label="确认拆步",
                effect="按计划逐步 preview 和保存",
                risk_level="low",
            ),
        ),
    }


def first_visible_entity_in_text(
    conn: sqlite3.Connection,
    text: str,
    entity_type: str | None,
    *,
    preferred_types: tuple[str, ...] = (),
) -> sqlite3.Row | None:
    ensure_visibility_sql_functions(conn)
    visibility_clause = entity_visibility_sql("player", "e")
    subtype_visibility_clause = entity_subtype_visibility_sql("player", "e", "c")
    rows = conn.execute(
        f"""
        select e.id, e.type, e.name, e.summary, e.location_id
        from entities e
        left join clocks c on c.entity_id = e.id
        where {normalized_text_sql("e.status")} = 'active'
          {visibility_clause}
          {subtype_visibility_clause}
        order by length(e.name) desc, e.id
        """
    ).fetchall()
    haystack = text.lower()
    preferred = set(preferred_types)
    candidates: list[tuple[int, sqlite3.Row]] = []
    for row in rows:
        if entity_type and row["type"] != entity_type:
            continue
        labels = [str(row["id"]), str(row["name"])]
        alias_rows = conn.execute("select alias from aliases where entity_id = ?", (row["id"],)).fetchall()
        labels.extend(str(alias["alias"]) for alias in alias_rows)
        score = 0
        for label in labels:
            normalized = label.strip().lower()
            if normalized and normalized in haystack:
                score = max(score, len(normalized))
        if score:
            if preferred and row["type"] in preferred:
                score += 1000
            candidates.append((score, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], str(item[1]["id"])))
    return candidates[0][1]


def infer_topic(text: str) -> str:
    for marker in ("问", "询问", "关于", "聊", "谈"):
        if marker in text:
            tail = text.split(marker, 1)[1].strip()
            if tail:
                return tail[:40]
    return "当前情况"


def infer_approach(text: str) -> str:
    if any(term in text for term in ("低声", "悄悄", "私下")):
        return "低声询问"
    if any(term in text for term in ("威慑", "逼问")):
        return "威慑询问"
    return "直接询问"


def infer_rest_until(text: str) -> str:
    if text_has_any(text, ("早上", "明早", "morning")):
        return "morning"
    if text_has_any(text, ("夜里", "晚上", "night")):
        return "night"
    return "morning"


def infer_random_options(text: str, user_text: str) -> dict[str, Any]:
    options: dict[str, Any] = {"user_text": user_text}
    table_match = TABLE_ID_TEXT_PATTERN.search(text)
    dice_match = DICE_TEXT_PATTERN.search(text)
    if table_match:
        options["table"] = table_match.group(1)
    elif dice_match:
        options["dice"] = dice_match.group(0)
    reason = text.strip()
    if reason:
        options["reason"] = reason[:120]
    return options


def current_location_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("select value from meta where key = 'current_location_id'").fetchone()
    return str(row["value"]) if row else None


def inferred_status(inferred: dict[str, Any]) -> UxStatus:
    value = str(inferred.get("status") or "ready")
    return coerce_status(value)


def coerce_status(value: Any) -> UxStatus:
    value = str(value or "ready")
    if value in {"ready", "needs_confirmation", "clarify", "blocked", "internal_error"}:
        return value  # type: ignore[return-value]
    return "ready"


def summarize_inferred_action(inferred: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": inferred.get("kind"),
        "action": inferred.get("action"),
        "status": inferred.get("status", "ready"),
        "fallback": bool(inferred.get("fallback")),
        "missing_required": list(inferred.get("missing_required", ())),
        "summary": inferred.get("summary"),
    }


def semantic_trace(suggestion: dict[str, Any] | None) -> dict[str, Any] | None:
    if not suggestion:
        return None
    return {
        "mode": suggestion.get("mode"),
        "submode": suggestion.get("submode"),
        "confidence": suggestion.get("confidence"),
        "targets": suggestion.get("targets", []),
        "notes": suggestion.get("notes", []),
    }


def detect_preview_action_mismatch(user_text: str | None, action: str) -> dict[str, Any] | None:
    if not user_text:
        return None
    text = normalize_player_text(user_text).strip()
    action = action.strip()
    if not text or not action:
        return None
    expected = keyword_expected_action(text)
    if expected and expected != action:
        return {
            "severity": "needs_confirmation",
            "expected_action": expected,
            "message": f"source_user_text 更像 `{expected}`，但调用方传入了 `{action}`。请改用 preview_from_text 或确认 action 后重试。",
        }
    if action == "social" and text_has_any(text, ("去", "前往", "下到", "到")) and text_has_any(text, ("问", "询问", "找")):
        return {
            "severity": "warning",
            "expected_action": "composite",
            "message": "这句话可能是 travel + social 组合行动；直接 social 预演前应确认角色已经在同一地点。",
        }
    return None


def keyword_expected_action(text: str) -> str | None:
    if text_has_any(text, CRAFT_INTENT_TERMS):
        return "craft"
    if text_has_any(text, ("采", "采集", "采药", "摘", "收集", "拾取", "捡", "gather", "collect", "harvest")):
        return "gather"
    if text_has_any(text, ("去", "前往", "移动到", "go to", "travel to", "head to")):
        return "travel"
    if text_has_any(text, ("询问", "问", "交谈", "聊", "talk", "ask", "speak")):
        return "social"
    if text_has_any(text, ("睡", "休息", "守夜", "等到明早", "过夜", "rest", "sleep", "wait")):
        return "rest"
    if text_has_any(text, ("探索", "调查", "搜索", "侦查", "inspect", "investigate", "explore", "scout")):
        return "explore"
    if text_has_any(text, ROUTINE_INTENT_TERMS):
        return "routine"
    return None
