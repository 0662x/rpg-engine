from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import get_meta
from .delta_schema import validate_delta_schema
from .response_lint import load_response_text, section_text
from .write_guard import add_generated_write_guards


HIGH_RISK_TERMS = [
    "攻击",
    "开火",
    "射",
    "爆炸",
    "杀",
    "死亡",
    "过夜",
    "离开",
    "扣除",
    "失去",
    "受伤",
    "关系恶化",
    "进度钟",
]


@dataclass(frozen=True)
class DeltaDraftResult:
    delta: dict[str, Any]
    warnings: list[str]
    errors: list[str]

    def render(self) -> str:
        lines = [
            "# Delta Draft",
            "",
            f"- valid: `{'yes' if not self.errors else 'no'}`",
            "",
            "## Warnings",
        ]
        lines.extend(f"- {item}" for item in self.warnings or ["无"])
        if self.errors:
            lines.extend(["", "## Errors"])
            lines.extend(f"- {item}" for item in self.errors)
        lines.extend(["", "## Delta", "", "```json", json.dumps(self.delta, ensure_ascii=False, indent=2, sort_keys=True), "```"])
        return "\n".join(lines).rstrip() + "\n"


def draft_delta_from_response(
    conn: sqlite3.Connection,
    *,
    user_text: str,
    response_text: str,
    intent: str = "assistant_draft",
) -> DeltaDraftResult:
    meta = get_meta(conn)
    action_result = section_text(response_text, "行动结果")
    state_changes = parse_state_changes(response_text)
    summary = summarize_response(action_result or response_text)
    delta = {
        "user_text": user_text,
        "intent": intent,
        "changed": True,
        "summary": summary,
        "game_time_before": meta.get("current_time_block", ""),
        "game_time_after": meta.get("current_time_block", ""),
        "location_before": meta.get("current_location_id", ""),
        "location_after": meta.get("current_location_id", ""),
        "events": [
            {
                "type": intent,
                "title": state_changes.get("title") or "AI 回复草案事件",
                "summary": summary,
                "payload": {
                    "state_changes": state_changes.get("rows", []),
                    "draft_source": "response_delta_draft",
                    "needs_gm_review": True,
                },
                "source": "response_delta_draft",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }
    apply_obvious_meta(delta, state_changes, meta)
    add_generated_write_guards(conn, delta, prefix="response-draft")
    warnings = risk_warnings(user_text + "\n" + response_text, state_changes)
    errors = validate_delta_schema(delta, conn)
    return DeltaDraftResult(delta=delta, warnings=warnings, errors=errors)


def load_and_draft_delta(
    conn: sqlite3.Connection,
    *,
    user_text: str,
    response_file: str | Path | None,
    response_text: str | None,
    intent: str,
) -> DeltaDraftResult:
    text = load_response_text(response_file, response_text)
    return draft_delta_from_response(conn, user_text=user_text, response_text=text, intent=intent)


def parse_state_changes(response_text: str) -> dict[str, Any]:
    text = section_text(response_text, "状态变化")
    rows: list[dict[str, str]] = []
    title = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"类型", "项目"}:
            continue
        rows.append({"type": cells[0], "change": cells[1]})
        if not title and cells[0] not in {"无", ""}:
            title = f"{cells[0]}变化"
    return {"title": title, "rows": rows}


def summarize_response(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    clean = re.sub(r"[|#`*_]", "", clean).strip()
    if not clean:
        return "AI 回复草案，需 GM 复核。"
    parts = re.split(r"[。！？.!?]", clean)
    summary = parts[0].strip() or clean
    return summary[:180]


def apply_obvious_meta(delta: dict[str, Any], state_changes: dict[str, Any], meta: dict[str, str]) -> None:
    for row in state_changes.get("rows", []):
        kind = row.get("type", "")
        change = row.get("change", "")
        entity_id_match = re.search(r"`?(loc:[A-Za-z0-9_.-]+)`?", change)
        if "位置" in kind and entity_id_match:
            delta["location_after"] = entity_id_match.group(1)
            delta.setdefault("meta", {})["current_location_id"] = entity_id_match.group(1)
        if "时间" in kind and change and "无" not in change:
            delta["game_time_after"] = change
            delta.setdefault("meta", {})["current_time_block"] = change
    delta.setdefault("location_after", meta.get("current_location_id", ""))


def risk_warnings(text: str, state_changes: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for term in HIGH_RISK_TERMS:
        if term in text:
            warnings.append(f"高风险词命中：{term}；保存前需要 GM 复核。")
    if state_changes.get("rows") and not any(row.get("type") == "无" for row in state_changes["rows"]):
        warnings.append("检测到状态变化表；保存前必须确认 delta 与回复逐项一致。")
    if not state_changes.get("rows"):
        warnings.append("未解析到状态变化表；delta 只能作为低可信草案。")
    return dedupe(warnings)


def check_delta_response_consistency(delta: dict[str, Any], response_text: str) -> list[str]:
    warnings: list[str] = []
    summary = str(delta.get("summary", ""))
    if summary and summary not in response_text:
        warnings.append("delta.summary is not directly present in response text")
    if delta.get("tick_clocks") and "进度钟" not in response_text:
        warnings.append("delta ticks clocks but response does not mention 进度钟")
    if delta.get("upsert_entities") and not any(term in response_text for term in ["新信息", "状态变化", "发现"]):
        warnings.append("delta upserts entities but response lacks 新信息/发现/状态变化 wording")
    meta = delta.get("meta", {})
    if isinstance(meta, dict) and meta.get("current_location_id") and str(meta["current_location_id"]) not in response_text:
        warnings.append("delta changes current_location_id but response does not mention the target location id")
    return warnings


def render_delta_diff(conn: sqlite3.Connection, delta: dict[str, Any]) -> str:
    meta = get_meta(conn)
    lines = ["# Delta Diff Preview", "", "## Meta", "", "| 字段 | 当前 | Delta |", "|------|------|-------|"]
    for key in ["current_time_block", "current_location_id", "current_turn_id"]:
        current = meta.get(key, "")
        proposed = delta.get("meta", {}).get(key, current) if isinstance(delta.get("meta"), dict) else current
        if key == "current_turn_id":
            proposed = delta.get("turn_id", "auto")
        lines.append(f"| {key} | {current} | {proposed} |")
    lines.extend(["", "## Events", ""])
    for event in delta.get("events", []):
        lines.append(f"- {event.get('type', 'note')}：{event.get('title', '')} - {event.get('summary', '')}")
    lines.extend(["", "## Clock Ticks", ""])
    if delta.get("tick_clocks"):
        for item in delta["tick_clocks"]:
            row = conn.execute(
                "select e.name, c.segments_filled, c.segments_total from clocks c join entities e on e.id=c.entity_id where c.entity_id=?",
                (str(item.get("id")),),
            ).fetchone()
            current = f"{row['segments_filled']}/{row['segments_total']}" if row else "missing"
            lines.append(f"- `{item.get('id')}` {current} -> delta {item.get('delta')}")
    else:
        lines.append("- 无")
    lines.extend(["", "## Upsert Entities", ""])
    for entity in delta.get("upsert_entities", []):
        lines.append(f"- `{entity.get('id')}` {entity.get('name')} ({entity.get('type')})")
    if not delta.get("upsert_entities"):
        lines.append("- 无")
    return "\n".join(lines).rstrip() + "\n"


def render_consistency_report(warnings: list[str]) -> str:
    lines = ["OK" if not warnings else "WARN"]
    if warnings:
        lines.append("")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines) + "\n"


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
