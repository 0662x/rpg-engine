# Story 6.9 Validation Report

生成日期：2026-07-17

## 结论

**PASS — ready-for-dev**

- Critical misses：2，均已自动吸收到测试/实现要求
- Decision-needed：0
- 明确增强：4，已全部体现在 Story 正文
- 优化建议：2，已纳入测试与范围说明
- 剩余 blocker：0

Story 与已批准的 Epic 6 / Correct Course、BND-03 P0 证据和权威边界一致，可以进入 `[DS] Dev Story`。

## Checklist Results

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| Story / Epic / sprint key | PASS | Story key 与 Epic 6 / sprint-status 的 `6-9-retired-entity-binding-fail-closed` 一致；用户显式选择 6.9。 |
| 用户价值与 AC 完整性 | PASS | 覆盖 retired/archived、ID/name/alias、foreign/stale/hidden/ambiguous/missing、active positive 与 temporary Save。 |
| Correct Course / BND-03 对齐 | PASS | Iteration 3 RED 已实证 retired location 返回 `ok=true`；Story锁定 committable pending前 fail closed。 |
| 架构与事实权威 | PASS | 当前 Save SQLite负责 lifecycle/visibility，external/internal AI、manifest、cache与candidate均无事实或确认权。 |
| 当前代码可操作性 | PASS | 已定位 binder exact/partial SQL只排 archived而允许 retired；无需 migration、依赖或surface改动。 |
| Reinvention prevention | PASS | 要求扩展 canonical binder owner，禁止 MCP/CLI/platform/SaveManager与action-specific平行特判。 |
| Query / fallback 范围 | PASS | 识别 `find_entity_candidates()` 同时服务 query arbitration；明确 binder-only active gate，并关闭 known non-active 经 free-text fallback绕过。 |
| Security / privacy | PASS | hidden/GM-only不得出现在 player候选列表/trace/message；non-active拒绝采用 bounded generic结果，不输出row详情。 |
| No-mutation / package safety | PASS | committable pending/claim/receipt、SQLite turn/event/facts、projection/events.jsonl不变；所有写入仅在temporary workspace。 |
| Previous story intelligence | PASS | 复用 Story 6.3 canonical slot owner与Story 6.4 owner/thin-surface模式，不复制authority。 |
| Scope control | PASS | 明确排除 Story 3.8、Stories 6.5–6.8、Hermes E2E、Coordinator、migration、dependency与rebaseline worktree。 |
| Required final gates | PASS | Focused、adjacent、Campaign、Markdown、py_compile、Ruff、diff-check与repository full pytest均锁定为最终clean-diff门。 |

## Fresh Validator 结果

- Critical 1：non-active partial entity match 也必须阻断 `entity_or_text` fallback；已纳入 Story既有“exact/partial全部路径”约束和 focused test。
- Critical 2：共享 `find_entity_candidates()` query consumer 必须有显式回归，证明 active-only 为 binder opt-in；已纳入 focused test。
- Enhancement：hidden DB-only name/alias/summary canary 与 lifecycle NFKC/unknown/empty矩阵均已纳入 focused test。
- Decision-needed：0。

## 已应用的明确增强

1. 把 lifecycle语义收紧为 normalized `status='active'` 才可 action bind，覆盖 canonical ID、name、alias、exact与partial分支，并对非规范大小写/Unicode边缘值fail closed。
2. 识别 `find_entity_candidates()` 还被 external entity query arbitration调用；Story改为 binder-only active lookup，禁止无意改变 query/context/render的retired历史读取语义或混入Story 3.8。
3. 明确 `entity_or_text` / `text_or_entity` 不能把当前SQLite已识别的 retired/archived row降级成自由文本后继续形成ready proposal，同时保留真正不存在自由文本的既有合同。
4. 把 no-mutation边界精确到 committable pending action、confirmation claim/receipt和authoritative Save/projection artifacts；clarification可沿用既有公开合同，但不能升级成proposal或commit authority。

## 优化与风险说明

- 新测试必须自包含，不得import未提交的 Iteration 3 `conftest.py` / automation support；现有rebaseline test只作RED evidence。
- active与non-active同名/alias、inactive exact与active partial、ID-shaped missing、hidden lifecycle组合是review高风险点；测试应证明exact优先级、generic failure与active positive不会被inactive row污染。

## Source Review

- `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Story 6.9
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-17.md` — §4.2、§8.2、§8.4
- `_bmad-output/test-artifacts/automation-validation-iteration-3.json` — BND-03
- `_bmad-output/test-artifacts/test-review.md`、`traceability-matrix.md`、`gate-decision.json`
- `_bmad-output/implementation-artifacts/6-4-atomic-pending-confirmation-claim-and-replay-classification.md`
- `docs/project-context.md`、`docs/architecture.md`、`docs/ai-intent-chain.md`、`docs/data-models.md`、`docs/testing-and-quality-gates.md`
- `rpg_engine/ai_intent/binder.py`、`visibility.py`、`entity_access.py`、`ai_intent/arbiter.py`
- 现有 binder、action-slot、current-native player、cross-Campaign与Iteration 3 tests

## Verification

- Story 文档结构与 key/status检查：PASS
- `sprint-status.yaml` YAML parse 与 Story 6.9 `ready-for-dev`：PASS
- `git diff --check`：PASS
- RED reproduction：Iteration 3 BND-03参数测试 `1 passed, 1 failed`，retired分支失败点为 `assert result["ok"] is False`
- Validation阶段未把RED当作完成证据；行为绿灯属于后续Dev Story与最终required gates。

## BMAD Provenance

- Menu：`[VS] Validate Story`
- Skill：`.agents/skills/bmad-create-story/SKILL.md`（完整读取）
- Checklist：`.agents/skills/bmad-create-story/checklist.md`（完整读取并执行）
- Customization resolver：prepend/append/on_complete为空；persistent fact为 `file:{project-root}/**/project-context.md`
- Config：`_bmad/bmm/config.yaml`
- Persistent context：`docs/project-context.md`
- Checklist要求fresh-context复核；只读Story validator已完成并返回2项Critical、2项Enhancement，均为范围内、无歧义改进并已自动吸收，无Decision。
