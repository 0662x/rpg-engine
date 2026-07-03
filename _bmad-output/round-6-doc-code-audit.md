# Round 6 文档-代码深度复核报告

文档状态：**CURRENT：BMAD Round 6 Docs-Code Deep Audit**

日期：2026-07-04

## 目标

本轮按 BMAD `document-project` / `validate-doc` 思路，对当前 canonical 文档、代码入口、
测试哨兵和历史归档边界做深度复核。目标不是继续搬旧文档，而是确认现在的文档是否真正同步
当前代码状态，并修掉会误导后续开发的漂移点。

## 复核范围

- Canonical docs：`README.md`、`docs/index.md`、`docs/project-overview.md`、
  `docs/architecture.md`、`docs/component-inventory.md`、`docs/source-tree-analysis.md`、
  `docs/ai-intent-chain.md`、`docs/save-and-campaign-packages.md`、`docs/data-models.md`、
  `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`、
  `docs/authoring-guide.md`、`docs/testing-and-quality-gates.md`。
- Code evidence：`pyproject.toml`、`rpg_engine/cli.py`、`rpg_engine/cli_v1.py`,
  `rpg_engine/mcp_adapter.py`、`rpg_engine/surface_inventory.py`、`rpg_engine/intent_manifest.py`,
  `rpg_engine/save_manager.py`、`rpg_engine/runtime.py`、`rpg_engine/commit_service.py`,
  `rpg_engine/validation_pipeline.py`、`rpg_engine/projection_service.py`,
  `rpg_engine/campaign_validation.py`。
- Test evidence：full `pytest`、`ruff`、surface inventory sentinel、Markdown link gate。

## 代码事实快照

- Package：`aigm-kernel`，Python `>=3.11`，entry points `aigm` / `rpg_engine`。
- Top-level CLI groups 当前为 `campaign`、`save`、`play`、`mcp`、`player`、`platform`、
  `eval`，以及 legacy/admin groups including `migrate`、`projection`、`package`、`plugin`。
- MCP default `player` profile 只暴露 player-safe tools；`developer`、`trusted_gm`、
  `maintenance`、`admin` 才追加 low-level tools。
- Intent manifest 当前 actions：`combat`、`craft`、`explore`、`gather`、`random_table`、
  `rest`、`routine`、`social`、`travel`；queries：`scene`、`entity`、`context`。
- `SaveManager.player_turn()` 仍只产生 query / clarification / blocked / pending action；
  `player_confirm(session_id)` 才进入保存。
- `GMRuntime.commit_turn()`、`ValidationPipeline`、`commit_service.py` 和 `ProjectionService`
  继续承载 proposal validation、事实提交和 post-commit projection 边界。

## 已修复漂移

1. README 测试基线过期。
   - 旧文档仍写 `unittest` 和 `174 passed / 77 skipped`。
   - 已改为 `python3 -m pytest`，并记录 Round 6 本地基线：`449 passed, 483 subtests passed`。

2. Phase 0-7.1 完成度表述偏乐观。
   - README 旧语义容易被理解为产品成熟度已完成。
   - 已改为“内部合同、普通玩家主路径骨架和 projection 状态语义阶段性落地”，并明确下一步仍包括
     `TurnCoordinator`、目标工具协议、semantic AI parity、发布/回滚证据和 import/migration profile 报告。

3. `tests/test_surface_inventory.py` 仍把归档 stub 当作权威文档。
   - 全量 pytest 初次失败：surface inventory sentinel 读取
     `docs/architecture/phase-0-surface-inventory.md` 和
     `docs/architecture/turn-flow-architecture.md`，但这些文件已在 Round 4C 转为 stub。
   - 已改为读取 canonical `docs/mcp-contracts.md`、`docs/prompt-contracts.md`、
     `docs/authoring-guide.md`、`docs/cli-contracts.md` 和 `docs/testing-and-quality-gates.md`。
   - 历史 Phase 0-4 多角色复审仍从归档原文验证，并要求 stub 能指回 archive。

4. Surface inventory 的 migration CLI 名称漂移。
   - 代码 help 证据显示真实命令是 `aigm migrate apply`。
   - `rpg_engine.surface_inventory.PACKAGE_SURFACE_INVENTORY` 已从 `aigm migration apply`
     修正为 `aigm migrate apply`，`docs/cli-contracts.md` 已补 exact surface anchors。

5. 文档迁移状态陈述过期。
   - `docs/project-overview.md` 和 `docs/source-tree-analysis.md` 仍有“待迁移旧文档”语义。
   - 已改为 Round 4C 后旧 `architecture/`、`specs/`、`guides/` 只保留 compatibility stubs；
     `docs/prompts/` 是 active prompt artifact。

## Canonical 文档复核结论

| 文档 | 结论 |
| --- | --- |
| `docs/project-overview.md` | V1 范围、非目标、AI 边界、公开边界与代码/仓库形状一致；迁移状态已修正。 |
| `docs/architecture.md` | 玩家安全链、低层 runtime、platform sidecar、preflight、write/projection 边界与代码一致。 |
| `docs/component-inventory.md` | 当前模块清单与 `rpg_engine/` 结构一致。 |
| `docs/source-tree-analysis.md` | 顶层目录和打包资源描述一致；`docs/` 注释已修正。 |
| `docs/ai-intent-chain.md` | 标准 `player_turn -> player_confirm`、external/internal AI 权限边界和 manifest 动作集合一致。 |
| `docs/save-and-campaign-packages.md` | Save/Campaign 分层、pending action/session、projection、package validation 与代码一致。 |
| `docs/cli-contracts.md` | CLI group、player/play/platform/MCP/legacy 边界一致；补充 exact package surface anchors。 |
| `docs/mcp-contracts.md` | profile gate、player-safe tools、low-level tools、path boundary 和 preflight 合同与代码一致。 |
| `docs/prompt-contracts.md` | `docs/prompts/` 长期位置、prompt 权限边界一致；补充 exact prompt surface anchors。 |
| `docs/authoring-guide.md` | 作者可编辑/禁止路径与 Campaign/Save 分层一致。 |
| `docs/testing-and-quality-gates.md` | CI 命令与 `.github/workflows/ci.yml` 一致；补充 Round 6 测试基线和 surface/intent fixtures。 |

## 残余风险

- `risk_class` 目前是 prompt 更新触发条件之一，但 `build_intent_manifest()` 的当前 action 输出没有填充
  `risk_class` 值；这不是当前文档错误，但后续若把 risk class 写入 manifest，需要同步 prompt、
  MCP 和 intent 文档。
- Pending action 的 session id、save binding 和可选 platform/session hash 已实现；过期时间、wrong actor
  文案和并发确认提示仍应继续按 residual backlog 跟踪。
- 归档原文仍保留旧测试基线、旧 `aigm migration apply` 名称和阶段性完成度旧说法；这是历史证据，
  不再作为 canonical 入口。后续读 archive 时必须以 canonical docs 和代码事实覆盖旧结论。

## 验证

已执行：

```bash
python3 -m pytest -q tests/test_surface_inventory.py
python3 -m pytest -q
python3 -m ruff check .
git add -N README.md docs _bmad-output rpg_engine tests
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

结果：

- `tests/test_surface_inventory.py`：`8 passed, 91 subtests passed`
- Full pytest：`449 passed, 483 subtests passed`
- Ruff：`All checks passed!`
- `git diff --check`：通过
- Markdown links：`checked 101 markdown files; local links ok`
