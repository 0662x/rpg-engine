from __future__ import annotations

import copy
import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import rpg_engine.ai.advisory as advisory_module

from rpg_engine.ai import (
    ResidentAIAdvisory,
    normalize_resident_ai_advisory,
    resident_ai_advisory_to_maintenance_dict,
    resident_ai_advisory_to_player_dict,
)
from rpg_engine.ai.schema_validation import validate_ai_output_schema
from rpg_engine.ai.advisory import (
    AdvisoryAuthority,
    AdvisoryEvidence,
    AdvisoryFreshness,
    AdvisoryProvenance,
)
from rpg_engine.campaign import load_campaign
from rpg_engine.content_types.world_setting import upsert_world_setting
from rpg_engine.db import connect, upsert_clock, upsert_entity, upsert_rule
from rpg_engine.entity_access import read_entity
from rpg_engine.redaction import redact_player_hidden_material

from tests.helpers import copy_initialized_minimal, query_scalar


ADVISORY_TYPES = (
    "intent_recognition",
    "context_summary",
    "entity_maintenance",
    "progress_management",
    "plot_progression",
)


def authority_contract() -> dict[str, bool]:
    return {
        "advisory_only": True,
        "no_direct_writes": True,
        "can_write_facts": False,
        "can_approve_proposals": False,
        "can_confirm_players": False,
        "can_read_hidden": False,
        "can_inject_trusted_delta": False,
        "can_authorize_save": False,
        "can_escalate_profile": False,
        "can_bypass_validation": False,
        "can_commit": False,
    }


def advisory_value(
    *,
    advisory_type: str = "context_summary",
    visibility_mode: str = "player",
    target_ids: list[str] | None = None,
    evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "advisory_type": advisory_type,
        "target_ids": ["npc:visible-advisory"] if target_ids is None else target_ids,
        "evidence": [
            {
                "kind": "entity",
                "ref_id": "npc:visible-advisory",
                "as_of_turn_id": 1,
            }
        ]
        if evidence is None
        else evidence,
        "confidence": 0.75,
        "freshness": {
            "status": "current",
            "as_of_turn_id": 1,
            "source_event_ids": ["event:seed"],
        },
        "visibility_mode": visibility_mode,
        "source_assistant": "resident-context-summary",
        "schema_version": "resident_ai_advisory:v1",
        "proposed_next_workflow": advisory_type,
        "provenance": {
            "trace_id": "advisory:trace-001",
            "source_ids": ["turn:seed"],
        },
        "authority": authority_contract(),
    }


class ResidentAIAdvisoryContractTests(unittest.TestCase):
    def test_normalize_returns_deeply_immutable_contract_and_defensive_dicts(self) -> None:
        source = advisory_value()
        envelope = normalize_resident_ai_advisory(source)

        self.assertIsInstance(envelope, ResidentAIAdvisory)
        self.assertIsInstance(envelope.target_ids, tuple)
        self.assertIsInstance(envelope.evidence, tuple)
        self.assertIsInstance(envelope.freshness.source_event_ids, tuple)
        self.assertIsInstance(envelope.provenance.source_ids, tuple)

        source["target_ids"].append("npc:mutated")  # type: ignore[union-attr]
        source["evidence"][0]["ref_id"] = "npc:mutated"  # type: ignore[index]
        first = envelope.to_dict()
        first["target_ids"].append("npc:returned-mutation")
        first["evidence"][0]["ref_id"] = "npc:returned-mutation"
        second = envelope.to_dict()

        self.assertEqual(second["target_ids"], ["npc:visible-advisory"])
        self.assertEqual(second["evidence"][0]["ref_id"], "npc:visible-advisory")
        self.assertEqual(second["authority"], authority_contract())
        self.assertEqual(validate_ai_output_schema("resident_ai_advisory.schema.json", second), [])

    def test_all_v1_advisory_types_and_none_workflow_are_supported(self) -> None:
        for advisory_type in ADVISORY_TYPES:
            with self.subTest(advisory_type=advisory_type):
                result = normalize_resident_ai_advisory(advisory_value(advisory_type=advisory_type))
                self.assertEqual(result.advisory_type, advisory_type)
                self.assertEqual(result.proposed_next_workflow, advisory_type)

        value = advisory_value()
        value["proposed_next_workflow"] = "none"
        self.assertEqual(normalize_resident_ai_advisory(value).proposed_next_workflow, "none")

    def test_schema_and_semantic_failures_are_strict_and_path_qualified(self) -> None:
        cases: list[tuple[str, object]] = []
        missing = advisory_value()
        missing.pop("source_assistant")
        cases.append(("missing", missing))
        unknown = advisory_value()
        unknown["extra"] = True
        cases.append(("unknown", unknown))
        bool_confidence = advisory_value()
        bool_confidence["confidence"] = True
        cases.append(("bool confidence", bool_confidence))
        nonfinite = advisory_value()
        nonfinite["confidence"] = math.inf
        cases.append(("nonfinite confidence", nonfinite))
        duplicate_target = advisory_value(target_ids=["npc:one", "npc:one"])
        cases.append(("duplicate target", duplicate_target))
        duplicate_event = advisory_value()
        duplicate_event["freshness"]["source_event_ids"] = ["event:one", "event:one"]  # type: ignore[index]
        cases.append(("duplicate event", duplicate_event))
        duplicate_evidence = advisory_value()
        duplicate_evidence["evidence"] = duplicate_evidence["evidence"] * 2  # type: ignore[operator]
        cases.append(("duplicate evidence", duplicate_evidence))
        duplicate_ref_across_kinds = advisory_value(
            evidence=[
                {"kind": "entity", "ref_id": "rel:same-source", "as_of_turn_id": 1},
                {"kind": "relationship", "ref_id": "rel:same-source", "as_of_turn_id": 1},
            ]
        )
        cases.append(("duplicate ref across kinds", duplicate_ref_across_kinds))
        duplicate_source = advisory_value()
        duplicate_source["provenance"]["source_ids"] = ["turn:seed", "turn:seed"]  # type: ignore[index]
        cases.append(("duplicate provenance source", duplicate_source))
        stale_without_as_of = advisory_value()
        stale_without_as_of["freshness"] = {
            "status": "stale",
            "as_of_turn_id": None,
            "source_event_ids": [],
        }
        cases.append(("stale without evidence", stale_without_as_of))
        unknown_with_as_of = advisory_value()
        unknown_with_as_of["freshness"] = {
            "status": "unknown",
            "as_of_turn_id": 1,
            "source_event_ids": [],
        }
        cases.append(("unknown with evidence", unknown_with_as_of))
        invalid_workflow = advisory_value()
        invalid_workflow["proposed_next_workflow"] = "commit"
        cases.append(("workflow", invalid_workflow))
        invalid_visibility = advisory_value()
        invalid_visibility["visibility_mode"] = "public"
        cases.append(("visibility", invalid_visibility))
        false_authority = advisory_value()
        false_authority["authority"]["can_commit"] = True  # type: ignore[index]
        cases.append(("authority", false_authority))
        opaque = advisory_value()
        opaque["provenance"]["source_ids"] = [object()]  # type: ignore[index]
        cases.append(("opaque", opaque))
        empty_targets = advisory_value(target_ids=[])
        cases.append(("empty targets", empty_targets))
        empty_evidence = advisory_value(evidence=[])
        cases.append(("empty evidence", empty_evidence))
        nan_confidence = advisory_value()
        nan_confidence["confidence"] = math.nan
        cases.append(("nan confidence", nan_confidence))
        invalid_source = advisory_value()
        invalid_source["source_assistant"] = "RAW PROMPT SECRET"
        cases.append(("invalid source", invalid_source))
        invalid_schema = advisory_value()
        invalid_schema["schema_version"] = "resident_ai_advisory:v2"
        cases.append(("invalid schema", invalid_schema))
        runtime_target = advisory_value(target_ids=["trace:advisory-001"])
        cases.append(("runtime target", runtime_target))
        for prefix in (
            "commit",
            "memory",
            "save",
            "campaign",
            "session",
            "projection",
            "pending",
            "runtime",
            "candidate",
            "prompt",
            "hidden",
        ):
            cases.append((f"runtime target {prefix}", advisory_value(target_ids=[f"{prefix}:runtime-001"])))
        newline_target = advisory_value(target_ids=["npc:visible-advisory\n"])
        cases.append(("newline target", newline_target))
        oversized_turn = advisory_value()
        oversized_turn["freshness"]["as_of_turn_id"] = 9_007_199_254_740_992  # type: ignore[index]
        cases.append(("oversized turn", oversized_turn))
        invalid_evidence_ref = advisory_value()
        invalid_evidence_ref["evidence"][0]["ref_id"] = "NOT_CANONICAL"  # type: ignore[index]
        cases.append(("invalid evidence ref", invalid_evidence_ref))
        invalid_event_ref = advisory_value()
        invalid_event_ref["freshness"]["source_event_ids"] = ["trace:not-an-event"]  # type: ignore[index]
        cases.append(("invalid freshness event", invalid_event_ref))
        invalid_trace_ref = advisory_value()
        invalid_trace_ref["provenance"]["trace_id"] = "NOT_CANONICAL"  # type: ignore[index]
        cases.append(("invalid trace ref", invalid_trace_ref))
        invalid_source_ref = advisory_value()
        invalid_source_ref["provenance"]["source_ids"] = ["NOT_CANONICAL"]  # type: ignore[index]
        cases.append(("invalid provenance source", invalid_source_ref))
        for prefix in ("provider", "session", "prompt", "hidden", "commit", "save"):
            sensitive_source = advisory_value()
            sensitive_source["provenance"]["source_ids"] = [f"{prefix}:sensitive-source"]  # type: ignore[index]
            cases.append((f"sensitive provenance source {prefix}", sensitive_source))
        float_evidence_turn = advisory_value()
        float_evidence_turn["evidence"][0]["as_of_turn_id"] = 1.0  # type: ignore[index]
        cases.append(("float evidence turn", float_evidence_turn))
        float_freshness_turn = advisory_value()
        float_freshness_turn["freshness"]["as_of_turn_id"] = 1.0  # type: ignore[index]
        cases.append(("float freshness turn", float_freshness_turn))
        mismatched_relationship = advisory_value(
            evidence=[{"kind": "relationship", "ref_id": "npc:not-a-relationship", "as_of_turn_id": 1}]
        )
        cases.append(("mismatched relationship ref", mismatched_relationship))
        malformed_reference = advisory_value(
            evidence=[{"kind": "entity", "ref_id": "npc:::broken", "as_of_turn_id": 1}]
        )
        cases.append(("malformed reference", malformed_reference))

        for label, value in cases:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, r"^\$"):
                    normalize_resident_ai_advisory(value)

    def test_structural_budget_rejects_every_bounded_failure_class_before_schema(self) -> None:
        cyclic = advisory_value()
        cyclic["cycle"] = cyclic
        deep: object = "leaf"
        for _ in range(20):
            deep = {"nested": deep}
        deeply_nested = advisory_value()
        deeply_nested["extra"] = deep
        oversized = advisory_value()
        oversized["source_assistant"] = "x" * 5000
        oversized_container = advisory_value()
        oversized_container["extra"] = list(range(65))
        oversized_nodes = advisory_value()
        oversized_nodes["extra"] = [[index] * 8 for index in range(64)]
        oversized_total_text = advisory_value()
        oversized_total_text["extra"] = ["x" * 512 for _ in range(64)]

        class StatefulDict(dict):
            pass

        class StatefulList(list):
            pass

        class HostileStr(str):
            def __len__(self):
                raise RuntimeError("SECRET_SCALAR_CANARY")

        class HostileInt(int):
            def __abs__(self):
                raise RuntimeError("SECRET_SCALAR_CANARY")

        class HostileKey(str):
            def __len__(self):
                raise RuntimeError("SECRET_KEY_CANARY")

        stateful_root = StatefulDict(advisory_value())
        stateful_nested = advisory_value()
        stateful_nested["target_ids"] = StatefulList(["npc:visible-advisory"])
        hostile_string = advisory_value()
        hostile_string["source_assistant"] = HostileStr("resident-context-summary")
        hostile_integer = advisory_value()
        hostile_integer["freshness"]["as_of_turn_id"] = HostileInt(1)  # type: ignore[index]
        hostile_key = advisory_value()
        hostile_key[HostileKey("extra")] = True

        for value in (
            cyclic,
            deeply_nested,
            oversized,
            oversized_container,
            oversized_nodes,
            oversized_total_text,
            stateful_root,
            stateful_nested,
            hostile_string,
            hostile_integer,
            hostile_key,
        ):
            with self.assertRaisesRegex(ValueError, r"^\$") as raised:
                normalize_resident_ai_advisory(value)
            self.assertNotIn("SECRET_SCALAR_CANARY", str(raised.exception))
            self.assertNotIn("SECRET_KEY_CANARY", str(raised.exception))

    def test_schema_maximum_payload_fits_structural_budgets(self) -> None:
        def maximum_id(prefix: str, index: int) -> str:
            base = f"{prefix}:{index}-"
            return base + ("x" * (160 - len(base)))

        value = advisory_value(
            target_ids=[maximum_id("npc", index) for index in range(32)],
            evidence=[
                {
                    "kind": "entity",
                    "ref_id": maximum_id("npc", 100 + index),
                    "as_of_turn_id": 9_007_199_254_740_991,
                }
                for index in range(64)
            ],
        )
        value["freshness"]["source_event_ids"] = [  # type: ignore[index]
            maximum_id("event", index) for index in range(32)
        ]
        value["provenance"]["trace_id"] = maximum_id("advisory", 999)  # type: ignore[index]
        value["provenance"]["source_ids"] = [  # type: ignore[index]
            maximum_id("turn", index) for index in range(32)
        ]
        value["source_assistant"] = "a" * 120

        self.assertEqual(validate_ai_output_schema("resident_ai_advisory.schema.json", value), [])
        self.assertEqual(len(normalize_resident_ai_advisory(value).evidence), 64)

    def test_normalizer_uses_snapshot_after_preflight(self) -> None:
        source = advisory_value()

        def mutate_caller_after_snapshot(schema_name, snapshot):
            source["target_ids"][0] = "runtime:mutated"  # type: ignore[index]
            return validate_ai_output_schema(schema_name, snapshot)

        with mock.patch(
            "rpg_engine.ai.advisory.validate_ai_output_schema",
            side_effect=mutate_caller_after_snapshot,
        ):
            result = normalize_resident_ai_advisory(source)

        self.assertEqual(result.target_ids, ("npc:visible-advisory",))
        self.assertEqual(source["target_ids"], ["runtime:mutated"])

    def test_nested_colon_clock_ids_follow_progress_contract(self) -> None:
        value = advisory_value(
            target_ids=["clock:arc::phase-1:"],
            evidence=[{"kind": "progress", "ref_id": "clock:arc::phase-1:", "as_of_turn_id": 1}],
        )

        result = normalize_resident_ai_advisory(value)

        self.assertEqual(result.target_ids, ("clock:arc::phase-1:",))
        self.assertEqual(result.evidence[0].ref_id, "clock:arc::phase-1:")

    def test_authority_smuggling_keys_are_rejected_after_unicode_canonicalization(self) -> None:
        keys = (
            "human_confirmed",
            "ＨＵＭＡＮ​－ＣＯＮＦＩＲＭＥＤ",
            "approve.proposal",
            "hidden access",
            "raw-delta",
            "save_authorized",
            "profile escalation",
            "validation.bypass",
            "private_reasoning",
            "commit",
            "commi\u0301t",
            "commit_authority",
            "proposal_approval",
            "player_confirmation",
            "fact_write_authority",
            "authority",
            "approval",
            "confirmation",
        )
        for key in keys:
            with self.subTest(key=key):
                value = advisory_value()
                value["provenance"][key] = False  # type: ignore[index]
                with mock.patch("rpg_engine.ai.advisory.validate_ai_output_schema") as validator:
                    with self.assertRaisesRegex(ValueError, r"forbidden authority field"):
                        normalize_resident_ai_advisory(value)
                    validator.assert_not_called()

    def test_schema_errors_redact_attacker_controlled_keys_values_and_validator_failures(self) -> None:
        values = []
        invalid_value = advisory_value()
        invalid_value["source_assistant"] = "RAW PROMPT SECRET"
        values.append(invalid_value)
        unknown_key = advisory_value()
        unknown_key["PRIVATE_REASONING_CANARY"] = True
        values.append(unknown_key)

        for value in values:
            with self.assertRaises(ValueError) as raised:
                normalize_resident_ai_advisory(value)
            self.assertTrue(str(raised.exception).startswith("$"))
            self.assertNotIn("RAW PROMPT SECRET", str(raised.exception))
            self.assertNotIn("PRIVATE_REASONING_CANARY", str(raised.exception))

        invalid_known_field = advisory_value()
        invalid_known_field["source_assistant"] = "RAW PROMPT SECRET"
        with self.assertRaisesRegex(ValueError, r"^\$\.source_assistant: invalid advisory envelope$"):
            normalize_resident_ai_advisory(invalid_known_field)

        oversized_unknown_key = advisory_value()
        oversized_unknown_key["RAW_PROMPT_SECRET"] = "x" * 513
        with self.assertRaises(ValueError) as raised:
            normalize_resident_ai_advisory(oversized_unknown_key)
        self.assertEqual(str(raised.exception), "$[*]: string exceeds length budget")
        self.assertNotIn("RAW_PROMPT_SECRET", str(raised.exception))

        with mock.patch("rpg_engine.ai.advisory.validate_ai_output_schema", side_effect=RuntimeError("SECRET")):
            with self.assertRaisesRegex(ValueError, r"^\$: advisory schema validation failed$") as raised:
                normalize_resident_ai_advisory(advisory_value())
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        with mock.patch(
            "rpg_engine.ai.advisory._walk_json_structure",
            side_effect=RuntimeError("CONCURRENT_MUTATION_SECRET"),
        ):
            with self.assertRaisesRegex(ValueError, r"^\$: structure traversal failed$") as raised:
                normalize_resident_ai_advisory(advisory_value())
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)
            self.assertNotIn("CONCURRENT_MUTATION_SECRET", str(raised.exception))

        with mock.patch(
            "rpg_engine.ai.advisory._copy_json_value",
            side_effect=RuntimeError("SNAPSHOT_PRIVATE_CANARY"),
        ):
            with self.assertRaisesRegex(ValueError, r"^\$: advisory snapshot failed$") as raised:
                normalize_resident_ai_advisory(advisory_value())
            self.assertIsNone(raised.exception.__cause__)
            self.assertIsNone(raised.exception.__context__)

        traceback_value = advisory_value()
        traceback_value["source_assistant"] = "RAW PROMPT TRACEBACK CANARY"
        with self.assertRaises(ValueError) as raised:
            normalize_resident_ai_advisory(traceback_value)
        frames = []
        current = raised.exception.__traceback__
        while current is not None:
            if current.tb_frame.f_code.co_filename.endswith("rpg_engine/ai/advisory.py"):
                frames.append(repr(current.tb_frame.f_locals))
            current = current.tb_next
        self.assertNotIn("RAW PROMPT TRACEBACK CANARY", "".join(frames))

    def test_snapshot_copy_rechecks_budgets_after_preflight_mutation(self) -> None:
        value = advisory_value()
        original_validate = advisory_module._validate_json_structure
        calls = 0

        def mutate_after_preflight(candidate):
            nonlocal calls
            calls += 1
            original_validate(candidate)
            if calls == 1:
                candidate["evidence"].extend(candidate["evidence"] * 128)

        with mock.patch(
            "rpg_engine.ai.advisory._validate_json_structure",
            side_effect=mutate_after_preflight,
        ):
            with self.assertRaisesRegex(ValueError, r"advisory snapshot failed"):
                normalize_resident_ai_advisory(value)

    def test_maintenance_serializer_is_safe_stable_and_side_effect_free(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())
        first = resident_ai_advisory_to_maintenance_dict(envelope)
        second = resident_ai_advisory_to_maintenance_dict(envelope)

        self.assertEqual(first, second)
        self.assertEqual(first["provenance"]["trace_id"], "advisory:trace-001")
        self.assertEqual(first["authority"], authority_contract())
        self.assertNotIn("private_reasoning", json.dumps(first, ensure_ascii=False).lower())

    def test_serializers_reject_directly_constructed_unvalidated_envelopes(self) -> None:
        forged = ResidentAIAdvisory(
            advisory_type="PRIVATE_REASONING_CANARY",
            target_ids=["npc:visible-advisory"],  # type: ignore[arg-type]
            evidence=(AdvisoryEvidence("entity", "npc:visible-advisory", 1),),
            confidence=math.nan,
            freshness=AdvisoryFreshness("current", 1, ()),
            visibility_mode="player",
            source_assistant="RAW_PROMPT_CANARY",
            schema_version="wrong",
            proposed_next_workflow="commit --force",
            provenance=AdvisoryProvenance("trace:forged", ()),
            authority=AdvisoryAuthority(can_commit=True),
        )

        with self.assertRaises(ValueError):
            resident_ai_advisory_to_maintenance_dict(forged)
        conn = sqlite3.connect(":memory:")
        try:
            self.assertEqual(
                resident_ai_advisory_to_player_dict(forged, conn),
                {"ok": False, "status": "unavailable", "advisory": True, "no_direct_writes": True},
            )
        finally:
            conn.close()

        valid = normalize_resident_ai_advisory(advisory_value())
        forged_authority = ResidentAIAdvisory(
            advisory_type=valid.advisory_type,
            target_ids=valid.target_ids,
            evidence=valid.evidence,
            confidence=valid.confidence,
            freshness=valid.freshness,
            visibility_mode=valid.visibility_mode,
            source_assistant=valid.source_assistant,
            schema_version=valid.schema_version,
            proposed_next_workflow=valid.proposed_next_workflow,
            provenance=valid.provenance,
            authority=AdvisoryAuthority(can_commit=True),
        )
        with self.assertRaisesRegex(ValueError, r"^\$\.authority"):
            forged_authority.to_dict()
        with self.assertRaisesRegex(ValueError, r"^\$\.authority"):
            resident_ai_advisory_to_maintenance_dict(forged_authority)

        integer_authority = AdvisoryAuthority(advisory_only=1, can_commit=0)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, r"^\$\.authority"):
            integer_authority.to_dict()

        class HostileIterable:
            def __iter__(self):
                raise RuntimeError("SECRET_ITERATION_CANARY")

        hostile_collections = ResidentAIAdvisory(
            advisory_type=valid.advisory_type,
            target_ids=HostileIterable(),  # type: ignore[arg-type]
            evidence=valid.evidence,
            confidence=valid.confidence,
            freshness=valid.freshness,
            visibility_mode=valid.visibility_mode,
            source_assistant=valid.source_assistant,
            schema_version=valid.schema_version,
            proposed_next_workflow=valid.proposed_next_workflow,
            provenance=valid.provenance,
            authority=valid.authority,
        )
        with self.assertRaisesRegex(ValueError, r"advisory collections must be tuples") as raised:
            hostile_collections.to_dict()
        self.assertNotIn("SECRET_ITERATION_CANARY", str(raised.exception))

        oversized = ResidentAIAdvisory(
            advisory_type=valid.advisory_type,
            target_ids=valid.target_ids,
            evidence=(valid.evidence[0],) * 65,
            confidence=valid.confidence,
            freshness=valid.freshness,
            visibility_mode=valid.visibility_mode,
            source_assistant=valid.source_assistant,
            schema_version=valid.schema_version,
            proposed_next_workflow=valid.proposed_next_workflow,
            provenance=valid.provenance,
            authority=valid.authority,
        )
        with mock.patch.object(AdvisoryEvidence, "to_dict") as materialize:
            with self.assertRaisesRegex(ValueError, r"^\$\.evidence: advisory collection exceeds item budget$"):
                oversized.to_dict()
            materialize.assert_not_called()

        concurrent = normalize_resident_ai_advisory(advisory_value())
        original_authority_check = advisory_module._is_canonical_authority

        def replace_after_bounds(authority):
            object.__setattr__(concurrent, "evidence", (concurrent.evidence[0],) * 100_000)
            return original_authority_check(authority)

        with mock.patch(
            "rpg_engine.ai.advisory._is_canonical_authority",
            side_effect=replace_after_bounds,
        ):
            serialized = concurrent.to_dict()
        self.assertEqual(len(serialized["evidence"]), 1)

    def test_serializer_tracebacks_do_not_retain_rejected_envelope_values(self) -> None:
        valid = normalize_resident_ai_advisory(advisory_value())
        forged = ResidentAIAdvisory(
            advisory_type=valid.advisory_type,
            target_ids=valid.target_ids,
            evidence=valid.evidence,
            confidence=valid.confidence,
            freshness=valid.freshness,
            visibility_mode=valid.visibility_mode,
            source_assistant="RAW_PROMPT_SERIALIZER_TRACEBACK_CANARY",
            schema_version=valid.schema_version,
            proposed_next_workflow=valid.proposed_next_workflow,
            provenance=valid.provenance,
            authority=valid.authority,
        )

        for serializer in (forged.to_dict, lambda: resident_ai_advisory_to_maintenance_dict(forged)):
            with self.subTest(serializer=serializer):
                with self.assertRaises(ValueError) as raised:
                    serializer()
                frames = []
                current = raised.exception.__traceback__
                while current is not None:
                    if current.tb_frame.f_code.co_filename.endswith("rpg_engine/ai/advisory.py"):
                        frames.append(repr(current.tb_frame.f_locals))
                    current = current.tb_next
                self.assertNotIn("RAW_PROMPT_SERIALIZER_TRACEBACK_CANARY", "".join(frames))

        gm = normalize_resident_ai_advisory(
            advisory_value(
                target_ids=["npc:gm-secret-traceback-canary"],
                visibility_mode="gm",
            )
        )
        original_raw_dict = ResidentAIAdvisory._raw_dict
        calls = 0

        def fail_second_materialization(instance):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("second materialization failed")
            return original_raw_dict(instance)

        with mock.patch.object(
            ResidentAIAdvisory,
            "_raw_dict",
            autospec=True,
            side_effect=fail_second_materialization,
        ):
            with self.assertRaisesRegex(ValueError, r"advisory serialization failed") as raised:
                gm.to_dict()
        frames = []
        current = raised.exception.__traceback__
        while current is not None:
            if current.tb_frame.f_code.co_filename.endswith("rpg_engine/ai/advisory.py"):
                frames.append(repr(current.tb_frame.f_locals))
            current = current.tb_next
        self.assertNotIn("npc:gm-secret-traceback-canary", "".join(frames))


class ResidentAIAdvisoryPlayerProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.campaign_root = copy_initialized_minimal(Path(self.temp_dir.name))
        self.campaign = load_campaign(self.campaign_root)
        self.conn = connect(self.campaign)
        upsert_entity(
            self.conn,
            {
                "id": "npc:visible-advisory",
                "type": "character",
                "name": "Visible Advisory Target",
                "visibility": "known",
                "summary": "safe",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "npc:hidden-advisory",
                "type": "character",
                "name": "HIDDEN_ADVISORY_CANARY",
                "aliases": ["HIDDEN_ALIAS_CANARY"],
                "visibility": "hidden",
                "summary": "PRIVATE_REASONING_CANARY RAW_DELTA_CANARY",
            },
        )
        upsert_clock(
            self.conn,
            {
                "id": "clock:hidden-advisory",
                "name": "HIDDEN_CLOCK_CANARY",
                "summary": "UNSAFE_PROPOSAL_CANARY",
                "clock_type": "threat",
                "segments_total": 4,
                "segments_filled": 1,
                "visibility": "hidden",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "setting:hidden-advisory",
                "type": "world_setting",
                "name": "HIDDEN_WORLD_CANARY",
                "visibility": "hidden",
                "summary": "PROVIDER_BODY_CANARY RAW_PROMPT_CANARY",
            },
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def test_player_projection_filters_targets_and_evidence_with_authoritative_reads(self) -> None:
        value = advisory_value(
            target_ids=[
                "npc:visible-advisory",
                "npc:hidden-advisory",
                "clock:hidden-advisory",
                "setting:hidden-advisory",
                "npc:missing-advisory",
            ],
            evidence=[
                {"kind": "entity", "ref_id": "npc:visible-advisory", "as_of_turn_id": 1},
                {"kind": "entity", "ref_id": "npc:hidden-advisory", "as_of_turn_id": 1},
                {"kind": "progress", "ref_id": "clock:hidden-advisory", "as_of_turn_id": 1},
                {"kind": "world_setting", "ref_id": "setting:hidden-advisory", "as_of_turn_id": 1},
                {"kind": "event", "ref_id": "event:seed", "as_of_turn_id": 1},
            ],
        )
        result = resident_ai_advisory_to_player_dict(normalize_resident_ai_advisory(value), self.conn)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["target_ids"], ["npc:visible-advisory"])
        self.assertEqual(
            result["evidence"],
            [{"kind": "entity", "ref_id": "npc:visible-advisory"}],
        )
        self.assertEqual(
            set(result),
            {
                "ok",
                "status",
                "advisory",
                "no_direct_writes",
                "target_ids",
                "evidence",
                "schema_version",
                "authority",
            },
        )
        for token in (
            "npc:hidden-advisory",
            "clock:hidden-advisory",
            "setting:hidden-advisory",
            "npc:missing-advisory",
            "HIDDEN_ADVISORY_CANARY",
            "HIDDEN_ALIAS_CANARY",
            "PRIVATE_REASONING_CANARY",
            "RAW_DELTA_CANARY",
            "HIDDEN_CLOCK_CANARY",
            "UNSAFE_PROPOSAL_CANARY",
            "HIDDEN_WORLD_CANARY",
            "PROVIDER_BODY_CANARY",
            "RAW_PROMPT_CANARY",
            "event:seed",
        ):
            self.assertNotIn(token, rendered)
        self.assertEqual(result["authority"], authority_contract())

    def test_player_projection_dispatches_entity_refs_through_actual_typed_contract(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "rel:hidden-endpoint-advisory",
                "type": "Relationship",
                "name": "Unsafe relationship",
                "visibility": "known",
                "summary": "must remain unavailable",
                "details": {
                    "source_id": "npc:visible-advisory",
                    "target_id": "npc:hidden-advisory",
                    "kind": "knows",
                },
            },
        )
        self.conn.commit()
        value = advisory_value(
            target_ids=["npc:visible-advisory", "rel:hidden-endpoint-advisory"],
            evidence=[
                {
                    "kind": "entity",
                    "ref_id": "rel:hidden-endpoint-advisory",
                    "as_of_turn_id": 1,
                }
            ],
        )

        result = resident_ai_advisory_to_player_dict(normalize_resident_ai_advisory(value), self.conn)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["target_ids"], ["npc:visible-advisory"])
        self.assertEqual(result["evidence"], [])
        self.assertNotIn("rel:hidden-endpoint-advisory", json.dumps(result, sort_keys=True))

    def test_player_projection_accepts_visible_typed_evidence_branches(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "npc:visible-second-advisory",
                "type": "character",
                "name": "Second visible target",
                "visibility": "known",
                "summary": "safe",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "rel:visible-advisory",
                "type": "relationship",
                "name": "Visible relationship",
                "visibility": "known",
                "summary": "safe",
                "details": {
                    "source_id": "npc:visible-advisory",
                    "target_id": "npc:visible-second-advisory",
                    "kind": "knows",
                },
            },
        )
        upsert_clock(
            self.conn,
            {
                "id": "clock:visible-advisory",
                "name": "Visible clock",
                "summary": "safe",
                "clock_type": "progress",
                "segments_total": 4,
                "segments_filled": 1,
                "visibility": "known",
            },
        )
        upsert_world_setting(
            SimpleNamespace(conn=self.conn, turn_id="turn:seed"),
            {
                "id": "world:visible-advisory",
                "name": "Visible world setting",
                "summary": "safe",
                "category": "weather",
                "visibility": "known",
            },
        )
        upsert_rule(
            self.conn,
            {
                "id": "rule:visible-advisory",
                "statement": "Visible rule",
                "category": "general",
                "scope": "world",
            },
        )
        self.conn.commit()
        evidence = [
            {"kind": "relationship", "ref_id": "rel:visible-advisory", "as_of_turn_id": 1},
            {"kind": "progress", "ref_id": "clock:visible-advisory", "as_of_turn_id": 1},
            {"kind": "world_setting", "ref_id": "world:visible-advisory", "as_of_turn_id": 1},
            {"kind": "rule", "ref_id": "rule:visible-advisory", "as_of_turn_id": 1},
        ]

        result = resident_ai_advisory_to_player_dict(
            normalize_resident_ai_advisory(advisory_value(evidence=evidence)),
            self.conn,
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(
            result["evidence"],
            [{"kind": item["kind"], "ref_id": item["ref_id"]} for item in evidence],
        )

    def test_single_reference_read_failure_omits_only_that_reference(self) -> None:
        value = advisory_value(
            target_ids=["npc:visible-advisory", "npc:broken-advisory"],
            evidence=[
                {"kind": "entity", "ref_id": "npc:visible-advisory", "as_of_turn_id": 1},
                {"kind": "entity", "ref_id": "npc:broken-advisory", "as_of_turn_id": 1},
            ],
        )

        def selective_read(conn, entity_id, **kwargs):
            if entity_id == "npc:broken-advisory":
                raise sqlite3.DatabaseError("corrupt reference")
            return read_entity(conn, entity_id, **kwargs)

        with mock.patch("rpg_engine.ai.advisory.read_entity", side_effect=selective_read):
            result = resident_ai_advisory_to_player_dict(normalize_resident_ai_advisory(value), self.conn)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["target_ids"], ["npc:visible-advisory"])
        self.assertEqual(
            result["evidence"],
            [{"kind": "entity", "ref_id": "npc:visible-advisory"}],
        )

    def test_typed_prefixes_fail_closed_when_stored_entity_type_is_malformed(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "npc:visible-second-advisory",
                "type": "character",
                "name": "Second visible target",
                "visibility": "known",
                "summary": "safe",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "rel:malformed-advisory",
                "type": "character",
                "name": "Malformed relationship",
                "visibility": "known",
                "summary": "must not pass generic entity access",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "clock:malformed-advisory",
                "type": "relationship",
                "name": "Malformed clock",
                "visibility": "known",
                "summary": "must not pass relationship access",
                "details": {
                    "source_id": "npc:visible-advisory",
                    "target_id": "npc:visible-second-advisory",
                    "kind": "knows",
                },
            },
        )
        for entity_id in ("rule:malformed-advisory", "world:malformed-advisory"):
            upsert_entity(
                self.conn,
                {
                    "id": entity_id,
                    "type": "character",
                    "name": "Malformed typed entity",
                    "visibility": "known",
                    "summary": "must not pass prefix contract",
                },
            )
        self.conn.commit()
        value = advisory_value(
            target_ids=[
                "npc:visible-advisory",
                "rel:malformed-advisory",
                "clock:malformed-advisory",
                "rule:malformed-advisory",
                "world:malformed-advisory",
            ],
            evidence=[
                {"kind": "entity", "ref_id": "rel:malformed-advisory", "as_of_turn_id": 1},
                {"kind": "entity", "ref_id": "clock:malformed-advisory", "as_of_turn_id": 1},
                {"kind": "entity", "ref_id": "rule:malformed-advisory", "as_of_turn_id": 1},
                {"kind": "entity", "ref_id": "world:malformed-advisory", "as_of_turn_id": 1},
            ],
        )

        result = resident_ai_advisory_to_player_dict(normalize_resident_ai_advisory(value), self.conn)

        self.assertEqual(result["target_ids"], ["npc:visible-advisory"])
        self.assertEqual(result["evidence"], [])

    def test_player_serializer_runs_strict_schema_validation_once(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())

        with mock.patch(
            "rpg_engine.ai.advisory.validate_ai_output_schema",
            wraps=validate_ai_output_schema,
        ) as validator:
            result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(result["status"], "available")
        self.assertEqual(validator.call_count, 1)

    def test_player_projection_reads_only_canonical_snapshot_after_revalidation(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())
        original_check = read_entity

        def mutate_original_after_snapshot(conn, target_id):
            object.__setattr__(envelope, "schema_version", "forged-after-validation")
            return original_check(conn, target_id, view="player") is not None

        with mock.patch(
            "rpg_engine.ai.advisory._player_visible_target",
            side_effect=mutate_original_after_snapshot,
        ):
            result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["schema_version"], "resident_ai_advisory:v1")

    def test_player_projection_failures_share_one_generic_unavailable_shape(self) -> None:
        generic = {
            "ok": False,
            "status": "unavailable",
            "advisory": True,
            "no_direct_writes": True,
        }
        hidden_only = normalize_resident_ai_advisory(
            advisory_value(
                target_ids=["npc:hidden-advisory"],
                evidence=[{"kind": "entity", "ref_id": "npc:hidden-advisory", "as_of_turn_id": 1}],
            )
        )
        missing_only = normalize_resident_ai_advisory(
            advisory_value(
                target_ids=["npc:missing-advisory"],
                evidence=[{"kind": "entity", "ref_id": "npc:missing-advisory", "as_of_turn_id": 1}],
            )
        )
        upsert_entity(
            self.conn,
            {
                "id": "npc:archived-advisory",
                "type": "character",
                "name": "Archived advisory target",
                "status": "archived",
                "visibility": "known",
                "summary": "archived",
            },
        )
        self.conn.commit()
        archived_only = normalize_resident_ai_advisory(
            advisory_value(
                target_ids=["npc:archived-advisory"],
                evidence=[{"kind": "entity", "ref_id": "npc:archived-advisory", "as_of_turn_id": 1}],
            )
        )
        gm = normalize_resident_ai_advisory(advisory_value(visibility_mode="gm"))

        self.assertEqual(resident_ai_advisory_to_player_dict(hidden_only, self.conn), generic)
        self.assertEqual(resident_ai_advisory_to_player_dict(missing_only, self.conn), generic)
        self.assertEqual(resident_ai_advisory_to_player_dict(archived_only, self.conn), generic)
        self.assertEqual(resident_ai_advisory_to_player_dict(gm, self.conn), generic)
        self.assertEqual(resident_ai_advisory_to_player_dict(hidden_only, None), generic)

        broken = sqlite3.connect(":memory:")
        broken.row_factory = sqlite3.Row
        try:
            self.assertEqual(resident_ai_advisory_to_player_dict(hidden_only, broken), generic)
        finally:
            broken.close()

    def test_unrelated_hidden_text_cannot_collide_with_fixed_projection_keys(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "npc:hidden-shape-canary",
                "type": "character",
                "name": "Hidden shape canary",
                "visibility": "hidden",
                "summary": "target_ids evidence ref_id",
            },
        )
        self.conn.commit()

        result = resident_ai_advisory_to_player_dict(
            normalize_resident_ai_advisory(advisory_value()),
            self.conn,
        )

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["target_ids"], ["npc:visible-advisory"])

    def test_hidden_id_prefix_cannot_change_public_reference_availability(self) -> None:
        upsert_entity(
            self.conn,
            {
                "id": "npc:oracle-secret",
                "type": "character",
                "name": "Hidden prefix",
                "visibility": "hidden",
                "summary": "hidden",
            },
        )
        upsert_entity(
            self.conn,
            {
                "id": "npc:oracle-secret-public",
                "type": "character",
                "name": "Public longer id",
                "visibility": "known",
                "summary": "safe",
            },
        )
        self.conn.commit()
        envelope = normalize_resident_ai_advisory(
            advisory_value(
                target_ids=["npc:oracle-secret-public"],
                evidence=[
                    {
                        "kind": "entity",
                        "ref_id": "npc:oracle-secret-public",
                        "as_of_turn_id": 1,
                    }
                ],
            )
        )

        upsert_entity(
            self.conn,
            {
                "id": "NPC:ORACLE-SECRET-PUBLIC",
                "type": "character",
                "name": "npc:oracle-secret-public",
                "aliases": ["npc:oracle-secret-public"],
                "visibility": "hidden",
                "summary": "hidden collision",
            },
        )
        self.conn.commit()

        with mock.patch(
            "rpg_engine.redaction.hidden_entity_refs",
            side_effect=RuntimeError("full hidden corpus must not be materialized"),
        ):
            result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(result["status"], "available")
        self.assertEqual(result["target_ids"], ["npc:oracle-secret-public"])
        self.assertEqual(result["evidence"], [{"kind": "entity", "ref_id": "npc:oracle-secret-public"}])

    def test_player_projection_rejects_noncanonical_nested_wire_types_after_redaction(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())
        corrupted_refs = {
            "target_ids": ["npc:visible-advisory"],
            "evidence": [{"kind": "entity", "ref_id": "npc:visible-advisory", "as_of_turn_id": True}],
        }

        with mock.patch(
            "rpg_engine.ai.advisory.redact_player_hidden_material",
            return_value=corrupted_refs,
        ):
            result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(
            result,
            {"ok": False, "status": "unavailable", "advisory": True, "no_direct_writes": True},
        )

    def test_player_projection_rejects_list_to_tuple_redactor_shape_change(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())

        with mock.patch(
            "rpg_engine.ai.advisory.redact_player_hidden_material",
            side_effect=lambda _conn, refs, **_kwargs: tuple(refs),
        ):
            result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(
            result,
            {"ok": False, "status": "unavailable", "advisory": True, "no_direct_writes": True},
        )

    def test_player_projection_rejects_temp_schema_shadow_tables(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())
        self.conn.execute(
            "create temp table entities as select * from main.entities where 0"
        )
        self.conn.execute(
            "insert into temp.entities select * from main.entities where id = 'npc:visible-advisory'"
        )

        result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(
            result,
            {"ok": False, "status": "unavailable", "advisory": True, "no_direct_writes": True},
        )

    def test_player_projection_rejects_attached_only_authoritative_tables(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())
        wrong_main = sqlite3.connect(":memory:")
        wrong_main.row_factory = sqlite3.Row
        try:
            wrong_main.execute("attach database ? as attached_save", (str(self.campaign.database_path),))

            result = resident_ai_advisory_to_player_dict(envelope, wrong_main)

            self.assertEqual(
                result,
                {"ok": False, "status": "unavailable", "advisory": True, "no_direct_writes": True},
            )
        finally:
            wrong_main.close()

    def test_structured_redactor_rejects_unbounded_or_noncanonical_ids(self) -> None:
        for ref_id in ("x" * 1_000_000, "not-a-canonical-reference"):
            with self.subTest(ref_id=ref_id[:32]):
                with self.assertRaisesRegex(ValueError, r"bounded list"):
                    redact_player_hidden_material(
                        self.conn,
                        [ref_id],
                        drop_empty=False,
                        structured_reference_ids=True,
                    )

    def test_player_projection_detects_in_place_redactor_mutation(self) -> None:
        envelope = normalize_resident_ai_advisory(advisory_value())

        def mutate_in_place(_conn, refs, **_kwargs):
            refs[0] = "npc:hidden-advisory"
            return refs

        with mock.patch(
            "rpg_engine.ai.advisory.redact_player_hidden_material",
            side_effect=mutate_in_place,
        ):
            result = resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertEqual(
            result,
            {"ok": False, "status": "unavailable", "advisory": True, "no_direct_writes": True},
        )

    def test_serializers_preserve_caller_transaction_and_database_state(self) -> None:
        before_turn = query_scalar(self.campaign.database_path, "select value from meta where key='current_turn_id'")
        self.conn.execute(
            "insert into meta(key, value) values('advisory_test_sentinel', 'pending') "
            "on conflict(key) do update set value=excluded.value"
        )
        changes_before = self.conn.total_changes
        self.assertTrue(self.conn.in_transaction)
        envelope = normalize_resident_ai_advisory(advisory_value())

        resident_ai_advisory_to_maintenance_dict(envelope)
        resident_ai_advisory_to_player_dict(envelope, self.conn)

        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(self.conn.total_changes, changes_before)
        self.assertEqual(
            self.conn.execute("select value from meta where key='advisory_test_sentinel'").fetchone()[0],
            "pending",
        )
        other = sqlite3.connect(self.campaign.database_path)
        try:
            self.assertIsNone(other.execute("select value from meta where key='advisory_test_sentinel'").fetchone())
        finally:
            other.close()
        self.assertEqual(
            self.conn.execute("select value from meta where key='current_turn_id'").fetchone()[0],
            before_turn,
        )


if __name__ == "__main__":
    unittest.main()
