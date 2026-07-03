from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from ..campaign import Campaign
from ..ux import PlanStep, RepairOption


PreviewAction = Callable[[Campaign, sqlite3.Connection, dict[str, Any], Any], str]
RequiredContextAction = Callable[[Campaign, sqlite3.Connection, dict[str, Any], Any], list[str]]
ValidateRequestAction = Callable[[Campaign, sqlite3.Connection, dict[str, Any], Any], "ActionValidationResult"]
ResolveAction = Callable[[Campaign, sqlite3.Connection, dict[str, Any], Any], "ResolutionResult"]
ValidateDeltaAction = Callable[
    [Campaign, sqlite3.Connection, dict[str, Any], Any, dict[str, Any]],
    "ActionValidationResult",
]


@dataclass(frozen=True)
class ActionOptionSpec:
    name: str
    help: str
    required: bool = False
    default: Any = None
    dest: str | None = None


@dataclass(frozen=True)
class ActionValidationResult:
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing_required: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing_required

    def render(self) -> str:
        if self.ok and not self.warnings:
            return "OK\n"
        lines = ["OK" if self.ok else "FAILED"]
        lines.extend(f"- missing: {item}" for item in self.missing_required)
        lines.extend(f"- error: {item}" for item in self.errors)
        lines.extend(f"- warning: {item}" for item in self.warnings)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class ResolutionResult:
    status: str
    facts_used: tuple[str, ...] = ()
    rules_applied: tuple[str, ...] = ()
    confirmations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    proposed_delta: dict[str, Any] | None = None
    narrative_constraints: tuple[str, ...] = ()
    player_message: str = ""
    repair_options: tuple[RepairOption, ...] = ()
    plan: tuple[PlanStep, ...] = ()
    confidence: str = "medium"

    @property
    def ok(self) -> bool:
        return self.status == "ready"

    def render(self) -> str:
        lines = [f"status: {self.status}"]
        if self.facts_used:
            lines.append("facts_used: " + ", ".join(self.facts_used))
        if self.rules_applied:
            lines.append("rules_applied: " + ", ".join(self.rules_applied))
        if self.confirmations:
            lines.extend(f"confirmation: {item}" for item in self.confirmations)
        if self.warnings:
            lines.extend(f"warning: {item}" for item in self.warnings)
        return "\n".join(lines) + "\n"


def option_value(options: Any, name: str, default: Any = None) -> Any:
    """Read one action option from argparse or assistant request objects."""
    return getattr(options, name, default)


@dataclass(frozen=True)
class ActionResolverSpec:
    name: str
    preview: PreviewAction
    response_template: str
    request_model: type = dict
    proposal_model: type = dict
    required_options: tuple[str, ...] = field(default_factory=tuple)
    option_specs: tuple[ActionOptionSpec, ...] = field(default_factory=tuple)
    keywords: tuple[str, ...] = field(default_factory=tuple)
    semantic_labels: tuple[str, ...] = field(default_factory=tuple)
    inference_priority: int = 50
    required_context: RequiredContextAction | None = None
    validate_request: ValidateRequestAction | None = None
    resolve: ResolveAction | None = None
    validate_delta: ValidateDeltaAction | None = None

    def request_contract(self, campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> ActionValidationResult:
        if self.validate_request:
            return self.validate_request(campaign, conn, context, options)
        return validate_required_options(self, options)

    def required_context_ids(self, campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> list[str]:
        if self.required_context:
            return self.required_context(campaign, conn, context, options)
        return []

    def resolve_contract(self, campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any) -> ResolutionResult:
        if self.resolve:
            return self.resolve(campaign, conn, context, options)
        validation = self.request_contract(campaign, conn, context, options)
        if validation.ok:
            return ResolutionResult(
                status="ready",
                warnings=validation.warnings,
                narrative_constraints=("Use preview output and validated state only.",),
            )
        return ResolutionResult(
            status="needs_confirmation",
            confirmations=validation.missing_required,
            warnings=validation.warnings,
            narrative_constraints=("Ask for missing action details before saving.",),
        )

    def delta_contract(
        self,
        campaign: Campaign,
        conn: sqlite3.Connection,
        context: dict[str, Any],
        options: Any,
        delta: dict[str, Any],
    ) -> ActionValidationResult:
        if self.validate_delta:
            return self.validate_delta(campaign, conn, context, options, delta)
        del campaign, conn, context, options, delta
        return ActionValidationResult()


def validate_required_options(spec: ActionResolverSpec, options: Any) -> ActionValidationResult:
    missing = tuple(name for name in spec.required_options if not option_value(options, name))
    return ActionValidationResult(missing_required=missing)


def option_specs_for(*specs: ActionOptionSpec) -> tuple[ActionOptionSpec, ...]:
    return specs


class ActionResolverRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ActionResolverSpec] = {}

    def register(self, spec: ActionResolverSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Duplicate action resolver: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ActionResolverSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def all(self) -> list[ActionResolverSpec]:
        return [self._specs[name] for name in self.names()]
