---
baseline_commit: a3187b5d4870fa6e5e0671331193e679d2c87c44
---

# Story 1.6: MCP Player Profile 权限门

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 AI client 集成者，
我希望默认 MCP `player` profile 只暴露 player-safe tools，
从而保证 MCP 不能绕过普通玩家的 preview、pending、confirm 和 commit 边界。

## 验收标准

1. 给定默认 MCP `player` profile 已启用，当 MCP server tool registration、tool list 或 surface inventory 被检查时，只注册 player-safe tools；low-level preview、validate、commit、preflight、hidden view、maintenance 和 per-call AI override tools 不可用。
2. 给定 MCP `player` profile 调用禁止工具，当请求到达权限门时，请求被拒绝并返回清晰的 tool/profile/surface category mismatch；拒绝不能写入 Save facts、pending action、pending clarification 或 audit 以外的 gameplay state。
3. 给定 developer、trusted_gm、maintenance 或 admin profile 显式启用，当 low-level tools 被注册或调用时，它们仍必须保留各自的 hidden-read、preflight、clarification、validation、state-audit 和 commit guard，不能因为收紧 player profile 而退化。
4. 给定 MCP audit logging 已启用，当 player profile 的禁止工具调用被拒绝时，audit record 只记录 sanitized request 和 summarized error result；audit 不能包含 raw `session_key`、raw delta/proposal internals、hidden facts 或 AI private reasoning。

## 任务 / 子任务

- [x] 收紧并文档化 MCP profile 工具注册合同。 (AC: 1)
  - [x] 复用现有 `PLAYER_MCP_TOOL_NAMES`、`LOW_LEVEL_MCP_TOOL_NAMES`、`MCP_TOOL_NAMES` 和 `mcp_tool_names_for_profile()`；不要新增并行 MCP registry。
  - [x] 保持 `serve_mcp()` 默认 `player` profile 只通过 FastMCP 注册 `PLAYER_MCP_TOOL_NAMES`。
  - [x] 明确禁止 `player` profile 注册或暴露 `player_query`、`player_act`、`start_turn`、`intent_preflight`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn`，以及 repair/plugin/package/migration/projection repair/arbitrary file/model proxy 类工具。
  - [x] 保持 `build_client_config()` 默认不输出 `--mcp-profile player`；只有非 player profile 才显式写入 `--mcp-profile <profile>`。

- [x] 在 adapter method 层补齐权限门，避免绕过注册层。 (AC: 1, 2, 3)
  - [x] 现有 server registration 已能阻止 player profile 注册低层工具；本 story 还要让 `AIGMMCPAdapter` 直接调用低层方法时也按 profile 拒绝。
  - [x] 对 `intent_preflight()`、`query()`、`preview_from_text()`、`preview_action()`、`validate_delta()`、`commit_turn()` 和需要低层语义的 `start_turn()` 做一致 gate；默认 player profile 应被拒绝，除非该方法被保留为明确 player-safe surface。
  - [x] 若 `start_turn()` 或 `preview_from_text()` 当前测试依赖 player profile 直接调用，应更新测试到 developer profile，或改为覆盖 `player_turn()` 的合法路径；不要用测试保留低层旁路。
  - [x] 保留 `player_turn()` 作为 player profile 的自然语言入口；它可以使用 server-level helper defaults 和 passive preflight identity，但不得接受 per-call AI override、hidden view、delta/proposal injection、confirmation 或 save authorization。
  - [x] 保留 low-level profiles 对这些工具的能力，但继续执行 hidden-read gate、pending clarification gate、state audit guard、validation/TurnProposal guard 和 backup policy。

- [x] 让拒绝结果成为清晰、稳定、可测的权限证据。 (AC: 2, 4)
  - [x] 禁止工具的返回必须结构化：`ok=false`、`errors` 含 tool name、当前 profile、所需 profile 或 surface category；`error_details` 保持可机读。
  - [x] 错误文案应能说明是 profile/surface category mismatch，而不是 campaign/save 缺失、validation failed 或 runtime exception。
  - [x] 拒绝路径不得创建 pending action、pending clarification、turns、events、entity/clocks changes、preflight cache rows 或 Save facts。
  - [x] 若 audit log 开启，拒绝可以写 audit evidence；audit 仍必须清洗 `session_key`，并只记录 summarized error result。

- [x] 保持 surface inventory 与 canonical docs 同步。 (AC: 1, 2, 3)
  - [x] `MCP_SURFACE_INVENTORY` 必须覆盖全部 MCP tools，且 default-exposed entries 全部是 `player-safe`。
  - [x] Low-level entries 必须 `default_exposed=False`，并保留 authority gate 说明。
  - [x] 如果工具清单、profile 语义、错误形状或 audit summary 变化，同步 `docs/mcp-contracts.md`、`docs/cli-contracts.md` 和必要的 prompt/AI client 指南。
  - [x] 不要把 MCP repair、projection repair、package install/upgrade/reconcile、migration apply、plugin 或 arbitrary file read/write 加入 player profile。

- [x] 添加 focused boundary tests。 (AC: 1, 2, 3, 4)
  - [x] 增强 `tests/test_mcp_adapter.py`：FakeFastMCP 注册层断言 player profile 只注册 `PLAYER_MCP_TOOL_NAMES`，developer profile 注册 full `MCP_TOOL_NAMES`。
  - [x] 增强 `tests/test_mcp_adapter.py`：默认 player profile 直接调用每个低层 adapter method 都返回 permission error，且不会写 Save facts、pending action、pending clarification 或 preflight cache。
  - [x] 增强 `tests/test_mcp_adapter.py`：developer profile 的低层 happy path、hidden view 限制、clarification guard、state audit guard 仍通过。
  - [x] 增强 `tests/test_surface_inventory.py`：`mcp_default_tool_names() == PLAYER_MCP_TOOL_NAMES`，`MCP_SURFACE_INVENTORY` 覆盖全部 tools，default-exposed non-player-safe entry 被拒绝。
  - [x] 如果 CLI `mcp serve` / `print-config` 参数语义变化，补 `tests/test_v1_cli.py` 对默认 player profile 和显式 non-player profile config 的断言。

### Review Findings

- [x] [Review][Patch] MCP audit summary can still expose sensitive field names or key variants [rpg_engine/mcp_adapter.py:1687]
- [x] [Review][Defer] Windows-style forward-slash drive paths are still accepted as root-relative on POSIX [rpg_engine/mcp_adapter.py:1596] — deferred, pre-existing

## 开发说明

### 来源上下文

- Epic 1 目标是让 Oliver 可以通过 player-safe path 长期游玩，并且 CLI/MCP/platform/low-level 入口不会混淆权限。Story 1.6 专门处理默认 MCP `player` profile 的权限门。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 1.6 原始 AC 要求默认 MCP `player` profile 只注册 player-safe tools；low-level preview、validate、commit、preflight、hidden view、maintenance 和 per-call AI override tools 不可用；禁止工具调用必须被拒绝且不写 gameplay state。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-1 要求普通 gameplay 写入必须经过 player turn、pending action、player confirmation、validation 和 commit；FR-2 要求所有 public/semi-public surfaces 分类；FR-16 要求外部 surfaces 有明确输入、输出、错误、权限边界和写入权威。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Execution-chain AD-1 规定 ordinary player fact writes 只能走 `SaveManager.player_turn()` 到 pending action，再 `SaveManager.player_confirm(session_id)`，再 `GMRuntime.commit_turn()`；AD-3 要求 MCP tool 声明 category/write authority；AD-5 要求 touching MCP/profile gate 的 story 带 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。
- Foundation AD-3 把 Surface Authority Contract 作为 foundation interface；AD-10 明确 feature-level gate 包含 “MCP player profile 不暴露低层 commit/preview/validate”。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Canonical MCP contract 声明 `player` profile 只注册 player-safe tools；developer/trusted_gm/maintenance/admin 才注册低层工具；`player` profile 不能使用 hidden view、maintenance mode 或 per-call semantic/intent AI override。来源：`docs/mcp-contracts.md`。
- CLI contract 声明 `mcp serve --root` 启动 MCP adapter，`--mcp-profile` 决定工具暴露和权限，`--ai-profile` 与 helper override 不改变 MCP profile gate。来源：`docs/cli-contracts.md`。

### 当前实现状态

- `rpg_engine/mcp_adapter.py` 已定义 `PLAYER_PROFILE`、`DEVELOPER_PROFILE`、`TRUSTED_GM_PROFILE`、`MAINTENANCE_PROFILE`、`ADMIN_PROFILE`、`LOW_LEVEL_PROFILES` 和 `HIDDEN_READ_PROFILES`。来源：`rpg_engine/mcp_adapter.py`。
- 当前 `PLAYER_MCP_TOOL_NAMES` 包含 `workspace_inspect`、`campaign_list`、`save_list`、`save_current`、`save_create`、`save_switch`、`start_or_continue`、`intent_manifest`、`player_turn`、`player_confirm`、`campaign_validate`、`save_inspect`、`health`。来源：`rpg_engine/mcp_adapter.py`。
- 当前 `LOW_LEVEL_MCP_TOOL_NAMES` 包含 `player_query`、`player_act`、`start_turn`、`intent_preflight`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn`。来源：`rpg_engine/mcp_adapter.py`。
- `mcp_tool_names_for_profile()` 当前对 `LOW_LEVEL_PROFILES` 返回 full `MCP_TOOL_NAMES`，对默认/其他 profile 返回 `PLAYER_MCP_TOOL_NAMES`。来源：`rpg_engine/mcp_adapter.py`。
- `serve_mcp()` 当前对 FastMCP tool registration 已做 profile split：player profile 注册 player-safe tools，low-level tools 只在 `config.mcp_profile in LOW_LEVEL_PROFILES` 时注册。来源：`rpg_engine/mcp_adapter.py`。
- `intent_preflight()`、`preview_action()`、`validate_delta()`、`commit_turn()` 当前在 adapter method 内调用 `require_low_level_profile()`；`query()` 当前只检查 hidden view；`start_turn()`/`preview_from_text()` 当前通过 `require_player_safe_start()` 只拒绝 player profile 的 maintenance mode 或 per-call AI override，而不是统一拒绝低层方法直接调用。来源：`rpg_engine/mcp_adapter.py`。
- `call_with_audit()` 当前会把 callback exception 转成 `error_dict()` 并写 audit record；`sanitize_for_audit()` 会 hash `session_key`；`summarize_result_for_audit()` 会只保留结果摘要。来源：`rpg_engine/mcp_adapter.py`。
- `MCP_SURFACE_INVENTORY` 已列出每个 MCP tool 的 taxonomy、profile、write authority、default_exposed 和 forbidden bypasses；`validate_surface_inventory()` 会拒绝 default-exposed non-player-safe MCP entry 和 player-safe low-level authority。来源：`rpg_engine/surface_inventory.py`。
- `tests/test_mcp_adapter.py` 已覆盖工具常量、FakeFastMCP 注册层 profile split、player workflow 隐藏 delta/proposal、hidden view/low-level/AI override 拒绝、path rejection、audit summary、state audit guard。来源：`tests/test_mcp_adapter.py`。
- `tests/test_surface_inventory.py` 已覆盖 inventory validate、default MCP tools 匹配 `PLAYER_MCP_TOOL_NAMES`、low-level entries 非 default exposed、write modes 和 canonical docs mention。来源：`tests/test_surface_inventory.py`。

### 前序故事情报

- Story 1.5 已创建但尚未实现，状态是 `ready-for-dev`。Story 1.6 实现不得依赖 Story 1.5 的未来代码；只能依赖当前代码事实和已完成故事。
- Story 1.4 已完成并强化 Save fact authority、registry/path boundary、archive import safety 和 `authority_contract`。Story 1.6 的拒绝路径不得回退这些边界，也不能让 MCP path 或 registry state 覆盖 Save SQLite facts。
- Story 1.3 完成后，`SaveManager.player_confirm()` 是普通玩家 commit gate；pending action 只有 matching session/save/platform identity 且 validation/commit 通过后才清理。
- Story 1.2 完成后，`SaveManager.player_turn()` 只能创建 query/clarification/blocked/pending-action，不提交 gameplay facts；player-safe MCP path 应继续调用这个 gate，而不是调用 low-level runtime preview/commit。
- 最近提交模式显示：`a3187b5` harden player confirm commit gate，`97aa92d` sanitize pending preflight identity，`6b8dfd8` surface authority inventory contract。Story 1.6 应沿用“先合同、再 gate、再 focused boundary tests”的模式。

### 架构合规要求

- Surface category：默认 MCP `player` profile 的 registered tools 必须全部是 `player-safe`；low-level tools 属于 `trusted low-level`，只能给 developer/trusted_gm/maintenance/admin profiles。
- Adapter 必须保持 thin wrapper：MCP 只把参数转给 `SaveManager`、`GMRuntime`、validators 和 inspection services；不要复制 player turn、validation 或 commit 业务逻辑。
- Default player profile 不得暴露或直通 `start_turn`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn`、`intent_preflight`、hidden view、maintenance mode、per-call semantic/intent/state-audit/archivist override。
- Server-level helper defaults 可以配置 internal intent helper，但这不是 per-call override，也不改变 profile 权限。`player_turn()` 可消费 passive preflight identity，但不能将 preflight 当成 proposal approval。
- `developer` profile 可以使用 low-level tools，但 hidden/GM/maintenance view 仍只给 `trusted_gm`、`maintenance`、`admin`。
- Rejected calls may write MCP audit evidence only；不得写 Save SQLite facts、pending action、pending clarification、preflight cache、registry mutation 或 Campaign Package files。
- Public results should keep structured `ok`、`errors`、`error_details` shape. If error shape changes, update docs/tests.

### 相关文件

- `rpg_engine/mcp_adapter.py`：MCP profile constants、tool names、adapter methods、method-level guards、FastMCP registration、audit sanitization、path boundary。
- `rpg_engine/surface_inventory.py`：`MCP_SURFACE_INVENTORY`、default MCP violations、surface inventory validation。
- `rpg_engine/save_manager.py`：player-safe `player_turn()` / `player_confirm()` gate；只在确认路径保持 gameplay fact authority。
- `rpg_engine/runtime.py`：low-level `start_turn()`、`query()`、`preview_from_text()`、`preview_action()`、`validate_delta()`、`commit_turn()` runtime facade；MCP player profile 不应直接暴露这些低层入口。
- `rpg_engine/preflight_cache.py`：advisory preflight state；player profile 禁止 `intent_preflight()`，但 `player_turn()` 可消费 passive preflight identity。
- `docs/mcp-contracts.md`：canonical MCP profile/tool/permission/audit contract。
- `docs/cli-contracts.md`：CLI `mcp serve` / `print-config` profile 参数合同。
- `docs/architecture.md`：player-safe chain 与 MCP profile gate 总览。
- `docs/testing-and-quality-gates.md`：MCP/default profile 和 high-risk boundary gate。
- `tests/test_mcp_adapter.py`：MCP adapter profile gate、registration、path、audit、player workflow、preflight/clarification/commit tests。
- `tests/test_surface_inventory.py`：surface taxonomy 和 default MCP tool sentinel。
- `tests/test_save_manager.py`：player turn/confirm no-mutation 和 pending-state contract，若 MCP changes touch SaveManager expectations。
- `tests/test_preflight_cache.py`：如果 player_turn passive preflight consumption 或 preflight gate 变化则追加。
- `tests/test_v1_cli.py`：如果 CLI `mcp` 参数或 print-config 输出变化则追加。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_mcp_adapter.py tests/test_surface_inventory.py
git diff --check
```

如果实现触碰 SaveManager player workflow 或 pending state：

```bash
python3 -m pytest -q tests/test_save_manager.py tests/test_mcp_adapter.py
```

如果实现触碰 preflight consumption、message-only identity 或 intent helper defaults：

```bash
python3 -m pytest -q tests/test_preflight_cache.py tests/test_mcp_adapter.py
```

如果实现触碰 CLI `mcp serve` / `print-config` 参数或 docs examples：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_mcp_adapter.py
```

若 shared runtime/validation/commit behavior changed：

```bash
python3 -m pytest -q
```

### 残余风险与边界

- 当前 server registration 层已经防止 player profile 注册低层 tools；本 story 主要补“直接 adapter method 调用也不能绕过权限门”的证据。实现时不要重写 MCP server 或改动 FastMCP dependency。
- `player_query` 和 `player_act` 当前属于 low-level/compat tools，不在默认 player profile 注册。不要把兼容 wrapper 重新放入 player profile；正常自然语言玩法入口是 `player_turn()`。
- `start_turn()` 和 `preview_from_text()` 当前可能有 player profile 直接调用测试。Story 1.6 应调整这些测试，把低层直接调用放到 developer profile，把 player profile 合法路径放到 `player_turn()`。
- `query(view="player")` 虽只读，但 canonical MCP contract 把 `query` 归为 low-level tool；default player profile 应用 `player_turn()` query result 或其他 player-safe tools，而不是 low-level `query()`。
- `health` 是 player-safe read-only tool，但不能 repair state，也不能成为 maintenance surface。
- `MCPAdapterConfig.from_values(..., ai_profile=...)` 的 server-level helper defaults 不等于 per-call override。不要把默认 helper 配置误判成 profile escalation；只拒绝 per-call override 或 low-level-only tools。
- MCP audit log 是 evidence，不是事实源；audit failure must not break MCP calls.

### 最新技术信息

无需外部 Web research。本 story 使用现有 Python stdlib、optional MCP FastMCP wrapper、pytest、SQLite temp fixtures、`AIGMMCPAdapter`、`SaveManager`、`GMRuntime` 和 `surface_inventory` patterns。不要新增运行时依赖。

## Project Structure Notes

Story 1.6 应优先修改 `mcp_adapter.py` 的 profile gate helper 和 tests；不要新增 MCP registry、不要新增数据库表、不要把 CLI handler 引入 MCP adapter。若需要共享错误形状，优先用现有 `error_dict()` / `issues_from_messages()` patterns。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/mcp-contracts.md`
- `docs/cli-contracts.md`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/surface_inventory.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/runtime.py`
- `rpg_engine/preflight_cache.py`
- `tests/test_mcp_adapter.py`
- `tests/test_surface_inventory.py`
- `tests/test_save_manager.py`
- `tests/test_preflight_cache.py`
- `tests/test_v1_cli.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Implementation Plan

- 复用现有 MCP tool constants 和 profile split，不新增并行 registry。
- 把 `player_query`、`player_act`、`start_turn`、`intent_preflight`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn` 统一收进 method-level low-level profile gate。
- 用结构化 `MCP_PROFILE_MISMATCH` 错误作为拒绝证据，并保持 audit 只写 sanitized request 和 summarized result。
- 更新 MCP/CLI 合同与 focused tests，确认 default player profile 只保留 player-safe path。

### Debug Log References

- RED: `python3 -m pytest -q tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_contract_names_every_player_profile_forbidden_low_level_tool tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_player_profile_rejects_all_low_level_adapter_methods_without_state_changes tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_developer_profile_keeps_hidden_read_gate_separate_from_low_level_gate tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_player_profile_permission_audit_is_sanitized_and_summarized tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_client_config_uses_relative_defaults_under_root` failed with 4 expected profile-gate/documentation/audit findings and 1 passing config assertion.
- GREEN: same MCP-focused command passed with 5 tests.
- MCP adapter gate: `python3 -m pytest -q tests/test_mcp_adapter.py` passed with 27 tests.
- Surface inventory gate: `python3 -m pytest -q tests/test_surface_inventory.py` passed with 19 tests and 212 subtests.
- Focused gate: `python3 -m pytest -q tests/test_mcp_adapter.py tests/test_surface_inventory.py` passed with 46 tests and 212 subtests.
- CLI config gate: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_mcp_print_config_command` passed with 1 test.
- Syntax gate: `python3 -m py_compile rpg_engine/mcp_adapter.py rpg_engine/surface_inventory.py` passed.
- Full regression: `python3 -m pytest -q` passed with 511 tests and 627 subtests.
- Diff gate: `git diff --check` passed.
- Docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/1-6-mcp-player-profile-权限门.md` passed.
- Review patch focused audit gate: `python3 -m pytest -q tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_player_profile_permission_audit_is_sanitized_and_summarized` passed with 1 test.
- Review patch focused story gate: `python3 -m pytest -q tests/test_mcp_adapter.py tests/test_surface_inventory.py` passed with 46 tests and 212 subtests.
- Review patch syntax gate: `python3 -m py_compile rpg_engine/mcp_adapter.py` passed.
- Review patch full regression: `python3 -m pytest -q` passed with 511 tests and 627 subtests.
- Review patch diff gate: `git diff --check` passed.

### Completion Notes List

- Reused the existing MCP tool constants/profile split and kept default FastMCP registration limited to `PLAYER_MCP_TOOL_NAMES`.
- Added method-level low-level profile gates for all low-level adapter methods, including direct calls to `player_query`, `player_act`, `start_turn`, `query`, and `preview_from_text`.
- Added structured `MCP_PROFILE_MISMATCH` error details with tool/profile/required profile/surface category evidence.
- Preserved `player_turn()` as the default player-safe natural-language path and moved low-level direct-call tests to developer profile where appropriate.
- Hardened MCP audit for denied player-profile low-level calls by hashing `session_key`, summarizing raw delta/proposal payloads without raw field names, and suppressing private reasoning / hidden-fact key variants.
- Updated MCP and CLI canonical contracts for player profile method-layer refusal, low-level tool list, and audit sanitization.

### File List

- `_bmad-output/implementation-artifacts/1-6-mcp-player-profile-权限门.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `rpg_engine/mcp_adapter.py`
- `tests/test_mcp_adapter.py`

## Change Log

- 2026-07-07: Implemented MCP player profile method-level permission gate, structured mismatch evidence, denied-call audit sanitization, focused boundary tests, and MCP/CLI contract updates; status set to review.
- 2026-07-07: Code review patch suppressed sensitive audit key-name leakage and marked Story 1.6 done.
