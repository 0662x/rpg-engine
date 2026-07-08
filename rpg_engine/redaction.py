from __future__ import annotations

import sqlite3
import re
from dataclasses import asdict, is_dataclass
from typing import Any

from .visibility import ensure_visibility_sql_functions, normalized_text_sql


def hidden_entity_ids(conn: sqlite3.Connection) -> set[str]:
    return set(hidden_entity_refs(conn).keys())


def hidden_entity_refs(conn: sqlite3.Connection) -> dict[str, set[str]]:
    ensure_visibility_sql_functions(conn)
    public_tokens = player_public_name_tokens(conn)
    rows = conn.execute(
        f"""
        select e.id, e.name
        from entities e
        left join clocks c on c.entity_id = e.id
        where {normalized_text_sql("e.status")} = 'archived'
           or {normalized_text_sql("e.visibility")} = 'hidden'
           or ({normalized_text_sql("e.type")} = 'clock'
               and {normalized_text_sql("coalesce(c.visibility, e.visibility)")} = 'hidden')
        """
    ).fetchall()
    refs: dict[str, set[str]] = {}
    for row in rows:
        entity_id = str(row["id"])
        tokens = set()
        if entity_id not in public_tokens:
            tokens.add(entity_id)
            tokens.add(f"pal:{entity_id}")
        name = str(row["name"] or "").strip()
        if name and name not in public_tokens:
            tokens.add(name)
        aliases = conn.execute("select alias from aliases where entity_id = ?", (entity_id,)).fetchall()
        for alias_row in aliases:
            alias = str(alias_row["alias"] or "").strip()
            if alias and alias not in public_tokens:
                tokens.add(alias)
        refs[entity_id] = tokens
    return refs


def player_public_name_tokens(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        f"""
        select e.id, e.name
        from entities e
        left join clocks c on c.entity_id = e.id
        where {normalized_text_sql("e.status")} != 'archived'
          and {normalized_text_sql("e.visibility")} != 'hidden'
          and not ({normalized_text_sql("e.type")} = 'clock'
                   and {normalized_text_sql("coalesce(c.visibility, e.visibility)")} = 'hidden')
        """
    ).fetchall()
    tokens = {str(row["id"]) for row in rows}
    tokens.update(str(row["name"] or "").strip() for row in rows if str(row["name"] or "").strip())
    ids = [str(row["id"]) for row in rows]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        aliases = conn.execute(
            f"select alias from aliases where entity_id in ({placeholders})",
            ids,
        ).fetchall()
        tokens.update(str(row["alias"] or "").strip() for row in aliases if str(row["alias"] or "").strip())
    return tokens


def redact_hidden_entity_refs(conn: sqlite3.Connection, value: Any, *, drop_empty: bool = True) -> Any:
    return redact_entity_refs(value, hidden_entity_refs(conn), drop_empty=drop_empty)


def find_hidden_entity_ref_tokens(conn: sqlite3.Connection, value: Any) -> list[str]:
    return find_entity_ref_tokens(value, hidden_entity_refs(conn))


def redact_entity_refs(value: Any, refs: dict[str, set[str]] | set[str], *, drop_empty: bool = True) -> Any:
    tokens = _redaction_tokens(refs)
    if not tokens:
        return value
    return _redact_value(value, tokens, drop_empty=drop_empty)


def find_entity_ref_tokens(value: Any, refs: dict[str, set[str]] | set[str]) -> list[str]:
    tokens = _redaction_tokens(refs)
    if not tokens:
        return []
    found: set[str] = set()
    _collect_ref_tokens(value, tokens, found)
    return sorted(found, key=lambda item: (len(item), item))


def _redaction_tokens(refs: dict[str, set[str]] | set[str]) -> list[str]:
    if isinstance(refs, set):
        tokens = set(refs)
    else:
        tokens = {token for values in refs.values() for token in values}
    return sorted((token for token in tokens if token), key=len, reverse=True)


def _redact_value(value: Any, tokens: list[str], *, drop_empty: bool) -> Any:
    if isinstance(value, str):
        if value in tokens:
            return "[hidden]" if not drop_empty else None
        redacted = value
        for token in tokens:
            redacted = _replace_token(redacted, token)
        return redacted
    if isinstance(value, list):
        items = [_redact_value(item, tokens, drop_empty=drop_empty) for item in value]
        if not drop_empty:
            return items
        return [item for item in items if not _should_drop(item)]
    if isinstance(value, tuple):
        items = tuple(_redact_value(item, tokens, drop_empty=drop_empty) for item in value)
        if not drop_empty:
            return items
        return tuple(item for item in items if not _should_drop(item))
    if isinstance(value, (set, frozenset)):
        items = [_redact_value(item, tokens, drop_empty=drop_empty) for item in value]
        if not drop_empty:
            return _redacted_set_value(items, as_frozenset=isinstance(value, frozenset))
        kept_items = [item for item in items if not _should_drop(item)]
        return _redacted_set_value(kept_items, as_frozenset=isinstance(value, frozenset))
    if isinstance(value, dict):
        redacted_items = {
            _redact_key(key, tokens, drop_empty=drop_empty): _redact_value(item, tokens, drop_empty=drop_empty)
            for key, item in value.items()
        }
        if not drop_empty:
            return redacted_items
        return {key: item for key, item in redacted_items.items() if not _should_drop(key) and not _should_drop(item)}
    if is_dataclass(value) and not isinstance(value, type):
        return _redact_value(asdict(value), tokens, drop_empty=drop_empty)
    return value


def _should_drop(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {} or value == () or value == set() or value == frozenset()


def _redacted_set_value(items: list[Any], *, as_frozenset: bool) -> Any:
    hashable_items = [_hashable_redaction_item(item) for item in items]
    return frozenset(hashable_items) if as_frozenset else set(hashable_items)


def _hashable_redaction_item(value: Any) -> Any:
    try:
        hash(value)
        return value
    except TypeError:
        pass
    if isinstance(value, dict):
        return tuple(
            sorted(
                (
                    (_hashable_redaction_item(key), _hashable_redaction_item(item))
                    for key, item in value.items()
                ),
                key=lambda pair: repr(pair[0]),
            )
        )
    if isinstance(value, list):
        return tuple(_hashable_redaction_item(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_hashable_redaction_item(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_hashable_redaction_item(item) for item in value)
    return repr(value)


def _redact_key(key: Any, tokens: list[str], *, drop_empty: bool) -> Any:
    if isinstance(key, str):
        return _redact_value(key, tokens, drop_empty=drop_empty)
    return key


def _collect_ref_tokens(value: Any, tokens: list[str], found: set[str]) -> None:
    if isinstance(value, str):
        for token in tokens:
            if token and _contains_token(value, token):
                found.add(token)
        return
    if is_dataclass(value) and not isinstance(value, type):
        _collect_ref_tokens(asdict(value), tokens, found)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_ref_tokens(str(key), tokens, found)
            _collect_ref_tokens(item, tokens, found)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_ref_tokens(item, tokens, found)


def _replace_token(text: str, token: str) -> str:
    if _is_reference_token(token):
        return re.sub(_reference_token_pattern(token), "[hidden]", text)
    return text.replace(token, "[hidden]")


def _contains_token(text: str, token: str) -> bool:
    if _is_reference_token(token):
        return re.search(_reference_token_pattern(token), text) is not None
    return token in text


def _is_reference_token(token: str) -> bool:
    return ":" in token and bool(token.split(":", 1)[0]) and bool(token.split(":", 1)[1])


def _reference_token_pattern(token: str) -> str:
    escaped = re.escape(token)
    # Entity ids use ASCII id characters; avoid matching `loc:hidden` inside
    # longer ids such as `loc:hidden-route` or `loc:hidden.route`, while still
    # allowing ordinary sentence punctuation after an id.
    return rf"(?<![A-Za-z0-9_.:-]){escaped}(?![A-Za-z0-9_:-]|\.[A-Za-z0-9_.:-])"
