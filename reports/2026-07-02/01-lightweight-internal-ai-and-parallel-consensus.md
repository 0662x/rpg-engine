# 当前实施：rpg-engine 轻量内部 AI 与 preflight cache；未来扩展：平台并发预热

Date: 2026-07-02

2026-07-03 文档整理：本文保留阶段一、阶段二和阶段三 3A 的设计、实现、专家复核和测试记录。阶段三 3B 的工程级实施计划与 rpg-engine 侧实现记录已拆到 [`../2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md`](../2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md)。后续 3B 开工、验收和 code review 以 2026-07-03 计划为准。

术语说明：本文中的 `IntentJoiner` 指 rpg-engine 内核已实现的 preflight lookup / join 行为，不是独立平台服务，也不表示 Hermes/QQ 平台监听已接入。

## 当前执行边界

本文当前执行范围是：阶段一收尾 + 阶段二 rpg-engine preflight cache + 阶段三 3A 内核 IntentJoiner。已在 `rpg-engine` 内实现轻量 `InternalAIService`、直连 flash provider、schema validation、timeout/fallback、telemetry，并保留旧 `hermes -z` 作为显式兼容 fallback；同时已实现内核自己的 preflight cache，让内部 AI review 可以提前计算、凭号或消息身份消费、进入正式仲裁链路。

第三阶段平台薄 adapter / Platform Prewarm Layer 仍不进入本轮开发或验收。本轮不修改 Hermes core / hermes-agent、Hermes gateway、QQ adapter、Hermes 用户插件或 QQ 插件。3B 工程计划见 2026-07-03 计划文档。

2026-07-02 追加专家复核后的结论是：阶段一/二的 rpg-engine 内核闭环可以接受；阶段三 3A 已先在 rpg-engine 内完成 `message-only preflight` 身份模型、`IntentJoiner`、pending 短等待、无 `preflight_id` 的 message lookup、`late_ready_unused` 和 `GameSessionGate` 纯函数契约。下一步仍不直接接 QQ/Hermes 平台预热，平台侧只作为 3B 薄 adapter 另行实施。

## 一句话结论

当前已经把内部 AI 做成 `rpg-engine` 内的轻量小裁判，并完成 rpg-engine 侧 preflight cache；长期方案仍按三阶段推进：

```text
第一阶段：把内部 AI 变成轻量常驻的小裁判。（已实现）
第二阶段：rpg-engine 支持提前算、凭号取、复用 internal_candidate。（已实现）
第三阶段：rpg-engine 内核 3A 已完成；未来如需平台加速，再让 QQ/Discord/Web 等平台输入通过薄 adapter 触发内部 AI 预判。（3B，未接平台。）
```

通俗地说：

```text
第一阶段：把厨师换快。
第二阶段：厨房支持提前备餐和凭号取餐。
第三阶段：任何服务员听到客人点菜的瞬间，都按同一张小纸条通知厨房先做。
```

最终写入前必须同时满足：外部 AI 与内部 AI 对玩家意图一致，并且内核 binder、resolver、preview、validation 都通过。V1 最多先生成 preview / pending proposal；真正写入仍需要 `player_confirm` 或等价确认边界。否则澄清或阻断。

## 职责分工

| 组件 | 长期职责 | 不能做什么 |
| --- | --- | --- |
| 外部 AI | 理解玩家自然语言，生成低信任 `external_candidate`。 | 不能直接提交，不能伪装内部 AI，不能绕过内核校验。 |
| 内部 AI | 在 rpg-engine 控制的 player-visible context 中独立复核意图、槽位和风险。 | 不能直接写存档，不能自己填安全确认槽位，不能成为事实源。 |
| 规则/确定性逻辑 | 做结构化绑定、风险分级、安全硬门、fallback gate、trace/audit。 | 不再承担长期自然语言主裁判职责。 |
| 内核 | 负责 binder、arbiter、resolver、validation、proposal 和 commit guard。 | 不接受未经仲裁和校验的 AI 输出。 |

## 硬边界

- 不修改 Hermes core / hermes-agent 源码。Hermes 上游持续更新，直接改 core 会产生长期冲突。
- 当前实施范围不修改 QQ adapter、Hermes gateway、Hermes core 或 QQ 侧插件代码；先只改 rpg-engine 内部 AI 与内核接口。
- 当前阶段只允许修改 rpg-engine 内部代码、配置、测试和文档；不启用 Hermes/QQ 用户插件或平台侧 prewarm。
- rpg-engine 内部 MCP 扩展、preflight cache 和 preflight 身份字段已进入本轮实施；workspace `GameSessionBinding`、Hermes 用户插件和 QQ/platform prewarm 仍属于未来第三阶段，必须再次确认后才实施。
- 内部 AI 只做判断、复核、总结、建议，不能直接改存档。
- 外部 AI 永远是低信任调用者；内部 AI 是内核控制的低权限增强模块，也不是最终事实源。
- AI 输出必须经过 schema validation、binder、arbiter、preview、validation、commit。
- 旧 `hermes -z` helper 只保留为显式 fallback；`direct` 默认失败时不得偷偷回退到 Hermes。

## 当前已拍板决策

- 这是单人游戏优先设计。V1 不做群共享队伍、多玩家协作或多人存档同步。
- 当前只做 rpg-engine 内部 AI。平台预热、插件、ACK、typing、群聊策略全部后置。
- 内部 AI 由 rpg-engine 直连轻量模型，目标是 `deepseek v4 flash` 或等价 flash 模型；`hermes_z` 只作为显式 backend 或显式 fallback。
- 第三阶段默认设计：游戏模式采用自动激活。首次成功调用 rpg-engine 并进入某个 save 后，当前 platform session binding 自动进入 active_game。
- 第三阶段默认设计：active_game 自动失效，默认 TTL 20 分钟，后续可按 telemetry 调整。
- V1 不允许自动 commit。快通道只是不等待内部 AI，保存仍需走 `player_turn -> player_confirm`；兼容 `player_act` 也必须落到同一个确认边界。
- 第二/第三阶段如启用 preflight，正式链路不允许外部直传 `internal_candidate`。外部只传 `preflight_id/message_id/text_hash/platform/session_key`，内部候选只能从 rpg-engine 自己的 cache 读取。
- `player_confirm` 必须由 host/UI 在玩家明确确认后传入 `player_turn` 返回的 `session_id`；AI 不能把自己连续调用 `player_turn -> player_confirm` 当作人类确认。
- `player_turn_commit` 必须带 `expected_turn_id` 和 `command_id`；这两个字段是普通玩家写入的并发/幂等硬门，不因 preflight 命中而放宽。

## 多角色审核结论

AI 游戏开发组多角色审核后的结论是：三阶段路线能支撑长期目标，但属于“条件可行”，不是现状直接可上。

必须坚持两个判断：

- 第一阶段和第二阶段是进入 QQ 插件预热前的内核硬前置，本轮已经完成；第三阶段仍是未来平台体验层。
- 第三阶段只负责提前启动内部 AI，不负责放权、不负责提交、不负责绕过内核。

审核后新增的硬补强项：

- 第一阶段验收看 `rpg-engine` 内部 AI：`InternalAIService`、direct provider、schema validation、timeout/fallback、risk/fail policy、telemetry 和测试。
- 第二阶段验收看 rpg-engine preflight cache：message id/text hash、platform/session 身份字段、candidate provenance、状态机、DB 锚定和测试。QQ gate、Hermes 用户插件、workspace `GameSessionBinding`、ACK/typing、群聊策略仍不属于当前验收。
- `InternalAIService` 必须是真正的轻量 provider 主路径，而不是继续包装 `hermes -z`。`hermes_z` 只能作为显式兼容 fallback。
- schema validation 必须足够硬。当前 schema 如果使用 `oneOf` 等复杂 JSON Schema 能力，校验器必须支持；否则 schema 要改成校验器实际支持的子集。
- `PreflightCache` 必须持久化，并有明确状态机：`pending -> ready | expired | failed | used | rejected`。
- preflight key 必须包含 `platform/session_key/message_id/source_user_text_hash/save_id/base_turn_id/intent_context_id/model_version/schema_version/task_version/backend/fallback_backend/external_candidate_hash/rule_candidate_hash` 这类身份信息。
- `ready` 命中必须重新校验文本 hash、active save、base turn、context hash、schema version、visibility profile、candidate provenance。任一不一致都不得复用。
- 外部调用者不能直接上传一个 `internal_intent_candidate` 并让内核信任。正式方案应优先让外部只传 `preflight_id/message_id/text_hash/platform/session_key`，内部候选从内核自己的缓存取；若支持直传，必须有内核签名或 trusted profile 限制。
- preflight 只能缓存 advisory intent/review，不能缓存 delta、TurnProposal 或任何可提交结果。正式 delta 必须现场 resolver preview，并继续带 `expected_turn_id/command_id`。
- 内部 AI timeout/error 必须 fail-closed。只读 query 可降级；写入型 action、复杂槽位、hidden info、forced save、prompt injection、maintenance 越权必须 clarification 或 block，不能 `rules_fallback + ready_to_save`。
- `intent_context_id` 已落到 TurnProposal 和 validation 边界。外部 AI、内部 AI、规则预检必须声明基于同一个冻结上下文。
- clarification 状态要统一并持久化。第三阶段跨进程预热时，旧澄清和新消息不能串线。
- preflight 生命周期必须有 durable audit：start、hit、miss、pending wait、expired、used、rejected、timeout、arbiter decision、stale reject，并截断敏感内容。
- 第三阶段若启用平台 prewarm 插件，必须复查授权、忽略 slash command/空文本/非游戏会话/pending approval 或 clarification；插件只投递后台任务并立刻 `allow`。
- 第三阶段若启用可见体验优化，应按平台能力采用 typing、延迟 ACK 或静默后台预热；V1 默认先不发可见 ACK，避免噪音。

## 本轮专家交叉审核确认

四位专家交叉审核后的共识：

- 目标清晰：当前做的是 `rpg-engine` 内部 AI 主路径，不是 QQ/Hermes 平台改造。
- 边界清晰：本轮未改 Hermes core、hermes-agent、Hermes gateway、QQ adapter、Hermes 用户插件或 QQ 插件。
- 阶段一已经形成可运行闭环：外部候选进入后，内部 AI 独立复核，arbiter 决策，binder/resolver/preview/validation 继续作为最终内核门。
- `direct` 是长期主路径；`hermes_z` 只作为显式 backend 或显式 fallback。`direct` 默认失败时不隐式回退 Hermes。
- 风险 fallback 已集中：`yellow_fast` 满足规则时可降级；`yellow_consensus/red` 在内部 AI 不可用时不得直接 ready。
- 战斗等 `red` 行动即使 AI 共识，也不能让 AI 自己填 `ready_state` 这类安全确认槽位；该槽位必须继续要求玩家确认。

## 宽松 V1 风险分级策略

这里的“宽松”只表示减少等待内部 AI 的场景，不表示减少 binder、resolver、preview、validation 或玩家确认，也不表示允许自动写入存档。

风险分级不要靠中文字符匹配。自然语言理解交给外部 AI / 内部 AI，硬规则只判断结构化 action candidate 是否适合快通道。

V1 可以先做得相对宽松：目标不是把所有写入都打成红灯，而是让明显低风险、槽位完整、validation 可通过的行动不用等内部 AI。

规则要分成两层理解：

- `legacy rules`：当前仍存在的旧自然语言/启发式路由。`intent_ai=off` 时它仍是默认主路由；`consensus` 成功时它只是候选和 trace；内部 AI 不可用时，它只能在 `yellow_fast` 且校验完整的场景做兜底。
- `risk/safety rules`：长期应该保留的确定性硬门。它不理解自然语言，只检查结构化 candidate、权限、hidden/maintenance、forced save、prompt injection、slots、binder/resolver/validation 等条件。这个层级应该在所有路径里生效。
- 因此长期目标不是“删掉所有规则”，而是把规则从自然语言主裁判降级为安全护栏、结构化校验和低风险 fallback gate。

当前真实 action resolver 列表是：

```text
combat
craft
explore
gather
random_table
rest
routine
social
travel
```

`query` 不是 action resolver，而是只读 mode/tool。`maintenance` 也不是 action resolver，而是 mode/profile 权限边界。因此风险分级 V1 不能把 `query_inventory/query_status/maintenance` 当作 action 名写进策略。

基础分级：

```text
green:
  明确只读或低影响行动，可跳过内部 AI 等待，直接 preview/validation。

yellow_fast:
  普通低影响写入，外部 AI 高置信、slots 完整、binder 成功时可以先 preview；
  如果 preview/validation 出现歧义，再升级到内部 AI 或 clarification。

yellow_consensus:
  普通但影响较明显的写入，需要外部 AI + 内部 AI 共识。

red:
  高风险、越权、隐藏信息、维护操作、强制保存、战斗/大额交易/稀有资源消耗等；
  必须内部 AI 复核，或直接 clarification/block。
```

V1 action metadata 可以先很薄：

```yaml
query:
  base_risk: green
  write: false
  hidden_access: false
  fast_path: true

routine:
  base_risk: yellow_fast
  write: true
  effects: [time, audit_event]
  fast_path: true
  notes: inventory-audit style routine may produce no state change

rest:
  base_risk: yellow_fast
  write: true
  effects: [time, hp, stamina, clocks]
  fast_path: true

travel:
  base_risk: yellow_fast
  write: true
  effects: [location, time, clocks]
  required_slots: [destination]
  fast_path: true

explore:
  base_risk: yellow_fast
  write: true
  effects: [discovery, time, audit_event]
  required_slots: [target]
  fast_path: true

gather:
  base_risk: yellow_consensus
  write: true
  effects: [inventory, location, resources]

craft:
  base_risk: yellow_consensus
  write: true
  effects: [inventory, materials, project_state]

social:
  base_risk: yellow_consensus
  write: true
  effects: [relationship, npc_state]

random_table:
  base_risk: yellow_consensus
  write: true
  effects: [kernel_random_audit_event]

combat:
  base_risk: red
  write: true
  effects: [combat, hp, inventory, relationship]
  required_slots: [target]
```

V1 提升风险的硬条件：

- `hidden_access=true`：直接 red。
- `maintenance=true`：直接 red。
- 命中 forced save / rollback / prompt injection / 越权维护：直接 red。
- slots 缺失或 binder 绑定失败：至少 yellow_consensus，通常 clarification。
- action 是 composite plan：至少 yellow_consensus。
- external candidate 置信低或与规则候选不一致：至少 yellow_consensus。
- internal AI 发现危险：只能升风险，不能降风险。

V1 快通道条件：

```text
允许跳过内部 AI 等待，仅当：
  - action metadata 允许 fast_path；
  - 不访问 hidden；
  - 非 maintenance；
  - 非 combat / 大额交易 / 稀有资源消耗 / 明显不可逆行动；
  - slots 完整；
  - binder 成功；
  - preview/validation 通过；
  - 没有 external/rules 明显冲突；
  - 没有 pending clarification。
```

V1 的宽松点：

- `routine/rest/travel/explore` 这类普通行动可以先进入 `yellow_fast`，不一律等待内部 AI。
- 只要 preview/validation 能发现问题，就把问题交给 clarification，而不是一开始就拦在内部 AI 前。
- 后续用 telemetry 观察误判、澄清率、回滚率，再把某些 action 从 `yellow_fast` 调到 `yellow_consensus` 或 `red`。

## 第二阶段：Preflight Cache 存储策略

preflight cache 已进入当前 rpg-engine 阶段二实现。本节记录已采用的内核设计：不放 Hermes，也不只放内存。

长期推荐采用两层存储。当前 rpg-engine 已实现 per-save SQLite preflight cache 和内核侧 `GameSessionGate` 纯函数；workspace session binding 的持久化与平台事件接入属于 3B 平台预热薄层：

```text
workspace session binding（3B 待实现）:
  负责记录外部平台 session_key 当前是否处于游戏模式、绑定哪个 active save。

per-save SQLite preflight cache（阶段二已实现）:
  存在当前 save 的 data/game.sqlite 里，负责保存 internal candidate、
  base_turn_id、intent_context_id、文本 hash、状态机和审计。
```

原因：

- preflight 结果强依赖某个 save 的当前 turn、player-visible context 和 schema version，放在 save SQLite 里最不容易串档。
- save SQLite 已经承载 turns、events、meta、write guard、projection state，适合做事务、migration、audit 和过期清理。
- workspace/session binding 是第三阶段路由信息，不是游戏事实；它可以很薄，只回答“这个外部 session 当前是否绑定某个游戏 save”。

因此第三阶段插件不应直接写入可提交状态。插件最多用 `session_key` 查询 workspace binding，然后调用 rpg-engine preflight API，让目标 save 的 SQLite 记录 pending/ready/expired。

## 未来 3B：混合会话策略

本节是 3B 方向摘要；详细工程任务、接口决策和验收清单见 [`../2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md`](../2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md)。

混合会话策略不属于当前代码接入阶段。本节记录未来 3B 启用 Platform/Hermes prewarm 时的边界：同一个平台会话里可能既有普通聊天，也有游戏行动，因此不能对所有平台输入都无条件 prewarm。QQ 只是 V1 示例。

`GameSessionGate` 已在 rpg-engine 内作为纯函数契约实现；3B 平台薄 adapter 接入时应使用该 gate：

```text
Platform MessageEvent
  -> Hermes 用户插件
  -> GameSessionGate
      -> inactive: 不 prewarm，交给 Hermes 普通聊天
      -> active_game: 可以 prewarm
      -> pending_clarification: 必须按游戏澄清处理
      -> cooldown: 只在强匹配 active save/message context 时 prewarm
```

V1 规则：

- 默认 inactive，不预热所有普通 QQ 消息。
- 首次成功调用 rpg-engine 并进入某个 save 后，由 rpg-engine 将当前 `session_key` 标记为 active_game。
- active_game 可以有 TTL，例如最近 10-30 分钟内有游戏行动才自动 prewarm。
- pending clarification 优先级最高；玩家下一句应被视为游戏澄清回答。
- slash command、审批、更新、普通 Hermes 控制消息永远不 prewarm。
- 如果 active_game 下用户其实在普通聊天，prewarm 最多浪费一次内部 AI；最终 Hermes 不调用 rpg-engine 时，cache 自然过期，不产生输出、不产生存档变化。

这让“普通聊天”和“游戏中”可以共用一个 QQ 会话，同时避免后台 AI 对所有消息乱跑。

## 已定默认、当前验收与后续待拍板

第一阶段和第二阶段已按拍板边界推进：只做 rpg-engine 内部 AI 与 preflight cache，不碰 Hermes/QQ 代码。第三阶段平台体验决策集中在未来上线前再拍板。

已建议并默认采用：

- V1 风险口味：默认 `routine/rest/travel/explore` 为 `yellow_fast`；`gather/craft/social/random_table` 为 `yellow_consensus`；`combat` 为 `red`。
- 是否允许自动 commit：V1 不允许。`player_turn` 只生成 pending/preview，仍由 `player_confirm` 保存；`player_act` 只是兼容 wrapper。
- 内部 AI timeout 后“能过”的定义：仅 fast action + slots 完整 + binder 成功 + preview/validation 通过 + 无 hidden/maintenance/composite/pending clarification。
- 第二/第三阶段正式链路是否允许外部直传 `internal_candidate`：不允许。只传 `preflight_id/message_id/text_hash/platform/session_key`，内部候选从内核 cache 取。

当前阶段可以由工程先设默认、以后调参：

- 审计详细度：默认存 hash、版本、loaded item ids、截断摘要和错误原因；不存完整 hidden context；raw AI output 只在 debug 开关下保存。
- direct provider 配置：默认从环境变量读取 API key，不复用 Hermes 私有配置；provider/model/base_url/timeout 都可配置。
- fallback 策略：`hermes_z` 只作为兼容 fallback；fallback 输出也必须经过同一 schema validator。

第三阶段可以由工程先设默认、以后调参：

- active_game TTL：默认 20 分钟。
- cache TTL：`pending` 30-60 秒；`ready` 2-5 分钟；`used/rejected/failed` 保留短期审计后清理。
- session binding 存储：workspace 级 SQLite 或 `.aigm/session-bindings.sqlite`，默认只存 hash 后的 session/user 标识。
- IntentContext 存储：默认存 `context_hash + 版本 + 相关 item ids + 截断摘要`，不存完整上下文。

第三阶段上线前必须拍板：

- 是否真的启用 Hermes/QQ prewarm。当前阶段不做。
- QQ 范围：V1 只做 C2C 私聊和普通群 @，还是包含 guild channel、guild DM、语音、图片/引用消息。
- 远期多人或群聊玩法：每个群成员独立存档，还是群共享队伍/存档。单人游戏 V1 不需要该决策。
- guild DM 是否禁用游戏预热。当前 QQ guild DM 身份字段更容易串线，V1 建议禁用。
- 游戏激活方式已初步拍板：首次成功调用 rpg-engine 后自动 active，并按 TTL 自动失效；第三阶段只需确认是否提供手动退出/继续命令。
- pending clarification 是否永远吃下一句，以及是否提供“退出澄清/普通聊天”逃逸词。
- QQ 可见反馈策略：仅 typing、延迟 ACK、还是私聊/群聊分策略。该项不阻塞阶段 1/2。

当前阶段验收前必须覆盖：

- `InternalAIService` 主路径测试：direct/lightweight provider 可完成 JSON task，旧 `hermes -z` 只在显式 fallback 配置时出现。
- schema 测试：`oneOf`、未知字段、错误类型、错误 enum、嵌套 plan shape 真的被拒绝，而不是只靠 normalizer 吞掉。
- 风险矩阵测试：逐 action 验证 `green/yellow_fast/yellow_consensus/red`，以及 hidden、maintenance、forced save、prompt injection、composite、missing slots 必升风险。
- timeout/fallback 测试：fast action 超时且 validation 通过可继续；yellow_consensus/red 超时必须澄清或阻断。
- 外部低信任测试：外部 candidate 可参与仲裁，但不能伪装 internal；内外不一致必须澄清。
- 自动提交测试：默认绝不自动 commit。
- 审计/telemetry 测试：记录 task/backend/model/status/elapsed/error/hash/fallback/risk decision，内容截断，无 hidden/raw context 泄漏。

阶段二回归与第三阶段验收前必须覆盖：

- preflight cache 测试：状态机、TTL、ready hit、used/rejected、stale reject，校验 text hash、save、base turn、context/schema/model/profile/provenance。
- 外部直传测试：player/external 不能传 `internal_candidate`，只能传 `preflight_id/message_id/text_hash/platform/session_key`。
- Platform gate 测试：inactive、slash、空文本、media-only、bot/self message、pending approval/clarification、非 active save 不 prewarm；插件失败不影响正常链路。
- 第三阶段 IntentJoiner 测试：内部先到、外部先到、pending 短等待、late ready unused、message-only preflight 携带 later external candidate 时不被误拒。
- 未来平台审计测试：preflight 生命周期事件完整，cache 清理策略生效。

## 当前问题

当前内部 AI 调用路径偏重：

```text
rpg-engine 需要内部 AI 复核
  -> subprocess hermes -z
  -> 启动完整 Hermes oneshot
  -> 加载配置、rules、tools、provider
  -> 调模型
  -> stdout 返回 JSON
  -> rpg-engine 再解析和仲裁
```

这个设计适合早期验证，因为复用了 Hermes 的 provider 配置和进程隔离；但它不适合长期实时游戏体验。每次内部判断都重新启动完整 Hermes，会把 CLI 启动、配置加载、工具加载、provider 初始化成本叠加到模型响应时间上。

长期接入 QQ 时，当前 QQ 到 rpg-engine 的慢链路大致是：

```text
QQ 用户输入
  -> Hermes 收到
  -> Hermes Agent 先思考
  -> 外部 AI 生成判断并决定调用 rpg-engine
  -> rpg-engine 现在才启动内部 AI
  -> 内外仲裁
  -> preview / commit / clarification
```

目标是把内部 AI 提前、变轻、可复用，让它和外部 AI 并发。

## 第一阶段：轻量内部 AI 小裁判

目的：先把内部 AI 从“每次启动 Hermes 的外部子进程”改成 rpg-engine 自己的轻量内部 AI 模型层。

目标形态：

```text
rpg-engine
  -> InternalAIService
      -> lightweight provider client
      -> task prompt registry
      -> schema validator
      -> timeout / retry / fallback
      -> telemetry
```

不再把主路径写成：

```text
rpg-engine
  -> subprocess hermes -z
      -> full Hermes oneshot agent
      -> provider call
      -> stdout JSON
```

InternalAIService 应尽量轻：

- 不加载完整 Hermes Agent。
- 不加载普通对话 toolsets。
- 不读取普通聊天 session。
- 不给模型隐藏 GM 信息，除非任务明确是 GM/maintenance 内部任务。
- 缓存 schema、action registry prompt 片段、静态 task prompt。
- provider/model 可配置，默认目标模型为 `deepseek v4 flash` 或当前配置里的等价 flash 模型名。

建议接口：

```python
internal_ai.complete_json(
    task="intent_independent_candidate",
    prompt=prompt,
    schema_name="intent_candidate",
    timeout_s=8,
)
```

第一批任务：

- `intent_independent_candidate`：只看玩家原文和 player-visible context，独立输出意图候选。
- `intent_review_external`：看到外部 AI candidate 后，复核其 action、mode、slots、安全性。
- `safety_review`：检查 forced save、hidden info、prompt injection、maintenance 越权。
- `state_audit`：commit 前后的状态一致性审计，可保持可选或后台化。
- `memory_summarize`：后台整理事件、NPC 记忆、日志压缩。

第一阶段完成标准：

- 内部 AI 可以不走 `hermes -z` 完成 JSON task。
- 旧 `hermes -z` backend 仍可作为显式 fallback。
- latency eval 能记录 cold/warm p50、p95、timeout rate。
- 意图识别 eval 质量不低于当前内部 AI helper。

## 第二阶段：预判缓存和凭号取餐（已实现，保留为架构记录）

本阶段已在 rpg-engine 内完成主链路。本节保留为架构记录：让 rpg-engine 能保存、查询、复用“提前算好的内部 AI 判断”，但不负责平台侧消息监听或 QQ/Hermes prewarm。

第二阶段不是负责 QQ 预热，而是先让内核具备这个能力：

```text
外部 AI 调 rpg-engine
  -> 带上 user_text / external_candidate / preflight_id / message_id 或 text_hash
  -> rpg-engine 优先用 preflight_id；message_only 可用 message_id/text_hash/platform/session_key 查提前算好的内部 AI 判断
      -> ready/hit: 直接使用提前算好的 internal_candidate
      -> pending: 短等软截止，超时 bypass 并回落现场内部 AI
      -> miss/rejected/expired/used: 回落现场内部 AI
```

这里：

- 当前已实现的“取餐号”有两种：`candidate_bound` 用 `preflight_id`；`message_only` 可用 `platform/session_key/message_id/source_user_text_hash`。
- `message_id` / `text_hash` 已在 3A 中升级为无 `preflight_id` 时的查找键，但只限 `message_only` identity，且必须唯一匹配当前 save/base_turn/context/model/schema/task。
- `internal_candidate` 是“后厨提前做好的菜”。
- `preflight cache` 是“凭号取餐的窗口”。

第二阶段要改的是 rpg-engine：

- 公共 runtime/MCP 接口只接收 `external_intent_candidate` 与 `preflight_id/message_id/source_user_text_hash/platform/session_key`。
- `internal_candidate` 只能由内核从自己的 preflight cache 读取，不能由外部调用方伪造上传。
- 内核内部仲裁层可以吃 `external_candidate + cached_internal_candidate`。
- 如果 cache 已有可接受的 internal candidate，就不要再同步启动内部 AI。
- 增加 `preflight cache`，状态包括 `pending`、`ready`、`failed`、`expired`、`used`、`rejected`。
- 使用 `message_id + platform/session_key + source_user_text_hash + save_id/base_turn_id + candidate_hash` 防 stale。
- `intent_context_id` 由内核生成并写入 `TurnProposal.context_id`/provenance；validation 通过 `preflight_id` 回查 DB 中的 cached preflight context。

第二阶段的仲裁规则：

```text
外部 AI candidate
内部 AI candidate
规则/安全预检
        |
        v
deterministic arbiter
        |
        +-- 一致且可绑定 -> preview / validate / commit
        +-- 不一致/缺槽位/不安全 -> clarification / block / fallback
```

第二阶段已实现能力与维护标准：

- rpg-engine 内部仲裁能吃 `external_candidate + cached_internal_candidate`。
- 当前实现以 `preflight_id` 优先消费缓存；无 `preflight_id` 时，`message_only` 按消息身份查找唯一可用 review。`candidate_bound` 仍要求显式 `preflight_id`，避免 later external candidate 改变缓存语义。
- 预判结果过期、文本不一致、turn/version 不一致时不会被误用。
- 内部 AI 超时不视为同意。

## 未来第三阶段：Platform Prewarm Layer

本节保留为架构背景。3B 施工时优先阅读 [`../2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md`](../2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md)，避免把历史讨论当作完整实现清单。

本阶段不属于当前开发。本节目的：平台消息刚到，就让内部 AI 先开做，同时 Hermes Agent / 外部 AI 继续正常跑。QQ 只是 V1 adapter，不应把设计写死成 QQ 专用。

阶段三必须保持轻量：它只是“可丢弃的加速旁路”，不是新运行时。

```text
预热成功 -> 快一点
预热失败 -> 当没发生，正常走原链路
预热没命中 -> 正常现场调用内部 AI
```

V1 最小公共消息模型：

```text
platform: qqbot | discord | telegram | web | cli
message_id: 平台稳定消息 id
session_key: canonical Hermes/platform session key
text: NFKC strip 后文本
text_hash: sha256(normalized text)
message_type: text | command | media | mixed
chat: { type, id, scope_id?, parent_id?, thread_id? }
actor: { id, display_name?, authorized_via? }
timestamp
raw_ref?: adapter-local opaque metadata
```

平台 adapter 只负责把自己的事件转换成这张小纸条。rpg-engine 不关心 QQ、Discord、Telegram 或 Web 的细节，只认 `platform/session_key/message_id/text_hash/user_text`。

当前链路：

```text
平台用户发消息
  -> Hermes 收到
  -> Hermes Agent 思考
  -> Hermes Agent 决定调用 rpg-engine
  -> rpg-engine 才开始内部 AI 判断
```

第三阶段目标链路：

```text
平台用户发消息
  -> Hermes 收到 MessageEvent
  -> 用户插件读取原文、message_id、session_key、platform
  -> GameSessionGate 判断 active_game
  -> 插件 enqueue message-only preflight
  -> 插件立刻 allow，不拦截 Hermes 正常处理

同时：
  -> Hermes Agent / 外部 AI 正常思考并生成 external_candidate
  -> rpg-engine / InternalAIService 已经在独立生成 message-only internal review
```

当 Hermes Agent 后续调用 rpg-engine：

```text
Hermes 提交 external_candidate
  -> rpg-engine 优先用 preflight_id
  -> message_only 没有 id 时用 platform/session_key/message_id/text_hash 找到唯一 internal review
  -> 外部和内部一致：继续 preview / validate / commit
  -> 外部和内部不一致：进入 clarification / block / fallback
```

这个方案不改 Hermes core。只使用 Hermes 用户插件或等价薄 adapter 做轻量 prewarm：

- 插件只读取平台 MessageEvent 的原文和标识。
- 插件只通知 rpg-engine 启动 message-only preflight。
- 插件立刻返回 `allow`，不阻断正常 Hermes Agent。
- 插件不 commit、不读 hidden 信息、不做危险动作。
- V1 默认不发可见 ACK/typing；如果要发“收到，正在判定”，也应做延迟 ACK，例如 800ms 后仍未完成才发，避免快速回复时多发一条。

### 阶段三轻量边界

必须做：

- `GameSessionBinding`：极薄 workspace 状态，只记录 `platform`、hash 后的 `session_key/user_id`、active save、state、active_until、last_message_id、可选 clarification_id。
- `message-only preflight`：平台消息刚到时通常没有 external candidate，因此该模式不能绑定 later external candidate hash。
- `pending` 短等待：正式调用发现匹配 preflight 仍 pending 时，只短等一次。
- 轻量 enqueue/worker：bounded queue + 1 个 worker；队列满就 drop，失败只记录 trace。
- 按 `preflight_id` 优先消费；没有 id 时允许用 `platform/session_key/message_id/text_hash/save/base_turn/context` 找唯一未过期记录。

当前代码状态：

- 已实现：rpg-engine 内核 `message_only` identity、无 `preflight_id` message lookup、pending 短等待、`late_ready_unused`、bypassed/expired 状态机、`GameSessionGate` 纯函数契约与测试。
- 已实现：`intent_preflight` 创建 pending 后立即提交，内部 AI 在事务外运行；正式链路可以在另一个连接里看到 pending 并在短等待窗口内命中 ready。
- 2026-07-03 已实现：rpg-engine 侧 3B 平台无关 binding store、bounded queue/worker、drop reason、metrics、feature flag、标准 `player_turn` 与兼容 `player_act` 的被动 preflight 标识消费。
- 仍未实现：Hermes/QQ 真实薄 adapter、ACK/typing、真实平台 latency/hit-rate metrics。

先不要做：

- 不做完整跨平台 SDK。
- 不改 Hermes core、Hermes gateway、QQ/Discord/Web adapter core。
- 不做 guild DM、guild channel、语音、图片、引用消息预热。
- 不做多人/群共享存档。
- 不做自动 commit，不绕过 `player_confirm`、validation、approval、clarification。
- 不在 binding 中保存 raw session id、hidden context；raw text 只允许在 save preflight cache 中短 TTL 存放，后续可迁移为 hash + 短预览。

V1 平台范围：

- QQ C2C 私聊与普通群 @ 可作为第一批。
- QQ guild DM 默认禁用预热，因为现有身份字段更容易串线。
- Discord/Telegram/Web 以后作为 adapter 接入同一公共消息模型。

### 外部/内部候选汇合策略

阶段三不要求外部 AI 和内部 AI 谁先谁后。正式执行时只做一个短“汇合窗口”，不能互相无限等待。

```text
玩家原话
  -> 外部 AI candidate
  -> 内部 AI review
  -> 规则 candidate
       |
       v
IntentJoiner 汇合
       |
       v
arbiter / clarification / block / low-risk fallback
```

四种情况：

1. 内部 AI 先完成，外部 AI 后来：最理想。正式调用时直接取 ready cache，进入三方仲裁。
2. 外部 AI 先来，内部 AI 还 pending：短等 `300-800ms`，硬上限 `1s`。ready 就用；还没 ready 就不等。
3. 两边都没来或没有 preflight：走现有普通链路，rpg-engine 现场启动内部 AI，timeout 仍为 `6-8s`。
4. 内部 AI 太晚完成：标记 `late_ready_unused` 或等价 telemetry，不能回头影响已经处理完的当前回合。

等待规则：

```text
prewarm worker 内部 AI timeout: 6-8s
正式调用 pending wait: 300-800ms
pending wait 硬上限: 1s
总用户体验硬线: 10-12s
```

汇合决策：

```text
有 ready 就用；
有 pending 就短等；
短等还没 ready 就不等；
低风险 fast action 可在外部 AI + 规则一致、slots 完整、binder/resolver/validation 通过时继续；
中高风险、combat、forced save、hidden、maintenance 必须等内部 AI 或澄清/阻断；
迟到结果只记录，不回头改当前回合。
```

状态机：

```text
none -> pending -> ready -> used
              \-> failed
pending -> expired
ready -> rejected | expired
ready_after_turn_handled -> late_ready_unused
```

第三阶段完成标准：

- 平台输入到达后，内部 AI 能在 Hermes Agent 调 rpg-engine 前启动。
- preflight hit rate 可观测。
- 命中 ready 时，rpg-engine 不再重复调用内部 AI。
- 插件失败时，正常 Hermes -> rpg-engine 链路仍可 fallback。

## 为什么不直接改 Hermes core

不推荐改 Hermes core 的原因：

- Hermes 上游持续更新，core patch 容易冲突。
- 当前需求本质是 rpg-engine 的游戏内核体验优化，不应该绑定到某个 Hermes 内部实现。
- 未来如果做并发预热，也应优先用 rpg-engine preflight cache 和外部插件式集成，不把游戏逻辑写进 Hermes core。

更稳的边界是：

```text
Hermes core: 不改
当前 rpg-engine: 实现 InternalAIService、direct provider、schema validation、risk/fail policy
未来 rpg-engine: preflight cache、双候选仲裁、平台 prewarm 接入点
未来 Hermes 用户插件: 只做 QQ 输入 prewarm，不做提交或内核判断
```

## 不优先选择独立 QQ 入口

独立 AIGM QQ ingress 的理论体验最好：

```text
QQ -> AIGM Orchestrator -> external AI + internal AI 并发 -> rpg-engine -> QQ
```

但近期不建议作为第一选择，因为它会复制 QQ 接入、鉴权、会话、发送逻辑，和当前 Hermes QQ gateway 形成双入口，维护成本高。

只有当用户体验仍受通用 Hermes Agent 工具选择延迟严重影响时，才考虑这条路线。

## 阶段一收尾完成状态（2026-07-02）

已完成：

1. 新增 `InternalAIService`，统一 `off/direct/hermes_z` backend。
2. `direct` backend 走 OpenAI-compatible chat completions，可配置 provider/model/base_url/api_key_env/timeout。
3. 默认 fallback 为 `off`。只有显式 `fallback_backend=hermes_z` 才会调用旧 `hermes -z`。
4. MCP/runtime/context/intent router 已透传 intent backend/provider/model/timeout/base_url/api_key_env/fallback_backend。
5. 内部 intent review 走 `InternalAIService`，返回必须经过 JSON Schema validation 和 normalizer。
6. 引入 `jsonschema>=4.20`，主路径使用 Draft202012Validator，覆盖 `oneOf`、unknown field 等 schema 错误。
7. 增加集中 `action_risk`：`routine/rest/travel/explore` 为 `yellow_fast`；`gather/craft/social/random_table` 为 `yellow_consensus`；`combat` 为 `red`。
8. 内部 AI 不可用时，只有低风险且外部/规则一致、slots 完整、binder 成功、preview/validation 可继续的 fast action 可规则兜底；复杂/安全行动进入澄清或阻断。
9. `combat.ready_state` 这类安全确认槽位不接受 AI 候选直接填充，仍要求玩家确认。
10. archivist/state_audit/reflection/semantic helper 支持新的 backend 语义，不再硬编码只认 `hermes`。
11. eval 支持 fake `hermes_z` 和 direct fake-response 两种测试模式；real canary 报告 latency p50/p95、8000ms budget 和 over-budget rate。
12. 阶段一全量测试通过；阶段二补强后重新跑全量测试，见下方“验证结果”。

本轮专家复审发现并已修复：

- `intent_fallback_backend=direct` 曾被配置层接受，但 provider 会按 Hermes fallback 执行；已改为 fallback 只允许 `off/hermes_z`，非法值快速失败。
- direct 测试曾依赖本机没有 API key；已改为显式缺失测试 key，避免误发真实请求。
- `combat.ready_state` 曾可能由 AI 候选填充后绕过玩家确认；已在 binder 层忽略 AI 提供的安全确认槽位并记录 trace。
- audit 中 `advisory/no_direct_writes` 曾固定为 true；已改为使用实际 policy 值。

## 阶段二完成状态（2026-07-02）

阶段二目标：不修改 Hermes/QQ core，只在 rpg-engine 内部提供可并发预热的内部 AI 入口；正式链路只消费内核自己缓存的 internal review，不接受外部直传 internal candidate。

已完成：

1. 新增 `intent_preflight_cache` 表，状态机支持 `pending/ready/failed/expired/used/rejected`。
2. 新增 `GMRuntime.preflight_intent()` 和 MCP `intent_preflight`，只写 advisory cache，不 preview、不生成 delta、不 commit。
3. `start_turn`、`preview_from_text`、`act`、`context build` 支持透传 `preflight_id/message_id/source_user_text_hash/platform/session_key`；当前缓存消费以 `preflight_id` 为准，其余字段用于身份校验。
4. `AIIntentRouter` 优先消费 preflight cache；cache miss/rejected/expired/used 时回落到正常内部 AI 调用，并把原因写入 trace。
5. cache 命中后仍必须经过 arbiter、binder、resolver、preview/validation/commit guard；缓存不拥有提交权限。
6. `source_user_text_hash` 改为内核根据当前 `user_text` 计算；外部传入的 hash 只作为声明值核对，不能覆盖内核计算结果。
7. cache 身份绑定增强为：`user_text`、`message_id`、`platform`、`session_key`、`save_id`、`base_turn_id`、`context_hash`、`intent_context_id`、`provider/model/backend/fallback_backend`、`schema_version`、`task_version`、`external_candidate_hash`、`rule_candidate_hash`。
8. cached internal review 消费前重新跑 `internal_intent_review.schema.json` validation；坏缓存不能变成 OK helper。
9. ready/failed 只能从未过期的 pending 状态转换；consume 是 single-use，成功/失败/过期转换都做条件更新并检查 rowcount，不覆盖已 used 记录。
10. `intent_context_id` 已进入 `TurnProposal.context_id` 和 provenance；validation 会通过 `preflight_id` 回查 DB 中的 `intent_context_id`，拒绝与 cached preflight context 不一致的 proposal。
11. CLI/MCP 文档和 surface inventory 已同步 `intent_preflight` 与低层工具 profile 边界。

AI 游戏开发组复审结论：

- 未发现 P0：没有发现 preflight 绕过 resolver、validation 或 commit guard 的直接写入漏洞。
- 已修复 P1：调用方可伪造/复用 `source_user_text_hash` 的问题；遗漏 `message_id/platform/session_key` 校验的问题；候选 provenance 未绑定的问题；cached review 未重新 schema validation 的问题；single-use consume 与 rejected/expired 状态转换未完整检查 rowcount 的问题；backend/fallback 创建和消费规范化不一致的问题；`intent_context_id` 未进入 proposal/validation DB 锚定边界的问题。
- 已同步 P2 文档：MCP include 示例、`intent_preflight` 工具契约、AI client prompt 工具列表、CLI spec、surface inventory 的普通/低层 profile 边界。

阶段二安全收尾复核（2026-07-02 已完成）：

- `rejected/expired/failed/used/pending` 这类非 hit preflight lookup 不再生成 proposal context/provenance；intent trace 只保留安全摘要，非允许命中时不带 record。
- proposal validation 要求：只有 intent trace 中 `preflight.status == hit` 时，`provenance.preflight_id` 才有效；DB 行在被消费后应为 `used`，并且 `intent_context_id` 必须与 proposal 一致。
- 坏缓存 schema revalidation 失败时，router 会把它当作 cache miss，回退现场内部 AI；该坏缓存不进入 proposal provenance。
- `player_confirm` 已收紧为必须传入 pending action 的 `session_id`，并在确认边界内给 proposal 标记 `human_confirmed=true` 和确认 provenance。
- `player_turn_commit` 已在 validation pipeline 与 commit service 两层要求 `expected_turn_id/command_id`，示例 campaign smoke delta 已同步补齐。
- MCP 空字符串 per-call override 已按“未传值”处理，不会把默认 AI 配置覆盖成空值。
- arbiter 缺槽语义已拆清：双方都缺同一槽位是 `ai_consensus_unbound`；外部缺槽但内部补齐才进入澄清分歧；`external_candidate_quality=incomplete` 不再被一刀切当成硬分歧。

阶段三 3A 已完成的内核闭环：

- `message_only` 与 `candidate_bound` 两种 preflight identity 已分离。`message_only` 不绑定 external/rule candidate hash；later external candidate 只进入正式 arbiter，不参与缓存命中 identity。
- `IntentJoiner` 已实现：`preflight_id` 优先；无 id 时按 `platform/session_key/message_id/text_hash/save/base_turn/context/model/schema/task` 找唯一 `message_only` 记录。
- pending 短等待已实现，硬上限 1000ms；等待超时会标记 bypass，后续 late ready 转 `rejected/late_ready_unused`，不能回头影响已处理回合。
- pending 过期先转 `expired`，不会被错误 bypass；bypassed pending 不再参与 message lookup，避免平台重复投递造成 ambiguous。
- `intent_preflight()` 创建 pending 后立即 commit，内部 AI 在事务外运行；正式链路可在另一个连接中等待并命中后到的 ready。
- 正式链路 preflight 非 hit 后会在现场内部 AI fallback 前提交 cache 状态转换，避免把 SQLite 写锁跨过内部 AI 调用。
- bypass CAS 失败时会重读最新状态；如果 ready 刚好赢过 bypass，本次正式链路会直接消费，不留下后续可重复消费的 active ready。
- `message_only` 创建阶段会忽略 external candidate，避免“外部 A 参与生成的内部 review 被外部 B 命中”。
- `GameSessionGate` 已作为 rpg-engine 纯函数契约落地：默认 inactive、空 TTL 视为 expired、缺 message_id 不 prewarm、bot/self/approval/media/command/重复消息等都会拒绝。
- MCP `intent_preflight` 已加 pending clarification guard；默认数值 `0` 不再误判为 AI override；被动 preflight 标识不算 per-call intent override。

阶段三仍保留的设计/观察项：

- P2：当前 `context_hash` 覆盖 save/turn/location/time/text/candidate 等核心身份，但还没有完整纳入 visibility profile、可见实体列表或规则卡片版本。binder/resolver/validation 能降低提交风险，但后续如果让 prewarm 更激进，应继续补 context identity。
- P2：完整 durable audit/metrics 还应覆盖 prewarm start、hit/miss、pending wait、expired、used、rejected、timeout、arbiter decision、stale reject、late ready unused 的聚合统计。
- P2：message-only 重复预热目前通过 bypass/expired 排除降低歧义；未来 3B 平台 adapter 最好再做幂等 upsert 或 message 级去重，避免重复 enqueue 浪费内部 AI。
- P2：preflight cache 当前仍存 `session_key` 原文用于身份校验；3B 平台 adapter 和长期审计应改为 hash/redaction，只持久化 hash、reason、message_id、session hash 和截断摘要。
- P2：`message_only` 创建阶段目前不硬性要求 `platform/session_key/message_id` 三元组，缺失字段会导致 by-message lookup miss；后续 3B 若只允许平台消息预热，可升级为硬校验。

当前保留观察项：

- 现有旧存档如果已经应用过旧版 `0006/0007`，需要继续跑迁移到 `0008_intent_joiner_message_only.sql` 才能使用 3A 的 message-only identity、bypassed/late-ready 字段和 message lookup 索引。
- real canary 仍是非门禁观察项；报告会显示 expectation miss 和 latency over-budget，但不会阻断普通测试。
- QQ/Hermes 并发预热插件仍是后续 3B；本轮只完成 rpg-engine 内核 3A，不改 Hermes/QQ 代码。
- 平台预热默认 feature flag off；即使未来启用，也必须可按平台/save/session 关闭，关闭后完全回到现有 Hermes -> rpg-engine 现场内部 AI 链路。

## 验证结果

- 受影响测试：`tests/test_preflight_cache.py tests/test_game_session.py tests/test_runtime.py tests/test_mcp_adapter.py tests/test_ai_intent.py tests/test_validation_pipeline.py tests/test_eval_suite.py tests/test_surface_inventory.py tests/test_namespace_boundaries.py tests/test_ai_helper.py` 通过，`167 passed, 156 subtests passed`。
- 升级/CLI 回归：`tests/test_upgrade_v2.py tests/test_v1_cli.py tests/test_author_kit_new.py tests/test_official_example.py` 通过，`20 passed, 31 skipped, 23 subtests passed`。
- 全量测试：`291 passed, 103 skipped, 216 subtests passed`。

## 阶段三 3A 专家复核结论

三位专家一致认为：3A 的正确边界是先完成 rpg-engine 内核契约和测试，不直接接 QQ/Hermes 平台预热上线。本轮已按该边界完成 3A，并修复专家复核指出的并发、状态机和安全门问题。

当前拆法：

```text
Phase 2.5 / 3A：rpg-engine 内部契约和测试（已完成）
  -> message-only identity profile
  -> IntentJoiner
  -> 无 preflight_id 的 message lookup
  -> pending 短等待
  -> late_ready_unused telemetry
  -> GameSessionBinding/Gate 契约和测试

Phase 3B：平台薄 adapter
  -> Hermes 用户插件或等价薄 adapter
  -> 只 enqueue prewarm，立刻 allow
  -> 不读 hidden，不 commit，不阻断正常 Hermes Agent
```

不建议现在直接做 3B 的原因：

- Hermes 上游和 QQ 接入持续更新，本轮不改平台代码可以避免冲突。
- rpg-engine 侧 gate 只是纯函数契约，尚未有 workspace 持久 binding store、last_message_id 更新、bounded queue/worker 和平台 feature flag。
- 可观测性还需要补：hit rate、miss/reject/expired/late_unused、pending wait p50/p95/max、queue drop、fallback success、clarification rate。

3A Go 条件（已满足）：

- `message-only` 与 `candidate-bound` 两种 preflight identity 明确分离。
- later external candidate 不参与 cache 命中 identity，只进入正式 arbiter。
- `IntentJoiner` 只做短汇合：`preflight_id` 优先；无 id 时按 `platform/session_key/message_id/text_hash/save/base_turn/context` 找唯一未过期记录；pending wait `300-800ms`，硬上限 `1s`。
- late ready 只记 telemetry，不能回头改已经处理完的回合。
- 所有路径继续经过 arbiter、binder、resolver、preview/validation、`player_confirm` 或低层 commit guard。

3A/3B No-Go 仍保留：

- 不改 Hermes core / hermes-agent / Hermes gateway / QQ adapter core。
- 不做独立 QQ ingress。
- 不做自动 commit。
- 不缓存 delta 或 TurnProposal。
- 不允许外部上传 `internal_candidate`。
- 不在 binding 中存 raw session id、hidden context 或长期 raw text。
- 不做 guild DM、语音、图片、引用消息、多人/群共享存档。

## 当前阶段体验目标

- 内部 AI 不再因每次 `hermes -z` 重启产生固定慢启动成本。
- 简单 query / 无写入路径：继续优先走确定性内核和快路径。
- 可保存 action 的意图共识：内部 AI soft timeout 6-8 秒，硬上限约 10-12 秒。
- 内外一致时继续 preview/commit。
- 内外不一致时快速澄清，不让用户等完整长链路失败。
- 内部 AI 超时不视为同意。涉及写入、安全、隐藏信息、复杂槽位时，超时应 clarification 或 block。
- latency/audit 要能看出 direct provider、fallback、schema error、timeout、risk decision 各自耗时和比例。

## 未来第三阶段体验目标

- 平台收到输入后，prewarm 应在 0.3-1 秒内启动；可见 typing/轻量 ACK 作为后续体验优化，不是 V1 必需项。
- preflight 命中时，Hermes Agent 调 rpg-engine 后不重复等待内部 AI。
- 插件失败或 preflight miss 时，正常 Hermes -> rpg-engine 链路仍可 fallback。

## 最终设计原则

这套设计的核心不是让 AI 拥有更大权限，而是让 AI 更早、更轻、更可验证地给出结构化候选。

```text
外部 AI：理解玩家表达，生成低信任候选。
内部 AI：在内核控制的上下文中独立复核。
规则/确定性逻辑：负责硬安全、风险分级、结构化校验和低风险兜底。
内核：负责绑定、仲裁、验证和提交。
```

标准路径是：只有外部 AI、内部 AI 和内核确定性校验达成一致，玩家行动才进入正式执行。

唯一允许的 V1 例外是低风险 `yellow_fast` 兜底：内部 AI 不可用时，外部 AI 与规则候选不冲突、slots 完整、binder/resolver/validation 通过、且不涉及 hidden/maintenance/combat/forced save/pending clarification，才可以先生成 preview/pending proposal。这个例外仍然不允许自动 commit。
