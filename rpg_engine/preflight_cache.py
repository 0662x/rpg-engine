from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .campaign import Campaign
from .db import utc_now
from .resource_paths import schema_resource_text


PREFLIGHT_CACHE_SCHEMA_VERSION = "intent_preflight_cache:v1"
PREFLIGHT_TASK_VERSION = "internal_intent_review:v1"
PREFLIGHT_TTL_SECONDS = 300
PREFLIGHT_READY = "ready"
PREFLIGHT_PENDING = "pending"
PREFLIGHT_FAILED = "failed"
PREFLIGHT_USED = "used"
PREFLIGHT_EXPIRED = "expired"
PREFLIGHT_REJECTED = "rejected"
PREFLIGHT_PENDING_WAIT_DEFAULT_MS = 0
PREFLIGHT_PENDING_WAIT_MAX_MS = 1000
PREFLIGHT_IDENTITY_CANDIDATE_BOUND = "candidate_bound"
PREFLIGHT_IDENTITY_MESSAGE_ONLY = "message_only"
PREFLIGHT_IDENTITY_PROFILES = {
    PREFLIGHT_IDENTITY_CANDIDATE_BOUND,
    PREFLIGHT_IDENTITY_MESSAGE_ONLY,
}


@dataclass(frozen=True)
class PreflightContextIdentity:
    identity_profile: str
    save_id: str
    source_user_text_hash: str
    base_turn_id: str
    context_hash: str
    intent_context_id: str
    model_version: str
    schema_version: str
    external_candidate_hash: str
    rule_candidate_hash: str
    task_version: str = PREFLIGHT_TASK_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_profile": self.identity_profile,
            "save_id": self.save_id,
            "source_user_text_hash": self.source_user_text_hash,
            "base_turn_id": self.base_turn_id,
            "context_hash": self.context_hash,
            "intent_context_id": self.intent_context_id,
            "model_version": self.model_version,
            "schema_version": self.schema_version,
            "external_candidate_hash": self.external_candidate_hash,
            "rule_candidate_hash": self.rule_candidate_hash,
            "task_version": self.task_version,
        }


@dataclass(frozen=True)
class PreflightRecord:
    id: str
    status: str
    identity: PreflightContextIdentity
    message_id: str = ""
    platform: str = ""
    session_key: str = ""
    expires_at: str = ""
    error: str = ""
    bypassed_at: str = ""
    late_ready_unused_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message_id": self.message_id,
            "platform": self.platform,
            "session_key": self.session_key,
            "expires_at": self.expires_at,
            "error": self.error,
            "bypassed_at": self.bypassed_at,
            "late_ready_unused_at": self.late_ready_unused_at,
            "identity": self.identity.to_dict(),
        }


@dataclass(frozen=True)
class PreflightLookupResult:
    status: str
    record: PreflightRecord | None = None
    internal_review: dict[str, Any] | None = None
    helper_audit: dict[str, Any] | None = None
    reason: str = ""

    @property
    def hit(self) -> bool:
        return self.status == "hit" and self.internal_review is not None

    def to_trace(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "record": self.record.to_dict() if self.record else None,
        }


def create_pending_intent_preflight(
    conn: sqlite3.Connection,
    campaign: Campaign,
    user_text: str,
    *,
    provider: str,
    model: str,
    backend: str,
    fallback_backend: str = "off",
    message_id: str = "",
    platform: str = "",
    session_key: str = "",
    source_user_text_hash: str = "",
    external_candidate: dict[str, Any] | None = None,
    rule_candidate: dict[str, Any] | None = None,
    identity_profile: str = PREFLIGHT_IDENTITY_CANDIDATE_BOUND,
    ttl_seconds: int = PREFLIGHT_TTL_SECONDS,
) -> PreflightRecord:
    profile = normalize_identity_profile(identity_profile)
    stored_external_candidate = None if profile == PREFLIGHT_IDENTITY_MESSAGE_ONLY else external_candidate
    identity = build_preflight_identity(
        conn,
        campaign,
        user_text,
        provider=provider,
        model=model,
        backend=backend,
        fallback_backend=fallback_backend,
        external_candidate=stored_external_candidate,
        rule_candidate=rule_candidate,
        identity_profile=profile,
    )
    assert_declared_text_hash(user_text, source_user_text_hash)
    preflight_id = f"preflight:{uuid.uuid4().hex}"
    now = utc_now()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(ttl_seconds)))).isoformat()
    conn.execute(
        """
        insert into intent_preflight_cache (
          id, status, identity_profile, platform, session_key, message_id, save_id, user_text,
          source_user_text_hash, base_turn_id, context_hash, intent_context_id,
          provider, model, backend, fallback_backend, model_version, schema_version, task_version,
          external_candidate_hash, rule_candidate_hash, external_candidate_json, rule_candidate_json,
          created_at, updated_at, expires_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            preflight_id,
            PREFLIGHT_PENDING,
            profile,
            clean(platform),
            clean(session_key),
            clean(message_id),
            identity.save_id,
            normalize_text(user_text),
            identity.source_user_text_hash,
            identity.base_turn_id,
            identity.context_hash,
            identity.intent_context_id,
            clean(provider),
            clean(model),
            clean(backend),
            clean(fallback_backend or "off"),
            identity.model_version,
            identity.schema_version,
            identity.task_version,
            identity.external_candidate_hash,
            identity.rule_candidate_hash,
            json_text(stored_external_candidate or {}),
            json_text(rule_candidate or {}),
            now,
            now,
            expires_at,
        ),
    )
    return PreflightRecord(
        id=preflight_id,
        status=PREFLIGHT_PENDING,
        identity=identity,
        message_id=clean(message_id),
        platform=clean(platform),
        session_key=clean(session_key),
        expires_at=expires_at,
    )


def mark_intent_preflight_ready(
    conn: sqlite3.Connection,
    preflight_id: str,
    *,
    internal_review: dict[str, Any],
    helper_audit: dict[str, Any] | None = None,
) -> str:
    late_ready_at = utc_now()
    updated_at = utc_now()
    cursor = conn.execute(
        """
        update intent_preflight_cache
        set status=case when bypassed_at is null then ? else ? end,
            internal_review_json=?,
            helper_audit_json=?,
            error=null,
            rejected_reason=case when bypassed_at is null then rejected_reason else ? end,
            late_ready_unused_at=case when bypassed_at is null then late_ready_unused_at else ? end,
            updated_at=?
        where id=? and status=? and expires_at > ?
        """,
        (
            PREFLIGHT_READY,
            PREFLIGHT_REJECTED,
            json_text(internal_review),
            json_text(helper_audit or {}),
            "late_ready_unused",
            late_ready_at,
            updated_at,
            preflight_id,
            PREFLIGHT_PENDING,
            utc_now(),
        ),
    )
    if cursor.rowcount != 1:
        raise ValueError("preflight is not pending or has expired")
    row = conn.execute("select status from intent_preflight_cache where id=?", (preflight_id,)).fetchone()
    return str(row["status"]) if row else PREFLIGHT_READY


def mark_intent_preflight_failed(conn: sqlite3.Connection, preflight_id: str, *, error: str) -> None:
    cursor = conn.execute(
        """
        update intent_preflight_cache
        set status=?, error=?, updated_at=?
        where id=? and status=? and expires_at > ?
        """,
        (PREFLIGHT_FAILED, clean(error), utc_now(), preflight_id, PREFLIGHT_PENDING, utc_now()),
    )
    if cursor.rowcount != 1:
        raise ValueError("preflight is not pending or has expired")


def consume_intent_preflight(
    conn: sqlite3.Connection,
    campaign: Campaign,
    user_text: str,
    *,
    preflight_id: str,
    provider: str,
    model: str,
    backend: str,
    fallback_backend: str = "off",
    message_id: str = "",
    platform: str = "",
    session_key: str = "",
    source_user_text_hash: str = "",
    external_candidate: dict[str, Any] | None = None,
    rule_candidate: dict[str, Any] | None = None,
    pending_wait_ms: int = 0,
) -> PreflightLookupResult:
    row = conn.execute("select * from intent_preflight_cache where id=?", (preflight_id,)).fetchone()
    if row is None:
        return PreflightLookupResult("miss", reason="preflight id not found")
    if str(row["status"]) == PREFLIGHT_PENDING and not is_expired(str(row["expires_at"])) and pending_wait_ms > 0:
        row = wait_for_preflight_ready(conn, preflight_id, pending_wait_ms) or row
    return consume_intent_preflight_row(
        conn,
        campaign,
        row,
        user_text,
        provider=provider,
        model=model,
        backend=backend,
        fallback_backend=fallback_backend,
        message_id=message_id,
        platform=platform,
        session_key=session_key,
        source_user_text_hash=source_user_text_hash,
        external_candidate=external_candidate,
        rule_candidate=rule_candidate,
    )


def consume_intent_preflight_by_message(
    conn: sqlite3.Connection,
    campaign: Campaign,
    user_text: str,
    *,
    provider: str,
    model: str,
    backend: str,
    fallback_backend: str = "off",
    message_id: str = "",
    platform: str = "",
    session_key: str = "",
    source_user_text_hash: str = "",
    external_candidate: dict[str, Any] | None = None,
    rule_candidate: dict[str, Any] | None = None,
    pending_wait_ms: int = 0,
) -> PreflightLookupResult:
    if not clean(message_id):
        return PreflightLookupResult("miss", reason="message_id is required for message lookup")
    if not clean(platform) or not clean(session_key):
        return PreflightLookupResult("miss", reason="platform and session_key are required for message lookup")
    declared_hash_mismatch = declared_text_hash_mismatch(user_text, source_user_text_hash)
    if declared_hash_mismatch:
        return PreflightLookupResult(PREFLIGHT_REJECTED, reason=declared_hash_mismatch)
    expected = build_preflight_identity(
        conn,
        campaign,
        user_text,
        provider=provider,
        model=model,
        backend=backend,
        fallback_backend=fallback_backend,
        external_candidate=external_candidate,
        rule_candidate=rule_candidate,
        identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
    )
    rows = conn.execute(
        """
        select * from intent_preflight_cache
        where identity_profile=?
          and save_id=?
          and base_turn_id=?
          and source_user_text_hash=?
          and context_hash=?
          and intent_context_id=?
          and model_version=?
          and schema_version=?
          and task_version=?
          and platform=?
          and session_key=?
          and message_id=?
          and status in (?, ?)
          and bypassed_at is null
        order by created_at asc
        """,
        (
            PREFLIGHT_IDENTITY_MESSAGE_ONLY,
            expected.save_id,
            expected.base_turn_id,
            expected.source_user_text_hash,
            expected.context_hash,
            expected.intent_context_id,
            expected.model_version,
            expected.schema_version,
            expected.task_version,
            clean(platform),
            clean(session_key),
            clean(message_id),
            PREFLIGHT_PENDING,
            PREFLIGHT_READY,
        ),
    ).fetchall()
    if not rows:
        return PreflightLookupResult("miss", reason="message preflight not found")
    active_rows: list[sqlite3.Row] = []
    expired_record: PreflightRecord | None = None
    for candidate in rows:
        if is_expired(str(candidate["expires_at"])):
            expired_record = record_from_row(candidate)
            update_preflight_status(
                conn,
                expired_record.id,
                PREFLIGHT_EXPIRED,
                reason="expired",
                current_status=expired_record.status,
            )
            continue
        active_rows.append(candidate)
    if not active_rows:
        return PreflightLookupResult(PREFLIGHT_EXPIRED, record=expired_record, reason="preflight expired")
    rows = active_rows
    if len(rows) > 1:
        return PreflightLookupResult("ambiguous", reason="multiple message preflights matched")
    row = rows[0]
    if str(row["status"]) == PREFLIGHT_PENDING and pending_wait_ms > 0:
        row = wait_for_preflight_ready(conn, str(row["id"]), pending_wait_ms) or row
    return consume_intent_preflight_row(
        conn,
        campaign,
        row,
        user_text,
        provider=provider,
        model=model,
        backend=backend,
        fallback_backend=fallback_backend,
        message_id=message_id,
        platform=platform,
        session_key=session_key,
        source_user_text_hash=source_user_text_hash,
        external_candidate=external_candidate,
        rule_candidate=rule_candidate,
    )


def consume_intent_preflight_row(
    conn: sqlite3.Connection,
    campaign: Campaign,
    row: sqlite3.Row,
    user_text: str,
    *,
    provider: str,
    model: str,
    backend: str,
    fallback_backend: str = "off",
    message_id: str = "",
    platform: str = "",
    session_key: str = "",
    source_user_text_hash: str = "",
    external_candidate: dict[str, Any] | None = None,
    rule_candidate: dict[str, Any] | None = None,
) -> PreflightLookupResult:
    record = record_from_row(row)
    if is_expired(str(row["expires_at"])):
        if update_preflight_status(conn, record.id, PREFLIGHT_EXPIRED, reason="expired", current_status=record.status):
            return PreflightLookupResult(PREFLIGHT_EXPIRED, record=record, reason="preflight expired")
        return preflight_lookup_after_lost_transition(conn, record.id, record)
    if record.status == PREFLIGHT_PENDING:
        if record.bypassed_at:
            return PreflightLookupResult(PREFLIGHT_REJECTED, record=record, reason="preflight was bypassed")
        if not mark_intent_preflight_bypassed(conn, record.id, reason="pending wait timeout"):
            latest = conn.execute("select * from intent_preflight_cache where id=?", (record.id,)).fetchone()
            if latest is not None:
                return consume_intent_preflight_row(
                    conn,
                    campaign,
                    latest,
                    user_text,
                    provider=provider,
                    model=model,
                    backend=backend,
                    fallback_backend=fallback_backend,
                    message_id=message_id,
                    platform=platform,
                    session_key=session_key,
                    source_user_text_hash=source_user_text_hash,
                    external_candidate=external_candidate,
                    rule_candidate=rule_candidate,
                )
        return PreflightLookupResult(PREFLIGHT_PENDING, record=record, reason="preflight is pending")
    if record.status != PREFLIGHT_READY:
        return PreflightLookupResult(record.status, record=record, reason=f"preflight is {record.status}")

    declared_hash_mismatch = declared_text_hash_mismatch(user_text, source_user_text_hash)
    if declared_hash_mismatch:
        if update_preflight_status(conn, record.id, PREFLIGHT_REJECTED, reason=declared_hash_mismatch):
            return PreflightLookupResult(PREFLIGHT_REJECTED, record=record, reason=declared_hash_mismatch)
        return preflight_lookup_after_lost_transition(conn, record.id, record)

    expected = build_preflight_identity(
        conn,
        campaign,
        user_text,
        provider=provider,
        model=model,
        backend=backend,
        fallback_backend=fallback_backend,
        external_candidate=external_candidate,
        rule_candidate=rule_candidate,
        identity_profile=record.identity.identity_profile,
    )
    mismatch = identity_mismatch(
        row,
        expected,
        user_text=user_text,
        message_id=message_id,
        platform=platform,
        session_key=session_key,
    )
    if mismatch:
        if update_preflight_status(conn, record.id, PREFLIGHT_REJECTED, reason=mismatch):
            return PreflightLookupResult(PREFLIGHT_REJECTED, record=record, reason=mismatch)
        return preflight_lookup_after_lost_transition(conn, record.id, record)

    internal_review = json_object(row["internal_review_json"])
    helper_audit = json_object(row["helper_audit_json"])
    cursor = conn.execute(
        """
        update intent_preflight_cache
        set status=?, used_at=?, updated_at=?
        where id=? and status=? and used_at is null
        """,
        (PREFLIGHT_USED, utc_now(), utc_now(), record.id, PREFLIGHT_READY),
    )
    if cursor.rowcount != 1:
        return PreflightLookupResult(PREFLIGHT_USED, record=record, reason="preflight already consumed")
    return PreflightLookupResult("hit", record=record, internal_review=internal_review, helper_audit=helper_audit)


def wait_for_preflight_ready(
    conn: sqlite3.Connection,
    preflight_id: str,
    pending_wait_ms: int,
) -> sqlite3.Row | None:
    deadline = time.monotonic() + max(0, min(int(pending_wait_ms), PREFLIGHT_PENDING_WAIT_MAX_MS)) / 1000.0
    row = conn.execute("select * from intent_preflight_cache where id=?", (preflight_id,)).fetchone()
    while row is not None and str(row["status"]) == PREFLIGHT_PENDING and time.monotonic() < deadline:
        if is_expired(str(row["expires_at"])):
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))
        row = conn.execute("select * from intent_preflight_cache where id=?", (preflight_id,)).fetchone()
    return row


def mark_intent_preflight_bypassed(conn: sqlite3.Connection, preflight_id: str, *, reason: str) -> bool:
    now = utc_now()
    cursor = conn.execute(
        """
        update intent_preflight_cache
        set bypassed_at=coalesce(bypassed_at, ?),
            rejected_reason=coalesce(rejected_reason, ?),
            updated_at=?
        where id=? and status=? and bypassed_at is null
        """,
        (now, clean(reason), now, preflight_id, PREFLIGHT_PENDING),
    )
    return cursor.rowcount == 1


def build_preflight_identity(
    conn: sqlite3.Connection,
    campaign: Campaign,
    user_text: str,
    *,
    provider: str,
    model: str,
    backend: str,
    fallback_backend: str = "off",
    external_candidate: dict[str, Any] | None = None,
    rule_candidate: dict[str, Any] | None = None,
    identity_profile: str = PREFLIGHT_IDENTITY_CANDIDATE_BOUND,
) -> PreflightContextIdentity:
    profile = normalize_identity_profile(identity_profile)
    resolved_hash = hash_text(user_text)
    if profile == PREFLIGHT_IDENTITY_MESSAGE_ONLY:
        external_hash = ""
        rule_hash = ""
    else:
        external_hash = candidate_hash(external_candidate)
        rule_hash = candidate_hash(rule_candidate)
    base_turn_id = meta_value(conn, "current_turn_id", "turn:unknown")
    context_seed = {
        "campaign_id": campaign.campaign_id,
        "save_id": save_id(campaign),
        "base_turn_id": base_turn_id,
        "location": meta_value(conn, "current_location_id", ""),
        "day": meta_value(conn, "current_game_day", ""),
        "time_block": meta_value(conn, "current_time_block", ""),
        "source_user_text_hash": resolved_hash,
        "external_candidate_hash": external_hash,
        "rule_candidate_hash": rule_hash,
    }
    context_hash = hash_json(context_seed)
    model_version = (
        f"{clean(provider)}:{clean(model)}"
        f":backend={clean(backend)}"
        f":fallback={clean(fallback_backend or 'off')}"
    )
    schema_version = hash_text(schema_resource_text("internal_intent_review.schema.json"))
    intent_context_id = hash_json(
        {
            **context_seed,
            "context_hash": context_hash,
            "schema_version": schema_version,
            "task_version": PREFLIGHT_TASK_VERSION,
            "model_version": model_version,
        }
    )
    return PreflightContextIdentity(
        identity_profile=profile,
        save_id=save_id(campaign),
        source_user_text_hash=resolved_hash,
        base_turn_id=base_turn_id,
        context_hash=context_hash,
        intent_context_id=intent_context_id,
        model_version=model_version,
        schema_version=schema_version,
        external_candidate_hash=external_hash,
        rule_candidate_hash=rule_hash,
    )


def record_from_row(row: sqlite3.Row) -> PreflightRecord:
    identity = PreflightContextIdentity(
        identity_profile=str(row["identity_profile"] or PREFLIGHT_IDENTITY_CANDIDATE_BOUND),
        save_id=str(row["save_id"]),
        source_user_text_hash=str(row["source_user_text_hash"]),
        base_turn_id=str(row["base_turn_id"]),
        context_hash=str(row["context_hash"]),
        intent_context_id=str(row["intent_context_id"]),
        model_version=str(row["model_version"]),
        schema_version=str(row["schema_version"]),
        external_candidate_hash=str(row["external_candidate_hash"] or ""),
        rule_candidate_hash=str(row["rule_candidate_hash"] or ""),
        task_version=str(row["task_version"]),
    )
    return PreflightRecord(
        id=str(row["id"]),
        status=str(row["status"]),
        identity=identity,
        message_id=str(row["message_id"] or ""),
        platform=str(row["platform"] or ""),
        session_key=str(row["session_key"] or ""),
        expires_at=str(row["expires_at"] or ""),
        error=str(row["error"] or ""),
        bypassed_at=str(row["bypassed_at"] or ""),
        late_ready_unused_at=str(row["late_ready_unused_at"] or ""),
    )


def identity_mismatch(
    row: sqlite3.Row,
    expected: PreflightContextIdentity,
    *,
    user_text: str,
    message_id: str = "",
    platform: str = "",
    session_key: str = "",
) -> str:
    if str(row["user_text"] or "") != normalize_text(user_text):
        return "user_text mismatch"
    for key, provided in {
        "message_id": message_id,
        "platform": platform,
        "session_key": session_key,
    }.items():
        row_value = str(row[key] or "")
        provided_value = clean(provided)
        if (row_value or provided_value) and row_value != provided_value:
            return f"{key} mismatch"
    checks = {
        "save_id": expected.save_id,
        "source_user_text_hash": expected.source_user_text_hash,
        "base_turn_id": expected.base_turn_id,
        "model_version": expected.model_version,
        "schema_version": expected.schema_version,
        "external_candidate_hash": expected.external_candidate_hash,
        "rule_candidate_hash": expected.rule_candidate_hash,
        "task_version": expected.task_version,
        "context_hash": expected.context_hash,
        "intent_context_id": expected.intent_context_id,
    }
    for key, expected_value in checks.items():
        if str(row[key]) != expected_value:
            return f"{key} mismatch"
    return ""


def update_preflight_status(
    conn: sqlite3.Connection,
    preflight_id: str,
    status: str,
    *,
    reason: str,
    current_status: str = PREFLIGHT_READY,
) -> bool:
    cursor = conn.execute(
        """
        update intent_preflight_cache
        set status=?, rejected_reason=?, updated_at=?
        where id=? and status=? and used_at is null
        """,
        (status, reason, utc_now(), preflight_id, current_status),
    )
    return cursor.rowcount == 1


def preflight_lookup_after_lost_transition(
    conn: sqlite3.Connection,
    preflight_id: str,
    fallback_record: PreflightRecord,
) -> PreflightLookupResult:
    row = conn.execute("select * from intent_preflight_cache where id=?", (preflight_id,)).fetchone()
    record = record_from_row(row) if row else fallback_record
    return PreflightLookupResult(record.status, record=record, reason=f"preflight is {record.status}")


def is_expired(value: str) -> bool:
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def meta_value(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("select value from meta where key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def save_id(campaign: Campaign) -> str:
    return str(campaign.root.expanduser().resolve())


def hash_text(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def hash_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def candidate_hash(value: dict[str, Any] | None) -> str:
    return hash_json(value or {})


def declared_text_hash_mismatch(user_text: str, source_user_text_hash: str = "") -> str:
    declared = clean(source_user_text_hash)
    actual = hash_text(user_text)
    if declared and declared != actual:
        return "source_user_text_hash mismatch"
    return ""


def assert_declared_text_hash(user_text: str, source_user_text_hash: str = "") -> None:
    mismatch = declared_text_hash_mismatch(user_text, source_user_text_hash)
    if mismatch:
        raise ValueError(mismatch)


def normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_identity_profile(value: str) -> str:
    profile = clean(value) or PREFLIGHT_IDENTITY_CANDIDATE_BOUND
    if profile not in PREFLIGHT_IDENTITY_PROFILES:
        raise ValueError(f"unsupported preflight identity_profile: {profile}")
    return profile


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_object(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
