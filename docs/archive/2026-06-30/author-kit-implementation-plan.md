# AIGM Author Kit Implementation Plan

文档状态：**READY FOR DEVELOPMENT：可按步骤直接开工的实现计划**  
日期：2026-06-30  
设计来源：[`author-kit-design.md`](author-kit-design.md)  
相关文档：[`ux-design.md`](ux-design.md)、[`../../specs/campaign-package.md`](../../specs/campaign-package.md)、[`../../specs/cli.md`](../../specs/cli.md)、[`../../../README.md`](../../../README.md)、[`../../../pyproject.toml`](../../../pyproject.toml)

## 1. 判断结论

Author Kit 的设计目标已经明确：

- 服务对象是剧本作者，不是玩家。
- 目标是降低 Campaign Package 创作、检查、维护成本。
- 第一阶段是内核自带作者工具层，不是独立 Web App，也不是内置 AI 编剧器。
- 作者可以借助外部 AI，但 AIGM Kernel 不依赖外部 AI。
- 输出必须继续落到可校验的 Campaign Package，而不是自然语言世界书。

边界已经清晰：

- Author Kit 管 Campaign Package 的创建、诊断、总览、模板和作者文档。
- Player UX 管游玩时自然语言输入、repair options、preview/commit。
- Save Package 管某次游玩的运行态事实和归档。
- Legacy/Admin 工具继续保留，但不作为普通作者主入口。

开发路径已经清晰：

```text
P0 文档和模板
  -> P1 campaign new + doctor
  -> P2 outline + explain + AI 辅助闭环
  -> P3 split/check-ai/高级维护
  -> 全量测试和发布验收
```

本计划把上述路径拆成可以直接执行的开发任务。

## 2. 最小交付范围

V1.1 最小可交付版本必须包含：

```text
AUTHOR_GUIDE.md
AUTHOR_AI_PROMPT.md
examples/blank_campaign
examples/small_cn_campaign
rpg_engine/resources/examples/blank_campaign
rpg_engine/resources/examples/small_cn_campaign
aigm campaign new
aigm campaign doctor
aigm campaign outline
tests/test_author_kit_new.py
tests/test_author_kit_doctor.py
tests/test_author_kit_outline.py
README / CLI_SPEC / CAMPAIGN_SPEC 更新
pyproject.toml package-data 更新
```

`campaign explain`、`campaign check-ai`、`campaign split --dry-run` 可以作为 P2/P3，但本计划仍给出实现细节，避免后续再重新设计。

## 3. 代码结构

新增模块：

```text
rpg_engine/authoring/
  __init__.py
  templates.py
  doctor.py
  outline.py
  explain.py
  split.py
```

职责：

| 文件 | 职责 |
|---|---|
| `templates.py` | 模板复制、id/name 替换、资源发现、`campaign new` 服务函数 |
| `doctor.py` | 作者诊断模型、validate 包装、额外质量检查、markdown/json 渲染 |
| `outline.py` | 读取 Campaign Package 并生成作者总览 markdown/json |
| `explain.py` | capability、字段、错误码解释 |
| `split.py` | 大文件拆分建议，V1.1 只做 dry-run |

修改模块：

| 文件 | 修改 |
|---|---|
| `rpg_engine/cli_v1.py` | 增加 `campaign new/doctor/outline/explain/check-ai/split` parser 和 handler |
| `rpg_engine/resource_paths.py` | 增加通用 `copy_packaged_campaign_template()` 或复用并泛化 `copy_packaged_example()` |
| `pyproject.toml` | 打包 `blank_campaign`、`small_cn_campaign`、作者文档模板 |
| `README.md` | 增加作者入口 |
| `CLI_SPEC.md` | 增加 Author Kit 命令 |
| `CAMPAIGN_SPEC.md` | 区分最小结构、推荐结构、高级结构、生成物边界 |

新增公开文档：

```text
AUTHOR_GUIDE.md
AUTHOR_AI_PROMPT.md
AUTHOR_MAINTENANCE.md
AUTHOR_EXAMPLES.md
```

V1.1 必须完成 `AUTHOR_GUIDE.md` 与 `AUTHOR_AI_PROMPT.md`；`AUTHOR_MAINTENANCE.md`、`AUTHOR_EXAMPLES.md` 可先建立骨架。

## 4. 资源与打包

当前 `pyproject.toml` 只打包：

```toml
"rpg_engine.resources" = [
  "migrations/*.sql",
  "schemas/*.json",
  "examples/v1_minimal_adventure/**/*.yaml",
  "examples/v1_minimal_adventure/**/*.md",
]
```

Author Kit 必须扩展为：

```toml
"rpg_engine.resources" = [
  "migrations/*.sql",
  "schemas/*.json",
  "examples/v1_minimal_adventure/**/*.yaml",
  "examples/v1_minimal_adventure/**/*.md",
  "examples/blank_campaign/**/*.yaml",
  "examples/blank_campaign/**/*.md",
  "examples/small_cn_campaign/**/*.yaml",
  "examples/small_cn_campaign/**/*.md",
]
```

如果后续增加 `advanced_cn_campaign`，同步追加 package-data。

资源目录要求：

```text
examples/blank_campaign/**
examples/small_cn_campaign/**
rpg_engine/resources/examples/blank_campaign/**
rpg_engine/resources/examples/small_cn_campaign/**
```

仓库根 `examples/` 用于源码用户和文档；`rpg_engine/resources/examples/` 用于 pip/pipx 安装后 `campaign new` 和 `copy-example`。

验收：

```bash
python3 -m rpg_engine campaign new /tmp/aigm-small-cn --template small-cn --format json
python3 -m rpg_engine campaign validate /tmp/aigm-small-cn
python3 -m rpg_engine campaign test /tmp/aigm-small-cn
```

## 5. 模板内容

### 5.1 `blank_campaign`

目标：极简、可运行、适合高级作者改造。

目录：

```text
campaign.yaml
AUTHOR_NOTES.md
AUTHOR_AI_PROMPT.md
content/entities.yaml
content/rules.yaml
content/clocks.yaml
content/random_tables.yaml
content/world_settings.yaml
prompts/gm.md
templates/action.md
templates/query.md
tests/smoke.yaml
```

能力：

```yaml
capabilities:
  - query
  - rest_time
```

内容最小对象：

- `loc:start`
- `pc:player`
- `rule:player-agency`
- `clock:pressure`
- `table:minor-detail`

Smoke：

- `query-scene`
- `rest-preview`

### 5.2 `small_cn_campaign`

目标：普通中文作者复制后能理解和改写。

目录推荐结构：

```text
campaign.yaml
AUTHOR_NOTES.md
AUTHOR_AI_PROMPT.md
content/world_settings.yaml
content/locations.yaml
content/characters.yaml
content/items.yaml
content/projects.yaml
content/rules.yaml
content/clocks.yaml
content/random_tables.yaml
prompts/gm.md
templates/action.md
templates/query.md
tests/smoke.yaml
```

能力：

```yaml
capabilities:
  - query
  - explore
  - social
  - travel
  - random_table
  - clue
  - risk
  - inventory_resource
  - project_task
  - rest_time
```

建议内容：

- 起始地点：`loc:start-village` 或 `loc:camp`
- 相邻地点：`loc:old-road`、`loc:watch-hill`
- 玩家：`pc:traveler`
- NPC：`npc:guide-lin`、`npc:merchant-qiao`
- 物品：`item:rations`、`item:rope`
- 项目：`project:repair-signal` 或 `project:find-water`
- 规则：玩家能动性、资源消耗、风险递进
- 进度钟：天气压力、营地怀疑
- 随机表：旅途细节、营地传闻

Smoke：

- `query-scene`
- `query-npc`
- `preview-explore`
- `preview-travel`
- `preview-rest`
- `random-table`

### 5.3 模板替换规则

`campaign new` 支持：

```bash
--id my-story
--name "我的剧本"
```

替换范围：

- `campaign.yaml.id`
- `campaign.yaml.name`
- `AUTHOR_NOTES.md` 标题
- `prompts/gm.md` 标题或首段

不得做复杂语义替换。模板内容本身保持稳定，避免脚手架不可预测。

## 6. `campaign new`

### 6.1 CLI

```bash
aigm campaign new TARGET_DIR --template small-cn --id my-story --name "我的剧本" --force --format json
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `target_dir` | 必填 | 新剧本目录 |
| `--template` | `small-cn` | `blank`、`small-cn`、后续 `small-en`、`advanced-cn` |
| `--id` | 从目录名推导 | 必须匹配 campaign id 规则 |
| `--name` | 从模板默认 | 显示名称 |
| `--force` | false | 允许覆盖非空目录 |
| `--format` | markdown | markdown/json |

### 6.2 服务函数

建议 API：

```python
def create_campaign_from_template(
    template: str,
    target: str | Path,
    *,
    campaign_id: str | None = None,
    name: str | None = None,
    force: bool = False,
) -> AuthorTemplateResult:
    ...
```

`AuthorTemplateResult`：

```python
@dataclass(frozen=True)
class AuthorTemplateResult:
    ok: bool
    template: str
    target_dir: str
    campaign_id: str
    name: str
    files_written: tuple[str, ...]
    next_steps: tuple[str, ...]
    errors: tuple[str, ...] = ()
```

### 6.3 错误处理

必须处理：

- 模板不存在。
- 目标目录非空且未 `--force`。
- 目标路径是文件且未 `--force`。
- `--id` 非法。
- 模板复制后 `campaign validate` 失败。

错误输出 JSON：

```json
{
  "ok": false,
  "template": "small-cn",
  "target_dir": "/tmp/x",
  "errors": ["target directory is not empty: /tmp/x"]
}
```

### 6.4 验收

```bash
python3 -m rpg_engine campaign new /tmp/aigm-author-new --template small-cn --format json
python3 -m rpg_engine campaign validate /tmp/aigm-author-new
python3 -m rpg_engine campaign test /tmp/aigm-author-new
```

测试：

- `test_campaign_new_creates_valid_small_cn`
- `test_campaign_new_creates_valid_blank`
- `test_campaign_new_rejects_non_empty_target_without_force`
- `test_campaign_new_force_replaces_target`
- `test_campaign_new_overrides_id_and_name`
- `test_campaign_new_json_shape_is_stable`

## 7. `campaign doctor`

### 7.1 CLI

```bash
aigm campaign doctor CAMPAIGN_DIR --strict --format json
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `campaign_dir` | 必填 | 剧本目录 |
| `--strict` | false | warning 也导致非 0 |
| `--format` | markdown | markdown/json |

### 7.2 诊断模型

新增：

```python
@dataclass(frozen=True)
class AuthorRepairOption:
    label: str
    kind: str = "manual_edit"
    example: str = ""

@dataclass(frozen=True)
class AuthorIssue:
    severity: str
    code: str
    title: str
    message: str
    why_it_matters: str
    file: str = ""
    path: str = ""
    repair_options: tuple[AuthorRepairOption, ...] = ()
    raw_message: str = ""

@dataclass(frozen=True)
class AuthorDoctorResult:
    ok: bool
    status: str
    campaign_id: str
    errors: int
    warnings: int
    suggestions: int
    issues: tuple[AuthorIssue, ...]
```

`ok` 规则：

- 默认：无 `error` 即 `ok=true`。
- `--strict`：无 `error` 且无 `warning` 才 `ok=true`。

### 7.3 诊断来源

`doctor` 必须复用：

- `validate_campaign_package()`
- `issues_from_messages()`
- `run_campaign_smoke_tests()` 可选，不在 V1.1 默认跑全 smoke，避免 doctor 太慢；可后续增加 `--run-smoke`

额外检查：

1. Save Package 误传检查。
2. 生成物目录混入检查。
3. 运行态字段在 Campaign Package `campaign.yaml` 中出现。
4. 推荐结构检查。
5. 大文件检查。
6. Python/plugin 文件检查。
7. 中文作者友好 alias 检查。
8. 起始场景可玩性检查。
9. capability smoke 覆盖提示。
10. `AUTHOR_NOTES.md` / `AUTHOR_AI_PROMPT.md` 缺失提示。

### 7.4 具体检查规则

#### Save Package 误传

条件：

- 存在 `save.yaml`。
- 存在 `data/game.sqlite`。

输出 `error`：

```text
这个目录看起来是 Save Package，不是 Campaign Package。
```

repair options：

- 运行 `aigm save validate <dir>`。
- 打开 `save.yaml.source_campaign_path` 找来源剧本。
- 如果要维护存档，使用 `aigm save patch` 或 `play commit`。

#### 生成物目录混入

目录：

```text
data/
cards/
snapshots/
memory/
reports/
backups/
```

在 Campaign Package 中出现时输出 `warning`。

#### 运行态字段泄漏

`campaign.yaml` 中出现：

```text
database
events
current_snapshot
current_snapshot_json
cards
```

输出 `suggestion` 或 `warning`：

- 对官方旧示例兼容，可先设为 `suggestion`。
- 新模板不应包含这些字段。

#### 大文件

规则：

- YAML 文件超过 2000 行：`warning`
- YAML 文件超过 800 行：`suggestion`

repair：

- 按 `locations/characters/items/rules/clocks/random_tables` 拆分。

#### 中文 alias

如果检测到中文剧本：

- `name` 或 `summary` 包含 CJK。
- 重要 known 实体没有 `aliases`。

输出 `suggestion`：

- 为地点、NPC、项目、物品添加短别名。

#### 起始场景可玩性

必须能找到：

- `initial_location_id` 指向 known location。
- `defaults.player_entity_id` 指向 player entity。
- 起始地点有 summary。
- 起始地点至少具备 NPC、出口、资源、项目、线索之一。

缺失为 `warning` 或 `error`，依赖是否影响 validate。

### 7.5 Markdown 输出

格式：

```text
# Campaign Doctor

- status: `OK|NEEDS_FIX|WARNINGS`
- campaign: `my-story`
- errors: 0
- warnings: 2
- suggestions: 4

## Errors
...

## Warnings
...

## Suggestions
...

## Next Steps
1. 修复 Errors。
2. 重新运行 `aigm campaign doctor ...`。
3. 运行 `aigm campaign test ...`。
```

### 7.6 验收

```bash
python3 -m rpg_engine campaign doctor ./examples/small_cn_campaign
python3 -m rpg_engine campaign doctor ./examples/small_cn_campaign --format json
```

测试：

- `test_doctor_ok_for_small_cn`
- `test_doctor_reports_validate_errors_with_repair_options`
- `test_doctor_detects_save_package`
- `test_doctor_warns_generated_dirs_in_campaign`
- `test_doctor_warns_large_yaml`
- `test_doctor_strict_fails_on_warnings`
- `test_doctor_json_shape_is_stable`

## 8. `campaign outline`

### 8.1 CLI

```bash
aigm campaign outline CAMPAIGN_DIR --format markdown
```

参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `campaign_dir` | 必填 | 剧本目录 |
| `--format` | markdown | markdown/json |
| `--view` | author | 预留：`author`、`debug` |

### 8.2 输出内容

Markdown：

```text
# Campaign Outline: 名称

## Package
- id
- version
- capabilities

## Start
- player
- initial location
- initial time

## Content Counts
...

## Key Locations
...

## Key Characters
...

## Rules
...

## Clocks
...

## Random Tables
...

## Smoke Coverage
...

## Maintenance Notes
...
```

JSON：

```json
{
  "campaign_id": "my-story",
  "name": "我的剧本",
  "package_version": "0.1.0",
  "capabilities": ["query"],
  "start": {
    "player_entity_id": "pc:traveler",
    "initial_location_id": "loc:start"
  },
  "counts": {
    "location": 3,
    "character": 2
  },
  "smoke_coverage": {
    "query": true,
    "travel": false
  },
  "maintenance_notes": []
}
```

### 8.3 数据加载策略

优先复用 `campaign_validation` 的内容读取函数。如果当前函数不方便复用，可以先在 `outline.py` 内部读取 YAML：

- `campaign.yaml.content.entities`
- `relationships`
- `rules`
- `clocks`
- `world_settings`
- `random_tables`
- `tests/smoke.yaml`

V1.1 不需要初始化 SQLite。`outline` 应是纯文件读取，避免产生运行态文件。

### 8.4 Hidden 信息处理

默认 `author` 视图可以统计 hidden，但不要展开 hidden 详细内容。

规则：

- known/hinted：可显示 name、summary。
- hidden：只显示 id、type、visibility。
- debug：可显示全部。

测试必须覆盖 hidden summary 不进入默认 markdown。

### 8.5 验收

```bash
python3 -m rpg_engine campaign outline ./examples/small_cn_campaign
python3 -m rpg_engine campaign outline ./examples/small_cn_campaign --format json
```

测试：

- `test_outline_markdown_contains_start_and_counts`
- `test_outline_json_shape_is_stable`
- `test_outline_does_not_expand_hidden_summary`
- `test_outline_has_smoke_coverage`

## 9. `campaign explain`

### 9.1 CLI

```bash
aigm campaign explain field:visibility
aigm campaign explain capability:combat
aigm campaign explain error:MISSING_REFERENCE
```

### 9.2 实现

静态映射即可，不需要复杂系统：

```python
EXPLANATIONS = {
  "field:visibility": "...",
  "capability:combat": "...",
  "error:MISSING_REFERENCE": "...",
}
```

支持：

- `field:visibility`
- `field:summary`
- `field:aliases`
- `field:location_id`
- `capability:*`
- `error:*`

未知 key 返回可用 key 列表。

### 9.3 验收

```bash
python3 -m rpg_engine campaign explain field:visibility
```

测试：

- `test_explain_visibility`
- `test_explain_unknown_key_lists_candidates`

## 10. `campaign check-ai`

V1.1 可不实现独立命令；也可以作为 `doctor` 的一组 issue code。建议 V1.2 独立。

若实现：

```bash
aigm campaign check-ai CAMPAIGN_DIR --format json
```

检查：

- CJK 剧本缺 alias。
- hidden 内容出现在 known summary。
- 大段 prose details。
- 规则/world_setting 重复标题。
- smoke contains 太泛。
- 未确认信息没有放在 unknowns/hinted。

返回结构复用 `AuthorDoctorResult`。

## 11. `campaign split`

V1.1 只做 dry-run。

```bash
aigm campaign split CAMPAIGN_DIR --by type --dry-run
```

输出：

```text
# Campaign Split Plan

content/entities.yaml -> content/locations.yaml
content/entities.yaml -> content/characters.yaml
content/entities.yaml -> content/items.yaml
...
```

JSON：

```json
{
  "ok": true,
  "dry_run": true,
  "moves": [
    {
      "source": "content/entities.yaml",
      "target": "content/locations.yaml",
      "record_ids": ["loc:start"]
    }
  ]
}
```

不执行写入，避免自动重排造成大量 diff。V1.2 再加 `--apply`。

## 12. 文档任务

### 12.1 `AUTHOR_GUIDE.md`

必须包含：

1. 作者只需要知道什么。
2. Campaign Package vs Save Package。
3. 推荐工作流。
4. 如何创建模板。
5. 如何写地点、角色、物品、规则、进度钟、随机表。
6. 如何用 AI 辅助。
7. 如何运行 `doctor`、`outline`、`test`。
8. 常见错误。
9. 不要编辑哪些文件。

长度控制：普通作者文档不要超过约 300 行。

### 12.2 `AUTHOR_AI_PROMPT.md`

必须包含：

- AI 角色。
- 可编辑文件。
- 不可编辑文件。
- ID 命名。
- YAML 输出约束。
- repair loop。
- hidden/hinted/known 规则。
- smoke test 要求。

该 prompt 要适合直接复制给外部 AI。

### 12.3 `CAMPAIGN_SPEC.md`

更新：

- `V1 最小结构`
- `推荐作者结构`
- `高级拆分结构`
- `作者不应编辑的生成物`
- `campaign.yaml` 中运行态路径字段说明：兼容可用，但新作者模板不应暴露。

### 12.4 `README.md`

增加：

```bash
aigm campaign new ./campaigns/my-story --template small-cn
aigm campaign doctor ./campaigns/my-story
aigm campaign outline ./campaigns/my-story
aigm campaign test ./campaigns/my-story
```

### 12.5 `CLI_SPEC.md`

增加 Author Kit 命令说明。

## 13. 测试文件

新增：

```text
tests/test_author_kit_new.py
tests/test_author_kit_doctor.py
tests/test_author_kit_outline.py
tests/test_author_kit_explain.py
```

可选：

```text
tests/test_author_kit_split.py
tests/test_author_ai_prompt_contract.py
```

### 13.1 测试辅助

复用 `tests/test_v1_cli.py` 的 `run_cli()` 模式。

新增临时目录测试，不写仓库状态。

### 13.2 必测用例

`test_author_kit_new.py`：

- small-cn 模板生成后 validate/test 通过。
- blank 模板生成后 validate/test 通过。
- `--id` 和 `--name` 替换正确。
- 非空目录未 `--force` 失败。
- `--force` 覆盖成功。
- JSON 输出包含 `ok/template/target_dir/campaign_id/files_written/next_steps`。

`test_author_kit_doctor.py`：

- small-cn doctor OK。
- 缺 initial location 产生 error 和 repair options。
- 缺 smoke coverage 产生 error 或 warning。
- Save Package 误传产生清晰错误。
- 混入 `data/`、`cards/` 产生 warning。
- 大 YAML 产生 warning/suggestion。
- `--strict` 对 warning 返回非 0。

`test_author_kit_outline.py`：

- markdown 包含起始地点、玩家、counts。
- json counts 正确。
- hidden summary 默认不展开。
- smoke coverage 正确。

`test_author_kit_explain.py`：

- `field:visibility` 输出 known/hinted/hidden。
- `capability:combat` 输出 combat 解释。
- unknown key 返回候选。

## 14. 全量测试矩阵

每个开发阶段完成后至少运行：

```bash
python3 -m unittest tests.test_author_kit_new tests.test_author_kit_doctor tests.test_author_kit_outline -v
python3 -m unittest tests.test_v1_cli tests.test_campaign_validation tests.test_official_example -v
```

P0/P1 合并前运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/regression.py
python3 -m rpg_engine campaign validate ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign test ./examples/v1_minimal_adventure
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
```

安装打包验证：

```bash
python3 -m pip install -e .
python3 -m rpg_engine campaign new /tmp/aigm-author-install-test --template small-cn
python3 -m rpg_engine campaign test /tmp/aigm-author-install-test
```

如果环境允许，追加 pipx/venv 安装测试：

```bash
python3 -m venv /tmp/aigm-author-venv
/tmp/aigm-author-venv/bin/python -m pip install .
/tmp/aigm-author-venv/bin/aigm campaign new /tmp/aigm-author-venv-campaign --template small-cn
/tmp/aigm-author-venv/bin/aigm campaign test /tmp/aigm-author-venv-campaign
```

## 15. 开发顺序

### Step 1：资源模板和文档

文件：

- `AUTHOR_GUIDE.md`
- `AUTHOR_AI_PROMPT.md`
- `examples/blank_campaign/**`
- `examples/small_cn_campaign/**`
- `rpg_engine/resources/examples/blank_campaign/**`
- `rpg_engine/resources/examples/small_cn_campaign/**`
- `pyproject.toml`

验收：

```bash
python3 -m rpg_engine campaign validate ./examples/blank_campaign
python3 -m rpg_engine campaign test ./examples/blank_campaign
python3 -m rpg_engine campaign validate ./examples/small_cn_campaign
python3 -m rpg_engine campaign test ./examples/small_cn_campaign
```

### Step 2：`campaign new`

文件：

- `rpg_engine/authoring/__init__.py`
- `rpg_engine/authoring/templates.py`
- `rpg_engine/cli_v1.py`
- `tests/test_author_kit_new.py`

实现：

- 资源复制。
- id/name 替换。
- markdown/json 输出。
- force 行为。

验收：

```bash
python3 -m unittest tests.test_author_kit_new -v
```

### Step 3：`campaign doctor`

文件：

- `rpg_engine/authoring/doctor.py`
- `rpg_engine/cli_v1.py`
- `tests/test_author_kit_doctor.py`

实现：

- issue model。
- validate 包装。
- save package 检测。
- generated dirs 检测。
- runtime fields 检测。
- large file 检测。
- strict 模式。

验收：

```bash
python3 -m unittest tests.test_author_kit_doctor -v
```

### Step 4：`campaign outline`

文件：

- `rpg_engine/authoring/outline.py`
- `rpg_engine/cli_v1.py`
- `tests/test_author_kit_outline.py`

实现：

- 文件级 YAML 读取。
- counts。
- start 信息。
- key location/character 列表。
- smoke coverage。
- hidden summary 默认不展开。

验收：

```bash
python3 -m unittest tests.test_author_kit_outline -v
```

### Step 5：`campaign explain`

文件：

- `rpg_engine/authoring/explain.py`
- `rpg_engine/cli_v1.py`
- `tests/test_author_kit_explain.py`

实现：

- 静态解释表。
- unknown key 候选。
- markdown/json 输出。

验收：

```bash
python3 -m unittest tests.test_author_kit_explain -v
```

### Step 6：文档更新和入口收束

文件：

- `README.md`
- `CLI_SPEC.md`
- `CAMPAIGN_SPEC.md`
- 可选 `AIGM_KERNEL_REQUIREMENTS.md`

实现：

- 主路径加入 Author Kit。
- 普通作者工作流独立成节。
- 明确 legacy/admin 不属于普通作者入口。

验收：

```bash
python3 -m rpg_engine --help
python3 -m rpg_engine campaign --help
python3 -m rpg_engine campaign new --help
python3 -m rpg_engine campaign doctor --help
```

### Step 7：全量测试

运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/regression.py
```

再跑 CLI 端到端：

```bash
tmp="$(mktemp -d)"
python3 -m rpg_engine campaign new "$tmp/campaign" --template small-cn
python3 -m rpg_engine campaign doctor "$tmp/campaign"
python3 -m rpg_engine campaign outline "$tmp/campaign"
python3 -m rpg_engine campaign test "$tmp/campaign"
python3 -m rpg_engine save init "$tmp/campaign" "$tmp/save"
python3 -m rpg_engine save validate "$tmp/save"
```

## 16. 退出标准

Author Kit V1.1 完成必须满足：

- `campaign new --template small-cn` 创建后首次 `campaign test` 通过。
- `campaign doctor` 对普通问题给出 repair options。
- `campaign doctor --format json` 可被外部 AI 稳定读取。
- `campaign outline` 能让作者不用看 YAML 就理解剧本结构。
- 普通作者不需要理解 SQLite/MCP/delta/projection/migration。
- 新模板不暴露 `database/events/current_snapshot/cards` 运行态字段。
- `pyproject.toml` 打包资源完整，pip 安装后仍能创建模板。
- 全量 unittest 和 regression 通过。

## 17. 已知延期项

V1.2 或之后再做：

- `campaign split --apply`
- Web/UI 作者工具
- 编辑器插件
- 内置 AI 生成器
- package upgrade 自动迁移已有存档
- 高级引用图可视化
- 语义别名自动学习

这些不阻塞 V1.1 Author Kit 上线。

## 18. 开工检查清单

开始编码前确认：

- 本文档和 `AIGM_AUTHOR_KIT_DESIGN_2026-06-30.md` 都已提交或纳入变更。
- 当前 `python3 -m unittest discover -s tests -p 'test_*.py'` 基线通过，或已记录现有失败。
- 新模板内容先以源码 `examples/` 为准，再复制到 `rpg_engine/resources/examples/`。
- 每次新增资源目录后同步 `pyproject.toml`。
- 每个 CLI 新命令同时支持 markdown 和 json。
- 每个非 0 失败都要有机器可读错误。
- 不引入新的运行时依赖。

按本计划执行即可从文档设计直接进入实现。
