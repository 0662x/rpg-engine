from __future__ import annotations

import argparse
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from rpg_engine.runtime import GMRuntime


DEFAULT_RP_ROOT = Path("/Users/oliver/.hermes/rp")
CAMPAIGN_DIR_NAME = "isekai-farm-campaign-native-v1"
SAVE_DIR_NAME = "isekai-farm-save-native-v1"


@dataclass(frozen=True)
class ExpectedRoute:
    mode: str
    submode: str
    can_proceed: bool | None = None


@dataclass(frozen=True)
class RouteCase:
    area: str
    name: str
    text: str
    expected: tuple[ExpectedRoute, ...]
    notes: str = ""


@dataclass(frozen=True)
class QueryCase:
    area: str
    name: str
    text: str
    query_kind: str
    expected_route: tuple[ExpectedRoute, ...]
    required_any: tuple[str, ...] = ()
    required_all: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class ProbeResult:
    area: str
    name: str
    text: str
    status: str
    observed: str
    expected: str
    details: list[str] = field(default_factory=list)
    issue: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe query/action recognition on the current isekai-farm save.")
    parser.add_argument("--rp-root", type=Path, default=DEFAULT_RP_ROOT)
    parser.add_argument(
        "--action-output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-action-recognition-probe-2026-07-01.md"),
    )
    parser.add_argument(
        "--query-output",
        type=Path,
        default=Path("reports/2026-07-01/current-save-query-recognition-probe-2026-07-01.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional legacy combined report output.",
    )
    args = parser.parse_args()

    action_results: list[ProbeResult] = []
    query_results: list[ProbeResult] = []
    with copied_save(args.rp_root) as save_dir:
        runtime = GMRuntime.from_path(save_dir)
        for case in action_route_cases():
            action_results.append(run_route_case(runtime, case))
        for case in query_route_cases():
            query_results.append(run_route_case(runtime, case))
        for case in query_cases():
            query_results.append(run_query_case(runtime, case))

    action_report = render_report(
        action_results,
        title="Current Save Action Recognition Probe",
        focus="action type recognition only; query routing/output cases are recorded separately.",
    )
    query_report = render_report(
        query_results,
        title="Current Save Query Recognition Probe",
        focus="query routing and query output usefulness only; action recognition cases are recorded separately.",
    )
    print(action_report)
    print("\n\n---\n")
    print(query_report)
    args.action_output.parent.mkdir(parents=True, exist_ok=True)
    args.query_output.parent.mkdir(parents=True, exist_ok=True)
    args.action_output.write_text(action_report, encoding="utf-8")
    args.query_output.write_text(query_report, encoding="utf-8")
    if args.output:
        combined = render_report(
            [*action_results, *query_results],
            title="Current Save Intent/Query Probe",
            focus="legacy combined report; split action/query reports are authoritative.",
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(combined, encoding="utf-8")
    return 0


@contextmanager
def copied_save(rp_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="aigm-current-save-intent-probe-") as tmp:
        root = Path(tmp)
        shutil.copytree(rp_root / CAMPAIGN_DIR_NAME, root / CAMPAIGN_DIR_NAME)
        shutil.copytree(rp_root / SAVE_DIR_NAME, root / SAVE_DIR_NAME)
        yield root / SAVE_DIR_NAME


def route_cases() -> list[RouteCase]:
    query_scene = (ExpectedRoute("query", "scene", True),)
    query_entity = (ExpectedRoute("query", "entity", True),)
    query_loose = (
        ExpectedRoute("query", "entity", True),
        ExpectedRoute("query", "scene", True),
    )
    routine = (ExpectedRoute("action", "routine", True),)
    travel = (ExpectedRoute("action", "travel", True),)
    social = (ExpectedRoute("action", "social", True),)
    gather = (
        ExpectedRoute("action", "gather", True),
        ExpectedRoute("action", "gather", False),
    )
    combat_clarify = (ExpectedRoute("action", "combat", False),)
    craft = (
        ExpectedRoute("action", "craft", True),
        ExpectedRoute("action", "craft", False),
    )
    rest = (ExpectedRoute("action", "rest", True),)
    composite_or_travel = (
        ExpectedRoute("action", "composite", False),
        ExpectedRoute("action", "travel", True),
        ExpectedRoute("action", "gather", False),
    )
    cases = [
        RouteCase("scene/status query", "look around", "看一下周围", query_scene),
        RouteCase("scene/status query", "where am I", "我现在在哪", query_scene),
        RouteCase("scene/status query", "current situation", "现在是什么情况", query_scene),
        RouteCase("scene/status query", "today status", "今天上午当前状态", query_scene),
        RouteCase("scene/status query", "current board", "看一下当前局面", query_scene),
        RouteCase("scene/status query", "nearby objects", "我身边有什么", query_scene),
        RouteCase("scene/status query", "turn info", "当前回合信息", query_scene),
        RouteCase("scene/status query", "urgent issues", "现在最紧急的事情是什么", query_loose),
        RouteCase("scene/status query", "pending todo", "当前有哪些待办", query_loose),
        RouteCase("scene/status query", "pending projects", "现在有哪些项目没处理", query_loose),
        RouteCase("scene/status query", "what should do", "我现在该干嘛", query_loose),
        RouteCase("inventory query", "stun bolt count", "琥珀麻箭还剩几支", query_entity),
        RouteCase("inventory query", "stun bolt direct", "查一下琥珀麻箭", query_entity),
        RouteCase("inventory query", "all arrows", "所有箭矢数量", query_entity),
        RouteCase("inventory query", "usable ammo", "我能用的弹药有哪些", query_entity),
        RouteCase("inventory query", "crossbow and ammo", "检查终极复合弩和所有箭矢数量", query_loose),
        RouteCase("inventory query", "powder arrows", "我还有多少火药箭", query_entity),
        RouteCase("inventory query", "toxic old bolts", "旧毒弩箭还有几支能用", query_entity),
        RouteCase("inventory query", "water spinach count", "空心菜还有多少株", query_entity),
        RouteCase("inventory query", "food stock", "还有多少能吃的", query_loose),
        RouteCase("inventory query", "kitchen food", "厨房存粮情况", query_loose),
        RouteCase("inventory query", "root mycelium count", "根源菌丝有几面", query_entity),
        RouteCase("inventory query", "salt count", "盐还剩多少", query_entity),
        RouteCase("inventory query", "fish trap count", "竹编鱼笼有几个", query_entity),
        RouteCase("mycelium query", "mycelium people total", "菌丝人总数是多少", query_entity),
        RouteCase("mycelium query", "mycelium population", "菌丝城人口", query_entity),
        RouteCase("mycelium query", "unit list", "菌丝单位名单", query_entity),
        RouteCase("mycelium query", "how many mycelium people", "现在有多少菌丝人", query_entity),
        RouteCase("mycelium query", "mushroom count", "目前菌丝蘑菇有几个", query_entity),
        RouteCase("mycelium query", "mycelium city units", "地下菌丝城现在有多少单位", query_entity),
        RouteCase("mycelium query", "unit split counts", "腐工蕈锐孢蕈思菌蕈各有几个", query_entity),
        RouteCase("mycelium query", "worker count", "腐工蕈数量", query_entity),
        RouteCase("mycelium query", "sharp spore count", "锐孢蕈数量", query_entity),
        RouteCase("mycelium query", "thinking fungus count", "思菌蕈数量", query_entity),
        RouteCase("mycelium query", "eve dispatch capacity", "夏娃现在能调度多少菌丝单位", query_entity),
        RouteCase("mycelium query", "capacity limit", "夏娃和菌丝城容量上限", query_entity),
        RouteCase("clock/project query", "drought clock", "春末干旱进度到几格了", query_entity),
        RouteCase("clock/project query", "base upkeep clock", "基地维护压力多少", query_entity),
        RouteCase("clock/project query", "water project", "十六畦浇水多久没做了", query_entity),
        RouteCase("clock/project query", "ashmoss trust", "灰藓族互信现在几格", query_entity),
        RouteCase("routine action", "patrol territory short", "巡查领地", routine),
        RouteCase("routine action", "patrol territory with subject", "我巡查领地", routine),
        RouteCase("routine action", "inspect territory", "巡视一下领地", routine),
        RouteCase("routine action", "routine patrol", "例行巡逻", routine),
        RouteCase("routine action", "wall patrol", "巡逻围墙", routine),
        RouteCase("routine action", "walk base", "在家里绕一圈检查农田和围墙", routine),
        RouteCase("routine action", "inspect defenses", "检查基地防线", routine),
        RouteCase("routine action", "check soil water", "检查农田水分", routine),
        RouteCase("routine action", "check traps", "检查陷阱", routine),
        RouteCase("routine action", "check fish trap no harvest", "检查鱼笼但不收", routine),
        RouteCase("routine action", "check t2 status", "检查T2状态", routine),
        RouteCase("routine action", "test pumpkin ability", "测试南瓜能力", routine),
        RouteCase("routine action", "check warehouse", "盘点仓库", routine),
        RouteCase("routine action", "count inventory action", "清点库存", routine),
        RouteCase("routine action", "water crops", "给十六畦浇水", routine),
        RouteCase("routine action", "mycelium irrigation", "让菌丝辅助灌溉十六畦", routine),
        RouteCase("routine action", "feed t2", "喂T2母猫和幼崽", routine),
        RouteCase("routine action", "sort dangerous goods", "整理危险品仓库", routine),
        RouteCase("routine action", "separate powder", "把火药和食物分开放", routine),
        RouteCase("routine action", "check tunnels", "检查菌丝通道", routine),
        RouteCase("social action", "ask eve status", "问夏娃菌丝城状态", social),
        RouteCase("social action", "discuss irrigation with eve", "和夏娃商量灌溉", social),
        RouteCase("social action", "eve report units", "让夏娃汇报菌丝单位", social),
        RouteCase("social action", "talk an trade", "找An聊交易", social),
        RouteCase("social action", "ask an sulfur", "让An帮忙采硫磺", social),
        RouteCase("social action", "practice slate", "跟小的练石板", social),
        RouteCase("social action", "call young to eat", "叫小的过来吃饭", social),
        RouteCase("social action", "ask pumpkin rest", "问南瓜要不要休息", social),
        RouteCase("social action", "say morning pumpkin", "给南瓜说早安", social),
        RouteCase("social action", "comfort t2", "安抚T2母猫", social),
        RouteCase("travel action", "go creek", "去L1小溪", travel),
        RouteCase("travel action", "go spring and look", "到溪源泉眼看看水", composite_or_travel),
        RouteCase("travel action", "descend mycelium city", "从菌丝屋下到地下菌丝城", travel),
        RouteCase("travel action", "go i room", "去I室看看T2", composite_or_travel),
        RouteCase("travel action", "go lake settlement", "去湖边聚落", travel),
        RouteCase("travel action", "tunnel l7", "沿隧道去L7泉眼", travel),
        RouteCase("travel action", "go home", "回家", travel),
        RouteCase("travel action", "go old hut", "去旧小屋", travel),
        RouteCase("travel action", "go d warehouse", "去D仓库", travel),
        RouteCase("travel action", "surface from underground", "上到地表", travel),
        RouteCase("travel action", "enter underground", "进地下", travel),
        RouteCase("gather action", "gather water spinach", "采空心菜", gather),
        RouteCase("gather action", "pick vegetables", "摘点菜", gather),
        RouteCase("gather action", "collect water spinach", "收一点空心菜", gather),
        RouteCase("gather action", "harvest fish trap", "收鱼笼", gather),
        RouteCase("gather action", "take fish from trap", "从鱼笼取鱼", gather),
        RouteCase("gather action", "travel gather fish trap", "去L1小溪收鱼笼", composite_or_travel),
        RouteCase("gather action", "gather sulfur", "采硫磺", gather),
        RouteCase("gather action", "fetch spring water", "去泉眼取水", composite_or_travel),
        RouteCase("gather action", "dig niter", "挖硝石", gather),
        RouteCase("gather action", "pick pine nuts", "捡松子", gather),
        RouteCase("gather action", "collect milk sap", "采见血封喉乳汁", gather),
        RouteCase("combat action", "shoot t2", "用终极复合弩射T2母猫", combat_clarify),
        RouteCase("combat action", "load and overwatch", "装填琥珀麻箭戒备", combat_clarify),
        RouteCase("combat action", "conditional shooting", "如果有东西靠近就射", combat_clarify),
        RouteCase("combat action", "guard with crossbow", "拿弩守夜", combat_clarify),
        RouteCase("combat action", "keep alert", "保持警戒", combat_clarify),
        RouteCase("combat action", "aim at entrance", "架弩瞄准入口", combat_clarify),
        RouteCase("combat action", "distance from t2", "对T2保持距离", combat_clarify),
        RouteCase("combat action", "shoot suspicious target", "用麻痹箭射可疑目标", combat_clarify),
        RouteCase("craft action", "calibrate powder arrow", "做火药箭引信校准", craft),
        RouteCase("craft action", "calibrate crossbow", "校准弩", craft),
        RouteCase("craft action", "make curewood shafts", "制作愈疮木箭杆", craft),
        RouteCase("craft action", "assemble thorn bolts", "装配渊刺藤箭", craft),
        RouteCase("craft action", "repair water channel", "修水渠", craft),
        RouteCase("craft action", "build channel", "造水渠", craft),
        RouteCase("craft action", "make trap", "做陷阱", craft),
        RouteCase("craft action", "repair wall", "修围墙", craft),
        RouteCase("craft action", "expand warehouse", "扩建仓库", craft),
        RouteCase("craft action", "expand mycelium side room", "扩建菌丝城侧室", craft),
        RouteCase("rest action", "rest afternoon", "休息到下午", rest),
        RouteCase("rest action", "sleep morning", "睡到明天早上", rest),
        RouteCase("rest action", "nap", "小睡一会儿", rest),
        RouteCase("rest action", "eat to recover", "吃点东西恢复", routine),
        RouteCase("rest action", "breakfast", "吃早饭", routine),
        RouteCase("rest action", "cook meal", "做饭", routine),
        RouteCase("rest action", "drink water", "喝水", routine),
        RouteCase("rest action", "rest hour", "休息一小时", rest),
    ]
    cases.extend(extra_action_route_cases())
    cases.extend(extra_query_route_cases())
    return cases


def action_route_cases() -> list[RouteCase]:
    return [case for case in route_cases() if any(item.mode == "action" for item in case.expected)]


def query_route_cases() -> list[RouteCase]:
    return [case for case in route_cases() if all(item.mode == "query" for item in case.expected)]


def extra_action_route_cases() -> list[RouteCase]:
    routine = (ExpectedRoute("action", "routine", True),)
    travel = (ExpectedRoute("action", "travel", True),)
    social = (ExpectedRoute("action", "social", True),)
    gather = (
        ExpectedRoute("action", "gather", True),
        ExpectedRoute("action", "gather", False),
    )
    combat = (
        ExpectedRoute("action", "combat", True),
        ExpectedRoute("action", "combat", False),
    )
    craft = (
        ExpectedRoute("action", "craft", True),
        ExpectedRoute("action", "craft", False),
    )
    rest = (ExpectedRoute("action", "rest", True),)
    explore = (
        ExpectedRoute("action", "explore", True),
        ExpectedRoute("action", "explore", False),
    )
    composite = (
        ExpectedRoute("action", "composite", False),
        ExpectedRoute("action", "travel", True),
        ExpectedRoute("action", "gather", False),
        ExpectedRoute("action", "explore", False),
    )
    return [
        RouteCase("routine action extended", "morning base sweep", "早上先把基地巡视一遍", routine),
        RouteCase("routine action extended", "check kitchen stores", "去厨房角整理一下存粮", routine),
        RouteCase("routine action extended", "inspect dangerous storage", "检查旧小屋危险品封存情况", routine),
        RouteCase("routine action extended", "check water containers", "检查竹水筒和储水是否漏水", routine),
        RouteCase("routine action extended", "check fermentation jar", "看看浆果醋发酵和封口", routine),
        RouteCase("routine action extended", "clean workbench", "清理工坊台面和工具", routine),
        RouteCase("routine action extended", "maintain crossbow", "保养终极复合弩", routine),
        RouteCase("routine action extended", "sort ammo box", "整理箭矢盒，把不同箭分开", routine),
        RouteCase("routine action extended", "inspect landmine", "检查M2地雷绊线有没有松", routine),
        RouteCase("routine action extended", "check field water", "确认十六畦今天需不需要浇水", routine),
        RouteCase("routine action extended", "feed cats carefully", "给T2母猫和幼崽安排一点吃的", routine),
        RouteCase("routine action extended", "check pumpkin mood", "看看南瓜今天精神状态", routine),
        RouteCase("travel action extended", "walk to clearing", "走到围栏空地", travel),
        RouteCase("travel action extended", "enter old hut", "进旧小屋材料仓", travel),
        RouteCase("travel action extended", "go to h room", "去H室找An", travel),
        RouteCase("travel action extended", "go to d warehouse", "下到D仓库", travel),
        RouteCase("travel action extended", "go to i room", "去I室隔离区", travel),
        RouteCase("travel action extended", "go to field west", "去西区扩田边看看", travel),
        RouteCase("travel action extended", "return mycelium house", "回六边形菌丝复合屋", travel),
        RouteCase("travel action extended", "go lake edge", "往湖边方向走", travel),
        RouteCase("travel action extended", "go tunnel entrance", "走到菌丝通道入口", travel),
        RouteCase("travel action extended", "go l13 pool", "去L13石槽深潭", travel),
        RouteCase("gather action extended", "cut chives", "割半把韭菜", gather),
        RouteCase("gather action extended", "harvest amaranth", "摘几片苋菜大叶", gather),
        RouteCase("gather action extended", "pick red lettuce", "掰三片红叶生菜", gather),
        RouteCase("gather action extended", "dig ginger", "挖一块生姜", gather),
        RouteCase("gather action extended", "collect berries", "摘半竹杯红浆果", gather),
        RouteCase("gather action extended", "collect resin", "刮一点硬化残胶", gather),
        RouteCase("gather action extended", "collect acid resin", "取一点酸残胶样本", gather),
        RouteCase("gather action extended", "collect thunder moss", "采一片雷苔", gather),
        RouteCase("gather action extended", "collect frost leaf", "采霜叶样本", gather),
        RouteCase("gather action extended", "collect honey mushroom", "采蜂巢菇样本", gather),
        RouteCase("social action extended", "ask an old home", "问An关于L9旧居的事", social),
        RouteCase("social action extended", "ask young slate", "请小的继续教我石板符号", social),
        RouteCase("social action extended", "ask eve irrigation", "让夏娃说明今天灌溉安排", social),
        RouteCase("social action extended", "ask pumpkin ability", "问南瓜它的能力边界", social),
        RouteCase("social action extended", "comfort pumpkin", "安抚南瓜，告诉它今天先休息", social),
        RouteCase("social action extended", "trade with an", "和An谈一下交换硫磺样本", social),
        RouteCase("combat action extended", "shoot warning bolt", "用终极复合弩朝可疑目标射一支警告箭", combat),
        RouteCase("combat action extended", "load frost bolt", "装填霜白冻箭准备压制", combat),
        RouteCase("combat action extended", "ready toxic bolt", "把紫黑毒箭搭上弩保持戒备", combat),
        RouteCase("combat action extended", "guard cave mouth", "在洞口架弩警戒", combat),
        RouteCase("combat action extended", "disarm landmine combat", "如果目标冲门就引爆地雷", combat),
        RouteCase("craft action extended", "make simple rope", "用麻纤维编一段绳子", craft),
        RouteCase("craft action extended", "repair bamboo cup", "修补竹杯裂缝", craft),
        RouteCase("craft action extended", "make herb poultice", "用止血草做外敷药糊", craft),
        RouteCase("craft action extended", "mix powder sample", "试配一小份火药比例", craft),
        RouteCase("craft action extended", "seal resin coating", "用残胶做防水涂层测试", craft),
        RouteCase("craft action extended", "make fish trap repair", "修补竹编鱼笼", craft),
        RouteCase("rest action extended", "rest until noon", "休息到中午", rest),
        RouteCase("rest action extended", "sleep tonight", "今晚早点睡", rest),
        RouteCase("rest action extended", "sit and recover", "坐下歇十分钟恢复体力", rest),
        RouteCase("rest action extended", "long rest", "找安全处长休息", rest),
        RouteCase("explore action extended", "investigate smoke", "调查远处烟柱", explore),
        RouteCase("explore action extended", "search footprints", "侦查围墙外的脚印", explore),
        RouteCase("explore action extended", "inspect strange shard", "检查陌生陶片的来源", explore),
        RouteCase("explore action extended", "scout night whistle", "搜索夜里哨声来源", explore),
        RouteCase("composite action extended", "go creek collect water", "去L1小溪打一筒水再回来", composite),
        RouteCase("composite action extended", "go old hut get powder", "去旧小屋取黑火药并回工坊", composite),
        RouteCase("composite action extended", "go field harvest then cook", "去田里摘菜然后回来做饭", composite),
    ]


def extra_query_route_cases() -> list[RouteCase]:
    query_scene = (ExpectedRoute("query", "scene", True),)
    query_entity = (ExpectedRoute("query", "entity", True),)
    query_loose = (
        ExpectedRoute("query", "entity", True),
        ExpectedRoute("query", "scene", True),
    )
    return [
        RouteCase("scene/status query extended", "where exact location", "我现在具体在什么地点", query_scene),
        RouteCase("scene/status query extended", "time and weather", "现在时间和天气怎么样", query_scene),
        RouteCase("scene/status query extended", "current safety", "当前周围安全吗", query_scene),
        RouteCase("scene/status query extended", "visible exits", "附近能去哪些地方", query_scene),
        RouteCase("scene/status query extended", "current companions", "我身边现在有谁", query_scene),
        RouteCase("scene/status query extended", "current risks", "当前有哪些风险", query_loose),
        RouteCase("scene/status query extended", "today priorities", "今天优先事项是什么", query_loose),
        RouteCase("scene/status query extended", "pending confirmations", "现在有哪些需要确认的事", query_loose),
        RouteCase("scene/status query extended", "last saved turn", "最近一次保存到哪个回合", query_scene),
        RouteCase("scene/status query extended", "current resources nearby", "当前地点附近有什么资源", query_scene),
        RouteCase("inventory query extended", "water amount", "竹水筒里还有多少水", query_entity),
        RouteCase("inventory query extended", "salt amount", "盐现在还够不够", query_entity),
        RouteCase("inventory query extended", "berries amount", "红浆果还剩多少", query_entity),
        RouteCase("inventory query extended", "vinegar amount", "浆果醋还有多少", query_entity),
        RouteCase("inventory query extended", "oil amount", "松子油库存", query_entity),
        RouteCase("inventory query extended", "resin amount", "普通残胶和硬化残胶各有多少", query_entity),
        RouteCase("inventory query extended", "acid resin amount", "酸残胶还剩多少ml", query_entity),
        RouteCase("inventory query extended", "niter sulfur stock", "硝石和硫磺库存", query_entity),
        RouteCase("inventory query extended", "black powder stock", "黑火药还有多少", query_entity),
        RouteCase("inventory query extended", "landmine stock", "地雷现在有几枚", query_entity),
        RouteCase("ammo query extended", "all special bolts", "特殊箭矢分别还剩几支", query_entity),
        RouteCase("ammo query extended", "toxic bolt count", "紫黑毒箭数量", query_entity),
        RouteCase("ammo query extended", "frost bolt count", "霜白冻箭数量", query_entity),
        RouteCase("ammo query extended", "burst bolt count", "赤红炸箭数量", query_entity),
        RouteCase("ammo query extended", "plain bolt count", "旧普通箭数量", query_entity),
        RouteCase("equipment query extended", "crossbow detail", "终极复合弩参数", query_entity),
        RouteCase("equipment query extended", "armor detail", "我身上的护甲有哪些", query_entity),
        RouteCase("equipment query extended", "backpack detail", "竹藤背包情况", query_entity),
        RouteCase("character query extended", "pumpkin status", "南瓜现在状态", query_entity),
        RouteCase("character query extended", "an status", "An现在在哪里", query_entity),
        RouteCase("character query extended", "young status", "小的现在情况", query_entity),
        RouteCase("character query extended", "eve status", "夏娃现在状态", query_entity),
        RouteCase("character query extended", "t2 status", "T2母猫情况", query_entity),
        RouteCase("mycelium query extended", "mycelium core", "母孢子树现在怎么样", query_entity),
        RouteCase("mycelium query extended", "mycelium city rooms", "菌丝城有哪些房间", query_entity),
        RouteCase("mycelium query extended", "mycelium irrigation capacity", "菌丝能帮忙灌溉到什么程度", query_entity),
        RouteCase("field query extended", "field six status", "畦6空心菜状态", query_entity),
        RouteCase("field query extended", "field water pressure", "十六畦浇水压力", query_entity),
        RouteCase("field query extended", "new fields status", "新增畦17到27状态", query_entity),
        RouteCase("field query extended", "harvestable crops", "哪些作物现在能收", query_entity),
        RouteCase("clock query extended", "forest attention clock", "森林注意进度", query_entity),
        RouteCase("clock query extended", "civilization rumor clock", "文明传闻钟多少", query_entity),
        RouteCase("clock query extended", "lake suspicion clock", "湖边聚落警惕几格", query_entity),
        RouteCase("clock query extended", "fatigue clock", "疲劳压力现在多少", query_entity),
        RouteCase("clock query extended", "soil clock", "土壤肥力消耗多少", query_entity),
        RouteCase("location query extended", "old hut status", "旧小屋现在有什么", query_entity),
        RouteCase("location query extended", "l1 creek status", "L1小溪情况", query_entity),
        RouteCase("location query extended", "d warehouse status", "D仓库里有什么", query_entity),
        RouteCase("location query extended", "h room status", "H室情况", query_entity),
        RouteCase("location query extended", "i room status", "I室隔离区情况", query_entity),
        RouteCase("project query extended", "crafting breakthrough", "工艺突破进度", query_entity),
        RouteCase("project query extended", "base maintenance", "基地维护压力详情", query_entity),
        RouteCase("project query extended", "ashmoss trust detail", "灰藓族互信详情", query_entity),
    ]


def query_cases() -> list[QueryCase]:
    query_entity = (ExpectedRoute("query", "entity", True),)
    query_scene = (ExpectedRoute("query", "scene", True),)
    query_loose = (
        ExpectedRoute("query", "entity", True),
        ExpectedRoute("query", "scene", True),
    )
    cases = [
        QueryCase(
            "query output",
            "mycelium people total",
            "菌丝人总数是多少",
            "entity",
            query_entity,
            required_any=("幽壤菌裔", "夏娃", "菌丝"),
            required_all=("数量",),
            notes="用户点名失败场景：应该能命中菌丝族群/单位统计，而不是未找到实体。",
        ),
        QueryCase(
            "query output",
            "mycelium species direct",
            "幽壤菌裔",
            "entity",
            query_entity,
            required_any=("幽壤菌裔",),
        ),
        QueryCase(
            "query output",
            "eve direct",
            "夏娃",
            "entity",
            query_entity,
            required_any=("夏娃",),
        ),
        QueryCase(
            "query output",
            "mycelium city direct",
            "地下菌丝城",
            "entity",
            query_entity,
            required_any=("地下菌丝城",),
        ),
        QueryCase(
            "query output",
            "mycelium units count",
            "地下菌丝城现在有多少单位",
            "entity",
            query_entity,
            required_any=("幽壤菌裔", "夏娃", "菌丝"),
            required_all=("数量",),
        ),
        QueryCase(
            "query output",
            "fungus worker split",
            "腐工蕈锐孢蕈思菌蕈各有几个",
            "entity",
            query_entity,
            required_any=("腐工蕈", "锐孢蕈", "思菌蕈", "幽壤菌裔"),
            required_all=("数量",),
        ),
        QueryCase(
            "query output",
            "stun bolts count",
            "琥珀麻箭还剩几支",
            "entity",
            query_entity,
            required_any=("琥珀麻箭",),
            required_all=("12支",),
        ),
        QueryCase(
            "query output",
            "stun bolts direct",
            "琥珀麻箭",
            "entity",
            query_entity,
            required_any=("琥珀麻箭",),
            required_all=("12支",),
        ),
        QueryCase(
            "query output",
            "all arrows count",
            "所有箭矢数量",
            "entity",
            query_entity,
            required_any=("琥珀麻箭", "火药箭", "紫黑毒箭", "霜白冻箭"),
            required_all=("数量",),
        ),
        QueryCase(
            "query output",
            "water spinach count",
            "空心菜还有多少株",
            "entity",
            query_entity,
            required_any=("空心菜",),
            required_all=("13株",),
        ),
        QueryCase(
            "query output",
            "water spinach direct",
            "空心菜",
            "entity",
            query_entity,
            required_any=("空心菜",),
            required_all=("13株",),
        ),
        QueryCase(
            "query output",
            "pending projects",
            "当前有哪些待办",
            "scene",
            query_scene,
            required_any=("十六畦浇水维护", "T2观察与喂养前置", "灰藓族分工贸易"),
        ),
        QueryCase(
            "query output",
            "urgent issues",
            "现在最紧急的事情是什么",
            "scene",
            query_loose,
            required_any=("十六畦", "干旱", "维护", "待处理"),
        ),
    ]
    cases.extend(extra_query_output_cases())
    return cases


def extra_query_output_cases() -> list[QueryCase]:
    query_entity = (ExpectedRoute("query", "entity", True),)
    query_scene = (ExpectedRoute("query", "scene", True),)
    query_loose = (
        ExpectedRoute("query", "entity", True),
        ExpectedRoute("query", "scene", True),
    )
    return [
        QueryCase("query output extended", "current location scene", "看一下周围", "scene", query_scene, required_any=("地点", "当前", "六边形菌丝复合屋")),
        QueryCase("query output extended", "current situation scene", "现在是什么情况", "scene", query_scene, required_any=("当前", "地点", "待处理")),
        QueryCase("query output extended", "urgent things scene", "当前最紧急的事情", "scene", query_loose, required_any=("十六畦", "维护", "干旱")),
        QueryCase("query output extended", "water bottle direct", "竹水筒", "entity", query_entity, required_any=("竹水筒",), required_all=("4L",)),
        QueryCase("query output extended", "salt direct", "盐", "entity", query_entity, required_any=("盐",), required_all=("0.5勺",)),
        QueryCase("query output extended", "red berries direct", "红浆果", "entity", query_entity, required_any=("红浆果",), required_all=("0.5竹杯",)),
        QueryCase("query output extended", "berry vinegar direct", "浆果醋", "entity", query_entity, required_any=("浆果醋",), required_all=("1竹杯",)),
        QueryCase("query output extended", "pine nut oil direct", "松子油", "entity", query_entity, required_any=("松子油",), required_all=("3竹杯",)),
        QueryCase("query output extended", "ordinary resin direct", "普通残胶", "entity", query_entity, required_any=("普通残胶",), required_all=("0.5竹杯",)),
        QueryCase("query output extended", "hardened resin direct", "硬化残胶", "entity", query_entity, required_any=("硬化残胶",), required_all=("80ml",)),
        QueryCase("query output extended", "acid resin direct", "酸残胶", "entity", query_entity, required_any=("酸残胶",), required_all=("30ml",)),
        QueryCase("query output extended", "niter direct", "硝石针晶", "entity", query_entity, required_any=("硝石针晶",), required_all=("0.5杯",)),
        QueryCase("query output extended", "sulfur shards direct", "硫磺碎晶", "entity", query_entity, required_any=("硫磺碎晶",), required_all=("1把",)),
        QueryCase("query output extended", "black powder direct", "黑火药", "entity", query_entity, required_any=("黑火药",), required_all=("0.5竹杯",)),
        QueryCase("query output extended", "water spinach stock", "空心菜库存", "entity", query_entity, required_any=("空心菜",), required_all=("13株",)),
        QueryCase("query output extended", "amaranth direct", "苋菜大叶", "entity", query_entity, required_any=("苋菜大叶",), required_all=("8片",)),
        QueryCase("query output extended", "lettuce direct", "红叶生菜", "entity", query_entity, required_any=("红叶生菜",), required_all=("3片",)),
        QueryCase("query output extended", "wild onion direct", "野葱", "entity", query_entity, required_any=("野葱",), required_all=("3根",)),
        QueryCase("query output extended", "garlic leaf direct", "蒜叶", "entity", query_entity, required_any=("蒜叶",), required_all=("2片",)),
        QueryCase("query output extended", "ginger direct", "生姜", "entity", query_entity, required_any=("生姜",), required_all=("3块",)),
        QueryCase("query output extended", "stun bolts direct extra", "琥珀麻箭数量", "entity", query_entity, required_any=("琥珀麻箭",), required_all=("12支",)),
        QueryCase("query output extended", "powder arrows direct extra", "火药箭数量", "entity", query_entity, required_any=("火药箭",), required_all=("5支",)),
        QueryCase("query output extended", "toxic bolts direct", "紫黑毒箭", "entity", query_entity, required_any=("紫黑毒箭",), required_all=("20支",)),
        QueryCase("query output extended", "frost bolts direct", "霜白冻箭", "entity", query_entity, required_any=("霜白冻箭",), required_all=("20支",)),
        QueryCase("query output extended", "burst bolts direct", "赤红炸箭", "entity", query_entity, required_any=("赤红炸箭",), required_all=("20支",)),
        QueryCase("query output extended", "plain bolts direct", "旧普通箭", "entity", query_entity, required_any=("旧普通箭",), required_all=("3支",)),
        QueryCase("query output extended", "poison bolts direct", "旧毒弩箭", "entity", query_entity, required_any=("旧毒弩箭",), required_all=("9支",)),
        QueryCase("query output extended", "bamboo arrows direct", "竹箭", "entity", query_entity, required_any=("竹箭",), required_all=("15支",)),
        QueryCase("query output extended", "ultimate crossbow direct", "终极复合弩", "entity", query_entity, required_any=("终极复合弩", "140kg")),
        QueryCase("query output extended", "backpack direct", "竹藤背包", "entity", query_entity, required_any=("竹藤背包",)),
        QueryCase("query output extended", "landmine direct", "M2地雷", "entity", query_entity, required_any=("M2", "地雷"), required_all=("1枚",)),
        QueryCase("query output extended", "fish trap direct", "竹编鱼笼", "entity", query_entity, required_any=("竹编鱼笼",), required_all=("2个",)),
        QueryCase("query output extended", "pumpkin direct", "南瓜", "entity", query_entity, required_any=("南瓜",)),
        QueryCase("query output extended", "an direct extra", "An现在在哪里", "entity", query_entity, required_any=("An", "H室")),
        QueryCase("query output extended", "young direct", "小的", "entity", query_entity, required_any=("小的", "灰藓")),
        QueryCase("query output extended", "eve direct extra", "夏娃现在状态", "entity", query_entity, required_any=("夏娃", "菌丝")),
        QueryCase("query output extended", "ashmoss trust direct", "灰藓族互信", "entity", query_entity, required_any=("灰藓族互信",), required_all=("互信",)),
        QueryCase("query output extended", "drought clock direct", "春末干旱", "entity", query_entity, required_any=("春末干旱",)),
        QueryCase("query output extended", "base upkeep direct", "基地维护压力", "entity", query_entity, required_any=("基地维护压力",)),
        QueryCase("query output extended", "forest attention direct", "森林注意", "entity", query_entity, required_any=("森林注意",)),
        QueryCase("query output extended", "civilization rumor direct", "文明传闻", "entity", query_entity, required_any=("文明传闻",)),
        QueryCase("query output extended", "soil depletion direct", "土壤肥力消耗", "entity", query_entity, required_any=("土壤肥力消耗",)),
        QueryCase("query output extended", "field six direct", "畦6 空心菜", "entity", query_entity, required_any=("畦6", "空心菜")),
        QueryCase("query output extended", "field ten direct", "畦10 盐角草", "entity", query_entity, required_any=("畦10", "盐角草")),
        QueryCase("query output extended", "field sixteen direct", "畦16 储存南瓜", "entity", query_entity, required_any=("畦16", "储存南瓜")),
        QueryCase("query output extended", "home house location", "六边形菌丝复合屋", "entity", query_entity, required_any=("六边形菌丝复合屋",)),
        QueryCase("query output extended", "old hut location", "旧小屋", "entity", query_entity, required_any=("旧小屋",)),
        QueryCase("query output extended", "l1 creek location", "L1小溪", "entity", query_entity, required_any=("L1", "小溪")),
        QueryCase("query output extended", "d warehouse location", "D仓库", "entity", query_entity, required_any=("D仓库",)),
        QueryCase("query output extended", "h room location", "H室", "entity", query_entity, required_any=("H室",)),
        QueryCase("query output extended", "i room location", "I室", "entity", query_entity, required_any=("I室",)),
        QueryCase("query output extended", "root mycelium direct", "根源菌丝", "entity", query_entity, required_any=("根源菌丝",), required_all=("1面",)),
        QueryCase("query output extended", "mother spore tree direct", "母孢子树", "entity", query_entity, required_any=("母孢子树", "夏娃")),
    ]


def run_route_case(runtime: GMRuntime, case: RouteCase) -> ProbeResult:
    try:
        start = runtime.start_turn(case.text).to_dict()
        preview = runtime.preview_from_text(case.text).to_dict()
    except Exception as exc:  # pragma: no cover - report path
        return ProbeResult(
            area=case.area,
            name=case.name,
            text=case.text,
            status="ISSUE",
            observed=f"{type(exc).__name__}: {exc}",
            expected=format_expected(case.expected),
            issue="exception",
        )
    observed_route = (str(start["mode"]), str(start["submode"]), bool(start["can_proceed"]))
    ok = route_matches(start, case.expected)
    details = route_details(start, preview)
    if case.notes:
        details.append(f"note={case.notes}")
    issue = "" if ok else classify_route_issue(start, case.expected)
    if not ok:
        details.extend(explicit_override_details(runtime, case.text, case.expected[0]))
    return ProbeResult(
        area=case.area,
        name=case.name,
        text=case.text,
        status="PASS" if ok else "ISSUE",
        observed=f"{observed_route[0]}:{observed_route[1]} can_proceed={observed_route[2]}",
        expected=format_expected(case.expected),
        details=details,
        issue=issue,
    )


def run_query_case(runtime: GMRuntime, case: QueryCase) -> ProbeResult:
    start = runtime.start_turn(case.text).to_dict()
    route_ok = route_matches(start, case.expected_route)
    query_result = runtime.query(case.query_kind, case.text).to_dict()
    text = str(query_result.get("text") or "")
    any_ok = not case.required_any or any(term in text for term in case.required_any)
    all_ok = all(term in text for term in case.required_all)
    ok = route_ok and any_ok and all_ok and "未找到实体" not in text
    missing_terms = []
    if not any_ok:
        missing_terms.append(f"missing any of {list(case.required_any)}")
    if not all_ok:
        missing_terms.append(f"missing required {list(case.required_all)}")
    if "未找到实体" in text:
        missing_terms.append("query returned 未找到实体")
    details = [
        f"start_turn={start['mode']}:{start['submode']} can_proceed={start['can_proceed']}",
        f"query_kind={case.query_kind}",
        f"query_excerpt={one_line(text[:500])}",
    ]
    if case.notes:
        details.append(f"note={case.notes}")
    if missing_terms:
        details.append("; ".join(missing_terms))
    if not route_ok:
        details.extend(explicit_override_details(runtime, case.text, case.expected_route[0]))
    return ProbeResult(
        area=case.area,
        name=case.name,
        text=case.text,
        status="PASS" if ok else "ISSUE",
        observed=("route ok; query useful" if ok else "query/route gap"),
        expected=f"route {format_expected(case.expected_route)}; useful query output",
        details=details,
        issue="" if ok else classify_query_issue(route_ok, text, missing_terms),
    )


def route_matches(start: dict[str, Any], expected: tuple[ExpectedRoute, ...]) -> bool:
    mode = str(start["mode"])
    submode = str(start["submode"])
    can_proceed = bool(start["can_proceed"])
    for item in expected:
        if mode != item.mode or submode != item.submode:
            continue
        if item.can_proceed is not None and can_proceed != item.can_proceed:
            continue
        return True
    return False


def format_expected(expected: tuple[ExpectedRoute, ...]) -> str:
    parts = []
    for item in expected:
        suffix = "" if item.can_proceed is None else f" can_proceed={item.can_proceed}"
        parts.append(f"{item.mode}:{item.submode}{suffix}")
    return " or ".join(parts)


def route_details(start: dict[str, Any], preview: dict[str, Any]) -> list[str]:
    intent = start.get("intent") if isinstance(start.get("intent"), dict) else {}
    return [
        f"missing_required={start.get('missing_required')}",
        f"needs_user_confirmation={start.get('needs_user_confirmation')}",
        f"intent_kind={intent.get('kind')}",
        f"intent_action={intent.get('action')}",
        f"intent_status={intent.get('status')}",
        f"intent_options={intent.get('options')}",
        f"preview={preview.get('action')} status={preview.get('status')} ready={preview.get('ready_to_save')}",
        f"player_message={one_line(str(preview.get('player_message') or ''))}",
    ]


def explicit_override_details(runtime: GMRuntime, text: str, expected: ExpectedRoute) -> list[str]:
    details = []
    try:
        forced = runtime.start_turn(text, mode=expected.mode, submode=expected.submode).to_dict()
        details.append(
            "explicit_start_turn="
            f"{forced['mode']}:{forced['submode']} can_proceed={forced['can_proceed']} "
            f"missing={forced.get('missing_required')}"
        )
    except Exception as exc:  # pragma: no cover - report path
        details.append(f"explicit_start_turn_error={type(exc).__name__}: {exc}")
    try:
        forced_preview = runtime.preview_from_text(text, mode=expected.mode, submode=expected.submode).to_dict()
        details.append(
            "explicit_preview="
            f"{forced_preview.get('action')} status={forced_preview.get('status')} "
            f"ready={forced_preview.get('ready_to_save')}"
        )
    except Exception as exc:  # pragma: no cover - report path
        details.append(f"explicit_preview_error={type(exc).__name__}: {exc}")
    return details


def classify_route_issue(start: dict[str, Any], expected: tuple[ExpectedRoute, ...]) -> str:
    mode = str(start["mode"])
    submode = str(start["submode"])
    for item in expected:
        if mode == item.mode and submode == item.submode:
            return "right_mode_but_wrong_proceed_state"
    if mode == "query" and any(item.mode == "action" for item in expected):
        return "action_misread_as_query"
    if mode == "action" and any(item.mode == "query" for item in expected):
        return "query_misread_as_action"
    return "wrong_action_or_query_kind"


def classify_query_issue(route_ok: bool, query_text: str, missing_terms: list[str]) -> str:
    if "未找到实体" in query_text:
        return "query_entity_not_found"
    if not route_ok:
        return "query_route_gap"
    if missing_terms:
        return "query_output_missing_expected_fact"
    return "query_unknown_gap"


def one_line(text: str) -> str:
    return " ".join(text.split())


def render_report(results: list[ProbeResult], *, title: str, focus: str) -> str:
    pass_count = sum(1 for item in results if item.status == "PASS")
    issue_count = len(results) - pass_count
    issue_by_type: dict[str, int] = {}
    issue_by_area: dict[str, int] = {}
    for item in results:
        if item.status == "PASS":
            continue
        issue_by_type[item.issue or "unspecified"] = issue_by_type.get(item.issue or "unspecified", 0) + 1
        issue_by_area[item.area] = issue_by_area.get(item.area, 0) + 1
    lines = [
        f"# {title}",
        "",
        "Scope: temporary copies of the current `isekai-farm` save; the real save is not modified.",
        f"Focus: {focus}",
        "Policy: this report records recognition/query issues only. No engine behavior is changed by this probe.",
        "",
        f"Summary: PASS={pass_count} ISSUE={issue_count} TOTAL={len(results)}",
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
    issues = [item for item in results if item.status != "PASS"]
    if not issues:
        lines.append("No issues found.")
    else:
        lines.extend(["| Area | Case | Text | Observed | Expected | Issue |", "|---|---|---|---|---|---|"])
        for item in issues:
            lines.append(
                f"| {item.area} | {item.name} | `{item.text}` | {item.observed} | "
                f"{item.expected} | `{item.issue}` |"
            )
    lines.extend(["", "## Full Matrix", "", "| Status | Area | Case | Text | Observed | Expected |", "|---|---|---|---|---|---|"])
    for item in results:
        lines.append(
            f"| {item.status} | {item.area} | {item.name} | `{item.text}` | "
            f"{item.observed} | {item.expected} |"
        )
    lines.extend(["", "## Details", ""])
    for item in results:
        lines.extend(
            [
                f"### {item.status} · {item.area} · {item.name}",
                "",
                f"- Text: `{item.text}`",
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


if __name__ == "__main__":
    raise SystemExit(main())
