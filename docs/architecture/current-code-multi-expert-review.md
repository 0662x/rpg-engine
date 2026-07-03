# RPG Engine 当前实现多专家代码评审与优化方案

日期：2026-07-01

更新说明（2026-07-03）：本文主体保留当时代码评审发现。后续已经完成默认 MCP player surface 收窄：`player_turn` / `player_confirm` 成为默认自然语言与确认入口，`player_query`、`player_act`、`start_turn`、`intent_preflight`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn` 只在 low-level profile 注册。下文涉及“默认暴露低层工具”的表述按历史发现理解，并在相关条目补充当前状态。

范围：本评审只看 `/Users/oliver/.hermes/rpg-engine` 当前已经实现的引擎代码、示例、测试和项目配置。评审不按愿景或路线图打分，只按代码现实打分。

方法：按“RPG Engine 全链路设计说明和优化方案”中的 12 个角色视角进行多专家审查。每个角色给出 0-100 分，100 表示该角色认为当前实现已接近可发布、可长期维护、可低信任接入的成熟状态；60-70 表示核心可运行但仍有明显边界、可靠性或质量门问题；低于 60 表示该角色视角下存在需要优先治理的系统性缺口。

验证命令：

```bash
python3 -m pytest -q
python3 -m pytest --collect-only -q
python3 -m pytest --collect-only -q tests/test_regression.py
python3 -m ruff check .
python3 -m coverage --version
```

验证结果：

- `python3 -m pytest -q`：`174 passed, 77 skipped, 173 subtests passed`
- 默认 pytest 收集：`251 tests`
- `tests/test_regression.py` 显式收集：`26 tests`
- `python3 -m ruff check .`：当前环境失败，`No module named ruff`
- `python3 -m coverage --version`：当前环境失败，`No module named coverage`

## 总体结论

综合评分：**67/100**。

12 位专家的算术均分约为 67.4。考虑到安全、数据评估、SRE、QA 分数偏低，并且这些问题会影响低信任 MCP 接入、长期运行和发布质量门，保守取整为 67。

当前 RPG Engine 已经具备一个可运行的本地 AIGM 内核：`preview -> validate -> commit` 主链路、TurnProposal、ValidationPipeline、State Auditor、projection/outbox、SaveManager、campaign/package 工具和示例内容都已经存在，测试体量也不薄。

但当前代码更接近“本地可信单用户原型/开发者工具链”，还不能称为“默认安全、玩家体验完整、可发布、可长期运行”的 RPG 引擎。核心差距集中在：

1. 安全与权限边界尚未封口。
2. 玩家体验层和内核 delta/commit 层混在一起。
3. 保存、投影、备份、导入导出的崩溃一致性不足。
4. 架构分层方向正确，但 Runtime、CLI、preview、render、projection 仍承担过多 owner。
5. 测试不少，但 CI、真实 MCP 传输、回归收集、ruff/coverage、发布包验证不完整。
6. 数据评估处于“可观测但未量化”状态，缺少 accuracy、recall、consistency、block rate 等门禁指标。

## 12 角色量化评估

| 角色 | 分数 | 评估摘要 |
|---|---:|---|
| 产品经理 | 78 | 核心链路和功能覆盖较完整，但玩家闭环仍不够产品化。 |
| UX/交互设计师 | 64 | 玩家界面暴露 delta、ID、Context Packet 和 commit 流程，体验像开发工具。 |
| 游戏设计师/内容作者 | 76 | 内容治理和低幻觉设计强，但 action、clock、resolver heuristic 仍偏硬编码。 |
| 软件架构师 | 72 | 分层雏形清楚，V1 主链路可跑，但 Runtime/CLI/preview/render/projection owner 仍集中。 |
| 后端/内核工程师 | 72 | 写入骨架扎实，事务、proposal、outbox 都有；但 guard 强制性、patch 一致性和 archive 原子性不足。 |
| AI Agent 工程师 | 70 | 外部 Agent 合同有意识，但 MCP 默认工具仍暴露低层对象和 maintenance 读面。 |
| AI/ML 与提示词工程师 | 74 | No-AI fallback 和 deterministic audit 不错；结构化模型调用、JSON schema、真实模型评测不足。 |
| QA/测试工程师 | 62 | 测试体量不小，负例也多；但 CI 质量门、外部 fixture、MCP 传输层、发布路径覆盖偏弱。 |
| SRE/可靠性工程师 | 61 | 适合单机本地运行，抗崩溃、抗并发、长档案性能还不够生产级。 |
| 安全/权限/隐私工程师 | 52 | 路径逃逸、MCP 角色隔离、hidden 派生文件、外部模型外流是硬风险。 |
| 数据/评估工程师 | 56 | 已有审计和测试种子，但没有统一 metrics report 和可门禁指标。 |
| 发布/维护工程师 | 72 | 维护骨架和迁移工具不错；构建元数据、wheel/sdist、optional MCP、版本约束未收口。 |

## 最高优先级风险

### P0：路径、权限和 hidden 信息泄露

当前最需要优先治理的是安全边界。

关键证据：

- `Campaign.resolve()` 对绝对路径直接放行，database/events/cards/content 都可能借由 campaign 配置逃出 campaign root：`rpg_engine/campaign.py:75`。
- `init_database()` 会创建和写入解析后的 DB 路径，`--force` 场景下还可能删除既有路径：`rpg_engine/db.py:42`。
- MCP `query(view=...)` 直接接受调用方视图参数，Runtime 再把视图交给 render；`visibility.py` 中 `gm/maintenance` 可读 hidden：`rpg_engine/mcp_adapter.py:618`、`rpg_engine/runtime.py:1150`、`rpg_engine/visibility.py:21`。
- MCP 可通过 `start_turn(mode="maintenance")` 触发维护视图，低信任外部 Agent 不应拥有该能力。
- `cards.py` 会为所有非 archived 实体生成卡片，hidden 实体也可能被派生到文件；存档导出包含 `cards/memory`：`rpg_engine/cards.py:46`、`rpg_engine/save_archive.py:25`。
- MCP 每次调用可启用 `semantic_ai/state_audit_ai/archivist_ai`，prompt 可能包含玩家文本、实体命中、delta 和事件；外部模型调用边界缺少服务器级硬性配置封顶：`rpg_engine/mcp_adapter.py:248`、`rpg_engine/ai/provider.py:74`。

推荐改进方向：

1. 将 campaign/package/save 的所有路径解析统一改为 root-contained resolver，默认拒绝绝对路径、`..`、symlink escape 和 home expansion。
2. 对 `database`、`events`、`cards`、`content_paths`、package migration path 使用同一套 `ensure_under_root`。
3. MCP 引入明确 profile：`player`、`trusted_gm`、`maintenance`、`admin`。默认 profile 只能读 player view，不能切换 `view=gm/maintenance`。
4. MCP 写操作增加主体字段、权限策略、审计主体、可选人工确认 token。
5. hidden 实体不得生成默认玩家可读派生卡片；导出包区分 player export 和 full maintenance export。
6. 外部 AI helper 必须由服务器配置允许，客户端不能逐请求打开 provider/model。
7. MCP audit log 做脱敏、权限收紧和完整性保护，至少加入 per-record digest；高安全模式下加入 hash chain。

### P0：玩家表面和内核表面混合

当前玩家路径仍在暴露内部对象：delta、TurnProposal、validate、commit、entity id、path、Context Packet。这会让普通玩家和外部 Agent 都被迫理解内部协议。

关键证据：

- `play act "在家盘点库存"` 默认输出“结构化 delta”和 JSON：`rpg_engine/runtime.py:1313`、`tests/test_v1_cli.py:215`。
- `start-turn` 输出 AI/开发者 Context Packet，包含模板、预算、loaded/omitted、实体 ID 和后续命令说明：`rpg_engine/cli_v1.py:528`、`rpg_engine/context_builder.py:398`、`rpg_engine/context/procedure.py:14`。
- 顶层 CLI 将 `player/play` 与 save-turn/projection/package/plugin/importer 等维护命令平铺：`rpg_engine/cli.py:169`。
- 评审时 MCP 默认工具含 `preview_action`、`validate_delta`、`commit_turn`，接口参数要求调用方理解 `delta` 和 `turn_proposal`：`rpg_engine/mcp_adapter.py:30`。当前状态：默认 player profile 已改为只注册 player-safe surface，低层工具只在 low-level profile 注册。
- `--auto-confirm-low-risk` 是用户可见参数，但 Runtime 当前忽略：`rpg_engine/cli_v1.py:199`、`rpg_engine/runtime.py:1516`。

推荐改进方向：

1. 建立真正的 player-facing orchestration：`act -> GM response -> confirm/cancel`，隐藏 delta/proposal/commit。
2. 将 `preview_action/validate_delta/commit_turn` 从默认 MCP player profile 移出，放入 `developer` 或 `trusted_gm` profile。
3. `play act` 默认输出叙事反馈、风险、资源变化摘要、是否需要确认；`--json` 或 `--debug` 才输出 delta。
4. `start-turn` 默认输出玩家可读场景入口，不输出 Context Packet；Context Packet 作为 `--debug-context` 或 AI adapter 内部工具。
5. `auto-confirm-low-risk` 要么实现，要么从公开 CLI 删除。
6. 玩家可见 render 层隐藏内部 path、database、health、entity id；调试模式再展示。

### P1：保存、投影和备份的一致性不足

SQLite 主写入路径已有 `BEGIN IMMEDIATE`、rollback、外键、command_id 幂等和 expected_turn_id guard，这是优点。但文件派生物、outbox、patch、archive 的一致性还不够硬。

关键证据：

- `save_turn_delta()` 幂等重试命中后直接返回，不会补跑 outbox/finalize：`rpg_engine/save.py:49`。
- `commit_turn_delta()` 只刷新 snapshots/cards，且成功语义偏乐观：`rpg_engine/commit_service.py:124`。
- `save_patch` 直接改实体，只刷新 search/snapshots/cards，不写 turn/event/outbox，也不标 memory/reports dirty：`rpg_engine/save_patch.py:229`。
- projection 写文件缺少 atomic replace 和 fsync，快照直接 `write_text`，cards 先删后写，events JSONL 直接重写：`rpg_engine/render.py:1023`、`rpg_engine/cards.py:43`、`rpg_engine/projections.py:232`。
- `finalize_artifacts()` 在 DB commit 后运行，SQLite 锁不覆盖投影文件/outbox 文件操作：`rpg_engine/unit_of_work.py:90`。
- backup/restore 是逐文件 copy，restore 先删除 cards，失败可能污染当前存档：`rpg_engine/backup.py:94`。
- archive export 直接打包 live `game.sqlite`，import `force=True` 不先清空目标，也不是 temp dir 原子替换：`rpg_engine/save_archive.py:70`、`rpg_engine/save_archive.py:92`。

推荐改进方向：

1. 所有派生文件写入使用 `write temp -> fsync file -> rename -> fsync dir`。
2. cards/snapshots/memory/reports/events 全部纳入 projection/outbox 成功语义，而不仅是 events JSONL。
3. idempotent retry 命中时检查 projection/outbox 状态，必要时自动补跑 repair。
4. `save_patch` 改成 maintenance transaction：写 non-story event、标所有受影响 projection dirty、可选生成 patch audit turn。
5. archive export 使用 SQLite backup API 生成一致性快照后打包。
6. archive import 先解压到临时目录，校验通过后原子替换目标；`force=True` 必须避免旧文件残留。
7. 长档案场景中避免每回合全量 FTS rebuild 和 events JSONL 全文件读去重。

### P1：架构 owner 仍集中

当前架构已经从脚本式实现进化出 Runtime、ValidationPipeline、ActionResolverSpec、ContentTypeSpec、ProjectionService、SaveManager 等结构。但多个核心文件仍承担过多职责，扩展时需要改核心。

关键证据：

- `GMRuntime` 同时承担防注入、自然语言行动推断、实体匹配 SQL、UX 文案、delta option 反推：`rpg_engine/runtime.py:500`、`rpg_engine/runtime.py:710`、`rpg_engine/runtime.py:1740`。
- 顶层 `cli.py` 同时承载 V1、legacy、admin、plugin、importer、package、migration、backup 等入口：`rpg_engine/cli.py:169`、`rpg_engine/cli.py:625`。
- action 默认 registry 逐个 import 内置 resolver，插件动态加载未实现：`rpg_engine/actions/registry.py:15`、`rpg_engine/admin/plugins.py:126`。
- `ProjectionService` 用 central string switch 写 snapshots/cards/memory/audit/package_lock：`rpg_engine/projection_service.py:281`。
- `preview.py` 名为预览，实际承载大量 action 规则、解析、delta 构造，actions 又反向依赖 preview helper：`rpg_engine/actions/travel.py:10`、`rpg_engine/actions/gather.py:14`。
- `render.py` 内置 ID 前缀、标签、内容域词表和按实体类型拼行动建议：`rpg_engine/render.py:25`、`rpg_engine/render.py:862`。

推荐改进方向：

1. 将 Runtime 收缩成 orchestration facade；intent、action resolve、proposal、validation、render 分别成为独立 owner。
2. 将 CLI 拆成 `player_cli.py`、`maintenance_cli.py`、`package_cli.py`、`admin_cli.py`，顶层只做子命令装配。
3. 将 preview 中的 action 规则迁到各 action resolver；preview 只负责呈现 `ActionResolution`。
4. projection 改成 registry：每个 projection 提供 name、version、dependencies、write_atomic、validate、repair。
5. render/card/content presentation 改成按 content type 注册 adapter，避免新类型继续修改核心 render。
6. plugin 动态加载先限定为声明式扩展，逐步开放 Python 扩展。

### P1：测试、CI 和发布质量门不完整

测试数量不少，负例质量也不错。但关键问题是：默认质量门没有强制覆盖最重要的回归、真实安装包路径和 MCP 传输层。

关键证据：

- 本地 `pytest` 通过，但 77 skipped。
- 多个测试依赖仓库外 `../rp/isekai-farm-v2`，干净环境会跳过：`tests/test_context_quality.py:43`、`tests/test_upgrade_v2.py:31`、`tests/test_content_registry.py:15`。
- 原评审发现 `tests/regression.py` 默认不会被 pytest 命名规则收集，需显式运行；R4 修补后应命名为 `tests/test_regression.py` 并进入默认收集。
- MCP `mcp` 是 optional 依赖，CI 主要直调 `AIGMMCPAdapter`，没有充分验证 stdio server 合约：`rpg_engine/mcp_adapter.py:518`。
- CI 未强制 ruff/coverage；当前环境也缺 ruff/coverage 包。
- 大多数 CLI 测试跑源码树 `python -m rpg_engine`，不是安装后的 console script。
- `aigm_kernel.egg-info/SOURCES.txt` 陈旧，只列到旧迁移资源，而当前已有 `0004/0005`：`aigm_kernel.egg-info/SOURCES.txt:158`。

推荐改进方向：

1. 将 `tests/regression.py` 重命名为 `tests/test_regression.py`，确保默认收集。
2. 将外部 campaign fixture 最小化后纳入 repo，或者把依赖外部 fixture 的测试从强回归门中分离并明确标记。
3. 增加 `.[dev]` extra，声明 ruff、coverage、build、twine、pytest 等开发依赖。
4. CI 增加 `ruff check`、coverage threshold、wheel/sdist build、`pip install dist/*.whl` 后跑 CLI smoke。
5. CI 增加 `pip install .[mcp]` 和 MCP stdio server contract test。
6. 清理或重新生成 egg-info，发布前验证 package data 包含 migrations/examples/prompts/schema。
7. Python 版本策略收口：要么测试 3.13，要么设置 `<3.13` 上界。

### P2：AI/ML、提示词和评估体系仍未 metrics 化

AI 默认关闭、No-AI fallback 可运行，这是重要优点。State Auditor 对“叙事说获得/消耗但结构化状态没写”有实际阻断能力。但当前还不是 ML-grade 的结构化调用与评估体系。

关键证据：

- 模型调用是 `hermes -z <prompt>` 子进程字符串调用，没有 SDK 级 system/user 分层、response_format 或工具调用约束：`rpg_engine/ai/provider.py:74`。
- fenced JSON 用非贪婪 `{.*?}`，嵌套对象可能解析失败：`rpg_engine/ai/provider.py:234`。
- 自研 schema 校验只覆盖部分 JSON Schema：`rpg_engine/ai/schema_validation.py:19`。
- `validate_delta` 不跑 deterministic state audit，提交时才默认跑，低信任 Agent 可能误以为 validate OK 就可保存：`rpg_engine/runtime.py:1526`、`rpg_engine/runtime.py:1585`。
- 所谓 semantic retrieval 主要是 SQLite LIKE/FTS/别名关键词检索，不是 embedding/vector semantic retrieval：`rpg_engine/context/resolution.py:345`、`rpg_engine/memory.py:320`。
- intent gold set 是逐条硬断言，没有 pass rate、混淆矩阵、分桶指标：`tests/test_runtime.py:612`。
- context audit 有 loaded/omitted，但没有和标注期望计算 precision/recall：`rpg_engine/context_audit.py:13`。

推荐改进方向：

1. 将 AI provider 抽象升级为结构化消息接口，区分 system/developer/user/context。
2. 支持 provider-native structured output 或 JSON schema response format；本地 fallback 再做严格 parser。
3. 使用成熟 JSON Schema validator，覆盖 nested object、min/max、oneOf、pattern 等。
4. `validate_delta` 可选运行 deterministic state audit，并在报告中清晰区分“schema ok”和“commit-safe”。
5. 建立 intent eval report：accuracy、macro-F1、混淆矩阵、语言/动作类型分桶。
6. 建立 retrieval eval report：precision@k、recall@k、must-load/must-hide、budget stability。
7. 建立 state consistency eval：block rate、false positive、false negative、commit success/failure reason。
8. 保留 No-AI gold set，同时增加真实模型/对抗 prompt/嵌套 JSON/幻觉压力测试。

## 分角色详细意见与整改方向

### 产品经理：78/100

判断：核心用户价值已经能跑通，但玩家闭环仍不够顺。系统有 create/continue/query/natural preview/validate/commit/health，SaveManager onboarding 也不错；问题是“开始游戏”和“执行行动”之间没有形成自然、连续、低概念负担的体验。

主要问题：

- `player start` 可以创建/继续，但 `play act/query/commit` 仍要求用户理解和传入 `campaign_dir`，active save 概念未贯穿。
- 评审时 MCP 默认暴露 `preview_action`，而 surface inventory 已将其标成非普通游玩面；当前已移入 low-level profile。
- `validate_delta.ok=true` 不等于可提交，容易误导 AI 和用户。
- 输出中出现 delta/tool/commit 等开发者概念。
- 安全词和越权词识别会误伤正常世界内表达，例如“隐藏线索”“数据库”。

整改方向：

- 产品入口收敛为 `player start`、`player act`、`player confirm`、`player query`。
- 将 active save/campaign 上下文持久化到 SaveManager registry，后续命令默认使用当前会话。
- 将 validate/commit 从普通用户路径降级为内部步骤。
- 输出改为 GM 叙事和确认卡片，不展示 delta JSON。
- 将安全词判断上下文化，避免普通故事表达被误判为越权。

### UX/交互设计师：64/100

判断：内核能力强于交互层。玩家看到的是“数据库写入预演”，不是“GM 回合反馈”。

主要问题：

- `play act` 默认返回结构化 delta 和 JSON。
- `start-turn` 输出 Context Packet，而不是场景入口。
- 顶层 CLI 将玩家命令和维护命令混排。
- MCP 的普通行动路径要求理解 delta/turn_proposal。
- 玩家可见输出暴露 loc/item id、save_dir、database、health 等。
- `--auto-confirm-low-risk` 可见但无效。

整改方向：

- 增加 `PlayerResponse` 层，字段包括 `narration`、`state_changes_summary`、`risk`、`needs_confirmation`、`choices`。
- CLI 默认只渲染玩家响应，`--debug-json` 才输出内部结构。
- 帮助信息按人群拆分：player 默认，maintenance/admin 单独入口。
- 对 icon/短命令不适用的 CLI 场景，至少用清晰命令组和自然文案降低概念负担。

### 游戏设计师/内容作者：76/100

判断：内容治理意识强，尤其是 palette/discovery、proposal、state audit 对低幻觉 RPG 很有价值。但长期创作和多题材扩展会遇到硬编码边界。

主要问题：

- action 集合由 Python 固定注册，作者难以数据化新增“占卜、调查、仪式、经营”等玩法。
- 部分 resolver/context 泄漏示例世界设定，例如“弩/矛/刀”“蘑菇/孢子”“竹水筒/南瓜”等。
- random table 有 audit delta 文本，但 runtime API 未真正交出可提交 delta。
- clock 作为计数器可用，作为规则系统偏弱，tick 条件多写死在 preview。
- content smoke 测试更多验证“能跑”，较少验证长期叙事质量和规则语义。

整改方向：

- 引入声明式 action spec：参数、目标解析、风险、clock tick、delta template、验证约束。
- 将世界特定词汇迁到 campaign content 或 locale pack。
- 补齐 random table resolver，使其返回可提交 TurnProposal/delta。
- clock 增加规则条件、触发效果、可测试断言。
- author kit 增加 narrative quality smoke：hidden 不泄露、clock 触发正确、palette 不越权实体化。

### 软件架构师：72/100

判断：架构方向正确，但还不是干净插件化内核。Runtime/CLI/preview/render/projection 的中央化 owner 是主要维护风险。

主要问题：

- GMRuntime 不是纯 facade。
- CLI 过大，V1、legacy、admin、maintenance 共存。
- registry 有接口，但默认扩展仍靠核心硬编码。
- ProjectionService 是中央 string switch。
- preview.py 承载 action 领域规则并被 actions 反向依赖。
- render.py 内置大量内容类型知识。

整改方向：

- Runtime 只负责 orchestration，禁止新增领域规则。
- action resolver 成为唯一 action 规则 owner。
- projection、content presentation、card renderer 全部 registry 化。
- legacy/admin 与 V1 player runtime 做包级隔离。
- 对 `preview.py`、`cli.py`、`runtime.py` 制定拆分计划和新增代码禁入规则。

### 后端/内核工程师：72/100

判断：核心写入骨架不错，但可靠性 contract 还没完全硬化。

主要问题：

- commit/outbox 成功语义偏乐观。
- write guard 不是所有写路径的强制契约。
- `next_turn_id()` 在 `BEGIN IMMEDIATE` 前计算，存在并发空洞。
- save_patch 影响 projection 状态但不完整标脏。
- SQLite schema 约束偏弱，负数等不变量靠提交后检查。
- 主写路径会随长档案线性退化。
- archive 导入导出不是原子安全路径。

整改方向：

- 所有 story/maintenance write path 都必须经过统一 write contract。
- turn id 分配移入写锁事务。
- DB schema 增加关键 CHECK、json_valid、非负数量等约束。
- changed ids 贯穿到 projection refresh，减少全量重建。
- archive/backup 统一 snapshot 和 atomic import 策略。

### AI Agent 工程师：70/100

判断：外部 Agent 防线已有雏形，但默认 MCP 面不能视为低信任安全。

主要问题：

- 默认 MCP 可读 maintenance/GM hidden 信息。
- `commit_turn` 可由客户端同步篡改 delta + proposal，再关闭 state_audit 来绕过一致性审计。
- `validate_delta.ok=true` 容易误导 Agent workflow。
- 已处理：`preview_action` 不再默认注册到 player profile，与 surface inventory 的 normal_play=false 一致。
- 外部 AI helper 可逐调用启用，而不是服务器配置硬封顶。

整改方向：

- MCP profile 默认低信任，只保留 `start_or_continue/player_turn/player_confirm`，`player_query/player_act` 仅作为结构化或兼容入口。
- `TurnProposal` 增加 server-side nonce/session binding，避免客户端随意伪造 proposal。
- `state_audit=False` 只允许 trusted profile。
- validate report 增加 `commit_safe=false` 等强语义字段。
- 所有 AI helper 由 server policy 控制。

### AI/ML 与提示词工程师：74/100

判断：No-AI fallback 做得好，AI 是辅助而不是唯一链路。但结构化调用和评估还不够专业化。

主要问题：

- `hermes -z` prompt 调用没有消息分层或 response_format。
- JSON parser/schema validator 偏弱。
- semantic retrieval 不是真正向量语义检索。
- legacy semantic_ai 已退权为 trace-only；主要剩余风险转移到 intent consensus 候选质量、helper prompt injection 与默认开启前的 eval 覆盖。
- eval 偏工程回归，缺少真实模型和对抗测试。

整改方向：

- provider 抽象改成 structured chat/message API。
- 支持 provider-native JSON schema 或工具调用。
- 增加 prompt injection eval、schema robustness eval、semantic routing eval。
- semantic helper 只能建议，最终 route/resolve/commit 继续由 deterministic contract 决定。

### QA/测试工程师：62/100

判断：测试基础不薄，但发布级防回归中等偏弱。

主要问题：

- 大量回归依赖仓库外 fixture。
- 原 `tests/regression.py` 默认不被收集，R4 修补要求改为 `tests/test_regression.py`。
- MCP 真实传输层未进 CI。
- CLI 测试主要跑源码树，不是安装后 console script。
- CI 没有 coverage/ruff 门禁。
- 测试本身有工作区副作用，如清理源码目录下 `__pycache__`。

整改方向：

- 默认测试收集必须包含 regression。
- repo 内置最小真实 campaign fixture。
- 加 installed-package smoke test。
- 加 MCP stdio server test。
- 加 lint/coverage/dev dependency。
- 对测试副作用做隔离，所有临时写入必须在 temp dir。

### SRE/可靠性工程师：61/100

判断：适合本地单用户，但不是抗崩溃、抗并发、长档案稳定运行的生产级可靠引擎。

主要问题：

- 投影文件写入非原子。
- 备份/恢复非事务化。
- SQLite 锁不覆盖提交后文件操作。
- outbox 覆盖面窄、无退避和 dead-letter。
- 日志和观测性不足，MCP audit 失败 best effort。
- 长档案性能线性退化。

整改方向：

- 文件写入原子化。
- projection/outbox 统一失败重试策略。
- 增加 lock file 或 per-save process lock，覆盖 DB + artifacts。
- 增加 structured logging、trace id、metrics emission。
- 增加 long-run benchmark 和性能阈值。

### 安全/权限/隐私工程师：52/100

判断：当前代码适合作为本地可信单机引擎原型，但不能作为可靠 MCP/权限/隐私隔离边界。

主要问题：

- campaign path 逃逸。
- MCP 无角色/授权隔离。
- MCP 写工具面较大，无认证、主体审计和人工确认凭证。
- hidden 派生文件泄露。
- 外部模型外流控制不足。
- package/archive 有 zip bomb、绝对路径、全量内存读取等攻击面。
- audit log 可能记录敏感文本，无脱敏和防篡改。

整改方向：

- P0 先封 path containment 和 MCP role。
- hidden 数据派生物默认不落玩家可读文件。
- archive/package 加大小、文件数、压缩比限制。
- external AI egress 加显式 policy 和 redaction。
- audit log 加最小化、脱敏、权限和完整性。

### 数据/评估工程师：56/100

判断：当前是“可观测但未量化”。已有数据种子，但没有形成可报告、可比较、可门禁的评估体系。

主要问题：

- `ValidationReport` 只汇总 ok/status/errors/warnings，没有 accuracy、consistency rate、block rate。
- intent gold set 不输出 pass rate、混淆矩阵、分桶指标。
- context audit 记录 loaded/omitted，但不计算 precision/recall。
- 真实 context accuracy matrix 依赖本地外部 campaign。
- projection/card 数据质量校验偏浅。
- performance baseline 没有硬阈值。
- 内容质量评估是启发式 finding 计数，没有质量分和趋势。

整改方向：

- 增加 `rpg_engine eval` 命令，输出 JSON/Markdown metrics report。
- intent/retrieval/state/projection/content 各自建立指标。
- 建立 repo 自包含 eval dataset。
- CI 加关键指标阈值，允许 baseline update 但必须显式审阅。
- projection/card 加字段完整性和 DB/Markdown 一致性抽检。

### 发布/维护工程师：72/100

判断：维护骨架不错，但可发布性还没完全收口。

主要问题：

- egg-info/SOURCES 陈旧，可能漏包迁移资源。
- CI 未覆盖 wheel/sdist、`.[mcp]`、twine/check、包内容验证。
- 公共 CLI 面过宽。
- 版本/迁移兼容约束偏软，engine_version 只要求非空字符串。
- pyproject 缺 license、authors、urls、classifiers 等发布元数据。
- 大型集中模块和 `import *` wrapper 有维护漂移风险。

整改方向：

- 增加发布前 `python -m build`、`twine check`、wheel install smoke。
- 删除或自动生成 egg-info，不把陈旧构建产物当事实。
- package data 加测试，确保 resources/migrations/examples/prompts/schemas 全入包。
- 明确 semver 和 engine_version 兼容矩阵。
- 公共 CLI 默认只暴露 player，维护命令单独 profile 或二级入口。

## 推荐实施路线图

### Phase A：安全止血

目标：让默认本地和 MCP 使用不再有明显越权/泄露/路径逃逸。

任务：

1. 统一 root-contained path resolver。
2. campaign/package/save/archive 全路径接入 resolver。
3. MCP 默认 profile 降权为 player。
4. 禁止 player profile 使用 `view=gm/maintenance`、`state_audit=False`、外部 AI 开关。
5. hidden entity card/export 分离。
6. archive/package 加文件数、大小、压缩比限制。

验收：

- 恶意 campaign 绝对路径、`..`、symlink escape 全部被拒绝。
- 默认 MCP 无法读 hidden。
- 默认 MCP 无法关闭 state audit。
- player export 不包含 hidden cards/memory。

### Phase B：玩家闭环

目标：普通玩家不再接触 delta/proposal/commit 概念。

任务：

1. 增加 PlayerResponse/PlayerActionSession。
2. `player act` 只输出叙事、摘要、风险和确认选项。
3. `player confirm` 内部完成 validate + commit。
4. `preview_action/validate_delta/commit_turn` 移入 developer/trusted profile。
5. `start-turn` 默认输出玩家场景入口。

验收：

- 玩家 happy path 只需要 `start -> act -> confirm/query`。
- 默认输出不出现 delta JSON、Context Packet、database path。
- CLI 和 MCP transcript 都覆盖自然语言玩家路径。

### Phase C：可靠保存内核

目标：崩溃、重试、导入导出和投影失败时可恢复且语义清晰。

任务：

1. 所有 projection/artifact 原子写入。
2. outbox 覆盖 snapshots/cards/memory/reports/events。
3. idempotent retry 自动补 repair。
4. save_patch 事件化和 projection dirty 完整化。
5. archive import/export 使用 snapshot + temp dir + atomic replace。
6. 长档案增量 projection 和 events index 优化。

验收：

- 故障注入测试覆盖投影半写、backup/restore 中断、archive import 中断。
- commit ok 不再掩盖 requested/global projection 失败。
- 长档案 benchmark 有稳定阈值。

### Phase D：质量门与发布链

目标：任何人拉取仓库后可以复现质量门，发布包内容可信。

任务：

1. `tests/test_regression.py` 纳入默认收集。
2. repo 自包含真实 campaign/eval fixture。
3. 增加 dev extra：ruff、coverage、build、twine、pytest。
4. CI 增加 lint、coverage、MCP stdio、wheel install、sdist/wheel content check。
5. 清理 egg-info，发布产物由 build 生成。
6. pyproject 补齐元数据和 Python 版本策略。

验收：

- 干净环境 CI 不再大量跳过核心回归。
- `pip install dist/*.whl` 后 CLI/MCP smoke 通过。
- ruff/coverage 结果可复现。

### Phase E：评估与 ML-grade 工具链

目标：从“有测试”升级为“有指标、有趋势、有门禁”。

任务：

1. 增加 `rpg_engine eval`。
2. intent eval 输出 accuracy、macro-F1、confusion matrix。
3. retrieval eval 输出 precision@k、recall@k、must-hide leak rate。
4. state audit eval 输出 block rate、false positive、false negative。
5. content quality eval 输出质量分和趋势。
6. AI provider 升级到 structured message/output contract。

验收：

- 每次 CI 有 machine-readable metrics report。
- 指标下降会阻断合并或需要显式 baseline update。
- 真实模型和 No-AI 两套路径都有评估。

## 建议的修复顺序

1. 先修安全：path containment、MCP profile、hidden 派生文件、外部 AI egress。
2. 再修玩家闭环：隐藏 delta/proposal/commit，建立 player response。
3. 再修可靠性：atomic artifact、outbox 覆盖面、save_patch 事件化、archive 原子导入导出。
4. 再修质量门：regression 默认收集、dev extra、ruff/coverage、MCP stdio、wheel/sdist。
5. 最后做架构抽象和 metrics 化，避免在边界未封口时先大重构。

## 最终判断

当前 RPG Engine 的基础是好的：它不是玩具脚本，已经有内核、验证、proposal、projection、package、authoring、MCP 和测试体系。但如果目标是“可给低信任外部 Agent 使用的 RPG 引擎”，现在最不能忽视的是安全边界和玩家表面。

把路径、权限、hidden、外部 AI 开关封住，再把普通玩家路径从 delta/commit 里解放出来，这两个动作会让整体成熟度从 67 分显著抬升。随后再做可靠性和质量门，才适合进入更大范围的内容创作和发布维护。

## 对照原设计文档后的路线图修订

对照对象：

- 原设计文档：[`turn-flow-architecture.md`](turn-flow-architecture.md)
- 当前代码评审：本文档

本节记录 12 个专家在同时阅读两份文档后的共同判断和修补计划。它的作用不是推翻原设计，而是把原设计中的目标边界、阶段门槛和当前代码现实重新对齐，避免把“阶段性架构成果”误读成“产品和发布成熟度已经达标”。

### 1. 对照后的总判断

专家一致认为：原设计文档的主方向是正确的，尤其是以下判断仍然成立：

- `IntentRouter -> TurnContract -> TurnProposal -> ValidationPipeline -> TurnCommitService -> ProjectionService` 这条主链路方向正确。
- No-AI baseline 必须是最低标准，AI helper 只能受控增强。
- 外部 AI/MCP 调用者必须按低信任处理。
- 普通玩家路径、developer/debug 路径、maintenance/admin 路径必须 profile 化。
- 事实提交和 projection 刷新应该分离表达，projection failure 不应伪装成事实提交失败。
- 测试、metrics、release、rollback、repair 必须贯穿每个阶段。

但专家也一致认为：原设计文档对“当前完成度”的表述偏乐观。尤其是“Phase 0-7.1 主路径和 projection hardening 已完成，可进入完整 TurnCoordinator”这类表述，只能被理解为内部架构里程碑，不能被理解为当前实现已经具备默认安全、玩家体验完整、可发布和可长期运行的成熟度。

更准确的当前状态应表述为：

> 当前实现已经完成多项关键内部合同和投影状态语义，但默认使用面、权限边界、玩家闭环、文件级可靠性、质量门和发布链仍未达到原设计验收标准。进入完整 `TurnCoordinator` 之前，必须先完成安全/profile、玩家表面、可靠保存和质量门修补。

### 2. 12 角色对照结论

| 角色 | 对照结论 | 对路线图的修正要求 |
|---|---|---|
| 产品经理 | 设计方向正确，但完成度口径过乐观。当前更像本地可信开发者工具链，不是可交付玩家产品。 | 暂缓完整 `TurnCoordinator`，先做安全止血、玩家闭环、可靠保存和质量门。 |
| UX/交互设计师 | 原设计追求状态可追踪，但当前玩家看到的是 delta、Context Packet、ID、commit 流程。 | 验收从“内部 report 完整”升级为“默认输出玩家可理解”。 |
| 游戏设计师/内容作者 | 内容治理理念匹配，但玩法规则和 authoring 数据化不足。 | 补声明式 action/clock/random table/locale pack，减少核心硬编码。 |
| 软件架构师 | 两文档不冲突，是目标边界与实现偏差的关系。 | 进入 Coordinator 前先给 Runtime/CLI/preview/render/projection owner 设硬边界。 |
| 后端/内核工程师 | profile、ValidationPipeline、CommitService、ProjectionService 方向正确，但强制性不足。 | profile 必须变成权限和一致性策略，不只是报告标签。 |
| AI Agent 工程师 | 原设计默认低信任 workflow 正确，但当前 MCP 暴露面未兑现。 | 默认 MCP 只留 player workflow；低层工具移入 developer/trusted profile。 |
| AI/ML 与提示词工程师 | 原设计理念匹配 ML-grade 缺口，但指标和 provider 仍不够硬。 | 将 structured provider、semantic parity、prompt/tool transcript 防漂移前置。 |
| QA/测试工程师 | 原设计有测试矩阵，但粒度不足以成为 CI 门禁。 | 先建可复现环境、默认收集、ruff/coverage、MCP stdio、wheel/sdist gates。 |
| SRE/可靠性工程师 | Phase 7.1 解决了 projection 状态语义，不等于解决崩溃一致性。 | atomic write、backup/archive 原子化、outbox 全覆盖应列为发布前阻断项。 |
| 安全/权限/隐私工程师 | 风险模型一致，但当前实现存在 P0 安全缺口。 | path containment、MCP role、hidden 派生物、AI egress policy 必须前置。 |
| 数据/评估工程师 | 原设计指标名称正确，但当前仍是可观测未量化。 | 先落 `rpg_engine eval`、No-AI accuracy、block rate、latency baseline。 |
| 发布/维护工程师 | 原设计偏架构发布门槛，评审补齐了 Python 包发布链细节。 | 先做 alpha 质量门：wheel/sdist、`.[mcp]`、package data、版本兼容矩阵。 |

### 3. 路线修订原则

#### 3.1 设计文档是目标，不是当前成熟度证明

原设计文档应继续作为目标架构依据，但凡涉及“已完成”的表述，都必须由当前代码评审和质量门验证支撑。不能只因为某个类、报告字段或测试存在，就认为对应阶段的产品目标已经完成。

#### 3.2 profile 必须从分类标签升级为强制 contract

`player`、`trusted_gm`、`developer`、`maintenance`、`admin` 不应只是 report/profile 字段，而应决定：

- 能调用哪些 MCP/CLI 工具。
- 能读取哪些 visibility view。
- 能否关闭 state audit。
- 能否启用外部 AI helper。
- 能否导入、导出、patch、repair、migration。
- 提交时必须满足哪些 validation stage。
- 失败时返回何种 report 和 audit record。

#### 3.3 状态可追踪不等于玩家可理解

`TurnProposal`、`ValidationReport`、`CommitResult`、`ProjectionReport` 是内部可追踪的基础，但默认玩家输出必须隐藏这些协议细节。玩家需要看到的是：

- 系统理解了什么。
- 这是否会改变世界状态。
- 有哪些风险和资源变化。
- 是否需要确认。
- 是否已经保存。
- 派生产物是否失败，是否需要重试或修复。

#### 3.4 Projection hardening 不能替代文件级可靠性

Phase 7.1 的 projection status、requested/global scope、stale repair 是必要成果，但仍不能替代：

- artifact 原子写入。
- fsync 和 rename 语义。
- backup/restore 原子性。
- archive import/export 一致性快照。
- outbox 全覆盖。
- retry/dead-letter。
- 长档案性能预算。

#### 3.5 质量门必须可机械执行

“有测试矩阵”不等于质量门闭合。质量门必须能在干净环境中自动执行，且有明确失败条件：

- 默认 pytest 是否收集全部强回归。
- 核心 skipped 是否为 0，或是否有显式豁免清单。
- ruff/coverage 是否可复现。
- MCP stdio 是否真实跑通。
- wheel/sdist 是否可构建、可安装、内容完整。
- metrics 是否输出 machine-readable report。

### 4. 修补计划总览

修补计划分为 8 个阶段。除非特别说明，阶段之间按顺序推进。R1 和 R2 可并行一部分，但 R1 的安全门禁必须先于任何低信任 MCP/外部 Agent 扩大使用。

| 阶段 | 名称 | 目标 | 进入下一阶段的硬门槛 |
|---|---|---|---|
| R0 | 文档和完成度口径校准 | 修正路线图语义，避免把目标当现状 | 设计文档标清“架构里程碑”和“产品成熟度”差异 |
| R1 | 安全/profile 止血 | 默认使用面不能越权、读 hidden 或逃出 root | path、MCP role、hidden、AI egress blocker 测试通过 |
| R2 | 玩家/MCP 默认工作流收敛 | 默认玩家不接触 delta/proposal/validate/commit | `start -> act -> confirm/query` CLI/MCP golden transcript 通过 |
| R3 | 写入、投影、备份可靠性 | 崩溃、重试、导入导出可恢复 | atomic write、archive/backup、outbox、repair 故障注入通过 |
| R4 | 质量门和发布链 | 干净环境可复现测试和包发布链 | pytest/ruff/coverage/MCP stdio/wheel/sdist gates 通过 |
| R5 | 指标和 ML-grade 评估 | 从测试通过升级为指标可比较 | `rpg_engine eval` 输出稳定 metrics report |
| R6 | owner 拆分和 Coordinator 前置门槛 | 防止 Coordinator 包进现有复杂度 | Runtime/CLI/preview/render/projection 禁入规则和拆分完成 |
| R7 | Authoring 和规则数据化 | 支撑长期多题材创作 | action/clock/random table/locale pack 声明式基线可用 |

### 5. R0：文档和完成度口径校准

目标：让原设计文档、当前代码评审和后续开发计划使用同一套完成度语言。

范围：

- 修改文档叙述，不改变运行时代码。
- 明确“已完成内部架构里程碑”和“已达到产品/发布成熟度”是两种不同状态。
- 将本文档作为后续代码 review 的现实基线。

非目标：

- 不调整功能行为。
- 不做代码重构。
- 不改变原设计的目标架构方向。

任务：

1. 在原设计文档中增加“当前代码评审校准”小节，链接本文档。
2. 将“Phase 0-7.1 主路径完成”的描述改成“内部合同和投影状态语义阶段性完成”。
3. 明确写出：完整 `TurnCoordinator` 之前必须先完成 R1-R4。
4. 将“profile 化”重新定义为强制权限和一致性策略，而不只是报告字段。
5. 将“Projection hardening”限定为状态语义，不覆盖 atomic file write、archive/backup、outbox 全覆盖。

验收：

- 文档不再暗示当前实现已经可低信任外部 Agent 默认安全使用。
- 文档明确写出进入完整 Coordinator 的前置门槛。
- 后续 issue/PR 能按 R1-R7 分类。

### 6. R1：安全/profile 止血

目标：默认运行和默认 MCP profile 不再存在路径逃逸、hidden 泄露、maintenance 越权和外部 AI egress 失控。

范围：

- campaign/package/save/archive 路径解析。
- MCP profile 和默认 tool surface。
- visibility view 访问控制。
- hidden 派生文件和导出。
- 外部 AI helper policy。
- archive/package 基础输入限制。

非目标：

- 不实现完整认证系统。
- 不开放多租户权限模型。
- 不重写所有 CLI。
- 不引入网络服务级 RBAC。

任务：

1. 新增统一 root-contained path resolver。
   - 默认拒绝绝对路径。
   - 拒绝 `..`、home expansion 和 symlink escape。
   - 应用于 campaign `database/events/cards/content`、package `content_paths/migration_entry_path`、save/archive import/export 目标。

2. MCP 增加强制 profile。
   - 默认 profile 为 `player`。
   - `player` 禁止 `view=gm/maintenance`。
   - `player` 禁止 `start_turn(mode="maintenance")`。
   - `player` 禁止关闭 `state_audit`。
   - `developer/trusted_gm/maintenance/admin` 才能访问低层或维护能力。

3. 收紧默认 MCP tool surface。
   - 默认只保留 player workflow、只读 player query、受控 save start/continue。
   - `preview_action/validate_delta/commit_turn` 移入 developer/trusted profile。
   - 过渡期如保留，必须 profile-gated，并在 audit 中记录 low-level tool use。

4. hidden 派生物隔离。
   - hidden entity 默认不生成玩家可读 card。
   - player export 不包含 hidden cards/memory/reports。
   - full maintenance export 必须显式 profile。

5. 外部 AI egress 由服务端 policy 控制。
   - 客户端不能逐请求开启 `semantic_ai/state_audit_ai/archivist_ai`。
   - provider/model/profile 由配置决定。
   - audit 中记录是否发生外部 egress，但不得泄露敏感内容。

6. archive/package 输入限制。
   - zip 文件数上限。
   - 单文件大小上限。
   - 总解压大小上限。
   - 压缩比限制。
   - 逐项 streaming 校验，避免 `archive.read()` 无限制全量进内存。

建议测试：

- `tests/test_security_paths.py`
- `tests/test_mcp_profiles.py`
- `tests/test_hidden_visibility.py`
- `tests/test_ai_egress_policy.py`
- `tests/test_archive_safety.py`

验收：

- 恶意 campaign/package 绝对路径和 escape path 全部失败。
- 默认 MCP 无法读取 hidden。
- 默认 MCP 无法调用 maintenance mode。
- 默认 MCP 无法关闭 state audit。
- 默认 MCP 无法逐请求打开外部 AI helper。
- player export 不包含 hidden 派生物。

### 7. R2：玩家/MCP 默认工作流收敛

目标：默认玩家和默认外部 Agent 不再接触 delta、TurnProposal、validate、commit 这些内部协议。

范围：

- CLI player path。
- MCP player workflow。
- Runtime player-facing response。
- 默认输出格式。
- golden transcript。

非目标：

- 不删除 developer/debug 低层工具。
- 不取消 TurnProposal、ValidationPipeline、CommitService。
- 不重写所有 action resolver。

任务：

1. 新增 player-facing session/response 抽象。
   - `PlayerActionSession` 或等价对象记录本次待确认行动。
   - `PlayerResponse` 包含 narration、理解结果、变化摘要、风险、确认状态、下一步。
   - 内部仍可持有 `TurnProposal`，但默认不展示。

2. CLI 默认链路改为：
   - `player start`
   - `player act "<natural text>"`
   - `player confirm`
   - `player query`

3. MCP 默认链路改为：
   - `player_start`
   - `player_query`
   - `player_act`
   - `player_confirm`

4. `player act` 内部可以调用 preview、proposal、validate preview profile，但输出只显示玩家语义。

5. `player confirm` 内部完成 validation + state audit + commit + projection status report。

6. 默认输出禁止出现：
   - delta JSON。
   - raw `TurnProposal`。
   - `Context Packet`。
   - database path。
   - save_dir。
   - internal health dict。
   - 非必要 entity id。

7. `--debug-json` 或 developer profile 可显示内部结构。

建议测试：

- `tests/test_player_workflow.py`
- `tests/test_player_output_golden.py`
- `tests/test_mcp_player_transcript.py`
- `tests/test_low_level_tools_profile_gate.py`

验收：

- 默认玩家 happy path 为 `start -> act -> confirm/query`。
- 默认 CLI/MCP transcript 不出现 delta/proposal/validate/commit 概念。
- 确认后输出明确区分：已保存、未保存、投影失败、可重试。
- developer/debug profile 仍可访问低层诊断。

### 8. R3：写入、投影、备份可靠性

目标：事实库和派生产物在崩溃、重试、导入导出、维护 patch 下保持可恢复、一致且语义清晰。

范围：

- facts DB write contract。
- save_patch maintenance transaction。
- projection artifact write。
- outbox 覆盖面。
- backup/restore。
- archive import/export。
- idempotent retry repair。

非目标：

- 不引入异步分布式队列。
- 不支持多写者服务端集群。
- 不把 projection failure 回滚事实提交。

任务：

1. 建立 atomic artifact writer。
   - `temp -> fsync file -> rename -> fsync dir`。
   - snapshots/cards/events/memory/reports/package_lock 全部接入。

2. projection registry 化的最低实现。
   - 每个 projection 声明 name、version、artifact path、write_atomic、validate、repair。
   - `ProjectionService` 不再靠单一 string switch 扩展所有类型。

3. outbox 覆盖所有派生产物。
   - events JSONL。
   - snapshots。
   - cards。
   - memory。
   - reports。
   - package_lock。
   - retry count、last_error、dead-letter。

4. idempotent retry 补 repair。
   - `command_id` 命中既有 turn 时检查 projection/outbox。
   - 如事实已提交但 artifact 未完成，自动补跑 targeted repair 或返回明确 repair_required。

5. `save_patch` 事件化。
   - maintenance patch 写 audit/provenance event。
   - 标记所有受影响 projection dirty。
   - 需要时生成 non-story maintenance turn 或等价 audit record。

6. turn id 分配放入写锁内。

7. SQLite schema 增加强约束。
   - 关键 JSON 字段 `json_valid`。
   - quantity/segments 等非负约束。
   - 高风险 invariant 前置到写入前或 DB CHECK。

8. backup/export 使用一致性快照。
   - export 先用 SQLite backup API 生成临时 DB。
   - 再打包 artifact。

9. import/restore 原子化。
   - 解压到 temp dir。
   - 完整校验 manifest、hash、schema、size。
   - 通过后 atomic replace。
   - 失败不污染当前存档。

建议测试：

- `tests/test_atomic_artifacts.py`
- `tests/test_outbox_full_coverage.py`
- `tests/test_save_patch_audit.py`
- `tests/test_archive_atomicity.py`
- `tests/test_backup_restore_faults.py`
- `tests/test_idempotent_repair.py`

验收：

- 故障注入：snapshot/cards/events 写到一半崩溃后可 repair。
- archive import 中途失败不污染目标。
- backup restore 中途失败不删除当前可用存档。
- idempotent retry 不会返回“成功但 artifact 永久缺失”。
- `CommitResult` 明确区分 `write_status` 和 `projection_status`。

### 9. R4：质量门和发布链

目标：任何人在干净环境中都能复现测试、lint、coverage、MCP、安装包和发布包检查。

范围：

- test collection。
- fixture 可移植性。
- dev/mcp extras。
- CI。
- wheel/sdist。
- package data。
- pyproject metadata。

非目标：

- 不要求立即公开稳定发布。
- 不要求 100% coverage。
- 不要求所有外部真实 campaign 都进入 repo。

任务：

1. 建立 `.[dev]`。
   - pytest。
   - ruff。
   - coverage。
   - build。
   - twine。

2. 建立 `.[mcp]` CI 测试。

3. 默认 pytest 收集强回归。
   - 将 `tests/test_regression.py` 纳入默认收集，或配置 pytest 显式包含。
   - 核心 skipped 必须为 0，或有 `allowed_skips.yaml` 豁免清单。

4. repo 内置最小真实 fixture。
   - 用于 context accuracy、content registry、upgrade、visibility。
   - 不依赖 `../rp/isekai-farm-v2`。

5. CI gates。
   - `python -m pytest`
   - `python -m ruff check .`
   - `python -m coverage run -m pytest`
   - coverage report threshold。
   - MCP stdio smoke。
   - installed CLI smoke。

6. 发布包 gates。
   - `python -m build`
   - `twine check dist/*`
   - wheel install 后运行 CLI/MCP smoke。
   - 校验 migrations/examples/prompts/schemas/package data 全部入包。

7. pyproject 元数据。
   - license。
   - authors/maintainers。
   - project.urls。
   - classifiers。
   - Python 版本策略。
   - semver/engine_version 兼容矩阵。

验收：

- 干净环境不需要本机外部 campaign 即可跑核心质量门。
- 强回归默认被 pytest 收集。
- ruff/coverage 在 `.[dev]` 环境可用。
- MCP stdio server 被真实启动并通过 contract smoke。
- wheel/sdist 内容完整，安装后 CLI 可用。

### 10. R5：指标和 ML-grade 评估

目标：从“测试通过”升级为“指标可报告、可比较、可门禁”。

范围：

- eval command。
- No-AI baseline。
- intent metrics。
- validation/state consistency metrics。
- retrieval/context metrics。
- projection/content metrics。
- AI helper/prompt metrics。
- structured provider hardening。

非目标：

- 不要求立即接入真实线上模型。
- 不要求 embedding/vector 检索在第一步完成。
- 不允许 AI eval 绕过 deterministic gate。

任务：

1. 增加 `rpg_engine eval`。
   - 输出 JSON。
   - 输出 Markdown。
   - 支持 baseline compare。

2. No-AI intent metrics。
   - accuracy。
   - macro-F1。
   - confusion matrix。
   - clarify rate。
   - block rate。
   - silent wrong resolver rate。

3. validation/state consistency metrics。
   - schema_valid rate。
   - audit_passed rate。
   - commit_safe rate。
   - false positive/false negative 标注集。
   - commit failure reason 分布。

4. retrieval/context metrics。
   - precision@k。
   - recall@k。
   - must-load hit rate。
   - must-hide leak rate。
   - budget stability。

5. latency metrics。
   - context。
   - intent。
   - preview。
   - validate。
   - commit。
   - projection。
   - p50/p95/max。
   - 超过 baseline 20% 需要说明。

6. projection/content metrics。
   - projection failure rate。
   - repair duration。
   - dirty/stale age。
   - card/DB 一致性抽检。
   - content quality trend。

7. AI helper hardening。
   - structured message provider contract。
   - provider-native JSON schema 或 tool-call output。
   - 成熟 JSON Schema validator。
   - prompt/schema/provider/model/provenance 记录。
   - prompt injection eval。
   - schema robustness eval。

8. `validate_delta` 语义拆分。
   - `schema_valid`。
   - `resolver_valid`。
   - `audit_passed`。
   - `proposal_valid`。
   - `commit_safe`。

验收：

- CI 至少生成 No-AI eval report。
- 指标下降超过阈值会失败或要求显式 baseline update。
- semantic-on 与 No-AI 有可比较报告。
- “validate ok”不再被误读为“commit safe”。

### 11. R6：owner 拆分和 Coordinator 前置门槛

目标：进入完整 `TurnCoordinator` 前，先阻止现有 Runtime/CLI/preview/render/projection 继续扩大 owner。

范围：

- Runtime orchestration boundary。
- CLI module split。
- preview/action resolver boundary。
- render/presentation boundary。
- projection registry。
- code review 禁入规则。

非目标：

- 不一次性重写所有模块。
- 不要求立即完整 plugin system。
- 不删除 legacy/admin，只分层隔离。

任务：

1. Runtime 禁入规则。
   - `GMRuntime` 只允许 orchestration。
   - 不新增领域规则。
   - 不新增 SQL/entity matching 规则。
   - 不新增 UX 文案模板。

2. CLI 拆分。
   - `player_cli.py`
   - `maintenance_cli.py`
   - `package_cli.py`
   - `admin_cli.py`
   - 顶层 `cli.py` 只做装配。

3. preview 收窄。
   - action 规则、参数解析、delta 构造迁回 resolver。
   - `preview.py` 只呈现 `ActionResolution` 和 proposal preview。

4. render/presentation adapter。
   - 每个 content type 注册 presentation adapter。
   - card renderer 按 adapter 生成。
   - 新内容类型不修改核心 render。

5. projection registry。
   - name。
   - version。
   - dependencies。
   - artifact paths。
   - write_atomic。
   - validate。
   - repair。

6. Coordinator 前置门槛。
   - R1-R4 必须完成。
   - Runtime/CLI/preview/render/projection 禁入规则已生效。
   - player workflow 不再暴露内部协议。

验收：

- 新增 action 不需要修改 `preview.py` central branch。
- 新增 content presentation 不需要修改核心 render 大表。
- 新增 projection 不需要修改 `ProjectionService` string switch。
- 完整 Coordinator PR 中不得包含 resolver/validation/commit/projection 规则实现。

### 12. R7：Authoring 和规则数据化

目标：把长期玩法和多题材创作从 Python 核心硬编码中释放出来。

范围：

- action spec。
- clock rule。
- random table resolver。
- locale/content pack。
- author smoke quality。
- palette/discovery governance。

非目标：

- 不允许未受控 Python 插件直接进入普通 campaign。
- 不让 AI 生成内容无确认落库。
- 不牺牲 safety/profile 边界换取扩展性。

任务：

1. 声明式 action spec。
   - 参数。
   - 目标解析。
   - 风险。
   - delta template。
   - clock tick。
   - resolver contract。
   - validation constraints。

2. clock rule system。
   - tick 条件。
   - trigger effects。
   - visibility。
   - smoke assertion。

3. random table 完整 resolver。
   - kernel random audit event。
   - 可提交 delta。
   - seed/provenance。
   - validation gate。

4. locale/content pack。
   - 将“弩/矛/刀”“蘑菇/孢子”“竹水筒/南瓜”等示例世界词汇迁出核心。
   - resolver heuristic 通过 campaign/locale 注册。

5. author quality smoke。
   - hidden 不泄露。
   - palette 不越权实体化。
   - clock 触发正确。
   - random table 可提交。
   - long-run narrative consistency 抽检。

验收：

- 新增一个非示例题材 action 不需要改核心 Runtime/preview/render。
- random table preview 能生成可提交 proposal/delta。
- clock 触发语义可由 smoke test 验证。
- 示例世界词汇不再出现在通用 resolver/context 核心逻辑中。

### 13. 推荐执行顺序

严格建议按以下顺序推进：

1. R0：先校准文档和完成度口径。
2. R1：安全/profile 止血。
3. R2：玩家/MCP 默认工作流收敛。
4. R3：写入、投影、备份可靠性。
5. R4：质量门和发布链。
6. R5：指标和 ML-grade 评估。
7. R6：owner 拆分和 Coordinator 前置门槛。
8. R7：Authoring 和规则数据化。
9. 完成 R1-R6 的硬门槛后，再进入完整 `TurnCoordinator` / `plan_turn -> validate_proposal -> commit_proposal`。

原因：

- 如果先做 Coordinator，会把当前 unsafe surface、开发者化玩家体验和不完整写入可靠性包装进更大的中心。
- 如果先做 AI/semantic，会在没有安全/profile/metrics 的情况下扩大不可控面。
- 如果先做 authoring 扩展，会把硬编码问题扩散到更多内容类型。
- 如果先做发布，会把当前 P0 安全和质量门缺口固化给外部用户。

### 14. 完整 Coordinator 的进入条件

只有满足以下条件，才建议进入完整 `TurnCoordinator`：

1. 默认 MCP player profile 无法读 hidden、无法调用 maintenance、无法关闭 audit。
2. 默认玩家 workflow 为 `start -> act -> confirm/query`。
3. 默认输出不暴露 delta/proposal/Context Packet/database path。
4. 低层工具全部 profile-gated。
5. path containment 全面覆盖 campaign/package/save/archive。
6. hidden 派生文件和 export 隔离完成。
7. projection/artifact atomic write 完成。
8. archive/backup/import/restore 具备一致性快照和失败不污染保证。
9. 强回归默认收集，核心 skipped 有豁免清单。
10. ruff/coverage/MCP stdio/wheel/sdist 质量门可运行。
11. 至少有 No-AI intent metrics 和 validation/state consistency metrics。
12. Runtime/CLI/preview/render/projection 新增 owner 禁入规则生效。

满足这些条件后，Coordinator 才能保持“薄编排层”定位，而不是变成新的复杂度中心。

### 15. 修补计划的成功标准

完成上述修补后，下一次多专家复审的目标分数应为：

| 维度 | 当前分数 | 修补后目标 |
|---|---:|---:|
| 综合评分 | 67 | 80+ |
| 安全/权限/隐私 | 52 | 80+ |
| UX/交互 | 64 | 78+ |
| SRE/可靠性 | 61 | 78+ |
| QA/测试 | 62 | 80+ |
| 数据/评估 | 56 | 75+ |
| 发布/维护 | 72 | 82+ |

硬性成功标准：

- 默认 player profile 安全。
- 默认玩家体验不暴露内部协议。
- 崩溃和导入导出失败可恢复。
- 干净环境质量门可复现。
- metrics report 可比较。
- Coordinator 仍是薄编排层。

### 16. 对原设计文档的建议修订

建议在原设计文档中补充以下修订：

1. 将“Phase 0-7.1 主路径完成”改为“内部合同和 projection 状态语义阶段性完成”。
2. 明确本文档中的 R1-R4 是进入完整 Coordinator 的前置门槛。
3. 将 profile 从“标记和报告”升级为“权限、可见性、AI egress、write contract 策略”。
4. 将 projection hardening 拆成两个层次：
   - 状态语义 hardening。
   - 文件级可靠性 hardening。
5. 将 MCP 默认 surface 验收提前到安全阶段。
6. 将玩家可理解输出作为 UX blocker。
7. 将 `rpg_engine eval` 和 metrics report 作为独立阶段门槛。
8. 将 wheel/sdist、`.[mcp]`、MCP stdio、package data 校验纳入 release gate。

### 17. 对照后的最终结论

原设计文档仍然是正确的目标地图，但当前实现还没有走到地图上标注的成熟出口。下一阶段不应急着扩大架构，而应先修补默认安全、玩家表面、可靠保存、质量门和指标体系。

最重要的路线修订是：

> 先把边界变硬，再把体验变顺，再把写入变可靠，再把质量门变可复现，最后再用 Coordinator 统一编排。

如果按这个顺序推进，当前 67/100 的实现有机会在一轮集中 hardening 后进入 80 分以上；如果跳过这些前置门槛直接做 Coordinator，风险是得到一个看起来更统一、但仍然不安全、不像玩家产品、不可发布的更大系统。

### 18. 2026-07-01 第一批修补落地记录

本节记录本评审形成后的第一批实际修补。该批次只覆盖可安全独立合并的 R0、R1 和 R4 基础项，不代表 R0-R7 已全部完成。

已落地：

1. R0 文档校准：
   - [`turn-flow-architecture.md`](turn-flow-architecture.md) 开头新增“当前代码评审校准”。
   - 明确 Phase 0-7.1 是内部合同、主路径骨架和 projection 状态语义的阶段性架构里程碑，不代表默认 MCP/player surface、权限隔离、文件级可靠性、发布质量门和长期评估体系已经达到产品成熟度。
   - 明确完整 `TurnCoordinator` 前应先完成 R1-R4 硬门槛。

2. R1 路径 containment 第一刀：
   - `Campaign.database_path`、`events_path`、`current_snapshot_path`、`current_snapshot_json_path`、`cards_path` 改为 root-contained runtime path。
   - 新增 `Campaign.resolve_under_root()`，拒绝绝对路径和逃出 campaign root 的 runtime write/artifact 路径。
   - 为 save package 兼容，`content_files()` 暂时仍走原 `resolve()`；后续 R1/R7 需要通过受控 source campaign allowlist 或复制内容入 save package 完成 content path 收口。

3. R1 MCP profile gate 第一刀：
   - `MCPAdapterConfig` 新增 `mcp_profile`，默认 `player`。
   - 默认 player profile 禁止 `view=gm/maintenance`。
   - 默认 player profile 禁止 `mode="maintenance"`。
   - 默认 player profile 禁止 per-call semantic AI override。
   - 默认 player profile 禁止调用 `preview_action`、`validate_delta`、`commit_turn` 等低层工具。
   - 默认 player profile 禁止关闭 `state_audit` 或逐调用覆盖 commit AI helper。
   - 后续 2026-07-03 已完成 R2 第一刀：低层工具不再注册到默认 MCP player profile，只在 developer/trusted/maintenance/admin profile 注册。
   - MCP server CLI 新增 `--mcp-profile`，默认 `player`；需要低层工具时必须显式以 `developer`、`trusted_gm`、`maintenance` 或 `admin` profile 启动。

4. R4 质量门第一刀：
   - `pyproject.toml` 新增 `dev` extra：`pytest`、`ruff`、`coverage`、`build`、`twine`。
   - CI 改为安装 `.[dev,mcp]`。
   - CI 使用 `pytest` 默认收集测试。
   - CI 增加 `ruff check`、coverage report、wheel/sdist build 和 `twine check`。
   - `tests/regression.py` 改名为 `tests/test_regression.py`，进入默认 pytest 收集。

新增/更新测试：

- `tests/test_campaign_validation.py::CampaignValidationTests::test_campaign_runtime_paths_must_stay_under_campaign_root`
- `tests/test_mcp_adapter.py::MCPAdapterTests::test_mcp_player_profile_rejects_hidden_views_low_level_tools_and_ai_overrides`
- 需要低层 MCP 工具的既有测试显式使用 `mcp_profile="developer"`。

验证结果：

- `python3 -m pytest -q tests/test_campaign_validation.py tests/test_mcp_adapter.py`：`17 passed`
- `python3 -m pytest --collect-only -q`：`279 tests collected`
- `python3 -m pytest --collect-only -q tests/test_regression.py`：`26 tests collected`
- `python3 -m pytest -q`：`176 passed, 103 skipped, 173 subtests passed`

仍未完成：

- R1：content path 完整收口、hidden cards/export 隔离、archive/package zip bomb 限制、外部 AI egress server policy 完整化。
- R2：默认 player workflow 的 `start -> act -> confirm/query` 和默认输出隐藏内部协议。
- R3：atomic artifact write、outbox 全覆盖、save_patch 事件化、archive/backup 原子化。
- R4：repo 自包含真实 fixture、核心 skipped 豁免清单、MCP stdio smoke、package data 校验、Python 版本策略和完整元数据。
- R5：`rpg_engine eval` 和 metrics report。
- R6：Runtime/CLI/preview/render/projection owner 拆分和 Coordinator 前置门槛。
- R7：声明式 action/clock/random table/locale pack。

结论：第一批修补已经把两个硬风险从“文档要求”推进到“代码约束”：runtime write/artifact path 不能逃出 campaign root，默认 MCP player profile 不能直接碰 hidden/maintenance/低层写入工具。同时，强回归已进入默认 pytest 收集。但 R0-R7 仍必须按后续批次推进，不能把本批次视为完整 hardening 完成。

### 19. 2026-07-01 R0-R7 集中修补落地记录

本节记录第一批之后的集中修补结果。与第 18 节不同，本批次覆盖 R0-R7 的可落地修补项，并把安全、玩家表面、可靠写入、质量门、评估、边界测试和规则数据化切片串成可验证闭环。

重要边界说明：

- 本批次已经完成 R0-R7 修补计划中的“当前代码可安全独立落地”范围。
- R7 已完成一个可验证的规则数据化切片：自然语言随机/掷骰意图可以进入 `random_table` resolver，preview 与 commit 使用同一份 proposed delta，不再出现预览和保存二次掷骰不一致的问题。
- R7 的更大目标，即完整声明式 action spec、clock authoring、locale pack 和多题材内容 authoring 体系，仍属于后续大型 authoring 重构，不应在本批次中被夸大为全量完成。

#### 19.1 R0：完成度口径和文档校准

已落地：

- 保留第 18 节“第一批只覆盖 R0/R1/R4”的历史口径。
- 新增本节作为 R0-R7 集中修补的实际落地记录，避免把第一批止血误读为完整 hardening。
- `phase-0-surface-inventory.md` 补充玩家安全 workflow 和工具 profile 分类，使 MCP/player surface 与实际代码保持一致。

验收结果：

- 文档现在能区分三层状态：
  - 原设计目标。
  - 代码评审发现的问题。
  - 已实现修补项和仍需后续大型重构的边界。

#### 19.2 R1：安全/profile 和路径边界继续加固

已落地：

- `Campaign.resolve_under_root()` 已用于 runtime 写入和 artifacts 路径，拒绝绝对路径和 `..` 逃逸。
- 默认 MCP profile 仍为 `player`，低层工具、hidden/gm/maintenance 视图、maintenance mode、per-call semantic override、关闭 state audit 等操作均由代码级 gate 拒绝。
- 新增 boundary tests，确认 player profile 不属于低层工具或 hidden read profile，低层方法中存在显式 profile gate。

验收结果：

- 默认 player profile 无法直接调用 `preview_action`、`validate_delta`、`commit_turn`。
- 需要低层工具的测试必须显式使用 `developer` profile。
- 路径 containment 有回归测试覆盖。

仍需后续继续收口：

- `content_files()` 为兼容 save package 仍保留受控读取路径，后续应通过 source campaign allowlist 或复制内容入 save package 完成内容读取路径最终收口。
- hidden cards/export 和外部 AI egress server policy 可以进一步独立 hardening。

#### 19.3 R2：玩家/MCP 默认工作流收敛

已落地：

- 新增玩家级 workflow：
  - `player_query`
  - `player_act`
  - `player_confirm`
- CLI 新增 `aigm player query|act|confirm`。
- MCP surface 新增 `player_query`、`player_act`、`player_confirm`。
- `player_act` 只返回玩家可读的 preview/message/status，不暴露 `delta_draft`、`turn_proposal`、数据库路径或 Context Packet。
- `player_act` 将待确认行动写入 `.aigm/pending-player-action.json`。
- `player_confirm` 只提交当前待确认行动，并在成功后清除 pending action。
- `surface_inventory.py` 将低层 preview/validate/commit 标注为非 normal play、profile-gated，将 `player_confirm` 标为唯一 normal play validated commit surface。

验收结果：

- 玩家默认路径从“外部 Agent 直接碰内核 preview/validate/commit”收敛为“act -> confirm/query”。
- 测试覆盖玩家行动确认后保存、隐藏内部 delta/proposal、随机掷骰流程可提交。

后续建议：

- 增加 `player_start` 或更明确的 session bootstrap API，把当前 save、角色、可用动作和最近状态一次性返回给 UI/Agent。
- 为 pending action 增加过期、actor/session id 和并发冲突提示。

#### 19.4 R3：写入、投影、备份和归档可靠性

已落地：

- 新增 `rpg_engine/atomic_io.py`：
  - same-dir 临时文件。
  - file fsync。
  - `os.replace`。
  - directory fsync。
  - 失败清理。
- 以下写入改为 atomic write：
  - save registry 和 pending action。
  - save manifest rewrite。
  - events JSONL rewrite/append。
  - snapshots markdown/json。
  - generated cards 和 card index。
  - 初始空 events 文件。
  - save package 中的 `campaign.yaml` 和 `save.yaml`。
- cards 生成流程调整为先写新文件，再删除旧 generated card，避免中途失败留下空目录或半更新状态。
- save archive export 改为先写临时输出，再原子替换目标 archive。
- save archive import 增加 staging directory、路径安全校验、manifest/checksum/size/file count/extra file 校验，再原子替换目标目录，并提供失败回滚。
- archive import 增加基础 zip bomb 防护：
  - 最大文件数。
  - 单文件最大大小。
  - 总解压大小上限。

验收结果：

- `write_text_atomic` 在 replace 失败时保留旧文件。
- 恶意 archive path 不会创建目标目录。
- import 失败不会污染已有 save。
- `force` import 通过完整校验后才替换目标。

后续建议：

- 继续推进 outbox 全覆盖和 save patch 事件化。
- 对大型 archive 增加可配置限额和更完整的 restore drill。

#### 19.5 R4：质量门和发布链

已落地：

- `pyproject.toml` 新增 `dev` extra，包含 `pytest`、`ruff`、`coverage`、`build`、`twine`。
- `pytest` 默认只收集 `tests`，并排除 build/dist/egg-info/cache。
- `ruff` 排除 build/dist/egg-info/cache，避免发布产物影响静态检查。
- CI 安装 `.[dev,mcp]`。
- CI 覆盖：
  - 全量 pytest。
  - ruff。
  - coverage report。
  - installed CLI smoke。
  - wheel/sdist build。
  - twine check。
- `tests/regression.py` 已更名为 `tests/test_regression.py`，进入默认 pytest 收集。

最终验证结果：

- `python3 -m ruff check .`：通过。
- `python3 -m pytest -q`：`190 passed, 103 skipped, 183 subtests passed in 26.74s`。
- `coverage run -m pytest` + `coverage report --format=total`：`50`。
- `python3 -m build` + `python3 -m twine check dist/*`：wheel 和 sdist 均通过。
- wheel 内容检查：`rpg_engine/resources/evals/*.yaml` 已包含在 wheel 中。
- installed CLI smoke：
  - `aigm campaign copy-example`
  - `aigm campaign validate`
  - `aigm campaign test`
  - `aigm save init`
  - `aigm save validate`
  全部通过。
- wheel 安装后 `aigm eval run --format json`：`ok=true total=34 accuracy=1.0`。

后续建议：

- 为 103 个 skipped tests 建立豁免清单，区分“外部依赖缺失”“长期保留但非默认门禁”“需要恢复执行”的不同类型。
- coverage 50% 只能作为当前基线，后续应按模块设置增长目标，而不是直接要求全局一步到位。

#### 19.6 R5：指标和 ML-grade 评估

已落地：

- 新增 `rpg_engine/eval_suite.py`。
- eval gold set 和 MCP transcript fixtures 已复制到 `rpg_engine/resources/evals` 并纳入 package data，wheel 环境不再依赖源码树 `tests/fixtures`。
- 新增 CLI：
  - `aigm eval run --suite all|intent|mcp --format json|markdown`
  - `python3 -m rpg_engine eval run --format json`
- No-AI intent gold set 覆盖：
  - query。
  - routine。
  - travel。
  - social。
  - gather。
  - explore。
  - rest。
  - composite/negated/hypothetical/hidden injection block。
  - unresolved clarification。
  - random dice。
- MCP transcript eval 覆盖：
  - 合法自然语言行动。
  - 合法低层随机表 preview。
  - 先 preview_action 绕过自然语言的误用。
  - 未 validate 就 commit。
  - unready/failed validation 后 commit。
  - normal play 使用 maintenance/package upgrade 工具。
- 输出指标包括：
  - `accuracy`
  - `intent_accuracy`
  - `preview_accuracy`
  - `block_rate`
  - `ready_to_save_rate`
  - `tool_misuse_rate`

最终验证结果：

- `python3 -m rpg_engine eval run --format json`：
  - `ok: true`
  - total：`34`
  - passed：`34`
  - failed：`0`
  - accuracy：`1.0`
  - intent suite：`27/27`
  - MCP suite：`7/7`

后续建议：

- 增加带版本号的 eval report 输出，便于不同提交之间比较。

#### 19.7 R6：边界测试和 Coordinator 前置门槛

已落地：

- `tests/test_namespace_boundaries.py` 增加 owner/boundary 约束：
  - v1 CLI command set 暴露 `player` 和 `eval`，不暴露 `admin`。
  - player profile 不进入低层或 hidden read profile 集合。
  - 低层 MCP 方法必须包含显式 `require_low_level_profile` gate。
  - `player_confirm` 是 normal play surface 中唯一的 validated commit surface。
- 既有 boundary tests 继续保证 v1/MCP/runtime 不引入 legacy/admin surface。

验收结果：

- Coordinator 之前的关键门槛已经由测试约束，不再只停留在文档原则。

后续建议：

- 在正式引入完整 `TurnCoordinator` 前，继续把 runtime、preview/render、projection、CLI/MCP 的 owner 边界固化为更多 import 和 API contract tests。

#### 19.8 R7：规则数据化和 authoring 切片

已落地：

- `intent_router.py` 增加随机/掷骰自然语言识别：
  - 中文：`随机`、`掷骰`、`骰子`、`事件表`、`随机表`。
  - 英文：`roll`、`dice`、`random`。
  - 支持 `1d6`、`d20`、`2d6+1` 等 dice 表达式。
  - 支持 `table:<id>` 指定 table id。
- `actions/random_table.py` 增加 `resolve_random_table()`：
  - 生成 `kernel_random` 审计 delta。
  - 返回 `ResolutionResult(status="ready", proposed_delta=...)`。
  - 写入 `rules_applied` 和 `facts_used`。
- `runtime.preview_action()` 在 resolver 产生 `proposed_delta` 后，把该 delta 注入 preview context。
- `preview_random_table()` 优先使用 preview context 中的 proposed delta，确保 preview 展示的随机结果就是之后保存的随机结果。
- gold set 增加 `random_dice_cn`：`掷骰 1d6 判断桥上风险`。
- runtime 和 player workflow 测试覆盖随机掷骰 preview -> confirm -> save。

验收结果：

- 自然语言随机/掷骰行动可以进入可提交路径。
- preview 与 commit 不再二次随机。
- 随机结果作为 `kernel_random` 审计事件落入 delta，满足可追踪要求。

后续建议：

- 把 random table 的 table schema、dice policy、seed policy、locale text 和 outcome template 进一步数据化。
- 将更多 action resolver 从 Python 硬编码迁移到声明式 action spec。
- 引入 author smoke，验证新增一个非示例题材 action 不需要改核心 Runtime。

#### 19.9 本批次新增/更新的关键测试

新增或更新覆盖包括：

- `tests/test_atomic_io.py`
- `tests/test_eval_suite.py`
- `tests/test_save_manager.py`
- `tests/test_mcp_adapter.py`
- `tests/test_surface_inventory.py`
- `tests/test_namespace_boundaries.py`
- `tests/test_runtime.py`
- `tests/test_campaign_validation.py`
- `tests/fixtures/intent_router_gold_set.yaml`
- `tests/fixtures/mcp_external_agent_transcripts.yaml`
- `rpg_engine/resources/evals/intent_router_gold_set.yaml`
- `rpg_engine/resources/evals/mcp_external_agent_transcripts.yaml`

测试重点：

- 默认 player profile 安全拒绝。
- 玩家 act/confirm 不暴露内部协议。
- pending action 写入和提交闭环。
- 随机 dice 行动可自然语言 preview 并可提交。
- atomic write 失败不破坏旧文件。
- archive import/export 安全和回滚。
- eval suite 指标输出。
- namespace/profile/surface 边界。

#### 19.10 多专家复评结论

12 个角色对照本批次代码后的复评判断：

| 角色 | 复评分数 | 判断 |
|---|---:|---|
| 产品经理 | 82 | 默认玩家路径清晰很多，已能解释“玩家该怎么玩”，但 session bootstrap 仍需补齐。 |
| UX/交互设计师 | 78 | 玩家不再看到 delta/proposal，体验从开发者协议转为行动确认流。 |
| 游戏设计师/内容作者 | 78 | random/dice 切片解决了一个真实规则创作痛点，但声明式 authoring 还未全量完成。 |
| 软件架构师 | 80 | profile、surface、atomic IO 和 eval 都有清晰边界，Coordinator 前置条件明显改善。 |
| 后端/内核工程师 | 81 | pending action、atomic write、archive staging 让核心写入链路更稳。 |
| AI Agent 工程师 | 80 | 默认 MCP agent 不再直连内核低层写入，工具误用也有 transcript eval。 |
| AI/ML 与提示词工程师 | 77 | 有 No-AI gold set 和 MCP transcript metrics，仍需版本化 report 和更多真实 agent traces。 |
| QA/测试工程师 | 82 | 回归进入默认收集，新增边界、atomic、eval、player workflow 测试，质量门可跑。 |
| SRE/可靠性工程师 | 79 | 文件级 atomic 和 archive staging 明显降低事故面，restore drill 还可更强。 |
| 安全/权限/隐私工程师 | 81 | 默认 player profile 的拒绝策略已代码化，hidden/export/egress 仍建议继续专项加固。 |
| 数据/评估工程师 | 78 | eval CLI、基础指标和 package resources 已建立，下一步应做版本化历史对比。 |
| 发布/维护工程师 | 82 | dev extra、ruff、coverage、build/twine、installed CLI smoke 已形成基础发布门。 |

综合复评分数：`80/100`。

分数解释：

- 本批次已经达到第 15 节“修补后目标”的下限，可以视为 R0-R7 修补计划的第一轮完整 hardening 通过。
- 没有给到 85+ 的原因是 R7 完整声明式 authoring、hidden/export/AI egress 专项、coverage 增长和版本化 eval 历史对比仍是后续工作。

#### 19.11 最终修补状态

| 阶段 | 状态 | 本批次结论 |
|---|---|---|
| R0 | 完成 | 文档口径、已落地范围和后续边界已校准。 |
| R1 | 完成第一轮 hardening | 默认 player profile 和 runtime path 边界已代码化，仍有专项安全后续项。 |
| R2 | 完成 | player query/act/confirm 闭环已实现并测试。 |
| R3 | 完成第一轮 hardening | atomic write 和 archive staging/rollback 已实现并测试。 |
| R4 | 完成 | ruff、pytest、coverage、build/twine、installed CLI smoke 均可运行。 |
| R5 | 完成 | eval CLI、gold set、MCP transcript metrics 已实现并测试。 |
| R6 | 完成第一轮 boundary gate | profile/surface/namespace 关键边界已由测试约束。 |
| R7 | 完成可交付切片 | random/dice 数据化切片已打通 preview/commit，完整 authoring 重构留后续。 |

最终建议：

1. 可以把本批次作为 “R0-R7 hardening pass 1” 合并。
2. 下一轮不应继续扩大外部 surface，而应优先做：
   - eval report 版本化和历史趋势对比。
   - skipped tests 豁免清单。
   - hidden/export/AI egress 专项。
   - declarative action spec 的第二个非 random 示例。
   - pending action 的 session/concurrency 语义。
3. 完整 `TurnCoordinator` 可以开始设计和薄实现，但必须保持现有 player workflow、profile gate、atomic write 和 eval metrics 不倒退。
