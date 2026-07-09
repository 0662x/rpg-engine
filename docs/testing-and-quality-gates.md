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

写入安全和 validation cluster：

```bash
python3 -m pytest \
  tests/test_cross_layer_regression.py \
  tests/test_validation_pipeline.py \
  tests/test_projection_service.py \
  tests/test_save_manager.py
```

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
save package 或 source Campaign Package。完整 Context Slice、basic query 和 player-safe play loop
跨 Campaign 测试属于 context 集成 gate，不由这个 model-boundary smoke 代替。

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
- pending action session / concurrency 语义。
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
