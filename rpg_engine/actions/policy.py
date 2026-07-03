from __future__ import annotations

import re
import sqlite3


def first_matching_clock(conn: sqlite3.Connection, terms: list[str]) -> sqlite3.Row | None:
    rows = matching_clock_rows(conn, terms, limit=1)
    return rows[0] if rows else None


def matching_clock_rows(conn: sqlite3.Connection, terms: list[str], *, limit: int = 3) -> list[sqlite3.Row]:
    normalized = [term.lower() for term in terms if len(str(term).strip()) >= 2]
    if not normalized:
        return []
    rows = conn.execute(
        """
        select c.entity_id, e.name, e.summary, c.clock_type, c.segments_filled, c.segments_total,
               c.visibility, c.trigger_when_full, c.tick_rules_json
        from clocks c
        join entities e on e.id = c.entity_id
        order by c.visibility desc, c.entity_id
        """
    ).fetchall()
    scored: list[tuple[int, str, sqlite3.Row]] = []
    for row in rows:
        text = clock_row_text(row)
        score = sum(1 for term in normalized if term in text)
        if score:
            scored.append((score, str(row["entity_id"]), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [row for _, _, row in scored[:limit]]


def clock_row_text(row: sqlite3.Row) -> str:
    return " ".join(
        str(part).lower()
        for part in [
            row["entity_id"],
            row["name"],
            row["summary"],
            row["clock_type"],
            row["trigger_when_full"],
            row["tick_rules_json"],
        ]
        if part
    )


def clock_query_terms(text: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_.:-]{2,}|[\u4e00-\u9fff]{2,}", text)
    return [term for term in terms if term.strip()]
