from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

from rpg_engine.campaign import load_campaign
from rpg_engine.db import init_database


ENGINE_ROOT = Path(__file__).resolve().parents[1]
HERMES_ROOT = ENGINE_ROOT.parent
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"
DEFAULT_CURRENT_CAMPAIGN_ROOT = HERMES_ROOT / "rp" / "isekai-farm-campaign-native-v1"
DEFAULT_CURRENT_SAVE_ROOT = HERMES_ROOT / "rp" / "isekai-farm-save-native-v1"
CURRENT_CAMPAIGN_ROOT = Path(os.environ.get("RPG_ENGINE_CURRENT_CAMPAIGN_ROOT", DEFAULT_CURRENT_CAMPAIGN_ROOT)).expanduser()
CURRENT_SAVE_ROOT = Path(os.environ.get("RPG_ENGINE_CURRENT_SAVE_ROOT", DEFAULT_CURRENT_SAVE_ROOT)).expanduser()

CURRENT_NATIVE_REQUIRED = unittest.skipIf(
    not CURRENT_CAMPAIGN_ROOT.exists() or not CURRENT_SAVE_ROOT.exists(),
    f"requires current native campaign/save packages: {CURRENT_CAMPAIGN_ROOT}, {CURRENT_SAVE_ROOT}",
)


class FormalCurrentSaveReadOnlyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.formal_turn_before = current_turn(CURRENT_SAVE_ROOT)
        cls.formal_events_before = event_log_text(CURRENT_SAVE_ROOT)
        cls.formal_context_runs_before = query_int(
            CURRENT_SAVE_ROOT / "data" / "game.sqlite",
            "select count(*) from context_runs",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        if current_turn(CURRENT_SAVE_ROOT) != cls.formal_turn_before:
            raise AssertionError("formal current native save turn changed during tests")
        if event_log_text(CURRENT_SAVE_ROOT) != cls.formal_events_before:
            raise AssertionError("formal current native save event log changed during tests")
        if query_int(CURRENT_SAVE_ROOT / "data" / "game.sqlite", "select count(*) from context_runs") != cls.formal_context_runs_before:
            raise AssertionError("formal current native save context audit table changed during tests")


def run_cli(*args: object, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rpg_engine", *[str(arg) for arg in args]],
        cwd=ENGINE_ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def load_stdout_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)


def consensus_candidate(action: str, slots: dict[str, object], *, reason: str) -> dict[str, object]:
    return {
        "kind": "single",
        "mode": "action",
        "action": action,
        "slots": slots,
        "plan": [],
        "confidence": "high",
        "missing_slots": [],
        "needs_confirmation": [],
        "safety_flags": [],
        "reason": reason,
    }


def internal_review(action: str, slots: dict[str, object], *, reason: str) -> dict[str, object]:
    return {
        **consensus_candidate(action, slots, reason=reason),
        "agreement_with_external": "agree",
        "disagreements": [],
        "external_candidate_quality": "usable",
    }


def query_candidate(kind: str, query_text: str) -> dict[str, object]:
    slots: dict[str, object] = {"query_kind": kind}
    if kind != "scene":
        slots["query_text"] = query_text
    return {
        "kind": "query",
        "mode": "query",
        "action": "",
        "slots": slots,
        "plan": [],
        "confidence": "high",
        "missing_slots": [],
        "needs_confirmation": [],
        "safety_flags": [],
        "reason": f"external AI selected {kind} query",
    }


def internal_query_review(kind: str, query_text: str) -> dict[str, object]:
    return {
        **query_candidate(kind, query_text),
        "agreement_with_external": "agree",
        "disagreements": [],
        "external_candidate_quality": "usable",
        "reason": f"internal AI selected {kind} query",
    }


def query_scalar(db_path: Path, sql: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(sql).fetchone()
    finally:
        conn.close()
    return "" if row is None else str(row[0])


def query_int(db_path: Path, sql: str) -> int:
    return int(query_scalar(db_path, sql) or 0)


def current_turn(save_root: Path) -> str:
    return query_scalar(save_root / "data" / "game.sqlite", "select value from meta where key='current_turn_id'")


def current_location(save_root: Path) -> str:
    return query_scalar(save_root / "data" / "game.sqlite", "select value from meta where key='current_location_id'")


def event_log_text(save_root: Path) -> str:
    return (save_root / "data" / "events.jsonl").read_text(encoding="utf-8")


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            digest.update(f"L:{path.relative_to(root).as_posix()}".encode("utf-8"))
            digest.update(b"\0")
            digest.update(os.readlink(path).encode("utf-8"))
            digest.update(b"\0")
            continue
        marker = "D" if path.is_dir() else "F"
        digest.update(f"{marker}:{path.relative_to(root).as_posix()}".encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def loaded_ids(packet: Any) -> set[str]:
    return {str(item.get("id", "")) for item in packet.loaded_items}


def copy_initialized_minimal(tmp_root: str | Path) -> Path:
    target = Path(tmp_root) / "campaign"
    shutil.copytree(MINIMAL_FIXTURE, target)
    init_database(load_campaign(target), force=True)
    return target


def copy_current_packages(tmp_root: str | Path) -> Path:
    root = Path(tmp_root)
    campaign_target = root / CURRENT_CAMPAIGN_ROOT.name
    save_target = root / CURRENT_SAVE_ROOT.name
    shutil.copytree(
        CURRENT_CAMPAIGN_ROOT,
        campaign_target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
    )
    shutil.copytree(
        CURRENT_SAVE_ROOT,
        save_target,
        ignore=shutil.ignore_patterns("backups", "__pycache__", "*.sqlite-journal", "*.db-journal"),
    )
    return save_target


def normalize_current_native_story_fixture(save_root: str | Path) -> Path:
    """Pin a temporary current-native copy to the story-language baseline."""
    save = Path(save_root)
    if save.resolve() == CURRENT_SAVE_ROOT.resolve():
        raise AssertionError("temporary Save copy required")
    db_path = save / "data" / "game.sqlite"
    formal_db_path = CURRENT_SAVE_ROOT / "data" / "game.sqlite"
    if db_path.resolve() == formal_db_path.resolve() or db_path.samefile(formal_db_path):
        raise AssertionError("independent temporary Save database required")
    with sqlite3.connect(db_path) as conn:
        main_row = next(
            (row for row in conn.execute("pragma database_list") if str(row[1]) == "main"),
            None,
        )
        if main_row is None or Path(str(main_row[2])).samefile(formal_db_path):
            raise AssertionError("independent temporary Save database required")
        conn.row_factory = sqlite3.Row
        player_row = conn.execute(
            "select value from main.meta where key='player_entity_id'"
        ).fetchone()
        turn_row = conn.execute(
            "select value from main.meta where key='current_turn_id'"
        ).fetchone()
        if player_row is None or turn_row is None:
            raise AssertionError("temporary current-native fixture lacks player/current turn metadata")
        location_meta = conn.execute(
            "update main.meta set value='loc:home-mycelium-house' where key='current_location_id'"
        )
        time_meta = conn.execute(
            "update main.meta set value='第28天 · 上午' where key='current_time_block'"
        )
        player_entity = conn.execute(
            "update main.entities set location_id='loc:home-mycelium-house' where id=?",
            (str(player_row["value"]),),
        )
        projection = conn.execute(
            """
            update main.projection_state
            set version=1, last_turn_id=?, status='clean',
                updated_at='9999-12-31T23:59:59+00:00', last_error=null
            where name='memory'
            """,
            (str(turn_row["value"]),),
        )
        if any(cursor.rowcount != 1 for cursor in (location_meta, time_meta, player_entity, projection)):
            raise AssertionError("temporary current-native fixture normalization target missing")
        conn.commit()
    return save
