# Release Quality Gate

本文定义 `isekai-farm` 原生剧情包和存档包的发布前检查。

## 当前发布入口

- 剧情包：`../`
- 当前存档：`../../isekai-farm-save-native-v1/`
- 起始存档：`../../isekai-farm-save-native-starter-v1/`
- 一键质量门禁：`../../tools/validate_isekai_farm_native.py`

## 必须通过

- `campaign doctor --strict` 没有 error 或 warning。
- `campaign validate` 通过。
- `campaign test` 通过。
- 当前存档和起始存档 `save validate` 通过。
- 当前存档可查询当前场景。
- 当前存档可导出为 `.aigmsave`，导入后仍可验证。
- 剧情包不包含运行态目录或文件。
- 剧情包通过 `campaign save-fact boundary` 检查：不得包含当前关系记录、当前天数/turn、当前裁决、当前陷阱状态、当前角色状态或具体存档数值。
- 存档包顶层只包含 `campaign.yaml`、`save.yaml`、`data/`、`snapshots/`、`cards/`。

## 当前允许的非阻塞项

这些项目不会阻止继续游玩，也不代表包不是原生包：

- `content/world_settings.yaml` 仍较大，后续可按主题拆分。
- 物品内容已从旧 `content/items.yaml` 拆分为 `content/items/*.yaml`，后续按类别维护。
- 部分实体 ID 仍是 `v1-*` 风格，已在 `docs/v1-id-mapping.md` 建立映射；后续需要连同存档引用分批迁移。
- 若缺少世界细节，应进入内容补全流程，不在工程整理中推测补齐。

## 发布前人工核对

- 确认继续游玩入口是 `rp/isekai-farm-save-native-v1/`。
- 确认新开局测试入口是 `rp/isekai-farm-save-native-starter-v1/`。
- 确认 `archive/` 下内容没有被当作日常入口。
- 确认本次改动没有修改玩家未确认的游戏事实。
- 若执行 ID 迁移，确认旧 ID 已保留 alias，且当前存档、起始存档、导出/导入验证均通过。
