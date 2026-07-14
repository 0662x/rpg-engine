# 数据模型

文档状态：**CURRENT：BMAD canonical data model authority**

本文件是 RPG Engine 当前数据模型的 canonical 文档。它描述持久事实、运行合同、投影、
缓存和包 manifest 的边界。旧 `docs/specs/` 与 `docs/architecture/` 路径现在是
compatibility stubs，原文位于 [`archive/pre-bmad-docs-2026-07-03/`](archive/pre-bmad-docs-2026-07-03/)；
日常开发应先读本文件。

## 核心结论

RPG Engine 的数据模型分成四类。只有 Save Package 中的 SQLite 当前事实库拥有游戏事实权威。

```text
Campaign manifest/content -> 初始化或同步来源
Save SQLite -> 当前事实权威
TurnProposal / delta / reports -> 运行合同和校验证据
Projection / registry / archive / cache -> 派生物、索引或 advisory state
```

硬边界：

- `data/game.sqlite` 是当前事实权威。
- `events` 表是权威审计记录；`data/events.jsonl` 是投影。
- `projection_state` 和 `outbox` 描述投影健康，不是游戏事实。
- `.aigm/save-registry.json` 选择 active save，不保存游戏事实。
- pending action / pending clarification 是玩家入口临时状态，不是已发生事实。
- `intent_preflight_cache` 是 advisory AI intent cache，不能替代 preview、validation、confirm 或 commit。
- `ResidentAIAdvisory` 是严格的 runtime/advisory contract representation，不是新的事实表、queue 或 persistence owner。
- `.aigmsave` 是归档格式，不是另一个可写事实源。

## 数据地图

```mermaid
flowchart TD
  Campaign["Campaign Package\ncampaign.yaml + content YAML"]
  SaveManifest["Save Package manifests\ncampaign.yaml + save.yaml"]
  SQLite["data/game.sqlite\ncurrent fact authority"]
  Delta["Turn Delta\nvalidated write payload"]
  Proposal["TurnProposal\npending/approved contract"]
  Validation["ValidationReport\ncommit evidence"]
  ProjectionState["projection_state + outbox\nprojection health"]
  Artifacts["events.jsonl + snapshots + cards + memory\nrebuildable artifacts"]
  Registry[".aigm/save-registry.json\nworkspace index"]
  Pending[".aigm/pending-*.json\nplayer entry temporary state"]
  Preflight["intent_preflight_cache\nadvisory internal review"]
  Archive[".aigmsave\narchive manifest + files"]

  Campaign --> SaveManifest
  SaveManifest --> SQLite
  Proposal --> Delta
  Delta --> Validation
  Validation --> SQLite
  SQLite --> ProjectionState
  ProjectionState --> Artifacts
  Registry --> SQLite
  Pending --> Proposal
  Preflight -. "candidate only" .-> Proposal
  SQLite --> Archive
```

## Package Manifests

### Campaign Manifest

`campaign.yaml` 描述作者包，由 `rpg_engine.campaign.load_campaign()` 读取。

当前核心字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定 campaign id。 |
| `name` | 面向人类的 campaign 名称。 |
| `engine_version` | 需要的引擎版本。 |
| `package_version` | Campaign package 版本。 |
| `content_schema_version` | Campaign content schema 版本。 |
| `capabilities` | 声明支持的玩法能力。 |
| `defaults.player_entity_id` | 默认玩家实体 id。 |
| `defaults.context_budget` | 默认上下文预算。 |
| `defaults.sample_texts` | 作者提供的路由和 smoke 覆盖样例。 |
| `content.*` | 相对 YAML 内容路径。 |

Campaign manifest 和 content 是来源数据，不是当前游玩状态。Campaign validation 会报告
Campaign root 中混入的 Save/runtime artifacts，例如 `save.yaml`、`data/game.sqlite`、
`data/events.jsonl`、`snapshots/`、`cards/`、`memory/`、`backups/`、`reports/` 和
`.aigm/save-registry.json`、`.aigm/pending-*`。这些报告是 ownership warnings；validation
不会把这些 artifacts 当作作者内容导入，也不会自动修复或删除它们。

### Save Manifest

`save.yaml` 描述某个具体 Save Package。

当前核心字段：

| 字段 | 说明 |
| --- | --- |
| `save_schema_version` | Save manifest schema 版本。 |
| `campaign_id` | 来源 campaign id。 |
| `campaign_version` | 来源 campaign package 版本。 |
| `engine_version` | 当前 save 使用的引擎版本。 |
| `source_campaign_path` | 用作 trusted content root 的来源 campaign 路径。 |
| `created_at` | 创建时间戳。 |

`save.yaml` 是元数据，不覆盖 SQLite 中的当前事实。`save init` 的目标 Save Package 必须位于
source Campaign root 之外，避免运行态 manifests、SQLite 和投影产物写入作者包目录。

### Runtime Campaign Manifest In Save

Save Package 也包含运行态 `campaign.yaml`。`init_v1_save()` 会用稳定 runtime 路径写入该
manifest：

- `data/game.sqlite`
- `data/events.jsonl`
- `snapshots/current.md`
- `snapshots/current.json`
- `cards`

它的 `content.*` 路径指向已复制的本地内容，或指向声明来源 campaign root 下的内容。
绝对 content 路径不允许。

## SQLite Fact Store

`data/game.sqlite` 是当前事实库。它由 `init_database()` 初始化，并通过
`rpg_engine/resources/migrations/*.sql`.

### Current Version Meta

`db.py` 会把这些版本写入 `meta`：

| 键 | 当前值 |
| --- | --- |
| `schema_version` | `0.3` |
| `save_schema_version` | `0.3` |
| `content_schema_version` | `1` |
| `projection_schema_version` | `1` |

其他重要 `meta` 键：

- `engine_version`
- `package_version`
- `campaign_id`
- `campaign_name`
- `player_entity_id`
- `current_turn_id`
- `current_game_day`
- `current_time_block`
- `current_location_id`
- `last_saved_at`

`meta` 保存当前指针和版本标记，应保持小而标量化。

### Core Tables

| 表 | 职责 |
| --- | --- |
| `meta` | Version markers and current state pointers. |
| `turns` | One row per accepted turn or seed turn. |
| `events` | Authoritative event audit rows linked to turns. |
| `entities` | Canonical entity records and shared fields. |
| `aliases` | Entity aliases for lookup. |
| `facts` | Structured subject-predicate facts with validity window. |
| `characters` | Character-specific side table. |
| `items` | Item/equipment side table. |
| `locations` | Location-specific side table. |
| `routes` | Travel graph edges. |
| `crop_plots` | Crop plot side table retained by current schema. |
| `clocks` | Clock state and tick metadata. |
| `rules` | Rule entities and rule-specific fields. |
| `world_settings` | Stable world explanations and hidden/visible setting content. |
| `memory_summaries` | Long-term memory summaries，带 source/freshness/visibility metadata 的派生 context evidence。 |
| `context_runs` | Context build audit records. |
| `context_items` | Items included or omitted in a context build. |
| `fts_index` | Full-text index for non-hidden, non-archived entities. |

`entities` 是共享锚点表。类型专属表应引用它，不应发明并行身份系统。

### Reliability Tables

| 表 | 职责 |
| --- | --- |
| `schema_migrations` | Applied migrations and checksums. |
| `outbox` | Durable projection work queue, currently used for events JSONL append. |
| `projection_state` | Projection status, version, turn pointer and last error. |

`projection_state` can report `clean`, `dirty`, `refreshing`, `failed` or `stale`. Save validation requires
required projections to be clean and aligned with `current_turn_id`.
缺失的 `memory` state row 必须初始化为 `dirty`，直到 deterministic rebuild 完成；事实维护在同一 turn
修改 current-state tables 时也必须将 `memory` 标 dirty，即使 `updated_turn_id` 没有变化。
`projection_state` 的可写性不依赖 `outbox` 同时存在；queue 缺失必须单独报告 unhealthy，不能阻止 memory
invalidation，也不能把旧 summary 留在 clean 状态。空 names invalidation 是无副作用成功。
这些表是 health/evidence 表，不是另一套 gameplay fact authority。

`inspect_save_package()` exposes this as `projection_health`, a machine-readable evidence object. Required
projection items report stored status, effective status, version, expected version, `last_turn_id`,
alignment with `current_turn_id`, `last_error`, `updated_at` and artifact paths. The outbox summary reports
`ok`/`status`, schema or availability `errors`, status counts, plus every non-`done` row id, topic, status,
attempts, last error and timestamps. Missing or malformed outbox schema is reported as unhealthy evidence,
not as an empty clean queue.

### AI And Proposal Tables

| 表 | 职责 |
| --- | --- |
| `discovery_states` | Discovered clues, palette links and confirmation evidence. |
| `proposal_queue` | Proposal queue for non-immediate proposals. |
| `archivist_suggestions` | Archivist AI suggestions and audit payloads. |
| `intent_preflight_cache` | Advisory internal intent review cache. |

`intent_preflight_cache` stores identity-bound, single-use preflight review data. It may include player text,
external candidate hashes, rule candidate hashes, internal review and helper audit. It must not become a
commit authorization model.

### Resident AI Advisory Envelope

`ResidentAIAdvisory` 的 canonical schema id 是 `resident_ai_advisory:v1`。它是未来 resident helper、
adapter 或 owner 可消费的 JSON-safe contract representation；当前不选择存储 owner，不新增 SQLite 表、
repository、queue 或 lifecycle。

严格顶层字段：

| 字段 | 说明 |
| --- | --- |
| `advisory_type` | `intent_recognition`、`context_summary`、`entity_maintenance`、`progress_management` 或 `plot_progression`。 |
| `target_ids` | 有界、唯一的目标 entity/access-contract references；runtime trace id 不能替代 entity id。 |
| `evidence` | 只有 `kind`、`ref_id`、nullable as-of turn 的有界 references，不包含正文、prompt、delta 或 provider payload。 |
| `confidence` | `0.0..1.0` finite number，拒绝 bool、NaN 与 Infinity。 |
| `freshness` | `current/stale/unknown`、nullable as-of turn 与有界 source event ids；它是 freshness evidence，不是事实。 |
| `visibility_mode` | 只接受 `player`、`gm`、`maintenance`。 |
| `source_assistant` / `schema_version` | 窄 assistant 来源与固定 contract version。 |
| `proposed_next_workflow` | `none` 或五类受限 workflow hint，不是 callback、command、approval、confirmation 或 commit capability。 |
| `provenance` | 有界 trace/source references，仅供安全 maintenance/debug 使用。 |
| `authority` | Required const：advisory-only/no-direct-writes；write/approve/confirm/hidden/trusted-delta/save/profile/validation/commit capabilities 全为 false。 |

Player projection 不复用 maintenance representation。它只在精确 player view 和有效 SQLite connection
下，通过 Entity/Relationship/Progress access contracts 权威证明每个 target/evidence 可见，再从正向
allowlist 重建结果；hidden、archived、absent、unsupported 与 query failure 使用同一个 generic unavailable
形状，不泄露 id、alias、kind、数量或逐项 omission reason。通用 hidden redaction 是最后一道防御，不替代
inclusion check。Normalizer 和 serializers 不写数据库，也不 commit/rollback/close caller-owned connection。
`ResidentAIAdvisory` 的公开 frozen dataclass constructor 不代表已经验证；serializer 必须重新 normalization。
Player projection 不输出 confidence、freshness、source assistant 或 workflow hint，只输出经实际 entity subtype
对应 access contract 证明的安全 `kind/ref_id` 引用、固定 schema/authority 与通用 advisory/no-write 标记；
maintenance evidence 的 as-of turn 不进入 player projection，避免形成历史或未来时态的存在性提示。
已验证的结构化 player references 只对 bounded candidate IDs 做区分大小写的 exact canonical-ID redaction；
hidden name/alias、大小写变体或 ID 前缀均不得改变公开结果，也不加载全库 hidden corpus。
含事实表 TEMP shadow 的 SQLite connection 不具备 player projection authority，必须统一 fail closed。
权威 facts/access tables 必须来自 `main` schema；仅在 attached schema 中存在同名表的 connection 不是有效 Save。
Evidence/provenance 使用 canonical `prefix:id` references，freshness sources 使用 `event:` ids；直接构造的
authority flags 必须在 `to_dict()` 或 serializer 边界被拒绝，不能先洗白再当作已验证输入。
Evidence kind 必须与 `entity/rel/clock/world/rule/event/context/memory` reference namespace 对齐；authority
只接受 exact bool，as-of turn 只接受 exact bounded int，normalized collection 只使用 tuple。
Target ids 排除 commit/save/memory/session/projection 等 runtime/derived namespaces；同一 ref/as-of evidence 不得
用不同 kind 重复。JSON scalar subclasses 不是 canonical input。
Progress target/evidence 保持 `clock:` contract 对 nested-colon ids 的兼容；normalization 基于 preflight 后的
bounded copy，不继续读取 caller-owned mutable collections。
Provenance source ids 使用受限安全 namespace，不把 provider/session/prompt/hidden/commit/save 标识保存为安全
来源证据。
Clock advisory references 与现有 Progress contract 一样允许 nested/连续/尾随冒号；candidate/prompt/hidden
references 只能作为受限来源语义（如适用），不能伪装成 gameplay target。

#### Representative Adapter Mapping

| Existing output | Companion advisory | Mapping boundary |
| --- | --- | --- |
| successful exact `internal_intent_review` + final Kernel binding | `intent_recognition` / original binder view | first-seen canonical `entity_bindings`；high/medium/low 映射 0.9/0.6/0.3 |
| exact `StateAuditResult` + complete valid `tick_clocks` set | `progress_management` / maintenance | first-seen clock ids；confidence 固定 0.5，risk 不是 confidence |

两类 mapping 的 freshness 都是 `unknown/null/[]`，因为 intent helper 没有 canonical numeric as-of evidence，
而 state audit 检查的是尚未 commit 的 delta。Helper payload 与 envelope metadata 严格分离：player text、slots、
reason、findings、warnings、missing changes、delta、provider audit 与 prompt 不进入 envelope 或 digest。Adapter
不新增表、repository、storage owner 或 fact lifecycle；validation artifacts 中的 maintenance advisory 不是
proposal、delta、approval 或 commit token。

未迁移清单包括 semantic/context summary、Archivist、reflection、memory、entity maintenance、delta draft、
response acceptance、turn assistant 与 plot progression。AI suggestion -> review artifact 仍由 Story 4.6 管理，
plot progression 由 Story 4.7 管理，proposal queue lifecycle/apply/revert/report 由 Story 5.7 管理。

### Advisory Review Artifact

`AdvisoryReviewArtifact` 使用固定 `resident_ai_advisory_review:v1` contract，把 canonical advisory metadata 与
独立 candidate draft 绑定为显式、非权威 review evidence。内部 nested records 全部冻结为 tuple-based snapshot；
serializer 每次重建新的 exact JSON built-ins，caller 后续修改 input 或返回 dict 不会改变 artifact/digest。

固定字段包括 suggestion family/operation、disposition、target ids、candidate snapshot、只读 validation summary、
required gate、next owner、base turn、supersedes、rollback hint 与 source advisory。Authority 永远是
`current_fact_authority=false`、`application_authorized=false`、`proposal_approval_is_commit=false`。
`reviewable` 也只表示当前 preflight 可进入后续 owner，不代表 application authorization；实际 apply 必须重新
验证 current facts。

该 artifact 不新增表、migration、repository、proposal queue row 或持久 context source。`rejected`、`stale`、
`superseded`、`conflict` artifact 固定不可 application；maintenance projection 可见 bounded supersession/rollback
evidence，player projection 不输出 candidate、validation、rollback 或 source internals，并复用 authoritative
Entity/Relationship/Progress access contract 过滤 hidden/archived/missing targets。

## Entity Model

每个持久游戏对象都应该有稳定的 `entities.id`。

核心字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 稳定 entity id，通常带前缀，例如 `pc:...`、`loc:...`、`npc:...`。 |
| `type` | 实体类型。 |
| `name` | 面向人类的名称。 |
| `status` | 生命周期状态，例如 active 或 archived。 |
| `visibility` | 玩家可见性边界。 |
| `location_id` | 地点包含关系。 |
| `owner_id` | 所有者包含关系。 |
| `summary` | 简短权威描述。 |
| `details_json` | 未提升到 side table 的结构化额外字段。 |
| `updated_turn_id` | 最近更新该实体的 turn。 |
| `updated_at` | 最近更新时间戳。 |

活动实体不能同时设置 `location_id` 和 `owner_id`。

### Entity Access Contract

`rpg_engine/entity_access.py` 是当前 Entity Identity Access Contract 的命名实现。
它不拥有写入权威，只提供 common identity 读取和 runtime delta reference validation：

- `EntityRecord` 暴露稳定 common fields：`id`、`type`、`name`、`status`、`visibility`、
  `location_id`、`owner_id`、`summary`、parsed `details`、`updated_turn_id` 和 `updated_at`。
- `read_entity()` / `list_entities()` 默认排除 `status='archived'`，并按 caller view 应用
  visibility filter。player view 不能读取 player-hidden visibility label（`hidden`、`gm`、
  `gm-only`、`gm_only`、`gm only`）的 entity；GM / maintenance view 必须显式选择。
- Clock subtype 还必须检查 `clocks.visibility`。即使 `entities.visibility` 不是 hidden，
  `clocks.visibility` 是 player-hidden label 的 clock 也不能通过 player view access contract 读取。
- `validate_delta_entity_references()` 校验 runtime delta 中的 entity references；引用必须已存在，
  或属于同一 delta 的 `upsert_entities[*].id`。这覆盖 `location_before`、`location_after`、
  `meta.current_location_id`、entity `location_id` / `owner_id`、`character.species_id` 和
  `location.parent_id`、`crop_plot.crop_entity_id`。
- active entity 的 `location_id` / `owner_id` invariant 仍由 delta/content validation 执行；
  validated mutation 不能让同一个 active entity 同时位于某地又归属某 owner。

Relationship / Progress access contract 复用 `entities.id` 作为身份锚点，不新增并行
identity system，也不要求调用方直接依赖 table-specific storage 细节来读取 common fields。

### Relationship Access Contract

`rpg_engine/relationship_access.py` 是当前 Relationship Access Contract 的命名实现。
Relationship 仍以 `entities.type='relationship'` 存储，并把 `source_id`、`target_id`、
`kind`、`state`、`attitude`、`stance`、`trust` 等关系字段放在规范化 `details` 中；调用方应
使用 access contract，而不是直接解析任意 `details_json`。

- `RelationshipRecord` 暴露 stable relationship fields：`id`、`source_id`、`target_id`、
  `kind`、`state`、`attitude`、`stance`、`trust`、`visibility`、`status`、`summary`、parsed
  `details`、`updated_turn_id`、`updated_at`，以及可解析 endpoint records 和
  `endpoint_issues`。
- `read_relationship()` / `list_relationships()` 默认排除 archived relationship，并对
  player view 同时过滤 hidden relationship、hidden endpoint、archived endpoint 和缺失 endpoint。
  GM / maintenance view 必须显式选择；这类 view 可以读取 hidden endpoints，但 archived 或缺失
  endpoints 只会作为 `endpoint_issues` 报告，不会作为 normal endpoint record 返回。
- Runtime delta 中 `upsert_entities[*].type == "relationship"` 时，`details.source_id` 和
  `details.target_id` 必须存在、是合法非空 entity id，并且引用已存在 entity 或同一 delta 中创建的
  entity。该校验通过 `validate_delta_schema(..., conn)` 的 database reference gate 执行，并由
  maintenance/content delta validation 对 relationship-shaped `upsert_entities` 复用。
- Relationship suggestions from AI, maintenance assistants, package tooling, or proposal workflows are
  advisory until they enter an explicit validated mutation, proposal, or maintenance path. Relationship
  access helpers do not grant confirmation, validation bypass, proposal approval, or commit authority.

### Progress / Clock Access Contract

`rpg_engine/progress_access.py` 是当前 Progress Track / Clock Access Contract 的命名实现。
Progress v1 仍以 `entities.type='clock'` 加 `clocks` side table 存储，并继续通过
`tick_clocks` delta 推进；调用方应使用 access contract，而不是直接依赖 clock storage 细节。

- `ProgressRecord` 暴露 stable progress fields：`id`、`kind` / `clock_type`、`scope`、
  `segments_total`、`segments_filled`、`visibility`、`status`、`summary`、
  `trigger_when_full`、parsed `tick_rules`、parsed `details`、`last_ticked_turn_id`、
  `updated_turn_id` 和 `updated_at`。
- `read_progress()` / `list_progress()` 默认排除 archived clock entity，并复用
  `entity_access` 的 clock subtype visibility behavior。player view 同时过滤
  `entities.visibility` 和 `clocks.visibility` 上的 player-hidden label；GM / maintenance view
  必须显式选择。
- Runtime delta 中 `tick_clocks[*].id` 必须引用存在且未 archived 的 clock。caller view 为
  player 时，hidden clock entity 或 hidden clock side table row 会被报告为 unavailable。
  Runtime tick id 使用 `clock:[A-Za-z0-9_.:-]+` 合同，并与 Campaign clock validation、
  proposal validation 和 packaged `turn_delta.schema.json` 保持一致。`tick_clocks[*].reason`
  是必填安全可见的非空字符串，用于解释该 tick；progress change 仍需要 event audit row
  记录状态变化。
- Turn delta 不得通过 `upsert_entities` 写入 `id='clock:*'` 或 `type='clock'` 的 entity，
  也不得借伪装 type 修改 clock entity 的 summary、status、visibility 或其他 progress-facing
  字段。Campaign / package clock definitions 仍走 content type path；runtime progress mutation
  仍只走 `tick_clocks`。
- Narrative-only progress claims 不具备事实权威。event/title/summary、top-level summary、
  payload 中的 clock/progress update 声称，以及已知 clock name 加 update 动词的叙事，都必须
  对应结构化 `tick_clocks`，否则 validation 会拒绝。
- Progress / clock suggestions from AI, maintenance assistants, package tooling, or proposal workflows
  are advisory until they enter an explicit validated mutation, proposal, or maintenance path. Progress
  access helpers do not grant confirmation, validation bypass, proposal approval, or commit authority.

### Cross-Campaign Model Boundary Smoke

跨 Campaign model-boundary smoke 使用至少两个不同 capability profile 或 genre assumption 的
Campaign Package，在临时 Save Package 上验证同一套模型合同：

- Campaign validate/test、Save init/inspect、Content Type / Merge、Entity、Relationship 和
  Progress access 都走同一组 kernel APIs。
- 玩法差异通过 package data 表达：capabilities、registered content roots、rules、
  relationship details/kinds、clock/progress records、palettes、random tables 和 smoke tests。
- SQLite schema、fact authority 和 player confirmation boundary 不因 campaign 题材变化而 fork。
- 写入类 smoke 必须使用 temporary save copy，并保留 source Campaign Package no-mutation 证据。

当前 model-boundary focused regression 是 `tests/test_cross_campaign_model_smoke.py`。

Story 3.7 另以 `tests/test_cross_campaign_context_smoke.py` 验证完整 context assembly、basic query
和 player-safe play loop。它在两个独立 temporary workspace/Save 上复用同一
`ContextBuildResult` pipeline/collector contract、player visibility filtering、`GMRuntime` preview/validation
与 `SaveManager.player_turn -> pending -> player_confirm -> validation/commit` 链。测试分别证明
query、context assembly、preview、validation 和 pending creation 不修改 authoritative facts，错误
session id 被拒绝，只有正确 confirm 会增加 turn/event。每个 player result 都检查
Campaign 自带 hidden canary，失败 evidence 只报告安全的 campaign/save/stage/context-source/
visibility-mode，不复制 hidden 正文。写入仅发生在 temporary Save，仓库 source Campaign
和 configured/registered formal current Saves 前后 fingerprint 必须一致；该 postcondition 在早期失败时也会执行。

### Typed Side Tables

Typed side tables 增加结构化字段，但不替代 entity row：

- `characters`
- `items`
- `locations`
- `crop_plots`
- `clocks`
- `rules`
- `world_settings`

如果 side table 存储玩家可见内容，它仍必须服从 entity visibility 边界。

### Visibility

玩家可见 search、context 和派生 read model 不能包含 hidden / GM-only facts。

当前 FTS rebuild 规则：

- Include `entities` where `status != 'archived'`.
- Exclude player-hidden visibility labels（`hidden`、`gm`、`gm-only`、`gm_only`、`gm only`），并对
  clock subtype 的有效 visibility 做同样检查。
- Index name, summary, details JSON and aliases after hidden entity ref redaction.

Cards、snapshots、FTS/search、scene/query 和 onboarding 输出必须遵循同一 player-view 原则。
隐藏当前位置可以在玩家入口中渲染为安全占位，但不能把隐藏 id、名称、摘要或 alias 放进玩家产物。
GM 或 maintenance 视图必须显式选择。

### ContextBuildResult And Context Audit

`memory_summaries` 是派生上下文，不是当前事实权威。每条 summary 必须记录 summary type、
source event ids、source turn ids、visibility mode、freshness status / reason、freshness evidence 和
derived authority evidence。SQLite `entities`、relationships、progress/clocks 和 `meta` 等 current-state
tables 中的当前事实始终优先；committed events 只提供 provenance/audit evidence，不能覆盖当前状态。当
memory summary 的 subject 已更新、缺失、archived、hidden-unavailable 或与
当前事实冲突时，context assembly 必须把 summary 标记为 stale/omitted 或交给 advisory review，而不能用
summary 覆盖当前事实。`reports/memory-current.md` 和 projection `memory` health 是可重建读模型证据。
Canonical summary type 为 deterministic day/world/character/project/faction/fallback 类型；缺失 legacy 值可
按 kind 推断，未知非空值必须显示为 `unknown`。Player report 必须呈现安全 source events/turns、freshness
evidence 与 clamped derived authority，不能返回原始 provenance JSON。若 memory projection 早于 provenance
migration、非 clean、重复/损坏或与 current turn 不一致，summary lookup 只返回通用 fallback evidence。
Player row 由固定字段 allowlist 重建，未知 kind 映射为 `unknown`；source turn location refs、过期或逆序的
validity window、过量 provenance refs，以及 lookup/context render 期间变化的 projection/current-turn snapshot
都必须 fail closed。最终 context gate 必须同步移除 memory section、memory-derived plot signals、loaded evidence，
并重建 omission/completeness/budget/markdown，不能返回混合 generation。每次 budget pass 在独立 render-state
副本上过滤 plot signals，不能污染 collector state；连续变化超过重试上限时，必须冻结为不再读取 projection
的 generic `projection_memory_unstable` fallback。Subject evidence 必须绑定 row subject，
且其 `subject_updated_turn_id` 必须精确对账 authoritative entity；validity bounds 及仅复制 bound 的 scalar turn
不计作 freshness provenance。Player direct render/redactor/omitted-item 边界都必须重新执行 visibility/hidden-id
检查；maintenance/hidden omissions 合并为一个 generic signal，不能暴露数量或分类。

`projection_state.updated_at` 同时是 projection lifecycle 的 generation token，正常值保持单调。
`refreshing -> clean/failed` 必须使用 status + generation compare-and-swap；same-turn fact maintenance 产生的
新 dirty generation 不可被旧 refresh 覆盖。最大可表示 timestamp 等异常 metadata 必须轮换为不同、可解析的
token，不能让投影元数据回滚事实事务；metadata writes 必须由 savepoint 与 authoritative writes 隔离并保留
caller 的 commit/rollback ownership。同一 campaign/projection 的 database/file publication 采用跨线程/进程锁
序列化并有界等待，events outbox 与全量 JSONL rewrite 共享 target lock；最终 report 只可把最终 effective status
仍为 clean 的 item 列入 `refreshed`。dirty-only report 仍以原始 requested set 对账，不能把采样后变 dirty 的 skipped
projection 报成 clean。`projection_state` 与
`outbox` 的运行 SQL 显式使用 `main`，TEMP aliases 不能改变 machine-readable 或 rendered health。
Canonical schema 允许不会阻止标准 insert/upsert 的 nullable 或 safe-literal-default additive columns，但拒绝
额外主键、无 default 的必填普通列、可执行 default、generated columns、非 canonical UNIQUE、任意
expression/partial/custom-collation index、额外 FK/CHECK/main-or-TEMP trigger，以及非 BINARY canonical
projection identity。Identifier
匹配采用 SQLite ASCII case-insensitive 语义，不能用 Unicode `casefold()` 把伪同名扩展当成 canonical column。
`memory_summaries` 还要求 canonical FK signatures/actions 与 `(kind, subject_id)` lookup index；`0009` additive
migration 必须限定 `main`、拒绝所有 statement targets 的 TEMP shadow/write-blocking CHECK/COLLATE/trigger constraints，
并以严格 JSON type 区分 boolean 与 `0/1`。Migration ledger 固定为 `main.schema_migrations`；helper table、metadata
columns 与 canonical index 必须在同一 savepoint 内完成或整体回滚。Player-visible memory IDs 也必须扫描 hidden
entity id/name/alias substrings；malformed non-hidden omission IDs 使用互不冲突的 opaque fallback IDs。

`rpg_engine.context_builder.ContextBuildResult` 是当前 Context Slice 合同。`build_context()` 先产出该结构，
再由 CLI、runtime query、start-turn result、prompt/render path 消费它；不要在下游重新查询事实来拼另一套
prompt context。

当前稳定输出字段：

| 字段 | 说明 |
| --- | --- |
| `contract` | Context contract metadata：`id=ContextBuildResult`、版本、visibility mode、audit tables、pipeline steps、collector sources 和 authority note。 |
| `scope` | 本次 request scope：玩家文本、mode/submode、visibility mode、预算、event/depth 限制、AI helper 设置和来源。 |
| `request` | 路由、intent、turn contract、decision trace、visibility 和 helper trace。 |
| `budget` | 请求/effective 预算、策略 profile/reason、section token evidence、included/omitted keys、确定性 `decisions`、overflow/utilization 和 trimmed 状态。 |
| `completeness` | allow/confidence、missing required、high-value `missing_signal_evidence`、有界 `quality_diagnostics`、confirmation needs、clarification 和 assumptions。 |
| `loaded_items` | included item evidence；每项包含 `id`、`kind`、`source`、`provenance`、`reason`、`visibility`、`priority`、`depth` 和 budget evidence。 |
| `omitted_items` | omitted/default-forbidden evidence；每项同样包含 source/provenance/visibility/budget reason。 |
| `sections` | 已选 context sections 的 render text。 |
| `markdown` | 面向人类或 prompt 消费的渲染结果。 |

`context_runs.output_json` 保存完整 `ContextBuildResult.to_json_text()`，用于解释某次 context 为什么包含或省略内容。
`context_items` 保存 item-level audit rows；`included` 表示 included/omitted，`source` 保存真实来源
（例如 `entity_resolution`、collector source 或 `default_policy`），不是事实权威。Section evidence 使用
`section:<key>` item id，避免与真实事实 item id 冲突；token budget omission 的原因保存在 item budget
evidence 中。如果合法内容 id 与同 run 内其他 evidence 的 `(item_id, source)` 仍然相同，`context_items.item_id`
会使用 audit-only disambiguation；原始 evidence id 保留在 `context_runs.output_json`。Context audit 是
opt-in 诊断证据：默认 `build_context()`、`GMRuntime.start_turn()` 和普通 query 不写 audit rows；启用
`audit_context=True` 也不能推进 turn、event 或 gameplay facts。

`budget.decisions` 的每项固定记录 section key、required、priority、estimated tokens、included、reason 与稳定
`reason_code`；`trimmed` 只表示至少一个 `reason_code=over_budget` 的真实 token trimming，dependency unavailable
仍会出现在 `omitted_sections`，但不会改变旧 `trimmed` 语义。
`over_limit` / `overflow_tokens` 对最终 included tokens 与 effective limit 计算，required section 自身超限另以
`required_over_limit` / `required_overflow_tokens` 记录。Token-budget omitted evidence 的 effective priority
至少为 70，或 required sections 自身超限时，才会产生 high-value advisory；按 `(code, source, signal)` 去重、
确定性排序且最多 8 条，只进入 `completeness.missing_signal_evidence`。

`completeness.quality_diagnostics` 每项固定包含 `code`、`severity`、`source`、`subject_kind`、安全
`subject_id`、`missing_fields`、`reason`、`visibility`、`provenance` 与 `advisory_only=true`。它只描述本次
visibility-safe context 的 missing summary/alias、relationship endpoint、progress metadata、memory freshness 或
结构化 budget tradeoff；按稳定 key 去重排序且最多 32 条，不做 prose/taste scoring。该 evidence 不是 SQLite
事实权威，不能改变 allow/confidence/confirmation 或写入授权。`context_runs.output_json` 保存这些最终字段；
source 诊断异常使用优先保留的 `severity=error` unavailable sentinel，但仍保持 `advisory_only=true`；
`context_items.estimated_tokens` 对 included 与 omitted rows 都保存 item 已有的安全 token evidence，仍不新增事实表，
audit 也继续保持 opt-in、同 snapshot、同 view、同 budget pass。所有 context audit DDL/DML 显式限定 canonical
`main.context_runs` / `main.context_items`；TEMP shadow 不得接收、覆盖或分流 audit evidence。

新增 context source 必须声明 visibility、provenance 和 budget behavior，并通过 `ContextBuildResult`
输出和 audit 记录，不得绕过 `visibility.py`、context pipeline 或 access contracts。

Story 3.4 后，relationship、progress/clock 和 plot progression signal 也是明确的 context source：

- `relationships` 通过 `relationship_access.py` 读取 relationship records，并把 included / omitted
  relationship evidence 写入 `loaded_items` / `omitted_items`。Player view 同时过滤 hidden relationship、
  hidden endpoint、archived endpoint 和 missing endpoint；hidden / GM-only 或 unavailable relationship
  不在 player-safe omission evidence 中暴露存在或数量。GM / maintenance view 可用脱敏 `reason_code`
  区分 `hidden`、`missing_reference`、`archived`、`conflict` 和 `over_budget`。
- `progress_context` 通过 `progress_access.py` 读取 progress / clock records，并把相关 active tracks、
  world-setting linked clocks、recent activity 和 action-submode 相关 tracks 写入 context evidence。Player
  view 同时过滤 hidden clock entity 和 hidden `clocks.visibility` side-table rows；hidden / GM-only
  progress 不在 player-safe omission evidence 中暴露存在或数量；ordinary player view 只保留 visible
  over-budget omission evidence，`missing_reference`、`archived` 和 `conflict` structural categories 只在
  GM / maintenance debug view 可检查。
- `plot_signals` 只从已按当前 view 过滤后的 relationship、progress、world settings、rules、routes、
  palette candidates、discovery states、events、memory summaries、character goals、project summaries 和
  Campaign light hooks / goals / clues / project summaries 中派生。它是 `advisory_only` context evidence，
  不是事实权威、clock tick、proposal approval、mandatory storylet 或 automatic director command；若其
  relationship/progress source section 因 budget 被省略，对应 plot signal 也必须省略并写入 omission evidence。

Memory summaries 现在携带 `visibility_mode` 和 freshness metadata，但仍不拥有独立 hidden authority；
player-safe collection 继续跳过含 hidden entity refs 的 memory/event rows，并通过 omitted item evidence
说明 stale、missing table 或 lower-quality fallback。GM / maintenance view 可以检查脱敏 stale reason。
Player view 只接受显式 `visibility_mode=player` 和完整 metadata schema；empty 与 hidden-only summary 集合使用
同一通用 fallback，避免形成 hidden existence oracle。

Player-safe context、ordinary query、scene output 和 player-safe AI/helper prompts 必须在 collection
或 query 阶段排除 hidden / GM-only material。最终 render redaction 只能作为 defense-in-depth，不能成为
唯一防线。GM / maintenance reads 必须显式选择 `gm` 或 `maintenance` view；同一 save 上的 trusted
context、audit upsert 或 helper result 不能被复用到 player view。没有独立 visibility 字段的 event 或
memory material 不承载独立 hidden 权限；hidden / GM-only 事实必须通过 hidden 或 archived entity refs
表达。Player view collection 必须跳过包含 hidden entity refs 的 event / memory rows，且
`ContextBuildResult.contract.visibility_invariants` 必须记录 `events` 的
`structured_visibility: not_applicable` 证据，以及 `memory_summaries` 的 `visibility_mode` metadata
证据。若后续要让 event / memory summary 承载不绑定实体的
GM-only 自由文本，必须先新增结构化 visibility / sensitivity 字段和迁移，不能静默混入当前 player-safe
context 或 prompt。

## Turn And Event Model

### Turn

`turns` 记录已接受的 turns。

重要字段：

- `id`
- `session_id`
- `user_text`
- `intent`
- `game_time_before`
- `game_time_after`
- `location_before`
- `location_after`
- `summary`
- `changed`
- `command_id`
- `command_hash`
- `expected_turn_id`

`command_id`、`command_hash` 和 `expected_turn_id` 支持 write guards 与幂等。
同一 `command_id` + 同一 canonical payload hash 的 durable row 会分类为
`write_status=already_confirmed`；同一 command + 不同 payload 必须 conflict。该分类来自 SQLite，不来自
workspace receipt。

### Event

`events` 记录权威审计事件。

重要字段：

- `id`
- `turn_id`
- `game_time`
- `type`
- `title`
- `summary`
- `payload_json`
- `source`
- `created_at`

`events` rows 是权威记录。`data/events.jsonl` 通过 projection/outbox 逻辑从这些 rows 生成。

## Turn Delta

Turn delta 是 `save_turn_delta()` 和 commit services 消费的已校验写入 payload。

允许的顶层字段：

- `turn_id`
- `session_id`
- `user_text`
- `intent`
- `changed`
- `summary`
- `game_time_before`
- `game_time_after`
- `location_before`
- `location_after`
- `events`
- `upsert_entities`
- `tick_clocks`
- `meta`
- `expected_turn_id`
- `command_id`

必填字段：

- `user_text`
- `intent`
- `summary`

写入规则：

- A changed turn must include events or state changes.
- A state-changing delta should include at least one event explaining the change.
- `meta` values must stay scalar.
- `tick_clocks` must reference existing clocks.
- Entity references must already exist or be created in the same delta.
- `command_id` and `expected_turn_id` are required for `player_turn_commit`.

## Content Type Registry

Content registry 映射 campaign YAML、delta keys、runtime tables、validation rule 和 merge policy。

当前 default registry：

| 名称 | Campaign key | YAML key | Delta key | Entity type | Table | Sync safe | Validation | Merge policy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `entity` | `entities` | `entities` | `upsert_entities` |  | `entities` | no | record | author-owned name/summary/visibility; runtime-owned status/location/owner/typed side data; aliases merge; id/type/details conflict-only |
| `rule` | `rules` | `rules` | `upsert_rules` | `rule` | `rules` | no | record | author-owned statement/scope/priority/examples/exceptions; aliases merge; id conflict-only |
| `clock` | `clocks` | `clocks` |  | `clock` | `clocks` | no | record | author-owned clock definition; runtime-owned filled segments and last tick; aliases merge; id conflict-only |
| `route` | `routes` | `routes` | `upsert_routes` |  | `routes` | no | record | author-owned endpoints/travel requirements; runtime-owned verification turn; id conflict-only |
| `relationship` | `relationships` | `relationships` |  | `relationship` | `entities` | no | record | author-owned endpoints/summary/state/stance; runtime-owned trust/status; aliases merge; id/details conflict-only |
| `world_setting` | `world_settings` | `world_settings` | `upsert_world_settings` | `world_setting` | `world_settings` | yes | record + database | author-owned setting content; linked lists merge; id/status conflict-only |

Delta schema 允许的 entity `type` 多于 registry 当前作为一等 content type seed 的类型。
不要把每个允许的 entity type 都当成已注册 package content type。例如 `character`、`item`
和 `location` 是 `entities` content type 中的 entity records，不是 `campaign.yaml.content`
下的独立 `characters`、`items` 或 `locations` roots。

Package validation、diff、install 和 upgrade 必须使用 registry seed specs 检查 registered
content roots。`random_tables` 和 `palettes` 是当前合法 auxiliary author content，但不会被伪装成
registry content records。未知 `campaign.yaml.content.*` key、绝对路径或 package root escape
必须拒绝，不能在 package workflow 中静默忽略。

`python3 -m rpg_engine content inspect-type <name>` 会从 `ContentTypeSpec` 输出 lifecycle、
record/database validation、merge policy ownership buckets 和 presentation contract。该输出是
检查 schema drift 的运维入口；不要维护第二份手写 content type 真值表。未列入 merge policy
bucket 的字段默认按 `conflict-only` 处理，需要 migration 或显式维护决策。

## TurnProposal

`TurnProposal` 是 preview 与 commit 之间的桥。只有 validation 和 `player_confirm()` 成功后，
它才可能变成已提交事实。

允许字段：

- `proposal_id`
- `intent`
- `context_id`
- `preview`
- `response_text`
- `facts_used`
- `narrative_claims`
- `delta`
- `delta_source`
- `provenance`
- `human_confirmed`
- `turn_contract`

允许的 `delta_source` 值：

- `resolver_proposed`
- `ai_generated`
- `human_edited`
- `response_draft`
- `maintenance_delta`

玩家提交要求 `human_confirmed=true`，并且 `TurnContract` 匹配 player commit profile。

## Intent And Turn Contract

`ActionIntent` 表示已路由的玩家请求：

- `user_text`
- `mode`
- `submode`
- `action`
- `options`
- `confidence`
- `source`
- `alternatives`
- `missing_required`
- `needs_confirmation`
- `decision_trace`
- `kind`
- `status`
- `player_message`
- `plan`
- `repair_options`
- `clarification`

`TurnContract` 把已路由 intent 绑定到回复和 validation 期望：

- `intent`
- `required_template`
- `response_headings`
- `requires_preview`
- `must_save`
- `allowed_delta_sources`
- `validation_profile`

这些模型是合同，本身不写入事实。

## Validation Report

`ValidationReport` 记录某个 delta/proposal 是否能在指定 profile 下继续。

当前 validation profiles：

- `preview_only`
- `player_turn_commit`
- `response_acceptance`
- `maintenance_commit`
- `admin_or_legacy_save_turn`
- `import_or_migration`

当前 stages 包括：

- profile
- write guard
- proposal guard
- delta schema
- capability
- resolver request
- resolver resolution
- resolver delta contract
- response lint
- response consistency
- state audit

Validation reports 是证据。除非 commit 成功，否则它们不会变成当前事实。

## Projection Report

`ProjectionReport` 记录派生 artifacts 的刷新状态。

已知 projections：

- `events_jsonl`
- `search`
- `snapshots`
- `cards`
- `memory`
- `reports`
- `package_lock`

Projection reports 可能包含 profile、requested、refreshed、skipped、requested/global
dirty/failed/stale、outbox_status/counts/non_done/errors、artifact、item、started/finished time 和 duration
字段。`global_status` 必须纳入 outbox health；targeted projection repair 不能把未修复的 outbox failed
work 隐藏成 global clean。
这些字段描述 projection health，不改变已提交事实的含义。

`inspect_save_package()` 的 `authority_contract` 和 `projection_health` 字段把这些职责暴露为机器可读合同：

| Contract key | Authority |
| --- | --- |
| `current_fact_authority` | `data/game.sqlite`，当前事实权威。 |
| `authoritative_audit` | SQLite `events`，权威审计记录。 |
| `audit_projection` | `data/events.jsonl`，derived audit projection。 |
| `snapshots` / `cards` / `search` / `memory` | derived read models。 |
| `projection_state` / `outbox` | projection health 或 work-queue evidence。 |
| `workspace_registry` / `pending_state` | workspace/player entry state。 |
| `preflight_cache` | advisory AI intent cache。 |
| `mcp_audit_logs` / `archive_manifest` | call/archive evidence。 |

## SaveManager Registry

Workspace registry 位于：

```text
<workspace>/.aigm/save-registry.json
```

Registry 字段：

- `schema_version`
- `active_save_id`
- `campaigns`
- `saves`

Campaign records 包含 id、name、path、可选 starter save path 和 status。Save records 包含 id、
campaign path、save path、label、kind、source、current turn/time/location summary、health
以及 inspection/play metadata。

Registry paths 必须是 workspace-root relative，且不能是绝对路径，不能包含 `..`、反斜杠或 resolved
root escape。Registry state 只选择 Save Package，不拥有游玩事实。`current_save(refresh=False)`
可以返回 registry cached summary，但结果必须用 `current_save_authority` 标明 `summary_source=registry_cache`
且 `summary_authoritative=false`；需要 authoritative facts 时必须 refresh 或读取 Save SQLite。

## Platform Session Binding State

`.aigm/game-session-bindings.json` 是 workspace runtime state，不是 Save Package 或事实库。每条 binding
保存 hashed platform/session/user identity、active Save path、状态/TTL、最近 message/action/confirm id，
以及 monotonic state `revision`。Start/act/deactivate/expiry reservation 或 completion 推进 revision；同一
confirmation 的 message reservation 与 advisory prewarm 只更新 message/correlation 字段并保留 state
revision。所有 RMW 使用同一跨线程/进程、进程退出自动释放的 OS lock。

Binding 可保存 `pending_confirmation_session_hash` 与
`pending_confirmation_revision`、`last_completed_confirmation_session_hash`。Pending revision 记录该
confirmation 所属的操作 generation；start/act 等新权威操作推进 binding revision 后，旧 confirmation
即使稍后返回也不能完成旧 generation。它们只用于识别“SQLite 已 durable，但 fresh platform
completion 尚未落地”的同一 confirmation：匹配 replay 只补状态 transition 并保持原 TTL。Hash 不授予事实、
玩家确认、proposal approval 或 commit authority；Save、revision 或状态已变化时必须保留较新的 binding。
兼容旧 schema 的回填仅限 correlation 为空、binding/pending revision 均为 0、Save/state 精确匹配，且
SaveManager owner result 回传同一 confirmation hash；任何已存在的新权威 revision 都关闭该兼容路径。

## Pending Player State

SaveManager 在 `.aigm/` 下存储临时玩家入口状态：

```text
.aigm/pending-player-action.json
.aigm/pending-player-clarification.json
.aigm/pending-player-action.lock
.aigm/last-confirmed-player-action.json
```

Pending action 绑定：

- `session_id`
- `save_id`
- `save_path`
- `user_text`
- `action`
- `delta`
- `turn_proposal`
- optional platform/session identity hash

只有 proposal ready to confirm 时，`player_turn()` 才写 pending state。`player_confirm()` 在提交前
必须匹配 pending session、save 和可选 platform/session identity。

确认开始后，pending action 可增加 `confirmation_claim`，其中只有 schema、save id/path、confirmation 与
platform/session/actor hashes、command id、delta/proposal digest 与自校验 digest；claim digest 还锚定到
目标 Save SQLite meta。`last-confirmed-player-action.json` 是最多 4 KiB 的单条
replay evidence，包含 save identity/path、hashed confirmation/platform/session/actor identity、command
id/hash、delta/proposal digest、turn id、event count 与 result classification。二者均不属于 Save Package
事实模型；receipt 的完整摘要锚定在目标 Save SQLite `meta`，replay 必须同时复核该 anchor 与
turn/command/event evidence，不能靠可重算的 workspace 自摘要授权。

Pending `confirmation_claim` 还用于区分“TTL 到期且从未提交”与“已 durable、等待 reconcile”：后者不得按
expired pending 删除。Replay permission 默认拒绝；只有带 `confirmed_via=player_confirm`、非空
confirmation session 且通过 SaveManager identity/payload 校验的 proposal，才可进入 authoritative replay
分类。

## Archives And Schemas

`.aigmsave` archives 包含 `save-archive.json` 和清单列出的核心文件。Manifest 记录文件、大小和
checksum，让 import 能拒绝未列出或损坏的成员。
Archive member path 不能是绝对路径，不能包含 `..` 或反斜杠；manifest 未列出的成员、
缺少核心 Save 文件、size mismatch 和 checksum mismatch 都必须拒绝，且失败 import 不能替换目标目录。
缺少核心 Save 文件必须在 payload member 解包前拒绝。

Public JSON schemas 同时存在于 source-facing 和 packaged resource 位置：

- `schemas/`
- `rpg_engine/resources/schemas/`

当前 schema files 包括 campaign、smoke、capabilities、random tables、turn delta、content delta、
save patch、state audit、semantic suggestion、archivist 和 reflection drafts。Intent candidate
和 internal intent review schemas 位于 packaged resources。

Schemas 描述 interchange formats。Runtime code 仍执行额外的代码级校验、引用校验和 profile 校验。

## Development Checklist

修改数据模型前，回答这些问题：

- Does the change alter `data/game.sqlite` fact authority?
- Does it require a migration and migration checksum?
- Does it preserve `save.yaml`, `campaign.yaml` and SQLite meta compatibility?
- Does it keep hidden content out of player view, FTS, cards, snapshots and onboarding?
- Does it distinguish facts from projections, registry state, archive manifests and AI caches?
- Does it preserve `player_turn -> pending/no save` and `player_confirm -> commit`?
- Does it require updates to public JSON schemas?
- Does it require current native package tests or migration/validation tests?

## Suggested Focused Gates

数据模型行为改动应选择最小相关测试集：

```bash
python3 -m pytest -q tests/test_validation_pipeline.py tests/test_projection_service.py
python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_write_safety.py
python3 -m pytest -q tests/test_current_native_visibility.py tests/test_save_manager.py
python3 -m pytest -q tests/test_cross_campaign_model_smoke.py
python3 -m pytest -q tests/test_package_cli.py tests/test_package_merge.py tests/test_package_save_condition_coverage.py
python3 -m pytest -q tests/test_ai_intent.py tests/test_preflight_cache.py
```

文档-only 变更运行：

```bash
git add -N docs _bmad-output
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```
