# CLI 合同

文档状态：**CURRENT：BMAD canonical CLI contract authority**

本文件是 RPG Engine / AIGM Kernel 当前命令行入口、玩家可见流程、低层运行时工具和维护命令的
canonical 文档。旧 `docs/specs/cli.md` 现在是 compatibility stub，原文位于
[`archive/pre-bmad-docs-2026-07-03/specs/cli.md`](archive/pre-bmad-docs-2026-07-03/specs/cli.md)；
日常开发应先读本文件，并以当前 `rpg_engine/cli_v1.py`、`rpg_engine/cli.py`、`SaveManager`、
`GMRuntime` 和 MCP/profile 代码事实为准。

## 核心结论

CLI 是 kernel 的参考入口，不是另一套业务逻辑。

```text
aigm / rpg_engine / python3 -m rpg_engine
  -> V1 public groups: campaign, save, player, play, platform, mcp, eval
  -> legacy/admin groups: init, query, context, package, proposal, turn, ...
```

普通玩家自然语言主路径是：

```text
player start/new/switch
  -> player turn
  -> query / clarification / blocked / pending action
  -> player confirm --session-id
  -> validated commit
```

硬边界：

- `player turn` 可以返回 query、clarification、blocked 或写 pending action，但不能提交游戏事实。
- `player confirm --session-id` 是普通玩家 CLI 路径唯一的提交门。
- `play *` 是低层 runtime / developer / trusted-gm 工具，不是普通玩家 UI 的默认入口。
- `platform *` 是平台消息 sidecar 包装层，必须继续走 SaveManager 的 start、act/turn 和 confirm 边界。
- `mcp serve` 只启动 MCP adapter；MCP 权限由 profile gate 决定，不由 CLI flag 绕过。
- `save patch`、legacy/admin 命令和 package/projection/migration 命令都是维护能力，不能伪装成玩家行动。
- CLI 不应直接写 SQLite 事实表；事实写入必须经过 validation、proposal/commit 和 projection/outbox 机制。

## 入口和输出合同

`pyproject.toml` 暴露两个安装脚本：

- `aigm`
- `rpg_engine`

它们和 `python3 -m rpg_engine` 进入同一个 `rpg_engine.cli:main` 命令树。文档、测试和示例可以用
`python3 -m rpg_engine` 保持本地源码可执行，也可以用安装后的 `aigm` 验证 installed CLI。

V1 命令统一支持：

```bash
--format markdown|json
```

默认输出是 markdown / human-readable 文本。`--format json` 用于自动化、测试、MCP-adjacent
调试和客户端集成。失败命令必须返回非零退出码；JSON 失败结果应保留 `ok=false` 或 `errors`
等结构化错误字段。

Legacy/admin 命令来自 `rpg_engine/cli.py`，参数和输出格式不完全统一。新增面向玩家或平台的行为时，
优先扩展 V1 public groups；只有维护、迁移、调试和 package 运维能力才应放在 legacy/admin surface。

## V1 命令组

| 组 | 面向对象 | 合同 |
| --- | --- | --- |
| `campaign` | 作者 / CI | 创建、校验、解释和诊断 Campaign Package；不能保存玩家进度。 |
| `save` | 维护 / package flow | 初始化、检查、导入导出和安全 patch Save Package；不能绕过玩家 action resolution。 |
| `player` | 普通玩家入口 | 管理 workspace saves，执行自然语言 turn，确认 pending action。 |
| `play` | developer / trusted-gm | 低层 runtime query、preview、validate、commit 和 health 工具。 |
| `platform` | 平台 sidecar | 归一化平台消息、绑定平台 session、prewarm 和转发玩家入口。 |
| `mcp` | AI client integration | 打印 MCP client config 或启动 adapter；具体工具权限由 MCP profile 决定。 |
| `eval` | QA / regression | 运行 deterministic intent 和 MCP transcript eval，不写 gameplay facts。 |

这些 V1 command group 也登记在 `rpg_engine.surface_inventory.CLI_V1_COMMAND_SURFACE_INVENTORY`。
每个 group 必须声明 canonical taxonomy、write authority、authority gate 和 forbidden bypasses；如果
某个 group 通过 subcommand 或 profile 改变权限，必须在 inventory 里写明 gate。
Top-level help 文案也必须暴露同一权限边界：`play` 是 “developer/trusted low-level runtime commands”，
`player` 是 “player-safe save registry and turn commands”，`platform` 是 “platform sidecar prewarm and
player entry commands”，`mcp` 是 “MCP adapter host/profile commands”。`play --help` 的子命令文案也必须
保持 developer/trusted low-level 边界，避免把 `play act` / `play commit` 误读为普通玩家入口。

## Campaign 命令

当前子命令：

```text
campaign validate
campaign test
campaign copy-example
campaign new
campaign doctor
campaign outline
campaign explain
campaign check-ai
campaign split
```

合同：

- `validate` 和 `test` 是作者与 CI 门禁。`test` 可以初始化临时 save 做 smoke checks，但不能改正式 save。
- `copy-example` 和 `new` 创建 Campaign Package 文件；`--force` 是显式覆盖能力。
- `doctor`、`outline`、`explain`、`check-ai` 是 authoring diagnostics。
- `split --dry-run` 只建议拆分；`split --apply` 是作者内容维护能力，不是运行时事实写入。
- Campaign 工具不得写 `data/game.sqlite`、`save.yaml`、workspace registry、pending action 或玩家事实。

## Save 命令

当前子命令：

```text
save init
save inspect
save validate
save export
save import
save patch
```

合同：

- `save init <campaign_dir> <save_dir>` 从 Campaign Package 初始化 Save Package。
- `inspect` 和 `validate` 读取 Save Package 结构、manifest、SQLite 和投影状态；JSON 输出包含
  `authority_contract` 和 `projection_health`，声明 SQLite facts/events 与 derived、entry、advisory、
  evidence artifacts 的职责边界，并暴露 required projections 与 outbox 的 health/evidence。
- `export` 生成 `.aigmsave` 归档；归档默认可能包含 GM hidden 信息。
- `import` 需要显式 `--yes`，写入目标目录时必须遵守目标目录和 `--force` 语义；缺少核心 Save
  文件、unsafe member path、manifest drift、size mismatch 或 checksum mismatch 必须失败且不能替换目标目录。
- `patch` 是维护 patch 通道，默认应保留 pre-patch backup；它不能作为玩家行动、AI proposal 或
  action resolver 的替代入口。

Save 命令可以管理 Save Package 文件，但不能把未确认的自然语言 action 直接写成事实。玩家事实仍必须走
`player turn -> player confirm` 或 trusted 低层 `play preview/validate/commit` 链。

## Player 命令

当前子命令：

```text
player inspect
player campaigns
player saves
player current
player start
player query
player turn
player act
player confirm
player new
player switch
player duplicate
```

合同：

- `inspect`、`campaigns`、`saves`、`current` 是 workspace registry 和当前 save 查询。`current`
  不带 `--refresh` 时可以返回 workspace registry cache；JSON 输出的
  `current_save_authority.summary_source` 必须是 `registry_cache`，且
  `summary_authoritative=false`。带 `--refresh` 时 summary 来自 Save SQLite inspection。
- `start` 会继续 active save，或在允许时从 campaign/starter 创建一个 save。
- `new`、`switch`、`duplicate` 只管理 active save 指向和 save copy，不写 gameplay facts。
- `query` 是结构化只读查询，不保存、不推进时间、不需要 confirm。
- `turn` 是普通自然语言标准入口。它可以接受 `--external-intent-candidate`，但 external candidate
  永远是 low-trust input；internal intent AI enabled 时保持 external/internal arbitration，显式 `off`
  且候选合法时采用 `external_primary`，`off` 且无候选时保持 deterministic fallback。三条路径都必须
  经过 Kernel schema、registry、safety、binding/query、preview 和 pending/confirm 边界。
- 当前 client 应从 `intent_manifest` / Python `build_intent_manifest()` 取得 manifest v4 + taxonomy v1 + safety v1
  identity，
  在 candidate 的 optional all-or-nothing `contract` 中原样携带四个字段。省略时只进入显式
  `legacy_unversioned` compatibility；unknown safety 仍 fail closed。
- Action list/inspect 展示的 taxonomy version/digest/locale terms 来自 registry render helper；CLI 不维护
  平行 synonyms，也不因此获得 Campaign loader 或动态 plugin authority。
- `act` 是兼容 wrapper。它不接受 `--external-intent-candidate`，避免旧调用面把 external AI
  候选塞进兼容路径。
- `confirm --session-id` 只确认当前 pending player action；session id 必须来自 `player turn` 或
  兼容 `player act` 的 ready-to-confirm 返回。

玩家命令返回给普通玩家的结果不得暴露内部 `delta_draft` 或完整 `turn_proposal`。ready action 应只显示
玩家可见 preview、确认提示和 `session_id`。确认成功后 pending action 必须清理。
Pending action 有过期时间；过期、session id 不匹配、active save 不匹配、平台 session/actor
不匹配时，`confirm` 必须拒绝保存，过期 action 会被清理并要求玩家重新发起 `turn`。
确认 JSON 结果透传 Kernel 的 `write_status` 与 `idempotent_replay`：仅 fresh `committed` 使用
`saved=true` 和“本次已写入”文案；合法重试使用 `already_confirmed`、`idempotent_replay=true`、
`saved=false` 和“此前已确认”文案。Kernel 在完成 session/identity 核验后还可返回 bounded
`confirmation_session_hash`，用于可信 platform completion correlation；它不授予确认或 commit authority。
CLI 不读取 receipt 或自行分类，也不把 replay 描述为新保存。

## Play 命令

当前子命令：

```text
play preflight
play start-turn
play query
play act
play preview
play validate-delta
play commit
play health
play ux-metrics
```

合同：

- `preflight` 只预计算 advisory internal intent review；结果是 single-use / identity-bound 辅助证据。
- `start-turn` 构建上下文并分类玩家输入；它不是普通玩家提交入口。
- `query` 只读。
- `act` 是低层自然语言 preview/act primitive。即使存在 `--auto-confirm-low-risk`，普通玩家 UI
  也不应把它当作标准保存入口。
- `preview` 预演一个已选择 action，不能保存。
- `validate-delta` 校验 delta，不能保存。
- `commit` 只能提交已经 validation 和 approval 过的 TurnProposal/delta；默认应保留 backup、
  State Auditor 和 projection evidence。普通玩家保存仍应从 `player confirm` 进入。
- `health` 和 `ux-metrics` 是只读诊断。

`play start-turn`、`play preflight`、`play act` 和 `player turn` 遇到 typed external contract failure 时，
JSON 固定返回 `ok=false`、`errors`、`error_details` 并以非零退出；human mode 只输出 concise message 与 recovery
action，不输出 traceback 或 raw candidate。Mismatch 要求 refresh manifest 后重生成；unknown safety 要求按
当前 vocabulary 重生成。

任何使用 `play commit` 的脚本都必须能解释 proposal 来源、approval 来源、delta 来源和 backup/audit
策略。不能把 raw AI 文本、external candidate 或未确认 preview 直接交给 `commit`。

## Platform 命令

当前子命令：

```text
platform message
platform start
platform act
platform confirm
platform metrics
platform expire
platform deactivate
```

合同：

- 平台参数可以来自 `--event-json`，也可以来自 `--platform`、`--session-key`、`--message-id`、
  `--actor-id`、`--chat-type`、`--message-type` 和文本参数。
- `message` 只处理平台消息事件和 advisory prewarm，可选择 drain 做诊断；它不推进游戏事实。
- `start` 从平台消息 start/continue game，创建或绑定 active save 时仍必须通过 SaveManager。
- `act` 从平台消息调用 player act/turn 语义，并转发 passive preflight identity；不能绕过 pending/confirm。
- `confirm --session-id` 从平台消息确认 pending player action；平台 gate 必须校验 active binding。
- 平台确认必须保持同一 platform、session key 和 actor identity；同一群/会话里不同 actor 不能确认
  另一位玩家的 pending action。
- `metrics`、`expire`、`deactivate` 管理 sidecar canary metrics 和平台 session binding，不写游戏事实。
- Platform sidecar audit 是脱敏证据，不是事实源或权限源。启用 audit 时，记录应包含 operation、
  surface category、status、duration、identity hash、request/result summary；raw session key、
  raw actor id、delta/proposal/validation internals、hidden/private reasoning 不得写入 audit。
- Platform audit 写入失败不能改变已完成的 platform operation、gate 拒绝结果、pending state、
  Save facts、projection/outbox 或权限判断；最多作为 stderr/log warning 暴露。

Platform sidecar 可以配置 prewarm、intent helper 和 active binding 策略；这些配置只影响候选评审和
平台 gate，不授予 external AI、平台消息或 prewarm cache 提交事实的权限。

## MCP 命令

当前子命令：

```text
mcp serve
mcp print-config
```

合同：

- `serve --root <root>` 在 stdio transport 上启动 V1 MCP adapter。所有 campaign/save/starter 默认路径都应在
  `--root` 下解析，并保持 relative path boundary。
- `print-config <root>` 打印 AI client MCP JSON config，默认 server name 是 `aigm-kernel`，默认 command 是
  `aigm`。
- `--registry-active` 可以让省略 save 的 MCP 调用解析 workspace active save，但 registry 仍不是事实源。
- `--mcp-profile` 决定工具暴露和权限。player profile 只能使用 player-safe surface；developer、
  trusted_gm、maintenance、admin profile 才能使用低层 preview、validate、commit、preflight 或
  per-call AI override。
- `--ai-profile` 和各类 helper override 只配置辅助 AI；它们不能绕过 MCP profile gate、hidden-content
  gate、validation 或 commit gate。

MCP 详细工具合同会在 Round 3 的 MCP 合同文档中单独收敛。本文件只定义 CLI 如何启动和配置 MCP。

## Eval 命令

当前子命令：

```text
eval run
```

`eval run` 可以选择 intent、intent consensus、clarification-loop、real canary 或 MCP transcript suite。
它的职责是产生 regression evidence，不是 gameplay 或 maintenance 写入入口。新增 eval suite 时应保持
fixture 可复现，并把对应 focused tests 写入变更记录。

## Legacy / Admin Surface

当前 legacy/admin 顶层命令包括：

```text
init
query
context
memory
render-current
render-cards
save-turn
validate
response
proposal
delta
turn
reflection
ops
backup
migrate
projection
package
simulate
content
apply-content-delta
action
plugin
check
audit
preview
palette
import-v1
importer
```

合同：

- 这些命令主要服务 migration、projection repair、package upgrade、content maintenance、ops reports、
  proposal queue、legacy turn flow 和 developer diagnostics。
- 它们可以保留为维护面，但不应成为新普通玩家体验的入口。
- 会写入的命令必须遵守 backup、validation、projection/outbox、approval 和 path boundary。
- `query`、`context`、`preview`、`validate`、`check`、`audit` 等只读或诊断命令不得被客户端解释为事实已发生。
- Legacy `context build` 只在顶层投影 `ExternalIntentContractError`；unknown/mismatch 均非零退出、脱敏且不创建
  context audit row（除非其他成功调用显式请求 `--audit-context`）。
- `save-turn`、`turn accept-response`、`proposal apply`、`apply-content-delta`、`package upgrade` 等写入命令
  只能在 trusted maintenance / GM / migration 场景使用。
- `projection repair` 输出必须保留 repair evidence：profile、requested/skipped names、requested/global
  dirty/failed/stale、status/global_status、outbox_status/counts/non_done、artifacts、errors、started/finished
  time 和 duration。它只能刷新 post-commit read models/outbox evidence，不能提交 gameplay facts。Targeted
  repair 也必须暴露全局 outbox failed/pending evidence，不能把未修复工作报告成 global clean。

`rpg_engine.surface_inventory` 的 package / maintenance surface 测试哨兵使用以下精确名称：

- `aigm campaign validate`
- `aigm campaign test`
- `aigm campaign new`
- `aigm campaign doctor`
- `aigm save init`
- `aigm save inspect`
- `aigm save validate`
- `aigm save export`
- `aigm save import`
- `aigm save patch`
- `aigm package upgrade`
- `aigm package install`
- `aigm package reconcile`
- `aigm proposal apply`
- `aigm apply-content-delta`
- `aigm save-turn`
- `aigm migrate apply`
- `aigm projection repair`
- `aigm plugin validate`

同一 inventory 还登记 runtime、platform 和 projection/outbox entry points。CLI 新增或重命名入口时，
应同步更新 inventory 与 `tests/test_surface_inventory.py`，避免出现未分类的写入或维护旁路。

## AI 和 Preflight 参数

相关参数族：

```text
--intent-ai
--intent-backend
--intent-provider
--intent-model
--intent-timeout
--intent-base-url
--intent-api-key-env
--intent-fallback-backend
--external-intent-candidate
--preflight-id
--preflight-message-id
--preflight-platform
--preflight-session-key
--preflight-source-user-text-hash
```

合同：

- `--external-intent-candidate` 只在明确支持的入口中出现，尤其是 `player turn` 和低层 `play` intent preview
  能力；它不能表达确认、approval、hidden access 或保存授权。
- CLI 不提供关闭 legacy compatibility 的 flag，也不接受 per-call active-contract override；contract policy
  只能由 Kernel manifest schema version 演进。
- Internal AI、semantic helper、Archivist 和 State Auditor 都是辅助角色。它们可以影响 review、suggestion
  或 audit evidence，不能替代 confirm / validation / commit。
- `--intent-timeout` 表示一次 player-facing intent helper operation 的 hard total budget，默认候选约
  15 秒；约 8 秒 soft wait 只产生 latency evidence 或安全降级信号。Direct primary 与 fallback
  共享 hard budget，迟到结果不能进入 arbitration、pending 或 commit。
- Internal intent AI enabled 时 timeout/unavailable 不能被解释为显式 `off`，也不能授予 external
  candidate `external_primary` route proposal authority。
- Preflight cache 只缓存 advisory internal review；消费时必须绑定 text hash、message/session identity
  和 single-use 语义。
- API key env、provider、model 和 backend 参数只是 helper 配置，不改变 CLI/MCP profile 权限。

## 开发检查清单

改 CLI 相关代码或文档时，至少检查：

- 新命令属于 V1 public group 还是 legacy/admin surface？
- 普通玩家是否仍只能通过 `player turn -> player confirm` 保存事实？
- 新参数是否可能把 external AI、preflight 或平台消息升级成事实权限？
- JSON 输出是否稳定、可测试，并保留结构化失败信息？
- 写入命令是否有 path boundary、backup、validation、projection/outbox 和 approval 证据？
- 文档示例是否避免把 low-level `play` 工具描述成普通玩家默认入口？
- MCP 或 platform 相关 CLI flag 是否仍受 profile gate 和 platform gate 限制？

推荐 focused gate：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_save_manager.py tests/test_mcp_adapter.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py
```

如果改到 legacy package/projection/maintenance 命令，再追加对应 package、projection、migration 或 content
tests。
