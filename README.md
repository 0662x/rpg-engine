# RPG Engine

本项目是本地优先的 AIGM Kernel：用 Campaign Package 定义世界与玩法，用 Save Package 保存一次游玩，用 GMRuntime/CLI/MCP 提供查询、预演、校验和提交边界。

当前权威文档入口：[`docs/README.md`](docs/README.md)

## Quick Start

源码运行：

```bash
cd rpg-engine
python3 -m pip install -e .
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine save init ./examples/v1_minimal_adventure /tmp/aigm-save
python3 -m rpg_engine play query /tmp/aigm-save scene
python3 -m rpg_engine play preview /tmp/aigm-save explore --target "Broken Seal Mark" --approach careful --user-text "Inspect the seal"
```

安装后可用 `aigm` 替代 `python3 -m rpg_engine`。

带 MCP adapter：

```bash
python3 -m pip install -e ".[mcp]"
aigm mcp print-config /tmp --default-save aigm-save
```

## Main Paths

普通用户优先使用：

```text
campaign  validate/test/new/doctor/outline/copy-example
save      init/inspect/validate/import/export/patch
player    start/new/saves/current/switch/duplicate
play      start-turn/query/preview/validate-delta/commit/act
mcp       print-config/serve
```

普通玩家 `play commit` / MCP `commit_turn` 需要提交 preview 返回的 `TurnProposal`；裸 delta 写入保留在 `save-turn` 等 admin/legacy 路径，并会显式使用对应 profile。

Legacy/admin 入口仍保留用于维护、迁移和调试，例如 `content`、`proposal`、`palette`、`projection`、`migrate`、`package`、`plugin`、`importer`。

Phase 0-7.1 的内部合同、普通玩家主路径骨架和 projection 状态语义已阶段性落地：intent、contract、proposal、validation、commit 和 projection 都有集中 owner。Commit 后 snapshots/cards/memory/reports 等事务后投影由 `ProjectionService` 生成 `ProjectionReport`，旧 artifact 命令保留为 legacy/admin/maintenance profile。

Phase 7.1 已硬化 projection 事务边界、targeted repair、commit/projection 状态 API、stale/version repair 和指标字段。这不等于完整产品成熟度已经完成；下一步仍是完整 `TurnCoordinator`、目标工具协议、semantic AI parity、发布/回滚证据和 import/migration 批量 profile 报告。

## Documentation

- 文档索引：[`docs/README.md`](docs/README.md)
- 开发入口：[`AGENTS.md`](AGENTS.md)、[`docs/project-context.md`](docs/project-context.md)、[`docs/development-workflow.md`](docs/development-workflow.md)
- 产品边界：[`docs/project-overview.md`](docs/project-overview.md)
- Campaign / Save 规范：[`docs/save-and-campaign-packages.md`](docs/save-and-campaign-packages.md)
- CLI 规范：[`docs/cli-contracts.md`](docs/cli-contracts.md)
- MCP 规范：[`docs/mcp-contracts.md`](docs/mcp-contracts.md)
- 作者指南：[`docs/authoring-guide.md`](docs/authoring-guide.md)
- AI 客户端 Prompt：[`docs/prompts/ai-client-prompt.md`](docs/prompts/ai-client-prompt.md)
- 模块边界：[`docs/component-inventory.md`](docs/component-inventory.md)、[`docs/source-tree-analysis.md`](docs/source-tree-analysis.md)
- 旧文档归档：[`docs/archive/pre-bmad-docs-2026-07-03/`](docs/archive/pre-bmad-docs-2026-07-03/)

## Included Campaign Content

- 当前公开剧情包：[`rp/isekai-farm-campaign-native-v1`](rp/isekai-farm-campaign-native-v1)
- 存档包不进入公开仓库；本地继续游玩存档应保留在私有目录中。

2026-06-30 的设计报告、测试报告和 UX 模拟报告已归档到 [`docs/archive/2026-06-30/`](docs/archive/2026-06-30/)。它们用于追溯决策，不再作为当前实现的权威入口。

## Test

```bash
python3 -m pytest
```

当前 Round 6 本地基准：`449 passed, 483 subtests passed`。

## Boundaries

- Engine 不负责写剧情；AI 客户端负责叙事，Kernel 负责事实、规则、随机、校验、保存和上下文。
- AI 输出不能直接成为权威事实；事实变化必须经过 preview/validate/commit 或受控维护命令。
- Hidden 内容默认不能进入玩家视图、FTS、场景和普通查询。
- 动态插件加载、插件市场、HTTP 后端、多人服务和完整电子游戏式数值系统不属于 V1 主路径。
