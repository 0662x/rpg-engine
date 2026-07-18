---
baseline_commit: 0496842947a0eba0f614afcd4c0a7c044f797268
---

# Story 6.8：RPG Engine Compatibility Fixture for Hermes Stdio E2E

Status: done

## Story

作为跨仓库集成维护者，
我希望获得一个稳定的 RPG Engine provider 兼容性夹具，
从而让 Hermes 兼容性套件可以验证真实 stdio 行为，而不让 RPG Engine 承担 Hermes client lifecycle。

## Acceptance Criteria

1. **真实、确定且离线的 stdio provider 夹具**
   - Given 兼容性夹具启动 RPG Engine MCP provider，when scripted client 执行确定性 transcript，then 必须经 `mcp.client.stdio` 连接真实 FastMCP stdio subprocess，不得用 FakeFastMCP、adapter 直调或 in-memory transport 代替 wire contract。
   - 夹具固定使用 `player` MCP profile，并显式关闭 semantic、intent 与 state-audit AI；运行不得读取 `.env`、API key，也不得发起网络请求。
   - 夹具只编排现有 `python -m rpg_engine mcp serve` production entrypoint，不新增测试专用 production API、不复制 Kernel/SaveManager 业务规则。
   - 必须提供稳定、可复用的启动描述和 data-driven scripted-model contract，供本仓测试及 Hermes CI 在检出 RPG Engine 后消费。

2. **manifest、refresh、turn、confirm 与安全 audit 契约可观测**
   - `intent_manifest` transcript 必须暴露当前 `schema_version`、`manifest_digest`、safety vocabulary version/digest；四字段仅作为 external candidate 的低信任 contract envelope，不能授予事实、玩家确认或 commit authority。
   - 使用 stale/wrong contract 的 candidate 必须在 pending/事实写入前返回稳定的 `INTENT_CONTRACT_VERSION_MISMATCH`、`contract_version_mismatch` 与 `refresh_manifest_and_regenerate_candidate`；错误结果和 audit 不得泄露 raw candidate、玩家文本、session secret、private reasoning 或 hidden/GM-only canary。
   - refresh 后必须从新取的 live manifest **整体重建** candidate，而不是 patch 旧 candidate；随后真实 `player_turn` 只创建一个可确认 pending，SQLite/turn/event/events.jsonl 在确认前不变。
   - 玩家确认必须是与 scripted-model 输出分离的显式 client step。正确 `player_confirm(session_id)` 精确提交一次；replay 返回 `already_confirmed` / idempotent，不能产生第二个 turn/event。
   - 夹具必须产出 bounded、机器可读的 transcript hooks，足以让 Hermes H4 断言 provider 输出与 next-turn ordering；volatile timestamp、Save ID 与 pending session ID 只能按存在性、枚举或批准 hash 投影，RPG Engine 不在本 Story 实现 Hermes next-model-turn barrier。
   - 范围决策（2026-07-19）：为满足本 Story 的 safe-audit hook，允许在 canonical MCP audit sanitizer 中把 `player_confirm` 的 raw `session_id` 改为批准的 hash/摘要并补回归；Story 6.7 仍独占完整 normalized route reconstruction summary、manifest/preflight route metadata 与其余审计重构，不得在本 Story实现。

3. **所有写入严格隔离在 temporary Campaign/Save/workspace**
   - 每次可写测试必须新建独立 temporary root，将 source Campaign 复制到 temporary Campaign，并只初始化/写 temporary Save、temporary registry、temporary pending state 与 temporary audit log。
   - 夹具必须拒绝 absolute、`..` 或逃逸 temporary root 的 Campaign/Save 参数；server 的 root、Campaign、Save 与 audit owner 均绑定同一 temporary workspace。
   - 验证前后必须比较 source Campaign、formal current Campaign/Save、正式 workspace registry、其 `data/game.sqlite` 与玩家数据指纹；除 temporary workspace 外不得发生变化。
   - stale candidate、错误 session、确认、replay、异常退出与清理路径都必须保持上述隔离；subprocess 必须有 timeout 并可靠关闭，避免 CI 悬挂。

4. **player surface、事实权威与既有行为不退化**
   - `data/game.sqlite` 继续是当前事实权威；external/scripted model 仅能提出 candidate，internal AI 不获得事实、hidden、玩家确认、proposal approval、validation 或 commit authority。
   - 真实 `tools/list` 必须证明 player profile 只暴露既有 player-safe 工具，低层 preview/validate/commit/preflight 工具不可注册；player response、normal query、transcript 与 audit 均不得泄露 hidden/GM-only 内容。
   - `player_turn` 不直接写事实，只有明确 `player_confirm` 可提交；现有 manifest、安全 vocabulary、candidate ingress、confirmation replay、Campaign/Save isolation 与 MCP audit sanitizer 行为不得退化。
   - 不新增依赖、数据库 migration、测试短句 production 分支、模型代理、Coordinator 或平行业务路径。

5. **跨仓 CI ownership 保持清晰**
   - RPG Engine CI 只验证 provider fixture 能启动、真实 stdio framing、player tool surface、contract outputs、deterministic transcript、safe audit 与 temporary-data isolation。
   - Hermes CI 独占真实 Hermes client、tool registration、next-model-turn barrier、reconnect lifecycle 和 combined release gate；不得修改 `/Users/oliver/.hermes/hermes-agent`。
   - Hermes H1–H4 不写入 RPG Engine sprint 状态。本 Story 不实现 Stories 6.5–6.7、6.9、Story 3.8、Story 1.10 或其他 rebaseline/Trace 工作。
   - 6.5–6.7 仍为 backlog；本 Story 的 safe-audit hook 只验证当前 provider sanitizer，不吸收 Story 6.7 的 audit reconstruction redesign。

## Tasks / Subtasks

- [x] Task 1：建立 test-owned provider fixture 与确定性脚本合同（AC: 1, 2, 3, 5）
  - [x] 新增独立 compatibility helper，创建 temporary root、复制 minimal Campaign、初始化独立 Save，并返回现有 MCP CLI 的 `StdioServerParameters`/等价稳定启动描述。
  - [x] 固定 player profile、stdio transport 与所有 AI helper 为 `off`；构造 scrubbed subprocess environment，明确移除常见 provider key 与代理变量，不读取 `.env`。
  - [x] 新增 data-driven scripted transcript，声明 `intent_manifest -> stale candidate rejection -> refresh -> entirely regenerated candidate -> player_turn -> explicit player confirmation -> wrong-session rejection -> player_confirm -> replay -> safe audit`；脚本必须有稳定 schema version、固定 step/event vocabulary、capture/reference 插值规则与 bounded expectation/hook projection，且不得产生确认 authority。
  - [x] compatibility helper 与测试不得 import 当前未跟踪的 Iteration/rebaseline/Hermes real-model harness。

- [x] Task 2：以真实 MCP stdio 锁定 provider wire contract（AC: 1, 2, 4）
  - [x] fixture 必须先在 temporary registry 建立 active Save，再以 `--registry-active` 启动 provider；不得把 `--default-save` 误当成 player flow 的 active registry owner。
  - [x] 使用官方 MCP Python SDK 的 `stdio_client` + `ClientSession` 完成 initialize、`tools/list` 与 `tools/call`，精确定义 `CallToolResult` TextContent JSON 解码/tool-error处理，并为连接/调用设置 bounded timeout、stderr capture与可靠 teardown。
  - [x] 断言 player profile 工具清单精确等于test-owned schema-v1 literal，并与canonical `PLAYER_MCP_TOOL_NAMES`同步；所有 low-level tools 缺席。
  - [x] 解析真实 MCP content envelope，锁定 live manifest 四字段、deterministic digest 与 scripted transcript 输出 shape。
  - [x] stale candidate 返回稳定 typed mismatch，刷新后从 live manifest 全量重建 candidate；两代 candidate 必须是独立对象且使用不同 generation reason，不得原地 patch或fallback到legacy unversioned candidate。

- [x] Task 3：锁定 pending/confirm、audit 与 no-mutation 语义（AC: 2, 3, 4）
  - [x] stale/错误 session 前后比较 temporary SQLite table counts、current turn、events.jsonl、pending/receipt，证明失败不写事实或可确认状态；stale request可携带platform/session-key canary验证hash，但valid turn不得携带当前MCP confirm无法回传的platform identity。
  - [x] valid `player_turn` 只产生一个预期 pending且不投影 delta/proposal；显式确认精确增加一个 turn/event，replay 不增加第二次写入。
  - [x] 检查 temporary audit JSONL：工具顺序与状态可重建，但 raw candidate slots/reason/provider body、玩家文本、platform session secret、pending confirmation `session_id`、private reasoning、hidden canary 不出现；`session_key`/`session_id`仅保留批准hash，audit仍是非权威evidence。
  - [x] 对必有 source minimal Campaign 强制前后 fingerprint；对显式配置或当前环境中存在的 formal current Campaign/Save、正式 registry/SQLite/player data 做可移植的 optional fingerprint，并证明只有 temporary root 改变且不存在samefile/路径别名。
  - [x] 通过test-owned subprocess socket deny oracle拒绝并记录实际provider路径所用CPython `socket`/DNS surface，断言正常transcript零尝试；该oracle不声称提供OS syscall/FFI sandbox。不得改写系统`HOME`，不得仅凭删除常见API-key环境变量宣称no-network。

- [x] Task 4：同步 canonical 文档和跨仓 handoff（AC: 1, 4, 5）
  - [x] 在 `docs/mcp-contracts.md` 说明 fixture 启动/消费方式、scripted contract、player surface、safe audit 与 RPG Engine/Hermes CI ownership。
  - [x] 在 `docs/testing-and-quality-gates.md` 登记 Story 6.8 focused gate、real stdio/no-network/temporary-data oracle 及 full-suite 要求。
  - [x] 仅在新 fixture 成为正式组件入口时更新 `docs/component-inventory.md` / `docs/index.md`；不得让未实现的 Hermes lifecycle 成为本仓 runtime 事实。

- [x] Task 5：从最终 clean Story diff 执行验证与持续评审收敛（AC: 1–5）
  - [x] 运行 focused real-stdio compatibility tests 与 adjacent MCP/manifest/intent/SaveManager/transcript/surface/package-isolation regressions。
  - [x] 运行两个 canonical Campaign validate/test、Markdown links、全仓 `py_compile`、full Ruff、`git diff --check` 与 repository full pytest suite。
  - [x] 三路 fresh review 按 Blind Hunter、Edge Case Hunter、Acceptance Auditor 执行；所有有效 `[Review][Patch]` 去重、复现、修复、重新验证并复审到 clean，仅记录正确 dismiss/defer。
  - [x] 所有门禁通过后同步 Story/sprint/epic 状态，只暂存 Story 6.8 归属文件，commit、push `origin/main` 并核验本地 HEAD 与远端 main 一致。

### Review Findings

- [x] [Review][Patch] 让 YAML scripted contract 以 typed arguments、capture/reference 插值及 bounded expectations 独立驱动真实 transcript [tests/compatibility/hermes_stdio_provider.py:52]
- [x] [Review][Patch] 让 no-network guard fail closed、自证加载并覆盖公开 DNS 与 connectionless socket 入口 [tests/compatibility/hermes_stdio_provider.py:179]
- [x] [Review][Patch] 用完整 SQLite logical digest 锁定确认前、失败与 replay 的权威状态不变 [tests/test_hermes_stdio_compatibility.py:26]
- [x] [Review][Patch] 无条件保护 source Campaign，并验证 custom source、absolute、`..` 与 symlink/escape 路径 [tests/compatibility/hermes_stdio_provider.py:130]
- [x] [Review][Patch] 对 versioned YAML top-level、step、hook ID 与 hook fields 使用 fail-closed allowlist [tests/compatibility/hermes_stdio_provider.py:213]
- [x] [Review][Patch] MCP tool result 必须只含唯一 TextContent，拒绝额外 image/resource/audio block [tests/compatibility/hermes_stdio_provider.py:275]
- [x] [Review][Patch] 正式数据指纹必须拒绝 protected tree 内的 symlink 盲区 [tests/compatibility/hermes_stdio_provider.py:344]
- [x] [Review][Patch] 以 temporary hidden/GM-only canary 覆盖 normal query 的 player response、hook 与 audit 边界 [tests/test_hermes_stdio_compatibility.py:201]
- [x] [Review][Patch] 添加异常/取消 teardown 证明，并以 finally 保证正式数据后置指纹检查 [tests/test_hermes_stdio_compatibility.py:201]
- [x] [Review][Patch] 直接断言 stale/wrong wire result 与 bounded hook 不泄露所有 raw canary [tests/test_hermes_stdio_compatibility.py:220]
- [x] [Review][Patch] 以两个独立 provider launch 证明 manifest digest 跨进程确定 [tests/test_hermes_stdio_compatibility.py:140]
- [x] [Review][Patch] 收紧逐 step argument schema、candidate override allowlist 与 strict non-null capture reference [tests/compatibility/hermes_stdio_provider.py:159]
- [x] [Review][Patch] 为每个 scripted step 增加 fail-closed bounded expected projection并由本仓通用断言消费 [tests/fixtures/hermes_stdio_compatibility.yaml:4]
- [x] [Review][Patch] 将 wrong-session 调用纳入 versioned transcript、typed arguments、hook 与 audit ordering [tests/fixtures/hermes_stdio_compatibility.yaml:48]
- [x] [Review][Patch] 以 subprocess network audit hook 封住低层构造绕过，并补 AF_INET6 connect/sendto positive oracle [tests/compatibility/hermes_stdio_provider.py:544]
- [x] [Review][Patch] 以隔离 subprocess cwd 与 `.env` open deny/log oracle证明 provider 不读取 dotenv [tests/compatibility/hermes_stdio_provider.py:212]
- [x] [Review][Patch] SQLite logical digest 纳入完整 sqlite_master schema objects 与 authority PRAGMA [tests/test_hermes_stdio_compatibility.py:41]
- [x] [Review][Patch] formal path 环境变量为空白时回退默认路径，禁止把 cwd 误当保护根 [tests/compatibility/hermes_stdio_provider.py:416]
- [x] [Review][Patch] hidden/GM-only wire oracle 同时扫描 subprocess stderr canary [tests/test_hermes_stdio_compatibility.py:780]
- [x] [Review][Patch] YAML loader 拒绝 duplicate mapping key，消除跨 parser transcript 分歧 [tests/compatibility/hermes_stdio_provider.py:328]
- [x] [Review][Patch] teardown 使用公开 lifecycle + child PID evidence，并精确展开预期 exception group [tests/test_hermes_stdio_compatibility.py:801]
- [x] [Review][Patch] bounded expectation 对 scalar/enum 同时校验 JSON type 与值，并拒绝空白 nonempty [tests/compatibility/hermes_stdio_provider.py:721]
- [x] [Review][Patch] 封闭 `_socket.SocketType` 与 `socket._socket` alias，并加入 raw alias positive oracle [tests/compatibility/hermes_stdio_provider.py:951]
- [x] [Review][Patch] dotenv guard 覆盖 `os.open` descriptor 入口并加入正向读取拒绝测试 [tests/compatibility/hermes_stdio_provider.py:854]
- [x] [Review][Patch] candidate generation 在任何 tool call 前固定 canonical action/slots/reason/digest source与字段类型 [tests/compatibility/hermes_stdio_provider.py:810]
- [x] [Review][Patch] 递归冻结已加载合同的arguments、expect、candidate generations与hooks，阻止load后篡改绕过 [tests/compatibility/hermes_stdio_provider.py:249]
- [x] [Review][Patch] versioned expectation与candidate generation使用递归JSON类型严格比较，拒绝`true/1`等值混淆 [tests/compatibility/hermes_stdio_provider.py:621]
- [x] [Review][Patch] 以process audit hook统一拒绝CPython原始socket、descriptor反射与guard内部alias绕过 [tests/compatibility/hermes_stdio_provider.py:945]
- [x] [Review][Patch] 保持标准`socket`/`_socket` reload兼容且reload后仍由audit hook拒绝INET构造 [tests/test_hermes_stdio_compatibility.py:419]
- [x] [Review][Patch] dotenv guard解析真实目标并以samefile识别symlink、hardlink与大小写别名 [tests/compatibility/hermes_stdio_provider.py:878]
- [x] [Review][Patch] MCP decoder要求`structuredContent`与TextContent JSON类型严格相等并拒绝非空opaque `_meta` envelope [tests/compatibility/hermes_stdio_provider.py:558]
- [x] [Review][Patch] safe audit hook关联`status`与`result.ok`，拒绝成功/失败摘要相互矛盾的false-green [tests/compatibility/hermes_stdio_provider.py:321]
- [x] [Review][Patch] wrong-session hook锁定稳定session mismatch错误文本，禁止无关provider失败冒充确认门拒绝 [tests/fixtures/hermes_stdio_compatibility.yaml:81]
- [x] [Review][Patch] audit hash oracle按对应raw session key/id计算并断言精确摘要，拒绝固定格式常量false-green [tests/test_hermes_stdio_compatibility.py:866]
- [x] [Review][Patch] 从非空formal Campaign/Save环境覆盖根派生并保护各自workspace registry指纹 [tests/compatibility/hermes_stdio_provider.py:586]
- [x] [Review][Patch] 将显式配置但尚不存在的formal根作为missing sentinel纳入别名拒绝与前后指纹 [tests/compatibility/hermes_stdio_provider.py:606]
- [x] [Review][Patch] versioned YAML hook object仅允许`fields`键，拒绝未知扩展导致的跨仓解析分歧 [tests/compatibility/hermes_stdio_provider.py:530]
- [x] [Review][Patch] 在test-owned schema-v1 YAML/helper中冻结13项player tool literal，以独立oracle核验真实`tools/list` [tests/fixtures/hermes_stdio_compatibility.yaml:3]
- [x] [Review][Patch] dotenv deny接入CPython `open` audit event并覆盖reload `io`与`_io.open`入口 [tests/compatibility/hermes_stdio_provider.py:1023]
- [x] [Review][Patch] 在surface、主transcript、hidden query与异常teardown路径锁定copied temporary Campaign前后指纹 [tests/test_hermes_stdio_compatibility.py:679]
- [x] [Review][Patch] launcher以`PYTHONNOUSERSITE=1`禁用宿主user-site/`usercustomize.py`并补temporary canary回归 [tests/compatibility/hermes_stdio_provider.py:472]
- [x] [Review][Decision] no-network证据采用CPython socket/DNS surface与实际provider路径边界，不扩张为OS级syscall/FFI sandbox（用户选择方案1，2026-07-19）
- [x] [Review][Defer] PID sentinel 不能排除极短窗口 PID reuse 或未来派生进程组 [tests/test_hermes_stdio_compatibility.py:941] — deferred：Hermes CI独占 reconnect/client lifecycle，当前AI-off provider不派生子进程；在MCP SDK提供稳定public process identity前不回引private handle

### Focused Gate

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_hermes_stdio_compatibility.py \
  tests/test_mcp_adapter.py \
  tests/test_intent_manifest.py \
  tests/test_ai_intent.py \
  -p no:cacheprovider
```

### Adjacent Gate

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  tests/test_save_manager.py \
  tests/test_mcp_transcript.py \
  tests/test_surface_inventory.py \
  tests/test_cross_campaign_model_smoke.py \
  tests/test_cross_campaign_context_smoke.py \
  tests/test_current_native_visibility.py \
  tests/test_current_native_write_safety.py \
  -p no:cacheprovider
```

## Dev Notes

### 当前可复现基线

- Story 基线 `HEAD` / `origin/main`：`0496842947a0eba0f614afcd4c0a7c044f797268`（Story 3.8）。工作树已有用户批准的 Correct Course、Iteration 3/4 rebaseline、Test Review/Trace/gate、reports 与 automation support；全部保留并从 Story 6.8 commit 排除。
- 现有 `serve_mcp()` 已通过 `FastMCP.run(transport="stdio")` 提供真实 server；CLI 已暴露 `mcp serve --transport stdio`，CI 安装 `.[dev,mcp]`。本 Story没有预设 production defect。
- 现有 `tests/test_mcp_adapter.py` 使用 FakeFastMCP 或 adapter 直调；`tests/test_mcp_transcript.py` 验证静态 transcript normalization，都不能证明真实 subprocess/stdin/stdout JSON-RPC。
- 本地 system `python3` 已安装项目兼容的 MCP SDK，可真实执行 `ClientSession`/`stdio_client`；仓库 `.venv` 未安装 mcp extra。CI 仍以 `.[dev,mcp]` 为依赖权威，不新增依赖或 lockfile 变更。
- 官方 MCP Python SDK 将 `StdioServerParameters`、`stdio_client` 与 `ClientSession` 作为标准 stdio client lifecycle；Story 实现应沿用该公开 API，并用 context manager 确保 teardown。

### Architecture Compliance

- 权威链保持：`AI proposes. Kernel verifies. Player confirms. Engine commits.`
- MCP fixture 只负责真实 transport 与可复现观察，不成为事实、validation、confirmation 或 commit owner；所有业务结果继续来自 `AIGMMCPAdapter -> SaveManager -> GMRuntime/Kernel`。
- `intent_manifest` 只读；contract mismatch 必须先于 internal helper、routing、pending 与事实写入。refresh 语义是重新取 manifest 后整体 regenerate candidate。
- Player profile 仅允许 player-safe tool registration；fixture 不通过 developer profile 获取低层能力，也不把 hidden/GM-only 置入 transcript oracle。
- Audit 是脱敏、可丢失的 evidence；不得影响 tool result、profile gate、pending、确认或事实。Story 6.7 的 normalized reconstruction summary 继续独立规划。
- Campaign 是不可变规则/内容包，Save 是可变运行态；夹具只复制 Campaign 并写 temporary Save，不可把 runtime state 写回 source Campaign 或 formal Save。

### Existing Code: Current / Change / Preserve

- `rpg_engine/mcp_adapter.py` / `rpg_engine/cli_v1.py`
  - Current：已有 player/developer profile、真实 stdio、manifest、turn/confirm、audit 与 CLI entrypoint。
  - Change：仅允许在 `mcp_adapter.py` canonical audit sanitizer 对 `session_id` 做批准hash/摘要；除此之外只有真实wire test复现明确provider defect时才做最小修复。
  - Preserve：tool registration owner、thin-adapter 结构、path confinement、audit sanitizer 与 authority gates。
- Compatibility fixture/tests
  - Change：新增独立 helper、data-driven script 与 focused real-stdio test；使用当前 Python 启动 server，确保 external Hermes CI 可从检出的 RPG Engine 仓库消费。
  - Preserve：不依赖未跟踪 `tests/conftest.py`、`tests/automation_support/hermes_actual.py`、`system_journeys.py` 或真实模型/API key。
- CI
  - Current：full pytest 已收集 tests，且 workflow 安装 `.[dev,mcp]`。
  - Change：一般不改 `.github/workflows/ci.yml`；若需单独可见 gate，也只能添加 provider-focused step，不得加入 Hermes binary/client/reconnect 状态。

### Expected File Scope

- NEW：`tests/compatibility/hermes_stdio_provider.py`。
- NEW：`tests/fixtures/hermes_stdio_compatibility.yaml`。
- NEW：`tests/test_hermes_stdio_compatibility.py`。
- UPDATE：`rpg_engine/mcp_adapter.py`、`tests/test_mcp_adapter.py`（仅 raw confirmation `session_id` audit sanitizer 与回归）。
- UPDATE：`docs/mcp-contracts.md`、`docs/testing-and-quality-gates.md`；必要时才更新 `docs/component-inventory.md` / `docs/index.md`。
- UPDATE（BMAD）：本 Story、validation report、`sprint-status.yaml`。
- 通常不改：除上述audit sanitizer外的production MCP、SaveManager/Runtime、schema/migration、dependencies/lockfile、CI、Hermes repo、Stories 6.5–6.7/6.9、现有dirty planning/test artifacts与automation/rebaseline files。

### Testing Requirements

- Focused：真实 initialize/list/call wire path、player surface、manifest identity、stale rejection/refresh、turn/confirm/replay、safe audit、timeout/teardown 与 temp-only writes。
- Adjacent：MCP adapter、intent manifest/external ingress、SaveManager confirmation、transcript、surface inventory、cross-Campaign 与 current-native visibility/write safety。
- Protected data：source minimal Campaign、formal current Campaign/Save、正式 registry和SQLite只允许读取 fingerprint；任何测试写都必须先复制到独立 temporary root。
- Final clean-diff gates：focused、adjacent、两个 canonical Campaign validate/test、Markdown links、全仓 py_compile、full Ruff、`git diff --check`、repository full pytest；任何 review patch 后重跑所有受影响或失效的 gate。

## Project Structure Notes

- fixture 放在 test-owned compatibility boundary，跨仓使用方可检出本仓后读取稳定脚本/启动描述，但不会扩大安装包 production API。
- scripted model contract 应描述数据与步骤，不把 Story 专用玩家短句或测试分支写入 `mcp_adapter.py`、SaveManager 或 Runtime。
- 若实施发现必须修改 Hermes、增加依赖/migration、改变 player surface/authority，或必须先完成 Story 6.7 的新 audit 语义，按 HALT 条件停止并提供证据；当前规划与真实 stdio原型未发现该 blocker。

## References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Story 6.8]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md` — D8 / Story 6.8 / H1–H4 ownership]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-17.md` — scope guard / Hermes H2-H4 / dirty worktree ownership]
- [Source: `docs/project-context.md` — fact authority / AI / hidden / package boundaries]
- [Source: `docs/architecture.md` — MCP thin-adapter and player-safe authority chain]
- [Source: `docs/mcp-contracts.md` — profiles / manifest / refresh / audit / path contract]
- [Source: `docs/ai-intent-chain.md` — external candidate ingress and player confirmation]
- [Source: `docs/save-and-campaign-packages.md` — Campaign/Save ownership and temporary copies]
- [Source: `docs/testing-and-quality-gates.md` — canonical gates and high-risk review]
- [Source: `rpg_engine/mcp_adapter.py` — `serve_mcp`, player tools, audit owner]
- [Source: `rpg_engine/intent_manifest.py` — deterministic manifest identity]
- [Source: `rpg_engine/ai_intent/external.py` — strict external contract validation]
- [Source: `rpg_engine/save_manager.py` — pending/confirmation owner]
- [Source: `tests/helpers.py` — temporary package/fingerprint helpers]
- [Source: `https://github.com/modelcontextprotocol/python-sdk` — official stdio client/server API]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Create Story transport probe：system `python3` 通过 `StdioServerParameters -> stdio_client -> ClientSession` 成功 initialize、列出 player profile 工具并调用真实 `intent_manifest`；provider subprocess正常 teardown。
- Create Story code trace：`python -m rpg_engine mcp serve` → `serve_mcp()` → `FastMCP.run(stdio)` → `AIGMMCPAdapter` → `SaveManager/GMRuntime`。
- Validate Story wire probe：temporary registry active Save下stale contract与live turn均符合预期；携带platform identity的valid turn因MCP `player_confirm`只转发`session_id`而不可确认，故脚本把identity hash canary限定在stale路径。
- Dev Story Task 1 RED：`tests/test_hermes_stdio_compatibility.py` 初始 `2 failed`，均因 `tests.compatibility.hermes_stdio_provider` 尚不存在；实现fixture/YAML后 `2 passed`。
- Dev Story Task 2 RED：新增real stdio test初始 `1 failed, 2 passed`，缺少`stdio_server_parameters()`；补充wire parameter/decoder后暴露StringIO无fileno并修正为真实temporary file，最终`3 passed`。
- Dev Story Task 3 RED：完整wire流程先因fingerprint/hook helpers缺失失败；补齐后精确复现audit raw wrong/correct `session_id`泄露。最小sanitizer patch后Task 3 + adapter regression `2 passed`。

### Implementation Plan

- RED：新增真实 stdio focused test，证明现有测试未覆盖 wire lifecycle、stable handoff 与正式数据 fingerprint。
- GREEN：仅新增 test-owned fixture/scripted contract，复用 production CLI；真实测试如暴露 defect，再修 canonical owner。
- REFACTOR：固定 bounded transcript 与跨仓 ownership 文档，不创建第二套业务规则。
- VERIFY：focused/adjacent/package/docs/static/full suite，之后三路 fresh review持续自动收敛。
- Task 1实现：test-owned dataclass launcher + temporary active Save bootstrap + socket deny `sitecustomize` + versioned YAML/whole-candidate builder；不新增production API或依赖。
- Task 2实现：官方SDK真实initialize/list/call、精确player tool清单、TextContent JSON object解码、15秒bounded lifecycle、stderr parse guard与stale→refresh whole-candidate证明。
- Task 3实现：SQLite/events/pending/receipt状态快照、wrong/commit/replay exact oracles、portable protected-tree fingerprints、bounded hook projection与canonical `session_id` audit hash。
- Task 4实现：MCP canonical contract登记fixture消费/脚本/审计/ownership，quality gates登记真实wire/temp/network/fingerprint oracle，component inventory登记test-owned入口；无需新增canonical doc，故`docs/index.md`保持不变。

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created。
- Task 1完成：fixture仅写temporary root，source Campaign fingerprint不变；player profile与所有AI helper显式off，脚本合同固定9步actor/tool/capture/expect顺序及bounded hook字段。Focused `2 passed`，py_compile/Ruff/diff-check通过；用户worktree full suite `1623 passed, 10331 subtests`。
- Task 2完成：真实FastMCP stdio subprocess暴露精确13个player-safe工具，low-level工具缺席；manifest identity稳定，stale candidate返回typed refresh合同且无网络尝试。Focused `3 passed`，static checks通过；用户worktree full suite `1624 passed, 10331 subtests`。
- Task 3完成：stale/wrong确认零事实与确认状态写入；valid turn仅建pending，confirm精确+1 turn/+1 event，replay幂等。Audit所有raw canary缺席且session key/id均hash；source/formal fingerprints不变、network尝试为零。Focused `39 passed, 8 subtests`，static checks通过；用户worktree full suite `1626 passed, 10331 subtests`。
- Task 4完成：同步MCP/quality/component三份canonical docs，明确RPG Engine provider与Hermes client lifecycle owner；213个Markdown本地链接通过，diff/Ruff通过，用户worktree full suite `1626 passed, 10331 subtests`。
- Task 5完成：12轮三路fresh review持续收敛，共应用41个去重有效patch；第12轮Blind Hunter、Edge Case Hunter、Acceptance Auditor均clean。保留1项已记录PID reuse/process-group defer；no-network Decision按用户方案1收窄为CPython socket/DNS与实际provider路径证据。
- 最终clean diff门禁：focused `137 passed, 163 subtests`；adjacent `87 passed, 9167 subtests`；两套Campaign validate/test均`OK`；213个Markdown links、全仓py_compile、full Ruff与diff-check通过；repository full pytest `1632 passed, 10342 subtests`。

### File List

- `_bmad-output/implementation-artifacts/6-8-rpg-engine-compatibility-fixture-for-hermes-stdio-e2e.md`
- `_bmad-output/implementation-artifacts/6-8-rpg-engine-compatibility-fixture-for-hermes-stdio-e2e.validation-report.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `tests/compatibility/__init__.py`
- `tests/compatibility/hermes_stdio_provider.py`
- `tests/fixtures/hermes_stdio_compatibility.yaml`
- `tests/test_hermes_stdio_compatibility.py`
- `rpg_engine/mcp_adapter.py`
- `tests/test_mcp_adapter.py`
- `docs/mcp-contracts.md`
- `docs/testing-and-quality-gates.md`
- `docs/component-inventory.md`

## Change Log

- 2026-07-18：创建 Story 6.8，锁定真实 stdio provider fixture、deterministic scripted contract、temporary-data isolation 与 RPG Engine/Hermes CI ownership；状态设为 `ready-for-dev`。
- 2026-07-19：用户选择validation方案2；允许最小canonical `session_id` audit摘要patch，Story 6.7完整审计重构仍保持独立backlog，并吸收script schema、active Save bootstrap、socket deny与portable fingerprint增强。
- 2026-07-19：完成Task 1，新增test-owned temporary provider fixture、offline stdio launcher、network deny oracle与versioned scripted-model contract。
- 2026-07-19：完成Task 2，以官方MCP client锁定真实stdio player surface、manifest identity、stale rejection与refresh regeneration。
- 2026-07-19：完成Task 3，锁定pending/confirm/replay/no-mutation/protected fingerprints，并最小修复MCP audit raw `session_id`。
- 2026-07-19：完成Task 4，发布canonical fixture/handoff/quality contract并登记compatibility component。
- 2026-07-19：完成Task 5，12轮三路fresh review收敛至clean，41个有效patch全部应用，required gates全绿；Story与sprint状态设为`done`，Epic 6因6.5–6.7仍为backlog而保持`in-progress`。
