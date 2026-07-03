# AIGM Save Package Spec V1

文档状态：**V1 规范，已由 `aigm save init/inspect/validate/import/export/patch` 执行**  
适用范围：一次具体游玩的进度、事实状态、派生快照和可分享归档。  
边界：存档包不是剧本包，不内嵌完整剧本；剧情推进必须走结构化 delta。

## 1. 目标

Save Package 负责保存某次游玩进度。新游戏不要求用户提前准备存档；从 Campaign Package 运行：

```bash
aigm save init ./examples/v1_minimal_adventure ./saves/my-run
```

即可生成初始存档。

## 2. 目录结构

运行形态是目录：

```text
saves/my-run/
  campaign.yaml
  save.yaml
  data/
    game.sqlite
    events.jsonl
  snapshots/
    current.md
    current.json
  cards/
  memory/
```

权威事实源是 `data/game.sqlite`。`events.jsonl`、`snapshots/`、`cards/`、`memory/` 是可重建或可校验的运行产物。

## 3. save.yaml

`save init` 会生成：

```yaml
save_schema_version: "1"
campaign_id: v1-minimal-adventure
campaign_version: "0.1.0"
engine_version: "0.2"
source_campaign_path: ../v1-minimal-adventure
created_at: "..."
```

要求：

- `campaign_id` 必须记录来源剧本。
- `campaign_version` 必须记录来源剧本版本。
- `engine_version` 必须记录所需内核版本。
- `source_campaign_path` 推荐写成相对存档根目录的路径，便于剧本包和存档包并排移动、导入和分享。
- 导入别人存档前，应具备兼容剧本包；V1 `.aigmsave` 不承诺内嵌完整剧本内容。

`save init` 默认会把 `campaign.yaml.content.*` 写成相对存档根目录的本地内容路径。运行时也允许存档包通过 `save.yaml.source_campaign_path` 只读引用来源剧本包，并在 `campaign.yaml.content.*` 中使用指向该来源剧本包内部文件的相对路径。绝对 content 路径仍不允许；未落在存档根或已声明来源剧本根下的 content 路径必须被拒绝。

## 4. .aigmsave

分享形态是单文件归档：

```text
my-run.aigmsave
```

命令：

```bash
aigm save export ./saves/my-run --output ./my-run.aigmsave
aigm save import ./my-run.aigmsave ./saves/imported-run --yes
```

归档内必须包含 `save-archive.json` manifest。V1 当前会打包存在的核心文件：

- `campaign.yaml`
- `save.yaml`
- `data/game.sqlite`
- `data/events.jsonl`
- `package-lock.json`
- `snapshots/current.md`
- `snapshots/current.json`
- `cards/**`
- `memory/**`

`.aigmsave` 默认是完整存档，可能包含隐藏 GM 信息；玩家视角导出不属于 V1。

## 5. Inspect 与 Validate

```bash
aigm save inspect ./saves/my-run
aigm save validate ./saves/my-run
```

`inspect` 返回人类/AI 可读的当前状态摘要：

- campaign/save 路径。
- 当前 turn、地点、时间。
- entities、turns、events、clocks 数量。
- 核心文件是否缺失。
- 数据一致性错误。

`validate` 是只读深度校验；通过时输出 `OK`。V1 会检查：

- `save.yaml` 与 `campaign.yaml` 的 campaign/version/engine 兼容性。
- SQLite 必需表、migration 记录和基础一致性检查。
- 当前 turn/location/time 与 `snapshots/current.json` 是否一致。
- `events.jsonl` 是否为合法 JSONL、event_id 是否唯一、是否与 SQLite events 双向一致。
- `projection_state` 中 events_jsonl、search、snapshots、cards 是否 clean 且指向当前 turn。
- `cards/` 是否覆盖所有非归档实体，search FTS 数量是否匹配可见实体。
- outbox 是否仍有未完成投影任务。

## 6. Safe Patch

普通用户不直接编辑 SQLite。安全维护使用：

```bash
aigm save patch ./saves/my-run ./patch.json
```

patch 文件：

```json
{
  "patch_schema_version": "1",
  "reason": "fix typo and alias",
  "operations": [
    {
      "op": "set_entity_summary",
      "entity_id": "npc:warden-mira",
      "summary": "The camp warden who tracks risks and keeps the maps."
    },
    {
      "op": "add_entity_alias",
      "entity_id": "npc:warden-mira",
      "alias": "Mira"
    }
  ]
}
```

V1 允许的维护操作：

- `set_entity_name`
- `set_entity_summary`
- `set_entity_visibility`
- `add_entity_alias`
- `remove_entity_alias`
- `set_entity_detail`
- `remove_entity_detail`
- `set_character_field`，仅限 `attitude`、`trust`、`health_state`

V1 明确不允许通过 patch 推进剧情：

- 不创建 turn。
- 不写 event。
- 不 tick clock。
- 不改当前地点、当前时间、当前 turn。
- 不移动实体位置或归属。
- 不修改库存数量、资源消耗、项目进度等行动后果。

这些变化必须走 `play preview` -> `play validate-delta` -> `play commit --proposal-json`。

patch 成功后会自动备份，并刷新 search、snapshot 和 cards，让后续 query/context 立即读到维护结果。

## 7. Schema

规范文件：

```text
schemas/save_patch.schema.json
```
