from __future__ import annotations

import math
from dataclasses import dataclass

from .defaults import (
    DEFAULT_AI_SOFT_WAIT_SECONDS,
    DEFAULT_BACKGROUND_TARGET_MAX_SECONDS,
    DEFAULT_BACKGROUND_TARGET_MIN_SECONDS,
)

MAX_AI_TIMEOUT_SECONDS = 120


def is_finite_nonnegative_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return False
    return not isinstance(value, float) or math.isfinite(value)


@dataclass(frozen=True)
class AIHelperPolicy:
    advisory: bool = True
    fail_closed: bool = True
    no_direct_writes: bool = True
    min_timeout_seconds: int = 3
    max_timeout_seconds: int = 120
    max_output_chars: int = 12000
    soft_wait_seconds: int = DEFAULT_AI_SOFT_WAIT_SECONDS
    background_target_min_seconds: int = DEFAULT_BACKGROUND_TARGET_MIN_SECONDS
    background_target_max_seconds: int = DEFAULT_BACKGROUND_TARGET_MAX_SECONDS

    def __post_init__(self) -> None:
        for name in ("advisory", "fail_closed", "no_direct_writes"):
            if getattr(self, name) is not True:
                raise ValueError(f"{name} must remain true for AI helper policy")
        for name in (
            "min_timeout_seconds",
            "max_timeout_seconds",
            "max_output_chars",
            "soft_wait_seconds",
            "background_target_min_seconds",
            "background_target_max_seconds",
        ):
            value = getattr(self, name)
            if not is_finite_nonnegative_number(value):
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.min_timeout_seconds > self.max_timeout_seconds:
            raise ValueError("min_timeout_seconds must not exceed max_timeout_seconds")
        if not isinstance(self.min_timeout_seconds, int) or not isinstance(self.max_timeout_seconds, int):
            raise ValueError("min_timeout_seconds and max_timeout_seconds must be integers")
        if self.max_timeout_seconds > MAX_AI_TIMEOUT_SECONDS:
            raise ValueError(f"max_timeout_seconds must not exceed {MAX_AI_TIMEOUT_SECONDS}")
        if self.max_output_chars <= 0:
            raise ValueError("max_output_chars must be greater than zero")
        if not isinstance(self.max_output_chars, int):
            raise ValueError("max_output_chars must be an integer")
        if self.soft_wait_seconds > self.max_timeout_seconds:
            raise ValueError("soft_wait_seconds must not exceed max_timeout_seconds")
        if self.background_target_min_seconds > self.background_target_max_seconds:
            raise ValueError("background_target_min_seconds must not exceed background_target_max_seconds")
        if self.background_target_max_seconds > self.max_timeout_seconds:
            raise ValueError("background_target_max_seconds must not exceed max_timeout_seconds")


DEFAULT_AI_HELPER_POLICY = AIHelperPolicy()


def normalize_timeout(value: int | float | None, policy: AIHelperPolicy = DEFAULT_AI_HELPER_POLICY) -> int:
    if value is None:
        return policy.min_timeout_seconds
    if not is_finite_nonnegative_number(value):
        raise ValueError("ai timeout must be a finite number")
    bounded = min(policy.max_timeout_seconds, max(policy.min_timeout_seconds, value))
    return int(bounded)
