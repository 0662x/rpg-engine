from __future__ import annotations

from importlib import resources
import json
import os
import shutil
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .mcp_transcript import validate_external_agent_transcript
from .ai.defaults import DEFAULT_AI_MODEL, DEFAULT_AI_PROVIDER
from .campaign import load_campaign
from .db import connect, init_database
from .resource_paths import copy_packaged_example
from .runtime import GMRuntime


ENGINE_ROOT = Path(__file__).resolve().parents[1]
EVAL_RESOURCE_DIR = resources.files("rpg_engine.resources").joinpath("evals")
DEFAULT_INTENT_GOLD = EVAL_RESOURCE_DIR.joinpath("intent_router_gold_set.yaml")
DEFAULT_INTENT_CONSENSUS_GOLD = EVAL_RESOURCE_DIR.joinpath("intent_consensus_gold_set.yaml")
DEFAULT_INTENT_CONSENSUS_COMMIT = EVAL_RESOURCE_DIR.joinpath("intent_consensus_commit_paths.yaml")
DEFAULT_INTENT_REAL_CANARY = EVAL_RESOURCE_DIR.joinpath("intent_real_canary.yaml")
DEFAULT_INTENT_CLARIFICATION_LOOPS = EVAL_RESOURCE_DIR.joinpath("intent_clarification_loops.yaml")
DEFAULT_MCP_TRANSCRIPTS = EVAL_RESOURCE_DIR.joinpath("mcp_external_agent_transcripts.yaml")
INTENT_LATENCY_BUDGET_MS = 8000


@dataclass(frozen=True)
class EvalCaseResult:
    id: str
    ok: bool
    errors: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalSuiteResult:
    suite: str
    ok: bool
    metrics: dict[str, Any]
    cases: tuple[EvalCaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "ok": self.ok,
            "metrics": self.metrics,
            "cases": [case.to_dict() for case in self.cases],
        }


@dataclass(frozen=True)
class EvalRunResult:
    ok: bool
    suites: tuple[EvalSuiteResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "metrics": aggregate_metrics(self.suites),
            "suites": [suite.to_dict() for suite in self.suites],
        }

    def to_json_text(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run_eval_suite(
    *,
    suite: str = "all",
    intent_gold_path: str | Path | None = None,
    intent_consensus_gold_path: str | Path | None = None,
    intent_consensus_commit_path: str | Path | None = None,
    intent_real_canary_path: str | Path | None = None,
    intent_clarification_loops_path: str | Path | None = None,
    mcp_transcripts_path: str | Path | None = None,
    campaign_dir: str | Path | None = None,
) -> EvalRunResult:
    requested = normalize_suite(suite)
    suites: list[EvalSuiteResult] = []
    if requested in {"all", "intent"}:
        suites.append(run_intent_gold_eval(intent_gold_path or DEFAULT_INTENT_GOLD, campaign_dir=campaign_dir))
    if requested in {"all", "intent-consensus"}:
        suites.append(
            run_intent_consensus_eval(
                intent_consensus_gold_path or DEFAULT_INTENT_CONSENSUS_GOLD,
                campaign_dir=campaign_dir,
            )
        )
    if requested in {"all", "intent-consensus-commit"}:
        suites.append(
            run_intent_consensus_commit_eval(
                intent_consensus_commit_path or DEFAULT_INTENT_CONSENSUS_COMMIT,
                campaign_dir=campaign_dir,
            )
        )
    if requested == "intent-real-canary":
        suites.append(
            run_intent_real_canary_eval(
                intent_real_canary_path or DEFAULT_INTENT_REAL_CANARY,
                campaign_dir=campaign_dir,
            )
        )
    if requested in {"all", "intent-clarification-loop"}:
        suites.append(
            run_intent_clarification_loop_eval(
                intent_clarification_loops_path or DEFAULT_INTENT_CLARIFICATION_LOOPS,
                campaign_dir=campaign_dir,
            )
        )
    if requested in {"all", "mcp"}:
        suites.append(run_mcp_transcript_eval(mcp_transcripts_path or DEFAULT_MCP_TRANSCRIPTS))
    return EvalRunResult(ok=all(item.ok for item in suites), suites=tuple(suites))


def normalize_suite(value: str) -> str:
    normalized = str(value or "all").strip().lower().replace("_", "-")
    aliases = {
        "intent-router": "intent",
        "intent-gold": "intent",
        "consensus-intent": "intent-consensus",
        "intent_consensus": "intent-consensus",
        "intent-consensus-gold": "intent-consensus",
        "consensus-commit": "intent-consensus-commit",
        "intent-commit": "intent-consensus-commit",
        "intent-consensus-commit-path": "intent-consensus-commit",
        "intent-consensus-commit-paths": "intent-consensus-commit",
        "real-canary": "intent-real-canary",
        "intent-canary": "intent-real-canary",
        "ai-canary": "intent-real-canary",
        "clarification-loop": "intent-clarification-loop",
        "clarification-loops": "intent-clarification-loop",
        "intent-loop": "intent-clarification-loop",
        "intent-clarification-loops": "intent-clarification-loop",
        "transcript": "mcp",
        "mcp-transcript": "mcp",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {
        "all",
        "intent",
        "intent-consensus",
        "intent-consensus-commit",
        "intent-real-canary",
        "intent-clarification-loop",
        "mcp",
    }:
        raise ValueError(f"unknown eval suite: {value}")
    return normalized


def run_intent_gold_eval(gold_path: str | Path, *, campaign_dir: str | Path | None = None) -> EvalSuiteResult:
    cases = load_yaml_mapping(gold_path).get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("intent gold set must contain a cases array")
    results: list[EvalCaseResult] = []
    with prepared_campaign(campaign_dir) as campaign_path:
        runtime = GMRuntime.from_path(campaign_path)
        for raw_case in cases:
            case = raw_case if isinstance(raw_case, dict) else {}
            results.append(evaluate_intent_case(runtime, case))
    metrics = summarize_intent_results(results)
    return EvalSuiteResult(
        suite="intent",
        ok=all(case.ok for case in results),
        metrics=metrics,
        cases=tuple(results),
    )


def run_intent_consensus_eval(gold_path: str | Path, *, campaign_dir: str | Path | None = None) -> EvalSuiteResult:
    cases = load_yaml_mapping(gold_path).get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("intent consensus gold set must contain a cases array")
    results: list[EvalCaseResult] = []
    with prepared_campaign(campaign_dir) as campaign_path:
        runtime = GMRuntime.from_path(campaign_path)
        with fake_internal_intent_reviews(cases):
            for raw_case in cases:
                case = raw_case if isinstance(raw_case, dict) else {}
                results.append(evaluate_intent_case(runtime, case))
    metrics = summarize_intent_results(results)
    return EvalSuiteResult(
        suite="intent-consensus",
        ok=all(case.ok for case in results),
        metrics=metrics,
        cases=tuple(results),
    )


def run_intent_clarification_loop_eval(
    gold_path: str | Path,
    *,
    campaign_dir: str | Path | None = None,
) -> EvalSuiteResult:
    loops = load_yaml_mapping(gold_path).get("loops", [])
    if not isinstance(loops, list):
        raise ValueError("intent clarification loop gold set must contain a loops array")
    results: list[EvalCaseResult] = []
    with prepared_campaign(campaign_dir) as campaign_path:
        runtime = GMRuntime.from_path(campaign_path)
        with fake_internal_intent_reviews(loop_step_cases(loops)):
            for raw_loop in loops:
                loop = raw_loop if isinstance(raw_loop, dict) else {}
                results.append(evaluate_clarification_loop(runtime, loop))
    metrics = summarize_clarification_loop_results(results)
    return EvalSuiteResult(
        suite="intent-clarification-loop",
        ok=all(case.ok for case in results),
        metrics=metrics,
        cases=tuple(results),
    )


def run_intent_consensus_commit_eval(
    gold_path: str | Path,
    *,
    campaign_dir: str | Path | None = None,
) -> EvalSuiteResult:
    cases = load_yaml_mapping(gold_path).get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("intent consensus commit gold set must contain a cases array")
    results: list[EvalCaseResult] = []
    with fake_internal_intent_reviews(cases):
        for raw_case in cases:
            case = raw_case if isinstance(raw_case, dict) else {}
            with prepared_campaign(campaign_dir) as campaign_path:
                runtime = GMRuntime.from_path(campaign_path)
                results.append(evaluate_consensus_commit_case(runtime, case))
    metrics = summarize_consensus_commit_results(results)
    return EvalSuiteResult(
        suite="intent-consensus-commit",
        ok=all(case.ok for case in results),
        metrics=metrics,
        cases=tuple(results),
    )


def run_intent_real_canary_eval(
    gold_path: str | Path,
    *,
    campaign_dir: str | Path | None = None,
) -> EvalSuiteResult:
    cases = load_yaml_mapping(gold_path).get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("intent real canary set must contain a cases array")
    results: list[EvalCaseResult] = []
    for raw_case in cases:
        case = raw_case if isinstance(raw_case, dict) else {}
        with prepared_campaign(campaign_dir) as campaign_path:
            runtime = GMRuntime.from_path(campaign_path)
            results.append(evaluate_real_canary_case(runtime, case))
    metrics = summarize_real_canary_results(results)
    return EvalSuiteResult(
        suite="intent-real-canary",
        ok=True,
        metrics=metrics,
        cases=tuple(results),
    )


def evaluate_intent_case(runtime: GMRuntime, case: dict[str, Any]) -> EvalCaseResult:
    case_id = str(case.get("id") or "unknown")
    text = str(case.get("text") or "")
    errors: list[str] = []
    expected_start = case.get("start") if isinstance(case.get("start"), dict) else {}
    expected_preview = case.get("preview") if isinstance(case.get("preview"), dict) else {}
    runtime_options = intent_runtime_options(case)
    start = runtime.start_turn(text, **runtime_options)
    preview = runtime.preview_from_text(text, **runtime_options)
    start_clarification = start.clarification if isinstance(start.clarification, dict) else None
    context_clarification = (
        start.context.completeness.get("clarification")
        if start.context and isinstance(start.context.completeness.get("clarification"), dict)
        else None
    )
    preview_intent = preview.interpretation.get("intent") if isinstance(preview.interpretation.get("intent"), dict) else {}
    preview_clarification = (
        preview.interpretation.get("clarification") if isinstance(preview.interpretation.get("clarification"), dict) else None
    )
    preview_trace = preview_intent.get("decision_trace") if isinstance(preview_intent.get("decision_trace"), dict) else {}
    intent_ai_trace = preview_trace.get("intent_ai") if isinstance(preview_trace.get("intent_ai"), dict) else {}
    start_checks = {
        "mode": start.mode,
        "submode": start.submode,
        "requires_preview": start.requires_preview,
        "can_proceed": start.can_proceed,
        "intent_kind": start.intent.get("kind"),
        "intent_action": start.intent.get("action"),
        "intent_status": start.intent.get("status"),
    }
    preview_checks = {
        "action": preview.action,
        "status": preview.status,
        "ready_to_save": preview.ready_to_save,
        "recommended_next_tool": preview.interpretation.get("recommended_next_tool"),
        "plan": [step.action for step in preview.plan],
    }
    for key, actual in start_checks.items():
        compare_expected(errors, f"start.{key}", actual, expected_start.get(key))
    if "clarification_reason" in expected_start:
        reason = start_clarification.get("reason") if isinstance(start_clarification, dict) else None
        compare_expected(errors, "start.clarification_reason", reason, expected_start.get("clarification_reason"))
    if "context_clarification_reason" in expected_start:
        reason = context_clarification.get("reason") if isinstance(context_clarification, dict) else None
        compare_expected(
            errors,
            "start.context_clarification_reason",
            reason,
            expected_start.get("context_clarification_reason"),
        )
    for key, actual in preview_checks.items():
        compare_expected(errors, f"preview.{key}", actual, expected_preview.get(key))
    for expected in expected_preview.get("errors_contains", []):
        if not any(str(expected) in error for error in preview.errors):
            errors.append(f"preview.errors missing text: {expected}")
    for expected in expected_preview.get("missing_contains", []):
        if not any(str(expected) in item for item in preview.missing_required):
            errors.append(f"preview.missing_required missing text: {expected}")
    if "clarification_reason" in expected_preview:
        reason = preview_clarification.get("reason") if isinstance(preview_clarification, dict) else None
        compare_expected(errors, "preview.clarification_reason", reason, expected_preview.get("clarification_reason"))
    if "clarification_choice_count" in expected_preview:
        choices = preview_clarification.get("choices") if isinstance(preview_clarification, dict) else []
        count = len(choices) if isinstance(choices, list) else 0
        compare_expected(errors, "preview.clarification_choice_count", count, expected_preview.get("clarification_choice_count"))
    for expected in expected_preview.get("clarification_question_contains", []):
        question = str(preview_clarification.get("question") or "") if isinstance(preview_clarification, dict) else ""
        if str(expected) not in question:
            errors.append(f"preview.clarification.question missing text: {expected}")
    compare_expected_outcome(errors, "preview.rules_outcome", intent_ai_trace.get("rules_outcome"), expected_preview.get("rules_outcome"))
    compare_expected_outcome(
        errors,
        "preview.consensus_outcome",
        intent_ai_trace.get("consensus_outcome"),
        expected_preview.get("consensus_outcome"),
    )
    compare_expected_outcome(
        errors,
        "preview.selected_outcome",
        intent_ai_trace.get("selected_outcome"),
        expected_preview.get("selected_outcome"),
    )
    return EvalCaseResult(
        id=case_id,
        ok=not errors,
        errors=tuple(errors),
        metrics={
            "text": text,
            "actual_blocked": (not start.can_proceed) or preview.status == "blocked",
            "actual_ready_to_save": preview.ready_to_save,
            "expected_blocked": (expected_start.get("can_proceed") is False) or expected_preview.get("status") == "blocked",
            "start_ok": not any(error.startswith("start.") for error in errors),
            "preview_ok": not any(error.startswith("preview.") for error in errors),
            "intent_ai_mode": intent_ai_trace.get("mode"),
            "legacy_rule_route": compact_trace_mapping(preview_trace.get("legacy_rule_route")),
            "rules_outcome": compact_trace_mapping(intent_ai_trace.get("rules_outcome")),
            "consensus_outcome": compact_trace_mapping(intent_ai_trace.get("consensus_outcome")),
            "selected_outcome": compact_trace_mapping(intent_ai_trace.get("selected_outcome")),
            "final_intent": compact_trace_mapping(preview_trace.get("final_intent")),
            "consensus": compact_trace_mapping(preview_trace.get("consensus")),
            "start_clarification": compact_clarification(start_clarification),
            "context_clarification": compact_clarification(context_clarification),
            "clarification": compact_clarification(preview_clarification),
        },
    )


def evaluate_consensus_commit_case(runtime: GMRuntime, case: dict[str, Any]) -> EvalCaseResult:
    case_id = str(case.get("id") or "unknown")
    text = str(case.get("text") or "")
    errors: list[str] = []
    runtime_options = intent_runtime_options(case)
    expected_preview = case.get("preview") if isinstance(case.get("preview"), dict) else {}
    expected_validate = case.get("validate") if isinstance(case.get("validate"), dict) else {}
    expected_commit = case.get("commit") if isinstance(case.get("commit"), dict) else {}
    before_state = runtime_state(runtime)

    start = runtime.start_turn(text, **runtime_options)
    preview = runtime.preview_from_text(text, **runtime_options)
    preview_intent = preview.interpretation.get("intent") if isinstance(preview.interpretation.get("intent"), dict) else {}
    preview_trace = preview_intent.get("decision_trace") if isinstance(preview_intent.get("decision_trace"), dict) else {}
    intent_ai_trace = preview_trace.get("intent_ai") if isinstance(preview_trace.get("intent_ai"), dict) else {}
    selected = intent_ai_trace.get("selected_outcome") if isinstance(intent_ai_trace.get("selected_outcome"), dict) else {}

    preview_checks = {
        "status": preview.status,
        "ready_to_save": preview.ready_to_save,
        "action": preview.action,
        "selected_source": selected.get("source"),
    }
    for key, actual in preview_checks.items():
        compare_expected_if_present(errors, f"preview.{key}", actual, expected_preview)

    validation_ok: bool | None = None
    validation_errors: tuple[str, ...] = ()
    commit_ok: bool | None = None
    commit_errors: tuple[str, ...] = ()
    commit_result: dict[str, Any] | None = None
    commit_attempted = bool(preview.ready_to_save and preview.delta_draft and preview.turn_proposal)
    expected_attempt = expected_commit.get("attempted")
    if expected_attempt is not None and commit_attempted != bool(expected_attempt):
        errors.append(f"commit.attempted: expected {bool(expected_attempt)!r}, got {commit_attempted!r}")

    if commit_attempted:
        validation = runtime.validate_delta(preview.delta_draft or {})
        validation_ok = validation.ok
        validation_errors = validation.errors
        compare_expected_if_present(errors, "validate.ok", validation_ok, expected_validate)
        if validation.ok:
            try:
                committed = runtime.commit_turn(preview.delta_draft or {}, turn_proposal=preview.turn_proposal, backup=False)
                commit_ok = committed.ok
                commit_result = committed.to_dict()
            except Exception as exc:
                commit_ok = False
                commit_errors = (str(exc),)
        else:
            commit_ok = False
        compare_expected_if_present(errors, "commit.ok", commit_ok, expected_commit)
    else:
        compare_expected_if_present(errors, "validate.ok", validation_ok, expected_validate)
        compare_expected_if_present(errors, "commit.ok", commit_ok, expected_commit)

    after_state = runtime_state(runtime)
    expected_state = expected_commit.get("state") if isinstance(expected_commit.get("state"), dict) else {}
    for key, expected_value in expected_state.items():
        compare_expected(errors, f"commit.state.{key}", after_state.get(key), expected_value)
    if expected_commit.get("state_changed") is not None:
        compare_expected(errors, "commit.state_changed", before_state != after_state, bool(expected_commit.get("state_changed")))

    return EvalCaseResult(
        id=case_id,
        ok=not errors,
        errors=tuple(errors),
        metrics={
            "text": text,
            "start_can_proceed": start.can_proceed,
            "preview_status": preview.status,
            "preview_ready_to_save": preview.ready_to_save,
            "selected_outcome": compact_trace_mapping(selected),
            "validation_ok": validation_ok,
            "validation_errors": list(validation_errors),
            "commit_attempted": commit_attempted,
            "commit_ok": commit_ok,
            "commit_errors": list(commit_errors),
            "commit_result": compact_commit_result(commit_result),
            "before_state": before_state,
            "after_state": after_state,
        },
    )


def evaluate_real_canary_case(runtime: GMRuntime, case: dict[str, Any]) -> EvalCaseResult:
    case_id = str(case.get("id") or "unknown")
    text = str(case.get("text") or "")
    runtime_options = real_canary_runtime_options(case)
    metrics: dict[str, Any] = {
        "text": text,
        "provider": runtime_options.get("intent_provider"),
        "model": runtime_options.get("intent_model"),
        "expectation_met": None,
        "expectation_errors": [],
        "canary_ok": False,
        "json_ok": False,
        "helper_status": "not_run",
        "helper_error": None,
        "elapsed_ms": 0,
        "selected_outcome": None,
        "clarification": None,
        "preview_status": None,
        "ready_to_save": False,
    }
    try:
        preview = runtime.preview_from_text(text, **runtime_options)
        preview_intent = preview.interpretation.get("intent") if isinstance(preview.interpretation.get("intent"), dict) else {}
        preview_trace = preview_intent.get("decision_trace") if isinstance(preview_intent.get("decision_trace"), dict) else {}
        intent_ai_trace = preview_trace.get("intent_ai") if isinstance(preview_trace.get("intent_ai"), dict) else {}
        helper = intent_ai_trace.get("internal_helper") if isinstance(intent_ai_trace.get("internal_helper"), dict) else {}
        selected = intent_ai_trace.get("selected_outcome") if isinstance(intent_ai_trace.get("selected_outcome"), dict) else {}
        clarification = preview.interpretation.get("clarification") if isinstance(preview.interpretation.get("clarification"), dict) else None
        metrics.update(
            {
                "canary_ok": helper.get("status") == "ok",
                "json_ok": helper.get("status") == "ok",
                "helper_status": helper.get("status") or "unknown",
                "helper_error": helper.get("error"),
                "elapsed_ms": int(helper.get("elapsed_ms") or 0),
                "selected_outcome": compact_trace_mapping(selected),
                "clarification": compact_clarification(clarification),
                "preview_status": preview.status,
                "ready_to_save": preview.ready_to_save,
            }
        )
    except Exception as exc:
        metrics["helper_status"] = "exception"
        metrics["helper_error"] = str(exc)
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    expectation_errors = real_canary_expectation_errors(metrics, expected)
    metrics["expectation_errors"] = expectation_errors
    metrics["expectation_met"] = (not expectation_errors) if expected else None
    return EvalCaseResult(
        id=case_id,
        ok=True,
        errors=(),
        metrics=metrics,
    )


def evaluate_clarification_loop(runtime: GMRuntime, loop: dict[str, Any]) -> EvalCaseResult:
    loop_id = str(loop.get("id") or "unknown")
    raw_steps = loop.get("steps") if isinstance(loop.get("steps"), list) else []
    expected = loop.get("expected") if isinstance(loop.get("expected"), dict) else {}
    errors: list[str] = []
    step_results: list[EvalCaseResult] = []

    if not raw_steps:
        errors.append("loop.steps: expected at least one step")

    for index, raw_step in enumerate(raw_steps):
        step = dict(raw_step) if isinstance(raw_step, dict) else {}
        step_id = str(step.get("id") or f"step_{index + 1}")
        step["id"] = f"{loop_id}.{step_id}"
        result = evaluate_intent_case(runtime, step)
        step_results.append(result)
        for error in result.errors:
            errors.append(f"{step_id}: {error}")

    clarification_reasons = [
        step_clarification_reason(result)
        for result in step_results
    ]
    final = step_results[-1] if step_results else None
    final_selected = final.metrics.get("selected_outcome") if final else None
    final_clarification = final.metrics.get("clarification") if final else None
    final_action = final_selected.get("action") if isinstance(final_selected, dict) else None
    final_source = final_selected.get("source") if isinstance(final_selected, dict) else None
    intent_resolved = (
        final is not None
        and final.ok
        and final_clarification is None
        and bool(final_action)
        and final_source == "ai_consensus"
    )
    final_status = final_selected.get("status") if isinstance(final_selected, dict) else None
    final_ready_to_save = final.metrics.get("actual_ready_to_save") if final else None
    loop_closed = intent_resolved and final_status == "ready" and final_ready_to_save is True

    compare_expected_if_present(errors, "expected.step_count", len(step_results), expected)
    compare_expected_if_present(errors, "expected.clarification_reasons", clarification_reasons, expected)
    compare_expected_if_present(errors, "expected.intent_resolved", intent_resolved, expected)
    compare_expected_if_present(errors, "expected.closed", loop_closed, expected)
    compare_expected_if_present(errors, "expected.final_action", final_action, expected)
    compare_expected_if_present(errors, "expected.final_status", final_status, expected)
    compare_expected_if_present(errors, "expected.final_ready_to_save", final_ready_to_save, expected)
    compare_expected_if_present(errors, "expected.final_selected_source", final_source, expected)

    return EvalCaseResult(
        id=loop_id,
        ok=not errors,
        errors=tuple(errors),
        metrics={
            "step_count": len(step_results),
            "intent_resolved": intent_resolved,
            "closed": loop_closed,
            "clarification_reasons": clarification_reasons,
            "final_selected_outcome": compact_trace_mapping(final_selected),
            "final_clarification": final_clarification,
            "final_ready_to_save": final_ready_to_save,
            "steps": [
                {
                    "id": result.id,
                    "ok": result.ok,
                    "selected_outcome": result.metrics.get("selected_outcome"),
                    "clarification": result.metrics.get("clarification"),
                    "ready_to_save": result.metrics.get("actual_ready_to_save"),
                    "errors": list(result.errors),
                }
                for result in step_results
            ],
        },
    )


def step_clarification_reason(result: EvalCaseResult) -> str:
    clarification = result.metrics.get("clarification")
    if not isinstance(clarification, dict):
        return "none"
    return str(clarification.get("reason") or "none")


def compare_expected_if_present(errors: list[str], key: str, actual: Any, expected: dict[str, Any]) -> None:
    field = key.rsplit(".", 1)[-1]
    if field in expected:
        compare_expected(errors, key, actual, expected.get(field))


def intent_runtime_options(case: dict[str, Any]) -> dict[str, Any]:
    raw_options = case.get("runtime") if isinstance(case.get("runtime"), dict) else {}
    options: dict[str, Any] = {}
    for key in (
        "intent_ai",
        "intent_backend",
        "intent_model",
        "intent_provider",
        "intent_timeout",
        "intent_base_url",
        "intent_api_key_env",
        "intent_fallback_backend",
    ):
        if key in raw_options:
            options[key] = raw_options[key]
    if "intent_backend" not in options and case_uses_fake_internal_review(case):
        options["intent_backend"] = "hermes_z"
    external = raw_options.get("external_intent_candidate")
    if isinstance(external, dict):
        options["external_intent_candidate"] = external
    return options


def real_canary_runtime_options(case: dict[str, Any]) -> dict[str, Any]:
    options = intent_runtime_options(case)
    options.setdefault("intent_ai", "consensus")
    options.setdefault("intent_provider", DEFAULT_AI_PROVIDER)
    options.setdefault("intent_model", DEFAULT_AI_MODEL)
    options.setdefault("intent_timeout", 20)
    if "intent_backend" not in options and eval_hermes_backend_available(options.get("intent_provider")):
        options["intent_backend"] = "hermes_z"
    return options


def case_uses_fake_internal_review(case: dict[str, Any]) -> bool:
    return isinstance(case.get("fake_internal_review"), dict) or bool(case.get("fake_helper_error"))


def eval_hermes_backend_available(provider: Any) -> bool:
    if direct_api_key_available(provider):
        return False
    return shutil.which("hermes") is not None


def direct_api_key_available(provider: Any) -> bool:
    provider_key = str(provider or DEFAULT_AI_PROVIDER).strip().lower()
    env_names = {
        "deepseek": ("DEEPSEEK_API_KEY", "AIGM_DEEPSEEK_API_KEY", "AIGM_AI_API_KEY"),
        "openai": ("OPENAI_API_KEY", "AIGM_OPENAI_API_KEY", "AIGM_AI_API_KEY"),
    }.get(provider_key, (f"{provider_key.upper()}_API_KEY", "AIGM_AI_API_KEY"))
    return any(bool(os.environ.get(name)) for name in env_names)


def real_canary_expectation_errors(metrics: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not expected:
        return errors
    selected = metrics.get("selected_outcome") if isinstance(metrics.get("selected_outcome"), dict) else {}
    clarification = metrics.get("clarification") if isinstance(metrics.get("clarification"), dict) else {}
    checks = {
        "helper_status": metrics.get("helper_status"),
        "selected_source": selected.get("source"),
        "preview_status": metrics.get("preview_status"),
        "action": selected.get("action"),
        "clarification_reason": clarification.get("reason"),
        "ready_to_save": metrics.get("ready_to_save"),
    }
    for key, actual in checks.items():
        if key in expected and actual != expected.get(key):
            errors.append(f"{key}: expected {expected.get(key)!r}, got {actual!r}")
    return errors


def compare_expected_outcome(errors: list[str], key: str, actual: Any, expected: Any) -> None:
    if expected is None:
        return
    if not isinstance(expected, dict):
        errors.append(f"{key}: expected outcome must be an object")
        return
    actual_mapping = actual if isinstance(actual, dict) else {}
    for field, expected_value in expected.items():
        compare_expected(errors, f"{key}.{field}", actual_mapping.get(field), expected_value)


def compact_trace_mapping(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = (
        "mode",
        "submode",
        "action",
        "source",
        "status",
        "router",
        "enabled",
        "binding_status",
        "reason",
    )
    return {key: value[key] for key in keys if key in value}


def compact_clarification(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    choices = value.get("choices") if isinstance(value.get("choices"), list) else []
    return {
        "reason": value.get("reason"),
        "suggested_next_tool": value.get("suggested_next_tool"),
        "choice_count": len(choices),
        "missing_slots": list(value.get("missing_slots") or []),
    }


def run_mcp_transcript_eval(transcripts_path: str | Path) -> EvalSuiteResult:
    transcripts = load_yaml_mapping(transcripts_path).get("transcripts", [])
    if not isinstance(transcripts, list):
        raise ValueError("MCP transcript fixture must contain a transcripts array")
    results: list[EvalCaseResult] = []
    misuse_codes = {
        "forbidden_normal_play_tool",
        "unknown_default_mcp_tool",
        "natural_language_preview_action_first",
        "clarification_not_asked",
        "clarification_self_selected",
        "tool_after_clarification_without_player_answer",
        "commit_after_clarification_without_player_answer",
        "tool_after_clarification_answer_without_repreview",
        "commit_after_clarification_answer_without_repreview",
        "clarification_stale_repreview",
        "clarification_answer_without_repreview",
        "commit_without_validation",
        "commit_without_preview",
        "commit_after_unready_preview",
        "commit_after_failed_validation",
        "commit_without_turn_proposal",
    }
    for raw_transcript in transcripts:
        transcript = raw_transcript if isinstance(raw_transcript, dict) else {}
        transcript_id = str(transcript.get("id") or "unknown")
        findings = validate_external_agent_transcript(transcript)
        actual_codes = [finding.code for finding in findings]
        expected_codes = list(transcript.get("expected_findings") or [])
        errors = [] if actual_codes == expected_codes else [f"expected {expected_codes}, got {actual_codes}"]
        results.append(
            EvalCaseResult(
                id=transcript_id,
                ok=not errors,
                errors=tuple(errors),
                metrics={
                    "finding_codes": actual_codes,
                    "expected_finding_codes": expected_codes,
                    "tool_misuse": any(code in misuse_codes for code in actual_codes),
                },
            )
        )
    metrics = summarize_mcp_results(results)
    return EvalSuiteResult(
        suite="mcp",
        ok=all(case.ok for case in results),
        metrics=metrics,
        cases=tuple(results),
    )


def compare_expected(errors: list[str], key: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{key}: expected {expected!r}, got {actual!r}")


def summarize_intent_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.ok)
    start_passed = sum(1 for result in results if result.metrics.get("start_ok"))
    preview_passed = sum(1 for result in results if result.metrics.get("preview_ok"))
    actual_blocked = sum(1 for result in results if result.metrics.get("actual_blocked"))
    ready_to_save = sum(1 for result in results if result.metrics.get("actual_ready_to_save"))
    selected_sources: dict[str, int] = {}
    clarification_reasons: dict[str, int] = {}
    for result in results:
        selected = result.metrics.get("selected_outcome")
        source = selected.get("source") if isinstance(selected, dict) else None
        key = str(source or "none")
        selected_sources[key] = selected_sources.get(key, 0) + 1
        clarification = result.metrics.get("clarification")
        reason = clarification.get("reason") if isinstance(clarification, dict) else None
        reason_key = str(reason or "none")
        clarification_reasons[reason_key] = clarification_reasons.get(reason_key, 0) + 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": ratio(passed, total),
        "intent_accuracy": ratio(start_passed, total),
        "preview_accuracy": ratio(preview_passed, total),
        "block_rate": ratio(actual_blocked, total),
        "ready_to_save_rate": ratio(ready_to_save, total),
        "selected_outcome_sources": selected_sources,
        "clarification_reasons": clarification_reasons,
    }


def summarize_mcp_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.ok)
    misuse = sum(1 for result in results if result.metrics.get("tool_misuse"))
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": ratio(passed, total),
        "tool_misuse_rate": ratio(misuse, total),
    }


def summarize_clarification_loop_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.ok)
    closed = sum(1 for result in results if result.metrics.get("closed"))
    intent_resolved = sum(1 for result in results if result.metrics.get("intent_resolved"))
    final_sources: dict[str, int] = {}
    sequence_counts: dict[str, int] = {}
    for result in results:
        selected = result.metrics.get("final_selected_outcome")
        source = selected.get("source") if isinstance(selected, dict) else None
        source_key = str(source or "none")
        final_sources[source_key] = final_sources.get(source_key, 0) + 1
        sequence = " -> ".join(str(item) for item in result.metrics.get("clarification_reasons", []))
        sequence_counts[sequence or "none"] = sequence_counts.get(sequence or "none", 0) + 1
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": ratio(passed, total),
        "intent_resolved_rate": ratio(intent_resolved, total),
        "closed_rate": ratio(closed, total),
        "final_selected_outcome_sources": final_sources,
        "clarification_sequences": sequence_counts,
    }


def summarize_consensus_commit_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.ok)
    preview_ready = sum(1 for result in results if result.metrics.get("preview_ready_to_save"))
    validation_ok = sum(1 for result in results if result.metrics.get("validation_ok") is True)
    commit_attempted = sum(1 for result in results if result.metrics.get("commit_attempted"))
    commit_ok = sum(1 for result in results if result.metrics.get("commit_ok") is True)
    state_changed = sum(1 for result in results if result.metrics.get("before_state") != result.metrics.get("after_state"))
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "accuracy": ratio(passed, total),
        "preview_ready_rate": ratio(preview_ready, total),
        "validation_ok_rate": ratio(validation_ok, total),
        "commit_attempt_rate": ratio(commit_attempted, total),
        "commit_ok_rate": ratio(commit_ok, total),
        "state_changed_rate": ratio(state_changed, total),
    }


def summarize_real_canary_results(results: list[EvalCaseResult]) -> dict[str, Any]:
    total = len(results)
    canary_ok = sum(1 for result in results if result.metrics.get("canary_ok"))
    json_ok = sum(1 for result in results if result.metrics.get("json_ok"))
    expected_total = sum(1 for result in results if result.metrics.get("expectation_met") is not None)
    expectation_met = sum(1 for result in results if result.metrics.get("expectation_met") is True)
    expectation_miss = expected_total - expectation_met
    clarifications = sum(1 for result in results if result.metrics.get("clarification") is not None)
    ready_to_save = sum(1 for result in results if result.metrics.get("ready_to_save") is True)
    consensus = sum(
        1
        for result in results
        if isinstance(result.metrics.get("selected_outcome"), dict)
        and result.metrics["selected_outcome"].get("source") == "ai_consensus"
    )
    elapsed_values = [int(result.metrics.get("elapsed_ms") or 0) for result in results if result.metrics.get("elapsed_ms")]
    avg_elapsed = round(sum(elapsed_values) / len(elapsed_values), 1) if elapsed_values else 0.0
    over_budget = sum(1 for value in elapsed_values if value > INTENT_LATENCY_BUDGET_MS)
    statuses: dict[str, int] = {}
    preview_statuses: dict[str, int] = {}
    selected_sources: dict[str, int] = {}
    for result in results:
        status = str(result.metrics.get("helper_status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        preview_status = str(result.metrics.get("preview_status") or "unknown")
        preview_statuses[preview_status] = preview_statuses.get(preview_status, 0) + 1
        selected = result.metrics.get("selected_outcome")
        source = selected.get("source") if isinstance(selected, dict) else None
        source_key = str(source or "none")
        selected_sources[source_key] = selected_sources.get(source_key, 0) + 1
    return {
        "total": total,
        "passed": total,
        "failed": 0,
        "accuracy": 1.0 if total else 0.0,
        "canary_ok_rate": ratio(canary_ok, total),
        "json_ok_rate": ratio(json_ok, total),
        "expectation_met_rate": ratio(expectation_met, expected_total),
        "expectation_miss_count": expectation_miss,
        "clarification_rate": ratio(clarifications, total),
        "ready_to_save_rate": ratio(ready_to_save, total),
        "consensus_accept_rate": ratio(consensus, total),
        "avg_elapsed_ms": avg_elapsed,
        "timeout_budget_ms": INTENT_LATENCY_BUDGET_MS,
        "over_budget_rate": ratio(over_budget, len(elapsed_values)),
        "latency_min_ms": min(elapsed_values) if elapsed_values else 0,
        "latency_p50_ms": latency_percentile(elapsed_values, 0.50),
        "latency_p90_ms": latency_percentile(elapsed_values, 0.90),
        "latency_p95_ms": latency_percentile(elapsed_values, 0.95),
        "latency_max_ms": max(elapsed_values) if elapsed_values else 0,
        "helper_statuses": statuses,
        "preview_statuses": preview_statuses,
        "selected_outcome_sources": selected_sources,
    }


def aggregate_metrics(suites: tuple[EvalSuiteResult, ...]) -> dict[str, Any]:
    total = sum(int(suite.metrics.get("total", 0)) for suite in suites)
    passed = sum(int(suite.metrics.get("passed", 0)) for suite in suites)
    failed = sum(int(suite.metrics.get("failed", 0)) for suite in suites)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "accuracy": ratio(passed, total),
    }


def ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def latency_percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = int((len(ordered) * fraction) + 0.999999)
    index = max(0, min(len(ordered) - 1, rank - 1))
    return float(ordered[index])


def runtime_state(runtime: GMRuntime) -> dict[str, Any]:
    with connect(runtime.campaign) as conn:
        rows = conn.execute(
            "select key, value from meta where key in ('current_turn_id', 'current_location_id', 'current_game_day', 'current_time_block')"
        ).fetchall()
    return {str(row["key"]): row["value"] for row in rows}


def compact_commit_result(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        key: value.get(key)
        for key in ("ok", "turn_id", "write_status", "projection_status")
        if key in value
    }


def render_eval_report(result: EvalRunResult) -> str:
    data = result.to_dict()
    lines = [
        "# Eval Report",
        "",
        f"- status: `{'OK' if result.ok else 'FAILED'}`",
        f"- total: `{data['metrics']['total']}`",
        f"- passed: `{data['metrics']['passed']}`",
        f"- failed: `{data['metrics']['failed']}`",
        f"- accuracy: `{data['metrics']['accuracy']}`",
        "",
    ]
    for suite in result.suites:
        lines.extend(
            [
                f"## {suite.suite}",
                "",
                f"- status: `{'OK' if suite.ok else 'FAILED'}`",
                f"- total: `{suite.metrics['total']}`",
                f"- accuracy: `{suite.metrics['accuracy']}`",
            ]
        )
        for key in (
            "intent_accuracy",
            "preview_accuracy",
            "block_rate",
            "ready_to_save_rate",
            "preview_ready_rate",
            "validation_ok_rate",
            "commit_attempt_rate",
            "commit_ok_rate",
            "state_changed_rate",
            "canary_ok_rate",
            "json_ok_rate",
            "expectation_met_rate",
            "expectation_miss_count",
            "clarification_rate",
            "consensus_accept_rate",
            "avg_elapsed_ms",
            "timeout_budget_ms",
            "over_budget_rate",
            "latency_min_ms",
            "latency_p50_ms",
            "latency_p90_ms",
            "latency_p95_ms",
            "latency_max_ms",
            "intent_resolved_rate",
            "closed_rate",
            "tool_misuse_rate",
        ):
            if key in suite.metrics:
                lines.append(f"- {key}: `{suite.metrics[key]}`")
        if "selected_outcome_sources" in suite.metrics:
            lines.append(f"- selected_outcome_sources: `{suite.metrics['selected_outcome_sources']}`")
        if "clarification_reasons" in suite.metrics:
            lines.append(f"- clarification_reasons: `{suite.metrics['clarification_reasons']}`")
        if "final_selected_outcome_sources" in suite.metrics:
            lines.append(f"- final_selected_outcome_sources: `{suite.metrics['final_selected_outcome_sources']}`")
        if "clarification_sequences" in suite.metrics:
            lines.append(f"- clarification_sequences: `{suite.metrics['clarification_sequences']}`")
        if "helper_statuses" in suite.metrics:
            lines.append(f"- helper_statuses: `{suite.metrics['helper_statuses']}`")
        if "preview_statuses" in suite.metrics:
            lines.append(f"- preview_statuses: `{suite.metrics['preview_statuses']}`")
        expectation_misses = [case for case in suite.cases if case.metrics.get("expectation_met") is False]
        if expectation_misses:
            lines.append(f"- warning: `{len(expectation_misses)} non-gating canary expectation miss(es)`")
            lines.extend(
                [
                    "",
                    "| Case | Selected Outcome | Clarification | Expectation Errors |",
                    "|------|------------------|---------------|--------------------|",
                ]
            )
            for case in expectation_misses:
                selected = metric_summary(case.metrics.get("selected_outcome"), ("source", "mode", "submode", "action", "status"))
                clarification = metric_summary(case.metrics.get("clarification"), ("reason", "choice_count", "missing_slots"))
                errors = "; ".join(str(item) for item in case.metrics.get("expectation_errors", []))
                lines.append(
                    f"| `{case.id}` | {markdown_cell(selected)} | {markdown_cell(clarification)} | {markdown_cell(errors)} |"
                )
        failed = [case for case in suite.cases if not case.ok]
        if failed:
            lines.extend(["", "| Case | Selected Outcome | Clarification | Errors |", "|------|------------------|---------------|--------|"])
            for case in failed:
                selected = metric_summary(case.metrics.get("selected_outcome"), ("source", "mode", "submode", "action", "status"))
                clarification = metric_summary(case.metrics.get("clarification"), ("reason", "choice_count", "missing_slots"))
                lines.append(
                    f"| `{case.id}` | {markdown_cell(selected)} | {markdown_cell(clarification)} | {markdown_cell('; '.join(case.errors))} |"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def metric_summary(value: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(value, dict):
        return "-"
    parts: list[str] = []
    for key in keys:
        if key not in value:
            continue
        item = value[key]
        if item is None or item == []:
            continue
        parts.append(f"{key}={item}")
    return ", ".join(parts) if parts else "-"


def markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def load_yaml_mapping(path: str | Path | Any) -> dict[str, Any]:
    if isinstance(path, str | Path):
        text = Path(path).expanduser().read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def loop_step_cases(loops: list[Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw_loop in loops:
        loop = raw_loop if isinstance(raw_loop, dict) else {}
        steps = loop.get("steps") if isinstance(loop.get("steps"), list) else []
        for raw_step in steps:
            if isinstance(raw_step, dict):
                cases.append(raw_step)
    return cases


class prepared_campaign:
    def __init__(self, campaign_dir: str | Path | None) -> None:
        self.campaign_dir = Path(campaign_dir).expanduser().resolve() if campaign_dir else None
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path:
        if self.campaign_dir is not None:
            self.tmp = tempfile.TemporaryDirectory()
            self.path = Path(self.tmp.name) / "campaign"
            shutil.copytree(self.campaign_dir, self.path)
            init_database(load_campaign(self.path), force=True)
            return self.path
        self.tmp = tempfile.TemporaryDirectory()
        self.path = copy_packaged_example("v1_minimal_adventure", Path(self.tmp.name) / "campaign", force=True)
        init_database(load_campaign(self.path), force=True)
        return self.path

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        if self.tmp is not None:
            self.tmp.cleanup()
        return False


class fake_internal_intent_reviews:
    def __init__(self, cases: list[Any]) -> None:
        self.cases = cases
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.old_path = ""

    def __enter__(self) -> None:
        mapping: dict[str, dict[str, Any]] = {}
        for raw_case in self.cases:
            case = raw_case if isinstance(raw_case, dict) else {}
            text = normalize_fake_review_text(case.get("text"))
            if not text:
                continue
            if case.get("fake_helper_error"):
                mapping[text] = {"error": str(case.get("fake_helper_error") or "fake helper error")}
                continue
            review = case.get("fake_internal_review")
            if isinstance(review, dict):
                mapping[text] = {"output": review}
        self.tmp = tempfile.TemporaryDirectory()
        bin_dir = Path(self.tmp.name)
        hermes = bin_dir / "hermes"
        script = "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, re, sys, unicodedata",
                f"mapping = {json.dumps(mapping, ensure_ascii=False, sort_keys=True)!r}",
                "data = json.loads(mapping)",
                "prompt = ''",
                "for index, arg in enumerate(sys.argv):",
                "    if arg == '-z' and index + 1 < len(sys.argv):",
                "        prompt = sys.argv[index + 1]",
                "        break",
                "match = re.search(r'玩家原文：([^\\n]+)', prompt)",
                "text = unicodedata.normalize('NFKC', match.group(1)).strip() if match else ''",
                "item = data.get(text)",
                "if item is None:",
                "    sys.stderr.write(f'no fake internal review for {text}\\n')",
                "    sys.exit(3)",
                "if 'error' in item:",
                "    sys.stderr.write(str(item['error']) + '\\n')",
                "    sys.exit(2)",
                "print(json.dumps(item['output'], ensure_ascii=False, sort_keys=True))",
            ]
        )
        hermes.write_text(script + "\n", encoding="utf-8")
        hermes.chmod(0o755)
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{self.old_path}"

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        os.environ["PATH"] = self.old_path
        if self.tmp is not None:
            self.tmp.cleanup()
        return False


def normalize_fake_review_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()
