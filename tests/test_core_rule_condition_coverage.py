from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rpg_engine.actions.base import (
    ActionOptionSpec,
    ActionResolverRegistry,
    ActionResolverSpec,
    ActionValidationResult,
    ResolutionResult,
    option_specs_for,
)
from rpg_engine.campaign_validation import (
    CampaignTestResult,
    CampaignValidationResult,
    SmokeCaseResult,
    as_list as campaign_as_list,
    check_contains,
    content_paths,
    dedupe as campaign_dedupe,
    first_random_table_result,
    load_smoke_cases,
    palette_paths,
    parse_capabilities,
    prefix_errors,
    relative_path,
    render_campaign_test,
    render_campaign_validation,
    run_smoke_case,
    validate_content_paths,
    validate_content_references,
    validate_no_v1_code_extensions,
    validate_palette_entry,
    validate_palettes,
    validate_random_tables,
    validate_required_files,
    validate_smoke_case_shape,
    validate_smoke_file,
    validate_v1_structure,
)
from rpg_engine.campaign import load_campaign
from rpg_engine.context.rendering import (
    append_ammo_table_context,
    append_context_table,
    append_detail_entry,
    append_range_bands_context,
    append_sequence_section,
    entity_context_level,
    escape_table_cell,
    format_context_quantity,
    format_context_value,
    render_ambiguous_candidates,
    render_context_entity,
    render_entity_hit,
    render_player_state,
    render_relevant_entities,
    trim_inline,
)
from rpg_engine.context.resolution import (
    EntityHit,
    add_hit,
    ambiguous_candidates,
    ambiguous_keywords,
    apply_semantic_entity_hints,
    as_list,
    collect_entity_hits,
    contains_any,
    dedupe_links,
    dedupe_rows,
    dedupe_texts,
    expand_related_entities,
    extract_entity_ids,
    find_candidate_entities,
    find_explicit_entity_matches,
    is_direct_hit,
    linked_entity_ids,
    linked_priority,
    maybe_add_entity,
    profile_links,
    recipe_links,
    resolve_exact_entity_label,
    salient_ambiguous_candidates,
    sanitize_fts_query,
    sort_hits,
)
from rpg_engine.content_validation import (
    collect_created_records,
    dedupe as content_dedupe,
    entity_exists,
    existing_entity,
    high_impact_warnings,
    ids_for_key,
    location_exists,
    nested_lookup,
    parse_json as content_parse_json,
    records_for_key,
    review_warning,
    table_entity_exists,
    validate_content_delta,
    validate_content_sources,
    validate_metadata,
)
from rpg_engine.content_types import get_default_registry
from rpg_engine.db import connect, upsert_clock, upsert_entity
from rpg_engine.intent_router import action_intent_from_dict, turn_contract_from_dict
from rpg_engine.proposal import (
    ApprovedOutcome,
    TurnProposal,
    collect_delta_result,
    collect_request_result,
    collect_resolution_result,
    intent_context_id_from_intent,
    load_json_payload,
    load_proposal,
    load_turn_proposal,
    outcome_status,
    parse_intent_confidence,
    preflight_id_from_intent,
    preflight_status_from_intent,
    provenance_string,
    rejected,
    turn_proposal_from_dict,
    validate_claims_against_response,
    validate_context_id_matches_intent,
    validate_contract_matches_intent,
    validate_delta_source,
    validate_string_list,
    validate_turn_proposal,
)
from rpg_engine.save_validation import (
    dedupe as save_dedupe,
    inspect_save_package,
    load_save_manifest,
    table_columns,
    table_count,
    table_exists as save_table_exists,
    validate_cards,
    validate_events_jsonl,
    validate_meta_compatibility,
    validate_migrations,
    validate_projection_state,
    validate_save_manifest,
    validate_search_projection,
    validate_snapshot_json,
    validate_sqlite_schema,
    validate_time_meta,
)
from rpg_engine.turn_assistant import (
    TurnAssistantOptions,
    render_action_contract_for_context,
    render_delta_validation_for_options,
    render_next_steps,
    render_preview_for_context,
    render_proposal_validation,
    render_response_lint,
    run_save_pipeline,
    run_turn_assistant,
)
from tests.helpers import copy_initialized_minimal


def intent_data(
    *,
    action: str | None = "test_action",
    confidence: str = "high",
    decision_trace: dict[str, object] | None = None,
    options: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "user_text": "执行测试动作",
        "mode": "action",
        "submode": action or "unknown",
        "action": action,
        "options": options or {},
        "confidence": confidence,
        "source": "test",
        "decision_trace": decision_trace or {},
    }


def contract_data(
    intent: dict[str, object],
    *,
    allowed: list[str] | None = None,
    profile: str = "player_turn_commit",
) -> dict[str, object]:
    return {
        "intent": intent,
        "required_template": "test.md",
        "response_headings": ["场景", "行动结果"],
        "requires_preview": True,
        "must_save": True,
        "allowed_delta_sources": allowed if allowed is not None else ["resolver_proposed", "human_edited"],
        "validation_profile": profile,
    }


def base_delta(**overrides: object) -> dict[str, object]:
    delta: dict[str, object] = {
        "user_text": "执行测试动作",
        "intent": "test_action",
        "changed": False,
        "summary": "No significant change.",
    }
    delta.update(overrides)
    return delta


def proposal_from_parts(
    *,
    intent: dict[str, object] | None = None,
    delta_source: str = "resolver_proposed",
    human_confirmed: bool = True,
    delta: dict[str, object] | None = None,
    contract: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
    context_id: str | None = None,
    claims: list[str] | None = None,
) -> TurnProposal:
    intent = intent or intent_data()
    return turn_proposal_from_dict(
        {
            "proposal_id": "proposal:test",
            "intent": intent,
            "context_id": context_id,
            "preview": {"ok": True},
            "response_text": "已执行测试动作。",
            "facts_used": ["fact:a"],
            "narrative_claims": claims or [],
            "delta": delta or base_delta(),
            "delta_source": delta_source,
            "provenance": provenance or {},
            "human_confirmed": human_confirmed,
            "turn_contract": contract or contract_data(intent),
        }
    )


def registry_with(status: str = "ready") -> ActionResolverRegistry:
    registry = ActionResolverRegistry()

    def request(_campaign, _conn, _context, options):
        if getattr(options, "missing", False):
            return ActionValidationResult(
                errors=("bad request",),
                warnings=("request warning",),
                missing_required=("target",),
            )
        return ActionValidationResult(warnings=("request warning",))

    def resolve(_campaign, _conn, _context, _options):
        return ResolutionResult(
            status=status,
            facts_used=("fact:a", "fact:b"),
            rules_applied=("rule:a",),
            confirmations=("confirm resolver",) if status != "ready" else (),
            warnings=("resolver warning",),
            proposed_delta=base_delta(),
            narrative_constraints=("stay grounded",),
        )

    def delta_contract(_campaign, _conn, _context, _options, _delta):
        return ActionValidationResult(
            errors=("bad delta",) if status == "blocked" else (),
            warnings=("delta warning",),
            missing_required=("delta_target",) if status == "needs_confirmation" else (),
        )

    registry.register(
        ActionResolverSpec(
            name="test_action",
            preview=lambda *_args: "preview",
            response_template="test.md",
            validate_request=request,
            resolve=resolve,
            validate_delta=delta_contract,
        )
    )
    return registry


def setup_context_fixture(conn: sqlite3.Connection) -> None:
    upsert_entity(
        conn,
        {
            "id": "loc:lab",
            "type": "location",
            "name": "实验场",
            "status": "active",
            "visibility": "known",
            "summary": "用于上下文测试的地点。",
            "location": {
                "description_short": "实验场短描述。",
                "biome": "forest",
                "safety_level": "guarded",
                "travel_minutes_from_home": 12,
                "resources": ["水", "木材", "蘑菇", "矿石", "草药"],
                "exits": ["北门", "南门", "河岸", "山路"],
            },
        },
    )
    conn.execute(
        "insert into meta(key, value) values('current_location_id', 'loc:lab') "
        "on conflict(key) do update set value=excluded.value"
    )
    conn.execute(
        "insert into meta(key, value) values('primary_energy_label', '体力') "
        "on conflict(key) do update set value=excluded.value"
    )
    conn.execute(
        "insert into meta(key, value) values('primary_energy_detail_key', 'stamina_bar') "
        "on conflict(key) do update set value=excluded.value"
    )
    conn.execute(
        "update entities set details_json=? where id='pc:traveler'",
        (json.dumps({"health": "ok", "stamina_bar": "████ 40%"}, ensure_ascii=False),),
    )
    upsert_entity(
        conn,
        {
            "id": "species:mushroom",
            "type": "species",
            "name": "蘑菇人",
            "status": "active",
            "visibility": "known",
            "summary": "孢子族群。",
        },
    )
    upsert_entity(
        conn,
        {
            "id": "char:neighbor",
            "type": "character",
            "name": "邻居",
            "status": "active",
            "visibility": "known",
            "location_id": "loc:lab",
            "summary": "可靠的邻居。",
            "aliases": ["Neighbor"],
            "character": {
                "species_id": "species:mushroom",
                "role": "npc",
                "attitude": "friendly",
                "trust": 3,
                "health_state": "healthy",
            },
            "details": {
                "known_abilities": ["辨认孢子"] * 4,
                "commitments": ["帮忙看守"] * 4,
                "unknowns": ["真实目的"] * 4,
                "linked_entities": ["item:bow"],
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:bow",
            "type": "item",
            "name": "测试弓",
            "status": "active",
            "visibility": "known",
            "owner_id": "pc:traveler",
            "summary": "带有多种档案的弓。",
            "aliases": ["弓", "Bow"],
            "item": {
                "category": "weapon",
                "quantity": 1,
                "unit": "把",
                "equipped_slot": "hands",
                "properties": {
                    "combat_profile": {
                        "role": "ranged",
                        "ready_state": "ready",
                        "noise": "low",
                        "wet_weather": "bad",
                        "range_bands": [{"band": str(i), "distance": f"{i}m", "use": "test", "risk": "low"} for i in range(6)],
                        "compatible_ammo": [{"id": f"item:arrow-{i}", "name": f"箭{i}", "role": "ammo", "notes": "ok"} for i in range(9)],
                        "constraints": ["c1", "c2", "c3", "c4", "c5", "c6"],
                        "risks": ["r1", "r2", "r3", "r4", "r5", "r6"],
                        "adjudication_rules": ["a1", "a2", "a3", "a4", "a5", "a6"],
                    },
                    "ammo_profile": {"compatible_weapon_id": "item:bow", "effect_type": "pierce", "risks": ["wet"]},
                    "melee_profile": {"role": "backup", "reach": "short", "risks": ["break"]},
                    "defense_profile": {"role": "none", "coverage": "low", "risks": ["gap"]},
                    "carry_profile": {"role": "carried", "capacity": "small", "risks": ["snag"]},
                },
            },
            "details": {
                "action_guidance": {"use": "aim", "avoid": "rain", "extra1": 1, "extra2": 2, "extra3": 3},
                "risk_profile": ["wet", "snap", "noise", "miss"],
                "source": "test",
                "custom": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "g": 7},
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": "item:arrow-0",
            "type": "item",
            "name": "测试箭",
            "status": "active",
            "visibility": "known",
            "owner_id": "pc:traveler",
            "summary": "弹药。",
            "item": {
                "category": "ammunition",
                "quantity": 2.0,
                "unit": "支",
                "properties": {"ammo_profile": {"compatible_weapon_id": "item:bow"}},
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": "recipe:test",
            "type": "recipe",
            "name": "测试配方",
            "status": "active",
            "visibility": "known",
            "summary": "配方。",
            "details": {
                "recipe_profile": {
                    "inputs": [{"id": "item:arrow-0"}],
                    "tools": [{"id": "item:bow"}],
                    "output": {"id": "item:trap"},
                },
                "linked": "char:neighbor loc:lab",
            },
        },
    )
    upsert_entity(conn, {"id": "item:trap", "type": "item", "name": "陷阱", "status": "active", "visibility": "known", "summary": "输出。", "item": {"quantity": 1}})
    upsert_entity(conn, {"id": "clock:plain", "type": "clock", "name": "空钟", "status": "active", "visibility": "known", "summary": "无 clock row。"})
    upsert_entity(conn, {"id": "clock:danger", "type": "clock", "name": "危险钟", "status": "active", "visibility": "known", "summary": "危险逼近。"})
    conn.execute(
        """
        insert or replace into clocks
        (entity_id, clock_type, segments_total, segments_filled, visibility, trigger_when_full, tick_rules_json)
        values ('clock:danger', 'danger', 4, 2, 'visible', '危险爆发', '{}')
        """
    )
    upsert_entity(conn, {"id": "rule:plain", "type": "rule", "name": "空规则", "status": "active", "visibility": "known", "summary": "无 rule row。"})
    upsert_entity(conn, {"id": "rule:player-agency", "type": "rule", "name": "玩家能动性", "status": "active", "visibility": "known", "summary": "玩家决定。"})
    conn.execute(
        """
        insert or replace into rules
        (entity_id, category, scope, statement, examples_json, exceptions_json, source, locked)
        values ('rule:player-agency', 'play', 'global', '玩家保留最终选择', '[]', '[]', 'test', 1)
        """
    )
    upsert_entity(conn, {"id": "rule:monster-tier", "type": "rule", "name": "威胁等级", "status": "active", "visibility": "known", "summary": "威胁分层。"})
    conn.commit()


class CoreRuleProposalCoverageTests(unittest.TestCase):
    def test_turn_proposal_shape_loading_render_and_helper_branches(self) -> None:
        intent = intent_data()
        proposal = proposal_from_parts(intent=intent, claims=["存在的叙事", "缺失的叙事"])
        roundtrip = proposal.to_dict()
        outcome = ApprovedOutcome(
            status="approved",
            proposal=proposal,
            facts_used=("fact:a",),
            rules_applied=("rule:a",),
            delta=base_delta(),
            confirmations=("confirm",),
            warnings=("warn",),
            errors=("error",),
            narrative_constraints=("constraint",),
        )
        errors: list[str] = []
        warnings: list[str] = []
        confirmations: list[str] = []
        collect_request_result(ActionValidationResult(errors=("e",), warnings=("w",), missing_required=("target",)), errors, warnings, confirmations)
        collect_resolution_result(ResolutionResult(status="needs_confirmation", warnings=("rw",), confirmations=("rc",)), warnings, confirmations)
        collect_delta_result(ActionValidationResult(warnings=("dw",), missing_required=("dm",)), errors, warnings, confirmations)

        with tempfile.TemporaryDirectory() as tmp:
            object_path = Path(tmp) / "proposal.json"
            list_path = Path(tmp) / "list.json"
            object_path.write_text(json.dumps(roundtrip, ensure_ascii=False), encoding="utf-8")
            list_path.write_text("[]", encoding="utf-8")
            loaded = load_turn_proposal(object_path)
            loaded_payload = load_proposal(object_path)
            with self.assertRaisesRegex(ValueError, "JSON root must be an object"):
                load_json_payload(list_path)

        invalid = {
            "unknown": True,
            "proposal_id": "",
            "intent": "bad",
            "context_id": 3,
            "preview": [],
            "response_text": 4,
            "delta": [],
            "delta_source": "",
            "provenance": [],
            "human_confirmed": "yes",
            "facts_used": "bad",
            "narrative_claims": ["", 3],
            "turn_contract": "bad",
        }
        with self.assertRaisesRegex(ValueError, "Invalid TurnProposal"):
            turn_proposal_from_dict(invalid)

        self.assertEqual(loaded.proposal_id, "proposal:test")
        self.assertEqual(loaded_payload["proposal_id"], "proposal:test")
        self.assertIn("Approved Delta", outcome.render())
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome_status([], []), "approved")
        self.assertEqual(outcome_status(["e"], []), "rejected")
        self.assertEqual(outcome_status([], ["c"]), "needs_confirmation")
        self.assertEqual(validate_string_list(None, "$.x", []), ())
        bad_list_errors: list[str] = []
        self.assertEqual(validate_string_list("bad", "$.x", bad_list_errors), ())
        self.assertIn("$.x: must be array", bad_list_errors)
        self.assertEqual(validate_claims_against_response((), None), [])
        self.assertIn("not checked", validate_claims_against_response(("claim",), None)[0])
        self.assertIn("缺失", validate_claims_against_response(("存在", "缺失"), "存在的叙事")[0])
        confidence_warnings: list[str] = []
        self.assertEqual(parse_intent_confidence("", confidence_warnings), None)
        self.assertEqual(parse_intent_confidence("explicit", confidence_warnings), 1.0)
        self.assertEqual(parse_intent_confidence("medium", confidence_warnings), 0.7)
        self.assertEqual(parse_intent_confidence("low", confidence_warnings), 0.4)
        self.assertIsNone(parse_intent_confidence("not-number", confidence_warnings))
        self.assertIsNone(parse_intent_confidence("2", confidence_warnings))
        self.assertTrue(any("non-numeric" in item for item in confidence_warnings))
        self.assertTrue(any("outside" in item for item in confidence_warnings))

    def test_validate_turn_proposal_action_context_and_resolution_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                valid = proposal_from_parts()
                approved = validate_turn_proposal(campaign, conn, valid, registry=registry_with("ready"))
                needs = validate_turn_proposal(
                    campaign,
                    conn,
                    proposal_from_parts(intent=intent_data(confidence="low")),
                    registry=registry_with("needs_confirmation"),
                )
                blocked = validate_turn_proposal(campaign, conn, valid, registry=registry_with("blocked"))
                no_action = validate_turn_proposal(
                    campaign,
                    conn,
                    proposal_from_parts(intent=intent_data(action=None), contract=contract_data(intent_data(action=None))),
                    registry=registry_with("ready"),
                )
                unknown = validate_turn_proposal(
                    campaign,
                    conn,
                    proposal_from_parts(intent=intent_data(action="missing"), contract=contract_data(intent_data(action="missing"))),
                    registry=registry_with("ready"),
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-proposal",
                        "name": "Hidden Proposal Clock",
                        "summary": "Hidden from player proposal validation.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "Hidden consequence.",
                    },
                )
                conn.commit()
                hidden_clock = validate_turn_proposal(
                    campaign,
                    conn,
                    proposal_from_parts(
                        delta=base_delta(
                            events=[{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                            tick_clocks=[{"id": "clock:hidden-proposal", "delta": 1}],
                        )
                    ),
                    registry=registry_with("ready"),
                )
                with self.assertRaises(TypeError):
                    validate_turn_proposal(campaign, conn, "bad")  # type: ignore[arg-type]

        self.assertEqual(approved.status, "approved")
        self.assertIn("request warning", "\n".join(approved.warnings))
        self.assertIn("fact:b", approved.facts_used)
        self.assertIn("stay grounded", approved.narrative_constraints)
        self.assertEqual(needs.status, "needs_confirmation")
        self.assertIn("proposal confidence is below approval threshold", needs.confirmations)
        self.assertTrue(any("resolver status is needs_confirmation" in item for item in needs.confirmations))
        self.assertTrue(any("delta_contract missing" in item for item in needs.confirmations))
        self.assertEqual(blocked.status, "rejected")
        self.assertIn("resolver status is blocked", blocked.errors)
        self.assertEqual(no_action.status, "rejected")
        self.assertIn("$.action: required", no_action.errors)
        self.assertEqual(unknown.status, "rejected")
        self.assertTrue(any("unknown action resolver" in item for item in unknown.errors))
        self.assertEqual(hidden_clock.status, "rejected")
        self.assertTrue(any("unavailable clock clock:hidden-proposal" in item for item in hidden_clock.errors))

    def test_proposal_delta_source_contract_and_preflight_identity_branches(self) -> None:
        proposal = proposal_from_parts(delta_source="response_draft", human_confirmed=False)
        errors: list[str] = []
        confirmations: list[str] = []
        validate_delta_source(proposal, errors, confirmations)
        invalid_source = proposal_from_parts(delta_source="bad-source")
        validate_delta_source(invalid_source, errors, confirmations)
        mismatch_contract = proposal_from_parts(
            intent=intent_data(action="test_action"),
            contract=contract_data(intent_data(action="other"), allowed=["maintenance_delta"], profile="preview_only"),
        )
        validate_contract_matches_intent(mismatch_contract, errors)
        no_contract = proposal_from_parts()
        object.__setattr__(no_contract, "turn_contract", None)
        validate_contract_matches_intent(no_contract, errors)

        trace = {
            "intent_ai": {
                "preflight": {
                    "status": "hit",
                    "record": {"id": "pre:1", "identity": {"intent_context_id": "ctx:trace"}},
                }
            }
        }
        intent = action_intent_from_dict(intent_data(decision_trace=trace))
        self.assertEqual(intent_context_id_from_intent(intent), "ctx:trace")
        self.assertEqual(preflight_id_from_intent(intent), "pre:1")
        self.assertEqual(preflight_status_from_intent(intent), "hit")
        self.assertIsNone(intent_context_id_from_intent(action_intent_from_dict(intent_data(decision_trace={"intent_context_id": ""}))))
        self.assertIsNone(preflight_id_from_intent(action_intent_from_dict(intent_data(decision_trace={"intent_ai": {"preflight": {"status": "miss"}}}))))
        self.assertIsNone(preflight_status_from_intent(action_intent_from_dict(intent_data(decision_trace={}))))

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("create table intent_preflight_cache(id text primary key, status text, intent_context_id text)")
            preflight_errors: list[str] = []
            validate_context_id_matches_intent(
                conn,
                proposal_from_parts(intent=intent_data(decision_trace=trace), provenance={"preflight_id": "pre:missing"}),
                preflight_errors,
            )
            conn.execute("insert into intent_preflight_cache values('pre:1', 'pending', 'ctx:cache')")
            validate_context_id_matches_intent(
                conn,
                proposal_from_parts(
                    intent=intent_data(decision_trace=trace),
                    provenance={"preflight_id": "pre:2", "intent_context_id": "wrong"},
                    context_id="wrong",
                ),
                preflight_errors,
            )
            validate_context_id_matches_intent(
                conn,
                proposal_from_parts(
                    intent=intent_data(decision_trace=trace),
                    provenance={"preflight_id": "pre:1"},
                    context_id=None,
                ),
                preflight_errors,
            )
            no_preflight_errors: list[str] = []
            validate_context_id_matches_intent(
                conn,
                proposal_from_parts(context_id="ctx:orphan", provenance={"intent_context_id": "ctx:orphan"}),
                no_preflight_errors,
            )
        finally:
            conn.close()

        self.assertIn("response_draft requires human confirmation before approval", confirmations)
        self.assertTrue(any("unsupported delta source" in item for item in errors))
        self.assertTrue(any("does not match proposal intent" in item for item in errors))
        self.assertTrue(any("player_turn_commit" in item for item in errors))
        self.assertTrue(any("turn_contract: required" in item for item in errors))
        self.assertIsNone(provenance_string(proposal_from_parts(provenance={"x": " "}), "x"))
        self.assertIn("$.provenance.preflight_id: unknown preflight id", preflight_errors)
        self.assertIn("$.provenance.preflight_id: does not match intent preflight id", preflight_errors)
        self.assertIn("$.provenance.preflight_id: cached preflight must be used after a hit", preflight_errors)
        self.assertTrue(any("does not match cached preflight context" in item for item in preflight_errors))
        self.assertTrue(any("required when preflight_id is present" in item for item in preflight_errors))
        self.assertIn("$.context_id: preflight context requires provenance.preflight_id", no_preflight_errors)
        self.assertIn("bad", rejected(proposal, errors=["bad", "bad"], warnings=["warn"]).render())


class CoreRuleContentAndSaveValidationCoverageTests(unittest.TestCase):
    def test_content_delta_metadata_references_warnings_and_source_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            content_dir = campaign.root / "content"
            content_dir.mkdir(exist_ok=True)
            (content_dir / "world_settings.yaml").write_text("world_settings: bad\n", encoding="utf-8")
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "species:hidden-rare",
                        "type": "species",
                        "name": "隐藏稀有物种",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "隐藏。",
                        "details": {"rarity": "rare"},
                    },
                )
                delta = {
                    "unknown": True,
                    "upsert_unknown": [],
                    "title": "",
                    "turn_id": "bad-turn",
                    "updated_turn_id": "turn:bad",
                    "expected_turn_id": "x",
                    "command_id": "!!",
                    "changed": "yes",
                    "events": {},
                    "meta": {"review_required": True, "bad": []},
                    "upsert_entities": [
                        "bad",
                        {"id": "item:new", "type": "item", "name": "新物品", "summary": "缺 item。", "location_id": "loc:missing"},
                        {
                            "id": "char:new",
                            "type": "character",
                            "name": "新人",
                            "summary": "缺物种。",
                            "character": {"species_id": "species:missing"},
                            "location_id": "loc:also-missing",
                        },
                        {
                            "id": "loc:new",
                            "type": "location",
                            "name": "新地点",
                            "summary": "父地点缺失。",
                            "location": {"parent_id": "loc:missing"},
                        },
                        {
                            "id": "plot:new",
                            "type": "crop_plot",
                            "name": "田畦",
                            "summary": "缺作物。",
                            "crop_plot": {"crop_entity_id": "plant:missing"},
                        },
                        {
                            "id": "species:hidden-rare",
                            "type": "species",
                            "name": "公开稀有",
                            "visibility": "known",
                            "summary": "公开。",
                            "details": {"resource_profile": {"rarity": "legendary"}},
                        },
                        {"id": "fstate:new", "type": "faction_state", "name": "新势力", "summary": "高影响。"},
                    ],
                    "upsert_routes": [
                        "bad",
                        {"id": "route:bad", "from_location_id": "loc:missing", "to_location_id": "loc:new"},
                    ],
                    "upsert_rules": [
                        {"id": "rule:new", "name": "规则", "summary": "新规则。"},
                    ],
                    "upsert_world_settings": [
                        {
                            "id": "world:new",
                            "name": "设定",
                            "summary": "新设定。",
                            "category": "weather",
                            "linked_rules": ["rule:missing"],
                            "linked_clocks": ["clock:missing"],
                            "linked_entities": ["loc:missing"],
                        }
                    ],
                }
                result = validate_content_delta(delta, conn)
                sources_result = validate_content_sources(
                    campaign,
                    conn,
                    [get_default_registry().get("world_setting")],
                )
                ok_result = validate_content_delta({"meta": {"reviewed_by": "tester"}, "upsert_entities": []}, conn)

        rendered = result.render()
        self.assertFalse(validate_content_delta("bad", sqlite3.connect(":memory:")).ok)
        self.assertIn("$.unknown: unknown top-level field", result.errors)
        self.assertIn("$.upsert_unknown: unknown top-level field", result.errors)
        self.assertTrue(any("must be non-empty string" in item for item in result.errors))
        self.assertTrue(any("must match turn:000001" in item for item in result.errors))
        self.assertIn("$.command_id: must be 3-128 safe identifier characters", result.errors)
        self.assertIn("$.changed: must be boolean", result.errors)
        self.assertIn("$.events: must be array", result.errors)
        self.assertIn("$.meta: keys must be strings and values must be scalar", result.errors)
        self.assertTrue(any(".item: required" in item for item in result.errors))
        self.assertTrue(any(".location_id: missing entity" in item for item in result.errors))
        self.assertTrue(any(".character.species_id" in item for item in result.errors))
        self.assertTrue(any(".location.parent_id" in item for item in result.errors))
        self.assertTrue(any(".crop_plot.crop_entity_id" in item for item in result.errors))
        self.assertTrue(any(".from_location_id" in item for item in result.errors))
        self.assertTrue(any(".linked_rules" in item for item in result.errors))
        self.assertTrue(any(".linked_clocks" in item for item in result.errors))
        self.assertTrue(any(".linked_entities" in item for item in result.errors))
        self.assertTrue(any("review marker present" in item for item in result.warnings))
        self.assertIn("FAILED", rendered)
        self.assertIn("warning", rendered)
        self.assertTrue(any("world_settings.yaml.world_settings: must be array" in item for item in sources_result.errors))
        self.assertTrue(ok_result.ok)
        self.assertIn("OK", ok_result.render())

        errors: list[str] = []
        validate_metadata({"meta": "bad"}, errors)
        self.assertIn("$.meta: must be object", errors)
        created_errors: list[str] = []
        created = collect_created_records(
            {
                "upsert_entities": [{"id": "same"}, {"id": "same"}],
                "upsert_world_settings": [{"id": "same"}],
            },
            get_default_registry().delta_specs(),
            created_errors,
        )
        self.assertEqual(created["same"]["id"], "same")
        self.assertTrue(any("duplicate record id" in item for item in created_errors))
        self.assertTrue(any("also appears" in item for item in created_errors))
        self.assertEqual(records_for_key({"x": "bad"}, "x"), [])
        self.assertEqual(ids_for_key({"x": [{"id": "a"}, {}, "bad"]}, "x"), {"a"})
        self.assertTrue(entity_exists(sqlite3.connect(":memory:"), "same", {"same"}))
        self.assertTrue(location_exists(sqlite3.connect(":memory:"), "loc:new", {"loc:new": {"type": "item", "location": {}}}))
        self.assertEqual(review_warning("msg", False), "msg; requires meta.review_required=true or meta.reviewed_by")
        self.assertEqual(nested_lookup({"a": "bad"}, ("a", "b")), None)
        self.assertEqual(content_parse_json("", []), [])
        self.assertEqual(content_parse_json("{bad", []), [])
        self.assertEqual(content_dedupe(["a", "a", "b"]), ["a", "b"])

    def test_save_validation_direct_error_branches_and_missing_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            save_dir = campaign.root
            bad_manifest = save_dir / "bad-save.yaml"
            bad_manifest.write_text("[", encoding="utf-8")
            list_manifest = save_dir / "list-save.yaml"
            list_manifest.write_text("- bad\n", encoding="utf-8")
            manifest_errors: list[str] = []
            self.assertEqual(load_save_manifest(save_dir / "missing.yaml", manifest_errors), {})
            self.assertEqual(load_save_manifest(bad_manifest, manifest_errors), {})
            self.assertEqual(load_save_manifest(list_manifest, manifest_errors), {})
            validate_save_manifest(campaign, {"campaign_id": "wrong", "campaign_version": "bad", "engine_version": "bad"}, manifest_errors)
            validate_meta_compatibility(campaign, {"campaign_id": "manifest"}, {"campaign_id": "meta"}, manifest_errors)
            time_errors: list[str] = []
            validate_time_meta({"current_game_day": "2", "current_time_block": "第 1 天 · 夜"}, time_errors)
            validate_time_meta({"current_game_day": "", "current_time_block": ""}, time_errors)
            validate_time_meta({"current_game_day": "2", "current_time_block": "夜晚"}, time_errors)

            with connect(campaign) as conn:
                schema_errors: list[str] = []
                validate_sqlite_schema(conn, schema_errors)
                migration_errors: list[str] = []
                validate_migrations(conn, migration_errors)
                conn.execute(
                    "insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at) "
                    "values('turn:000001', 's', 'u', 'wait', 'other', 0, 'now')"
                )
                conn.execute(
                    """
                    insert or ignore into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values('event:extra', 'turn:000001', '', 'note', '额外事件', '未投影事件。', '{}', 'test', 'now')
                    """
                )
                conn.execute("insert or replace into projection_state(name, version, last_turn_id, status, updated_at, last_error) values('events_jsonl', 0, 'turn:000001', 'dirty', 'now', null)")
                conn.execute("insert or replace into projection_state(name, version, last_turn_id, status, updated_at, last_error) values('search', 0, 'turn:seed', 'clean', 'now', null)")
                conn.execute("insert or replace into projection_state(name, version, last_turn_id, status, updated_at, last_error) values('snapshots', 1, 'turn:000001', 'clean', 'now', null)")
                conn.execute("insert or replace into outbox(id, topic, payload_json, status, attempts, created_at, processed_at, last_error) values('out:1','x','{}','pending',0,'now',null,null)")
                projection_errors: list[str] = []
                meta = {str(row["key"]): str(row["value"]) for row in conn.execute("select key, value from meta")}
                validate_projection_state(conn, meta, projection_errors)
                conn.execute("delete from fts_index")
                search_errors: list[str] = []
                validate_search_projection(conn, search_errors)
                conn.commit()

                events_path = save_dir / "bad-events.jsonl"
                events_path.write_text(
                    "\n".join(
                        [
                            "{bad",
                            "[]",
                            json.dumps({"event_id": ""}),
                            json.dumps({"event_id": "event:missing"}),
                            json.dumps({"event_id": "event:seed"}),
                            json.dumps({"event_id": "event:seed"}),
                        ]
                    ),
                    encoding="utf-8",
                )
                event_errors: list[str] = []
                validate_events_jsonl(events_path, conn, event_errors)

                snapshot_path = save_dir / "bad-snapshot.json"
                snapshot_errors: list[str] = []
                snapshot_path.write_text("{bad", encoding="utf-8")
                validate_snapshot_json(snapshot_path, snapshot_path, conn, meta, campaign.campaign_id, snapshot_errors)
                snapshot_path.write_text("[]", encoding="utf-8")
                validate_snapshot_json(snapshot_path, snapshot_path, conn, meta, campaign.campaign_id, snapshot_errors)
                snapshot_path.write_text(json.dumps({"campaign": {"id": "wrong"}, "meta": []}), encoding="utf-8")
                validate_snapshot_json(snapshot_path, snapshot_path, conn, meta, campaign.campaign_id, snapshot_errors)
                snapshot_path.write_text(json.dumps({"campaign": {"id": campaign.campaign_id}, "meta": {"current_turn_id": "wrong"}}), encoding="utf-8")
                validate_snapshot_json(snapshot_path, snapshot_path, conn, meta, campaign.campaign_id, snapshot_errors)

                cards_dir = save_dir / "bad-cards"
                cards_dir.mkdir()
                card_errors: list[str] = []
                validate_cards(cards_dir, conn, card_errors)

                count_missing = table_count(conn, "missing")
                columns = table_columns(conn, "entities")
                has_entities = save_table_exists(conn, "entities")

            missing_db_root = Path(tmp) / "missing-db"
            copy_initialized_minimal(missing_db_root)
            missing_db_campaign = missing_db_root / "campaign"
            (missing_db_campaign / "data" / "game.sqlite").unlink()
            package_report = inspect_save_package(missing_db_campaign)

        self.assertTrue(any("invalid YAML" in item for item in manifest_errors))
        self.assertIn("save.yaml: must be object", manifest_errors)
        self.assertTrue(any("save.yaml.campaign_id" in item for item in manifest_errors))
        self.assertIn("save.yaml.campaign_id does not match meta.campaign_id", manifest_errors)
        self.assertIn("meta.current_game_day 2 does not match current_time_block day 1", time_errors)
        self.assertEqual(schema_errors, [])
        self.assertEqual(migration_errors, [])
        self.assertTrue(any("projection_state.events_jsonl: status is dirty" in item for item in projection_errors))
        self.assertTrue(any("version 0 <" in item for item in projection_errors))
        self.assertTrue(any("last_turn_id turn:000001" in item for item in projection_errors))
        self.assertIn("outbox.out:1: status is pending", projection_errors)
        self.assertTrue(any("fts_index: expected" in item for item in search_errors))
        self.assertTrue(any("invalid JSON" in item for item in event_errors))
        self.assertTrue(any("must be object" in item for item in event_errors))
        self.assertTrue(any("missing event_id" in item for item in event_errors))
        self.assertTrue(any("not found in SQLite" in item for item in event_errors))
        self.assertTrue(any("duplicate event_id" in item for item in event_errors))
        self.assertTrue(any("missing SQLite event" in item for item in event_errors))
        self.assertTrue(any("snapshots/current.json: invalid JSON" in item for item in snapshot_errors))
        self.assertIn("snapshots/current.json: must be object", snapshot_errors)
        self.assertIn("snapshots/current.json.campaign.id: does not match campaign", snapshot_errors)
        self.assertIn("snapshots/current.json.meta: missing", snapshot_errors)
        self.assertTrue(any("snapshots/current.json.meta.current_turn_id" in item for item in snapshot_errors))
        self.assertIn("cards/INDEX.md: missing", card_errors)
        self.assertTrue(any("cards: missing generated card" in item for item in card_errors))
        self.assertEqual(count_missing, 0)
        self.assertIn("id", columns)
        self.assertTrue(has_entities)
        self.assertFalse(package_report["ok"])
        self.assertTrue(any("missing database" in item for item in package_report["errors"]))
        self.assertEqual(save_dedupe(["a", "a", "b"]), ["a", "b"])


class CoreRuleContextResolutionRenderingCoverageTests(unittest.TestCase):
    def test_context_resolution_semantic_ambiguity_links_and_sorting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                setup_context_fixture(conn)
                state = SimpleNamespace(
                    campaign=campaign,
                    conn=conn,
                    user_text="那个蘑菇是什么",
                    mode="query",
                    submode="scene",
                    max_depth=3,
                    entity_hits=[],
                    ambiguous_hits=[],
                    needs_user_confirmation=[],
                    semantic_suggestion=None,
                    semantic_alias_gaps=[],
                )
                collect_entity_hits(state)
                semantic_state = SimpleNamespace(
                    campaign=campaign,
                    conn=conn,
                    user_text="语义",
                    mode="query",
                    submode="entity",
                    max_depth=3,
                    entity_hits=[],
                    ambiguous_hits=[],
                    needs_user_confirmation=[],
                    semantic_suggestion={"targets": ["Neighbor", "可靠", "不存在标签"], "entities_mentioned": ["Bow"]},
                    semantic_alias_gaps=[],
                )
                apply_semantic_entity_hints(semantic_state)
                combat_state = SimpleNamespace(
                    campaign=campaign,
                    conn=conn,
                    user_text="射击",
                    mode="action",
                    submode="combat",
                    max_depth=3,
                    entity_hits=[
                        EntityHit("item:bow", "item", "测试弓", "弓", "active", None, "pc:traveler", "name contains", 95),
                        EntityHit("char:neighbor", "character", "邻居", "可靠", "active", "loc:lab", None, "name contains", 90),
                    ],
                    ambiguous_hits=[],
                    needs_user_confirmation=[],
                    semantic_suggestion=None,
                    semantic_alias_gaps=[],
                )
                expand_related_entities(combat_state)
                empty_label = resolve_exact_entity_label(conn, "")
                exact_rows = resolve_exact_entity_label(conn, "Neighbor")
                explicit_rows = find_explicit_entity_matches(conn, "我拿起弓")
                candidate_rows = find_candidate_entities(conn, "可靠", limit=3)
                no_candidate = find_candidate_entities(conn, "!!!", limit=3)
                ambiguous = ambiguous_candidates(conn, "那个菌在哪")
                salient = salient_ambiguous_candidates(conn)
                recipe_hit = EntityHit("recipe:test", "recipe", "测试配方", "", "active", None, None, "candidate", 70)
                bow_hit = EntityHit("item:bow", "item", "测试弓", "", "active", None, "pc:traveler", "candidate", 70)
                recipe_related = linked_entity_ids(conn, recipe_hit, combat_state)
                bow_related = linked_entity_ids(conn, bow_hit, combat_state)
                max_depth_related = linked_entity_ids(conn, EntityHit("item:bow", "item", "测试弓", "", "active", None, None, "candidate", 70, depth=9), combat_state)
                missing_add = maybe_add_entity(combat_state, {}, "missing", "missing", 1, depth=0)

        self.assertTrue(state.ambiguous_hits)
        self.assertTrue(state.needs_user_confirmation)
        self.assertTrue(any(hit.id == "char:neighbor" for hit in semantic_state.entity_hits))
        self.assertTrue(any(gap["status"] in {"candidate_only", "unresolved"} for gap in semantic_state.semantic_alias_gaps))
        self.assertTrue(any(hit.id == "species:mushroom" for hit in combat_state.entity_hits))
        self.assertTrue(any(hit.id == "rule:player-agency" for hit in combat_state.entity_hits))
        self.assertEqual(empty_label, [])
        self.assertTrue(exact_rows)
        self.assertTrue(explicit_rows)
        self.assertTrue(candidate_rows)
        self.assertEqual(no_candidate, [])
        self.assertTrue(ambiguous)
        self.assertTrue(salient)
        self.assertTrue(any(item[0] == "item:arrow-0" for item in recipe_related))
        self.assertTrue(any(item[0] == "item:arrow-0" for item in bow_related))
        self.assertEqual(max_depth_related, [])
        self.assertIsNone(missing_add)
        self.assertEqual(ambiguous_keywords("那个菌是什么"), ["菌", "孢子"])
        self.assertIn("loc:lab", extract_entity_ids({"x": "loc:lab char:neighbor"}))
        self.assertEqual(dedupe_links([("a", "low", 1), ("a", "high", 5), ("self", "skip", 9)], source_id="self"), [("a", "high", 5)])
        self.assertEqual(as_list(None), [])
        self.assertEqual(as_list("x"), ["x"])
        self.assertEqual(linked_priority(EntityHit("x", "faction", "", "", "active", None, None, "r", 1), SimpleNamespace(submode="social")), 68)
        self.assertEqual(linked_priority(EntityHit("x", "item", "", "", "active", None, None, "r", 1), SimpleNamespace(submode="craft")), 68)
        self.assertEqual(linked_priority(EntityHit("x", "location", "", "", "active", None, None, "r", 1), SimpleNamespace(submode="scene")), 58)
        self.assertEqual(profile_links(EntityHit("x", "item", "", "", "active", None, None, "r", 1), {"combat_profile": {"compatible_ammo": {"id": "ammo"}}, "ammo_profile": {"compatible_weapon_id": "weapon"}}, SimpleNamespace(submode="scene"))[0][2], 68)
        self.assertEqual(recipe_links(EntityHit("x", "recipe", "", "", "active", None, None, "r", 1), {}, SimpleNamespace(submode="craft")), [])
        self.assertEqual(sanitize_fts_query("a b c d e f g"), "")
        self.assertEqual(dedupe_texts([" a ", "", "a", "b"]), ["a", "b"])
        self.assertTrue(contains_any("abc", ["", "b"]))
        self.assertTrue(is_direct_hit(EntityHit("x", "item", "", "", "active", None, None, "candidate search", 1)))
        hits = {"x": EntityHit("x", "item", "old", "", "active", None, None, "candidate", 1)}
        add_hit(hits, EntityHit("x", "item", "new", "", "active", None, None, "candidate", 5))
        self.assertEqual(hits["x"].name, "new")
        self.assertEqual([hit.id for hit in sort_hits([EntityHit("b", "item", "B", "", "active", None, None, "linked", 1), EntityHit("a", "item", "A", "", "active", None, None, "name contains", 1)])], ["a", "b"])

    def test_context_rendering_entity_types_profiles_tables_and_value_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                setup_context_fixture(conn)
                full_hit = EntityHit("item:bow", "item", "测试弓", "弓", "active", None, "pc:traveler", "name contains", 95)
                compact_hit = EntityHit("item:arrow-0", "item", "测试箭", "弹药", "active", None, "pc:traveler", "linked", 50)
                state = SimpleNamespace(conn=conn, mode="query", submode="entity", entity_hits=[full_hit, compact_hit], ambiguous_hits=[compact_hit])
                player = render_player_state(conn)
                relevant = render_relevant_entities(state)
                full = "\n".join(render_entity_hit(conn, full_hit, detail="full"))
                compact = "\n".join(render_entity_hit(conn, compact_hit, detail="compact"))
                missing = "\n".join(render_context_entity(conn, EntityHit("missing", "item", "Missing", "", "active", None, None, "test", 1), level="full"))
                location = "\n".join(render_context_entity(conn, EntityHit("loc:lab", "location", "实验场", "", "active", None, None, "name contains", 95), level="full"))
                character = "\n".join(render_context_entity(conn, EntityHit("char:neighbor", "character", "邻居", "", "active", "loc:lab", None, "name contains", 95), level="full"))
                clock_plain = "\n".join(render_context_entity(conn, EntityHit("clock:plain", "clock", "空钟", "", "active", None, None, "candidate", 70), level="standard"))
                clock = "\n".join(render_context_entity(conn, EntityHit("clock:danger", "clock", "危险钟", "", "active", None, None, "candidate", 70), level="standard"))
                rule_plain = "\n".join(render_context_entity(conn, EntityHit("rule:plain", "rule", "空规则", "", "active", None, None, "candidate", 70), level="standard"))
                rule = "\n".join(render_context_entity(conn, EntityHit("rule:player-agency", "rule", "玩家能动性", "", "active", None, None, "candidate", 70), level="standard"))
                generic = "\n".join(render_context_entity(conn, EntityHit("species:mushroom", "species", "蘑菇人", "", "active", None, None, "candidate", 70), level="standard"))
                ambiguous = render_ambiguous_candidates(state)
                quantity = conn.execute("select * from items where entity_id='item:arrow-0'").fetchone()

        self.assertIn("体力", player)
        self.assertEqual(entity_context_level(state, full_hit), "full")
        self.assertEqual(entity_context_level(SimpleNamespace(mode="action", submode="combat"), full_hit), "standard")
        self.assertEqual(entity_context_level(state, compact_hit), "compact")
        self.assertIn("相关实体", relevant)
        self.assertIn("战斗档案", full)
        self.assertIn("弹药档案", full)
        self.assertIn("近战档案", full)
        self.assertIn("防护档案", full)
        self.assertIn("携行档案", full)
        self.assertIn("另有", full)
        self.assertIn("所有者", compact)
        self.assertIn("实体已不在当前数据库", missing)
        self.assertIn("已知资源", location)
        self.assertIn("当前承诺", character)
        self.assertIn("空钟", clock_plain)
        self.assertIn("危险爆发", clock)
        self.assertIn("空规则", rule_plain)
        self.assertIn("玩家保留最终选择", rule)
        self.assertIn("蘑菇人", generic)
        self.assertIn("歧义候选", ambiguous)
        self.assertEqual(format_context_quantity(quantity), "2支")
        self.assertEqual(format_context_quantity(None), "不适用")
        self.assertEqual(format_context_value(None), "无")
        self.assertEqual(format_context_value(True), "是")
        self.assertEqual(format_context_value(False), "否")
        self.assertEqual(format_context_value([]), "无")
        self.assertEqual(format_context_value({}), "无")
        self.assertIn("另有", format_context_value([1, 2, 3], list_limit=2))
        self.assertIn("另有", format_context_value({"a": 1, "b": 2, "c": 3}, list_limit=2))
        self.assertEqual(escape_table_cell("a|b\nc"), "a\\|b c")
        self.assertTrue(trim_inline("x" * 20, 5).endswith("…"))
        lines: list[str] = []
        append_context_table(lines, [("空", None)])
        self.assertEqual(lines, [])
        append_sequence_section(lines, "### 空", None, limit=2)
        append_range_bands_context(lines, "bad", limit=2)
        append_ammo_table_context(lines, [], limit=2)
        append_detail_entry(lines, "custom", list(range(5)), level="compact", entity_type="item")
        append_detail_entry(lines, "custom", {str(i): i for i in range(7)}, level="full", entity_type="item")
        self.assertTrue(any("另有" in line for line in lines))


class CoreRuleActionBaseAndTurnAssistantCoverageTests(unittest.TestCase):
    def test_action_base_render_registry_and_default_contracts(self) -> None:
        ok = ActionValidationResult()
        warn = ActionValidationResult(warnings=("watch",))
        failed = ActionValidationResult(errors=("bad",), warnings=("warn",), missing_required=("target",))
        ready = ResolutionResult(
            status="ready",
            facts_used=("fact",),
            rules_applied=("rule",),
            confirmations=("confirm",),
            warnings=("warn",),
        )
        spec = ActionResolverSpec(
            name="base-test",
            preview=lambda *_args: "preview",
            response_template="template",
            required_options=("target",),
            required_context=lambda *_args: ["entity:a"],
        )
        registry = ActionResolverRegistry()
        registry.register(spec)
        with self.assertRaisesRegex(ValueError, "Duplicate action resolver"):
            registry.register(spec)

        missing_resolution = spec.resolve_contract(None, None, {}, SimpleNamespace(target=""))
        ready_resolution = spec.resolve_contract(None, None, {}, SimpleNamespace(target="x"))

        self.assertEqual(ok.render(), "OK\n")
        self.assertIn("OK", warn.render())
        self.assertIn("FAILED", failed.render())
        self.assertIn("facts_used", ready.render())
        self.assertIn("rules_applied", ready.render())
        self.assertIn("confirmation", ready.render())
        self.assertIn("warning", ready.render())
        self.assertEqual(spec.required_context_ids(None, None, {}, SimpleNamespace()), ["entity:a"])
        self.assertEqual(missing_resolution.status, "needs_confirmation")
        self.assertEqual(ready_resolution.status, "ready")
        self.assertEqual(spec.delta_contract(None, None, {}, SimpleNamespace(), {}), ActionValidationResult())
        self.assertEqual(registry.names(), ["base-test"])
        self.assertEqual(registry.all(), [spec])
        self.assertEqual(option_specs_for(ActionOptionSpec("x", "help")), (ActionOptionSpec("x", "help"),))

    def test_turn_assistant_report_renderers_and_save_pipeline_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = load_campaign(copy_initialized_minimal(tmp))
            with connect(campaign) as conn:
                setup_context_fixture(conn)
                context = {
                    "request": {
                        "mode": "action",
                        "submode": "gather",
                        "must_save": True,
                        "requires_preview": True,
                        "turn_contract": contract_data(intent_data(action="gather")),
                    },
                    "completeness": {
                        "allow_proceed": True,
                        "missing_required": ["target"],
                        "needs_user_confirmation": ["confirm"],
                    },
                    "budget": {"estimated": 10, "limit": 100},
                }
                options = TurnAssistantOptions(user_text="采集", target=None, response_text="## 场景\nok", save=True)
                action_contract = render_action_contract_for_context(campaign, conn, context, options)
                preview = render_preview_for_context(campaign, conn, context, options)
                query_context = {**context, "request": {**context["request"], "mode": "query", "submode": "scene"}}
                no_action_contract = render_action_contract_for_context(campaign, conn, query_context, options)
                no_preview = render_preview_for_context(campaign, conn, query_context, options)
                unknown_context = {**context, "request": {**context["request"], "submode": "unknown"}}
                unknown_action_contract = render_action_contract_for_context(campaign, conn, unknown_context, options)
                unknown_preview = render_preview_for_context(campaign, conn, unknown_context, options)
                lint_empty = render_response_lint(context, TurnAssistantOptions(user_text="x"))
                delta_empty = render_delta_validation_for_options(conn, TurnAssistantOptions(user_text="x"))
                proposal_path = Path(tmp) / "proposal.json"
                proposal_path.write_text(json.dumps(proposal_from_parts(intent=intent_data(action="gather"), contract=contract_data(intent_data(action="gather"))).to_dict(), ensure_ascii=False), encoding="utf-8")
                proposal_text = render_proposal_validation(campaign, conn, TurnAssistantOptions(user_text="x", proposal_json=str(proposal_path), response_text="采集"))

                packet = SimpleNamespace(to_json_text=lambda: json.dumps(context, ensure_ascii=False))
                with mock.patch("rpg_engine.turn_assistant.build_context", return_value=packet), \
                    mock.patch("rpg_engine.turn_assistant.render_action_contract_for_context", return_value="contract"), \
                    mock.patch("rpg_engine.turn_assistant.render_preview_for_context", return_value="preview"), \
                    mock.patch("rpg_engine.turn_assistant.render_proposal_validation", return_value="proposal"), \
                    mock.patch("rpg_engine.turn_assistant.render_response_lint", return_value="lint"), \
                    mock.patch("rpg_engine.turn_assistant.render_delta_validation_for_options", return_value=("delta", [], {"ok": True})), \
                    mock.patch("rpg_engine.turn_assistant.run_save_pipeline", return_value="save"):
                    report = run_turn_assistant(campaign, conn, TurnAssistantOptions(user_text="x", save=True))

                invalid_validation = SimpleNamespace(ok=False, profile="p", errors=["blocked"])
                good_validation = SimpleNamespace(ok=True, profile="p", errors=[])
                projection_report = SimpleNamespace(
                    requested_dirty=("cards",),
                    requested_failed=("search",),
                    global_failed=("memory",),
                )
                commit_result = SimpleNamespace(
                    ok=True,
                    profile="p",
                    write_status="ok",
                    projection_status="partial",
                    backup_id="backup-1",
                    turn_id="turn:000001",
                    snapshot_path=Path("snapshot.md"),
                    snapshot_json_path=Path("snapshot.json"),
                    cards_count=3,
                    projection_report=projection_report,
                    memory_summaries=2,
                    memory_report_path=Path("memory.md"),
                    check_errors=["check bad"],
                )
                delta_path = Path(tmp) / "delta.json"
                delta_path.write_text(json.dumps(base_delta(), ensure_ascii=False), encoding="utf-8")
                blocked_save = ""
                ok_save = ""
                with mock.patch("rpg_engine.turn_assistant.run_validation_pipeline", return_value=invalid_validation):
                    blocked_save = run_save_pipeline(campaign, conn, TurnAssistantOptions(user_text="x", delta_json=str(delta_path)), base_delta(), [])
                with mock.patch("rpg_engine.turn_assistant.run_validation_pipeline", return_value=good_validation), \
                    mock.patch("rpg_engine.turn_assistant.commit_turn_delta", return_value=commit_result):
                    ok_save = run_save_pipeline(campaign, conn, TurnAssistantOptions(user_text="x", delta_json=str(delta_path), rebuild_memory=True), base_delta(), [])

        self.assertIn("resolver: `gather`", action_contract)
        self.assertIn("missing_required", action_contract)
        self.assertTrue(preview)
        self.assertEqual(no_action_contract, "")
        self.assertEqual(no_preview, "")
        self.assertEqual(unknown_action_contract, "")
        self.assertEqual(unknown_preview, "")
        self.assertEqual(lint_empty, "")
        self.assertEqual(delta_empty, ("未提供 delta，跳过 schema 校验。", [], None))
        self.assertIn("Proposal Validation", proposal_text)
        self.assertIn("Turn Assistant Report", report)
        self.assertIn("missing_required", report)
        self.assertIn("needs_user_confirmation", report)
        self.assertIn("Save Pipeline", report)
        self.assertIn("validation blocked save", blocked_save)
        self.assertIn("projection_dirty", ok_save)
        self.assertIn("projection_failed", ok_save)
        self.assertIn("projection_global_failed", ok_save)
        self.assertIn("memory_summaries", ok_save)
        self.assertIn("check errors", ok_save)
        self.assertEqual(render_next_steps({"completeness": {"allow_proceed": False}, "request": {"mode": "action"}}, TurnAssistantOptions(user_text="x"), False, []), ["- 先向玩家确认缺失信息，不要推进结算。"])


class CoreRuleCampaignValidationCoverageTests(unittest.TestCase):
    def test_campaign_validation_structure_content_paths_and_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors: list[str] = []
            caps = parse_capabilities({"capabilities": ["query", "query", "bad"]}, errors)
            bad_caps = parse_capabilities({"capabilities": "bad"}, errors)
            validate_v1_structure(root, {"content": {"entities": "x", "unsupported": "x"}, "defaults": {}}, errors)
            validate_v1_structure(root, {"content": "bad"}, errors)
            (root / "plugins").mkdir()
            (root / "bad.py").write_text("print('bad')\n", encoding="utf-8")
            validate_no_v1_code_extensions(root, errors)
            (root / "content").mkdir(exist_ok=True)
            (root / "content" / "dir").mkdir()
            (root / "empty.txt").write_text("", encoding="utf-8")
            validate_content_paths(
                root,
                {
                    "content": {
                        "entities": ["", "/absolute/path", "missing.yaml", "content/dir"],
                    }
                },
                errors,
            )
            validate_required_files(root, errors)
            for required in ["prompts/gm.md", "templates/action.md", "templates/query.md", "tests/smoke.yaml"]:
                path = root / required
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            validate_required_files(root, errors)
            outside = relative_path(root, Path("/tmp/outside-file"))
            prefixed = prefix_errors("x", ["a", "b"])
            rendered_validation = render_campaign_validation(
                CampaignValidationResult(
                    campaign_id="cid",
                    package_version="1",
                    ok=False,
                    errors=("err",),
                    warnings=("warn",),
                    record_counts={"entity": 2},
                    capabilities=("query",),
                    smoke_tests=("smoke",),
                )
            )
            rendered_test = render_campaign_test(
                CampaignTestResult(
                    campaign_id="cid",
                    ok=False,
                    validation=CampaignValidationResult(),
                    health_errors=("health",),
                    smoke_results=(SmokeCaseResult("s", False, "query", "bad"),),
                    errors=("err",),
                )
            )
            rendered_empty_test = render_campaign_test(
                CampaignTestResult(campaign_id="cid", ok=False, validation=CampaignValidationResult())
            )

        self.assertEqual(caps, ["query", "query", "bad"])
        self.assertEqual(bad_caps, [])
        self.assertTrue(any("unsupported capability bad" in item for item in errors))
        self.assertTrue(any("duplicate capability query" in item for item in errors))
        self.assertTrue(any("required non-empty string" in item for item in errors))
        self.assertIn("campaign.yaml.content: required object", errors)
        self.assertIn("plugins/: V1 campaign packages must not include plugins", errors)
        self.assertTrue(any("bad.py" in item for item in errors))
        self.assertTrue(any("entries must be non-empty paths" in item for item in errors))
        self.assertTrue(any("must use relative package path" in item for item in errors))
        self.assertTrue(any("missing file" in item for item in errors))
        self.assertTrue(any("not a file" in item for item in errors))
        self.assertTrue(any("required" in item for item in errors))
        self.assertTrue(any("must not be empty" in item for item in errors))
        self.assertEqual(outside, "/tmp/outside-file")
        self.assertEqual(prefixed, ["x.a", "x.b"])
        self.assertEqual(campaign_dedupe(["a", "a", "b"]), ["a", "b"])
        self.assertEqual(campaign_as_list(None), [])
        self.assertEqual(campaign_as_list("x"), ["x"])
        self.assertIn("FAILED", rendered_validation)
        self.assertIn("capabilities", rendered_validation)
        self.assertIn("Smoke Tests", rendered_test)
        self.assertIn("health", rendered_test)
        self.assertIn("no smoke tests ran", rendered_empty_test)

    def test_campaign_random_tables_palettes_smoke_and_reference_matrices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = root / "content"
            content.mkdir()
            errors: list[str] = []
            warnings: list[str] = []
            bad_random = content / "random.yaml"
            bad_random.write_text(
                "random_tables:\n"
                "  - bad\n"
                "  - id: table:a\n"
                "    name: ''\n"
                "    visibility: public\n"
                "    entries: []\n"
                "  - id: table:a\n"
                "    name: A\n"
                "    entries:\n"
                "      - bad\n"
                "      - result: ''\n"
                "        weight: false\n",
                encoding="utf-8",
            )
            missing_random = content / "missing-random.yaml"
            missing_random.write_text("x: 1\n", encoding="utf-8")
            invalid_random = content / "invalid-random.yaml"
            invalid_random.write_text("[", encoding="utf-8")
            validate_random_tables(
                root,
                {"content": {"random_tables": ["content/random.yaml", "content/missing-random.yaml", "content/invalid-random.yaml"]}},
                errors,
            )
            validate_palette_entry(
                "bad",
                "palette.bad",
                "materials",
                set(),
                set(),
                set(),
                set(),
                errors,
                warnings,
            )
            seen = {"pal:a"}
            validate_palette_entry(
                {
                    "id": "pal:a",
                    "name": "",
                    "summary": "",
                    "rarity": "hidden",
                    "locations": ["loc:missing"],
                    "intents": ["bad"],
                    "discovery": {"mode": "direct", "clue_text": ""},
                    "unlock": {"required_locations": ["loc:missing"], "required_clocks": {"clock:missing": 1}},
                    "save_as": {"type": "bad", "entity_id": "entity:existing"},
                    "risks": [],
                },
                "palette.entry",
                "materials",
                seen,
                {"loc:known"},
                {"entity:existing"},
                {"clock:known"},
                errors,
                warnings,
            )
            palette_file = content / "palettes.yaml"
            palette_file.write_text("bad_key: []\nmaterials: bad\nspecies: null\n", encoding="utf-8")
            bad_palette_file = content / "bad-palettes.yaml"
            bad_palette_file.write_text("- bad\n", encoding="utf-8")
            invalid_palette_file = content / "invalid-palettes.yaml"
            invalid_palette_file.write_text("[", encoding="utf-8")
            validate_palettes(
                root,
                {"content": {"palettes": ["content/palettes.yaml", "content/bad-palettes.yaml", "content/invalid-palettes.yaml"]}},
                {"entity": [{"id": "loc:known", "type": "location"}], "clock": [{"id": "clock:known"}]},
                errors,
                warnings,
            )
            found_palette_paths = palette_paths(root, {"content": {"palettes": "content/palettes.yaml"}}, errors)
            default_palette_dir = content / "palettes"
            default_palette_dir.mkdir()
            (default_palette_dir / "auto.yaml").write_text("materials: []\n", encoding="utf-8")
            discovered_default = palette_paths(root, {"content": {}}, errors)

            smoke_path = root / "smoke.yaml"
            smoke_path.write_text("smoke_tests:\n  - id: q\n    type: query\n", encoding="utf-8")
            smoke_cases = load_smoke_cases(smoke_path)
            for text in ["[", "- bad\n", "smoke_tests: []\n"]:
                path = root / f"bad-{len(errors)}.yaml"
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_smoke_cases(path)
            smoke_errors: list[str] = []
            validate_smoke_case_shape({"type": "start_turn"}, "case.start", smoke_errors)
            validate_smoke_case_shape({"type": "query", "kind": "entity"}, "case.query", smoke_errors)
            validate_smoke_case_shape({"type": "preview", "options": [], "expect_status": 3}, "case.preview", smoke_errors)
            validate_smoke_case_shape({"type": "validate_delta"}, "case.delta", smoke_errors)
            validate_smoke_case_shape({"type": "random_table"}, "case.table", smoke_errors)
            validate_smoke_case_shape({"type": "query", "contains": []}, "case.contains", smoke_errors)
            smoke_file = root / "tests" / "smoke.yaml"
            smoke_file.parent.mkdir(exist_ok=True)
            smoke_file.write_text(
                "smoke_tests:\n"
                "  - id: ''\n"
                "    type: bad\n"
                "    capabilities: bad\n"
                "  - id: q\n"
                "    type: query\n"
                "    capabilities: [missing_cap]\n"
                "    kind: bad\n",
                encoding="utf-8",
            )
            smoke_ids = validate_smoke_file(root, ["query"], smoke_errors)

            references_errors: list[str] = []
            validate_content_references(
                {
                    "entity": [
                        {"id": "loc:known", "type": "location", "visibility": "bad"},
                        {
                            "id": "char:bad",
                            "type": "character",
                            "location_id": "loc:missing",
                            "owner_id": "missing",
                            "character": {"species_id": "species:missing"},
                        },
                        {"id": "loc:child", "type": "location", "location": {"parent_id": "loc:missing"}},
                    ],
                    "route": [{"from_location_id": "loc:missing", "to_location_id": "loc:also"}],
                    "relationship": [{"source_id": "missing", "target_id": "missing2"}],
                    "clock": [{"id": "clock:bad", "visibility": "public"}],
                    "world_setting": [
                        {
                            "linked_rules": ["rule:missing"],
                            "linked_clocks": ["clock:missing"],
                            "linked_entities": ["entity:missing"],
                        }
                    ],
                },
                {"initial_location_id": "loc:missing", "defaults": {"player_entity_id": "pc:missing"}},
                references_errors,
            )

            random_success = content / "random-success.yaml"
            random_success.write_text(
                "random_tables:\n"
                "  - id: table:ok\n"
                "    entries:\n"
                "      - result: success\n",
                encoding="utf-8",
            )
            campaign = SimpleNamespace(content_files=lambda key: [random_success] if key == "random_tables" else [])
            success_text = first_random_table_result(campaign, "table:ok")
            no_entries = content / "random-empty.yaml"
            no_entries.write_text("random_tables:\n  - id: table:empty\n    entries: []\n", encoding="utf-8")
            no_result = content / "random-no-result.yaml"
            no_result.write_text("random_tables:\n  - id: table:no-result\n    entries:\n      - result: ''\n", encoding="utf-8")
            error_campaign = SimpleNamespace(content_files=lambda key: [no_entries, no_result] if key == "random_tables" else [])
            with self.assertRaisesRegex(ValueError, "random_table smoke requires table"):
                first_random_table_result(error_campaign, "")
            with self.assertRaisesRegex(ValueError, "has no entries"):
                first_random_table_result(error_campaign, "table:empty")
            with self.assertRaisesRegex(ValueError, "has no result entries"):
                first_random_table_result(error_campaign, "table:no-result")
            with self.assertRaisesRegex(ValueError, "not found"):
                first_random_table_result(error_campaign, "table:missing")

            fake_runtime = SimpleNamespace(
                campaign=campaign,
                start_turn=lambda *_args, **_kwargs: SimpleNamespace(can_proceed=False, missing_required=["x"], needs_user_confirmation=["y"], markdown="hello"),
                query=lambda *_args, **_kwargs: SimpleNamespace(text="query text"),
                preview_action=lambda *_args, **_kwargs: SimpleNamespace(errors=["e"], missing_required=[], warnings=["w"], status="needs_confirmation", ok=False, markdown="preview text"),
                validate_delta=lambda *_args, **_kwargs: SimpleNamespace(ok=False, errors=["delta bad"]),
            )
            smoke_results = [
                run_smoke_case(fake_runtime, {"id": "s", "type": "start_turn", "contains": "missing"}),
                run_smoke_case(fake_runtime, {"id": "q", "type": "query", "kind": "scene", "contains": "query"}),
                run_smoke_case(fake_runtime, {"id": "p", "type": "preview", "action": "gather", "expect_status": "ready"}),
                run_smoke_case(fake_runtime, {"id": "d", "type": "validate_delta", "delta": {}}),
                run_smoke_case(fake_runtime, {"id": "r", "type": "random_table", "table": "table:ok", "contains": "success"}),
                run_smoke_case(fake_runtime, {"id": "u", "type": "unknown"}),
            ]
            contains_failed = check_contains({"contains": "absent"}, "text", SmokeCaseResult("c", True, "query"))

        self.assertTrue(any("invalid YAML" in item for item in errors))
        self.assertTrue(any("random_tables: must be array" in item for item in errors))
        self.assertTrue(any("duplicate random table id table:a" in item for item in errors))
        self.assertTrue(any(".weight: must be positive number" in item for item in errors))
        self.assertTrue(any("palette.bad: must be object" in item for item in errors))
        self.assertTrue(any("duplicate palette id pal:a" in item for item in errors))
        self.assertTrue(any("hidden rarity cannot use discovery.mode direct" in item for item in errors))
        self.assertTrue(any("unsupported palette key" in item for item in errors))
        self.assertTrue(any("must be array" in item for item in errors))
        self.assertTrue(warnings)
        self.assertEqual(found_palette_paths, [palette_file])
        self.assertEqual(discovered_default, [default_palette_dir / "auto.yaml"])
        self.assertEqual(smoke_cases, [{"id": "q", "type": "query"}])
        self.assertTrue(any(".user_text: required" in item for item in smoke_errors))
        self.assertTrue(any(".kind: must be scene/entity/context" in item for item in smoke_errors))
        self.assertTrue(any(".query_text: required" in item for item in smoke_errors))
        self.assertTrue(any(".action: required" in item for item in smoke_errors))
        self.assertTrue(any(".delta: required object" in item for item in smoke_errors))
        self.assertTrue(any(".table: required" in item for item in smoke_errors))
        self.assertTrue(any(".contains: must be string" in item for item in smoke_errors))
        self.assertTrue(any("unsupported value" in item for item in smoke_errors))
        self.assertEqual(smoke_ids, ["", "q"])
        self.assertTrue(any("visibility: unsupported" in item for item in references_errors))
        self.assertTrue(any("location_id: missing" in item for item in references_errors))
        self.assertTrue(any("relationship" in item for item in references_errors))
        self.assertTrue(any("world_setting" in item for item in references_errors))
        self.assertIn("missing location", "\n".join(references_errors))
        self.assertEqual(success_text, "success")
        self.assertFalse(smoke_results[0].ok)
        self.assertTrue(smoke_results[1].ok)
        self.assertFalse(smoke_results[2].ok)
        self.assertFalse(smoke_results[3].ok)
        self.assertTrue(smoke_results[4].ok)
        self.assertFalse(smoke_results[5].ok)
        self.assertFalse(contains_failed.ok)


if __name__ == "__main__":
    unittest.main()
