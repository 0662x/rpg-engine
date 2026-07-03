from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER, DEFAULT_INTENT_TIMEOUT_SECONDS
from .campaign import load_campaign
from .game_session import (
    ACTIVE_GAME,
    COMMAND_PREFIXES,
    INACTIVE,
    PENDING_APPROVAL,
    PENDING_CLARIFICATION,
    SUPPORTED_CHAT_TYPES,
    SUPPORTED_MESSAGE_TYPES,
    GameSessionBinding,
    PlatformMessage,
    clean,
    hash_identity,
    hash_text,
    is_expired,
    normalize_text,
)
from .platform_prewarm import (
    GameSessionBindingStore,
    PlatformPrewarmConfig,
    PlatformPrewarmResult,
    PlatformPrewarmWorkerResult,
    PlatformPrewarmService,
    PrewarmDispatcher,
    PrewarmMetrics,
    PrewarmQueue,
    PrewarmWorker,
    elapsed_ms,
    percentile,
)
from .save_manager import SaveManager
from .runtime import GMRuntime


DEFAULT_PLATFORM_SESSION_TTL_SECONDS = 1800
DEFAULT_PLATFORM_PLAYER_PENDING_WAIT_MS = 200


@dataclass(frozen=True)
class PlatformSidecarConfig:
    prewarm: PlatformPrewarmConfig
    player_intent_ai: str = "consensus"
    player_intent_backend: str = "direct"
    player_intent_provider: str = DEFAULT_AI_PROVIDER
    player_intent_model: str = DEFAULT_AI_MODEL
    player_intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS
    player_intent_base_url: str = ""
    player_intent_api_key_env: str = ""
    player_intent_fallback_backend: str = "off"
    active_ttl_seconds: int = DEFAULT_PLATFORM_SESSION_TTL_SECONDS
    preflight_pending_wait_ms: int = DEFAULT_PLATFORM_PLAYER_PENDING_WAIT_MS

    @classmethod
    def from_prewarm_config(
        cls,
        prewarm: PlatformPrewarmConfig,
        *,
        player_intent_ai: str = "consensus",
        active_ttl_seconds: int = DEFAULT_PLATFORM_SESSION_TTL_SECONDS,
        preflight_pending_wait_ms: int = DEFAULT_PLATFORM_PLAYER_PENDING_WAIT_MS,
    ) -> "PlatformSidecarConfig":
        return cls(
            prewarm=prewarm,
            player_intent_ai=player_intent_ai,
            player_intent_backend=prewarm.intent_backend,
            player_intent_provider=prewarm.intent_provider,
            player_intent_model=prewarm.intent_model,
            player_intent_timeout=prewarm.intent_timeout,
            player_intent_base_url=prewarm.intent_base_url,
            player_intent_api_key_env=prewarm.intent_api_key_env,
            player_intent_fallback_backend=prewarm.intent_fallback_backend,
            active_ttl_seconds=active_ttl_seconds,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
        )


@dataclass(frozen=True)
class PlatformActionResult:
    result: dict[str, Any]
    prewarm: dict[str, Any] | None = None
    binding: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.result)
        data["platform_prewarm"] = self.prewarm
        data["platform_binding"] = self.binding
        data["platform_metrics"] = self.metrics
        return data


@dataclass(frozen=True)
class PlatformEntryGateResult:
    allow: bool
    reason: str
    kind: str
    platform: str = ""
    session_key_hash: str = ""
    message_id: str = ""
    active_save: str = ""
    binding_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "reason": self.reason,
            "kind": self.kind,
            "platform": self.platform,
            "session_key_hash": self.session_key_hash,
            "message_id": self.message_id,
            "active_save": self.active_save,
            "binding_state": self.binding_state,
        }


class PlatformSidecarMetrics:
    def __init__(self) -> None:
        self.message_event_count = 0
        self.start_count = 0
        self.player_act_count = 0
        self.player_confirm_count = 0
        self.ready_to_confirm_count = 0
        self.clarification_count = 0
        self.saved_count = 0
        self.error_count = 0
        self.player_visible_durations_ms: list[int] = []

    def record_message_event(self) -> None:
        self.message_event_count += 1

    def record_player_result(self, result: dict[str, Any], *, duration_ms: int, kind: str) -> None:
        if kind == "start":
            self.start_count += 1
        elif kind == "act":
            self.player_act_count += 1
        elif kind == "confirm":
            self.player_confirm_count += 1
        self.player_visible_durations_ms.append(max(0, int(duration_ms)))
        if result.get("ready_to_confirm"):
            self.ready_to_confirm_count += 1
        if result.get("clarification") or str(result.get("status") or "") in {"clarify", "needs_confirmation"}:
            self.clarification_count += 1
        if result.get("saved"):
            self.saved_count += 1
        if not bool(result.get("ok", True)):
            self.error_count += 1

    def snapshot(self) -> dict[str, Any]:
        durations = list(self.player_visible_durations_ms)
        average = int(sum(durations) / len(durations)) if durations else 0
        return {
            "message_event_count": self.message_event_count,
            "start_count": self.start_count,
            "player_act_count": self.player_act_count,
            "player_confirm_count": self.player_confirm_count,
            "ready_to_confirm_count": self.ready_to_confirm_count,
            "clarification_count": self.clarification_count,
            "saved_count": self.saved_count,
            "error_count": self.error_count,
            "user_visible_latency_average_ms": average,
            "user_visible_latency_p50_ms": percentile(durations, 0.50) if durations else 0,
            "user_visible_latency_p95_ms": percentile(durations, 0.95) if durations else 0,
        }


class PlatformSidecar:
    def __init__(
        self,
        root: str | Path,
        *,
        config: PlatformSidecarConfig | None = None,
        binding_store: GameSessionBindingStore | None = None,
        metrics: PrewarmMetrics | None = None,
        runtime_factory: Callable[[Path], Any] | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        prewarm_config = PlatformPrewarmConfig.from_env()
        self.config = config or PlatformSidecarConfig.from_prewarm_config(prewarm_config)
        self.binding_store = binding_store or GameSessionBindingStore(self.root)
        self.prewarm_metrics = metrics or PrewarmMetrics()
        self.prewarm_service = PlatformPrewarmService(
            self.root,
            config=self.config.prewarm,
            binding_store=self.binding_store,
            metrics=self.prewarm_metrics,
        )
        worker = PrewarmWorker(
            config=self.config.prewarm,
            metrics=self.prewarm_metrics,
            runtime_factory=runtime_factory or GMRuntime.from_path,
        )
        self.dispatcher = PrewarmDispatcher(
            queue_=self.prewarm_service.queue,
            worker=worker,
            worker_count=self.config.prewarm.worker_count,
        )
        self.metrics = PlatformSidecarMetrics()

    def start(self) -> None:
        self.dispatcher.start()

    def stop(self) -> None:
        self.dispatcher.stop()

    def handle_message_event(self, event: PlatformMessage | dict[str, Any]) -> PlatformPrewarmResult:
        self.expire_stale_bindings()
        message = ensure_platform_message(event)
        self.metrics.record_message_event()
        return self.prewarm_service.handle_message(message)

    def drain_prewarm(self, *, limit: int | None = None) -> list[PlatformPrewarmWorkerResult]:
        worker = self.dispatcher.worker
        return self.prewarm_service.queue.drain(worker, limit=limit)

    def start_or_continue_from_message(
        self,
        event: PlatformMessage | dict[str, Any],
        *,
        campaign: str | None = None,
        create_if_missing: bool = True,
        starter_save: str | None = None,
        label: str | None = None,
    ) -> PlatformActionResult:
        self.expire_stale_bindings()
        message = ensure_platform_message(event)
        started = time.monotonic()
        manager = SaveManager(self.root)
        result = manager.start_or_continue(
            campaign=campaign,
            user_text=message.text or "开始游戏",
            create_if_missing=create_if_missing,
            starter_save=starter_save,
            label=label,
        )
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="start")
        binding = self.activate_from_result(message, result)
        return PlatformActionResult(
            result=result,
            binding=binding_to_public_dict(binding),
            metrics=self.metrics_snapshot(),
        )

    def player_act_from_message(self, event: PlatformMessage | dict[str, Any]) -> PlatformActionResult:
        self.expire_stale_bindings()
        message = ensure_platform_message(event)
        started = time.monotonic()
        gate, binding = self.gate_player_entry(message, kind="act")
        if not gate.allow or binding is None:
            result = platform_gate_rejection(gate)
            self.metrics.record_player_result(result, duration_ms=elapsed_ms(started), kind="act")
            return PlatformActionResult(
                result=result,
                prewarm=platform_gate_prewarm_result(gate),
                binding=binding_to_public_dict(binding),
                metrics=self.metrics_snapshot(),
            )
        manager = SaveManager(self.root)
        pending_conflict = platform_pending_conflict(manager, binding, message)
        if pending_conflict:
            result = platform_gate_rejection(gate_with_reason(gate, pending_conflict))
            self.metrics.record_player_result(result, duration_ms=elapsed_ms(started), kind="act")
            return PlatformActionResult(
                result=result,
                prewarm=platform_gate_prewarm_result(gate_with_reason(gate, pending_conflict)),
                binding=binding_to_public_dict(binding),
                metrics=self.metrics_snapshot(),
            )
        prewarm = self.prewarm_service.handle_message(message)
        try:
            result = manager.player_turn(
                user_text=message.text,
                save_path=binding.active_save,
                intent_ai=self.config.player_intent_ai,
                intent_backend=self.config.player_intent_backend,
                intent_provider=self.config.player_intent_provider,
                intent_model=self.config.player_intent_model,
                intent_timeout=self.config.player_intent_timeout,
                intent_base_url=self.config.player_intent_base_url,
                intent_api_key_env=self.config.player_intent_api_key_env,
                intent_fallback_backend=self.config.player_intent_fallback_backend,
                message_id=message.message_id,
                platform=message.platform,
                session_key=message.session_key,
                source_user_text_hash=hash_text(message.text),
                preflight_pending_wait_ms=self.config.preflight_pending_wait_ms,
            )
        except Exception as exc:
            result = platform_manager_error(exc, gate=gate)
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="act")
        binding = self.activate_from_result(message, result, last_action_message_id=message.message_id)
        return PlatformActionResult(
            result=result,
            prewarm=prewarm.to_dict(),
            binding=binding_to_public_dict(binding),
            metrics=self.metrics_snapshot(),
        )

    def player_confirm_from_message(self, event: PlatformMessage | dict[str, Any], *, session_id: str) -> PlatformActionResult:
        self.expire_stale_bindings()
        message = ensure_platform_message(event)
        started = time.monotonic()
        gate, binding = self.gate_player_entry(message, kind="confirm")
        if not gate.allow or binding is None:
            result = platform_gate_rejection(gate)
            self.metrics.record_player_result(result, duration_ms=elapsed_ms(started), kind="confirm")
            return PlatformActionResult(
                result=result,
                binding=binding_to_public_dict(binding),
                metrics=self.metrics_snapshot(),
            )
        manager = SaveManager(self.root)
        try:
            result = manager.player_confirm(
                session_id=session_id,
                save_path=binding.active_save,
                platform=message.platform,
                session_key=message.session_key,
            )
        except Exception as exc:
            result = platform_manager_error(exc, gate=gate)
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="confirm")
        binding = self.activate_from_result(message, result, last_confirm_message_id=message.message_id)
        return PlatformActionResult(
            result=result,
            binding=binding_to_public_dict(binding),
            metrics=self.metrics_snapshot(),
        )

    def gate_player_entry(
        self,
        message: PlatformMessage,
        *,
        kind: str,
    ) -> tuple[PlatformEntryGateResult, GameSessionBinding | None]:
        binding = None
        if clean(message.platform) and clean(message.session_key):
            binding = self.binding_store.get(platform=message.platform, session_key=message.session_key)
        return platform_entry_gate(binding, message, kind=kind), binding

    def deactivate_from_message(self, event: PlatformMessage | dict[str, Any]) -> dict[str, Any] | None:
        message = ensure_platform_message(event)
        existing = self.binding_store.get(platform=message.platform, session_key=message.session_key)
        if existing is None:
            return None
        inactive = GameSessionBinding(
            platform=existing.platform,
            session_key_hash=existing.session_key_hash,
            active_save=existing.active_save,
            state=INACTIVE,
            active_until="",
            user_id_hash=existing.user_id_hash,
                last_message_id=existing.last_message_id,
                last_action_message_id=existing.last_action_message_id,
                last_confirm_message_id=existing.last_confirm_message_id,
                clarification_id=existing.clarification_id,
                updated_at=utc_now_compat(),
            )
        self.binding_store.upsert(inactive)
        return binding_to_public_dict(inactive)

    def activate_from_result(
        self,
        message: PlatformMessage,
        result: dict[str, Any],
        *,
        last_action_message_id: str = "",
        last_confirm_message_id: str = "",
    ) -> GameSessionBinding | None:
        if not bool(result.get("ok")) and not result.get("active_save_id"):
            return None
        save_path = active_save_path_from_result(self.root, result)
        if not save_path:
            return None
        clarification = result.get("clarification") if isinstance(result.get("clarification"), dict) else None
        if result.get("ready_to_confirm"):
            state = PENDING_APPROVAL
        elif clarification:
            state = PENDING_CLARIFICATION
        else:
            state = ACTIVE_GAME
        clarification_id = str(clarification.get("clarification_id") or "") if clarification else ""
        active_until = (datetime.now(timezone.utc) + timedelta(seconds=max(1, self.config.active_ttl_seconds))).isoformat()
        return self.binding_store.upsert_raw(
            platform=message.platform,
            session_key=message.session_key,
            user_id=message.actor_id,
            active_save=save_path,
            state=state,
            active_until=active_until,
            last_message_id=message.message_id,
            last_action_message_id=last_action_message_id,
            last_confirm_message_id=last_confirm_message_id,
            clarification_id=clarification_id,
        )

    def expire_stale_bindings(self, *, now: datetime | None = None) -> int:
        expired = 0
        for binding in self.binding_store.list_bindings():
            if binding.state == ACTIVE_GAME and is_expired(binding.active_until, now=now):
                self.binding_store.upsert(
                    GameSessionBinding(
                        platform=binding.platform,
                        session_key_hash=binding.session_key_hash,
                        active_save=binding.active_save,
                        state=INACTIVE,
                        active_until="",
                        user_id_hash=binding.user_id_hash,
                        last_message_id=binding.last_message_id,
                        last_action_message_id=binding.last_action_message_id,
                        last_confirm_message_id=binding.last_confirm_message_id,
                        clarification_id=binding.clarification_id,
                        updated_at=utc_now_compat(),
                    )
                )
                expired += 1
        return expired

    def metrics_snapshot(self) -> dict[str, Any]:
        bindings = self.binding_store.list_bindings()
        binding_counts: dict[str, int] = {}
        for binding in bindings:
            binding_counts[binding.state] = binding_counts.get(binding.state, 0) + 1
        return {
            "sidecar": self.metrics.snapshot(),
            "prewarm": self.prewarm_metrics.snapshot(queue_depth=self.prewarm_service.queue.qsize()),
            "bindings": {
                "total": len(bindings),
                "by_state": dict(sorted(binding_counts.items())),
            },
            "preflight_cache": collect_prewarm_cache_stats(self.root, bindings),
            "config": {
                "prewarm_enabled": self.config.prewarm.enabled,
                "player_intent_ai": self.config.player_intent_ai,
                "intent_backend": self.config.player_intent_backend,
                "intent_provider": self.config.player_intent_provider,
                "intent_model": self.config.player_intent_model,
                "intent_timeout": self.config.player_intent_timeout,
                "active_ttl_seconds": self.config.active_ttl_seconds,
                "preflight_pending_wait_ms": self.config.preflight_pending_wait_ms,
            },
        }


def ensure_platform_message(event: PlatformMessage | dict[str, Any]) -> PlatformMessage:
    if isinstance(event, PlatformMessage):
        return event
    return platform_message_from_event(event)


def platform_entry_gate(
    binding: GameSessionBinding | None,
    message: PlatformMessage,
    *,
    kind: str,
) -> PlatformEntryGateResult:
    platform = clean(message.platform)
    session_key = clean(message.session_key)
    message_id = clean(message.message_id)
    session_hash = hash_identity(session_key) if session_key else ""

    def decision(allow: bool, reason: str) -> PlatformEntryGateResult:
        return PlatformEntryGateResult(
            allow=allow,
            reason=reason,
            kind=kind,
            platform=platform,
            session_key_hash=session_hash,
            message_id=message_id,
            active_save=binding.active_save if binding else "",
            binding_state=binding.state if binding else "",
        )

    if not platform:
        return decision(False, "missing_platform")
    if not session_key:
        return decision(False, "missing_session_key")
    if not message_id:
        return decision(False, "missing_message_id")
    if binding is None:
        return decision(False, "inactive")
    if platform != binding.platform:
        return decision(False, "platform_mismatch")
    if session_hash != binding.session_key_hash:
        return decision(False, "session_mismatch")
    if not binding.active_save:
        return decision(False, "no_active_save")
    if is_expired(binding.active_until):
        return decision(False, "expired")
    if message.actor_is_bot or message.actor_is_self:
        return decision(False, "actor_not_allowed")
    if clean(message.message_type) not in SUPPORTED_MESSAGE_TYPES:
        return decision(False, "unsupported_message_type")
    if clean(message.chat_type) not in SUPPORTED_CHAT_TYPES:
        return decision(False, "unsupported_chat")

    if kind == "confirm":
        if binding.state not in {ACTIVE_GAME, PENDING_APPROVAL}:
            return decision(False, binding.state or INACTIVE)
        if message_id == binding.last_confirm_message_id:
            return decision(False, "duplicate_confirm_message")
        return decision(True, "allowed")

    if message_id == binding.last_action_message_id:
        return decision(False, "duplicate_action_message")
    if binding.state not in {ACTIVE_GAME, PENDING_CLARIFICATION}:
        return decision(False, binding.state or INACTIVE)
    if message.is_approval:
        return decision(False, PENDING_APPROVAL)
    text = normalize_text(message.text)
    if not text:
        return decision(False, "empty_text")
    if text.startswith(COMMAND_PREFIXES):
        return decision(False, "command")
    return decision(True, "allowed")


def gate_with_reason(gate: PlatformEntryGateResult, reason: str) -> PlatformEntryGateResult:
    return PlatformEntryGateResult(
        allow=False,
        reason=reason,
        kind=gate.kind,
        platform=gate.platform,
        session_key_hash=gate.session_key_hash,
        message_id=gate.message_id,
        active_save=gate.active_save,
        binding_state=gate.binding_state,
    )


def platform_pending_conflict(manager: SaveManager, binding: GameSessionBinding, message: PlatformMessage) -> str:
    try:
        pending_action = manager.read_pending_action()
        pending_clarification = manager.read_pending_clarification()
    except Exception:
        return "pending_state_error"
    for label, pending in (
        ("pending_action", pending_action),
        ("pending_clarification", pending_clarification),
    ):
        reason = pending_session_conflict(label, pending, binding=binding, message=message)
        if reason:
            return reason
    return ""


def pending_session_conflict(
    label: str,
    pending: dict[str, Any] | None,
    *,
    binding: GameSessionBinding,
    message: PlatformMessage,
) -> str:
    if not pending:
        return ""
    pending_save_path = clean(pending.get("save_path"))
    if pending_save_path and pending_save_path != binding.active_save:
        return f"{label}_save_mismatch"
    pending_platform = clean(pending.get("platform"))
    pending_session_hash = clean(pending.get("session_key_hash"))
    if not pending_platform and not pending_session_hash:
        return f"{label}_unscoped"
    if pending_platform and pending_platform != clean(message.platform):
        return f"{label}_platform_mismatch"
    if pending_session_hash and pending_session_hash != hash_identity(message.session_key):
        return f"{label}_session_mismatch"
    return ""


def platform_gate_rejection(gate: PlatformEntryGateResult) -> dict[str, Any]:
    message = platform_gate_message(gate.reason)
    return {
        "ok": False,
        "status": "platform_rejected",
        "action": None,
        "message": message,
        "ready_to_confirm": False,
        "session_id": None,
        "clarification": None,
        "pending_clarification_id": None,
        "saved": False,
        "warnings": [],
        "errors": [f"platform gate rejected: {gate.reason}"],
        "repair_options": [],
        "platform_gate": gate.to_dict(),
    }


def platform_gate_prewarm_result(gate: PlatformEntryGateResult) -> dict[str, Any]:
    return {
        "allow_platform": False,
        "enqueued": False,
        "dropped": True,
        "reason": gate.reason,
        "message_id": gate.message_id,
        "active_save": gate.active_save,
        "queue_depth": 0,
        "decision": gate.to_dict(),
    }


def platform_manager_error(exc: Exception, *, gate: PlatformEntryGateResult) -> dict[str, Any]:
    message = str(exc) or exc.__class__.__name__
    return {
        "ok": False,
        "status": "platform_error",
        "action": None,
        "message": message if message.endswith("\n") else message + "\n",
        "ready_to_confirm": False,
        "session_id": None,
        "clarification": None,
        "pending_clarification_id": None,
        "saved": False,
        "warnings": [],
        "errors": [message],
        "repair_options": [],
        "platform_gate": gate.to_dict(),
    }


def platform_gate_message(reason: str) -> str:
    messages = {
        "inactive": "这个平台会话还没有绑定游戏存档，请先开始或继续游戏。\n",
        "expired": "这个平台会话已经过期，请先重新开始或继续游戏。\n",
        "actor_not_allowed": "这条平台消息来自机器人或当前账号，已忽略。\n",
        "unsupported_message_type": "当前只支持文本消息。\n",
        "unsupported_chat": "当前平台会话类型暂不支持。\n",
        "command": "这条消息被识别为平台命令，不会推进游戏。\n",
        "empty_text": "没有可处理的玩家文本。\n",
        "duplicate_action_message": "这条平台消息已经处理过，已忽略重复行动。\n",
        "duplicate_confirm_message": "这条确认消息已经处理过，已忽略重复确认。\n",
        PENDING_APPROVAL: "正在等待你确认上一个行动，请先确认或重新开始。\n",
        PENDING_CLARIFICATION: "正在等待你回答上一个澄清问题。\n",
    }
    if reason.startswith("pending_action"):
        return "另一个平台会话有待确认行动，当前消息不会覆盖它。\n"
    if reason.startswith("pending_clarification"):
        return "另一个平台会话有待回答的澄清问题，当前消息不会覆盖它。\n"
    return messages.get(reason, f"平台入口拒绝处理：{reason}\n")


def platform_message_from_event(event: dict[str, Any], *, default_platform: str = "qq") -> PlatformMessage:
    platform = first_text(event, "platform", "source_platform") or default_platform
    text = first_text(event, "text", "raw_text", "content", "message", "message_text")
    message_id = first_text(event, "message_id", "msg_id", "id")
    actor_id = first_text(event, "actor_id", "user_id", "sender_id", "from_user_id")
    chat_type = normalize_chat_type(first_text(event, "chat_type", "conversation_type", "type"), event)
    session_key = first_text(event, "session_key") or derive_session_key(platform, chat_type, event, actor_id)
    message_type = normalize_message_type(first_text(event, "message_type", "content_type") or "text")
    return PlatformMessage(
        platform=clean(platform),
        session_key=session_key,
        message_id=message_id,
        text=text,
        message_type=message_type,
        chat_type=chat_type,
        actor_id=actor_id,
        actor_is_bot=bool(event.get("actor_is_bot") or event.get("sender_is_bot") or event.get("is_bot")),
        actor_is_self=bool(event.get("actor_is_self") or event.get("sender_is_self") or event.get("is_self")),
        is_approval=bool(event.get("is_approval") or event.get("approval")),
    )


def normalize_chat_type(value: str, event: dict[str, Any]) -> str:
    raw = clean(value).lower()
    if raw in {"private", "c2c", "friend", "dm"}:
        return "c2c"
    if raw in {"group_at", "group-at"}:
        return "group_at"
    if raw in {"group", "qq_group"} and bool(event.get("at_bot") or event.get("is_at") or event.get("mentioned_bot")):
        return "group_at"
    if raw in {"cli", "web"}:
        return raw
    return raw or "c2c"


def normalize_message_type(value: str) -> str:
    raw = clean(value).lower()
    if raw in {"plain", "text/plain"}:
        return "text"
    return raw or "text"


def derive_session_key(platform: str, chat_type: str, event: dict[str, Any], actor_id: str) -> str:
    conversation_id = first_text(event, "conversation_id", "session_id", "chat_id", "channel_id")
    group_id = first_text(event, "group_id", "guild_id")
    if conversation_id:
        return f"{clean(platform)}:conversation:{conversation_id}"
    if chat_type == "group_at" and group_id:
        return f"{clean(platform)}:group:{group_id}"
    if actor_id:
        return f"{clean(platform)}:user:{actor_id}"
    return ""


def first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and clean(value):
            return clean(value)
    return ""


def active_save_path_from_result(root: Path, result: dict[str, Any]) -> str:
    save = result.get("save") if isinstance(result.get("save"), dict) else None
    if save and clean(save.get("path")):
        return clean(save.get("path"))
    manager = SaveManager(root)
    current = manager.current_save(refresh=False)
    save = current.get("save") if isinstance(current.get("save"), dict) else None
    return clean(save.get("path")) if save else ""


def binding_to_public_dict(binding: GameSessionBinding | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "platform": binding.platform,
        "session_key_hash": binding.session_key_hash,
        "user_id_hash": binding.user_id_hash,
        "active_save": binding.active_save,
        "state": binding.state,
        "active_until": binding.active_until,
        "last_message_id": binding.last_message_id,
        "last_action_message_id": binding.last_action_message_id,
        "last_confirm_message_id": binding.last_confirm_message_id,
        "clarification_id": binding.clarification_id,
        "updated_at": binding.updated_at,
    }


def collect_prewarm_cache_stats(root: Path, bindings: list[GameSessionBinding]) -> dict[str, Any]:
    active_saves = sorted({binding.active_save for binding in bindings if binding.active_save})
    status_counts: dict[str, int] = {}
    late_ready_unused = 0
    errors: list[str] = []
    for active_save in active_saves:
        try:
            campaign = load_campaign((root / active_save).resolve())
            conn = sqlite3.connect(campaign.database_path)
            try:
                rows = conn.execute(
                    """
                    select status, count(*)
                    from intent_preflight_cache
                    where identity_profile='message_only'
                    group by status
                    """
                ).fetchall()
                for status, count in rows:
                    status_counts[str(status)] = status_counts.get(str(status), 0) + int(count)
                row = conn.execute(
                    """
                    select count(*)
                    from intent_preflight_cache
                    where identity_profile='message_only' and late_ready_unused_at is not null
                    """
                ).fetchone()
                late_ready_unused += int(row[0] if row else 0)
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"{active_save}: {exc}")
    used = status_counts.get("used", 0)
    ready = status_counts.get("ready", 0)
    failed = status_counts.get("failed", 0)
    rejected = status_counts.get("rejected", 0)
    consumed_or_missed = used + ready + failed + rejected
    hit_rate = round(used / consumed_or_missed, 4) if consumed_or_missed else 0.0
    return {
        "message_only_status_counts": dict(sorted(status_counts.items())),
        "message_only_used_count": used,
        "message_only_ready_count": ready,
        "message_only_late_ready_unused_count": late_ready_unused,
        "message_only_hit_rate_estimate": hit_rate,
        "errors": errors[:10],
    }


def utc_now_compat() -> str:
    return datetime.now(timezone.utc).isoformat()
