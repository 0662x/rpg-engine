# 作者指南

文档状态：**CURRENT：BMAD canonical authoring guide**

本文件面向 Campaign Package 作者。作者不需要写 Python，也不需要理解 SQLite、MCP、
delta、projection、migration 或插件机制，就可以创建一个可试玩的 AIGM V1 剧本包。

本文件合并了旧 `docs/guides/author-guide.md`、`docs/guides/author-examples.md` 和
`docs/guides/author-maintenance.md` 中仍然有效的作者流程。包模型和运行边界的长期权威
仍是 [Save 与 Campaign Package](save-and-campaign-packages.md)。

## 核心概念

Campaign Package 定义一场新游戏的初始世界、规则、NPC、地点、随机表、GM 风格和
smoke tests。Save Package 保存某个玩家的一次具体游玩进度。

```text
Campaign Package -> save init -> Save Package
```

玩家进度、当前库存、当前地点、时钟推进和关系变化都属于 Save Package，不应写回
Campaign Package 源文件。

## 新建剧本

```bash
aigm campaign new ./campaigns/my-story --template small-cn
aigm campaign doctor ./campaigns/my-story
aigm campaign outline ./campaigns/my-story
aigm campaign test ./campaigns/my-story
```

创建试玩存档：

```bash
aigm save init ./campaigns/my-story ./saves/my-story-test
aigm play query ./saves/my-story-test scene
```

`campaign doctor` 用来检查结构和引用问题；`campaign outline` 用来审阅剧本摘要；
`campaign test` 会初始化临时存档并跑作者 smoke tests。

## 可以编辑的文件

作者通常编辑：

```text
campaign.yaml
AUTHOR_NOTES.md
AUTHOR_AI_PROMPT.md
content/**
prompts/**
templates/**
tests/**
docs/**
```

不要把这些运行态或生成文件当成 Campaign 内容编辑：

```text
data/**
cards/**
snapshots/**
memory/**
reports/**
backups/**
save.yaml
package-lock.json
```

这些文件属于 Save Package、投影产物、运行报告、备份或维护锁定信息。

## 推荐内容文件

小型 Campaign 可以从以下内容文件开始：

```text
content/locations.yaml
content/characters.yaml
content/items.yaml
content/projects.yaml
content/references.yaml
content/relationships.yaml
content/rules.yaml
content/clocks.yaml
content/routes.yaml
content/world_settings.yaml
content/random_tables.yaml
```

每个 YAML 文件都应该易读、易 review、易 diff。如果单个文件膨胀到数百行，按地区、
阵营或类型拆分。

## 基础记录示例

地点：

```yaml
entities:
  - id: loc:camp
    type: location
    name: Camp
    visibility: known
    summary: A safe starting camp.
    aliases: [camp, start]
    location:
      safety_level: guarded
      description_short: A small camp beside the road.
      exits: [Old Bridge]
      resources: [clean water]
```

角色：

```yaml
entities:
  - id: npc:mira
    type: character
    name: Mira
    visibility: known
    location_id: loc:camp
    summary: A cautious guide.
    aliases: [guide]
    character:
      role: guide
      attitude: cautious
      health_state: healthy
```

规则：

```yaml
rules:
  - id: rule:player-agency
    statement: Do not decide major player intent without confirmation.
```

进度钟：

```yaml
clocks:
  - id: clock:storm
    name: Storm
    segments_total: 6
    segments_filled: 0
    visibility: visible
    trigger_when_full: Travel becomes dangerous.
```

随机表：

```yaml
random_tables:
  - id: table:road-detail
    name: Road Detail
    entries:
      - result: Wind moves through the broken sign.
        weight: 1
```

## ID 与可见性

推荐 ID 前缀：

| 类型 | 前缀 |
| --- | --- |
| 地点 | `loc:` |
| 玩家角色 | `pc:` |
| NPC / 角色 | `npc:` 或 `char:` |
| 物品 | `item:` |
| 材料 | `mat:` |
| 项目 | `project:` |
| 线索 / 参考 | `ref:` |
| 关系 | `rel:` |
| 规则 | `rule:` |
| 进度钟 | `clock:` |
| 随机表 | `table:` |

可见性约定：

- `known`：玩家可见事实。
- `hinted`：线索、传闻或部分事实。
- `hidden`：GM-only 事实；不要把 hidden 剧透放进 `known` 摘要。

中文剧本应给地点、人物、物品和重要线索补 `aliases`，方便自然语言检索。

## 题材模板

调查剧本常用能力：

```text
query, explore, clue, risk, social, travel, random_table, rest_time
```

内容重点：3-5 个地点、2-4 个 NPC、3-6 个线索或 reference entity、1-2 个进度钟，
以及场景细节和并发症随机表。Smoke tests 至少覆盖 scene query、clue query、
explore preview、travel preview 和 rest preview。

生存剧本常用能力：

```text
query, travel, gather_search, inventory_resource, project_task, risk, rest_time, clock
```

内容重点：资源、工具、天气或饥饿时钟、修理 shelter 等 project、带风险的 routes。

社交阵营剧本常用能力：

```text
query, social, trade_exchange, clue, clock, random_table
```

内容重点：NPC、关系、阵营状态实体、怀疑/信任/期限进度钟。

战斗防御剧本常用能力：

```text
query, combat, risk, inventory_resource, project_task, rest_time
```

内容重点：威胁、武器弹药、防御 project、确认与后果规则。战斗剧本应包含带 target、
weapon、distance 和 ready state 的 combat smoke test。

## 使用 AI 辅助创作

可以把 [作者 AI Prompt](prompts/author-ai-prompt.md)、剧本本地 `AUTHOR_NOTES.md` 和
doctor JSON 一起交给外部 AI 助手。

推荐修复循环：

```bash
aigm campaign doctor ./campaigns/my-story --format json
```

先修 `severity=error`，再修 `severity=warning`。`suggestion` 默认只作为可选润色，
除非作者明确要求。

AI 辅助只能编辑作者文件。它不能写 Python、插件、脚本规则、migration、save patch，
也不能声称作者文件里的改动已经成为玩家存档事实。

## 维护已有剧本

安全编辑：

- 修错字、名称和摘要。
- 增加 aliases。
- 增加地点、NPC、物品、规则、进度钟、路线和随机表。
- 给新声明的 capabilities 增加 smoke tests。
- 改进 prompts 和 response templates。

需要小心的编辑：

- Entity ID。
- 起始地点。
- 玩家角色 ID。
- 可能在游玩中变化的字段，例如 `location_id`、`owner_id`、库存数量、
  clock filled segments 或 relationship trust。

已有玩家 Save Package 时，Campaign 源文件变化不会自动更新旧存档。维护旧存档要走受控的
package upgrade、save patch 或 gameplay commit 路径，不能手工编辑 save 文件。

## 发布前检查

```bash
aigm campaign doctor ./campaigns/my-story --strict
aigm campaign test ./campaigns/my-story
aigm campaign outline ./campaigns/my-story > RELEASE_OUTLINE.md
```

发布新版 Campaign 时同步更新 `package_version`，并保留 outline 供 review。
