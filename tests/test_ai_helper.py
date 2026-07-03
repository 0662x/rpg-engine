from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from rpg_engine.ai import AIHelperTask
from rpg_engine.ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER
from rpg_engine.ai.provider import resolve_direct_base_url, run_ai_helper_json
from rpg_engine.ai.config import resolve_ai_helper_settings
from rpg_engine.ai.policy import AIHelperPolicy, normalize_timeout


class AIHelperTests(unittest.TestCase):
    def run_with_fake_hermes(self, output: str, task: AIHelperTask):
        with tempfile.TemporaryDirectory() as tmp:
            fake_hermes = Path(tmp) / "hermes"
            fake_hermes.write_text("#!/bin/sh\nprintf '%s\\n' " + repr(output) + "\n", encoding="utf-8")
            fake_hermes.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
            try:
                return run_ai_helper_json(
                    task,
                    backend="hermes",
                    provider=DEFAULT_AI_PROVIDER,
                    model=DEFAULT_AI_MODEL,
                    timeout=3,
                )
            finally:
                os.environ["PATH"] = old_path

    def test_direct_backend_uses_openai_compatible_json_without_hermes(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        response_body = json_bytes(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"title":"t","summary":"s","key_points":[],"source_event_ids":[]}'
                        }
                    }
                ]
            }
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, _limit: int) -> bytes:
                return response_body

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
            with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
                result = run_ai_helper_json(
                    task,
                    backend="direct",
                    provider=DEFAULT_AI_PROVIDER,
                    model=DEFAULT_AI_MODEL,
                    timeout=3,
                    fallback_backend="off",
                )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.backend, "direct")
        self.assertEqual(result.parsed["title"], "t")
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        body = json_loads(request.data)
        self.assertEqual(body["model"], DEFAULT_AI_MODEL)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["thinking"], {"type": "disabled"})

    def test_direct_backend_accepts_openai_compatible_base_url(self) -> None:
        self.assertEqual(
            resolve_direct_base_url("deepseek", "https://api.deepseek.com"),
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            resolve_direct_base_url("deepseek", "https://api.deepseek.com/beta"),
            "https://api.deepseek.com/beta/chat/completions",
        )
        self.assertEqual(
            resolve_direct_base_url("deepseek", "https://api.deepseek.com/chat/completions"),
            "https://api.deepseek.com/chat/completions",
        )
        self.assertEqual(
            resolve_direct_base_url("openai", "https://api.openai.com"),
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            resolve_direct_base_url("openai", "https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_direct_backend_does_not_fallback_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
            os.environ.pop("AIGM_TEST_MISSING_KEY", None)
            result = run_ai_helper_json(
                AIHelperTask(name="x", prompt="x", output_schema="reflection_draft.schema.json"),
                backend="direct",
                provider=DEFAULT_AI_PROVIDER,
                model=DEFAULT_AI_MODEL,
                timeout=3,
                api_key_env="AIGM_TEST_MISSING_KEY",
            )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.backend, "direct")
        self.assertIn("missing API key", result.error or "")
        self.assertNotIn("fallback_used", result.audit)

    def test_direct_backend_rejects_direct_as_fallback_backend(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
            result = run_ai_helper_json(
                AIHelperTask(name="x", prompt="x", output_schema="reflection_draft.schema.json"),
                backend="direct",
                provider=DEFAULT_AI_PROVIDER,
                model=DEFAULT_AI_MODEL,
                timeout=3,
                fallback_backend="direct",
            )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.backend, "direct")
        self.assertIn("unsupported ai helper fallback backend", result.error or "")

    def test_direct_backend_explicit_hermes_z_fallback_records_primary_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_hermes = Path(tmp) / "hermes"
            fake_hermes.write_text(
                "#!/bin/sh\nprintf '%s\\n' '{\"title\":\"t\",\"summary\":\"s\",\"key_points\":[],\"source_event_ids\":[]}'\n",
                encoding="utf-8",
            )
            fake_hermes.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
            try:
                os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                os.environ.pop("AIGM_TEST_MISSING_KEY", None)
                result = run_ai_helper_json(
                    AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json"),
                    backend="direct",
                    provider=DEFAULT_AI_PROVIDER,
                    model=DEFAULT_AI_MODEL,
                    timeout=3,
                    api_key_env="AIGM_TEST_MISSING_KEY",
                    fallback_backend="hermes_z",
                )
            finally:
                os.environ["PATH"] = old_path

        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.backend, "hermes_z")
        self.assertTrue(result.audit["fallback_used"])
        self.assertEqual(result.audit["primary_backend"], "direct")
        self.assertIn("primary_audit", result.audit)

    def test_provider_validates_json_schema_output_before_normalizing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_hermes = Path(tmp) / "hermes"
            fake_hermes.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' '{\"ok\":\"yes\",\"risk\":\"urgent\",\"findings\":[],\"missing_structured_changes\":[],\"requires_human_review\":false}'\n",
                encoding="utf-8",
            )
            fake_hermes.chmod(0o755)
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{tmp}{os.pathsep}{old_path}"
            try:
                result = run_ai_helper_json(
                    AIHelperTask(
                        name="state_audit",
                        prompt="return bad schema",
                        output_schema="state_audit.schema.json",
                    ),
                    backend="hermes",
                    provider=DEFAULT_AI_PROVIDER,
                    model=DEFAULT_AI_MODEL,
                    timeout=3,
                )
            finally:
                os.environ["PATH"] = old_path

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "error")
        self.assertIn("schema validation failed", result.error or "")
        self.assertIn("$.ok", result.error or "")

    def test_semantic_and_reflection_schemas_are_real_resources(self) -> None:
        semantic = self.run_with_fake_hermes(
            '{"mode":"action","submode":"gather","targets":[],"entities_mentioned":[],"missing_confirmations":[],"notes":[],"confidence":"high"}',
            AIHelperTask(name="semantic", prompt="x", output_schema="semantic_suggestion.schema.json"),
        )
        reflection = self.run_with_fake_hermes(
            '{"title":"t","summary":"s","key_points":[],"source_event_ids":[]}',
            AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json"),
        )
        self.assertTrue(semantic.ok, semantic.error)
        self.assertTrue(reflection.ok, reflection.error)

    def test_unknown_schema_name_and_parser_failure_return_standard_error(self) -> None:
        bad_schema = self.run_with_fake_hermes(
            '{}', AIHelperTask(name="bad", prompt="x", output_schema="NotAResource")
        )
        bad_parser = self.run_with_fake_hermes(
            '{"title":"t","summary":"s","key_points":[],"source_event_ids":[]}',
            AIHelperTask(
                name="bad_parser",
                prompt="x",
                output_schema="reflection_draft.schema.json",
                parser=lambda value: (_ for _ in ()).throw(ValueError("boom")),
            ),
        )
        self.assertEqual(bad_schema.status, "error")
        self.assertIn("must end with .json", bad_schema.error or "")
        self.assertEqual(bad_parser.status, "error")
        self.assertIn("normalization failed", bad_parser.error or "")

    def test_provider_rejects_empty_model_and_bounds_timeout(self) -> None:
        result = run_ai_helper_json(
            AIHelperTask(name="x", prompt="x", output_schema="reflection_draft.schema.json"),
            backend="hermes",
            provider="deepseek",
            model="",
            timeout=3,
        )
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error, "ai model is required")
        self.assertEqual(normalize_timeout(999, AIHelperPolicy(max_timeout_seconds=20)), 20)

    def test_profiles_share_defaults_and_allow_feature_overrides(self) -> None:
        balanced = resolve_ai_helper_settings(profile="balanced", model="flash-model")
        self.assertEqual(balanced.semantic_ai, "direct")
        self.assertEqual(balanced.semantic_model, "flash-model")
        self.assertEqual(balanced.intent_ai, "off")
        self.assertEqual(balanced.intent_backend, "direct")
        self.assertEqual(balanced.intent_model, "flash-model")
        self.assertEqual(balanced.state_audit_ai, "off")
        self.assertFalse(balanced.archivist_suggest)

        full = resolve_ai_helper_settings(profile="full", archivist_ai="off", semantic_timeout=999)
        self.assertEqual(full.intent_ai, "consensus")
        self.assertEqual(full.intent_backend, "direct")
        self.assertEqual(full.state_audit_ai, "direct")
        self.assertTrue(full.archivist_suggest)
        self.assertEqual(full.archivist_ai, "off")
        self.assertEqual(full.semantic_timeout, 120)

        explicit = resolve_ai_helper_settings(profile="off", intent_ai="consensus", intent_timeout=2)
        self.assertEqual(explicit.intent_ai, "consensus")
        self.assertEqual(explicit.intent_timeout, 3)

        custom = resolve_ai_helper_settings(
            profile="full",
            intent_base_url=" https://unit.test/chat ",
            intent_api_key_env=" AIGM_TEST_KEY ",
            intent_fallback_backend="hermes",
        )
        self.assertEqual(custom.intent_base_url, "https://unit.test/chat")
        self.assertEqual(custom.intent_api_key_env, "AIGM_TEST_KEY")
        self.assertEqual(custom.intent_fallback_backend, "hermes_z")

        with self.assertRaises(ValueError):
            resolve_ai_helper_settings(profile="full", intent_fallback_backend="direct")


def json_bytes(value: dict) -> bytes:
    import json

    return json.dumps(value).encode("utf-8")


def json_loads(value: bytes) -> dict:
    import json

    return json.loads(value.decode("utf-8"))
