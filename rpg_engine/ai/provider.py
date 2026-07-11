from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
import time
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from .audit import helper_audit_record
from .policy import DEFAULT_AI_HELPER_POLICY, AIHelperPolicy, normalize_timeout
from .schema_validation import validate_ai_output_schema
from .tasks import AIHelperTask


@dataclass(frozen=True)
class AIHelperResult:
    task: str
    backend: str
    provider: str
    model: str
    status: str
    parsed: dict[str, Any] | None = None
    raw_text: str = ""
    error: str | None = None
    elapsed_ms: int = 0
    advisory: bool = True
    no_direct_writes: bool = True
    audit: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    soft_wait_exceeded: bool = False
    hard_timeout: bool = False
    late_discarded: bool = False
    timeout_seconds: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.parsed is not None


BACKEND_ALIASES = {
    "hermes": "hermes_z",
}
SUPPORTED_BACKENDS = {"off", "direct", "hermes_z"}
DEFAULT_DIRECT_TIMEOUT_ERROR = "direct ai timed out"
DEFAULT_DIRECT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}
DEFAULT_API_KEY_ENVS = {
    "deepseek": ("DEEPSEEK_API_KEY", "AIGM_DEEPSEEK_API_KEY", "AIGM_AI_API_KEY"),
    "openai": ("OPENAI_API_KEY", "AIGM_OPENAI_API_KEY", "AIGM_AI_API_KEY"),
}
AI_HELPER_WORKER_LIMIT = 8
MAX_PUBLIC_SAFE_INTEGER = (1 << 53) - 1
MAX_PUBLIC_AUDIT_DEPTH = 4
PUBLIC_AI_HELPER_TASKS = {
    "archivist",
    "internal_intent_review",
    "reflection",
    "semantic",
    "state_audit",
}
_AI_HELPER_WORKER_SLOTS = {
    "foreground": threading.BoundedSemaphore(AI_HELPER_WORKER_LIMIT),
    "background": threading.BoundedSemaphore(AI_HELPER_WORKER_LIMIT),
}


class InternalAIService:
    """Lightweight internal AI JSON task runner.

    The service is intentionally small: it only knows how to complete one JSON
    task, validate it, normalize it, and optionally fall back to the legacy
    hermes oneshot backend.
    """

    def complete_json(
        self,
        task: AIHelperTask,
        *,
        backend: str,
        provider: str,
        model: str,
        timeout: int,
        policy: AIHelperPolicy = DEFAULT_AI_HELPER_POLICY,
        base_url: str | None = None,
        api_key_env: str | None = None,
        fallback_backend: str | None = None,
    ) -> AIHelperResult:
        started = time.perf_counter()
        normalized_backend = normalize_backend_name(backend)
        provider = str(provider or "")
        model = str(model or "")
        if normalized_backend == "off":
            return build_result(task, normalized_backend, provider, model, "off", started, policy)
        if normalized_backend not in SUPPORTED_BACKENDS:
            return build_result(
                task,
                normalized_backend,
                provider,
                model,
                "error",
                started,
                policy,
                error=f"unsupported ai helper backend: {backend}",
            )
        if not provider.strip():
            return build_result(
                task, normalized_backend, provider, model, "error", started, policy, error="ai provider is required"
            )
        if not model.strip():
            return build_result(
                task, normalized_backend, provider, model, "error", started, policy, error="ai model is required"
            )

        try:
            effective_timeout = normalize_timeout(timeout, policy)
        except (TypeError, ValueError) as exc:
            return build_result(
                task, normalized_backend, provider, model, "error", started, policy, error=f"invalid ai timeout: {exc}"
            )
        deadline = started + effective_timeout

        if normalized_backend == "direct":
            try:
                fallback = normalize_fallback_backend(fallback_backend)
            except ValueError as exc:
                return build_result(
                    task,
                    normalized_backend,
                    provider,
                    model,
                    "error",
                    started,
                    policy,
                    error=str(exc),
                )
            primary = run_operation_with_deadline(
                lambda remaining: self._complete_direct(
                    task,
                    provider=provider,
                    model=model,
                    timeout=remaining,
                    policy=policy,
                    started=started,
                    deadline=deadline,
                    base_url=base_url,
                    api_key_env=api_key_env,
                ),
                task=task,
                backend=normalized_backend,
                provider=provider,
                model=model,
                started=started,
                deadline=deadline,
                timeout_seconds=effective_timeout,
                policy=policy,
            )
            primary = with_latency_evidence(
                primary,
                started=started,
                timeout_seconds=effective_timeout,
                policy=policy,
                execution_class=task.execution_class,
            )
            if primary.ok:
                return primary
            if fallback == "off":
                return primary
            if deadline_reached(deadline):
                return hard_timeout_result(
                    primary,
                    started=started,
                    timeout_seconds=effective_timeout,
                    policy=policy,
                    execution_class=task.execution_class,
                )
            remaining_timeout = remaining_timeout_seconds(deadline)
            if remaining_timeout <= 0:
                return hard_timeout_result(
                    primary,
                    started=started,
                    timeout_seconds=effective_timeout,
                    policy=policy,
                    execution_class=task.execution_class,
                )
            fallback_result = run_operation_with_deadline(
                lambda remaining: self._complete_hermes_z(
                    task,
                    provider=provider,
                    model=model,
                    timeout=remaining,
                    policy=policy,
                    started=started,
                    deadline=deadline,
                ),
                task=task,
                backend="hermes_z",
                provider=provider,
                model=model,
                started=started,
                deadline=deadline,
                timeout_seconds=effective_timeout,
                policy=policy,
            )
            fallback_result = with_latency_evidence(
                fallback_result,
                started=started,
                timeout_seconds=effective_timeout,
                policy=policy,
                execution_class=task.execution_class,
            )
            return with_fallback_audit(fallback_result, primary=primary)

        result = run_operation_with_deadline(
            lambda remaining: self._complete_hermes_z(
                task,
                provider=provider,
                model=model,
                timeout=remaining,
                policy=policy,
                started=started,
                deadline=deadline,
            ),
            task=task,
            backend=normalized_backend,
            provider=provider,
            model=model,
            started=started,
            deadline=deadline,
            timeout_seconds=effective_timeout,
            policy=policy,
        )
        return with_latency_evidence(
            result,
            started=started,
            timeout_seconds=effective_timeout,
            policy=policy,
            execution_class=task.execution_class,
        )

    def _complete_direct(
        self,
        task: AIHelperTask,
        *,
        provider: str,
        model: str,
        timeout: float,
        policy: AIHelperPolicy,
        started: float,
        deadline: float | None = None,
        base_url: str | None,
        api_key_env: str | None,
    ) -> AIHelperResult:
        fake_response = os.environ.get("AIGM_AI_FAKE_RESPONSE")
        if fake_response is not None:
            return parse_validate_normalize_result(
                task,
                backend="direct",
                provider=provider,
                model=model,
                status_started=started,
                policy=policy,
                raw=fake_response,
                deadline=deadline,
            )

        endpoint = resolve_direct_base_url(provider, base_url)
        api_key, key_source = resolve_api_key(provider, api_key_env)
        if not api_key:
            return build_result(
                task,
                "direct",
                provider,
                model,
                "error",
                started,
                policy,
                error=f"missing API key; set {key_source}",
            )

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return exactly one valid JSON object. Do not include Markdown or commentary.",
                },
                {"role": "user", "content": task.prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        if provider.strip().lower() == "deepseek" and model.strip().lower() == "deepseek-v4-flash":
            payload["thinking"] = {"type": "disabled"}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urlrequest.Request(
            endpoint,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "aigm-kernel-internal-ai/1",
            },
        )
        transport_timeout = min(timeout, remaining_timeout_seconds(deadline)) if deadline is not None else timeout
        if transport_timeout <= 0:
            return stage_deadline_result(task, "direct", provider, model, started, policy, "transport start")
        try:
            with urlrequest.urlopen(request, timeout=transport_timeout) as response:
                body = response.read(policy.max_output_chars * 4 + 4096).decode("utf-8", errors="replace")
        except TimeoutError:
            return build_result(
                task,
                "direct",
                provider,
                model,
                "error",
                started,
                policy,
                error=f"{task.name} {DEFAULT_DIRECT_TIMEOUT_ERROR} after {transport_timeout}s",
                failure_reason="timeout",
            )
        except urlerror.HTTPError as exc:
            message = ""
            try:
                message = exc.read(1000).decode("utf-8", errors="replace")
            except Exception:
                message = str(exc)
            return build_result(
                task,
                "direct",
                provider,
                model,
                "error",
                started,
                policy,
                error=f"direct ai HTTP {exc.code}: {trim_inline(message, 180)}",
                failure_reason="timeout" if exc.code in {408, 504} else None,
            )
        except (urlerror.URLError, OSError) as exc:
            return build_result(
                task,
                "direct",
                provider,
                model,
                "error",
                started,
                policy,
                error=f"direct ai request failed: {trim_inline(exc, 180)}",
                failure_reason="timeout" if is_timeout_exception(exc) else None,
            )

        if deadline_reached(deadline):
            return stage_deadline_result(task, "direct", provider, model, started, policy, "response read")

        raw = extract_direct_message_content(body)
        if raw is None:
            return build_result(
                task,
                "direct",
                provider,
                model,
                "error",
                started,
                policy,
                raw_text=body[: policy.max_output_chars],
                error=f"{task.name} direct ai returned no message content",
            )
        return parse_validate_normalize_result(
            task,
            backend="direct",
            provider=provider,
            model=model,
            status_started=started,
            policy=policy,
            raw=raw,
            deadline=deadline,
        )

    def _complete_hermes_z(
        self,
        task: AIHelperTask,
        *,
        provider: str,
        model: str,
        timeout: float,
        policy: AIHelperPolicy,
        started: float,
        deadline: float | None = None,
    ) -> AIHelperResult:
        command = [
            "hermes",
            "-z",
            task.prompt,
            "--provider",
            provider,
            "--model",
            model,
            "--ignore-rules",
        ]
        process_timeout = min(timeout, remaining_timeout_seconds(deadline)) if deadline is not None else timeout
        if process_timeout <= 0:
            return stage_deadline_result(task, "hermes_z", provider, model, started, policy, "process start")
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=process_timeout,
                check=False,
            )
        except FileNotFoundError:
            return build_result(task, "hermes_z", provider, model, "error", started, policy, error="hermes command not found")
        except subprocess.TimeoutExpired:
            return build_result(
                task,
                "hermes_z",
                provider,
                model,
                "error",
                started,
                policy,
                error=f"{task.name} ai timed out after {process_timeout}s",
                failure_reason="timeout",
            )
        except OSError as exc:
            return build_result(
                task,
                "hermes_z",
                provider,
                model,
                "error",
                started,
                policy,
                error=f"failed to run hermes: {trim_inline(exc, 140)}",
                failure_reason="timeout" if is_timeout_exception(exc) else None,
            )

        stdout = completed.stdout or ""
        if deadline_reached(deadline):
            return stage_deadline_result(task, "hermes_z", provider, model, started, policy, "process completion")
        raw = stdout[: policy.max_output_chars]
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            return build_result(
                task,
                "hermes_z",
                provider,
                model,
                "error",
                started,
                policy,
                raw_text=raw,
                error=trim_inline(message or f"hermes exited with {completed.returncode}", 180),
            )
        if len(stdout) > policy.max_output_chars:
            return build_result(
                task,
                "hermes_z",
                provider,
                model,
                "error",
                started,
                policy,
                raw_text=raw,
                error=f"{task.name} ai output exceeded {policy.max_output_chars} characters",
            )
        return parse_validate_normalize_result(
            task,
            backend="hermes_z",
            provider=provider,
            model=model,
            status_started=started,
            policy=policy,
            raw=raw,
            deadline=deadline,
        )


def run_ai_helper_json(
    task: AIHelperTask,
    *,
    backend: str,
    provider: str,
    model: str,
    timeout: int,
    policy: AIHelperPolicy = DEFAULT_AI_HELPER_POLICY,
    base_url: str | None = None,
    api_key_env: str | None = None,
    fallback_backend: str | None = None,
) -> AIHelperResult:
    return InternalAIService().complete_json(
        task,
        backend=backend,
        provider=provider,
        model=model,
        timeout=timeout,
        policy=policy,
        base_url=base_url,
        api_key_env=api_key_env,
        fallback_backend=fallback_backend,
    )


def parse_validate_normalize_result(
    task: AIHelperTask,
    *,
    backend: str,
    provider: str,
    model: str,
    status_started: float,
    policy: AIHelperPolicy,
    raw: str,
    deadline: float | None = None,
) -> AIHelperResult:
    if deadline_reached(deadline):
        return stage_deadline_result(task, backend, provider, model, status_started, policy, "JSON parse")
    if len(raw) > policy.max_output_chars:
        return build_result(
            task,
            backend,
            provider,
            model,
            "error",
            status_started,
            policy,
            raw_text=raw[: policy.max_output_chars],
            error=f"{task.name} ai output exceeded {policy.max_output_chars} characters",
        )
    parsed = parse_json_object(raw)
    if not isinstance(parsed, dict):
        return build_result(
            task,
            backend,
            provider,
            model,
            "error",
            status_started,
            policy,
            raw_text=raw,
            error=f"{task.name} ai returned non-JSON output",
        )
    if deadline_reached(deadline):
        return stage_deadline_result(task, backend, provider, model, status_started, policy, "schema validation")
    schema_errors = validate_ai_output_schema(task.output_schema, parsed)
    if schema_errors:
        return build_result(
            task,
            backend,
            provider,
            model,
            "error",
            status_started,
            policy,
            raw_text=raw,
            error=f"{task.name} ai schema validation failed: {schema_errors[0]}",
        )
    if deadline_reached(deadline):
        return stage_deadline_result(task, backend, provider, model, status_started, policy, "normalization")
    if task.parser:
        if deadline_reached(deadline):
            return stage_deadline_result(task, backend, provider, model, status_started, policy, "normalization")
        try:
            parsed = task.parser(parsed)
        except Exception as exc:
            return build_result(
                task,
                backend,
                provider,
                model,
                "error",
                status_started,
                policy,
                raw_text=raw,
                error=f"{task.name} ai output normalization failed: {trim_inline(exc, 140)}",
            )
        if not isinstance(parsed, dict):
            return build_result(
                task,
                backend,
                provider,
                model,
                "error",
                status_started,
                policy,
                raw_text=raw,
                error=f"{task.name} ai output normalizer must return an object",
            )
        if deadline_reached(deadline):
            return stage_deadline_result(task, backend, provider, model, status_started, policy, "normalization")
    if deadline_reached(deadline):
        return stage_deadline_result(task, backend, provider, model, status_started, policy, "result acceptance")
    return build_result(task, backend, provider, model, "ok", status_started, policy, parsed=parsed, raw_text=raw)


def build_result(
    task: AIHelperTask,
    backend: str,
    provider: str,
    model: str,
    status: str,
    started: float,
    policy: AIHelperPolicy,
    *,
    parsed: dict[str, Any] | None = None,
    raw_text: str = "",
    error: str | None = None,
    failure_reason: str | None = None,
) -> AIHelperResult:
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    audit = helper_audit_record(
        task=task.name,
        backend=backend,
        provider=provider,
        model=model,
        status=status,
        elapsed_ms=elapsed_ms,
        error=error,
        output=parsed or raw_text,
        advisory=policy.advisory,
        no_direct_writes=policy.no_direct_writes,
    )
    return AIHelperResult(
        task=task.name,
        backend=backend,
        provider=provider,
        model=model,
        status=status,
        parsed=parsed,
        raw_text=raw_text,
        error=error,
        elapsed_ms=elapsed_ms,
        advisory=policy.advisory,
        no_direct_writes=policy.no_direct_writes,
        audit=audit,
        failure_reason=failure_reason,
    )


def with_latency_evidence(
    result: AIHelperResult,
    *,
    started: float,
    timeout_seconds: float,
    policy: AIHelperPolicy,
    execution_class: str = "foreground",
) -> AIHelperResult:
    elapsed_seconds = max(0.0, time.perf_counter() - started)
    elapsed_ms = int(elapsed_seconds * 1000)
    effective_soft_wait = min(float(policy.soft_wait_seconds), float(timeout_seconds))
    is_background = execution_class == "background"
    soft_wait_exceeded = not is_background and elapsed_seconds > effective_soft_wait
    background_target_status = (
        "before_target"
        if elapsed_seconds < policy.background_target_min_seconds
        else "within_target"
        if elapsed_seconds <= policy.background_target_max_seconds
        else "target_exceeded"
    )
    provider_timeout = result.failure_reason == "timeout"
    late_discarded = result.ok and elapsed_seconds >= timeout_seconds
    hard_timeout = result.hard_timeout or late_discarded or elapsed_seconds >= timeout_seconds
    classification = (
        "late_discarded"
        if late_discarded
        else "hard_timeout"
        if hard_timeout
        else "backend_timeout"
        if provider_timeout
        else f"background_{background_target_status}"
        if is_background
        else "soft_wait_exceeded"
        if soft_wait_exceeded
        else "within_soft_wait"
    )
    audit = dict(result.audit)
    audit["elapsed_ms"] = elapsed_ms
    audit["latency"] = {
        "classification": classification,
        "elapsed_ms": elapsed_ms,
        "soft_wait_seconds": effective_soft_wait,
        "configured_soft_wait_seconds": policy.soft_wait_seconds,
        "hard_timeout_seconds": timeout_seconds,
        "execution_class": execution_class,
        "soft_wait_exceeded": soft_wait_exceeded,
        "hard_timeout": hard_timeout,
        "late_discarded": late_discarded,
        "background_target_seconds": [
            policy.background_target_min_seconds,
            policy.background_target_max_seconds,
        ],
        "background_target_status": background_target_status if is_background else "not_applicable",
    }
    if late_discarded:
        late_error = f"{result.task} result arrived after hard timeout of {timeout_seconds}s"
        audit.update({"status": "error", "error": late_error, "elapsed_ms": elapsed_ms, "output_summary": ""})
        return replace(
            result,
            status="error",
            parsed=None,
            raw_text="",
            error=late_error,
            elapsed_ms=elapsed_ms,
            audit=audit,
            failure_reason="timeout",
            soft_wait_exceeded=soft_wait_exceeded,
            hard_timeout=True,
            late_discarded=True,
            timeout_seconds=timeout_seconds,
        )
    if hard_timeout:
        hard_error = f"{result.task} ai timed out after {timeout_seconds}s total budget"
        audit.update({"status": "error", "error": hard_error, "elapsed_ms": elapsed_ms, "output_summary": ""})
        return replace(
            result,
            status="error",
            parsed=None,
            raw_text="",
            error=hard_error,
            elapsed_ms=elapsed_ms,
            audit=audit,
            failure_reason="timeout",
            soft_wait_exceeded=soft_wait_exceeded,
            hard_timeout=True,
            late_discarded=False,
            timeout_seconds=timeout_seconds,
        )
    return replace(
        result,
        elapsed_ms=elapsed_ms,
        audit=audit,
        soft_wait_exceeded=soft_wait_exceeded,
        hard_timeout=hard_timeout,
        late_discarded=False,
        timeout_seconds=timeout_seconds,
    )


def remaining_timeout_seconds(deadline: float) -> float:
    return max(0.0, deadline - time.perf_counter())


def hard_timeout_result(
    result: AIHelperResult,
    *,
    started: float,
    timeout_seconds: float,
    policy: AIHelperPolicy,
    execution_class: str = "foreground",
) -> AIHelperResult:
    timed_out = replace(
        result,
        status="error",
        parsed=None,
        error=f"{result.task} ai timed out after {timeout_seconds}s total budget",
        failure_reason="timeout",
        hard_timeout=True,
    )
    return with_latency_evidence(
        timed_out,
        started=started,
        timeout_seconds=timeout_seconds,
        policy=policy,
        execution_class=execution_class,
    )


def run_operation_with_deadline(
    operation: Any,
    *,
    task: AIHelperTask,
    backend: str,
    provider: str,
    model: str,
    started: float,
    deadline: float,
    timeout_seconds: float,
    policy: AIHelperPolicy,
) -> AIHelperResult:
    remaining = remaining_timeout_seconds(deadline)
    if remaining <= 0:
        return deadline_timeout_result(task, backend, provider, model, started, policy, timeout_seconds)
    holder: dict[str, Any] = {}
    worker_slots = _AI_HELPER_WORKER_SLOTS[task.execution_class]
    try:
        completed = threading.Event()
        slot_lock = threading.Lock()
    except Exception as exc:
        return worker_unavailable_result(
            task,
            backend,
            provider,
            model,
            started,
            policy,
            f"ai helper worker setup failed: {trim_inline(exc, 140)}",
        )
    if not worker_slots.acquire(blocking=False):
        return worker_unavailable_result(
            task,
            backend,
            provider,
            model,
            started,
            policy,
            "ai helper worker capacity exhausted",
        )
    slot_released = False
    worker_entered = False
    start_cancelled = False

    def release_slot_locked() -> None:
        nonlocal slot_released
        if slot_released:
            return
        slot_released = True
        worker_slots.release()

    def release_slot() -> None:
        with slot_lock:
            release_slot_locked()

    def invoke() -> None:
        nonlocal worker_entered
        with slot_lock:
            if start_cancelled:
                completed.set()
                return
            worker_entered = True
        try:
            remaining_now = remaining_timeout_seconds(deadline)
            holder["result"] = (
                deadline_timeout_result(task, backend, provider, model, started, policy, timeout_seconds)
                if remaining_now <= 0
                else context.run(operation, remaining_now)
            )
        except BaseException as exc:  # process-control exceptions are re-raised on the caller thread below
            holder["error"] = exc
        finally:
            release_slot()
            completed.set()

    worker: threading.Thread | None = None
    try:
        context = copy_context()
        worker = threading.Thread(target=invoke, name=f"aigm-ai-{task.name}", daemon=True)
        worker.start()
    except BaseException as exc:
        with slot_lock:
            if not worker_entered:
                start_cancelled = True
                release_slot_locked()
        if not isinstance(exc, Exception):
            raise
        return worker_unavailable_result(
            task,
            backend,
            provider,
            model,
            started,
            policy,
            f"ai helper worker start failed: {trim_inline(exc, 140)}",
        )
    wait_budget = remaining_timeout_seconds(deadline)
    if wait_budget <= 0 or not completed.wait(wait_budget):
        return deadline_timeout_result(task, backend, provider, model, started, policy, timeout_seconds)
    worker_error = holder.get("error")
    if worker_error is not None and not isinstance(worker_error, Exception):
        raise worker_error
    if deadline_reached(deadline):
        return deadline_timeout_result(task, backend, provider, model, started, policy, timeout_seconds)
    if worker_error is not None:
        return worker_unavailable_result(
            task,
            backend,
            provider,
            model,
            started,
            policy,
            f"ai helper worker failed: {trim_inline(worker_error, 140)}",
        )
    return holder["result"]


def deadline_timeout_result(
    task: AIHelperTask,
    backend: str,
    provider: str,
    model: str,
    started: float,
    policy: AIHelperPolicy,
    timeout_seconds: float,
) -> AIHelperResult:
    result = build_result(
        task,
        backend,
        provider,
        model,
        "error",
        started,
        policy,
        error=f"{task.name} ai timed out after {timeout_seconds}s total budget",
        failure_reason="timeout",
    )
    result = replace(result, hard_timeout=True)
    return with_latency_evidence(
        result,
        started=started,
        timeout_seconds=timeout_seconds,
        policy=policy,
        execution_class=task.execution_class,
    )


def worker_unavailable_result(
    task: AIHelperTask,
    backend: str,
    provider: str,
    model: str,
    started: float,
    policy: AIHelperPolicy,
    error: str,
) -> AIHelperResult:
    return build_result(
        task,
        backend,
        provider,
        model,
        "error",
        started,
        policy,
        error=error,
        failure_reason="worker_unavailable",
    )


def stage_deadline_result(
    task: AIHelperTask,
    backend: str,
    provider: str,
    model: str,
    started: float,
    policy: AIHelperPolicy,
    stage: str,
) -> AIHelperResult:
    return build_result(
        task,
        backend,
        provider,
        model,
        "error",
        started,
        policy,
        error=f"{task.name} hard deadline reached before {stage}",
        failure_reason="timeout",
    )


def deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.perf_counter() >= deadline


def is_timeout_exception(exc: BaseException) -> bool:
    pending: list[BaseException] = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        if isinstance(current, urlerror.URLError) and isinstance(current.reason, BaseException):
            pending.append(current.reason)
        if isinstance(current.__cause__, BaseException):
            pending.append(current.__cause__)
        if isinstance(current.__context__, BaseException):
            pending.append(current.__context__)
    return False


def parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.S)
    if fence:
        stripped = fence.group(1)
    elif "{" in stripped and "}" in stripped:
        stripped = stripped[stripped.find("{") : stripped.rfind("}") + 1]
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def normalize_backend_name(value: str | None) -> str:
    backend = str(value or "off").strip().lower()
    return BACKEND_ALIASES.get(backend, backend)


def normalize_fallback_backend(value: str | None) -> str:
    if value is None:
        return "off"
    backend = normalize_backend_name(value)
    if backend not in {"off", "hermes_z"}:
        raise ValueError(f"unsupported ai helper fallback backend: {backend}; expected one of off, hermes_z")
    return backend


def resolve_direct_base_url(provider: str, base_url: str | None) -> str:
    provider_key = provider.strip().lower()
    configured = (base_url or os.environ.get("AIGM_AI_BASE_URL") or os.environ.get(f"{provider.upper()}_BASE_URL") or "").strip()
    if configured:
        return normalize_direct_chat_endpoint(provider_key, configured)
    return DEFAULT_DIRECT_BASE_URLS.get(provider_key, f"https://api.{provider_key}.com/v1/chat/completions")


def normalize_direct_chat_endpoint(provider_key: str, configured: str) -> str:
    url = configured.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if provider_key == "openai" and url == "https://api.openai.com":
        return f"{url}/v1/chat/completions"
    return f"{url}/chat/completions"


def resolve_api_key(provider: str, api_key_env: str | None) -> tuple[str, str]:
    provider_key = provider.strip().lower()
    env_names = (api_key_env,) if api_key_env else DEFAULT_API_KEY_ENVS.get(provider_key, (f"{provider_key.upper()}_API_KEY", "AIGM_AI_API_KEY"))
    for name in env_names:
        if not name:
            continue
        value = os.environ.get(name)
        if value:
            return value, name
    return "", " or ".join(name for name in env_names if name)


def extract_direct_message_content(body: str) -> str | None:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(value, dict):
        choices = value.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
        if isinstance(value.get("content"), str):
            return value["content"]
    return None


def with_fallback_audit(result: AIHelperResult, *, primary: AIHelperResult) -> AIHelperResult:
    audit = dict(result.audit)
    audit["fallback_used"] = True
    audit["primary_backend"] = primary.backend
    audit["primary_status"] = primary.status
    primary_summary = primary.failure_reason or primary.status
    audit["primary_error"] = primary_summary
    audit["primary_audit"] = {
        **primary.audit,
        "error": primary_summary,
        "output_summary": "",
    }
    if not result.ok:
        audit["error"] = result.failure_reason or "unavailable"
        audit["output_summary"] = ""
    return AIHelperResult(
        task=result.task,
        backend=result.backend,
        provider=result.provider,
        model=result.model,
        status=result.status,
        parsed=result.parsed,
        raw_text=result.raw_text if result.ok else "",
        error=result.error,
        elapsed_ms=result.elapsed_ms,
        advisory=result.advisory,
        no_direct_writes=result.no_direct_writes,
        audit=audit,
        failure_reason=result.failure_reason,
        soft_wait_exceeded=result.soft_wait_exceeded,
        hard_timeout=result.hard_timeout,
        late_discarded=result.late_discarded,
        timeout_seconds=result.timeout_seconds,
    )


def public_ai_helper_result_dict(result: Any) -> dict[str, Any]:
    """Return player-safe helper evidence without provider payloads or exception text."""

    source_task = getattr(result, "task", "ai helper")
    task = source_task if isinstance(source_task, str) and source_task in PUBLIC_AI_HELPER_TASKS else "ai helper"
    source_failure_reason = getattr(result, "failure_reason", None)
    failure_reason = (
        source_failure_reason
        if isinstance(source_failure_reason, str)
        and source_failure_reason in {"timeout", "worker_unavailable"}
        else "unavailable"
        if source_failure_reason
        else None
    )
    hard_timeout = getattr(result, "hard_timeout", False) is True
    late_discarded = getattr(result, "late_discarded", False) is True
    error = getattr(result, "error", None)
    public_error = None
    if error:
        public_error = (
            f"{task} ai timed out"
            if failure_reason == "timeout" or hard_timeout or late_discarded
            else f"{task} ai unavailable"
        )
    source_audit = getattr(result, "audit", {})
    audit = public_ai_helper_audit(source_audit, public_error=public_error)
    source_timeout = getattr(result, "timeout_seconds", None)
    timeout_seconds = public_nonnegative_number(source_timeout, default=None)
    return {
        "task": task,
        "backend": public_backend(getattr(result, "backend", "")),
        "provider": "",
        "model": "",
        "status": public_status(getattr(result, "status", "error")),
        "error": public_error,
        "elapsed_ms": public_nonnegative_number(getattr(result, "elapsed_ms", 0), default=0),
        "advisory": True,
        "no_direct_writes": True,
        "failure_reason": failure_reason,
        "soft_wait_exceeded": getattr(result, "soft_wait_exceeded", False) is True,
        "hard_timeout": hard_timeout,
        "late_discarded": late_discarded,
        "timeout_seconds": timeout_seconds,
        "audit": audit,
    }


def public_ai_helper_audit(
    value: Any,
    *,
    public_error: str | None,
    depth: int = 0,
    seen: set[int] | None = None,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    visited = set() if seen is None else seen
    if depth >= MAX_PUBLIC_AUDIT_DEPTH or id(source) in visited:
        return {}
    visited.add(id(source))
    public: dict[str, Any] = {}
    if "task" in source:
        source_task = source["task"]
        public["task"] = (
            source_task if isinstance(source_task, str) and source_task in PUBLIC_AI_HELPER_TASKS else "ai helper"
        )
    for key in ("backend", "primary_backend"):
        if key in source:
            public[key] = public_backend(source[key])
    for key in ("provider", "model"):
        if key in source:
            public[key] = ""
    for key in ("status", "primary_status"):
        if key in source:
            public[key] = public_status(source[key])
    if "elapsed_ms" in source:
        public["elapsed_ms"] = public_nonnegative_number(source["elapsed_ms"], default=0)
    if "advisory" in source:
        public["advisory"] = True
    if "no_direct_writes" in source:
        public["no_direct_writes"] = True
    if "fallback_used" in source:
        public["fallback_used"] = public_bool(source["fallback_used"], default=False)
    latency = public_ai_helper_latency(source.get("latency"))
    if latency:
        public["latency"] = latency
    if "error" in source or public_error is not None:
        public["error"] = public_error
    if "output_summary" in source:
        public["output_summary"] = ""
    primary_audit = source.get("primary_audit")
    if isinstance(primary_audit, dict):
        primary_error_value = source.get("primary_error")
        primary_error = primary_error_value if isinstance(primary_error_value, str) else "unavailable"
        if primary_error not in {"timeout", "worker_unavailable", "error", "off", "unavailable"}:
            primary_error = "unavailable"
        public["primary_error"] = primary_error
        public["primary_audit"] = public_ai_helper_audit(
            primary_audit,
            public_error=primary_error,
            depth=depth + 1,
            seen=visited,
        )
    return public


def public_ai_helper_latency(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    public: dict[str, Any] = {}
    classification = source.get("classification")
    if isinstance(classification, str) and classification in {
        "late_discarded",
        "hard_timeout",
        "backend_timeout",
        "soft_wait_exceeded",
        "within_soft_wait",
        "background_before_target",
        "background_within_target",
        "background_target_exceeded",
    }:
        public["classification"] = classification
    execution_class = source.get("execution_class")
    if isinstance(execution_class, str) and execution_class in {"foreground", "background"}:
        public["execution_class"] = execution_class
    background_status = source.get("background_target_status")
    if isinstance(background_status, str) and background_status in {
        "not_applicable",
        "before_target",
        "within_target",
        "target_exceeded",
    }:
        public["background_target_status"] = background_status
    for key in (
        "elapsed_ms",
        "soft_wait_seconds",
        "configured_soft_wait_seconds",
        "hard_timeout_seconds",
    ):
        item = source.get(key)
        public_item = public_nonnegative_number(item, default=None)
        if public_item is not None:
            public[key] = public_item
    for key in ("soft_wait_exceeded", "hard_timeout", "late_discarded"):
        item = source.get(key)
        if item is True or item is False:
            public[key] = item
    target = source.get("background_target_seconds")
    if (
        isinstance(target, (list, tuple))
        and len(target) == 2
        and all(public_nonnegative_number(item, default=None) is not None for item in target)
    ):
        public["background_target_seconds"] = list(target)
    return public


def public_backend(value: Any) -> str:
    return value if isinstance(value, str) and value in {"off", "direct", "hermes_z", "preflight_cache"} else ""


def public_status(value: Any) -> str:
    return value if isinstance(value, str) and value in {"ok", "error", "off", "ready", "failed"} else "error"


def public_bool(value: Any, *, default: bool) -> bool:
    return value if value is True or value is False else default


def public_nonnegative_number(value: Any, *, default: int | float | None) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return default
    if isinstance(value, int):
        return value if value <= MAX_PUBLIC_SAFE_INTEGER else default
    if math.isfinite(value) and value <= MAX_PUBLIC_SAFE_INTEGER:
        return value
    return default


def trim_inline(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)] + "…"
