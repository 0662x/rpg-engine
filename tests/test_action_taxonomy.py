from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from rpg_engine.actions import (
    ACTION_TAXONOMY_VERSION,
    MAX_ACTION_TAXONOMY_ACTIONS,
    MAX_ACTION_TAXONOMY_LOCALE_LENGTH,
    MAX_ACTION_TAXONOMY_ROLES_PER_TERM,
    MAX_ACTION_TAXONOMY_ROLE_LENGTH,
    MAX_ACTION_TAXONOMY_TERM_LENGTH,
    MAX_ACTION_TAXONOMY_TERMS_PER_ACTION,
    MAX_ACTION_TAXONOMY_VERSION_LENGTH,
    SUPPORTED_EXECUTABLE_TAXONOMY_LANGUAGES,
    ActionResolverRegistry,
    ActionResolverSpec,
    ActionTaxonomySpec,
    ActionTaxonomyTerm,
    get_default_action_registry,
    taxonomy_terms,
)
from rpg_engine.actions.registry import render_action_resolver_detail, render_action_resolver_list
from rpg_engine.actions.routine import routine_template
from rpg_engine.actions.taxonomy import (
    TAXONOMY_NORMALIZATION,
    build_action_taxonomy_projection,
    normalize_taxonomy_text,
    taxonomy_term_matches,
)
from rpg_engine.ai_intent.external import validate_external_intent_candidate
from rpg_engine.ai_intent.normalization import normalize_intent_candidate
from rpg_engine.ai_intent.prompts import build_internal_intent_review_prompt
from rpg_engine.ai_intent.safety_contract import ExternalIntentContractError
from rpg_engine.context.validation import validate_context
from rpg_engine.context.semantic import build_semantic_prompt, normalize_semantic_suggestion
from rpg_engine.intent_manifest import build_intent_manifest
from rpg_engine import intent_router
from rpg_engine.intent_router import (
    ActionIntent,
    TurnContract,
    action_keywords,
    detect_preview_action_mismatch,
    infer_action_from_registry,
    infer_mode,
    inferred_actions_not_in_registry,
    infer_submode,
    keyword_expected_action,
    looks_like_noise_text,
)
from rpg_engine.response_lint import lint_response


def preview_stub(*_args: object, **_kwargs: object) -> str:
    return ""


def taxonomy_spec(
    action: str,
    *,
    terms: tuple[ActionTaxonomyTerm, ...],
    priority: int = 50,
) -> ActionResolverSpec:
    return ActionResolverSpec(
        name=action,
        preview=preview_stub,
        response_template="action.md",
        taxonomy=ActionTaxonomySpec(
            terms=terms,
            semantic_labels=(action,),
            inference_priority=priority,
        ),
    )


def registry_with_survey(
    term: str = "survey",
    *,
    locale: str = "en",
    priority: int = 15,
    taxonomy_version: str = ACTION_TAXONOMY_VERSION,
) -> ActionResolverRegistry:
    registry = ActionResolverRegistry(taxonomy_version=taxonomy_version)
    for spec in get_default_action_registry().all():
        registry.register(spec)
    registry.register(
        taxonomy_spec(
            "survey",
            terms=(
                *taxonomy_terms(locale, (term,)),
                *taxonomy_terms("zh-Hans", ("勘测",)),
            ),
            priority=priority,
        )
    )
    return registry


def candidate_contract(manifest: dict[str, object]) -> dict[str, str]:
    safety = manifest["safety_vocabulary"]
    assert isinstance(safety, dict)
    return {
        "manifest_schema_version": str(manifest["schema_version"]),
        "manifest_digest": str(manifest["manifest_digest"]),
        "safety_vocabulary_version": str(safety["version"]),
        "safety_vocabulary_digest": str(safety["digest"]),
    }


class ActionTaxonomyTests(unittest.TestCase):
    def test_public_limits_and_version_are_bounded_contract_constants(self) -> None:
        self.assertEqual(ACTION_TAXONOMY_VERSION, "1")
        self.assertEqual(MAX_ACTION_TAXONOMY_VERSION_LENGTH, 32)
        self.assertEqual(MAX_ACTION_TAXONOMY_LOCALE_LENGTH, 35)
        self.assertEqual(MAX_ACTION_TAXONOMY_TERM_LENGTH, 128)
        self.assertEqual(MAX_ACTION_TAXONOMY_TERMS_PER_ACTION, 256)
        self.assertEqual(MAX_ACTION_TAXONOMY_ACTIONS, 128)
        self.assertEqual(MAX_ACTION_TAXONOMY_ROLE_LENGTH, 64)
        self.assertEqual(MAX_ACTION_TAXONOMY_ROLES_PER_TERM, 16)
        self.assertEqual(SUPPORTED_EXECUTABLE_TAXONOMY_LANGUAGES, {"en", "ja", "ko", "zh"})

    def test_public_validation_bounds_accept_maxima_and_reject_overflow_or_coercion(self) -> None:
        max_locale = "abcdefgh-12345678-12345678-12345678"
        self.assertEqual(len(max_locale), MAX_ACTION_TAXONOMY_LOCALE_LENGTH)
        max_term = "x" * MAX_ACTION_TAXONOMY_TERM_LENGTH
        max_role = "r" + "x" * (MAX_ACTION_TAXONOMY_ROLE_LENGTH - 1)
        max_roles = tuple(f"r{index}" for index in range(MAX_ACTION_TAXONOMY_ROLES_PER_TERM))

        ActionTaxonomyTerm(locale=max_locale, value=max_term, roles=(max_role,))
        ActionTaxonomyTerm(locale="en", value="bounded", roles=max_roles)
        self.assertEqual(
            build_action_taxonomy_projection((), version="v" * MAX_ACTION_TAXONOMY_VERSION_LENGTH)["version"],
            "v" * MAX_ACTION_TAXONOMY_VERSION_LENGTH,
        )
        max_terms = tuple(
            ActionTaxonomyTerm(locale="en", value=f"term-{index}")
            for index in range(MAX_ACTION_TAXONOMY_TERMS_PER_ACTION)
        )
        self.assertEqual(len(ActionTaxonomySpec(terms=max_terms).terms), MAX_ACTION_TAXONOMY_TERMS_PER_ACTION)

        invalid_term_inputs = (
            {"locale": max_locale + "x", "value": "term"},
            {"locale": "en", "value": "x" * (MAX_ACTION_TAXONOMY_TERM_LENGTH + 1)},
            {"locale": "en", "value": ""},
            {"locale": "und", "value": "!"},
            {"locale": "und", "value": "🧭"},
            {"locale": " en", "value": "term"},
            {"locale": 1, "value": "term"},
            {"locale": "en", "value": True},
            {"locale": "en", "value": "term", "roles": ()},
            {"locale": "en", "value": "term", "roles": ("",)},
            {"locale": "en", "value": "term", "roles": ("bad\nrole",)},
            {"locale": "en", "value": "term", "roles": (1,)},
        )
        for kwargs in invalid_term_inputs:
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                ActionTaxonomyTerm(**kwargs)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            build_action_taxonomy_projection((), version="v" * (MAX_ACTION_TAXONOMY_VERSION_LENGTH + 1))
        with self.assertRaises(ValueError):
            build_action_taxonomy_projection((), version="")
        with self.assertRaises(ValueError):
            build_action_taxonomy_projection((), version="v\n1")
        with self.assertRaises(TypeError):
            build_action_taxonomy_projection((), version=1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ActionTaxonomySpec(
                terms=(*max_terms, ActionTaxonomyTerm(locale="en", value="overflow")),
            )

        registry = ActionResolverRegistry()
        for index in range(MAX_ACTION_TAXONOMY_ACTIONS):
            registry.register(
                taxonomy_spec(
                    f"action_{index}",
                    terms=taxonomy_terms("en", (f"action-term-{index}",)),
                )
            )
        before = registry.taxonomy_projection()
        with self.assertRaises(ValueError):
            registry.register(taxonomy_spec("overflow", terms=taxonomy_terms("en", ("overflow-term",))))
        self.assertEqual(registry.taxonomy_projection(), before)

    def test_live_registry_rejects_locales_without_safety_grammar_policy(self) -> None:
        metadata_projection = build_action_taxonomy_projection(
            (
                (
                    "survey",
                    ActionTaxonomySpec(terms=taxonomy_terms("fr", ("patrouiller",))),
                ),
            )
        )
        self.assertEqual(metadata_projection["actions"][0]["terms"][0]["locale"], "fr")

        registry = ActionResolverRegistry()
        registry.register(
            taxonomy_spec(
                "rest",
                terms=taxonomy_terms("en", ("rest",)),
            )
        )
        with self.assertRaisesRegex(ValueError, "no safety grammar policy: fr"):
            registry.register(
                taxonomy_spec(
                    "survey",
                    terms=taxonomy_terms("fr", ("patrouiller",)),
                )
            )
        self.assertEqual(registry.names(), ["rest"])

        unsupported_locale_terms = (
            ("ja-Latn", "patorooru"),
            ("zh-Latn", "xunluo"),
            ("ko-Latn", "suncal"),
            ("zh", "xunluo"),
            ("zh-Hans", "ㄓㄨˋ"),
            ("ja-Hira", "パトロール"),
            ("ja-Kana", "巡"),
            ("ko-Hang", "巡"),
            ("zh-Hans-Latn", "巡视"),
            ("ja-Hira", "ゝ"),
            ("ja-Kana", "ヽ"),
            ("ja", "ゝ"),
            ("ja-Hira", "ゝあ"),
            ("ja-Kana", "ヽカ"),
            ("ja", "ゝ巡"),
            ("ja-Kana", "ー"),
            ("ko-Hang", "ㅤ"),
            ("ko", "ᅟ"),
            ("zh-Hans", "々巡"),
            ("ja-Hani", "々巡"),
            ("ko-Hani", "々察"),
            ("ko-Hang", "순ㅤ"),
            ("ja", "あ漢ゝ"),
            ("ja", "時あ々"),
            ("ja", "あ-ゝ"),
            ("ja", "時-々"),
            ("en", "s҈urvey"),
            ("en", "sाurvey"),
            ("en", "sัurvey"),
            ("en", "1ा"),
            ("en", "1ั"),
            ("zh-Bopo", "ˋㄅ"),
            ("zh-Bopo", "ㄅ-ˋ"),
        )
        for locale, term in unsupported_locale_terms:
            with (
                self.subTest(locale=locale),
                self.assertRaisesRegex(
                    ValueError,
                    f"no safety grammar policy: {locale}",
                ),
            ):
                registry.register(
                    taxonomy_spec(
                        "survey",
                        terms=taxonomy_terms(locale, (term,)),
                    )
                )
            self.assertEqual(registry.names(), ["rest"])

        registry.register(
            taxonomy_spec(
                "survey",
                terms=(
                    *taxonomy_terms("en-AU", ("patrol",)),
                    *taxonomy_terms("ja-Hira", ("ひら",)),
                    *taxonomy_terms("ja-Hira", ("くゝ",)),
                    *taxonomy_terms("ja-Kana", ("カナ",)),
                    *taxonomy_terms("ja-Kana", ("カヽ",)),
                    *taxonomy_terms("ja-Hani", ("巡",)),
                    *taxonomy_terms("ja", ("時々",)),
                    *taxonomy_terms("ko-Hang", ("순",)),
                    *taxonomy_terms("ko-Hani", ("察",)),
                    *taxonomy_terms("zh-Bopo", ("ㄓㄨ",)),
                    *taxonomy_terms("zh-Bopo", ("ㄅㄆˋ",)),
                    *taxonomy_terms("zh", ("ㄆㄇˋ",)),
                    *taxonomy_terms("zh-Hans", ("巡́",)),
                ),
            )
        )
        self.assertEqual(registry.match_action("patrol the walls"), "survey")

        registry.register(
            ActionResolverSpec(
                name="legacy_survey",
                preview=preview_stub,
                response_template="action.md",
                keywords=("ㄈㄉˋ",),
            )
        )
        legacy_spec = registry.get("legacy_survey")
        assert legacy_spec is not None
        self.assertEqual(legacy_spec.taxonomy.terms[0].locale, "zh-Bopo")

        registry.register(
            ActionResolverSpec(
                name="legacy_mixed_survey",
                preview=preview_stub,
                response_template="action.md",
                keywords=("注ㄓㄨˋ",),
            )
        )
        legacy_mixed_spec = registry.get("legacy_mixed_survey")
        assert legacy_mixed_spec is not None
        self.assertEqual(legacy_mixed_spec.taxonomy.terms[0].locale, "zh")

    def test_projection_bounds_generator_consumption_and_rejects_reserved_action_names(self) -> None:
        consumed = 0

        def oversized_entries():
            nonlocal consumed
            for index in range(MAX_ACTION_TAXONOMY_ACTIONS + 10):
                consumed += 1
                yield f"action_{index}", ActionTaxonomySpec()

        with self.assertRaisesRegex(ValueError, "too many actions"):
            build_action_taxonomy_projection(oversized_entries())
        self.assertEqual(consumed, MAX_ACTION_TAXONOMY_ACTIONS + 1)

        for reserved in ("act", "none", "null", "unknown"):
            with self.subTest(reserved=reserved), self.assertRaisesRegex(ValueError, "reserved"):
                build_action_taxonomy_projection(((reserved, ActionTaxonomySpec()),))

    def test_normalization_metadata_is_immutable(self) -> None:
        with self.assertRaises(TypeError):
            TAXONOMY_NORMALIZATION["case"] = "lower"  # type: ignore[index]

    def test_taxonomy_is_frozen_and_legacy_fields_are_derived(self) -> None:
        spec = ActionResolverSpec(
            name="custom",
            preview=preview_stub,
            response_template="action.md",
            keywords=("巡视", "patrol"),
            semantic_labels=("patrol",),
            inference_priority=17,
        )

        self.assertEqual(spec.keywords, ("patrol", "巡视"))
        self.assertEqual(spec.semantic_labels, ("patrol",))
        self.assertEqual(spec.inference_priority, 17)
        self.assertIsInstance(spec.taxonomy, ActionTaxonomySpec)
        with self.assertRaises(FrozenInstanceError):
            spec.taxonomy.inference_priority = 99  # type: ignore[misc]

    def test_canonical_and_legacy_taxonomy_inputs_are_mutually_exclusive(self) -> None:
        taxonomy = ActionTaxonomySpec(
            terms=taxonomy_terms("en", ("patrol",)),
            semantic_labels=("patrol",),
            inference_priority=10,
        )

        with self.assertRaisesRegex(ValueError, "legacy taxonomy"):
            ActionResolverSpec(
                name="custom",
                preview=preview_stub,
                response_template="action.md",
                taxonomy=taxonomy,
                keywords=("patrol",),
            )
        with self.assertRaisesRegex(ValueError, "legacy taxonomy"):
            ActionResolverSpec(
                name="custom",
                preview=preview_stub,
                response_template="action.md",
                taxonomy=None,
                keywords=("patrol",),
            )
        with self.assertRaisesRegex(TypeError, "exact ActionTaxonomySpec"):
            ActionResolverSpec(
                name="custom",
                preview=preview_stub,
                response_template="action.md",
                taxonomy=None,
            )

    def test_term_and_spec_validation_rejects_unsafe_or_coerced_values(self) -> None:
        invalid_terms = (
            {"locale": "e", "value": "patrol"},
            {"locale": "en_au", "value": "patrol"},
            {"locale": "en", "value": " patrol"},
            {"locale": "en", "value": "patrol\nnow"},
            {"locale": "en", "value": "x" * (MAX_ACTION_TAXONOMY_TERM_LENGTH + 1)},
            {"locale": "en", "value": 1},
            {"locale": "en", "value": "patrol", "roles": ["simple"]},
            {"locale": "en", "value": "patrol", "roles": ("x" * 65,)},
            {"locale": "en", "value": "patrol", "roles": tuple(f"r{i}" for i in range(17))},
        )
        for kwargs in invalid_terms:
            with self.subTest(kwargs=kwargs), self.assertRaises((TypeError, ValueError)):
                ActionTaxonomyTerm(**kwargs)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            ActionTaxonomySpec(terms=[], semantic_labels=(), inference_priority=1)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            ActionTaxonomySpec(terms=(), semantic_labels=(), inference_priority=True)  # type: ignore[arg-type]

    def test_registry_matches_nfkc_casefold_latin_boundaries_and_cjk_substrings(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(
            taxonomy_spec(
                "routine",
                terms=(
                    *taxonomy_terms("en", ("patrol", "rest")),
                    *taxonomy_terms("zh-Hans", ("巡视",)),
                ),
                priority=20,
            )
        )

        self.assertEqual(registry.match_action("PATROL the walls"), "routine")
        self.assertEqual(registry.match_action("开始巡视领地"), "routine")
        self.assertEqual(registry.match_action("ＰＡＴＲＯＬ the walls"), "routine")
        self.assertIsNone(registry.match_action("walk through the forest"))

    def test_term_matching_handles_unicode_word_and_punctuation_boundaries(self) -> None:
        cases = (
            ("roll!", "roll!", "en", True),
            ("xroll!", "roll!", "en", False),
            ("#go", "#go", "en", True),
            ("#going", "#go", "en", False),
            ("x#go", "#go", "en", False),
            ("#go x", "#go", "en", True),
            ("C++", "C++", "en", True),
            ("é", "é", "fr", True),
            ("résumé", "é", "fr", False),
            ("rest\u0301ful day", "rest", "en", False),
            ("İLERİDE", "İLERİ", "tr", False),
            ("forest巡", "rest巡", "en", False),
            ("rest巡回", "rest巡", "en", True),
            ("togo巡逻", "go巡逻", "en", False),
        )
        for text, value, locale, expected in cases:
            with self.subTest(text=text, value=value):
                self.assertEqual(
                    taxonomy_term_matches(text, ActionTaxonomyTerm(locale=locale, value=value)),
                    expected,
                )

    def test_japanese_and_korean_terms_use_the_same_substring_contract(self) -> None:
        cases = (
            ("城をパトロールする", "パトロール", "ja"),
            ("もうねる時間", "ねる", "ja"),
            ("성을 순찰한다", "순찰", "ko"),
            ("甲𠀀乙", "𠀀", "zh-Hant"),
            ("ᄀꥠᄂ", "ꥠ", "ko"),
            ("ㄅㄆ", "ㄅ", "zh-Hant"),
            ("ㆠㆡ", "ㆠ", "zh-Hant"),
            ("請ㄓㄨˋ意", "ㄓㄨˋ", "zh-Hant"),
            ("我巡́逻", "巡́", "zh-Hans"),
            ("あ𛀀い", "𛀀", "ja"),
            ("あ𛄀い", "𛄀", "ja"),
        )
        for text, value, locale in cases:
            with self.subTest(locale=locale, value=value):
                self.assertTrue(taxonomy_term_matches(text, ActionTaxonomyTerm(locale=locale, value=value)))

        registry = ActionResolverRegistry()
        registry.register(
            taxonomy_spec(
                "survey",
                terms=(
                    *taxonomy_terms("ja", ("パトロール",)),
                    *taxonomy_terms("ko", ("순찰",)),
                ),
            )
        )
        self.assertEqual(registry.match_action("城をパトロールする"), "survey")
        self.assertEqual(registry.match_action("성을 순찰한다"), "survey")
        self.assertFalse(looks_like_noise_text("城をパトロールする"))
        self.assertFalse(looks_like_noise_text("성을 순찰한다"))
        projection = registry.taxonomy_projection()
        self.assertEqual(
            {term["locale"] for term in projection["actions"][0]["terms"]},
            {"ja", "ko"},
        )

    def test_registry_normalizes_player_text_once_per_match_operation(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(
            taxonomy_spec(
                "custom",
                terms=tuple(ActionTaxonomyTerm(locale="en", value=f"term-{index}") for index in range(128)),
            )
        )

        with mock.patch(
            "rpg_engine.actions.base.normalize_taxonomy_text",
            wraps=normalize_taxonomy_text,
        ) as normalize:
            self.assertIsNone(registry.match_action("no matching taxonomy term"))

        self.assertEqual(normalize.call_count, 1)

    def test_register_is_atomic_and_rejects_normalized_cross_action_collision(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(taxonomy_spec("routine", terms=taxonomy_terms("en", ("patrol",))))
        before_names = registry.names()
        before_projection = registry.taxonomy_projection()

        with self.assertRaisesRegex(ValueError, "collision"):
            registry.register(taxonomy_spec("explore", terms=taxonomy_terms("en", ("ＰＡＴＲＯＬ",))))

        self.assertEqual(registry.names(), before_names)
        self.assertEqual(registry.taxonomy_projection(), before_projection)

    def test_registry_requires_lowercase_action_names_and_accepts_resolver_subclasses(self) -> None:
        registry = ActionResolverRegistry()
        with self.assertRaisesRegex(ValueError, "lowercase"):
            registry.register(taxonomy_spec("Survey", terms=taxonomy_terms("en", ("survey",))))
        self.assertEqual(registry.names(), [])
        for invalid_name in ("ｎｏｎｅ", "ｓｕｒｖｅｙ", "bad name", "1survey"):
            with self.subTest(name=invalid_name), self.assertRaisesRegex(ValueError, "identifier"):
                registry.register(taxonomy_spec(invalid_name, terms=taxonomy_terms("en", (f"term-{invalid_name}",))))
        self.assertEqual(registry.names(), [])

        class DerivedActionResolverSpec(ActionResolverSpec):
            pass

        derived = DerivedActionResolverSpec(
            name="survey",
            preview=preview_stub,
            response_template="action.md",
            taxonomy=ActionTaxonomySpec(
                terms=taxonomy_terms("en", ("survey",)),
                semantic_labels=("survey",),
                inference_priority=10,
            ),
        )
        registry.register(derived)
        self.assertEqual(registry.names(), ["survey"])

    def test_projection_is_defensive_and_registration_order_independent(self) -> None:
        first = taxonomy_spec("routine", terms=taxonomy_terms("zh-Hans", ("巡视",)), priority=20)
        second = taxonomy_spec("craft", terms=taxonomy_terms("en", ("craft",)), priority=10)
        registry_a = ActionResolverRegistry()
        registry_b = ActionResolverRegistry()
        for spec in (first, second):
            registry_a.register(spec)
        for spec in (second, first):
            registry_b.register(spec)

        projection = registry_a.taxonomy_projection()
        projection["version"] = "changed"
        projection["actions"][0]["terms"][0]["value"] = "changed"

        self.assertEqual(registry_a.taxonomy_projection(), registry_b.taxonomy_projection())
        self.assertEqual(registry_a.taxonomy_projection()["version"], ACTION_TAXONOMY_VERSION)
        self.assertRegex(registry_a.taxonomy_digest, r"^[0-9a-f]{64}$")

    def test_projection_and_digest_are_stable_across_hash_seeds(self) -> None:
        script = (
            "import json; "
            "from rpg_engine.actions import get_default_action_registry; "
            "r=get_default_action_registry(); "
            "print(json.dumps(r.taxonomy_projection(), ensure_ascii=False, sort_keys=True, separators=(',', ':')))"
        )
        outputs: list[str] = []
        for seed in ("1", "8675309"):
            env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=os.fspath(os.path.dirname(os.path.dirname(__file__))),
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            outputs.append(result.stdout.strip())

        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(json.loads(outputs[0])["version"], ACTION_TAXONOMY_VERSION)

    def test_legal_overlap_uses_priority_then_stable_action_name(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(taxonomy_spec("alpha", terms=taxonomy_terms("en", ("look",)), priority=20))
        registry.register(taxonomy_spec("beta", terms=taxonomy_terms("en", ("look around",)), priority=10))
        self.assertEqual(registry.match_action("look around the room"), "beta")

        equal_priority = ActionResolverRegistry()
        equal_priority.register(taxonomy_spec("alpha", terms=taxonomy_terms("en", ("look",)), priority=10))
        equal_priority.register(taxonomy_spec("beta", terms=taxonomy_terms("en", ("look around",)), priority=10))
        self.assertEqual(equal_priority.match_action("look around the room"), "alpha")

    def test_term_locale_priority_and_version_changes_rotate_taxonomy_and_manifest_digests(self) -> None:
        baseline_registry = registry_with_survey()
        baseline_manifest = build_intent_manifest(registry=baseline_registry)
        variants = (
            registry_with_survey("reconnoitre"),
            registry_with_survey(locale="en-AU"),
            registry_with_survey(priority=16),
        )
        for registry in variants:
            with self.subTest(taxonomy=registry.taxonomy_projection()):
                self.assertNotEqual(registry.taxonomy_digest, baseline_registry.taxonomy_digest)
                self.assertNotEqual(
                    build_intent_manifest(registry=registry)["manifest_digest"],
                    baseline_manifest["manifest_digest"],
                )

        version_two_registry = registry_with_survey(taxonomy_version="2")
        version_two_manifest = build_intent_manifest(registry=version_two_registry)
        self.assertEqual(version_two_registry.taxonomy_version, "2")
        self.assertNotEqual(version_two_registry.taxonomy_digest, baseline_registry.taxonomy_digest)
        self.assertNotEqual(version_two_manifest["manifest_digest"], baseline_manifest["manifest_digest"])

        stale_payload = {
            "contract": candidate_contract(baseline_manifest),
            "kind": "single",
            "mode": "action",
            "action": "survey",
            "slots": {},
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [],
            "reason": "old taxonomy version",
        }
        with self.assertRaises(ExternalIntentContractError) as raised:
            validate_external_intent_candidate(stale_payload, registry=version_two_registry)
        self.assertEqual(raised.exception.reason, "contract_version_mismatch")

    def test_builtin_taxonomy_contains_all_actions_locales_and_required_terms(self) -> None:
        registry = get_default_action_registry()
        projection = registry.taxonomy_projection()
        actions = {entry["name"]: entry for entry in projection["actions"]}

        self.assertEqual(
            tuple(actions),
            ("combat", "craft", "explore", "gather", "random_table", "rest", "routine", "social", "travel"),
        )
        expected_matches = {
            "attack": "combat",
            "craft": "craft",
            "inspect": "explore",
            "harvest": "gather",
            "roll": "random_table",
            "sleep": "rest",
            "巡视": "routine",
            "巡逻": "routine",
            "ask": "social",
            "travel": "travel",
        }
        for term, action in expected_matches.items():
            with self.subTest(term=term):
                self.assertEqual(registry.match_action(term), action)

        routine_terms = {term["value"]: term for term in actions["routine"]["terms"]}
        self.assertIn("inventory", routine_terms)
        self.assertIn("inventory", routine_terms["inventory"]["roles"])
        self.assertIn("inventory", routine_terms["盘点"]["roles"])
        self.assertEqual(routine_terms["巡视"]["locale"], "zh-Hans")
        self.assertEqual(routine_terms["patrol"]["locale"], "en")
        self.assertEqual(
            routine_template(SimpleNamespace(task="库存", target=None, focus=None, user_text=None)).id,
            "routine:inventory-audit",
        )
        self.assertEqual(
            routine_template(SimpleNamespace(task="物资", target=None, focus=None, user_text=None)).id,
            "routine:inventory-audit",
        )

    def test_patrol_terms_have_manifest_and_internal_prompt_parity(self) -> None:
        manifest = build_intent_manifest()
        routine = next(action for action in manifest["action_taxonomy"]["actions"] if action["name"] == "routine")
        values = {term["value"] for term in routine["terms"]}
        self.assertTrue({"巡视", "巡逻"}.issubset(values))

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("create table meta (key text primary key, value text not null)")
        conn.execute("insert into meta(key, value) values ('current_location_id', 'loc:test')")
        try:
            prompt = build_internal_intent_review_prompt(conn, "巡逻领地")
        finally:
            conn.close()
        self.assertIn('"value": "巡视"', prompt)
        self.assertIn('"value": "巡逻"', prompt)

    def test_builtin_compatibility_fields_are_derived_from_taxonomy(self) -> None:
        registry = get_default_action_registry()
        routine = registry.get("routine")
        self.assertIsNotNone(routine)
        assert routine is not None

        self.assertEqual(routine.keywords, routine.taxonomy.keywords)
        self.assertIn("巡视", routine.keywords)
        self.assertIn("patrol", routine.keywords)
        self.assertEqual(routine.semantic_labels, routine.taxonomy.semantic_labels)
        self.assertEqual(routine.inference_priority, routine.taxonomy.inference_priority)

    def test_registry_introspection_publishes_taxonomy_identity_and_terms(self) -> None:
        listing = render_action_resolver_list()
        detail, ok = render_action_resolver_detail("routine")

        self.assertTrue(ok)
        self.assertIn("taxonomy_version: `1`", listing)
        self.assertIn("taxonomy_digest:", listing)
        self.assertIn("taxonomy_version: `1`", detail)
        self.assertIn("巡视", detail)
        self.assertIn("inventory", detail)

    def test_router_simple_lexical_helpers_consume_one_registry_projection(self) -> None:
        registry = get_default_action_registry()

        self.assertEqual(infer_action_from_registry("巡视领地", registry=registry), "routine")
        self.assertEqual(infer_action_from_registry("CRAFT a shelter", registry=registry), "craft")
        self.assertEqual(infer_submode("PATROL the walls", registry=registry), "routine")
        self.assertEqual(infer_mode("PATROL the walls", "routine", registry=registry), "action")
        self.assertEqual(keyword_expected_action("巡逻领地", registry=registry), "routine")
        self.assertEqual(
            tuple(action_keywords(registry=registry)),
            registry.terms_for(role="simple"),
        )

    def test_low_level_mismatch_guard_uses_its_canonical_role_without_context_terms(self) -> None:
        registry = get_default_action_registry()

        self.assertIsNone(detect_preview_action_mismatch("找草药", "gather", registry=registry))
        self.assertIsNone(detect_preview_action_mismatch("检查线索", "explore", registry=registry))
        self.assertIsNone(detect_preview_action_mismatch("patrol the walls", "routine", registry=registry))
        self.assertEqual(keyword_expected_action("巡逻领地", registry=registry), "routine")
        mismatch = detect_preview_action_mismatch("问 Traveler", "gather", registry=registry)
        self.assertIsNotNone(mismatch)
        assert mismatch is not None
        self.assertEqual(mismatch["expected_action"], "social")

        custom_registry = ActionResolverRegistry()
        custom_registry.register(
            taxonomy_spec(
                "survey",
                terms=taxonomy_terms(
                    "en",
                    ("survey",),
                    roles=("preview.mismatch", "simple"),
                ),
            )
        )
        self.assertEqual(
            keyword_expected_action("survey the walls", registry=custom_registry),
            "survey",
        )
        custom_mismatch = detect_preview_action_mismatch(
            "survey the walls",
            "routine",
            registry=custom_registry,
        )
        self.assertIsNotNone(custom_mismatch)
        assert custom_mismatch is not None
        self.assertEqual(custom_mismatch["expected_action"], "survey")

        overlap_registry = ActionResolverRegistry()
        for spec in registry.all():
            overlap_registry.register(spec)
        overlap_registry.register(
            taxonomy_spec(
                "survey",
                terms=taxonomy_terms(
                    "en",
                    ("fix bridge",),
                    roles=("preview.mismatch", "simple"),
                ),
                priority=1,
            )
        )
        self.assertEqual(infer_action_from_registry("fix bridge", registry=overlap_registry), "survey")
        self.assertEqual(keyword_expected_action("fix bridge", registry=overlap_registry), "survey")
        self.assertEqual(keyword_expected_action("去问情况", registry=overlap_registry), "travel")

        isolated_registry = ActionResolverRegistry()
        isolated_registry.register(taxonomy_spec("travel", terms=taxonomy_terms("en", ("voyage",))))
        isolated_registry.register(taxonomy_spec("social", terms=taxonomy_terms("en", ("parley",))))
        self.assertIsNone(detect_preview_action_mismatch("去问情况", "social", registry=isolated_registry))
        default_composite = detect_preview_action_mismatch("到营地找人", "social", registry=registry)
        self.assertIsNotNone(default_composite)
        assert default_composite is not None
        self.assertEqual(default_composite["expected_action"], "composite")

    def test_explicit_empty_action_selector_matches_nothing(self) -> None:
        registry = get_default_action_registry()

        self.assertEqual(registry.terms_for(action=""), ())
        self.assertFalse(registry.text_has_term("巡视领地", action=""))

    def test_falsey_injected_registry_never_falls_back_to_default_contract(self) -> None:
        class FalseyRegistry(ActionResolverRegistry):
            def __bool__(self) -> bool:
                return False

        registry = FalseyRegistry()
        registry.register(
            ActionResolverSpec(
                name="survey",
                preview=preview_stub,
                response_template="action.md",
                required_options=("target",),
                taxonomy=ActionTaxonomySpec(
                    terms=taxonomy_terms("en", ("survey",)),
                    semantic_labels=("survey",),
                ),
            )
        )

        manifest = build_intent_manifest(registry=registry)
        self.assertEqual([action["name"] for action in manifest["actions"]], ["survey"])
        self.assertEqual(infer_action_from_registry("survey the walls", registry=registry), "survey")
        self.assertIsNone(infer_action_from_registry("patrol the walls", registry=registry))
        normalized = normalize_intent_candidate(
            {"kind": "single", "mode": "action", "action": "survey"},
            registry=registry,
        )
        self.assertEqual(normalized.action, "survey")

        state = SimpleNamespace(
            mode="action",
            submode="survey",
            entity_hits=(),
            user_text="survey",
            action_registry=registry,
            missing_required=[],
        )
        validate_context(state)
        self.assertEqual(state.missing_required, ["行动目标未明确。"])

    def test_response_lint_resolves_custom_template_from_injected_registry(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(taxonomy_spec("survey", terms=taxonomy_terms("en", ("survey",))))
        contract = TurnContract(
            intent=ActionIntent(
                user_text="survey the walls",
                mode="action",
                submode="survey",
                action="survey",
                options={},
                confidence="high",
                source="rules",
            ),
            required_template="action.md",
            response_headings=("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
            requires_preview=True,
            must_save=True,
            allowed_delta_sources=("resolver_proposed",),
            validation_profile="player_turn_commit",
        )
        response = "\n".join(
            (
                "## 场景",
                "城墙仍在玩家可见范围内。",
                "## 行动结果",
                "完成勘测。",
                "## 状态变化",
                "| 类型 | 变化 |",
                "| --- | --- |",
                "| 无 | 无 |",
                "## 保存状态",
                "尚未保存。",
                "## 后续行动",
                "| # | 行动 |",
                "| --- | --- |",
                "| 1 | 返回 |",
            )
        )

        result = lint_response(response, turn_contract=contract, registry=registry)

        self.assertNotIn("required_template mismatch", "\n".join(result.errors))

    def test_router_module_has_no_parallel_simple_synonym_tables(self) -> None:
        self.assertFalse(hasattr(intent_router, "ROUTINE_INTENT_TERMS"))
        self.assertFalse(hasattr(intent_router, "CRAFT_INTENT_TERMS"))

    def test_context_grammar_roles_are_selected_from_taxonomy(self) -> None:
        registry = get_default_action_registry()

        self.assertTrue(registry.text_has_term("盘点库存", action="routine", role="inventory"))
        self.assertFalse(registry.text_has_term("巡视领地", action="routine", role="inventory"))
        self.assertTrue(registry.text_has_term("到 Old Bridge", action="travel", role="context.travel"))
        self.assertTrue(registry.text_has_term("检查线索", role="context.explore"))

    def test_registry_detects_meaningful_content_after_the_last_canonical_term(self) -> None:
        registry = get_default_action_registry()

        self.assertTrue(registry.text_has_term_with_target_content("craft a sword", action="craft"))
        self.assertTrue(registry.text_has_term_with_target_content("请制作一把刀", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("craft?!", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("请修理", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("craft later", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("craft please", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("craft tomorrow morning", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("craft for me", action="craft"))
        self.assertFalse(registry.text_has_term_with_target_content("craft in the morning", action="craft"))
        for text in (
            "craft in two days",
            "craft on Monday",
            "craft after lunch",
            "craft for two days",
            "craft during the weekend",
            "craft before dinner",
            "craft at noon",
            "craft by tomorrow",
            "craft this week",
            "craft every day",
            "craft until Monday",
            "craft in four days",
            "craft for four weeks",
            "craft every week",
            "craft next Monday",
            "craft in several days",
            "craft after two days",
            "craft here",
            "craft carefully",
            "craft at camp",
            "craft weekly",
            "craft every weekend",
            "craft on the weekend",
            "craft monthly",
            "craft yearly",
            "craft every morning",
            "craft each day",
            "craft on weekends",
            "craft on weekdays",
            "craft at the weekend",
            "craft in 5 hours",
            "craft — please",
            "craft ※ please",
        ):
            with self.subTest(text=text):
                self.assertFalse(registry.text_has_term_with_target_content(text, action="craft"))

    def test_semantic_prompt_and_normalizer_use_the_injected_registry(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(taxonomy_spec("survey", terms=taxonomy_terms("en", ("survey",))))
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("create table meta (key text primary key, value text not null)")
        conn.execute("insert into meta(key, value) values ('current_location_id', 'loc:test')")
        try:
            prompt = build_semantic_prompt(
                SimpleNamespace(
                    conn=conn,
                    user_text="survey the walls",
                    mode="query",
                    submode="entity",
                    visibility_view="gm",
                    entity_hits=(),
                    action_registry=registry,
                )
            )
        finally:
            conn.close()

        self.assertIn("- survey:", prompt)
        self.assertNotIn("- routine:", prompt)
        self.assertEqual(
            normalize_semantic_suggestion(
                {"mode": "action", "submode": "survey", "confidence": "high"},
                registry=registry,
            )["submode"],
            "survey",
        )
        self.assertEqual(
            normalize_semantic_suggestion(
                {"mode": "action", "submode": "routine", "confidence": "high"},
                registry=registry,
            )["submode"],
            "unknown",
        )

    def test_subset_registry_rejects_dict_shaped_nested_actions(self) -> None:
        registry = ActionResolverRegistry()
        registry.register(taxonomy_spec("survey", terms=taxonomy_terms("en", ("survey",))))

        unsupported = inferred_actions_not_in_registry(
            {
                "action": "survey",
                "plan": ({"action": "travel"},),
                "repair_options": ({"action": "craft"}, {"action": "act"}),
            },
            registry=registry,
        )

        self.assertEqual(unsupported, ("craft", "travel"))

    def test_custom_registry_drives_manifest_prompt_normalization_and_external_contract(self) -> None:
        registry = registry_with_survey()
        manifest = build_intent_manifest(registry=registry)
        action_names = [action["name"] for action in manifest["actions"]]

        self.assertIn("survey", action_names)
        self.assertEqual(registry.match_action("勘测城墙"), "survey")
        self.assertEqual(manifest["action_taxonomy"], registry.taxonomy_projection())
        normalized = normalize_intent_candidate(
            {
                "kind": "single",
                "mode": "action",
                "action": "survey",
                "slots": {},
                "plan": [],
                "confidence": "high",
                "missing_slots": [],
                "needs_confirmation": [],
                "safety_flags": [],
                "reason": "custom action",
            },
            registry=registry,
        )
        self.assertEqual(normalized.action, "survey")

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("create table meta (key text primary key, value text not null)")
        conn.execute("insert into meta(key, value) values ('current_location_id', 'loc:test')")
        try:
            prompt = build_internal_intent_review_prompt(
                conn,
                "survey the walls",
                registry=registry,
            )
        finally:
            conn.close()
        self.assertIn('"name": "survey"', prompt)
        self.assertIn('"value": "survey"', prompt)
        self.assertIn(registry.taxonomy_digest, prompt)

        payload = {
            "contract": candidate_contract(manifest),
            "kind": "single",
            "mode": "action",
            "action": "survey",
            "slots": {},
            "plan": [],
            "confidence": "high",
            "missing_slots": [],
            "needs_confirmation": [],
            "safety_flags": [],
            "reason": "custom action",
        }
        validated = validate_external_intent_candidate(payload, registry=registry)
        self.assertEqual(validated.candidate.action, "survey")

        with self.assertRaises(ExternalIntentContractError) as raised:
            validate_external_intent_candidate(payload, registry=registry_with_survey("reconnoitre"))
        self.assertEqual(raised.exception.reason, "contract_version_mismatch")


if __name__ == "__main__":
    unittest.main()
