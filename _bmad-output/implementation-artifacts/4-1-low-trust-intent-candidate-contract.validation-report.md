# Story 4.1 Validation Report

Story: `4-1-low-trust-intent-candidate-contract`

Validation-time status: ready-for-dev（创建期、实现前快照；不代表当前 review/done readiness）

## Checklist Result

已按 `.agents/skills/bmad-create-story/checklist.md` 完整复核 Story、Epic 4、PRD、两份 Architecture Spine、批准的 Sprint Change Proposal、external intent authority 调查、canonical intent/runtime/API/testing 文档、计划修改的 production/test 文件、外部 GM Skill 三个同步文件及最近 5 个 commit。结论：Critical 0、未处理 Enhancement 0、未处理 Optimization 0、decision-needed 0；Story 可进入 Dev Story。

## Critical Misses

- 无。Story 明确区分 `enabled + external`、`off + external`、`off + no external` 三分支，且只改变 route proposal authority。
- 无。Story 保留 Kernel schema、registry、binding、safety、preview、validation、pending、player confirm 与 commit authority；external/internal AI 均不取得事实、权限、玩家确认或提交权。
- 无。Story 要求 malformed、unsafe、unknown action、invalid query、missing/ambiguous binding、composite plan 均不得静默 fallback 或产生 pending。
- 无。Story 将 routed intent mismatch 降为诊断，同时明确保留 direct low-level `preview_action` 的 hard guard。
- 无。Story 明确所有写测试与真实 playtest 使用 temporary Save/copy，并保护 source Campaign、formal current Save 与正式 registry。

## Enhancements Applied

- 将共享 candidate contract 限定为 external candidate 与既有 internal review candidate，明确本 Story 不新增 resident ingress/advisory envelope。
- 将 malformed candidate 的错误形态按现有层级合同消歧：direct Python normalization 保持带字段路径的 `ValueError`，CLI/MCP 由既有 wrapper 转结构化 error，router 内 binding/safety 失败返回结构化 outcome；不扩大 SaveManager 或 public API surface。
- 补充禁止字段、来源伪造、AI supplied confirmation slots、invalid query、hidden target、composite plan 与 maintenance safety flag 覆盖。
- 补充 trace/provenance 要求：`mode`、`route_authority`、external/rules candidate、rules outcome、decision、selected/adopted outcome，同时保留兼容 `consensus_outcome`。
- 明确 routed mismatch 的推荐实现不得信任 caller-supplied context；direct low-level guard 不能因伪造 provenance 绕过。
- 补充 current-native temporary-copy playtest、外部 GM Skill 版本/三文件 mode matrix 验证与 adjacent regression suites。

## LLM Optimization

- 三分支 mode matrix、每类失败结果、生产修改边界、禁止修改边界、RED/GREEN 顺序与最终 required gates 均已显式列出。
- 对 `off + no external` hardening、Story 4.2-4.7、public signatures、schema/migration、新 coordinator 与大规模 intent tree 重构作了明确排除。
- 将 external GM Skill 标记为 repo 外批准同步 artifact，禁止复制进仓库或混入 Git commit。
- 将 Prompt version 固定为 `2026-07-11.internal-ai-off-external-primary`，避免实现后文档/Skill 语义漂移。

## Discovery Inputs

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-10.md`
- `_bmad-output/implementation-artifacts/investigations/external-intent-authority-investigation.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/mcp-contracts.md`
- `docs/cli-contracts.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/ai_intent/arbiter.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/ai_intent/adapters.py`
- `rpg_engine/runtime.py`
- `rpg_engine/intent_router.py`
- `tests/test_ai_intent.py`
- `tests/test_runtime.py`
- `tests/test_save_manager.py`
- `tests/test_mcp_adapter.py`
- `tests/test_v1_cli.py`
- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/SKILL.md`
- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/references/mcp-interface.md`
- `/Users/oliver/.hermes/skills/gaming/aigm-kernel-v1-gm/references/ai-intent-playtest.md`

## Validation Notes

- Catalog 路由：`[VS] Validate Story`，`bmad-create-story:validate`。当前 skill package 未提供独立 validate step file；依其唯一 validation 定义，使用已完整读取的 `checklist.md` 在 create 完成后进行 fresh-context adversarial validation，并生成本报告。
- Customization resolver 已再次运行：prepend/append 为空，persistent fact 仅为 `docs/project-context.md`；config、persistent fact 与 project context 均已完整加载。
- 未执行实现测试；此 gate 只验证 story readiness。Dev Story 必须从 focused RED 开始，并在任何后续 patch 后重跑所有失效 gates。
- 未进行外部 Web research；创建期 Story 计划不引入或升级 library、framework、external API、依赖、schema 或 migration。实现期 review 后仅收紧了仓库内既有 `intent_candidate.schema.json` 的 plan-step 合同与长度上限；本报告保留原验证 provenance，不替代最终门禁。
- 未发现需要用户选择的 improvement 或 decision-needed，因此 validation gate 关闭。
