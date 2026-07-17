from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from rpg_engine.ai.schema_validation import validate_with_jsonschema
from rpg_engine.campaign import load_campaign
from rpg_engine.content_types.core import validate_clock_record
from rpg_engine.db import connect, upsert_clock
from rpg_engine.delta_schema import load_schema_text, validate_delta_schema
from rpg_engine.progress_access import (
    ProgressRecord,
    list_progress,
    read_progress,
    validate_delta_progress_references,
)
from rpg_engine.preview import recipe_tick_clocks
from rpg_engine.save_service import init_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


class ProgressAccessContractTests(unittest.TestCase):
    def test_read_progress_exposes_stable_fields_and_filters_player_hidden_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_clock(
                    conn,
                    {
                        "id": "clock:storm",
                        "name": "Storm Front",
                        "summary": "The storm is closing in.",
                        "clock_type": "threat",
                        "segments_total": 6,
                        "segments_filled": 2,
                        "visibility": "visible",
                        "trigger_when_full": "The storm reaches camp.",
                        "tick_rules": {"on": "travel delay", "scope": ["loc:camp"]},
                        "last_ticked_turn_id": "turn:seed",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-side",
                        "name": "Hidden Side Clock",
                        "summary": "Hidden side-table clock.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "Hidden consequence.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden-entity",
                        "name": "Hidden Entity Clock",
                        "summary": "Hidden entity clock.",
                        "clock_type": "phase",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "Hidden phase.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:archived",
                        "name": "Archived Clock",
                        "summary": "Archived clock.",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 4,
                        "visibility": "visible",
                        "trigger_when_full": "Already resolved.",
                    },
                )
                conn.execute("update entities set visibility = 'hidden' where id = 'clock:hidden-entity'")
                conn.execute("update entities set status = 'archived' where id = 'clock:archived'")
                conn.execute("update entities set details_json = ? where id = 'clock:storm'", ('{"scope":["loc:camp"]}',))
                conn.commit()

                progress = read_progress(conn, "clock:storm")
                self.assertIsInstance(progress, ProgressRecord)
                assert progress is not None
                self.assertEqual(progress.id, "clock:storm")
                self.assertEqual(progress.kind, "threat")
                self.assertEqual(progress.clock_type, "threat")
                self.assertEqual(progress.scope, ["loc:camp"])
                self.assertEqual(progress.segments_total, 6)
                self.assertEqual(progress.segments_filled, 2)
                self.assertEqual(progress.visibility, "visible")
                self.assertEqual(progress.status, "active")
                self.assertEqual(progress.summary, "The storm is closing in.")
                self.assertEqual(progress.trigger_when_full, "The storm reaches camp.")
                self.assertEqual(progress.tick_rules["on"], "travel delay")
                self.assertEqual(progress.details["scope"], ["loc:camp"])
                self.assertEqual(progress.last_ticked_turn_id, "turn:seed")
                self.assertEqual(progress.updated_turn_id, "turn:seed")
                self.assertRegex(progress.updated_at, r"^\d{4}-\d{2}-\d{2}T")
                self.assertEqual(progress.to_dict()["segments_filled"], 2)

                player_ids = {item.id for item in list_progress(conn, view="player")}
                self.assertIn("clock:storm", player_ids)
                self.assertNotIn("clock:hidden-side", player_ids)
                self.assertNotIn("clock:hidden-entity", player_ids)
                self.assertNotIn("clock:archived", player_ids)
                self.assertIsNone(read_progress(conn, "clock:hidden-side", view="player"))
                self.assertIsNone(read_progress(conn, "clock:hidden-entity", view="player"))
                self.assertIsNone(read_progress(conn, "clock:archived", view="player"))

                maintenance_ids = {item.id for item in list_progress(conn, view="maintenance", include_archived=True)}
                self.assertIn("clock:hidden-side", maintenance_ids)
                self.assertIn("clock:hidden-entity", maintenance_ids)
                self.assertIn("clock:archived", maintenance_ids)
                hidden = read_progress(conn, "clock:hidden-side", view="maintenance")
                self.assertIsNotNone(hidden)
                assert hidden is not None
                self.assertEqual(hidden.visibility, "hidden")
                hidden_entity = read_progress(conn, "clock:hidden-entity", view="maintenance")
                self.assertIsNotNone(hidden_entity)
                assert hidden_entity is not None
                self.assertEqual(hidden_entity.visibility, "hidden")

                self.assertEqual(list_progress(conn, limit=0), [])
                self.assertEqual(list_progress(conn, limit=-1), [])
                with self.assertRaisesRegex(ValueError, "limit must be an integer"):
                    list_progress(conn, limit=True)  # type: ignore[arg-type]
                with self.assertRaisesRegex(ValueError, "kinds must be string or sequence of strings"):
                    list_progress(conn, kinds=123)  # type: ignore[arg-type]

    def test_delta_progress_validation_handles_visibility_archival_and_reason_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_dir = Path(tmp) / "save"
            init_v1_save(MINIMAL_FIXTURE, save_dir, force=True)
            campaign = load_campaign(save_dir)
            with connect(campaign) as conn:
                upsert_clock(
                    conn,
                    {
                        "id": "clock:visible",
                        "name": "Visible Clock",
                        "summary": "Visible clock.",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "Done.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:hidden",
                        "name": "Hidden Clock",
                        "summary": "Hidden clock.",
                        "clock_type": "threat",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "hidden",
                        "trigger_when_full": "Hidden done.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:chapter:1",
                        "name": "Chapter Clock",
                        "summary": "Clock id using the existing broad clock: prefix contract.",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "Chapter done.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:a",
                        "name": "A",
                        "summary": "Short clock name.",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "Short done.",
                    },
                )
                upsert_clock(
                    conn,
                    {
                        "id": "clock:archived",
                        "name": "Archived Clock",
                        "summary": "Archived clock.",
                        "clock_type": "project",
                        "segments_total": 4,
                        "segments_filled": 1,
                        "visibility": "visible",
                        "trigger_when_full": "Archived done.",
                    },
                )
                conn.execute("update entities set status = 'archived' where id = 'clock:archived'")
                conn.commit()

                valid_delta = {
                    "user_text": "advance clock",
                    "intent": "clock",
                    "summary": "Clock advanced.",
                    "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                    "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": "Travel took longer."}],
                }
                self.assertEqual(validate_delta_progress_references(conn, valid_delta), [])
                self.assertEqual(validate_delta_progress_references(conn, valid_delta, view="player"), [])
                self.assertEqual(validate_delta_schema(valid_delta, conn), [])
                self.assertEqual(
                    validate_delta_schema(
                        {
                            **valid_delta,
                            "tick_clocks": [{"id": "clock:chapter:1", "delta": 1, "reason": "Chapter pressure."}],
                        },
                        conn,
                    ),
                    [],
                )

                invalid_delta = {
                    "user_text": "advance bad clocks",
                    "intent": "clock",
                    "summary": "Bad clock changes.",
                    "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                    "tick_clocks": [
                        "bad",
                        {"id": "", "delta": 1},
                        {"id": " clock:visible ", "delta": 1},
                        {"id": 0, "delta": 1},
                        {"id": "bad", "delta": 1},
                        {"id": "clock:bad space", "delta": 1},
                        {"id": "clock:missing", "delta": 1},
                        {"id": "clock:archived", "delta": 1},
                        {"id": "clock:visible", "delta": 0},
                        {"id": "clock:visible", "delta": True},
                        {"id": "clock:visible", "delta": 1, "reason": ""},
                        {"id": "clock:visible", "delta": 1, "reason": "\u200b"},
                        {"id": "clock:visible", "delta": 1, "reason": "\u0001"},
                        {"id": "clock:visible", "delta": 1, "reason": "ok\u0001"},
                        {"id": "clock:visible", "delta": 1, "reason": "\u0080"},
                        {"id": "clock:visible", "delta": 1, "reason": "\ufe0f"},
                        {"id": "clock:visible", "delta": 1, "reason": "\U000e0061"},
                        {"id": "clock:visible", "delta": 1, "reason": "\u00b4"},
                    ],
                }
                errors = validate_delta_progress_references(conn, invalid_delta)
                self.assertIn("$.tick_clocks[0]: must be object", errors)
                self.assertIn("$.tick_clocks[1].id: must be non-empty string", errors)
                self.assertIn("$.tick_clocks[2].id: must not contain leading or trailing whitespace", errors)
                self.assertIn("$.tick_clocks[3].id: must be non-empty string", errors)
                self.assertIn("$.tick_clocks[4].id: invalid clock id", errors)
                self.assertIn("$.tick_clocks[5].id: invalid clock id", errors)
                self.assertIn("$.tick_clocks[6].id: Missing clock clock:missing", errors)
                self.assertIn("$.tick_clocks[7].id: archived clock clock:archived", errors)
                self.assertIn("$.tick_clocks[8].delta: must be non-zero integer", errors)
                self.assertIn("$.tick_clocks[9].delta: must be non-zero integer", errors)
                self.assertIn("$.tick_clocks[10].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[11].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[12].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[13].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[14].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[15].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[16].reason: must be non-empty string when present", errors)
                self.assertIn("$.tick_clocks[17].reason: must be non-empty string when present", errors)
                for bad_reason in ("\u0600", "\u2017", "\u203e", "\u2adc", "\ufe49", "\ufe4c", "\uffe3"):
                    with self.subTest(bad_reason=bad_reason.encode("unicode_escape").decode()):
                        bad_reason_errors = validate_delta_progress_references(
                            conn,
                            {
                                "user_text": "advance bad reason",
                                "intent": "clock",
                                "summary": "Bad reason.",
                                "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                                "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": bad_reason}],
                            },
                        )
                        self.assertIn("$.tick_clocks[0].reason: must be non-empty string when present", bad_reason_errors)

                player_errors = validate_delta_progress_references(
                    conn,
                    {
                        "user_text": "advance hidden",
                        "intent": "clock",
                        "summary": "Hidden progress.",
                        "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                        "tick_clocks": [{"id": "clock:hidden", "delta": 1, "reason": "Hidden pressure."}],
                    },
                    view="player",
                )
                self.assertIn("$.tick_clocks[0].id: unavailable clock clock:hidden", player_errors)
                player_schema_errors = validate_delta_schema(
                    {
                        "user_text": "advance hidden",
                        "intent": "clock",
                        "summary": "Hidden progress.",
                        "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                        "tick_clocks": [{"id": "clock:hidden", "delta": 1, "reason": "Hidden pressure."}],
                    },
                    conn,
                    caller_view="player",
                )
                self.assertIn("$.tick_clocks[0].id: unavailable clock clock:hidden", player_schema_errors)

                no_event_errors = validate_delta_schema(
                    {
                        "user_text": "advance clock",
                        "intent": "clock",
                        "summary": "Clock advanced.",
                        "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": "Travel took longer."}],
                    },
                    conn,
                )
                self.assertIn("$: state-changing delta should include at least one event explaining the change", no_event_errors)

                narrative_only_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "clock_tick",
                                "title": "Clock",
                                "summary": "The clock advances.",
                                "payload": {"clock_id": "clock:visible", "delta": 1},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", narrative_only_errors)
                generic_payload_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Clock",
                                "summary": "Progress changed.",
                                "payload": {"id": "clock:visible", "delta": 1},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", generic_payload_errors)
                mismatched_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim wrong progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Different clock",
                                "summary": "clock:missing advances.",
                                "source": "test",
                            }
                        ],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": "Visible pressure."}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", mismatched_event_errors)
                completed_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible completed.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", completed_event_errors)
                fraction_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible is now 2/4.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", fraction_event_errors)
                chinese_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible 推进一格。", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", chinese_event_errors)
                plain_text_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "The clock advances.", "source": "test"}],
                    },
                    conn,
                )
                self.assertNotIn("$.events[0]: progress update event requires structured tick_clocks", plain_text_event_errors)
                top_level_split_verb_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "clock:visible ad\u200bvances one segment.",
                        "events": [{"type": "note", "title": "Observation", "summary": "No structured tick.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$: progress update narrative requires structured tick_clocks", top_level_split_verb_errors)
                top_level_format_split_verb_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "clock:visible ad\u0600vances one segment.",
                        "events": [{"type": "note", "title": "Observation", "summary": "No structured tick.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$: progress update narrative requires structured tick_clocks", top_level_format_split_verb_errors)
                progress_alias_mismatch_errors = validate_delta_schema(
                    {
                        "user_text": "claim wrong progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Progress",
                                "summary": "progress:quest-a advances.",
                                "source": "test",
                            }
                        ],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": "Visible pressure."}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", progress_alias_mismatch_errors)
                punctuated_clock_id_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Clock",
                                "summary": "clock:visible. completed.",
                                "source": "test",
                            }
                        ],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": "Visible pressure."}],
                    },
                    conn,
                )
                self.assertNotIn("$.events[0]: progress update event requires structured tick_clocks", punctuated_clock_id_errors)
                top_level_claim_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "clock:visible advanced one segment.",
                        "events": [{"type": "note", "title": "Observation", "summary": "No structured tick.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$: progress update narrative requires structured tick_clocks", top_level_claim_errors)
                clock_name_claim_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Visible Clock", "summary": "The clock advances.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", clock_name_claim_errors)
                short_clock_name_errors = validate_delta_schema(
                    {
                        "user_text": "observe lever",
                        "intent": "observe",
                        "summary": "Lever changed.",
                        "events": [{"type": "note", "title": "Lever", "summary": "A lever changed position.", "source": "test"}],
                    },
                    conn,
                )
                self.assertNotIn("$.events[0]: progress update event requires structured tick_clocks", short_clock_name_errors)
                nested_payload_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"state_changes": ["clock:visible advances one segment"]},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", nested_payload_errors)
                nested_payload_array_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Array payload only.",
                                "payload": ["clock:visible advances one segment"],
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", nested_payload_array_errors)
                nested_payload_name_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"state_changes": ["Visible Clock advances one segment"]},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", nested_payload_name_errors)
                nested_payload_structured_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"state": {"clock_id": "clock:visible", "delta": 1}},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", nested_payload_structured_errors)
                nested_payload_structured_array_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"state_changes": [{"id": "clock:visible", "delta": 1}]},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", nested_payload_structured_array_errors)
                payload_key_claim_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"clock:visible": {"delta": 1}},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", payload_key_claim_errors)
                split_sibling_payload_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"state": {"clock_id": "clock:visible"}, "change": {"delta": 1}},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", split_sibling_payload_errors)
                segments_payload_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"clock_id": "clock:visible", "segments_filled": 2},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", segments_payload_errors)
                status_payload_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [
                            {
                                "type": "note",
                                "title": "Observation",
                                "summary": "Nested payload only.",
                                "payload": {"clock_id": "clock:visible", "status": "completed"},
                                "source": "test",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", status_payload_errors)
                for payload in ({"progress": "advanced"}, {"segments_filled": 2}, {"status": "completed"}):
                    with self.subTest(payload=payload):
                        progress_key_errors = validate_delta_schema(
                            {
                                "user_text": "claim progress",
                                "intent": "clock",
                                "summary": "Progress claimed.",
                                "events": [
                                    {
                                        "type": "note",
                                        "title": "Observation",
                                        "summary": "Progress payload only.",
                                        "payload": payload,
                                        "source": "test",
                                    }
                                ],
                            },
                            conn,
                        )
                        self.assertIn("$.events[0]: progress update event requires structured tick_clocks", progress_key_errors)
                escalated_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible escalates.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", escalated_event_errors)
                resolved_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible resolved.", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", resolved_event_errors)
                chinese_rise_event_errors = validate_delta_schema(
                    {
                        "user_text": "claim progress",
                        "intent": "clock",
                        "summary": "Progress claimed.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible 上升一段。", "source": "test"}],
                    },
                    conn,
                )
                self.assertIn("$.events[0]: progress update event requires structured tick_clocks", chinese_rise_event_errors)
                clock_upsert_errors = validate_delta_schema(
                    {
                        "user_text": "archive clock",
                        "intent": "clock",
                        "summary": "Clock mutated.",
                        "events": [{"type": "note", "title": "Clock", "summary": "Clock changed.", "source": "test"}],
                        "upsert_entities": [
                            {
                                "id": "clock:visible",
                                "type": "clock",
                                "name": "Visible Clock",
                                "summary": "Archived.",
                                "status": "archived",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.upsert_entities[0].type: clock entities must be mutated through tick_clocks", clock_upsert_errors)
                disguised_clock_upsert_errors = validate_delta_schema(
                    {
                        "user_text": "archive clock",
                        "intent": "clock",
                        "summary": "Clock mutated.",
                        "events": [{"type": "note", "title": "Clock", "summary": "Clock changed.", "source": "test"}],
                        "upsert_entities": [
                            {
                                "id": "clock:visible",
                                "type": "project",
                                "name": "Visible Clock",
                                "summary": "Archived.",
                                "status": "archived",
                            }
                        ],
                    },
                    conn,
                )
                self.assertIn("$.upsert_entities[0].id: clock entities must be mutated through tick_clocks", disguised_clock_upsert_errors)
                unexplained_tick_errors = validate_delta_schema(
                    {
                        "user_text": "advance clock",
                        "intent": "clock",
                        "summary": "Clock advanced.",
                        "events": [{"type": "note", "title": "Looked around", "summary": "The scene stayed quiet.", "source": "test"}],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1}],
                    },
                    conn,
                )
                self.assertIn("$.tick_clocks[0].reason: required when no event explains this clock tick", unexplained_tick_errors)
                missing_reason_errors = validate_delta_schema(
                    {
                        "user_text": "advance clock",
                        "intent": "clock",
                        "summary": "Clock advanced.",
                        "events": [{"type": "note", "title": "Clock", "summary": "clock:visible advances.", "source": "test"}],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1}],
                    },
                    conn,
                )
                self.assertIn("$.tick_clocks[0].reason: required", missing_reason_errors)
                generic_event_tick_errors = validate_delta_schema(
                    {
                        "user_text": "advance clock",
                        "intent": "clock",
                        "summary": "Clock advanced.",
                        "events": [{"type": "clock_tick", "title": "Progress", "summary": "Progress changed.", "source": "test"}],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1}],
                    },
                    conn,
                )
                self.assertIn("$.tick_clocks[0].reason: required when no event explains this clock tick", generic_event_tick_errors)
                invisible_event_errors = validate_delta_schema(
                    {
                        "user_text": "advance clock",
                        "intent": "clock",
                        "summary": "Clock advanced.",
                        "events": [{"type": "\u200b", "title": "\u200b", "summary": "\u200b", "source": "\u200b"}],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": "Visible reason."}],
                    },
                    conn,
                )
                self.assertIn("$.events[0].type: must be non-empty string", invisible_event_errors)
                self.assertIn("$.events[0].title: must be non-empty string", invisible_event_errors)
                self.assertIn("$.events[0].summary: must be non-empty string", invisible_event_errors)
                self.assertIn("$.events[0].source: must be non-empty string", invisible_event_errors)

    def test_clock_id_contract_is_consistent_for_content_runtime_and_schema(self) -> None:
        self.assertEqual(
            validate_clock_record(
                {
                    "id": "clock:valid:phase",
                    "name": "Valid Phase",
                    "segments_total": 4,
                    "trigger_when_full": "Done.",
                }
            ),
            [],
        )
        self.assertIn(
            "id: invalid clock id",
            validate_clock_record(
                {
                    "id": "clock:quest+1",
                    "name": "Bad Clock",
                    "segments_total": 4,
                    "trigger_when_full": "Done.",
                }
            ),
        )
        schema = json.loads(load_schema_text())
        jsonschema_errors = validate_with_jsonschema(
            schema,
            {
                "user_text": "advance clock",
                "intent": "clock",
                "summary": "Clock advanced.",
                "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                "tick_clocks": [
                    {"id": "clock:bad space", "delta": 1, "reason": "   "},
                    {"id": "clock:\u200b", "delta": 1, "reason": "\u200b"},
                    {"id": "clock:quest+1", "delta": 1, "reason": "ok\u0001"},
                    {"id": "clock:visible", "delta": 1, "reason": "\u0080"},
                    {"id": "clock:visible", "delta": 1, "reason": "\ufe0f"},
                    {"id": "clock:visible", "delta": 1, "reason": "\U000e0061"},
                    {"id": "clock:visible", "delta": 1, "reason": "\u00b4"},
                ],
            },
        )
        self.assertTrue(any("$.tick_clocks[0].id" in item for item in jsonschema_errors), jsonschema_errors)
        self.assertTrue(any("$.tick_clocks[0].reason" in item for item in jsonschema_errors), jsonschema_errors)
        self.assertTrue(any("$.tick_clocks[2].id" in item for item in jsonschema_errors), jsonschema_errors)
        self.assertTrue(any("$.tick_clocks[2].reason" in item for item in jsonschema_errors), jsonschema_errors)
        self.assertTrue(any("$.tick_clocks[3].reason" in item for item in jsonschema_errors), jsonschema_errors)
        self.assertTrue(any("$.tick_clocks[4].reason" in item for item in jsonschema_errors), jsonschema_errors)
        for bad_reason in ("\U000e0061", "\u00b4", "\u0600", "\u2017", "\u203e", "\u2adc", "\ufe49", "\ufe4c", "\uffe3"):
            with self.subTest(bad_reason=bad_reason.encode("unicode_escape").decode()):
                single_reason_errors = validate_with_jsonschema(
                    schema,
                    {
                        "user_text": "advance clock",
                        "intent": "clock",
                        "summary": "Clock advanced.",
                        "events": [{"type": "test", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
                        "tick_clocks": [{"id": "clock:visible", "delta": 1, "reason": bad_reason}],
                    },
                )
                self.assertTrue(any("$.tick_clocks[0].reason" in item for item in single_reason_errors), single_reason_errors)
        event_schema_errors = validate_with_jsonschema(
            schema,
            {
                "user_text": "advance clock",
                "intent": "clock",
                "summary": "Clock advanced.",
                "events": [{"type": "\u200b", "title": "Clock", "summary": "Progress changed.", "source": "test"}],
            },
        )
        self.assertTrue(any("$.events[0].type" in item for item in event_schema_errors), event_schema_errors)
        clock_upsert_schema_errors = validate_with_jsonschema(
            schema,
            {
                "user_text": "archive clock",
                "intent": "clock",
                "summary": "Clock mutated.",
                "events": [{"type": "test", "title": "Clock", "summary": "Clock changed.", "source": "test"}],
                "upsert_entities": [{"id": "clock:visible", "type": "clock", "name": "Visible Clock", "summary": "Archived."}],
            },
        )
        self.assertTrue(any("$.upsert_entities[0]" in item for item in clock_upsert_schema_errors), clock_upsert_schema_errors)
        disguised_clock_schema_errors = validate_with_jsonschema(
            schema,
            {
                "user_text": "archive clock",
                "intent": "clock",
                "summary": "Clock mutated.",
                "events": [{"type": "test", "title": "Clock", "summary": "Clock changed.", "source": "test"}],
                "upsert_entities": [{"id": "clock:visible", "type": "project", "name": "Visible Clock", "summary": "Archived."}],
            },
        )
        self.assertTrue(any("$.upsert_entities[0]" in item for item in disguised_clock_schema_errors), disguised_clock_schema_errors)

    def test_progress_payload_scan_fails_closed_on_excessive_depth_or_cycle(self) -> None:
        payload: dict[str, object] = {"progress_id": "progress:quest", "delta": 1}
        for _ in range(66):
            payload = {"nested": payload}
        deep_errors = validate_delta_schema(
            {
                "user_text": "claim progress",
                "intent": "clock",
                "summary": "Progress claimed.",
                "events": [
                    {
                        "type": "note",
                        "title": "Progress",
                        "summary": "Progress was reviewed.",
                        "payload": payload,
                        "source": "test",
                    }
                ],
            }
        )
        self.assertIn("$.events[0].payload: nesting exceeds validation limit", deep_errors)

        cycle: dict[str, object] = {}
        cycle["self"] = cycle
        cyclic_errors = validate_delta_schema(
            {
                "user_text": "review progress",
                "intent": "clock",
                "summary": "Progress reviewed.",
                "events": [
                    {
                        "type": "note",
                        "title": "Progress",
                        "summary": "Progress was reviewed.",
                        "payload": cycle,
                        "source": "test",
                    }
                ],
            }
        )
        self.assertIn("$.events[0].payload: cyclic container is not allowed", cyclic_errors)

    def test_recipe_tick_clocks_preserves_reason_without_bool_delta_coercion(self) -> None:
        self.assertEqual(
            recipe_tick_clocks(
                {
                    "suggested_clock_ticks": [
                        {"id": "clock:craft", "delta": 1, "reason": "Crafting takes time."},
                        {"id": "clock:bad", "delta": True, "reason": "Bool should not become one."},
                    ]
                }
            ),
            [{"id": "clock:craft", "delta": 1, "reason": "Crafting takes time."}],
        )


if __name__ == "__main__":
    unittest.main()
