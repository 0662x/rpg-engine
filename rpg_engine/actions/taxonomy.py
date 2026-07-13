from __future__ import annotations

from dataclasses import dataclass, field
from itertools import islice
import re
from types import MappingProxyType
import unicodedata
from typing import Any, Iterable, Mapping

from ..canonical_json import canonical_json_sha256


ACTION_TAXONOMY_VERSION = "1"
MAX_ACTION_TAXONOMY_VERSION_LENGTH = 32
MAX_ACTION_TAXONOMY_LOCALE_LENGTH = 35
MAX_ACTION_TAXONOMY_TERM_LENGTH = 128
MAX_ACTION_TAXONOMY_TERMS_PER_ACTION = 256
MAX_ACTION_TAXONOMY_ACTIONS = 128
MAX_ACTION_TAXONOMY_ROLE_LENGTH = 64
MAX_ACTION_TAXONOMY_ROLES_PER_TERM = 16
MAX_ACTION_TAXONOMY_SEMANTIC_LABEL_LENGTH = 128

LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_HAN_RANGES = (
    r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002ee5f\U0002f800-\U0002fa1f"
    r"\U00030000-\U000323af"
)
_KANA_SUPPLEMENT_RANGES = r"\U0001aff0-\U0001afff\U0001b000-\U0001b16f"
_BOPOMOFO_TONE_RANGES = r"\u02c7\u02c9-\u02cb\u02d9"
HAN_PATTERN = re.compile(f"[{_HAN_RANGES}]")
HIRAGANA_PATTERN = re.compile(r"[\u3040-\u309f\U0001b001-\U0001b11f]")
KATAKANA_PATTERN = re.compile(rf"[\u30a0-\u30ff\u31f0-\u31ff\uff65-\uff9f{_KANA_SUPPLEMENT_RANGES}]")
JAPANESE_PATTERN = re.compile(rf"[\u3040-\u30ff\u31f0-\u31ff\uff65-\uff9f{_KANA_SUPPLEMENT_RANGES}]")
BOPOMOFO_PATTERN = re.compile(r"[\u3100-\u312f\u31a0-\u31bf]")
HANGUL_PATTERN = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]")
CJK_PATTERN = re.compile(
    rf"[{_BOPOMOFO_TONE_RANGES}\u1100-\u11ff\u3040-\u30ff\u3100-\u312f"
    rf"\u3130-\u318f\u31a0-\u31bf\u31f0-\u31ff{_HAN_RANGES}"
    rf"\ua960-\ua97f\uac00-\ud7ff\uff65-\uff9f{_KANA_SUPPLEMENT_RANGES}]"
)
BOPOMOFO_TONE_MARKS = frozenset("ˉˊˇˋ˙")
IDEOGRAPHIC_ITERATION_MARKS = frozenset("々〻")
KANA_ITERATION_MARKS = frozenset("ゝゞヽヾ")
KANA_MODIFIER_MARKS = KANA_ITERATION_MARKS | frozenset("ー")
RESERVED_ACTION_NAMES = frozenset({"act", "none", "null", "unknown"})
SUPPORTED_EXECUTABLE_TAXONOMY_LANGUAGES = frozenset({"en", "ja", "ko", "zh"})
_SUPPORTED_EXECUTABLE_TAXONOMY_SCRIPTS = MappingProxyType(
    {
        "en": frozenset({"Latn"}),
        "ja": frozenset({"Hani", "Hira", "Jpan", "Kana"}),
        "ko": frozenset({"Hang", "Hani", "Kore"}),
        "zh": frozenset({"Bopo", "Hani", "Hans", "Hant"}),
    }
)

TAXONOMY_NORMALIZATION: Mapping[str, str] = MappingProxyType(
    {
        "unicode": "NFKC",
        "case": "casefold",
        "latin_match": "word_boundary",
        "cjk_match": "substring",
    }
)


def normalize_taxonomy_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _validate_exact_text(value: Any, *, label: str, max_length: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{label} must be an exact string")
    if not 1 <= len(value) <= max_length:
        raise ValueError(f"{label} must contain 1..{max_length} characters")
    if value != value.strip():
        raise ValueError(f"{label} must not contain leading or trailing whitespace")
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError(f"{label} must not contain Unicode control characters")
    return value


@dataclass(frozen=True)
class ActionTaxonomyTerm:
    locale: str
    value: str
    roles: tuple[str, ...] = ("simple",)
    _normalized_value: str = field(init=False, repr=False, compare=False)
    _match_pattern: re.Pattern[str] | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        locale = _validate_exact_text(
            self.locale,
            label="taxonomy locale",
            max_length=MAX_ACTION_TAXONOMY_LOCALE_LENGTH,
        )
        if not LOCALE_PATTERN.fullmatch(locale):
            raise ValueError("taxonomy locale must be a bounded BCP47-like tag")
        _validate_exact_text(
            self.value,
            label="taxonomy term",
            max_length=MAX_ACTION_TAXONOMY_TERM_LENGTH,
        )
        normalized_value = normalize_taxonomy_text(self.value)
        if not any(unicodedata.category(char)[0] in {"L", "N"} for char in normalized_value):
            raise ValueError("taxonomy term must contain a Unicode letter or number")
        if type(self.roles) is not tuple:
            raise TypeError("taxonomy term roles must be an exact tuple")
        if not 1 <= len(self.roles) <= MAX_ACTION_TAXONOMY_ROLES_PER_TERM:
            raise ValueError("taxonomy term roles must be a bounded non-empty tuple")
        normalized_roles: list[str] = []
        for role in self.roles:
            text = _validate_exact_text(
                role,
                label="taxonomy term role",
                max_length=MAX_ACTION_TAXONOMY_ROLE_LENGTH,
            )
            if not ROLE_PATTERN.fullmatch(text):
                raise ValueError("taxonomy term role must be a lowercase identifier")
            if text in normalized_roles:
                raise ValueError("taxonomy term roles must be unique")
            normalized_roles.append(text)
        object.__setattr__(self, "roles", tuple(sorted(normalized_roles)))
        object.__setattr__(self, "_normalized_value", normalized_value)
        object.__setattr__(self, "_match_pattern", _compile_taxonomy_match_pattern(normalized_value))

    @property
    def normalized_value(self) -> str:
        return self._normalized_value

    def to_projection(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "value": self.value,
            "roles": self.roles,
        }


@dataclass(frozen=True)
class ActionTaxonomySpec:
    terms: tuple[ActionTaxonomyTerm, ...] = ()
    semantic_labels: tuple[str, ...] = ()
    inference_priority: int = 50

    def __post_init__(self) -> None:
        if type(self.terms) is not tuple:
            raise TypeError("taxonomy terms must be an exact tuple")
        if len(self.terms) > MAX_ACTION_TAXONOMY_TERMS_PER_ACTION:
            raise ValueError("taxonomy has too many terms for one action")
        if any(type(term) is not ActionTaxonomyTerm for term in self.terms):
            raise TypeError("taxonomy terms must contain exact ActionTaxonomyTerm values")
        if type(self.semantic_labels) is not tuple:
            raise TypeError("taxonomy semantic labels must be an exact tuple")
        labels: list[str] = []
        seen_labels: set[str] = set()
        for label in self.semantic_labels:
            text = _validate_exact_text(
                label,
                label="taxonomy semantic label",
                max_length=MAX_ACTION_TAXONOMY_SEMANTIC_LABEL_LENGTH,
            )
            normalized = normalize_taxonomy_text(text)
            if normalized in seen_labels:
                raise ValueError("taxonomy semantic labels must be unique after normalization")
            seen_labels.add(normalized)
            labels.append(text)
        if type(self.inference_priority) is not int:
            raise TypeError("taxonomy inference priority must be an exact integer")

        terms = sorted(
            self.terms,
            key=lambda term: (
                term.normalized_value,
                term.locale.casefold(),
                term.value,
                term.roles,
            ),
        )
        seen_terms: set[str] = set()
        for term in terms:
            if term.normalized_value in seen_terms:
                raise ValueError("taxonomy terms must be unique after normalization")
            seen_terms.add(term.normalized_value)
        object.__setattr__(self, "terms", tuple(terms))
        object.__setattr__(
            self,
            "semantic_labels",
            tuple(sorted(labels, key=lambda item: (normalize_taxonomy_text(item), item))),
        )

    @property
    def keywords(self) -> tuple[str, ...]:
        return tuple(term.value for term in self.terms if "simple" in term.roles)


def validate_executable_taxonomy_locales(spec: ActionTaxonomySpec) -> None:
    """Fail closed when live player routing lacks a locale grammar policy."""
    unsupported: set[str] = set()
    for term in spec.terms:
        language, _, _ = term.locale.partition("-")
        language = language.casefold()
        subtags = term.locale.split("-")[1:]
        explicit_scripts = tuple(subtag.title() for subtag in subtags if len(subtag) == 4 and subtag.isalpha())
        explicit_script = explicit_scripts[0] if len(explicit_scripts) == 1 else None
        allowed_scripts = _SUPPORTED_EXECUTABLE_TAXONOMY_SCRIPTS.get(language)
        if (
            language not in SUPPORTED_EXECUTABLE_TAXONOMY_LANGUAGES
            or len(explicit_scripts) > 1
            or explicit_script is not None
            and allowed_scripts is not None
            and explicit_script not in allowed_scripts
            or not _taxonomy_term_uses_script(term, explicit_script or _language_script(language))
        ):
            unsupported.add(term.locale)
    if unsupported:
        raise ValueError(
            "executable action taxonomy locale has no safety grammar policy: "
            + ", ".join(sorted(unsupported, key=lambda locale: (locale.casefold(), locale)))
        )


def _language_script(language: str) -> str:
    return {"en": "Latn", "ja": "Jpan", "ko": "Kore", "zh": "Hani+Bopo"}.get(
        language,
        "",
    )


def _taxonomy_term_uses_script(term: ActionTaxonomyTerm, script: str) -> bool:
    letters = tuple(char for char in term.normalized_value if unicodedata.category(char).startswith("L"))
    if not letters:
        return script == "Latn" and not any(
            unicodedata.category(char).startswith("M") for char in term.normalized_value
        )

    def matches(char: str, *patterns: re.Pattern[str]) -> bool:
        return any(pattern.fullmatch(char) is not None for pattern in patterns)

    def is_hangul_base(char: str) -> bool:
        return matches(char, HANGUL_PATTERN) and "FILLER" not in unicodedata.name(char, "")

    def is_script_base(char: str) -> bool:
        if script == "Latn":
            return "LATIN" in unicodedata.name(char, "")
        if script in {"Hani", "Hans", "Hant"}:
            return matches(char, HAN_PATTERN)
        if script == "Bopo":
            return matches(char, BOPOMOFO_PATTERN)
        if script == "Hira":
            return matches(char, HIRAGANA_PATTERN) and char not in KANA_MODIFIER_MARKS
        if script == "Kana":
            return matches(char, KATAKANA_PATTERN) and char not in KANA_MODIFIER_MARKS
        if script == "Hang":
            return is_hangul_base(char)
        if script == "Jpan":
            return matches(char, HAN_PATTERN, HIRAGANA_PATTERN, KATAKANA_PATTERN) and char not in (
                KANA_MODIFIER_MARKS | IDEOGRAPHIC_ITERATION_MARKS
            )
        if script == "Kore":
            return matches(char, HAN_PATTERN) or is_hangul_base(char)
        if script == "Hani+Bopo":
            return matches(char, HAN_PATTERN, BOPOMOFO_PATTERN)
        return False

    def combining_modifiers_follow_script_base() -> bool:
        def is_supported_combining_block(char: str) -> bool:
            codepoint = ord(char)
            return (
                0x0300 <= codepoint <= 0x036F
                or 0x1AB0 <= codepoint <= 0x1AFF
                or 0x1DC0 <= codepoint <= 0x1DFF
                or 0x20D0 <= codepoint <= 0x20FF
                or 0xFE20 <= codepoint <= 0xFE2F
                or script in {"Hira", "Jpan", "Kana"}
                and char in {"゙", "゚"}
            )

        known_script_names = {
            "ARABIC",
            "BOPOMOFO",
            "CJK",
            "CYRILLIC",
            "GREEK",
            "HANGUL",
            "HEBREW",
            "HIRAGANA",
            "IDEOGRAPHIC",
            "KATAKANA",
            "LATIN",
        }
        allowed_script_names = {
            "Latn": {"LATIN"},
            "Hani": {"CJK", "IDEOGRAPHIC"},
            "Hans": {"CJK", "IDEOGRAPHIC"},
            "Hant": {"CJK", "IDEOGRAPHIC"},
            "Bopo": {"BOPOMOFO"},
            "Hira": {"HIRAGANA"},
            "Kana": {"KATAKANA"},
            "Hang": {"HANGUL"},
            "Jpan": {"CJK", "HIRAGANA", "IDEOGRAPHIC", "KATAKANA"},
            "Kore": {"CJK", "HANGUL", "IDEOGRAPHIC"},
            "Hani+Bopo": {"BOPOMOFO", "CJK", "IDEOGRAPHIC"},
        }.get(script, set())
        has_compatible_base = False
        for char in term.normalized_value:
            category = unicodedata.category(char)[0]
            if category == "L":
                has_compatible_base = is_script_base(char)
                continue
            if category == "M":
                name = unicodedata.name(char, "")
                named_scripts = {token for token in known_script_names if token in name}
                if (
                    not has_compatible_base
                    or not is_supported_combining_block(char)
                    or named_scripts - allowed_script_names
                ):
                    return False
                continue
            has_compatible_base = False
        return True

    def kana_modifiers_follow_base() -> bool:
        if not any(char in KANA_MODIFIER_MARKS for char in letters):
            return True
        previous: str | None = None
        for char in term.normalized_value:
            if char in {"ゝ", "ゞ"} and (
                previous is None
                or not matches(previous, HIRAGANA_PATTERN)
                or previous in KANA_MODIFIER_MARKS
            ):
                return False
            if char in {"ヽ", "ヾ"} and (
                previous is None
                or not matches(previous, KATAKANA_PATTERN)
                or previous in KANA_MODIFIER_MARKS
            ):
                return False
            if char == "ー" and (
                previous is None
                or not matches(previous, HIRAGANA_PATTERN, KATAKANA_PATTERN)
                or previous in KANA_MODIFIER_MARKS
            ):
                return False
            previous = char
        return True

    def ideographic_modifiers_follow_han_base() -> bool:
        if not any(char in IDEOGRAPHIC_ITERATION_MARKS for char in letters):
            return True
        previous: str | None = None
        for char in term.normalized_value:
            if char in IDEOGRAPHIC_ITERATION_MARKS and (
                previous is None or not matches(previous, HAN_PATTERN)
            ):
                return False
            previous = char
        return True

    def bopomofo_modifiers_follow_base() -> bool:
        previous: str | None = None
        for char in term.normalized_value:
            if char in BOPOMOFO_TONE_MARKS and (
                previous is None or not matches(previous, BOPOMOFO_PATTERN)
            ):
                return False
            previous = char
        return True

    if not combining_modifiers_follow_script_base():
        return False

    if script == "Latn":
        return all("LATIN" in unicodedata.name(char, "") for char in letters)
    if script in {"Hani", "Hans", "Hant"}:
        return ideographic_modifiers_follow_han_base() and all(
            matches(char, HAN_PATTERN) or char in IDEOGRAPHIC_ITERATION_MARKS for char in letters
        )
    if script == "Bopo":
        return (
            bopomofo_modifiers_follow_base()
            and any(matches(char, BOPOMOFO_PATTERN) for char in letters)
            and all(matches(char, BOPOMOFO_PATTERN) or char in BOPOMOFO_TONE_MARKS for char in letters)
        )
    if script == "Hira":
        return kana_modifiers_follow_base() and all(matches(char, HIRAGANA_PATTERN) or char == "ー" for char in letters)
    if script == "Kana":
        return kana_modifiers_follow_base() and all(matches(char, KATAKANA_PATTERN) for char in letters)
    if script == "Hang":
        return any(is_hangul_base(char) for char in letters) and all(is_hangul_base(char) for char in letters)
    if script == "Jpan":
        return (
            any(
                matches(char, HAN_PATTERN, HIRAGANA_PATTERN, KATAKANA_PATTERN) and char not in KANA_ITERATION_MARKS
                for char in letters
            )
            and kana_modifiers_follow_base()
            and ideographic_modifiers_follow_han_base()
            and all(
                matches(char, HAN_PATTERN, HIRAGANA_PATTERN, KATAKANA_PATTERN) or char in IDEOGRAPHIC_ITERATION_MARKS
                for char in letters
            )
        )
    if script == "Kore":
        return (
            any(matches(char, HAN_PATTERN) or is_hangul_base(char) for char in letters)
            and ideographic_modifiers_follow_han_base()
            and all(
                matches(char, HAN_PATTERN) or is_hangul_base(char) or char in IDEOGRAPHIC_ITERATION_MARKS
                for char in letters
            )
        )
    if script == "Hani+Bopo":
        return (
            bopomofo_modifiers_follow_base()
            and any(matches(char, HAN_PATTERN, BOPOMOFO_PATTERN) for char in letters)
            and ideographic_modifiers_follow_han_base()
            and all(
                matches(char, HAN_PATTERN, BOPOMOFO_PATTERN)
                or char in BOPOMOFO_TONE_MARKS
                or char in IDEOGRAPHIC_ITERATION_MARKS
                for char in letters
            )
        )
    return False


def taxonomy_terms(
    locale: str,
    values: tuple[str, ...],
    *,
    roles: tuple[str, ...] = ("simple",),
) -> tuple[ActionTaxonomyTerm, ...]:
    if type(values) is not tuple:
        raise TypeError("taxonomy term values must be an exact tuple")
    return tuple(ActionTaxonomyTerm(locale=locale, value=value, roles=roles) for value in values)


def taxonomy_term(
    locale: str,
    value: str,
    *,
    roles: tuple[str, ...] = ("simple",),
) -> ActionTaxonomyTerm:
    return ActionTaxonomyTerm(locale=locale, value=value, roles=roles)


def legacy_action_taxonomy(
    *,
    keywords: tuple[str, ...],
    semantic_labels: tuple[str, ...],
    inference_priority: int,
) -> ActionTaxonomySpec:
    if type(keywords) is not tuple:
        raise TypeError("legacy taxonomy keywords must be an exact tuple")
    if type(semantic_labels) is not tuple:
        raise TypeError("legacy taxonomy semantic labels must be an exact tuple")
    return ActionTaxonomySpec(
        terms=tuple(ActionTaxonomyTerm(locale=_legacy_term_locale(value), value=value) for value in keywords),
        semantic_labels=semantic_labels,
        inference_priority=inference_priority,
    )


def _legacy_term_locale(value: Any) -> str:
    if type(value) is not str:
        raise TypeError("legacy taxonomy keyword must be an exact string")
    if JAPANESE_PATTERN.search(value):
        return "ja"
    if HANGUL_PATTERN.search(value):
        return "ko"
    if BOPOMOFO_PATTERN.search(value) and HAN_PATTERN.search(value):
        return "zh"
    if BOPOMOFO_PATTERN.search(value):
        return "zh-Bopo"
    if HAN_PATTERN.search(value):
        return "zh-Hans"
    if value.isascii():
        return "en"
    return "und"


def build_action_taxonomy_projection(
    entries: Iterable[tuple[str, ActionTaxonomySpec]],
    *,
    version: str = ACTION_TAXONOMY_VERSION,
) -> dict[str, Any]:
    version = _validate_exact_text(
        version,
        label="taxonomy version",
        max_length=MAX_ACTION_TAXONOMY_VERSION_LENGTH,
    )
    collected = list(islice(entries, MAX_ACTION_TAXONOMY_ACTIONS + 1))
    if len(collected) > MAX_ACTION_TAXONOMY_ACTIONS:
        raise ValueError("taxonomy registry has too many actions")
    actions: list[dict[str, Any]] = []
    term_owners: dict[str, str] = {}
    action_names: set[str] = set()
    for name, spec in sorted(collected, key=lambda item: item[0]):
        action_name = _validate_exact_text(name, label="taxonomy action name", max_length=64)
        if action_name != action_name.lower():
            raise ValueError("taxonomy action name must use canonical lowercase")
        if not ROLE_PATTERN.fullmatch(action_name):
            raise ValueError("taxonomy action name must be a lowercase ASCII identifier")
        if action_name in RESERVED_ACTION_NAMES:
            raise ValueError("taxonomy action name is reserved by the intent candidate contract")
        if action_name in action_names:
            raise ValueError(f"Duplicate action taxonomy: {action_name}")
        action_names.add(action_name)
        if type(spec) is not ActionTaxonomySpec:
            raise TypeError("taxonomy registry entries must use exact ActionTaxonomySpec values")
        for term in spec.terms:
            owner = term_owners.get(term.normalized_value)
            if owner is not None and owner != action_name:
                raise ValueError(
                    "action taxonomy collision after normalization: "
                    f"{term.value!r} belongs to both {owner!r} and {action_name!r}"
                )
            term_owners[term.normalized_value] = action_name
        actions.append(
            {
                "name": action_name,
                "inference_priority": spec.inference_priority,
                "semantic_labels": spec.semantic_labels,
                "terms": tuple(term.to_projection() for term in spec.terms),
            }
        )
    payload: dict[str, Any] = {
        "version": version,
        "normalization": dict(TAXONOMY_NORMALIZATION),
        "actions": tuple(actions),
    }
    return {
        "version": version,
        "digest": canonical_json_sha256(payload),
        "normalization": dict(TAXONOMY_NORMALIZATION),
        "actions": tuple(actions),
    }


def _compile_taxonomy_match_pattern(value: str) -> re.Pattern[str]:
    return re.compile(re.escape(value))


def _is_taxonomy_word_character(value: str) -> bool:
    return value == "_" or unicodedata.category(value)[0] in {"L", "M", "N"}


def _taxonomy_boundary_base(value: str, *, reverse: bool) -> str:
    characters = reversed(value) if reverse else iter(value)
    for character in characters:
        if (
            _is_taxonomy_word_character(character)
            and unicodedata.category(character)[0] != "M"
            and character not in BOPOMOFO_TONE_MARKS
        ):
            return character
    return value[-1] if reverse else value[0]


def taxonomy_term_match_spans_normalized(
    normalized_text: str,
    term: ActionTaxonomyTerm,
) -> Iterable[tuple[int, int]]:
    prefix_base = _taxonomy_boundary_base(term.normalized_value, reverse=False)
    suffix_base = _taxonomy_boundary_base(term.normalized_value, reverse=True)
    needs_prefix_boundary = (
        _is_taxonomy_word_character(prefix_base) and CJK_PATTERN.fullmatch(prefix_base) is None
    )
    needs_suffix_boundary = (
        _is_taxonomy_word_character(suffix_base) and CJK_PATTERN.fullmatch(suffix_base) is None
    )
    for match in term._match_pattern.finditer(normalized_text):
        if (
            needs_prefix_boundary
            and match.start() > 0
            and _is_taxonomy_word_character(normalized_text[match.start() - 1])
        ):
            continue
        if (
            needs_suffix_boundary
            and match.end() < len(normalized_text)
            and _is_taxonomy_word_character(normalized_text[match.end()])
        ):
            continue
        yield match.start(), match.end()


def taxonomy_term_matches_normalized(normalized_text: str, term: ActionTaxonomyTerm) -> bool:
    return next(taxonomy_term_match_spans_normalized(normalized_text, term), None) is not None


def taxonomy_term_matches(text: str, term: ActionTaxonomyTerm) -> bool:
    return taxonomy_term_matches_normalized(normalize_taxonomy_text(str(text)), term)
