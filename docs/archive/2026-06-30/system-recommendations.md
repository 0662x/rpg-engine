# AIGM 系统建议报告

文档状态：**RECOMMENDATION：基于当前代码、治理文档与 AI GM 资料的系统建议**  
日期：2026-06-30  
适用范围：`rpg_engine`、Campaign Package、Save Package、GMRuntime、Context Pipeline、Memory、Palette、Proposal、AI Client Prompt  
关联文档：`AIGM_CONTENT_GENERATION_GOVERNANCE.md`、`AIGM_UX_DESIGN_2026-06-30.md`、`ARCHITECTURE_REVIEW.md`、`AI_CLIENT_PROMPT.md`

同步状态：**已按 2026-06-30 最新代码与本轮实现重新核对**  
本次同步重点：`rpg_engine/ai` 统一 AI Helper Layer、`semantic_ai` / `reflection` 迁移、commit 后可选 Archivist suggestions、`memory suggest --store/--enqueue`、动态 `context_budget_policy`、`discovery_states` context collector、`proposal_queue` 维护报告/拒绝原因/批量 review/回滚辅助、`travel/craft` palette 合约、`small_cn_campaign` 随机表/palette/中文自然输入体验契约。

验证状态：`python3 -m unittest discover tests` 已通过，194 tests OK。

## 1. 核心结论

优秀 AIGM 不是“把更多上下文塞给模型”，而是以下五层协作：

```text
Narrator 叙事模型
  + Kernel 结构化状态
  + Context/Memory 动态召回
  + Tools/Resolvers 工具调用
  + Governance 人类/规则边界
```

当前系统方向是正确的：`preview_action -> validate_delta -> commit_turn` 已经把“AI 可以讲故事”和“事实必须结构化落盘”分开了。真正应该继续加强的不是单纯扩大上下文，而是把本轮已经落地的治理基础继续产品化：

- 把后台 Archivist / Context Curator 从手动建议命令推进为可审计后台流程；本轮已支持 commit 后可选生成并进入 proposal 待审。
- 继续约束 `semantic_ai`、`reflection AI` 和 Archivist 必须走统一 AI Helper Layer。
- 继续调优动态上下文预算和高信号 section 保留策略。
- 继续增强 palette、random table、unknown lead 的一等玩法合约。
- 把已落地的 proposal/review 队列做成更完整的内容维护流程；本轮已补报告、拒绝原因、批量 review 和回滚提示。
- 让中文玩家自然表达时，系统更会理解、补别名、给修复选项；本轮已覆盖“找草药”进入 gather、“做草药包”保持 craft。

截至本次同步，系统已经完成一批之前建议中的 P0/P1 内容治理工作，并补上了本报告原先列出的几个关键缺口：

- `campaign.yaml.content.palettes` 已进入 schema 和 validator。
- `small_cn_campaign` 已显式声明 `materials / encounters / factions / locations / species` palette 文件。
- `random_tables.yaml` 已在多个结果 payload 中携带 `palette_id`。
- `gather`、`explore`、`social` 已能消费 `palette_id`，并要求 delta payload 保留来源。
- `content from-palette` 已能把候选素材转成 `review_required` 的内容草案。
- `validate_content_delta` 已对 faction/location/world_setting/route/rule/rare species 等高影响写入输出 warning。
- `rpg_engine/ai` 已成为统一 AI Helper Layer 基础：`semantic_ai`、`reflection --ai hermes` 和 Archivist 建议共享 provider、task、policy、audit 边界。
- `memory suggest` 已提供后台 Archivist 建议入口，输出 advisory 结构化 JSON，不直接写事实。
- 动态 `context_budget_policy` 已落地；未显式传 budget 时，探索/采集/旅行/制作会使用更高预算并保留 `palette_candidates`。
- `travel`、`craft` 已支持 `--palette-id`，分别生成旅行线索/制作计划，不直接创建 route、location、库存或产物事实。
- `discovery_states` 已通过迁移落库，palette/unknown-lead 事件提交后会派生结构化发现状态。
- `proposal_queue` 已落库，并提供 `proposal create/list/review/apply`。
- `apply-content-delta --strict-review` 已能阻止未人工 review 的高影响内容，并把内容 delta 入队。
- `play commit --archivist-suggest` 已能在提交后存储 Archivist suggestion，并可把 memory/alias/lead/contradiction 建议投递到 `proposal_queue`。
- `memory suggest --store/--enqueue` 已支持手动存储/入队 Archivist 建议。
- `context builder` 已读取 `discovery_states`，把 hinted/known 且未归档的线索作为 `discovery_states` section 召回，并明确标注不是事实。
- `proposal_queue` 已补 `report`、`review --reason`、`batch-review`、`rollback-plan` 和 apply 前 backup id 回写。
- `small_cn_campaign` 已增加制作前材料确认随机表、旅行中的 species 风险线索、locked 且不允许提前露线索的材料候选，并扩展中文自然输入测试。

因此，新的开发重心不再是“让 palette/discovery/proposal/AI helper 形成闭环基础”，而是继续深化：把 memory/alias proposal 的实际 apply 工作流产品化，把 discovery_state 的多源确认/归档维护做完整，把 proposal queue 接入更友好的维护 UI/批处理，并继续扩充中文沙盒的内容密度和自然语言样例。

## 2. 外部经验对本系统的启发

### 2.1 AI GM 需要工具和结构化状态

`Enhancing AI Game Masters with Function Calling` 指出，LLM 做 GM 时容易偏离规则和状态；引入函数调用和游戏专用控制后，叙事质量和状态一致性会更好。  
来源：<https://arxiv.org/abs/2409.06949>

对本系统的建议：

- 保留并强化 `GMRuntime`、Action Resolver、delta schema、random table、clock、inventory、route。
- AI 叙事不能直接成为权威事实。
- `preview/validate/commit` 是正确主线，不应退回“纯聊天保存”。

### 2.2 Narrator 和 Archivist 应分离

`Static Vs. Agentic Game Master AI` 的 v2 使用多代理架构，把 narrator 和 archivist 分开，改善了模块化、沉浸感和游戏体验。  
来源：<https://arxiv.org/abs/2502.19519>

对本系统的建议：

- 前台 AI GM 是 Narrator，负责即时叙事、语气、玩家可见反馈。
- 后台轻量 AI 是 Archivist / Context Curator，负责摘要、线索、别名、记忆、风险提示。
- Archivist 只能提案，不能直接写入权威事实源。

### 2.3 记忆靠摘要和检索，不靠完整历史

AI Dungeon 的 Memory System 使用 Auto Summarization、Memory Bank、Story Cards 等机制自动保存和召回关键信息。  
来源：<https://help.aidungeon.com/faq/the-memory-system>  
上下文组成说明：<https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai>

对本系统的建议：

- 最近事件保留高细节，旧事件进入摘要。
- 长期记忆按当前行动和实体动态召回。
- 角色卡、世界设定、候选素材不应全量常驻，而应被触发加载。

### 2.4 给 DM/AI 的应是短小可用信息

`CALYPSO` 研究强调，DM 辅助系统应提供 bite-sized prose：短小、场景相关、可直接使用，而不是长篇 lore。  
来源：<https://arxiv.org/abs/2308.07540>

对本系统的建议：

- `world_settings_core`、`palette_candidates`、`recent_events` 应保持短、高密度、可裁决。
- 大段世界观应留在内容包和维护视图，不应塞进普通玩家回合。
- AI GM 每回合需要的是“能裁决这回合的信息”，不是整本设定集。

### 2.5 状态跟踪是 AI RPG 的核心难题

`Dungeons and Dragons as a Dialog Challenge` 把 D&D 建模为对话生成和 game state tracking 双任务，并指出状态信息会影响生成质量。  
来源：<https://arxiv.org/abs/2210.07109>

对本系统的建议：

- UX 核心不是“文笔更华丽”，而是系统稳定知道：谁、在哪里、有什么、发生了什么、是否可以保存。
- `save validate`、投影校验、delta 合约、visibility 边界都属于体验质量的一部分。

## 3. 当前系统已经做对的部分

### 3.1 核心写入链路方向正确

当前 `GMRuntime` 已有：

```text
start_turn -> preview_action -> validate_delta -> commit_turn
```

这正符合 AI GM function calling 的经验：AI 可以生成叙事和草案，但实际状态变化必须通过结构化工具、校验和提交。

### 3.2 上下文不是静态拼接

当前 `context_builder.py` 和 `rpg_engine/context/` 已经具备：

- 自动分类 `query/action/maintenance`。
- 实体命中和相关实体扩展。
- routes、palettes、world_settings、recent_events、memory_summaries collector。
- section priority 和 token budget 裁剪。
- `loaded_items` / `omitted_items` 可审计。

这是正确的动态上下文方向。

### 3.3 记忆系统已有基础

`memory.py` 已有确定性 memory rebuild：

- day summary
- current-world summary
- character memory
- project memory
- faction/species memory

这说明系统已经有 Archivist 的数据地基。本轮已新增 `rpg_engine/archivist.py`、`memory suggest --store/--enqueue` 和 `play commit --archivist-suggest`，完成“只输出结构化提案、不写事实，并进入待审队列”的第一版；后续仍需把 memory/alias proposal 的实际应用、回滚和 UI 流程产品化。

### 3.4 Palette 已经不只是文档概念

`palette.py` 已支持：

- 自动读取 `content/palettes/*.yaml`
- 读取 `campaign.yaml.content.palettes` 显式 manifest
- `available / confirm_required / clue_only / locked / out_of_context`
- 按地点、生态、意图、解锁条件筛选
- `palette_candidate_payload`
- `palette_entry_to_entity`

当前最新代码已经进一步完成：

- `campaign_validation.py` 会校验 palette 文件、字段、引用位置、状态、保存目标等。
- `resources/schemas/campaign.schema.json` 已支持 `content.palettes`。
- `small_cn_campaign` 已包含 `content/palettes/materials.yaml`、`encounters.yaml`、`factions.yaml`、`locations.yaml`、`species.yaml`。
- `gather` resolver 能消费 `palette_id` 并生成带来源的草案 delta。
- `explore` resolver 能消费 `palette_id`，并把候选素材保存为可观察线索，而不是直接创建事实实体。
- `social` resolver 能消费 `palette_id`，并约束其作为传闻/话题，不直接确认派系或文明事实。
- `runtime.py` 已能从部分随机表 payload 中前置提取 `palette_id` 进入 action options。
- `travel` resolver 能消费 location palette，生成旅行线索/找路计划，不直接 upsert route 或移动到候选地点。
- `craft` resolver 能消费 material/recipe palette，生成制作候选计划，不直接消耗材料或创建产物。
- `tests/test_palette_governance.py` 已覆盖 palette 校验、动态上下文候选保留、gather 合约、clue_only explore 不创建实体、travel/craft palette 合约、discovery_state 写入、from-palette review 标记、strict review 入队和 proposal approve/apply。
- `context builder` 已读取 `discovery_states`，把探索/采集/旅行留下的线索阶段作为可召回上下文，并明确提示“线索不是事实”。
- `small_cn_campaign` 已继续补随机表和 palette 覆盖：旅行表引用 species 风险，新增 `table:craft-material-check`，新增 locked 且不可提前露线索的 `pal:mat:sealed-copper-dust`。

当前剩余缺口：

- runtime 从 random table payload 自动进入 preview 时，仍应继续加强 action/submode 的 kind/status 防错。
- `craft` 目前覆盖 material 和 save_as recipe/project 的计划边界，正式 recipe 内容类型和产物审稿流程仍可继续增强。
- Archivist 已支持 commit 后可选 suggest/入队，但 `memory_update`、`alias_suggestion` 的实际 apply-suggestions 工作流仍待设计。

### 3.5 UX 状态和修复选项方向正确

`PreviewActionResult` 已经区分：

- `status`
- `ready_to_save`
- `player_message`
- `repair_options`
- `warnings`
- `delta_draft`

这能把严格性留在写入层，而不是直接惩罚玩家表达。

### 3.6 AI 接口已收敛到统一 Helper 基础层

当前系统已有几个 AI 相关接口：

- `semantic_ai=hermes`：用于 `start_turn/context build` 中的语义判断、目标识别和别名缺口提示。
- `reflection draft --ai hermes`：用于单个实体的长期反思草案。
- `memory suggest --ai hermes|off`：用于后台 Archivist 建议，默认可关闭；输出 advisory 结构化提案。
- 外部 AI Client：通过 MCP/CLI 调用内核，负责前台 Narrator 叙事。

这些能力的共同点是：都能输出有价值的辅助判断，但都不能直接成为权威事实。本轮已新增 `rpg_engine/ai/provider.py`、`tasks.py`、`schemas.py`、`policy.py`、`audit.py`，让 `semantic_ai`、`reflection` 和 Archivist 共享 provider、JSON 解析、timeout、fail-closed、advisory、no-write 和 audit 边界。

因此后续不应再继续零散增加 AI 调用点；新增 AI 辅助任务应先进入 AI Helper Layer，并明确 task schema、失败策略和写入边界。

### 3.7 内容治理已有持久队列基础，但维护体验仍需深化

最新代码已经把内容生产从“纯建议”推进到了可执行工具：

- `content_factory.py` 支持 `make_content_delta_from_palette`。
- `content from-palette` 生成的 delta 会写入 `meta.palette_id`、`meta.palette_status`、`meta.review_required=true`、`meta.high_impact`。
- `content_validation.py` 已输出高影响 warning，并提示需要 `meta.review_required=true` 或 `meta.reviewed_by`。
- 现有 `proposal.py` 仍保留一次性 `proposal validate` 工具。
- 新增 `proposal_queue.py` 和 `proposal_queue` 表，支持 `proposal create/list/review/apply`。
- `apply-content-delta --strict-review` 会阻止未 `reviewed_by` 的高影响内容，并将其入队。
- `proposal report`、`review --reason`、`batch-review` 和 `rollback-plan` 已落地；`proposal apply` 会把 apply 前 backup id 写入 rollback hint。

这说明系统已经具备内容治理闭环的基础：候选素材 -> 内容草案 -> warning -> 入队 -> 审批 -> apply -> 回滚提示。后续重点应转为更细的结构化报告、memory/alias proposal apply、UI/批处理体验和运行中内容沉淀。

## 4. 当前最值得采纳的建议

### 建议 1：正式引入后台 Archivist，但只给提案权

优先级：**P1/P2，强烈建议采纳**

当前状态：**基础版已落地并已接入可选后台流程**。已新增 `rpg_engine/archivist.py`、`archivist.schema.json`、`memory suggest --store/--enqueue` 和 `play commit --archivist-suggest`，默认关闭 AI，输出 advisory 结构化建议，不直接写权威事实。commit 后可选生成 suggestions，并可进入 `proposal_queue` 待审。尚未提供 `memory apply-suggestions` 或 alias proposal 的实际 apply 流程。

当前 memory 事实摘要仍主要依赖手工/命令式 rebuild；Archivist suggestions 已可在 commit 后可选生成，但只是待审建议，不直接改 memory。建议继续把受限后台角色产品化：

```text
commit_turn 成功
  -> Archivist 输入本回合 delta、事件、实体变化、当前场景
  -> 输出结构化 JSON 提案
  -> schema 校验
  -> 低风险写入 memory
  -> 高风险进入 proposal/review 队列
```

Archivist 输出建议：

```json
{
  "turn_summary": "...",
  "memory_candidates": [],
  "entity_alias_suggestions": [],
  "unresolved_leads": [],
  "possible_contradictions": [],
  "next_context_hints": [],
  "review_required": []
}
```

边界：

- 不能直接 upsert entity。
- 不能直接改 inventory、location、clock、relationship。
- 不能把 hidden 转 known。
- 所有事实写入仍走 `validate_delta`、`content_delta` 或 proposal review。

工程路径状态：

1. 已完成：新增 `rpg_engine/archivist.py`。
2. 已完成：新增 `archivist.schema.json`。
3. 已完成：已提供手动 `memory suggest`，并支持 `--store/--enqueue`。
4. 已完成：`play commit --archivist-suggest` 可在提交后可选触发 Archivist workflow。
5. 已完成基础：Archivist 输出可自动进入 `proposal_queue`；`memory apply-suggestions` 和 alias apply 待设计。

### 建议 2：整合现有 AI 接口为统一 AI Helper Layer

优先级：**P1，强烈建议采纳**

当前状态：**基础版已落地**。`semantic_ai`、`reflection --ai hermes` 和 Archivist 建议已通过 `rpg_engine/ai` 统一 provider/task/policy/audit。外部 Narrator 仍由 AI Client 通过 MCP/CLI 驱动，不进入内核写事实。

当前不建议把几个 AI 接口合成一个“万能后台大脑”。更合理的方式是新增一个统一辅助层，让所有模型调用共享 provider、schema、policy 和 audit。

建议模块结构：

```text
rpg_engine/ai/
  provider.py   # 统一 hermes / future provider 调用
  tasks.py      # semantic、reflection、archivist 等任务定义
  schemas.py    # 每类 AI 输出 dataclass/schema/validator
  policy.py     # timeout、fail closed、advisory、no-write 边界
  audit.py      # 记录输入摘要、输出摘要、错误和耗时
```

统一后的角色关系：

```text
Semantic AI
  - 触发：start_turn/context build
  - 作用：理解玩家输入、补目标、识别别名缺口
  - 输出：SemanticSuggestion

Narrator AI
  - 触发：外部 AI Client
  - 作用：前台叙事、玩家可见表达
  - 输出：自然语言回复和结构化 delta 草案

Archivist AI
  - 触发：commit_turn 成功后
  - 作用：整理回合、提记忆、提别名、提线索、提矛盾
  - 输出：ArchivistSuggestion

Reflection AI
  - 触发：维护命令或 Archivist 子任务
  - 作用：为单个实体生成长期摘要草案
  - 输出：ReflectionDraft
```

统一安全边界：

- 默认关闭，显式配置后才启用。
- 超时、失败、非 JSON、schema 不通过时 fail closed。
- 输出必须标记为 advisory。
- AI Helper 不能直接写 DB。
- AI Helper 不能覆盖 SQLite、resolver、validator 或玩家确认。
- 所有高风险输出进入 proposal/review，不直接落地。
- 所有模型输入应使用摘要和白名单字段，不把完整 hidden 信息随意发给模型。

工程路径状态：

1. 已完成：`context/semantic.py` 和 `reflection.py` 已改为调用 `rpg_engine/ai/provider.py`。
2. 已完成：新增 `AIHelperTask`、`SemanticSuggestion`、`ReflectionAIOutput`、`ArchivistSuggestion` 等基础结构。
3. 部分完成：统一 JSON parser、timeout、fail-closed、deterministic fallback 已有；更严格的 JSON Schema 运行时校验仍可增强。
4. 已完成：`semantic_ai` 和 `reflection draft --ai hermes` 行为保持兼容。
5. 已完成：Archivist 第一版只输出建议报告，不直接写事实库。
6. 已完成基础：Archivist 输出可接入 proposal queue；memory/alias apply 工作流待补。

验收：

- 关闭 AI 时，核心路径完全可运行。
- fake `hermes` 测试能覆盖 semantic/reflection/archivist 三类 task。
- 模型返回坏 JSON 时不影响 `validate/init/query/preview/commit`。
- AI 输出不会直接改 `entities/items/clocks/relationships/current_location`。

### 建议 3：把上下文预算改为动态档位

优先级：**P0/P1，强烈建议采纳**

当前状态：**基础版已落地**。新增 `rpg_engine/context/budget.py`；未显式传 `--budget` 时，`start_turn/context build` 会按 mode/submode 使用策略预算，探索/采集/旅行/制作默认保留 `palette_candidates`。显式传 `--budget` 时仍尊重调用方预算，便于调试和回归测试。

当前预算是静态配置或 CLI 参数。对普通查询够用，但对探索、采集、新内容候选偏紧。

建议默认档位：

| 场景 | 建议预算 |
|---|---:|
| 普通实体查询 | 3000-3600 |
| 场景查询 | 3000-4000 |
| 普通行动 | 4200-5200 |
| 社交/交易/路线/战斗 | 4800-6000 |
| 探索/采集/新内容生成 | 5500-7000 |
| 内容维护/世界扩展 | 7000-10000 |
| 审计/调试 | 12000+ |

建议 section 预算：

| 层 | 内容 | 建议长度 |
|---|---|---:|
| 永久核心 | system rules、玩家状态、当前场景、保存边界 | 800-1200 tokens |
| 当前回合 | 玩家输入、解析意图、缺失项、必要流程 | 400-800 |
| 相关实体 | 直接命中实体 + 1 层关系 | 1200-2500 |
| 世界约束 | compact world settings | 300-800 |
| 候选素材 | palette / random table 候选 | 300-1000 |
| 近期历史 | 最近 4-8 个相关事件 | 400-1000 |
| 长期记忆 | 3-6 条检索记忆 + 总摘要 | 500-1200 |

工程路径状态：

1. 已完成：新增 `context_budget_policy`。
2. 已完成：未传 budget 时使用策略值和 campaign 默认值取较高值。
3. 已完成：对 `explore/gather/travel/craft` 提升并保留 `palette_candidates`。
4. 已有基础：action 已保留 `world_settings_core`；裁剪策略仍可继续细化。
5. 已完成：context result 输出 `budget.policy_profile`、`budget.policy_reason`、`requested` 和 `campaign_default`。

验收：

- 探索/采集回合默认包含 `palette_candidates`。
- 普通查询不会因为预算上升而塞入无关大段设定。
- `budget.trimmed` 为 true 时，玩家关键裁决信息仍保留。

### 建议 4：补齐 palette 一等玩法合约的剩余部分

优先级：**P1，强烈建议采纳**

当前状态：**基础版已落地**。`travel` 和 `craft` 已补上 `--palette-id` 合约，并纳入 `tests/test_palette_governance.py`。

当前 `content.palettes`、示例 palette、validator/schema、`gather/explore/social` 的 `palette_id` 已经落地。后续不应重复建设基础能力，而应把剩余 action 和发现阶段补完整：

| Action | palette 行为 |
|---|---|
| `gather` | 已实现 `palette_id` 合约；继续强化数量、品质、资源状态和 `confirm_required` 校验 |
| `explore` | 已实现 `palette_id` 合约；候选素材生成 clue event，不直接确认事实 |
| `social` | 已实现 `palette_id` 合约；候选素材作为询问话题或传闻，不直接确认派系 |
| `travel` | 已实现；消费 location lead，生成找路/确认路线 clue/plan，不直接新增 route，不直接移动到候选地点 |
| `craft` | 已实现；消费 material/recipe candidate，生成制作计划；产物和消耗必须由后续 delta 明确表达 |

工程路径状态：

1. 已完成：扩展 `tests/test_palette_governance.py`，作为 palette 合约主测试。
2. 已完成：`travel` 增加 `--palette-id`，只允许把 location palette 变成路线线索/计划，不直接 upsert route。
3. 已完成：`craft` 增加 `--palette-id`，只允许 material/recipe palette 参与计划或草案，实际消耗和产物必须走 delta。
4. `validate_delta` 继续强化：`clue_only` 不得直接创建 known entity、库存或 route。
5. runtime 从 random table payload 提取 `palette_id` 时，应根据 action/submode 做 kind/status 校验。
6. 已完成：context builder 在 `explore/gather/travel/craft` 时提高并保留 `palette_candidates`。
7. 已完成：palette event payload 已接入 `discovery_states`，context builder 已把 discovery_state 作为 `discovery_states` section 召回。

示例 payload：

```json
{
  "palette_id": "pal:loc:bridge-underpass",
  "palette_kind": "location",
  "palette_status": "clue_only",
  "source": "palette",
  "needs_gm_resolution": true,
  "clue_stage": "hinted"
}
```

### 建议 5：新增 discovery_state，替代“靠 event 和 visibility 约定”

优先级：**P2，建议采纳**

当前状态：**基础版已落地并已接入上下文召回**。新增迁移 `0004_discovery_proposals.sql` 和 `discovery_states` 表；`save_turn_delta` 会从 palette/unknown-lead 事件 payload 派生 discovery state。context builder 现在会读取 hinted/known 且未归档的 discovery state，作为 `Discovery Leads` section 召回，并明确标注不是已确认事实。

现在多阶段发现主要靠 event、visibility、details 和人工约定模拟。随着 AIGM 内容增长，这会变脆。

建议新增表：

```sql
create table discovery_states (
  id text primary key,
  subject_id text,
  palette_id text,
  kind text not null,
  stage text not null,
  visibility text not null,
  evidence_count integer not null default 0,
  confirmation_methods_json text not null default '[]',
  source_event_ids_json text not null default '[]',
  created_turn_id text,
  updated_turn_id text,
  notes text,
  created_at text not null,
  updated_at text not null
);
```

推荐 stage：

```text
rumor -> clue -> sampled -> confirmed -> archived
```

用途：

- 区分“玩家听说过”和“玩家确认了”。
- 防止 hidden/legendary 内容一步变 known。
- 支撑多源确认：遗迹证据、NPC 证词、采样、研究、交易。

### 建议 6：给 content delta 增加高影响 warning/approval

优先级：**P1，强烈建议采纳**

当前状态：**基础版已落地**。`apply-content-delta` 会打印 warnings；新增 `--strict-review`，遇到未 `reviewed_by` 的高影响 content delta 会阻止 apply，并自动写入 `proposal_queue`。

当前 `validate_content_delta` 已经返回高影响 warnings，且 `content from-palette` 会生成 `meta.review_required=true`。这个方向正确，下一步应该从“能提示”升级为“可治理”。

高影响内容：

- world_setting
- rule
- location
- route
- faction / faction_state
- rare/hidden/legendary species
- hidden/hinted -> known

示例 warning：

```text
warning: upsert_entities[0] creates high-impact faction; require meta.review_required=true or meta.reviewed_by
```

已完成：

1. `ContentValidationResult` 已包含 `warnings`。
2. `validate_content_delta` 已检测高影响写入。
3. `content validate-delta` 已打印 warnings。
4. `content from-palette` 已默认携带 `meta.review_required=true`。
5. `apply-content-delta --strict-review` 已能阻止未人工 review 的高影响 delta。
6. 高影响 delta 已可自动入 `proposal_queue`。

剩余工程路径：

1. 已完成：`apply-content-delta` 默认允许 warnings，并打印高影响摘要。
2. 已完成：`--strict-review` 会要求人工 review。
3. 待增强：high-impact warning 可继续输出更细的结构化 JSON，便于 UI 消费。
4. 已完成基础：`meta.review_required=true` 会触发 proposal queue 入队。
5. 部分完成：已有 strict review / proposal queue 测试；route/rule/world_setting/visibility promotion 可继续扩充覆盖。

这能防止 AI 把“新文明、新势力、新世界规则”当成普通实体创建。

### 建议 7：把 proposal validate 扩展为持久审稿队列

优先级：**P2/P3，建议采纳**

当前状态：**基础版已落地并补齐维护命令**。保留 `proposal validate`，新增持久 `proposal_queue` 表和 `proposal create/list/review/apply/report/batch-review/rollback-plan` CLI。`proposal apply` 当前支持 approved `content_delta`，并复用 `apply_content_delta`，不开新写入通道；apply 前 backup id 会写入 rollback hint。

当前 `proposal validate` 是一次性工具，适合开发调试，但不适合真实 AIGM 长期运行。

建议新增 proposal queue：

```text
aigm proposal create ./save ./proposal.json
aigm proposal list ./save --status needs_review
aigm proposal review ./save proposal:000123 --approve --reason "人工核对通过"
aigm proposal batch-review ./save --status needs_review --reject --reviewed-by gm --reason "证据不足"
aigm proposal report ./save
aigm proposal rollback-plan ./save proposal:000123
aigm proposal apply ./save proposal:000123
```

队列表字段建议：

- `id`
- `kind`：turn_delta / content_delta / memory_update / alias_suggestion
- `status`：draft / needs_review / approved / rejected / applied
- `risk_level`
- `source_turn_id`
- `payload_json`
- `validation_json`
- `reviewed_by`
- `review_reason`
- `applied_turn_id`
- `rollback_hint_json`
- `created_at`
- `updated_at`

边界：

- 未 approved 不能 apply。
- 高风险 proposal 必须人工或 strict review。
- proposal apply 仍调用现有 validate/commit/apply-content-delta，不开新写入通道。

剩余工程路径：

- `turn_delta`、`memory_update`、`alias_suggestion` 的 apply 仍需按各自写入通道设计，不能共用 content_delta apply。
- 把 proposal queue 的报告、批量 review 和回滚计划接入更友好的维护 UI。
- 继续扩充 high-impact 结构化风险字段，方便 UI 做筛选。

### 建议 8：为中文玩家强化别名、语义桥接和误操作恢复

优先级：**P1，强烈建议采纳**

你的玩家主要是中文玩家。中文自由输入常见问题：

- 省略主语：“去看看那个”
- 指代词：“刚才那个东西”
- 近义词：“找草药 / 采药 / 摘点能用的叶子”
- 夹杂英文/代码/攻击语
- 错别字和口语

当前系统已有中文关键词和 `semantic_ai` 可选辅助，但建议继续加强：

1. Archivist 提 alias suggestions。
2. context audit 记录未命中查询。
3. `campaign doctor` 报告高频未命中词。
4. 对同义动作建立中文短语库；本轮已补资源搜索词，使“找草药/找芦苇”进入 gather，同时“做草药包”仍保持 craft。
5. `repair_options` 用中文玩家语言表达，而不是 schema 字段。

验收：

- 玩家说“找草药”能进入 gather，而不是 social 或泛化 explore。
- 玩家说“那个”时能给候选列表，不硬猜。
- 恶意/越权输入进入 blocked 或 maintenance，不污染事实。

### 建议 9：继续把示例剧本打磨成真正的 AIGM 小沙盒

优先级：**P0，强烈建议采纳**

`small_cn_campaign` 是中文玩家体验的门面。最新代码已经补上：

```text
content/palettes/
  materials.yaml
  encounters.yaml
  factions.yaml
  locations.yaml
  species.yaml
```

并且 `campaign.yaml` 已显式声明这些 palette 文件，`random_tables.yaml` 已在多个结果 payload 中引用 `palette_id`。

本轮继续补强：

- `table:travel-risk` 增加 species 风险线索，引用 `pal:species:reed-leech`。
- 新增 `table:craft-material-check`，覆盖草药包、过滤垫、信号架修复、河泥封缝等制作前确认。
- 新增 `pal:mat:sealed-copper-dust`，覆盖 locked 且不允许提前作为 clue 投放的材料边界。
- 增加中文自然输入体验测试：`找草药` -> gather，`做个草药包` -> craft。

下一步不是从零补 palette，而是继续打磨“可玩的小沙盒”：

- `table:camp-rumor`
- `table:travel-risk`
- `table:explore-discovery`
- `table:gather-yield`
- `table:gather-complication`
- `table:social-reaction`
- `table:minor-cost`

建议继续补：

- 每个核心地点至少 3-5 个可触发候选。
- 每类 palette 继续扩展 `available / confirm_required / clue_only / locked` 覆盖；material 已有 direct、confirm_required、clue_only、locked 对照。
- 中文玩家常用表达样例进入 `sample_texts` 或测试。
- 每个高影响候选都能通过 `content from-palette` 生成 review 草案。
- 随机表 payload 和 action contract 保持一致，不出现“roll 到了但 resolver 不能消费”的素材。

验收：

```bash
aigm campaign validate rpg_engine/resources/examples/small_cn_campaign
aigm campaign test rpg_engine/resources/examples/small_cn_campaign
aigm save init rpg_engine/resources/examples/small_cn_campaign /tmp/aigm-small-cn-save --force
aigm play start-turn /tmp/aigm-small-cn-save --user-text "在营地附近找草药" --submode gather
aigm palette suggest /tmp/aigm-small-cn-save --kind all --location loc:camp --intent explore
aigm play preview /tmp/aigm-small-cn-save explore --palette-id pal:faction:bridge-wardens --location loc:old-bridge
aigm content from-palette /tmp/aigm-small-cn-save pal:faction:bridge-wardens --output /tmp/bridge-wardens.delta.json
aigm content validate-delta /tmp/aigm-small-cn-save /tmp/bridge-wardens.delta.json
```

### 建议 10：普通玩家入口继续隐藏 admin/legacy

优先级：**P1，建议采纳**

`ARCHITECTURE_REVIEW.md` 已指出 `cli.py` 仍偏大，admin/legacy 能力集中在同一个入口里。建议继续收敛：

- 普通玩家路径只暴露 campaign/save/play/mcp。
- migration、package、plugin、importer、projection repair 放到 admin 子命令或隐藏入口。
- MCP 不暴露 admin/repair/plugin/migration。

这不是功能问题，而是 UX 和安全边界问题。

### 建议 11：把测试从“功能正确”扩展到“体验契约”

优先级：**P1/P2，建议采纳**

当前测试已经覆盖 runtime、context、campaign、namespace、恶意模拟等。建议新增几类体验契约测试：

- `test_context_budget_policy.py`
- `test_ai_helper_layer.py`
- `test_archivist_suggestions.py`
- 扩展现有 `test_palette_governance.py` 或新增 `test_palette_action_contracts.py`
- `test_discovery_state.py`
- 扩展现有 high-impact warning 覆盖，必要时新增 `test_content_delta_high_impact_warnings.py`
- `test_proposal_queue.py`
- `test_chinese_player_phrases.py`

重点不是 snapshot 文本完全一致，而是断言：

- 必要 section 不被裁掉。
- candidate 不被当事实。
- hidden 不进 player view。
- high-impact 内容必须 warning/review。
- palette_id 来源进入 payload。
- 中文模糊输入有 repair option。

## 5. 推荐落地路线

### P0：巩固已落地的内容治理，并调准默认体验

目标：让已经实现的 palette/content governance 在中文示例里稳定可玩。

当前状态：**基础版已完成，继续打磨示例体验。**

已完成：

1. 保持 `small_cn_campaign` 的 palette manifest、random table payload、world_settings/rules 一致。
2. 动态 context budget 已落地；探索/采集/旅行/制作未显式传 budget 时会提升到 discovery 档位。
3. `tests/test_palette_governance.py` 已覆盖中文示例核心 palette/content governance。
4. 当前 AI 接口清单已更新为：`semantic_ai`、`reflection draft`、外部 Narrator、`memory suggest` Archivist。
5. `small_cn_campaign` 已继续补充 craft 随机表、travel species 线索、locked material palette 和中文自然输入体验测试。

继续任务：

1. 扩充随机表和 palette 覆盖面，而不是重做基础 schema。
2. 更新 `AI_CLIENT_PROMPT.md` 和示例 `prompts/gm.md`，强调事实阶梯、候选边界、`review_required`、proposal queue。
3. 用中文异常玩家输入继续做 UX simulation，验证 repair option 和 blocked path。
4. 继续补充 `travel/craft` 在 small-cn smoke 中的自然语言样例。

完成标准：

- 中文示例能跑出候选素材。
- 探索和采集不会直接确认 hidden/重大事实。
- travel/craft palette 只产生线索或计划，不直接写地点、路线、库存或产物事实。
- 普通玩家不会看到内部 schema 错误。
- 文档明确哪些 AI 接口是已实现、哪些只是设计。
- `tests/test_palette_governance.py` 持续通过。

### P1：把手工纪律变成产品规则

目标：减少靠提示词自觉。

当前状态：**基础版已完成。**

已完成：

1. 新增 `rpg_engine/ai/`，把 `semantic_ai` 和 `reflection AI` 的 hermes 调用收口到统一 provider。
2. 给 AI task 增加统一 schema、timeout、fail-closed、advisory policy。
3. 动态 context budget policy。
4. 完成 `travel/craft` 的 `palette_id` 消费。
5. 高影响 warning 接入 `--strict-review` 和 proposal queue。

继续任务：

1. high-impact warning 输出更细结构化 JSON。
2. 中文 alias gap 报告和 repair option 继续优化。
3. runtime 从 random table payload 自动进入 preview 时增加更严格的 kind/status 防错。
4. 给 AI Helper Layer 增加 fake provider / bad JSON 的专门单测矩阵。

完成标准：

- 关闭 AI 时核心路径完全可运行。
- `semantic_ai` 和 `reflection draft --ai hermes` 行为保持兼容，但模型调用只走统一 provider。
- 坏 palette 会被 validate 捕获。
- `clue_only` 不可能直接变库存或 known entity。
- `context.budget.policy_reason` 可解释为什么加预算或裁剪。
- 高影响内容没有 review 标记时，在 strict 模式下不能 apply。

### P2：引入后台 Archivist 和 discovery_state

目标：让长期游玩不靠完整历史，也不靠人工记忆。

当前状态：**基础版已落地，commit 后可选自动化和 context 召回已补齐，apply/维护待补强。**

已完成：

1. 在 AI Helper Layer 上新增 `ArchivistTask`。
2. 新增 Archivist 建议 schema。
3. 新增 `memory suggest`，可生成 memory/alias/lead/contradiction advisory suggestions。
4. 新增 `discovery_states` 表。
5. commit/save 时已从 palette/unknown-lead 事件派生 discovery_state。
6. `play commit --archivist-suggest` 可选生成并存储 Archivist suggestions，且可入 `proposal_queue`。
7. context builder 已读取 `discovery_states`，把线索阶段变成可召回上下文。

继续任务：

1. memory 从 rebuild-only 走向 incremental suggestions / apply-suggestions。
2. alias_suggestion proposal 的审核和应用通道。
3. discovery_state 支持多源确认、归档和维护报告。
4. commit 后 Archivist 的默认启用策略、节流策略和失败报告。

完成标准：

- 多回合线索能从 rumor/clue 走到 sampled/confirmed。
- 玩家重复提到模糊对象时，系统能召回相关线索。
- Archivist 不能绕过 proposal/validate 直接写权威事实。

### P3：持久 proposal 队列和内容沉淀工作流

目标：支持长线开放世界维护。

当前状态：**基础队列和核心维护命令已落地，更多 proposal kind 的 apply 待产品化。**

已完成：

1. proposal queue。
2. 高影响 `content_delta` 可通过 strict review 自动入队。
3. `proposal create/list/review/apply` 已支持 content_delta review/apply。
4. `proposal report`、`review --reason`、`batch-review`、`rollback-plan` 已支持。

继续任务：

1. 把 `content from-palette` 提供直接 `--enqueue` 工作流，而不是先生成本地 delta 文件再入队。
2. maintenance UI 和更细粒度结构化报告。
3. 长期内容沉淀：临时 NPC、材料、地点、规则进入 campaign/save package。
4. 支持 `turn_delta`、`memory_update`、`alias_suggestion` 的 apply 边界和回滚策略。

完成标准：

- AI 草案可排队、可审、可拒、可追踪。
- 高影响内容不会静默进入世界。
- 作者能把运行中反复出现的内容沉淀为正式内容。

## 6. 不建议采纳的方向

以下方向短期不建议做：

- 不要把上下文无限加长作为主要方案。
- 不要让后台 AI 拥有直接 DB 写入权。
- 不要让 MCP 暴露 migration、plugin、repair、任意文件读写。
- 不要把普通玩家输入直接转 content delta。
- 不要让剧本作者在 V1 默认写 Python resolver。
- 不要把所有 world lore 常驻上下文。
- 不要用 prompt 替代 schema、resolver 和 validate。

## 7. 最小推荐决策

原先建议只采纳四件事时按以下顺序。本轮已经完成四件事的基础版：

1. **已完成基础版：统一 AI Helper Layer，先把 `semantic_ai`、`reflection AI` 和 Archivist 的 provider/schema/policy 收口。**
2. **已完成基础版：动态上下文预算 + 探索/采集/旅行/制作保留 palette candidates。**
3. **已完成基础版：后台 Archivist 只做结构化提案，不直接写事实。**
4. **已完成基础版：补齐 `travel/craft` palette 合约、discovery_state 和 high-impact review 队列，防止新内容失控。**

本轮追加完成：

1. **已完成基础版：Archivist suggestions 可选地在 commit 后生成，并进入 memory/proposal 待审工作流。**
2. **已完成基础版：context builder 读取 `discovery_states`，把线索阶段变成可召回上下文。**
3. **已完成基础版：proposal queue 补维护报告、拒绝原因、批量 review 和回滚辅助。**
4. **已完成基础版：继续打磨 `small_cn_campaign` 的随机表、palette 覆盖和中文自然输入体验。**

下一步最小决策应转为：

1. 设计 `memory_update` 和 `alias_suggestion` proposal 的 apply/revert 规则，避免只入队不能落地。
2. 给 discovery_state 增加确认/归档/维护报告命令，支持多证据来源和过期线索清理。
3. 给 `content from-palette` 增加直接 `--enqueue`，减少“先写本地 delta 再 proposal create”的维护摩擦。
4. 扩展 small-cn smoke/sample_texts，把 travel/craft/social 的中文自然输入短语纳入包级体验契约。

## 8. 与当前治理文档的关系

`AIGM_CONTENT_GENERATION_GOVERNANCE.md` 的事实阶梯、palette、random table、content delta、visibility 设计方向正确，应继续作为内容治理主文档。

本报告补充四点：

1. 从 AI GM 资料看，系统应明确采用 Narrator + Kernel + Archivist 的混合架构。
2. 当前已有的 `semantic_ai`、`reflection AI` 和 Archivist 建议已经收敛到统一 AI Helper Layer；后续 AI 辅助任务必须继续沿用该边界。
3. 上下文长度应走动态预算和高信号 section，而不是依赖静态 `context_budget`；当前已实现 policy 基础版，并已把 discovery_state 纳入召回。
4. 当前代码已经完成 `content.palettes`、示例 palette、`gather/explore/social/travel/craft palette_id`、`content from-palette`、high-impact warning、strict review、discovery_state、proposal queue、Archivist commit 后可选建议、discovery context 召回和 proposal 维护命令基础版，所以后续计划应从“补闭环基础”修正为“增强 memory/alias apply、discovery 维护、proposal UI/批处理和中文沙盒内容密度”。

## 9. 来源

- Jaewoo Song, Andrew Zhu, Chris Callison-Burch, `You Have Thirteen Hours in Which to Solve the Labyrinth: Enhancing AI Game Masters with Function Calling`, arXiv 2024. <https://arxiv.org/abs/2409.06949>
- Nicolai Hejlesen Jorgensen 等, `Static Vs. Agentic Game Master AI for Facilitating Solo Role-Playing Experiences`, arXiv 2025. <https://arxiv.org/abs/2502.19519>
- AI Dungeon Guidebook, `What is the Memory System?` <https://help.aidungeon.com/faq/the-memory-system>
- AI Dungeon Guidebook, `What goes into the Context sent to the AI?` <https://help.aidungeon.com/faq/what-goes-into-the-context-sent-to-the-ai>
- Andrew Zhu, Lara J. Martin, Andrew Head, Chris Callison-Burch, `CALYPSO: LLMs as Dungeon Masters' Assistants`, arXiv 2023. <https://arxiv.org/abs/2308.07540>
- Chris Callison-Burch 等, `Dungeons and Dragons as a Dialog Challenge for Artificial Intelligence`, arXiv 2022. <https://arxiv.org/abs/2210.07109>
