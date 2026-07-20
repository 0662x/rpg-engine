# MCP 合同

文档状态：**CURRENT：BMAD canonical MCP contract authority**

本文件是 RPG Engine / AIGM Kernel 当前 MCP adapter、MCP profile、工具暴露、AI helper
边界和玩家安全入口的 canonical 文档。旧 [`specs/mcp-adapter.md`](specs/mcp-adapter.md)
现在是 compatibility stub，原文位于
[`archive/pre-bmad-docs-2026-07-03/specs/mcp-adapter.md`](archive/pre-bmad-docs-2026-07-03/specs/mcp-adapter.md)；
日常开发应先读本文件，并以当前 `rpg_engine/mcp_adapter.py`、`SaveManager`、`GMRuntime`、
[`ai-intent-chain.md`](ai-intent-chain.md) 和
[`cli-contracts.md`](cli-contracts.md) 为准。

## 核心结论

MCP adapter 是薄适配层，不是后端、插件系统、模型代理或另一套 CLI handler。

```text
AI client
  -> MCP stdio server: aigm mcp serve
  -> AIGMMCPAdapter
  -> SaveManager / GMRuntime / validators
  -> Save Package
```

普通 AI client 的玩家自然语言主路径仍是：

```text
player_turn(user_text, optional external_intent_candidate)
  -> query / clarification / blocked / pending action
  -> player_confirm(session_id)
  -> validated commit
```

硬边界：

- MCP 不能绕过 `player_turn -> player_confirm` 普通玩家提交门。
- `player` profile 只注册 player-safe 工具；低层 preview、validate、commit 和 preflight 工具不注册。
- `developer`、`trusted_gm`、`maintenance`、`admin` profile 才注册低层工具。
- `developer` profile 可以使用低层工具，但 hidden / GM / maintenance 视图读取仍只给
  `trusted_gm`、`maintenance`、`admin`。
- `external_intent_candidate` 是 low-trust 候选输入，不是确认、approval、hidden access 或保存授权。
- `intent_manifest` 当前发布 manifest v4、action taxonomy v1 projection/digest、resolver-owned slot/group
  projection（含 group cardinality/binding rule）、完整 manifest digest 与 safety vocabulary v1 identity。External candidate 可携带
  optional all-or-nothing contract；显式 mismatch 必须 refresh + regenerate，unknown safety 必须 fail closed。
- Internal intent AI enabled 时 external/internal 保持既有 arbitration；显式 `off` 且 external candidate
  通过 schema、registry、safety、query/binding 检查时，它以 `external_primary` 成为 route proposal，
  rules 只留诊断；显式 `off` 且无 external 时保持 deterministic fallback。
- MCP path 必须在 configured root 下解析；campaign/save/starter 默认值和工具参数都不能是绝对路径或包含 `..`。
- `commit_turn` 是 trusted low-level 写入入口，必须提交 validated and accepted TurnProposal delta；
  MCP 不暴露 no-backup 写入。
- MCP audit 是证据和排障日志，不是事实源。

## Adapter 职责

`rpg_engine.mcp_adapter.AIGMMCPAdapter` 只做：

- 把 MCP 工具参数转为 `SaveManager`、`GMRuntime`、campaign validation 和 save inspection 调用。
- 根据 MCP profile 注册工具，并在 adapter method 层再次拒绝 profile/surface category mismatch。
- 校验 configured root 下的相对路径。
- 校验 player profile 的 hidden view、maintenance mode 和 per-call AI override 边界。
- 每次从 `SaveManager` canonical persisted session 检查 pending clarification，防止 adapter restart 或低层工具跳过澄清。
- 写结构化 audit record。

它不做：

- 不 import `rpg_engine.cli` handler。
- 不执行 package upgrade、migration apply、projection repair 或 plugin loading。
- 不读取任意本地文件。
- 不接收 delta 文件路径；低层 `validate_delta` 和 `commit_turn` 接收 JSON object。
- 不作为模型调用代理。
- 不调度长期后台任务。

MCP audit record 是排障和合规证据，不是事实源或权限源。记录必须包含稳定的 tool、surface
category、profile/tool identity、status、duration、sanitized request summary 和 summarized result。
当请求包含 platform/session/message identity 时，audit 只能写入 platform、message id 和 hashed
session key；不得写 raw session key、raw delta/proposal internals、hidden/private reasoning 或
未脱敏 AI helper payload。Audit 写入失败必须被吞掉并作为 warning 输出，不能改变 tool result、
MCP profile gate、hidden read gate、preflight gate 或 commit authority。

## 启动和配置

MCP 由 CLI 启动：

```bash
aigm mcp serve \
  --root /path/to/workspace \
  --default-campaign campaigns/minimal \
  --default-save saves/run \
  --default-starter-save starters/minimal \
  --registry-active
```

合同：

- `--root` 是 MCP 可访问 workspace 的唯一根。
- `--default-campaign`、`--default-save`、`--default-starter-save` 必须是 root 下相对路径。
- `--registry-active` 允许省略 save 时解析 workspace active save；registry 仍不是游戏事实源。
- `--mcp-profile` 默认是 `player`。非 player profile 必须显式配置。
- `--ai-profile`、`--semantic-*`、`--intent-*`、`--state-audit-*`、`--archivist-*`
  只配置 helper 默认值，不改变 MCP profile 权限。
- 当前 MCP transport 是 `stdio`。

生成 AI client 配置：

```bash
aigm mcp print-config /path/to/workspace \
  --default-campaign campaigns/minimal \
  --default-save saves/run \
  --default-starter-save starters/minimal \
  --registry-active
```

`print-config` 默认 server name 是 `aigm-kernel`，默认 command 是 `aigm`。非 player profile 会把
`--mcp-profile <profile>` 写入生成的 args。

## Profile 合同

| Profile | 工具暴露 | 典型用途 |
| --- | --- | --- |
| `player` | 只注册 player-safe tools。 | 普通 AI client、聊天 UI、玩家自然语言。 |
| `developer` | 注册 player-safe + low-level tools。 | 开发调试、测试、低层 runtime 验证。 |
| `trusted_gm` | 注册 low-level tools，并允许 hidden / GM views。 | 可信 GM 操作和受控诊断。 |
| `maintenance` | 注册 low-level tools，并允许 hidden / maintenance views。 | 维护、迁移前诊断、内容运营。 |
| `admin` | 注册 low-level tools，并允许 hidden / maintenance views。 | 管理员级维护。 |

权限细节：

- player profile 不能注册或调用 `player_query`、`player_act`、`start_turn`、`intent_preflight`、
  `query`、`preview_from_text`、`preview_action`、`validate_delta` 或 `commit_turn`；如果这些低层
  adapter method 被直接调用，也必须返回 profile/surface category mismatch。
- `player` profile 不能使用 hidden view、maintenance mode 或 per-call semantic/intent AI override。
- `developer` profile 可以使用低层工具，但 `query(view="gm")` 或 `query(view="maintenance")`
  仍会被 hidden-read gate 拒绝。
- `trusted_gm`、`maintenance`、`admin` profile 可以读取 GM / maintenance view；调用方仍必须遵守
  hidden-content policy。
- 低层 profile 可以传 per-call AI helper override，但 override 仍只是 helper 配置，不是提交权限。

## 工具清单

默认 `player` profile 注册：

```text
workspace_inspect
campaign_list
save_list
save_current
save_create
save_switch
start_or_continue
intent_manifest
player_turn
player_cancel
player_confirm
campaign_validate
save_inspect
health
```

低层 profile 额外注册：

```text
player_query
player_act
start_turn
intent_preflight
query
preview_from_text
preview_action
validate_delta
commit_turn
```

当前 MCP 不暴露：

- `repair`
- `plugin`
- package install / upgrade / reconcile
- migration apply
- projection repair
- arbitrary file read/write
- model proxy

`rpg_engine.surface_inventory.MCP_SURFACE_INVENTORY` 是 MCP 工具暴露的可测试权限清单。每个工具必须声明
canonical taxonomy、write authority、intended caller 和 forbidden bypasses；默认 player profile 的
工具必须全部是 player-safe，低层工具必须通过 MCP profile gate 留在 developer / trusted / maintenance /
admin profiles。

## Player-Safe 工具合同

| 工具 | 合同 |
| --- | --- |
| `workspace_inspect` | 读取 workspace registry 摘要；不写 gameplay facts。 |
| `campaign_list` | 列出注册 campaign；可 refresh registry；不写 gameplay facts。 |
| `save_list` | 列出注册 saves；可按 campaign 过滤；不写 gameplay facts。 |
| `save_current` | 返回 active save；不 refresh 时 summary 是 registry cache，并通过 `current_save_authority` 标明非权威。 |
| `save_create` | 创建 Save Package；可以 activate，但不能推进剧情。 |
| `save_switch` | 切换 active save；不改 save 内事实。 |
| `start_or_continue` | 继续或创建 onboarding context；gameplay facts 仍要走 `player_turn/player_confirm`。 |
| `intent_manifest` | 只读 manifest v4 action/query/slot/taxonomy/safety/version contract；不是玩法入口或授权。 |
| `player_turn` | 标准自然语言入口；返回 query、clarification、blocked 或 pending action。 |
| `player_cancel` | 用 exact `expected_pending_id` 取消 action 或 clarification；不写 gameplay facts。 |
| `player_confirm` | 用 `player_turn` 返回的 `session_id` 确认并保存 pending action。 |
| `campaign_validate` | 只读校验 configured campaign package。 |
| `save_inspect` | 只读检查 configured save package；结果包含 Save fact authority `authority_contract` 和 projection/outbox evidence `projection_health`，其中 outbox evidence 包含 `ok`/`status`、schema/availability errors、counts 和非 `done` work rows。 |
| `health` | 只读 runtime health check；不 repair。 |

`player_turn` 可以接收：

- `user_text`
- `external_intent_candidate`
- passive preflight identity：`preflight_id`、`message_id`、`platform`、`session_key`、
  `source_user_text_hash`、`preflight_pending_wait_ms`
- pending lifecycle：`actor_id`、`expected_pending_id`、`clarification_id`

`player_turn` 不能接收：

- delta / proposal 注入
- hidden view
- per-call AI override
- player confirmation
- commit instruction

结果要求：

- Query result：`ready_to_confirm=false`，不保存。
- Clarification / blocked：客户端必须先问玩家或说明阻断原因。
- Pending action：返回 `ready_to_confirm=true` 和 `session_id`，但不暴露 `delta_draft` 或完整
  `turn_proposal`。
- Confirm：只有玩家明确确认后，客户端才调用 `player_confirm(session_id)`；pending action 过期、
  active save 不匹配、session id 不匹配或平台 session/actor identity 不匹配时必须拒绝保存。
- Confirm result：MCP 原样透传 Kernel 的 `write_status=committed|already_confirmed`、
  `idempotent_replay`、`saved` 与 owner-validated bounded `confirmation_session_hash`。该 hash 仅供同一
  platform completion generation correlation，不是确认或 commit authority。合法 replay 的
  `ok=true`、`saved=false`；client 必须避免重复叙事和
  fresh-only 外围动作。Adapter 不读取 workspace receipt、不重算 command hash，也不拥有 claim authority。

## Low-Level 工具合同

| 工具 | 合同 |
| --- | --- |
| `player_query` | 结构化兼容查询；普通自然语言仍应走 `player_turn`。 |
| `player_act` | 兼容 wrapper；当前只在低层 profile 注册，新玩法应使用 `player_turn`。 |
| `intent_preflight` | 预计算 advisory internal intent review；不 preview、不写 delta、不提交事实。 |
| `start_turn` | 构建上下文并分类输入；如果返回 clarification，必须先问玩家。 |
| `query` | 低层只读 query；hidden views 受 profile gate 限制。 |
| `preview_from_text` | 低层自然语言 preview primitive；普通 player profile 不注册。 |
| `preview_action` | 已选择 action 的低层 preview；不能保存。 |
| `validate_delta` | 校验 JSON delta object；不能保存。 |
| `commit_turn` | 提交 validated and accepted TurnProposal delta；写入前仍经 runtime guards。 |

低层链路：

```text
start_turn / preview_from_text
  -> clarification? ask player and re-run
  -> preview_action or preview_from_text ready_to_save
  -> validate_delta
  -> player / GM approval
  -> commit_turn(delta, turn_proposal)
```

低层工具不得把以下结果当作可提交：

- `ready_to_save=false`
- `needs_confirmation`
- `clarify`
- `blocked`
- `internal_error`
- stale preview
- missing or hand-written minimal `turn_proposal`

## Path Boundary

MCP config 和工具参数中的 `campaign`、`save`、`starter_save` 必须满足：

- 相对 `--root`。
- 不能是绝对路径。
- 不能包含 `..`。
- 解析后必须仍在 root 下。

省略规则：

- `campaign` 省略时使用 `default_campaign`。
- `save` 省略时，如果 `registry_active=true`，优先解析 active save。
- 否则 `save` 省略时使用 `default_save`。
- 没有可解析默认值时返回结构化错误。

MCP 不从工具参数读取任意 delta 文件。`validate_delta` 和 `commit_turn` 的 `delta` 必须是 JSON object。

## AI Helper 和 External Candidate

MCP 的 AI 配置分两层：

- Server config：`--ai-profile` 和各类 helper 默认值。
- Per-call override：低层工具参数中的 semantic / intent / state-audit / archivist override。

合同：

- `player` profile 可以通过 server config 使用标准 `player_turn` 的 internal intent helper，但不能传
  per-call AI override。
- `external_intent_candidate` 只在允许的入口作为 low-trust input。它不能表达确认、approval、hidden
  access、delta injection 或保存授权。
- Candidate contract match 只产生 bounded validation evidence，不提升 route/hidden/confirmation/proposal/
  validation/commit authority。整体省略 contract 仅在 manifest 明示的 `legacy_unversioned_allowed=true`
  compatibility window 内继续；partial contract、mismatch 或 unknown safety 均不得 fallback 到 rules。
- Typed external contract error 只由 adapter 的统一 error boundary 映射为固定、脱敏的 `errors + error_details`：
  unknown 使用 `UNKNOWN_INTENT_SAFETY_FLAG` / `regenerate_candidate`；mismatch 使用
  `INTENT_CONTRACT_VERSION_MISMATCH` / `refresh_manifest_and_regenerate_candidate`。Audit 不记录 raw flag、
  candidate、slots、reason、player text、session key 或 provider body。
- `external_primary` 只是 mode-gated route proposal source，不是事实、玩家确认、proposal approval 或
  commit authority；非法候选必须 block/clarify，不能静默换成 rules 的另一意图。
- Internal AI 是 visible-external independent review：可以看见 external candidate，但必须基于玩家原文和
  player-visible context 复核。
- Server `intent_timeout` 是 helper operation 的 hard total budget，默认候选约 15 秒；约 8 秒 soft
  wait 只记录 latency evidence/触发安全降级。Primary/fallback 共享预算，late result 不得进入 route、
  pending 或 commit。
- Internal AI enabled 时 timeout/unavailable 仍保持 enabled mode 并走 risk-aware fallback、clarify
  或 block；不得转成显式 `off` 或无条件采用 external candidate。
- `player_act` 兼容入口不接收 `external_intent_candidate`。
- 空字符串和数值 `0` 的 per-call AI override 视为未提供；passive preflight identity 不算 AI override。

## Preflight 合同

`intent_preflight` 只在低层 profile 注册。它写 advisory cache，不写 gameplay facts。

两种 identity profile：

- `candidate_bound`：preflight 时已有 external candidate，消费时必须匹配 preflight id、玩家文本、
  candidate、save/base turn、context identity 和 helper 配置。
- `message_only`：host/sidecar 后台只按平台消息身份预热；正式调用可用
  `platform/session_key/message_id/source_user_text_hash` 查找唯一记录。

消费规则：

- `player_turn` 可以消费 passive preflight identity。
- `player_act` 兼容路径可以消费 passive message-only preflight。
- `start_turn` 和 `preview_from_text` 低层工具可以消费 preflight。
- Cache hit 仍必须进入 arbiter、binder、resolver、validation 和 commit guard。
- 过期、已消费、身份不匹配、schema revalidation 失败、pending timeout 或 late-ready 的 cache 不能成为 proposal
  provenance。
- Pending clarification 存在时，`intent_preflight` 会被拒绝，不能预热跨过未回答的玩家澄清。

## Clarification Guard

MCP adapter 不拥有进程内 clarification truth。`SaveManager` 在 owner lock 内持久化唯一 canonical
action/clarification；每个 low-level gate 都重新读取 owner state，可能发布 clarification 的工具还会冻结
Save binding 与 pending generation 并在 Runtime 后执行 CAS，所以 adapter restart 后仍观察相同 id、origin、
expiry 和 terminal outcome。

规则：

- 注册 Save workspace 的 `start_turn` 或 `preview_from_text` 返回 clarification 后，由 SaveManager owner
  记录 `clarification_id`；legacy standalone low-level Save 只返回 preview，不获得普通 player lifecycle authority。
- 两个 low-level 入口均薄转发可选 `actor_id`；与 `platform/session_key` 一起提供时，owner snapshot 与
  clarification 只保存 actor hash，同 actor 才能继续或取消，cross-actor 必须 conflict 且不得泄露 token。
- 同一 save 上，`preview_action`、`validate_delta`、`commit_turn` 和 `intent_preflight` 会被拒绝，
  直到 clarification 被新输入处理。
- 后续 low-level preview 不能结束 canonical clarification；必须回到 `player_turn`，同时提交匹配的
  `expected_pending_id` / `clarification_id` 和 fresh 玩家回答，或调用 `player_cancel`。
- Fresh re-preview 后，旧 preview 不能直接套用 choice 或继续 commit。

RPG Engine MCP adapter 只发布并校验 contract，不实现 Hermes consumer lifecycle。Hermes 应读取
`intent_manifest`、缓存当前 identity、为每个 fresh candidate 填充 contract，并在 mismatch 后刷新再生成；
reconnect、next-model-turn barrier 和跨仓 E2E 仍属于 Hermes 自身工作。

MCP `intent_manifest` 只是 `build_intent_manifest()` 的 thin wrapper，不自行拼装 taxonomy 或 slot metadata。
Per-action slots/groups 由 active `ActionResolverRegistry` 的 resolved slot contract 投影；metadata 变化旋转完整
manifest digest，custom/falsey registry 不得回退 default contract。Consumer 必须以
`action_taxonomy.actions[].terms/semantic_labels/inference_priority` 为当前 lexical contract；taxonomy 内容改变会
旋转 taxonomy 与 manifest digest，绑定旧 identity 的 candidate 必须刷新 manifest 后整体重新生成。

普通 `player_turn` 路径还会通过 SaveManager 的 pending action / pending clarification 规则避免确认到旧预演。

## Hermes stdio provider compatibility fixture

RPG Engine 为跨仓 Hermes compatibility CI 提供一个 test-owned、真实 stdio 的稳定 provider 入口：

- launcher/helper：`tests/compatibility/hermes_stdio_provider.py`
- scripted-model contract：`tests/fixtures/hermes_stdio_compatibility.yaml`
- 本仓 wire oracle：`tests/test_hermes_stdio_compatibility.py`

使用方必须检出 RPG Engine 仓库并从仓库根运行。`prepare_provider_fixture(empty_temp_root)` 会复制 minimal
Campaign、在该 temporary workspace 的 registry 中建立 active Save，并返回固定调用现有
`python -m rpg_engine mcp serve` 的 player-profile launcher；它不新增 production API 或第二套业务规则。
`stdio_server_parameters(fixture)` 只把该启动描述转为官方 MCP Python SDK 的
`StdioServerParameters`。subprocess cwd固定为temporary root内不含dotenv的隔离目录，仓库通过`PYTHONPATH`加载；root
内放置的poison `.env`不得被打开。所有 AI helper 显式为 `off`，test-owned `sitecustomize` guard会以PID-bearing ready
sentinel证明已加载，拒绝/记录provider进程通过公开`socket`、`socket._socket`或新import/reload的`_socket`/`SocketType`
发起的DNS、AF_INET/AF_INET6连接与connectionless I/O，并通过builtin/io/`os.open`拒绝记录`.env`读取；AF_UNIX本地
self-pipe仍可供asyncio teardown使用。该oracle覆盖CPython socket/DNS surface与实际provider路径，不承诺OS级
syscall/FFI sandbox。运行不需要网络、
`.env`内容或 API key，并以`PYTHONNOUSERSITE=1`禁用宿主user-site与`usercustomize.py`。

YAML contract `schema_version=1` / `fixture_id=rpg-engine-hermes-stdio-v1` 固定以下可执行顺序：

```text
manifest_initial
-> stale_candidate_rejected
-> manifest_refreshed
-> player_turn_ready
-> explicit_player_confirmation
-> wrong_session_rejected
-> player_confirm_committed
-> player_confirm_replayed
-> safe_audit
```

每个step都以typed `arguments`声明调用参数，并以bounded `expect`按JSON type和值锁定对应hook的
scalar/enum/hash/presence值（`0/1`不能冒充boolean，空白不能冒充nonempty）；
`{$ref: capture.path}`只能引用更早step的非null capture，缺失路径立即fail closed，
`{$candidate: {generation, manifest, overrides}}`从引用的完整manifest生成新candidate。`stale` 与 `refreshed` 是两个
内容和类型均由schema v1固定的完整、独立 candidate generation；refresh 必须从第二次 live manifest 的四字段identity
整体重建 candidate，不能
原地 patch 旧 object、以override替换canonical candidate字段或回退 legacy unversioned candidate。duplicate YAML key、
top-level、step arguments/expectation shape、hook ID和hook fields均按`schema_version=1` fail closed；YAML `hooks` 只投影
allowlisted scalar/enum/presence字段，timestamp、Save ID、raw pending
session ID、candidate payload和hidden内容不进入跨仓 hook。玩家确认是单独的 `actor=player` step，其typed reference
再传给两个confirm step；wrong-session也是独立typed step且不能消耗pending。scripted model不能生成确认authority。

当前 MCP `player_confirm` 工具只接收 `session_id`。因此兼容脚本只在必定于pending前失败的stale请求放置
platform/session-key hash canary；合法 `player_turn` 使用默认MCP player flow，再由独立玩家步骤把返回的
`session_id`交给confirm。fixture不替Hermes实现tool registration、next-model-turn barrier、reconnect或combined
release gate；这些生命周期及H1-H4状态全部由Hermes CI持有，不写入RPG Engine sprint。

任何可写验证都必须使用新的empty temporary root。source Campaign、formal current Campaign/Save、正式workspace
registry、其SQLite/player data按存在性做前后fingerprint；temporary root不得与它们samefile或形成父子路径别名。
source Campaign始终并入保护集合，caller提供额外保护路径不能替换默认边界；空白formal-path环境变量按未配置处理，
protected tree内symlink会fail closed。
stale、wrong-session、confirm、replay及teardown都只能改变temporary workspace。确认前、失败与replay使用全表logical
SQLite digest（含完整`sqlite_master`及authority PRAGMA）而非只看turn/event count；异常teardown用ready PID与公开SDK
lifecycle证明child已退出、只出现预期cancellation且正式数据后置指纹仍执行。PID reuse/未来派生进程组属于Hermes
client lifecycle defer；本fixture不依赖MCP SDK private process handle。

## Commit 合同

`commit_turn` 是低层写入工具，只在 low-level profile 注册。

要求：

- `delta` 必须是 JSON object。
- `turn_proposal` 应来自同一 preview 返回的完整 object。
- `delta` 和 `turn_proposal` 必须能通过 runtime validation 和 state audit guard。
- 调用前必须有玩家或可信 GM approval。
- MCP commit 总是启用 backup。
- MCP 不暴露 `--no-backup`。
- 默认 State Auditor guard 可能阻断高风险或不一致 delta。
- Archivist suggestion 只是 post-commit advisory/proposal 机制，不是事实源。

禁止：

- 直接提交 raw AI 文本。
- 手写最小 `turn_proposal` 替代 preview 返回值。
- 用 external candidate 当 proposal approval。
- 在 pending clarification 未回答时 commit。
- 在 player profile 中 commit。

## Audit 合同

默认 audit log：

```text
<root>/logs/aigm-mcp-audit.jsonl
```

每条记录包含：

- `created_at`
- `server`
- `tool`
- `duration_ms`
- `status`
- sanitized `request`
- summarized `result`

安全边界：

- `session_key` 会以 hash 摘要记录。
- `player_confirm` 的 pending confirmation `session_id` 同样只记录 hash摘要；raw capability token不得进入audit。
- 长文本和深层结构会截断。
- denied low-level player-profile calls 的 audit request 会摘要化 raw `delta`、`turn_proposal` /
  proposal payload，并清洗 private reasoning / hidden-fact keys。
- query / markdown 结果只记录 preview 摘要。
- audit 写入失败不能中断 MCP 调用。
- audit 是调用证据，不是 SQLite facts、projection 或 player confirmation。

MCP 的 campaign/save/default path 参数必须保持 configured root 下的相对路径；绝对路径、`..` 和
反斜杠都必须被拒绝，失败时不能写 registry、pending state 或 Save SQLite。

## 推荐流程

默认 `player` profile：

1. 用 `workspace_inspect`、`save_current`、`save_inspect` 或 `health` 确认 workspace/save 可用。
2. 玩家自然语言进入 `player_turn`。
3. 如外部 AI 生成候选，只作为 `external_intent_candidate` 传入。
4. 如果返回 query，直接使用 kernel 玩家可见结果回答。
5. 如果返回 clarification 或 blocked，先问玩家或说明阻断。
6. 只有返回 `ready_to_confirm=true` 且玩家确认时，调用 `player_confirm(session_id)`。

低层 profile：

1. 用 `save_inspect` 或 `health` 确认 save 可用。
2. 用 `start_turn` 或 `preview_from_text` 建立本轮上下文和 preview。
3. clarification 必须先问玩家，并重新运行 fresh preview。
4. 低层 `preview_action` 只用于 action 已由合同明确选择的情况。
5. `validate_delta` 通过后，拿到玩家或可信 GM approval。
6. 调 `commit_turn(delta, turn_proposal)`。
7. commit 后用 `query`、`save_inspect` 或 `health` 读取新状态。

## 开发检查清单

改 MCP adapter、MCP 文档或 MCP-facing runtime 行为时，至少检查：

- 新工具是否应该进入 player-safe list，还是只属于 low-level profiles？
- `player` profile 是否仍不能注册 preview/validate/commit/preflight low-level tools？
- `developer`、`trusted_gm`、`maintenance`、`admin` 的 hidden-read 和 low-level 权限是否分开？
- path 参数是否仍拒绝 absolute path 和 `..`？
- `player_turn` 是否仍隐藏 `delta_draft` 和 `turn_proposal`？
- `player_confirm` 是否仍需要 `session_id`？
- external candidate 是否仍只是 low-trust input？
- per-call AI override 是否仍不能进入 default player profile？
- pending clarification 是否仍能阻断 stale low-level tools？
- `commit_turn` 是否仍启用 backup 和 state audit guard？
- audit 是否仍只记录 sanitized request 和 summarized result？

推荐 focused gate：

```bash
python3 -m pytest -q tests/test_mcp_adapter.py tests/test_save_manager.py tests/test_ai_intent.py tests/test_preflight_cache.py
```

如果改到 CLI 启动参数或 platform prewarm 消费链路，再追加：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py
```
