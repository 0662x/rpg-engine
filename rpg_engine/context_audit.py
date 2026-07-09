from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import utc_now


def ensure_context_audit_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists context_runs (
          id text primary key,
          created_at text not null,
          user_text text not null,
          mode text not null,
          submode text,
          budget_limit integer not null,
          estimated_tokens integer not null,
          allow_proceed integer not null,
          confidence text not null,
          missing_required_json text not null,
          needs_confirmation_json text not null,
          output_json text not null
        );

        create table if not exists context_items (
          context_run_id text not null,
          item_id text not null,
          item_kind text not null,
          source text not null,
          reason text not null,
          priority integer not null,
          estimated_tokens integer,
          included integer not null,
          omitted_reason text,
          depth integer,
          primary key (context_run_id, item_id, source),
          foreign key(context_run_id) references context_runs(id) on delete cascade
        );

        create index if not exists idx_context_runs_created on context_runs(created_at);
        """
    )


def write_context_audit(
    conn: sqlite3.Connection,
    result: Any,
    *,
    run_id: str | None = None,
) -> str:
    ensure_context_audit_tables(conn)
    created_at = utc_now()
    audit_id = run_id or f"context:{created_at.replace(':', '').replace('-', '').replace('.', '')}"
    result.request["context_audit_run_id"] = audit_id
    request = result.request
    completeness = result.completeness
    budget = result.budget

    conn.execute(
        """
        insert into context_runs
        (id, created_at, user_text, mode, submode, budget_limit, estimated_tokens,
         allow_proceed, confidence, missing_required_json, needs_confirmation_json, output_json)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
          created_at=excluded.created_at,
          user_text=excluded.user_text,
          mode=excluded.mode,
          submode=excluded.submode,
          budget_limit=excluded.budget_limit,
          estimated_tokens=excluded.estimated_tokens,
          allow_proceed=excluded.allow_proceed,
          confidence=excluded.confidence,
          missing_required_json=excluded.missing_required_json,
          needs_confirmation_json=excluded.needs_confirmation_json,
          output_json=excluded.output_json
        """,
        (
            audit_id,
            created_at,
            str(request.get("user_text", "")),
            str(request.get("mode", "")),
            request.get("submode"),
            int(budget.get("limit", 0)),
            int(budget.get("estimated", 0)),
            1 if completeness.get("allow_proceed") else 0,
            str(completeness.get("confidence", "")),
            json.dumps(completeness.get("missing_required", []), ensure_ascii=False, sort_keys=True),
            json.dumps(completeness.get("needs_user_confirmation", []), ensure_ascii=False, sort_keys=True),
            result.to_json_text(),
        ),
    )
    conn.execute("delete from context_items where context_run_id = ?", (audit_id,))
    seen_item_keys: set[tuple[str, str]] = set()
    for item in result.loaded_items:
        source = str(item.get("source", "loaded"))
        item_id = context_item_audit_id(item, source, seen_item_keys)
        conn.execute(
            """
            insert into context_items
            (context_run_id, item_id, item_kind, source, reason, priority, estimated_tokens,
             included, omitted_reason, depth)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                item_id,
                str(item.get("kind", "")),
                source,
                str(item.get("reason", "")),
                int(item.get("priority", 0)),
                None,
                1,
                None,
                item.get("depth"),
            ),
        )
    for item in result.omitted_items:
        source = str(item.get("source", "omitted"))
        item_id = context_item_audit_id(item, source, seen_item_keys)
        conn.execute(
            """
            insert into context_items
            (context_run_id, item_id, item_kind, source, reason, priority, estimated_tokens,
             included, omitted_reason, depth)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                item_id,
                str(item.get("kind", "")),
                source,
                str(item.get("reason", "")),
                int(item.get("priority", 0)),
                item.get("estimated_tokens"),
                0,
                str(item.get("reason", "")),
                item.get("depth"),
            ),
        )
    conn.commit()
    return audit_id


def context_item_audit_id(
    item: dict[str, Any],
    source: str,
    seen_item_keys: set[tuple[str, str]],
) -> str:
    item_id = str(item.get("id"))
    key = (item_id, source)
    if key not in seen_item_keys:
        seen_item_keys.add(key)
        return item_id

    kind = str(item.get("kind") or "item")
    base = f"audit:{kind}:{item_id}"
    candidate = base
    index = 2
    while (candidate, source) in seen_item_keys:
        candidate = f"{base}:{index}"
        index += 1
    seen_item_keys.add((candidate, source))
    return candidate
