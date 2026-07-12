# Story 4.6 Validation Report

Status: passed-with-improvements-applied

## 验证范围

- BMAD route：`[VS] Validate Story`（`bmad-create-story:validate`）。
- 目标：`4-6-entity-relationship-and-progress-advisory-review.md`。
- Fresh validator 完整对照 Epic 4 / Story 4.6、PRD、两份 Architecture Spine、Correct Course §4.5、previous Story 4.5、canonical docs 与现有 advisory/access/proposal/content code。

## 结果

- Critical：3，全部 `[Validation][Patch]`，已应用。
- Enhancement：4，全部 `[Validation][Patch]`，已应用。
- Optimization：2，全部 `[Validation][Patch]`，已应用。
- `[Validation][Decision]`：0。
- 总应用改进：9。

## 已应用改进

1. 区分 entity/relationship create 与 update 的 target existence/currentness 语义，避免 create 分支被 missing-target 规则错误阻断。
2. 为六个 suggestion family 固定实际 preflight、required gate、next owner 与 application eligibility；没有现成 owner 的 alias/memory/progress definition 不得猜测 application 权威。
3. 移除所有对 proposal queue 持久化或 create-only 条件修改的入口；4.6 只做 pure artifact/projection，5.7 保留完整 lifecycle ownership。
4. 将 artifact 深度不可变要求收紧为 exact frozen nested records/tuples 与 defensive serialization。
5. 固定 schema、operation、disposition、authority、required gate 与 next-owner vocabulary，未知 token fail closed。
6. 限制 report/context recall 为 caller 显式传入 artifact 的 pure projection，不接 queue、storage 或 persistent collector。
7. 补充两个 canonical Campaign 的四条可复制命令。
8. 澄清“六个 suggestion family”及 entity/relationship create/update 分支矩阵。
9. 将 authority bypass 测试整理为 queue lifecycle、apply、validation/commit、provider 的最小 no-call matrix。

## Clean evidence

- Baseline commit 与当前 Story 4.5 completion commit 一致。
- Sprint status、规划 artifact、previous Story 与所有列出的现有测试/UPDATE 文件路径一致。
- 无缺失 source document、无 dependency/范围扩大、无 decision-needed。
