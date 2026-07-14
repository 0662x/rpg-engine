# 测试与质量门禁

文档状态：**CURRENT：BMAD canonical testing and quality gates**

## 基线命令

使用 `python3`：

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m coverage run -m pytest -q
python3 -m coverage report
```

文档-only 变更至少执行：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

如果修改 `_bmad-output/project-scan-report.json`，还要执行：

```bash
python3 -m json.tool _bmad-output/project-scan-report.json >/dev/null
```

## 测试层级

- Unit / white-box：覆盖小型合约和分支逻辑，例如 intent classification、response acceptance、
  content type registration、validation profiles、schema helpers。
- Integration / gray-box：检查数据库副作用、write guard、projection state、context audit rows、
  package import/export、rollback 行为。
- System / black-box：通过 CLI 或 `GMRuntime` 对真实 package 或打包示例跑流程，包括 current
  native read-only query、temp copy 上的 preview/commit、export/import round trip、projection repair。

## 常用目标

全量测试：

```bash
python3 -m pytest
```

Round 7 本地基线（2026-07-04）：`python3 -m pytest -q` 通过，`450 passed, 483 subtests passed`。

当前 native campaign/save 回归：

```bash
python3 -m pytest tests/test_current_native_*.py tests/test_cross_layer_regression.py
```

Context contract / audit gate：

```bash
python3 -m pytest -q tests/test_context_quality.py tests/test_current_native_context.py tests/test_runtime.py
```

该 gate 适用于触碰 `ContextBuildResult`、context collectors、budget / omission evidence、
`context_runs` / `context_items` audit、`GMRuntime.query("context")`、CLI `context build` 或 prompt/render
context 消费路径的变更。新增 context source 必须声明 visibility、provenance 和 budget behavior，并证明
player-safe view 下不会通过新增 evidence 字段泄露 hidden / GM-only 内容。
Relationship、progress/clock 或 plot progression signal context 变更还应覆盖
`tests/test_relationship_access.py`、`tests/test_progress_access.py` 和 current-native context/audit regression。
测试需要证明 included item evidence、budget omission、player-safe hidden-count non-disclosure、
GM / maintenance sanitized omission categories、context audit rows 和 `advisory_only` plot signal authority
都可检查，且 plot signals 不变成 facts、clock ticks、proposal approval 或 mandatory storylets，也不会引用
budget-omitted relationship / progress source。

Story 3.6 context budget / quality diagnostics 的可复现 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_context_quality.py \
  tests/test_current_native_context.py \
  tests/test_current_native_visibility.py \
  tests/test_relationship_access.py \
  tests/test_progress_access.py \
  -p no:cacheprovider
```

该 gate 必须覆盖 section decisions、required overflow、最多 8 条 high-value missing signals、最多 32 条
quality warnings、unavailable sentinel 上限保留、canonical alias 批量查询、relationship/progress/memory 结构缺口、audit token rows，以及
context audit TEMP-shadow 防护与 hidden-only/absent non-oracle。Story 3.5 compatibility evidence 另运行
`tests/test_maintenance_tooling_coverage.py tests/test_projection_service.py tests/test_runtime.py`；diagnostics patch、
review patch 或文档后仍需重跑 repository full suite、canonical campaigns、Markdown links 与静态 gates。

Player-safe context / query / prompt hidden-boundary 变更还应覆盖 `tests/test_current_native_visibility.py`。
测试需要证明 hidden entities、relationships、world settings、discovery states、memory summaries、events、
scene output、ordinary query 和 player-safe helper prompt 输入都不会泄露 hidden material；trusted
GM / maintenance view 应保留 explicit hidden read 能力，并证明 `gm -> player` 或 `maintenance -> player`
的连续 context/audit 构建不会复用 hidden 内容。Events 目前没有独立 visibility 字段；memory summaries
携带 `visibility_mode` metadata，但 hidden / GM-only 内容仍必须通过 hidden entity refs 或明确 visibility
metadata 被 player collection 跳过。测试应覆盖含 hidden refs 的 rows 不会因 SQL top-N filtering 饿死后续
safe recall，并检查 `ContextBuildResult.contract.visibility_invariants` 记录 event not-applicable 与
memory visibility metadata 证据。

Long-term memory summary 变更还必须覆盖 schema migration / helper backfill、source turn/event
provenance、summary type、visibility mode、freshness/staleness metadata、derived authority evidence、
stale summary omission、authoritative SQLite facts precedence，以及 resident AI / memory projection 不可用时的
recent-events 或 lower-quality fallback。相关 focused tests 应至少覆盖
`tests/test_maintenance_tooling_coverage.py`、`tests/test_context_quality.py`、
`tests/test_current_native_context.py` 和 `tests/test_current_native_visibility.py`。
高风险回归还应覆盖 partial/incompatible schema、projection version/migration freshness 与 turn alignment、
future/incomparable turns、unresolved/oversized provenance ids、deep/corrupt metadata JSON、hidden-only existence
oracle、player row/report metadata sanitization，以及 non-clean projection 的 bounded-query fast fallback。还要覆盖
missing memory state 默认 dirty、无害 additive projection columns、非有限 version、same-turn fact maintenance
dirty、source-turn hidden locations、expired/reversed validity windows、projection snapshot TOCTOU 与 provenance
reference/query bounds。Generation/CAS 回归还必须覆盖 same-turn dirty overwrite、clean/dirty/clean ABA、
all-view BLOB rows、复合主键、阻塞 canonical writes 的 required extensions、NOCASE projection aliases、
trusted-marker subject 一致性，以及 future validity bounds 与 freshness provenance 的解耦。最终 gate 还必须覆盖
apply-budget 后的真实双连接 generation 变化、memory-derived plot signal 清除、post-refresh effective health
对账、bound-only freshness 拒绝、Unicode 伪同名列、非 canonical UNIQUE / generated / FK / CHECK / trigger
约束、最大 timestamp 经 UnitOfWork/save path 不阻断事实提交，以及 maintenance trusted row 的动态类型合同。
还要覆盖 commented `CHECK`、TEMP trigger、可执行 defaults、非 UNIQUE expression/partial index、required-extension
status diagnostics、direct rebuild report failure、失去 owner 的 failed refresh、大小写 alias 的 machine-readable
状态、连续 generation thrash 的 generic fallback，以及 budget retry 不丢失非 memory plot signals。Review 后的
最终回归还必须覆盖 `0009` TEMP shadow、write-blocking existing columns、严格 JSON boolean default、大小写
main/TEMP trigger、canonical FK action/index、bound-scalar-only freshness、direct player render/id/omission 脱敏、
同 target publication serialization、TEMP projection/outbox aliases、metadata savepoint rollback ownership、零行
failed update、最终 report health 对账，以及 omission evidence 与 generation snapshot 的双连接绑定。
关闭 Story 前还必须覆盖：fresh empty DB 的完整 `0001..0009` chain、late-column migration rollback、helper
table/index atomicity、TEMP migration ledger/statement targets、exact authority/non-finite JSON、validity-bound exact match、
total row-scan cap、hidden name/alias in legal memory IDs、report TEMP/snapshot publication、缺失 outbox 时的 memory dirty、
self-owned metadata transaction commit、empty-name no-op、invalid projection name/status、lock timeout、真实跨进程 target
serialization、真实双连接 generation loss、TEMP outbox processing、clean-empty fallback，以及 memory unavailable 时仍保留
authoritative recent-events/lower-quality context。

Story 3.5 的可复现 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_maintenance_tooling_coverage.py \
  tests/test_projection_service.py \
  tests/test_context_quality.py \
  tests/test_current_native_context.py \
  tests/test_current_native_visibility.py \
  tests/test_current_native_package.py \
  -p no:cacheprovider
```

该 focused gate 通过后仍必须执行 repository full suite；后续补丁会使更早的 full-suite 证据失效。

Derived player artifact hidden-boundary 变更也必须覆盖 `tests/test_current_native_visibility.py` 和
`tests/test_projection_service.py`。测试需要证明 FTS/search、snapshots/current.md、
snapshots/current.json、cards/INDEX.md、generated cards、scene JSON 和 start/continue onboarding
不会输出 hidden / GM-only token、id、alias、summary 或详情；隐藏当前位置只能变成玩家安全占位。

写入安全和 validation cluster：

```bash
python3 -m pytest \
  tests/test_cross_layer_regression.py \
  tests/test_validation_pipeline.py \
  tests/test_projection_service.py \
  tests/test_save_manager.py
```

AI intent / platform / SaveManager 高风险 cluster：

```bash
python3 -m pytest -q \
  tests/test_ai_intent.py \
  tests/test_runtime.py \
  tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py \
  tests/test_platform_sidecar.py \
  tests/test_save_manager.py \
  tests/test_v1_cli.py \
  tests/test_current_native_context.py \
  tests/test_context_quality.py
```

Preflight boundary 变更还必须覆盖 provider/model/backend/fallback 逐字段 mismatch、分隔符碰撞拒绝、
`message_only` 缺 platform/session/message 时在 cache 写入与 helper 调用前失败、NFKC/trim text hash 不可伪造、
active action taxonomy digest 或 action slot projection digest 不同的 default/custom registry 不得复用
cached internal review，low-level preflight identity 缺少 slot digest 时必须 fail closed、
双连接并发消费只有一个 hit 且其他连接观察 `used`，以及 late reject/expire 不能覆盖 used。公开
preflight/player/prewarm evidence 不得包含 raw session key、raw prompt、helper audit/provider body 或 hidden token。

Resident AI Advisory Envelope contract 的 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_resident_ai_advisory.py \
  tests/test_ai_helper.py \
  tests/test_current_native_visibility.py \
  -p no:cacheprovider
```

该 gate 必须覆盖 strict required/unknown fields、五类 advisory type、finite confidence、freshness、
schema/authority const、深度不可变与 defensive copies；jsonschema 前必须有有界 structural budget、cycle
detection 和 Unicode-canonical authority-key rejection。Player projection 必须分别以 SQLite/access contract
验证 target/evidence，hidden/archived/absent/unsupported/query failure 使用同一个 generic unavailable，且
private reasoning、hidden token/id/alias、raw delta/proposal、provider body 与 raw prompt 不进入结果。
No-mutation 测试还必须证明 helper 不写 facts/events/turn，不 commit/rollback/close caller connection，也不改变
caller transaction ownership。该 Story 不新增 adapter、storage、queue、Coordinator 或 CLI/MCP surface；相邻
回归需覆盖 AI intent mode matrix、preflight CAS、platform pending/confirm、surface profile 与 current-native write safety。
Contract gate 还必须覆盖直接构造 dataclass 的 revalidation、schema 最大合法 payload 与 structural budgets 一致、
JSON-safe integer 上界、重复 evidence、canonical target/reference ids、脱敏 schema error，以及 relationship/clock
被伪装成 generic entity evidence 时仍按实际 subtype access contract 过滤。Redaction 后输出 shape 有任何变化均
必须收敛为 generic unavailable。
最大 payload 测试必须同时覆盖 collection count 与 schema 最大字符串长度；duplicate evidence/provenance、
canonical prefixed references、forged authority 以及 structural unknown-key path 脱敏也属于 required focused gate。
Focused tests 还必须拒绝 stateful container subclasses、hostile iterables、`1/0` authority、integral float turn id、
kind/prefix mismatch 与 malformed colon references，并证明无关 hidden 文本不会因固定 projection key 碰撞造成
全局 unavailable，redaction 后 bool/int 等 wire type 变化仍会 fail closed。
还必须覆盖 hostile scalar subclasses、明确 runtime target namespaces、authority capability 同义变体、validator
exception cause 脱敏、跨 kind duplicate refs、archived omission，以及 visible relationship/progress/world/rule
evidence 的正向分支。Defense redaction 只扫描 reference leaf values，不扫描协议容器 key。
Hostile mapping-key subclasses、`runtime:` control-plane targets、单引用 read failure 的局部 omission，以及 player
serializer 每次只执行一次 strict schema validation 也必须有 focused 断言。
Caller mutation snapshot、malformed `rel:`/`clock:` storage type、nested-colon clock ids 与 in-place redactor
mutation 也属于 focused regression matrix。
Safe provenance namespace、nested bare authority nouns、conflicting `clock:`/relationship storage type 与 snapshot
前 structural traversal mutation 的脱敏失败必须有 focused regression。
Progress clock 完整 ID pattern、candidate/prompt/hidden target 拒绝、malformed rule/world prefix 与 revalidation
后原对象 mutation 不影响 canonical player snapshot，均属于 focused regression。

Resident AI representative adapters 的 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_resident_ai_advisory_adapters.py \
  tests/test_resident_ai_advisory.py \
  tests/test_ai_intent.py \
  tests/test_validation_pipeline.py \
  tests/test_maintenance_tooling_coverage.py \
  -p no:cacheprovider
```

该 gate 必须覆盖 `intent_recognition` 与 `progress_management` 两种 mapping、exact source/authority flags、
normal `None` 与 malformed `ValueError` 矩阵、first-seen typed references、confidence/unknown-freshness、canonical
digest、payload exclusion 与 source immutability。Intent owner integration 只能在 Kernel decision/binding 完成后
生成 optional object，且 adapter 三类异常不能改变 trace/decision/outcome/guards；temporary Save 的 player
serializer 必须继续 omission hidden/archived/missing refs，并排除 confidence/freshness/source/provenance。

State Audit owner integration 必须 all-or-none 提取 clock ids，只允许 maintenance profiles 的 stage artifacts，
并证明 preview/player/response/unknown profile omission。Adapter success/failure 都不得改变 audit/status/issues、
ValidationReport ok 或 commit eligibility；不得新增 provider call、SQLite write、proposal/queue transition、public
renderer 或 CLI/MCP surface。Adjacent regression继续覆盖 preflight CAS、AI helper、runtime、SaveManager、platform、
surface inventory 与 current-native visibility/write safety，所有写测试使用 temporary Save。

Resident AI advisory review intake 的 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_resident_ai_advisory_review.py \
  tests/test_resident_ai_advisory_adapters.py \
  tests/test_resident_ai_advisory.py \
  tests/test_entity_access.py \
  tests/test_relationship_access.py \
  tests/test_progress_access.py \
  tests/test_validation_pipeline.py \
  tests/test_palette_governance.py \
  -p no:cacheprovider
```

该 gate 必须区分 entity/relationship create 与 update existence/currentness，覆盖 alias、memory summary、progress
definition 的 no-owner 状态与 clock tick structured preflight；还要覆盖 exact types、bounded deep snapshot、source
mutation/TOCTOU、direct dataclass forgery、authority smuggling、TEMP shadow、hidden/archived/missing non-oracle、
rejected/stale/superseded/conflict、defensive serialization 与全表 no-mutation。Intake/serializer 不得调用 proposal
queue、content/save apply、provider、validation/commit owner；application eligibility 不是 authorization，真正写入仍须
重新运行对应 validation/reference/visibility 与 commit/maintenance gate。Proposal queue lifecycle/report 属于后续
Story 5.7，不得在本 gate 中通过 production hook 或 queue integration 实现。

External intent manifest v4 / taxonomy v1 / safety v1 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_action_slot_contract.py \
  tests/test_intent_manifest.py \
  tests/test_action_taxonomy.py \
  tests/test_ai_intent.py \
  tests/test_ai_helper.py \
  tests/test_runtime.py \
  tests/test_context_quality.py \
  tests/test_current_native_context.py \
  tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py \
  tests/test_platform_sidecar.py \
  tests/test_save_manager.py \
  tests/test_v1_cli.py \
  tests/test_bug_report_regressions.py \
  tests/test_surface_inventory.py \
  tests/test_eval_suite.py \
  tests/test_mcp_transcript.py \
  tests/test_current_native_player_turn.py \
  -p no:cacheprovider
```

该 gate 必须覆盖 manifest v4/taxonomy v1/safety v1 canonical digest 与 schema parity、requirement-group
`cardinality` / `binding_rule` 投影及 digest 旋转、不同
`PYTHONHASHSEED` 的跨进程 taxonomy/slot/manifest wire 稳定性、taxonomy frozen/validation/collision/
registration-order/custom-locale projection、slot frozen/defensive-copy/exact-type/alias-group collision/
registration atomicity/legacy normalization、term/locale/priority/version 与 slot metadata digest 旋转、
exact/legacy envelope、old/new/wrong-digest rolling skew、
stale-before-unknown precedence、external
strict/internal tolerant 行为、所有 direct Runtime/SaveManager 入口 typed propagation，以及 MCP/V1/legacy CLI 的
固定脱敏投影。失败必须发生在 helper/route/preview/cache/new pending/fact write 前；contract evidence 只进入 bounded
trace，不能提升 authority。Slot gate 还必须逐 action 锁定 required/group cardinality、alias/type、custom/falsey
registry、confirmation/visibility/no-mutation，并以 `action.slot.field` 报告 parity 失败。Story 6.3 只关闭本仓
slot ownership/parity design debt；Hermes reconnect/next-model-turn/E2E 仍不由本 gate 代替。

Surface / intent 基线材料：

- `tests/fixtures/intent_router_gold_set.yaml`
- `tests/fixtures/mcp_external_agent_transcripts.yaml`
- `tests/test_surface_inventory.py` 校验 public / semi-public entry surface 的 canonical taxonomy、
  write authority、forbidden bypasses、MCP default profile、V1 CLI groups、runtime API、platform
  sidecar/prewarm 和 projection/outbox 覆盖。
- `docs/architecture/phase-0-performance-baseline.md` 是归档 stub；原始本机性能基线已随
  `phase-0-performance-baseline.md` 归档到 `docs/archive/pre-bmad-docs-2026-07-03/`。

Campaign smoke：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
```

跨 Campaign model-boundary smoke：

```bash
python3 -m pytest -q tests/test_cross_campaign_model_smoke.py
```

该 gate 适用于触碰 Campaign/Save ownership、Content Type / Merge、Entity、Relationship 或
Progress access contract 的 foundation 变更。它必须只写临时 Save Package，不能修改正式 current
save package 或 source Campaign Package。

跨 Campaign Context / player-safe loop smoke：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_cross_campaign_context_smoke.py \
  -p no:cacheprovider
```

该 gate 适用于触碰 `ContextBuildResult`、player visibility filtering、basic query、preview/validation
或 `SaveManager` pending/confirm 边界的 foundation 变更。它对
`examples/v1_minimal_adventure` 和 `examples/small_cn_campaign` 各创建独立 temporary
workspace/Save，并证明两者复用同一 context pipeline/collector contract 与
`player_turn -> pending -> player_confirm -> validation/commit` 链。失败 evidence 必须指出安全的
campaign、temporary save、context source、visibility mode 和 player-safe stage，不得回显 hidden
正文或 raw player payload。测试必须证明 query/preview/validation/pending 不写 facts，错误
session 被拒绝，只有正确 confirm 提交，且 source Campaign 与 configured formal current
Save（包括 workspace registry 中的 Save）的 fingerprint 不变，且这些 postcondition 在早期失败时仍执行。
该 context integration gate 与 model-boundary smoke 正交，两者不能
互相代替。

慢测试观察：

```bash
python3 -m pytest --durations=20 -q
```

覆盖率：

```bash
python3 -m coverage erase
python3 -m coverage run -m pytest -q
python3 -m coverage combine
python3 -m coverage report --sort=cover
```

## Current Native Packages

默认 current native 回归路径：

- Campaign package：`/Users/oliver/.hermes/rp/isekai-farm-campaign-native-v1`
- Save package：`/Users/oliver/.hermes/rp/isekai-farm-save-native-v1`

可用环境变量覆盖：

```bash
RPG_ENGINE_CURRENT_CAMPAIGN_ROOT=/path/to/campaign \
RPG_ENGINE_CURRENT_SAVE_ROOT=/path/to/save \
python3 -m pytest tests/test_current_native_*.py
```

测试不得修改正式 current save package。会写入的测试必须先复制 campaign/save 到临时目录，
通常使用 [`../tests/helpers.py`](../tests/helpers.py) 中的 helper。

## Current Native 回归分组

- `tests/test_current_native_package.py`：package manifests、validation、migration health、author/save 边界。
- `tests/test_current_native_context.py`：read-only scene/entity queries、context routing、recall budgets、audit rows。
- `tests/test_current_native_actions.py`：preview contracts、delta guards、blocked action behavior。
- `tests/test_current_native_write_safety.py`：commit guards、rollback、export/import、projection repair on temp copies。
- `tests/test_current_native_visibility.py`：hidden / GM-only 内容泄漏检查。

## Helper 约定

共享测试脚手架位于 [`../tests/helpers.py`](../tests/helpers.py)。

优先复用：

- `run_cli(...)`
- `load_stdout_json(...)`
- `query_scalar(...)` / `query_int(...)`
- `current_turn(...)` / `current_location(...)`
- `copy_initialized_minimal(...)`
- `copy_current_packages(...)`

断言应留在测试文件中。helper 应保持朴素：路径、临时 fixture、CLI subprocess 和简单
SQLite 读取。

## BMAD 风险门禁

高风险 intent / platform / SaveManager 改动合入前必须回答：

- external AI 是否仍只是 low-trust candidate？
- internal AI 是否仍不能 preview / validate / confirm / commit？
- preflight cache 是否仍是 advisory、single-use、identity-bound？
- `message_only` preflight 是否仍不带 external candidate？
- `player_turn` 是否仍不提交事实？
- `player_confirm` 是否仍是 commit gate？
- MCP player profile 是否仍不能调用低层工具？
- platform sidecar 是否仍只 gate / forward passive identity？

如果答案不清楚，不能合入。

## 残余风险 Backlog

Round 4B 已把旧长评审中仍有效的后续风险摘到
[`../_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`](../_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md)。

当前重点追踪：

- hidden / export / AI egress 专项加固。
- backup / restore / archive 故障注入。
- skipped tests 豁免清单和按模块 coverage 增长。
- eval report 版本化与历史趋势对比。
- declarative action spec 的第二个非 random 示例。
- pending action session / concurrency 语义。
- TurnCoordinator 不得回退 player workflow、profile gate、atomic write 和 eval metrics。

## CI 对齐

CI 当前执行：

- Python 3.11 / 3.12 matrix。
- `python -m pytest -q`
- `python -m ruff check .`
- `python -m coverage run -m pytest -q`
- `python -m coverage report`
- installed CLI V1 smoke。
- package build。
- `python -m twine check dist/*`

本地变更不一定每次都要跑全量 CI，但最终说明必须记录已跑命令和未跑原因。
