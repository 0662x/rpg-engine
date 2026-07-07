---
baseline_commit: 110fb3ab6b6786bd90acb680e3fc48e91e49b561
---

# Story 2.1: Campaign and Save Ownership Contract

Status: done

Completion note: Ultimate context engine analysis completed - comprehensive developer guide created.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## 用户故事

作为 campaign author，
我希望 Campaign Package 作者内容和 Save Package 运行事实拥有显式 ownership contracts，
从而改变游戏世界和游玩存档时不会修改错误的事实来源。

## 验收标准

1. 给定一个 Campaign Package，当 campaign validation 检查包内容时，author content、capabilities、rules、prompts、templates、smoke tests 和 content files 必须被允许；SQLite、save manifests、projections、memory、backups、reports、pending state 等运行态文件必须被拒绝或以稳定 warning 报告为不适合出现在作者包中。
2. 给定一个从 Campaign Package 初始化的 Save Package，当 save init 或 starter copy 完成时，`save.yaml`、运行态 `campaign.yaml`、SQLite、events projection、snapshots 和 cards 必须被创建或规范化；作者 Campaign Package 文件不得被视为可变 runtime progress，也不得因为初始化而被改写。
3. 给定普通 play 创建 runtime changes，当 facts、relationships、progress 或 events 被提交时，这些变化必须只存储在 Save Package fact boundary 内；source Campaign Package 不得被修改。

## 任务 / 子任务

- [x] 固化 Campaign Package 作者内容 vs 运行态文件 ownership validation。 (AC: 1)
  - [x] 在 `rpg_engine/campaign_validation.py` 增加或强化 package ownership 检查，允许 author files：`campaign.yaml`、`AUTHOR_NOTES.md`、`AUTHOR_AI_PROMPT.md`、`content/**`、`prompts/**`、`templates/**`、`tests/**`、`docs/**`。
  - [x] 对 Campaign root 中的 Save/runtime artifacts 给出稳定 error 或 warning，至少覆盖：`data/game.sqlite`、`data/events.jsonl`、`save.yaml`、`snapshots/**`、`cards/**`、`memory/**`、`backups/**`、`reports/**`、`.aigm/pending-player-action.json`、`.aigm/pending-player-clarification.json`。
  - [x] 不把 `package-lock.json`、author docs 或 campaign author prompts 误判为 runtime facts；`package-lock.json` 是 package maintenance evidence，不是 gameplay fact。
  - [x] 在 `tests/test_campaign_validation.py` 增加 focused tests，验证 runtime artifacts 被报告，正常 author files 仍通过。

- [x] 固化 Save init / starter copy 产物归属。 (AC: 2)
  - [x] 复用 `rpg_engine/save_service.init_v1_save()`、`normalize_content_paths_for_save()`、`copy_content_file_for_save()`、`load_campaign()` 和 `ProjectionService`；不要新增第二套 save initializer 或 package copier。
  - [x] 增加/强化 tests，确认 `save init` 产物包含运行态 `campaign.yaml`、`save.yaml`、`data/game.sqlite`、`data/events.jsonl`、`snapshots/current.md`、`snapshots/current.json` 和 `cards/`，且 `save.yaml.source_campaign_path` 为相对路径。
  - [x] 断言运行态 `campaign.yaml` 使用 save-local runtime paths：`data/game.sqlite`、`data/events.jsonl`、`snapshots/current.md`、`snapshots/current.json`、`cards`，content paths 仍为相对路径。
  - [x] 增加 source Campaign tree digest 或 selected file mtime/content 断言，证明 `init_v1_save()` 不修改来源 Campaign 文件。
  - [x] 如触碰 starter copy 路径，在 `tests/test_save_manager.py` 或 `tests/test_package_save_condition_coverage.py` 中覆盖 starter copy 重写运行态 manifests 后仍不修改 source Campaign。

- [x] 固化普通 play 不回写 source Campaign。 (AC: 3)
  - [x] 使用临时 workspace 和 `SaveManager` 或 CLI `player` path 初始化 Save，再执行能产生 pending action 的普通玩家 turn 和 confirm；验证提交后的 turn/events/entity/projection 变化只发生在 Save Package 内。
  - [x] 用 source Campaign tree digest 断言 `player_turn()`、`player_confirm()`、projection refresh 和 registry refresh 不修改 source Campaign。
  - [x] 继续保持 `player_turn()` 只写 pending action / clarification，`player_confirm()` 才提交 Save facts；不要为了本 story 直接调用 low-level `GMRuntime.commit_turn()` 作为普通玩家路径替代。
  - [x] 如果最小 fixture 的自然语言无法稳定产生 committable action，使用现有 deterministic action / external candidate test helper，但仍必须通过 `SaveManager.player_turn()` / `player_confirm()` player-safe 边界。

- [x] 同步 canonical docs 与 contract wording。 (AC: 1, 2, 3)
  - [x] 更新 `docs/save-and-campaign-packages.md`，明确 campaign validation 对 runtime artifacts 的 error/warning contract，以及 save init/source Campaign no-mutation evidence。
  - [x] 更新 `docs/authoring-guide.md` 或 `docs/data-models.md`，仅在实现改变作者可编辑文件、runtime artifact 分类或 validation 输出语义时同步。
  - [x] 不新增旧 `docs/specs/`、`docs/architecture/` 正文；旧路径只保留 compatibility stubs。

- [x] 运行 focused gates 并记录证据。 (AC: 1, 2, 3)
  - [x] 先跑新增/修改的 RED tests；若某项行为已满足，只记录 “existing behavior locked by new test”。
  - [x] 最小 GREEN gate：`python3 -m pytest -q tests/test_campaign_validation.py tests/test_v1_cli.py tests/test_save_manager.py tests/test_package_save_condition_coverage.py` 中与本 story 相关的测试或完整文件。
  - [x] Campaign/Save focused gate：`python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_write_safety.py`，写入类 current native 测试必须只用 temp copy，不得修改正式 current save package。
  - [x] Campaign smoke gate：`python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` 和 `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure`。
  - [x] 收尾运行 `git diff --check`；若 docs/story links 变化，运行 `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`。

### Review Findings

- [x] [Review][Patch] `.aigm/pending-*` 文档承诺与实现枚举不一致；已改为 glob 覆盖任意 pending runtime artifact。[rpg_engine/campaign_validation.py:36]
- [x] [Review][Patch] runtime artifacts warning contract 测试未证明不会变成 validation error；已显式断言 `result.ok` 且路径只出现在 warnings。[tests/test_campaign_validation.py:142]
- [x] [Review][Patch] `tests/test_v1_cli.py` 重复实现 `tree_digest`；已改为复用 `tests.helpers.tree_digest`，并增强 helper 对空目录 mutation 的检测。[tests/test_v1_cli.py:62]
- [x] [Review][Patch] starter copy 成功路径缺少 AC2 验收证据；已在 SaveManager starter flow 测试中断言 `starter_copy`、runtime manifests/artifacts、相对 `source_campaign_path` 和 source Campaign no-mutation。[tests/test_save_manager.py:102]
- [x] [Review][Patch] `data/`、`exports/`、`.aigmsave`、dangling symlink 和 directory symlink runtime artifacts 可能漏报或被遍历；已扩展 artifact detector 并补测试。[rpg_engine/campaign_validation.py:36]
- [x] [Review][Patch] source Campaign no-mutation digest 不检测空目录，ordinary play 也未显式拒绝 source runtime dirs；已让 shared digest 纳入目录并补 source runtime dir sentinel。[tests/helpers.py:147]
- [x] [Review][Patch] runtime artifact 目录内的 dangling symlink 仍可能被 `rglob().is_file()` 过滤掉；已把目录扫描扩展为普通文件或 symlink，并补 `data/dangling-runtime.tmp` 覆盖。[rpg_engine/campaign_validation.py:318]
- [x] [Review][Patch] source tree digest 未覆盖 symlink target 变化；已在 shared `tree_digest()` 中记录 symlink path 和 `os.readlink()` target。[tests/helpers.py:147]
- [x] [Review][Patch] warning wording/path boundary 缺少精确断言；已逐项断言 runtime artifact warning 的完整稳定字符串。[tests/test_campaign_validation.py:163]
- [x] [Review][Patch] starter copy 证据可在未复制 starter-only payload 时通过；已在 starter package 增加 marker 并断言目标 Save Package 含该 marker。[tests/test_save_manager.py:110]
- [x] [Review][Patch] 非 canonical SQLite/DB/WAL runtime 文件可能漏报；已把 `.sqlite`、`.db` 及 WAL/SHM/journal suffix 纳入 Campaign ownership warning，并补 root-level DB 测试。[rpg_engine/campaign_validation.py:43]
- [x] [Review][Patch] `campaign.yaml.content.* = ../outside/...` 可能被 package loader 读取到 Campaign root 外部；已在 Campaign validation 和 package source loader 双层拒绝 root escape，并补外部 content path 测试。[rpg_engine/packages/service.py:1282]
- [x] [Review][Patch] `.aigm` 目录 symlink 可能让 pending glob 跨出 Campaign root；已改为先检查 `.aigm` 本身，symlink 只报告 `.aigm/`，真目录才枚举 pending/registry 文件，并补外部 pending 不枚举测试。[rpg_engine/campaign_validation.py:332]
- [x] [Review][Patch] `campaign test` temp copy 未忽略完整 runtime artifact 集合；已复用 runtime ignore patterns 覆盖 `memory/`、`.aigm/`、`save.yaml` 和 archive/DB suffix，并补 runtime symlink copy 测试。[rpg_engine/campaign_validation.py:58]
- [x] [Review][Patch] `source_campaign_path` 只断言相对路径，未证明解析后指向 source Campaign；已在 save init 和 starter copy 测试中断言解析目标。[tests/test_v1_cli.py:571]
- [x] [Review][DecisionNeeded] `.aigm/save-registry.json` 是否应纳入 Campaign runtime warning；用户决策为“纳入”，已作为 warning-only runtime/workspace artifact 覆盖。[rpg_engine/campaign_validation.py:38]
- [x] [Review][Patch] `.aigm` symlink 下仍可能先探测外部 `save-registry.json`；已只在真实 `.aigm/` 目录内枚举 registry/pending，symlink 只报告 `.aigm/`。[rpg_engine/campaign_validation.py:326]
- [x] [Review][Patch] root-level smoke copy ignore 会误删合法作者目录 `content/data/`；已改为 root-aware ignore，只忽略 Campaign root 下的 runtime dirs/files，并补 `content/data/entities.yaml` smoke test。[rpg_engine/campaign_validation.py:359]
- [x] [Review][Patch] migration paths 仍可绝对路径或 `..` 逃出 package root；已在 `migration_entry_path()` 加硬边界并补 `load_package_source()` 越界测试。[rpg_engine/packages/service.py:923]
- [x] [Review][Patch] SQLite runtime suffix 漏掉 `.sqlite3` 及 WAL/SHM/journal 变体；已扩展 warning suffix 并补 `.sqlite3`/`.sqlite3-wal` 覆盖。[rpg_engine/campaign_validation.py:43]
- [x] [Review][Patch] canonical docs 未显式同步 `.aigm/save-registry.json` runtime warning 决策；已更新 Campaign/Save、data model 和 authoring docs。[docs/save-and-campaign-packages.md:86]
- [x] [Review][DecisionNeeded] 是否禁止 Save target 位于 source Campaign root 内；用户决策为“禁止”，已在 `init_v1_save()` 创建 target 前拒绝并补 CLI no-mutation 测试。[rpg_engine/save_service.py:49]
- [x] [Review][Patch] `init_v1_save(..., --force)` 未拒绝 target 为 source Campaign 祖先目录，可能删除 source；已加 source/target 双向 overlap guard 并补 `--force` CLI 测试。[rpg_engine/save_service.py:18]
- [x] [Review][Patch] `SaveManager.create_save()` starter/non-starter 路径可绕过 save target placement guard；已在创建目录前复用同一 guard，并补 workspace root 等于 source Campaign root 的 no-dir test。[rpg_engine/save_manager.py:240]
- [x] [Review][Patch] `content/palettes/*.yaml` 自动发现可经 symlink 读取 Campaign root 外文件；已在 validation/runtime palette discovery 加 root boundary，并补 symlink escape 测试。[rpg_engine/campaign_validation.py:498]

## 开发说明

### 来源上下文

- Epic 2 要求作者可以用 Campaign Package 定义可替换世界、实体、关系和进度，Save Package 承载运行事实；Story 2.1 是 Campaign/Save 分层的入口故事。来源：`_bmad-output/planning-artifacts/epics.md`。
- PRD FR-13 要求 Campaign Package 表达 AI-hosted play 基础结构；FR-14 要求 Save Package 保持长期本地 play 的 authoritative runtime state；FR-17 要求通用 Kernel 与具体 Campaign 内容分离。来源：`_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`。
- Foundation Architecture AD-1 规定 Campaign Package 只包含 authored content 和 author tests；Save Package 包含 SQLite facts/events、relationship/progress changes、projections、snapshots、cards、memory 和 metadata；普通 play 不能把运行事实写回 Campaign Package。来源：`_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`。
- Foundation Architecture AD-10 要求涉及 Campaign/Save foundation 的 story 用 package/boundary tests 证明普通 play 不修改 Campaign Package，Save SQLite 仍是事实权威。来源：同上。
- Execution-chain AD-1 仍适用：ordinary player fact writes 必须通过 `SaveManager.player_turn()` -> pending action -> `SaveManager.player_confirm()` -> `GMRuntime.commit_turn()` validation/commit。来源：`_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`。
- Canonical docs 明确 Campaign Package 不应包含 `data/game.sqlite`、`data/events.jsonl`、`snapshots/`、`cards/`、`memory/`、`backups/`、`save.yaml` 或运行时报告/缓存/玩家进度；Save Package 保存当前事实和投影。来源：`docs/save-and-campaign-packages.md`、`docs/authoring-guide.md`、`docs/data-models.md`。

### 当前实现状态

- `validate_campaign_package()` 当前读取 `campaign.yaml`，执行 manifest shape、capabilities、V1 structure、code extension、content path、required files、random tables、smoke tests、package source、content references 和 palette checks。来源：`rpg_engine/campaign_validation.py`。
- `validate_no_v1_code_extensions()` 当前拒绝 `plugins/` 和 campaign root 下的 Python code；`validate_content_paths()` 当前拒绝绝对 content paths 但还没有专门的 runtime artifact ownership check。来源：`rpg_engine/campaign_validation.py`。
- `Campaign.resolve_under_root()` 拒绝 runtime 路径绝对值和 root escape；`Campaign.resolve_content_file()` 只允许 campaign root 或 trusted source roots 下的相对 content path。来源：`rpg_engine/campaign.py`。
- `init_v1_save()` 当前复制/规范化 source campaign content，写入 save-local runtime `campaign.yaml`、`save.yaml`，初始化 SQLite，并刷新 `events_jsonl`、`search`、`snapshots` 和 `cards`。来源：`rpg_engine/save_service.py`。
- `save.yaml.source_campaign_path` 当前由 `relative_to_save(target, source.root)` 产生，因此应保持相对路径；运行态 `campaign.yaml` 的 database/events/snapshots/cards paths 已固定为 save-local runtime paths。来源：`rpg_engine/save_service.py`。
- `tests/test_campaign_validation.py` 已覆盖 minimal campaign validation/smoke、bad references、random table errors、absolute content path/code extension rejection，以及 runtime path root boundary。
- `tests/test_v1_cli.py::test_save_init_inspect_validate_export_import` 已覆盖 save init / inspect / validate / export / import 的核心形状和 authority contract，是 Story 2.1 可扩展的主要系统测试。
- `tests/test_current_native_package.py` 已覆盖 current author package 和 current save package 的责任边界，但 formal current save 只能 read-only；写入测试必须复制到 temp dirs。
- `tests/helpers.py` 提供 `tree_digest()`、`copy_initialized_minimal()`、`copy_current_packages()`、`current_turn()` 等 helper，可直接用于 source Campaign no-mutation 断言。

### 前序故事情报

- Story 1.4 已完成 Save fact authority 与 runtime state boundary：SQLite `data/game.sqlite` 是 current fact authority，registry/pending/projection/archive/preflight/MCP audit 都不能覆盖 facts。Story 2.1 应复用这个 authority wording。
- Story 1.5 已完成 projection/outbox health evidence：projection artifacts 是 post-commit read models/evidence，不是反向事实源。Story 2.1 的 save init 产物归属必须沿用该边界。
- Story 1.7/1.8 已完成 CLI/platform thin adapter 边界。Story 2.1 不应把 Campaign/Save ownership 逻辑散落进 CLI/platform handler；CLI 只能调用 kernel services。

### 架构合规要求

- Campaign validation 可以读取和报告 runtime artifacts，但不得把它们当成可导入 author content，也不得初始化/修复 Save facts。
- Save init 是 maintenance/package operation，不是普通 gameplay commit；它可以创建 Save Package runtime state，但不能改 source Campaign Package 文件。
- Ordinary play 的 runtime changes 必须落在 Save Package：SQLite facts/events、projection artifacts、pending state 或 workspace registry。source Campaign Package 不得变化。
- 不要引入第二个 package model、第二个 save manifest format、并行 fact authority 或 campaign-specific runtime schema。
- 不要把 `package-lock.json` 和 package maintenance evidence 等同于 gameplay runtime facts；如果 validation 需要提示，应使用明确 wording 避免破坏已有 package workflows。
- Tests 涉及 formal current native save 时必须只读；写入测试复制到 temp dirs。

### 相关文件

- `rpg_engine/campaign_validation.py`：Campaign Package validation、runtime artifact ownership check 的主要落点。
- `rpg_engine/campaign.py`：Campaign path resolution、trusted source root 和 content file boundary；除非 story 发现明确缺口，否则不要改大范围 API。
- `rpg_engine/save_service.py`：`init_v1_save()`、save-local runtime manifest、source campaign relative path 和 projection refresh。
- `rpg_engine/save_manager.py`：player-safe `player_turn()` / `player_confirm()`；用于证明 ordinary play 不回写 source Campaign。
- `rpg_engine/cli_v1.py` / `rpg_engine/cli.py`：仅当 CLI output/contract 需要同步时触碰；不要复制 package ownership 业务逻辑。
- `docs/save-and-campaign-packages.md`：Campaign/Save ownership canonical contract。
- `docs/authoring-guide.md`：作者可编辑/不可编辑文件指导。
- `docs/data-models.md`：Campaign manifest、Save manifest、SQLite fact authority 和 projection/registry/advisory state 边界。
- `tests/test_campaign_validation.py`：campaign validation focused tests。
- `tests/test_v1_cli.py`：save init/inspect/validate/export/import 系统测试。
- `tests/test_save_manager.py`：player-safe workflow 和 starter/save creation tests。
- `tests/test_package_save_condition_coverage.py`：SaveManager package/starter edge coverage。
- `tests/test_current_native_package.py`、`tests/test_current_native_write_safety.py`：current native package/save boundary tests。

### 测试要求

最小 focused gates：

```bash
python3 -m pytest -q tests/test_campaign_validation.py
python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import
python3 -m pytest -q tests/test_save_manager.py tests/test_package_save_condition_coverage.py
git diff --check
```

如果触碰 current native package/save boundary：

```bash
python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_write_safety.py
```

如果触碰 Campaign validation 或 author docs：

```bash
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md
```

如果实现变化影响 package CLI or SaveManager creation broadly：

```bash
python3 -m pytest -q tests/test_package_cli.py tests/test_save_manager.py tests/test_package_save_condition_coverage.py tests/test_v1_cli.py
```

### 残余风险与边界

- 本 story 不要求实现 Content Type / Merge Contract；那是 Story 2.2。
- 本 story 不要求新增 Entity/Relationship/Progress access APIs；那是 Story 2.3-2.5。
- 本 story 不要求跨 Campaign model smoke；那是 Story 2.6。
- 本 story 不要求构建 package upgrade/migration UX，也不要求把 source Campaign 改动同步到已有 saves。
- 本 story 不要求评价作者文本质量、玩法趣味或 no-code authoring 完成度。
- 不要让 campaign validation 自动删除 runtime artifacts；本 story 只要求稳定报告 error/warning。

### 最新技术信息

无需外部 Web research。本 story 使用仓库现有 Python stdlib、PyYAML、SQLite、pytest、Campaign/Save services、ProjectionService 和 SaveManager。不要新增运行时依赖。

## Project Structure Notes

Story 2.1 应优先小步增强 `campaign_validation.py` 与 focused tests，并在 `save_service.py` / `SaveManager` 周边只补必要 no-mutation evidence。保持 Campaign Package、Save Package、workspace registry、pending state、projection artifacts 和 archive manifest 的现有职责分离，不做目录大改。

## References

- `_bmad-output/planning-artifacts/epics.md`
- `_bmad-output/planning-artifacts/prds/prd-aigm-kernel-foundation-2026-07-04/prd.md`
- `_bmad-output/planning-artifacts/architecture/architecture-aigm-kernel-foundation-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/planning-artifacts/architecture/architecture-rpg-engine-execution-chain-2026-07-04/ARCHITECTURE-SPINE.md`
- `_bmad-output/implementation-artifacts/1-8-platform-forwarding-与审计边界.md`
- `_bmad-output/implementation-artifacts/1-5-projection-and-outbox-health-evidence.md`
- `_bmad-output/implementation-artifacts/1-4-save-fact-authority-and-runtime-state-boundary.md`
- `docs/project-context.md`
- `docs/save-and-campaign-packages.md`
- `docs/authoring-guide.md`
- `docs/data-models.md`
- `docs/component-inventory.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/campaign_validation.py`
- `rpg_engine/campaign.py`
- `rpg_engine/save_service.py`
- `rpg_engine/save_manager.py`
- `tests/test_campaign_validation.py`
- `tests/test_v1_cli.py`
- `tests/test_save_manager.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_current_native_package.py`
- `tests/test_current_native_write_safety.py`

## Dev Agent Record

### Agent Model Used

Codex GPT-5

### Implementation Plan

- 先补 campaign validation RED tests，锁住 Campaign root 运行态 artifact 报告和 author 文件白名单。
- 再补 save init / ordinary play no-mutation tests，证明 source Campaign tree digest 不因初始化或确认提交改变。
- 最小实现 ownership validation helper；复用现有 Save/Campaign services，不新增 package/runtime 架构。
- 同步 canonical docs，运行 focused gates、campaign smoke 和 markdown/diff 检查。

### Debug Log References

- DEV start: baseline commit `110fb3ab6b6786bd90acb680e3fc48e91e49b561`; sprint status moved to `in-progress` at 2026-07-08T03:56:13+1000.
- RED: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_reports_runtime_artifacts_without_rejecting_author_files` failed because Campaign validation did not report `data/game.sqlite`, `data/events.jsonl`, `save.yaml`, projections, memory, backups, reports, or pending state under a Campaign root.
- Existing behavior locked: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import` passed after adding source Campaign tree digest and runtime manifest assertions.
- Existing behavior locked: `python3 -m pytest -q tests/test_save_manager.py::SaveManagerTests::test_player_confirm_commits_only_to_save_package_without_mutating_source_campaign` passed after adding a source Campaign tree digest sentinel around `player_turn()` and `player_confirm()`.
- GREEN: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_reports_runtime_artifacts_without_rejecting_author_files` passed with 1 test and 10 subtests after adding runtime artifact ownership warnings.
- Focused gate: `python3 -m pytest -q tests/test_campaign_validation.py` passed with 8 tests and 10 subtests.
- Save init gate: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import` passed.
- SaveManager gate: `python3 -m pytest -q tests/test_save_manager.py` passed with 28 tests and 35 subtests.
- Package/save condition gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py` passed with 12 tests and 11 subtests.
- Current native package/write-safety gate: `python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 15 tests and 17 subtests.
- Campaign validate gate: `python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure` returned OK.
- Campaign smoke gate: `python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure` returned OK.
- Docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md` passed, checking 87 markdown files.
- Syntax gate: `python3 -m py_compile rpg_engine/campaign_validation.py` passed.
- Whitespace gate: `git diff --check` passed.
- Full regression: `python3 -m pytest -q` passed with 534 tests and 648 subtests.
- CODE REVIEW: three review subagents completed. Blind Hunter reported 3 patch findings, Edge Case Hunter reported 7 edge findings, Acceptance Auditor reported 1 patch finding; triage merged them into 6 patch items and 0 decision-needed/defer items.
- REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_reports_runtime_artifacts_without_rejecting_author_files` passed with 1 test and 15 subtests.
- REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_save_manager.py::SaveManagerTests::test_start_or_continue_creates_from_starter_then_continues tests/test_save_manager.py::SaveManagerTests::test_player_confirm_commits_only_to_save_package_without_mutating_source_campaign` passed with 2 tests.
- REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import` passed.
- REVIEW PATCH syntax gate: `python3 -m py_compile rpg_engine/campaign_validation.py` passed.
- REVIEW PATCH focused gate: `python3 -m pytest -q tests/test_campaign_validation.py` passed with 8 tests and 15 subtests.
- REVIEW PATCH SaveManager gate: `python3 -m pytest -q tests/test_save_manager.py` passed with 28 tests and 35 subtests.
- REVIEW PATCH package/save condition gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py` passed with 12 tests and 11 subtests.
- REVIEW PATCH current native package/write-safety gate: `python3 -m pytest -q tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 15 tests and 17 subtests.
- REVIEW PATCH campaign validate/test gates returned OK for `./examples/v1_minimal_adventure`.
- REVIEW PATCH docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md` passed, checking 87 markdown files.
- REVIEW PATCH whitespace gate: `git diff --check` passed.
- REVIEW PATCH full regression: `python3 -m pytest -q` passed with 534 tests and 653 subtests.
- SECOND REVIEW: three review subagents completed. Blind Hunter, Edge Case Hunter, and Acceptance Auditor reported 4 additional patch findings around runtime-dir symlinks, symlink target digest coverage, exact warning wording, and starter-only copy evidence; triage found 0 decision-needed/defer items.
- SECOND REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_reports_runtime_artifacts_without_rejecting_author_files` passed with 1 test and 17 subtests.
- SECOND REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_save_manager.py::SaveManagerTests::test_start_or_continue_creates_from_starter_then_continues` passed.
- SECOND REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import` passed.
- SECOND REVIEW PATCH syntax gate: `python3 -m py_compile rpg_engine/campaign_validation.py` passed.
- FINAL REVIEW: three review subagents completed. Acceptance Auditor returned clean; Blind Hunter reported 1 patch item; Edge Case Hunter reported 4 patch items and 1 decision-needed item. User decided to include `.aigm/save-registry.json` as a warning-only runtime artifact.
- FINAL REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_reports_runtime_artifacts_without_rejecting_author_files tests/test_campaign_validation.py::CampaignValidationTests::test_reports_aigm_symlink_without_following_external_pending_files tests/test_campaign_validation.py::CampaignValidationTests::test_rejects_content_paths_that_escape_campaign_root tests/test_campaign_validation.py::CampaignValidationTests::test_campaign_test_ignores_runtime_symlink_artifacts_when_copying_temp_campaign` passed with 4 tests and 21 subtests.
- FINAL REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_save_manager.py::SaveManagerTests::test_start_or_continue_creates_from_starter_then_continues` passed.
- FINAL REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import` passed.
- FINAL REVIEW PATCH GREEN: `python3 -m pytest -q tests/test_package_save_condition_coverage.py` passed with 12 tests and 11 subtests.
- FINAL REVIEW PATCH syntax gate: `python3 -m py_compile rpg_engine/campaign_validation.py rpg_engine/packages/service.py` passed.
- CLEAN REVIEW FOLLOW-UP: Acceptance Auditor reported 2 patch items; Edge Case Hunter reported 4 patch items and 1 decision-needed item; Blind Hunter returned clean. User decided to forbid Save targets inside the source Campaign root.
- CLEAN REVIEW FOLLOW-UP PATCH GREEN: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_reports_runtime_artifacts_without_rejecting_author_files tests/test_campaign_validation.py::CampaignValidationTests::test_reports_aigm_symlink_without_following_external_pending_files tests/test_campaign_validation.py::CampaignValidationTests::test_campaign_test_ignores_runtime_symlink_artifacts_when_copying_temp_campaign tests/test_campaign_validation.py::CampaignValidationTests::test_campaign_test_keeps_author_content_directories_named_like_runtime_dirs` passed with 4 tests and 23 subtests.
- CLEAN REVIEW FOLLOW-UP PATCH GREEN: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_rejects_target_inside_source_campaign tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import` passed.
- CLEAN REVIEW FOLLOW-UP PATCH GREEN: `python3 -m pytest -q tests/test_package_save_condition_coverage.py::PackageServiceConditionCoverageTests::test_package_source_validation_combines_manifest_record_and_migration_errors tests/test_package_save_condition_coverage.py::PackageServiceConditionCoverageTests::test_package_source_rejects_migration_paths_that_escape_package_root tests/test_package_save_condition_coverage.py::PackageServiceConditionCoverageTests::test_package_authorizations_renderers_and_helper_edges` passed.
- CLEAN REVIEW FOLLOW-UP PATCH syntax gate: `python3 -m py_compile rpg_engine/campaign_validation.py rpg_engine/packages/service.py rpg_engine/save_service.py` passed.
- CLEAN REVIEW FOLLOW-UP docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md` passed, checking 87 markdown files.
- FINAL CLEAN REVIEW FOLLOW-UP: Blind Hunter, Edge Case Hunter, and Acceptance Auditor reported 3 additional patch items and 0 decision-needed items: save target ancestor overlap, SaveManager target placement guard, and palette auto-discovery symlink escape.
- FINAL CLEAN REVIEW FOLLOW-UP PATCH GREEN: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_rejects_target_inside_source_campaign tests/test_v1_cli.py::V1CliTests::test_save_init_rejects_target_that_contains_source_campaign_even_with_force` passed.
- FINAL CLEAN REVIEW FOLLOW-UP PATCH GREEN: `python3 -m pytest -q tests/test_save_manager.py::SaveManagerTests::test_create_save_rejects_save_target_inside_source_campaign_before_creating_dirs` passed.
- FINAL CLEAN REVIEW FOLLOW-UP PATCH GREEN: `python3 -m pytest -q tests/test_campaign_validation.py::CampaignValidationTests::test_palette_auto_discovery_rejects_symlink_escape` passed.
- FINAL CLEAN REVIEW FOLLOW-UP syntax gate: `python3 -m py_compile rpg_engine/save_service.py rpg_engine/save_manager.py rpg_engine/campaign_validation.py rpg_engine/palette.py` passed.
- FINAL CLEAN REVIEW FOLLOW-UP whitespace gate: `git diff --check` passed.
- FINAL CLEAN REVIEW: Blind Hunter, Edge Case Hunter, and Acceptance Auditor all returned clean with 0 patch items and 0 decision-needed items.
- FINAL focused gate: `python3 -m pytest -q tests/test_campaign_validation.py` passed with 13 tests and 23 subtests.
- FINAL save init gate: `python3 -m pytest -q tests/test_v1_cli.py::V1CliTests::test_save_init_inspect_validate_export_import tests/test_v1_cli.py::V1CliTests::test_save_init_rejects_target_inside_source_campaign tests/test_v1_cli.py::V1CliTests::test_save_init_rejects_target_that_contains_source_campaign_even_with_force` passed with 3 tests.
- FINAL SaveManager gate: `python3 -m pytest -q tests/test_save_manager.py` passed with 29 tests and 35 subtests.
- FINAL package gate: `python3 -m pytest -q tests/test_package_save_condition_coverage.py` passed with 13 tests and 11 subtests.
- FINAL package/current native gate: `python3 -m pytest -q tests/test_package_cli.py tests/test_current_native_package.py tests/test_current_native_write_safety.py` passed with 31 tests and 17 subtests.
- FINAL campaign validate/test gates returned OK for `./examples/v1_minimal_adventure`.
- FINAL docs gate: `python3 scripts/check_markdown_links.py docs _bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md` passed, checking 87 markdown files.
- FINAL syntax gate: `python3 -m py_compile rpg_engine/campaign_validation.py rpg_engine/packages/service.py rpg_engine/palette.py rpg_engine/save_manager.py rpg_engine/save_service.py` passed.
- FINAL whitespace gate: `git diff --check` passed.
- FINAL full regression: `python3 -m pytest -q` passed with 543 tests and 661 subtests.
- DONE sync: story status moved to `done`; sprint status synced at 2026-07-08T05:07:47+1000.

### Completion Notes List

- Added stable Campaign ownership warnings for Save/runtime artifacts found under a Campaign root, including SQLite, events projection, save manifest, projections, memory, backups, reports, and pending player state.
- Kept author files and package maintenance evidence out of runtime fact classification: author notes/prompts/docs and `package-lock.json` are not reported as gameplay runtime facts.
- Added source Campaign no-mutation sentinels for save init and ordinary `SaveManager.player_turn()` / `player_confirm()` flow; runtime changes remain in Save Package boundaries.
- Synchronized canonical Campaign/Save, authoring, and data model docs with the ownership warning and source Campaign no-mutation contract.
- Applied code review patches for broader runtime artifact detection (`data/`, `exports/`, `.aigmsave`, pending globs, symlinks), warning-only validation assertions, shared tree digest behavior, starter copy evidence, and source runtime directory mutation sentinels.
- Applied second-review patches for runtime-directory symlink artifacts, symlink-target digest coverage, exact warning wording, and starter-only payload copy proof.
- Applied final-review patches for non-canonical DB/WAL artifacts, `.aigm` symlink safety, content path root-escape rejection, campaign smoke runtime-copy ignores, `source_campaign_path` target proof, and `.aigm/save-registry.json` warning coverage.
- Applied clean-review follow-up patches for `.aigm` symlink registry safety, root-aware smoke copy ignores, migration path root boundaries, `.sqlite3` runtime artifacts, docs sync, and Save target placement rejection inside source Campaign roots.
- Applied final clean-review follow-up patches for source/target ancestor overlap protection, SaveManager placement guard reuse, and palette auto-discovery symlink root boundaries.

### Change Log

- 2026-07-08: Implemented Story 2.1 Campaign/Save ownership validation warnings, no-mutation tests, docs sync, review patches, and final verification gates; story moved to done.

### File List

- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.md`
- `_bmad-output/implementation-artifacts/2-1-campaign-and-save-ownership-contract.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/authoring-guide.md`
- `docs/data-models.md`
- `docs/save-and-campaign-packages.md`
- `rpg_engine/campaign_validation.py`
- `rpg_engine/packages/service.py`
- `rpg_engine/palette.py`
- `rpg_engine/save_manager.py`
- `rpg_engine/save_service.py`
- `tests/helpers.py`
- `tests/test_campaign_validation.py`
- `tests/test_package_save_condition_coverage.py`
- `tests/test_save_manager.py`
- `tests/test_v1_cli.py`
