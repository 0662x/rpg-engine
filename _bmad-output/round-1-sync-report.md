# Round 1 同步记录

文档状态：DRAFT / Round 1 Deep Scan Close-out
语言：zh-CN
迁移阶段：BMAD 扫描素材，未进入 canonical docs
日期：2026-07-03

## 本轮目标

使用 BMAD `gds-document-project` 的 Deep Scan 思路，对当前仓库做一轮代码事实扫描，生成迁移前的临时文档基线。目标是为后续正式迁移 `docs/` 建立受控素材，而不是直接把旧文档批量搬进新结构。

## 已生成产物

- [扫描索引](./index.md)
- [项目概览](./project-overview.md)
- [源码树分析](./source-tree-analysis.md)
- [架构扫描](./architecture.md)
- [组件清单](./component-inventory.md)
- [数据模型](./data-models.md)
- [开发指南](./development-guide.md)
- [扫描状态 JSON](./project-scan-report.json)

## 扫描范围

- `README.md`
- `pyproject.toml`
- `.github/workflows/ci.yml`
- `docs/architecture/module-map.md`
- `docs/architecture/game-engine.md`
- `rpg_engine/` 关键 runtime、save、intent、context、platform、actions、package、infra 模块
- `rpg_engine/resources/migrations/*.sql`
- `rpg_engine/resources/schemas/*.json`
- `rpg_engine/resources/examples/**`
- `tests/test_*.py` 测试清单

## 排除和不迁移内容

- `__pycache__`、构建缓存、虚拟环境和临时输出。
- 旧 `docs/` 尚未迁移，只作为后续分类素材。
- `.aigm/`、`saves/`、Save Package、玩家 SQLite、平台 session、preflight cache 内容。
- 当前工作区可见的 `run1/` 属于 save-like 运行数据，除非后续脱敏转为示例，否则不进入公开仓库。
- `rp/` 后续只考虑当前剧情包本体，不迁移存档。

## 专家 review 结论

本轮派出 6 个 review 视角：架构、AI 意图、平台/MCP、数据模型、BMAD 文档治理、测试/CI。

已修正的问题：

- 将玩家主调用链修正为 `SaveManager.player_turn -> GMRuntime.act -> route_intent -> preview_intent/preview_action -> pending TurnProposal -> SaveManager.player_confirm -> GMRuntime.commit_turn`。
- 明确 `GMRuntime.start_turn` 主要是上下文构建入口，不是玩家动作提交主入口。
- 明确核心预览边界是 `ActionResolverSpec` 与 `GMRuntime.preview_action`，`preview.py` 只是部分动作 helper。
- 补入 `proposal.py` / `TurnProposal` 作为确认和提交前边界。
- 补入 `ai_intent/router.py` / `AIIntentRouter` 作为 AI 意图链实际协调者。
- 将 `preflight_cache.py` 从“平台预热缓存”修正为 advisory internal intent review cache。
- 补充 `candidate_bound` 与 `message_only` profile、预热生命周期、竞态和敏感数据风险。
- 修正平台绑定边界：workspace/runtime 级 `.aigm/game-session-bindings.json`，不属于 Save Package。
- 补充 `.aigm/`、`saves/`、Save Package、玩家 SQLite、platform session、preflight cache 均不得公开。
- 将 CI 命令修正为 `coverage run -m pytest -q`、`coverage report`、`ruff check .`。
- 新增 `scripts/check_markdown_links.py`，让 Markdown 本地链接检查可重复执行。
- 将 `project-scan-report.json` 修正为 BMAD resumability state schema 所需字段。
- 修正 SQLite 后续迁移清单：`0004` 创建 `discovery_states` 与 `proposal_queue`，`0005` 创建 `archivist_suggestions`。
- 统一新增文档的状态头，明确 `_bmad-output/` 是待校准扫描素材，不是 canonical docs。

## 仍需后续处理

- 将本扫描结果整理到 `docs/` 下的正式 BMAD 文档骨架。
- 对旧 `docs/` 建立迁移清单：有效、部分有效、过期、归档。
- 对公开仓库策略做单独安全轮：检查并必要时更新 `.gitignore`，尤其是 `.aigm/`、`saves/`、`run1/`、Save Package 和剧情包存档。
- 后续可把 `scripts/check_markdown_links.py` 接入 CI。
- 为 AI 意图链、平台预热链、玩家确认提交链分别建立 canonical 章节。

## 验证记录

本轮修改代码行为：无。

已执行验证：

- `python3 -m json.tool _bmad-output/project-scan-report.json >/dev/null`
- `_bmad-output/*.md` 本地相对链接检查
- `git add -N _bmad-output && git diff --check`
- `python3 scripts/check_markdown_links.py _bmad-output`
- `python3 scripts/check_markdown_links.py docs _bmad-output`
- `python3 -m ruff check scripts/check_markdown_links.py`
- `project-scan-report.json` 按 BMAD `project-scan-report-schema.json` 验证
- `python3 -m pytest -q`

测试结果：

- 第一次：`449 passed, 483 subtests passed in 72.10s`
- 第二次：`449 passed, 483 subtests passed in 67.98s`

说明：第二次全量 pytest 在新增固定链接检查脚本后执行，确认本轮文档/工具脚本变更未引入测试回归。

## 迁移判断

本轮产物可以作为后续 BMAD 迁移的 reviewed scan material，但不能直接视为最终文档。下一轮应开始创建 `docs/` canonical 骨架，并逐步把旧文档中的有效内容吸收到新结构里。
