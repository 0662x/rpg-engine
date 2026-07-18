# Story 6.8 Validation Report

生成日期：2026-07-18

## 结论

**PASS — ready-for-dev**

- Critical misses：4，3项范围内修法与1项用户决策均已吸收。
- Decision-needed：0（原1项已于2026-07-19选择方案2）。
- 明确增强：5，已全部写回Story正文。
- 剩余 blocker：0。

Story 的provider fixture、真实stdio、temporary-data和跨仓ownership方向正确；用户已授权最小canonical `session_id` audit摘要patch，完整Story 6.7重构仍保持独立，可以进入`[DS] Dev Story`。

## Checklist Results

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| Story / Epic / sprint key | PASS | Story key 与 Epic 6 / sprint-status 的 `6-8-rpg-engine-compatibility-fixture-for-hermes-stdio-e2e` 一致；用户显式选择 6.8。 |
| 用户价值与 AC 完整性 | PARTIAL | 覆盖真实 stdio、manifest/refresh、turn/confirm、audit、temporary writes 与 CI ownership；safe-audit 的 session 边界存在 owner 冲突。 |
| 架构与事实权威 | PASS | fixture 只编排现有 MCP CLI；SQLite、Kernel、玩家确认与 SaveManager authority 不变。 |
| 真实 transport 可行性 | PASS | 真实 `StdioServerParameters -> stdio_client -> ClientSession` 原型已 initialize/list/call；不是 FakeFastMCP/in-memory。 |
| Active Save bootstrap | ENHANCE | `player_turn` 读取 registry active Save，单独 `--default-save` 不足；fixture 必须预建 temporary registry active Save或真实调用 `start_or_continue`。 |
| Platform identity parity | ENHANCE | MCP `player_confirm` 只接受 `session_id`；valid scripted turn 若传 platform/session_key会确认失败。valid path须省略身份参数，hash canary只放 stale request。 |
| Scripted-model contract | CRITICAL | 仅声明 YAML 文件不够；必须定义版本化、可执行 schema、变量捕获/插值、whole-candidate regeneration与bounded transcript projection。 |
| Safe audit / Story 6.7 | PASS | 用户选择最小canonical `session_id` hash/摘要patch；Story 6.7继续独占完整normalized route reconstruction与其余metadata。 |
| No-network proof | CRITICAL | 仅删除常见key/env不能证明零网络。应以test-owned subprocess socket deny oracle记录并拒绝任意连接尝试；不改变production API。不得通过改写系统 `HOME` 规避。 |
| Temporary/protected fingerprints | ENHANCE | CI可能没有formal current packages；必须对必有source fixture强制fingerprint，对显式配置或存在的formal Campaign/Save/registry/SQLite做portable optional fingerprint，并始终证明temp root不别名正式路径。 |
| MCP result/timeout lifecycle | ENHANCE | 必须精确定义 `CallToolResult` TextContent JSON解码、tool error处理、per-call timeout、context-manager teardown与stderr capture。 |
| Reinvention prevention | PASS | 禁止修改Hermes、复制业务规则、新增测试专用production API；默认不改MCP/SaveManager/依赖/migration。 |
| Required final gates | PASS | Focused、adjacent、Campaign、Markdown、py_compile、Ruff、diff-check与repository full pytest均已锁定。 |

## Decision Resolution

现有真实 wire 原型证明：`player_confirm(session_id)` 成功后，temporary audit JSONL 的 request 会保存原始 pending `session_id`。这与 Story 6.7 的“candidate/player text/session identity raw values omitted or hashed”直接重叠。

用户于2026-07-19选择方案2：Story 6.8在canonical audit sanitizer中仅把confirmation `session_id`变为批准hash/摘要并补回归；Story 6.7仍负责完整normalized route reconstruction summary。该决策解除HALT，不授权任何其他6.7范围。

## 已确认、待自动应用的明确增强

1. 为 scripted contract 增加 schema version、固定 step/event vocabulary、capture/reference规则、live contract整体重建证明与volatile字段归一化后的bounded hooks。
2. 由 fixture 在temporary root预建registry active Save；server固定`--registry-active`，不得依赖无效的`--default-save`假设。
3. valid player_turn不传platform/session_key；stale request使用独立session-key canary验证hash且无pending，避免MCP confirm identity mismatch。
4. 用test-owned subprocess `sitecustomize`/socket deny oracle拒绝并计数任意网络连接；AI helpers全部off且不读取API key。遵守仓库规则，不改写系统`HOME`。
5. protected fingerprint采用必有source强制验证 + 可配置/存在formal path验证，覆盖registry、SQLite、events/player data且保持CI可移植。

## Source Review

- `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Stories 6.7、6.8
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md` — D8、Story顺序与H1–H4 ownership
- `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-17.md` — scope guard、Hermes handoff与dirty worktree归属
- `docs/project-context.md`、`docs/architecture.md`、`docs/mcp-contracts.md`、`docs/ai-intent-chain.md`
- `docs/save-and-campaign-packages.md`、`docs/testing-and-quality-gates.md`
- `rpg_engine/mcp_adapter.py`、`rpg_engine/save_manager.py`、`rpg_engine/intent_manifest.py`
- `tests/test_mcp_adapter.py`、`tests/test_mcp_transcript.py`、`tests/helpers.py`
- MCP Python SDK official stdio client/server examples

## Verification

- Story 文档结构、key/status：PASS
- `sprint-status.yaml` YAML parse与Story 6.8 `ready-for-dev`：PASS
- `git diff --check`（Story artifact + sprint status）：PASS
- 真实 stdio initialize/list/call：PASS
- stale contract typed mismatch：PASS
- live external candidate `player_turn` ready：PASS
- 带platform/session identity的MCP confirm：FAIL（现有工具只转发session_id；已转成Story脚本约束，不作为production patch）
- raw confirmation session_id audit privacy：RED已复现；用户已授权最小patch，行为绿灯属于Dev Story。

## BMAD Provenance

- Menu：`[VS] Validate Story`
- Skill：`.agents/skills/bmad-create-story/SKILL.md`（完整读取）
- Checklist：`.agents/skills/bmad-create-story/checklist.md`（完整读取并执行）
- Customization resolver：prepend/append/on_complete为空；persistent fact为 `file:{project-root}/**/project-context.md`
- Config：`_bmad/bmm/config.yaml`
- Persistent context：`docs/project-context.md`
- Fresh-context validator：独立只读复核已完成；识别4项Critical/必须补强，明确增强已写回，唯一scope/AC decision已由用户选择方案2。
