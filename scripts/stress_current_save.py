from __future__ import annotations

import argparse
import copy
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
from rpg_engine.save_manager import SaveManager
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
    expected: str = ""
    details: list[str] = field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress test the current isekai-farm save on a temporary copy.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_start_turn_checks(args.rp_root))
    checks.extend(run_preview_checks(args.rp_root))
    checks.extend(run_full_chain_checks(args.rp_root))
    checks.extend(run_player_entry_check(args.rp_root))

    report = render_report(checks)
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    return 1 if any(check.status == "FAIL" for check in checks) else 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-stress-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


@contextmanager
def copied_workspace(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-workspace-stress-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        shutil.copytree(rp_root / ".aigm", root / ".aigm")
        pending = root / ".aigm" / "pending-player-action.json"
        if pending.exists():
            pending.unlink()
        yield root


def run_start_turn_checks(rp_root: Path) -> list[Check]:
    cases = [
        {
            "name": "scene query",
            "text": "查看当前场景",
            "accept": [("query", "scene", True)],
        },
        {
            "name": "direct ammo count query",
            "text": "查询琥珀麻箭还剩多少支",
            "accept": [("query", "entity", True)],
        },
        {
            "name": "broad weapon and ammo inventory query",
            "text": "检查终极复合弩和所有箭矢数量",
            "accept": [("query", "entity", True), ("action", "routine", True)],
            "reject": [("action", "explore")],
        },
        {
            "name": "pumpkin status query",
            "text": "查看南瓜状态",
            "accept": [("query", "entity", True)],
        },
        {
            "name": "ask pumpkin status socially",
            "text": "问南瓜状态",
            "accept": [("action", "social", True)],
        },
        {
            "name": "talk to pumpkin in natural language",
            "text": "找南瓜聊聊，问问它今天状态怎么样",
            "accept": [("action", "social", True)],
        },
        {
            "name": "patrol territory",
            "text": "巡视领地，看看大家都在做什么",
            "accept": [("action", "routine", True)],
        },
        {
            "name": "short travel",
            "text": "去围墙领地/家巡查",
            "accept": [("action", "travel", True)],
        },
        {
            "name": "water crops command",
            "text": "给十六畦浇水",
            "accept": [("action", "routine", True), ("action", "craft", True)],
            "reject": [("query", "entity")],
        },
        {
            "name": "drought and water pressure check",
            "text": "检查春末干旱和十六畦浇水压力",
            "accept": [("query", "entity", True), ("action", "routine", True)],
            "reject": [("action", "explore")],
        },
        {
            "name": "pending projects query",
            "text": "当前有哪些待处理项目",
            "accept": [("query", "entity", True), ("query", "scene", True)],
        },
        {
            "name": "compound fish-trap action",
            "text": "去L1小溪收鱼笼",
            "accept": [("action", "composite", False), ("action", "travel", True), ("action", "gather", False)],
        },
        {
            "name": "vague combat should ask clarification",
            "text": "用终极复合弩装填琥珀麻箭戒备射击可疑目标",
            "accept": [("action", "combat", False)],
        },
        {
            "name": "gather inventory-like target",
            "text": "采集空心菜",
            "accept": [("action", "gather", True)],
        },
        {
            "name": "rest",
            "text": "休息到下午",
            "accept": [("action", "rest", True)],
        },
    ]
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        for case in cases:
            try:
                result = runtime.start_turn(case["text"]).to_dict()
                observed_tuple = (result["mode"], result["submode"], bool(result["can_proceed"]))
                status = "PASS" if observed_tuple in case["accept"] else "FAIL"
                for rejected in case.get("reject", []):
                    if observed_tuple[:2] == tuple(rejected):
                        status = "FAIL"
                details = [
                    f"text={case['text']}",
                    f"missing_required={result.get('missing_required')}",
                    f"intent_options={result.get('intent', {}).get('options') if isinstance(result.get('intent'), dict) else None}",
                ]
                checks.append(
                    Check(
                        area="start_turn",
                        name=case["name"],
                        status=status,
                        observed=f"{observed_tuple[0]}:{observed_tuple[1]} can_proceed={observed_tuple[2]}",
                        expected=" or ".join(f"{a}:{b} can_proceed={c}" for a, b, c in case["accept"]),
                        details=details,
                    )
                )
            except Exception as exc:
                checks.append(
                    Check(
                        area="start_turn",
                        name=case["name"],
                        status="FAIL",
                        observed=f"{type(exc).__name__}: {exc}",
                        expected="no exception",
                        details=[f"text={case['text']}"],
                    )
                )
    return checks


def run_preview_checks(rp_root: Path) -> list[Check]:
    cases = [
        {
            "name": "read-only ammo count stays unsaved",
            "text": "查询琥珀麻箭还剩多少支",
            "expect_action": "query",
            "expect_ready": False,
        },
        {
            "name": "patrol can be previewed",
            "text": "巡视领地，看看大家都在做什么",
            "expect_action": "routine",
            "expect_ready": True,
        },
        {
            "name": "crop watering should not become read-only query",
            "text": "给十六畦浇水",
            "expect_action": "routine",
            "expect_ready": True,
        },
        {
            "name": "social preview is generated",
            "text": "找南瓜聊聊，问问它今天状态怎么样",
            "expect_action": "social",
            "expect_ready": True,
        },
        {
            "name": "gather preview is generated",
            "text": "采集空心菜",
            "expect_action": "gather",
            "expect_ready": False,
        },
    ]
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        for case in cases:
            result = runtime.preview_from_text(case["text"]).to_dict()
            observed = f"{result.get('action')} status={result.get('status')} ready={result.get('ready_to_save')}"
            status = "PASS"
            if result.get("action") != case["expect_action"] or bool(result.get("ready_to_save")) != case["expect_ready"]:
                status = "FAIL"
            checks.append(
                Check(
                    area="preview_from_text",
                    name=case["name"],
                    status=status,
                    observed=observed,
                    expected=f"{case['expect_action']} ready={case['expect_ready']}",
                    details=[
                        f"text={case['text']}",
                        f"errors={result.get('errors')}",
                        f"warnings={result.get('warnings')}",
                    ],
                )
            )
    return checks


def run_full_chain_checks(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    checks.append(check_travel_commit(rp_root))
    checks.append(check_routine_commit(rp_root))
    checks.append(check_combat_ammo_commit(rp_root))
    checks.append(check_combat_off_location_guard(rp_root))
    checks.append(check_unedited_gather_commit_consistency(rp_root))
    checks.append(check_unedited_social_commit_consistency(rp_root))
    checks.append(check_human_edited_gather_inventory_commit(rp_root))
    return checks


def check_travel_commit(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        before_turns = table_count(save_dir, "turns")
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_action(
            "travel",
            {"destination": "loc:home-clearing", "pace": "careful", "user_text": "去围墙领地/家巡查"},
        )
        result = runtime.commit_turn(preview.delta_draft, turn_proposal=preview.turn_proposal, backup=False)
        after_turns = table_count(save_dir, "turns")
        location = meta_value(save_dir, "current_location_id")
        health = inspect_save_package(save_dir)
        ok = result.to_dict()["ok"] and after_turns == before_turns + 1 and location == "loc:home-clearing" and health["ok"]
        return Check(
            area="commit",
            name="travel commit updates location",
            status="PASS" if ok else "FAIL",
            observed=f"ok={result.to_dict()['ok']} turns={before_turns}->{after_turns} location={location} health={health['ok']}",
            expected="commit ok, turns +1, current_location_id=loc:home-clearing, health ok",
        )


def check_routine_commit(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        before_turns = table_count(save_dir, "turns")
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_from_text("巡视领地，看看大家都在做什么")
        result = runtime.commit_turn(preview.delta_draft, turn_proposal=preview.turn_proposal, backup=False)
        after_turns = table_count(save_dir, "turns")
        event_type = latest_event_type(save_dir)
        ok = result.to_dict()["ok"] and after_turns == before_turns + 1 and event_type == "routine"
        return Check(
            area="commit",
            name="routine text preview commits",
            status="PASS" if ok else "FAIL",
            observed=f"ok={result.to_dict()['ok']} turns={before_turns}->{after_turns} latest_event={event_type}",
            expected="commit ok, turns +1, event type routine",
        )


def check_combat_ammo_commit(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        before = item_quantity(save_dir, "item:stun-thorn-bolts")
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_action(
            "combat",
            {
                "target": "char:pumpkin-s2",
                "weapon": "item:ultimate-compound-crossbow",
                "ammo": "item:stun-thorn-bolts",
                "distance": "medium",
                "ready_state": "已上弦并装填",
                "user_text": "压力测试：用琥珀麻箭做一次射击结算",
            },
        )
        result = runtime.commit_turn(preview.delta_draft, turn_proposal=preview.turn_proposal, backup=False)
        after = item_quantity(save_dir, "item:stun-thorn-bolts")
        ok = result.to_dict()["ok"] and before == 12 and after == 11
        return Check(
            area="commit",
            name="combat commit decrements ammo",
            status="PASS" if ok else "FAIL",
            observed=f"ok={result.to_dict()['ok']} stun_bolts={before}->{after}",
            expected="stun bolts 12 -> 11",
            details=list(preview.warnings),
        )


def check_combat_off_location_guard(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_action(
            "combat",
            {
                "target": "threat:t2-large-cat",
                "weapon": "item:ultimate-compound-crossbow",
                "ammo": "item:stun-thorn-bolts",
                "distance": "medium",
                "ready_state": "已上弦并装填",
                "user_text": "压力测试：射击不在当前地点的T2母猫",
            },
        )
        target_location = entity_location(save_dir, "threat:t2-large-cat")
        current_location = meta_value(save_dir, "current_location_id")
        should_block = target_location and target_location != current_location
        ok = not (should_block and preview.ready_to_save)
        return Check(
            area="preview_action",
            name="combat blocks off-location target",
            status="PASS" if ok else "FAIL",
            observed=f"ready={preview.ready_to_save} current={current_location} target_location={target_location} errors={preview.errors}",
            expected="not ready when target is in another location",
            details=list(preview.warnings),
        )


def check_unedited_gather_commit_consistency(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_from_text("采集空心菜")
        if not preview.ready_to_save:
            return Check(
                area="preview_commit_consistency",
                name="unedited gather preview should not fail at confirm",
                status="PASS",
                observed=f"preview_ready={preview.ready_to_save} status={preview.status}",
                expected="unquantified gather should ask for quantity before confirm",
            )
        try:
            result = runtime.commit_turn(preview.delta_draft, turn_proposal=preview.turn_proposal, backup=False)
            observed = f"preview_ready={preview.ready_to_save} commit_ok={result.to_dict()['ok']}"
            status = "PASS"
        except Exception as exc:
            observed = f"preview_ready={preview.ready_to_save} commit_error={type(exc).__name__}: {exc}"
            status = "FAIL" if preview.ready_to_save else "PASS"
        return Check(
            area="preview_commit_consistency",
            name="unedited gather preview should not fail at confirm",
            status=status,
            observed=observed,
            expected="if preview is ready_to_save, confirm should commit; otherwise preview should ask for quantity first",
        )


def check_unedited_social_commit_consistency(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_from_text("找南瓜聊聊，问问它今天状态怎么样")
        try:
            result = runtime.commit_turn(preview.delta_draft, turn_proposal=preview.turn_proposal, backup=False)
            observed = f"preview_ready={preview.ready_to_save} commit_ok={result.to_dict()['ok']}"
            status = "PASS"
        except Exception as exc:
            observed = f"preview_ready={preview.ready_to_save} commit_error={type(exc).__name__}: {exc}"
            status = "FAIL" if preview.ready_to_save else "PASS"
        return Check(
            area="preview_commit_consistency",
            name="unedited social preview should not fail at confirm",
            status=status,
            observed=observed,
            expected="if preview is ready_to_save, confirm should commit; otherwise preview should ask for relationship/trade result first",
        )


def check_human_edited_gather_inventory_commit(rp_root: Path) -> Check:
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        preview = runtime.preview_action("gather", {"target": "item:v1-3a6b64e5c1", "user_text": "采集空心菜"})
        delta = extract_delta_from_markdown(preview.markdown)
        delta["summary"] = "采集空心菜，确认收获2株并入库存。"
        delta["events"][0]["summary"] = "采集空心菜，确认收获2株并入库存。"
        delta["events"][0]["payload"]["output_item_id"] = "item:stress-water-spinach-harvest"
        delta["events"][0]["payload"]["output_quantity"] = 2
        delta["events"][0]["payload"]["output_unit"] = "株"
        delta["events"][0]["payload"]["resource_state_update_required"] = False
        delta["upsert_entities"] = [
            {
                "id": "item:stress-water-spinach-harvest",
                "type": "item",
                "name": "压力测试收获空心菜",
                "status": "active",
                "visibility": "known",
                "location_id": "loc:home-mycelium-house",
                "summary": "压力测试：采集空心菜2株并入库。",
                "details": {"source": "stress_simulation", "quantity_confidence": "confirmed"},
                "item": {
                    "category": "food",
                    "quantity": 2,
                    "unit": "株",
                    "stackable": True,
                    "quality": "fresh",
                    "properties": {"source_target_id": "item:v1-3a6b64e5c1"},
                },
            }
        ]
        proposal = human_edited_proposal(
            "gather",
            {"target": "item:v1-3a6b64e5c1", "user_text": "采集空心菜", "output_confirmed": True},
            delta,
        )
        result = runtime.commit_turn(delta, turn_proposal=proposal, backup=False)
        row = item_row(save_dir, "item:stress-water-spinach-harvest")
        query_text = runtime.query("entity", "item:stress-water-spinach-harvest").text
        audit = result.to_dict().get("state_audit") or {}
        ok = result.to_dict()["ok"] and row and row["quantity"] == 2 and "2株" in query_text
        status = "PASS" if ok else "FAIL"
        if audit.get("findings"):
            status = "WARN" if status == "PASS" else status
        return Check(
            area="commit",
            name="human-edited gather delta stores inventory quantity",
            status=status,
            observed=f"ok={result.to_dict()['ok']} item_quantity={row['quantity'] if row else None}{row['unit'] if row else ''} audit_findings={len(audit.get('findings', []))}",
            expected="commit ok and query returns 2株",
            details=[json.dumps(audit.get("findings", []), ensure_ascii=False)],
        )


def run_player_entry_check(rp_root: Path) -> list[Check]:
    with copied_workspace(rp_root) as workspace:
        manager = SaveManager(workspace)
        act = manager.player_act(user_text="去围墙领地/家巡查")
        if not act.get("ready_to_confirm"):
            return [
                Check(
                    area="player_entry",
                    name="player act/confirm travel",
                    status="FAIL",
                    observed=f"act={act}",
                    expected="ready_to_confirm true",
                )
            ]
        confirm = manager.player_confirm()
        current = manager.current_save()
        save_dir = workspace / SAVE_DIR_NAME
        location = meta_value(save_dir, "current_location_id")
        ok = bool(confirm.get("ok")) and location == "loc:home-clearing" and current.get("save", {}).get("health") == "ok"
        return [
            Check(
                area="player_entry",
                name="player act/confirm travel",
                status="PASS" if ok else "FAIL",
                observed=f"act_ready={act.get('ready_to_confirm')} confirm_ok={confirm.get('ok')} location={location} health={current.get('save', {}).get('health')}",
                expected="player act returns pending action, confirm commits, active save remains healthy",
            )
        ]


def table_count(save_dir: Path, table: str) -> int:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        return int(conn.execute(f"select count(*) from {table}").fetchone()[0])


def meta_value(save_dir: Path, key: str) -> str | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select value from meta where key = ?", (key,)).fetchone()
        return str(row[0]) if row else None


def item_quantity(save_dir: Path, entity_id: str) -> float | None:
    row = item_row(save_dir, entity_id)
    return float(row["quantity"]) if row and row["quantity"] is not None else None


def item_row(save_dir: Path, entity_id: str) -> sqlite3.Row | None:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            """
            select e.id, e.name, e.location_id, e.owner_id, i.quantity, i.unit
            from entities e
            left join items i on i.entity_id = e.id
            where e.id = ?
            """,
            (entity_id,),
        ).fetchone()
    finally:
        conn.close()


def latest_event_type(save_dir: Path) -> str | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select type from events order by rowid desc limit 1").fetchone()
        return str(row[0]) if row else None


def entity_location(save_dir: Path, entity_id: str) -> str | None:
    with sqlite3.connect(save_dir / "data" / "game.sqlite") as conn:
        row = conn.execute("select location_id from entities where id = ?", (entity_id,)).fetchone()
        return str(row[0]) if row and row[0] is not None else None


def extract_delta_from_markdown(markdown: str) -> dict[str, Any]:
    marker = "```json"
    if marker not in markdown:
        raise ValueError("preview markdown has no JSON delta block")
    raw = markdown.split(marker, 1)[1].split("```", 1)[0]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("delta block is not an object")
    return data


def human_edited_proposal(action: str, options: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    intent = ActionIntent(
        user_text=str(options.get("user_text") or ""),
        mode="action",
        submode=action,
        action=action,
        options=options,
        confidence="high",
        source="stress_test",
    )
    contract = TurnContract(
        intent=intent,
        required_template=f"{action}_turn.md" if action != "gather" else "gather_turn.md",
        response_headings=("场景", "行动结果", "状态变化", "保存状态", "后续行动"),
        requires_preview=True,
        must_save=True,
        allowed_delta_sources=("resolver_proposed", "ai_generated", "human_edited", "response_draft"),
        validation_profile="player_turn_commit",
    )
    return TurnProposal(
        proposal_id=f"turn-proposal:stress:{action}",
        intent=intent,
        preview={"action": action, "status": "ready", "facts_used": [], "rules_applied": []},
        delta=delta,
        delta_source="human_edited",
        provenance={"source": "stress_current_save", "resolver": action},
        human_confirmed=True,
        turn_contract=contract,
    ).to_dict()


def render_report(checks: list[Check]) -> str:
    counts = {status: sum(1 for check in checks if check.status == status) for status in ("PASS", "WARN", "FAIL")}
    lines = [
        "# Current Save Stress Report",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "",
        f"Summary: PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}",
        "",
        "| Status | Area | Case | Observed | Expected |",
        "|---|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check.status} | {check.area} | {check.name} | {escape(check.observed)} | {escape(check.expected)} |"
        )
    lines.extend(["", "## Details", ""])
    for check in checks:
        if check.status == "PASS" and not check.details:
            continue
        lines.extend([f"### {check.status} · {check.area} · {check.name}", "", f"- Observed: {check.observed}"])
        if check.expected:
            lines.append(f"- Expected: {check.expected}")
        for item in check.details:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines)


def escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
