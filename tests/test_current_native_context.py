from __future__ import annotations

import json
import sqlite3
import tempfile
from types import SimpleNamespace
from typing import Any
from unittest import mock

from rpg_engine.campaign import load_campaign
from rpg_engine.context.collectors import recent_activity_progress_ids
from rpg_engine.context_builder import build_context
from rpg_engine.db import connect, upsert_clock, upsert_entity
from rpg_engine.memory import ensure_memory_tables
from rpg_engine.projections import mark_projections_dirty
from rpg_engine.runtime import GMRuntime

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    CURRENT_SAVE_ROOT as SAVE_ROOT,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
    current_turn,
    event_log_text,
    load_stdout_json,
    loaded_ids,
    query_int,
    run_cli,
)


@CURRENT_NATIVE_REQUIRED
class CurrentNativeContextTests(FormalCurrentSaveReadOnlyTestCase):
    def test_context_rebinds_omissions_to_changed_projection_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn, connect(campaign) as writer:
                turn_id = str(
                    conn.execute(
                        "select value from meta where key='current_turn_id'"
                    ).fetchone()["value"]
                )
                conn.execute(
                    """
                    insert or replace into main.projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean',
                           '2099-07-10T00:00:00+00:00', null)
                    """,
                    (turn_id,),
                )
                conn.commit()
                marker = "STALE_OMISSION_FROM_OLD_GENERATION"
                changed = False

                def old_generation_omission(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
                    nonlocal changed
                    if not changed:
                        changed = True
                        writer.execute(
                            """
                            update main.projection_state
                            set status='dirty', updated_at='2099-07-10T00:00:01+00:00'
                            where name='memory'
                            """
                        )
                        writer.commit()
                    return [
                        {
                            "id": "memory:omitted:old-generation",
                            "title": marker,
                            "stale_reason": "stored_stale",
                            "visibility_mode": "player",
                            "freshness_status": "stale",
                            "source_event_ids_json": "[]",
                            "source_turn_ids_json": "[]",
                            "freshness_evidence_json": "{}",
                            "derived_authority_json": json.dumps(
                                {
                                    "authority": "derived_context",
                                    "fact_authority": False,
                                }
                            ),
                        }
                    ]

                with (
                    mock.patch(
                        "rpg_engine.context.collectors.find_relevant_memories",
                        return_value=[],
                    ),
                    mock.patch(
                        "rpg_engine.context.collectors.find_omitted_relevant_memories",
                        side_effect=old_generation_omission,
                    ),
                ):
                    result = build_context(
                        campaign,
                        conn,
                        user_text="stable omission snapshot",
                        mode="query",
                        view="player",
                        budget=1800,
                        max_events=0,
                    )

        serialized = result.to_json_text()
        self.assertNotIn(marker, serialized)
        self.assertIn("projection_memory_dirty", serialized)

    def test_context_final_snapshot_gate_freezes_after_repeated_generation_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn, connect(campaign) as writer:
                ensure_memory_tables(conn)
                turn_id = str(
                    conn.execute(
                        "select value from meta where key='current_turn_id'"
                    ).fetchone()["value"]
                )
                marker = "FINAL_SNAPSHOT_MEMORY_MARKER"
                query = "native final snapshot"
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json,
                     source_event_ids_json, source_turn_ids_json, valid_from_turn,
                     valid_to_turn, summary_type, visibility_mode, freshness_status,
                     freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values(?, 'world', null, ?, ?, '[]', '[]', ?, null, null,
                           'deterministic_world', 'player', 'fresh', ?, '', ?, ?, ?)
                    """,
                    (
                        "memory:native-final-snapshot",
                        query,
                        marker,
                        json.dumps([turn_id]),
                        turn_id,
                        json.dumps({"current_turn_id": turn_id}),
                        json.dumps(
                            {
                                "authority": "derived_context",
                                "fact_authority": False,
                                "fact_source": "data/game.sqlite",
                                "summary_overrides_facts": False,
                            }
                        ),
                        "2099-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean', '2099-07-10T00:00:00+00:00', null)
                    """,
                    (turn_id,),
                )
                conn.commit()

                from rpg_engine import context_builder

                original_apply_budget = context_builder.apply_budget
                transitions = [
                    ("dirty", "2099-07-10T00:00:01+00:00"),
                    ("failed", "2099-07-10T00:00:02+00:00"),
                    ("refreshing", "2099-07-10T00:00:03+00:00"),
                ]

                def dirty_after_budget(*args: Any, **kwargs: Any) -> Any:
                    result = original_apply_budget(*args, **kwargs)
                    if transitions:
                        status, updated_at = transitions.pop(0)
                        writer.execute(
                            """
                            update projection_state
                            set status=?, updated_at=?, last_error=?
                            where name='memory'
                            """,
                            (
                                status,
                                updated_at,
                                "repeated transition" if status == "failed" else None,
                            ),
                        )
                        writer.commit()
                    return result

                with mock.patch(
                    "rpg_engine.context_builder.apply_budget",
                    side_effect=dirty_after_budget,
                ):
                    result = build_context(
                        campaign,
                        conn,
                        user_text=query,
                        mode="query",
                        view="player",
                        budget=1800,
                        max_events=0,
                    )

        serialized = json.dumps(result.to_json_text(), ensure_ascii=False)
        self.assertNotIn(marker, serialized)
        self.assertNotIn("memory:native-final-snapshot", serialized)
        self.assertNotIn("plot:memory:memory:native-final-snapshot", serialized)
        self.assertTrue(
            any(
                item.get("source") == "memory_summaries"
                and item.get("freshness", {}).get("reason")
                == "projection_memory_unstable"
                for item in result.omitted_items
            ),
            result.omitted_items,
        )

    def test_context_retry_preserves_non_memory_plot_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn, connect(campaign) as writer:
                turn_id = str(
                    conn.execute(
                        "select value from meta where key='current_turn_id'"
                    ).fetchone()["value"]
                )
                conn.execute(
                    """
                    insert or replace into projection_state
                    (name, version, last_turn_id, status, updated_at, last_error)
                    values('memory', 1, ?, 'clean', '2099-07-10T00:00:00+00:00', null)
                    """,
                    (turn_id,),
                )
                conn.commit()

                from rpg_engine import context_builder

                original_apply_budget = context_builder.apply_budget
                first_pass = True

                def omit_routes_then_retry(*args: Any, **kwargs: Any) -> Any:
                    nonlocal first_pass
                    selected, omitted = original_apply_budget(*args, **kwargs)
                    if first_pass:
                        first_pass = False
                        progress_sections = [
                            item for item in selected if item.key == "progress_context"
                        ]
                        selected = [
                            item for item in selected if item.key != "progress_context"
                        ]
                        omitted = [*omitted, *progress_sections]
                        mark_projections_dirty(writer, ["memory"], turn_id=turn_id)
                        writer.commit()
                    return selected, omitted

                with mock.patch(
                    "rpg_engine.context_builder.apply_budget",
                    side_effect=omit_routes_then_retry,
                ):
                    result = build_context(
                        campaign,
                        conn,
                        user_text="去围墙领地/家",
                        mode="action",
                        submode="travel",
                        view="player",
                        budget=5000,
                        max_events=0,
                    )

        self.assertIn("progress_context", result.sections)
        self.assertTrue(
            any(
                str(item.get("id", "")).startswith("plot:progress:")
                and item.get("budget", {}).get("included") is True
                for item in result.loaded_items
            ),
            result.loaded_items,
        )

    def test_stale_memory_summary_is_omitted_when_subject_fact_is_newer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                conn.execute(
                    """
                    insert or ignore into turns(id, session_id, user_text, intent, summary, changed, created_at)
                    values
                      ('turn:memory-stale-old', 's', 'old', 'note', 'old', 1, '2024-01-01T00:00:00+00:00'),
                      ('turn:memory-stale-new', 's', 'new', 'note', 'new', 1, '2024-01-02T00:00:00+00:00')
                    """
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-memory-stale",
                        "type": "item",
                        "name": "记忆校验物",
                        "status": "active",
                        "visibility": "known",
                        "summary": "NEW AUTHORITATIVE ENTITY SUMMARY",
                        "updated_turn_id": "turn:memory-stale-new",
                    },
                )
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:test-stale-subject",
                        "project",
                        "item:test-memory-stale",
                        "Stale memory",
                        "OLD MEMORY SUMMARY",
                        json.dumps(["OLD MEMORY SUMMARY"], ensure_ascii=False),
                        "[]",
                        json.dumps(["turn:memory-stale-old"], ensure_ascii=False),
                        "turn:memory-stale-old",
                        None,
                        "deterministic_project",
                        "player",
                        "fresh",
                        "turn:memory-stale-old",
                        "",
                        json.dumps(
                            {
                                "current_turn_id": "turn:memory-stale-old",
                                "subject_id": "item:test-memory-stale",
                                "subject_updated_turn_id": "turn:memory-stale-old",
                                "valid_from_turn": "turn:memory-stale-old",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2024-01-01T00:00:00+00:00",
                    ),
                )
                conn.commit()

                result = build_context(
                    campaign,
                    conn,
                    user_text="item:test-memory-stale",
                    mode="query",
                    view="player",
                    budget=1800,
                    max_events=0,
                )

        loaded_memory_ids = {
            item["id"]
            for item in result.loaded_items
            if item.get("source") == "memory_summaries" and item.get("kind") == "memory"
        }
        omitted_memory = [
            item
            for item in result.omitted_items
            if item["id"] == "memory:test-stale-subject" and item.get("source") == "memory_summaries"
        ]
        self.assertNotIn("memory:test-stale-subject", loaded_memory_ids)
        self.assertEqual(omitted_memory[0]["freshness"]["status"], "stale")
        self.assertEqual(omitted_memory[0]["freshness"]["reason"], "subject_updated_after_summary")
        self.assertTrue(
            any(
                item.get("source") == "memory_summaries"
                and item.get("reason") == "subject_updated_after_summary"
                and item.get("severity") == "advisory"
                for item in result.completeness["missing_signal_evidence"]
            )
        )
        self.assertNotIn("OLD MEMORY SUMMARY", result.markdown)
        self.assertIn("NEW AUTHORITATIVE ENTITY SUMMARY", result.markdown)

    def test_player_context_memory_evidence_does_not_leak_hidden_source_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            hidden_id = "item:hidden-memory-source-probe"
            with connect(campaign) as conn:
                ensure_memory_tables(conn)
                upsert_entity(
                    conn,
                    {
                        "id": hidden_id,
                        "type": "item",
                        "name": "Hidden Memory Source Probe",
                        "status": "active",
                        "visibility": "hidden",
                        "summary": "Hidden source should not leak through memory evidence.",
                    },
                )
                conn.execute(
                    """
                    insert or replace into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:native-opaque-hidden-source",
                        "turn:000044",
                        "第28天",
                        "note",
                        "Opaque native source event",
                        f"Opaque source summary references {hidden_id}",
                        json.dumps({"hidden_ref": hidden_id}, ensure_ascii=False),
                        "test",
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:native-hidden-source-evidence",
                        "world",
                        None,
                        "Safe native hidden source memory",
                        "The visible text does not mention the hidden source.",
                        "[]",
                        json.dumps(["event:native-opaque-hidden-source"], ensure_ascii=False),
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "fresh",
                        "turn:000044",
                        "",
                        json.dumps({"source_event_ids": ["event:native-opaque-hidden-source"]}, ensure_ascii=False),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
                     freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
                     derived_authority_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:native-hidden-reason-evidence",
                        "world",
                        None,
                        "Safe native hidden reason memory",
                        "The visible text also does not mention the hidden source.",
                        "[]",
                        "[]",
                        "[]",
                        None,
                        None,
                        "deterministic_world",
                        "player",
                        "stale",
                        "turn:000044",
                        f"stale because of {hidden_id}",
                        json.dumps({"current_turn_id": "turn:000044"}, ensure_ascii=False),
                        json.dumps({"authority": "derived_context", "fact_authority": False}, ensure_ascii=False),
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                conn.commit()

                result = build_context(
                    campaign,
                    conn,
                    user_text="Safe native hidden source memory",
                    mode="query",
                    view="player",
                    budget=1800,
                    max_events=0,
                )

        serialized = result.to_json_text()
        self.assertNotIn(hidden_id, serialized)
        self.assertNotIn("event:native-opaque-hidden-source", serialized)
        self.assertNotIn("memory:native-hidden-source-evidence", {
            item.get("id")
            for item in result.loaded_items
            if item.get("source") == "memory_summaries"
        })

    def test_formal_save_read_only_surfaces_do_not_mutate(self) -> None:
        db_path = SAVE_ROOT / "data" / "game.sqlite"
        before_turn = current_turn(SAVE_ROOT)
        before_events = event_log_text(SAVE_ROOT)
        before_context_runs = query_int(db_path, "select count(*) from context_runs")

        self.assertEqual(run_cli("check", SAVE_ROOT).stdout.strip(), "OK")

        runtime = GMRuntime.from_path(SAVE_ROOT)
        scene = runtime.query("scene")
        crossbow = runtime.query("entity", "终极复合弩")
        social_context = runtime.start_turn("询问夏娃基地状态和物资交换安排", mode="auto")

        self.assertIn("六边形菌丝复合屋", scene.text)
        self.assertIn("item:ultimate-compound-crossbow", crossbow.text)
        self.assertEqual(social_context.mode, "action")
        self.assertEqual(social_context.submode, "social")
        self.assertTrue(social_context.must_save)
        self.assertTrue(social_context.requires_preview)
        self.assertIn("char:eve-mycelium-core", loaded_ids(social_context.context))

        self.assertEqual(current_turn(SAVE_ROOT), before_turn)
        self.assertEqual(event_log_text(SAVE_ROOT), before_events)
        self.assertEqual(query_int(db_path, "select count(*) from context_runs"), before_context_runs)

    def test_context_audit_records_loaded_and_omitted_items_on_temp_save_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            db_path = save / "data" / "game.sqlite"
            before_runs = query_int(db_path, "select count(*) from context_runs")
            before_turn = current_turn(save)

            packet = load_stdout_json(
                run_cli(
                    "context",
                    "build",
                    save,
                    "--user-text",
                    "检查终极复合弩",
                    "--mode",
                    "auto",
                    "--budget",
                    "1200",
                    "--format",
                    "json",
                    "--audit-context",
                    "--context-run-id",
                    "context:current-native-audit",
                )
            )

            self.assertEqual(packet["request"]["context_audit_run_id"], "context:current-native-audit")
            self.assertEqual(current_turn(save), before_turn)
            self.assertEqual(query_int(db_path, "select count(*) from context_runs"), before_runs + 1)
            self.assertEqual(
                query_int(db_path, "select count(*) from context_runs where id='context:current-native-audit'"),
                1,
            )
            self.assertGreater(
                query_int(
                    db_path,
                    "select count(*) from context_items where context_run_id='context:current-native-audit' and included=1",
                ),
                0,
            )
            self.assertGreater(
                query_int(
                    db_path,
                    "select count(*) from context_items where context_run_id='context:current-native-audit' and included=0",
                ),
                0,
            )
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                run = conn.execute(
                    "select output_json from context_runs where id='context:current-native-audit'"
                ).fetchone()
                assert run is not None
                payload = json.loads(run["output_json"])
                self.assertEqual(payload["contract"]["id"], "ContextBuildResult")
                self.assertEqual(payload["contract"]["version"], "1.0")
                self.assertEqual(payload["contract"]["visibility_mode"], "player")
                self.assertEqual(payload["scope"]["mode"], payload["request"]["mode"])
                self.assertEqual(payload["scope"]["submode"], payload["request"]["submode"])
                self.assertEqual(payload["request"]["context_audit_run_id"], "context:current-native-audit")
                self.assertIn("Context Packet", payload["markdown"])
                self.assertIn("missing_signal_evidence", payload["completeness"])
                self.assertTrue(payload["loaded_items"])
                loaded = payload["loaded_items"][0]
                for field in ("source", "provenance", "visibility", "budget", "depth"):
                    self.assertIn(field, loaded)
                omitted = payload["omitted_items"][0]
                for field in ("source", "provenance", "visibility", "budget", "depth"):
                    self.assertIn(field, omitted)
                self.assertTrue(all("depth" in item for item in payload["omitted_items"]))
                active_clocks = conn.execute(
                    """
                    select source, reason
                    from context_items
                    where context_run_id='context:current-native-audit'
                      and item_id='section:active_clocks'
                      and included=1
                    """
                ).fetchone()
                assert active_clocks is not None
                self.assertEqual(active_clocks["source"], "active_clocks")
                self.assertTrue(active_clocks["reason"])
                direct_hit = conn.execute(
                    """
                    select source, reason
                    from context_items
                    where context_run_id='context:current-native-audit'
                      and item_id='item:ultimate-compound-crossbow'
                      and included=1
                    """
                ).fetchone()
                assert direct_hit is not None
                self.assertEqual(direct_hit["source"], "entity_resolution")
                self.assertTrue(direct_hit["reason"])

    def test_context_audit_distinguishes_section_evidence_from_route_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            db_path = save / "data" / "game.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "update routes set id='section:routes' where id='route:home-mycelium-house--home-mycelium-city'"
                )
                conn.commit()

            packet = load_stdout_json(
                run_cli(
                    "context",
                    "build",
                    save,
                    "--user-text",
                    "去地下菌丝城",
                    "--mode",
                    "auto",
                    "--budget",
                    "2600",
                    "--format",
                    "json",
                    "--audit-context",
                    "--context-run-id",
                    "context:route-id-collision",
                )
            )

            self.assertTrue(
                any(item["id"] == "section:routes" and item["kind"] == "section" for item in packet["loaded_items"])
            )
            self.assertTrue(
                any(item["id"] == "section:routes" and item["kind"] == "route" for item in packet["loaded_items"])
            )
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    select item_id, item_kind
                    from context_items
                    where context_run_id='context:route-id-collision'
                      and source='routes'
                      and included=1
                      and item_kind in ('route', 'section')
                    order by item_kind
                    """
                ).fetchall()
            self.assertIn("route", {row["item_kind"] for row in rows})
            self.assertIn("section", {row["item_kind"] for row in rows})
            self.assertIn("section:routes", [row["item_id"] for row in rows if row["item_kind"] == "section"])
            self.assertIn("audit:route:section:routes", [row["item_id"] for row in rows if row["item_kind"] == "route"])
            self.assertEqual(len(rows), len({row["item_id"] for row in rows}))

    def test_current_entity_query_matrix_covers_inventory_people_threats_and_clocks(self) -> None:
        runtime = GMRuntime.from_path(SAVE_ROOT)
        cases = [
            ("终极复合弩", "item:ultimate-compound-crossbow"),
            ("盐", "item:salt"),
            ("竹编鱼笼", "item:fishing-trap"),
            ("夏娃", "char:eve-mycelium-core"),
            ("大型猫科", "threat:t2-large-cat"),
            ("春末干旱", "clock:drought-spring"),
        ]
        for query, expected_id in cases:
            with self.subTest(query=query):
                result = runtime.query("entity", query)
                self.assertIn(expected_id, result.text)

    def test_missing_entity_query_is_helpful_and_read_only(self) -> None:
        runtime = GMRuntime.from_path(SAVE_ROOT)
        before_turn = current_turn(SAVE_ROOT)

        result = runtime.query("entity", "不存在的月亮钥匙")

        self.assertIn("未找到实体", result.text)
        self.assertIn("可尝试", result.text)
        self.assertEqual(current_turn(SAVE_ROOT), before_turn)

    def test_query_context_for_direct_entity_keeps_direct_hit_under_low_budget(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        with connect(campaign) as conn:
            packet = build_context(campaign, conn, user_text="终极复合弩", mode="auto", budget=900)

        self.assertEqual(packet.request["mode"], "query")
        self.assertEqual(packet.request["submode"], "entity")
        self.assertIn("item:ultimate-compound-crossbow", loaded_ids(packet))
        self.assertIn("relevant_entities", packet.sections)
        self.assertNotIn("palette_candidates", packet.sections)

    def test_budget_omitted_collector_items_are_not_marked_loaded(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        with connect(campaign) as conn:
            packet = build_context(campaign, conn, user_text="去地下菌丝城", mode="auto", budget=500)

        self.assertNotIn("routes", packet.sections)
        self.assertFalse(
            any(item.get("source") == "routes" and item.get("kind") == "route" for item in packet.loaded_items),
            packet.loaded_items,
        )
        omitted_routes = [
            item for item in packet.omitted_items if item.get("source") == "routes" and item.get("kind") == "route"
        ]
        self.assertTrue(omitted_routes, packet.omitted_items)
        self.assertTrue(all(item["budget"]["included"] is False for item in omitted_routes))
        self.assertTrue(all(item["budget"]["reason"] == "source section omitted by token budget" for item in omitted_routes))

    def test_repeat_context_builds_are_stable_for_current_key_query(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        fingerprints: set[tuple[Any, ...]] = set()
        with connect(campaign) as conn:
            for _ in range(3):
                packet = build_context(campaign, conn, user_text="终极复合弩", mode="auto", budget=1800)
                fingerprints.add(
                    (
                        packet.request["mode"],
                        packet.request["submode"],
                        tuple(item.get("id") for item in packet.loaded_items[:12]),
                        tuple(packet.sections.keys()),
                    )
                )

        self.assertEqual(len(fingerprints), 1)

    def test_start_turn_routing_matrix_for_current_story_language(self) -> None:
        runtime = GMRuntime.from_path(SAVE_ROOT)
        cases = [
            ("查看当前场景", "query", "scene", False),
            ("检查终极复合弩", "action", "explore", True),
            ("去地下菌丝城", "action", "travel", True),
            ("询问夏娃基地状态和物资交换安排", "action", "social", True),
            ("在六边形菌丝复合屋休息到清晨", "action", "rest", True),
            ("盘点盐和调料库存", "action", "routine", True),
        ]
        for text, mode, submode, must_save in cases:
            with self.subTest(text=text):
                result = runtime.start_turn(text, mode="auto")
                self.assertEqual(result.mode, mode)
                self.assertEqual(result.submode, submode)
                self.assertEqual(result.must_save, must_save)
                self.assertEqual(result.requires_preview, must_save)
                self.assertTrue(result.can_proceed)

    def test_context_recall_matrix_loads_story_critical_ids_under_budget(self) -> None:
        campaign = load_campaign(SAVE_ROOT)
        cases = [
            (
                "检查终极复合弩",
                "action",
                "explore",
                {"item:ultimate-compound-crossbow", "item:stun-thorn-bolts"},
            ),
            (
                "去地下菌丝城",
                "action",
                "travel",
                {"loc:home-mycelium-city", "route:home-mycelium-house--home-mycelium-city"},
            ),
            (
                "询问夏娃基地状态和物资交换安排",
                "action",
                "social",
                {"char:eve-mycelium-core", "world:economy-trade"},
            ),
            (
                "天气会影响农田浇水吗",
                "action",
                "routine",
                {"project:water-crops", "world:weather", "clock:drought-spring"},
            ),
        ]
        with connect(campaign) as conn:
            for text, mode, submode, expected_ids in cases:
                with self.subTest(text=text):
                    packet = build_context(campaign, conn, user_text=text, mode="auto", budget=2600)
                    self.assertEqual(packet.request["mode"], mode)
                    self.assertEqual(packet.request["submode"], submode)
                    self.assertTrue(packet.completeness["allow_proceed"])
                    self.assertLessEqual(packet.budget["limit"], 2600)
                    self.assertTrue(expected_ids.issubset(loaded_ids(packet)), loaded_ids(packet))

    def test_relationship_progress_and_plot_signals_include_auditable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                player_id = conn.execute("select value from meta where key='player_entity_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": "char:test-context-ally",
                        "type": "character",
                        "name": "证据伙伴",
                        "summary": "可见伙伴，用于 relationship context regression。",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "char:test-context-secret",
                        "type": "character",
                        "name": "隐秘关系对象SECRET_REL_CONTEXT",
                        "visibility": "hidden",
                        "summary": "SECRET_REL_CONTEXT hidden endpoint",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:test-context-ally",
                        "type": "relationship",
                        "name": "主角与证据伙伴",
                        "summary": "证据伙伴信任谨慎证明。",
                        "details": {
                            "source_id": player_id,
                            "target_id": "char:test-context-ally",
                            "kind": "social",
                            "state": "cautious ally",
                            "attitude": "guarded",
                            "trust": 2,
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:test-context-hidden-endpoint",
                        "type": "relationship",
                        "name": "隐藏端点关系SECRET_REL_CONTEXT",
                        "summary": "hidden endpoint relationship SECRET_REL_CONTEXT",
                        "details": {
                            "source_id": player_id,
                            "target_id": "char:test-context-secret",
                            "kind": "secret",
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:test-context-missing-endpoint",
                        "type": "relationship",
                        "name": "缺失端点关系",
                        "summary": "missing endpoint relationship",
                        "details": {
                            "source_id": player_id,
                            "target_id": "char:test-context-missing",
                            "kind": "broken",
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:test-context-archived",
                        "type": "relationship",
                        "name": "归档证据关系",
                        "status": "archived",
                        "summary": "archived relationship",
                        "details": {
                            "source_id": player_id,
                            "target_id": "char:test-context-ally",
                            "kind": "archived",
                        },
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-context-goal",
                        "name": "证据计划",
                        "summary": "证据计划正在推进。",
                        "clock_type": "project",
                        "segments_total": 6,
                        "segments_filled": 2,
                        "visibility": "visible",
                        "trigger_when_full": "证据计划成为稳定方案。",
                        "tick_rules": {"scope": ["char:test-context-ally"], "tick_when": ["完成共同验证"]},
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-context-hidden",
                        "name": "隐秘进度SECRET_PROGRESS_CONTEXT",
                        "summary": "SECRET_PROGRESS_CONTEXT hidden progress",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "hidden consequence",
                        "tick_rules": {"scope": ["char:test-context-ally"]},
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-context-complete",
                        "name": "已完成证据计划",
                        "summary": "这个计划已经完成，不应作为 active progress loaded。",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 4,
                        "visibility": "visible",
                        "trigger_when_full": "已完成。",
                        "tick_rules": {"scope": ["char:test-context-ally"]},
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-context-missing-ref",
                        "name": "缺失引用证据计划",
                        "summary": "这个计划引用缺失实体，不应作为 progress loaded。",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "引用缺失实体。",
                        "tick_rules": {"scope": ["char:test-context-missing"]},
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-context-archived",
                        "name": "归档证据计划",
                        "summary": "这个计划已经归档，不应作为 active progress loaded。",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "归档计划完成。",
                        "tick_rules": {"scope": ["char:test-context-ally"]},
                    },
                )
                conn.execute("update entities set status = 'archived' where id = 'clock:test-context-archived'")
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-context-event-only",
                        "name": "隐秘事件提到的可见计划",
                        "summary": "只有隐秘事件引用的可见计划。",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "事件计划完成。",
                        "tick_rules": {},
                    },
                )
                conn.execute(
                    """
                    insert into events(id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:test-hidden-progress-boost",
                        "turn:seed",
                        "test",
                        "gm_note",
                        "hidden progress boost",
                        "hidden event mentions clock:test-context-event-only and char:test-context-secret",
                        json.dumps({"clock": "clock:test-context-event-only", "secret": "char:test-context-secret"}),
                        "test",
                        "2026-07-10T00:00:00+00:00",
                    ),
                )
                conn.commit()

                event_state = SimpleNamespace(conn=conn)
                self.assertNotIn(
                    "clock:test-context-event-only",
                    recent_activity_progress_ids(event_state, view="player"),
                )
                self.assertIn(
                    "clock:test-context-event-only",
                    recent_activity_progress_ids(event_state, view="maintenance"),
                )

                packet = build_context(
                    campaign,
                    conn,
                    user_text="询问证据伙伴并推进证据计划",
                    mode="auto",
                    budget=4200,
                    audit_context=True,
                    audit_context_run_id="context:relationship-progress-plot",
                )

                loaded_sources = {(item["source"], item["kind"], item["id"]) for item in packet.loaded_items}
                self.assertIn(("relationships", "relationship", "rel:test-context-ally"), loaded_sources)
                self.assertIn(("progress_context", "progress", "clock:test-context-goal"), loaded_sources)
                self.assertTrue(
                    any(item["source"] == "plot_signals" and item["kind"] == "plot_signal" for item in packet.loaded_items),
                    packet.loaded_items,
                )
                self.assertIn("relationships", packet.sections)
                self.assertIn("progress_context", packet.sections)
                self.assertIn("plot_signals", packet.sections)
                plot_item = next(
                    item
                    for item in packet.loaded_items
                    if item["source"] == "plot_signals" and item["kind"] == "plot_signal"
                )
                self.assertTrue(plot_item["provenance"]["advisory_only"])
                self.assertFalse(plot_item["provenance"]["requires_storylet"])
                serialized = packet.to_json_text()
                self.assertNotIn("SECRET_REL_CONTEXT", serialized)
                self.assertNotIn("SECRET_PROGRESS_CONTEXT", serialized)
                self.assertFalse(
                    any(str(item.get("id", "")).startswith("relationships:unavailable") for item in packet.omitted_items),
                    packet.omitted_items,
                )
                self.assertFalse(
                    any(str(item.get("id", "")).startswith("progress:unavailable") for item in packet.omitted_items),
                    packet.omitted_items,
                )
                self.assertNotIn(("progress_context", "progress", "clock:test-context-complete"), loaded_sources)
                self.assertNotIn("clock:test-context-complete", packet.sections.get("active_clocks", ""))
                self.assertNotIn("clock:test-context-missing-ref", packet.sections.get("active_clocks", ""))
                self.assertNotIn("clock:test-context-archived", packet.sections.get("active_clocks", ""))

                audit_rows = conn.execute(
                    """
                    select item_id, item_kind, source, included
                    from context_items
                    where context_run_id='context:relationship-progress-plot'
                    """
                ).fetchall()
                audit_keys = {(row["source"], row["item_kind"], row["item_id"], row["included"]) for row in audit_rows}
                self.assertIn(("relationships", "relationship", "rel:test-context-ally", 1), audit_keys)
                self.assertIn(("progress_context", "progress", "clock:test-context-goal", 1), audit_keys)
                self.assertTrue(any(key[0] == "plot_signals" and key[1] == "plot_signal" and key[3] == 1 for key in audit_keys))

                missing_ref_player_packet = build_context(
                    campaign,
                    conn,
                    user_text="检查 clock:test-context-missing-ref",
                    mode="query",
                    submode="context",
                    budget=4200,
                )
                self.assertFalse(
                    any(
                        item.get("source") == "progress_context"
                        and item.get("id") == "clock:test-context-missing-ref"
                        for item in missing_ref_player_packet.loaded_items
                    ),
                    missing_ref_player_packet.loaded_items,
                )
                self.assertFalse(
                    any(
                        item.get("source") == "progress_context"
                        and item.get("id") == "clock:test-context-missing-ref"
                        for item in missing_ref_player_packet.omitted_items
                    ),
                    missing_ref_player_packet.omitted_items,
                )

                maintenance_packet = build_context(
                    campaign,
                    conn,
                    user_text=(
                        "系统维护：检查证据伙伴关系 rel:test-context-archived "
                        "clock:test-context-complete clock:test-context-missing-ref clock:test-context-archived"
                    ),
                    mode="maintenance",
                    view="maintenance",
                    budget=4200,
                )
                maintenance_omissions = {
                    (item.get("source"), item.get("id")): item
                    for item in maintenance_packet.omitted_items
                    if item.get("source") in {"relationships", "progress_context"}
                }
                self.assertEqual(
                    maintenance_omissions[("relationships", "rel:test-context-missing-endpoint")]["reason_code"],
                    "missing_reference",
                )
                self.assertEqual(
                    maintenance_omissions[("relationships", "rel:test-context-archived")]["reason_code"],
                    "archived",
                )
                self.assertEqual(
                    maintenance_omissions[("progress_context", "clock:test-context-complete")]["reason_code"],
                    "conflict",
                )
                self.assertEqual(
                    maintenance_omissions[("progress_context", "clock:test-context-missing-ref")]["reason_code"],
                    "missing_reference",
                )
                self.assertEqual(
                    maintenance_omissions[("progress_context", "clock:test-context-archived")]["reason_code"],
                    "archived",
                )
                maintenance_keys = [
                    (item.get("source"), item.get("id"), item.get("reason_code"))
                    for item in maintenance_packet.omitted_items
                    if item.get("source") in {"relationships", "progress_context"}
                ]
                self.assertEqual(len(maintenance_keys), len(set(maintenance_keys)), maintenance_packet.omitted_items)

    def test_relationship_and_progress_items_move_to_omitted_when_sections_exceed_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                player_id = conn.execute("select value from meta where key='player_entity_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": "char:test-budget-ally",
                        "type": "character",
                        "name": "预算伙伴",
                        "summary": "可见伙伴，用于 budget omission regression。",
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "rel:test-budget-ally",
                        "type": "relationship",
                        "name": "主角与预算伙伴",
                        "summary": "预算伙伴关系。",
                        "details": {"source_id": player_id, "target_id": "char:test-budget-ally", "kind": "social"},
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-budget-goal",
                        "name": "预算计划",
                        "summary": "预算计划进度。",
                        "clock_type": "project",
                        "segments_total": 6,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "预算计划完成。",
                        "tick_rules": {"scope": ["char:test-budget-ally"]},
                    },
                )
                conn.commit()

                packet = build_context(campaign, conn, user_text="询问预算伙伴和预算计划", mode="auto", budget=500)

                self.assertNotIn("relationships", packet.sections)
                self.assertNotIn("progress_context", packet.sections)
                self.assertFalse(
                    any(item.get("source") == "relationships" and item.get("kind") == "relationship" for item in packet.loaded_items),
                    packet.loaded_items,
                )
                self.assertFalse(
                    any(item.get("source") == "progress_context" and item.get("kind") == "progress" for item in packet.loaded_items),
                    packet.loaded_items,
                )
                relationship_omissions = [
                    item
                    for item in packet.omitted_items
                    if item.get("source") == "relationships" and item.get("kind") == "relationship"
                ]
                progress_omissions = [
                    item
                    for item in packet.omitted_items
                    if item.get("source") == "progress_context" and item.get("kind") == "progress"
                ]
                self.assertTrue(relationship_omissions, packet.omitted_items)
                self.assertTrue(progress_omissions, packet.omitted_items)
                target_relationship = next(item for item in relationship_omissions if item["id"] == "rel:test-budget-ally")
                target_progress = next(item for item in progress_omissions if item["id"] == "clock:test-budget-goal")
                self.assertEqual(target_relationship["budget"]["reason"], "source section omitted by token budget")
                self.assertEqual(target_progress["budget"]["reason"], "source section omitted by token budget")
                self.assertFalse(
                    any(
                        item.get("source") == "plot_signals"
                        and item.get("kind") == "plot_signal"
                        and "clock:test-budget-goal" in item.get("source_refs", [])
                        for item in packet.loaded_items
                    ),
                    packet.loaded_items,
                )
                self.assertTrue(
                    any(
                        item.get("source") == "plot_signals"
                        and item.get("kind") == "plot_signal"
                        and "clock:test-budget-goal" in item.get("source_refs", [])
                        and item["budget"]["reason"] == "source section omitted by token budget"
                        for item in packet.omitted_items
                    ),
                    packet.omitted_items,
                )

    def test_plot_signal_omission_does_not_render_campaign_hint_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            campaign.config["plot_hints"] = [
                {
                    "id": f"visible-hint-{index}",
                    "name": f"Visible hint {index}",
                    "text": f"VISIBLE_HINT_BODY_{index} 证据伙伴 optional continuity detail",
                    "visibility": "known",
                }
                for index in range(12)
            ]
            with connect(campaign) as conn:
                packet = build_context(
                    campaign,
                    conn,
                    user_text="询问证据伙伴 optional continuity detail",
                    mode="auto",
                    budget=4200,
                )

            omitted_plot_signals = [
                item
                for item in packet.omitted_items
                if item.get("source") == "plot_signals" and item.get("kind") == "plot_signal"
            ]
            self.assertTrue(omitted_plot_signals, packet.omitted_items)
            serialized = json.dumps(omitted_plot_signals, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("VISIBLE_HINT_BODY_", serialized)
            self.assertNotIn("VISIBLE_HINT_BODY_", packet.markdown)

            with connect(campaign) as conn:
                low_budget_packet = build_context(
                    campaign,
                    conn,
                    user_text="询问证据伙伴 optional continuity detail",
                    mode="auto",
                    budget=500,
                )
            low_budget_omitted_plot_signals = [
                item
                for item in low_budget_packet.omitted_items
                if item.get("source") == "plot_signals" and item.get("kind") == "plot_signal"
            ]
            self.assertTrue(low_budget_omitted_plot_signals, low_budget_packet.omitted_items)
            low_budget_serialized = json.dumps(low_budget_omitted_plot_signals, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("VISIBLE_HINT_BODY_", low_budget_serialized)
            self.assertNotIn("VISIBLE_HINT_BODY_", low_budget_packet.markdown)


if __name__ == "__main__":
    import unittest

    unittest.main()
