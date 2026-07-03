# AIGM 新内容生成、候选素材与内容维护机制

文档状态：设计与实现对照，P0/P1 已在 AIGM Kernel V1 落地，P2 仍为后续机制设计  
适用范围：Campaign Package、Save Package、GMRuntime、AI GM 客户端  
相关实现：`palette.py`、`content_delta.py`、`content_factory.py`、`world_settings`、`random_tables`、`unknown_lead`、`validate_delta`、`commit_turn`

## 1. 目标

本机制解决一个核心问题：AIGM 需要开放世界的自由度，但不能让 AI 随口创造的势力、文明、材料、人物、规则直接变成世界事实。

目标是把新内容分成三层：

1. 剧本包预设的权威内容。
2. 可由 AI 按条件投放的候选素材。
3. 运行中通过 delta 审核后进入存档的新增事实。

AI 可以即兴描述，但不能绕过结构化保存。所有会影响后续玩法的新增实体、线索、资源、势力、路线、世界规则，都必须经过候选、确认、delta、校验、提交这条链路。

## 2. 设计原则

### 2.1 剧本包是世界宪法

以下内容默认应由 Campaign Package 明确写好：

- 核心世界观、文明结构、魔法/科技规则。
- 主要势力、主要族群、关键 NPC。
- 核心材料、关键资源、特殊生态。
- 重要地点、路线、区域边界。
- 主线线索、隐藏真相、危险等级。
- 玩家能使用的 capability。
- 重要随机表、进度钟和 GM 风格。

这些内容不应该由普通行动回合临时创造。若运行中确实需要新增，应走内容维护 delta。

### 2.2 AI 是即兴执行者，不是事实裁判

AI 可以做：

- 描述感官细节。
- 给出低风险环境颜色。
- 根据已加载事实推断合理选择。
- 从 palette/random table 中选择候选。
- 起草新实体或新设定的 content delta。

AI 不可以直接做：

- 创造新文明并当作已存在事实。
- 创造重大势力并让其立刻影响局势。
- 发明核心材料并直接加入库存。
- 替玩家确认发现、交易、承诺或风险接受。
- 把 hidden 内容直接说给玩家。
- 绕过 preview/validate/commit 保存事实。

### 2.3 新事实必须有来源

每个新增事实至少要能回答：

- 玩家如何接触到它？
- 它从哪个候选、线索、随机表或 GM 维护动作而来？
- 它是否需要验证、采样、研究、询问或交易确认？
- 它写入后会影响哪些行动类型？
- 它是否改变世界设定、地图、资源、关系或进度钟？

不能回答这些问题的内容，只能作为临时叙事颜色，不能保存为实体。

## 3. 事实阶梯

所有新内容按以下阶梯推进，不能跳级。

| 阶段 | 名称 | 是否事实 | 典型写法 | 能做什么 |
|---:|---|---|---|---|
| 0 | 禁止内容 | 否 | 越权、系统命令、读文件、改存档 | 直接 blocked |
| 1 | 叙事颜色 | 否 | 风声、泥水、路人神情 | 可描述，不保存 |
| 2 | 候选素材 | 否 | palette 条目、随机表结果 | 可提示、可伏笔 |
| 3 | 未知线索 | 部分 | `unknown_lead`、`ref:*` hinted | 可被探索或询问 |
| 4 | 待确认实体 | 部分 | `visibility: hinted`、`needs_gm_resolution` | 需要采样/研究/交易/接触 |
| 5 | 已确认运行事实 | 是 | turn delta 的 `upsert_entities`/`events` | 进入当前存档 |
| 6 | 剧本权威内容 | 是 | campaign YAML 或 content delta 审核后同步 | 可复用、可测试、可维护 |

## 4. 内容所有权矩阵

| 内容类型 | 默认归属 | AI 可否临时生成 | 正式写入方式 | 备注 |
|---|---|---:|---|---|
| 世界底层规则 | 剧本包 | 否 | `upsert_world_settings` 或人工改包 | 高影响 |
| 文明/大势力 | 剧本包 | 仅候选草案 | content delta | 需要目标、地盘、资源、关系 |
| 小型派系/队伍 | 剧本包或 palette | 可以草案 | content delta 或 turn delta | 影响关系和社交 |
| 关键 NPC | 剧本包 | 否 | content delta | 需要动机、位置、关系 |
| 临时 NPC | AI | 可以 | turn delta 可选 | 若会复现才保存 |
| 地点/路线 | 剧本包 | 仅线索 | `upsert_entities` + `upsert_routes` | 地图结构需审核 |
| 材料/资源 | 剧本包或 palette | 可以候选 | turn delta 或 content delta | 入库存必须结构化 |
| 生物/物种 | 剧本包或 palette | 可以线索 | content delta | 需要栖息地、行为、风险 |
| 遭遇 | random table/palette | 可以 | event + clock/entity 更新 | 不一定成为实体 |
| 传闻 | random table | 可以 | event，可不建实体 | 不等于事实 |
| 线索 | 剧本包或探索生成 | 可以 unknown lead | event/ref entity | hidden 不能直出 |
| 项目/建设 | 剧本包或运行中 | 可以草案 | project entity + craft/routine delta | 需要阶段和任务 |

## 5. 候选素材 Palette

### 5.1 目录约定

推荐在剧本包中新增：

```text
content/
  palettes/
    materials.yaml
    species.yaml
    factions.yaml
    encounters.yaml
    locations.yaml
```

当前 palette loader 已能自动读取 `content/palettes/*.yaml`，也支持读取 `campaign.yaml.content.palettes` 中声明的文件。P1 已让 V1 campaign validator 和 schema 正式接受 `content.palettes`，因此作者可以显式声明 palette 文件；未声明时仍可依靠自动发现。

### 5.2 Palette 条目字段

推荐统一字段：

```yaml
materials:
  - id: pal:mat:moon-herb-variant
    name: 银边月白草
    summary: 月白草的罕见变体，叶缘带银光，可能用于更稳定的敷料。
    rarity: uncommon
    locations: [loc:camp]
    biomes: [riverside camp]
    intents: [gather, explore, craft]
    discovery:
      mode: confirm_required
      clue_text: 草丛里有几片叶缘发亮的月白草。
      confirm_methods: [观察, 小量采样, 询问熟悉草药的人]
    unlock:
      min_day: 1
      allow_clue_when_locked: true
    risks:
      - 与普通月白草混淆会降低药效。
    save_as:
      type: material
      category: herb
      default_quantity: 1
      unit: 小束
```

`discovery.mode` 建议只使用：

- `direct`：可直接作为低风险事实投放。
- `confirm_required`：只能先提示，确认后才能保存。
- `clue_only`：只能作为伏笔，不能给资源收益。

`unlock` 可约束：

- 游戏天数。
- 地点。
- 生物群系。
- 进度钟阶段。
- 已发现前置线索。

### 5.3 Palette 状态解释

内核已有五类状态：

- `available`：可投放。适合普通资源、低风险遭遇、小型细节。
- `confirm_required`：需确认。适合材料、人物、物种、派系。
- `clue_only`：仅线索。适合隐藏地点、稀有文明、危险生物。
- `locked`：锁定。条件未满足，不应出现。
- `out_of_context`：不适用。地点、生态或行动不匹配。

AI 只能把 `available` 当作可保存候选。`confirm_required` 和 `clue_only` 必须先进入线索阶段。

## 6. 随机表 Random Tables

随机表用于产生不可预测性，不用于绕过世界设定。

推荐表类型：

| 表 | 用途 | 是否可直接成事实 |
|---|---|---:|
| 风险细节表 | 旅行、探索、战斗的即时环境压力 | 通常是 event |
| 传闻表 | NPC 或营地口耳相传 | 否，默认是未证实信息 |
| 遭遇表 | 途中或夜间事件 | 视条目而定 |
| 代价表 | 失败、部分成功、拖延的后果 | 是，但需 delta |
| 发现表 | 探索可见线索 | 通常先 hinted |
| NPC 反应表 | 社交态度和临时要求 | 关系变化需 delta |
| 采集产出表 | 资源数量、品质、风险 | 入库存需 delta |
| 制作事故表 | craft 失败或额外代价 | 消耗/损坏需 delta |

随机表结果必须记录为 `random_table_roll` 或相关行动 event。AI 不能私自重掷或改结果。

## 7. 运行时新内容流程

### 7.1 探索未知事物

玩家输入类似：

```text
调查奇怪声音
看看桥下是什么
找山岗上的信号痕迹
```

流程：

1. `start_turn` 判断为 `explore`。
2. 若目标不是已知可见实体，走 `unknown_lead`。
3. `preview_action` 生成探索草案，但 payload 必须含 `needs_gm_resolution=true`。
4. AI 只能描述可观察迹象，不得确认 hidden 真相。
5. 若需要保存，turn delta 写入 event 或 hinted `ref:*`。
6. 后续通过再次探索、社交询问、采样、制作测试等行动确认。

### 7.2 发现新材料

流程：

1. `gather` 或 `explore` 触发当前地点 palette 查询。
2. 若 palette 有 `available` 材料，可作为本回合候选。
3. 若是 `confirm_required`，先描述线索，不能直接加入库存。
4. 玩家确认采样后，turn delta 可写：
   - event：采样过程。
   - `upsert_entities`：材料实体或库存物品。
   - `tick_clocks`：暴露、污染、干旱、生态扰动等。
5. 若该材料会长期影响世界或配方，应转 content delta 审核后进入剧本/存档内容库。

### 7.3 遇见新人物

临时 NPC 可以不保存。只有满足以下任一条件才保存：

- 玩家获得姓名。
- 发生交易、承诺、冲突或关系变化。
- 该 NPC 会再次出现。
- 该 NPC 持有线索、路线、资源或派系信息。

保存方式：

- 小人物：turn delta `upsert_entities`，`type: character`，`visibility: known/hinted`。
- 关键人物：content delta 或人工改剧本包。
- 隐藏人物：先 `visibility: hidden` 或仅通过 hinted reference 暗示，不能玩家可见直出。

### 7.4 新势力或文明

新势力/文明属于高影响内容，默认不能由普通行动直接确认。

允许的最低路径：

1. 传闻或符号：random table / explore event。
2. 线索实体：`ref:*` 或 hinted `faction_state`。
3. 多源确认：社交询问、遗迹证据、物品标记、路线发现。
4. content delta 创建正式 `faction` 或 `faction_state`。
5. 补关系、目标、资源、敌友、可见性和相关 clock。

新文明必须同时补：

- 核心世界设定。
- 至少一个势力/代表群体。
- 可见线索或接触方式。
- 与现有地点/路线/资源的关系。
- 不泄露给玩家的 hidden 部分。

### 7.5 新地点和路线

新地点默认先作为未知线索或远景出现。

正式落地需：

- `upsert_entities` 创建 `type: location`。
- 若可旅行，必须 `upsert_routes` 创建路线。
- 地点需有 `biome`、`safety_level`、`description_short`、`resources`、`exits`。
- 旅行耗时和危险必须明确。

禁止只在叙事里说“你到了一个新城镇”但不更新 `current_location_id` 和路线。

## 8. 内容维护 Delta

### 8.1 使用场景

以下情况应使用 content delta，而不是普通 turn delta：

- 新增长期稳定世界设定。
- 新增大势力、文明、关键 NPC、物种。
- 新增地图路线或重要地点。
- 新增规则、能力边界或全局约束。
- 把多次运行中确认的内容沉淀为可复用内容。

### 8.2 Content Delta 允许写入

当前 schema 支持：

- `upsert_entities`
- `upsert_routes`
- `upsert_rules`
- `upsert_world_settings`
- `meta`

应用时会先执行 `validate_content_delta`，失败则不写入。

### 8.3 推荐审核清单

应用 content delta 前检查：

- ID 是否稳定且命名空间正确。
- 是否引用了不存在的实体。
- 是否把 hidden 内容暴露成 known。
- 是否和已有 world_setting/rule 冲突。
- 是否需要 smoke test。
- 是否需要新增 random table 或 palette 条目。
- 是否影响 capability 声明。
- 是否需要同步到 packaged example。

## 9. 可见性规则

所有新内容必须显式选择可见性：

- `known`：玩家已确认知道。
- `hinted`：玩家知道迹象，但不知道完整事实。
- `hidden`：玩家不可见，只能在 GM/maintenance 视图或条件满足后使用。

规则：

- 新文明、新势力、新敌人默认不能直接 `known`，除非玩家已经正面接触。
- 传闻默认不等于 `known` 事实。
- 随机表结果若只是传闻，应写成 event 或 hinted reference。
- hidden 不能进入玩家查询、场景和普通回复。

## 10. AI GM 回复规范

当 AI 想引入新内容时，必须使用以下措辞层级：

- 叙事颜色：`你注意到...`、`看起来...`
- 未确认线索：`可能...`、`像是...`、`需要进一步确认...`
- 候选素材：`这可以作为候选发现，但需要采样/询问后保存。`
- 正式事实：只有在 delta commit 后才能说 `你确认...`、`现在已知...`、`你获得...`

禁止句式：

- `你发现了一个从未提过的强大文明，并确认他们控制这里。`
- `你的背包里多了三份新材料。` 但没有 `upsert_entities`。
- `这个 hidden NPC 告诉你...` 但玩家上下文不可见。
- `我直接保存这个设定。` 但没有 validate/commit。

## 11. 推荐命令流程

查询候选素材：

```bash
aigm palette suggest ./saves/my-run --kind material --location loc:camp --intent gather
```

预演探索未知线索：

```bash
aigm play preview ./saves/my-run explore --target "奇怪声音" --unknown-lead true --approach careful
```

验证内容维护 delta：

```bash
aigm content validate-delta ./saves/my-run ./draft_content_delta.json
```

应用内容维护 delta：

```bash
aigm apply-content-delta ./saves/my-run ./draft_content_delta.json
```

保存正式行动：

```bash
aigm play validate-delta ./saves/my-run ./turn_delta.json
aigm play commit ./saves/my-run ./turn_delta.json --proposal-json ./turn_proposal.json
```

## 12. 作者工作流

### 12.1 开局前

作者应准备：

- `world_settings.yaml`：世界规则和核心限制。
- `entities/locations/characters/items/projects/references`：初始事实。
- `relationships.yaml`：初始关系。
- `clocks.yaml`：主要压力。
- `random_tables.yaml`：风险、传闻、代价、发现。
- `content/palettes/*.yaml`：可被 AI 投放的候选素材。
- `tests/smoke.yaml`：覆盖声明的 capabilities。

### 12.2 游玩中

AI GM 应：

1. 先查当前场景。
2. 对行动运行 preview。
3. 需要新内容时先查 palette/random table。
4. 查不到时使用 `unknown_lead`，不直接确认。
5. 玩家确认后写 turn delta。
6. 稳定内容用 content delta 维护。

### 12.3 游玩后维护

维护者应定期：

- 审计新增实体是否缺别名、用途、风险、发现方式。
- 把重复出现的临时 NPC/地点沉淀为剧本内容。
- 把临时材料补入 palette 或正式 item/material。
- 把运行中形成的长期规则补入 `world_settings` 或 `rules`。
- 给新增 capability 补 smoke test。

## 13. 分阶段落地计划

本计划基于当前仓库能力，而不是理想状态假设。

当前已经存在的基础：

- `GMRuntime` 已有 `start_turn`、`preview_action`、`validate_delta`、`commit_turn`，普通玩家事实写入可以被 preview/validate/proposal commit 管住。
- 行动 resolver 已覆盖 `explore`、`travel`、`social`、`gather`、`craft`、`routine`、`rest`、`combat`、`random_table`。
- `palette.py` 已能读取 `content/palettes/*.yaml`，并根据地点、生态、意图、解锁条件给出 `available`、`confirm_required`、`clue_only`、`locked`、`out_of_context`。
- context collector 已能在行动上下文中加入 palette 候选；`auto` 模式会覆盖 `gather`、`travel` 和带探索词的输入。
- `random_table` 已由内核掷出结果，并能生成 `random_table_roll` 或 `dice_roll` 审计事件。
- `content_delta` 已能校验并应用 `upsert_entities`、`upsert_routes`、`upsert_rules`、`upsert_world_settings`、`meta`。
- `content_factory` 已能生成 material/location/species/faction/recipe/project/npc 的通用 content delta 草案。
- `proposal validate` 仍可用于一次性校验；持久 `proposal_queue` 已落库，并提供 `create/list/review/apply/report/batch-review/rollback-plan`。
- `discovery_states` 已落库；palette/unknown-lead 事件提交后会派生发现状态，并进入 context builder 的 `discovery_states` section。
- `campaign doctor`、`campaign check-ai`、`campaign outline` 和 `campaign validate` 已覆盖作者体验与基础 palette 可见性；更细诊断码仍可继续增强。

P0/P1 已落地的基础：

- `small_cn_campaign` 已声明 `gather_search`，并用 smoke test 覆盖采集 preview。
- 示例剧本包已加入 `content/palettes/*.yaml`，包含材料、遭遇、势力、地点和物种候选。
- 随机表已扩展到探索发现、采集产出、采集代价、社交反应、旅行风险和营地传闻等路径。
- `gather`、`explore`、`social`、`travel`、`craft` resolver 已能消费 `palette_id`，并在 delta payload 中保留候选来源。
- V1 validator 和 schema 已支持 `campaign.yaml.content.palettes`，也会验证 palette 字段、引用、状态和保存类型。
- `content validate-delta` 已支持 warnings，高影响 entity/route/rule/world_setting 会提示 review 风险。
- `content from-palette` 已能把 palette 候选转成带 `review_required` 的 content delta 草案。
- `apply-content-delta --strict-review` 会阻止未人工 review 的高影响内容，并把 proposal 入队。
- `campaign outline` 已能展示 palette 数量分布，authoring 流程能看见候选素材层。

仍未完整产品化的缺口：

- `memory_update`、`alias_suggestion` 和 `turn_delta` proposal 已能入队/审核，但 apply/revert 规则仍需按各自写入通道设计。
- `discovery_states` 已能记录和召回线索，但多源确认、归档、维护报告和过期线索清理仍需补完整。
- `content from-palette` 还没有直接 `--enqueue` 入口，目前需要先输出 delta 再创建 proposal。
- composite plan 目前主要返回 plan/repair options，还不是原子化多步 commit。
- high-impact warning 目前主要是字符串 warning，后续可补结构化风险字段，方便 UI 消费。

### 13.1 P0 目标：用剧本包和提示词先跑起来

P0 不改内核。目标是让当前系统已经支持的机制真正有内容可用，并把 AI 的自由度限制在现有边界内。

#### P0.1 Capability 契约状态

`small_cn_campaign` 当前已声明 `gather_search`，并通过 smoke test 覆盖采集 preview。后续维护时需要保持：

- `campaign.yaml.capabilities` 与 smoke tests 一致。
- 开局场景、物品摘要和 GM prompt 不承诺未声明 capability 的玩法。
- 采集目标要么是可见实体，要么通过 palette 作为候选线索，不直接承诺入库存。

验收命令：

```bash
aigm campaign validate examples/small_cn_campaign
aigm campaign test examples/small_cn_campaign
```

完成标准：

- `campaign validate` 通过。
- `campaign test` 覆盖已声明 capability。
- UX 模拟中 `找月白草` 不再处于“内容承诺存在但 capability 缺失”的状态。

#### P0.2 新增候选素材库

新增目录：

```text
examples/small_cn_campaign/content/palettes/
  materials.yaml
  encounters.yaml
  factions.yaml
  locations.yaml
  species.yaml
```

当前实现支持两种接入方式：

- 在 `campaign.yaml.content.palettes` 中显式列出 palette 文件，适合正式剧本包和 CI 校验。
- 省略 manifest 声明，由 `palette.py` 自动扫描 `content/palettes/*.yaml`，适合快速试验。

示例剧本包使用显式声明，以便 `campaign validate` 能更早暴露坏引用和缺字段。

首批内容建议：

| 文件 | 首批数量 | 主要用途 |
|---|---:|---|
| `materials.yaml` | 8-12 | 采集、制作、交易、疗伤 |
| `encounters.yaml` | 6-10 | 旅行、夜间、桥边、营地压力 |
| `factions.yaml` | 3-5 | 传闻、符号、巡逻痕迹，不直接确认大势力 |
| `locations.yaml` | 3-5 | 山岗、桥下、旧路、河湾等未知地点线索 |
| `species.yaml` | 3-5 | 可观察痕迹、危险生态、材料来源 |

每个 palette 条目必须写：

- `id`：使用 `pal:<kind>:<slug>`，例如 `pal:mat:silver-moon-herb`。
- `name`、`summary`、`rarity`。
- `locations` 或 `biomes`，至少一个。
- `intents`，例如 `[gather, explore, craft]`。
- `discovery.mode`，只能用 `direct`、`confirm_required`、`clue_only`。
- `discovery.clue_text`。
- `discovery.confirm_methods`。
- `risks`。
- 对材料、物种、地点这类可沉淀内容，补 `save_as`。

P0 默认策略：

- 普通低价值素材可以 `direct`。
- 新材料、未知物种、小派系线索默认 `confirm_required`。
- 新势力、新文明、隐藏地点默认 `clue_only`。
- 不要在 palette 里把 hidden 真相写进 `summary`；hidden 只放在 GM/maintenance 可见内容或后续 content delta。

手工验收命令：

```bash
aigm save init examples/small_cn_campaign /tmp/aigm-small-cn-save --force
aigm palette suggest /tmp/aigm-small-cn-save --kind material --location loc:camp --intent gather
aigm play start-turn /tmp/aigm-small-cn-save --user-text "在营地附近找草药" --submode gather
```

完成标准：

- `palette suggest` 能返回候选。
- `start-turn` 的 context 中出现 `Palette Candidates`。
- 候选文本明确说明“候选不是事实”。

#### P0.3 扩充随机表

当前随机表只适合演示，不足以支撑 AIGM 的持续游玩。P0 需要把 `content/random_tables.yaml` 扩成可用的 GM 工具箱。

建议表：

| 表 ID | 用途 | 条目建议 |
|---|---|---:|
| `table:camp-rumor` | 营地传闻 | 8-12 |
| `table:travel-risk` | 旅行即时风险 | 8-12 |
| `table:explore-discovery` | 探索可见发现 | 8-12 |
| `table:gather-yield` | 采集产出差异 | 6-10 |
| `table:gather-complication` | 采集代价/误判 | 6-10 |
| `table:social-reaction` | NPC 初始反应 | 6-10 |
| `table:minor-cost` | 失败或部分成功的轻代价 | 8-12 |

每个条目建议带：

- `weight`：控制出现概率。
- `tags`：例如 `[risk, clue, material, social]`。
- `payload`：可选，但推荐写 `clock_id`、`palette_id`、`clue_stage`、`risk_level`、`requires_followup`。

规则：

- 传闻表结果默认不是事实。
- 发现表结果默认是 `hinted` 或 event，不直接创建 known 实体。
- 采集产出如果要入库存，必须走 `gather` delta 或手写 turn delta。
- 随机表不能代替 `upsert_entities`、`tick_clocks` 或 `commit_turn`。

验收命令：

```bash
aigm play preview /tmp/aigm-small-cn-save random_table --table table:camp-rumor
aigm play preview /tmp/aigm-small-cn-save random_table --table table:travel-risk
```

完成标准：

- 每个新增表至少有一个 smoke 或手工 preview 覆盖。
- `random_table` preview 能生成审计 delta。
- 条目没有把高影响新文明、新势力直接写成玩家已确认事实。

#### P0.4 补 world_settings 和 rules

新增或扩展 `world_settings.yaml`：

- `world:new-content-boundary`：说明 AI 只能提出候选，不能确认重大新事实。
- `world:material-discovery`：说明材料发现需要观察、采样、确认。
- `world:faction-contact`：说明势力/文明必须多源确认。
- `world:rumor-is-not-fact`：说明传闻和随机表结果默认未证实。

新增或扩展 `rules.yaml`：

- `rule:no-inventory-without-delta`：没有库存 delta，不得说玩家获得物品。
- `rule:palette-candidate-boundary`：palette 是候选，不是事实。
- `rule:high-impact-content-review`：新地点、路线、势力、文明、世界规则需要人工或 content delta 维护。
- `rule:hidden-never-player-visible`：hidden 内容不得出现在玩家视图。

完成标准：

- `start_turn` 在相关行动上下文中能加载这些 world setting/rule。
- AI GM 回复中出现“可能”“像是”“需要确认”，而不是直接“你确认发现”。

#### P0.5 更新作者 AI Prompt 和 GM prompt

在 [`../prompts/author-ai-prompt.md`](../prompts/author-ai-prompt.md) 和 campaign-local `prompts/gm.md` 增加硬规则：

- 必须遵守事实阶梯。
- 新内容优先来自已知实体、palette、random table。
- `available` 可以作为低风险候选；`confirm_required` 只能提示或要求采样；`clue_only` 只能做伏笔。
- 不得把随机表传闻写成事实。
- 不得把 hidden 内容透露给玩家。
- 不得声称“已保存”“已加入背包”“已确认势力存在”，除非 delta 已通过 commit。
- 对未知目标使用 `unknown_lead`，不要发明实体 ID。

完成标准：

- AI GM 对未知事物的措辞稳定落在“线索/候选/待确认”。
- 提示词明确告诉 AI：它可以提议世界，但不能擅自改写世界。

#### P0.6 P0 回归清单

每次 P0 内容改动后运行：

```bash
aigm campaign validate examples/small_cn_campaign
aigm campaign doctor examples/small_cn_campaign
aigm campaign test examples/small_cn_campaign
```

手工跑一组 UX 样例：

```bash
aigm save init examples/small_cn_campaign /tmp/aigm-small-cn-save --force
aigm play start-turn /tmp/aigm-small-cn-save --user-text "在营地附近找草药" --submode gather
aigm play start-turn /tmp/aigm-small-cn-save --user-text "调查桥下的奇怪声音" --submode explore
aigm play preview /tmp/aigm-small-cn-save explore --target "桥下的奇怪声音" --unknown-lead true --approach careful
aigm palette suggest /tmp/aigm-small-cn-save --kind all --location loc:camp --intent explore
```

P0 完成标准：

- 示例剧本 validate/test 通过。
- 至少一个采集、一个探索、一个传闻、一个旅行风险路径可跑。
- palette 能在 context 中出现。
- AI 不会把候选素材直接说成正式事实。
- 所有新增事实仍然需要 turn delta 或 content delta。

### 13.2 P1 目标：把 P0 的手工约定产品化

P1 需要轻量改内核/CLI。目标是减少人工纪律依赖，让候选素材能被行动 resolver 直接识别、消费和校验。

#### P1.1 让 V1 validator 正式支持 palettes

当前状态：**已落地**。维护时需要保持以下规则：

- `campaign_validation.py` 的可选 content key 包含 `palettes`。
- `schemas/campaign.schema.json` 和 packaged resource schema 支持 `content.palettes`。
- palette 文件验证覆盖字段、引用、状态、保存类型和可见性边界。
- `campaign validate` 应捕获坏 palette；`campaign outline` 应展示 palette 分布。

验证规则：

- 文件顶层只能包含 `materials`、`species`、`factions`、`encounters`、`locations`。
- `id` 必填且全局唯一。
- `discovery.mode` 必须是 `direct`、`confirm_required`、`clue_only`。
- `locations` 引用的地点必须存在，或明确允许 biome-only。
- `intents` 必须是已知行动意图。
- `unlock.required_clocks` 引用的 clock 必须存在。
- `save_as.type` 必须能映射到当前支持的实体类型。
- `rarity: hidden` 的条目不能 `discovery.mode: direct`。

完成标准：

- 可以安全把 `content.palettes` 写入 `campaign.yaml`。
- `campaign validate` 能捕获坏 palette。
- `campaign doctor --strict` 能把缺少发现方式、风险、用途的候选标出来。

#### P1.2 preview_action 消费 palette 候选

当前状态：**基础版已落地**。`gather/explore/social/travel/craft` 均可消费 `--palette-id`。后续重点是继续扩充 kind/status 防错和更多自然语言样例。

新增通用 action option：

```text
--palette-id pal:mat:silver-moon-herb
```

或在自然语言 `act` 中识别候选 ID/名称后写入 `options.palette_id`。

resolver 行为：

- `gather`：
  - `palette_id` 指向 material 且状态是 `available`：可生成采集 preview delta，但入库存仍要有结构化 `upsert_entities` 或 item 变化。
  - 状态是 `confirm_required`：返回 `needs_confirmation`，要求观察/采样/询问；可生成线索 event，不直接给库存。
  - 状态是 `clue_only`：只能生成 hinted clue，不允许产出资源。
- `explore`：
  - `palette_id` 指向 location/species/faction/encounter：生成带 `palette_id`、`candidate_status`、`needs_gm_resolution` 的 event。
  - 高影响候选默认 `clue_only` 或 `confirm_required`，不能 `ready_to_save` 为 known 实体。
- `social`：
  - `palette_id` 指向 rumor/faction clue 时，只能把它作为询问话题或传闻，不直接确认派系存在。
  - 若 NPC 给出确认，需要写 relationship/event/clue delta。
- `travel`：
  - `palette_id` 指向 location lead 时，默认只给“寻找路线/确认方向”的 explore/travel plan，不直接新增路线。

所有 resolver 生成的 delta payload 都应包含：

```json
{
  "palette_id": "pal:mat:silver-moon-herb",
  "palette_status": "confirm_required",
  "source": "palette",
  "needs_gm_resolution": true
}
```

完成标准：

- 玩家能选择具体候选，而不是让 AI 自由改写候选。
- `preview_action` 的 `facts_used` 或 payload 能追踪候选来源。
- `validate_delta` 能拒绝状态不匹配的候选消费，例如把 `clue_only` 材料直接加入库存。

#### P1.3 从 palette 生成 content delta

当前状态：**基础版已落地**。`content from-palette` 可生成带 `review_required` 的 content delta 草案；后续应增加直接 `--enqueue`，减少“先写本地 delta 再 proposal create”的维护摩擦。

扩展 `content_factory`：

```bash
aigm content from-palette ./saves/my-run pal:mat:silver-moon-herb --visibility hinted --output ./draft.json
```

生成规则：

- material -> `type: material` 或 `type: item` 草案。
- location -> `type: location` 草案；若可旅行，要求补 `upsert_routes`。
- faction -> `type: faction` 或 `type: faction_state` 草案，默认 `visibility: hinted`。
- species -> `type: species` 草案，要求 habitat、behavior、risks。
- encounter -> 默认生成 event 模板，不一定生成实体。

输出必须带：

- `source: content_factory_from_palette`
- `meta.palette_id`
- `meta.review_required: true`
- `description` 说明这是候选转内容草案，不是自动事实。

完成标准：

- 作者能把常出现的候选沉淀成 content delta。
- 高影响类型默认 `hinted` 或 `hidden`，不能默认 `known`。
- `content validate-delta` 能校验生成结果。

#### P1.4 高影响内容 warning/approval

当前状态：**已落地**。`validate_content_delta` 已输出 warnings；`apply-content-delta --strict-review` 会阻止未人工 review 的高影响内容，并把 proposal 入队。

高影响内容：

- `world_setting`
- `rule`
- `location`
- `route`
- `faction`
- `faction_state`
- `species` 且 rarity 为 rare/hidden/legendary
- visibility 从 `hidden/hinted` 变为 `known`

warning 示例：

```text
warning: upsert_entities[0] creates high-impact faction; require meta.reviewed_by or meta.review_required=true
```

推荐规则：

- `content validate-delta` 输出 warnings。
- `apply-content-delta` 默认允许 warnings，但打印摘要。
- `apply-content-delta --strict-review` 要求高影响内容先进入人工 review。
- 后续可把 warning 从字符串扩展为结构化风险字段，方便 UI 筛选。

完成标准：

- AI 草案不会静默创建大势力、新文明、新世界规则。
- 维护者能看见高影响变更的风险。

#### P1.5 palette 与 authoring 工具集成

已落地：

- `campaign validate`：验证 palette 缺字段、坏引用、发现模式、保存类型、hidden/direct 冲突等结构问题。
- `campaign doctor`：继承 `campaign validate` 的 palette error/warning，能在作者诊断流中暴露坏候选。
- `campaign outline`：展示 palette 数量和按 kind 分布。
- [`../prompts/author-ai-prompt.md`](../prompts/author-ai-prompt.md) 和 GM prompt：包含事实阶梯、候选素材边界、delta 保存规则。

后续可增强：

- `campaign doctor`：增加候选过少、状态分布不合理、缺少用途链路等专项诊断码。
- `campaign check-ai`：检测 AI 味内容，例如“待定”“神秘力量”“古老文明”但没有发现方式/风险/限制。

完成标准：

- 作者不需要读内核代码，也能知道 palette 哪里坏了。
- AI 生成剧本包时不会漏掉候选素材层。

#### P1.6 P1 测试要求

新增或扩展测试：

- `test_palette_validation.py`
- `test_palette_context.py`
- `test_palette_action_consumption.py`
- `test_content_delta_high_impact_warnings.py`
- `test_content_factory_from_palette.py`

必须覆盖：

- 自动扫描 `content/palettes/*.yaml`。
- `campaign.yaml.content.palettes` 显式声明。
- locked/clue_only/confirm_required/available 四类行为。
- gather 使用 material candidate。
- explore 使用 unknown location/faction/species candidate。
- clue_only 候选不能变成 known 实体或库存。

P1 完成标准：

- P0 的手工流程不再依赖 AI 自觉。
- 候选可以被 action resolver 识别和约束。
- 坏 palette 会在 authoring 阶段暴露。
- 高影响内容会给出明确 warning。

### 13.3 P2 目标：把新内容治理内核化

P2 是机制增强，不应和 P0/P1 混在一起做。目标是让“发现、候选、审核、沉淀”成为正式状态机。

#### P2.1 discovery_state

新增发现状态模型。可以是数据库表，也可以先作为实体 details 的规范字段；建议最终使用表。

推荐字段：

| 字段 | 含义 |
|---|---|
| `id` | discovery record id |
| `subject_id` | 已存在实体 ID，可为空 |
| `palette_id` | 候选素材 ID，可为空 |
| `kind` | material/species/faction/location/clue |
| `stage` | unseen/rumored/hinted/observed/sampled/confirmed/rejected |
| `visibility` | player/gm/maintenance |
| `confidence` | 0-1 或 low/medium/high |
| `location_id` | 发现发生地 |
| `source_event_ids` | 支撑该状态的事件 |
| `required_next_steps` | 下一步确认方法 |
| `updated_turn_id` | 最近更新回合 |

行动集成：

- random rumor -> `rumored`
- explore clue -> `hinted` 或 `observed`
- gather sample -> `sampled`
- successful research/social confirmation -> `confirmed`
- false lead -> `rejected`

完成标准：

- 同一材料/势力/地点不会每次都被 AI 当作全新东西。
- 玩家查询能看到自己已知的发现阶段。
- hidden 真相仍不会进入 player view。

#### P2.2 proposal 审稿队列

当前 `proposal validate` 已能校验一次性 TurnProposal。P2 应把它扩成持久队列。

推荐状态：

```text
draft -> needs_review -> approved -> applied
draft -> rejected
approved -> superseded
```

推荐命令：

```bash
aigm proposal create ./saves/my-run ./proposal.json
aigm proposal list ./saves/my-run --status needs_review
aigm proposal review ./saves/my-run proposal:000123 --approve
aigm proposal apply ./saves/my-run proposal:000123
```

队列记录必须保存：

- 原始 AI 草案。
- 关联玩家输入。
- `facts_used`。
- `narrative_claims`。
- `proposed_delta` 或 content delta。
- 审核人/审核时间。
- 应用后的 turn_id/event_id。

完成标准：

- AI 可以大量提出候选，但不会直接污染世界事实。
- 维护者能批量审核、拒绝、应用。
- proposal 与 content delta/turn delta 有可追踪关系。

#### P2.3 多步行动计划 composite plan

当前 composite 主要是 plan/repair options，不做原子提交。P2 可以逐步支持结构化多步计划。

第一阶段：

- 只生成 plan，不 commit。
- 每个 step 都是现有 action resolver。
- 每个 step 可单独 preview/validate/commit。

第二阶段：

- 引入 `plan_id`。
- 保存 plan 状态：pending/running/completed/abandoned.
- 支持跨回合继续。

第三阶段：

- 原子 composite commit，仅用于低风险可确定步骤。
- 每个子步骤仍必须有 resolver contract。

典型场景：

- 先 travel 到旧桥，再 explore 桥下。
- 先 social 询问 NPC，再根据回答 explore。
- 先 gather 采样，再 craft 小量测试。
- 先 random_table 生成风险，再 travel 结算。

完成标准：

- 复合输入不再退化为 routine。
- 多步计划不会绕过 capability、visibility、delta 校验。
- 失败步骤能清楚提示玩家下一步。

#### P2.4 内容沉淀与回写

当前 `apply-content-delta` 主要写入 save/package 当前数据库，不等于自动回写作者剧本 YAML。P2 需要明确“运行事实沉淀为剧本权威内容”的流程。

推荐能力：

```bash
aigm content diff-runtime ./saves/my-run
aigm content promote ./saves/my-run --entity mat:silver-moon-herb --target-campaign examples/small_cn_campaign
aigm content export-delta ./saves/my-run --since turn:000120 --output ./maintenance_delta.json
```

规则：

- 默认只导出草案，不直接改 Campaign Package。
- 高影响内容必须带 review 标记。
- 回写后必须跑 `campaign validate`、`campaign doctor`、`campaign test`。
- 回写应保留来源 event/proposal ID。

完成标准：

- 长期运行中出现的 NPC、材料、地点能沉淀回剧本包。
- 下一次新开档也能复用这些内容。
- 不会把一次性噪音全部固化为世界设定。

#### P2.5 P2 测试要求

新增测试方向：

- `test_discovery_state.py`
- `test_proposal_queue.py`
- `test_composite_plan_runtime.py`
- `test_content_promotion.py`
- `test_visibility_discovery_integration.py`

必须覆盖：

- 传闻不会直接变 known。
- 多源确认能把 hinted 推进到 confirmed。
- rejected lead 不再反复出现为新发现。
- proposal 未批准不能应用。
- composite plan 中任一步失败时不提交后续事实。
- content promote 不会覆盖作者手写字段。

P2 完成标准：

- 新内容有正式生命周期。
- AI 生产内容、玩家发现内容、作者维护内容三者不再混在一起。
- 世界能扩展，但扩展路径可审计、可回滚、可测试。

### 13.4 推荐实施顺序

优先级从高到低：

1. 已完成：修正 `small_cn_campaign` capability 与 smoke 覆盖。
2. 已完成：为 `small_cn_campaign` 增加 `content/palettes/*.yaml`。
3. 已完成：扩充随机表。
4. 已完成：更新作者 AI prompt 和 `prompts/gm.md`。
5. 已完成：给 palette 增加 validator/doctor 基础支持。
6. 已完成：给 gather/explore/social/travel/craft 增加 `palette_id` 消费。
7. 已完成：给 `content_factory` 增加 `from-palette`。
8. 已完成：给 content delta 增加高影响 warnings。
9. 已完成基础：引入 `discovery_states` 并接入 context 召回；后续补确认/归档/报告。
10. 已完成基础：引入持久 `proposal_queue`；后续补 `memory_update`、`alias_suggestion`、`turn_delta` apply/revert。
11. 后续 P2：引入 composite plan 状态。
12. 后续 P2：做内容沉淀/回写工具。

不建议提前做：

- 不要先做复杂 UI。
- 不要先做自动回写 Campaign Package。
- 不要让 AI 直接生成高影响 known 实体。
- 不要把 `content_delta` 当成绕过行动结算的万能入口。
- 不要把 discovery_state 召回误当成已确认事实；线索晋升仍需要明确证据和审核边界。

## 14. 判断标准

一个新内容机制算健康，应该满足：

- 玩家感觉世界会扩展，而不是被剧本锁死。
- AI 不能随口让重大世界事实成立。
- 所有新增事实都有来源、可见性和保存记录。
- 隐藏内容不会泄露到玩家视图。
- 运行中反复出现的内容能沉淀回剧本包。
- UX 模拟中的 unknown、越权、伪 delta、复合动作不会误存为 routine。

最终边界：

> AI 可以提议世界，不能擅自改写世界。候选素材提供自由度，content delta 提供记忆和治理，`commit_turn(delta, turn_proposal)` 提供普通玩家事实边界。
