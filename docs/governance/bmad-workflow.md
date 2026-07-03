# BMAD 强约束开发流程

文档状态：**CURRENT：BMAD / AI-assisted development workflow**

本仓库使用 BMAD 作为 AI-assisted development 的强流程层。BMAD 不替代测试、
CI、代码审查和 Git 历史；它负责让需求、架构、story、实现、测试和文档同步
变成可重复流程。

## 安装状态

- BMAD 安装目录：`_bmad/`
- BMAD 输出目录：`_bmad-output/`
- Codex / Hermes skill 目录：`.agents/skills/`
- 已安装模块：
  - BMad Core / BMM
  - BMad Game Dev Studio
  - Test Architect
- 当前配置：
  - 交流语言：中文
  - 文档输出语言：中文
  - 项目知识目录：`docs`
  - 测试框架：pytest
  - CI 平台目标：GitHub Actions

## 角色模型

默认使用六角色 gate：

| 角色 | 职责 |
| --- | --- |
| Product / PM | 判断需求价值、范围和验收条件 |
| Game Architect | 保护引擎边界、模块归属和长期架构 |
| Game Developer | 实现 story，保持 diff 小而可测 |
| AI Intent Safety | 审查 external/internal AI、preflight、trust boundary |
| Test Architect | 风险分级、测试设计、回归门禁 |
| Docs / Repo Maintainer | 文档同步、提交范围、索引和 Git hygiene |

不是每个小改动都要开完整会议，但高风险改动必须留下这些视角的证据。

## 改动分级

### P0：必须先规划，不能直接改代码

满足任一条件即为 P0：

- 改 Runtime / SaveManager / commit / projection / validation。
- 改 AI intent、preflight cache、arbiter、binder、semantic routing。
- 改 MCP / CLI / platform sidecar 的公开行为、权限或参数语义。
- 改 Campaign Package / Save Package schema、迁移、导入导出。
- 跨两个以上模块的重构。
- 可能泄露 hidden / GM-only 内容。
- 可能改变玩家确认、pending action 或事实提交时机。

P0 必须至少产出：

- PRD / spec / proposal
- architecture 或 ADR
- story / task list
- test design 或 regression gate
- code review 记录
- docs sync 记录

### P1：可以小步实现，但必须有明确 plan

满足任一条件即为 P1：

- 单模块行为改动。
- 新增 CLI/MCP 参数但不改变旧语义。
- 新增测试工具、报告或维护命令。
- 性能、上下文质量、查询质量调整。

P1 必须产出：

- 简短 plan
- focused tests
- 风险说明
- 必要文档同步

### P2：低风险维护

满足任一条件即为 P2：

- 注释、文档、测试数据、无行为 refactor。
- 明确的 typo / link / formatting 修复。
- 不影响 runtime 的内部测试整理。

P2 可以直接改，但仍必须跑最小检查。

## 推荐 BMAD skill

规划和设计：

- `bmad-help`
- `bmad-prd`
- `bmad-spec`
- `bmad-create-architecture`
- `gds-prd`
- `gds-game-architecture`
- `gds-create-story`

实现：

- `bmad-dev-story`
- `bmad-quick-dev`
- `gds-dev-story`
- `gds-quick-dev`

测试和质量：

- `bmad-tea`
- `bmad-testarch-test-design`
- `bmad-testarch-test-review`
- `bmad-testarch-trace`
- `gds-test-design`
- `gds-test-review`

复盘和纠偏：

- `bmad-code-review`
- `gds-code-review`
- `bmad-correct-course`
- `gds-correct-course`
- `bmad-retrospective`

## 标准工作流

P0/P1 改动使用以下流程：

1. 分类：按 P0/P1/P2 判断风险。
2. 读上下文：读取 `docs/project-context.md`、`AGENTS.md` 和 touched surface 文档。
3. 规划：用 BMAD 生成或更新 PRD/spec/story。
4. 设计：涉及架构边界时写 architecture note 或 ADR。
5. 实现：按 story 小步提交，不混入无关重构。
6. 测试：按 Test Architect 建议跑 focused tests 和必要 regression gate。
7. Review：至少覆盖 engine boundary、AI safety、gameplay flow、QA、docs sync。
8. 文档同步：更新 docs、implementation log、ADR 或 governance 文档。
9. 提交：提交信息说明行为边界，不只列文件名。

## RPG Engine 专属硬门禁

AI intent / SaveManager / MCP / platform 改动合入前必须回答：

- external AI 是否仍只是 low-trust candidate？
- internal AI 是否仍不能 preview / validate / confirm / commit？
- preflight cache 是否仍是 advisory、single-use、identity-bound？
- `message_only` preflight 是否仍不带 external candidate？
- `player_turn` 是否仍不提交事实？
- `player_confirm` 是否仍是 commit gate？
- MCP player profile 是否仍不能调用低层工具？
- platform sidecar 是否仍只 gate / forward passive identity？

若答案不清楚，不能合入。

## 验证基线

优先跑最小有意义测试。高风险 intent / platform / SaveManager 改动至少考虑：

```bash
python3 -m pytest -q tests/test_ai_intent.py tests/test_runtime.py tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py tests/test_platform_sidecar.py \
  tests/test_save_manager.py tests/test_v1_cli.py \
  tests/test_current_native_context.py tests/test_context_quality.py

git diff --check
```

如果测试没跑，必须记录原因和剩余风险。

## 输出和入库规则

- 长期项目知识放 `docs/`。
- BMAD 临时规划产物默认放 `_bmad-output/`。
- 需要长期保留的 BMAD 产物应整理进 `docs/specs`、`docs/architecture`、
  `docs/governance` 或 `docs/guides`，并在 `docs/README.md` 登记。
- `_bmad/config.user.toml` 是个人安装配置，不入库。
- 不要手改 `_bmad/config.toml`；要改安装答案，重新运行 BMAD installer。

## 完成定义

一个 BMAD 管控下的改动只有同时满足以下条件，才算完成：

- scope 清楚。
- tests 跑过或明确记录未跑原因。
- docs 同步。
- review 结论无 blocker。
- git worktree 干净。
- 远端分支已同步，除非用户明确要求只保留本地。
