# AIGM Author Kit Design

文档状态：**PROPOSED：面向 V1.1/V1.2 的剧本作者工具包设计方案**  
日期：2026-06-30  
适用范围：`rpg_engine`、Campaign Package、作者文档、剧本模板、CLI/MCP 辅助工具、AI 辅助创作工作流。  
输入依据：[`ux-design.md`](ux-design.md)、[`../../specs/campaign-package.md`](../../specs/campaign-package.md)、[`../../specs/kernel-requirements.md`](../../specs/kernel-requirements.md)、[`bug-report.md`](bug-report.md)。

## 1. 核心结论

AIGM Kernel 当前已经具备“工程上可运行的 Campaign Package 格式”，但还没有形成“作者可以轻松创作和维护剧本”的产品层。

现有能力偏向：

```text
作者写 YAML/Markdown
  -> campaign validate/test
  -> 报错
  -> 作者或 AI 反复修
```

这对高级用户可用，但对普通剧本作者仍然偏硬。Author Kit 的目标是把这条路径升级为：

```text
作者描述世界和玩法
  -> Author Kit 生成清晰骨架
  -> 作者/AI 填写内容
  -> doctor 用作者语言指出问题和修复路径
  -> outline 帮作者审查设定
  -> test 验证剧本能跑
  -> save init 进入试玩
```

一句话目标：

> **剧本作者应该像写跑团模组和世界书一样创作 Campaign Package，而不是像维护数据库导入文件一样工作。**

Author Kit 不是内核之外的重型独立软件。第一阶段应作为 AIGM Kernel 内置的作者工具层交付：CLI 命令、模板、文档、AI prompt、诊断输出和维护报告。

## 2. 与 Player UX 的关系

[`ux-design.md`](ux-design.md) 主要解决玩家和 GM 在游玩时的自然语言体验：

```text
玩家自然输入
  -> Intent Layer
  -> GM Ruling Layer
  -> Preview Layer
  -> Commit Layer
```

Author Kit 解决的是作者在游玩前和剧本维护期的体验：

```text
作者设定草稿
  -> Author Scaffold
  -> Author Draft
  -> Author Doctor
  -> Author Outline
  -> Campaign Test
  -> Playtest Save
```

两者共用原则：

- 宽进严出：输入可以自然，落盘必须结构化。
- 错误必须有 repair options。
- 普通人不应被迫理解内部契约。
- debug 信息应保留给高级用户，但不作为默认输出。
- 严格性保护世界一致性，不惩罚表达方式。

两者不应混成一个工具：

| 层 | 面向对象 | 主要问题 | 主要入口 |
|---|---|---|---|
| Player UX | 玩家、AI GM | 如何自然游玩、预演、确认、保存 | `aigm play act/query/preview/commit` |
| Author Kit | 剧本作者、内容维护者 | 如何创作、检查、维护、升级剧本 | `aigm campaign new/doctor/outline/test` |

## 3. 作者画像

### 3.1 普通作者

特征：

- 不会代码。
- 可能会写小说、跑团模组、世界观文档。
- 会使用 ChatGPT、Claude、Gemini 等外部 AI。
- 能编辑 Markdown，可能能接受简单 YAML，但不熟悉 schema、ID、引用和测试。

需要：

- 一个干净的空白剧本模板。
- 明确知道“我应该编辑哪些文件”。
- 能把自然语言设定交给 AI 转成结构化文件。
- 出错时看到“哪个设定缺了什么，怎么改”，而不是内部字段名堆栈。
- 不需要理解 SQLite、MCP、delta、projection、migration、package-lock。

### 3.2 AI 辅助作者

特征：

- 作者本人不直接写所有结构化内容。
- 会把规范、设定草稿、错误输出交给 AI 修订。
- 需要可复制、稳定、上下文友好的 prompt 和检查清单。

需要：

- `AUTHOR_AI_PROMPT.md`：告诉 AI 如何生成和修复 Campaign Package。
- `doctor --format json`：让 AI 能可靠读取错误、路径、建议和严重度。
- 分阶段任务模板：先写世界骨架，再写地点，再写角色，再写玩法。
- 明确禁止 AI 改运行态存档、隐藏 GM 信息和不该碰的生成物。

### 3.3 高级作者

特征：

- 熟悉 Git、YAML、JSON schema、命令行。
- 想维护大型剧本、版本升级、协作 review 和自动测试。
- 可能希望用脚本生成初稿，但不希望默认引入任意代码执行。

需要：

- 稳定 schema 和机器可读诊断。
- 可 diff 的推荐文件结构。
- 严格 smoke tests。
- package upgrade / reconcile 的明确边界。
- 字段所有权、definition/runtime 分离和兼容迁移路径。
- debug 输出、完整引用图、内容索引、覆盖率报告。

## 4. 设计目标

Author Kit 应达成：

1. 从零创建一个可运行剧本包。
2. 普通作者知道该编辑哪些文件、不该编辑哪些文件。
3. 外部 AI 可以基于稳定 prompt 生成初稿和修复错误。
4. 校验输出从“报错”升级为“诊断 + 修复建议 + 示例”。
5. 作者可以审查剧本设定总览，而不是只看 YAML。
6. 大型剧本可以按类型拆分、协作修改、Git review。
7. 高级作者可以使用 JSON 输出、schema、smoke test 和 CI。
8. 不要求作者写 Python、插件、resolver 或脚本化规则。
9. 不把 AI 生成器作为内核强依赖。
10. 不把存档包维护和剧本包创作混为一谈。

## 5. 非目标

Author Kit 第一阶段不做：

- 内置 AI 编剧模型。
- 一键生成完整大型世界。
- Web 创作 UI。
- 可视化地图编辑器。
- 作者自定义 Python 规则。
- 动态插件 SDK。
- 自动解决所有设定冲突。
- 自动升级所有已有玩家存档。
- 把自然语言剧本直接作为权威事实源。

这些可以作为后续独立工具或扩展能力，但不应进入 V1.1 的核心交付范围。

## 6. 推荐作者工作流

### 6.1 从零创作

```bash
aigm campaign new ./campaigns/my-story --template small-cn
cd ./campaigns/my-story
```

作者编辑：

```text
AUTHOR_NOTES.md
campaign.yaml
content/world_settings.yaml
content/locations.yaml
content/characters.yaml
content/items.yaml
content/projects.yaml
content/rules.yaml
content/clocks.yaml
content/random_tables.yaml
prompts/gm.md
templates/action.md
templates/query.md
tests/smoke.yaml
```

检查：

```bash
aigm campaign doctor ./campaigns/my-story
aigm campaign outline ./campaigns/my-story
aigm campaign test ./campaigns/my-story
```

试玩：

```bash
aigm save init ./campaigns/my-story ./saves/my-story-test
aigm play query ./saves/my-story-test scene
aigm play preview ./saves/my-story-test explore --target "..."
```

### 6.2 AI 辅助创作

推荐流程：

1. 作者用自然语言写 `AUTHOR_NOTES.md`。
2. 作者把 `AUTHOR_AI_PROMPT.md`、`CAMPAIGN_SPEC.md` 和 `AUTHOR_NOTES.md` 给外部 AI。
3. AI 只修改 `content/`、`prompts/`、`templates/`、`tests/` 和 `campaign.yaml` 中的作者字段。
4. 作者运行 `campaign doctor --format json`。
5. 作者把 JSON 诊断交给 AI 修复。
6. 作者运行 `campaign outline` 审查设定。
7. 作者运行 `campaign test`。
8. 作者试玩并迭代。

AI 辅助创作的关键限制：

- AI 不应编辑 `data/`、`cards/`、`snapshots/`、`memory/`、`reports/`。
- AI 不应创建 Python 文件或插件。
- AI 不应把未确认设定写成 confirmed 事实。
- AI 不应绕过 `campaign validate/test`。

### 6.3 已有剧本维护

常规修改：

```bash
aigm campaign outline ./campaigns/my-story --changed
aigm campaign doctor ./campaigns/my-story
aigm campaign test ./campaigns/my-story
```

发布前：

```bash
aigm campaign doctor ./campaigns/my-story --strict
aigm campaign test ./campaigns/my-story
aigm campaign outline ./campaigns/my-story --format markdown > RELEASE_OUTLINE.md
```

如果已有玩家存档，需要另走 package upgrade/reconcile 或受控迁移路径。Author Kit 可以提示风险，但不应在 V1.1 自动覆盖存档运行态。

## 7. 推荐目录结构

### 7.1 基础结构

```text
campaign/
  campaign.yaml
  AUTHOR_NOTES.md
  content/
    world_settings.yaml
    locations.yaml
    characters.yaml
    items.yaml
    projects.yaml
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

### 7.2 高级结构

大型剧本可以继续拆分：

```text
content/
  world/
    cosmology.yaml
    factions.yaml
    cultures.yaml
  locations/
    home.yaml
    region_north.yaml
    region_ruins.yaml
  characters/
    player.yaml
    allies.yaml
    factions.yaml
  items/
    resources.yaml
    equipment.yaml
    quest_items.yaml
  projects/
    crafting.yaml
    quests.yaml
  rules/
    safety.yaml
    travel.yaml
    social.yaml
  clocks/
    world_pressure.yaml
    faction_pressure.yaml
  random_tables/
    travel.yaml
    encounters.yaml
    crafting.yaml
```

`campaign.yaml.content.*` 支持多个相对路径：

```yaml
content:
  entities:
    - content/locations/home.yaml
    - content/locations/region_north.yaml
    - content/characters/player.yaml
    - content/characters/allies.yaml
    - content/items/resources.yaml
  rules:
    - content/rules/safety.yaml
    - content/rules/travel.yaml
  clocks:
    - content/clocks/world_pressure.yaml
  random_tables:
    - content/random_tables/travel.yaml
```

### 7.3 作者可编辑与不可编辑

作者可编辑：

```text
campaign.yaml
AUTHOR_NOTES.md
content/**
prompts/**
templates/**
tests/**
docs/**
```

作者通常不编辑：

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

如果这些目录出现在 Campaign Package 中，`campaign doctor` 应提示它们可能是生成物或存档产物。

## 8. CLI 设计

### 8.1 `campaign new`

目标：生成一个可立即 `validate/test` 的剧本骨架。

```bash
aigm campaign new ./campaigns/my-story --template small-cn
```

参数：

```text
--template blank|small-cn|small-en|advanced-cn|advanced-en
--id my-story
--name "我的剧本"
--force
--format markdown|json
```

行为：

- 创建目录结构。
- 写入最小 `campaign.yaml`。
- 写入示例 `content/*.yaml`。
- 写入 `AUTHOR_NOTES.md`。
- 写入 `AUTHOR_AI_PROMPT.md` 或提示复制全局 prompt。
- 写入最小 `tests/smoke.yaml`。
- 输出下一步命令。

成功输出示例：

```text
已创建剧本包：./campaigns/my-story

下一步：
1. 编辑 AUTHOR_NOTES.md，写下世界、主角、起始场景和玩法。
2. 编辑 content/locations.yaml 与 content/characters.yaml。
3. 运行 aigm campaign doctor ./campaigns/my-story。
4. 运行 aigm campaign test ./campaigns/my-story。
```

### 8.2 `campaign doctor`

目标：比 `validate` 更面向作者，提供严重度、解释、修复建议和例子。

```bash
aigm campaign doctor ./campaigns/my-story
aigm campaign doctor ./campaigns/my-story --strict
aigm campaign doctor ./campaigns/my-story --format json
```

检查范围：

- `campaign validate` 的所有结构检查。
- 推荐目录结构检查。
- 运行态字段泄漏检查。
- 生成物目录混入检查。
- ID 命名风格检查。
- 别名覆盖和中文搜索友好性检查。
- 能力声明和 smoke 覆盖检查。
- 起始场景可玩性检查。
- 重要实体摘要质量检查。
- hidden/hinted/known 使用检查。
- 大型单文件可维护性提示。
- world_setting/rule/clock 职责混淆提示。

输出结构：

```json
{
  "status": "needs_fix",
  "campaign_id": "my-story",
  "summary": {
    "errors": 2,
    "warnings": 5,
    "suggestions": 8
  },
  "issues": [
    {
      "severity": "error",
      "code": "MISSING_INITIAL_LOCATION",
      "file": "campaign.yaml",
      "path": "initial_location_id",
      "message": "起始地点 loc:start 没有在 content 中定义。",
      "why_it_matters": "玩家进入游戏时需要一个可渲染的起始场景。",
      "repair_options": [
        {
          "label": "创建起始地点",
          "example": "在 content/locations.yaml 添加 id: loc:start 的 location。"
        },
        {
          "label": "改用已有地点",
          "example": "把 initial_location_id 改为 loc:watch-camp。"
        }
      ]
    }
  ]
}
```

### 8.3 `campaign outline`

目标：把结构化剧本渲染成作者可读的设定总览，用于审稿、交给 AI、发布前检查。

```bash
aigm campaign outline ./campaigns/my-story
aigm campaign outline ./campaigns/my-story --format markdown
aigm campaign outline ./campaigns/my-story --view author
```

输出内容：

- 剧本名称、版本、能力。
- 起始场景。
- 主角和关键 NPC。
- 地点图谱。
- 世界设定摘要。
- 规则摘要。
- active clocks。
- 随机表列表。
- 项目/任务入口。
- smoke tests 覆盖。
- 维护风险。

示例：

```text
# 剧本总览：我的剧本

## 起始体验
- 玩家角色：沈砚
- 起始地点：空地/家
- 开局可做：查看基地、找夏娃、检查农田、去小溪

## 设定覆盖
- 地点：12
- 角色：5
- 物品/资源：28
- 规则：14
- 进度钟：6

## 维护提醒
- content/entities.yaml 超过 2000 行，建议按类型拆分。
- combat 已声明但 smoke test 未覆盖。
```

### 8.4 `campaign explain`

目标：解释某个字段、实体、capability 或错误码，降低作者学习成本。

```bash
aigm campaign explain capability:combat
aigm campaign explain field:visibility
aigm campaign explain error:MISSING_REFERENCE
```

示例：

```text
visibility 控制玩家是否能看到对象：
- known：玩家已知，可进入查询和场景。
- hinted：玩家知道线索，但不一定知道完整事实。
- hidden：只给 GM/维护视图，不能泄漏到玩家查询。
```

### 8.5 `campaign split`

目标：帮助高级作者把大文件拆成推荐结构。

```bash
aigm campaign split ./campaigns/my-story --by type --dry-run
aigm campaign split ./campaigns/my-story --by type --apply
```

V1.1 可先只提供 `--dry-run` 建议，不自动改文件。V1.2 再实现可逆自动拆分。

### 8.6 `campaign check-ai`

目标：检查外部 AI 生成内容常见问题。

```bash
aigm campaign check-ai ./campaigns/my-story
```

检查：

- 编造了未引用的 ID。
- 把隐藏设定写进 player-facing summary。
- details 里塞入长篇散文但缺少结构字段。
- 同一 NPC 多个 ID。
- 规则和世界设定互相重复。
- smoke test 只检查文字片段，没有覆盖玩法能力。
- 所有对象都 declared known，缺少 hinted/hidden 的信息层次。

## 9. 模板设计

### 9.1 `blank`

适合高级作者：

- 最小可运行。
- 内容极少。
- 注释少。
- 便于从零建立自己的结构。

### 9.2 `small-cn`

适合普通中文作者：

- 中文字段示例。
- 1 个起始地点。
- 1 个玩家角色。
- 2 个 NPC。
- 2 个地点。
- 3 条规则。
- 1 个 clock。
- 1 个随机表。
- query + rest/explore smoke tests。

### 9.3 `small-en`

对应 `small-cn` 的英文版本，便于发布和测试。

### 9.4 `advanced-cn`

适合大型剧本作者：

- 按类型拆分目录。
- factions、projects、items、routes、world_settings 示例齐全。
- 多 capability smoke tests。
- `docs/` 和 `AUTHOR_NOTES.md` 示例。
- Git/CI 友好。

### 9.5 `migration-template`

适合从旧世界书或 Markdown 存档迁移：

- `source_notes/` 放旧文档。
- `AUTHOR_NOTES.md` 记录迁移假设。
- `content/` 放结构化结果。
- `tests/smoke.yaml` 保证起始查询和核心玩法能跑。

## 10. AUTHOR_AI_PROMPT

应新增 `AUTHOR_AI_PROMPT.md`，用于作者复制给外部 AI。

核心要求：

```text
你是 AIGM Campaign Package 剧本整理助手。

目标：
- 把作者的世界观、角色、地点、规则和玩法整理为 AIGM V1 Campaign Package。
- 只修改作者可编辑文件。
- 保持 YAML 可解析、ID 稳定、引用存在、visibility 正确。
- 不写 Python，不创建插件，不编辑存档运行产物。

工作方式：
1. 先阅读 AUTHOR_NOTES.md 和 campaign.yaml。
2. 先输出计划，再修改内容。
3. 每次修改后提醒作者运行 aigm campaign doctor。
4. 如果 doctor 返回 JSON，优先修 error，再修 warning。
5. 不确定的设定写入 unknowns 或 hinted，不要写成 confirmed。
6. 不要为剧情推进修改存档；剧情推进属于 Save Package 和 play commit。

输出约束：
- YAML 使用稳定 ID。
- 地点 id 用 loc:...
- 玩家角色用 pc:...
- NPC 用 npc:... 或 char:...
- 规则用 rule:...
- 进度钟用 clock:...
- 随机表用 table:...
```

AI prompt 应包含：

- 推荐目录结构。
- 常用实体模板。
- ID 命名规则。
- visibility 解释。
- smoke test 示例。
- 常见错误和修复方式。
- “不要做”的清单。

## 11. 作者文档

建议新增：

```text
AUTHOR_GUIDE.md
AUTHOR_AI_PROMPT.md
AUTHOR_MAINTENANCE.md
AUTHOR_EXAMPLES.md
```

### 11.1 `AUTHOR_GUIDE.md`

面向普通作者：

- 什么是 Campaign Package。
- 什么是 Save Package。
- 作者该编辑哪些文件。
- 如何写地点、角色、物品、规则、clock、随机表。
- 如何用 AI 辅助。
- 如何运行 doctor/test。
- 如何试玩。

### 11.2 `AUTHOR_MAINTENANCE.md`

面向维护：

- 如何改名、补摘要、加别名。
- 如何新增地点和路线。
- 如何新增 NPC。
- 如何新增能力和 smoke test。
- 如何发布新版本。
- 如何避免覆盖玩家存档状态。

### 11.3 `AUTHOR_EXAMPLES.md`

面向学习：

- 小型调查剧本。
- 生存建设剧本。
- 社交势力剧本。
- 战斗防卫剧本。
- 解谜探索剧本。

每个例子都应说明：

- 需要哪些 capabilities。
- 起始体验是什么。
- 最少需要哪些 content 文件。
- smoke tests 应覆盖什么。

## 12. 诊断模型

Author Kit 需要比当前 `issues_from_messages` 更丰富的作者诊断模型。

建议结构：

```json
{
  "severity": "error|warning|suggestion|info",
  "audience": "author|ai|advanced|debug",
  "code": "MISSING_REFERENCE",
  "title": "引用不存在",
  "message": "npc:mira 位于 loc:camp，但 loc:camp 没有定义。",
  "why_it_matters": "角色无法进入场景查询，相关行动也无法解析。",
  "file": "content/characters.yaml",
  "path": "entities[3].location_id",
  "repair_options": [
    {
      "label": "创建地点 loc:camp",
      "kind": "add_record",
      "example": "在 content/locations.yaml 添加地点。"
    },
    {
      "label": "改成已有地点",
      "kind": "edit_field",
      "example": "location_id: loc:watch-camp"
    }
  ],
  "debug": {
    "raw_message": "entity[3].location_id: missing entity loc:camp"
  }
}
```

严重度定义：

| 严重度 | 含义 | validate/test |
|---|---|---|
| `error` | 剧本不能可靠运行 | 必须失败 |
| `warning` | 能运行，但作者体验或维护风险高 | 默认不失败，`--strict` 失败 |
| `suggestion` | 改进建议 | 不失败 |
| `info` | 统计和说明 | 不失败 |

## 13. 内容质量检查

### 13.1 可玩性检查

起始场景至少应有：

- 一个 known 起始地点。
- 一个玩家角色。
- 一段可读场景 summary。
- 至少 2 个可行动入口：NPC、地点出口、项目、资源、线索或 routine。
- query scene smoke test。

### 13.2 可维护性检查

提示项：

- 单个 YAML 文件超过建议行数。
- 大量实体缺 alias。
- 中文剧本实体没有中文 alias 或短别名。
- summary 太长，像正文段落。
- details 中混入大量不可结构化散文。
- world_setting/rule/entity 重复表达同一事实。
- hidden 信息出现在 known summary。

### 13.3 玩法覆盖检查

如果声明 capability：

| Capability | 推荐 smoke |
|---|---|
| `query` | `query scene`、`query entity` |
| `travel` | 合法 travel preview |
| `social` | 与当前位置 NPC 交谈 |
| `combat` | 带 target/weapon/ready_state 的 combat preview |
| `gather_search` | 合法采集或盘点 routine |
| `project_task` | 查询或预演一个项目 |
| `random_table` | 固定骰值或 deterministic table smoke |
| `rest_time` | rest preview |

### 13.4 设定一致性检查

检查：

- 地点引用完整。
- NPC location 合理。
- route 两端存在。
- clock 与规则或世界设定有关联。
- project 所需材料存在。
- faction/relationship 双方存在。
- hidden object 不被 player-facing 文案泄漏。

## 14. 高级作者能力

### 14.1 JSON 输出

所有 Author Kit 命令应支持：

```bash
--format markdown|json
```

JSON 用于：

- CI。
- 外部 AI 修复。
- 编辑器插件。
- 高级脚本。

### 14.2 CI 示例

```bash
aigm campaign doctor ./campaigns/my-story --strict --format json
aigm campaign test ./campaigns/my-story --format json
```

### 14.3 字段所有权提示

doctor 应能提示：

- 这个字段是作者定义。
- 这个字段会在运行中变化。
- 修改它可能影响已有存档。
- 建议通过 package upgrade 或 save patch 处理。

示例：

```text
你修改了 npc:mira.location_id。这个字段在存档运行中可能已经变化。
如果这是初始剧本修订，可以改；如果要更新已有玩家存档，需要迁移计划。
```

### 14.4 内容索引

`campaign outline --format json` 应输出：

- entity counts by type。
- references graph。
- capability coverage。
- smoke coverage。
- hidden/known distribution。
- largest files。
- duplicate aliases。

## 15. 与 Save Package 的边界

Author Kit 必须反复强调：

- Campaign Package 定义初始世界和玩法。
- Save Package 保存某次游玩的当前事实。
- 作者修剧本不等于修改玩家存档。
- 玩家进度不应通过编辑 campaign YAML 推进。
- 运行态事实以 `data/game.sqlite` 为准。

当用户把 Save Package 当 Campaign Package 传给 `campaign doctor` 时，应输出：

```text
这个目录看起来是 Save Package，不是 Campaign Package。

你可以：
1. 对存档运行 aigm save validate。
2. 找到来源剧本 source_campaign_path。
3. 如果你要修剧本，请编辑 Campaign Package。
4. 如果你要维护当前存档，请使用 aigm save patch 或 play commit。
```

## 16. 实施计划

### P0：文档和模板

1. 新增 `AUTHOR_GUIDE.md`。
2. 新增 `AUTHOR_AI_PROMPT.md`。
3. 新增 `examples/blank_campaign`。
4. 新增 `examples/small_cn_campaign`。
5. 更新 `README.md`，加入作者入口。
6. 更新 `CAMPAIGN_SPEC.md`，区分最小结构、推荐结构、高级结构。

验收：

```bash
aigm campaign validate ./examples/blank_campaign
aigm campaign test ./examples/small_cn_campaign
```

### P1：`campaign new` 和 `campaign doctor`

1. `campaign new` 支持模板复制和 id/name 替换。
2. `campaign doctor` 包装 validate/test 诊断。
3. author-facing issue model。
4. `--format json`。
5. 运行态/生成物混入检查。
6. 大文件和推荐结构提示。

验收：

```bash
aigm campaign new /tmp/aigm-author-test --template small-cn
aigm campaign doctor /tmp/aigm-author-test
aigm campaign test /tmp/aigm-author-test
```

### P2：`campaign outline` 和 AI 辅助闭环

1. `campaign outline` markdown/json。
2. `campaign explain`。
3. `campaign check-ai`。
4. doctor 输出 repair options。
5. AUTHOR_AI_PROMPT 与 doctor JSON 对齐。

验收：

```bash
aigm campaign outline ./examples/small_cn_campaign
aigm campaign doctor ./examples/small_cn_campaign --format json
```

### P3：高级维护

1. `campaign split --dry-run`。
2. 字段所有权提示。
3. package upgrade 风险报告。
4. 内容引用图。
5. CI 示例和编辑器插件接口。

## 17. 测试计划

新增测试建议：

```text
tests/test_author_kit_new.py
tests/test_author_kit_doctor.py
tests/test_author_kit_outline.py
tests/test_author_ai_prompt_contract.py
```

必须覆盖：

- `campaign new` 生成的每个模板都能 validate/test。
- `doctor` 能识别缺引用、缺 smoke、运行态目录混入、Python 文件混入。
- `doctor --format json` 输出稳定 schema。
- `outline` 不泄漏 hidden 详细信息到 author/player 默认视图。
- 中文模板包含中文 alias 和自然语言 smoke。
- AI prompt 明确禁止编辑存档生成物。

## 18. 成功指标

建议指标：

| 指标 | 目标 |
|---|---:|
| 新作者从安装到跑通小剧本 | <= 30 分钟 |
| `campaign new --template small-cn` 首次 test 通过率 | 100% |
| doctor error 带 repair_options 比例 | 100% |
| 普通作者必须理解 SQLite/MCP/delta 的步骤 | 0 |
| 外部 AI 根据 doctor JSON 修复结构错误成功率 | > 80% |
| 大型剧本单文件超过 2000 行未提示比例 | 0 |
| capability 无 smoke 覆盖漏报率 | 0 |

## 19. 风险与取舍

### 19.1 文档过多

风险：作者看到太多文档仍然会怕。

取舍：

- `AUTHOR_GUIDE.md` 面向普通作者，短而实用。
- `CAMPAIGN_SPEC.md` 保持规范性。
- `AUTHOR_AI_PROMPT.md` 面向 AI，不要求人完整阅读。
- 高级内容放 `AUTHOR_MAINTENANCE.md`。

### 19.2 模板变成新负担

风险：模板太复杂，作者不知道删什么。

取舍：

- `blank` 必须极简。
- `small-cn` 必须小而完整。
- `advanced-cn` 才展示复杂结构。

### 19.3 doctor 变成第二套 validator

风险：validate 和 doctor 逻辑重复。

取舍：

- `validate` 负责硬规范。
- `doctor` 复用 validate 结果并补充作者体验检查。
- 共享 issue model，避免规则分叉。

### 19.4 AI 修复误改设定

风险：外部 AI 为了通过校验而改坏世界观。

取舍：

- AI prompt 要求先解释计划再修改。
- doctor 只建议，不自动应用。
- outline 帮作者审稿。
- 高风险字段给出维护提示。

## 20. 最小可交付版本

最小有价值版本不是完整命令集，而是：

```text
AUTHOR_GUIDE.md
AUTHOR_AI_PROMPT.md
examples/small_cn_campaign
aigm campaign new --template small-cn
aigm campaign doctor
```

只要这五项成立，普通作者就可以：

1. 创建剧本。
2. 让 AI 帮忙填内容。
3. 用 doctor 发现结构问题。
4. 用 outline 或 test 确认可玩。
5. 初始化存档开始试玩。

这会把 AIGM Kernel 从“有剧本包规范的内核”推进到“普通作者可以实际创作剧本的工具链”。
