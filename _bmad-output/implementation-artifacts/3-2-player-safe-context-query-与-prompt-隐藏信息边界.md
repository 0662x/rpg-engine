---
baseline_commit: da6ad6d3565065b0f6402da156f85e1426340f1e
---

# Story 3.2: Player-Safe Context、Query 与 Prompt 隐藏信息边界

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为玩家，
我希望 hidden 和 GM-only 信息不会进入 player-safe context、ordinary query、scene output 或 player-safe AI prompts，
从而让游戏可以保留秘密，同时仍能让 AI 主持可见内容。

## 验收标准

1. 给定 hidden 或 GM-only entities、relationships、world settings、discovery states、memory summaries 或 events 存在，当 player-safe context、ordinary query、scene output 或 player-safe AI prompts 被构建时，hidden material 必须在 collection 或 query 阶段被排除，并且不能只依赖最终 render 阶段隐藏。
2. 给定 trusted GM 或 maintenance context 被请求，当 caller profile 允许 hidden reads 时，hidden material 可以带 explicit visibility mode 和 provenance 被纳入。
3. 给定同一 Save 上先构建 trusted GM / maintenance context、再构建 player-safe context，当 player-safe 结果返回时，任何 context/cache/audit/result reuse 都不能把 hidden material 泄漏到 player-safe mode。

## 任务 / 子任务

- [x] 加固 player-safe context collection/query 阶段的 hidden 排除。 (AC: 1)
  - [x] 审查 `rpg_engine/context_builder.py`、`rpg_engine/context/collectors.py`、`rpg_engine/context/resolution.py`、`rpg_engine/context/rendering.py`、`rpg_engine/render.py` 中所有进入 `ContextBuildResult`、ordinary query 和 scene output 的事实读取点，确认 player view 下使用 visibility-aware SQL/access contract，而不是先取出 hidden 再字符串遮盖。
  - [x] 对 entities、relationship-shaped entities、world settings、discovery states、memory summaries、recent events 和 active clocks/progress 的 player-safe collection 增加或修正过滤；如果某类数据当前没有结构化 visibility 字段，必须记录明确 omission / not-applicable evidence，不能静默混入 prompt/context。
  - [x] 保留 Story 3.1 的 `ContextBuildResult` 合同字段和 audit evidence；新增过滤逻辑必须继续写出 included / omitted、visibility mode、provenance、budget evidence 和 missing-signal evidence。

- [x] 加固 ordinary query 和 scene output 的 player-safe 边界。 (AC: 1)
  - [x] 确认 `GMRuntime.query("scene"|"entity"|"context")`、CLI/MCP player-safe query path 和 `render_scene()` 默认 view 均为 `player`，并在读取阶段排除 hidden / GM-only rows。
  - [x] 对 scene output、entity query、context query 的 JSON/markdown/text 输出增加 focused tests，断言 hidden id、name、summary、details、event title/summary/payload、world setting content、memory summary 和 relationship endpoint 不出现在 player view。
  - [x] 保持 GM/maintenance read 不退化：trusted view 下同一 fixture 的 hidden material 应可见，并带 view / provenance evidence。

- [x] 加固 player-safe AI prompt/context 输入边界。 (AC: 1, 3)
  - [x] 检查 `context/semantic.py`、runtime `start_turn()` / `preview_from_text()`、MCP `player_turn` 和 prompt artifacts 的 context consumption；player-safe prompt 或 internal helper prompt 必须消费 player-view `ContextBuildResult` 或等价 player-safe state，不得重新查询 hidden facts。
  - [x] 如果发现 helper prompt、semantic prompt 或 intent review prompt 使用未过滤字段，改为从 player-safe context fields / redacted fields 取值，并加测试证明 prompt 输入不包含 hidden material。
  - [x] 不改变 external/internal AI authority：AI helper 仍只是 advisory/review，不获得 hidden permission、confirmation、proposal approval 或 save authorization。

- [x] 覆盖 trusted GM / maintenance explicit hidden read 与 cache/reuse 隔离。 (AC: 2, 3)
  - [x] 为 `view="gm"` / `view="maintenance"` 添加或更新测试，证明 hidden material 可以在允许 profile/view 下进入 context/query，并且结果记录 explicit visibility mode 与 provenance。
  - [x] 在同一临时 save 上按 `gm -> player`、`maintenance -> player` 顺序构建 context/query，断言第二次 player-safe 输出、`ContextBuildResult.to_json_text()` 和可选 audit rows 不复用前一次 hidden 内容。
  - [x] 如果实现中存在 context cache、semantic helper cache 或 audit upsert 复用，key 必须包含 visibility mode / view identity；如果不存在缓存，也要用测试锁定不通过 audit/result reuse 泄漏。

- [x] 同步 canonical docs 与 prompt 合同。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 或 `docs/architecture.md` 中的 ContextBuildResult / Visibility 说明，明确 Story 3.2 后 player-safe collection/query/prompt 在读取阶段排除 hidden。
  - [x] 如 prompt artifact 或 helper prompt 语义变化，更新 `docs/prompt-contracts.md` 与对应 prompt 文件版本/说明；如果没有 prompt artifact 变更，在 Dev Agent Record 说明原因。
  - [x] 不把 Story 3.3 的 cards、snapshots、FTS、onboarding、derived read models 纳入本 story，除非修复 player-safe query/prompt 时发现明确直接泄漏；若发现派生产物问题，记录为后续 3.3 follow-up。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN visibility/context gates：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_context_quality.py tests/test_current_native_context.py -p no:cacheprovider`
  - [x] Runtime/CLI/MCP player-safe gates：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_v1_cli.py tests/test_mcp_adapter.py -p no:cacheprovider`
  - [x] Campaign smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`
  - [x] Docs / syntax / quality：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`、`python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/resolution.py rpg_engine/context/rendering.py rpg_engine/render.py rpg_engine/runtime.py`、`python3 -m ruff check .`、`git diff --check`

### Review Findings

- [x] [Review][Decision] Memory/events 无结构化 visibility 的安全模型需要产品决策 — resolved by option 2: keep current schema invariant that event / memory hidden material must be expressed through hidden entity refs; added docs, `ContextBuildResult.contract.visibility_invariants`, and focused tests.
- [x] [Review][Patch] Player-safe helper prompts 仍会消费未过滤输入或 raw current meta [`rpg_engine/context/semantic.py:76`, `rpg_engine/ai_intent/prompts.py:58`]
- [x] [Review][Patch] Discovery states 的 player collection 只过滤 discovery visibility，未验证 backing subject entity visibility；GM/maintenance 也缺少正向 allowed visibility clause [`rpg_engine/context/collectors.py:339`]
- [x] [Review][Patch] History/memory hidden-ref filtering 发生在 SQL LIMIT 之后，hidden rows 可能饿死后续 safe recall；general recent helper 的返回数量契约也被放宽 [`rpg_engine/context/collectors.py:791`, `rpg_engine/memory.py:431`]
- [x] [Review][Patch] Trusted reuse isolation 缺少 `maintenance -> player` 顺序覆盖 [`tests/test_current_native_visibility.py:199`]
- [x] [Review][Patch] 第二轮 review: discovery / memory / event fixed overfetch 仍可能被大量 hidden rows 饿死 — resolved with player-view pagination until enough safe rows or EOF, plus 30-hidden-row regression tests.
- [x] [Review][Patch] 第二轮 review: event hidden-ref 检查未覆盖 rendered id / turn_id / game_time — resolved by checking all rendered event fields before collection.
- [x] [Review][Patch] 第二轮 review: internal intent view 未贯通 route / arbiter / binder / rules entity matching — resolved by threading `view` through `route_intent`, `AIIntentRouter`, arbiter, binder, and rules inference.
- [x] [Review][Patch] 第二轮 review: player-view internal helper prompt redaction fail-open and parsed `source_user_text` raw回写 — resolved with fail-closed prompt fallback and parser source text redaction.
- [x] [Review][Patch] 后续 review: `mode="maintenance"` 分类阶段在 `state.mode` 更新前被误判为 player view — resolved by deriving classification view from explicit `visibility_view` or `mode_arg`.
- [x] [Review][Patch] 后续 review: hidden entity id 嵌入 event / memory / discovery identifiers 或 rendered text 时仍可绕过边界匹配 — resolved with hidden entity id substring filtering/redaction and prefixed-id regression tests.
- [x] [Review][Patch] 后续 review: player-safe semantic/internal prompts 和 `ContextBuildResult` final JSON/markdown 仍可能保留嵌入式 hidden id — resolved by applying substring redaction to prompt inputs and final player context output.

## 开发说明

### 来源上下文

- Epic 3 的目标是让 AI / host 获得准确、相关、可审计、不会泄露 hidden 的 Context Slice，并支持长期记忆召回。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 3.2 明确只覆盖 player-safe context、ordinary query、scene output 和 player-safe AI prompts；cards、snapshots、FTS、onboarding 和其他派生玩家视图属于 Story 3.3。来源：`_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md`。
- PRD FR-10 要求 context assembly 足够 deterministic / inspectable；FR-11 要求 hidden/GM-only 信息不能进入 player-visible views、ordinary query、scene output 或不合适的 AI prompts。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Architecture AD-5 要求 context assembly 先产出 inspectable `ContextBuildResult`，player-safe context 在进入 AI prompt 或 player-visible rendering 前排除 hidden/GM-only facts，并通过 `context_runs` / `context_items` 审计。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。

### 当前实现状态

- Story 3.1 已完成 `ContextBuildResult` contract/scope、collector metadata、section/item evidence、context audit row 和 runtime JSON 兼容增强。当前 story 应复用这套合同，不新建平行 context object。
- `visibility.py` 提供 `normalize_visibility_view()`、`context_visibility_view()`、`can_read_hidden()`、`entity_visibility_sql()`、`clock_visibility_sql()` 和 `world_setting_visibility_sql()`。
- `build_context()` 通过 `BuildState.visibility_view` 和 `context_state_visibility_view()` 决定 player/gm/maintenance view；`render_context_result()` 会 redaction，但本 story 的重点是把 hidden 排除前移到 collection/query。
- `render_scene()` 已接收 `view` 并对 location、present entities、carried items、active clocks、affordances 使用 visibility clauses；实现时仍需用测试覆盖 hidden relationship/world setting/memory/event/prompt 输入等当前薄弱面。
- `GMRuntime.query("scene")` 直接调用 `render_scene()`；`query("entity")` 调 `render_entity()`；`query("context")` 调 `build_context(..., view=normalized_view)`。
- `context/collectors.py` 已有 routes、palettes、discovery_states、world_settings、recent_events、memory_summaries 等 collector；每个 collector 必须保持 source/visibility/provenance/budget metadata。
- `context/resolution.py` 的 entity matching 和 related expansion 已按 view 过滤实体；新增测试应防止未来绕过这些 helpers。

### 前序故事情报

- Story 3.1 的 review 曾发现 section evidence、palette metadata、budget omission 和 audit id collision 等问题；本 story 不得破坏这些修复。
- Story 3.1 的最终 gates 显示 `tests/test_context_quality.py`、`tests/test_current_native_context.py`、`tests/test_runtime.py`、`tests/test_v1_cli.py`、`tests/test_current_native_visibility.py` 和 campaign smoke 是 context 变更的有效回归组合。
- Epic 1 / Epic 2 已建立 player-safe pending/confirm、surface authority、Save fact authority、Entity/Relationship/Progress access contract；本 story 不得改变提交权限或引入直接 SQL 写事实的旁路。

### 架构合规要求

- 本 story 是 hidden / visibility / prompt boundary 变更，按 BMAD 规则属于高风险 context 边界，必须小步修改并用 focused tests 证明。
- Player-safe collection/query 阶段必须排除 hidden / GM-only facts；render redaction 只能作为 defense-in-depth，不能作为唯一防线。
- GM / maintenance hidden reads 必须显式选择 view/profile，并在 output/audit 中留下 visibility mode 与 provenance。
- Query、start_turn、prompt/helper context 都必须是只读路径；不得推进 turn、写 event、创建 pending action 或改变 Save facts。
- External AI、internal AI、semantic helper 和 prompt artifacts 不获得 hidden permission、confirmation、proposal approval、delta injection 或 save authorization。
- 不新增第二条 context pipeline，不在 CLI/MCP/runtime adapter 中复制业务逻辑。

### 相关文件

- `rpg_engine/visibility.py`：visibility view 与 SQL helper。
- `rpg_engine/context_builder.py`：`ContextBuildResult`、pipeline、render/audit hook。
- `rpg_engine/context/collectors.py`：context source collection 与 metadata。
- `rpg_engine/context/resolution.py`：entity matching、related expansion、FTS sanitization。
- `rpg_engine/context/rendering.py`：context section rendering。
- `rpg_engine/context/semantic.py`：semantic helper prompt 输入。
- `rpg_engine/render.py`：scene/entity/snapshot rendering。
- `rpg_engine/runtime.py`：`GMRuntime.start_turn()`、`query()`、`preview_from_text()`。
- `rpg_engine/mcp_adapter.py`：MCP player profile、query/player_turn hidden-read gates。
- `rpg_engine/cli.py` / `rpg_engine/cli_v1.py`：CLI context/query/player path。
- `docs/data-models.md`、`docs/architecture.md`、`docs/prompt-contracts.md`、`docs/testing-and-quality-gates.md`。
- `tests/test_current_native_visibility.py`、`tests/test_context_quality.py`、`tests/test_current_native_context.py`、`tests/test_runtime.py`、`tests/test_v1_cli.py`、`tests/test_mcp_adapter.py`。

### 测试要求

最小 focused gates：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_context_quality.py tests/test_current_native_context.py -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_v1_cli.py tests/test_mcp_adapter.py -p no:cacheprovider
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md
python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/resolution.py rpg_engine/context/rendering.py rpg_engine/render.py rpg_engine/runtime.py
python3 -m ruff check .
git diff --check
```

如实现触碰 SaveManager、commit/projection、package schema、platform prewarm 或 FTS/cards/snapshots/onboarding，再追加对应 gates 并记录为何 scope 扩展；否则把 derived artifact 风险留给 Story 3.3。

### 残余风险与边界

- 本 story 不要求修复 cards、snapshots、FTS、onboarding 或 player-facing search artifacts；这些属于 Story 3.3。
- 本 story 不要求长期记忆 summary freshness/provenance 的完整治理；这是 Story 3.5。
- 本 story 不要求 context budget diagnostics 的完整 operator UX；这是 Story 3.6。
- 本 story 不要求 resident AI advisory envelope、proposal queue lifecycle 或 content promotion；这些属于 Epic 4 / Epic 5。
- 本 story 不改变 public CLI/MCP command taxonomy；若只加固默认 player view 与测试，不应改变工具暴露面。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python 3.11+、stdlib `sqlite3` / `json`、pytest、现有 visibility helpers、context pipeline 和 SQLite audit tables；不要新增运行时依赖。

## Project Structure Notes

- 保持过滤逻辑靠近现有 context/render/query modules，优先复用 `visibility.py` SQL helper 与 Entity/Relationship/Progress access contracts。
- 新 helper 应放在 `rpg_engine/context/*` 或 `visibility.py` 的既有边界内；不要在 CLI/MCP adapter 中手写第二份 hidden 过滤。
- 测试优先使用 temp save copy 注入 hidden probe；正式 current save package 只能 read-only。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/3-1-contextbuildresult-contract-and-audit.md`
- `docs/project-context.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `docs/prompt-contracts.md`
- `docs/ai-intent-chain.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `rpg_engine/visibility.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context/resolution.py`
- `rpg_engine/context/rendering.py`
- `rpg_engine/context/semantic.py`
- `rpg_engine/render.py`
- `rpg_engine/runtime.py`
- `rpg_engine/mcp_adapter.py`
- `tests/test_current_native_visibility.py`
- `tests/test_context_quality.py`
- `tests/test_current_native_context.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED visibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py -p no:cacheprovider` failed as expected on hidden current-location leakage in semantic prompt and hidden probe context coverage.
- GREEN focused visibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py -p no:cacheprovider` passed with 4 tests.
- Context/visibility/story gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_context_quality.py tests/test_current_native_context.py -p no:cacheprovider` passed with 29 tests and 33 subtests.
- Runtime/CLI/MCP gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_v1_cli.py tests/test_mcp_adapter.py -p no:cacheprovider` passed with 138 tests and 59 subtests.
- Campaign smoke: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` passed.
- Docs/syntax/quality gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`, `python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/resolution.py rpg_engine/context/rendering.py rpg_engine/render.py rpg_engine/runtime.py rpg_engine/context/semantic.py rpg_engine/memory.py`, `python3 -m ruff check .`, and `git diff --check` passed.
- Full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 623 tests and 736 subtests.
- Review patch focused visibility gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py -p no:cacheprovider` passed with 5 tests.
- Review patch AI intent prompt gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_ai_intent.py -p no:cacheprovider` passed with 39 tests.
- Review patch context/visibility/story gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_context_quality.py tests/test_current_native_context.py -p no:cacheprovider` passed with 30 tests and 33 subtests.
- Review patch Runtime/CLI/MCP gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_v1_cli.py tests/test_mcp_adapter.py -p no:cacheprovider` passed with 138 tests and 59 subtests.
- Review patch syntax/quality gate: `python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/semantic.py rpg_engine/memory.py rpg_engine/ai_intent/prompts.py rpg_engine/ai_intent/internal_review.py`, `python3 -m ruff check .`, and `git diff --check` passed.
- Second review patch targeted gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_ai_intent.py -p no:cacheprovider` passed with 47 tests.
- Second review patch context/visibility/story gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_context_quality.py tests/test_current_native_context.py -p no:cacheprovider` passed with 31 tests and 33 subtests.
- Second review patch Runtime/CLI/MCP gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_v1_cli.py tests/test_mcp_adapter.py -p no:cacheprovider` passed with 138 tests and 59 subtests.
- Final review targeted gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_ai_intent.py -p no:cacheprovider` passed with 48 tests.
- Final review context/visibility/story gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py tests/test_context_quality.py tests/test_current_native_context.py -p no:cacheprovider` passed with 32 tests and 33 subtests.
- Final review Runtime/CLI/MCP gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_v1_cli.py tests/test_mcp_adapter.py -p no:cacheprovider` passed with 138 tests and 59 subtests.
- Final review Campaign smoke: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure && python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` passed.
- Final review docs/syntax/quality gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`, `python3 -m py_compile ...`, `python3 -m ruff check .`, and `git diff --check` passed.
- Final clean review: Blind Hunter, Edge Case Hunter, and Acceptance Auditor all returned clean after the last explicit patch.
- Final full regression gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` passed with 628 tests and 736 subtests.

### Completion Notes List

- Added current-native hidden probe coverage for player-safe context/query/scene output, trusted GM read, audit reuse isolation, memory/event/discovery/world-setting visibility, and semantic prompt current-location handling.
- Updated context collectors so player view skips history events and discovery rows containing hidden refs, validates discovery backing hidden subjects, and uses a positive trusted discovery visibility allowlist.
- Updated memory and history recall to overfetch before hidden-ref filtering so safe rows are not starved by hidden top-N rows.
- Updated semantic and internal intent prompt construction to hide hidden current-location ids and hidden-ref user/candidate/entity text in player view.
- Recorded the chosen event/memory invariant in docs and `ContextBuildResult.contract.visibility_invariants` instead of adding schema migration in this story.
- Threaded trusted `view` through internal intent review routing, arbitration, binding, and rule entity inference.
- Changed player-view internal prompt fallback to fail closed when redaction schema or SQL redaction is unavailable, and redacted parsed `source_user_text`.
- Added hidden entity id substring filtering/redaction for rendered identifiers and player-safe prompt/context output so prefixed ids cannot expose hidden entity ids.
- Fixed classification-time view selection so implicit `mode="maintenance"` context routes internal intent helpers under maintenance view.
- Synchronized canonical data model, prompt contract, and testing gate docs for Story 3.2 player-safe collection/query/prompt boundaries.
- No prompt artifact file version change was needed; the behavior change is in runtime helper prompt construction, and `docs/prompt-contracts.md` now records the contract.

### File List

- `rpg_engine/context/collectors.py`
- `rpg_engine/context/semantic.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/ai_intent/prompts.py`
- `rpg_engine/ai_intent/internal_review.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/ai_intent/arbiter.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/runtime.py`
- `rpg_engine/memory.py`
- `rpg_engine/redaction.py`
- `tests/test_ai_intent.py`
- `tests/test_current_native_visibility.py`
- `docs/data-models.md`
- `docs/prompt-contracts.md`
- `docs/testing-and-quality-gates.md`
- `_bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`
- `_bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`

### Change Log

- 2026-07-09: Implemented player-safe context/query/prompt hidden-boundary hardening, tests, docs sync, and verification gates.
