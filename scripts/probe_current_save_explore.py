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
TRACKED_CLOCKS = (
    "clock:drought-spring",
    "clock:forest-attention",
    "clock:lake-settlement-suspicion",
    "clock:civilization-rumor",
)


@dataclass(frozen=True)
class StructuredExploreCase:
    name: str
    options: dict[str, Any]
    expected_target: str | None
    expected_kind: str = ""
    expected_behavior: str = "known-target explore should commit one explore event without moving, creating entities or ticking clocks"


@dataclass(frozen=True)
class GuardrailExploreCase:
    name: str
    options: dict[str, Any]
    expectation: str
    expected_behavior: str


@dataclass(frozen=True)
class NaturalExploreCase:
    name: str
    text: str
    expectation: str
    expected_behavior: str
    expected_target: str | None = None
    expected_plan: tuple[str, ...] = ()
    expected_non_explore: str = ""


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
    parser = argparse.ArgumentParser(description="Probe explore behavior on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-explore-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_structured_explore_cases(args.rp_root))
    checks.extend(run_guardrail_cases(args.rp_root))
    checks.extend(run_natural_explore_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-explore-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_structured_explore_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = snapshot(save_dir)
            try:
                preview = runtime.preview_action(
                    "explore",
                    {**case.options, "user_text": f"探索探测：{case.name}"},
                )
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="structured explore",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="explore_preview_exception",
                    )
                )
                continue

            if not preview.ready_to_save:
                checks.append(
                    Check(
                        area="structured explore",
                        name=case.name,
                        status="ISSUE",
                        observed=f"ready=False status={data.get('status')}",
                        expected=case.expected_behavior,
                        details=preview_details(data),
                        issue=issue_for_explore_preview(data),
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_explore_commit(
                    area="structured explore",
                    name=case.name,
                    save_dir=save_dir,
                    preview_data=data,
                    outcome=outcome,
                    before=before,
                    expected_target=case.expected_target,
                    expected_kind=case.expected_kind,
                    expected=case.expected_behavior,
                )
            )
    return checks


def run_guardrail_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in guardrail_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = snapshot(save_dir)
            try:
                preview = runtime.preview_action("explore", {**case.options, "user_text": f"探索阻挡探测：{case.name}"})
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="explore guardrails",
                        name=case.name,
                        status="PASS" if case.expectation == "blocked" else "ISSUE",
                        observed=f"preview_exception={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="" if case.expectation == "blocked" else "explore_preview_exception",
                    )
                )
                continue

            no_write = same_counts(save_dir, before)
            if case.expectation == "blocked":
                ok = not preview.ready_to_save and no_write
                issue = "" if ok else "explore_guardrail_ready_or_written"
                checks.append(
                    Check(
                        area="explore guardrails",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=(
                            f"ready={preview.ready_to_save} status={data.get('status')} "
                            f"turns={before['turns']}->{table_count(save_dir, 'turns')} "
                            f"events={before['events']}->{table_count(save_dir, 'events')}"
                        ),
                        expected=case.expected_behavior,
                        details=preview_details(data),
                        issue=issue,
                    )
                )
                continue

            if case.expectation == "unknown_lead_ready":
                if not preview.ready_to_save:
                    checks.append(
                        Check(
                            area="explore guardrails",
                            name=case.name,
                            status="ISSUE",
                            observed=f"ready=False status={data.get('status')}",
                            expected=case.expected_behavior,
                            details=preview_details(data),
                            issue="unknown_lead_not_ready",
                        )
                    )
                    continue
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                checks.append(
                    evaluate_explore_commit(
                        area="explore guardrails",
                        name=case.name,
                        save_dir=save_dir,
                        preview_data=data,
                        outcome=outcome,
                        before=before,
                        expected_target=None,
                        expected_kind="unknown_lead",
                        expected=case.expected_behavior,
                    )
                )
                continue

            if case.expectation == "palette_ready":
                if not preview.ready_to_save:
                    checks.append(
                        Check(
                            area="palette explore",
                            name=case.name,
                            status="ISSUE",
                            observed=f"ready=False status={data.get('status')}",
                            expected=case.expected_behavior,
                            details=preview_details(data),
                            issue=issue_for_explore_preview(data),
                        )
                    )
                    continue
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                checks.append(
                    evaluate_explore_commit(
                        area="palette explore",
                        name=case.name,
                        save_dir=save_dir,
                        preview_data=data,
                        outcome=outcome,
                        before=before,
                        expected_target=None,
                        expected_kind="palette_candidate",
                        expected=case.expected_behavior,
                    )
                )
                continue

            checks.append(
                Check(
                    area="explore guardrails",
                    name=case.name,
                    status="ISSUE",
                    observed=f"ready={preview.ready_to_save} status={data.get('status')}",
                    expected=case.expected_behavior,
                    details=preview_details(data),
                    issue="unknown_guardrail_expectation",
                )
            )
    return checks


def run_natural_explore_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in natural_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = snapshot(save_dir)
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="natural explore",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=[f"text={case.text}"],
                        issue="natural_explore_exception",
                    )
                )
                continue

            no_write = same_counts(save_dir, before)
            route = route_key(start)
            pkey = preview_key(data)
            details = [
                f"text={case.text}",
                f"start_plan={plan_actions(start)}",
                f"preview_plan={plan_actions(data)}",
                f"player_message={one_line(str(data.get('player_message') or ''))}",
                *explore_delta_details(data),
                *preview_details(data),
            ]

            if case.expectation == "known_ready":
                if pkey != "action:explore" or not preview.ready_to_save:
                    checks.append(natural_issue(case, start, data, preview.ready_to_save, no_write, details))
                    continue
                payload = delta_event_payload(data)
                target_id = str(payload.get("target_id") or "")
                if case.expected_target and target_id != case.expected_target:
                    checks.append(
                        Check(
                            area="natural explore",
                            name=case.name,
                            status="ISSUE",
                            observed=natural_observed(start, data, preview.ready_to_save, no_write),
                            expected=case.expected_behavior,
                            details=details,
                            issue="natural_explore_wrong_target",
                        )
                    )
                    continue
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                checks.append(
                    evaluate_explore_commit(
                        area="natural explore",
                        name=case.name,
                        save_dir=save_dir,
                        preview_data=data,
                        outcome=outcome,
                        before=before,
                        expected_target=case.expected_target,
                        expected_kind="",
                        expected=case.expected_behavior,
                        extra_details=details,
                    )
                )
                continue

            if case.expectation == "clarify_unknown":
                ok = pkey == "action:explore" and not preview.ready_to_save and no_write
                checks.append(
                    Check(
                        area="natural unknown lead",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=natural_observed(start, data, preview.ready_to_save, no_write),
                        expected=case.expected_behavior,
                        details=details,
                        issue="" if ok else issue_for_natural_explore(route, pkey, preview.ready_to_save),
                    )
                )
                continue

            if case.expectation == "unknown_lead_ready":
                ok = pkey == "action:explore" and preview.ready_to_save and delta_event_payload(data).get("target_kind") == "unknown_lead"
                if ok:
                    outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                    checks.append(
                        evaluate_explore_commit(
                            area="natural unknown lead",
                            name=case.name,
                            save_dir=save_dir,
                            preview_data=data,
                            outcome=outcome,
                            before=before,
                            expected_target=None,
                            expected_kind="unknown_lead",
                            expected=case.expected_behavior,
                            extra_details=details,
                        )
                    )
                else:
                    issue = "natural_unknown_lead_not_extracted"
                    if pkey != "action:explore":
                        issue = issue_for_natural_explore(route, pkey, preview.ready_to_save)
                    checks.append(
                        Check(
                            area="natural unknown lead",
                            name=case.name,
                            status="ISSUE",
                            observed=natural_observed(start, data, preview.ready_to_save, no_write),
                            expected=case.expected_behavior,
                            details=details,
                            issue=issue,
                        )
                    )
                continue

            if case.expectation == "composite":
                ok = not preview.ready_to_save and tuple(plan_actions(data)) == case.expected_plan and no_write
                checks.append(
                    Check(
                        area="natural composite explore",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=natural_observed(start, data, preview.ready_to_save, no_write),
                        expected=case.expected_behavior,
                        details=details,
                        issue="" if ok else "natural_explore_composite_plan_wrong",
                    )
                )
                continue

            if case.expectation == "query":
                ok = (route.startswith("query:") or pkey == "action:query" or pkey.startswith("query:")) and no_write
                checks.append(
                    Check(
                        area="explore boundary",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=natural_observed(start, data, preview.ready_to_save, no_write),
                        expected=case.expected_behavior,
                        details=details,
                        issue="" if ok else "explore_query_misrouted",
                    )
                )
                continue

            if case.expectation == "not_explore":
                ok = pkey != "action:explore" and route != "action:explore" and no_write
                if case.expected_non_explore:
                    ok = ok and (pkey == case.expected_non_explore or route == case.expected_non_explore)
                issue = ""
                if not ok:
                    issue = "explore_boundary_commit_ready" if pkey == "action:explore" and preview.ready_to_save else "explore_boundary_wrong_action"
                checks.append(
                    Check(
                        area="explore boundary",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=natural_observed(start, data, preview.ready_to_save, no_write),
                        expected=case.expected_behavior,
                        details=details,
                        issue=issue,
                    )
                )
                continue

            checks.append(
                Check(
                    area="natural explore",
                    name=case.name,
                    status="ISSUE",
                    observed=natural_observed(start, data, preview.ready_to_save, no_write),
                    expected=case.expected_behavior,
                    details=details,
                    issue="unknown_expectation",
                )
            )
    return checks


def evaluate_explore_commit(
    *,
    area: str,
    name: str,
    save_dir: Path,
    preview_data: dict[str, Any],
    outcome: CommitOutcome,
    before: dict[str, Any],
    expected_target: str | None,
    expected_kind: str,
    expected: str,
    extra_details: list[str] | None = None,
) -> Check:
    after = snapshot(save_dir)
    latest_event = latest_event_row(save_dir)
    latest_turn = latest_turn_row(save_dir)
    health = inspect_save_package(save_dir)
    payload = delta_event_payload(preview_data)
    delta = delta_draft(preview_data)

    errors: list[str] = []
    issue = ""
    if not outcome.ok:
        errors.append("commit did not return ok")
        issue = "explore_commit_failed"
    if after["turns"] != before["turns"] + 1:
        errors.append(f"turn count {before['turns']}->{after['turns']}")
        issue = issue or "explore_turn_not_written"
    if after["events"] != before["events"] + 1:
        errors.append(f"event count {before['events']}->{after['events']}")
        issue = issue or "explore_event_not_written"
    if latest_event.get("type") != "explore":
        errors.append(f"latest_event.type={latest_event.get('type')}")
        issue = issue or "explore_event_missing"
    if latest_turn.get("intent") != "explore":
        errors.append(f"latest_turn.intent={latest_turn.get('intent')}")
        issue = issue or "explore_turn_intent_wrong"
    if after["meta"].get("current_location_id") != before["meta"].get("current_location_id"):
        errors.append(
            "meta.current_location_id "
            f"{before['meta'].get('current_location_id')}->{after['meta'].get('current_location_id')}"
        )
        issue = issue or "explore_changed_location"
    if after["pc_location"] != before["pc_location"]:
        errors.append(f"player.location_id {before['pc_location']}->{after['pc_location']}")
        issue = issue or "explore_changed_player_location"
    if expected_target is not None and payload.get("target_id") != expected_target:
        errors.append(f"payload.target_id={payload.get('target_id')} expected={expected_target}")
        issue = issue or "explore_wrong_target"
    if expected_kind and payload.get("target_kind") != expected_kind:
        errors.append(f"payload.target_kind={payload.get('target_kind')} expected={expected_kind}")
        issue = issue or "explore_wrong_target_kind"
    if payload.get("needs_gm_resolution") is not True:
        errors.append("payload.needs_gm_resolution is not true")
        issue = issue or "explore_missing_gm_resolution_flag"
    if after["entities"] != before["entities"]:
        errors.append(f"entity count {before['entities']}->{after['entities']}")
        issue = issue or "explore_created_entities"
    if after["clocks"] != before["clocks"]:
        errors.append(f"clocks changed {before['clocks']}->{after['clocks']}")
        issue = issue or "explore_ticked_clocks"
    if delta.get("upsert_entities"):
        errors.append("delta includes upsert_entities")
        issue = issue or "explore_delta_upserts_entities"
    if delta.get("tick_clocks"):
        errors.append("delta includes tick_clocks")
        issue = issue or "explore_delta_ticks_clocks"
    if not health["ok"]:
        errors.append("save health failed")
        issue = issue or "explore_save_health_failed"

    details = [
        *(extra_details or []),
        f"payload={payload}",
        f"turn={latest_turn}",
        f"event_payload={latest_event.get('payload')}",
        f"entities={before['entities']}->{after['entities']}",
        f"clocks={before['clocks']}->{after['clocks']}",
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
            f"ok={outcome.ok} turns={before['turns']}->{after['turns']} "
            f"events={before['events']}->{after['events']} "
            f"target={payload.get('target_id')} kind={payload.get('target_kind')} "
            f"event={latest_event.get('type')} health={health['ok']}"
        ),
        expected=expected,
        details=details,
        issue=issue,
    )


def structured_cases() -> list[StructuredExploreCase]:
    return [
        StructuredExploreCase("current room by id", {"target": "loc:home-mycelium-house", "approach": "环视"}, "loc:home-mycelium-house"),
        StructuredExploreCase("current room by name", {"target": "六边形菌丝复合屋", "approach": "检查屋内动线"}, "loc:home-mycelium-house"),
        StructuredExploreCase("home clearing", {"target": "围墙领地", "approach": "沿墙检查"}, "loc:home-clearing"),
        StructuredExploreCase("mycelium city", {"target": "地下菌丝城", "approach": "让夏娃同步感知"}, "loc:home-mycelium-city"),
        StructuredExploreCase("old hut", {"target": "旧小屋", "approach": "远离危险品检查"}, "loc:home-old-hut"),
        StructuredExploreCase("creek", {"target": "小溪", "approach": "沿水线观察"}, "loc:l01-creek"),
        StructuredExploreCase("waterfall", {"target": "瀑布深潭", "approach": "远距观察水位和掌印"}, "loc:l06-waterfall"),
        StructuredExploreCase("sulfur spring", {"target": "溪源泉眼", "approach": "检查泉眼扰动"}, "loc:l07-sulfur-spring"),
        StructuredExploreCase("stone trough", {"target": "石槽深潭", "approach": "远离深水边缘"}, "loc:l13-stone-trough"),
        StructuredExploreCase("lake settlement", {"target": "湖边聚落", "approach": "低姿态远距观察"}, "loc:lake-ashmoss-settlement"),
        StructuredExploreCase("drought clock", {"target": "春末干旱", "approach": "对照水位和农田"}, "clock:drought-spring"),
        StructuredExploreCase("forest attention clock", {"target": "森林注意", "approach": "复盘暴露痕迹"}, "clock:forest-attention"),
        StructuredExploreCase("civilization rumor clock", {"target": "文明传闻", "approach": "检查外溢风险"}, "clock:civilization-rumor"),
        StructuredExploreCase("water crops project", {"target": "十六畦浇水维护", "approach": "检查项目压力"}, "project:water-crops"),
        StructuredExploreCase("M2 landmine", {"target": "M2 围栏竹门外地雷", "approach": "不触碰远距离检查"}, "item:landmine-m2"),
        StructuredExploreCase("field plot", {"target": "畦1 红薯", "approach": "看叶片和土面"}, "plot:field-001"),
        StructuredExploreCase("stone tablet", {"target": "An的凿刻石板", "approach": "只看不改动"}, "item:v1-5a357b56c5"),
        StructuredExploreCase("current priorities reference", {"target": "第28天当前优先事项", "approach": "核对今日线索"}, "ref:day-028-current-priorities"),
    ]


def guardrail_cases() -> list[GuardrailExploreCase]:
    return [
        GuardrailExploreCase("missing target", {"approach": "careful"}, "blocked", "missing explore target should not be ready or write state"),
        GuardrailExploreCase("unknown target blocked", {"target": "奇怪的嗡鸣", "approach": "careful"}, "blocked", "unknown target without explicit unknown_lead should not save"),
        GuardrailExploreCase("unknown target allowed bool", {"target": "奇怪的嗡鸣", "approach": "careful", "unknown_lead": True}, "unknown_lead_ready", "explicit unknown_lead should commit as unresolved clue without target_id"),
        GuardrailExploreCase("unknown target allowed text", {"target": "陌生陶片", "approach": "careful", "unknown_lead": "未知线索"}, "unknown_lead_ready", "text unknown_lead flag should commit as unresolved clue without target_id"),
        GuardrailExploreCase("available palette candidate", {"palette_id": "pal:encounter:home-door-trace", "approach": "careful"}, "palette_ready", "available palette explore should commit as palette_candidate and not create known entity"),
        GuardrailExploreCase("out of context palette", {"palette_id": "pal:encounter:distant-smoke-thread", "approach": "careful"}, "blocked", "out-of-context palette should be blocked"),
        GuardrailExploreCase("missing palette", {"palette_id": "pal:missing", "approach": "careful"}, "blocked", "missing palette should be blocked"),
    ]


def natural_cases() -> list[NaturalExploreCase]:
    known = "natural explore should resolve to explore, keep the intended known target, commit one explore event, and not mutate unrelated state"
    unknown_plain = "unknown natural clue should at least stay as explore clarification without writing state"
    unknown_explicit = "explicit unknown-lead wording should set unknown_lead and become a saveable unresolved clue"
    composite = "travel plus explore wording should return a composite plan without writing state"
    boundary = "non-explore intent should not be stolen by broad explore keywords"
    query = "read-only status/count/progress questions should remain query/routine without writing explore events"
    return [
        NaturalExploreCase("natural current room", "探索六边形菌丝复合屋", "known_ready", known, "loc:home-mycelium-house"),
        NaturalExploreCase("natural inspect house", "检查菌丝复合屋屋内有没有异常", "known_ready", known, "loc:home-mycelium-house"),
        NaturalExploreCase("natural home clearing", "检查围墙领地", "known_ready", known, "loc:home-clearing"),
        NaturalExploreCase("natural home defenses", "侦查围墙外侧", "known_ready", known, "loc:home-clearing"),
        NaturalExploreCase("natural old hut", "侦查旧小屋", "known_ready", known, "loc:home-old-hut"),
        NaturalExploreCase("natural old hut dangerous goods", "检查旧小屋危险品封存情况", "known_ready", known, "loc:home-old-hut"),
        NaturalExploreCase("natural creek trace", "搜索L1小溪附近痕迹", "known_ready", known, "loc:l01-creek"),
        NaturalExploreCase("natural creek alias", "调查小溪水线变化", "known_ready", known, "loc:l01-creek"),
        NaturalExploreCase("natural pool", "检查水潭有没有干裂", "known_ready", known, "loc:l02-pool"),
        NaturalExploreCase("natural pinewood", "侦查松林边缘", "known_ready", known, "loc:l03-pinewood"),
        NaturalExploreCase("natural bramble ring", "探索黑荆条圈", "known_ready", known, "loc:l04-bramble-ring"),
        NaturalExploreCase("natural oldwood", "调查老树林腐叶层", "known_ready", known, "loc:l05-oldwood"),
        NaturalExploreCase("natural waterfall", "检查瀑布深潭掌印", "known_ready", known, "loc:l06-waterfall"),
        NaturalExploreCase("natural t5 overlook", "侦查T5瞭望石槽", "known_ready", known, "loc:l06-t5-overlook-trough"),
        NaturalExploreCase("natural sulfur spring", "调查L7泉眼水源", "known_ready", known, "loc:l07-sulfur-spring"),
        NaturalExploreCase("natural stone terrace", "探索碎石台地", "known_ready", known, "loc:l08-stone-terrace"),
        NaturalExploreCase("natural An old home", "调查巨树地下居所", "known_ready", known, "loc:l09-underground-home"),
        NaturalExploreCase("natural river", "侦查森林小河", "known_ready", known, "loc:l10-river"),
        NaturalExploreCase("natural delta", "搜索河口三角洲渔网痕迹", "known_ready", known, "loc:l11-delta"),
        NaturalExploreCase("natural niter point", "检查硝石岩壳裂缝", "known_ready", known, "loc:l12-niter-crust"),
        NaturalExploreCase("natural stone trough", "探索石槽深潭边缘", "known_ready", known, "loc:l13-stone-trough"),
        NaturalExploreCase("natural wetland", "调查腐殖湿地软泥", "known_ready", known, "loc:l14-humus-wetland"),
        NaturalExploreCase("natural grassland cliff", "侦查断崖草原外侧", "known_ready", known, "loc:l15-grassland-cliff"),
        NaturalExploreCase("natural quartz quarry", "检查石英采掘场工具痕", "known_ready", known, "loc:l15-west-quartz-quarry"),
        NaturalExploreCase("natural lake settlement", "远距观察湖边聚落", "known_ready", known, "loc:lake-ashmoss-settlement"),
        NaturalExploreCase("natural drought clock", "检查春末干旱", "known_ready", known, "clock:drought-spring"),
        NaturalExploreCase("natural forest attention", "调查森林注意来源", "known_ready", known, "clock:forest-attention"),
        NaturalExploreCase("natural civilization rumor", "检查文明传闻风险", "known_ready", known, "clock:civilization-rumor"),
        NaturalExploreCase("natural lake suspicion", "调查湖边聚落警惕", "known_ready", known, "clock:lake-settlement-suspicion"),
        NaturalExploreCase("natural water crops project", "调查十六畦浇水压力", "known_ready", known, "project:water-crops"),
        NaturalExploreCase("natural landmine", "检查M2地雷绊线有没有松", "known_ready", known, "item:landmine-m2"),
        NaturalExploreCase("natural field water", "检查畦1红薯土面水分", "known_ready", known, "plot:field-001"),
        NaturalExploreCase("natural stone tablet", "检查An的凿刻石板符号", "known_ready", known, "item:v1-5a357b56c5"),
        NaturalExploreCase("natural pumpkin status", "调查南瓜状态", "known_ready", known, "char:pumpkin-s2"),
        NaturalExploreCase("natural current room english", "inspect current room", "known_ready", known, "loc:home-mycelium-house"),
        NaturalExploreCase("natural drought english", "investigate drought clock", "known_ready", known, "clock:drought-spring"),
        NaturalExploreCase("natural wall english", "scout around the wall", "known_ready", known, "loc:home-clearing"),
        NaturalExploreCase("natural strange hum plain", "探索奇怪的嗡鸣", "clarify_unknown", unknown_plain),
        NaturalExploreCase("natural strange shard plain", "检查陌生陶片的来源", "clarify_unknown", unknown_plain),
        NaturalExploreCase("natural night whistle plain", "搜索夜里哨声来源", "clarify_unknown", unknown_plain),
        NaturalExploreCase("natural unknown hum explicit", "把奇怪的嗡鸣当未知线索探索", "unknown_lead_ready", unknown_explicit),
        NaturalExploreCase("natural unknown footprint explicit", "把围墙外陌生脚印作为未知线索侦查", "unknown_lead_ready", unknown_explicit),
        NaturalExploreCase("natural unknown smoke explicit", "远处烟柱作为未知线索调查", "unknown_lead_ready", unknown_explicit),
        NaturalExploreCase("natural round trip creek", "去小溪探索一圈再回来", "composite", composite, expected_plan=("travel", "explore", "travel")),
        NaturalExploreCase("natural travel then spring explore", "去L7泉眼检查菌丝抽水", "composite", composite, expected_plan=("travel", "explore")),
        NaturalExploreCase("natural travel delta traces", "去河口三角洲搜索渔网痕迹", "composite", composite, expected_plan=("travel", "explore")),
        NaturalExploreCase("natural travel social not pure explore", "去湖边聚落问有没有烟柱线索", "composite", composite, expected_plan=("travel", "social")),
        NaturalExploreCase("natural view around", "查看周围", "query", query),
        NaturalExploreCase("natural forest attention progress", "看看森林注意进度", "query", query),
        NaturalExploreCase("natural ammo count", "检查火药箭数量", "query", query),
        NaturalExploreCase("natural material status", "查看硫磺碎晶还剩多少", "query", query),
        NaturalExploreCase("natural current options", "现在附近有什么可以调查", "query", query),
        NaturalExploreCase("natural gather herbs", "找草药", "not_explore", boundary, expected_non_explore="action:gather"),
        NaturalExploreCase("natural search herbs", "搜索草药", "not_explore", boundary, expected_non_explore="action:gather"),
        NaturalExploreCase("natural collect fiber", "搜索附近可用材料", "not_explore", boundary, expected_non_explore="action:gather"),
        NaturalExploreCase("natural ask pumpkin anomaly", "问南瓜有没有发现异常", "not_explore", boundary, expected_non_explore="action:social"),
        NaturalExploreCase("natural tell An inspect", "告诉An一起检查石板", "not_explore", boundary, expected_non_explore="action:social"),
        NaturalExploreCase("natural armed scout wall", "拿弩侦查围墙外", "not_explore", boundary, expected_non_explore="action:combat"),
        NaturalExploreCase("natural inspect before rest", "休息前检查门闩", "not_explore", boundary, expected_non_explore="action:routine"),
        NaturalExploreCase("natural check traps maintenance", "检查陷阱", "not_explore", boundary, expected_non_explore="action:routine"),
        NaturalExploreCase("natural check tunnels maintenance", "检查菌丝通道", "not_explore", boundary, expected_non_explore="action:routine"),
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


def snapshot(save_dir: Path) -> dict[str, Any]:
    return {
        "turns": table_count(save_dir, "turns"),
        "events": table_count(save_dir, "events"),
        "entities": table_count(save_dir, "entities"),
        "meta": {
            key: meta_value(save_dir, key)
            for key in ("current_location_id", "current_game_day", "current_time_block")
        },
        "pc_location": entity_location(save_dir, PLAYER_ENTITY_ID),
        "clocks": {clock_id: clock_segments(save_dir, clock_id) for clock_id in TRACKED_CLOCKS},
    }


def same_counts(save_dir: Path, before: dict[str, Any]) -> bool:
    return table_count(save_dir, "turns") == before["turns"] and table_count(save_dir, "events") == before["events"]


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


def clock_segments(save_dir: Path, clock_id: str) -> int | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select segments_filled from clocks where entity_id = ?", (clock_id,)).fetchone()
        return int(row[0]) if row and row[0] is not None else None


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


def plan_actions(data: dict[str, Any]) -> list[str]:
    plan = data.get("plan")
    if not isinstance(plan, list):
        return []
    actions: list[str] = []
    for step in plan:
        if isinstance(step, dict):
            action = step.get("action")
            if action:
                actions.append(str(action))
    return actions


def delta_draft(preview_data: dict[str, Any]) -> dict[str, Any]:
    delta = preview_data.get("delta_draft")
    return delta if isinstance(delta, dict) else {}


def delta_event_payload(preview_data: dict[str, Any]) -> dict[str, Any]:
    delta = delta_draft(preview_data)
    events = delta.get("events")
    if not isinstance(events, list) or not events:
        return {}
    first = events[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("payload")
    return payload if isinstance(payload, dict) else {}


def natural_observed(start: dict[str, Any], data: dict[str, Any], ready: bool, no_write: bool) -> str:
    payload = delta_event_payload(data)
    return (
        f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
        f"preview={preview_key(data)} ready={ready} status={data.get('status')} no_write={no_write} "
        f"target={payload.get('target_id')} kind={payload.get('target_kind')} "
        f"plan={plan_actions(data)}"
    )


def natural_issue(
    case: NaturalExploreCase,
    start: dict[str, Any],
    data: dict[str, Any],
    ready: bool,
    no_write: bool,
    details: list[str],
) -> Check:
    route = route_key(start)
    pkey = preview_key(data)
    return Check(
        area="natural explore",
        name=case.name,
        status="ISSUE",
        observed=natural_observed(start, data, ready, no_write),
        expected=case.expected_behavior,
        details=details,
        issue=issue_for_natural_explore(route, pkey, ready),
    )


def issue_for_explore_preview(data: dict[str, Any]) -> str:
    pkey = preview_key(data)
    errors = " ".join(str(item) for item in data.get("errors", []))
    if pkey != "action:explore":
        if pkey.startswith("query:") or pkey == "action:query":
            return "explore_misread_as_query"
        if pkey.startswith("action:"):
            return "explore_wrong_action"
        return "explore_route_gap"
    if "target not found" in errors:
        return "explore_target_not_found"
    if "palette candidate is out_of_context" in errors:
        return "explore_palette_out_of_context"
    if "palette not found" in errors:
        return "explore_palette_not_found"
    if "target" in " ".join(str(item) for item in data.get("missing_required", [])):
        return "explore_target_missing"
    return "explore_preview_not_ready"


def issue_for_natural_explore(route: str, pkey: str, ready: bool) -> str:
    if pkey == "action:explore" and ready:
        return "natural_explore_wrong_ready_state"
    if pkey == "action:explore":
        return "natural_explore_target_unresolved"
    if route.startswith("query:") or pkey.startswith("query:") or pkey == "action:query":
        return "natural_explore_misread_as_query"
    if route == "action:gather" or pkey == "action:gather":
        return "natural_explore_misread_as_gather"
    if route == "action:routine" or pkey == "action:routine":
        return "natural_explore_misread_as_routine"
    if route == "action:social" or pkey == "action:social":
        return "natural_explore_misread_as_social"
    if route == "action:combat" or pkey == "action:combat":
        return "natural_explore_misread_as_combat"
    if route == "action:travel" or pkey == "action:travel":
        return "natural_explore_misread_as_travel"
    if route.startswith("action:") or pkey.startswith("action:"):
        return "natural_explore_wrong_action"
    return "natural_explore_route_gap"


def explore_delta_details(preview_data: dict[str, Any]) -> list[str]:
    delta = delta_draft(preview_data)
    return [
        f"delta_intent={delta.get('intent')}",
        f"delta_summary={one_line(str(delta.get('summary') or ''))}",
        f"payload={delta_event_payload(preview_data)}",
        f"upsert_entities={delta.get('upsert_entities')}",
        f"tick_clocks={delta.get('tick_clocks')}",
    ]


def preview_details(preview_data: dict[str, Any]) -> list[str]:
    return [
        f"warnings={preview_data.get('warnings')}",
        f"errors={preview_data.get('errors')}",
        f"confirmations={preview_data.get('confirmations')}",
    ]


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
        else:
            issue_by_type[item.issue or "unspecified"] = issue_by_type.get(item.issue or "unspecified", 0) + 1

    lines = [
        "# Current Save Explore Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records explore recognition, preview, persistence and target resolution behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Coverage",
        "",
        "- Structured explore: known locations, clocks, project, item/trap, crop plot, reference and explicit unknown leads.",
        "- Natural explore: current base, field/defense checks, L1-L15 locations, water sources, settlement traces, clocks, projects, items and English commands.",
        "- Boundary cases: read-only query, gather/resource search, social requests, armed scouting/combat-like wording, routine maintenance and composite travel+explore plans.",
        "- Persistence checks: commit result, turn/event write, payload target/kind, location stability, entity count, clock stability, state audit and save health.",
        "",
        "## Design Risk Note",
        "",
        "- Structured `explore` is conservative and useful for known targets: it writes an explore event and does not directly create facts, entities or clock ticks.",
        "- Natural-language target extraction is brittle. Some broad wording resolves to unrelated world rules or reference entities instead of the object the player named.",
        "- Explicit unknown-lead wording is not extracted from natural text; only structured `unknown_lead=True` makes unresolved clues saveable.",
        "- `检查/搜索/侦查` overlap heavily with query, gather, routine, combat and social. Without structured intent, maintenance and resource-search commands are often routed through explore or blocked as target-not-found.",
        "- Recommended direction: have the frontend/AI pass structured explore intent with `target_id|target_query`, `target_kind=known|unknown_lead|palette_candidate`, `location_id`, `approach`, `risk_posture`, `touch/collect=false`, and `save_mode=preview|commit`.",
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

    lines.extend(["", "## Issue Summary", "", "| Issue | Count |", "| --- | ---: |"])
    for issue, count in sorted(issue_by_type.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {issue} | {count} |")
    if not issue_by_type:
        lines.append("| none | 0 |")

    lines.extend(["", "## Issue Details", ""])
    for index, item in enumerate(checks, start=1):
        if item.status == "PASS":
            continue
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

    lines.extend(["## Full Results", "", "| Area | Name | Status | Observed | Expected | Issue |", "| --- | --- | --- | --- | --- | --- |"])
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


def escape_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
