from __future__ import annotations

import argparse
import hashlib
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


DEFAULT_RP_ROOT = Path("/Users/oliver/.hermes/rp")
CAMPAIGN_DIR_NAME = "isekai-farm-campaign-native-v1"
SAVE_DIR_NAME = "isekai-farm-save-native-v1"
CURRENT_LOCATION_ID = "loc:home-mycelium-house"
VALIDATION_GATHER_TARGET_ID = "item:v1-3a6b64e5c1"


@dataclass(frozen=True)
class NaturalCase:
    area: str
    name: str
    text: str
    accept: tuple[str, ...]
    expected_behavior: str


@dataclass(frozen=True)
class InventoryCase:
    name: str
    text: str
    item_id: str
    item_name: str
    category: str
    quantity: float
    unit: str
    quality: str
    source_target_id: str
    risk: str = "low"


@dataclass(frozen=True)
class WorldCase:
    name: str
    text: str
    upserts: tuple[dict[str, Any], ...]
    expected_entities: tuple[str, ...]
    expected_event_type: str


@dataclass(frozen=True)
class GuardrailCase:
    name: str
    area: str
    delta: dict[str, Any]
    action: str
    options: dict[str, Any]
    expected: str
    should_block: bool = True
    check_entity_id: str | None = None


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
    turn_id: str = ""
    error: str = ""
    check_errors: tuple[str, ...] = ()
    audit_findings: tuple[str, ...] = ()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe gather/discovery intake persistence on the current isekai-farm save.",
    )
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-intake-probe-2026-07-01.md"),
    )
    args = parser.parse_args()

    checks: list[Check] = []
    checks.extend(run_natural_cases(args.rp_root))
    checks.extend(run_inventory_intake_cases(args.rp_root))
    checks.extend(run_world_intake_cases(args.rp_root))
    checks.extend(run_guardrail_cases(args.rp_root))

    report = render_report(checks)
    print(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-intake-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def run_natural_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        turns_before = table_count(save_dir, "turns")
        entities_before = table_count(save_dir, "entities")
        items_before = table_count(save_dir, "items")
        for case in natural_cases():
            try:
                start = runtime.start_turn(case.text).to_dict()
                preview = runtime.preview_from_text(case.text).to_dict()
            except Exception as exc:
                checks.append(
                    Check(
                        area=case.area,
                        name=case.name,
                        status="ISSUE",
                        observed=f"error={type(exc).__name__}: {exc}",
                        expected=case.expected_behavior,
                        issue="natural_intake_exception",
                    )
                )
                continue
            route = route_key(start)
            preview_route = preview_key(preview)
            route_ok = route in case.accept or preview_route in case.accept
            no_write = (
                table_count(save_dir, "turns") == turns_before
                and table_count(save_dir, "entities") == entities_before
                and table_count(save_dir, "items") == items_before
            )
            ok = route_ok and no_write
            issue = ""
            if not route_ok:
                issue = issue_for_natural_route(start, preview)
            elif not no_write:
                issue = "preview_mutated_save"
            checks.append(
                Check(
                    area=case.area,
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"start={route} can_proceed={start.get('can_proceed')} "
                        f"preview={preview_route} ready={preview.get('ready_to_save')} "
                        f"status={preview.get('status')}"
                    ),
                    expected=case.expected_behavior,
                    details=[
                        f"text={case.text}",
                        f"player_message={one_line(str(preview.get('player_message') or ''))}",
                        f"errors={preview.get('errors')}",
                        f"warnings={preview.get('warnings')}",
                    ],
                    issue=issue,
                )
            )
    return checks


def run_inventory_intake_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        for case in inventory_cases():
            before_entity = entity_row(save_dir, case.item_id)
            delta = gather_intake_delta(save_dir, case)
            options = {
                "target": VALIDATION_GATHER_TARGET_ID,
                "location": CURRENT_LOCATION_ID,
                "user_text": case.text,
                "output_confirmed": True,
            }
            outcome = commit(runtime, delta, human_proposal("gather", options, delta), "gather", options)
            row = item_row(save_dir, case.item_id)
            event = event_for_turn(save_dir, outcome.turn_id)
            query_text = ""
            if row:
                try:
                    query_text = runtime.query("entity", case.item_id).text
                except Exception as exc:  # pragma: no cover - report path
                    query_text = f"query_error={type(exc).__name__}: {exc}"
            quantity_ok = bool(row and row.get("quantity") == case.quantity and row.get("unit") == case.unit)
            entity_ok = bool(
                row
                and row.get("id") == case.item_id
                and row.get("name") == case.item_name
                and row.get("location_id") == CURRENT_LOCATION_ID
            )
            event_ok = bool(
                event
                and event.get("type") == "gather"
                and event.get("payload", {}).get("output_item_id") == case.item_id
                and event.get("payload", {}).get("output_quantity") == case.quantity
            )
            query_ok = case.item_name in query_text and query_has_quantity(query_text, case.quantity, case.unit)
            ok = (
                before_entity is None
                and outcome.committed
                and outcome.ok
                and quantity_ok
                and entity_ok
                and event_ok
                and query_ok
            )
            issue = ""
            if not ok:
                if not outcome.committed:
                    issue = "confirmed_intake_not_committed"
                elif not outcome.ok:
                    issue = "confirmed_intake_committed_with_check_errors"
                elif not quantity_ok:
                    issue = "confirmed_intake_wrong_quantity"
                elif not event_ok:
                    issue = "confirmed_intake_event_payload_gap"
                elif not query_ok:
                    issue = "confirmed_intake_query_gap"
                else:
                    issue = "confirmed_intake_persistence_gap"
            checks.append(
                Check(
                    area="confirmed inventory intake",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"committed={outcome.committed} ok={outcome.ok} "
                        f"row={row_quantity(row)} event_ok={event_ok} query_ok={query_ok}"
                    ),
                    expected=f"immediately store {case.item_name} as {format_quantity(case.quantity, case.unit)}",
                    details=[
                        f"text={case.text}",
                        f"turn_id={outcome.turn_id}",
                        *outcome_details(outcome),
                        f"query={one_line(query_text)}",
                    ],
                    issue=issue,
                )
            )
    return checks


def run_world_intake_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    with copied_save(rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        for case in world_cases():
            delta = explore_intake_delta(save_dir, case)
            options = {
                "target": case.text,
                "approach": "careful",
                "unknown_lead": True,
                "user_text": case.text,
            }
            outcome = commit(runtime, delta, human_proposal("explore", options, delta), "explore", options)
            event = event_for_turn(save_dir, outcome.turn_id)
            entity_rows = [entity_row(save_dir, entity_id) for entity_id in case.expected_entities]
            entities_ok = all(row is not None for row in entity_rows)
            event_ok = bool(event and event.get("type") == case.expected_event_type)
            query_ok = True
            query_details: list[str] = []
            for entity_id in case.expected_entities:
                try:
                    text = runtime.query("entity", entity_id).text
                except Exception as exc:  # pragma: no cover - report path
                    text = f"query_error={type(exc).__name__}: {exc}"
                query_details.append(f"{entity_id}={one_line(text)}")
                row = entity_row(save_dir, entity_id)
                if not row or str(row["name"]) not in text:
                    query_ok = False
            ok = outcome.committed and outcome.ok and event_ok and entities_ok and query_ok
            issue = ""
            if not ok:
                if not outcome.committed:
                    issue = "world_intake_not_committed"
                elif not outcome.ok:
                    issue = "world_intake_committed_with_check_errors"
                elif not event_ok:
                    issue = "world_intake_event_gap"
                elif not entities_ok:
                    issue = "world_intake_missing_entity"
                elif not query_ok:
                    issue = "world_intake_query_gap"
                else:
                    issue = "world_intake_persistence_gap"
            checks.append(
                Check(
                    area="confirmed world/event intake",
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"committed={outcome.committed} ok={outcome.ok} "
                        f"event_ok={event_ok} entities_ok={entities_ok} query_ok={query_ok}"
                    ),
                    expected="event and new fact entities are immediately persisted and queryable",
                    details=[f"text={case.text}", f"turn_id={outcome.turn_id}", *outcome_details(outcome), *query_details],
                    issue=issue,
                )
            )
    return checks


def run_guardrail_cases(rp_root: Path) -> list[Check]:
    checks: list[Check] = []
    for case in guardrail_cases():
        with copied_save(rp_root) as save_dir:
            runtime = GMRuntime.from_path(save_dir)
            before = entity_row(save_dir, case.check_entity_id) if case.check_entity_id else None
            outcome = commit(runtime, case.delta, human_proposal(case.action, case.options, case.delta), case.action, case.options)
            after = entity_row(save_dir, case.check_entity_id) if case.check_entity_id else None
            blocked = not outcome.committed or not outcome.ok
            no_persist = before == after if case.check_entity_id else True
            ok = blocked and no_persist if case.should_block else outcome.committed and outcome.ok
            issue = ""
            if not ok:
                if outcome.committed and outcome.ok:
                    issue = "intake_guardrail_missing"
                elif outcome.committed and not no_persist:
                    issue = "intake_guardrail_reported_after_write"
                else:
                    issue = "intake_guardrail_unexpected_result"
            checks.append(
                Check(
                    area=case.area,
                    name=case.name,
                    status="PASS" if ok else "ISSUE",
                    observed=(
                        f"committed={outcome.committed} ok={outcome.ok} "
                        f"blocked={blocked} no_persist={no_persist}"
                    ),
                    expected=case.expected,
                    details=outcome_details(outcome),
                    issue=issue,
                )
            )
    return checks


def natural_cases() -> list[NaturalCase]:
    gather = ("action:gather",)
    travel_or_gather = ("action:composite", "action:travel", "action:gather")
    explore = ("action:explore", "action:composite")
    social = ("action:social", "action:composite")
    return [
        NaturalCase("natural gather recognition", "gather water spinach", "采空心菜", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect water spinach", "收一点空心菜", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "cut two water spinach", "割2株空心菜入库", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick shiso", "摘紫苏叶", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick hemostatic herb", "采止血草", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick anti-inflammatory herb", "采消炎草", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "dig fever root", "挖退热根", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick moon dew", "采月露草", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect moon moss", "采月光苔", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect thunder moss", "采雷苔", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "harvest fish trap", "收鱼笼", gather, "recognize gather or require travel before saving"),
        NaturalCase("natural gather recognition", "take fish from trap", "从鱼笼取鱼", gather, "recognize gather or require travel before saving"),
        NaturalCase("natural gather recognition", "go creek harvest trap", "去L1小溪收鱼笼", travel_or_gather, "recognize travel+gather plan instead of inventory query"),
        NaturalCase("natural gather recognition", "fetch spring water", "去泉眼取水", travel_or_gather, "recognize travel+gather plan instead of inventory query"),
        NaturalCase("natural gather recognition", "fill water bottle", "打一筒水", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick pine nuts", "捡松子", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick pine cone", "捡松塔", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect milky sap", "采见血封喉乳汁", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect sulfur shards", "采硫磺碎晶", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "dig niter", "挖硝石", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick flint", "捡燧石", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect hemp fiber", "搜集麻纤维", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "collect lake fiber", "收集湖边细纤维", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "take root mycelium sample", "采根源菌丝样本", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick berries", "摘红浆果", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick chili", "采红辣椒", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "pick wild onion", "采野葱", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "cut chives", "割韭菜", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "harvest potatoes", "收土豆", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "harvest sweet potato", "收红薯", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "look for herbs", "找草药", gather, "resource search should become gather"),
        NaturalCase("natural gather recognition", "look for materials", "找材料", gather, "resource search should become gather"),
        NaturalCase("natural gather recognition", "search food", "搜索可用食材", gather, "resource search should become gather"),
        NaturalCase("natural gather recognition", "search creek materials", "搜索河边可采集材料", travel_or_gather, "travel/search/gather plan should be explicit"),
        NaturalCase("natural discovery recognition", "inspect smoke column", "调查远处烟柱看看有没有文明", explore, "recognize exploration/discovery, not query"),
        NaturalCase("natural discovery recognition", "scout strange footprints", "侦查陌生脚印并记录", explore, "recognize exploration/discovery, not query"),
        NaturalCase("natural discovery recognition", "search pottery shard", "搜索陌生陶片来源", explore, "recognize exploration/discovery, not query"),
        NaturalCase("natural discovery recognition", "record new tribe", "发现新部落，先记录下来", explore, "recognize discovery that must save structured event/entity"),
        NaturalCase("natural discovery recognition", "observe civilization trace", "观察陌生文明留下的编织纹样", explore, "recognize discovery that must save structured event/entity"),
        NaturalCase("natural discovery recognition", "ask an civilization rumor", "和An确认新文明传闻", social, "recognize social confirmation of new fact"),
        NaturalCase("natural discovery recognition", "ask eve new event", "问夏娃有没有发现新的菌丝事件", social, "recognize social fact intake"),
        NaturalCase("natural discovery recognition", "record earthquake", "记录一次刚发生的地震事件", explore, "recognize event intake, not only routine narration"),
        NaturalCase("natural discovery recognition", "new spring", "发现新的泉眼并标记位置", explore, "recognize location discovery intake"),
        NaturalCase("natural discovery recognition", "new cave", "发现新洞穴入口并记录", explore, "recognize location discovery intake"),
        NaturalCase("natural discovery recognition", "new caravan", "遇到一队陌生商旅，先观察记录", explore, "recognize encounter/faction discovery"),
        NaturalCase("natural discovery recognition", "new species", "遇到陌生种族先观察", explore, "recognize species/civilization discovery"),
        NaturalCase("natural discovery recognition", "night whistle source", "搜索夜里哨声来源", explore, "recognize event/threat discovery"),
        NaturalCase("natural gather recognition", "unknown feather", "捡起地上的未知羽毛入库", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "blue mineral sand", "收集蓝色矿砂", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "rubbing slab", "把新发现的石碑拓片入库", gather, "recognize item intake and require structured output"),
        NaturalCase("natural gather recognition", "honeycomb mushroom", "采集蜂巢菇", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "crystal mushroom", "采晶化菇", gather, "recognize gather and ask for confirmed output before saving"),
        NaturalCase("natural gather recognition", "powder residue", "取火药残渣样本", gather, "recognize high-risk gather and require exact output"),
        NaturalCase("natural gather recognition", "footprint sample", "搜集围墙附近的脚印样本", gather, "recognize evidence/sample intake"),
    ]


def inventory_cases() -> list[InventoryCase]:
    raw = [
        ("water spinach leaves", "确认采到2株空心菜嫩叶并入库", "空心菜嫩叶", "food", 2, "株", "fresh", "item:v1-3a6b64e5c1"),
        ("shiso leaves", "确认摘到5片紫苏叶并入库", "紫苏叶", "food", 5, "片", "fresh", "item:v1-da43d4526b"),
        ("lettuce leaves", "确认收获3片红叶生菜并入库", "红叶生菜叶", "food", 3, "片", "fresh", "item:v1-f07d297448"),
        ("garlic leaves", "确认割到4束蒜叶并入库", "蒜叶束", "food", 4, "束", "fresh", "item:v1-8aa915dbc4"),
        ("wild onion", "确认采到2把野葱并入库", "野葱把", "food", 2, "把", "fresh", "item:v1-0629e81966"),
        ("pine nuts", "确认捡到0.5竹杯松子仁并入库", "松子仁补充", "food", 0.5, "竹杯", "dry", "item:v1-b4fc16271b"),
        ("pine nut oil", "确认滤出0.25竹杯松子油并入库", "松子油补装", "food", 0.25, "竹杯", "filtered", "item:pine-nut-oil"),
        ("berries", "确认摘到6枚红浆果并入库", "红浆果补充", "food", 6, "枚", "fresh", "item:v1-8182ae0835"),
        ("fresh chili", "确认摘到2个新鲜辣椒并入库", "新鲜辣椒补充", "food", 2, "个", "fresh", "item:v1-d409c6757a"),
        ("ginger", "确认挖到1块生姜并入库", "生姜块", "food", 1, "块", "fresh", "item:v1-a5ed98dd5e"),
        ("clear water", "确认灌到1L清水并入库", "清水补给", "food", 1, "L", "clean", "item:v1-0b81d0d73c"),
        ("filtered water", "确认过滤出0.5L水并入库", "过滤水", "food", 0.5, "L", "filtered", "item:v1-0b81d0d73c"),
        ("hemostatic herb", "确认采到3株止血草样本并入库", "止血草样本", "material", 3, "株", "fresh", "item:v1-ad42a74d20"),
        ("anti inflammatory herb", "确认采到2株消炎草样本并入库", "消炎草样本", "material", 2, "株", "fresh", "item:v1-e0ad1e8f81"),
        ("fever root slices", "确认切下4片退热根并入库", "退热根切片", "material", 4, "片", "fresh", "item:v1-cba23af8e3"),
        ("insect repellent herb", "确认采到2株驱虫草并入库", "驱虫草样本", "material", 2, "株", "fresh", "item:v1-2f16f97815"),
        ("moon dew herb", "确认采到1株月露草样本并入库", "月露草样本", "material", 1, "株", "fresh", "item:v1-e154966caa"),
        ("moon moss", "确认刮下0.5捧月光苔并入库", "月光苔样本", "material", 0.5, "捧", "damp", "item:v1-e7996a2e98"),
        ("thunder moss", "确认收下1片雷苔并入库", "雷苔样本", "material", 1, "片", "fresh", "item:v1-e494d4c06f"),
        ("frost leaf", "确认采到2片霜叶并入库", "霜叶样本", "material", 2, "片", "fresh", "item:v1-810cb2033c"),
        ("hemp fiber", "确认整理出0.75kg麻纤维并入库", "麻纤维补充", "material", 0.75, "kg", "dry", "item:v1-9852b22696"),
        ("common resin", "确认收集0.2竹杯普通残胶并入库", "普通残胶样本", "material", 0.2, "竹杯", "sticky", "item:v1-9bb88c5944"),
        ("hardened resin", "确认敲下0.1竹杯硬化残胶并入库", "硬化残胶碎片", "material", 0.1, "竹杯", "dry", "item:v1-0322977645"),
        ("milky residue", "确认收集0.1竹杯乳白残液样本并入库", "乳白残液样本", "material", 0.1, "竹杯", "wet", "item:v1-1767a0dfd3"),
        ("bamboo cup", "确认新增1个竹杯并入库", "竹杯补充", "container", 1, "个", "usable", "item:v1-638acf1712"),
        ("salt crystals", "确认刮下0.1勺盐晶并入库", "盐晶样本", "material", 0.1, "勺", "dry", "item:salt"),
        ("sulfur shards", "确认采到0.2竹杯硫磺碎晶并入库", "硫磺碎晶样本", "material", 0.2, "竹杯", "raw", "item:v1-4681d8edfb"),
        ("niter needles", "确认采到0.15竹杯硝石针晶并入库", "硝石针晶样本", "material", 0.15, "竹杯", "raw", "item:v1-26667819cb"),
        ("flint", "确认捡到1块优质燧石并入库", "优质燧石样本", "material", 1, "块", "sharp", "item:v1-c1101bc083"),
        ("serpentine", "确认捡到2块蛇纹石碎片并入库", "蛇纹石碎片", "material", 2, "块", "raw", "item:v1-670a49c919"),
        ("river mud", "确认采到3团河泥样本并入库", "河泥样本", "material", 3, "团", "wet", "item:v1-0b81d0d73c"),
        ("reed fiber", "确认整理出1捆芦苇纤维并入库", "芦苇纤维", "material", 1, "捆", "dry", "item:v1-9852b22696"),
        ("lake fiber", "确认收集0.3kg湖边细纤维并入库", "湖边细纤维样本", "material", 0.3, "kg", "dry", "item:v1-ac25ff32a4"),
        ("honeycomb mushroom", "确认采到2朵蜂巢菇样本并入库", "蜂巢菇样本", "material", 2, "朵", "fresh", "item:v1-33e843dea4"),
        ("crystal mushroom", "确认取下1片晶化菇碎片并入库", "晶化菇碎片", "material", 1, "片", "brittle", "item:v1-5224f28cd2"),
        ("echo pollen", "确认收集0.05竹杯回声花花粉并入库", "回声花花粉", "material", 0.05, "竹杯", "fine", "item:v1-3ff3e8ec4d"),
        ("star seed pod", "确认收下3枚星辰草种荚并入库", "星辰草种荚", "material", 3, "枚", "seed", "item:v1-51622cf688"),
        ("thorn vine", "确认截下2段荆棘藤并入库", "荆棘藤段", "material", 2, "段", "fresh", "item:v1-5ae3d48ea9"),
        ("root mycelium", "确认取下1面根源菌丝样本并入库", "根源菌丝样本", "material", 1, "面", "live", "item:v1-22e37e913c"),
        ("mother spore", "确认收集0.1捧母孢子树孢子并入库", "母孢子树孢子", "material", 0.1, "捧", "live", "item:v1-d9e3f1ce7b"),
        ("sample bag note", "确认新增1件样品袋记录并入库", "样品袋记录", "evidence", 1, "件", "noted", "item:v1-638acf1712"),
        ("footprint cast", "确认保存1件新脚印石膏模并入库", "新脚印石膏模", "evidence", 1, "件", "dry", "item:v1-638acf1712"),
        ("pottery shard", "确认收集2片陌生陶片并入库", "陌生陶片", "evidence", 2, "片", "old", "item:v1-c1101bc083"),
        ("weave rubbing", "确认保存1张编织纹样拓片并入库", "编织纹样拓片", "evidence", 1, "张", "clear", "item:v1-5a357b56c5"),
        ("charcoal sample", "确认收集5块焦黑木炭样本并入库", "焦黑木炭样本", "material", 5, "块", "dry", "item:v1-c1101bc083"),
        ("metal filings", "确认收集0.05竹杯金属碎屑并入库", "金属碎屑", "material", 0.05, "竹杯", "raw", "item:v1-c1101bc083"),
        ("blue mineral sand", "确认收集0.2竹杯蓝色矿砂并入库", "蓝色矿砂", "material", 0.2, "竹杯", "raw", "item:v1-c1101bc083"),
        ("resin drops", "确认收集7滴透明树脂滴并入库", "透明树脂滴", "material", 7, "滴", "sticky", "item:v1-9bb88c5944"),
        ("animal hair", "确认保存1撮动物毛束并入库", "动物毛束", "evidence", 1, "撮", "dry", "item:v1-638acf1712"),
        ("fish scales", "确认保存6片鱼鳞样本并入库", "鱼鳞样本", "evidence", 6, "片", "dry", "item:v1-638acf1712"),
        ("toxin strip", "确认保存1张毒液试纸并入库", "毒液试纸", "evidence", 1, "张", "sealed", "item:v1-638acf1712"),
        ("powder residue", "确认保存0.02竹杯火药残渣样本并入库", "火药残渣样本", "material", 0.02, "竹杯", "sealed", "item:black-powder"),
        ("paralysis spore", "确认保存0.1捧麻痹孢子样本并入库", "麻痹孢子样本", "material", 0.1, "捧", "sealed", "item:v1-d9e3f1ce7b"),
        ("black eggshell", "确认保存1片不明黑色卵壳并入库", "不明黑色卵壳", "evidence", 1, "片", "unknown", "item:v1-638acf1712"),
        ("watch bell", "确认新增1个警戒哨采样铃并入库", "警戒哨采样铃", "tool", 1, "个", "usable", "item:v1-638acf1712"),
    ]
    cases: list[InventoryCase] = []
    for index, (name, text, item_name, category, quantity, unit, quality, source_target_id) in enumerate(raw, start=1):
        cases.append(
            InventoryCase(
                name=name,
                text=text,
                item_id=f"item:probe-intake-{index:03d}",
                item_name=f"测试入库{index:03d} {item_name}",
                category=category,
                quantity=float(quantity),
                unit=unit,
                quality=quality,
                source_target_id=source_target_id,
                risk="high" if any(word in item_name for word in ("火药", "毒", "麻痹", "不明")) else "low",
            )
        )
    return cases


def world_cases() -> list[WorldCase]:
    return [
        world_case_location("new smoke ridge", "确认发现烟柱高地并记录为新地点", "loc:probe-smoke-ridge", "测试烟柱高地"),
        world_case_location("new spring", "确认发现新的侧泉眼并记录为新地点", "loc:probe-side-spring", "测试侧泉眼"),
        world_case_location("new cave mouth", "确认发现新洞穴入口并记录为新地点", "loc:probe-cave-mouth", "测试洞穴入口"),
        world_case_simple("new faction", "确认遇见芦苇编织者聚落并登记派系", "faction:probe-reed-weavers", "faction", "测试芦苇编织者"),
        world_case_simple("new species", "确认首次观察到灰鳞人并登记物种", "species:probe-ashscale", "species", "测试灰鳞人"),
        world_case_character("new envoy", "确认遇见芦苇编织者使者并登记人物", "char:probe-reed-envoy", "测试芦苇使者", "species:probe-reed-person"),
        world_case_simple("new threat", "确认夜间哨声来源是一种潜在威胁", "threat:probe-night-whistle", "threat", "测试夜哨威胁"),
        world_case_simple("new project", "确认开启陌生文明接触记录项目", "project:probe-civilization-contact", "project", "测试文明接触记录"),
        world_case_simple("new reference", "确认保存陌生陶片纹样参考", "ref:probe-pottery-pattern", "reference", "测试陶片纹样参考"),
        world_case_simple("new world setting", "确认记录湖边有定期贸易迹象", "setting:probe-lake-trade-sign", "world_setting", "测试湖边贸易迹象"),
        world_case_simple("new relationship", "确认记录与芦苇编织者的初始关系", "rel:probe-reed-weavers-contact", "relationship", "测试芦苇编织者初始关系"),
        world_case_simple("new faction rumor", "确认An提供一个远方盐路文明传闻", "faction:probe-salt-road-rumor", "faction", "测试盐路文明传闻"),
        world_case_simple("new event reference", "确认地震事件需要后续追踪", "ref:probe-quake-event", "reference", "测试地震事件记录"),
        world_case_simple("new species track", "确认陌生三趾脚印来自未知物种", "species:probe-three-toed", "species", "测试三趾未知种"),
        world_case_simple("new encounter note", "确认陌生商旅经过领地边缘", "ref:probe-caravan-encounter", "reference", "测试商旅遭遇记录"),
        world_case_simple("new marker", "确认地图上增加蓝砂采样点", "ref:probe-blue-sand-marker", "reference", "测试蓝砂采样点"),
        world_case_simple("new cultural artifact", "确认编织纹样指向一种新文化", "faction:probe-weave-culture", "faction", "测试编织纹样文化"),
        world_case_simple("new fungal incident", "确认夏娃报告新的菌丝异常事件", "ref:probe-mycelium-anomaly", "reference", "测试菌丝异常事件"),
        world_case_simple("new trade item", "确认商旅展示一种陌生陶币", "ref:probe-clay-coin", "reference", "测试陌生陶币记录"),
        world_case_simple("new hazard note", "确认新洞穴入口有塌方风险", "threat:probe-cave-collapse", "threat", "测试洞穴塌方风险"),
    ]


def guardrail_cases() -> list[GuardrailCase]:
    meta = {"time": "当前时段"}
    target = "item:v1-3a6b64e5c1"
    base_options = {
        "target": target,
        "location": CURRENT_LOCATION_ID,
        "user_text": "异常入库测试",
        "output_confirmed": True,
    }
    return [
        GuardrailCase(
            name="output event without upsert",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "事件说采到物品但没有新增实体。",
                target,
                [{"type": "gather", "title": "缺少入库", "summary": "声称采到物品但无 upsert。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-no-upsert", "output_quantity": 2, "output_unit": "株"}, "source": "intake_probe"}],
                [],
            ),
            action="gather",
            options=base_options,
            expected="should block claimed inventory output without matching upsert_entities",
            check_entity_id="item:probe-bad-no-upsert",
        ),
        GuardrailCase(
            name="non numeric quantity",
            area="intake guardrail",
            delta=single_bad_item_delta(target, "item:probe-bad-fuzzy-quantity", "模糊数量物品", "大量", "株"),
            action="gather",
            options=base_options,
            expected="should block non-numeric item.quantity in exact inventory upsert",
            check_entity_id="item:probe-bad-fuzzy-quantity",
        ),
        GuardrailCase(
            name="item without item payload",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "新增 item 类型但没有 item 子记录。",
                target,
                [{"type": "gather", "title": "缺少 item payload", "summary": "新增 item 类型但没有 item 子记录。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID}, "source": "intake_probe"}],
                [{"id": "item:probe-bad-no-item-payload", "type": "item", "name": "缺少子记录物品", "summary": "应被拦截。", "location_id": CURRENT_LOCATION_ID}],
            ),
            action="gather",
            options=base_options,
            expected="should block item entity without item payload",
            check_entity_id="item:probe-bad-no-item-payload",
        ),
        GuardrailCase(
            name="negative gathered quantity",
            area="intake guardrail",
            delta=single_bad_item_delta(target, "item:probe-bad-negative", "负数采集物品", -1, "株"),
            action="gather",
            options=base_options,
            expected="should block negative gathered quantity before writing",
            check_entity_id="item:probe-bad-negative",
        ),
        GuardrailCase(
            name="zero gathered quantity",
            area="intake guardrail",
            delta=single_bad_item_delta(target, "item:probe-bad-zero", "零数量采集物品", 0, "株"),
            action="gather",
            options=base_options,
            expected="should block zero-quantity intake when event claims new stock",
            check_entity_id="item:probe-bad-zero",
        ),
        GuardrailCase(
            name="output id mismatch",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "事件 output_item_id 和 upsert id 不一致。",
                target,
                [{"type": "gather", "title": "ID 不一致", "summary": "事件和实体入库 id 不一致。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-event-id", "output_quantity": 1, "output_unit": "株"}, "source": "intake_probe"}],
                [item_entity("item:probe-bad-upsert-id", "ID 不一致物品", "material", 1, "株", target)],
            ),
            action="gather",
            options=base_options,
            expected="should block mismatch between event output_item_id and upsert entity id",
            check_entity_id="item:probe-bad-upsert-id",
        ),
        GuardrailCase(
            name="missing location on item",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "新增入库物品没有 location_id 或 owner_id。",
                target,
                [{"type": "gather", "title": "缺少位置", "summary": "新增入库物品没有位置。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-no-location", "output_quantity": 1, "output_unit": "株"}, "source": "intake_probe"}],
                [item_entity("item:probe-bad-no-location", "无位置物品", "material", 1, "株", target, location_id=None)],
            ),
            action="gather",
            options=base_options,
            expected="should block newly gathered inventory without location_id or owner_id",
            check_entity_id="item:probe-bad-no-location",
        ),
        GuardrailCase(
            name="both owner and location",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "新增入库物品同时设置 owner_id 和 location_id。",
                target,
                [{"type": "gather", "title": "位置冲突", "summary": "同时设置 owner 和 location。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-owner-location", "output_quantity": 1, "output_unit": "株"}, "source": "intake_probe"}],
                [item_entity("item:probe-bad-owner-location", "位置冲突物品", "material", 1, "株", target, owner_id="pc:shenyan")],
            ),
            action="gather",
            options=base_options,
            expected="should block active entity with both owner_id and location_id",
            check_entity_id="item:probe-bad-owner-location",
        ),
        GuardrailCase(
            name="unknown location ref",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "新增入库物品指向不存在地点。",
                target,
                [{"type": "gather", "title": "不存在地点", "summary": "入库位置不存在。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-unknown-location", "output_quantity": 1, "output_unit": "株"}, "source": "intake_probe"}],
                [item_entity("item:probe-bad-unknown-location", "未知地点物品", "material", 1, "株", target, location_id="loc:does-not-exist")],
            ),
            action="gather",
            options=base_options,
            expected="should block newly gathered inventory with missing location ref",
            check_entity_id="item:probe-bad-unknown-location",
        ),
        GuardrailCase(
            name="duplicate upsert ids",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "同一 delta 重复 upsert 同一物品。",
                target,
                [{"type": "gather", "title": "重复实体", "summary": "重复 upsert id。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-duplicate", "output_quantity": 1, "output_unit": "株"}, "source": "intake_probe"}],
                [
                    item_entity("item:probe-bad-duplicate", "重复物品A", "material", 1, "株", target),
                    item_entity("item:probe-bad-duplicate", "重复物品B", "material", 1, "株", target),
                ],
            ),
            action="gather",
            options=base_options,
            expected="should block duplicate upsert entity ids",
            check_entity_id="item:probe-bad-duplicate",
        ),
        GuardrailCase(
            name="fuzzy high risk quantity",
            area="intake guardrail",
            delta=base_gather_delta(
                meta,
                "高风险火药样本没有精确数量。",
                target,
                [{"type": "gather", "title": "高风险模糊数量", "summary": "火药样本没有精确数量。", "payload": {"target_id": target, "location_id": CURRENT_LOCATION_ID, "output_item_id": "item:probe-bad-fuzzy-high-risk", "output_quantity": None, "output_unit": "竹杯"}, "source": "intake_probe"}],
                [item_entity("item:probe-bad-fuzzy-high-risk", "火药样本模糊数量", "material", None, "竹杯", "item:black-powder", risk="high")],
            ),
            action="gather",
            options=base_options,
            expected="should block high-risk inventory intake without exact quantity",
            check_entity_id="item:probe-bad-fuzzy-high-risk",
        ),
        GuardrailCase(
            name="civilization event without entity",
            area="intake guardrail",
            delta=base_explore_delta(
                "确认发现新文明但没有新增派系或参考实体。",
                [{"type": "discovery", "title": "新文明", "summary": "确认发现新文明但没有结构化实体。", "payload": {"target_query": "新文明", "target_kind": "unknown_lead", "needs_gm_resolution": True}, "source": "intake_probe"}],
                [],
            ),
            action="explore",
            options={"target": "新文明", "approach": "careful", "unknown_lead": True, "user_text": "发现新文明"},
            expected="should block confirmed new civilization event without structured entity/reference",
        ),
        GuardrailCase(
            name="location entity without location payload",
            area="intake guardrail",
            delta=base_explore_delta(
                "确认发现新地点但 location 类型没有 location 子记录。",
                [{"type": "discovery", "title": "新地点", "summary": "location 实体缺少 location 子记录。", "payload": {"target_query": "新地点", "target_kind": "unknown_lead", "needs_gm_resolution": True}, "source": "intake_probe"}],
                [{"id": "loc:probe-bad-no-location-payload", "type": "location", "name": "缺少子记录地点", "summary": "应被拦截。", "visibility": "known"}],
            ),
            action="explore",
            options={"target": "新地点", "approach": "careful", "unknown_lead": True, "user_text": "发现新地点"},
            expected="should block location entity without location payload",
            check_entity_id="loc:probe-bad-no-location-payload",
        ),
    ]


def gather_intake_delta(save_dir: Path, case: InventoryCase) -> dict[str, Any]:
    meta = meta_map(save_dir)
    event = {
        "type": "gather",
        "title": "采集入库确认",
        "summary": f"{case.text}；确认入库 {format_quantity(case.quantity, case.unit)}。",
        "payload": {
            "target_id": case.source_target_id,
            "target_type": "item",
            "source_target_id": case.source_target_id,
            "from_location_id": CURRENT_LOCATION_ID,
            "location_id": CURRENT_LOCATION_ID,
            "travel_required": False,
            "needs_gm_resolution": False,
            "output_item_id": case.item_id,
            "output_quantity": case.quantity,
            "output_unit": case.unit,
            "resource_state_update_required": False,
        },
        "source": "intake_probe",
    }
    event["payload"]["target_id"] = VALIDATION_GATHER_TARGET_ID
    return base_gather_delta(meta, case.text, VALIDATION_GATHER_TARGET_ID, [event], [inventory_entity(case)])


def base_gather_delta(
    meta: dict[str, Any],
    summary: str,
    target_id: str,
    events: list[dict[str, Any]],
    upserts: list[dict[str, Any]],
) -> dict[str, Any]:
    del target_id
    return {
        "user_text": summary,
        "intent": "gather",
        "changed": True,
        "game_time_before": str(meta.get("current_time_block") or meta.get("time") or "当前时段"),
        "game_time_after": str(meta.get("current_time_block") or meta.get("time") or "当前时段"),
        "location_before": CURRENT_LOCATION_ID,
        "location_after": CURRENT_LOCATION_ID,
        "summary": summary,
        "events": events,
        "upsert_entities": upserts,
        "tick_clocks": [],
    }


def inventory_entity(case: InventoryCase) -> dict[str, Any]:
    return item_entity(
        case.item_id,
        case.item_name,
        case.category,
        case.quantity,
        case.unit,
        case.source_target_id,
        quality=case.quality,
        risk=case.risk,
        summary=f"{case.text}；测试临时存档入库。",
    )


def item_entity(
    entity_id: str,
    name: str,
    category: str,
    quantity: Any,
    unit: str,
    source_target_id: str,
    *,
    quality: str = "confirmed",
    risk: str = "low",
    location_id: str | None = CURRENT_LOCATION_ID,
    owner_id: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "id": entity_id,
        "type": "item",
        "name": name,
        "status": "active",
        "visibility": "known",
        "summary": summary or f"入库测试物品：{name}。",
        "details": {
            "source": "intake_probe",
            "source_target_id": source_target_id,
            "quantity_confidence": "confirmed" if isinstance(quantity, (int, float)) and quantity > 0 else "invalid_probe",
            "risk": risk,
        },
        "item": {
            "category": category,
            "quantity": quantity,
            "unit": unit,
            "quality": quality,
            "stackable": True,
            "properties": {
                "source_target_id": source_target_id,
                "intake_probe": True,
                "risk": risk,
            },
        },
    }
    if location_id is not None:
        entity["location_id"] = location_id
    if owner_id is not None:
        entity["owner_id"] = owner_id
    return entity


def explore_intake_delta(save_dir: Path, case: WorldCase) -> dict[str, Any]:
    del save_dir
    event = {
        "type": case.expected_event_type,
        "title": "发现事实确认",
        "summary": case.text,
        "payload": {
            "target_query": case.text,
            "target_kind": "unknown_lead",
            "needs_gm_resolution": True,
            "confirmed_entity_ids": list(case.expected_entities),
        },
        "source": "intake_probe",
    }
    return base_explore_delta(case.text, [event], list(case.upserts))


def base_explore_delta(summary: str, events: list[dict[str, Any]], upserts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "user_text": summary,
        "intent": "explore",
        "changed": True,
        "game_time_before": "当前时段",
        "game_time_after": "当前时段",
        "location_before": CURRENT_LOCATION_ID,
        "location_after": CURRENT_LOCATION_ID,
        "summary": summary,
        "events": events,
        "upsert_entities": upserts,
        "tick_clocks": [],
    }


def world_case_location(name: str, text: str, entity_id: str, entity_name: str) -> WorldCase:
    entity = {
        "id": entity_id,
        "type": "location",
        "name": entity_name,
        "status": "active",
        "visibility": "known",
        "summary": f"入库测试发现地点：{entity_name}。",
        "details": {"source": "intake_probe", "confidence": "confirmed"},
        "location": {
            "parent_id": "loc:home-clearing",
            "biome": "probe",
            "safety_level": "unknown",
            "travel_minutes_from_home": 15,
            "description_short": f"测试记录地点：{entity_name}",
            "exits": [],
            "resources": [],
        },
    }
    return WorldCase(name, text, (entity,), (entity_id,), "discovery")


def world_case_simple(name: str, text: str, entity_id: str, entity_type: str, entity_name: str) -> WorldCase:
    entity = {
        "id": entity_id,
        "type": entity_type,
        "name": entity_name,
        "status": "active",
        "visibility": "known",
        "location_id": CURRENT_LOCATION_ID if entity_type not in {"world_setting"} else None,
        "summary": f"入库测试新增事实：{entity_name}。",
        "details": {"source": "intake_probe", "confidence": "confirmed"},
    }
    if entity["location_id"] is None:
        entity.pop("location_id")
    return WorldCase(name, text, (entity,), (entity_id,), "discovery")


def world_case_character(
    name: str,
    text: str,
    character_id: str,
    character_name: str,
    species_id: str,
) -> WorldCase:
    species = {
        "id": species_id,
        "type": "species",
        "name": "测试芦苇人",
        "status": "active",
        "visibility": "known",
        "summary": "入库测试新增物种。",
        "details": {"source": "intake_probe", "confidence": "confirmed"},
    }
    character = {
        "id": character_id,
        "type": "character",
        "name": character_name,
        "status": "active",
        "visibility": "known",
        "location_id": CURRENT_LOCATION_ID,
        "summary": "入库测试新增人物。",
        "details": {"source": "intake_probe", "confidence": "confirmed"},
        "character": {
            "species_id": species_id,
            "role": "envoy",
            "attitude": "cautious",
            "trust": 0,
            "health_state": "unknown",
            "stress": {},
            "consequences": [],
            "goals": [],
            "knowledge": {},
        },
    }
    return WorldCase(name, text, (species, character), (species_id, character_id), "encounter")


def single_bad_item_delta(target: str, entity_id: str, name: str, quantity: Any, unit: str) -> dict[str, Any]:
    event = {
        "type": "gather",
        "title": "异常入库",
        "summary": f"异常入库测试：{name}。",
        "payload": {
            "target_id": target,
            "location_id": CURRENT_LOCATION_ID,
            "output_item_id": entity_id,
            "output_quantity": quantity,
            "output_unit": unit,
        },
        "source": "intake_probe",
    }
    return base_gather_delta(
        {"time": "当前时段"},
        f"异常入库测试：{name}。",
        target,
        [event],
        [item_entity(entity_id, name, "material", quantity, unit, target)],
    )


def commit(
    runtime: GMRuntime,
    delta: dict[str, Any],
    proposal: dict[str, Any],
    action: str,
    options: dict[str, Any],
) -> CommitOutcome:
    try:
        result = runtime.commit_turn(delta, turn_proposal=proposal, backup=False, action=action, action_options=options)
    except Exception as exc:
        return CommitOutcome(False, False, error=f"{type(exc).__name__}: {exc}")
    data = result.to_dict()
    audit = data.get("state_audit") or {}
    findings: list[str] = []
    for item in audit.get("findings", []) if isinstance(audit.get("findings", []), list) else []:
        if isinstance(item, dict):
            findings.append(str(item.get("code") or item.get("message") or item))
        else:
            findings.append(str(item))
    return CommitOutcome(
        True,
        bool(data.get("ok")),
        turn_id=str(data.get("turn_id") or ""),
        check_errors=tuple(str(item) for item in data.get("check_errors", [])),
        audit_findings=tuple(findings),
    )


def human_proposal(action: str, options: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha1(json.dumps(delta, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    intent = ActionIntent(
        user_text=str(options.get("user_text") or delta.get("user_text") or ""),
        mode="action",
        submode=action,
        action=action,
        options=options,
        confidence="high",
        source="intake_probe",
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
        proposal_id=f"turn-proposal:intake:{action}:{digest}",
        intent=intent,
        preview={"action": action, "status": "ready", "facts_used": [], "rules_applied": []},
        delta=delta,
        delta_source="human_edited",
        provenance={"source": "probe_current_save_intake", "resolver": action},
        human_confirmed=True,
        turn_contract=contract,
    ).to_dict()


def table_count(save_dir: Path, table: str) -> int:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    try:
        return int(conn.execute(f"select count(*) from {table}").fetchone()[0])
    finally:
        conn.close()


def meta_map(save_dir: Path) -> dict[str, str]:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    try:
        return {str(row[0]): str(row[1]) for row in conn.execute("select key, value from meta")}
    finally:
        conn.close()


def entity_row(save_dir: Path, entity_id: str | None) -> dict[str, Any] | None:
    if not entity_id:
        return None
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("select * from entities where id = ?", (entity_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def item_row(save_dir: Path, entity_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            select e.id, e.name, e.location_id, e.owner_id, i.category, i.quantity,
                   i.unit, i.quality, i.stackable, i.properties_json
            from entities e
            join items i on i.entity_id = e.id
            where e.id = ?
            """,
            (entity_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def event_for_turn(save_dir: Path, turn_id: str) -> dict[str, Any] | None:
    if not turn_id:
        return None
    conn = sqlite3.connect(save_dir / "data" / "game.sqlite")
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "select * from events where turn_id = ? order by id limit 1",
            (turn_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = json.loads(str(data.get("payload_json") or "{}"))
        return data
    finally:
        conn.close()


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


def issue_for_natural_route(start: dict[str, Any], preview: dict[str, Any]) -> str:
    route = route_key(start)
    pkey = preview_key(preview)
    if route.startswith("query:") or pkey.startswith("query:"):
        return "natural_intake_misread_as_query"
    if "maintenance" in {route, pkey}:
        return "natural_intake_misread_as_maintenance"
    if route == "action:routine" or pkey == "action:routine":
        return "natural_intake_misread_as_routine"
    return "natural_intake_route_gap"


def row_quantity(row: dict[str, Any] | None) -> str:
    if not row:
        return "missing"
    return f"{row.get('quantity')}{row.get('unit') or ''}"


def format_quantity(quantity: float, unit: str) -> str:
    return f"{format_number(quantity)}{unit}"


def format_number(value: float) -> str:
    return f"{value:g}"


def query_has_quantity(text: str, quantity: float, unit: str) -> bool:
    compact = "".join(str(text).split())
    expected = f"{format_number(quantity)}{unit}"
    return expected in compact


def one_line(value: str, *, limit: int = 220) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


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
    by_issue: dict[str, int] = {}
    by_area: dict[str, int] = {}
    total_by_area: dict[str, int] = {}
    pass_by_area: dict[str, int] = {}
    for item in checks:
        total_by_area[item.area] = total_by_area.get(item.area, 0) + 1
        if item.status == "PASS":
            pass_by_area[item.area] = pass_by_area.get(item.area, 0) + 1
            continue
        by_issue[item.issue or "unspecified"] = by_issue.get(item.issue or "unspecified", 0) + 1
        by_area[item.area] = by_area.get(item.area, 0) + 1
    inventory_total = total_by_area.get("confirmed inventory intake", 0)
    inventory_pass = pass_by_area.get("confirmed inventory intake", 0)
    world_total = total_by_area.get("confirmed world/event intake", 0)
    world_pass = pass_by_area.get("confirmed world/event intake", 0)
    natural_total = total_by_area.get("natural gather recognition", 0) + total_by_area.get(
        "natural discovery recognition",
        0,
    )
    natural_pass = pass_by_area.get("natural gather recognition", 0) + pass_by_area.get(
        "natural discovery recognition",
        0,
    )
    guardrail_total = total_by_area.get("intake guardrail", 0)
    guardrail_pass = pass_by_area.get("intake guardrail", 0)

    lines = [
        "# Current Save Intake Probe",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        "Focus: gather/acquisition intake, newly discovered civilization/event facts, quantity correctness, and immediate queryability after commit.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(checks)}",
        "",
        "## Key Findings",
        "",
        f"- Confirmed inventory intake: {inventory_pass}/{inventory_total} passed; explicit `upsert_entities` stored the right item, quantity, event payload, and immediate query result.",
        f"- Confirmed world/event intake: {world_pass}/{world_total} passed; new locations, factions, species, references, threats, relationships, and characters were immediately queryable.",
        f"- Natural player-language intake recognition: {natural_pass}/{natural_total} passed; failures are mostly query/route misclassification before structured confirmation.",
        f"- Intake guardrails: {guardrail_pass}/{guardrail_total} passed; several bad deltas still commit or write before post-check.",
        "",
        "## Test Design",
        "",
        "- Natural player inputs are routed through `start_turn` and `preview_from_text`; they must not mutate the save during preview.",
        "- Confirmed inventory intake uses human-confirmed gather deltas with explicit `upsert_entities` and checks SQLite plus immediate `query()` results.",
        "- Confirmed world/event intake uses human-confirmed explore deltas and checks event rows, entity rows, and immediate `query()` results.",
        "- Guardrail cases intentionally submit bad intake deltas and expect pre-commit blocking with no persisted bad entity.",
        "",
    ]
    if by_issue:
        lines.extend(["## Issue Summary", "", "| Issue | Count |", "|---|---:|"])
        for issue, count in sorted(by_issue.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| `{issue}` | {count} |")
        lines.append("")
    if by_area:
        lines.extend(["## Issue By Area", "", "| Area | Count |", "|---|---:|"])
        for area, count in sorted(by_area.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {area} | {count} |")
        lines.append("")
    issues = [item for item in checks if item.status != "PASS"]
    lines.extend(["## Issues", ""])
    if not issues:
        lines.append("No issues found.")
    else:
        lines.extend(["| Area | Case | Observed | Expected | Issue |", "|---|---|---|---|---|"])
        for item in issues:
            lines.append(
                f"| {escape(item.area)} | {escape(item.name)} | {escape(item.observed)} | "
                f"{escape(item.expected)} | `{item.issue}` |"
            )
    lines.extend(["", "## Full Matrix", "", "| Status | Area | Case | Observed | Expected |", "|---|---|---|---|---|"])
    for item in checks:
        lines.append(
            f"| {item.status} | {escape(item.area)} | {escape(item.name)} | "
            f"{escape(item.observed)} | {escape(item.expected)} |"
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
