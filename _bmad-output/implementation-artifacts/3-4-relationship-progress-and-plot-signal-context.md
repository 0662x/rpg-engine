---
baseline_commit: 3610d74fa0c484ffbfb805d1c26d6419e1bb7f45
---

# Story 3.4: Relationship, Progress, and Plot Signal Context

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 AI host，
我希望 context slices 纳入相关 relationships、progress tracks 和 plot progression signals，
从而让叙事和意图处理基于当前游戏状态推理，而不是猜测。

## 验收标准

1. 给定玩家行动引用 entity、place、goal、resource、threat 或 social target，当 context assembly 选择相关事实时，related entities、relationships、active progress tracks/clocks、recent events、world settings、rules、routes、palettes、discovery states 和 plot progression signals 会被考虑，并且已纳入 item 携带 source 与 visibility evidence。
2. 给定 relationship 或 progress item 相关但因 budget、visibility、missing reference 或 conflict resolution 被省略，当检查 `ContextBuildResult` 时，omission evidence 解释被排除原因，并且 debugging 能区分 absent facts、hidden facts 和 over-budget facts。
3. 给定 Campaign Package 提供 light hooks、goals、clues、project summaries 或其他 plot hints，当这些 hints 对玩家可见且相关时，它们可以作为 plot progression signals 出现在 context 中，并且不会变成 mandatory storylets 或 automatic director commands。

## 任务 / 子任务

- [x] 建立 relationship context collector 与渲染输出。 (AC: 1, 2)
  - [x] 复用 `rpg_engine/relationship_access.py` 的 `read_relationship()` / `list_relationships()`，不要直接解析任意 `details_json` 作为关系合同。
  - [x] 根据 `state.entity_hits`、玩家角色、当前地点、direct hit endpoints 和 action submode 选择相关 relationship；player view 必须过滤 hidden relationship、hidden endpoint、archived endpoint 和 missing endpoint。
  - [x] 新增 relationship section 和 item evidence：`source=relationships`、`kind=relationship`、稳定 id、reason、priority、depth、visibility、provenance 与 budget behavior。
  - [x] 对因 hidden endpoint、missing/archived endpoint、conflict resolution 或 budget 排除的 relationship 生成 `omitted_items` evidence；player-safe evidence 不得泄露 hidden endpoint id/name/summary。

- [x] 建立 progress / clock context collector 与渲染输出。 (AC: 1, 2)
  - [x] 复用 `rpg_engine/progress_access.py` 的 `read_progress()` / `list_progress()`，不要新增第二套 clock table access contract。
  - [x] 选择与目标 entity、resource、goal、threat、world setting linked clocks、recent activity 和 action submode 相关的 active visible progress；保留现有 `active_clocks` 行为或以兼容方式迁移。
  - [x] 渲染 progress section，包含 id、kind/clock_type、filled/total、summary、trigger_when_full、tick/reduce rule 摘要和 scope；player view 下隐藏 hidden side-table clock 和 hidden entity clock。
  - [x] 为 included / omitted progress 写入 item evidence，区分 over-budget、hidden/unavailable、missing reference、archived/conflict 等原因。

- [x] 建立 non-authoritative plot progression signal collector。 (AC: 1, 3)
  - [x] 从 player-visible world settings、rules、routes、palette candidates、discovery states、recent events、memory summaries 和 selected progress/relationship 中综合轻量 `plot_signal` evidence。
  - [x] 输出必须声明 `advisory_only=true` 或等价 authority evidence，说明 plot signal 只指导 AI/host，不会创建 facts、tick clocks、approve proposal、要求 storylet 或发出 automatic director command。
  - [x] 支持 Campaign light hooks / goals / clues / project summaries 的相关性来源；如果当前实现没有 formal storylet package，不新增 mandatory `storylets.yaml` 依赖。
  - [x] player-safe plot signals 必须在 collection/query 阶段排除 hidden / GM-only material，render redaction 只能作为 defense-in-depth。

- [x] 收敛 ContextBuildResult、audit 和 omission evidence。 (AC: 1, 2)
  - [x] 更新 `DEFAULT_CONTEXT_COLLECTORS` 的稳定顺序与 metadata tests；每个新增 collector 必须声明 visibility、provenance、budget behavior。
  - [x] 确保 `loaded_items` 和 `omitted_items` 中 relationship/progress/plot signal 都包含 `source`、`provenance`、`visibility`、`budget`、`depth` 字段，并写入 `context_runs` / `context_items` audit。
  - [x] 确保低预算时 item 不被误标为 loaded；budget omission 仍通过 section-key mapping 归因。
  - [x] 不改变 `ContextBuildResult` 顶层字段名、`context_runs` / `context_items` 表结构或默认 audit opt-in 语义，除非测试和文档同步证明必要。

- [x] 同步 canonical docs。 (AC: 1, 2, 3)
  - [x] 更新 `docs/data-models.md` 的 ContextBuildResult / relationship / progress context 说明，明确 relationship/progress/plot_signal 是 context evidence，不是事实权威。
  - [x] 更新 `docs/architecture.md` 或 `docs/testing-and-quality-gates.md` 中 context source 与验证门禁说明。
  - [x] 若 CLI `context build`、runtime query、MCP 或 prompt contract 的公开字段语义变化，同步 `docs/cli-contracts.md`、`docs/mcp-contracts.md` 或 `docs/prompt-contracts.md`；若无变化，在 Dev Agent Record 说明。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] RED/GREEN context collector gate：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider`
  - [x] Current-native context/audit gate：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider`
  - [x] Runtime/query regression gate：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_ai_intent.py -p no:cacheprovider`
  - [x] Campaign smoke：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure`、`python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`
  - [x] Docs / syntax / quality：`python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.md`、`python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/rendering.py rpg_engine/relationship_access.py rpg_engine/progress_access.py`、`python3 -m ruff check .`、`git diff --check`

### Review Findings

- [x] [Review][Decision] Player-safe hidden omission count policy — resolved 2026-07-10: ordinary player-safe view must not expose hidden / GM-only relationship or progress existence or count. GM / maintenance debug view may retain sanitized omission categories.
- [x] [Review][Patch] Preserve `ContextCollector` positional compatibility [rpg_engine/context/collectors.py:36]
- [x] [Review][Patch] Emit omitted evidence for collector-local relationship/progress/plot-signal caps [rpg_engine/context/collectors.py:340]
- [x] [Review][Patch] Prevent loaded plot signals from referencing budget-omitted relationship/progress sources [rpg_engine/context/collectors.py:893]
- [x] [Review][Patch] Expand plot-signal sources to satisfy visible rules, palettes, memory, campaign hooks/goals/clues/project summaries [rpg_engine/context/collectors.py:893]
- [x] [Review][Patch] Add distinct sanitized omission categories for hidden, missing, archived, conflict, and over-budget relationship/progress omissions [rpg_engine/context/collectors.py:365]
- [x] [Review][Patch] Restrict progress context to active visible progress [rpg_engine/context/collectors.py:443]
- [x] [Review][Patch] Include world-setting linked clocks and recent activity when selecting relevant progress [rpg_engine/context/collectors.py:443]
- [x] [Review][Patch] Add audit assertions for progress, plot-signal, and omitted context items [tests/test_current_native_context.py:1336]
- [x] [Review][Patch] Escape Markdown table cells in relationship, progress, and plot-signal rendering [rpg_engine/context/collectors.py:424]
- [x] [Review][Decision] Campaign plot hint default visibility policy — resolved 2026-07-10: shorthand/no-visibility plot hints default to player-visible `known`; hidden or GM-only hints must be explicitly labelled.
- [x] [Review][Decision] Player structural omission policy — resolved 2026-07-10: ordinary player-safe view suppresses missing_reference / archived / conflict omission existence and counts; GM / maintenance debug view retains sanitized categories.
- [x] [Review][Patch] Prevent Campaign plot hint body leakage through fallback signal id/name in omitted evidence [rpg_engine/context/collectors.py:1463]
- [x] [Review][Patch] Filter recent activity progress ranking through player-safe hidden-event policy [rpg_engine/context/collectors.py:685]
- [x] [Review][Patch] Normalize progress active status before active context filtering [rpg_engine/context/collectors.py:782]
- [x] [Review][Patch] Merge partial low-budget plot-signal omission budget evidence with full collector budget metadata [rpg_engine/context/collectors.py:115]
- [x] [Review][Patch] Preserve explicit hidden visibility for single-object Campaign plot hints instead of treating fields as visible hints [rpg_engine/context/collectors.py:1463]
- [x] [Review][Patch] Treat `world_settings_core` as satisfying world-setting plot signal source evidence [rpg_engine/context_builder.py:436]
- [x] [Review][Patch] Align canonical docs with player structural omission policy [docs/data-models.md:390]
- [x] [Review][Patch] Scrub plot signal `detail_text` when the whole plot signal section is omitted by token budget [rpg_engine/context_builder.py:904]

## 开发说明

### 来源上下文

- Epic 3 要求 `ContextBuildResult` 成为 prompt/render/query/advisory 的 inspectable context contract，并在 player-safe path 排除 hidden / GM-only material。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 3.4 的重点是 relationship、progress/clock 和 plot progression signal 的相关性与 omission evidence；不要把 Story 3.5 的 memory summary freshness/provenance 或 Story 3.6 的 budget diagnostics UX 混入本轮。
- PRD FR-10 / FR-11 / FR-12 要求 context 准确、相关、可检查、不会泄露 hidden，并支持长期游玩所需召回。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Architecture AD-4 / AD-5 要求 Relationship 和 Progress 是 first-class access contract，ContextBuildResult 是 Context Slice 合同，AI/plot signals 只能是 advisory/candidate。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- AR-24 / AR-25 / AR-26 要求 context 包含 relationships、progress/clocks、rules、routes、palettes、recent events、memory summaries、discovery_states、plot progression signals、visibility/provenance/budget/omitted evidence，并在 collection/query 阶段过滤 hidden。来源：`_bmad-output/planning-artifacts/epics.md`。

### 当前实现状态

- `rpg_engine/context_builder.py` 已定义 `ContextBuildResult`，顶层字段包括 `contract`、`scope`、`request`、`budget`、`completeness`、`loaded_items`、`omitted_items`、`sections` 和 `markdown`。
- `DEFAULT_CONTEXT_COLLECTORS` 当前稳定顺序是 `active_clocks`、`routes`、`palettes`、`discovery_states`、`world_settings`、`world_settings_core`、`recent_events`、`memory_summaries`；新增 collector 必须更新 `tests/test_context_quality.py` 中的稳定顺序断言。
- `active_clocks` 目前直接渲染 visible clocks，但没有把每个 progress/clock 作为 first-class item evidence 输出；Story 3.4 应补齐或兼容迁移，避免破坏现有 markdown。
- `relationship_access.py` 和 `progress_access.py` 已提供命名 access contract 和 visibility behavior；context collector 应复用它们。
- `context_items` audit 由 `context_audit.py` 从 `loaded_items` / `omitted_items` 写入；如果合法 item id 与 section evidence 冲突，已有 audit-only disambiguation 会保留原始 evidence id。
- Current native save 当前可能没有 relationship entities；relationship context regression 应在 temporary save copy 中注入可见、hidden endpoint、archived/missing endpoint 的 relationship probe，而不是依赖正式 current data。

### 前序故事情报

- Story 3.1 固化了 ContextBuildResult 与 context audit evidence；不要新增平行 context authority。
- Story 3.2 加固了 player-safe context、ordinary query、scene output 和 player-safe AI prompt 的 hidden 边界；任何新增 collector 必须继承 collection/query 阶段过滤。
- Story 3.3 加固了 player-facing derived artifacts、FTS/search、snapshots、cards 和 onboarding；本 story 不应重写 projection service 或 derived artifact pipeline。
- 最近提交 `3610d74 Complete story 3.3 player-safe derived artifacts` 证明 visibility/redaction helper 与 current-native visibility tests 已扩展；优先复用这些 helper 和测试模式。

### 架构合规要求

- 本 story 触碰 context assembly、relationship/progress access、visibility 和 audit evidence，按 BMAD 视为高风险 context boundary 变更；必须先写 focused tests，再实现最小改动。
- Relationship / Progress 只能通过命名 access contract 读取；不要让 collector 依赖临时 `details_json` 或直接 clock storage 细节来定义外部合同。
- Plot progression signal 是 context evidence / advisory input，不是事实、delta、storylet scheduler、proposal approval、clock tick 或 director command。
- Player-safe path 必须在 collection/query 阶段过滤 hidden / GM-only；GM / maintenance 必须显式 `view` 才能读取 hidden evidence。
- 不新增运行时依赖，不新增数据库迁移，不改变 player confirmation flow、AI intent authority、MCP profile gate、platform prewarm 或 projection/outbox fact authority。

### 相关文件

- `rpg_engine/context_builder.py`：ContextBuildResult 组装、section/item evidence、budget omission、markdown 渲染。
- `rpg_engine/context/collectors.py`：context collectors、loaded items、active clocks、routes、palettes、discovery、world settings、history、memory。
- `rpg_engine/context/rendering.py`：entity/player state rendering；新增 relationship/progress 渲染 helper 可放在 collector 或 rendering，保持本地模式一致。
- `rpg_engine/context/resolution.py`：entity hit、related entity expansion、visibility-aware resolution。
- `rpg_engine/context_audit.py`：context item audit 写入。
- `rpg_engine/relationship_access.py`：Relationship Access Contract。
- `rpg_engine/progress_access.py`：Progress / Clock Access Contract。
- `rpg_engine/visibility.py`、`rpg_engine/redaction.py`：hidden / GM-only filtering 与 defense-in-depth redaction。
- `tests/test_context_quality.py`：collector metadata、稳定顺序、budget evidence unit tests。
- `tests/test_current_native_context.py`：current-native ContextBuildResult / audit regression。
- `tests/test_current_native_visibility.py`：hidden / GM-only context leakage regression。
- `tests/test_relationship_access.py`、`tests/test_progress_access.py`：access contract unit/integration tests。

### 测试要求

最小 focused gates：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_ai_intent.py -p no:cacheprovider
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.md
python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/rendering.py rpg_engine/relationship_access.py rpg_engine/progress_access.py
python3 -m ruff check .
git diff --check
```

如实现触碰 SaveManager commit/pending、MCP profile exposure、platform sidecar/prewarm、Campaign/Save schema、migration、prompt artifact 文件或 projection service，再追加对应高风险 gates 并同步 canonical docs；否则记录未触碰原因。

### 残余风险与边界

- 本 story 不要求 memory summary freshness/staleness schema，这是 Story 3.5。
- 本 story 不要求 operator-facing context budget diagnostics UX，这是 Story 3.6。
- 本 story 不要求跨 Campaign player-safe loop smoke，这是 Story 3.7。
- 本 story 不要求 Resident AI advisory envelope、proposal queue apply/revert、AI latency policy 或 preflight cache 变更。
- 如果发现 current implementation 已经包含部分 active clock / discovery / route signals，仍必须补 relationship/progress/plot_signal item evidence 与 omission tests，因为 AC 要求 debugging 能区分 hidden、absent 和 over-budget。

### 最新技术信息

无需外部 Web research。本 story 使用仓库当前 Python 3.11+、stdlib `sqlite3` / `json` / `dataclasses`、pytest、ruff、现有 `relationship_access.py`、`progress_access.py`、`ContextBuildResult`、visibility/redaction helpers 和 current-native fixtures；不要新增运行时依赖。

## Project Structure Notes

- 保持 context collector 逻辑靠近 `rpg_engine/context/collectors.py`；共享渲染可放在 `context/rendering.py`，但不要创建大型新抽象。
- 不在 CLI/MCP adapter 中手写第二套 relationship/progress/plot signal context；CLI/MCP 应继续消费 `GMRuntime` / `build_context()` 的结果。
- 所有写入测试必须使用 temporary save copy；正式 current save package 只读。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/3-1-contextbuildresult-contract-and-audit.md`
- `_bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`
- `_bmad-output/implementation-artifacts/3-3-派生玩家视图与检索产物的隐藏信息边界.md`
- `docs/project-context.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/context_builder.py`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context/resolution.py`
- `rpg_engine/context/rendering.py`
- `rpg_engine/relationship_access.py`
- `rpg_engine/progress_access.py`
- `tests/test_context_quality.py`
- `tests/test_current_native_context.py`
- `tests/test_current_native_visibility.py`
- `tests/test_relationship_access.py`
- `tests/test_progress_access.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py::CurrentNativeContextTests::test_relationship_progress_and_plot_signals_include_auditable_evidence tests/test_current_native_context.py::CurrentNativeContextTests::test_relationship_and_progress_items_move_to_omitted_when_sections_exceed_budget -p no:cacheprovider` -> failed as expected before implementation: missing collector omitted callback, missing relationship/progress/plot signal collectors and evidence.
- GREEN focused gate: `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py::CurrentNativeContextTests::test_relationship_progress_and_plot_signals_include_auditable_evidence tests/test_current_native_context.py::CurrentNativeContextTests::test_relationship_and_progress_items_move_to_omitted_when_sections_exceed_budget -p no:cacheprovider` -> 17 passed, 20 subtests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_context_quality.py tests/test_relationship_access.py tests/test_progress_access.py -p no:cacheprovider` -> 25 passed, 39 subtests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_visibility.py::CurrentNativeVisibilityTests::test_player_safe_context_excludes_hidden_probe_while_gm_context_can_read_it -p no:cacheprovider` -> 1 passed after adjusting query-mode plot signal priority.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_current_native_context.py tests/test_current_native_visibility.py -p no:cacheprovider` -> 26 passed, 8906 subtests passed.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_runtime.py tests/test_ai_intent.py -p no:cacheprovider` -> 101 passed, 52 subtests passed.
- `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` -> OK.
- `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` -> OK.
- `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.md` -> checked 87 markdown files; local links ok.
- `python3 -m py_compile rpg_engine/context_builder.py rpg_engine/context/collectors.py rpg_engine/context/rendering.py rpg_engine/relationship_access.py rpg_engine/progress_access.py tests/test_context_quality.py tests/test_current_native_context.py` -> passed.
- `python3 -m ruff check .` -> All checks passed.
- `git diff --check` -> passed.
- Final three-way review after all patches: Blind Hunter, Edge Case Hunter, and Acceptance Auditor reported no `[Review][Patch]` and no `[Review][Decision]`.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider` -> 643 passed, 9629 subtests passed.

### Completion Notes List

- Added relationship context collection and rendering through the existing `relationship_access.py` contract, with included item evidence and sanitized omission evidence for player-hidden or unavailable endpoints.
- Added progress context collection and rendering through the existing `progress_access.py` contract, preserving `active_clocks` while adding first-class progress item evidence and budget/visibility omissions.
- Added advisory-only plot progression signals derived from already visible context evidence, explicitly preventing storylet/director/fact-authority semantics.
- Extended `ContextCollector` with compatible omitted-item callbacks and merged collector omissions into `ContextBuildResult.omitted_items` without changing top-level context fields or audit table schemas.
- Added current-native regression tests for relationship/progress/plot signal loaded evidence, context audit rows, hidden omission redaction, and budget omission behavior.
- Applied code-review patch set: player-safe hidden omission counts are suppressed, GM / maintenance omission categories are structured, collector-local caps write omission evidence, progress context is active-only, plot signals cover visible rules/palettes/memory/campaign hints and are filtered when source sections are budget-omitted, and Markdown table cells are escaped.
- Applied final review patch set: campaign hint fallback IDs/names no longer derive from hint body, recent event progress ranking ignores hidden-event evidence in player view, progress active checks normalize status labels, and low-budget plot-signal omissions keep complete budget metadata.
- Applied last Edge/Blind patch set: single-object hidden campaign hints preserve hidden visibility, `world_settings_core` satisfies world-setting plot signal source requirements, player structural omission docs match policy, and section-budget plot-signal omissions scrub hint detail text.
- Synchronized canonical docs for context source, relationship/progress evidence, plot signal authority, and quality gates. CLI/MCP/prompt public command syntax did not change.

### File List

- `_bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.md`
- `_bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/context/__init__.py`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context/sections.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/relationship_access.py`
- `tests/test_context_quality.py`
- `tests/test_current_native_context.py`

### Implementation Plan

- 先补 focused RED tests，覆盖新增 collector 顺序、relationship/progress/plot signal item evidence、budget omission 和 hidden/missing endpoint omission。
- 在 `context/collectors.py` 中最小扩展 collector contract，支持 per-collector omitted item evidence，并添加 relationships、progress_context、plot_signals 三个 collector。
- 在 `context_builder.py` 中把 collector omitted evidence 合并进 `ContextBuildResult.omitted_items`，保持顶层字段和 audit 表结构不变。
- 同步 context 相关文档，说明 relationship/progress/plot signal 仍是 context evidence/advisory，不是事实权威。

### Change Log

- 2026-07-09: Implemented Story 3.4 relationship/progress/plot signal context evidence, synchronized docs, passed focused and full regression gates, and moved story to review.
- 2026-07-10: Applied BMAD code-review patch set from Blind Hunter, Edge Case Hunter, and Acceptance Auditor; focused patch tests, py_compile, ruff targeted check, and `git diff --check` passed before second review.
- 2026-07-10: Resolved final review decisions for campaign plot hint default visibility and player structural omission policy; applied final Blind/Edge patch set and added focused regressions.
- 2026-07-10: Applied last Blind/Edge review patches for single-object hidden plot hints, world-setting source aliases, docs policy wording, and section-budget plot signal detail scrubbing.
- 2026-07-10: Final three-way review passed cleanly; final focused, campaign, docs, static, and full pytest gates passed; story moved to done.
