# AIGM Player Entry 与 Save Manager 设计

文档状态：**DESIGN DRAFT：待实现的 V1.1 玩家入口规格**
适用范围：首次开始游戏、继续游戏、多存档管理、AI GM 新手引导和 MCP/CLI 玩家入口。
权威依赖：[`kernel-requirements.md`](kernel-requirements.md)、[`save-package.md`](save-package.md)、[`mcp-adapter.md`](mcp-adapter.md)、[`../prompts/ai-client-prompt.md`](../../../prompts/ai-client-prompt.md)。

## 1. 问题定义

当前 Kernel 已经具备核心能力：

- Campaign Package 定义剧情包。
- Save Package 保存一次游玩。
- `save init` 能从剧情包生成初始存档。
- `GMRuntime` 能对一个指定存档执行 `start_turn`、`query`、`preview_from_text`、`preview_action`、`validate_delta`、`commit_turn` 和 `health`；默认玩家包装层通过 `player_turn` 和 `player_confirm` 隐藏低层 delta/proposal。
- MCP 能对一个默认存档或显式传入的存档路径执行游玩工具。

缺口在玩家入口层：

- 玩家第一次和 AI GM 说“开始游戏”时，没有自动创建新存档的通用流程。
- 多存档只能靠路径手动切换，没有玩家可理解的“读取存档/切换存档”体验。
- 新手引导目前主要依赖 `query scene` 的可行动列表，还不是完整的首轮 onboarding。
- MCP 暴露的是运行工具，不暴露存档管理工具。
- 客户端配置只能指向一个 `default_save`，不能表达“当前激活存档”。

本设计的目标是补一个薄的 Player Entry / Save Manager 层，让普通玩家可以：

```text
安装内核 + 放入剧情包 + 对 AI GM 说开始游戏 = 自动建档并进入第一幕
```

## 2. 设计原则

### 2.1 不改坏现有 Kernel 边界

Save Manager 不应取代 `GMRuntime`，也不应直接推进剧情。它只负责选择、创建、登记和展示存档。

```text
AI Client / Hermes
        |
Player Entry / Save Manager
        |
GMRuntime
        |
Campaign Package + Save Package
```

普通玩家事实变化只允许走：

```text
player_turn -> player_confirm
```

developer/trusted 低层事实变化仍只允许走：

```text
preview_from_text -> validate_delta -> commit_turn(delta, turn_proposal)
```

### 2.2 玩家不应接触路径和内部术语

玩家看到的是：

```text
继续游戏
新游戏
读取存档
复制当前存档
导入存档
```

不是：

```text
campaign.yaml
save_dir
data/game.sqlite
delta
commit
```

技术路径仍保留给 CLI、debug 和维护流程。

### 2.3 首轮引导是第一幕，不是说明书

Onboarding 不应是一大段规则文档。它必须来自玩家视角的当前场景，并给出 3-5 个可以直接说出口的行动。

示例：

```text
你在林间空地醒来。现在是第1天清晨。
附近有夏娃、树屋、火坑、小溪方向和十六畦田地。

你可以直接说：
- 看看周围有什么
- 和夏娃说话
- 去小溪取水
- 盘点身上的东西
- 检查农田

我会先告诉你行动可能的风险和代价；你确认后，结果才会写进存档。
```

### 2.4 多存档是本地工作区能力，不是账号系统

V1.1 不引入账号、云同步、Web 后端、多人在线或市场。所有存档管理都在本地 `root` 下完成。

### 2.5 兼容现有存档

已经存在的 Save Package 不需要移动。Save Manager 可以把它们登记为已有存档。

## 3. 目标与非目标

### 3.1 目标

- 自动首启：没有激活存档时，根据剧情包自动创建新存档。
- 继续游戏：有激活存档时，自动 inspect + query scene。
- 多存档列表：显示可读标签、剧情包、当前时间、地点、turn、最后游玩时间和健康状态。
- 存档切换：用稳定 `save_id` 切换激活存档。
- 新游戏：为同一剧情包创建多个独立存档。
- Starter 支持：优先从作者打磨过的 starter save 复制新档；没有 starter 时回退到 `save init`。
- Onboarding：首启后生成面向玩家的第一幕引导。
- MCP 工具：让 AI 客户端不用直接读写文件也能管理存档。
- CLI 入口：提供可测试、可脚本化的参考实现。
- 安全：不覆盖已有存档，不删除存档，不让 registry 路径逃逸 root。

### 3.2 非目标

- 不做 Web UI。
- 不做账号、云同步、远程托管。
- 不做插件市场。
- 不做玩家视角 `.aigmsave` 脱敏导出。
- 不把 Save Manager 做成第二套剧情推进系统。
- 不把 starter save 混入 Campaign Package 的运行目录。
- 不要求所有旧存档迁移到新目录结构。

## 4. 工作区与目录约定

Save Manager 以 MCP/CLI 的 `root` 作为本地工作区边界。

推荐新工作区结构：

```text
workspace/
  campaigns/
    isekai-farm/
      campaign.yaml
      content/
  saves/
    isekai-farm/
      save-20260701-001/
        campaign.yaml
        save.yaml
        data/
        snapshots/
        cards/
  starters/
    isekai-farm/
      native-starter/
        campaign.yaml
        save.yaml
        data/
  .aigm/
    save-registry.json
    locks/
      save-registry.lock
```

兼容现有工作区时，registry 可以登记 root 下任意相对路径：

```text
workspace/
  isekai-farm-campaign-native-v1/
  isekai-farm-save-native-v1/
  isekai-farm-save-native-starter-v1/
  .aigm/
    save-registry.json
```

路径规则：

- registry 中所有路径必须是 root 相对路径。
- 禁止绝对路径。
- 禁止 `..`。
- 禁止 symlink 逃逸 root。
- Save Manager 所有文件操作必须 resolve 后确认仍在 root 下。

## 5. Registry 数据模型

Registry 文件：

```text
<root>/.aigm/save-registry.json
```

V1.1 schema：

```json
{
  "schema_version": "1",
  "active_save_id": "save_20260701_001",
  "campaigns": [
    {
      "id": "isekai-farm",
      "name": "万能农具 · 异世界悠闲农家",
      "path": "isekai-farm-campaign-native-v1",
      "starter_save_path": "isekai-farm-save-native-starter-v1",
      "last_validated_at": "2026-07-01T00:00:00Z",
      "status": "ok"
    }
  ],
  "saves": [
    {
      "id": "save_20260701_001",
      "campaign_id": "isekai-farm",
      "campaign_name": "万能农具 · 异世界悠闲农家",
      "path": "saves/isekai-farm/save-20260701-001",
      "label": "异世界悠闲农家 · 新游戏 1",
      "kind": "normal",
      "source": "starter_copy",
      "created_at": "2026-07-01T00:00:00Z",
      "last_played_at": "2026-07-01T00:00:00Z",
      "last_inspected_at": "2026-07-01T00:00:00Z",
      "current_turn_id": "turn:seed",
      "current_game_day": "1",
      "current_time_block": "第1天 · 清晨",
      "current_location_id": "loc:home-clearing",
      "current_location_name": "空地/家",
      "summary": "第1天清晨，位于空地/家。",
      "health": "ok",
      "archived": false
    }
  ]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `schema_version` | Registry schema 版本。 |
| `active_save_id` | 当前激活存档；可为 `null`。 |
| `campaigns` | Save Manager 已知剧情包。 |
| `campaigns[].starter_save_path` | 可选 starter save template 路径；没有时使用 `save init`。 |
| `saves` | 可游玩存档列表。 |
| `saves[].id` | 稳定存档 ID，不依赖目录名。 |
| `saves[].path` | root 相对 Save Package 路径。 |
| `saves[].kind` | `normal`、`test`、`starter_template`、`imported`、`archived`。 |
| `saves[].source` | `save_init`、`starter_copy`、`import`、`duplicate`、`adopted`。 |
| `health` | `ok`、`warning`、`error`、`unknown`。 |

Starter template 可以登记在 `campaigns[].starter_save_path`，不建议作为普通 `saves[]` 展示给玩家。

## 6. Save Manager 服务 API

内部 Python API 建议放在：

```text
rpg_engine/player_entry.py
rpg_engine/save_manager.py
```

核心类型：

```python
@dataclass
class SaveManagerConfig:
    root: Path
    registry_path: Path | None = None
    default_campaign: str | None = None
    default_starter_save: str | None = None


class SaveManager:
    def inspect_workspace(self) -> WorkspaceInspectResult: ...
    def list_campaigns(self) -> CampaignListResult: ...
    def register_campaign(self, campaign: str, starter_save: str | None = None) -> CampaignRecord: ...
    def list_saves(self, campaign_id: str | None = None, include_archived: bool = False) -> SaveListResult: ...
    def current_save(self) -> CurrentSaveResult: ...
    def switch_save(self, save_id: str) -> SwitchSaveResult: ...
    def create_save(
        self,
        campaign: str | None = None,
        label: str | None = None,
        starter_save: str | None = None,
        kind: str = "normal",
    ) -> CreateSaveResult: ...
    def duplicate_save(self, save_id: str, label: str | None = None) -> CreateSaveResult: ...
    def refresh_save(self, save_id: str) -> SaveRecord: ...
    def refresh_all(self) -> SaveListResult: ...
    def start_or_continue(
        self,
        campaign: str | None = None,
        user_text: str | None = None,
        create_if_missing: bool = True,
    ) -> PlayerEntryResult: ...
```

服务规则：

- `create_save` 不覆盖非空目录。
- `duplicate_save` 必须复制整个 Save Package，并为新 registry entry 分配新 `save_id`。
- `switch_save` 只改 registry 的 `active_save_id`，不修改存档事实。
- `refresh_save` 调用 `inspect_v1_save`，把当前时间、地点、turn、健康状态写回 registry。
- `start_or_continue` 是玩家入口主流程；它可以创建存档，但不能推进剧情。

## 7. 首次开始游戏流程

### 7.1 高层流程

```text
玩家说“开始游戏”
  -> start_or_continue
    -> 读取 registry
    -> 如果有 active save：inspect + query scene + 返回继续游戏引导
    -> 如果没有 active save：
      -> 解析 campaign
      -> 创建新 save
        -> 优先复制 starter save
        -> 否则执行 save init
      -> 登记 registry
      -> 设置 active_save_id
      -> inspect 新 save
      -> query scene
      -> 渲染 onboarding
```

### 7.2 Starter 优先级

新建存档时按以下顺序选择来源：

1. `start_or_continue` 参数传入的 `starter_save`。
2. registry 中 `campaigns[].starter_save_path`。
3. Save Manager config 的 `default_starter_save`。
4. 调用 `init_v1_save(campaign, target)`。

Starter save 的优势：

- 作者可以打磨第一幕状态。
- 可以包含经过验证的起始 snapshot、cards 和 search。
- 新手体验稳定，避免每次从裸 campaign 初始化时丢失作者调校。

约束：

- 复制 starter 不得修改剧情事实。
- 可以只更新 registry 元数据；是否写入 `save.yaml` 扩展字段作为 P1。
- 复制后必须执行 `save validate` 或至少 `save inspect`。

### 7.3 新存档命名

默认目录：

```text
saves/<campaign_id>/save-<YYYYMMDD-HHMMSS>-<shortid>/
```

默认标签：

```text
<campaign_name> · 新游戏 N
```

若用户指定标签，标签只影响 registry，不影响目录安全。

## 8. 继续游戏流程

有 active save 时：

1. `refresh_save(active_save_id)`。
2. 若 `health=ok`，调用 `GMRuntime.query("scene", view="player")`。
3. 返回当前场景摘要和 3-5 个可行动建议。
4. 更新 `last_played_at`。

如果 active save 不健康：

- 不自动创建新档覆盖。
- 给出明确选项：

```text
当前存档校验失败，不能安全继续。

可以选择：
1. 查看错误
2. 切换其他存档
3. 新建一个存档
4. 导入备份
```

## 9. 多存档列表与切换 UX

### 9.1 玩家可见列表

示例：

```text
你有 3 个存档：

1. 异世界悠闲农家 · 第28天上午 · 六边形菌丝复合屋
   最近游玩：2026-07-01 09:20，状态：正常

2. 异世界悠闲农家 · 第1天清晨 · 空地/家
   最近游玩：未开始，状态：正常

3. 测试档 · 第3天傍晚 · 小溪
   最近游玩：2026-06-30 22:10，状态：正常

你可以说“继续第一个”“切到测试档”或“新开一个档”。
```

### 9.2 切换规则

- 切换只改变 active save。
- 切换后必须立刻 inspect 新 active save。
- 切换后建议 query scene，让 AI GM 不沿用旧存档上下文。
- AI 客户端在切换后必须清楚告知玩家当前存档。

示例：

```text
已切换到“异世界悠闲农家 · 第1天清晨 · 空地/家”。
当前存档从第1天清晨开始，位置是空地/家。
```

### 9.3 不自动跨档承接上下文

如果玩家刚从第28天存档切到第1天存档，AI GM 必须重新 query scene，不得继续使用前一个存档的角色状态、NPC位置或历史事件。

## 10. Onboarding 模板

推荐剧情包可选文件：

```text
templates/onboarding.md
```

Fallback 模板由引擎提供。

### 10.1 模板输入

```json
{
  "campaign_name": "万能农具 · 异世界悠闲农家",
  "save_label": "异世界悠闲农家 · 新游戏 1",
  "player_name": "亚",
  "current_time": "第1天 · 清晨",
  "current_location_name": "空地/家",
  "scene_text": "...player query scene text...",
  "affordances": [
    "看看周围有什么",
    "和夏娃说话",
    "去小溪取水",
    "盘点身上的东西"
  ]
}
```

### 10.2 模板规则

- 只能使用 player view `query scene` 返回的内容。
- 不展示 hidden 信息。
- 不推进时间。
- 不生成 delta。
- 不承诺玩家已经行动。
- 不使用 `delta`、`commit`、`SQLite`、`save_dir` 等内部词。
- 必须提供 3-5 个自然语言行动。
- 必须说明“行动会先预演，确认后保存”。

### 10.3 默认模板

```text
你正在开始《{campaign_name}》。

现在是 {current_time}，你位于 {current_location_name}。
{scene_summary}

你可以直接说想做什么，例如：
{affordance_list}

我会先告诉你行动可能的风险、代价和需要确认的地方；你确认后，结果才会写进存档。
```

## 11. MCP 设计

### 11.1 新增工具

MCP V1.1 建议新增：

```text
workspace_inspect
campaign_list
save_list
save_current
save_create
save_switch
start_or_continue
intent_manifest
player_turn
player_confirm
```

P1 可再加：

```text
save_rename
save_duplicate
save_archive
save_adopt
```

P2 才考虑：

```text
save_delete
```

`save_delete` 是高风险操作，默认不进入普通 AI GM 工具白名单。

### 11.2 工具契约

#### workspace_inspect

输入：

```json
{}
```

输出：

```json
{
  "ok": true,
  "root": "/path/to/workspace",
  "registry_exists": true,
  "campaigns_count": 1,
  "saves_count": 3,
  "active_save_id": "save_20260701_001",
  "errors": []
}
```

#### campaign_list

输入：

```json
{
  "refresh": true
}
```

输出：已登记剧情包，包含 `id`、`name`、`path`、`starter_save_path` 和 `status`。

#### save_list

输入：

```json
{
  "campaign_id": "isekai-farm",
  "include_archived": false,
  "refresh": true
}
```

输出：玩家可见存档摘要列表。

#### save_current

输入：

```json
{
  "refresh": true
}
```

输出：当前 active save 摘要。没有 active save 时返回 `ok=false` 和可执行建议。

#### save_create

输入：

```json
{
  "campaign": "isekai-farm-campaign-native-v1",
  "label": "新游戏 1",
  "starter_save": "isekai-farm-save-native-starter-v1",
  "activate": true
}
```

输出：新建 save record。该工具可以写文件，但不得覆盖既有目录。

#### save_switch

输入：

```json
{
  "save_id": "save_20260701_001"
}
```

输出：切换后的 current save 摘要。

#### start_or_continue

输入：

```json
{
  "campaign": "isekai-farm-campaign-native-v1",
  "user_text": "开始游戏",
  "create_if_missing": true
}
```

输出：

```json
{
  "ok": true,
  "mode": "created",
  "save": { "...": "..." },
  "scene": { "...": "query scene result" },
  "onboarding_text": "..."
}
```

`mode` 可取：

- `created`
- `continued`
- `needs_campaign`
- `needs_save_choice`
- `blocked`

### 11.3 与现有 play 工具的关系

现有工具仍保留：

```text
save_inspect
start_turn
query
preview_from_text
preview_action
validate_delta
commit_turn
health
```

解析 save 的优先级：

1. 工具调用显式传入 `save`。
2. 如果 MCP 配置启用 registry active mode，使用 registry 的 `active_save_id`。
3. 回退到 `--default-save`。
4. 都没有则返回错误，提示调用 `start_or_continue` 或 `save_switch`。

默认兼容旧行为：如果配置了 `--default-save` 且未启用 registry active mode，仍使用旧默认存档。

## 12. CLI 设计

新增玩家入口命令组：

```text
aigm player inspect <root>
aigm player campaigns <root>
aigm player saves <root>
aigm player current <root>
aigm player start <root> --campaign <campaign> [--starter-save <save>] [--label <label>]
aigm player new <root> --campaign <campaign> [--starter-save <save>] [--label <label>]
aigm player switch <root> <save-id>
aigm player duplicate <root> <save-id> [--label <label>]
```

说明：

- `player start`：有 active save 时继续；没有时创建。
- `player new`：无论是否有 active save，都新建一个存档并激活。
- `player saves`：列出玩家友好摘要。
- `player switch`：切换 active save。
- `player duplicate`：P1；复制现有存档用于测试或分支路线。

CLI 输出必须支持 `--format json`，供 MCP 测试和自动化复用。

## 13. 当前 Isekai Farm 应用方案

当前工作区：

```text
/Users/oliver/.hermes/rp
```

现有包：

```text
isekai-farm-campaign-native-v1/
isekai-farm-save-native-v1/
isekai-farm-save-native-starter-v1/
```

建议初始 registry：

```json
{
  "schema_version": "1",
  "active_save_id": "isekai_farm_current",
  "campaigns": [
    {
      "id": "isekai-farm",
      "name": "万能农具 · 异世界悠闲农家",
      "path": "isekai-farm-campaign-native-v1",
      "starter_save_path": "isekai-farm-save-native-starter-v1",
      "status": "ok"
    }
  ],
  "saves": [
    {
      "id": "isekai_farm_current",
      "campaign_id": "isekai-farm",
      "campaign_name": "万能农具 · 异世界悠闲农家",
      "path": "isekai-farm-save-native-v1",
      "label": "异世界悠闲农家 · 当前进度",
      "kind": "normal",
      "source": "adopted",
      "archived": false,
      "health": "ok"
    }
  ]
}
```

当前 Hermes MCP 配置应从旧包：

```text
--default-campaign isekai-farm-campaign-v1
--default-save isekai-farm-save-v1
```

改为 native 包：

```text
--default-campaign isekai-farm-campaign-native-v1
--default-save isekai-farm-save-native-v1
```

实现 registry active mode 后，可进一步改为：

```text
--root /Users/oliver/.hermes/rp
--registry-active
--default-campaign isekai-farm-campaign-native-v1
```

`--default-save` 可以保留作为 fallback。

## 14. 安全与一致性

### 14.1 Registry 写入

Registry 写入必须：

- 加锁。
- 写入临时文件。
- fsync 后原子 rename。
- 写入失败不得破坏旧 registry。

### 14.2 文件复制

创建或复制存档必须：

- 目标目录不存在或为空。
- 不接受 `--force` 作为玩家入口默认能力。
- 复制后执行 inspect/validate。
- 失败时清理未登记的半成品目录，或标记为 `health=error` 并提示人工处理。

### 14.3 并发

同一 root 可能有多个 AI 客户端。Save Manager 应至少保证 registry 级别互斥。

游戏回合写入仍由现有 UnitOfWork、backup 和 projection 状态保证。

### 14.4 Hidden 信息

存档列表只使用 `save inspect` 的摘要字段，不读取 GM hidden 内容。

Onboarding 只使用 player view `query scene`。

## 15. 测试计划

### 15.1 Unit Tests

- registry 路径校验：拒绝绝对路径、`..` 和 root 逃逸。
- registry 读写：空 registry、损坏 registry、版本不匹配。
- active save 切换：存在、缺失、archived、health error。
- create save：starter copy、save init fallback、目录冲突。
- duplicate save：复制后 save_id 不同，源存档不变。
- refresh save：inspect 结果写回 registry。

### 15.2 CLI Tests

使用 `examples/small_cn_campaign` 建临时 workspace：

```bash
aigm player inspect /tmp/aigm-workspace --format json
aigm player start /tmp/aigm-workspace --campaign campaigns/small_cn --format json
aigm player saves /tmp/aigm-workspace --format json
aigm player switch /tmp/aigm-workspace <save-id> --format json
```

断言：

- 第一次 `player start` 创建存档。
- 第二次 `player start` 继续同一个 active save。
- `player saves` 显示健康状态和当前地点。
- 切换后 `current` 返回新存档。

### 15.3 MCP Tests

- 无 active save 时 `start_or_continue` 自动创建。
- 有 active save 时 `start_or_continue` 不创建新档。
- `save_list` 不暴露绝对路径给普通结果，debug 视图可显示 root 相对路径。
- `query` 省略 save 时能使用 active save。
- `save_switch` 后下一次 `query scene` 读取新存档。

### 15.4 Onboarding Tests

- Onboarding 包含当前时间、地点和 3-5 个可行动建议。
- Onboarding 不包含 hidden 实体。
- Onboarding 不包含 `delta`、`commit`、`SQLite`、`save_dir` 等内部术语。
- Onboarding 不推进 turn，不写 event。

### 15.5 Isekai Farm Gate

在现有质量门禁外增加：

- registry 存在且可解析。
- active save 指向 `isekai-farm-save-native-v1`。
- starter save 指向 `isekai-farm-save-native-starter-v1`。
- `start_or_continue` 对 active save 返回 continued。
- 清空 active save 的临时 registry 副本后，`start_or_continue` 能从 starter 创建新档。

## 16. 实施计划

### P0：让玩家能安全开始和继续

1. 新增 `save_manager.py` 和 registry 读写。
2. 新增 `player start/current/saves/switch/new` CLI。
3. 新增 MCP 工具：`save_list`、`save_current`、`save_create`、`save_switch`、`start_or_continue`。
4. 支持 starter copy 和 `save init` fallback。
5. 实现 fallback onboarding 模板。
6. 修正当前 Hermes 默认 native 路径。
7. 为 Isekai Farm 创建 registry。

### P1：改善多存档体验

1. 增加 `templates/onboarding.md` 支持。
2. 增加 `save_duplicate` 和 `save_rename`。
3. 存档列表加入更好的 `summary` 生成。
4. MCP play 工具支持 registry active mode。
5. 导入 `.aigmsave` 后自动登记 registry。
6. 导出时使用 registry label 生成默认文件名。

### P2：维护和高级能力

1. archive save，不删除文件，只隐藏在普通列表中。
2. 高风险 `save_delete`，默认不暴露给普通 AI GM。
3. registry schema migration。
4. 多剧情包安装/发现体验。
5. 可选 TUI/Web UI。

## 17. 验收标准

P0 完成后，以下流程必须成立：

```text
给一个剧情包和一个空 workspace。
玩家说“开始游戏”。
系统自动创建存档。
系统返回第一幕和 3-5 个可选行动。
玩家退出后再次说“继续游戏”。
系统继续同一个存档。
玩家说“列出存档”。
系统显示所有存档摘要。
玩家说“切到第二个存档”。
系统切换 active save 并重新查询场景。
```

工程验收：

- 不破坏现有 `save init`、`play query`、`play commit`。
- 不要求移动旧存档。
- 不泄露 hidden 内容。
- 不覆盖非空目录。
- 所有新增 CLI 输出支持 JSON。
- MCP 没有任意文件读写能力。

## 18. 开放问题

1. 是否把 `save_id` 写入 `save.yaml`？
   - P0 可只存在 registry。
   - P1 可作为可选 metadata 写入，方便单个存档脱离 registry 后仍可识别。

2. Starter save 应如何发布？
   - 当前建议作为 workspace 中的独立 Save Package 或 `.aigmsave`。
   - 不建议把运行态 `data/` 放进 Campaign Package。

3. `default_save` 与 registry active 的优先级是否需要配置开关？
   - 为兼容旧客户端，建议默认旧行为。
   - 新配置显式启用 registry active mode。

4. 是否需要多玩家 profile？
   - V1.1 不做账号系统。
   - 如果本地多人共用同一 workspace，可在 P2 增加 `profile_id` 字段。
