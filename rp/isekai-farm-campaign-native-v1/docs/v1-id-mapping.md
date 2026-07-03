# V1 ID Migration Map

Status: draft mapping only. Do not apply automatically.

Purpose: keep the current native package playable while preparing a later semantic-ID migration. The IDs below remain active until campaign and save references are migrated together.

Migration rule: change one family at a time, keep old IDs as aliases during transition, run campaign/save validation after each batch, and do not rename IDs inside current save history without a dedicated migration script.

| Source File | Current ID | Type | Name | Proposed Semantic ID |
|---|---|---|---|---|
| `content/equipment.yaml` | `item:v1-00892107da` | `equipment` | 愈疮木旧弩 | `item:curewood-old-crossbow` |
| `content/equipment.yaml` | `item:v1-278674ee6e` | `equipment` | 愈疮木护臂×2 | `item:curewood-bracers-pair` |
| `content/equipment.yaml` | `item:v1-2e5154fd4c` | `equipment` | 铁木弩+矛+刀+甲片 | `item:ironwood-weapon-armor-bundle` |
| `content/equipment.yaml` | `item:v1-bb5662dae8` | `equipment` | 愈疮木护颈 | `item:curewood-neck-guard` |
| `content/items/ammunition.yaml` | `item:v1-9a74235657` | `item` | 竹箭（弓用） | `item:bamboo-arrows-bow` |
| `content/items/containers-and-mementos.yaml` | `item:v1-0b81d0d73c` | `item` | 竹水筒 | `item:bamboo-water-tube` |
| `content/items/containers-and-mementos.yaml` | `item:v1-5a357b56c5` | `item` | An的凿刻石板 | `item:an-carved-slate` |
| `content/items/containers-and-mementos.yaml` | `item:v1-638acf1712` | `item` | 竹杯 | `item:bamboo-cup` |
| `content/items/containers-and-mementos.yaml` | `item:v1-bfe6f6e71d` | `item` | 松塔（An赠） | `item:an-gift-pinecone` |
| `content/items/containers-and-mementos.yaml` | `item:v1-d9e3f1ce7b` | `item` | 母孢子树（夏娃菌核） | `item:mother-spore-tree-core` |
| `content/items/craft-materials.yaml` | `item:v1-0322977645` | `item` | 硬化残胶 | `item:slime-hardened-residue` |
| `content/items/craft-materials.yaml` | `item:v1-1767a0dfd3` | `item` | 乳白残液（矿物釉） | `item:milky-mineral-glaze` |
| `content/items/craft-materials.yaml` | `item:v1-18a38459f1` | `item` | 酸残胶（S1） | `item:acid-slime-residue-s1` |
| `content/items/craft-materials.yaml` | `item:v1-22e37e913c` | `item` | 根源菌丝 | `item:root-mycelium` |
| `content/items/craft-materials.yaml` | `item:v1-26667819cb` | `item` | 硝石针晶 | `item:niter-needle-crystals` |
| `content/items/craft-materials.yaml` | `item:v1-4681d8edfb` | `item` | 硫磺碎晶 | `item:sulfur-crystals` |
| `content/items/craft-materials.yaml` | `item:v1-515c3e4a2f` | `item` | 备用纤维绳 | `item:spare-fiber-rope` |
| `content/items/craft-materials.yaml` | `item:v1-5ae3d48ea9` | `item` | 荆棘藤 | `item:bramble-vine` |
| `content/items/craft-materials.yaml` | `item:v1-670a49c919` | `item` | 蛇纹石 | `item:serpentine-stone` |
| `content/items/craft-materials.yaml` | `item:v1-9852b22696` | `item` | 麻纤维 | `item:hemp-fiber` |
| `content/items/craft-materials.yaml` | `item:v1-9bb88c5944` | `item` | 普通残胶（S4） | `item:slime-neutral-residue-s4` |
| `content/items/craft-materials.yaml` | `item:v1-ac25ff32a4` | `item` | 湖边细纤维 | `item:lake-fine-fiber` |
| `content/items/craft-materials.yaml` | `item:v1-c1101bc083` | `item` | 优质燧石 | `item:quality-flint` |
| `content/items/craft-materials.yaml` | `item:v1-d1e0bf81d4` | `item` | 石英磨石 | `item:quartz-whetstone` |
| `content/items/craft-materials.yaml` | `item:v1-d88d8320cf` | `item` | 硫磺样本 | `item:sulfur-sample` |
| `content/items/food-and-kitchen.yaml` | `item:v1-0629e81966` | `item` | 野葱 | `item:wild-scallion` |
| `content/items/food-and-kitchen.yaml` | `item:v1-3a6b64e5c1` | `item` | 空心菜 | `item:water-spinach` |
| `content/items/food-and-kitchen.yaml` | `item:v1-7de3677e06` | `item` | 浆果醋 | `item:berry-vinegar` |
| `content/items/food-and-kitchen.yaml` | `item:v1-8182ae0835` | `item` | 红浆果 | `item:red-berries` |
| `content/items/food-and-kitchen.yaml` | `item:v1-88aed012b9` | `item` | 新鲜辣椒 | `item:fresh-chili` |
| `content/items/food-and-kitchen.yaml` | `item:v1-8aa915dbc4` | `item` | 蒜叶 | `item:garlic-leaves` |
| `content/items/food-and-kitchen.yaml` | `item:v1-a5ed98dd5e` | `item` | 生姜 | `item:ginger` |
| `content/items/food-and-kitchen.yaml` | `item:v1-b4fc16271b` | `item` | 松子仁 | `item:pine-nut-kernels` |
| `content/items/food-and-kitchen.yaml` | `item:v1-d409c6757a` | `item` | 红辣椒 | `item:red-chili` |
| `content/items/food-and-kitchen.yaml` | `item:v1-da43d4526b` | `item` | 紫苏 | `item:shiso` |
| `content/items/food-and-kitchen.yaml` | `item:v1-e247bca14a` | `item` | 生桐油 | `item:raw-tung-oil` |
| `content/items/food-and-kitchen.yaml` | `item:v1-e267e90894` | `item` | 苋菜大叶 | `item:amaranth-leaves` |
| `content/items/food-and-kitchen.yaml` | `item:v1-f07d297448` | `item` | 红叶生菜 | `item:redleaf-lettuce` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-147943e323` | `item` | 🌲 直脊杉 | `item:straight-spine-fir-sample` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-2f16f97815` | `item` | 驱虫草 | `item:insect-repellent-herb` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-33e843dea4` | `item` | 蜂巢菇 | `item:honeycomb-mushroom` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-3ff3e8ec4d` | `item` | 回声花 | `item:echo-flower` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-51622cf688` | `item` | 星辰草 | `item:star-herb` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-5224f28cd2` | `item` | 晶化菇 | `item:crystallized-mushroom` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-810cb2033c` | `item` | 霜叶 | `item:frostleaf` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-ad42a74d20` | `item` | 止血草 | `item:hemostatic-herb` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-cba23af8e3` | `item` | 退热根 | `item:fever-root` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-d7379c8908` | `item` | 纯化花 | `item:purification-flower` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-e0ad1e8f81` | `item` | 消炎草 | `item:anti-inflammatory-herb` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-e154966caa` | `item` | 月露草 | `item:moon-dew-grass` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-e494d4c06f` | `item` | 雷苔 | `item:thunder-moss` |
| `content/items/herbs-and-magic-plants.yaml` | `item:v1-e7996a2e98` | `item` | 月光苔 | `item:moonlight-moss` |
| `content/projects.yaml` | `project:v1-1d1f3d242a` | `project` | 竹箭杆→愈疮木杆全面升级 | `project:curewood-arrow-shaft-upgrade` |
| `content/projects.yaml` | `project:v1-3ebed921cd` | `project` | 愈疮木重箭杆 | `project:curewood-heavy-bolt-shafts` |
| `content/projects.yaml` | `project:v1-4150f6481e` | `project` | 渊刺藤毒刺替代 | `project:abyss-thorn-substitution` |
| `content/projects.yaml` | `project:v1-4c859eaa91` | `project` | 毒箭效力 | `project:poison-arrow-effectiveness` |
| `content/projects.yaml` | `project:v1-569a730495` | `project` | 见血封喉树恢复 | `project:antiaris-recovery` |
| `content/projects.yaml` | `project:v1-a793ab2ec9` | `project` | 农作物生长 | `project:crop-growth` |
| `content/references.yaml` | `ref:v1-3ac9e73b42` | `reference` | 战斗参考·武器威力对比（估算） | `ref:combat-weapon-power-estimate` |
| `content/references.yaml` | `ref:v1-6b9e0a537e` | `reference` | 死亡森林·地形剖面（东西向） | `ref:death-forest-east-west-profile` |
| `content/references.yaml` | `ref:v1-7199ba25ca` | `reference` | 死亡森林·地理位置 | `ref:death-forest-geography` |
| `content/references.yaml` | `ref:v1-74142750b3` | `reference` | 死亡森林·资源分布 | `ref:death-forest-resource-map` |
| `content/references.yaml` | `ref:v1-9d3e541d09` | `reference` | 死亡森林·气候特征（第1-3天观察） | `ref:death-forest-climate-day-001-003` |
| `content/references.yaml` | `ref:v1-a94116e788` | `reference` | 死亡森林·生态观察 | `ref:death-forest-ecology-observation` |
| `content/references.yaml` | `ref:v1-b929be7b4e` | `reference` | 死亡森林·土壤 | `ref:death-forest-soil` |
| `content/references.yaml` | `ref:v1-d8e86538af` | `reference` | 战斗参考·毒箭杀伤链 | `ref:combat-poison-bolt-kill-chain` |
| `content/species.yaml` | `creature:v1-31e9c69edd` | `species` | 核心（核）解剖数据 | `species:slime-core-dissection` |
| `content/species.yaml` | `creature:v1-bd9c1ff382` | `species` | 鸟类 | `species:forest-birds-observation` |

Total mapped IDs: 68.
