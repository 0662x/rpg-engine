---
baseline_commit: adb81ea02a438d95fbbe6258d151ddde549caf75
---

# Story 3.7: 跨 Campaign 的 Context 与玩家安全回路集成冒烟测试

Status: done

Completion note: Cross-campaign Context 与 player-safe loop integration smoke 已实现，review 与最终门禁证据记录于下文。

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为引擎作者，
我希望在 Context Slice 基础完成后，再用跨 Campaign 冒烟测试覆盖 context assembly 和基础 player-safe loop，
从而证明通用 Kernel 行为成立，同时避免 Epic 2 依赖 Epic 3。

## 验收标准

1. 给定至少两个 capability profile 或 genre assumption 不同的 Campaign Packages，当每个 package 在 temporary save copy 上运行 context assembly、basic query、preview、validation 和 safe player loop smoke 时，两者都必须复用同一套 `ContextBuildResult`、visibility filtering、`player_turn`、pending action、`player_confirm` 和 commit validation 边界，且不需要 campaign-specific context fork 或 custom player-safe commit chain。
2. 给定 cross-campaign smoke 发现 context 缺失、hidden 泄漏或 player-safe loop 失败，当测试报告生成时，报告必须指出对应 Campaign、Save、context source、visibility mode 或 player-safe stage，且正式 current save packages 不会被测试修改。

## 任务 / 子任务

- [x] 建立独立的跨 Campaign Context / player-safe focused regression。 (AC: 1, 2)
  - [x] 新增 `tests/test_cross_campaign_context_smoke.py`，覆盖 `examples/v1_minimal_adventure` 与 `examples/small_cn_campaign`；不把 Story 3.7 的 context / player loop 断言塞回 Story 2.6 的 model-only smoke。
  - [x] 每个 case 在独立 `TemporaryDirectory` workspace 中复制 source Campaign，通过同一 `SaveManager.start_or_continue()` 创建 temporary Save；断言 temp root 不在 source Campaign 或任何 configured/registered formal current Save 之下。
  - [x] 在测试前后 fingerprint 两个仓库 source Campaign、workspace 中的 Campaign copy 和已配置的 formal current Save；只允许 temporary Save、temporary `.aigm` registry/pending 发生变化。
  - [x] 复用 `tests/helpers.py::tree_digest` 和现有 SaveManager/runtime 公开 helper；不将 test orchestration 移入 production CLI、MCP、`SaveManager` 或 `GMRuntime`。

- [x] 证明两个 Campaign 复用同一 Context Slice 与 player visibility 边界。 (AC: 1, 2)
  - [x] 在每个 temporary Save 上通过 `GMRuntime.start_turn(..., view="player")` 和 `GMRuntime.query("context", ..., view="player")` 构建 context；断言 `contract.id == "ContextBuildResult"`、版本、pipeline steps、collector sources、visibility mode 与稳定顶层 shape。
  - [x] 比较两个 result 的 contract/pipeline 结构而不强求题材内容相同；要求 context evidence 自然反映各 Campaign 的 entity、relationship、progress/clock 与 world-setting 数据。
  - [x] 通过 `GMRuntime.query("scene", view="player")` 和 context query 覆盖 basic query，并证明 query/context assembly 不推进 `current_turn_id`、events 或 gameplay facts；默认未启用 audit 时不新增 `context_runs` rows。
  - [x] 使用两个 Campaign 已有 hidden reference 的 id/name/summary/alias 作为 canary，断言它们不存在于 `StartTurnResult`、`QueryResult`、`ContextBuildResult.to_json_text()`、markdown、loaded/omitted evidence 或 player-safe diagnostics；不得仅检查最终 markdown。
  - [x] 断言 player result 不会通过 hidden count、raw omission category、endpoint、alias 或 diagnostics 形成 existence oracle；不复制 Story 3.2-3.6 的全量极端 case，仅做跨 Campaign 集成护栏。

- [x] 证明 preview、validation、pending/confirm/commit 为同一玩家安全链。 (AC: 1, 2)
  - [x] 为每个 case 使用 package 已声明的 `rest_time` capability 和题材对应的玩家文本，先通过 `GMRuntime.preview_action("rest", ...)` 生成 ready preview；断言 preview 有 `delta_draft` / `turn_proposal` 且不改 SQLite facts。
  - [x] 对 preview delta 调用 `GMRuntime.validate_delta(..., action="rest", ...)`，断言使用 `player_turn_commit` validation profile 的结果可通过，且 validation-only 不写入事实。
  - [x] 通过 `SaveManager.player_turn()` 再次走正式玩家入口；断言返回 `ready_to_confirm=true`、`saved=false` 和一次性 `session_id`，pending 绑定 active save/path/player text/action/delta/TurnProposal/expiry，但 authoritative Save snapshot 不变。
  - [x] 使用错误 session id 的 `player_confirm` 必须被拒绝且不写入；随后使用 `player_turn` 返回的正确 id 调用 `player_confirm`，断言 validation/commit 成功、turn/event 增加、pending 清理、projection health 可检查。
  - [x] 测试只通过公开 `SaveManager` / `GMRuntime` 边界推进流程；禁止直接 SQL commit、手工调用 `save_turn_delta()` 或 campaign-specific helper 伪造通过。

- [x] 让失败报告可操作，不泄漏 hidden 正文。 (AC: 2)
  - [x] 为每个阶段生成安全的 assertion context，至少包含 `campaign`、temporary `save` label/path、`stage`、`context_source` 和 `visibility_mode`；失败信息不得复制 hidden name/summary/alias 或 raw player payload。
  - [x] 对 context source 缺失、hidden canary 命中、preview/validation/pending/confirm/commit 失败使用独立 stage code，使 pytest/subTest 输出可直接定位 Campaign 与边界。
  - [x] 报告仅是 test evidence，不新增 SQLite 事实表、runtime diagnostics API、CLI/MCP 输出字段或玩家可见的 hidden debugging surface。

- [x] 同步 canonical docs 与门禁。 (AC: 1, 2)
  - [x] 更新 `docs/data-models.md` 中 Story 2.6 的“后续 Context Slice story”说明，记录 Story 3.7 跨 Campaign Context / player-safe loop 集成边界与测试入口。
  - [x] 更新 `docs/save-and-campaign-packages.md`，说明两个 Campaign 在 temporary workspace/save 上复用同一 `SaveManager` pending/confirm 链与 no-source/no-formal-save mutation 护栏。
  - [x] 更新 `docs/testing-and-quality-gates.md`，把 `tests/test_cross_campaign_context_smoke.py` 记为 context assembly / player-safe foundation 变更的 focused integration gate。
  - [x] 本 story 若只新增 regression test/docs 且不改公开 CLI/MCP/prompt 语义，在完成记录中明确说明无需更新 `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`。

- [x] 以 RED/GREEN 方式完成实现、review 与最终证据。 (AC: 1, 2)
  - [x] 先运行不存在的 `tests/test_cross_campaign_context_smoke.py` 作为 RED，再新增最小 focused test 转 GREEN。
  - [x] 运行“测试要求”中的 focused、adjacent context/player-safe、Campaign CLI、docs/static 与 full-suite gates；review patch 落地后之前的结果失效，必须重跑。
  - [x] 证据必须记录每个 Campaign 的 context contract、query no-write、preview/validation no-write、pending no-write、wrong-session reject、confirm commit 和 source/formal-save no-mutation 结论。

### Review Findings

- [x] [Review][Patch] 枚举所有 configured/registered formal Save，在 cleanup/finally 中强制 fingerprint postcondition，并完整拒绝 temp workspace 与 protected root 的双向包含 [tests/test_cross_campaign_context_smoke.py:92]
- [x] [Review][Patch] no-write snapshot 应动态覆盖全部 application tables 与 schema，避免新增 authoritative table 或 schema 变更被硬编码清单漏过 [tests/test_cross_campaign_context_smoke.py:76]
- [x] [Review][Patch] 所有 runtime/manager 调用、mapping key 和敏感等值断言必须 fail closed 为安全 stage report，不回显 raw player/scene payload [tests/test_cross_campaign_context_smoke.py:108]
- [x] [Review][Patch] context source、entry path、hidden guard 和 signature 失败应使用独立 stage/source report，不得共用笼统 `ContextBuildResult` 报告 [tests/test_cross_campaign_context_smoke.py:126]
- [x] [Review][Patch] hidden canary 排除前必须先证明 fixture 中该 entity 真实存在且 maintenance view 下仍为 hidden [tests/test_cross_campaign_context_smoke.py:30]
- [x] [Review][Patch] 对 omitted/completeness/diagnostics 执行递归 non-oracle 检查，拒绝 hidden count/existence/raw category 与 GM-only 标签泄漏 [tests/test_cross_campaign_context_smoke.py:289]
- [x] [Review][Patch] 同时比较 `start_turn` 与 `query("context")` 的 contract signature，顶层 shape 使用必需键子集以允许 additive compatibility [tests/test_cross_campaign_context_smoke.py:132]
- [x] [Review][Patch] 对每个 Campaign 断言实际 visible entity/relationship/progress/world-setting markers，防止空壳 collector 仅伪造 source label [tests/test_cross_campaign_context_smoke.py:140]
- [x] [Review][Patch] 显式要求至少两个 Campaign、capability profile 不同，且两者共同声明 `query` / `rest_time` [tests/test_cross_campaign_context_smoke.py:30]
- [x] [Review][Patch] pending 必须精确绑定返回的 session id；wrong-session 后 pending 不得改写，正确 confirm 后同一 session replay 必须被拒绝且 no-write [tests/test_cross_campaign_context_smoke.py:184]
- [x] [Review][Patch] hidden canary 扫描需覆盖 preview、validation、player_turn 和 confirm 结果，不能只检查 context/query 阶段 [tests/test_cross_campaign_context_smoke.py:146]
- [x] [Review][Patch] 修正模板 completion note、validation-time status 表述与 canonical docs 过度承诺，并在 review patch 后重跑和记录最终门禁 [_bmad-output/implementation-artifacts/3-7-跨-campaign-的-context-与玩家安全回路集成冒烟测试.md:9]
- [x] [Review][Patch] 对每个 Campaign 反向排除其他 Campaign 的唯一可见 marker，防止全局缓存或 collector 将跨 Campaign 内容串线 [tests/test_cross_campaign_context_smoke.py:223]
- [x] [Review][Patch] 把每个可见 marker 绑定到宣称的 loaded-item collector source，不得仅分别证明 source label 和全局 payload marker 存在 [tests/test_cross_campaign_context_smoke.py:217]
- [x] [Review][Patch] 对 pipeline_steps、collector_sources 和 audit_tables 显式验证类型/存在性，禁止两个 Campaign 以相同 `__invalid__` 哨兵值伪装 contract 一致 [tests/test_cross_campaign_context_smoke.py:612]
- [x] [Review][Patch] 递归扫描完整 completeness 以及 preview/validation/pending/player_turn/confirm 的 hidden/non-oracle evidence，不得只检查两个 completeness 子字段或精确 canary [tests/test_cross_campaign_context_smoke.py:234]
- [x] [Review][Patch] 断言 pending TurnProposal 的 validation_profile、human_confirmed 和 proposal.delta 与 pending.delta 自一致，证明正式 pending/confirm 仍走 player_turn_commit 链 [tests/test_cross_campaign_context_smoke.py:324]
- [x] [Review][Patch] registry 读取或 shape/path 非法时 fail closed 为安全 stage report，不得静默遗漏 formal Save fingerprint 与 workspace-overlap 保护 [tests/test_cross_campaign_context_smoke.py:668]
- [x] [Review][Patch] 正确 confirm 必须精确只增加一个 turn，同时保留 event 增长断言，防止首次 confirm 重复提交 [tests/test_cross_campaign_context_smoke.py:392]
- [x] [Review][Patch] replay 被拒绝后再次断言 pending 仍为空，防止拒绝路径重建可重放 session state [tests/test_cross_campaign_context_smoke.py:396]
- [x] [Review][Patch] 所有 player-safe payload 同时扫描两个 Campaign 的 hidden canary，防止跨 Campaign 缓存只串入 foreign hidden 内容 [tests/test_cross_campaign_context_smoke.py:642]
- [x] [Review][Patch] non-oracle 递归必须识别嵌套/复数形态，包括 `visibility_counts.hidden`、`omission_categories=[hidden]` 与 `gm_only.alias` [tests/test_cross_campaign_context_smoke.py:650]
- [x] [Review][Patch] registry Save path 必须复用公开相对路径合同，拒绝 absolute、反斜杠、`..` 和 resolve/symlink workspace escape [tests/test_cross_campaign_context_smoke.py:793]
- [x] [Review][Patch] temporary workspace cleanup 需断言写入只位于原 Campaign copy、temporary Saves 与 temporary `.aigm` entry state，拒绝其他 top-level 副作用 [tests/test_cross_campaign_context_smoke.py:494]
- [x] [Review][Patch] 每个 Campaign 必须显式断言 hidden canary 非空，禁止空 tuple 让 fixture 与泄漏扫描 vacuous pass [tests/test_cross_campaign_context_smoke.py:156]
- [x] [Review][Patch] non-oracle 扫描需拒绝 `gm_metadata` 等 composite GM/hidden key、`hidden_allowed=true` 与 `visibility_mode=gm-only` [tests/test_cross_campaign_context_smoke.py:660]
- [x] [Review][Patch] formal registry 必须显式支持 schema v1/存在 saves list，并在解析前拒绝 registry 自身的 symlink workspace escape [tests/test_cross_campaign_context_smoke.py:835]
- [x] [Review][Patch] source/formal Save no-mutation cleanup 必须同时 fingerprint 已发现的正式 `.aigm/save-registry.json` [tests/test_cross_campaign_context_smoke.py:827]
- [x] [Review][Patch] temporary workspace scope 必须递归禁止嵌套 symlink escape，限定 `.aigm` 为 registry/pending 文件且 `saves` 为本 case Save，并对非目录 campaigns fail closed [tests/test_cross_campaign_context_smoke.py:812]
- [x] [Review][Patch] 所有 player-facing chain payload 都必须反向排除 foreign Campaign 的唯一可见 marker，不得只在 Context payload 检查 [tests/test_cross_campaign_context_smoke.py:639]
- [x] [Review][Patch] wrong-session 与 replay 捕获到的异常文本必须扫描 all-Campaign hidden canary 和 foreign visible marker [tests/test_cross_campaign_context_smoke.py:501]
- [x] [Review][Patch] broken registry symlink 不得因 `Path.exists()` 为 false 而被当作缺失 registry 静默跳过 [tests/test_cross_campaign_context_smoke.py:899]
- [x] [Review][Patch] temporary `.aigm` 允许的 registry/pending entry 必须是普通文件，同名目录必须 fail closed [tests/test_cross_campaign_context_smoke.py:865]
- [x] [Review][Patch] non-oracle 需识别 `visibility_mode` 中的 composite hidden/GM label，不得只做整串等值 [tests/test_cross_campaign_context_smoke.py:740]
- [x] [Review][Patch] configured current Save 为 symlink 时必须同时沿 lexical 与 resolved parents 发现正式 registry [tests/test_cross_campaign_context_smoke.py:886]
- [x] [Review][Patch] formal registry fingerprint 必须同时记录 lexical symlink target 与 file bytes，防止等价 retarget 绕过 no-mutation [tests/test_cross_campaign_context_smoke.py:934]
- [x] [Review][Patch] 两个 Campaign 共用 `clock:storm-front` 时必须另加各自唯一 progress canary，防止只串线 progress collector 却通过隔离断言 [tests/test_cross_campaign_context_smoke.py:54]
- [x] [Review][Patch] configured lexical/resolved ancestors 下的候选 registry 即使初始缺失也必须纳入 fingerprint，防止运行中新建正式 registry [tests/test_cross_campaign_context_smoke.py:926]

## 开发说明

### 来源上下文

- Epic 3 的完成目标是让 `ContextBuildResult` 成为 prompt/render/query/advisory 的 inspectable Context Slice，并在 collection/query 阶段排除 hidden / GM-only 内容。来源：`_bmad-output/planning-artifacts/epics.md#Epic 3`。
- Story 3.7 明确要求两个不同 Campaign 复用 context assembly、basic query、preview、validation 与 safe player loop，并为失败输出可操作且不泄密的 stage evidence。来源：`_bmad-output/planning-artifacts/epics.md#Story 3.7`。
- PRD FR-10 / FR-11 / FR-17 要求可检查、visibility-safe 的 context，并证明不同 Campaign Package 复用同一通用 Kernel foundation flow。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-5 定义 `ContextBuildResult` / Context Slice，AD-7 要求题材差异留在 Campaign capability/content/hooks，AD-10 要求至少两个 package 的 boundary test。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Execution-chain Architecture AD-1 / AD-5 要求普通玩家写入必须通过 pending、confirmation、validation 和 commit，且 Story 必须附带 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。

### 当前实现状态

- `examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 已是 Story 2.6 使用的稳定对照：语言、初始地点、capability/content shape、relationship 和 clock 内容不同，但两者均声明 `query` 与 `rest_time`。
- `tests/test_cross_campaign_model_smoke.py` 已证明 Campaign/Save ownership、ContentRegistry、Entity/Relationship/Progress access、schema sameness 与写入隔离；Story 3.7 应建立正交的 context/player-safe integration gate，不重写 model contract 全集。
- `GMRuntime.start_turn()` 和 `query("context")` 消费同一 `build_context()` / `ContextBuildResult`；`query("scene")` 在 player view 使用同一 visibility/redaction 边界。
- `SaveManager.player_turn()` 会清理旧 pending，调用 `GMRuntime.act(view="player")`，只在 ready result 时写 pending action；`player_confirm()` 验证 save/session/identity/expiry，将 `TurnProposal.human_confirmed` 置为 true，再调用 `GMRuntime.commit_turn()`。
- `GMRuntime.validate_delta()` 使用 `player_turn_commit` profile，可作为 validation-only no-write evidence；真正普通玩家 commit 仍只能由 `player_confirm()` 驱动。
- `tests/helpers.py::tree_digest` 已提供稳定目录 fingerprint；前序 model smoke 中的极端 registry/schema 防护无需在新文件复制，但 Story 3.7 仍必须对自己的 formal current Save no-mutation 做直接断言。

### 前序故事情报

- Story 3.1 固化 `ContextBuildResult` 和 opt-in context audit。
- Story 3.2 / 3.3 固化 player-safe context/query/prompt 与派生 read-model hidden boundary。
- Story 3.4 把 relationship/progress/plot signals 纳入 context，并为 omission 提供结构化证据。
- Story 3.5 固化 memory provenance/freshness、projection generation/CAS 和 stable snapshot。
- Story 3.6 增加 budget decisions、quality diagnostics、high-value missing signals 与 context audit token evidence。其最终证据记录：`uv.lock`、external-intent investigation 与 2026-07-10 Correct Course planning artifacts 属于 Story 4.1，本 story 必须保持它们未跟踪/未纳入提交。
- 最近 5 个 story commit 都采用 focused RED/GREEN、三路 review、patch 后重跑门禁，并将 story/sprint 同步后单独提交。本 story 沿用该模式。

### 架构合规要求

- 风险级别：P0-adjacent integration / hidden / player-confirmation boundary regression；已有 PRD、Architecture、Epic/Story planning，实现以 tests/docs 为主，不改 production behavior。
- `data/game.sqlite` 仍是 current fact authority；context result/audit/diagnostics、registry、pending 和 projection health 仍只是 contract/evidence/entry/derived state。
- hidden filtering 必须在 collection/query 阶段完成，最终 redaction 仅作 defense-in-depth；跨 Campaign 测试必须检查 raw structured result，不只检查可读文本。
- 不修改 `SaveManager`、`GMRuntime`、context collectors、visibility、validation/commit、schema/migration、Campaign 内容或 public surface；若 RED test 暴露真实 production 缺口，先将其按明确 `[Review][Patch]` 或 workflow blocker 分类，不进行无证据的大重构。
- 不新增运行时依赖、campaign-specific context helper、custom commit chain、第二个 Context Slice model 或 test-only production API。
- 所有写入只能发生在 temporary Save；不直接修改 source examples、formal current Campaign/Save、workspace registry 或 `data/game.sqlite`。

### 预计文件

- NEW `tests/test_cross_campaign_context_smoke.py`：两个 Campaign 的 ContextBuildResult/basic query/preview/validation/player pending-confirm-commit 集成 smoke 与安全 stage report。
- UPDATE `docs/data-models.md`：将 Story 3.7 从“后续”改为当前 cross-campaign context/player-safe integration contract。
- UPDATE `docs/save-and-campaign-packages.md`：记录 temporary workspace 上的跨 Campaign pending/confirm 与 no-mutation 证据。
- UPDATE `docs/testing-and-quality-gates.md`：新增 Story 3.7 focused gate 和适用边界。
- UPDATE `_bmad-output/implementation-artifacts/3-7-跨-campaign-的-context-与玩家安全回路集成冒烟测试.md` 与 `sprint-status.yaml`：记录 implementation/review/gates 并同步状态。
- NEW `_bmad-output/implementation-artifacts/3-7-跨-campaign-的-context-与玩家安全回路集成冒烟测试.validation-report.md`：Validate Story 证据。
- 不计划修改 production Python、schemas、migrations、examples、CLI/MCP/prompt 合同或 Story 4.1 规划产物。

### 测试要求

首选 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_cross_campaign_context_smoke.py \
  -p no:cacheprovider
```

相邻 context / player-safe / model regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_cross_campaign_model_smoke.py \
  tests/test_context_quality.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_validation_pipeline.py \
  tests/test_current_native_context.py \
  tests/test_current_native_visibility.py \
  -p no:cacheprovider
```

Campaign CLI smoke：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
```

最终仍运行 repository full suite、Markdown links（`docs` 与本 story/validation report）、`py_compile` 覆盖新测试、`python3 -m ruff check .` 和 `git diff --check`。任何 review patch 落地后，更早 full-suite 证据失效，必须重跑。

### 残余风险与明确非目标

- Hidden/export/AI egress：本 story 只验证两个 canonical example 的 player context/query 集成边界；Story 3.2-3.6 仍为极端 hidden/non-oracle/memory/diagnostics 真值门禁。
- Pending/concurrency：覆盖单个 active Save 的 session mismatch 和正确 confirm，不扩大到多进程 platform concurrency 或 pending expiry 全组合。
- 不测试 resident AI、external intent candidate、preflight cache、MCP profile、platform sidecar、proposal queue 或 Story 4.x 的 authority decision。
- 不要求两个 Campaign 拥有相同的 loaded content、文本或预算数值；只要求共享 contract shape、pipeline、visibility 和 player-safe stage。
- 不修改 Campaign Package content 来让测试通过；若其中一个 package 缺失已声明的基础能力，必须在 review 中明确分类。

### 最新技术信息

无需外部 Web research。本 story 只使用仓库已固定的 Python 3.11+、stdlib `tempfile` / `sqlite3`、pytest/unittest 兼容测试、`SaveManager`、`GMRuntime`、`ContextBuildResult` 和现有 canonical example packages；不新增或升级依赖。

## Project Structure Notes

- 新的 focused integration test 放在 `tests/`，与 `test_cross_campaign_model_smoke.py`、`test_runtime.py`、`test_save_manager.py` 并列；不在 `rpg_engine/` 中增加为测试服务的编排层。
- 测试使用各 Campaign 已声明的 query/rest 能力和现有 hidden canary；不修改 example content 或伪造 campaign-specific schema。
- assertion report 只保留安全 label/stage/source/view，不将 hidden canary 正文打印到失败输出。
- canonical docs 仅记录已有 contract 的跨 Campaign 证据，不声称新的 runtime API 或 authority。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/2-6-跨-campaign-的模型边界冒烟测试.md`
- `_bmad-output/implementation-artifacts/3-6-context-budget-and-quality-diagnostics.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/architecture.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/context_builder.py`
- `rpg_engine/runtime.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/validation_pipeline.py`
- `tests/helpers.py`
- `tests/test_cross_campaign_model_smoke.py`
- `tests/test_context_quality.py`
- `tests/test_runtime.py`
- `tests/test_save_manager.py`
- `tests/test_validation_pipeline.py`
- `tests/test_current_native_context.py`
- `tests/test_current_native_visibility.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Debug Log References

- RED：`PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_cross_campaign_context_smoke.py -p no:cacheprovider` 按预期因文件不存在失败。
- GREEN / final focused：`1 passed, 2 subtests passed in 1.59s`。
- Adjacent context/player-safe/model regression：`171 passed, 9017 subtests passed in 263.43s`。
- Campaign CLI smoke：`v1_minimal_adventure` 与 `small_cn_campaign` 的 validate/test 全部 `OK`。
- Docs/static：`checked 88 markdown files; local links ok`；`py_compile`、focused Ruff 和 `git diff --check` 通过。
- Pre-review repository full suite：`771 passed, 9637 subtests passed in 481.07s`。
- First three-way review：`0 decision-needed / 12 patch / 0 defer / 10 dismiss`；12 项明确 patch 已全部应用，focused 复验 `1 passed, 2 subtests passed`。
- Second three-way review：`0 decision-needed / 8 patch / 0 defer / 2 dismiss`；依 `AGENTS.md` 二次复审规则，8 项新 patch 已写入 Review Findings，workflow 在应用前停止。
- Continued review action：用户明确要求继续后已应用第二轮全部 8 项 patch；focused 复验 `1 passed, 2 subtests passed in 2.17s`，Ruff、`py_compile` 与 `git diff --check` 通过。
- Third three-way review：`0 decision-needed / 4 patch / 0 defer / 6 dismiss`；Blind、fresh replacement Edge 与 Acceptance 三层均返回可解析结果，4 项新 patch 已写入 Review Findings，依 `AGENTS.md` 规则在应用前再次停止。
- Continued convergence action：用户再次明确继续后已应用第三轮全部 4 项 patch；focused 复验 `1 passed, 2 subtests passed in 2.06s`，Ruff、`py_compile` 与 `git diff --check` 通过。
- Fourth three-way review：`0 decision-needed / 5 patch / 0 defer / 4 dismiss`；Blind、Edge 与 Acceptance 三层均成功，5 项新 patch 已写入 Review Findings，依 `AGENTS.md` 规则在应用前停止。
- Continuous-auto action：用户明确授权除 decision-needed 外持续自动后，已应用第四轮全部 5 项 patch；focused 复验 `1 passed, 2 subtests passed in 2.07s`，Ruff、`py_compile` 与 `git diff --check` 通过。
- Fifth three-way review：`0 decision-needed / 7 patch / 0 defer / 2 dismiss`；三层结果可解析，7 项新 patch 已写入 Review Findings，按用户持续自动授权直接应用。
- Fifth review action：7 项 patch 已全部应用；focused 复验 `1 passed, 2 subtests passed in 2.05s`，Ruff、`py_compile` 与 `git diff --check` 通过，自动继续下一轮收敛复审。
- Sixth three-way review：`0 decision-needed / 2 patch / 0 defer / 0 dismiss`；Blind 与 Acceptance clean，Edge 识别 2 项可复现边界，按持续自动授权直接应用。
- Sixth review action：2 项 patch 已全部应用；focused 复验 `1 passed, 2 subtests passed in 1.92s`，Ruff、`py_compile` 与 `git diff --check` 通过。
- Seventh three-way convergence review：`0 decision-needed / 0 patch / 0 defer / 0 dismiss`；Blind、Edge 与 Acceptance 全部 clean，无 failed layer，Story 与 sprint 同步为 `done`。
- Final post-review gates：focused `1 passed, 2 subtests passed in 1.89s`；adjacent `171 passed, 9017 subtests passed in 287.44s`；两个 Campaign validate/test 全部 `OK`；Markdown `checked 170 markdown files; local links ok`；`py_compile`、full Ruff 与 `git diff --check` 通过；repository full suite `771 passed, 9637 subtests passed in 539.70s`。

### Completion Notes List

- 新增两个 canonical example Campaign 的独立 temporary-workspace integration smoke，证明两者复用同一 `ContextBuildResult` pipeline/collectors 和 relationship/progress/world-setting context sources。
- 对 player-safe structured result、query 和 scene output 检查各 Campaign 的 hidden id/name/summary/alias canary，并禁止 raw hidden omission evidence。
- 证明 query/context/preview/validation/pending 都不修改 authoritative facts，错误 session 被拒绝，只有正确 `player_confirm` 会经 validation/commit 增加 turn/event。
- 测试失败 evidence 仅包含安全的 campaign/save/stage/context-source/visibility-mode；source Campaign、temporary Campaign copy 与 configured formal current Save fingerprint 前后一致。
- 本 story 只新增 regression test 并同步 canonical docs，未修改 production Python、schema、migration、example content 或 public CLI/MCP/prompt 语义，因此无需更新 `docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`。

### File List

- `_bmad-output/implementation-artifacts/3-7-跨-campaign-的-context-与玩家安全回路集成冒烟测试.md`
- `_bmad-output/implementation-artifacts/3-7-跨-campaign-的-context-与玩家安全回路集成冒烟测试.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `docs/testing-and-quality-gates.md`
- `tests/test_cross_campaign_context_smoke.py`

### Implementation Plan

- 先运行不存在的 focused test 获得 RED。
- 新增两个 Campaign 共享的 context/query/preview/validation/pending-confirm-commit 集成 smoke，并保留 no-mutation/stage-report 证据。
- 同步 canonical docs，运行 focused/adjacent/full/static gates。
- 执行三路 code review，自动修复所有明确 patch，复审后同步 story/sprint。

### Change Log

- 2026-07-10: Created Story 3.7 cross-campaign Context and player-safe loop integration smoke with comprehensive implementation guardrails; status set to ready-for-dev.
- 2026-07-10: Implemented cross-campaign ContextBuildResult, hidden, query/preview/validation no-write, pending-confirm-commit, safe stage-report and no-mutation integration evidence; synchronized canonical docs and set status to review.
- 2026-07-10: First three-way code review triaged 0 decisions, 12 patches, 0 defers and 10 dismissals; applied every patch and kept status at review pending mandatory second review.
- 2026-07-10: Second three-way code review triaged 0 decisions, 8 patches, 0 defers and 2 dismissals; persisted the new patch findings and halted as required before any further patch cycle.
- 2026-07-11: Applied all 8 second-review patches after explicit continuation, passed focused/static verification and kept status at review pending a fresh convergence review.
- 2026-07-11: Third three-way review triaged 0 decisions, 4 patches, 0 defers and 6 dismissals; persisted the new patch findings and halted before another patch cycle as required.
- 2026-07-11: Applied all 4 third-review patches after explicit continuation, passed focused/static verification and kept status at review pending the next clean convergence review.
- 2026-07-11: Fourth three-way review triaged 0 decisions, 5 patches, 0 defers and 4 dismissals; persisted the new patch findings and halted before another patch cycle as required.
- 2026-07-11: Applied all 5 fourth-review patches under explicit continuous-auto authorization, passed focused/static verification and continued directly to convergence review.
- 2026-07-11: Fifth three-way review triaged 0 decisions, 7 patches, 0 defers and 2 dismissals; continued automatically into patch handling under explicit authorization.
- 2026-07-11: Applied all 7 fifth-review patches, passed focused/static verification and continued automatically toward clean review.
- 2026-07-11: Sixth three-way review triaged 0 decisions, 2 patches, 0 defers and 0 dismissals; continued automatically into patch handling.
- 2026-07-11: Applied both sixth-review patches, passed focused/static verification and continued automatically toward clean review.
- 2026-07-11: Seventh three-way convergence review was clean across Blind, Edge and Acceptance; marked Story 3.7 done and synchronized Epic 3 completion.
- 2026-07-11: Passed all final post-review focused, adjacent, Campaign CLI, docs/static and repository full-suite gates; Story 3.7 is ready to commit and push.
