# 文档 Provenance 复核

文档状态：DRAFT / GDS full_rescan exhaustive provenance audit
语言：zh-CN
工作流：`gds-document-project`
生成时间：2026-07-04

## 目的

本文件专门回答这次 BMAD 复核中的核心问题：此前写出来的一大批文档怎么办？它们是不是
“非标准 BMAD 文档”？结论是：

- 不是全部作废。
- 但只有记录了明确 skill provenance、config、instruction files、验证门禁的产物，才能作为严格
  BMAD 执行证明。
- 缺少 provenance 的旧 BMAD-style 文档可以作为 working artifact / historical evidence，不能单独作为
  当前规范权威。

## 本轮严格 BMAD 证据

本轮已按以下路径执行：

| 项 | 证据 |
| --- | --- |
| 用户触发 | `gds-document-project` |
| Skill read | `.agents/skills/gds-document-project/SKILL.md` |
| Resolver | `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow` |
| Config | `_bmad/gds/config.yaml` |
| Persistent facts | `docs/project-context.md` |
| Workflow files | `.agents/skills/gds-document-project/instructions.md`, `.agents/skills/gds-document-project/workflows/full-scan-instructions.md` |
| Support files | `.agents/skills/gds-document-project/checklist.md`, `.agents/skills/gds-document-project/documentation-requirements.csv` |
| Mode | `full_rescan` |
| Scan level | `exhaustive` |
| User focus | `none` |
| State file | `_bmad-output/project-scan-report.json` |

安装包存在两个 workflow packaging gaps，已记录在 state file：

- `instructions.md` 引用了 `.agents/skills/gds-document-project/workflow.yaml`，但当前安装目录里没有该文件。
- `instructions.md` 引用了 `skill:gds-workflow-status`，但当前 `.agents/skills/` 没有安装对应 skill。

因此本轮按 skill 指令允许的 standalone 模式继续执行，并把 gap 写入 provenance。

## 文档可信度分层

| 层级 | 文档类型 | 使用方式 |
| --- | --- | --- |
| 1 | 当前代码、测试、packaged resources、CI | 最高事实源 |
| 2 | `docs/` canonical 文档 | 长期项目知识入口；若与代码冲突，以代码为准 |
| 3 | 本轮 `_bmad-output/` strict provenance 输出 | Brownfield PRD / 后续 story 的扫描基线 |
| 4 | Round 2-7 BMAD close-out / audit / implementation reports | 有价值的历史执行记录；要看是否记录了当时门禁和代码证据 |
| 5 | Round 1 Deep Scan 旧输出 | 有价值的初始素材；原状态头说明“未进入 canonical docs” |
| 6 | `docs/archive/pre-bmad-docs-2026-07-03/` 原文 | 历史证据；不能覆盖当前代码或 canonical docs |
| 7 | `docs/architecture/`, `docs/specs/`, `docs/guides/` 旧路径 | Round 4C compatibility stubs，只作为跳转入口 |

## 当前 canonical 文档复核

本轮确认这些长期入口仍是当前主文档集合：

- `docs/index.md`
- `docs/project-overview.md`
- `docs/source-tree-analysis.md`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/ai-intent-chain.md`
- `docs/save-and-campaign-packages.md`
- `docs/authoring-guide.md`
- `docs/data-models.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/prompt-contracts.md`
- `docs/development-guide.md`
- `docs/testing-and-quality-gates.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/governance/content-generation.md`

本轮已抽到的重点状态：

- 作者指南已经是 canonical 文档，不再依赖旧 `docs/guides/` 正文。
- Prompt 长期位置已定为 `docs/prompts/`，由 `docs/prompt-contracts.md` 管理。
- V1 产品边界已经在 `docs/project-overview.md` 中收敛。
- 残余风险已被摘到 `_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`。
- 旧 `architecture/specs/guides` 已归档为 Round 4C stubs + archive source。

## 发现的问题

| 发现 | 严重度 | 说明 |
| --- | --- | --- |
| 旧 `_bmad-output` Round 1 文件状态头仍写着 Deep Scan / 未进入 canonical docs | Minor | 容易让人误会这些是当前最终文档；本轮已刷新主要扫描输出 |
| 旧 BMAD-style 输出并非全部都有 strict skill provenance | Minor | 不能作为严格执行证明，但仍能作为历史素材 |
| `gds-document-project` 安装包引用了缺失的 `workflow.yaml` 和 `gds-workflow-status` | Minor | 已记录；当前按 standalone 模式执行 |
| Packaged migrations 到 `0008`，root mirror 到 `0005` | Minor / future risk | 可能误导只看根目录镜像的开发者；数据模型输出已记录 |
| Root schema mirror 缺少部分 packaged schemas | Minor / future risk | 以 packaged schemas 为准；数据模型输出已记录 |
| `bmad-create-architecture` 仍存在但已标记 deprecated shim | Informational | 后续推荐优先用 `bmad-architecture` 或 GDS 的 `gds-game-architecture` |

## 对“以前文档怎么办”的处理结论

保留，不整锅推翻：

- Canonical docs 继续作为长期入口。
- Round reports 继续作为执行历史。
- Archive 原文继续作为历史证据。
- `_bmad-output` 旧扫描输出作为素材，不作为最终权威。

后续开发时的读取顺序：

1. 先读当前代码、测试和 touched surface。
2. 再读 `docs/index.md` 指向的 canonical 文档。
3. 再读本轮 `_bmad-output/` strict provenance 输出。
4. 只有需要追溯历史时才读 archive 原文。

## 后续建议

- 短期：完成本轮 `gds-document-project` 验证和用户 review checkpoint。
- 中期：选择性把本轮发现的 mirror drift / provenance 分层写回 canonical governance 文档。
- 长期：每次用户说 `bmad`、菜单码或 skill 名时，都按 `AGENTS.md` 的 strict activation 跑，避免再出现“像 BMAD 但缺 provenance”的文档。
