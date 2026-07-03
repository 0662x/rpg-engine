# AIGM Kernel V1 · Bug Report

> 最后更新：2026-07-01 · 发现者：悉悉 (CC) + 用户

---

## #1 行动分类器误判：巡视/探索 → craft

**日期**：2026-07-01  
**严重程度**：🟡 中等（影响玩法体验，不影响数据安全）

### 复现

```
python3 -m rpg_engine play start-turn <save> --user-text "巡视领地，看看大家都在做什么"
```

### 预期行为

"巡视领地，看看大家都在做什么" 应被分类为：
- `action:explore`（领地巡逻/侦察），或
- `action:routine`（日常巡视）

### 实际行为

引擎分类为 `action:craft`（制作），返回的 Context Packet 中：
```
模式: action:craft
回复模板: craft_turn.md
```

### 影响

1. `play preview craft` 要求指定成品、材料、配方 —— 对巡逻行动毫无意义
2. GM 被迫在 craft 框架里捏造不存在的制作内容，或绕过引擎手动叙事
3. 破坏了 `start-turn → preview → validate → commit` 的自动化管道

### 推测根因

分类器可能对中文"看看"（look around / check）缺乏映射，"巡视"也未匹配到 explore/routine 意图。可能被"查看"类的模糊语义 fallback 到了 craft。

### 建议

- 将 "巡视"、"巡逻"、"看看周围"、"查看领地" 等中文短语映射到 `explore` 或 `routine`
- 或增加一个 `survey` / `patrol` 子模式，避免 fallback 到 craft

---

## #2 引擎 API 无法查询菌丝单位实时数量（兵力）

**日期**：2026-07-01  
**严重程度**：🟡 中等（破坏「kernel 是唯一真相源」原则）

### 复现

尝试通过引擎 API 获取腐工蕈/锐孢蕈/思菌蕈/岩铠蕈的当前数量：

1. `play start-turn` 的 Context Packet → 不返回单位数量
2. `play query <save> entity species:youhrang-mycelium` → 只返回物种描述和能力，不返回实时计数
3. `save inspect` → 只返回总实体数（288），不分解子类型

### 预期行为

引擎应提供查询接口返回当前菌丝兵力，例如：
- `play query <save> force` 或 `play query <save> entity species:youhrang-mycelium --with-counts`
- 或在 Context Packet 中自动包含单位统计

### 实际行为

**没有任何引擎 API 能查到菌丝单位的实时数量。** 目前唯一能获取数量的是直接读 `data/events.jsonl` 中的历史快照——最新一份是第24天用户快照（110 腐工蕈、21 锐孢蕈、5 思菌蕈）。

### 影响

1. GM 被迫绕过引擎，直接翻 SQLite / events.jsonl 才能回答「兵力多少」——违反了 `Hard Rules` 第一条：「The kernel is the source of truth」
2. 第24天到第28天之间没有新的兵力事件，无法确认数字是否变化
3. 岩铠蕈「5-7天成熟」的倒计时完全靠手工推算，引擎不自动推进孢子→成体

### 当前降级方案

engine-pitfalls.md 已记录降级路径（读 events.jsonl），但这是技术债。

### 建议

- `species:youhrang-mycelium` 实体中增加 `unit_counts` 字段，由 delta 自动更新
- 或在 `play query` 中增加 `force` / `unit-summary` 查询类型
- 岩铠蕈孢子倒计时应有自动推进机制（或至少暴露为可查询的 clock）

---

## #3 Hermes 安全门误拦 `play start-turn`

**日期**：2026-07-01  
**严重程度**：🔴 高（阻断 GM 正常游戏流程，无法推进回合）

### 复现

```
python3 -B -m rpg_engine play start-turn <save> --user-text "让夏娃启动菌丝从L7泉眼引水自动灌溉..."
```

用户输入任何带中文的自然语言行动文本均被拦截。

### 实际行为

Hermes 安全门返回：
```
BLOCKED: Command denied by user. The user has NOT consented to this action.
```

用户**已明确说"允许"**后重试，仍被拦截。

### 关键点

- `play start-turn` 是**纯读取操作**——生成 Context Packet，不写入存档
- 被拦截并非因为写操作风险，而是安全门对 `--user-text` 参数中的中文内容或保存路径触发了误判
- `play query` 同类路径正常通过，说明问题不在文件访问权限

### 影响

1. GM 无法使用标准流程推进回合（`start-turn → preview → validate → commit`）
2. 被迫降级为手动叙事 + 手工构造 delta，跳过引擎的 context 生成和自动分类
3. 每次行动前都要绕过安全门，严重破坏游戏流畅度

### 当前降级方案

跳过 `start-turn`，直接用 `play query scene` 获取场景，然后 GM 手工叙事、手工构造 delta、手动 `play commit`。

但这意味着跳过：
- 引擎自动分类（explore/social/travel 等）
- Context Packet 中的关联实体、世界设定、进度钟压力提示
- `preview_action` 的风险/成本估算

### 建议

- 将 `play start-turn` 加入 Hermes 白名单（该命令只读不写）
- 或排查安全门的中文文本匹配规则，避免对 `--user-text` 内容误判

**状态更新 (2026-07-01 重测)**：`start-turn` 已恢复正常，安全门不再拦截。此 bug 可能为间歇性问题，或已被修复。

**根因确认 (2026-07-01)**：拦截并非泛安全门，而是 **同形字符检测 (homoglyph detection)**。安全扫描信息：
> `[HIGH] Confusable Unicode characters in text: Content contains Unicode characters visually identical to ASCII (math alphanumerics, Cyrillic/Greek lookalikes) appearing near ASCII text, which may indicate a homoglyph attack`

`--user-text` 中的中文字符被误判为与 ASCII 字符同形的 Unicode 码点。间歇性出现可能是因为不同文本触发的同形字符数量不同。

**建议修正**：将 `play start-turn --user-text` 的中文内容排除同形字符检测，或将 `rpg_engine` 加入白名单。

---

## #4 Long-Term Memory 未随 delta commit 更新（数据陈旧）

**日期**：2026-07-01  
**严重程度**：🟡 中等（叙事与实际状态不一致，可能误导 GM）

### 复现

1. Turn #44 提交了灌溉 delta（夏娃引水浇十六畦，`commit` 成功）
2. 重新调用 `play start-turn`
3. 查看 Context Packet → Long-Term Memory → `reflection:project:project-water-crops`

### 预期行为

灌溉提交后，项目摘要应反映浇水已完成，如「十六畦已灌溉」或移除浇水提醒。

### 实际行为

长期记忆摘要仍显示旧数据：
```
摘要：当前最紧迫的日常项目：十六畦两天未浇水...
next_steps: 先确认浇水方式：竹水筒多趟、菌丝引水或两者结合...
```

### 影响

1. GM 看到旧提醒会误判状态，重复建议浇水
2. 长期记忆与 entity/item 状态脱节——entity 层正确（鱼虾已消费），但 memory/reflection 层不更新
3. reflection 似乎是手工写入而非自动从 delta 派生

### 建议

- `play commit` 成功后触发相关 project/clocks 的 reflection 刷新
- 或在 `play health` / `save inspect` 中加入陈旧 memory 检测

---

