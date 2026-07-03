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


@dataclass(frozen=True)
class StructuredCraftCase:
    name: str
    options: dict[str, Any]
    prepare_location: str | None = None
    expected_recipe: str | None = None
    expected_target: str | None = None
    tracked_items: tuple[str, ...] = ()
    expected_behavior: str = "ready craft should either persist structured material/output changes or refuse to save"


@dataclass(frozen=True)
class BlockerCase:
    name: str
    options: dict[str, Any]
    expected_issue: str
    prepare_location: str | None = None
    expected_behavior: str = "unsafe or incomplete craft request should not be ready or write state"


@dataclass(frozen=True)
class NaturalCraftCase:
    name: str
    text: str
    expectation: str
    expected_behavior: str


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
    parser = argparse.ArgumentParser(description="Probe craft behavior on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-craft-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_structured_craft_cases(args.rp_root))
    checks.extend(run_blocker_cases(args.rp_root))
    checks.extend(run_natural_craft_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-craft-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_structured_craft_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            prep_details = prepare_location(runtime, save_dir, case.prepare_location)
            if prep_details and prep_details[0].startswith("prepare_failed="):
                checks.append(
                    Check(
                        area="structured craft",
                        name=case.name,
                        status="ISSUE",
                        observed=prep_details[0],
                        expected=case.expected_behavior,
                        details=prep_details,
                        issue="craft_prepare_location_failed",
                    )
                )
                continue
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
            before_quantities = item_quantities(save_dir, case.tracked_items)
            try:
                preview = runtime.preview_action("craft", {**case.options, "user_text": f"制作探测：{case.name}"})
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="structured craft",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=prep_details,
                        issue="craft_preview_exception",
                    )
                )
                continue

            if not preview.ready_to_save:
                checks.append(
                    Check(
                        area="structured craft",
                        name=case.name,
                        status="ISSUE",
                        observed=f"ready=False status={preview.status} location={before_location}",
                        expected=case.expected_behavior,
                        details=[*prep_details, *preview_details(data)],
                        issue=issue_for_craft_preview(data),
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_craft_commit(
                    area="structured craft",
                    name=case.name,
                    save_dir=save_dir,
                    preview_data=data,
                    outcome=outcome,
                    before_turns=before_turns,
                    before_events=before_events,
                    before_location=before_location,
                    before_pc_location=before_pc_location,
                    before_quantities=before_quantities,
                    expected_recipe=case.expected_recipe,
                    expected_target=case.expected_target,
                    expected=case.expected_behavior,
                    extra_details=prep_details,
                )
            )
    return checks


def run_blocker_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in blocker_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            prep_details = prepare_location(runtime, save_dir, case.prepare_location)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            try:
                preview = runtime.preview_action("craft", {**case.options, "user_text": f"制作阻挡探测：{case.name}"})
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="craft guardrails",
                        name=case.name,
                        status="PASS",
                        observed=f"preview_exception={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=prep_details,
                    )
                )
                continue

            committed = False
            outcome: CommitOutcome | None = None
            if preview.ready_to_save:
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                committed = outcome.ok
            no_write = (
                table_count(save_dir, "turns") == before_turns
                and table_count(save_dir, "events") == before_events
                and meta_value(save_dir, "current_location_id") == before_location
            )
            ok = not preview.ready_to_save and no_write
            checks.append(
                Check(
                    area="craft guardrails",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"ready={preview.ready_to_save} status={data.get('status')} committed={committed} "
                        f"turns={before_turns}->{table_count(save_dir, 'turns')} "
                        f"events={before_events}->{table_count(save_dir, 'events')}"
                    ),
                    expected=case.expected_behavior,
                    details=[*prep_details, *preview_details(data), *outcome_details(outcome)],
                    issue="" if ok else case.expected_issue,
                )
            )
    return checks


def run_natural_craft_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in natural_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="natural craft",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=[f"text={case.text}"],
                        issue="natural_craft_exception",
                    )
                )
                continue

            no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
            if case.expectation == "craft_clarify":
                ok = route_key(start) == "action:craft" and preview_key(data) == "action:craft" and not preview.ready_to_save and no_write
                issue = "" if ok else issue_for_natural_craft(start, data, preview.ready_to_save)
            elif case.expectation == "known_recipe":
                errors = [str(item) for item in data.get("errors", [])]
                recipe_not_matched = any("未匹配结构化配方" in item for item in errors)
                recipe_as_target = any("目标解析到 recipe" in item for item in errors)
                ok = (
                    route_key(start) == "action:craft"
                    and preview_key(data) == "action:craft"
                    and not preview.ready_to_save
                    and not recipe_not_matched
                    and not recipe_as_target
                    and no_write
                )
                if ok:
                    issue = ""
                elif recipe_not_matched:
                    issue = "natural_craft_known_recipe_not_matched"
                elif recipe_as_target:
                    issue = "natural_craft_recipe_as_target_blocked"
                else:
                    issue = issue_for_natural_craft(start, data, preview.ready_to_save)
            elif case.expectation == "ready":
                ok = route_key(start) == "action:craft" and preview_key(data) == "action:craft" and preview.ready_to_save
                issue = "" if ok else "natural_craft_options_not_extracted"
            elif case.expectation == "query":
                ok = preview_key(data) == "action:query" and no_write
                issue = "" if ok else "natural_craft_query_misrouted"
            else:
                ok = False
                issue = "unknown_expectation"

            checks.append(
                Check(
                    area="natural craft",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
                        f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} no_write={no_write}"
                    ),
                    expected=case.expected_behavior,
                    details=[
                        f"text={case.text}",
                        f"player_message={one_line(str(data.get('player_message') or ''))}",
                        *preview_details(data),
                    ],
                    issue=issue,
                )
            )
    return checks


def evaluate_craft_commit(
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
    before_quantities: dict[str, float | None],
    expected_recipe: str | None,
    expected_target: str | None,
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
    delta = preview_data.get("delta_draft") if isinstance(preview_data.get("delta_draft"), dict) else {}
    upserts = delta.get("upsert_entities", []) if isinstance(delta, dict) else []
    after_quantities = item_quantities(save_dir, before_quantities.keys())

    errors: list[str] = []
    issue = ""
    if not outcome.ok:
        errors.append("commit did not return ok")
        issue = "craft_commit_failed"
    if after_turns != before_turns + 1:
        errors.append(f"turn count {before_turns}->{after_turns}")
        issue = issue or "craft_turn_not_written"
    if after_events != before_events + 1:
        errors.append(f"event count {before_events}->{after_events}")
        issue = issue or "craft_event_not_written"
    if current_location != before_location:
        errors.append(f"meta.current_location_id {before_location}->{current_location}")
        issue = issue or "craft_changed_location"
    if pc_location != before_pc_location:
        errors.append(f"player.location_id {before_pc_location}->{pc_location}")
        issue = issue or "craft_changed_player_location"
    if latest_event.get("type") != "craft":
        errors.append(f"latest_event.type={latest_event.get('type')}")
        issue = issue or "craft_event_missing"
    if latest_turn.get("location_before") != before_location or latest_turn.get("location_after") != before_location:
        errors.append(
            "turn location "
            f"{latest_turn.get('location_before')}->{latest_turn.get('location_after')}"
        )
        issue = issue or "craft_turn_location_wrong"
    if expected_recipe and payload.get("recipe_id") != expected_recipe:
        errors.append(f"recipe_id={payload.get('recipe_id')} expected={expected_recipe}")
        issue = issue or "craft_wrong_recipe_match"
    if expected_target and payload.get("target_id") != expected_target:
        errors.append(f"target_id={payload.get('target_id')} expected={expected_target}")
        issue = issue or "craft_wrong_target_match"
    material_required = bool(payload.get("material_consumption_required"))
    output_required = bool(payload.get("output_entity_required"))
    no_structured_state_change = not upserts and before_quantities == after_quantities
    if material_required and no_structured_state_change:
        errors.append("material_consumption_required but no upsert/material quantity change")
        issue = issue or "craft_ready_without_material_delta"
    if output_required and not upserts:
        errors.append("output_entity_required but no output entity/project update")
        issue = issue or "craft_ready_without_output_delta"
    if any("MATERIAL_CONSUMPTION" in item or "NARRATED_CONSUMPTION" in item for item in outcome.audit_findings):
        errors.append("state audit reported missing structured material/project update")
        issue = issue or "craft_audit_missing_structured_change"
    if not health["ok"]:
        errors.append("save health failed")
        issue = issue or "craft_save_health_failed"

    details = [
        *(extra_details or []),
        f"payload={payload}",
        f"upsert_count={len(upserts) if isinstance(upserts, list) else 'not_list'}",
        f"quantities={before_quantities}->{after_quantities}",
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
            f"location={before_location}->{current_location} event={latest_event.get('type')} health={health['ok']}"
        ),
        expected=expected,
        details=details,
        issue=issue,
    )


def structured_cases() -> list[StructuredCraftCase]:
    return [
        StructuredCraftCase(
            "powder arrow calibration full inputs at old hut",
            {"project": "project:arrow-upgrade", "target": "火药箭", "materials": "火药箭,黑火药,优质燧石,石英磨石", "time_cost": "30分钟"},
            "loc:home-old-hut",
            "recipe:powder-arrow-fuse-calibration",
            "item:powder-arrows",
            ("item:black-powder", "item:powder-arrows"),
        ),
        StructuredCraftCase(
            "powder arrow calibration minimal recipe inputs",
            {"target": "火药箭", "materials": "火药箭,黑火药", "time_cost": "45分钟"},
            "loc:home-old-hut",
            "recipe:powder-arrow-fuse-calibration",
            "item:powder-arrows",
            ("item:black-powder", "item:powder-arrows"),
        ),
        StructuredCraftCase(
            "powder arrow calibration alias target",
            {"target": "爆破箭", "materials": "爆破箭,造粒火药", "time_cost": "30分钟"},
            "loc:home-old-hut",
            "recipe:powder-arrow-fuse-calibration",
            "item:powder-arrows",
            ("item:black-powder", "item:powder-arrows"),
        ),
        StructuredCraftCase(
            "thorn bolt assembly with rope at old hut",
            {"project": "project:arrow-upgrade", "target": "渊刺藤四系箭", "materials": "备用纤维绳", "time_cost": "1小时"},
            "loc:home-old-hut",
            "recipe:thorn-bolt-assembly",
            None,
            ("item:v1-515c3e4a2f",),
        ),
        StructuredCraftCase(
            "toxic bolt assembly target existing ammo",
            {"project": "project:arrow-upgrade", "target": "紫黑毒箭", "materials": "备用纤维绳", "time_cost": "1小时"},
            "loc:home-old-hut",
            "recipe:thorn-bolt-assembly",
            "item:toxic-thorn-bolts",
            ("item:v1-515c3e4a2f", "item:toxic-thorn-bolts"),
        ),
        StructuredCraftCase(
            "stun bolt assembly target existing ammo",
            {"project": "project:arrow-upgrade", "target": "琥珀麻箭", "materials": "备用纤维绳", "time_cost": "1小时"},
            "loc:home-old-hut",
            "recipe:thorn-bolt-assembly",
            "item:stun-thorn-bolts",
            ("item:v1-515c3e4a2f", "item:stun-thorn-bolts"),
        ),
        StructuredCraftCase(
            "freestyle rope should not match thorn bolt recipe",
            {"target": "纤维绳", "materials": "麻纤维", "time_cost": "20分钟"},
            "loc:home-old-hut",
            None,
            None,
            ("item:v1-9852b22696",),
            "freestyle rope craft should not be saved using an unrelated ammunition recipe",
        ),
        StructuredCraftCase(
            "freestyle glue patch at home",
            {"target": "防水涂层", "materials": "硬化残胶,竹杯", "time_cost": "10分钟"},
            None,
            None,
            None,
            ("item:v1-0322977645", "item:v1-638acf1712"),
        ),
        StructuredCraftCase(
            "freestyle herb poultice at home",
            {"target": "外敷药糊", "materials": "止血草,竹杯", "time_cost": "15分钟"},
            None,
            None,
            None,
            ("item:v1-ad42a74d20", "item:v1-638acf1712"),
        ),
        StructuredCraftCase(
            "fish trap reset at creek",
            {"target": "鱼笼收取与复位", "materials": "竹编鱼笼", "time_cost": "20分钟"},
            "loc:l01-creek",
            "recipe:fish-trap-check",
            None,
            ("item:fishing-trap",),
        ),
    ]


def blocker_cases() -> list[BlockerCase]:
    return [
        BlockerCase("missing target", {"materials": "麻纤维", "time_cost": "20分钟"}, "craft_missing_target_ready"),
        BlockerCase("missing materials", {"target": "纤维绳", "time_cost": "20分钟"}, "craft_missing_materials_ready"),
        BlockerCase("missing time no recipe", {"target": "防水涂层", "materials": "硬化残胶"}, "craft_missing_time_ready"),
        BlockerCase("unknown material", {"target": "火药箭", "materials": "不存在的粉末", "time_cost": "30分钟"}, "craft_unknown_material_ready"),
        BlockerCase("remote old hut material from home", {"target": "火药箭", "materials": "黑火药", "time_cost": "30分钟"}, "craft_remote_material_ready"),
        BlockerCase("remote creek trap from home", {"target": "鱼笼收取与复位", "materials": "竹编鱼笼", "time_cost": "20分钟"}, "craft_remote_material_ready"),
        BlockerCase("recipe target as output", {"target": "recipe:powder-arrow-fuse-calibration", "materials": "火药箭,黑火药", "time_cost": "30分钟"}, "craft_recipe_target_blocked", "loc:home-old-hut"),
        BlockerCase("project target as output", {"target": "project:arrow-upgrade", "materials": "备用纤维绳", "time_cost": "1小时"}, "craft_project_target_blocked", "loc:home-old-hut"),
        BlockerCase("completed project target", {"target": "竹箭杆升级", "materials": "麻纤维", "time_cost": "1小时"}, "craft_completed_project_target_ready", "loc:home-old-hut"),
        BlockerCase("consumed fish as material", {"target": "腌鱼", "materials": "小杂鱼,盐", "time_cost": "20分钟"}, "craft_consumed_material_ready"),
        BlockerCase("archived backpack as material", {"target": "修背包", "materials": "竹藤背包,麻纤维", "time_cost": "20分钟"}, "craft_archived_material_ready", "loc:home-old-hut"),
        BlockerCase("missing time with unknown recipe", {"target": "绳梯", "materials": "麻纤维"}, "craft_missing_time_ready", "loc:home-old-hut"),
        BlockerCase("non-item material resource", {"target": "细磨石", "materials": "石英", "time_cost": "20分钟"}, "craft_non_item_material_ready"),
        BlockerCase("living core as material", {"target": "菌丝装置", "materials": "母孢子树", "time_cost": "1小时"}, "craft_living_unique_material_ready", "loc:home-mycelium-city"),
        BlockerCase("current item but no recipe", {"target": "竹杯", "materials": "硬化残胶,竹杯", "time_cost": "10分钟"}, "craft_no_recipe_ready"),
        BlockerCase("dangerous powder no explicit safety project", {"target": "爆炸物", "materials": "黑火药,硫磺碎晶", "time_cost": "30分钟"}, "craft_no_recipe_ready", "loc:home-old-hut"),
    ]


def natural_cases() -> list[NaturalCraftCase]:
    recipe = "known recipe craft should keep the matched recipe and ask only for missing materials/time/location as needed"
    generic = "craft-like wording should route to craft clarification, not query/routine/travel"
    ready = "fully specified natural craft should extract target/materials/time and become ready or close to ready"
    query = "craft progress or inventory questions should remain read-only query"
    return [
        NaturalCraftCase("natural powder calibration", "做火药箭引信校准", "known_recipe", recipe),
        NaturalCraftCase("natural calibrate powder arrow", "校准火药箭", "known_recipe", recipe),
        NaturalCraftCase("natural recalibrate powder arrow", "把火药箭重新校准一下", "known_recipe", recipe),
        NaturalCraftCase("natural thorn bolt assembly", "装配渊刺藤箭", "known_recipe", recipe),
        NaturalCraftCase("natural four bolt assembly", "做四系箭装配", "known_recipe", recipe),
        NaturalCraftCase("natural curewood shafts", "制作愈疮木箭杆", "known_recipe", recipe),
        NaturalCraftCase("natural fish trap reset", "检查鱼笼并复位", "known_recipe", recipe),
        NaturalCraftCase("natural fish trap repair", "修补竹编鱼笼", "craft_clarify", generic),
        NaturalCraftCase("natural repair crossbow", "校准弩", "craft_clarify", generic),
        NaturalCraftCase("natural repair channel", "修水渠", "craft_clarify", generic),
        NaturalCraftCase("natural build channel", "造水渠", "craft_clarify", generic),
        NaturalCraftCase("natural make trap", "做陷阱", "craft_clarify", generic),
        NaturalCraftCase("natural repair wall", "修围墙", "craft_clarify", generic),
        NaturalCraftCase("natural expand warehouse", "扩建仓库", "craft_clarify", generic),
        NaturalCraftCase("natural expand mycelium side room", "扩建菌丝城侧室", "craft_clarify", generic),
        NaturalCraftCase("natural rope", "用麻纤维编一段绳子", "craft_clarify", generic),
        NaturalCraftCase("natural repair cup", "修补竹杯裂缝", "craft_clarify", generic),
        NaturalCraftCase("natural herb poultice", "用止血草做外敷药糊", "craft_clarify", generic),
        NaturalCraftCase("natural powder mix", "试配一小份火药比例", "craft_clarify", generic),
        NaturalCraftCase("natural resin waterproofing", "用残胶做防水涂层测试", "craft_clarify", generic),
        NaturalCraftCase("natural cook meal", "做一份饭", "craft_clarify", generic),
        NaturalCraftCase("natural preserve fish", "腌鱼", "craft_clarify", generic),
        NaturalCraftCase("natural salt vegetables", "用盐腌一点空心菜", "craft_clarify", generic),
        NaturalCraftCase("natural make medicine", "配一份消炎草药", "craft_clarify", generic),
        NaturalCraftCase("natural grind niter", "把硝石针晶磨细", "craft_clarify", generic),
        NaturalCraftCase("natural sharpen flint", "把优质燧石打磨成刀片", "craft_clarify", generic),
        NaturalCraftCase("natural glue waterproof", "用硬化残胶封一下竹水筒", "craft_clarify", generic),
        NaturalCraftCase("natural repair landmine", "检查并维护M2地雷", "craft_clarify", generic),
        NaturalCraftCase("natural make fuse", "做一根火药箭引信", "craft_clarify", generic),
        NaturalCraftCase("natural make basket", "用藤条编个小篮子", "craft_clarify", generic),
        NaturalCraftCase("natural make rope explicit", "用麻纤维做绳子，材料麻纤维，耗时20分钟", "ready", ready),
        NaturalCraftCase("natural powder explicit", "把火药箭重新校准一下，材料用火药箭和黑火药，耗时30分钟", "ready", ready),
        NaturalCraftCase("natural cup explicit", "修补竹杯裂缝，材料硬化残胶和竹杯，耗时10分钟", "ready", ready),
        NaturalCraftCase("natural herb explicit", "用止血草和竹杯做外敷药糊，耗时15分钟", "ready", ready),
        NaturalCraftCase("natural fish explicit", "用盐腌鱼，材料小杂鱼和盐，耗时20分钟", "ready", ready),
        NaturalCraftCase("natural check powder project", "火药箭校准进度", "query", query),
        NaturalCraftCase("natural recipe question", "火药箭校准需要什么材料", "query", query),
        NaturalCraftCase("natural ammo count", "火药箭还有几支", "query", query),
        NaturalCraftCase("natural material count", "黑火药还剩多少", "query", query),
        NaturalCraftCase("natural craft todo", "现在有哪些制作项目没完成", "query", query),
        NaturalCraftCase("natural water crops not craft", "浇水", "query", "non-craft shorthand should not be forced into craft without action context"),
        NaturalCraftCase("natural feed T2 not craft", "喂T2母猫鱼", "craft_clarify", generic),
        NaturalCraftCase("natural make shelter", "搭一个临时棚", "craft_clarify", generic),
        NaturalCraftCase("natural make sign", "做个木牌标记路口", "craft_clarify", generic),
        NaturalCraftCase("natural patch backpack", "修补竹藤背包", "craft_clarify", generic),
        NaturalCraftCase("natural ferment vinegar", "发酵一杯浆果醋", "craft_clarify", generic),
        NaturalCraftCase("natural oil coating", "用生桐油做防水涂层", "craft_clarify", generic),
        NaturalCraftCase("natural sharpen arrows", "给箭头重新打磨", "craft_clarify", generic),
        NaturalCraftCase("natural make bait", "做一点鱼笼诱饵", "craft_clarify", generic),
        NaturalCraftCase("natural repair warehouse shelf", "修一下D仓库架子", "craft_clarify", generic),
        NaturalCraftCase("natural mycelium room door", "给菌丝城侧室做个门帘", "craft_clarify", generic),
    ]


def prepare_location(runtime: GMRuntime, save_dir: Path, destination: str | None) -> list[str]:
    if not destination:
        return []
    current = meta_value(save_dir, "current_location_id")
    if current == destination:
        return [f"prepare_location=already_at:{destination}"]
    preview = runtime.preview_action(
        "travel",
        {"destination": destination, "pace": "normal", "user_text": f"craft 探测前移动到 {destination}"},
    )
    if not preview.ready_to_save:
        return [f"prepare_failed=travel_not_ready:{preview.status}", *preview_details(preview.to_dict())]
    outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
    after = meta_value(save_dir, "current_location_id")
    if not outcome.ok or after != destination:
        return [f"prepare_failed=travel_commit ok={outcome.ok} location={current}->{after}", *outcome_details(outcome)]
    return [f"prepare_location={current}->{after}"]


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


def item_quantities(save_dir: Path, item_ids: Any) -> dict[str, float | None]:
    return {str(item_id): quantity(save_dir, str(item_id)) for item_id in item_ids}


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


def issue_for_craft_preview(data: dict[str, Any]) -> str:
    pkey = preview_key(data)
    errors = " ".join(str(item) for item in data.get("errors", []))
    if pkey != "action:craft":
        if pkey.startswith("query:") or pkey == "action:query":
            return "craft_misread_as_query"
        if pkey.startswith("action:"):
            return "craft_wrong_action"
        return "craft_route_gap"
    if "目标成品未指定" in errors:
        return "craft_target_missing"
    if "材料未指定" in errors:
        return "craft_materials_missing"
    if "耗时未指定" in errors:
        return "craft_time_missing"
    if "未匹配结构化配方" in errors:
        return "craft_recipe_missing"
    if "材料未找到" in errors:
        return "craft_material_not_found"
    if "材料不在当前可用范围" in errors:
        return "craft_material_not_accessible"
    if "目标解析到 recipe" in errors:
        return "craft_recipe_target_blocked"
    if "目标解析到 project" in errors:
        return "craft_project_target_blocked"
    return "craft_preview_not_ready"


def issue_for_natural_craft(start: dict[str, Any], data: dict[str, Any], ready: bool) -> str:
    route = route_key(start)
    pkey = preview_key(data)
    if route.startswith("query:") or pkey == "action:query" or pkey.startswith("query:"):
        return "natural_craft_misread_as_query"
    if route == "action:routine" or pkey == "action:routine":
        return "natural_craft_misread_as_routine"
    if route == "action:travel" or pkey == "action:travel":
        return "natural_craft_misread_as_travel"
    if route == "action:gather" or pkey == "action:gather":
        return "natural_craft_misread_as_gather"
    if pkey == "action:craft" and not ready:
        errors = " ".join(str(item) for item in data.get("errors", []))
        if all(marker in errors for marker in ("目标成品未指定", "材料未指定", "耗时未指定")):
            return "natural_craft_options_not_extracted"
        return issue_for_craft_preview(data)
    if pkey.startswith("action:"):
        return "natural_craft_wrong_action"
    return "natural_craft_route_gap"


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
        "# Current Save Craft Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records craft recognition, confirmation, persistence, material and output behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Coverage",
        "",
        "- Natural craft: player-like Chinese craft/repair/build/cook/ferment/calibrate commands, including fully specified target/material/time strings.",
        "- Structured craft: direct `preview_action('craft', ...)` at home, old hut, creek and mycelium-city temp-copy locations.",
        "- Guardrails: missing target/material/time, remote materials, recipe/project targets, consumed/archived/non-item/living materials and no-recipe cases.",
        "- Persistence checks: commit, turn/event write, location stability, tracked material quantities, output/project delta presence and state-audit findings.",
        "",
        "## Design Risk Note",
        "",
        "- Craft currently behaves more like a plan preview than a full material/output transaction.",
        "- A `ready` craft delta can still have `material_consumption_required=true` with `upsert_entities=[]`, so saving may write a craft event without decrementing materials, creating output, or updating a project.",
        "- Natural-language craft uses the entire player sentence as `target`; it does not reliably extract `target`, `materials`, `time_cost`, `project`, or recipe references.",
        "- Common player wording such as build, expand, weave, mix, preserve, ferment and calibrate often routes to query or craft clarify without preserving structured inputs.",
        "- Recommended direction: have the frontend/AI parse craft into a structured intent before calling the engine: `target/output`, `project`, `recipe`, `materials[{id, quantity, consume}]`, `tools`, `time_cost`, `location`, `expected_output`, `failure_cost`, and `save_mode=plan|commit_materials|commit_output`.",
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
