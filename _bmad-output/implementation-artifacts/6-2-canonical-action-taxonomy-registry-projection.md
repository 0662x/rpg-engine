---
baseline_commit: dbced868397e2bc165156d28450f33aa8e50a113
---

# Story 6.2：规范行动分类注册表投影

Status: done

## Story

作为 intent contract maintainer，
我希望 simple lexical action taxonomy 只有一个 versioned registry owner，
从而避免 deterministic routing、live manifest、internal prompts 与 external consumers 漂移。

## Acceptance Criteria

1. **Canonical owner 与同源投影**
   - Given builtin resolvers 已注册，when action taxonomy 被解析，then `ActionResolverSpec` / `ActionResolverRegistry` 持有 versioned `ActionTaxonomySpec` 的唯一事实源。
   - Deterministic router、live intent manifest、internal intent prompt 和 registry/CLI introspection 必须消费该 resolved projection；不得继续维护平行的 simple synonym tables。
   - Public manifest 发布明确的 taxonomy `version`、canonical `digest` 和确定性 action/locale projection；taxonomy 进入整体 manifest digest。
   - 本 Story 新增 public manifest wire shape 时，将 `MANIFEST_SCHEMA_VERSION` 从 `"2"` 提升为 `"3"`；此后单纯词项/locale/priority 变化只旋转 taxonomy digest 与整体 manifest digest，不把 schema version 当内容版本使用。
   - `ActionResolverSpec` 持有不可变的 per-action taxonomy metadata；`ActionResolverRegistry` 持有唯一的全局 taxonomy version、resolved projection 与 digest。兼容构造参数只能通过互斥 migration adapter 归一化为 canonical taxonomy，不能形成第二事实源。

2. **Router grammar 与既有权威不回退**
   - Router 继续拥有 composite、negation/hypothetical、maintenance、query、entity-aware 和 context-aware grammar；仅迁移 simple lexical synonyms。
   - 现有 P0 routes、step order、entity/hidden binding、player-surface filtering、low-level mismatch guard、off-mode valid external-primary 与 consensus fail-closed 行为不得回退。
   - External/internal AI 继续没有事实、玩家确认、validation、commit 或 hidden/GM-only 内容公开权威。

3. **Builtin/custom/campaign/locale parity 与 stale refresh**
   - Builtin resolvers、注册到合法 custom/campaign registry 的 resolver spec，以及 multilingual locale terms 都经同一 resolved contract 投影和匹配；不新增 Campaign schema、动态插件代码加载或 locale pack loader。
   - “巡视”和“巡逻”在 deterministic route、manifest 与 internal prompt 中都映射到 `routine`，且保持 `ready` / `ready_to_save` 的当前 P0 行为。
   - Registry 注册顺序和 `PYTHONHASHSEED` 不得改变 projection/digest；simple term collision 需要确定性、fail-closed 的验证，不能静默覆盖。
   - Taxonomy term、locale term、priority 或 taxonomy version 改变必须旋转 taxonomy digest 与整体 manifest digest；绑定旧 manifest identity 的 candidate 必须复用 Story 6.1 的 retriable `contract_version_mismatch`，action 为 `refresh_manifest_and_regenerate_candidate`。
   - Runtime 使用 injected/custom registry 时，同一 registry 必须贯通 deterministic route、binder、internal prompt、live manifest 与 active external-contract validation；不得在链路中悄悄回退到 default registry。

## Tasks / Subtasks

- [x] Task 1：建立唯一的 versioned taxonomy contract（AC: 1, 3）
  - [x] 在 `rpg_engine/actions/` 定义 frozen、JSON-safe 的 `ActionTaxonomyTerm`、`ActionTaxonomySpec` 与 resolved projection；使用不可变 tuple/只读派生值，禁止调用方通过可变引用改写 registry 合同。
  - [x] `ActionResolverSpec.taxonomy` 持有 per-action terms、semantic labels 与 inference priority；`ActionResolverRegistry` 持有全局 `ACTION_TAXONOMY_VERSION = "1"`、确定性 resolved projection 与 SHA-256 digest。
  - [x] 保留既有 `ActionResolverSpec(..., keywords=..., semantic_labels=..., inference_priority=...)` 调用兼容性，但它必须作为 migration adapter 一次性构造 canonical `taxonomy`；显式 `taxonomy=` 与任一 legacy taxonomy 参数同时出现必须 fail closed。`.keywords`、`.semantic_labels`、`.inference_priority` 仅是 canonical taxonomy 的只读派生 property。
  - [x] 复用仓库既有 canonical JSON 规则：UTF-8、`ensure_ascii=False`、sorted keys、compact separators、`allow_nan=False`；不得新增第二套相互不兼容的 digest 语义。
  - [x] 若将 `canonical_json_sha256()` 下沉到中性 leaf module，旧 `rpg_engine.ai_intent.safety_contract` import path 必须 re-export 同一函数，并证明 Story 6.1 digest/import 行为不变。
  - [x] 校验常量必须公开且有测试：version 长度 `1..32`；locale 长度 `2..35` 且匹配 `^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$`；term 长度 `1..128`；每 action 最多 `256` terms；每 registry 最多 `128` actions；role 长度 `1..64`、每 term 最多 `16` roles。输入必须是 exact built-in `str` / `tuple`，拒绝 blank、leading/trailing whitespace、Unicode control、bool/int coercion 与 oversize 值。
  - [x] 对同 action 规范化重复和 cross-action exact collision 做 fail-closed 验证；跨 action 的合法非完全重叠仍保持确定性 priority/name 规则。
  - [x] 规范化必须锁定现有行为：Unicode NFKC + casefold；Latin 使用 word boundary，CJK 使用 substring；避免 `rest` 误命中 `forest`。
  - [x] Registry register 必须先完整验证 prospective projection/collision，再原子替换 `_specs`；失败后 names、projection、version 与 digest 必须逐字节不变。

- [x] Task 2：迁移 builtin resolver taxonomy，并保留兼容投影（AC: 1, 2, 3）
  - [x] 将九个 builtin resolver 的 simple lexical terms、locale terms、semantic labels 与 priority 迁到 taxonomy owner；把 `ROUTINE_INTENT_TERMS`、`CRAFT_INTENT_TERMS` 及其他纯 simple synonyms 收敛进去。
  - [x] 补齐当前 router-only 的 routine/craft 词项，至少覆盖“巡视”“巡逻”“巡检”、`patrol`、`inventory`、`audit`、`craft`、`make`、`build`、`repair`、`fix`。
  - [x] 若继续暴露 `spec.keywords` / `semantic_labels` 或 CLI 旧字段，它们必须是 taxonomy 的只读兼容 projection，不得继续成为可独立维护的第二事实源。
  - [x] 保持九个 action name、默认 registry 排序、resolver preview/request/resolve/delta 合同不变。

- [x] Task 3：让 deterministic routing 只消费 resolved taxonomy（AC: 1, 2, 3）
  - [x] 为 `ActionResolverRegistry` 提供确定性的 resolved projection 与 simple-term matching API；默认及注入 registry 使用相同逻辑。
  - [x] 删除 router 中平行的 simple lexical tables 和 special fallback；`infer_action_from_registry()`、`action_keywords()` 与 `keyword_expected_action()` 使用同一 registry projection。
  - [x] 每个 canonical term 必须携带稳定 `roles` tuple；所有 action synonym 至少有 `simple`，inventory composite 子集另带 `inventory` role。Router 通过 registry 的 role projection 读取 `盘点/inventory/audit` 等词项，不复制词面，也不得把全部 routine terms 当 inventory grammar。
  - [x] 保留 composite grammar（含 inventory/round-trip step order）、否定/假设、maintenance/query、可见实体与上下文消歧；“找/搜索/检查/到”等 context grammar 若需要词项，只能通过 canonical role 选择器引用，不得维护平行 literal table。
  - [x] 保持 current `inference_priority + stable action name` 的确定性顺序及 travel 的既有消歧语义；若实现必须改变 collision precedence，属于 decision-needed，立即 HALT。
  - [x] Low-level direct `preview_action` mismatch guard 仍 fail closed，但 expected action 必须来自同一 taxonomy；routed intent mismatch 仍仅作 diagnostic。

- [x] Task 4：发布 manifest、prompt 与 introspection 的同源投影（AC: 1, 3）
  - [x] `build_intent_manifest(registry=...)` 新增 `action_taxonomy` identity/projection，并从同一 projection 派生 per-action compatibility fields。
  - [x] 将 manifest schema 升为 v3；整体 `manifest_digest` 必须覆盖 taxonomy version/digest/projection，同时保持 safety vocabulary v1 与 Story 6.1 四字段 candidate contract 不变。
  - [x] 固定 v3 wire shape（tuple 在 canonical JSON/wire 中按 array 处理）：
    ```json
    {
      "schema_version": "3",
      "action_taxonomy": {
        "version": "1",
        "digest": "<sha256>",
        "normalization": {
          "unicode": "NFKC",
          "case": "casefold",
          "latin_match": "word_boundary",
          "cjk_match": "substring"
        },
        "actions": [
          {
            "name": "routine",
            "inference_priority": 65,
            "semantic_labels": ["routine", "daily activity"],
            "terms": [
              {"locale": "zh-Hans", "value": "巡视", "roles": ["simple"]},
              {"locale": "zh-Hans", "value": "盘点", "roles": ["inventory", "simple"]}
            ]
          }
        ]
      }
    }
    ```
  - [x] `actions` 按 action name 排序；`semantic_labels`、terms 和 roles 按规范化值稳定排序。Taxonomy digest 的 payload 为除自身 `digest` 外的完整 `action_taxonomy`；整体 manifest digest 覆盖包含 taxonomy digest 的完整 manifest payload。Per-action `keywords` / `semantic_labels` / priority compatibility fields必须从该结构派生。
  - [x] Internal intent prompt 从 live manifest taxonomy 摘录 action、locale/simple terms、semantic labels 与 priority；不得重新硬编码 synonyms，也不得纳入 hidden/GM-only Campaign 内容。
  - [x] Manifest schema v3 同步提升 `docs/prompts/ai-client-prompt.md` 的 prompt/contract version，并明确 consumer 必须先刷新 manifest 再生成 candidate。
  - [x] MCP `intent_manifest` 保持 thin wrapper；CLI action list/inspect 通过 registry render helper 自动反映 taxonomy identity，不在 `mcp_adapter.py` / `cli.py` 复制投影。
  - [x] 使用自定义 registry/spec 证明 custom/campaign 与 Unicode locale terms 走同一 projection；没有规划证据时不得新增 Campaign loader/schema 或动态 plugin surface。
  - [x] 将同一个 injected registry 从 `GMRuntime.action_registry` 贯通 `runtime.py` → `intent_router.py` route/prepare/infer → `ai_intent/router.py` → binder/internal review/prompt → manifest/active external-contract validation；custom term 必须可路由、出现在 prompt/manifest、接受 exact live contract，并拒绝旧 digest。CLI/MCP 不因此新增 Campaign loader 或动态插件能力。

- [x] Task 5：建立 taxonomy、parity 与 stale-contract gates（AC: 1, 2, 3）
  - [x] 新增 focused taxonomy tests：frozen/defensive-copy、校验边界、collision fail-closed、注册顺序无关、hash-seed 稳定、合法 overlap/priority、builtin/custom/locale projection。
  - [x] 覆盖 router/manifest/internal prompt parity；直接断言“巡视/巡逻”均为 `routine` 并进入相同 projection。
  - [x] 覆盖 taxonomy term/locale/priority/version 变化旋转 taxonomy digest 与 manifest digest，并复用 6.1 contract validator 拒绝 stale candidate。
  - [x] 回归 composite、negation/hypothetical、maintenance、query/context、entity/hidden binding、English routes、unresolved gather/explore、low-level mismatch、off-mode external-primary 与 consensus fallback。
  - [x] 保持两份 intent router gold-set fixture 字节同步；若无需改 fixture，则证明既有 gold set 仍全绿。
  - [x] 所有写测试仅使用 temporary Campaign/Save；不得修改 source Campaign、formal current Saves、正式 registry 或 `data/game.sqlite`。
  - [x] Final focused union（不得用 iteration 子集替代）：
    ```bash
    python3 -m pytest -q tests/test_action_taxonomy.py tests/test_intent_manifest.py tests/test_ai_intent.py tests/test_runtime.py tests/test_p0_stop_loss_acceptance.py tests/test_core_rule_condition_coverage.py tests/test_mcp_adapter.py tests/test_v1_cli.py -p no:cacheprovider
    ```

- [x] Task 6：同步 canonical docs 与最终质量门（AC: 1, 2, 3）
  - [x] 更新 `docs/architecture.md`、`docs/component-inventory.md`、`docs/ai-intent-chain.md`、`docs/mcp-contracts.md`、`docs/cli-contracts.md`、`docs/prompt-contracts.md`、`docs/prompts/ai-client-prompt.md`、`docs/testing-and-quality-gates.md` 中实际受影响的合同描述。
  - [x] 明确 Story 6.1 的 manifest identity/stale refresh 被复用，Story 6.3 的 slot ownership 未被提前实现。
  - [x] 从最终 clean diff 重跑 focused、adjacent、Campaign validate/test、Markdown links、py_compile、full Ruff、`git diff --check` 与 repository full pytest；后续 patch 使旧结果失效时必须重跑受影响 gate。

### Review Findings

- [x] [Review][Patch] 恢复 routine inventory 模板的独立“库存/物资”匹配 [`rpg_engine/actions/routine.py:23`]
- [x] [Review][Patch] 从 public actions API 导出 locale 长度常量并补断言 [`rpg_engine/actions/__init__.py:3`]
- [x] [Review][Patch] 补齐 taxonomy validation 边界与“巡视/巡逻”跨 surface parity gates [`tests/test_action_taxonomy.py:99`]
- [x] [Review][Patch] custom simple action 在无 composite/context grammar 时遵守 registry priority [`rpg_engine/intent_router.py:1280`]
- [x] [Review][Patch] 修复标点边界与非 ASCII Latin term 的 word-boundary 匹配 [`rpg_engine/actions/taxonomy.py:263`]
- [x] [Review][Patch] context completeness 使用 injected registry [`rpg_engine/context/validation.py:49`]
- [x] [Review][Patch] 冻结 normalization contract metadata，防止声明与 matcher 脱节 [`rpg_engine/actions/taxonomy.py:26`]
- [x] [Review][Patch] 预编译 term matcher 并避免最大合法 taxonomy 重复规范化玩家文本 [`rpg_engine/actions/taxonomy.py:263`]
- [x] [Review][Patch] registry fail closed 拒绝大小写混合 action name，保持 manifest/external normalization 一致 [`rpg_engine/actions/taxonomy.py:220`]
- [x] [Review][Patch] 保留既有 ActionResolverSpec subclass 注册兼容性 [`rpg_engine/actions/base.py:226`]
- [x] [Review][Patch] 第二轮复现推翻第一轮 Defer：以 canonical `preview.mismatch` role 恢复 low-level mismatch guard 旧边界 [`rpg_engine/intent_router.py:1892`]
- [x] [Review][Patch] 将 taxonomy substring matcher 扩展到日语假名/片假名与韩文脚本，并保持 legacy locale 推断正确 [`rpg_engine/actions/taxonomy.py:24`]
- [x] [Review][Patch] response lint 与 validation pipeline 使用 injected registry 解析 custom response template/resolver [`rpg_engine/response_lint.py:39`]
- [x] [Review][Patch] fail closed 拒绝 candidate normalization 保留动作名 `none/null/unknown` [`rpg_engine/actions/taxonomy.py:31`]
- [x] [Review][Patch] 所有 Story 6.2 registry seam 以显式 `is not None` 保留 falsey injected registry [`rpg_engine/intent_manifest.py:36`]
- [x] [Review][Patch] 空 action selector 不再退化为全 registry lexical match [`rpg_engine/actions/base.py:256`]
- [x] [Review][Patch] registry projection 只消费上限加一项，oversized/infinite iterable 可有界拒绝 [`rpg_engine/actions/taxonomy.py:231`]
- [x] [Review][Patch] custom `preview.mismatch` role 通过 registry priority/name 参与 low-level hard guard [`rpg_engine/intent_router.py:1892`]
- [x] [Review][Patch] Unicode letter/number noise guard 不再提前拦截合法日语、韩语 action route [`rpg_engine/intent_router.py:1283`]
- [x] [Review][Patch] context completeness 以显式 `is not None` 保留 falsey injected registry [`rpg_engine/context/validation.py:49`]
- [x] [Review][Patch] canonical taxonomy 参数使用 unset sentinel，显式 `taxonomy=None` 不再绕过 legacy 互斥 [`rpg_engine/actions/base.py:128`]
- [x] [Review][Patch] Latin word boundary 将 combining mark 视为词内字符 [`rpg_engine/actions/taxonomy.py:291`]
- [x] [Review][Patch] supplementary Han 与 compatibility ideographs 使用同一 CJK substring matcher [`rpg_engine/actions/taxonomy.py:24`]
- [x] [Review][Patch] 短 Unicode canonical term 命中时不再被标点 noise gate 提前拦截 [`rpg_engine/intent_router.py:1321`]
- [x] [Review][Patch] custom mismatch winner 遵守 registry priority，同时保持 builtin low-level guard 旧顺序 [`rpg_engine/intent_router.py:1892`]
- [x] [Review][Patch] mixed-script term 只在 Latin 端应用 Unicode word boundary，不整体退化为 substring [`rpg_engine/actions/taxonomy.py:292`]
- [x] [Review][Patch] Hangul Extended-A/Extended-B Jamo 使用同一 CJK substring contract [`rpg_engine/actions/taxonomy.py:31`]
- [x] [Review][Patch] Bopomofo 与 Extended 注音字符使用同一 CJK substring contract [`rpg_engine/actions/taxonomy.py:33`]
- [x] [Review][Patch] action name 限定为 lowercase ASCII identifier，阻断 NFKC-confusable reserved/collision 绕过 [`rpg_engine/actions/taxonomy.py:251`]
- [x] [Review][Patch] travel+social low-level composite warning 只消费 injected registry canonical roles [`rpg_engine/intent_router.py:1878`]
- [x] [Review][Patch] taxonomy version 旋转整体 manifest digest 并触发 stale `contract_version_mismatch` 的完整 gate [`tests/test_action_taxonomy.py:455`]
- [x] [Review][Patch] 注音声调/组合字符与 supplementary Kana 按实际 script-bearing base 使用 CJK substring [`rpg_engine/actions/taxonomy.py:30`]
- [x] [Review][Patch] 恢复“检查+领地/单位状态/维护”的 baseline routine P0，同时保持“检查线索”为 explore [`rpg_engine/actions/routine.py:59`]
- [x] [Review][Patch] builtin inventory composite grammar 仅消费 builtin role owner，不吞掉 custom `search` priority winner [`rpg_engine/intent_router.py:1354`]
- [x] [Review][Patch] subset injected registry 对未注册或不完整 inferred/composite plan 统一 fail closed [`rpg_engine/intent_router.py:1294`]
- [x] [Review][Patch] craft completeness 从 active registry canonical term 判断词项后的目标内容，删除中文平行词面表 [`rpg_engine/context/validation.py:42`]
- [x] [Review][Patch] semantic prompt 与 suggestion normalizer 贯通同一个 injected registry [`rpg_engine/context/semantic.py:24`]
- [x] [Review][Patch] subset registry 缺少 routine 时，纯查询 fallback 仍保持 query 路由 [`rpg_engine/intent_router.py:731`]
- [x] [Review][Patch] dict 形态 plan/repair action 纳入 subset registry fail-closed 核验 [`rpg_engine/intent_router.py:1672`]
- [x] [Review][Patch] custom-only registry 的合法 lexical winner 不再被未注册 routine fallback 覆盖 [`rpg_engine/intent_router.py:743`]
- [x] [Review][Patch] English informational query、negation 与 hypothetical grammar 不因新增 simple terms 变成可保存行动 [`rpg_engine/intent_router.py:1267`]
- [x] [Review][Patch] English system/engine/code maintenance 管理语境在 routine term 前 fail closed，同时保留世界内 upkeep [`rpg_engine/intent_router.py:1094`]
- [x] [Review][Patch] 扩展 English auxiliary/information query grammar 与中文“查看…信息”custom term 查询边界 [`rpg_engine/intent_router.py:1340`]
- [x] [Review][Patch] 扩展 English `not/won't/no/suppose/imagine` 否定假设形态，保持 non-saveable [`rpg_engine/intent_router.py:1289`]
- [x] [Review][Patch] English maintenance/upkeep 以软件对象和世界 engine 限定双向判别 [`rpg_engine/intent_router.py:1098`]
- [x] [Review][Patch] `runtime.query("context")` 嵌套构建贯通 custom/falsey active registry [`rpg_engine/runtime.py:1067`]
- [x] [Review][Patch] 日文、韩文 canonical terms 增加对应否定与假设 grammar guard [`rpg_engine/intent_router.py:1310`]
- [x] [Review][Patch] craft completeness 按 locale 接受日/韩对象助词 SOV 目标且拒绝无目标礼貌前缀 [`rpg_engine/actions/base.py:303`]
- [x] [Review][Patch] explicit `mode=action` 不得绕过 out-of-world maintenance hard guard [`rpg_engine/intent_router.py:484`]
- [x] [Review][Patch] maintenance 软件对象与 world engine 所有格/审计任务正确双向区分 [`rpg_engine/intent_router.py:1110`]
- [x] [Review][Patch] 日/韩 canonical action 的条件、句尾疑问形态统一 non-saveable [`rpg_engine/intent_router.py:1320`]
- [x] [Review][Patch] 第三人称 English `Can …?` 能力问句保持只读 query，`Can I/we` 保持 clarify [`rpg_engine/intent_router.py:1390`]
- [x] [Review][Patch] 中文 custom taxonomy 的通用否定前缀与“吗/呢”问句不再执行 [`rpg_engine/intent_router.py:1306`]
- [x] [Review][Patch] 日文 craft 计划语尾不再冒充目标，同时保留带对象助词的计划制作 [`rpg_engine/actions/base.py:315`]
- [x] [Review][Patch] 韩文前置否定 `안` 形态统一 non-saveable [`rpg_engine/intent_router.py:1320`]
- [x] [Review][Patch] English `tell/show/teach me how to` 教学式请求保持 query [`rpg_engine/intent_router.py:1390`]
- [x] [Review][Patch] 保留 action 名 `act`，避免真实 resolver 与 unresolved pseudo-action sentinel 冲突 [`rpg_engine/actions/taxonomy.py:44`]
- [x] [Review][Patch] taxonomy term 必须至少含一个 Unicode Letter/Number，阻断纯标点或 emoji 词项吞噬 noise [`rpg_engine/actions/taxonomy.py:93`]
- [x] [Review][Patch] 日/韩无问号礼貌疑问句尾保持 non-saveable [`rpg_engine/intent_router.py:1340`]
- [x] [Review][Decision] 用户选择 A：live executable registry 仅接受已有 safety grammar 的 `zh/en/ja/ko` locale family；其他合法 BCP47-like locale 只可保留为非运行时 projection 元数据 [`rpg_engine/actions/base.py:238`]
- [x] [Review][Patch] 日/韩问句 guard 忽略安全句尾标点/闭引号，阻断 `ますか。` / `하나요.` 绕过 [`rpg_engine/intent_router.py:1320`]
- [x] [Review][Patch] executable locale 同时校验显式 script subtag 与 term 实际 script，阻断 `ja/zh/ko-Latn` 及错标 romanization [`rpg_engine/actions/taxonomy.py:184`]
- [x] [Review][Patch] 日文 script-limited 裸句末助词 `か` 保持 non-saveable [`rpg_engine/intent_router.py:1350`]
- [x] [Review][Patch] 中文 custom 问句按 active/default 实际 lexical owner 判定，复用 builtin action 名不再绕过 [`rpg_engine/intent_router.py:1430`]
- [x] [Review][Patch] 日/韩 craft 纯辅助动词语尾不再冒充制作目标，并保留对象助词目标路径 [`rpg_engine/actions/base.py:320`]
- [x] [Review][Patch] 补齐用户触发、CS/VS/DS/CR catalog chain、skill/resolver/config/facts、step/checklist 与最终 gate 命令的 BMAD provenance [`BMAD Provenance`]
- [x] [Review][Patch] 日/韩与 custom 中文问句共享 Unicode sentence-terminal 归一化，覆盖破折号、省略号、句点及闭引号 [`rpg_engine/intent_router.py:1318`]
- [x] [Review][Patch] explicit script subtag 与 term 全部 Letter script 严格一致并拒绝多个 script subtags [`rpg_engine/actions/taxonomy.py:194`]
- [x] [Review][Patch] safety grammar 按 winning canonical term locale 分派，覆盖 supplementary/Hani 问句及日/韩能力否定 [`rpg_engine/actions/base.py:380`]
- [x] [Review][Patch] craft completeness 排除 English 时间/礼貌副词和日/韩复合辅助语尾，同时保留对象助词目标 [`rpg_engine/actions/base.py:235`]
- [x] [Review][Patch] winning action 聚合全部命中 term locale，并与实际日/韩句法 script 合并启用安全语法 [`rpg_engine/actions/base.py:390`]
- [x] [Review][Patch] Unicode sentence-terminal 接受 Punctuation/Symbol/Mark 尾饰，阻断 emoji、variation selector 与 combining mark 绕过 [`rpg_engine/intent_router.py:1320`]
- [x] [Review][Patch] craft 非目标语法覆盖更多 English 时间/礼貌短语及日/韩礼貌、话题、属格与复合辅助形态 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] explicit `zh-Bopo` script 校验接受 canonical Bopomofo tone modifiers [`rpg_engine/actions/taxonomy.py:230`]
- [x] [Review][Patch] legacy adapter 推断 Bopomofo 为 `zh-Bopo`，通用 `zh` 与显式 locale 同步接受含 base 的 tone modifiers [`rpg_engine/actions/taxonomy.py:245`]
- [x] [Review][Patch] English modal safety grammar 覆盖负式 contractions 与第一人称 `shall` 问句 [`rpg_engine/intent_router.py:1350`]
- [x] [Review][Patch] 日文 safety grammar 覆盖过去否定、礼貌过去否定、`せず` 与禁止形 [`rpg_engine/intent_router.py:1390`]
- [x] [Review][Patch] craft 非目标语法补齐 someday/weekend/介词时间短语与日/韩意志辅助形态 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] legacy mixed Han+Bopomofo term 推断为通用 `zh`，纯注音保持 `zh-Bopo` [`rpg_engine/actions/taxonomy.py:310`]
- [x] [Review][Patch] English modal grammar 覆盖 `shan't`、第一人称 `must` 与 `ought` [`rpg_engine/intent_router.py:1350`]
- [x] [Review][Patch] craft 非目标语法覆盖 next-year 与日/韩过去式计划形态，并保留带对象目标 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] executable 中文 `吗/呢` 问句对 builtin/custom 均 fail closed，仅保留已锁定 builtin routine P0 [`rpg_engine/intent_router.py:1475`]
- [x] [Review][Patch] 日文安全语法补齐 `かな/かしら/するの` 问句与意向/能力过去否定 [`rpg_engine/intent_router.py:1375`]
- [x] [Review][Patch] 韩文安全语法补齐疑问、意愿、许可、能力否定与间接疑问形态 [`rpg_engine/intent_router.py:1385`]
- [x] [Review][Patch] builtin routine 中文问句例外收窄到唯一有 baseline 证据的 weather/agriculture P0 [`rpg_engine/intent_router.py:1490`]
- [x] [Review][Patch] English safety grammar 补齐 auxiliary contractions 与第一人称 `need/dare` semi-modal [`rpg_engine/intent_router.py:1350`]
- [x] [Review][Patch] 日文安全语法补齐 `かね` 及意向、义务、能力、禁止否定形态 [`rpg_engine/intent_router.py:1380`]
- [x] [Review][Patch] 韩文安全语法补齐前置 `못`、义务否定、正式/许可/间接问句 [`rpg_engine/intent_router.py:1395`]
- [x] [Review][Patch] craft 非目标语法覆盖通用 duration/day/event 时间短语与日/韩礼貌过去计划 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] strict Jpan/Hani-family script 接受带真实 base 的 ideographic iteration marks [`rpg_engine/actions/taxonomy.py:235`]
- [x] [Review][Patch] craft 非目标语法覆盖更多 duration/preposition/recurrence 时间短语与日/韩时间词 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] 日/韩 safety grammar 改用句首/句尾形态边界，避免目标名内部 substring 误杀 [`rpg_engine/intent_router.py:1390`]
- [x] [Review][Patch] 韩文无标点正式问句覆盖通用 `니까/십니까` 句尾 [`rpg_engine/intent_router.py:1385`]
- [x] [Review][Patch] Hira/Kana/Jpan iteration mark 必须伴随真实 script base，拒绝单独 mark 路由 [`rpg_engine/actions/taxonomy.py:245`]
- [x] [Review][Patch] 中文带第一人称主语否定前缀保持 non-saveable [`rpg_engine/intent_router.py:1345`]
- [x] [Review][Patch] English negative contractions 补齐 `needn't/daren't` [`rpg_engine/intent_router.py:1355`]
- [x] [Review][Patch] 中文通用 `不/没/未` 与第一人称计划否定保持 non-saveable [`rpg_engine/intent_router.py:1345`]
- [x] [Review][Patch] 日文礼貌禁止/否定与韩文正式完成否定形态保持 non-saveable [`rpg_engine/intent_router.py:1410`]
- [x] [Review][Patch] English contractions 同步接受 left quote 与 modifier apostrophe Unicode 变体 [`rpg_engine/intent_router.py:1355`]
- [x] [Review][Patch] craft 非目标语法泛化数量、周期、相对日期、地点/方式与日/韩 topic suffix [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] Kana iteration/prolonged modifiers 必须位于对应 script base 之后 [`rpg_engine/actions/taxonomy.py:235`]
- [x] [Review][Patch] Hangul script 校验拒绝无真实 base 的 filler-only executable term [`rpg_engine/actions/taxonomy.py:245`]
- [x] [Review][Patch] 中文礼貌/时间前缀否定与 `要不要/是否要` 选择问句保持 non-saveable [`rpg_engine/intent_router.py:1345`]
- [x] [Review][Patch] 日文常见礼貌/意愿否定及句尾语气助词保持 non-saveable [`rpg_engine/intent_router.py:1410`]
- [x] [Review][Patch] 韩文过去、意愿、命令等礼貌否定形态保持 non-saveable [`rpg_engine/intent_router.py:1440`]
- [x] [Review][Patch] English apostrophe-like Unicode 在 ingress/pre-normalized 两条路径统一为 contraction apostrophe [`rpg_engine/intent_router.py:1335`]
- [x] [Review][Patch] English polite modal question 支持句首 `please` [`rpg_engine/intent_router.py:1370`]
- [x] [Review][Patch] craft 非目标语法补齐 daily/weekend/location/ready 与日/韩频率/topic+time 形态 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] 中文礼貌、时间与主语前缀按常见顺序组合，覆盖否定和选择问句 [`rpg_engine/intent_router.py:1349`]
- [x] [Review][Patch] English `please` modal guard 接受逗号与破折号等安全分隔符 [`rpg_engine/intent_router.py:1370`]
- [x] [Review][Patch] English contraction ingress 补齐 Unicode PRIME apostrophe [`rpg_engine/intent_router.py:1333`]
- [x] [Review][Patch] 日文复合句尾语气助词与礼貌意愿否定保持 non-saveable [`rpg_engine/intent_router.py:1410`]
- [x] [Review][Patch] 日文 `するなら/すれば` 条件形保持 non-saveable [`rpg_engine/intent_router.py:1431`]
- [x] [Review][Patch] 韩文将来、请求、普通体与过去体否定保持 non-saveable [`rpg_engine/intent_router.py:1477`]
- [x] [Review][Patch] craft 非目标语法补齐 weekly/every weekend/on the weekend 频率与时间短语 [`rpg_engine/actions/base.py:236`]
- [x] [Review][Patch] 中文 safety 前缀补齐 `麻烦（你）` 礼貌否定组合 [`rpg_engine/intent_router.py:1349`]
- [x] [Review][Patch] English `please` modal guard 补齐冒号、分号与句点分隔 [`rpg_engine/intent_router.py:1373`]
- [x] [Review][Patch] 日文 safety grammar 补齐礼貌否定及 `すると/した場合/しなければ` 条件形 [`rpg_engine/intent_router.py:1431`]
- [x] [Review][Patch] 韩文 safety grammar 补齐基本体与正式将来否定 [`rpg_engine/intent_router.py:1490`]
- [x] [Review][Patch] craft 非目标语法泛化小时、周期副词、every/each 与 weekend/weekday 表达 [`rpg_engine/actions/base.py:229`]
- [x] [Review][Patch] craft grammar-only 后缀统一剥离 Unicode Mark/Punctuation/Symbol 边缘分隔符 [`rpg_engine/actions/base.py:281`]
- [x] [Review][Patch] executable script 校验拒绝前置 ideographic iteration mark 与混入真实 base 的 Hangul filler [`rpg_engine/actions/taxonomy.py:260`]
- [x] [Review][Patch] Kana/ideographic modifier 必须紧邻对应 script-bearing base [`rpg_engine/actions/taxonomy.py:245`]
- [x] [Review][Patch] punctuated Latin term 按首尾 Unicode word character 应用 identifier 外边界 [`rpg_engine/actions/taxonomy.py:460`]
- [x] [Review][Patch] executable script validator 拒绝跨脚本 combining mark，并要求 Bopomofo tone 紧邻兼容 base [`rpg_engine/actions/taxonomy.py:245`]
- [x] [Review][Patch] executable taxonomy 仅接受 Unicode 通用 combining blocks 与目标脚本专用 modifier [`rpg_engine/actions/taxonomy.py:264`]
- [x] [Review][Patch] 纯数字 executable term 不得通过 early return 携带任意 category-M modifier [`rpg_engine/actions/taxonomy.py:230`]
- [x] [Review][Patch] preflight context identity 绑定 active taxonomy digest，隔离 default/custom registry cached internal review [`rpg_engine/preflight_cache.py:689`]
- [x] [Review][Patch] 三路 clean 后从最终 clean diff 重跑并记录全部 required gates

## Dev Notes

### 当前可复现基线

- 当前 `HEAD` / `origin/main` 基线：`dbced868397e2bc165156d28450f33aa8e50a113`（Story 6.1）。
- 当前 deterministic router 能把“巡视”识别为 `routine`，但 `routine` resolver keywords、live manifest 和 internal prompt 均不包含“巡视”；manifest schema 为 v2，尚无独立 taxonomy identity。
- 可复现的 validation 基线命令：`python3 -m pytest -q tests/test_intent_manifest.py tests/test_p0_stop_loss_acceptance.py -p no:cacheprovider` → `16 passed, 14 subtests passed`；现有测试保护运行路由，但没有保护 registry/manifest/prompt parity。
- Root cause 是 resolver keywords、router private tables/inline tuples 与 prompt subset 三路并存，不是 Story 6.1 safety contract 的回归。

### 锁定实现边界

- `ActionResolverSpec` 持有不可变 per-action metadata，`ActionResolverRegistry` 持有唯一全局 version/projection/digest；在 `rpg_engine/actions/taxonomy.py` 放置无 AI 依赖的 leaf contract。
- Taxonomy 属于公开 provider contract，只能来自已注册 resolver 的 player-safe static metadata；不得从 hidden/GM-only runtime 内容或 `data/game.sqlite` 生成词项。
- Custom/campaign 的最小且唯一有规划证据的含义是“注册到 `ActionResolverRegistry` 的 custom spec”；本 Story 不发明 Campaign package loader、locale fallback/override 系统或动态插件。
- Candidate envelope 继续只携带 Story 6.1 的四个 identity 字段；taxonomy projection 被整体 manifest digest 覆盖，不新增外部 taxonomy authority。
- External/internal AI 是 low-trust candidate/advisory source；kernel registry、binder、resolver、preview、validation 与 explicit confirmation/commit 继续拥有最终权威。
- Story 6.3 才处理 resolved slot contract；不得顺手迁移 `ACTION_REQUIRED_SLOTS` 或 AI confirmation slots。

### 复用点与防重造

- 复用 `rpg_engine.ai_intent.safety_contract.canonical_json_sha256()`；如为依赖方向必须下沉 canonical JSON helper，应做单点迁移并保持 6.1 行为/测试，不复制算法。
- 复用 `build_intent_manifest(registry=...)` 的 custom registry seam 与现有 manifest full-payload digest。
- 复用 Story 6.1 `validate_external_intent_candidate()` 的 typed mismatch/refresh 行为，不新增平行 validator。
- MCP manifest 与 CLI action surface 已有 thin wrapper/render seam；应更新底层 owner，而不是在 surface 重新组装 taxonomy。
- `GMRuntime.action_registry` 已存在，必须贯通 route preparation、deterministic inference、AI router/binder、internal prompt、manifest 与 active contract validation；这仍不等于新增 Campaign runtime loader。

### Router 风险清单

- `contains_any()` 与 `text_has_any()` 当前匹配规则不同；集中化必须用测试锁定大小写、NFKC、Latin boundary 与 CJK substring。
- “盘点/inventory/audit”既是 routine synonym，又参与 composite inventory grammar；词面及 `inventory` role 来自 taxonomy，composite 结构判断仍属于 router。
- “找/搜索/检查/到”依赖可见实体类型或句法上下文；属于 router grammar，不得作为无条件 action synonym 导致误路由。
- 未识别具体 travel/social/gather/explore 不能因宽泛 taxonomy 回退成可保存 routine。
- Pure query、hidden/GM-only、maintenance 与 out-of-world 文本不能因词项扩展变成可执行 action。

### 预计文件范围

- NEW：`rpg_engine/actions/taxonomy.py`、`tests/test_action_taxonomy.py`。
- UPDATE：`rpg_engine/actions/base.py`、`registry.py`、`__init__.py`、九个 builtin resolver、`rpg_engine/runtime.py`、`rpg_engine/intent_router.py`、`rpg_engine/intent_manifest.py`、`rpg_engine/ai_intent/router.py`、`internal_review.py`、`prompts.py`、active contract validation 调用点及 focused tests/docs；以实际最小 diff 为准，但 injected registry 链路不得缺段。
- 通常不改：`rpg_engine/mcp_adapter.py`、`rpg_engine/cli.py`、candidate JSON schema、binder、pending/confirmation、DB/Campaign/Save schema。

### Testing Standards

- Focused：taxonomy、manifest、AI prompt/router、runtime/P0、MCP、CLI registry introspection。
- Adjacent：current-native player/context/visibility、entity access、eval suite、platform AI simulation、preflight/sidecar、CLI/surface inventory、bug regressions。
- Campaign：按仓库 canonical workflow 对 example/fixture 执行 validate/test，所有潜在写入必须在临时副本。
- Docs/static：Markdown links、Python compile/`py_compile`、full Ruff、`git diff --check`。
- Final：repository full pytest；只接受最后一轮 clean diff 上的新鲜结果。

### Project Structure Notes

- 新 taxonomy contract 放入 `rpg_engine/actions/`，保持依赖方向为 actions → manifest/router/prompt surfaces；不得让 actions leaf module 依赖 `ai_intent`。
- Public wire projection 必须由纯数据构成，顺序确定、JSON 可序列化，并且在不同注册顺序和 hash seed 下稳定。
- 不修改数据库 schema、Campaign YAML schema、formal Save、workspace registry 或 production API 来承载测试编排。
- 若发现需要新增依赖、改变 P0 mapping、引入 locale precedence/override 产品语义或扩大到 Hermes consumer 仓库，立即 HALT 并标记 decision-needed。

### References

- [Source: `_bmad-output/planning-artifacts/epics.md` — Epic 6 / Story 6.2]
- [Source: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-13.md` — D1、D7、Story 6.2 排期]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-recognition-chain-design-investigation.md` — taxonomy drift 与 owner 选择]
- [Source: `_bmad-output/implementation-artifacts/investigations/intent-mode-mismatch-mcp-call-investigation.md` — “巡视”P0 contract 边界]
- [Source: `_bmad-output/implementation-artifacts/6-1-strict-external-safety-vocabulary-and-version-negotiation.md` — manifest v2、canonical digest、stale refresh]
- [Source: `docs/project-context.md` — repository authority、Save/AI/hidden 边界]
- [Source: `docs/governance/bmad-workflow.md` — BMAD workflow 与 quality gates]
- [Source: `docs/ai-intent-chain.md` — deterministic/AI intent authority]
- [Source: `docs/prompt-contracts.md` — internal/external prompt contract]
- [Source: `docs/mcp-contracts.md` — live intent manifest 与 MCP authority]
- [Source: `docs/testing-and-quality-gates.md` — canonical verification]
- [Source: Python 3.11 `dataclasses` — https://docs.python.org/3.11/library/dataclasses.html]
- [Source: Python 3.11 `json` — https://docs.python.org/3.11/library/json.html]
- [Source: Python 3.11 `unicodedata` — https://docs.python.org/3.11/library/unicodedata.html]

## Dev Agent Record

### Agent Model Used

GPT-5 Codex

### Debug Log References

- Validate Story baseline：`16 passed, 14 subtests passed`。
- Task 1 RED：`tests/test_action_taxonomy.py` collection 因 taxonomy public contract 尚不存在而失败。
- Task 1 GREEN：`18 passed, 21 subtests passed`；开发期 full suite：`982 passed, 10084 subtests passed`。
- Task 2 RED：builtin locale/required terms、routine inventory role 与 registry introspection 共 13 项断言按预期失败。
- Task 2 GREEN：`18 passed, 58 subtests passed`；开发期 full suite：`985 passed, 10094 subtests passed`。
- Task 3 RED：router registry injection 与平行常量移除断言按预期失败。
- Task 3 convergence：修复“做什么”误触 craft、资源查找误触 social、`检查实体` 误触 routine 三个可复现回归；以 taxonomy playable/context roles 和原有分支优先级收敛。
- Task 3 GREEN：router/P0/runtime `131 passed, 112 subtests passed`，current-native focused `2 passed, 10 subtests passed`；开发期 full suite：`988 passed, 10094 subtests passed`。
- Task 4 RED：manifest v3/taxonomy projection/custom runtime chain 共 4 项断言按预期失败。
- Task 4 GREEN：focused `27 passed, 40 subtests passed`；intent/runtime/context adjacent `215 passed, 245 subtests passed`。
- Task 5 GREEN：最终 focused union `280 passed, 253 subtests passed`；两份 intent gold set `cmp` 一致。
- Dev convergence full suite：`991 passed, 10103 subtests passed`；Campaign 两套 validate/test 均 `OK`；Markdown links `189` files、py_compile、full Ruff 与 `git diff --check` 均通过。
- Review Round 1：三路 fresh review 共 16 条 raw findings，去重为 10 Patch、1 Defer、2 Dismiss；10 个 patch 全部应用。次生 inventory-role 回归由 focused snapshot 捕获并以 `template.inventory` role 收敛。
- Review Round 1 verification：focused/adjacent `324 passed, 292 subtests passed`；full suite `1000 passed, 10125 subtests passed`；Campaign、docs/static gates 全绿。
- Review Round 2：三路 fresh review 共 9 条 raw findings，去重为 7 Patch；全部复现并应用，0 Decision、0 Defer。Round 1 的“找/检查”Defer 经 baseline 逐词核验后更正为 Patch。
- Review Round 2 verification：taxonomy `29 passed, 45 subtests passed`；validation/response/proposal adjacent `48 passed, 139 subtests passed`；focused union 退出码 0；full suite `1006 passed, 10131 subtests passed`。
- Review Round 3：三路 fresh review 共 12 条 raw findings，去重为 6 Patch；全部复现并应用，0 Decision、0 Defer。
- Review Round 3 affected verification：taxonomy/runtime/validation/P0 `121 passed, 123 subtests passed`；Ruff、py_compile 与最小 Unicode probes 全绿。
- Review Round 3 post-patch full suite：`1006 passed, 10134 subtests passed`。
- Review Round 4：Acceptance Auditor clean；Blind/Edge 共 4 条净新 Patch，全部复现并应用；0 Decision、0 Defer。
- Review Round 4 affected verification：taxonomy/runtime/P0 `111 passed, 127 subtests passed`；Ruff 与 py_compile 全绿。
- Review Round 4 post-patch full suite：`1006 passed, 10138 subtests passed`。
- Review Round 5：Blind Hunter clean；Edge/Acceptance 共 4 条净新 Patch，全部复现并应用；0 Decision、0 Defer。
- Review Round 5 affected verification：taxonomy/manifest/AI/runtime/P0 `199 passed, 268 subtests passed`；Ruff 与 py_compile 全绿。
- Review Round 5 post-patch full suite：`1006 passed, 10144 subtests passed`。
- Review Round 6：三路共 6 条 raw findings，去重为 5 Patch；4 个代码/测试 patch 已复现并应用，final clean-diff gate patch 待 review clean 后执行；0 Decision、0 Defer。
- Review Round 6 affected verification：taxonomy/runtime/P0/AI `189 passed, 251 subtests passed`；Ruff 全绿。首次运行捕获并修复一处测试断言插入位置错误，fresh rerun 全绿。
- Review Round 6 post-patch full suite：`1007 passed, 10148 subtests passed`。
- Review Round 7：Blind Hunter 与 Acceptance Auditor clean；Edge Case Hunter 1 Patch，已复现并应用；0 Decision、0 Defer。
- Review Round 7 affected verification：runtime/taxonomy/P0 `113 passed, 137 subtests passed`；Ruff 全绿。两次初始断言分别识别了旧 UX 映射与单步 composite fixture 差异，收紧 production fail-closed 后 fresh rerun 全绿。
- Review Round 7 post-patch full suite：`1008 passed, 10148 subtests passed`。
- Review Round 8：Blind Hunter clean；Edge/Acceptance 共 4 条净新 Patch，全部复现并应用；0 Decision、0 Defer。
- Review Round 8 affected verification：taxonomy/runtime/context/low-level `155 passed, 194 subtests passed`；Ruff 全绿。首次运行识别自定义测试词项缺少 canonical `playable.craft` role，修正 fixture 后 fresh rerun 全绿。
- Review Round 8 post-patch full suite：`1012 passed, 10148 subtests passed`。
- Review Round 9：三路共 4 条 raw Patch findings，去重为 3 Patch；全部复现并应用，另有 2 条 duplicate/noise Dismiss；0 Decision、0 Defer。
- Review Round 9 affected verification：runtime/taxonomy/P0/AI/current-native `198 passed, 273 subtests passed`；Ruff 全绿。中间 focused run 捕获未覆盖的 `would/could` 假设形态，补齐泛化 guard 后 fresh rerun 全绿。
- Review Round 9 post-patch full suite：`1013 passed, 10158 subtests passed`。
- Review Round 10：三路共 9 条 raw Patch findings，去重为 7 Patch；全部复现并应用，0 Decision、0 Defer。
- Review Round 10 affected verification：runtime/taxonomy/P0/AI/current-native `199 passed, 285 subtests passed`；Ruff 全绿。首次 union 捕获 5 个 legacy trace/entity-query/meta-command 回归；未改旧快照掩盖问题，分层修复后定向 `9 passed, 66 subtests passed` 且 fresh union 全绿。
- Review Round 10 post-patch full suite：`1014 passed, 10170 subtests passed`。
- Review Round 11：三路共 8 条去重 Patch；全部复现并应用，0 Decision、0 Defer。
- Review Round 11 affected verification：runtime/taxonomy/P0/AI/current-native `199 passed, 290 subtests passed`；Ruff 全绿。两次初始 union 分别捕获 context-query 与 hidden hard-block 的宽 guard 回归，保留既有 gold 后 fresh rerun 全绿。
- Review Round 12：Blind Hunter 与 Acceptance Auditor 在随后被 root patch 失效的旧 snapshot 上 clean；Edge Case Hunter 在最新 snapshot 提交 2 Patch、1 Decision、0 Defer。两项 Patch 已复现；Decision 按 workflow 暂停并由用户选择推荐方案 A 后继续。
- Review Round 12 patch：拒绝纯标点/emoji taxonomy term；补齐日/韩无问号问句；live executable registry 对缺少 safety grammar 的 locale fail closed，而通用 projection 保留 BCP47-like 元数据能力。
- Review Round 12 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 308 subtests passed`；full Ruff 全绿。
- Review Round 13：三路共 7 条 raw Patch findings，去重为 6 Patch；0 Decision、0 Defer。Blind 发现日/韩尾随标点绕过；Edge 发现 locale script、裸 `か`、同名 custom action、craft 辅助语尾；Acceptance 重复同名 custom finding并补充 provenance finding。
- Review Round 13 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 312 subtests passed`；full Ruff 全绿。并发中间 full suite 的两项 visibility UDF 失败在 reviewers 全退出后以单进程精确复跑 `2 passed, 1084 subtests passed`，判定为并发干扰并 dismiss，未修改无关 redaction 范围。
- Review Round 14：三路共 7 条 raw Patch findings，按根因去重为 4 Patch；0 Decision、0 Defer。句尾 finding 由三路重复复现，script 与 craft finding 各由 Blind/Edge 重复复现；Edge 另发现安全语法未按命中 locale 分派。
- Review Round 14 targeted verification：首次运行识别 English completeness fixture 被放入日/韩 subset registry 的测试编排错误；迁回 default registry temporary Save 后 fresh taxonomy/runtime `114 passed, 173 subtests passed`，Ruff 全绿。
- Review Round 14 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 317 subtests passed`；full Ruff 全绿。
- Review Round 15：三路共 8 条 raw Patch findings，按根因去重为 4 Patch；0 Decision、0 Defer。三路重复复现 mixed-locale/actual-script、Unicode decoration 与 craft grammar；Blind 另发现 Bopomofo tone modifier 被 strict script validator 误拒。
- Review Round 15 targeted verification：taxonomy/runtime `114 passed, 173 subtests passed`；Ruff 全绿。
- Review Round 15 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 317 subtests passed`；full Ruff 全绿。
- Review Round 16：Acceptance Auditor clean；Blind/Edge 共 6 条 raw Patch findings，去重为 5 Patch；0 Decision、0 Defer。Bopomofo generic/legacy 分支分别修正，craft 时间 finding 去重；另补 English modal 与日文否定形态。
- Review Round 16 targeted verification：taxonomy/runtime `114 passed, 173 subtests passed`；Ruff 全绿。
- Review Round 16 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 317 subtests passed`；full Ruff 全绿。
- Review Round 17：Acceptance Auditor clean；Blind/Edge 共 8 条 raw Patch findings，去重为 7 Patch；0 Decision、0 Defer。English modal 与日文否定按共同 grammar 根因合并，其他 mixed-Bopomofo、craft、builtin 中文问句、日文问句、韩文语法均独立复现并修复。
- Review Round 17 targeted verification：首次运行确认 minimal Campaign 的 locked routine P0 正确路由为 `routine`，但因缺少上下文按 resolver 返回 `blocked`；修正测试断言为“不被问句 guard 改为 clarify”，fresh taxonomy/runtime/current-native P0 `115 passed, 177 subtests passed`，Ruff 全绿。
- Review Round 17 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 317 subtests passed`；full Ruff 全绿。
- Review Round 18：Acceptance Auditor clean；Blind/Edge 共 11 条 raw Patch findings，按 grammar 根因去重为 6 Patch；0 Decision、0 Defer。routine P0、English、日文、韩文、craft 与 Jpan iteration mark 均有独立复现。
- Review Round 18 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 180 subtests passed`；Ruff 全绿。
- Review Round 18 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 320 subtests passed`；full Ruff 全绿。
- Review Round 19：Acceptance Auditor clean；Blind/Edge 共 7 条 raw Patch findings，craft 时间 finding 去重后为 6 Patch；0 Decision、0 Defer。另修复日/韩 substring 边界、韩文正式问句、kana iteration base、中文主语否定与 English negative semi-modal。
- Review Round 19 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 191 subtests passed`；Ruff 全绿。
- Review Round 19 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 331 subtests passed`；full Ruff 全绿。
- Review Round 20：Acceptance Auditor clean；Blind/Edge 共 10 条 raw Patch findings，按中文/韩文/craft/kana 根因去重为 6 Patch；0 Decision、0 Defer。另补日文礼貌否定、Unicode apostrophe 与 Hangul filler meaningful-base。
- Review Round 20 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 205 subtests passed`；Ruff 全绿。
- Review Round 20 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 345 subtests passed`；full Ruff 全绿。
- Review Round 21：Acceptance Auditor clean；Blind/Edge 共 8 条 raw Patch findings，日文去重后为 7 Patch；0 Decision、0 Defer。首次 targeted run 识别 acute apostrophe 被上游预规范化为 combining mark，补齐 pre-normalized ingress；同时移除因 official Campaign `camp` direct entity hit 而不适用的 runtime fixture，仅保留 base helper gate。
- Review Round 21 targeted verification：精确 grammar/craft/P0 `36 passed, 107 subtests passed`，fresh taxonomy/runtime `114 passed, 202 subtests passed`；Ruff 全绿。
- Review Round 21 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 346 subtests passed`；full Ruff 全绿。
- Review Round 22：Acceptance Auditor clean；Blind/Edge 共 10 条 raw Patch findings，按中文前缀、English polite separator、Unicode apostrophe、日文否定、日文条件、韩文否定与 craft 时间语法去重为 7 Patch；全部复现并应用，0 Decision、0 Defer。
- Review Round 22 targeted verification：taxonomy/runtime/current-native P0 精确组合退出码 0；Ruff 全绿。
- Review Round 22 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 349 subtests passed`；full Ruff 全绿。
- Review Round 23：Acceptance Auditor clean；Blind/Edge 共 7 条 raw Patch findings，按中文礼貌前缀、English polite separator、日文句尾、韩文句尾与 craft 时间语法去重为 5 Patch；全部复现并按共同 grammar 根因应用，0 Decision、0 Defer。
- Review Round 23 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 217 subtests passed`；Ruff 全绿。
- Review Round 23 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 357 subtests passed`；full Ruff 全绿。
- Review Round 24：Blind Hunter 与 Acceptance Auditor clean；Edge Case Hunter 2 Patch，全部复现并应用；0 Decision、0 Defer。修复 grammar-only suffix 的通用 Unicode 边缘分隔，以及 ideographic iteration/Hangul filler 的可执行 script 校验根因。
- Review Round 24 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 223 subtests passed`；Ruff 全绿。
- Review Round 24 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 363 subtests passed`；full Ruff 全绿。
- Review Round 25：Blind Hunter 与 Acceptance Auditor clean；Edge Case Hunter 2 Patch，全部复现并应用；0 Decision、0 Defer。modifier 改为紧邻兼容 base 的通用不变量，punctuated Latin term 改为按首尾 Unicode word character 应用 identifier 外边界。
- Review Round 25 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 227 subtests passed`；Ruff 全绿。
- Review Round 25 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 367 subtests passed`；full Ruff 全绿。
- Review Round 26：Blind Hunter 与 Acceptance Auditor clean；Edge Case Hunter 1 Patch，已复现并应用；0 Decision、0 Defer。所有 combining/script modifier 改为按原始规范化字符序列校验相邻兼容 base 与显式脚本名称。
- Review Round 26 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 232 subtests passed`；Ruff 全绿。
- Review Round 26 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 372 subtests passed`；full Ruff 全绿。
- Review Round 27：Blind Hunter 与 Acceptance Auditor clean；Edge Case Hunter 1 Patch，已复现并应用；0 Decision、0 Defer。category-M 校验改用 Unicode 通用 combining blocks 正向 allowlist，并保留脚本名与相邻 base 不变量。
- Review Round 27 targeted verification：taxonomy/runtime/current-native P0 `115 passed, 234 subtests passed`；Ruff 全绿。
- Review Round 27 affected verification：taxonomy/runtime/AI/P0/current-native `219 passed, 374 subtests passed`；full Ruff 全绿。
- Review Round 28：Acceptance Auditor clean；Blind/Edge 各 1 Patch，共 2 Patch，全部复现并应用；0 Decision、0 Defer。纯数字 term modifier early-return 被关闭；preflight canonical context seed 纳入 active taxonomy digest，隔离 default/custom registry cache。
- Review Round 28 targeted verification：首次运行捕获一处手工 preflight fixture 未传新增 digest；补齐 temporary fixture 后 fresh taxonomy/preflight/runtime/current-native P0 `146 passed, 249 subtests passed`，Ruff 全绿。
- Review Round 28 affected verification：taxonomy/preflight/runtime/AI/P0/current-native `250 passed, 389 subtests passed`；full Ruff 全绿。
- Review Round 29：Blind Hunter、Edge Case Hunter、Acceptance Auditor 三路 fresh review 全部 clean；0 Patch、0 Decision、0 Defer。bounded probes 覆盖 taxonomy Unicode/script/boundary、registry 原子投影/digest、preflight taxonomy identity/injection、AC/File List/authority/save-hidden 边界。

### Implementation Plan

- 先建立中性 canonical JSON helper 与 frozen taxonomy leaf contract，再让 `ActionResolverSpec` 的 legacy 参数单向迁移到 canonical metadata。
- Registry 在写入前计算 prospective projection，以稳定 action/term 排序、normalized collision 与全局 digest 实现原子注册。
- 后续按 Story 顺序迁移 builtin terms/roles、router、manifest/prompt/injected-registry 链路，再补齐 docs 与最终 gates。

### Completion Notes List

- Create Story 完成：已生成完整中文开发上下文与 guardrails。
- Validate Story 完成：采用 `A1 B1 C1`，应用全部 12 项改进；两个 decision-needed 已由用户解除。
- Dev Story 完成：canonical taxonomy owner、builtin/router parity、manifest v3、internal prompt、custom registry 全链路、typed stale refresh 与 canonical docs 已实现。
- 权威边界保持不变：taxonomy 只含 player-safe static resolver metadata；AI 无事实/确认/commit authority；Story 6.3 slot ownership 未提前实现。
- Review Round 12 Decision 已由用户选择 A 解除：不扩大为 locale grammar plugin 系统，runtime 仅启用已有 grammar policy 覆盖的四个 language family。
- Review Round 29 三路 clean；29 轮共应用 131 个去重代码/文档 Patch，加最终 clean-diff gate Patch 共 132 个；无未决 Decision/Defer。
- Final focused：`PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q tests/test_action_taxonomy.py tests/test_intent_manifest.py tests/test_ai_intent.py tests/test_runtime.py tests/test_p0_stop_loss_acceptance.py tests/test_core_rule_condition_coverage.py tests/test_mcp_adapter.py tests/test_v1_cli.py -p no:cacheprovider` → `302 passed, 392 subtests passed`。
- Final adjacent：current-native context/player/visibility、preflight、platform、SaveManager、entity、surface/eval/transcript 与 cross-layer 16-file gate → `267 passed, 9287 subtests passed`。
- Final Campaign：`examples/v1_minimal_adventure` 与 `examples/small_cn_campaign` 的 `campaign validate` / `campaign test` 均 `OK`，init/health/smoke 全通过。
- Final docs/static：Markdown links `checked 189 markdown files; local links ok`；全仓 Python `py_compile`、full Ruff 与 `git diff --check` 均通过。
- Story/Sprint 状态同步后再次运行 Markdown links（`189` files）与 `git diff --check`，均通过。
- Final repository suite：`PYTHONDONTWRITEBYTECODE=1 uv run --extra dev python -m pytest -q -p no:cacheprovider` → `1016 passed, 10245 subtests passed`。
- `[CR] workflow.on_complete` resolver：`workflow.on_complete` 为空；Story 与 Sprint 同步为 `done`，Epic 6 因 6.3–6.8 仍为 backlog 保持 `in-progress`。

### File List

- `_bmad-output/implementation-artifacts/6-2-canonical-action-taxonomy-registry-projection.md`
- `_bmad-output/implementation-artifacts/deferred-work.md`
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `docs/ai-intent-chain.md`
- `docs/architecture.md`
- `docs/cli-contracts.md`
- `docs/component-inventory.md`
- `docs/mcp-contracts.md`
- `docs/prompt-contracts.md`
- `docs/prompts/ai-client-prompt.md`
- `docs/testing-and-quality-gates.md`
- `rpg_engine/actions/__init__.py`
- `rpg_engine/actions/base.py`
- `rpg_engine/actions/combat.py`
- `rpg_engine/actions/craft.py`
- `rpg_engine/actions/explore.py`
- `rpg_engine/actions/gather.py`
- `rpg_engine/actions/random_table.py`
- `rpg_engine/actions/registry.py`
- `rpg_engine/actions/rest.py`
- `rpg_engine/actions/routine.py`
- `rpg_engine/actions/social.py`
- `rpg_engine/actions/taxonomy.py`
- `rpg_engine/actions/travel.py`
- `rpg_engine/ai_intent/safety_contract.py`
- `rpg_engine/ai_intent/arbiter.py`
- `rpg_engine/ai_intent/binder.py`
- `rpg_engine/ai_intent/external.py`
- `rpg_engine/ai_intent/internal_review.py`
- `rpg_engine/ai_intent/normalization.py`
- `rpg_engine/ai_intent/prompts.py`
- `rpg_engine/ai_intent/router.py`
- `rpg_engine/canonical_json.py`
- `rpg_engine/context_builder.py`
- `rpg_engine/context/semantic.py`
- `rpg_engine/context/validation.py`
- `rpg_engine/intent_manifest.py`
- `rpg_engine/intent_router.py`
- `rpg_engine/proposal.py`
- `rpg_engine/preflight_cache.py`
- `rpg_engine/response_lint.py`
- `rpg_engine/runtime.py`
- `rpg_engine/validation_pipeline.py`
- `tests/test_ai_intent.py`
- `tests/test_action_taxonomy.py`
- `tests/test_intent_manifest.py`
- `tests/test_preflight_cache.py`
- `tests/test_runtime.py`

### Change Log

- 2026-07-13：实现 Story 6.2 canonical action taxonomy、manifest v3、injected registry 全链路与验证文档；状态转为 review。
- 2026-07-14：完成 29 轮三路 review 自动收敛、最终 required gates 与 BMAD 状态同步；状态转为 done。

## BMAD Provenance

- 用户触发：`bmad-story-cycle-auto with review subagents and apply every patch`；从指定
  `sprint-status.yaml` 选择 Epic 6 下一个 backlog Story，并授权持续收敛至 commit/push。
- Catalog chain：完整读取 `bmad-help` 后按 `_bmad/_config/bmad-help.csv` 路由：
  `[CS] bmad-create-story:create` → `[VS] bmad-create-story:validate` →
  `[DS] bmad-dev-story` → `[CR] bmad-code-review`。
- `[CS]/[VS]` skill：`.agents/skills/bmad-create-story/SKILL.md`，create 与 validate 两种模式均完整读取；
  resolver 命令为 `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/bmad-create-story --key workflow`，
  结果 prepend/append/on-complete 为空，persistent fact 为 `file:{project-root}/**/project-context.md`。
  加载 `_bmad/bmm/config.yaml`、`docs/project-context.md` 后，create 依次执行 embedded steps 1→6，
  再完整执行 `.agents/skills/bmad-create-story/checklist.md`；validate 使用同一 skill 的 validate catalog mode
  与 checklist。fresh validator 报告 4 Critical、5 Enhancement、3 Optimization，用户选择推荐 `A1 B1 C1`，全部吸收。
- `[DS]` skill：`.agents/skills/bmad-dev-story/SKILL.md` 与 `.agents/skills/bmad-dev-story/checklist.md` 均完整读取；
  resolver 命令为 `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/bmad-dev-story --key workflow`，
  同样解析为空 activation/on-complete + project-context persistent fact；加载 config/facts/context 后按 embedded
  steps 1→10 顺序执行，逐 task RED/GREEN/refactor、验证并转 `review`。
- `[CR]` skill：`.agents/skills/bmad-code-review/SKILL.md` 完整读取；resolver 命令为
  `python3 _bmad/scripts/resolve_customization.py --skill .agents/skills/bmad-code-review --key workflow`，
  解析结果同上；加载 config/facts/context 后依次完整读取并执行
  `steps/step-01-gather-context.md` → `step-02-review.md` → `step-03-triage.md` → `step-04-present.md`。
  每次 patch 后使用 fresh Blind Hunter、Edge Case Hunter、Acceptance Auditor 三路审查；Blind/Edge 分别使用
  `.agents/skills/bmad-review-adversarial-general/SKILL.md` 与 `.agents/skills/bmad-review-edge-case-hunter/SKILL.md`
  的只读 adversarial provenance，Acceptance 逐 AC/Task/File List/BMAD evidence 审计。
- 全阶段共同加载：Epic/PRD/architecture spines、Correct Course、Story 6.1、investigations、canonical docs、
  相关源码/测试与 recent git history；facts authority 始终为 `data/game.sqlite`，reviewers 无修改/确认/commit authority。
- 最终 clean-diff gates 的精确命令与结果记录在 Completion Notes；命令集为 story focused pytest、adjacent
  pytest、Campaign validate/test、Markdown links、`py_compile`、full Ruff、`git diff --check`、repository full pytest。
