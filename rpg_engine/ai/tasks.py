from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AIHelperTask:
    """Side-effect-free JSON helper task.

    Parsers normalize already bounded model output. They must not write files,
    databases, caches, or external services because a timed-out daemon worker
    may finish normalization after the caller has safely degraded.
    """

    name: str
    prompt: str
    output_schema: str
    parser: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    execution_class: str = "foreground"

    def __post_init__(self) -> None:
        if self.execution_class not in {"foreground", "background"}:
            raise ValueError("execution_class must be foreground or background")
