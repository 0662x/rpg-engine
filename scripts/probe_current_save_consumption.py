from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from rpg_engine.intent_router import ActionIntent, TurnContract
from rpg_engine.proposal import TurnProposal
from rpg_engine.runtime import GMRuntime
from rpg_engine.save_validation import inspect_save_package


DEFAULT_RP_ROOT = Path("/Users/oliver/.hermes/rp")
CAMPAIGN_DIR_NAME = "isekai-farm-campaign-native-v1"
SAVE_DIR_NAME = "isekai-farm-save-native-v1"


@dataclass
class Check:
    area: str
    name: str
    status: str
    observed: str
    expected: str
    details: list[str] = field(default_factory=list)
    issue: str = ""


@dataclass(frozen=True)
class CommitOutcome:
    committed: bool
    ok: bool
    error: str = ""
    check_errors: tuple[str, ...] = ()
    audit_findings: tuple[str, ...] = ()


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe inventory consumption/decrement behavior on the current save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-consumption-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_auto_combat_cases(args.rp_root))
    checks.extend(run_natural_consumption_cases(args.rp_root))
    checks.extend(run_natural_consumption_variant_cases(args.rp_root))
    checks.extend(run_manual_consumption_cases(args.rp_root))
    checks.extend(run_manual_extended_consumption_cases(args.rp_root))
    checks.extend(run_guardrail_cases(args.rp_root))
    checks.extend(run_guardrail_extended_cases(args.rp_root))
    checks.extend(run_stale_write_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-consumption-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_auto_combat_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    ammo_cases = [
        ("auto combat consumes stun bolt", "item:stun-thorn-bolts", 12, 11),
        ("auto combat consumes toxic bolt", "item:toxic-thorn-bolts", 20, 19),
        ("auto combat consumes burst bolt", "item:burst-thorn-bolts", 20, 19),
        ("auto combat consumes frost bolt", "item:frost-thorn-bolts", 20, 19),
        ("auto combat consumes powder arrow", "item:powder-arrows", 5, 4),
    ]
    for name, ammo_id, expected_before, expected_after in ammo_cases:
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = quantity(save_dir, ammo_id)
            try:
                preview = runtime.preview_action(
                    "combat",
                    {
                        "target": "char:pumpkin-s2",
                        "weapon": "item:ultimate-compound-crossbow",
                        "ammo": ammo_id,
                        "distance": "medium",
                        "ready_state": "已上弦并装填",
                        "user_text": f"消费压力测试：发射 {ammo_id}",
                    },
                )
                if not preview.ready_to_save:
                    after = quantity(save_dir, ammo_id)
                    checks.append(
                        Check(
                            "auto combat",
                            name,
                            "ISSUE",
                            f"preview_not_ready status={preview.status} before={before} after={after}",
                            f"{expected_before:g}->{expected_after:g}, commit ok",
                            details=[*preview.errors, *preview.warnings],
                            issue="combat_preview_not_ready",
                        )
                    )
                    continue
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            except Exception as exc:  # pragma: no cover - report path
                outcome = CommitOutcome(False, False, f"{type(exc).__name__}: {exc}")
            after = quantity(save_dir, ammo_id)
            ok = outcome.committed and outcome.ok and before == expected_before and after == expected_after
            checks.append(
                Check(
                    "auto combat",
                    name,
                    "PASS" if ok else "ISSUE",
                    f"before={before} after={after} committed={outcome.committed} ok={outcome.ok}",
                    f"{expected_before:g}->{expected_after:g}, commit ok",
                    details=outcome_details(outcome),
                    issue="" if ok else "auto_combat_decrement_gap",
                )
            )

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        before = quantity(save_dir, "item:stun-thorn-bolts")
        outcomes: list[CommitOutcome] = []
        for index in range(3):
            preview = runtime.preview_action(
                "combat",
                {
                    "target": "char:pumpkin-s2",
                    "weapon": "item:ultimate-compound-crossbow",
                    "ammo": "item:stun-thorn-bolts",
                    "distance": "medium",
                    "ready_state": "已上弦并装填",
                    "user_text": f"连续消费压力测试：第 {index + 1} 次发射琥珀麻箭",
                },
            )
            if not preview.ready_to_save:
                outcomes.append(CommitOutcome(False, False, f"preview_not_ready:{preview.status}"))
                break
            outcomes.append(commit(runtime, preview.delta_draft or {}, preview.turn_proposal))
        after = quantity(save_dir, "item:stun-thorn-bolts")
        ok = before == 12 and after == 9 and all(item.committed and item.ok for item in outcomes)
        checks.append(
            Check(
                "auto combat",
                "three sequential stun shots",
                "PASS" if ok else "ISSUE",
                f"before={before} after={after} outcomes={[item.ok for item in outcomes]}",
                "12->9 across three committed shots",
                details=[detail for item in outcomes for detail in outcome_details(item)],
                issue="" if ok else "sequential_decrement_gap",
            )
        )
    return checks


def run_natural_consumption_cases(rp_root: Path) -> list[Check]:
    cases = [
        ("eat water spinach", "吃掉1株空心菜", "item:v1-3a6b64e5c1", 13, 12),
        ("drink water", "喝0.5L水", "item:v1-0b81d0d73c", 4, 3.5),
        ("use salt", "用掉0.25勺盐调味", "item:salt", 0.5, 0.25),
        ("use pine nut oil in cooking", "做饭用掉0.5竹杯松子油", "item:pine-nut-oil", 3, 2.5),
        ("use black powder in fuse test", "测试火药箭引信用掉0.25竹杯黑火药", "item:black-powder", 0.5, 0.25),
        ("use hemp fiber for rope", "用0.5kg麻纤维修绳索", "item:v1-9852b22696", 3, 2.5),
        ("shoot plain bolts in training", "训练射完3支旧普通箭", "item:plain-bolts", 3, 0),
        ("shoot stun bolt natural complete", "用终极复合弩发射琥珀麻箭射南瓜，中距离", "item:stun-thorn-bolts", 12, 11),
        ("shoot powder arrow natural complete", "用终极复合弩射一支火药箭打南瓜，中距离", "item:powder-arrows", 5, 4),
        ("feed t2 with fish", "喂T2母猫1条小杂鱼", "item:turn-000043-small-fish", 0, -1),
    ]
    checks: list[Check] = []
    for name, text, item_id, expected_before, expected_after in cases:
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = quantity(save_dir, item_id)
            try:
                start = runtime.start_turn(text).to_dict()
                preview = runtime.preview_from_text(text).to_dict()
            except Exception as exc:  # pragma: no cover - report path
                checks.append(
                    Check(
                        "natural consumption",
                        name,
                        "ISSUE",
                        f"error={type(exc).__name__}: {exc}",
                        f"natural command should decrement {item_id} {expected_before:g}->{expected_after:g} or block clearly before save",
                        issue="natural_consumption_exception",
                    )
                )
                continue
            committed = False
            commit_ok = False
            commit_error = ""
            if preview.get("ready_to_save") and preview.get("delta_draft") and preview.get("turn_proposal"):
                outcome = commit(runtime, preview["delta_draft"], preview["turn_proposal"])
                committed = outcome.committed
                commit_ok = outcome.ok
                commit_error = outcome.error
            after = quantity(save_dir, item_id)
            extracted_decrement = after == float(expected_after)
            blocked_safely = before == 0 and after == before and not committed
            ok = (
                before == float(expected_before)
                and ((committed and commit_ok and extracted_decrement) or blocked_safely)
            )
            issue = ""
            if not ok:
                if start.get("mode") == "query":
                    issue = "natural_consumption_misread_as_query"
                elif start.get("mode") == "maintenance":
                    issue = "natural_consumption_misread_as_maintenance"
                elif not preview.get("ready_to_save"):
                    issue = "natural_consumption_not_ready"
                elif committed and not extracted_decrement:
                    issue = "natural_consumption_committed_without_decrement"
                else:
                    issue = "natural_consumption_gap"
            checks.append(
                Check(
                    "natural consumption",
                    name,
                    "PASS" if ok else "ISSUE",
                    "start="
                    f"{start.get('mode')}:{start.get('submode')} can_proceed={start.get('can_proceed')} "
                    f"preview={preview.get('action')}:{preview.get('status')} ready={preview.get('ready_to_save')} "
                    f"before={before} after={after} committed={committed} ok={commit_ok}",
                    f"natural command should decrement {item_id} {expected_before:g}->{expected_after:g} or block clearly before save",
                    details=[
                        f"player_message={preview.get('player_message')}",
                        f"errors={preview.get('errors')}",
                        f"warnings={preview.get('warnings')}",
                        f"commit_error={commit_error}" if commit_error else "",
                    ],
                    issue=issue,
                )
            )
    return checks


def run_natural_consumption_variant_cases(rp_root: Path) -> list[Check]:
    cases = [
        ("sip water small amount", "喝掉0.1L水润喉", "item:v1-0b81d0d73c", 4, 3.9),
        ("eat lettuce leaf", "吃1片红叶生菜", "item:v1-f07d297448", 3, 2),
        ("eat amaranth leaves", "吃掉2片苋菜大叶", "item:v1-e267e90894", 8, 6),
        ("eat wild onion", "吃1根野葱", "item:v1-0629e81966", 3, 2),
        ("eat garlic leaf", "吃掉1片蒜叶", "item:v1-8aa915dbc4", 2, 1),
        ("eat chili", "吃掉1颗红辣椒", "item:v1-d409c6757a", 1, 0),
        ("eat pine nuts", "吃掉0.5份松子仁", "item:v1-b4fc16271b", 1, 0.5),
        ("cook with berries", "做酱用掉0.25竹杯红浆果", "item:v1-8182ae0835", 0.5, 0.25),
        ("use ordinary resin", "修补器具用掉0.25竹杯普通残胶", "item:v1-9bb88c5944", 0.5, 0.25),
        ("use hardened resin", "粘合试验用掉10ml硬化残胶", "item:v1-0322977645", 80, 70),
        ("use acid resin", "酸蚀试验用掉5ml酸残胶", "item:v1-18a38459f1", 30, 25),
        ("use sulfur shards", "配药用掉0.5把硫磺碎晶", "item:v1-4681d8edfb", 1, 0.5),
        ("use niter needles", "研磨用掉0.25杯硝石针晶", "item:v1-26667819cb", 0.5, 0.25),
        ("use tung oil", "给木件上油用掉0.25L生桐油", "item:v1-e247bca14a", 1, 0.75),
        ("use spare rope", "绑扎用掉0.5m备用纤维绳", "item:v1-515c3e4a2f", 3, 2.5),
        ("use lake fiber", "编绳用掉0.5束湖边细纤维", "item:v1-ac25ff32a4", 1, 0.5),
        ("shoot old poison bolt", "用旧毒弩箭射一支警告箭", "item:poison-bolts", 9, 8),
        ("shoot bamboo arrows", "练习射掉5支竹箭", "item:v1-9a74235657", 15, 10),
        ("shoot frost bolt", "用终极复合弩发射1支霜白冻箭，中距离", "item:frost-thorn-bolts", 20, 19),
        ("shoot burst bolt", "用终极复合弩发射1支赤红炸箭，中距离", "item:burst-thorn-bolts", 20, 19),
        ("shoot toxic thorn bolt", "用终极复合弩发射1支紫黑毒箭，中距离", "item:toxic-thorn-bolts", 20, 19),
        ("disassemble landmine", "拆掉M2地雷并消耗1枚地雷", "item:landmine-m2", 1, 0),
        ("feed with berries", "喂T2一点红浆果，用掉0.25竹杯", "item:v1-8182ae0835", 0.5, 0.25),
        ("season meal with salt", "晚饭再用0.1勺盐", "item:salt", 0.5, 0.4),
        ("drink all water", "把竹水筒里的4L水都喝完", "item:v1-0b81d0d73c", 4, 0),
    ]
    checks: list[Check] = []
    for name, text, item_id, expected_before, expected_after in cases:
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = quantity(save_dir, item_id)
            try:
                start = runtime.start_turn(text).to_dict()
                preview = runtime.preview_from_text(text).to_dict()
            except Exception as exc:  # pragma: no cover - report path
                checks.append(
                    Check(
                        "natural consumption variants",
                        name,
                        "ISSUE",
                        f"error={type(exc).__name__}: {exc}",
                        f"natural command should decrement {item_id} {expected_before:g}->{expected_after:g} or block clearly before save",
                        issue="natural_consumption_exception",
                    )
                )
                continue
            committed = False
            commit_ok = False
            commit_error = ""
            if preview.get("ready_to_save") and preview.get("delta_draft") and preview.get("turn_proposal"):
                outcome = commit(runtime, preview["delta_draft"], preview["turn_proposal"])
                committed = outcome.committed
                commit_ok = outcome.ok
                commit_error = outcome.error
            after = quantity(save_dir, item_id)
            extracted_decrement = after == float(expected_after)
            blocked_safely = before == 0 and after == before and not committed
            ok = (
                before == float(expected_before)
                and ((committed and commit_ok and extracted_decrement) or blocked_safely)
            )
            issue = ""
            if not ok:
                if start.get("mode") == "query":
                    issue = "natural_consumption_misread_as_query"
                elif start.get("mode") == "maintenance":
                    issue = "natural_consumption_misread_as_maintenance"
                elif not preview.get("ready_to_save"):
                    issue = "natural_consumption_not_ready"
                elif committed and not extracted_decrement:
                    issue = "natural_consumption_committed_without_decrement"
                else:
                    issue = "natural_consumption_gap"
            checks.append(
                Check(
                    "natural consumption variants",
                    name,
                    "PASS" if ok else "ISSUE",
                    "start="
                    f"{start.get('mode')}:{start.get('submode')} can_proceed={start.get('can_proceed')} "
                    f"preview={preview.get('action')}:{preview.get('status')} ready={preview.get('ready_to_save')} "
                    f"before={before} after={after} committed={committed} ok={commit_ok}",
                    f"natural command should decrement {item_id} {expected_before:g}->{expected_after:g} or block clearly before save",
                    details=[
                        f"player_message={preview.get('player_message')}",
                        f"errors={preview.get('errors')}",
                        f"warnings={preview.get('warnings')}",
                        f"commit_error={commit_error}" if commit_error else "",
                    ],
                    issue=issue,
                )
            )
    return checks


def run_manual_consumption_cases(rp_root: Path) -> list[Check]:
    cases = [
        ("consume one water spinach", "item:v1-3a6b64e5c1", 12, "吃掉1株空心菜"),
        ("consume fractional salt", "item:salt", 0.25, "用掉半勺盐的一半调味"),
        ("drink half liter water", "item:v1-0b81d0d73c", 3.5, "喝掉0.5L竹水筒里的水"),
        ("use pine nut oil", "item:pine-nut-oil", 2.5, "做饭用掉0.5竹杯松子油"),
        ("use black powder", "item:black-powder", 0.25, "测试火药箭引信用掉0.25竹杯黑火药"),
        ("use hemp fiber", "item:v1-9852b22696", 2.5, "修补绳索用掉0.5kg麻纤维"),
        ("use milky residue", "item:v1-1767a0dfd3", 30, "涂层实验用掉10ml乳白残液"),
        ("consume single purple leaf", "item:v1-da43d4526b", 0, "吃掉1片紫苏"),
        ("consume all plain bolts", "item:plain-bolts", 0, "训练射完3支旧普通箭"),
        ("manual ammo decrement", "item:stun-thorn-bolts", 11, "人工记录消耗1支琥珀麻箭"),
    ]
    checks: list[Check] = []
    for name, item_id, expected_after, text in cases:
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = quantity(save_dir, item_id)
            delta = routine_consumption_delta(save_dir, item_id, expected_after, text)
            outcome = commit(runtime, delta, human_proposal("routine", {"task": text, "user_text": text}, delta))
            after = quantity(save_dir, item_id)
            health = inspect_save_package(save_dir)
            ok = outcome.committed and outcome.ok and after == float(expected_after) and health["ok"]
            checks.append(
                Check(
                    "manual consumption",
                    name,
                    "PASS" if ok else "ISSUE",
                    f"before={before} after={after} committed={outcome.committed} ok={outcome.ok} health={health['ok']}",
                    f"quantity becomes {float(expected_after):g}, commit ok, health ok",
                    details=outcome_details(outcome),
                    issue="" if ok else "manual_decrement_gap",
                )
            )
    return checks


def run_manual_extended_consumption_cases(rp_root: Path) -> list[Check]:
    cases = [
        ("manual lettuce leaf", "item:v1-f07d297448", 2, "结构化记录：吃掉1片红叶生菜"),
        ("manual amaranth leaves", "item:v1-e267e90894", 6, "结构化记录：吃掉2片苋菜大叶"),
        ("manual wild onion", "item:v1-0629e81966", 2, "结构化记录：吃掉1根野葱"),
        ("manual garlic leaf", "item:v1-8aa915dbc4", 1, "结构化记录：吃掉1片蒜叶"),
        ("manual red chili", "item:v1-d409c6757a", 0, "结构化记录：吃掉1颗红辣椒"),
        ("manual red berries", "item:v1-8182ae0835", 0.25, "结构化记录：用掉0.25竹杯红浆果"),
        ("manual pine nuts", "item:v1-b4fc16271b", 0.5, "结构化记录：吃掉0.5份松子仁"),
        ("manual ordinary resin", "item:v1-9bb88c5944", 0.25, "结构化记录：用掉0.25竹杯普通残胶"),
        ("manual hardened resin", "item:v1-0322977645", 70, "结构化记录：用掉10ml硬化残胶"),
        ("manual acid resin", "item:v1-18a38459f1", 25, "结构化记录：用掉5ml酸残胶"),
        ("manual sulfur shards", "item:v1-4681d8edfb", 0.5, "结构化记录：用掉0.5把硫磺碎晶"),
        ("manual niter needles", "item:v1-26667819cb", 0.25, "结构化记录：用掉0.25杯硝石针晶"),
        ("manual tung oil", "item:v1-e247bca14a", 0.75, "结构化记录：用掉0.25L生桐油"),
        ("manual spare rope", "item:v1-515c3e4a2f", 2.5, "结构化记录：用掉0.5m备用纤维绳"),
        ("manual lake fiber", "item:v1-ac25ff32a4", 0.5, "结构化记录：用掉0.5束湖边细纤维"),
        ("manual old poison bolt", "item:poison-bolts", 8, "结构化记录：消耗1支旧毒弩箭"),
        ("manual bamboo arrows", "item:v1-9a74235657", 10, "结构化记录：消耗5支竹箭"),
        ("manual frost bolt", "item:frost-thorn-bolts", 19, "结构化记录：消耗1支霜白冻箭"),
        ("manual burst bolt", "item:burst-thorn-bolts", 19, "结构化记录：消耗1支赤红炸箭"),
        ("manual toxic bolt", "item:toxic-thorn-bolts", 19, "结构化记录：消耗1支紫黑毒箭"),
        ("manual plain bolt partial", "item:plain-bolts", 2, "结构化记录：只消耗1支旧普通箭"),
        ("manual landmine removed", "item:landmine-m2", 0, "结构化记录：拆除并消耗1枚M2地雷"),
        ("manual bamboo water all", "item:v1-0b81d0d73c", 0, "结构化记录：用完4L竹水筒水"),
        ("manual berry vinegar", "item:berry-vinegar", 0.5, "结构化记录：用掉0.5竹杯浆果醋"),
        ("manual sulfur sample", "item:v1-d88d8320cf", 0, "结构化记录：用完1份硫磺样本"),
    ]
    checks: list[Check] = []
    for name, item_id, expected_after, text in cases:
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = quantity(save_dir, item_id)
            delta = routine_consumption_delta(save_dir, item_id, expected_after, text)
            outcome = commit(runtime, delta, human_proposal("routine", {"task": text, "user_text": text}, delta))
            after = quantity(save_dir, item_id)
            query_ok = False
            query_text = ""
            if outcome.committed and outcome.ok:
                try:
                    query_text = runtime.query("entity", item_id).text
                    row = full_item_row(save_dir, item_id)
                    query_ok = f"{float(expected_after):g}{row['unit'] or ''}" in "".join(query_text.split())
                except Exception as exc:  # pragma: no cover - report path
                    query_text = f"query_error={type(exc).__name__}: {exc}"
            health = inspect_save_package(save_dir)
            ok = outcome.committed and outcome.ok and after == float(expected_after) and health["ok"] and query_ok
            checks.append(
                Check(
                    "manual consumption extended",
                    name,
                    "PASS" if ok else "ISSUE",
                    f"before={before} after={after} committed={outcome.committed} ok={outcome.ok} health={health['ok']} query_ok={query_ok}",
                    f"quantity becomes {float(expected_after):g}, query updates immediately, health ok",
                    details=[*outcome_details(outcome), f"query={query_text[:220]}"],
                    issue="" if ok else "manual_extended_decrement_gap",
                )
            )
    return checks


def run_guardrail_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        before = quantity(save_dir, "item:v1-3a6b64e5c1")
        delta = base_delta(save_dir, "吃掉1株空心菜但没有写库存扣减", "routine")
        delta["events"][0]["payload"].update(
            {
                "consumed_item_id": "item:v1-3a6b64e5c1",
                "consumed_quantity": 1,
                "material_consumption_required": True,
            }
        )
        delta["upsert_entities"] = []
        outcome = commit(runtime, delta, human_proposal("routine", {"task": delta["user_text"], "user_text": delta["user_text"]}, delta))
        after = quantity(save_dir, "item:v1-3a6b64e5c1")
        ok = (not outcome.committed or not outcome.ok) and after == before
        checks.append(
            Check(
                "guardrail",
                "narrated consumption without upsert",
                "PASS" if ok else "ISSUE",
                f"before={before} after={after} committed={outcome.committed} ok={outcome.ok}",
                "should block or remain uncommitted when consumption is not structured",
                details=outcome_details(outcome),
                issue="" if ok else "narrated_consumption_committed_without_decrement",
            )
        )

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        before = quantity(save_dir, "item:v1-3a6b64e5c1")
        delta = routine_consumption_delta(save_dir, "item:v1-3a6b64e5c1", before or 0, "声称吃掉1株空心菜但数量保持不变")
        delta["events"][0]["payload"]["consumed_quantity"] = 1
        outcome = commit(runtime, delta, human_proposal("routine", {"task": delta["user_text"], "user_text": delta["user_text"]}, delta))
        after = quantity(save_dir, "item:v1-3a6b64e5c1")
        ok = (not outcome.committed or not outcome.ok) and after == before
        checks.append(
            Check(
                "guardrail",
                "event says consumed but upsert keeps same quantity",
                "PASS" if ok else "ISSUE",
                f"before={before} after={after} committed={outcome.committed} ok={outcome.ok}",
                "should block inconsistent consumption/no-op quantity",
                details=outcome_details(outcome),
                issue="" if ok else "consumption_noop_quantity_committed",
            )
        )

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        before = quantity(save_dir, "item:salt")
        delta = routine_consumption_delta(save_dir, "item:salt", -0.5, "超额用盐导致负库存")
        outcome = commit(runtime, delta, human_proposal("routine", {"task": delta["user_text"], "user_text": delta["user_text"]}, delta))
        after = quantity(save_dir, "item:salt")
        ok = (not outcome.committed or not outcome.ok) and after == before
        checks.append(
            Check(
                "guardrail",
                "overconsume into negative quantity",
                "PASS" if ok else "ISSUE",
                f"before={before} after={after} committed={outcome.committed} ok={outcome.ok}",
                "negative inventory should be blocked before write and leave quantity unchanged",
                details=outcome_details(outcome),
                issue="" if ok else "negative_quantity_written_or_reported_late",
            )
        )

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        before = quantity(save_dir, "item:salt")
        delta = routine_consumption_delta(save_dir, "item:salt", 0.25, "用盐但单位写错")
        delta["upsert_entities"][0]["item"]["unit"] = "支"
        outcome = commit(runtime, delta, human_proposal("routine", {"task": delta["user_text"], "user_text": delta["user_text"]}, delta))
        after_row = full_item_row(save_dir, "item:salt")
        ok = (not outcome.committed or not outcome.ok) and float(after_row["quantity"]) == before and after_row["unit"] == "勺"
        checks.append(
            Check(
                "guardrail",
                "unit mismatch on decrement",
                "PASS" if ok else "ISSUE",
                f"before={before} after={after_row['quantity']}{after_row['unit']} committed={outcome.committed} ok={outcome.ok}",
                "unit changes during pure consumption should be blocked",
                details=outcome_details(outcome),
                issue="" if ok else "unit_mismatch_committed",
            )
        )

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        before = quantity(save_dir, "item:powder-arrows")
        before_row = full_item_row(save_dir, "item:powder-arrows")
        delta = routine_consumption_delta(
            save_dir,
            "item:powder-arrows",
            4,
            "最小字段upsert测试：发射1支火药箭",
            minimal_upsert=True,
        )
        outcome = commit(runtime, delta, human_proposal("routine", {"task": delta["user_text"], "user_text": delta["user_text"]}, delta))
        after_row = full_item_row(save_dir, "item:powder-arrows")
        metadata_preserved = (
            after_row["owner_id"] == before_row["owner_id"]
            and after_row["location_id"] == before_row["location_id"]
            and json.loads(after_row["properties_json"] or "{}") == json.loads(before_row["properties_json"] or "{}")
        )
        ok = outcome.committed and outcome.ok and quantity(save_dir, "item:powder-arrows") == 4 and metadata_preserved
        checks.append(
            Check(
                "guardrail",
                "minimal quantity upsert preserves metadata",
                "PASS" if ok else "ISSUE",
                "before_qty="
                f"{before} after_qty={after_row['quantity']} owner={before_row['owner_id']}->{after_row['owner_id']} "
                f"location={before_row['location_id']}->{after_row['location_id']} "
                f"properties_preserved={metadata_preserved} committed={outcome.committed} ok={outcome.ok}",
                "quantity decrements while owner/location/properties remain intact",
                details=outcome_details(outcome),
                issue="" if ok else "minimal_upsert_loses_metadata",
            )
        )

    return checks


def run_guardrail_extended_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []

    def add_case(
        name: str,
        item_ids: list[str],
        expected: str,
        issue_code: str,
        build_delta: Any,
    ) -> None:
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = {item_id: item_snapshot(save_dir, item_id) for item_id in item_ids}
            delta = build_delta(save_dir)
            outcome = commit(
                runtime,
                delta,
                human_proposal("routine", {"task": delta["user_text"], "user_text": delta["user_text"]}, delta),
            )
            after = {item_id: item_snapshot(save_dir, item_id) for item_id in item_ids}
            unchanged = before == after
            ok = (not outcome.committed or not outcome.ok) and unchanged
            checks.append(
                Check(
                    "guardrail extended",
                    name,
                    "PASS" if ok else "ISSUE",
                    f"committed={outcome.committed} ok={outcome.ok} unchanged={unchanged}",
                    expected,
                    details=outcome_details(outcome),
                    issue="" if ok else issue_code,
                )
            )

    def salt_delta(save_dir: Path, after_quantity: float = 0.25, text: str = "扩展防护：用盐") -> dict[str, Any]:
        return routine_consumption_delta(save_dir, "item:salt", after_quantity, text)

    add_case(
        "non-numeric quantity on decrement",
        ["item:salt"],
        "should block non-numeric quantity before write",
        "non_numeric_quantity_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：数量写成文字"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("quantity", "少量"),
        ),
    )
    add_case(
        "null quantity on exact decrement",
        ["item:salt"],
        "should block null quantity when exact stock is decremented",
        "null_quantity_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：数量被写成null"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("quantity", None),
        ),
    )
    add_case(
        "missing unit on decrement",
        ["item:salt"],
        "should block losing unit during pure consumption",
        "missing_unit_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：单位丢失"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("unit", None),
        ),
    )
    add_case(
        "event consumes salt but upsert decrements water",
        ["item:salt", "item:v1-0b81d0d73c"],
        "should block event/upsert item mismatch",
        "consumed_item_upsert_mismatch_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：事件用盐但扣水"),
            lambda delta: delta.__setitem__(
                "upsert_entities",
                [entity_payload_for_quantity(save_dir, "item:v1-0b81d0d73c", 3.5)],
            ),
        ),
    )
    add_case(
        "payload after quantity mismatches upsert",
        ["item:salt"],
        "should block payload after_quantity that disagrees with upsert quantity",
        "payload_after_quantity_mismatch_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：payload after数量不一致"),
            lambda delta: delta["events"][0]["payload"].__setitem__("after_quantity", 0.4),
        ),
    )
    add_case(
        "payload before quantity mismatches db",
        ["item:salt"],
        "should block payload before_quantity that disagrees with current stock",
        "payload_before_quantity_mismatch_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：payload before数量不一致"),
            lambda delta: delta["events"][0]["payload"].__setitem__("before_quantity", 99),
        ),
    )
    add_case(
        "payload consumed quantity too high",
        ["item:salt"],
        "should block consumed_quantity inconsistent with before/after",
        "payload_consumed_quantity_mismatch_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：payload消耗量过大"),
            lambda delta: delta["events"][0]["payload"].__setitem__("consumed_quantity", 99),
        ),
    )
    add_case(
        "negative consumed quantity payload",
        ["item:salt"],
        "should block negative consumed_quantity in event payload",
        "negative_consumed_quantity_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：payload消耗量为负"),
            lambda delta: delta["events"][0]["payload"].__setitem__("consumed_quantity", -1),
        ),
    )
    add_case(
        "payload consumed item id mismatch",
        ["item:salt"],
        "should block consumed_item_id that disagrees with upsert entity",
        "payload_consumed_item_mismatch_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：payload物品id不一致"),
            lambda delta: delta["events"][0]["payload"].__setitem__("consumed_item_id", "item:v1-0b81d0d73c"),
        ),
    )
    add_case(
        "category changed during decrement",
        ["item:salt"],
        "should block category mutation during pure consumption",
        "category_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时改分类"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("category", "weapon"),
        ),
    )
    add_case(
        "quality changed during decrement",
        ["item:salt"],
        "should block quality mutation during pure consumption",
        "quality_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时改品质"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("quality", "spoiled"),
        ),
    )
    add_case(
        "name changed during decrement",
        ["item:salt"],
        "should block renaming item during pure consumption",
        "name_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时改名"),
            lambda delta: delta["upsert_entities"][0].__setitem__("name", "不是盐"),
        ),
    )
    add_case(
        "status archived during decrement",
        ["item:salt"],
        "should block status mutation during pure consumption",
        "status_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时归档"),
            lambda delta: delta["upsert_entities"][0].__setitem__("status", "archived"),
        ),
    )
    add_case(
        "visibility hidden during decrement",
        ["item:salt"],
        "should block visibility mutation during pure consumption",
        "visibility_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时隐藏物品"),
            lambda delta: delta["upsert_entities"][0].__setitem__("visibility", "hidden"),
        ),
    )
    add_case(
        "location and owner lost during decrement",
        ["item:salt"],
        "should block dropping storage location/owner during pure consumption",
        "storage_location_lost_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时丢失位置"),
            lambda delta: (delta["upsert_entities"][0].pop("location_id", None), delta["upsert_entities"][0].pop("owner_id", None)),
        ),
    )
    add_case(
        "properties lost during decrement",
        ["item:powder-arrows"],
        "should block losing high-risk item properties during pure consumption",
        "properties_lost_committed",
        lambda save_dir: with_mutation(
            routine_consumption_delta(save_dir, "item:powder-arrows", 4, "扩展防护：扣减时清空火药箭属性"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("properties", {}),
        ),
    )
    add_case(
        "stackable changed during decrement",
        ["item:salt"],
        "should block stackable mutation during pure consumption",
        "stackable_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时改stackable"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("stackable", False),
        ),
    )
    add_case(
        "durability changed during decrement",
        ["item:salt"],
        "should block durability mutation during pure consumption",
        "durability_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时写入耐久"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("durability_current", 1),
        ),
    )
    add_case(
        "equipped slot changed during decrement",
        ["item:salt"],
        "should block equipped_slot mutation during pure consumption",
        "equipped_slot_mutation_committed",
        lambda save_dir: with_mutation(
            salt_delta(save_dir, 0.25, "扩展防护：扣减时写装备槽"),
            lambda delta: delta["upsert_entities"][0]["item"].__setitem__("equipped_slot", "hand"),
        ),
    )
    add_case(
        "minimal toxic bolt upsert loses metadata",
        ["item:toxic-thorn-bolts"],
        "should preserve owner/location/properties when decrementing high-risk ammo",
        "minimal_high_risk_upsert_loses_metadata",
        lambda save_dir: routine_consumption_delta(
            save_dir,
            "item:toxic-thorn-bolts",
            19,
            "扩展防护：最小字段扣减紫黑毒箭",
            minimal_upsert=True,
        ),
    )
    return checks


def run_stale_write_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        initial_turn = meta_value(save_dir, "current_turn_id")
        first = routine_consumption_delta(save_dir, "item:salt", 0.25, "第一次用盐")
        first_outcome = commit(runtime, first, human_proposal("routine", {"task": first["user_text"], "user_text": first["user_text"]}, first))
        stale = routine_consumption_delta(save_dir, "item:salt", 0.4, "基于旧库存的第二次用盐")
        stale_outcome = commit(runtime, stale, human_proposal("routine", {"task": stale["user_text"], "user_text": stale["user_text"]}, stale))
        after = quantity(save_dir, "item:salt")
        ok = first_outcome.committed and first_outcome.ok and (not stale_outcome.committed or not stale_outcome.ok) and after == 0.25
        checks.append(
            Check(
                "stale write",
                "stale consumption without expected_turn_id",
                "PASS" if ok else "ISSUE",
                f"initial_turn={initial_turn} after={after} first_ok={first_outcome.ok} stale_committed={stale_outcome.committed} stale_ok={stale_outcome.ok}",
                "stale second consumption should not overwrite a fresher quantity",
                details=[*outcome_details(first_outcome), *outcome_details(stale_outcome)],
                issue="" if ok else "stale_consumption_overwrites_quantity",
            )
        )

    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        initial_turn = meta_value(save_dir, "current_turn_id")
        first = routine_consumption_delta(save_dir, "item:salt", 0.25, "第一次用盐")
        first_outcome = commit(runtime, first, human_proposal("routine", {"task": first["user_text"], "user_text": first["user_text"]}, first))
        stale = routine_consumption_delta(save_dir, "item:salt", 0.4, "带expected_turn_id的旧库存第二次用盐")
        stale["expected_turn_id"] = initial_turn
        stale_outcome = commit(runtime, stale, human_proposal("routine", {"task": stale["user_text"], "user_text": stale["user_text"]}, stale))
        after = quantity(save_dir, "item:salt")
        ok = first_outcome.committed and first_outcome.ok and not stale_outcome.committed and after == 0.25
        checks.append(
            Check(
                "stale write",
                "stale consumption with expected_turn_id",
                "PASS" if ok else "ISSUE",
                f"initial_turn={initial_turn} after={after} first_ok={first_outcome.ok} stale_committed={stale_outcome.committed} error={stale_outcome.error}",
                "expected_turn_id should block stale write and preserve 0.25",
                details=[*outcome_details(first_outcome), *outcome_details(stale_outcome)],
                issue="" if ok else "expected_turn_guard_failed",
            )
        )
    return checks


def routine_consumption_delta(
    save_dir: Path,
    item_id: str,
    new_quantity: float,
    user_text: str,
    *,
    minimal_upsert: bool = False,
) -> dict[str, Any]:
    before = quantity(save_dir, item_id)
    row = full_item_row(save_dir, item_id)
    delta = base_delta(save_dir, user_text, "routine")
    delta["summary"] = f"{user_text}；库存 {row['name']} {before:g}->{float(new_quantity):g}{row['unit'] or ''}。"
    delta["events"][0]["summary"] = delta["summary"]
    delta["events"][0]["payload"].update(
        {
            "consumed_item_id": item_id,
            "before_quantity": before,
            "after_quantity": new_quantity,
            "unit": row["unit"],
            "material_consumption_required": True,
        }
    )
    delta["upsert_entities"] = [entity_payload_for_quantity(save_dir, item_id, new_quantity, minimal=minimal_upsert)]
    return delta


def base_delta(save_dir: Path, user_text: str, intent: str) -> dict[str, Any]:
    current_location = meta_value(save_dir, "current_location_id")
    current_time = meta_value(save_dir, "current_time_block")
    return {
        "user_text": user_text,
        "intent": intent,
        "changed": True,
        "game_time_before": current_time,
        "game_time_after": current_time,
        "location_before": current_location,
        "location_after": current_location,
        "summary": user_text,
        "events": [
            {
                "type": intent,
                "title": "库存消费压力测试",
                "summary": user_text,
                "payload": {
                    "task": user_text,
                    "state_changes_must_be_structured": True,
                },
                "source": "consumption_probe",
            }
        ],
        "upsert_entities": [],
        "tick_clocks": [],
    }


def entity_payload_for_quantity(save_dir: Path, item_id: str, new_quantity: float, *, minimal: bool = False) -> dict[str, Any]:
    row = full_item_row(save_dir, item_id)
    item = {
        "category": row["category"],
        "quantity": new_quantity,
        "unit": row["unit"],
        "quality": row["quality"],
        "durability_current": row["durability_current"],
        "durability_max": row["durability_max"],
        "stackable": bool(row["stackable"]),
        "equipped_slot": row["equipped_slot"],
    }
    if not minimal:
        item["properties"] = json.loads(row["properties_json"] or "{}")
    entity: dict[str, Any] = {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "status": row["status"],
        "visibility": row["visibility"],
        "summary": row["summary"],
        "details": json.loads(row["details_json"] or "{}"),
        "item": item,
    }
    if not minimal:
        entity["aliases"] = aliases(save_dir, item_id)
        entity["location_id"] = row["location_id"]
        entity["owner_id"] = row["owner_id"]
        entity["details"].setdefault("last_consumption_probe", "temporary stress-test copy only")
        entity["details"].setdefault("quantity_confidence", "confirmed")
        entity["details"].setdefault("source", "consumption_probe")
    return entity


def commit(runtime: GMRuntime, delta: dict[str, Any], proposal: dict[str, Any] | TurnProposal | None) -> CommitOutcome:
    try:
        result = runtime.commit_turn(delta, turn_proposal=proposal, backup=False)
    except Exception as exc:
        return CommitOutcome(False, False, f"{type(exc).__name__}: {exc}")
    data = result.to_dict()
    audit = data.get("state_audit") or {}
    findings = []
    for item in audit.get("findings", []) if isinstance(audit.get("findings", []), list) else []:
        if isinstance(item, dict):
            findings.append(str(item.get("code") or item.get("message") or item))
        else:
            findings.append(str(item))
    return CommitOutcome(
        True,
        bool(data.get("ok")),
        check_errors=tuple(str(item) for item in data.get("check_errors", [])),
        audit_findings=tuple(findings),
    )


def human_proposal(action: str, options: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    intent = ActionIntent(
        user_text=str(options.get("user_text") or ""),
        mode="action",
        submode=action,
        action=action,
        options=options,
        confidence="high",
        source="consumption_probe",
    )
    contract = TurnContract(
        intent=intent,
        required_template=f"{action}_turn.md",
        response_headings=("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
        requires_preview=True,
        must_save=True,
        allowed_delta_sources=("resolver_proposed", "ai_generated", "human_edited", "response_draft"),
        validation_profile="player_turn_commit",
    )
    return TurnProposal(
        proposal_id=f"turn-proposal:consumption:{action}:{abs(hash(json.dumps(delta, ensure_ascii=False, sort_keys=True)))}",
        intent=intent,
        preview={"action": action, "status": "ready", "facts_used": [], "rules_applied": []},
        delta=delta,
        delta_source="human_edited",
        provenance={"source": "probe_current_save_consumption", "resolver": action},
        human_confirmed=True,
        turn_contract=contract,
    ).to_dict()


def full_item_row(save_dir: Path, item_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            select e.id, e.type, e.name, e.status, e.visibility, e.location_id, e.owner_id,
                   e.summary, e.details_json,
                   i.category, i.quantity, i.unit, i.quality, i.durability_current, i.durability_max,
                   i.stackable, i.equipped_slot, i.properties_json
            from entities e
            join items i on i.entity_id = e.id
            where e.id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"missing item: {item_id}")
        return row
    finally:
        conn.close()


def quantity(save_dir: Path, item_id: str) -> float | None:
    row = full_item_row(save_dir, item_id)
    return float(row["quantity"]) if row["quantity"] is not None else None


def aliases(save_dir: Path, entity_id: str) -> list[str]:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        return [
            str(row[0])
            for row in conn.execute(
                "select alias from aliases where entity_id = ? and kind = 'name' order by alias",
                (entity_id,),
            )
        ]


def meta_value(save_dir: Path, key: str) -> str | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select value from meta where key = ?", (key,)).fetchone()
        return str(row[0]) if row else None


def item_snapshot(save_dir: Path, item_id: str) -> dict[str, Any] | None:
    try:
        row = full_item_row(save_dir, item_id)
    except ValueError:
        return None
    return dict(row)


def with_mutation(delta: dict[str, Any], mutate: Any) -> dict[str, Any]:
    mutate(delta)
    return delta


def outcome_details(outcome: CommitOutcome) -> list[str]:
    details: list[str] = []
    if outcome.error:
        details.append(f"error={outcome.error}")
    if outcome.check_errors:
        details.append("check_errors=" + "; ".join(outcome.check_errors))
    if outcome.audit_findings:
        details.append("state_audit=" + "; ".join(outcome.audit_findings))
    return details


def render_report(checks: list[Check]) -> str:
    pass_count = sum(1 for item in checks if item.status == "PASS")
    issue_count = len(checks) - pass_count
    issue_by_type: dict[str, int] = {}
    issue_by_area: dict[str, int] = {}
    for item in checks:
        if item.status == "PASS":
            continue
        issue_by_type[item.issue or "unspecified"] = issue_by_type.get(item.issue or "unspecified", 0) + 1
        issue_by_area[item.area] = issue_by_area.get(item.area, 0) + 1
    lines = [
        "# Current Save Consumption Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records inventory consumption/decrement behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Quantity Strategy Gap",
        "",
        "Intended policy:",
        "",
        "- High-risk or key inventory must be stored with exact quantity, unit, source, confidence, and location metadata before it can be spent automatically.",
        "- Low-risk common consumables may be stored fuzzily, but the fuzzy value must still be structured, queryable, and usable by consumption rules.",
        "",
        "Current implementation gap:",
        "",
        "- The item table has only numeric `quantity` plus `unit` as first-class fields.",
        "- Fuzzy inventory is usually parked in `details.quantity_text` or free-form properties.",
        "- Render, query, validation, and decrement paths do not share one reliable fuzzy quantity representation.",
        "- Ordinary fuzzy resources can be described, but cannot yet be consistently queried, reduced, exhausted, or escalated to an exact audit.",
        "- High-risk resources already have campaign rules that demand precision, but the engine still needs stronger pre-commit guards against approximate or metadata-losing spends.",
        "",
        "Tracking requirement: add a first-class quantity strategy that separates exact critical inventory from structured fuzzy low-risk consumables, with matching query, render, validation, and consumption behavior.",
        "",
    ]
    if issue_by_type:
        lines.extend(["## Issue Summary", "", "| Issue | Count |", "|---|---:|"])
        for issue, count in sorted(issue_by_type.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| `{issue}` | {count} |")
        lines.append("")
    if issue_by_area:
        lines.extend(["## Issue By Area", "", "| Area | Count |", "|---|---:|"])
        for area, count in sorted(issue_by_area.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {area} | {count} |")
        lines.append("")
    lines.extend(["## Issues", ""])
    issues = [item for item in checks if item.status != "PASS"]
    if not issues:
        lines.append("No issues found.")
    else:
        lines.extend(["| Area | Case | Observed | Expected | Issue |", "|---|---|---|---|---|"])
        for item in issues:
            lines.append(
                f"| {item.area} | {item.name} | {escape(item.observed)} | {escape(item.expected)} | `{item.issue}` |"
            )
    lines.extend(["", "## Full Matrix", "", "| Status | Area | Case | Observed | Expected |", "|---|---|---|---|---|"])
    for item in checks:
        lines.append(
            f"| {item.status} | {item.area} | {item.name} | {escape(item.observed)} | {escape(item.expected)} |"
        )
    lines.extend(["", "## Details", ""])
    for item in checks:
        lines.extend(
            [
                f"### {item.status} · {item.area} · {item.name}",
                "",
                f"- Observed: {item.observed}",
                f"- Expected: {item.expected}",
            ]
        )
        if item.issue:
            lines.append(f"- Issue: `{item.issue}`")
        for detail in item.details:
            lines.append(f"- {detail}")
        lines.append("")
    return "\n".join(lines)


def escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
