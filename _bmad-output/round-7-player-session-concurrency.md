# Round 7 Player Session / Concurrency Hardening

文档状态：**CURRENT：BMAD Round 7 implementation report**

日期：2026-07-04

## 目标

本轮处理 Round 6 后确认的 Player Session / Concurrency 残余风险：pending action 的过期、
actor binding、平台会话确认边界和文档同步。目标是先把普通玩家确认门钉牢，不启动
`TurnCoordinator` 大改。

## 实现范围

- `SaveManager.player_turn()` 写 pending action 时新增：
  - `expires_at`
  - `ttl_seconds`
  - 可选 `actor_id_hash`
- `SaveManager.player_confirm()` 新增：
  - pending action TTL 检查；过期时清理 pending action 并拒绝提交。
  - actor identity hash 校验；平台路径若绑定 actor，确认必须来自同一 actor。
- `platform_session_metadata()` / `validate_pending_platform_session()` 扩展 actor identity。
- `PlatformSidecar` 新增：
  - `player_turn` / `player_confirm` 转发 `actor_id` 给 `SaveManager`。
  - platform entry gate 拒绝 `actor_mismatch` 和 `missing_actor_id`。
  - pending action / clarification conflict 检查纳入 actor hash。
- `game_session.should_prewarm_message()` 新增 actor gate，避免后台 prewarm 处理同一绑定会话中的其他 actor。

## 保持不变

- 纯 CLI / MCP 普通路径没有 actor 概念，不强制 actor identity。
- 默认玩家保存仍必须走 `player_turn -> player_confirm`。
- `player_turn` 仍只写 pending action，不提交事实。
- `player_confirm` 仍会校验 active save、session id、platform/session identity 和 proposal 完整性。
- 新 TTL 不改变 runtime delta、proposal、commit 或 projection 行为。

## 测试覆盖

新增/更新测试：

- pending action 写入 `expires_at`。
- expired pending action 被 `player_confirm` 拒绝并清理。
- pending action actor identity 缺失/不匹配时拒绝确认。
- platform sidecar 对同一绑定 session 的 wrong actor 返回 `actor_mismatch`。
- 既有 save/session/platform mismatch 和确认成功路径继续通过。

## 文档同步

已更新：

- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/ai-intent-chain.md`
- `docs/save-and-campaign-packages.md`
- `_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`

## 残余风险

- UI / Agent transcript 仍可进一步细化 expired action、wrong actor、pending clarification 和 pending proposal
  的展示文案。
- 如果后续支持多人或多 actor 同一平台会话，需要先设计 party/session 模型；当前实现是单 actor binding。

## 验证

已执行：

```bash
python3 -m pytest -q tests/test_package_save_condition_coverage.py tests/test_save_manager.py tests/test_platform_sidecar.py tests/test_platform_prewarm.py tests/test_mcp_adapter.py
python3 -m pytest -q
python3 -m ruff check rpg_engine/save_manager.py rpg_engine/platform_sidecar.py rpg_engine/game_session.py tests/test_package_save_condition_coverage.py tests/test_platform_sidecar.py
git add -N README.md docs _bmad-output rpg_engine tests
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

结果：

- Focused gate：`54 passed, 28 subtests passed`
- Full pytest：`450 passed, 483 subtests passed`
- Ruff：`All checks passed!`
- `git diff --check`：通过
- Markdown links：`checked 102 markdown files; local links ok`
