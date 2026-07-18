---
baseline_commit: 3c3c5da56aec05b1cbf08693c39f96ee1b8b6955
---

# Story 3.8: Player-Safe Query 聚合完整性

Status: done

<!-- Note: 本 Story 已进入强制 validate-create-story；validation 结果记录于同名 validation report。 -->

## 用户故事

作为玩家，
我希望集合与数量查询返回所有符合条件的可见事实及准确聚合，
从而避免模糊匹配只返回单个对象或错误地报告“未找到”。

## 验收标准

1. 给定一个 `view="player"` 的结构化 query 请求某个物品语义类别的 `all`、`owner` 或 `location` scope，并可选择数量聚合，当 query pipeline 从当前 Save 读取事实时，返回所有 player-visible、active 且符合 owner/location/current-Save world scope 的成员；每个成员的 ID、名称、数量和单位与 SQLite 当前事实一致；数量合计必须由完整成员集按单位分组计算，不能退化为一个 fuzzy hit 或错误的 not-found。`all` 明确定义为当前 Runtime/Save world 内不附加 owner/location anchor 的全部匹配成员；非 player view 的 structured collection 请求稳定拒绝。
2. 给定当前场景中的地点、对象或同类资源查询，当 collection、filter 与 aggregation 运行时，location、status、visibility、owner 和 current-Save world scope 必须使用同一合同与次序；成员以 canonical `entities.id` 去重，duplicate aliases、重复名称或重复匹配条件不能造成重复成员或重复计数。
3. 给定候选集合含 hidden、GM-only、retired/archived/其他 non-active、其他 Campaign/Save 或超出 owner/location/player 可见范围的事实，当 player-safe query 生成结果时，这些事实必须在聚合前被排除；hidden-only、hidden/GM-only/retired/missing scope anchor 与真正空集合必须返回同形的安全 empty result，不得通过总数、成员数、名称、ID、scope id、omission reason 或诊断泄露其存在。只有 request schema/类型/字段组合本身非法时才返回固定、无敏感细节的 request error。
4. 给定 query 成功、集合为空、请求无效或被 visibility/scope gate 阻断，当调用前后比较 Save 与 workspace 时，query 始终只读；pending、turn、event、SQLite facts/schema、registry、`events.jsonl`、projection 与 Save 文件树均不发生 gameplay mutation，且 helper 不 commit/rollback/close caller-owned connection。
5. 给定 focused、current-native 与 cross-campaign 回归运行，当覆盖单项、多项、空集合、hidden、GM-only、retired、`all`/owner/location scope、mixed units 和 duplicate alias 对照组时，全部 fixture 使用独立 temporary Save/workspace；production 实现必须是通用结构化 query/collection/aggregation contract，不得加入特定自然语言短句、测试编排、AI 权威、Campaign 专用硬编码、依赖、migration 或测试专用 production API。

### Structured Query Contract

Request 使用固定 JSON-safe mapping：

| 字段 | 合同 |
| --- | --- |
| `entity_type` | 必填、非空 NFKC/casefold string；当前 Story 至少支持 `item`，不得从自然语言推断。 |
| `category` | 可选、非空 NFKC/casefold string；按 typed side table 的 canonical category 精确匹配。 |
| `scope` | 必填枚举：`all`、`owner`、`location`。`all` 即当前 Save world。 |
| `scope_id` | `owner`/`location` 必填 exact canonical ID；`all` 必须省略或为 `null`。不接受 alias、FTS、路径或隐式 current-player/current-location。 |
| `aggregation` | 必填枚举：`none`、`count`、`quantity`。`quantity` 按 exact unit 分组。 |

Scope 真值矩阵：

| `scope` | `scope_id` | 成员 SQL oracle | 隐式行为 |
| --- | --- | --- | --- |
| `all` | 禁止 | 当前连接的 `main` fact tables 中全部 matching active/player-visible members | current Save 即 world 边界；不自动限定玩家或当前地点。 |
| `owner` | 必填 | `e.owner_id = scope_id`，且 owner anchor 本身必须 active/player-visible | “玩家持有”必须由 caller 显式传入 canonical player entity ID。 |
| `location` | 必填 | `e.location_id = scope_id`，且 location anchor 必须是 active/player-visible location | 不隐式读取 current location；caller 必须显式传 canonical location ID。 |

Result 使用固定 allowlist：`contract`、`status`、`view`、`scope`、`entity_type`、`category`、`aggregation`、`members`、`member_count`、`totals`、`provenance`、`authority`。Member 只含 `id/name/quantity/unit`；quantity total 只含 `unit/quantity`。Empty、hidden-only、不可见/不存在/non-active anchor 均返回 `status="empty"`、`members=[]`、`member_count=0`、`totals=[]`，不返回 `scope_id`、omission/debug/raw request。Schema 非法固定抛出 `ValueError("structured entity query request is invalid")`；非 player view 固定抛出 `ValueError("structured entity query is player-only")`。

## 任务 / 子任务

- [x] 固化结构化 query collection 合同及其 authority。 (AC: 1, 2, 4, 5)
  - [x] 新增窄的 production query collection 模块，定义严格、可检查、只读的 request/result/member/totals contract；请求至少表达 entity type、semantic category、scope、scope id 与 aggregation，不把自然语言解析、AI candidate 或 fuzzy resolver 结果当作 collection membership。
  - [x] 只接受已命名的固定字段和枚举；拒绝 unknown fields、错误 scalar/collection 类型、空 category、scope/scope-id 不一致、unsupported aggregation 与同时提供旧单实体 query text 的歧义请求。
  - [x] 按上方 scope 真值矩阵实现：`owner` / `location` 使用 explicit exact canonical ID；`all` 只读取当前 Runtime 绑定的 Save SQLite world，不接受 caller 提供 Campaign/Save 路径或跨库来源，也不隐式替 caller 选择玩家/当前地点。
  - [x] Result 必须按字段表稳定输出完整 member list、member count、按单位分组的 quantity totals、scope/view/provenance 与固定 read-only authority；不同单位、`null` 与空字符串 unit 不得静默合并，空集合使用稳定安全 shape 且不回显 scope ID。
  - [x] Structured collection contract 固定为 player-only；`gm`/`maintenance` structured 请求稳定拒绝。旧单实体 query 仍按既有显式 view 合同工作，本 Story 不新增 hidden collection surface。

- [x] 实现单一 collection → filter → aggregation pipeline。 (AC: 1, 2, 3)
  - [x] 从 `main.entities` 及所需 typed side table 读取 current facts，先应用 exact type/category、normalized `status='active'`、scope 与 player visibility/subtype/world-setting filters，再按 canonical entity ID 形成成员，最后计算聚合。
  - [x] 复用 `normalize_visibility_view()`、`entity_visibility_sql()`、`entity_subtype_visibility_sql()` 与 `world_setting_entity_join_and_clause()`；player-safe hidden exclusion 必须发生在 SQL collection/query 阶段，最终 redaction 仅作 defense-in-depth。
  - [x] 不 join aliases 来决定 membership；duplicate aliases/名称不得扩增结果。SQL 与结果都按 canonical ID 确定性排序，并对意外重复 ID fail closed 或去重后只计一次。
  - [x] `quantity is null` 的记录保留为 member 但不进入 quantity total；SQLite exact integer 保持 integer，finite REAL 保持 JSON finite number，`-0.0` 规范为 `0.0`；`null` 与空字符串 unit 分组保持不同。任一已通过 visibility/scope filter 的 non-finite quantity使用固定 unavailable error，不能输出 NaN/Infinity；不跨单位求和，不从名称或 alias 推断 category。
  - [x] 保持普通 `resolve_entity()` / `render_entity()` 的 exact/alias/token/partial/body/FTS 单实体读取合同与非 archived read 语义，不把 active-only collection 规则扩散到共享普通 query/read。

- [x] 通过 Runtime facade 暴露结构化集合查询而不复制业务逻辑。 (AC: 1, 4, 5)
  - [x] 扩展 `GMRuntime.query(kind="entity", ...)` 的明确 keyword-only structured request 输入；旧 `query_text` 单实体路径保持兼容，structured 与 query text 同时出现时 fail closed。
  - [x] Runtime 只负责 capability/view normalization、调用 collection service 与把结构化 result/rendered text 放入 `QueryResult`；collection/filter/aggregation 不落在 CLI、MCP、SaveManager 或 adapter。
  - [x] 不新增默认 player MCP tool、CLI 自然语言规则或 `QUERY_KINDS`；不改变 surface taxonomy、pending/confirm/commit、context audit 或 AI intent authority。
  - [x] 输出的 `QueryResult.data` 必须是上表定义的 JSON-safe 正向 allowlist；`QueryResult.to_dict()` / `to_json_text()` 不允许 NaN/Infinity，player view 不包含原始 request、scope ID、hidden omission、SQL、debug exception 或 Campaign/Save filesystem path。

- [x] 建立自包含 focused / current-native / cross-campaign regression。 (AC: 1-5)
  - [x] 新增受追踪的 `tests/test_player_safe_query_aggregation.py`，不得依赖 Iteration 3 未提交 helper 或未跟踪 rebaseline 测试；先以不存在的 contract 取得 RED，再实现 GREEN。
  - [x] 在独立 temporary Save 中构造 single/multiple/empty、`all`/owner/location、mixed unit、hidden/GM-only、retired/archived、foreign/other-save 与 duplicate alias 对照；SQLite exact oracle 逐项核对 member ID/name/quantity/unit 和 totals。
  - [x] 对 player hidden-present 与 absent 建立 paired oracle，要求 member/totals/data/text/error shape 相同；失败断言仅输出安全 stage/scope/view/campaign/save label，不打印 hidden canary 正文或 raw row。
  - [x] success、empty、invalid、visibility-blocked 每条路径都比较 SQLite application schema/data snapshot、pending/registry/`events.jsonl` 与完整 Save tree digest；source Campaign、formal current Saves 与正式 registry 在 `finally` 中 fingerprint 不变。
  - [x] 在 temporary current-native copy 上证明至少两个 active player-visible ammunition rows 被完整返回并按 SQLite 精确聚合；自然语言“所有箭矢数量”不作为 production 行为合同。
  - [x] 在两个 canonical example Campaign 的 temporary Save 上复用同一 request/result contract，证明 current-Save isolation、空/非空结果均不需要 Campaign-specific branch，也不修改 source Campaign。
  - [x] 覆盖 unknown keys、bool/非 string 伪类型、caller mutable mapping defensive copy、全部 scope/scope-id 非法组合、`query_text + structured request` 冲突、hidden/foreign scope-id paired non-oracle，以及 result `to_dict()`/`to_json_text()` 的 strict JSON-safe shape。
  - [x] 分别验证 direct collection service 与 Runtime facade：direct service 使用 caller-owned connection，证明不 commit、rollback、close；Runtime 验证 keyword-only structured call、固定 errors 与旧单实体 path 兼容。
  - [x] Zero-write snapshot 动态覆盖全部 `main` application tables 与 DDL，同时覆盖 `events.jsonl`、projection、pending、registry 与完整 tree；不得用硬编码少量事实表掩盖新增写入。

- [x] 保留相邻 read/write/visibility 边界。 (AC: 2-5)
  - [x] 回归普通单实体 exact/alias/fuzzy resolution、scene query、context query、ContextBuildResult、Entity/Relationship/Progress access 与 Story 3.7 cross-campaign player-safe loop。
  - [x] 证明 consumption、gather/intake、craft、combat、pending/confirm/commit、projection/outbox 与 current-native write safety 不退化；本 Story 不修改它们的 production owner。
  - [x] 保持 SQLite current fact authority、events authoritative audit、projection/registry/pending/advisory 非事实语义；query 不创建 TurnProposal、pending、event 或 context audit row。

- [x] 同步 canonical docs、BMAD 状态与完整门禁。 (AC: 1-5)
  - [x] 更新 `docs/architecture.md`、`docs/data-models.md`、`docs/testing-and-quality-gates.md`，记录结构化 collection contract、input/output/error/visibility/read-only authority、focused gate 与自然语言/AI/adapter 非所有权。
  - [x] 若不改变 CLI/MCP/prompt surface，在 completion notes 明确无需更新 `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`；若实现意外改变这些 surface，必须先停下按真实范围决策处理。
  - [x] `docs/save-and-campaign-packages.md` 若 package/save/player-entry contract 未变则不更新，并在 completion notes 说明；若 Runtime collection contract 影响该文档现有 query 说明，则同步最小必要段落。
  - [x] 完成 Story validation、dev story、三路 fresh review 自动收敛；每次有效 patch 后重跑受影响 verification，再做 fresh 三路 review，直到 clean 或只剩已正确记录的 dismiss/defer。
  - [x] 从最终 clean diff 重新运行 focused、adjacent、两套 Campaign validate/test、Markdown links、full `py_compile`、full Ruff、`git diff --check` 与 repository full pytest suite；不得复用被后续 patch 失效的绿灯。

### Review Findings

- [x] [Review][Patch] 聚合对 finite 大数泄漏 `OverflowError`，且 all-int defensive path 不保留整数精度 [rpg_engine/query_collection.py:297]
- [x] [Review][Patch] Renderer 将 `unit=None` 与 `unit=""` 合并为相同玩家文本 [rpg_engine/query_collection.py:324]
- [x] [Review][Patch] Structured Runtime/direct service 将 unknown、None、bool view 静默降级为 player [rpg_engine/runtime.py:1049]
- [x] [Review][Patch] `scope_id` grammar 宽于 canonical Entity ID contract [rpg_engine/query_collection.py:31]
- [x] [Review][Patch] Request 使用 casefold 而 SQL label helper 只 lower，导致 Unicode category 完整成员遗漏 [rpg_engine/query_collection.py:245]
- [x] [Review][Patch] Runtime 通用 hidden redactor 可因同名 hidden row 改写已通过 SQL gate 的 visible member/protocol 字段并形成 existence oracle [rpg_engine/runtime.py:1064]
- [x] [Review][Patch] Current-native oracle 未独立核对 exact quantity totals [tests/test_player_safe_query_aggregation.py:443]
- [x] [Review][Patch] Cross-campaign oracle 未应用 player visibility，且未逐项核对完整 member/totals [tests/test_player_safe_query_aggregation.py:475]
- [x] [Review][Patch] Focused matrix 缺 archived、aggregation none、unknown view 与 sibling workspace pending/registry zero-write evidence [tests/test_player_safe_query_aggregation.py:262]
- [x] [Review][Patch] Dev Agent Record、File List 与 Story/Sprint `review` 状态尚未同步真实实现证据 [_bmad-output/implementation-artifacts/3-8-player-safe-query-聚合完整性.md:7]
- [x] [Review][Patch] Renderer 的默认 `:g` 精度会舍入大数与高精度数量，导致玩家文本和结构化事实不一致 [rpg_engine/query_collection.py:348]
- [x] [Review][Patch] `math.fsum` 中间溢出会把真实有限的抵消合计误报为 unavailable，且结果受 canonical ID 顺序影响 [rpg_engine/query_collection.py:233]

## 开发说明

### 来源与 P0 范围

- 2026-07-17 Correct Course 将 QRY-02 / R-009 定为 P0，并固定收敛次序 `1.10 -> 6.9 -> 3.8`；当前前两项已完成，Story 3.8 是下一项。
- Epic 3 Story 3.8 明确要求 structured `all`/quantity collection、完整 visible active membership、owner/location/world filtering、pre-aggregation hidden exclusion、zero mutation 与 temporary Save coverage。
- Iteration 3 失败证据显示 current-native SQLite 有 5 个 active visible ammunition rows，而旧 `GMRuntime.query("entity", text)` 走单实体 fuzzy resolver 后返回 not-found。该现象证明缺少集合合同，不证明应扩大自然语言识别。
- 本 Story 只解决 QRY-02。Trace 中其他 PARTIAL gap、external Skill/Hermes system 收敛、Story 1.10/6.9 或其他 Epic 工作均不进入本 Story。

### 当前实现与架构所有权

- `GMRuntime.query()` 是 runtime facade；`render_entity()` + `resolve_entity()` 是旧单实体路径。`resolve_entity()` 的 exact/alias/token/partial/body/FTS 及 `limit 1` 是刻意的单实体合同，不能作为集合枚举 owner，也不能为本 Story放宽。
- 建议生产 owner 为窄 query collection 模块（例如 `rpg_engine/query_collection.py`）；它接收结构化条件、从当前 Save SQLite 收集并过滤、聚合，再交由纯 renderer。Runtime 只调用，不复制 SQL/aggregation。
- `ContextBuildResult` 仍是 Context Slice，不承担第二套集合 query model；Entity Access 默认 non-archived read 语义也不被全局改成 active-only。
- Hidden filtering 复用现有 visibility SQL helpers，并必须先于 aggregation；player hidden-only 与 absent 同形。SQLite 是事实权威，最终 redaction 只作 defense-in-depth。
- 当前 `tests/test_iteration3_query_aggregate.py` 是未提交 rebaseline 证据，不得成为 clean checkout 唯一测试依赖；Story 自身必须新增受追踪、自包含的 focused test。

### 仓库与文件边界

- 开始时 worktree 已包含用户的 Correct Course、Iteration 3 test reports/Trace、rebaseline helpers/tests 等未提交工作；全部保留，不删除、回滚、覆盖或整体暂存。
- Story 只预计新增/修改 query collection production owner、Runtime facade、focused test、三份 canonical docs、Story/validation artifact 与 sprint status。
- `sprint-status.yaml` 同时含用户已批准的日期/Epic 3 reopen/Story 3.8 backlog hunk；完成提交时只暂存 Story 3.8 所需的精确状态同步及必要上下文，不混入其余测试报告或规划文件。
- 不修改 source Campaign、formal current Saves、正式 registry、Hermes 仓库、examples 内容、schema/migrations、依赖、AI intent/preflight 或 SaveManager commit chain。

### 技术约束

- Python >= 3.11、stdlib `sqlite3`；不新增或升级依赖。
- Request normalization 必须拒绝 bool 冒充 string/number、unknown mapping keys 与 caller-owned mutable collection 的后续影响；公共错误稳定、脱敏，不保留 raw exception cause。
- SQL 参数化 scope/category/id；标识符只使用 production 固定常量。所有查询限定当前 Runtime connection 的 `main` fact tables，不 attach 外部数据库，不接受 filesystem path。
- Quantity totals 按 exact unit 分组；成员数量和值保持 SQLite JSON-safe 表达，聚合必须 finite 且确定。若 visibility/scope filter 后发现 non-finite quantity，使用固定 unavailable error，不得产生非 JSON 常量。
- Empty/hidden/missing anchor 固定为同形 QueryResult；仅 request schema 非法与 non-player view 使用上述固定 `ValueError`。所有 outcome 都必须 zero-write，错误形状不得因 hidden row 是否存在而变化。

### 测试要求

Focused RED/GREEN：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_player_safe_query_aggregation.py \
  -p no:cacheprovider
```

相邻 read/context/cross-campaign/visibility regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_runtime.py \
  tests/test_entity_resolution.py \
  tests/test_entity_access.py \
  tests/test_context_quality.py \
  tests/test_current_native_context.py \
  tests/test_current_native_visibility.py \
  tests/test_cross_campaign_context_smoke.py \
  tests/test_cross_campaign_model_smoke.py \
  -p no:cacheprovider
```

相邻 player-safe write/domain regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_save_manager.py \
  tests/test_validation_pipeline.py \
  tests/test_current_native_write_safety.py \
  tests/test_iteration3_intake_commit.py \
  tests/test_current_native_consumption_craft_deltas.py \
  -p no:cacheprovider
```

Campaign gate：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
```

最终 docs/static/full gates：

```bash
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m compileall -q rpg_engine tests scripts
python3 -m ruff check .
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

### 残余风险与非目标

- 本 Story 不负责把开放式自然语言自动翻译为 structured query；外部/内部 AI 可提出低信任 query slots，但不能获得 hidden、事实、确认或 commit authority。
- 不新增 SQL migration、专用 aggregation table、search index、Campaign-specific category ontology、CLI command、MCP default tool 或 test orchestration API。
- 不改变普通单实体 query 的 fuzzy behavior，不解决所有 Query/Trace PARTIAL，也不把 scene/context 全部重写为新合同；只在共享过滤不变量处复用 helper。
- 即使 QRY-02 修复并通过 Story 门禁，Iteration 3 总 Gate 仍按整体 Trace 条件独立评估，不能因本 Story 单项绿灯直接宣称 release-ready。

## Project Structure Notes

- 新 production contract 放在 `rpg_engine/` 的窄 query module；不要把 collection SQL 塞进 CLI/MCP/SaveManager，也不要让 `render.py` 继续增长为 query service。
- 新 focused test 放在 `tests/test_player_safe_query_aggregation.py`；使用仓库已有 temp Save/copy helper 或文件内朴素 helper，但不能依赖未提交 Iteration 3 conftest。
- canonical docs 只记录当前已实现合同，不提前承诺自然语言 parser、AI route、CLI/MCP surface 或 migration。

## References

- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-17.md`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/3-7-跨-campaign-的-context-与玩家安全回路集成冒烟测试.md`
- `_bmad-output/test-artifacts/automation-validation-iteration-3.json`
- `_bmad-output/test-artifacts/test-review.md`
- `_bmad-output/test-artifacts/traceability-matrix.md`
- `_bmad-output/test-artifacts/gate-decision.json`
- `docs/project-context.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/runtime.py`
- `rpg_engine/render.py`
- `rpg_engine/db.py`
- `tests/test_runtime.py`
- `tests/test_entity_resolution.py`
- `tests/test_cross_campaign_context_smoke.py`
- `tests/test_cross_campaign_model_smoke.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- Create Story research：Story 3.8 exact AC、Correct Course P0 scope、Iteration 3 QRY-02 failure、PRD/Architecture/canonical docs、Story 3.7 与当前 code path 已完成只读核验。
- RED baseline：pre-existing Iteration 3 probe `tests/test_iteration3_query_aggregate.py` 当前为 `1 passed, 1 failed`；失败项返回“未找到实体”，同时 temp Save tree digest 不变。
- Dev Story RED：新增 focused test 初次收集因 `rpg_engine.query_collection` 不存在而失败；实现 contract 后 focused suite 转绿。
- Review Round 1：Blind Hunter、Edge Case Hunter、Acceptance Auditor 三路 fresh review 共报告 10 个去重后有效 Patch、0 Decision、0 Defer；全部复现并修复，受影响 focused/runtime gate 为 `102 passed, 99 subtests passed`。
- Review Round 2：Blind Hunter 与 Edge Case Hunter 各报告 1 个有效 Patch，Acceptance Auditor CLEAN；修复 quantity 文本往返精度与可抵消 finite sum 的中间溢出，受影响 focused/runtime gate 为 `104 passed, 99 subtests passed`。
- Review Round 3：Blind Hunter、Edge Case Hunter、Acceptance Auditor 三路 fresh review 全部 CLEAN；0 Decision、0 Patch、0 Defer、0 Dismiss，进入最终 clean-diff verification。

### Completion Notes List

- 新增严格 player-only 的结构化 collection request/result contract，以当前 Save `main` SQLite 为唯一事实来源，并按 collection → scope/status/visibility → canonical-ID de-dup → unit aggregation 的次序执行。
- Runtime 仅暴露 keyword-only structured facade；旧单实体 query 保持兼容，structured 结果不经过会读取全库 hidden token 的通用 redactor，避免 hidden existence oracle。
- 覆盖 all/owner/location、empty/hidden/GM-only/retired/archived、mixed/null/empty units、Unicode casefold、overflow、duplicate aliases、strict view、caller-owned transaction、current-native 与 cross-campaign 独立 SQL oracle；所有写测试均使用 temporary Save/workspace。
- 同步 architecture、data model 与 quality gate 文档；CLI/MCP/prompt、package/save/player-entry surface 均未改变，因此无需修改 `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`、`docs/save-and-campaign-packages.md`。
- 最终 clean-diff gates：focused `23 passed`；read/context/visibility adjacent `176 passed, 9042 subtests passed`；write/domain adjacent `68 passed, 37 subtests passed`；两套 Campaign validate/test 均 `OK`；Markdown links `211 files checked`；全量 `py_compile`、full Ruff、`git diff --check` 均通过；repository full suite 最终 `1621 passed, 10331 subtests passed`。
- Full suite 首次运行只暴露未跟踪 Iteration 3 rebaseline test 的旧数量文本断言；最小同步为可往返 float 文本后失败节点与完整 suite 均通过。该 rebaseline 文件继续作为用户既有未跟踪工作保留，不进入 Story 3.8 commit。

### File List

- `_bmad-output/implementation-artifacts/3-8-player-safe-query-聚合完整性.md`
- `_bmad-output/implementation-artifacts/3-8-player-safe-query-聚合完整性.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `rpg_engine/query_collection.py`
- `rpg_engine/runtime.py`
- `tests/test_player_safe_query_aggregation.py`
- `tests/test_runtime.py`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`

### Implementation Plan

- 定义窄、严格且 JSON-safe 的 request/member/totals/result dataclass contract。
- 复用既有 visibility/subtype/world-setting SQL gate，在 current Save `main` 表中参数化收集完整成员后才聚合。
- 由 Runtime facade 调用单一 service 与纯 renderer，保持旧 query surface 及所有写路径不变。
- 以 self-contained temporary Save focused tests、current-native copy 与两个 example Campaign 的独立 SQL oracle 验证完整性、隔离性与零写。
- 更新 canonical docs，执行三路 fresh review 自动收敛及最终全门禁。

### Change Log

- 2026-07-18: 基于 Correct Course、Epic 3.8、Iteration 3 QRY-02、PRD/Architecture 与现有 query code path 创建 Story；状态设为 `ready-for-dev`。
- 2026-07-18: 完成 Dev Story 与第一轮三路 fresh review 的 10 个有效 Patch；focused/runtime 复验通过，状态设为 `review`。
- 2026-07-18: 完成第二轮三路 fresh review 的 2 个有效 Patch并复验通过；继续保持 `review` 等待 fresh clean round 与最终门禁。
- 2026-07-18: 第三轮三路 fresh review 全部 CLEAN；三轮累计 12 个有效 Patch全部关闭，进入最终 clean-diff required gates。
- 2026-07-18: 最终 focused、adjacent、Campaign、docs/static 与 repository full suite 全部通过；Story 3.8 设为 `done`，Epic 3 全部 Story 完成。
