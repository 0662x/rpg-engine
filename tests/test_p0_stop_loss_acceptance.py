from __future__ import annotations

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from rpg_engine.campaign import Campaign, load_campaign
from rpg_engine.cards import write_cards
from rpg_engine.db import connect, init_database, upsert_entity
from rpg_engine.memory import find_relevant_memories, rebuild_memory_summaries
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_archive import export_save
from rpg_engine.save_service import init_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
OFFICIAL_EXAMPLE = ENGINE_ROOT / "examples" / "v1_minimal_adventure"
SMALL_CN_EXAMPLE = ENGINE_ROOT / "examples" / "small_cn_campaign"


def copy_initialized_campaign(tmp: str | Path, source: Path) -> Path:
    target = Path(tmp) / "campaign"
    shutil.copytree(source, target)
    init_database(load_campaign(target), force=True)
    return target


def upsert_hidden_character(campaign: Campaign) -> None:
    with connect(campaign) as conn:
        upsert_entity(
            conn,
            {
                "id": "npc:hidden-reviewer",
                "type": "character",
                "name": "隐藏审查员",
                "status": "active",
                "visibility": "hidden",
                "summary": "这个角色只能出现在维护视角。",
                "character": {
                    "role": "secret reviewer",
                    "attitude": "watching",
                    "trust": 0,
                    "health_state": "unknown",
                    "goals": ["确认 hidden 派生物不会进入玩家可读文件"],
                    "knowledge": {"secret": "player export must not include this"},
                },
            },
        )
        conn.commit()


def external_source_content_paths(content: dict[str, object]) -> dict[str, object]:
    def convert(value: object) -> object:
        if isinstance(value, str):
            return (Path("../source") / value).as_posix()
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return {key: convert(value) for key, value in content.items()}


class P0StopLossAcceptanceTests(unittest.TestCase):
    def test_original_patrol_text_routes_to_routine_without_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GMRuntime.from_path(copy_initialized_campaign(tmp, OFFICIAL_EXAMPLE))

            result = runtime.preview_from_text("巡视领地，看看大家都在做什么").to_dict()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["action"], "routine")
        self.assertEqual(result["status"], "ready")
        self.assertTrue(result["ready_to_save"])

    def test_campaign_content_files_reject_absolute_and_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaign"
            root.mkdir()
            for unsafe in ("/tmp/outside.yaml", "../outside.yaml"):
                campaign = Campaign(root=root, config={"id": "p0", "content": {"characters": [unsafe]}})
                with self.subTest(unsafe=unsafe):
                    with self.assertRaises(ValueError):
                        campaign.content_files("characters")

    def test_save_package_can_read_content_from_declared_source_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            save_dir = root / "save"
            shutil.copytree(SMALL_CN_EXAMPLE, source)
            init_v1_save(source, save_dir)

            source_config = yaml.safe_load((source / "campaign.yaml").read_text(encoding="utf-8"))
            save_config_path = save_dir / "campaign.yaml"
            save_config = yaml.safe_load(save_config_path.read_text(encoding="utf-8"))
            save_config["content"] = external_source_content_paths(source_config["content"])
            save_config_path.write_text(yaml.safe_dump(save_config, allow_unicode=True, sort_keys=False), encoding="utf-8")

            campaign = load_campaign(save_dir)
            palette_files = campaign.content_files("palettes")
            start = GMRuntime(campaign).start_turn("在营地附近找草药")

        self.assertTrue(palette_files)
        self.assertTrue(all(source.resolve() in path.resolve().parents for path in palette_files))
        self.assertEqual(start.mode, "action")
        self.assertEqual(start.submode, "gather")
        self.assertIn("palette_candidates", start.context.sections if start.context else {})

    def test_turn_proposal_cannot_be_replayed_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GMRuntime.from_path(copy_initialized_campaign(tmp, OFFICIAL_EXAMPLE))
            options = {"table": "table:bridge-risk", "reason": "P0 replay acceptance"}
            preview = runtime.preview_action("random_table", options).to_dict()
            self.assertTrue(preview["ready_to_save"], preview)

            delta = preview["delta_draft"]
            proposal = preview["turn_proposal"]
            first = runtime.commit_turn(
                delta,
                turn_proposal=proposal,
                action="random_table",
                action_options=options,
                state_audit=False,
                backup=False,
            ).to_dict()
            self.assertTrue(first["ok"], first)

            with self.assertRaises(ValueError):
                runtime.commit_turn(
                    delta,
                    turn_proposal=proposal,
                    action="random_table",
                    action_options=options,
                    state_audit=False,
                    backup=False,
                )

    def test_hidden_entities_do_not_generate_player_readable_cards_or_export_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_initialized_campaign(tmp, MINIMAL_FIXTURE)
            campaign = load_campaign(campaign_path)
            upsert_hidden_character(campaign)

            with connect(campaign) as conn:
                write_cards(campaign, conn)

            hidden_card = campaign_path / "cards" / "characters" / "npc__hidden-reviewer.md"
            self.assertFalse(hidden_card.exists(), hidden_card)

            archive_path = Path(tmp) / "save.aigmsave"
            exported = export_save(campaign, archive_path)
            with zipfile.ZipFile(exported.archive_path) as archive:
                names = set(archive.namelist())
            self.assertNotIn("cards/characters/npc__hidden-reviewer.md", names)

    def test_hidden_character_memories_are_not_retrievable_in_default_memory_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path = copy_initialized_campaign(tmp, MINIMAL_FIXTURE)
            campaign = load_campaign(campaign_path)
            upsert_hidden_character(campaign)

            with connect(campaign) as conn:
                rebuild_memory_summaries(campaign, conn)
                rows = find_relevant_memories(conn, targets=["npc:hidden-reviewer", "隐藏审查员"], limit=10)

        leaked = [
            dict(row)
            for row in rows
            if row["subject_id"] == "npc:hidden-reviewer" or "隐藏审查员" in row["summary"]
        ]
        self.assertEqual(leaked, [])


if __name__ == "__main__":
    unittest.main()
