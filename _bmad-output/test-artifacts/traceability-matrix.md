---
stepsCompleted: ['step-01-load-context', 'step-02-discover-tests', 'step-03-map-criteria', 'step-04-analyze-gaps', 'step-05-gate-decision']
lastStep: 'step-05-gate-decision'
lastSaved: '2026-07-15'
workflowType: 'testarch-trace'
workflowStatus: 'complete'
traceIteration: 2
previousTrace:
  iteration: 1
  workflowStatus: 'complete'
  gateDecision: 'FAIL'
  p0Full: '21/46'
  p1Full: '2/9'
  overallFull: '23/55'
  reason: 'coverage completeness; CON-01/02/03 and CRF-01 were P0 NONE'
inputDocuments:
  - 'AGENTS.md'
  - '.agents/skills/bmad-testarch-trace/SKILL.md'
  - '_bmad/tea/config.yaml'
  - 'docs/project-context.md'
  - '_bmad-output/test-artifacts/test-design-architecture.md'
  - '_bmad-output/test-artifacts/test-design-qa.md'
  - '_bmad-output/test-artifacts/test-design-progress.md'
  - '_bmad-output/test-artifacts/test-design/aigm-kernel-handoff.md'
  - '_bmad-output/test-artifacts/automation-summary.md'
  - '_bmad-output/test-artifacts/automation-validation-iteration-2.json'
  - '_bmad-output/test-artifacts/test-review.md'
  - '_bmad-output/test-artifacts/test-reviews/test-review-test-automation-iteration-2-20260715.json'
  - 'tests/test_current_native_consumption_craft_deltas.py'
  - 'tests/automation_support/domain_deltas.py'
  - 'tests/automation_support/domain_environment.py'
coverageBasis: 'acceptance_criteria'
oracleConfidence: 'high'
oracleResolutionMode: 'formal_requirements'
oracleSources:
  - '_bmad-output/test-artifacts/test-design-qa.md'
  - '_bmad-output/test-artifacts/test-design-progress.md'
  - '_bmad-output/test-artifacts/test-design-architecture.md'
  - '_bmad-output/test-artifacts/test-design/aigm-kernel-handoff.md'
externalPointerStatus: 'not_used'
phase1Status: 'complete'
requestedExecutionMode: 'auto'
resolvedExecutionMode: 'agent-team'
tempCoverageMatrixPath: '/tmp/tea-trace-coverage-matrix-2026-07-15T09-53-06Z.json'
testDiscovery:
  repositoryCollectedTests: 1155
  candidateCollectedTests: 512
  candidateModules: 23
  explicitPriorityTests: 84
  explicitP0Tests: 66
  explicitP1Tests: 18
  runtimeSkipped: 0
  pending: 0
  fixme: 0
  conditionalEnvironmentSkip: '7 new cases skip only when current-native Campaign or Save package is absent; present in recorded run'
coverage_heuristics:
  api_endpoint_coverage: 'not_applicable_no_http_or_openapi_surface'
  authority_negative_paths: 'present_player_maintenance_session_candidate_and_visibility_guards'
  error_paths: 'direct_CON-03_negative_matrix_discovered_execution_failed_mapping_pending_step_03'
  ui_journey_coverage: 'not_applicable_backend_cli_mcp_project'
  ui_state_coverage: 'not_applicable_backend_cli_mcp_project'
coverageSummary:
  p0: {total: 46, full: 25, percentage: 54.3}
  p1: {total: 9, full: 2, percentage: 22.2}
  p2: {total: 0, full: 0, percentage: null}
  p3: {total: 0, full: 0, percentage: null}
  overall: {total: 55, full: 27, percentage: 49.1}
coverageStatusCounts:
  full: 27
  partial: 18
  unitOnly: 4
  integrationOnly: 3
  none: 3
observedExecution:
  focused: {total: 7, passed: 3, failed: 4, failingCriterion: 'CON-03'}
  repositoryFullPytest: {passed: 1151, failed: 4, subtestsPassed: 10331, status: 'FAIL'}
  directlyFailingCriteria: ['CON-03', 'STA-02']
collectionStatus: 'COLLECTED'
gateEligible: true
gateDecision: 'FAIL'
---

# 可追溯性矩阵与质量门决策：current-save 模拟用户测试重基线

**目标：** 2026-07-01 历史模拟用户测试向当前 external candidate / Kernel 架构迁移后的覆盖核验

**日期：** 2026-07-15

**评估者：** Oliver / BMAD TEA Master Test Architect

**覆盖 Oracle：** Test Design 中原子化的 P0/P1 测试责任与用户确认的迁移规则

**Oracle 置信度：** 高

> 本 workflow 只建立需求到测试的映射并作门禁判断，不生成测试。覆盖缺口应交由后续 `bmad-testarch-automate` 或承载产品 AC 的 `bmad-testarch-atdd` 处理。

## Step 1：覆盖 Oracle 与上下文

### 已解析的 Oracle

- **覆盖基础：** `acceptance_criteria`。系统级 Test Design 已把本轮目标拆成 55 个稳定原子 coverage ID，其中 P0=46、P1=9，并给出风险、层级、期望证据与门禁。
- **解析方式：** `formal_requirements`。选择 Test Design 与用户已确认的测试迁移边界作为正式需求，不使用源码 synthetic inference，也不以现有测试数量反推需求。
- **选择理由：** 这些 artifact 直接描述本次历史失败点迁移、Skill/candidate/Kernel 分层、temporary Save、hidden/authority、真实 Hermes 哨兵与完整报告要求；比一般 PRD、接口 schema 或源码路径更精确地界定本次 trace target。
- **置信度：** `high`。四份设计/交接 artifact 对 55 个 ID、14 项风险、1,016/382 历史基线及 P0/P1 门槛保持一致，且 Test Design 已完成独立 clean audit。
- **外部指针：** `not_used`。本轮 oracle 均为仓库内正式 artifact，没有待解析的 Jira、Linear、Confluence 或共享文档指针。

### Oracle 来源与优先级

1. `_bmad-output/test-artifacts/test-design-qa.md`：55 个 coverage ID、P0/P1 门禁、Entry/Exit Criteria 与执行策略。
2. `_bmad-output/test-artifacts/test-design-progress.md`：coverage ID 的风险推导、历史 1,016/382 迁移规则与 provenance。
3. `_bmad-output/test-artifacts/test-design-architecture.md`：事实权威、hidden、transaction、candidate/binder 与 delta authority 的架构边界。
4. `_bmad-output/test-artifacts/test-design/aigm-kernel-handoff.md`：风险到 Epic/Story 与后续 TEA workflow 的交接关系。

### 支撑证据

- `automation-summary.md`：Test Automation 迭代 1 已新增 77 条 pytest case，重点实现 MIG/ART/ENV/SKL runner 的证据底座；最终 focused 77 passed，repository full pytest 为 1,148 passed / 10,331 subtests。
- `test-review.md`：迭代 1 质量评分 87/100（B，Approve with Comments），确定性、隔离与性能均为 100；无 P0 测试质量 blocker。
- 当前 77 条测试**不能**被解释为完整模拟用户重测已完成：1,016 行 owner 核验、382 ISSUE 逐项复现/归因、220–360 个结构化领域参数行、30×3 Skill 金标、12–18 个真实 Hermes journey 及正式 current-native dated run 仍是明确开放范围。

### 风险与门禁基线

- 风险共 14 项：R-001–R-007 为 9 分阻断级，R-008–R-013 为 6 分高风险，R-014 为 4 分中风险。
- P0 coverage 与 pass rate 必须为 100%；P1 coverage/pass rate 门槛为 95%。
- hidden、AI authority、formal/source 数据、transaction integrity 不允许 waiver。
- 1,016 个历史案例映射完整率与 382 个 ISSUE 归因覆盖率均必须为 100%。
- 外部 provider 的 `INFRA_ERROR` 不计产品 PASS/FAIL；未知性能/flake 阈值保持 UNKNOWN。

## Step 2：测试发现与分类

### 发现方法

- 以 `.venv/bin/python -m pytest --collect-only -q` 为稳定 runtime identity 来源；当前仓库共收集 1,148 个 test node。
- 先按 55 个 oracle ID 的 action/candidate/binder/transaction/query/visibility/domain/environment/system/artifact 语义扫描全部 `tests/test_*.py`，再选出 22 个高信号模块作为 Step 3 的候选池。
- 候选池共 505 个 collected node；这表示“待映射候选”，不是 505 个 criterion 已覆盖。Step 3 只采用能提供直接行为证据的测试，并拒绝仅同名或邻近覆盖。
- 稳定 identity 使用完整 pytest node ID；源码 identity 记录 `file`、测试函数起始 `line`、class/函数标题和 level。参数化 case 保留 pytest 的 `[...]` suffix。
- 静态扫描未发现 `skip/skipif/xfail`、TODO 或 FIXME 测试；最近 full suite 也报告 1,148 passed、无 skipped。故当前候选的 `skipped=false`、`pending=false`、`fixme=false`。

### 候选测试目录

| TEA Level | Collected candidates | 主要模块与职责 |
|---|---:|---|
| Unit | 217 | 发现阶段的粗粒度 module bucket：`test_action_slot_contract.py`、`test_action_taxonomy.py`、`test_ai_intent.py`、`test_validation_pipeline.py` 及四个 Automation 迭代 1 模块；覆盖 schema、candidate、mapping/artifact/fingerprint/fake runner 合同 |
| API（Backend Integration） | 197 | 发现阶段的粗粒度 module bucket：`test_runtime.py`、`test_save_manager.py`、`test_pending_confirmation_replay.py`、六个 `test_current_native_*` 模块及两个 cross-campaign smoke；覆盖 service/SQLite/temporary Save 行为 |
| E2E（Backend System） | 91 | `test_mcp_adapter.py`、`test_mcp_transcript.py`、`test_v1_cli.py`；覆盖 CLI/MCP 外壳到 Kernel/SaveManager 的公开链路，但不是本轮尚未执行的真实 Hermes journey |
| Component | 0 | 后端项目无浏览器组件层 |
| **合计** | **505** | 22 个高信号模块；允许跨层纵深但不得把同名当直接覆盖 |

以上 217/197/91 是 Step 2 按模块调度的粗分，不是最终逐测试 level 统计；`test_ai_intent.py` 同时包含 pure contract Unit 与读取 SQLite/authority fixture 的 binder Integration。Step 3/4 以单个 stable identity 重新分类为准。

### 显式 ID 与优先级

- Automation 迭代 1 的 77 个 collected case 具有 docstring coverage ID，并由 `tests/conftest.py` 转换为 pytest marker：P0=59、P1=18。
- 其余既有测试使用稳定函数名/node ID，但没有 P0/P1 marker 或本轮 coverage ID；它们的优先级只能在 Step 3 根据所映射 oracle criterion 继承，不能从文件名臆造。
- 直接出现的 coverage family 为 MIG-01–03、ART-01/02、ENV-04、SKL-01/05、CNT-02、SYS-01；其中 SKL/SYS 仅验证 runner/manifest/fake adapter 合同，不代表真实模型或端到端旅程已执行。

### 代表性稳定身份目录

| Level | Stable node ID | File:line | 发现信号 |
|---|---|---|---|
| Unit | `AIIntentTests::test_external_candidate_contract_rejects_authority_fields_and_overwrites_provenance` | `tests/test_ai_intent.py:1136` | external candidate 不得携带 authority |
| API | `AIIntentTests::test_binder_keeps_hallucinated_entity_out_of_final_options` | `tests/test_ai_intent.py:805` | 读取 SQLite/authority fixture 的 binder Integration；幻觉实体 fail closed |
| Unit | `ActionSlotContractTests::test_binding_is_read_only_for_connection_state` | `tests/test_action_slot_contract.py:1268` | binder 只读 |
| Unit | `test_complete_manifest_and_results_satisfy_local_contracts` | `tests/test_automation_artifact_contract.py:20` | dated artifact 合同 |
| API | `GMRuntimeTests::test_query_scene_and_entity_do_not_mutate_save` | `tests/test_runtime.py:1327` | query/scene/entity 只读 |
| API | `SaveManagerTests::test_player_turn_ready_preview_does_not_mutate_authoritative_state_until_confirm` | `tests/test_save_manager.py:267` | preview/pending no-mutation |
| API | `PendingConfirmationReplayTests::test_two_thread_confirm_has_one_fresh_commit_and_one_replay` | `tests/test_pending_confirmation_replay.py:58` | confirm 单次提交与 replay 幂等 |
| API | `CurrentNativeVisibilityTests::test_player_safe_query_and_scene_output_do_not_expose_hidden_probe` | `tests/test_current_native_visibility.py:1472` | player query/scene hidden 防泄露 |
| API | `CrossCampaignContextSmokeTests::test_two_campaigns_share_context_and_player_safe_loop_on_temp_saves` | `tests/test_cross_campaign_context_smoke.py:118` | cross-campaign temporary Save 链路 |
| E2E | `MCPTranscriptTests::test_transcript_*`（具体 node 在 Step 3 逐项选取） | `tests/test_mcp_transcript.py` | MCP 公共 transcript |
| E2E | `V1CliTests::test_player_handler_routes_turn_act_and_confirm_through_save_manager` | `tests/test_v1_cli.py:125` | CLI 只经 SaveManager authority gate |

### Coverage Heuristics Inventory

- **HTTP/API endpoint：** N/A。仓库没有 OpenAPI/Swagger、HTTP route 或服务端 endpoint oracle；这里的 API level 指 Python public service/SQLite integration。`SaveManager.player_query/player_turn/player_confirm`、Runtime preview/validate/commit 与 MCP/CLI adapter 均有直接候选测试。
- **Auth/Authz：** 没有 login/token/session-auth 产品需求。与本轮等价的权限边界（player/maintenance profile、candidate authority field、wrong/expired/cross-session confirmation、hidden visibility）存在明确负例；完整性由 Step 3 对 CNT/TRN/QRY/SYS criterion 逐项判断。
- **Error path：** 已发现 schema/version/unknown-field、missing/ambiguous/hidden/retired、wrong/expired confirmation、write failure、timeout/INFRA_ERROR、path escape、rollback 与 no-mutation 测试。是否仅 happy path 必须按 criterion 检查，不能以存在错误测试概括为全覆盖。
- **UI journey/state：** N/A；项目为 backend/CLI/MCP，无页面、路由、表单、loading/empty rendering 或浏览器 component。

## Step 3：需求到测试的可追溯矩阵

### Coverage Summary

只把直接满足 criterion 的证据计为 `FULL`；相邻测试、fake provider、仅 schema 合同或仅低层覆盖不会被提升为完整系统覆盖。

| Priority | Total Criteria | FULL | Coverage | Status |
|---|---:|---:|---:|---|
| P0 | 46 | 21 | 45.7% | ❌ FAIL |
| P1 | 9 | 2 | 22.2% | ❌ FAIL |
| P2 | 0 | 0 | N/A | N/A |
| P3 | 0 | 0 | N/A | N/A |
| **Total** | **55** | **23** | **41.8%** | **❌ FAIL** |

**Status 统计：** FULL=23、PARTIAL=18、UNIT-ONLY=4、INTEGRATION-ONLY=3、NONE=7。

### Identity 与判定规则

- 下表中的 test ID 是稳定 pytest node identity；`file:line` 是测试定义起始位置；level 使用 Unit、API（Backend Integration）或 E2E（Backend System）。
- 所有列出的测试当前均为 `skipped=false`、`pending=false`、`fixme=false`；重复引用按完整 node ID 去重。
- `G/W/T` 分别表示 Given / When / Then 的压缩证据。`缺口`只记录为何不能标为 FULL，不在本步骤安排修复。
- CI/static gate 行使用执行 artifact，而不是伪造 pytest identity。

### 历史迁移与 Skill/Candidate

| ID | Pri | Coverage | Direct test identity / level | G/W/T evidence | 缺口 |
|---|---|---|---|---|---|
| MIG-01 | P0 | PARTIAL ⚠️ | `test_frozen_inventory_contains_exactly_the_ten_probe_reports` — `tests/test_legacy_probe_migration.py:26` (Unit)；`test_frozen_manifest_detects_report_drift` — `:124` (Unit) | G=当前 2026-07-01 报告；W=发现并计算 SHA-256/模拟生成后漂移；T=只接受十份 probe 且生成 manifest 后的漂移硬失败 | 缺少已持久化、受信任的 frozen digest 基线；运行前被等量篡改且仍满足 1,016/382 时无法由当前测试识别 |
| MIG-02 | P0 | PARTIAL ⚠️ | `test_actual_frozen_tables_match_the_1016_and_382_baseline` — `tests/test_legacy_probe_migration.py:38` (Unit)；`test_generated_mapping_has_exactly_one_row_per_legacy_case` — `:139` (Unit) | G=真实十份表；W=解析并生成 mapping；T=1,016 行、稳定且唯一 | rule-based bootstrap 尚未逐行由领域 owner 核验，mapping 也未持久化为最终 trace artifact |
| MIG-03 | P0 | PARTIAL ⚠️ | `test_all_legacy_issues_have_a_disposition_or_retirement_proof` — `tests/test_legacy_probe_migration.py:150` (Unit)；`test_issue_row_without_any_disposition_evidence_is_rejected` — `:202` (Unit) | G=382 个 ISSUE；W=验证 disposition 字段；T=字段缺失即失败 | 当前 reproduction/attribution 可自动填充，未证明 382 项真实复现与归因有效 |
| SKL-01 | P0 | UNIT-ONLY ⚠️ | `test_semantic_or_candidate_contract_mismatch_is_functional_fail` — `tests/test_external_probe_runner_contract.py:40` (Unit)；`test_internal_intent_ai_must_be_disabled_for_external_skill_eval` — `:98` (Unit) | G=fake external case；W=合同不匹配/内部 AI 启用；T=FAIL 或 manifest 拒绝 | 未运行 query/action/maintenance/unknown 的真实 Hermes+flash 金标 |
| SKL-02 | P1 | NONE ❌ | 无 | — | 八领域 action/slot 的真实 Skill 金标未实现、未执行 |
| SKL-03 | P1 | UNIT-ONLY ⚠️ | `AIIntentTests::test_arbiter_clarifies_when_external_candidate_missing_required_slot` — `tests/test_ai_intent.py:1886` (Unit)；`test_enabled_composite_handles_empty_duplicate_mismatch_and_early_disagreement` — `:1979` (Unit) | G=缺槽位/复合 candidate；W=Kernel arbiter 处理；T=clarify/fail closed | 只证明 Kernel 对结构化输入的处置，未评估 Skill 是否正确生成 clarify/composite |
| SKL-04 | P0 | INTEGRATION-ONLY ⚠️ | `GMRuntimeTests::test_act_blocks_out_of_world_or_force_save_text` — `tests/test_runtime.py:4114` (API)；`test_consensus_intent_ai_blocks_hidden_info_query_before_query_preview` — `:3662` (API) | G=越权/hidden 请求；W=Runtime route；T=阻断且不 preview/commit | 未运行真实 Skill prompt-injection/hidden/force-save 金标，故不能评价模型语义安全率 |
| SKL-05 | P1 | UNIT-ONLY ⚠️ | `test_deepseek_flash_manifest_contains_reproducible_provenance` — `tests/test_external_probe_runner_contract.py:57` (Unit)；`test_external_summary_excludes_infra_error_from_accuracy` — `:108` (Unit) | G=DeepSeek flash manifest 与合成结果；W=校验/汇总；T=provenance 完整且 INFRA_ERROR 不入分母 | 未做 30 条×3 重复运行、provider drift 或一致性矩阵 |
| CNT-01 | P0 | FULL ✅ | `AIIntentTests::test_external_contract_exact_match_and_legacy_omission_return_bounded_evidence` — `tests/test_ai_intent.py:324` (Unit)；`test_off_mode_external_primary_accepts_bound_action_without_rules_agreement` — `:1201` (Unit) | G=合法 versioned candidate；W=合同验证/route；T=被接收但仍保持低信任 provenance | — |
| CNT-02 | P0 | FULL ✅ | `AIIntentTests::test_intent_candidate_schema_and_external_ingress_reject_unknown_safety` — `tests/test_ai_intent.py:194` (Unit)；`test_external_candidate_contract_rejects_unknown_fields` — `:1118` (Unit) | G=未知 safety、字段/shape 错误；W=ingress validation；T=稳定 typed error、域归一化前拒绝 | — |
| CNT-03 | P0 | FULL ✅ | `AIIntentTests::test_ai_candidate_normalizer_keeps_maintenance_out_of_player_modes` — `tests/test_ai_intent.py:543` (Unit)；`test_external_candidate_contract_rejects_authority_fields_and_overwrites_provenance` — `:1136` (Unit) | G=maintenance/伪 authority candidate；W=normalize/validate；T=玩家模式拒绝且外部 provenance 不升级权限 | — |
| CNT-04 | P0 | FULL ✅ | `AIIntentTests::test_off_mode_external_primary_rejects_unsafe_unbound_unknown_and_composite` — `tests/test_ai_intent.py:1242` (Unit)；`test_arbiter_clarifies_when_external_candidate_missing_required_slot` — `:1886` (Unit) | G=unsafe/unbound/unknown/missing slot；W=route/arbiter；T=不得直接 ready | — |

### Binder、Transaction 与 Query

| ID | Pri | Coverage | Direct test identity / level | G/W/T evidence | 缺口 |
|---|---|---|---|---|---|
| BND-01 | P1 | FULL ✅ | `AIIntentTests::test_binder_binds_social_slots_to_visible_entity_ids` — `tests/test_ai_intent.py:780` (API)；`test_binder_covers_gather_and_explore_target_location_slots` — `:949` (API) | G=当前可见实体/alias 与 typed slots；W=binder 查询 authority；T=确定绑定为 canonical ID | — |
| BND-02 | P0 | FULL ✅ | `AIIntentTests::test_binder_keeps_hallucinated_entity_out_of_final_options` — `tests/test_ai_intent.py:805` (API)；`test_binder_reports_ambiguous_entity_alias` — `:826` (API)；`test_binder_ignores_hidden_entities_in_player_view` — `:850` (API) | G=幻觉/歧义/hidden 实体；W=binder 解析；T=不进入最终事实选项且保持只读 | — |
| BND-03 | P0 | PARTIAL ⚠️ | `AIIntentTests::test_binder_visibility_and_archived_binding_are_read_only` — `tests/test_ai_intent.py:871` (API)；`CrossCampaignContextSmokeTests::test_two_campaigns_share_context_and_player_safe_loop_on_temp_saves` — `tests/test_cross_campaign_context_smoke.py:118` (API) | G=archived 与两个 Campaign；W=分别 bind/run；T=archived fail closed、Campaign 状态不串写 | 缺少把 Campaign A ID 明确注入 Campaign B candidate 的负例及 registry-version incompatibility 断言 |
| TRN-01 | P0 | FULL ✅ | `SaveManagerTests::test_player_turn_ready_preview_does_not_mutate_authoritative_state_until_confirm` — `tests/test_save_manager.py:267` (API) | G=temporary Save ready action；W=player_turn 创建 pending；T=事实不变、仅 pending 可见 | — |
| TRN-02 | P0 | FULL ✅ | `SaveManagerTests::test_player_confirm_real_pending_failures_do_not_mutate_or_clear_pending` — `tests/test_save_manager.py:690` (API)；`test_player_confirm_real_pending_wrong_save_does_not_mutate_either_save_or_clear_pending` — `:730` (API)；`test_player_confirm_expired_or_incomplete_real_pending_does_not_mutate_save` — `:795` (API) | G=错误/串线/过期 confirmation；W=player_confirm；T=零写入并保留/清理正确证据 | — |
| TRN-03 | P0 | FULL ✅ | `SaveManagerTests::test_player_act_confirm_hides_internal_delta_and_saves` — `tests/test_save_manager.py:220` (API)；`CrossCampaignContextSmokeTests::test_two_campaigns_share_context_and_player_safe_loop_on_temp_saves` — `tests/test_cross_campaign_context_smoke.py:118` (API) | G=合法 pending/token；W=matching confirm；T=仅一次预期 turn/event/delta 且 player surface 不暴露 raw delta | — |
| TRN-04 | P0 | FULL ✅ | `PendingConfirmationReplayTests::test_two_thread_confirm_has_one_fresh_commit_and_one_replay` — `tests/test_pending_confirmation_replay.py:58` (API)；`test_normal_clear_retry_returns_stable_bounded_replay` — `:84` (API) | G=并发/重复 confirm；W=同一 confirmation identity 重放；T=一条 fresh commit，其余为有界幂等 replay | — |
| TRN-05 | P0 | FULL ✅ | `CurrentNativeWriteSafetyTests::test_stale_expected_turn_is_zero_side_effect_on_temp_copy` — `tests/test_current_native_write_safety.py:37` (API)；`test_failed_save_turn_on_temp_copy_rolls_back_sqlite_and_event_log` — `:110` (API)；`ValidationPipelineTests::test_player_commit_service_rejects_delta_without_turn_proposal` — `tests/test_validation_pipeline.py:241` (API) | G=stale/bad delta 或缺 proposal；W=validate/commit；T=持久化前拒绝、SQLite/event log rollback | — |
| QRY-01 | P0 | FULL ✅ | `CurrentNativeContextTests::test_current_entity_query_matrix_covers_inventory_people_threats_and_clocks` — `tests/test_current_native_context.py:739` (API)；`CurrentNativePlayerTurnTests::test_player_turn_queries_use_the_same_current_native_query_output` — `tests/test_current_native_player_turn.py:223` (API) | G=current-native authority；W=entity/scene/context query；T=结果含权威 ID，player_turn 与 direct query 一致 | — |
| QRY-02 | P0 | PARTIAL ⚠️ | `CurrentNativePlayerTurnTests::test_player_turn_queries_use_the_same_current_native_query_output` — `tests/test_current_native_player_turn.py:223` (API)；`CurrentNativeContextTests::test_current_entity_query_matrix_covers_inventory_people_threats_and_clocks` — `tests/test_current_native_context.py:739` (API) | G=当前 scene 与实体矩阵；W=query；T=scene/location 标题与 ID 正确 | 没有直接断言历史失败中要求的聚合数量/计数与 SQLite 对照 |
| QRY-03 | P0 | FULL ✅ | `GMRuntimeTests::test_query_scene_and_entity_do_not_mutate_save` — `tests/test_runtime.py:1327` (API)；`SaveManagerTests::test_player_act_executes_query_without_pending_confirmation` — `tests/test_save_manager.py:250` (API) | G=scene/entity/query；W=Runtime/SaveManager 查询；T=无 pending/turn/event/事实变化 | — |
| QRY-04 | P0 | FULL ✅ | `CurrentNativeVisibilityTests::test_player_safe_query_and_scene_output_do_not_expose_hidden_probe` — `tests/test_current_native_visibility.py:1472` (API)；`GMRuntimeTests::test_consensus_intent_ai_blocks_hidden_info_query_before_query_preview` — `tests/test_runtime.py:3662` (API) | G=hidden probe/hidden query；W=player result/error/context；T=player surface 无 token/ID，GM view 可见 | — |

### 领域行为

| ID | Pri | Coverage | Direct test identity / level | G/W/T evidence | 缺口 |
|---|---|---|---|---|---|
| INT-01 | P1 | NONE ❌ | 无 | — | 没有合法 intake delta 经 player confirm 后的实体/item/event 精确差异测试 |
| INT-02 | P0 | PARTIAL ⚠️ | `ValidationPipelineTests::test_commit_service_rejects_validation_report_for_different_delta` — `tests/test_validation_pipeline.py:195` (API)；`ResidentAIAdvisoryReviewTests::test_intake_does_not_call_queue_apply_commit_or_provider_owners` — `tests/test_resident_ai_advisory_review.py:1989` (Unit) | G=不匹配 delta/低信任 intake；W=commit/intake；T=拒绝或不触碰 commit owners | 缺少历史 intake malformed/bad delta 走当前 player transaction 且精确 no-mutation 的回归 |
| CON-01 | P0 | NONE ❌ | 无 | — | 没有 consumption 精确扣减指定数量的当前 structured-candidate/temporary-Save 测试 |
| CON-02 | P0 | NONE ❌ | 无 | — | 没有扣减后 quality/unit/properties/durability metadata 深比较 |
| CON-03 | P0 | NONE ❌ | 无 | — | 没有 insufficient/stale before_quantity/非法物品的 consumption no-mutation 矩阵 |
| CMB-01 | P0 | PARTIAL ⚠️ | `ActionResolverCombinationCoverageTests::test_combat_resolver_ready_blocked_and_delta_validation_paths` — `tests/test_maintenance_tooling_coverage.py:5345` (API) | G=武器/弹药/目标 fixture；W=resolver 与 bad decrement validation；T=ready delta 形成且错误 quantity 被拒绝 | 未经 pending→confirm 提交，也未断言实际弹药 before/after 与事件唯一性 |
| CMB-02 | P0 | PARTIAL ⚠️ | `ActionResolverCombinationCoverageTests::test_combat_resolver_ready_blocked_and_delta_validation_paths` — `tests/test_maintenance_tooling_coverage.py:5345` (API)；`CurrentNativeActionTests::test_low_level_previews_enforce_delta_guards_and_confirmation_boundaries` — `tests/test_current_native_actions.py:25` (API) | G=missing target/weapon/ammo、位置冲突；W=resolve/preview；T=needs_confirmation/fail closed | retired/unreliable ammo 及完整 no-mutation transaction 尚未直接覆盖 |
| CRF-01 | P0 | NONE ❌ | 无 | — | 没有 craft 材料精确消耗、输出生成和 commit 后 inventory exact diff |
| CRF-02 | P0 | PARTIAL ⚠️ | `ActionResolverCombinationCoverageTests::test_craft_resolver_ready_blocked_and_delta_validation_paths` — `tests/test_maintenance_tooling_coverage.py:5244` (API)；`PaletteGovernanceTests::test_craft_palette_candidate_creates_plan_only` — `tests/test_palette_governance.py:295` (API) | G=project/recipe/palette；W=resolve/preview/validate；T=形成 plan-only 或识别错误 project payload | 未提交 project/progress delta，也未验证重复 confirm 不重复产出 |
| CRF-03 | P0 | PARTIAL ⚠️ | `ActionResolverCombinationCoverageTests::test_craft_resolver_ready_blocked_and_delta_validation_paths` — `tests/test_maintenance_tooling_coverage.py:5244` (API) | G=unknown output/缺材料/配方/耗时；W=resolver/validator；T=needs_confirmation 或 errors | 缺错误地点与 pending/confirm 层的 no-mutation 精确证据 |
| EXP-01 | P1 | FULL ✅ | `CurrentNativeActionTests::test_explore_preview_delta_does_not_silently_confirm_hidden_facts` — `tests/test_current_native_actions.py:139` (API) | G=known current-native target；W=explore preview；T=canonical target event、允许 delta、未擅自确认 hidden fact | — |
| EXP-02 | P0 | FULL ✅ | `GMRuntimeTests::test_unknown_explore_target_does_not_generate_committable_delta` — `tests/test_runtime.py:1669` (API)；`PaletteGovernanceTests::test_travel_palette_candidate_records_discovery_without_route_or_location_fact` — `tests/test_palette_governance.py:218` (API) | G=unknown lead/palette clue；W=preview/commit discovery；T=不创建已知实体/路线/location fact | — |
| EXP-03 | P0 | FULL ✅ | `PaletteGovernanceTests::test_trusted_explore_palette_preview_preserves_hidden_refs` — `tests/test_palette_governance.py:130` (API)；`CurrentNativeVisibilityTests::test_player_safe_query_and_scene_output_do_not_expose_hidden_probe` — `tests/test_current_native_visibility.py:1472` (API) | G=hidden explore target；W=player/GM preview 与 query；T=player 无 hidden ID/name，GM 可见 | — |
| RST-01 | P0 | PARTIAL ⚠️ | `CurrentNativeActionTests::test_rest_preview_delta_contract_advances_day_and_ticks_drought` — `tests/test_current_native_actions.py:121` (API) | G=current-native day/time/location；W=rest preview；T=day/time/clock delta 精确 | 缺恢复状态字段与合法 confirm 后的实际持久化断言 |
| RST-02 | P1 | PARTIAL ⚠️ | `CurrentNativeActionTests::test_rest_preview_delta_contract_advances_day_and_ticks_drought` — `tests/test_current_native_actions.py:121` (API)；`ActionSlotContractTests::test_builtin_required_matrix_and_optional_rest_are_deterministic` — `tests/test_action_slot_contract.py:1169` (Unit) | G=原地点与 rest contract；W=preview；T=location_before=after | 非法/不安全休息的明确 no-mutation 负例缺失 |
| SOC-01 | P0 | PARTIAL ⚠️ | `ActionResolverCombinationCoverageTests::test_social_resolver_scope_palette_and_delta_validation_paths` — `tests/test_maintenance_tooling_coverage.py:5293` (API) | G=same-place NPC/topic/approach；W=resolve/validate；T=relationship/no-change/trade payload 约束可断言 | 未通过 confirm 提交并核验 relationship/event exact diff 与 NPC 事实不变 |
| SOC-02 | P0 | PARTIAL ⚠️ | `GMRuntimeTests::test_social_same_parent_returns_micro_travel_repair_plan` — `tests/test_runtime.py:1711` (API)；`CurrentNativeActionTests::test_low_level_previews_enforce_delta_guards_and_confirmation_boundaries` — `tests/test_current_native_actions.py:25` (API) | G=异地/same-parent NPC；W=social resolve；T=位置阻断或 repair plan | remote 与 unknown NPC 的完整矩阵、retired/hidden 组合及 no-mutation 尚不齐 |
| TRV-01 | P0 | FULL ✅ | `CurrentNativeActionTests::test_travel_preview_delta_contract_uses_known_route_and_destination` — `tests/test_current_native_actions.py:106` (API)；`CurrentNativeSystemBlackBoxTests::test_travel_commit_reopens_runtime_at_new_scene_and_social_context` — `tests/test_cross_layer_regression.py:375` (E2E) | G=known route/destination；W=preview→validate→commit→reopen；T=route/time/meta/player location 一致且新 scene 正确 | — |
| TRV-02 | P0 | PARTIAL ⚠️ | `GMRuntimeTests::test_unknown_travel_destination_does_not_generate_committable_delta` — `tests/test_runtime.py:1625` (API)；`EngineUpgradeFixtureTests::test_missing_route_cross_reference_is_rejected` — `tests/test_upgrade_v2.py:133` (Unit) | G=unknown/unreachable route；W=preview/validate；T=不得 committable | 同地点与 retired location 的 player transaction no-mutation 负例未直接覆盖 |

### Environment、System、Artifact 与 Static Gate

| ID | Pri | Coverage | Direct test identity / level | G/W/T evidence | 缺口 |
|---|---|---|---|---|---|
| ENV-01 | P0 | FULL ✅ | `CurrentNativePackageTests::test_author_campaign_package_validates_and_smoke_tests_current_contracts` — `tests/test_current_native_package.py:29` (API)；`test_current_save_check_and_inspect_report_runtime_shape` — `:94` (API) | G=current-native Campaign/Save；W=validate/test/check/inspect；T=当前合同与 health 成立 | — |
| ENV-02 | P0 | FULL ✅ | `CrossCampaignContextSmokeTests::test_two_campaigns_share_context_and_player_safe_loop_on_temp_saves` — `tests/test_cross_campaign_context_smoke.py:118` (API)；`CrossCampaignModelSmokeTests::test_two_campaigns_share_foundation_model_contracts_on_temp_saves` — `tests/test_cross_campaign_model_smoke.py:87` (API) | G=两个 Campaign 的独立 temp Saves；W=相同公共链路运行；T=各自 authority/context/state 保持隔离 | — |
| ENV-03 | P0 | FULL ✅ | `SaveManagerTests::test_start_or_continue_creates_from_starter_then_continues` — `tests/test_save_manager.py:124` (API)；`test_multiple_saves_can_be_created_listed_and_switched` — `:198` (API)；TRN-01–04 测试 | G=temp package/registry；W=clone/load/switch/pending/confirm/replay；T=生命周期与 cleanup/authority 正确 | — |
| ENV-04 | P0 | PARTIAL ⚠️ | `test_all_four_authoritative_surfaces_are_registered` — `tests/test_formal_source_fingerprint_guard.py:32` (Unit)；`test_guard_detects_mutation_after_timeout` — `:82` (Unit)；`test_fingerprint_evidence_contains_exact_before_and_after_snapshots` — `:149` (Unit) | G=四类 synthetic protected surfaces；W=normal/error/timeout guard；T=变化硬失败、clean evidence 前后一致 | 尚未对实际 current-native source Campaign、formal Save、正式 registry 与真实 `data/game.sqlite` 做 dated run 前后指纹 |
| SYS-01 | P0 | UNIT-ONLY ⚠️ | `test_runner_uses_an_injected_adapter_without_network_authority` — `tests/test_external_probe_runner_contract.py:127` (Unit) | G=fake adapter/query case；W=runner 调用；T=PASS/evidence path，provider 无 authority | 没有真实 Hermes+DeepSeek flash 的只读 query transcript/tool trace |
| SYS-02 | P1 | NONE ❌ | 无 | — | 八领域各至少一个真实 Hermes 成功 journey（合计 12–18）未实现/执行 |
| SYS-03 | P0 | INTEGRATION-ONLY ⚠️ | `GMRuntimeTests::test_consensus_intent_ai_blocks_hidden_info_query_before_query_preview` — `tests/test_runtime.py:3662` (API)；`MCPAdapterTests::test_mcp_developer_player_act_clears_stale_pending_action_when_new_action_needs_clarification` — `tests/test_mcp_adapter.py:743` (E2E) | G=hidden/clarify lower-layer input；W=Runtime/MCP；T=阻断或澄清且不提交 | 无真实 Hermes transcript，因此只证明 Kernel/adapter 防线 |
| SYS-04 | P0 | INTEGRATION-ONLY ⚠️ | `MCPAdapterTests::test_mcp_player_turn_hides_delta_and_confirms_pending_action` — `tests/test_mcp_adapter.py:716` (E2E)；`PendingConfirmationReplayTests::test_two_thread_confirm_has_one_fresh_commit_and_one_replay` — `tests/test_pending_confirmation_replay.py:58` (API) | G=pending/confirm/replay lower-layer链；W=MCP/SaveManager；T=正确确认、隐藏 delta、幂等 replay | 缺真实 Hermes 的错误确认→正确确认→replay 全 transcript |
| ART-01 | P0 | PARTIAL ⚠️ | `test_complete_manifest_and_results_satisfy_local_contracts` — `tests/test_automation_artifact_contract.py:18` (Unit)；`test_run_directory_rejects_each_missing_required_artifact` — `:174` (Unit) | G=synthetic dated run；W=validate manifest/results/mapping/INDEX/fingerprint/timing；T=缺一即失败 | 只验证合同，尚无实际 current-native/Hermes 完整 dated run artifact |
| ART-02 | P1 | PARTIAL ⚠️ | `test_fail_result_requires_actionable_diagnostic_fields` — `tests/test_automation_artifact_contract.py:78` (Unit)；`test_each_result_keeps_coverage_and_legacy_traceability` — `:186` (Unit) | G=synthetic FAIL/result；W=schema validation；T=复现、expected/actual、severity、attribution、evidence/coverage ID 必填 | 尚无真实失败运行记录可验证证据内容质量 |
| STA-01 | P0 | FULL ✅ | 非 pytest：`_bmad-output/test-artifacts/automation-summary.md:195`–`:198` (CI evidence) | G=Automation 最终测试 diff；W=Campaign validate/test、Markdown links、py_compile、Ruff、diff check；T=全部 PASS | — |
| STA-02 | P0 | FULL ✅ | 非 pytest：`_bmad-output/test-artifacts/automation-summary.md:194` (CI evidence) | G=Automation 最终测试 diff；W=repository full pytest；T=1,148 passed、10,331 subtests passed | — |

### Coverage Logic Validation

- **P0/P1 是否都有 coverage：** 否。7 个 criterion 为 NONE，其中 P0 有 CON-01/02/03、CRF-01，P1 有 SKL-02、INT-01、SYS-02。
- **API endpoint heuristic：** N/A；无 HTTP/OpenAPI surface。Python service/SQLite integration 的 FULL 判定均有直接 public/kernel boundary 证据。
- **Authority negative paths：** CNT-03/04、BND-02、TRN-02/05、QRY-04 均含 denied/invalid path；没有以正向 happy path 替代权限结论。
- **Error-path completeness：** FULL 的 transaction/query/candidate 项均含关键负例；缺错误态的 domain/system 项保持 PARTIAL/NONE。
- **UI journey/state heuristic：** N/A；无 UI oracle。
- **重复覆盖：** hidden、authority、formal-data、transaction 使用 Unit/API/E2E 纵深是设计明确允许的 defense in depth；自然语言关键词路由没有被用来重复证明 Kernel transaction。

## Step 4：Phase 1 Gap Analysis

### 执行模式与独立复核

- 用户本轮未指定执行模式；配置为 `tea_execution_mode: auto`、capability probe 开启。
- 运行时支持三路 worker，因此解析为 `agent-team`。依赖安全的 gap 分类、heuristics、统计/去重并行只读执行，推荐综合与 JSON 合并由主流程完成。
- 三路复核确认 55 个 criterion 的优先级与初始计数一致，并发现 MIG-01 的可信 digest 基线不足；已把 MIG-01 从 FULL 修正为 PARTIAL。
- Binder level taxonomy 已统一：pure candidate contract 为 Unit；读取 SQLite/authority fixture 的 binder 行为为 API/Backend Integration。`BND-01` 因此保留 FULL。
- Phase 1 未作 gate decision。

### Gap Classification

**Critical NONE（P0，4）：**

- CON-01：consumption 精确扣减。
- CON-02：consumption metadata 保留。
- CON-03：insufficient/stale/非法物品 no-mutation。
- CRF-01：craft 材料消耗、输出与 commit exact diff。

**High NONE（P1，3）：**

- SKL-02：八领域真实 Skill action/slot 金标。
- INT-01：合法 intake 经 confirm 精确写入。
- SYS-02：八领域真实 Hermes 成功 journey。

**PARTIAL（18）：**

- P0：MIG-01、MIG-02、MIG-03、BND-03、QRY-02、INT-02、CMB-01、CMB-02、CRF-02、CRF-03、RST-01、SOC-01、SOC-02、TRV-02、ENV-04、ART-01。
- P1：RST-02、ART-02。

**Lower-level only（7）：**

- UNIT-ONLY：SKL-01、SKL-03、SKL-05、SYS-01。
- INTEGRATION-ONLY：SKL-04、SYS-03、SYS-04。

### Heuristics Findings

- **HTTP endpoint gaps：0。** 项目无 HTTP/OpenAPI surface；API level 指 Python service/SQLite integration。
- **Authority negative-path gaps：0 个独立 heuristic gap。** CNT/BND/TRN/QRY 已有直接 denied/invalid path；BND-03、SKL-04、SYS-01/03/04 的不足已经由 criterion status 表达，不能因一般 auth negative 已存在而降级。
- **Happy-path-only：1。** RST-02 现有证据只断言 location 保持，缺非法/不安全休息的 no-mutation 负例。若项目把所有非法领域写入统一提升为 P0 invariant，应在下一轮设计/Story 中明确调高，而不是在 Trace 中静默改 priority。
- **Browser UI journey/state：0 / N/A。** 但 CLI/MCP/Hermes 仍是玩家 public journey；SYS-02/03/04 的真实外部链路缺口保持原严重度。
- **Backend public journey gaps：3。** SYS-02、SYS-03、SYS-04。

### Deduplicated Test Inventory

| Level | Active collected identities | Criteria with this level |
|---|---:|---:|
| Unit | 40 | 17 |
| API / Backend Integration | 43 | 32 |
| E2E / Backend System | 3 | 3 |
| Component / Other | 0 | 0 |
| **Total** | **86** | 按 criterion 可跨 level 重叠 |

- 86 个 active identity 分布在 24 个文件；skipped/pending/fixme 均为 0。
- 定义级去重为 76；两个 parameterized Unit 定义各展开 6 个真实 pytest item，因此 collected identity 为 86。
- Step 3 共 89 次定义级引用，按 `file::class::test` 去重后有 13 次重复 surplus；均属于合理的 shared invariant/defense-in-depth 引用。
- ENV-03 的“TRN-01–04”仅是交叉引用，不制造伪 test identity；STA-01/02 是 CI artifact evidence，也不计入 pytest inventory。

### Recommendations

1. **URGENT：** 下一轮 `bmad-testarch-automate` 先实现 CON-01/02/03、CRF-01 四个 P0 NONE 的确定性 structured-candidate/temporary-Save 回归；若复现产品缺陷，再单独进入 BMAD fix Story/ATDD。
2. **HIGH：** 补齐 SKL-02、INT-01、SYS-02 三个 P1 NONE。
3. **URGENT：** 把 SKL-01/04、SYS-01/03/04 从 fake/Kernel-only 证据升级为真实 external/nightly journey；不得把低层绿灯冒充 Hermes 结论。
4. **HIGH：** 完成 18 个 PARTIAL，优先为 frozen reports 建立可信 digest、由 owner 核验 1,016/382、补 cross-campaign 对抗绑定、领域 no-mutation、actual formal fingerprints 与 dated artifact。
5. **MEDIUM：** 下一轮 Automation 发生实质测试/fixture diff 后重新运行 `bmad-testarch-test-review`。

### Phase 1 Machine Artifact

- **Path：** `/tmp/tea-trace-coverage-matrix-2026-07-15T07-55-35Z.json`
- **Validation：** JSON 有效；`phase=PHASE_1_COMPLETE`；55 requirements；23 FULL、18 PARTIAL、4 UNIT-ONLY、3 INTEGRATION-ONLY、7 NONE；86 active collected identities；`gate_decision_made=false`。

### Phase 1 Summary

- Total Requirements：55
- Fully Covered：23（41.8%，workflow 整数显示 42%）
- Partially Covered：18
- Lower-level only：7
- Uncovered：7
- P0：21/46 FULL（45.7%，workflow 整数显示 46%）
- P1：2/9 FULL（22.2%）
- Critical NONE：4
- High NONE：3
- Recommendations：5

## Step 5：Phase 2 Gate Decision

### 🚨 Gate Decision：FAIL

**判定理由：** P0 完整覆盖率为 46%（21/46；精确值 45.7%），低于必须达到的 100%；仍有 4 项 P0 关键需求完全未覆盖。因此 current-save 模拟用户测试重基线的发布门禁被阻断。

### 门禁指标

| 指标 | 实际 | 要求 | 状态 |
|---|---:|---:|---|
| P0 完整覆盖率 | 46%（21/46） | 100% | NOT_MET |
| P1 完整覆盖率 | 22%（2/9） | PASS 目标 90%，最低 80% | NOT_MET |
| 总体完整覆盖率 | 42%（23/55） | 最低 80% | NOT_MET |

### 未覆盖需求

- **P0 Critical：** CON-01、CON-02、CON-03、CRF-01。
- **P1 High：** SKL-02、INT-01、SYS-02。
- 另有 18 项 PARTIAL、4 项 UNIT-ONLY、3 项 INTEGRATION-ONLY；这些证据不能按 FULL 计入门禁。

### 测试执行状态说明

- 本次 Trace workflow 建立需求—测试映射并作覆盖门禁判断，没有重跑产品 full suite。
- 可复用的最终 clean-diff 执行证据来自 Test Automation：focused 77 passed；repository full pytest 1,148 passed / 10,331 subtests；Campaign validate/test、Markdown links、py_compile、full Ruff、`git diff --check` 均通过。
- 因此本次 `FAIL` 是**覆盖完备性门禁失败**，不是已执行 pytest 的功能失败。

### 建议动作

1. 立即运行下一轮 `bmad-testarch-automate`，先补 CON-01/02/03 与 CRF-01 四个 P0 NONE。
2. 随后补 SKL-02、INT-01、SYS-02，并把 SKL-01/04、SYS-01/03/04 升级为真实 Hermes + DeepSeek flash 外部链路证据。
3. 完成 trusted frozen digest、1,016/382 owner 核验、领域 no-mutation、真实 formal fingerprints 与 actual dated run；出现产品缺陷时另建 BMAD fix Story/ATDD。

### Machine-readable Outputs

- `_bmad-output/test-artifacts/e2e-trace-summary.json`
- `_bmad-output/test-artifacts/gate-decision.json`
- Phase 1 source：`/tmp/tea-trace-coverage-matrix-2026-07-15T07-55-35Z.json`

🚫 **GATE: FAIL — 在覆盖率和关键缺口达到门禁要求前，不得将本次模拟用户测试重基线视为发布就绪。**

## Iteration 2 — Step 1：覆盖 Oracle 与本轮证据

### 激活与模式

- **用户触发：** 显式调用 `bmad-testarch-trace`；catalog 路由为 `[TR] Traceability`，本轮按 Create 新迭代执行。
- **Skill provenance：** 完整读取 `AGENTS.md`、`.agents/skills/bmad-help/SKILL.md` 与 `.agents/skills/bmad-testarch-trace/SKILL.md`；customization resolver 返回空 prepend/append、空 `on_complete`，persistent fact 为 `docs/project-context.md`。
- **历史处理：** 上方 Iteration 1 的完整矩阵和 `FAIL` 决策保持为不可混淆的历史基线；Iteration 2 只追加新证据并重新计算映射、gap 与 gate。
- **工作边界：** Trace 只建立需求—测试双向映射并作门禁判断，不修改 production、不 xfail/skip 红灯，也不调用外部或内部 AI。

### Oracle 决议

- **coverageBasis：** `acceptance_criteria`。
- **oracleResolutionMode：** `formal_requirements`。
- **oracleConfidence：** `high`。
- **externalPointerStatus：** `not_used`。
- **正式 Oracle：** `_bmad-output/test-artifacts/test-design-qa.md` 中 55 个稳定 coverage ID（P0=46、P1=9）及风险/门槛；Architecture、Progress 与 handoff 提供边界和 provenance，但不以源码 synthetic inference 代替正式需求。
- **门禁不变：** P0 coverage/pass 必须 100%，P1 coverage/pass 必须至少 95%；hidden、AI authority、formal/source 数据与 transaction integrity 不允许 waiver。

### Iteration 2 输入证据

- Test Automation 新增 `tests/test_current_native_consumption_craft_deltas.py`，包含 4 个逻辑测试 / 7 个 collected P0 Integration case，直接对应 `CON-01`、`CON-02`、`CON-03`、`CRF-01`。
- Focused 实测：3 passed、4 failed，71.57s。`CON-01`、`CON-02`、`CRF-01` 通过；`CON-03` 的 insufficient、stale-before、item-mismatch、malformed-quantity 均因真实 `commit_turn` 未抛 `ValueError` 而失败。
- Adjacent regression：95 passed + 45 subtests；Campaign validate/test、Markdown links、repository py_compile、full Ruff、`git diff --check` 均 PASS。
- Repository full pytest：1151 passed、4 failed、10331 subtests passed，580.78s；失败范围仅 `CON-03`。
- Test Review：92/100（A，Approve with Comments），无测试质量 P0 blocker；确定性 100、隔离 95、可维护性 80、性能 90。此 approval 仅说明红灯测试可作为可靠产品缺陷证据，不解除产品 gate。
- 数据安全：所有写操作只针对独立 current-native temporary Save；source Campaign、formal Save 与正式 registry 前后不变；无外部 AI、内部 intent AI 或 state-audit AI 调用，无 hidden/GM-only 内容进入 player surface。

### Step 1 判定约束

- 本轮必须区分两个维度：**coverage presence** 表示是否存在直接、稳定、可执行的 criterion 测试；**requirement execution** 表示该测试是否通过。`CON-03` 已有直接 P0 Integration 覆盖，但需求执行为 FAIL，不能写成 PASS，也不能继续写成“无测试”。
- `CON-01/02/CRF-01` 的绿灯只证明 structured GM-resolved delta 的 Kernel commit 行为；不外推为 external Skill、1,016/382 历史归因或真实 Hermes journey 完成。
- Iteration 1 的其余 51 个 criterion 保持待重新发现/核验；不得未经 Step 2/3 直接复用旧统计。

### Step 1 结论

- 正式 Oracle、执行证据、测试质量证据与数据边界均已加载，未触发 HALT。
- 下一步按 `step-02-discover-tests.md` 重新发现稳定 pytest identity、优先级与执行状态，再生成 Iteration 2 双向可追溯矩阵。

## Iteration 2 — Step 2：测试发现与分类

### 发现方法与范围

- 使用 `.venv/bin/python -m pytest --collect-only -q` 作为 runtime identity 来源；当前仓库收集 **1155** 个 test node，比 Iteration 1 的 1148 增加本轮 7 个 P0 case。
- 以 55 个正式 coverage ID、领域名称、candidate/binder/transaction/query/visibility/system/artifact 语义扫描 `tests/`；保留 Iteration 1 的 22 个高信号模块并加入本轮直接领域模块，共 **23 个候选模块 / 512 个候选 node**。
- 候选池用于 Step 3 逐项核验，不等于 512 个 criterion 已覆盖；只接受能提供直接 G/W/T 证据的稳定 pytest identity。
- 当前显式优先级共 **84** 个：P0=66、P1=18。新增模块以 `pytestmark = pytest.mark.p0` 标记 7/7；其余无 marker 的既有测试只能从其映射 criterion 继承优先级。

### 按测试层级分类

| TEA Level | Candidate nodes | 模块数 | 主要职责 |
|---|---:|---:|---|
| Unit | 217 | 8 | schema、candidate、mapping/artifact/fingerprint/fake runner 合同 |
| API（Backend Integration） | 204 | 12 | Python service、真实 Runtime/SaveManager、SQLite、temporary Save；本轮新增 7 个 CON/CRF case |
| E2E（Backend System） | 91 | 3 | CLI/MCP public shell 到 Kernel/SaveManager；不等同真实 Hermes journey |
| Component | 0 | 0 | 后端项目无浏览器组件层 |
| **合计** | **512** | **23** | 允许风险纵深，不允许用低层同名测试冒充完整 public journey |

### Iteration 2 新增稳定身份

| ID | Stable pytest node ID | File:line | Level | Runtime state |
|---|---|---|---|---|
| CON-01 | `tests/test_current_native_consumption_craft_deltas.py::test_consumption_commit_decrements_exact_quantity_and_writes_one_turn_event` | `tests/test_current_native_consumption_craft_deltas.py:39` | API / Backend Integration | active；PASS evidence |
| CON-02 | `tests/test_current_native_consumption_craft_deltas.py::test_consumption_changes_only_quantity_and_preserves_all_item_metadata` | `tests/test_current_native_consumption_craft_deltas.py:64` | API / Backend Integration | active；PASS evidence |
| CON-03 | `tests/test_current_native_consumption_craft_deltas.py::test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation[insufficient]` | `tests/test_current_native_consumption_craft_deltas.py:91` | API / Backend Integration | active；FAIL evidence |
| CON-03 | `tests/test_current_native_consumption_craft_deltas.py::test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation[stale-before]` | `tests/test_current_native_consumption_craft_deltas.py:91` | API / Backend Integration | active；FAIL evidence |
| CON-03 | `tests/test_current_native_consumption_craft_deltas.py::test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation[item-mismatch]` | `tests/test_current_native_consumption_craft_deltas.py:91` | API / Backend Integration | active；FAIL evidence |
| CON-03 | `tests/test_current_native_consumption_craft_deltas.py::test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation[malformed-quantity]` | `tests/test_current_native_consumption_craft_deltas.py:91` | API / Backend Integration | active；FAIL evidence |
| CRF-01 | `tests/test_current_native_consumption_craft_deltas.py::test_gm_resolved_craft_delta_consumes_material_and_upserts_output_exactly` | `tests/test_current_native_consumption_craft_deltas.py:120` | API / Backend Integration | active；PASS evidence |

### 执行状态与条件跳过

- 新增 7 个 identity 均为 `pending=false`、`fixme=false`，没有 xfail；Automation 记录的实际环境中 current-native packages 存在，故运行时 `skipped=0`。
- `current_native_temp_save` 在 current-native Campaign 或 Save 不存在时会显式 `pytest.skip("requires current native Campaign and Save packages")`。这是可发现的环境 blocker，不得把 0 执行误报为 P0 green；本轮证据没有触发它。
- 其余候选沿用 Iteration 1 的稳定 identity；本轮只新增上述 7 个，不改写旧测试标题或层级。

### Coverage Heuristics Inventory

- **HTTP/API endpoint：** N/A。无 OpenAPI/HTTP route；这里的 API 指 Python public service/SQLite Integration。新增测试直接调用真实 `GMRuntime.commit_turn`，不是 mock 或测试专用 production API。
- **Authentication/authorization：** 没有 login/token 产品需求；player/maintenance、candidate authority、confirmation session 与 hidden visibility 的负例候选仍存在。新增测试不授予 AI authority，使用 human-confirmed structured proposal。
- **Error path：** 已发现 `CON-03` 四个直接负例，覆盖 insufficient、stale before、item/upsert mismatch、negative quantity；它们当前执行为 FAIL。具体 coverage/requirement status 留给 Step 3，不能因存在测试就宣称需求满足。
- **UI journey/state：** N/A。项目为 backend/CLI/MCP；真实 Hermes journey 缺口由 SYS criterion 表达，不映射成浏览器 UI 缺口。

### Step 2 结论

- 测试发现、层级分类、优先级、稳定 identity、执行状态和 heuristics inventory 已完成。
- 下一步按 `step-03-map-criteria.md` 将 55 个 criterion 与直接测试双向映射，并明确拆分 coverage status 与 observed execution result。

## Iteration 2 — Step 3：需求—测试双向映射

### 判定口径

- `FULL / PARTIAL / UNIT-ONLY / INTEGRATION-ONLY / NONE` 描述**测试覆盖存在性与层级充分性**；`PASS / FAIL / N/A` 描述本轮直接执行证据。可靠红灯仍是直接覆盖，不能因未通过退回 `NONE`。
- 上方 Iteration 1 Step 3 已为原 51 个有测试或缺口的 criterion 保存完整 stable identity（title、file、line、level、G/W/T 与 gap）。本轮对这些 identity 逐项复核后保持不变；repository full pytest 证明除新增 `CON-03` 四参数外，所有既有 collected test 均通过。
- 新增 7 个 stable identity 在本节完整记录；它们与旧 identity 无重复。CI/static 行继续使用执行 artifact，不伪造 pytest node。

### Coverage Summary

| Priority | Total | FULL | Coverage | Coverage threshold | Result |
|---|---:|---:|---:|---:|---|
| P0 | 46 | 25 | 54.3% | 100% | FAIL |
| P1 | 9 | 2 | 22.2% | 95% | FAIL |
| P2 | 0 | 0 | N/A | N/A | N/A |
| P3 | 0 | 0 | N/A | N/A | N/A |
| **Total** | **55** | **27** | **49.1%** | — | **FAIL** |

**状态统计：** FULL=27、PARTIAL=18、UNIT-ONLY=4、INTEGRATION-ONLY=3、NONE=3。

### 55 项完整状态矩阵

`Mapped execution` 表示直接测试/门禁的已观测运行结果，不把 PARTIAL 的绿灯解释为 criterion 完成。

| Family | ID | Pri | Coverage | Mapped execution | Direct evidence / remaining gap |
|---|---|---|---|---|---|
| Migration | MIG-01 | P0 | PARTIAL | PASS | 原 stable identity 不变；仍缺 trusted frozen digest baseline |
| Migration | MIG-02 | P0 | PARTIAL | PASS | 原 stable identity 不变；仍缺 1,016 行 owner 核验与最终 mapping artifact |
| Migration | MIG-03 | P0 | PARTIAL | PASS | 原 stable identity 不变；仍缺 382 ISSUE 真实复现/归因证明 |
| Skill | SKL-01 | P0 | UNIT-ONLY | PASS | fake runner/contract；无真实 Hermes+flash 金标 |
| Skill | SKL-02 | P1 | NONE | N/A | 八领域 action/slot 真实 Skill 金标未实现 |
| Skill | SKL-03 | P1 | UNIT-ONLY | PASS | 仅 Kernel clarify/composite；无 Skill semantic evidence |
| Skill | SKL-04 | P0 | INTEGRATION-ONLY | PASS | Kernel 越权/hidden guard；无真实 prompt-injection Skill eval |
| Skill | SKL-05 | P1 | UNIT-ONLY | PASS | manifest/INFRA_ERROR 合同；无 30×3 provider drift run |
| Candidate | CNT-01 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Candidate | CNT-02 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Candidate | CNT-03 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Candidate | CNT-04 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Binder | BND-01 | P1 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Binder | BND-02 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Binder | BND-03 | P0 | PARTIAL | PASS | 缺 cross-campaign ID 注入与 registry-version incompatibility 负例 |
| Transaction | TRN-01 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Transaction | TRN-02 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Transaction | TRN-03 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Transaction | TRN-04 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Transaction | TRN-05 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Query | QRY-01 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Query | QRY-02 | P0 | PARTIAL | PASS | 缺聚合数量/计数与 SQLite 的直接对照 |
| Query | QRY-03 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Query | QRY-04 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Intake | INT-01 | P1 | NONE | N/A | 无合法 intake confirm 后 exact diff 测试 |
| Intake | INT-02 | P0 | PARTIAL | PASS | 缺 malformed/bad intake delta 的 current transaction no-mutation 回归 |
| Consumption | CON-01 | P0 | **FULL** | **PASS** | 新增直接 Integration exact quantity / turn / event / unrelated inventory 证据 |
| Consumption | CON-02 | P0 | **FULL** | **PASS** | 新增直接 Integration metadata deep-compare 证据 |
| Consumption | CON-03 | P0 | **FULL** | **FAIL** | 新增四路直接负例；产品未 pre-write reject，no-mutation Then 未到达 |
| Combat | CMB-01 | P0 | PARTIAL | PASS | 缺 pending→confirm 后 ammo exact diff / event uniqueness |
| Combat | CMB-02 | P0 | PARTIAL | PASS | 缺 retired/unreliable ammo 与完整 transaction no-mutation |
| Craft | CRF-01 | P0 | **FULL** | **PASS** | 新增 GM-resolved exact material/output/inventory/turn/event 证据 |
| Craft | CRF-02 | P0 | PARTIAL | PASS | 缺 project/progress commit 与 replay no-duplicate output |
| Craft | CRF-03 | P0 | PARTIAL | PASS | 缺错误地点与 pending/confirm no-mutation |
| Explore | EXP-01 | P1 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Explore | EXP-02 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Explore | EXP-03 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Rest | RST-01 | P0 | PARTIAL | PASS | 缺 recovery state 与 confirm 后实际持久化 |
| Rest | RST-02 | P1 | PARTIAL | PASS | 缺非法/不安全休息 no-mutation 负例 |
| Social | SOC-01 | P0 | PARTIAL | PASS | 缺 relationship/event confirm exact diff |
| Social | SOC-02 | P0 | PARTIAL | PASS | remote/unknown/retired/hidden 矩阵与 no-mutation 不完整 |
| Travel | TRV-01 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Travel | TRV-02 | P0 | PARTIAL | PASS | 缺 same-place / retired location transaction no-mutation |
| Environment | ENV-01 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Environment | ENV-02 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Environment | ENV-03 | P0 | FULL | PASS | 原 stable identity / GWT 继续成立 |
| Environment | ENV-04 | P0 | PARTIAL | PASS | synthetic guard 已绿；无 actual dated formal/source fingerprints |
| System | SYS-01 | P0 | UNIT-ONLY | PASS | injected fake adapter；无真实 Hermes+flash query trace |
| System | SYS-02 | P1 | NONE | N/A | 八领域真实 Hermes successful journey 未实现 |
| System | SYS-03 | P0 | INTEGRATION-ONLY | PASS | Kernel/MCP lower layer；无真实 Hermes hidden/clarify transcript |
| System | SYS-04 | P0 | INTEGRATION-ONLY | PASS | MCP/SaveManager lower layer；无真实 Hermes confirmation transcript |
| Artifact | ART-01 | P0 | PARTIAL | PASS | 合同测试已绿；无 actual complete dated run artifact |
| Artifact | ART-02 | P1 | PARTIAL | PASS | 合同测试已绿；无真实失败运行记录内容质量核验 |
| Static | STA-01 | P0 | FULL | PASS | Campaign validate/test、docs、py_compile、Ruff、diff check 全绿 |
| Static | STA-02 | P0 | FULL | **FAIL** | repository full pytest 已完整执行：1151 pass / 4 fail；仅 CON-03 |

### 新增正向映射：criterion → stable tests

| Criterion | Stable identity / file:line / level | G/W/T evidence | Execution |
|---|---|---|---|
| CON-01 | `tests/test_current_native_consumption_craft_deltas.py::test_consumption_commit_decrements_exact_quantity_and_writes_one_turn_event` — `:39`，API/Integration | G=temp Save + human-confirmed structured consumption；W=真实 `commit_turn`；T=0.5 精确扣减、1 turn/1 event、无关库存相同 | PASS |
| CON-02 | `tests/test_current_native_consumption_craft_deltas.py::test_consumption_changes_only_quantity_and_preserves_all_item_metadata` — `:64`，API/Integration | G=目标完整 metadata 快照；W=仅 quantity decrement；T=除 quantity 外的 canonical item/entity snapshot 深比较相同 | PASS |
| CON-03 | `tests/test_current_native_consumption_craft_deltas.py::test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation[insufficient]` — `:91`，API/Integration | G=consumed > live balance；W=真实 commit；T=预期 pre-write reject + DB/event/inventory no-mutation | FAIL：DID NOT RAISE |
| CON-03 | 同一参数测试 `[stale-before]` — `:91`，API/Integration | G=stale before_quantity；W=真实 commit；T=预期 pre-write reject + no-mutation | FAIL：DID NOT RAISE |
| CON-03 | 同一参数测试 `[item-mismatch]` — `:91`，API/Integration | G=payload item 与唯一 upsert 不一致；W=真实 commit；T=预期 pre-write reject + no-mutation | FAIL：DID NOT RAISE |
| CON-03 | 同一参数测试 `[malformed-quantity]` — `:91`，API/Integration | G=negative consumed_quantity；W=真实 commit；T=预期 pre-write reject + no-mutation | FAIL：DID NOT RAISE |
| CRF-01 | `tests/test_current_native_consumption_craft_deltas.py::test_gm_resolved_craft_delta_consumes_material_and_upserts_output_exactly` — `:120`，API/Integration | G=matching recipe + human-confirmed GM-resolved delta；W=真实 commit；T=材料精确扣减、产出 exact upsert、1 turn/1 event、无额外 inventory diff | PASS |

### 新增反向映射：stable test → criterion

| Stable test definition / parameters | Criterion | Justification |
|---|---|---|
| `test_consumption_commit_decrements_exact_quantity_and_writes_one_turn_event` | CON-01 | 唯一职责为合法消耗的数量、turn/event 与 unrelated-state exact diff |
| `test_consumption_changes_only_quantity_and_preserves_all_item_metadata` | CON-02 | 唯一职责为 quantity 之外的 metadata preservation |
| `test_invalid_consumption_is_rejected_before_commit_without_db_or_event_mutation` 四参数 | CON-03 | 四个 distinct failure signature 共同覆盖 malformed/stale/insufficient/mismatch pre-write guard |
| `test_gm_resolved_craft_delta_consumes_material_and_upserts_output_exactly` | CRF-01 | 唯一职责为 GM-resolved craft input/output exact transaction |

### Coverage Logic Validation

- **P0/P1 是否都有 coverage：** 否。P0 已无 `NONE`，但仍有 16 个 PARTIAL、5 个 UNIT/INTEGRATION-only 层级不足项，且 `CON-03`、`STA-02` 直接执行失败；P1 仍有 SKL-02、INT-01、SYS-02 三个 NONE。
- **错误路径：** CON-03 不再是 happy-path-only；四个关键负例都有直接 Integration identity，但均红灯，故覆盖完整不代表需求满足。
- **Endpoint heuristic：** HTTP/OpenAPI N/A；Python commit boundary 被直接覆盖。
- **Authority/authz：** CNT/BND/TRN/QRY 仍包含 denied/invalid path；新增测试使用 human-confirmed proposal，没有向 external/internal AI 授权事实或 commit authority。
- **UI heuristic：** N/A；SYS-02/03/04 继续表达真实 Hermes public journey 缺口。
- **重复覆盖：** 新增 7 个 identity 与旧 86 个 active identity 无重复；它们只补 CON/CRF 领域 exact transaction，不复制 Skill、binder 或 system journey。

### Step 3 结论

- 55 个正式 criterion 已全部重新映射。FULL 从 23 提升至 27；P0 FULL 从 21/46 提升至 25/46；NONE 从 7 降至 3。
- coverage 改善不解除 gate：`CON-03` 四路产品 FAIL 和 `STA-02` full-suite FAIL 已显式保留。
- 下一步按 `step-04-analyze-gaps.md` 对覆盖缺口、层级缺口、执行失败与启发式盲点进行 Phase 1 gap analysis。

## Iteration 2 — Step 4：Phase 1 Gap Analysis

### 执行模式与三路独立复核

- 用户本轮未指定 execution mode；config 为 `tea_execution_mode: auto`、capability probe 开启，runtime 支持 agent-team，故解析为 **`auto → agent-team`**。
- 依照 Step 4 的 dependency-safe orchestration，三路只读 worker 分别复核：A=gap classification，B=coverage heuristics，C=statistics/deduplication；recommendation synthesis 与 JSON merge 由主流程在三路完成后执行。
- 三路一致确认：55 criteria；FULL=27、PARTIAL=18、UNIT-ONLY=4、INTEGRATION-ONLY=3、NONE=3；P0 FULL=25/46，P1 FULL=2/9；没有 worker 作 Gate Decision 或修改仓库。

### Gap Classification

**Critical NONE（P0）：0。** Iteration 1 的 CON-01/02/03、CRF-01 均已建立直接 Integration coverage。

**High NONE（P1，3）：**

- `SKL-02`：八领域 action/slot 真实 Skill 金标未实现。
- `INT-01`：合法 intake 经 confirm 后 exact entity/item/event diff 未实现。
- `SYS-02`：真实 Hermes 八领域成功 journey 未实现。

**PARTIAL（18）：**

- P0（16）：MIG-01、MIG-02、MIG-03、BND-03、QRY-02、INT-02、CMB-01、CMB-02、CRF-02、CRF-03、RST-01、SOC-01、SOC-02、TRV-02、ENV-04、ART-01。
- P1（2）：RST-02、ART-02。

**Lower-level only（7）：**

- UNIT-ONLY（4）：SKL-01、SKL-03、SKL-05、SYS-01。
- INTEGRATION-ONLY（3）：SKL-04、SYS-03、SYS-04。

**覆盖已建立但执行失败（P0）：**

- `CON-03`：FULL coverage / FAIL execution；四个 direct Integration negative case 均 `DID NOT RAISE ValueError`。
- `STA-02`：FULL coverage / FAIL execution；repository full pytest 的四个失败全部由 CON-03 派生，不是第二个独立产品根因。

因此 P0 虽已无 NONE，仍有 21 个覆盖充分性缺口（16 PARTIAL + 2 UNIT-ONLY + 3 INTEGRATION-ONLY），并存在一个直接 P0 产品行为根因。

### Coverage Heuristics

- **HTTP endpoint：0 / N/A。** 项目没有 HTTP/OpenAPI surface；但 HTTP N/A 不能推导为 public boundary 完整。
- **Authority negative-path gaps（5）：** BND-03、SKL-04、SYS-01、SYS-03、SYS-04；分别缺 cross-campaign/registry 对抗注入、真实 Skill 越权语义、真实 provider no-authority trace 及 Hermes hidden/confirm 状态链。
- **Error-path incomplete（7）：** INT-02、CMB-02、CRF-02、CRF-03、RST-02、SOC-02、TRV-02。CON-03 不再是 happy-path-only，而是“负例已覆盖但产品失败”；QRY-02 是 correctness aggregate gap，不错误归类为 auth/error gap。
- **Browser UI journey/state：0 / N/A。** 没有页面/form/loading/empty oracle；但 CLI/MCP/Hermes 是有状态玩家 public surface，SYS-01/02/03/04 仍缺真实 journey。
- **Kernel/public 分层：** 本轮 human-confirmed structured proposal 直达 Kernel，足以证明 CON/CRF exact-delta criterion；它不证明 external candidate→binder/resolver→pending→confirm，后者继续回链 SYS-02/04。

### Deduplicated Test Inventory

| Level | Active collected identities | Criteria with this level |
|---|---:|---:|
| Unit | 40 | 17 |
| API / Backend Integration | 50 | 36 |
| E2E / Backend System | 3 | 3 |
| Component / Other | 0 | 0 |
| **Total** | **93** | 可跨层重复 criterion |

- 93 个唯一 collected identity 分布在 25 个文件；定义级为 80，参数化 expansion 为 13。
- runtime skipped=0、pending=0、fixme=0；active PASS=89、active FAIL=4。CON-03 红灯属于 active test，不计 blocker status。
- `current_native_temp_save` 在 current-native packages 缺失时会条件 skip，但本轮实际环境未触发；后续 gate 必须防止 0 执行假绿。

### Recommendations

1. **URGENT：** 为 `CON-03` 创建独立 BMAD production fix Story，校验 live quantity、before/consumed/after 算术、余额非负、payload item 与唯一 upsert 对齐，并提供稳定 error type/code/stage；修复后重跑四参数及 STA-02 full suite。
2. **HIGH：** 补 `SKL-02`、`INT-01`、`SYS-02` 三个 P1 NONE。
3. **HIGH：** 补 BND-03、SKL-04、SYS-01、SYS-03、SYS-04 的 authority/public journey 负例与真实 external/Hermes trace。
4. **HIGH：** 完成 18 个 PARTIAL，优先 owner 归因、领域 no-mutation、跨 Campaign 对抗绑定、actual formal fingerprints 与 dated artifact。
5. **MEDIUM：** 补 QRY-02 聚合数量与 SQLite 直接对照，并在规划时复核 RST-02 的 no-mutation priority。
6. **MEDIUM：** 仅在测试/fixture 有实质 diff 后重跑 Test Review；当前 92/100 审查继续有效。

### Phase 1 Machine Artifact

- **Path：** `/tmp/tea-trace-coverage-matrix-2026-07-15T09-53-06Z.json`
- **Validation：** JSON 有效；`phase=PHASE_1_COMPLETE`；55 unique requirements；27 FULL / 18 PARTIAL / 4 UNIT-ONLY / 3 INTEGRATION-ONLY / 3 NONE；93 unique collected identities；`gate_decision_made=false`。
- **Execution evidence：** CON-03 与 STA-02 以 FULL coverage + FAIL execution 单列；没有降为 NONE，也没有伪装为 PASS。

### Phase 1 Summary

- Total Requirements：55
- Fully Covered：27（49.1%，workflow safePct=49%）
- Partially Covered：18
- Lower-level only：7
- Uncovered：3
- P0：25/46 FULL（54.3%，safePct=54%）
- P1：2/9 FULL（22.2%，safePct=22%）
- Critical NONE：0
- High NONE：3
- Covered but execution failed：CON-03、STA-02（同一根因链）
- Recommendations：6

Phase 1 已完成；本步骤**未作 Gate Decision**。下一步严格读取 `step-05-gate-decision.md`，使用上述同一 temp matrix 进入 Phase 2。

## Iteration 2 — Step 5：Phase 2 Gate Decision

### Collection 与评估资格

- 从 frontmatter 的 `tempCoverageMatrixPath` 读取 `/tmp/tea-trace-coverage-matrix-2026-07-15T09-53-06Z.json`；没有重建或重算 Phase 1。
- matrix `phase=PHASE_1_COMPLETE`；`collection_mode=agent-team`、`allow_gate=true`，未提供 restricted/waived 状态，因此 collection status 解析为 **COLLECTED**。
- `gateEligible=true`；Oracle 为 high-confidence formal requirements，93 个 active collected identity，置信度不降级。

### 🚨 Gate Decision：FAIL

**确定性判定：** P0 FULL coverage 为 54%（25/46），低于必须达到的 100%，首先命中 FAIL 规则。总体 FULL coverage 49% 低于 80%，P1 FULL coverage 22% 也低于最低 80%。

此外，coverage threshold 之外还存在直接执行阻断：`CON-03` 四个 P0 negative case 均失败，导致 `STA-02` repository full pytest 失败。两者是同一根因链，不能因 P0 NONE 已清零而忽略。

### Gate Criteria

| Metric | Actual | Requirement | Status |
|---|---:|---:|---|
| P0 FULL coverage | 54%（25/46；exact 54.3%） | 100% | NOT_MET |
| P1 FULL coverage | 22%（2/9；exact 22.2%） | PASS target 90%，minimum 80% | NOT_MET |
| Overall FULL coverage | 49%（27/55；exact 49.1%） | minimum 80% | NOT_MET |
| P0 direct execution | 3 pass / 4 fail（本轮 focused） | 100% pass | NOT_MET |
| Repository full pytest | 1151 pass / 4 fail + 10331 subtests | 100% pass | NOT_MET |

### Open Risk Summary

- P0 `NONE`：0；这表示四个旧 Critical NONE 已有直接测试，不表示 P0 已满足。
- P0 coverage sufficiency gaps：21（16 PARTIAL + 2 UNIT-ONLY + 3 INTEGRATION-ONLY）。
- P1 `NONE`：3（SKL-02、INT-01、SYS-02）。
- Covered but execution failed：CON-03、STA-02；独立产品根因是 CON-03 pre-write semantic guard 缺失。
- 无 stakeholder waiver；hidden、AI authority、formal/source 数据与 transaction integrity 仍不可 waiver。

### Required Next Actions

1. 进入独立 BMAD production fix Story 修复 `CON-03`：live quantity、before/consumed/after 算术、余额非负、payload item/upsert 对齐、稳定 error type/code/stage。
2. 从修复后的 clean diff 重跑 CON-03 四参数、CON-01/02/CRF-01 成功对照、受影响 adjacent regression、Campaign/static gates 与 repository full pytest；禁止 xfail/skip/放宽 oracle。
3. 修复及测试 fixture 有实质 diff 后再次 Test Review，再运行 Trace 更新 execution 与 gate。
4. 后续独立补齐 P1 NONE、21 个 P0 sufficiency gap 及真实 external/Hermes public journeys。

### Machine-readable Outputs

- `_bmad-output/test-artifacts/e2e-trace-summary.json`
- `_bmad-output/test-artifacts/gate-decision.json`
- Phase 1 source：`/tmp/tea-trace-coverage-matrix-2026-07-15T09-53-06Z.json`

两份 JSON 已验证可解析，均记录 `gate_status=FAIL`、P0=54%、P1=22%、overall=49%，并保留 CON-03/STA-02 execution failure 链。

🚫 **GATE: FAIL — 当前模拟用户测试重基线不得视为发布就绪；必须先修复 CON-03，并从修复后的最终 diff 重新通过 required gates。**

---

## Story 1.9 Post-fix Execution Addendum（2026-07-16）

历史 Iteration 2 映射与 Gate Decision 保留不变；本节只更新 Story 1.9 完成后的 execution state。

| Criterion | Coverage | Final execution | Evidence |
|---|---|---|---|
| CON-01 | FULL | PASS | 合法结构化消耗精确扣量，只新增 1 turn / 1 event，无关库存不变 |
| CON-02 | FULL | PASS | quantity 是唯一业务变化，entity/item metadata 与 aliases exact preservation |
| CON-03 | FULL | **PASS** | 6 个 current-native Runtime 负例 + resolver 边界矩阵 + no-mutation + SaveManager 失败确认恢复 |
| CRF-01 | FULL | PASS | craft 材料扣减与 output upsert exact inventory diff |
| STA-02 | FULL | **PASS** | repository full pytest：1223 passed + 10331 subtests passed |

最终执行摘要：

- focused：75 passed / 0 skipped；clean-checkout 最小闭包：75 passed / 0 skipped。
- adjacent：292 passed + 160 subtests passed。
- Campaign：`v1_minimal_adventure` 与 `small_cn_campaign` 的 validate/test 均 PASS。
- docs/static：203 Markdown files、py_compile、full Ruff、`git diff --check` 均 PASS。
- full suite：1223 passed + 10331 subtests passed。

Coverage 统计不因本次执行修复而伪造提升：P0 FULL 仍为 25/46，总体 FULL 仍为 27/55，P1 NONE 仍为 3。因此最新 Gate 继续为 **FAIL**，但 `covered_but_execution_failed` 已清空；原 CON-03/STA-02 不再是开放执行阻断。

机器可读证据：`_bmad-output/test-artifacts/automation-validation-story-1-9.json`、`gate-decision.json`、`e2e-trace-summary.json`。
