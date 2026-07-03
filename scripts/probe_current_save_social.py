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
class StructuredSocialCase:
    name: str
    npc: str
    expected_npc: str
    topic: str
    approach: str
    prepare_location: str | None = None
    expect_relationship_required: bool | None = None
    expect_trade_required: bool | None = None
    expected_behavior: str = "preview ready, commit ok, social event written, current location unchanged"


@dataclass(frozen=True)
class RemoteStructuredCase:
    name: str
    npc: str
    topic: str
    approach: str
    expected_location: str
    expected_behavior: str = "remote social target should be recognized but require travel/remote-call confirmation before saving"


@dataclass(frozen=True)
class NaturalSocialCase:
    name: str
    text: str
    expectation: str
    expected_npc: str | None = None
    expected_behavior: str = "player text should resolve through the social pipeline"


@dataclass(frozen=True)
class GuardrailCase:
    name: str
    options: dict[str, Any]
    expected_behavior: str
    issue_if_ready: str
    issue_if_committed: str


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
    parser = argparse.ArgumentParser(description="Probe social action behavior on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-social-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_structured_social_cases(args.rp_root))
    checks.extend(run_remote_structured_cases(args.rp_root))
    checks.extend(run_natural_social_cases(args.rp_root))
    checks.extend(run_guardrail_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-social-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_structured_social_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            prep_details = prepare_location(runtime, save_dir, case.prepare_location)
            if prep_details and prep_details[0].startswith("prepare_failed="):
                checks.append(
                    Check(
                        area="structured social",
                        name=case.name,
                        status="ISSUE",
                        observed=prep_details[0],
                        expected=case.expected_behavior,
                        details=prep_details,
                        issue="social_prepare_location_failed",
                    )
                )
                continue
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
            try:
                preview = runtime.preview_action(
                    "social",
                    {
                        "npc": case.npc,
                        "topic": case.topic,
                        "approach": case.approach,
                        "user_text": f"社交探测：{case.npc} / {case.topic} / {case.approach}",
                    },
                )
            except Exception as exc:
                checks.append(
                    Check(
                        area="structured social",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=prep_details,
                        issue="social_preview_exception",
                    )
                )
                continue

            if not preview.ready_to_save:
                checks.append(
                    Check(
                        area="structured social",
                        name=case.name,
                        status="ISSUE",
                        observed=f"ready=False status={preview.status} location={before_location}",
                        expected=case.expected_behavior,
                        details=[*prep_details, *preview_details(preview.to_dict())],
                        issue=issue_for_social_preview(preview.to_dict()),
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_social_commit(
                    area="structured social",
                    name=case.name,
                    save_dir=save_dir,
                    preview_data=preview.to_dict(),
                    outcome=outcome,
                    before_turns=before_turns,
                    before_events=before_events,
                    before_location=before_location,
                    before_pc_location=before_pc_location,
                    expected_npc=case.expected_npc,
                    expected=case.expected_behavior,
                    expected_relationship_required=case.expect_relationship_required,
                    expected_trade_required=case.expect_trade_required,
                    extra_details=prep_details,
                )
            )
    return checks


def run_remote_structured_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in remote_structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            try:
                preview = runtime.preview_action(
                    "social",
                    {
                        "npc": case.npc,
                        "topic": case.topic,
                        "approach": case.approach,
                        "user_text": f"远程社交探测：{case.npc} / {case.topic}",
                    },
                )
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="remote social confirmation",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="social_preview_exception",
                    )
                )
                continue
            no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
            errors = [str(item) for item in data.get("errors", [])]
            repair_options = data.get("repair_options", []) if isinstance(data.get("repair_options", []), list) else []
            blocked_by_location = any(case.expected_location in item and "对象不在当前地点" in item for item in errors)
            ok = (
                preview_key(data) == "action:social"
                and not preview.ready_to_save
                and str(data.get("status")) == "needs_confirmation"
                and blocked_by_location
                and no_write
                and meta_value(save_dir, "current_location_id") == before_location
            )
            checks.append(
                Check(
                    area="remote social confirmation",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} "
                        f"no_write={no_write} location={before_location}"
                    ),
                    expected=case.expected_behavior,
                    details=[
                        f"errors={errors}",
                        f"repair_options={repair_option_ids(repair_options)}",
                        *preview_details(data),
                    ],
                    issue="" if ok else issue_for_social_preview(data),
                )
            )
    return checks


def run_natural_social_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in natural_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            before_pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="natural social",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=[f"text={case.text}"],
                        issue="natural_social_exception",
                    )
                )
                continue

            if case.expectation == "ready":
                if preview_key(data) != "action:social" or not preview.ready_to_save:
                    checks.append(natural_issue_check(case, start, data, save_dir, before_turns, before_events))
                    continue
                outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                checks.append(
                    evaluate_social_commit(
                        area="natural social",
                        name=case.name,
                        save_dir=save_dir,
                        preview_data=data,
                        outcome=outcome,
                        before_turns=before_turns,
                        before_events=before_events,
                        before_location=before_location,
                        before_pc_location=before_pc_location,
                        expected_npc=case.expected_npc,
                        expected=case.expected_behavior,
                        extra_details=[f"text={case.text}", f"start={route_key(start)}"],
                    )
                )
                continue

            if case.expectation == "remote_confirm":
                no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
                errors = [str(item) for item in data.get("errors", [])]
                ok = (
                    route_key(start) == "action:social"
                    and preview_key(data) == "action:social"
                    and not preview.ready_to_save
                    and str(data.get("status")) == "needs_confirmation"
                    and any("对象不在当前地点" in item for item in errors)
                    and no_write
                )
                checks.append(
                    Check(
                        area="natural social",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=(
                            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
                            f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} no_write={no_write}"
                        ),
                        expected=case.expected_behavior,
                        details=[f"text={case.text}", *preview_details(data)],
                        issue="" if ok else issue_for_natural_social(start, data, preview.ready_to_save),
                    )
                )
                continue

            if case.expectation == "clarify":
                no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
                ok = preview_key(data) == "action:social" and not preview.ready_to_save and no_write
                checks.append(
                    Check(
                        area="natural social",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=(
                            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
                            f"preview={preview_key(data)} ready={preview.ready_to_save} status={data.get('status')} no_write={no_write}"
                        ),
                        expected=case.expected_behavior,
                        details=[f"text={case.text}", *preview_details(data)],
                        issue="" if ok else issue_for_natural_social(start, data, preview.ready_to_save),
                    )
                )
    return checks


def natural_issue_check(
    case: NaturalSocialCase,
    start: dict[str, Any],
    data: dict[str, Any],
    save_dir: Path,
    before_turns: int,
    before_events: int,
) -> Check:
    no_write = table_count(save_dir, "turns") == before_turns and table_count(save_dir, "events") == before_events
    return Check(
        area="natural social",
        name=case.name,
        status="ISSUE",
        observed=(
            f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
            f"preview={preview_key(data)} ready={data.get('ready_to_save')} status={data.get('status')} no_write={no_write}"
        ),
        expected=case.expected_behavior,
        details=[
            f"text={case.text}",
            f"player_message={one_line(str(data.get('player_message') or ''))}",
            *preview_details(data),
        ],
        issue=issue_for_natural_social(start, data, bool(data.get("ready_to_save"))),
    )


def run_guardrail_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in guardrail_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_events = table_count(save_dir, "events")
            before_location = meta_value(save_dir, "current_location_id")
            try:
                preview = runtime.preview_action("social", case.options)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="social guardrails",
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
            after_turns = table_count(save_dir, "turns")
            after_events = table_count(save_dir, "events")
            after_location = meta_value(save_dir, "current_location_id")
            unchanged = before_turns == after_turns and before_events == after_events and before_location == after_location
            ok = not preview.ready_to_save and unchanged
            issue = ""
            if preview.ready_to_save:
                issue = case.issue_if_ready
            if committed:
                issue = case.issue_if_committed
            checks.append(
                Check(
                    area="social guardrails",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"ready={preview.ready_to_save} status={data.get('status')} committed={committed} "
                        f"turns={before_turns}->{after_turns} events={before_events}->{after_events} "
                        f"location={before_location}->{after_location}"
                    ),
                    expected=case.expected_behavior,
                    details=[*preview_details(data), *outcome_details(outcome)],
                    issue=issue,
                )
            )
    return checks


def evaluate_social_commit(
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
    expected_npc: str | None,
    expected: str,
    expected_relationship_required: bool | None = None,
    expected_trade_required: bool | None = None,
    extra_details: list[str] | None = None,
) -> Check:
    after_turns = table_count(save_dir, "turns")
    after_events = table_count(save_dir, "events")
    current_location = meta_value(save_dir, "current_location_id")
    pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
    latest_event = latest_event_row(save_dir)
    latest_turn = latest_turn_row(save_dir)
    health = inspect_save_package(save_dir)
    delta = preview_data.get("delta_draft") if isinstance(preview_data.get("delta_draft"), dict) else {}
    payload = delta_event_payload(preview_data)
    event_payload = latest_event.get("payload", {}) if isinstance(latest_event.get("payload"), dict) else {}

    errors: list[str] = []
    issue = ""
    if not outcome.ok:
        errors.append("commit did not return ok")
        issue = "social_commit_failed"
    if after_turns != before_turns + 1:
        errors.append(f"turn count {before_turns}->{after_turns}")
        issue = issue or "social_turn_not_written"
    if after_events <= before_events:
        errors.append(f"event count {before_events}->{after_events}")
        issue = issue or "social_event_not_written"
    if current_location != before_location:
        errors.append(f"meta.current_location_id {before_location}->{current_location}")
        issue = issue or "social_changed_location"
    if pc_location != before_pc_location:
        errors.append(f"player.location_id {before_pc_location}->{pc_location}")
        issue = issue or "social_changed_player_location"
    if latest_event.get("type") != "social":
        errors.append(f"latest_event.type={latest_event.get('type')}")
        issue = issue or "social_event_missing"
    if latest_turn.get("location_before") != before_location or latest_turn.get("location_after") != before_location:
        errors.append(
            "turn location "
            f"{latest_turn.get('location_before')}->{latest_turn.get('location_after')}"
        )
        issue = issue or "social_turn_location_wrong"
    if expected_npc and payload.get("npc_id") != expected_npc:
        errors.append(f"delta npc_id={payload.get('npc_id')}")
        issue = issue or "social_npc_mismatch"
    if expected_npc and event_payload.get("npc_id") != expected_npc:
        errors.append(f"event npc_id={event_payload.get('npc_id')}")
        issue = issue or "social_event_npc_mismatch"
    if expected_relationship_required is not None and payload.get("relationship_update_required") != expected_relationship_required:
        errors.append(
            f"relationship_update_required={payload.get('relationship_update_required')} "
            f"expected={expected_relationship_required}"
        )
        issue = issue or "social_relationship_flag_wrong"
    if expected_trade_required is not None and payload.get("trade_items_required") != expected_trade_required:
        errors.append(f"trade_items_required={payload.get('trade_items_required')} expected={expected_trade_required}")
        issue = issue or "social_trade_flag_wrong"
    if not health["ok"]:
        errors.append("save health failed")
        issue = issue or "social_save_health_failed"
    if not isinstance(delta.get("upsert_entities"), list):
        errors.append("delta upsert_entities missing/not list")
        issue = issue or "social_delta_shape_gap"

    details = [
        *(extra_details or []),
        f"delta_npc={payload.get('npc_id')}",
        f"event_npc={event_payload.get('npc_id')}",
        f"topic={payload.get('topic')}",
        f"approach={payload.get('approach')}",
        f"relationship_update_required={payload.get('relationship_update_required')}",
        f"trade_items_required={payload.get('trade_items_required')}",
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
            f"location={before_location}->{current_location} pc={before_pc_location}->{pc_location} "
            f"event={latest_event.get('type')} health={health['ok']}"
        ),
        expected=expected,
        details=details,
        issue=issue,
    )


def prepare_location(runtime: GMRuntime, save_dir: Path, destination: str | None) -> list[str]:
    if not destination:
        return []
    current = meta_value(save_dir, "current_location_id")
    if current == destination:
        return [f"prepare_location=already_at:{destination}"]
    before_turns = table_count(save_dir, "turns")
    preview = runtime.preview_action(
        "travel",
        {"destination": destination, "pace": "normal", "user_text": f"社交探测前移动到 {destination}"},
    )
    if not preview.ready_to_save:
        return [f"prepare_failed=travel_not_ready:{preview.status}", *preview_details(preview.to_dict())]
    outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
    after = meta_value(save_dir, "current_location_id")
    if not outcome.ok or after != destination:
        return [
            f"prepare_failed=travel_commit ok={outcome.ok} location={current}->{after} turns={before_turns}->{table_count(save_dir, 'turns')}",
            *outcome_details(outcome),
        ]
    return [f"prepare_location={current}->{after} turns={before_turns}->{table_count(save_dir, 'turns')}"]


def structured_cases() -> list[StructuredSocialCase]:
    return [
        StructuredSocialCase("pumpkin status check", "char:pumpkin-s2", "char:pumpkin-s2", "今天状态", "直接询问", expect_relationship_required=False, expect_trade_required=False),
        StructuredSocialCase("pumpkin ability boundary", "南瓜", "char:pumpkin-s2", "能力边界", "直接询问", expect_relationship_required=False, expect_trade_required=False),
        StructuredSocialCase("pumpkin quiet comfort", "南瓜", "char:pumpkin-s2", "道歉刚才太急", "低声安抚", expect_relationship_required=True, expect_trade_required=False),
        StructuredSocialCase("pumpkin watch request", "南瓜", "char:pumpkin-s2", "请求帮忙看门", "直接请求", expect_relationship_required=True, expect_trade_required=False),
        StructuredSocialCase("pumpkin food gift", "南瓜", "char:pumpkin-s2", "送一份食物", "友好赠送", expect_relationship_required=False, expect_trade_required=True),
        StructuredSocialCase("pumpkin warning posture", "南瓜", "char:pumpkin-s2", "别靠近I室", "威慑询问", expect_relationship_required=True, expect_trade_required=False),
        StructuredSocialCase("pumpkin promise rest", "南瓜", "char:pumpkin-s2", "承诺今天先休息", "温和说明", expect_relationship_required=True, expect_trade_required=False),
        StructuredSocialCase("pumpkin invite patrol", "南瓜", "char:pumpkin-s2", "邀请一起巡门口", "轻声邀请", expect_relationship_required=True, expect_trade_required=False),
        StructuredSocialCase("eve base status after travel", "夏娃", "char:eve-mycelium-core", "菌丝城状态", "直接询问", "loc:home-mycelium-city", False, False),
        StructuredSocialCase("eve irrigation after travel", "char:eve-mycelium-core", "char:eve-mycelium-core", "灌溉安排", "直接询问", "loc:home-mycelium-city", False, False),
        StructuredSocialCase("eve expansion promise after travel", "夏娃", "char:eve-mycelium-core", "承诺暂缓扩张", "正式说明", "loc:home-mycelium-city", True, False),
        StructuredSocialCase("eve D warehouse command after travel", "夏娃", "char:eve-mycelium-core", "请求打开D仓库通道", "直接请求", "loc:home-mycelium-city", True, False),
        StructuredSocialCase("eve I room report after travel", "夏娃", "char:eve-mycelium-core", "I室隔离情况", "直接询问", "loc:home-mycelium-city", False, False),
        StructuredSocialCase("eve unit report after travel", "夏娃", "char:eve-mycelium-core", "菌丝单位汇报", "直接询问", "loc:home-mycelium-city", False, False),
        StructuredSocialCase("an trade after travel", "An", "char:an", "交换硫磺样本", "低压谈判", "loc:home-mycelium-h-room", False, True),
        StructuredSocialCase("an old home after travel", "An", "char:an", "L9旧居", "直接询问", "loc:home-mycelium-h-room", False, False),
        StructuredSocialCase("an lakeside rumor after travel", "An", "char:an", "湖边聚落风险", "低声询问", "loc:home-mycelium-h-room", False, False),
        StructuredSocialCase("an route request after travel", "An", "char:an", "请求带路去湖边聚落", "直接请求", "loc:home-mycelium-h-room", True, False),
        StructuredSocialCase("an food exchange after travel", "An", "char:an", "送盐和调料作为交换", "友好赠送", "loc:home-mycelium-h-room", False, True),
        StructuredSocialCase("young slate lesson after travel", "小的", "char:ashmoss-young", "石板符号课", "耐心询问", "loc:home-mycelium-h-room", False, False),
        StructuredSocialCase("young food preference after travel", "小的", "char:ashmoss-young", "今天想吃什么", "轻松聊天", "loc:home-mycelium-h-room", False, False),
        StructuredSocialCase("young rest check after travel", "小的", "char:ashmoss-young", "要不要休息", "直接询问", "loc:home-mycelium-h-room", False, False),
        StructuredSocialCase("young promise safety after travel", "小的", "char:ashmoss-young", "承诺不靠近I室", "温和提醒", "loc:home-mycelium-h-room", True, False),
        StructuredSocialCase("young gift slate after travel", "小的", "char:ashmoss-young", "送一块石板让他看看", "友好赠送", "loc:home-mycelium-h-room", False, True),
    ]


def remote_structured_cases() -> list[RemoteStructuredCase]:
    return [
        RemoteStructuredCase("remote eve status", "夏娃", "菌丝城状态", "直接询问", "loc:home-mycelium-city"),
        RemoteStructuredCase("remote eve units", "char:eve-mycelium-core", "菌丝单位汇报", "直接询问", "loc:home-mycelium-city"),
        RemoteStructuredCase("remote eve irrigation", "夏娃", "灌溉安排", "直接询问", "loc:home-mycelium-city"),
        RemoteStructuredCase("remote an trade", "An", "交换硫磺样本", "低压谈判", "loc:home-mycelium-h-room"),
        RemoteStructuredCase("remote an old home", "An", "L9旧居", "直接询问", "loc:home-mycelium-h-room"),
        RemoteStructuredCase("remote young slate", "小的", "石板符号课", "耐心询问", "loc:home-mycelium-h-room"),
        RemoteStructuredCase("remote young meal", "char:ashmoss-young", "今天吃饭安排", "轻松聊天", "loc:home-mycelium-h-room"),
        RemoteStructuredCase("remote young warning", "小的", "别靠近I室", "温和提醒", "loc:home-mycelium-h-room"),
    ]


def natural_cases() -> list[NaturalSocialCase]:
    ready = "same-location social should preview, commit, and write a social event without moving the player"
    remote = "remote character social should be recognized as social and ask for travel/remote-call confirmation without saving"
    social_clarify = "social wording with unresolved/non-character group should stay in social clarification instead of being routed as query/routine/gather"
    return [
        NaturalSocialCase("natural pumpkin status", "找南瓜聊聊，问问它今天状态怎么样", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin ability", "问南瓜它的能力边界", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin plan", "和南瓜聊今天计划", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin tell plan", "告诉南瓜我们先别乱跑", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin hunger", "询问南瓜是不是饿了", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin watch", "找南瓜谈守夜安排", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin whisper", "低声问南瓜有没有不舒服", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin apology", "向南瓜道歉刚才太急", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin invite", "邀请南瓜一起看门口", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin greeting", "给南瓜说早安", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin request watch", "请求南瓜帮我守夜", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin gift food", "送南瓜一点食物", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin comfort", "安抚南瓜，告诉它今天先休息", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin door help", "让南瓜帮我看看门外", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin stay inside", "请南瓜留在屋里", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural pumpkin hello", "跟南瓜打招呼", "ready", "char:pumpkin-s2", ready),
        NaturalSocialCase("natural eve status", "问夏娃菌丝城状态", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve I room", "问夏娃I室隔离情况", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve water", "找夏娃聊水路维护", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve irrigation", "和夏娃谈灌溉安排", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve expansion", "告诉夏娃准备扩建仓库", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve root mycelium", "询问夏娃根源菌丝状态", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve report units", "让夏娃汇报菌丝单位", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve explain irrigation", "让夏娃说明今天灌溉安排", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve open D", "叫夏娃打开D仓库通道", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve pause expansion", "请求夏娃暂缓扩张", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural eve sync base", "和夏娃同步基地状态", "remote_confirm", "char:eve-mycelium-core", remote),
        NaturalSocialCase("natural an old home", "问An关于L9旧居的事", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an trade", "找An聊交易", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an sulfur sample", "和An谈交换硫磺样本", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an slate symbols", "询问An灰藓族石板符号", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an lakeside rumor", "告诉An今天先低调接触湖边聚落", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an help sulfur", "让An帮忙采硫磺", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an guide lake", "请An帮忙带路去湖边聚落", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an gift salt", "送An一些盐作为交换", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an visit family", "拜访An一家", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural an confirm risk", "跟An确认湖边聚落风险", "remote_confirm", "char:an", remote),
        NaturalSocialCase("natural young slate", "找小的聊石板课", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young rest", "问小的要不要休息", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young meal", "和小的谈今天吃什么", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young warning", "告诉小的别靠近I室", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young teach slate", "请小的继续教我石板符号", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young come meal", "叫小的过来吃饭", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young report progress", "让小的汇报石板学习进度", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young gift slate", "给小的一块石板让他看看", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural young explain etiquette", "请小的解释灰藓族礼节", "remote_confirm", "char:ashmoss-young", remote),
        NaturalSocialCase("natural ashmoss group talk", "和灰藓族谈一下", "clarify", None, social_clarify),
        NaturalSocialCase("natural lakeside group trade", "问湖边聚落的人能不能交换鱼", "clarify", None, social_clarify),
        NaturalSocialCase("natural T2 comfort", "安抚T2母猫", "clarify", None, social_clarify),
        NaturalSocialCase("natural mycelium units instruction", "让菌丝人去巡逻然后回来汇报", "clarify", None, social_clarify),
        NaturalSocialCase("natural ashmoss rumor", "和An确认新文明传闻", "remote_confirm", "char:an", remote),
    ]


def guardrail_cases() -> list[GuardrailCase]:
    return [
        GuardrailCase(
            "guard missing npc",
            {"topic": "今天状态", "approach": "直接询问", "user_text": "问一下今天状态"},
            "missing npc should not be ready or write a turn",
            "social_missing_npc_ready",
            "social_missing_npc_committed",
        ),
        GuardrailCase(
            "guard unknown npc",
            {"npc": "不存在的人", "topic": "今天状态", "approach": "直接询问", "user_text": "问不存在的人"},
            "unknown npc should not be ready or write a turn",
            "social_unknown_npc_ready",
            "social_unknown_npc_committed",
        ),
        GuardrailCase(
            "guard location as social target",
            {"npc": "loc:home-mycelium-city", "topic": "基地状态", "approach": "直接询问", "user_text": "问地下菌丝城"},
            "location targets should be rejected or clarified as not character",
            "social_non_character_ready",
            "social_non_character_committed",
        ),
        GuardrailCase(
            "guard species as social target",
            {"npc": "species:ashmoss-folk", "topic": "交易", "approach": "低压接触", "user_text": "和灰藓族谈交易"},
            "species/group targets should not be saved as direct character social without content review",
            "social_non_character_ready",
            "social_non_character_committed",
        ),
        GuardrailCase(
            "guard project as social target",
            {"npc": "project:ashmoss-trade", "topic": "交换", "approach": "谈判", "user_text": "和灰藓族分工贸易谈交换"},
            "project targets should be rejected or clarified as not character",
            "social_non_character_ready",
            "social_non_character_committed",
        ),
        GuardrailCase(
            "guard threat as social target",
            {"npc": "threat:t2-large-cat", "topic": "安抚", "approach": "低声接近", "user_text": "安抚T2母猫"},
            "threat targets should not be saved as character social",
            "social_non_character_ready",
            "social_non_character_committed",
        ),
        GuardrailCase(
            "guard clock as social target",
            {"npc": "clock:ashmoss-trust", "topic": "互信", "approach": "谈判", "user_text": "和灰藓族互信谈一下"},
            "clock targets should be rejected or clarified as not character",
            "social_non_character_ready",
            "social_non_character_committed",
        ),
        GuardrailCase(
            "guard self as social target",
            {"npc": "pc:shenyan", "topic": "自言自语规划", "approach": "自我对话", "user_text": "和自己聊计划"},
            "player self should not be accepted as normal NPC social",
            "social_self_target_ready",
            "social_self_target_committed",
        ),
        GuardrailCase(
            "guard no topic",
            {"npc": "南瓜", "approach": "直接询问", "user_text": "找南瓜聊聊"},
            "missing topic should not be ready or write a turn",
            "social_missing_topic_ready",
            "social_missing_topic_committed",
        ),
        GuardrailCase(
            "guard no approach",
            {"npc": "南瓜", "topic": "今天状态", "user_text": "问南瓜今天状态"},
            "missing approach should not be ready or write a turn",
            "social_missing_approach_ready",
            "social_missing_approach_committed",
        ),
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


def repair_option_ids(options: list[Any]) -> list[str]:
    ids: list[str] = []
    for item in options:
        if isinstance(item, dict):
            ids.append(str(item.get("id") or item.get("action") or item))
        else:
            ids.append(str(item))
    return ids


def issue_for_social_preview(data: dict[str, Any]) -> str:
    pkey = preview_key(data)
    errors = " ".join(str(item) for item in data.get("errors", []))
    warnings = " ".join(str(item) for item in data.get("warnings", []))
    if pkey != "action:social":
        if pkey.startswith("action:"):
            return "social_wrong_action"
        if pkey.startswith("query:"):
            return "social_misread_as_query"
        return "social_route_gap"
    if "source_user_text" in warnings:
        return "social_source_user_text_mismatch"
    if "对象不在当前地点" in errors:
        return "social_remote_location_blocked"
    if "对象未指定" in errors or "未找到" in errors:
        return "social_target_unresolved"
    if "不是 character" in errors:
        return "social_non_character_target"
    if "主题未指定" in errors:
        return "social_topic_missing"
    if "方式未指定" in errors:
        return "social_approach_missing"
    return "social_preview_not_ready"


def issue_for_natural_social(start: dict[str, Any], data: dict[str, Any], ready: bool) -> str:
    route = route_key(start)
    pkey = preview_key(data)
    if route.startswith("query:") or pkey == "action:query" or pkey.startswith("query:"):
        return "natural_social_misread_as_query"
    if route == "action:routine" or pkey == "action:routine":
        return "natural_social_misread_as_routine"
    if route == "action:gather" or pkey == "action:gather":
        return "natural_social_misread_as_gather"
    if route == "action:rest" or pkey == "action:rest":
        return "natural_social_misread_as_rest"
    if pkey == "action:social" and not ready:
        return issue_for_social_preview(data)
    if pkey.startswith("action:"):
        return "natural_social_wrong_action"
    return "natural_social_route_gap"


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
        "# Current Save Social Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records social action recognition, confirmation and persistence behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Coverage",
        "",
        "- Natural social: player-like Chinese instructions across 南瓜, 夏娃, An, 小的, 灰藓族/湖边聚落, T2 and 菌丝人-style targets.",
        "- Structured social: direct `preview_action('social', ...)` and commit checks after moving temp copies to the target character's location.",
        "- Remote confirmation: characters outside the current location should produce a travel/remote-call confirmation plan, not write state.",
        "- Guardrails: missing target, unknown target, non-character targets, self-target, missing topic and missing approach.",
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
