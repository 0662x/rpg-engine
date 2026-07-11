from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from contextvars import ContextVar
from dataclasses import replace
from unittest import mock
from pathlib import Path
from urllib import error as urlerror

from rpg_engine.ai import AIHelperTask
from rpg_engine.ai.defaults import (
    DEFAULT_AI_HARD_TIMEOUT_SECONDS,
    DEFAULT_AI_MODEL,
    DEFAULT_AI_PROVIDER,
    DEFAULT_AI_SOFT_WAIT_SECONDS,
    DEFAULT_BACKGROUND_TARGET_MAX_SECONDS,
    DEFAULT_BACKGROUND_TARGET_MIN_SECONDS,
    DEFAULT_INTENT_TIMEOUT_SECONDS,
)
from rpg_engine.ai.provider import (
    AI_HELPER_WORKER_LIMIT,
    AIHelperResult,
    InternalAIService,
    _AI_HELPER_WORKER_SLOTS,
    hard_timeout_result,
    public_ai_helper_result_dict,
    resolve_direct_base_url,
    run_ai_helper_json,
    with_latency_evidence,
)
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
        self.assertEqual(
            normalize_timeout(
                999,
                AIHelperPolicy(
                    max_timeout_seconds=20,
                    background_target_min_seconds=20,
                    background_target_max_seconds=20,
                ),
            ),
            20,
        )

        task = AIHelperTask(name="x", prompt="x", output_schema="reflection_draft.schema.json")
        for invalid_timeout in (float("inf"), float("-inf"), float("nan"), True, "15"):
            with self.subTest(invalid_timeout=invalid_timeout):
                invalid = run_ai_helper_json(
                    task,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    timeout=invalid_timeout,  # type: ignore[arg-type]
                )
                self.assertEqual(invalid.status, "error")
                self.assertIn("invalid ai timeout", invalid.error or "")

        with mock.patch.dict(os.environ, {}, clear=True):
            huge_timeout = run_ai_helper_json(
                task,
                backend="direct",
                provider="deepseek",
                model="test",
                timeout=10**10000,
                api_key_env="AIGM_TEST_MISSING_KEY",
            )
        self.assertEqual(huge_timeout.status, "error")
        self.assertEqual(huge_timeout.timeout_seconds, 120)

    def test_default_latency_policy_separates_soft_hard_and_background_targets(self) -> None:
        policy = AIHelperPolicy()

        self.assertEqual(DEFAULT_AI_SOFT_WAIT_SECONDS, 8)
        self.assertEqual(DEFAULT_AI_HARD_TIMEOUT_SECONDS, 15)
        self.assertEqual(DEFAULT_INTENT_TIMEOUT_SECONDS, DEFAULT_AI_HARD_TIMEOUT_SECONDS)
        self.assertEqual(DEFAULT_BACKGROUND_TARGET_MIN_SECONDS, 30)
        self.assertEqual(DEFAULT_BACKGROUND_TARGET_MAX_SECONDS, 60)
        self.assertEqual(policy.soft_wait_seconds, DEFAULT_AI_SOFT_WAIT_SECONDS)
        self.assertEqual(policy.background_target_min_seconds, DEFAULT_BACKGROUND_TARGET_MIN_SECONDS)
        self.assertEqual(policy.background_target_max_seconds, DEFAULT_BACKGROUND_TARGET_MAX_SECONDS)

    def test_helper_result_exposes_structured_timeout_evidence(self) -> None:
        result = AIHelperResult(
            task="internal_intent_review",
            backend="direct",
            provider="deepseek",
            model="test",
            status="error",
            error="internal_intent_review direct ai timed out after 15s",
            failure_reason="timeout",
            soft_wait_exceeded=True,
            hard_timeout=True,
            late_discarded=False,
            timeout_seconds=15,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_reason, "timeout")
        self.assertTrue(result.soft_wait_exceeded)
        self.assertTrue(result.hard_timeout)
        self.assertFalse(result.late_discarded)
        self.assertEqual(result.timeout_seconds, 15)

    def test_public_helper_evidence_redacts_provider_payloads_and_errors(self) -> None:
        helper = AIHelperResult(
            task="internal_intent_review",
            backend="direct",
            provider="deepseek",
            model="test",
            status="error",
            raw_text="hidden fact and private reasoning",
            error="HTTP 500: hidden fact and private reasoning",
            audit={
                "status": "error",
                "error": "HTTP 500: hidden fact",
                "output_summary": "private reasoning",
                "latency": {
                    "classification": "within_soft_wait",
                    "raw_prompt": "hidden prompt",
                    "private_reasoning": "secret chain",
                },
            },
        )

        public = public_ai_helper_result_dict(helper)
        encoded = str(public)

        self.assertEqual(public["error"], "internal_intent_review ai unavailable")
        self.assertEqual(public["audit"]["output_summary"], "")
        self.assertNotIn("hidden fact", encoded)
        self.assertNotIn("private reasoning", encoded)
        self.assertNotIn("hidden prompt", encoded)
        self.assertNotIn("secret chain", encoded)

        private_task = replace(helper, task="hidden fact private reasoning")
        self.assertEqual(public_ai_helper_result_dict(private_task)["task"], "ai helper")
        private_metadata = replace(
            helper,
            backend="vault_key_SECRET_BACKEND",
            provider="private reasoning",
            model="raw prompt",
        )
        private_public = public_ai_helper_result_dict(private_metadata)
        self.assertEqual(private_public["backend"], "")
        self.assertEqual(private_public["provider"], "")
        self.assertEqual(private_public["model"], "")

        false_authority = replace(helper, advisory=False, no_direct_writes=False)
        false_authority_public = public_ai_helper_result_dict(false_authority)
        self.assertTrue(false_authority_public["advisory"])
        self.assertTrue(false_authority_public["no_direct_writes"])

        malformed = type(
            "MalformedHelper",
            (),
            {
                "task": {"raw_prompt": "SECRET1"},
                "backend": ["SECRET2"],
                "provider": {"private_reasoning": "SECRET3"},
                "model": ["SECRET4"],
                "status": {"SECRET5": True},
                "error": "x",
                "elapsed_ms": {"SECRET6": 1},
                "advisory": {"SECRET7": True},
                "no_direct_writes": ["SECRET8"],
                "audit": {
                    "task": "vault_key_SECRET9",
                    "primary_audit": {"task": "vault_key_SECRET11"},
                    "latency": {
                        "classification": {"raw_prompt": "SECRET10"},
                        "elapsed_ms": float("nan"),
                        "hard_timeout_seconds": float("inf"),
                    },
                },
            },
        )()
        malformed_public = public_ai_helper_result_dict(malformed)
        malformed_encoded = str(malformed_public)
        self.assertNotIn("SECRET", malformed_encoded)
        self.assertEqual(malformed_public["audit"]["task"], "ai helper")
        self.assertEqual(malformed_public["audit"]["primary_audit"]["task"], "ai helper")
        self.assertEqual(malformed_public["task"], "ai helper")
        self.assertEqual(malformed_public["status"], "error")
        self.assertEqual(malformed_public["elapsed_ms"], 0)

        malformed.elapsed_ms = 10**10000
        malformed.timeout_seconds = 10**10000
        huge_public = public_ai_helper_result_dict(malformed)
        self.assertEqual(huge_public["elapsed_ms"], 0)
        self.assertIsNone(huge_public["timeout_seconds"])

        cyclic_audit: dict[str, object] = {}
        cyclic_audit["primary_audit"] = cyclic_audit
        malformed.audit = cyclic_audit
        cyclic_public = public_ai_helper_result_dict(malformed)
        self.assertEqual(cyclic_public["audit"]["primary_audit"], {})

    def test_direct_fallback_uses_remaining_total_deadline(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        primary = AIHelperResult(
            task=task.name,
            backend="direct",
            provider="deepseek",
            model="test",
            status="error",
            error="primary failed",
            failure_reason="timeout",
            audit={"status": "error", "error": "private transport body", "output_summary": "private reasoning"},
        )
        fallback = AIHelperResult(
            task=task.name,
            backend="hermes_z",
            provider="deepseek",
            model="test",
            status="ok",
            parsed={"title": "t", "summary": "s", "key_points": [], "source_event_ids": []},
        )
        service = InternalAIService()

        with mock.patch.object(service, "_complete_direct", return_value=primary) as direct:
            with mock.patch.object(service, "_complete_hermes_z", return_value=fallback) as hermes:
                with mock.patch(
                    "rpg_engine.ai.provider.time.perf_counter",
                    side_effect=clock_sequence(100.0, 100.0, 103.0),
                ):
                    result = service.complete_json(
                        task,
                        backend="direct",
                        provider="deepseek",
                        model="test",
                        timeout=15,
                        fallback_backend="hermes_z",
                    )

        self.assertTrue(result.ok, result.error)
        self.assertLessEqual(direct.call_args.kwargs["timeout"], 15)
        self.assertGreater(direct.call_args.kwargs["timeout"], 11)
        self.assertLessEqual(hermes.call_args.kwargs["timeout"], 12)
        self.assertGreater(hermes.call_args.kwargs["timeout"], 11)
        self.assertEqual(result.timeout_seconds, 15)
        self.assertFalse(result.hard_timeout)
        self.assertEqual(result.audit["primary_audit"]["latency"]["classification"], "backend_timeout")
        self.assertEqual(result.audit["primary_audit"]["output_summary"], "")
        self.assertEqual(result.audit["primary_error"], "timeout")

    def test_valid_result_after_hard_deadline_is_discarded(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        late = AIHelperResult(
            task=task.name,
            backend="direct",
            provider="deepseek",
            model="test",
            status="ok",
            parsed={"title": "t", "summary": "s", "key_points": [], "source_event_ids": []},
            raw_text="private late payload",
        )
        with mock.patch("rpg_engine.ai.provider.time.perf_counter", return_value=216.0):
            result = with_latency_evidence(
                late,
                started=200.0,
                timeout_seconds=15,
                policy=AIHelperPolicy(),
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_reason, "timeout")
        self.assertTrue(result.soft_wait_exceeded)
        self.assertTrue(result.hard_timeout)
        self.assertTrue(result.late_discarded)
        self.assertIsNone(result.parsed)
        self.assertEqual(result.raw_text, "")
        self.assertEqual(result.audit["latency"]["classification"], "late_discarded")
        self.assertEqual(result.audit["status"], "error")
        self.assertEqual(result.audit["error"], result.error)
        self.assertEqual(result.audit["output_summary"], "")

    def test_soft_wait_exceeded_before_hard_deadline_keeps_valid_result(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        success = AIHelperResult(
            task=task.name,
            backend="direct",
            provider="deepseek",
            model="test",
            status="ok",
            parsed={"title": "t", "summary": "s", "key_points": [], "source_event_ids": []},
        )
        service = InternalAIService()

        with mock.patch.object(service, "_complete_direct", return_value=success):
            with mock.patch(
                "rpg_engine.ai.provider.time.perf_counter",
                side_effect=clock_sequence(0.0, 0.0, 9.0),
            ):
                result = service.complete_json(
                    task,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    timeout=15,
                    fallback_backend="off",
                )

        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.soft_wait_exceeded)
        self.assertFalse(result.hard_timeout)
        self.assertEqual(result.audit["latency"]["classification"], "soft_wait_exceeded")
        self.assertEqual(result.audit["elapsed_ms"], result.elapsed_ms)

    def test_background_latency_uses_background_target_instead_of_player_soft_wait(self) -> None:
        success = AIHelperResult(
            task="reflection",
            backend="direct",
            provider="deepseek",
            model="test",
            status="ok",
            parsed={"title": "t"},
        )
        with mock.patch("rpg_engine.ai.provider.time.perf_counter", return_value=140.0):
            result = with_latency_evidence(
                success,
                started=100.0,
                timeout_seconds=60,
                policy=AIHelperPolicy(),
                execution_class="background",
            )

        self.assertFalse(result.soft_wait_exceeded)
        self.assertEqual(result.audit["latency"]["classification"], "background_within_target")
        self.assertEqual(result.audit["latency"]["background_target_status"], "within_target")

    def test_operation_boundary_returns_at_hard_deadline_before_late_worker(self) -> None:
        parser_started = threading.Event()
        parser_release = threading.Event()
        parser_finished = threading.Event()

        def blocking_parser(value: dict) -> dict:
            parser_started.set()
            parser_release.wait()
            parser_finished.set()
            return value

        task = AIHelperTask(
            name="reflection",
            prompt="x",
            output_schema="reflection_draft.schema.json",
            parser=blocking_parser,
        )
        service = InternalAIService()

        try:
            with mock.patch.dict(
                os.environ,
                {"AIGM_AI_FAKE_RESPONSE": '{"title":"t","summary":"s","key_points":[],"source_event_ids":[]}'},
                clear=False,
            ):
                with mock.patch("rpg_engine.ai.provider.normalize_timeout", return_value=0.2):
                    result = service.complete_json(
                        task,
                        backend="direct",
                        provider="deepseek",
                        model="test",
                        timeout=15,
                        fallback_backend="off",
                    )
            self.assertTrue(parser_started.wait(1))
            self.assertFalse(parser_finished.is_set())
            self.assertFalse(result.ok)
            self.assertEqual(result.failure_reason, "timeout")
            self.assertTrue(result.hard_timeout)
        finally:
            parser_release.set()
        self.assertTrue(parser_finished.wait(1))

    def test_wrapped_and_http_gateway_timeouts_are_structured(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        service = InternalAIService()
        cases = (
            urlerror.URLError(TimeoutError("timed out")),
            urlerror.URLError(urlerror.URLError(TimeoutError("nested timeout"))),
            urlerror.HTTPError("https://example.test", 504, "gateway timeout", {}, None),
            urlerror.HTTPError("https://example.test", 408, "request timeout", {}, None),
        )

        for exception in cases:
            with self.subTest(exception=exception):
                with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
                    os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
                    with mock.patch("urllib.request.urlopen", side_effect=exception):
                        result = service.complete_json(
                            task,
                            backend="direct",
                            provider=DEFAULT_AI_PROVIDER,
                            model=DEFAULT_AI_MODEL,
                            timeout=15,
                            fallback_backend="off",
                        )

                self.assertFalse(result.ok)
                self.assertEqual(result.failure_reason, "timeout")
                self.assertFalse(result.hard_timeout)
                self.assertEqual(result.audit["latency"]["classification"], "backend_timeout")

        with mock.patch("subprocess.run", side_effect=TimeoutError("process timed out")):
            hermes_timeout = service.complete_json(
                task,
                backend="hermes_z",
                provider=DEFAULT_AI_PROVIDER,
                model=DEFAULT_AI_MODEL,
                timeout=15,
                fallback_backend="off",
            )
        self.assertEqual(hermes_timeout.failure_reason, "timeout")
        self.assertEqual(hermes_timeout.audit["latency"]["classification"], "backend_timeout")

    def test_transport_and_process_do_not_start_after_deadline(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        service = InternalAIService()
        policy = AIHelperPolicy()

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
            os.environ.pop("AIGM_AI_FAKE_RESPONSE", None)
            with mock.patch("rpg_engine.ai.provider.remaining_timeout_seconds", return_value=0):
                with mock.patch("urllib.request.urlopen") as urlopen:
                    direct = service._complete_direct(
                        task,
                        provider="deepseek",
                        model="test",
                        timeout=15,
                        policy=policy,
                        started=time.perf_counter(),
                        deadline=time.perf_counter() + 15,
                        base_url=None,
                        api_key_env=None,
                    )
        urlopen.assert_not_called()
        self.assertEqual(direct.failure_reason, "timeout")

        with mock.patch("rpg_engine.ai.provider.remaining_timeout_seconds", return_value=0):
            with mock.patch("subprocess.run") as run:
                hermes = service._complete_hermes_z(
                    task,
                    provider="deepseek",
                    model="test",
                    timeout=15,
                    policy=policy,
                    started=time.perf_counter(),
                    deadline=time.perf_counter() + 15,
                )
        run.assert_not_called()
        self.assertEqual(hermes.failure_reason, "timeout")

    def test_latency_policy_rejects_invalid_targets(self) -> None:
        invalid = (
            {"soft_wait_seconds": -1},
            {"soft_wait_seconds": None},
            {"background_target_min_seconds": -1},
            {"background_target_min_seconds": 61, "background_target_max_seconds": 60},
            {"min_timeout_seconds": 20, "max_timeout_seconds": 10},
            {"max_output_chars": 0},
            {"max_output_chars": 1.5},
            {"soft_wait_seconds": 121, "max_timeout_seconds": 120},
            {"max_timeout_seconds": 59},
            {"max_timeout_seconds": 121},
            {"min_timeout_seconds": 3.5},
            {"max_timeout_seconds": 120.5, "background_target_max_seconds": 60},
            {"advisory": False},
            {"fail_closed": False},
            {"no_direct_writes": False},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    AIHelperPolicy(**kwargs)

    def test_explicit_hard_timeout_flag_is_not_downgraded_by_fast_annotation(self) -> None:
        task = AIHelperTask(name="x", prompt="x", output_schema="reflection_draft.schema.json")
        base = AIHelperResult(
            task=task.name,
            backend="direct",
            provider="deepseek",
            model="test",
            status="error",
            error="deadline",
        )
        with mock.patch("rpg_engine.ai.provider.time.perf_counter", side_effect=clock_sequence(10.0, 10.0)):
            result = hard_timeout_result(
                base,
                started=10.0,
                timeout_seconds=15,
                policy=AIHelperPolicy(),
            )

        self.assertTrue(result.hard_timeout)
        self.assertEqual(result.failure_reason, "timeout")
        self.assertEqual(result.audit["latency"]["classification"], "hard_timeout")

    def test_worker_capacity_bounds_late_operations_and_recovers(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        service = InternalAIService()
        release = threading.Event()
        all_started = threading.Event()
        all_finished = threading.Event()
        lock = threading.Lock()
        start_condition = threading.Condition(lock)
        counts = {"started": 0, "finished": 0}
        thread_start_count = 0
        remaining_call_count = 0
        original_thread_start = threading.Thread.start
        blocked_result = AIHelperResult(
            task=task.name,
            backend="direct",
            provider="deepseek",
            model="test",
            status="error",
            error="released",
        )

        background_success = AIHelperResult(
            task=task.name,
            backend="direct",
            provider="deepseek",
            model="test",
            status="ok",
            parsed={"title": "t", "summary": "s", "key_points": [], "source_event_ids": []},
        )

        def blocked(task_arg, *args, **kwargs):
            if task_arg.execution_class == "background":
                return background_success
            with lock:
                counts["started"] += 1
                start_condition.notify_all()
                if counts["started"] == 8:
                    all_started.set()
            release.wait()
            with lock:
                counts["finished"] += 1
                if counts["finished"] == 8:
                    all_finished.set()
            return blocked_result

        def coordinated_thread_start(worker):
            nonlocal thread_start_count
            with lock:
                thread_start_count += 1
                expected_started = thread_start_count
            original_thread_start(worker)
            if expected_started <= AI_HELPER_WORKER_LIMIT:
                with start_condition:
                    self.assertTrue(start_condition.wait_for(lambda: counts["started"] >= expected_started, timeout=1))

        def deterministic_remaining(_deadline: float) -> float:
            nonlocal remaining_call_count
            with lock:
                value = (1.0, 1.0, 0.001)[remaining_call_count % 3]
                remaining_call_count += 1
            return value

        try:
            with mock.patch.object(service, "_complete_direct", side_effect=blocked):
                with mock.patch(
                    "rpg_engine.ai.provider.remaining_timeout_seconds",
                    side_effect=deterministic_remaining,
                ):
                    with mock.patch("rpg_engine.ai.provider.threading.Thread.start", coordinated_thread_start):
                        timed_out = [
                            service.complete_json(
                                task,
                                backend="direct",
                                provider="deepseek",
                                model="test",
                                timeout=15,
                                fallback_backend="off",
                            )
                            for _ in range(8)
                        ]
                        self.assertTrue(all_started.wait(1))
                        saturated = service.complete_json(
                            task,
                            backend="direct",
                            provider="deepseek",
                            model="test",
                            timeout=15,
                            fallback_backend="off",
                        )
                        background = service.complete_json(
                            AIHelperTask(
                                name="reflection",
                                prompt="x",
                                output_schema="reflection_draft.schema.json",
                                execution_class="background",
                            ),
                            backend="direct",
                            provider="deepseek",
                            model="test",
                            timeout=15,
                            fallback_backend="off",
                        )

            self.assertTrue(all(item.hard_timeout for item in timed_out))
            self.assertEqual(saturated.failure_reason, "worker_unavailable")
            self.assertTrue(background.ok, background.error)
        finally:
            release.set()
        self.assertTrue(all_finished.wait(1))

    def test_worker_start_delay_uses_fresh_wait_budget_and_exception_can_fallback(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        service = InternalAIService()
        release = threading.Event()
        worker_started = threading.Event()
        worker_finished = threading.Event()
        original_start = threading.Thread.start
        remaining_budgets = iter((0.05, 0.04, 0.01))
        observed_budgets: list[float] = []

        def delayed_start(worker):
            original_start(worker)
            self.assertTrue(worker_started.wait(1))

        def blocked(*args, **kwargs):
            try:
                worker_started.set()
                release.wait()
                return AIHelperResult(
                    task=task.name,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    status="error",
                    error="released",
                )
            finally:
                worker_finished.set()

        def record_remaining(deadline: float) -> float:
            remaining = next(remaining_budgets)
            observed_budgets.append(remaining)
            return remaining

        try:
            with mock.patch.object(service, "_complete_direct", side_effect=blocked):
                with mock.patch("rpg_engine.ai.provider.normalize_timeout", return_value=0.05):
                    with mock.patch(
                        "rpg_engine.ai.provider.time.perf_counter",
                        side_effect=(100.0, 100.05, 100.05, 100.05),
                    ):
                        with mock.patch(
                            "rpg_engine.ai.provider.remaining_timeout_seconds",
                            side_effect=record_remaining,
                        ):
                            with mock.patch("rpg_engine.ai.provider.threading.Thread.start", delayed_start):
                                result = service.complete_json(
                                    task,
                                    backend="direct",
                                    provider="deepseek",
                                    model="test",
                                    timeout=15,
                                    fallback_backend="off",
                                )
        finally:
            release.set()

        self.assertTrue(worker_finished.wait(1))
        self.assertEqual(observed_budgets, [0.05, 0.04, 0.01])
        self.assertTrue(result.hard_timeout)

        fallback = AIHelperResult(
            task=task.name,
            backend="hermes_z",
            provider="deepseek",
            model="test",
            status="ok",
            parsed={"title": "t", "summary": "s", "key_points": [], "source_event_ids": []},
        )
        with mock.patch.object(service, "_complete_direct", side_effect=RuntimeError("backend crash")):
            with mock.patch.object(service, "_complete_hermes_z", return_value=fallback):
                recovered = service.complete_json(
                    task,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    timeout=15,
                    fallback_backend="hermes_z",
                )
        self.assertTrue(recovered.ok, recovered.error)
        self.assertEqual(recovered.audit["primary_error"], "worker_unavailable")

    def test_worker_propagates_contextvars_and_start_failure_is_structured(self) -> None:
        request_id: ContextVar[str] = ContextVar("request_id", default="missing")
        observed: list[str] = []
        token = request_id.set("request:test")
        task = AIHelperTask(
            name="reflection",
            prompt="x",
            output_schema="reflection_draft.schema.json",
            parser=lambda value: observed.append(request_id.get()) or value,
        )
        try:
            with mock.patch.dict(
                os.environ,
                {"AIGM_AI_FAKE_RESPONSE": '{"title":"t","summary":"s","key_points":[],"source_event_ids":[]}'},
                clear=False,
            ):
                result = InternalAIService().complete_json(
                    task,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    timeout=15,
                    fallback_backend="off",
                )
        finally:
            request_id.reset(token)

        self.assertTrue(result.ok, result.error)
        self.assertEqual(observed, ["request:test"])

        with mock.patch("rpg_engine.ai.provider.threading.Thread.start", side_effect=RuntimeError("no threads")):
            failed = InternalAIService().complete_json(
                task,
                backend="direct",
                provider="deepseek",
                model="test",
                timeout=15,
                fallback_backend="off",
            )
        self.assertFalse(failed.ok)
        self.assertEqual(failed.failure_reason, "worker_unavailable")

        with mock.patch("rpg_engine.ai.provider.copy_context", side_effect=ValueError("context unavailable")):
            context_failed = InternalAIService().complete_json(
                task,
                backend="direct",
                provider="deepseek",
                model="test",
                timeout=15,
                fallback_backend="off",
            )
        self.assertEqual(context_failed.failure_reason, "worker_unavailable")

        for _ in range(AI_HELPER_WORKER_LIMIT):
            with mock.patch("rpg_engine.ai.provider.threading.Lock", side_effect=RuntimeError("no lock")):
                lock_failed = InternalAIService().complete_json(
                    task,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    timeout=15,
                    fallback_backend="off",
                )
            self.assertEqual(lock_failed.failure_reason, "worker_unavailable")

        for _ in range(AI_HELPER_WORKER_LIMIT):
            with mock.patch("rpg_engine.ai.provider.copy_context", side_effect=KeyboardInterrupt()):
                with self.assertRaises(KeyboardInterrupt):
                    InternalAIService().complete_json(
                        task,
                        backend="direct",
                        provider="deepseek",
                        model="test",
                        timeout=15,
                        fallback_backend="off",
                    )

        control_service = InternalAIService()
        with mock.patch.object(control_service, "_complete_direct", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                control_service.complete_json(
                    task,
                    backend="direct",
                    provider="deepseek",
                    model="test",
                    timeout=15,
                    fallback_backend="off",
                )

        boundary_service = InternalAIService()
        with mock.patch.object(boundary_service, "_complete_direct", side_effect=KeyboardInterrupt()):
            with mock.patch("rpg_engine.ai.provider.deadline_reached", return_value=True):
                with self.assertRaises(KeyboardInterrupt):
                    boundary_service.complete_json(
                        task,
                        backend="direct",
                        provider="deepseek",
                        model="test",
                        timeout=15,
                        fallback_backend="off",
                    )

    def test_worker_start_interruption_after_launch_releases_slot_exactly_once(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        service = InternalAIService()
        worker_started = threading.Event()
        worker_release = threading.Event()
        original_start = threading.Thread.start
        launched_workers: list[threading.Thread] = []
        uncaught: list[BaseException] = []

        def blocked(*args, **kwargs):
            worker_started.set()
            worker_release.wait()
            return AIHelperResult(
                task=task.name,
                backend="direct",
                provider="deepseek",
                model="test",
                status="error",
            )

        def start_then_interrupt(worker):
            launched_workers.append(worker)
            original_start(worker)
            self.assertTrue(worker_started.wait(1))
            raise KeyboardInterrupt()

        def capture_uncaught(args):
            uncaught.append(args.exc_value)

        slots = _AI_HELPER_WORKER_SLOTS["foreground"]
        try:
            with mock.patch.object(service, "_complete_direct", side_effect=blocked):
                with mock.patch("rpg_engine.ai.provider.threading.Thread.start", start_then_interrupt):
                    with mock.patch("threading.excepthook", side_effect=capture_uncaught):
                        with self.assertRaises(KeyboardInterrupt):
                            service.complete_json(
                                task,
                                backend="direct",
                                provider="deepseek",
                                model="test",
                                timeout=15,
                                fallback_backend="off",
                            )
                        self.assertEqual(slots._value, AI_HELPER_WORKER_LIMIT - 1)
        finally:
            worker_release.set()
        launched_workers[0].join(1)
        self.assertFalse(launched_workers[0].is_alive())
        self.assertEqual(slots._value, AI_HELPER_WORKER_LIMIT)
        self.assertEqual(uncaught, [])

    def test_worker_start_interruption_before_entry_cancels_delayed_worker(self) -> None:
        task = AIHelperTask(name="reflection", prompt="x", output_schema="reflection_draft.schema.json")
        service = InternalAIService()
        enter_gate = threading.Event()
        delayed_finished = threading.Event()
        operation_started = threading.Event()
        original_thread = threading.Thread
        delayed_threads: list[threading.Thread] = []

        class DelayedEntryThread:
            ident = None

            def __init__(self, *, target, name, daemon):
                self.target = target
                self.name = name
                self.daemon = daemon

            def start(self):
                def delayed_target():
                    enter_gate.wait()
                    try:
                        self.target()
                    finally:
                        delayed_finished.set()

                delayed = original_thread(target=delayed_target, daemon=True)
                delayed_threads.append(delayed)
                delayed.start()
                raise KeyboardInterrupt()

        def operation(*args, **kwargs):
            operation_started.set()
            return AIHelperResult(
                task=task.name,
                backend="direct",
                provider="deepseek",
                model="test",
                status="error",
            )

        slots = _AI_HELPER_WORKER_SLOTS["foreground"]
        with mock.patch.object(service, "_complete_direct", side_effect=operation):
            with mock.patch("rpg_engine.ai.provider.threading.Thread", DelayedEntryThread):
                with self.assertRaises(KeyboardInterrupt):
                    service.complete_json(
                        task,
                        backend="direct",
                        provider="deepseek",
                        model="test",
                        timeout=15,
                        fallback_backend="off",
                    )
        self.assertEqual(slots._value, AI_HELPER_WORKER_LIMIT)
        enter_gate.set()
        self.assertTrue(delayed_finished.wait(1))
        delayed_threads[0].join(1)
        self.assertFalse(operation_started.is_set())
        self.assertEqual(slots._value, AI_HELPER_WORKER_LIMIT)

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


def clock_sequence(*values: float):
    iterator = iter(values)
    last = values[-1]

    def current() -> float:
        nonlocal last
        try:
            last = next(iterator)
        except StopIteration:
            pass
        return last

    return current
