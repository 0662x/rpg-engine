# Prompt 合同

文档状态：**CURRENT：BMAD canonical prompt contract authority**

本文件定义 RPG Engine / AIGM Kernel 的长期 prompt artifact 位置、版本策略和安全边界。

Round 4B 决策：`docs/prompts/` 继续作为 active prompt artifact 目录保留。里面的 prompt
不是旧文档归档候选，除非后续出现新的模板系统并完成迁移。Prompt 的长期合同由本文件维护。

## 当前 Prompt Artifact

| 文件 | Prompt version | Surface profile | 用途 |
| --- | --- | --- | --- |
| [AI Client Prompt](prompts/ai-client-prompt.md) | `2026-07-03.player-turn-standard-entry` | `external_agent_low_trust` | 外部 AI client 通过 MCP 或 CLI 连接 AIGM save 时使用。 |
| [Author AI Prompt](prompts/author-ai-prompt.md) | `2026-07-01.phase-0-2` | `authoring_low_trust` | 外部 AI assistant 辅助创建或维护 Campaign Package 时使用。 |

## 权限模型

Prompt 是操作指导，不是权限授予。

- Prompt 不能授予工具、文件、profile、admin 命令、maintenance 命令或 hidden facts。
- MCP / CLI 暴露什么能力，由当前 profile gate、path gate 和 kernel service 决定。
- Prompt 不能让 AI 跳过 preview、validation、confirm 或 commit。
- Prompt 不能把 AI 生成文本变成已保存事实。
- Prompt 中的示例命令必须与 [CLI 合同](cli-contracts.md) 和
  [MCP 合同](mcp-contracts.md) 保持一致。

## AI Client Prompt 合同

[AI Client Prompt](prompts/ai-client-prompt.md) 约束普通外部叙事 AI。

必须保持：

- 外部 AI 始终是 low-trust candidate。
- 默认玩家路径是 `player_turn -> player_confirm`。
- `player_turn` 可以产生 query、clarification、block 或 pending proposal，但不能提交事实。
- `player_confirm` 才是普通玩家路径的提交门。
- `intent_manifest` 是只读能力和 slot 清单，不是执行或授权工具。
- `intent_preflight` 只是 advisory / background optimization，不是确认、保存或权限提升。
- 普通玩家 prompt 不要求 hidden、admin、maintenance、repair、migration、package、plugin、
  arbitrary-file、import、export 或 patch 工具。
- 低层 `play` / `preview` / `commit` 工具只属于 developer/trusted profile 或诊断流程。

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
