# 源码树分析

文档状态：**CURRENT：BMAD canonical source tree**

## 顶层结构

```text
.
├── .agents/                  # BMAD/GDS 代理技能与工作流定义
├── .github/workflows/         # GitHub Actions CI
├── _bmad/                     # BMAD 配置与生成资源
├── _bmad-output/              # BMAD 扫描、规划和实施产物
├── docs/                      # canonical 文档、active prompts、archive stubs
├── examples/                  # 仓库级示例
├── migrations/                # 根级迁移/历史材料
├── reports/                   # 日期化报告和 probe 输出
├── rp/                        # 剧本/剧情包材料
├── rpg_engine/                # Python 引擎源码
├── run1/                      # save-like 运行数据，不进入 canonical 文档或公开仓库
├── schemas/                   # 根级 schema/历史材料
├── scripts/                   # 工具脚本
├── test_deltas/               # 测试 delta 样本
└── tests/                     # pytest 测试
```

## `rpg_engine/` 结构

```text
rpg_engine/
├── actions/                   # 内建行动解析和动作策略
├── admin/                     # 管理侧插件入口
├── ai/                        # AI provider、policy、schema validation、审计
├── ai_intent/                 # AI 意图候选、裁决、绑定、风险链
├── authoring/                 # 作者工具、拆分、模板、doctor
├── compat/                    # 兼容层
├── content_types/             # 内容类型注册
├── context/                   # 上下文收集、预算、语义、渲染、验证
├── importers/                 # 外部/旧内容导入
├── legacy/                    # 历史兼容动作
├── packages/                  # 包归档、锁定、合并、服务
├── resources/                 # 打包迁移、schema、示例、评估集
└── *.py                       # runtime、CLI、MCP、save、commit、preview 等核心模块
```

## 主要模块分组

| 分组 | 代表模块 | 责任 |
| --- | --- | --- |
| 对外入口 | `cli.py`, `__main__.py`, `runtime.py`, `mcp_adapter.py` | CLI/API/MCP 门面 |
| 运行时会话 | `runtime.py`, `save_manager.py`, `game_session.py` | 回合编排、存档管理、平台消息/绑定类型 |
| 预览/提案/写入链 | `actions/base.py`, `preview.py`, `proposal.py`, `validation_pipeline.py`, `commit_service.py`, `unit_of_work.py`, `write_guard.py` | 动作预览、`TurnProposal`、校验、提交、写保护 |
| AI 意图 | `intent_router.py`, `intent_manifest.py`, `ai_intent/router.py`, `ai_intent/*`, `preflight_cache.py` | 规则/兼容候选、AI 编排、裁决、绑定、advisory preflight cache |
| 上下文 | `context_builder.py`, `context/*`, `visibility.py`, `context_audit.py`, `render.py` | 可见上下文生成和审计 |
| 包/存档 | `campaign.py`, `save.py`, `save_service.py`, `packages/*`, `projection_service.py` | Campaign/Save 包与投影 |
| 内容生产 | `content_types/*`, `content_delta.py`, `content_factory.py`, `content_validation.py`, `authoring/*` | 内容类型、增量、作者工具 |
| 平台集成 | `platform_sidecar.py`, `platform_prewarm.py`, `mcp_transcript.py` | 平台入口、预热、转录 |
| 基础设施 | `db.py`, `migrations.py`, `atomic_io.py`, `backup.py`, `resource_paths.py` | 数据库、迁移、原子写、备份 |
| 兼容/导入 | `legacy/*`, `importers/*`, `cli_v1.py` | 历史兼容和导入 |

## 打包资源

[`rpg_engine/resources/`](../rpg_engine/resources/) 是当前权威打包资源目录：

- `migrations/0001_init.sql` 到 `0009_memory_summary_provenance.sql`
- `schemas/*.schema.json`
- `examples/blank_campaign`
- `examples/small_cn_campaign`
- `examples/v1_minimal_adventure`
- `evals/*`

## 测试结构

[`../tests/`](../tests/) 覆盖 CLI、运行时、save、intent、MCP、平台预热、上下文、内容、
迁移和校验等区域。测试层级和推荐门禁见 [测试与质量门禁](testing-and-quality-gates.md)。

## 文档结构

当前长期入口是 [`index.md`](index.md)。旧目录在 BMAD Round 4C 后只保留 compatibility stubs：

- [`architecture/`](architecture/)
- [`specs/`](specs/)
- [`guides/`](guides/)

归档原文位于 [`archive/pre-bmad-docs-2026-07-03/`](archive/pre-bmad-docs-2026-07-03/)。
`prompts/` 是 active prompt artifact 目录，由 [Prompt 合同](prompt-contracts.md) 治理。
归档原文包含阶段性设计、审查记录、重构计划和实现日志，只作历史证据。

## 运行数据风险

`.aigm/`、`saves/`、`run1/`、Save Package、玩家 SQLite、platform session 和 preflight
cache 都是运行数据或 save-like 数据。除非明确脱敏并转为示例，否则不要纳入公开仓库、
长期文档或 BMAD canonical 素材。
