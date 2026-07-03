# AIGM Kernel V1 需求校准稿

文档状态：**BASELINE：V1 产品边界与已落地需求基线**  
目的：固定“要做什么、不做什么、做到什么程度”，避免继续膨胀成完整后端或平台。  
权威关系：本文件是 V1 产品边界锚点；已归档的旧 redesign/V2 文档只作为历史与实现参考，不再作为扩张主线。

## 0. 当前固定结论

- 方向固定为**通用本地 AIGM 游戏内核**，不是 Web 后端、平台、市场或某个客户端的私有插件。
- 核心用法固定为“剧本包 + 存档包 + Kernel API + CLI/MCP 适配 + AI 客户端 prompt”。
- 剧本包和存档包必须分离；新游戏可从剧本包自动生成初始存档。
- AI 客户端负责叙事，内核负责事实、规则、随机、校验、保存和上下文。
- 核心运行默认不依赖 LLM；AI 辅助只做 advisory，不做事实源和写库入口。
- V1 必须能承载旧纯文档系统整理后的继续游玩，但不承诺无监督一键完美迁移。
- V1 游戏性采用“精确事实 + 结构化模糊状态”，不做完整电子游戏式全局数值系统。
- MCP 是必须交付的薄适配层，不是新后端，也不要求修改 Hermes 或其他 AI 客户端源码。

## 1. 产品定位

要做的是一个**通用本地 AIGM 游戏内核**，不是独立 Web 后端，也不是只服务某个客户端的私有插件。

一句话：

```text
下载内核 + 下载剧本包 + 新建/导入存档 + 接入 AI 客户端 = 可稳定运行的文字 RPG。
```

核心分工：

- **AI 客户端**：负责对话和自然语言叙事。
- **AIGM Kernel**：负责事实、上下文、规则、随机、校验、保存和一致性。
- **剧本包**：负责世界、角色、规则摘要、模板和玩法声明。
- **存档包**：负责某一次游玩的状态和历史。

核心运行不强制调用模型。内核可以提供可选 AI 辅助，但 AI 辅助不能成为事实源、不能绕过校验、不能直接写库。AI 客户端不能绕过内核结算和保存。

## 1.1 长期最终目标

本节是 AIGM Kernel 的长期北极星，不等同于 V1 必须一次性交付的全部范围。V1 仍以“稳定本地内核 + 剧本包 + 存档包 + CLI/MCP + 官方示例”为主。

最终目标：

```text
做一个通用、本地优先、可发布、可扩展的 AI GM 游戏内核。
作者用剧本包定义世界与玩法，玩家用存档包持续游玩，
AI 客户端负责叙事，内核负责事实、规则、随机、校验、保存和一致性。
```

长期目标包括：

- **设定支持性强**：世界设定、种族、文化、势力、能力、遗迹、宗教、任务和场景均能被 AI 正确召回，并能区分叙事说明与可执行规则。
- **架构清晰**：剧本定义、运行状态、AI 编排、规则结算、持久化和派生投影各自有明确边界。
- **性能优秀**：当前几百实体保持毫秒级响应，同时为一万实体、一万回合以上的存档预留增量处理能力；大规模目标必须通过单独 benchmark 验证，不能只做口头承诺。
- **运行稳定**：任何失败都不能产生半写入存档；数据库、事件、快照、卡片和索引之间可以检测并修复不一致。
- **扩展性强**：新增内容类型或行动类型主要通过注册模块完成，不需要在多个中央文件中增加分支。
- **可维护性好**：数据契约、版本、迁移、测试、文档和兼容策略可检查，不依赖维护者记忆。
- **模块化设计**：引擎核心不包含具体游戏角色、物品、规则和世界观名称。
- **剧本维护方便**：支持剧本校验、构建、差异预览、安装、升级、导出、迁移和冲突处理；其中高级升级链路可作为 legacy/admin 或后续版本逐步稳定。
- **易用性足够高**：普通用户应能通过少量命令完成安装内核、复制或下载剧本、校验剧本、新建存档、接入 AI 客户端并开始游玩。
- **AI 安全边界清晰**：AI 客户端不能绕过内核直接推进剧情、修改事实、发明随机结果或泄露隐藏信息；所有事实变化必须经 preview、validate、commit。

这些目标的优先级顺序是：先稳定运行与边界清晰，再增强扩展性和剧本维护链路，最后做大规模性能与高级生态能力。

## 2. V1 交付范围

V1 必须交付：

- AIGM Kernel 核心库。
- 剧本包规范与校验器。
- 存档包规范与导入、导出、查看、校验。
- CLI 参考实现。
- 可用的 MCP Adapter。
- 通用 AI 客户端 prompt。
- 一个小型官方示例剧本。
- 旧纯文档系统存档继续游玩的迁移/承载能力。

V1 明确不交付：

- Web 后端、HTTP API、多人在线、账号、云同步、市场。
- 强制依赖 LLM 的核心运行路径。
- 独立聊天 UI。
- 内置 AI 剧本生成器。
- 动态插件系统和插件市场。
- 10k/100k 规模目标。

V1 支持规模目标：

```text
100-1000 个结构化内容项，数百回合。
```

V1 边界锁定：

- 不新增需要常驻 Web 服务才能使用的主路径。
- 不新增账号、云端、同步、远程托管、多人协作或市场能力。
- 不把 MCP 做成第二套业务层；MCP 只能转调同一套 Kernel API。
- 不把 CLI 做成另一套业务层；CLI 是参考入口和维护入口。
- 不把 optional AI helpers 做成核心依赖、模型网关或 agent 框架。
- 不把剧本作者体验推进到写代码、写插件或理解数据库。
- 不把旧文档迁移承诺成全自动、无监督、零人工审核。
- 不为单一题材预置复杂专用系统；题材差异通过剧本包内容、capability、规则摘要、随机表和结构化状态表达。

## 3. V1 实施原则

V1 是**收敛式改造**，不是推倒重写。

优先复用现有 `rpg-engine` 已经实现并验证过的能力：

```text
SQLite
context build
query
preview
save-turn
check
projection
backup
content registry
action registry
```

实现顺序应围绕“把已有能力收敛成稳定 Kernel API、CLI、MCP、剧本/存档规范”展开。只有当现有实现明显违背 V1 边界时，才收缩、重命名或降级。

专业实现问题按现有实现优先；不为未来高级能力预建复杂系统。任何新增模块都必须能对应到 V1 交付范围、核心 API、剧本包规范、存档包规范、CLI 或 MCP Adapter。

V1 以现有 `rpg-engine` 代码为迁移基线，不改名重开项目。先收敛现有实现，未来再考虑包名、模块名或公开 API 命名迁移。

V1 官方示例剧本应新建一个小型但玩法完整的模组；现有 `isekai-farm-v2` 作为兼容/压力案例，不作为官方最小示例。

剧本包规范先围绕现有 content registry 已支持类型落地，再补足旧纯文档系统继续游玩所需的通用玩法内容类型，例如 `clue`、`relationship`、`inventory/resource`、`project/task`。不为了特定题材预建完整专用数值系统，也不在 V1 引入作者自定义代码执行。

存档包导入导出优先复用现有 `save export/import` 能力；V1 主要补元信息、兼容性校验和 `.aigmsave` 包装。

MCP V1 可以短期复用现有 CLI/内部函数，但目标是收敛到 `GMRuntime`。MCP 不得长期散落调用各模块形成第二套业务编排。

现有 package upgrade/reconcile/install 能力保留为 legacy/admin，不进入 README 快速路径，也不面向普通用户文档化。

## 4. 可选 AI 辅助原则

内核可以提供可选 AI-assisted helpers，用于提高体验和准确性，但这是一组辅助能力，不是 V1 必须完成的独立 AI 平台。例如：

- 语义别名识别。
- 意图判断辅助。
- 上下文召回建议。
- 剧本校验建议。
- 错误修复建议。

但 AI 辅助必须满足：

- 默认关闭；用户显式配置模型后才开启。
- 默认核心路径无 AI 也能运行。
- 可关闭。
- 超时或失败不阻断 validate、init、query、preview、commit。
- 输出必须标记为 advisory。
- 不直接写库。
- 不成为事实源。
- 不覆盖 SQLite、规则、校验器或用户确认。
- 不引入必须配置的模型供应商、账号系统或长期后台任务。

AI 辅助可以用于 live play 的 `start_turn` 意图判断、语义别名识别和上下文召回建议，但本地规则/数据库结果仍是主结果。

## 5. 产品对象

V1 有三个一等对象：

```text
Kernel Package    # 引擎
Campaign Package  # 剧本/模组/世界书
Save Package      # 某次游玩进度或预设开局
```

辅助对象：

- **CLI Adapter**：调试、校验、初始化、维护和参考实现。
- **MCP Adapter**：AI 客户端的主流结构化接入方式。
- **Client Prompt / Skill**：说明 GM 行为、叙事风格和工具调用原则。

CLI 与 MCP 都必须调用同一套 Kernel API，不允许各自实现业务逻辑。

## 6. 内核运行契约

内核应提供正常可用的通用跑团式回合循环：

```text
玩家输入 -> 上下文 -> 查询/行动判断 -> 可选预览 -> AI 叙事 -> 校验 -> 保存
```

V1 核心 API：

```text
player_turn      # 默认玩家自然语言入口：内部判断 query/action/clarify/block
player_confirm   # 默认玩家确认并保存 pending action
start_turn      # 玩家输入 -> 上下文、意图、是否可推进
query           # 查询场景、实体、规则、世界设定、线索
preview_from_text # 低层自然语言路由 + 安全预演，不保存
preview_action  # 行动预览，不保存
validate_delta  # 保存前校验
commit_turn     # 低层 TurnProposal 正式写入入口
health          # 检查一致性和必要修复建议
```

V1 可以保留内部 `draft_delta` 能力作为辅助，但不作为 MCP 必暴露工具。

`draft_delta` 保留为 CLI/admin 兼容和辅助能力，不作为默认保存路径。

行动类保存必须经过校验。缺关键上下文、引用不存在、剧本不支持该玩法或 expected turn 不匹配时，内核必须拒绝保存。

随机表和骰子由内核执行，结果写入可审计事件；AI 只能叙事化结果。

V1 必须能承载旧纯文档系统迁移后的继续游玩。迁移可以是人工/AI 辅助整理后的剧本包 + 存档包，不承诺无监督一键完美解析旧文档。

## 7. 剧情背景支持

内核应对各种剧情背景有强支持，但不能内置具体世界观。

必须支持：

- 不同题材：奇幻、科幻、现代、悬疑、恋爱、经营、生存、政治、恐怖等。
- 不同设定层级：世界观、地区、势力、文化、种族、科技/魔法体系、宗教、历史、传闻和秘密。
- 不同实体类型：人物、地点、物品、组织、线索、关系、规则、进度钟、世界设定。
- 不同信息可见性：玩家已知、GM 已知、隐藏、未发现、传闻、候选素材。
- 不同召回方式：按玩家输入、场景、地点、实体关系、标签、规则和剧情状态检索相关信息。
- 不同回复风格：由剧本 prompt 和模板控制，不写死在内核里。

核心强在“表达、校验、召回和保存各种背景”，不是强在“内置某一种背景”。

## 8. 剧本包规范

正式名称：

- 中文：剧本包
- 英文：`Campaign Package`

V1 剧本作者不写代码，只使用 Markdown/YAML/JSON。Python resolver、插件扩展、脚本化规则和高级代码扩展放到 V2 或 experimental。

V1 剧本包基础结构：

```text
campaign.yaml
content/world.md
content/entities.yaml
content/locations.yaml
content/characters.yaml
content/factions.yaml
content/items.yaml
content/clues.yaml
content/relationships.yaml
content/rules.md
content/clocks.yaml
content/random_tables.yaml
prompts/gm.md
templates/action.md
templates/query.md
tests/smoke.yaml
```

最低要求：

- 有唯一 `id`、名称、版本和所需内核版本。
- 有初始世界状态、玩家角色、起始场景。
- 有 GM prompt 和回复模板。
- 有 smoke tests，能验证剧本可以初始化并跑通基本查询/行动。
- 内容易读、易搜索、易 diff，适合 GitHub review 和协作修改。

`clue`、`relationship`、`inventory/resource`、`project/task` 是 V1 一等或准一等内容；实现可以复用通用 entity/details，但剧本规范和校验器必须明确支持它们。

## 9. 作者体验

普通作者体验应接近“写世界书/跑团模组”：

- 作者写世界观、角色、地点、线索、势力、规则摘要、随机表、进度钟和 GM 风格。
- 作者主要编辑 Markdown/YAML/JSON。
- 作者不需要理解 SQLite、MCP、delta、projection、migration 或 Python 插件。
- 作者可以使用任意外部 AI 按剧本规范生成初稿。
- 作者负责创意、审稿、调整和试玩。
- 本项目负责规范、示例、校验、初始化和运行。

当前阶段不做内置剧本生成器、AI 编剧 UI、一键生成完整世界或自动修复全部剧本错误。

后续如果需要剧本生成器，应作为独立工具或扩展能力，不进入内核主线。

## 10. 游戏性、精确性与模糊性

不同剧本包不应被迫支持同一套玩法。游戏性由剧本包通过 `capabilities` 声明。

AI GM 游戏不应设计成纯数值电子游戏，也不应退回纯散文世界书。V1 的游戏性基线是**结构化模糊**：

```text
精确事实 + 结构化模糊状态 + 进度轨道 + 风险后果 + 动态上下文
```

精确性负责一致性、可保存和可校验：

- 实体、地点、物品、线索、任务、势力等对象 ID。
- 当前场景、所在位置、已知/隐藏/未发现信息。
- 物品归属、关系对象、线索发现状态。
- turn、event、delta、command_id 和 expected_turn_id。
- 随机表/骰子结果、进度钟数值、审计记录。

模糊性负责叙事弹性和 AI GM 的自然表达，但必须是结构化字段，不允许只存在于 AI 回复文本：

- 资源数量可用 `充足 / 紧张 / 少量 / 耗尽 / 未盘点`。
- 伤势/压力可用 `无碍 / 轻微 / 明显 / 严重 / 危急`。
- 关系可用 `信任 / 友善 / 中立 / 怀疑 / 敌意 / 依赖`。
- 风险可用 `低 / 中 / 高 / 灾难性`。
- 时间可用 `片刻 / 一段时间 / 半天 / 一天 / 多日`。
- 后果可记录为状态、资源、关系、线索、时钟或任务阶段变化。

V1 的默认结算模型：

```text
玩家意图 -> capability -> 风险/难度/效果 -> 可选随机/规则 -> 后果 -> 结构化 delta
```

AI 可以把结果写成故事，但不能直接改写事实。进入存档的内容必须能落成受校验的结构化 delta。无法确认的内容应返回歧义或要求确认，不能让 AI 硬编后保存。

V1 内置能力：

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

V1 游戏性目标是支持旧纯文档系统和常见跑团模组继续游玩，而不是只做查询和移动。内核应提供通用玩法积木：

- 角色 / NPC。
- 地点 / 区域。
- 物品 / 库存 / 资源状态。
- 状态 / 伤势 / 体力 / 心理压力。
- 关系 / 信任 / 敌意。
- 线索 / 秘密 / 已发现事实。
- 势力 / 组织状态。
- 任务 / 项目 / 阶段推进。
- 进度钟。
- 随机表 / 事件表。
- 探索、旅行、社交、交易、采集/搜索、休息/时间推进。
- 风险、代价和后果记录。
- 可见性和隐藏信息。

V1 不做完整电子游戏式数值系统：不实现完整 DnD 战斗、复杂制作树、经营模拟、经济系统、职业等级、法术编程或国家模拟。对应玩法如果出现，应使用跑团式轻量结算：风险/难度 -> 随机/规则 -> 后果 -> 状态、资源、关系、线索、任务阶段或时钟变化。

剧本可以声明更精确的数字字段，例如金币、弹药、天数、HP 或阵营声望；但这属于剧本数据和轻量规则，不是 V1 内核默认强加给所有剧本的全局数值系统，也不是脚本化规则引擎。

如果剧本没有声明某个 capability，内核必须明确返回“不支持该玩法”，不能让 AI 硬编。

每个声明的 capability 必须有 smoke test 或玩法测试。

## 11. 存档包规范

正式名称：

- 中文：存档包
- 英文：`Save Package`

存档必须和剧本包分离。第一次游玩不要求用户准备存档包；新游戏应能从剧本包自动生成初始存档。

运行形态是目录：

```text
saves/my-run/
  campaign.yaml
  save.yaml
  data/
    game.sqlite
    events.jsonl
  snapshots/
    current.md
    current.json
  cards/
  memory/
```

分享形态是单文件归档：

```text
my-run.aigmsave
```

要求：

- 存档记录来源剧本 `campaign_id`、剧本版本和所需内核版本。
- 导入别人存档必须拥有兼容剧本包；存档包不内嵌完整剧本。
- `.aigmsave` 默认是完整存档，包含隐藏 GM 信息；玩家视角导出留到后续。
- SQLite 是权威事实源。
- 行动保存必须有结构化 delta。
- 保存必须支持 `expected_turn_id` 防旧状态写入。
- 保存必须支持 `command_id` 幂等。
- 写入前自动备份。
- 写入后自动检查一致性。
- 查询不推进时间、不保存。

普通用户不直接编辑 SQLite。正式修改路径是 `save patch` 或结构化 delta。

V1 `save patch` 只允许安全维护：别名、摘要、可见性、实体小字段、关系修正、错字和轻维护；不允许绕过行动结算推进剧情。

## 12. 校验器

校验器是内核项目自带能力，不是独立产品。CLI、MCP、运行时初始化和导入流程都应复用同一套校验逻辑。

`campaign validate` 必须检查：

- 文件结构和 schema。
- ID 唯一性。
- 引用存在。
- 入口场景和玩家角色存在。
- 模板存在。
- capability 声明合法。
- 可见性字段合法。
- 随机表权重合法。
- clock 合法。

`campaign test` 必须初始化临时存档并跑 smoke tests。

`save validate` 必须检查：

- 存档结构。
- 剧本兼容性。
- SQLite schema。
- 当前 turn。
- events。
- snapshots/cards/search 等派生投影一致性。

MCP 的 `health` 必须保持只读，不执行 repair。V1 必须提供的是 `validate`、`inspect` 和受控 `patch`；如果未来加入自动 repair，只能通过显式 CLI/admin 路径提供，不能进入 MCP 默认工具。

校验错误必须对人类和 AI 友好，包含：

```text
code
file
path
message
suggestion
```

## 13. CLI 要求

CLI 是所有能力的参考实现。V1 必须提供：

```text
aigm campaign validate
aigm campaign test
aigm campaign copy-example
aigm save init
aigm save import
aigm save export
aigm save inspect
aigm save validate
aigm save patch
aigm play start-turn
aigm play query
aigm play preview
aigm play commit --proposal-json ./turn_proposal.json
aigm mcp serve
aigm mcp print-config
```

理想使用路径：

```bash
pipx install aigm-kernel
aigm campaign copy-example ./campaigns/example
aigm campaign validate ./campaigns/example
aigm save init ./campaigns/example ./saves/my-run
aigm save inspect ./saves/my-run
aigm mcp print-config . --default-save saves/my-run
```

常用操作应有一条清晰命令路径。错误信息必须告诉用户下一步该做什么。

## 14. MCP Adapter 要求

MCP Adapter 是 V1 必须交付，但只能是薄适配层。

V1 MCP 暴露玩家入口/存档选择工具和运行时工具：

```text
workspace_inspect
campaign_list
save_list
save_current
save_create
save_switch
start_or_continue
intent_manifest
campaign_validate
save_inspect
player_turn
player_confirm
health
```

V1 developer/trusted low-level MCP 额外暴露：

```text
player_query
player_act
start_turn
query
preview_from_text
preview_action
validate_delta
commit_turn(delta, turn_proposal)
```

V1 MCP 不暴露：

- migration apply。
- package upgrade/reconcile。
- plugin loading。
- 任意文件读写。
- 高风险 admin 操作。
- 模型调用代理。
- 长期任务调度。

MCP 不接受任意绝对路径；只能访问配置好的 campaign/save root，并通过 ID 或相对名称选择对象。

项目不修改 Hermes、Claude、Cursor 或其他 AI 客户端源码，只通过 MCP/CLI/配置接入。

## 15. AI 客户端 Prompt

V1 必须提供通用 AI 客户端 prompt，而不是只提供 Hermes 专用 skill。

AI 客户端不凭空写故事。它根据以下内容叙事：

```text
剧本 GM prompt
+ 当前上下文
+ 查询/行动预览结果
+ 规则和限制
+ 回复模板
+ 玩家原话
```

Prompt 必须要求：

- 事实以内核返回为准。
- 查询不推进时间、不保存。
- 行动必须通过 preview/validate/commit。
- 不支持的 capability 不得硬编。
- 不得声称已保存，除非 commit 成功。
- 叙事文本不能替代结构化 delta。

## 16. 明确降级项

以下内容降级为 legacy/admin/experimental，不进入 V1 主线：

- 现有复杂 package upgrade/reconcile/install。
- 动态插件加载。
- 插件市场。
- HTTP 后端。
- 多用户服务。
- 大规模平台生态。
- 10k/100k 规模目标。
- 玩家视角存档导出。
- 完整电子游戏式战斗/制作/经营/恋爱/政治数值系统。
- 作者自定义代码执行、脚本化规则引擎和插件 SDK。
- 模型网关、agent 平台和长期任务系统。
- 全自动旧文档迁移器。

源码边界：降级项不得重新挤入 V1 主路径命名空间。Campaign Package 实现可以保留为通用 `packages` 子命名空间；插件 manifest 检查属于 `admin`；旧文档/旧游戏导入属于 `compat`；根层旧路径只能作为兼容 wrapper。

## 17. 成功标准

V1 可以算成功，必须满足：

- 内核和剧本没有互相写死。
- 新剧本可以通过同一套接口加载。
- 新游戏可以只从剧本包自动生成初始存档。
- 兼容存档包可以独立导入和继续游玩。
- 存档包可以导出分享、查看状态、校验健康并通过受控 patch 修改。
- 查询回合不会误保存。
- 行动回合可以 preview、validate、commit。
- 保存失败不会产生半写入状态。
- 文档能让别人从零安装并跑通示例。
- AI 客户端接入只需要配置 adapter，不需要改客户端源码。
- 剧本包普通内容修改不需要改内核代码。
- 剧本包声明的能力都有对应 smoke test 或玩法测试。
- 普通作者可以用外部 AI 按剧本规范生成初稿，并用校验器发现结构问题。
- 旧纯文档系统可以通过人工/AI 辅助整理迁移为剧本包 + 存档包，并继续游玩。
- V1 能支持常见跑团式玩法积木，而不是只支持查询和移动。
- 精确事实和结构化模糊状态都能被保存、查询、校验和用于上下文构建。

## 18. 后续文档拆分

后续规范拆分状态：

```text
specs/campaign-package.md      # 剧本包规范，已落地
specs/save-package.md          # 存档包规范，已落地
specs/mcp-adapter.md           # MCP 工具契约，已落地
specs/cli.md                   # CLI 命令契约，已落地
prompts/ai-client-prompt.md    # 通用 AI 客户端 prompt，已落地
```

本文件继续作为产品边界锚点。上述规范不得扩大本文件定义的 V1 范围。

具体 API 返回格式、schema 字段、adapter 参数和 CLI 参数放到后续规范文档中定义，不在本需求校准稿中展开。
