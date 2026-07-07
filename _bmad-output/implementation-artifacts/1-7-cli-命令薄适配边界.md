---
baseline_commit: a3187b5d4870fa6e5e0671331193e679d2c87c44
---

# Story 1.7: CLI 命令薄适配边界

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为本地 host，
我希望 CLI `player` / `platform` / `mcp` 入口只调用 Kernel services，
从而避免 CLI 复制 intent、preview、validation 或 commit 业务逻辑。

## 验收标准

1. 给定 CLI `player` 命令处理普通玩家输入，当 preview 或 confirm 流程执行时，命令只把请求交给 `SaveManager.player_turn()` / `SaveManager.player_confirm()` 这类 SaveManager player-safe service，且不直接写 SQLite facts、events、entity state、clock/progress state、pending JSON 或 projection/outbox artifacts。
2. 给定现有 `player act` 兼容命令仍存在，当它处理自然语言玩家输入时，它只能保持 SaveManager-only 兼容 wrapper；不得直接调用 `GMRuntime`、`preview_action()`、`validate_delta()`、`commit_turn()`、SQLite 或 action resolver。
3. 给定 CLI `platform` / `mcp` 命令处理外部入口，当对应 contract test 运行时，`platform` 只通过 `PlatformSidecar` gate-and-forward，`mcp` 只组装/启动 MCP adapter config；CLI handler 不复制 platform identity、MCP profile gate、intent、preview、validation 或 commit 业务逻辑。
4. 给定 CLI `play` low-level 命令仍作为 developer/trusted 工具存在，当 CLI command contract test 运行时，`player`/`platform`/`mcp` 与 `play` 有明确分组、surface inventory 和帮助文本边界；普通 `player` path 不能获得 low-level commit 权限。

## 任务 / 子任务

- [x] 固化 CLI V1 surface 分组合同。 (AC: 3, 4)
  - [x] 复用现有 `rpg_engine/cli_v1.py` parser/handler 与 `rpg_engine/surface_inventory.py` inventory；不要新增并行 CLI dispatcher、command registry 或权限表。
  - [x] 明确 `aigm player` 是普通 player-safe 入口，`aigm platform` 是 platform sidecar 入口，`aigm mcp` 是 MCP host/adapter 入口，`aigm play` 是 developer/trusted low-level runtime 入口。
  - [x] 如帮助文本或 inventory wording 仍把 `play` 描述成普通玩法入口，改为 developer/trusted low-level；如 `player`/`platform` wording 暗示可直接 commit，也要收紧。

- [x] 为 `player` handler 增加薄适配边界测试。 (AC: 1, 2, 4)
  - [x] 在 `tests/test_v1_cli.py` 添加 focused contract test，证明 `handle_player()` 的 preview/confirm path 只经 `SaveManager.player_turn()` / `SaveManager.player_confirm()` 或既有 SaveManager 兼容 wrapper。
  - [x] 断言 `handle_player()` 不实例化或调用 `GMRuntime`，不调用 low-level `preview_action()`、`validate_delta()`、`commit_turn()`，不导入或使用 `sqlite3.connect()` 写 gameplay state。
  - [x] 覆盖 `player turn`、`player confirm`，并对现有 `player act` 兼容命令做 SaveManager-only 约束；不要通过删除兼容命令来满足测试，除非 canonical docs 和 inventory 同步改动。

- [x] 为 `platform` 与 `mcp` handler 增加薄适配边界测试。 (AC: 3, 4)
  - [x] 证明 `handle_platform()` 只调用 `build_platform_sidecar()` 和 `PlatformSidecar` methods，不直接创建 `SaveManager`、`GMRuntime` 或复制 platform binding/identity 业务逻辑。
  - [x] 证明 `handle_mcp()` 只调用 `MCPAdapterConfig.from_values()`、`build_client_config()`、`render_client_config()`、`serve_mcp()` 等 adapter 边界，不直接访问 runtime、Save SQLite 或 MCP tool registry internals。
  - [x] 保留 `build_platform_sidecar()` 作为 CLI 参数到 `PlatformSidecarConfig` / `PlatformPrewarmConfig` 的薄组装层；不要把 sidecar 行为搬进 CLI。

- [x] 保持 `play` low-level 能力存在但不混入普通 player path。 (AC: 4)
  - [x] 不删除 `play start-turn`、`play preflight`、`play query`、`play act`、`play preview`、`play validate-delta`、`play commit`、`play health`、`play ux-metrics`。
  - [x] 确认 `play commit` 仍通过 `GMRuntime.commit_turn()` 的 validation / approved `TurnProposal` / backup / audit guard；本 story 不应弱化这些 guard。
  - [x] 增加或更新 `tests/test_surface_inventory.py`，确认 `aigm player` 是 `player-safe`，`aigm play` 是 `trusted low-level`，且 `aigm play commit` 不属于 default player-safe path。

- [x] 同步 canonical contract docs。 (AC: 1, 2, 3, 4)
  - [x] 若 CLI help、inventory、handler 边界或 `player act` 兼容语义变化，同步 `docs/cli-contracts.md`。
  - [x] 若 MCP profile/default config wording 变化，同步 `docs/mcp-contracts.md`；不要改变 Story 1.6 已完成的默认 `player` profile 权限门。
  - [x] 若架构总览需要补充 CLI 薄适配说明，同步 `docs/architecture.md` 或 `docs/component-inventory.md`，但避免重复业务流程细节。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3, 4)
  - [x] 先跑新增/修改的 RED 测试，确认当前缺口被测试抓住。
  - [x] 最小 GREEN gate：`python3 -m pytest -q tests/test_v1_cli.py tests/test_surface_inventory.py`。
  - [x] 若改动触碰 player workflow：`python3 -m pytest -q tests/test_v1_cli.py tests/test_save_manager.py`。
  - [x] 若改动触碰 platform sidecar：`python3 -m pytest -q tests/test_v1_cli.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py`。
  - [x] 若改动触碰 MCP config/profile：`python3 -m pytest -q tests/test_v1_cli.py tests/test_mcp_adapter.py`。
  - [x] 收尾运行 `git diff --check`；若 docs/story links 变化，运行 `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-7-cli-命令薄适配边界.md`。

### Review Findings

- [ ] [Review][Carry Forward] Windows-style forward-slash drive paths are still accepted as root-relative on POSIX in MCP path validation; this is deferred from Story 1.6 and is not in scope for CLI thin adapter unless touched.
- [x] [Review][Patch] `play --help` subcommands still read like ordinary gameplay instead of trusted low-level commands [rpg_engine/cli_v1.py:333]
- [x] [Review][Patch] `handle_player` forbidden-call sentinel does not cover direct artifact/file writes [tests/test_v1_cli.py:184]
- [x] [Review][Patch] CLI contract docs/tests omit the `platform` help authority phrase [docs/cli-contracts.md:79]
- [x] [Review][Patch] Top-level help test asserts exact argparse spacing instead of semantic whitespace [tests/test_v1_cli.py:70]
- [x] [Review][Defer] `platform_event_from_args` can override `--event-json` identity/text with explicit flags [rpg_engine/cli_v1.py:1186] — deferred, pre-existing
- [x] [Review][Patch] Surface inventory sentinel should cover every `aigm play *` subcommand, not only `play commit` [tests/test_surface_inventory.py:331]
- [x] [Review][Patch] `handle_player` forbidden-call sentinel should include additional direct filesystem APIs [tests/test_v1_cli.py:197]

## 开发说明

### 来源上下文

- Epic 1 目标是让 Oliver 可以通过 player-safe path 长期游玩、确认行动、保存事实，并且 CLI/MCP/platform/low-level 入口不会混淆权限。Story 1.7 专门处理 CLI `player` / `platform` / `mcp` 的薄适配边界。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 1.7 原始 AC 要求 CLI `player` preview/confirm 只调用 `SaveManager.player_turn()` / `SaveManager.player_confirm()`，不直接写 SQLite facts/events/entity/progress；`play` low-level 仍作为 developer/trusted 工具存在，并与 player-safe 命令有明确帮助文本边界。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-1 要求普通 gameplay 写入必须经过 player turn、pending action、player confirmation、validation 和 commit；FR-2 要求所有 public / semi-public surfaces 分类；FR-16 要求外部 surfaces 有明确输入、输出、错误、权限边界和写入权威。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Execution-chain AD-1 规定 ordinary player fact writes 只能走 `SaveManager.player_turn()` 到 pending action，再 `SaveManager.player_confirm(session_id)`，再 `GMRuntime.commit_turn()`；AD-3 要求每个 CLI/MCP/platform/runtime surface 声明 category/write authority；AD-5 要求 touching CLI 的 story 带 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。
- Foundation AD-3 把 Surface Authority Contract 作为 foundation interface；AD-10 要求下游 story 触碰 foundation boundary 时增加最小有意义测试，并保持 player-safe / low-level / platform / MCP 边界。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Canonical CLI contract 声明 CLI 是 reference entry，不是业务逻辑源；`player turn` 创建 query/clarification/blocked/pending action 但不提交 facts；`player confirm --session-id` 是普通玩家 CLI commit gate；`play *` 是 low-level runtime/developer/trusted 工具；`platform *` 通过 sidecar/SaveManager 边界；`mcp serve` 启动 MCP adapter，profile gate 不属于 CLI flag 之外的临时逻辑。来源：`docs/cli-contracts.md`。
- Project context 明确 “AI proposes. Kernel verifies. Player confirms. Engine commits.”，SQLite 是当前事实权威，MCP/CLI/platform sidecar 是薄 wrapper，只调用 kernel services，不能复制 business logic。来源：`docs/project-context.md`。

### 当前实现状态

- `rpg_engine/cli.py` 的 `main()` 构建 legacy/admin parser 后先调用 `add_v1_parsers()`，parse 后调用 `handle_v1_command(args)`；若返回非 `None`，V1 command 直接完成。Story 1.7 应主要落在 `rpg_engine/cli_v1.py`，不要把 V1 player/platform/mcp 逻辑搬回 legacy CLI 分支。来源：`rpg_engine/cli.py`。
- `rpg_engine/cli_v1.py` 当前声明 V1 top-level commands：`campaign`、`save`、`play`、`mcp`、`player`、`platform`、`eval`。`play` parser 当前 help 是 “V1 runtime play commands”，实现上直接 `GMRuntime.from_path(args.campaign_dir)` 后调用 runtime preflight/start/query/act/preview/validate/commit/health/ux-metrics。来源：`rpg_engine/cli_v1.py`。
- `handle_player()` 当前只实例化 `SaveManager(args.root)`，并把 `inspect`、`campaigns`、`saves`、`current`、`start`、`query`、`turn`、`act`、`confirm`、`new`、`switch`、`duplicate` 转给 SaveManager。`player turn` 使用 `manager.player_turn(..., **intent_preview_kwargs_from_args(args))`；`player confirm` 使用 `manager.player_confirm(session_id=args.session_id)`；`player act` 是 `manager.player_act(...)` 兼容 wrapper。来源：`rpg_engine/cli_v1.py`。
- `player turn` parser 当前允许 `--external-intent-candidate`，并通过 `intent_preview_kwargs_from_args()` 解析为外部 AI intent candidate；这仍必须保持 low-trust candidate 语义，不能被 CLI 当作 approval、delta 或 commit authorization。来源：`rpg_engine/cli_v1.py` 与 Story 1.6/PRD AI low-trust 约束。
- `handle_platform()` 当前通过 `build_platform_sidecar(args)` 创建 `PlatformSidecar`，再调用 `handle_message_event()`、`start_or_continue_from_message()`、`player_act_from_message()`、`player_confirm_from_message()`、`metrics_snapshot()`、`expire_stale_bindings()`、`deactivate_from_message()`。CLI 只应保持参数组装和结果渲染，不复制 sidecar binding、prewarm 或 SaveManager gate。来源：`rpg_engine/cli_v1.py`。
- `handle_mcp()` 当前局部导入 `MCPAdapterConfig`、`build_client_config`、`render_client_config`、`serve_mcp`；`print-config` 只构建客户端配置，`serve` 只用 `MCPAdapterConfig.from_values()` 组装并调用 `serve_mcp(config, transport=args.transport)`。不要在 CLI handler 内复制 MCP tool registration/profile gate。来源：`rpg_engine/cli_v1.py`。
- `CLI_V1_COMMAND_SURFACE_INVENTORY` 已把 `aigm player` 标为 `player-safe`，`aigm platform` 标为 `platform sidecar`，`aigm mcp` 标为 MCP host/trusted low-level command group，`aigm play` 标为 `trusted low-level`。来源：`rpg_engine/surface_inventory.py`。
- `CLI_V1_SUBCOMMAND_SURFACE_INVENTORY` 已把 `play commit` 标为 `trusted low-level` / `developer_or_trusted_gm_commit`，把 `player turn` / `player confirm` 标为 player-safe pending/confirm path，把 `player act` 标为 player-safe compatibility wrapper。Story 1.7 的实现应优先加测试巩固这些分类，而不是重写 inventory 模型。来源：`rpg_engine/surface_inventory.py`。
- `tests/test_surface_inventory.py` 已覆盖 CLI V1 command group 与 parser-derived subcommands：`V1_COMMANDS`、`aigm player` category、`aigm platform` category、`aigm mcp` authority gate、`aigm player turn` 与 `aigm play commit` presence。Story 1.7 应扩展这些测试到 help wording / low-level boundary，而不是只重复现有 presence 断言。来源：`tests/test_surface_inventory.py`。
- `tests/test_v1_cli.py` 当前以 subprocess smoke 和 helper-unit 测试为主，已有 intent helper/preflight/external candidate 参数覆盖、player confirm JSON 隐藏 raw commit payload、player path rejection 不写 workspace state、play low-level runtime flow、MCP print-config 等测试。Story 1.7 可在该文件增加 source/AST 或 monkeypatch focused contract tests。来源：`tests/test_v1_cli.py`。

### 前序故事情报

- Story 1.6 已完成默认 MCP `player` profile 权限门：默认 profile 只暴露 player-safe tools；low-level MCP tools 在 registration 和直接 adapter method 层都会被 gate；audit summary 不暴露 raw session key、raw delta/proposal internals、hidden/private key variants。Story 1.7 不得重新打开 MCP player profile 的低层工具。来源：`_bmad-output/implementation-artifacts/1-6-mcp-player-profile-权限门.md`。
- Story 1.6 明确 `player_query` 和 `player_act` 在 MCP 中属于 low-level/compat tools，不是默认 MCP player profile；CLI 的 `player act` 目前仍是 player-safe compatibility wrapper，经 SaveManager 处理。实现时不要把 MCP 结论机械套到 CLI 上；应以 `docs/cli-contracts.md` 和 `surface_inventory.py` 当前 CLI 分类为准。
- Story 1.5 已完成 projection/outbox health evidence：projection/outbox 是 post-commit read model/evidence，不是 pre-commit authority。CLI `player` / `platform` / `mcp` boundary tests 不应直接写 projection/outbox 来证明 gameplay state。
- Story 1.4 已完成 Save fact authority 和 runtime state boundary：SQLite `data/game.sqlite` 是当前事实权威；registry、pending、projection、archive、preflight cache、MCP audit 不能覆盖 facts。Story 1.7 的 CLI contract 必须保留这个分层。
- Story 1.3 已完成 `SaveManager.player_confirm()` 普通玩家 commit gate；Story 1.2 已完成 `SaveManager.player_turn()` pending contract。CLI `player` implementation 应依赖这些 services，而不是复刻 preview/validation/commit logic。
- 最近提交模式显示：`a3187b5` harden player confirm commit gate、`97aa92d` sanitize pending preflight identity、`6b8dfd8` add surface authority inventory contract。Story 1.7 应沿用“合同清晰 + focused boundary tests + 不新增并行机制”的模式。

### 架构合规要求

- Thin adapter means CLI handler may parse args, call one kernel/service boundary, render result, and map exceptions to CLI output. It must not decide gameplay authority, construct deltas, validate commit eligibility, write facts/events, or duplicate profile/session/identity gates.
- Ordinary player write chain remains: `aigm player turn` -> `SaveManager.player_turn()` -> pending action/session id or non-commit outcome -> `aigm player confirm --session-id` -> `SaveManager.player_confirm()` -> runtime validation/commit internally.
- `aigm play *` remains trusted low-level. It may call `GMRuntime` directly, but it is not normal player UX and must remain separated in help text, docs, and inventory.
- `aigm platform *` remains platform sidecar. It may accept platform/session/actor/message args, but binding, prewarm, passive preflight identity, pending conflict, and confirm identity checks belong in `PlatformSidecar` / SaveManager services.
- `aigm mcp *` remains adapter host/config surface. MCP profile selection and low-level tool exposure belong in `mcp_adapter.py`, not in CLI handler branches.
- AI/internal intent candidate inputs remain low-trust. CLI may pass candidates through existing service kwargs; it must not treat an AI candidate as final intent, hidden access authorization, proposal approval, delta injection, or commit permission.
- If a change touches public CLI semantics, update canonical docs and surface inventory in the same story. If only tests are added to lock current semantics, docs changes may be unnecessary.

### 相关文件

- `rpg_engine/cli_v1.py`：V1 parser definitions, `handle_v1_command()`, `handle_play()`, `handle_player()`, `handle_platform()`, `handle_mcp()`, CLI argument-to-service kwargs helpers.
- `rpg_engine/cli.py`：top-level CLI entry that registers V1 parsers and delegates V1 commands before legacy/admin handlers; only touch if V1 dispatch boundary itself changes.
- `rpg_engine/surface_inventory.py`：`CLI_V1_COMMAND_SURFACE_INVENTORY`、`CLI_V1_SUBCOMMAND_SURFACE_INVENTORY`、surface validation rules.
- `rpg_engine/save_manager.py`：player-safe `player_turn()` / `player_confirm()` / compatibility helpers; use as service boundary, do not copy logic into CLI.
- `rpg_engine/platform_sidecar.py` 和 `rpg_engine/platform_prewarm.py`：platform gate-and-forward, active binding, passive preflight/prewarm behavior.
- `rpg_engine/mcp_adapter.py`：MCP profile/tool registration/method gate; CLI `mcp` should only configure and start it.
- `rpg_engine/runtime.py`：trusted low-level runtime facade for `play` command and internal SaveManager/platform paths.
- `docs/cli-contracts.md`：canonical CLI group and command boundary.
- `docs/mcp-contracts.md`：canonical MCP profile and tool boundary; update only if CLI `mcp` profile/config semantics change.
- `docs/architecture.md` 和 `docs/component-inventory.md`：high-level architecture/component inventory for thin adapter rules.
- `tests/test_v1_cli.py`：primary focused CLI contract tests.
- `tests/test_surface_inventory.py`：surface taxonomy and CLI V1 command/subcommand inventory tests.
- `tests/test_save_manager.py`：run if player workflow expectations or SaveManager compatibility wrapper behavior changes.
- `tests/test_platform_sidecar.py`、`tests/test_platform_prewarm.py`：run if platform CLI argument flow or sidecar config/behavior changes.
- `tests/test_mcp_adapter.py`：run if CLI `mcp` config/profile semantics or MCP docs/inventory change.

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_surface_inventory.py
git diff --check
```

如果实现触碰 SaveManager player workflow、pending state、`player_act` compatibility wrapper 或 player result shape：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_save_manager.py
```

如果实现触碰 platform sidecar CLI 参数、prewarm config、binding identity 或 platform result rendering：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py
```

如果实现触碰 CLI `mcp serve` / `print-config`、MCP profile defaults 或 MCP docs examples：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_mcp_adapter.py
```

如果 implementation changes shared dispatch, runtime validation/commit, SaveManager, MCP adapter gates, or cross-module contracts:

```bash
python3 -m pytest -q
```

### 残余风险与边界

- 本 story 不要求删除 legacy/admin CLI commands，也不要求把 `rpg_engine/cli.py` 所有 older maintenance/admin paths 重构成 V1。范围是 V1 `player` / `platform` / `mcp` 入口和它们相对 `play` low-level 的边界。
- 不要为了让测试简单而删除 `player act`。它是现有 CLI compatibility wrapper；若保留，必须证明它仍只调用 SaveManager boundary。
- 不要把 `play` 伪装成 player-safe，也不要把 `play commit` 从 trusted low-level 降级到普通 player command。`play` 存在是 developer/trusted 诊断能力，边界应通过 help/docs/inventory/tests表达清楚。
- 不要新增数据库表、pending 格式、projection 格式、MCP tool registry 或 platform binding store。Story 1.7 应主要是 tests/help/docs/inventory/handler guard 的局部修正。
- Static source/AST tests can be valuable here, but avoid brittle tests that fail on harmless formatting. Prefer asserting forbidden call/import names inside specific handler function bodies and behavioral monkeypatch tests for call routing.
- RED/GREEN 记录要能说明新增测试先抓住了真实边界缺口；如果当前实现已满足某项边界，只记录 “existing behavior locked by new test”，不要伪造失败。

### 最新技术信息

无需外部 Web research。本 story 使用现有 Python stdlib `argparse`、`unittest` / `pytest`、`sqlite3` temp fixtures、`SaveManager`、`GMRuntime`、`PlatformSidecar`、`MCPAdapterConfig` 和 `surface_inventory` patterns。不要新增运行时依赖。

## Project Structure Notes

Story 1.7 应优先修改 `rpg_engine/cli_v1.py`、`rpg_engine/surface_inventory.py`、`docs/cli-contracts.md` 和 focused tests。保持 V1 command handlers 在 `cli_v1.py`，保持 kernel/service 逻辑在 SaveManager、PlatformSidecar、MCP adapter 和 runtime。若需要测试 handler body，直接定位 `handle_player()` / `handle_platform()` / `handle_mcp()`，不要全局扫描整个 CLI 文件误伤 legacy/admin surfaces。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-6-mcp-player-profile-权限门.md`
- `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/cli.py`
- `rpg_engine/cli_v1.py`
- `rpg_engine/surface_inventory.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/platform_sidecar.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/runtime.py`
- `tests/test_v1_cli.py`
- `tests/test_surface_inventory.py`
- `tests/test_save_manager.py`
- `tests/test_platform_sidecar.py`
- `tests/test_platform_prewarm.py`
- `tests/test_mcp_adapter.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Implementation Plan

- 先写 focused CLI boundary tests，锁住 `player` / `platform` / `mcp` handler 只调用 service boundary，`play` 保持 trusted low-level。
- 根据 RED 结果最小修改 help text、inventory、docs 或 handler routing；不新增并行 dispatcher/registry，不复制 kernel business logic。
- 运行最小 gates，若触碰 SaveManager/platform/MCP contract，再追加对应 focused suites。

### Debug Log References

- RED: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_cli_help_separates_player_safe_and_trusted_low_level_groups` failed because top-level CLI help still described `play` as generic V1 runtime commands.
- GREEN: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_cli_help_separates_player_safe_and_trusted_low_level_groups` passed.
- Surface inventory focused gate: `python3 -m pytest -q tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_v1_command_inventory_covers_declared_command_groups tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_v1_subcommand_inventory_covers_parser_derived_subcommands` passed.
- Existing behavior locked: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_player_handler_routes_turn_act_and_confirm_through_save_manager tests/test_v1_cli.py::V1CliTests::test_player_handler_does_not_call_low_level_runtime_or_sqlite` passed, proving current `handle_player()` routes `turn`/`act`/`confirm` through SaveManager and contains no direct low-level runtime/SQLite calls.
- Existing behavior locked: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_platform_handler_routes_player_entries_through_sidecar tests/test_v1_cli.py::V1CliTests::test_mcp_handler_routes_config_and_serve_through_adapter_boundary tests/test_v1_cli.py::V1CliTests::test_platform_and_mcp_handlers_do_not_call_low_level_runtime_or_sqlite` passed with 3 tests and 2 subtests, proving current `handle_platform()` uses sidecar forwarding and current `handle_mcp()` uses adapter config/serve boundaries without direct runtime/SQLite calls.
- Existing behavior locked: `python3 -m pytest -q tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_v1_inventory_keeps_play_commit_out_of_player_safe_path` passed, proving inventory keeps `aigm play` / `aigm play commit` trusted low-level and outside default player-safe normal play.
- RED: `python3 -m pytest -q tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_contract_docs_describe_v1_help_authority_boundaries` failed because `docs/cli-contracts.md` did not yet mention the tightened top-level help authority wording.
- GREEN: `python3 -m pytest -q tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_contract_docs_describe_v1_help_authority_boundaries` passed.
- Focused gate: `python3 -m pytest -q tests/test_v1_cli.py tests/test_surface_inventory.py` passed with 65 tests and 219 subtests.
- Markdown links: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-7-cli-命令薄适配边界.md` passed, checking 87 markdown files.
- Whitespace gate: `git diff --check` passed.
- Full regression: `python3 -m pytest -q` passed with 519 tests and 629 subtests.
- Code review patch focused gate: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_cli_help_separates_player_safe_and_trusted_low_level_groups tests/test_v1_cli.py::V1CliTests::test_play_help_labels_subcommands_as_trusted_low_level tests/test_v1_cli.py::V1CliTests::test_player_handler_routes_turn_act_and_confirm_through_save_manager tests/test_v1_cli.py::V1CliTests::test_player_handler_does_not_call_low_level_runtime_or_sqlite tests/test_v1_cli.py::V1CliTests::test_platform_handler_routes_player_entries_through_sidecar tests/test_v1_cli.py::V1CliTests::test_mcp_handler_routes_config_and_serve_through_adapter_boundary tests/test_v1_cli.py::V1CliTests::test_platform_and_mcp_handlers_do_not_call_low_level_runtime_or_sqlite tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_v1_inventory_keeps_play_commit_out_of_player_safe_path tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_contract_docs_describe_v1_help_authority_boundaries` passed with 9 tests and 2 subtests.
- Code review patch focused gate: `python3 -m pytest -q tests/test_v1_cli.py tests/test_surface_inventory.py` passed with 66 tests and 219 subtests.
- Code review patch markdown links: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-7-cli-命令薄适配边界.md` passed, checking 87 markdown files.
- Code review patch whitespace gate: `git diff --check` passed.
- Code review re-run patch focused gate: `python3 -m pytest -q tests/test_surface_inventory.py::SurfaceInventoryTests::test_cli_v1_inventory_keeps_play_commit_out_of_player_safe_path tests/test_v1_cli.py::V1CliTests::test_player_handler_does_not_call_low_level_runtime_or_sqlite` passed with 2 tests and 9 subtests.
- Code review re-run patch focused gate: `python3 -m pytest -q tests/test_v1_cli.py tests/test_surface_inventory.py` passed with 66 tests and 228 subtests.
- Code review re-run patch markdown links: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-7-cli-命令薄适配边界.md` passed, checking 87 markdown files.
- Code review re-run patch whitespace gate: `git diff --check` passed.

### Completion Notes List

- Tightened V1 CLI top-level help and surface inventory descriptions so `play` is explicitly developer/trusted low-level, `player` is player-safe, and `mcp` is adapter host/profile scoped without changing command behavior.
- Added `handle_player()` boundary tests that lock `player turn`, `player act`, and `player confirm` to SaveManager-only routing and guard against direct `GMRuntime`/SQLite/low-level commit calls.
- Added `handle_platform()` and `handle_mcp()` boundary tests that lock platform routing to `PlatformSidecar` and MCP routing to `MCPAdapterConfig` / `build_client_config` / `serve_mcp`.
- Added surface inventory sentinel proving `aigm play commit` remains trusted low-level while `aigm player confirm` remains the player-safe SaveManager confirmation path.
- Synchronized `docs/cli-contracts.md` with the CLI help authority wording; no MCP profile/default semantics changed, so `docs/mcp-contracts.md` did not need edits.
- Completed focused and full regression gates; SaveManager/platform/MCP optional suites are covered by full regression and no behavior changed in those services.

### File List

- `_bmad-output/implementation-artifacts/1-7-cli-命令薄适配边界.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/cli-contracts.md`
- `rpg_engine/cli_v1.py`
- `rpg_engine/surface_inventory.py`
- `tests/test_v1_cli.py`
- `tests/test_surface_inventory.py`

### Change Log

- 2026-07-07: Implemented CLI thin-adapter boundary guards for Story 1.7; tightened V1 help/inventory wording, added player/platform/MCP handler boundary tests, added play-vs-player inventory sentinel, synchronized CLI contract docs, and passed focused/full regression gates.
