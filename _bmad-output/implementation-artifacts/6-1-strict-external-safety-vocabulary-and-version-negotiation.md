---
baseline_commit: 1141404b2ddb6cc1f16c1126761d40d508f790ee
story_id: "6.1"
story_key: "6-1-strict-external-safety-vocabulary-and-version-negotiation"
epic_id: "6"
created: "2026-07-13"
---

# Story 6.1：严格外部安全词表与版本协商

Status: done

## Story

作为 external AI 集成者，
我希望 external safety vocabulary validation 和版本协商严格 fail closed，
从而避免 unknown flag 或 rolling upgrade 静默削弱 Kernel trust boundary。

## Acceptance Criteria

1. **Unknown external safety flag 在 ingress 明确失败**

   **Given** external intent candidate 的 `safety_flags` 含 active versioned vocabulary 之外的值
   **When** external candidate boundary 校验 envelope 并进入 normalization
   **Then** Kernel 在 tolerant normalization、internal helper、arbitration、binding、preview 之前以结构化 `unknown_safety_flag` 失败
   **And** unknown flag 不得被静默删除、adopt、route、preview 或转换成新的 pending state。

2. **显式 contract mismatch 可重试但不可继续 routing**

   **Given** caller 提供的 manifest schema version/digest 或 safety-vocabulary version/digest 与当前 provider 不一致
   **When** external candidate 到达 provider contract boundary
   **Then** Kernel 返回结构化 `contract_version_mismatch`，标记 `retriable=true`，并要求 `refresh_manifest_and_regenerate_candidate`
   **And** 即使 candidate 只含 empty/known flags，也不得 fallback、调用 helper、进入 arbiter、preview 或创建新的 pending action。

3. **Legacy caller compatibility 不允许 unknown fail open**

   **Given** compatibility-window caller 整体省略 contract provenance
   **When** candidate 其余 schema 合法且所有 safety flag 属于 active allowlist
   **Then** provider 可以按 `legacy_unversioned` compatibility policy 继续现有 off/consensus 路径
   **And** 省略 provenance 但含任意 unknown flag 时仍必须返回 `unknown_safety_flag`，不能因兼容窗口放行。
   **And** Story 6.1 的默认值固定为 `legacy_unversioned_allowed=true`，由 manifest v2 对 caller 明示；它不是 CLI、MCP 或单次请求可覆盖的开关，只能由后续获批的 Correct Course 配合 manifest schema version bump 关闭。

4. **Safety vocabulary 只有一个 canonical owner**

   **Given** schema、external validation、tolerant internal/rules/domain-compatibility normalization、risk、arbiter、manifest 和 internal prompt 需要表达 safety vocabulary
   **When** parity 与 digest gates 运行
   **Then** active values、version 和 digest 来自一个 canonical safety-contract owner；静态 JSON Schema enum 如无法动态生成，必须由 executable parity test 证明完全一致
   **And** 当前六个 known flags 的 off/consensus 行为保持不变。

5. **Manifest/candidate wire contract 与 digest 稳定**

   **Given** Kernel 构建 intent manifest 或校验带 contract provenance 的 external candidate
   **When** 相同 contract inputs 在不同调用/进程中被 canonical serialization
   **Then** manifest 与 safety-vocabulary digest 使用确定性 SHA-256 lowercase hex，字段排序与 wire list/tuple 表达稳定，digest 不包含自身或任何 volatile timestamp
   **And** safety vocabulary 变化会改变 vocabulary digest 和 manifest digest；action taxonomy 如何进入 resolved projection 仍由 Story 6.2 完成。

6. **公开错误结构稳定、脱敏且 adapters 保持薄**

   **Given** direct Python/Runtime/SaveManager、MCP player/developer 或 CLI 遇到 unknown safety 或 contract mismatch
   **When** 错误被映射到公开结果
   **Then** direct Python/Runtime/SaveManager 保持 typed `ValueError` subclass；MCP/CLI public error detail 包含稳定 machine code/reason、retryability 和 bounded recovery action，且不回显 raw candidate、raw flag、slots、reason、player text、session key、provider body 或 hidden context
   **And** 只有 MCP/V1 CLI/legacy CLI command boundary 投影 Kernel typed contract error；direct `SaveManager.player_turn()` 与其他 direct Python/Runtime 入口传播同一 typed exception，任何 surface 都不复制 vocabulary 或 version comparison 业务逻辑。

7. **既有 authority、mode 与数据边界不回退**

   **Given** empty/known safety candidate、known blocker、healthy consensus、internal unavailable 或 explicit off 场景
   **When** Story 6.1 回归矩阵运行
   **Then** external AI 仍是 low-trust route proposal；healthy consensus 对 external-only safety 自述的既有 review 语义、known blocker、enabled-mode degradation、off-mode external-primary 和 no-external rules fallback 保持当前合同
   **And** binder、resolver、hidden visibility、pending、player confirmation、validation、commit、preflight CAS/identity 和 SQLite fact authority不改变。

## Tasks / Subtasks

- [x] Task 1：建立 RED characterization、threat/consequence 与 compatibility matrix（AC: 1-3, 7）
  - [x] 翻转 `tests/test_ai_intent.py` 中当前把 `unknown_flag` 静默裁剪掉的 characterization：external ingress 必须失败；保留明确的 tolerant internal/legacy normalizer characterization，防止误把所有 candidate source 全局 strict 化。
  - [x] 覆盖 empty、每个 known flag、unknown-only、known+unknown、duplicate、大小写/前后空白；external wire token 使用精确、case-sensitive canonical lowercase，duplicate、case variant 和 whitespace variant 均视为非法 external input。
  - [x] 覆盖 off 与 consensus：off known blocker 保持 blocked；consensus internal-confirmed danger 保持 blocked；healthy consensus 的 external-only known signal 仍可由 internal review clear 并保留 trace；unknown 不得被 internal review clear。
  - [x] 完成 consequence probe：证明 unknown/mismatch 在 helper/arbitration/binder/preview 之前失败，不能产生新的 pending、preflight cache row、turn/event/fact 或 commit evidence。结论保持“已复现 strict-validation/future-compatibility fail-open gap”；除非 probe 证明实际 unsafe consequence，不升级为已发生 security incident。

- [x] Task 2：建立单一 versioned safety contract owner（AC: 4-5）
  - [x] 在 `rpg_engine/ai_intent/` 新增叶子模块 `safety_contract.py`；它唯一持有 current six-flag vocabulary、`SAFETY_VOCABULARY_VERSION = "1"`、canonical digest、compatibility policy、typed contract error 和安全 public error projection helper。模块不得 import manifest、external、normalization、risk 或 arbiter，避免循环依赖。
  - [x] Safety digest 固定为对 `{"version": <version>, "values": [<sorted unique flags>]}` 做 UTF-8 canonical JSON（`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")`、`allow_nan=False`）后计算 SHA-256 lowercase hex。
  - [x] `normalization.py`、`risk.py`、`arbiter.py` 和 `intent_manifest.py` 从 canonical module import；删除平行 owner。可以保留兼容 export 名，但它们必须引用同一个 immutable value，不得复制 set literal。
  - [x] `normalize_safety_flags()` 对 internal/rules/legacy 继续有界、宽容并只保留 known values；strict external boundary 不能复用“静默过滤后算成功”的结果。

- [x] Task 3：锁定 manifest 与 external candidate envelope（AC: 2-6）
  - [x] 将 `MANIFEST_SCHEMA_VERSION` 升为 `"2"`。Manifest top-level 新增 `manifest_digest` 和 `safety_vocabulary={version,digest,values}`；`candidate_shape.safety_flags` 继续作为兼容投影，并按下方 wire contract 新增精确的 `candidate_shape.contract` 声明。
  - [x] Manifest digest 固定为对不含 top-level `manifest_digest` 的完整 manifest wire payload做相同 canonical JSON + SHA-256；payload 不得含 `generated_at`、进程 id 或其他 volatile 字段。现有 tuple 必须按 JSON wire array 计算，测试 tuple/list serialization 等价；非标准 NaN/Infinity 必须 fail closed。
  - [x] `intent_candidate.schema.json` 新增 optional top-level `contract` object；legacy caller 可整体省略，但一旦存在必须 `additionalProperties=false` 且完整包含：`manifest_schema_version`、`manifest_digest`、`safety_vocabulary_version`、`safety_vocabulary_digest`。四个值必须是 exact builtin `str`（不接受 subclass/coercion）；两个 version 字段固定 `minLength=1`、`maxLength=32`，两个 digest 固定 `minLength=maxLength=64`且匹配 `^[0-9a-f]{64}$`。
  - [x] `safety_flags.items` 使用 canonical enum，并固定 `uniqueItems=true`、`minItems=0`、`maxItems=6`。Schema enum 与 canonical owner 之间必须有 parity test；不要通过运行时修改 packaged schema 文件。
  - [x] Provider-side validation precedence 固定为：envelope/contract exact builtin shape 与 bounds → 若提供则比较完整 provenance，任何 mismatch 返回 retriable mismatch → strict raw safety flags → 完整 JSON Schema/plan action registry → tolerant domain normalization。Partial/malformed contract 是 schema/contract-shape error，不得作为 legacy omission。
  - [x] Compatibility policy 固定由 canonical owner 提供 `ALLOW_LEGACY_UNVERSIONED_EXTERNAL_CANDIDATE = True`，并由 manifest `candidate_shape.contract.legacy_unversioned_allowed=true` 对 provider/caller 明示；本 Story 不提供环境变量、CLI flag、MCP 参数或 per-call override。关闭窗口必须另行获批 Correct Course 并升级 manifest schema version，不设隐含日期。
  - [x] Version/digest provenance 只证明 caller 看到的 contract identity，不证明 candidate 正确，也不授予 route、hidden、confirmation、proposal、validation 或 commit authority。

- [x] Task 4：收敛 external ingress 与 bounded provenance transport（AC: 1-3, 6-7）
  - [x] Strict validator 固定返回 frozen `ValidatedExternalCandidate(candidate, contract_evidence)`；`contract_evidence` 是 frozen `ExternalContractEvidence(status, validated_manifest_schema_version, validated_manifest_digest, validated_safety_vocabulary_version, validated_safety_vocabulary_digest)`，`status` 只允许 `matched | legacy_unversioned`。五个值都是 bounded provider-side validation evidence，不表示 caller/route authority。
  - [x] `normalize_external_intent_candidate()` 必须调用该 strict validator，并继续为兼容 direct caller 只返回 `IntentCandidate`；`ExternalCandidateInput` / `PreparedIntentCandidates` 必须用相邻字段携带 frozen evidence，不得把 provider envelope 或 evidence 混入 `IntentCandidate` domain fields。
  - [x] Validator 接收由 provider manifest 组装的 immutable active-contract snapshot；只保留 pure/private test injection seam 来模拟 rolling skew，不得暴露为 CLI/MCP/request/per-call override。该 seam 必须允许 Story 6.2 后续证明 taxonomy 改变会使 manifest digest stale。
  - [x] 所有 production raw external candidate 必须通过同一 `prepare_intent_candidates()` / external boundary，包括 `route_intent()`、direct `build_context()`、`GMRuntime.start_turn()` / `preview_from_text()` / `act()` / `preflight_intent()`、`SaveManager.player_turn()`、MCP `start_turn` / `preview_from_text` / `intent_preflight` / `player_turn` 与对应 CLI；不得在 adapter 再做 vocab/version comparison。
  - [x] `AIIntentRouter.route_candidates()` / arbiter 的 raw dict 参数是 kernel-internal/domain compatibility API，不是 external wire ingress；本 Story 不在它们内复制 strict validator，也不收窄既有 internal caller。测试必须证明上述所有 public production raw 输入先进 shared ingress。
  - [x] Validated/legacy evidence 必须进入 bounded intent trace，供 Story 6.7 后续 audit 使用；trace 只记录 status、validated-against versions/digests 和错误 class，不记录 raw candidate/flag/reason/slots。
  - [x] 既有 entry/profile/empty-text/pending-clarification guard 如果在 candidate boundary 前拒绝，继续返回既有错误且不 route/adopt；typed contract precedence 只在 candidate 真正到达 shared ingress 后生效。不得为 6.1 偷改 empty-text/pending clarification UX 优先级。
  - [x] Preflight candidate hash/identity 行为不得削弱：显式 stale contract 必须在 cache create/lookup/helper 前失败；本 Story 不改变 preflight purpose、TTL、CAS 或 `message_only` 语义（Story 6.6）。

- [x] Task 5：提供 typed contract error 和 thin-surface mapping（AC: 1-3, 6）
  - [x] Kernel typed error 对 unknown 使用 `reason="unknown_safety_flag"`、`retriable=false`、`action="regenerate_candidate"`；对显式 version/digest mismatch 使用 `reason="contract_version_mismatch"`、`retriable=true`、`action="refresh_manifest_and_regenerate_candidate"`。
  - [x] Public `error_details` 使用下方固定投影；每项必含 `code`、`reason`、`retriable`、`action`、`path`、`message`，可选 `count` 只能是 exact builtin `int`（不接受 `bool`）且 `0 <= count <= 6`。Uppercase codes 固定为 `UNKNOWN_INTENT_SAFETY_FLAG` / `INTENT_CONTRACT_VERSION_MISMATCH`；错误消息和 detail 不包含 offending raw value。
  - [x] Typed Python API 的 stable import path 固定为 `from rpg_engine.ai_intent import ExternalIntentContractError`，并由 `rpg_engine/ai_intent/__init__.py` re-export；direct caller 可以通过该类型和固定 attrs 进行 machine handling。
  - [x] `mcp_adapter.error_dict()` 与 CLI failure path 复用 canonical error projection helper。`save_manager.error_dict()` 当前没有 production caller，不得为匹配计划制造空改；只有验证到真实调用面或保留其独立 public-helper 测试合同时才复用 projection helper，且不得给 `SaveManager.player_turn()` 新增 blanket catch。Generic exceptions 继续走现有 `issues_from_messages()`，profile/path/validation errors 不回归。
  - [x] `normalize_external_intent_candidate()`、`prepare_intent_candidates()`、`route_intent()`、direct `build_context()`、`GMRuntime.start_turn()` / `preview_from_text()` / `act()` / `preflight_intent()` 与 `SaveManager.player_turn()` 都向 direct Python caller 传播同一 typed `ExternalIntentContractError(ValueError)`；尤其 preflight 不得把它降级为 generic failed `IntentPreflightResult`。
  - [x] 只有 MCP `call_with_audit()`、V1 CLI `play start-turn` / `play preflight` / `play act`、V1 `player turn` 与 legacy `rpg_engine.cli context build` 顶层 command boundary 捕获并投影该 typed error。这些路径均不得输出 traceback，不得把 mismatch 转成 rules fallback、clarification 或 ready outcome；CLI recovery action 指向调用方经 MCP `intent_manifest` 或 Python `build_intent_manifest()` refresh，本 Story 不新增 CLI manifest command。

- [x] Task 6：完成 surface、rolling-upgrade 与 no-authority integration gates（AC: 1-7）
  - [x] 版本矩阵：new/current exact match；explicit older/newer manifest version；same version/wrong manifest digest；wrong safety version/digest；partial/malformed contract；legacy omitted + empty/known；legacy omitted + unknown。
  - [x] 对“new caller → old provider”不虚构旧 binary 能返回新错误：caller 看到 schema v1 时只能使用 legacy envelope/current-known values或在 caller side 停止；provider-side测试使用可注入 active-contract fixture模拟 skew。`new caller → current provider` 的显式 stale identity必须由当前 provider返回 retriable mismatch。
  - [x] Digest gate 必须在两个 subprocess 中使用不同 `PYTHONHASHSEED` 构建 manifest，断言完整 wire、vocabulary digest 与 manifest digest 相同；测试独立重算 canonical JSON digest，再通过 pure/private provider fixture 改变一个 safety value，断言两个 digest 都变化。不得把 fixture 变成 public override。
  - [x] Direct normalizer/Runtime/SaveManager 测试使用 `assertRaises(ExternalIntentContractError)` 并逐字段断言 `code/reason/retriable/action/path/message`；MCP/V1 CLI/legacy CLI 才断言 `{ok:false, errors, error_details}`，不得给 `SaveManager.player_turn()` 添加 dict 失败语义。
  - [x] Runtime/SaveManager/MCP player profile/developer `start_turn` / preview/V1 CLI/legacy `context build` JSON/preflight 覆盖 machine error shape、no helper call、no new cache/pending、no facts/events/turn；CLI human mode 必须 concise failure 且无 traceback；所有写测试使用 temporary Save/workspace。
  - [x] Legacy `context build` subprocess 在 `tests/test_bug_report_regressions.py` 覆盖 unknown/mismatch 的 JSON 与 human mode：断言 nonzero exit、fixed detail、concise human output、stdout/stderr 无 `Traceback`，temporary Save 的 facts/events/turns/context_runs（未传 `--audit-context`）不变。
  - [x] 同一高熵 sentinel 必须分别注入 raw flag/reason/slots/player text/session key/provider body，并扫描 direct exception `str/repr`、MCP result + audit log、CLI stdout + stderr；任何一处不得泄漏。
  - [x] 注意当前 `SaveManager.player_turn()` 在 Runtime validation 前会清理已有 pending action；本 Story只承诺“不创建/采用新的 pending”。不得在 6.1 偷改 existing-pending supersede 语义或声称完整 workspace zero-mutation；该问题由 Story 6.5 处理并在测试命名/断言中明确。
  - [x] Formal current Campaign/Save、正式 registry 和 `data/game.sqlite` 只读或 fingerprint 前后相等；需要 player-turn 集成时复制到 temporary workspace。

- [x] Task 7：实现验证后同步 canonical docs，并运行 final clean gates（AC: 1-7）
  - [x] 同步 `docs/architecture.md`、`docs/component-inventory.md`、`docs/ai-intent-chain.md`、`docs/cli-contracts.md`、`docs/mcp-contracts.md`、`docs/prompt-contracts.md`、`docs/prompts/ai-client-prompt.md` 和 `docs/testing-and-quality-gates.md`；prompt version 固定更新为 `2026-07-13.intent-contract-v2-safety-v1`。
  - [x] 文档明确 compatibility window、error recovery、manifest v2/safety v1、authority 非升级，以及 6.1/6.2/Hermes 边界。PRD 与两份 Architecture Spine 不重做；Story 4.7 不修改。
  - [x] 先跑 Story focused 与 current-native temporary-copy gates，再跑两个 canonical Campaign validate/test、Markdown links、changed Python `py_compile`、full Ruff、`git diff --check` 和 repository full pytest。
  - [x] 任何 implementation/review patch 会使受影响旧绿灯失效；关闭 Story 前从 final clean diff 重跑所有 invalidated gates。

### Review Findings

- [x] [Review][Patch] 对 frozen contract evidence 执行 exact builtin、version bounds 与 lowercase SHA-256 bounds 校验 [`rpg_engine/ai_intent/safety_contract.py`]
- [x] [Review][Patch] 在扫描 raw safety tokens 前执行六项长度上限，避免超大输入的重复 O(n) 扫描 [`rpg_engine/ai_intent/external.py`]
- [x] [Review][Patch] 未注册 plan action 的 schema failure 不得回显 caller token [`rpg_engine/ai_intent/external.py`]
- [x] [Review][Patch] Contract shape 必须先于 active manifest digest 构建，保持固定 validation precedence [`rpg_engine/ai_intent/external.py`]
- [x] [Review][Patch] 删除未消费且可能产生矛盾 provenance 的 `ExternalCandidateInput.contract_evidence` 字段 [`rpg_engine/intent_router.py`]
- [x] [Review][Patch] 补六项 known blocker 的 off-mode 回归与 unknown/mismatch 下游 helper/router/preview 未调用证据 [`tests/test_ai_intent.py`]
- [x] [Review][Patch] MCP unknown/mismatch 覆盖全部四个 external surfaces、精确 public payload、独立敏感 sentinel 与 helper no-call [`tests/test_mcp_adapter.py`]
- [x] [Review][Patch] 增加从真实 manifest 构建 exact contract 的 public-surface matched success gate [`tests/test_mcp_adapter.py`]
- [x] [Review][Patch] SaveManager direct typed errors 逐字段断言全部稳定 attrs [`tests/test_save_manager.py`]
- [x] [Review][Patch] Canonical testing 文档中的 Story focused gate 必须镜像完整 final union [`docs/testing-and-quality-gates.md`]
- [x] [Review][Patch] 从 final clean diff 重建 Story Debug/Completion Notes、完整 File List、Change Log 与 Task 7 状态 [`6-1-strict-external-safety-vocabulary-and-version-negotiation.md`]

## Dev Notes

### 当前实现与根因

- `intent_candidate.schema.json` 当前只要求 `safety_flags` item 是 string；unknown 能通过 schema。
- `normalize_safety_flags()` 当前用 `SAFETY_FLAG_VALUES` 静默过滤 unknown；`risk.py` 与 `arbiter.py` 又各有一份相同六项集合，没有 executable parity gate。
- `build_intent_manifest()` 当前只输出 `schema_version="1"` 和从 risk set 投影的 flags，无 manifest digest 或 safety vocabulary version/digest。
- `prepare_intent_candidates()` 在 deterministic routing/internal helper 之前调用 external normalization，因此 strict contract validation 放在此共享 ingress 可以阻止后续 route/preview；不能把 strict check 分散到 MCP/CLI。
- 缺口来自 baseline `3df5748`；Story 4.1 commit `e2b1760` 让 `off + external_primary` 可达后，unknown 被删再 accepted 的 consequence 可复现。最近五个 advisory/latency/preflight commits 未引入该缺口。
- Story 4.1 的多轮 review 表明 shared candidate shape 很容易出现旁路；必须把 strict check 放在 external ingress，且让 Runtime/SaveManager/MCP/preflight 共用，不在每个 surface 复制。

### Wire Contract（实现时不得临场改形状）

Manifest v2 新增/变更字段摘录（不是可替换完整 manifest 的最小 wire）：

```json
{
  "schema_version": "2",
  "manifest_digest": "<64 lowercase hex>",
  "safety_vocabulary": {
    "version": "1",
    "digest": "<64 lowercase hex>",
    "values": [
      "forced_save",
      "hidden_info",
      "maintenance_request",
      "out_of_world",
      "prompt_injection",
      "unsafe_command"
    ]
  },
  "candidate_shape": {
    "safety_flags": [
      "forced_save",
      "hidden_info",
      "maintenance_request",
      "out_of_world",
      "prompt_injection",
      "unsafe_command"
    ],
    "contract": {
      "required": false,
      "all_or_nothing": true,
      "additional_properties": false,
      "legacy_unversioned_allowed": true,
      "required_fields_when_present": [
        "manifest_schema_version",
        "manifest_digest",
        "safety_vocabulary_version",
        "safety_vocabulary_digest"
      ]
    }
  }
}
```

完整 manifest 必须保留现有 `generated_by`、`modes`、`actions`、`queries`、`unsupported_query_kind_policy`，以及 `candidate_shape.required_fields/action_names/query_kinds`等现有字段；上例只摘录 6.1 的增量。`action_names` 仍由现有 registry 完整投影，任何占位值都不得出现在实际 wire。Manifest digest 必须覆盖这个完整 payload，并增加 backward-shape regression 证明既有字段未丢失。`candidate_shape.contract` 的 key、boolean 与 field list 是 manifest v2 的固定 provider declaration，不新增同义字段。

New-caller external candidate 增加 optional、all-or-nothing envelope metadata：

```json
{
  "contract": {
    "manifest_schema_version": "2",
    "manifest_digest": "<manifest digest>",
    "safety_vocabulary_version": "1",
    "safety_vocabulary_digest": "<safety vocabulary digest>"
  },
  "kind": "single",
  "mode": "action",
  "action": "rest",
  "slots": {"until": "morning"},
  "plan": [],
  "confidence": "high",
  "missing_slots": [],
  "needs_confirmation": [],
  "safety_flags": [],
  "reason": "玩家想休息"
}
```

`contract` 整体缺失是受控 `legacy_unversioned`；只给一部分字段、未知字段、错误类型或不完整 digest 都是非法 shape。Contract metadata 经过 validation 后不得进入 internal model prompt 的 candidate domain payload。

Compatibility 窗口的初始状态固定为打开；caller 以 manifest v2 的 `candidate_shape.contract.legacy_unversioned_allowed` 判断 provider 是否接收未版本化 envelope。它不能由请求方临时开启/关闭，未来关闭必须经过独立 Correct Course 并以新的 manifest schema version 显式发布。若显式 contract 同时 stale 且带 unknown flag，按固定 precedence 先返回 retriable `contract_version_mismatch`；只有 contract match 或整体省略时才把 unknown 映射为 non-retriable `unknown_safety_flag`。

### Surface Category / Error / Write Authority

下表是 6.1 的 surface 真源；现有 taxonomy 与 write authority 不得因 contract error handling 改变，并由 `tests/test_surface_inventory.py` 回归固定。

| Entry family | Existing taxonomy / write mode | Error owner | 6.1 mutation authority |
| --- | --- | --- | --- |
| `normalize_external_*` / `prepare_intent_candidates()` / `route_intent()` / direct `build_context()` | kernel internal / trusted Python boundary；none or read-only | Kernel typed exception propagates | none |
| `GMRuntime.start_turn()` / `preview_from_text()` / `act()` | trusted low-level；read-only or preview-only | Kernel typed exception propagates | no gameplay fact commit |
| `GMRuntime.preflight_intent()` | trusted low-level；advisory-only | Kernel typed exception propagates before cache | no gameplay fact commit; no stale/unknown cache row |
| direct `SaveManager.player_turn()` | player-safe workflow；preview-only | Kernel typed exception propagates | existing pending supersede semantics only; no new pending/fact commit on typed failure |
| MCP `player_turn` | player-safe；preview-only | `call_with_audit()` projects canonical detail | no gameplay fact commit |
| MCP `start_turn` / `intent_preflight` / `preview_from_text` | trusted low-level；read-only/advisory-only/preview-only | `call_with_audit()` projects canonical detail | no gameplay fact commit |
| V1 `player turn` | player-safe；preview-only | command boundary projects canonical detail | no gameplay fact commit |
| V1 `play start-turn` / `play preflight` / `play act` | trusted low-level；read-only/advisory-only/preview-only | command boundary projects canonical detail | no gameplay fact commit |
| legacy `context build` | legacy/maintenance compatibility read path | top-level command boundary projects canonical detail | read-only unless existing explicit `--audit-context`; typed failure creates no context run |

### Validation / Surface Decision Table

| Ingress state | Kernel result / evidence | Direct surface observable | Adapter observable | Mutation guarantee |
| --- | --- | --- | --- | --- |
| entry/profile/empty-text/pending guard 先拒绝 | 既有 guard result；candidate 未到 shared ingress | 保持既有 direct result | 保持既有 surface result | 不 route/adopt；不改 guard 优先级 |
| partial/malformed contract | contract shape/schema error | 现有 schema `ValueError` | MCP/CLI 既有 validation projection | helper/route/new pending/cache 前失败 |
| explicit stale contract（即使同时 unknown） | typed `contract_version_mismatch` | direct Runtime/SaveManager propagate | MCP/CLI retriable canonical detail | helper/route/new pending/cache 前失败 |
| exact 或 omitted contract + unknown | typed `unknown_safety_flag` | direct Runtime/SaveManager propagate | MCP/CLI non-retriable canonical detail | helper/route/new pending/cache 前失败 |
| contract omitted + empty/current-known | frozen `legacy_unversioned` evidence | 继续既有 off/consensus result | 继续既有 surface shape | 不新增 Story 6.1 mutation |
| exact contract + empty/current-known | frozen `matched` evidence | 继续既有 off/consensus result | 继续既有 surface shape | 不新增 Story 6.1 mutation |

Method boundary 固定如下：`normalize_external_intent_candidate()`、`prepare_intent_candidates()`、`route_intent()`、direct `build_context()`、`GMRuntime.start_turn()` / `preview_from_text()` / `act()` / `preflight_intent()` 与 direct `SaveManager.player_turn()` 不捕获 typed contract error；MCP `call_with_audit()`、V1 CLI `play start-turn` / `play preflight` / `play act`、V1 `player turn` 与 legacy `rpg_engine.cli context build` 顶层 command boundary 才捕获并投影。不要在 `runtime.py`、`context_builder.py` 或 `save_manager.py` 添加 blanket exception mapping。

公开 mismatch 示例（unknown 使用同形状，只替换 code/reason/retry/action/path/message）：

```json
{
  "ok": false,
  "errors": ["External intent contract does not match the current provider."],
  "error_details": [
    {
      "code": "INTENT_CONTRACT_VERSION_MISMATCH",
      "reason": "contract_version_mismatch",
      "retriable": true,
      "action": "refresh_manifest_and_regenerate_candidate",
      "path": "$.contract",
      "message": "External intent contract does not match the current provider."
    }
  ]
}
```

Direct typed exception 携带同一组 `code/reason/retriable/action/path/message` 属性，但不伪装成含 `ok` 的 dict。Unknown 的 public `path` 固定为 `$.safety_flags`，message 固定为 `External intent candidate contains unsupported safety flags.`；两种 message 都不得插入 raw value。MCP/CLI 可以把上述 payload 嵌入现有返回/退出码合同，但不得重命名或删除必填 detail 字段。

### Authority 与兼容不变量

- External candidate 永远是 low-trust。Contract match 只说明调用方看过某版 contract，不是事实、正确意图、hidden permission、玩家确认、proposal approval、validation token 或 commit authorization。
- Explicit `off + valid external` 保持 `external_primary`；rules mismatch 仍只作诊断。Unknown/stale external candidate 不是 valid external，必须在 route 前失败。
- Enabled consensus timeout/unavailable 不能偷换成 off。External-only known safety flag 仍是低信任自述，healthy internal review 的现有 clear/confirm 语义不在本 Story改变；Kernel/rules/internal known safety guard 继续生效。
- Tolerant internal/rules/domain-compatibility normalization 可以保留；只有 external wire boundary 必须 strict。这里的 “legacy” 只指历史 internal/domain compatibility input，不指 `legacy_unversioned` external caller；不要把 shared normalizer 全局改成 raise。
- `legacy_unversioned` external caller 虽可整体省略 provenance，仍必须通过 strict external flag gate，且只可使用 current-known/empty flags。不要立即把 contract 设为 required，否则会无计划中断现有 MCP/CLI/Hermes/eval fixtures。
- 实际旧 provider 不具备新错误码；当前 provider只对自己收到的显式 stale contract负责。跨仓 next-model-turn barrier、Hermes capability negotiation 和完整 E2E 分别属于 Hermes H2/H4 与 Story 6.8。

### Source Tree / File Guardrails

Recommended NEW：

- `rpg_engine/ai_intent/safety_contract.py`：canonical vocabulary/version/digest、compatibility policy、typed error、public error projection；保持叶子模块。

Expected UPDATE：

- `rpg_engine/resources/schemas/intent_candidate.schema.json`
- `rpg_engine/ai_intent/__init__.py`（只 re-export stable typed exception）
- `rpg_engine/ai_intent/external.py`
- `rpg_engine/ai_intent/normalization.py`
- `rpg_engine/ai_intent/risk.py`
- `rpg_engine/ai_intent/arbiter.py`（只删除重复词表 owner/改 import，不重写 arbitration）
- `rpg_engine/intent_manifest.py`
- `rpg_engine/runtime.py`（保持 typed error 传播；只在需要 transport 时做窄改动，不得 generic catch）
- `rpg_engine/context_builder.py`（只验证 direct `build_context()` 传播/窄 transport，不添加 error mapping）
- `rpg_engine/intent_router.py`（只做 validated contract evidence transport）
- `rpg_engine/ai_intent/router.py`（仅在 bounded route trace / candidate-bound preflight 需要 contract evidence 时；不改变 arbitration）
- `rpg_engine/ai_intent/types.py` 或窄新 carrier（仅当需要，不能污染 `IntentCandidate`）
- `rpg_engine/ai_intent/prompts.py`（从 manifest projection渲染 safety values/version，删除硬编码第四份列表）
- `rpg_engine/mcp_adapter.py`、`rpg_engine/cli_v1.py`、`rpg_engine/cli.py`（只在 adapter/command boundary 投影 typed error；不得复制 validation；legacy `context build` 同样不得 traceback）
- `rpg_engine/save_manager.py` 只在 frozen evidence transport 或已验证的现有 helper 合同必需时窄改；`player_turn()` 不捕获 typed error，不得为匹配计划制造空改。
- story-relevant tests 与 canonical docs。

在实现前完整读取所有实际 UPDATE 文件。若实现能在不改某个 optional 文件的情况下满足 AC，应从最终 File List 移除，不要为匹配计划制造空改动。

### 明确不做

- 不迁移 action taxonomy、不处理“巡视/巡逻→routine”、不修改 resolver keywords；这是 Story 6.2。
- 不清理 slot ownership 或 route representations；这是 Story 6.3 或后续设计债务。
- 不实现 atomic confirm、pending supersede/clarification TTL、preflight consumer purpose、safe audit reconstruction 或 real stdio E2E；分别属于 6.4–6.8。
- 不修改 Hermes reconnect、GM skill、next-model-turn barrier、background self-improvement 或 Hermes H1–H4。
- 不新增 `IntentCoordinator`，不重写 arbiter/binder/resolver/validation/commit，不新增 dependency、DB migration、Campaign/Save schema。
- Story 4.7 标题、用户价值与三组 Acceptance Criteria 不得改；实现前后 section SHA-256 必须保持 `27c2a9538c8b83d63d66a275631a222053fc4f94237c9fd1f3ce2dc0286e3f58`。

### Testing Requirements

最低行为矩阵：

| Scenario | Required result |
| --- | --- |
| exact contract + empty/known non-blocking flags | 继续当前 off/consensus path；contract match不提升 authority |
| exact contract + unknown flag | `unknown_safety_flag`；不进入 helper/route/preview/new pending |
| explicit old/new version mismatch | `contract_version_mismatch`；retriable；refresh+regenerate |
| same version + wrong manifest/safety digest | 同上；证明不是只比较 version |
| partial/malformed contract | schema/contract-shape error；不是 legacy omission |
| contract omitted + empty/current-known | compatibility-window允许；标记 `legacy_unversioned` evidence |
| contract omitted + unknown | `unknown_safety_flag`；compatibility不能放行 |
| stale contract + unknown | precedence 返回 `contract_version_mismatch`；refresh 后才评估 unknown |
| off + each known blocker | 现有 blocked 语义保持 |
| consensus + external-only known signal + healthy clearing review | 现有 review/trace 语义保持；不变成 external永久 veto |
| consensus unavailable + known danger | 不偷换 off；rules fast fallback不得越过 safety |
| preflight candidate-bound unknown/mismatch | cache/helper前失败；不创建 cache row |
| direct normalize/prepare/route/build_context/Runtime/SaveManager unknown/mismatch | `assertRaises(ExternalIntentContractError)` 且 attrs 精确；无新 pending/cache/facts/events/turn |
| MCP player/developer tools + audit unknown/mismatch | `{ok:false, errors, error_details}`；MCP `start_turn` 也覆盖；无 raw payload |
| V1 `play` 三分支 / `player turn` / legacy `context build` unknown/mismatch | nonzero；JSON fixed detail；human concise；stdout/stderr 无 traceback/sentinel |
| pre-ingress profile/empty-text/pending guard | 保持既有 guard 结果；不进 strict ingress；不 route/adopt |

Test owner 与可观测结果固定如下，Tasks 1–6 以此表为可执行映射：

| Contract cluster | Test owner/file | Required observable |
| --- | --- | --- |
| manifest/schema/digest/parity | `tests/test_intent_manifest.py` | complete shape retained；canonical recompute；cross-process/different-hash-seed stability；changed safety alters both digests |
| strict external / tolerant internal / precedence | `tests/test_ai_intent.py` | external unknown/duplicate/case/space fail；internal compatibility filter remains；stale-before-unknown |
| direct context/start-turn/runtime/preflight | `tests/test_runtime.py`, `tests/test_context_quality.py`, `tests/test_current_native_context.py` | typed propagation；`build_context/start_turn` covered；no helper/cache/new state |
| MCP player/developer/audit | `tests/test_mcp_adapter.py` | player + low-level `start_turn/preview/preflight` canonical detail；audit redaction；SQLite counts unchanged |
| SaveManager | `tests/test_save_manager.py` | typed exception；no new pending/facts/events/turn；existing pending supersede assertion named separately |
| V1 CLI | `tests/test_v1_cli.py` | `play start-turn/preflight/act` + `player turn` JSON/human projections；no traceback |
| legacy context CLI | `tests/test_bug_report_regressions.py` | `context build` unknown/mismatch subprocess JSON/human/nonzero/redaction/no context run |
| taxonomy / shared regressions | `tests/test_surface_inventory.py` 及 focused shared suites | taxonomy/write authority unchanged；platform/eval/transcript/current-native boundaries unchanged |

RED/core：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_intent_manifest.py \
  tests/test_ai_intent.py \
  -p no:cacheprovider
```

Surface contract iteration gate（开发期快速跑，不替代 final focused）：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_intent_manifest.py \
  tests/test_ai_intent.py \
  tests/test_runtime.py \
  tests/test_context_quality.py \
  tests/test_current_native_context.py \
  tests/test_mcp_adapter.py \
  tests/test_preflight_cache.py \
  tests/test_save_manager.py \
  tests/test_v1_cli.py \
  tests/test_bug_report_regressions.py \
  tests/test_surface_inventory.py \
  -p no:cacheprovider
```

Shared regression iteration gate：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_ai_helper.py \
  tests/test_platform_prewarm.py \
  tests/test_platform_ai_simulation.py \
  tests/test_platform_sidecar.py \
  tests/test_eval_suite.py \
  tests/test_mcp_transcript.py \
  tests/test_current_native_player_turn.py \
  -p no:cacheprovider
```

Story focused（final union，不得用上述任一 iteration gate 代替）：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_intent_manifest.py \
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

Final clean diff：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
python3 scripts/check_markdown_links.py docs _bmad-output
PYTHONPYCACHEPREFIX="${TMPDIR:-/tmp}/rpg-engine-pycache" python3 -m compileall -q rpg_engine tests
python3 -m ruff check .
git add -N -- rpg_engine/ai_intent/safety_contract.py
git diff --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

text = Path("_bmad-output/planning-artifacts/epics.md").read_text()
section = "### Story 4.7:" + text.split("### Story 4.7:", 1)[1].split("\n## Epic 5:", 1)[0] + "\n"
actual = sha256(section.encode()).hexdigest()
expected = "27c2a9538c8b83d63d66a275631a222053fc4f94237c9fd1f3ce2dc0286e3f58"
assert actual == expected, (actual, expected)
PY
```

当前只读 pre-implementation 基线（2026-07-13）：RED/core 命令为 `73 passed, 80 subtests passed`；上方扩展后 Story-focused final union 为 `447 passed, 519 subtests passed in 267.21s`。任何 implementation/review patch 后，受影响旧证据必须重跑。

### Project Structure Notes

- Story artifact 位于 `_bmad-output/implementation-artifacts/`；production contract 留在 `rpg_engine/ai_intent/`，packaged wire schema 留在 `rpg_engine/resources/schemas/`。
- 现有 `ExternalCandidateInput` 是 passive raw input，`PreparedIntentCandidates.external_low_trust_candidate` 是 normalized domain candidate。实现必须使用本 Story 固定的 `ValidatedExternalCandidate` + `ExternalContractEvidence` 相邻 frozen carrier，不应混入 domain candidate 或赋予 authority。
- `intent_manifest.py` 当前同时表达 action/query/slot/safety；6.1 只增加通用 contract identity与 safety projection。Story 6.2 后续可让 taxonomy projection参与同一 manifest digest，6.1 不提前搬词表。
- 当前 worktree 已包含用户批准的 Correct Course 规划变更与两份 untracked investigation inputs；这些是本 Story 的来源，不属于 6.1 implementation diff，Dev 不得覆盖或删除。
- 无 UX artifact；本项目为 CLI/MCP/kernel-first，本 Story 只改变 machine contract/error recovery，不新增 UI。

### Git Intelligence

- Baseline：`1141404 feat(ai): add advisory review workflow`。
- `3df5748` 引入宽松 safety normalization/平行词表；`e2b1760` 实现 Story 4.1 external-primary，使 unknown 被删后 accepted 的路径可达。
- 最近 `2e64979`、`a3f33de`、`4ea796b`、`d1c5784`、`1141404` 分别建立 latency、preflight、advisory envelope/adapters/review 的严格边界。复用其 exact builtin types、bounded inputs、canonical digest、revalidation、sanitized errors 和 no-mutation 测试模式。
- 不回滚 Story 4.1；修复发生在它之前的 external validation contract。避免再次扩成大规模 arbiter rewrite。

### Latest Technical Information

- Repository 已使用 JSON Schema Draft 2020-12 和 `jsonschema.Draft202012Validator`，无需新增或升级 dependency。
- Draft 2020-12 `enum` 对实例值做精确匹配，适合 external wire strict validation；Schema 继续声明具体 `$schema` URI。[JSON Schema Draft 2020-12 validation](https://json-schema.org/draft/2020-12/json-schema-validation)；[Draft 2020-12 specification](https://json-schema.org/draft/2020-12)
- Python stdlib `json.dumps()` 必须显式设置 Story 中的 canonical knobs，特别是 `allow_nan=False`，才会拒绝非 JSON 规范的 NaN/Infinity。[Python `json` documentation](https://docs.python.org/3/library/json.html)
- JSON Schema 负责 wire constraints，但不能取代 canonical Python owner/parity test、typed error mapping 或 digest/version comparison；不要引入 custom meta-schema/keyword。

### Correct Course Decision Traceability

- D2（external safety strict fail-closed）→ AC 1/3/4、Tasks 1–4；unknown 不得被 tolerant normalization 消失。
- D7（versioned compatibility negotiation）→ AC 2/5/6、Tasks 2–6；manifest v2/safety v1、digest、compatibility window 与 recovery 形状在此 Story 锁定。
- D1/D3/D4/D5/D6/D8 分别 defer 给 Story 6.2/6.3/6.4/6.5/6.6/6.7–6.8；Hermes consumer/reconnect/next-model-turn/E2E 仍由 Hermes H1–H4 持有，不回写 RPG Engine Sprint 或 Story 4.7。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.1: Strict External Safety Vocabulary and Version Negotiation`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md#2. 八项产品/架构决策`]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md#4.2 RPG Engine Stories`]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md#Finding 4: 未知 safety flag 被 schema 接受、normalizer 静默删除，并可在 off mode 被采用`]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md#Minimal Boundaries`]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md#Review Correction: 2026-07-13`]
- [Source: `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md#5.2 AI-First 意图与 Resident AI 边界`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md#AD-2 - AI route proposal 按 mode 选择，但 AI 不能成为事实、确认或提交权威 [ADOPTED]`]
- [Source: `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md#AD-2 - Intent coordination may select a route proposal but owns no gameplay fact or write authority [ADOPTED]`]
- [Source: `docs/project-context.md#不可破坏边界`]
- [Source: `docs/ai-intent-chain.md#External Candidate`]
- [Source: `docs/ai-intent-chain.md#Intent Manifest`]
- [Source: `docs/mcp-contracts.md#AI Helper 和 External Candidate`]
- [Source: `docs/prompt-contracts.md#更新触发条件`]
- [Source: `docs/testing-and-quality-gates.md#AI intent / platform / SaveManager 高风险 cluster`]

## BMAD Provenance

- 用户触发：用户要求直接开始 Story 6.1 的 `[CS] Create Story`。
- Catalog 路由：`[CS] Create Story`，`bmad-create-story:create`，BMM phase `4-implementation`，required。
- Skill：`.agents/skills/bmad-create-story/SKILL.md` 已完整读取。
- Customization resolver：成功；prepend/append 为空；persistent fact 为 `file:{project-root}/**/project-context.md`；`on_complete` 为空。
- Config：`_bmad/bmm/config.yaml`；`communication_language=Chinese`、`document_output_language=Chinese`，planning/implementation artifact roots 已解析。
- 执行文件：`discover-inputs.md`、`checklist.md`、`template.md` 已完整读取；workflow steps 1-6 按顺序执行。
- 输入：完整 sprint status 与 epics、相关 PRD/Architecture shards、批准的 2026-07-13 Correct Course、两份调查、canonical docs、现有 production/test UPDATE 文件、最近 Git 历史和官方 JSON Schema 文档。
- 并行分析：safety code boundary、planning/architecture artifacts、tests/Git intelligence 三路只读 subagents；均未编辑 workspace。
- 完成说明：Ultimate context engine analysis completed - comprehensive developer guide created。

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Implementation Plan

- 以 strict external RED matrix 锁定 fail-open 缺口，再把临时 ingress guard 收敛到 canonical leaf contract。
- 依次实现 manifest/schema identity、frozen evidence transport、typed surface projection 和全链 no-authority/redaction gates。
- 最后同步 canonical docs，从 final clean diff 运行 focused/full gates，然后进入对抗性 Code Review 收敛。

### Debug Log References

- Task 1 RED：`8 failed, 1 passed, 7 subtests passed`，确认 unknown/variant/duplicate 当前 fail open。
- Task 1 GREEN：`tests/test_ai_intent.py` 通过，`71 passed, 81 subtests passed`。
- Task 2 RED：manifest contract test collection 因 canonical leaf module 尚不存在而失败。
- Task 2 GREEN：`tests/test_intent_manifest.py tests/test_ai_intent.py` 通过，`77 passed, 93 subtests passed`。
- Task 3/4 GREEN：manifest/schema/AI/runtime focused gates 分别通过 `82 passed, 98 subtests passed` 与 `156 passed, 155 subtests passed`。
- Task 5/6 surface gate：`386 passed, 504 subtests passed`；CLI/MCP/direct no-write 与 digest/rolling-skew matrix 全绿。
- Dev final：Story focused `465 passed, 583 subtests passed`；repository full `972 passed, 10059 subtests passed`。
- Code Review：Blind Hunter、Edge Case Hunter、Acceptance Auditor 三层完成；11 项 patch 全部修复，9 项 spec-conflicting/noise finding 排除，无 decision/defer。
- Review final：受影响快速门 `220 passed, 230 subtests passed`；Story focused `467 passed, 599 subtests passed`；repository full `974 passed, 10075 subtests passed`。
- Final clean：两个 canonical Campaign validate/test、188 个 Markdown 文件链接、compileall、Ruff、`git diff --check` 全绿；Story 4.7 section hash 保持 `27c2a9538c8b83d63d66a275631a222053fc4f94237c9fd1f3ce2dc0286e3f58`。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created。
- Task 1：external ingress 已对 unknown/case/whitespace/duplicate safety token fail closed，internal/rules tolerant normalization 与既有 off/consensus safety 语义保持。
- Task 2：六项 safety vocabulary、v1 digest、兼容窗口与 typed error 投影收敛到无循环依赖的 immutable canonical owner；运行时 alias identity 与 prompt manifest 投影已锁定。
- Task 3：发布 manifest v2、完整 deterministic manifest digest、safety vocabulary v1 identity 与 optional all-or-nothing candidate contract；固定 mismatch-before-unknown precedence。
- Task 4：所有 production raw external candidate 复用 shared strict ingress，并以 frozen adjacent carrier 把 bounded matched/legacy evidence 送入 trace，不污染 domain candidate 或提升 authority。
- Task 5：direct Python/Runtime/SaveManager 传播稳定 typed exception；MCP/V1/legacy CLI 只在 command boundary 投影固定、脱敏的 machine error 与 recovery action。
- Task 6：完成 old/new/wrong-digest/legacy/exact matrix、跨进程 hash-seed stability、direct/MCP/CLI/current-native no-write 与 redaction integration gates。
- Task 7：八份 canonical docs 与 AI client prompt 已同步到 `2026-07-13.intent-contract-v2-safety-v1`，明确 6.1/6.2/Hermes ownership split；final clean gates 从 review 后 diff 重跑。
- Review：补强 evidence exact bounds、safety pre-scan bound、plan-action redaction、shape precedence、六 blocker、全 MCP surface、live-manifest matched E2E、SaveManager attrs 与完整 focused 文档命令；无未决 review finding。

### File List

- `_bmad-output/implementation-artifacts/6-1-strict-external-safety-vocabulary-and-version-negotiation.md`
- `_bmad-output/implementation-artifacts/6-1-strict-external-safety-vocabulary-and-version-negotiation.validation-report.md`
- `_bmad-output/implementation-artifacts/investigations/intent-mode-mismatch-mcp-call-investigation.md`
- `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/component-inventory.md`
- `docs/mcp-contracts.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/ai/schema_validation.py`
- `rpg_engine/ai_intent/__init__.py`
- `rpg_engine/ai_intent/arbiter.py`
- `rpg_engine/ai_intent/external.py`
- `rpg_engine/ai_intent/normalization.py`
- `rpg_engine/ai_intent/prompts.py`
- `rpg_engine/ai_intent/risk.py`
- `rpg_engine/ai_intent/safety_contract.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/cli.py`
- `rpg_engine/cli_v1.py`
- `rpg_engine/intent_manifest.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/resources/schemas/intent_candidate.schema.json`
- `tests/test_ai_intent.py`
- `tests/test_bug_report_regressions.py`
- `tests/test_intent_manifest.py`
- `tests/test_mcp_adapter.py`
- `tests/test_runtime.py`
- `tests/test_save_manager.py`
- `tests/test_v1_cli.py`

## Change Log

| Date | Change |
| --- | --- |
| 2026-07-13 | 实现 Story 6.1 manifest v2 / safety v1 strict external contract、typed thin-surface mapping、全 surface/digest/no-write gates与 canonical docs。 |
| 2026-07-13 | 对抗性 Code Review 收敛 11 项 patch；review 后 focused/full/final clean gates 全部重跑通过，Story 4.7 边界未变。 |
