from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
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
    game_session_binding_lock as platform_entry_file_lock,
    percentile,
    platform_message_id_is_valid,
    public_platform_message_id,
)
from .save_manager import (
    DEFAULT_PENDING_ACTION_TTL_SECONDS,
    MAX_PENDING_STRING_LENGTH,
    SaveManager,
    identity_input_is_bounded_utf8,
    player_identity_inputs_are_valid,
)
from .runtime import GMRuntime

DEFAULT_PLATFORM_SESSION_TTL_SECONDS = 1800
DEFAULT_PLATFORM_PLAYER_PENDING_WAIT_MS = 200
PRIVATE_GATE_REASONS = frozenset(
    {
        "actor_mismatch",
        "actor_not_allowed",
        "invalid_identity",
        "invalid_message_id",
        "missing_actor_id",
        "platform_mismatch",
        "session_mismatch",
    }
)


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
    audit_log: Path | None = None

    @classmethod
    def from_prewarm_config(
        cls,
        prewarm: PlatformPrewarmConfig,
        *,
        player_intent_ai: str = "consensus",
        player_intent_timeout: int = DEFAULT_INTENT_TIMEOUT_SECONDS,
        active_ttl_seconds: int = DEFAULT_PLATFORM_SESSION_TTL_SECONDS,
        preflight_pending_wait_ms: int = DEFAULT_PLATFORM_PLAYER_PENDING_WAIT_MS,
        audit_log: str | Path | None = None,
    ) -> "PlatformSidecarConfig":
        return cls(
            prewarm=prewarm,
            player_intent_ai=player_intent_ai,
            player_intent_backend=prewarm.intent_backend,
            player_intent_provider=prewarm.intent_provider,
            player_intent_model=prewarm.intent_model,
            player_intent_timeout=player_intent_timeout,
            player_intent_base_url=prewarm.intent_base_url,
            player_intent_api_key_env=prewarm.intent_api_key_env,
            player_intent_fallback_backend=prewarm.intent_fallback_backend,
            active_ttl_seconds=active_ttl_seconds,
            preflight_pending_wait_ms=preflight_pending_wait_ms,
            audit_log=Path(audit_log).expanduser() if audit_log is not None else None,
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
        redact_private = not self.allow and self.reason in PRIVATE_GATE_REASONS
        return {
            "allow": self.allow,
            "reason": self.reason,
            "kind": self.kind,
            "platform": self.platform,
            "session_key_hash": self.session_key_hash,
            "message_id": self.message_id,
            "active_save": "" if redact_private else self.active_save,
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
        self.audit_log = resolve_platform_audit_log_path(self.root, self.config.audit_log)
        self._entry_lock = threading.Lock()
        self._start_message_reservations: set[tuple[str, str, str]] = set()

    def start(self) -> None:
        self.dispatcher.start()

    def stop(self) -> None:
        self.dispatcher.stop()

    def handle_message_event(self, event: PlatformMessage | dict[str, Any]) -> PlatformPrewarmResult:
        message = ensure_platform_message(event)
        started = time.monotonic()
        if platform_message_identity_fields_are_valid(message):
            self.expire_stale_bindings(audit=False)
        self.metrics.record_message_event()
        try:
            result = self.prewarm_service.handle_message(message)
        except Exception as exc:
            self._write_platform_audit_record(
                "PlatformSidecar.handle_message_event",
                message,
                platform_exception_result(exc),
                duration_ms=elapsed_ms(started),
                surface_category="platform prewarm",
            )
            raise
        self._write_platform_audit_record(
            "PlatformSidecar.handle_message_event",
            message,
            result.to_dict(),
            duration_ms=elapsed_ms(started),
            surface_category="platform prewarm",
        )
        return result

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
        message = ensure_platform_message(event)
        started = time.monotonic()
        if platform_message_identity_fields_are_valid(message):
            self.expire_stale_bindings(audit=False)
        gate = platform_start_gate(message)
        start_key = platform_start_reservation_key(message)
        start_previous: GameSessionBinding | None = None
        start_reservation: GameSessionBinding | None = None
        if gate.allow:
            with self._entry_lock, platform_entry_file_lock(self.root):
                start_previous = self.binding_store.get(
                    platform=message.platform,
                    session_key=message.session_key,
                )
                gate, _ = self._reserve_platform_start_message(message, gate, start_key=start_key)
                if gate.allow:
                    start_reservation = self.binding_store.get(
                        platform=message.platform,
                        session_key=message.session_key,
                    )
        if not gate.allow:
            result = platform_gate_rejection(gate)
            duration_ms = elapsed_ms(started)
            self.metrics.record_player_result(result, duration_ms=duration_ms, kind="start")
            action_result = PlatformActionResult(
                result=result,
                prewarm=platform_gate_prewarm_result(gate),
                binding=None,
                metrics=(
                    None
                    if gate.reason in PRIVATE_GATE_REASONS
                    else self.metrics_snapshot(audit=False)
                ),
            )
            self._write_platform_audit_record(
                "PlatformSidecar.start_or_continue_from_message",
                message,
                action_result.to_dict(),
                duration_ms=duration_ms,
            )
            return action_result
        manager = SaveManager(self.root)
        try:
            result = manager.start_or_continue(
                campaign=campaign,
                user_text=message.text or "开始游戏",
                create_if_missing=create_if_missing,
                starter_save=starter_save,
                label=label,
            )
        except Exception as exc:
            self._write_platform_audit_record(
                "PlatformSidecar.start_or_continue_from_message",
                message,
                platform_exception_result(exc),
                duration_ms=elapsed_ms(started),
            )
            with self._entry_lock, platform_entry_file_lock(self.root):
                self._start_message_reservations.discard(start_key)
                self._rollback_platform_start_reservation(
                    message,
                    expected=start_reservation,
                    previous=start_previous,
                )
            raise
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="start")
        with self._entry_lock, platform_entry_file_lock(self.root):
            current = self.binding_store.get(platform=message.platform, session_key=message.session_key)
            if (
                start_reservation is None
                or current is None
                or completion_binding_context_changed(start_reservation, current)
            ):
                binding = current
            else:
                activated = self.activate_from_result(message, result, reserved_binding=current)
                if activated is None:
                    self._rollback_platform_start_reservation(
                        message,
                        expected=start_reservation,
                        previous=start_previous,
                    )
                    binding = self.binding_store.get(
                        platform=message.platform,
                        session_key=message.session_key,
                    )
                else:
                    binding = activated
            self._start_message_reservations.discard(start_key)
        action_result = PlatformActionResult(
            result=result,
            binding=binding_to_public_dict(binding),
            metrics=self.metrics_snapshot(audit=False),
        )
        self._write_platform_audit_record(
            "PlatformSidecar.start_or_continue_from_message",
            message,
            action_result.to_dict(),
            duration_ms=duration_ms,
        )
        return action_result

    def player_act_from_message(self, event: PlatformMessage | dict[str, Any]) -> PlatformActionResult:
        message = ensure_platform_message(event)
        started = time.monotonic()
        if platform_message_identity_fields_are_valid(message):
            self.expire_stale_bindings(audit=False)
        manager: SaveManager | None = None
        with self._entry_lock, platform_entry_file_lock(self.root):
            gate, binding = self.gate_player_entry(message, kind="act")
            if gate.allow and binding is not None:
                manager = SaveManager(self.root)
                binding = self._reserve_platform_message(binding, message, kind="act")
        if not gate.allow or binding is None:
            result = platform_gate_rejection(gate)
            duration_ms = elapsed_ms(started)
            self.metrics.record_player_result(result, duration_ms=duration_ms, kind="act")
            action_result = PlatformActionResult(
                result=result,
                prewarm=platform_gate_prewarm_result(gate),
                binding=binding_to_public_dict(binding, redact_private=gate.reason in PRIVATE_GATE_REASONS),
                metrics=(None if gate.reason in PRIVATE_GATE_REASONS else self.metrics_snapshot(audit=False)),
            )
            self._write_platform_audit_record(
                "PlatformSidecar.player_act_from_message",
                message,
                action_result.to_dict(),
                duration_ms=duration_ms,
            )
            return action_result
        try:
            prewarm = self.prewarm_service.handle_message(message)
        except Exception:
            prewarm = platform_advisory_prewarm_error(message, binding)
        if manager is None:
            manager = SaveManager(self.root)
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
                actor_id=message.actor_id,
                expected_pending_id=(
                    binding.clarification_id if binding.state == PENDING_CLARIFICATION else ""
                ),
                clarification_id=(
                    binding.clarification_id if binding.state == PENDING_CLARIFICATION else ""
                ),
                source_user_text_hash=hash_text(message.text),
                preflight_pending_wait_ms=self.config.preflight_pending_wait_ms,
            )
        except Exception as exc:
            result = platform_manager_error(exc, gate=gate)
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="act")
        with self._entry_lock, platform_entry_file_lock(self.root):
            current = self.binding_store.get(platform=message.platform, session_key=message.session_key)
            if current is None or completion_binding_context_changed(binding, current):
                if current is not None and current.state == INACTIVE:
                    binding = current
                else:
                    canonical = (
                        self._canonical_pending_result(manager, message, current)
                        if current is not None
                        else None
                    )
                    if current is not None and canonical is not None:
                        binding = self.activate_from_result(
                            message,
                            canonical,
                            last_action_message_id=current.last_action_message_id,
                            reserved_binding=current,
                        ) or current
                    else:
                        binding = current or binding
            else:
                canonical = self._canonical_pending_result(manager, message, current)
                if canonical is None:
                    binding = current
                else:
                    binding = self.activate_from_result(
                        message,
                        canonical,
                        last_action_message_id=message.message_id,
                        reserved_binding=current,
                    ) or current
        action_result = PlatformActionResult(
            result=result,
            prewarm=prewarm.to_dict(),
            binding=binding_to_public_dict(binding),
            metrics=self.metrics_snapshot(audit=False),
        )
        self._write_platform_audit_record(
            "PlatformSidecar.player_act_from_message",
            message,
            action_result.to_dict(),
            duration_ms=duration_ms,
        )
        return action_result

    def player_confirm_from_message(self, event: PlatformMessage | dict[str, Any], *, session_id: str) -> PlatformActionResult:
        message = ensure_platform_message(event)
        started = time.monotonic()
        if platform_message_identity_fields_are_valid(message):
            self.expire_stale_bindings(audit=False)
        with self._entry_lock, platform_entry_file_lock(self.root):
            gate, binding = self.gate_player_entry(message, kind="confirm")
            if gate.allow and binding is not None:
                binding = self._reserve_platform_message(binding, message, kind="confirm")
        if not gate.allow or binding is None:
            result = platform_gate_rejection(gate)
            duration_ms = elapsed_ms(started)
            self.metrics.record_player_result(result, duration_ms=duration_ms, kind="confirm")
            action_result = PlatformActionResult(
                result=result,
                binding=binding_to_public_dict(binding, redact_private=gate.reason in PRIVATE_GATE_REASONS),
                metrics=(None if gate.reason in PRIVATE_GATE_REASONS else self.metrics_snapshot(audit=False)),
            )
            self._write_platform_audit_record(
                "PlatformSidecar.player_confirm_from_message",
                message,
                action_result.to_dict(),
                duration_ms=duration_ms,
            )
            return action_result
        manager = SaveManager(self.root)
        try:
            result = manager.player_confirm(
                session_id=session_id,
                save_path=binding.active_save,
                platform=message.platform,
                session_key=message.session_key,
                actor_id=message.actor_id,
            )
        except Exception as exc:
            result = platform_manager_error(exc, gate=gate)
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="confirm")
        binding = self._merge_confirm_result_binding(
            message,
            result,
            fallback=binding,
            confirmation_session_id=session_id,
        )
        action_result = PlatformActionResult(
            result=result,
            binding=binding_to_public_dict(binding),
            metrics=self.metrics_snapshot(audit=False),
        )
        self._write_platform_audit_record(
            "PlatformSidecar.player_confirm_from_message",
            message,
            action_result.to_dict(),
            duration_ms=duration_ms,
        )
        return action_result

    def player_cancel_from_message(
        self,
        event: PlatformMessage | dict[str, Any],
        *,
        expected_pending_id: str,
    ) -> PlatformActionResult:
        message = ensure_platform_message(event)
        started = time.monotonic()
        if platform_message_identity_fields_are_valid(message):
            self.expire_stale_bindings(audit=False)
        manager: SaveManager | None = None
        with self._entry_lock, platform_entry_file_lock(self.root):
            gate, binding = self.gate_player_entry(message, kind="cancel")
        if not gate.allow or binding is None:
            result = platform_gate_rejection(gate)
        else:
            try:
                manager = SaveManager(self.root)
                result = manager.player_cancel(
                    expected_pending_id,
                    save_path=binding.active_save,
                    platform=message.platform,
                    session_key=message.session_key,
                    actor_id=message.actor_id,
                )
            except Exception as exc:
                result = platform_manager_error(exc, gate=gate)
        duration_ms = elapsed_ms(started)
        self.metrics.record_player_result(result, duration_ms=duration_ms, kind="cancel")
        if binding is not None and result.get("ok") and result.get("status") in {"canceled", "expired", "not_found"}:
            with self._entry_lock, platform_entry_file_lock(self.root):
                current = self.binding_store.get(platform=message.platform, session_key=message.session_key)
                if current is None:
                    binding = None
                else:
                    canonical: dict[str, Any] | None = None
                    canonical_terminal = False
                    canonical_check_failed = False
                    try:
                        inspected = (manager or SaveManager(self.root)).inspect_pending(
                            save_path=current.active_save,
                            platform=message.platform,
                            session_key=message.session_key,
                            actor_id=message.actor_id,
                        )
                        classification = canonical_pending_inspect_classification(inspected)
                        if classification == "active":
                            canonical = inspected
                        elif classification == "terminal":
                            canonical_terminal = True
                        else:
                            canonical_check_failed = True
                    except Exception:
                        canonical_check_failed = True
                    if (
                        canonical_check_failed
                        or completion_binding_context_changed(binding, current)
                        or current.state == INACTIVE
                    ):
                        binding = current
                    elif canonical is not None:
                        binding = self.activate_from_result(
                            message,
                            canonical,
                            last_action_message_id=current.last_action_message_id,
                            reserved_binding=current,
                        ) or current
                    elif canonical_terminal:
                        binding = self.binding_store.upsert_raw(
                            platform=message.platform,
                            session_key=message.session_key,
                            user_id=message.actor_id,
                            active_save=current.active_save,
                            state=ACTIVE_GAME,
                            active_until=current.active_until,
                            last_message_id=message.message_id,
                            last_action_message_id=current.last_action_message_id,
                            last_confirm_message_id=current.last_confirm_message_id,
                            pending_confirmation_session_hash="",
                            last_completed_confirmation_session_hash=current.last_completed_confirmation_session_hash,
                            clarification_id="",
                        )
                    else:
                        binding = current
        action_result = PlatformActionResult(
            result=result,
            binding=binding_to_public_dict(
                binding,
                redact_private=not gate.allow and gate.reason in PRIVATE_GATE_REASONS,
            ),
            metrics=(
                None
                if not gate.allow and gate.reason in PRIVATE_GATE_REASONS
                else self.metrics_snapshot(audit=False)
            ),
        )
        self._write_platform_audit_record(
            "PlatformSidecar.player_cancel_from_message",
            message,
            action_result.to_dict(),
            duration_ms=duration_ms,
        )
        return action_result

    def gate_player_entry(
        self,
        message: PlatformMessage,
        *,
        kind: str,
    ) -> tuple[PlatformEntryGateResult, GameSessionBinding | None]:
        binding = None
        if (
            all(
                identity_input_is_bounded_utf8(value)
                for value in (message.platform, message.session_key, message.actor_id)
            )
            and clean(message.platform)
            and clean(message.session_key)
        ):
            binding = self.binding_store.get(platform=message.platform, session_key=message.session_key)
        return platform_entry_gate(binding, message, kind=kind), binding

    def _canonical_pending_result(
        self,
        manager: SaveManager,
        message: PlatformMessage,
        binding: GameSessionBinding,
    ) -> dict[str, Any] | None:
        try:
            inspected = manager.inspect_pending(
                save_path=binding.active_save,
                platform=message.platform,
                session_key=message.session_key,
                actor_id=message.actor_id,
            )
        except Exception:
            return None
        if canonical_pending_inspect_classification(inspected) in {"active", "terminal"}:
            return inspected
        return None

    def _reserve_platform_start_message(
        self,
        message: PlatformMessage,
        gate: PlatformEntryGateResult,
        *,
        start_key: tuple[str, str, str],
    ) -> tuple[PlatformEntryGateResult, bool]:
        existing = self.binding_store.get(platform=message.platform, session_key=message.session_key)
        if existing is not None and clean(existing.last_message_id) == clean(message.message_id):
            return gate_with_reason(gate, "duplicate_start_message"), False
        if existing is not None and not existing.active_save and clean(existing.last_message_id):
            return gate_with_reason(gate, "start_in_progress"), False
        if start_key in self._start_message_reservations:
            return gate_with_reason(gate, "duplicate_start_message"), False
        self._start_message_reservations.add(start_key)
        if existing is None:
            self.binding_store.upsert(
                GameSessionBinding(
                    platform=clean(message.platform),
                    session_key_hash=hash_identity(message.session_key),
                    active_save="",
                    state=INACTIVE,
                    active_until="",
                    user_id_hash=hash_identity(message.actor_id) if clean(message.actor_id) else "",
                    last_message_id=clean(message.message_id),
                    revision=1,
                    updated_at=utc_now_compat(),
                )
            )
            return gate, True
        self.binding_store.upsert(
            GameSessionBinding(
                platform=existing.platform,
                session_key_hash=existing.session_key_hash,
                active_save=existing.active_save,
                state=existing.state,
                active_until=existing.active_until,
                user_id_hash=existing.user_id_hash,
                last_message_id=clean(message.message_id),
                last_action_message_id=existing.last_action_message_id,
                last_confirm_message_id=existing.last_confirm_message_id,
                pending_confirmation_session_hash=existing.pending_confirmation_session_hash,
                pending_confirmation_revision=existing.pending_confirmation_revision,
                last_completed_confirmation_session_hash=existing.last_completed_confirmation_session_hash,
                clarification_id=existing.clarification_id,
                revision=existing.revision + 1,
                updated_at=utc_now_compat(),
            )
        )
        return gate, False

    def _rollback_platform_start_reservation(
        self,
        message: PlatformMessage,
        *,
        expected: GameSessionBinding | None,
        previous: GameSessionBinding | None,
    ) -> None:
        current = self.binding_store.get(platform=message.platform, session_key=message.session_key)
        if expected is None or current is None or start_reservation_context_changed(expected, current):
            return
        if previous is None:
            self.binding_store.delete(platform=message.platform, session_key=message.session_key)
            return
        self.binding_store.upsert(
            GameSessionBinding(
                platform=previous.platform,
                session_key_hash=previous.session_key_hash,
                active_save=previous.active_save,
                state=previous.state,
                active_until=previous.active_until,
                user_id_hash=previous.user_id_hash,
                last_message_id=(
                    previous.last_message_id
                    if clean(current.last_message_id) == clean(message.message_id)
                    else current.last_message_id
                ),
                last_action_message_id=previous.last_action_message_id,
                last_confirm_message_id=current.last_confirm_message_id,
                pending_confirmation_session_hash=previous.pending_confirmation_session_hash,
                pending_confirmation_revision=previous.pending_confirmation_revision,
                last_completed_confirmation_session_hash=previous.last_completed_confirmation_session_hash,
                clarification_id=previous.clarification_id,
                revision=previous.revision,
                updated_at=utc_now_compat(),
            )
        )

    def _reserve_platform_message(
        self,
        binding: GameSessionBinding,
        message: PlatformMessage,
        *,
        kind: str,
    ) -> GameSessionBinding:
        next_revision = binding.revision + (1 if kind == "act" else 0)
        pending_confirmation_revision = (
            next_revision
            if kind == "act" and binding.pending_confirmation_session_hash
            else binding.pending_confirmation_revision
        )
        reserved = GameSessionBinding(
            platform=binding.platform,
            session_key_hash=binding.session_key_hash,
            active_save=binding.active_save,
            state=binding.state,
            active_until=binding.active_until,
            user_id_hash=binding.user_id_hash,
            last_message_id=message.message_id,
            last_action_message_id=message.message_id if kind == "act" else binding.last_action_message_id,
            last_confirm_message_id=message.message_id if kind == "confirm" else binding.last_confirm_message_id,
            pending_confirmation_session_hash=binding.pending_confirmation_session_hash,
            pending_confirmation_revision=pending_confirmation_revision,
            last_completed_confirmation_session_hash=binding.last_completed_confirmation_session_hash,
            clarification_id=binding.clarification_id,
            revision=next_revision,
            updated_at=utc_now_compat(),
        )
        self.binding_store.upsert(reserved)
        return reserved

    def deactivate_from_message(self, event: PlatformMessage | dict[str, Any]) -> dict[str, Any] | None:
        started = time.monotonic()
        message = ensure_platform_message(event)
        existing: GameSessionBinding | None = None
        with self._entry_lock, platform_entry_file_lock(self.root):
            if platform_message_identity_fields_are_valid(message):
                existing = self.binding_store.get(
                    platform=message.platform,
                    session_key=message.session_key,
                )
            if existing is not None:
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
                    pending_confirmation_session_hash=existing.pending_confirmation_session_hash,
                    pending_confirmation_revision=existing.pending_confirmation_revision,
                    last_completed_confirmation_session_hash=existing.last_completed_confirmation_session_hash,
                    clarification_id=existing.clarification_id,
                    revision=existing.revision + 1,
                    updated_at=utc_now_compat(),
                )
                self.binding_store.upsert(inactive)
        if existing is None:
            self._write_platform_audit_record(
                "PlatformSidecar.deactivate_from_message",
                message,
                {"ok": False, "status": "not_found"},
                duration_ms=elapsed_ms(started),
            )
            return None
        result = binding_to_public_dict(inactive)
        self._write_platform_audit_record(
            "PlatformSidecar.deactivate_from_message",
            message,
            {"ok": True, "binding": result},
            duration_ms=elapsed_ms(started),
        )
        return result

    def activate_from_result(
        self,
        message: PlatformMessage,
        result: dict[str, Any],
        *,
        last_action_message_id: str = "",
        last_confirm_message_id: str = "",
        reserved_binding: GameSessionBinding | None = None,
        completed_confirmation_session_hash: str | None = None,
    ) -> GameSessionBinding | None:
        clarification = result.get("clarification") if isinstance(result.get("clarification"), dict) else None
        lifecycle = result.get("lifecycle") if isinstance(result.get("lifecycle"), dict) else {}
        lifecycle_kind = clean(lifecycle.get("kind"))
        lifecycle_state = clean(lifecycle.get("state"))
        lifecycle_id = clean(lifecycle.get("pending_id"))
        terminal_supersede = (
            lifecycle_state == "superseded"
            and not bool(result.get("ready_to_confirm"))
            and clarification is None
            and not clean(result.get("pending_clarification_id"))
            and not clean(result.get("session_id"))
        )
        retained_state = lifecycle_state in {"active", "preserved", "migrated"} or (
            lifecycle_state == "superseded" and not terminal_supersede
        )
        canonical_pending = lifecycle_kind in {"action", "clarification"} and retained_state
        if not bool(result.get("ok")) and not canonical_pending and not terminal_supersede:
            return reserved_binding
        save_path = active_save_path_from_result(
            self.root,
            result,
            fallback=reserved_binding.active_save if reserved_binding is not None else "",
        )
        if not save_path:
            return None
        if lifecycle_kind == "action" and retained_state:
            state = PENDING_APPROVAL
        elif lifecycle_kind == "clarification" and retained_state:
            state = PENDING_CLARIFICATION
        elif result.get("ready_to_confirm"):
            state = PENDING_APPROVAL
        elif clarification:
            state = PENDING_CLARIFICATION
        else:
            state = ACTIVE_GAME
        clarification_id = (
            lifecycle_id
            if state == PENDING_CLARIFICATION and lifecycle_id
            else (str(clarification.get("clarification_id") or "") if clarification else "")
        )
        pending_confirmation_session_hash = ""
        confirmation_session_id = clean(result.get("session_id")) or (lifecycle_id if state == PENDING_APPROVAL else "")
        if state == PENDING_APPROVAL and confirmation_session_id:
            pending_confirmation_session_hash = hash_identity(confirmation_session_id)
        active_until = (datetime.now(timezone.utc) + timedelta(seconds=max(1, self.config.active_ttl_seconds))).isoformat()
        last_message_id = reserved_binding.last_message_id if reserved_binding else message.message_id
        if reserved_binding is not None:
            last_action_message_id = reserved_binding.last_action_message_id or last_action_message_id
            last_confirm_message_id = reserved_binding.last_confirm_message_id or last_confirm_message_id
        return self.binding_store.upsert_raw(
            platform=message.platform,
            session_key=message.session_key,
            user_id=message.actor_id,
            active_save=save_path,
            state=state,
            active_until=active_until,
            last_message_id=last_message_id,
            last_action_message_id=last_action_message_id,
            last_confirm_message_id=last_confirm_message_id,
            pending_confirmation_session_hash=pending_confirmation_session_hash,
            last_completed_confirmation_session_hash=completed_confirmation_session_hash,
            clarification_id=clarification_id,
        )

    def _merge_confirm_result_binding(
        self,
        message: PlatformMessage,
        result: dict[str, Any],
        *,
        fallback: GameSessionBinding,
        confirmation_session_id: str,
    ) -> GameSessionBinding:
        confirmation_session_hash = hash_identity(clean(confirmation_session_id))
        with self._entry_lock, platform_entry_file_lock(self.root):
            current = self.binding_store.get(platform=message.platform, session_key=message.session_key)
            if result.get("idempotent_replay") is True:
                if replay_confirmation_binding_needs_reconcile(
                    self.root,
                    current,
                    result,
                    confirmation_session_hash=confirmation_session_hash,
                    expected_revision=fallback.revision,
                ):
                    assert current is not None
                    reconciled = GameSessionBinding(
                        platform=current.platform,
                        session_key_hash=current.session_key_hash,
                        active_save=current.active_save,
                        state=ACTIVE_GAME,
                        active_until=current.active_until,
                        user_id_hash=current.user_id_hash,
                        last_message_id=current.last_message_id,
                        last_action_message_id=current.last_action_message_id,
                        last_confirm_message_id=current.last_confirm_message_id,
                        pending_confirmation_session_hash="",
                        pending_confirmation_revision=0,
                        last_completed_confirmation_session_hash=confirmation_session_hash,
                        clarification_id="",
                        revision=current.revision + 1,
                        updated_at=utc_now_compat(),
                    )
                    self.binding_store.upsert(reconciled)
                    return reconciled
                return current or fallback
            if current is not None and confirmation_binding_context_changed(fallback, current):
                return current
            if current is None or not confirmation_binding_matches_session(
                current,
                result,
                confirmation_session_hash=confirmation_session_hash,
            ):
                return current or fallback
            activated = self.activate_from_result(
                message,
                result,
                last_confirm_message_id=message.message_id,
                reserved_binding=current,
                completed_confirmation_session_hash=confirmation_session_hash,
            )
            return activated or current or fallback

    def expire_stale_bindings(self, *, now: datetime | None = None, audit: bool = True) -> int:
        started = time.monotonic()
        expired = 0
        with self._entry_lock, platform_entry_file_lock(self.root):
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
                            pending_confirmation_session_hash=binding.pending_confirmation_session_hash,
                            pending_confirmation_revision=binding.pending_confirmation_revision,
                            last_completed_confirmation_session_hash=binding.last_completed_confirmation_session_hash,
                            clarification_id=binding.clarification_id,
                            revision=binding.revision + 1,
                            updated_at=utc_now_compat(),
                        )
                    )
                    expired += 1
        if audit:
            self._write_platform_audit_record(
                "PlatformSidecar.expire_stale_bindings",
                None,
                {"ok": True, "expired": expired},
                duration_ms=elapsed_ms(started),
            )
        return expired

    def metrics_snapshot(self, *, audit: bool = True) -> dict[str, Any]:
        started = time.monotonic()
        bindings = self.binding_store.list_bindings()
        binding_counts: dict[str, int] = {}
        for binding in bindings:
            binding_counts[binding.state] = binding_counts.get(binding.state, 0) + 1
        snapshot = {
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
        if audit:
            self._write_platform_audit_record(
                "PlatformSidecar.metrics_snapshot",
                None,
                {"ok": True, "metrics": snapshot},
                duration_ms=elapsed_ms(started),
            )
        return snapshot

    def _write_platform_audit_record(
        self,
        operation: str,
        message: PlatformMessage | None,
        result: dict[str, Any],
        *,
        duration_ms: int,
        surface_category: str = "platform sidecar",
    ) -> None:
        path = self.audit_log
        if path is None:
            return
        try:
            record = {
                "created_at": utc_now_compat(),
                "operation": operation,
                "surface_category": surface_category,
                "duration_ms": duration_ms,
                "status": platform_audit_status(result),
                "identity": platform_audit_identity(message),
                "request": platform_audit_request_summary(message),
                "result": platform_audit_result_summary(result, message=message),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception as exc:  # pragma: no cover - audit must never break platform calls
            print(f"aigm-kernel platform audit write failed: {exc}", file=sys.stderr)


def ensure_platform_message(event: PlatformMessage | dict[str, Any]) -> PlatformMessage:
    if isinstance(event, PlatformMessage):
        return event
    return platform_message_from_event(event)


def platform_message_identity_fields_are_valid(message: PlatformMessage) -> bool:
    return (
        player_identity_inputs_are_valid(
            platform=message.platform,
            session_key=message.session_key,
            actor_id=message.actor_id,
        )
        and platform_message_id_is_valid(message.message_id)
    )


def resolve_platform_audit_log_path(root: Path, audit_log: str | Path | None) -> Path | None:
    if audit_log is None:
        return None
    path = Path(audit_log).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def platform_audit_identity(message: PlatformMessage | None) -> dict[str, Any]:
    if message is None:
        return {}
    platform = clean(message.platform) if identity_input_is_bounded_utf8(message.platform) else ""
    session_key = clean(message.session_key) if identity_input_is_bounded_utf8(message.session_key) else ""
    actor_id = clean(message.actor_id) if identity_input_is_bounded_utf8(message.actor_id) else ""
    message_id = (
        clean(message.message_id)
        if platform_message_id_is_valid(message.message_id)
        else "<invalid message id>"
    )
    identity: dict[str, Any] = {"platform": platform, "message_id": message_id}
    if session_key:
        identity["session_key_hash"] = bounded_platform_audit_hash(message.session_key)
    if actor_id:
        identity["actor_id_hash"] = bounded_platform_audit_hash(message.actor_id)
    return {key: value for key, value in identity.items() if value}


def bounded_platform_audit_hash(value: Any) -> str:
    if not identity_input_is_bounded_utf8(value):
        return "<invalid identity>"
    normalized = value.strip()
    return f"sha256:{hash_identity(normalized)}" if normalized else ""


def platform_audit_request_summary(message: PlatformMessage | None) -> dict[str, Any]:
    if message is None:
        return {}
    summary = dict(platform_audit_identity(message))
    summary.update(
        {
            "chat_type": clean(message.chat_type),
            "message_type": clean(message.message_type),
            "text_hash": hash_text(message.text),
            "text_preview": sanitize_platform_audit_text(message.text, max_text=180),
            "is_approval": bool(message.is_approval),
        }
    )
    return {key: value for key, value in summary.items() if value not in {"", None}}


def platform_audit_result_summary(result: dict[str, Any], *, message: PlatformMessage | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    sensitive_terms = platform_audit_sensitive_terms(message)
    for key in (
        "ok",
        "status",
        "action",
        "ready_to_confirm",
        "session_id",
        "pending_id",
        "clarification_id",
        "pending_clarification_id",
        "saved",
        "write_status",
        "idempotent_replay",
        "projection_status",
        "allow_platform",
        "enqueued",
        "dropped",
        "reason",
        "message_id",
        "active_save",
        "queue_depth",
        "decision",
        "expired",
        "binding",
        "metrics",
        "errors",
        "warnings",
        "platform_gate",
        "platform_prewarm",
        "platform_binding",
    ):
        if key in result:
            if key in {
                "session_id",
                "pending_id",
                "clarification_id",
                "pending_clarification_id",
            }:
                raw_token = str(result[key] or "")
                summary[key] = f"sha256:{hash_identity(raw_token)}" if raw_token.strip() else ""
            else:
                summary[key] = sanitize_platform_audit_value(
                    result[key],
                    sensitive_terms=sensitive_terms,
                )
    redacted = count_redacted_platform_payloads(result)
    if redacted:
        summary["redacted_sensitive_field_count"] = redacted
    return summary


def platform_audit_status(result: dict[str, Any]) -> str:
    status = clean(result.get("status"))
    if status == "platform_rejected":
        return "rejected"
    if result.get("ok") is False or result.get("errors"):
        return "error"
    if result.get("ok") is True:
        return "ok"
    if result.get("dropped"):
        return "dropped"
    prewarm = result.get("platform_prewarm") if isinstance(result.get("platform_prewarm"), dict) else None
    if prewarm and prewarm.get("dropped"):
        return "dropped"
    return "ok"


def platform_exception_result(exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "platform_error",
        "errors": [str(exc) or exc.__class__.__name__],
    }


def platform_advisory_prewarm_error(message: PlatformMessage, binding: GameSessionBinding) -> PlatformPrewarmResult:
    return PlatformPrewarmResult(
        allow_platform=True,
        enqueued=False,
        dropped=True,
        reason="platform_prewarm_error",
        message_id=public_platform_message_id(message.message_id),
        active_save=binding.active_save,
        queue_depth=0,
        decision={
            "allow": True,
            "reason": "platform_prewarm_error",
            "kind": "act_advisory_prewarm",
        },
    )


PLATFORM_AUDIT_SUMMARIZED_KEYS = {
    "delta",
    "delta_draft",
    "turn_proposal",
    "proposal",
    "validation_report",
    "projection_report",
    "state_audit",
    "check_errors",
    "external_intent_candidate",
    "internal_intent_candidate",
}
PLATFORM_AUDIT_REDACTED_KEYS = {
    "private_reasoning",
    "private_reasonings",
    "hidden_fact",
    "hidden_facts",
    "gm_note",
    "gm_notes",
    "secret",
    "secrets",
}


def sanitize_platform_audit_value(
    value: Any,
    *,
    max_text: int = 600,
    depth: int = 0,
    sensitive_terms: tuple[str, ...] = (),
) -> Any:
    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return sanitize_platform_audit_text(value, max_text=max_text, sensitive_terms=sensitive_terms)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        redacted = 0
        for key, item in value.items():
            normalized_key = str(key)
            audit_key = normalize_platform_audit_key(normalized_key)
            if audit_key in {
                "session_key",
                "session_id",
                "expected_pending_id",
                "clarification_id",
                "pending_id",
                "pending_clarification_id",
            }:
                sanitized[normalized_key] = bounded_platform_audit_hash(item)
            elif audit_key in {"actor_id", "user_id", "sender_id", "from_user_id"}:
                sanitized[f"{normalized_key}_hash"] = bounded_platform_audit_hash(item)
            elif audit_key in PLATFORM_AUDIT_SUMMARIZED_KEYS or audit_key in PLATFORM_AUDIT_REDACTED_KEYS:
                redacted += 1
            else:
                sanitized[normalized_key] = sanitize_platform_audit_value(
                    item,
                    max_text=max_text,
                    depth=depth + 1,
                    sensitive_terms=sensitive_terms,
                )
        if redacted:
            sanitized["redacted_sensitive_field_count"] = redacted
        return sanitized
    if isinstance(value, (list, tuple)):
        items = [
            sanitize_platform_audit_value(
                item,
                max_text=max_text,
                depth=depth + 1,
                sensitive_terms=sensitive_terms,
            )
            for item in value[:30]
        ]
        if len(value) > 30:
            items.append(f"<truncated {len(value) - 30} items>")
        return items
    return sanitize_platform_audit_text(str(value), max_text=max_text, sensitive_terms=sensitive_terms)


def sanitize_platform_audit_text(value: str, *, max_text: int, sensitive_terms: tuple[str, ...] = ()) -> str:
    text = str(value or "")
    if audit_text_has_sensitive_marker(text):
        return "<redacted sensitive audit text>"
    for term in sorted((term for term in sensitive_terms if term), key=len, reverse=True):
        text = text.replace(term, "<redacted>")
    text = re.sub(
        r"(?:player_action|clarification):[0-9a-f]{32}",
        lambda match: f"sha256:{hash_identity(match.group(0))}",
        text,
    )
    if len(text) <= max_text:
        return text
    return text[:max_text] + f"... <truncated {len(text) - max_text} chars>"


def audit_text_has_sensitive_marker(text: str) -> bool:
    normalized = normalize_platform_audit_key(text)
    return any(marker in normalized for marker in PLATFORM_AUDIT_REDACTED_KEYS)


def platform_audit_sensitive_terms(message: PlatformMessage | None) -> tuple[str, ...]:
    if message is None:
        return ()
    terms = {
        clean(message.session_key),
        clean(message.actor_id),
    }
    return tuple(term for term in terms if term)


def count_redacted_platform_payloads(value: Any, *, depth: int = 0) -> int:
    if depth > 6:
        return 0
    if isinstance(value, dict):
        total = 0
        for key, item in value.items():
            audit_key = normalize_platform_audit_key(str(key))
            if audit_key in PLATFORM_AUDIT_SUMMARIZED_KEYS or audit_key in PLATFORM_AUDIT_REDACTED_KEYS:
                total += 1
            else:
                total += count_redacted_platform_payloads(item, depth=depth + 1)
        return total
    if isinstance(value, (list, tuple)):
        return sum(count_redacted_platform_payloads(item, depth=depth + 1) for item in value[:30])
    return 0


def normalize_platform_audit_key(value: str) -> str:
    with_word_boundaries = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value.strip())
    return re.sub(r"[^0-9A-Za-z]+", "_", with_word_boundaries).strip("_").lower()


def platform_start_reservation_key(message: PlatformMessage) -> tuple[str, str, str]:
    if not all(
        identity_input_is_bounded_utf8(value)
        for value in (message.platform, message.session_key, message.actor_id)
    ) or not platform_message_id_is_valid(message.message_id):
        return "", "", ""
    return (
        clean(message.platform),
        hash_identity(message.session_key) if clean(message.session_key) else "",
        clean(message.message_id),
    )


def platform_start_gate(message: PlatformMessage) -> PlatformEntryGateResult:
    if not all(
        identity_input_is_bounded_utf8(value)
        for value in (message.platform, message.session_key, message.actor_id)
    ):
        return PlatformEntryGateResult(
            allow=False,
            reason="invalid_identity",
            kind="start",
        )
    if isinstance(message.message_id, str) and not message.message_id.strip():
        return PlatformEntryGateResult(
            allow=False,
            reason="missing_message_id",
            kind="start",
        )
    if not platform_message_id_is_valid(message.message_id):
        return PlatformEntryGateResult(
            allow=False,
            reason="invalid_message_id",
            kind="start",
        )
    platform = clean(message.platform)
    session_key = clean(message.session_key)
    message_id = clean(message.message_id)
    session_hash = hash_identity(session_key) if session_key else ""

    def decision(allow: bool, reason: str) -> PlatformEntryGateResult:
        return PlatformEntryGateResult(
            allow=allow,
            reason=reason,
            kind="start",
            platform=platform,
            session_key_hash=session_hash,
            message_id=message_id,
        )

    if not platform:
        return decision(False, "missing_platform")
    if not session_key:
        return decision(False, "missing_session_key")
    if not message_id:
        return decision(False, "missing_message_id")
    if message.actor_is_bot or message.actor_is_self:
        return decision(False, "actor_not_allowed")
    if not clean(message.actor_id):
        return decision(False, "missing_actor_id")
    if clean(message.message_type) not in SUPPORTED_MESSAGE_TYPES:
        return decision(False, "unsupported_message_type")
    if clean(message.chat_type) not in SUPPORTED_CHAT_TYPES:
        return decision(False, "unsupported_chat")
    return decision(True, "allowed")


def platform_entry_gate(
    binding: GameSessionBinding | None,
    message: PlatformMessage,
    *,
    kind: str,
) -> PlatformEntryGateResult:
    if not all(
        identity_input_is_bounded_utf8(value)
        for value in (message.platform, message.session_key, message.actor_id)
    ):
        return PlatformEntryGateResult(
            allow=False,
            reason="invalid_identity",
            kind=kind,
        )
    if isinstance(message.message_id, str) and not message.message_id.strip():
        return PlatformEntryGateResult(
            allow=False,
            reason="missing_message_id",
            kind=kind,
        )
    if not platform_message_id_is_valid(message.message_id):
        return PlatformEntryGateResult(
            allow=False,
            reason="invalid_message_id",
            kind=kind,
        )
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
    if binding.user_id_hash:
        actor_hash = hash_identity(message.actor_id) if clean(message.actor_id) else ""
        if not actor_hash:
            return decision(False, "missing_actor_id")
        if actor_hash != binding.user_id_hash:
            return decision(False, "actor_mismatch")
    if message.actor_is_bot or message.actor_is_self:
        return decision(False, "actor_not_allowed")
    if not binding.active_save:
        return decision(False, "no_active_save")
    pending_cancel = kind == "cancel" and binding.state in {PENDING_APPROVAL, PENDING_CLARIFICATION}
    if is_expired(binding.active_until) and not pending_cancel:
        return decision(False, "expired")
    if clean(message.message_type) not in SUPPORTED_MESSAGE_TYPES:
        return decision(False, "unsupported_message_type")
    if clean(message.chat_type) not in SUPPORTED_CHAT_TYPES:
        return decision(False, "unsupported_chat")

    if kind == "cancel":
        if binding.state not in {ACTIVE_GAME, PENDING_APPROVAL, PENDING_CLARIFICATION}:
            return decision(False, binding.state or INACTIVE)
        return decision(True, "allowed")

    if kind == "confirm":
        if binding.state not in {ACTIVE_GAME, PENDING_APPROVAL}:
            return decision(False, binding.state or INACTIVE)
        if message_id == binding.last_confirm_message_id:
            return decision(False, "duplicate_confirm_message")
        return decision(True, "allowed")

    if message_id == binding.last_action_message_id:
        return decision(False, "duplicate_action_message")
    if binding.state not in {ACTIVE_GAME, PENDING_APPROVAL, PENDING_CLARIFICATION}:
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
        "active_save": "" if gate.reason in PRIVATE_GATE_REASONS else gate.active_save,
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
        "missing_actor_id": "平台消息缺少玩家身份，无法确认这是同一位玩家。\n",
        "invalid_message_id": "平台消息标识无效，当前消息不会推进游戏。\n",
        "actor_mismatch": "这个平台会话已绑定到另一位玩家，当前消息不会推进游戏。\n",
        "command": "这条消息被识别为平台命令，不会推进游戏。\n",
        "empty_text": "没有可处理的玩家文本。\n",
        "duplicate_start_message": "这条开始/继续消息已经处理过，已忽略重复请求。\n",
        "start_in_progress": "这个平台会话正在开始或继续游戏，请稍后再试。\n",
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
    platform = first_identity_value(event, "platform", "source_platform")
    if isinstance(platform, str) and not platform:
        platform = default_platform
    text = first_text(event, "text", "raw_text", "content", "message", "message_text")
    message_id = first_message_id_value(event, "message_id", "msg_id", "id")
    actor_id = first_identity_value(event, "actor_id", "user_id", "sender_id", "from_user_id")
    chat_type = normalize_chat_type(first_text(event, "chat_type", "conversation_type", "type"), event)
    session_key = first_identity_value(event, "session_key")
    if isinstance(session_key, str) and not session_key:
        session_key = derive_session_key(platform, chat_type, event, actor_id)
    message_type = normalize_message_type(first_text(event, "message_type", "content_type") or "text")
    return PlatformMessage(
        platform=platform,
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


def derive_session_key(platform: Any, chat_type: str, event: dict[str, Any], actor_id: Any) -> Any:
    conversation_id = first_identity_value(
        event,
        "conversation_id",
        "session_id",
        "chat_id",
        "channel_id",
    )
    group_id = first_identity_value(event, "group_id", "guild_id")
    for value in (platform, conversation_id, group_id, actor_id):
        if not identity_input_is_bounded_utf8(value):
            return value
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


def first_identity_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if not identity_input_is_bounded_utf8(value):
            return value
        normalized = value.strip()
        if normalized:
            return normalized
    return ""


def first_message_id_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in data or data[key] is None:
            continue
        value = data[key]
        if isinstance(value, int) and not isinstance(value, bool):
            if value.bit_length() > 128:
                return value
            try:
                value = str(value)
            except (ValueError, MemoryError):
                return value
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if normalized:
            return normalized
    return ""


def active_save_path_from_result(
    root: Path,
    result: dict[str, Any],
    *,
    fallback: str = "",
) -> str:
    save = result.get("save") if isinstance(result.get("save"), dict) else None
    if save and clean(save.get("path")):
        return clean(save.get("path"))
    if clean(fallback):
        return clean(fallback)
    manager = SaveManager(root)
    current = manager.current_save(refresh=False)
    save = current.get("save") if isinstance(current.get("save"), dict) else None
    return clean(save.get("path")) if save else ""


def binding_to_public_dict(
    binding: GameSessionBinding | None,
    *,
    redact_private: bool = False,
) -> dict[str, Any] | None:
    if binding is None:
        return None
    if redact_private:
        return {"state": binding.state}
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


def confirmation_binding_context_changed(
    expected: GameSessionBinding,
    current: GameSessionBinding,
) -> bool:
    return any(
        (
            current.revision != expected.revision,
            current.active_save != expected.active_save,
            current.state != expected.state,
            current.last_action_message_id != expected.last_action_message_id,
            current.pending_confirmation_session_hash != expected.pending_confirmation_session_hash,
            current.pending_confirmation_revision != expected.pending_confirmation_revision,
            current.clarification_id != expected.clarification_id,
        )
    )


def completion_binding_context_changed(
    expected: GameSessionBinding,
    current: GameSessionBinding,
) -> bool:
    return any(
        (
            current.revision != expected.revision,
            current.active_save != expected.active_save,
            current.state != expected.state,
            current.last_action_message_id != expected.last_action_message_id,
            current.clarification_id != expected.clarification_id,
        )
    )


def canonical_pending_inspect_classification(inspected: Any) -> str:
    if not isinstance(inspected, dict):
        return "invalid"
    if set(inspected) != {"ok", "status", "lifecycle", "errors"}:
        return "invalid"
    lifecycle = inspected.get("lifecycle")
    if (
        inspected.get("ok") is not True
        or inspected.get("errors") != []
        or not isinstance(lifecycle, dict)
    ):
        return "invalid"
    status = inspected.get("status")
    lifecycle_state = lifecycle.get("state")
    lifecycle_kind = lifecycle.get("kind")
    if type(status) is not str or status != lifecycle_state:
        return "invalid"
    if (status, lifecycle_kind) == ("not_found", "unknown"):
        return "terminal" if set(lifecycle) == {"state", "kind"} else "invalid"

    base_keys = {"state", "kind", "save_id", "created_at", "expires_at", "ttl_seconds"}
    clarification_keys = base_keys | {"clarification_origin"}
    if lifecycle_kind == "action":
        evidence_keys = base_keys
    elif lifecycle_kind == "clarification":
        evidence_keys = clarification_keys
    else:
        return "invalid"
    required_keys = set(evidence_keys)
    if status == "orphaned" and lifecycle_kind == "clarification":
        required_keys = {"state", "kind", "save_id", "created_at"}
    allowed_keys = set(evidence_keys)
    if status in {"active", "migrated"}:
        required_keys.add("pending_id")
        allowed_keys.add("pending_id")
    if not required_keys.issubset(lifecycle) or not set(lifecycle).issubset(allowed_keys):
        return "invalid"

    pending_id = lifecycle.get("pending_id")
    pending_id_is_canonical = (
        canonical_bounded_utf8_string(pending_id)
        and (
            lifecycle_kind == "clarification"
            or re.fullmatch(r"player_action:[0-9a-f]{32}", pending_id) is not None
        )
    )
    if status in {"active", "migrated"} and not pending_id_is_canonical:
        return "invalid"
    if status not in {"active", "migrated"} and "pending_id" in lifecycle:
        return "invalid"
    save_id = lifecycle.get("save_id")
    created_at = canonical_utc_datetime(lifecycle.get("created_at"))
    expires_at = canonical_utc_datetime(lifecycle.get("expires_at"))
    ttl_seconds = lifecycle.get("ttl_seconds")
    if (
        not canonical_bounded_utf8_string(save_id)
        or created_at is None
    ):
        return "invalid"
    if "expires_at" in lifecycle and (
        expires_at is None
        or expires_at - created_at
        != timedelta(seconds=DEFAULT_PENDING_ACTION_TTL_SECONDS)
    ):
        return "invalid"
    if "ttl_seconds" in lifecycle and (
        type(ttl_seconds) is not int
        or ttl_seconds != DEFAULT_PENDING_ACTION_TTL_SECONDS
    ):
        return "invalid"
    if lifecycle_kind == "clarification" and "clarification_origin" in lifecycle:
        if lifecycle.get("clarification_origin") not in {
            "player_input_ambiguity",
            "candidate_contract_mismatch",
        }:
            return "invalid"
    if (
        (status, lifecycle_kind) in {
            ("active", "action"),
            ("active", "clarification"),
            ("migrated", "clarification"),
        }
        and pending_id_is_canonical
    ):
        return "active"
    terminal_shape = (status, lifecycle_kind) in {
        ("not_found", "unknown"),
        ("expired", "action"),
        ("expired", "clarification"),
        ("orphaned", "action"),
        ("orphaned", "clarification"),
    }
    if terminal_shape:
        return "terminal"
    return "invalid"


def canonical_utc_datetime(value: Any) -> datetime | None:
    if not canonical_bounded_utf8_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() != timedelta(0)
        or parsed.isoformat() != value
    ):
        return None
    return parsed


def canonical_bounded_utf8_string(value: Any) -> bool:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > MAX_PENDING_STRING_LENGTH
    ):
        return False
    try:
        value.encode("utf-8")
    except UnicodeError:
        return False
    return True


def start_reservation_context_changed(
    expected: GameSessionBinding,
    current: GameSessionBinding,
) -> bool:
    return any(
        (
            current.revision != expected.revision,
            current.active_save != expected.active_save,
            current.state != expected.state,
            current.last_action_message_id != expected.last_action_message_id,
            current.pending_confirmation_session_hash != expected.pending_confirmation_session_hash,
            current.pending_confirmation_revision != expected.pending_confirmation_revision,
            current.clarification_id != expected.clarification_id,
        )
    )


def replay_confirmation_binding_needs_reconcile(
    root: Path,
    binding: GameSessionBinding | None,
    result: dict[str, Any],
    *,
    confirmation_session_hash: str,
    expected_revision: int,
) -> bool:
    if (
        binding is None
        or not confirmation_session_hash
        or result.get("ok") is not True
        or result.get("write_status") != "already_confirmed"
        or result.get("idempotent_replay") is not True
        or binding.revision != expected_revision
        or binding.state != PENDING_APPROVAL
        or clean(result.get("confirmation_session_hash")) != confirmation_session_hash
    ):
        return False
    if not confirmation_binding_generation_matches(binding, confirmation_session_hash):
        return False
    result_save_path = active_save_path_from_result(root, result)
    return bool(result_save_path and result_save_path == binding.active_save)


def confirmation_binding_matches_session(
    binding: GameSessionBinding,
    result: dict[str, Any],
    *,
    confirmation_session_hash: str,
) -> bool:
    if (
        not confirmation_session_hash
        or clean(result.get("confirmation_session_hash")) != confirmation_session_hash
        or binding.state != PENDING_APPROVAL
    ):
        return False
    return confirmation_binding_generation_matches(binding, confirmation_session_hash)


def confirmation_binding_generation_matches(
    binding: GameSessionBinding,
    confirmation_session_hash: str,
) -> bool:
    current_generation = (
        binding.pending_confirmation_session_hash == confirmation_session_hash
        and binding.pending_confirmation_revision == binding.revision
    )
    legacy_generation = (
        not binding.pending_confirmation_session_hash
        and binding.pending_confirmation_revision == 0
        and binding.revision == 0
    )
    return current_generation or legacy_generation


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
