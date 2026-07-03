# 外部项目经验对照评审

文档状态：**Phase 3 前架构校准材料**
调研日期：2026-07-01
适用对象：RPG Engine / AIGM Kernel 全链路优化，尤其是 `TurnProposal`、validation、commit、projection、MCP/AI surface、Campaign/Save Package 管理。
调研原则：优先参考官方文档、官方仓库或项目维护方文档；不照搬框架，只提炼对本引擎可执行的架构约束。

## 1. 结论摘要

外部项目经验支持当前优化方向：No-AI baseline、结构化事实源、存档包和内容包分离、外部 AI 低信任、MCP 默认最小暴露、预演/校验/提交分层，都是正确方向。

但外部经验也提示：Phase 3 不能只新增 `TurnProposal` 类型。它必须同时明确：

- 哪个数据结构是事实源，哪个只是候选、上下文、投影或缓存。
- 哪些字段可以进入 Save Package，哪些只能进入 runtime/projection/cache/log。
- Campaign Package 的 manifest/schema/version/capability 是否足够支撑升级和兼容。
- 外部 AI、MCP tool、作者工具、维护工具是否分 profile，并有可测试的调用序列约束。
- commit 和 projection 是否像 durable workflow 一样可追踪、可重放、可恢复。

因此，本轮建议：

1. Phase 3 继续做 `TurnProposal` 薄层，但必须带 `source/provenance/profile/validation_state/commit_state`。
2. 在 `validate_proposal` 之前，先定义 proposal 与 save fact 的边界：proposal 不是事实。
3. 在 `commit_proposal` 前，保留当前 `validate_delta -> commit_turn` 主路径，不要一次性重写保存。
4. 同步补 Campaign/Save Package 版本和兼容策略草案，避免后续 migration 失控。
5. 对 MCP 和外部 AI 保留低信任策略：prompt/skill 不是权限来源，tool call 必须过 profile 和 transcript 检查。

## 2. 参考来源

| 项目 | 资料 | 研究重点 |
| --- | --- | --- |
| Ink | [Running your ink](https://github.com/inkle/ink/blob/master/Documentation/RunningYourInk.md) | story state JSON、choice loop、external function side effects、tags/metadata |
| Ren'Py | [Saving, Loading, and Rollback](https://www.renpy.org/doc/html/save_load_rollback.html)、[Persistent Data](https://www.renpy.org/doc/html/persistent.html) | save/rollback/persistent 分层、可保存/不可保存对象、save metadata、兼容 |
| Yarn Spinner | [Variable Storage](https://docs.yarnspinner.dev/components/variable-storage) | 变量存储可替换、in-memory 不等于持久化 |
| SugarCube/Twine | [SugarCube v2 Documentation](https://www.motoslave.net/sugarcube/2/docs/) | story variables、temporary variables、state history、可序列化类型限制 |
| Inform 7 | [Out of world actions](https://ganelson.github.io/inform-website/book/WI_12_15.html) | 世界内行动和世界外命令不能混淆 |
| Godot | [Saving games](https://docs.godotengine.org/en/stable/tutorials/io/saving_games.html) | saveable object、JSON 限制、load 时重建对象 |
| Foundry VTT | [System Development](https://foundryvtt.com/article/system-development/)、[System Data Models](https://foundryvtt.com/article/system-data-models/) | package manifest、documentTypes、data model、compatibility |
| MCP | [Model Context Protocol Specification](https://modelcontextprotocol.io/specification/2025-06-18) | resources/prompts/tools、tool safety、user consent、data privacy |
| LangGraph / LangChain | [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview)、[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) | checkpoint/store、human review、tool policy、agent persistence |
| Temporal | [Workflow Definition](https://docs.temporal.io/workflow-definition) | deterministic workflow、external calls as activities、versioning |

## 3. 核心经验映射

### 3.1 事实源必须单一，投影和上下文不能反写事实

外部经验：

- Ink 的 runtime story state 可以序列化和恢复，但输出文本、标签和外部集成不是自动事实源。
- Ren'Py 区分 internal state、Python store、persistent data 和 rollback state，并明确有些对象不能保存。
- Godot 的保存示例要求每个可保存对象提供自己的 save 数据，load 时按数据重建对象。

对本引擎的要求：

- `turns/events/entities/clocks/meta` 或未来 `TurnCommitService` 写入结果必须是事实源。
- `ContextPacket`、`PreviewActionResult`、`TurnProposal`、snapshot、cards、memory、reports 都不是事实源。
- `ProjectionService` 只能从事实源重建派生产物，不能让 snapshot/cards 反写事实库。

专家检查问题：

- 是否存在任何从 projection/cache/report 反推事实并保存的路径？
- `TurnProposal` 是否明确标注 `proposal_only` 或 `not_committed`？
- 所有玩家可见叙事是否能追溯到 committed turn/event？

当前状态：

- 当前 `commit_turn()` 和 `save_turn_delta()` 已是事实写入主路径。
- 仍需在 Phase 3+ 防止 `TurnProposal`、response acceptance、turn assistant、maintenance 路径成为事实源旁路。

### 3.2 世界内行动和世界外命令要硬隔离

外部经验：

- Inform 7 把 save/quit 这类命令视为 out-of-world action，并强调这类命令不应影响虚构世界。
- Ren'Py 的 save/load/rollback 是引擎命令，不等于剧情行动。

对本引擎的要求：

- `query`、`health`、`campaign_validate`、`save_inspect`、`save_create`、`save_switch`、`start_or_continue` 属于世界外或外壳操作，不得推进剧情事实。
- `preview_from_text` 和 `preview_action` 只能生成预演，不能保存。
- `commit_turn` 或未来 `commit_proposal` 才能把世界内行动写入事实源。

专家检查问题：

- `save_create`、`start_or_continue` 是否可能在 onboarding 中写入剧情进度？
- `campaign_validate`、`health` 是否会自动 repair？
- 外部 AI 输入中出现 “commit_turn / JSON delta / hidden info” 时，是否会被当作玩家行动？

当前状态：

- `surface_inventory` 已将工具分为 `read_only`、`controlled_create`、`preview_only`、`validation_only`、`validated_commit`。
- `intent_router_gold_set.yaml` 已覆盖越权和工具注入文本。

### 3.3 存档兼容和持久数据必须提前设计

外部经验：

- Ren'Py 文档明确 save compatibility 不能天然保证；它区分 per-save state 和 persistent data。
- SugarCube 区分 story variables 和 temporary variables，并说明 state history 对可序列化类型有约束。
- Yarn Spinner 的变量存储默认可以是 in-memory，因此“运行时有变量”不等于“已经持久化”。

对本引擎的要求：

- Save Package 必须有 schema version、engine version、campaign version、migration status。
- 跨存档或跨 campaign 的数据必须单独定义，不能混入普通 Save Package。
- 运行时缓存、AI 中间状态、temporary variables 不应进入权威 save facts。

专家检查问题：

- Save Package 里哪些字段是事实，哪些是索引/cache/projection？
- 是否需要类似 `persistent` 的跨存档数据层？如果需要，是否独立于 Save Package？
- package upgrade 后旧 save 如何验证、迁移、回滚？

当前状态：

- 已有 Save Package / Campaign Package 管理入口和 profile inventory。
- 仍需在后续阶段补版本兼容策略、migration note、rollback note。

### 3.4 内容包需要 manifest、schema、capability 和数据模型

外部经验：

- Foundry VTT 的 system manifest 明确要求 `system.json`，并使用 `documentTypes` 和 data model 声明系统数据。
- Foundry 的 package 字段还包含 version、compatibility、relationships、packs、languages 等发行和依赖信息。

对本引擎的要求：

- Campaign Package 不应只是文件夹约定；它需要 manifest、capability、schema、content type、compatibility 和 tests。
- content authoring 和 runtime save 应分层：作者 AI 可改 campaign source，但不能写 save facts。
- package upgrade/reconcile/import/export 必须属于 maintenance/admin profile。

专家检查问题：

- Campaign Package 是否声明了每类 content 的 schema 和 capability？
- capability 和 action resolver 是否一一对应，有 smoke/gold tests？
- package upgrade 是否能 dry-run、diff、rollback？

当前状态：

- 现有 `campaign.yaml`、content schema、campaign validation、author kit 已覆盖一部分。
- Phase 3 之后应把 proposal/validation 和 package capability 更紧密关联。

### 3.5 AI 和外部工具必须按低信任、可审批、可恢复处理

外部经验：

- MCP specification 明确 tools 是 AI 可执行函数，需要用户知情、授权和工具安全控制。
- LangChain HITL middleware 对写文件、执行 SQL 等工具调用提供中断、审批、编辑、拒绝机制。
- LangGraph persistence 区分 thread checkpoint 和 long-term store，用于中断后恢复和跨会话记忆。

对本引擎的要求：

- AI 输出只能进入 `semantic_suggestion`、`TurnProposal`、state audit suggestion、authoring draft 等低信任层。
- 外部 AI prompt/skill 不授予权限；MCP tool description 也不应被当作可信安全边界。
- side-effecting tool 需要 profile、consent、validation 和 transcript tests。
- AI 失败时必须降级到 deterministic no-AI path。

专家检查问题：

- 有没有 AI 输出能直接写 facts？
- 外部 AI 能否调用 maintenance/admin/import/export/patch/repair？
- transcript 是否覆盖“自然语言直调低层 preview_action”“未 validate 就 commit”“失败 validate 后 commit”？

当前状态：

- 已新增 `mcp_transcript.py` 和 transcript fixture。
- `preview_action` 已移出默认 player profile，只在 low-level profile 注册；仍应继续用 transcript fixture 评估低层工具误用。

### 3.6 Durable workflow 思想适合借鉴，但不要引入重框架

外部经验：

- Temporal 要求 workflow 在重放时按同输入产生同序列 API 调用，外部交互应放到 activity 中。
- LangGraph 使用 checkpoints 支持中断、恢复、HITL 和 fault tolerance。

对本引擎的要求：

- `TurnProposal -> validate -> commit -> projection` 应有稳定事件记录和状态机。
- 随机表、AI 调用、外部工具、时间等非确定性输入必须记录 provenance 和结果，commit 时使用已记录结果。
- Phase 3 不需要引入 Temporal/LangGraph，但应采用“状态机 + event log + idempotent stage”的思想。

专家检查问题：

- 同一个 proposal 重试 validate/commit 是否幂等？
- commit 失败后能否知道停在哪个 stage？
- projection 失败后能否重建，而不是修改 facts？

当前状态：

- `commit_turn()` 已有 backup、state audit、projection refresh，但整体 stage 状态还不够集中。
- Phase 3/4 应引入 proposal state 和 validation report，再逐步收敛 commit/projection。

## 4. 项目逐项对照

### 4.1 Ink

可借鉴：

- story state 可序列化，适合“当前故事运行点 + 变量”的恢复。
- tags/metadata 用于把作者意图和运行时系统连接起来。
- external functions 区分有副作用动作和纯函数，这与本引擎的 `read_only` / `preview_only` / `validated_commit` 分层一致。

不应照搬：

- Ink 偏向嵌入式叙事脚本，本引擎需要 campaign/save/database/projection，因此不能把全部状态压成一个 story JSON。

落地建议：

- `TurnProposal` 记录 `provenance.tags`、`source_text`、`resolver`、`ai_provider/model`。
- 随机表和外部 AI 结果必须像 Ink state 一样可恢复，但不能作为未提交事实。

### 4.2 Ren'Py

可借鉴：

- 明确 “What is Saved / What isn't Saved”。
- 保存文件包含 metadata，能列举、检查、读取而不一定加载。
- persistent data 独立于具体存档点，可用于 gallery/unlock 等跨存档信息。
- rollback 是对玩家体验有价值的能力，但它要求清楚的状态边界。

不应照搬：

- Ren'Py 使用 Python pickle 等机制，本引擎应继续坚持 JSON/schema/SQLite 可检查结构，不应保存任意对象。

落地建议：

- 新增 Save Package 文档章节：`saved_facts`、`derived_state`、`runtime_cache`、`metadata`、`not_saved`。
- 如果需要跨存档数据，单独设计 `PlayerProfile` 或 `PersistentProfile`，不要混入普通 Save Package。

### 4.3 Yarn Spinner / SugarCube / Twine

可借鉴：

- Yarn Spinner 说明变量存储是可替换组件，默认内存变量不会自动落盘。
- SugarCube 的 story variables 参与历史，temporary variables 不参与；可保存类型受限。

不应照搬：

- Twine/SugarCube 对浏览器历史和 passage 的模型不适合直接套到长线 RPG simulation。

落地建议：

- 本引擎需要明确 `temporary_context`、`proposal_draft`、`committed_fact` 三层。
- Save Package schema 不应允许函数、任意对象、可执行脚本或未声明类型。

### 4.4 Inform 7

可借鉴：

- 世界内行动和世界外命令是概念上的硬边界。
- 查询、保存、退出、调试等外壳命令不推进世界时间。

落地建议：

- `IntentRouter` 应继续把 hidden、tool call、JSON delta、admin 命令归为 out-of-world 或 blocked，而不是“低置信玩家行动”。
- `query` 和 `health` 的 read-only 语义要像规则一样不可破。

### 4.5 Godot

可借鉴：

- 可保存对象自己提供 save data；load 时按数据重建。
- JSON 便于调试但有类型限制，复杂对象需要自定义编码/解码。
- load 前需要重置/重建现有对象，避免旧状态残留。

落地建议：

- `entities/clocks/projects/relationships` 应有清楚的 serializer/validator，不靠临时 dict 拼接。
- projection rebuild 应先清理或版本化旧 projection，再从事实源重建。

### 4.6 Foundry VTT

可借鉴：

- package manifest 是系统运行和分发的核心。
- `documentTypes` 和 DataModel 让内容类型在服务器层被认识，而不是加载时临时猜测。
- compatibility、relationships、packs、languages 等字段把发行和依赖纳入 manifest。

落地建议：

- Campaign Package 的 `campaign.yaml` 应继续向 manifest 演进：schema version、engine range、capabilities、content types、dependencies、migration policy。
- authoring tools 产出的内容必须被 campaign validate 和 smoke tests 接住。

### 4.7 MCP

可借鉴：

- MCP 把 resources、prompts、tools 分开；tools 是最危险的，因为 AI 可以执行函数。
- 协议强调用户同意、数据隐私、工具安全、授权和访问控制。

落地建议：

- 当前 `surface_inventory`、MCP tool list、AI prompt 低信任声明方向正确。
- 后续应考虑把低层 `preview_action` 标成 advanced/low-level，或者至少保持 transcript misuse tests。
- MCP 不应成为 package/admin/maintenance 的默认入口。

### 4.8 LangGraph / LangChain HITL

可借鉴：

- agent state 需要 checkpoint，长期事实需要 store，二者不是一回事。
- side-effecting tool 可以按 policy interrupt，等待人类 approve/edit/reject/respond。

落地建议：

- `TurnProposal` 是 checkpoint/proposal，不是 store/fact。
- `commit_turn` / `commit_proposal` 是 side-effecting tool，必须保留 approval/validation/profile 门禁。
- 外部 AI 只能建议，不应直接越过 player/GM 确认。

### 4.9 Temporal

可借鉴：

- 长流程需要 deterministic constraints，外部调用和不确定性应隔离并记录。
- 工作流版本化是长期运行系统的必需品。

落地建议：

- `ValidationPipeline` 的 stage 顺序应固定，stage 结果可记录、可重放。
- AI、随机表、当前时间、外部文件状态都应作为输入/provenance 记录，而不是在 commit 内临时重新生成。

## 5. 专家评审清单

### 产品经理

- 普通玩家路径是否保持简单：继续、查询、描述行动、确认、保存？
- package/admin/maintenance 能力是否没有进入玩家默认路径？
- No-AI path 是否足够快和准确，AI 只是增强？

### UX/交互设计师

- 玩家能否区分查询、预演、等待确认、校验失败、已保存？
- `TurnProposal` 的状态是否对人可解释？
- 失败时是否给出可行动的 repair option？

### 游戏设计师/内容作者

- 内容包 schema 是否足以表达世界、规则、能力、随机表和 smoke test？
- 作者 AI 产物是否只能进入候选/草稿，不能直接改运行事实？
- hidden/GM-only 信息是否不会被普通 query/MCP 泄露？

### 软件架构师

- `TurnProposal` 是否只是薄层合同，而不是新的巨型上帝对象？
- validation/commit/projection 是否有单一 owner？
- profile 是否横跨 CLI/MCP/runtime，而不是只写在文档里？

### 后端/内核工程师

- proposal validate 是否复用现有 resolver/delta_contract，而不是复制校验逻辑？
- commit 是否幂等，失败是否可定位 stage？
- migration、save import/export、package upgrade 是否隔离在 maintenance/admin profile？

### AI Agent 工程师

- 外部 Agent 默认 workflow 是否固定为 `player_turn -> player_confirm`，并且只有 developer/trusted 附录才使用 `start_turn -> preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)`？
- 低层工具误用是否有 transcript tests？
- AI helper 失败时是否降级到 deterministic fallback？

### AI/ML 与提示词工程师

- AI 输出是否记录 provider/model/prompt/schema/timeout/confidence？
- AI 结果是否只能覆盖低信任建议层，不能绕过 resolver 和 validation？
- No-AI baseline 与 AI-assisted lift 是否可比较？

### QA/测试工程师

- gold set 是否覆盖多语言、多动作、失败、越权、组合行动？
- package/save migration 是否有 fixture？
- projection repair/rebuild 是否有从事实源重放测试？

### SRE/可靠性工程师

- commit/projection 关键路径是否有 P50/P95 baseline？
- 失败是否能重试，是否有 audit log？
- long-running 或 interrupted flow 是否能恢复？

### 安全/权限/隐私工程师

- MCP tools 是否默认最小暴露？
- hidden/admin/maintenance 数据是否被普通 Agent 隔离？
- tool description 和 prompt 是否被当作不可信输入处理？

### 数据/评估工程师

- 是否有 intent accuracy、clarify rate、block rate、tool misuse rate、latency report？
- proposal 到 commit 的转化率和失败原因是否可统计？
- AI-assisted 与 No-AI 是否能 A/B 或离线回放？

### 发布/维护工程师

- Campaign/Save Package 是否有 schema version、engine version、migration note、rollback note？
- prompt/tool description/inventory 是否随协议版本发布？
- 旧 save 是否有兼容检查和 dry-run upgrade？

## 6. 对当前计划的修正建议

### Phase 3 前置门槛

进入 `TurnProposal` 薄层前，应确认：

- `external-projects-review.md` 已被专家用作 checklist。
- `intent_router_gold_set.yaml` 继续通过。
- `mcp_external_agent_transcripts.yaml` 继续通过。
- `phase-0-performance-baseline.md` 已记录本地基线。

### Phase 3：TurnProposal 薄层

必须包含：

- `proposal_id`
- `source`: resolver、AI、human_edit、import、maintenance
- `profile`: player_turn、maintenance、authoring
- `intent`
- `action`
- `action_options`
- `delta_draft`
- `provenance`
- `validation_state`
- `commit_state`
- `created_from_context_id` 或等价 trace id

不得包含：

- 已提交事实语义。
- projection 刷新逻辑。
- AI 直接执行权限。
- package/admin/maintenance 默认授权。

### Phase 4：ValidationPipeline

应借鉴 Temporal 的固定 stage 思路：

1. schema validation
2. capability/profile validation
3. resolver delta_contract
4. state audit
5. hidden/privacy audit
6. projection preflight
7. commit readiness

每个 stage 产出结构化 finding，支持 repeatable report。

### Phase 5：Commit/Projection

应借鉴 durable workflow 和 Godot load/rebuild 思路：

- commit 只写事实和 outbox。
- projection 只从事实源重建。
- projection 失败不回滚事实，但标记 dirty/error 并可 repair。
- commit result 记录哪些 projection clean、dirty、failed。

## 7. 明确不采用的外部模式

- 不采用 Ren'Py 式任意对象 pickle 存档；本引擎继续使用 schema/JSON/SQLite 可审计结构。
- 不采用把全部故事状态压成 Ink 单一 story JSON；本引擎有 campaign/save/projection 多层。
- 不采用浏览器历史式完整状态复制作为长期存档；长线 RPG 状态会膨胀，应走事件和结构化事实。
- 不引入 Temporal 或 LangGraph 作为运行时依赖；只借鉴 durable state、checkpoint、HITL 和 deterministic stage 思想。
- 不把 MCP tool description 或 AI prompt 当安全边界；真实边界必须在 runtime/profile/validation/test 中。

## 8. 总体判断

外部经验没有推翻当前方案，反而强化了三个判断：

1. No-AI path 是最低标准。成熟叙事引擎都不依赖语言模型维持状态正确性。
2. AI 和 MCP 必须被当作低信任外部调用者。工具权限、写入、持久化和隐藏信息不能靠 prompt 约束。
3. `TurnProposal` 是下一步正确方向，但它必须是可验证、可追踪、可丢弃的候选层，而不是新的事实源。

所以，后续可以继续进入 Phase 3，但每次实现都应带着本文件第 5 节的专家清单复核。
