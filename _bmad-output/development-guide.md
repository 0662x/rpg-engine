# 开发指南

文档状态：DRAFT / Round 1 Deep Scan
语言：zh-CN
迁移阶段：BMAD 扫描素材，未进入 canonical docs

## 本轮定位

这是 BMAD Deep Scan 生成的临时开发指南，用于约束后续文档迁移和开发流程。正式版本后续应迁入 `docs/development-guide.md`。

## 环境

项目要求 Python `>=3.11`。建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,mcp]"
```

## 常用命令

```bash
python -m pytest
python -m coverage run -m pytest -q
python -m coverage report
python -m ruff check .
python -m build
python -m twine check dist/*
```

CLI 入口：

```bash
aigm --help
rpg_engine --help
python -m rpg_engine --help
```

## CI 门禁

GitHub Actions 当前在 Python 3.11 和 3.12 上运行：

- 安装 `.[dev,mcp]`
- `pytest`
- `coverage run -m pytest -q`
- `coverage report`
- `ruff check .`
- CLI smoke
- package build
- `twine check`

参考：[.github/workflows/ci.yml](../.github/workflows/ci.yml)

## BMAD 开发流程

从本轮开始，开发和文档应遵循 BMAD 约束：

1. 先写或更新对应文档/计划。
2. 明确本轮目标、影响范围和不改范围。
3. 小步修改代码。
4. 运行与影响范围匹配的验证。
5. 做专家视角 review。
6. 同步文档状态。
7. 提交并推送。

## 文档迁移规则

- `_bmad-output/` 是扫描和规划区。
- `docs/` 后续作为 canonical 文档区。
- 旧 `docs/` 内容不能批量照搬。
- 每篇旧文档迁移前必须判断：仍有效、部分有效、已过期、应归档。
- 旧决策记录可以归档，但不能覆盖当前代码事实。

## 代码改动分级

| 类型 | 示例 | 验证建议 |
| --- | --- | --- |
| 文档/治理 | BMAD 文档、README、计划 | `git add -N <new-files>` 后跑 `git diff --check`、本地 Markdown 链接检查 |
| 局部逻辑 | 单个模块行为调整 | 对应单测 + 相关 smoke |
| 调用链调整 | intent/context/preview/commit 链路 | 相关模块测试 + 回归子集 |
| 数据模型 | schema/迁移/save 结构 | 迁移测试 + schema 测试 + save 测试 |
| 平台/MCP | sidecar/prewarm/mcp adapter | 平台测试 + MCP 测试 + intent 回归 |

## AI 意图链开发约束

- 规则候选、AI 候选、外部候选应保留来源和置信信息。
- `intent_router.py` 是外层兼容/规则候选 facade，`ai_intent/router.py` 的 `AIIntentRouter` 是 AI 意图链协调者。
- preflight cache 是 advisory internal intent review cache，不是最终状态权威。
- 预热结果必须绑定或校验 platform/session/message/context/provider/model/schema/task 等身份。
- `candidate_bound` profile 绑定候选身份；平台预热常用 `message_only` profile，正式入口必须重新构建候选并验证身份。
- pending/wait、ready、failed、bypassed、late_ready_unused、ambiguous、expired/rejected/used 等状态或结局都要被显式处理。
- 意图裁决不能直接提交状态。
- 槽位绑定失败应进入澄清或安全 fallback。
- 新意图需要同步 manifest、schema、tests 和文档。
- preflight cache 可能包含原始玩家输入、platform/session/message 标识、internal review 和 audit，不能公开提交。

## 写入链开发约束

- 新动作必须接入 `ActionResolverSpec` 或明确说明等价预览合约。
- 新 delta 必须有 schema/validation 覆盖。
- 玩家动作必须先生成 pending `TurnProposal`，确认后才能提交。
- 提交路径必须走 validation pipeline 和 commit service。
- 不应让 CLI/MCP/provider 直接写 SQLite 事实表。

## 上下文开发约束

- 新上下文来源必须标明 visibility。
- 语义建议不能泄漏隐藏内容。
- 上下文预算变化需要有测试或明确基准。
- AI prompt 相关变更应同步审计材料。

## 公开仓库约束

- 可以提交源码、测试、schema、示例 campaign、BMAD 文档和当前剧情包本体。
- 不提交真实玩家存档、平台会话、运行缓存、密钥、私有配置。
- 不提交 `.aigm/`、`saves/`、Save Package、玩家 SQLite、platform session 绑定、preflight cache 内容。
- 当前工作区可见的 `run1/` 属于 save-like 运行数据，除非脱敏转为示例，否则不进入公开仓库。
- `_bmad/config.user.toml` 已被忽略。
- BMAD vendor/generated 内容由 `.gitattributes` 标记，避免无意义 whitespace 噪声。

## 文档验证建议

文档-only 变更至少应执行：

```bash
git add -N _bmad-output docs
git diff --check
python3 -m json.tool _bmad-output/project-scan-report.json >/dev/null
python3 scripts/check_markdown_links.py _bmad-output docs
```

## 下一轮建议

下一轮应把本扫描产物整理成 `docs/` 下的正式 BMAD 文档骨架，并建立旧文档迁移清单。
