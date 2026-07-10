# Story 3.6 Validation Report

Story: `3-6-context-budget-and-quality-diagnostics`

Status: ready-for-dev

## Checklist Result

已按 `.agents/skills/bmad-create-story/checklist.md` 完整复核 story、Epic 3、PRD FR-10 / FR-11 / FR-12、两份 Architecture Spine、Story 3.5、canonical context docs、当前 `ContextBuildResult` / audit / access-contract 实现与最近提交。Fresh-context validator 初始结论为 Critical 0、Enhancement 3、Optimization 0、LLM optimization 1；用户选择 `all` 后已全部应用。最终剩余项为 0 / 0 / 0 / 0，Story 可以进入 Dev Story。

## Critical Misses

- 无。Story 明确要求 budget decisions、included / omitted evidence、high-value missing signals 与结构化 quality warnings，同时锁定 collection/query-time hidden filtering 和 player-safe non-oracle 边界。
- 无。Story 明确复用 `ContextBuildResult`、`context_runs` / `context_items`、Entity / Relationship / Progress access contracts 和 Story 3.5 memory freshness evidence，不新建平行业务链、事实来源或 SQLite schema。
- 无。Story 明确把 diagnostics 保持为 advisory evidence，不改变 `allow_proceed`、player confirmation、validation、commit 或 Save fact authority。
- 无。Story 把全 Campaign author doctor、跨 Campaign player loop、prose/taste scoring、intent authority 和 memory/projection lifecycle 排除在范围外。

## Enhancements Applied During Validation

- 已把 budget additive shape 收紧为 `over_limit`、`overflow_tokens`、`utilization`、`decisions` 和 `omitted_sections`，并要求 required overflow / zero-edge 可序列化。
- 已加入 alias lookup 的 visible-id batch 查询要求，避免 N+1、whole-Campaign 或 maintenance 全集扫描。
- 已加入 `context_audit.py` loaded-item `estimated_tokens` 证据修复，保持现有表结构和 audit opt-in。
- 已明确 quality diagnostics / high-value advisory 不得改变既有 `allow_proceed`、confidence、missing-required 或 confirmation decision。
- 已明确当前未提交 external-intent Correct Course、investigation 与 `uv.lock` 属于其他工作链，Story 3.6 commit 必须使用显式 pathspec 排除。

## Applied Improvement Choices

1. 已固定 quality warning 唯一路径为 `completeness.quality_diagnostics`，high-value signal 唯一追加到 `completeness.missing_signal_evidence`。
2. 已将 high-value 判定固定为 effective priority `>= 70` 或 required-token overflow，定义去重键、确定性排序与最多 8 条。
3. 已明确 required-over-budget 使用经最小 500 clamp 后的 effective `budget.limit`，raw `requested` 仅作输入证据。
4. 已把 gate 命令收敛到“测试要求”单一权威列表，由任务引用覆盖目标。

## LLM Optimization

- 任务按 budget evidence、quality warning、visibility、audit、docs、tests 分组，每组映射 AC。
- 每个 warning source 都指向现有可复用 contract，并同时列出禁止复制的业务规则和明确非目标。
- UPDATE / NEW 文件、focused gates、HALT 边界与 prior-story snapshot constraints 均直接可执行。

## Discovery Inputs

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
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

## Validation Notes

- 未执行实现测试；此 gate 只验证 story readiness。Dev Story 必须先补 RED coverage，再运行 story 中的 focused/full/campaign/docs/static gates。
- 未进行外部 Web research；story 不引入新库、新 API、依赖或版本升级。
- 两个较宽范围 validator 尝试未在 bounded wait 内返回；第三个 bounded fresh-context validator 已返回上述 3 项 enhancement 与 1 项 LLM optimization。
- 2026-07-10：用户选择 `all`，四项均已应用，validation gate 关闭。
