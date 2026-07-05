# Story 1.4: Save Fact Authority and Runtime State Boundary

Status: ready-for-dev

## 用户故事

作为引擎维护者，
我希望 Save Package facts、registry state、pending state、archives、caches 和 audit artifacts 拥有清晰分离的合同，
从而避免任何派生产物、workspace index 或缓存悄悄变成事实来源。

## 验收标准

1. 给定一个 Save Package，当事实权威被 inspect 或 validate 时，`data/game.sqlite` 被文档和测试确认为当前事实权威，SQLite `events` 表被确认为权威审计记录；`data/events.jsonl`、snapshots、cards、memory、projection reports 和 registry metadata 不得覆盖 SQLite 中的 current turn、entity、event、clock 或 meta 事实。
2. 给定 registry、pending files、projection_state、outbox、archive manifests、preflight cache、MCP audit logs、snapshots、cards 或 memory artifacts 存在，当 player 或 maintenance path 读取它们时，它们必须被当作 entry state、derived state、advisory state 或 evidence；它们可以报告健康状态、路由入口、待确认动作或修复证据，但不能让未提交或派生状态成为 gameplay facts。
3. 给定 workspace registry paths、SaveManager path fields、MCP/CLI save/campaign path parameters 或 archive member paths 包含绝对路径、`..`、反斜杠或 root escape 尝试，当验证运行时，路径必须被拒绝，且 registry、save、campaign、pending state 和 SQLite facts 都不被修改。
4. 给定 Save Package 的派生 artifacts 与 SQLite facts 不一致，例如 `events.jsonl` 缺少 SQLite event、snapshot meta 不匹配、cards/search/projection_state/outbox dirty/failed/stale，当 `save validate` 或等价 inspection 运行时，结果必须报告 drift/dirty/failed/stale，而不是把派生 artifact 解释成新的事实。
5. 给定 maintenance/admin surfaces 执行 save init、inspect、validate、patch、archive export/import 或 projection repair，当操作成功或失败时，它们必须保留 Campaign/Save 分层、路径边界、backup/manifest/checksum/projection evidence，并且不能绕过普通玩家的 `player_turn -> pending action -> player_confirm -> validation -> commit` 写入链。

## 任务 / 子任务

- [ ] 建立 Save fact authority 合同证据。 (AC: 1, 2)
  - [ ] 复用现有 `docs/save-and-campaign-packages.md`、`docs/data-models.md` 与 `inspect_save_package()` 语义；不要新增并行事实 registry 或新权威状态表。
  - [ ] 若当前 `save inspect`/`inspect_save_package()` 输出缺少稳定可测的角色说明，优先补一个小而明确的 contract/role 字段，列明 `data/game.sqlite`、SQLite `events`、`data/events.jsonl`、snapshots、cards、memory、registry、pending、preflight cache、archive 的职责。
  - [ ] 如果只需要测试和文档即可满足合同，不要扩大公共 API。
- [ ] 防止派生产物覆盖 SQLite facts。 (AC: 1, 2, 4)
  - [ ] 添加或强化测试：手动篡改 `data/events.jsonl`、`snapshots/current.json`、cards/search/projection_state/outbox，使其与 SQLite 不一致；断言 `save validate` 报告不一致，`save inspect` 的 current turn/location/time/entity counts 仍来自 SQLite。
  - [ ] 覆盖 registry 中陈旧或恶意的 save summary/current_turn metadata：`current_save(refresh=True)` 可以刷新 registry 摘要，但 registry 自身不能覆盖 Save SQLite facts。
  - [ ] 覆盖 pending action / pending clarification：pending state 不能被 query、inspect、validate 或 archive manifest 当成已经发生的事实。
- [ ] 强化路径边界与无副作用失败。 (AC: 3)
  - [ ] 覆盖 `SaveManager` 的 registry path、campaign/save/starter path、`save_path` 参数和 pending path helper：绝对路径、`..`、root escape 必须拒绝。
  - [ ] 覆盖 MCP/CLI save/campaign path 参数：被拒绝时不写 registry、不创建 save、不写 pending、不修改 SQLite。
  - [ ] 覆盖 archive import 成员路径：绝对路径、`..`、反斜杠、未列入 manifest、checksum/size mismatch 必须失败，且目标目录保持未替换或可恢复。
- [ ] 保持 maintenance/admin 写入不冒充玩家事实提交。 (AC: 2, 5)
  - [ ] 若触碰 `save_patch.py`，保留当前限制：patch 是 maintenance 操作，可以修正允许字段，但不能推进 `current_turn_id` 或注入 story progression 字段。
  - [ ] 若触碰 projection repair，保留 `ProjectionService` 的 evidence/health 语义：projection/outbox 修复不能改变已提交事实含义。
  - [ ] 若触碰 save init/export/import，保留 manifest、checksum、size、路径安全和 temp target 语义。
- [ ] 同步公开文档或 surface taxonomy，仅在公共合同实际改变时执行。 (AC: 1, 5)
  - [ ] 如果新增/修改 `save inspect` 字段，更新 `docs/save-and-campaign-packages.md`、`docs/data-models.md` 和 CLI/MCP 相关文档。
  - [ ] 如果新增 public/semi-public surface，更新 `rpg_engine/surface_inventory.py` 并补 `tests/test_surface_inventory.py`。

## 开发说明

### 来源上下文

- Epic 1 的目标是可信本地游玩闭环与入口权限。Story 1.4 负责把 Save facts、workspace/runtime state、projection/outbox、archive 和 audit/advisory artifacts 的权威边界写成可执行合同。来源：`_bmad-output/planning-artifacts/epics.md`。
- Story 1.4 原始验收标准要求：`data/game.sqlite` 是 current fact authority，SQLite `events` rows 是权威审计记录；registry、pending files、projection_state、outbox、archive manifests、preflight cache、MCP audit logs、snapshots、cards、memory 不能覆盖 SQLite facts；绝对路径、`..` 和 root escape 必须拒绝且无状态修改。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-14 要求 Save Package 保持长期本地 play 的 authoritative runtime state，并要求 current facts、events、pending actions、projections 和 metadata 职责分离。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Execution-chain Architecture AD-4 规定 SQLite commits 是 facts，projection/outbox 是可修复 evidence；AD-5 要求触碰 SaveManager、Runtime、validation、commit、projection 或 visibility 的 story 带最小有意义 boundary tests。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。
- Foundation Architecture AD-1 规定 Campaign Package 拥有作者内容，Save Package 拥有运行事实，Kernel 拥有机制；`.aigm/save-registry.json`、pending action/clarification、preflight cache、proposal queue 和 advisory/review artifacts 不是 gameplay facts。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Canonical docs 已声明硬边界：`data/game.sqlite` 是 Save Package 当前事实权威，`data/events.jsonl`、snapshots、cards、memory 是审计或投影产物，`.aigm/save-registry.json` 是玩家工作区索引。来源：`docs/save-and-campaign-packages.md`、`docs/data-models.md`。
- 项目长期上下文要求事实完整性优先，玩家确认和写入校验优先，MCP/CLI/platform sidecar 必须薄封装 kernel service。来源：`docs/project-context.md`。

### 当前实现状态

- `save_service.init_v1_save()` 创建 Save Package，写入 runtime `campaign.yaml`，将 runtime paths 固定为 `data/game.sqlite`、`data/events.jsonl`、`snapshots/current.md`、`snapshots/current.json` 和 `cards`，初始化 SQLite，并通过 `ProjectionService` 刷新 `events_jsonl`、`search`、`snapshots` 和 `cards`。来源：`rpg_engine/save_service.py` lines 49-103。
- `save_validation.inspect_save_package()` 当前检查 required files、SQLite table/migration/meta、projection_state、outbox、events JSONL、snapshot JSON、cards 和 search projection，并返回 `current_turn_id`、location/time meta、counts、errors/warnings。来源：`rpg_engine/save_validation.py` lines 51-107, 190-218, 220-310。
- `validate_events_jsonl()` 已按 SQLite `events` 做双向一致性检查：JSONL 事件必须存在于 SQLite，SQLite event 也必须出现在 JSONL。来源：`rpg_engine/save_validation.py` lines 220-248。
- `validate_snapshot_json()` 和 `validate_cards()` 已把 snapshot/card 当作 SQLite meta 和 entity rows 的投影一致性检查对象。来源：`rpg_engine/save_validation.py` lines 251-295。
- `SaveManager` 以 workspace root 为边界，默认 registry 是 `.aigm/save-registry.json`，pending action/clarification 是 `.aigm/pending-player-action.json` 与 `.aigm/pending-player-clarification.json`。路径 helpers 已拒绝 absolute path、`..` 和 root escape。来源：`rpg_engine/save_manager.py` lines 27-31, 49-52, 648-694, 867-904。
- `SaveManager.current_save(refresh=True)` 和 `require_save(refresh=True)` 会刷新 registry 中的 save record 摘要，但这应保持为 workspace metadata refresh，不能成为事实写入。来源：`rpg_engine/save_manager.py` lines 149-174 and 619-632。
- `ProjectionService` 与 `projections.py` 使用 `projection_state`、`outbox`、projection reports 和 artifacts 记录派生状态；reports 中 `dirty`、`failed`、`stale` 等字段描述 health，不改变事实含义。来源：`rpg_engine/projections.py` lines 16-24, 48-116, 131-179, 241-290；`rpg_engine/projection_service.py` lines 57-140 and 179-260。
- `save_archive.export_save()` 打包 core files、cards 和 memory；`import_save_archive()` 校验 manifest、文件清单、大小、总大小、SHA256，并使用 staging + atomic replace。`validate_archive_names()` 拒绝空名、反斜杠、绝对路径和 `..`。来源：`rpg_engine/save_archive.py` lines 23-35, 77-149, 181-198, 235-266。
- `save_patch.apply_save_patch()` 是 maintenance 操作：允许有限实体修正，先 backup，提交后刷新 search/snapshots/cards；现有测试证明它不推进 `current_turn_id`，并拒绝 `current_turn_id` 这类 protected gameplay field。来源：`rpg_engine/save_patch.py` lines 207-260；`tests/test_save_patch.py` lines 60-117。
- `AIGMMCPAdapter` 的 save/campaign tools 调用 SaveManager 或 runtime services，并用 `resolve_relative_under_root()` 约束 campaign/save path；MCP audit log 是调用证据，不是事实源。来源：`rpg_engine/mcp_adapter.py` lines 246-319, 1017-1055, 1064-1077。

### 前序故事情报

- Story 1.3 当前已创建为 `ready-for-dev`，但还未实现或提交。它会强化 `player_confirm -> validation -> commit` 半段；Story 1.4 不应假设 1.3 的代码变更已经存在，只能依赖当前代码和 Story 1.2 已完成事实。
- Story 1.3 的 story context 强调：pending action 是 runtime entry state，直到 `player_confirm()` 提交到 validated commit path 前都不是 accepted fact；不要暴露 raw delta、full TurnProposal、raw session/actor identity 或 AI private reasoning。
- Story 1.2 已完成并提交，基线 commit 为 `97aa92d39e4a6a6e375ef124b5fd3075c7e9f409`。它证明 `player_turn()` ready preview 不写 SQLite gameplay state，pending action 绑定 save/path/text/action/delta/proposal/session/TTL/platform/session/actor hashes，且 non-ready outcomes 不产生 committable pending action。
- 最近提交 `97aa92d` 还修正了 platform preflight trace identity 泄漏，确保 pending proposal 中保存 hash 而不是 raw `session_key`。1.4 的 cache/audit/pending 边界测试不能倒退这个行为。

### 架构合规要求

- 不要新增第二套事实权威。`data/game.sqlite` 和 SQLite `events` 仍是事实与审计权威；JSONL、projection_state、outbox、snapshots、cards、memory、registry、archive manifest、MCP audit、preflight cache 都只能是 evidence、derived/read model、entry state 或 advisory state。
- 不要把 registry refresh、projection repair、archive import 或 save patch 描述成普通玩家 gameplay commit。
- 不要让 `save inspect` 或 `save validate` 从 JSONL/snapshot/cards/registry 中反向“修正” SQLite facts。它们只能报告 drift 或通过显式 maintenance repair 重建派生产物。
- 不要直接写正式 current save package；所有写入测试必须复制 campaign/save 到临时目录。
- 不要改变 player-safe 写入链：普通 gameplay facts 仍必须通过 `player_turn -> pending action -> player_confirm -> validation -> commit`。
- 不要扩大默认 MCP `player` profile 的低层能力，也不要让 CLI/MCP/platform adapter 复制 Save/validation/commit 业务逻辑。
- 如果 public result shape 改动，保持结构化 `ok`、`status`、`warnings`、`errors` 和 source/evidence 字段，不暴露 hidden facts 或敏感 raw platform/preflight identity。

### 相关文件

- `rpg_engine/save_validation.py`：Save Package inspect/validate 主入口；最可能需要补 fact-authority/derived-state assertions 或 result fields。
- `rpg_engine/save_service.py`：Save init runtime path、SQLite 初始化与初始 projection refresh。
- `rpg_engine/save_manager.py`：workspace registry、active save、pending action/clarification、path boundary、registry refresh。
- `rpg_engine/projections.py` 和 `rpg_engine/projection_service.py`：projection_state/outbox/projection report/read model 健康语义。
- `rpg_engine/save_archive.py`：archive manifest、export/import、path safety、checksum/size validation、atomic import。
- `rpg_engine/save_patch.py`：maintenance patch 写入边界、backup、projection refresh、protected gameplay field 约束。
- `rpg_engine/mcp_adapter.py` 和 `rpg_engine/cli_v1.py`：public/semi-public save/campaign/player/maintenance surfaces。
- `rpg_engine/preflight_cache.py`：advisory cache 语义和 raw identity sanitization，只有触碰 cache/audit 输出时才改。
- `docs/save-and-campaign-packages.md` 和 `docs/data-models.md`：canonical package/data model authority docs。
- `tests/test_v1_cli.py`：save init/inspect/validate/export/import、projection drift CLI gates。
- `tests/test_package_save_condition_coverage.py`：SaveManager helper/path/registry/pending branch coverage。
- `tests/test_mcp_adapter.py`：MCP path rejection、audit log、default profile boundaries。
- `tests/test_projection_service.py`：projection_state/outbox/report/repair behavior。
- `tests/test_save_patch.py`：maintenance patch 不推进 turn、protected field rejection。
- `tests/test_current_native_write_safety.py` 和 `tests/test_current_native_package.py`：current native temp-copy write safety/package boundary gates if behavior touches current native contracts.

### 测试要求

最小有意义门禁应覆盖本 story 实际触碰面：

```bash
python3 -m pytest -q tests/test_v1_cli.py tests/test_package_save_condition_coverage.py tests/test_mcp_adapter.py tests/test_projection_service.py tests/test_save_patch.py
git diff --check
```

如果只改 docs 或 story artifact：

```bash
git diff --check
python3 scripts/check_markdown_links.py docs _bmad-output
```

如果改动 Save Package schema、migration、archive import/export 或 current native contracts：

```bash
python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_write_safety.py
python3 -m pytest -q
```

如果新增/修改 public/semi-public surface taxonomy：

```bash
python3 -m pytest -q tests/test_surface_inventory.py tests/test_namespace_boundaries.py
```

### 残余风险与边界

- Projection/outbox 健康证据和 Save fact authority 关系紧密；Story 1.5 会专门处理 projection/outbox health evidence。1.4 应建立“不能覆盖 facts”的边界，不要抢做 1.5 的完整 repair UX。
- `.aigmsave` 默认可能包含 hidden/GM-only 信息；本 story 只要求它不是另一个可写事实源，不承诺玩家视角脱敏导出。
- `memory`、`reports`、`package_lock` 当前在 projection versions 中存在，但不是全部 required projections。测试应覆盖 required projections，并在涉及 optional projection 时明确其 advisory/derived 语义。
- 多人/多 actor 模型仍不在本 story 范围内；pending/platform actor 绑定沿用 Story 1.2/1.3 的单 actor 边界。

### 最新技术信息

无需外部 Web research。本 story 使用现有 Python stdlib、SQLite、zipfile、JSON/YAML、pytest fixtures、atomic write helpers、ProjectionService 和 SaveManager patterns。不要新增运行时依赖。

## Project Structure Notes

Story 1.4 应优先增强现有 Save/validation/manager/projection/archive/patch 合同和测试，不应引入新的包层级或第二套状态服务。若需要 machine-readable contract，优先放在 `save_validation.py` 的 inspect 输出或小型 helper 中，并同步 docs/tests；不要建立新数据库表。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/bmad-residual-risk-backlog.md`
- `_bmad-output/implementation-artifacts/1-3-player-confirm-validation-commit-gate.md`
- `_bmad-output/implementation-artifacts/1-2-player-turn-pending-contract.md`
- `docs/project-context.md`
- `docs/save-and-campaign-packages.md`
- `docs/data-models.md`
- `docs/testing-and-quality-gates.md`
- `docs/architecture.md`
- `rpg_engine/save_validation.py`
- `rpg_engine/save_service.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/projections.py`
- `rpg_engine/projection_service.py`
- `rpg_engine/save_archive.py`
- `rpg_engine/save_patch.py`
- `rpg_engine/mcp_adapter.py`
- `rpg_engine/cli_v1.py`
- `tests/test_v1_cli.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_mcp_adapter.py`
- `tests/test_projection_service.py`
- `tests/test_save_patch.py`

## Dev Agent Record

### Agent Model Used

TBD

### Debug Log References

- TBD

### Completion Notes List

- TBD

### File List

- TBD

## Change Log

- 2026-07-05: Created Story 1.4 from Epic 1 backlog, incorporating Save/Campaign authority docs, current Save/projection/archive implementation state, and previous player-safe boundary learnings; status set to ready-for-dev.
