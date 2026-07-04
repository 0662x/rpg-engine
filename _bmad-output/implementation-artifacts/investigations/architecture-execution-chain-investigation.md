# Investigation: RPG Engine Architecture and Execution Chain

## Hand-off Brief

1. **What happened.** 用户担心 RPG Engine 是在缺少规范时由 AI 自发堆出来的，可能存在架构和执行链路问题；调查把这个前提当作假设验证，而不是事实接受。
2. **Where the case stands.** 本案已结论化：普通玩家链路有明确 pending/confirm/commit 守卫；legacy/admin 与 low-level 写入是有意维护/受信面；projection/outbox 是提交后可靠性面；AI intent/preflight 的分散所有权是最主要架构债。
3. **What's needed next.** 最高价值下一步是跑 `gds-game-architecture`，围绕 `IntentCoordinator`、surface taxonomy、projection consistency 产出一条可执行的架构 spine。

## Case Info

| Field            | Value |
| ---------------- | ----- |
| Ticket           | N/A |
| Date opened      | 2026-07-04 |
| Status           | Concluded |
| System           | Darwin 25.5.0 arm64; Python 3.13.9 observed in shell; project targets Python 3.11+ |
| Evidence sources | User description, `docs/project-context.md`, source-code scans, targeted source snippets, pytest collection, focused pytest run, py_compile, `git diff --check`, git log, BMAD scan outputs, reports inventory |

## Problem Statement

User-reported description: "现在的引擎设计是ai在没有规范的情况下自己写的，有更多的问题。我现在应该梳理一下整个架构和执行链路" followed by explicit invocation of `gds-investigate`.

Initial claim: the RPG Engine architecture and execution chain may contain systemic issues because AI generated significant design/code before a stable specification existed.

## Evidence Inventory

| Source | Status | Notes |
| ------ | ------ | ----- |
| User description | Available | Free-text hypothesis captured above; not treated as fact until independently verified. |
| Project contract | Available | `docs/project-context.md:11` through `docs/project-context.md:20` define the engine as local-first AIGM kernel and state `AI proposes. Kernel verifies. Player confirms. Engine commits.` |
| Non-negotiable boundaries | Available | `docs/project-context.md:31` through `docs/project-context.md:44` define SQLite authority, AI trust boundaries, SaveManager pending/confirm gates, adapter thinness, prewarm advisory scope, hidden-content boundaries, and package separation. |
| Canonical architecture doc | Available | `docs/architecture.md:7` through `docs/architecture.md:37` describe player-safe, low-level runtime, platform sidecar, and prewarm chains; `docs/architecture.md:39` through `docs/architecture.md:52` describe the player-safe chain. |
| BMAD rescan outputs | Available | `_bmad-output/document-project-completion-summary.md:10` through `_bmad-output/document-project-completion-summary.md:12` record completed strict `gds-document-project` full rescan; `_bmad-output/document-project-completion-summary.md:42` through `_bmad-output/document-project-completion-summary.md:49` record known open risks. |
| BMAD output index | Available | `_bmad-output/index.md:13` through `_bmad-output/index.md:18` say strict GDS rescan outputs are brownfield inputs but current code and canonical docs win on conflicts; `_bmad-output/index.md:53` through `_bmad-output/index.md:59` showed no visible implementation/test artifacts before this case. |
| Source-code entry points | Available for target trace | Public/semi-public sources include `rpg_engine/cli.py`, `rpg_engine/cli_v1.py`, `rpg_engine/mcp_adapter.py`, `rpg_engine/platform_sidecar.py`, `rpg_engine/platform_prewarm.py`, `rpg_engine/runtime.py`, and `rpg_engine/save_manager.py`. Outcome 4 traced the unresolved high-risk surfaces rather than a full whole-repo caller graph. |
| SaveManager player-safe path | Available for perimeter | `rpg_engine/save_manager.py:421` creates `GMRuntime`; `rpg_engine/save_manager.py:452` calls `runtime.act`; `rpg_engine/save_manager.py:465` through `rpg_engine/save_manager.py:479` write pending action; `rpg_engine/save_manager.py:557` through `rpg_engine/save_manager.py:599` validate pending state and call `runtime.commit_turn`. |
| Runtime path | Available for perimeter | `rpg_engine/runtime.py:631` through `rpg_engine/runtime.py:781` show preflight; `rpg_engine/runtime.py:1083` through `rpg_engine/runtime.py:1162` show text preview routing; `rpg_engine/runtime.py:1399` through `rpg_engine/runtime.py:1468` show validation, approved proposal requirement, and commit service call. |
| MCP profile and tool perimeter | Available for perimeter | `rpg_engine/mcp_adapter.py:1151` through `rpg_engine/mcp_adapter.py:1207` show `player_turn`/`player_confirm` registration and low-level profile gating for `player_act`; `rpg_engine/mcp_adapter.py:1219` through `rpg_engine/mcp_adapter.py:1422` show low-level gated preflight/start/preview/validate/commit tools. |
| Platform sidecar perimeter | Available for perimeter | `rpg_engine/platform_sidecar.py:255` through `rpg_engine/platform_sidecar.py:310` gate, prewarm, and call `SaveManager.player_turn`; `rpg_engine/platform_sidecar.py:312` through `rpg_engine/platform_sidecar.py:343` gate and call `SaveManager.player_confirm`; `rpg_engine/platform_sidecar.py:552` through `rpg_engine/platform_sidecar.py:591` check pending save/platform/session/actor conflicts. |
| Tests | Available for key boundary subset | `python3 -m pytest --collect-only -q tests/test_save_manager.py tests/test_runtime.py tests/test_mcp_adapter.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_ai_intent.py tests/test_v1_cli.py` collected 158 tests in 0.12s. Focused Outcome 3 run covering MCP profile gates, SaveManager pending/confirm, platform gate, Runtime commit guards, surface inventory, and V1 play commit passed: 12 tests in 1.36s. |
| Legacy/admin CLI trace | Available | `rpg_engine/cli.py:839` through `rpg_engine/cli.py:957` create/review/apply proposals and apply content deltas after approval; `rpg_engine/cli.py:1510` through `rpg_engine/cli.py:1538` validate and commit an admin/legacy turn delta; `rpg_engine/cli.py:1560` through `rpg_engine/cli.py:1607` validates/applies content delta with backup/projection refresh. |
| Commit/projection/outbox trace | Available | `rpg_engine/commit_service.py:91` through `rpg_engine/commit_service.py:136`, `rpg_engine/save.py:36` through `rpg_engine/save.py:159`, `rpg_engine/unit_of_work.py:34` through `rpg_engine/unit_of_work.py:102`, `rpg_engine/projections.py:130` through `rpg_engine/projections.py:180`, and `rpg_engine/projection_service.py:184` through `rpg_engine/projection_service.py:404` show validation, DB commit, outbox processing, projection reporting, and failed projection state marking. |
| AI intent/preflight trace | Available | `rpg_engine/runtime.py:631` through `rpg_engine/runtime.py:781`, `rpg_engine/intent_router.py:208` through `rpg_engine/intent_router.py:316`, `rpg_engine/ai_intent/router.py:109` through `rpg_engine/ai_intent/router.py:276`, `rpg_engine/preflight_cache.py:254` through `rpg_engine/preflight_cache.py:500`, `rpg_engine/context_builder.py:196` through `rpg_engine/context_builder.py:310`, `rpg_engine/platform_prewarm.py:441` through `rpg_engine/platform_prewarm.py:461`, and `rpg_engine/mcp_adapter.py:455` through `rpg_engine/mcp_adapter.py:525` show distributed ownership and cache identity checks. |
| Outcome 4 focused tests | Available | `python3 -m pytest -q tests/test_projection_service.py::ProjectionServiceTests::test_commit_result_carries_projection_report tests/test_projection_service.py::ProjectionServiceTests::test_commit_result_reports_projection_failure_without_rollback tests/test_preflight_cache.py::PreflightCacheTests::test_preflight_cache_ready_hit_is_single_use tests/test_preflight_cache.py::PreflightCacheTests::test_message_only_preflight_consumes_by_message_with_later_external_candidate tests/test_runtime.py::GMRuntimeTests::test_intent_preflight_cache_reuses_internal_review_without_direct_key tests/test_runtime.py::GMRuntimeTests::test_message_only_preflight_cache_reuses_internal_review_without_preflight_id tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_intent_preflight_can_be_consumed_by_preview tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_message_only_preflight_can_be_consumed_without_preflight_id` returned `8 passed in 0.44s`. |
| Static analysis / syntax | Available | `python3 -m py_compile rpg_engine/save_manager.py rpg_engine/runtime.py rpg_engine/mcp_adapter.py rpg_engine/platform_sidecar.py rpg_engine/platform_prewarm.py rpg_engine/cli.py` passed. `git diff --check` passed. |
| Version control | Available | Recent history includes `83c84c3 docs: complete GDS document project rescan`, `130c968 docs: require strict BMAD skill activation`, and `c34706b feat: harden player pending session confirmation`. Full causal history is not yet analyzed. |
| Reports / diagnostic archives | Partial | `reports/` contains dated analysis/probe reports for action/query recognition, AI consensus intent, prewarm/platform simulation, current-save probes, and stress reports. These are contextual artifacts, not live incident logs. |
| Issue tracker | Missing | No issue tracker integration or ticket ID was supplied. |
| Runtime logs / crash reports | Missing | No concrete failure log, crash report, or production incident was supplied. This remains an exploration case. |

## Investigation Backlog

| # | Path to Explore | Priority | Status | Notes |
| - | --------------- | -------- | ------ | ----- |
| 1 | Map public entry points from CLI, MCP, platform sidecar, and package/runtime APIs into kernel services | High | Done for target trace | Outcome 3 confirmed `player` CLI, MCP player-safe tools, and platform sidecar delegate through SaveManager. Outcome 4 classified low-level and legacy/admin surfaces as separate trusted/maintenance paths. |
| 2 | Trace `SaveManager.player_turn()` and `SaveManager.player_confirm()` side effects and storage writes | High | Done for target trace | Pending action, confirm gate, Runtime validation, commit service, UnitOfWork, projection, and outbox were traced. |
| 3 | Trace AI intent / preflight / candidate preparation ownership across Runtime, ContextBuilder, MCP, SaveManager, and CLI | High | Done for target trace | Ownership is distributed across Runtime, intent router, AIIntentRouter, preflight cache, context builder, MCP, and platform prewarm. This is architecture debt, not a confirmed correctness bug. |
| 4 | Compare canonical docs and current source for contradictions | High | Done for current canonical docs | Current CLI/MCP/architecture/project-context docs align with traced player-safe, low-level, preflight, and IntentCoordinator-not-yet-implemented boundaries. |
| 5 | Inventory tests that prove trust, visibility, pending/confirm, and adapter-thinness boundaries | Medium | Done for key boundary subset | Focused tests passed for MCP profile gate, player profile rejections, pending/confirm, platform gate, Runtime commit guard, and surface inventory. Full suite not run. |
| 6 | Check BMAD output and residual-risk backlog for known issues that overlap architecture chain risks | Medium | Open | BMAD outputs and reports inventoried; backlog-to-code mapping remains. |
| 7 | Inspect CLI command handlers for whether player-safe commands use SaveManager or bypass via Runtime low-level paths | High | Done for target trace | V1 `player` uses SaveManager; V1 `play` intentionally uses Runtime low-level primitives; legacy/admin `cli.py` contains maintenance/proposal/content/admin save commands, not ordinary player commands. |
| 8 | Inspect commit service / unit of work / write guard / projection path | High | Done for target trace | Commit service, write guard, UnitOfWork, projection refresh, outbox, and final artifact behavior are mapped. |

## Timeline of Events

| Time | Event | Source | Confidence |
| ---- | ----- | ------ | ---------- |
| 2026-07-04 | `gds-document-project` full rescan completed and produced BMAD scan outputs. | `_bmad-output/document-project-completion-summary.md:3` through `_bmad-output/document-project-completion-summary.md:12` | Confirmed |
| 2026-07-04 | User asked to investigate the engine architecture and execution chain because AI-generated design may contain broader problems. | Current conversation | Confirmed |
| 2026-07-04 | `gds-investigate` case initialized. | This case file | Confirmed |
| 2026-07-04 | Outcome 2 source/test/static/git evidence perimeter was mapped. | This case file | Confirmed |
| 2026-07-04 | Outcome 3 focused boundary tests passed: 12 tests in 1.36s. | `python3 -m pytest -q ...` focused command output | Confirmed |
| 2026-07-04 | Outcome 4 targeted source trace completed for legacy/admin CLI, commit/projection/outbox, and AI intent/preflight ownership. | Source snippets listed in Evidence Inventory and Source Code Trace | Confirmed |
| 2026-07-04 | Outcome 4 focused projection/preflight tests passed: 8 tests in 0.44s. | `python3 -m pytest -q ...` focused command output | Confirmed |

## Confirmed Findings

### Finding 1: The project has an explicit execution-boundary contract.

**Evidence:** `docs/project-context.md:11`, `docs/project-context.md:15`, `docs/project-context.md:18`

**Detail:** The canonical context defines RPG Engine as a local-first AIGM kernel responsible for factual state, rules, validation, queryable context, and safe public entries; it also states the core boundary as "AI proposes. Kernel verifies. Player confirms. Engine commits."

### Finding 2: The codebase has multiple public and semi-public execution entry points that must be reconciled with that contract.

**Evidence:** `rpg_engine/cli.py:183`, `rpg_engine/mcp_adapter.py:337`, `rpg_engine/mcp_adapter.py:438`, `rpg_engine/mcp_adapter.py:1159`, `rpg_engine/mcp_adapter.py:1205`, `rpg_engine/mcp_adapter.py:1661`, `rpg_engine/platform_sidecar.py:312`, `rpg_engine/runtime.py:620`, `rpg_engine/save_manager.py:40`, `rpg_engine/save_manager.py:375`, `rpg_engine/save_manager.py:557`

**Detail:** Initial symbol search confirms there are CLI, MCP, platform, runtime, and save-manager surfaces involved in player turn/confirm behavior. Their full caller chains and write authority are not yet mapped.

### Finding 3: The player-safe SaveManager path writes pending state before confirmation and commits only through `player_confirm`.

**Evidence:** `rpg_engine/save_manager.py:452`, `rpg_engine/save_manager.py:459`, `rpg_engine/save_manager.py:465`, `rpg_engine/save_manager.py:510`, `rpg_engine/save_manager.py:557`, `rpg_engine/save_manager.py:597`, `rpg_engine/save_manager.py:598`

**Detail:** `player_turn()` calls `runtime.act()`, computes readiness, writes pending action data when ready, and returns `saved: False`. `player_confirm()` validates pending state and session identity before calling `runtime.commit_turn()`.

### Finding 4: Runtime separates preflight, preview/routing, validation, and commit entry points.

**Evidence:** `rpg_engine/runtime.py:631`, `rpg_engine/runtime.py:701`, `rpg_engine/runtime.py:719`, `rpg_engine/runtime.py:1083`, `rpg_engine/runtime.py:1147`, `rpg_engine/runtime.py:1162`, `rpg_engine/runtime.py:1399`, `rpg_engine/runtime.py:1424`, `rpg_engine/runtime.py:1452`, `rpg_engine/runtime.py:1454`

**Detail:** Runtime has a preflight path that creates pending intent preflight records and collects internal review, a preview path that routes text into an intent and previews it, and a commit path that validates, requires an approved proposal, and delegates to commit service.

### Finding 5: MCP exposes player-safe tools broadly and gates lower-level tools behind low-level profiles.

**Evidence:** `rpg_engine/mcp_adapter.py:1151`, `rpg_engine/mcp_adapter.py:1158`, `rpg_engine/mcp_adapter.py:1181`, `rpg_engine/mcp_adapter.py:1204`, `rpg_engine/mcp_adapter.py:1219`, `rpg_engine/mcp_adapter.py:1328`, `rpg_engine/mcp_adapter.py:1391`, `rpg_engine/mcp_adapter.py:1401`

**Detail:** `player_turn` and `player_confirm` are registered as standard tools, while compatibility/low-level act, preflight, start, preview, validate, and commit tools are decorated or scoped as low-level.

### Finding 6: Platform sidecar performs platform/session gating and then delegates player action/confirm to SaveManager.

**Evidence:** `rpg_engine/platform_sidecar.py:259`, `rpg_engine/platform_sidecar.py:269`, `rpg_engine/platform_sidecar.py:280`, `rpg_engine/platform_sidecar.py:282`, `rpg_engine/platform_sidecar.py:312`, `rpg_engine/platform_sidecar.py:316`, `rpg_engine/platform_sidecar.py:327`, `rpg_engine/platform_sidecar.py:552`

**Detail:** The sidecar checks entry gates and pending conflicts, optionally runs prewarm handling, then calls `SaveManager.player_turn()` or `SaveManager.player_confirm()` with bound save path and platform identity.

### Finding 7: V1 CLI separates ordinary player commands from low-level runtime play commands.

**Evidence:** `rpg_engine/cli_v1.py:315`, `rpg_engine/cli_v1.py:377`, `rpg_engine/cli_v1.py:493`, `rpg_engine/cli_v1.py:509`, `rpg_engine/cli_v1.py:526`, `rpg_engine/cli_v1.py:831`, `rpg_engine/cli_v1.py:969`, `rpg_engine/cli_v1.py:1047`, `rpg_engine/cli_v1.py:1072`, `rpg_engine/cli_v1.py:1083`

**Detail:** `play` commands call `GMRuntime` primitives directly, including low-level commit with a proposal. `player` commands instantiate `SaveManager` and route natural-language turn/confirm through `manager.player_turn()` and `manager.player_confirm()`.

### Finding 8: Commit has layered guards after `player_confirm`.

**Evidence:** `rpg_engine/runtime.py:1421`, `rpg_engine/runtime.py:1424`, `rpg_engine/runtime.py:1452`, `rpg_engine/commit_service.py:91`, `rpg_engine/commit_service.py:93`, `rpg_engine/commit_service.py:95`, `rpg_engine/commit_service.py:101`, `rpg_engine/commit_service.py:189`, `rpg_engine/commit_service.py:193`, `rpg_engine/write_guard.py:57`, `rpg_engine/unit_of_work.py:34`, `rpg_engine/unit_of_work.py:90`

**Detail:** Commit normalizes and validates the TurnProposal, checks validation profile and proposal identity, requires write guards, rejects mismatched delta digest, checks for duplicate command commits, uses `begin immediate`, and commits/rolls back through UnitOfWork.

### Finding 9: Key boundary tests pass in the current workspace.

**Evidence:** Focused command `python3 -m pytest -q tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_server_registers_player_surface_by_profile ... tests/test_v1_cli.py::V1CliTests::test_play_start_query_preview_and_commit_commands` returned `12 passed in 1.36s`.

**Detail:** The passing subset covers MCP profile tool registration, player-profile low-level/hidden/AI override rejection, MCP player pending confirmation, SaveManager pending session combinations, platform inactive/actor/bound-save gates, Runtime approved-proposal and state-audit guards, MCP surface write-mode inventory, and V1 low-level play preview/commit flow.

### Finding 10: Canonical CLI and MCP docs match the traced high-level boundary.

**Evidence:** `docs/cli-contracts.md:21`, `docs/cli-contracts.md:33`, `docs/cli-contracts.md:35`, `docs/cli-contracts.md:70`, `docs/cli-contracts.md:71`, `docs/mcp-contracts.md:25`, `docs/mcp-contracts.md:36`, `docs/mcp-contracts.md:37`, `docs/mcp-contracts.md:43`, `docs/mcp-contracts.md:115`

**Detail:** CLI docs name `player turn -> player confirm` as ordinary path and classify `play *` as developer/trusted-gm low-level tooling. MCP docs state `player` profile cannot register low-level preview/validate/commit/preflight tools and that `commit_turn` is trusted low-level write.

### Finding 11: Legacy/admin CLI contains maintenance write surfaces outside the ordinary player path.

**Evidence:** `rpg_engine/cli.py:839`, `rpg_engine/cli.py:851`, `rpg_engine/cli.py:896`, `rpg_engine/cli.py:936`, `rpg_engine/cli.py:947`, `rpg_engine/cli.py:1510`, `rpg_engine/cli.py:1514`, `rpg_engine/cli.py:1529`, `rpg_engine/cli.py:1560`, `rpg_engine/cli.py:1573`, `rpg_engine/cli.py:1599`, `rpg_engine/cli.py:1601`

**Detail:** The legacy/admin CLI can create and review proposals, apply approved content deltas, validate and commit an admin/legacy turn delta, and apply content deltas after validation, backup, and projection refresh. These commands are separate from the V1 player-safe `player turn -> player confirm` chain.

### Finding 12: The commit chain commits SQLite first, then refreshes/report projections and outbox artifacts.

**Evidence:** `rpg_engine/commit_service.py:91`, `rpg_engine/commit_service.py:101`, `rpg_engine/commit_service.py:111`, `rpg_engine/commit_service.py:126`, `rpg_engine/commit_service.py:131`, `rpg_engine/save.py:36`, `rpg_engine/save.py:47`, `rpg_engine/save.py:153`, `rpg_engine/save.py:159`, `rpg_engine/unit_of_work.py:34`, `rpg_engine/unit_of_work.py:90`, `rpg_engine/projections.py:130`, `rpg_engine/projections.py:144`, `rpg_engine/projections.py:164`, `rpg_engine/projections.py:176`, `rpg_engine/projection_service.py:184`, `rpg_engine/projection_service.py:238`, `rpg_engine/projection_service.py:267`, `rpg_engine/projection_service.py:351`

**Detail:** `commit_turn_delta()` checks validation profile and digest, writes through `save_turn_delta()` and `UnitOfWork`, commits the DB transaction, then runs `ProjectionService.refresh()` under `caller_committed_required`. Outbox and projection failures are recorded in projection state/report rather than treated as the same atomic unit as the SQLite fact commit.

### Finding 13: Preflight cache has concrete identity, status, and single-use protections.

**Evidence:** `rpg_engine/runtime.py:701`, `rpg_engine/runtime.py:718`, `rpg_engine/runtime.py:734`, `rpg_engine/preflight_cache.py:254`, `rpg_engine/preflight_cache.py:295`, `rpg_engine/preflight_cache.py:316`, `rpg_engine/preflight_cache.py:319`, `rpg_engine/preflight_cache.py:386`, `rpg_engine/preflight_cache.py:427`, `rpg_engine/preflight_cache.py:457`, `rpg_engine/preflight_cache.py:463`, `rpg_engine/preflight_cache.py:490`, `tests/test_preflight_cache.py:54`, `tests/test_runtime.py:1424`, `tests/test_runtime.py:1643`, `tests/test_mcp_adapter.py:551`, `tests/test_mcp_adapter.py:631`

**Detail:** Runtime creates pending preflight records and marks ready/failed; consumption validates text hash, identity, context, provider/model/backend, message/platform/session when applicable, expiration/status, and transitions ready records to used. Focused Outcome 4 tests passed for single-use and message-only consumption through Runtime and MCP.

### Finding 14: AI intent/preflight ownership is distributed, and the missing `IntentCoordinator` is documented.

**Evidence:** `docs/project-context.md:69`, `docs/project-context.md:77`, `docs/architecture.md:83`, `docs/architecture.md:87`, `docs/architecture.md:89`, `docs/architecture.md:95`, `rpg_engine/runtime.py:631`, `rpg_engine/intent_router.py:208`, `rpg_engine/intent_router.py:295`, `rpg_engine/ai_intent/router.py:109`, `rpg_engine/preflight_cache.py:115`, `rpg_engine/context_builder.py:196`, `rpg_engine/context_builder.py:284`, `rpg_engine/platform_prewarm.py:441`, `rpg_engine/mcp_adapter.py:455`

**Detail:** Candidate preparation, request metadata, AI consensus routing, preflight production/consumption, context classification, MCP preflight exposure, and platform prewarm are split across several modules. Canonical project context explicitly says this does not mean a future `IntentCoordinator` has been implemented.

## Deduced Conclusions

### Deduction 1: This investigation should remain architecture-chain exploration rather than a narrow bug hunt.

**Based on:** Confirmed Finding 1 and Confirmed Finding 2.

**Reasoning:** The user supplied a systemic concern and no single error message, while confirmed evidence shows a contract spanning multiple modules and multiple execution entry points.

**Conclusion:** The next step is disciplined reasoning over the mapped chains before forming root-cause claims.

### Deduction 2: The perimeter evidence currently supports the existence of a designed player-safe path, but not yet its full correctness.

**Based on:** Confirmed Findings 3, 4, 5, and 6.

**Reasoning:** SaveManager, Runtime, MCP, and platform sidecar all show recognizable gate/delegate/preview/confirm/commit structure. However, Outcome 2 did not yet trace every CLI path, low-level MCP profile rule, commit service side effect, hidden-content boundary, or test assertion.

**Conclusion:** Adapter duplication or boundary drift remains an open hypothesis, not yet confirmed or refuted.

### Deduction 3: The ordinary player-safe path is not currently behaving like an unguarded AI-written bypass.

**Based on:** Confirmed Findings 3, 5, 6, 7, 8, 9, and 10.

**Reasoning:** Player-facing CLI, MCP player tools, and platform sidecar all route through SaveManager or profile/platform gates. SaveManager writes pending state, hides internal delta/proposal data from player results, and only commits through confirmation. Runtime and commit service require approved proposal validation before final write. Focused tests pass for these boundaries.

**Conclusion:** The user premise remains useful as an investigation trigger, but the specific claim "ordinary player path is likely unguarded because AI wrote it without spec" is not supported by the current evidence.

### Deduction 4: Low-level paths are intentional architecture, not automatically defects.

**Based on:** Confirmed Findings 5, 7, 8, 9, and 10.

**Reasoning:** Both source and docs explicitly expose low-level `play` and MCP developer/trusted tools. Tests verify player profile exclusions and surface write modes. These paths still require audit because they bypass `SaveManager.player_confirm` by design, but they are constrained by Runtime validation, proposal checks, and profile/documentation gates.

**Conclusion:** The risk is not "low-level paths exist"; the risk is whether any ordinary-player or untrusted integration can reach them, or whether scripts/docs encourage ordinary play to use them.

### Deduction 5: Remaining systemic risk is concentrated in surfaces not fully traced in Outcome 3.

**Based on:** Missing Evidence and Backlog items 3, 4, 6, 7, and 8.

**Reasoning:** Outcome 3 did not complete legacy/admin CLI review, full projection/outbox artifact trace, AI intent/preflight/cache ownership, or historical report-to-code mapping.

**Conclusion:** The next source trace should be narrower and deeper, not another broad scan.

### Deduction 6: Legacy/admin write commands are not evidence of an ordinary player bypass, but they require explicit surface taxonomy.

**Based on:** Confirmed Findings 7, 10, and 11.

**Reasoning:** The legacy/admin handlers write state or content only through admin/maintenance/proposal paths, not through V1 player-safe commands. However, these commands do bypass `SaveManager.player_confirm` by purpose, so scripts and docs must never present them as normal play entry points.

**Conclusion:** Treat legacy/admin CLI as a maintenance surface that needs documentation and test inventory, not as an immediate player-chain defect.

### Deduction 7: Projection/outbox behavior is a post-commit reliability concern, not a pre-commit validation bypass.

**Based on:** Confirmed Findings 8, 12, and Outcome 4 focused tests.

**Reasoning:** Fact writes are guarded before `save_turn_delta()`. Projections and event JSONL are refreshed after the DB commit and report dirty/failed state when artifacts cannot be written. The test `test_commit_result_reports_projection_failure_without_rollback` supports the diagnosis that projection failure is reported without rolling back the DB fact commit.

**Conclusion:** Architecture docs should make this consistency model obvious: SQLite is authoritative, projections are repairable/read-model artifacts, and failed projection state must be operationally visible.

### Deduction 8: The clearest architecture-debt target is intent/preflight coordination, not the player confirm gate.

**Based on:** Confirmed Findings 13 and 14.

**Reasoning:** Preflight is protected by identity and one-use checks, but the chain's ownership is spread across Runtime, intent routing, AI routing, cache, context builder, platform prewarm, and MCP adapter. The project context already names `IntentCoordinator` as future work.

**Conclusion:** A future architecture story should consolidate or document this coordination boundary before broad feature work in AI intent/preflight.

## Hypothesized Paths

### Hypothesis 1: AI-generated implementation may have duplicated or blurred business logic across CLI, MCP, platform, Runtime, and SaveManager.

**Status:** Partially refuted; architecture debt remains

**Theory:** Because the project has multiple public execution surfaces and a strict "adapters are thin" contract, there may be duplicate decision logic or inconsistent enforcement outside kernel services.

**Supporting indicators:** The project context explicitly warns that MCP, CLI, and platform sidecar must call kernel services rather than copy business logic; initial symbol scan confirms several adapter-facing turn/confirm entry points.

**Would confirm:** Caller-chain evidence showing policy, validation, write, hidden-content, or commit decisions implemented independently in adapters.

**Would refute:** Caller-chain evidence showing adapters consistently delegate to a single kernel path with tests covering profile, visibility, and commit boundaries.

**Resolution:** Refuted for the ordinary player-safe perimeter and for the traced low-level/MCP profile separation. Legacy/admin surfaces are maintenance paths, not player bypasses. The remaining blurred-ownership concern is concentrated in AI intent/preflight coordination.

### Hypothesis 2: Current documentation may mix intended architecture, historical artifacts, and actual behavior.

**Status:** Mostly refuted for current canonical docs; historical artifacts not fully audited

**Theory:** Existing docs and BMAD outputs may include useful but non-authoritative descriptions that need verification against source code.

**Supporting indicators:** The project context and BMAD output index distinguish canonical docs from historical reports and warn that current code/canonical docs override old BMAD-style documents.

**Would confirm:** Contradictions between canonical docs, BMAD scan outputs, historical reports, and source-code behavior.

**Would refute:** A clean trace where current source, canonical docs, tests, and BMAD outputs align on ownership and execution order.

**Resolution:** Refuted for current project-context, architecture, CLI, and MCP contracts relevant to player-safe, low-level, preflight, and IntentCoordinator-not-yet-implemented boundaries. Historical reports and old scripts remain contextual rather than authoritative.

### Hypothesis 3: Low-level trusted/developer paths may be legitimate but increase audit burden because they can call Runtime primitives directly.

**Status:** Confirmed

**Theory:** MCP low-level tools expose `intent_preflight`, `start_turn`, `preview_from_text`, `validate_delta`, and `commit_turn` for trusted profiles. This may be intended architecture, but it requires strong profile tests and docs to prevent accidental player exposure.

**Supporting indicators:** `rpg_engine/mcp_adapter.py:1219` through `rpg_engine/mcp_adapter.py:1422` expose low-level tools behind low-level registration.

**Would confirm:** Missing or weak profile tests, or CLI/platform paths that expose low-level commit behavior to ordinary player mode.

**Would refute:** Tests and docs proving ordinary player profiles cannot access low-level write tools and that CLI commands clearly separate player-safe vs trusted/developer flows.

**Resolution:** Confirmed as an architecture property, not as a defect. Focused tests show player profile exclusion and rejection of low-level/hidden/override calls; broader audit burden remains for documentation, scripts, and non-MCP low-level surfaces.

### Hypothesis 4: The ordinary player chain has a supported pending-confirm-commit boundary.

**Status:** Confirmed

**Theory:** Standard player play should produce a pending action, hide internal delta/proposal details, require `session_id`, validate pending identity, and commit only after confirmation.

**Supporting indicators:** SaveManager code, MCP player workflow tests, SaveManager pending-session tests, Runtime commit guard tests, and CLI/MCP docs all point to this chain.

**Would confirm:** Passing tests covering hidden internal data, pending action session id, platform/session/actor mismatch rejection, approved proposal requirement, and commit state advance only after confirmation.

**Would refute:** A player-safe CLI/MCP/platform path that writes gameplay facts without `player_confirm`, returns raw delta/proposal to ordinary player output, or bypasses approved proposal validation.

**Resolution:** Confirmed for the focused perimeter by `12 passed in 1.36s`; broader paths remain outside this hypothesis.

### Hypothesis 5: AI intent/preflight needs an explicit coordinator or equivalent architecture boundary.

**Status:** Confirmed as architecture debt, not as a correctness bug

**Theory:** The current implementation has enough guards to work, but its ownership is too distributed for a high-risk AI boundary.

**Supporting indicators:** `docs/project-context.md:77` says `IntentCoordinator` is not implemented; `docs/architecture.md:83` through `docs/architecture.md:104` lists several AI intent/preflight modules; source trace shows Runtime, intent router, AIIntentRouter, preflight cache, context builder, MCP, and platform prewarm each own part of the chain.

**Would confirm:** Source and docs showing no single coordination object or package boundary around candidate preparation, preflight identity, AI consensus, and downstream proposal provenance.

**Would refute:** A central coordinator already owning those responsibilities with adapters calling into it and tests proving the single path.

**Resolution:** Confirmed as the highest-value architecture follow-up from this investigation.

## Missing Evidence

| Gap | Impact | How to Obtain |
| --- | ------ | ------------- |
| Full whole-repo caller graph | Helpful for total assurance, but not required for this case's target diagnosis | Future architecture work can run a whole-repo graph; Outcome 4 target trace is complete. |
| Commit service / UnitOfWork / WriteGuard side effects | Target trace complete; deeper artifact-specific repair operations still not exhaustively audited | Future reliability story can inventory all projection repair commands and operational checks. |
| Full test assertion map | Required for complete confidence across hidden visibility, preflight identity, and legacy/admin boundaries | Expand from focused 12-test subset to categorized test inventory or targeted suites. |
| CLI command path mapping | Target write surfaces are mapped; exhaustive legacy command documentation still pending | Future docs/story can classify every `rpg_engine/cli.py` command into read-only, projection repair, content maintenance, proposal, or trusted write. |
| Issue tracker / concrete incident logs | Would allow symptom-driven root cause analysis | User would need to provide ticket/logs; absent for this exploration. |
| Version-history causal chain | Helps determine whether AI-generated drift was introduced or later corrected | Inspect commits around `c34706b` and AI intent/platform hardening reports. |

## Source Code Trace

| Area | Origin | Trigger | Condition | Related files | Diagnosis |
| ---- | ------ | ------- | --------- | ------------- | --------- |
| Exploration case | User concern, no single stack trace | Explicit `gds-investigate` request after user stated need to梳理整个架构和执行链路 | Architecture may have been generated before stable spec | `docs/project-context.md`, `docs/architecture.md`, `_bmad-output/*`, `reports/*` | Treat as architecture-chain diagnosis, not a symptom-specific bug. |
| Ordinary player-safe chain | CLI/MCP/platform player action | Player natural-language turn followed by confirmation | Pending action exists and session/platform/actor identity matches | `rpg_engine/save_manager.py`, `rpg_engine/runtime.py`, `rpg_engine/commit_service.py`, `rpg_engine/mcp_adapter.py`, `rpg_engine/platform_sidecar.py`, `rpg_engine/cli_v1.py` | Supported by source/docs/tests; no unguarded player bypass confirmed. |
| Low-level/trusted runtime chain | Developer/trusted `play` or MCP low-level tools | Direct preview/validate/commit/preflight tooling | Low-level profile or developer/trusted command use; commit requires validation/proposal | `rpg_engine/cli_v1.py`, `rpg_engine/mcp_adapter.py`, `rpg_engine/runtime.py`, `docs/cli-contracts.md`, `docs/mcp-contracts.md` | Intentional architecture surface; audit burden is profile/docs/tests. |
| Legacy/admin maintenance chain | Legacy `rpg_engine/cli.py` commands | Proposal create/review/apply, admin/legacy save-turn, apply content delta | Operator invokes maintenance command; backup/proposal/projection behavior varies by command | `rpg_engine/cli.py`, content/proposal modules, projection service | Maintenance write surface exists; not ordinary player path. Needs taxonomy and script discipline. |
| Commit/write chain | Approved proposal or admin/legacy validated delta | `commit_turn_delta()` / `save_turn_delta()` | Validation profile allowed, digest matches, write guard and UnitOfWork pass | `rpg_engine/commit_service.py`, `rpg_engine/save.py`, `rpg_engine/unit_of_work.py`, `rpg_engine/write_guard.py` | Guarded before DB write; SQLite remains authority. |
| Projection/outbox chain | Post-commit artifact/read-model refresh | UnitOfWork finalizes outbox; ProjectionService refreshes snapshots/cards/etc. | DB commit already happened; projection tables exist; artifacts may fail independently | `rpg_engine/projections.py`, `rpg_engine/projection_service.py`, `rpg_engine/commit_service.py` | Reliability/read-model consistency concern; failed artifacts are reported/repairable, not fact authority. |
| AI intent/preflight chain | Advisory internal intent review and consensus routing | Platform prewarm or low-level preflight, later preview/action consumes cache | Identity, text hash, context, provider/model/backend, platform/session/message, status and TTL must match | `rpg_engine/runtime.py`, `rpg_engine/intent_router.py`, `rpg_engine/ai_intent/router.py`, `rpg_engine/preflight_cache.py`, `rpg_engine/context_builder.py`, `rpg_engine/platform_prewarm.py`, `rpg_engine/mcp_adapter.py` | Guards exist and focused tests pass; ownership remains distributed and should be consolidated/documented. |

## Final Conclusion

**Confidence:** Medium

本次调查没有确认“普通玩家路径因为 AI 写作而失守”的缺陷。相反，源码、规范文档和 focused tests 一起支持 `player turn -> pending action -> player confirm -> runtime commit` 这条主链。

真正需要处理的是架构层面的三件事：第一，legacy/admin 与 low-level 写入面需要明确分类，避免脚本或文档把维护入口误当普通游玩入口；第二，projection/outbox 是 SQLite 提交后的可修复读模型/证据链，可靠性语义需要被更明确地写入架构；第三，AI intent/preflight 已有 identity/status/single-use 守卫，但职责分散在 Runtime、intent router、AIIntentRouter、preflight cache、context builder、MCP 和 platform prewarm 之间，`IntentCoordinator` 或等价边界应成为下一轮设计目标。

置信度为 Medium：对已追踪的目标链路有直接源码与测试证据；但没有做全仓 caller graph、历史报告逐条审计或版本因果考古，所以不标 High。

## Recommended Next Steps

### Fix direction

本调查不直接给代码补丁。若后续进入实现，建议按机制拆成三类：

1. **架构边界。** 设计 `IntentCoordinator` 或等价协调层，收拢 candidate preparation、preflight identity、AI consensus、proposal provenance 的主控责任。
2. **入口分类。** 给 CLI/MCP/platform/runtime 写清 player-safe、trusted low-level、maintenance/admin 的 surface taxonomy，并补对应测试/文档。
3. **可靠性语义。** 把 projection/outbox 定义成 post-commit repairable read model/evidence surface，明确失败报告、repair、health/readiness gate 的行为。

### Diagnostic

无需更多证据才能做下一步架构设计。仍可选的补充诊断包括：

1. 全仓 caller graph，用于确认没有未记录公开写入面。
2. `rpg_engine/cli.py` legacy command 全量 taxonomy。
3. 历史 reports 与 git commits 的因果审计，判断哪些风险已经被修复、哪些只是历史噪音。

## Next BMAD Menu

| Recommendation | Menu code | Display name | Skill | Required | Action context / args | Why |
| -------------- | --------- | ------------ | ----- | -------- | --------------------- | --- |
| **Recommended** | `GA` | Game Architecture | `gds-game-architecture` | Required for GDS technical architecture track | Focus: RPG Engine execution-chain spine; `IntentCoordinator`; player-safe/trusted/maintenance surface taxonomy; projection/outbox consistency model | 当前问题是架构边界债，不是小 bug。先产出 architecture spine，后续 story 才不会继续漂移。 |
| Secondary | `CS` | Create Story | `gds-create-story` | Required in production story cycle | Story candidates: `IntentCoordinator` architecture extraction, CLI/MCP surface taxonomy tests/docs, projection consistency readiness gate | 当架构 spine 明确后，用 story 承接实现。 |
| Conditional | `CC` | Correct Course | `gds-correct-course` | Optional | Use if there is an active sprint or existing plan that conflicts with this investigation | 如果当前 sprint 已经在按错误路线推进，用它调整计划。 |
| Not recommended now | `QD` | Quick Dev | `gds-quick-dev` | Optional | Only for tiny doc/test guard updates | 当前不是一行修复；直接 quick-dev 容易继续把边界债写进代码。 |
| Later | `CR` | Code Review | `gds-code-review` | Optional | Run after architecture/story implementation changes exist | 现在没有新实现可审；适合作为后续质量门。 |

## Verification Plan

这是探索/架构调查，不适用传统 reproduction。已执行的验证：

- Outcome 3 boundary tests: `12 passed in 1.36s`.
- Outcome 4 projection/preflight tests: `8 passed in 0.44s`.
- Syntax/static sanity: `py_compile` 目标文件通过；`git diff --check` 通过。

下一轮架构/故事的验收应至少覆盖：

1. 玩家 profile 仍不能访问 low-level preview/validate/commit/preflight。
2. `player_turn` 仍只能创建 pending action，`player_confirm` 仍是普通玩家提交门。
3. preflight cache identity/status/single-use 语义不回退。
4. projection/outbox 失败仍被报告、可 repair，且不被误写成事实源。

## BMAD Provenance

- User trigger: 用户先后调用 `bmad-help`、`gds-investigate` 并多次确认“继续”。
- Catalog/menu: Game Dev Studio `gds-investigate`, display `Investigate`, menu code `IN`, optional, output `implementation_artifacts/investigations`.
- Skill path read: `.agents/skills/gds-investigate/SKILL.md`.
- Customization resolver: `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-investigate --key workflow`.
- Resolver result: no prepend/append steps; persistent facts `file:{project-root}/**/project-context.md`; case template `references/case-file-template.md`; subdir `investigations`; filename `{slug}-investigation.md`; `on_complete` empty.
- Config loaded: `_bmad/gds/config.yaml`; `communication_language: Chinese`; `document_output_language: Chinese`; `implementation_artifacts: {project-root}/_bmad-output/implementation-artifacts`.
- Instruction/template files followed: `.agents/skills/gds-investigate/references/case-file-template.md`.
- Verification gates: focused pytest runs, `py_compile`, and `git diff --check` as listed in Verification Plan.

## Side Findings

- Confirmed: shell reports Python 3.13.9, while project context states Python 3.11+; this is likely compatible but should be considered when running tests.
- Confirmed: the initial case file patch was created under the parent `.hermes/_bmad-output` path because `apply_patch` used the thread cwd; the case file has been moved into `rpg-engine/_bmad-output/implementation-artifacts/investigations/`.
- Confirmed: `git status --short` showed an existing modified `_bmad-output/index.md` before this investigation wrote the case file. This investigation did not modify that index.

## Follow-up: 2026-07-04 Outcome 3

### New Evidence

- Outcome 2 collected source perimeter, test collection, static checks, git history, reports inventory, and BMAD output references.
- Outcome 3 read V1 CLI command handlers, commit service, save/write guard/unit-of-work, canonical CLI/MCP docs, and representative tests.
- Outcome 3 focused boundary test run passed: `12 passed in 1.36s`.

### Additional Findings

- See Confirmed Findings 3 through 10.

### Updated Hypotheses

- Added Hypothesis 3 about low-level trusted/developer paths and profile-gate audit burden; marked it Confirmed as an architecture property, not as a defect.
- Added Hypothesis 4 and marked the ordinary player pending-confirm-commit boundary Confirmed for the focused perimeter.

### Backlog Changes

- Marked player-safe CLI/MCP/platform boundary reasoning complete for the focused perimeter.
- Kept legacy/admin CLI, projection/outbox artifacts, and AI intent/preflight ownership as high-priority follow-ups.

### Updated Conclusion

Outcome 3 is complete for the first reasoning pass. The investigation should now move to Outcome 4 targeted source tracing for the unresolved high-risk surfaces.

## Follow-up: 2026-07-04 Outcome 4

### New Evidence

- Traced legacy/admin CLI write surfaces in `rpg_engine/cli.py`.
- Traced `commit_service -> save_turn_delta -> UnitOfWork -> projection/outbox/artifacts`.
- Traced AI intent/preflight ownership across Runtime, intent router, AIIntentRouter, preflight cache, context builder, platform prewarm, and MCP.
- Ran focused projection/preflight tests: `8 passed in 0.44s`.

### Additional Findings

- Added Findings 11 through 14.
- Legacy/admin writes are classified as maintenance/trusted surfaces, not ordinary player bypasses.
- Projection/outbox is a post-commit consistency and repairability surface.
- Preflight cache has concrete identity/status/single-use guards, while overall intent/preflight ownership remains distributed.

### Updated Hypotheses

- Hypothesis 1 is partially refuted for adapter/player-safe duplication; remaining concern is intent/preflight coordination.
- Hypothesis 2 is mostly refuted for current canonical docs.
- Added Hypothesis 5: explicit `IntentCoordinator` or equivalent boundary is needed; confirmed as architecture debt.

### Backlog Changes

- Marked legacy/admin CLI, projection/outbox, and AI intent/preflight target traces complete.
- Left exhaustive whole-repo caller graph, all legacy command taxonomy, historical report audit, and version-history causal analysis as future work.

### Updated Conclusion

Outcome 4 is complete. The case can move to Outcome 5 final recommendations after user confirmation.

## Follow-up: 2026-07-04 Outcome 5

### New Evidence

- Reloaded `gds-investigate` workflow instructions, customization, case template, GDS config, project context, and BMAD menu metadata.
- Confirmed `workflow.on_complete` is empty, so no post-case automation is required.

### Additional Findings

- BMAD menu metadata supports `gds-game-architecture` (`GA`) as the strongest next architecture-track move.
- The required Outcome 5 menu alternatives are documented in `Next BMAD Menu`.

### Updated Hypotheses

- No hypothesis changed status in Outcome 5. Outcome 5 is hand-off finalization.

### Backlog Changes

- Case status changed to `Concluded`.
- Remaining backlog items are future optional work, not blockers for the user's stated goal of understanding the architecture and execution chain.

### Updated Conclusion

Investigation is concluded. The mental model is sufficient for the stated exploration goal, and the recommended next action is `gds-game-architecture` focused on the execution-chain architecture spine.
