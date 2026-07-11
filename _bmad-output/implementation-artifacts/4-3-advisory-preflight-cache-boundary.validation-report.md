# Story 4.3 验证报告

Story: `4-3-advisory-preflight-cache-boundary`

Validation-time status: ready-for-dev（实现前快照，不代表 review/done readiness）

## Checklist 结果

已按 `.agents/skills/bmad-create-story/checklist.md` 重新检查 Story、Epic 4、PRD FR-4/FR-6、两份 Architecture Spine、execution-chain verification gates、previous Story 4.2、canonical intent/CLI/MCP/testing 文档、现有 preflight/runtime/router/platform 代码、相关测试与最近 5 个 commit。

Fresh validator 初始发现 Critical 2、Enhancement 4、Optimization 1、decision-needed 0；全部属于无歧义、范围内的 artifact 完整性改进，已直接写入 Story。应用后复核结论：未处理 Critical 0、未处理 Enhancement 0、未处理 Optimization 0、decision-needed 0。

## 关键缺失

- 无。Story 完整保留 candidate-bound 的 text/candidate/save/turn/context/helper/schema/task identity、TTL 与 single-use 要求。
- 无。Story 同时要求 Runtime 上层与 cache service 最内层双重保证 `message_only` 不携带 external candidate，并要求 platform/session/message/source-text identity 完整。
- 无。Story 明确 cache hit 只替代 live internal review，arbiter/binder/resolver/preview/validation/pending/confirm/commit guard 不得跳过。
- 无。Story 禁止新依赖、schema/migration、public preflight surface、coordinator、mode-matrix 改写、正式 Save/Campaign/registry 修改。

## 已应用增强

- 将原始三组 AC 展开成可测试的 identity mismatch matrix、SQLite CAS/single-use、late-ready/non-hit 与 public evidence/redaction contract。
- 识别现有最明确实现缺口：`message_only` 上层 prewarm 已检查 identity，但 `create_pending_intent_preflight()` 尚未在最内层强制非空 platform/session/message；Story 指定从 RED test 修复该 service boundary。
- 识别 helper identity 仅依赖拼接 `model_version` 的碰撞风险；Story 要求复用现有数据库列逐字段核验 provider/model/backend/fallback，无需 migration。
- 补充唯一 preflight ID、NFKC/trim source hash、伪造 declared hash、失败零写入与双连接 single-use characterization。
- 明确沿用既有 300 秒 TTL，不在本 Story 决定新产品值，也不增加 cleanup daemon 或 distributed cache。
- 加入 Story 4.1 mode matrix 与 Story 4.2 enabled-timeout/background latency 回归，防止 cache reuse 偷换 route authority。
- 明确 primary/conditional/expected-no-change 文件集，避免为了测试扩大 Runtime、SaveManager、MCP/CLI 或 migration 范围。
- 将并发/race 测试限定为独立 SQLite connections 与 Event/barrier happens-before，避免固定毫秒 sleep 和 flaky required gate。
- 补齐 temporary Save、source Campaign/formal Save/registry fingerprint、surface inventory、Markdown links、Ruff、py_compile、diff check 与 full suite 要求。
- 将 BMAD provenance 与中文 artifact 标题补齐，并把 `tests/test_current_native_visibility.py` 纳入 adjacent gate。

## 范围与架构验证

- P0 规划证据完整：PRD FR-4/FR-6、Architecture AD-2/AD-8/AD-10、execution-chain AD-1/AD-2/AD-5、Epic 4 Story 4.3 与 verification gates 都明确支持本边界加固。
- 推荐实现复用 `create_pending_intent_preflight()`、`build_preflight_identity()`、SQLite conditional updates、`GMRuntime.preflight_intent()`、`AIIntentRouter.lookup_preflight()`、`ai_helper_result_from_preflight()` 与现有 platform prewarm/sidecar path。
- `data/game.sqlite` 仍是事实权威；cache 是 Save SQLite 中的敏感 advisory runtime state，但不能成为 gameplay fact、permission、proposal、confirmation 或 commit authority。
- 未发现必须扩大 P0 范围、增加依赖、改变 public API、修改 schema/migration 或引入主观方案选择的证据。

## 已发现并读取的输入

- `.agents/skills/bmad-create-story/SKILL.md`
- `.agents/skills/bmad-create-story/discover-inputs.md`
- `.agents/skills/bmad-create-story/checklist.md`
- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/specs/spec-rpg-engine-execution-chain-architecture/verification-gates.md`
- `_bmad-output/implementation-artifacts/4-2-ai-latency-policy-and-safe-degradation.md`
- `docs/project-context.md`
- `docs/governance/bmad-workflow.md`
- `docs/architecture.md`
- `docs/component-inventory.md`
- `docs/ai-intent-chain.md`
- `docs/cli-contracts.md`
- `docs/mcp-contracts.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/preflight_cache.py`
- `rpg_engine/runtime.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/platform_prewarm.py`
- `rpg_engine/resources/migrations/0006_intent_preflight_cache.sql`
- `rpg_engine/resources/migrations/0007_intent_preflight_identity_hardening.sql`
- `rpg_engine/resources/migrations/0008_intent_joiner_message_only.sql`
- `tests/test_preflight_cache.py`

## 验证说明

- Catalog 路由：`[VS] Validate Story`，`bmad-create-story:validate`。
- Skill package 未提供独立 validate step file；依其 validation 定义，重新运行 customization resolver、加载 persistent facts/config，并使用已完整读取的 `checklist.md` 执行 fresh validation。
- Customization resolver 成功：prepend/append 为空，persistent fact 为 `docs/project-context.md`，`on_complete` 为空。
- 未运行实现测试；本 gate 只验证 story readiness。Dev Story 必须从 RED characterization 开始。
- 未执行外部 Web research：本 Story 不新增/升级 library、framework、external API 或依赖，只复用 Python 3.11+ 标准库、SQLite 与现有实现。
- 未发现 decision-needed 或 skill-defined HALT condition。
