# Prompt 合同

文档状态：**CURRENT：BMAD canonical prompt contract authority**

本文件定义 RPG Engine / AIGM Kernel 的长期 prompt artifact 位置、版本策略和安全边界。

Round 4B 决策：`docs/prompts/` 继续作为 active prompt artifact 目录保留。里面的 prompt
不是旧文档归档候选，除非后续出现新的模板系统并完成迁移。Prompt 的长期合同由本文件维护。

## 当前 Prompt Artifact

| 文件 | Prompt version | Surface profile | 用途 |
| --- | --- | --- | --- |
| [AI Client Prompt](prompts/ai-client-prompt.md) | `2026-07-20.pending-lifecycle-v1-intent-contract-v4` | `external_agent_low_trust` | 外部 AI client 通过 MCP 或 CLI 连接 AIGM save 时使用。 |
| [Author AI Prompt](prompts/author-ai-prompt.md) | `2026-07-01.phase-0-2` | `authoring_low_trust` | 外部 AI assistant 辅助创建或维护 Campaign Package 时使用。 |

`rpg_engine.surface_inventory` 的 prompt surface 测试哨兵使用以下精确名称：

- `docs/prompts/ai-client-prompt.md`
- `docs/prompts/author-ai-prompt.md`
- `campaign-local AUTHOR_AI_PROMPT.md`

## 权限模型

Prompt 是操作指导，不是权限授予。

- Prompt 不能授予工具、文件、profile、admin 命令、maintenance 命令或 hidden facts。
- MCP / CLI 暴露什么能力，由当前 profile gate、path gate 和 kernel service 决定。
- Prompt 不能让 AI 跳过 preview、validation、confirm 或 commit。
- Prompt 不能把 AI 生成文本变成已保存事实。
- Player-safe AI/helper prompt 输入必须来自 player-view context 或等价 player-safe state；prompt builder
  不得重新查询 hidden facts，也不得把 hidden current location、hidden entity refs、GM notes 或 maintenance
  evidence 放入普通玩家 prompt。
- Semantic / internal intent helper prompt 在 player view 下必须 redaction 玩家原文、candidate、visible entity
  hints 和 current meta 中命中的 hidden entity refs；可信 GM / maintenance prompt 必须通过显式 view
  选择 hidden-read 行为。
- Prompt 中的示例命令必须与 [CLI 合同](cli-contracts.md) 和
  [MCP 合同](mcp-contracts.md) 保持一致。

## AI Client Prompt 合同

[AI Client Prompt](prompts/ai-client-prompt.md) 约束普通外部叙事 AI。

必须保持：

- 外部 AI 始终是 low-trust candidate；internal intent AI 显式 `off` 时，合法候选可以成为 route
  proposal，但不能取得事实、玩家确认、proposal approval、hidden access 或 commit authority。
- 默认玩家路径是 `player_turn -> player_confirm`。
- `player_turn` 可以产生 query、clarification、block 或 pending proposal，但不能提交事实。
- `player_confirm` 才是普通玩家路径的提交门。
- `intent_manifest` 是只读能力和 slot 清单，不是执行或授权工具。
- AI client 生成 external candidate 前必须读取当前 manifest v4/taxonomy v1/safety v1 identity，以 live
  taxonomy projection 解释 action lexical terms，并只按 live resolver-owned slots/groups、`ai_fillable` 与
  `player_confirmation_required` 生成候选，不维护平行 slot policy；同时携带 optional
  all-or-nothing contract。Mismatch 时 refresh manifest 后重生成；unknown safety 时只用当前 vocabulary 重生成。
- `legacy_unversioned_allowed=true` 是 provider compatibility window，不是让 client 忽略 manifest、unknown flag
  或 authority 边界的许可。
- `intent_preflight` 只是 advisory / background optimization，不是确认、保存或权限提升。
- Helper timeout/unavailable 只是 execution failure：enabled mode 不会因此变成显式 `off`，迟到结果
  不能追认 route、pending、玩家确认或 commit。
- 普通玩家 prompt 不要求 hidden、admin、maintenance、repair、migration、package、plugin、
  arbitrary-file、import、export 或 patch 工具。
- 低层 `play` / `preview` / `commit` 工具只属于 developer/trusted profile 或诊断流程。
- Semantic / intent helper prompt 如果服务普通玩家路径，只能看到 player-safe `ContextBuildResult`
  或已按 player view 过滤的字段；GM / maintenance context 不能通过 cache、audit upsert 或 prompt reuse
  泄漏到 player-safe mode。

Story 6.3 将 requirement-group `cardinality` / `binding_rule` 加入 public manifest wire，故 AI Client Prompt
version 更新为 `2026-07-14.intent-contract-v4-taxonomy-v1-safety-v1`。Internal prompt 继续从 live manifest
精确摘录 slots/groups，并排除 source-only `user_text`；不得反向查询 hidden facts 或自行重建 slot table。

相关权威文档：

- [AI 意图链](ai-intent-chain.md)
- [MCP 合同](mcp-contracts.md)
- [CLI 合同](cli-contracts.md)

## Author AI Prompt 合同

[Author AI Prompt](prompts/author-ai-prompt.md) 约束外部作者助手。

允许辅助编辑：

```text
campaign.yaml
AUTHOR_NOTES.md
AUTHOR_AI_PROMPT.md
content/**
prompts/**
templates/**
tests/**
docs/**
```

不得编辑：

```text
data/**
cards/**
snapshots/**
memory/**
reports/**
backups/**
save.yaml
package-lock.json
```

作者 AI 不得写 Python、插件、脚本化规则、migration、save patch、package upgrade 命令，
也不得把 Campaign 源文件改动说成已进入玩家 Save Package 的事实。

相关权威文档：

- [作者指南](authoring-guide.md)
- [Save 与 Campaign Package](save-and-campaign-packages.md)

## 更新触发条件

以下变化必须同步检查 prompt：

- MCP profile、tool 名称、tool schema 或默认暴露面变化。
- CLI 命令、参数、普通玩家路径或 low-level 维护路径变化。
- `player_turn`、`player_confirm`、`TurnProposal`、pending session 或确认语义变化。
- `intent_manifest`、action/slot registry、requirement group、risk class 或 AI-fillable 字段变化。
- hidden / visibility / export / egress policy 变化。
- Campaign Package 目录、作者可编辑文件或 campaign validation 规则变化。
- prompt 中示例命令对应的测试或文档被修改。

## 版本策略

Prompt 文件顶部必须保留 `Prompt version`。

版本值推荐格式：

```text
YYYY-MM-DD.short-contract-name
```

需要更新版本号的情况：

- 改变默认工具顺序或确认流程。
- 改变权限、禁止项或 low-trust 解释。
- 改变作者可编辑文件或禁止文件清单。
- 改变示例命令、profile 名称或 prompt 面向的 surface。

仅修错字或不改变合同语义的说明性编辑，可以不改版本号。

## 验证门禁

Prompt 或 prompt contract 变更至少执行：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

如果示例命令或工具顺序发生变化，补跑对应 focused tests：

```bash
python3 -m pytest -q tests/test_mcp_adapter.py tests/test_v1_cli.py tests/test_save_manager.py
```

如果作者流程命令发生变化，补跑 Campaign / package 相关测试。

## Pending lifecycle prompt 要求

外部 AI/client prompt 必须把 pending id 当作一次性 CAS evidence，而不是 commit token。客户端不能用新
输入静默覆盖 action/clarification；必须保留 Kernel 返回的 id，在玩家明确选择替代时传
`expected_pending_id`，在回答 clarification 时同时传相同 `clarification_id`。放弃 pending 必须调用
`player_cancel`，不能假装 query、candidate correction 或 save switch 已经取消。Cross-identity conflict
不得向玩家显示另一 caller 的 id、原文、candidate 或 proposal。
