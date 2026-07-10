---
title: '持续自动 review 收敛规则'
type: 'chore'
created: '2026-07-11'
status: 'done'
route: 'one-shot'
---

# 持续自动 review 收敛规则

## Intent

**Problem:** `AGENTS.md` 原先要求第二轮 review 仍有 patch 时停止，导致已授权的自动 story cycle 反复要求用户继续。

**Approach:** 将默认策略改为基于 triage、可复现证据与完整 verification gates 的持续收敛循环，只在 `decision-needed`、歧义、安全/范围边界或有证据的无进展 blocker 时停止。

## Suggested Review Order

- 先核对自动 patch、verification 与 review 的收敛和停止边界。
  [`AGENTS.md:113`](../../AGENTS.md#L113)

- 再核对授权复用、安全优先级与 failing-gate 提交禁止。
  [`AGENTS.md:163`](../../AGENTS.md#L163)
