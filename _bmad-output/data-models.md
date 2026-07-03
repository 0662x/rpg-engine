# 数据模型

文档状态：DRAFT / Round 1 Deep Scan
语言：zh-CN
迁移阶段：BMAD 扫描素材，未进入 canonical docs

## 权威状态

Save Package 内的 SQLite 数据库是当前状态权威。事件表提供审计与回放材料，事实表和领域表提供当前查询与上下文构建材料。

## 初始迁移

`rpg_engine/resources/migrations/0001_init.sql` 定义基础表：

| 表 | 责任 |
| --- | --- |
| `meta` | 数据库元信息 |
| `turns` | 回合记录 |
| `events` | 状态事件流 |
| `entities` | 通用实体 |
| `aliases` | 名称/别名 |
| `facts` | 事实表 |
| `characters` | 角色 |
| `items` | 物品 |
| `locations` | 地点 |
| `routes` | 路线 |
| `crop_plots` | 作物/地块 |
| `clocks` | 时钟 |
| `rules` | 规则 |
| `memory_summaries` | 记忆摘要 |
| `context_runs` | 上下文构建运行记录 |
| `context_items` | 上下文条目 |
| `fts_index` | 全文索引 |

## 后续迁移

| 迁移 | 主题 | 关键表/字段 |
| --- | --- | --- |
| `0002_world_settings.sql` | 世界设定扩展 | `world_settings` |
| `0003_write_reliability.sql` | 写入可靠性 | `schema_migrations.checksum`、`outbox`、`projection_state` |
| `0004_discovery_proposals.sql` | 发现/提案 | `discovery_states`、`proposal_queue` |
| `0005_archivist_proposal_queue.sql` | archivist 建议 | `archivist_suggestions` |
| `0006_intent_preflight_cache.sql` | 意图预热缓存 | `intent_preflight_cache` |
| `0007_intent_preflight_identity_hardening.sql` | 预热身份硬化 | context/provider/model/backend/fallback/profile 等身份字段与索引 |
| `0008_intent_joiner_message_only.sql` | 意图 joiner message-only 优化 | message-only join 相关索引/字段 |

`schema_migrations` 由迁移 runner 创建，后续迁移会补充 checksum 等字段。权威迁移目录是 `rpg_engine/resources/migrations/`。

## 意图预热缓存

`intent_preflight_cache` 是 advisory internal intent review cache。平台预热是重要生产者，但 CLI/MCP/runtime 也可以创建或消费 preflight 结果。它保存消息级/会话级/上下文级的预热候选和状态，用于让正式入口在重新校验身份后复用已经完成的意图识别结果。

关键概念：

- `status`：预热状态。
- `platform` / `session_key` / `message_id`：平台消息身份。
- `save_id` / `base_turn` / `context_hash`：存档与上下文身份。
- `provider` / `model` / `backend`：AI 来源。
- `fallback` / `bypassed` / `late_ready`：降级与时序状态。
- `hash` / `profile`：结果身份与配置。
- `user_text`、platform、session/message 标识、internal review 和 helper audit：敏感运行数据。

架构约束：缓存只能作为候选来源，不能绕过最终上下文校验、preview、validation 和 commit。

## JSON Schema

打包 schema 位于 `rpg_engine/resources/schemas/`：

- `campaign.schema.json`
- `turn_delta.schema.json`
- `intent_candidate.schema.json`
- `internal_intent_review.schema.json`
- `semantic_suggestion.schema.json`
- `save_patch.schema.json`
- `content_delta.schema.json`
- `state_audit.schema.json`
- `reflection_draft.schema.json`
- `random_tables.schema.json`
- `capabilities.schema.json`
- `archivist.schema.json`
- `smoke.schema.json`

这些 schema 是 AI 输出、内容包、状态补丁和能力声明的主要结构约束。

## 包模型

### Campaign Package

Campaign Package 承载世界、规则、内容、capabilities、smoke tests、作者提示和模板。示例包位于：

- `rpg_engine/resources/examples/blank_campaign`
- `rpg_engine/resources/examples/small_cn_campaign`
- `rpg_engine/resources/examples/v1_minimal_adventure`

### Save Package

Save Package 承载一个存档实例的状态、SQLite 数据库、事件、投影、snapshots、cards/memory 和运行时存档元数据。

Save Package 不承载 workspace 级平台绑定。平台绑定默认位于 `.aigm/game-session-bindings.json`，由 `GameSessionBindingStore` 管理；`.aigm/save-registry.json` 和 `.aigm/pending-*` 也属于 workspace/runtime state。

### RP / 剧情包材料

`rp/` 是当前剧本/剧情包材料区域。公开仓库策略应只纳入当前最新剧情包本体，不纳入玩家存档、运行时缓存或私有历史记录。

## 数据治理建议

- schema 变更必须配套测试和迁移说明。
- SQLite 表结构变更必须通过迁移文件进入。
- AI 输出结构变更必须同步 `intent_candidate`、`internal_intent_review` 或相关 schema。
- Save Package 内玩家进度数据默认不进入公开仓库。
- `.aigm/`、`saves/`、Save Package、玩家 SQLite、平台 session 绑定和 preflight cache 内容默认不进入公开仓库。
- 示例 campaign 可进入公开仓库，真实存档和平台会话数据不进入公开仓库。
