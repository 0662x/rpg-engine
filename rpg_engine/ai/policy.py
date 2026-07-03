from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AIHelperPolicy:
    advisory: bool = True
    fail_closed: bool = True
    no_direct_writes: bool = True
    min_timeout_seconds: int = 3
    max_timeout_seconds: int = 120
    max_output_chars: int = 12000


DEFAULT_AI_HELPER_POLICY = AIHelperPolicy()


def normalize_timeout(value: int | None, policy: AIHelperPolicy = DEFAULT_AI_HELPER_POLICY) -> int:
    if value is None:
        return policy.min_timeout_seconds
    return min(policy.max_timeout_seconds, max(policy.min_timeout_seconds, int(value)))
