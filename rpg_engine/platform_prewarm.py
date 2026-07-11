from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .ai.defaults import (
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_BACKGROUND_TARGET_MAX_SECONDS,
)
from .atomic_io import write_text_atomic
from .db import utc_now
from .game_session import (
    ACTIVE_GAME,
    GameSessionBinding,
    GameSessionGateDecision,
    PlatformMessage,
    clean,
    hash_identity,
    should_prewarm_message,
)
from .preflight_cache import PREFLIGHT_IDENTITY_MESSAGE_ONLY
from .runtime import GMRuntime


PLATFORM_PREWARM_ENV = "AIGM_PLATFORM_PREWARM"
PLATFORM_PREWARM_SCHEMA_VERSION = "1"
DEFAULT_BINDINGS_RELATIVE = ".aigm/game-session-bindings.json"
DEFAULT_PREWARM_QUEUE_SIZE = 16
DEFAULT_PREWARM_WORKERS = 1
DEFAULT_PREWARM_TTL_SECONDS = 300

DROP_FEATURE_DISABLED = "feature_disabled"
DROP_MISSING_PLATFORM = "missing_platform"
DROP_MISSING_SESSION_KEY = "missing_session_key"
DROP_MISSING_MESSAGE_ID = "missing_message_id"
DROP_DUPLICATE_MESSAGE = "duplicate_message"
DROP_QUEUE_FULL = "queue_full"
DROP_AI_TIMEOUT = "ai_timeout"
DROP_AI_FAILED = "ai_failed"
DROP_WORKER_ERROR = "worker_error"
DROP_REASONS = {
    DROP_FEATURE_DISABLED,
    DROP_MISSING_PLATFORM,
    DROP_MISSING_SESSION_KEY,
    DROP_MISSING_MESSAGE_ID,
    "inactive",
    "platform_mismatch",
    "session_mismatch",
    "expired",
    "no_active_save",
    DROP_DUPLICATE_MESSAGE,
    "actor_not_allowed",
    "unsupported_message_type",
    "unsupported_chat",
    "empty_text",
    "command",
    "pending_approval",
    "pending_clarification",
    "cooldown",
    DROP_QUEUE_FULL,
    DROP_AI_TIMEOUT,
    DROP_AI_FAILED,
    DROP_WORKER_ERROR,
}


@dataclass(frozen=True)
class PlatformPrewarmConfig:
    enabled: bool = False
    max_queue_size: int = DEFAULT_PREWARM_QUEUE_SIZE
    worker_count: int = DEFAULT_PREWARM_WORKERS
    intent_backend: str = "direct"
    intent_provider: str = DEFAULT_AI_PROVIDER
    intent_model: str = DEFAULT_AI_MODEL
    intent_timeout: int = DEFAULT_BACKGROUND_TARGET_MAX_SECONDS
    intent_base_url: str = ""
    intent_api_key_env: str = ""
    intent_fallback_backend: str = "off"
    ttl_seconds: int = DEFAULT_PREWARM_TTL_SECONDS

    @classmethod
    def from_env(cls) -> "PlatformPrewarmConfig":
        return cls(
            enabled=env_flag(PLATFORM_PREWARM_ENV, default=False),
            max_queue_size=env_int("AIGM_PLATFORM_PREWARM_QUEUE_SIZE", DEFAULT_PREWARM_QUEUE_SIZE, minimum=1),
            worker_count=env_int("AIGM_PLATFORM_PREWARM_WORKERS", DEFAULT_PREWARM_WORKERS, minimum=1),
            intent_backend=os.environ.get("AIGM_PLATFORM_PREWARM_INTENT_BACKEND", "direct").strip() or "direct",
            intent_provider=os.environ.get("AIGM_PLATFORM_PREWARM_INTENT_PROVIDER", DEFAULT_AI_PROVIDER).strip()
            or DEFAULT_AI_PROVIDER,
            intent_model=os.environ.get("AIGM_PLATFORM_PREWARM_INTENT_MODEL", DEFAULT_AI_MODEL).strip()
            or DEFAULT_AI_MODEL,
            intent_timeout=env_int(
                "AIGM_PLATFORM_PREWARM_INTENT_TIMEOUT",
                DEFAULT_BACKGROUND_TARGET_MAX_SECONDS,
                minimum=3,
                maximum=120,
            ),
            intent_base_url=os.environ.get("AIGM_PLATFORM_PREWARM_INTENT_BASE_URL", "").strip(),
            intent_api_key_env=os.environ.get("AIGM_PLATFORM_PREWARM_INTENT_API_KEY_ENV", "").strip(),
            intent_fallback_backend=os.environ.get("AIGM_PLATFORM_PREWARM_INTENT_FALLBACK_BACKEND", "off").strip()
            or "off",
            ttl_seconds=env_int("AIGM_PLATFORM_PREWARM_TTL_SECONDS", DEFAULT_PREWARM_TTL_SECONDS, minimum=1),
        )


@dataclass(frozen=True)
class PlatformPrewarmRequest:
    root: Path
    active_save: str
    message: PlatformMessage
    source_user_text_hash: str
    enqueued_at: str = field(default_factory=utc_now)

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        return (
            clean(self.message.platform),
            hash_identity(self.message.session_key),
            clean(self.message.message_id),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "active_save": self.active_save,
            "platform": clean(self.message.platform),
            "session_key_hash": hash_identity(self.message.session_key),
            "message_id": clean(self.message.message_id),
            "source_user_text_hash": self.source_user_text_hash,
            "enqueued_at": self.enqueued_at,
        }


@dataclass(frozen=True)
class PlatformPrewarmResult:
    allow_platform: bool = True
    enqueued: bool = False
    dropped: bool = False
    reason: str = ""
    message_id: str = ""
    active_save: str = ""
    queue_depth: int = 0
    decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_platform": self.allow_platform,
            "enqueued": self.enqueued,
            "dropped": self.dropped,
            "reason": self.reason,
            "message_id": self.message_id,
            "active_save": self.active_save,
            "queue_depth": self.queue_depth,
            "decision": self.decision,
        }


@dataclass(frozen=True)
class PlatformPrewarmWorkerResult:
    ok: bool
    status: str
    reason: str
    message_id: str
    preflight_id: str = ""
    duration_ms: int = 0
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "reason": self.reason,
            "message_id": self.message_id,
            "preflight_id": self.preflight_id,
            "duration_ms": self.duration_ms,
            "errors": list(self.errors),
        }


class GameSessionBindingStore:
    def __init__(self, root: str | Path, path: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = resolve_store_path(self.root, path)

    def read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_binding_state()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("game session binding store must be a JSON object")
        if str(data.get("schema_version", "")) != PLATFORM_PREWARM_SCHEMA_VERSION:
            raise ValueError(
                f"game session binding store schema_version must be {PLATFORM_PREWARM_SCHEMA_VERSION}, "
                f"got {data.get('schema_version')}"
            )
        bindings = data.setdefault("bindings", [])
        if not isinstance(bindings, list):
            raise ValueError("game session binding store bindings must be an array")
        return data

    def write_state(self, state: dict[str, Any]) -> None:
        normalized = {
            "schema_version": PLATFORM_PREWARM_SCHEMA_VERSION,
            "bindings": [normalize_binding_record(item) for item in state.get("bindings", []) if isinstance(item, dict)],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.path, json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def list_bindings(self) -> list[GameSessionBinding]:
        return [binding_from_record(item) for item in self.read_state().get("bindings", []) if isinstance(item, dict)]

    def get(self, *, platform: str, session_key: str) -> GameSessionBinding | None:
        platform_value = clean(platform)
        session_hash = hash_identity(session_key)
        for binding in self.list_bindings():
            if binding.platform == platform_value and binding.session_key_hash == session_hash:
                return binding
        return None

    def upsert_raw(
        self,
        *,
        platform: str,
        session_key: str,
        active_save: str,
        state: str = ACTIVE_GAME,
        active_until: str,
        user_id: str = "",
        last_message_id: str = "",
        last_action_message_id: str = "",
        last_confirm_message_id: str = "",
        clarification_id: str = "",
    ) -> GameSessionBinding:
        existing = self.get(platform=platform, session_key=session_key)
        binding = GameSessionBinding.from_raw(
            platform=platform,
            session_key=session_key,
            active_save=active_save,
            state=state,
            active_until=active_until,
            user_id=user_id,
            last_message_id=last_message_id or (existing.last_message_id if existing else ""),
            last_action_message_id=last_action_message_id or (existing.last_action_message_id if existing else ""),
            last_confirm_message_id=last_confirm_message_id or (existing.last_confirm_message_id if existing else ""),
            clarification_id=clarification_id,
            updated_at=utc_now(),
        )
        self.upsert(binding)
        return binding

    def upsert(self, binding: GameSessionBinding) -> None:
        state = self.read_state()
        record = binding_to_record(binding)
        bindings = [
            item
            for item in state.get("bindings", [])
            if not (
                isinstance(item, dict)
                and clean(item.get("platform")) == record["platform"]
                and clean(item.get("session_key_hash")) == record["session_key_hash"]
            )
        ]
        bindings.append(record)
        state["bindings"] = sorted(bindings, key=lambda item: (str(item.get("platform", "")), str(item.get("session_key_hash", ""))))
        self.write_state(state)

    def record_last_message(self, *, platform: str, session_key: str, message_id: str) -> None:
        binding = self.get(platform=platform, session_key=session_key)
        if binding is None:
            return
        self.upsert(
            GameSessionBinding(
                platform=binding.platform,
                session_key_hash=binding.session_key_hash,
                active_save=binding.active_save,
                state=binding.state,
                active_until=binding.active_until,
                user_id_hash=binding.user_id_hash,
                last_message_id=clean(message_id),
                last_action_message_id=binding.last_action_message_id,
                last_confirm_message_id=binding.last_confirm_message_id,
                clarification_id=binding.clarification_id,
                updated_at=utc_now(),
            )
        )

    def delete(self, *, platform: str, session_key: str) -> bool:
        state = self.read_state()
        platform_value = clean(platform)
        session_hash = hash_identity(session_key)
        before = len(state.get("bindings", []))
        state["bindings"] = [
            item
            for item in state.get("bindings", [])
            if not (
                isinstance(item, dict)
                and clean(item.get("platform")) == platform_value
                and clean(item.get("session_key_hash")) == session_hash
            )
        ]
        changed = len(state["bindings"]) != before
        if changed:
            self.write_state(state)
        return changed


class PrewarmMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.enqueue_count = 0
        self.drop_count = 0
        self.finish_count = 0
        self.drop_reasons: dict[str, int] = {}
        self.finish_statuses: dict[str, int] = {}
        self.worker_durations_ms: list[int] = []
        self.max_queue_depth = 0

    def record_enqueue(self, *, queue_depth: int) -> None:
        with self._lock:
            self.enqueue_count += 1
            self.max_queue_depth = max(self.max_queue_depth, queue_depth)

    def record_drop(self, reason: str) -> None:
        with self._lock:
            self.drop_count += 1
            self.drop_reasons[reason] = self.drop_reasons.get(reason, 0) + 1

    def record_finish(self, status: str, *, duration_ms: int) -> None:
        with self._lock:
            self.finish_count += 1
            self.finish_statuses[status] = self.finish_statuses.get(status, 0) + 1
            self.worker_durations_ms.append(max(0, int(duration_ms)))

    def snapshot(self, *, queue_depth: int = 0) -> dict[str, Any]:
        with self._lock:
            durations = list(self.worker_durations_ms)
            average = int(sum(durations) / len(durations)) if durations else 0
            p95 = percentile(durations, 0.95) if durations else 0
            return {
                "prewarm_enqueue_count": self.enqueue_count,
                "prewarm_drop_count": self.drop_count,
                "prewarm_drop_reasons": dict(sorted(self.drop_reasons.items())),
                "prewarm_finish_count": self.finish_count,
                "prewarm_finish_statuses": dict(sorted(self.finish_statuses.items())),
                "prewarm_worker_average_ms": average,
                "prewarm_worker_p95_ms": p95,
                "queue_depth": queue_depth,
                "queue_depth_max": self.max_queue_depth,
            }


class PrewarmQueue:
    def __init__(self, *, maxsize: int = DEFAULT_PREWARM_QUEUE_SIZE, metrics: PrewarmMetrics | None = None) -> None:
        self._queue: queue.Queue[PlatformPrewarmRequest] = queue.Queue(maxsize=max(1, int(maxsize)))
        self._metrics = metrics or PrewarmMetrics()
        self._queued_keys: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()

    @property
    def metrics(self) -> PrewarmMetrics:
        return self._metrics

    def qsize(self) -> int:
        return self._queue.qsize()

    def enqueue(self, request: PlatformPrewarmRequest) -> PlatformPrewarmResult:
        missing = missing_request_identity_reason(request)
        if missing:
            self._metrics.record_drop(missing)
            return dropped_result(missing, request=request, queue_depth=self.qsize())
        key = request.dedupe_key
        with self._lock:
            if key in self._queued_keys:
                self._metrics.record_drop(DROP_DUPLICATE_MESSAGE)
                return dropped_result(DROP_DUPLICATE_MESSAGE, request=request, queue_depth=self.qsize())
            if self._queue.full():
                self._metrics.record_drop(DROP_QUEUE_FULL)
                return dropped_result(DROP_QUEUE_FULL, request=request, queue_depth=self.qsize())
            self._queued_keys.add(key)
            try:
                self._queue.put_nowait(request)
            except queue.Full:
                self._queued_keys.discard(key)
                self._metrics.record_drop(DROP_QUEUE_FULL)
                return dropped_result(DROP_QUEUE_FULL, request=request, queue_depth=self.qsize())
            depth = self.qsize()
            self._metrics.record_enqueue(queue_depth=depth)
            return PlatformPrewarmResult(
                allow_platform=True,
                enqueued=True,
                dropped=False,
                reason="enqueued",
                message_id=clean(request.message.message_id),
                active_save=request.active_save,
                queue_depth=depth,
            )

    def run_next(
        self,
        worker: "PrewarmWorker",
        *,
        block: bool = False,
        timeout: float | None = None,
    ) -> PlatformPrewarmWorkerResult | None:
        try:
            request = self._queue.get(block=block, timeout=timeout if timeout is not None else 0)
        except queue.Empty:
            return None
        try:
            return worker.process(request)
        finally:
            with self._lock:
                self._queued_keys.discard(request.dedupe_key)
            self._queue.task_done()

    def drain(self, worker: "PrewarmWorker", *, limit: int | None = None) -> list[PlatformPrewarmWorkerResult]:
        results: list[PlatformPrewarmWorkerResult] = []
        while limit is None or len(results) < limit:
            result = self.run_next(worker, block=False)
            if result is None:
                break
            results.append(result)
        return results


class PrewarmWorker:
    def __init__(
        self,
        *,
        config: PlatformPrewarmConfig | None = None,
        metrics: PrewarmMetrics | None = None,
        runtime_factory: Callable[[Path], Any] = GMRuntime.from_path,
    ) -> None:
        self.config = config or PlatformPrewarmConfig()
        self.metrics = metrics or PrewarmMetrics()
        self.runtime_factory = runtime_factory

    def process(self, request: PlatformPrewarmRequest) -> PlatformPrewarmWorkerResult:
        started = time.monotonic()
        try:
            runtime = self.runtime_factory(resolve_active_save_path(request.root, request.active_save))
            result = runtime.preflight_intent(
                request.message.text,
                intent_backend=self.config.intent_backend,
                intent_provider=self.config.intent_provider,
                intent_model=self.config.intent_model,
                intent_timeout=self.config.intent_timeout,
                intent_base_url=self.config.intent_base_url,
                intent_api_key_env=self.config.intent_api_key_env,
                intent_fallback_backend=self.config.intent_fallback_backend,
                external_intent_candidate=None,
                message_id=request.message.message_id,
                platform=request.message.platform,
                session_key=request.message.session_key,
                source_user_text_hash=request.source_user_text_hash,
                preflight_identity_profile=PREFLIGHT_IDENTITY_MESSAGE_ONLY,
                ttl_seconds=self.config.ttl_seconds,
            )
            data = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            duration_ms = elapsed_ms(started)
            source_ok = data.get("ok") is True
            source_status = data.get("status")
            status = (
                source_status
                if isinstance(source_status, str) and source_status in {"ready", "failed", "expired", "rejected"}
                else "failed"
            )
            if not source_ok and status == "ready":
                status = "failed"
            preflight_id = public_preflight_id(data.get("preflight_id"))
            ok = source_ok and status == "ready" and bool(preflight_id)
            if not ok and status == "ready":
                status = "failed"
            errors = tuple(str(item) for item in data.get("errors", []) if str(item).strip())
            internal_helper = data.get("internal_helper")
            helper_failure_reason = (
                str(internal_helper.get("failure_reason") or "") if isinstance(internal_helper, dict) else ""
            )
            helper_hard_timeout = (
                internal_helper.get("hard_timeout") is True if isinstance(internal_helper, dict) else False
            )
            helper_late_discarded = (
                internal_helper.get("late_discarded") is True if isinstance(internal_helper, dict) else False
            )
            helper_timeout = helper_failure_reason == "timeout" or helper_hard_timeout or helper_late_discarded
            if ok and helper_timeout:
                ok = False
                status = "failed"
            reason = (
                status
                if ok
                else (
                    DROP_AI_TIMEOUT
                    if is_timeout_error(
                        errors,
                        status,
                        failure_reason=helper_failure_reason,
                        hard_timeout=helper_hard_timeout,
                        late_discarded=helper_late_discarded,
                    )
                    else DROP_AI_FAILED
                )
            )
            self.metrics.record_finish(reason if not ok else status, duration_ms=duration_ms)
            return PlatformPrewarmWorkerResult(
                ok=ok,
                status=status,
                reason=reason,
                message_id=clean(request.message.message_id),
                preflight_id=preflight_id if ok else "",
                duration_ms=duration_ms,
                errors=public_prewarm_errors(reason) if not ok else (),
            )
        except TimeoutError:
            duration_ms = elapsed_ms(started)
            self.metrics.record_finish(DROP_AI_TIMEOUT, duration_ms=duration_ms)
            return PlatformPrewarmWorkerResult(
                ok=False,
                status="failed",
                reason=DROP_AI_TIMEOUT,
                message_id=clean(request.message.message_id),
                duration_ms=duration_ms,
                errors=public_prewarm_errors(DROP_AI_TIMEOUT),
            )
        except Exception:  # pragma: no cover - worker must never break the host adapter
            duration_ms = elapsed_ms(started)
            self.metrics.record_finish(DROP_WORKER_ERROR, duration_ms=duration_ms)
            return PlatformPrewarmWorkerResult(
                ok=False,
                status="failed",
                reason=DROP_WORKER_ERROR,
                message_id=clean(request.message.message_id),
                duration_ms=duration_ms,
                errors=public_prewarm_errors(DROP_WORKER_ERROR),
            )


class PrewarmDispatcher:
    def __init__(self, *, queue_: PrewarmQueue, worker: PrewarmWorker, worker_count: int = DEFAULT_PREWARM_WORKERS) -> None:
        self.queue = queue_
        self.worker = worker
        self.worker_count = max(1, int(worker_count))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for index in range(self.worker_count):
            thread = threading.Thread(target=self._loop, name=f"aigm-prewarm-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, *, timeout: float = 2.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads = [thread for thread in self._threads if thread.is_alive()]

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.queue.run_next(self.worker, block=True, timeout=0.1)


class PlatformPrewarmService:
    def __init__(
        self,
        root: str | Path,
        *,
        config: PlatformPrewarmConfig | None = None,
        binding_store: GameSessionBindingStore | None = None,
        prewarm_queue: PrewarmQueue | None = None,
        metrics: PrewarmMetrics | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.config = config or PlatformPrewarmConfig.from_env()
        self.metrics = metrics or PrewarmMetrics()
        self.binding_store = binding_store or GameSessionBindingStore(self.root)
        self.queue = prewarm_queue or PrewarmQueue(maxsize=self.config.max_queue_size, metrics=self.metrics)

    def handle_message(self, message: PlatformMessage) -> PlatformPrewarmResult:
        if not self.config.enabled:
            self.metrics.record_drop(DROP_FEATURE_DISABLED)
            return PlatformPrewarmResult(
                allow_platform=True,
                dropped=True,
                reason=DROP_FEATURE_DISABLED,
                message_id=clean(message.message_id),
                queue_depth=self.queue.qsize(),
            )
        missing = missing_message_identity_reason(message)
        if missing:
            self.metrics.record_drop(missing)
            return PlatformPrewarmResult(
                allow_platform=True,
                dropped=True,
                reason=missing,
                message_id=clean(message.message_id),
                queue_depth=self.queue.qsize(),
            )
        binding = self.binding_store.get(platform=message.platform, session_key=message.session_key)
        decision = should_prewarm_message(binding, message)
        if not decision.allow:
            self.metrics.record_drop(decision.reason)
            return PlatformPrewarmResult(
                allow_platform=True,
                dropped=True,
                reason=decision.reason,
                message_id=clean(message.message_id),
                active_save=decision.active_save,
                queue_depth=self.queue.qsize(),
                decision=decision.to_dict(),
            )
        request = request_from_decision(self.root, message, decision)
        result = self.queue.enqueue(request)
        if result.enqueued:
            self.binding_store.record_last_message(
                platform=message.platform,
                session_key=message.session_key,
                message_id=message.message_id,
            )
        return result


def request_from_decision(root: Path, message: PlatformMessage, decision: GameSessionGateDecision) -> PlatformPrewarmRequest:
    return PlatformPrewarmRequest(
        root=root,
        active_save=decision.active_save,
        message=message,
        source_user_text_hash=decision.source_user_text_hash,
    )


def binding_to_record(binding: GameSessionBinding) -> dict[str, Any]:
    return normalize_binding_record(
        {
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
            "updated_at": binding.updated_at or utc_now(),
        }
    )


def binding_from_record(record: dict[str, Any]) -> GameSessionBinding:
    normalized = normalize_binding_record(record)
    return GameSessionBinding(
        platform=normalized["platform"],
        session_key_hash=normalized["session_key_hash"],
        user_id_hash=normalized["user_id_hash"],
        active_save=normalized["active_save"],
        state=normalized["state"],
        active_until=normalized["active_until"],
        last_message_id=normalized["last_message_id"],
        last_action_message_id=normalized["last_action_message_id"],
        last_confirm_message_id=normalized["last_confirm_message_id"],
        clarification_id=normalized["clarification_id"],
        updated_at=normalized["updated_at"],
    )


def normalize_binding_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": clean(record.get("platform")),
        "session_key_hash": clean(record.get("session_key_hash")),
        "user_id_hash": clean(record.get("user_id_hash")),
        "active_save": clean(record.get("active_save")),
        "state": clean(record.get("state")) or "inactive",
        "active_until": clean(record.get("active_until")),
        "last_message_id": clean(record.get("last_message_id")),
        "last_action_message_id": clean(record.get("last_action_message_id")),
        "last_confirm_message_id": clean(record.get("last_confirm_message_id")),
        "clarification_id": clean(record.get("clarification_id")),
        "updated_at": clean(record.get("updated_at")),
    }


def empty_binding_state() -> dict[str, Any]:
    return {"schema_version": PLATFORM_PREWARM_SCHEMA_VERSION, "bindings": []}


def resolve_store_path(root: Path, path: str | Path | None) -> Path:
    if path is None:
        candidate = root / DEFAULT_BINDINGS_RELATIVE
    else:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
    candidate = candidate.resolve()
    ensure_under_root(root, candidate, "game session binding store")
    return candidate


def resolve_active_save_path(root: Path, active_save: str) -> Path:
    relative = Path(clean(active_save))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("active_save must be relative to workspace root")
    candidate = (root / relative).resolve()
    ensure_under_root(root, candidate, "active_save")
    return candidate


def ensure_under_root(root: Path, candidate: Path, label: str) -> None:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    if candidate_resolved != root_resolved and root_resolved not in candidate_resolved.parents:
        raise ValueError(f"{label} escapes workspace root")


def missing_message_identity_reason(message: PlatformMessage) -> str:
    if not clean(message.platform):
        return DROP_MISSING_PLATFORM
    if not clean(message.session_key):
        return DROP_MISSING_SESSION_KEY
    if not clean(message.message_id):
        return DROP_MISSING_MESSAGE_ID
    return ""


def missing_request_identity_reason(request: PlatformPrewarmRequest) -> str:
    return missing_message_identity_reason(request.message)


def dropped_result(reason: str, *, request: PlatformPrewarmRequest, queue_depth: int) -> PlatformPrewarmResult:
    return PlatformPrewarmResult(
        allow_platform=True,
        enqueued=False,
        dropped=True,
        reason=reason,
        message_id=clean(request.message.message_id),
        active_save=request.active_save,
        queue_depth=queue_depth,
    )


def elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def is_timeout_error(
    errors: tuple[str, ...],
    status: str,
    *,
    failure_reason: str = "",
    hard_timeout: bool = False,
    late_discarded: bool = False,
) -> bool:
    if failure_reason.strip().lower() == "timeout" or hard_timeout or late_discarded:
        return True
    text = " ".join((*errors, status)).lower()
    return "timeout" in text or "timed out" in text


def public_prewarm_errors(reason: str) -> tuple[str, ...]:
    if reason == DROP_AI_TIMEOUT:
        return ("AI prewarm timed out.",)
    if reason == DROP_WORKER_ERROR:
        return ("AI prewarm worker unavailable.",)
    return ("AI prewarm unavailable.",)


def public_preflight_id(value: Any) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"preflight:[0-9a-f]{32}", value) else ""


def env_flag(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return ordered[index]
