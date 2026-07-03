# Round 5 文档迁移收尾门禁报告

文档状态：**COMPLETE：BMAD Round 5 docs gate**

日期：2026-07-04

## 目标

Round 5 的目标是确认 Round 4A-4C 文档迁移没有留下坏入口、坏链接或过时状态。
本轮不改 Python 行为代码。

## 检查范围

入口文档：

- [`README.md`](../README.md)
- [`AGENTS.md`](../AGENTS.md)
- [`docs/README.md`](../docs/README.md)
- [`docs/index.md`](../docs/index.md)
- [`docs/project-context.md`](../docs/project-context.md)
- [`docs/development-workflow.md`](../docs/development-workflow.md)
- [`docs/governance/bmad-workflow.md`](../docs/governance/bmad-workflow.md)
- [`docs/archive/README.md`](../docs/archive/README.md)

BMAD 迁移产物：

- [`planning-artifacts/bmad-documentation-migration-plan.md`](planning-artifacts/bmad-documentation-migration-plan.md)
- [`round-4-archive-map.md`](round-4-archive-map.md)

旧目录状态：

- `docs/architecture/`：只保留 compatibility stubs。
- `docs/specs/`：只保留 compatibility stubs。
- `docs/guides/`：只保留 compatibility stubs。
- `docs/archive/pre-bmad-docs-2026-07-03/`：保存 Round 4C 移动的旧原文。
- `docs/prompts/`：保持 active prompt artifact，由 [`docs/prompt-contracts.md`](../docs/prompt-contracts.md) 治理。

## 本轮修正

- `README.md` 的 Documentation 列表从旧 `docs/specs/*` / `docs/guides/*` / `docs/architecture/*`
  改为 canonical docs。
- `AGENTS.md` 的 AI intent 权威入口改为 `docs/ai-intent-chain.md`，阅读顺序改为 canonical docs。
- `docs/project-context.md` 的必读清单从旧 spec / architecture 文档改为 canonical docs。
- `docs/development-workflow.md` 的 change-area map 改为 canonical docs。
- `docs/governance/bmad-workflow.md` 明确旧 `specs`、`architecture`、`guides` 不再接收当前规范正文。
- `docs/development-guide.md` 明确 `docs/prompts` 是 active artifact，而不是普通旧文档。
- `docs/save-and-campaign-packages.md` 的旧文档映射说明改为 Round 4C 后的 archive/stub 状态。

## 引用检查结论

主动入口不再要求读旧 `docs/specs/*`、`docs/architecture/*` 或 `docs/guides/*` 作为当前权威。

仍保留旧路径引用的地方属于以下允许类别：

- compatibility stub 自身。
- canonical 文档中的 “旧来源 / 归档映射” 说明。
- `_bmad-output/` 历史 round 报告。
- `docs/archive/` 历史原文。

## 验证命令

已执行：

```bash
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m pytest -q tests/test_ai_intent.py tests/test_save_manager.py
```

结果：

```text
git diff --check: passed
checked 100 markdown files; local links ok
51 passed, 17 subtests passed in 7.32s
```

## 剩余风险

- Archive 原文内部仍可能以旧语境称某些旧文档为 CURRENT；这是历史证据语境，不作为当前权威。
- `_bmad-output/round-1` 到 `round-4` 报告保留当时状态，可能包含 “待迁移/旧目录” 叙述；读取时应以本报告、
  `docs/index.md` 和 migration plan 当前状态为准。
- 后续新增长期规范时，应更新 canonical docs，不应把新正文放回旧 `docs/specs`、`docs/architecture`
  或 `docs/guides` stub 目录。

## 结论

BMAD 文档迁移主线已收口：

- Round 1-3 建立并填充 canonical docs。
- Round 4A-4C 完成旧文档映射、摘取、prompt 决策、残余风险摘取、归档和 stub。
- Round 5 完成入口清理、引用检查和轻量回归。

后续文档工作进入常规维护模式：改动 touched surface 时同步 canonical docs，并把一次性证据放入
`_bmad-output/` 或 `reports/`。
