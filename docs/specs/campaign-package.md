# AIGM Campaign Package Spec V1

文档状态：**V1 规范，已由 `aigm campaign validate/test` 执行**  
适用范围：普通作者可写、可读、可改的 AIGM 剧本包。  
边界：V1 剧本作者不写代码，不提供插件，不写脚本化规则。

## 1. 目标

剧本包负责定义一次游戏可加载的世界、初始状态、玩法声明、GM 风格和 smoke tests。它不保存某次游玩的进度；进度属于 Save Package。

V1 剧本包必须能被以下命令检查：

```bash
aigm campaign validate ./campaigns/example
aigm campaign test ./campaigns/example
```

未安装命令时可用：

```bash
python3 -m rpg_engine campaign validate ./campaigns/example
python3 -m rpg_engine campaign test ./campaigns/example
```

## 2. 目录结构

V1 最小结构：

```text
campaign.yaml
content/
  entities.yaml
  relationships.yaml
  rules.yaml
  clocks.yaml
  random_tables.yaml
prompts/
  gm.md
templates/
  action.md
  query.md
tests/
  smoke.yaml
```

推荐作者结构：

```text
campaign.yaml
AUTHOR_NOTES.md
AUTHOR_AI_PROMPT.md
content/
  world_settings.yaml
  locations.yaml
  characters.yaml
  items.yaml
  projects.yaml
  references.yaml
  relationships.yaml
  rules.yaml
  clocks.yaml
  routes.yaml
  random_tables.yaml
  palettes/
    materials.yaml
    encounters.yaml
prompts/
  gm.md
templates/
  action.md
  query.md
tests/
  smoke.yaml
```

大型剧本可继续按区域、章节或类型拆分；`campaign.yaml.content.*` 支持多个相对路径。作者工具可用：

```bash
aigm campaign new ./campaigns/my-story --template small-cn
aigm campaign doctor ./campaigns/my-story
aigm campaign outline ./campaigns/my-story
```

可选内容文件：

```text
content/routes.yaml
content/world_settings.yaml
```

V1 不允许：

- `plugins/`
- Python 文件
- 作者自定义代码执行
- 脚本化规则引擎
- 任意绝对路径引用

Campaign Package 中不应混入 Save Package 或生成物目录：

```text
data/
cards/
snapshots/
memory/
reports/
backups/
save.yaml
```

`database`、`events`、`current_snapshot`、`current_snapshot_json`、`cards` 是运行路径字段。旧包可保留以兼容；新作者模板应省略它们，使用内核默认值。

## 3. campaign.yaml

最小示例：

```yaml
id: minimal-campaign
name: Minimal Campaign
engine_version: "0.2"
package_version: "0.1.0"
content_schema_version: "1"

capabilities:
  - query
  - rest_time

initial_game_day: 1
initial_time_block: morning
initial_game_time: Day 1 morning
initial_location_id: loc:start

defaults:
  player_entity_id: pc:traveler
  context_budget: 1800
  sample_texts:
    - 查看周围

content:
  entities:
    - content/entities.yaml
  rules:
    - content/rules.yaml
  clocks:
    - content/clocks.yaml
  random_tables:
    - content/random_tables.yaml
  palettes:
    - content/palettes/materials.yaml
    - content/palettes/encounters.yaml
```

要求：

- `id`、`name`、`engine_version`、`package_version`、`content_schema_version` 必填。
- `capabilities` 必填，且只能使用 V1 支持的能力。
- `initial_location_id` 必须指向一个已定义地点。
- `defaults.player_entity_id` 必须指向一个已定义实体。
- `content.*` 必须是相对路径，不能是绝对路径。
- `content.palettes` 可选；也可以只放 `content/palettes/*.yaml` 由 palette loader 自动发现。

## 4. Capabilities

V1 支持的 capability：

```text
query
explore
social
travel
clock
random_table
clue
risk
inventory_resource
project_task
rest_time
trade_exchange
gather_search
combat
```

不同剧本包不需要声明所有能力。声明了某个 capability，就必须在 `tests/smoke.yaml` 中有对应 smoke test 覆盖。

## 5. 内容文件

### entities.yaml

```yaml
entities:
  - id: loc:start
    type: location
    name: Start
    visibility: known
    summary: A quiet starting room.
    location:
      description_short: A quiet starting room.

  - id: pc:traveler
    type: character
    name: Traveler
    visibility: known
    location_id: loc:start
    summary: The player character.
    character:
      role: player
      health_state: healthy
```

要求：

- `id`、`type`、`name`、`summary` 必填。
- `visibility` 可用 `known`、`hinted`、`hidden`。
- `location_id`、`owner_id`、`character.species_id`、`location.parent_id` 必须引用存在的实体。

### relationships.yaml

```yaml
relationships:
  - id: rel:pc-mira
    name: PC and Warden Mira
    source_id: pc:runner
    target_id: npc:warden-mira
    state: cautious ally
    trust: 20
    visibility: known
    summary: Mira will help if the player brings concrete proof.
```

要求：

- `id` 必须以 `rel:` 开头。
- `source_id`、`target_id` 必须引用存在的实体。
- `visibility` 可用 `known`、`hinted`、`hidden`。
- 关系会导入为 `type: relationship` 的实体，额外字段进入 `details`，普通作者不需要写代码。

### rules.yaml

```yaml
rules:
  - id: rule:player-agency
    statement: Do not decide major player intent without confirmation.
```

要求：

- `id` 必须以 `rule:` 开头。
- `statement` 必填。

### clocks.yaml

```yaml
clocks:
  - id: clock:alarm
    name: Alarm
    segments_total: 4
    segments_filled: 0
    visibility: visible
    trigger_when_full: Trouble arrives.
```

要求：

- `id` 必须以 `clock:` 开头。
- `segments_total` 必须是正整数。
- `segments_filled` 不能小于 0，不能超过 `segments_total`。
- `visibility` 可用 `visible`、`hinted`、`hidden`。

### random_tables.yaml

```yaml
random_tables:
  - id: table:room-detail
    name: Room Detail
    visibility: known
    entries:
      - result: A faint sound comes from the wall.
        weight: 1
```

要求：

- `entries` 必须非空。
- `weight` 必须大于 0。
- `visibility` 可用 `known`、`hinted`、`hidden`、`gm`。

### content/palettes/*.yaml

```yaml
materials:
  - id: pal:mat:moon-herb-fresh
    name: 新鲜月白草
    summary: 营地边湿土里的浅色草药，可做简单敷料。
    rarity: common
    locations: [loc:camp]
    intents: [gather, explore, craft]
    discovery:
      mode: direct
      clue_text: 帆布棚外的湿草里有几株叶面泛白的月白草。
      confirm_methods: [观察叶色, 少量采样]
    risks:
      - 采得过多会让营地附近短期无草可取。
    save_as:
      type: material
      entity_id: mat:moon-herb
```

要求：

- 顶层键可用 `materials`、`species`、`factions`、`encounters`、`locations`。
- `id` 必须唯一，建议使用 `pal:<kind>:...`。
- `discovery.mode` 只能是 `direct`、`confirm_required`、`clue_only`。
- `locations` 必须引用已有地点；无固定地点时使用 `biomes`。
- `intents` 必须引用已知行动意图，如 `gather`、`explore`、`social`、`travel`。
- hidden 稀有度不能使用 `direct`，高影响内容应先用 `confirm_required` 或 `clue_only`。

## 6. Prompt 与模板

`prompts/gm.md` 定义 GM 风格、叙事边界和题材语气。

`templates/query.md` 定义查询回复的基本格式。

`templates/action.md` 定义行动回复的基本格式。

这三个文件必须存在且非空。AI 客户端可以读取它们，但事实、保存和校验以内核返回为准。

## 7. Smoke Tests

`tests/smoke.yaml` 示例：

```yaml
smoke_tests:
  - id: query-scene
    type: query
    capabilities: [query]
    kind: scene
    contains: Start

  - id: rest-preview
    type: preview
    capabilities: [rest_time]
    action: rest
    user_text: 休息到早上
    options:
      until: morning
    contains: Delta 草案
```

支持的 smoke test 类型：

- `start_turn`
- `query`
- `preview`
- `validate_delta`
- `random_table`

`campaign validate` 检查 smoke 文件格式和 capability 覆盖。  
`campaign test` 会初始化临时存档并实际运行 smoke tests。

官方最小示例：

```bash
aigm campaign copy-example ./campaigns/v1_minimal_adventure
aigm campaign validate ./campaigns/v1_minimal_adventure
aigm campaign test ./campaigns/v1_minimal_adventure
```

该示例覆盖 V1 的 `query`、`explore`、`social`、`travel`、`clock`、`random_table`、`clue`、`risk`、`inventory_resource`、`project_task`、`rest_time`、`trade_exchange`、`gather_search`。`combat` 是可选能力，适合有明确战斗/防卫玩法的剧本包另行声明并提供 smoke test。

## 8. Schema

规范文件：

```text
schemas/campaign.schema.json
schemas/capabilities.schema.json
schemas/random_tables.schema.json
schemas/smoke.schema.json
```

当前 V1 校验器使用内置 Python 校验逻辑执行这些约束；schema 文件作为对外规范和后续工具生成依据。
