# Source Mapping

本次重建没有主动改写既有实体 ID。

来源：

- `../archive/legacy/isekai-farm-save-v1/data/game.sqlite`：当前权威存档状态。
- `../archive/legacy/isekai-farm-campaign-v1/content/random_tables.yaml`：玩法随机表来源。
- `../archive/legacy/isekai-farm-v2/content/deltas/*.json`：后续内容补全参考，不在本次机械导出中直接重放。

`v1-<hash>` 风格 ID 暂时保留，后续如需改名，应先参考 `docs/v1-id-mapping.md` 的 old -> new 映射，再迁移剧情包和存档引用。

当前映射状态：

- 已生成：`docs/v1-id-mapping.md`
- 覆盖范围：当前剧情包内容源中的 68 个 v1 风格 ID。
- 当前策略：本轮不直接改 ID，避免破坏现有存档、历史事件和卡片引用；后续按类别分批迁移，并在过渡期保留旧 ID 作为 alias。
