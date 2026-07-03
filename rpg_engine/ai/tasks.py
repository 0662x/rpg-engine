from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AIHelperTask:
    name: str
    prompt: str
    output_schema: str
    parser: Callable[[dict[str, Any]], dict[str, Any]] | None = None
