# AI GM 引擎文档基准与权威关系

文档状态：**HISTORICAL：2026-06-30 归档基线**  
基准日期：2026-06-30  
适用范围：`rpg-engine` 与 `rp/isekai-farm-v2` 的非归档设计、运行协议和内容规范

> 本文件保留文档整理前的基线记录。当前长期文档入口见 [`../../../README.md`](../../../README.md)。

## 1. 目的

本文件解决不同阶段文档同时存在时的三个问题：

1. 明确哪份文档描述当前实现，哪份描述未来目标。
2. 防止历史设计中的旧数字、旧阶段和旧假设影响新开发。
3. 规定代码、数据库、运行协议、目标设计和生成报告发生冲突时如何处理。

## 2. 归档时统一基准

截至基准日期：

| 项目 | 归档时事实 |
|------|----------|
| 正式存档活动实体 | 233 |
| 世界设定 | 10 |
| 进度钟 | 6 |
| 路线 | 26 |
| 长期记忆摘要 | 19 |
| 单元测试 | 146 OK |
| 回归测试 | 26 OK |
| 测试合计 | 172 OK |
| 正式数据库检查 | OK |
| GMRuntime V1 门面 | 已实现 `start_turn`、`query`、`preview_action`、`validate_delta`、`commit_turn`、`health` |
| V1 CLI 主路径 | 已实现 `campaign copy-example/validate/test`、`save init/inspect/validate/import/export/patch`、`play start-turn/query/preview/commit`，并拆入 `rpg_engine/cli_v1.py` |
| V1 capability 契约 | 已集中到 `rpg_engine/capabilities.py`，schema/runtime/validator 同步由测试约束 |
| V1 剧本包规范/校验器 | 已实现 `docs/specs/campaign-package.md`、campaign/capabilities/random_tables/smoke schema、V1 campaign validator 和 smoke runner，包含确定性 `random_table` smoke |
| V1 存档包规范/工具 | 已实现 `docs/specs/save-package.md`、`.aigmsave` 默认导出、`save inspect/validate` 深度一致性检查和受控 `save patch` |
| 官方最小示例剧本 | 已实现 `examples/v1_minimal_adventure`，覆盖 V1 游戏性最小闭环 capability |
| V1 MCP Adapter | 已实现 `docs/specs/mcp-adapter.md`、`aigm mcp serve/print-config` 和 8 个只读/运行时工具；MCP 不依赖 CLI handler |
| 发布整理 | 已实现 `docs/specs/cli.md`、`docs/prompts/ai-client-prompt.md`、README 快速开始、pip/pipx 安装说明、GitHub Actions CI 和测试基准 |
| V1.1 源码命名空间 | 已迁移 Campaign Package 实现到 `rpg_engine/packages/`，plugin manifest 检查到 `rpg_engine/admin/`，旧 importer 到 `rpg_engine/compat/`；根层旧路径仅保留兼容 wrapper |
| 内容维护 preflight | 已实现注册类型 record/reference 校验、未知字段拒绝和同步源预检 |
| Action Resolver Registry | 已实现 registry；六种既有 preview 与 `explore` 已迁移，request/resolve/delta 合约入口已统一，`travel/rest/gather/craft/social/combat` 均已有领域 resolve/delta 校验 |
| 定义/运行状态分层 | 已有 `faction_state` 最小 runtime entity；全量 definition/runtime 拆分未实现 |
| Outbox/投影版本 | 已实现 events JSONL outbox、package_lock 文件投影、projection state/status/repair；正式 turn/content delta/content sync 已统一 UnitOfWork 生命周期 |
| 剧本包编译、diff、upgrade | 已实现 package validate/build/test/reconcile/install/diff/upgrade、package-lock adopt/repair、create/update apply、自动备份、受限显式 migration 执行、同版本 checksum 阻断、migration checksum 追踪和 save export/import；V1 `.aigmsave` 已包含 `save.yaml` 与派生 cards 文件；复杂脚本 migration 未实现 |
| 外部插件发现 | 已实现 manifest 发现/校验门禁；动态代码加载未实现 |
| 写入并发/幂等 | `expected_turn_id`、`command_id` 已实现并由 `0003_write_reliability` 启用 |
| 主角 ID | 已迁入 campaign defaults；第二 campaign fixture 已通过 |

当前性能基线：233 个活动实体规模下，上下文构建约 1.2ms 平均值，全量 FTS 重建约 9.5ms，全量卡片生成约 39ms；最近一次 100 回合临时长跑平均 0.0014s、最大 0.0046s、check errors 0。这是本机小规模抽样，不代表一万实体目标已经达成。

### 2.1 本次基准验证证据

验证日期：2026-06-30；工作目录：`/Users/oliver/.hermes/rpg-engine`。

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/regression.py
python3 -m rpg_engine check ../rp/isekai-farm-v2
python3 -m rpg_engine migrate status ../rp/isekai-farm-v2
python3 -m rpg_engine projection status ../rp/isekai-farm-v2
python3 -m rpg_engine package validate ../rp/isekai-farm-v2
python3 -m rpg_engine package reconcile ../rp/isekai-farm-v2 ../rp/isekai-farm-v2
python3 -m rpg_engine package test ../rp/isekai-farm-v2 --campaign-dir ../rp/isekai-farm-v2
python3 -m rpg_engine package upgrade ../rp/isekai-farm-v2 ../rp/isekai-farm-v2 --dry-run
python3 -m rpg_engine simulate longrun ../rp/isekai-farm-v2 --turns 100 --budget 3000
```

结果：

- 单元测试：146/146 OK，33.734s。
- 回归测试：26/26 OK，7.440s。
- pip 安装后 CLI 验证：临时 venv 中 `pip install .` 后，`aigm campaign copy-example`、`campaign validate`、`campaign test`、`save init`、`save validate` 均 OK。
- MCP extra 临时 venv 验证：`pip install -e ".[mcp]"`、`FastMCP` 导入和工具白名单 OK。
- 100 回合临时长跑：平均 0.0014s，最大 0.0046s，check errors 0。
- 正式 campaign check：OK。
- 投影状态：cards/events_jsonl/memory/package_lock/reports/search/snapshots 全 clean，outbox empty。
- package validate：正式包 OK；65 entity、12 rule、6 clock、10 world_setting。
- package reconcile/test/dry-run：正式包 validate OK；对正式库 diff 因缺少 package-lock warning、71 个 drift records 和 9 个 entity `details` conflict-only 分叉而阻断；正式库未创建 package-lock。
- package upgrade apply：带 package-lock 的 create/update、`update_conflict_field`、`rename_entity`、新库 install、lock projection repair、同版本 checksum 阻断和 migration checksum mismatch 已有测试覆盖；正式包因缺少 lock 和 `details` 冲突仍阻断。
- `0003_write_reliability` 已在自动备份 `backup-20260629T082818523466+0000` 后应用到正式存档；只改变 schema/版本元数据，没有创建游戏回合或推进游戏时间。
- 测试中的回合、内容同步、故障注入和长跑写入均发生在临时副本。

## 3. 文档类型

统一使用以下状态：

| 状态 | 含义 |
|------|------|
| `TARGET` | 未来目标、强制过程和验收要求；不代表已经实现 |
| `CURRENT` | 当前代码和数据应具备的实现契约 |
| `OPERATING` | AI GM 运行当前游戏时必须遵守的协议 |
| `CONTENT` | 当前游戏包的内容结构与世界设计 |
| `HISTORICAL` | 已完成/旧阶段的设计记录；不能作为新开发目标覆盖 TARGET |
| `GENERATED` | 某次运行生成的报告或快照，只代表生成时点 |
| `ARCHIVED` | 只用于追溯，不参与当前开发决策 |

## 4. 权威优先级

同一问题发生冲突时按以下顺序处理：

1. **当前运行事实**：正式 `data/game.sqlite`，只决定当前存档事实。
2. **V1 目标要求**：`docs/specs/kernel-requirements.md`，决定当前收敛方向、scope、边界和验收。
3. **当前实现契约**：代码、migration、schema、`docs/architecture/game-engine.md`，决定当前命令实际应如何工作。
4. **当前游戏运行协议**：`rp/isekai-farm-v2/system/*.md`，决定 AI GM 如何安全使用现有实现。
5. **当前游戏内容规范**：`rp/isekai-farm-v2/content/*.md` 与 YAML，决定游戏世界内容边界。
6. **历史设计记录**：`docs/archive/2026-06-30/historical/AI_GM_ENGINE_MODULAR_REDESIGN.md`、`docs/archive/2026-06-30/historical/AI_GM_ENGINE_UPGRADE_DESIGN_V2.md`，用于理解既有决策，不再定义下一阶段优先级。
7. **生成报告**：`reports/*-current.md` 只证明生成时点的测试或状态，不定义架构。
8. **archive/backups**：只用于恢复和追溯。

注意：代码能运行不代表符合 TARGET；TARGET 描述未来要求时也不能被误写成当前已实现能力。

## 5. 文档清单

### 5.1 引擎文档

| 文档 | 状态 | 用途 |
|------|------|------|
| `docs/specs/kernel-requirements.md` | TARGET | V1 产品边界、交付范围、运行契约和验收要求 |
| `docs/architecture/game-engine.md` | CURRENT | 当前实现契约与已知边界 |
| `README.md` | CURRENT | 当前能力、命令入口和快速说明 |
| `docs/specs/campaign-package.md` | CURRENT | V1 剧本包规范与作者结构 |
| `docs/specs/save-package.md` | CURRENT | V1 存档包规范、归档和安全 patch |
| `docs/specs/cli.md` | CURRENT | V1 CLI 主路径与 legacy/admin 边界 |
| `docs/specs/mcp-adapter.md` | CURRENT | V1 MCP 工具契约、路径边界和接入流程 |
| `docs/prompts/ai-client-prompt.md` | OPERATING | 通用 AI 客户端运行 prompt |
| `docs/architecture/review.md` | CURRENT | 当前架构评估、代码结构边界和归档决策 |
| `docs/archive/2026-06-30/historical/AI_GM_ENGINE_UPGRADE_DESIGN_V2.md` | HISTORICAL | 旧升级设计，只作为实现参考，不再作为扩张主线 |
| `docs/archive/2026-06-30/historical/AI_GM_ENGINE_MODULAR_REDESIGN.md` | HISTORICAL | registry/world-setting 等既有改造记录 |
| `docs/archive/2026-06-30/historical/DOCUMENTATION_BASELINE.md` | HISTORICAL | 文档整理前的权威关系和统一数字基线 |

### 5.2 当前游戏运行协议

| 文档 | 状态 | 用途 |
|------|------|------|
| `system/README.md` | OPERATING | AI GM 运行入口和命令索引 |
| `system/GM_PROTOCOL.md` | OPERATING | 当前回合处理协议 |
| `system/QUERY_PROTOCOL.md` | OPERATING | 当前查询协议 |
| `system/SAVE_PROTOCOL.md` | OPERATING | 当前保存与维护协议 |
| `system/WORLD_GENERATION_POLICY.md` | OPERATING | AI 生成权限、候选与确认边界 |
| `system/CONTEXT_BUILDER_DESIGN.md` | CURRENT | 当前 Context Builder 的设计与已知限制 |

### 5.3 当前游戏内容文档

| 文档 | 状态 | 用途 |
|------|------|------|
| `content/ISEKAI_FARM_CONTENT_SPEC.md` | CONTENT | 当前内容包结构和维护边界 |
| `content/PALETTE_SYSTEM_DESIGN.md` | CONTENT | 素材库结构与投放规则 |
| `content/WORLD_SETTING_LIBRARY_DESIGN.md` | CONTENT | 当前 world_setting 实现和内容组织方式 |
| `content/WORLD_SETTING_PROPOSAL.md` | CONTENT | 已确认世界方向和仍待确认内容 |

## 6. 当前实现与目标架构的边界

开发时必须明确使用哪一列：

| 领域 | 当前实现 | V1 收敛目标 |
|------|----------|---------|
| 内容扩展 | 内置 Registry + record/reference preflight | 收敛为剧本包规范、校验器和普通作者可维护的 Markdown/YAML/JSON |
| 行动扩展 | Action Resolver Registry 已接管 turn-assistant/CLI preview 与支持列表；已有统一合约入口，`travel/rest/gather/craft/social/combat` 均已有领域 resolve/delta 校验 | 通过 `capabilities`、轻量规则、随机表和结构化 delta 表达；不引入作者自定义代码或插件 SDK |
| AI 输出 | 叙事回复 + 保守 delta 草案 + `proposal validate` guard | AI 客户端按内核上下文叙事；事实保存必须经 `validate_delta`/`commit_turn` |
| 状态模型 | entity 中定义与状态混合，已有 `faction_state` 最小 runtime entity | 支持精确事实和结构化模糊状态的保存、查询、校验和上下文构建 |
| 事件 | SQLite events + durable JSONL outbox | 保持 SQLite 为权威事实源，行动写入统一经 GMRuntime/UnitOfWork |
| cards/snapshot/FTS/memory | 已有 projection version/status/repair，包含 package_lock 文件投影；刷新仍部分全量 | V1 保持稳定可修复，不追求大规模增量投影目标 |
| 剧本/存档 | compat importer registry、content delta、`rpg_engine/packages/` 中的 package validate/build/test/reconcile/install/diff/upgrade、package-lock adopt/repair、package apply、save export/import、V1 campaign copy-example/validate/test、V1 save init/inspect/validate/patch、官方最小示例剧本、`save_service` | 已收敛为 Campaign Package + Save Package，旧文档迁移只承诺人工/AI 辅助整理后继续游玩 |
| 插件 | `rpg_engine/admin/plugins.py` manifest 发现/校验门禁，不加载代码 | V1 不做动态插件系统；MCP/CLI 只作为薄适配层调用 GMRuntime |

当前短期收敛顺序以 `docs/specs/kernel-requirements.md` 为准：`GMRuntime`、V1 CLI 主路径、`docs/specs/campaign-package.md`、V1 Campaign Validator、`docs/specs/save-package.md`、V1 Save Tools、官方最小示例剧本、MCP Adapter、发布整理和 V1.1 源码命名空间瘦身已完成。旧 V2/模块化文档只保留既有决策记录，不再定义下一阶段优先级。

旧协议继续描述当前实现，不能提前要求尚未存在的 V1 命令；V1 实现落地后，必须在同一提交中更新对应 OPERATING/CURRENT 文档。

## 7. 文档同步规则

任何影响下列事项的改动必须更新文档：

- CLI 名称、参数和默认值。
- schema、migration 和字段所有权。
- 内容类型、行动类型和可见性。
- 保存、备份、恢复和失败语义。
- AI 上下文、输出格式和 token 预算。
- 测试数量、性能基线和已知限制。
- 正式游戏运行协议。

每个阶段发布前执行：

```text
1. 更新 TARGET 的阶段状态。
2. 更新 CURRENT 的实际能力。
3. 更新 OPERATING 的实际命令和安全边界。
4. 更新 CONTENT 对新 schema 的使用方式。
5. 生成测试/运维报告。
6. 搜索旧测试数、旧世界设定数、旧命令和“已实现/未实现”描述。
```

## 8. 禁止做法

- 不复制 TARGET 目标到 README 并写成当前能力。
- 不使用 HISTORICAL 文档中的阶段顺序覆盖 V1 路线。
- 不把 GENERATED 报告当作长期规范。
- 不在 archive/backups 中批量改文档；这些目录必须保持历史原貌。
- 不仅更新设计文档而遗漏 GM/SAVE/QUERY 运行协议。
- 不仅修改代码而保留错误命令示例。
- 不用“基本完成”代替明确的缺失能力和验收结果。

## 9. 冲突处理

发现冲突时：

1. 先以代码、schema 和正式数据库确认当前事实。
2. 判断冲突属于 TARGET、CURRENT、OPERATING、CONTENT 还是 HISTORICAL。
3. CURRENT 文档写实际实现，不替代码掩饰缺陷。
4. TARGET 文档写目标和门禁，不把未实现内容标成完成。
5. 如果目标本身需要调整，必须修改 `docs/specs/kernel-requirements.md` 或增加 ADR。
6. 同步受影响文档并在验证报告中列出修改项。

## 10. 本基准不覆盖的文件

以下文件不参与当前文档同步：

- `archive_v1/**`
- `backups/**`
- 旧 `reports/**` 历史报告
- 自动生成的 `cards/**`
- 自动生成的 `snapshots/**`

这些文件保留生成时点或历史状态，不应为了“看起来一致”而改写。
