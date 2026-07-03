from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...campaign import Campaign
from ...db import connect
from ...projection_service import ProjectionService
from ...save import save_turn_delta
from ...time_weather import enrich_time_weather_meta


KNOWN_LOCATION_IDS = {
    "L1": "loc:l01-creek",
    "L2": "loc:l02-pool",
    "L3": "loc:l03-pinewood",
    "L4": "loc:l04-bramble-ring",
    "L5": "loc:l05-oldwood",
    "L6": "loc:l06-waterfall",
    "L7": "loc:l07-sulfur-spring",
    "L8": "loc:l08-stone-terrace",
    "L9": "loc:l09-underground-home",
    "L10": "loc:l10-river",
    "L11": "loc:l11-delta",
    "L12": "loc:l12-niter-crust",
    "L13": "loc:l13-stone-trough",
    "L14": "loc:l14-humus-wetland",
    "L15": "loc:l15-grassland-cliff",
    "L15-E": "loc:l15-east-ashmoss-hearth",
    "L15-W": "loc:l15-west-quartz-quarry",
    "L6+": "loc:l06-t5-overlook-trough",
}

KNOWN_LOCATION_NAME_IDS = {
    "灰藓族湖边聚落": "loc:lake-ashmoss-settlement",
    "空地/家": "loc:home-clearing",
    "树屋松针床": "loc:home-treehouse",
    "六边形菌丝复合屋": "loc:home-mycelium-house",
    "菌丝城": "loc:home-mycelium-city",
    "菌丝城H室": "loc:home-mycelium-h-room",
    "石槽深潭": "loc:l13-stone-trough",
    "腐殖湿地": "loc:l14-humus-wetland",
    "森林断崖/草原": "loc:l15-grassland-cliff",
    "废弃灰藓族火塘": "loc:l15-east-ashmoss-hearth",
    "石英采掘场": "loc:l15-west-quartz-quarry",
    "T5瞭望石槽": "loc:l06-t5-overlook-trough",
}

KNOWN_ITEM_IDS = {
    "终极复合弩": "item:ultimate-compound-crossbow",
    "愈疮木长矛": "item:curewood-spear",
    "愈疮木短刀": "item:curewood-knife",
    "藤盾": "item:vine-shield",
    "火药箭": "item:powder-arrows",
    "毒弩箭": "item:poison-bolts",
    "普通弩箭": "item:plain-bolts",
    "旧毒弩箭": "item:poison-bolts",
    "旧普通箭": "item:plain-bolts",
    "紫黑毒箭": "item:toxic-thorn-bolts",
    "霜白冻箭": "item:frost-thorn-bolts",
    "琥珀麻箭": "item:stun-thorn-bolts",
    "赤红炸箭": "item:burst-thorn-bolts",
    "黑火药（造粒）": "item:black-powder",
    "黑火药": "item:black-powder",
    "盐": "item:salt",
    "松子油": "item:pine-nut-oil",
    "浆果醋（发酵中）": "item:berry-vinegar-ferment",
    "竹编鱼笼": "item:fishing-trap",
    "竹藤胸甲": "item:bamboo-vine-breastplate",
    "竹藤背包": "item:bamboo-vine-backpack",
}

KNOWN_PLANT_IDS = {
    "红薯": "plant:sweet-potato",
    "红薯②": "plant:sweet-potato",
    "矮生豇豆": "plant:cowpea",
    "苋菜": "plant:amaranth",
    "矮油菜": "plant:leafy-mix",
    "土豆": "plant:potato",
    "土豆②": "plant:potato",
    "空心菜": "plant:leafy-mix",
    "韭菜": "plant:leafy-mix",
    "木耳菜": "plant:leafy-mix",
    "生菜+芥蓝混栽": "plant:leafy-mix",
    "盐角草": "plant:saltgrass",
    "芝麻": "plant:sesame",
    "大豆": "plant:soybean",
    "甜菜": "plant:sugar-beet",
    "储存南瓜": "plant:storage-pumpkin",
    "铁木": "plant:ironwood",
    "见血封喉（箭毒木）": "plant:antiaris-toxicaria",
    "见血封喉": "plant:antiaris-toxicaria",
    "巨型实心竹": "plant:giant-solid-bamboo",
    "韧皮纤维植物（未命名）": "plant:bast-fiber",
    "愈疮木": "plant:curewood",
    "油桐": "plant:tung-tree",
    "麻": "plant:hemp",
    "藤条（编织用）": "plant:weaving-vine",
    "藤条": "plant:weaving-vine",
    "龙息柳（弩臂材料）": "plant:dragonbreath-willow",
    "龙息柳": "plant:dragonbreath-willow",
    "星髓木（弩身材料）": "plant:star-pith-wood",
    "星髓木": "plant:star-pith-wood",
    "月蛛藤（弩弦材料）": "plant:moon-spider-vine",
    "月蛛藤": "plant:moon-spider-vine",
    "晶节竹（凸轮/轴承材料）": "plant:crystal-node-bamboo",
    "晶节竹": "plant:crystal-node-bamboo",
    "镜面苔（箭轨涂层）": "plant:mirror-moss",
    "镜面苔": "plant:mirror-moss",
    "鹰瞳果（魔力瞄镜）": "plant:eagle-eye-fruit",
    "鹰瞳果": "plant:eagle-eye-fruit",
    "渊刺藤（魔力弹药藤·活体）": "plant:abyss-thorn-vine",
    "渊刺藤": "plant:abyss-thorn-vine",
    "直脊杉（箭杆材料）": "plant:straight-spine-fir",
    "直脊杉": "plant:straight-spine-fir",
}

KNOWN_CHARACTER_IDS = {
    "C1": "char:an",
    "C2": "char:ashmoss-young",
    "An": "char:an",
    '"小的"': "char:ashmoss-young",
    "小的": "char:ashmoss-young",
}

KNOWN_THREAT_IDS = {
    "T1": "threat:t1-night-hum",
    "T2": "threat:t2-large-cat",
    "T3": "threat:t3-hatched-unknown",
    "T4": "threat:t4-reptile",
    "T5": "threat:t5-large-print",
}

KNOWN_CREATURE_IDS = {
    "F1": "creature:ungulate-f1",
    "F2": "creature:slime-common-small",
    "F3": "creature:slime-acid-medium",
    "F4": "creature:slime-hardened-medium",
    "F5": "creature:slime-milky-medium",
    "F6": "creature:slime-water-medium",
    "T1": "threat:t1-night-hum",
    "T2": "threat:t2-large-cat",
    "T3": "threat:t3-hatched-unknown",
    "T4": "threat:t4-reptile",
    "T5": "threat:t5-large-print",
}

KNOWN_EQUIPMENT_IDS = {
    "竹藤胸甲": "item:bamboo-vine-breastplate",
    "铁木弩": "item:ironwood-crossbow",
    "竹弓（退役备用）": "item:bamboo-bow",
    "竹弓": "item:bamboo-bow",
    "铁木长矛": "item:ironwood-spear",
    "铁木短刀": "item:ironwood-knife",
    "藤盾": "item:vine-shield",
    "竹藤背包": "item:bamboo-vine-backpack",
}

LEGACY_DUPLICATE_TARGETS = {
    "threat:t3-a076e9": ("threat", "不明孵化物", "threat:t3-hatched-unknown"),
    "threat:t4-cce009": ("threat", "不明爬行生物", "threat:t4-reptile"),
    "item:v1-401496103b": ("item", "竹藤背包", "item:bamboo-vine-backpack"),
    "item:v1-6d947fa58d": ("equipment", "竹藤胸甲", "item:bamboo-vine-breastplate"),
}


@dataclass
class ImportReport:
    source_dir: Path
    entities: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    applied_turn_id: str | None = None

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for entity in self.entities:
            entity_type = str(entity["type"])
            result[entity_type] = result.get(entity_type, 0) + 1
        return dict(sorted(result.items()))

    def to_markdown(self) -> str:
        lines = [
            "# isekai-farm v1 导入报告",
            "",
            f"源目录：`{self.source_dir}`",
            f"应用回合：{self.applied_turn_id or '未应用（dry-run）'}",
            "",
            "## 实体统计",
            "",
            "| 类型 | 数量 |",
            "|------|------|",
        ]
        for key, value in self.counts().items():
            lines.append(f"| {key} | {value} |")
        lines.extend(["", "## Meta", ""])
        if self.meta:
            for key, value in self.meta.items():
                lines.append(f"- `{key}`: {value}")
        else:
            lines.append("- 无")
        lines.extend(["", "## 警告", ""])
        lines.extend(f"- {item}" for item in self.warnings) if self.warnings else lines.append("- 无")
        lines.extend(["", "## 跳过", ""])
        lines.extend(f"- {item}" for item in self.skipped) if self.skipped else lines.append("- 无")
        return "\n".join(lines)


def import_v1_state(campaign: Campaign, source_dir: Path, *, apply: bool = False) -> ImportReport:
    state_path = source_dir / "state.md"
    if not state_path.exists():
        raise FileNotFoundError(state_path)
    text = state_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    report = ImportReport(source_dir=source_dir)

    report.meta.update(parse_time_meta(text))

    player = parse_player(text)
    report.meta["current_location_id"] = str(player.get("location_id") or "loc:home-clearing")
    for entity in parse_current_base_locations(text):
        add_entity(report, entity)
    add_entity(report, player)
    for entity in parse_landmarks(lines, report):
        add_entity(report, entity)
    for entity in parse_equipment_tables(lines, report):
        add_entity(report, entity)
    for entity in parse_crop_plots(lines, report):
        add_entity(report, entity)
    for entity in parse_threat_tables(lines, report):
        add_entity(report, entity)
    for entity in parse_projects(lines, report):
        add_entity(report, entity)

    world_path = source_dir / "world.md"
    if world_path.exists():
        for entity in parse_world(world_path, report):
            add_entity(report, entity)
    else:
        report.warnings.append(f"缺少 world.md: {world_path}")

    characters_path = source_dir / "characters.md"
    if characters_path.exists():
        for entity in parse_characters(characters_path, report):
            add_entity(report, entity)
    else:
        report.warnings.append(f"缺少 characters.md: {characters_path}")

    for entity in parse_sapient_contacts(lines, report):
        add_entity(report, entity)

    if apply:
        delta = {
            "user_text": "import isekai-farm v1 markdown state",
            "intent": "import_v1",
            "changed": True,
            "summary": f"Imported {len(report.entities)} entities from {source_dir}",
            "events": [
                {
                    "type": "import",
                    "title": "v1 Markdown import",
                    "summary": f"Imported structured state from {state_path}",
                    "payload": {
                        "source": str(state_path),
                        "entity_count": len(report.entities),
                        "counts": report.counts(),
                    },
                    "source": "isekai_farm_v1_importer",
                }
            ],
            "upsert_entities": report.entities + legacy_retirement_entities(),
            "meta": report.meta,
        }
        with connect(campaign) as conn:
            report.applied_turn_id = save_turn_delta(campaign, conn, delta)
            ProjectionService(campaign, conn).refresh(
                names=["snapshots"],
                dirty_only=False,
                profile="compat_importer:import_projection",
                commit_policy="caller_committed_required",
            )

    return report


def legacy_retirement_entities() -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for entity_id, (entity_type, name, merged_into) in LEGACY_DUPLICATE_TARGETS.items():
        entities.append(
            {
                "id": entity_id,
                "type": entity_type,
                "name": name,
                "status": "archived",
                "visibility": "known",
                "summary": f"旧导入重复实体；当前已合并到 {merged_into}",
                "aliases": [],
                "details": {
                    "merged_into": merged_into,
                    "reason": "legacy duplicate from earlier v2 staging import",
                },
            }
        )
    return entities


def add_entity(report: ImportReport, entity: dict[str, Any] | None) -> None:
    if not entity:
        return
    existing = next((item for item in report.entities if item["id"] == entity["id"]), None)
    if existing:
        merge_entity(existing, entity)
        return
    report.entities.append(entity)


def merge_entity(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        if value is None:
            continue
        if key == "aliases":
            current = existing.setdefault("aliases", [])
            for alias in value:
                if alias and alias not in current:
                    current.append(alias)
        elif key == "details":
            current = existing.setdefault("details", {})
            if isinstance(current, dict) and isinstance(value, dict):
                current.update(value)
            else:
                existing[key] = value
        elif key in {"character", "item", "location", "crop_plot"}:
            current = existing.setdefault(key, {})
            if isinstance(current, dict) and isinstance(value, dict):
                current.update({k: v for k, v in value.items() if v is not None})
            else:
                existing[key] = value
        elif key == "summary":
            current = str(existing.get("summary", ""))
            incoming_text = str(value)
            if len(incoming_text) > len(current):
                existing[key] = incoming_text
        else:
            existing[key] = value


def parse_time_meta(text: str) -> dict[str, str]:
    block = extract_code_block_after(text, "## ⏰ 时间")
    meta: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        if "：" not in raw_line:
            if current_key and raw_line.strip():
                meta_key = time_meta_key(current_key)
                if meta_key and meta_key in meta:
                    meta[meta_key] = f"{meta[meta_key]}{raw_line.strip()}"
            continue
        key, value = raw_line.split("：", 1)
        key = key.strip()
        value = value.strip()
        current_key = key
        if key == "天数":
            match = re.search(r"第\s*(\d+)\s*天", value)
            if match:
                meta["current_game_day"] = match.group(1)
        elif key == "时段":
            meta["current_time_block"] = value
        elif key == "年份":
            meta["year_label"] = value
        elif key == "季节":
            meta["season_label"] = value
        elif key == "月份":
            meta["month_label"] = value
        elif key == "天气":
            meta["weather_label"] = value
    return enrich_time_weather_meta(meta)


def time_meta_key(key: str) -> str | None:
    return {
        "时段": "current_time_block",
        "天气": "weather_label",
        "气温": "temperature_label",
        "月相": "moon_label",
        "明日推测": "tomorrow_guess",
    }.get(key)


def extract_code_block_after(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    fence_start = text.find("```", start)
    if fence_start < 0:
        return ""
    fence_end = text.find("```", fence_start + 3)
    if fence_end < 0:
        return ""
    return text[fence_start + 3 : fence_end].strip()


def parse_player(text: str) -> dict[str, Any]:
    block = extract_code_block_after(text, "## ❤️ 主角")
    details: dict[str, str] = {}
    for raw_line in block.splitlines():
        if "：" not in raw_line:
            continue
        key, value = raw_line.split("：", 1)
        key = key.strip()
        value = value.strip()
        if key in {"饱食度", "体力", "健康", "口渴度", "负重", "睡眠", "当前位置"}:
            details[translate_player_key(key)] = value
    summary = "；".join(
        part
        for part in [
            f"健康{details.get('health', '未知')}",
            f"体力{details.get('stamina', '未知')}",
            f"饥饿{details.get('hunger', '未知')}",
            f"位置{details.get('location_text', '未知')}",
        ]
        if part
    )
    details.setdefault("golden_light", parse_golden_light(text))
    location_id = infer_current_location_id(details.get("location_text", ""))
    return {
        "id": "pc:shenyan",
        "type": "character",
        "name": "亚",
        "status": "active",
        "visibility": "known",
        "location_id": location_id,
        "summary": summary,
        "aliases": ["主角", "玩家", "亚", "沈砚"],
        "details": details,
        "character": {
            "species_id": "species:human",
            "role": "player_character",
            "attitude": "self",
            "trust": 100,
            "health_state": details.get("health", "未知"),
        },
    }


def infer_current_location_id(location_text: str) -> str:
    if "六边形菌丝复合屋" in location_text or "新屋" in location_text:
        return "loc:home-mycelium-house"
    if "菌丝城H室" in location_text:
        return "loc:home-mycelium-h-room"
    if "菌丝城" in location_text:
        return "loc:home-mycelium-city"
    if "树屋" in location_text:
        return "loc:home-treehouse"
    return "loc:home-clearing"


def parse_current_base_locations(text: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    if "六边形菌丝复合屋" in text:
        entities.append(
            {
                "id": "loc:home-mycelium-house",
                "type": "location",
                "name": "六边形菌丝复合屋",
                "status": "active",
                "visibility": "known",
                "location_id": "loc:home-clearing",
                "summary": "第23天竣工的主居所，位于700㎡围墙领地中央；有菌丝床、厨房角、储物墙和通往地下菌丝城的竖井入口。",
                "aliases": ["新屋", "菌丝屋", "主居所", "六边形屋"],
                "details": {
                    "source": "state.md:设施",
                    "constructed_day": 23,
                    "area": "约28㎡",
                },
                "location": {
                    "parent_id": "loc:home-clearing",
                    "biome": "mycelium_house",
                    "safety_level": "defended",
                    "travel_minutes_from_home": 0,
                    "description_short": "领地中央的六边形菌丝复合屋，当前主居所。",
                    "exits": ["空地/家", "地下菌丝城竖井"],
                    "resources": ["菌丝床", "厨房角", "储物墙", "竖井入口"],
                },
            }
        )
    if "菌丝城" in text:
        entities.append(
            {
                "id": "loc:home-mycelium-city",
                "type": "location",
                "name": "地下菌丝城",
                "status": "active",
                "visibility": "known",
                "location_id": "loc:home-clearing",
                "summary": "母孢子树/夏娃扩展出的地下菌丝城，有12臂穹顶、13侧室、4条隧道和菌群分工体系。",
                "aliases": ["菌丝城", "地下城", "夏娃地下城"],
                "details": {
                    "source": "state.md:母孢子树/设施",
                    "rooms": "A育成B编织C沉积D仓库E锐孢F思菌G农场H An生活室I生活室J岩铠K织坊L深层M厨房",
                },
                "location": {
                    "parent_id": "loc:home-clearing",
                    "biome": "mycelium_underground",
                    "safety_level": "defended",
                    "travel_minutes_from_home": 1,
                    "description_short": "领地下方的菌丝城市和生产中枢。",
                    "exits": ["六边形菌丝复合屋竖井", "西隧至L9", "各功能侧室"],
                    "resources": ["腐工蕈", "锐孢蕈", "思菌蕈", "地下仓库", "菌丝厨房"],
                },
            }
        )
        entities.append(
            {
                "id": "loc:home-mycelium-h-room",
                "type": "location",
                "name": "菌丝城H室",
                "status": "active",
                "visibility": "known",
                "location_id": "loc:home-mycelium-city",
                "summary": "An 和小的搬入后的独立生活侧室；有火塘、草席、骨刀石斧和三块石板。",
                "aliases": ["H室", "An生活室", "An的新家"],
                "details": {
                    "source": "state.md:智慧生物接触",
                },
                "location": {
                    "parent_id": "loc:home-mycelium-city",
                    "biome": "mycelium_underground_room",
                    "safety_level": "friendly",
                    "travel_minutes_from_home": 1,
                    "description_short": "菌丝城内给 An 与小的居住的侧室。",
                    "exits": ["地下菌丝城主腔", "西隧至L9"],
                    "resources": ["火塘", "草席", "石板", "灰藓族生活物资"],
                },
            }
        )
    return entities


def translate_player_key(key: str) -> str:
    return {
        "饱食度": "hunger",
        "体力": "stamina",
        "健康": "health",
        "口渴度": "thirst",
        "负重": "load",
        "睡眠": "sleep",
        "当前位置": "location_text",
    }[key]


def parse_golden_light(text: str) -> str:
    block = extract_code_block_after(text, "## 🔧 万能农具")
    for raw_line in block.splitlines():
        if raw_line.strip().startswith("金光") and "：" in raw_line:
            return raw_line.split("：", 1)[1].strip()
    return "未知"


def parse_landmarks(lines: list[str], report: ImportReport) -> list[dict[str, Any]]:
    rows = table_after_heading(lines, "### 已探明地标")
    entities: list[dict[str, Any]] = []
    for row in rows:
        raw_id = row.get("ID", "").strip()
        name = clean_name(row.get("名称", ""))
        if not name:
            continue
        entity_id = KNOWN_LOCATION_IDS.get(raw_id) or KNOWN_LOCATION_NAME_IDS.get(name) or f"loc:v1-{stable_hash(name)}"
        direction = clean_text(row.get("方向", ""))
        distance = clean_text(row.get("距离", ""))
        travel = clean_text(row.get("步行", ""))
        location_type = clean_text(row.get("类型", ""))
        entities.append(
            {
                "id": entity_id,
                "type": "location",
                "name": name,
                "status": "active",
                "summary": f"{direction}，{distance}，步行{travel}；类型：{location_type}",
                "aliases": [raw_id, name] if raw_id and raw_id != "—" else [name],
                "details": {
                    "v1_id": raw_id,
                    "direction": direction,
                    "distance": distance,
                    "elevation_delta": clean_text(row.get("海拔差", "")),
                    "source": "state.md:已探明地标",
                },
                "location": {
                    "travel_minutes_from_home": parse_int(travel),
                    "description_short": f"{name}：{location_type}；{direction}；{distance}",
                    "resources": [location_type] if location_type else [],
                },
            }
        )
    return entities


def parse_equipment_tables(lines: list[str], report: ImportReport) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in table_after_heading(lines, "### 武器系统"):
        name = clean_name(row.get("名称", ""))
        slot = clean_text(row.get("槽位", ""))
        if not name or name == "—":
            continue
        if slot in {"—", "-", ""}:
            report.skipped.append(f"武器组件行：{name}")
            continue
        status_text = clean_text(row.get("状态", ""))
        location_text = clean_text(row.get("位置", ""))
        status = "retired" if "退役" in slot or "备用" in status_text else "active"
        entity_id = KNOWN_ITEM_IDS.get(name) or f"item:v1-{stable_hash('weapon:' + name)}"
        entities.append(
            {
                "id": entity_id,
                "type": "equipment",
                "name": name,
                "status": status,
                "owner_id": "pc:shenyan" if status == "active" else None,
                "location_id": None if status == "active" else "loc:home-clearing",
                "summary": clean_text(row.get("规格", "")) or status_text,
                "aliases": [name],
                "details": {
                    "slot": slot,
                    "material": clean_text(row.get("材质", "")),
                    "state": status_text,
                    "v1_location": location_text,
                },
                "item": {
                    "category": infer_weapon_category(slot),
                    "quantity": 1,
                    "unit": infer_unit(name),
                    "quality": "legendary" if "终极" in name or "毕业" in status_text else "normal",
                    "equipped_slot": slot if status == "active" else None,
                },
            }
        )

    for row in table_after_heading(lines, "### 弹药库存"):
        name = clean_name(row.get("类型", ""))
        if not name or "合计" in name or "总弩箭" in name:
            continue
        quantity = parse_quantity(row.get("数量", ""))
        if quantity is None:
            report.skipped.append(f"非库存弹药行：{name}")
            continue
        entity_id = KNOWN_ITEM_IDS.get(name) or f"item:v1-{stable_hash('ammo:' + name)}"
        special = clean_text(row.get("特殊处理", ""))
        storage = clean_text(row.get("存放位置", ""))
        retired = name.startswith("旧") or "退役" in special or "旧小屋" in storage
        entities.append(
            {
                "id": entity_id,
                "type": "item",
                "name": name,
                "status": "retired" if retired else "active",
                "owner_id": None if retired else "pc:shenyan",
                "location_id": "loc:home-clearing" if retired else None,
                "summary": special or clean_text(row.get("材质", "")),
                "aliases": [name],
                "details": {
                    "material": clean_text(row.get("材质", "")),
                    "special": special,
                    "v1_location": storage,
                },
                "item": {
                    "category": "ammunition",
                    "quantity": quantity,
                    "unit": "支" if "支" in row.get("数量", "") else "",
                    "stackable": True,
                },
            }
        )

    for heading, category in [("### 工具/容器", "tool"), ("### 食物库存", "food")]:
        for row in table_after_heading(lines, heading):
            name = clean_name(row.get("物品", ""))
            if not name:
                continue
            if heading == "### 食物库存" and is_duplicate_non_food_inventory_row(name):
                report.skipped.append(f"食物库存遗留非食物行：{name}")
                continue
            quantity_text = clean_text(row.get("数量", "") or row.get("容量/规格", ""))
            if is_consumed(quantity_text):
                report.skipped.append(f"已消耗库存：{name} ({quantity_text})")
                continue
            entity_id = KNOWN_ITEM_IDS.get(name) or f"item:v1-{stable_hash(category + ':' + name)}"
            entities.append(
                {
                    "id": entity_id,
                    "type": "item",
                    "name": name,
                    "status": "active",
                    "location_id": map_location_text(row.get("位置", "")),
                    "summary": clean_text(row.get("类型", "") or row.get("状态", "")),
                    "aliases": [name],
                    "details": {
                        "quantity_text": quantity_text,
                        "storage": clean_text(row.get("可保存", "")),
                        "v1_location": clean_text(row.get("位置", "")),
                    },
                    "item": {
                        "category": infer_item_category(name, row.get("类型", ""), category),
                        "quantity": parse_quantity(quantity_text),
                        "unit": parse_unit(quantity_text),
                        "stackable": True,
                    },
                }
            )
    return entities


def parse_crop_plots(lines: list[str], report: ImportReport) -> list[dict[str, Any]]:
    plots: dict[int, dict[str, Any]] = {}
    plants: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^###\s+畦\s*(\d+)\s+[—-]\s+(.+)$", line.strip())
        if not match:
            continue
        plot_no = int(match.group(1))
        crop_name = clean_name(match.group(2))
        attrs = property_table_after(lines, index + 1)
        crop_id = KNOWN_PLANT_IDS.get(crop_name) or f"plant:v1-{stable_hash(crop_name)}"
        plants[crop_id] = {
            "id": crop_id,
            "type": "plant",
            "name": strip_crop_suffix(crop_name),
            "status": "active",
            "summary": clean_text(attrs.get("用途", "") or attrs.get("产出", "") or attrs.get("预计产量", "")) or "v1导入作物",
            "aliases": [crop_name, strip_crop_suffix(crop_name)],
        }
        stage, stage_max = parse_growth_stage(attrs.get("生长阶段", ""))
        plots[plot_no] = {
            "id": f"plot:field-{plot_no:03d}",
            "type": "crop_plot",
            "name": f"畦{plot_no} {crop_name}",
            "status": "active",
            "location_id": "loc:home-clearing",
            "summary": clean_text(attrs.get("当前状态", "")) or f"{crop_name}作物畦",
            "aliases": [f"畦{plot_no}", f"畦{plot_no}{crop_name}"],
            "details": {
                "v1_attrs": attrs,
                "source": "state.md:耕地",
            },
            "crop_plot": {
                "plot_no": plot_no,
                "crop_entity_id": crop_id,
                "area_sqm": parse_area(attrs.get("面积", "")),
                "planted_day": parse_day(attrs.get("播种日", "")),
                "growth_stage": stage,
                "growth_stage_max": stage_max,
                "harvest_day_min": parse_day(attrs.get("预计首收", "") or attrs.get("预计首摘", "")),
                "harvest_day_max": None,
                "harvest_status": infer_harvest_status(attrs),
                "water_status": "needs_check",
                "soil_status": "active",
                "expected_yield": clean_text(attrs.get("预计产量", "") or attrs.get("产出", "") or attrs.get("后续周期", "")),
                "notes": clean_text(attrs.get("当前状态", "")),
            },
        }
    return list(plants.values()) + [plots[key] for key in sorted(plots)]


def parse_threat_tables(lines: list[str], report: ImportReport) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in table_after_heading(lines, "### 活跃威胁"):
        raw_id = clean_text(row.get("ID", ""))
        name = clean_name(row.get("名称", ""))
        if not raw_id or not name:
            continue
        if raw_id in KNOWN_CHARACTER_IDS:
            entity_id = KNOWN_CHARACTER_IDS[raw_id]
            entities.append(
                {
                    "id": entity_id,
                    "type": "character",
                    "name": clean_character_name(name),
                    "status": "active",
                    "visibility": "known",
                    "location_id": "loc:l09-underground-home" if raw_id in {"C1", "C2"} else None,
                    "summary": clean_text(row.get("状态", "")),
                    "details": {
                        "evidence": clean_text(row.get("证据", "")),
                        "last_activity": clean_text(row.get("最近活动", "")),
                        "source": "state.md:活跃威胁",
                    },
                    "character": {
                        "species_id": "species:ashmoss-folk",
                        "role": "ally" if raw_id in {"C1", "C2"} else "unknown",
                        "attitude": "friendly" if raw_id in {"C1", "C2"} else "unknown",
                        "trust": 70 if raw_id == "C1" else 60 if raw_id == "C2" else 0,
                        "health_state": "未知",
                    },
                }
            )
            continue
        entity_id = KNOWN_THREAT_IDS.get(raw_id) or f"threat:{raw_id.lower()}-{stable_hash(name)[:6]}"
        entities.append(
            {
                "id": entity_id,
                "type": "threat",
                "name": name,
                "status": "inactive" if "已离开" in row.get("状态", "") else "active",
                "visibility": "known",
                "summary": clean_text(row.get("证据", "")),
                "aliases": [raw_id, name],
                "details": {
                    "tier_estimate": clean_text(row.get("魔物等级", "")),
                    "last_activity": clean_text(row.get("最近活动", "")),
                    "state": clean_text(row.get("状态", "")),
                    "source": "state.md:活跃威胁",
                },
            }
        )
    return entities


def parse_sapient_contacts(lines: list[str], report: ImportReport) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in table_after_heading(lines, "### 🆕 智慧生物接触"):
        raw_id = clean_text(row.get("ID", ""))
        name = clean_character_name(clean_name(row.get("名称", "")))
        if raw_id not in KNOWN_CHARACTER_IDS or not name:
            continue
        entity_id = KNOWN_CHARACTER_IDS[raw_id]
        location_id = map_location_text(row.get("位置", "")) or "loc:home-mycelium-h-room"
        entities.append(
            {
                "id": entity_id,
                "type": "character",
                "name": name,
                "status": "active",
                "visibility": "known",
                "location_id": location_id,
                "summary": clean_text(row.get("备注", "") or row.get("状态", "")),
                "aliases": [raw_id, name],
                "details": {
                    "state": clean_text(row.get("状态", "")),
                    "v1_location": clean_text(row.get("位置", "")),
                    "source": "state.md:智慧生物接触",
                },
                "character": {
                    "species_id": "species:ashmoss-folk",
                    "role": "ally",
                    "attitude": "friendly",
                    "trust": 75 if raw_id == "C1" else 65,
                    "health_state": "未知",
                },
            }
        )
    return entities


def parse_projects(lines: list[str], report: ImportReport) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for row in table_after_heading(lines, "## 📋 进行中项目"):
        name = clean_name(row.get("项目", ""))
        if not name:
            continue
        entities.append(
            {
                "id": f"project:v1-{stable_hash(name)}",
                "type": "project",
                "name": name,
                "status": "active" if "✅" not in row.get("状态", "") else "completed",
                "summary": clean_text(row.get("状态", "")),
                "aliases": [name],
                "details": {
                    "started": clean_text(row.get("启动日", "")),
                    "expected": clean_text(row.get("预计完成", "")),
                    "progress": clean_text(row.get("进度", "")),
                    "source": "state.md:进行中项目",
                },
            }
        )
    # Short-term checklist is intentionally not imported yet; it needs a richer task model.
    return entities


def parse_world(path: Path, report: ImportReport) -> list[dict[str, Any]]:
    sections = split_sections(path.read_text(encoding="utf-8"))
    entities: list[dict[str, Any]] = []
    for section in sections:
        if section.level != 3:
            continue
        parent = section.parent or ""
        title = clean_name(section.title)
        if not title:
            continue
        if "植物志" in parent or title in KNOWN_PLANT_IDS:
            entities.append(world_plant_entity(title, section))
        elif "动物志" in parent:
            entities.append(world_creature_entity(title, section))
        elif "护甲系统" in parent:
            entities.append(world_equipment_entity(title, section))
        elif "死亡森林" in parent and "地标" in title:
            entities.extend(world_landmark_entities(section))
        elif "死亡森林" in parent:
            entities.append(world_reference_entity("lore", f"死亡森林·{title}", section))
        elif "万能农具" in parent:
            entities.append(world_reference_entity("rule", f"万能农具·{title}", section))
        elif "战斗参考" in parent:
            if title in KNOWN_PLANT_IDS:
                entities.append(world_plant_entity(title, section))
            else:
                entities.append(world_reference_entity("reference", f"战斗参考·{title}", section))

    for row in table_after_heading(path.read_text(encoding="utf-8").splitlines(), "### 资源分布"):
        name = clean_name(row.get("资源", ""))
        if not name:
            continue
        entity_id = f"mat:resource-{stable_hash(name)}"
        entities.append(
            {
                "id": entity_id,
                "type": "material",
                "name": name,
                "status": "active",
                "summary": f"{clean_text(row.get('丰度', ''))}；{clean_text(row.get('主要分布', ''))}；用途：{clean_text(row.get('用途', ''))}",
                "aliases": [name],
                "details": {
                    "abundance": clean_text(row.get("丰度", "")),
                    "distribution": clean_text(row.get("主要分布", "")),
                    "use": clean_text(row.get("用途", "")),
                    "source": "world.md:资源分布",
                },
            }
        )
    return entities


def parse_characters(path: Path, report: ImportReport) -> list[dict[str, Any]]:
    sections = split_sections(path.read_text(encoding="utf-8"))
    entities: list[dict[str, Any]] = []
    for section in sections:
        if section.level != 3:
            continue
        title = clean_name(section.title)
        raw_code = first_code_block(section.body)
        kv = parse_colon_block(raw_code)
        excerpt = compact_excerpt(raw_code or section.body)
        match = re.match(r"^(C\d+|F\d+|T\d+)\s*·\s*(.+)$", title)
        if not match:
            continue
        raw_id = match.group(1)
        display_name = clean_character_name(clean_name(match.group(2)))
        if raw_id in KNOWN_CHARACTER_IDS:
            entity_id = KNOWN_CHARACTER_IDS[raw_id]
            entities.append(
                {
                    "id": entity_id,
                    "type": "character",
                    "name": display_name,
                    "status": "active",
                    "visibility": "known",
                    "location_id": "loc:l09-underground-home" if raw_id in {"C1", "C2"} else None,
                    "summary": first_meaningful_value(kv, ["分类", "体型", "行为特征"]) or excerpt,
                    "aliases": [raw_id, display_name],
                    "details": {
                        "profile": kv,
                        "profile_excerpt": excerpt,
                        "source": f"characters.md:{section.title}",
                    },
                    "character": {
                        "species_id": "species:ashmoss-folk",
                        "role": "ally",
                        "attitude": "friendly",
                        "trust": 72 if raw_id == "C1" else 62,
                        "health_state": "未见异常",
                    },
                }
            )
        else:
            entity_id = KNOWN_CREATURE_IDS.get(raw_id) or f"creature:{raw_id.lower()}-{stable_hash(display_name)}"
            entity_type = "threat" if raw_id.startswith("T") else "species"
            entities.append(
                {
                    "id": entity_id,
                    "type": entity_type,
                    "name": display_name,
                    "status": "active",
                    "visibility": "known",
                    "summary": first_meaningful_value(kv, ["分类", "证据", "威胁评估", "习性"]) or excerpt,
                    "aliases": [raw_id, display_name],
                    "details": {
                        "profile": kv,
                        "profile_excerpt": excerpt,
                        "source": f"characters.md:{section.title}",
                    },
                }
            )
    return entities


@dataclass
class Section:
    level: int
    title: str
    parent: str | None
    body: str


def split_sections(text: str) -> list[Section]:
    lines = text.splitlines()
    sections: list[Section] = []
    stack: dict[int, str] = {}
    current_level: int | None = None
    current_title: str | None = None
    current_parent: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal body, current_level, current_title, current_parent
        if current_level is not None and current_title is not None:
            sections.append(Section(current_level, current_title, current_parent, "\n".join(body).strip()))
        body = []

    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            parent = stack.get(level - 1)
            stack[level] = title
            for key in list(stack):
                if key > level:
                    del stack[key]
            current_level = level
            current_title = title
            current_parent = parent
        else:
            body.append(line)
    flush()
    return sections


def world_plant_entity(title: str, section: Section) -> dict[str, Any]:
    code = first_code_block(section.body)
    kv = parse_colon_block(code)
    excerpt = compact_excerpt(code or section.body)
    entity_id = KNOWN_PLANT_IDS.get(title) or f"plant:v1-{stable_hash(title)}"
    return {
        "id": entity_id,
        "type": "plant",
        "name": strip_parenthetical(title),
        "status": "active",
        "summary": first_meaningful_value(kv, ["特性", "用途", "产物", "分类"]) or excerpt,
        "aliases": [title, strip_parenthetical(title)],
        "details": {
            "encyclopedia": kv,
            "encyclopedia_excerpt": excerpt,
            "source": f"world.md:{section.title}",
        },
    }


def world_creature_entity(title: str, section: Section) -> dict[str, Any]:
    code = first_code_block(section.body)
    kv = parse_colon_block(code)
    excerpt = compact_excerpt(code or section.body)
    match = re.match(r"^(F\d+|T\d+)\s*·\s*(.+)$", title)
    raw_id = match.group(1) if match else ""
    name = clean_name(match.group(2)) if match else title
    entity_id = KNOWN_CREATURE_IDS.get(raw_id) or f"creature:v1-{stable_hash(title)}"
    entity_type = "threat" if raw_id.startswith("T") else "species"
    return {
        "id": entity_id,
        "type": entity_type,
        "name": name,
        "status": "active",
        "visibility": "known",
        "summary": first_meaningful_value(kv, ["分类", "证据", "威胁评估", "习性"]) or excerpt,
        "aliases": [raw_id, name] if raw_id else [name],
        "details": {
            "encyclopedia": kv,
            "encyclopedia_excerpt": excerpt,
            "source": f"world.md:{section.title}",
        },
    }


def world_equipment_entity(title: str, section: Section) -> dict[str, Any]:
    excerpt = compact_excerpt(section.body)
    entity_id = KNOWN_EQUIPMENT_IDS.get(title) or KNOWN_ITEM_IDS.get(title) or f"item:v1-{stable_hash('world-eq:' + title)}"
    return {
        "id": entity_id,
        "type": "equipment",
        "name": strip_parenthetical(title),
        "status": "retired" if "退役" in title or "铁木" in title else "active",
        "summary": excerpt,
        "aliases": [title, strip_parenthetical(title)],
        "details": {
            "encyclopedia_excerpt": excerpt,
            "source": f"world.md:{section.title}",
        },
        "item": {
            "category": infer_equipment_category(title),
            "quantity": 1,
            "unit": infer_unit(title),
            "stackable": False,
        },
    }


def world_reference_entity(entity_type: str, title: str, section: Section) -> dict[str, Any]:
    excerpt = compact_excerpt(section.body)
    prefix = "rule" if entity_type == "rule" else "ref"
    return {
        "id": f"{prefix}:v1-{stable_hash(title)}",
        "type": "rule" if entity_type == "rule" else "reference",
        "name": title,
        "status": "active",
        "summary": excerpt,
        "aliases": [title],
        "details": {
            "excerpt": excerpt,
            "source": f"world.md:{section.title}",
        },
    }


def world_landmark_entities(section: Section) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for line in section.body.splitlines():
        match = re.match(r"^\*\*(L\d+)\s*·\s*(.+?)\*\*\s*[—-]\s*(.+)$", line.strip())
        if not match:
            continue
        raw_id, name, summary = match.groups()
        entity_id = KNOWN_LOCATION_IDS.get(raw_id) or f"loc:{raw_id.lower()}-{stable_hash(name)}"
        entities.append(
            {
                "id": entity_id,
                "type": "location",
                "name": clean_name(name),
                "status": "active",
                "summary": clean_text(summary),
                "aliases": [raw_id, clean_name(name)],
                "details": {
                    "encyclopedia_excerpt": clean_text(summary),
                    "source": f"world.md:{section.title}",
                },
                "location": {
                    "description_short": clean_text(summary),
                },
            }
        )
    return entities


def first_code_block(text: str) -> str:
    match = re.search(r"```(.*?)```", text, flags=re.S)
    return match.group(1).strip() if match else ""


def parse_colon_block(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        if "：" in raw_line:
            key, value = raw_line.split("：", 1)
            key = clean_text(key)
            value = clean_text(value)
            if key:
                result[key] = value
                current_key = key
        elif current_key and raw_line.strip():
            result[current_key] = f"{result[current_key]} {clean_text(raw_line)}".strip()
    return result


def compact_excerpt(text: str, *, max_chars: int = 700) -> str:
    text = clean_text(re.sub(r"```", "", text))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def first_meaningful_value(data: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = clean_text(data.get(key, ""))
        if value:
            return value
    return ""


def strip_parenthetical(text: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", text).strip()


def table_after_heading(lines: list[str], heading: str) -> list[dict[str, str]]:
    start = find_line(lines, heading)
    if start < 0:
        return []
    for index in range(start + 1, len(lines)):
        if is_table_header(lines, index):
            return parse_markdown_table(lines, index)
        if index > start + 40 or lines[index].startswith("## "):
            return []
    return []


def property_table_after(lines: list[str], start: int) -> dict[str, str]:
    for index in range(start, min(start + 20, len(lines))):
        if is_table_header(lines, index):
            rows = parse_markdown_table(lines, index)
            result: dict[str, str] = {}
            for row in rows:
                key = row.get("属性", "").strip()
                value = row.get("值", "").strip()
                if key:
                    result[clean_text(key)] = clean_text(value)
            return result
        if lines[index].startswith("### "):
            return {}
    return {}


def find_line(lines: list[str], heading: str) -> int:
    for index, line in enumerate(lines):
        if line.strip() == heading.strip():
            return index
    return -1


def is_table_header(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return lines[index].lstrip().startswith("|") and re.match(r"^\s*\|?\s*:?-{2,}", lines[index + 1]) is not None


def parse_markdown_table(lines: list[str], header_index: int) -> list[dict[str, str]]:
    headers = split_table_row(lines[header_index])
    rows: list[dict[str, str]] = []
    for line in lines[header_index + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        cells = split_table_row(line)
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        if len(cells) > len(headers):
            cells = cells[: len(headers)]
        rows.append(dict(zip(headers, cells, strict=False)))
    return rows


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def stable_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def clean_name(text: str) -> str:
    text = clean_text(text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"[🆕⭐✨✅📦🔴🟣🟠☠️🎋🧪🧂🟡⬜💥🏹💣⚙️🎯🧵🕯️🌙🌸🍄🧊⚡🎧🍯🕸️🥬🍠🫘🥔🌱🌿🥗🌻🟤🎃]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("<br>", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def strip_crop_suffix(text: str) -> str:
    return re.sub(r"[②2]+$", "", clean_name(text)).strip()


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def parse_quantity(text: str | None) -> float | None:
    if not text:
        return None
    text = str(text)
    if re.search(r"^\s*0(?:[（(]|$)", text):
        return 0
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    if "半" in text:
        return 0.5
    if "一" in text or "1" in text:
        return 1.0
    return None


def parse_unit(text: str | None) -> str | None:
    if not text:
        return None
    for unit in ["支", "把", "面", "颗", "个", "枚", "竹杯", "杯", "勺", "片", "根", "株", "丛", "kg", "L", "m"]:
        if unit in text:
            return unit
    return None


def parse_area(text: str | None) -> float | None:
    return parse_quantity(text)


def parse_day(text: str | None) -> int | None:
    if not text:
        return None
    match = re.search(r"第\s*(\d+)\s*天", text)
    if match:
        return int(match.group(1))
    return parse_int(text)


def parse_growth_stage(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def is_consumed(quantity_text: str) -> bool:
    return (
        bool(re.search(r"^\s*0(?:[（(]|$)", quantity_text))
        or "已吃" in quantity_text
        or "已喂" in quantity_text
        or "已采收" in quantity_text
    )


def map_location_text(text: str | None) -> str | None:
    text = clean_text(text)
    if not text or text in {"—", "-"}:
        return None
    if "随身" in text or "背" in text or "腰间" in text:
        return None
    if "L1" in text:
        return "loc:l01-creek"
    if "L2" in text:
        return "loc:l02-pool"
    if "H室" in text or "An生活室" in text:
        return "loc:home-mycelium-h-room"
    if "菌丝城" in text:
        return "loc:home-mycelium-city"
    if "六边形菌丝复合屋" in text or "新屋" in text:
        return "loc:home-mycelium-house"
    if "树屋" in text:
        return "loc:home-treehouse"
    if "旧小屋" in text or "空地" in text or "围栏" in text:
        return "loc:home-clearing"
    return "loc:home-clearing"


def infer_weapon_category(slot: str) -> str:
    if "护" in slot or "防具" in slot:
        return "armor"
    return "weapon"


def infer_equipment_category(name: str) -> str:
    if "背包" in name or "筒" in name or "杯" in name:
        return "container"
    if any(word in name for word in ["甲", "盾", "护臂", "护颈"]):
        return "armor"
    if any(word in name for word in ["弓", "弩", "矛", "刀"]):
        return "weapon"
    return "equipment"


def infer_unit(name: str) -> str:
    if "弩" in name or "刀" in name:
        return "把"
    if "矛" in name:
        return "支"
    if "盾" in name or "甲" in name:
        return "件"
    return "个"


def infer_item_category(name: str, item_type: str, fallback: str) -> str:
    text = f"{name} {item_type}"
    if any(word in text for word in ["火药", "硫磺", "硝石", "纤维", "桐油", "残胶"]):
        return "material"
    if any(word in text for word in ["箭", "地雷"]):
        return "ammunition" if "箭" in text else "trap"
    if fallback == "food" or any(word in text for word in ["盐", "油", "菜", "果", "姜", "辣椒"]):
        return "food"
    return fallback


def is_duplicate_non_food_inventory_row(name: str) -> bool:
    return name in {
        "火药箭",
        "地雷",
        "羊脚杆",
        "瞄具刻度",
    }


def infer_harvest_status(attrs: dict[str, str]) -> str:
    text = " ".join(attrs.values())
    if "可割" in text or "可摘" in text or "可掰" in text or "可砍" in text:
        return "partial_harvest"
    if "已割" in text:
        return "regrowing"
    return "growing"


def clean_character_name(name: str) -> str:
    if "An" in name:
        return "An"
    if "小的" in name:
        return "小的"
    return name
