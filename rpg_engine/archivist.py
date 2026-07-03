from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .ai import AIHelperTask, run_ai_helper_json
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_ARCHIVIST_TIMEOUT_SECONDS
from .ai.schemas import ArchivistSuggestion, normalize_archivist_suggestion
from .db import get_meta, utc_now
from .proposal_queue import ProposalRecord, create_proposal
from .render import parse_json


@dataclass(frozen=True)
class ArchivistSuggestResult:
    suggestion: ArchivistSuggestion
    ai_status: str
    errors: tuple[str, ...] = ()
    audit: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ai_status": self.ai_status,
            "errors": list(self.errors),
            "suggestion": self.suggestion.to_dict(),
            "audit": self.audit,
        }

    def render(self) -> str:
        data = self.to_dict()
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class ArchivistWorkflowResult:
    turn_id: str
    suggestion_id: str | None
    suggest_result: ArchivistSuggestResult
    proposals: tuple[ProposalRecord, ...] = ()
    stored: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "suggestion_id": self.suggestion_id,
            "stored": self.stored,
            "suggest_result": self.suggest_result.to_dict(),
            "proposal_ids": [record.id for record in self.proposals],
            "proposals": [record.to_dict() for record in self.proposals],
        }

    def render(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def suggest_archivist(
    conn: sqlite3.Connection,
    *,
    turn_id: str | None = None,
    ai: str = "off",
    provider: str = DEFAULT_AI_PROVIDER,
    model: str = DEFAULT_AI_MODEL,
    timeout: int = DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
) -> ArchivistSuggestResult:
    turn = latest_turn(conn, turn_id)
    if not turn:
        return ArchivistSuggestResult(ArchivistSuggestion(), ai_status="failed", errors=("missing turn",))
    events = events_for_turn(conn, turn["id"])
    if ai == "off":
        return ArchivistSuggestResult(deterministic_archivist(turn, events), ai_status="off")
    task = AIHelperTask(
        name="archivist",
        output_schema="archivist.schema.json",
        prompt=build_archivist_prompt(conn, turn, events),
        parser=lambda value: normalize_archivist_suggestion(value).to_dict(),
    )
    result = run_ai_helper_json(task, backend=ai, provider=provider, model=model, timeout=timeout)
    if not result.ok or result.parsed is None:
        return ArchivistSuggestResult(
            deterministic_archivist(turn, events),
            ai_status="failed",
            errors=(result.error or "AI archivist failed; returned deterministic fallback",),
            audit=result.audit,
        )
    return ArchivistSuggestResult(
        normalize_archivist_suggestion(result.parsed),
        ai_status="ok",
        audit=result.audit,
    )


def run_archivist_workflow(
    conn: sqlite3.Connection,
    *,
    turn_id: str | None = None,
    ai: str = "off",
    provider: str = DEFAULT_AI_PROVIDER,
    model: str = DEFAULT_AI_MODEL,
    timeout: int = DEFAULT_ARCHIVIST_TIMEOUT_SECONDS,
    enqueue: bool = True,
) -> ArchivistWorkflowResult:
    turn = latest_turn(conn, turn_id)
    if not turn:
        result = ArchivistSuggestResult(ArchivistSuggestion(), ai_status="failed", errors=("missing turn",))
        return ArchivistWorkflowResult(
            turn_id=turn_id or "",
            suggestion_id=None,
            suggest_result=result,
            proposals=(),
            stored=False,
        )
    resolved_turn_id = str(turn["id"])
    result = suggest_archivist(
        conn,
        turn_id=resolved_turn_id,
        ai=ai,
        provider=provider,
        model=model,
        timeout=timeout,
    )
    suggestion_id, stored = store_archivist_suggestion(conn, turn_id=resolved_turn_id, result=result)
    proposals: list[ProposalRecord] = []
    if enqueue and stored:
        proposals.extend(enqueue_archivist_suggestions(conn, turn_id=resolved_turn_id, suggestion_id=suggestion_id, result=result))
    return ArchivistWorkflowResult(
        turn_id=resolved_turn_id,
        suggestion_id=suggestion_id,
        suggest_result=result,
        proposals=tuple(proposals),
        stored=stored,
    )


def store_archivist_suggestion(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    result: ArchivistSuggestResult,
) -> tuple[str, bool]:
    ensure_archivist_tables(conn)
    suggestion_id = f"archivist:{turn_id.replace(':', '-')}"
    existing = conn.execute("select id from archivist_suggestions where id = ?", (suggestion_id,)).fetchone()
    if existing:
        return suggestion_id, False
    now = utc_now()
    conn.execute(
        """
        insert into archivist_suggestions
        (id, turn_id, ai_status, suggestion_json, audit_json, status, created_at, updated_at)
        values (?, ?, ?, ?, ?, 'suggested', ?, ?)
        """,
        (
            suggestion_id,
            turn_id,
            result.ai_status,
            json.dumps(result.suggestion.to_dict(), ensure_ascii=False, sort_keys=True),
            json.dumps(result.audit or {}, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )
    return suggestion_id, True


def enqueue_archivist_suggestions(
    conn: sqlite3.Connection,
    *,
    turn_id: str,
    suggestion_id: str,
    result: ArchivistSuggestResult,
) -> list[ProposalRecord]:
    suggestion = result.suggestion.to_dict()
    proposals: list[ProposalRecord] = []
    proposal_specs = [
        ("memory_candidates", "memory_update", "low", "Archivist memory candidate needs review."),
        ("entity_alias_suggestions", "alias_suggestion", "low", "Archivist alias suggestion needs review."),
        ("unresolved_leads", "memory_update", "medium", "Archivist unresolved lead should remain advisory until reviewed."),
        ("possible_contradictions", "memory_update", "high", "Archivist contradiction warning needs review."),
        ("review_required", "memory_update", "high", "Archivist marked this item for review."),
    ]
    for field, kind, risk, reason in proposal_specs:
        for index, item in enumerate(suggestion.get(field, []) if isinstance(suggestion.get(field), list) else []):
            if not isinstance(item, dict):
                continue
            payload = {
                "source": "archivist",
                "archivist_suggestion_id": suggestion_id,
                "turn_id": turn_id,
                "field": field,
                "index": index,
                "candidate": item,
                "advisory": True,
            }
            proposals.append(
                create_proposal(
                    conn,
                    kind=kind,
                    payload=payload,
                    validation={"ok": True, "errors": [], "warnings": [reason]},
                    source_turn_id=turn_id,
                    status="needs_review",
                    risk_level=risk,
                    review_reason=reason,
                )
            )
    return proposals


def latest_turn(conn: sqlite3.Connection, turn_id: str | None) -> sqlite3.Row | None:
    if turn_id:
        return conn.execute("select * from turns where id = ?", (turn_id,)).fetchone()
    return conn.execute("select * from turns order by created_at desc, id desc limit 1").fetchone()


def events_for_turn(conn: sqlite3.Connection, turn_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select id, turn_id, type, title, summary, payload_json, source, created_at
        from events
        where turn_id = ?
        order by id
        """,
        (turn_id,),
    ).fetchall()


def ensure_archivist_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists archivist_suggestions (
          id text primary key,
          turn_id text,
          ai_status text not null,
          suggestion_json text not null,
          audit_json text not null default '{}',
          status text not null default 'suggested',
          created_at text not null,
          updated_at text not null
        )
        """
    )
    conn.execute(
        "create index if not exists idx_archivist_suggestions_turn on archivist_suggestions(turn_id, status, created_at)"
    )


def deterministic_archivist(turn: sqlite3.Row, events: list[sqlite3.Row]) -> ArchivistSuggestion:
    unresolved: list[dict[str, Any]] = []
    review_required: list[dict[str, Any]] = []
    hints: list[str] = []
    for row in events:
        payload = parse_json(row["payload_json"], {})
        if isinstance(payload, dict) and payload.get("needs_gm_resolution"):
            lead = {
                "event_id": row["id"],
                "kind": payload.get("palette_kind") or payload.get("target_kind") or row["type"],
                "palette_id": payload.get("palette_id"),
                "summary": row["summary"],
            }
            unresolved.append(lead)
            hints.append(str(payload.get("palette_id") or payload.get("target_query") or row["title"]))
        if isinstance(payload, dict) and payload.get("high_impact"):
            review_required.append({"event_id": row["id"], "reason": "high_impact payload"})
    summary = str(turn["summary"] or "")
    if not summary and events:
        summary = "；".join(str(row["summary"]) for row in events[:3])
    return ArchivistSuggestion(
        turn_summary=summary,
        memory_candidates=[],
        entity_alias_suggestions=[],
        unresolved_leads=unresolved[:8],
        possible_contradictions=[],
        next_context_hints=[item for item in dict.fromkeys(hints) if item][:8],
        review_required=review_required[:8],
        advisory=True,
    )


def build_archivist_prompt(conn: sqlite3.Connection, turn: sqlite3.Row, events: list[sqlite3.Row]) -> str:
    meta = get_meta(conn)
    event_lines = []
    for row in events[:12]:
        payload = parse_json(row["payload_json"], {})
        safe_payload = {
            key: payload.get(key)
            for key in (
                "target_id",
                "target_query",
                "palette_id",
                "palette_kind",
                "palette_status",
                "needs_gm_resolution",
            )
            if isinstance(payload, dict) and key in payload
        }
        event_lines.append(f"- {row['id']} | {row['type']} | {row['summary']} | {safe_payload}")
    return "\n".join(
        [
            "你是文字 RPG 的后台 Archivist。只输出 JSON，不要 Markdown。",
            "你只能提出结构化建议，不能写事实，不能确认隐藏信息，不能改库存、地点、关系、进度钟或实体。",
            "所有建议必须是 advisory。",
            "",
            "输出格式：",
            '{"turn_summary":"短摘要","memory_candidates":[],"entity_alias_suggestions":[],"unresolved_leads":[],"possible_contradictions":[],"next_context_hints":[],"review_required":[]}',
            "",
            f"turn_id: {turn['id']}",
            f"user_text: {turn['user_text']}",
            f"intent: {turn['intent']}",
            f"summary: {turn['summary']}",
            f"current_location_id: {meta.get('current_location_id', '')}",
            "events:",
            "\n".join(event_lines) if event_lines else "- 无",
        ]
    )
