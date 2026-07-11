from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, is_dataclass
from typing import Any

from .visibility import (
    ensure_visibility_sql_functions,
    normalized_text_sql,
    player_hidden_visibility_sql,
    player_visible_visibility_sql,
    world_setting_entity_visibility_sql,
)


HIDDEN_TEXT_TOKEN_BLOCKLIST = frozenset(
    {
        "hidden",
        "secret",
        "gm",
        "only",
        "gm-only",
        "gm_only",
        "active",
        "archived",
        "character",
        "clock",
        "context",
        "entity",
        "faction",
        "hinted",
        "known",
        "location",
        "player",
        "query",
        "relationship",
        "source",
        "status",
        "summary",
        "target",
        "unknown",
        "visible",
        "visibility",
        "world",
    }
)
HIDDEN_STRUCTURED_TOKEN_RE = re.compile(r"[A-Za-z0-9_:-]{8,}")
HIDDEN_TEXT_SEGMENT_RE = re.compile(r"[^,，。；;、\n\r\t]+")
HIDDEN_CJK_LOCATIVE_FRAGMENT_RE = re.compile(r"[在于至向从靠近]([\u4e00-\u9fff]{2,8})")
HIDDEN_CJK_SECRET_FRAGMENT_RE = re.compile(
    r"(?:口令|代号|暗号|密钥|密语|真名|编号|代码|信物)(?:是|为|[:：])?\s*([\u4e00-\u9fff]{2,8})"
)
HIDDEN_CJK_MARKER_SUFFIX_RE = re.compile(r"([\u4e00-\u9fff]{2,8}(?:细节|摘要|真相|内容|线索|秘密|封印))")
HIDDEN_CJK_MARKER_PREFIX_RE = re.compile(r"((?:细节|摘要|真相|内容|线索|秘密|封印)[\u4e00-\u9fff]{2,8})")
HIDDEN_ENGLISH_SECRET_FRAGMENT_RE = re.compile(
    r"\b(?:secret|code|password|passphrase|key|token)"
    r"(?:\s+(?:secret|code|password|passphrase|key|token))*"
    r"\s*(?:is|=|:)?\s*([A-Za-z][A-Za-z0-9_:-]{4,})\b",
    re.IGNORECASE,
)
HIDDEN_EXACT_TEXT_MIN_LENGTH = 5
HIDDEN_PURE_ALPHA_TEXT_MIN_LENGTH = 7
HIDDEN_KEY_TOKEN_MARKERS = frozenset({"secret", "hidden", "gm", "code", "key", "token", "password", "passphrase"})
STRUCTURED_REFERENCE_ID_RE = re.compile(r"^(?:clock:[A-Za-z0-9_.:-]+|[a-z]+:[A-Za-z0-9_.-]+)$")
MAX_STRUCTURED_REFERENCE_IDS = 128
MAX_STRUCTURED_REFERENCE_ID_LENGTH = 160


def hidden_entity_ids(conn: sqlite3.Connection) -> set[str]:
    return set(hidden_entity_refs(conn).keys())


def hidden_entity_refs(conn: sqlite3.Connection) -> dict[str, set[str]]:
    ensure_visibility_sql_functions(conn)
    public_reference_tokens = player_public_reference_tokens(conn)
    has_world_settings = _table_exists(conn, "world_settings")
    world_setting_visibility_expr = "coalesce(ws.visibility, '')"
    world_setting_hidden_expr = (
        f"({normalized_text_sql('e.type')} = 'world_setting' "
        f"and (ws.entity_id is null or {normalized_text_sql(world_setting_visibility_expr)} not in ('known', 'hinted')))"
        if has_world_settings
        else f"{normalized_text_sql('e.type')} = 'world_setting'"
    )
    world_setting_select = (
        f"{world_setting_hidden_expr} as world_setting_hidden,"
        " ws.summary as world_setting_summary,"
        " ws.content_json as world_setting_content_json"
        if has_world_settings
        else f"{world_setting_hidden_expr} as world_setting_hidden, null as world_setting_summary, null as world_setting_content_json"
    )
    world_setting_join = "left join world_settings ws on ws.entity_id = e.id" if has_world_settings else ""
    world_setting_where = f"or {world_setting_hidden_expr}"
    rows = conn.execute(
        f"""
        select e.id,
               e.name,
               e.summary,
               e.details_json,
               {normalized_text_sql("e.status")} = 'archived' as entity_archived,
               {player_hidden_visibility_sql("e.visibility")} as entity_hidden,
               ({normalized_text_sql("e.type")} = 'clock'
                and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")}) as clock_hidden,
               {world_setting_select}
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {normalized_text_sql("e.status")} = 'archived'
           or {player_hidden_visibility_sql("e.visibility")}
           or ({normalized_text_sql("e.type")} = 'clock'
               and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
           {world_setting_where}
        """
    ).fetchall()
    refs: dict[str, set[str]] = {}
    for row in rows:
        entity_id = str(row["id"])
        tokens = set()
        tokens.add(entity_id)
        tokens.add(f"pal:{entity_id}")
        name = str(row["name"] or "").strip()
        if name:
            tokens.add(name)
        aliases = conn.execute("select alias from aliases where entity_id = ?", (entity_id,)).fetchall()
        for alias_row in aliases:
            alias = str(alias_row["alias"] or "").strip()
            if alias:
                tokens.add(alias)
        if (
            bool(row["entity_archived"])
            or bool(row["entity_hidden"])
            or bool(row["clock_hidden"])
            or bool(row["world_setting_hidden"])
        ):
            tokens.update(_hidden_text_tokens(row["summary"], public_tokens=public_reference_tokens))
            tokens.update(_hidden_text_tokens(_parse_json(row["details_json"], {}), public_tokens=public_reference_tokens))
        if bool(row["world_setting_hidden"]) or bool(row["entity_hidden"]):
            tokens.update(_hidden_text_tokens(row["world_setting_summary"], public_tokens=public_reference_tokens))
            tokens.update(
                _hidden_text_tokens(_parse_json(row["world_setting_content_json"], {}), public_tokens=public_reference_tokens)
            )
        refs[entity_id] = tokens
    return refs


def player_public_name_tokens(conn: sqlite3.Connection) -> set[str]:
    rows = player_public_entity_rows(conn)
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


def player_public_entity_tokens(conn: sqlite3.Connection) -> set[str]:
    rows = player_public_entity_rows(conn)
    tokens = {str(row["id"]) for row in rows}
    tokens.update(str(row["name"] or "").strip() for row in rows if str(row["name"] or "").strip())
    return tokens


def player_public_reference_tokens(conn: sqlite3.Connection) -> set[str]:
    rows = player_public_entity_rows(conn)
    tokens = {str(row["id"]) for row in rows}
    tokens.update(f"pal:{row['id']}" for row in rows)
    return tokens


def player_public_entity_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    has_world_settings = _table_exists(conn, "world_settings")
    world_setting_join = "left join world_settings ws on ws.entity_id = e.id" if has_world_settings else ""
    world_setting_visibility_clause = world_setting_entity_visibility_sql(
        "player",
        entity_alias="e",
        setting_alias="ws",
        has_world_settings=has_world_settings,
    )
    rows = conn.execute(
        f"""
        select e.id, e.name
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where {normalized_text_sql("e.status")} != 'archived'
          and {player_visible_visibility_sql("e.visibility")}
          and not ({normalized_text_sql("e.type")} = 'clock'
                   and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
          {world_setting_visibility_clause}
        """
    ).fetchall()
    return list(rows)


def redact_hidden_entity_refs(conn: sqlite3.Connection, value: Any, *, drop_empty: bool = True) -> Any:
    return redact_entity_refs(value, hidden_entity_refs(conn), drop_empty=drop_empty)


def redact_hidden_entity_id_substrings(conn: sqlite3.Connection, value: Any, *, drop_empty: bool = True) -> Any:
    refs = hidden_entity_refs(conn)
    return redact_hidden_entity_id_substrings_from_refs(value, refs, drop_empty=drop_empty)


def redact_hidden_entity_id_substrings_from_refs(
    value: Any,
    refs: dict[str, set[str]],
    *,
    drop_empty: bool = True,
) -> Any:
    tokens = set(refs.keys()) | {f"pal:{entity_id}" for entity_id in refs}
    return redact_entity_substrings(value, tokens, drop_empty=drop_empty)


def redact_player_hidden_material(
    conn: sqlite3.Connection,
    value: Any,
    *,
    drop_empty: bool = True,
    redact_id_substrings: bool = True,
    structured_reference_ids: bool = False,
) -> Any:
    if structured_reference_ids:
        return _redact_structured_reference_ids(conn, value, drop_empty=drop_empty)
    refs = hidden_entity_refs(conn)
    return redact_player_hidden_material_from_refs(
        value,
        refs,
        drop_empty=drop_empty,
        redact_id_substrings=redact_id_substrings,
    )


def _redact_structured_reference_ids(conn: sqlite3.Connection, value: Any, *, drop_empty: bool) -> Any:
    if (
        type(value) is not list
        or len(value) > MAX_STRUCTURED_REFERENCE_IDS
        or not all(
            type(item) is str
            and len(item) <= MAX_STRUCTURED_REFERENCE_ID_LENGTH
            and STRUCTURED_REFERENCE_ID_RE.fullmatch(item) is not None
            for item in value
        )
    ):
        raise ValueError("structured references must be a bounded list of strings")
    hidden_ids = _hidden_candidate_entity_ids(conn, value)
    redacted = ["[hidden]" if item in hidden_ids else item for item in value]
    if not drop_empty:
        return redacted
    return [item for item in redacted if not _should_drop(item)]


def _hidden_candidate_entity_ids(conn: sqlite3.Connection, candidates: list[str]) -> set[str]:
    if not candidates:
        return set()
    ensure_visibility_sql_functions(conn)
    has_world_settings = _table_exists(conn, "world_settings")
    world_setting_visibility_expr = "coalesce(ws.visibility, '')"
    world_setting_hidden_expr = (
        f"({normalized_text_sql('e.type')} = 'world_setting' "
        f"and (ws.entity_id is null or {normalized_text_sql(world_setting_visibility_expr)} not in ('known', 'hinted')))"
        if has_world_settings
        else f"{normalized_text_sql('e.type')} = 'world_setting'"
    )
    world_setting_join = "left join world_settings ws on ws.entity_id = e.id" if has_world_settings else ""
    placeholders = ",".join("?" for _ in candidates)
    rows = conn.execute(
        f"""
        select e.id
        from entities e
        left join clocks c on c.entity_id = e.id
        {world_setting_join}
        where e.id in ({placeholders})
          and (
            {normalized_text_sql("e.status")} = 'archived'
            or {player_hidden_visibility_sql("e.visibility")}
            or ({normalized_text_sql("e.type")} = 'clock'
                and {player_hidden_visibility_sql("coalesce(c.visibility, e.visibility)")})
            or {world_setting_hidden_expr}
          )
        """,
        tuple(candidates),
    ).fetchall()
    return {str(row["id"]) for row in rows}


def redact_player_hidden_material_from_refs(
    value: Any,
    refs: dict[str, set[str]],
    *,
    drop_empty: bool = True,
    redact_id_substrings: bool = True,
) -> Any:
    redacted = redact_entity_refs(value, refs, drop_empty=drop_empty)
    if not redact_id_substrings:
        return redacted
    return redact_hidden_entity_id_substrings_from_refs(redacted, refs, drop_empty=drop_empty)


def find_hidden_entity_ref_tokens(conn: sqlite3.Connection, value: Any) -> list[str]:
    return find_entity_ref_tokens(value, hidden_entity_refs(conn))


def find_hidden_entity_ref_substrings(conn: sqlite3.Connection, value: Any) -> list[str]:
    return find_entity_ref_substrings(value, hidden_entity_refs(conn))


def find_hidden_entity_id_substrings(conn: sqlite3.Connection, value: Any) -> list[str]:
    refs = hidden_entity_refs(conn)
    tokens = set(refs.keys()) | {f"pal:{entity_id}" for entity_id in refs}
    return find_entity_ref_substrings(value, tokens)


def redact_entity_refs(value: Any, refs: dict[str, set[str]] | set[str], *, drop_empty: bool = True) -> Any:
    tokens = _redaction_tokens(refs)
    if not tokens:
        return value
    return _redact_value(value, tokens, drop_empty=drop_empty)


def redact_entity_substrings(value: Any, refs: dict[str, set[str]] | set[str], *, drop_empty: bool = True) -> Any:
    tokens = _redaction_tokens(refs)
    if not tokens:
        return value
    return _redact_value_substrings(value, tokens, drop_empty=drop_empty)


def find_entity_ref_tokens(value: Any, refs: dict[str, set[str]] | set[str]) -> list[str]:
    tokens = _redaction_tokens(refs)
    if not tokens:
        return []
    found: set[str] = set()
    _collect_ref_tokens(value, tokens, found)
    return sorted(found, key=lambda item: (len(item), item))


def find_entity_ref_substrings(value: Any, refs: dict[str, set[str]] | set[str]) -> list[str]:
    tokens = _redaction_tokens(refs)
    if not tokens:
        return []
    found: set[str] = set()
    _collect_substring_tokens(value, tokens, found)
    return sorted(found, key=lambda item: (len(item), item))


def _redaction_tokens(refs: dict[str, set[str]] | set[str]) -> list[str]:
    if isinstance(refs, set):
        tokens = set(refs)
    else:
        tokens = {token for values in refs.values() for token in values}
    return sorted((token for token in tokens if token), key=len, reverse=True)


def _parse_json(text: Any, default: Any) -> Any:
    if not isinstance(text, str) or not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("select 1 from sqlite_master where type='table' and name = ?", (table,)).fetchone()
    return bool(row)


def _hidden_text_tokens(value: Any, *, public_tokens: set[str]) -> set[str]:
    found: set[str] = set()
    _collect_hidden_text_tokens(value, found, public_tokens=public_tokens)
    return found


def _collect_hidden_text_tokens(value: Any, found: set[str], *, public_tokens: set[str]) -> None:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        if _should_keep_hidden_exact_text_token(text, public_tokens=public_tokens):
            found.add(text)
        for segment in HIDDEN_TEXT_SEGMENT_RE.findall(text):
            segment = segment.strip()
            if segment != text and _should_keep_hidden_exact_text_token(segment, public_tokens=public_tokens):
                found.add(segment)
            for fragment in _hidden_english_marker_fragments(segment):
                if _should_keep_hidden_english_marker_fragment(fragment, public_tokens=public_tokens):
                    found.add(fragment)
            for fragment in _hidden_short_text_fragments(segment):
                if _should_keep_hidden_short_fragment(
                    fragment,
                    public_tokens=public_tokens,
                ) or _should_keep_hidden_exact_text_token(fragment, public_tokens=public_tokens):
                    found.add(fragment)
        for token in HIDDEN_STRUCTURED_TOKEN_RE.findall(text):
            if _should_keep_hidden_structured_token(token, public_tokens=public_tokens):
                found.add(token)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            _collect_hidden_key_tokens(key_text, found, public_tokens=set())
            _collect_hidden_text_tokens(item, found, public_tokens=public_tokens)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_hidden_text_tokens(item, found, public_tokens=public_tokens)


def _should_keep_hidden_exact_text_token(token: str, *, public_tokens: set[str]) -> bool:
    normalized = token.strip()
    return bool(
        (len(normalized) >= HIDDEN_EXACT_TEXT_MIN_LENGTH or re.fullmatch(r"[\u4e00-\u9fff]{2,4}", normalized))
        and normalized.lower() not in HIDDEN_TEXT_TOKEN_BLOCKLIST
        and normalized not in public_tokens
        and (
            not re.fullmatch(r"[A-Za-z]+", normalized)
            or any(char.isupper() for char in normalized)
            or len(normalized) >= HIDDEN_PURE_ALPHA_TEXT_MIN_LENGTH
        )
    )


def _collect_hidden_key_tokens(key: str, found: set[str], *, public_tokens: set[str]) -> None:
    text = key.strip()
    if not text:
        return
    lowered = text.lower()
    if (
        not any(char.isupper() or char.isdigit() for char in text)
        and not (any(separator in text for separator in ("_", "-", ":")) and any(marker in lowered for marker in HIDDEN_KEY_TOKEN_MARKERS))
    ):
        return
    for token in HIDDEN_STRUCTURED_TOKEN_RE.findall(text):
        if _should_keep_hidden_structured_token(token, public_tokens=public_tokens):
            found.add(token)


def _should_keep_hidden_structured_token(token: str, *, public_tokens: set[str]) -> bool:
    normalized = token.strip()
    return bool(
        normalized
        and normalized.lower() not in HIDDEN_TEXT_TOKEN_BLOCKLIST
        and normalized not in public_tokens
        and (any(char.isdigit() for char in normalized) or ":" in normalized or "-" in normalized or "_" in normalized)
    )


def _hidden_short_text_fragments(text: str) -> set[str]:
    fragments = {match.group(1).strip() for match in HIDDEN_CJK_LOCATIVE_FRAGMENT_RE.finditer(text)}
    fragments.update(match.group(1).strip() for match in HIDDEN_CJK_SECRET_FRAGMENT_RE.finditer(text))
    fragments.update(match.group(1).strip() for match in HIDDEN_CJK_MARKER_SUFFIX_RE.finditer(text))
    fragments.update(match.group(1).strip() for match in HIDDEN_CJK_MARKER_PREFIX_RE.finditer(text))
    return fragments


def _should_keep_hidden_short_fragment(token: str, *, public_tokens: set[str]) -> bool:
    normalized = token.strip()
    return bool(
        2 <= len(normalized) <= 8
        and normalized not in public_tokens
        and re.fullmatch(r"[\u4e00-\u9fff]+", normalized)
    )


def _hidden_english_marker_fragments(text: str) -> set[str]:
    return {match.group(1).strip() for match in HIDDEN_ENGLISH_SECRET_FRAGMENT_RE.finditer(text)}


def _should_keep_hidden_english_marker_fragment(token: str, *, public_tokens: set[str]) -> bool:
    normalized = token.strip()
    return bool(
        normalized
        and normalized not in public_tokens
        and normalized.lower() not in HIDDEN_TEXT_TOKEN_BLOCKLIST
        and (
            _should_keep_hidden_structured_token(normalized, public_tokens=public_tokens)
            or (5 <= len(normalized) <= 8 and re.fullmatch(r"[A-Za-z]+", normalized))
        )
    )


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


def _redact_value_substrings(value: Any, tokens: list[str], *, drop_empty: bool) -> Any:
    if isinstance(value, str):
        redacted = value
        for token in tokens:
            redacted = _replace_substring_token(redacted, token)
        return redacted
    if isinstance(value, list):
        items = [_redact_value_substrings(item, tokens, drop_empty=drop_empty) for item in value]
        if not drop_empty:
            return items
        return [item for item in items if not _should_drop(item)]
    if isinstance(value, tuple):
        items = tuple(_redact_value_substrings(item, tokens, drop_empty=drop_empty) for item in value)
        if not drop_empty:
            return items
        return tuple(item for item in items if not _should_drop(item))
    if isinstance(value, (set, frozenset)):
        items = [_redact_value_substrings(item, tokens, drop_empty=drop_empty) for item in value]
        if not drop_empty:
            return _redacted_set_value(items, as_frozenset=isinstance(value, frozenset))
        kept_items = [item for item in items if not _should_drop(item)]
        return _redacted_set_value(kept_items, as_frozenset=isinstance(value, frozenset))
    if isinstance(value, dict):
        redacted_items = {
            _redact_value_substrings(str(key), tokens, drop_empty=drop_empty): _redact_value_substrings(
                item,
                tokens,
                drop_empty=drop_empty,
            )
            for key, item in value.items()
        }
        if not drop_empty:
            return redacted_items
        return {key: item for key, item in redacted_items.items() if not _should_drop(key) and not _should_drop(item)}
    if is_dataclass(value) and not isinstance(value, type):
        return _redact_value_substrings(asdict(value), tokens, drop_empty=drop_empty)
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


def _collect_substring_tokens(value: Any, tokens: list[str], found: set[str]) -> None:
    if isinstance(value, str):
        for token in tokens:
            if token and _contains_substring_token(value, token):
                found.add(token)
        return
    if is_dataclass(value) and not isinstance(value, type):
        _collect_substring_tokens(asdict(value), tokens, found)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_substring_tokens(str(key), tokens, found)
            _collect_substring_tokens(item, tokens, found)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_substring_tokens(item, tokens, found)


def _replace_token(text: str, token: str) -> str:
    if _is_reference_token(token):
        return re.sub(_reference_token_pattern(token), "[hidden]", text, flags=re.IGNORECASE)
    if _is_case_insensitive_token(token):
        return re.sub(re.escape(token), "[hidden]", text, flags=re.IGNORECASE)
    return text.replace(token, "[hidden]")


def _contains_token(text: str, token: str) -> bool:
    if _is_reference_token(token):
        return re.search(_reference_token_pattern(token), text, flags=re.IGNORECASE) is not None
    if _is_case_insensitive_token(token):
        return token.casefold() in text.casefold()
    return token in text


def _replace_substring_token(text: str, token: str) -> str:
    if _is_case_insensitive_token(token) or _is_reference_token(token):
        return re.sub(re.escape(token), "[hidden]", text, flags=re.IGNORECASE)
    return text.replace(token, "[hidden]")


def _contains_substring_token(text: str, token: str) -> bool:
    if _is_case_insensitive_token(token) or _is_reference_token(token):
        return token.casefold() in text.casefold()
    return token in text


def _is_case_insensitive_token(token: str) -> bool:
    return token.isascii() and any(char.isalpha() for char in token)


def _is_reference_token(token: str) -> bool:
    return ":" in token and bool(token.split(":", 1)[0]) and bool(token.split(":", 1)[1])


def _reference_token_pattern(token: str) -> str:
    escaped = re.escape(token)
    # Entity ids use ASCII id characters; avoid matching `loc:hidden` inside
    # longer ids such as `loc:hidden-route` or `loc:hidden.route`, while still
    # allowing ordinary sentence punctuation after an id.
    return rf"(?<![A-Za-z0-9_.:-]){escaped}(?![A-Za-z0-9_:-]|\.[A-Za-z0-9_.:-])"
