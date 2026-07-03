# AIGM CLI Spec V1

文档状态：**V1 规范，已由 `aigm` / `python3 -m rpg_engine` 执行**
目标：CLI 是 Kernel 能力的参考实现，也是 MCP 以外的最小可用入口。

## 1. 安装

本地源码：

```bash
python3 -m pip install -e .
python3 -m pip install -e ".[mcp]"
```

从 GitHub：

```bash
pipx install "git+https://github.com/<owner>/aigm-kernel.git"
```

从 PyPI，发布后：

```bash
pipx install aigm-kernel
```

带 MCP，发布后：

```bash
pipx install "aigm-kernel[mcp]"
```

未安装时可用：

```bash
python3 -m rpg_engine ...
```

## 2. Campaign

```bash
aigm campaign new ./campaigns/my_story --template small-cn
aigm campaign doctor ./campaigns/my_story
aigm campaign outline ./campaigns/my_story
aigm campaign explain field:visibility
aigm campaign check-ai ./campaigns/my_story
aigm campaign split ./campaigns/my_story --by type --dry-run
aigm campaign copy-example ./campaigns/v1_minimal_adventure
aigm campaign validate ./examples/v1_minimal_adventure
aigm campaign test ./examples/v1_minimal_adventure
```

- `campaign new`：从作者模板创建新剧本包。
- `campaign doctor`：作者向诊断，复用 validate 并补充修复建议、生成物混入、大文件和可维护性提示。
- `campaign outline`：把结构化剧本渲染成作者可读总览。
- `campaign explain`：解释字段、capability 或错误码。
- `campaign check-ai`：检查常见 AI 辅助创作问题；`--strict` 可把 warning 当作失败。
- `campaign split`：输出按类型拆分内容文件的 dry-run 计划；V1.1 不自动改文件。
- `campaign copy-example`：从安装包复制官方最小示例，供 pipx/PyPI 安装后直接试跑。
- `campaign validate`：检查剧本包结构、capability、引用、可见性、随机表、进度钟和 smoke 覆盖。
- `campaign test`：初始化临时存档，运行 runtime health 和 smoke tests。

## 3. Save

```bash
aigm save init ./examples/v1_minimal_adventure ./saves/my-run
aigm save inspect ./saves/my-run
aigm save validate ./saves/my-run
aigm save export ./saves/my-run --output ./my-run.aigmsave
aigm save import ./my-run.aigmsave ./saves/imported-run --yes
aigm save patch ./saves/my-run ./safe_patch.json
```

- `save init`：从剧本包生成初始存档。
- `save inspect`：查看存档当前 turn、地点、文件状态和表计数。
- `save validate`：只读校验存档健康，包含 SQLite、events.jsonl、snapshot、cards、search 和 projection 状态一致性。
- `save export/import`：导出/导入 `.aigmsave`。
- `save patch`：安全维护，不推进剧情。

`save patch` 不能绕过行动结算。普通玩家剧情推进必须使用 `player turn` 和 `player confirm`；developer/trusted 低层调试才使用 `play preview`、`play validate-delta`、`play commit --proposal-json`。

## 4. Play

`play *` 是 developer/trusted 低层 runtime 工具集，不是普通玩家默认入口。普通自然语言玩法使用第 6 节的 `player turn -> player confirm`。

```bash
aigm play preflight ./saves/my-run --user-text "Go to Warden Mira and ask about the bridge" --preflight-identity-profile message_only --message-id "qq:message:123" --platform qq --session-key "qq:user:456" --format json
aigm play start-turn ./saves/my-run --user-text "Look around" --mode query --submode scene
aigm play query ./saves/my-run scene
aigm play query ./saves/my-run entity "Warden Mira"
aigm play query ./saves/my-run context "What do I know about the bridge?"
aigm play act ./saves/my-run "Go to Warden Mira and ask about the bridge"
aigm play preview ./saves/my-run explore --target "Broken Seal Mark" --approach careful --user-text "Inspect the seal"
aigm play validate-delta ./saves/my-run ./turn_delta.json
aigm play commit ./saves/my-run ./turn_delta.json --proposal-json ./turn_proposal.json
aigm play ux-metrics ./saves/my-run
aigm play health ./saves/my-run --format json
```

- `preflight`：可信/开发链路的内部意图复核预热，只写 advisory cache；`candidate_bound` 用 `preflight_id` 消费，`message_only` 可按 `message_id/source_user_text_hash/platform/session_key` 消费。`start-turn`、`act` 支持 `--preflight-pending-wait-ms` 做短等待，硬上限 1000ms。
- `start-turn`：构建上下文并返回回合契约。
- `query`：只读查询，不推进时间。
- `act`：低层自然语言 preview 入口；可返回单 action preview，也可返回组合 plan 和 repair options；默认不保存。普通玩家自然语言不要首选它。
- `preview`：行动预演，不保存；JSON 输出包含 `status`、`ready_to_save`、`delta_draft`、`turn_proposal`、`player_message` 和 `repair_options`。
- `validate-delta`：通过 GMRuntime 校验 delta；会复用 preview delta 中的事件 payload 反推动作参数，也可显式传 `--action`、`--options-json`、`--context-json`。
- `commit`：保存已校验且已批准的 `TurnProposal` delta；普通玩家路径必须传 `--proposal-json`，自动备份并刷新 snapshot/cards/search。
- `ux-metrics`：输出 UX 观察指标，包括当前 turn、地点、intent 分布和场景可行动数量。
- `health`：运行只读 runtime health check。

自动化客户端必须只在 `ready_to_save=true`、`validate-delta` 通过且玩家/GM 确认后提交 delta，并必须把 preview 返回的 `turn_proposal` 一起传入。`status=needs_confirmation/clarify/blocked` 时不得调用 `commit`。

Legacy `validate delta` 仍保留，并默认调用 GMRuntime；需要旧式 schema-only 检查时使用 `--schema-only`。

## 5. Platform Sidecar

```bash
aigm platform start ./workspace --platform qq --session-key "qq:user:456" --message-id "qq:start:1" --actor-id "user:456" --user-text "开始游戏" --campaign campaigns/minimal --enable-prewarm --format json
aigm platform message ./workspace --platform qq --session-key "qq:user:456" --message-id "qq:message:123" --actor-id "user:456" --user-text "休息到早上" --enable-prewarm --drain --format json
aigm platform act ./workspace --platform qq --session-key "qq:user:456" --message-id "qq:message:123" --actor-id "user:456" --user-text "休息到早上" --enable-prewarm --format json
aigm platform act ./workspace --platform qq --session-key "qq:user:456" --message-id "qq:message:124" --actor-id "user:456" --user-text "去小溪" --enable-prewarm --drain-before-act --format json
aigm platform confirm ./workspace --platform qq --session-key "qq:user:456" --message-id "qq:confirm:124" --actor-id "user:456" --session-id "player_action:..." --format json
aigm platform metrics ./workspace --format json
aigm platform expire ./workspace --format json
aigm platform deactivate ./workspace --platform qq --session-key "qq:user:456" --message-id "qq:deactivate:1" --actor-id "user:456" --format json
```

- `platform message`：平台消息到达即触发 advisory prewarm；默认不等待内部 AI，`--drain` 只用于诊断/测试。真实异步预热需要长驻 sidecar 或插件进程调用 `PlatformSidecar.start()`。
- `platform start/act/confirm`：真实玩家链路 sidecar。首次成功调用后自动写 binding；过期后自动 inactive。
- `platform act` 会自动把同一条消息的 `message_id/platform/session_key/source_user_text_hash/preflight_pending_wait_ms` 传给标准 `player_turn`，但仍不接收 `external_intent_candidate`，也不暴露 delta/proposal。`--drain-before-act` 只用于诊断，让同一个一次性 CLI 进程先同步跑完队列；真实长驻 sidecar 不应依赖它。
- `platform act/confirm` 会先校验平台 binding gate；未绑定、过期、bot/self、命令、unsupported 或重复正式消息不会进入 `SaveManager`。正式执行使用 binding 的 `active_save`，不依赖全局 active save。
- `platform metrics`：输出 canary 指标，包括 prewarm drop reason、queue depth、worker average/P95、玩家可见 latency、clarification count、message-only cache used/hit-rate estimate。
- `platform expire/deactivate`：清理过期 binding 或手动让一个平台会话失效。
- 所有 platform prewarm 都是可丢弃加速旁路；queue full、AI timeout、worker error 只降级为没有预热，不影响普通玩家链路。

## 6. Player Entry

```bash
aigm player inspect ./workspace
aigm player campaigns ./workspace --refresh
aigm player start ./workspace --campaign campaigns/watch-camp --starter-save starters/watch-camp
aigm player new ./workspace --campaign campaigns/watch-camp --label "New Game 2"
aigm player saves ./workspace --refresh
aigm player current ./workspace --refresh
aigm player switch ./workspace save_20260701_001
aigm player duplicate ./workspace save_20260701_001 --label "Branch Test"
aigm player turn ./workspace "去 Old Bridge 看看"
aigm player turn ./workspace "休息到早上" --external-intent-candidate ./candidate.json --format json
aigm player confirm ./workspace --session-id player_action:... --format json
```

- `player start`：有 active save 时继续；没有 active save 时从 campaign 或 starter save 创建新存档并返回 onboarding。
- `player new`：创建并激活一个新存档。
- `player saves/current/switch`：列出、查看和切换 registry 中的玩家存档。
- `player duplicate`：复制现有存档，用于测试路线或分支。
- `player inspect/campaigns`：检查 workspace 和已登记剧情包。
- `player turn`：玩家安全自然语言入口；支持 host 级内部 AI 配置、`--external-intent-candidate` 和被动 `--preflight-id/--message-id/--platform/--session-key/--source-user-text-hash/--preflight-pending-wait-ms`，输出不暴露 delta/proposal。
- `player confirm`：保存 `player turn` 暂存的行动，必须传 `--session-id`，该值来自 `player turn` 返回的 `session_id`。
- `player act`：兼容别名，内部走 player turn 语义，但不接收 `external_intent_candidate`，不作为新普通玩法入口。

`player start/new/saves/current/switch/duplicate/inspect/campaigns` 只管理存档选择和创建，不推进剧情。玩家安全行动入口是 `player turn` + `player confirm`：`turn` 判断 query/action/clarify/block；action 只生成待确认行动，不保存；`confirm` 使用 `session_id` 保存。`player act` 只作为旧脚本兼容命令保留。developer/trusted 低层事实写入仍必须走 `play preview`、`play validate-delta`、`play commit --proposal-json`。

详见 [`player-entry-save-manager.md`](player-entry-save-manager.md)。

## 7. MCP

```bash
aigm mcp print-config ./workspace --default-save saves/my-run
aigm mcp serve --root ./workspace --default-save saves/my-run
aigm mcp print-config ./workspace \
  --default-campaign campaigns/watch-camp \
  --default-save saves/my-run \
  --default-starter-save starters/watch-camp \
  --registry-active
```

详见 [`mcp-adapter.md`](mcp-adapter.md)。

## 8. Legacy/Admin

旧命令仍保留，但不属于普通 V1 主路径：

```text
init
query
context
save-turn
render-current
render-cards
check
audit
package *
projection *
migrate *
plugin *
importer *
```

这些命令用于维护、兼容、测试或高级迁移；普通用户优先使用 `campaign`、`save`、`play`、`mcp`。
