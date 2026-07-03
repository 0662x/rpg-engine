# RPG Engine GDS Document Project Index

文档状态：DRAFT / GDS full_rescan exhaustive master index
语言：zh-CN
工作流：`gds-document-project`
生成时间：2026-07-04

本目录是本轮严格 `gds-document-project` 的扫描输出区，用于 brownfield PRD、后续 story、
代码复核和文档治理。长期规范入口仍是 [`docs/index.md`](../docs/index.md)；本目录不是替代
canonical docs，而是带 provenance 的扫描基线。

## BMAD Provenance

- 用户触发：`gds-document-project`
- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Customization resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Config：`_bmad/gds/config.yaml`
- Workflow instructions：
  `.agents/skills/gds-document-project/instructions.md`,
  `.agents/skills/gds-document-project/workflows/full-scan-instructions.md`
- 支撑文件：
  `.agents/skills/gds-document-project/checklist.md`,
  `.agents/skills/gds-document-project/documentation-requirements.csv`
- 模式：`full_rescan`
- 扫描深度：`exhaustive`
- 状态文件：[`project-scan-report.json`](./project-scan-report.json)

## 项目判断

RPG Engine 当前是 **single-part Python backend / CLI / library 型 local-first AI GM engine
kernel**，带 game 和 data traits。它不是 Unity/Godot/Unreal 图形客户端项目，也没有 HTTP API
或 cloud deployment surface。

核心架构原则：

```text
AI proposes. Kernel verifies. Player confirms. Engine commits.
```

普通玩家路径以 `SaveManager.player_turn()` 生成 pending proposal，以
`SaveManager.player_confirm()` 作为提交门。AI intent、preflight cache、MCP、CLI 和 platform
sidecar 都不能绕过 preview / validation / confirmation / commit 边界。

## 本轮产物

| 文档 | 用途 |
| --- | --- |
| [项目概览](./project-overview.md) | 项目定位、V1 边界、技术栈、主要能力 |
| [源码树分析](./source-tree-analysis.md) | 仓库结构、关键目录、runtime data 边界 |
| [架构扫描](./architecture.md) | 当前架构模式、入口边界、写入链、AI trust boundary |
| [组件清单](./component-inventory.md) | 模块职责、集成面、测试覆盖地图 |
| [API / Public Surface Contracts](./api-contracts.md) | CLI、MCP、Runtime、SaveManager、platform surface |
| [数据模型](./data-models.md) | SQLite migrations、schemas、Save/Campaign/workspace state |
| [开发与运维指南](./development-guide.md) | 环境、测试、CI、文档门禁、public repo 边界 |
| [文档 Provenance 复核](./documentation-provenance-audit.md) | 旧文档可信度分层、strict BMAD 证据、残余治理项 |
| [Document Project Completion Summary](./document-project-completion-summary.md) | 本轮完成记录、验证摘要、剩余风险和后续建议 |
| [扫描状态 JSON](./project-scan-report.json) | 可恢复 workflow state |

## Canonical Docs

当前长期文档入口仍是 [`../docs/index.md`](../docs/index.md)。本轮确认的 canonical 集合：

- [`../docs/project-overview.md`](../docs/project-overview.md)
- [`../docs/source-tree-analysis.md`](../docs/source-tree-analysis.md)
- [`../docs/architecture.md`](../docs/architecture.md)
- [`../docs/component-inventory.md`](../docs/component-inventory.md)
- [`../docs/ai-intent-chain.md`](../docs/ai-intent-chain.md)
- [`../docs/save-and-campaign-packages.md`](../docs/save-and-campaign-packages.md)
- [`../docs/authoring-guide.md`](../docs/authoring-guide.md)
- [`../docs/data-models.md`](../docs/data-models.md)
- [`../docs/cli-contracts.md`](../docs/cli-contracts.md)
- [`../docs/mcp-contracts.md`](../docs/mcp-contracts.md)
- [`../docs/prompt-contracts.md`](../docs/prompt-contracts.md)
- [`../docs/development-guide.md`](../docs/development-guide.md)
- [`../docs/testing-and-quality-gates.md`](../docs/testing-and-quality-gates.md)
- [`../docs/project-context.md`](../docs/project-context.md)
- [`../docs/governance/bmad-workflow.md`](../docs/governance/bmad-workflow.md)
- [`../docs/governance/content-generation.md`](../docs/governance/content-generation.md)

## 旧文档使用规则

- 旧 `docs/architecture/`、`docs/specs/` 和 `docs/guides/` 只保留 compatibility stubs。
- 归档原文位于 [`../docs/archive/pre-bmad-docs-2026-07-03/`](../docs/archive/pre-bmad-docs-2026-07-03/)。
- `docs/prompts/` 是 active prompt artifact 目录，不是普通历史目录。
- 旧 `_bmad-output` Round reports 是历史执行记录；缺少 strict skill provenance 的文件不能单独作为
  BMAD 执行证明。
- 若 archive 原文、旧 BMAD-style 输出、canonical docs 与代码事实冲突，以当前代码事实和
  canonical docs 为准。

## 关键发现

- Packaged migrations 已到 `rpg_engine/resources/migrations/0008`，root `migrations/` mirror
  只到 `0005`。
- Packaged schemas 包含 root `schemas/` mirror 中不存在的新 schema。
- `gds-document-project` 当前安装包引用缺失的 `workflow.yaml` 和 `gds-workflow-status`；
  本轮已按 standalone 模式继续，并在 state file 记录。
- `bmad-create-architecture` 仍存在，但 skill 自身标记为 deprecated shim；新工作优先走
  `bmad-architecture` 或 GDS 的 `gds-game-architecture`。

## 下一步

本轮已进入 validation / review checkpoint。完成前必须：

- 验证 `project-scan-report.json` 是有效 JSON。
- 检查 Markdown 链接和 diff whitespace。
- 按 `gds-document-project` checklist 记录缺口。
- 由用户 review 并确认是否需要补扫或接受本轮文档。
