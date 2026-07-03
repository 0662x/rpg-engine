from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
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
            primary = self._complete_direct(
                task,
                provider=provider,
                model=model,
                timeout=effective_timeout,
                policy=policy,
                started=started,
                base_url=base_url,
                api_key_env=api_key_env,
            )
            if primary.ok:
                return primary
            if fallback == "off":
                return primary
            fallback_result = self._complete_hermes_z(
                task,
                provider=provider,
                model=model,
                timeout=effective_timeout,
                policy=policy,
                started=started,
            )
            return with_fallback_audit(fallback_result, primary=primary)

        return self._complete_hermes_z(
            task,
            provider=provider,
            model=model,
            timeout=effective_timeout,
            policy=policy,
            started=started,
        )

    def _complete_direct(
        self,
        task: AIHelperTask,
        *,
        provider: str,
        model: str,
        timeout: int,
        policy: AIHelperPolicy,
        started: float,
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
        try:
            with urlrequest.urlopen(request, timeout=timeout) as response:
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
                error=f"{task.name} {DEFAULT_DIRECT_TIMEOUT_ERROR} after {timeout}s",
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
            )

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
        )

    def _complete_hermes_z(
        self,
        task: AIHelperTask,
        *,
        provider: str,
        model: str,
        timeout: int,
        policy: AIHelperPolicy,
        started: float,
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
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=timeout,
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
                error=f"{task.name} ai timed out after {timeout}s",
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
            )

        stdout = completed.stdout or ""
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
) -> AIHelperResult:
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
    if task.parser:
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
    )


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
    audit["primary_error"] = primary.error
    audit["primary_audit"] = primary.audit
    return AIHelperResult(
        task=result.task,
        backend=result.backend,
        provider=result.provider,
        model=result.model,
        status=result.status,
        parsed=result.parsed,
        raw_text=result.raw_text,
        error=result.error,
        elapsed_ms=result.elapsed_ms,
        advisory=result.advisory,
        no_direct_writes=result.no_direct_writes,
        audit=audit,
    )


def trim_inline(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)] + "…"
