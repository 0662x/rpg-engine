# RPG Engine 项目上下文

文档状态：**CURRENT：BMAD / AI agent 项目宪法**

这份文档是 RPG Engine / AIGM Kernel 的长期项目上下文。BMAD agent、Codex
agent、Hermes agent 和人工贡献者在规划或编辑代码前都应读取它。它记录的是
项目的不可破坏边界、优先级和验证方式，不是一次性设计草稿。

## 产品定位

RPG Engine 是一个 local-first 的 AI GM kernel，用于长期文本 RPG 战役。它负责
保存事实、执行规则、校验状态变化、构建可查询上下文，并通过 CLI / MCP / 平台
入口暴露安全能力。

外部 AI 可以叙事、解释、建议和提出候选意图；引擎负责验证、预演、确认和提交。
一句话边界：

```text
AI proposes. Kernel verifies. Player confirms. Engine commits.
```

## 技术栈

- Python 3.11+
- SQLite 作为当前事实库和测试集成边界
- pytest 作为主测试框架
- Ruff 只启用当前仓库已有的关键 lint 规则
- CLI / MCP / platform sidecar 都必须薄封装 kernel service
- BMAD 已安装在 `_bmad/`，Codex/Hermes skills 生成在 `.agents/skills/`

## 不可破坏边界

- `data/game.sqlite` 是当前事实权威来源。
- events、JSONL、reports 是审计或投影证据，不是绕过写入校验的通道。
- 外部 AI 输出永远是低信任候选；internal intent AI 显式 `off` 时，合法 external candidate
  可以成为 selected route proposal，但仍不是事实、玩家确认、proposal approval 或写入授权。
- internal AI review 可以帮助分类和复核，但不能 preview、validate、confirm 或
  commit。
- `SaveManager.player_turn()` 可以创建 pending action，但不能提交游戏事实。
- `SaveManager.player_confirm()` 是普通玩家路径的提交门。
- MCP、CLI、platform sidecar 不允许复制业务逻辑；它们必须调用 kernel service。
- platform prewarm 只能产生 advisory / `message_only` preflight，不能驱动回合。
- hidden / GM-only 内容不能泄露到玩家视图、FTS、scene output 或普通 query。
- 正式当前 save package 不能被测试直接修改；写测试必须复制到临时目录。
- Campaign Package 与 Save Package 的职责必须分开，不能把剧情源数据和存档事实混在一起。

## BMAD 强约束流程

BMAD 是本仓库的强流程层。后续开发不是“想改哪里就改哪里”，而是先分类，再选工作流。

必须走 BMAD plan / story / review 的改动：

- AI intent、preflight cache、arbiter、binder、semantic routing
- Runtime / SaveManager / commit / projection / validation
- MCP、CLI、platform sidecar 的公开行为或权限边界
- Campaign Package / Save Package schema 或迁移
- 任何跨两个以上模块的重构
- 任何可能影响玩家可见输出、存档事实或隐藏信息边界的改动

小型 bugfix 可以直接实现，但仍必须：

- 读 touched module 和最近测试
- 跑最小有意义测试
- 在最终说明里写清楚变更边界、测试、剩余风险

具体 BMAD 使用规则见 `docs/governance/bmad-workflow.md`。

## 当前架构重点

当前代码已经完成 AI intent 调用链的阶段性收拢：

- candidate preparation 已抽出 side-effect-limited helper
- preflight production 复用同一套 candidate preparation
- Runtime、ContextBuilder、MCP、SaveManager、CLI 的 intent 参数已逐步 bundling
- platform prewarm / sidecar 已验证保持 advisory / forwarding 边界
- Phase 1-4 已通过最终回归门禁

这不代表未来 `IntentCoordinator` 已经实现。真正的 coordinator / package split 仍是后续工作。

## 开发优先级

1. 事实完整性优先于叙事便利。
2. 玩家确认和写入校验优先于自动化速度。
3. 清晰边界优先于聪明推断。
4. 小步提交优先于大爆炸重构。
5. 测试护栏优先于口头保证。
6. 文档同步优先于把设计留在聊天记录里。

## 必读文档

规划或大改前按顺序读取：

1. `docs/README.md`
2. `AGENTS.md`
3. `docs/governance/bmad-workflow.md`
4. `docs/development-workflow.md`
5. `docs/development-guide.md`
6. `docs/architecture.md`
7. `docs/component-inventory.md`
8. touched surface 对应的 canonical 文档
9. `docs/testing-and-quality-gates.md`

AI intent 相关改动还必须读取：

- `docs/ai-intent-chain.md`
- `docs/mcp-contracts.md`
- `docs/cli-contracts.md`
- `docs/prompt-contracts.md`

Save/Campaign、CLI、MCP、数据模型或作者流程相关改动还应读取：

- `docs/save-and-campaign-packages.md`
- `docs/data-models.md`
- `docs/authoring-guide.md`

## 测试期望

行为改动至少选择一种：

- pure helper 的 focused unit test
- SQLite / package state 的 integration test
- CLI / MCP / platform 的公开入口测试
- formal current package 相关的 current native regression

高风险写入路径必须包含 no-mutation、rollback、pending/confirm 或 hidden-content 断言。

AI intent / SaveManager / MCP / platform 改动必须说明：

- external AI 是否仍是低信任
- internal AI 是否仍只 review
- preview / validation / confirm / commit 是否仍在引擎内
- 是否影响 message-only preflight
- 是否影响玩家 profile 的 MCP 工具边界

## 收尾证据

每个完成的变更都必须能回答：

- 改了哪些文件
- 改的是行为、重构、测试还是文档
- 哪个边界被保护或改变了
- 跑了哪些测试
- 哪些测试没有跑，为什么
- 文档是否同步
- 是否有剩余风险
