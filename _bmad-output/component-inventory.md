# 组件清单

文档状态：DRAFT / GDS full_rescan exhaustive component inventory
语言：zh-CN
工作流：`gds-document-project`
生成时间：2026-07-04
迁移阶段：BMAD 扫描输出；长期规范入口仍是 [`docs/component-inventory.md`](../docs/component-inventory.md)。

## BMAD Provenance

- 用户触发：`gds-document-project`
- Skill：`.agents/skills/gds-document-project/SKILL.md`
- Customization resolver：
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/gds-document-project --key workflow`
- Config：`_bmad/gds/config.yaml`
- Workflow instructions：
  `.agents/skills/gds-document-project/instructions.md`,
  `.agents/skills/gds-document-project/workflows/full-scan-instructions.md`
- 支撑文件：
  `.agents/skills/gds-document-project/checklist.md`,
  `.agents/skills/gds-document-project/documentation-requirements.csv`
- 模式：`full_rescan`
- 扫描深度：`exhaustive`

## 对外入口

| 组件 | 文件 | 当前责任 | 注意事项 |
| --- | --- | --- | --- |
| CLI | `rpg_engine/cli.py`, `rpg_engine/__main__.py` | 命令行入口、玩家/开发者操作面 | 调用 kernel service，不复制业务逻辑 |
| CLI V1 | `rpg_engine/cli_v1.py` | V1 命令实现和兼容入口 | campaign/save/play/mcp/player/platform/eval 是主要当前组 |
| Runtime API | `rpg_engine/runtime.py` | `GMRuntime` 编程门面 | start/query/preview/validate/commit 边界要分清 |
| MCP Adapter | `rpg_engine/mcp_adapter.py` | Profile-gated MCP 工具、配置、审计清洗 | 默认 player-safe；低层工具仅受信 profile |
| Platform Sidecar | `rpg_engine/platform_sidecar.py` | 平台入口门禁、冲突处理、指标 | 不提交事实，不复制 SaveManager/Runtime |

## 运行时与存档

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Game Session | `rpg_engine/game_session.py` | `GameSessionBinding`、`PlatformMessage` 和平台预热门禁辅助类型 |
| Save Manager | `rpg_engine/save_manager.py` | campaign/save 生命周期、玩家安全 `player_turn/player_confirm`、pending action/clarification、平台 session 校验 |
| Save Service | `rpg_engine/save_service.py` | 存档服务能力 |
| Save Validation | `rpg_engine/save_validation.py` | 存档结构与一致性校验 |
| Save Patch | `rpg_engine/save_patch.py` | 存档补丁 |
| Save Archive | `rpg_engine/save_archive.py` | 存档归档 |
| Projection Service | `rpg_engine/projection_service.py`, `rpg_engine/projections.py` | 事实投影刷新和查询材料 |

## AI 意图链

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Intent Router | `rpg_engine/intent_router.py` | 候选准备、规则路由、外部候选、配置与元数据 |
| Intent Manifest | `rpg_engine/intent_manifest.py` | 意图/动作能力声明 |
| AI Intent Router | `rpg_engine/ai_intent/router.py` | AI 候选收集、preflight 消费、内部复核、仲裁、绑定和 trace 组装 |
| AI Provider | `rpg_engine/ai/provider.py` | AI provider 抽象 |
| AI Policy | `rpg_engine/ai/policy.py` | AI 策略约束 |
| AI Schema Validation | `rpg_engine/ai/schema_validation.py` | AI 输出 schema 校验 |
| Arbiter | `rpg_engine/ai_intent/arbiter.py` | 候选裁决 |
| Binder | `rpg_engine/ai_intent/binder.py` | 槽位绑定 |
| Adapters | `rpg_engine/ai_intent/adapters.py` | 外部候选适配 |
| External | `rpg_engine/ai_intent/external.py` | 外部意图接入 |
| Internal Review | `rpg_engine/ai_intent/internal_review.py` | 内部复核 |
| Risk | `rpg_engine/ai_intent/risk.py` | 风险等级判断 |
| Slot Contract | `rpg_engine/ai_intent/slot_contract.py` | 槽位契约 |
| Preflight Cache | `rpg_engine/preflight_cache.py` | Advisory internal intent review cache；不是最终状态权威 |

## 动作系统

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Action Resolver Contract | `rpg_engine/actions/base.py` | `ActionResolverSpec` 预览核心合约 |
| Registry | `rpg_engine/actions/registry.py` | 动作解析器注册 |
| Builtin | `rpg_engine/actions/builtin.py` | 内建动作聚合 |
| Explore | `rpg_engine/actions/explore.py` | 探索动作 |
| Travel | `rpg_engine/actions/travel.py` | 移动/旅行 |
| Combat | `rpg_engine/actions/combat.py` | 战斗动作 |
| Rest | `rpg_engine/actions/rest.py` | 休息 |
| Gather | `rpg_engine/actions/gather.py` | 采集 |
| Craft | `rpg_engine/actions/craft.py` | 制作 |
| Social | `rpg_engine/actions/social.py` | 社交 |
| Random Table | `rpg_engine/actions/random_table.py` | 随机表动作 |
| Policy/Scope | `rpg_engine/actions/policy.py`, `rpg_engine/actions/scope.py` | 动作约束与作用域 |

## 写入链

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Runtime Preview | `rpg_engine/runtime.py` | `GMRuntime.preview_action()` 编排动作预览 |
| Preview Helpers | `rpg_engine/preview.py` | 部分动作复用的渲染/delta helper |
| Turn Proposal | `rpg_engine/proposal.py` | Pending/approved `TurnProposal`，确认、来源和 intent contract 边界 |
| Delta Schema | `rpg_engine/delta_schema.py` | turn delta 结构与辅助 |
| Validation Pipeline | `rpg_engine/validation_pipeline.py` | 多阶段校验 |
| Commit Service | `rpg_engine/commit_service.py` | 提交 turn proposal / delta |
| Unit of Work | `rpg_engine/unit_of_work.py` | SQLite 事务封装 |
| Write Guard | `rpg_engine/write_guard.py` | 写入保护 |
| Validation Issues | `rpg_engine/validation_issues.py` | 校验问题模型 |

## 上下文与渲染

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Context Builder | `rpg_engine/context_builder.py` | 上下文构建主入口 |
| Collectors | `rpg_engine/context/collectors.py` | 事实收集 |
| Resolution | `rpg_engine/context/resolution.py` | 引用和冲突解析 |
| Budget | `rpg_engine/context/budget.py` | 上下文预算 |
| Semantic | `rpg_engine/context/semantic.py` | 语义建议 |
| Rendering | `rpg_engine/context/rendering.py`, `rpg_engine/render.py` | 输出渲染 |
| Visibility | `rpg_engine/visibility.py` | 可见性边界 |
| Audit | `rpg_engine/context_audit.py` | 上下文审计 |

## 内容与作者工具

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Campaign | `rpg_engine/campaign.py`, `rpg_engine/campaign_validation.py` | Campaign Package 读取和校验 |
| Content Types | `rpg_engine/content_types/*` | 内容类型注册 |
| Content Delta | `rpg_engine/content_delta.py` | 内容增量 |
| Content Factory | `rpg_engine/content_factory.py` | 内容生成辅助 |
| Content Validation | `rpg_engine/content_validation.py` | 内容校验 |
| Authoring | `rpg_engine/authoring/*` | 作者工具、模板、doctor、拆分 |
| Palette | `rpg_engine/palette.py` | 内容调色板/选择材料 |
| Proposal Queue | `rpg_engine/proposal_queue.py` | 提案队列 |

## 平台与集成

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Platform Sidecar | `rpg_engine/platform_sidecar.py` | 平台入口门禁、冲突处理、指标 |
| Platform Prewarm | `rpg_engine/platform_prewarm.py` | 异步预热队列、worker、service |
| MCP Transcript | `rpg_engine/mcp_transcript.py` | MCP 转录/审计材料 |
| Capabilities | `rpg_engine/capabilities.py` | 能力声明 |
| Plugins | `rpg_engine/plugins.py` | 插件机制 |

## 基础设施与资源

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| DB | `rpg_engine/db.py` | SQLite 连接、schema 常量和基础操作 |
| Migrations | `rpg_engine/migrations.py`, `rpg_engine/resources/migrations/*.sql` | 迁移管理；打包资源到 `0008` |
| Root Migration Mirror | `migrations/*.sql` | 开发便利镜像；本轮发现只到 `0005` |
| Schemas | `rpg_engine/resources/schemas/*.schema.json` | 打包 JSON schema 权威 |
| Root Schema Mirror | `schemas/*.schema.json` | 开发便利镜像；缺少部分新 schema |
| Atomic IO | `rpg_engine/atomic_io.py` | 原子文件写入 |
| Backup | `rpg_engine/backup.py` | 备份 |
| Resource Paths | `rpg_engine/resource_paths.py` | 打包资源路径 |
| Ops Report | `rpg_engine/ops_report.py` | 运维报告 |

## 兼容与导入

| 组件 | 文件 | 当前责任 |
| --- | --- | --- |
| Legacy Actions | `rpg_engine/legacy/*` | 历史动作兼容 |
| Importers | `rpg_engine/importers/*` | 外部/旧内容导入 |
| Compat | `rpg_engine/compat/*` | 兼容边界 |

## 测试覆盖地图

本轮扫描确认 `tests/` 下约 50 个 `test_*.py` 文件，覆盖：

- Current native package/context。
- AI intent、external/internal review、preflight cache。
- MCP adapter、profile gate、transcript boundaries。
- Platform prewarm、platform sidecar、player session / concurrency。
- SaveManager、Save Package、projection、validation。
- CLI V1、package services、maintenance tooling。

## 本轮组件复核结论

- 组件职责与 canonical `docs/component-inventory.md` 大体一致。
- `_bmad-output/component-inventory.md` 原先是 Round 1 草稿状态；本文件已升级为本轮严格
  `gds-document-project` provenance 版本。
- 需要后续注意的 drift 不是模块归属，而是资源镜像：packaged migrations/schemas 领先 root mirrors。
