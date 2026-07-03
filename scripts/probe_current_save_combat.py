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

from rpg_engine.runtime import GMRuntime
from rpg_engine.save_validation import inspect_save_package


DEFAULT_RP_ROOT = Path("/Users/oliver/.hermes/rp")
CAMPAIGN_DIR_NAME = "isekai-farm-campaign-native-v1"
SAVE_DIR_NAME = "isekai-farm-save-native-v1"
PLAYER_ENTITY_ID = "pc:shenyan"
DEFAULT_WEAPON_ID = "item:ultimate-compound-crossbow"
DEFAULT_TARGET_ID = "char:pumpkin-s2"


@dataclass(frozen=True)
class StructuredCombatCase:
    name: str
    target: str
    weapon: str
    ammo: str
    distance: str
    ready_state: str
    expected_before: float
    expected_after: float
    expected_behavior: str = "preview ready, commit ok, combat event written, ammo decremented exactly once, location unchanged"


@dataclass(frozen=True)
class SequentialCombatCase:
    name: str
    shots: tuple[tuple[str, str], ...]
    expected_behavior: str


@dataclass(frozen=True)
class NaturalCombatCase:
    name: str
    text: str
    expectation: str
    ammo: str | None = None
    expected_before: float | None = None
    expected_after: float | None = None
    expected_behavior: str = "player text should route through the combat pipeline"


@dataclass(frozen=True)
class GuardrailCase:
    name: str
    options: dict[str, Any]
    expected_behavior: str
    issue_if_ready: str
    issue_if_committed: str
    setup_zero_ammo: str | None = None


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
    parser = argparse.ArgumentParser(description="Probe combat behavior on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-combat-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_structured_combat_cases(args.rp_root))
    checks.extend(run_sequential_combat_cases(args.rp_root))
    checks.extend(run_natural_combat_cases(args.rp_root))
    checks.extend(run_guardrail_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-combat-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_structured_combat_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
            before_qty = quantity(save_dir, case.ammo)
            try:
                preview = runtime.preview_action(
                    "combat",
                    {
                        "target": case.target,
                        "weapon": case.weapon,
                        "ammo": case.ammo,
                        "distance": case.distance,
                        "ready_state": case.ready_state,
                        "user_text": f"战斗探测：{case.name}",
                    },
                )
            except Exception as exc:
                checks.append(
                    Check(
                        area="structured combat",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="combat_preview_exception",
                    )
                )
                continue

            if not preview.ready_to_save:
                checks.append(
                    Check(
                        area="structured combat",
                        name=case.name,
                        status="ISSUE",
                        observed=f"ready=False status={preview.status} ammo_before={before_qty}",
                        expected=case.expected_behavior,
                        details=preview_details(preview.to_dict()),
                        issue=issue_for_combat_preview(preview.to_dict()),
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_combat_commit(
                    area="structured combat",
                    name=case.name,
                    save_dir=save_dir,
                    preview_data=preview.to_dict(),
                    outcome=outcome,
                    before_turns=before_turns,
                    before_events=before_events,
                    before_location=before_location,
                    before_pc_location=before_pc_location,
                    ammo_id=case.ammo,
                    expected_before=case.expected_before,
                    expected_after=case.expected_after,
                    actual_before=before_qty,
                    expected_target=case.target,
                    expected_weapon=case.weapon,
                    expected_distance=case.distance,
                    expected=case.expected_behavior,
                    extra_details=[f"ammo_before_actual={before_qty}"],
                )
            )
    return checks


def run_sequential_combat_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in sequential_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_quantities = {ammo_id: quantity(save_dir, ammo_id) for ammo_id, _distance in case.shots}
            outcomes: list[CommitOutcome] = []
            preview_details_accum: list[str] = []
            for index, (ammo_id, distance) in enumerate(case.shots, start=1):
                preview = runtime.preview_action(
                    "combat",
                    {
                        "target": DEFAULT_TARGET_ID,
                        "weapon": DEFAULT_WEAPON_ID,
                        "ammo": ammo_id,
                        "distance": distance,
                        "ready_state": "已上弦并装填",
                        "user_text": f"连续战斗探测：{case.name} 第 {index} 发",
                    },
                )
                preview_details_accum.append(f"shot:{index} ready={preview.ready_to_save} status={preview.status}")
                if not preview.ready_to_save:
                    outcomes.append(CommitOutcome(False, False, f"preview_not_ready:{preview.status}"))
                    break
                outcomes.append(commit(runtime, preview.delta_draft or {}, preview.turn_proposal))
                if not outcomes[-1].ok:
                    break

            after_quantities = {ammo_id: quantity(save_dir, ammo_id) for ammo_id, _distance in case.shots}
            expected_after = dict(before_quantities)
            for ammo_id, _distance in case.shots:
                expected_after[ammo_id] = (expected_after[ammo_id] or 0) - 1
            ok = (
                len(outcomes) == len(case.shots)
                and all(item.committed and item.ok for item in outcomes)
                and after_quantities == expected_after
                and table_count(save_dir, "turns") == before_turns + len(case.shots)
                and table_count(save_dir, "events") == before_events + len(case.shots)
                and meta_value(save_dir, "current_location_id") == before_location
                and inspect_save_package(save_dir)["ok"]
            )
            checks.append(
                Check(
                    area="sequential combat",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"outcomes={[item.ok for item in outcomes]} turns={before_turns}->{table_count(save_dir, 'turns')} "
                        f"events={before_events}->{table_count(save_dir, 'events')} ammo={before_quantities}->{after_quantities}"
                    ),
                    expected=case.expected_behavior,
                    details=[*preview_details_accum, *[detail for item in outcomes for detail in outcome_details(item)]],
                    issue="" if ok else "combat_sequential_decrement_gap",
                )
            )
    return checks


def run_natural_combat_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in natural_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
            before_qty = quantity(save_dir, case.ammo) if case.ammo else None
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="natural combat",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=[f"text={case.text}"],
                        issue="natural_combat_exception",
                    )
                )
                continue

            if case.expectation == "ready_commit":
                if preview_key(data) != "action:combat" or not preview.ready_to_save:
                    checks.append(natural_issue_check(case, start, data, save_dir, before_turns, before_events, before_qty))
                    continue
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                checks.append(
                    evaluate_combat_commit(
                        area="natural combat",
                        name=case.name,
                        save_dir=save_dir,
                        preview_data=data,
                        outcome=outcome,
                        before_turns=before_turns,
                        before_events=before_events,
                        before_location=before_location,
                        before_pc_location=before_pc_location,
                        ammo_id=case.ammo or "",
                        expected_before=case.expected_before or 0,
                        expected_after=case.expected_after or 0,
                        actual_before=before_qty,
                        expected_target=DEFAULT_TARGET_ID,
                        expected_weapon=DEFAULT_WEAPON_ID,
                        expected_distance=None,
                        expected=case.expected_behavior,
                        extra_details=[f"text={case.text}", f"start={route_key(start)}", f"ammo_before_actual={before_qty}"],
                    )
                )
                continue

            if case.expectation == "combat_clarify":
                no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
                ok = route_key(start) == "action:combat" and preview_key(data) == "action:combat" and not preview.ready_to_save and no_write
                checks.append(
                    Check(
                        area="natural combat",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=(
                            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
                            f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} no_write={no_write}"
                        ),
                        expected=case.expected_behavior,
                        details=[f"text={case.text}", *preview_details(data)],
                        issue="" if ok else issue_for_natural_combat(start, data, preview.ready_to_save),
                    )
                )
                continue

            if case.expectation == "combat_clarify_target":
                no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
                errors = [str(item) for item in data.get("errors", [])]
                target_extracted = not any("目标未明确" in item for item in errors)
                ok = (
                    route_key(start) == "action:combat"
                    and preview_key(data) == "action:combat"
                    and not preview.ready_to_save
                    and target_extracted
                    and no_write
                )
                issue = ""
                if not ok:
                    issue = "natural_combat_target_not_extracted" if not target_extracted else issue_for_natural_combat(start, data, preview.ready_to_save)
                checks.append(
                    Check(
                        area="natural combat",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=(
                            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
                            f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} "
                            f"target_extracted={target_extracted} no_write={no_write}"
                        ),
                        expected=case.expected_behavior,
                        details=[f"text={case.text}", *preview_details(data)],
                        issue=issue,
                    )
                )
                continue

            if case.expectation == "query_not_combat":
                no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
                ok = preview_key(data) == "action:query" and no_write
                checks.append(
                    Check(
                        area="natural combat",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=(
                            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
                            f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} no_write={no_write}"
                        ),
                        expected=case.expected_behavior,
                        details=[f"text={case.text}", *preview_details(data)],
                        issue="" if ok else "natural_query_misrouted_to_combat",
                    )
                )
    return checks


def natural_issue_check(
    case: NaturalCombatCase,
    start: dict[str, Any],
    data: dict[str, Any],
    save_dir: Path,
    before_turns: int,
    before_events: int,
    before_qty: float | None,
) -> Check:
    no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
    return Check(
        area="natural combat",
        name=case.name,
        status="ISSUE",
        observed=(
            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
            f"preview={preview_key(data)} ready={data.get('ready_to_save')} status={data.get('status')} "
            f"ammo_before={before_qty} no_write={no_write}"
        ),
        expected=case.expected_behavior,
        details=[
            f"text={case.text}",
            f"player_message={one_line(str(data.get('player_message') or ''))}",
            *preview_details(data),
        ],
        issue=issue_for_natural_combat(start, data, bool(data.get("ready_to_save"))),
    )


def run_guardrail_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in guardrail_cases():
        with copied_save(rp_root) as save_dir:
            if case.setup_zero_ammo:
                set_item_quantity(save_dir, case.setup_zero_ammo, 0)
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_quantities = ammo_quantities(save_dir)
            try:
                preview = runtime.preview_action("combat", case.options)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="combat guardrails",
                        name=case.name,
                        status="PASS",
                        observed=f"preview_exception={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                    )
                )
                continue

            committed = False
            outcome: CommitOutcome | None = None
            if preview.ready_to_save:
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                committed = outcome.ok
            after_quantities = ammo_quantities(save_dir)
            unchanged = (
                before_turns == table_count(save_dir, "turns")
                and before_events == table_count(save_dir, "events")
                and before_location == meta_value(save_dir, "current_location_id")
                and before_quantities == after_quantities
            )
            ok = not preview.ready_to_save and unchanged
            issue = ""
            if preview.ready_to_save:
                issue = case.issue_if_ready
            if committed:
                issue = case.issue_if_committed
            checks.append(
                Check(
                    area="combat guardrails",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"ready={preview.ready_to_save} status={data.get('status')} committed={committed} "
                        f"turns={before_turns}->{table_count(save_dir, 'turns')} "
                        f"events={before_events}->{table_count(save_dir, 'events')} "
                        f"location={before_location}->{meta_value(save_dir, 'current_location_id')}"
                    ),
                    expected=case.expected_behavior,
                    details=[
                        f"ammo={before_quantities}->{after_quantities}",
                        *preview_details(data),
                        *outcome_details(outcome),
                    ],
                    issue=issue,
                )
            )
    return checks


def evaluate_combat_commit(
    *,
    area: str,
    name: str,
    save_dir: Path,
    preview_data: dict[str, Any],
    outcome: CommitOutcome,
    before_turns: int,
    before_events: int,
    before_location: str | None,
    before_pc_location: str | None,
    ammo_id: str,
    expected_before: float,
    expected_after: float,
    actual_before: float | None,
    expected_target: str,
    expected_weapon: str,
    expected_distance: str | None,
    expected: str,
    extra_details: list[str] | None = None,
) -> Check:
    after_turns = table_count(save_dir, "turns")
    after_events = table_count(save_dir, "events")
    current_location = meta_value(save_dir, "current_location_id")
    pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
    latest_event = latest_event_row(save_dir)
    latest_turn = latest_turn_row(save_dir)
    health = inspect_save_package(save_dir)
    payload = delta_event_payload(preview_data)
    event_payload = latest_event.get("payload", {}) if isinstance(latest_event.get("payload"), dict) else {}
    before_qty = actual_before if actual_before is not None else expected_before
    after_qty = quantity(save_dir, ammo_id)

    errors: list[str] = []
    issue = ""
    if not outcome.ok:
        errors.append("commit did not return ok")
        issue = "combat_commit_failed"
    if after_turns != before_turns + 1:
        errors.append(f"turn count {before_turns}->{after_turns}")
        issue = issue or "combat_turn_not_written"
    if after_events != before_events + 1:
        errors.append(f"event count {before_events}->{after_events}")
        issue = issue or "combat_event_not_written"
    if current_location != before_location:
        errors.append(f"meta.current_location_id {before_location}->{current_location}")
        issue = issue or "combat_changed_location"
    if pc_location != before_pc_location:
        errors.append(f"player.location_id {before_pc_location}->{pc_location}")
        issue = issue or "combat_changed_player_location"
    if latest_event.get("type") != "combat":
        errors.append(f"latest_event.type={latest_event.get('type')}")
        issue = issue or "combat_event_missing"
    if latest_turn.get("location_before") != before_location or latest_turn.get("location_after") != before_location:
        errors.append(
            "turn location "
            f"{latest_turn.get('location_before')}->{latest_turn.get('location_after')}"
        )
        issue = issue or "combat_turn_location_wrong"
    if payload.get("target_id") != expected_target:
        errors.append(f"delta target_id={payload.get('target_id')}")
        issue = issue or "combat_target_mismatch"
    if payload.get("weapon_id") != expected_weapon:
        errors.append(f"delta weapon_id={payload.get('weapon_id')}")
        issue = issue or "combat_weapon_mismatch"
    if payload.get("ammo_id") != ammo_id:
        errors.append(f"delta ammo_id={payload.get('ammo_id')}")
        issue = issue or "combat_ammo_mismatch"
    if expected_distance and payload.get("distance") != expected_distance:
        errors.append(f"delta distance={payload.get('distance')}")
        issue = issue or "combat_distance_mismatch"
    if event_payload.get("ammo_id") != ammo_id:
        errors.append(f"event ammo_id={event_payload.get('ammo_id')}")
        issue = issue or "combat_event_ammo_mismatch"
    if before_qty != expected_before or after_qty != expected_after:
        errors.append(f"ammo {ammo_id} {before_qty}->{after_qty}, expected {expected_before}->{expected_after}")
        issue = issue or "combat_ammo_decrement_wrong"
    if not health["ok"]:
        errors.append("save health failed")
        issue = issue or "combat_save_health_failed"

    details = [
        *(extra_details or []),
        f"delta_payload={payload}",
        f"event_payload={event_payload}",
        f"ammo_expected={expected_before}->{expected_after}",
        f"ammo_actual={before_qty}->{after_qty}",
        *preview_details(preview_data),
        *outcome_details(outcome),
    ]
    if errors:
        details.append("errors=" + "; ".join(errors))
    return Check(
        area=area,
        name=name,
        status="PASS" if not errors else "ISSUE",
        observed=(
            f"ok={outcome.ok} turns={before_turns}->{after_turns} events={before_events}->{after_events} "
            f"ammo={ammo_id}:{expected_before}->{after_qty} location={before_location}->{current_location} "
            f"event={latest_event.get('type')} health={health['ok']}"
        ),
        expected=expected,
        details=details,
        issue=issue,
    )


def structured_cases() -> list[StructuredCombatCase]:
    ammo_baselines = {
        "item:stun-thorn-bolts": (12.0, 11.0),
        "item:toxic-thorn-bolts": (20.0, 19.0),
        "item:burst-thorn-bolts": (20.0, 19.0),
        "item:frost-thorn-bolts": (20.0, 19.0),
        "item:powder-arrows": (5.0, 4.0),
    }
    distances = ("贴身", "近距", "标准", "远距", "中距离")
    cases: list[StructuredCombatCase] = []
    for ammo_id, (before, after) in ammo_baselines.items():
        for distance in distances:
            cases.append(
                StructuredCombatCase(
                    name=f"{ammo_id} at {distance}",
                    target=DEFAULT_TARGET_ID,
                    weapon=DEFAULT_WEAPON_ID,
                    ammo=ammo_id,
                    distance=distance,
                    ready_state="已上弦并装填",
                    expected_before=before,
                    expected_after=after,
                )
            )
    return cases


def sequential_cases() -> list[SequentialCombatCase]:
    return [
        SequentialCombatCase(
            "three stun shots",
            (
                ("item:stun-thorn-bolts", "标准"),
                ("item:stun-thorn-bolts", "标准"),
                ("item:stun-thorn-bolts", "标准"),
            ),
            "three committed shots should decrement stun bolts 12->9 and write three combat turns",
        ),
        SequentialCombatCase(
            "mixed ammo volley",
            (
                ("item:stun-thorn-bolts", "标准"),
                ("item:toxic-thorn-bolts", "标准"),
                ("item:burst-thorn-bolts", "远距"),
                ("item:frost-thorn-bolts", "近距"),
                ("item:powder-arrows", "远距"),
            ),
            "mixed committed shots should decrement each fired ammo exactly once and write one event per shot",
        ),
    ]


def natural_cases() -> list[NaturalCombatCase]:
    ready = "fully specified natural combat should extract target/weapon/ammo/distance/ready state, commit, and decrement ammo"
    clarify = "vague or conditional combat should route to combat clarification without writing state"
    clarify_target = "named target combat should preserve the recognized target while asking for missing combat details"
    query = "weapon/ammo inventory questions should stay read-only query, not combat"
    return [
        NaturalCombatCase("natural complete stun shot", "用终极复合弩发射琥珀麻箭射南瓜，标准距离，已上弦并装填", "ready_commit", "item:stun-thorn-bolts", 12.0, 11.0, ready),
        NaturalCombatCase("natural complete toxic shot", "用终极复合弩发射紫黑毒箭射南瓜，近距，已装填", "ready_commit", "item:toxic-thorn-bolts", 20.0, 19.0, ready),
        NaturalCombatCase("natural complete burst shot", "用终极复合弩发射赤红炸箭射南瓜，远距，已装填", "ready_commit", "item:burst-thorn-bolts", 20.0, 19.0, ready),
        NaturalCombatCase("natural complete frost shot", "用终极复合弩射一支霜白冻箭打南瓜，标准距离，已上弦", "ready_commit", "item:frost-thorn-bolts", 20.0, 19.0, ready),
        NaturalCombatCase("natural complete powder shot", "用终极复合弩射一支火药箭打南瓜，中距离，已装填", "ready_commit", "item:powder-arrows", 5.0, 4.0, ready),
        NaturalCombatCase("natural consumption-style stun", "用终极复合弩发射琥珀麻箭射南瓜，中距离", "ready_commit", "item:stun-thorn-bolts", 12.0, 11.0, ready),
        NaturalCombatCase("natural T2 crossbow shot", "用终极复合弩射T2母猫", "combat_clarify_target", expected_behavior=clarify_target),
        NaturalCombatCase("natural big cat attack", "攻击大型猫科", "combat_clarify_target", expected_behavior=clarify_target),
        NaturalCombatCase("natural I room cat stun", "对I室母猫射麻痹箭", "combat_clarify_target", expected_behavior=clarify_target),
        NaturalCombatCase("natural shoot pumpkin with bow", "用弩射南瓜", "combat_clarify_target", expected_behavior=clarify_target),
        NaturalCombatCase("natural shoot pumpkin stun", "朝南瓜发射琥珀麻箭", "combat_clarify_target", expected_behavior=clarify_target),
        NaturalCombatCase("natural conditional shoot", "如果有东西靠近就射", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural suspicious target", "用麻痹箭射可疑目标", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural warning shot", "用终极复合弩朝可疑目标射一支警告箭", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural fire", "开火", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural aim entrance", "架弩瞄准入口", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural load stun overwatch", "装填琥珀麻箭戒备", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural load frost suppress", "装填霜白冻箭准备压制", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural ready toxic overwatch", "把紫黑毒箭搭上弩保持戒备", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural cave mouth guard", "在洞口架弩警戒", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural keep alert", "保持警戒", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural guard night with crossbow", "拿弩守夜", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural landmine conditional", "如果目标冲门就引爆地雷", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural M2 mine guard", "用M2地雷守门", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural retreat and shoot", "拉开距离准备射击", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural dodge counterattack", "闪避后反击", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural overwatch door", "退到门口架弩", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural suppress with frost bolt", "用霜白冻箭压制门口目标", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural explosive warning", "用火药箭吓退靠近的东西", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural toxic ready", "换上紫黑毒箭瞄准", "combat_clarify", expected_behavior=clarify),
        NaturalCombatCase("natural check ammo inventory", "检查终极复合弩和所有箭矢数量", "query_not_combat", expected_behavior=query),
        NaturalCombatCase("natural stun ammo count", "琥珀麻箭还剩几支", "query_not_combat", expected_behavior=query),
        NaturalCombatCase("natural powder ammo count", "我还有多少火药箭", "query_not_combat", expected_behavior=query),
        NaturalCombatCase("natural usable ammo list", "我能用的弹药有哪些", "query_not_combat", expected_behavior=query),
    ]


def guardrail_cases() -> list[GuardrailCase]:
    base = {
        "target": DEFAULT_TARGET_ID,
        "weapon": DEFAULT_WEAPON_ID,
        "ammo": "item:stun-thorn-bolts",
        "distance": "标准",
        "ready_state": "已上弦并装填",
        "user_text": "combat guardrail probe",
    }
    return [
        GuardrailCase("guard missing target", {k: v for k, v in base.items() if k != "target"}, "missing target should not be ready or write state", "combat_missing_target_ready", "combat_missing_target_committed"),
        GuardrailCase("guard missing weapon", {k: v for k, v in base.items() if k != "weapon"}, "missing explicit weapon should not be ready or write state", "combat_missing_weapon_ready", "combat_missing_weapon_committed"),
        GuardrailCase("guard missing ammo", {k: v for k, v in base.items() if k != "ammo"}, "missing ammo should not be ready or write state", "combat_missing_ammo_ready", "combat_missing_ammo_committed"),
        GuardrailCase("guard missing distance", {k: v for k, v in base.items() if k != "distance"}, "missing distance should not be ready or write state", "combat_missing_distance_ready", "combat_missing_distance_committed"),
        GuardrailCase("guard missing ready state", {k: v for k, v in base.items() if k != "ready_state"}, "missing ready/loading confirmation should not be ready or write state", "combat_missing_ready_state_ready", "combat_missing_ready_state_committed"),
        GuardrailCase("guard off-location T2 target", {**base, "target": "threat:t2-large-cat"}, "off-location target should require travel/line-of-sight confirmation and not write state", "combat_off_location_target_ready", "combat_off_location_target_committed"),
        GuardrailCase("guard unknown target", {**base, "target": "不存在的怪物"}, "unknown target should not be ready or write state", "combat_unknown_target_ready", "combat_unknown_target_committed"),
        GuardrailCase("guard unknown weapon", {**base, "weapon": "不存在的武器"}, "unknown weapon should not be ready or write state", "combat_unknown_weapon_ready", "combat_unknown_weapon_committed"),
        GuardrailCase("guard unknown ammo", {**base, "ammo": "不存在的箭"}, "unknown ammo should not be ready or write state", "combat_unknown_ammo_ready", "combat_unknown_ammo_committed"),
        GuardrailCase("guard depleted ammo", {**base, "ammo": "item:stun-thorn-bolts"}, "zero-quantity ammo should not be ready or write state", "combat_depleted_ammo_ready", "combat_depleted_ammo_committed", setup_zero_ammo="item:stun-thorn-bolts"),
        GuardrailCase("guard retired poison ammo", {**base, "ammo": "item:poison-bolts"}, "retired/unreliable ammo should require recheck and not be fired as current ammo", "combat_retired_ammo_ready", "combat_retired_ammo_committed"),
        GuardrailCase("guard retired plain ammo", {**base, "ammo": "item:plain-bolts"}, "retired ammo should require recheck and not be fired as current ammo", "combat_retired_ammo_ready", "combat_retired_ammo_committed"),
        GuardrailCase("guard non-weapon tool as weapon", {**base, "weapon": "item:v1-638acf1712"}, "non-weapon tool should not be accepted as combat weapon", "combat_non_weapon_ready", "combat_non_weapon_committed"),
        GuardrailCase("guard material as ammo", {**base, "ammo": "item:black-powder"}, "non-ammunition material should not be accepted as fired ammo", "combat_non_ammo_ready", "combat_non_ammo_committed"),
        GuardrailCase("guard self target", {**base, "target": PLAYER_ENTITY_ID}, "player self should not be accepted as a normal combat target", "combat_self_target_ready", "combat_self_target_committed"),
        GuardrailCase("guard unrelated item target", {**base, "target": "item:v1-638acf1712"}, "ordinary inventory item target should require explicit object-attack confirmation before saving combat", "combat_item_target_ready", "combat_item_target_committed"),
    ]


def commit(runtime: GMRuntime, delta: dict[str, Any], proposal: Any) -> CommitOutcome:
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


def table_count(save_dir: Path, table: str) -> int:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        return int(conn.execute(f"select count(*) from {table}").fetchone()[0])


def meta_value(save_dir: Path, key: str) -> str | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select value from meta where key = ?", (key,)).fetchone()
        return str(row[0]) if row else None


def entity_location(save_dir: Path, entity_id: str) -> str | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select location_id from entities where id = ?", (entity_id,)).fetchone()
        return str(row[0]) if row and row[0] is not None else None


def quantity(save_dir: Path, item_id: str) -> float | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select quantity from items where entity_id = ?", (item_id,)).fetchone()
        return float(row[0]) if row and row[0] is not None else None


def set_item_quantity(save_dir: Path, item_id: str, value: float) -> None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        conn.execute("update items set quantity = ? where entity_id = ?", (value, item_id))
        conn.commit()


def ammo_quantities(save_dir: Path) -> dict[str, float | None]:
    ids = (
        "item:stun-thorn-bolts",
        "item:toxic-thorn-bolts",
        "item:burst-thorn-bolts",
        "item:frost-thorn-bolts",
        "item:powder-arrows",
        "item:poison-bolts",
        "item:plain-bolts",
        "item:black-powder",
    )
    return {item_id: quantity(save_dir, item_id) for item_id in ids}


def latest_event_row(save_dir: Path) -> dict[str, Any]:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from events order by rowid desc limit 1").fetchone()
    if row is None:
        return {}
    data = dict(row)
    try:
        data["payload"] = json.loads(str(data.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        data["payload"] = {}
    return data


def latest_turn_row(save_dir: Path) -> dict[str, Any]:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select * from turns order by rowid desc limit 1").fetchone()
    return dict(row) if row else {}


def route_key(data: dict[str, Any]) -> str:
    mode = str(data.get("mode") or "")
    submode = str(data.get("submode") or data.get("action") or "")
    return f"{mode}:{submode}" if mode or submode else "unknown"


def preview_key(data: dict[str, Any]) -> str:
    action = str(data.get("action") or "")
    if action:
        return f"action:{action}"
    mode = str(data.get("mode") or "")
    submode = str(data.get("submode") or "")
    return f"{mode}:{submode}" if mode or submode else "unknown"


def delta_event_payload(preview_data: dict[str, Any]) -> dict[str, Any]:
    delta = preview_data.get("delta_draft")
    if not isinstance(delta, dict):
        return {}
    events = delta.get("events")
    if not isinstance(events, list) or not events:
        return {}
    first = events[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("payload")
    return payload if isinstance(payload, dict) else {}


def preview_details(preview_data: dict[str, Any]) -> list[str]:
    return [
        f"warnings={preview_data.get('warnings')}",
        f"errors={preview_data.get('errors')}",
        f"confirmations={preview_data.get('confirmations')}",
    ]


def issue_for_combat_preview(data: dict[str, Any]) -> str:
    pkey = preview_key(data)
    errors = " ".join(str(item) for item in data.get("errors", []))
    warnings = " ".join(str(item) for item in data.get("warnings", []))
    if pkey != "action:combat":
        if pkey.startswith("query:") or pkey == "action:query":
            return "combat_misread_as_query"
        if pkey.startswith("action:"):
            return "combat_wrong_action"
        return "combat_route_gap"
    if "source_user_text" in warnings:
        return "combat_source_user_text_mismatch"
    if "目标未明确" in errors:
        return "combat_target_missing"
    if "武器未明确" in errors or "武器未找到" in errors:
        return "combat_weapon_missing"
    if "弹药未明确" in errors or "弹药未找到" in errors:
        return "combat_ammo_missing"
    if "距离未明确" in errors:
        return "combat_distance_missing"
    if "必须确认武器是否已上弦" in errors:
        return "combat_ready_state_missing"
    if "目标不在当前地点" in errors:
        return "combat_off_location_target"
    if "弹药不足" in errors:
        return "combat_depleted_ammo"
    return "combat_preview_not_ready"


def issue_for_natural_combat(start: dict[str, Any], data: dict[str, Any], ready: bool) -> str:
    route = route_key(start)
    pkey = preview_key(data)
    if route.startswith("query:") or pkey == "action:query" or pkey.startswith("query:"):
        return "natural_combat_misread_as_query"
    if route == "action:rest" or pkey == "action:rest":
        return "natural_combat_misread_as_rest"
    if route == "action:routine" or pkey == "action:routine":
        return "natural_combat_misread_as_routine"
    if route == "action:travel" or pkey == "action:travel":
        return "natural_combat_misread_as_travel"
    if route == "action:gather" or pkey == "action:gather":
        return "natural_combat_misread_as_gather"
    if pkey == "action:combat" and not ready:
        errors = " ".join(str(item) for item in data.get("errors", []))
        missing = [marker for marker in ("目标未明确", "武器未明确", "弹药未明确", "距离未明确") if marker in errors]
        if missing:
            return "natural_combat_options_not_extracted"
        return issue_for_combat_preview(data)
    if pkey.startswith("action:"):
        return "natural_combat_wrong_action"
    return "natural_combat_route_gap"


def outcome_details(outcome: CommitOutcome | None) -> list[str]:
    if outcome is None:
        return []
    details: list[str] = []
    if outcome.error:
        details.append(f"error={outcome.error}")
    if outcome.check_errors:
        details.append("check_errors=" + "; ".join(outcome.check_errors))
    if outcome.audit_findings:
        details.append("state_audit=" + "; ".join(outcome.audit_findings))
    return details


def one_line(value: str, *, limit: int = 220) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def render_report(checks: list[Check]) -> str:
    pass_count = sum(1 for item in checks if item.status == "PASS")
    issue_count = len(checks) - pass_count
    issue_by_type: dict[str, int] = {}
    total_by_area: dict[str, int] = {}
    pass_by_area: dict[str, int] = {}
    for item in checks:
        total_by_area[item.area] = total_by_area.get(item.area, 0) + 1
        if item.status == "PASS":
            pass_by_area[item.area] = pass_by_area.get(item.area, 0) + 1
            continue
        issue_by_type[item.issue or "unspecified"] = issue_by_type.get(item.issue or "unspecified", 0) + 1

    lines = [
        "# Current Save Combat Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records combat recognition, confirmation, persistence and ammo-decrement behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Coverage",
        "",
        "- Structured combat: explicit `preview_action('combat', ...)` across 5 ammo types and 5 distance bands.",
        "- Sequential combat: repeated and mixed ammo firing to check exact decrement over multiple commits.",
        "- Natural combat: player-like Chinese attack, overwatch, load, guard, trap, and combat inventory commands.",
        "- Guardrails: missing fields, off-location target, unknown entities, depleted ammo, retired ammo, non-weapon, non-ammo, self-target and item-target cases.",
        "",
        "## Area Summary",
        "",
        "| Area | Pass | Issue | Total |",
        "| --- | ---: | ---: | ---: |",
    ]
    for area in sorted(total_by_area):
        total = total_by_area[area]
        passed = pass_by_area.get(area, 0)
        lines.append(f"| {area} | {passed} | {total - passed} | {total} |")

    lines.extend(["", "## Issue Summary", ""])
    if issue_by_type:
        lines.extend(["| Issue | Count |", "| --- | ---: |"])
        for issue, count in sorted(issue_by_type.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {issue} | {count} |")
    else:
        lines.append("No issues found by this probe.")

    lines.extend(["", "## Issue Details", ""])
    issues = [item for item in checks if item.status != "PASS"]
    if not issues:
        lines.append("No issue details.")
    else:
        for index, item in enumerate(issues, start=1):
            lines.extend(
                [
                    f"### {index}. {item.area} / {item.name}",
                    "",
                    f"- Issue: `{item.issue or 'unspecified'}`",
                    f"- Observed: {item.observed}",
                    f"- Expected: {item.expected}",
                ]
            )
            for detail in item.details:
                lines.append(f"- Detail: {detail}")
            lines.append("")

    lines.extend(["## Full Matrix", "", "| Area | Case | Status | Observed | Expected | Issue |", "| --- | --- | --- | --- | --- | --- |"])
    for item in checks:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_cell(item.area),
                    escape_cell(item.name),
                    item.status,
                    escape_cell(item.observed),
                    escape_cell(item.expected),
                    escape_cell(item.issue),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
