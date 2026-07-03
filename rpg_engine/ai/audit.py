from __future__ import annotations

from typing import Any


def summarize_ai_payload(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "..."


def helper_audit_record(
    *,
    task: str,
    backend: str,
    provider: str,
    model: str,
    status: str,
    elapsed_ms: int,
    error: str | None = None,
    output: Any = None,
    advisory: bool = True,
    no_direct_writes: bool = True,
) -> dict[str, Any]:
    return {
        "task": task,
        "backend": backend,
        "provider": provider,
        "model": model,
        "status": status,
        "elapsed_ms": elapsed_ms,
        "advisory": advisory,
        "no_direct_writes": no_direct_writes,
        "error": error,
        "output_summary": summarize_ai_payload(output) if output is not None else "",
    }
