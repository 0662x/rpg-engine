# 调查：Intent mode mismatch 与 MCP 调用失败

## Hand-off Brief

04:26 的 intent 故障由 Hermes 调用侧把“巡视一下我的基地”构造成与当前项目 contract 不一致的 `mode=query`，同时 live manifest 又没有暴露 deterministic router 中“巡视→routine”的 exact-term taxonomy；kernel 的 consensus fail-closed 符合 contract。该证据能确认 route contract mismatch，不能单独证明玩家主观上一定希望推进时间；manifest/player_turn 同 batch 是前一个请求的独立编排弱点，不是本次巡视事件的直接原因。14:20 的 MCP 故障与 intent 无关：Hermes MCP 客户端在 12:48 keepalive 失败后无法重建 stdio session，注销工具后请求未到达 RPG Engine。

## Case Info

| Field | Value |
| --- | --- |
| Ticket | N/A |
| Date opened | 2026-07-12 |
| Status | Concluded |
| System | macOS；RPG Engine main；截图显示 MCP/游戏会话调用 |
| Evidence sources | 两张用户截图；当前源码、测试、文档与版本历史 |

## Problem Statement

用户报告游戏调用链出现 bug：自然语言动作请求在 `player_turn` 中产生 external/internal intent mode mismatch，后续 MCP 工具调用又失败，希望确认问题的真实原因与所属层级。

## Evidence Inventory

| Source | Status | Notes |
| --- | --- | --- |
| `/var/folders/g3/vgyn86xd5rn7lpk338bj9pcw0000gn/T/codex-clipboard-8392efce-42db-46b5-96b4-0ba35e6d9368.png` | Available | 会话前半段；包含 `needs_confirmation`、clarification 与 fallback 过程 |
| `/var/folders/g3/vgyn86xd5rn7lpk338bj9pcw0000gn/T/codex-clipboard-27b33887-d057-4752-9064-e09a36198c57.png` | Available | external candidate/kernel 返回 JSON、后续 MCP 工具调用失败与诊断尝试 |
| 当前仓库源码与测试 | Available | 已完成 caller、rules、consensus/risk 与 MCP reconnect 状态机 trace |
| `../state.db` | Available | session `20260712_040918_37f6ea2c` 保存了原始 assistant tool call；message 9390/9395 含错误 external candidate，9419/9420 含工具不存在返回 |
| `../rp/logs/aigm-mcp-audit.jsonl` | Available | 精确记录 04:26 mismatch 请求/结果；14:20 无请求到达 kernel |
| `../logs/errors.log`、`../logs/mcp-stderr.log` | Available | 记录 12:48 keepalive 失败、连续 TaskGroup reconnect failure、parking 与 server 启动 marker |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --- | --- | --- | --- |
| 1 | 还原截图中每次 `player_turn` 的 exact request/response | High | Closed | SQLite raw message 与 MCP audit 已对齐 |
| 2 | 追踪 external/internal/rules 仲裁与 mode mismatch 分支 | High | Closed | 调用侧 query 与 rules routine 分歧；fail-closed 符合 contract |
| 3 | 追踪 MCP 工具调用失败的工具名、入口、配置与 transport | High | Closed | Hermes reconnect 持续失败后注销工具；未到达 kernel |
| 4 | 核对最近相关提交与回归测试 | Medium | Closed | Story 4.1 是 off-mode 修复，本事件运行于 consensus，非同一回归 |
| 5 | 展开 Hermes `ExceptionGroup` 的嵌套异常 | Medium | Deferred | 当前日志只保留摘要；需要客户端观测 patch 或同环境故障注入 |

## Timeline of Events

| Time | Event | Source | Confidence |
| --- | --- | --- | --- |
| 截图约 04:15–04:34 | 游戏会话进入 turn 000044；动作请求出现 external query / rules action mode mismatch 和 clarification | 截图 1–2、raw audit | Confirmed |
| 截图约 14:20–14:33 | 天气任务后尝试 MCP 调用，工具调用失败；随后执行本地配置/连通性诊断 | 截图 2 | Confirmed |
| 2026-07-12 12:48:34 | `aigm-kernel` keepalive 失败，Hermes 开始重连 | `../logs/errors.log:9668` | Confirmed |
| 12:48–14:20 | 每五分钟 self-probe；每轮 initialize 前后以 `TaskGroup (1 sub-exception)` 失败并 parking | `../logs/errors.log:9669` | Confirmed |

## Confirmed Findings

### Finding 1: 截图中的 mismatch 是 fail-closed 结果，不是事实写入成功

**Evidence:** 截图 2 的 kernel JSON 显示 `status="needs_confirmation"`、`action="act"`、`clarification`，并包含 warning `internal AI unavailable; external/rules mode mismatch`。

**Detail:** 该返回没有形成可提交动作；后续调用方通过 clarification/fallback 继续。现阶段不能把它直接等同于 kernel 写入 bug。

### Finding 2: warning 是当前源码的组合结果，不是未知旧文案

**Evidence:** audit 保存的完整 warning 为 `internal AI unavailable; external/rules mode mismatch`（`../rp/logs/aigm-mcp-audit.jsonl:6`）。前半来自 consensus internal unavailable policy（`rpg_engine/ai_intent/router.py:236`），后半来自 risk guard（`rpg_engine/ai_intent/risk.py:86`）。

**Detail:** exact-string 搜索不命中是因为返回层组合了两个 guard，并非错误来自仓库外或旧版本。

### Finding 3: external candidate 的确与当前 canonical route contract 不一致

**Evidence:** `../state.db` session `20260712_040918_37f6ea2c` message 9390 保存的 tool call 对原话“巡视一下我的基地”传入：`{"action":"","kind":"query","mode":"query","slots":{"query_kind":"scene"},...}`；message 9395 再次传入同类 candidate。schema 只要求 `action` 为 string，因此空串仍可通过结构校验。

**Detail:** canonical rules 明确把“巡视”列入 routine 词表（`rpg_engine/intent_router.py:67`）；gold fixture 也规定巡视领地为 `action/routine/ready`（`tests/fixtures/intent_router_gold_set.yaml:104`）。因此调用侧的 query 解释与当前项目 contract 冲突。自然语言“巡视一下我的基地”本身可能被人理解为查看或执行巡视；现有证据不能把项目 contract mismatch 进一步升级为已经证明的玩家主观意图误读。

### Finding 4: 调用侧 sequencing 是弱 contract，但不是“巡视”incident 的直接原因

**Evidence:** `../state.db` message 9383 的同一个 assistant message 确实预序列化 `intent_manifest` 与前一个“我现在在哪里”的 `player_turn`；但 manifest result 9384 已先返回，真正的“巡视”incident 是后续 user message 9389 与独立 player_turn 9390。

**Detail:** 同 batch 参数无法使用前一个 tool result，是独立的编排弱点；但把本次巡视误判直接归因于同 batch 已被反证。随后 assistant 加载旧 `engine-pitfalls` 并把 incident 错误归因为 craft classifier；background self-improvement 的 prompt/guard 允许未经 domain reproduction 的结论被固化，因此存在 diagnostic knowledge poisoning 风险，但 exact durable patch 缺少 old/new payload，只能作为 Deduced risk。

### Finding 5: MCP 工具在 Hermes 客户端被注销，请求未到达 RPG Engine

**Evidence:** `../state.db` message 9419 尝试 `mcp__aigm_kernel__player_turn`，message 9420 返回 `Tool ... does not exist`，当时 available tools 中没有 MCP 工具。对应时段 `../rp/logs/aigm-mcp-audit.jsonl` 没有任何调用。

**Detail:** Hermes 在 12:48 keepalive 失败后，连续三次重连均报 `unhandled errors in a TaskGroup (1 sub-exception)`，随后按状态机 parking 并 deregister tools（`../logs/errors.log:9668`；`../hermes-agent/tools/mcp_tool.py:2716`）。因此截图中的 unknown tool 是上游 registry 结果，不是 AIGM 拒绝或 tool rename。

### Finding 6: server command/config 本身可启动，失败属于 Hermes reconnect lifecycle

**Evidence:** 配置明确使用 Python 3.13、同一 repo editable install 与 stdio command（`../config.yaml:8`）；按 exact command 直接启动时 server 保持存活。故障前 server 连续处理 Ping 至 12:45（`../logs/mcp-stderr.log:8498`），12:48 后每次只有 start marker、没有 server traceback（`../logs/mcp-stderr.log:8514`）。gateway 重启后同一配置又能恢复。

**Detail:** 现有证据排除“命令无效、模块无法 import、kernel tool 不存在”。Hermes `_run_stdio` 每次重连会重新包装 watchdog、清理 orphan、创建 stdio client/ClientSession 并 initialize（`../hermes-agent/tools/mcp_tool.py:2007`）；但 logger 只输出顶层 `ExceptionGroup` 文本，嵌套异常丢失，无法再精确断言是 watchdog、orphan reaper、pipe teardown 还是 MCP SDK TaskGroup 内部失败。

## Deduced Conclusions

### Deduction 1: 截图包含两个彼此独立的问题

**Based on:** Finding 1、截图时间线。

**Reasoning:** intent mismatch 发生在游戏 `player_turn` 仲裁；数小时后的 MCP 工具失败发生在另一次任务和调用阶段，且截图没有证明两者共享同一异常或进程状态。

**Conclusion:** 两起故障确实独立：04:26 是 external candidate 与 canonical route contract 不一致，并叠加 live manifest taxonomy 缺口，触发 kernel 正常 fail-closed；14:20 是 Hermes MCP 客户端重连失败导致工具注销。prompt-only sequencing 是独立设计弱点，不是巡视事件的直接触发条件。

## Hypothesized Paths

### Hypothesis 1: 调用方生成了与 canonical route contract 不一致的 external candidate

**Status:** Confirmed

**Theory:** 对当前项目规定为 routine 的巡视文本，调用方传入了 `mode=query, action=""` 的 external candidate；rules 路径识别为 `action/routine`，kernel 因 mode 分歧正常 fail closed。

**Supporting indicators:** raw session 显示 external candidate 为 query，而原话是“巡视一下我的基地”；项目 prompt 要求每轮基于当前 manifest 和原始 `user_text` 生成 fresh candidate。

**Would confirm:** 原始 MCP request 显示 exact text 命中当前 canonical routine contract，但同一请求的 external candidate 为 query。

**Would refute:** 当前 canonical contract 或 exact request context 证明该输入应为 query，且 kernel rules 错误地产生 action route。

**Resolution:** raw tool call 已确认 query candidate；deterministic replay 复现同一 mismatch。

### Hypothesis 2: internal classifier unavailable 后的 rules fallback 对中文动作发生误分类

**Status:** Refuted

**Theory:** internal AI 不可用时，rules classifier 把应为 query/explore 的文本判成 craft，造成 mismatch。

**Supporting indicators:** 截图 warning 明确含 internal AI unavailable；但 exact 输入尚缺失。

**Would confirm:** 用截图中的 exact user_text 在当前 rules classifier 稳定复现 craft，而预期 contract 为 query/explore。

**Would refute:** rules classifier 对 exact 输入返回正确类别，分歧来自 external candidate。

**Resolution:** exact 输入稳定路由为 routine，不是 craft；截图中的 craft 说法来自 assistant 自行诊断，不是 kernel raw evidence。

### Hypothesis 3: MCP 工具调用失败是独立的 client/config/transport 问题

**Status:** Confirmed

**Theory:** 后续 MCP failure 与 intent mismatch 无直接因果，可能是工具名、profile、gateway 或 stdio/HTTP 配置不一致。

**Supporting indicators:** 截图中的 MCP 失败发生在不同时间和任务；随后的诊断集中于 MCP server/config/gateway。

**Would confirm:** 原始 MCP stderr/response 指向 unknown tool、profile restriction、connection 或 transport error。

**Would refute:** MCP response 明确由同一 intent mismatch 状态触发。

**Resolution:** 原始 client result 为 unknown tool；server audit 无请求；Hermes reconnect/parking 日志与工具注销状态机完全对齐。

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | --- | --- |
| Hermes reconnect 的 nested `ExceptionGroup` | 无法定位客户端内部精确失败语句 | 对 ExceptionGroup 使用 `logger.exception`/递归展开，并复现 keepalive reconnect |
| 截图时 Hermes 精确 commit | 影响具体 upstream commit 归因，不影响故障层级判断 | 从部署/安装元数据恢复；当前 checkout 只能证明该区域近期有多次 reconnect 修订 |

## Source Code Trace

| Element | Detail |
| --- | --- |
| Intent origin | Hermes caller 生成 `mode=query` candidate；RPG Engine `risk.py` 在 consensus/internal unavailable 下拒绝 mode mismatch |
| Intent trigger | `player_turn("巡视一下我的基地", external_intent_candidate=query)` |
| MCP origin | Hermes MCP client keepalive 后 stdio reconnect 连续失败，run loop parking 并 deregister tools |
| Related files | `rpg_engine/intent_router.py`、`rpg_engine/ai_intent/router.py`、`rpg_engine/ai_intent/risk.py`、`../hermes-agent/tools/mcp_tool.py` |

## Final Conclusion

**Confidence:** Intent High；MCP 故障层级 High；MCP 客户端内部精确语句 Medium/Unresolved

04:26 的根因不是 RPG Engine 把“巡视”分类成 craft。Hermes external caller 在 manifest 已可见的后续模型轮仍把当前项目 contract 规定为 `action/routine` 的文本构造成 `query`；同时 machine manifest 从 resolver keywords 导出，本身不包含 deterministic router 独有的“巡视/巡逻”词项。internal AI 不可用时，kernel 的 consensus fail-closed 行为正确。该结论描述的是项目 route contract，不替代对玩家真实意图的产品语义判断。

14:20 的根因与 intent 无关。Hermes MCP client 自 12:48 keepalive 失败后无法重建 stdio session，状态机随后注销 `aigm-kernel` 工具；所以模型看到的是“tool does not exist”，请求从未到达 RPG Engine。server command 可独立启动，同一配置在 gateway restart 后恢复，故障边界在 Hermes reconnect lifecycle。现有日志隐藏嵌套异常，因此不把根因过度收窄到某一个内部函数。

## Recommended Next Steps

### Fix direction

调查阶段不修改代码。后续修复按机制拆分：

1. **Route taxonomy/caller contract：** 先由 planning 选定唯一、版本化的 taxonomy 机器真源（可由 resolver/registry 承担，也可使用独立 taxonomy contract），确保 deterministic router、live manifest 和 internal prompt 同源表达“巡视/巡逻→routine”；调用层再强制 `intent_manifest → 下一模型轮 candidate preparation → player_turn`，删除 GM skill 中不适用于当前版本的“巡视→craft”pitfall，并加入 exact phrase 跨边界 contract test。
2. **MCP reconnect/observability：** 在 Hermes MCP client 展开记录 `BaseExceptionGroup` 的 nested traceback，并覆盖 keepalive failure → stdio teardown → initialize → tools re-register 的恢复测试；确认失败时的 orphan/watchdog/pipe 状态均可观测。
3. **Defense in depth：** 不应全局拒绝空 `action`，因为 query/unresolved contract 明确使用空字符串；如需加固，应做条件一致性校验（`mode=action` 必须是 registered action，`mode=query/unknown` 才允许空 action），但该项不修复本次 mode mismatch，不能替代前两项。

### Diagnostic

MCP 精确内部语句仍需一次带 nested traceback 的故障复现。最低诊断输出应包含 keepalive 原始 exception、stdio client `ExceptionGroup` 叶异常、child PID/PGID、watchdog exit status、initialize 阶段与 tool re-registration 结果；在得到这些信息前，不把修复武断限定为 orphan reaper、watchdog 或 MCP SDK 任一单点。

## Reproduction Plan

已在只读/temporary 边界完成 exact text 重放：rules 为 `routine/ready`；consensus + internal unavailable + external query 稳定得到 `clarify` 与 `external/rules mode mismatch`。相关定向测试 3 项通过：internal timeout fail-closed、off-mode external-primary、原始巡逻文本 P0 acceptance。

MCP 修复后的 verification plan：先建立可控 keepalive failure，再断言旧 session 完整 teardown、新 stdio server 完成 initialize、`aigm-kernel` tools 重新注册且一次 `player_turn` 可到达 audit；同时验证连续失败时工具只在真实不可用期间注销，self-probe 恢复后无需 gateway restart。

## Handoff

| 工作流 | 责任域 | 推荐 BMAD 路由 | 验收重点 |
| --- | --- | --- | --- |
| Caller sequencing/contract | Hermes external caller 与 RPG Engine prompt/tool contract | `[CS] Create Story` (`bmad-create-story:create`) | manifest 必须先完成；fresh candidate 与 canonical routine contract 一致 |
| MCP reconnect/observability | `hermes-agent/tools/mcp_tool.py` | 在 Hermes 仓库建立对应 tracked story；若无 sprint story，先用 `[QQ] Quick Dev` (`bmad-quick-dev`) | nested exception 可见；keepalive 后自动恢复并重新注册 tools |
| 跨项目排期/所有权调整 | RPG Engine 与 Hermes 两个仓库 | `[CC] Correct Course` (`bmad-correct-course`) | 明确两个独立 defect 的 owner、story 与发布顺序 |

**最高价值下一步：** `[CC] Correct Course`，因为已确认的修复跨越两个仓库和两个不同机制，直接塞进当前 RPG Engine backlog story 会混淆责任边界。完成 scope/owner 调整后，再分别创建并验证 tracked story。

## Side Findings

- 截图中的调用方已经使用 CLI fallback 绕过 MCP failure；这证明 fallback 可用，但不能证明 MCP 根因。

> 以下 Follow-up 保留调查演进和 refutation 记录；若阶段性措辞与文首 Hand-off Brief、Final Conclusion 或末尾 Review Correction 不一致，以后者为当前权威结论。

## Follow-up: 2026-07-12

### New Evidence

- SQLite raw session 补足了被 audit redaction 的 external candidate，并证明前一请求曾把 manifest/player_turn 预序列化在同一 batch；后续反证表明巡视 incident 本身不是该 batch。
- AIGM audit 补足了 exact text、运行模式、backend/model、warning 与时间戳。
- Hermes errors/mcp-stderr 补足了 keepalive、重连、parking、工具注销前因。

### Additional Findings

- Story 4.1 修复的是 `intent_ai=off` 的 external-primary 路径；现场配置为 `consensus`（`../config.yaml:31`），所以不是该修复回归。
- 第二次加入“只读查询”后出现 `unknown mode requires clarification`，说明人为把动作压成 query 并不能绕过 contract，反而继续触发正确的保守仲裁。

### Updated Hypotheses

- H1 Confirmed；H2 Refuted；H3 Confirmed。
- 新假设“MCP server 配置/模块坏掉”已被 exact command 独立存活测试 refute。

### Backlog Changes

- Outcome 2–4 路径全部关闭；只保留 Hermes nested ExceptionGroup 观测缺口，进入 Outcome 5 handoff 后由对应仓库处理。

### Updated Conclusion

两起调用 bug 不共享根因：intent 是 external candidate 与当前 canonical route contract 不一致并叠加 manifest taxonomy 缺口；MCP 是 Hermes client reconnect outage。RPG Engine 在两起事件中分别执行了正确的 fail-closed，或根本没有收到请求。

## Outcome 5 Finalization: 2026-07-12

- Case 状态已设为 `Concluded`；已确认根因或明确剩余观测缺口。
- Hand-off Brief、Final Conclusion、fix direction、diagnostic steps、reproduction/verification plan 与跨仓库 handoff 已完成。
- `workflow.on_complete` 为空，无额外 completion hook。

## Follow-up: 2026-07-12 #2

### New Evidence

- `../skills/gaming/aigm-kernel-v1-gm/references/engine-pitfalls.md:41` 当前把“巡视领地/巡视基地/巡逻→craft”记录为已知误分类。`state.db` message 9396 证明该内容已在 04:29:30 由 `skill_view` 返回；当前磁盘文件的 birth/mtime 却为 04:37:36，因此当前文件时间不能用于推断该知识最初何时产生或来自哪个版本。可以确认的只有：该 skill 在 04:26 初次 query candidate 之后、04:29 后续误诊之前被加载。
- 同一 skill 的 candidate contract 明确要求先调用 manifest（`../skills/gaming/aigm-kernel-v1-gm/references/external-intent-candidate.md:61`）。raw session 证明前一个“我现在在哪里”请求把 manifest/player_turn 放在同一个 assistant tool batch；巡视事件则是 manifest result 已可见后的独立 player_turn。
- Kernel manifest 提供每个 action 的 `keywords`、`semantic_labels` 与 `inference_priority`（`rpg_engine/intent_manifest.py:54`），但 routine resolver keywords 本身不含“巡视/巡逻”（`rpg_engine/actions/routine.py:257`）；这些词只存在于 `ROUTINE_INTENT_TERMS`（`rpg_engine/intent_router.py:67`）。因此当前 live manifest 无法完整表达 canonical deterministic taxonomy。
- Hermes background review prompt 把“non-trivial fix/workaround”视为任一即足以 patch skill 的信号，并鼓励主动 patch（`../hermes-agent/agent/background_review.py:180`）；现有 anti-pattern gate 只明确排除环境/瞬态/负面工具声明，没有要求 runtime classifier 诊断必须有 deterministic test 或 raw trace 才能固化（`../hermes-agent/agent/background_review.py:250`）。

### Updated Root Cause

第一个问题有三段因果链：machine manifest 与 deterministic taxonomy 不同构，external AI 在 manifest 已可见时仍生成与项目 contract 不一致的 query candidate，kernel 随后正常 fail closed；旧 skill 又诱发 craft 错误诊断。现有顺序证据证明了 skill load 与误诊的关系，但缺少 background patch 的完整 old/new payload，因此“self-improvement 强化了哪条 durable claim”属于强推断。修复必须收敛 taxonomy 真源、加强 consumer contract，并给 skill self-improvement 增加证据门。

### Concrete Fix Shape

1. 立即清除 `engine-pitfalls.md` 中“巡视→craft”的错误条目，明确记录 current project contract：`巡视/巡逻` 默认 `action/routine`；`看看周围/查看当前状态` 为 query；混合或真实语义不清时使用 unresolved/clarification。该映射是产品 route contract，不应被表述为对所有玩家自然语言主观意图的普遍事实。
2. GM skill 明文禁止在同一 tool-call batch 预生成依赖 manifest 的 candidate；candidate 必须在 manifest result 到达后的新模型轮生成，并消费完整 route hints。该措施只有在 manifest taxonomy 已先收敛后才足以避免当前问题。
3. Hermes background self-improvement 在写入 classifier/API/kernel 行为结论前，必须具备 raw trace 加 deterministic reproduction/test；否则只能记录为待验证 session note，不能写成“已知 bug”。
4. Consumer contract tests 覆盖 exact transcript、tool ordering 与 candidate JSON；provider regression 继续断言 rules 对“巡视”输出 `routine/ready`，mismatch 时不写 Save。

## Follow-up: 2026-07-12 #3

### Corrections from Full-chain Outcome 3

- Refuted：巡视 incident 不是 manifest/player_turn 同 batch 直接造成。该 batch 属于前一个“我现在在哪里”请求；巡视是 manifest result 已可见后的独立 player_turn。
- Refuted：完整消费 live manifest keywords 即可得到“巡视→routine”。当前 routine manifest keywords 不含“巡视/巡逻”，deterministic router 的独立词表才包含。
- Confirmed：caller 生成了 query candidate；它与当前 canonical route contract 不一致。现有 telemetry 无法证明它忽略了哪个具体 manifest 字段，也不能单独确定玩家主观意图。
- Confirmed：旧 `engine-pitfalls` 在初次 query candidate 之后才被加载，因此没有造成最初误路由；它造成后续 craft 错误归因。Deduced：background self-improvement 机制可能再固化该错误知识，但 exact patch payload 缺失。
- Confirmed：正确修复顺序应是 taxonomy single source → live manifest parity → next-model-turn consumer sequencing → cross-boundary exact transcript test。

## Review Correction: 2026-07-13

- 已纠正使用当前文件 birth/mtime 推断历史 skill 产生时间的无效证据；历史来源仍属于 Missing Evidence。
- 已将“caller 曲解玩家意图”收窄为“external candidate 与当前 canonical route contract 不一致”。
- 已明确同 batch 只发生在前一个 query，请勿把 prompt-only sequencing 当作巡视 incident 的直接原因。
- taxonomy 唯一 owner 与玩家自然语言默认语义属于后续 planning/AC 选择；本调查只确认 drift 与当前 contract。
- background self-improvement 的 exact durable patch 缺少完整 payload，只保留为 Deduced risk。
