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

Routine 结构化库存消耗的 P0 gate：

```bash
python3 -m pytest -q \
  tests/test_routine_consumption_validation.py \
  tests/test_routine_consumption_save_manager.py \
  tests/test_current_native_consumption_craft_deltas.py
```

该 gate 必须覆盖合法精确扣量、after 最多 1 ULP / 实际扣量最多 2 ULP 算术、stale/insufficient/malformed/item mismatch、metadata 与
aliases 保留、额外库存 upsert 拒绝、validator 输入不变性，以及
`player_turn -> pending -> player_confirm -> receipt replay`。失败确认必须恢复原 pending、清除新 claim
anchor，并保持 SQLite 逻辑事实、库存、turn/event 与 JSONL 不变；replay 必须证明不重入 validation/commit。
所有写入只允许发生在 temporary Save，source Campaign、formal current Save 与正式 registry 必须保持不变。

Gather Intake 语义提交的 P0 gate：

```bash
python3 -m pytest -q \
  tests/test_gather_intake_validation.py \
  tests/test_gather_intake_commit.py \
  tests/test_current_native_consumption_craft_deltas.py \
  tests/test_routine_consumption_validation.py \
  tests/test_routine_consumption_save_manager.py \
  tests/test_palette_governance.py \
  tests/test_maintenance_tooling_coverage.py::ActionResolverCombinationCoverageTests::test_combat_resolver_ready_blocked_and_delta_validation_paths
```

该 gate 必须覆盖 direct output trigger、unique event/upsert、finite-positive quantity、owner/location
exact-ID 与 retired 拒绝、payload/upsert ID/quantity/unit/ownership 对齐、existing-item metadata/aliases
保留，以及真实 `GMRuntime.commit_turn` 和 `SaveManager.player_confirm`。非法输入必须证明 SQLite 事实、
库存、turn/event、JSONL、pending action/clarification、claim/receipt 与 backup 最终不变；合法玩家确认只新增
或更新一个预期 item，并精确新增一个 turn/event。相邻 positive controls 必须继续覆盖 routine consumption、
craft、combat、普通 gather draft marker 与 palette gather validation。所有写测试只使用独立 temporary Save；
现有 Iteration 3 rebaseline fixtures 只作为其所属 rebaseline 工作树中的额外 acceptance evidence；上述
canonical gate 在 Story-only clean checkout 中必须完全由 tracked tests 自包含，不得依赖未提交 helper。

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

Story 6.8 Hermes stdio provider compatibility focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_hermes_stdio_compatibility.py \
  tests/test_mcp_adapter.py \
  tests/test_intent_manifest.py \
  tests/test_ai_intent.py \
  -p no:cacheprovider
```

该gate必须通过官方MCP Python SDK的`stdio_client`/`ClientSession`启动真实
`python -m rpg_engine mcp serve` subprocess；FakeFastMCP、adapter直调、in-memory transport或静态transcript
不能替代。必须精确断言player profile工具清单和low-level缺席、manifest schema/digest与safety identity、stale
typed rejection、第二次manifest后的whole-candidate regeneration、`player_turn` pending-only、wrong-session
no-mutation、显式`player_confirm`精确+1 turn/+1 event及replay无第二次写入。

夹具必须在独立empty temporary workspace复制Campaign、建立registry active Save，并以20秒内的bounded client
lifecycle可靠teardown。SQLite counts/current turn、events.jsonl、pending/receipt与audit必须同时作为oracle；source
minimal Campaign始终fingerprint，SQLite还必须使用全表logical digest捕获不改变count的meta/entity写入；环境中存在或
显式配置的formal current Campaign/Save、正式registry/SQLite/player data也必须前后fingerprint且不得与temporary
root形成samefile/父子/symlink别名。异常退出测试必须证明child已退出、temporary root可清理且正式指纹后置断言仍执行。
Subprocess cwd必须隔离于poison `.env`，builtin/io/`os.open` dotenv deny/log必须证明provider未读取；socket deny guard
必须以PID-bearing ready sentinel证明加载，并证明公开`socket`、`socket._socket`与新import/reload `_socket`/
`SocketType`的DNS、IPv4/IPv6 connect及UDP sendto均被
拒绝记录；正常provider transcript必须零尝试。该test-owned oracle证明CPython socket/DNS surface与实际provider路径，
不等同于OS级syscall/FFI网络沙箱。launcher必须以`PYTHONNOUSERSITE=1`禁用宿主user-site与
`usercustomize.py`；所有AI helper为off且不依赖`.env`内容/API key。

Audit必须只保留bounded tool/status/result evidence：raw candidate slot/reason/provider body、player text、private/
hidden canary、platform session key和pending confirmation session ID均不得出现；`session_key`/`session_id`只能是批准
SHA-256摘要。真实normal query还必须在temporary Campaign/Save含hidden与GM-only canary时证明player response、bounded
hook、audit和stderr均不泄露。YAML `schema_version=1`固定actor/tool/capture顺序、typed arguments、仅向后且非null的
capture reference、wrong-session step、load-time exact candidate generation、JSON type-strict bounded expectations与
allowlisted hooks；duplicate key、
未知schema字段、canonical override或raw session hook必须fail closed，scripted-model步骤不能产生
玩家确认authority。RPG Engine CI只拥有provider fixture/contract oracle；Hermes真实client、tool registration、
next-model-turn barrier、reconnect和combined release gate仍由Hermes CI持有，本gate不得复制或替代。

Retired/archived entity action binding的P0 gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_retired_entity_binding.py \
  tests/test_ai_intent.py \
  tests/test_action_slot_contract.py \
  tests/test_current_native_player_turn.py \
  -p no:cacheprovider
```

该gate必须覆盖当前temporary Save SQLite中的active-only action binding、canonical ID/name/alias与partial、
retired/archived/unknown/空status、NFKC/边缘空白归一化、active exact胜过同alias或non-active partial历史、无active exact时
visible non-active exact优先阻断、visible non-active partial与active partial冲突时fail-closed，以及
`entity_or_text` / `text_or_entity` visible non-active fallback和composite resolver的case/token/body/FTS二次解析阻断。
Composite canonical reference必须在SQL前经过NFKC/casefold并先于active partial；短alias不得在无关单词内部误伤literal，
短qualified ID不得把`-`/`:`延续的active长ID当作自身命中；任何多codepoint非Latin letter script的name/alias都必须覆盖连写自然短语，并锁定任意不同letter script与Latin name/alias相邻时的cross-script boundary而不放宽Latin单词内部；NFKD后Mn/Mc/Me与完整Default_Ignorable范围（含U+2065、U+FFF0、Plane 14）必须同时覆盖预组合/视觉等同canonical与单词内部continuation，单codepoint判定使用folding前identity且public control-character safety不得削弱，U+200B/U+2060
等edge whitespace必须保留active正向绑定，同时锁定共享resolver token/FTS与binder共用完整Default_Ignorable folding、不会从Hangul filler等分隔处重新制造短alias或FTS历史命中；按token顺序的首个exact winner必须决定active放行或non-active阻断，未命中时token partial/body/FTS每阶段任一non-active命中不得被同阶段active winner遮蔽，且归一化空输入不生成`LIKE '%%'`。未配对UTF-16 surrogate必须有direct/public no-pending回归。Supplementary Han与`.` dotted ID
必须有active/non-active冲突回归；normalized-empty hybrid必须missing，`text_or_entity` exact-only必须保留active composite
ID为literal，同时继续阻断visible non-active shadow。`%`、`_`、`!` 必须同时以
纯literal与真实entity文本锁定binder/shared resolver exact-token ID suffix及partial/body-query语义，并锁定partial过滤与排序CASE的ESCAPE一致性；active player-visible positive control保持可用。
Foreign、stale manifest、ambiguous与missing行为必须保持原contract。Hidden DB-only canary必须使用成对的
hidden-present/absent 同输入oracle（包含entity、clock及world-setting subtype visibility）：PLAYER_VIEW entity-only两者
均missing，hybrid两者均只作literal，不形成
entity binding、facts used或hidden projection。失败不得创建committable pending/claim/receipt或修改Save SQLite、turn/event、projection和
events.jsonl。`find_entity_candidates()` 的默认query consumer必须有回归证明binder-only lifecycle gate未把
共享query/read无条件改成active-only。测试不得依赖Iteration 3未提交rebaseline helper，所有写入只在独立
temporary Campaign/Save/workspace。

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

Player-safe structured query aggregation gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_player_safe_query_aggregation.py \
  -p no:cacheprovider
```

该 gate 适用于 `GMRuntime.query(..., structured=...)`、`rpg_engine.query_collection` 或共享
query visibility/scope filter 的变更。它必须在 self-contained temporary Saves 上覆盖 single/multiple/empty、
`all`/owner/location、mixed units、duplicate aliases、hidden/GM-only、retired/non-active、hidden-vs-absent
scope anchor paired oracle、invalid request、caller-owned transaction、current-native 完整 SQLite oracle与两个
canonical Campaign 的 current-Save isolation。

成员 `id/name/quantity/unit` 和按 exact unit 分组的 totals 必须与 visibility-safe active SQLite set
逐项一致；alias、名称或 fuzzy hit 不得扩增/缩减集合。Success、empty、invalid 和 visibility-excluded 路径
必须动态比较全部 `main` application table/schema、pending、registry、events JSONL、projection 与完整 Save tree，
并保持 source Campaign/formal current Save 不变。测试不得依赖未提交 Iteration 3 conftest/helper，也不得把
自然语言样例、Campaign 特例或测试编排放入 production API。普通 entity text query、scene/context、Story 3.7
cross-campaign loop 与 player-safe write/domain tests 是相邻回归，不能由本 focused gate替代。

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
- 两线程与两进程确认是否精确产生一个 fresh `committed` 和一个
  `already_confirmed/idempotent_replay=true`？
- SQLite commit 后、receipt/pending clear 前的进程退出是否能由 parent retry 收敛，且 lock 自动释放？
- SQLite commit 后、`UnitOfWork.finalize_artifacts()` 前的进程退出是否能以 dirty-only repair 收敛
  events outbox、snapshots、cards 与 stale registry，而不重复 clean work？
- `player_turn` 发布新 pending 与 in-flight confirm 交错时，新 session 是否仍存在；发布失败时旧 receipt
  是否恢复？
- replay identity/payload/receipt mismatch 是否 fail closed，backup、archivist、projection/outbox、registry
  与 platform `saved_count` 是否只在 fresh commit 执行/计数一次？
- receipt identity/payload/result 被修改并重算 workspace digest 后，是否仍因 SQLite anchor mismatch 被拒绝；
  low-level proposal 自报 `player_confirm` provenance 是否仍不能取得 replay success？
- fresh confirm 的 refresh 窗口切换 active save 是否仍写入首次 bound path；platform replay 是否保持既有
  binding TTL；若 fresh platform completion 从未落地，是否只凭匹配的 hashed confirmation correlation
  补做状态 transition，而不覆盖更新 action/deactivate/save context？
- missing pending save path、duplicate receipt key、lock acquire/release failure 是否 fail closed 且脱敏；
  confirm registry merge 与 platform completion 是否保留并发 switch/latest message reservation？
- receipt 缺失的 durable retry 若重绑 save/identity并重算 claim，是否仍因 SQLite claim anchor 拒绝；普通
  stale/integrity failure 是否恢复原 pending 且不留下 claim meta；commit 后可捕获异常是否保留 durable
  claim 并在过期后 replay；registry owner 崩溃是否自动释放 OS lock；start/act/confirm completion、prewarm、
  deactivate 与 expiry 是否共用跨平台锁，并以 revision 拒绝 stale activation；registry refresh 是否可能用
  锁外旧快照或 caller 的 stale metadata 覆盖 concurrent confirm merge；旧 confirm 是否可能抢占更新 start
  revision；confirm message-only reservation 是否会反向阻断有效 act/start completion；旧 schema revision=0
  回填是否同时要求 owner-validated hash、精确 Save/state 且拒绝任何新权威 generation？
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
- pending supersede/cancel/clarification lifecycle（atomic confirmation/replay 已由 Story 6.4 关闭）。
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
