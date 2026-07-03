from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .ai import AIHelperTask, run_ai_helper_json
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_REFLECTION_TIMEOUT_SECONDS
from .campaign import Campaign
from .memory import as_text_list
from .render import parse_json


@dataclass(frozen=True)
class ReflectionDraft:
    subject_id: str
    title: str
    summary: str
    key_points: list[str]
    source_event_ids: list[str]
    errors: list[str]
    ai_status: str = "off"

    def render(self) -> str:
        lines = [
            "# Reflection Draft",
            "",
            f"- subject: `{self.subject_id}`",
            f"- title: {self.title}",
            f"- ai_status: `{self.ai_status}`",
            f"- valid: `{'yes' if not self.errors else 'no'}`",
            "",
            "## Summary",
            "",
            self.summary or "无",
            "",
            "## Key Points",
        ]
        lines.extend(f"- {item}" for item in self.key_points or ["无"])
        lines.extend(["", "## Source Events"])
        lines.extend(f"- `{item}`" for item in self.source_event_ids or ["无"])
        if self.errors:
            lines.extend(["", "## Errors"])
            lines.extend(f"- {item}" for item in self.errors)
        lines.extend(
            [
                "",
                "## Import Candidate",
                "",
                "```json",
                json.dumps(
                    {
                        "subject_id": self.subject_id,
                        "title": self.title,
                        "summary": self.summary,
                        "key_points": self.key_points,
                        "source_event_ids": self.source_event_ids,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                "```",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"


def draft_reflection(
    campaign: Campaign,
    conn: sqlite3.Connection,
    *,
    subject_id: str,
    ai: str = "off",
    model: str = DEFAULT_AI_MODEL,
    provider: str = DEFAULT_AI_PROVIDER,
    timeout: int = DEFAULT_REFLECTION_TIMEOUT_SECONDS,
) -> ReflectionDraft:
    del campaign
    subject = conn.execute("select * from entities where id = ?", (subject_id,)).fetchone()
    if not subject:
        return ReflectionDraft(subject_id, "", "", [], [], [f"missing subject: {subject_id}"])
    events = related_events(conn, subject_id, subject["name"], limit=8)
    allowed_event_ids = [row["id"] for row in events]
    if ai == "hermes":
        draft = ai_reflection(subject, events, model=model, provider=provider, timeout=timeout)
        return validate_reflection_draft(draft, subject, allowed_event_ids, ai_status="ok" if draft else "failed")
    if ai != "off":
        return ReflectionDraft(subject_id, "", "", [], [], [f"unsupported ai backend: {ai}"], ai_status="failed")
    return deterministic_reflection(subject, events)


def deterministic_reflection(subject: sqlite3.Row, events: list[sqlite3.Row]) -> ReflectionDraft:
    details = parse_json(subject["details_json"], {})
    points = [f"当前摘要：{subject['summary']}"]
    if isinstance(details, dict):
        for key in ["evidence", "last_activity", "known_traits", "unknowns", "contact_rules", "relationship_axes", "next_steps", "risks"]:
            if key in details:
                points.append(f"{key}: {format_value(details[key])}")
    points.extend(f"{row['title']}：{row['summary']}" for row in events[:4])
    errors = [] if events else ["no source events found; draft is current-state summary, not event-cited reflection"]
    return ReflectionDraft(
        subject_id=subject["id"],
        title=f"{subject['name']} 反思草案",
        summary=trim("；".join(points[:3]), 320),
        key_points=[trim(item, 220) for item in points[:8]],
        source_event_ids=[row["id"] for row in events],
        errors=errors,
        ai_status="off",
    )


def ai_reflection(
    subject: sqlite3.Row,
    events: list[sqlite3.Row],
    *,
    model: str,
    provider: str,
    timeout: int,
) -> dict[str, Any] | None:
    event_lines = [
        f"- {row['id']} | {row['turn_id']} | {row['title']} | {row['summary']}"
        for row in events
    ]
    prompt = "\n".join(
        [
            "你是文字 RPG 的长期反思生成器。只输出 JSON，不要 Markdown。",
            "必须只依据给定 subject 和 source events；不能创造新事实。",
            "source_event_ids 只能从给定事件 ID 中选择，至少 1 个。",
            "",
            "输出格式：",
            '{"title":"短标题","summary":"不超过160字","key_points":["要点"],"source_event_ids":["event:000001:001"]}',
            "",
            f"subject_id: {subject['id']}",
            f"name: {subject['name']}",
            f"type: {subject['type']}",
            f"summary: {subject['summary']}",
            "events:",
            "\n".join(event_lines) if event_lines else "- 无",
        ]
    )
    task = AIHelperTask(name="reflection", prompt=prompt, output_schema="reflection_draft.schema.json")
    result = run_ai_helper_json(
        task,
        backend="hermes",
        provider=provider,
        model=model,
        timeout=timeout,
    )
    return result.parsed if result.ok else None


def validate_reflection_draft(
    draft: dict[str, Any] | None,
    subject: sqlite3.Row,
    allowed_event_ids: list[str],
    *,
    ai_status: str,
) -> ReflectionDraft:
    if not draft:
        fallback = deterministic_reflection(subject, [])
        return ReflectionDraft(
            subject_id=fallback.subject_id,
            title=fallback.title,
            summary=fallback.summary,
            key_points=fallback.key_points,
            source_event_ids=fallback.source_event_ids,
            errors=["AI reflection failed; returned deterministic fallback"],
            ai_status=ai_status,
        )
    errors: list[str] = []
    title = str(draft.get("title") or f"{subject['name']} AI 反思草案").strip()
    summary = str(draft.get("summary") or "").strip()
    key_points = as_text_list(draft.get("key_points", []))[:8]
    source_event_ids = as_text_list(draft.get("source_event_ids", []))
    allowed = set(allowed_event_ids)
    if not summary:
        errors.append("summary is required")
    if not key_points:
        errors.append("key_points is required")
    if not source_event_ids:
        errors.append("source_event_ids must cite at least one event")
    for event_id in source_event_ids:
        if event_id not in allowed:
            errors.append(f"source_event_ids contains non-allowed event: {event_id}")
    return ReflectionDraft(
        subject_id=subject["id"],
        title=trim(title, 80),
        summary=trim(summary, 320),
        key_points=[trim(item, 220) for item in key_points],
        source_event_ids=source_event_ids,
        errors=errors,
        ai_status=ai_status,
    )


def related_events(conn: sqlite3.Connection, subject_id: str, name: str, *, limit: int) -> list[sqlite3.Row]:
    like_id = f"%{subject_id}%"
    like_name = f"%{name}%"
    return conn.execute(
        """
        select id, turn_id, type, title, summary, game_time, payload_json, created_at
        from events
        where payload_json like ?
           or summary like ?
           or title like ?
        order by created_at desc, id desc
        limit ?
        """,
        (like_id, like_name, like_name, limit),
    ).fetchall()


def format_value(value: Any) -> str:
    if isinstance(value, list):
        return "；".join(format_value(item) for item in value[:4])
    if isinstance(value, dict):
        return "；".join(f"{key}={format_value(item)}" for key, item in list(value.items())[:4])
    return str(value)


def trim(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"
