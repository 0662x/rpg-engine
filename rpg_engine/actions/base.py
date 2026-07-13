from __future__ import annotations

import sqlite3
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from ..campaign import Campaign
from ..ux import PlanStep, RepairOption
from .taxonomy import (
    ACTION_TAXONOMY_VERSION,
    ActionTaxonomySpec,
    ActionTaxonomyTerm,
    build_action_taxonomy_projection,
    legacy_action_taxonomy,
    normalize_taxonomy_text,
    taxonomy_term_match_spans_normalized,
    taxonomy_term_matches_normalized,
    validate_executable_taxonomy_locales,
)


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


_TAXONOMY_UNSET = object()


@dataclass(frozen=True, init=False)
class ActionResolverSpec:
    name: str
    preview: PreviewAction
    response_template: str
    request_model: type = dict
    proposal_model: type = dict
    required_options: tuple[str, ...] = field(default_factory=tuple)
    option_specs: tuple[ActionOptionSpec, ...] = field(default_factory=tuple)
    taxonomy: ActionTaxonomySpec = field(default_factory=ActionTaxonomySpec)
    required_context: RequiredContextAction | None = None
    validate_request: ValidateRequestAction | None = None
    resolve: ResolveAction | None = None
    validate_delta: ValidateDeltaAction | None = None

    def __init__(
        self,
        name: str,
        preview: PreviewAction,
        response_template: str,
        request_model: type = dict,
        proposal_model: type = dict,
        required_options: tuple[str, ...] = (),
        option_specs: tuple[ActionOptionSpec, ...] = (),
        keywords: tuple[str, ...] | object = _TAXONOMY_UNSET,
        semantic_labels: tuple[str, ...] | object = _TAXONOMY_UNSET,
        inference_priority: int | object = _TAXONOMY_UNSET,
        required_context: RequiredContextAction | None = None,
        validate_request: ValidateRequestAction | None = None,
        resolve: ResolveAction | None = None,
        validate_delta: ValidateDeltaAction | None = None,
        *,
        taxonomy: ActionTaxonomySpec | object = _TAXONOMY_UNSET,
    ) -> None:
        legacy_used = any(value is not _TAXONOMY_UNSET for value in (keywords, semantic_labels, inference_priority))
        canonical_used = taxonomy is not _TAXONOMY_UNSET
        if canonical_used and legacy_used:
            raise ValueError("canonical taxonomy and legacy taxonomy inputs are mutually exclusive")
        if not canonical_used:
            taxonomy = legacy_action_taxonomy(
                keywords=() if keywords is _TAXONOMY_UNSET else keywords,  # type: ignore[arg-type]
                semantic_labels=() if semantic_labels is _TAXONOMY_UNSET else semantic_labels,  # type: ignore[arg-type]
                inference_priority=50 if inference_priority is _TAXONOMY_UNSET else inference_priority,  # type: ignore[arg-type]
            )
        elif type(taxonomy) is not ActionTaxonomySpec:
            raise TypeError("taxonomy must be an exact ActionTaxonomySpec")

        for key, value in (
            ("name", name),
            ("preview", preview),
            ("response_template", response_template),
            ("request_model", request_model),
            ("proposal_model", proposal_model),
            ("required_options", required_options),
            ("option_specs", option_specs),
            ("taxonomy", taxonomy),
            ("required_context", required_context),
            ("validate_request", validate_request),
            ("resolve", resolve),
            ("validate_delta", validate_delta),
        ):
            object.__setattr__(self, key, value)

    @property
    def keywords(self) -> tuple[str, ...]:
        return self.taxonomy.keywords

    @property
    def semantic_labels(self) -> tuple[str, ...]:
        return self.taxonomy.semantic_labels

    @property
    def inference_priority(self) -> int:
        return self.taxonomy.inference_priority

    def request_contract(
        self, campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any
    ) -> ActionValidationResult:
        if self.validate_request:
            return self.validate_request(campaign, conn, context, options)
        return validate_required_options(self, options)

    def required_context_ids(
        self, campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any
    ) -> list[str]:
        if self.required_context:
            return self.required_context(campaign, conn, context, options)
        return []

    def resolve_contract(
        self, campaign: Campaign, conn: sqlite3.Connection, context: dict[str, Any], options: Any
    ) -> ResolutionResult:
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


_ENGLISH_NON_TARGET_ATOM = (
    r"(?:again|eventually|immediately|later|now|please|someday|soon|today|tonight|tomorrow|"
    r"for\s+(?:me|us)|right\s+now|"
    r"(?:in\s+the|this|tomorrow)\s+(?:morning|afternoon|evening|night|weekend)|"
    r"in\s+(?:a|an|one|two|three|four|several|few|many|\d+)\s+"
    r"(?:hours?|days?|weeks?|months?|years?)|"
    r"for\s+(?:a|an|one|two|three|four|several|few|many|\d+)\s+(?:hours?|days?|weeks?|months?|years?)|"
    r"during\s+(?:the\s+)?(?:day|week|weekend|month|year)|"
    r"on\s+(?:(?:the\s+)?(?:weekends?|weekdays?)|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|"
    r"(?:after|before)\s+(?:(?:one|two|three|four|several|\d+)\s+(?:hours?|days?|weeks?)|"
    r"breakfast|lunch|dinner|work|school)|"
    r"at\s+(?:dawn|noon|midnight|night)|"
    r"by\s+(?:today|tonight|tomorrow)|"
    r"this\s+(?:day|week|month|year)|(?:every|each)\s+"
    r"(?:hour|morning|afternoon|evening|night|day|weekday|week|weekend|month|year)|"
    r"next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"(?:alone|carefully|here|indoors|outside|quickly|slowly|there|together)|"
    r"until\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"next\s+(?:day|week|weekend|month|year)|"
    r"(?:hourly|daily|nightly|weekly|monthly|quarterly|yearly|annually|when\s+ready)|"
    r"at\s+(?:(?:the\s+)?weekend|camp|home|work))"
)
_ENGLISH_NON_TARGET_SUFFIX = re.compile(rf"{_ENGLISH_NON_TARGET_ATOM}(?:\s+{_ENGLISH_NON_TARGET_ATOM})*$")
_JAPANESE_NON_TARGET_SUFFIX = re.compile(
    r"(?:"
    r"(?:を)?(?:する|します|しました|しています|していました|している|した|して|しよう|したい|"
    r"できる|できます|してください|して下さい|しましょう)"
    r"(?:予定(?:です|でした|だ|だった)?|つもり(?:です|でした|だ|だった)?|"
    r"計画(?:です|でした|だ|だった)?|こと|ため)?|"
    r"(?:を)?お願いします|"
    r"(?:の)?(?:予定(?:です|でした|だ|だった)?|つもり(?:です|でした|だ|だった)?|"
    r"計画(?:です|でした|だ|だった)?|こと|ため)|"
    r"について|は|なら|だけ|明日|来週|今日|今夜|毎日|は(?:明日|来週|今日)(?:です)?"
    r")$"
)
_KOREAN_NON_TARGET_SUFFIX = re.compile(
    r"(?:"
    r"(?:을|를)?(?:하다|합니다|했습니다|하고|한다|했다|해|해요|하세요|할|할게요|"
    r"하고있다|하고있습니다|해주세요|해주십시오|해달라|합시다)"
    r"(?:예정(?:입니다|이었습니다|이다|이었다)?|계획(?:입니다|이었습니다|이다|이었다)?|것|위해)?|"
    r"(?:을|를)?부탁(?:해요|합니다)?|"
    r"(?:의)?(?:예정(?:입니다|이었습니다|이다|이었다)?|"
    r"계획(?:입니다|이었습니다|이다|이었다)?|것|위해)|"
    r"에대해|에관해|은|는|만|내일|다음주|오늘|오늘밤|매일|"
    r"(?:은|는)(?:내일|다음주|오늘)(?:입니다)?"
    r")$"
)


def _suffix_is_non_target_grammar(suffix: str, locale: str) -> bool:
    start = 0
    end = len(suffix)
    while start < end and (suffix[start].isspace() or unicodedata.category(suffix[start])[0] in "MPS"):
        start += 1
    while end > start and (suffix[end - 1].isspace() or unicodedata.category(suffix[end - 1])[0] in "MPS"):
        end -= 1
    core = suffix[start:end]
    if not core:
        return True
    language = locale.partition("-")[0].casefold()
    if language == "en":
        return _ENGLISH_NON_TARGET_SUFFIX.fullmatch(core.casefold()) is not None
    compact = re.sub(r"\s+", "", core)
    if language == "ja":
        return _JAPANESE_NON_TARGET_SUFFIX.fullmatch(compact) is not None
    if language == "ko":
        return _KOREAN_NON_TARGET_SUFFIX.fullmatch(compact) is not None
    return False


class ActionResolverRegistry:
    def __init__(self, *, taxonomy_version: str = ACTION_TAXONOMY_VERSION) -> None:
        build_action_taxonomy_projection((), version=taxonomy_version)
        self._taxonomy_version = taxonomy_version
        self._specs: dict[str, ActionResolverSpec] = {}

    def register(self, spec: ActionResolverSpec) -> None:
        if not isinstance(spec, ActionResolverSpec):
            raise TypeError("action resolver must be an ActionResolverSpec")
        if spec.name in self._specs:
            raise ValueError(f"Duplicate action resolver: {spec.name}")
        validate_executable_taxonomy_locales(spec.taxonomy)
        prospective = {**self._specs, spec.name: spec}
        build_action_taxonomy_projection(
            ((name, item.taxonomy) for name, item in prospective.items()),
            version=self._taxonomy_version,
        )
        self._specs[spec.name] = spec

    def get(self, name: str) -> ActionResolverSpec | None:
        return self._specs.get(name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def all(self) -> list[ActionResolverSpec]:
        return [self._specs[name] for name in self.names()]

    def taxonomy_projection(self) -> dict[str, Any]:
        return build_action_taxonomy_projection(
            ((spec.name, spec.taxonomy) for spec in self.all()),
            version=self._taxonomy_version,
        )

    @property
    def taxonomy_version(self) -> str:
        return self._taxonomy_version

    @property
    def taxonomy_digest(self) -> str:
        return str(self.taxonomy_projection()["digest"])

    def _selected_specs(self, action: str | None) -> list[ActionResolverSpec]:
        if action is None:
            return self.all()
        spec = self._specs.get(action)
        return [spec] if spec is not None else []

    def terms_for(
        self,
        action: str | None = None,
        *,
        role: str | None = None,
        locale: str | None = None,
    ) -> tuple[str, ...]:
        specs = self._selected_specs(action)
        return tuple(
            term.value
            for spec in specs
            for term in spec.taxonomy.terms
            if (role is None or role in term.roles) and (locale is None or locale == term.locale)
        )

    def text_has_term(
        self,
        text: str,
        *,
        action: str | None = None,
        role: str | None = None,
    ) -> bool:
        specs = self._selected_specs(action)
        normalized_text = normalize_taxonomy_text(str(text))
        return any(
            taxonomy_term_matches_normalized(normalized_text, term)
            for spec in specs
            for term in spec.taxonomy.terms
            if role is None or role in term.roles
        )

    def text_has_term_with_target_content(
        self,
        text: str,
        *,
        action: str,
        role: str | None = None,
    ) -> bool:
        spec = self._specs.get(action)
        if spec is None:
            return False
        normalized_text = normalize_taxonomy_text(str(text))
        matches = (
            (end, end - start, start, term.locale)
            for term in spec.taxonomy.terms
            if role is None or role in term.roles
            for start, end in taxonomy_term_match_spans_normalized(normalized_text, term)
        )
        last_match = max(matches, key=lambda item: (item[0], item[1]), default=None)
        if last_match is None:
            return False
        locale = last_match[3].casefold()
        suffix = normalized_text[last_match[0] :]
        suffix_is_non_target_grammar = _suffix_is_non_target_grammar(suffix, locale)
        if not suffix_is_non_target_grammar and any(character.isalnum() for character in suffix):
            return True
        prefix = normalized_text[: last_match[2]].rstrip(" \t\r\n,，、。.!！?？:：;；")
        particles = ("を",) if locale.startswith("ja") else ("을", "를") if locale.startswith("ko") else ()
        for particle in particles:
            if prefix.endswith(particle) and any(character.isalnum() for character in prefix[: -len(particle)]):
                return True
        return False

    def match_action(self, text: str, *, role: str = "simple") -> str | None:
        match = self.match_action_terms(text, role=role)
        return match[0] if match is not None else None

    def match_action_terms(
        self,
        text: str,
        *,
        role: str = "simple",
    ) -> tuple[str, tuple[ActionTaxonomyTerm, ...]] | None:
        normalized_text = normalize_taxonomy_text(str(text))
        specs = sorted(
            self.all(),
            key=lambda spec: (spec.name == "travel", spec.inference_priority, spec.name),
        )
        for spec in specs:
            terms = tuple(
                term
                for term in spec.taxonomy.terms
                if role in term.roles and taxonomy_term_matches_normalized(normalized_text, term)
            )
            if terms:
                return spec.name, terms
        return None

    def match_action_term(
        self,
        text: str,
        *,
        role: str = "simple",
    ) -> tuple[str, ActionTaxonomyTerm] | None:
        match = self.match_action_terms(text, role=role)
        if match is None:
            return None
        action, terms = match
        term = max(
            terms,
            key=lambda item: (len(item.normalized_value), item.locale.casefold(), item.value),
        )
        return action, term
