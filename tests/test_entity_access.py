from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from rpg_engine.actions.craft import build_palette_craft_delta
from rpg_engine.actions.explore import resolve_explore
from rpg_engine.actions.routine import preview_routine, resolve_routine
from rpg_engine.actions.travel import build_palette_travel_delta
from rpg_engine.actions.policy import matching_clock_rows
from rpg_engine.actions.combat import combat_blockers, resolve_combat_inputs
from rpg_engine.actions.social import attach_palette_to_social_delta, resolve_social, social_scope
from rpg_engine.campaign import load_campaign
from rpg_engine.cards import GENERATED_MARKER, write_cards
from rpg_engine.context_builder import build_context
from rpg_engine.context.resolution import (
    find_candidate_entities,
    find_trusted_literal_candidate_entities,
    find_trusted_token_candidate_entities,
)
from rpg_engine.content_factory import audit_content_quality
from rpg_engine.content_types.core import validate_entity_record
from rpg_engine.context_builder import render_semantic_suggestion
from rpg_engine.db import connect, get_meta, rebuild_fts, resolve_entity, upsert_clock, upsert_entity, upsert_route
from rpg_engine.delta_schema import validate_delta_schema
from rpg_engine.ai_intent.binder import find_entity_candidates
from rpg_engine.entity_access import (
    EntityRecord,
    list_entities,
    read_entity,
    validate_delta_entity_references,
)
from rpg_engine.intent_router import ActionIntent, first_visible_entity_in_text
from rpg_engine.memory import find_relevant_memories, rebuild_memory_summaries
from rpg_engine.memory import build_world_memories
from rpg_engine.mcp_adapter import AIGMMCPAdapter, MCPAdapterConfig
from rpg_engine.ops_report import build_ops_report
from rpg_engine.palette import evaluate_palette_entry
from rpg_engine.preview import (
    current_location_row,
    gatherable_items,
    harvestable_crop_rows,
    location_detail_row,
    nearby_crafting_candidates,
    render_craft_preview,
    render_combat_preview,
    render_gather_preview,
    render_rest_preview,
    render_social_preview,
    render_travel_preview,
    resolve_location,
    resolve_recipe,
    shortest_route_plan,
    social_relevant_clocks,
    summarize_crop_plots,
)
from rpg_engine.redaction import find_entity_ref_tokens, redact_entity_refs
from rpg_engine.render import render_current_snapshot, render_current_snapshot_json, render_entity, render_scene
from rpg_engine.render import write_current_snapshot_json
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import SaveManager
from rpg_engine.save_service import init_v1_save
from rpg_engine.save_validation import validate_cards, validate_search_projection, validate_snapshot_json
from rpg_engine.validators import run_checks


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


class EntityAccessContractTests(unittest.TestCase):
    def test_redaction_uses_reference_id_boundaries(self) -> None:
        refs = {"loc:hidden": {"loc:hidden"}}
        text = "loc:hidden-route loc:hidden.route loc:hidden..route loc:hidden"
        self.assertEqual(redact_entity_refs(text, refs), "loc:hidden-route loc:hidden.route loc:hidden..route [hidden]")
        self.assertEqual(find_entity_ref_tokens(text, refs), ["loc:hidden"])
        self.assertEqual(redact_entity_refs({"loc:hidden": "loc:hidden"}, refs, drop_empty=False), {"[hidden]": "[hidden]"})
        self.assertEqual(redact_entity_refs(("loc:hidden", "safe"), refs, drop_empty=False), ("[hidden]", "safe"))
        self.assertEqual(redact_entity_refs({"loc:hidden"}, refs, drop_empty=False), {"[hidden]"})

    def test_redaction_scans_dataclass_and_frozenset_payloads(self) -> None:
        @dataclass(frozen=True)
        class HiddenPayload:
            label: str
            refs: frozenset[str]

        refs = {"loc:hidden": {"loc:hidden"}}
        payload = HiddenPayload(label="loc:hidden", refs=frozenset({"loc:hidden", "safe"}))

        self.assertEqual(find_entity_ref_tokens(payload, refs), ["loc:hidden"])
        self.assertEqual(
            redact_entity_refs(payload, refs, drop_empty=False),
            {"label": "[hidden]", "refs": frozenset({"[hidden]", "safe"})},
        )
        nested = frozenset({payload})
        redacted_nested = redact_entity_refs(nested, refs, drop_empty=False)
        redacted_set = redact_entity_refs({payload}, refs, drop_empty=False)
        expected_payload = (("label", "[hidden]"), ("refs", frozenset({"[hidden]", "safe"})))
        self.assertEqual(redacted_nested, frozenset({expected_payload}))
        self.assertEqual(redacted_set, {expected_payload})

    def test_mcp_view_guard_normalizes_unicode_hidden_read_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            player = AIGMMCPAdapter(MCPAdapterConfig(root=Path(tmp), mcp_profile="player"))
            trusted = AIGMMCPAdapter(MCPAdapterConfig(root=Path(tmp), mcp_profile="trusted_gm"))

            with self.assertRaisesRegex(PermissionError, "view='gm' requires"):
                player.require_view_allowed("\u2060ＧＭ\u2060")
            trusted.require_view_allowed("\u2060ＧＭ\u2060")

    def test_context_candidate_search_filters_request_words_for_fts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-official-notice",
                        "type": "location",
                        "name": "Official Notice",
                        "summary": "Visible target for mixed request-word recall.",
                    },
                )
                for index in range(6):
                    upsert_entity(
                        conn,
                        {
                            "id": f"loc:request-noise-{index}",
                            "type": "location",
                            "name": f"Look At Noise {index}",
                            "summary": "Visible request-word-only noise.",
                        },
                    )
                conn.commit()
                rebuild_fts(conn)

                rows = find_candidate_entities(conn, "look at official notice", limit=1)

        self.assertEqual([row["id"] for row in rows], ["loc:visible-official-notice"])

    def test_context_candidate_search_filters_cjk_request_words_for_fts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                for verb in ["看", "查", "问", "找"]:
                    for index in range(3):
                        upsert_entity(
                            conn,
                            {
                                "id": f"item:cjk-request-noise-{verb}-{index}",
                                "type": "item",
                                "name": f"{verb} Noise {index}",
                                "summary": "Visible request-word-only noise.",
                            },
                        )
                    upsert_entity(
                        conn,
                        {
                            "id": f"item:cjk-attached-request-noise-{verb}",
                            "type": "item",
                            "name": f"{verb}弩 Noise",
                            "summary": "Visible attached request-word noise.",
                        },
                    )
                upsert_entity(
                    conn,
                    {
                        "id": "item:visible-crossbow-bolt",
                        "type": "item",
                        "name": "弩",
                        "summary": "Visible target for mixed CJK request-word recall.",
                    },
                )
                conn.commit()
                rebuild_fts(conn)

                for verb in ["看", "查", "问", "找"]:
                    for separator in [" ", ""]:
                        with self.subTest(verb=verb, separator=separator):
                            rows = find_candidate_entities(conn, f"{verb}{separator}弩", limit=1)

                            self.assertEqual([row["id"] for row in rows], ["item:visible-crossbow-bolt"])

    def test_context_candidate_search_escapes_like_wildcards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-a_b",
                        "type": "location",
                        "name": "A_B",
                        "summary": "Visible literal underscore target.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-axb",
                        "type": "location",
                        "name": "Axb",
                        "summary": "Visible wildcard decoy.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden-a_b",
                        "type": "location",
                        "name": "A_B Hidden",
                        "summary": "Hidden literal underscore target.",
                        "visibility": "hidden",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden-axb",
                        "type": "location",
                        "name": "Axb Hidden",
                        "summary": "Hidden wildcard decoy.",
                        "visibility": "hidden",
                    },
                )
                conn.commit()
                rebuild_fts(conn)

                for query in ["%", "_", "__"]:
                    with self.subTest(query=query):
                        self.assertEqual(find_candidate_entities(conn, query, limit=5, view="gm"), [])

                public_rows = find_candidate_entities(conn, "A_B", limit=5)
                trusted_rows = find_trusted_token_candidate_entities(conn, "A_B", limit=5, view="gm")

        public_ids = [row["id"] for row in public_rows]
        trusted_ids = [row["id"] for row in trusted_rows]
        self.assertIn("loc:visible-a_b", public_ids)
        self.assertNotIn("loc:visible-axb", public_ids)
        self.assertIn("loc:hidden-a_b", trusted_ids)
        self.assertNotIn("loc:hidden-axb", trusted_ids)

    def test_trusted_candidate_search_prefers_raw_hidden_literals_before_stripped_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                for entity_id, name in [
                    ("item:hidden-crossbow", "弩"),
                    ("item:hidden-find-crossbow", "找弩"),
                    ("item:hidden-device", "器"),
                    ("item:hidden-query-device", "查询器"),
                ]:
                    upsert_entity(
                        conn,
                        {
                            "id": entity_id,
                            "type": "item",
                            "name": name,
                            "summary": "Hidden exact-priority probe.",
                            "visibility": "hidden",
                        },
                    )
                conn.commit()
                rebuild_fts(conn)

                find_crossbow_rows = find_candidate_entities(conn, "找弩", limit=1, view="gm")
                query_device_rows = find_candidate_entities(conn, "查询器", limit=1, view="gm")

        self.assertEqual([row["id"] for row in find_crossbow_rows], ["item:hidden-find-crossbow"])
        self.assertEqual([row["id"] for row in query_device_rows], ["item:hidden-query-device"])

    def test_trusted_candidate_search_uses_literal_percent_tokens_for_aliases_and_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-percent-code",
                        "type": "item",
                        "name": "Percent Code",
                        "summary": "Hidden literal percent target.",
                        "visibility": "hidden",
                        "aliases": ["A%B"],
                        "details": {"code": "A%B"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-wildcard-decoy",
                        "type": "item",
                        "name": "Wildcard Decoy",
                        "summary": "Axb",
                        "visibility": "hidden",
                        "aliases": ["Axb"],
                        "details": {"code": "Axb"},
                    },
                )
                conn.commit()

                rows = find_trusted_token_candidate_entities(conn, "A%B", limit=5, view="gm")

        ids = [row["id"] for row in rows]
        self.assertIn("item:hidden-percent-code", ids)
        self.assertNotIn("item:hidden-wildcard-decoy", ids)

    def test_trusted_literal_candidate_helper_guards_player_and_stopword_only_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-direct-literal",
                        "type": "item",
                        "name": "Hidden Literal",
                        "summary": "Hidden direct literal probe.",
                        "visibility": "hidden",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-stopword-sentence",
                        "type": "item",
                        "name": "can you show me",
                        "summary": "Hidden stopword-only sentence probe.",
                        "visibility": "hidden",
                    },
                )
                conn.commit()

                player_literal_rows = find_trusted_literal_candidate_entities(
                    conn,
                    "Hidden Literal",
                    limit=5,
                    view="player",
                )
                gm_stopword_literal_rows = find_trusted_literal_candidate_entities(
                    conn,
                    "can you show me",
                    limit=5,
                    view="gm",
                )
                gm_stopword_token_rows = find_trusted_token_candidate_entities(
                    conn,
                    "can you show me",
                    limit=5,
                    view="gm",
                )

        self.assertEqual(player_literal_rows, [])
        self.assertEqual(gm_stopword_literal_rows, [])
        self.assertEqual(gm_stopword_token_rows, [])

    def test_gm_candidate_search_prefers_visible_exact_before_hidden_contains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-official-notice",
                        "type": "location",
                        "name": "Official Notice",
                        "summary": "Visible exact target.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden-official-notice-decoy",
                        "type": "location",
                        "name": "Hidden Official Notice Decoy",
                        "summary": "Hidden contains decoy.",
                        "visibility": "hidden",
                    },
                )
                conn.commit()
                rebuild_fts(conn)

                exact_rows = find_candidate_entities(conn, "Official Notice", limit=1, view="gm")
                lowercase_rows = find_candidate_entities(conn, "official notice", limit=1, view="gm")
                natural_rows = find_candidate_entities(conn, "look at official notice", limit=1, view="gm")

        self.assertEqual([row["id"] for row in exact_rows], ["loc:visible-official-notice"])
        self.assertEqual([row["id"] for row in lowercase_rows], ["loc:visible-official-notice"])
        self.assertEqual([row["id"] for row in natural_rows], ["loc:visible-official-notice"])

    def test_palette_structured_outputs_redact_hidden_refs_without_dropping_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.route",
                        "type": "location",
                        "name": "Hidden Grove",
                        "summary": "GM-only location.",
                        "visibility": "hidden",
                    },
                )
                conn.commit()
                candidate = {
                    "status": "available",
                    "entry": {
                        "id": "palette:hidden-grove",
                        "_kind": "location",
                        "name": "Hidden Grove",
                        "summary": "Points to loc:hidden.route.",
                        "discovery": {"mode": "confirm_required"},
                    },
                }

                craft_delta = build_palette_craft_delta(conn, candidate, SimpleNamespace(user_text=None, target=None, materials=None, time_cost=None))
                travel_delta = build_palette_travel_delta(conn, candidate, SimpleNamespace(user_text=None, destination=None, pace="normal"))
                social_delta = {"events": [{"payload": {}}], "upsert_entities": [], "tick_clocks": []}
                attach_palette_to_social_delta(conn, social_delta, candidate)

                for delta in (craft_delta, travel_delta, social_delta):
                    rendered = json.dumps(delta, ensure_ascii=False, sort_keys=True)
                    self.assertNotIn("Hidden Grove", rendered)
                    self.assertNotIn("loc:hidden.route", rendered)
                    self.assertIn("[hidden]", rendered)
                    self.assertIn("upsert_entities", delta)
                self.assertNotIn("loc:hidden.route", render_entity(conn, "loc:hidden.route", view="player"))
                semantic_text = render_semantic_suggestion(
                    SimpleNamespace(
                        conn=conn,
                        semantic_ai="mock",
                        semantic_provider="test",
                        semantic_model="test",
                        mode="query",
                        semantic_error=None,
                        semantic_suggestion={
                            "mode": "action",
                            "submode": "explore",
                            "confidence": "high",
                            "targets": ["loc:hidden.route"],
                            "entities_mentioned": ["Hidden Grove"],
                            "missing_confirmations": [],
                            "notes": ["Secret Route Alias"],
                        },
                        semantic_alias_gaps=[
                            {"label": "loc:hidden.route", "status": "missing", "candidates": [], "suggestion": "Hidden Grove"}
                        ],
                    )
                )
                self.assertNotIn("loc:hidden.route", semantic_text)
                self.assertNotIn("Hidden Grove", semantic_text)
                context_packet = build_context(
                    campaign,
                    conn,
                    user_text="查看 loc:hidden.route Hidden Grove",
                    mode="query",
                    budget=500,
                    max_events=0,
                )
                context_payload = json.dumps(context_packet.request, ensure_ascii=False, sort_keys=True) + context_packet.markdown
                self.assertNotIn("loc:hidden.route", context_payload)
                self.assertNotIn("Hidden Grove", context_payload)
                leaky_markdown_path = save_dir / "snapshots" / "leaky-current.md"
                missing_json_path = save_dir / "snapshots" / "missing-current.json"
                leaky_markdown_path.write_text("loc:hidden.route\n", encoding="utf-8")
                snapshot_errors: list[str] = []
                validate_snapshot_json(
                    leaky_markdown_path,
                    missing_json_path,
                    conn,
                    get_meta(conn),
                    campaign.campaign_id,
                    snapshot_errors,
                )
                self.assertTrue(any("contains hidden entity refs" in item for item in snapshot_errors))

            runtime = GMRuntime.from_path(save_dir)
            query_payload = runtime.query("entity", "loc:hidden.route").to_dict()
            unsupported = runtime.preview_action("loc:hidden.route", {})
            invalid_option = runtime.preview_action("explore", {"loc:hidden.route": []})
            blocked = runtime.preview_action("explore", {"target": "loc:hidden.route"})
            ready = runtime.preview_action("explore", {"target": "loc:hidden.route", "unknown_lead": True})
            invalid_delta = runtime.validate_delta(
                {"intent": "gather", "events": [], "upsert_entities": [], "tick_clocks": []},
                action="gather",
                action_options={"target": "loc:hidden.route"},
            )
            for payload in (
                query_payload,
                unsupported.to_dict(),
                invalid_option.to_dict(),
                blocked.to_dict(),
                ready.to_dict(),
                invalid_delta.to_dict(),
            ):
                rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                self.assertNotIn("loc:hidden.route", rendered)
                self.assertNotIn("Hidden Grove", rendered)

    def test_save_manager_refresh_redacts_hidden_current_location_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_dir = root / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.route",
                        "type": "location",
                        "name": "Hidden Grove",
                        "summary": "GM-only location.",
                        "visibility": "hidden",
                    },
                )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:hidden.route",),
                )
                conn.commit()

            refreshed = SaveManager(root).refresh_save_record({"path": "save"})
            rendered = json.dumps(refreshed, ensure_ascii=False, sort_keys=True)

            self.assertNotIn("loc:hidden.route", rendered)
            self.assertNotIn("Hidden Grove", rendered)
            self.assertIn("[hidden]", rendered)

    def test_trusted_views_keep_hidden_refs_in_runtime_render_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.route",
                        "type": "location",
                        "name": "Hidden Grove",
                        "summary": "GM-only location summary loc:hidden.route.",
                        "visibility": "hidden",
                        "details": {"note": "Hidden Grove detail"},
                        "location": {"description_short": "Hidden Grove panorama loc:hidden.route."},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden.relic",
                        "type": "item",
                        "name": "Hidden Relic",
                        "summary": "Stored near loc:hidden.route.",
                        "visibility": "hidden",
                        "details": {"note": "Hidden Grove detail"},
                    },
                )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:hidden.route",),
                )
                conn.commit()

                player_scene = render_scene(conn, view="player")
                gm_scene = render_scene(conn, view="gm")
                player_snapshot = render_current_snapshot_json(campaign, conn, view="player")
                gm_snapshot = render_current_snapshot_json(campaign, conn, view="maintenance")
                player_context = build_context(campaign, conn, user_text="查看 Hidden Grove", mode="query", budget=700)
                maintenance_context = build_context(
                    campaign,
                    conn,
                    user_text="维护 Hidden Grove",
                    mode="maintenance",
                    budget=700,
                )

                self.assertNotIn("loc:hidden.route", player_scene)
                self.assertIn("loc:hidden.route", gm_scene)
                self.assertEqual(player_snapshot["meta"]["current_location_id"], "当前地点不可见或不存在")
                self.assertEqual(gm_snapshot["meta"]["current_location_id"], "loc:hidden.route")
                self.assertNotIn("loc:hidden.route", player_context.markdown)
                self.assertIn("loc:hidden.route", maintenance_context.markdown)
                self.assertNotIn("loc:hidden.route", render_entity(conn, "item:hidden.relic", view="player"))
                self.assertIn("loc:hidden.route", render_entity(conn, "item:hidden.relic", view="gm"))

            runtime = GMRuntime.from_path(save_dir)
            runtime.campaign.config.setdefault("capabilities", []).append("explore")
            self.assertIn("loc:hidden.route", runtime.query("scene", view="gm").text)

            unsupported_player = runtime.preview_action("loc:hidden.route", {})
            unsupported_gm = runtime.preview_action("loc:hidden.route", {}, context={"view": "gm"})
            explore_gm = runtime.preview_action("explore", {"target": "loc:hidden.route"}, context={"view": "gm"})
            unresolved_intent = ActionIntent(
                user_text="loc:hidden.route",
                mode="action",
                submode="act",
                action="loc:hidden.route",
                options={},
                confidence="low",
                source="test",
                kind="unresolved",
                status="blocked",
                player_message="loc:hidden.route needs clarification",
                errors=("loc:hidden.route",),
            )
            unresolved_player = runtime.preview_intent(unresolved_intent, view="player")
            unresolved_gm = runtime.preview_intent(unresolved_intent, view="gm")

            self.assertNotIn("loc:hidden.route", json.dumps(unsupported_player.to_dict(), ensure_ascii=False, sort_keys=True))
            self.assertIn("loc:hidden.route", json.dumps(unsupported_gm.to_dict(), ensure_ascii=False, sort_keys=True))
            self.assertIn("loc:hidden.route", json.dumps(explore_gm.to_dict(), ensure_ascii=False, sort_keys=True))
            self.assertTrue(explore_gm.ready_to_save, explore_gm.to_dict())
            self.assertNotIn("loc:hidden.route", json.dumps(unresolved_player.to_dict(), ensure_ascii=False, sort_keys=True))
            self.assertIn("loc:hidden.route", json.dumps(unresolved_gm.to_dict(), ensure_ascii=False, sort_keys=True))

    def test_semantic_suggestion_redacts_only_player_context_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden.route",
                        "type": "location",
                        "name": "Hidden Grove",
                        "summary": "GM-only location.",
                        "visibility": "hidden",
                    },
                )
                conn.commit()
                common = {
                    "conn": conn,
                    "semantic_ai": "mock",
                    "semantic_provider": "test",
                    "semantic_model": "test",
                    "semantic_error": None,
                    "semantic_suggestion": {
                        "mode": "query",
                        "submode": "entity",
                        "confidence": "high",
                        "targets": ["loc:hidden.route"],
                        "entities_mentioned": ["Hidden Grove"],
                        "missing_confirmations": [],
                        "notes": ["loc:hidden.route"],
                    },
                    "semantic_alias_gaps": [
                        {"label": "loc:hidden.route", "status": "missing", "candidates": [], "suggestion": "Hidden Grove"}
                    ],
                }

                player_text = render_semantic_suggestion(SimpleNamespace(**common, mode="query"))
                maintenance_text = render_semantic_suggestion(SimpleNamespace(**common, mode="maintenance"))

                self.assertNotIn("loc:hidden.route", player_text)
                self.assertIn("loc:hidden.route", maintenance_text)

    def test_read_entity_exposes_common_identity_fields_and_visibility_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible",
                        "type": "location",
                        "name": "Visible Camp",
                        "summary": "Player-visible camp.",
                        "details": {"region": "north"},
                        "aliases": ["Camp"],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden",
                        "type": "character",
                        "name": "Hidden Contact",
                        "summary": "GM-only contact.",
                        "visibility": "hidden",
                        "details": {"secret": True},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:archived",
                        "type": "item",
                        "name": "Archived Relic",
                        "status": "archived",
                        "summary": "Archived item.",
                        "item": {"category": "relic", "quantity": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:archived-variant",
                        "type": "item",
                        "name": "Archived Variant",
                        "status": "\u001cＡ\u20dd\u034f\u200cｒｃｈｉｖｅｄ\u202f",
                        "summary": "Archived item with non-canonical casing.",
                        "item": {"category": "relic", "quantity": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden-variant",
                        "type": "character",
                        "name": "Hidden Variant",
                        "visibility": "\u001fＨ\u0903ｉ\u034f\u200cｄｄｅｎ\u3000",
                        "summary": "Hidden contact with non-canonical casing.",
                    },
                )
                rebuild_fts(conn)
                conn.commit()

                visible = read_entity(conn, "loc:visible")
                self.assertIsInstance(visible, EntityRecord)
                self.assertEqual(visible.id, "loc:visible")
                self.assertEqual(visible.type, "location")
                self.assertEqual(visible.status, "active")
                self.assertEqual(visible.visibility, "known")
                self.assertEqual(visible.details, {"region": "north"})
                self.assertTrue(visible.updated_turn_id)
                self.assertTrue(visible.updated_at)

                self.assertIsNone(read_entity(conn, "npc:hidden", view="player"))
                self.assertIsNone(read_entity(conn, "npc:hidden-variant", view="player"))
                hidden_for_gm = read_entity(conn, "npc:hidden", view="gm")
                self.assertIsNotNone(hidden_for_gm)
                self.assertEqual(hidden_for_gm.details, {"secret": True})
                unicode_gm_hidden = read_entity(conn, "npc:hidden", view="\u2060ＧＭ\u2060")
                self.assertIsNotNone(unicode_gm_hidden)
                unicode_maintenance_ids = {
                    entity.id for entity in list_entities(conn, view="\u2060ＭＡＩＮＴＥＮＡＮＣＥ\u2060")
                }
                self.assertIn("npc:hidden", unicode_maintenance_ids)
                self.assertIn("npc:hidden-variant", unicode_maintenance_ids)

                self.assertIsNone(read_entity(conn, "item:archived"))
                self.assertIsNone(read_entity(conn, "item:archived-variant"))
                archived = read_entity(conn, "item:archived", include_archived=True)
                self.assertIsNotNone(archived)
                self.assertEqual(archived.status, "archived")
                self.assertIsNone(resolve_entity(conn, "item:archived-variant", view="player"))
                self.assertIsNone(resolve_entity(conn, "npc:hidden-variant", view="player"))
                hidden_variant_for_gm = resolve_entity(conn, "npc:hidden-variant", view="gm")
                self.assertIsNotNone(hidden_variant_for_gm)
                self.assertEqual(hidden_variant_for_gm["id"], "npc:hidden-variant")
                fts_ids = {row["entity_id"] for row in conn.execute("select entity_id from fts_index")}
                self.assertNotIn("item:archived-variant", fts_ids)
                self.assertNotIn("npc:hidden-variant", fts_ids)

                default_ids = {entity.id for entity in list_entities(conn, view="player")}
                self.assertIn("loc:visible", default_ids)
                self.assertNotIn("item:archived", default_ids)
                self.assertNotIn("item:archived-variant", default_ids)
                self.assertNotIn("npc:hidden", default_ids)
                self.assertNotIn("npc:hidden-variant", default_ids)

                player_ids = {entity.id for entity in list_entities(conn, view="player", include_archived=True)}
                self.assertIn("loc:visible", player_ids)
                self.assertIn("item:archived", player_ids)
                self.assertNotIn("npc:hidden", player_ids)
                self.assertNotIn("npc:hidden-variant", player_ids)

                self.assertEqual(list_entities(conn, statuses=["archived"]), [])
                archived_items = list_entities(conn, statuses="\u001cＡＲＣＨＩＶＥＤ\u2060", types="ＩＴＥＭ", include_archived=True)
                self.assertEqual([entity.id for entity in archived_items], ["item:archived", "item:archived-variant"])
                location_ids = {entity.id for entity in list_entities(conn, statuses="ACTIVE", types="LOCATION")}
                self.assertIn("loc:visible", location_ids)

                with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                    list_entities(conn, limit="2")
                with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                    list_entities(conn, limit=True)
                with self.assertRaisesRegex(ValueError, "include_archived must be boolean"):
                    read_entity(conn, "item:archived", include_archived="yes")
                with self.assertRaisesRegex(ValueError, "include_archived must be boolean"):
                    list_entities(conn, include_archived=1)
                with self.assertRaisesRegex(ValueError, "statuses must be string or sequence of strings"):
                    list_entities(conn, statuses=123)  # type: ignore[arg-type]
                with self.assertRaisesRegex(ValueError, "types must be string or sequence of strings"):
                    list_entities(conn, types=b"item")  # type: ignore[arg-type]
                with self.assertRaisesRegex(ValueError, "types must be string or sequence of strings"):
                    list_entities(conn, types=["item", 5])  # type: ignore[list-item]

    def test_hidden_clock_subtype_visibility_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-threat",
                        "name": "Hidden Threat",
                        "summary": "A hidden clock.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "\u001cＨ\u0903ｉ\u034f\u200cｄｄｅｎ\u202f",
                        "trigger_when_full": "Threat arrives.",
                    },
                )
                conn.commit()

                self.assertIsNone(read_entity(conn, "clock:hidden-threat", view="player"))
                clock = read_entity(conn, "clock:hidden-threat", view="maintenance")
                self.assertIsNotNone(clock)
                self.assertEqual(clock.type, "clock")
                rebuild_fts(conn)
                fts_ids = {row["entity_id"] for row in conn.execute("select entity_id from fts_index")}
                self.assertNotIn("clock:hidden-threat", fts_ids)

    def test_delta_reference_validation_allows_existing_and_same_delta_entities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:camp",
                        "type": "location",
                        "name": "Camp",
                        "summary": "Known camp.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "species:human",
                        "type": "species",
                        "name": "Human",
                        "summary": "Known species.",
                    },
                )
                conn.commit()

                valid_delta = {
                    "location_before": "loc:camp",
                    "location_after": "loc:new-room",
                    "meta": {"current_location_id": "loc:new-room"},
                    "upsert_entities": [
                        {
                            "id": "loc:new-room",
                            "type": "location",
                            "name": "New Room",
                            "summary": "Created in same delta.",
                            "location": {"parent_id": "loc:camp"},
                        },
                        {
                            "id": "npc:new",
                            "type": "character",
                            "name": "New NPC",
                            "summary": "Created in same delta.",
                            "location_id": "loc:new-room",
                            "character": {"species_id": "species:human"},
                        },
                        {
                            "id": "plant:new",
                            "type": "plant",
                            "name": "New Plant",
                            "summary": "Created in same delta.",
                        },
                        {
                            "id": "plot:new",
                            "type": "crop_plot",
                            "name": "New Plot",
                            "summary": "Created in same delta.",
                            "crop_plot": {"plot_no": 1, "crop_entity_id": "plant:new"},
                        },
                    ],
                }
                self.assertEqual(validate_delta_entity_references(conn, valid_delta), [])
                non_location_current_errors = validate_delta_entity_references(
                    conn,
                    {"meta": {"current_location_id": "species:human"}},
                )
                self.assertEqual(
                    non_location_current_errors,
                    ["$.meta.current_location_id: must reference location entity species:human"],
                )
                same_delta_non_location_current_errors = validate_delta_entity_references(
                    conn,
                    {
                        "meta": {"current_location_id": "item:new-current"},
                        "upsert_entities": [
                            {
                                "id": "item:new-current",
                                "type": "item",
                                "name": "New Current",
                                "summary": "Not a location.",
                            }
                        ],
                    },
                )
                self.assertEqual(
                    same_delta_non_location_current_errors,
                    ["$.meta.current_location_id: must reference location entity item:new-current"],
                )

                invalid_delta = {
                    "location_after": "loc:missing",
                    "upsert_entities": [
                        {
                            "id": "npc:bad",
                            "type": "character",
                            "name": "Bad NPC",
                            "summary": "Invalid refs.",
                            "location_id": "loc:missing",
                            "owner_id": "pc:missing",
                        }
                    ],
                }
                errors = validate_delta_entity_references(conn, invalid_delta)
                self.assertIn("$.location_after: missing entity loc:missing", errors)
                self.assertIn("$.upsert_entities[0].location_id: missing entity loc:missing", errors)
                self.assertIn("$.upsert_entities[0].owner_id: missing entity pc:missing", errors)

                crop_ref_errors = validate_delta_entity_references(
                    conn,
                    {
                        "upsert_entities": [
                            {
                                "id": "plot:bad",
                                "type": "crop_plot",
                                "name": "Bad Plot",
                                "summary": "Invalid crop ref.",
                                "crop_plot": {"plot_no": 1, "crop_entity_id": "plant:missing"},
                            }
                        ],
                    },
                )
                self.assertIn("$.upsert_entities[0].crop_plot.crop_entity_id: missing entity plant:missing", crop_ref_errors)

                missing_crop_ref_errors = validate_delta_entity_references(
                    conn,
                    {
                        "upsert_entities": [
                            {
                                "id": "plot:missing-crop",
                                "type": "crop_plot",
                                "name": "Missing Crop",
                                "summary": "No crop ref.",
                                "crop_plot": {"plot_no": 1},
                            }
                        ],
                    },
                )
                self.assertEqual(missing_crop_ref_errors, [])

                self.assertEqual(validate_delta_entity_references(conn, []), ["$ must be an object"])
                empty_ref_errors = validate_delta_entity_references(
                    conn,
                    {
                        "meta": {"current_location_id": ""},
                        "upsert_entities": [
                            {
                                "id": "npc:empty-ref",
                                "type": "character",
                                "name": "Empty Ref",
                                "summary": "Invalid empty ref.",
                                "location_id": "",
                                "character": {"species_id": 0},
                            }
                        ],
                    },
                )
                self.assertIn("$.meta.current_location_id: must be non-empty string", empty_ref_errors)
                self.assertIn("$.upsert_entities[0].location_id: must be non-empty string", empty_ref_errors)
                self.assertIn("$.upsert_entities[0].character.species_id: must be non-empty string", empty_ref_errors)
                whitespace_ref_errors = validate_delta_entity_references(
                    conn,
                    {"location_after": " loc:camp "},
                )
                self.assertEqual(
                    whitespace_ref_errors,
                    ["$.location_after: must not contain leading or trailing whitespace"],
                )
                invalid_same_delta_errors = validate_delta_entity_references(
                    conn,
                    {
                        "location_after": "not-an-entity-id",
                        "upsert_entities": [
                            {
                                "id": "not-an-entity-id",
                                "type": "location",
                                "name": "Invalid ID",
                                "summary": "Should not count as same-delta ref.",
                            }
                        ],
                    },
                )
                self.assertIn("$.location_after: invalid entity id", invalid_same_delta_errors)

    def test_delta_schema_uses_entity_access_reference_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:camp",
                        "type": "location",
                        "name": "Camp",
                        "summary": "Known camp.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "pc:owner",
                        "type": "character",
                        "name": "Owner",
                        "summary": "Known owner.",
                    },
                )
                conn.commit()

                missing_ref_delta = {
                    "user_text": "move",
                    "intent": "test",
                    "summary": "Missing destination.",
                    "location_after": "loc:missing",
                    "events": [
                        {
                            "type": "test",
                            "title": "Move",
                            "summary": "Move attempted.",
                            "source": "test",
                        }
                    ],
                }
                missing_errors = validate_delta_schema(missing_ref_delta, conn)
                self.assertIn("$.location_after: missing entity loc:missing", missing_errors)

                empty_ref_delta = {
                    "user_text": "move",
                    "intent": "test",
                    "summary": "Empty destination.",
                    "location_after": "",
                    "events": [
                        {
                            "type": "test",
                            "title": "Move",
                            "summary": "Move attempted.",
                            "source": "test",
                        }
                    ],
                }
                empty_ref_schema_errors = validate_delta_schema(empty_ref_delta, conn)
                self.assertEqual(empty_ref_schema_errors.count("$.location_after: must be non-empty string"), 1)

                invariant_delta = {
                    "user_text": "take item",
                    "intent": "test",
                    "summary": "Invalid ownership.",
                    "events": [
                        {
                            "type": "test",
                            "title": "Take",
                            "summary": "Item state changed.",
                            "source": "test",
                        }
                    ],
                    "upsert_entities": [
                        {
                            "id": "item:bad",
                            "type": "item",
                            "name": "Bad Item",
                            "summary": "Both owner and location set.",
                            "location_id": "loc:camp",
                            "owner_id": "pc:owner",
                            "item": {"category": "gear", "quantity": 1},
                        }
                    ],
                }
                invariant_errors = validate_delta_schema(invariant_delta, conn)
                self.assertIn(
                    "$.upsert_entities[0]: active entity cannot set both owner_id and location_id",
                    invariant_errors,
                )
                self.assertFalse(any("missing entity loc:camp" in error for error in invariant_errors))
                self.assertFalse(any("missing entity pc:owner" in error for error in invariant_errors))

                missing_plot_no_delta = {
                    "user_text": "plant crop",
                    "intent": "test",
                    "summary": "Invalid plot.",
                    "events": [
                        {
                            "type": "test",
                            "title": "Plant",
                            "summary": "Plot state changed.",
                            "source": "test",
                        }
                    ],
                    "upsert_entities": [
                        {
                            "id": "plant:new",
                            "type": "plant",
                            "name": "New Plant",
                            "summary": "Crop.",
                        },
                        {
                            "id": "plot:bad",
                            "type": "crop_plot",
                            "name": "Bad Plot",
                            "summary": "Missing plot number.",
                            "crop_plot": {"crop_entity_id": "plant:new"},
                        },
                    ],
                }
                missing_plot_errors = validate_delta_schema(missing_plot_no_delta, conn)
                self.assertIn("$.upsert_entities[1].crop_plot.plot_no: required integer", missing_plot_errors)

                missing_crop_ref_schema_delta = {
                    "user_text": "plant crop",
                    "intent": "test",
                    "summary": "Invalid plot.",
                    "events": [
                        {
                            "type": "test",
                            "title": "Plant",
                            "summary": "Plot state changed.",
                            "source": "test",
                        }
                    ],
                    "upsert_entities": [
                        {
                            "id": "plot:missing-crop",
                            "type": "crop_plot",
                            "name": "Bad Plot",
                            "summary": "Missing crop entity.",
                            "crop_plot": {"plot_no": 1},
                        }
                    ],
                }
                missing_crop_ref_schema_errors = validate_delta_schema(missing_crop_ref_schema_delta, conn)
                self.assertEqual(
                    missing_crop_ref_schema_errors.count(
                        "$.upsert_entities[0].crop_plot.crop_entity_id: required"
                    ),
                    1,
                )

                missing_crop_subrecord_delta = {
                    "user_text": "plant crop",
                    "intent": "test",
                    "summary": "Invalid plot.",
                    "events": [
                        {
                            "type": "test",
                            "title": "Plant",
                            "summary": "Plot state changed.",
                            "source": "test",
                        }
                    ],
                    "upsert_entities": [
                        {
                            "id": "plot:no-subrecord",
                            "type": "crop_plot",
                            "name": "Bad Plot",
                            "summary": "Missing crop_plot subrecord.",
                        }
                    ],
                }
                missing_subrecord_errors = validate_delta_schema(missing_crop_subrecord_delta, conn)
                self.assertIn("$.upsert_entities[0].crop_plot: required", missing_subrecord_errors)

    def test_player_context_uses_entity_access_visibility_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-threat",
                        "name": "Hidden Threat",
                        "summary": "A hidden clock.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "Threat arrives.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:entity-hidden",
                        "name": "Entity Hidden Clock",
                        "summary": "A clock with hidden entity row.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "Threat arrives.",
                    },
                )
                conn.execute("update entities set visibility = 'hidden' where id = 'clock:entity-hidden'")
                upsert_entity(
                    conn,
                    {
                        "id": "item:archived-variant",
                        "type": "item",
                        "name": "Archived Variant",
                        "status": "\u001cＡ\u034f\u200cｒｃｈｉｖｅｄ\u2060",
                        "summary": "Archived entity with non-canonical status.",
                        "item": {"category": "relic", "quantity": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:visible-ref",
                        "type": "item",
                        "name": "Visible Reference",
                        "summary": "Mentions clock:hidden-threat, clock:entity-hidden, and item:archived-variant.",
                        "item": {"category": "note", "quantity": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:archived-variant",
                        "type": "location",
                        "name": "Archived Location",
                        "status": "\u001cＡ\u034f\u200cｒｃｈｉｖｅｄ\u2060",
                        "summary": "Archived location.",
                    },
                )
                rebuild_fts(conn)
                conn.commit()

                write_cards(campaign, conn, index_view="player")
                self.assertFalse((campaign.cards_path / "clocks" / "clock__hidden-threat.md").exists())
                self.assertFalse((campaign.cards_path / "clocks" / "clock__entity-hidden.md").exists())
                self.assertFalse((campaign.cards_path / "items" / "item__archived-variant.md").exists())
                index_text = (campaign.cards_path / "INDEX.md").read_text(encoding="utf-8")
                self.assertNotIn("clock:hidden-threat", index_text)
                self.assertNotIn("clock:entity-hidden", index_text)
                visible_card = (campaign.cards_path / "items" / "item__visible-ref.md").read_text(encoding="utf-8")
                self.assertNotIn("clock:hidden-threat", visible_card)
                self.assertNotIn("clock:entity-hidden", visible_card)
                self.assertNotIn("item:archived-variant", visible_card)
                self.assertIn("[hidden]", visible_card)

                self.assertIsNone(resolve_location(conn, "Archived Location"))
                self.assertFalse(
                    any(
                        row["id"] == "item:archived-variant"
                        for row in find_entity_candidates(conn, "Archived Variant", allowed_types=None)
                    )
                )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', 'loc:archived-variant') "
                    "on conflict(key) do update set value=excluded.value"
                )
                self.assertIn("当前地点不可见或不存在", render_scene(conn, view="player"))

                hidden_packet = build_context(
                    campaign,
                    conn,
                    user_text="Hidden Threat Entity Hidden Clock",
                    mode="query",
                    budget=900,
                    max_events=0,
                )
                hidden_ids = {item["id"] for item in hidden_packet.loaded_items}
                self.assertNotIn("clock:hidden-threat", hidden_ids)
                self.assertNotIn("clock:entity-hidden", hidden_ids)
                active_clocks_section = hidden_packet.sections.get("active_clocks", "")
                self.assertNotIn("Hidden Threat", active_clocks_section)
                self.assertNotIn("Entity Hidden Clock", active_clocks_section)
                maintenance_packet = build_context(
                    campaign,
                    conn,
                    user_text="Hidden Threat Entity Hidden Clock",
                    mode="maintenance",
                    budget=900,
                    max_events=0,
                )
                maintenance_clocks = maintenance_packet.sections.get("active_clocks", "")
                self.assertIn("Hidden Threat", maintenance_clocks)
                self.assertIn("clock:hidden-threat", maintenance_clocks)

                archived_packet = build_context(
                    campaign,
                    conn,
                    user_text="Archived Variant",
                    mode="query",
                    budget=900,
                    max_events=0,
                )
                archived_ids = {item["id"] for item in archived_packet.loaded_items}
                self.assertNotIn("item:archived-variant", archived_ids)

    def test_player_read_surfaces_share_entity_visibility_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-route",
                        "type": "location",
                        "name": "Visible Route",
                        "summary": "Visible route hub.",
                        "location": {
                            "description_short": "A visible route hub mentions loc:hidden-route Hidden Route Secret Route Alias."
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden-parent",
                        "type": "location",
                        "name": "Hidden Parent",
                        "visibility": "hidden",
                        "summary": "Hidden parent location.",
                        "location": {"description_short": "Hidden parent."},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-child-a",
                        "type": "location",
                        "name": "Visible Child A",
                        "summary": "Visible child A.",
                        "location": {"parent_id": "loc:hidden-parent", "description_short": "Visible child A."},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:visible-child-b",
                        "type": "location",
                        "name": "Visible Child B",
                        "summary": "Visible child B.",
                        "location": {"parent_id": "loc:hidden-parent", "description_short": "Visible child B."},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:hidden-route",
                        "type": "location",
                        "name": "Hidden Route",
                        "visibility": "\u001fＨ\u0903ｉｄｄｅｎ\u3000",
                        "summary": "Hidden destination.",
                        "aliases": ["Secret Route Alias"],
                        "location": {"description_short": "A hidden destination."},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "species:hidden",
                        "type": "species",
                        "name": "Hidden Species",
                        "visibility": "hidden",
                        "summary": "Hidden species.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:leaky-visible",
                        "type": "item",
                        "name": "Leaky Visible",
                        "location_id": "loc:hidden-route",
                        "summary": "Mentions loc:hidden-route Hidden Route Secret Route Alias.",
                        "details": {"note": "Hidden Species and species:hidden should not leak."},
                        "item": {"category": "material", "quantity": 1},
                    },
                )
                upsert_route(
                    conn,
                    {
                        "id": "route:hidden",
                        "from_location_id": "loc:visible-route",
                        "to_location_id": "loc:hidden-route",
                        "travel_minutes": 5,
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-suggestion",
                        "name": "Hidden Suggestion",
                        "summary": "Hidden clock suggestion.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "\u001cＨ\u0903ｉｄｄｅｎ\u202f",
                        "trigger_when_full": "Hidden event.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-social",
                        "name": "Hidden Social Clock",
                        "summary": "Hidden social fallback clock.",
                        "clock_type": "relationship",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "Hidden social event.",
                    },
                )
                upsert_route(
                    conn,
                    {
                        "id": "route:hidden-clock",
                        "from_location_id": "loc:visible-route",
                        "to_location_id": "clock:hidden-suggestion",
                        "travel_minutes": 4,
                    },
                )
                conn.execute("update entities set location_id = ? where id = ?", ("loc:visible-route", "clock:hidden-suggestion"))
                conn.execute(
                    """
                    insert into items
                    (entity_id, category, quantity, unit, quality, durability_current, durability_max, stackable, equipped_slot, properties_json)
                    values ('clock:hidden-suggestion', 'material', 1, null, null, null, null, 0, null, '{}')
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden-route-target",
                        "type": "character",
                        "name": "Remote Target",
                        "location_id": "loc:hidden-route",
                        "summary": "NPC in hidden destination.",
                        "character": {"trust": 1, "species_id": "species:hidden"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden-parent-target",
                        "type": "character",
                        "name": "Hidden Parent Target",
                        "location_id": "loc:visible-child-b",
                        "summary": "NPC in visible child under hidden parent.",
                        "character": {"trust": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "recipe:hidden",
                        "type": "recipe",
                        "name": "Hidden Recipe",
                        "visibility": "hidden",
                        "summary": "Hidden recipe.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:hidden-material",
                        "type": "item",
                        "name": "Hidden Material",
                        "visibility": "hidden",
                        "location_id": "loc:visible-route",
                        "summary": "Hidden local material.",
                        "item": {"category": "material", "quantity": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "npc:hidden-memory",
                        "type": "character",
                        "name": "Hidden Memory",
                        "visibility": "\u001fＨ\u0903ｉｄｄｅｎ\u3000",
                        "summary": "Hidden memory subject.",
                        "character": {"trust": 1},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "project:archived-memory",
                        "type": "project",
                        "name": "Archived Memory",
                        "status": "\u001cＡ\u20ddｒｃｈｉｖｅｄ\u2060",
                        "summary": "Archived memory subject.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "material:archived-audit",
                        "type": "material",
                        "name": "Bad",
                        "status": "\u001cＡ\u20ddｒｃｈｉｖｅｄ\u2060",
                        "summary": "short",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "fstate:archived-report",
                        "type": "faction_state",
                        "name": "Archived Report",
                        "status": "\u001cＡ\u20ddｒｃｈｉｖｅｄ\u2060",
                        "summary": "Archived report row.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plant:visible",
                        "type": "plant",
                        "name": "Visible Crop",
                        "summary": "Visible crop.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plant:hidden",
                        "type": "plant",
                        "name": "Hidden Crop",
                        "visibility": "hidden",
                        "summary": "Hidden crop.",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plot:hidden",
                        "type": "crop_plot",
                        "name": "Hidden Plot",
                        "visibility": "hidden",
                        "summary": "Hidden crop plot.",
                        "crop_plot": {
                            "plot_no": 1,
                            "crop_entity_id": "plant:visible",
                            "harvest_day_min": 0,
                            "harvest_status": "partial_harvest",
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plot:hidden-clock-crop",
                        "type": "crop_plot",
                        "name": "Hidden Clock Crop Plot",
                        "summary": "Visible plot with hidden clock crop.",
                        "crop_plot": {
                            "plot_no": 3,
                            "crop_entity_id": "clock:hidden-suggestion",
                            "harvest_day_min": 0,
                            "harvest_status": "partial_harvest",
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "plot:hidden-crop",
                        "type": "crop_plot",
                        "name": "Hidden Crop Plot",
                        "summary": "Visible plot with hidden crop.",
                        "crop_plot": {
                            "plot_no": 2,
                            "crop_entity_id": "plant:hidden",
                            "harvest_day_min": 0,
                            "harvest_status": "partial_harvest",
                        },
                    },
                )
                conn.execute(
                    """
                    insert or replace into world_settings
                    (entity_id, category, scope, visibility, priority, summary, content_json,
                     linked_rules_json, linked_clocks_json, linked_entities_json, applies_when_json, source)
                    values (?, 'general', 'world', 'known', 100, 'Hidden world setting.', '{}',
                            '[]', '[]', '[]', '{"keywords":["Hidden Suggestion"]}', 'test')
                    """,
                    ("clock:hidden-suggestion",),
                )
                conn.execute(
                    """
                    insert into events(id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, 'turn:seed', '第1天 morning', 'note', ?, ?, ?, 'test', '2026-07-08T00:00:00+00:00')
                    """,
                    (
                        "event:hidden-ref",
                        "Heard Hidden Route",
                        "Event mentions loc:hidden-route and Secret Route Alias.",
                        '{"key_points":["Hidden Species species:hidden"]}',
                    ),
                )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:visible-route",),
                )
                conn.commit()

                self.assertEqual(find_candidate_entities(conn, "   ", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "the and what did prove", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "to in of", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "a an to", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "what is", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "where is", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "look at", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "show around", limit=5), [])
                self.assertEqual(find_candidate_entities(conn, "查看 查询", limit=5), [])
                self.assertEqual(
                    find_trusted_token_candidate_entities(conn, "Hidden Route", limit=5, view="player"),
                    [],
                )

                hidden_clock_palette = evaluate_palette_entry(
                    conn,
                    {
                        "id": "pal:hidden-clock-gated",
                        "_kind": "material",
                        "name": "Hidden gated material",
                        "summary": "Hidden gated material.",
                        "unlock": {"required_clocks": {"clock:hidden-suggestion": 1}},
                    },
                    {"day": 1, "intent": "gather", "location": None, "location_id": None, "biome": None},
                )
                self.assertEqual(hidden_clock_palette["status"], "locked")
                self.assertNotIn("clock:hidden-suggestion", "\n".join(hidden_clock_palette["unmet"]))

                self.assertIsNone(resolve_recipe(conn, "Hidden Recipe"))
                self.assertIsNone(first_visible_entity_in_text(conn, "Hidden Suggestion", None))
                self.assertIsNone(current_location_row(conn, {"current_location_id": "clock:hidden-suggestion"}))
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("plant:visible",),
                )
                self.assertIn("当前地点不可见或不存在", render_scene(conn, view="player"))
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:visible-route",),
                )
                self.assertIsNone(current_location_row(conn, {"current_location_id": "plant:visible"}))
                self.assertIsNone(location_detail_row(conn, "loc:hidden-route"))
                self.assertIsNotNone(location_detail_row(conn, "loc:visible-route"))
                self.assertIsNone(shortest_route_plan(conn, "loc:visible-route", "loc:hidden-route"))
                explore_blocked = resolve_explore(
                    campaign,
                    conn,
                    {},
                    SimpleNamespace(target="loc:hidden-route", location=None, approach=None, user_text=None, unknown_lead=False),
                )
                routine_preview = preview_routine(
                    campaign,
                    conn,
                    {},
                    SimpleNamespace(task="检查", target="loc:hidden-route", focus=None, time_cost=None, user_text=None),
                )
                routine_result = resolve_routine(
                    campaign,
                    conn,
                    {},
                    SimpleNamespace(task="检查", target="loc:hidden-route", focus=None, time_cost=None, user_text=None),
                )
                for hidden_text in ("loc:hidden-route", "Hidden Route", "Secret Route Alias"):
                    self.assertNotIn(hidden_text, " ".join(explore_blocked.confirmations))
                    self.assertNotIn(hidden_text, explore_blocked.player_message)
                    self.assertNotIn(hidden_text, str(explore_blocked.repair_options))
                    self.assertNotIn(hidden_text, routine_preview)
                    self.assertNotIn(hidden_text, str(routine_result.proposed_delta))
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:hidden-route",),
                )
                rest_preview = render_rest_preview(conn)
                craft_preview = render_craft_preview(conn)
                combat_preview = render_combat_preview(conn, target_query="Leaky Visible")
                travel_preview = render_travel_preview(conn, destination_query="Visible Route")
                gather_preview = render_gather_preview(conn, target_query="Leaky Visible")
                social_hidden_current_preview = render_social_preview(
                    conn,
                    npc_query="Remote Target",
                    topic="问候",
                    approach="低压",
                )
                hidden_scene = render_scene(conn, view="player")
                hidden_snapshot = render_current_snapshot(campaign, conn, view="player")
                hidden_snapshot_json = render_current_snapshot_json(campaign, conn, view="player")
                hidden_context = build_context(
                    campaign,
                    conn,
                    user_text="查看当前状态",
                    mode="query",
                    budget=500,
                    max_events=0,
                )
                hidden_world_memory = build_world_memories(conn)[0]
                snapshot_errors: list[str] = []
                validate_snapshot_json(
                    campaign.current_snapshot_path,
                    write_current_snapshot_json(campaign, conn, view="player"),
                    conn,
                    get_meta(conn),
                    campaign.campaign_id,
                    snapshot_errors,
                )
                self.assertNotIn("loc:hidden-route", rest_preview)
                self.assertNotIn("loc:hidden-route", craft_preview)
                self.assertNotIn("loc:hidden-route", combat_preview)
                self.assertNotIn("loc:hidden-route", travel_preview)
                self.assertNotIn("Hidden Route", combat_preview)
                self.assertNotIn("loc:hidden-route", gather_preview)
                self.assertNotIn("Hidden Route", gather_preview)
                self.assertNotIn("Secret Route Alias", gather_preview)
                self.assertNotIn("loc:hidden-route", social_hidden_current_preview)
                self.assertNotIn("loc:hidden-route", hidden_scene)
                self.assertNotIn("loc:hidden-route", hidden_snapshot)
                self.assertNotIn("loc:hidden-route", str(hidden_snapshot_json))
                self.assertNotIn("loc:hidden-route", "\n".join(hidden_context.sections.values()))
                self.assertNotIn("loc:hidden-route", "\n".join(hidden_world_memory["key_points"]))
                self.assertEqual(snapshot_errors, [])
                self.assertIn(
                    "meta.current_location_id points to missing or unreadable location: loc:hidden-route",
                    run_checks(conn),
                )
                self.assertIn("当前地点不可见", rest_preview)
                self.assertIn("当前地点不可见", combat_preview)
                self.assertIn("当前地点不可见", gather_preview)
                self.assertIn("当前地点不可见", social_hidden_current_preview)
                self.assertIn("当前地点不可见或不存在", hidden_scene)
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:visible-route",),
                )
                conn.execute(
                    "insert into meta(key, value) values('home_location_ids', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ('["loc:hidden-route", "loc:visible-route"]',),
                )
                visible_scene = render_scene(conn, view="player")
                visible_snapshot_json = render_current_snapshot_json(campaign, conn, view="player")
                visible_scene_snapshot = str(visible_snapshot_json)
                for hidden_text in ("loc:hidden-route", "Hidden Route", "Secret Route Alias"):
                    self.assertNotIn(hidden_text, visible_scene)
                    self.assertNotIn(hidden_text, visible_scene_snapshot)
                hidden_route_npc = conn.execute("select * from entities where id = 'npc:hidden-route-target'").fetchone()
                hidden_scope = social_scope(
                    conn,
                    {"meta": {"current_location_id": "loc:visible-route"}, "npc": hidden_route_npc},
                )
                self.assertEqual(hidden_scope.kind, "blocked")
                self.assertIsNone(hidden_scope.route_id)
                social_preview = render_social_preview(
                    conn,
                    npc_query="Remote Target",
                    topic="问候",
                    approach="低压",
                )
                social_result = resolve_social(
                    campaign,
                    conn,
                    {},
                    SimpleNamespace(npc="Remote Target", topic="问候", approach="低压"),
                )
                self.assertNotIn("loc:hidden-route", social_preview)
                self.assertNotIn("loc:hidden-route", "\n".join(social_result.confirmations))
                self.assertNotIn("loc:hidden-route", social_result.player_message)
                combat_data = resolve_combat_inputs(
                    conn,
                    SimpleNamespace(target="Leaky Visible", weapon="missing", ammo="missing", distance="近距"),
                )
                combat_blocker_text = "\n".join(combat_blockers(combat_data, conn))
                self.assertNotIn("loc:hidden-route", combat_blocker_text)
                self.assertNotIn("Hidden Route", combat_blocker_text)
                leaky_query = render_entity(conn, "item:leaky-visible")
                self.assertNotIn("loc:hidden-route", leaky_query)
                self.assertNotIn("Hidden Route", leaky_query)
                self.assertNotIn("Secret Route Alias", leaky_query)
                hidden_parent_npc = conn.execute("select * from entities where id = 'npc:hidden-parent-target'").fetchone()
                hidden_parent_scope = social_scope(
                    conn,
                    {"meta": {"current_location_id": "loc:visible-child-a"}, "npc": hidden_parent_npc},
                )
                self.assertNotEqual(hidden_parent_scope.kind, "same_parent")
                self.assertIsNone(hidden_parent_scope.parent_id)
                self.assertNotIn("item:hidden-material", {row["id"] for row in gatherable_items(conn, "loc:visible-route")})
                self.assertNotIn("clock:hidden-suggestion", {row["id"] for row in gatherable_items(conn, "loc:visible-route")})
                self.assertNotIn(
                    "item:hidden-material",
                    {row["id"] for row in nearby_crafting_candidates(conn, {"current_location_id": "loc:visible-route"})},
                )
                self.assertNotIn(
                    "clock:hidden-suggestion",
                    {row["id"] for row in nearby_crafting_candidates(conn, {"current_location_id": "loc:visible-route"})},
                )
                self.assertNotIn(
                    "item:leaky-visible",
                    {row["id"] for row in nearby_crafting_candidates(conn, {"current_location_id": "loc:hidden-route"})},
                )
                self.assertEqual([row["entity_id"] for row in matching_clock_rows(conn, ["Hidden Suggestion"])], [])
                self.assertEqual([row["entity_id"] for row in social_relevant_clocks(conn, None, "unmatched", None)], [])
                self.assertEqual(summarize_crop_plots(conn)["total"], 0)
                self.assertEqual(harvestable_crop_rows(conn, 0), [])
                self.assertNotIn("Hidden Suggestion", render_scene(conn, view="player"))
                rebuild_fts(conn)
                fts_text = "\n".join(
                    "".join(str(row[key] or "") for key in ("title", "body", "tags"))
                    for row in conn.execute("select title, body, tags from fts_index").fetchall()
                )
                for hidden_text in ("loc:hidden-route", "Hidden Route", "Secret Route Alias", "species:hidden", "Hidden Species"):
                    self.assertNotIn(hidden_text, fts_text)

                write_cards(campaign, conn, index_view="player")
                route_card = (campaign.cards_path / "locations" / "loc__visible-route.md").read_text(encoding="utf-8")
                self.assertNotIn("loc:hidden-route", route_card)
                self.assertNotIn("Hidden Route", route_card)
                self.assertNotIn("clock:hidden-suggestion", route_card)
                self.assertNotIn("Hidden Suggestion", route_card)
                leaky_card = (campaign.cards_path / "items" / "item__leaky-visible.md").read_text(encoding="utf-8")
                hidden_route_npc_card = (
                    campaign.cards_path / "characters" / "npc__hidden-route-target.md"
                ).read_text(encoding="utf-8")
                hidden_parent_location_card = (
                    campaign.cards_path / "locations" / "loc__visible-child-a.md"
                ).read_text(encoding="utf-8")
                for hidden_text in ("loc:hidden-route", "Hidden Route", "Secret Route Alias", "species:hidden", "Hidden Species"):
                    self.assertNotIn(hidden_text, leaky_card)
                    self.assertNotIn(hidden_text, hidden_route_npc_card)
                self.assertNotIn("loc:hidden-parent", hidden_parent_location_card)
                hidden_crop_card = (campaign.cards_path / "crop_plots" / "plot__hidden-crop.md").read_text(encoding="utf-8")
                hidden_clock_crop_card = (
                    campaign.cards_path / "crop_plots" / "plot__hidden-clock-crop.md"
                ).read_text(encoding="utf-8")
                self.assertNotIn("plant:hidden", hidden_crop_card)
                self.assertNotIn("clock:hidden-suggestion", hidden_clock_crop_card)
                self.assertIn("[hidden]", hidden_crop_card)
                self.assertIn("[hidden]", hidden_clock_crop_card)

                card_errors: list[str] = []
                leaky_card_path = campaign.cards_path / "items" / "item__leaky-visible.md"
                leaky_card_path.write_text(leaky_card + "\nHidden Route\n", encoding="utf-8")
                stale_card_path = campaign.cards_path / "locations" / "loc__hidden-route.md"
                stale_card_path.write_text(f"{GENERATED_MARKER}\n# stale hidden card\n", encoding="utf-8")
                (campaign.cards_path / "INDEX.md").write_text("loc:hidden-route\n", encoding="utf-8")
                validate_cards(campaign.cards_path, conn, card_errors)
                self.assertTrue(any("contains hidden entity refs" in error for error in card_errors), card_errors)
                self.assertTrue(any("stale generated card" in error for error in card_errors), card_errors)

                fts_errors: list[str] = []
                conn.execute(
                    "update fts_index set body = coalesce(body, '') || ' loc:hidden-route Hidden Route' "
                    "where entity_id = 'item:leaky-visible'"
                )
                validate_search_projection(conn, fts_errors)
                self.assertTrue(any("contains hidden entity refs" in error for error in fts_errors), fts_errors)
                rebuild_fts(conn)

                snapshot_path = write_current_snapshot_json(campaign, conn, view="player")
                campaign.current_snapshot_path.write_text("loc:hidden-route\n", encoding="utf-8")
                snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
                snapshot_data["present"].append({"id": "loc:hidden-route", "name": "Hidden Route"})
                snapshot_path.write_text(json.dumps(snapshot_data, ensure_ascii=False), encoding="utf-8")
                hidden_snapshot_errors: list[str] = []
                validate_snapshot_json(
                    campaign.current_snapshot_path,
                    snapshot_path,
                    conn,
                    get_meta(conn),
                    campaign.campaign_id,
                    hidden_snapshot_errors,
                )
                self.assertTrue(
                    any("contains hidden entity refs" in error for error in hidden_snapshot_errors),
                    hidden_snapshot_errors,
                )
                visible_placeholder = render_current_snapshot_json(campaign, conn, view="player")
                visible_placeholder["meta"]["current_location_id"] = "当前地点不可见或不存在"
                snapshot_path.write_text(json.dumps(visible_placeholder, ensure_ascii=False), encoding="utf-8")
                placeholder_errors: list[str] = []
                validate_snapshot_json(
                    campaign.current_snapshot_path,
                    snapshot_path,
                    conn,
                    get_meta(conn),
                    campaign.campaign_id,
                    placeholder_errors,
                )
                self.assertTrue(
                    any("placeholder used while current location is visible" in error for error in placeholder_errors),
                    placeholder_errors,
                )

                write_cards(campaign, conn, index_view="\u2060ＭＡＩＮＴＥＮＡＮＣＥ\u2060")
                maintenance_index = (campaign.cards_path / "INDEX.md").read_text(encoding="utf-8")
                self.assertIn("| 索引视角 | 维护 |", maintenance_index)
                self.assertNotIn("ＭＡＩＮＴＥＮＡＮＣＥ", maintenance_index)
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("plant:visible",),
                )
                write_cards(campaign, conn, index_view="player")
                non_location_index = (campaign.cards_path / "INDEX.md").read_text(encoding="utf-8")
                self.assertNotIn("[plant:visible](locations/plant__visible.md)", non_location_index)
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("loc:visible-route",),
                )

                rebuild_memory_summaries(campaign, conn)
                memory_rows = find_relevant_memories(
                    conn,
                    targets=["Hidden Memory", "Archived Memory", "Hidden Suggestion"],
                    limit=10,
                )
                memory_text = "\n".join(row["title"] + row["summary"] + row["key_points_json"] for row in memory_rows)
                self.assertNotIn("Hidden Memory", memory_text)
                self.assertNotIn("Archived Memory", memory_text)
                self.assertNotIn("Hidden Suggestion", memory_text)
                self.assertNotIn("loc:hidden-route", memory_text)
                self.assertNotIn("Secret Route Alias", memory_text)
                self.assertNotIn("species:hidden", memory_text)
                trusted_memory_rows = find_relevant_memories(
                    conn,
                    targets=["Hidden Memory", "loc:hidden-route"],
                    limit=10,
                    view="maintenance",
                )
                trusted_memory_text = "\n".join(
                    row["title"] + row["summary"] + row["key_points_json"] for row in trusted_memory_rows
                )
                self.assertIn("Hidden Memory", trusted_memory_text)
                self.assertIn("loc:hidden-route", trusted_memory_text)

                packet = build_context(
                    campaign,
                    conn,
                    user_text="Hidden Suggestion",
                    mode="query",
                    budget=900,
                    max_events=0,
                )
                self.assertNotIn("clock:hidden-suggestion", {item["id"] for item in packet.loaded_items})
                self.assertNotIn("Hidden Suggestion", packet.sections.get("world_settings", ""))
                maintenance_packet = build_context(
                    campaign,
                    conn,
                    user_text="Hidden Suggestion loc:hidden-route",
                    mode="maintenance",
                    budget=1200,
                    max_events=2,
                )
                maintenance_text = "\n".join(maintenance_packet.sections.values())
                self.assertIn("clock:hidden-suggestion", maintenance_text)
                self.assertIn("Hidden Suggestion", maintenance_text)
                self.assertIn("loc:hidden-route", maintenance_text)
                memory_packet = build_context(
                    campaign,
                    conn,
                    user_text="Hidden Memory loc:hidden-route",
                    mode="maintenance",
                    budget=1200,
                    max_events=2,
                )
                self.assertIn("Hidden Memory", memory_packet.sections.get("memory_summaries", ""))
                self.assertIn("loc:hidden-route", memory_packet.sections.get("memory_summaries", ""))
                self.assertEqual(get_meta(conn)["current_location_id"], "loc:visible-route")

                findings = audit_content_quality(conn)
                self.assertNotIn("material:archived-audit", {finding.entity_id for finding in findings})
                ops_report = build_ops_report(campaign, conn, run_speed=False)
                self.assertNotIn("| faction_state |", ops_report)

    def test_campaign_entity_validator_requires_crop_plot_write_fields(self) -> None:
        errors = validate_entity_record(
            {
                "id": "plot:bad",
                "type": "crop_plot",
                "name": "Bad Plot",
                "summary": "Missing write fields.",
                "crop_plot": {},
            }
        )
        self.assertIn("crop_plot.plot_no: required integer", errors)
        self.assertIn("crop_plot.crop_entity_id: required non-empty string", errors)
        self.assertIn(
            "crop_plot: required",
            validate_entity_record(
                {
                    "id": "plot:no-subrecord",
                    "type": "crop_plot",
                    "name": "Bad Plot",
                    "summary": "Missing subrecord.",
                }
            ),
        )

    def test_save_checks_require_current_location_to_be_a_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "plant:not-location",
                        "type": "plant",
                        "name": "Not Location",
                        "summary": "Not a location.",
                    },
                )
                conn.execute(
                    "insert into meta(key, value) values('current_location_id', ?) "
                    "on conflict(key) do update set value=excluded.value",
                    ("plant:not-location",),
                )
                self.assertIn(
                    "meta.current_location_id points to non-location entity: plant:not-location",
                    run_checks(conn),
                )


if __name__ == "__main__":
    unittest.main()
