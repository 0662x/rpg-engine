# BMAD 残余风险 Backlog

文档状态：**ACTIVE：Round 4B extracted backlog**

日期：2026-07-04

本文件从旧 [current-code-multi-expert-review](../../docs/architecture/current-code-multi-expert-review.md)
中摘取仍有后续价值的残余风险。旧评审早期的 67/100 结论已被后续 hardening 部分更新；
本 backlog 不重新宣告已修复风险，只保留最终复评仍明确标出的后续项。

## 使用原则

- 本文件是 BMAD planning artifact，不是当前实现合同。
- 当前行为仍以代码、测试和 `docs/` canonical 文档为准。
- 风险关闭时，应同时更新对应测试、质量门禁和 canonical 文档。
- 完整 `TurnCoordinator` 设计或薄实现不能让现有 player workflow、profile gate、
  atomic write 和 eval metrics 倒退。

## R1 Security / Privacy

残余风险：

- hidden 派生物、player export 和 full maintenance export 的隔离仍值得专项加固。
- 外部 AI egress 需要持续保持服务端 policy、redaction 和审计边界。
- 普通 player profile 不能获得 hidden / GM / maintenance 视图或低层写入工具。

建议证据：

- hidden visibility / player export 专项测试。
- AI egress policy / redaction 测试。
- MCP player profile 拒绝 hidden、maintenance 和 low-level tool 的 contract tests。

## R3 Reliability

残余风险：

- 文件级 atomic write 和 archive staging 已有第一轮 hardening，但 restore drill 还可更强。
- 大型 archive、import、backup 和 restore 需要继续覆盖中断、半写和污染当前 save 的故障模式。

建议证据：

- backup / restore fault injection。
- archive import interruption tests。
- restore 失败不删除当前可用存档的回归测试。

## R4 Quality / Release

残余风险：

- skipped tests 需要豁免清单，区分外部依赖缺失、长期保留但非默认门禁和应恢复执行。
- coverage 需要按模块设置增长目标，不能只用全局百分比掩盖关键链路。
- wheel / sdist / installed CLI smoke / package data 检查应保持可复现。

建议证据：

- `allowed_skips` 或等价豁免机制。
- 按模块覆盖率趋势。
- 发布包内 eval resources、fixtures 和 CLI entry point 的 installed smoke。

## R5 Eval / Metrics

残余风险：

- eval report 已具备基础命令和 metrics，但仍需要版本化输出与历史趋势对比。
- 需要更明确地比较不同提交之间的 intent、MCP transcript、retrieval/context 和 state audit 指标。

建议证据：

- 带版本号的 eval report artifact。
- 历史趋势比较命令或 CI artifact。
- 真实 agent trace / prompt injection / schema robustness 扩展集。

## R7 Authoring / Rules

残余风险：

- random/dice 数据化切片已完成，但 declarative action spec 需要第二个非 random 示例。
- 完整 authoring / rules 数据化仍是后续工作，不能在 V1 主线中变成作者写代码。
- 作者 smoke tests 应继续覆盖 hidden 不泄露、clock 触发正确、palette 不越权实体化等质量点。

建议证据：

- 第二个非 random declarative action spec 示例。
- 对应 preview / commit / validation / docs tests。
- 作者级 narrative quality smoke。

## Player Session / Concurrency

残余风险：

- pending action 的 session、过期、actor binding 和并发冲突提示仍需明确语义。
- UI / Agent 需要更清楚地区分 clarification、pending proposal、player confirmation 和 expired action。

建议证据：

- pending action session contract tests。
- stale session / wrong actor / concurrent confirmation 回归。
- 文档同步到 [AI 意图链](../../docs/ai-intent-chain.md)、[MCP 合同](../../docs/mcp-contracts.md)
  和 [CLI 合同](../../docs/cli-contracts.md)。

## TurnCoordinator Guardrail

完整 `TurnCoordinator` 可以继续设计或薄实现，但必须保持：

- 当前 `player_turn -> player_confirm` 普通玩家闭环。
- MCP / CLI profile gate。
- hidden / visibility gate。
- atomic write 与 archive staging 的可靠性边界。
- eval CLI 和 metrics 不倒退。

任何 coordinator 改动都应先写边界测试，再缩短 Runtime / preview / render / projection / CLI / MCP
之间的重复 owner 面。
