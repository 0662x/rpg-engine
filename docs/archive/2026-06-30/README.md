# 2026-06-30 Archive

本目录保存 2026-06-30 的一次性设计、评审和测试材料。它们用于追溯背景，不再作为当前实现的权威入口。

当前文档入口：[`../../README.md`](../../README.md)
归档总入口：[`../README.md`](../README.md)

## Reports

- [`system-recommendations.md`](system-recommendations.md)：AIGM 系统建议报告。
- [`ux-design.md`](ux-design.md)：玩家/GM UX 设计稿。
- [`author-kit-design.md`](author-kit-design.md)：Author Kit 设计稿。
- [`author-kit-implementation-plan.md`](author-kit-implementation-plan.md)：Author Kit 实施计划。
- [`bug-report.md`](bug-report.md)：2026-06-30 多轮 bug/修复测试记录。
- [`ux-simulation-report.md`](ux-simulation-report.md)：UX 行为模拟与恶意/异常输入测试报告。

## Historical Design

- [`historical/DOCUMENTATION_BASELINE.md`](historical/DOCUMENTATION_BASELINE.md)：文档整理前的历史基线记录。
- [`historical/AI_GM_ENGINE_MODULAR_REDESIGN.md`](historical/AI_GM_ENGINE_MODULAR_REDESIGN.md)：模块化改造历史设计。
- [`historical/AI_GM_ENGINE_UPGRADE_DESIGN_V2.md`](historical/AI_GM_ENGINE_UPGRADE_DESIGN_V2.md)：旧 V2 升级设计。

## Generated Output

- [`generated/stdout-report.md`](generated/stdout-report.md)：一次性生成输出记录。

## Reading Notes

- 这些文档包含多轮“先发现、后修复”的记录。判断当前状态时，应优先看当前 specs、README 和测试结果。
- 当前全量测试基准已更新到 `195 tests OK`。
- 已确认当前实现的长期边界已整理到 [`../../specs/kernel-requirements.md`](../../specs/kernel-requirements.md)、[`../../governance/content-generation.md`](../../governance/content-generation.md) 和 [`../../architecture/game-engine.md`](../../architecture/game-engine.md)。
