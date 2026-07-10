from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rpg_engine.ai.provider import AIHelperResult
from rpg_engine.ai_intent import build_internal_intent_review_prompt
from rpg_engine.campaign import load_campaign
from rpg_engine.cards import GENERATED_MARKER
from rpg_engine.content_types.world_setting import render_world_setting_entity
from rpg_engine.context.collectors import collect_related_history
from rpg_engine.context.semantic import build_semantic_prompt
from rpg_engine.context_builder import build_context
from rpg_engine.db import connect, upsert_clock, upsert_entity
from rpg_engine.memory import find_relevant_memories
from rpg_engine.migrations import apply_pending_migrations
from rpg_engine.projection_service import ProjectionService
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_manager import SaveManager
from rpg_engine.save_patch import apply_save_patch
from rpg_engine.save_validation import validate_search_projection

from tests.helpers import (
    CURRENT_NATIVE_REQUIRED,
    FormalCurrentSaveReadOnlyTestCase,
    copy_current_packages,
)


HIDDEN_PROBE_TOKEN = "BMAD-HIDDEN-CONTEXT-3-2"
GM_ONLY_PROBE_TOKEN = "BMAD-GM-ONLY-DERIVED-3-3"
DETAIL_ONLY_PROBE_TOKEN = "BMAD-HIDDEN-DETAIL-3-3"
HIDDEN_ALIAS_DUPLICATE_TOKEN = "SECRET_ALIAS_X1"
UNSTRUCTURED_HIDDEN_SUMMARY = "绝密口令紫月门"
UNSTRUCTURED_HIDDEN_CODE_FRAGMENT = "紫月门"
UNSTRUCTURED_HIDDEN_DETAIL = "紫月门细节封印"
UNSTRUCTURED_HIDDEN_DETAIL_FRAGMENT = "细节封印"
UNSTRUCTURED_HIDDEN_SEGMENT = "入口在南墙"
UNSTRUCTURED_HIDDEN_SHORT_FRAGMENT = "南墙"
UNDERSCORE_HIDDEN_TOKEN = "SECRET_CODE_KEY"
ALPHA_HIDDEN_TOKEN = "Rosebud"
LOWER_ALPHA_HIDDEN_TOKEN = "rosebud"
HIDDEN_DETAIL_KEY_TOKEN = "SECRET_DETAIL_KEY"
LOWER_HIDDEN_DETAIL_KEY_TOKEN = "secret_detail_key"
MARKER_ALPHA_HIDDEN_TOKEN = "rosebudx"
SHORT_MARKER_ALPHA_HIDDEN_TOKEN = "acorn"
LOWER_MARKER_KEY_TOKEN = "secret_code_key"
SHORT_CJK_HIDDEN_TOKEN = "龙牙"
HIDDEN_ID_SUBSTRING_TOKEN = "Xitem:test-hidden-context-probeY"
PUBLIC_NAME_SECRET_TOKEN = "VISIBLE_SECRET_X1"
WORLD_SETTING_SIDE_SECRET = "紫月门世界设定真相"
WORLD_SETTING_SIDE_ALIAS = "紫月门设定别名"
WORLD_SETTING_SIDE_ALPHA_SECRET = "worldsecretalpha"
WORLD_SETTING_MISSING_ROW_SECRET = "缺行世界设定真相"
WORLD_SETTING_MISSING_ROW_ALIAS = "缺行设定别名"


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
         source_turn_ids_json, valid_from_turn, valid_to_turn, summary_type, visibility_mode,
         freshness_status, freshness_turn_id, stale_reason, freshness_evidence_json,
         derived_authority_json, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            "deterministic_world",
            "maintenance",
            "fresh",
            current_turn,
            "",
            json.dumps(
                {
                    "current_turn_id": current_turn,
                    "valid_from_turn": current_turn,
                },
                ensure_ascii=False,
            ),
            json.dumps({"authority": "derived_context", "fact_authority": False}),
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

    def test_player_search_projection_excludes_hidden_and_gm_only_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                install_hidden_context_probe(conn)
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-hidden-detail-only-probe",
                        "type": "item",
                        "name": "隐藏细节专用探针",
                        "visibility": "hidden",
                        "status": "active",
                        "summary": UNSTRUCTURED_HIDDEN_SUMMARY,
                        "aliases": [HIDDEN_ALIAS_DUPLICATE_TOKEN, PUBLIC_NAME_SECRET_TOKEN],
                        "details": {
                            "secret": DETAIL_ONLY_PROBE_TOKEN,
                            "unstructured": UNSTRUCTURED_HIDDEN_DETAIL,
                            "sentence": f"{UNSTRUCTURED_HIDDEN_DETAIL}，{UNSTRUCTURED_HIDDEN_SEGMENT}",
                            "marker_sentence": f"the secret code is {MARKER_ALPHA_HIDDEN_TOKEN}",
                            "short_marker_sentence": f"secret code is {SHORT_MARKER_ALPHA_HIDDEN_TOKEN}",
                            "cjk_marker_sentence": f"暗号是{SHORT_CJK_HIDDEN_TOKEN}",
                            "underscore": UNDERSCORE_HIDDEN_TOKEN,
                            "alpha": ALPHA_HIDDEN_TOKEN,
                            "lower_alpha": LOWER_ALPHA_HIDDEN_TOKEN,
                            HIDDEN_DETAIL_KEY_TOKEN: "hidden key marker",
                            LOWER_HIDDEN_DETAIL_KEY_TOKEN: "hidden lowercase key marker",
                            LOWER_MARKER_KEY_TOKEN: "hidden lowercase code marker",
                            "short_cjk": SHORT_CJK_HIDDEN_TOKEN,
                        },
                    },
                )
                current_location = conn.execute("select value from meta where key='current_location_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-gm-only-fts-probe",
                        "type": "item",
                        "name": f"GM专用星图{GM_ONLY_PROBE_TOKEN}",
                        "visibility": "gm",
                        "status": "active",
                        "location_id": current_location,
                        "summary": f"GM-only 摘要 {GM_ONLY_PROBE_TOKEN}",
                        "aliases": [GM_ONLY_PROBE_TOKEN],
                        "details": {"secret": f"GM-only 细节 {GM_ONLY_PROBE_TOKEN}"},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-visible-derived-carrier",
                        "type": "item",
                        "name": f"可见派生载体{UNSTRUCTURED_HIDDEN_CODE_FRAGMENT}",
                        "visibility": "known",
                        "status": "active",
                        "location_id": current_location,
                        "summary": (
                            "可见摘要误带 "
                            "item:test-hidden-context-probe "
                            "item:test-gm-only-fts-probe "
                            f"{DETAIL_ONLY_PROBE_TOKEN} "
                            f"{UNSTRUCTURED_HIDDEN_SUMMARY} "
                            f"{UNSTRUCTURED_HIDDEN_SEGMENT} "
                            f"{HIDDEN_ID_SUBSTRING_TOKEN} "
                            f"{ALPHA_HIDDEN_TOKEN} "
                            f"{LOWER_ALPHA_HIDDEN_TOKEN} "
                            f"{LOWER_ALPHA_HIDDEN_TOKEN.upper()} "
                            f"{MARKER_ALPHA_HIDDEN_TOKEN.upper()} "
                            f"{SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper()} "
                            f"{LOWER_MARKER_KEY_TOKEN.upper()} "
                            f"{SHORT_CJK_HIDDEN_TOKEN}"
                        ),
                        "details": {
                            "leaked_hidden": "item:test-hidden-context-probe",
                            "leaked_gm_only": "item:test-gm-only-fts-probe",
                            "leaked_hidden_substring": HIDDEN_ID_SUBSTRING_TOKEN,
                            "leaked_hidden_detail": DETAIL_ONLY_PROBE_TOKEN,
                            "leaked_unstructured_detail": UNSTRUCTURED_HIDDEN_DETAIL,
                            "leaked_detail_fragment": UNSTRUCTURED_HIDDEN_DETAIL_FRAGMENT,
                            "leaked_code_fragment": UNSTRUCTURED_HIDDEN_CODE_FRAGMENT,
                            "leaked_segment": UNSTRUCTURED_HIDDEN_SEGMENT,
                            "leaked_short_fragment": UNSTRUCTURED_HIDDEN_SHORT_FRAGMENT,
                            "leaked_underscore": UNDERSCORE_HIDDEN_TOKEN,
                            "leaked_alpha": ALPHA_HIDDEN_TOKEN,
                            "leaked_lower_alpha": LOWER_ALPHA_HIDDEN_TOKEN,
                            "leaked_upper_lower_alpha": LOWER_ALPHA_HIDDEN_TOKEN.upper(),
                            "leaked_marker_alpha": MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                            "leaked_short_marker_alpha": SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                            "leaked_detail_key": HIDDEN_DETAIL_KEY_TOKEN,
                            "leaked_lower_detail_key": LOWER_HIDDEN_DETAIL_KEY_TOKEN,
                            "leaked_lower_marker_key": LOWER_MARKER_KEY_TOKEN.upper(),
                            "leaked_short_cjk": SHORT_CJK_HIDDEN_TOKEN,
                        },
                        "aliases": [
                            HIDDEN_ALIAS_DUPLICATE_TOKEN,
                            "item:test-hidden-detail-only-probe",
                        ],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-visible-public-name-collision",
                        "type": "item",
                        "name": PUBLIC_NAME_SECRET_TOKEN,
                        "visibility": "known",
                        "status": "active",
                        "location_id": current_location,
                        "summary": PUBLIC_NAME_SECRET_TOKEN,
                        "details": {"public_name": PUBLIC_NAME_SECRET_TOKEN},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "world:test-side-hidden-search",
                        "type": "world_setting",
                        "name": "可见实体隐藏设定搜索壳",
                        "visibility": "known",
                        "status": "active",
                        "summary": f"{WORLD_SETTING_SIDE_SECRET} {WORLD_SETTING_SIDE_ALPHA_SECRET}",
                        "details": {"content": f"{WORLD_SETTING_SIDE_SECRET} {WORLD_SETTING_SIDE_ALPHA_SECRET}"},
                        "aliases": [WORLD_SETTING_SIDE_ALIAS],
                    },
                )
                conn.execute(
                    """
                    insert or replace into world_settings
                    (entity_id, category, scope, visibility, priority, summary, content_json,
                     linked_rules_json, linked_clocks_json, linked_entities_json, applies_when_json, source)
                    values (?, 'truth', 'world', 'gm', 100, ?, ?, '[]', '[]', '[]', '{}', 'test')
                    """,
                    (
                        "world:test-side-hidden-search",
                        f"{WORLD_SETTING_SIDE_SECRET} {WORLD_SETTING_SIDE_ALPHA_SECRET}",
                        json.dumps(
                            {"truth": WORLD_SETTING_SIDE_SECRET, "alpha_secret": WORLD_SETTING_SIDE_ALPHA_SECRET},
                            ensure_ascii=False,
                        ),
                    ),
                )
                upsert_entity(
                    conn,
                    {
                        "id": "world:test-missing-side-row-search",
                        "type": "world_setting",
                        "name": WORLD_SETTING_MISSING_ROW_ALIAS,
                        "visibility": "known",
                        "status": "active",
                        "summary": WORLD_SETTING_MISSING_ROW_SECRET,
                        "details": {"truth": WORLD_SETTING_MISSING_ROW_SECRET},
                        "aliases": [WORLD_SETTING_MISSING_ROW_ALIAS],
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-visible-missing-side-row-carrier",
                        "type": "item",
                        "name": "缺行设定可见载体",
                        "visibility": "known",
                        "status": "active",
                        "location_id": current_location,
                        "summary": (
                            f"误带 {WORLD_SETTING_MISSING_ROW_SECRET} "
                            f"world:test-missing-side-row-search {WORLD_SETTING_MISSING_ROW_ALIAS} "
                            f"{WORLD_SETTING_SIDE_ALPHA_SECRET.upper()}"
                        ),
                        "details": {
                            "missing_side_row_secret": WORLD_SETTING_MISSING_ROW_SECRET,
                            "missing_side_row_ref": "world:test-missing-side-row-search",
                            "missing_side_row_alias": WORLD_SETTING_MISSING_ROW_ALIAS,
                            "side_alpha_secret": WORLD_SETTING_SIDE_ALPHA_SECRET.upper(),
                        },
                    },
                )
                side_setting_entity = conn.execute(
                    "select * from entities where id = ?",
                    ("world:test-side-hidden-search",),
                ).fetchone()
                missing_side_setting_entity = conn.execute(
                    "select * from entities where id = ?",
                    ("world:test-missing-side-row-search",),
                ).fetchone()
                direct_side_player_render = render_world_setting_entity(conn, side_setting_entity)
                direct_missing_side_player_render = render_world_setting_entity(conn, missing_side_setting_entity)
                direct_side_gm_render = render_world_setting_entity(conn, side_setting_entity, view="gm")
                conn.commit()
                report = ProjectionService(campaign, conn).refresh(
                    names=["search"],
                    dirty_only=False,
                    profile="test:derived_visibility_search",
                )
                self.assertTrue(report.ok, report.errors)
                rows = [dict(row) for row in conn.execute("select entity_id, title, body, tags from fts_index").fetchall()]
                fts_blob = json.dumps(rows, ensure_ascii=False)
                validation_errors: list[str] = []
                validate_search_projection(conn, validation_errors)
                self.assertEqual(validation_errors, [])
                for leaked_token in (
                    DETAIL_ONLY_PROBE_TOKEN,
                    HIDDEN_ALIAS_DUPLICATE_TOKEN,
                    UNSTRUCTURED_HIDDEN_SUMMARY,
                    UNSTRUCTURED_HIDDEN_CODE_FRAGMENT,
                    UNSTRUCTURED_HIDDEN_DETAIL_FRAGMENT,
                    UNSTRUCTURED_HIDDEN_SEGMENT,
                    UNSTRUCTURED_HIDDEN_SHORT_FRAGMENT,
                    UNDERSCORE_HIDDEN_TOKEN,
                    ALPHA_HIDDEN_TOKEN,
                    LOWER_ALPHA_HIDDEN_TOKEN,
                    MARKER_ALPHA_HIDDEN_TOKEN,
                    SHORT_MARKER_ALPHA_HIDDEN_TOKEN,
                    HIDDEN_DETAIL_KEY_TOKEN,
                    LOWER_HIDDEN_DETAIL_KEY_TOKEN,
                    LOWER_MARKER_KEY_TOKEN,
                    SHORT_CJK_HIDDEN_TOKEN,
                    PUBLIC_NAME_SECRET_TOKEN,
                    "item:test-hidden-context-probe",
                    "world:test-side-hidden-search",
                    WORLD_SETTING_SIDE_ALIAS,
                    WORLD_SETTING_SIDE_ALPHA_SECRET,
                    "world:test-missing-side-row-search",
                    WORLD_SETTING_MISSING_ROW_ALIAS,
                    WORLD_SETTING_MISSING_ROW_SECRET,
                ):
                    with self.subTest(validation_token=leaked_token):
                        conn.execute(
                            "update fts_index set body = ? where entity_id = ?",
                            (f"visible pollution {leaked_token}", "item:test-visible-derived-carrier"),
                        )
                        validation_errors = []
                        validate_search_projection(conn, validation_errors)
                        self.assertTrue(any(leaked_token in error for error in validation_errors), validation_errors)
                for leaked_token, expected_token in (
                    (LOWER_ALPHA_HIDDEN_TOKEN.upper(), LOWER_ALPHA_HIDDEN_TOKEN),
                    (MARKER_ALPHA_HIDDEN_TOKEN.upper(), MARKER_ALPHA_HIDDEN_TOKEN),
                    (SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(), SHORT_MARKER_ALPHA_HIDDEN_TOKEN),
                    (LOWER_MARKER_KEY_TOKEN.upper(), LOWER_MARKER_KEY_TOKEN),
                    (WORLD_SETTING_SIDE_ALPHA_SECRET.upper(), WORLD_SETTING_SIDE_ALPHA_SECRET),
                    ("XITEM:TEST-HIDDEN-CONTEXT-PROBEY", "item:test-hidden-context-probe"),
                ):
                    with self.subTest(validation_token=leaked_token):
                        conn.execute(
                            "update fts_index set body = ? where entity_id = ?",
                            (f"visible pollution {leaked_token}", "item:test-visible-derived-carrier"),
                        )
                        validation_errors = []
                        validate_search_projection(conn, validation_errors)
                        self.assertTrue(any(expected_token in error for error in validation_errors), validation_errors)
                conn.execute(
                    "update fts_index set body = ? where entity_id = ?",
                    (f"visible pollution {HIDDEN_ID_SUBSTRING_TOKEN}", "item:test-visible-derived-carrier"),
                )
                validation_errors = []
                validate_search_projection(conn, validation_errors)
                self.assertTrue(
                    any("item:test-hidden-context-probe" in error for error in validation_errors),
                    validation_errors,
                )
                report = ProjectionService(campaign, conn).refresh(
                    names=["search"],
                    dirty_only=False,
                    profile="test:derived_visibility_search_restore",
                )
                self.assertTrue(report.ok, report.errors)
                player_side_context = build_context(
                    campaign,
                    conn,
                    user_text=f"查询 {WORLD_SETTING_SIDE_ALIAS}",
                    mode="query",
                    submode="context",
                    view="player",
                    budget=1800,
                )
                player_missing_row_context = build_context(
                    campaign,
                    conn,
                    user_text=f"查询 {WORLD_SETTING_MISSING_ROW_ALIAS}",
                    mode="query",
                    submode="context",
                    view="player",
                    budget=1800,
                )
                player_hidden_like_context = build_context(
                    campaign,
                    conn,
                    user_text=f"查询 {LOWER_ALPHA_HIDDEN_TOKEN}",
                    mode="query",
                    submode="entity",
                    view="player",
                    budget=1800,
                )
                gm_side_context = build_context(
                    campaign,
                    conn,
                    user_text=f"查询 {WORLD_SETTING_SIDE_ALIAS}",
                    mode="query",
                    submode="context",
                    view="gm",
                    budget=1800,
                )
                semantic_prompt = build_semantic_prompt(
                    SimpleNamespace(
                        conn=conn,
                        user_text=f"查询 {WORLD_SETTING_SIDE_ALIAS}",
                        mode="query",
                        submode="context",
                        entity_hits=[],
                        visibility_view="player",
                    )
                )
                intent_prompt = build_internal_intent_review_prompt(
                    conn,
                    f"查询 {WORLD_SETTING_SIDE_ALIAS}",
                    view="player",
                )

            runtime = GMRuntime.from_path(save)
            player_hidden_query = runtime.query("entity", HIDDEN_PROBE_TOKEN, view="player")
            player_gm_query = runtime.query("entity", GM_ONLY_PROBE_TOKEN, view="player")
            player_detail_query = runtime.query("entity", DETAIL_ONLY_PROBE_TOKEN, view="player")
            player_duplicate_alias_query = runtime.query("entity", HIDDEN_ALIAS_DUPLICATE_TOKEN, view="player")
            player_code_fragment_query = runtime.query("entity", UNSTRUCTURED_HIDDEN_CODE_FRAGMENT, view="player")
            player_detail_fragment_query = runtime.query("entity", UNSTRUCTURED_HIDDEN_DETAIL_FRAGMENT, view="player")
            player_segment_query = runtime.query("entity", UNSTRUCTURED_HIDDEN_SEGMENT, view="player")
            player_short_fragment_query = runtime.query("entity", UNSTRUCTURED_HIDDEN_SHORT_FRAGMENT, view="player")
            player_underscore_query = runtime.query("entity", UNDERSCORE_HIDDEN_TOKEN, view="player")
            player_alpha_query = runtime.query("entity", ALPHA_HIDDEN_TOKEN, view="player")
            player_lower_alpha_query = runtime.query("entity", LOWER_ALPHA_HIDDEN_TOKEN, view="player")
            player_upper_lower_alpha_query = runtime.query("entity", LOWER_ALPHA_HIDDEN_TOKEN.upper(), view="player")
            player_marker_alpha_query = runtime.query("entity", MARKER_ALPHA_HIDDEN_TOKEN, view="player")
            player_marker_alpha_upper_query = runtime.query("entity", MARKER_ALPHA_HIDDEN_TOKEN.upper(), view="player")
            player_short_marker_alpha_query = runtime.query("entity", SHORT_MARKER_ALPHA_HIDDEN_TOKEN, view="player")
            player_short_marker_alpha_upper_query = runtime.query(
                "entity",
                SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                view="player",
            )
            player_detail_key_query = runtime.query("entity", HIDDEN_DETAIL_KEY_TOKEN, view="player")
            player_lower_detail_key_query = runtime.query("entity", LOWER_HIDDEN_DETAIL_KEY_TOKEN, view="player")
            player_lower_marker_key_query = runtime.query("entity", LOWER_MARKER_KEY_TOKEN, view="player")
            player_lower_marker_key_upper_query = runtime.query("entity", LOWER_MARKER_KEY_TOKEN.upper(), view="player")
            player_short_cjk_query = runtime.query("entity", SHORT_CJK_HIDDEN_TOKEN, view="player")
            player_hidden_substring_query = runtime.query("entity", HIDDEN_ID_SUBSTRING_TOKEN, view="player")
            player_hidden_substring_upper_query = runtime.query("entity", "XITEM:TEST-HIDDEN-CONTEXT-PROBEY", view="player")
            player_public_name_collision_query = runtime.query("entity", PUBLIC_NAME_SECRET_TOKEN, view="player")
            player_side_entity_query = runtime.query("entity", "world:test-side-hidden-search", view="player")
            gm_query = runtime.query("entity", GM_ONLY_PROBE_TOKEN, view="gm")
            gm_side_entity_query = runtime.query("entity", "world:test-side-hidden-search", view="gm")

            self.assertNotIn(HIDDEN_PROBE_TOKEN, fts_blob)
            self.assertNotIn("item:test-hidden-context-probe", fts_blob)
            self.assertNotIn(HIDDEN_ID_SUBSTRING_TOKEN, fts_blob)
            self.assertNotIn(DETAIL_ONLY_PROBE_TOKEN, fts_blob)
            self.assertNotIn(HIDDEN_ALIAS_DUPLICATE_TOKEN, fts_blob)
            self.assertNotIn("item:test-hidden-detail-only-probe", fts_blob)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_SUMMARY, fts_blob)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_CODE_FRAGMENT, fts_blob)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_DETAIL, fts_blob)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_DETAIL_FRAGMENT, fts_blob)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_SEGMENT, fts_blob)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_SHORT_FRAGMENT, fts_blob)
            self.assertNotIn(UNDERSCORE_HIDDEN_TOKEN, fts_blob)
            self.assertNotIn(ALPHA_HIDDEN_TOKEN, fts_blob)
            self.assertNotIn(LOWER_ALPHA_HIDDEN_TOKEN, fts_blob)
            self.assertNotIn(LOWER_ALPHA_HIDDEN_TOKEN.upper(), fts_blob)
            self.assertNotIn(MARKER_ALPHA_HIDDEN_TOKEN, fts_blob)
            self.assertNotIn(MARKER_ALPHA_HIDDEN_TOKEN.upper(), fts_blob)
            self.assertNotIn(SHORT_MARKER_ALPHA_HIDDEN_TOKEN, fts_blob)
            self.assertNotIn(SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(), fts_blob)
            self.assertNotIn(HIDDEN_DETAIL_KEY_TOKEN, fts_blob)
            self.assertNotIn(LOWER_HIDDEN_DETAIL_KEY_TOKEN, fts_blob)
            self.assertNotIn(LOWER_MARKER_KEY_TOKEN, fts_blob)
            self.assertNotIn(LOWER_MARKER_KEY_TOKEN.upper(), fts_blob)
            self.assertNotIn(SHORT_CJK_HIDDEN_TOKEN, fts_blob)
            self.assertNotIn(PUBLIC_NAME_SECRET_TOKEN, fts_blob)
            self.assertNotIn(WORLD_SETTING_SIDE_SECRET, fts_blob)
            self.assertNotIn(WORLD_SETTING_SIDE_ALPHA_SECRET, fts_blob)
            self.assertNotIn(WORLD_SETTING_SIDE_ALPHA_SECRET.upper(), fts_blob)
            self.assertNotIn("world:test-side-hidden-search", fts_blob)
            self.assertNotIn(WORLD_SETTING_SIDE_ALIAS, fts_blob)
            self.assertNotIn(WORLD_SETTING_MISSING_ROW_SECRET, fts_blob)
            self.assertNotIn("world:test-missing-side-row-search", fts_blob)
            self.assertNotIn(WORLD_SETTING_MISSING_ROW_ALIAS, fts_blob)
            self.assertNotIn(GM_ONLY_PROBE_TOKEN, fts_blob)
            self.assertNotIn("item:test-gm-only-fts-probe", fts_blob)
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_hidden_query.text)
            self.assertNotIn("item:test-hidden-context-probe", player_hidden_query.text)
            self.assertNotIn(DETAIL_ONLY_PROBE_TOKEN, player_detail_query.text)
            self.assertNotIn(HIDDEN_ALIAS_DUPLICATE_TOKEN, player_duplicate_alias_query.text)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_CODE_FRAGMENT, player_code_fragment_query.text)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_DETAIL_FRAGMENT, player_detail_fragment_query.text)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_SEGMENT, player_segment_query.text)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_SHORT_FRAGMENT, player_short_fragment_query.text)
            self.assertNotIn(UNDERSCORE_HIDDEN_TOKEN, player_underscore_query.text)
            self.assertNotIn(ALPHA_HIDDEN_TOKEN, player_alpha_query.text)
            self.assertNotIn(LOWER_ALPHA_HIDDEN_TOKEN, player_lower_alpha_query.text)
            self.assertNotIn(LOWER_ALPHA_HIDDEN_TOKEN.upper(), player_upper_lower_alpha_query.text)
            self.assertNotIn(MARKER_ALPHA_HIDDEN_TOKEN, player_marker_alpha_query.text)
            self.assertNotIn(MARKER_ALPHA_HIDDEN_TOKEN.upper(), player_marker_alpha_upper_query.text)
            self.assertNotIn(SHORT_MARKER_ALPHA_HIDDEN_TOKEN, player_short_marker_alpha_query.text)
            self.assertNotIn(SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(), player_short_marker_alpha_upper_query.text)
            self.assertNotIn(HIDDEN_DETAIL_KEY_TOKEN, player_detail_key_query.text)
            self.assertNotIn(LOWER_HIDDEN_DETAIL_KEY_TOKEN, player_lower_detail_key_query.text)
            self.assertNotIn(LOWER_MARKER_KEY_TOKEN, player_lower_marker_key_query.text)
            self.assertNotIn(LOWER_MARKER_KEY_TOKEN.upper(), player_lower_marker_key_upper_query.text)
            self.assertNotIn(SHORT_CJK_HIDDEN_TOKEN, player_short_cjk_query.text)
            self.assertNotIn("item:test-hidden-context-probe", player_hidden_substring_query.text)
            self.assertNotIn("ITEM:TEST-HIDDEN-CONTEXT-PROBE", player_hidden_substring_upper_query.text)
            player_hidden_substring_payload = json.dumps(player_hidden_substring_query.to_dict(), ensure_ascii=False)
            player_hidden_substring_upper_payload = json.dumps(
                player_hidden_substring_upper_query.to_dict(),
                ensure_ascii=False,
            )
            self.assertNotIn(HIDDEN_ID_SUBSTRING_TOKEN, player_hidden_substring_payload)
            self.assertNotIn("item:test-hidden-context-probe", player_hidden_substring_payload)
            self.assertNotIn("ITEM:TEST-HIDDEN-CONTEXT-PROBE", player_hidden_substring_upper_payload)
            self.assertNotIn(PUBLIC_NAME_SECRET_TOKEN, player_public_name_collision_query.text)
            self.assertNotIn("world:test-side-hidden-search", player_side_entity_query.text)
            self.assertNotIn(WORLD_SETTING_SIDE_SECRET, player_side_entity_query.text)
            self.assertNotIn(WORLD_SETTING_SIDE_ALPHA_SECRET, player_side_entity_query.text)
            self.assertNotIn("world:test-side-hidden-search", direct_side_player_render)
            self.assertNotIn(WORLD_SETTING_SIDE_ALIAS, direct_side_player_render)
            self.assertNotIn(WORLD_SETTING_SIDE_SECRET, direct_side_player_render)
            self.assertNotIn("world:test-missing-side-row-search", direct_missing_side_player_render)
            self.assertNotIn(WORLD_SETTING_MISSING_ROW_ALIAS, direct_missing_side_player_render)
            self.assertNotIn(WORLD_SETTING_MISSING_ROW_SECRET, direct_missing_side_player_render)
            self.assertNotIn(GM_ONLY_PROBE_TOKEN, player_gm_query.text)
            self.assertNotIn("item:test-gm-only-fts-probe", player_gm_query.text)
            self.assertIn("item:test-gm-only-fts-probe", gm_query.text)
            self.assertIn(GM_ONLY_PROBE_TOKEN, gm_query.text)
            self.assertIn("world:test-side-hidden-search", gm_side_entity_query.text)
            self.assertIn(WORLD_SETTING_SIDE_SECRET, gm_side_entity_query.text)
            self.assertIn(WORLD_SETTING_SIDE_ALPHA_SECRET, gm_side_entity_query.text)
            self.assertIn("world:test-side-hidden-search", direct_side_gm_render)
            self.assertIn(WORLD_SETTING_SIDE_SECRET, direct_side_gm_render)
            player_side_json = player_side_context.to_json_text()
            player_missing_row_json = player_missing_row_context.to_json_text()
            player_hidden_like_json = player_hidden_like_context.to_json_text()
            gm_side_json = gm_side_context.to_json_text()
            player_side_loaded_ids = {str(item.get("id")) for item in player_side_context.loaded_items}
            self.assertNotIn("world:test-side-hidden-search", player_side_loaded_ids)
            self.assertNotIn("world:test-side-hidden-search", player_side_json)
            self.assertNotIn(WORLD_SETTING_SIDE_ALIAS, player_side_json)
            self.assertNotIn(WORLD_SETTING_SIDE_SECRET, player_side_json)
            self.assertNotIn(WORLD_SETTING_SIDE_ALPHA_SECRET, player_side_json)
            self.assertNotIn("world:test-missing-side-row-search", player_missing_row_json)
            self.assertNotIn(WORLD_SETTING_MISSING_ROW_ALIAS, player_missing_row_json)
            self.assertNotIn(WORLD_SETTING_MISSING_ROW_SECRET, player_missing_row_json)
            self.assertNotIn(
                "item:test-visible-derived-carrier",
                player_hidden_like_context.sections.get("relevant_entities", ""),
            )
            self.assertNotIn(LOWER_ALPHA_HIDDEN_TOKEN, player_hidden_like_json)
            self.assertNotIn(WORLD_SETTING_SIDE_ALIAS, semantic_prompt)
            self.assertNotIn(WORLD_SETTING_SIDE_ALIAS, intent_prompt)
            self.assertIn("world:test-side-hidden-search", gm_side_json)
            self.assertIn(WORLD_SETTING_SIDE_ALIAS, gm_side_json)

    def test_player_snapshots_cards_and_onboarding_exclude_hidden_and_gm_only_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            save = copy_current_packages(root)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                apply_pending_migrations(conn)
                original_location = conn.execute("select value from meta where key='current_location_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-hidden-context-probe",
                        "type": "item",
                        "name": f"隐藏派生道具{HIDDEN_PROBE_TOKEN}",
                        "visibility": "hidden",
                        "status": "active",
                        "location_id": original_location,
                        "summary": f"隐藏派生道具摘要 {HIDDEN_PROBE_TOKEN}",
                        "aliases": [HIDDEN_PROBE_TOKEN, PUBLIC_NAME_SECRET_TOKEN],
                        "details": {
                            "secret": f"隐藏派生道具细节 {HIDDEN_PROBE_TOKEN}",
                            "detail_only": DETAIL_ONLY_PROBE_TOKEN,
                            "alpha": ALPHA_HIDDEN_TOKEN,
                            "lower_alpha": LOWER_ALPHA_HIDDEN_TOKEN,
                            "marker_sentence": f"the secret code is {MARKER_ALPHA_HIDDEN_TOKEN}",
                            "short_marker_sentence": f"secret code is {SHORT_MARKER_ALPHA_HIDDEN_TOKEN}",
                            "cjk_marker_sentence": f"暗号是{SHORT_CJK_HIDDEN_TOKEN}",
                            HIDDEN_DETAIL_KEY_TOKEN: "hidden card key marker",
                            LOWER_HIDDEN_DETAIL_KEY_TOKEN: "hidden lowercase card key marker",
                            LOWER_MARKER_KEY_TOKEN: "hidden lowercase card code marker",
                            "short_cjk": SHORT_CJK_HIDDEN_TOKEN,
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "loc:test-hidden-derived-current",
                        "type": "location",
                        "name": f"隐藏派生当前位置{HIDDEN_PROBE_TOKEN}",
                        "visibility": "hidden",
                        "status": "active",
                        "summary": f"隐藏当前位置摘要 {HIDDEN_PROBE_TOKEN}",
                        "aliases": [f"hidden-derived-location-{HIDDEN_PROBE_TOKEN}"],
                        "details": {"secret": f"隐藏当前位置细节 {HIDDEN_PROBE_TOKEN}"},
                    },
                )
                conn.execute(
                    "insert into locations(entity_id, description_short) values(?, ?) "
                    "on conflict(entity_id) do update set description_short=excluded.description_short",
                    ("loc:test-hidden-derived-current", f"隐藏当前位置描述 {HIDDEN_PROBE_TOKEN}"),
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-gm-only-card-probe",
                        "type": "item",
                        "name": f"GM专用卡片{GM_ONLY_PROBE_TOKEN}",
                        "visibility": "gm",
                        "status": "active",
                        "location_id": original_location,
                        "summary": f"GM-only 卡片摘要 {GM_ONLY_PROBE_TOKEN}",
                        "aliases": [GM_ONLY_PROBE_TOKEN],
                        "details": {"secret": f"GM-only 卡片细节 {GM_ONLY_PROBE_TOKEN}"},
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:test-hidden-derived-clock",
                        "name": f"隐藏派生时钟{HIDDEN_PROBE_TOKEN}",
                        "summary": f"隐藏时钟摘要 {HIDDEN_PROBE_TOKEN}",
                        "visibility": "hidden",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "trigger_when_full": f"隐藏时钟触发 {HIDDEN_PROBE_TOKEN}",
                        "aliases": [f"hidden-derived-clock-{HIDDEN_PROBE_TOKEN}"],
                    },
                )
                current_turn = conn.execute("select value from meta where key='current_turn_id'").fetchone()[0]
                now = "9999-07-09T00:00:00+00:00"
                conn.execute(
                    """
                    insert or replace into events
                    (id, turn_id, game_time, type, title, summary, payload_json, source, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "event:test-hidden-derived-artifact-probe",
                        current_turn,
                        "第28天",
                        "hidden_probe",
                        f"隐藏事件 item:test-hidden-context-probe {HIDDEN_PROBE_TOKEN}",
                        f"隐藏事件摘要 item:test-hidden-context-probe {HIDDEN_PROBE_TOKEN}",
                        json.dumps(
                            {
                                "hidden_ref": "item:test-hidden-context-probe",
                                "secret": HIDDEN_PROBE_TOKEN,
                            },
                            ensure_ascii=False,
                        ),
                        "test",
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
                        "memory:test-hidden-derived-artifact-probe",
                        "world",
                        None,
                        f"隐藏记忆 item:test-hidden-context-probe {HIDDEN_PROBE_TOKEN}",
                        f"隐藏记忆摘要 item:test-hidden-context-probe {HIDDEN_PROBE_TOKEN}",
                        json.dumps(
                            [f"隐藏记忆要点 item:test-hidden-context-probe {HIDDEN_PROBE_TOKEN}"],
                            ensure_ascii=False,
                        ),
                        json.dumps(["event:test-hidden-derived-artifact-probe"], ensure_ascii=False),
                        json.dumps([current_turn], ensure_ascii=False),
                        current_turn,
                        None,
                        now,
                    ),
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-visible-card-carrier",
                        "type": "item",
                        "name": "可见卡片载体",
                        "visibility": "known",
                        "status": "active",
                        "location_id": original_location,
                        "summary": (
                            "可见卡片摘要误带 "
                            "item:test-hidden-context-probe "
                            "item:test-gm-only-card-probe "
                            f"{DETAIL_ONLY_PROBE_TOKEN} "
                            f"{HIDDEN_ID_SUBSTRING_TOKEN} "
                            f"{ALPHA_HIDDEN_TOKEN} "
                            f"{LOWER_ALPHA_HIDDEN_TOKEN} "
                            f"{LOWER_ALPHA_HIDDEN_TOKEN.upper()} "
                            f"{MARKER_ALPHA_HIDDEN_TOKEN.upper()} "
                            f"{SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper()} "
                            f"{LOWER_MARKER_KEY_TOKEN.upper()} "
                            f"{SHORT_CJK_HIDDEN_TOKEN}"
                        ),
                        "details": {
                            "hidden_ref": "item:test-hidden-context-probe",
                            "gm_only_ref": "item:test-gm-only-card-probe",
                            "hidden_ref_substring": HIDDEN_ID_SUBSTRING_TOKEN,
                            "hidden_detail": DETAIL_ONLY_PROBE_TOKEN,
                            "hidden_alpha": ALPHA_HIDDEN_TOKEN,
                            "hidden_lower_alpha": LOWER_ALPHA_HIDDEN_TOKEN,
                            "hidden_upper_lower_alpha": LOWER_ALPHA_HIDDEN_TOKEN.upper(),
                            "hidden_marker_alpha": MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                            "hidden_short_marker_alpha": SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                            "hidden_key": HIDDEN_DETAIL_KEY_TOKEN,
                            "hidden_lower_key": LOWER_HIDDEN_DETAIL_KEY_TOKEN,
                            "hidden_lower_marker_key": LOWER_MARKER_KEY_TOKEN.upper(),
                            "hidden_short_cjk": SHORT_CJK_HIDDEN_TOKEN,
                        },
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-visible-card-public-name-collision",
                        "type": "item",
                        "name": PUBLIC_NAME_SECRET_TOKEN,
                        "visibility": "known",
                        "status": "active",
                        "location_id": original_location,
                        "summary": PUBLIC_NAME_SECRET_TOKEN,
                        "details": {"public_name": PUBLIC_NAME_SECRET_TOKEN},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "world:test-side-hidden-card",
                        "type": "world_setting",
                        "name": "可见实体隐藏设定卡片壳",
                        "visibility": "known",
                        "status": "active",
                        "summary": f"{WORLD_SETTING_SIDE_SECRET} {WORLD_SETTING_SIDE_ALPHA_SECRET}",
                        "details": {"content": f"{WORLD_SETTING_SIDE_SECRET} {WORLD_SETTING_SIDE_ALPHA_SECRET}"},
                        "aliases": [WORLD_SETTING_SIDE_ALIAS],
                    },
                )
                conn.execute(
                    """
                    insert or replace into world_settings
                    (entity_id, category, scope, visibility, priority, summary, content_json,
                     linked_rules_json, linked_clocks_json, linked_entities_json, applies_when_json, source)
                    values (?, 'truth', 'world', 'gm', 100, ?, ?, '[]', '[]', '[]', '{}', 'test')
                    """,
                    (
                        "world:test-side-hidden-card",
                        f"{WORLD_SETTING_SIDE_SECRET} {WORLD_SETTING_SIDE_ALPHA_SECRET}",
                        json.dumps(
                            {"truth": WORLD_SETTING_SIDE_SECRET, "alpha_secret": WORLD_SETTING_SIDE_ALPHA_SECRET},
                            ensure_ascii=False,
                        ),
                    ),
                )
                conn.execute(
                    "update meta set value='loc:test-hidden-derived-current' where key='current_location_id'"
                )
                conn.commit()

                stale_gm_only_card = campaign.cards_path / "items" / "item__test-gm-only-card-probe.md"
                stale_gm_only_card.parent.mkdir(parents=True, exist_ok=True)
                stale_gm_only_card.write_text(
                    f"{GENERATED_MARKER}\n# 旧 GM-only 卡片\n\n{GM_ONLY_PROBE_TOKEN}\n",
                    encoding="utf-8",
                )

                report = ProjectionService(campaign, conn).refresh(
                    names=["events_jsonl", "search", "snapshots", "cards"],
                    dirty_only=False,
                    profile="test:derived_visibility_artifacts",
                )
                self.assertTrue(report.ok, report.errors)
                conn.commit()

            manager = SaveManager(root)
            save_record = manager.build_save_record(
                save_id="save:test-derived-visibility",
                campaign_path=campaign.root.relative_to(root).as_posix(),
                save_path=save.relative_to(root).as_posix(),
                label="Derived visibility test",
                kind="normal",
                source="test",
            )
            manager.write_registry({
                "active_save_id": "save:test-derived-visibility",
                "campaigns": [],
                "saves": [save_record],
            })
            onboarding = manager.start_or_continue(create_if_missing=False)
            self.assertTrue(onboarding["ok"], onboarding)
            scene_query = manager.player_query(kind="scene")
            self.assertTrue(scene_query["ok"], scene_query)

            artifact_blobs = {
                "snapshot_md": campaign.current_snapshot_path.read_text(encoding="utf-8"),
                "snapshot_json": campaign.current_snapshot_json_path.read_text(encoding="utf-8"),
                "cards_index": (campaign.cards_path / "INDEX.md").read_text(encoding="utf-8"),
                "onboarding": json.dumps(
                    {
                        "scene": onboarding["scene"],
                        "onboarding_text": onboarding["onboarding_text"],
                        "save": onboarding["save"],
                    },
                    ensure_ascii=False,
                ),
            }
            for path in sorted(campaign.cards_path.rglob("*.md")):
                if path.name == "INDEX.md":
                    continue
                artifact_blobs[f"card:{path.relative_to(campaign.cards_path).as_posix()}"] = path.read_text(
                    encoding="utf-8"
                )
            forbidden_tokens = {
                    "hidden_entity": [
                        HIDDEN_PROBE_TOKEN,
                        "item:test-hidden-context-probe",
                        HIDDEN_ID_SUBSTRING_TOKEN,
                        DETAIL_ONLY_PROBE_TOKEN,
                        ALPHA_HIDDEN_TOKEN,
                        LOWER_ALPHA_HIDDEN_TOKEN,
                        LOWER_ALPHA_HIDDEN_TOKEN.upper(),
                        MARKER_ALPHA_HIDDEN_TOKEN,
                        MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                        SHORT_MARKER_ALPHA_HIDDEN_TOKEN,
                        SHORT_MARKER_ALPHA_HIDDEN_TOKEN.upper(),
                        HIDDEN_DETAIL_KEY_TOKEN,
                        LOWER_HIDDEN_DETAIL_KEY_TOKEN,
                        LOWER_MARKER_KEY_TOKEN,
                        LOWER_MARKER_KEY_TOKEN.upper(),
                        SHORT_CJK_HIDDEN_TOKEN,
                        PUBLIC_NAME_SECRET_TOKEN,
                    ],
                "hidden_location": ["loc:test-hidden-derived-current"],
                "hidden_clock": ["clock:test-hidden-derived-clock"],
                "hidden_event": ["event:test-hidden-derived-artifact-probe"],
                "hidden_memory": ["memory:test-hidden-derived-artifact-probe"],
                "gm_only_entity": [GM_ONLY_PROBE_TOKEN, "item:test-gm-only-card-probe"],
                "gm_only_world_setting": [
                    WORLD_SETTING_SIDE_SECRET,
                    WORLD_SETTING_SIDE_ALPHA_SECRET,
                    "world:test-side-hidden-card",
                ],
                "gm_only_world_setting_alias": [WORLD_SETTING_SIDE_ALIAS],
            }
            for artifact, blob in artifact_blobs.items():
                for item_type, tokens in forbidden_tokens.items():
                    for token in tokens:
                        with self.subTest(artifact=artifact, item_type=item_type, token=token):
                            self.assertNotIn(token, blob)
            self.assertFalse((campaign.cards_path / "items" / "item__test-gm-only-card-probe.md").exists())
            self.assertFalse((campaign.cards_path / "world_settings" / "world__test-side-hidden-card.md").exists())
            self.assertNotIn(WORLD_SETTING_SIDE_SECRET, scene_query["text"])

    def test_missing_world_settings_table_world_setting_rows_are_player_hidden_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            secret = "缺表世界设定秘密"
            alias = "缺表设定别名"
            world_id = "world:test-missing-side-table-secret"
            with connect(campaign) as conn:
                apply_pending_migrations(conn)
                current_location = conn.execute("select value from meta where key='current_location_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": world_id,
                        "type": "world_setting",
                        "name": alias,
                        "visibility": "known",
                        "status": "active",
                        "summary": secret,
                        "aliases": [alias],
                        "details": {"truth": secret},
                    },
                )
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-missing-world-setting-carrier",
                        "type": "item",
                        "name": "缺表可见载体",
                        "visibility": "known",
                        "status": "active",
                        "location_id": current_location,
                        "summary": f"误带 {secret} {world_id} {alias}",
                        "details": {"secret": secret, "world_ref": f"X{world_id}Y", "alias": alias},
                    },
                )
                conn.execute("drop table world_settings")
                missing_table_entity = conn.execute("select * from entities where id = ?", (world_id,)).fetchone()
                direct_missing_table_player_render = render_world_setting_entity(conn, missing_table_entity)
                direct_missing_table_gm_render = render_world_setting_entity(conn, missing_table_entity, view="gm")
                conn.commit()
                report = ProjectionService(campaign, conn).refresh(
                    names=["search", "snapshots", "cards"],
                    dirty_only=False,
                    profile="test:missing_world_settings_redaction",
                )
                self.assertTrue(report.ok, report.errors)
                validation_errors: list[str] = []
                validate_search_projection(conn, validation_errors)
                self.assertEqual(validation_errors, [])
                rows = [dict(row) for row in conn.execute("select entity_id, title, body, tags from fts_index").fetchall()]
                fts_blob = json.dumps(rows, ensure_ascii=False)
                conn.commit()

            artifact_blobs = {
                "fts": fts_blob,
                "snapshot_md": campaign.current_snapshot_path.read_text(encoding="utf-8"),
                "snapshot_json": campaign.current_snapshot_json_path.read_text(encoding="utf-8"),
                "cards_index": (campaign.cards_path / "INDEX.md").read_text(encoding="utf-8"),
            }
            for path in sorted(campaign.cards_path.rglob("*.md")):
                if path.name == "INDEX.md":
                    continue
                artifact_blobs[f"card:{path.relative_to(campaign.cards_path).as_posix()}"] = path.read_text(
                    encoding="utf-8"
                )
            for artifact, blob in artifact_blobs.items():
                for token in (secret, world_id, f"X{world_id}Y", alias):
                    with self.subTest(artifact=artifact, token=token):
                        self.assertNotIn(token, blob)
            self.assertNotIn(secret, direct_missing_table_player_render)
            self.assertNotIn(world_id, direct_missing_table_player_render)
            self.assertNotIn(alias, direct_missing_table_player_render)
            self.assertIn(secret, direct_missing_table_gm_render)
            self.assertIn(world_id, direct_missing_table_gm_render)
            self.assertFalse((campaign.cards_path / "world_settings" / "world__test-missing-side-table-secret.md").exists())

    def test_snapshot_scene_overview_handles_exact_hidden_free_text_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                apply_pending_migrations(conn)
                install_hidden_context_probe(conn)
                current_location = conn.execute("select value from meta where key='current_location_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": "item:test-hidden-scene-overview-token",
                        "type": "item",
                        "name": "隐藏场景概览探针",
                        "visibility": "hidden",
                        "status": "active",
                        "summary": UNSTRUCTURED_HIDDEN_SUMMARY,
                        "details": {"overview": UNSTRUCTURED_HIDDEN_SUMMARY},
                    },
                )
                conn.execute(
                    "update locations set description_short = ? where entity_id = ?",
                    (UNSTRUCTURED_HIDDEN_SUMMARY, current_location),
                )
                conn.commit()

                report = ProjectionService(campaign, conn).refresh(
                    names=["snapshots"],
                    dirty_only=False,
                    profile="test:scene_overview_exact_hidden_redaction",
                )
                self.assertTrue(report.ok, report.errors)
                snapshot_md = campaign.current_snapshot_path.read_text(encoding="utf-8")
                snapshot_json = campaign.current_snapshot_json_path.read_text(encoding="utf-8")

            self.assertNotIn(UNSTRUCTURED_HIDDEN_SUMMARY, snapshot_md)
            self.assertNotIn(UNSTRUCTURED_HIDDEN_SUMMARY, snapshot_json)
            self.assertIn("[hidden]", snapshot_md)

    def test_player_scene_affordances_redact_hidden_material_in_route_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                apply_pending_migrations(conn)
                install_hidden_context_probe(conn)
                current_location = conn.execute("select value from meta where key='current_location_id'").fetchone()[0]
                upsert_entity(
                    conn,
                    {
                        "id": "loc:test-visible-route-hidden-name",
                        "type": "location",
                        "name": f"可见去处{HIDDEN_PROBE_TOKEN}",
                        "visibility": "known",
                        "status": "active",
                        "summary": "可见目的地摘要",
                    },
                )
                conn.execute(
                    "insert into locations(entity_id, description_short) values(?, ?) "
                    "on conflict(entity_id) do update set description_short=excluded.description_short",
                    ("loc:test-visible-route-hidden-name", "可见目的地描述"),
                )
                conn.execute(
                    """
                    insert or replace into routes
                    (id, from_location_id, to_location_id, travel_minutes, difficulty,
                     hazards_json, requirements_json, last_verified_turn_id)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "route:test-hidden-name-affordance",
                        current_location,
                        "loc:test-visible-route-hidden-name",
                        5,
                        "normal",
                        "[]",
                        "[]",
                        "turn:000044",
                    ),
                )
                conn.commit()

            runtime = GMRuntime.from_path(save)
            scene = runtime.query("scene", view="player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, scene.text)
            self.assertNotIn(f"可见去处{HIDDEN_PROBE_TOKEN}", scene.text)

    def test_save_patch_accepts_gm_only_visibility_and_player_artifacts_exclude_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                apply_pending_migrations(conn)
                row = conn.execute(
                    """
                    select id
                    from entities
                    where type = 'item'
                      and status = 'active'
                      and visibility in ('known', 'hinted')
                    order by id
                    limit 1
                    """
                ).fetchone()
                self.assertIsNotNone(row)
                entity_id = str(row["id"])
                conn.commit()

            result = apply_save_patch(
                campaign,
                {
                    "patch_schema_version": "1",
                    "reason": "test gm-only visibility label",
                    "operations": [
                        {
                            "op": "set_entity_visibility",
                            "entity_id": entity_id,
                            "visibility": "gm",
                        }
                    ],
                },
                backup=False,
            )
            self.assertTrue(result.ok, result.errors)

            runtime = GMRuntime.from_path(save)
            player = runtime.query("entity", entity_id, view="player")
            gm = runtime.query("entity", entity_id, view="gm")
            self.assertNotIn(entity_id, player.text)
            self.assertIn(entity_id, gm.text)

    def test_player_safe_context_excludes_hidden_probe_while_gm_context_can_read_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save = copy_current_packages(tmp)
            campaign = load_campaign(save)
            with connect(campaign) as conn:
                oracle_token = "玄穹秘钥无公开项"
                absent_context = build_context(
                    campaign,
                    conn,
                    user_text=oracle_token,
                    mode="query",
                    submode="context",
                    view="player",
                    budget=500,
                )
                install_hidden_context_probe(conn)
                conn.execute(
                    "update entities set summary='' where id='item:test-hidden-context-probe'"
                )
                conn.execute(
                    "insert into aliases(alias, entity_id, kind) values (?, ?, 'name')",
                    (oracle_token, "item:test-hidden-context-probe"),
                )
                conn.commit()

                hidden_only_context = build_context(
                    campaign,
                    conn,
                    user_text=oracle_token,
                    mode="query",
                    submode="context",
                    view="player",
                    budget=500,
                )

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
                gm_quality = gm_context.completeness["quality_diagnostics"]
                maintenance_quality = maintenance_context.completeness["quality_diagnostics"]
                player_quality = player_context.completeness["quality_diagnostics"]
                player_after_gm_quality = player_after_gm_context.completeness["quality_diagnostics"]
                absent_quality = absent_context.completeness["quality_diagnostics"]
                hidden_only_quality = hidden_only_context.completeness["quality_diagnostics"]
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
            self.assertTrue(
                any(
                    item.get("code") == "missing_summary"
                    and item.get("subject_id") == "item:test-hidden-context-probe"
                    for item in gm_quality
                ),
                gm_quality,
            )
            self.assertTrue(
                any(
                    item.get("code") == "missing_summary"
                    and item.get("subject_id") == "item:test-hidden-context-probe"
                    for item in maintenance_quality
                ),
                maintenance_quality,
            )

            self.assertEqual(player_after_gm_context.contract["visibility_mode"], "player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_after_gm_json)
            self.assertEqual(player_context.contract["visibility_mode"], "player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_json)
            self.assertNotIn("event:test-hidden-context-probe", player_loaded_ids)
            self.assertNotIn("memory:test-hidden-context-probe", player_loaded_ids)
            self.assertNotIn("disc:test-hidden-context-probe", player_json)
            self.assertNotIn("disc:test-hidden-subject-context-probe", player_json)
            self.assertNotIn("world:test-hidden-context-probe", player_json)
            player_quality_blob = json.dumps(
                [player_after_gm_quality, player_quality],
                ensure_ascii=False,
                sort_keys=True,
            )
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_quality_blob)
            self.assertNotIn("item:test-hidden-context-probe", player_quality_blob)
            self.assertNotIn("rel:test-hidden-context-probe", player_quality_blob)
            self.assertNotIn("world:test-hidden-context-probe", player_quality_blob)
            player_high_value_blob = json.dumps(
                [
                    item
                    for item in player_context.completeness["missing_signal_evidence"]
                    if item.get("code") in {
                        "high_value_budget_omission",
                        "required_budget_overflow",
                    }
                ],
                ensure_ascii=False,
                sort_keys=True,
            )
            self.assertNotIn(HIDDEN_PROBE_TOKEN, player_high_value_blob)
            self.assertNotIn("item:test-hidden-context-probe", player_high_value_blob)
            absent_high_value = [
                item
                for item in absent_context.completeness["missing_signal_evidence"]
                if item.get("code") in {
                    "high_value_budget_omission",
                    "required_budget_overflow",
                }
            ]
            hidden_only_high_value = [
                item
                for item in hidden_only_context.completeness["missing_signal_evidence"]
                if item.get("code") in {
                    "high_value_budget_omission",
                    "required_budget_overflow",
                }
            ]
            self.assertTrue(absent_high_value, absent_context.completeness)
            self.assertEqual(hidden_only_quality, absent_quality)
            self.assertEqual(hidden_only_high_value, absent_high_value)
            self.assertEqual(audit_payload_after_gm["contract"]["visibility_mode"], "player")
            self.assertEqual(audit_payload_after_maintenance["contract"]["visibility_mode"], "player")
            self.assertNotIn(HIDDEN_PROBE_TOKEN, json.dumps(audit_payload_after_gm, ensure_ascii=False))
            self.assertNotIn(HIDDEN_PROBE_TOKEN, json.dumps(audit_payload_after_maintenance, ensure_ascii=False))
            self.assertNotIn(
                "item:test-hidden-context-probe",
                json.dumps(audit_payload_after_maintenance["completeness"]["quality_diagnostics"], ensure_ascii=False),
            )
            invariants = {
                item["source"]: item
                for item in player_context.contract.get("visibility_invariants", [])
                if isinstance(item, dict)
            }
            self.assertEqual(invariants["events"]["structured_visibility"], "not_applicable")
            self.assertEqual(invariants["memory_summaries"]["structured_visibility"], "visibility_mode_metadata")

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
                conn.execute(
                    """
                    update memory_summaries
                    set summary_type='deterministic_world',
                        visibility_mode='player',
                        freshness_status='fresh',
                        freshness_turn_id=?,
                        stale_reason='',
                        freshness_evidence_json=?,
                        derived_authority_json=?
                    where title like ?
                    """,
                    (
                        current_turn,
                        json.dumps(
                            {
                                "current_turn_id": current_turn,
                                "valid_from_turn": current_turn,
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps({"authority": "derived_context", "fact_authority": False}),
                        f"%{target}%",
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
