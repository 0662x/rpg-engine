---
baseline_commit: fd6c5d395d93a8e2a38b5fc045418aee69cc9840
---

# Story 3.6: Context Budget and Quality Diagnostics

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 engine author，
我希望获得针对缺失、超预算、过期或低价值 context 的质量诊断，
从而在不削弱 visibility 边界的前提下改进 AI 主持质量。

## 验收标准

1. 给定一次 context request 超出预算，当 budgeting 运行时，`ContextBuildResult` 记录可检查的 budget decisions、included / omitted items 和 high-value missing signals；player-safe hidden filtering 仍在任何 prompt 或 render 输出前完成。
2. 给定本次 context 涉及的 entity、relationship、progress track、memory summary、alias 或 world setting 缺少有用的结构化字段，当 diagnostics 运行时，warning 能指出 missing summary、aliases、endpoint references、progress metadata 或 stale summary evidence；diagnostics 不评价文笔、剧情质量、题材偏好或审美品味。
3. 给定 context 行为发生变化，当 focused tests 运行时，测试覆盖 context audit rows、recall budget、relationship / progress inclusion、hidden leakage 和 current-native context regression；最终 story evidence 明确记录所选 gate 与结果。

## 任务 / 子任务

- [x] 扩展现有 `ContextBuildResult` 的 budget decision evidence，不新建第二套 budget/diagnostics contract。 (AC: 1)
  - [x] 在 `rpg_engine/context_builder.py` 的现有 `budget` object 中记录确定性 section decision：section key、required、priority、estimated tokens、included / omitted、reason，以及 included / omitted section keys；保留既有 `limit`、`requested`、`campaign_default`、`policy_profile`、`policy_reason`、`estimated`、`sections` 和 `trimmed` 字段兼容语义。
  - [x] Additive budget evidence 至少包含 `over_limit`、`overflow_tokens`、`utilization`、`decisions` 和 `omitted_sections`；`over_limit` / `overflow_tokens` 使用最终 included tokens 与经最小 500 clamp 后的 effective `budget.limit` 比较，raw `requested` 只保留为输入证据，数值必须有界可序列化。
  - [x] 明确记录 required sections 自身超过 effective `budget.limit` 的情况；required context 仍不得为了满足数字预算被静默删除，diagnostics 应指出超额原因和影响。
  - [x] 从最终、已按 visibility 过滤且已完成 budget reconciliation 的 evidence 中生成 high-value missing signals，并只追加到 `completeness.missing_signal_evidence`。确定性规则：token-budget omitted item/section 的 effective priority `>= 70`，或 required sections 总 tokens 超过 effective limit；按 `(code, source, signal)` 去重，按 priority 降序、source、signal 排序，最多 8 条；只报告结构化 source、reason code、priority / budget evidence，不复制隐藏内容或被省略正文。
  - [x] 保持 Story 3.5 的 render-state copy、memory generation snapshot、bounded retry、ABA 防护和 non-memory plot signal preservation；不得直接修改 collector state 来制造 budget evidence。

- [x] 提供一次 context assembly 范围内的结构化 quality warnings。 (AC: 1, 2)
  - [x] 新增小型、纯诊断 helper（优先放在 `rpg_engine/context/diagnostics.py`），消费当前 build state、最终 loaded / omitted evidence 和既有 access contract；warnings 的唯一 additive JSON 路径固定为 `completeness.quality_diagnostics`，不新增 SQLite 表、全包 Campaign doctor、平行顶层 result model 或其他 warning path。
  - [x] warning 使用稳定结构 `code`、`severity`、`source`、`subject_kind`、安全 `subject_id`、`missing_fields`、`reason`、`visibility`、`provenance`、`advisory_only=true`；按 `(code, source, subject_kind, subject_id, missing_fields)` 去重，按 severity、code、source、subject id 排序，最多 32 条，且全部 JSON-safe。
  - [x] 对本次 context 中可见且相关的 entity / world setting 检查缺失 summary；对相关 entity 的 alias 可用性或既有 semantic alias gap 产出 missing-alias warning，避免扫描并报告整个 Campaign；alias lookup 必须按已过滤 visible ids 批量查询，禁止 N+1 或 maintenance 全集扫描。
  - [x] 复用 `relationship_access.py` 的 `RelationshipRecord.endpoint_issues` 与既有 relationship omission categories，报告缺失 endpoint reference；不要直接解析任意 `details_json` 或创建第二套 endpoint 规则。
  - [x] 复用 `progress_access.py` 的 `ProgressRecord`，对缺失 `scope`、`clock_type/kind`、有效 segments、tick rules / trigger metadata 或 summary 产出结构化 progress metadata warning；不把 progress 质量等同于剧情完成度。
  - [x] 复用 Story 3.5 的 memory omission / freshness evidence，报告 stale、unavailable 或 unverifiable summary evidence；不得把 memory projection health 与单条 summary freshness 混为一谈，也不得让 diagnostics 修复或提升 summary authority。
  - [x] low-value 仅表示结构化 priority、relevance、budget、freshness 或缺字段 evidence；禁止 prose scoring、剧情品味评分、genre preference、AI 文风评价或自动改写内容。

- [x] 加固 player-safe diagnostics 的 visibility 与 non-oracle 边界。 (AC: 1, 2)
  - [x] diagnostics 必须基于已选择的 context view 与 visibility-safe access/collector 结果；hidden filtering 发生在 ranking、budget/high-value signal 和 prompt/render 之前，最终 redaction 仅作为 defense-in-depth。
  - [x] player view 不得通过 warning 暴露 hidden / GM-only item 的 id、name、alias、summary、endpoint、数量、具体 omission category、raw metadata 或 private AI reasoning；hidden-only 与真正 absent/empty 应产生相同的 generic bounded signal。
  - [x] GM / maintenance view 可检查脱敏的结构类别与安全 identity，但仍必须使用字段 allowlist、值级 normalization 和 JSON-safe output。
  - [x] warning / high-value signal 不得成为事实、proposal approval、clock tick、player confirmation、save authorization 或 commit gate；diagnostics 失败只能降级为安全的 missing/unavailable evidence，不能阻塞普通 gameplay fact submission。
  - [x] `completeness.quality_diagnostics` 和 `completeness.missing_signal_evidence` 中新增的 high-value advisory 不能改变既有 `allow_proceed`、`confidence`、`missing_required` 或 confirmation decision；只有原有 validation/intent contract 可以阻塞推进。

- [x] 保持 context audit 与现有消费 surface 同步。 (AC: 1, 3)
  - [x] `context_runs.output_json` 必须保存最终 `budget.decisions`、`completeness.quality_diagnostics` 和 `completeness.missing_signal_evidence`；`context_items` 继续通过最终 loaded / omitted evidence 记录 included / omitted rows，不新增重复事实表。
  - [x] 修正 `context_audit.py` 当前对 loaded item 固定写入 `estimated_tokens=NULL` 的缺口，改为保存 item 已有的安全 token evidence；不改变表结构或 audit opt-in 语义。
  - [x] audit 结果必须与最终 `ContextBuildResult` 同 snapshot、同 visibility view、同 budget pass；不能把 pre-budget、pre-redaction 或 superseded memory generation 写入 audit。
  - [x] 保持默认 context audit opt-in：普通 `build_context()` / query 不因 diagnostics 写数据库；启用 audit 也不能推进 turn、events 或 gameplay facts。
  - [x] 不新增 CLI/MCP 参数或新的公开 diagnostics command。现有 CLI/runtime JSON 若自然序列化 `ContextBuildResult` 的 additive evidence，应保持旧字段可用；若实现需要改变公开命令/字段语义，HALT 并先同步对应合同。

- [x] 同步 canonical docs。 (AC: 1, 2, 3)
  - [x] 更新 `docs/architecture.md`，说明 context quality diagnostics 复用 visibility-safe collection、budget result 和 access contracts，且只产生 advisory evidence。
  - [x] 更新 `docs/data-models.md` 的 `ContextBuildResult` / audit contract，记录 `budget.decisions`、`completeness.quality_diagnostics` 和 high-value `completeness.missing_signal_evidence` shape；不改变 SQLite fact authority。
  - [x] 更新 `docs/component-inventory.md`（若新增 `context/diagnostics.py`）和 `docs/testing-and-quality-gates.md` 的 Story 3.6 focused gate。
  - [x] 若未改变 CLI、MCP、prompt 的公开语义，在 Dev Agent Record 明确记录无需更新 `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`。

- [x] 以 RED/GREEN 方式覆盖验收与边界，并记录最终证据。 (AC: 1, 2, 3)
  - [x] Unit gate：在 `tests/test_context_quality.py` 覆盖确定性 budget decisions、required-over-budget、high-value missing signal、warning 去重/排序/上限，以及 diagnostics 不做 prose/taste scoring。
  - [x] Current-native context/audit gate：在 temp copy 上验证 `context_runs.output_json` 和 `context_items` 与最终 result 同步，覆盖 recall budget、included / omitted、relationship / progress source 和 stable snapshot。
  - [x] Hidden gate：覆盖 player view 不泄露 hidden id/name/alias/summary/count/category，GM / maintenance 仍可看到安全结构 warning，并证明 hidden-only 与 empty 结果不形成 oracle。
  - [x] Memory regression：保留 stale/fallback/generation evidence 和 Story 3.5 的 bounded retry / snapshot contract，不重复实现 memory freshness。
  - [x] 运行“测试要求”中的唯一权威 focused、compatibility、campaign/docs/static 与 full-suite gate 列表；若实现未触碰 memory/projection code，在完成记录中说明 compatibility gate 是 regression evidence 而非变更面。

### Review Findings

- [x] [Review][Patch] 区分 plot dependency unavailable 与真实 token-budget omission，避免虚假 budget reason [rpg_engine/context_builder.py:442]
- [x] [Review][Patch] high-value omission 使用结构化 `reason_code` / `included=false`，不以文本包含关系判定 [rpg_engine/context/diagnostics.py:107]
- [x] [Review][Patch] 缺失或显式 `unverifiable` 的 memory freshness 必须产生安全 warning [rpg_engine/context/diagnostics.py:412]
- [x] [Review][Patch] diagnostics 按 source 隔离异常，保留其他来源已成功的 warnings [rpg_engine/context/diagnostics.py:178]
- [x] [Review][Patch] 空白 alias 行不得被视为可用 lookup alias [rpg_engine/context/diagnostics.py:557]
- [x] [Review][Patch] overflow 比较使用原始任意精度整数，仅在序列化字段时饱和 [rpg_engine/context/diagnostics.py:26]
- [x] [Review][Patch] context audit DDL/DML 显式绑定 canonical `main`，抵抗 TEMP shadow [rpg_engine/context_audit.py:10]
- [x] [Review][Patch] progress `conflict` omission 也要提供安全的 segment/status metadata warning [rpg_engine/context/diagnostics.py:391]
- [x] [Review][Patch] required overflow signal 必须在 8 条上限内保留固定槽位 [rpg_engine/context/diagnostics.py:82]
- [x] [Review][Patch] 接入已 visibility-safe 的 semantic alias gaps，输出单一通用 missing-alias warning [rpg_engine/context/diagnostics.py:213]
- [x] [Review][Patch] `budget.requested` 保留有界有符号 raw input，不把负数静默改写为零 [rpg_engine/context/diagnostics.py:60]
- [x] [Review][Defer] plot post-filter 释放预算后不会重新选择较低优先级 source section [rpg_engine/context_builder.py:545] — deferred, pre-existing
- [x] [Review][Patch] `budget.trimmed` 仅表示真实 `over_budget` omission，保留旧兼容语义 [rpg_engine/context/diagnostics.py:77]
- [x] [Review][Patch] `low_value_budget_tradeoff` 仅检查结构化 `over_budget` decision [rpg_engine/context/diagnostics.py:523]
- [x] [Review][Patch] 在 32 条上限内优先保留 source-failure unavailable sentinel [rpg_engine/context/diagnostics.py:543]
- [x] [Review][Patch] scope-only `tick_rules` 不得掩盖缺失 tick/trigger metadata [rpg_engine/context/diagnostics.py:411]
- [x] [Review][Patch] memory freshness diagnostics 只消费真实 `kind=memory` evidence，排除 section rows [rpg_engine/context/diagnostics.py:458]
- [x] [Review][Patch] hidden-only/absent high-value non-oracle 测试必须在紧预算下产生非空 signal [tests/test_current_native_visibility.py:1262]
- [x] [Review][Patch] 增加 visible relationship/progress 指向 hidden endpoint/scope 的 player diagnostics 证据 [tests/test_current_native_context.py:865]
- [x] [Review][Defer] Second review reaffirmed：plot post-filter 释放预算后不重选较低优先级 source section [rpg_engine/context_builder.py:545] — deferred, pre-existing

## 开发说明

### 来源上下文

- Epic 3 要求 `ContextBuildResult` 成为 prompt/render/query/advisory 共用且可审计的 Context Slice，并在 collection/query 阶段排除 hidden / GM-only 内容。来源：`_bmad-output/planning-artifacts/epics.md#Epic 3`。
- Story 3.6 明确要求 budget decisions、included/omitted、high-value missing signals、结构化 context usability warning 和五组 focused regression。来源：`_bmad-output/planning-artifacts/epics.md#Story 3.6`。
- PRD FR-10 / FR-11 / FR-12 要求 context 准确、相关、inspectable，遵守 hidden boundary，并让 long-term summary 有 evidence/freshness。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Architecture AD-5 要求 `ContextBuildResult` 包含 visibility、provenance、budget、included/omitted 和 missing signals；AD-10 要求 context foundation 变更带 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- 本 story 是一次 context assembly/runtime result 的 diagnostics，不是 Story 5.3 的全 Campaign author-facing usability/capability doctor，也不是 Story 3.7 的跨 Campaign player-safe loop smoke。

### 当前实现状态

- `ContextBuildResult` 已有稳定顶层字段 `contract`、`scope`、`request`、`budget`、`completeness`、`loaded_items`、`omitted_items`、`sections`、`markdown`；优先在 `budget` 和 `completeness` 内做 additive evidence，避免顶层 contract 分叉。
- `apply_budget()` 已按 required first、optional priority/token/key 排序选择 sections，但当前 `budget` 仅列 included section token map 和 `trimmed`，未完整记录每个 section decision、required-over-budget 或 high-value omitted signal。
- `ContextCollector` 已要求 source、visibility、provenance、budget behavior；relationship、progress、world setting、memory collectors 已把最终可见记录存入 `BuildState` 并产生 loaded / omitted evidence。
- `context_runs.output_json` 已存完整 `ContextBuildResult`，`context_items` 已存 loaded/omitted item rows；本 story 不需要 schema migration。
- `ContextBuildResult.completeness.missing_signal_evidence` 已承载 blocking、confirmation 和 memory advisory evidence；应扩展/归一化现有 surface，不要新建第二套事实来源。
- 当前 render 在 player view 对 contract/scope/request/completeness/items/sections/markdown 执行 redaction；diagnostics 仍必须从 visibility-safe inputs 生成，不能只依赖这层最终清洗。

### 前序故事情报

- Story 3.1 固化 `ContextBuildResult` 和 context audit contract。
- Story 3.2 / 3.3 固化 player-safe collection/query/prompt 与派生 read-model hidden boundary。
- Story 3.4 新增 relationship/progress/plot signal context、结构化 omission categories 和 budget-linked plot signal filtering。
- Story 3.5 新增 memory provenance/freshness、generic fallback、projection generation/CAS、stable snapshot 和 bounded retry；最近提交 `fd6c5d3` 对 `context_builder.py`、collectors、memory/projection/tests 做了大幅加固，必须基于当前代码实现。
- Story 3.5 已经记录用户决定：`uv.lock` 与 external-intent investigation 保持 untracked，不纳入 story commit；当前 2026-07-10 intent Correct Course planning artifacts 属于 Story 4.1，也必须排除。

### 架构合规要求

- 风险级别：P0 context / hidden boundary 变更，已有 PRD、Architecture、Epic/Story planning；开发必须先写 focused RED tests，再最小实现并做三路 review。
- `data/game.sqlite` 仍是 current fact authority；context audit、quality warnings、memory summaries 和 reports 都是 diagnostics/derived evidence。
- 复用 `entity_access.py`、`relationship_access.py`、`progress_access.py` 与现有 memory helpers；不在 diagnostics 中直接复制 visibility、endpoint、progress 或 freshness 业务规则。
- 不触碰 SaveManager pending/confirm、intent/preflight、MCP profile、platform、validation/commit 或 Campaign schema。若实现发现必须修改这些边界，HALT 并走 correct-course。
- 不新增运行时依赖，不修改 migration，不写正式 current save package。

### 预计文件

- NEW `rpg_engine/context/diagnostics.py`：纯结构化、visibility-aware context quality warnings 和 budget/high-value helper。
- UPDATE `rpg_engine/context_builder.py`：在最终稳定 render pass 组装 additive budget/completeness evidence。
- UPDATE `rpg_engine/context_audit.py`：让 loaded / omitted audit rows 都保存既有 item token evidence；无需 migration。
- OPTIONAL UPDATE `rpg_engine/context/__init__.py`：仅在需要稳定内部 import/export 时更新。
- UPDATE `tests/test_context_quality.py`、`tests/test_current_native_context.py`、`tests/test_current_native_visibility.py`；仅在现有 focused fixture 更合适时扩展 relationship/progress tests。
- UPDATE `docs/architecture.md`、`docs/data-models.md`、`docs/component-inventory.md`、`docs/testing-and-quality-gates.md`。
- 不计划修改 `context/collectors.py`、access contract、memory/projection、CLI/MCP/prompt；如实际需要，必须先完整读取对应 UPDATE 文件并在 File List / gates 中说明。

### 测试要求

本节是 Story 3.6 gate 命令的唯一权威列表；上方任务只定义覆盖目标，避免重复维护命令。

首选 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_context_quality.py \
  tests/test_current_native_context.py \
  tests/test_current_native_visibility.py \
  tests/test_relationship_access.py \
  tests/test_progress_access.py \
  -p no:cacheprovider
```

Compatibility / regression gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_maintenance_tooling_coverage.py \
  tests/test_projection_service.py \
  tests/test_runtime.py \
  -p no:cacheprovider
```

最终仍运行 repository full suite、两个 canonical example campaign validate/test、Markdown links、`py_compile`、Ruff 和 `git diff --check`；任何 review patch 落地后，更早 full-suite 证据失效，必须重跑。

### 残余风险与明确非目标

- Hidden/export/AI egress：quality warning 和 budget signal 属于 player-visible evidence 新字段，必须用 current-native visibility gate 证明无 hidden existence oracle。
- 不做全包 Campaign quality scan、capability/smoke coverage doctor、成熟作者 UX；这些属于 Story 5.3。
- 不做跨 Campaign context + player-safe loop smoke；这属于 Story 3.7。
- 不做 prose、story taste、genre 或 aesthetic quality scoring。
- 不修改 memory schema、projection lifecycle、intent authority、player confirmation 或 write chain。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python 3.11+、stdlib `sqlite3` / `dataclasses`、pytest、Ruff、`ContextBuildResult`、access contracts 和 visibility/redaction helpers；不新增依赖或升级 API。

## Project Structure Notes

- diagnostics 放在 `rpg_engine/context/`，由 `context_builder.py` 在最终稳定 render pass 组装；不要在 CLI/MCP adapter 建第二套逻辑。
- budget selection 仍由 `context/sections.py::apply_budget()` 负责；diagnostics 只记录与解释决策，除非 RED test 证明选择算法本身违反 AC。
- 结构化 warning 只能描述可操作的 missing field / evidence，不复制整段 section/content。
- current-native audit/write tests 必须复制到 temp dir；正式 current package 只读。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-04.md`
- `_bmad-output/planning-artifacts/implementation-readiness-report-2026-07-04.md`
- `_bmad-output/implementation-artifacts/3-1-contextbuildresult-contract-and-audit.md`
- `_bmad-output/implementation-artifacts/3-2-player-safe-context-query-与-prompt-隐藏信息边界.md`
- `_bmad-output/implementation-artifacts/3-3-派生玩家视图与检索产物的隐藏信息边界.md`
- `_bmad-output/implementation-artifacts/3-4-relationship-progress-and-plot-signal-context.md`
- `_bmad-output/implementation-artifacts/3-5-long-term-memory-summary-provenance.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/source-tree-analysis.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/context_builder.py`
- `rpg_engine/context/sections.py`
- `rpg_engine/context/collectors.py`
- `rpg_engine/context_audit.py`
- `rpg_engine/entity_access.py`
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

- RED：新增 diagnostics import、budget decision 集成、audit loaded token、canonical alias/TEMP shadow、plot reconciliation、loaded stale memory 与 non-oracle 用例均先按预期失败；对应最小实现后逐项 GREEN。
- Focused：`64 passed, 8945 subtests passed in 226.24s`。
- Compatibility：`196 passed, 63 subtests passed in 12.43s`；仅作为 Story 3.5 memory/projection/runtime regression evidence，本 story 未修改 memory/projection code。
- Campaign smoke：`v1_minimal_adventure` 与 `small_cn_campaign` 的 validate/test 全部 `OK`。
- Docs/static：`checked 168 markdown files; local links ok`；`py_compile`、`ruff check .`、`git diff --check` 全部通过。
- Pre-review full suite：`759 passed, 9635 subtests passed in 475.31s`。
- First review post-patch RED/GREEN：新增 8 个 unit 路径与 1 个 current-native TEMP-shadow audit 路径先失败后通过；受影响的 6 个 current-native diagnostics/audit/visibility 用例通过。
- Post-first-review focused：`72 passed, 8945 subtests passed in 231.55s`。
- Second review post-patch RED/GREEN：4 个实现路径先失败后通过；完整 unit gate `37 passed, 20 subtests passed`，4 个受影响 current-native diagnostics/audit/visibility 用例通过。
- Final focused：`75 passed, 8945 subtests passed in 237.67s`。
- Final compatibility：`196 passed, 63 subtests passed in 13.04s`。
- Final Campaign smoke：`v1_minimal_adventure` 与 `small_cn_campaign` 的 validate/test 全部 `OK`。
- Final docs/static：`checked 168 markdown files; local links ok`；`py_compile`、`ruff check .`、`git diff --check` 全部通过。
- Final repository full suite：`770 passed, 9635 subtests passed in 497.64s`。

### Completion Notes List

- 新增 `context/diagnostics.py`，在既有 `budget` / `completeness` 路径提供确定性 section decisions、required overflow、最多 8 条 high-value missing signals 与最多 32 条结构化 quality warnings。
- warnings 复用 visibility-safe entity/world-setting state、relationship/progress access records、最终 loaded/omitted memory freshness evidence；alias 仅批量查询 canonical `main.aliases`，并保留 final player redaction 作为 defense-in-depth。
- player hidden probe 覆盖 result/audit/high-value diagnostics 不泄漏，并以相同唯一查询验证 hidden-only 与 absent 的 advisory evidence 等价；GM/maintenance 仍可查看安全结构 warning。
- audit 保持 opt-in/同 snapshot，`context_runs.output_json` 自然保存 additive evidence，`context_items` included/omitted rows保存安全 token evidence；无 schema/migration 或新事实表。
- 未新增或改变 CLI、MCP、prompt 的公开参数/语义，因此无需更新 `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`。
- 保留 Story 3.5 render-state copy、generation snapshot/bounded retry/ABA 与 non-memory plot signals；未修改 collectors、memory/projection、access contracts、write chain 或正式 current save package。

### File List

- `_bmad-output/implementation-artifacts/3-6-context-budget-and-quality-diagnostics.md`
- `_bmad-output/implementation-artifacts/3-6-context-budget-and-quality-diagnostics.validation-report.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/context/diagnostics.py`
- `rpg_engine/context_audit.py`
- `rpg_engine/context_builder.py`
- `tests/test_context_quality.py`
- `tests/test_current_native_context.py`
- `tests/test_current_native_visibility.py`

### Implementation Plan

- 先为 budget decisions、required-over-budget、高价值遗漏和结构 warning 写 RED tests。
- 新增小型 diagnostics helper，并在最终稳定 `ContextBuildResult` render pass 组装 additive evidence。
- 加固 player-safe non-oracle、audit snapshot 与 current-native regressions。
- 同步 canonical docs，完成 focused/full/campaign/docs/static gates。

### Change Log

- 2026-07-10: Created Story 3.6 context budget and quality diagnostics with comprehensive implementation guardrails; status set to ready-for-dev.
- 2026-07-10: Implemented additive context budget/quality diagnostics, audit token evidence, player-safe non-oracle regressions, canonical docs, and all pre-review verification gates; status set to review.
- 2026-07-10: First three-way code review triaged 0 decisions, 11 patches, 1 pre-existing defer, and 5 dismissals; applied every patch and retained review status pending the mandatory second review.
- 2026-07-10: Second three-way code review triaged 0 decisions, 7 patches, 1 reaffirmed pre-existing defer, and 3 dismissals; applied every patch and synchronized story/sprint to done pending final gates.
- 2026-07-10: Final focused/compatibility/campaign/docs/static/full gates passed; Story 3.6 is done and ready for commit/push.
