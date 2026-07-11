# Story 4.2 Validation Report

Story: `4-2-ai-latency-policy-and-safe-degradation`

Validation-time status: ready-for-dev（实现前快照，不代表 review/done readiness）

## Checklist Result

已按 `.agents/skills/bmad-create-story/checklist.md` 重新检查 Story、Epic 4、PRD FR-6、Architecture AD-8、获批 Sprint Change Proposal、previous Story 4.1、canonical intent/CLI/MCP/testing 文档、现有 AI provider/policy/config/router/preflight/platform 代码、`tests/test_ai_helper.py` 及最近 5 个 commit。

结论：Critical 0、未处理 Enhancement 0、未处理 Optimization 0、decision-needed 0；Story 可进入 Dev Story。

## Critical Misses

- 无。Story 明确区分 soft wait evidence、单次 operation 的 hard total deadline、background target 与 late result discard。
- 无。Story 明确 `consensus` timeout/unavailable 不能转换成显式 `off`，也不能授予 external candidate `external_primary` route authority。
- 无。Story 保留 Story 4.1 的三分支 mode matrix，以及 schema、binder、resolver、preview、validation、pending、confirm 与 commit gates。
- 无。Story 禁止新依赖、async framework、coordinator、schema/migration 与正式 Save/Campaign/registry 修改。

## Enhancements Applied

- 将 hard timeout 明确为 primary、fallback、parse 与 normalization 共享的 monotonic total budget，防止当前 fallback 再获得完整 timeout。
- 将 soft wait 明确为 execution/observability policy，不是新的 route 或 permission mode；允许继续等待到 hard deadline，但必须留下结构化 evidence。
- 要求 timeout 分类具备结构化 status/reason，不能只靠英文 error substring；同时保留既有错误文本兼容。
- 要求 hard deadline 后返回的 schema-valid payload 也必须丢弃，不能进入 normalization、arbitration、pending 或 commit。
- 补充 preflight pending timeout、late-ready、single-use、identity/hash/provider/model mismatch 与 platform queue/drop reason 回归。
- 修正 focused gate 的真实文件名为 `tests/test_ai_helper.py`。

## Scope and Architecture Validation

- P0 规划证据完整：PRD FR-6、Architecture AD-8、Epic 4 Story 4.2 与获批 Correct Course 均明确支持本改动。
- 推荐实现复用现有 `AIHelperPolicy`、`InternalAIService`、`AIHelperResult`、`apply_unavailable_internal_policy()`、preflight cache 与 platform prewarm；不另建第二套业务路径。
- `intent_timeout` 继续作为 caller hard budget；默认候选从当前 8 秒与 PRD 15 秒目标对齐时，必须同步现有 config/CLI/MCP tests 与 canonical docs，但不扩张 default player profile 的 per-call override 权限。
- Background 只验证现有 advisory/prewarm scheduling 与 timeout evidence；Resident Advisory Envelope、正式 coordinator 和 helper 大迁移仍属于 Story 4.4-4.5。

## Discovery Inputs

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-10.md`
- `_bmad-output/implementation-artifacts/4-1-low-trust-intent-candidate-contract.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/ai/defaults.py`
- `rpg_engine/ai/config.py`
- `rpg_engine/ai/policy.py`
- `rpg_engine/ai/provider.py`
- `rpg_engine/ai_intent/internal_review.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/preflight_cache.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/platform_sidecar.py`
- `tests/test_ai_helper.py`
- `tests/test_ai_intent.py`
- `tests/test_platform_prewarm.py`
- `tests/test_platform_ai_simulation.py`

## Validation Notes

- Catalog 路由：`[VS] Validate Story`，`bmad-create-story:validate`。
- Skill package 未提供独立 validate step file；依其 validation 定义，重新运行 customization resolver、加载 persistent fact/config，并使用已完整读取的 `checklist.md` 执行 fresh validation。
- Customization resolver 成功：prepend/append 为空，persistent fact 为 `docs/project-context.md`，`on_complete` 为空。
- 未运行实现测试；本 gate 只验证 story readiness。Dev Story 必须从 RED characterization 开始。
- 未执行外部 Web research：本 Story 不新增/升级 library、framework、external API 或依赖，只复用 Python 3.11+ 标准库与仓库现有 timeout 实现。
- 未发现需要主观方案选择或用户决策的 validation finding；所有明确修正已直接并入 Story。
