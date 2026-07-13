from __future__ import annotations

import json
import re
from typing import Any

from ..ai.tasks import AIHelperTask
from ..ai.provider import public_ai_helper_result_dict, run_ai_helper_json
from ..db import entity_subtype_visibility_sql, get_meta
from ..redaction import redact_hidden_entity_id_substrings, redact_hidden_entity_refs
from ..visibility import (
    can_read_hidden,
    context_visibility_view,
    ensure_visibility_sql_functions,
    entity_not_archived_sql,
    entity_visibility_sql,
    normalized_text_sql,
)
from .rendering import trim_inline
from .resolution import apply_semantic_entity_hints
from ..actions import ActionResolverRegistry, get_default_action_registry


def collect_semantic_suggestion(state: Any) -> None:
    if state.semantic_ai == "off":
        return

    injected_registry = getattr(state, "action_registry", None)
    action_registry = injected_registry if injected_registry is not None else get_default_action_registry()
    prompt = build_semantic_prompt(state)
    task = AIHelperTask(
        name="semantic",
        prompt=prompt,
        output_schema="semantic_suggestion.schema.json",
        parser=lambda value: normalize_semantic_suggestion(value, registry=action_registry),
    )
    result = run_ai_helper_json(
        task,
        backend=state.semantic_ai,
        provider=state.semantic_provider,
        model=state.semantic_model,
        timeout=state.semantic_timeout,
    )
    public_result = public_ai_helper_result_dict(result)
    state.semantic_audit = public_result["audit"]
    if not result.ok or result.parsed is None:
        state.semantic_error = public_result["error"] or "semantic ai returned no usable suggestion"
        return
    state.semantic_suggestion = result.parsed
    apply_semantic_entity_hints(state)


def build_semantic_prompt(state: Any) -> str:
    meta = get_meta(state.conn)
    view = getattr(state, "visibility_view", None) or context_visibility_view(getattr(state, "mode", None))
    should_redact = not can_read_hidden(view)
    user_text = (
        str(
            redact_hidden_entity_id_substrings(
                state.conn,
                redact_hidden_entity_refs(state.conn, state.user_text, drop_empty=False),
                drop_empty=False,
            )
        )
        if should_redact
        else state.user_text
    )
    hit_rows = [
        {
            "id": hit.id,
            "type": hit.type,
            "name": hit.name,
            "reason": hit.reason,
        }
        for hit in state.entity_hits[:8]
    ]
    if should_redact:
        hit_rows = redact_hidden_entity_id_substrings(
            state.conn,
            redact_hidden_entity_refs(state.conn, hit_rows, drop_empty=False) or [],
            drop_empty=False,
        )
    hit_lines = [
        f"- {hit['id']} | {hit['type']} | {hit['name']} | {hit['reason']}"
        for hit in hit_rows
    ]
    current_location = semantic_current_location_label(state, meta.get("current_location_id", "unknown"))
    injected_registry = getattr(state, "action_registry", None)
    action_registry = injected_registry if injected_registry is not None else get_default_action_registry()
    action_names = action_registry.names()
    action_lines = [
        f"- {spec.name}: labels={','.join(spec.semantic_labels) or '-'}; keywords={','.join(spec.keywords) or '-'}"
        for spec in action_registry.all()
    ]
    allowed_submodes = ["entity", "scene", "context", *action_names, "unknown"]
    submode_union = "|".join(allowed_submodes)
    return "\n".join(
        [
            "你是文字冒险游戏的上下文语义判断器。只输出一个 JSON 对象，不要 Markdown，不要解释。",
            "任务：根据玩家输入判断意图、子类型、目标名和可能缺失的信息。不要创造新事实；不知道就写 unknown 或空数组。",
            "",
            "允许的 mode：query, action, unknown",
            f"允许的 submode：{', '.join(allowed_submodes)}",
            "confidence 只能是 high, medium, low",
            "",
            "输出格式：",
            f'{{"mode":"query|action|unknown","submode":"{submode_union}","targets":["目标名"],"entities_mentioned":["实体名或ID"],"missing_confirmations":["需要玩家补充的短句"],"notes":["短句"],"confidence":"high|medium|low"}}',
            "",
            f"玩家输入：{user_text}",
            f"规则初判：{state.mode}:{state.submode}",
            f"当前位置：{current_location}",
            "已注册行动类型：",
            "\n".join(action_lines) if action_lines else "- 无",
            "已由规则命中的实体：",
            "\n".join(hit_lines) if hit_lines else "- 无",
        ]
    )


def semantic_current_location_label(state: Any, location_id: str) -> str:
    view = getattr(state, "visibility_view", None) or context_visibility_view(getattr(state, "mode", None))
    if can_read_hidden(view):
        return location_id
    ensure_visibility_sql_functions(state.conn)
    visibility_clause = entity_visibility_sql(view, "e")
    subtype_visibility_clause = entity_subtype_visibility_sql(view, "e", "c")
    row = state.conn.execute(
        f"""
        select e.id
        from entities e
        left join clocks c on c.entity_id = e.id
        where e.id = ?
          and {normalized_text_sql("e.type")} = 'location'
          and {entity_not_archived_sql("e")}
          {visibility_clause}
          {subtype_visibility_clause}
        """,
        (location_id,),
    ).fetchone()
    return location_id if row else "当前地点不可见或不存在"


def parse_semantic_json(text: str) -> Any:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.S)
    if fence:
        stripped = fence.group(1)
    elif "{" in stripped and "}" in stripped:
        stripped = stripped[stripped.find("{") : stripped.rfind("}") + 1]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def normalize_semantic_suggestion(
    value: dict[str, Any],
    *,
    registry: ActionResolverRegistry | None = None,
) -> dict[str, Any]:
    action_names = set((registry if registry is not None else get_default_action_registry()).names())
    return {
        "mode": normalize_choice(value.get("mode"), {"query", "action", "unknown"}, "unknown"),
        "submode": normalize_choice(
            value.get("submode"),
            {"entity", "scene", "context", "unknown", *action_names},
            "unknown",
        ),
        "targets": normalize_string_list(value.get("targets"), limit=8),
        "entities_mentioned": normalize_string_list(value.get("entities_mentioned"), limit=8),
        "missing_confirmations": normalize_string_list(value.get("missing_confirmations"), limit=6),
        "notes": normalize_string_list(value.get("notes"), limit=6),
        "confidence": normalize_choice(value.get("confidence"), {"high", "medium", "low"}, "low"),
    }


def normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value).strip().lower() if value is not None else ""
    return text if text in allowed else default


def normalize_string_list(value: Any, *, limit: int) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = trim_inline(str(item).strip(), 80)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result
