# 通用文字 RPG 引擎规范

版本：v0.2（实现状态同步：2026-06-30）
文档状态：**CURRENT：当前实现契约**
文档基准：[`../specs/kernel-requirements.md`](../specs/kernel-requirements.md)
V1 产品边界：[`../specs/kernel-requirements.md`](../specs/kernel-requirements.md)

## 目标

为任意长期文字 RPG 提供通用底座：

- 精准保存当前事实
- 追加记录历史事件
- 快速查询实体/场景/规则
- 生成短上下文快照
- 支持内容包复用

## 分层

| 层 | 职责 |
|----|------|
| Engine Core | SQLite schema、迁移、事件日志、查询、渲染、校验、上下文管线、内容注册、进度钟 |
| GMRuntime | V1 稳定门面：`start_turn`、`query`、`preview_action`、`validate_delta`、`commit_turn`、`health` |
| Campaign Package | 世界观、规则、初始实体、world settings、随机表、模板、玩法声明和 smoke tests |
| Save Package | 某次游玩的 SQLite 状态、事件投影、snapshot/cards/memory 和 `.aigmsave` 归档 |
| CLI / MCP Adapter | 参考入口和 AI 客户端接入；只转调内核能力，不形成第二套业务逻辑 |
| AI Client Prompt | 规定 AI 客户端如何使用查询、预演、校验和保存工具 |

## V1 Package 目录约定

```text
campaign/
  campaign.yaml
  content/
    entities.yaml
    rules.yaml
    clocks.yaml
    random_tables.yaml
    world_settings.yaml
  prompts/
    gm.md
  templates/
    action.md
    query.md
  tests/
    smoke.yaml

save/
  campaign.yaml
  save.yaml
  data/
    game.sqlite
    events.jsonl
  snapshots/
    current.md
    current.json
  cards/
  memory/
```

## 运行原则

1. `data/game.sqlite` 是当前事实源。
2. `events` 表是当前权威审计记录；`data/events.jsonl` 是由 durable outbox 驱动的外部审计投影，不承担独立恢复保证。
3. `snapshots/current.md` 是 AI 新会话启动上下文。
4. 内容包可替换是目标边界；`player_entity_id`、玩家主资源标签和 ops/simulation 样例输入已支持 campaign defaults。旧 v1 importer 仍是 campaign-specific adapter。
5. 所有重要对象必须有稳定 ID。
6. `world_setting` 保存稳定世界解释，`rule` 保存硬边界，`clock` 只保存动态压力，`palette` 只保存尚未成为事实的候选。
7. 默认玩家视角不得读取 hidden 实体；GM/maintenance 视角必须显式选择。
8. 内容维护和正式回合分离；正式行动用 turn delta，资料维护用 content delta。
9. V1 普通路径是 Campaign Package + Save Package + GMRuntime + CLI/MCP；package upgrade/reconcile、migration、repair、plugin 仍属于 legacy/admin。

## 当前已知边界

- Content Registry 已实现内置注册、记录级 preflight、未知字段拒绝和引用预检；`faction_state` 已作为最小 runtime entity 类型可用。package validate/build/test/reconcile/install/diff/upgrade 已支持当前注册内容类型的字段所有权预览、数据库引用预检、冲突报告、新库初始化、legacy adoption 门禁、SQLite-backed package-lock 修复、同版本 checksum 阻断和 migration checksum 追踪。带 lock 的 package create/update 和受限显式 migration 可真实 apply。复杂脚本 migration、archive 直接安装与动态插件加载尚未实现。
- Action Resolver Registry 已接管六种既有行动和 `explore` 的 turn-assistant/直连 CLI preview、context 支持列表和 semantic prompt；已有统一 request/resolve/delta 合约入口，`travel/rest/gather/craft/social/combat` 均已迁入领域 resolve/delta 校验。
- 作者定义与运行状态尚未分层，核心内容类型不能安全地任意同步覆盖。
- JSONL 已使用 durable outbox；正式 turn/content delta/content sync 已统一到 UnitOfWork 生命周期；cards、snapshots、FTS、memory、reports 和 package_lock 已有 projection state/status/repair，但尚未全部实现统一增量投影。
- `0003_write_reliability` 已增加 migration checksum、写入 guard、outbox 和 projection state；旧库应用 migration 前必须自动备份并在应用后执行 `check`。
- V1 Campaign/Save Package、官方最小示例剧本、CLI 主路径、MCP Adapter 和通用 AI 客户端 prompt 已落地；默认 MCP player profile 暴露 `start_or_continue`、save/campaign 检查与选择、只读 `intent_manifest`、`player_turn`、`player_confirm`、`health`。`start_turn`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn` 等低层运行工具只在 developer/trusted/maintenance/admin profile 注册。
- Phase 5/6 后，低层 `commit_turn` 必须传入 preview 返回的 `TurnProposal`；默认普通玩家通过 `player_confirm` 保存，裸 delta 写入只允许走显式 admin/legacy 或 maintenance profile。
- 当前系统是 SQLite 状态快照模型，不是可仅凭 events 重放的完整事件溯源系统。
