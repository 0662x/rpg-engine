from __future__ import annotations

import json
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from rpg_engine.ai.provider import AIHelperResult
from rpg_engine.ai_intent import build_internal_intent_review_prompt
from rpg_engine.campaign import load_campaign
from rpg_engine.context.collectors import collect_related_history
from rpg_engine.context.semantic import build_semantic_prompt
from rpg_engine.context_builder import build_context
from rpg_engine.db import connect, upsert_entity
from rpg_engine.memory import find_relevant_memories
from rpg_engine.projection_service import ProjectionService
from rpg_engine.runtime import GMRuntime

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
)


HIDDEN_PROBE_TOKEN = "BMAD-HIDDEN-CONTEXT-3-2"


def install_hidden_context_probe(conn: sqlite3.Connection) -> None:
    current_location = conn.execute("select value from meta where key='current_location_id'").fetchone()[0]
    current_turn = conn.execute("select value from meta where key='current_turn_id'").fetchone()[0]
    player_id = conn.execute("select value from meta where key='player_entity_id'").fetchone()[0]
    now = "9999-07-09T00:00:00+00:00"
    upsert_entity(
        conn,
        {
            "id": "item:test-hidden-context-probe",
            "type": "item",
            "name": f"隐秘星钥{HIDDEN_PROBE_TOKEN}",
            "visibility": "hidden",
            "status": "active",
            "location_id": current_location,
            "summary": f"隐藏道具摘要 {HIDDEN_PROBE_TOKEN}",
            "aliases": [HIDDEN_PROBE_TOKEN],
            "details": {"secret": f"隐藏道具细节 {HIDDEN_PROBE_TOKEN}"},
        },
    )
    upsert_entity(
        conn,
        {
            "id": "rel:test-hidden-context-probe",
            "type": "relationship",
            "name": f"隐秘关系{HIDDEN_PROBE_TOKEN}",
            "visibility": "hidden",
            "status": "active",
            "summary": f"隐藏关系摘要 {HIDDEN_PROBE_TOKEN}",
            "details": {
                "source_id": player_id,
                "target_id": "item:test-hidden-context-probe",
                "kind": "secret-link",
                "state": "hidden",
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": "world:test-hidden-context-probe",
            "type": "world_setting",
            "name": f"隐秘天幕{HIDDEN_PROBE_TOKEN}",
            "visibility": "hidden",
            "status": "active",
            "summary": f"隐藏世界设定摘要 {HIDDEN_PROBE_TOKEN}",
            "details": {},
        },
    )
    conn.execute(
        """
        insert or replace into world_settings
        (entity_id, category, scope, visibility, priority, summary, content_json,
         linked_rules_json, linked_clocks_json, linked_entities_json, applies_when_json, source)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "world:test-hidden-context-probe",
            "ecology",
            "world",
            "hidden",
            100,
            f"隐藏世界设定摘要 {HIDDEN_PROBE_TOKEN}",
            json.dumps({"truth": f"隐藏世界设定内容 {HIDDEN_PROBE_TOKEN}"}, ensure_ascii=False),
            "[]",
            "[]",
            json.dumps(["item:test-hidden-context-probe"], ensure_ascii=False),
            json.dumps({"keywords": [HIDDEN_PROBE_TOKEN], "submodes": ["context"]}, ensure_ascii=False),
            "test",
        ),
    )
    conn.execute(
        """
        insert or replace into discovery_states
        (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
         confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
         notes, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "disc:test-hidden-context-probe",
            "item:test-hidden-context-probe",
            None,
            "clue",
            "clue",
            "hidden",
            1,
            "[]",
            "[]",
            current_turn,
            current_turn,
            f"隐藏线索备注 {HIDDEN_PROBE_TOKEN}",
            now,
            now,
        ),
    )
    conn.execute(
        """
        insert or replace into discovery_states
        (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
         confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
         notes, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "disc:test-hidden-subject-context-probe",
            "item:test-hidden-context-probe",
            None,
            "clue",
            "clue",
            "hinted",
            1,
            "[]",
            "[]",
            current_turn,
            current_turn,
            "hinted discovery points at hidden subject",
            now,
            now,
        ),
    )
    conn.execute(
        """
        insert or replace into memory_summaries
        (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
         source_turn_ids_json, valid_from_turn, valid_to_turn, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "memory:test-hidden-context-probe",
            "world",
            None,
            f"隐藏记忆{HIDDEN_PROBE_TOKEN}",
            f"隐藏记忆摘要 {HIDDEN_PROBE_TOKEN}",
            json.dumps([f"隐藏记忆要点 {HIDDEN_PROBE_TOKEN}"], ensure_ascii=False),
            "[]",
            "[]",
            current_turn,
            None,
            now,
        ),
    )
    conn.execute(
        """
        insert or replace into events
        (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "event:test-hidden-context-probe",
            current_turn,
            "第1天",
            "hidden_probe",
            f"隐秘星钥{HIDDEN_PROBE_TOKEN} 隐藏事件",
            f"隐秘星钥{HIDDEN_PROBE_TOKEN} 隐藏事件摘要",
            json.dumps({"secret": HIDDEN_PROBE_TOKEN}, ensure_ascii=False),
            "test",
            now,
        ),
    )
    conn.commit()


@CURRENT_NATIVE_REQUIRED
class CurrentNativeVisibilityTests(FormalCurrentSaveReadOnlyTestCase):
    def test_hidden_entity_probe_is_not_visible_to_player_but_is_visible_to_gm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-hidden-leak",
                        "type": "item",
                        "name": "泄漏诱饵SECRET",
                        "visibility": "hidden",
                        "status": "active",
                        "location_id": "loc:home-mycelium-house",
                        "summary": "绝密摘要不要给玩家",
                        "aliases": ["泄漏诱饵SECRET"],
                        "details": {"secret": "紫色密钥"},
                    },
                )
                conn.commit()
                report = ProjectionService(campaign, conn).refresh(names=["search"], dirty_only=False, profile="test:hidden_probe")
                conn.commit()
                self.assertTrue(report.ok, report.errors)

            runtime = GMRuntime.from_path(save)
            player = runtime.query("entity", "泄漏诱饵SECRET", view="player")
            gm = runtime.query("entity", "泄漏诱饵SECRET", view="gm")

            self.assertIn("未找到实体", player.text)
            self.assertNotIn("绝密摘要不要给玩家", player.text)
            self.assertNotIn("紫色密钥", player.text)
            self.assertIn("item:test-hidden-leak", gm.text)
            self.assertIn("绝密摘要不要给玩家", gm.text)
            self.assertIn("紫色密钥", gm.text)

    def test_player_safe_context_excludes_hidden_probe_while_gm_context_can_read_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                install_hidden_context_probe(conn)

                gm_context = build_context(
                    campaign,
                    conn,
                    user_text=f"线索 隐秘天幕{HIDDEN_PROBE_TOKEN} {HIDDEN_PROBE_TOKEN}",
                    mode="query",
                    submode="context",
                    view="gm",
                    audit_context=True,
                    audit_context_run_id="context:hidden-probe-reuse-gm",
                )
                player_after_gm_context = build_context(
                    campaign,
                    conn,
                    user_text=f"线索 隐秘天幕{HIDDEN_PROBE_TOKEN} {HIDDEN_PROBE_TOKEN}",
                    mode="query",
                    submode="context",
                    view="player",
                    audit_context=True,
                    audit_context_run_id="context:hidden-probe-reuse-gm",
                )
                maintenance_context = build_context(
                    campaign,
                    conn,
                    user_text=f"线索 隐秘天幕{HIDDEN_PROBE_TOKEN} {HIDDEN_PROBE_TOKEN}",
                    mode="query",
                    submode="context",
                    view="maintenance",
                    audit_context=True,
                    audit_context_run_id="context:hidden-probe-reuse-maintenance",
                )
                player_context = build_context(
                    campaign,
                    conn,
                    user_text=f"线索 隐秘天幕{HIDDEN_PROBE_TOKEN} {HIDDEN_PROBE_TOKEN}",
                    mode="query",
                    submode="context",
                    view="player",
                    audit_context=True,
                    audit_context_run_id="context:hidden-probe-reuse-maintenance",
                )
                conn.commit()

                gm_json = gm_context.to_json_text()
                maintenance_json = maintenance_context.to_json_text()
                player_after_gm_json = player_after_gm_context.to_json_text()
                player_json = player_context.to_json_text()
                player_loaded_ids = {str(item.get("id")) for item in player_context.loaded_items}
                gm_loaded_ids = {str(item.get("id")) for item in gm_context.loaded_items}
                maintenance_loaded_ids = {str(item.get("id")) for item in maintenance_context.loaded_items}
                audit_payload_after_gm = json.loads(
                    conn.execute(
                        "select output_json from context_runs where id='context:hidden-probe-reuse-gm'"
                    ).fetchone()["output_json"]
                )
                audit_payload_after_maintenance = json.loads(
                    conn.execute(
                        "select output_json from context_runs where id='context:hidden-probe-reuse-maintenance'"
                    ).fetchone()["output_json"]
                )

            self.assertEqual(gm_context.contract["visibility_mode"], "gm")
            self.assertIn(HIDDEN_PROBE_TOKEN, gm_json)
            self.assertIn("event:test-hidden-context-probe", gm_loaded_ids)
            self.assertIn("memory:test-hidden-context-probe", gm_loaded_ids)
            self.assertIn("disc:test-hidden-context-probe", gm_loaded_ids)
            self.assertIn("disc:test-hidden-subject-context-probe", gm_loaded_ids)
            self.assertIn("world:test-hidden-context-probe", gm_json)
            self.assertEqual(maintenance_context.contract["visibility_mode"], "maintenance")
            self.assertIn(HIDDEN_PROBE_TOKEN, maintenance_json)
            self.assertIn("disc:test-hidden-subject-context-probe", maintenance_loaded_ids)

            self.assertEqual(player_after_gm_context.contract["visibility_mode"], "player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_after_gm_json)
            self.assertEqual(player_context.contract["visibility_mode"], "player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_json)
            self.assertNotIn("event:test-hidden-context-probe", player_loaded_ids)
            self.assertNotIn("memory:test-hidden-context-probe", player_loaded_ids)
            self.assertNotIn("disc:test-hidden-context-probe", player_json)
            self.assertNotIn("disc:test-hidden-subject-context-probe", player_json)
            self.assertNotIn("world:test-hidden-context-probe", player_json)
            self.assertEqual(audit_payload_after_gm["contract"]["visibility_mode"], "player")
            self.assertEqual(audit_payload_after_maintenance["contract"]["visibility_mode"], "player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, json.dumps(audit_payload_after_gm, ensure_ascii=False))
            self.assertNotIn(HIDDEN_PROBE_TOKEN, json.dumps(audit_payload_after_maintenance, ensure_ascii=False))
            invariants = {
                item["source"]: item
                for item in player_context.contract.get("visibility_invariants", [])
                if isinstance(item, dict)
            }
            self.assertEqual(invariants["events"]["structured_visibility"], "not_applicable")
            self.assertEqual(invariants["memory_summaries"]["structured_visibility"], "not_applicable")

    def test_player_safe_query_and_scene_output_do_not_expose_hidden_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                install_hidden_context_probe(conn)

            runtime = GMRuntime.from_path(save)
            player_scene = runtime.query("scene", view="player")
            player_entity = runtime.query("entity", HIDDEN_PROBE_TOKEN, view="player")
            player_context = runtime.query("context", f"线索 {HIDDEN_PROBE_TOKEN}", view="player")
            gm_scene = runtime.query("scene", view="gm")
            gm_entity = runtime.query("entity", HIDDEN_PROBE_TOKEN, view="gm")
            gm_context = runtime.query("context", f"线索 {HIDDEN_PROBE_TOKEN}", view="gm")

            player_blob = "\n".join(
                [
                    player_scene.text,
                    player_entity.text,
                    player_context.text,
                    json.dumps(player_context.to_dict(), ensure_ascii=False),
                ]
            )
            gm_blob = "\n".join(
                [
                    gm_scene.text,
                    gm_entity.text,
                    gm_context.text,
                    json.dumps(gm_context.to_dict(), ensure_ascii=False),
                ]
            )

            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_blob)
            self.assertNotIn("item:test-hidden-context-probe", player_blob)
            self.assertNotIn("event:test-hidden-context-probe", player_blob)
            self.assertIn(HIDDEN_PROBE_TOKEN, gm_blob)
            self.assertIn("item:test-hidden-context-probe", gm_blob)

    def test_player_safe_semantic_prompt_hides_hidden_current_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                upsert_entity(
                    conn,
                    {
                        "id": "loc:test-hidden-current-location",
                        "type": "location",
                        "name": f"隐秘当前位置{HIDDEN_PROBE_TOKEN}",
                        "visibility": "hidden",
                        "status": "active",
                        "summary": f"隐藏地点摘要 {HIDDEN_PROBE_TOKEN}",
                        "aliases": [HIDDEN_PROBE_TOKEN],
                        "details": {},
                    },
                )
                conn.execute(
                    "insert into locations(entity_id, description_short) values(?, ?) "
                    "on conflict(entity_id) do update set description_short=excluded.description_short",
                    ("loc:test-hidden-current-location", f"隐藏地点描述 {HIDDEN_PROBE_TOKEN}"),
                )
                conn.execute(
                    "update meta set value='loc:test-hidden-current-location' where key='current_location_id'"
                )
                conn.commit()
                prompt = build_semantic_prompt(
                    SimpleNamespace(
                        conn=conn,
                        user_text=f"查看 {HIDDEN_PROBE_TOKEN} event:loc:test-hidden-current-location-prefixed 周围",
                        mode="query",
                        submode="scene",
                        entity_hits=[],
                        visibility_view="player",
                    )
                )
                intent_prompt = build_internal_intent_review_prompt(
                    conn,
                    f"查看 {HIDDEN_PROBE_TOKEN} event:loc:test-hidden-current-location-prefixed 周围",
                    view="player",
                )
                player_context = build_context(
                    campaign,
                    conn,
                    user_text="线索 event:loc:test-hidden-current-location-prefixed",
                    mode="query",
                    submode="context",
                    view="player",
                )

            self.assertNotIn("loc:test-hidden-current-location", prompt)
            self.assertNotIn(HIDDEN_PROBE_TOKEN, prompt)
            self.assertNotIn("loc:test-hidden-current-location", intent_prompt)
            self.assertNotIn(HIDDEN_PROBE_TOKEN, intent_prompt)
            self.assertNotIn("loc:test-hidden-current-location", player_context.to_json_text())

    def test_player_safe_memory_and_history_recall_overfetch_past_hidden_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                install_hidden_context_probe(conn)
                current_turn = conn.execute("select value from meta where key='current_turn_id'").fetchone()[0]
                target = "safe-starvation-target-3-2"
                safe_memory_marker = "SAFE-MEMORY-RECALL-3-2"
                safe_event_marker = "SAFE-EVENT-RECALL-3-2"
                for index in range(30):
                    conn.execute(
                        """
                        insert or replace into memory_summaries
                        (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                         source_turn_ids_json, valid_from_turn, valid_to_turn, updated_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"memory:test-hidden-starvation-{index}",
                            "world",
                            None,
                            f"{target} hidden memory {HIDDEN_PROBE_TOKEN} {index}",
                            f"{target} hidden memory summary {HIDDEN_PROBE_TOKEN}",
                            json.dumps([HIDDEN_PROBE_TOKEN], ensure_ascii=False),
                            "[]",
                            "[]",
                            current_turn,
                            None,
                            f"9999-07-09T00:00:{index:02d}+00:00",
                        ),
                    )
                    conn.execute(
                        """
                        insert or replace into events
                        (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"event:test-hidden-starvation-{index}",
                            current_turn,
                            "第1天",
                            "test",
                            f"{target} hidden event {HIDDEN_PROBE_TOKEN} {index}",
                            f"{target} hidden event summary {HIDDEN_PROBE_TOKEN}",
                            json.dumps({"target": target, "secret": HIDDEN_PROBE_TOKEN}, ensure_ascii=False),
                            "test",
                            f"9999-07-09T00:00:{index:02d}+00:00",
                        ),
                    )
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:item:test-hidden-context-probe-prefixed",
                        "world",
                        None,
                        f"{target} id-embedded memory",
                        f"{target} id-embedded memory summary",
                        json.dumps([target], ensure_ascii=False),
                        "[]",
                        "[]",
                        current_turn,
                        None,
                        "9999-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:test-hidden-text-prefixed",
                        "world",
                        None,
                        f"{target} text-embedded memory",
                        f"{target} event:item:test-hidden-context-probe-prefixed",
                        json.dumps(["memory:item:test-hidden-context-probe-prefixed"], ensure_ascii=False),
                        "[]",
                        "[]",
                        current_turn,
                        None,
                        "9999-07-10T00:00:01+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:item:test-hidden-context-probe-prefixed",
                        current_turn,
                        "第1天",
                        "test",
                        f"{target} id-embedded event",
                        f"{target} id-embedded event summary",
                        json.dumps({"target": target}, ensure_ascii=False),
                        "test",
                        "9999-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:test-hidden-text-prefixed",
                        current_turn,
                        "第1天",
                        "test",
                        f"{target} event:item:test-hidden-context-probe-prefixed",
                        f"{target} text-embedded event summary",
                        json.dumps({"target": target}, ensure_ascii=False),
                        "test",
                        "9999-07-10T00:00:01+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into memory_summaries
                    (id, kind, subject_id, title, summary, key_points_json, source_event_ids_json,
                     source_turn_ids_json, valid_from_turn, valid_to_turn, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "memory:test-safe-starvation",
                        "world",
                        None,
                        f"{target} safe memory",
                        safe_memory_marker,
                        json.dumps([safe_memory_marker], ensure_ascii=False),
                        "[]",
                        "[]",
                        current_turn,
                        None,
                        "9999-07-08T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:test-safe-starvation",
                        current_turn,
                        "第1天",
                        "test",
                        f"{target} safe event",
                        safe_event_marker,
                        json.dumps({"target": target, "safe": safe_event_marker}, ensure_ascii=False),
                        "test",
                        "9999-07-08T00:00:00+00:00",
                    ),
                )
                conn.commit()

                memories = find_relevant_memories(conn, targets=[target], limit=1, view="player")
                state = SimpleNamespace(
                    conn=conn,
                    max_events=1,
                    entity_hits=[
                        SimpleNamespace(
                            id=target,
                            type="item",
                            name=target,
                            reason="id",
                            depth=0,
                        )
                    ],
                    routes=[],
                    mode="query",
                    visibility_view="player",
                    related_events=[],
                    general_events=[],
                )
                collect_related_history(state)

            self.assertEqual([row["id"] for row in memories], ["memory:test-safe-starvation"])
            self.assertEqual(state.related_events[0]["id"], "event:test-safe-starvation")

    def test_player_safe_discovery_recall_overfetches_past_hidden_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                install_hidden_context_probe(conn)
                current_turn = conn.execute("select value from meta where key='current_turn_id'").fetchone()[0]
                target = "安全线索饥饿"
                safe_marker = "SAFE-DISCOVERY-RECALL-3-2"
                for index in range(30):
                    conn.execute(
                        """
                        insert or replace into discovery_states
                        (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
                         confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
                         notes, created_at, updated_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"disc:test-hidden-starvation-{index}",
                            "item:test-hidden-context-probe",
                            None,
                            "clue",
                            "clue",
                            "hinted",
                            10,
                            "[]",
                            "[]",
                            current_turn,
                            current_turn,
                            f"{target} hidden discovery {HIDDEN_PROBE_TOKEN} {index}",
                            f"9999-07-09T00:00:{index:02d}+00:00",
                            f"9999-07-09T00:00:{index:02d}+00:00",
                        ),
                    )
                conn.execute(
                    """
                    insert or replace into discovery_states
                    (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
                     confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
                     notes, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "disc:item:test-hidden-context-probe-prefixed",
                        None,
                        None,
                        "clue",
                        "clue",
                        "hinted",
                        20,
                        "[]",
                        "[]",
                        current_turn,
                        current_turn,
                        f"{target} id-embedded discovery",
                        "9999-07-10T00:00:00+00:00",
                        "9999-07-10T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into discovery_states
                    (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
                     confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
                     notes, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "disc:test-hidden-text-prefixed",
                        None,
                        None,
                        "clue",
                        "clue",
                        "hinted",
                        20,
                        json.dumps(["disc:item:test-hidden-context-probe-prefixed"], ensure_ascii=False),
                        "[]",
                        current_turn,
                        current_turn,
                        f"{target} text discovery",
                        "9999-07-10T00:00:01+00:00",
                        "9999-07-10T00:00:01+00:00",
                    ),
                )
                conn.execute(
                    """
                    insert or replace into discovery_states
                    (id, subject_id, palette_id, kind, stage, visibility, evidence_count,
                     confirmation_methods_json, source_event_ids_json, created_turn_id, updated_turn_id,
                     notes, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "disc:test-safe-starvation",
                        None,
                        None,
                        "clue",
                        "clue",
                        "hinted",
                        1,
                        "[]",
                        "[]",
                        current_turn,
                        current_turn,
                        f"{target} {safe_marker}",
                        "9999-07-08T00:00:00+00:00",
                        "9999-07-08T00:00:00+00:00",
                    ),
                )
                conn.commit()
                player_context = build_context(
                    campaign,
                    conn,
                    user_text=f"线索 {target}",
                    mode="query",
                    submode="context",
                    view="player",
                )

            player_json = player_context.to_json_text()
            player_loaded_ids = {str(item.get("id")) for item in player_context.loaded_items}
            self.assertIn("disc:test-safe-starvation", player_loaded_ids)
            self.assertIn(safe_marker, player_json)
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_json)
            self.assertNotIn("item:test-hidden-context-probe", player_json)

    def test_maintenance_context_intent_ai_uses_maintenance_view_during_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            captured: dict[str, str] = {}

            def fake_collect(*_args: object, **kwargs: object) -> AIHelperResult:
                captured["view"] = str(kwargs.get("view") or "")
                return AIHelperResult(
                    task="internal_intent_review",
                    backend="direct",
                    provider="test",
                    model="test",
                    status="ok",
                    parsed={
                        "kind": "unresolved",
                        "mode": "unknown",
                        "action": None,
                        "slots": {},
                        "plan": [],
                        "confidence": "low",
                        "missing_slots": [],
                        "needs_confirmation": [],
                        "safety_flags": ["maintenance_request"],
                        "reason": "maintenance classification test",
                        "agreement_with_external": "no_external",
                        "disagreements": [],
                        "external_candidate_quality": "no_external",
                    },
                    audit={"status": "ok"},
                )

            with connect(campaign) as conn:
                with patch("rpg_engine.ai_intent.router.collect_internal_intent_candidate", side_effect=fake_collect):
                    build_context(
                        campaign,
                        conn,
                        user_text="系统维护：检查隐藏上下文",
                        mode="maintenance",
                        submode="maintenance",
                        view=None,
                        intent_ai="consensus",
                        intent_backend="direct",
                    )

            self.assertEqual(captured["view"], "maintenance")


if __name__ == "__main__":
    import unittest

    unittest.main()
