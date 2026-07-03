# AIGM MCP Adapter Spec V1

文档状态：**V1 规范，已由 `aigm mcp print-config` 和 `rpg_engine.mcp_adapter` 执行**
目标：让 AI 客户端通过 MCP 调用 AIGM Kernel。
边界：MCP Adapter 是薄适配层，只转调 V1 runtime/validator，不是后端、插件系统或模型代理。

## 1. 安装

本地源码开发：

```bash
python3 -m pip install -e ".[mcp]"
```

从 GitHub：

```bash
pipx install "aigm-kernel[mcp] @ git+https://github.com/<owner>/aigm-kernel.git"
```

从 PyPI，发布后：

```bash
pipx install "aigm-kernel[mcp]"
```

## 2. 启动

MCP 只通过配置好的 root 访问 campaign/save。工具参数中的 campaign/save 必须是 root 下的相对路径。

```bash
aigm mcp serve \
  --root /path/to/workspace \
  --default-campaign campaigns/watch-camp \
  --default-save saves/my-run \
  --default-starter-save starters/watch-camp \
  --registry-active
```

AI Helper 统一使用 `--ai-provider`、`--ai-model`、`--ai-timeout` 设置默认值，并通过 profile 控制启用范围：

```bash
# 推荐日常配置：只开启只读语义辅助；确定性状态审计仍保持开启
aigm mcp serve --root /path/to/workspace \
  --ai-profile balanced \
  --ai-provider deepseek \
  --ai-model deepseek-v4-flash

# 全量模型辅助：语义、模型状态审计、Archivist
aigm mcp serve --root /path/to/workspace --ai-profile full
```

profile 有 `off`、`balanced`、`full`。各功能的 `--semantic-*`、`--state-audit-*`、`--archivist-*` 参数优先于 profile，可单独覆盖。`full` 会增加每回合延迟和模型调用量，不建议作为默认值。

MCP 调用 profile 和 AI profile 是两件事：

- 默认 `player` MCP profile 只能走玩家安全入口和只读工具。普通外部 AI 应优先使用 `player_turn`、`player_confirm`。
- `developer`、`trusted_gm`、`maintenance`、`admin` 才能直接调用低层 `preview_action`、`validate_delta`、`commit_turn`。
- `player_turn` 可以接收后台 `external_intent_candidate`，这是标准玩家链路的低信任外部候选输入，不是玩家可见字段。
- 每次调用低层工具传入 `intent_ai`、`intent_provider`、`intent_model`、`intent_timeout` 属于 intent override；默认 `player` profile 会拒绝，开发/可信 profile 才能使用。
- `preview_from_text` 是低层 natural-language preview primitive，不再作为普通玩法主入口。低信任玩家入口应使用 `player_turn`；`player_act` 仅保留为兼容 wrapper。

开发/可信 profile 中的 `external_intent_candidate` 采用 visible-external independent review：internal AI 会看见 external candidate，但只能把它当低信任输入；internal AI 必须基于玩家原文和玩家可见上下文重新复核，并输出 agreement/disagreements/external_candidate_quality。它不是 blind review，也不是 external AI 说了算。

生成 AI 客户端配置：

```bash
aigm mcp print-config /path/to/workspace \
  --default-campaign campaigns/watch-camp \
  --default-save saves/my-run \
  --default-starter-save starters/watch-camp \
  --registry-active
```

输出形态：

```json
{
  "mcpServers": {
    "aigm-kernel": {
      "command": "aigm",
      "args": [
        "mcp",
        "serve",
        "--root",
        "/path/to/workspace",
        "--default-campaign",
        "campaigns/watch-camp",
        "--default-save",
        "saves/my-run",
        "--default-starter-save",
        "starters/watch-camp",
        "--registry-active"
      ]
    }
  }
}
```

### Hermes Agent 本机接入

Hermes Agent 读取 `~/.hermes/config.yaml` 的 `mcp_servers`。本机当前 Isekai Farm V1 链路配置为：
这里列出 `intent_preflight` 只是注册 MCP 工具，不代表 Hermes/QQ 消息监听或平台预热 adapter 已接入。

```yaml
mcp_servers:
  aigm-kernel:
    command: python3
    args:
      - -m
      - rpg_engine
      - mcp
      - serve
      - --root
      - ~/.hermes/rp
      - --default-campaign
      - isekai-farm-campaign-native-v1
      - --default-save
      - isekai-farm-save-native-v1
      - --default-starter-save
      - isekai-farm-save-native-starter-v1
      - --registry-active
    timeout: 300
    connect_timeout: 60
    supports_parallel_tool_calls: false
    tools:
      include:
        - workspace_inspect
        - campaign_list
        - save_list
        - save_current
        - save_create
        - save_switch
        - start_or_continue
        - intent_manifest
        - player_turn
        - player_confirm
        - campaign_validate
        - save_inspect
        - health
```

验证命令：

```bash
hermes mcp list
hermes mcp test aigm-kernel
```

Hermes 注册工具时会加前缀，例如 `query` 会显示为 `mcp_aigm_kernel_query`。正常对话不需要用户手工调用这些名字；Hermes 会根据 skill 和上下文选择。

默认 MCP 调用审计日志：

```text
<root>/logs/aigm-mcp-audit.jsonl
```

每条记录包含调用时间、工具名、参数摘要、结果摘要、错误、耗时和状态。日志只保存摘要，不落盘完整长上下文。

## 3. 暴露工具

V1 当前按 MCP profile 暴露两组工具。默认 `player` profile 只注册玩家标准入口和存档管理工具；developer/trusted/maintenance/admin profile 才注册低层运行时工具。

默认 `player` profile：

```text
workspace_inspect
campaign_list
save_list
save_current
save_create
save_switch
start_or_continue
intent_manifest
player_turn
player_confirm
campaign_validate
save_inspect
health
```

Low-level profiles 额外注册：

```text
player_query
player_act
intent_preflight
start_turn
query
preview_from_text
preview_action
validate_delta
commit_turn
```

V1 不暴露：

- admin/repair。
- migration apply。
- package upgrade/reconcile。
- plugin loading。
- 任意文件读写。
- 模型调用代理。
- 长期任务调度。

`intent_manifest` 是只读 action/query 合同，不是玩法入口。外部 AI 可以用它了解 action、query kind、slot、required/requirement group、risk、capability、AI-fillable 字段和玩家确认字段，然后生成低信任 `external_intent_candidate`；真正的自然语言输入仍必须走 `player_turn`。`player_confirmation_required=true` 或 `ai_fillable=false` 的 slot 不能由外部 AI 自行填成“已确认”。

`save_create` 和 `start_or_continue` 可以创建 Save Package，但不得推进剧情。默认 `player` profile 的自然语言输入应通过 `player_turn` 进入 kernel，由 kernel 内部判断 query/action/clarify/block；若产生 pending action，再由 `player_confirm` 保存。开发/可信 profile 可以直接走 `preview_from_text`、`validate_delta`、`commit_turn(delta, turn_proposal)` 低层链路。无论哪条链路，剧情事实变化最终都只能由内核验证并保存。

## 4. 路径边界

MCP 配置有一个 `root`。工具中的 `campaign` 和 `save` 参数：

- 可以省略；省略时使用 `--default-campaign` 或 `--default-save`。
- 必须是 root 下相对路径，例如 `saves/my-run`。
- 不能是绝对路径。
- 不能包含 `..`。

MCP 不读取任意 delta 文件。`validate_delta` 和低层 `commit_turn` 接收 JSON object；developer/trusted `commit_turn` 必须同时传入 preview 返回的 `turn_proposal`。默认普通玩家通过 `player_confirm(session_id)` 保存 pending action。

## 5. 工具契约

### workspace_inspect

输入：

```json
{}
```

输出：workspace registry 摘要，包含 root、registry 是否存在、campaign/save 数量和 active save。

### campaign_list / save_list / save_current

输入示例：

```json
{
  "refresh": true
}
```

`save_list` 还支持 `campaign_id` 和 `include_archived`。输出为 registry 中的玩家向 campaign/save 摘要。

### save_create / save_switch / start_or_continue

输入示例：

```json
{
  "campaign": "campaigns/watch-camp",
  "starter_save": "starters/watch-camp",
  "label": "New Game 1",
  "activate": true
}
```

`save_create` 创建新 Save Package；`save_switch` 只切换 active save；`start_or_continue` 在已有 active save 时继续，没有 active save 时可创建并返回 onboarding。详见 [`player-entry-save-manager.md`](player-entry-save-manager.md)。

### intent_preflight

profile：`developer/trusted/maintenance/admin` 低层辅助；默认 player profile 不应直接调用。

语义：提前计算内部 AI intent review，只写 advisory cache，不 preview、不生成 delta、不提交剧情事实。

普通玩家-facing AI client 不应主动调用本工具；它主要给 developer/trusted profile、host/adapter 后台预热或测试使用。`intent_preflight` 不是确认，不授予提交权限，也不能替代 `player_turn -> player_confirm`。

`candidate_bound` 输入示例，适用于 developer/trusted profile 或测试：

```json
{
  "user_text": "休息到早上",
  "save": "saves/my-run",
  "intent_backend": "direct",
  "intent_provider": "deepseek",
  "intent_model": "deepseek-v4-flash",
  "intent_timeout": 8,
  "intent_base_url": "https://api.deepseek.com",
  "intent_api_key_env": "DEEPSEEK_API_KEY",
  "intent_fallback_backend": "off",
  "external_intent_candidate": {
    "kind": "single",
    "mode": "action",
    "action": "rest",
    "slots": {"until": "morning"},
    "confidence": "high"
  },
  "preflight_identity_profile": "candidate_bound",
  "ttl_seconds": 300
}
```

`message_only` 输入示例，适用于 host/adapter 后台预热：

```json
{
  "user_text": "休息到早上",
  "save": "saves/my-run",
  "intent_backend": "direct",
  "intent_provider": "deepseek",
  "intent_model": "deepseek-v4-flash",
  "intent_timeout": 8,
  "intent_base_url": "https://api.deepseek.com",
  "intent_api_key_env": "DEEPSEEK_API_KEY",
  "intent_fallback_backend": "off",
  "message_id": "qq:message:123",
  "platform": "qq",
  "session_key": "qq:user:456",
  "preflight_identity_profile": "message_only",
  "ttl_seconds": 300
}
```

输出包含：

- `ok`、`status`、`preflight_id`。
- `source_user_text_hash`、`message_id`、`expires_at`。
- 成功时包含 `internal_review` 与 `internal_helper` 审计摘要。

消费方式：后续 `player_turn` / `player_act` / `start_turn` / `preview_from_text` / 低层 `act` 传入同一 `preflight_id`、`message_id`、`source_user_text_hash`、`platform`、`session_key`。若使用 `message_only`，正式调用可以不传 `preflight_id`，由内核按 `platform/session_key/message_id/source_user_text_hash/save/base_turn/context/model/schema/task` 查找唯一记录。`player_turn` / `player_act` / `start_turn` / `preview_from_text` 还可传 `preflight_pending_wait_ms` 做短等待，硬上限为 1000ms。命中后仍会进入 arbiter、binder、resolver、TurnProposal validation 和 commit guard。

当前实现边界：

- 已实现：`candidate_bound` 按 `preflight_id` 消费；`message_only` 可无 `preflight_id` 按消息身份 lookup。
- 已实现：pending 短等待、过期 pending 转 `expired`、等待超时标记 bypass、late ready 转 `rejected/late_ready_unused`，不会回头影响已处理回合。
- 已实现：非 hit、过期、拒绝、已消费或 schema revalidation 失败的 cache 不会进入 proposal provenance；会回退现场内部 AI。
- 已实现：空字符串与数值 `0` per-call AI override 视为未提供，使用 MCP config 默认值；被动 preflight 标识不算 AI override。
- 已实现：`intent_preflight` 在 pending clarification 存在时会被拒绝，避免后台预热跨过未回答的澄清。
- 已实现：rpg-engine 内有 `GameSessionGate` 纯函数契约和测试。
- 已实现：3B rpg-engine 侧平台无关基座，包括 `GameSessionBindingStore`、`PlatformPrewarmService`、`PrewarmQueue`、`PrewarmWorker`、`PrewarmMetrics`。
- 已实现：`PlatformSidecar` 可归一化 QQ/Hermes 风格 MessageEvent、触发预热、维护 binding，并通过平台 action facade 调用标准 `player_turn` 语义后输出 canary metrics；Hermes/QQ 原生代码未改。
- 已实现：MCP `player_turn` 可接收后台 `external_intent_candidate`，并可接收被动 preflight 标识按 MCP server 内部 AI 配置消费 cache。
- 已实现：MCP `player_act` 保留为兼容入口，可接收被动 preflight 标识；它不接收 `external_intent_candidate`。
- 未实现能力不得由外部 AI 模拟；外部调用者不能上传 `internal_candidate`。

平台监听 / Hermes/QQ 薄 adapter 的 rpg-engine sidecar 已可用，工程计划见 [`../../reports/2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md`](../../../../reports/2026-07-03/01-platform-prewarm-3b-lightweight-implementation-plan.md)。注册 `intent_preflight` MCP 工具或 rpg-engine sidecar 完成，不等于已经修改 Hermes/QQ 原生代码；真实平台 canary 需要由外部插件/sidecar 进程调用 `PlatformSidecar`。

### player_query

`player_query` 是结构化只读能力。普通自然语言问题应优先进入 `player_turn`，由 kernel 内部判断为 query 后执行同一条查询路径；外部 AI 不应把玩家自然语言手动分流到 `player_query`。

输入：

```json
{
  "kind": "scene",
  "query_text": null,
  "budget": null
}
```

输出：玩家可见查询结果，不暴露隐藏视图、delta 或内部 proposal。

### player_turn

输入：

```json
{
  "user_text": "休息到早上",
  "external_intent_candidate": {
    "kind": "single",
    "mode": "action",
    "action": "rest",
    "slots": {"until": "morning"},
    "confidence": "high"
  },
  "preflight_id": "",
  "message_id": "qq:message:123",
  "platform": "qq",
  "session_key": "qq:user:456",
  "source_user_text_hash": "sha256-of-normalized-user-text",
  "preflight_pending_wait_ms": 200
}
```

输出：玩家可读 kernel 结果。结果可能是 query result、clarification、blocked reason 或 action preview。若可保存，会在 Save Manager 暂存 pending action，并返回 `ready_to_confirm=true`；输出不会暴露 `delta_draft` 或 `turn_proposal`。若返回 `clarification`、`needs_confirmation`、`blocked` 或 `ready_to_confirm=false`，客户端必须先向玩家澄清或说明阻断原因，不能调用 `player_confirm`。

`external_intent_candidate` 是外部 AI/GM 层生成的后台低信任候选，不是玩家字段。它会进入 kernel 的 external/internal/rules 复核链路；external candidate 不能直接决定保存。

### player_act

`player_act` 是兼容入口。新普通玩法应使用 `player_turn`。

输入：

```json
{
  "user_text": "休息到早上",
  "preflight_id": "",
  "message_id": "qq:message:123",
  "platform": "qq",
  "session_key": "qq:user:456",
  "source_user_text_hash": "sha256-of-normalized-user-text",
  "preflight_pending_wait_ms": 200
}
```

输出：玩家可读行动预演。若可保存，会在 Save Manager 暂存 pending action，并返回 `ready_to_confirm=true`；输出不会暴露 `delta_draft` 或 `turn_proposal`。若返回 `clarification`、`needs_confirmation`、`blocked` 或 `ready_to_confirm=false`，客户端必须先向玩家澄清，不能调用 `player_confirm`。

`player_act` 的 preflight 字段是 host/adapter 透传的被动标识，只能用于 cache lookup。默认 player-safe profile 仍不允许 per-call `external_intent_candidate`、intent backend/model override、delta 或 proposal 注入。若 message-only preflight 命中但没有外部结构化候选，当前策略允许低风险且内部 AI 与规则候选一致的单步行动进入 `ai_single_source_internal_fast` 预览确认；其他情况仍会澄清、fallback 或阻断。

### player_confirm

输入：

```json
{
  "session_id": "player_action:..."
}
```

输出：确认并保存最近一次 `player_turn` 暂存的可确认行动。兼容 `player_act` 也会写入同一种 pending action，但新普通玩法应使用 `player_turn`。`session_id` 必须来自本次 pending action 的返回值，并且只能在玩家明确确认后由 host/UI 传入。没有 pending action、pending action 已失效、session 不匹配、或上一轮预演不可保存时会失败。

### campaign_validate

输入：

```json
{
  "campaign": "campaigns/watch-camp"
}
```

输出：`CampaignValidationResult.to_dict()`。

### save_inspect

输入：

```json
{
  "save": "saves/my-run"
}
```

输出：V1 save inspect dict，包含当前 turn、地点、文件状态、表计数和错误列表。

### start_turn

输入：

```json
{
  "save": "saves/my-run",
  "user_text": "I inspect the bridge seal",
  "mode": "auto",
  "submode": null,
  "budget": 2200,
  "max_events": 6,
  "max_depth": 1
}
```

输出：`StartTurnResult.to_dict()`，包含 context markdown。

如果输出包含 `clarification`，客户端必须先把 `clarification.question` 以玩家可读语言问给玩家，并在有 `clarification.choices` 时展示候选选项。玩家明确回答前，客户端不得把任一 choice 当成确认，也不得继续 `validate_delta` 或 `commit_turn`。

### query

输入：

```json
{
  "save": "saves/my-run",
  "kind": "scene",
  "query_text": null,
  "view": "player"
}
```

`kind` 支持 `scene`、`entity`、`context`。

输出：`QueryResult.to_dict()`。

### preview_from_text

输入：

```json
{
  "save": "saves/my-run",
  "user_text": "I inspect the bridge seal",
  "mode": "auto",
  "submode": null
}
```

输出：`PreviewActionResult.to_dict()`，其中 `interpretation.intent` 包含 `ActionIntent`，`interpretation.turn_contract` 包含本轮模板、保存和校验 profile。

默认 `player` profile 面对自然语言玩家输入时应使用 `player_turn`。`preview_from_text` 是 developer/trusted low-level primitive；只有当 action 已由 `ActionIntent`、UI 选择或其他确定合同给出时，才直接调用低层 `preview_action`。

在 developer/trusted profile 中，`preview_from_text` 可以接收 `external_intent_candidate` 用于 external/internal consensus。该 candidate 不是给 internal AI 抄答案；internal AI 会看见它，但必须重新判断玩家原文，并把一致、部分一致、不一致或候选质量问题交给 arbiter。默认 `player` profile 不接受这种注入。

如果 `interpretation.clarification` 或 `interpretation.intent.clarification` 存在，`preview_from_text` 的结果只是澄清请求，不是可提交预演。客户端必须先问玩家；玩家回答后在普通 profile 下重新走 `player_turn`，或在开发/可信 profile 下提交新的完整 `external_intent_candidate`，让内核重新执行外部/内部 AI 共识、binder、resolver、validation。默认 `player` profile 不直接注册 `preview_from_text`。不得在旧 preview 上直接套用 `choice_id`。

MCP adapter 会在同一 server 进程内记录 pending `clarification_id`。在 fresh `player_turn` / `start_turn` / `preview_from_text` 回答该 clarification 之前，低层 `preview_action`、`validate_delta`、`commit_turn` 会被拒绝。默认 `player_turn` 入口还会把 pending clarification 写入 workspace `.aigm` 状态，并在新行动不可确认时清掉旧 pending action，避免确认到上一轮旧预演。

### preview_action

输入：

```json
{
  "save": "saves/my-run",
  "action": "explore",
  "options": {
    "target": "Broken Seal Mark",
    "approach": "careful visual inspection",
    "user_text": "Inspect the broken bridge seal"
  },
  "source_user_text": "Inspect the broken bridge seal"
}
```

输出：`PreviewActionResult.to_dict()`。

`preview_action` 是低层确定性 API。调用方若传入 `source_user_text`，Runtime 会做轻量 action/text 冲突检查；例如 routine 文本被传成 craft 时会返回 `needs_confirmation`。

`preview_action` 的 JSON 输出包含 `status`、`ready_to_save`、`delta_draft`、`turn_proposal`、`player_message` 和 `repair_options`。MCP 客户端必须只在 `ready_to_save=true`、`validate_delta.ok=true`、玩家/GM 已确认且可传回同一个 `turn_proposal` 时调用 `commit_turn`；`needs_confirmation`、`clarify`、`blocked` 和 `internal_error` 都不是可提交状态。

### validate_delta

输入：

```json
{
  "save": "saves/my-run",
  "action": "explore",
  "action_options": {
    "target": "Broken Seal Mark"
  },
  "turn_proposal": {
    "proposal_id": "turn-proposal:v1-minimal-adventure:explore",
    "delta_source": "resolver_proposed",
    "human_confirmed": false
  },
  "delta": {
    "expected_turn_id": "turn:seed",
    "command_id": "example-command",
    "user_text": "Inspect the broken bridge seal",
    "intent": "explore",
    "changed": false,
    "summary": "No saved consequence yet."
  }
}
```

输出：`DeltaValidationResult.to_dict()`。

### commit_turn

输入：

```json
{
  "save": "saves/my-run",
  "action": "explore",
  "action_options": {
    "target": "Broken Seal Mark"
  },
  "delta": {
    "expected_turn_id": "turn:seed",
    "command_id": "example-command",
    "user_text": "Wait and watch.",
    "intent": "wait",
    "changed": false,
    "summary": "No significant change."
  }
}
```

输出：`CommitTurnResult.to_dict()`。

上例的 `turn_proposal` 仅为节选；真实调用必须传入 `preview_from_text` 或 `preview_action` 返回的完整 `turn_proposal` object，不能手写最小字段替代。

`action` 和 `action_options` 可选。若省略，GMRuntime 会优先从 proposal intent 和 delta 的事件 payload 反推动作参数；preview 生成的 delta 必须和 preview 返回的 `turn_proposal` 一起提交。`commit_turn` 总是启用备份；MCP 不暴露 `--no-backup`。

### health

输入：

```json
{
  "save": "saves/my-run"
}
```

输出：`HealthResult.to_dict()`。该工具只读，不 repair。

## 6. AI 客户端推荐流程

默认 `player` profile：

1. 调 `save_current`、`save_inspect` 或 `health` 确认存档可用。
2. 玩家说自然语言时，外部 AI 先生成后台低信任 `external_intent_candidate`。
3. 调 `player_turn(user_text, external_intent_candidate)`，由 kernel 内部判断 query/action/clarify/block。
4. 如果返回 query result，直接基于 kernel 返回的玩家可见内容回答，不推进时间、不保存。
5. 如果返回 `clarification`、`needs_confirmation` 或 `blocked`，先把内核问题/阻断原因告诉玩家；玩家补充后重新调 `player_turn`。
6. 只有 `ready_to_confirm=true` 且玩家确认时调 `player_confirm`。
7. 保存后再调 `player_turn` 处理下一句自然语言，或使用结构化只读能力刷新上下文。

默认 `player` profile 不调用 `intent_preflight`。如果 host/adapter 已经在后台做了预热，只把返回的 `preflight_id/message_id/platform/session_key/source_user_text_hash/preflight_pending_wait_ms` 作为标识透传给 `player_turn`。不要把 preflight 当作玩家确认。

开发/可信低层 profile：

1. 调 `save_inspect` 或 `health` 确认存档可用。
2. 玩家发话后调 `start_turn`。
3. 如果是查询，调 `query`，直接叙事回答。
4. 如果是行动，优先调 `preview_from_text`；只有 action 已由合同明确给出时才调 `preview_action`，让玩家确认风险和意图。
5. 如果 `start_turn` 或 `preview_from_text` 返回 `clarification`，先问玩家；玩家回答后重新生成候选并重新走 `start_turn` / `preview_from_text`。
6. AI 草拟或选择 delta 后调 `validate_delta`。
7. 只有 validate OK 且玩家/GM 同意时调 `commit_turn(delta, turn_proposal)`。
8. commit 后再调 `query` 或 `start_turn` 获取新上下文。

事实以 save 为准；AI 文本不能把未 commit 的内容当成已发生。
