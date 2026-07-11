from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

from rpg_engine.ai.advisory import (
    ResidentAIAdvisory,
    resident_ai_advisory_to_maintenance_dict,
    resident_ai_advisory_to_player_dict,
)
from rpg_engine.ai.advisory_adapters import (
    adapt_internal_intent_review_advisory,
    adapt_state_audit_progress_advisory,
)
from rpg_engine.ai.provider import AIHelperResult
from rpg_engine.ai.schemas import StateAuditResult
from rpg_engine.ai.state_audit import merge_state_audit_results
from rpg_engine.ai_intent.router import AIIntentRouter
from rpg_engine.campaign import load_campaign
from rpg_engine.db import connect, upsert_clock, upsert_entity
from rpg_engine.preflight_cache import PreflightLookupResult
from rpg_engine.validation_pipeline import (
    MAINTENANCE_ADVISORY_PROFILES,
    ValidationReport,
    ValidationStageResult,
    stable_delta_digest,
    validate_delta_schema_stage,
    validate_state_audit_stage,
)

from tests.helpers import copy_initialized_minimal


PRIVATE_CANARY = "RAW_PROMPT_PRIVATE_DELTA_PROVIDER_CANARY"
ADAPTER_EXCEPTION_CANARY = "ADAPTER_EXCEPTION_MUST_NOT_LEAK"


def helper_result(
    *,
    status: str = "ok",
    task: str = "internal_intent_review",
    confidence: object = "high",
    advisory: object = True,
    no_direct_writes: object = True,
) -> AIHelperResult:
    parsed = {
        "kind": "single",
        "mode": "action",
        "action": "social",
        "slots": {"npc": PRIVATE_CANARY},
        "plan": [],
        "confidence": confidence,
        "missing_slots": [],
        "needs_confirmation": [],
        "safety_flags": [],
        "reason": PRIVATE_CANARY,
        "agreement_with_external": "agree",
        "disagreements": [PRIVATE_CANARY],
        "external_candidate_quality": "usable",
        "source_user_text": PRIVATE_CANARY,
    }
    return AIHelperResult(
        task=task,
        backend="direct",
        provider=PRIVATE_CANARY,
        model=PRIVATE_CANARY,
        status=status,
        parsed=parsed if status == "ok" else None,
        raw_text=PRIVATE_CANARY,
        error=PRIVATE_CANARY if status != "ok" else None,
        advisory=advisory,  # type: ignore[arg-type]
        no_direct_writes=no_direct_writes,  # type: ignore[arg-type]
        audit={"output_summary": PRIVATE_CANARY},
    )


def state_audit_result(
    *,
    advisory: object = True,
    no_direct_writes: object = True,
) -> StateAuditResult:
    return StateAuditResult(
        ok=False,
        risk="high",
        findings=[{"message": PRIVATE_CANARY}],
        missing_structured_changes=[{"raw_delta": PRIVATE_CANARY}],
        requires_human_review=True,
        ai_status="ok",
        warnings=[PRIVATE_CANARY],
        advisory=advisory,  # type: ignore[arg-type]
        no_direct_writes=no_direct_writes,  # type: ignore[arg-type]
        audit={"provider_body": PRIVATE_CANARY},
    )


def expected_digest(payload: dict[str, object]) -> str:
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def validated_delta_stage(
    conn: sqlite3.Connection,
    delta: dict[str, object],
    *,
    profile: str = "maintenance_commit",
) -> ValidationStageResult:
    return validate_delta_schema_stage(conn, profile, delta)  # type: ignore[arg-type]


def memory_clock_conn(*clock_ids: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("create table entities (id text primary key, status text not null default 'active')")
    conn.execute("create table clocks (entity_id text primary key)")
    conn.executemany("insert into entities (id, status) values (?, 'active')", ((clock_id,) for clock_id in clock_ids))
    conn.executemany("insert into clocks (entity_id) values (?)", ((clock_id,) for clock_id in clock_ids))
    conn.commit()
    return conn


def complete_clock_delta(tick_clocks: list[dict[str, object]] | None) -> dict[str, object]:
    delta: dict[str, object] = {
        "user_text": "advance clock",
        "intent": "clock",
        "changed": True,
        "summary": "Clock advanced.",
        "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
    }
    if tick_clocks is not None:
        delta["tick_clocks"] = tick_clocks
    return delta


class ResidentAIAdvisoryAdapterTests(unittest.TestCase):
    def test_intent_adapter_builds_strict_companion_without_helper_payload(self) -> None:
        envelope = adapt_internal_intent_review_advisory(
            helper_result(),
            bound_target_ids=(
                "char:advisor",
                "rel:advisor-friend",
                "clock:advisor:phase-1",
                "rule:advisor",
                "world:advisor",
                "char:advisor",
            ),
            visibility_mode="player",
        )

        self.assertIs(type(envelope), ResidentAIAdvisory)
        assert envelope is not None
        value = resident_ai_advisory_to_maintenance_dict(envelope)
        digest = expected_digest(
            {
                "adapter": "internal_intent_review",
                "confidence": "high",
                "targets": [
                    "char:advisor",
                    "rel:advisor-friend",
                    "clock:advisor:phase-1",
                    "rule:advisor",
                    "world:advisor",
                ],
                "visibility_mode": "player",
            }
        )
        self.assertEqual(value["advisory_type"], "intent_recognition")
        self.assertEqual(value["confidence"], 0.9)
        self.assertEqual(value["freshness"], {"status": "unknown", "as_of_turn_id": None, "source_event_ids": []})
        self.assertEqual(value["visibility_mode"], "player")
        self.assertEqual(value["source_assistant"], "internal_intent_review")
        self.assertEqual(value["proposed_next_workflow"], "none")
        self.assertEqual(value["target_ids"], [
            "char:advisor",
            "rel:advisor-friend",
            "clock:advisor:phase-1",
            "rule:advisor",
            "world:advisor",
        ])
        self.assertEqual(
            [(item["kind"], item["ref_id"]) for item in value["evidence"]],
            [
                ("entity", "char:advisor"),
                ("relationship", "rel:advisor-friend"),
                ("progress", "clock:advisor:phase-1"),
                ("rule", "rule:advisor"),
                ("world_setting", "world:advisor"),
            ],
        )
        self.assertEqual(value["provenance"], {
            "trace_id": f"trace:intent-review:{digest}",
            "source_ids": [f"candidate:intent-review:{digest}"],
        })
        self.assertTrue(value["authority"]["advisory_only"])
        self.assertTrue(value["authority"]["no_direct_writes"])
        self.assertTrue(all(not flag for key, flag in value["authority"].items() if key.startswith("can_")))
        self.assertNotIn(PRIVATE_CANARY, json.dumps(value, ensure_ascii=False, sort_keys=True))

    def test_intent_adapter_return_and_rejection_matrix(self) -> None:
        for status in ("off", "error", "timeout"):
            with self.subTest(status=status):
                self.assertIsNone(
                    adapt_internal_intent_review_advisory(
                        helper_result(status=status),
                        bound_target_ids=("char:advisor",),
                        visibility_mode="player",
                    )
                )
        self.assertIsNone(
            adapt_internal_intent_review_advisory(
                helper_result(),
                bound_target_ids=(),
                visibility_mode="player",
            )
        )
        missing = helper_result()
        object.__setattr__(missing, "parsed", None)
        self.assertIsNone(
            adapt_internal_intent_review_advisory(
                missing,
                bound_target_ids=("char:advisor",),
                visibility_mode="player",
            )
        )
        wrong_parsed = helper_result()
        object.__setattr__(wrong_parsed, "parsed", [PRIVATE_CANARY])
        malformed = (
            (object(), ("char:advisor",), "player"),
            (helper_result(task="semantic"), ("char:advisor",), "player"),
            (helper_result(advisory=1), ("char:advisor",), "player"),
            (helper_result(no_direct_writes=1), ("char:advisor",), "player"),
            (helper_result(confidence=True), ("char:advisor",), "player"),
            (wrong_parsed, ("char:advisor",), "player"),
            (helper_result(), ["char:advisor"], "player"),
            (helper_result(), ("proposal:unsafe",), "player"),
            (helper_result(), ("char:\ud800private",), "player"),
            (helper_result(), ("char:advisor",), "unsafe"),
        )
        for result, targets, visibility in malformed:
            with self.subTest(result=type(result).__name__, targets=targets, visibility=visibility):
                with self.assertRaises(ValueError) as raised:
                    adapt_internal_intent_review_advisory(
                        result,  # type: ignore[arg-type]
                        bound_target_ids=targets,  # type: ignore[arg-type]
                        visibility_mode=visibility,
                    )
                self.assertNotIn(PRIVATE_CANARY, str(raised.exception))

    def test_intent_adapter_rejects_forged_or_malformed_source_metadata(self) -> None:
        class ExactLookingString(str):
            pass

        cases: list[tuple[object, object]] = [
            (ExactLookingString("internal_intent_review"), "ok"),
            ("internal_intent_review", ExactLookingString("ok")),
            ("internal_intent_review", 1),
            ("semantic", "off"),
            ("internal_intent_review", "unexpected"),
        ]
        for task, status in cases:
            with self.subTest(task=task, status=status):
                result = helper_result()
                object.__setattr__(result, "task", task)
                object.__setattr__(result, "status", status)
                with self.assertRaises(ValueError) as raised:
                    adapt_internal_intent_review_advisory(
                        result,
                        bound_target_ids=("char:advisor",),
                        visibility_mode="player",
                    )
                self.assertNotIn(PRIVATE_CANARY, str(raised.exception))

        class ExplodingStatus:
            def __eq__(self, _other: object) -> bool:
                raise RuntimeError(PRIVATE_CANARY)

            def __ne__(self, _other: object) -> bool:
                raise RuntimeError(PRIVATE_CANARY)

        hostile = helper_result()
        object.__setattr__(hostile, "status", ExplodingStatus())
        with self.assertRaises(ValueError) as raised:
            adapt_internal_intent_review_advisory(
                hostile,
                bound_target_ids=("char:advisor",),
                visibility_mode="player",
            )
        self.assertNotIn(PRIVATE_CANARY, str(raised.exception))

    def test_intent_adapter_rejects_hostile_or_oversized_parsed_keys(self) -> None:
        class HostileKey(str):
            def __hash__(self) -> int:
                return hash("confidence")

            def __eq__(self, _other: object) -> bool:
                raise RuntimeError(PRIVATE_CANARY)

        hostile = helper_result()
        object.__setattr__(hostile, "parsed", {HostileKey("private"): "high"})
        oversized = helper_result()
        object.__setattr__(
            oversized,
            "parsed",
            {**{f"safe_{index}": index for index in range(64)}, "confidence": "high"},
        )
        for result in (hostile, oversized):
            with self.subTest(result=result):
                with self.assertRaises(ValueError) as raised:
                    adapt_internal_intent_review_advisory(
                        result,
                        bound_target_ids=("char:advisor",),
                        visibility_mode="player",
                    )
                self.assertNotIn(PRIVATE_CANARY, str(raised.exception))

    def test_intent_digest_changes_only_with_contract_metadata(self) -> None:
        first = adapt_internal_intent_review_advisory(
            helper_result(),
            bound_target_ids=("char:first", "char:second"),
            visibility_mode="player",
        )
        changed_sensitive = helper_result()
        changed_sensitive.parsed["reason"] = "DIFFERENT_PRIVATE_VALUE"  # type: ignore[index]
        second = adapt_internal_intent_review_advisory(
            changed_sensitive,
            bound_target_ids=("char:first", "char:second"),
            visibility_mode="player",
        )
        reordered = adapt_internal_intent_review_advisory(
            helper_result(),
            bound_target_ids=("char:second", "char:first"),
            visibility_mode="player",
        )
        assert first is not None and second is not None and reordered is not None
        self.assertEqual(first.provenance, second.provenance)
        self.assertNotEqual(first.provenance, reordered.provenance)

    def test_adapters_do_not_mutate_or_alias_source_collections(self) -> None:
        helper = helper_result()
        helper_before = json.dumps(helper.parsed, ensure_ascii=False, sort_keys=True)
        targets = ("char:first", "char:second")
        intent = adapt_internal_intent_review_advisory(
            helper,
            bound_target_ids=targets,
            visibility_mode="player",
        )
        audit = state_audit_result()
        audit_before = json.dumps(audit.to_dict(), ensure_ascii=False, sort_keys=True)
        clocks = ("clock:first", "clock:second")
        progress = adapt_state_audit_progress_advisory(audit, clock_ids=clocks)

        assert intent is not None and progress is not None
        self.assertEqual(json.dumps(helper.parsed, ensure_ascii=False, sort_keys=True), helper_before)
        self.assertEqual(json.dumps(audit.to_dict(), ensure_ascii=False, sort_keys=True), audit_before)
        self.assertEqual(targets, ("char:first", "char:second"))
        self.assertEqual(clocks, ("clock:first", "clock:second"))

    def test_state_adapter_builds_maintenance_progress_companion(self) -> None:
        envelope = adapt_state_audit_progress_advisory(
            state_audit_result(),
            clock_ids=("clock:danger:phase-1", "clock:danger:phase-1", "clock:hope"),
        )

        self.assertIs(type(envelope), ResidentAIAdvisory)
        assert envelope is not None
        value = resident_ai_advisory_to_maintenance_dict(envelope)
        digest = expected_digest(
            {
                "adapter": "state_audit_progress",
                "targets": ["clock:danger:phase-1", "clock:hope"],
                "visibility_mode": "maintenance",
            }
        )
        self.assertEqual(value["advisory_type"], "progress_management")
        self.assertEqual(value["target_ids"], ["clock:danger:phase-1", "clock:hope"])
        self.assertEqual(value["evidence"], [
            {"kind": "progress", "ref_id": "clock:danger:phase-1", "as_of_turn_id": None},
            {"kind": "progress", "ref_id": "clock:hope", "as_of_turn_id": None},
        ])
        self.assertEqual(value["confidence"], 0.5)
        self.assertEqual(value["visibility_mode"], "maintenance")
        self.assertEqual(value["source_assistant"], "state_audit")
        self.assertEqual(value["provenance"], {
            "trace_id": f"trace:state-audit:{digest}",
            "source_ids": [f"candidate:state-audit:{digest}"],
        })
        self.assertNotIn(PRIVATE_CANARY, json.dumps(value, ensure_ascii=False, sort_keys=True))

    def test_state_adapter_return_and_rejection_matrix(self) -> None:
        self.assertIsNone(adapt_state_audit_progress_advisory(state_audit_result(), clock_ids=()))
        malformed = (
            (object(), ("clock:one",)),
            (state_audit_result(advisory=1), ("clock:one",)),
            (state_audit_result(no_direct_writes=1), ("clock:one",)),
            (state_audit_result(), ["clock:one"]),
            (state_audit_result(), ("char:not-clock",)),
            (state_audit_result(), ("clock:bad\n",)),
            (state_audit_result(), ("clock:\ud800private",)),
        )
        for result, clock_ids in malformed:
            with self.subTest(result=type(result).__name__, clock_ids=clock_ids):
                with self.assertRaises(ValueError) as raised:
                    adapt_state_audit_progress_advisory(
                        result,  # type: ignore[arg-type]
                        clock_ids=clock_ids,  # type: ignore[arg-type]
                    )
                self.assertNotIn(PRIVATE_CANARY, str(raised.exception))

    def test_reference_budget_counts_unique_targets_after_first_seen_dedupe(self) -> None:
        repeated = adapt_state_audit_progress_advisory(
            state_audit_result(),
            clock_ids=("clock:one",) * 33,
        )
        assert repeated is not None
        self.assertEqual(repeated.target_ids, ("clock:one",))
        with self.assertRaisesRegex(ValueError, "item budget"):
            adapt_state_audit_progress_advisory(
                state_audit_result(),
                clock_ids=tuple(f"clock:{index}" for index in range(33)),
            )
        with self.assertRaisesRegex(ValueError, "traversal budget"):
            adapt_state_audit_progress_advisory(
                state_audit_result(),
                clock_ids=("clock:one",) * 65,
            )

    def test_intent_player_projection_reuses_story_4_4_visibility_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                for entity_id, visibility in (("char:public-adapter", "known"), ("char:hidden-adapter", "hidden")):
                    upsert_entity(conn, {
                        "id": entity_id,
                        "type": "character",
                        "name": entity_id,
                        "visibility": visibility,
                        "summary": PRIVATE_CANARY if visibility == "hidden" else "safe",
                    })
                conn.commit()
                envelope = adapt_internal_intent_review_advisory(
                    helper_result(),
                    bound_target_ids=("char:public-adapter", "char:hidden-adapter", "char:missing-adapter"),
                    visibility_mode="player",
                )
                assert envelope is not None
                player = resident_ai_advisory_to_player_dict(envelope, conn)

        rendered = json.dumps(player, ensure_ascii=False, sort_keys=True)
        self.assertEqual(player["target_ids"], ["char:public-adapter"])
        self.assertEqual(player["evidence"], [{"kind": "entity", "ref_id": "char:public-adapter"}])
        for forbidden in ("confidence", "freshness", "source_assistant", "provenance", PRIVATE_CANARY):
            self.assertNotIn(forbidden, rendered)


class ResidentAIAdvisoryOwnerIntegrationTests(unittest.TestCase):
    def assert_route_semantics_unchanged(self, actual: object, baseline: object) -> None:
        for field_name in ("decision", "rules_outcome", "consensus_outcome", "adopted_outcome", "selected_outcome"):
            actual_value = getattr(actual, field_name)
            baseline_value = getattr(baseline, field_name)
            actual_wire = actual_value.to_dict() if field_name == "decision" else (
                actual_value.final_trace() if actual_value is not None else None
            )
            baseline_wire = baseline_value.to_dict() if field_name == "decision" else (
                baseline_value.final_trace() if baseline_value is not None else None
            )
            self.assertEqual(actual_wire, baseline_wire, field_name)
        self.assertEqual(getattr(actual, "guards"), getattr(baseline, "guards"))
        self.assertEqual(getattr(actual, "trace"), getattr(baseline, "trace"))

    def test_intent_router_adds_companion_after_kernel_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(conn, {
                    "id": "char:route-advisor",
                    "type": "character",
                    "name": "Route Advisor",
                    "visibility": "known",
                    "summary": "safe",
                })
                conn.commit()
                router = AIIntentRouter(conn)
                parsed = dict(helper_result().parsed or {})
                parsed["slots"] = {"npc": "Route Advisor", "topic": "status"}
                internal = helper_result()
                object.__setattr__(internal, "parsed", parsed)
                with mock.patch("rpg_engine.ai_intent.router.collect_internal_intent_candidate", return_value=internal):
                    result = router.route_candidates(
                        campaign,
                        "ask advisor",
                        intent_ai_mode="consensus",
                        external_candidate=None,
                        rule_candidate={
                            "kind": "single",
                            "mode": "action",
                            "action": "social",
                            "slots": {"npc": "Route Advisor", "topic": "status"},
                            "confidence": "medium",
                        },
                        backend="direct",
                        provider="test",
                        model="test",
                        timeout=3,
                        view="player",
                    )

        self.assertIsNotNone(result.internal_advisory)
        assert result.internal_advisory is not None
        self.assertEqual(result.internal_advisory.advisory_type, "intent_recognition")
        self.assertIn("char:route-advisor", result.internal_advisory.target_ids)
        self.assertNotIn("internal_advisory", result.trace)

    def test_intent_owner_adapter_failure_is_observationally_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(conn, {
                    "id": "char:failure-advisor",
                    "type": "character",
                    "name": "Failure Advisor",
                    "visibility": "known",
                    "summary": "safe",
                })
                conn.commit()
                router = AIIntentRouter(conn)
                internal = helper_result()
                parsed = dict(internal.parsed or {})
                parsed["slots"] = {"npc": "Failure Advisor", "topic": "status"}
                object.__setattr__(internal, "parsed", parsed)
                kwargs = dict(
                    intent_ai_mode="consensus",
                    external_candidate=None,
                    rule_candidate={
                        "kind": "single",
                        "mode": "action",
                        "action": "social",
                        "slots": {"npc": "Failure Advisor", "topic": "status"},
                    },
                    backend="direct",
                    provider="test",
                    model="test",
                    timeout=3,
                )
                with mock.patch("rpg_engine.ai_intent.router.collect_internal_intent_candidate", return_value=internal):
                    baseline = router.route_candidates(campaign, "ask advisor", **kwargs)
                    for error_type in (TypeError, ValueError, RuntimeError):
                        with self.subTest(error_type=error_type.__name__):
                            with mock.patch(
                                "rpg_engine.ai_intent.router.adapt_internal_intent_review_advisory",
                                side_effect=error_type(ADAPTER_EXCEPTION_CANARY),
                            ):
                                failed = router.route_candidates(campaign, "ask advisor", **kwargs)
                            self.assertIsNone(failed.internal_advisory)
                            self.assertEqual(failed.trace, baseline.trace)
                            self.assertEqual(failed.guards, baseline.guards)
                            self.assertEqual(failed.selected_outcome, baseline.selected_outcome)
                            self.assertNotIn(
                                ADAPTER_EXCEPTION_CANARY,
                                json.dumps(failed.trace, ensure_ascii=False, sort_keys=True),
                            )
                    with mock.patch(
                        "rpg_engine.ai_intent.router.adapt_internal_intent_review_advisory",
                        return_value={"authority": "forged"},
                    ):
                        wrong_type = router.route_candidates(campaign, "ask advisor", **kwargs)
                    self.assertIsNone(wrong_type.internal_advisory)
                    self.assert_route_semantics_unchanged(wrong_type, baseline)
                    wrong_semantics = adapt_state_audit_progress_advisory(
                        state_audit_result(),
                        clock_ids=("clock:wrong-surface",),
                    )
                    with mock.patch(
                        "rpg_engine.ai_intent.router.adapt_internal_intent_review_advisory",
                        return_value=wrong_semantics,
                    ):
                        wrong_surface = router.route_candidates(campaign, "ask advisor", **kwargs)
                    self.assertIsNone(wrong_surface.internal_advisory)
                    self.assert_route_semantics_unchanged(wrong_surface, baseline)
                    wrong_targets = adapt_internal_intent_review_advisory(
                        internal,
                        bound_target_ids=("char:unrelated",),
                        visibility_mode="player",
                    )
                    with mock.patch(
                        "rpg_engine.ai_intent.router.adapt_internal_intent_review_advisory",
                        return_value=wrong_targets,
                    ):
                        unrelated = router.route_candidates(campaign, "ask advisor", **kwargs)
                    self.assertIsNone(unrelated.internal_advisory)
                    self.assert_route_semantics_unchanged(unrelated, baseline)

    def test_intent_owner_absence_fallback_blocked_and_clarify_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                router = AIIntentRouter(conn)
                rest_rule = {
                    "kind": "single",
                    "mode": "action",
                    "action": "rest",
                    "slots": {"until": "morning"},
                    "confidence": "medium",
                }
                common = dict(
                    external_candidate=None,
                    rule_candidate=rest_rule,
                    backend="direct",
                    provider="test",
                    model="test",
                    timeout=3,
                )
                with mock.patch(
                    "rpg_engine.ai_intent.router.collect_internal_intent_candidate",
                    side_effect=AssertionError("off mode must not call internal helper"),
                ):
                    disabled = router.route_candidates(
                        campaign,
                        "rest",
                        intent_ai_mode="off",
                        **common,
                    )
                self.assertIsNone(disabled.internal_helper)
                self.assertIsNone(disabled.internal_advisory)

                for status in ("off", "error", "timeout"):
                    with self.subTest(status=status):
                        unavailable = helper_result(status=status)
                        with mock.patch(
                            "rpg_engine.ai_intent.router.collect_internal_intent_candidate",
                            return_value=unavailable,
                        ):
                            fallback = router.route_candidates(
                                campaign,
                                "rest",
                                intent_ai_mode="consensus",
                                **common,
                            )
                        self.assertIsNone(fallback.internal_advisory)
                        self.assertIn(fallback.decision.source, {"rules_fallback", "rules"})

                no_binding = helper_result()
                no_binding_payload = dict(no_binding.parsed or {})
                no_binding_payload.update(action="rest", slots={"until": "morning"})
                object.__setattr__(no_binding, "parsed", no_binding_payload)
                with mock.patch(
                    "rpg_engine.ai_intent.router.collect_internal_intent_candidate",
                    return_value=no_binding,
                ):
                    no_binding_result = router.route_candidates(
                        campaign,
                        "rest",
                        intent_ai_mode="consensus",
                        **common,
                    )
                assert no_binding_result.decision.bound is not None
                self.assertEqual(no_binding_result.decision.bound.entity_bindings, {})
                self.assertIsNone(no_binding_result.internal_advisory)

                for name, action, slots, expected_status in (
                    ("blocked", "not_registered", {}, "blocked"),
                    ("clarify", "travel", {"destination": "Missing Place"}, "clarify"),
                ):
                    with self.subTest(name=name):
                        internal = helper_result()
                        payload = dict(internal.parsed or {})
                        payload.update(action=action, slots=slots)
                        object.__setattr__(internal, "parsed", payload)
                        with mock.patch(
                            "rpg_engine.ai_intent.router.collect_internal_intent_candidate",
                            return_value=internal,
                        ):
                            result = router.route_candidates(
                                campaign,
                                name,
                                intent_ai_mode="consensus",
                                **common,
                            )
                        self.assertEqual(result.decision.status, expected_status)
                        self.assertIsNone(result.internal_advisory)

    def test_intent_owner_agree_disagree_and_preflight_companions_are_observational(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                upsert_entity(conn, {
                    "id": "char:matrix-advisor",
                    "type": "character",
                    "name": "Matrix Advisor",
                    "visibility": "known",
                    "summary": "safe",
                })
                conn.commit()
                router = AIIntentRouter(conn)
                candidate = {
                    "kind": "single",
                    "mode": "action",
                    "action": "social",
                    "slots": {"npc": "Matrix Advisor", "topic": "status"},
                    "confidence": "high",
                }
                common = dict(
                    intent_ai_mode="consensus",
                    external_candidate=candidate,
                    rule_candidate=candidate,
                    backend="direct",
                    provider="test",
                    model="test",
                    timeout=3,
                )
                for agreement in ("agree", "disagree"):
                    with self.subTest(agreement=agreement):
                        internal = helper_result()
                        payload = dict(internal.parsed or {})
                        payload.update(
                            slots={"npc": "Matrix Advisor", "topic": "status"},
                            agreement_with_external=agreement,
                            disagreements=[] if agreement == "agree" else ["safe disagreement"],
                        )
                        object.__setattr__(internal, "parsed", payload)
                        with mock.patch(
                            "rpg_engine.ai_intent.router.collect_internal_intent_candidate",
                            return_value=internal,
                        ):
                            actual = router.route_candidates(campaign, "ask", **common)
                        with (
                            mock.patch(
                                "rpg_engine.ai_intent.router.collect_internal_intent_candidate",
                                return_value=internal,
                            ),
                            mock.patch(
                                "rpg_engine.ai_intent.router.adapt_internal_intent_review_advisory",
                                return_value=None,
                            ),
                        ):
                            baseline = router.route_candidates(campaign, "ask", **common)
                        assert actual.internal_advisory is not None
                        self.assertEqual(actual.internal_advisory.target_ids, ("char:matrix-advisor",))
                        self.assert_route_semantics_unchanged(actual, baseline)

                cached = helper_result()
                cached_payload = dict(cached.parsed or {})
                cached_payload["slots"] = {"npc": "Matrix Advisor", "topic": "status"}
                lookup = PreflightLookupResult(
                    "hit",
                    internal_review=cached_payload,
                    helper_audit={"private": PRIVATE_CANARY},
                )
                with (
                    mock.patch.object(router, "lookup_preflight", return_value=lookup),
                    mock.patch("rpg_engine.ai_intent.router.collect_internal_intent_candidate") as live_helper,
                ):
                    preflight = router.route_candidates(
                        campaign,
                        "ask",
                        preflight_id="preflight:test",
                        **common,
                    )
                live_helper.assert_not_called()
                assert preflight.internal_advisory is not None
                self.assertEqual(preflight.internal_advisory.target_ids, ("char:matrix-advisor",))
                provenance_wire = json.dumps(preflight.internal_advisory.provenance.to_dict(), sort_keys=True)
                self.assertNotIn("preflight", provenance_wire)
                self.assertNotIn(PRIVATE_CANARY, provenance_wire)

    def test_state_audit_artifact_is_maintenance_only_and_all_or_none(self) -> None:
        valid_delta = complete_clock_delta(
            [
                {"id": "clock:one", "delta": 1, "reason": "test"},
                {"id": "clock:one", "delta": 1, "reason": "test"},
                {"id": "clock:two", "delta": 1, "reason": "test"},
            ]
        )
        conn = memory_clock_conn("clock:one", "clock:two")
        stages = (validated_delta_stage(conn, valid_delta),)
        try:
            maintenance = validate_state_audit_stage(
                conn,
                "maintenance_commit",
                valid_delta,
                state_audit=True,
                state_audit_ai="off",
                state_audit_provider="test",
                state_audit_model="test",
                state_audit_timeout=3,
                state_audit_block=True,
                action=None,
                action_options={},
                context={},
                stages=stages,
            )
            player = validate_state_audit_stage(
                conn,
                "player_turn_commit",
                valid_delta,
                state_audit=True,
                state_audit_ai="off",
                state_audit_provider="test",
                state_audit_model="test",
                state_audit_timeout=3,
                state_audit_block=True,
                action=None,
                action_options={},
                context={},
                stages=(ValidationStageResult("delta_schema", "player_turn_commit", "ok"),),
            )
            mixed = validate_state_audit_stage(
                conn,
                "maintenance_commit",
                {**valid_delta, "tick_clocks": [{"id": "clock:one"}, {"id": "bad"}]},
                state_audit=True,
                state_audit_ai="off",
                state_audit_provider="test",
                state_audit_model="test",
                state_audit_timeout=3,
                state_audit_block=True,
                action=None,
                action_options={},
                context={},
                stages=stages,
            )
            blocked = validate_state_audit_stage(
                conn,
                "maintenance_commit",
                valid_delta,
                state_audit=True,
                state_audit_ai="off",
                state_audit_provider="test",
                state_audit_model="test",
                state_audit_timeout=3,
                state_audit_block=True,
                action=None,
                action_options={},
                context={},
                stages=(ValidationStageResult("delta_schema", "maintenance_commit", "blocked"),),
            )
        finally:
            conn.close()

        self.assertEqual(maintenance.artifacts["advisory"]["target_ids"], ["clock:one", "clock:two"])
        self.assertNotIn("advisory", player.artifacts)
        self.assertNotIn("advisory", mixed.artifacts)
        self.assertNotIn("advisory", blocked.artifacts)
        self.assertEqual(maintenance.status, player.status)
        self.assertEqual(maintenance.issues, player.issues)
        self.assertEqual(
            MAINTENANCE_ADVISORY_PROFILES,
            frozenset({"maintenance_commit", "admin_or_legacy_save_turn", "import_or_migration"}),
        )

    def test_state_owner_profile_and_input_omission_matrix(self) -> None:
        class ForgedProfile(str):
            def __hash__(self) -> int:
                return hash("maintenance_commit")

            def __eq__(self, other: object) -> bool:
                return other == "maintenance_commit"

        class ForgedStageString(str):
            def __eq__(self, other: object) -> bool:
                return other in {"delta_schema", "maintenance_commit", "ok"}

        class ForgedDelta(dict[object, object]):
            def get(self, key: object, default: object = None) -> object:
                if key == "tick_clocks":
                    return [{"id": "clock:forged"}]
                return super().get(key, default)

        class ForgedKey(str):
            def __new__(cls, value: str, target: str) -> ForgedKey:
                instance = super().__new__(cls, value)
                instance.target = target
                return instance

            def __hash__(self) -> int:
                return hash(self.target)

            def __eq__(self, other: object) -> bool:
                return other == self.target

        self.assertIs(type(MAINTENANCE_ADVISORY_PROFILES), frozenset)
        conn = memory_clock_conn("clock:one")
        try:
            valid_delta = complete_clock_delta([{"id": "clock:one", "delta": 1, "reason": "test"}])
            for profile in (
                "preview_only",
                "player_turn_commit",
                "response_acceptance",
                "unknown_profile",
                ForgedProfile("unknown_profile"),
            ):
                with self.subTest(profile=profile):
                    result = validate_state_audit_stage(
                        conn,
                        profile,
                        valid_delta,
                        state_audit=True,
                        state_audit_ai="off",
                        state_audit_provider="test",
                        state_audit_model="test",
                        state_audit_timeout=3,
                        state_audit_block=True,
                        action=None,
                        action_options={},
                        context={},
                        stages=(ValidationStageResult("delta_schema", str(profile), "ok"),),
                    )
                    self.assertNotIn("advisory", result.artifacts)

            maintenance_cases = (
                ("empty", {"tick_clocks": []}, False),
                ("missing", {}, False),
                ("mixed", {"tick_clocks": [{"id": "clock:one"}, {"id": 1}]}, False),
                ("oversize-ref", {"tick_clocks": [{"id": "clock:" + "x" * 161}]}, False),
                (
                    "oversize-unique",
                    {"tick_clocks": [{"id": f"clock:{index}"} for index in range(33)]},
                    False,
                ),
                (
                    "duplicates-do-not-spend-budget",
                    {"tick_clocks": [{"id": "clock:one", "delta": 1, "reason": "test"} for _ in range(33)]},
                    True,
                ),
                (
                    "item-container-64",
                    {
                        "tick_clocks": [{
                            "id": "clock:one",
                            "delta": 1,
                            "reason": "test",
                            **{f"extra_{index}": index for index in range(61)},
                        }]
                    },
                    True,
                ),
                (
                    "item-container-65",
                    {
                        "tick_clocks": [{
                            "id": "clock:one",
                            "delta": 1,
                            "reason": "test",
                            **{f"extra_{index}": index for index in range(62)},
                        }]
                    },
                    False,
                ),
                (
                    "raw-traversal-budget",
                    {"tick_clocks": [{"id": "clock:one", "delta": 1, "reason": "test"} for _ in range(65)]},
                    False,
                ),
            )
            for name, raw_delta, expected_advisory in maintenance_cases:
                with self.subTest(name=name):
                    raw_tick_clocks = raw_delta.get("tick_clocks")
                    delta = complete_clock_delta(raw_tick_clocks if type(raw_tick_clocks) is list else None)
                    result = validate_state_audit_stage(
                        conn,
                        "maintenance_commit",
                        delta,
                        state_audit=True,
                        state_audit_ai="off",
                        state_audit_provider="test",
                        state_audit_model="test",
                        state_audit_timeout=3,
                        state_audit_block=True,
                        action=None,
                        action_options={},
                        context={},
                        stages=(validated_delta_stage(conn, delta),),
                    )
                    self.assertEqual("advisory" in result.artifacts, expected_advisory)

            hostile_mapping_cases: tuple[tuple[str, dict[object, object]], ...] = (
                ("outer-subclass", ForgedDelta()),
                ("outer-key", {ForgedKey("private", "tick_clocks"): [{"id": "clock:forged"}]}),
                (
                    "item-key",
                    {"tick_clocks": [{ForgedKey("private", "id"): "clock:forged"}]},
                ),
            )
            for name, delta in hostile_mapping_cases:
                with self.subTest(hostile_mapping=name):
                    result = validate_state_audit_stage(
                        conn,
                        "maintenance_commit",
                        delta,  # type: ignore[arg-type]
                        state_audit=True,
                        state_audit_ai="off",
                        state_audit_provider="test",
                        state_audit_model="test",
                        state_audit_timeout=3,
                        state_audit_block=True,
                        action=None,
                        action_options={},
                        context={},
                        stages=(ValidationStageResult("delta_schema", "maintenance_commit", "ok"),),
                    )
                    self.assertNotIn("advisory", result.artifacts)

            current_stage = validated_delta_stage(conn, valid_delta)
            assert current_stage._validated_delta_proof is not None
            forged_proof_stage = replace(
                current_stage,
                _validated_delta_proof=replace(current_stage._validated_delta_proof),
            )
            for name, stages in (
                ("cross-profile", (ValidationStageResult("delta_schema", "player_turn_commit", "ok"),)),
                ("warning", (ValidationStageResult("delta_schema", "maintenance_commit", "warning"),)),
                ("skipped", (ValidationStageResult("delta_schema", "maintenance_commit", "skipped"),)),
                ("duplicate", (current_stage, current_stage)),
                ("non-exact", (mock.Mock(name="delta_schema", profile="maintenance_commit", status="ok"),)),
                ("forged-private-proof", (forged_proof_stage,)),
                (
                    "forged-fields",
                    (
                        ValidationStageResult(
                            ForgedStageString("evil"),
                            ForgedStageString("evil"),
                            ForgedStageString("blocked"),
                        ),
                    ),
                ),
            ):
                with self.subTest(stage_provenance=name):
                    result = validate_state_audit_stage(
                        conn,
                        "maintenance_commit",
                        valid_delta,
                        state_audit=True,
                        state_audit_ai="off",
                        state_audit_provider="test",
                        state_audit_model="test",
                        state_audit_timeout=3,
                        state_audit_block=True,
                        action=None,
                        action_options={},
                        context={},
                        stages=stages,  # type: ignore[arg-type]
                    )
                    self.assertNotIn("advisory", result.artifacts)
        finally:
            conn.close()

    def test_state_owner_warning_blocking_merge_report_and_commit_semantics_are_unchanged(self) -> None:
        deterministic = StateAuditResult(ok=True, risk="low", ai_status="off")
        merged = merge_state_audit_results(
            deterministic,
            StateAuditResult(ok=True, risk="low", warnings=["merged warning"]),
            ai_status="ok",
            audit={"merge": "safe"},
        )
        blocking = StateAuditResult(
            ok=False,
            risk="high",
            findings=[{"message": "blocking finding"}],
            requires_human_review=True,
            ai_status="ok",
        )
        conn = memory_clock_conn("clock:one")
        try:
            for name, audit in (("deterministic", deterministic), ("merged", merged), ("blocking", blocking)):
                with self.subTest(name=name):
                    delta = complete_clock_delta([{"id": "clock:one", "delta": 1, "reason": "test"}])
                    kwargs = dict(
                        profile="maintenance_commit",
                        delta=delta,
                        state_audit=True,
                        state_audit_ai="off",
                        state_audit_provider="test",
                        state_audit_model="test",
                        state_audit_timeout=3,
                        state_audit_block=True,
                        action=None,
                        action_options={},
                        context={},
                        stages=(validated_delta_stage(conn, delta),),
                    )
                    with mock.patch("rpg_engine.validation_pipeline.run_state_audit", return_value=audit):
                        actual = validate_state_audit_stage(conn, **kwargs)
                    with (
                        mock.patch("rpg_engine.validation_pipeline.run_state_audit", return_value=audit),
                        mock.patch(
                            "rpg_engine.validation_pipeline.adapt_state_audit_progress_advisory",
                            return_value=None,
                        ),
                    ):
                        baseline = validate_state_audit_stage(conn, **kwargs)
                    self.assertIn("advisory", actual.artifacts)
                    self.assertEqual(actual.status, baseline.status)
                    self.assertEqual(actual.issues, baseline.issues)
                    self.assertEqual(actual.artifacts["audit"], baseline.artifacts["audit"])

                    profile_stage = ValidationStageResult(
                        "profile",
                        "maintenance_commit",
                        "ok",
                        artifacts={"allowed_commit": True},
                    )
                    actual_report = ValidationReport("maintenance_commit", (profile_stage, actual))
                    baseline_report = ValidationReport("maintenance_commit", (profile_stage, baseline))
                    self.assertEqual(actual_report.status, baseline_report.status)
                    self.assertEqual(actual_report.ok, baseline_report.ok)
                    self.assertEqual(actual_report.errors, baseline_report.errors)
                    self.assertEqual(actual_report.warnings, baseline_report.warnings)
                    self.assertEqual(actual_report.state_audit, baseline_report.state_audit)
                    self.assertEqual(
                        actual_report.stage("profile").artifacts["allowed_commit"],  # type: ignore[union-attr]
                        baseline_report.stage("profile").artifacts["allowed_commit"],  # type: ignore[union-attr]
                    )
                    actual_wire = actual_report.to_dict()
                    baseline_wire = baseline_report.to_dict()
                    self.assertEqual(actual_wire["status"], baseline_wire["status"])
                    self.assertEqual(actual_wire["ok"], baseline_wire["ok"])
                    self.assertEqual(actual_wire["errors"], baseline_wire["errors"])
                    self.assertEqual(actual_wire["warnings"], baseline_wire["warnings"])
        finally:
            conn.close()

    def test_state_owner_isolates_delta_when_audit_mutates_its_input(self) -> None:
        delta = complete_clock_delta([{"id": "clock:validated", "delta": 1, "reason": "test"}])

        def mutate_delta_during_audit(*_args: object, **kwargs: object) -> StateAuditResult:
            mutable_delta = kwargs["delta"]
            assert isinstance(mutable_delta, dict)
            mutable_delta["tick_clocks"][0]["id"] = "clock:unvalidated"  # type: ignore[index]
            return StateAuditResult()

        conn = memory_clock_conn("clock:validated")
        try:
            with mock.patch(
                "rpg_engine.validation_pipeline.run_state_audit",
                side_effect=mutate_delta_during_audit,
            ):
                result = validate_state_audit_stage(
                    conn,
                    "maintenance_commit",
                    delta,
                    state_audit=True,
                    state_audit_ai="off",
                    state_audit_provider="test",
                    state_audit_model="test",
                    state_audit_timeout=3,
                    state_audit_block=True,
                    action=None,
                    action_options={},
                    context={},
                    stages=(validated_delta_stage(conn, delta),),
                )
        finally:
            conn.close()

        self.assertEqual(delta["tick_clocks"][0]["id"], "clock:validated")
        self.assertNotIn("advisory", result.artifacts)

    def test_delta_digest_fails_closed_for_non_serializable_values(self) -> None:
        self.assertIsNone(stable_delta_digest({"meta": {"private": object()}}))
        self.assertIsNone(stable_delta_digest({"meta": {True: "value"}}))  # type: ignore[dict-item]
        self.assertIsNone(stable_delta_digest({"summary": "bad\ud800"}))

        class StringSubclass(str):
            pass

        self.assertIsNone(
            stable_delta_digest({"meta": {StringSubclass("private"): "value"}}),  # type: ignore[dict-item]
        )

        conn = memory_clock_conn()
        try:
            result = validate_delta_schema_stage(
                conn,
                "maintenance_commit",
                {"summary": "bad\ud800"},
            )
        finally:
            conn.close()
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.issues, ("$: delta snapshot mismatch",))

    def test_state_owner_omits_companion_when_delta_changes_after_schema_stage(self) -> None:
        delta = complete_clock_delta([{"id": "clock:validated", "delta": 1, "reason": "test"}])
        delta["tick_clocks"][0]["id"] = "clock:changed-after-validation"
        conn = memory_clock_conn("clock:validated")
        try:
            delta["tick_clocks"][0]["id"] = "clock:validated"
            validated_stage = validated_delta_stage(conn, delta)
            delta["tick_clocks"][0]["id"] = "clock:changed-after-validation"
            with mock.patch(
                "rpg_engine.validation_pipeline.run_state_audit",
                return_value=StateAuditResult(),
            ):
                result = validate_state_audit_stage(
                    conn,
                    "maintenance_commit",
                    delta,
                    state_audit=True,
                    state_audit_ai="off",
                    state_audit_provider="test",
                    state_audit_model="test",
                    state_audit_timeout=3,
                    state_audit_block=True,
                    action=None,
                    action_options={},
                    context={},
                    stages=(validated_stage,),
                )
        finally:
            conn.close()

        self.assertNotIn("advisory", result.artifacts)

    def test_state_audit_always_receives_an_isolated_delta_without_clock_targets(self) -> None:
        delta = complete_clock_delta(None)
        conn = memory_clock_conn("clock:injected")

        def mutate_audit_copy(*_args: object, **kwargs: object) -> StateAuditResult:
            audit_delta = kwargs["delta"]
            self.assertIsNot(audit_delta, delta)
            audit_delta["tick_clocks"] = [{"id": "clock:injected", "delta": 1, "reason": "test"}]
            return StateAuditResult()

        try:
            with mock.patch(
                "rpg_engine.validation_pipeline.run_state_audit",
                side_effect=mutate_audit_copy,
            ):
                result = validate_state_audit_stage(
                    conn,
                    "maintenance_commit",
                    delta,
                    state_audit=True,
                    state_audit_ai="off",
                    state_audit_provider="test",
                    state_audit_model="test",
                    state_audit_timeout=3,
                    state_audit_block=True,
                    action=None,
                    action_options={},
                    context={},
                    stages=(validated_delta_stage(conn, delta),),
                )
        finally:
            conn.close()

        self.assertNotIn("tick_clocks", delta)
        self.assertNotIn("advisory", result.artifacts)

    def test_state_audit_preserves_noncanonical_delta_semantics_on_an_isolated_copy(self) -> None:
        delta = complete_clock_delta(None)
        delta["intent"] = "query"
        delta["extension"] = ("noncanonical",)
        conn = memory_clock_conn()
        try:
            result = validate_state_audit_stage(
                conn,
                "maintenance_commit",
                delta,
                state_audit=True,
                state_audit_ai="off",
                state_audit_provider="test",
                state_audit_model="test",
                state_audit_timeout=3,
                state_audit_block=True,
                action=None,
                action_options={},
                context={},
                stages=(validated_delta_stage(conn, delta),),
            )
        finally:
            conn.close()

        audit = result.artifacts["audit"]
        self.assertEqual(audit["risk"], "high")
        self.assertIn("QUERY_MUTATES_STATE", {item["code"] for item in audit["findings"]})
        self.assertEqual(delta["extension"], ("noncanonical",))
        self.assertNotIn("advisory", result.artifacts)

    def test_state_owner_rechecks_liveness_after_adapter_returns(self) -> None:
        for operation in ("archive", "delete"):
            with self.subTest(operation=operation):
                delta = complete_clock_delta([{"id": "clock:live", "delta": 1, "reason": "test"}])
                conn = memory_clock_conn("clock:live")

                def change_liveness_then_adapt(
                    audit: StateAuditResult,
                    *,
                    clock_ids: tuple[str, ...],
                ) -> ResidentAIAdvisory | None:
                    if operation == "archive":
                        conn.execute("update main.entities set status = 'archived' where id = ?", ("clock:live",))
                    else:
                        conn.execute("delete from main.clocks where entity_id = ?", ("clock:live",))
                    conn.commit()
                    return adapt_state_audit_progress_advisory(audit, clock_ids=clock_ids)

                try:
                    with mock.patch(
                        "rpg_engine.validation_pipeline.adapt_state_audit_progress_advisory",
                        side_effect=change_liveness_then_adapt,
                    ):
                        result = validate_state_audit_stage(
                            conn,
                            "maintenance_commit",
                            delta,
                            state_audit=True,
                            state_audit_ai="off",
                            state_audit_provider="test",
                            state_audit_model="test",
                            state_audit_timeout=3,
                            state_audit_block=True,
                            action=None,
                            action_options={},
                            context={},
                            stages=(validated_delta_stage(conn, delta),),
                        )
                finally:
                    conn.close()

                self.assertNotIn("advisory", result.artifacts)

    def test_state_owner_omits_companion_when_clock_is_no_longer_live(self) -> None:
        delta = complete_clock_delta([{"id": "clock:live", "delta": 1, "reason": "test"}])
        conn = memory_clock_conn("clock:live")

        def delete_clock_during_audit(*_args: object, **_kwargs: object) -> StateAuditResult:
            conn.execute("delete from clocks where entity_id = ?", ("clock:live",))
            conn.commit()
            return StateAuditResult()

        try:
            with mock.patch(
                "rpg_engine.validation_pipeline.run_state_audit",
                side_effect=delete_clock_during_audit,
            ):
                result = validate_state_audit_stage(
                    conn,
                    "maintenance_commit",
                    delta,
                    state_audit=True,
                    state_audit_ai="off",
                    state_audit_provider="test",
                    state_audit_model="test",
                    state_audit_timeout=3,
                    state_audit_block=True,
                    action=None,
                    action_options={},
                    context={},
                    stages=(validated_delta_stage(conn, delta),),
                )
        finally:
            conn.close()

        self.assertNotIn("advisory", result.artifacts)

    def test_state_owner_omits_companion_when_clock_is_archived(self) -> None:
        archived_statuses = ("archived", "\x1cＡＲＣＨＩＶＥＤ\u2060")
        for archived_status in archived_statuses:
            with self.subTest(archived_status=archived_status):
                delta = complete_clock_delta([{"id": "clock:live", "delta": 1, "reason": "test"}])
                conn = memory_clock_conn("clock:live")

                def archive_clock_during_audit(*_args: object, **_kwargs: object) -> StateAuditResult:
                    conn.execute(
                        "update entities set status = ? where id = ?",
                        (archived_status, "clock:live"),
                    )
                    conn.commit()
                    return StateAuditResult()

                try:
                    with mock.patch(
                        "rpg_engine.validation_pipeline.run_state_audit",
                        side_effect=archive_clock_during_audit,
                    ):
                        result = validate_state_audit_stage(
                            conn,
                            "maintenance_commit",
                            delta,
                            state_audit=True,
                            state_audit_ai="off",
                            state_audit_provider="test",
                            state_audit_model="test",
                            state_audit_timeout=3,
                            state_audit_block=True,
                            action=None,
                            action_options={},
                            context={},
                            stages=(validated_delta_stage(conn, delta),),
                        )
                finally:
                    conn.close()

                self.assertNotIn("advisory", result.artifacts)

    def test_state_owner_uses_authoritative_main_tables_for_liveness(self) -> None:
        delta = complete_clock_delta([{"id": "clock:live", "delta": 1, "reason": "test"}])
        conn = memory_clock_conn("clock:live")

        def shadow_archived_clock_during_audit(*_args: object, **_kwargs: object) -> StateAuditResult:
            conn.execute("update main.entities set status = 'archived' where id = ?", ("clock:live",))
            conn.execute("create temp table entities (id text primary key, status text not null)")
            conn.execute("create temp table clocks (entity_id text primary key)")
            conn.execute("insert into temp.entities values ('clock:live', 'active')")
            conn.execute("insert into temp.clocks values ('clock:live')")
            conn.commit()
            return StateAuditResult()

        try:
            with mock.patch(
                "rpg_engine.validation_pipeline.run_state_audit",
                side_effect=shadow_archived_clock_during_audit,
            ):
                result = validate_state_audit_stage(
                    conn,
                    "maintenance_commit",
                    delta,
                    state_audit=True,
                    state_audit_ai="off",
                    state_audit_provider="test",
                    state_audit_model="test",
                    state_audit_timeout=3,
                    state_audit_block=True,
                    action=None,
                    action_options={},
                    context={},
                    stages=(validated_delta_stage(conn, delta),),
                )
        finally:
            conn.close()

        self.assertNotIn("advisory", result.artifacts)

    def test_validated_delta_proof_cannot_cross_connections(self) -> None:
        delta = complete_clock_delta([{"id": "clock:same", "delta": 1, "reason": "test"}])
        first_conn = memory_clock_conn("clock:same")
        second_conn = memory_clock_conn("clock:same")
        try:
            stage = validated_delta_stage(first_conn, delta)
            proof = stage._validated_delta_proof
            self.assertIsNotNone(proof)
            self.assertIs(proof.connection, first_conn)  # type: ignore[union-attr]
            with mock.patch(
                "rpg_engine.validation_pipeline.run_state_audit",
                return_value=StateAuditResult(),
            ):
                result = validate_state_audit_stage(
                    second_conn,
                    "maintenance_commit",
                    delta,
                    state_audit=True,
                    state_audit_ai="off",
                    state_audit_provider="test",
                    state_audit_model="test",
                    state_audit_timeout=3,
                    state_audit_block=True,
                    action=None,
                    action_options={},
                    context={},
                    stages=(stage,),
                )
        finally:
            first_conn.close()
            second_conn.close()

        self.assertNotIn("advisory", result.artifacts)

    def test_state_owner_adapter_failure_does_not_change_audit_result(self) -> None:
        conn = memory_clock_conn("clock:one")
        kwargs = dict(
            profile="maintenance_commit",
            delta=complete_clock_delta([{"id": "clock:one", "delta": 1, "reason": "test"}]),
            state_audit=True,
            state_audit_ai="off",
            state_audit_provider="test",
            state_audit_model="test",
            state_audit_timeout=3,
            state_audit_block=True,
            action=None,
            action_options={},
            context={},
            stages=(),
        )
        kwargs["stages"] = (validated_delta_stage(conn, kwargs["delta"]),)
        try:
            baseline = validate_state_audit_stage(conn, **kwargs)
            failures = []
            for error_type in (TypeError, ValueError, RuntimeError):
                kwargs["stages"] = (validated_delta_stage(conn, kwargs["delta"]),)
                with mock.patch(
                    "rpg_engine.validation_pipeline.adapt_state_audit_progress_advisory",
                    side_effect=error_type(ADAPTER_EXCEPTION_CANARY),
                ):
                    failures.append(validate_state_audit_stage(conn, **kwargs))

            def mutate_audit_then_fail(audit: StateAuditResult, **_kwargs: object) -> None:
                audit.warnings.append(ADAPTER_EXCEPTION_CANARY)
                raise RuntimeError(ADAPTER_EXCEPTION_CANARY)

            with mock.patch(
                "rpg_engine.validation_pipeline.adapt_state_audit_progress_advisory",
                side_effect=mutate_audit_then_fail,
            ):
                kwargs["stages"] = (validated_delta_stage(conn, kwargs["delta"]),)
                failures.append(validate_state_audit_stage(conn, **kwargs))
            wrong_semantics = adapt_internal_intent_review_advisory(
                helper_result(),
                bound_target_ids=("char:wrong-surface",),
                visibility_mode="player",
            )
            with mock.patch(
                "rpg_engine.validation_pipeline.adapt_state_audit_progress_advisory",
                return_value=wrong_semantics,
            ):
                kwargs["stages"] = (validated_delta_stage(conn, kwargs["delta"]),)
                failures.append(validate_state_audit_stage(conn, **kwargs))
            baseline_audit = StateAuditResult(**baseline.artifacts["audit"])
            wrong_targets = adapt_state_audit_progress_advisory(
                baseline_audit,
                clock_ids=("clock:unrelated",),
            )
            with mock.patch(
                "rpg_engine.validation_pipeline.adapt_state_audit_progress_advisory",
                return_value=wrong_targets,
            ):
                kwargs["stages"] = (validated_delta_stage(conn, kwargs["delta"]),)
                failures.append(validate_state_audit_stage(conn, **kwargs))
        finally:
            conn.close()

        for failed in failures:
            self.assertEqual(failed.status, baseline.status)
            self.assertEqual(failed.issues, baseline.issues)
            self.assertEqual(failed.artifacts["audit"], baseline.artifacts["audit"])
            self.assertNotIn("advisory", failed.artifacts)
            self.assertNotIn(
                ADAPTER_EXCEPTION_CANARY,
                json.dumps(failed.artifacts, ensure_ascii=False, sort_keys=True),
            )


if __name__ == "__main__":
    unittest.main()
