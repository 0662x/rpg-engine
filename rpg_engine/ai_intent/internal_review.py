from __future__ import annotations

import sqlite3
from typing import Any

from ..actions import ActionResolverRegistry
from ..ai.provider import AIHelperResult, run_ai_helper_json
from ..ai.tasks import AIHelperTask
from ..campaign import Campaign
from .normalization import normalize_internal_intent_review
from .prompts import build_internal_intent_review_prompt, prompt_safe_value
from .types import IntentCandidate


def collect_internal_intent_candidate(
    campaign: Campaign,
    conn: sqlite3.Connection,
    user_text: str,
    *,
    external_candidate: IntentCandidate | dict[str, Any] | None = None,
    rule_candidate: IntentCandidate | dict[str, Any] | None = None,
    safety_notes: tuple[str, ...] = (),
    visible_entities: list[dict[str, Any]] | None = None,
    backend: str,
    provider: str,
    model: str,
    timeout: int,
    base_url: str = "",
    api_key_env: str = "",
    fallback_backend: str = "off",
    view: str = "player",
    execution_class: str = "foreground",
    registry: ActionResolverRegistry | None = None,
) -> AIHelperResult:
    del campaign
    parser_user_text = str(prompt_safe_value(conn, user_text, view=view))
    prompt = build_internal_intent_review_prompt(
        conn,
        user_text,
        external_candidate=external_candidate,
        rule_candidate=rule_candidate,
        safety_notes=safety_notes,
        visible_entities=visible_entities,
        view=view,
        registry=registry,
    )
    task = AIHelperTask(
        name="internal_intent_review",
        prompt=prompt,
        output_schema="internal_intent_review.schema.json",
        parser=lambda value: normalize_internal_intent_review(
            value,
            user_text=parser_user_text,
            registry=registry,
        ),
        execution_class=execution_class,
    )
    return run_ai_helper_json(
        task,
        backend=backend,
        provider=provider,
        model=model,
        timeout=timeout,
        base_url=base_url or None,
        api_key_env=api_key_env or None,
        fallback_backend=fallback_backend,
    )
