# 源码树分析

文档状态：DRAFT / Round 1 Deep Scan
语言：zh-CN
迁移阶段：BMAD 扫描素材，未进入 canonical docs

## 顶层结构

```text
.
├── .agents/                  # BMAD/GDS 代理技能与工作流定义
├── .github/workflows/         # CI
├── _bmad/                     # BMAD 配置与生成资源
├── _bmad-output/              # BMAD 扫描与规划产物
├── docs/                      # 旧文档与已新增治理文档，待迁移
├── examples/                  # 仓库级示例
├── migrations/                # 根级迁移/历史材料
├── reports/                   # 报告输出
├── rp/                        # 剧本/剧情包材料
├── rpg_engine/                # Python 引擎源码
├── run1/                      # 当前工作区可见的 save-like 运行数据，不迁移到公开仓库
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
├── ai_intent/                 # AI 意图候选/裁决/绑定/风险链
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
| 预览/提案/写入链 | `actions/base.py`, `preview.py`, `proposal.py`, `validation_pipeline.py`, `commit_service.py`, `unit_of_work.py`, `write_guard.py` | 动作预览、TurnProposal、校验、提交、写保护 |
| AI 意图 | `intent_router.py`, `intent_manifest.py`, `ai_intent/router.py`, `ai_intent/*`, `preflight_cache.py` | 规则/兼容候选、AI 编排、裁决、绑定、advisory preflight cache |
| 上下文 | `context_builder.py`, `context/*`, `visibility.py`, `context_audit.py`, `render.py` | 可见上下文生成和审计 |
| 包/存档 | `campaign.py`, `save.py`, `save_service.py`, `packages/*`, `projection_service.py` | Campaign/Save 包与投影 |
| 内容生产 | `content_types/*`, `content_delta.py`, `content_factory.py`, `content_validation.py`, `authoring/*` | 内容类型、增量、作者工具 |
| 平台集成 | `platform_sidecar.py`, `platform_prewarm.py`, `mcp_transcript.py` | 平台入口、预热、转录 |
| 基础设施 | `db.py`, `migrations.py`, `atomic_io.py`, `backup.py`, `resource_paths.py` | 数据库、迁移、原子写、备份 |
| 兼容/导入 | `legacy/*`, `importers/*`, `cli_v1.py` | 历史兼容和导入 |

## 资源结构

`rpg_engine/resources/` 是打包资源目录：

- `migrations/0001_init.sql` 到 `0008_intent_joiner_message_only.sql`
- `schemas/*.schema.json`
- `examples/blank_campaign`
- `examples/small_cn_campaign`
- `examples/v1_minimal_adventure`
- `evals/*`

## 测试结构

`tests/` 当前约 50 个 `test_*.py` 文件，覆盖 CLI、运行时、save、intent、MCP、平台预热、上下文、内容、迁移和校验等区域。

## 文档结构风险

旧 `docs/` 数量较多，且包含阶段性设计、审查记录、重构计划和已实现状态混合内容。BMAD 迁移不能简单移动文件，需要逐篇判断：

- 当前代码事实是否仍然一致。
- 是架构规范、开发指南、历史决策还是归档材料。
- 是否已经被后续实现覆盖或反向修正。

## 运行数据风险

当前工作区可能出现 `.aigm/`、`saves/`、`run1/` 这类运行数据或 save-like 目录。它们不是源码树 canonical 内容，公开仓库整理时应默认排除，除非明确转成脱敏示例。
