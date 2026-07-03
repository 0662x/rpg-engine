# AIGM Kernel UX Design

文档状态：**PROPOSED：面向 V1.1/V1.2 的 UX 与工程设计方案**  
日期：2026-06-30  
适用范围：`rpg_engine`、V1 CLI/MCP、Action Resolver、GMRuntime、AI Client Prompt、Isekai Farm 存档实战体验。  
输入依据：[`bug-report.md`](bug-report.md)、当前源码结构、外部 AI GM/互动叙事/UX 资料。

## 1. 核心结论

AIGM Kernel 当前的问题不是“系统太严格”本身，而是**严格性出现的位置不对**。

正式写入层必须严格：隐藏信息不能泄漏，未知实体不能落盘，资源不能负数，`expected_turn_id` 不能过期，`commit` 不能保存不完整的世界状态。这些严格性保护游戏世界。

玩家体验层不能像数据库 API：玩家说“找 An 问异常”“在家盘点库存”“去草原边缘探索一圈再回来”时，系统应该先像 GM 一样理解、补全、拆分和确认，而不是直接暴露 `location_after must remain ...`、`target not at location`、`missing options.npc` 这类内部契约。

目标设计可以浓缩成一句话：

> **严格性应该保护世界，不应该惩罚玩家表达。**

因此，V1.1/V1.2 的 UX 方向应是：

```text
玩家自然输入
  -> Intent Layer 宽松理解
  -> GM Ruling Layer 解释、补全、拆分、确认
  -> Preview Layer 计算代价/风险/状态变化
  -> Commit Layer 严格落盘
  -> Debug/Ops Layer 给开发者看内部契约
```

## 2. 外部资料结论

本设计参考以下资料，全部以“原则和架构启发”为主，不照搬具体产品。

### 2.1 AI GM 需要结构化状态约束

Song、Zhu、Callison-Burch 的 AI Game Master function calling 论文指出，LLM 作为 GM 可以处理多样输入和生成丰富叙事，但会受不可预测性、规则执行和状态一致性限制；引入函数调用和游戏专用控制，可以改善叙事质量与状态更新一致性。  
来源：Jaewoo Song, Andrew Zhu, Chris Callison-Burch, *You Have Thirteen Hours in Which to Solve the Labyrinth: Enhancing AI Game Masters with Function Calling*, arXiv 2024. <https://arxiv.org/html/2409.06949v1>

对本系统的启发：

- `GMRuntime`、Action Resolver、delta schema、clock、inventory、route 等结构化系统必须保留。
- AI/玩家自然语言不能直接成为权威状态。
- `commit` 层继续严格是正确方向。

### 2.2 LLM 创造力和符号系统一致性需要分层

IVIE 论文把互动小说生成中的核心矛盾表述为：LLM 擅长创造性叙事，但世界一致性弱；符号系统能保证一致性，但灵活性弱。论文采用增量生成与符号校验结合的方式平衡二者。  
来源：Micaela Vaucher 等, *IVIE: A Neuro-symbolic Approach to Incremental and Validated Generation of Interactive Fiction Worlds*, arXiv 2026. <https://arxiv.org/abs/2606.13348>

对本系统的启发：

- 玩家体验层应允许自然表达、模糊表达和组合动作。
- 落盘层应只接受结构化、可验证、完整的 world-state transformation。
- UX 层需要明确“这只是预演/建议”与“这可以保存”的边界。

### 2.3 玩家 agency 不等于无限自由

互动叙事研究长期讨论玩家 agency 和叙事一致性的矛盾。Hammond、Pain、Smith 指出，传统互动叙事问题常把 agency 当成必须被限制的对象，这种问题框架本身容易和玩家参与相冲突。  
来源：Sean Hammond, Helen Pain, Tim J. Smith, *Player Agency in Interactive Narrative: Audience, Actor & Author*, University of Edinburgh Research Explorer. <https://www.research.ed.ac.uk/en/publications/player-agency-in-interactive-narrative-audience-actoramp-author/>

Tanenbaum 进一步提出，叙事游戏中的 agency 不应只理解为自由选择，还应理解为对意义的承诺。限制可以存在，但要服务于有意义的玩法和叙事，而不是把玩家视为需要被防范的破坏源。  
来源：Karen Tanenbaum, Theresa Tanenbaum, *Commitment to Meaning: A Reframing of Agency in Games*. <https://escholarship.org/content/qt6f49r74n/qt6f49r74n_noSplash_305fd28ab3e5a5fe4d03d722afe8a8d8.pdf?t=pyebbq>

对本系统的启发：

- “不能瞬间通关”“不能凭空创造无限资源”是合理限制。
- “同建筑不同房间不能找人说话”“在家盘点被解释成去空地采集”属于 UX 摩擦。
- 限制必须用世界内理由和可选路径表达，而不是直接用内部校验错误表达。

### 2.4 自由文本输入需要可发现性和错误恢复

Emily Short 对 parser/choice/natural language interface 的分析指出，自然语言和 parser 输入表达力强，但 ambiguity 高；玩家很难知道系统到底把输入映射成了什么，也很难知道可用 affordance。  
来源：Emily Short, *Not All Choice Interfaces Are Alike*. <https://emshort.blog/2016/05/25/not-all-choice-interfaces-are-alike/>  
来源：Emily Short, *So, Do We Need This Parser Thing Anyway?* <https://emshort.blog/2010/06/07/so-do-we-need-this-parser-thing-anyway/>

Nielsen Norman Group 的 usability heuristics 强调：系统应使用用户熟悉的语言，显示系统状态，帮助用户识别、诊断并恢复错误，且应尽量预防错误。  
来源：Jakob Nielsen, *10 Usability Heuristics for User Interface Design*, NN/g. <https://www.nngroup.com/articles/ten-usability-heuristics/>

对本系统的启发：

- `query scene` 应提供“可行动 affordance”，减少玩家猜命令。
- `preview` 应明确系统理解到的意图。
- 错误必须带 repair options。
- 技术细节只在 `--view debug` 或 `--debug` 下出现。

### 2.5 产品对照：过松和过紧都有问题

AI Dungeon 展示了开放 AI 叙事的吸引力，也暴露出开放生成在安全、记忆和一致性上的风险。  
来源：AI Dungeon 官网和应用描述。 <https://aidungeon.com/>  
来源：WIRED 对 AI Dungeon 内容治理问题的报道。 <https://www.wired.com/story/ai-fueled-dungeon-game-got-much-darker/>

Hidden Door 则采用更强的世界内限制，防止玩家直接写出无敌物品或瞬间通关；The Verge 的体验也指出，这种限制保护挑战和故事，但如果过于明显，会让玩家感觉系统在强拉剧情。  
来源：Jay Peters, *Hidden Door is an AI storytelling game that actually makes sense*, The Verge, 2025-08-13. <https://www.theverge.com/games/757816/hidden-door-early-access-ai-story>

对本系统的启发：

- AIGM Kernel 不应做无限自由的纯聊天叙事。
- 也不应把玩家拖进过度显性的 resolver contract。
- 最好的体验是“GM 裁决感”：玩家知道世界有边界，但边界看起来来自地点、时间、风险、资源和 NPC 行为，而不是来自 schema。

## 3. 当前系统 UX 诊断

[`bug-report.md`](bug-report.md) 显示：核心管线已经明显改善，许多早期 bug 已修复，包括中文解析、hidden clock 泄漏、combat capability、`validate-delta` 与 `commit` 契约漂移、未知 travel/explore 目标可提交、`preview.ok` 语义过宽等。

剩余 UX 问题集中在“严格性暴露到了玩家/GM 操作层”：

| 场景 | 当前表现 | UX 问题 | 应有体验 |
|---|---|---|---|
| 找 An 聊天 | An 在 `h-room`，玩家在 `house`，social 被阻断 | 同建筑不同房间被当成完全跨地点 | “An 在 H 室，要先过去再谈吗？” |
| 在家盘点库存 | 可能被 gather 解释成 target/location 不匹配 | 用户语言和 action 语义不匹配 | 归入 `routine.inventory_audit` |
| 去某地探索再回来 | 需要手动拆 travel/explore/travel | 玩家意图是组合动作，系统只支持单动作 | 自动拆 plan 并预览总耗时/风险 |
| preview 有 blocker | 早期 `ok=true` 容易误导自动化 | 预演成功和可保存混在一起 | `status` 与 `ready_to_save` 分离 |
| commit 报错 | 内部 contract 文案 | 玩家不理解，也无法恢复 | 世界内解释 + 2-3 个修复选项 |
| 低风险日常 | 需要准确 action/type/options | 日常操作被工程语义打断 | `routine` 作为低风险总线 |

## 4. UX 设计原则

### 4.1 宽进严出

输入侧宽松：自然中文、英文短语、组合动作、别名、模糊目标都允许进入 Intent Layer。

输出侧严格：只有 `ready_to_save=true` 的结构化 delta 才能进入 `commit`。

### 4.2 玩家语言优先

玩家看到的是：

```text
An 不在你当前房间。她在 H 室。
你可以先过去再和她谈，约 1-2 分钟。
```

不是：

```text
location_after must remain loc:home-mycelium-house
```

内部 `entity_id` 可以在 GM/debug 视图中显示，但玩家视图应优先显示名称、地点关系和可执行选项。

### 4.3 preview 不是 commit

`preview` 可以展示草案、解释、风险和缺口，但不能让“含 blocker 的草案”看起来可提交。

必须显式区分：

- 系统能否理解请求
- 请求是否符合世界规则
- 是否可以直接保存
- 是否需要玩家确认
- 是否需要 GM 补写结构化 delta

### 4.4 所有阻断都要有 repair options

阻断不能只说“不行”。它必须回答：

1. 为什么不行。
2. 可以怎么改。
3. 哪些选项会消耗时间、移动位置或改变风险。

### 4.5 低风险自动补全，高风险明确确认

低风险：

- 同一建筑内移动找人
- 盘点库存
- 检查农田
- 喂食、整理、擦拭、维护
- 只读观察

可以自动补全或轻确认。

高风险：

- 战斗
- 进入危险地点
- 消耗稀缺资源
- 推进危险 clock
- 公开承诺、交易、威慑、攻击
- 可能不可逆的实体状态变化

必须明确确认。

### 4.6 视图分离

同一结果至少支持三种视图：

| 视图 | 受众 | 内容 |
|---|---|---|
| `player` | 玩家 | 世界内解释、可选行动、可见信息，不泄漏 hidden |
| `gm` | GM/AI 客户端 | 结构化 plan、delta、风险、隐藏 GM 信息 |
| `debug` | 开发者 | resolver、schema、SQL/trace、contract errors |

## 5. 目标交互模型

### 5.1 普通玩家入口

建议新增主入口：

```bash
aigm play act ./save "去H室找An问异常"
```

玩家视图输出：

```text
当前状态
第26天 · 下午｜菌丝屋｜体力正常｜当前位置：菌丝屋

GM理解
你想去 H 室找 An，询问最近的异常。

将执行
1. 从菌丝屋前往 H 室
2. 与 An 低声交谈，主题：异常情况

影响
时间：约 1-3 分钟
位置：H 室
风险：低
状态保存：可执行

选择
[执行] [只去H室] [在门口呼唤An] [取消]
```

GM/debug 视图才显示：

```json
{
  "status": "needs_confirmation",
  "ready_to_save": false,
  "plan": [
    {"action": "travel", "kind": "micro_travel", "from": "loc:home-mycelium-house", "to": "loc:home-mycelium-h-room"},
    {"action": "social", "npc": "char:an", "topic": "异常情况", "approach": "低声询问"}
  ],
  "repair_options": [
    {"id": "go_and_talk", "label": "去H室找An谈"},
    {"id": "call_from_here", "label": "在门口呼唤An"},
    {"id": "travel_only", "label": "只去H室"}
  ]
}
```

### 5.2 查询场景时展示 affordance

`play query scene` 末尾增加简短“可行动”区块，来自当前位置、可见 NPC、routes、active projects、routine templates 自动生成。

示例：

```text
可行动
- 找 An 谈谈
- 盘点库存
- 检查农田
- 制作或校准火药箭
- 去 L1 小溪
```

这不是教程，而是可发现性支持。它解决 parser/自然语言系统中“玩家不知道系统能理解什么”的问题。

### 5.3 回合输出固定结构

所有玩家向输出尽量遵循固定结构：

```text
当前状态
...

GM理解
...

将执行
...

影响
...

选择
...
```

阻断时改为：

```text
无法直接执行
...

原因
...

你可以
...
```

## 6. Preview 状态模型

现有 `PreviewActionResult.ok: bool` 不够表达 UX 状态。建议引入以下状态：

| 状态 | 含义 | 是否可保存 | 是否给 committable delta |
|---|---|---:|---:|
| `ready` | 已解析、风险可接受、delta 完整 | 是 | 是 |
| `needs_confirmation` | 系统能处理，但需要玩家确认 | 否，确认后才是 | 否，或 delta 标记不可提交 |
| `clarify` | 多个解释合理，必须选择其一 | 否 | 否 |
| `blocked` | 世界规则或安全边界不允许 | 否 | 否 |
| `internal_error` | 系统异常 | 否 | 否 |

建议 JSON 结构：

```json
{
  "campaign_id": "isekai-farm-v1",
  "action": "social",
  "status": "needs_confirmation",
  "ok": false,
  "ready_to_save": false,
  "player_message": "An 在 H 室，要先过去再谈吗？",
  "interpretation": {
    "summary": "去H室找An问异常",
    "confidence": "high"
  },
  "plan": [
    {
      "step_id": "step:1",
      "action": "travel",
      "kind": "micro_travel",
      "from_location_id": "loc:home-mycelium-house",
      "to_location_id": "loc:home-mycelium-h-room",
      "estimated_minutes": 2
    },
    {
      "step_id": "step:2",
      "action": "social",
      "npc_id": "char:an",
      "topic": "异常",
      "approach": "低声询问"
    }
  ],
  "repair_options": [
    {
      "id": "confirm_go_and_talk",
      "label": "去H室找An谈",
      "effect": "移动到H室并开始交谈"
    },
    {
      "id": "call_from_here",
      "label": "在门口呼唤An",
      "effect": "不移动，但谈话私密性下降"
    }
  ],
  "delta_draft": null,
  "debug": {
    "resolver": "social",
    "scope": "same_parent",
    "raw_errors": []
  }
}
```

兼容策略：

- `ok` 暂时保留，定义为 `status == "ready"`。
- 新增 `status`、`ready_to_save`、`repair_options`。
- `markdown` 保留，但不再作为自动化提取 delta 的唯一来源。
- 自动化必须读 `ready_to_save`，不能只读 `ok` 或 fenced JSON。

## 7. 位置交互范围

当前系统把 location 作为严格相等判断，导致同建筑不同房间的自然动作被阻断。建议新增 interaction scope：

| Scope | 含义 | 例子 |
|---|---|---|
| `same_location` | 同一实体地点 | 玩家和 An 都在 H 室 |
| `same_parent` | 同一父地点内不同子地点 | house 和 h-room 同属地下菌丝城/基地 |
| `one_hop` | 有直接 route | 菌丝屋到空地 |
| `nearby_visible` | 可看见或可呼喊 | 门口、邻近隔间 |
| `remote` | 远程，需要 travel 或通信手段 | L15 草原边缘 |
| `blocked` | 不可达或不可见 | 封锁地点、隐藏地点 |

不同 action 的默认范围：

| Action | 默认允许范围 | UX 处理 |
|---|---|---|
| `query` | visible scope | 只读，不推进 |
| `social` 普通交谈 | `same_location`、`same_parent` | 同 parent 自动建议 micro-travel |
| `social` 私密/交易/承诺 | `same_location` | 不同房间需确认移动或降级方式 |
| `routine` 家务/盘点 | owned/base scope | 不要求 target.location 精确等于当前位置 |
| `gather` 野外采集 | `same_location` | 需要先 travel |
| `craft` | workshop/base scope | 材料和工作台决定可行性 |
| `combat` 近战 | `same_location` | 严格 |
| `combat` 远程 | weapon range + line of sight | 必须确认 ready_state |
| `travel` | route graph | 目的地必须解析 |
| `explore` | visible or newly declared unknown | 未知探索必须显式标记为 unknown lead |

工程上新增：

```python
@dataclass(frozen=True)
class InteractionScope:
    kind: Literal["same_location", "same_parent", "one_hop", "nearby_visible", "remote", "blocked"]
    from_location_id: str | None
    target_location_id: str | None
    parent_id: str | None = None
    route_id: str | None = None
    estimated_minutes: int | None = None
    requires_travel: bool = False
```

建议放在 `rpg_engine/actions/scope.py`，供 `social`、`gather`、`combat`、`routine` 共用。

## 8. Action UX 策略

### 8.1 `routine`：低风险日常总线

`routine` 应成为低风险、低戏剧性、常见维护动作的首选：

- 盘点库存
- 灌金光
- 检查农田
- 喂食俘虏/照看 NPC
- 整理装备
- 检查武器
- 清洁、维护、搬运小物件
- 在基地内查看/确认状态

建议新增 routine template registry：

```python
@dataclass(frozen=True)
class RoutineTemplate:
    id: str
    labels: tuple[str, ...]
    keywords: tuple[str, ...]
    default_time_minutes: int
    allowed_scope: str
    risk_level: Literal["none", "low", "medium"]
    produces_delta: bool
    requires_confirmation: bool
```

示例：

```yaml
routine_templates:
  - id: routine:inventory-audit
    labels: ["盘点库存", "整理库存", "看看物资"]
    default_time_minutes: 5
    allowed_scope: base
    risk_level: none
    produces_delta: false
    requires_confirmation: false
```

UX 规则：

- “在家盘点库存”不走 `gather`，直接走 `routine.inventory_audit`。
- 不改变状态的 routine 可以作为 query/routine 混合，不必 commit。
- 改变状态的 routine 必须产出结构化 delta。

### 8.2 `social`：允许同 parent micro-travel

当前 `social` 要求 NPC 与玩家在同一 `location_id`，这对游戏状态严格，但对玩家体验过硬。

建议：

- `same_location`：直接 ready。
- `same_parent`：`needs_confirmation`，提供“过去谈/呼唤/取消”。
- `one_hop`：`needs_confirmation`，展示耗时。
- `remote`：`blocked` 或建议 travel。
- 私密谈话、交易、威慑、承诺：默认必须 `same_location`，但可自动拆 `micro_travel + social`。

玩家文案：

```text
An 不在你当前房间。她在 H 室，和你同属地下菌丝城。
你可以先过去再问，约 2 分钟。
```

debug 文案：

```text
social scope=same_parent; proposed composite plan=micro_travel+social
```

### 8.3 `gather`：只处理采集，不处理盘点

`gather` 应保持相对严格，因为它会产生资源。

规则：

- 野外采集/收获作物/拾取自然资源：走 `gather`。
- 盘点库存/检查仓库/看看有什么：走 `routine` 或 `query`。
- target 不在当前 location：不要直接失败成技术错误，提供 travel option。

玩家文案：

```text
你现在在菌丝屋，目标资源在空地。
可以先去空地采集，或改为盘点家中库存。
```

### 8.4 `travel`：区分 travel 和 micro-travel

`travel` 负责有意义的位置变化、耗时、路线风险。

新增 `micro_travel` 概念：

- 同 parent 子地点之间
- 耗时极短
- 通常无独立 encounter
- 可作为 composite plan 的内部步骤

正式 delta 可以有两种实现：

1. 仍保存为 `intent=travel` 的短行动。
2. composite delta 中记录 `events[].payload.micro_travel`，最终 `location_after` 为社交/日常完成后的地点。

V1.1 建议先选 1，保守简单；V1.2 再做 composite delta。

### 8.5 `craft`：缺材料时返回计划，不当成死错误

制作类动作常常是“我想做 X”，不是“我现在一定要完成 X”。

建议状态：

- 材料齐、时间齐、地点合适：`ready`。
- 材料缺、但可列出缺口：`blocked` 或 `needs_confirmation`，返回制作计划。
- 项目不明确：`clarify`。

玩家文案：

```text
现在不能完成火药箭校准。
缺少：硝石粉 x1，稳定工时 30 分钟。

你可以：
1. 先整理材料
2. 去 L12 找硝石
3. 改做普通箭维护
```

### 8.6 `explore`：允许“未知线索”，但必须显式建模

第七轮已修复未知 explore 目标可提交的问题。未来如果要支持探索未知对象，应引入显式 unknown lead，而不是让 `target_id=null` 通过。

建议：

```json
{
  "intent": "explore",
  "payload": {
    "target_id": null,
    "target_query": "奇怪的声音",
    "target_kind": "unknown_lead",
    "needs_gm_resolution": true
  }
}
```

commit 规则：

- `target_id` 为空时，必须有 `target_kind=unknown_lead`。
- 必须有 `needs_gm_resolution=true`。
- 必须由 resolver 生成，不允许手写绕过。

### 8.7 `combat`：高风险必须确认

combat 应保持最严格 UX。

规则：

- 主动攻击、消耗弹药、暴露位置、接近威胁：必须 `needs_confirmation`。
- `ready_state` 可以降低风险，但不等于攻击。
- 远程武器必须校验距离、弹药、视线或已知位置。

玩家文案：

```text
你可以用终极复合弩戒备 T2 大猫，但这不是攻击。
若主动射击，会消耗火药箭并可能惊动地下区域。
```

### 8.8 `random_table`：GM 工具，不是普通玩家动作

随机表应保留结构化和审计能力，但 UX 上默认不作为玩家动作展示。

玩家说“看看会不会遇到危险”时：

- GM 层判断是否需要 roll。
- 若 roll，输出结果和原因。
- debug/gm 视图显示 table id 和 dice。

## 9. 错误文案规范

### 9.1 错误必须分层

同一个错误有三层表达：

玩家层：

```text
An 不在你当前房间。她在 H 室。
你可以先过去再谈，或在门口呼唤她。
```

GM 层：

```json
{
  "status": "needs_confirmation",
  "reason_code": "NPC_NOT_IN_CURRENT_LOCATION",
  "scope": "same_parent",
  "repair_options": [...]
}
```

debug 层：

```text
social.validate_delta: location_after must remain loc:home-mycelium-house
```

### 9.2 文案模板

实体未找到：

```text
我没找到“{query}”对应的已知对象。
可以改成更具体的名字，或从下面选择：
1. {candidate_1}
2. {candidate_2}
3. 新线索：把它当作未知对象探索
```

地点不匹配：

```text
{target} 不在你当前地点。它在 {target_location}。
你现在在 {current_location}。
可以先过去，预计 {minutes} 分钟。
```

材料不足：

```text
现在还不能完成 {project}。
缺少：{materials}
可以改为整理材料、寻找缺口材料，或取消。
```

过期 turn：

```text
当前回合已经变化，这个草案过期了。
我需要基于最新状态重新预演一次。
```

## 10. 工程实现设计

### 10.1 新增 UX 数据结构

建议新增 `rpg_engine/ux.py`：

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

UxStatus = Literal["ready", "needs_confirmation", "clarify", "blocked", "internal_error"]
UxView = Literal["player", "gm", "debug"]

@dataclass(frozen=True)
class RepairOption:
    id: str
    label: str
    description: str = ""
    action: str | None = None
    options: dict[str, Any] = field(default_factory=dict)
    effect: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = True

@dataclass(frozen=True)
class PlanStep:
    step_id: str
    action: str
    label: str
    status: UxStatus = "ready"
    options: dict[str, Any] = field(default_factory=dict)
    estimated_minutes: int | None = None
    risk_level: str = "low"
    delta_draft: dict[str, Any] | None = None

@dataclass(frozen=True)
class UxEnvelope:
    status: UxStatus
    ready_to_save: bool
    player_message: str
    interpretation: dict[str, Any] = field(default_factory=dict)
    plan: tuple[PlanStep, ...] = ()
    repair_options: tuple[RepairOption, ...] = ()
    delta_draft: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    debug: dict[str, Any] = field(default_factory=dict)
```

### 10.2 扩展 `ResolutionResult`

当前 `rpg_engine/actions/base.py` 已有：

- `ResolutionResult.status`
- `confirmations`
- `warnings`
- `proposed_delta`
- `narrative_constraints`

建议增量扩展：

```python
@dataclass(frozen=True)
class ResolutionResult:
    status: str
    facts_used: tuple[str, ...] = ()
    rules_applied: tuple[str, ...] = ()
    confirmations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    proposed_delta: dict[str, Any] | None = None
    narrative_constraints: tuple[str, ...] = ()
    player_message: str = ""
    repair_options: tuple[RepairOption, ...] = ()
    plan: tuple[PlanStep, ...] = ()
    confidence: str = "medium"
```

兼容：

- `status == "ready"` 仍表示 resolver 完全 ready。
- 旧 resolver 不提供 `repair_options` 时，runtime 生成默认 repair option。

### 10.3 扩展 `PreviewActionResult`

当前 `GMRuntime.preview_action()` 返回：

```python
PreviewActionResult(
    campaign_id,
    action,
    ok,
    markdown,
    missing_required,
    errors,
    warnings,
)
```

建议扩展为：

```python
@dataclass(frozen=True)
class PreviewActionResult:
    campaign_id: str
    action: str
    ok: bool
    status: str = "ready"
    ready_to_save: bool = False
    markdown: str = ""
    player_message: str = ""
    interpretation: dict[str, Any] = field(default_factory=dict)
    plan: tuple[PlanStep, ...] = ()
    repair_options: tuple[RepairOption, ...] = ()
    delta_draft: dict[str, Any] | None = None
    missing_required: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
```

`to_dict()` 新增：

```python
"status": self.status,
"ready_to_save": self.ready_to_save,
"player_message": self.player_message,
"interpretation": self.interpretation,
"plan": [asdict(item) for item in self.plan],
"repair_options": [asdict(item) for item in self.repair_options],
"delta_draft": self.delta_draft if self.ready_to_save else None,
```

强规则：

```python
ok = status == "ready"
ready_to_save = status == "ready" and delta_draft is not None
```

### 10.4 修改 `GMRuntime.preview_action`

当前逻辑：

```python
validation = resolver.request_contract(...)
resolution = resolver.resolve_contract(...)
markdown = resolver.preview(...)
ok = validation.ok and resolution.ok
```

目标逻辑：

```python
validation = resolver.request_contract(...)
resolution = resolver.resolve_contract(...)
markdown = resolver.preview(...)

status = normalize_ux_status(validation, resolution)
ready_to_save = status == "ready" and resolution.proposed_delta is not None

return PreviewActionResult(
    ok=status == "ready",
    status=status,
    ready_to_save=ready_to_save,
    player_message=resolution.player_message or build_player_message(...),
    plan=resolution.plan,
    repair_options=resolution.repair_options or default_repair_options(...),
    delta_draft=resolution.proposed_delta if ready_to_save else None,
    ...
)
```

注意：

- 不再鼓励从 markdown fenced JSON 提取 delta。
- `delta_draft` 成为正式结构字段。
- `markdown` 只用于人类阅读。
- `status != ready` 时，`delta_draft` 必须为 `null`。

### 10.5 新增 Intent Layer

现在 `start_turn` 已能分类 `mode/submode`，但还不是完整玩家入口。建议新增：

```python
class GMRuntime:
    def act(
        self,
        user_text: str,
        *,
        view: str = "player",
        auto_confirm_low_risk: bool = False,
    ) -> ActResult:
        ...
```

`act()` 职责：

1. 调用 `start_turn` 做上下文和初步分类。
2. 用 action resolver keywords/semantic labels 推断候选 action。
3. 对组合动作调用 planner。
4. 返回 `UxEnvelope`。
5. 若 `auto_confirm_low_risk=true` 且 `ready_to_save=true`，可选择自动 commit。默认不自动 commit。

CLI：

```bash
aigm play act ./save "找An问异常"
aigm play act ./save "去L15探索一圈再回来" --view gm
aigm play act ./save "在家盘点库存" --auto-confirm-low-risk
```

MCP：

```text
act(save, user_text, view="gm", auto_confirm_low_risk=false)
```

### 10.6 Composite Action Planner

新增 `rpg_engine/actions/planner.py`：

```python
@dataclass(frozen=True)
class CompositePlan:
    status: UxStatus
    summary: str
    steps: tuple[PlanStep, ...]
    repair_options: tuple[RepairOption, ...]
    ready_to_save: bool = False
    delta_draft: dict[str, Any] | None = None
```

最小 V1.1 支持：

| 输入 | 计划 |
|---|---|
| “去 X 找 Y 聊” | `travel/micro_travel + social` |
| “去 X 采 Y” | `travel + gather` |
| “去 X 探索一圈再回来” | `travel + explore + travel_back` |
| “在家盘点/整理/检查” | `routine` |
| “休息后做 X” | `rest + next_intent_preview`，不自动合并 commit |

V1.1 可以只返回 plan，不生成 composite delta。V1.2 再实现 atomic composite commit。

### 10.7 Resolver 改造点

#### `social.py`

新增：

- `resolve_social_scope(conn, npc, meta) -> InteractionScope`
- same parent/one hop repair options
- `player_message`
- plan step：`micro_travel` + `social`

`validate_social_delta` 保持严格：真正的 `social` delta 仍不允许偷偷移动。组合动作由 planner 或 micro-travel 前置解决。

#### `gather.py`

新增：

- intent reroute：盘点/整理/查看库存 -> `routine`
- target not current location -> repair option `travel_then_gather`
- 玩家文案替代 raw blocker

`gather` commit 仍严格要求采集目标与地点可靠解析。

#### `routine.py`

新增：

- template registry
- owned/base scope
- no-op/query-like routine 标记
- routine delta 最小字段规范

#### `travel.py`

新增：

- `micro_travel` 估时
- round-trip plan 支持
- destination repair candidates

#### `craft.py`

新增：

- 缺材料返回 crafting plan
- 材料缺口作为 structured `repair_options`
- “制作/校准/维护/整理材料”语义拆分

#### `combat.py`

新增：

- high-risk confirmation standard
- ready_state 文案
- `attack` 与 `ready/aim/observe` 区分

#### `explore.py`

新增：

- unknown lead 显式建模
- `target_kind=unknown_lead` contract
- 继续禁止普通 `target_id=null` 直接 commit

### 10.8 Schema 与文档

新增公开 schema：

```text
schemas/preview_result.schema.json
schemas/ux_envelope.schema.json
```

更新：

- [`../../specs/cli.md`](../../specs/cli.md)：加入 `play act`、`--view`、`status/ready_to_save`。
- [`../../specs/mcp-adapter.md`](../../specs/mcp-adapter.md)：加入 `act` 或扩展 `preview_action` 返回结构。
- [`../../prompts/ai-client-prompt.md`](../../prompts/ai-client-prompt.md)：要求 AI 客户端只在 `ready_to_save=true` 时提交 delta；遇到 `repair_options` 时向玩家选择。
- [`../../architecture/game-engine.md`](../../architecture/game-engine.md)：定义 UX 状态模型和 interaction scope。

### 10.9 CLI 输出

`play preview --format json`：

- 输出完整 `PreviewActionResult`。
- 非 `ready` 返回非 0，保持当前修复方向。
- 但 JSON 中要有 `status` 和 `repair_options`，方便客户端恢复。

`play preview` markdown：

- player 视图默认隐藏 debug。
- `--view gm` 显示 delta draft 和 hidden GM-only risk。
- `--view debug` 显示 resolver contract。

`play commit`：

- 错误返回应通过 `issues_from_messages` 增加 UX code。
- CLI 人类输出显示 player/gm 文案。
- debug 才显示 raw contract。

### 10.10 MCP 输出

MCP 工具默认面向 AI 客户端，建议默认 `view="gm"`，但继续尊重 visibility：

- `player_message` 不含 hidden。
- `gm_notes` 可含 hidden，但只给 GM view。
- `debug` 默认不返回，除非参数 `debug=true`。

AI 客户端规则：

```text
If ready_to_save is false, never call commit_turn.
If repair_options is non-empty, ask the player to choose one unless a low-risk default is explicitly allowed.
If status is blocked, explain the in-world reason and offer alternatives.
```

## 11. 测试计划

新增测试文件建议：

```text
tests/test_ux_preview_status.py
tests/test_interaction_scope.py
tests/test_composite_planner.py
tests/test_player_facing_errors.py
```

### 11.1 Preview 状态测试

必须覆盖：

| 用例 | 预期 |
|---|---|
| 合法 travel | `status=ready`, `ready_to_save=true`, `delta_draft != null` |
| 未知 travel 目的地 | `status=blocked`, `ready_to_save=false`, `delta_draft=null` |
| 缺 social topic/approach | `status=needs_confirmation` 或 `clarify`, no committable delta |
| NPC 同 parent 不同房间 | `status=needs_confirmation`, repair option 包含前往谈话 |
| gather 目标不在当前位置 | repair option 包含先 travel |
| 在家盘点库存 | reroute 到 `routine`, 不走 `gather` blocker |

### 11.2 Commit 严格性回归

必须继续覆盖：

- hidden clock player view 不泄漏。
- `target_id=null` 的普通 explore 不能 commit。
- `location_after=null` 的 travel 不能 commit。
- `expected_turn_id` 过期不能 commit。
- `ready_to_save=false` 的 preview result 不能被 CLI/MCP 自动提交。

### 11.3 文案测试

玩家向错误不能只包含内部字段名。测试示例：

```python
assert "location_after must remain" not in result.player_message
assert "An" in result.player_message
assert "H 室" in result.player_message
assert result.repair_options
```

debug 视图允许 raw contract。

### 11.4 UX 指标

建议在 long-run simulation 或新 report 中记录：

| 指标 | 目标 |
|---|---:|
| 合理自然语言首轮可处理率 | > 85% |
| `ready_to_save=true` 后 commit 失败率 | < 1% |
| blocked 响应提供 repair options 比例 | 100% |
| player view hidden 泄漏 | 0 |
| 玩家必须输入 entity_id 的比例 | 越低越好 |
| 低风险 routine 平均确认次数 | <= 1 |

## 12. 实施优先级

### P0：先修 UX 契约边界

1. 扩展 `PreviewActionResult`：`status`、`ready_to_save`、`repair_options`、`player_message`、`delta_draft`。
2. 保证 `status != ready` 时不返回 committable delta。
3. 更新 `GMRuntime.preview_action()`，使用 `resolution.proposed_delta` 作为结构字段。
4. 所有 resolver 的 blocker 返回 repair option。
5. CLI/MCP/AI prompt 明确：只有 `ready_to_save=true` 才能 commit。
6. player/gm/debug 输出分离。

验收：

```bash
python3 -m unittest tests.test_v1_cli tests.test_runtime -v
python3 -m unittest tests.test_ux_preview_status -v
```

### P1：解决当前实战 UX 痛点

1. `social` 支持 same parent micro-travel repair。
2. `routine` template registry。
3. “在家盘点/整理/检查”归入 routine。
4. `gather` target/location blocker 改成世界内 repair。
5. scene affordance 输出。
6. `craft` 缺材料计划。

验收场景：

```text
找An问异常
在家盘点库存
检查农田
制作火药箭
去L1小溪收鱼笼
```

这些输入不要求玩家知道 entity id。

### P2：自然语言主入口

1. 新增 `play act`。
2. 复用 `start_turn`、resolver keywords、可见实体名/别名做保守意图推断。
3. 单动作输入直接转为 `preview_action`。
4. 低风险日常输入转为 `routine`。
5. 默认不自动 commit；`auto_confirm_low_risk` 只作为后续策略入口。

### P3：组合动作和更强 GM 裁决

1. Composite planner 支持 `travel + social`、`travel + gather`、`travel + explore`。
2. round-trip plan 支持“去 X 探索一圈再回来”。
3. unknown lead 显式建模：默认未知 explore 仍阻断；只有显式 `unknown_lead` 才能保存为未知线索。
4. Composite plan 第一阶段只返回 plan 和 repair options，不做原子 composite commit。
5. 组合动作拆步保存，继续由每个 resolver 的 delta contract 严格把关。

### P4：可运营体验与长期优化入口

1. player/gm/debug 参数进入 CLI/runtime 入口；debug 细节不作为默认玩家输出。
2. `ux-metrics` 输出基础 UX 指标：当前 turn、地点、intent 分布、场景可行动数量。
3. 一键 undo/rollback、完整 Web UI、长期偏好系统不进入 V1.1 内核交付；只作为后续独立设计。
4. 语义别名学习先通过可见实体名/alias 解析和 doctor/metrics 暴露问题，不自动改剧本。
5. 所有新增入口必须保持 `ready_to_save` 边界：不可保存的 plan 不能返回 committable delta。

## 13. 关键验收剧本

### 13.1 找 An 问异常

输入：

```text
找An问异常
```

若玩家在 `house`，An 在 `h-room`：

预期：

- `status=needs_confirmation`
- `ready_to_save=false`
- `repair_options` 包含：
  - 去 H 室找 An 谈
  - 在门口呼唤 An
  - 取消
- 玩家文案说明 An 的位置和移动成本。
- 不泄漏 hidden clock。

确认“去 H 室找 An 谈”后：

- planner 生成 `micro_travel + social`。
- 可拆为两个 ready preview 或 composite ready plan。
- commit 严格写入位置和社交事件。

### 13.2 在家盘点库存

输入：

```text
在家盘点库存
```

预期：

- 不走 `gather`。
- `action=routine`
- `status=ready` 或 no-op query result。
- 若不改变状态，`ready_to_save=false` 但不是错误，返回库存摘要。
- 若记录“完成盘点”，生成 routine delta。

### 13.3 去草原边缘探索一圈再回来

输入：

```text
去L15草原边缘探索一圈再回来
```

预期：

- `status=needs_confirmation`
- plan:
  - travel out
  - explore
  - travel back
- 展示总耗时、风险、天色影响。
- 不自动 commit 三步，除非玩家确认。

### 13.4 制作火药箭

输入：

```text
制作火药箭
```

材料齐：

- `ready`
- 展示耗时、材料消耗、风险。

材料不足：

- `blocked` 或 `needs_confirmation`
- 不给 committable delta。
- repair options：
  - 查缺口材料
  - 去对应地点采集
  - 改做普通维护

## 14. 与现有架构的兼容性

这套 UX 设计不要求推翻现有架构。它依赖并强化当前结构：

- `GMRuntime` 继续作为 CLI/MCP 唯一主门面。
- `ActionResolverSpec` 继续承载 preview/request/resolve/delta contract。
- `validate_delta` 与 `commit_turn` 继续共用 runtime contract。
- `save validate`、projection、cards、search、hidden visibility 继续保持严格。
- `BUG_REPORT_2026-06-30.md` 中已修复的安全边界不得回退。

真正变化是：

1. `preview` 结果从单一布尔升级为 UX 状态。
2. resolver 从“报 blocker”升级为“报 blocker + repair options”。
3. 玩家入口从“指定 action/options”升级为“自然意图 -> GM plan”。
4. debug 信息从默认输出中下沉。

## 15. 不建议做的事

- 不建议降低 `commit` 严格性来换取表面流畅。
- 不建议让 AI 直接写 SQLite 或绕过 delta。
- 不建议把 hidden clock 暴露给 player view 作为“解释”。
- 不建议所有动作都自动确认，尤其是 combat、trade、resource spend。
- 不建议只改报错文案而不改 `ready_to_save` 契约。
- 不建议把 `routine` 做成万能绕过口；它仍必须有明确低风险边界。

## 16. 最终判断

AIGM 游戏的 UX 不是“让玩家做任何事”，也不是“让规则系统拒绝一切不标准输入”。优秀体验来自中间层：

```text
玩家表达自由
GM 裁决清楚
预演影响透明
落盘状态严格
错误可以恢复
```

当前 AIGM Kernel 已经有足够强的结构化底座。下一阶段最重要的不是继续加更多 resolver，而是把现有 resolver 包装成一个会解释、会补全、会给选择的 GM。

只有这样，系统的严格性才会被玩家感知为“世界可信”，而不是“命令难用”。
