# 开发指南

文档状态：**CURRENT：BMAD canonical development guide**

## 开发前先判级

本仓库使用 BMAD 作为强流程层。开始编辑前先按 [BMAD 强约束开发流程](governance/bmad-workflow.md)
判断 P0 / P1 / P2。

P0 必须先规划，不能直接改代码：

- Runtime / SaveManager / commit / projection / validation。
- AI intent、preflight cache、arbiter、binder、semantic routing。
- MCP / CLI / platform sidecar 的公开行为、权限或参数语义。
- Campaign Package / Save Package schema、迁移、导入导出。
- 跨两个以上模块的重构。
- hidden / GM-only、玩家确认、pending action 或事实提交时机。

P1 可以小步实现，但必须有明确 plan 和 focused tests。P2 文档、注释、测试数据或低风险维护
可以直接改，但仍需要最小检查。

## 环境

项目要求 Python `>=3.11`。建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e ".[dev,mcp]"
```

## 常用命令

```bash
python3 -m pytest
python3 -m coverage run -m pytest -q
python3 -m coverage report
python3 -m ruff check .
python3 -m build
python3 -m twine check dist/*
```

CLI 入口：

```bash
aigm --help
rpg_engine --help
python3 -m rpg_engine --help
```

## CI 门禁

GitHub Actions 当前在 Python 3.11 和 3.12 上运行：

- 安装 `.[dev,mcp]`
- `python -m pytest -q`
- `python -m ruff check .`
- `python -m coverage run -m pytest -q`
- `python -m coverage report`
- installed CLI V1 flow smoke
- package build
- `python -m twine check dist/*`

参考 [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml)。

## 推荐工作流

1. 分类：判断 P0 / P1 / P2。
2. 读上下文：读取 [项目上下文](project-context.md)、[`../AGENTS.md`](../AGENTS.md) 和 touched surface 文档。
3. 规划：P0/P1 用 BMAD 生成或更新 PRD、spec、story 或 plan。
4. 设计：涉及架构边界时写 architecture note 或 ADR。
5. 实现：按 story 小步修改，不混入无关重构。
6. 测试：按风险选择 focused tests 和必要 regression gate。
7. Review：覆盖 engine boundary、AI safety、gameplay flow、QA 和 docs sync。
8. 文档同步：更新 canonical docs、旧领域 spec 或 implementation log。
9. 收尾：运行检查，说明变更边界、测试和剩余风险。

## 代码改动分级和验证

| 类型 | 示例 | 验证建议 |
| --- | --- | --- |
| 文档/治理 | BMAD 文档、README、计划 | `git add -N <new-files>`、`git diff --check`、Markdown 链接检查 |
| 局部逻辑 | 单个模块行为调整 | 对应单测 + 相关 smoke |
| 调用链调整 | intent/context/preview/commit 链路 | 相关模块测试 + 回归子集 |
| 数据模型 | schema/迁移/save 结构 | 迁移测试 + schema 测试 + save 测试 |
| 平台/MCP | sidecar/prewarm/mcp adapter | 平台测试 + MCP 测试 + intent 回归 |

## AI 意图链开发约束

- 规则候选、AI 候选、外部候选应保留来源和置信信息。
- `intent_router.py` 是外层兼容/规则候选 facade。
- `ai_intent/router.py` 的 `AIIntentRouter` 是 AI 意图链协调者。
- preflight cache 是 advisory internal intent review cache，不是最终状态权威。
- 预热结果必须绑定或校验 platform、session、message、context、provider、model、schema、task 等身份。
- `candidate_bound` profile 绑定候选身份。
- 平台预热常用 `message_only` profile，正式入口必须重新构建候选并验证身份。
- pending、wait、ready、failed、bypassed、late_ready_unused、ambiguous、expired、rejected、used 等状态或结局都要被显式处理。
- 意图裁决不能直接提交状态。
- 槽位绑定失败应进入澄清或安全 fallback。
- 新意图需要同步 manifest、schema、tests 和文档。

## 写入链开发约束

- 新动作必须接入 `ActionResolverSpec` 或明确说明等价预览合约。
- 新 delta 必须有 schema / validation 覆盖。
- 玩家动作必须先生成 pending `TurnProposal`，确认后才能提交。
- 提交路径必须走 validation pipeline 和 commit service。
- CLI、MCP、provider 不应直接写 SQLite 事实表。

## 上下文开发约束

- 新上下文来源必须标明 visibility。
- 语义建议不能泄露 hidden / GM-only 内容。
- 上下文预算变化需要有测试或明确基准。
- AI prompt 相关变更应同步审计材料。

## 文档规则

- `docs/` 是 canonical 文档区。
- `_bmad-output/` 是扫描、规划和实施产物区。
- 旧 `docs/architecture`、`docs/specs`、`docs/guides`、`docs/prompts` 内容不能批量照搬。
- 每篇旧文档迁移前必须判断：仍有效、部分有效、已过期、应归档。
- 长期入口更新 [`index.md`](index.md)。
- 一次性报告和 probe 输出放入 `reports/YYYY-MM-DD/`。

## 公开仓库约束

可以提交源码、测试、schema、示例 campaign、BMAD 文档和当前剧情包本体。不要提交真实玩家
存档、平台会话、运行缓存、密钥、私有配置、`.aigm/`、`saves/`、Save Package、玩家
SQLite、platform session 绑定、preflight cache 内容。

## 收尾证据

完成变更时必须能回答：

- 改了哪些文件。
- 改的是行为、重构、测试还是文档。
- 哪个边界被保护或改变。
- 跑了哪些测试。
- 哪些测试没有跑，为什么。
- 文档是否同步。
- 是否有剩余风险。
