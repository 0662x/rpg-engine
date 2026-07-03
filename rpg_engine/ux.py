from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


UxStatus = Literal["ready", "needs_confirmation", "clarify", "blocked", "internal_error"]
UxView = Literal["player", "gm", "debug"]


@dataclass(frozen=True)
class RepairOption:
    id: str
    label: str
    description: str = ""
    action: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    effect: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = True


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    action: str
    label: str
    status: UxStatus = "ready"
    options: dict[str, Any] = field(default_factory=dict)
    estimated_minutes: int | None = None
    risk_level: str = "low"
    delta_draft: dict[str, Any] | None = None


@dataclass(frozen=True)
class UxEnvelope:
    status: UxStatus
    ready_to_save: bool
    player_message: str
    interpretation: dict[str, Any] = field(default_factory=dict)
    plan: tuple[PlanStep, ...] = ()
    repair_options: tuple[RepairOption, ...] = ()
    delta_draft: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    debug: dict[str, Any] = field(default_factory=dict)
