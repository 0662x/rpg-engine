# AIGM Kernel Architecture Review

文档状态：**CURRENT：架构评估与代码结构边界**
评估日期：2026-06-30
适用范围：`rpg_engine`、V1 CLI/MCP、Campaign Package、Save Package、官方示例、测试与归档边界。

## 1. 结论

当前架构方向是正确的：它已经从“单个游戏的文档/脚本系统”收敛成了本地 AIGM Kernel。V1 主路径应继续保持：

```text
Campaign Package -> Save Package -> GMRuntime -> CLI/MCP Adapter -> AI Client
```

这条链路已经具备可发布基础：剧本校验、存档初始化/导入/导出/校验、行动预览、delta 校验、正式提交、MCP 转调和官方最小示例均可跑通。

主要架构风险不在核心方向，而在历史能力仍挤在同一个 CLI 入口里：`package *`、`projection *`、`migrate *`、`importer *`、`plugin *`、旧 preview/check/report 等能力仍有价值，但它们属于 legacy/admin，不应再出现在普通用户主路径里。

## 1.1 长期目标对齐

长期上，AIGM Kernel 要成为通用、本地优先、可发布、可扩展的 AI GM 游戏内核。架构演进必须持续服务这些目标：

- 强设定表达与召回：世界设定、种族、文化、势力、能力、遗迹、宗教、任务和场景可以被结构化保存、检索和进入 AI 上下文。
- 清晰分层：剧本定义、运行状态、AI 编排、规则结算、持久化和派生投影不能互相混写。
- 稳定写入：失败不能半写入；SQLite、events、snapshot、cards、search 等多份投影必须可检测、可修复。
- 注册式扩展：新增内容类型和行动类型应主要通过 registry 增加，减少中央分支。
- 通用内核：核心代码不包含具体游戏角色、物品、规则和世界观名称。
- 可维护工具链：schema、migration、版本、测试、文档、兼容策略和剧本升级流程都应可检查。

这些是长期方向，不是要求 V1 一次性完成一万实体、一万回合、完整插件生态或全自动剧本升级。

## 2. 当前代码结构

```text
rpg_engine/
  runtime.py                 # V1 Kernel API 门面；CLI/MCP 应优先调用这里
  mcp_adapter.py             # MCP 薄适配层，只暴露 V1 runtime 工具
  cli.py                     # CLI 聚合入口；保留 legacy/admin handler
  cli_v1.py                  # V1 campaign/save/play/mcp parser 与 handler
  save_service.py            # Save Package 初始化和 inspect 服务，供 CLI/MCP 复用
  capabilities.py            # V1 capability 单一权威源
  campaign*.py               # Campaign Package 加载、校验和 smoke test
  save*.py                   # Save Package、归档、patch、深度校验
  db.py / migrations.py      # SQLite、migration、初始化
  projections.py             # events_jsonl/search/snapshots/cards 投影状态
  packages/                  # Campaign Package source/lock/merge/archive/service
  content_types/             # 内容类型注册与写入 preflight
  actions/                   # 行动 resolver 与 preview/delta 合约
  context/ + context_builder.py
                             # 上下文管线与旧兼容 facade
  resources/                 # 安装包内 migrations/schema/example 资源
  admin/                     # admin/experimental 工具实现，如 plugin manifest 检查
  compat/                    # 旧内容/旧存档兼容实现，如 legacy importer
  legacy/                    # 兼容旧导出，不属于 V1 主路径
  package_*.py / plugins.py / importers/
                             # 兼容 wrapper；新代码不从这些路径导入
```

文档目录保留当前规范与发布入口：

```text
README.md
docs/README.md
docs/specs/kernel-requirements.md
docs/specs/campaign-package.md
docs/specs/save-package.md
docs/specs/cli.md
docs/specs/mcp-adapter.md
docs/prompts/ai-client-prompt.md
docs/architecture/review.md
docs/architecture/game-engine.md
schemas/
examples/
tests/
.github/workflows/ci.yml
```

## 3. 已整理/归档

- `docs/archive/2026-06-30/historical/`：归档旧 redesign/V2 设计文档和旧测试基线。它们只解释历史决策，不再定义当前目标。
- `docs/archive/2026-06-30/generated/`：归档误输出报告；本地构建产物和 egg-info 已清理，不作为源码交付物保留。
- `rpg_engine/legacy/actions_builtin.py`：归档旧 action 聚合导出；`rpg_engine/actions/builtin.py` 仅保留兼容 wrapper。
- `rpg_engine/cli_v1.py`：V1 普通用户命令已从 legacy/admin CLI handler 中拆出。
- `rpg_engine/save_service.py`：MCP 不再依赖 CLI handler，CLI/MCP 共同调用 save service。
- `rpg_engine/capabilities.py`：campaign validator、runtime 和 capability schema 通过测试锁定一致性。
- `rpg_engine/packages/`：迁入 `package_service`、`package_archive`、`package_lock`、`package_merge` 的实际实现；根层 `package_*.py` 只保留兼容 wrapper。
- `rpg_engine/admin/plugins.py`：迁入 plugin manifest 发现/校验实现；根层 `plugins.py` 只保留兼容 wrapper。
- `rpg_engine/compat/importers/`：迁入旧文档/旧游戏 importer 实现；根层 `importers/` 只保留兼容 wrapper。
- `.github/workflows/ci.yml`：新增公开 CI，覆盖安装、单元/回归、官方示例和存档校验。
- `.gitignore`：加入 Python/build/egg-info/venv/cache 规则，防止生成物回流源码。

`projection` 和 `migration` 仍保留在根层，因为它们既服务 V1 存档健康检查，也服务 admin repair/status；直接迁走会让核心写入可靠性边界变模糊。

## 4. V1 主路径边界

V1 普通用户主路径只应包含：

```text
aigm campaign copy-example
aigm campaign validate
aigm campaign test
aigm save init
aigm save inspect
aigm save validate
aigm save import
aigm save export
aigm save patch
aigm play start-turn
aigm play query
aigm play preview
aigm play commit
aigm mcp print-config
aigm mcp serve
```

MCP 只应转调：

```text
campaign_validate
save_inspect
start_turn
query
preview_action
validate_delta
commit_turn
health
```

不应把 admin、repair、migration、package upgrade、plugin、任意文件读写或模型代理暴露给普通 AI 客户端。

## 5. 架构优点

- SQLite 作为权威事实源，符合本地单用户文字 RPG 的部署和事务需求。
- GMRuntime 已形成稳定门面，CLI/MCP 不需要各写一套业务逻辑。
- Campaign/Save 分离正确，支持通用核心和可替换剧本。
- Content Type Registry、Action Resolver Registry 已经降低了新增玩法类型的耦合。
- `save validate` 深度检查 events、projection、snapshot、cards、search，能发现多事实源漂移。
- 随机表/骰子由内核生成并审计，避免 AI 叙事直接制造不可追溯结果。
- 官方最小示例可通过安装包复制，具备“装上就试跑”的发布体验。

## 6. 架构风险

1. `cli.py` 仍偏大，legacy/admin handler 还集中在一个文件里；V1 主路径已拆到 `cli_v1.py`。
2. `context_builder.py` 仍承担旧 facade 职责，新的 `context/` 管线尚未完全成为唯一入口。
3. 根层仍保留 `package_*.py`、`plugins.py`、`importers/` 兼容 wrapper；新代码已有边界测试禁止 V1/MCP 反向导入这些旧路径。
4. `schemas/` 和 `rpg_engine/resources/schemas/` 双份存在：前者是公开规范，后者是安装包资源；已有同步测试，但仍需要维护纪律。
5. definition/runtime 全量拆分尚未完成，部分运行态和剧本定义仍混在 entity/details 中。

## 7. 后续整理顺序

按收益和风险排序：

1. 继续瘦身 `cli.py`：把 package/projection/migrate/plugin/importer 的 parser/handler 拆到 `rpg_engine/admin/cli_*.py`，根入口只调 dispatcher。
2. 继续收敛公共 API：让普通 CLI/MCP 默认只调用 `GMRuntime`、campaign/save service，不直接碰底层 DB。
3. 把 `preview.py` 中的旧大分支继续迁移到 `actions/` resolver；旧 preview 只保留兼容入口。
4. 逐步拆 definition/runtime：先从 inventory/resource、project/task、relationship 这些 V1 类型开始。
5. 补许可证、发布版本策略和 PyPI 元数据后再正式公开发布。

## 8. 不建议做的事

- 不建议现在把 legacy/admin 模块大规模移动到 `archive/`。它们仍有测试覆盖，也仍承担兼容、迁移和维护职责。
- 不建议新增 Web 后端、HTTP API 或账号/同步能力。
- 不建议把 MCP 做成第二套业务层。
- 不建议让剧本作者写 Python resolver 或脚本规则作为 V1 默认能力。
- 不建议把 AI helper 做成核心依赖或事实写入入口。
