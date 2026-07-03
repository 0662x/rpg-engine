# AI GM 引擎模块化改造设计书

文档状态：**HISTORICAL：既有模块化改造记录**  
基准说明：[`DOCUMENTATION_BASELINE.md`](DOCUMENTATION_BASELINE.md)  

> 本文件保留既有模块化改造的设计与实现记录。当前 V1 产品边界、主路径、剧本包、存档包、CLI、MCP 和发布要求，以 [`kernel-requirements.md`](../../../specs/kernel-requirements.md) 及 [`DOCUMENTATION_BASELINE.md`](DOCUMENTATION_BASELINE.md) 为准。本文后半部的历史阶段计划不得覆盖 V1 实施顺序。
>
> 当前实现状态以 [`DOCUMENTATION_BASELINE.md`](DOCUMENTATION_BASELINE.md) 和 [`game-engine.md`](../../../architecture/game-engine.md) 为准。最新基线已包含 GMRuntime、V1 CLI、Campaign/Save Package Spec、官方最小示例、MCP Adapter 和发布整理；测试数字以基准文档为准。

## 0. 当前实现功能速览

截至 2026-06-30，当前引擎可以按下面这几层理解：

1. **存档内核**：SQLite 是权威事实源；支持结构化回合保存、内容维护 delta、`expected_turn_id` 并发保护、`command_id` 幂等、自动备份、schema migration、`check` 一致性检查。
2. **内容系统**：Content Type Registry 已管理 `entity`、`rule`、`clock`、`route`、`world_setting`；写入前会做 record/reference preflight、未知字段拒绝和 visibility 边界检查。
3. **展示与查询**：Card Registry、`query entity`、`query scene`、`render-current`、`render-cards`、FTS/search、player/gm/maintenance 视角隔离都已可用。
4. **上下文与行动**：Context pipeline 已支持预算裁剪、实体/别名解析、world setting 按需召回、长期记忆和审计；Action Resolver Registry 已接管 `travel/rest/gather/craft/social/combat/explore` 的 preview、turn assistant、request/resolve/delta 合约。
5. **投影与恢复**：JSONL outbox、projection state/status/repair 已启用；`events_jsonl`、`search`、`snapshots`、`cards`、`memory`、`reports`、`package_lock` 均可检测和修复，其中 package apply 已有 FTS dirty entity 增量切片。
6. **剧本包生命周期**：package validate/build/test/reconcile/install/diff/upgrade 已可用；支持字段所有权 dry-run、legacy adoption 门禁、新库初始化、package-lock adopt/repair、真实 create/update apply、自动备份、受限显式 migration、同版本 checksum 阻断和 migration checksum 追踪。
7. **存档搬运与导入**：`save export/import` 可打包恢复核心文件；importer registry 已接管旧 `isekai_farm_v1` 导入器。
8. **AI 安全门禁**：`proposal validate` 已能把 TurnProposal 校验为 ApprovedOutcome，检查 action resolver 合约、delta schema 和回复 claims；旧 response/delta 路径仍保留兼容。
9. **扩展门禁**：plugin manifest discovery/validate 已可用，只做版本和 capability 校验，不动态加载第三方代码。
10. **运行态世界类型切片**：`faction_state` 已作为最小 runtime entity 类型接入 delta schema、card/query 和 memory 摘要。

还没有完成的主要边界也很明确：动态插件代码加载、完整 definition/runtime 拆分、复杂脚本 migration、package archive 直接安装、cards/snapshot/memory 全量增量化、10k/100k 规模压测，以及 AI Proposal 成为默认保存路径。

## 1. 背景

当前 `rpg-engine` 已经具备一个可工作的 AI GM 存档引擎：

- `entities` 统一保存 ID、类型、名称、摘要、别名、可见性和自由 JSON 细节。
- `rules` 保存硬规则。
- `clocks` 保存世界推进钟，例如 `clock:drought-spring`、`clock:forest-attention`。
- `locations`、`items`、`characters`、`crop_plots` 等专表保存高频结构化状态。
- `palettes` 保存“可能出现但尚未成为事实”的素材候选。
- `turns`、`events`、`meta` 保存回合、事件和当前状态。
- `context_builder` 根据玩家输入组装有限上下文。
- `content/deltas` 支持后续内容维护。

这套设计对当前异世界农家游戏已经够用，但如果目标是把它发展成长期可扩展、维护性高、可复用的 AI GM 引擎，当前架构存在一个核心问题：

> 内容类型是手写分散支持的。新增一个一等内容类型时，需要同时修改加载、保存、校验、渲染、卡片、上下文、CLI 和测试。

本设计书提出一个渐进式改造方案：引入 **Content Type Registry**，让内容类型通过注册模块声明自己的加载、校验、保存、渲染和上下文召回能力。改造不推翻现有数据库事实模型，而是在现有 `entities + domain tables + events + context` 基础上降低耦合。

## 2. 目标

### 2.1 产品目标

- 支持多个不同题材的 AI GM 游戏包。
- 允许游戏包扩展新的内容类型，例如 `world_setting`、`quest`、`faction_state`、`calendar`、`weather_model`、`lore_thread`。
- 让世界观设定、动态压力、事实实体、候选素材分层清晰。
- 控制上下文体积，避免把全部设定无脑塞给 GM。
- 让扩展内容可验证、可渲染、可查询、可回滚、可测试。

### 2.2 工程目标

- 保持当前 campaign 和存档向后兼容。
- 不一次性重写全部模块。
- 保留 SQLite 作为事实存储。
- 保留 `entities` 作为统一索引层。
- 把硬编码内容类型改为可注册内容类型。
- 把 `context_builder.py` 从“理解所有领域”改为“调度多个 context collector”。
- 新增 `world_setting` 作为第一个验证注册架构价值的内容类型。

## 3. 非目标

- 不在本阶段替换 SQLite。
- 不在本阶段实现远程插件市场。
- 不让 LLM 自由改数据库 schema。
- 不把 palette 候选自动升级为事实。
- 不让所有 Markdown 文档自动进入上下文。
- 不重写当前保存协议和回合协议。

## 4. 当前架构评估

### 4.1 已有优点

| 设计点 | 价值 |
|--------|------|
| `entities` 统一索引 | 所有内容有稳定 ID、名称、摘要、别名、FTS 搜索入口 |
| 专表保存高频结构 | `clocks`、`rules`、`locations` 等可被精确查询和校验 |
| `palettes` 区分候选和事实 | 防止 AI GM 把未发现内容当成当前事实 |
| `content/deltas` | 支持内容维护和存档演进 |
| `clocks.yaml` | 动态世界压力独立，不和静态设定混在一起 |
| `context_builder` 预算裁剪 | 适合 AI GM 的有限上下文运行方式 |

### 4.2 主要耦合点

| 模块 | 当前问题 |
|------|----------|
| `db.seed_content()` | 手写加载 `entities/rules/clocks/routes` |
| `db.upsert_entity()` | 子记录类型内嵌在一个函数里，新增专表需要改核心函数 |
| `content_delta.apply_content_delta()` | 只认识 `upsert_entities/upsert_routes/upsert_rules` |
| `delta_schema.py` | 顶层字段和实体类型白名单硬编码 |
| `validators.py` | 校验逻辑集中在一个函数里 |
| `render.py` / `cards.py` | 每种类型渲染硬编码 |
| `context_builder.py` | clock、route、palette、entity 召回逻辑集中，扩展新类型成本高 |
| `cli.py` | 命令和内容工厂选择硬编码 |

### 4.3 `clocks.yaml` 的定位

`clocks.yaml` 当前设计是合理的。它应继续只表达动态进度：

- 什么会推进。
- 什么会降低。
- 满格发生什么。
- 玩家是否知道。

它不应该承载天气百科、种族百科、力量体系全文。大世界设定应成为单独内容类型，和 clocks 通过 `linked_clocks` 关联。

## 5. 目标架构

```text
rpg-engine
  Campaign
    |
    v
  Content Type Registry
    |-- entity
    |-- rule
    |-- clock
    |-- route
    |-- palette
    |-- world_setting
    |-- future types...
    |
    v
  Storage Layer
    |-- entities               # unified index
    |-- aliases
    |-- domain tables           # rules, clocks, routes, world_settings...
    |-- turns/events/meta
    |-- fts_index
    |
    v
  Content Lifecycle
    |-- seed from campaign YAML
    |-- apply content delta
    |-- validate
    |-- rebuild FTS
    |-- render snapshots/cards
    |
    v
  Context Pipeline
    |-- classify intent
    |-- resolve entities
    |-- run registered collectors
    |-- rank/prune by budget
    |-- audit optional
```

## 6. 核心抽象：Content Type Registry

### 6.1 ContentTypeSpec

新增模块：

```text
rpg_engine/content_types/
  __init__.py
  base.py
  registry.py
  core.py
  world_setting.py
```

建议接口：

```python
from dataclasses import dataclass
from typing import Any, Callable, Iterable
import sqlite3

@dataclass(frozen=True)
class ContentTypeSpec:
    name: str
    entity_type: str | None
    campaign_key: str | None
    yaml_key: str | None
    delta_key: str | None
    table: str | None

    seed: Callable[[ContentRuntime, dict[str, Any]], None] | None = None
    upsert: Callable[[ContentRuntime, dict[str, Any]], None] | None = None
    validate_seed: Callable[[ValidationRuntime, dict[str, Any]], list[str]] | None = None
    validate_delta: Callable[[ValidationRuntime, dict[str, Any]], list[str]] | None = None
    validate_database: Callable[[ValidationRuntime], list[str]] | None = None
    collect_context: Callable[[ContextRuntime], list[ContextSection]] | None = None
```

`ContentRuntime` 包含：

```python
@dataclass
class ContentRuntime:
    campaign: Campaign
    conn: sqlite3.Connection
    turn_id: str
    now: str
```

`ValidationRuntime` 包含 campaign、conn、path、upsert_ids 等校验上下文。

### 6.2 Registry

```python
class ContentRegistry:
    def register(self, spec: ContentTypeSpec) -> None: ...
    def get(self, name: str) -> ContentTypeSpec: ...
    def by_campaign_key(self, key: str) -> ContentTypeSpec | None: ...
    def by_delta_key(self, key: str) -> ContentTypeSpec | None: ...
    def by_entity_type(self, entity_type: str) -> ContentTypeSpec | None: ...
    def all(self) -> list[ContentTypeSpec]: ...
```

默认注册：

```python
register_core_content_types(registry)
register_world_setting(registry)
```

未来游戏包插件可以在加载 campaign 时注册额外 spec，但第一阶段先只做内置注册。

### 6.3 Registry 接口约束

Registry 的第一阶段目标是降低横向硬编码，不是把所有引擎行为都抽象成回调。实现时必须遵守：

- 只注册内容生命周期必需能力：seed、content delta upsert、validate、render、context collect。
- 不把 turn resolution、AI 调用、业务预演和安全策略塞进 `ContentTypeSpec`。
- 不把 card renderer、query renderer、目录、排序等展示策略塞进 `ContentTypeSpec`；这些属于 `CardRegistry` / presentation registry。
- 不要求所有类型实现所有接口；缺省时走现有 generic 行为。
- 核心 `entities`、`turns`、`events`、`meta` 仍是引擎基础设施，不做成可卸载类型。
- 第一阶段只迁 `entity/rule/clock/route`，验证稳定后再迁更多行为。

如果一个新字段需要多个模块共同理解，优先判断它是不是一个内容类型；如果只是某个内容类型的内部字段，不应升级为 registry 级接口。

## 7. 存储模型

### 7.1 保留 `entities`

所有内容类型如果需要搜索、别名、卡片和上下文，都必须有对应 `entities` 行。

`entities` 继续负责：

- `id`
- `type`
- `name`
- `status`
- `visibility`
- `location_id`
- `owner_id`
- `summary`
- `details_json`
- `updated_turn_id`
- `updated_at`

### 7.2 专表规则

内容类型分三类：

| 类型 | 是否需要专表 | 示例 |
|------|--------------|------|
| 纯实体型 | 不需要 | `reference`、普通 `faction` 初期可只放 details |
| 专表型 | 需要 | `rule`、`clock`、`route`、`world_setting` |
| 外部候选型 | 不进入事实库 | `palette` |

### 7.3 新增 `world_settings` 表

用于一等世界观设定库。它不是 clock，也不是 rule，而是“稳定设定模块”。

```sql
create table if not exists world_settings (
  entity_id text primary key,
  category text not null,
  scope text not null default 'world',
  visibility text not null default 'known',
  priority integer not null default 50,
  summary text not null default '',
  content_json text not null default '{}',
  linked_rules_json text not null default '[]',
  linked_clocks_json text not null default '[]',
  linked_entities_json text not null default '[]',
  applies_when_json text not null default '{}',
  source text not null default 'content',
  foreign key(entity_id) references entities(id) on delete cascade
);

create index if not exists idx_world_settings_category
on world_settings(category, visibility, priority);
```

### 7.4 Migration 结构

当前 `init_database()` 直接执行 `0001_init.sql`，同时已有 `migrations.py`。建议明确：

- `0001_init.sql` 继续作为新库基础。
- `0002_world_settings.sql` 增量添加 `world_settings`。
- `init_database()` 新库初始化后自动应用全部 migrations，或者把 0002 并入 migration runner。
- `migrate apply` 必须支持已有库升级。
- migration apply 前必须自动创建 `pre_migration` 备份，当前 CLI 已有这个模式，后续迁移不得绕开。
- 单个 migration 必须在事务中执行；失败时回滚，不写入 `schema_migrations`。
- 新库初始化和旧库升级必须走同一批 migration 文件，避免“新库有表、旧库缺表”的分叉。

验收点：

```bash
python3 -m rpg_engine migrate status ../rp/isekai-farm-v2
python3 -m rpg_engine migrate apply ../rp/isekai-farm-v2
python3 -m rpg_engine check ../rp/isekai-farm-v2
```

## 8. 内容生命周期

### 8.1 Campaign seed

目标：

```python
def seed_content(conn: sqlite3.Connection, campaign: Campaign) -> None:
    runtime = ContentRuntime(campaign, conn, SEED_TURN_ID, utc_now())
    for spec in registry.all():
        if not spec.campaign_key or not spec.yaml_key or not spec.seed:
            continue
        for path in campaign.content_files(spec.campaign_key):
            data = load_yaml_file(path)
            for record in data.get(spec.yaml_key, []):
                spec.seed(runtime, record)
```

现有映射：

| campaign key | yaml key | spec |
|--------------|----------|------|
| `entities` | `entities` | entity |
| `rules` | `rules` | rule |
| `clocks` | `clocks` | clock |
| `routes` | `routes` | route |
| `world_settings` | `world_settings` | world_setting |

### 8.2 Content delta

目标：

```python
for spec in registry.all():
    if not spec.delta_key or not spec.upsert:
        continue
    for record in delta.get(spec.delta_key, []):
        spec.upsert(runtime, record)
```

现有 delta 字段继续支持：

- `upsert_entities`
- `upsert_routes`
- `upsert_rules`

新增：

- `upsert_world_settings`

以后新增内容类型只需注册 `delta_key`。

### 8.3 Turn delta

短期不把所有内容类型都塞进 `save-turn` turn delta。`save-turn` 继续处理玩家行动导致的：

- `events`
- `upsert_entities`
- `tick_clocks`
- `meta`

内容维护类变化继续走 `content_delta`。这是为了保持玩家回合 schema 简洁。

## 9. Context Pipeline 模块化

### 9.1 当前问题

`context_builder.py` 同时负责：

- intent/submode 判断
- entity resolution
- active clocks
- routes
- palettes
- history
- memory
- section ranking
- budget pruning
- audit

新增内容类型时容易继续往这个文件堆逻辑。

### 9.2 目标拆分

```text
context_builder.py
  build_context()
  classify_request()
  resolve_entities()
  run_context_collectors()
  rank_and_prune()

content_types/*.py
  collect_context()
```

### 9.3 Collector 接口

```python
@dataclass
class ContextCollectorResult:
    sections: list[ContextSection]
    audit_items: list[ContextAuditItem]

def collect_context(runtime: ContextRuntime) -> ContextCollectorResult:
    ...
```

`ContextRuntime` 包含：

- campaign
- conn
- user_text
- mode/submode
- entity_hits
- meta
- budget
- existing sections

### 9.4 Collector 顺序

建议默认顺序：

1. scene/current state
2. directly relevant entities
3. rules
4. world settings
5. active clocks
6. routes
7. palettes
8. recent history
9. memory summaries
10. templates

注意：`world_settings` 不应默认全量加载，只在以下条件召回：

- 玩家问题命中 alias/name/FTS。
- 玩家意图与 category 相关，例如“天气”“历法”“力量体系”“种族”“势力”。
- 当前 active clock 的 `linked_clocks` 反向命中。
- 相关 rule 的 `linked_rules` 反向命中。
- 行动 submode 需要，例如 `travel` 可召回 weather/calendar，`social` 可召回 species/faction culture。

每个 collector 必须返回可审计 reason，例如：

```text
玩家文本命中关键词：天气
关联进度钟：clock:drought-spring
行动子模式 travel 需要 weather category
```

没有 reason 的 section 不得进入最终上下文。

### 9.5 Budget 策略

每个 collector 只返回候选 section，不直接决定最终上下文。

`rank_and_prune()` 统一处理：

- `priority`
- `required`
- `estimated_tokens`
- `mode/submode`
- hidden visibility
- audit reason

## 10. 新内容类型：world_setting

### 10.1 用途

`world_setting` 表示稳定的大世界设定模块，例如：

- 时间与历法
- 天气与气候
- 力量体系
- 种族文化
- 势力结构
- 生态资源循环
- 经济贸易
- 科技制作
- 世界真相边界

它和其他类型的关系：

| 类型 | 关系 |
|------|------|
| `rule` | world_setting 引用多个 rule，rule 负责硬边界 |
| `clock` | world_setting 引用相关 clock，clock 负责动态推进 |
| `entity` | world_setting 引用地点、种族、势力、物品等事实 |
| `palette` | world_setting 描述规则，palette 提供未发现候选 |

### 10.2 YAML

```yaml
world_settings:
  - id: world:weather
    name: 天气与气候
    category: weather
    scope: world
    visibility: known
    priority: 70
    summary: 天气影响出行、灌溉、痕迹、火药安全和动物活动。
    content:
      patterns:
        clear:
          effects: [适合出行, 作物需浇水, 可能推进干旱]
        rain:
          effects: [免浇水, 冲淡痕迹, 泥地行动变慢]
        storm:
          effects: [远行危险, 火药操作高风险, 水源恢复较快]
    linked_rules: [rule:water-budget]
    linked_clocks: [clock:drought-spring, clock:forest-attention]
    linked_entities: []
    applies_when:
      submodes: [travel, gather, craft]
      keywords: [天气, 下雨, 干旱, 火药]
    source: content/world_settings.yaml
    aliases: [天气, 气候, 下雨, 干旱天气]
```

### 10.3 Category 建议

```text
calendar
weather
power
species_culture
faction
ecology
economy
technology
truth
```

### 10.4 Upsert 行为

`upsert_world_setting()`：

1. 写 `entities`：
   - `type = "world_setting"`
   - `summary = setting["summary"]`
   - `details_json` 放 category、scope、links、applies_when、source。
2. 写 `world_settings` 专表。
3. 写 aliases。
4. 重建 FTS。

### 10.5 校验

必须校验：

- `id` 匹配 `world:<slug>`。
- `category` 在白名单内。
- `visibility` 在 `known/hinted/hidden` 内。
- `priority` 是整数。
- `linked_rules` 存在于 `rules` 或本 delta 即将 upsert。
- `linked_clocks` 存在于 `clocks`。
- `linked_entities` 存在于 `entities` 或本 delta 即将 upsert。
- `content` 是 object。
- hidden setting 不应默认进入普通查询上下文，除非 GM/maintenance 模式。

隐藏内容防泄露规则：

- `visibility: hidden` 的 world setting 不应被普通 `query entity`、FTS、alias 或 context collector 直接展示。
- 普通卡片渲染可以生成 hidden 卡，但默认索引不得把 hidden 内容列为玩家可见事实。
- GM/maintenance 模式可以读取 hidden 内容，但 context audit 必须记录读取原因。
- 如果 hidden 内容只用于防止 GM 乱编，可以只放设计文档，不必入库。

### 10.6 渲染

卡片目录：

```text
cards/world_settings/world__weather.md
```

渲染结构：

```text
## 大世界设定：天气与气候

| 字段 | 值 |
|------|----|
| ID | `world:weather` |
| 分类 | weather |
| 范围 | world |
| 可见性 | known |
| 优先级 | 70 |

### 摘要
...

### 关联规则
- `rule:water-budget`

### 关联进度钟
- `clock:drought-spring`

### 内容
...
```

## 11. Delta 与 Schema 改造

### 11.1 问题

`delta_schema.py` 当前硬编码：

- 顶层字段白名单。
- entity type 白名单。
- `tick_clocks` 结构。
- 数据库引用校验。

### 11.2 设计

保留 turn delta 的稳定 schema，但让内容维护 delta 走 registry。

拆分：

```text
delta_schema.py              # turn delta only
content_delta_schema.py      # content maintenance delta
content_types/*              # each type validates its records
```

内容维护 delta：

```json
{
  "description": "补充大世界设定",
  "event_type": "content_delta",
  "intent": "content_maintenance",
  "source": "world_setting_update",
  "upsert_world_settings": []
}
```

`content_delta_schema` 不需要硬编码每个 `upsert_*` 字段，而是：

```python
known_delta_keys = {spec.delta_key for spec in registry.all() if spec.delta_key}
```

## 12. 渲染与卡片改造

### 12.1 当前问题

`render.py` 和 `cards.py` 对类型分支较多。新增类型会继续加 if/elif。

### 12.2 设计

内容生命周期 registry 提供 seed / delta / sync / validate；展示 registry 单独提供：

- `card_dir`
- `append_sections`
- `render_query`
- `sort_order`
- `id_prefixes`
- `render_context_entity` 可选

通用逻辑：

```python
spec = card_registry.by_entity_type(entity["type"])
if spec and spec.render_query:
    text = spec.render_query(conn, entity)
else:
    text = render_generic_entity(entity)
```

卡片路径：

```python
card_dir = card_registry.card_dir(entity_type)
```

现有类型先保持输出路径不变，避免破坏外部链接。

## 13. 校验与审计改造

### 13.1 Database checks

当前 `validators.run_checks()` 集中校验所有类型。改为：

```python
def run_checks(conn):
    errors = run_core_checks(conn)
    for spec in registry.all():
        if spec.validate_database:
            errors.extend(spec.validate_database(runtime))
    return errors
```

### 13.2 Context audit

每个 collector 返回 audit reason：

```text
item_id
item_kind
source
reason
priority
included
omitted_reason
depth
```

这样可以解释为什么某个 world setting、rule 或 clock 进入上下文。

## 14. CLI 改造

短期保持现有命令。

已实现：

```bash
python3 -m rpg_engine content list-types
python3 -m rpg_engine content inspect-type world_setting
python3 -m rpg_engine content sync ../rp/isekai-farm-v2
```

当前已由 V2 首批改造实现：

```bash
python3 -m rpg_engine content validate-delta ../rp/isekai-farm-v2 /path/to/content_delta.json
python3 -m rpg_engine package validate ../rp/isekai-farm-v2
python3 -m rpg_engine package diff ../rp/isekai-farm-v2 ../rp/isekai-farm-v2
python3 -m rpg_engine package upgrade ../rp/isekai-farm-v2 ../rp/isekai-farm-v2 --dry-run
```

`content sync` 也会在备份和事务前校验注册源文件。package validate/build/test/reconcile/install/diff/upgrade、package-lock adopt/repair、自动备份、真实 apply、同版本 checksum 阻断和受限显式 deterministic migration 已由 V2 阶段 E 实现；archive 直接安装和复杂脚本 migration 继续按 V2 后续边界处理。

可选命令，当前不阻塞，因为 `query entity` 已能满足：

```bash
python3 -m rpg_engine query world-setting ../rp/isekai-farm-v2 天气
```

`query entity 天气` 已可通过 alias/FTS 满足同一需求。

## 15. 文件组织建议

```text
rpg_engine/
  content_types/
    __init__.py
    base.py
    registry.py
    entity.py
    rule.py
    clock.py
    route.py
    world_setting.py
  context/
    pipeline.py
    collectors.py
    sections.py
    budget.py
  storage/
    json.py
    refs.py
  migrations.py
  db.py
  content_delta.py
  render.py
  cards.py
```

不要一次性搬完。第一阶段只引入 `content_types/`，其他文件继续存在。

### 15.1 当前实施状态同步（2026-06-29）

当前实现已经从“设计计划”推进到“通用内核核心闭环已站住”的完成态；后续重点是完整 package/API/plugin 平台化。

已完成：

| 阶段 | 状态 | 当前实现 |
|------|------|----------|
| 阶段 0：特征测试补齐 | 已完成 | 单测、回归测试、正式 campaign check 已覆盖核心行为。 |
| 阶段 1：引入 registry | 已完成 | `ContentTypeSpec`、`ContentRegistry`、`content list-types`、`content inspect-type` 已实现。 |
| 阶段 2：seed registry 化 | 已完成 | `db.seed_content()` 已按 registry seed specs 加载内容。 |
| 阶段 3：content_delta registry 化 | 已完成当前注册类型范围 | `content_delta.apply_content_delta()` 已按 registered delta specs 分发 upsert；独立 content-delta schema、未知顶层字段拒绝、注册类型 record 校验和跨引用预检已落地。字段所有权 dry-run 内核、package apply/upgrade 和受限显式 migration 归入 V2 剧本包阶段并已完成最小安全闭环。 |
| 阶段 4：render/cards/query registry 化 | 已完成主体 | 新增 `rpg_engine/card_registry.py`；卡片目录、排序、INDEX 分组、ID 前缀推断、card section 分发和 `query entity` renderer 已由 `CardRegistry` / `CardTypeSpec` 驱动；`cards.py` / `render.py` 保留 fallback。 |
| 阶段 5：validators registry 化 | 已完成当前注册类型范围 | `validators.run_checks()` 已拆成 core checks + registered type checks；`world_setting` 的数据库事后校验已回到类型模块；写入前 record/reference preflight 已通过 `content_validation.py` 覆盖当前 delta 类型。 |
| 阶段 6：world_setting | 引擎完成、内容持续扩展 | `0002_world_settings.sql`、`content_types/world_setting.py`、`content/world_settings.yaml`、查询、卡片、数据库校验和 context recall 均已落地；当前 campaign 已有 10 个设定模块，包含神祇和 hinted 可见性的古代文明/遗迹 truth 模块。 |
| 阶段 7：context collectors / pipeline 模块化 | 已完成主体 | `active_clocks`、`routes`、`palettes`、`world_settings`、`recent_events`、`memory_summaries` 已迁入 `rpg_engine/context/collectors.py`；`build_context()` 编排已抽到 `rpg_engine/context/pipeline.py`，原入口保持兼容；collector 仍由内置固定列表装配。 |
| 阶段 7.5：visibility / sync 安全边界 | 已完成主体 | 新增 `rpg_engine/visibility.py`；普通 query/context/FTS/card index 默认使用 player 视角过滤 hidden；GM/maintenance 可显式读取；`ContentTypeSpec.sync_safe` 限制 `content sync` 默认范围。 |
| 阶段 7.6：context resolution / validation 拆分 | 已完成主体 | `EntityHit`、实体命中、候选搜索、语义别名补全、相关实体扩展已迁入 `rpg_engine/context/resolution.py`；行动/query 校验已迁入 `rpg_engine/context/validation.py`；流程说明和模板加载已迁入 `rpg_engine/context/procedure.py`。 |
| 阶段 7.7：context rendering 拆分 | 已完成主体 | 玩家状态、相关实体、实体详情、歧义候选和上下文格式化 helper 已迁入 `rpg_engine/context/rendering.py`；`context_builder.py` 已收敛为分类、section 组装和最终 packet 渲染。 |
| 阶段 7.8：context semantic 拆分 | 已完成主体 | semantic AI prompt、外部 `hermes` 调用、JSON 解析和 normalizer 已迁入 `rpg_engine/context/semantic.py`；`context_builder.py` 仅保留 pipeline 引用和兼容导入。 |
| 阶段 7.9：render / snapshot visibility 收敛 | 已完成主体 | `render_scene()`、`render_current_snapshot_json()` 已支持 view 参数并复用 `visibility.py`；当前场景对象排序复用 `CardRegistry`；`query scene --view` 已支持 player/gm/maintenance；`content inspect-type` 已拆分 Content Lifecycle 与 Presentation 输出。 |
| 阶段 7.10：content / presentation registry 边界收敛 | 已完成主体 | `ContentTypeSpec` 已移除 `card_dir`、`append_card_sections`、`render_entity` 展示字段；`CardTypeSpec` 负责 card sections 与 query renderer；`content inspect-type` 从 `CardRegistry` 展示 presentation 信息。 |
| V2 阶段 D：Action Resolver 合约入口 | 核心闭环完成 | `ActionResolverSpec` 已具备 option spec、request/resolve/delta 合约入口、keywords、semantic labels 和 inference priority；`preview` CLI 子命令由 registry 生成；`turn assistant` 输出 Action Contract；新增 `explore` 验证行动；`travel/rest/gather/craft/social/combat` 均已有领域 resolve/delta 校验；action adapter 已拆成独立模块；`actions/policy.py` 提供进度钟策略 seam。剩余是完整规则组件注入和动态插件扩展。 |
| V2 阶段 B：Outbox / Projection | 核心完成 | `0003_write_reliability.sql` 已加入 `outbox` 和 `projection_state`；JSONL outbox、package_lock 文件投影、projection status/repair、提交后失败重试已落地；`save_turn_delta`、`apply_content_delta`、`sync_campaign_content` 已统一到 `UnitOfWork` 生命周期；package apply 的 FTS/search 投影已有 dirty entity 增量切片。增量 cards/snapshot/memory 投影仍待续。 |
| V2 阶段 E：Package merge / apply 最小闭环 | 安全提交闭环完成 | `ContentTypeSpec.merge_policy`、`MergePolicy`、`package_merge.py`、`package_service.py`、`package_lock.py` 和 `package_archive.py` 已支持 `author-owned`、`runtime-owned`、`mergeable`、`conflict-only` 字段策略、注册内容包加载、package validate/build/test/reconcile/install/diff/upgrade、package-lock adopt/repair、数据库引用预检、冲突报告、no-op 过滤、带 lock 的 create/update apply、自动备份、受限显式 deterministic migration 执行/checksum 追踪、同版本 checksum 阻断和 lock projection failure recovery；archive 直接安装、复杂脚本 migration 和更大规模 fixture 仍待后续。 |
| V2 阶段 F：AI Proposal 最小 guard | 最小完成 | `proposal.py`、TurnProposal schema、ApprovedOutcome、delta contract 校验、response claim guard、`proposal validate` CLI 和 assistant `--proposal-json` 已落地；默认保存路径尚未强制切换到 proposal。 |
| V2 阶段 G：大世界运行类型切片 | 最小完成 | `faction_state` 已作为 runtime entity 类型接入 delta schema、card/query 渲染和 memory 摘要；完整 faction relation、quest/scene/lore thread、神祇 gate 和遗迹探索仍待后续。 |
| V2 阶段 H：插件/API 门禁 | 门禁切片完成 | importer registry、plugin manifest discovery/validate 和 engine API version/capability 校验已落地；动态插件代码加载和公共插件 API 仍不开放。 |

当前验证命令：

```bash
python3 -m unittest discover -s tests
python3 tests/regression.py
python3 -m rpg_engine check ../rp/isekai-farm-v2
python3 -m rpg_engine simulate longrun ../rp/isekai-farm-v2 --turns 100 --budget 3000
python3 -m rpg_engine projection status ../rp/isekai-farm-v2
python3 -m rpg_engine migrate status ../rp/isekai-farm-v2
python3 -m rpg_engine package validate ../rp/isekai-farm-v2
python3 -m rpg_engine package reconcile ../rp/isekai-farm-v2 ../rp/isekai-farm-v2
python3 -m rpg_engine package upgrade ../rp/isekai-farm-v2 ../rp/isekai-farm-v2 --dry-run
```

最近一次通过状态：

- unit tests：110 OK
- regression tests：26 OK
- total：136 OK
- formal campaign check：OK
- 100-turn longrun simulation：avg 0.0014s，max 0.0046s，check_errors 0
- projection status：all clean including package_lock，outbox empty
- migration status：0001/0002/0003 applied，checksum ok
- package validate：正式包 OK；65 entity、12 rule、6 clock、10 world_setting
- package reconcile/test/upgrade --dry-run：因缺少 package-lock warning、71 个 drift records 与 9 个 entity `details` conflict-only 分叉而阻断
- package upgrade apply：带 package-lock 的 create/update、`update_conflict_field`、`rename_entity`、新库 install、lock projection repair、同版本 checksum 阻断和 migration checksum mismatch 已在临时 fixture 覆盖；正式包未创建 package-lock

当前剩余架构债：

1. `context_builder.py` 仍负责 intent 分类、核心 section 组装和最终 packet / markdown 渲染；collector、pipeline、resolution、validation、procedure、entity rendering、semantic 已拆出。
2. content lifecycle 与 presentation registry 已拆清：`ContentTypeSpec` 负责 seed/delta/sync/validate，`CardTypeSpec` 负责 card/query 展示；后续新增类型不得把展示策略写回 content lifecycle spec。
3. `render.py` 的 scene / snapshot 已支持 view-aware visibility 和 presentation sort；`query entity` 已走 `CardRegistry.render_query`，剩余硬编码主要是 renderer 函数本身仍集中在 `render.py`。
4. visibility policy 已覆盖普通 query、context entity resolution、world_setting collector、FTS、card index、scene/snapshot 和部分 preview 解析；后续若新增读取路径，必须继续复用 `visibility.py`。
5. `content sync` 已由 `ContentTypeSpec.sync_safe` 限制默认同步范围；显式同步不安全类型需要 `--allow-unsafe`。
6. 内容维护 delta 已有独立 schema 文件、未知 `upsert_*` 拒绝、注册类型 record 校验和跨引用预检；definition/runtime 字段所有权 dry-run 内核、package validate/build/test/reconcile/install/diff/upgrade CLI、package-lock adopt/repair、conflict-free apply、自动备份、受限显式 deterministic migration 执行/checksum 追踪、同版本 checksum 阻断和 save export/import 已落地。剩余缺口是 archive 直接安装、复杂脚本 migration 和更大规模 fixture。
7. `world_settings` 和 `world_settings_core` 已加入显式排序；行动模式有不可裁掉的 compact 世界约束，完整设定仍按预算选入。
8. 多主题世界观查询已能召回多个设定，但通用指代词检测可能把“这个世界的力量体系和天气”误判为需要确认。
9. Action Resolver Registry 已有合约入口、`explore` 验证行动、`travel/rest/gather/craft/social/combat` 领域 resolve/delta 校验；preview 不再是核心闭环的唯一规则来源，进度钟匹配已抽到 policy seam，剩余缺口是把更多高风险规则抽成可注入 policy/规则组件。
10. 阶段 8 只完成 manifest discovery/validate 门禁：collector、presentation、action resolver 和 content lifecycle 仍没有动态外部 module loading，不能把当前 registry 称为公共插件 API。

## 16. 渐进式实施计划

### 阶段 0：特征测试补齐

目标：保证重构不改变现有行为。

新增或确认测试：

- `init` 后实体、rule、clock、route 数量一致。
- `render-cards` 输出关键文件。
- `context build` 对典型输入仍包含 active clocks。
- `validate delta` 对现有合法/非法样例结果不变。
- `apply-content-delta` 可写 rule/entity/route。
- `palette suggest` 行为不变。

### 阶段 1：引入 registry，不改行为

新增：

- `ContentTypeSpec`
- `ContentRegistry`
- `register_core_content_types`

但 `db.py` 等模块先不使用 registry。只建立测试。

验收：

- `content list-types` 可列出内置类型。
- 现有测试全部通过。

### 阶段 2：seed_content 改为 registry 驱动

把 `entities/rules/clocks/routes` 的 seed 注册进去。

现有函数 `upsert_rule`、`upsert_clock`、`upsert_route` 可继续复用。

验收：

- 重新 init 临时 campaign，数据库内容一致。
- 当前 `rp/isekai-farm-v2` check 通过。

### 阶段 3：content_delta 改为 registry 驱动

将 `upsert_rules/upsert_routes/upsert_entities` 从手写循环迁到 registry。

验收：

- 现有 `content/deltas/*.json` 可继续应用到临时副本。
- event payload 仍记录 counts 和 upsert ids。

### 阶段 4：render/cards 改为 registry 渲染

当前已从 `ContentTypeSpec` 的局部 card hook 继续推进到独立展示 registry：

- `rpg_engine/card_registry.py` 定义 `CardTypeSpec` / `CardRegistry`。
- `cards.py` 的目录、排序、INDEX 分组、ID 前缀推断和 card section 分发已走 `CardRegistry`。
- `render.py` 的 `query entity` 渲染已走 `CardRegistry.render_query`。
- `ContentTypeSpec` 不再承载 `card_dir`、`append_card_sections`、`render_entity` 展示字段。
- `character/item/location/crop_plot/plant/material/species/reference/project/recipe/threat/rule/clock/world_setting` 均有默认展示 spec。
- 未注册类型仍落到 `misc` 和 generic details fallback。

验收：

- 卡片内容无意外差异，路径不变。
- `INDEX.md` 继续按 player view 过滤隐藏实体；实体卡文件仍为全部非 archived 实体生成。
- `tests/test_card_registry.py` 覆盖默认展示注册、路径、前缀推断、排序和重复注册保护。

### 阶段 5：validators 改为 registry 校验

拆出 core checks 和 type checks。

验收：

- bad clock、bad route、missing alias target 等仍能报错。

### 阶段 6：新增 world_setting

实施：

- `0002_world_settings.sql`
- `content_types/world_setting.py`
- `upsert_world_setting`
- `validate_world_setting`
- `render_world_setting`
- `collect_world_settings`
- `content/world_settings.yaml`
- `campaign.yaml` 添加：

```yaml
content:
  world_settings:
    - content/world_settings.yaml
```

验收：

- `query entity 天气` 命中 `world:weather`。
- `context build --user-text "天气会影响我去小溪吗"` 包含天气设定。
- 普通行动不会全量加载所有 world settings。
- hidden world truth 不会在普通上下文泄露。

### 阶段 7：context collectors 模块化

把 active clocks、routes、palettes、world_settings 拆成 collector。

验收：

- context output section key 稳定。
- context audit 能解释每个 section 来源。
- budget 裁剪结果可预测。

### 阶段 8：插件化扩展

在内置 registry 稳定后再考虑：

- campaign 指定启用哪些 content type。
- 游戏包本地 Python 插件注册类型。
- CLI 检查插件版本和 engine version。

## 17. 向后兼容策略

必须保持：

- 现有 `campaign.yaml` 可运行。
- 现有 `content/rules.yaml`、`content/clocks.yaml` 可加载。
- 现有 `content/deltas/*.json` 可应用。
- 现有 `cards/` 路径尽量不变。
- `save-turn` turn delta schema 不被 world_setting 复杂化。
- `palettes` 仍然不是当前事实。

可接受变化：

- 新增 `world_settings` 表。
- 新增 `world_setting` entity type。
- 新增 cards 子目录 `cards/world_settings/`。
- `context_builder` 内部实现变化，只要输出语义稳定。

## 18. 风险与控制

| 风险 | 说明 | 控制 |
|------|------|------|
| 过度抽象 | 为未来类型设计过多接口 | 先只迁 rule/clock/route/world_setting |
| 回归现有游戏 | 重构影响当前存档 | 阶段 0 特征测试和临时副本验证 |
| 上下文膨胀 | world settings 全量进入上下文 | collector 必须按关键词/链接/意图召回 |
| 隐藏设定泄露 | hidden truth 被普通查询命中 | visibility 过滤和 GM/maintenance 模式隔离 |
| migration 失败 | 现有库升级风险 | migrate 前自动 backup，check 后提交 |
| plugin 安全 | 外部 Python 插件执行任意代码 | 远期再做；短期只内置类型 |
| registry 变成万能抽象 | 类型 spec 承担过多职责 | 第一阶段只抽内容生命周期，业务预演和 AI 调用不进 spec |
| 查询路径泄露隐藏设定 | FTS/alias/card/scene/snapshot 绕过 context visibility | hidden 过滤必须覆盖 query、FTS、context、索引展示、scene 和 snapshot |

## 19. 测试计划

### 19.1 Unit tests

- registry register/get/duplicate error。
- each content type validate seed record。
- world_setting link validation。
- visibility filtering。
- hidden scene/snapshot/context leakage filtering。
- JSON serialization stable。

### 19.2 Integration tests

- init campaign from YAML。
- apply content delta with world settings。
- render cards。
- context build with world setting query。
- context build ordinary action excludes irrelevant world settings。
- migrate old database to new schema。
- content list-types / inspect-type 输出稳定。

### 19.3 Golden output tests

模块化改造最容易出现“命令不报错但上下文质量变差”。必须保留一组小型 golden output 或 fingerprint：

- `context build --user-text "我去小溪收鱼笼"` 的 section keys、loaded item ids、allow_proceed。
- `render-cards` 后关键卡片路径存在。
- `query entity 终极复合弩` 包含关键字段。
- `palette suggest --location 小溪 --intent gather` 的候选状态分布。

golden 不需要逐字锁定完整 Markdown，优先锁定结构、关键 ID 和关键字段，避免文本微调造成脆弱测试。

### 19.4 Regression tests

继续运行现有：

```bash
python3 -m unittest discover -s tests
python3 tests/regression.py
```

并保留当前 campaign 检查：

```bash
python3 -m rpg_engine check ../rp/isekai-farm-v2
python3 -m rpg_engine context build ../rp/isekai-farm-v2 --user-text "我去小溪收鱼笼" --budget 2500
```

## 20. 成功标准

短期成功：

- 引入 registry 后现有行为不变。
- `world_setting` 能成为一等内容类型。
- 世界观设定能被查询、渲染、校验和按需进入上下文。
- `clocks.yaml` 继续只承担动态进度职责。

长期成功：

- 新增内容类型不再需要横向修改 6 个以上核心模块。
- 每个内容类型能独立声明自己的存储、校验、渲染和上下文策略。
- AI GM 的事实层、规则层、动态压力层、候选生成层保持清晰分离。
- 多个 campaign 可以复用同一引擎，只替换内容包和少量注册类型。

## 21. 历史遗留观察

本节只保留模块化改造完成后的遗留观察，不再定义当前开发优先级。当前实施顺序以 [`kernel-requirements.md`](../../../specs/kernel-requirements.md) 和 [`DOCUMENTATION_BASELINE.md`](DOCUMENTATION_BASELINE.md) 为准。

历史遗留观察：

1. 内容维护 preflight 已完成当前注册类型范围；merge policy、package validate/build/test/reconcile/install/diff/upgrade、package-lock adopt/repair、conflict-free apply、受限显式 deterministic migration 执行/checksum 追踪、同版本 checksum 阻断和 save export/import 已落地，archive 直接安装、复杂脚本 migration 和更大规模 fixture 仍是后续输入。
2. `world_settings` section 排序与 compact 保底已完成；context 歧义候选已移除当前游戏专名 fallback，但多主题通用指代误判仍需继续补回归。
3. 世界设定文档与当前 10 个 `world_setting` 模块已经同步；后续 faction 运行状态、神祇显现 gate 和遗迹探索按 V2 阶段 G 实施，不再沿用本文件“第 9 类 truth”旧任务。
4. plugin API 延后到 V2 阶段 H；当前只开放 plugin manifest discovery/validate 门禁，在 Action Resolver、内容契约、投影和事务边界稳定前不开放动态外部 module loading。
5. 视代码体量决定是否把 `render.py` 的具体 renderer 拆入 presentation 子包；这不是启用阻塞项。

当前开发优先级不在本文维护；不得使用本历史文档覆盖 V1 基线。高影响内容补丁即使通过 package validate/build/test/reconcile/install/diff/upgrade，仍需在显式 migration、package-lock 和冲突报告可人工复核后再应用到正式库。
