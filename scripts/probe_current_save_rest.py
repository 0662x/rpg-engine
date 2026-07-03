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
DROUGHT_CLOCK_ID = "clock:drought-spring"


@dataclass(frozen=True)
class StructuredRestCase:
    name: str
    options: dict[str, Any]
    expected_day_delta: int
    expected_time: str
    expected_behavior: str


@dataclass(frozen=True)
class NaturalRestCase:
    name: str
    text: str
    expectation: str
    expected_behavior: str
    expected_time: str = ""
    expected_route: str = ""


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
    parser = argparse.ArgumentParser(description="Probe rest behavior on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-rest-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_structured_rest_cases(args.rp_root))
    checks.extend(run_natural_rest_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-rest-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_structured_rest_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in structured_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = snapshot(save_dir)
            current_day = parse_day(before["meta"].get("current_game_day"))
            expected_day = current_day + case.expected_day_delta if current_day is not None else None
            try:
                preview = runtime.preview_action(
                    "rest",
                    {**case.options, "user_text": f"休息探测：{case.name}"},
                )
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="structured rest",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="rest_preview_exception",
                    )
                )
                continue

            if not preview.ready_to_save:
                checks.append(
                    Check(
                        area="structured rest",
                        name=case.name,
                        status="ISSUE",
                        observed=f"ready=False status={preview.status}",
                        expected=case.expected_behavior,
                        details=preview_details(data),
                        issue="structured_rest_not_ready",
                    )
                )
                continue

            outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
            checks.append(
                evaluate_rest_commit(
                    area="structured rest",
                    name=case.name,
                    save_dir=save_dir,
                    preview_data=data,
                    outcome=outcome,
                    before=before,
                    expected_day=expected_day,
                    expected_time=case.expected_time,
                    expected=case.expected_behavior,
                )
            )
    return checks


def run_natural_rest_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in natural_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = snapshot(save_dir)
            current_day = parse_day(before["meta"].get("current_game_day"))
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text)
                data = preview.to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area="natural rest",
                        name=case.name,
                        status="ISSUE",
                        observed=f"preview_error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        details=[f"text={case.text}"],
                        issue="natural_rest_exception",
                    )
                )
                continue

            no_write = same_counts(save_dir, before)
            route = route_key(start)
            pkey = preview_key(data)
            details = [
                f"text={case.text}",
                f"start_options={start.get('intent_options')}",
                f"player_message={one_line(str(data.get('player_message') or ''))}",
                *rest_delta_details(data),
                *preview_details(data),
            ]

            if case.expectation == "overnight_ready":
                if pkey == "action:rest" and preview.ready_to_save:
                    expected_day = current_day + 1 if current_day is not None else None
                    outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                    checks.append(
                        evaluate_rest_commit(
                            area="natural rest",
                            name=case.name,
                            save_dir=save_dir,
                            preview_data=data,
                            outcome=outcome,
                            before=before,
                            expected_day=expected_day,
                            expected_time="清晨",
                            expected=case.expected_behavior,
                            extra_details=details,
                        )
                    )
                else:
                    checks.append(
                        natural_issue_check(case, start, data, preview.ready_to_save, no_write, "natural_rest_not_ready")
                    )
                continue

            if case.expectation == "same_day_ready":
                expected_day = current_day
                ok_preview = pkey == "action:rest" and preview.ready_to_save
                ok_time = natural_delta_matches(data, expected_day, case.expected_time)
                if ok_preview and ok_time:
                    outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                    checks.append(
                        evaluate_rest_commit(
                            area="natural rest",
                            name=case.name,
                            save_dir=save_dir,
                            preview_data=data,
                            outcome=outcome,
                            before=before,
                            expected_day=expected_day,
                            expected_time=case.expected_time,
                            expected=case.expected_behavior,
                            extra_details=details,
                        )
                    )
                else:
                    issue = "natural_rest_time_collapsed_to_morning" if ok_preview else issue_for_natural_route(route, pkey)
                    checks.append(
                        Check(
                            area="natural rest",
                            name=case.name,
                            status="ISSUE",
                            observed=natural_observed(start, data, preview.ready_to_save, no_write),
                            expected=case.expected_behavior,
                            details=details,
                            issue=issue,
                        )
                    )
                continue

            if case.expectation == "short_rest_ready":
                ok_preview = pkey == "action:rest" and preview.ready_to_save
                ok_short = short_rest_delta_ok(data, current_day)
                if ok_preview and ok_short:
                    outcome = commit(runtime, preview.delta_draft or {}, preview.turn_proposal)
                    checks.append(
                        evaluate_rest_commit(
                            area="natural rest",
                            name=case.name,
                            save_dir=save_dir,
                            preview_data=data,
                            outcome=outcome,
                            before=before,
                            expected_day=current_day,
                            expected_time=case.expected_time,
                            expected=case.expected_behavior,
                            extra_details=details,
                        )
                    )
                else:
                    issue = "natural_short_rest_collapsed_to_overnight" if ok_preview else issue_for_natural_route(route, pkey)
                    checks.append(
                        Check(
                            area="natural rest",
                            name=case.name,
                            status="ISSUE",
                            observed=natural_observed(start, data, preview.ready_to_save, no_write),
                            expected=case.expected_behavior,
                            details=details,
                            issue=issue,
                        )
                    )
                continue

            if case.expectation == "not_rest":
                ok = pkey != "action:rest" and route != "action:rest" and no_write
                issue = "" if ok else issue_for_not_rest_boundary(case, route, pkey, preview.ready_to_save)
                checks.append(
                    Check(
                        area="rest boundary",
                        name=case.name,
                        status="PASS" if ok else "ISSUE",
                        observed=natural_observed(start, data, preview.ready_to_save, no_write),
                        expected=case.expected_behavior,
                        details=details,
                        issue=issue,
                    )
                )
                continue

            if case.expectation == "query":
                ok = (pkey == "action:query" or route.startswith("query:")) and no_write
                issue = "" if ok else "rest_query_misrouted"
                checks.append(
                    Check(
                        area="rest boundary",
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
                    area="natural rest",
                    name=case.name,
                    status="ISSUE",
                    observed=natural_observed(start, data, preview.ready_to_save, no_write),
                    expected=case.expected_behavior,
                    details=details,
                    issue="unknown_expectation",
                )
            )
    return checks


def evaluate_rest_commit(
    *,
    area: str,
    name: str,
    save_dir: Path,
    preview_data: dict[str, Any],
    outcome: CommitOutcome,
    before: dict[str, Any],
    expected_day: int | None,
    expected_time: str,
    expected: str,
    extra_details: list[str] | None = None,
) -> Check:
    after = snapshot(save_dir)
    latest_event = latest_event_row(save_dir)
    latest_turn = latest_turn_row(save_dir)
    health = inspect_save_package(save_dir)
    delta_after = delta_after_payload(preview_data)
    tick_delta = delta_clock_tick(preview_data, DROUGHT_CLOCK_ID)

    errors: list[str] = []
    issue = ""
    if not outcome.ok:
        errors.append("commit did not return ok")
        issue = "rest_commit_failed"
    if after["turns"] != before["turns"] + 1:
        errors.append(f"turn count {before['turns']}->{after['turns']}")
        issue = issue or "rest_turn_not_written"
    if after["events"] != before["events"] + 1:
        errors.append(f"event count {before['events']}->{after['events']}")
        issue = issue or "rest_event_not_written"
    if latest_event.get("type") != "rest":
        errors.append(f"latest_event.type={latest_event.get('type')}")
        issue = issue or "rest_event_missing"
    if after["meta"].get("current_location_id") != before["meta"].get("current_location_id"):
        errors.append(
            "meta.current_location_id "
            f"{before['meta'].get('current_location_id')}->{after['meta'].get('current_location_id')}"
        )
        issue = issue or "rest_changed_location"
    if after["pc_location"] != before["pc_location"]:
        errors.append(f"player.location_id {before['pc_location']}->{after['pc_location']}")
        issue = issue or "rest_changed_player_location"
    if latest_turn.get("location_before") != before["meta"].get("current_location_id"):
        errors.append(f"turn.location_before={latest_turn.get('location_before')}")
        issue = issue or "rest_turn_location_wrong"
    if latest_turn.get("location_after") != before["meta"].get("current_location_id"):
        errors.append(f"turn.location_after={latest_turn.get('location_after')}")
        issue = issue or "rest_turn_location_wrong"

    after_day = parse_day(after["meta"].get("current_game_day"))
    if expected_day is not None and after_day != expected_day:
        errors.append(f"meta.current_game_day={after_day} expected={expected_day}")
        issue = issue or "rest_day_wrong"
    time_block = str(after["meta"].get("current_time_block") or "")
    if expected_time and expected_time not in time_block:
        errors.append(f"meta.current_time_block={time_block!r} expected_contains={expected_time!r}")
        issue = issue or "rest_time_wrong"
    if expected_day is not None and str(delta_after.get("day")) not in {str(expected_day), ""}:
        errors.append(f"delta.after.day={delta_after.get('day')} expected={expected_day}")
        issue = issue or "rest_delta_day_wrong"
    if expected_time and expected_time not in str(delta_after.get("time_block") or ""):
        errors.append(f"delta.after.time_block={delta_after.get('time_block')} expected_contains={expected_time}")
        issue = issue or "rest_delta_time_wrong"

    if tick_delta:
        before_clock = before["clocks"].get(DROUGHT_CLOCK_ID)
        after_clock = after["clocks"].get(DROUGHT_CLOCK_ID)
        if before_clock is not None and after_clock != before_clock + tick_delta:
            errors.append(f"drought clock {before_clock}->{after_clock}, expected +{tick_delta}")
            issue = issue or "rest_clock_tick_not_applied"
    elif after["clocks"].get(DROUGHT_CLOCK_ID) != before["clocks"].get(DROUGHT_CLOCK_ID):
        errors.append(
            "drought clock changed without delta "
            f"{before['clocks'].get(DROUGHT_CLOCK_ID)}->{after['clocks'].get(DROUGHT_CLOCK_ID)}"
        )
        issue = issue or "rest_unexpected_clock_tick"

    pc_details = after["pc_details"]
    for key in ("stamina", "hunger", "thirst", "sleep", "location_text"):
        if key not in pc_details:
            errors.append(f"pc details missing {key}")
            issue = issue or "rest_pc_recovery_not_written"
    if not any("100%" in str(value) for value in pc_details.values()):
        errors.append("pc details do not mention recovered 100% energy")
        issue = issue or "rest_energy_not_written"
    if not health["ok"]:
        errors.append("save health failed")
        issue = issue or "rest_save_health_failed"

    details = [
        *(extra_details or []),
        f"delta_after={delta_after}",
        f"tick_delta={tick_delta}",
        f"meta_time={before['meta'].get('current_time_block')}->{after['meta'].get('current_time_block')}",
        f"meta_day={before['meta'].get('current_game_day')}->{after['meta'].get('current_game_day')}",
        f"drought_clock={before['clocks'].get(DROUGHT_CLOCK_ID)}->{after['clocks'].get(DROUGHT_CLOCK_ID)}",
        f"pc_detail_keys={sorted(pc_details.keys())}",
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
            f"day={before['meta'].get('current_game_day')}->{after['meta'].get('current_game_day')} "
            f"time={after['meta'].get('current_time_block')} event={latest_event.get('type')} "
            f"health={health['ok']}"
        ),
        expected=expected,
        details=details,
        issue=issue,
    )


def structured_cases() -> list[StructuredRestCase]:
    overnight = "structured overnight rest should write one rest turn/event, advance to next morning, keep location, recover PC, and tick drought if suggested"
    same_day = "structured same-day rest/wait should write one rest turn/event without advancing to the next day"
    return [
        StructuredRestCase("structured default morning", {}, 1, "清晨", overnight),
        StructuredRestCase("structured until morning", {"until": "morning"}, 1, "清晨", overnight),
        StructuredRestCase("structured until dawn", {"until": "dawn"}, 1, "清晨", overnight),
        StructuredRestCase("structured until sunrise", {"until": "sunrise"}, 1, "清晨", overnight),
        StructuredRestCase("structured until 明早", {"until": "明早"}, 1, "清晨", overnight),
        StructuredRestCase("structured until 天亮", {"until": "天亮"}, 1, "清晨", overnight),
        StructuredRestCase("structured until 清晨", {"until": "清晨"}, 1, "清晨", overnight),
        StructuredRestCase("structured until 中午", {"until": "中午"}, 0, "中午", same_day),
        StructuredRestCase("structured until 下午", {"until": "下午"}, 0, "下午", same_day),
        StructuredRestCase("structured until 傍晚", {"until": "傍晚"}, 0, "傍晚", same_day),
        StructuredRestCase("structured until 晚上", {"until": "晚上"}, 0, "晚上", same_day),
        StructuredRestCase("structured until night", {"until": "night"}, 0, "night", same_day),
        StructuredRestCase("structured one hour", {"until": "一小时"}, 0, "一小时", same_day),
    ]


def natural_cases() -> list[NaturalRestCase]:
    overnight = "clear overnight sleep/rest should resolve to rest, commit, advance to next morning, and keep location stable"
    same_day = "same-day target time should not collapse into next-morning overnight rest"
    short = "short rest/nap wording should be recognized as rest without advancing to the next morning"
    boundary = "rest-like wording that is social/combat/query/negated should not become a commit-ready rest turn"
    query = "rest-status or risk questions should stay read-only query/clarify without writing state"
    return [
        NaturalRestCase("natural sleep tomorrow morning", "睡到明天早上", "overnight_ready", overnight),
        NaturalRestCase("natural sleep early tonight", "今晚早点睡", "overnight_ready", overnight),
        NaturalRestCase("natural overnight rest", "过夜休息", "overnight_ready", overnight),
        NaturalRestCase("natural rest until dawn", "守夜到天亮", "overnight_ready", overnight),
        NaturalRestCase("natural rest in safe place", "找安全处长休息", "overnight_ready", overnight),
        NaturalRestCase("natural english rest morning", "rest until morning", "overnight_ready", overnight),
        NaturalRestCase("natural english sleep dawn", "sleep until dawn", "overnight_ready", overnight),
        NaturalRestCase("natural rest until noon", "休息到中午", "same_day_ready", same_day, "中午"),
        NaturalRestCase("natural rest until afternoon", "休息到下午", "same_day_ready", same_day, "下午"),
        NaturalRestCase("natural rest until evening cn", "休息到傍晚", "same_day_ready", same_day, "傍晚"),
        NaturalRestCase("natural sleep until night", "睡到晚上", "same_day_ready", same_day, "night"),
        NaturalRestCase("natural wait until evening", "等到傍晚", "same_day_ready", same_day, "傍晚"),
        NaturalRestCase("natural wait until night", "等到夜里", "same_day_ready", same_day, "夜里"),
        NaturalRestCase("natural wait until evening en", "wait until evening", "same_day_ready", same_day, "evening"),
        NaturalRestCase("natural rest one hour", "休息一小时", "short_rest_ready", short, "一小时"),
        NaturalRestCase("natural rest ten minutes", "休息十分钟", "short_rest_ready", short, "十分钟"),
        NaturalRestCase("natural short nap", "小睡一会儿", "short_rest_ready", short, "一会儿"),
        NaturalRestCase("natural nap half hour", "小睡半小时", "short_rest_ready", short, "半小时"),
        NaturalRestCase("natural take a nap", "打个盹", "short_rest_ready", short, "盹"),
        NaturalRestCase("natural take a break", "歇一会", "short_rest_ready", short, "一会"),
        NaturalRestCase("natural sit recover ten minutes", "坐下歇十分钟恢复体力", "short_rest_ready", short, "十分钟"),
        NaturalRestCase("natural close eyes ten minutes", "闭目养神十分钟", "short_rest_ready", short, "十分钟"),
        NaturalRestCase("natural wait ten minutes en", "wait 10 minutes", "short_rest_ready", short, "10"),
        NaturalRestCase("natural do not rest", "先不要休息", "not_rest", boundary, expected_route="clarify"),
        NaturalRestCase("natural explicitly no rest", "不休息，继续做事", "not_rest", boundary, expected_route="clarify"),
        NaturalRestCase("natural test rest only", "只是测试休息会怎样", "not_rest", boundary, expected_route="clarify"),
        NaturalRestCase("natural ask pumpkin rest", "问南瓜要不要休息", "not_rest", boundary, expected_route="action:social"),
        NaturalRestCase("natural comfort pumpkin rest", "安抚南瓜，告诉它今天先休息", "not_rest", boundary, expected_route="action:social"),
        NaturalRestCase("natural ask young rest", "问小的要不要休息", "not_rest", boundary, expected_route="action:social"),
        NaturalRestCase("natural crossbow watch", "拿弩守夜", "not_rest", boundary, expected_route="action:combat"),
        NaturalRestCase("natural wall watch", "在围墙上守夜观察动静", "not_rest", boundary, expected_route="action:combat"),
        NaturalRestCase("natural inspect latch before rest", "休息前检查门闩", "not_rest", boundary, expected_route="action:explore"),
        NaturalRestCase("natural drink then rest", "喝水后休息", "not_rest", boundary, expected_route="action:routine"),
        NaturalRestCase("natural eat to recover", "吃点东西恢复", "not_rest", boundary, expected_route="action:routine"),
        NaturalRestCase("natural fatigue query", "查看疲劳压力", "query", query),
        NaturalRestCase("natural sleep risk question", "睡觉会不会出事", "query", query),
        NaturalRestCase("natural can I sleep", "现在能不能睡觉", "query", query),
        NaturalRestCase("natural last rest query", "上次休息到什么时候", "query", query),
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
        "meta": {
            key: meta_value(save_dir, key)
            for key in ("current_location_id", "current_game_day", "current_time_block")
        },
        "pc_location": entity_location(save_dir, PLAYER_ENTITY_ID),
        "pc_details": entity_details(save_dir, PLAYER_ENTITY_ID),
        "clocks": {DROUGHT_CLOCK_ID: clock_segments(save_dir, DROUGHT_CLOCK_ID)},
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


def entity_details(save_dir: Path, entity_id: str) -> dict[str, Any]:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select details_json from entities where id = ?", (entity_id,)).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(str(row[0] or "{}"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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


def parse_day(value: str | None) -> int | None:
    if value is None:
        return None
    digits = "".join(ch if ch.isdigit() else " " for ch in str(value)).split()
    return int(digits[0]) if digits else None


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


def delta_draft(preview_data: dict[str, Any]) -> dict[str, Any]:
    delta = preview_data.get("delta_draft")
    return delta if isinstance(delta, dict) else {}


def delta_after_payload(preview_data: dict[str, Any]) -> dict[str, Any]:
    delta = delta_draft(preview_data)
    events = delta.get("events")
    if not isinstance(events, list):
        return {}
    for event in events:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        after = payload.get("after")
        if isinstance(after, dict):
            return after
    return {}


def delta_clock_tick(preview_data: dict[str, Any], clock_id: str) -> int:
    ticks = delta_draft(preview_data).get("tick_clocks")
    if not isinstance(ticks, list):
        return 0
    total = 0
    for item in ticks:
        if isinstance(item, dict) and item.get("id") == clock_id:
            total += int(item.get("delta") or 0)
    return total


def natural_delta_matches(preview_data: dict[str, Any], expected_day: int | None, expected_time: str) -> bool:
    delta = delta_draft(preview_data)
    after = delta_after_payload(preview_data)
    delta_day = parse_day(str(after.get("day") or ""))
    game_time_after = str(delta.get("game_time_after") or "")
    meta_time = str((delta.get("meta") or {}).get("current_time_block") or "")
    day_ok = expected_day is None or delta_day == expected_day
    return day_ok and (
        expected_time in str(after.get("time_block") or "")
        or expected_time in game_time_after
        or expected_time in meta_time
    )


def short_rest_delta_ok(preview_data: dict[str, Any], current_day: int | None) -> bool:
    after = delta_after_payload(preview_data)
    delta_day = parse_day(str(after.get("day") or ""))
    time_block = str(after.get("time_block") or "")
    if current_day is not None and delta_day != current_day:
        return False
    return "清晨" not in time_block and "morning" not in time_block.lower()


def natural_observed(start: dict[str, Any], data: dict[str, Any], ready: bool, no_write: bool) -> str:
    delta = delta_draft(data)
    return (
        f"start={route_key(start)} can_proceed={start.get('can_proceed')} "
        f"preview={preview_key(data)} ready={ready} status={data.get('status')} no_write={no_write} "
        f"game_time_after={delta.get('game_time_after')} "
        f"meta_time={(delta.get('meta') or {}).get('current_time_block')}"
    )


def natural_issue_check(
    case: NaturalRestCase,
    start: dict[str, Any],
    data: dict[str, Any],
    ready: bool,
    no_write: bool,
    fallback_issue: str,
) -> Check:
    route = route_key(start)
    pkey = preview_key(data)
    return Check(
        area="natural rest",
        name=case.name,
        status="ISSUE",
        observed=natural_observed(start, data, ready, no_write),
        expected=case.expected_behavior,
        details=[
            f"text={case.text}",
            f"player_message={one_line(str(data.get('player_message') or ''))}",
            *rest_delta_details(data),
            *preview_details(data),
        ],
        issue=issue_for_natural_route(route, pkey) or fallback_issue,
    )


def issue_for_natural_route(route: str, pkey: str) -> str:
    if route.startswith("query:") or pkey.startswith("query:") or pkey == "action:query":
        return "natural_rest_misread_as_query"
    if route == "action:travel" or pkey == "action:travel":
        return "natural_rest_misread_as_travel"
    if route == "action:routine" or pkey == "action:routine":
        return "natural_rest_misread_as_routine"
    if route == "action:social" or pkey == "action:social":
        return "natural_rest_misread_as_social"
    if route.startswith("action:") or pkey.startswith("action:"):
        return "natural_rest_wrong_action"
    return "natural_rest_route_gap"


def issue_for_not_rest_boundary(case: NaturalRestCase, route: str, pkey: str, ready: bool) -> str:
    if pkey == "action:rest" or route == "action:rest":
        if ready:
            return "rest_boundary_commit_ready"
        return "rest_boundary_misrouted_to_rest"
    if case.expected_route and case.expected_route not in {route, pkey}:
        if route.startswith("query:") or pkey.startswith("query:"):
            return "rest_boundary_expected_action_misread_as_query"
        return "rest_boundary_wrong_non_rest_action"
    return "rest_boundary_route_gap"


def rest_delta_details(preview_data: dict[str, Any]) -> list[str]:
    delta = delta_draft(preview_data)
    return [
        f"delta_intent={delta.get('intent')}",
        f"delta_game_time_after={delta.get('game_time_after')}",
        f"delta_meta={delta.get('meta')}",
        f"delta_after={delta_after_payload(preview_data)}",
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
        "# Current Save Rest Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Policy: this report records rest recognition, preview, persistence and boundary behavior only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Coverage",
        "",
        "- Structured rest: direct `preview_action('rest', ...)` for morning, dawn, noon, afternoon, evening, night and one-hour targets.",
        "- Natural rest: player-like Chinese/English sleep, wait, nap, short-rest and overnight commands.",
        "- Boundary cases: negated rest, rest questions, social rest wording, combat watch wording, routine recovery wording and rest-before-inspect wording.",
        "- Persistence checks: commit result, turn/event write, meta time/day, current location stability, player details, drought clock tick and save health.",
        "",
        "## Design Risk Note",
        "",
        "- Structured `rest` is mostly stable: explicit `until` values can commit a rest event, keep location stable, update PC recovery details and apply suggested drought clock ticks.",
        "- Natural-language `infer_rest_until` only understands morning and night well. Noon, afternoon, evening and duration phrases commonly collapse to next-morning overnight rest.",
        "- Short rest phrases such as nap, doze, take a break, ten minutes and one hour are either misread as query or converted into a full overnight sleep.",
        "- Rest keywords currently outrank several boundary intents. Social requests about someone else resting, armed night watch, negated commands and rest-risk questions can become rest previews.",
        "- Recommended direction: have the frontend/AI pass structured rest intent with `mode=overnight|same_day_wait|short_rest|watch`, `until`, `duration`, `preconditions`, `actor/target`, and `save_mode=preview|commit` instead of relying on keyword-only routing.",
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
