from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


ACTIVE_GAME = "active_game"
INACTIVE = "inactive"
PENDING_CLARIFICATION = "pending_clarification"
PENDING_APPROVAL = "pending_approval"
SUPPORTED_MESSAGE_TYPES = {"text"}
SUPPORTED_CHAT_TYPES = {"private", "c2c", "group_at", "cli", "web"}
COMMAND_PREFIXES = ("/", "!", ".")


@dataclass(frozen=True)
class GameSessionBinding:
    platform: str
    session_key_hash: str
    active_save: str
    state: str = INACTIVE
    active_until: str = ""
    user_id_hash: str = ""
    last_message_id: str = ""
    last_action_message_id: str = ""
    last_confirm_message_id: str = ""
    clarification_id: str = ""
    updated_at: str = ""

    @classmethod
    def from_raw(
        cls,
        *,
        platform: str,
        session_key: str,
        active_save: str,
        state: str = INACTIVE,
        active_until: str = "",
        user_id: str = "",
        last_message_id: str = "",
        last_action_message_id: str = "",
        last_confirm_message_id: str = "",
        clarification_id: str = "",
        updated_at: str = "",
    ) -> GameSessionBinding:
        return cls(
            platform=clean(platform),
            session_key_hash=hash_identity(session_key),
            active_save=clean(active_save),
            state=clean(state) or INACTIVE,
            active_until=clean(active_until),
            user_id_hash=hash_identity(user_id) if user_id else "",
            last_message_id=clean(last_message_id),
            last_action_message_id=clean(last_action_message_id),
            last_confirm_message_id=clean(last_confirm_message_id),
            clarification_id=clean(clarification_id),
            updated_at=clean(updated_at),
        )


@dataclass(frozen=True)
class PlatformMessage:
    platform: str
    session_key: str
    message_id: str
    text: str
    message_type: str = "text"
    chat_type: str = "private"
    actor_id: str = ""
    actor_is_bot: bool = False
    actor_is_self: bool = False
    is_approval: bool = False


@dataclass(frozen=True)
class GameSessionGateDecision:
    allow: bool
    reason: str
    platform: str = ""
    session_key_hash: str = ""
    message_id: str = ""
    active_save: str = ""
    normalized_text: str = ""
    source_user_text_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "reason": self.reason,
            "platform": self.platform,
            "session_key_hash": self.session_key_hash,
            "message_id": self.message_id,
            "active_save": self.active_save,
            "normalized_text": self.normalized_text,
            "source_user_text_hash": self.source_user_text_hash,
        }


def should_prewarm_message(
    binding: GameSessionBinding | None,
    message: PlatformMessage,
    *,
    now: datetime | None = None,
) -> GameSessionGateDecision:
    normalized_text = normalize_text(message.text)
    session_hash = hash_identity(message.session_key)
    base = {
        "platform": clean(message.platform),
        "session_key_hash": session_hash,
        "message_id": clean(message.message_id),
        "normalized_text": normalized_text,
        "source_user_text_hash": hash_text(normalized_text),
    }
    if binding is None:
        return gate(False, "inactive", **base)
    if clean(message.platform) != binding.platform:
        return gate(False, "platform_mismatch", active_save=binding.active_save, **base)
    if session_hash != binding.session_key_hash:
        return gate(False, "session_mismatch", active_save=binding.active_save, **base)
    if binding.state != ACTIVE_GAME:
        return gate(False, binding.state or INACTIVE, active_save=binding.active_save, **base)
    if not binding.active_save:
        return gate(False, "no_active_save", **base)
    if is_expired(binding.active_until, now=now):
        return gate(False, "expired", active_save=binding.active_save, **base)
    if not clean(message.message_id):
        return gate(False, "missing_message_id", active_save=binding.active_save, **base)
    if clean(message.message_id) and clean(message.message_id) == binding.last_message_id:
        return gate(False, "duplicate_message", active_save=binding.active_save, **base)
    if message.actor_is_bot or message.actor_is_self:
        return gate(False, "actor_not_allowed", active_save=binding.active_save, **base)
    if message.is_approval:
        return gate(False, PENDING_APPROVAL, active_save=binding.active_save, **base)
    if clean(message.message_type) not in SUPPORTED_MESSAGE_TYPES:
        return gate(False, "unsupported_message_type", active_save=binding.active_save, **base)
    if clean(message.chat_type) not in SUPPORTED_CHAT_TYPES:
        return gate(False, "unsupported_chat", active_save=binding.active_save, **base)
    if not normalized_text:
        return gate(False, "empty_text", active_save=binding.active_save, **base)
    if normalized_text.startswith(COMMAND_PREFIXES):
        return gate(False, "command", active_save=binding.active_save, **base)
    return gate(True, "active_game", active_save=binding.active_save, **base)


def gate(allow: bool, reason: str, **kwargs: Any) -> GameSessionGateDecision:
    return GameSessionGateDecision(allow=allow, reason=reason, **kwargs)


def is_expired(value: str, *, now: datetime | None = None) -> bool:
    if not clean(value):
        return True
    try:
        active_until = datetime.fromisoformat(value)
    except ValueError:
        return True
    if active_until.tzinfo is None:
        active_until = active_until.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return active_until <= current


def hash_identity(value: str) -> str:
    return hashlib.sha256(clean(value).encode("utf-8")).hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def clean(value: Any) -> str:
    return str(value or "").strip()
