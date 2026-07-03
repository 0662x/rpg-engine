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
class StructuredTravelCase:
    name: str
    destination: str
    expected_destination: str
    pace: str = "normal"
    expected_behavior: str = "preview ready, commit ok, current location and player entity move to destination"


@dataclass(frozen=True)
class NaturalTravelCase:
    name: str
    text: str
    expected_destination: str
    expected_behavior: str = "natural language should resolve to travel, commit, and move to the intended destination"


@dataclass(frozen=True)
class ChainStep:
    name: str
    destination: str
    expected_destination: str
    expected_before: str


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
    parser = argparse.ArgumentParser(description="Probe travel/movement behavior on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-travel-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_structured_travel_cases(args.rp_root))
    checks.extend(run_natural_travel_cases(args.rp_root))
    checks.extend(run_chain_cases(args.rp_root))
    checks.extend(run_guardrail_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-travel-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_structured_travel_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_loc = meta_value(save_dir, "current_location_id")
            try:
                preview = runtime.preview_action(
                    "travel",
                    {
                        "destination": case.destination,
                        "pace": case.pace,
                        "user_text": f"移动探测：去{case.destination}",
                    },
                )
            except Exception as exc:
                checks.append(
                    Check(
                        area="structured travel",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="travel_preview_exception",
                    )
                )
                continue

            if not preview.ready_to_save:
                data = preview.to_dict()
                checks.append(
                    Check(
                        area="structured travel",
                        name=case.name,
                        status="ISSUE",
                        observed=f"ready=False status={preview.status} location={before_loc}",
                        expected=case.expected_behavior,
                        details=preview_details(data),
                        issue="travel_preview_not_ready",
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_travel_commit(
                    area="structured travel",
                    name=case.name,
                    save_dir=save_dir,
                    preview_data=preview.to_dict(),
                    outcome=outcome,
                    before_turns=before_turns,
                    before_location=before_loc,
                    expected_destination=case.expected_destination,
                    expected=case.expected_behavior,
                )
            )
    return checks


def run_natural_travel_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in natural_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_loc = meta_value(save_dir, "current_location_id")
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text)
                preview_data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="natural travel",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=[f"text={case.text}"],
                        issue="natural_travel_exception",
                    )
                )
                continue

            start_key = route_key(start)
            pkey = preview_key(preview_data)
            delta_dest = delta_destination(preview_data)
            if pkey != "action:travel" or not preview.ready_to_save:
                checks.append(
                    Check(
                        area="natural travel",
                        name=case.name,
                        status="ISSUE",
                        observed=(
                            f"start={start_key} can_proceed={start.get('can_proceed')} "
                            f"preview={pkey} ready={preview.ready_to_save} status={preview.status} "
                            f"delta_destination={delta_dest}"
                        ),
                        expected=case.expected_behavior,
                        details=[
                            f"text={case.text}",
                            f"player_message={one_line(str(preview_data.get('player_message') or ''))}",
                            *preview_details(preview_data),
                        ],
                        issue=issue_for_natural_travel(start_key, pkey, preview.ready_to_save),
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            check = evaluate_travel_commit(
                area="natural travel",
                name=case.name,
                save_dir=save_dir,
                preview_data=preview_data,
                outcome=outcome,
                before_turns=before_turns,
                before_location=before_loc,
                expected_destination=case.expected_destination,
                expected=case.expected_behavior,
                extra_details=[f"text={case.text}", f"start={start_key}"],
            )
            if check.status == "PASS" and delta_dest != case.expected_destination:
                check.status = "ISSUE"
                check.issue = "natural_travel_destination_mismatch"
                check.details.append(f"delta_destination={delta_dest}")
            checks.append(check)
    return checks


def run_chain_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        for step in chain_steps():
            before_turns = table_count(save_dir, "turns")
            before_loc = meta_value(save_dir, "current_location_id")
            try:
                preview = runtime.preview_action(
                    "travel",
                    {
                        "destination": step.destination,
                        "pace": "normal",
                        "user_text": f"连续移动探测：{step.name}",
                    },
                )
            except Exception as exc:
                checks.append(
                    Check(
                        area="multi-leg travel chain",
                        name=step.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected="each leg should preview, commit, and update location from the previous leg",
                        issue="travel_preview_exception",
                    )
                )
                continue

            if before_loc != step.expected_before:
                checks.append(
                    Check(
                        area="multi-leg travel chain",
                        name=step.name,
                        status="ISSUE",
                        observed=f"before_location={before_loc}",
                        expected=f"previous committed leg should leave character at {step.expected_before}",
                        details=preview_details(preview.to_dict()),
                        issue="travel_chain_previous_location_wrong",
                    )
                )
                break

            if not preview.ready_to_save:
                checks.append(
                    Check(
                        area="multi-leg travel chain",
                        name=step.name,
                        status="ISSUE",
                        observed=f"ready=False status={preview.status} location={before_loc}",
                        expected="each leg should preview, commit, and update location from the previous leg",
                        details=preview_details(preview.to_dict()),
                        issue="travel_preview_not_ready",
                    )
                )
                break

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_travel_commit(
                    area="multi-leg travel chain",
                    name=step.name,
                    save_dir=save_dir,
                    preview_data=preview.to_dict(),
                    outcome=outcome,
                    before_turns=before_turns,
                    before_location=before_loc,
                    expected_destination=step.expected_destination,
                    expected="each leg should preview, commit, and update location from the previous leg",
                )
            )
            if checks[-1].status != "PASS":
                break
    return checks


def run_guardrail_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in guardrail_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before_turns = table_count(save_dir, "turns")
            before_loc = meta_value(save_dir, "current_location_id")
            try:
                preview = runtime.preview_action("travel", case.options)
                preview_data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="travel guardrails",
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
            after_loc = meta_value(save_dir, "current_location_id")
            unchanged = before_loc == after_loc and before_turns == after_turns
            ok = not preview.ready_to_save and unchanged
            issue = ""
            if preview.ready_to_save:
                issue = case.issue_if_ready
            if committed:
                issue = case.issue_if_committed
            checks.append(
                Check(
                    area="travel guardrails",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"ready={preview.ready_to_save} status={preview.status} committed={committed} "
                        f"turns={before_turns}->{after_turns} location={before_loc}->{after_loc}"
                    ),
                    expected=case.expected_behavior,
                    details=[*preview_details(preview_data), *outcome_details(outcome)],
                    issue=issue,
                )
            )
    return checks


def evaluate_travel_commit(
    *,
    area: str,
    name: str,
    save_dir: Path,
    preview_data: dict[str, Any],
    outcome: CommitOutcome,
    before_turns: int,
    before_location: str | None,
    expected_destination: str,
    expected: str,
    extra_details: list[str] | None = None,
) -> Check:
    after_turns = table_count(save_dir, "turns")
    current_location = meta_value(save_dir, "current_location_id")
    pc_location = entity_location(save_dir, PLAYER_ENTITY_ID)
    latest_event = latest_event_row(save_dir)
    latest_turn = latest_turn_row(save_dir)
    health = inspect_save_package(save_dir)
    delta_dest = delta_destination(preview_data)
    payload = delta_event_payload(preview_data)
    estimated_minutes = payload.get("estimated_minutes")
    route_ids = payload.get("route_ids") or []

    errors: list[str] = []
    issue = ""
    if not outcome.ok:
        errors.append("commit did not return ok")
        issue = "travel_commit_failed"
    if after_turns != before_turns + 1:
        errors.append(f"turn count {before_turns}->{after_turns}")
        issue = issue or "travel_turn_not_written"
    if current_location != expected_destination:
        errors.append(f"meta.current_location_id={current_location}")
        issue = issue or "travel_meta_location_not_updated"
    if pc_location != expected_destination:
        errors.append(f"player.location_id={pc_location}")
        issue = issue or "travel_player_location_not_updated"
    if latest_event.get("type") != "travel":
        errors.append(f"latest_event.type={latest_event.get('type')}")
        issue = issue or "travel_event_missing"
    if latest_turn.get("location_before") != before_location or latest_turn.get("location_after") != expected_destination:
        errors.append(
            "turn location "
            f"{latest_turn.get('location_before')}->{latest_turn.get('location_after')}"
        )
        issue = issue or "travel_turn_location_wrong"
    if delta_dest != expected_destination:
        errors.append(f"delta.location_after={delta_dest}")
        issue = issue or "travel_delta_destination_mismatch"
    if not health["ok"]:
        errors.append("save health failed")
        issue = issue or "travel_save_health_failed"

    if before_location != expected_destination and estimated_minutes in {0, "0"}:
        errors.append("estimated_minutes=0 for different locations")
        issue = issue or "travel_unrouted_zero_time"
    if before_location != expected_destination and not route_ids and "未找到结构化路线" in " ".join(
        str(item) for item in preview_data.get("warnings", [])
    ):
        errors.append("no structured route warning")
        issue = issue or "travel_unstructured_route_warning"

    details = [
        *(extra_details or []),
        f"before_location={before_location}",
        f"delta_destination={delta_dest}",
        f"estimated_minutes={estimated_minutes}",
        f"route_ids={route_ids}",
        f"event_payload_to={latest_event.get('payload', {}).get('to_location_id')}",
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
            f"ok={outcome.ok} turns={before_turns}->{after_turns} "
            f"meta={current_location} pc={pc_location} event={latest_event.get('type')} health={health['ok']}"
        ),
        expected=expected,
        details=details,
        issue=issue,
    )


def structured_cases() -> list[StructuredTravelCase]:
    return [
        StructuredTravelCase("structured to surface home clearing", "loc:home-clearing", "loc:home-clearing"),
        StructuredTravelCase("structured to mycelium city", "loc:home-mycelium-city", "loc:home-mycelium-city"),
        StructuredTravelCase("structured to D warehouse", "loc:home-mycelium-d-warehouse", "loc:home-mycelium-d-warehouse"),
        StructuredTravelCase("structured to H room", "loc:home-mycelium-h-room", "loc:home-mycelium-h-room"),
        StructuredTravelCase("structured to old hut/material warehouse", "loc:home-old-hut", "loc:home-old-hut"),
        StructuredTravelCase("structured to creek", "loc:l01-creek", "loc:l01-creek"),
        StructuredTravelCase("structured to pool", "loc:l02-pool", "loc:l02-pool"),
        StructuredTravelCase("structured to pinewood", "loc:l03-pinewood", "loc:l03-pinewood"),
        StructuredTravelCase("structured to bramble ring", "loc:l04-bramble-ring", "loc:l04-bramble-ring"),
        StructuredTravelCase("structured to oldwood", "loc:l05-oldwood", "loc:l05-oldwood"),
        StructuredTravelCase("structured to waterfall", "loc:l06-waterfall", "loc:l06-waterfall"),
        StructuredTravelCase("structured to T5 overlook", "loc:l06-t5-overlook-trough", "loc:l06-t5-overlook-trough"),
        StructuredTravelCase("structured to sulfur spring", "loc:l07-sulfur-spring", "loc:l07-sulfur-spring"),
        StructuredTravelCase("structured to stone terrace", "loc:l08-stone-terrace", "loc:l08-stone-terrace"),
        StructuredTravelCase("structured to An underground home", "loc:l09-underground-home", "loc:l09-underground-home"),
        StructuredTravelCase("structured to river", "loc:l10-river", "loc:l10-river"),
        StructuredTravelCase("structured to river delta", "loc:l11-delta", "loc:l11-delta"),
        StructuredTravelCase("structured to niter crust", "loc:l12-niter-crust", "loc:l12-niter-crust"),
        StructuredTravelCase("structured to stone trough", "loc:l13-stone-trough", "loc:l13-stone-trough"),
        StructuredTravelCase("structured to humus wetland", "loc:l14-humus-wetland", "loc:l14-humus-wetland"),
        StructuredTravelCase("structured to grassland cliff", "loc:l15-grassland-cliff", "loc:l15-grassland-cliff"),
        StructuredTravelCase("structured to ashmoss hearth", "loc:l15-east-ashmoss-hearth", "loc:l15-east-ashmoss-hearth"),
        StructuredTravelCase("structured to quartz quarry", "loc:l15-west-quartz-quarry", "loc:l15-west-quartz-quarry"),
        StructuredTravelCase("structured to ashmoss settlement", "loc:lake-ashmoss-settlement", "loc:lake-ashmoss-settlement"),
    ]


def natural_cases() -> list[NaturalTravelCase]:
    return [
        NaturalTravelCase("natural go to creek", "去小溪", "loc:l01-creek"),
        NaturalTravelCase("natural walk to L1", "走到L1", "loc:l01-creek"),
        NaturalTravelCase("natural reach creek side", "到溪边看看", "loc:l01-creek"),
        NaturalTravelCase("natural go to pool", "去水潭", "loc:l02-pool"),
        NaturalTravelCase("natural go to L2 pool", "去L2水潭", "loc:l02-pool"),
        NaturalTravelCase("natural follow creek to waterfall", "沿溪走到瀑布深潭", "loc:l06-waterfall"),
        NaturalTravelCase("natural go to L6", "去L6", "loc:l06-waterfall"),
        NaturalTravelCase("natural climb to T5 overlook", "爬到T5瞭望石槽", "loc:l06-t5-overlook-trough"),
        NaturalTravelCase("natural go to pinewood", "去松林", "loc:l03-pinewood"),
        NaturalTravelCase("natural walk toward L3", "走向L3", "loc:l03-pinewood"),
        NaturalTravelCase("natural go to bramble ring", "去荆棘圈", "loc:l04-bramble-ring"),
        NaturalTravelCase("natural go to black bramble ring", "去黑荆条圈", "loc:l04-bramble-ring"),
        NaturalTravelCase("natural go to oldwood", "去老树林", "loc:l05-oldwood"),
        NaturalTravelCase("natural go to spring", "去溪源泉眼", "loc:l07-sulfur-spring"),
        NaturalTravelCase("natural go to sulfur spring", "去硫磺泉眼", "loc:l07-sulfur-spring"),
        NaturalTravelCase("natural go to stone terrace", "去碎石台地", "loc:l08-stone-terrace"),
        NaturalTravelCase("natural go to An home", "去An家", "loc:l09-underground-home"),
        NaturalTravelCase("natural go to underground tree home", "去巨树地下居所", "loc:l09-underground-home"),
        NaturalTravelCase("natural go to river", "去森林小河", "loc:l10-river"),
        NaturalTravelCase("natural go to delta", "去河口三角洲", "loc:l11-delta"),
        NaturalTravelCase("natural go to lakeside settlement", "去湖边三人聚落", "loc:lake-ashmoss-settlement"),
        NaturalTravelCase("natural go to ashmoss settlement", "去湖边聚落", "loc:lake-ashmoss-settlement"),
        NaturalTravelCase("natural go to niter point", "去硝石矿点", "loc:l12-niter-crust"),
        NaturalTravelCase("natural go to stone trough", "去石槽深潭", "loc:l13-stone-trough"),
        NaturalTravelCase("natural go to wetland", "去腐殖湿地", "loc:l14-humus-wetland"),
        NaturalTravelCase("natural go to grassland cliff", "去断崖草原", "loc:l15-grassland-cliff"),
        NaturalTravelCase("natural go to old hearth", "去旧火塘", "loc:l15-east-ashmoss-hearth"),
        NaturalTravelCase("natural go to quartz quarry", "去石英采掘场", "loc:l15-west-quartz-quarry"),
        NaturalTravelCase("natural return to surface clearing", "回围墙领地", "loc:home-clearing"),
        NaturalTravelCase("natural return home", "回家", "loc:home-clearing"),
        NaturalTravelCase("natural return to mycelium house", "回六边形菌丝复合屋", "loc:home-mycelium-house"),
        NaturalTravelCase("natural enter underground", "进地下", "loc:home-mycelium-city"),
        NaturalTravelCase("natural go down to mycelium city", "下到地下菌丝城", "loc:home-mycelium-city"),
        NaturalTravelCase("natural go to D warehouse", "去D仓库", "loc:home-mycelium-d-warehouse"),
        NaturalTravelCase("natural go to H room", "去H室", "loc:home-mycelium-h-room"),
        NaturalTravelCase("natural go to material warehouse", "去材料仓库", "loc:home-old-hut"),
        NaturalTravelCase("natural go to old hut", "去旧小屋", "loc:home-old-hut"),
        NaturalTravelCase("natural go up to surface", "上到地表", "loc:home-clearing"),
        NaturalTravelCase("natural leave mycelium house to territory", "从菌丝屋出门到领地", "loc:home-clearing"),
        NaturalTravelCase("natural go to base", "去基地", "loc:home-clearing"),
        NaturalTravelCase("natural return to clearing", "回空地", "loc:home-clearing"),
    ]


def chain_steps() -> list[ChainStep]:
    return [
        ChainStep("chain house to clearing", "loc:home-clearing", "loc:home-clearing", "loc:home-mycelium-house"),
        ChainStep("chain clearing to creek", "loc:l01-creek", "loc:l01-creek", "loc:home-clearing"),
        ChainStep("chain creek to pool", "loc:l02-pool", "loc:l02-pool", "loc:l01-creek"),
        ChainStep("chain pool to waterfall", "loc:l06-waterfall", "loc:l06-waterfall", "loc:l02-pool"),
        ChainStep("chain waterfall to river", "loc:l10-river", "loc:l10-river", "loc:l06-waterfall"),
        ChainStep("chain river to delta", "loc:l11-delta", "loc:l11-delta", "loc:l10-river"),
        ChainStep("chain delta to settlement", "loc:lake-ashmoss-settlement", "loc:lake-ashmoss-settlement", "loc:l11-delta"),
        ChainStep("chain settlement back to delta", "loc:l11-delta", "loc:l11-delta", "loc:lake-ashmoss-settlement"),
        ChainStep("chain delta back to river", "loc:l10-river", "loc:l10-river", "loc:l11-delta"),
        ChainStep("chain river back to waterfall", "loc:l06-waterfall", "loc:l06-waterfall", "loc:l10-river"),
        ChainStep("chain waterfall to An home", "loc:l09-underground-home", "loc:l09-underground-home", "loc:l06-waterfall"),
        ChainStep("chain An home to mycelium city", "loc:home-mycelium-city", "loc:home-mycelium-city", "loc:l09-underground-home"),
        ChainStep("chain city to H room", "loc:home-mycelium-h-room", "loc:home-mycelium-h-room", "loc:home-mycelium-city"),
        ChainStep("chain H room back to city", "loc:home-mycelium-city", "loc:home-mycelium-city", "loc:home-mycelium-h-room"),
        ChainStep("chain city to D warehouse", "loc:home-mycelium-d-warehouse", "loc:home-mycelium-d-warehouse", "loc:home-mycelium-city"),
        ChainStep("chain D warehouse back to city", "loc:home-mycelium-city", "loc:home-mycelium-city", "loc:home-mycelium-d-warehouse"),
        ChainStep("chain city to humus wetland", "loc:l14-humus-wetland", "loc:l14-humus-wetland", "loc:home-mycelium-city"),
        ChainStep("chain wetland to pinewood", "loc:l03-pinewood", "loc:l03-pinewood", "loc:l14-humus-wetland"),
        ChainStep("chain pinewood back to clearing", "loc:home-clearing", "loc:home-clearing", "loc:l03-pinewood"),
        ChainStep("chain clearing back to house", "loc:home-mycelium-house", "loc:home-mycelium-house", "loc:home-clearing"),
    ]


def guardrail_cases() -> list[GuardrailCase]:
    return [
        GuardrailCase(
            "guard missing destination",
            {"pace": "normal", "user_text": "我移动一下"},
            "missing destination should not be ready or write a turn",
            "travel_missing_destination_ready",
            "travel_missing_destination_committed",
        ),
        GuardrailCase(
            "guard nonexistent destination",
            {"destination": "不存在的地点", "pace": "normal", "user_text": "去不存在的地点"},
            "unknown destination should not be ready or write a turn",
            "travel_unknown_destination_ready",
            "travel_unknown_destination_committed",
        ),
        GuardrailCase(
            "guard same current location",
            {"destination": "loc:home-mycelium-house", "pace": "normal", "user_text": "回六边形菌丝复合屋"},
            "same-location travel should be clarified/no-op instead of writing a changed movement turn",
            "travel_same_location_ready",
            "travel_same_location_committed",
        ),
        GuardrailCase(
            "guard retired treehouse location",
            {"destination": "树屋", "pace": "normal", "user_text": "回树屋"},
            "retired historical locations should not be accepted as normal travel destinations",
            "travel_retired_location_ready",
            "travel_retired_location_committed",
        ),
        GuardrailCase(
            "guard retired original clearing",
            {"destination": "原始空地", "pace": "normal", "user_text": "回原始空地"},
            "retired historical locations should not be accepted as normal travel destinations",
            "travel_retired_location_ready",
            "travel_retired_location_committed",
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


def issue_for_natural_travel(start_key: str, preview_route: str, ready: bool) -> str:
    if preview_route.startswith("query:") or start_key.startswith("query:"):
        return "natural_travel_misread_as_query"
    if preview_route == "action:routine" or start_key == "action:routine":
        return "natural_travel_misread_as_routine"
    if preview_route == "action:travel" and not ready:
        return "natural_travel_destination_unresolved"
    if preview_route.startswith("action:"):
        return "natural_travel_wrong_action"
    return "natural_travel_route_gap"


def delta_destination(preview_data: dict[str, Any]) -> str | None:
    delta = preview_data.get("delta_draft")
    if isinstance(delta, dict):
        value = delta.get("location_after")
        return str(value) if value is not None else None
    return None


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
    issue_by_area: dict[str, int] = {}
    total_by_area: dict[str, int] = {}
    pass_by_area: dict[str, int] = {}
    for item in checks:
        total_by_area[item.area] = total_by_area.get(item.area, 0) + 1
        if item.status == "PASS":
            pass_by_area[item.area] = pass_by_area.get(item.area, 0) + 1
            continue
        issue_by_type[item.issue or "unspecified"] = issue_by_type.get(item.issue or "unspecified", 0) + 1
        issue_by_area[item.area] = issue_by_area.get(item.area, 0) + 1

    lines = [
        "# Current Save Travel/Movement Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records movement/travel behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Coverage",
        "",
        "- Structured travel: direct `preview_action('travel', destination=...)` over active known locations.",
        "- Natural travel: player-like Chinese movement commands through `start_turn` + `preview_from_text`.",
        "- Multi-leg chain: committed route sequence that moves across surface, water, settlement, underground, and home nodes.",
        "- Guardrails: missing/unknown/same-location/retired-location movement attempts.",
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
