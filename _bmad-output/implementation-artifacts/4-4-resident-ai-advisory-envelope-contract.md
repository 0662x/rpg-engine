---
baseline_commit: a3f33de72883a3535b67eb35b4a7175c2e26acce
---

# Story 4.4：Resident AI Advisory Envelope Contract

Status: done

## Story

作为引擎作者，
我希望 resident AI 输出共享一个 advisory envelope contract，
从而让意图识别、上下文总结、实体维护、进度管理和剧情推进建议都可追踪、非权威、可调试。

## 验收标准

1. **Resident AI 输出使用统一、严格且非权威的 envelope**

   **Given** resident AI assistant 产生输出
   **When** 输出被规范化、存储或返回
   **Then** v1 envelope 顶层只能包含且必须包含 `advisory_type`、`target_ids`、`evidence`、`confidence`、`freshness`、`visibility_mode`、`source_assistant`、`schema_version`、`proposed_next_workflow`、`provenance` 与 `authority`，所有 object 层级均使用 `additionalProperties: false`
   **And** `advisory_type` 固定为 `intent_recognition`、`context_summary`、`entity_maintenance`、`progress_management`、`plot_progression`；`confidence` 是拒绝 bool/NaN/Infinity 的 finite number `0.0..1.0`；`visibility_mode` 只接受 `player`、`gm`、`maintenance`；`schema_version` 固定为 `resident_ai_advisory:v1`；`proposed_next_workflow` 只接受 `none` 或对应五类受限 workflow hint，不接受自由文本、callback 或 command
   **And** `freshness` 严格包含 `status=current|stale|unknown`、nullable non-negative `as_of_turn_id` 与有界唯一 `source_event_ids`；current/stale 至少有一种 as-of evidence，unknown 不得伪造 freshness evidence；`evidence` 只包含有界 reference objects（至少 `kind`、`ref_id`、nullable `as_of_turn_id`），不得携带正文、delta、prompt 或任意扩展 payload
   **And** `authority` 是 required const object：`advisory_only=true`、`no_direct_writes=true`，fact-write、proposal-approve、player-confirm、hidden-read、trusted-delta、save-authorize、profile-escalate、validation-bypass 与 commit capability 全部固定为 false，任何输入都不能覆盖。

2. **Player-visible projection 在 contract 边界 fail closed**

   **Given** advisory record 会暴露给 player-visible surface
   **When** 它被 render，或未来由 CLI/MCP 等 player surface 消费
   **Then** player projection 必须从独立正向 allowlist 重建，并对 `target_ids` 与每个 evidence reference 分别使用权威 SQLite/access-contract 结果证明 player-visible；不得信任 envelope 自报的 visibility，最终再调用 hidden-material redaction 作为 defense-in-depth
   **And** hidden、archived、truly absent、unsupported evidence kind、查询失败与错误连接使用同一 omission 规则，不输出 id、alias、类型、名称、数量或逐项 reason；没有任何可证明公开的 target/evidence、缺少有效 SQLite connection 或 envelope 不是精确 `visibility_mode=player` 时，都返回同一个固定 generic unavailable 形状
   **And** private reasoning、hidden/GM-only facts、raw delta/delta draft、unsafe proposal internals、provider body、raw prompt 和敏感 provenance 被排除；maintenance/debug projection 仍保留有界且 JSON-safe 的 advisory type、source assistant、schema、安全 target/evidence 引用、freshness、visibility 与 provenance，不得形成 hidden existence oracle。

## 任务 / 子任务

- [x] Task 1：先补 RED contract tests，冻结 envelope schema 与 authority（AC: 1-2）
  - [x] 新增 `tests/test_resident_ai_advisory.py`，覆盖完整合法 envelope、稳定 round-trip、frozen/immutable 行为与 package resource schema 可加载。
  - [x] 覆盖五个 v1 `advisory_type`：intent recognition、context summary、entity maintenance、progress management、plot progression；不得在本 Story 接入对应 helper。
  - [x] 覆盖全部必填字段、unknown/missing field、空或重复 target、非法 confidence/freshness/visibility/source/workflow、非 JSON 值、bool 冒充 number、NaN/Infinity、循环/过深/过大输入的有界 fail-closed 行为；structural budget 必须先于 jsonschema 限制深度、总节点数、容器项数、单字符串与总字符串预算，并以 object identity 检测循环。
  - [x] 覆盖大小写、分隔符与 Unicode 变体以及嵌套 key 的 authority smuggling：对 mapping key 做 NFKC + casefold，并移除 Unicode separator、punctuation、format 与 combining-mark 后匹配禁止 key；至少覆盖 fullwidth、零宽、空格、`-`、`_`、`.` 变体，只检查 key，不因普通 evidence 文本含 `confirm` 等词误拒。
  - [x] 覆盖 authority 输出固定为 `advisory_only=true`、`no_direct_writes=true` 且 write/approve/confirm/hidden/commit capabilities 为 false，caller 输入不能覆盖。

- [x] Task 2：实现共享 Resident AI Advisory contract（AC: 1）
  - [x] 新增 `rpg_engine/ai/advisory.py`，使用现有 Python 3.11+ frozen dataclass、纯函数 normalization 与显式 `to_dict` 风格；nested value objects 同样 frozen、collection 使用 tuple、不保留 caller 的 list/dict 引用，`to_dict()` 每次返回新的 JSON structures。
  - [x] 稳定 API 固定为 `normalize_resident_ai_advisory(value) -> ResidentAIAdvisory`、`resident_ai_advisory_to_maintenance_dict(envelope)` 与 `resident_ai_advisory_to_player_dict(envelope, conn)`；serializer 只接受已验证 envelope。
  - [x] Normalizer 先执行有界 JSON-safe structural preflight，再复用现有 Draft 2020-12 validator；unknown、missing、duplicate、oversized、cyclic、过深、非有限、非 JSON 或 validator 异常统一以脱敏、稳定 `$...` path `ValueError` 拒绝，不静默裁剪、不对未知对象调用 `str()`、不返回部分结果。
  - [x] 新增 `rpg_engine/resources/schemas/resident_ai_advisory.schema.json`，使用与 structural budget 同源的稳定 enum/type/bounds、所有 object 的 `additionalProperties: false`；复用 `ai/schema_validation.py` 与现有 resource loader，不建立平行 schema validator。
  - [x] `target_ids`、evidence 与 provenance 必须有界、去重、确定性、JSON-safe；advisory runtime/trace id 不得替代 `entities.id`，evidence 不得成为 gameplay fact。
  - [x] `freshness` 必须明确当前/stale/unknown 与 as-of evidence；`proposed_next_workflow` 只是受限 workflow hint，不能是 callback、命令执行、approval、confirmation 或 commit capability。
  - [x] 在 `rpg_engine/ai/__init__.py` 只导出稳定 contract/normalization/projection API；保持现有 `SemanticSuggestion`、`ArchivistSuggestion`、`StateAuditResult`、`AIHelperResult` shape 不变。

- [x] Task 3：实现 maintenance/debug 与 player-safe projection（AC: 2）
  - [x] Maintenance/debug serializer 只保留 contract 所需的有界 provenance；不得保存或回显 model chain-of-thought/private reasoning。
  - [x] Player serializer 使用独立正向 allowlist，不得直接递归复制 maintenance/storage payload；先验证 `visibility_mode=player`，再对 target/evidence 做权威 inclusion check 并复用 `visibility.py` 与 `redact_player_hidden_material()`；缺少有效 connection、错误 view/connection、未知 reference 或核验失败时只返回固定 generic unavailable，不抛含输入内容的异常，也不 fallback 到 maintenance renderer。
  - [x] Player targets/evidence 只保留已证明 player-visible 的安全引用；hidden/archived/absent/unsupported/query-failed 输入产生相同 omission 规则，不泄露 hidden 数量、类型、名称、id、alias 或逐项 reason。
  - [x] 用 temporary SQLite/Save fixture 放入 hidden entity、alias、clock/world-setting canary，证明 public result 不含 private reasoning、hidden token、raw delta、proposal internals、raw prompt/provider body；GM/maintenance debug 仍能检查安全 provenance。
  - [x] 证明 normalize/serialize/render 均为无副作用 contract 操作：不写 SQLite facts/events/current turn，不改 Campaign、Save、registry、pending state、preflight cache 或 proposal queue；在 caller-owned 未提交 transaction 中放置 sentinel，调用后 `conn.in_transaction`、commit/rollback ownership、`total_changes` 与 connection lifecycle 都不被 helper 改变。

- [x] Task 4：同步 canonical contract 文档（AC: 1-2）
  - [x] 更新 `docs/architecture.md`，定义 Resident AI Advisory Envelope、非权威边界、visibility-safe projection 与 30-60 秒仅为 background scheduling target。
  - [x] 更新 `docs/data-models.md`，记录 envelope 是 runtime/advisory contract 而非 Save fact，列明字段、freshness/provenance/authority 与 player-safe projection 语义；不得新增持久化表或暗示 storage authority。
  - [x] 更新 `docs/component-inventory.md` 登记 `rpg_engine/ai/advisory.py` 的 contract 职责。
  - [x] 更新 `docs/testing-and-quality-gates.md` 登记 focused、redaction、no-authority/no-mutation 与 adjacent regression gate。
  - [x] `docs/ai-intent-chain.md`、CLI/MCP contract 仅在真实公开行为发生变化时才更新；本 Story 默认禁止新增 CLI/MCP tool 或改变 route/preflight mode matrix。

- [x] Task 5：从最终 clean diff 运行全部 required gates（AC: 1-2）
  - [x] Story focused：Resident advisory schema/normalization/projection、AI helper sanitizer、current-native visibility。
  - [x] Adjacent regression：AI intent、current-native context、context quality、MCP/platform/SaveManager/surface inventory、cross-layer/write safety；所有写测试使用 temporary Save。
  - [x] Campaign：两个 canonical example 的 validate/test。
  - [x] Docs/static：Markdown links、changed Python `py_compile`、full Ruff、`git diff --check`。
  - [x] Repository full `pytest`；任何后续 review patch 都使受影响的旧绿灯失效，必须重跑。

### Review Findings

- [x] [Review][Patch] Serializer 必须重新验证公开 dataclass，拒绝直接构造的伪造 envelope [`rpg_engine/ai/advisory.py:191`]
- [x] [Review][Patch] Player target/evidence 必须按实际 relationship/progress 类型走对应 access contract [`rpg_engine/ai/advisory.py:239`]
- [x] [Review][Patch] Player allowlist 不得回显可由 hidden evidence 影响的 assistant/confidence/freshness/workflow 元数据 [`rpg_engine/ai/advisory.py:210`]
- [x] [Review][Patch] Structural node/total-string budget 必须覆盖 schema 允许的最大合法 envelope [`rpg_engine/ai/advisory.py:18`]
- [x] [Review][Patch] `as_of_turn_id` 必须有 JSON-safe integer 上界并在 structural preflight 拒绝巨型整数 [`rpg_engine/ai/advisory.py:291`]
- [x] [Review][Patch] Schema/validator rejection 必须收敛为脱敏、稳定的 `$` path `ValueError` [`rpg_engine/ai/advisory.py:155`]
- [x] [Review][Patch] Package schema 必须与 normalizer 一致拒绝重复 evidence [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:37`]
- [x] [Review][Patch] Target/reference ID 必须拒绝非 canonical、runtime/trace target 与尾随换行 [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:30`]
- [x] [Review][Patch] Authority key canonicalization 必须在兼容分解后移除 combining marks [`rpg_engine/ai/advisory.py:350`]
- [x] [Review][Patch] RED matrix 必须真实覆盖 empty、NaN、source/schema、node/container/total-string budgets 与 schema 上限 [`tests/test_resident_ai_advisory.py:49`]
- [x] [Review][Patch] Authority-smuggling 测试必须证明在 schema 前由 canonical-key gate 拒绝 [`tests/test_resident_ai_advisory.py:185`]
- [x] [Review][Patch] Hidden redaction 后必须重新验证 player projection 的固定 allowlist 形状 [`rpg_engine/ai/advisory.py:227`]
- [x] [Review][Patch] 公开 `to_dict` 与 serializer 必须拒绝内部 authority flag 被伪造的 envelope [`rpg_engine/ai/advisory.py:104`]
- [x] [Review][Patch] Evidence、freshness event 与 provenance ids 必须使用 canonical prefixed reference syntax [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:59`]
- [x] [Review][Patch] Structural/schema 错误必须脱敏未知 key/value，同时保留已知字段的稳定 `$` path [`rpg_engine/ai/advisory.py:155`]
- [x] [Review][Patch] Authority-smuggling gate 必须覆盖完整 capability key variants，并证明 schema validator 未被调用 [`rpg_engine/ai/advisory.py:24`]
- [x] [Review][Patch] RED matrix 必须覆盖 duplicate evidence/source ids 与 schema 真实最大字符串 payload [`tests/test_resident_ai_advisory.py:119`]
- [x] [Review][Patch] Structural preflight 与公开 dataclass 必须拒绝 stateful container subclasses 和非 tuple collections [`rpg_engine/ai/advisory.py:192`]
- [x] [Review][Patch] Authority const 必须使用精确 bool，拒绝 `1/0` 借 dataclass equality 洗白 [`rpg_engine/ai/advisory.py:157`]
- [x] [Review][Patch] Evidence/freshness `as_of_turn_id` 必须在 runtime contract 中精确为 int 而非 integral float [`rpg_engine/ai/advisory.py:223`]
- [x] [Review][Patch] Evidence kind/ref、trace 与 source assistant 必须使用对应 canonical identifier syntax [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:58`]
- [x] [Review][Patch] Defense-in-depth redaction 只检查动态 references，避免 hidden 文本碰撞固定协议 key 造成全局 unavailable [`rpg_engine/ai/advisory.py:292`]
- [x] [Review][Patch] Player projection nested shape 与 redaction equality 必须区分 bool/int 等不同 wire types [`rpg_engine/ai/advisory.py:328`]
- [x] [Review][Patch] Structural preflight 必须拒绝 hostile JSON scalar subclasses 并统一脱敏失败 [`rpg_engine/ai/advisory.py:420`]
- [x] [Review][Patch] Target/entity evidence 必须排除完整已知 runtime/derived namespaces [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:40`]
- [x] [Review][Patch] Authority-smuggling gate 必须覆盖 authority/approval/confirmation 直白 capability variants [`rpg_engine/ai/advisory.py:24`]
- [x] [Review][Patch] Validator 内部异常不得通过 exception cause/traceback 保留敏感正文 [`rpg_engine/ai/advisory.py:230`]
- [x] [Review][Patch] 同一 ref/as-of 不得借不同 evidence kind 重复进入 canonical envelope [`rpg_engine/ai/advisory.py:508`]
- [x] [Review][Patch] Authority key canonicalization 必须保持 NFKC 规则并在之后分解 combining marks [`rpg_engine/ai/advisory.py:490`]
- [x] [Review][Patch] Defense redactor 必须只扫描 reference leaf values，固定动态容器 key 也不能形成 hidden token DoS [`rpg_engine/ai/advisory.py:292`]
- [x] [Review][Patch] RED matrix 必须覆盖 archived omission 与 typed relationship/progress/world/rule 正向分支 [`tests/test_resident_ai_advisory.py:489`]
- [x] [Review][Patch] Structural preflight 的 mapping key 必须是 exact str，拒绝 hostile key subclasses [`rpg_engine/ai/advisory.py:458`]
- [x] [Review][Patch] 单个 target/evidence access 异常必须只 omission 该引用，不得压掉其他安全项 [`rpg_engine/ai/advisory.py:300`]
- [x] [Review][Patch] Target/entity evidence 必须明确排除 `runtime:` 等控制面 namespace [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:40`]
- [x] [Review][Patch] Player serializer 不得在 `to_dict()` strict revalidation 后重复完整 normalization [`rpg_engine/ai/advisory.py:296`]
- [x] [Review][Patch] Normalizer 必须在 preflight 后使用 bounded exact snapshot，消除 caller mutation TOCTOU [`rpg_engine/ai/advisory.py:237`]
- [x] [Review][Patch] `rel:`/`clock:` reference 必须按 prefix fail closed 到 typed access contract，即使存储 type 损坏 [`rpg_engine/ai/advisory.py:325`]
- [x] [Review][Patch] Advisory schema 必须接受 Progress contract 合法的 nested-colon clock ids [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:39`]
- [x] [Review][Patch] Redactor 比较必须保存调用前 wire snapshot，拒绝 in-place mutation 绕过 [`rpg_engine/ai/advisory.py:316`]
- [x] [Review][Patch] Maintenance provenance source ids 必须限制为安全 source namespace [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:208`]
- [x] [Review][Patch] Bare `authority/approval/confirmation` 只能作为 canonical 顶层 authority，嵌套时 pre-schema 拒绝 [`rpg_engine/ai/advisory.py:28`]
- [x] [Review][Patch] `rel:`/`clock:` prefix dispatch 必须优先于相互冲突的 malformed storage type [`rpg_engine/ai/advisory.py:337`]
- [x] [Review][Patch] Snapshot 前 structural traversal 的并发 mutation 异常必须脱敏收敛 [`rpg_engine/ai/advisory.py:419`]
- [x] [Review][Patch] Clock target/evidence pattern 必须精确对齐现有 Progress Access Contract [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:39`]
- [x] [Review][Patch] Target/entity evidence 必须排除 candidate/prompt/hidden 等明确非事实 namespace [`rpg_engine/resources/schemas/resident_ai_advisory.schema.json:44`]
- [x] [Review][Patch] `rule:`/`world:`/`setting:` target prefix 必须与实际 storage type 一致 [`rpg_engine/ai/advisory.py:325`]
- [x] [Review][Patch] Player projection 必须只读取 `to_dict()` 生成的 canonical validated snapshot [`rpg_engine/ai/advisory.py:296`]
- [x] [Review][Patch] Player evidence 不得发布未经历史时点 visibility 证明的 `as_of_turn_id` [`rpg_engine/ai/advisory.py:319`]
- [x] [Review][Patch] Defense redactor 必须保持 exact `list[str]` 形状，拒绝 JSON 等价的 tuple 替换 [`rpg_engine/ai/advisory.py:333`]
- [x] [Review][Patch] 已验证的结构化公开 reference 不得因 hidden ID 子串前缀碰撞形成 existence oracle [`rpg_engine/ai/advisory.py:338`]
- [x] [Review][Patch] 公开 dataclass serializer 必须在 tuple materialization 前执行 exact collection 上限检查 [`rpg_engine/ai/advisory.py:216`]
- [x] [Review][Patch] Schema/snapshot/traversal 脱敏异常不得在 `__context__` 或 traceback 中保留底层敏感异常 [`rpg_engine/ai/advisory.py:253`]
- [x] [Review][Patch] Structured ref redaction 必须仅按 bounded canonical hidden IDs 区分大小写精确匹配，不加载 hidden name/alias/text corpus [`rpg_engine/redaction.py:215`]
- [x] [Review][Patch] Snapshot copy 本身必须执行 node/depth/item/string budgets，拒绝 preflight 后并发增长的 list [`rpg_engine/ai/advisory.py:574`]
- [x] [Review][Patch] Public normalizer 必须重抛无 hostile locals 的脱敏 traceback，而非仅清除 cause/context [`rpg_engine/ai/advisory.py:251`]
- [x] [Review][Patch] Structured redaction helper 必须自行拒绝超长或非 canonical reference IDs [`rpg_engine/redaction.py:240`]
- [x] [Review][Patch] Player serializer 必须拒绝可 shadow 权威 main access tables 的 TEMP table/view [`rpg_engine/ai/advisory.py:373`]
- [x] [Review][Patch] Maintenance serializer 与 envelope `to_dict()` 的脱敏 traceback 不得保留 envelope/self locals [`rpg_engine/ai/advisory.py:210`]
- [x] [Review][Patch] Dataclass `_raw_dict()` 必须先捕获 immutable local tuple snapshot 再做预算与 materialization [`rpg_engine/ai/advisory.py:229`]
- [x] [Review][Patch] Player serializer 必须要求权威 access tables 存在于 `main`，拒绝 attached-schema fallback [`rpg_engine/ai/advisory.py:456`]
- [x] [Review][Patch] Envelope `to_dict()` 二次 materialization 失败前必须清除 normalized/result locals [`rpg_engine/ai/advisory.py:219`]

## 开发说明

### 范围与 P0 边界

- 本 Story 只建立共享 contract、严格 schema/normalizer 和 visibility-aware projections；“storage/maintenance serializer”仅表示未来 owner 可消费的 canonical JSON-safe representation，本 Story 不选择 storage owner、不写表、不增加 queue/repository/service 或 persistence lifecycle，也不实现 resident coordinator、scheduler、worker 或 helper adapter。
- Story 4.5 才负责把少量现有 helper 接入 envelope；Story 4.6 才负责 entity/relationship/progress advisory 的 proposal/review workflow；Story 4.7 才负责 plot progression advice。不得提前迁移 `ai_intent`、semantic、Archivist、reflection、memory、state audit、delta draft、response acceptance、turn assistant 或 proposal queue。
- 禁止新增依赖、SQLite schema/migration、Campaign/Save schema、CLI/MCP surface、public parameter、Coordinator、异步框架或第二套 intent/write path。若 contract 无法在这些边界内落地，HALT 并核验新的 P0 planning。
- 不改变 Story 4.1 的 intent mode matrix、Story 4.2 的 8/15/30-60 秒 latency contract、Story 4.3 的 preflight cache identity/TTL/single-use/CAS 行为。
- `AI proposes. Kernel verifies. Player confirms. Engine commits.` 继续成立；external/internal/resident AI 都不能获得 fact、hidden、confirmation、proposal approval、validation 或 commit authority。

### 现有实现状态与复用要求

- `rpg_engine/ai/schemas.py` 已有 helper-specific frozen dataclasses；保持这些 shape 不变，新共享 contract 独立放在 `rpg_engine/ai/advisory.py`。
- `rpg_engine/ai/provider.py` 的 public helper serializer 已采用正向 allowlist、稳定枚举、有限深度、provider/model/private output 脱敏；新 player projection复用其安全原则，但不得把 provider serializer 变成 advisory contract。
- `rpg_engine/ai/schema_validation.py` 已支持 Draft 2020-12 与 `additionalProperties: false`；schema resources 已由 package-data glob 覆盖，无需修改依赖或 `pyproject.toml`。
- `rpg_engine/visibility.py` 已定义 player/gm/maintenance view；`rpg_engine/redaction.py` 已提供基于权威 SQLite 的 hidden/archived entity、clock、world-setting 与相关 token redaction。复用它们，不建立第二套 visibility vocabulary/redactor。
- Public projection 必须 allowlist，不得使用“复制完整 payload 后 denylist 删除几个 key”的设计；复杂、未知、非有限或循环输入必须安全拒绝，不能 crash、泄露或暗示权限。

### 文件结构要求

- **NEW**：`rpg_engine/ai/advisory.py`、`rpg_engine/resources/schemas/resident_ai_advisory.schema.json`、`tests/test_resident_ai_advisory.py`。
- **UPDATE**：`rpg_engine/ai/__init__.py`、`docs/architecture.md`、`docs/data-models.md`、`docs/component-inventory.md`、`docs/testing-and-quality-gates.md`。
- **EXPECTED NO CHANGE**：`rpg_engine/runtime.py`、`save_manager.py`、`preflight_cache.py`、`ai_intent/*`、`platform_*`、`mcp_adapter.py`、CLI、proposal/validation/commit、migrations、Campaign/Save schema、formal packages/registry，以及所有现有 helper adapter modules。
- 条件文件只有在 RED 证据证明 contract 无法落地时才能最小修改；编辑前必须完整重读目标文件并在开发记录中写明触发证据。不得把测试编排塞进 production API。

### 测试要求

建议 focused gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_resident_ai_advisory.py \
  tests/test_ai_helper.py \
  tests/test_current_native_visibility.py \
  -p no:cacheprovider
```

建议 adjacent regression：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ai_intent.py \
  tests/test_current_native_context.py \
  tests/test_context_quality.py \
  tests/test_mcp_adapter.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py \
  tests/test_platform_sidecar.py \
  tests/test_preflight_cache.py \
  tests/test_runtime.py \
  tests/test_save_manager.py \
  tests/test_surface_inventory.py \
  tests/test_cross_layer_regression.py \
  tests/test_current_native_write_safety.py \
  tests/test_validation_pipeline.py \
  -p no:cacheprovider
```

Campaign gate：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
```

最终静态与全量 gate：

```bash
python3 scripts/check_markdown_links.py docs _bmad-output
python3 -m py_compile <changed-python-files>
python3 -m ruff check .
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
```

### 前序 Story 情报

- Story 4.1 已固定 external/internal mode matrix；shared input 必须先做 schema、registry、binder、visibility 安全化，public trace 不得携带 raw low-trust slots。
- Story 4.2 已建立 `AIHelperResult` 的 advisory/no-write/latency evidence 与严格 public sanitizer。其 21 轮 review / 92 patch 表明 malformed nested input、非有限值、递归深度、allowlist 与 authority flag 是高风险热点；测试必须主动覆盖。
- Story 4.3 已加固 preflight identity、TTL、single-use/CAS 和短 advisory transaction。其 5 轮 review / 16 patch 表明独立 advisory state 不得 commit caller transaction，且任何 patch 后必须重新跑失效 gates。
- 已记录的 pre-existing defer “新 `player_turn` 清理已有 pending action的生命周期策略”与本 Story 无关，不得夹带处理。

### Git 情报摘要

- 基线 commit `a3f33de72883a3535b67eb35b4a7175c2e26acce`（`feat: harden advisory preflight cache`）；当前工作树在 Create Story 开始时 clean。
- 最近提交均采用“小步 contract/boundary hardening + focused tests + canonical docs + continuous three-way review”的模式；没有为 Story 4.4 授权新依赖、migration、public surface 或 coordinator。
- `uv.lock` 的存在不构成本 Story 增依赖授权；继续使用 Python 3.11+、stdlib、现有 jsonschema、pytest 与 Ruff。

### 最新技术信息

- 本 Story 不新增/升级 library、framework、external API 或数据库版本，也没有时效性技术决策；无需 Web research。

### 项目上下文参考

- `data/game.sqlite` 是事实权威；advisory envelope、trace、audit、cache 或 projection 都不能覆盖事实。
- Hidden/GM-only 内容不得进入 player surface、普通 query、scene、FTS、prompt 或 public advisory projection。
- 所有写测试必须使用 temporary Save；不得修改 source Campaign、formal current Saves 或正式 registry。
- CLI/MCP/platform 必须保持 thin adapter；本 Story不通过 public surface 暴露新的低层能力。

### 参考来源

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 4 / Story 4.4、AR-7、AR-9 至 AR-12、AR-24 至 AR-26、AR-40 至 AR-42]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md` — FR-5、FR-9、FR-12、FR-16、NFR-1、NFR-4、NFR-8]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md` — AD-2、AD-3、AD-6、AD-8、AD-10、Contract family seeds]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md` — AD-1、AD-2、AD-3、AD-5]
- [Source: `docs/project-context.md` — 不可破坏边界、测试期望]
- [Source: `docs/architecture.md` — AI intent、visibility、latency 与 write-chain 边界]
- [Source: `docs/data-models.md` — fact/advisory/visibility 模型]
- [Source: `docs/component-inventory.md` — AI component ownership]
- [Source: `docs/testing-and-quality-gates.md` — AI/visibility/write safety gates]
- [Source: `_bmad-output/implementation-artifacts/4-3-advisory-preflight-cache-boundary.md` — Review Findings、Previous Story learnings]

## 开发代理记录

### 使用的代理模型

GPT-5 Codex

### 调试日志引用

- RED：`tests/test_resident_ai_advisory.py` 初次 collection 因 `ResidentAIAdvisory` 未实现而失败。
- GREEN：focused contract 9 passed / 27 subtests；changed-file Ruff、py_compile 与 diff check 通过。
- Dev Story 最终 focused：49 passed / 8941 subtests。
- Dev Story 最终 adjacent：368 passed / 458 subtests。
- Dev Story 最终 Campaign：两个 canonical examples 的 validate/test 四命令全部 OK。
- Dev Story 最终 docs/static：Markdown links 179 files、changed py_compile、full Ruff、`git diff --check` 全部通过。
- Dev Story repository full：858 passed / 9774 subtests。
- BMAD Dev Story：完整读取 `.agents/skills/bmad-dev-story/SKILL.md` 与 checklist；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空；按 fresh start→in-progress→RED/GREEN/refactor→required gates→review 顺序执行。
- Code Review 持续收敛：14 轮三路 fresh Blind Hunter / Edge Case Hunter / Acceptance Auditor；各轮有效 patch 数为 12/5/6/8/4/4/4/4/2/3/3/4/2/0，共 61，Decision=0、Defer=0；第 14 轮 clean（仅剩 1 项经 AC/范围证据 dismiss 的既有 access-contract UDF 行为）。
- Review 最终 focused：70 passed / 8989 subtests；adjacent：368 passed / 458 subtests。
- Review 最终 Campaign：两个 canonical examples 的 validate/test 四命令全部 OK。
- Review 最终 docs/static：Markdown links 179 files、changed py_compile、full Ruff、`git diff --check` 全部通过。
- Review 最终 repository full：879 passed / 9822 subtests（冻结 temporary current-native Campaign/Save roots；正式 Save 未被测试修改）。
- BMAD Code Review：完整读取 `.agents/skills/bmad-code-review/SKILL.md`、三路 reviewer skills 与 step-01..04；resolver 成功，prepend/append 为空，persistent fact=`docs/project-context.md`，on_complete 为空；所有有效 `[Review][Patch]` 自动应用后重跑失效 gates 并持续复审至 clean。

### 实施计划

- 先用 contract/schema RED tests 冻结 required fields、authority rejection、player visibility 与 hidden redaction。
- 实现独立 frozen envelope、严格 schema/normalizer、maintenance/debug serializer 与 player-safe allowlist projection。
- 不接入现有 helper；同步 canonical docs 后，从最终 diff 跑 focused、adjacent、Campaign、docs/static 与 full suite。

### 完成说明列表

- 已完成终极上下文引擎分析并生成完整开发指南。
- 已实现 strict、deeply immutable Resident AI advisory envelope、schema/authority/freshness/provenance 合同与稳定 API export。
- 已实现 maintenance-safe serializer 与 SQLite/access-contract 驱动的 player allowlist projection；hidden/absent/unsupported/query failure 收敛为 generic unavailable，且不改变 caller transaction ownership。
- 已同步 architecture、data model、component inventory 与 testing canonical docs；公开 CLI/MCP/intent/preflight contract 未改变。
- 全部 Dev Story tasks、AC 与 DoD 已满足；14 轮三路 review 已持续收敛 clean，最终 focused、adjacent、Campaign、docs/static 与 repository full suite 全绿，状态转为 done。

### 文件列表

- `_bmad-output/implementation-artifacts/4-4-resident-ai-advisory-envelope-contract.md`
- `_bmad-output/implementation-artifacts/4-4-resident-ai-advisory-envelope-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/ai/__init__.py`
- `rpg_engine/ai/advisory.py`
- `rpg_engine/redaction.py`
- `rpg_engine/resources/schemas/resident_ai_advisory.schema.json`
- `tests/test_resident_ai_advisory.py`

## 变更日志

- 2026-07-12：Create Story 生成完整实现上下文，状态设为 ready-for-dev。
- 2026-07-12：Validate Story 自动应用 3 项 critical、4 项 enhancement 与 2 项 optimization，decision-needed 为 0。
- 2026-07-12：完成 Resident AI Advisory strict contract、player-safe projection、focused/adjacent/full regression 与 canonical docs 同步，Story 转为 review。
- 2026-07-12：完成 14 轮三路 fresh code review，自动应用 61 项有效 patch，最终 required gates 全绿，Story 转为 done。

## BMAD 来源记录

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`；从 `sprint-status.yaml` 选择首个 backlog Story。
- Catalog 路由：`[CS] Create Story`（`bmad-create-story:create`，required）后接 `[VS] Validate Story`（`bmad-create-story:validate`）。
- 完整读取的 skill：`.agents/skills/bmad-help/SKILL.md`、`.agents/skills/bmad-create-story/SKILL.md`。
- Customization：`bmad-create-story` resolver 成功，`activation_steps_prepend=[]`、`activation_steps_append=[]`、`persistent_facts=[file:{project-root}/**/project-context.md]`、`on_complete=""`；`bmad-help` 无 customization surface。
- 已加载 config/facts：`_bmad/bmm/config.yaml`、`_bmad/core/config.yaml`、`docs/project-context.md`、`docs/governance/bmad-workflow.md`；通信与文档语言均为中文。
- 已完整执行/读取：Create Story `discover-inputs.md`、`template.md`、`checklist.md`；`epics.md`、主 PRD、两份 Architecture Spine、previous Story 4.3、canonical architecture/data-model/component/testing docs、主要现有 AI schema/export 代码与最近 5 个 commit。
- Input discovery：`epics_content` 1 文件、`prd_content` 1 个主 PRD、`architecture_content` 2 个 spine；未发现 UX artifact。
- Create Story research subagents：三路只读研究分别覆盖 Epic/前序 Story、架构/代码触点、PRD/Git/测试；结论均为 contract-only、无新依赖/migration/surface/coordinator/helper adapter。
- Web research：未执行。本 Story 不新增或升级 library、framework、external API 或依赖，只复用仓库锁定的 Python 3.11+、stdlib、jsonschema、pytest 与 Ruff。
- Create Story `on_complete` 为空。
- Validate Story 使用 fresh subagent 按完整 checklist 独立复核；9 项无歧义改进已全部自动应用，decision-needed 为 0，报告见同名 `.validation-report.md`。
- Catalog review 路由：`[CR] Code Review`（`bmad-code-review`）；按用户授权启用 Blind Hunter、Edge Case Hunter、Acceptance Auditor 三路 fresh review subagents 并自动应用所有有效 `[Review][Patch]`。
- Code Review customization：resolver 成功，`activation_steps_prepend=[]`、`activation_steps_append=[]`、`persistent_facts=[file:{project-root}/**/project-context.md]`、`on_complete=""`；完整执行 step-01 gather、step-02 review、step-03 triage、step-04 present/resolve。
