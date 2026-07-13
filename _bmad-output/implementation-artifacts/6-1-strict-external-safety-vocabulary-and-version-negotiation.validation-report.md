# Story 6.1 Validation Report

Status: passed-with-improvements-applied

## 验证范围

- BMAD route：`[VS] Validate Story`（`bmad-create-story:validate`）。
- 目标：`6-1-strict-external-safety-vocabulary-and-version-negotiation.md`。
- Fresh validator 完整对照 Epic 6 / Story 6.1、PRD、两份 adopted Architecture Spine、2026-07-13 Correct Course、两份 intent 调查、canonical docs、当前 production/test code 与 Git history。
- 官方技术核验：JSON Schema Draft 2020-12 validation 与 Python stdlib canonical JSON 行为；不新增 dependency。

## 结果

- Critical：7，全部已应用。
- Enhancement：7，全部已应用。
- Optimization：2，全部已应用。
- `[Validation][Decision]`：0。
- 用户选择：`all`。

## 已应用改进

1. 补全 direct `build_context()`、`GMRuntime.start_turn()`、MCP `start_turn` 及 V1/legacy CLI 的真实 external-candidate 调用链。
2. 消除 SaveManager 语义矛盾：direct caller 传播 typed exception，只有 MCP/CLI command boundary 投影 public error dict。
3. 固定 `ValidatedExternalCandidate` + `ExternalContractEvidence` frozen carrier、`matched | legacy_unversioned` status 与 private active-contract skew seam。
4. 锁定 low-level router/arbiter raw-dict 为 internal compatibility API，并保留 profile/empty-text/pending guard 的既有优先级。
5. 增加 surface taxonomy、error owner、write authority 真源表及 `tests/test_surface_inventory.py` 回归门禁。
6. 增加不同 subprocess / `PYTHONHASHSEED` 的 digest 确定性、独立重算和变更传播门禁。
7. 将 legacy `context build`、V1 CLI 五条分支、MCP audit/redaction 与 Story 4.7 hash 收入可执行 final gates，移除 `py_compile` 占位符。
8. 固定 version/digest/count/flag-list 的 exact builtin types 与 bounds，canonical JSON 增加 `allow_nan=False`。
9. 将 Manifest 示例改为增量摘录，明确保留既有 fields/actions/queries，实际 wire 不得出现占位值。
10. 区分 tolerant internal/domain compatibility normalization 与 strict `legacy_unversioned` external ingress。
11. 固定 `ExternalIntentContractError` 的 public import path 和 prompt version `2026-07-13.intent-contract-v2-safety-v1`。
12. 为 manifest、strict ingress、Runtime/context、MCP、SaveManager、V1/legacy CLI 和 taxonomy 指定 test owner/file 与 observable。
13. 加入 `docs/component-inventory.md`，并明确 CLI recovery 复用 MCP/Python manifest，不新增 CLI command。
14. 增加高熵 sentinel 的 direct exception、MCP result/audit、CLI stdout/stderr 全链脱敏门禁。
15. 合并为唯一的“Ingress × Kernel result/evidence × direct/adapter observable × mutation”决策表。
16. 拆分 core、surface contract、shared regression 开发期门禁，final 仍运行 focused union 与 full pytest；避免对无 production caller 的 `save_manager.error_dict()` 制造空改。

## Clean Evidence

- Baseline commit 与 Story 一致：`1141404b2ddb6cc1f16c1126761d40d508f790ee`。
- Pre-implementation RED/core：`73 passed, 80 subtests passed`。
- VS 扩展前 Story-focused：`368 passed, 262 subtests passed`。
- VS 扩展后 Story-focused final union：`447 passed, 519 subtests passed in 267.21s`。
- Story 4.7 section SHA-256 保持 `27c2a9538c8b83d63d66a275631a222053fc4f94237c9fd1f3ce2dc0286e3f58`，标题、用户价值与三组 Acceptance Criteria 未改动。
- RPG Engine Story 与 Hermes H1–H4 仍分仓持有；Story 6.1 未吸收 Hermes reconnect/consumer/next-model-turn/E2E 责任。
- 无 UX artifact、无 dependency 变更、无 PRD/Architecture Spine 重做、无新 product decision。
