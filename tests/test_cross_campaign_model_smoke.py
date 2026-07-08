from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rpg_engine.campaign import load_campaign
from rpg_engine.campaign_validation import (
    RUNTIME_AIGM_DIR,
    RUNTIME_AIGM_FILES,
    RUNTIME_AIGM_PENDING_PREFIX,
    RUNTIME_ARTIFACT_DIRS,
    RUNTIME_ARTIFACT_FILES,
    RUNTIME_ARTIFACT_SUFFIXES,
    run_campaign_smoke_tests,
    validate_campaign_package,
)
from rpg_engine.content_types import get_default_registry
from rpg_engine.db import connect, upsert_clock, upsert_entity
from rpg_engine.delta_schema import validate_delta_schema
from rpg_engine.entity_access import list_entities, read_entity
from rpg_engine.packages.service import PACKAGE_AUXILIARY_CONTENT_KEYS, load_package_source
from rpg_engine.progress_access import list_progress, read_progress, validate_delta_progress_references
from rpg_engine.relationship_access import list_relationships, read_relationship
from rpg_engine.save_service import init_v1_save, inspect_v1_save


ENGINE_ROOT = Path(__file__).resolve().parents[1]
V1_MINIMAL = ENGINE_ROOT / "examples" / "v1_minimal_adventure"
SMALL_CN = ENGINE_ROOT / "examples" / "small_cn_campaign"
MINIMAL_FIXTURE = ENGINE_ROOT / "tests" / "fixtures" / "minimal_campaign"


@dataclass(frozen=True)
class CampaignCase:
    name: str
    root: Path
    player_entity_id: str
    current_location_id: str
    feature_entity_id: str
    hidden_entity_id: str
    relationship_id: str
    clock_id: str


CAMPAIGNS = (
    CampaignCase(
        name="v1-minimal-adventure",
        root=V1_MINIMAL,
        player_entity_id="pc:runner",
        current_location_id="loc:watch-camp",
        feature_entity_id="ref:broken-seal",
        hidden_entity_id="ref:tower-signal-code",
        relationship_id="rel:runner-mira",
        clock_id="clock:storm-front",
    ),
    CampaignCase(
        name="small-cn-campaign",
        root=SMALL_CN,
        player_entity_id="pc:traveler",
        current_location_id="loc:camp",
        feature_entity_id="ref:broken-seal",
        hidden_entity_id="ref:hidden-signal-code",
        relationship_id="rel:pc-guide-lin",
        clock_id="clock:storm-front",
    ),
)

HERMES_ROOT = ENGINE_ROOT.parent
DEFAULT_WORKSPACE_ROOT = HERMES_ROOT / "rp"
DEFAULT_CURRENT_SAVE_ROOT = HERMES_ROOT / "rp" / "isekai-farm-save-native-v1"
SAVE_REGISTRY_RELATIVE = Path(".aigm") / "save-registry.json"
WORKSPACE_STATE_RELATIVES = (
    Path(".aigm") / "save-registry.json",
    Path(".aigm") / "save-registry.json.lock",
    Path(".aigm") / "pending-player-action.json",
    Path(".aigm") / "pending-player-clarification.json",
    Path(".aigm") / "pending-clarification.json",
)

class CrossCampaignModelSmokeTests(unittest.TestCase):
    def test_two_campaigns_share_foundation_model_contracts_on_temp_saves(self) -> None:
        assert_tempfile_root_not_under_protected_roots(self)
        before = {case.name: fingerprint_package(case.root) for case in CAMPAIGNS}
        before_runtime = {case.name: runtime_artifacts(case.root) for case in CAMPAIGNS}
        self.assertEqual(before_runtime, {case.name: () for case in CAMPAIGNS})
        current_save_before = current_save_fingerprints()
        registry_contracts: dict[str, dict[str, dict[str, Any]]] = {}
        table_sets: dict[str, set[str]] = {}
        schema_signatures: dict[str, tuple[tuple[str, str, str, str], ...]] = {}
        capability_sets: dict[str, set[str]] = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            canonical_schema_signature = canonical_core_schema_signature(tmp_root)
            for case in CAMPAIGNS:
                with self.subTest(campaign=case.name):
                    validation = validate_campaign_package(case.root)
                    self.assertTrue(validation.ok, validation.errors)
                    registry_contracts[case.name] = assert_campaign_content_uses_default_registry(self, case)

                    campaign_smoke = run_campaign_smoke_tests(case.root)
                    self.assertTrue(campaign_smoke.ok, campaign_smoke.errors)

                    save_dir = tmp_root / case.name / "save"
                    assert_not_under_current_save_roots(self, save_dir)
                    init_result = init_v1_save(case.root, save_dir)
                    self.assertTrue(init_result["ok"], init_result)

                    inspect = inspect_v1_save(save_dir)
                    assert_save_inspect_contract(self, inspect)

                    save_campaign = load_campaign(save_dir)
                    capability_sets[case.name] = set(save_campaign.config.get("capabilities", ()))
                    with connect(save_campaign) as conn:
                        assert_foundation_access_contracts(self, conn, case)
                        assert_progress_tick_validation(self, conn, case)
                        table_sets[case.name] = sqlite_table_set(conn)
                        schema_signatures[case.name] = sqlite_schema_signature(conn)

                    post_write_inspect = inspect_v1_save(save_dir)
                    assert_direct_fixture_inspect_has_only_expected_drift(self, post_write_inspect)

        self.assertNotEqual(capability_sets["v1-minimal-adventure"], capability_sets["small-cn-campaign"])
        self.assertEqual(registry_contracts["v1-minimal-adventure"], registry_contracts["small-cn-campaign"])
        self.assertEqual(table_sets["v1-minimal-adventure"], table_sets["small-cn-campaign"])
        self.assertEqual(schema_signatures["v1-minimal-adventure"], schema_signatures["small-cn-campaign"])
        for signature in schema_signatures.values():
            self.assertEqual(signature, canonical_schema_signature)
        for tables in table_sets.values():
            assert_no_campaign_specific_schema_names(self, tables)
        for signature in schema_signatures.values():
            assert_no_campaign_specific_schema_names(
                self,
                {name for _, name, _, _ in signature} | {table_name for _, _, table_name, _ in signature},
            )
            assert_no_campaign_specific_schema_sql(self, signature)
        for case in CAMPAIGNS:
            with self.subTest(source_not_mutated=case.name):
                self.assertEqual(runtime_artifacts(case.root), before_runtime[case.name])
                self.assertEqual(fingerprint_package(case.root), before[case.name])
        self.assertEqual(current_save_fingerprints(), current_save_before)

    def test_content_registry_keeps_relationship_and_clock_as_shared_contracts(self) -> None:
        registry = get_default_registry()
        self.assertEqual([spec.name for spec in registry.all()], ["entity", "rule", "clock", "route", "relationship", "world_setting"])
        self.assertIsNone(registry.by_delta_key("upsert_clocks"))
        self.assertIsNone(registry.by_delta_key("upsert_relationships"))
        self.assertIsNone(registry.get("clock").contract_metadata()["delta_key"])
        self.assertIsNone(registry.get("relationship").contract_metadata()["delta_key"])
        self.assertFalse(registry.get("clock").contract_metadata()["has_delta_upsert"])
        self.assertFalse(registry.get("relationship").contract_metadata()["has_delta_upsert"])


def assert_foundation_access_contracts(testcase: unittest.TestCase, conn: Any, case: CampaignCase) -> None:
    player = read_entity(conn, case.player_entity_id, view="player")
    testcase.assertIsNotNone(player)
    assert player is not None
    testcase.assertEqual(player.id, case.player_entity_id)
    testcase.assertTrue(player.type)
    testcase.assertTrue(player.name)
    testcase.assertTrue(player.summary)

    location = read_entity(conn, case.current_location_id, view="player")
    testcase.assertIsNotNone(location)
    assert location is not None
    testcase.assertEqual(location.type, "location")
    testcase.assertGreaterEqual(len(list_entities(conn, view="player", types="location")), 1)

    feature = read_entity(conn, case.feature_entity_id, view="player")
    testcase.assertIsNotNone(feature)
    assert feature is not None
    testcase.assertIn(feature.type, {"reference", "clue"})

    relationship = read_relationship(conn, case.relationship_id, view="player")
    testcase.assertIsNotNone(relationship)
    assert relationship is not None
    testcase.assertEqual(relationship.id, case.relationship_id)
    testcase.assertEqual(relationship.source_id, case.player_entity_id)
    testcase.assertTrue(relationship.target_id)
    testcase.assertTrue(relationship.summary)
    testcase.assertTrue(relationship.state)
    testcase.assertIsInstance(relationship.trust, int)
    testcase.assertGreaterEqual(len(list_relationships(conn, view="player")), 1)

    progress = read_progress(conn, case.clock_id, view="player")
    testcase.assertIsNotNone(progress)
    assert progress is not None
    testcase.assertEqual(progress.id, case.clock_id)
    testcase.assertGreater(progress.segments_total, 0)
    testcase.assertGreaterEqual(progress.segments_filled, 0)
    testcase.assertIn(progress.visibility, {"visible", "hinted", "known"})
    testcase.assertTrue(progress.trigger_when_full)
    testcase.assertTrue(progress.last_ticked_turn_id)
    testcase.assertTrue(progress.updated_turn_id)
    testcase.assertGreaterEqual(len(list_progress(conn, view="player")), 1)

    assert_player_hidden_guards(testcase, conn, case)


def assert_player_hidden_guards(testcase: unittest.TestCase, conn: Any, case: CampaignCase) -> None:
    testcase.assertIsNone(read_entity(conn, case.hidden_entity_id, view="player"))
    hidden_source_entity = read_entity(conn, case.hidden_entity_id, view="maintenance")
    testcase.assertIsNotNone(hidden_source_entity)

    hidden_npc_id = f"npc:{case.name}-hidden"
    hidden_relationship_id = f"rel:{case.name}-hidden-endpoint"
    hidden_relationship_entity_id = f"rel:{case.name}-hidden-entity"
    hidden_clock_id = f"clock:{case.name}:hidden"
    hidden_clock_entity_id = f"clock:{case.name}:hidden-entity"
    upsert_entity(
        conn,
        {
            "id": hidden_npc_id,
            "type": "character",
            "name": "Hidden Boundary NPC",
            "visibility": "hidden",
            "summary": "Hidden NPC used by cross-campaign smoke.",
        },
    )
    upsert_entity(
        conn,
        {
            "id": f"npc:{case.name}-visible",
            "type": "character",
            "name": "Visible Boundary NPC",
            "visibility": "known",
            "summary": "Visible NPC used by cross-campaign smoke.",
        },
    )
    upsert_entity(
        conn,
        {
            "id": hidden_relationship_id,
            "type": "relationship",
            "name": "Hidden Boundary Relationship",
            "visibility": "known",
            "summary": "Visible relationship entity with an unavailable player endpoint.",
            "details": {
                "source_id": case.player_entity_id,
                "target_id": hidden_npc_id,
                "kind": "boundary-smoke",
                "state": "hidden",
                "trust": 0,
            },
        },
    )
    upsert_entity(
        conn,
        {
            "id": hidden_relationship_entity_id,
            "type": "relationship",
            "name": "Hidden Boundary Relationship Entity",
            "visibility": "hidden",
            "summary": "Hidden relationship entity with player-readable endpoints.",
            "details": {
                "source_id": case.player_entity_id,
                "target_id": f"npc:{case.name}-visible",
                "kind": "boundary-smoke",
                "state": "hidden",
                "trust": 0,
            },
        },
    )
    upsert_clock(
        conn,
        {
            "id": hidden_clock_id,
            "name": "Hidden Boundary Clock",
            "summary": "Hidden progress used by cross-campaign smoke.",
            "clock_type": "boundary",
            "segments_total": 4,
            "segments_filled": 1,
            "visibility": "hidden",
            "trigger_when_full": "Hidden boundary event.",
        },
    )
    upsert_clock(
        conn,
        {
            "id": hidden_clock_entity_id,
            "name": "Hidden Entity Boundary Clock",
            "summary": "Hidden clock entity used by cross-campaign smoke.",
            "clock_type": "boundary",
            "segments_total": 4,
            "segments_filled": 1,
            "visibility": "visible",
            "trigger_when_full": "Hidden entity boundary event.",
        },
    )
    conn.execute("update entities set visibility = 'hidden' where id = ?", (hidden_clock_entity_id,))
    conn.commit()

    testcase.assertIsNone(read_entity(conn, hidden_npc_id, view="player"))
    testcase.assertIsNotNone(read_entity(conn, hidden_relationship_id, view="player"))
    testcase.assertIsNone(read_relationship(conn, hidden_relationship_id, view="player"))
    testcase.assertIsNone(read_entity(conn, hidden_relationship_entity_id, view="player"))
    testcase.assertIsNone(read_relationship(conn, hidden_relationship_entity_id, view="player"))
    testcase.assertIsNone(read_progress(conn, hidden_clock_id, view="player"))
    testcase.assertIsNone(read_entity(conn, hidden_clock_entity_id, view="player"))
    testcase.assertIsNone(read_progress(conn, hidden_clock_entity_id, view="player"))
    testcase.assertNotIn(hidden_npc_id, {item.id for item in list_entities(conn, view="player")})
    testcase.assertIn(hidden_relationship_id, {item.id for item in list_entities(conn, view="player")})
    testcase.assertNotIn(hidden_relationship_entity_id, {item.id for item in list_entities(conn, view="player")})
    testcase.assertNotIn(hidden_relationship_id, {item.id for item in list_relationships(conn, view="player")})
    testcase.assertNotIn(hidden_relationship_entity_id, {item.id for item in list_relationships(conn, view="player")})
    testcase.assertNotIn(hidden_clock_id, {item.id for item in list_progress(conn, view="player")})
    testcase.assertNotIn(hidden_clock_entity_id, {item.id for item in list_progress(conn, view="player")})
    testcase.assertIsNotNone(read_relationship(conn, hidden_relationship_id, view="maintenance"))
    testcase.assertIsNotNone(read_relationship(conn, hidden_relationship_entity_id, view="maintenance"))
    testcase.assertIsNotNone(read_progress(conn, hidden_clock_id, view="maintenance"))
    testcase.assertIsNotNone(read_progress(conn, hidden_clock_entity_id, view="maintenance"))


def assert_progress_tick_validation(testcase: unittest.TestCase, conn: Any, case: CampaignCase) -> None:
    delta = {
        "expected_turn_id": "turn:seed",
        "command_id": f"smoke:{case.name}:clock",
        "user_text": f"Advance {case.clock_id} for cross-campaign model smoke.",
        "intent": "clock",
        "changed": True,
        "summary": "A visible campaign clock advances through the shared tick contract.",
        "events": [
            {
                "type": "clock_tick",
                "title": "Clock advances",
                "summary": "Model smoke advances a visible clock.",
                "source": "cross_campaign_model_smoke",
            }
        ],
        "tick_clocks": [
            {
                "id": case.clock_id,
                "delta": 1,
                "reason": "Cross-campaign model smoke.",
            }
        ],
    }
    testcase.assertEqual(validate_delta_progress_references(conn, delta, view="player"), [])
    testcase.assertEqual(validate_delta_schema(delta, conn), [])
    hidden_delta = dict(delta)
    hidden_delta["tick_clocks"] = [
        {
            "id": f"clock:{case.name}:hidden",
            "delta": 1,
            "reason": "Cross-campaign hidden clock guard.",
        }
    ]
    testcase.assertIn(
        f"$.tick_clocks[0].id: unavailable clock clock:{case.name}:hidden",
        validate_delta_progress_references(conn, hidden_delta, view="player"),
    )
    testcase.assertIn(
        f"$.tick_clocks[0].id: unavailable clock clock:{case.name}:hidden",
        validate_delta_schema(hidden_delta, conn, caller_view="player"),
    )
    for forbidden_key in ("upsert_clocks", "upsert_relationships"):
        invalid_delta = dict(delta)
        invalid_delta[forbidden_key] = []
        testcase.assertIn(f"$.{forbidden_key}: unknown top-level field", validate_delta_schema(invalid_delta, conn))


def assert_campaign_content_uses_default_registry(
    testcase: unittest.TestCase,
    case: CampaignCase,
) -> dict[str, dict[str, Any]]:
    registry = get_default_registry()
    source = load_package_source(case.root, registry=registry)
    content = source.manifest.get("content", {})
    testcase.assertIsInstance(content, dict)
    assert isinstance(content, dict)
    registered_campaign_keys = {spec.campaign_key for spec in registry.seed_specs() if spec.campaign_key}
    content_keys = set(content)
    testcase.assertEqual(content_keys - registered_campaign_keys - set(PACKAGE_AUXILIARY_CONTENT_KEYS), set())
    expected_types = {
        spec.name
        for key in content_keys
        if (spec := registry.by_campaign_key(key)) is not None
    }
    testcase.assertEqual(set(source.records_by_type), expected_types)
    testcase.assertTrue({"entity", "relationship", "clock", "rule", "route", "world_setting"} <= expected_types)
    return registry_contract_metadata(registry)


def canonical_core_schema_signature(tmp_root: Path) -> tuple[tuple[str, str, str, str], ...]:
    save_dir = tmp_root / "canonical-core-schema" / "save"
    init_result = init_v1_save(MINIMAL_FIXTURE, save_dir)
    if not init_result["ok"]:
        raise AssertionError(init_result)
    campaign = load_campaign(save_dir)
    with connect(campaign) as conn:
        return sqlite_schema_signature(conn)


def assert_save_inspect_contract(testcase: unittest.TestCase, inspect: dict[str, Any]) -> None:
    testcase.assertTrue(inspect["ok"], inspect["errors"])
    testcase.assertEqual(inspect["authority_contract"]["current_fact_authority"]["path"], "data/game.sqlite")
    testcase.assertEqual(inspect["authority_contract"]["current_fact_authority"]["authority"], "authoritative")
    testcase.assertEqual(inspect["projection_health"]["authority"], "evidence")
    testcase.assertGreaterEqual(inspect["counts"]["entities"], 1)
    testcase.assertGreaterEqual(inspect["counts"]["clocks"], 1)


def assert_direct_fixture_inspect_has_only_expected_drift(testcase: unittest.TestCase, inspect: dict[str, Any]) -> None:
    unexpected = [
        error
        for error in inspect["errors"]
        if not (str(error).startswith("cards: missing generated card") or is_expected_fts_count_drift(str(error)))
    ]
    testcase.assertEqual(unexpected, [])


def is_expected_fts_count_drift(error: str) -> bool:
    return error.startswith("fts_index: expected ") and " indexed entities, got " in error


def registry_contract_metadata(registry: Any | None = None) -> dict[str, dict[str, Any]]:
    registry = registry or get_default_registry()
    return {spec.name: spec.contract_metadata() for spec in registry.all()}


def sqlite_table_set(conn: Any) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute("select name from sqlite_master where type = 'table'")
        if not str(row["name"]).startswith("sqlite_")
    }


def sqlite_schema_signature(conn: Any) -> tuple[tuple[str, str, str, str], ...]:
    rows = conn.execute(
        """
        select type, name, tbl_name, sql
        from sqlite_master
        where type in ('table', 'index', 'trigger', 'view')
          and name not like 'sqlite_%'
        order by type, name
        """
    ).fetchall()
    return tuple(
        (
            str(row["type"]),
            str(row["name"]),
            str(row["tbl_name"]),
            str(row["sql"] or ""),
        )
        for row in rows
    )


def assert_no_campaign_specific_schema_names(testcase: unittest.TestCase, names: set[str]) -> None:
    forbidden_exact = {"progress_tracks", "relationship_edges", "campaign_specific_facts"}
    forbidden_prefixes = (
        "progress_tracks_",
        "relationships_",
        "relationship_",
        "relationship_edges_",
        "campaign_specific_",
        "genre_",
    )
    for name in names:
        normalized = name.lower()
        testcase.assertNotIn(normalized, forbidden_exact)
        for prefix in forbidden_prefixes:
            testcase.assertFalse(normalized.startswith(prefix), name)


def assert_no_campaign_specific_schema_sql(
    testcase: unittest.TestCase,
    signature: tuple[tuple[str, str, str, str], ...],
) -> None:
    forbidden_sql_fragments = (
        "progress_tracks",
        "relationship_edges",
        "relationships_",
        "campaign_specific",
        "genre_",
    )
    for _, name, _, sql in signature:
        normalized = sql.lower()
        for fragment in forbidden_sql_fragments:
            testcase.assertNotIn(fragment, normalized, name)


def runtime_artifacts(root: Path) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()

    def add(path: Path, *, directory: bool = False) -> None:
        relative = path.relative_to(root).as_posix()
        if directory and not relative.endswith("/"):
            relative += "/"
        if relative in seen:
            return
        seen.add(relative)
        found.append(relative)

    for relative in RUNTIME_ARTIFACT_FILES:
        path = root / relative
        if path.exists() or path.is_symlink():
            add(path)
    aigm = root / RUNTIME_AIGM_DIR
    if aigm.is_symlink():
        add(aigm, directory=True)
    elif aigm.exists() and not aigm.is_dir():
        add(aigm)
    elif aigm.is_dir():
        for path in sorted(aigm.iterdir()):
            if path.name in RUNTIME_AIGM_FILES or path.name.startswith(RUNTIME_AIGM_PENDING_PREFIX):
                add(path, directory=path.is_dir())
    for path in sorted(root.rglob("*")):
        if (path.is_file() or path.is_symlink()) and path.name.endswith(RUNTIME_ARTIFACT_SUFFIXES):
            add(path)
    for relative in RUNTIME_ARTIFACT_DIRS:
        path = root / relative
        if path.is_symlink():
            add(path, directory=True)
            continue
        if not path.exists():
            continue
        if not path.is_dir():
            add(path)
            continue
        artifacts = sorted(item for item in path.rglob("*") if item.is_file() or item.is_symlink())
        if not artifacts:
            add(path, directory=True)
            continue
        for item in artifacts:
            add(item, directory=item.is_dir())
    return tuple(sorted(found))


def fingerprint_package(root: Path) -> tuple[tuple[str, str, str], ...]:
    if not root.exists():
        return (("missing", ".", ""),)
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append(("symlink", relative, os.readlink(path)))
        elif path.is_dir():
            entries.append(("dir", relative, ""))
        elif path.is_file():
            entries.append(("file", relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return tuple(entries)


def current_save_roots() -> tuple[Path, ...]:
    roots = [DEFAULT_CURRENT_SAVE_ROOT]
    env_root = os.environ.get("RPG_ENGINE_CURRENT_SAVE_ROOT")
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.extend(registry_save_roots())
    return unique_paths(roots)


def current_workspace_roots() -> tuple[Path, ...]:
    roots = [DEFAULT_WORKSPACE_ROOT]
    env_save_root = os.environ.get("RPG_ENGINE_CURRENT_SAVE_ROOT")
    if env_save_root:
        roots.extend(candidate_workspace_roots_for_save(Path(env_save_root).expanduser()))
    return unique_paths(roots)


def candidate_workspace_roots_for_save(save_root: Path) -> list[Path]:
    roots = [save_root.parent]
    try:
        resolved = save_root.resolve()
    except FileNotFoundError:
        resolved = save_root
    for candidate in (resolved, *resolved.parents):
        if (candidate / SAVE_REGISTRY_RELATIVE).exists():
            roots.append(candidate)
    return roots


def current_registry_paths() -> tuple[Path, ...]:
    return tuple(path for root in current_workspace_roots() if (path := root / SAVE_REGISTRY_RELATIVE).exists())


def registry_save_roots() -> list[Path]:
    roots: list[Path] = []
    for registry_path in current_registry_paths():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(registry, dict):
            continue
        saves = registry.get("saves", [])
        if not isinstance(saves, list):
            continue
        workspace_root = registry_path.parent.parent
        for save in saves:
            if not isinstance(save, dict):
                continue
            path = save.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            candidate = Path(path).expanduser()
            roots.append(candidate if candidate.is_absolute() else workspace_root / candidate)
    return roots


def unique_paths(paths: list[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in paths:
        try:
            resolved = root.resolve()
        except FileNotFoundError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(root)
    return tuple(unique)


def current_save_fingerprints() -> dict[str, tuple[tuple[str, str, str], ...]]:
    fingerprints = {f"save:{root.resolve()}": fingerprint_package(root) for root in current_save_roots()}
    for workspace_root in current_workspace_roots():
        for relative in WORKSPACE_STATE_RELATIVES:
            path = workspace_root / relative
            fingerprints[f"workspace-state:{path.resolve()}"] = fingerprint_single_path(path)
    return fingerprints


def fingerprint_single_path(path: Path) -> tuple[tuple[str, str, str], ...]:
    if path.is_symlink():
        return (("symlink", path.name, os.readlink(path)),)
    if path.is_file():
        return (("file", path.name, hashlib.sha256(path.read_bytes()).hexdigest()),)
    if path.is_dir():
        return fingerprint_package(path)
    return (("missing", path.name, ""),)


def assert_not_under_current_save_roots(testcase: unittest.TestCase, path: Path) -> None:
    target = path.resolve()
    for root in current_save_roots():
        current_root = root.resolve()
        testcase.assertFalse(target == current_root or current_root in target.parents, f"{target} is under {current_root}")


def assert_tempfile_root_not_under_protected_roots(testcase: unittest.TestCase) -> None:
    assert_not_under_current_save_roots(testcase, Path(tempfile.gettempdir()) / "__rpg_engine_temp_probe__")
    assert_not_under_source_campaign_roots(testcase, Path(tempfile.gettempdir()) / "__rpg_engine_temp_probe__")


def assert_not_under_source_campaign_roots(testcase: unittest.TestCase, path: Path) -> None:
    target = path.resolve()
    for case in CAMPAIGNS:
        source_root = case.root.resolve()
        testcase.assertFalse(target == source_root or source_root in target.parents, f"{target} is under {source_root}")


if __name__ == "__main__":
    unittest.main()
